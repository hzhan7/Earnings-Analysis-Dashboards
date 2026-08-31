"""Reconciliation and shape tests for the SNPS page.

Same purpose as the other companies': nothing derived reaches the page until it
has been checked against a statement identity or a figure the company disclosed
separately.  Synopsys adds two identities the other pages do not have.

The first is that its guidance is *self-reconciling*.  Every earnings 8-K guides
revenue, non-GAAP expenses, non-GAAP other income, the non-GAAP tax rate and the
diluted share count, and then guides the non-GAAP EPS those five imply -- so
running the five midpoints through the arithmetic has to reproduce the sixth.
It does, to within the rounding of the published endpoints, which is what
licenses the page to treat "guided revenue minus guided expenses" as the
company's own operating-income number.

The second is a hazard rather than a help: Software Integrity moved to
discontinued operations in the quarter ended 2024-04-30, so that one quarter was
guided on one basis and reported on another.  The test pins the add-back that
shows the apparent miss is the basis change and not a miss, because a page that
quietly dropped that quarter would be hiding its most interesting data point.
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
from build.snps import build_payload, compact_period  # noqa: E402


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


class SnpsDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "snps.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]
        cls.by_section = {
            section["id"]: section["exhibits"] for section in cls.payload["sections"]
        }
        cls.record = cls.source["quarterly_guidance_history"]

    # ── shape ────────────────────────────────────────────────────────────────
    def test_the_quarterly_margin_guidance_is_not_the_full_year_one(self) -> None:
        """The two midpoints in the release are the fiscal year's, not Q4's.

        They used to sit in `guidance.q3_2026_next_quarter`, and the page's
        guidance table printed one of them as the next quarter's margin: "about
        41.5%", "-0.1pp versus this quarter". Both are wrong in a way nothing
        looked broken by, because the *values* are right -- they are simply the
        wrong period's. Midpoint arithmetic settles it without reading the HTML:
        the full year implies 41.48% and 10.40%, matching the stored figures to
        the digit, while the fourth quarter implies 42.66% and 11.45%.
        """
        guidance = self.source["guidance"]
        quarter = guidance["q3_2026_next_quarter"]
        year = guidance["fy2026"]
        self.assertNotIn("non_gaap_operating_margin_midpoint_pct", quarter)
        self.assertNotIn("gaap_operating_margin_midpoint_pct", quarter)

        def midpoint(values):
            return sum(values) / 2

        year_revenue = midpoint(year["revenue_usd_m"])
        self.assertAlmostEqual(
            (year_revenue - midpoint(year["non_gaap_expenses_usd_m"])) / year_revenue * 100,
            year["non_gaap_operating_margin_midpoint_pct"], places=1)
        self.assertAlmostEqual(
            (year_revenue - midpoint(year["gaap_expenses_usd_m"])) / year_revenue * 100,
            year["gaap_operating_margin_midpoint_pct"], places=1)

        quarter_revenue = midpoint(quarter["revenue_usd_m"])
        implied = ((quarter_revenue - midpoint(quarter["non_gaap_expenses_usd_m"]))
                   / quarter_revenue * 100)
        self.assertGreater(implied, year["non_gaap_operating_margin_midpoint_pct"] + 1.0,
                           "the quarter and the year are more than a point apart, "
                           "which is why filing one under the other was visible "
                           "on the page")
        table = next(t for t in self.payload["tables"] if "指引" in t["title"])
        row = next(r for r in table["rows"] if r[0] == "non-GAAP 营业利润率")
        self.assertIn(f"{implied:.2f}%", row[4])
        self.assertNotIn("41.5%", row[4])

    def test_the_ansys_split_is_recomputable_and_the_page_says_so(self) -> None:
        """The stated reason for excluding EDA-ex-Ansys was too broad.

        It read "the company has never broken out Ansys revenue in any filing,
        so a quarterly DA-minus-Ansys cannot be recomputed". The Q3 FY2026 10-Q's
        revenue disaggregation prints the product-group *percentages* -- EDA
        51.8, Design IP 19.1, Ansys 28.7, Other 0.4 -- and one decimal on a
        US$2.48B base pins each derived dollar figure to about +/- US$0.2M. What
        survives is the narrower claim: no dollar figure is printed, and the
        percentages exist for too few quarters to draw a line beside this page's
        forty-two.
        """
        note = self.source["ansys_split_note"]
        percentages = note["percentages_pct"]
        self.assertAlmostEqual(sum(percentages.values()), 100.0, places=6)
        revenue = note["revenue_usd_m"]
        self.assertAlmostEqual(revenue * percentages["Ansys"] / 100,
                               note["implied_ansys_usd_m"], places=1)
        self.assertAlmostEqual(
            revenue * (percentages["EDA"] + percentages["Other"]) / 100,
            note["implied_da_ex_ansys_usd_m"], places=1)
        excluded = self.source["next_kpi"]["excluded"]
        self.assertIn("那句话太宽了", excluded)
        self.assertNotIn("无法复算的拆分", excluded)

    def test_the_window_is_eight_quarters_and_complete(self) -> None:
        self.assertEqual(len(self.source["periods"]), 8)
        self.assertEqual(len(self.source["period_ends"]), 8)
        for group in ("financials", "segments_usd_m"):
            for name, values in self.source[group].items():
                self.assertEqual(len(values), 8, f"{group}.{name}")
                self.assertTrue(
                    all(value is not None and math.isfinite(value) for value in values),
                    f"{group}.{name}",
                )

    def test_the_guided_record_is_one_row_per_quarter(self) -> None:
        length = len(self.record["quarters"])
        self.assertEqual(length, 43)
        for name, values in self.record.items():
            if not isinstance(values, list):
                continue
            self.assertEqual(len(values), length, name)
        # The record ends on a quarter that has been guided but not reported.
        self.assertIsNone(self.record["actual_revenue_usd_m"][-1])
        self.assertTrue(all(value is not None
                            for value in self.record["actual_revenue_usd_m"][:-1]))
        self.assertEqual(self.record["quarters"][-1], "Q3 2026")
        self.assertEqual(self.record["fiscal_labels"][-1], "FY2026Q4")

    def test_quarters_are_contiguous_calendar_labels(self) -> None:
        for quarters in (self.record["quarters"], self.source["periods"],
                         self.source["backlog"]["quarters"],
                         self.source["disaggregation_usd_m"]["quarters"]):
            numbers = []
            for label in quarters:
                quarter, year = label.split()
                numbers.append(int(year) * 4 + int(quarter[1]) - 1)
            self.assertEqual(numbers, list(range(numbers[0], numbers[0] + len(numbers))),
                             quarters[:3])

    def test_the_window_is_the_tail_of_the_guided_record(self) -> None:
        self.assertEqual(self.record["quarters"][-9:-1], self.source["periods"])

    def test_fiscal_labels_map_to_the_calendar_labels_the_page_publishes(self) -> None:
        """FY Q1 → prior-year Q4, Q2 → Q1, Q3 → Q2, Q4 → Q3.

        Getting this backwards would silently shift every SNPS row of the
        cross-company capex table by one quarter, which is exactly the failure
        the shared convention exists to prevent.
        """
        shift = {"1": (-1, "Q4"), "2": (0, "Q1"), "3": (0, "Q2"), "4": (0, "Q3")}
        for fiscal, calendar in zip(self.record["fiscal_labels"], self.record["quarters"]):
            year, number = int(fiscal[2:6]), fiscal[-1]
            offset, quarter = shift[number]
            self.assertEqual(calendar, f"{quarter} {year + offset}", fiscal)
        self.assertEqual(self.source["fiscal_labels"][-1], "FY2026Q3")
        self.assertEqual(self.source["periods"][-1], "Q2 2026")
        self.assertEqual(self.source["period_ends"][-1], "2026-07-31")

    # ── identities the filings have to satisfy ───────────────────────────────
    def test_segment_revenue_sums_to_total_revenue(self) -> None:
        segments = self.source["segments_usd_m"]
        for index, period in enumerate(self.source["periods"]):
            self.assertAlmostEqual(
                segments["design_automation_revenue"][index]
                + segments["design_ip_revenue"][index],
                self.source["financials"]["revenue_usd_m"][index],
                places=3,
                msg=period,
            )

    def test_geography_and_revenue_type_each_sum_to_total_revenue(self) -> None:
        disagg = self.source["disaggregation_usd_m"]
        for index, period in enumerate(disagg["quarters"]):
            total = disagg["revenue_usd_m"][index]
            self.assertAlmostEqual(
                sum(disagg[key][index]
                    for key in ("united_states", "europe", "korea", "china", "other")),
                total, places=3, msg=f"geography {period}")
            self.assertAlmostEqual(
                sum(disagg[key][index]
                    for key in ("time_based", "upfront", "maintenance_and_service")),
                total, places=3, msg=f"revenue type {period}")

    def test_the_overlapping_quarters_agree_across_the_two_windows(self) -> None:
        """The disaggregation series and the eight-quarter window are separate reads."""
        disagg = self.source["disaggregation_usd_m"]
        for index, period in enumerate(self.source["periods"]):
            position = disagg["quarters"].index(period)
            self.assertAlmostEqual(
                disagg["revenue_usd_m"][position],
                self.source["financials"]["revenue_usd_m"][index],
                places=3, msg=period)

    def test_operating_margins_are_the_ratio_they_claim_to_be(self) -> None:
        financials = self.source["financials"]
        for index, period in enumerate(self.source["periods"]):
            revenue = financials["revenue_usd_m"][index]
            self.assertAlmostEqual(
                financials["gaap_operating_margin_pct"][index],
                financials["gaap_operating_income_usd_m"][index] / revenue * 100,
                places=4, msg=period)
            self.assertAlmostEqual(
                financials["non_gaap_operating_margin_pct"][index],
                financials["non_gaap_operating_income_usd_m"][index] / revenue * 100,
                places=4, msg=period)

    def test_non_gaap_operating_income_exceeds_gaap_every_quarter(self) -> None:
        financials = self.source["financials"]
        for index, period in enumerate(self.source["periods"]):
            self.assertGreater(
                financials["non_gaap_operating_income_usd_m"][index],
                financials["gaap_operating_income_usd_m"][index], period)

    def test_year_over_year_uses_the_restated_continuing_operations_base(self) -> None:
        """The first four YoY readings need a base outside the window.

        Using the as-originally-reported base instead would overstate the
        year-ago quarter by the Software Integrity revenue and understate every
        one of those four growth rates.
        """
        financials = self.source["financials"]
        base = {"Q3 2024": 1467.383, "Q4 2024": 1510.989,
                "Q1 2025": 1454.712, "Q2 2025": 1525.749}
        for index, period in enumerate(self.source["periods"]):
            revenue = financials["revenue_usd_m"][index]
            prior = base.get(period) or financials["revenue_usd_m"][index - 4]
            self.assertAlmostEqual(financials["revenue_yoy_pct"][index],
                                   (revenue / prior - 1) * 100, places=3, msg=period)

    # ── the guidance table reconciles to itself ──────────────────────────────
    def test_the_guided_eps_midpoint_is_implied_by_the_other_five_guided_lines(self) -> None:
        """(revenue − expenses + other) × (1 − tax) ÷ shares reproduces guided EPS.

        This is what lets the page treat "guided revenue minus guided expenses"
        as an operating income the company itself stands behind.

        It reproduces it *approximately*, and how approximately turns out to
        depend on the era — which is only visible now that the record reaches
        2016. On the 24 quarters this file used to cover, the reconstruction was
        within 2.2% of the printed EPS midpoint every time. Across the 19
        backfilled quarters it is within 8.4%, and the median is four times
        looser (2.1% against 0.5%). Q3 2018 is the extreme: every input matches
        the 2018-08-22 release verbatim -- revenue $774-804M, non-GAAP expenses
        $655-665M, other income $(3)-(1)M, tax 13%, shares 153-156M, non-GAAP
        EPS $0.76-0.80 -- and the midpoints still only reconstruct $0.715
        against a printed $0.78. The company does not compute its EPS midpoint
        from its own range midpoints, and the gap shows up most where the EPS
        base is smallest.

        So this is asserted per era rather than with one tolerance wide enough
        to cover both, which would have stopped saying anything about the recent
        quarters. Widening a bound until it passes is how a gate quietly retires.
        """
        record = self.record
        gaps, relative = [], []
        for index in range(len(record["quarters"])):
            revenue = (record["guide_revenue_lo_usd_m"][index]
                       + record["guide_revenue_hi_usd_m"][index]) / 2
            expenses = (record["guide_non_gaap_expenses_lo_usd_m"][index]
                        + record["guide_non_gaap_expenses_hi_usd_m"][index]) / 2
            other = (record["guide_non_gaap_other_income_lo_usd_m"][index]
                     + record["guide_non_gaap_other_income_hi_usd_m"][index]) / 2
            shares = (record["guide_shares_lo_m"][index]
                      + record["guide_shares_hi_m"][index]) / 2
            tax = record["guide_non_gaap_tax_rate_pct"][index] / 100
            printed = (record["guide_non_gaap_eps_lo_usd"][index]
                       + record["guide_non_gaap_eps_hi_usd"][index]) / 2
            gap = abs((revenue - expenses + other) * (1 - tax) / shares - printed)
            gaps.append(gap)
            relative.append(gap / printed * 100)

        # The era boundary is where this file's record used to begin.
        split = record["quarters"].index("Q4 2020")
        self.assertEqual(split, 19)
        early, recent = relative[:split], relative[split:]

        # Recent quarters keep the tight bound the original assertion had.
        self.assertLessEqual(max(recent), 2.5, "the modern reconstruction slipped")
        self.assertLessEqual(max(early), 9.0, "the early reconstruction slipped")
        self.assertLessEqual(max(gaps), 0.07)
        self.assertGreaterEqual(sum(1 for gap in gaps if gap <= 0.02), 26)

        # The difference between the eras is itself the finding, so it is
        # asserted -- but counted, not maximised. A max-based version of this
        # passed even after the single worst early quarter was smoothed flat
        # (mutation-checked: it survived by 0.11pp, which is not an assertion,
        # it is a coincidence). Counting how many quarters clear the threshold
        # makes any one of them being quietly fixed turn this red.
        loose = 2.0
        self.assertEqual(sum(1 for value in early if value > loose), 10)
        self.assertEqual(sum(1 for value in recent if value > loose), 2)
        self.assertGreater(_median(early), _median(recent) * 2)

    def test_the_two_legs_add_up_to_the_operating_income_beat(self) -> None:
        """Revenue leg + expense leg = actual non-GAAP OI − guided-implied OI, exactly."""
        record = self.record
        for index, quarter in enumerate(record["quarters"]):
            actual_revenue = record["actual_revenue_usd_m"][index]
            if actual_revenue is None:
                continue
            actual_income = record["actual_non_gaap_operating_income_usd_m"][index]
            # Reported and decomposable are different questions: Synopsys's
            # reconciliation carried no operating-income line before the release
            # of 2019-02-20, so eleven reported quarters have no leg split.
            if actual_income is None:
                continue
            guided_revenue = (record["guide_revenue_lo_usd_m"][index]
                              + record["guide_revenue_hi_usd_m"][index]) / 2
            guided_expense = (record["guide_non_gaap_expenses_lo_usd_m"][index]
                              + record["guide_non_gaap_expenses_hi_usd_m"][index]) / 2
            revenue_leg = actual_revenue - guided_revenue
            expense_leg = guided_expense - (actual_revenue - actual_income)
            self.assertAlmostEqual(revenue_leg + expense_leg,
                                   actual_income - (guided_revenue - guided_expense),
                                   places=6, msg=quarter)

    def test_the_guidance_tally_the_page_publishes_is_the_one_in_the_data(self) -> None:
        record = self.record
        def tally(low, high, actual):
            above = inside = below = 0
            for lo, hi, value in zip(low, high, actual):
                if value is None:
                    continue
                if value > hi:
                    above += 1
                elif value < lo:
                    below += 1
                else:
                    inside += 1
            return above, inside, below

        self.assertEqual(tally(record["guide_revenue_lo_usd_m"],
                               record["guide_revenue_hi_usd_m"],
                               record["actual_revenue_usd_m"]), (17, 23, 2))
        self.assertEqual(tally(record["guide_non_gaap_eps_lo_usd"],
                               record["guide_non_gaap_eps_hi_usd"],
                               record["actual_non_gaap_eps_usd"]), (32, 8, 2))
        titles = {exhibit["title"] for exhibit in self.by_section["settled"]}
        self.assertTrue(any("23 季落在区间内" in title for title in titles), titles)
        self.assertTrue(any("32 季超出上限、8 季落在区间内" in title for title in titles), titles)

    def test_the_one_basis_break_is_marked_and_explained(self) -> None:
        """Q1 2024 was guided with Software Integrity in and reported with it out."""
        record = self.record
        index = record["basis_break_at"]
        self.assertEqual(record["fiscal_labels"][index], "FY2024Q2")
        self.assertEqual(record["quarters"][index], "Q1 2024")
        actual = record["actual_revenue_usd_m"][index]
        low = record["guide_revenue_lo_usd_m"][index]
        high = record["guide_revenue_hi_usd_m"][index]
        self.assertLess(actual, low)
        # The 10-Q's discontinued-operations note put Software Integrity's
        # three months at 126.421 -- the segment table cannot supply it, because
        # that table had already removed the business from every period. Adding
        # it back lands inside the range the company had guided, which is what
        # licenses the page to call the apparent miss a basis change.
        addback = record["basis_break_addback_usd_m"]
        self.assertAlmostEqual(addback, 126.421, places=3)
        self.assertTrue(low <= actual + addback <= high,
                        f"{actual} + {addback} should be inside {low}-{high}")
        marked = [exhibit for exhibit in self.by_section["settled"]
                  if exhibit.get("break_at") is not None]
        self.assertEqual({exhibit["break_at"] for exhibit in marked}, {index})
        self.assertGreaterEqual(len(marked), 2)

    def test_the_only_other_revenue_miss_is_the_ansys_close_quarter(self) -> None:
        record = self.record
        misses = [record["quarters"][index]
                  for index, value in enumerate(record["actual_revenue_usd_m"])
                  if value is not None and value < record["guide_revenue_lo_usd_m"][index]]
        self.assertEqual(misses, ["Q1 2024", "Q2 2025"])
        # That quarter is also the only one whose share count came in above the
        # guided range, because the merger issued stock inside the quarter.
        above = [record["quarters"][index]
                 for index, value in enumerate(record["actual_diluted_shares_m"])
                 if value is not None and value > record["guide_shares_hi_m"][index]]
        self.assertEqual(above, ["Q2 2025"])

    # ── derived series the page publishes ────────────────────────────────────
    def test_twelve_month_backlog_uses_the_filing_s_own_ex_fsa_base(self) -> None:
        """The filed percentage applies to backlog *excluding* the FSA commitments."""
        backlog = self.source["backlog"]
        latest = ((backlog["backlog_usd_b"][-1] - backlog["fsa_usd_b"][-1])
                  * backlog["next_12m_pct_of_ex_fsa"][-1] / 100)
        self.assertAlmostEqual(latest, 4.41, places=2)
        entry = next(item for item in self.source["next_kpi"]["quantified"]
                     if item["metric"] == "未来 12 个月可确认 backlog")
        self.assertAlmostEqual(entry["current"], latest, places=3)
        for index, quarter in enumerate(backlog["quarters"]):
            self.assertLess(backlog["fsa_usd_b"][index], backlog["backlog_usd_b"][index], quarter)

    def test_long_history_amortization_is_the_sum_of_the_two_income_statement_lines(self) -> None:
        long = self.source["long_history"]
        self.assertEqual(len(long["fiscal_years"]), 10)
        self.assertEqual(long["fiscal_years"][0], "FY2016")
        self.assertEqual(long["fiscal_years"][-1], "FY2025")
        # FY2016 read straight off that year's 10-K: 102.118 in cost of revenue
        # and 27.507 in operating expenses, against revenue of 2,422.532.
        self.assertAlmostEqual(long["amortization_cost_of_revenue_usd_m"][0], 102.118, places=3)
        self.assertAlmostEqual(long["amortization_opex_usd_m"][0], 27.507, places=3)
        self.assertAlmostEqual(long["revenue_usd_m"][0], 2422.532, places=3)
        # The restated column exists only for the years a later 10-K recast.
        recast = {year for year, value
                  in zip(long["fiscal_years"], long["restated_revenue_usd_m"])
                  if value is not None}
        self.assertEqual(recast, {"FY2017", "FY2018", "FY2022", "FY2023", "FY2024"})
        self.assertAlmostEqual(long["restated_revenue_usd_m"][6], 4615.714, places=3)
        self.assertAlmostEqual(long["restated_revenue_usd_m"][7], 5318.014, places=3)

    def test_the_buyback_series_has_the_two_zero_years_the_page_claims(self) -> None:
        long = self.source["long_history"]
        zero = [year for year, value
                in zip(long["fiscal_years"], long["share_repurchases_usd_m"]) if value == 0]
        self.assertEqual(zero, ["FY2024", "FY2025"])
        self.assertTrue(all(value > 0 for value in long["share_repurchases_usd_m"][:8]))

    def test_the_fy2026_guidance_raise_splits_the_way_the_page_says(self) -> None:
        footnote = self.source["guidance"]["fy2026_revenue_footnote"]
        mid = [(lo + hi) / 2 for lo, hi
               in zip(footnote["revenue_lo_usd_m"], footnote["revenue_hi_usd_m"])]
        ansys = footnote["expected_ansys_revenue_usd_m"]
        core = [total - value for total, value in zip(mid, ansys)]
        self.assertAlmostEqual(mid[-1] - mid[0], 105.0, places=6)
        self.assertAlmostEqual(ansys[-1] - ansys[0], 80.0, places=6)
        self.assertAlmostEqual(core[-1] - core[0], 25.0, places=6)
        self.assertEqual(len(footnote["releases"]), 4)

    # ── thresholds ───────────────────────────────────────────────────────────
    def test_every_quantified_threshold_has_a_chart_and_a_headroom_bar(self) -> None:
        entries = self.source["next_kpi"]["quantified"]
        self.assertEqual(len(entries), 5)
        section = self.by_section["next_quarter"]
        self.assertEqual(len(section), 1 + len(entries))
        bar = section[0]
        self.assertEqual(bar["kind"], "diverging_bars")
        self.assertEqual(bar["xlabels"], [entry["metric"] for entry in entries])
        for entry, chart in zip(entries, section[1:]):
            self.assertIn(entry["metric"], chart["title"])
            threshold_series = chart["series"][1]["values"]
            self.assertEqual(set(threshold_series), {entry["threshold"]})

    def test_the_headroom_values_are_the_signed_distance_from_each_threshold(self) -> None:
        bar = self.by_section["next_quarter"][0]
        for entry, value in zip(self.source["next_kpi"]["quantified"], bar["values"]):
            self.assertAlmostEqual(
                value,
                round(headroom(entry["direction"], entry["threshold"], entry["current"]), 1),
                places=6, msg=entry["metric"])

    def test_the_share_count_threshold_is_the_company_s_own_guided_ceiling(self) -> None:
        entry = next(item for item in self.source["next_kpi"]["quantified"]
                     if item["metric"] == "摊薄股数")
        self.assertEqual(entry["threshold"],
                         self.source["guidance"]["q3_2026_next_quarter"]["diluted_shares_m"][1])
        self.assertEqual(entry["direction"], "down")

    def test_what_the_page_refuses_to_plot_is_named(self) -> None:
        excluded = self.source["next_kpi"]["excluded"]
        for term in ("Ansys", "Investor Day", "同业"):
            self.assertIn(term, excluded)
        self.assertIn("Ansys", " ".join(self.payload["notes"]))

    # ── payload hygiene ──────────────────────────────────────────────────────
    def test_exhibits_are_numbered_in_render_order_and_refs_resolve(self) -> None:
        numbers = [exhibit["n"] for exhibit in self.exhibits]
        self.assertEqual(numbers, list(range(2, 2 + len(self.exhibits))))
        for exhibit in self.exhibits:
            self.assertNotIn("ref", exhibit)
            for field in ("title", "note", "src_extra", "annot"):
                text = exhibit.get(field)
                if isinstance(text, str):
                    self.assertNotRegex(text, r"\{EX_[A-Z_]+\}", f"{exhibit['n']} {field}")

    def test_tables_are_numbered_after_the_exhibits(self) -> None:
        first = len(self.exhibits) + 2
        self.assertEqual([table["n"] for table in self.payload["tables"]],
                         list(range(first, first + len(self.payload["tables"]))))
        for table in self.payload["tables"]:
            for row in table["rows"]:
                self.assertEqual(len(row), len(table["headers"]), table["title"])

    def test_every_exhibit_carries_a_note_and_a_source_line(self) -> None:
        for exhibit in self.exhibits:
            self.assertTrue(exhibit.get("note"), exhibit["title"])
            self.assertTrue(exhibit.get("src_extra"), exhibit["title"])

    def test_the_published_payload_matches_a_fresh_build(self) -> None:
        """`python3 build/all.py && git status` stays the drift check."""
        published = js_payload(ROOT / "data" / "snps.js", "window.DASH")
        self.assertEqual(published, self.payload)

    def test_the_page_declares_the_fiscal_year_convention_in_its_subtitle(self) -> None:
        self.assertIn("FY2026 Q3", self.payload["subtitle"])
        self.assertIn("Q2 2026", self.payload["title"])
        self.assertEqual(self.payload["latest"]["period_end"], "2026-07-31")
        self.assertEqual(self.payload["latest"]["release_date"], "2026-08-26")

    def test_market_expectation_is_labelled_and_dated_but_unattributed(self) -> None:
        expectation = self.source["market_expectation"]
        self.assertIn("2026-08-26", expectation["as_of"])
        self.assertIn("不具名", expectation["basis"])
        joined = json.dumps(self.payload, ensure_ascii=False)
        self.assertIn("市场预期", joined)
        # No broker or vendor may be named anywhere in the payload. The words
        # 评级 / 目标价 themselves are not banned: they appear in the page's own
        # boundary statement saying it publishes neither.
        for named in ("Baird", "Wolfe", "Needham", "Morgan Stanley", "Citi",
                      "Mizuho", "Zacks", "Benzinga"):
            self.assertNotIn(named, joined)
        for exhibit in self.exhibits:
            self.assertNotIn("目标价", exhibit.get("note", ""))
            self.assertNotIn("评级", exhibit.get("note", ""))

    def test_the_roster_carries_snps_with_the_payload_s_own_labels(self) -> None:
        payloads = build_all()
        self.assertIn("snps", payloads)
        roster = roster_payload(payloads)
        entry = next(item for item in roster["items"] if item["slug"] == "snps")
        self.assertEqual(entry["latest_label"], self.payload["latest"]["disclosed_period_label"])
        self.assertEqual(entry["release_date"], self.payload["latest"]["release_date"])
        self.assertEqual(entry["group"], "semiconductor_ai")

    def test_the_shell_links_the_payload_by_content_hash(self) -> None:
        """Every `?v=` in the committed shell must be that file's CURRENT digest.

        Checking only the shape of the query string is not enough, and this test
        used to do exactly that. On 2026-08-29 a commit updated `data/snps.js`
        but left `snps/index.html` out of its explicit path list, so the shell
        went on stamping the previous payload's digest. Nothing caught it: the
        renderer is correct (main() writes the payload before rendering the
        shell), the working tree was consistent, and all 201 tests passed --
        because they run after `build/all.py` has already regenerated the shell.
        Only `git status` after a build showed it, and only if you looked.

        The consequence is precisely what the fingerprint exists to prevent: the
        payload bytes changed, its URL did not, so a reader who had already
        loaded the old `data/snps.js?v=...` kept being served it from cache.
        """
        import hashlib

        shell = (ROOT / "snps" / "index.html").read_text(encoding="utf-8")
        self.assertIn("<title>SNPS Quarterly Results</title>", shell)
        sources = re.findall(r'<script src="\.\./([^"?]+)(?:\?v=([0-9a-f]+))?"', shell)
        self.assertEqual(
            [name for name, _ in sources],
            ["data/roster.js", "data/snps.js", "assets/charts.js", "assets/page.js"],
        )
        for name, digest in sources:
            with self.subTest(script=name):
                self.assertTrue(digest, f"{name} is served without a cache-busting version")
                expected = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()[: len(digest)]
                self.assertEqual(digest, expected, f"{name} carries a stale digest")

    def test_compact_period_round_trips_the_labels_the_charts_use(self) -> None:
        self.assertEqual(compact_period("Q2 2026"), "Q2'26")
        self.assertEqual(compact_period("Q4 2020"), "Q4'20")
        for exhibit in self.by_section["settled"]:
            if exhibit["kind"] == "range_band":
                self.assertTrue(all(re.fullmatch(r"Q[1-4]'\d{2}", label)
                                    for label in exhibit["xlabels"]), exhibit["title"])


if __name__ == "__main__":
    unittest.main()
