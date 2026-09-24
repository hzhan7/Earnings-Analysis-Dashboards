"""Reconciliation and shape tests for the NVDA page.

The point of this file is the same as the other companies': nothing derived
reaches the page until it has been checked against a statement identity or a
figure the company disclosed separately. NVDA adds one identity the other pages
do not have -- the operating-income beat decomposition -- and one hazard they do
not have either: a non-GAAP definition that changed mid-record, which is only
safe because every guidance/actual pair sits on one side of the change.
"""

from __future__ import annotations

import copy
import json
import math
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.all import build_all, roster_payload  # noqa: E402
from build.board import cn_count, cn_ordinal, headroom  # noqa: E402
from build.nvda import build_payload, compact_period  # noqa: E402

# The last quarter whose figures this file pins exactly. A roll leaves these
# pins valid (the quarter is still in the window) and adds invariants for the
# newest quarter instead of retyping numbers.
PINNED_THROUGH = "Q2 2026"


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


def published_text(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def quarter_order(label: str) -> int:
    quarter, year = label.split()
    return int(year) * 4 + int(quarter[1]) - 1


def shift_quarter(label: str, step: int) -> str:
    index = quarter_order(label) + step
    return f"Q{index % 4 + 1} {index // 4}"


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
        length = quarter_order(self.source["periods"][-1]) - quarter_order("Q1 2016") + 1
        self.assertEqual(len(long["quarters"]), length)
        for name, values in long.items():
            if isinstance(values, list):
                self.assertEqual(len(values), length, name)
        # The 24 quarters this file used to assert against are still there and
        # unchanged: extending a series must not restate the part that existed.
        overlap = long["quarters"].index("Q2 2020")
        self.assertEqual(long["revenue_usd_m"][overlap], 3866)
        self.assertEqual(long["quarters"][overlap:][:3], ["Q2 2020", "Q3 2020", "Q4 2020"])

    def test_the_guided_record_is_one_row_per_quarter(self) -> None:
        guide = self.source["quarterly_guidance_history"]
        length = len(guide["quarters"])
        next_quarter = self.source["guidance"]["next_quarter"]["period"]
        self.assertEqual(length, quarter_order(next_quarter) - quarter_order("Q1 2016") + 1)
        for name, values in guide.items():
            if isinstance(values, list):
                self.assertEqual(len(values), length, name)
        # Extending the record backwards must not restate the part that was
        # already published: the 25 rows this file used to assert against are
        # still the tail, unchanged.
        overlap = guide["quarters"].index("Q3 2020")
        self.assertEqual(overlap, 18)
        self.assertEqual(guide["guide_revenue_usd_bn"][overlap], 4.4)
        self.assertEqual(guide["actual_revenue_usd_m"][overlap], 4726.0)
        # The record ends on a quarter that has been guided but not reported;
        # everything before it must be complete.
        self.assertIsNone(guide["actual_revenue_usd_m"][-1])
        self.assertTrue(all(value is not None for value in guide["actual_revenue_usd_m"][:-1]))
        self.assertEqual(guide["quarters"][-1], next_quarter)
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
        filed = mix["as_originally_filed"]
        self.assertEqual(filed["hyperscale"] + filed["acie"], by_period[filed["period"]])
        # The restatement moved a real amount, in one direction, and left the
        # total alone. If this ever nets to zero the two bases are the same and
        # the exhibit is claiming a difference that is not there.
        recast_index = mix["quarters"].index(filed["period"])
        shift = mix["hyperscale"][recast_index] - filed["hyperscale"]
        self.assertGreater(shift, 0)
        self.assertEqual(shift, filed["acie"] - mix["acie"][recast_index])

    def test_the_recast_gap_is_left_open_not_bridged(self) -> None:
        """Q3/Q4 2025 have no restated split, so they are absent, not guessed."""
        mix = self.source["dc_customer_mix"]
        if mix["period"] != PINNED_THROUGH:
            self.skipTest("the recast block describes a later quarter")
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
        # The value NVIDIA filed for the pinned quarter.
        self.assertEqual(
            platform["edge_computing"][self.source["periods"].index(PINNED_THROUGH)], 7198)

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
        see it because the peak sat two cells to the left of it (the page used
        to say one). Both readings are "not the high"; only the long one says by
        how much, which is the whole reason the window moved.
        """
        # The long record's reading lives on section four's ten-year chart, which
        # draws exactly these two series; section two used to draw the same two
        # series again under a title about the record rather than the quarter.
        long = self.source["long_history"]
        chart = next(ex for ex in self.by_section["routine"]
                     if ex.get("kind") == "lines" and "毛利率与营业利润率" in ex["title"])
        self.assertEqual(len(chart["xlabels"]), len(long["quarters"]))
        gross, operating = long["gaap_gross_margin_pct"], long["gaap_operating_margin_pct"]
        n = len(long["quarters"])
        if operating[-1] == max(operating):
            self.assertIn(f"营业利润率本季 {operating[-1]:.1f}%，是这 {n} 季的最高。", chart["note"])
        else:
            self.assertNotIn(f"是这 {n} 季的最高", chart["note"])
        if gross[-1] != max(gross):
            # The high the note names is the one in the series, not a typed
            # number, and so is its distance from the window's left edge.
            peak = max(gross)
            self.assertIn(f"而十年高点是 {compact_period(long['quarters'][gross.index(peak)])} 的 {peak:.1f}%",
                          chart["note"])
            cells = long["quarters"].index(self.source["periods"][0]) - gross.index(peak)
            if 0 < cells <= 4:
                # The note may -- and should -- mention the eight-quarter
                # window, but only to say what it hid.
                self.assertIn(f"落在窗口的前{'一' if cells == 1 else cn_count(cells)}格", chart["note"])
        # Section two's margin chart is about this quarter, not the record.
        now = next(ex for ex in self.by_section["quarter_highlights"]
                   if ex["title"].startswith("non-GAAP 毛利率本季"))
        self.assertLessEqual(len(now["xlabels"]), len(self.source["periods"]))
        self.assertIn(f"{self.source['financials']['non_gaap_gross_margin_pct'][-1]:.1f}%", now["title"])

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
        at = self.source["periods"].index(PINNED_THROUGH)
        self.assertEqual(financials["revenue_usd_m"][at], 96221)
        self.assertEqual(financials["revenue_usd_m"][at - 1], 81615)
        self.assertEqual(financials["gaap_operating_income_usd_m"][at], 63734)
        self.assertEqual(financials["gaap_net_income_usd_m"][at], 59688)
        self.assertEqual(financials["gaap_opex_usd_m"][at], 8408)
        self.assertEqual(financials["non_gaap_opex_usd_m"][at], 8232)
        self.assertEqual(financials["non_gaap_operating_income_usd_m"][at], 63956)
        self.assertEqual(financials["non_gaap_net_income_usd_m"][at], 53954)
        self.assertEqual(platform["data_center"][at], 89023)
        self.assertEqual(working["inventories_usd_m"][at], 31575)
        self.assertEqual(working["accounts_receivable_usd_m"][at], 63059)
        self.assertEqual(cash["free_cash_flow"][at], 21341)
        self.assertEqual(cash["operating_cash_flow"][at], 24077)
        mix = self.source.get("dc_customer_mix")
        if mix is not None and PINNED_THROUGH in mix["quarters"]:
            self.assertEqual(mix["hyperscale"][mix["quarters"].index(PINNED_THROUGH)], 48710)
            self.assertEqual(mix["acie"][mix["quarters"].index(PINNED_THROUGH)], 40313)
        # Income-statement identities, so a mis-typed line cannot pass.
        for index in range(len(self.source["periods"])):
            self.assertEqual(financials["non_gaap_gross_profit_usd_m"][index]
                             - financials["non_gaap_opex_usd_m"][index],
                             financials["non_gaap_operating_income_usd_m"][index])
        # Rounded percentages the company printed in the same release.
        self.assertAlmostEqual(financials["gaap_gross_margin_pct"][at], 75.0, places=1)
        self.assertAlmostEqual(financials["non_gaap_gross_margin_pct"][at], 75.0, places=1)
        # DSO is the quarter's headline balance-sheet fact and the first KPI,
        # so it is pinned to one decimal and to its own formula.
        self.assertAlmostEqual(working["dso_days"][at], 59.6, places=1)
        self.assertAlmostEqual(working["dso_days"][at - 1], 45.4, places=1)
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
        history = self.source["quarterly_guidance_history"]
        # The Q3 2026 outlook stays in the record after it is reported.
        pending = history["quarters"].index("Q3 2026")
        self.assertEqual(history["guide_revenue_usd_bn"][pending], 108.0)
        self.assertEqual(history["non_gaap_opex_guide_usd_bn"][pending], 9.0)
        self.assertEqual(history["gaap_opex_guide_usd_bn"][pending], 9.2)
        self.assertEqual(history["non_gaap_gm_guide_pct"][pending], 74.0)
        # The outlook block is keyed without years and must equal the record's last row.
        guide = self.source["guidance"]["next_quarter"]
        self.assertEqual(guide["period"], history["quarters"][-1])
        self.assertEqual(guide["revenue_usd_bn"], history["guide_revenue_usd_bn"][-1])
        self.assertEqual(guide["non_gaap_opex_usd_bn"], history["non_gaap_opex_guide_usd_bn"][-1])
        self.assertEqual(guide["gaap_opex_usd_bn"], history["gaap_opex_guide_usd_bn"][-1])
        self.assertEqual(guide["non_gaap_gross_margin_pct"], history["non_gaap_gm_guide_pct"][-1])
        for key in self.source["guidance"]:
            self.assertIsNone(re.search(r"\d", key), f"guidance key {key!r} carries a year")
        # When the gross-margin guide came down, the page must not print it as a
        # reaffirmation.
        reported = history["quarters"].index(self.source["periods"][-1])
        table = next(t for t in self.payload["tables"] if "指引" in t["title"] and "兑现与" in t["title"])
        row = next(r for r in table["rows"] if r[0] == "non-GAAP 毛利率")
        step = round(guide["non_gaap_gross_margin_pct"], 1) - round(history["non_gaap_gm_guide_pct"][reported], 1)
        if step < 0:
            self.assertTrue(row[5].startswith(f"下修 {abs(step):.1f}pp"), row[5])
        self.assertNotIn("-", row[5].split("，")[0], "「下修」 carries the sign")

    def test_call_only_guidance_stays_out_of_the_charts(self) -> None:
        """The forward numbers everyone quotes this quarter are call-only.

        FY2028 revenue growth, the Q4 and FY2028 gross-margin ranges and the
        full-year opex wording appear in no filing. They are the most quotable
        things NVIDIA said, which is exactly why the page has to keep them off
        the exhibits rather than trust itself to remember.
        """
        self.assertIn("call_only", self.source["guidance"])
        declared = self.source["guidance"]["call_only"]["note"]
        for figure in ["70%", "71%–72%", "72%–73%", "low 50s"]:
            self.assertIn(figure, declared, figure)
        # Each one may appear where it is declared out of scope (the notes, the
        # drawer's copy of the report's rows), and nowhere in the exhibits.
        # Asserting "not present at all" would fire on the disclosure itself and
        # get switched off.
        for exhibit in self.exhibits:
            body = " ".join(str(exhibit.get(field, "")) for field in
                            ("title", "note", "legend", "ylab", "src_extra"))
            # The spelling with a hyphen is the same call-only figure: the page
            # once carried 「high-30s 上调到 low-50s」 in a chart note.
            for figure in ["71%–72%", "72%–73%", "low 50s", "low-50s", "high-30s", "high 30s"]:
                self.assertNotIn(figure, body, f"{figure} in {exhibit['title']}")
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
        if restated["period"] != PINNED_THROUGH:
            self.skipTest("the restated block describes a later quarter")
        self.assertEqual(restated["quarters"], ["Q2 2026", "Q1 2026", "Q2 2025"])
        self.assertEqual(restated["non_gaap_eps_usd"], [2.22, 1.87, 1.01])
        mix = self.source["dc_customer_mix"]
        blob = json.dumps(self.payload, ensure_ascii=False)
        filed = mix["as_originally_filed"]
        for value in (filed["hyperscale"] / 1000,
                      mix["hyperscale"][mix["quarters"].index(filed["period"])] / 1000):
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
        if restated["period"] != PINNED_THROUGH:
            self.skipTest("the restated block describes a later quarter")
        # Looked up by label: a block that lists quarters newest-first today may
        # not tomorrow, and [0] / [1] would silently swap them.
        current = restated["quarters"].index(PINNED_THROUGH)
        prior = restated["quarters"].index(self.source["periods"][-2])
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
        other = self.source["other_income_usd_m"]
        self.assertGreater(
            restated["equity_securities_gains_usd_m"][current]
            / other["total_other_income"][other["quarters"].index(PINNED_THROUGH)], 0.99)

    # ── page assembly ────────────────────────────────────────────────────────
    def test_the_four_sections_and_what_section_one_holds(self) -> None:
        """The site's four sections, verbatim, and nothing in section one that
        last quarter did not leave.

        The market's consensus is not a line last quarter's analysis set and it
        is not something the company guided, so the chart that reads the quarter
        against it belongs to this quarter's highlights -- beside the GAAP /
        non-GAAP split it explains, which is the report's 「盈利质量」 conclusion.
        It used to sit in section one between the guidance charts.
        """
        self.assertEqual(
            [(section["id"], section["title"]) for section in self.payload["sections"]],
            [("settled", "一、上季跟踪指标兑现了吗"), ("quarter_highlights", "二、本季重点"),
             ("next_quarter", "三、下季要跟踪什么"), ("routine", "四、长期常规跟踪")])

        def reads_the_market(exhibit: dict) -> bool:
            return any("市场预期" in str(label) for label in exhibit.get("xlabels") or [])

        self.assertFalse([ex["title"] for ex in self.by_section["settled"] if reads_the_market(ex)])
        self.assertNotIn("市场预期", self.payload["sections"][0]["description"])
        highlights = self.by_section["quarter_highlights"]
        market = [i for i, ex in enumerate(highlights) if reads_the_market(ex)]
        if self.source.get("followup_closure"):
            self.assertIn("条待验证问题", self.by_section["settled"][0]["title"])
        # The chart is published only in a quarter whose series carries the
        # (period-stamped) expectation and the split it sits beside.
        if self.source.get("market_expectation") is None or self.source.get("restated_comparatives") is None:
            self.assertEqual(market, [], "a consensus chart with no expectation block behind it")
            return
        self.assertEqual(len(market), 1, "the consensus chart went missing or doubled")
        split = next(i for i, ex in enumerate(highlights)
                     if any(group["name"] == "GAAP 净利" for group in ex.get("groups", [])))
        self.assertEqual(market[0], split + 1, "the consensus chart no longer sits beside the split")

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

    def test_the_guided_record_table_covers_every_quarter(self) -> None:
        table = next(item for item in self.payload["tables"] if "指引兑现全表" in item["title"])
        self.assertEqual(len(table["rows"]),
                         len(self.source["quarterly_guidance_history"]["quarters"]))
        self.assertEqual(table["rows"][-1][0], self.source["guidance"]["next_quarter"]["period"])
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
        fiscal = self.source["fiscal_labels"][-1]
        self.assertIn(f"{fiscal[:6]} {fiscal[6:]}", self.payload["subtitle"])
        self.assertTrue(
            any(f"{fiscal[:6]} {fiscal[6:]}" in note for note in self.payload["notes"]),
            "the fiscal/calendar convention is not disclosed in the notes",
        )

    # ── boundary ─────────────────────────────────────────────────────────────
    def test_market_expectation_is_dated_and_sourced_and_names_no_broker(self) -> None:
        consensus = self.source["market_expectation"]
        self.assertIn(self.source["latest"]["release_date"], consensus["as_of"])
        # The note itself flags that this quarter's consensus is second-hand;
        # the page has to carry that caveat rather than quietly drop it.
        self.assertIn("二手", consensus["basis"])
        self.assertTrue(
            any("二手转述" in note for note in self.payload["notes"]),
            "the consensus caveat is not disclosed in the notes",
        )
        # Every chart that prints a consensus figure says where it came from:
        # a figure the page cannot point at is not published.
        for exhibit in self.exhibits:
            if "市场预期" in exhibit.get("note", "") + json.dumps(exhibit.get("xlabels"), ensure_ascii=False):
                self.assertIn(consensus["source"]["label"], exhibit["src_extra"], exhibit["title"])
        # Only the two figures the page already carried: no new consensus content.
        self.assertEqual({k for k in consensus if k.endswith(("_usd_m", "_usd"))},
                         {"revenue_usd_m", "non_gaap_eps_usd"})
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



class NvdaChecksTest(unittest.TestCase):
    """The newest quarter against what the filings print, once, in `_checks`.

    The builder never reads `_checks`; this class is the only reader, so a roll
    that forgets to re-check the new quarter fails here rather than on the page.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "nvda.json").read_text(encoding="utf-8"))
        cls.checks = cls.source["_checks"]
        cls.payload = build_payload(cls.source)
        cls.text = published_text(cls.payload)

    def test_the_page_names_the_checked_quarter(self) -> None:
        self.assertEqual(self.checks["period"], self.source["periods"][-1])
        self.assertEqual(self.checks["period_end"], self.source["period_ends"][-1])
        self.assertEqual(self.checks["release_date"], self.source["latest"]["release_date"])
        self.assertEqual(self.payload["latest"]["disclosed_period_label"], self.checks["period"])
        self.assertIn(self.checks["period_end"], self.payload["subtitle"])
        self.assertTrue(self.checks.get("source"))

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        fin = self.source["financials"]
        self.assertEqual(fin["revenue_usd_m"][-1], self.checks["revenue_usd_m"]["current"])
        self.assertEqual(fin["revenue_usd_m"][-2], self.checks["revenue_usd_m"]["prior_quarter"])
        self.assertEqual(fin["revenue_usd_m"][-5], self.checks["revenue_usd_m"]["year_ago"])
        dc = self.checks["data_center_usd_m"]
        self.assertEqual(self.source["market_platform_usd_m"]["data_center"][-1], dc["current"])
        self.assertEqual(self.source["market_platform_usd_m"]["edge_computing"][-1],
                         self.checks["edge_computing_usd_m"])
        mix = self.source["dc_customer_mix"]
        self.assertEqual(mix["hyperscale"][-1], dc["hyperscale"])
        self.assertEqual(mix["acie"][-1], dc["acie"])
        self.assertEqual(fin["gaap_opex_usd_m"][-1], self.checks["operating_expenses_usd_m"]["gaap"])
        self.assertEqual(fin["non_gaap_opex_usd_m"][-1], self.checks["operating_expenses_usd_m"]["non_gaap"])
        self.assertEqual(fin["gaap_operating_income_usd_m"][-1], self.checks["operating_income_usd_m"]["gaap"])
        self.assertEqual(fin["non_gaap_operating_income_usd_m"][-1],
                         self.checks["operating_income_usd_m"]["non_gaap"])
        self.assertEqual(fin["gaap_net_income_usd_m"][-1], self.checks["net_income_usd_m"]["gaap"])
        self.assertEqual(fin["non_gaap_net_income_usd_m"][-1], self.checks["net_income_usd_m"]["non_gaap"])
        restated = self.source["restated_comparatives"]
        at = restated["quarters"].index(self.checks["period"])
        self.assertEqual(restated["gaap_eps_usd"][at], self.checks["diluted_eps_usd"]["gaap"])
        self.assertEqual(restated["non_gaap_eps_usd"][at], self.checks["diluted_eps_usd"]["non_gaap"])
        self.assertEqual(restated["equity_securities_gains_usd_m"][at],
                         self.checks["equity_securities_gains_usd_m"])
        cash = self.source["cash_flow_usd_m"]
        self.assertEqual(cash["operating_cash_flow"][-1], self.checks["cash_flow_usd_m"]["operating"])
        self.assertEqual(cash["free_cash_flow"][-1], self.checks["cash_flow_usd_m"]["free"])
        commitments = self.source["total_supply_usd_bn"]["supply_related_commitments"]
        self.assertEqual(commitments[-1], self.checks["commitments_usd_bn"]["current"])
        self.assertEqual(commitments[-2], self.checks["commitments_usd_bn"]["prior_quarter"])
        # The readings section three measures its lines against.
        guarantees = self.source["guarantee_exposure_usd_bn"]
        self.assertEqual(guarantees["quarters"][-1], self.checks["period"])
        self.assertEqual(guarantees["max_gross_exposure"][-1],
                         self.checks["guarantee_max_exposure_usd_bn"]["current"])
        self.assertEqual(guarantees["max_gross_exposure"][-2],
                         self.checks["guarantee_max_exposure_usd_bn"]["prior_quarter"])
        other = self.source["other_income_usd_m"]
        self.assertEqual(other["quarters"][-1], self.checks["period"])
        self.assertEqual(other["total_other_income"][-1], self.checks["other_income_usd_m"]["current"])
        self.assertEqual(other["total_other_income"][-2], self.checks["other_income_usd_m"]["prior_quarter"])
        receivables = self.source["long_history"]["accounts_receivable_usd_m"]
        self.assertEqual(receivables[-1], self.checks["accounts_receivable_usd_m"]["current"])
        self.assertEqual(receivables[-2], self.checks["accounts_receivable_usd_m"]["prior_quarter"])
        # The company's own DSO, printed in whole days.
        self.assertEqual(self.source["working_capital"]["dso_days_printed"][-2:],
                         [self.checks["dso_days_printed"]["prior_quarter"],
                          self.checks["dso_days_printed"]["current"]])

    def test_the_other_income_record_adds_up_to_each_fiscal_year(self) -> None:
        """Four quarters of other income against the 10-K's full year, for every complete fiscal year.

        The quarters come from the 10-Qs and the February releases, the years
        from the 10-Ks -- different documents, so a quarter copied from the
        wrong column or a year-to-date figure taken for a quarter shows up here.
        The page labels a fiscal year by the calendar year it mostly covers, so
        page year Y is fiscal Y+1. Each total line is the sum of three lines
        rounded one by one, so a year can miss by more than one: measured, the
        widest gap is US$2M, in FY2018 (interest income 68 over the quarters
        against 69 for the year, other, net -23 against -22).
        """
        other = self.source["other_income_usd_m"]
        self.assertEqual(other["quarters"], self.source["long_history"]["quarters"])
        years: dict[str, list[int]] = {}
        for quarter, value in zip(other["quarters"], other["total_other_income"]):
            years.setdefault(f"FY{int(quarter[-4:]) + 1}", []).append(value)
        totals = self.checks["other_income_usd_m"]["fiscal_year_totals"]
        self.assertTrue(self.checks["other_income_usd_m"].get("fiscal_year_source"))
        gaps = {}
        for year, total in totals.items():
            self.assertEqual(len(years[year]), 4, year)
            gaps[year] = sum(years[year]) - total
        self.assertLessEqual(max(abs(gap) for gap in gaps.values()), 2, gaps)
        complete = [year for year, values in years.items() if len(values) == 4]
        self.assertEqual(sorted(totals), sorted(complete), "a complete fiscal year has no 10-K total to add up to")

    def test_the_outlook_is_the_checked_outlook(self) -> None:
        guide = self.source["guidance"]["next_quarter"]
        for key, value in self.checks["next_quarter"].items():
            self.assertEqual(guide[key], value, key)
        history = self.source["quarterly_guidance_history"]
        at = history["quarters"].index(self.checks["period"])
        prior = self.checks["prior_outlook_for_this_quarter"]
        self.assertEqual(history["guide_revenue_usd_bn"][at], prior["revenue_usd_bn"])
        self.assertEqual(history["gaap_gm_guide_pct"][at], prior["gaap_gross_margin_pct"])
        self.assertEqual(history["non_gaap_gm_guide_pct"][at], prior["non_gaap_gross_margin_pct"])
        self.assertEqual(history["gaap_opex_guide_usd_bn"][at], prior["gaap_opex_usd_bn"])
        self.assertEqual(history["non_gaap_opex_guide_usd_bn"][at], prior["non_gaap_opex_usd_bn"])
        tax = self.source["guidance"]["tax_rate"]
        self.assertEqual(tax["fiscal_year"], self.checks["tax_rate_pct"]["fiscal_year"])
        self.assertEqual(tax["current_pct"], self.checks["tax_rate_pct"]["range"])

    def test_the_page_prints_the_checked_figures(self) -> None:
        """Compared at the precision the company prints."""
        fin = self.source["financials"]
        revenue = fin["revenue_usd_m"]
        printed = self.checks["revenue_growth_printed_pct"]
        self.assertEqual(round((revenue[-1] / revenue[-2] - 1) * 100), printed["qoq"])
        self.assertEqual(round((revenue[-1] / revenue[-5] - 1) * 100), printed["yoy"])
        dc = self.source["market_platform_usd_m"]["data_center"]
        self.assertEqual(round((dc[-1] / dc[-5] - 1) * 100), self.checks["data_center_usd_m"]["yoy_printed_pct"])
        self.assertEqual(round(fin["gaap_gross_margin_pct"][-1], 1), self.checks["gross_margin_printed_pct"]["gaap"])
        self.assertEqual(round(fin["non_gaap_gross_margin_pct"][-1], 1),
                         self.checks["gross_margin_printed_pct"]["non_gaap"])
        dso = self.source["working_capital"]["dso_days"]
        self.assertEqual(round(dso[-1]), self.checks["dso_days_printed"]["current"])
        self.assertEqual(round(dso[-2]), self.checks["dso_days_printed"]["prior_quarter"])
        working = self.source["working_capital"]
        self.assertEqual(round(working["accounts_receivable_usd_m"][-1] / 1000, 1),
                         self.checks["accounts_receivable_usd_bn_printed"])
        self.assertEqual(round(working["inventories_usd_m"][-1] / 1000, 1), self.checks["inventory_usd_bn_printed"])
        self.assertIn(f"收入 US${revenue[-1] / 1000:.1f}B", self.payload["headline"])
        self.assertIn(f"US${self.checks['next_quarter']['revenue_usd_bn']:.1f}B", self.text)
        # The capital return is the cash-flow-statement sum; the release rounds
        # it to "approximately $26.0 billion". Same number at whole billions.
        returned = self.source["capital_return_usd_m"]["total"][-1] / 1000
        self.assertEqual(round(returned), round(self.checks["returned_to_shareholders_usd_bn_printed"]))


