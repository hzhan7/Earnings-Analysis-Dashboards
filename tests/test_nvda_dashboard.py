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
    # Series that are eight quarters long *and* complete. Anything with a hole
    # is listed in DECLARED_HOLES below with the reason, so a hole that appears
    # without being declared turns this red rather than being absorbed.
    DECLARED_HOLES = {
        # NVIDIA never printed FY2025's quarters on the post-restatement
        # non-GAAP basis, and net income cannot be derived the way margin and
        # opex can -- the tax line changed algorithm. See the basis note.
        "financials.non_gaap_net_income_usd_m": 2,
    }

    def test_all_historical_series_have_eight_quarters(self) -> None:
        self.assertEqual(len(self.source["periods"]), 8)
        for group in [
            "financials",
            "market_platform_usd_m",
            "cash_flow_usd_m",
            "working_capital",
        ]:
            for name, values in self.source[group].items():
                if not isinstance(values, list):
                    continue
                key = f"{group}.{name}"
                self.assertEqual(len(values), 8, key)
                holes = sum(1 for value in values if value is None)
                self.assertEqual(holes, self.DECLARED_HOLES.get(key, 0), key)
                self.assertTrue(
                    all(math.isfinite(value) for value in values if value is not None),
                    key,
                )
        # The declared hole has to be explained where a reader meets it.
        self.assertIn("留空", self.source["financials"]["non_gaap_basis_note"])

    def test_the_long_series_reaches_back_to_2016(self) -> None:
        """The long-run charts are the ones that carry the cycle, so they start
        far enough back to contain one. Anything shorter turns the 2022
        de-stocking trough into the beginning of the record rather than an
        episode inside it."""
        long = self.source["long_history"]
        self.assertEqual(long["quarters"][0], "Q1 2016")
        self.assertEqual(long["quarters"][-1], self.source["periods"][-1])
        self.assertEqual(len(long["quarters"]), 42)
        for name, values in long.items():
            if isinstance(values, list):
                self.assertEqual(len(values), 42, name)
        # The 24 quarters this file used to assert against are still there and
        # unchanged: extending a series must not restate the part that existed.
        overlap = long["quarters"].index("Q2 2020")
        self.assertEqual(long["revenue_usd_m"][overlap], 3866)
        self.assertEqual(long["quarters"][overlap:][:3], ["Q2 2020", "Q3 2020", "Q4 2020"])

    def test_the_guided_record_is_one_row_per_quarter(self) -> None:
        guide = self.source["quarterly_guidance_history"]
        length = len(guide["quarters"])
        self.assertEqual(length, 25)
        for name, values in guide.items():
            self.assertEqual(len(values), length, name)
        # The record ends on a quarter that has been guided but not reported;
        # everything before it must be complete.
        self.assertIsNone(guide["actual_revenue_usd_m"][-1])
        self.assertTrue(all(value is not None for value in guide["actual_revenue_usd_m"][:-1]))
        self.assertEqual(guide["quarters"][-1], "Q3 2026")
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
        """Hyperscale + ACIE = Data Center, on both sides of the restatement.

        This identity is what makes the split publishable at all: the Data
        Center total on the right-hand side is read from that quarter's own
        filing, so a mis-transcribed sub-market cannot hide. It has to hold for
        the recast values *and* for the ones Q1 FY2027 originally filed --
        both add to the same total, which is exactly why the reclassification
        is invisible to anyone reading only the Data Center line.
        """
        mix = self.source["dc_customer_mix"]
        platform = self.source["market_platform_usd_m"]
        by_period = dict(zip(self.source["periods"], platform["data_center"]))
        for index, period in enumerate(mix["quarters"]):
            self.assertEqual(
                mix["hyperscale"][index] + mix["acie"][index],
                by_period[period],
                period,
            )
        filed = mix["q1_2026_as_originally_filed"]
        self.assertEqual(filed["hyperscale"] + filed["acie"], by_period["Q1 2026"])
        # The restatement moved a real amount, in one direction, and left the
        # total alone. If this ever nets to zero the two bases are the same and
        # the exhibit is claiming a difference that is not there.
        recast_index = mix["quarters"].index("Q1 2026")
        shift = mix["hyperscale"][recast_index] - filed["hyperscale"]
        self.assertGreater(shift, 0)
        self.assertEqual(shift, filed["acie"] - mix["acie"][recast_index])

    def test_the_recast_gap_is_left_open_not_bridged(self) -> None:
        """Q3/Q4 2025 have no restated split, so they are absent, not guessed."""
        mix = self.source["dc_customer_mix"]
        self.assertEqual(mix["quarters"], ["Q2 2025", "Q1 2026", "Q2 2026"])
        for missing in ("Q3 2025", "Q4 2025"):
            self.assertNotIn(missing, mix["quarters"])
        self.assertIn("无法由两个已披露数相减得到", mix["note"])
        self.assertTrue(
            any("不再画这条八季序列" in note for note in self.payload["notes"]),
            "the page does not say why the eight-quarter split is gone",
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
        # The value NVIDIA filed for the quarter this page reports.
        self.assertEqual(platform["edge_computing"][-1], 7198)

    def test_compute_and_networking_sum_to_data_center(self) -> None:
        """Within the US$0.1B the company rounds those two lines to.

        The series is frozen -- NVIDIA stopped publishing the split this
        quarter -- so this checks the quarters that overlap the current window
        and then checks that the freeze is disclosed rather than extrapolated.
        """
        split = self.source["discontinued_dc_split_usd_m"]
        platform = self.source["market_platform_usd_m"]
        by_period = dict(zip(self.source["periods"], platform["data_center"]))
        overlap = 0
        for index, period in enumerate(split["quarters"]):
            if period not in by_period:
                continue
            overlap += 1
            total = split["compute"][index] + split["networking"][index]
            self.assertLess(abs(total - by_period[period]), 110, period)
        self.assertGreaterEqual(overlap, 6, "the two windows stopped overlapping")
        self.assertEqual(split["quarters"][-1], "Q1 2026")
        self.assertNotIn(self.source["periods"][-1], split["quarters"])
        self.assertIn("不做外推", split["note"])

    def test_year_on_year_copy_compares_the_same_quarter(self) -> None:
        """Four quarters back is index -5, not -4.

        The window is eight contiguous quarters, so an off-by-one here still
        produces a plausible growth rate against the wrong base -- the kind of
        error that survives a read-through. This pins the two YoY figures the
        market-platform exhibit prints against the series they claim to be.
        """
        periods = self.source["periods"]
        self.assertEqual(periods[-5].split()[0], periods[-1].split()[0])
        self.assertEqual(int(periods[-5].split()[1]) + 1, int(periods[-1].split()[1]))
        platform = self.source["market_platform_usd_m"]
        chart = next(ex for ex in self.by_section["quarter_highlights"]
                     if ex["title"].startswith("Data Center US$"))
        for series in ("data_center", "edge_computing"):
            growth = platform[series][-1] / platform[series][-5] * 100 - 100
            self.assertIn(f"同比 +{growth:.1f}%", chart["note"], series)
        # And the headline YoY on the revenue chart is the one the series carries.
        revenue_chart = next(ex for ex in self.by_section["quarter_highlights"]
                             if ex["kind"] == "gs_bar")
        stated = self.source["financials"]["revenue_yoy_pct"][-1]
        revenue = self.source["financials"]["revenue_usd_m"]
        self.assertAlmostEqual(stated, revenue[-1] / revenue[-5] * 100 - 100, places=3)
        self.assertIn(f"+{stated:.1f}%", revenue_chart["title"])

    def test_the_margin_high_water_claim_is_measured(self) -> None:
        """A high-water claim has to be derived from the window it is claimed over.

        Over eight quarters gross margin was two hundredths of a point off the
        best, which one decimal cannot even show. Over the ten-year record the
        answer is not close at all -- the high is 78.4% in Q1'24, three and a
        half points above this quarter -- and the eight-quarter window could not
        see it because the peak sat one cell to the left of it. Both readings
        are "not the high"; only the long one says by how much, which is the
        whole reason the window moved.
        """
        long = self.source["long_history"]
        chart = next(ex for ex in self.by_section["quarter_highlights"]
                     if ex.get("kind") == "lines" and "GAAP 毛利率" in ex["title"])
        self.assertEqual(len(chart["xlabels"]), len(long["quarters"]))
        gross, operating = long["gaap_gross_margin_pct"], long["gaap_operating_margin_pct"]
        self.assertFalse(gross[-1] == max(gross), "the case this test exists for has gone away")
        self.assertTrue(operating[-1] == max(operating))
        self.assertIn("营业利润率是十年新高，毛利率不是", chart["title"])
        self.assertNotIn("八季", chart["title"])
        # The note may -- and should -- mention the eight-quarter window, but
        # only to say what it hid. Asserting the word is absent would have
        # deleted the one sentence that makes the longer window worth reading.
        self.assertIn("八季的窗口看不到这件事", chart["note"])
        # The high the note names is the one in the series, not a typed number.
        peak = max(gross)
        self.assertIn(f"{peak:.1f}%", chart["note"])
        self.assertGreater(peak - gross[-1], 3.0,
                           "the gap is what makes the long window worth drawing")

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
        mix = self.source["dc_customer_mix"]
        self.assertEqual(financials["revenue_usd_m"][-1], 96221)
        self.assertEqual(financials["revenue_usd_m"][-2], 81615)
        self.assertEqual(financials["gaap_operating_income_usd_m"][-1], 63734)
        self.assertEqual(financials["gaap_net_income_usd_m"][-1], 59688)
        self.assertEqual(financials["gaap_opex_usd_m"][-1], 8408)
        self.assertEqual(financials["non_gaap_opex_usd_m"][-1], 8232)
        self.assertEqual(financials["non_gaap_operating_income_usd_m"][-1], 63956)
        self.assertEqual(financials["non_gaap_net_income_usd_m"][-1], 53954)
        self.assertEqual(platform["data_center"][-1], 89023)
        self.assertEqual(mix["hyperscale"][-1], 48710)
        self.assertEqual(mix["acie"][-1], 40313)
        self.assertEqual(working["inventories_usd_m"][-1], 31575)
        self.assertEqual(working["accounts_receivable_usd_m"][-1], 63059)
        self.assertEqual(cash["free_cash_flow"][-1], 21341)
        self.assertEqual(cash["operating_cash_flow"][-1], 24077)
        # Income-statement identities, so a mis-typed line cannot pass.
        self.assertEqual(financials["non_gaap_gross_profit_usd_m"][-1]
                         - financials["non_gaap_opex_usd_m"][-1],
                         financials["non_gaap_operating_income_usd_m"][-1])
        # Rounded percentages the company printed in the same release.
        self.assertAlmostEqual(financials["gaap_gross_margin_pct"][-1], 75.0, places=1)
        self.assertAlmostEqual(financials["non_gaap_gross_margin_pct"][-1], 75.0, places=1)
        # DSO is the quarter's headline balance-sheet fact and the first KPI,
        # so it is pinned to one decimal and to its own formula.
        self.assertAlmostEqual(working["dso_days"][-1], 59.6, places=1)
        self.assertAlmostEqual(working["dso_days"][-2], 45.4, places=1)
        for index, period in enumerate(self.source["periods"]):
            self.assertAlmostEqual(
                working["dso_days"][index],
                working["accounts_receivable_usd_m"][index]
                / financials["revenue_usd_m"][index] * 91,
                places=3,
                msg=period,
            )

    def test_the_derived_non_gaap_quarters_reproduce_the_published_ones(self) -> None:
        """Two quarters of the non-GAAP series are this page's arithmetic.

        NVIDIA restated its non-GAAP basis but only ever printed six of these
        eight quarters on the new one. The other two are derived by the same
        mechanical rule, and the rule is only usable because it reproduces the
        six published quarters exactly -- so that is what is checked, not the
        two derived values themselves.
        """
        financials = self.source["financials"]
        published = {
            "Q1 2025": (26794, 4993, 21801),
            "Q2 2025": (33902, 5361, 28541),
            "Q3 2025": (41897, 5800, 36097),
            "Q4 2025": (51140, 6666, 44474),
            "Q1 2026": (61232, 7449, 53783),
            "Q2 2026": (72188, 8232, 63956),
        }
        for period, (gross, opex, operating) in published.items():
            index = self.source["periods"].index(period)
            self.assertEqual(financials["non_gaap_gross_profit_usd_m"][index], gross, period)
            self.assertEqual(financials["non_gaap_opex_usd_m"][index], opex, period)
            self.assertEqual(
                financials["non_gaap_operating_income_usd_m"][index], operating, period)
        # Every quarter, published or derived, satisfies the same identity.
        for index, period in enumerate(self.source["periods"]):
            self.assertEqual(
                financials["non_gaap_gross_profit_usd_m"][index]
                - financials["non_gaap_opex_usd_m"][index],
                financials["non_gaap_operating_income_usd_m"][index],
                period,
            )
            self.assertAlmostEqual(
                financials["non_gaap_gross_margin_pct"][index],
                financials["non_gaap_gross_profit_usd_m"][index]
                / financials["revenue_usd_m"][index] * 100,
                places=3,
                msg=period,
            )
        self.assertIn("机械规则", financials["non_gaap_basis_note"])

    def test_current_guidance_matches_the_outlook_paragraph(self) -> None:
        guide = self.source["guidance"]["q3_new"]
        self.assertEqual(guide["revenue_usd_bn"], 108.0)
        self.assertEqual(guide["revenue_band_pct"], 2.0)
        self.assertEqual(guide["gaap_gross_margin_pct"], 74.0)
        self.assertEqual(guide["non_gaap_gross_margin_pct"], 74.0)
        self.assertEqual(guide["gaap_opex_usd_bn"], 9.2)
        self.assertEqual(guide["non_gaap_opex_usd_bn"], 9.0)
        history = self.source["quarterly_guidance_history"]
        pending = history["quarters"].index("Q3 2026")
        self.assertEqual(history["guide_revenue_usd_bn"][pending], 108.0)
        self.assertEqual(history["non_gaap_opex_guide_usd_bn"][pending], 9.0)
        # The gross-margin guide came down this quarter; the page must not
        # print it as a reaffirmation.
        reported = history["quarters"].index("Q2 2026")
        self.assertLess(guide["non_gaap_gross_margin_pct"],
                        history["non_gaap_gm_guide_pct"][reported])

    def test_call_only_guidance_stays_out_of_the_charts(self) -> None:
        """The forward numbers everyone quotes this quarter are call-only.

        FY2028 revenue growth, the Q4 and FY2028 gross-margin ranges and the
        full-year opex wording appear in no filing. They are the most quotable
        things NVIDIA said, which is exactly why the page has to keep them off
        the exhibits rather than trust itself to remember.
        """
        self.assertIn("call_only", self.source["guidance"])
        excluded = self.source["next_kpi"]["excluded"]
        for figure in ["70%", "71%–72%", "72%–73%", "low 50s"]:
            self.assertIn(figure, excluded, figure)
        # Each one may appear exactly where it is declared out of scope, and
        # nowhere else in the exhibits. Asserting "not present at all" would
        # fire on the disclosure itself and get switched off.
        for exhibit in self.exhibits:
            body = " ".join(str(exhibit.get(field, "")) for field in
                            ("title", "note", "legend", "ylab"))
            for figure in ["71%–72%", "72%–73%", "low 50s"]:
                self.assertNotIn(figure, body, f"{figure} in {exhibit['title']}")
            source_line = str(exhibit.get("src_extra", ""))
            if figure in source_line:
                self.assertIn("不设阈值图", source_line)
        self.assertTrue(
            any("只出现在电话会" in note for note in self.payload["notes"]),
            "the call-only boundary is not stated in the notes",
        )

    def test_the_restatement_is_recorded_not_smoothed(self) -> None:
        """Both bases of the reclassified split reach the page, and are labelled.

        Publishing only the recast numbers would make this quarter's ACIE growth
        look like a step change in the business; publishing only the originally
        filed ones would contradict the current 10-Q. The page has to carry both
        and say which is which.
        """
        restated = self.source["restated_comparatives"]
        self.assertEqual(restated["quarters"], ["Q2 2026", "Q1 2026", "Q2 2025"])
        self.assertEqual(restated["non_gaap_eps_usd"], [2.22, 1.87, 1.01])
        mix = self.source["dc_customer_mix"]
        blob = json.dumps(self.payload, ensure_ascii=False)
        for value in (mix["q1_2026_as_originally_filed"]["hyperscale"] / 1000,
                      mix["hyperscale"][mix["quarters"].index("Q1 2026")] / 1000):
            self.assertIn(f"{value:.2f}", blob, value)
        self.assertIn("reclassified", mix["note"])
        self.assertTrue(
            any("重分类并追溯重述" in note for note in self.payload["notes"]),
            "the reclassification is not disclosed in the page notes",
        )

    def test_equity_gains_explain_the_gaap_wedge(self) -> None:
        """The wedge is the same item as last quarter, running the other way.

        Last quarter equity gains pushed GAAP net income above non-GAAP; this
        quarter they fell US$8.2B and GAAP net income grew 2% on a quarter whose
        operating income grew 19%. Pinning the direction matters more than
        pinning the level -- an exhibit that only ever showed the flattering
        direction would have told the reader nothing when it reversed.
        """
        restated = self.source["restated_comparatives"]
        current, prior = 0, 1
        self.assertEqual(restated["equity_securities_gains_usd_m"][current], 7771)
        self.assertEqual(restated["equity_securities_gains_usd_m"][prior], 15936)
        self.assertLess(restated["equity_securities_gains_usd_m"][current],
                        restated["equity_securities_gains_usd_m"][prior])
        # GAAP still sits above non-GAAP, but the sequential *growth* ranking
        # flipped: that flip is the whole point of the exhibit.
        self.assertGreater(restated["gaap_net_income_usd_m"][current],
                           restated["non_gaap_net_income_usd_m"][current])
        gaap_growth = (restated["gaap_net_income_usd_m"][current]
                       / restated["gaap_net_income_usd_m"][prior])
        core_growth = (restated["non_gaap_net_income_usd_m"][current]
                       / restated["non_gaap_net_income_usd_m"][prior])
        operating_growth = (restated["gaap_operating_income_usd_m"][current]
                            / restated["gaap_operating_income_usd_m"][prior])
        self.assertLess(gaap_growth, core_growth)
        self.assertLess(gaap_growth, operating_growth)
        # Other income net is pretax income less operating income, and equity
        # gains are almost all of it -- which is what localises the wedge.
        self.assertGreater(
            restated["equity_securities_gains_usd_m"][current]
            / restated["gaap_total_other_income_usd_m"][current], 0.99)

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
        table_only = set(self.source["next_kpi"]["table_only"])
        # One overview bar plus one chart per metric that has a series. The
        # guarantee exposure has a single disclosed point -- last quarter's
        # 10-Q made no such disclosure at all -- so it is table-only, and that
        # has to be declared rather than silently dropped.
        self.assertEqual(len(next_charts), 1 + len(quantified) - len(table_only))
        plotted = " ".join(chart["title"] for chart in next_charts[1:])
        for entry in quantified:
            if entry["metric"] in table_only:
                self.assertNotIn(entry["metric"], plotted)
            else:
                self.assertIn(entry["metric"], plotted)
        # Every table-only name is a real KPI, not a stale entry.
        self.assertTrue(table_only <= {entry["metric"] for entry in quantified})
        self.assertIn("电话会", next_charts[0]["src_extra"])

    def test_a_kpi_without_a_series_cannot_be_dropped_silently(self) -> None:
        """The previous build skipped unmatched KPIs with `continue`.

        That is the failure mode this page has just lived through in another
        form: a metric disappears from the section and nothing anywhere says it
        did. Adding a KPI with no series must now raise.
        """
        broken = json.loads(json.dumps(self.source))
        broken["next_kpi"]["quantified"].append(
            {"metric": "没有序列的指标", "direction": "up",
             "threshold": 1.0, "unit": "pct", "current": 2.0}
        )
        with self.assertRaises(KeyError):
            build_payload(broken)

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
        # Exactly one line is over this quarter, and it is the cash-conversion
        # one. Pinning which one is the point -- an overview where everything is
        # green by construction would say nothing.
        self.assertEqual(set(breached), {"FCF / non-GAAP 净利转化率"}, breached)
        self.assertLess(breached["FCF / non-GAAP 净利转化率"], -15.0,
                        "this is a real breach, not a rounding miss")
        self.assertIn("已经越线", overview["title"])

    def test_the_guided_record_table_covers_every_quarter(self) -> None:
        table = next(item for item in self.payload["tables"] if "指引兑现全表" in item["title"])
        self.assertEqual(len(table["rows"]),
                         len(self.source["quarterly_guidance_history"]["quarters"]))
        self.assertEqual(table["rows"][-1][0], "Q3 2026")
        # The pending quarter has a guided range and nothing else.
        self.assertEqual(table["rows"][-1][2], "—")

    def test_the_dollar_band_chart_declares_its_shorter_window(self) -> None:
        """Drawing eight of twenty-four quarters is a choice, so it is stated."""
        band = next(ex for ex in self.by_section["settled"] if ex["kind"] == "range_band")
        self.assertEqual(len(band["xlabels"]), 8)
        self.assertIn("近 8 季", band["title"])
        self.assertIn("不是数据缺失", band["note"])

    def test_every_guided_metric_gets_a_level_chart_and_a_deviation_chart(self) -> None:
        """Three guided numbers, three pairs, grouped by metric."""
        settled = self.by_section["settled"]
        pairs = [("收入", "range_band"), ("收入", "grouped_bars"),
                 ("non-GAAP 毛利率", "range_band"), ("non-GAAP 毛利率", "grouped_bars"),
                 ("non-GAAP 营业费用", "range_band"), ("non-GAAP 营业费用", "grouped_bars")]
        for metric, kind in pairs:
            self.assertTrue(
                any(chart["kind"] == kind and chart["title"].startswith(metric)
                    for chart in settled),
                f"no {kind} for {metric}",
            )

    def test_the_opex_chart_is_a_point_guidance_with_a_marked_break(self) -> None:
        """Opex is guided as a single number, and its basis changed mid-record.

        Two things have to be true at once and neither may be smoothed over: the
        guidance has no width (so `lo == hi`, and the chart must not claim
        anything cleared a bound), and the non-GAAP basis changed in Q1 2026, so
        the *level* series is not comparable across that quarter.
        """
        chart = next(ex for ex in self.by_section["settled"]
                     if ex["kind"] == "range_band" and ex["title"].startswith("non-GAAP 营业费用"))
        self.assertEqual(chart["lo"], chart["hi"], "a point guidance must have no width")
        for word in ("超出上限", "跌破下限", "区间内"):
            self.assertNotIn(word, chart["title"], word)
        self.assertIn("高于指引", chart["title"])

        guide = self.source["quarterly_guidance_history"]
        self.assertEqual(chart["break_at"], guide["quarters"].index("Q1 2026"))
        self.assertIn("股权激励", chart["break_label"])
        # The level jumps at the break because the definition did, and both legs
        # jump together -- which is why the deviation chart carries no break.
        step = guide["quarters"].index("Q1 2026")
        before = guide["actual_non_gaap_opex_usd_m"][step - 1]
        after = guide["actual_non_gaap_opex_usd_m"][step]
        self.assertGreater(after / before, 1.3, "the restatement step vanished")
        deviation = next(ex for ex in self.by_section["settled"]
                         if ex["kind"] == "grouped_bars"
                         and ex["title"].startswith("non-GAAP 营业费用"))
        self.assertNotIn("break_at", deviation)

    def test_calendar_labelling_is_stated_because_the_fiscal_year_differs(self) -> None:
        self.assertIn("FY2027", self.payload["subtitle"])
        self.assertTrue(
            any("FY2027 Q2" in note for note in self.payload["notes"]),
            "the fiscal/calendar convention is not disclosed in the notes",
        )

    # ── boundary ─────────────────────────────────────────────────────────────
    def test_market_expectation_is_dated_and_unattributed(self) -> None:
        consensus = self.source["market_expectation"]
        self.assertIn("2026-08-26", consensus["as_of"])
        # The note itself flags that this quarter's consensus is second-hand;
        # the page has to carry that caveat rather than quietly drop it.
        self.assertIn("二手", consensus["basis"])
        self.assertTrue(
            any("二手转述" in note for note in self.payload["notes"]),
            "the consensus caveat is not disclosed in the notes",
        )
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
            ("八季度市场平台与客户集中度", "占收入"),
            ("八季度现金流与营运资金", "FCF / 收入"),
            ("八季度现金流与营运资金", "DSO"),
        ]:
            table = next(item for item in self.payload["tables"]
                         if item["title"] == table_title)
            index = table["headers"].index(column)
            self.assertTrue(all(row[index].endswith("D") for row in table["rows"]),
                            table_title)

    def test_nvda_sits_between_the_two_ends_of_the_capex_table(self) -> None:
        """The shared cross-reference carries Data Center, aligned by label only.

        NVIDIA's quarters end about four weeks after the calendar quarters the
        rest of the table uses, so a row compares periods that do not coincide.
        That is disclosed in the column header rather than corrected, because
        shifting a reported quarter onto another company's calendar would mean
        inventing a number. The quarter NVIDIA has not reported yet must stay a
        dash for the same reason.
        """
        table = next(item for item in self.payload["tables"] if "AI capex" in item["title"])
        column = next(index for index, header in enumerate(table["headers"])
                      if header.startswith("NVDA"))
        self.assertIn("晚约 1 个月", table["headers"][column])

        by_period = dict(zip(self.source["periods"],
                             self.source["market_platform_usd_m"]["data_center"]))
        seen = 0
        for row in table["rows"]:
            expected = by_period.get(row[0])
            if expected is None:
                self.assertEqual(row[column], "—", row[0])
            else:
                self.assertEqual(row[column], f"US${expected / 1000:.2f}B", row[0])
                seen += 1
        self.assertGreaterEqual(seen, 7, "the two windows stopped overlapping")
        # Edge Computing is deliberately excluded: hyperscaler capex does not
        # buy game consoles, so the whole-company line would overstate the link.
        self.assertNotEqual(
            table["rows"][0][column],
            f"US${self.source['financials']['revenue_usd_m'][1] / 1000:.2f}B",
        )

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
