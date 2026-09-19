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
from build.board import cn_count, headroom  # noqa: E402
from build.snps import build_payload, compact_period  # noqa: E402

# Record tallies are pinned exactly through the last quarter guided when this
# page was migrated; later quarters extend the record and are checked as
# invariants against what the page prints.
PINNED_THROUGH = "Q3 2026"


def published_text(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def quarter_order(label: str) -> int:
    quarter, year = label.split()
    return int(year) * 4 + int(quarter[1])


def pinned(record: dict) -> list[int]:
    return [i for i, q in enumerate(record["quarters"]) if quarter_order(q) <= quarter_order(PINNED_THROUGH)]


def current_value(source: dict, entry_id: str) -> float:
    """A threshold's current value, recomputed here rather than read from the builder."""
    fin, seg, backlog = source["financials"], source["segments_usd_m"], source["backlog"]
    if entry_id == "ng_margin":
        return fin["non_gaap_operating_income_usd_m"][-1] / fin["revenue_usd_m"][-1] * 100
    if entry_id == "ip_yoy":
        return (seg["design_ip_revenue"][-1] / seg["design_ip_revenue"][-5] - 1) * 100
    if entry_id == "backlog_12m":
        return ((backlog["backlog_usd_b"][-1] - backlog["fsa_usd_b"][-1])
                * backlog["next_12m_pct_of_ex_fsa"][-1] / 100)
    if entry_id == "fsa_share":
        return backlog["fsa_usd_b"][-1] / backlog["backlog_usd_b"][-1] * 100
    if entry_id == "shares":
        return fin["diluted_shares_m"][-1]
    raise KeyError(entry_id)


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
        quarter = guidance["next_quarter"]
        year = guidance["full_year"]["current"]
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
        51.8, Design IP 19.1, Ansys 28.7, Other 0.4 -- and one decimal (+/- 0.05pp)
        on a US$2.48B base pins each derived dollar figure to about +/- US$1.2M; the
        page used to say +/- US$0.2M, six times too tight. What
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
        excluded = "".join(self.source["next_kpi"]["excluded"])
        self.assertIn("那句话太宽了", excluded)
        self.assertNotIn("无法复算的拆分", excluded)
        self.assertNotIn("**", excluded, "the excluded note lands in innerHTML: markdown prints as asterisks")
        text = published_text(self.payload)
        self.assertIn(f"Ansys ≈ ${revenue * percentages['Ansys'] / 100:,.1f}M", text)
        self.assertIn(f"±${revenue * 0.0005:,.1f}M", text)

    def test_the_window_is_eight_quarters_and_complete(self) -> None:
        length = len(self.source["periods"])
        self.assertGreaterEqual(length, 8)
        self.assertEqual(len(self.source["period_ends"]), length)
        self.assertEqual(len(self.source["fiscal_labels"]), length)
        for group in ("financials", "segments_usd_m"):
            for name, values in self.source[group].items():
                if not isinstance(values, list):
                    continue
                self.assertEqual(len(values), length, f"{group}.{name}")
                self.assertTrue(
                    all(value is not None and math.isfinite(value) for value in values),
                    f"{group}.{name}",
                )

    def test_the_guided_record_is_one_row_per_quarter(self) -> None:
        length = len(self.record["quarters"])
        self.assertGreaterEqual(length, 43)
        for name, values in self.record.items():
            if not isinstance(values, list):
                continue
            self.assertEqual(len(values), length, name)
        # The record ends on a quarter that has been guided but not reported.
        self.assertIsNone(self.record["actual_revenue_usd_m"][-1])
        self.assertTrue(all(value is not None
                            for value in self.record["actual_revenue_usd_m"][:-1]))
        # ... and that quarter is the one after the page's.
        last = self.source["periods"][-1]
        following = quarter_order(last) + 1
        self.assertEqual(quarter_order(self.record["quarters"][-1]), following)
        self.assertEqual(self.record["quarters"][-1], self.source["guidance"]["next_quarter"]["period"])
        self.assertEqual(self.record["fiscal_labels"][-1],
                         self.source["guidance"]["next_quarter"]["fiscal_label"])

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
        checks = self.source["_checks"]
        self.assertEqual(self.source["fiscal_labels"][-1], checks["fiscal_label"].replace(" ", ""))
        self.assertEqual(self.source["periods"][-1], checks["period"])
        self.assertEqual(self.source["period_ends"][-1], checks["period_end"])

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
        # The two earliest quarters were recovered from a later filing's
        # comparative columns, which carry the geography split but not the
        # revenue-type one. So the two identities are checkable over different
        # spans, and both spans are asserted -- otherwise dropping a leg would
        # look like the identity still holding everywhere it is checked.
        geography = revenue_type = 0
        for index, period in enumerate(disagg["quarters"]):
            total = disagg["revenue_usd_m"][index]
            geo = [disagg[key][index]
                   for key in ("united_states", "europe", "korea", "china", "other")]
            if None not in geo:
                geography += 1
                self.assertAlmostEqual(sum(geo), total, places=3,
                                       msg=f"geography {period}")
            legs = [disagg[key][index]
                    for key in ("time_based", "upfront", "maintenance_and_service")]
            if None not in legs:
                revenue_type += 1
                self.assertAlmostEqual(sum(legs), total, places=3,
                                       msg=f"revenue type {period}")
        self.assertEqual(geography, len(disagg["quarters"]))
        self.assertEqual(revenue_type, len(disagg["quarters"]) - 2)

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
        for index in pinned(record):
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

        keep = pinned(record)
        def cut(key):
            return [record[key][i] for i in keep]
        self.assertEqual(tally(cut("guide_revenue_lo_usd_m"), cut("guide_revenue_hi_usd_m"),
                               cut("actual_revenue_usd_m")), (17, 23, 2))
        self.assertEqual(tally(cut("guide_non_gaap_eps_lo_usd"), cut("guide_non_gaap_eps_hi_usd"),
                               cut("actual_non_gaap_eps_usd")), (32, 8, 2))
        # What the page prints is the whole record, recounted.
        revenue = tally(record["guide_revenue_lo_usd_m"], record["guide_revenue_hi_usd_m"],
                        record["actual_revenue_usd_m"])
        eps = tally(record["guide_non_gaap_eps_lo_usd"], record["guide_non_gaap_eps_hi_usd"],
                    record["actual_non_gaap_eps_usd"])
        titles = {exhibit["title"] for exhibit in self.by_section["settled"]}
        self.assertTrue(any(f"{revenue[1]} 季落在区间内" in title for title in titles), titles)
        self.assertTrue(any(f"{eps[0]} 季超出上限、{eps[1]} 季落在区间内" in title for title in titles), titles)
        finished = sum(revenue)
        self.assertIn(f"{finished} 季指引记录里，收入落在自己区间内 {revenue[1]} 次，"
                      f"non-GAAP EPS 却 {eps[0]} 次穿出上限", self.payload["brief"])

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
                  if value is not None and value < record["guide_revenue_lo_usd_m"][index]
                  and index in pinned(record)]
        self.assertEqual(misses, ["Q1 2024", "Q2 2025"])
        # That quarter is also the only one whose share count came in above the
        # guided range, because the merger issued stock inside the quarter.
        above = [record["quarters"][index]
                 for index, value in enumerate(record["actual_diluted_shares_m"])
                 if value is not None and value > record["guide_shares_hi_m"][index]
                 and index in pinned(record)]
        self.assertEqual(above, ["Q2 2025"])

    # ── derived series the page publishes ────────────────────────────────────
    def test_twelve_month_backlog_uses_the_filing_s_own_ex_fsa_base(self) -> None:
        """The filed percentage applies to backlog *excluding* the FSA commitments."""
        backlog = self.source["backlog"]
        checks = self.source["_checks"]
        latest = ((checks["backlog_usd_bn"] - checks["fsa_usd_bn"])
                  * checks["next_12m_pct_of_ex_fsa"] / 100)
        self.assertAlmostEqual(current_value(self.source, "backlog_12m"), latest, places=6)
        entry = next(item for item in self.source["next_kpi"]["quantified"]
                     if item["id"] == "backlog_12m")
        self.assertNotIn("current", entry, "the current value is computed, not typed")
        table = next(t for t in self.payload["tables"] if t["title"].startswith("下季阈值"))
        row = next(r for r in table["rows"] if r[0] == entry["metric"])
        self.assertEqual(row[3], f"US${latest:.1f}B")
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
        footnote = self.source["guidance"]["full_year_revenue_footnote"]
        mid = [(lo + hi) / 2 for lo, hi
               in zip(footnote["revenue_lo_usd_m"], footnote["revenue_hi_usd_m"])]
        ansys = footnote["expected_ansys_revenue_usd_m"]
        core = [total - value for total, value in zip(mid, ansys)]
        if footnote["fiscal_year"] == "FY2026":
            self.assertAlmostEqual(mid[-1] - mid[0], 105.0, places=6)
            self.assertAlmostEqual(ansys[-1] - ansys[0], 80.0, places=6)
            self.assertAlmostEqual(core[-1] - core[0], 25.0, places=6)
        # The title counts raises, not vintages: four FY2026 releases carried
        # the guidance, and only two of them raised its midpoint (February
        # repeated December's range). The page used to say 「四次上调」.
        raises = sum(1 for a, b in zip(mid, mid[1:]) if b > a)
        chart = next(ex for ex in self.by_section["quarter_highlights"] if "收入指引" in ex["title"])
        self.assertIn(f"{footnote['fiscal_year']} 收入指引{cn_count(raises)}次上调共 US${mid[-1] - mid[0]:,.0f}M",
                      chart["title"])
        self.assertGreater(mid[-1], mid[0], "「上调」 carries the sign: the page prints the size")
        self.assertEqual(chart["xlabels"], footnote["releases"])

    # ── thresholds ───────────────────────────────────────────────────────────
    def test_every_quantified_threshold_has_a_chart_and_a_headroom_bar(self) -> None:
        entries = self.source["next_kpi"]["quantified"]
        self.assertTrue(entries)
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
                round(headroom(entry["direction"], entry["threshold"],
                               current_value(self.source, entry["id"])), 1),
                places=6, msg=entry["metric"])

    def test_the_share_count_threshold_is_the_company_s_own_guided_ceiling(self) -> None:
        entry = next(item for item in self.source["next_kpi"]["quantified"]
                     if item["id"] == "shares")
        self.assertEqual(entry["threshold"],
                         self.source["guidance"]["next_quarter"]["diluted_shares_m"][1])
        self.assertEqual(entry["direction"], "down")

    def test_what_the_page_refuses_to_plot_is_named(self) -> None:
        items = self.source["next_kpi"]["excluded"]
        for term, item in zip(("Ansys", "Investor Day", "同业"), items):
            self.assertIn(term, item)
        self.assertIn("Ansys", " ".join(self.payload["notes"]))
        # The count on the page is the length of the list, in both places it is said.
        text = published_text(self.payload)
        self.assertIn(f"另有{cn_count(len(items))}条本页<b>不接入</b>", text)
        self.assertIn(f"（{len(items)}）", text)
        self.assertNotIn(f"（{len(items) + 1}）", text)
        section = next(s for s in self.payload["sections"] if s["id"] == "next_quarter")
        self.assertIn(f"不接入的{cn_count(len(items))}条也写在这里", section["description"])
        # The guidance record's length inside the story is counted, not typed.
        finished = sum(1 for v in self.source["quarterly_guidance_history"]["actual_revenue_usd_m"]
                       if v is not None)
        self.assertIn(f"本页其余{cn_count(finished)}季并排", text)

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
        checks = self.source["_checks"]
        self.assertIn(f"本页 {checks['period']} 即公司所称 {checks['fiscal_label']}", self.payload["subtitle"])
        self.assertIn(checks["period"], self.payload["title"])
        self.assertEqual(self.payload["latest"]["period_end"], checks["period_end"])
        self.assertEqual(self.payload["latest"]["release_date"], checks["release_date"])

    def test_market_expectation_is_labelled_and_dated_but_unattributed(self) -> None:
        expectation = self.source["market_expectation"]
        self.assertIn(self.source["latest"]["release_date"], expectation["as_of"])
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