# The report's trigger side of a line, from the page's favourable side: a buy,
# milestone or upside line triggers on the favourable side, every other line
# on the opposite one.
FAVOURABLE_SIDE = {("up", True): ">", ("up", False): ">=", ("down", True): "<", ("down", False): "<="}
OPPOSITE = {">": "<=", ">=": "<", "<": ">=", "<=": ">"}
REACHING = ("加仓", "里程碑", "上行")
LINE_NAMES = {"加仓": "加仓线", "减仓": "减仓线", "警示": "警示线", "重新评估": "重新评估线",
              "里程碑": "里程碑", "上行": "上行线", "撤回立场": "撤销线"}
NO_HISTORY = {"revenue_beat_pct"}


def trigger_of(line: dict) -> str:
    side = FAVOURABLE_SIDE[(line["direction"], bool(line.get("strict")))]
    return side if line["action"] in REACHING else OPPOSITE[side]


def on_favourable_side(line: dict, value: float) -> bool:
    return {">": value > line["threshold"], ">=": value >= line["threshold"],
            "<": value < line["threshold"], "<=": value <= line["threshold"]}[
        FAVOURABLE_SIDE[(line["direction"], bool(line.get("strict")))]]


def raw_reading(source: dict, reads: str) -> float:
    """Each reading recomputed from the raw arrays, without the builder's `reading`."""
    fin = source["financials"]
    guide = source["quarterly_guidance_history"]
    period = source["periods"][-1]
    if reads == "revenue_bn":
        return fin["revenue_usd_m"][-1] / 1000
    if reads == "revenue_beat_pct":
        at = guide["quarters"].index(period)
        return (guide["actual_revenue_usd_m"][at] / guide["guide_revenue_usd_bn"][at] / 1000 - 1) * 100
    if reads == "acie_share_pct":
        mix = source["dc_customer_mix"]
        return mix["acie"][-1] / (mix["acie"][-1] + mix["hyperscale"][-1]) * 100
    if reads == "ng_gm_pct":
        return fin["non_gaap_gross_profit_usd_m"][-1] / fin["revenue_usd_m"][-1] * 100
    if reads == "ng_gm_guide_pct":
        return guide["non_gaap_gm_guide_pct"][-1]
    if reads == "dso_printed_days":
        return float(source["working_capital"]["dso_days_printed"][-1])
    if reads == "dso_days":
        return source["working_capital"]["accounts_receivable_usd_m"][-1] / fin["revenue_usd_m"][-1] * 91
    if reads == "total_supply_bn":
        supply = source["total_supply_usd_bn"]
        return supply["inventory"][-1] + supply["supply_related_commitments"][-1]
    if reads == "fcf_conversion_pct":
        return source["fcf_conversion"]["values_pct"][-1]
    if reads == "guarantee_bn":
        return source["guarantee_exposure_usd_bn"]["max_gross_exposure"][-1]
    if reads == "top_customer_pct":
        return float(source["customer_concentration"]["largest_direct_customer_pct"][-1])
    if reads == "fcf_bn":
        return source["cash_flow_usd_m"]["free_cash_flow"][-1] / 1000
    if reads == "other_income_bn":
        return source["other_income_usd_m"]["total_other_income"][-1] / 1000
    raise KeyError(reads)


