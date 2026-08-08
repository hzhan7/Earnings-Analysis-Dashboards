from __future__ import annotations

import json
import math
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.all import roster_payload  # noqa: E402
from build.board import STATUS_LABELS  # noqa: E402
from build.googl import build_payload as build_googl_payload  # noqa: E402
from build.tsm import build_payload  # noqa: E402


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


class TsmDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "tsm.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)

    def test_all_historical_series_have_eight_quarters(self) -> None:
        self.assertEqual(len(self.source["periods"]), 8)
        for section in [
            "financials",
            "technology_mix_pct",
            "platform_mix_pct",
            "cash_flow_ntd_bn",
            "working_capital_days",
            "revenue_guidance_history_usd_bn",
        ]:
            for name, values in self.source[section].items():
                self.assertEqual(len(values), 8, f"{section}.{name}")
                self.assertTrue(all(math.isfinite(value) for value in values), f"{section}.{name}")

    def test_key_source_values_and_formulas(self) -> None:
        financials = self.source["financials"]
        snapshot = self.source["current_snapshot"]
        self.assertEqual(financials["revenue_usd_bn"][-1], 40.20)
        self.assertEqual(financials["gross_margin_pct"][-1], 67.7)
        self.assertEqual(financials["operating_margin_pct"][-1], 60.3)
        self.assertEqual(self.source["technology_mix_pct"]["2nm"][-1], 3)
        self.assertEqual(self.source["platform_mix_pct"]["hpc"][-1], 66)

        cash = self.source["cash_flow_ntd_bn"]
        for operating, capex, free_cash in zip(
            cash["operating_cash_flow"], cash["capital_expenditures"], cash["free_cash_flow"]
        ):
            self.assertAlmostEqual(round(operating - capex, 2), free_cash, places=2)

        vis_gain = snapshot["vis_disposal_and_mark_to_market_gain_pretax_ntd_bn"]
        self.assertEqual(round(snapshot["non_operating_items_ntd_bn"][0] - vis_gain, 2), 32.63)

    def test_guidance_history_is_not_overstated(self) -> None:
        history = self.source["revenue_guidance_history_usd_bn"]
        at_or_above_high = 0
        for low, high, actual in zip(history["low"], history["high"], history["actual"]):
            midpoint = (low + high) / 2
            self.assertGreaterEqual(actual, midpoint)
            at_or_above_high += int(actual >= high)
        self.assertEqual(at_or_above_high, 6)
        self.assertLess(history["actual"][1], history["high"][1])  # Q4'24 remained in range.

    def test_expected_exhibit_order_and_quality_bridge(self) -> None:
        exhibits = [exhibit for section in self.payload["sections"] for exhibit in section["exhibits"]]
        self.assertEqual([exhibit["n"] for exhibit in exhibits], list(range(2, 11)))
        self.assertTrue(all(not exhibit.get("full", False) for exhibit in exhibits))
        bridge = next(exhibit for exhibit in exhibits if exhibit["n"] == 7)
        self.assertEqual(bridge["values"], [28.83, 32.63, 63.2])
        self.assertIn("出售及盯市", bridge["src_extra"])

    def test_implied_asp_reproduces_reported_revenue(self) -> None:
        """Implied ASP is the only number on the page that is not a reported
        level, so it has to invert back to the reported revenue exactly."""
        scale = next(
            group for group in self.payload["panel"]["groups"] if group["id"] == "trend_scale"
        )
        asp_row = next(row for row in scale["rows"] if row["label"] == "隐含 ASP")
        self.assertTrue(all(cell["status"] == "derived" for cell in asp_row["cells"]))
        for index, cell in enumerate(asp_row["cells"]):
            asp = float(cell["v"].lstrip("$").replace(",", ""))
            shipments = self.source["financials"]["wafer_shipments_kpcs_12in_equiv"][index]
            revenue = self.source["financials"]["revenue_usd_bn"][index]
            self.assertAlmostEqual(asp * shipments / 1_000_000, revenue, places=1)

    def test_tracking_board_rows_carry_threshold_and_action(self) -> None:
        blocks = self.payload["summary"]["blocks"]
        self.assertEqual([block["id"] for block in blocks], ["tracking"])
        board = blocks[0]
        self.assertEqual(len(board["rows"]), 8)
        known = {f"st st-{key}" for key in STATUS_LABELS}
        for row in board["rows"]:
            self.assertEqual(len(row["cells"]), len(board["heads"]))
            self.assertTrue(row["cells"][1]["v"].strip())
            self.assertTrue(row["cells"][2]["v"].strip())
            self.assertIn(row["cells"][3]["cls"], known)
        capex_row = next(row for row in board["rows"] if row["label"] == "收入增速 vs CapEx 增速")
        self.assertEqual(capex_row["cells"][3]["cls"], "st st-hit")

    def test_panel_groups_are_rectangular(self) -> None:
        panel = self.payload["panel"]
        self.assertEqual(
            [group["id"] for group in panel["groups"]],
            [
                "trend_scale",
                "trend_margin",
                "trend_mix",
                "trend_cash",
                "trend_guidance",
                "quarter_detail",
            ],
        )
        for group in panel["groups"]:
            for row in group["rows"]:
                self.assertEqual(len(row["cells"]), len(group["heads"]), f"{group['id']}/{row['label']}")
        for group in panel["groups"][:5]:
            self.assertEqual(len(group["heads"]), 8)

    def test_cross_page_table_is_identical_on_both_pages(self) -> None:
        googl_source = json.loads((ROOT / "series" / "googl.json").read_text(encoding="utf-8"))
        googl = build_googl_payload(googl_source)
        self.assertEqual(self.payload["tables"][0]["rows"], googl["tables"][0]["rows"])
        self.assertEqual(self.payload["tables"][0]["headers"], googl["tables"][0]["headers"])

    def test_sources_are_official_http_links(self) -> None:
        allowed_hosts = {"investor.tsmc.com", "www.sec.gov"}
        for source in self.payload["source_links"]:
            parsed = urlparse(source["url"])
            self.assertEqual(parsed.scheme, "https")
            self.assertIn(parsed.hostname, allowed_hosts)

    def test_published_payload_roster_and_shell(self) -> None:
        self.assertEqual(js_payload(ROOT / "data" / "tsm.js", "window.DASH"), self.payload)
        # roster.js is loaded by every company page, so a stale one -- the exact
        # result of rebuilding one company instead of running build/all.py --
        # corrupts the cross-company nav on all of them. Assert equality, not
        # just the slug set.
        googl_source = json.loads((ROOT / "series" / "googl.json").read_text(encoding="utf-8"))
        roster = js_payload(ROOT / "data" / "roster.js", "window.ROSTER")
        self.assertEqual(roster, roster_payload(build_googl_payload(googl_source), self.payload))
        shell = (ROOT / "tsm" / "index.html").read_text(encoding="utf-8")
        self.assertIn('../data/tsm.js', shell)
        self.assertNotIn('../data/googl.js', shell)
        self.assertIn('id="panel"', shell)

    def test_home_page_matches_roster(self) -> None:
        """index.html is hand-written and reads no payload, so it can silently
        keep advertising last quarter while the company pages move on."""
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        roster = js_payload(ROOT / "data" / "roster.js", "window.ROSTER")
        for item in roster["items"]:
            self.assertIn(f'href="{item["slug"]}/"', home)
            self.assertIn(item["latest_label"], home)
            self.assertIn(item["release_date"], home)

    def test_public_files_exclude_private_and_broker_material(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [
                ROOT / "series" / "tsm.json",
                ROOT / "data" / "tsm.js",
                ROOT / "tsm" / "index.html",
            ]
        ).lower()
        for forbidden in [
            "/users/",
            "/library/cloudstorage/",
            "onedrive",
            "seeking alpha",
            "alphastreet",
            "factset",
            "bloomberg",
            "yahoo finance",
            "谨慎多",
        ]:
            self.assertNotIn(forbidden, text)
        compact = "".join(text.split())
        self.assertNotIn(":nan", compact)
        self.assertNotIn(":infinity", compact)
        self.assertNotIn(":-infinity", compact)


if __name__ == "__main__":
    unittest.main()
