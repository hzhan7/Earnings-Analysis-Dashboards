from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import headroom  # noqa: E402
from build.googl import build_payload, parse_number  # noqa: E402


class GooglePageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads((ROOT / "series" / "googl.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.staging)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]

    def test_currency_sign_parsing(self) -> None:
        self.assertEqual(parse_number("-$5,855M"), -5855)
        self.assertEqual(parse_number("($5,855M)"), -5855)
        self.assertEqual(parse_number("$5,855M"), 5855)

    def test_page_is_chart_led(self) -> None:
        """The page replaces a slide deck, so the lead modules are charts.  A
        table creeping back above the charts is the regression to catch."""
        self.assertEqual(self.payload["summary"]["blocks"], [])
        self.assertIsNone(self.payload["guidance"])
        self.assertEqual([ex["n"] for ex in self.exhibits], list(range(2, 15)))
        for exhibit in self.exhibits:
            self.assertTrue(exhibit.get("kind"), exhibit["n"])
            self.assertTrue(exhibit.get("note"), f"exhibit {exhibit['n']} has no explanation")

    def test_section_order_matches_how_the_note_is_used(self) -> None:
        self.assertEqual(
            [(section["id"], len(section["exhibits"])) for section in self.payload["sections"]],
            [("settled", 1), ("quarter_highlights", 6), ("next_quarter", 1), ("routine", 5)],
        )

    def test_headroom_bars_reproduce_the_thresholds(self) -> None:
        """Exhibit 2 and 9 normalise mixed units into one axis, so the mapping
        back to the source thresholds has to be exact."""
        for exhibit_number, block, value_key in [
            (2, "prior_kpi_settlement", "actual"),
            (9, "next_kpi", "current"),
        ]:
            entries = self.staging[block]["quantified"]
            exhibit = next(ex for ex in self.exhibits if ex["n"] == exhibit_number)
            self.assertEqual(exhibit["kind"], "diverging_bars")
            self.assertEqual(exhibit["xlabels"], [entry["metric"] for entry in entries])
            for entry, plotted in zip(entries, exhibit["values"]):
                expected = headroom(entry["direction"], entry["threshold"], entry[value_key])
                self.assertAlmostEqual(plotted, round(expected, 1), places=6, msg=entry["metric"])

    def test_only_the_cash_line_broke_last_quarter(self) -> None:
        settled = next(ex for ex in self.exhibits if ex["n"] == 2)
        breached = [
            label for label, value in zip(settled["xlabels"], settled["values"]) if value < 0
        ]
        self.assertEqual(breached, ["TTM 自由现金流"])

    def test_market_expectation_is_labelled_and_unattributed(self) -> None:
        """Consensus is publishable here only as an unattributed, dated figure."""
        text = json.dumps(self.payload, ensure_ascii=False)
        self.assertIn("市场预期", text)
        for broker in ["FactSet", "Bloomberg", "LSEG", "Visible Alpha", "consensus"]:
            self.assertNotIn(broker.lower(), text.lower())
        expectation = self.staging["market_expectation"]
        self.assertEqual(expectation["as_of"], "2026-07-22")
        eps_exhibit = next(ex for ex in self.exhibits if ex["n"] == 8)
        self.assertEqual(eps_exhibit["values"][-1], expectation["operating_eps_mid"])

    def test_backlog_exhibit_keeps_the_net_add_collapse_visible(self) -> None:
        backlog = next(ex for ex in self.exhibits if ex["n"] == 5)
        self.assertEqual(backlog["bar"]["values"], [240, 462, 514])
        self.assertEqual(backlog["line"]["values"], [None, 222, 52])
        self.assertIn("TPU", backlog["note"])

    def test_audit_tables_back_every_derived_exhibit(self) -> None:
        tables = {table["n"]: table for table in self.payload["tables"]}
        self.assertEqual(sorted(tables), [15, 16, 17, 18, 19, 20])
        self.assertIn("AI capex", tables[20]["title"])
        self.assertEqual(len(tables[20]["rows"]), 8)
        # Thresholds must also be readable in their original units.
        self.assertEqual(
            len(tables[15]["rows"]), len(self.staging["prior_kpi_settlement"]["quantified"])
        )
        self.assertEqual(len(tables[16]["rows"]), len(self.staging["next_kpi"]["quantified"]))

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

    def test_ttm_free_cash_flow_discrepancy_stays_flagged(self) -> None:
        """The source table's y/y for TTM FCF does not reconcile with its own
        Q2 2025 column.  The page must keep saying so rather than quietly
        publishing whichever number looks tidier."""
        self.assertTrue(any("待回源核对" in note for note in self.payload["notes"]))


if __name__ == "__main__":
    unittest.main()