class NvdaSettlementTest(unittest.TestCase):
    """Section one settles what the previous report left, as the reports wrote it.

    The expected verdicts and lines are read from `_checks["note"]`, which was
    typed from the two reports independently of the blocks the builder reads;
    every reading is recomputed here from the raw arrays.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "nvda.json").read_text(encoding="utf-8"))
        cls.note = cls.source["_checks"]["note"]
        cls.payload = build_payload(cls.source)
        cls.settled = cls.payload["sections"][0]["exhibits"]
        cls.text = published_text(cls.payload)

    def test_the_closure_is_the_reports_section_zero(self) -> None:
        block = self.source["followup_closure"]
        expected = self.note["followup_closure"]
        self.assertEqual(block["set_in"], self.source["periods"][-2])
        self.assertEqual(block["total"], expected["total"])
        self.assertEqual([item["verdict"] for item in block["items"]], expected["verdicts"])
        self.assertEqual(dict(zip(block["labels"], block["counts"])), expected["counts"])
        chart = self.settled[0]
        self.assertEqual(chart["kind"], "bars_labeled")
        self.assertTrue(chart["title"].startswith(f"上季 {expected['total']} 条待验证问题："))
        # The title lists every category the report used, with its count.
        for label, count in expected["counts"].items():
            self.assertIn(f"{count} 条{label}", chart["title"])
        self.assertEqual(sum(chart["values"]), expected["total"])
        # Each question is on the page with its verdict, and the verdict is
        # attributed to the report, not to the page.
        for number, item in enumerate(block["items"], 1):
            self.assertIn(f"{number}. {item['question']} —— <b>{item['verdict']}</b>", chart["note"])
        self.assertIn("第 0 节", chart["src_extra"])
        self.assertNotIn("本页据此", chart["note"])

    def test_the_prior_lines_are_the_prior_reports_section_eight(self) -> None:
        block = self.source["prior_kpi_settlement"]
        self.assertEqual(block["set_in"], self.source["periods"][-2])
        self.assertEqual(len(block["rows"]), self.note["prior_rows"])
        self.assertEqual(len(block["dispositions"]), self.note["prior_rows"])
        expected = {(item["row"], item["threshold"]): item for item in self.note["prior_thresholds"]}
        drawn = {(line["row"], line["threshold"]): line for line in block["quantified"]}
        self.assertEqual(set(drawn), set(expected), "a line was added, dropped or retyped")
        for key, line in drawn.items():
            with self.subTest(line=line["id"]):
                self.assertEqual(trigger_of(line), expected[key]["trigger"])
                self.assertEqual(line["action"], expected[key]["action"])
        self.assertEqual(sorted(item["row"] for item in block["not_drawn"]),
                         self.note["prior_not_quantified_rows"])
        self.assertEqual({str(c["row"]): c["mode"] for c in block["conditions"]},
                         self.note["prior_compound_rows"])

    def test_the_prior_readings_are_recomputed_here(self) -> None:
        block = self.source["prior_kpi_settlement"]
        every = block["quantified"]
        # A line at zero has no percentage headroom: it is drawn on its series,
        # not in the overview (next quarter's block moves here with one).
        lines = [line for line in every if line["threshold"] != 0]
        overview = next(ex for ex in self.settled if ex["kind"] == "diverging_bars" and "量化阈值" in ex["title"])
        self.assertEqual(overview["xlabels"], [line["metric"] for line in lines])
        favourable = on_line = 0
        for line, bar in zip(lines, overview["values"]):
            value = raw_reading(self.source, line["reads"])
            self.assertAlmostEqual(bar, round(headroom(line["direction"], line["threshold"], value), 1),
                                   places=1, msg=line["id"])
            favourable += on_favourable_side(line, value)
            on_line += on_favourable_side(line, value) and value == line["threshold"]
        # A reading on a line it has not crossed counts as favourable, and the
        # aside that says so sits with that count.
        self.assertIn(f"{favourable} 条在有利一侧" + (f"（其中 {on_line} 条正压在线上）" if on_line else "")
                      + f"、{len(lines) - favourable} 条在不利一侧", overview["title"])
        # One history per reading that has one, every line of its row on it.
        charts = [ex for ex in self.settled if ex["kind"] == "lines"]
        by_reads = {}
        for line in every:
            by_reads.setdefault(line["reads"], []).append(line)
        # The one reading the page has no history for: the beat is a ratio of
        # two records, not a series of its own.
        drawn_reads = [reads for reads in by_reads if reads not in NO_HISTORY]
        self.assertEqual(len(charts), len(drawn_reads))
        for chart, reads in zip(charts, drawn_reads):
            for line in by_reads[reads]:
                value = raw_reading(self.source, line["reads"])
                name = LINE_NAMES[line["action"]]
                with self.subTest(line=line["id"]):
                    if str(line["id"]) in {i for c in block["conditions"] if c["mode"] == "and" for i in c["ids"]}:
                        verb = "未越过" if on_favourable_side(line, value) else "越过"
                        self.assertIn(f"{verb}上季合取条件之一", chart["title"])
                    elif on_favourable_side(line, value) and value == line["threshold"]:
                        self.assertIn(f"正压在上季{name}", chart["title"])
                    elif line["action"] in REACHING:
                        self.assertIn(("达到" if on_favourable_side(line, value) else "没到") + f"上季{name}",
                                      chart["title"])
                    else:
                        self.assertIn(("守住" if on_favourable_side(line, value) else "击穿") + f"上季{name}",
                                      chart["title"])
                    threshold_series = [s for s in chart["series"] if s["values"] == [line["threshold"]] * len(chart["xlabels"])]
                    self.assertEqual(len(threshold_series), 1, "each line is its own series")
        # The compound row: 「且」 needs both legs over their lines.
        for condition in block["conditions"]:
            legs = [next(l for l in every if l["id"] == i) for i in condition["ids"]]
            over = [not on_favourable_side(l, raw_reading(self.source, l["reads"])) for l in legs]
            met = all(over) if condition["mode"] == "and" else any(over)
            self.assertIn("<b>条件成立</b>" if met else "<b>条件不成立</b>", overview["note"])

    def test_history_is_counted_against_ratio_lines_only(self) -> None:
        """A margin line reads the same on any quarter; a dollar line was set for one quarter of a growing series.

        So a count of earlier quarters on the wrong side is printed for the
        first and never for the second -- seven quarters of revenue under this
        quarter's buy line would only say that revenue grew.
        """
        lines = self.source["prior_kpi_settlement"]["quantified"]
        charts = [ex for ex in self.settled if ex["kind"] == "lines"]
        for chart in charts:
            group = [l for l in lines
                     if any(s["values"] == [l["threshold"]] * len(chart["xlabels"]) for s in chart["series"])]
            drawn = [v for v in chart["series"][0]["values"] if v is not None]
            with self.subTest(chart=chart["title"]):
                if all(l["unit"].startswith("usd") for l in group):
                    self.assertNotIn("不利的一侧", chart["note"])
                    continue
                for line in group:
                    count = sum(1 for v in drawn if not on_favourable_side(line, v))
                    self.assertIn(("没有一季" if count == 0 else f"{count} 季") + "落在", chart["note"])
                self.assertIn(f"图上 {len(drawn)} 季里", chart["note"])

    def test_every_prior_row_is_settled_or_explained(self) -> None:
        block = self.source["prior_kpi_settlement"]
        table = next(t for t in self.payload["tables"] if t["title"].startswith("上季第 8 节"))
        self.assertEqual([row[1] for row in table["rows"]], block["rows"])
        self.assertEqual([row[3] for row in table["rows"]], block["dispositions"])
        for row in table["rows"]:
            self.assertTrue(row[2].strip(), row[0])
        for item in block["not_drawn"]:
            self.assertIn("不作图", table["rows"][item["row"] - 1][2])

    def test_the_guarantee_record_has_the_base_the_page_once_denied(self) -> None:
        """The previous 10-Q printed a maximum guarantee exposure; the page used to say it printed none."""
        record = self.source["guarantee_exposure_usd_bn"]
        self.assertEqual(record["quarters"][-1], self.source["periods"][-1])
        self.assertIn(self.source["periods"][-2], record["quarters"])
        self.assertIsNotNone(record["max_gross_exposure"][record["quarters"].index(self.source["periods"][-2])])
        for claim in ("没有任何担保上限披露", "没有可比的上季基数"):
            self.assertNotIn(claim, self.text)

    def test_a_malformed_settlement_block_stops_the_build(self) -> None:
        def rebuilt(edit) -> None:
            changed = copy.deepcopy(self.source)
            edit(changed)
            build_payload(changed)

        def uncovered_row(s: dict) -> None:
            block = s["prior_kpi_settlement"]
            block["rows"].append("（演练）没人处理的一行")
            block["dispositions"].append("（演练）")

        cases = [
            ("set in", lambda s: s["prior_kpi_settlement"].__setitem__("set_in", "Q4 2025")),
            ("types a reading", lambda s: s["prior_kpi_settlement"]["quantified"][0].__setitem__("value", 1.0)),
            ("no series on this page", lambda s: s["prior_kpi_settlement"]["quantified"][0].__setitem__("reads", "x")),
            # A row nothing draws, explains or conditions on -- made by adding
            # one, so the case does not depend on which rows this quarter's
            # block happens to leave uncovered once a not_drawn item goes.
            ("accounted for", uncovered_row),
            ("should have been settled", lambda s: s["prior_kpi_settlement"]["quantified"][0].__setitem__(
                "settles", "Q1 2026")),
            ("disagree", lambda s: s["followup_closure"].__setitem__("total", 7)),
            ("does not match", lambda s: s["followup_closure"]["items"][0].__setitem__("verdict", "被证伪")),
        ]
        for words, edit in cases:
            with self.subTest(words):
                with self.assertRaisesRegex(ValueError, words):
                    rebuilt(edit)


class NvdaNextQuarterTest(unittest.TestCase):
    """Section three is this quarter's report's section 8, every tier its own line."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "nvda.json").read_text(encoding="utf-8"))
        cls.note = cls.source["_checks"]["note"]
        cls.block = cls.source["next_kpi"]
        cls.payload = build_payload(cls.source)
        cls.section = cls.payload["sections"][2]["exhibits"]

    def test_the_next_lines_are_the_reports_section_eight(self) -> None:
        block = self.block
        self.assertEqual(len(block["rows"]), self.note["next_rows"])
        self.assertEqual(block["revocation_rows"], self.note["next_revocation_rows"])
        expected = {(item["row"], item["threshold"]): item for item in self.note["next_thresholds"]}
        lines = {(line["row"], line["threshold"]): line for line in block["quantified"]}
        self.assertEqual(set(lines), set(expected), "a line was added, dropped or retyped")
        for key, line in lines.items():
            with self.subTest(line=line["id"]):
                self.assertEqual(trigger_of(line), expected[key]["trigger"])
                self.assertEqual(line["action"], expected[key]["action"])
                self.assertEqual(line.get("consecutive"), expected[key].get("consecutive"))
                self.assertEqual(line["settles"], shift_quarter(self.source["periods"][-1], 1))
        self.assertEqual({str(c["row"]): [{"or": "或", "and": "且"}[c["mode"]], len(c["ids"])]
                          for c in block["conditions"]}, self.note["next_conditions"])
        self.assertEqual([item["row"] for item in block["not_drawn"]],
                         [item["row"] for item in self.note["next_not_quantified"]])

    def test_the_overview_is_recomputed_here(self) -> None:
        lines = [line for line in self.block["quantified"] if line["threshold"] != 0]
        overview = self.section[0]
        self.assertEqual(overview["kind"], "diverging_bars")
        self.assertEqual(overview["xlabels"], [line["metric"] for line in lines])
        favourable = on_line = 0
        for line, bar in zip(lines, overview["values"]):
            value = raw_reading(self.source, line["reads"])
            self.assertAlmostEqual(bar, round(headroom(line["direction"], line["threshold"], value), 1),
                                   places=1, msg=line["id"])
            if value == line["threshold"]:
                on_line += 1
            elif on_favourable_side(line, value):
                favourable += 1
        self.assertIn(f"下季 {len(lines)} 条量化阈值：{favourable} 条在有利一侧、"
                      f"{len(lines) - favourable - on_line} 条在线外", overview["title"])
        for line in self.block["quantified"]:
            if line["threshold"] == 0:
                self.assertIn(f"「{line['metric']}」的阈值是 0", overview["note"])

    def test_every_reading_gets_one_chart_with_every_line(self) -> None:
        groups: dict[str, list[dict]] = {}
        for line in self.block["quantified"]:
            groups.setdefault(line["reads"], []).append(line)
        charts = self.section[1:]
        self.assertEqual(len(charts), len(groups), "every reading here has a history to draw")
        for chart, (reads, group) in zip(charts, groups.items()):
            with self.subTest(reads=reads):
                self.assertIn("下季阈值", chart["title"])
                for line in group:
                    flat = [s for s in chart["series"] if s["values"] == [line["threshold"]] * len(chart["xlabels"])]
                    self.assertEqual(len(flat), 1, f"{line['id']} is not its own series")
                    self.assertEqual(flat[0]["color"], "GOLD" if line["action"] in REACHING else "RED")
                self.assertIn("本季报告原文：", chart["note"])

    def test_the_drawer_accounts_for_every_row(self) -> None:
        table = next(t for t in self.payload["tables"] if t["title"].startswith("下季阈值与当前值"))
        numbers = {row[0] for row in table["rows"]}
        self.assertEqual(numbers, {cn_ordinal(n) for n in range(1, len(self.block["rows"]) + 1)})
        for condition in self.block["conditions"]:
            self.assertTrue(any(row[0] == cn_ordinal(condition["row"]) and row[1].endswith("条件")
                                for row in table["rows"]), condition["row"])
        for item in self.block["not_drawn"]:
            self.assertTrue(any(row[1] == item["metric"] and row[-1].startswith("不作图") for row in table["rows"]))

    def test_the_dso_line_is_drawn_on_the_whole_receivables_record(self) -> None:
        long = self.source["long_history"]
        working = self.source["working_capital"]
        # The long record's last eight quarter-ends are the window's balances.
        self.assertEqual(long["accounts_receivable_usd_m"][-len(working["accounts_receivable_usd_m"]):],
                         working["accounts_receivable_usd_m"])
        dso = [ar / rev * 91 for ar, rev in zip(long["accounts_receivable_usd_m"], long["revenue_usd_m"])]
        for mine, theirs in zip(dso[-len(working["dso_days"]):], working["dso_days"]):
            self.assertAlmostEqual(mine, theirs, places=3)
        # Whichever lines this quarter's report draws on DSO (a later report
        # may draw none), their chart runs the whole record.
        group = [line for line in self.block["quantified"] if line["reads"] == "dso_days"]
        if not group:
            return
        chart = self.chart_of(group[0])
        self.assertEqual(len(chart["xlabels"]), len(long["quarters"]))
        cut = next((line for line in group if line["action"] == "减仓"), None)
        if cut is not None:
            over = [compact_period(q) for q, d in zip(long["quarters"], dso) if d >= cut["threshold"]]
            self.assertIn(f"{len(dso)} 季里 DSO 到过", chart["note"])
            if over:
                self.assertIn(f"有 {len(over)} 季（{'、'.join(over)}）", chart["note"])

    def test_the_other_income_line_is_drawn_on_the_whole_record(self) -> None:
        """The revocation line at zero, against every quarter back to 2016 -- counted here, not by the builder."""
        other = self.source["other_income_usd_m"]
        self.assertEqual(other["quarters"], self.source["long_history"]["quarters"])
        group = [line for line in self.block["quantified"] if line["reads"] == "other_income_bn"]
        if not group:
            return
        chart = self.chart_of(group[0])
        self.assertEqual(chart["xlabels"], [compact_period(q) for q in other["quarters"]])
        self.assertEqual(chart["xlabels"][0], "Q1'16")
        negative = [i for i, value in enumerate(other["total_other_income"]) if value < 0]
        self.assertGreater(len(negative), 4, "the sentence below is the long form; a short list is printed instead")
        since = len(other["quarters"]) - 1 - negative[-1]
        self.assertIn(f"图上 {len(other['quarters'])} 季里为负的有 {len(negative)} 季，"
                      f"最近一次是 {compact_period(other['quarters'][negative[-1]])}"
                      + (f"，此后 {since} 季都为正。" if since else "，也就是本季。"),
                      chart["note"])

    def chart_of(self, line: dict) -> dict:
        """The section-three chart that draws a line: the one carrying it as a flat series."""
        return next(ex for ex in self.section[1:]
                    if any(s["values"] == [line["threshold"]] * len(ex["xlabels"]) for s in ex["series"]))

    def test_a_line_that_is_due_cannot_sit_in_next_kpi(self) -> None:
        broken = copy.deepcopy(self.source)
        broken["next_kpi"]["quantified"][0]["settles"] = broken["periods"][-1]
        with self.assertRaisesRegex(ValueError, "belongs in prior_kpi_settlement"):
            build_payload(broken)


