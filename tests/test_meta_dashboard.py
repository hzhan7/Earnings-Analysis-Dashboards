"""Checks for the META page.

The three things worth pinning here are the ones a quarter roll can silently
break: the revenue lines must still add back to the reported total, the
volume/price bridge must still close against reported advertising growth, and
the adjusted figures the thresholds are settled on must still match the numbers
actually plotted.  Everything else on the page is a chart of a reported series.
"""

from __future__ import annotations

import json
import math
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import headroom  # noqa: E402
from build.meta import build_payload  # noqa: E402

WINDOW = 8


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


class MetaDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "meta.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]
        cls.by_section = {
            section["id"]: section["exhibits"] for section in cls.payload["sections"]
        }
        cls.q = cls.source["quarterly_usd_m"]

    def test_twelve_quarter_base_backs_every_yoy(self) -> None:
        self.assertEqual(len(self.source["periods"]), 12)
        for name, values in self.q.items():
            self.assertEqual(len(values), 12, name)
            self.assertTrue(all(math.isfinite(value) for value in values), name)
        for name, values in self.source["advertising_metrics"].items():
            if isinstance(values, list):
                self.assertEqual(len(values), 12, name)

    def test_revenue_lines_add_back_to_the_reported_total(self) -> None:
        """Advertising is derived by subtraction, so it is only trustworthy if
        the three published lines reconstruct the reported total exactly."""
        table = next(t for t in self.payload["tables"] if "十二季度基础数据" in t["title"])
        self.assertEqual(len(table["rows"]), 12)
        for index, period in enumerate(self.source["periods"]):
            total = self.q["revenue_total"][index]
            parts = (
                self.q["reality_labs_revenue"][index] + self.q["foa_other_revenue"][index]
            )
            advertising = int(table["rows"][index][2].strip("$M D").replace(",", ""))
            self.assertEqual(advertising + parts, total, period)

    def test_income_statement_identity_holds_each_quarter(self) -> None:
        for index, period in enumerate(self.source["periods"]):
            derived = self.q["revenue_total"][index] - self.q["costs_and_expenses"][index]
            self.assertEqual(derived, self.q["operating_income"][index], period)

    def test_free_cash_flow_uses_the_company_definition(self) -> None:
        """META nets finance-lease principal inside free cash flow; using the
        plain OCF-minus-capex form would overstate the current quarter by
        roughly a billion dollars."""
        snapshot = self.source["current_snapshot"]
        derived = [
            operating - purchases - lease
            for operating, purchases, lease in zip(
                self.q["operating_cash_flow"],
                self.q["purchases_of_property_and_equipment"],
                self.q["finance_lease_principal"],
            )
        ]
        self.assertEqual(derived[-1], snapshot["free_cash_flow_usd_m"][0])
        self.assertEqual(derived[-2], snapshot["free_cash_flow_usd_m"][1])
        self.assertEqual(derived[-5], snapshot["free_cash_flow_usd_m"][2])
        capex = [
            purchases + lease
            for purchases, lease in zip(
                self.q["purchases_of_property_and_equipment"],
                self.q["finance_lease_principal"],
            )
        ]
        self.assertEqual(capex[-1], snapshot["capex_incl_finance_leases_usd_m"][0])
        self.assertEqual(capex[-2], snapshot["capex_incl_finance_leases_usd_m"][1])

    def test_quarterly_series_reconcile_with_the_full_year(self) -> None:
        """The fourth quarter of each year is a subtraction from the annual
        report, so it has to add back to the disclosed full-year figures."""
        fy2025 = self.source["fy2025_actuals_usd_m"]
        year = slice(6, 10)  # Q1 2025 .. Q4 2025
        self.assertEqual(sum(self.q["revenue_total"][year]), fy2025["revenue"])
        self.assertEqual(
            sum(self.q["share_based_compensation"][year]), fy2025["share_based_compensation"]
        )
        self.assertEqual(
            sum(self.q["depreciation_and_amortization"][year]),
            fy2025["depreciation_and_amortization"],
        )
        self.assertEqual(
            sum(self.q["purchases_of_property_and_equipment"][year]),
            fy2025["purchases_of_property_and_equipment"],
        )
        self.assertEqual(
            sum(self.q["finance_lease_principal"][year]), fy2025["finance_lease_principal"]
        )
        # Operating income is reported to the nearest million in each filing, so
        # the quarterly sum lands within a rounding unit of the 10-K figure.
        self.assertLessEqual(
            abs(sum(self.q["operating_income"][year]) - fy2025["operating_income"]), 1
        )

    def test_volume_price_bridge_closes_against_reported_growth(self) -> None:
        """The page's central claim -- the deceleration is entirely volume -- is
        only defensible while impressions x price still reproduces advertising
        growth. Published rounding is to whole percent, so 1.2pp is the slack."""
        ads = self.source["advertising_metrics"]
        advertising = [
            total - reality - other
            for total, reality, other in zip(
                self.q["revenue_total"],
                self.q["reality_labs_revenue"],
                self.q["foa_other_revenue"],
            )
        ]
        for index in range(4, len(advertising)):
            product = (
                (1 + ads["ad_impressions_yoy_pct"][index] / 100)
                * (1 + ads["price_per_ad_yoy_pct"][index] / 100)
                - 1
            ) * 100
            actual = (advertising[index] / advertising[index - 4] - 1) * 100
            self.assertLess(
                abs(product - actual),
                1.2,
                f"{self.source['periods'][index]}: bridge {product:.1f}% vs actual {actual:.1f}%",
            )

    def test_page_is_chart_led(self) -> None:
        self.assertEqual(self.payload["summary"]["blocks"], [])
        self.assertIsNone(self.payload["guidance"])
        self.assertEqual(
            [ex["n"] for ex in self.exhibits], list(range(2, 2 + len(self.exhibits)))
        )
        for exhibit in self.exhibits:
            self.assertTrue(exhibit.get("kind"), exhibit["n"])
            self.assertTrue(exhibit.get("note"), f"exhibit {exhibit['n']} has no explanation")
            self.assertTrue(exhibit.get("src_extra"), f"exhibit {exhibit['n']} has no source line")

    def test_section_order_matches_how_the_note_is_used(self) -> None:
        self.assertEqual(
            [(section["id"], len(section["exhibits"])) for section in self.payload["sections"]],
            [("settled", 4), ("quarter_highlights", 6), ("next_quarter", 5), ("routine", 4)],
        )

    def test_headroom_bars_reproduce_the_thresholds(self) -> None:
        for section, block, key in (
            ("settled", "prior_kpi_settlement", "actual"),
            ("next_quarter", "next_kpi", "current"),
        ):
            entries = self.source[block]["quantified"]
            exhibit = next(
                ex for ex in self.by_section[section] if ex["kind"] == "diverging_bars"
            )
            self.assertEqual(exhibit["xlabels"], [entry["metric"] for entry in entries])
            for entry, plotted in zip(entries, exhibit["values"]):
                expected = headroom(entry["direction"], entry["threshold"], entry[key])
                self.assertAlmostEqual(plotted, round(expected, 1), places=6, msg=entry["metric"])
        breached = {
            label
            for label, value in zip(
                self.by_section["next_quarter"][0]["xlabels"],
                self.by_section["next_quarter"][0]["values"],
            )
            if value < 0
        }
        self.assertEqual(
            breached, {"同比增量经营利润率", "FoA Other 单季收入", "单季经营利润 vs FY2025 季均线"}
        )

    def test_every_tracked_metric_with_a_series_gets_its_own_chart(self) -> None:
        charted = {ex["title"].split("：")[0] for ex in self.by_section["next_quarter"][1:]}
        tracked = {entry["metric"] for entry in self.source["next_kpi"]["quantified"]}
        # The capex guidance midpoint is a three-point revision history, not a
        # quarterly series; it gets its own chart in the highlights section.
        self.assertEqual(tracked - charted, {"FY2026 CapEx 指引中点"})
        for exhibit in self.by_section["next_quarter"][1:]:
            threshold = exhibit["series"][-1]["values"]
            self.assertEqual(len(set(threshold)), 1, exhibit["title"])
            self.assertEqual(len(threshold), WINDOW, exhibit["title"])

    def test_adjusted_lines_match_the_value_the_threshold_is_settled_on(self) -> None:
        """Two thresholds are settled on the adjusted basis while the plotted
        history is GAAP. If the short adjusted line drifts from the stated
        current value, the chart contradicts its own caption."""
        snapshot = self.source["current_snapshot"]
        revenue = self.q["revenue_total"]
        operating_income = self.q["operating_income"]
        adjusted = snapshot["adjusted_operating_income_usd_m"]
        self.assertEqual(
            adjusted,
            snapshot["operating_income_usd_m"][0]
            + snapshot["legal_proceedings_charge_usd_m"]
            + snapshot["severance_charge_usd_m"],
        )

        margin_chart = next(ex for ex in self.by_section["settled"] if "经营利润率" in ex["title"])
        tail = margin_chart["series"][1]
        self.assertEqual(tail["values"][-1], round(adjusted / revenue[-1] * 100, 2))
        self.assertEqual(tail["values"][-2], round(margin_chart["series"][0]["values"][-2], 2))
        self.assertEqual(tail["values"][:-2], [None] * (WINDOW - 2))

        incremental_chart = next(
            ex for ex in self.by_section["next_quarter"] if "增量经营利润率" in ex["title"]
        )
        expected = (adjusted - operating_income[-5]) / (revenue[-1] - revenue[-5]) * 100
        self.assertEqual(incremental_chart["series"][1]["values"][-1], round(expected, 2))
        entry = next(
            item for item in self.source["next_kpi"]["quantified"]
            if item["metric"] == "同比增量经营利润率"
        )
        self.assertAlmostEqual(entry["current"], expected, places=1)

    def test_audit_tables_back_every_derived_exhibit(self) -> None:
        tables = self.payload["tables"]
        first = len(self.exhibits) + 2
        self.assertEqual([table["n"] for table in tables], list(range(first, first + len(tables))))
        self.assertIn("AI capex", tables[-1]["title"])
        self.assertEqual(
            len(tables[0]["rows"]), len(self.source["prior_kpi_settlement"]["quantified"])
        )
        self.assertEqual(len(tables[1]["rows"]), len(self.source["next_kpi"]["quantified"]))
        ad_table = next(t for t in tables if "广告量价" in t["title"])
        self.assertEqual(len(ad_table["rows"]), 12)

    def test_market_expectation_is_labelled_and_unattributed(self) -> None:
        text = json.dumps(self.payload, ensure_ascii=False)
        self.assertIn("市场预期", text)
        for broker in ["FactSet", "Bloomberg", "Visible Alpha", "Seeking Alpha", "consensus"]:
            self.assertNotIn(broker.lower(), text.lower())
        self.assertEqual(self.source["market_expectation"]["as_of"], "2026-07-29")
        # The post-earnings move is published as the range the sources disagree
        # over, never as a single number picked from one of them.
        self.assertIn("7%–11%", self.payload["headline"])

    def test_sources_are_official_http_links(self) -> None:
        allowed_hosts = {"investor.atmeta.com", "www.sec.gov"}
        for source in self.payload["source_links"]:
            parsed = urlparse(source["url"])
            self.assertEqual(parsed.scheme, "https")
            self.assertIn(parsed.hostname, allowed_hosts)

    def test_published_payload_and_shell(self) -> None:
        self.assertEqual(js_payload(ROOT / "data" / "meta.js", "window.DASH"), self.payload)
        shell = (ROOT / "meta" / "index.html").read_text(encoding="utf-8")
        self.assertIn("../data/meta.js", shell)
        self.assertNotIn("../data/googl.js", shell)

    def test_public_files_exclude_private_and_broker_material(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [
                ROOT / "series" / "meta.json",
                ROOT / "data" / "meta.js",
                ROOT / "meta" / "index.html",
            ]
        ).lower()
        for forbidden in [
            "/users/",
            "/library/cloudstorage/",
            "onedrive",
            "seeking alpha",
            "factset",
            "bloomberg",
            "anthropic",
            "谨慎多",
        ]:
            self.assertNotIn(forbidden, text)
        compact = "".join(text.split())
        self.assertNotIn(":nan", compact)
        self.assertNotIn(":infinity", compact)
        self.assertNotIn(":-infinity", compact)


if __name__ == "__main__":
    unittest.main()
