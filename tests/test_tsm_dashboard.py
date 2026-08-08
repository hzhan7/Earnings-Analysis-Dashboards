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
from build.board import headroom  # noqa: E402
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
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]
        cls.by_section = {
            section["id"]: section["exhibits"] for section in cls.payload["sections"]
        }

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

        bridge = self.source["net_income_bridge"]["values_ntd_bn"]
        self.assertAlmostEqual(bridge[0] - bridge[1], bridge[2], places=2)
        self.assertEqual(bridge[1], snapshot["vis_disposal_and_mark_to_market_gain_pretax_ntd_bn"])

    def test_guidance_history_is_not_overstated(self) -> None:
        history = self.source["revenue_guidance_history_usd_bn"]
        at_or_above_high = 0
        for low, high, actual in zip(history["low"], history["high"], history["actual"]):
            midpoint = (low + high) / 2
            self.assertGreaterEqual(actual, midpoint)
            at_or_above_high += int(actual >= high)
        self.assertEqual(at_or_above_high, 6)
        self.assertLess(history["actual"][1], history["high"][1])  # Q4'24 remained in range.

    def test_page_is_chart_led(self) -> None:
        self.assertEqual(self.payload["summary"]["blocks"], [])
        self.assertIsNone(self.payload["guidance"])
        self.assertEqual(
            [ex["n"] for ex in self.exhibits], list(range(2, 2 + len(self.exhibits)))
        )
        for exhibit in self.exhibits:
            self.assertTrue(exhibit.get("kind"), exhibit["n"])
            self.assertTrue(exhibit.get("note"), f"exhibit {exhibit['n']} has no explanation")

    def test_section_order_matches_how_the_note_is_used(self) -> None:
        self.assertEqual(
            [(section["id"], len(section["exhibits"])) for section in self.payload["sections"]],
            [("settled", 4), ("quarter_highlights", 7), ("next_quarter", 6), ("routine", 4)],
        )

    def test_implied_asp_reproduces_reported_revenue(self) -> None:
        """Implied ASP is the only plotted series that is not a reported level,
        so it has to invert back to reported revenue exactly."""
        exhibit = next(ex for ex in self.exhibits if "隐含 ASP" in ex["title"])
        asp = exhibit["yoy"]["values"]
        for index, value in enumerate(asp):
            shipments = self.source["financials"]["wafer_shipments_kpcs_12in_equiv"][index]
            revenue = self.source["financials"]["revenue_usd_bn"][index]
            self.assertAlmostEqual(value * shipments / 1_000_000, revenue, places=6)
        self.assertEqual(exhibit["values"], self.source["financials"]["wafer_shipments_kpcs_12in_equiv"])

    def test_headroom_bars_reproduce_the_thresholds(self) -> None:
        entries = self.source["next_kpi"]["quantified"]
        exhibit = self.by_section["next_quarter"][0]
        self.assertEqual(exhibit["kind"], "diverging_bars")
        self.assertEqual(exhibit["xlabels"], [entry["metric"] for entry in entries])
        for entry, plotted in zip(entries, exhibit["values"]):
            expected = headroom(entry["direction"], entry["threshold"], entry["current"])
            self.assertAlmostEqual(plotted, round(expected, 1), places=6, msg=entry["metric"])
        breached = [
            label for label, value in zip(exhibit["xlabels"], exhibit["values"]) if value < 0
        ]
        self.assertEqual(breached, ["2nm 占晶圆收入"])

    def test_every_tracked_metric_with_a_series_gets_its_own_chart(self) -> None:
        charted = {
            exhibit["title"].split("：")[0] for exhibit in self.by_section["next_quarter"][1:]
        }
        tracked = {entry["metric"] for entry in self.source["next_kpi"]["quantified"]}
        # The spot FX rate has no published quarterly series to plot against.
        self.assertEqual(tracked - charted, {"USD/TWD 即期（升值为逆风）"})
        for exhibit in self.by_section["next_quarter"][1:]:
            line = exhibit["series"][1]["values"]
            self.assertEqual(len(set(line)), 1, exhibit["title"])
            self.assertEqual(len(line), len(exhibit["series"][0]["values"]), exhibit["title"])

    def test_dollar_capex_backs_the_intensity_and_growth_charts(self) -> None:
        """CapEx is reported in NT$ but the intensity ratio and the growth
        crossover both need US$ on each side, so the dollar series has to carry
        four extra quarters and reconcile with the NT$ one."""
        block = self.source["capital_expenditures_usd_bn"]
        self.assertEqual(len(block["values"]), 12)
        self.assertEqual(len(block["periods"]), 12)
        self.assertEqual(block["periods"][-8:], self.source["periods"])
        ntd = self.source["cash_flow_ntd_bn"]["capital_expenditures"]
        for usd, nt in zip(block["values"][-8:], ntd):
            self.assertTrue(28.0 < nt / usd < 34.0, f"implied FX {nt / usd:.1f}")
        intensity = next(
            ex for ex in self.exhibits if ex["title"].startswith("资本强度八季")
        )
        for index, value in enumerate(intensity["values"]):
            expected = (
                block["values"][-8:][index]
                / self.source["financials"]["revenue_usd_bn"][index] * 100
            )
            self.assertAlmostEqual(value, expected, places=6)
        crossover = next(ex for ex in self.exhibits if "反超收入增速" in ex["title"])
        self.assertEqual(
            crossover["series"][0]["values"], self.source["financials"]["revenue_yoy_pct"]
        )
        self.assertEqual(len(crossover["series"][1]["values"]), 8)
        self.assertTrue(all(v is not None for v in crossover["series"][1]["values"]))

    def test_capex_threshold_is_converted_and_marked(self) -> None:
        """The CapEx line is tracked in US$ but reported in NT$, so the plotted
        threshold must be the converted value and must say so."""
        exhibit = next(ex for ex in self.by_section["next_quarter"][1:] if "CapEx" in ex["title"])
        rate = self.source["guidance"]["q2_actual"]["usd_ntd"]
        self.assertEqual(exhibit["series"][1]["values"][0], round(19.0 * rate, 1))
        self.assertIn("按本季实际汇率", exhibit["note"])
        self.assertIn("D", exhibit["note"])

    def test_market_expectation_is_labelled_and_unattributed(self) -> None:
        text = json.dumps(self.payload, ensure_ascii=False)
        self.assertIn("市场预期", text)
        for broker in ["FactSet", "Bloomberg", "LSEG", "QUICK", "consensus"]:
            self.assertNotIn(broker.lower(), text.lower())
        self.assertEqual(self.source["market_expectation"]["as_of"], "2026-07-16")

    def test_audit_tables_back_every_derived_exhibit(self) -> None:
        tables = self.payload["tables"]
        first = len(self.exhibits) + 2
        self.assertEqual([table["n"] for table in tables], list(range(first, first + 7)))
        self.assertIn("AI capex", tables[-1]["title"])
        self.assertEqual(len(tables[1]["rows"]), len(self.source["next_kpi"]["quantified"]))
        financials = next(table for table in tables if "隐含 ASP" in table["title"])
        for row in financials["rows"]:  # implied ASP travels with the raw inputs
            self.assertTrue(row[-1].endswith("D"))

    def test_cross_page_table_is_identical_on_both_pages(self) -> None:
        googl_source = json.loads((ROOT / "series" / "googl.json").read_text(encoding="utf-8"))
        googl = build_googl_payload(googl_source)
        mine = next(table for table in self.payload["tables"] if "AI capex" in table["title"])
        theirs = next(table for table in googl["tables"] if "AI capex" in table["title"])
        self.assertEqual(mine["rows"], theirs["rows"])
        self.assertEqual(mine["headers"], theirs["headers"])

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