def rolled_forward(source: dict, growth: float, overrides: dict | None = None) -> dict:
    """The series one quarter on, edited the way a roll edits it -- and only the series.

    Every aligned array gains the new quarter (its year-ago value, flows times
    ``growth``, ratios and days unchanged) and drops its oldest; the long and
    guided records grow; this quarter's section-8 block moves into
    `prior_kpi_settlement` unchanged but for `set_in` and a disposition per row;
    the quarter's one-off blocks are dropped; a stand-in section 8 settles one
    quarter later. ``overrides`` replaces named readings in the new quarter.
    """
    s = copy.deepcopy(source)
    overrides = overrides or {}
    period = s["periods"][-1]
    new = shift_quarter(period, 1)
    fiscal = s["fiscal_labels"][-1]
    year, number = int(fiscal[2:6]), int(fiscal[-1])
    new_fiscal = f"FY{year}Q{number + 1}" if number < 4 else f"FY{year + 1}Q1"
    back = -4                                   # the new quarter a year earlier

    def extend(values: list, value) -> None:
        values.append(value)
        del values[0]

    fin = s["financials"]
    revenue = fin["revenue_usd_m"][back] * growth
    flows = ("gaap_opex_usd_m", "gaap_operating_income_usd_m", "gaap_net_income_usd_m",
             "non_gaap_gross_profit_usd_m", "non_gaap_opex_usd_m", "non_gaap_operating_income_usd_m",
             "non_gaap_net_income_usd_m")
    for key in flows:
        extend(fin[key], fin[key][back] * growth)
    for key in ("gaap_gross_margin_pct", "gaap_operating_margin_pct", "non_gaap_gross_margin_pct"):
        extend(fin[key], overrides.get(key, fin[key][back]))
    extend(fin["revenue_yoy_pct"], (growth - 1) * 100)
    extend(fin["revenue_usd_m"], revenue)
    # A margin override moves the dollars under it, so the identities still hold.
    fin["non_gaap_gross_profit_usd_m"][-1] = revenue * fin["non_gaap_gross_margin_pct"][-1] / 100
    fin["non_gaap_operating_income_usd_m"][-1] = (fin["non_gaap_gross_profit_usd_m"][-1]
                                                  - fin["non_gaap_opex_usd_m"][-1])
    for key in ("data_center", "edge_computing"):
        extend(s["market_platform_usd_m"][key], s["market_platform_usd_m"][key][back] * growth)
    cash = s["cash_flow_usd_m"]
    for key in ("operating_cash_flow", "free_cash_flow"):
        extend(cash[key], overrides.get(key, cash[key][back] * growth))
    working = s["working_capital"]
    receivable = revenue * overrides.get("dso_days", working["dso_days"][back]) / 91
    extend(working["accounts_receivable_usd_m"], receivable)
    extend(working["inventories_usd_m"], working["inventories_usd_m"][back] * growth)
    extend(working["dso_days"], receivable / revenue * 91)
    extend(working["dso_days_printed"], round(receivable / revenue * 91))
    extend(s["periods"], new)
    extend(s["period_ends"], {"Q3 2026": "2026-10-25", "Q4 2026": "2027-01-31"}.get(new, "2099-12-31"))
    extend(s["fiscal_labels"], new_fiscal)
    long = s["long_history"]
    long["quarters"].append(new)
    long["revenue_usd_m"].append(revenue)
    long["gaap_gross_margin_pct"].append(fin["gaap_gross_margin_pct"][-1])
    long["gaap_operating_margin_pct"].append(fin["gaap_operating_margin_pct"][-1])
    long["opex_intensity_pct"].append(fin["gaap_gross_margin_pct"][-1] - fin["gaap_operating_margin_pct"][-1])
    long["accounts_receivable_usd_m"].append(receivable)
    guide = s["quarterly_guidance_history"]
    at = guide["quarters"].index(new)
    guide["actual_revenue_usd_m"][at] = revenue
    guide["actual_gaap_gm_pct"][at] = fin["gaap_gross_margin_pct"][-1]
    guide["actual_non_gaap_gm_pct"][at] = fin["non_gaap_gross_margin_pct"][-1]
    guide["actual_non_gaap_opex_usd_m"][at] = fin["non_gaap_opex_usd_m"][-1]
    guide["actual_non_gaap_operating_income_usd_m"][at] = fin["non_gaap_operating_income_usd_m"][-1]
    following = shift_quarter(new, 1)
    for key, values in guide.items():
        if isinstance(values, list) and key != "quarters":
            values.append(None if key.startswith("actual_") else values[-1])
    guide["quarters"].append(following)
    guide["guide_revenue_usd_bn"][-1] = round(revenue / 1000 * 1.05, 1)
    guide["non_gaap_gm_guide_pct"][-1] = overrides.get("gm_guide", guide["non_gaap_gm_guide_pct"][-2])
    g = s["guidance"]
    g["period"] = new
    g["next_quarter"].update({"period": following, "fiscal_label": "next", "revenue_usd_bn": guide["guide_revenue_usd_bn"][-1],
                              "non_gaap_gross_margin_pct": guide["non_gaap_gm_guide_pct"][-1],
                              "gaap_gross_margin_pct": guide["gaap_gm_guide_pct"][-1],
                              "non_gaap_opex_usd_bn": guide["non_gaap_opex_guide_usd_bn"][-1],
                              "gaap_opex_usd_bn": guide["gaap_opex_guide_usd_bn"][-1]})
    g.pop("call_only", None)
    conversion = s["fcf_conversion"]
    conversion["quarters"].append(new)
    conversion["values_pct"].append(cash["free_cash_flow"][-1] / fin["non_gaap_net_income_usd_m"][-1] * 100)
    if new_fiscal.endswith("Q4"):
        s["customer_concentration"]["missing_quarters"].append(new)
    else:
        concentration = s["customer_concentration"]
        concentration["quarters"].append(new)
        concentration["largest_direct_customer_pct"].append(overrides.get("top_customer", 16))
        concentration["customers_at_or_above_10pct"].append(1)
    supply = s["total_supply_usd_bn"]
    supply["quarters"].append(new)
    supply["inventory"].append(supply["inventory"][-1] * growth)
    supply["supply_related_commitments"].append(supply["supply_related_commitments"][-1])
    guarantees = s["guarantee_exposure_usd_bn"]
    guarantees["quarters"].append(new)
    guarantees["max_gross_exposure"].append(overrides.get("guarantee", guarantees["max_gross_exposure"][-1]))
    other = s["other_income_usd_m"]
    other["quarters"].append(new)
    other["total_other_income"].append(overrides.get("other_income", other["total_other_income"][-4] * growth))
    s["latest"].update({"period": new, "release_date": "2026-11-17", "analysis_date": "2026-11-20"})
    s["sources"].insert(0, {"label": f"NVIDIA Q{new_fiscal[-1]} {new_fiscal[:6]} 业绩新闻稿（演练）",
                            "url": "https://www.sec.gov/"})
    # Section 8 moves; its narrative does not.
    moved = copy.deepcopy(s["next_kpi"])
    s["prior_kpi_settlement"] = {
        "period": new, "set_in": period, "source_section": moved["source_section"], "rows": moved["rows"],
        "quantified": moved["quantified"], "conditions": moved.get("conditions", []),
        "not_drawn": moved.get("not_drawn", []), "dispositions": ["（演练）"] * len(moved["rows"])}
    stand_in = copy.deepcopy(moved)
    stand_in["period"] = new
    for key in ("chart_notes", "note"):
        stand_in.pop(key, None)
    for line in stand_in["quantified"]:
        line["settles"] = following
    s["next_kpi"] = stand_in
    for key in ("followup_closure", "dc_customer_mix", "restated_comparatives", "balance_sheet_exposure",
                "capital_return_usd_m", "quarter_story", "market_expectation"):
        s.pop(key, None)
    return s


