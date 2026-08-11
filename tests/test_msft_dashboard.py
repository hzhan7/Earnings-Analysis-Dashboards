"""Checks for the MSFT page.

Two things here are worth pinning beyond the usual shape checks.  First the
calendar-quarter relabelling: this is the only company on the site whose fiscal
year is not the calendar year, so a page that quietly reverts to fiscal labels
would break every cross-company comparison without failing to render.  Second
the adjusted free-cash-flow arithmetic, which is the page's core claim and is
built from three separate disclosures that have to keep reconciling.
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
from build.msft import build_payload  # noqa: E402

WINDOW = 8


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


class MsftDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "msft.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]
        cls.by_section = {
            section["id"]: section["exhibits"] for section in cls.payload["sections"]
        }
        cls.q = cls.source["quarterly_usd_m"]
        cls.segments = cls.source["segments_usd_m"]
        cls.fy = cls.source["fiscal_year_usd_m"]

    def test_twelve_quarter_base_backs_every_yoy(self) -> None:
        self.assertEqual(len(self.source["periods"]), 12)
        for name, values in self.q.items():
            self.assertEqual(len(values), 12, name)
            # Depreciation is only tagged from FY2025 onwards; every other line
            # has to be complete or a y/y curve would start mid-axis.
            expected_nulls = 4 if name == "depreciation" else 0
            self.assertEqual(sum(value is None for value in values), expected_nulls, name)
            self.assertTrue(
                all(math.isfinite(value) for value in values if value is not None), name
            )
        for name, values in self.segments.items():
            if isinstance(values, list):
                self.assertEqual(len(values), WINDOW, name)
        self.assertEqual(len(self.source["azure_growth_cc_pct"]), WINDOW)

    def test_periods_are_calendar_quarters_not_fiscal_ones(self) -> None:
        """Q2 2026 has to mean the quarter ended 2026-06-30 on this page, the
        same three months every other company page calls Q2 2026."""
        self.assertEqual(self.payload["latest"]["disclosed_period_label"], "Q2 2026")
        self.assertEqual(self.payload["latest"]["period_end"], "2026-06-30")
        self.assertIn("FY2026 Q4", self.payload["latest"]["full_financial_period_label"])
        self.assertIn("FY2026 Q4", self.payload["subtitle"])
        self.assertTrue(
            any("自然年季度" in note for note in self.payload["notes"]),
            "the labelling convention must be stated on the page, not only in the source",
        )
        self.assertEqual(self.segments["periods"], self.source["periods"][-WINDOW:])

    def test_segments_add_back_to_the_consolidated_statements(self) -> None:
        revenue = self.source["periods"][-WINDOW:]
        for index, period in enumerate(revenue):
            offset = len(self.source["periods"]) - WINDOW + index
            self.assertEqual(
                self.segments["productivity_revenue"][index]
                + self.segments["intelligent_cloud_revenue"][index]
                + self.segments["more_personal_computing_revenue"][index],
                self.q["revenue_total"][offset],
                period,
            )
            self.assertEqual(
                self.segments["productivity_operating_income"][index]
                + self.segments["intelligent_cloud_operating_income"][index]
                + self.segments["more_personal_computing_operating_income"][index],
                self.q["operating_income"][offset],
                period,
            )

    def test_quarterly_series_reconcile_with_both_fiscal_years(self) -> None:
        """Fiscal years end in June, so each one is four consecutive calendar
        quarters of the twelve-quarter base; the two must agree exactly."""
        pairs = {
            "revenue_total": "revenue",
            "operating_income": "operating_income",
            "operating_cash_flow": "operating_cash_flow",
            "cash_paid_for_property_and_equipment": "cash_paid_for_property_and_equipment",
            "finance_lease_additions": "finance_lease_additions",
            "stock_repurchases": "stock_repurchases",
            "dividends_paid": "dividends_paid",
            "depreciation": "depreciation",
        }
        years = {"FY2025": slice(4, 8), "FY2026": slice(8, 12)}
        for quarterly_key, annual_key in pairs.items():
            for position, (label, window) in enumerate(years.items()):
                self.assertEqual(
                    sum(self.q[quarterly_key][window]),
                    self.fy[annual_key][position],
                    f"{label} {quarterly_key}",
                )

    def test_adjusted_free_cash_flow_arithmetic(self) -> None:
        """Reported free cash flow only counts capex that was paid. The adjusted
        line subtracts the year's increase in unpaid capex -- three disclosed
        numbers, no estimate -- and is the page's central claim."""
        reported = [
            operating - spend
            for operating, spend in zip(
                self.fy["operating_cash_flow"], self.fy["cash_paid_for_property_and_equipment"]
            )
        ]
        self.assertEqual(reported, [71611, 66987])
        unpaid = [self.fy["unpaid_capex_in_payables_prior"]] + self.fy["unpaid_capex_in_payables"]
        adjusted = [
            value - (unpaid[index + 1] - unpaid[index]) for index, value in enumerate(reported)
        ]
        self.assertEqual(adjusted, [69011, 47187])
        returns = [
            repurchase + dividend
            for repurchase, dividend in zip(self.fy["stock_repurchases"], self.fy["dividends_paid"])
        ]
        self.assertEqual(returns, [42502, 48716])
        coverage = [value / base * 100 for value, base in zip(returns, adjusted)]
        self.assertAlmostEqual(coverage[0], 61.6, places=1)
        self.assertAlmostEqual(coverage[1], 103.2, places=1)

        exhibit = next(ex for ex in self.exhibits if ex["kind"] == "grouped_bars")
        self.assertEqual(exhibit["xlabels"], self.fy["labels"])
        self.assertEqual([group["values"] for group in exhibit["groups"]],
                         [reported, adjusted, returns])

    def test_intelligent_cloud_gross_margin_is_derived_from_the_segment_note(self) -> None:
        chart = next(ex for ex in self.exhibits if "分部毛利率连降" in ex["title"])
        expected = [
            (revenue - cost) / revenue * 100
            for revenue, cost in zip(
                self.segments["intelligent_cloud_revenue"],
                self.segments["intelligent_cloud_cost_of_revenue"],
            )
        ]
        self.assertEqual(chart["values"], expected)
        # The whole point of the exhibit: five consecutive falls, then one rise.
        self.assertTrue(all(b < a for a, b in zip(expected[:-2], expected[1:-1])))
        self.assertGreater(expected[-1], expected[-2])

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
        settled = self.by_section["settled"][1]
        self.assertTrue(all(value >= 0 for value in settled["values"]))
        breached = {
            label
            for label, value in zip(
                self.by_section["next_quarter"][0]["xlabels"],
                self.by_section["next_quarter"][0]["values"],
            )
            if value < 0
        }
        self.assertEqual(breached, {"股东回报 / 调整后自由现金流"})

    def test_every_tracked_metric_with_a_series_gets_its_own_chart(self) -> None:
        charted = {ex["title"].split("：")[0] for ex in self.by_section["next_quarter"][1:]}
        tracked = {entry["metric"] for entry in self.source["next_kpi"]["quantified"]}
        # The last two are annual ratios built from the 10-K, not quarterly series.
        self.assertEqual(
            tracked - charted,
            {"股东回报 / 调整后自由现金流", "已签约未起租租约 / 年收入"},
        )
        for exhibit in self.by_section["next_quarter"][1:]:
            threshold = exhibit["series"][-1]["values"]
            self.assertEqual(len(set(threshold)), 1, exhibit["title"])
            self.assertEqual(len(threshold), WINDOW, exhibit["title"])

    def test_long_history_agrees_with_the_reviewed_quarters(self) -> None:
        """The ten-year series and the reviewed twelve must not disagree.

        Microsoft's fiscal fourth quarter is never filed on its own -- it is the
        year minus the nine-month year-to-date -- so this is also the check that
        the subtraction still lands on the number a human already reviewed.
        """
        long = self.source["long_history"]
        index = {quarter: i for i, quarter in enumerate(long["quarters"])}
        pairs = [
            ("revenue_usd_m", "revenue_total"),
            ("gross_profit_usd_m", "gross_profit"),
            ("operating_income_usd_m", "operating_income"),
            ("capital_expenditures_usd_m", "cash_paid_for_property_and_equipment"),
            ("operating_cash_flow_usd_m", "operating_cash_flow"),
            ("depreciation_usd_m", "depreciation"),
            ("finance_lease_additions_usd_m", "finance_lease_additions"),
        ]
        for long_key, reviewed_key in pairs:
            for period, expected in zip(self.source["periods"], self.q[reviewed_key]):
                quarter, year = period.split()
                got = long[long_key][index[f"{year}Q{quarter[1]}"]]
                self.assertEqual(got, expected, f"{long_key} {period}")

    def test_quarterly_depreciation_is_not_invented_before_disclosure(self) -> None:
        """Microsoft publishes depreciation annually far further back than it
        publishes it quarterly.  Spreading a year over four quarters would draw a
        curve the company never gave, so that chart keeps its short window and
        the page says why rather than leaving the reader to notice."""
        long = self.source["long_history"]
        quarters = long["quarters"]
        start = quarters.index(long["depreciation_first_reported"])
        self.assertTrue(all(v is None for v in long["depreciation_usd_m"][:start]))
        self.assertTrue(all(v is not None for v in long["depreciation_usd_m"][start:]))

        depreciation_chart = next(ex for ex in self.exhibits if "季度折旧" in ex["title"])
        self.assertEqual(len(depreciation_chart["xlabels"]), WINDOW)
        self.assertIn("只有这张没有", depreciation_chart["note"])

        # The other three routine charts did make it back to the start.
        routine = self.by_section["routine"]
        long_axes = [ex for ex in routine if len(ex["xlabels"]) > WINDOW]
        self.assertEqual(len(long_axes), 3)

    def test_finance_leases_are_never_added_to_cash_capex(self) -> None:
        """The two spending channels take different routes through the cash flow
        statement, so the page charts them separately and says why."""
        long = self.source["long_history"]
        capex_chart = next(ex for ex in self.exhibits if "资本强度" in ex["title"])
        lease_chart = next(ex for ex in self.exhibits if "融资租赁新增" in ex["title"])
        intensity = [
            round(spend / total * 100, 6)
            for spend, total in zip(long["capital_expenditures_usd_m"], long["revenue_usd_m"])
        ]
        self.assertEqual(
            [round(v, 6) for v in capex_chart["series"][0]["values"]], intensity
        )
        leases = long["finance_lease_additions_usd_m"]
        self.assertEqual(
            lease_chart["series"][0]["values"], [v for v in leases if v is not None]
        )
        self.assertIn("不把它与现金资本开支相加", lease_chart["src_extra"])
        # The two channels stay on separate charts: neither series may be the
        # sum of the two, which is the mistake the note exists to prevent.
        combined = [
            spend + (lease or 0)
            for spend, lease in zip(long["capital_expenditures_usd_m"], leases)
        ]
        self.assertNotEqual(lease_chart["series"][0]["values"], combined)

    def test_audit_tables_back_every_derived_exhibit(self) -> None:
        tables = self.payload["tables"]
        first = len(self.exhibits) + 2
        self.assertEqual([table["n"] for table in tables], list(range(first, first + len(tables))))
        self.assertIn("AI capex", tables[-1]["title"])
        self.assertEqual(
            len(tables[0]["rows"]), len(self.source["prior_kpi_settlement"]["quantified"])
        )
        self.assertEqual(len(tables[1]["rows"]), len(self.source["next_kpi"]["quantified"]))
        segment_table = next(t for t in tables if "分部收入" in t["title"])
        self.assertEqual(len(segment_table["rows"]), WINDOW)
        base_table = next(t for t in tables if "十二季度基础数据" in t["title"])
        self.assertEqual(len(base_table["rows"]), 12)

    def test_market_expectation_is_labelled_and_unattributed(self) -> None:
        text = json.dumps(self.payload, ensure_ascii=False)
        self.assertIn("市场预期", text)
        for broker in ["FactSet", "Bloomberg", "Seeking Alpha", "consensus", "Anthropic"]:
            self.assertNotIn(broker.lower(), text.lower())
        self.assertEqual(self.source["market_expectation"]["as_of"], "2026-07-29")
        # Two public sources disagree by $1.75B, so only the direction is published.
        self.assertIn("不发布超预期幅度", text)

    def test_sources_are_official_http_links(self) -> None:
        allowed_hosts = {"www.microsoft.com", "www.sec.gov"}
        for source in self.payload["source_links"]:
            parsed = urlparse(source["url"])
            self.assertEqual(parsed.scheme, "https")
            self.assertIn(parsed.hostname, allowed_hosts)

    def test_published_payload_and_shell(self) -> None:
        self.assertEqual(js_payload(ROOT / "data" / "msft.js", "window.DASH"), self.payload)
        shell = (ROOT / "msft" / "index.html").read_text(encoding="utf-8")
        self.assertIn("../data/msft.js", shell)
        self.assertNotIn("../data/tsm.js", shell)

    def test_public_files_exclude_private_and_broker_material(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [
                ROOT / "series" / "msft.json",
                ROOT / "data" / "msft.js",
                ROOT / "msft" / "index.html",
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
            "openai",
            "谨慎多",
        ]:
            self.assertNotIn(forbidden, text)
        compact = "".join(text.split())
        self.assertNotIn(":nan", compact)
        self.assertNotIn(":infinity", compact)
        self.assertNotIn(":-infinity", compact)


if __name__ == "__main__":
    unittest.main()
