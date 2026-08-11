"""Reconciliation and shape tests for the NVDA page.

The point of this file is the same as the other companies': nothing derived
reaches the page until it has been checked against a statement identity or a
figure the company disclosed separately. NVDA adds one identity the other pages
do not have -- the operating-income beat decomposition -- and one hazard they do
not have either: a non-GAAP definition that changed mid-record, which is only
safe because every guidance/actual pair sits on one side of the change.
"""

from __future__ import annotations

import json
import math
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.all import build_all, roster_payload  # noqa: E402
from build.board import headroom  # noqa: E402
from build.nvda import build_payload, compact_period  # noqa: E402


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


class NvdaDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "nvda.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]
        cls.by_section = {
            section["id"]: section["exhibits"] for section in cls.payload["sections"]
        }

    # ── shape ────────────────────────────────────────────────────────────────
    def test_all_historical_series_have_eight_quarters(self) -> None:
        self.assertEqual(len(self.source["periods"]), 8)
        for group in [
            "financials",
            "market_platform_usd_m",
            "data_center_split_usd_m",
            "cash_flow_usd_m",
            "working_capital",
        ]:
            for name, values in self.source[group].items():
                if not isinstance(values, list) or name == "filed_split_quarters":
                    continue
                self.assertEqual(len(values), 8, f"{group}.{name}")
                self.assertTrue(
                    all(value is not None and math.isfinite(value) for value in values),
                    f"{group}.{name}",
                )

    def test_the_guided_record_is_one_row_per_quarter(self) -> None:
        guide = self.source["quarterly_guidance_history"]
        length = len(guide["quarters"])
        self.assertEqual(length, 24)
        for name, values in guide.items():
            self.assertEqual(len(values), length, name)
        # The record ends on a quarter that has been guided but not reported;
        # everything before it must be complete.
        self.assertIsNone(guide["actual_revenue_usd_m"][-1])
        self.assertTrue(all(value is not None for value in guide["actual_revenue_usd_m"][:-1]))
        self.assertEqual(guide["quarters"][-1], "Q2 2026")
        # The eight-quarter window is the tail of the guided record.
        self.assertEqual(guide["quarters"][-9:-1], self.source["periods"])

    def test_quarters_are_contiguous_calendar_labels(self) -> None:
        for quarters in (self.source["quarterly_guidance_history"]["quarters"],
                         self.source["long_history"]["quarters"]):
            numbers = []
            for label in quarters:
                quarter, year = label.split()
                numbers.append(int(year) * 4 + int(quarter[1]) - 1)
            self.assertEqual(numbers, list(range(numbers[0], numbers[0] + len(numbers))),
                             quarters[:3])

    # ── identities the filings have to satisfy ───────────────────────────────
    def test_data_center_sub_markets_sum_to_the_filed_total(self) -> None:
        """Hyperscale + ACIE = Data Center, every quarter.

        Five of the eight sub-market splits are NVIDIA's restatement as recorded
        in the local analysis note rather than a cell in a filing this repo
        read; this identity is what makes them publishable, because the Data
        Center total on the right-hand side was read from that quarter's own 8-K.
        """
        platform = self.source["market_platform_usd_m"]
        for index, period in enumerate(self.source["periods"]):
            self.assertEqual(
                platform["hyperscale"][index] + platform["acie"][index],
                platform["data_center"][index],
                period,
            )

    def test_edge_computing_is_revenue_less_data_center(self) -> None:
        platform = self.source["market_platform_usd_m"]
        revenue = self.source["financials"]["revenue_usd_m"]
        for index, period in enumerate(self.source["periods"]):
            self.assertEqual(
                platform["edge_computing"][index],
                revenue[index] - platform["data_center"][index],
                period,
            )
        # The one quarter NVIDIA filed an Edge Computing line, it agrees.
        self.assertEqual(platform["edge_computing"][-1], 6369)

    def test_compute_and_networking_sum_to_data_center(self) -> None:
        """Within the US$0.1B the company rounds those two lines to."""
        split = self.source["data_center_split_usd_m"]
        platform = self.source["market_platform_usd_m"]
        for index, period in enumerate(self.source["periods"]):
            total = split["compute"][index] + split["networking"][index]
            self.assertLess(abs(total - platform["data_center"][index]), 110, period)

    def test_the_operating_income_decomposition_is_an_identity(self) -> None:
        """actual − implied = revenue leg + margin leg + opex leg, exactly.

        This is the claim Exhibit 7 makes in its own note, so it is checked here
        rather than trusted: if the three legs ever stop adding up, the chart is
        asserting something arithmetic that is not true.
        """
        guide = self.source["quarterly_guidance_history"]
        for index, quarter in enumerate(guide["quarters"]):
            if guide["actual_revenue_usd_m"][index] is None:
                continue
            guided_revenue = guide["guide_revenue_usd_bn"][index] * 1000
            guided_margin = guide["non_gaap_gm_guide_pct"][index] / 100
            guided_opex = guide["non_gaap_opex_guide_usd_bn"][index] * 1000
            actual_revenue = guide["actual_revenue_usd_m"][index]
            actual_margin = guide["actual_non_gaap_gm_pct"][index] / 100
            actual_opex = guide["actual_non_gaap_opex_usd_m"][index]
            implied = guided_revenue * guided_margin - guided_opex
            actual = guide["actual_non_gaap_operating_income_usd_m"][index]
            legs = (
                (actual_revenue - guided_revenue) * guided_margin
                + actual_revenue * (actual_margin - guided_margin)
                - (actual_opex - guided_opex)
            )
            # US$1M of slack: NVIDIA computes its own non-GAAP subtotal off
            # unrounded components, so its printed operating income can differ
            # by a dollar-million from the two rounded lines above it.
            self.assertLess(abs(legs - (actual - implied)), 1.01, quarter)

    def test_reported_margins_reproduce_from_the_dollar_lines(self) -> None:
        long = self.source["long_history"]
        for index, quarter in enumerate(long["quarters"]):
            self.assertGreater(long["gaap_gross_margin_pct"][index], 0, quarter)
            self.assertLess(long["gaap_gross_margin_pct"][index], 100, quarter)
            self.assertAlmostEqual(
                long["gaap_operating_margin_pct"][index]
                + long["opex_intensity_pct"][index],
                long["gaap_gross_margin_pct"][index],
                places=2,
                msg=quarter,
            )

    # ── figures the filings state outright ───────────────────────────────────
    def test_key_source_values_match_the_filings(self) -> None:
        financials = self.source["financials"]
        platform = self.source["market_platform_usd_m"]
        working = self.source["working_capital"]
        cash = self.source["cash_flow_usd_m"]
        self.assertEqual(financials["revenue_usd_m"][-1], 81615)
        self.assertEqual(financials["revenue_usd_m"][-2], 68127)
        self.assertEqual(financials["gaap_operating_income_usd_m"][-1], 53536)
        self.assertEqual(financials["non_gaap_operating_income_usd_m"][-1], 53783)
        self.assertEqual(platform["data_center"][-1], 75246)
        self.assertEqual(platform["hyperscale"][-1], 37869)
        self.assertEqual(platform["acie"][-1], 37377)
        self.assertEqual(working["dso_days"][-1], 45)
        self.assertEqual(working["inventories_usd_m"][-1], 25797)
        self.assertEqual(working["accounts_receivable_usd_m"][-1], 40710)
        self.assertEqual(cash["free_cash_flow"][-1], 48554)
        self.assertEqual(cash["operating_cash_flow"][-1], 50344)
        # Rounded percentages the company printed in the same release.
        self.assertAlmostEqual(financials["gaap_gross_margin_pct"][-1], 74.9, places=1)
        self.assertAlmostEqual(financials["non_gaap_gross_margin_pct"][-1], 75.0, places=1)

    def test_current_guidance_matches_the_outlook_paragraph(self) -> None:
        guide = self.source["guidance"]["q2_new"]
        self.assertEqual(guide["revenue_usd_bn"], 91.0)
        self.assertEqual(guide["revenue_band_pct"], 2.0)
        self.assertEqual(guide["non_gaap_gross_margin_pct"], 75.0)
        self.assertEqual(guide["non_gaap_opex_usd_bn"], 8.3)
        history = self.source["quarterly_guidance_history"]
        pending = history["quarters"].index("Q2 2026")
        self.assertEqual(history["guide_revenue_usd_bn"][pending], 91.0)
        self.assertEqual(history["non_gaap_opex_guide_usd_bn"][pending], 8.3)

    def test_the_restatement_is_recorded_not_smoothed(self) -> None:
        """Q4 2025's non-GAAP EPS is the restated $1.59, and the page says so.

        Publishing $1.62 next to $1.87 would overstate the quarter's sequential
        improvement; publishing $1.59 without saying it was restated would look
        like a typo against every contemporaneous source.
        """
        restated = self.source["restated_comparatives"]
        self.assertEqual(restated["quarters"], ["Q1 2026", "Q4 2025", "Q1 2025"])
        self.assertEqual(restated["non_gaap_eps_usd"], [1.87, 1.59, 0.78])
        self.assertIn("1.62", restated["note"])
        self.assertTrue(
            any("1.62" in note for note in self.payload["notes"]),
            "the restatement is not disclosed in the page notes",
        )

    def test_equity_gains_explain_the_gaap_wedge(self) -> None:
        restated = self.source["restated_comparatives"]
        self.assertEqual(restated["equity_securities_gains_usd_m"][0], 15936)
        # A year ago equity securities were a net loss, so GAAP sat below
        # non-GAAP; that reversal is the point of Exhibit 14.
        self.assertLess(restated["equity_securities_gains_usd_m"][2], 0)
        self.assertLess(restated["gaap_net_income_usd_m"][2],
                        restated["non_gaap_net_income_usd_m"][2])
        self.assertGreater(restated["gaap_net_income_usd_m"][0],
                           restated["non_gaap_net_income_usd_m"][0])

    # ── page assembly ────────────────────────────────────────────────────────
    def test_exhibits_are_numbered_in_render_order(self) -> None:
        numbers = [exhibit["n"] for exhibit in self.exhibits]
        self.assertEqual(numbers, list(range(2, 2 + len(numbers))))
        table_numbers = [table["n"] for table in self.payload["tables"]]
        self.assertEqual(table_numbers[0], numbers[-1] + 1)
        self.assertEqual(table_numbers, list(range(table_numbers[0],
                                                   table_numbers[0] + len(table_numbers))))

    def test_no_unresolved_cross_reference_placeholders(self) -> None:
        blob = json.dumps(self.payload, ensure_ascii=False)
        self.assertNotIn("{EX_", blob)
        self.assertNotIn('"ref"', blob)

    def test_chart_titles_are_plain_text(self) -> None:
        """Titles are injected unescaped and reused in each card's aria-label."""
        for exhibit in self.exhibits:
            self.assertNotIn("<", exhibit["title"], exhibit["title"])

    def test_every_chart_carries_a_note_and_a_source_line(self) -> None:
        for exhibit in self.exhibits:
            self.assertTrue(exhibit.get("note"), exhibit["title"])
            self.assertTrue(exhibit.get("src_extra"), exhibit["title"])

    def test_tracked_metrics_get_their_own_chart_and_the_rest_are_named(self) -> None:
        """A threshold with a plottable series gets a chart; one without is disclosed."""
        next_charts = self.by_section["next_quarter"]
        quantified = self.source["next_kpi"]["quantified"]
        # One overview bar plus one chart per metric that has an eight-quarter
        # series. 存货 + 供应承诺 has only two disclosed points, so it is not
        # plotted -- and the overview has to say so.
        self.assertEqual(len(next_charts), 1 + 4)
        plotted = " ".join(chart["title"] for chart in next_charts[1:])
        for entry in quantified:
            if entry["metric"] == "存货 + 供应承诺":
                self.assertNotIn(entry["metric"], plotted)
            else:
                self.assertIn(entry["metric"], plotted)
        self.assertIn("Vera Rubin", next_charts[0]["src_extra"])
        self.assertIn("中国", next_charts[0]["src_extra"])

    def test_headroom_signs_follow_the_threshold_direction(self) -> None:
        overview = self.by_section["next_quarter"][0]
        for entry, value in zip(self.source["next_kpi"]["quantified"], overview["values"]):
            self.assertAlmostEqual(
                value,
                round(headroom(entry["direction"], entry["threshold"], entry["current"]), 1),
                places=1,
                msg=entry["metric"],
            )
        # The two share metrics sit just under their milestone this quarter and
        # must read negative; the risk metrics all have room. Pinning which side
        # each one is on is the point -- an overview where everything is green
        # by construction would say nothing.
        breached = {
            metric: value
            for metric, value in zip(overview["xlabels"], overview["values"])
            if value < 0
        }
        self.assertEqual(
            set(breached), {"ACIE 占 Data Center", "Networking 占 Data Center"}, breached)
        for metric, value in breached.items():
            # Headroom is percent *of the threshold*, not percentage points:
            # 19.67 against a 20 line is -1.7%, which is 0.33pp short.
            self.assertGreater(value, -2.0, f"{metric} is barely short, not broken")

    def test_the_guided_record_table_covers_every_quarter(self) -> None:
        table = next(item for item in self.payload["tables"] if "指引兑现全表" in item["title"])
        self.assertEqual(len(table["rows"]),
                         len(self.source["quarterly_guidance_history"]["quarters"]))
        self.assertEqual(table["rows"][-1][0], "Q2 2026")
        # The pending quarter has a guided range and nothing else.
        self.assertEqual(table["rows"][-1][2], "—")

    def test_the_dollar_band_chart_declares_its_shorter_window(self) -> None:
        """Drawing eight of twenty-four quarters is a choice, so it is stated."""
        band = next(ex for ex in self.by_section["settled"] if ex["kind"] == "range_band")
        self.assertEqual(len(band["xlabels"]), 8)
        self.assertIn("近 8 季", band["title"])
        self.assertIn("不是数据缺失", band["note"])

    def test_calendar_labelling_is_stated_because_the_fiscal_year_differs(self) -> None:
        self.assertIn("FY2027", self.payload["subtitle"])
        self.assertTrue(
            any("FY2027 Q1" in note for note in self.payload["notes"]),
            "the fiscal/calendar convention is not disclosed in the notes",
        )

    # ── boundary ─────────────────────────────────────────────────────────────
    def test_market_expectation_is_dated_and_unattributed(self) -> None:
        consensus = self.source["market_expectation"]
        self.assertIn("2026-05-20", consensus["as_of"])
        blob = json.dumps(self.payload, ensure_ascii=False).lower()
        for vendor in ["seeking alpha", "visible alpha", "factset", "bloomberg",
                       "s&p global", "morgan stanley", "goldman", "bernstein",
                       "melius", "cantor", "td cowen", "marketscreener"]:
            self.assertNotIn(vendor, blob, vendor)

    def test_no_rating_target_price_or_valuation_is_published(self) -> None:
        """Scoped to the analysis, not the whole payload.

        `评级` and `目标价` legitimately appear in the page's own boundary
        statement ("不构成评级或投资建议"), which is the same reason
        `test_content_boundary` keeps them out of its shared denylist. Asserting
        against the whole blob would fire on a clean build and get switched off,
        so this checks the place the words would actually do harm: chart copy
        and table cells.
        """
        analysis = json.dumps(
            [self.payload["sections"], self.payload["tables"],
             self.payload["headline"], self.payload["brief"]],
            ensure_ascii=False,
        )
        for term in ["目标价", "评级", "增持", "减持", "市盈率", "估值"]:
            self.assertNotIn(term, analysis, term)

    def test_derived_values_are_marked(self) -> None:
        """Anything this page computed carries the D marker somewhere visible."""
        for table_title, column in [
            ("八季度市场平台与 Data Center 拆分", "ACIE 占 DC"),
            ("八季度现金流与营运资金", "FCF / non-GAAP 净利"),
        ]:
            table = next(item for item in self.payload["tables"]
                         if item["title"] == table_title)
            index = table["headers"].index(column)
            self.assertTrue(all(row[index].endswith("D") for row in table["rows"]),
                            table_title)

    def test_payload_matches_the_committed_build(self) -> None:
        published = js_payload(ROOT / "data" / "nvda.js", "window.DASH")
        self.assertEqual(published, self.payload)

    def test_roster_carries_nvda_with_labels_read_from_the_payload(self) -> None:
        roster = roster_payload(build_all())
        entry = next(item for item in roster["items"] if item["slug"] == "nvda")
        self.assertEqual(entry["latest_label"], self.payload["latest"]["disclosed_period_label"])
        self.assertEqual(entry["release_date"], self.payload["latest"]["release_date"])
        self.assertEqual(entry["group"], self.payload["company"]["group"])
        published = js_payload(ROOT / "data" / "roster.js", "window.ROSTER")
        self.assertEqual(published, roster)

    def test_compact_period_round_trips_the_label_format(self) -> None:
        self.assertEqual(compact_period("Q1 2026"), "Q1'26")
        self.assertEqual(compact_period("Q3 2020"), "Q3'20")
        for quarter in self.source["quarterly_guidance_history"]["quarters"]:
            self.assertRegex(compact_period(quarter), r"^Q[1-4]'\d{2}$")


if __name__ == "__main__":
    unittest.main()
