from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import STATUS_LABELS  # noqa: E402
from build.googl import build_payload, parse_number  # noqa: E402


class GooglePageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads((ROOT / "series" / "googl.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.staging)

    def test_currency_sign_parsing(self) -> None:
        self.assertEqual(parse_number("-$5,855M"), -5855)
        self.assertEqual(parse_number("($5,855M)"), -5855)
        self.assertEqual(parse_number("$5,855M"), 5855)

    def test_expected_exhibit_order(self) -> None:
        exhibits = [ex for section in self.payload["sections"] for ex in section["exhibits"]]
        self.assertEqual([ex["n"] for ex in exhibits], list(range(2, 12)))
        self.assertTrue(all(not ex.get("full", False) for ex in exhibits))
        fcf = next(ex for ex in exhibits if ex["n"] == 8)
        self.assertEqual(fcf["values"][-1], -5855)

    def test_tracking_board_is_the_only_lead_block(self) -> None:
        blocks = self.payload["summary"]["blocks"]
        self.assertEqual([block["id"] for block in blocks], ["tracking"])
        board = blocks[0]
        self.assertEqual(len(board["rows"]), 8)
        known = {f"st st-{key}" for key in STATUS_LABELS}
        for row in board["rows"]:
            self.assertEqual(len(row["cells"]), len(board["heads"]))
            # Every row must carry a threshold and an action, or it is a metric
            # tile pretending to be a tracker.
            self.assertTrue(row["cells"][1]["v"].strip())
            self.assertTrue(row["cells"][2]["v"].strip())
            self.assertIn(row["cells"][3]["cls"], known)

    def test_board_numbers_reconcile_with_the_series(self) -> None:
        """The board may interpret, but it may not invent: each published value
        has to fall out of the same snapshot the panel prints."""
        rows = {row[0]: row for row in self.staging["snapshot"]["rows"]}
        revenue = parse_number(rows["总收入"][3])
        depreciation = parse_number(rows["折旧"][3])
        equity_gain = parse_number(rows["— 权益证券收益"][3])
        net_income = parse_number(rows["净利润（归属普通股）"][3])
        board = {row["label"]: row["cells"][0]["v"] for row in self.payload["summary"]["blocks"][0]["rows"]}
        self.assertIn(f"{depreciation / revenue * 100:.2f}%", board["折旧 / 收入"])
        self.assertIn(
            f"{equity_gain / net_income * 100:.1f}%",
            board["GAAP 净利润中权益证券收益占比"],
        )

    def test_panel_groups_are_rectangular(self) -> None:
        panel = self.payload["panel"]
        ids = [group["id"] for group in panel["groups"]]
        self.assertEqual(
            ids,
            [
                "trend_revenue",
                "trend_cash",
                "quarter_segments",
                "quarter_cost",
                "quarter_quality",
                "quarter_capital",
            ],
        )
        for group in panel["groups"]:
            for row in group["rows"]:
                self.assertEqual(len(row["cells"]), len(group["heads"]), f"{group['id']}/{row['label']}")
        trend = next(group for group in panel["groups"] if group["id"] == "trend_revenue")
        self.assertEqual(len(trend["heads"]), 8)

    def test_ttm_free_cash_flow_discrepancy_stays_flagged(self) -> None:
        """The source table's y/y for TTM FCF does not reconcile with its own
        Q2 2025 column.  The page must keep saying so rather than quietly
        publishing whichever number looks tidier."""
        capital = next(
            group for group in self.payload["panel"]["groups"] if group["id"] == "quarter_capital"
        )
        self.assertIn("待回源核对", capital["note"])

    def test_cross_page_table_is_published(self) -> None:
        tables = self.payload["tables"]
        self.assertEqual(len(tables), 1)
        self.assertIn("AI capex", tables[0]["title"])
        self.assertEqual(len(tables[0]["rows"]), 8)

    def test_published_payload_matches_builder(self) -> None:
        text = (ROOT / "data" / "googl.js").read_text(encoding="utf-8")
        body = text.split("window.DASH = ", 1)[1].rsplit(";", 1)[0]
        self.assertEqual(json.loads(body), self.payload)
        labels = {item["label"] for item in self.payload["source_links"]}
        self.assertIn("Q2 2026 Alphabet earnings call webcast", labels)

    def test_public_payload_excludes_restricted_material(self) -> None:
        text = json.dumps(self.payload, ensure_ascii=False).lower()
        for forbidden in [
            "谨慎多", "alphastreet", "yahoo finance", "bofa", "anthropic",
            "stockanalysis.com", "onedrive/",
        ]:
            self.assertNotIn(forbidden, text)
        self.assertNotIn("/users/", text)
        self.assertNotIn("/library/cloudstorage/", text)
        self.assertNotIn("$73,552m", text)
        self.assertNotIn("经营口径 eps", text)

    def test_derived_panel_cells_are_marked(self) -> None:
        segments = next(
            group for group in self.payload["panel"]["groups"] if group["id"] == "quarter_segments"
        )
        derived = {row["label"] for row in segments["rows"] if row["cells"][0]["status"] == "derived"}
        self.assertEqual(
            derived,
            {"广告收入合计", "Cloud OPM", "Services OPM", "经营利润率"},
        )
        for row in segments["rows"]:
            for cell in row["cells"][3:]:
                if cell["v"] != "—":
                    self.assertEqual(cell["status"], "derived")


if __name__ == "__main__":
    unittest.main()