class NvdaRollRehearsalTest(unittest.TestCase):
    """Next quarter is a series edit: the page builds and settles this quarter's lines."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "nvda.json").read_text(encoding="utf-8"))

    def settle_checked(self, rolled: dict) -> dict:
        payload = build_payload(rolled)
        self.assertEqual([s["id"] for s in payload["sections"]],
                         ["settled", "quarter_highlights", "next_quarter", "routine"])
        self.assertTrue(all(s["exhibits"] for s in payload["sections"]))
        text = published_text(payload)
        self.assertIsNone(re.search(r"\{[A-Za-z_:]+\}", text))
        self.assertNotIn("_checks", text)
        self.assertIsNone(re.search(r"-0\.0+(?!\d)", text), "a negative zero reached the rolled page")
        prior = rolled["prior_kpi_settlement"]
        lines = [line for line in prior["quantified"] if line["threshold"] != 0]
        overview = next(ex for ex in payload["sections"][0]["exhibits"] if ex["title"].startswith("上季 "))
        self.assertEqual(overview["xlabels"], [line["metric"] for line in lines])
        for line, bar in zip(lines, overview["values"]):
            value = raw_reading(rolled, line["reads"])
            self.assertAlmostEqual(bar, round(headroom(line["direction"], line["threshold"], value), 1), places=1)
        charts = [ex for ex in payload["sections"][0]["exhibits"] if ex["kind"] == "lines"]
        for line in prior["quantified"]:
            chart = next(c for c in charts if any(s["values"] == [line["threshold"]] * len(c["xlabels"])
                                                  for s in c["series"]))
            value = raw_reading(rolled, line["reads"])
            ok = on_favourable_side(line, value)
            name = LINE_NAMES[line["action"]]
            if line.get("consecutive") and not ok:
                continue          # the run is checked in its own test below
            if ok and value == line["threshold"]:
                self.assertIn(f"正压在上季{name}", chart["title"])
            elif line["action"] in REACHING:
                self.assertIn(("达到" if ok else "没到") + f"上季{name}", chart["title"])
            else:
                self.assertIn(("守住" if ok else "击穿") + f"上季{name}", chart["title"])
        for condition in prior["conditions"]:
            over = [not on_favourable_side(l, raw_reading(rolled, l["reads"]))
                    for l in prior["quantified"] if l["id"] in condition["ids"]]
            met = all(over) if condition["mode"] == "and" else any(over)
            self.assertIn("<b>条件成立</b>" if met else "<b>条件不成立</b>", overview["note"])
        return payload

    def test_flat_growing_and_stressed_quarters_all_build_and_settle(self) -> None:
        for name, growth, overrides in (
                ("flat", 1.0, {}),
                ("growth", 1.9, {}),
                ("stress", 1.5, {"dso_days": 72.0, "free_cash_flow": 12000.0, "non_gaap_gross_margin_pct": 73.0,
                                 "gm_guide": 70.5, "guarantee": 160.0, "other_income": -500.0,
                                 "top_customer": 22}),
                # A reading a hair under its line: the headroom rounds to zero
                # and must print as +0.0%, not the "-0.0%" it once did.
                ("hairline", 1.0, {"non_gaap_gross_margin_pct": 73.4999})):
            with self.subTest(name):
                rolled = rolled_forward(self.source, growth, overrides)
                payload = self.settle_checked(rolled)
                self.assertIn(rolled["periods"][-1], payload["title"])

    def test_two_quarters_below_the_conversion_line_trigger_it(self) -> None:
        rolled = rolled_forward(self.source, 1.2, {"free_cash_flow": 5000.0})
        payload = self.settle_checked(rolled)
        conversion = rolled["fcf_conversion"]["values_pct"]
        line = next(l for l in rolled["prior_kpi_settlement"]["quantified"] if l.get("consecutive"))
        self.assertTrue(all(v < line["threshold"] for v in conversion[-line["consecutive"]:]))
        text = published_text(payload)
        self.assertIn("击穿上季重新评估线", text)
        # One quarter below after one above is a run of one: not triggered yet.
        source = copy.deepcopy(self.source)
        source["fcf_conversion"]["values_pct"][-1] = line["threshold"] + 10
        rolled = rolled_forward(source, 1.2, {"free_cash_flow": 5000.0})
        text = published_text(build_payload(rolled))
        self.assertNotIn("击穿上季重新评估线", text)
        self.assertIn(f"只连续一季、要连续{cn_count(line['consecutive'])}季才触发", text)

    def test_a_fiscal_fourth_quarter_cannot_settle_a_concentration_line(self) -> None:
        once = rolled_forward(self.source, 1.2)
        twice = rolled_forward(once, 1.2)            # Q4 2026 is a fiscal Q4: no quarterly concentration
        with self.assertRaisesRegex(ValueError, "not_drawn"):
            build_payload(twice)
        # A roller moves the line to not_drawn with the reason, and the page builds.
        prior = twice["prior_kpi_settlement"]
        kept = [l for l in prior["quantified"] if l["reads"] != "top_customer_pct"]
        prior["not_drawn"].append({"row": 5, "metric": "单一最大直接客户占比", "reading": "财年第四季没有季度值",
                                   "why": "10-K 只印全年"})
        prior["quantified"] = kept
        twice["next_kpi"]["quantified"] = [l for l in twice["next_kpi"]["quantified"]
                                           if l["reads"] != "top_customer_pct"]
        twice["next_kpi"]["not_drawn"].append({"row": 5, "metric": "单一最大直接客户占比",
                                               "threshold_text": "—", "reading": "—", "why": "演练"})
        build_payload(twice)


class NvdaRollTest(unittest.TestCase):
    """A roll edits the series and nothing else."""

    STAMPED = ("guidance", "market_expectation", "followup_closure", "prior_kpi_settlement", "next_kpi",
               "dc_customer_mix", "restated_comparatives", "balance_sheet_exposure", "capital_return_usd_m",
               "quarter_story")

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "nvda.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)
        cls.text = published_text(cls.payload)

    def rebuilt(self, edit) -> dict:
        changed = copy.deepcopy(self.source)
        edit(changed)
        return build_payload(changed)

    def test_quarter_blocks_refuse_to_publish_under_another_quarter(self) -> None:
        for key in self.STAMPED:
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    self.rebuilt(lambda s, key=key: s[key].__setitem__("period", "Q1 1999"))
        with self.assertRaisesRegex(ValueError, "stamped"):
            self.rebuilt(lambda s: s["latest"].__setitem__("period", "Q1 1999"))
        with self.assertRaisesRegex(ValueError, "sources"):
            self.rebuilt(lambda s: s.__setitem__(
                "sources", [x for x in s["sources"] if "业绩新闻稿" not in x["label"]
                            or "Q1 FY2027" in x["label"]]))
        with self.assertRaisesRegex(ValueError, "disagree"):
            self.rebuilt(lambda s: s["guidance"]["next_quarter"].__setitem__("revenue_usd_bn", 100.0))

    def test_a_quarter_without_its_blocks_leaves_them_out(self) -> None:
        # Every stamped block but this quarter's section 8 may be absent; the
        # section-8 lines are what section three is, so their block stays (its
        # narrative, which names other blocks' figures, goes with them).
        def strip(s):
            for key in self.STAMPED:
                if key != "next_kpi":
                    del s[key]
            for key in ("chart_notes", "note"):
                s["next_kpi"].pop(key, None)
        payload = self.rebuilt(strip)
        text = published_text(payload)
        for gone in ("条待验证问题", "两套口径在营业利润上", "被改写成", "表外担保", "上季原文：",
                     "兑现与", "较市场预期", "二阶导连续第", "下修在指引里"):
            with self.subTest(gone=gone):
                self.assertIn(gone, self.text)
                self.assertNotIn(gone, text)
        self.assertEqual([s["id"] for s in payload["sections"]],
                         ["settled", "quarter_highlights", "next_quarter", "routine"])
        self.assertTrue(all(s["exhibits"] for s in payload["sections"]), "a section went empty")
        self.assertIsNone(re.search(r"\{[A-Za-z_:]+\}", text))
        # Without this quarter's section 8 there is no section three to draw.
        with self.assertRaisesRegex(ValueError, "section three would be empty"):
            self.rebuilt(lambda s: s.__delitem__("next_kpi"))

    def test_a_story_whose_premise_fails_stops_the_build(self) -> None:
        def guide_raised(s):
            s["guidance"]["next_quarter"]["non_gaap_gross_margin_pct"] = 76.0
            s["quarterly_guidance_history"]["non_gaap_gm_guide_pct"][-1] = 76.0
        with self.assertRaisesRegex(ValueError, "gm_guide_cut"):
            self.rebuilt(guide_raised)

        def typed_again(s):
            s["next_kpi"]["quantified"][0]["current"] = 59.6
        with self.assertRaisesRegex(ValueError, "computed from the series"):
            self.rebuilt(typed_again)

        def guarantee_moved(s):
            s["balance_sheet_exposure"]["guarantee_max_exposure_usd_bn"]["land_power_shell_ai_clouds_current"] = 5.0
        with self.assertRaisesRegex(ValueError, "flat"):
            self.rebuilt(guarantee_moved)

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        guide = self.source["quarterly_guidance_history"]
        q4_18 = guide["quarters"].index("Q4 2018")

        # Q4'18 is the one miss the revenue leg drove; lift its revenue into the
        # band and it stops being named as the exception.
        def demand_fixed(s):
            g = s["quarterly_guidance_history"]
            g["actual_revenue_usd_m"][q4_18] = g["guide_revenue_usd_bn"][q4_18] * 1000
        after = published_text(self.rebuilt(demand_fixed))
        self.assertIn("<b>例外是 Q4'18</b>", self.text)
        self.assertNotIn("<b>例外是 Q4'18</b>", after)

        # The opex line said 「超支」 on a quarter that spent less than guided.
        at = guide["quarters"].index(self.source["periods"][-1])
        spent, promised = guide["actual_non_gaap_opex_usd_m"][at] / 1000, guide["non_gaap_opex_guide_usd_bn"][at]
        self.assertLess(spent, promised)
        self.assertNotIn("超支", self.text)
        self.assertIn(f"比承诺少花 {abs(spent / promised - 1) * 100:.1f}%", self.text)

        def overspent(s):
            s["quarterly_guidance_history"]["actual_non_gaap_opex_usd_m"][at] = promised * 1000 + 100
        self.assertIn("超支", published_text(self.rebuilt(overspent)))

        # A break with no named charge withdraws 「都是计提」.
        def uncharged(s):
            c = s["gross_margin_charges"]
            k = c["quarters"].index("Q3 2018")
            for key in ("quarters", "charge_usd_m", "what"):
                del c[key][k]
        after = published_text(self.rebuilt(uncharged))
        for claim in ("仍然成立", "历史上都不是波动而是计提"):
            self.assertIn(claim, self.text)
            self.assertNotIn(claim, after)

        # 「逐季修复」 only when the margin rose every quarter since the charge.
        long = self.source["long_history"]
        start = long["quarters"].index("Q1 2025")

        def monotonic(s):
            gm = s["long_history"]["gaap_gross_margin_pct"]
            for i in range(start + 1, len(gm)):
                gm[i] = max(gm[i], gm[i - 1] + 0.01)
                s["long_history"]["opex_intensity_pct"][i] = gm[i] - s["long_history"]["gaap_operating_margin_pct"][i]
        self.assertNotIn("季毛利率逐季修复", self.text)
        self.assertIn("季毛利率逐季修复", published_text(self.rebuilt(monotonic)))

        # The DSO jump is ranked against the whole receivables record the chart
        # draws, not the eight quarters: only the jumps the record holds that
        # are bigger get named, and with none left it is the largest.
        long = self.source["long_history"]
        dso = [ar / rev * 91 for ar, rev in zip(long["accounts_receivable_usd_m"], long["revenue_usd_m"])]
        jumps = [dso[i] - dso[i - 1] for i in range(1, len(dso))]
        bigger = [compact_period(long["quarters"][i + 1]) for i, j in enumerate(jumps[:-1]) if j > jumps[-1]]
        dso_chart = next(ex for ex in self.payload["sections"][2]["exhibits"] if ex["title"].startswith("DSO："))
        if 0 < len(bigger) <= 2:
            for label in bigger:
                self.assertIn(f"{label} 的 +", dso_chart["note"])
        if bigger:
            def flattened(s):
                ar = s["long_history"]["accounts_receivable_usd_m"]
                rev = s["long_history"]["revenue_usd_m"]
                for i in range(1, len(ar) - 1):
                    ar[i] = ar[i - 1] / rev[i - 1] * rev[i]      # DSO flat until this quarter
            after = published_text(self.rebuilt(flattened))
            self.assertNotIn("最大的单季跳升", self.text)
            self.assertIn("是这些季里最大的单季跳升", after)

        # The restated block is read by quarter label, not by position: the same
        # three quarters listed oldest-first must print the same page.
        def reordered(s):
            block = s["restated_comparatives"]
            for key, value in block.items():
                if isinstance(value, list):
                    block[key] = value[::-1]
        self.assertEqual(published_text(self.rebuilt(reordered)), self.text)

        # Next quarter's guide is slower on both readings; a faster guide says so.
        def faster(s):
            s["guidance"]["next_quarter"]["revenue_usd_bn"] = 125.0
            s["quarterly_guidance_history"]["guide_revenue_usd_bn"][-1] = 125.0
        self.assertIn("环比与同比都比本季慢", self.text)
        after = published_text(self.rebuilt(faster))
        self.assertNotIn("环比与同比都比本季慢", after)
        self.assertIn("不减速", after)

    def test_the_counts_on_the_page_are_recounted_here(self) -> None:
        guide = self.source["quarterly_guidance_history"]
        done = [i for i, v in enumerate(guide["actual_revenue_usd_m"]) if v is not None]
        growth = guide["actual_revenue_usd_m"][done[-1]] / guide["actual_revenue_usd_m"][done[0]]
        tens = int(growth) // 10 * 10
        self.assertGreaterEqual(growth, 20)
        self.assertIn(f"{cn_count(tens)}多倍的量级差", self.text)
        self.assertIn(f"收入量级{cn_count(tens)}多倍变化", self.text)
        breaks = [i for i in done
                  if guide["actual_non_gaap_gm_pct"][i] - guide["non_gaap_gm_guide_pct"][i] < -guide["gm_band_bp"][i] / 100]
        deep = [i for i in breaks if guide["actual_non_gaap_gm_pct"][i] - guide["non_gaap_gm_guide_pct"][i] < -5]
        self.assertIn(f"的{cn_count(len(breaks))}次跌破放到同一根轴上", self.text)
        self.assertIn(f"{cn_count(len(deep))}根深坑", self.text)
        # Every break the page counts has a charge the company named.
        self.assertEqual({guide["quarters"][i] for i in breaks} - set(self.source["gross_margin_charges"]["quarters"]), set())
        # The opex step at the definition change, read from the record.
        k = guide["quarters"].index("Q1 2026")
        self.assertIn(f"US${guide['actual_non_gaap_opex_usd_m'][k - 1] / 1000:.2f}B → "
                      f"Q1'26 US${guide['actual_non_gaap_opex_usd_m'][k] / 1000:.2f}B", self.text)
        # Operating-margin falls of ten points or more, and how long each took back.
        om = self.source["long_history"]["gaap_operating_margin_pct"]
        labels = [compact_period(q) for q in self.source["long_history"]["quarters"]]
        drops = [i for i in range(1, len(om)) if om[i] - om[i - 1] <= -10]
        self.assertIn(f"单季掉 10pp 以上的有{cn_count(len(drops))}个季度（{'、'.join(labels[i] for i in drops)}）",
                      self.text)
        # Commitments against the capital line: a ratio, not 「几十倍」.
        cash = self.source["cash_flow_usd_m"]
        capex = cash["operating_cash_flow"][-1] - cash["free_cash_flow"][-1]
        ratio = self.source["total_supply_usd_bn"]["supply_related_commitments"][-1] * 1000 / capex
        self.assertIn(f"是它的{cn_count(int(ratio) // 10 * 10)}多倍", self.text)
        # The Arm charge sits in Q1'22, not at the opex-intensity peak.
        intensity = self.source["long_history"]["opex_intensity_pct"]
        peak = labels[intensity.index(max(intensity))]
        self.assertNotEqual(peak, "Q1'22")
        self.assertNotIn(f"（{peak}，含 Arm", self.text)
        self.assertIn("Arm 交易终止的 US$1.35B 一次性费用在 Q1'22", self.text)

    def test_no_markdown_reaches_the_page(self) -> None:
        """Exhibit notes and source lines are innerHTML: `**` prints as asterisks."""
        for section in self.payload["sections"]:
            for ex in section["exhibits"]:
                with self.subTest(exhibit=ex["n"]):
                    self.assertNotIn("**", ex.get("note", "") + ex.get("src_extra", ""))

    def test_a_verb_that_carries_the_direction_prints_the_size(self) -> None:
        self.assertIsNone(re.search(r"(上修|下修|上调|下调|跳升|抬到|降到|升到|掉到) ?(US\$)?[+−-]\d", self.text))
        self.assertIsNone(re.search(r"-0\.0+(?!\d)", self.text), "a negative zero reached the page")


if __name__ == "__main__":
    unittest.main()
