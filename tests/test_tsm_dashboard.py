from __future__ import annotations

import json
import math
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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
        self.assertEqual([exhibit["n"] for exhibit in exhibits], list(range(2, 10)))
        self.assertEqual(len({exhibit["n"] for exhibit in exhibits}), 8)
        self.assertTrue(all(not exhibit.get("full", False) for exhibit in exhibits))
        bridge = next(exhibit for exhibit in exhibits if exhibit["n"] == 6)
        self.assertEqual(bridge["values"], [28.83, 32.63, 63.2])
        self.assertIn("出售及盯市", bridge["src_extra"])

    def test_derived_summary_cells_are_marked(self) -> None:
        rows = self.payload["summary"]["blocks"][0]["rows"]
        for row in rows:
            self.assertTrue(all(cell["status"] == "derived" for cell in row["cells"][3:]))
        free_cash = next(row for row in rows if row["label"] == "自由现金流")
        self.assertTrue(all(cell["status"] == "derived" for cell in free_cash["cells"]))

    def test_sources_are_official_http_links(self) -> None:
        allowed_hosts = {"investor.tsmc.com", "www.sec.gov"}
        for source in self.payload["source_links"]:
            parsed = urlparse(source["url"])
            self.assertEqual(parsed.scheme, "https")
            self.assertIn(parsed.hostname, allowed_hosts)

    def test_published_payload_roster_and_shell(self) -> None:
        self.assertEqual(js_payload(ROOT / "data" / "tsm.js", "window.DASH"), self.payload)
        roster = js_payload(ROOT / "data" / "roster.js", "window.ROSTER")
        self.assertEqual({item["slug"] for item in roster["items"]}, {"googl", "tsm"})
        self.assertEqual(
            {group["key"] for group in roster["groups"]},
            {"internet", "semiconductor_ai"},
        )
        shell = (ROOT / "tsm" / "index.html").read_text(encoding="utf-8")
        self.assertIn('../data/tsm.js', shell)
        self.assertNotIn('../data/googl.js', shell)
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="googl/"', home)
        self.assertIn('href="tsm/"', home)

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