class SnpsChecksTest(unittest.TestCase):
    """The page's quarter against a record keyed separately from the filings.

    `_checks` is typed once per quarter from the earnings 8-K's EX-99.1 and the
    10-Q, with the place each figure was read; the builder never reads it
    (asserted in `test_data_only_roll`). Rolling a quarter re-keys `_checks`;
    this class does not change.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "snps.json").read_text(encoding="utf-8"))
        cls.checks = cls.source["_checks"]
        cls.payload = build_payload(cls.source)
        cls.text = published_text(cls.payload)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]

    def test_the_page_names_the_checked_quarter(self) -> None:
        c = self.checks
        self.assertIn(c["period"], self.payload["title"])
        self.assertIn(f"截至 {c['period_end']} · 发布 {c['release_date']}", self.payload["subtitle"])
        self.assertIn(f"本页 {c['period']} 即公司所称 {c['fiscal_label']}", self.payload["subtitle"])
        record = self.source["quarterly_guidance_history"]
        self.assertEqual(record["guided_in_release"][-1], c["release_date"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        c, fin, seg = self.checks, self.source["financials"], self.source["segments_usd_m"]
        self.assertEqual(round(fin["revenue_usd_m"][-1] * 1000), c["revenue_usd_k"])
        self.assertEqual(round(fin["revenue_usd_m"][-5] * 1000), c["revenue_year_ago_usd_k"])
        self.assertEqual(round(fin["gaap_operating_income_usd_m"][-1] * 1000), c["gaap_operating_income_usd_k"])
        adj = c["segment_adjusted_operating_income_usd_m"]
        self.assertEqual(round(seg["design_automation_adj_op_income"][-1], 1), adj["design_automation"])
        self.assertEqual(round(seg["design_ip_adj_op_income"][-1], 1), adj["design_ip"])
        self.assertAlmostEqual(fin["non_gaap_operating_income_usd_m"][-1],
                               adj["design_automation"] + adj["design_ip"], places=6)
        self.assertEqual(round(seg["design_ip_revenue"][-1] * 1000), c["design_ip_revenue_usd_k"])
        self.assertEqual(round(seg["design_ip_revenue"][-5] * 1000), c["design_ip_revenue_year_ago_usd_k"])
        self.assertEqual(fin["gaap_eps_usd"][-1], c["gaap_diluted_eps_usd"])
        self.assertEqual(fin["non_gaap_eps_usd"][-1], c["non_gaap_diluted_eps_usd"])
        self.assertEqual(round(fin["diluted_shares_m"][-1] * 1000), c["diluted_shares_k"])
        self.assertEqual(round(fin["non_gaap_net_income_usd_m"][-1], 1), c["non_gaap_net_income_usd_m"])
        backlog = self.source["backlog"]
        self.assertEqual(backlog["backlog_usd_b"][-1], c["backlog_usd_bn"])
        self.assertEqual(backlog["fsa_usd_b"][-1], c["fsa_usd_bn"])
        self.assertEqual(backlog["next_12m_pct_of_ex_fsa"][-1], c["next_12m_pct_of_ex_fsa"])
        self.assertEqual(self.source["ansys_split_note"]["percentages_pct"]["Ansys"], c["ansys_share_pct"])
        self.assertEqual(self.source["quarter_story"]["non_gaap_tax_rate_actual_pct"], c["non_gaap_tax_rate_pct"])

    def test_the_outlook_is_the_checked_outlook(self) -> None:
        guide, c = self.source["guidance"], self.checks
        nq, cnq = guide["next_quarter"], c["next_quarter"]
        self.assertEqual(nq["period"], cnq["period"])
        self.assertEqual(nq["fiscal_label"], cnq["fiscal_label"].replace(" ", ""))
        for key in ("revenue_usd_m", "non_gaap_expenses_usd_m", "non_gaap_eps_usd", "diluted_shares_m"):
            with self.subTest(key=key):
                self.assertEqual(nq[key], cnq[key])
        self.assertEqual(nq["non_gaap_tax_rate_pct"], cnq["non_gaap_tax_rate_pct"])
        full, cfull = guide["full_year"], c["full_year"]
        self.assertEqual(full["fiscal_year"], cfull["fiscal_year"])
        for key in ("revenue_usd_m", "non_gaap_eps_usd", "operating_cash_flow_usd_m",
                    "free_cash_flow_usd_m", "capex_usd_m"):
            with self.subTest(key=key):
                self.assertEqual(full["current"][key], cfull[key])
        self.assertEqual(guide["full_year_revenue_footnote"]["expected_ansys_revenue_usd_m"][-1],
                         cfull["expected_ansys_revenue_usd_m"])
        self.assertEqual(full["previous"]["released"], cfull["previous_released"])
        self.assertEqual(full["previous"]["revenue_usd_m"], cfull["previous_revenue_usd_m"])
        self.assertEqual(full["previous"]["non_gaap_eps_usd"], cfull["previous_non_gaap_eps_usd"])
        self.assertEqual(full["previous"]["operating_cash_flow_usd_m"],
                         cfull["previous_operating_cash_flow_usd_m"])

    def test_the_page_prints_the_checked_figures(self) -> None:
        c = self.checks
        self.assertIn(f"收入 US${c['revenue_usd_k'] / 1000:,.0f}M", self.payload["headline"])
        growth = (c["design_ip_revenue_usd_k"] / c["design_ip_revenue_year_ago_usd_k"] - 1) * 100
        self.assertIn(f"同比 {growth:+.1f}%", next(ex["title"] for ex in self.exhibits
                                                  if ex["title"].startswith("Design IP")))
        table = next(t for t in self.payload["tables"] if t["title"].startswith("本季兑现"))
        tax = next(r for r in table["rows"] if r[0] == "non-GAAP 税率")
        self.assertEqual(tax[2], f"{c['non_gaap_tax_rate_pct']:.1f}%")
        eps_move = sum(c["full_year"]["non_gaap_eps_usd"]) / 2 - sum(c["full_year"]["previous_non_gaap_eps_usd"]) / 2
        self.assertIn(f"上调 ${eps_move:.2f}", published_text(table))


class SnpsRollTest(unittest.TestCase):
    """A roll edits the series and nothing else."""

    STAMPED = ("guidance", "market_expectation", "followup_closure", "tracked_metric_verdicts",
               "next_kpi", "ansys_split_note", "quarter_story")

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "snps.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)
        cls.text = published_text(cls.payload)

    def rebuilt(self, edit) -> dict:
        changed = copy.deepcopy(self.source)
        edit(changed)
        return build_payload(changed)

    def moves(self, claims, edit) -> None:
        after = published_text(self.rebuilt(edit))
        for claim in claims:
            with self.subTest(claim=claim):
                self.assertIn(claim, self.text)
                self.assertNotIn(claim, after)

    def test_quarter_blocks_refuse_to_publish_under_another_quarter(self) -> None:
        for key in self.STAMPED:
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    self.rebuilt(lambda s, key=key: s[key].__setitem__("period", "Q1 1999"))
        with self.assertRaisesRegex(ValueError, "sources"):
            self.rebuilt(lambda s: s.__setitem__(
                "sources", [x for x in s["sources"] if "业绩新闻稿" not in x["label"]]))
        with self.assertRaisesRegex(ValueError, "footnote"):
            self.rebuilt(lambda s: s["guidance"]["full_year_revenue_footnote"]["releases"].__setitem__(
                -1, "1999-01-01"))

    def test_a_quarter_without_its_blocks_leaves_them_out(self) -> None:
        def strip(s):
            for key in self.STAMPED:
                del s[key]
        payload = self.rebuilt(strip)
        text = published_text(payload)
        for gone in ("条跟踪指标", "EPS 指引中值高出预期", "量化阈值", "Processor IP Solutions 出售", "收入指引两次上调",
                     "本季兑现与下季／全年指引", "28.7%", "投资者日"):
            with self.subTest(gone=gone):
                self.assertIn(gone, self.text)
                self.assertNotIn(gone, text)
        self.assertEqual([s["id"] for s in payload["sections"]],
                         ["settled", "quarter_highlights", "next_quarter", "routine"])

    def test_a_story_whose_premise_fails_stops_the_build(self) -> None:
        def guide_below(s):
            s["guidance"]["next_quarter"]["non_gaap_eps_usd"] = [3.70, 3.76]
        with self.assertRaisesRegex(ValueError, "guide_beats_quarter"):
            self.rebuilt(guide_below)

        def thinnest_changed(s):
            entry = next(e for e in s["next_kpi"]["quantified"] if e["id"] == "ip_yoy")
            entry["threshold"] = 10.7
        with self.assertRaisesRegex(ValueError, "thinnest"):
            self.rebuilt(thinnest_changed)

        def typed_again(s):
            s["next_kpi"]["quantified"][0]["current"] = 41.6
        with self.assertRaisesRegex(ValueError, "computed from the series"):
            self.rebuilt(typed_again)

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        record = self.source["quarterly_guidance_history"]

        def deeper_miss(s):
            r = s["quarterly_guidance_history"]
            row = r["quarters"].index("Q2 2019")
            r["actual_revenue_usd_m"][row] = r["guide_revenue_lo_usd_m"][row] * 0.9
        self.moves(("看上去是本记录里最大的一次跌破",), deeper_miss)

        def only_two_eps_misses(s):
            r = s["quarterly_guidance_history"]
            row = r["quarters"].index("Q2 2017")
            r["actual_non_gaap_eps_usd"][row] = r["guide_non_gaap_eps_hi_usd"][row]
        after = published_text(self.rebuilt(only_two_eps_misses))
        self.assertIn("三次为负", self.text)
        self.assertIn("两次为负仍是同样的两季", after)

        def ip_streak_shorter(s):
            s["segments_usd_m"]["design_ip_revenue_prior_year_outside_window"]["Q2 2025"] = 400.0
        after = published_text(self.rebuilt(ip_streak_shorter))
        self.assertIn("Design IP 连续四季同比负增长后重新转正", self.text)
        self.assertIn("Design IP 连续三季同比负增长后重新转正", after)

        def amortisation_monotonic(s):
            s["long_history"]["amortization_cost_of_revenue_usd_m"][2] = 70.0
        after = published_text(self.rebuilt(amortisation_monotonic))
        self.assertIn("小幅回升", self.text)
        self.assertNotIn("小幅回升", after)
        self.assertIn("一路降到", after)

        def recognisable_fell(s):
            year_end = max(i for i, label in enumerate(s["backlog"]["fiscal_labels"]) if label.endswith("Q4"))
            s["backlog"]["next_12m_pct_of_ex_fsa"][year_end] = 49.0
        self.moves(("但可确认的那一半从", "深蓝在降、金色在升"), recognisable_fell)

        def korea_not_leading(s):
            d = s["disaggregation_usd_m"]
            d["korea"][-1] -= 40.0
            d["other"][-1] += 40.0
        self.moves(("是全公司最强的一格",), korea_not_leading)

        def shares_over_twice(s):
            r = s["quarterly_guidance_history"]
            row = r["quarters"].index("Q2 2016")
            r["actual_diluted_shares_m"][row] = r["guide_shares_hi_m"][row] + 1
        self.moves(("唯一一次冲出上限的",), shares_over_twice)

        def both_legs_on_break(s):
            r = s["quarterly_guidance_history"]
            row = r["basis_break_at"]
            r["actual_non_gaap_operating_income_usd_m"][row] = 300.0
        after = published_text(self.rebuilt(both_legs_on_break))
        self.assertIn("两条腿同时为负的只有 Q3'21", self.text)
        self.assertIn("Q1'24（", after)
        self.assertEqual(record["quarters"][record["basis_break_at"]], "Q1 2024")

    def test_the_counts_on_the_page_are_recounted_here(self) -> None:
        record = self.source["quarterly_guidance_history"]
        n = sum(1 for v in record["actual_revenue_usd_m"] if v is not None)
        self.assertIn(f"在这里有 {n} 季的完整答案", self.text)
        geo = len(self.source["disaggregation_usd_m"]["quarters"])
        self.assertIn(f"全部{cn_count(geo)}季均为剔除 Software Integrity", self.text)
        self.assertIn(f"{cn_count(len(self.source['backlog']['quarters']))}季度 backlog 与资本配置", self.text)
        # Europe's step is read at the first full Ansys quarter, not at a fixed
        # index: backfilling two quarters at the front had moved a hard-coded
        # [9] - [8] onto Q1'25 - Q4'24 (+1.6pp) under a sentence naming Q3'25.
        d = self.source["disaggregation_usd_m"]
        full = d["quarters"].index("Q2 2025") + 1
        jump = (d["europe"][full] / d["revenue_usd_m"][full]
                - d["europe"][full - 1] / d["revenue_usd_m"][full - 1]) * 100
        self.assertIn(f"欧洲占比在 {compact_period(d['quarters'][full])} 单季跳升 {jump:.1f}pp", self.text)
        self.assertGreater(jump, 0)
        footnote = self.source["guidance"]["full_year_revenue_footnote"]
        mids = [(lo + hi) / 2 for lo, hi in zip(footnote["revenue_lo_usd_m"], footnote["revenue_hi_usd_m"])]
        self.assertIn(f"收入指引{cn_count(sum(1 for a, b in zip(mids, mids[1:]) if b > a))}次上调", self.text)

    def test_the_flat_stretch_is_measured_not_assumed(self) -> None:
        # The gold line is flat only while it stays inside the band the buyback years held it in.
        long = self.source["long_history"]
        buys, shares = long["share_repurchases_usd_m"], long["diluted_shares_m"]
        paid = [s for b, s in zip(buys, shares) if b > 0]
        low, high = min(paid) * 0.99, max(paid) * 1.01
        flat = next((i for i, s in enumerate(shares) if not low <= s <= high), len(shares))
        self.assertLess(flat, len(shares), "the Ansys shares sit above the buyback band")
        self.assertIn(f"金线前{cn_count(flat)}年几乎是一条平线", self.text)

        def no_step(s):
            s["long_history"]["diluted_shares_m"][-1] = max(paid)
        self.assertIn(f"金线{cn_count(len(shares))}年几乎是一条平线", published_text(self.rebuilt(no_step)))

    def test_one_footnote_vintage_draws_no_split_and_points_at_none(self) -> None:
        def one_vintage(s):
            footnote = s["guidance"]["full_year_revenue_footnote"]
            for key, value in footnote.items():
                if isinstance(value, list):
                    footnote[key] = value[-1:]
        text = published_text(self.rebuilt(one_vintage))
        self.assertIn("次上调共", self.text)
        self.assertNotIn("次上调共", text)
        self.assertNotIn("拆解见 Exhibit", text)
        self.assertNotIn("单独成图", text)
        self.assertIsNone(re.search(r"\{[A-Za-z_:]+\}", text))

    def test_a_verb_that_carries_the_direction_prints_the_size(self) -> None:
        for text in (self.text, published_text(self.rebuilt(lambda s: None))):
            self.assertIsNone(re.search(r"(上调共|上修了|下修了|跳升|抬到|降到|升到|掉到) ?(US\$)?[+−-]\d", text))

    def test_no_markdown_reaches_the_page(self) -> None:
        """Exhibit notes and source lines are innerHTML: `**` prints as asterisks."""
        for section in self.payload["sections"]:
            for ex in section["exhibits"]:
                with self.subTest(exhibit=ex["n"]):
                    self.assertNotIn("**", ex.get("note", "") + ex.get("src_extra", ""))


if __name__ == "__main__":
    unittest.main()
