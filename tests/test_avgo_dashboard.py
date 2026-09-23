"""Checks for the AVGO page.

Broadcom's page rests on four claims that would each fail silently on a quarter
roll, so each one is a test rather than a sentence:

* **The fiscal fourth quarter is stitched from a second document type.** XBRL
  carries no standalone quarterly fact for it, so those five values come from
  the quarter's own earnings release while the other twenty-eight come from the
  statements. The only independent check on that seam is that the four quarters
  of each year still add to the filed year, so that is pinned for every complete
  fiscal year, on revenue and on GAAP operating income.
* **The two segments' filed operating incomes sum to the company's non-GAAP
  operating income exactly.** The page attributes the guided margin to a
  semiconductor engine and a software engine on the strength of that identity;
  if it ever stopped holding, the attribution would silently become an estimate.
  FY2019 and earlier need the third, since-retired IP-licensing segment included.
* **The guided record must stay paired to the quarter it guides**, not the one
  the release reports. Every number in section one is worthless if a release's
  Outlook block is ever matched to the wrong quarter, and the two are only ever
  one row apart.
* **The beat decomposition must remain an identity**, because the page says in
  as many words that it is one.

Two more guard things the page asserts about *itself*: that the record's
one-sidedness is real (never below the guided point or midpoint in any finished
quarter, on either metric), and that the outlook is published after the guided
quarter has already begun -- the caveat that stops "never missed" from reading
as a forecasting record.
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
import re
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import avgo  # noqa: E402
from build.all import ENTRIES, build_all, roster_payload  # noqa: E402
from build.board import headroom  # noqa: E402
from build.avgo import build_payload, headline_metrics  # noqa: E402


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


class AvgoDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "avgo.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]
        cls.by_section = {s["id"]: s["exhibits"] for s in cls.payload["sections"]}
        cls.fin = cls.source["financials_usd_m"]
        cls.seg = cls.source["segments_usd_m"]
        cls.guide = cls.source["quarterly_guidance_history"]
        cls.years = cls.source["filed_fiscal_years"]
        cls.ends = cls.source["period_ends"]

    # ── the series itself ────────────────────────────────────────────────────
    def test_net_income_is_the_consolidated_row_and_the_other_two_are_kept(self) -> None:
        """One row for 41 quarters, and the identity that tells the rows apart.

        The eight earliest quarters used to hold "Net income attributable to
        ordinary shares" while everything from 2018-05-06 held the consolidated
        "Net income". Both are printed in one column band of the same statements
        with the Broadcom Cayman L.P. noncontrolling interest between them, so
        this was never an alignment question -- it was two rows in one column.

        Nothing rendered it, which is why nothing failed. The assertion that can
        see it is the three-row identity: consolidated minus noncontrolling
        equals attributable, in every quarter where all three exist. That is a
        real check rather than a value pin, and it fails immediately if the
        column reverts to the attributable row, because then the identity would
        need a noncontrolling interest of zero in quarters where it was -69, +336
        and so on.
        """
        fin = self.source["financials_usd_m"]
        periods = self.source["periods"]
        checked = 0
        for index, period in enumerate(periods):
            total = fin["gaap_net_income"][index]
            nci = fin["net_income_attributable_to_noncontrolling_interest"][index]
            attrib = fin["gaap_net_income_attributable_to_ordinary_shares"][index]
            if nci is None or attrib is None:
                continue
            with self.subTest(period=period):
                self.assertAlmostEqual(total - nci, attrib, places=6)
                self.assertNotEqual(nci, 0.0,
                                    "a zero here would make the two rows the same "
                                    "number and the identity undiscriminating")
            checked += 1
        self.assertEqual(checked, 9, "the nine quarters with all three rows printed")

    def test_the_q3_2017_restatement_records_both_rows(self) -> None:
        """561 and 532 were both right; the file had no way to say which was which.

        The restatement block recorded 561 for period-end 2017-10-29 while the
        series recorded 532, and the file read as though one of them was a
        transcription error. They are the consolidated row and the attributable
        row of the same statement, 29 apart.
        """
        restated = self.source["q3_2017_restatement"]
        for side in ("as_first_reported", "restated"):
            with self.subTest(side=side):
                block = restated[side]
                self.assertAlmostEqual(
                    block["gaap_net_income"]
                    - block["net_income_attributable_to_noncontrolling_interest"],
                    block["gaap_net_income_attributable_to_ordinary_shares"], places=6)

    def test_every_quarterly_series_is_the_same_length_and_in_order(self) -> None:
        n = len(self.ends)
        for group in ("financials_usd_m", "segments_usd_m", "cash_flow_usd_m",
                      "capital_allocation_usd_m", "working_capital_usd_m",
                      "purchase_commitments_usd_m"):
            for name, values in self.source[group].items():
                with self.subTest(series=f"{group}.{name}"):
                    self.assertEqual(len(values), n)
        self.assertEqual(self.ends, sorted(self.ends))
        self.assertEqual(len(set(self.ends)), n)

    def test_calendar_labels_follow_the_fiscal_mapping(self) -> None:
        """The site labels every page by calendar quarter; getting this wrong is
        invisible on the page and wrong in the cross-company capex table.

        Broadcom's year ends in early November, so the company's FY Q1 is the
        previous calendar year's Q4 and each later fiscal quarter maps one step
        back -- the same rule the Synopsys page uses for its October year-end.
        """
        month_to_quarter = {1: "Q4", 2: "Q4", 4: "Q1", 5: "Q1",
                            7: "Q2", 8: "Q2", 10: "Q3", 11: "Q3"}
        for end, period, fiscal in zip(self.ends, self.source["periods"],
                                       self.source["fiscal_labels"]):
            with self.subTest(period_end=end):
                year, month = int(end[:4]), int(end[5:7])
                quarter = month_to_quarter[month]
                calendar_year = year - 1 if quarter == "Q4" else year
                self.assertEqual(period, f"{quarter} {calendar_year}")
                fiscal_quarter = {1: 1, 2: 1, 4: 2, 5: 2, 7: 3, 8: 3, 10: 4, 11: 4}[month]
                self.assertEqual(fiscal, f"FY{year} Q{fiscal_quarter}")

    def test_quarterly_series_reconcile_with_the_filed_full_year(self) -> None:
        """The fiscal fourth quarter comes from the release, not the statements.

        Every other quarter is an XBRL fact; the fiscal fourth is not tagged
        standalone and is read off that quarter's own earnings release instead.
        A mis-stitched fourth quarter would look perfectly ordinary on the page,
        and the year total is the only thing that would notice.
        """
        by_end = dict(zip(self.ends, self.fin["revenue"]))
        oi_by_end = dict(zip(self.ends, self.fin["gaap_operating_income"]))
        checked = 0
        for index, year_end in enumerate(self.years["fiscal_year_ends"]):
            quarters = [end for end in self.ends if end <= year_end][-4:]
            if len(quarters) < 4 or quarters[0] < self.ends[0]:
                continue
            # only a year whose four quarters are all inside the reviewed window
            span_start = quarters[0]
            if (int(year_end[:4]) - int(span_start[:4])) > 1:
                continue
            with self.subTest(fiscal_year_end=year_end):
                self.assertAlmostEqual(
                    sum(by_end[q] for q in quarters),
                    self.years["revenue_usd_m"][index], delta=1.0)
                self.assertAlmostEqual(
                    sum(oi_by_end[q] for q in quarters),
                    self.years["gaap_operating_income_usd_m"][index], delta=1.0)
                checked += 1
        self.assertGreaterEqual(checked, 7)

    def test_fy2017_operating_income_is_the_last_filed_value_not_the_first(self) -> None:
        """Three filed values for one year, and the page carries the newest.

        FY2017 GAAP operating income appears as 2,493 in the 2017-12-06 earnings
        release, 2,383 in the FY2017 10-K and again in the FY2018 10-K's
        comparative column, and 2,371 in the FY2019 10-K's comparative column.
        All three are filed; the difference is *which filing*.

        This page stored 2,371 for one commit, on the repo's usual rule that the
        newest reading wins. That was wrong here, and the page's own identity is
        what said so: the four fiscal quarters of FY2017 are 506 + 474 + 648 +
        755 = 2,383, and the FY2019 10-K restated only the annual comparative --
        it never republished a quarter. Taking the newest value for the year and
        the only available value for the quarters left the two legs on different
        bases and the sum twelve short of the total.

        So the rule has an exception, and this is it: an annual figure has to sit
        on the same basis as the quarters that make it up. 2,371 stays recorded
        beside it, because anyone checking this page against the FY2019 10-K will
        find that number and needs to be told why it is not the one shown.
        """
        record = self.years["fy2017_operating_income_has_three_filed_values"]
        index = self.years["fiscal_year_ends"].index("2017-10-29")
        stored = self.years["gaap_operating_income_usd_m"][index]
        self.assertEqual(stored, 2383.0)
        self.assertEqual(record["stored"], stored)
        values = [entry["value"] for entry in record["values"]]
        self.assertEqual(values, [2493.0, 2383.0, 2371.0],
                         "release, then the first two 10-Ks, then the newest")
        self.assertEqual(len(set(values)), 3, "three genuinely different figures")
        self.assertIn("四季之和", record["why_this_one"])
        # The identity that decided it, asserted rather than described.
        ends = self.ends
        quarters = [i for i, end in enumerate(ends) if "2016-10-31" <= end <= "2017-10-29"]
        self.assertEqual(len(quarters), 4)
        self.assertAlmostEqual(
            sum(self.fin["gaap_operating_income"][i] for i in quarters), stored,
            delta=0.01)
        # Each one has to name where it came from, or the note is decoration.
        for entry in record["values"]:
            self.assertIn("-", entry["source"])
            self.assertTrue(entry["kind"])

    def test_the_debt_series_says_which_debt_it_means(self) -> None:
        """Two consecutive quarters carry the same number, and that is correct.

        2022-05-01 and 2022-07-31 both read 41,227. It looks like a paste, and
        an adversarial read of this page flagged it as one. It is not: the
        FY2022 Q2 10-Q and the FY2022 Q3 10-Q are two independent filings and
        both print 40,958 non-current plus 269 current. Broadcom neither issued
        nor retired anything between those two balance-sheet dates.

        The series is the balance sheet, not the earnings release -- the two
        differ by definition, which is the other half of why this note exists.
        """
        notes = self.source["capital_allocation_notes"]
        self.assertIn("40,958", notes["total_debt"])
        self.assertIn("两份互相独立的申报", notes["total_debt"])
        debt = self.source["capital_allocation_usd_m"]["total_debt"]
        ends = self.ends
        first = ends.index("2022-05-01")
        self.assertEqual(debt[first], debt[first + 1])
        self.assertEqual(ends[first + 1], "2022-07-31")
        # ...and it is the only consecutive repeat in the series, so a second
        # one appearing later is a question rather than a precedent.
        repeats = [ends[i] for i in range(1, len(debt))
                   if debt[i] is not None and debt[i] == debt[i - 1]]
        self.assertEqual(repeats, ["2022-07-31"])

    def test_segment_revenue_sums_to_the_consolidated_statement(self) -> None:
        """Two reportable segments today, three until the FY2019 IP-licensing
        line was wound down. Dropping the third would leave a residual that
        looks like a rounding error and is not one."""
        checked = 0
        for index, end in enumerate(self.ends):
            semi = self.seg["semiconductor_revenue"][index]
            isg = self.seg["infrastructure_software_revenue"][index]
            if semi is None or isg is None:
                continue
            ipl = self.seg["ip_licensing_revenue"][index] or 0.0
            with self.subTest(period_end=end):
                self.assertAlmostEqual(semi + isg + ipl, self.fin["revenue"][index], delta=1.0)
                checked += 1
        self.assertGreaterEqual(checked, 30)

    def test_segment_operating_income_sums_to_non_gaap_operating_income(self) -> None:
        """The identity the whole segment view rests on.

        Broadcom's segment note measures each segment's operating income before
        the items its own non-GAAP definition removes, so the segments add up to
        the non-GAAP line rather than the GAAP one. That is what lets the page
        split a guided *margin* between the two engines with no estimate. It has
        held exactly -- not approximately -- in every quarter the note covers.
        """
        checked = 0
        for index, end in enumerate(self.ends):
            semi = self.seg["semiconductor_operating_income"][index]
            isg = self.seg["infrastructure_software_operating_income"][index]
            if semi is None or isg is None:
                continue
            ipl = self.seg["ip_licensing_operating_income"][index] or 0.0
            with self.subTest(period_end=end):
                self.assertAlmostEqual(
                    semi + isg + ipl,
                    self.fin["non_gaap_operating_income"][index], delta=0.5)
                checked += 1
        self.assertGreaterEqual(checked, 30)

    def test_undisclosed_quarters_stay_empty(self) -> None:
        """FY2018's reportable segments were four product lines, not the two the
        page plots, so those quarters must be holes rather than being padded."""
        for index, end in enumerate(self.ends):
            if end >= "2019-02-03":
                continue
            with self.subTest(period_end=end):
                self.assertIsNone(self.seg["semiconductor_revenue"][index])
                self.assertIsNone(self.seg["infrastructure_software_revenue"][index])

    def test_segment_gross_margin_rests_on_filed_segment_cost(self) -> None:
        """Segment cost exists only since ASU 2023-07, and it is now long enough to draw.

        This test used to assert the opposite: two quarters of segment cost, so
        no segment gross margin anywhere on the page. That was right while the
        FY2026 10-Qs were the only source. They carry the prior year's quarter
        in their comparative columns, and the FY2025 10-K gives the year, so
        FY2025 Q1-Q4 exist too -- and the previous report settled a threshold
        on exactly this ratio (「半导体分部 GM <68%」). The report read it off a
        rounded call figure and a software-margin assumption (67.01%); the page
        reads the filed segment cost.

        Pinned: the fiscal quarters close on the 10-K year; the two segments'
        costs add to the company's non-GAAP cost of revenue (revenue less the
        release's non-GAAP gross margin), which is what licenses calling this a
        non-GAAP segment margin; nothing before the disclosure starts is filled.
        """
        cost = self.seg["semiconductor_cost_of_revenue"]
        soft = self.seg["infrastructure_software_cost_of_revenue"]
        filled = [i for i, v in enumerate(cost) if v is not None]
        self.assertEqual(filled, list(range(filled[0], len(cost))), "a hole inside the run")
        self.assertEqual([i for i, v in enumerate(soft) if v is not None], filled)
        first_end = self.ends[filled[0]]
        self.assertEqual(first_end, "2025-02-02", "FY2025 Q1 is the first quarter a filing covers")
        years = self.years
        closed = 0
        for index, year_end in enumerate(years["fiscal_year_ends"]):
            quarters = [i for i, end in enumerate(self.ends) if end <= year_end][-4:]
            if len(quarters) < 4 or any(cost[i] is None for i in quarters):
                continue
            with self.subTest(fiscal_year_end=year_end):
                self.assertEqual(sum(cost[i] for i in quarters),
                                 years["semiconductor_cost_of_revenue_usd_m"][index])
                self.assertEqual(sum(soft[i] for i in quarters),
                                 years["infrastructure_software_cost_of_revenue_usd_m"][index])
                closed += 1
        self.assertGreaterEqual(closed, 1)
        recon = self.source["release_reconciliation_usd_m"]
        for i in filled:
            with self.subTest(period_end=self.ends[i]):
                self.assertAlmostEqual(cost[i] + soft[i],
                                       self.fin["revenue"][i] - recon["non_gaap_gross_margin"][i],
                                       delta=0.5)
        chart = next(ex for ex in self.by_section["settled"]
                     if ex["title"].startswith("半导体分部毛利率"))
        margins = [(self.seg["semiconductor_revenue"][i] - cost[i])
                   / self.seg["semiconductor_revenue"][i] * 100 for i in filled]
        self.assertEqual(len(chart["xlabels"]), len(filled))
        for drawn, expected in zip(chart["series"][0]["values"], margins):
            self.assertAlmostEqual(drawn, expected, places=5)

    # ── the guided record ────────────────────────────────────────────────────
    def test_guidance_record_is_paired_on_the_guided_quarter(self) -> None:
        """Each Outlook block guides the quarter *after* the one being reported.

        Pairing a release to the quarter it reports rather than the one it
        guides would shift the entire record by one row and still look
        plausible, because consecutive quarters are similar. Two independent
        facts pin it: the release must fall inside the quarter it guides, and it
        must be the release that immediately precedes that quarter's own.
        """
        release_of = dict(zip(self.ends, self.source["release_dates"]))
        for index, end in enumerate(self.guide["period_ends"]):
            released = self.guide["guided_in_release"][index]
            with self.subTest(guided_quarter=end):
                self.assertLess(released, end)
                if end in release_of:
                    self.assertLess(released, release_of[end])

    def test_guidance_is_published_after_the_guided_quarter_has_begun(self) -> None:
        """The caveat that keeps 'never missed' honest.

        Broadcom publishes each quarter's outlook alongside the previous
        quarter's results, which lands about a third of the way into the quarter
        being guided. A record with no misses means something much weaker when
        part of the quarter is already banked, so the page prints this on every
        guidance chart -- and the numbers behind it are checked here.
        """
        for index, end in enumerate(self.guide["period_ends"]):
            days = self.guide["days_into_quarter_at_release"][index]
            length = self.guide["quarter_length_days"][index]
            with self.subTest(guided_quarter=end):
                self.assertGreater(days, 0, "guidance would be ex-ante, contradicting the page")
                self.assertLess(days, length)
        median = sorted(self.guide["days_into_quarter_at_release"])[
            len(self.guide["days_into_quarter_at_release"]) // 2]
        self.assertGreaterEqual(median, 24)
        self.assertLessEqual(median, 40)
        # The record's six charts close section one; what precedes them (the
        # follow-up and verdict charts) exists only in quarters that have them.
        for exhibit in self.by_section["settled"][-6:]:
            with self.subTest(exhibit=exhibit["n"]):
                self.assertIn("时点提醒", exhibit["note"] + exhibit.get("src_extra", ""))

    def test_guidance_form_flag_agrees_with_its_endpoints(self) -> None:
        """A point drawn as a band would invent a width the company never gave."""
        for index, form in enumerate(self.guide["revenue_form"]):
            lo = self.guide["guide_revenue_lo_usd_m"][index]
            hi = self.guide["guide_revenue_hi_usd_m"][index]
            mid = self.guide["guide_revenue_usd_m"][index]
            with self.subTest(quarter=self.guide["periods"][index], form=form):
                self.assertIn(form, ("range", "point"))
                if form == "point":
                    self.assertEqual(lo, mid)
                    self.assertEqual(hi, mid)
                else:
                    self.assertLess(lo, hi)
                    self.assertAlmostEqual((lo + hi) / 2, mid, places=6)

    def test_the_record_never_landed_below_the_guided_number(self) -> None:
        """The page's central claim, on both guided metrics."""
        finished = [i for i, v in enumerate(self.guide["actual_revenue_usd_m"]) if v is not None]
        self.assertGreaterEqual(len(finished), 24)
        for index in finished:
            with self.subTest(quarter=self.guide["periods"][index]):
                self.assertGreaterEqual(
                    self.guide["actual_revenue_usd_m"][index],
                    self.guide["guide_revenue_lo_usd_m"][index])
                self.assertGreaterEqual(
                    self.guide["actual_revenue_usd_m"][index],
                    self.guide["guide_revenue_usd_m"][index])
        # An EBITDA guide can now outlive the measure it was written in: Broadcom
        # stopped publishing Adjusted EBITDA with the 2026-09-02 release, so the
        # guide it had already given for that quarter can never be settled. Those
        # quarters are excluded from the claim rather than counted as passes --
        # and the exclusion is itself pinned, so a *second* unsettled quarter
        # cannot slip in without this test noticing.
        guided = [i for i in finished
                  if self.guide["guide_ebitda_margin_pct"][i] is not None]
        margin = [i for i in guided
                  if self.guide["actual_ebitda_margin_pct"][i] is not None]
        self.assertGreaterEqual(len(margin), 18)
        unsettled = [self.guide["periods"][i] for i in guided if i not in margin]
        stop = self.source["adjusted_ebitda_disclosure_stop"]
        self.assertEqual(
            unsettled, [stop["first_missing_period"]],
            "an EBITDA guide with no actual must be the documented disclosure stop")
        for index in margin:
            with self.subTest(quarter=self.guide["periods"][index], metric="ebitda margin"):
                self.assertGreater(
                    self.guide["actual_ebitda_margin_pct"][index],
                    self.guide["guide_ebitda_margin_pct"][index])

    def test_every_range_quarter_landed_inside_its_range(self) -> None:
        """The other half of the two-sided finding: when there was a band, the
        quarter stayed in it -- above it zero times, below it zero times."""
        ranges = [i for i, f in enumerate(self.guide["revenue_form"]) if f == "range"]
        self.assertEqual(len(ranges), 5)
        for index in ranges:
            actual = self.guide["actual_revenue_usd_m"][index]
            with self.subTest(quarter=self.guide["periods"][index]):
                self.assertIsNotNone(actual)
                self.assertGreaterEqual(actual, self.guide["guide_revenue_lo_usd_m"][index])
                self.assertLessEqual(actual, self.guide["guide_revenue_hi_usd_m"][index])

    def test_actual_ebitda_margin_is_the_reported_ratio(self) -> None:
        by_end = dict(zip(self.ends, zip(self.fin["adjusted_ebitda"], self.fin["revenue"],
                                         self.fin["non_gaap_operating_income"])))
        for index, end in enumerate(self.guide["period_ends"]):
            if end not in by_end:
                continue
            ebitda, revenue, ng_oi = by_end[end]
            with self.subTest(period_end=end):
                if ebitda is None:
                    # The measure stopped being published; the ratio must go
                    # empty with it rather than carry a recomputed stand-in.
                    self.assertIsNone(self.guide["actual_ebitda_margin_pct"][index])
                else:
                    self.assertAlmostEqual(self.guide["actual_ebitda_margin_pct"][index],
                                           ebitda / revenue * 100, places=3)
                self.assertAlmostEqual(
                    self.guide["actual_non_gaap_operating_margin_pct"][index],
                    ng_oi / revenue * 100, places=3)

    def test_beat_decomposition_is_an_identity(self) -> None:
        """actual − guided revenue × guided margin == revenue leg + margin leg."""
        checked = 0
        for index, guided_margin in enumerate(self.guide["guide_ebitda_margin_pct"]):
            actual_margin = self.guide["actual_ebitda_margin_pct"][index]
            if guided_margin is None or actual_margin is None:
                continue
            guided_revenue = self.guide["guide_revenue_usd_m"][index]
            actual_revenue = self.guide["actual_revenue_usd_m"][index]
            implied = guided_revenue * guided_margin / 100
            actual = self.guide["actual_adjusted_ebitda_usd_m"][index]
            revenue_leg = (actual_revenue - guided_revenue) * guided_margin / 100
            margin_leg = actual_revenue * (actual_margin - guided_margin) / 100
            with self.subTest(quarter=self.guide["periods"][index]):
                self.assertAlmostEqual(actual - implied, revenue_leg + margin_leg, delta=0.01)
                checked += 1
        self.assertGreaterEqual(checked, 18)

    def test_annual_only_guidance_covers_the_gaps_in_the_quarterly_record(self) -> None:
        """Eight reported quarters were never guided as quarters. The page shows
        them as gaps rather than zeros, and lists the annual guidance that
        replaced them, so the record's holes are visible instead of implied."""
        guided = set(self.guide["period_ends"])
        first = min(guided)
        gaps = [end for end in self.ends if end >= first and end not in guided]
        self.assertEqual(len(gaps), 8)
        self.assertEqual(len(self.source["annual_only_guidance"]), 8)
        for entry in self.source["annual_only_guidance"]:
            with self.subTest(released=entry["released"]):
                self.assertLess(entry["released"], entry["fiscal_year_end"])
                self.assertGreater(entry["revenue_usd_m"], 0)

    def test_non_gaap_operating_margin_guidance_is_a_record_now(self) -> None:
        """This block used to assert the guide appeared in exactly one release and
        had no delivery record. The 2026-09-02 release gave it a second time and
        settled the first, so the old shape was not merely out of date -- it was a
        universal claim that the next filing falsified. What replaces it is a
        record whose settled entries must reconcile against the quarterly series,
        and whose unsettled entries must be quarters the page has not reached."""
        record = self.source["non_gaap_operating_margin_guidance"]
        columns = ["period_ends", "periods", "fiscal_labels", "guided_in_release",
                   "guide_pct", "qualifier", "actual_pct"]
        lengths = {len(record[name]) for name in columns}
        self.assertEqual(len(lengths), 1, "the record's columns must stay aligned")
        self.assertGreaterEqual(record["period_ends"].count("2026-08-02"), 1)

        by_end = dict(zip(self.ends, zip(self.fin["non_gaap_operating_income"],
                                         self.fin["revenue"])))
        settled = 0
        for index, end in enumerate(record["period_ends"]):
            with self.subTest(period_end=end):
                if record["actual_pct"][index] is None:
                    self.assertNotIn(end, by_end,
                                     "an unsettled entry must be a quarter the page has not reached")
                    continue
                self.assertIn(end, by_end)
                ng_oi, revenue = by_end[end]
                self.assertAlmostEqual(record["actual_pct"][index],
                                       ng_oi / revenue * 100, places=3)
                self.assertGreater(record["actual_pct"][index], record["guide_pct"][index])
                settled += 1
        self.assertGreaterEqual(settled, 1, "the first guide has been settled")

    # ── a roll edits the series and nothing else ─────────────────────────────
    def test_quarter_blocks_refuse_to_publish_under_another_quarter(self) -> None:
        """What only one quarter has must say which quarter, and a stale one stops the build.

        The follow-up closure, the prior thresholds' settlement, the guidance by
        line, the next-quarter thresholds and the buyback story carry the quarter
        they describe; the outlook and the AI guide carry the release they came
        from; the release itself must be in the source list. Each is tampered
        alone here and each must stop the build with a message that names the
        stamp.
        """
        stamped = ("followup_closure", "prior_kpi_settlement", "guidance_by_line", "next_kpi",
                   "capital_return_story")
        for key in stamped:
            stale = copy.deepcopy(self.source)
            stale[key]["period"] = "Q1 1999"
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    build_payload(stale)
        stale = copy.deepcopy(self.source)
        stale["guidance"]["next_quarter"]["released"] = "1999-01-01"
        with self.assertRaisesRegex(ValueError, "stamped"):
            build_payload(stale)
        stale = copy.deepcopy(self.source)
        stale["ai_semiconductor_disclosures"]["next_quarter_guided_in_release"] = "1999-01-01"
        with self.assertRaisesRegex(ValueError, "stamped"):
            build_payload(stale)
        stale = copy.deepcopy(self.source)
        fiscal = self.source["fiscal_labels"][-1]
        stale["sources"] = [s for s in stale["sources"] if not s["label"].startswith(f"{fiscal} 业绩新闻稿")]
        self.assertNotEqual(len(stale["sources"]), len(self.source["sources"]))
        with self.assertRaisesRegex(ValueError, "sources"):
            build_payload(stale)

    def test_a_quarter_without_a_story_leaves_it_out(self) -> None:
        """Absent, an optional one-quarter block drops its chart rather than borrowing last quarter's."""
        bare = copy.deepcopy(self.source)
        for key in ("guidance_by_line", "capital_return_story"):
            del bare[key]
        payload = build_payload(bare)
        titles = [ex["title"] for s in payload["sections"] for ex in s["exhibits"]]
        self.assertFalse([t for t in titles if "按业务线拆开" in t])
        self.assertNotIn("公司没有解释", payload["headline"])
        self.assertEqual(len(titles), len(self.exhibits) - 1)

    def test_a_quarter_after_the_first_report_must_settle_it(self) -> None:
        """The settlement blocks are not optional once a report precedes the quarter.

        Dropping one used to drop its chart silently, which is how this page came
        to settle six questions and five thresholds of its own instead of the
        report's. After the first local report, a quarter without both blocks
        stops the build and says which block and which quarter.
        """
        for key in ("followup_closure", "prior_kpi_settlement"):
            bare = copy.deepcopy(self.source)
            del bare[key]
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "followup_closure.*prior_kpi_settlement"):
                    build_payload(bare)

    def test_the_first_report_quarter_settles_nothing_and_says_so(self) -> None:
        """The quarter of the site's first AVGO analysis has nothing before it to settle."""
        first = {"periods": ["Q3 2025", avgo.FIRST_REPORT_PERIOD]}
        charts, tables, facts = avgo.settle_prior(first, {}, {})
        self.assertEqual((charts, tables), ([], []))
        self.assertTrue(facts["first"])
        with self.assertRaisesRegex(ValueError, "nothing"):
            avgo.settle_prior({**first, "followup_closure": {"period": avgo.FIRST_REPORT_PERIOD}}, {}, {})

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        """Make one finished point quarter miss its guide: every sentence that says
        「一次都没有低于」 must stop saying it. A sentence that survived this would be
        a remembered claim, not a computed one."""
        missed = copy.deepcopy(self.source)
        record = missed["quarterly_guidance_history"]
        row = max(i for i, v in enumerate(record["actual_revenue_usd_m"]) if v is not None)
        record["actual_revenue_usd_m"][row] = record["guide_revenue_usd_m"][row] - 100
        before = json.dumps(self.payload, ensure_ascii=False)
        after = json.dumps(build_payload(missed), ensure_ascii=False)
        claims = ("一次都没有低于指引的点或中值", "全部高于</b>那个点", "从未低于指引",
                  "与正式指引的形态一致")
        for claim in claims:
            with self.subTest(claim=claim):
                self.assertIn(claim, before)
                self.assertNotIn(claim, after)

    def test_filing_dates_come_after_their_release_and_before_the_review(self) -> None:
        """The 10-Q lag the page quotes is read from EDGAR's own dates, so the
        dates themselves are held to what an EDGAR index can be: every report
        follows its quarter's results release, none postdates the review, and
        the lag the commitments chart prints is the one they give."""
        reports = self.source["periodic_reports_filed"]["reports"]
        release_of = dict(zip(self.ends, self.source["release_dates"]))
        review = self.source["latest"]["analysis_date"]
        self.assertTrue(reports)
        for row in reports:
            with self.subTest(period_end=row["period_end"]):
                self.assertIn(row["period_end"], release_of)
                self.assertGreater(row["filed"], release_of[row["period_end"]])
                self.assertLessEqual(row["filed"], review)
                self.assertIn(row["form"], ("10-Q", "10-K"))
        by_end = {row["period_end"]: row for row in reports}
        year_ago = self.ends[-5]
        commit = next(ex for ex in self.by_section["quarter_highlights"] if "采购承诺" in ex["title"])
        if self.source["purchase_commitments_usd_m"]["total"][-1] is None and year_ago in by_end:
            lag = (datetime.date.fromisoformat(by_end[year_ago]["filed"])
                   - datetime.date.fromisoformat(release_of[year_ago])).days
            self.assertIn(f"去年同季是发布后第 {lag} 天", commit["note"])

    # ── AI revenue is a different tier of disclosure ─────────────────────────
    def test_ai_revenue_is_labelled_as_a_quote_not_a_segment(self) -> None:
        """It comes from the CEO quote, not the Business Outlook block and not
        the segment note; mixing it into the formal record would overstate what
        the filings support."""
        ai = self.source["ai_semiconductor_disclosures"]
        self.assertIn(None, ai["actual_usd_bn"], "the quarter with no level must stay empty")
        self.assertTrue(any(ai["actual_is_floor"]), "the 'over $4.4 billion' floor must be flagged")
        chart = next(ex for ex in self.by_section["quarter_highlights"] if "AI 半导体收入" in ex["title"])
        self.assertIn("不是", chart["note"])
        self.assertIn("引语", chart["note"] + chart["src_extra"])
        # The formal guidance record never mixes the AI quote in. Section one
        # does settle the previous report's AI thresholds and the call-level
        # split of the guide, and every such chart names the quote as its source.
        self.assertNotIn("AI", " ".join(
            ex.get("title", "") for ex in self.by_section["settled"][-6:]))
        for exhibit in self.by_section["settled"]:
            if "AI" in exhibit["title"]:
                with self.subTest(exhibit=exhibit["title"][:30]):
                    self.assertIn("引语", exhibit["src_extra"])

    def test_the_ai_note_counts_its_pairs_and_names_its_holes(self) -> None:
        """This series is three-quarters holes and one-quarter numbers, so what
        the note claims about it has to be recomputed, not remembered.

        It said "of the four pairs so far, the actual came in slightly above the
        spoken guidance every time". The count was right and the claim was not:
        Q1 2025 was guided "over $4.4 billion" and reported 4.4 -- meeting a
        floor, not beating it. Extending the series back to Q1 2024 then added
        two more empty quarters with a different cause from the one the note
        already explained (those two releases gave a full-year AI figure and no
        quarterly one), and a note that explains one kind of hole while showing
        three reads as though the others were extraction failures.
        """
        ai = self.source["ai_semiconductor_disclosures"]
        pairs = [(g, a) for g, a in zip(ai["guided_usd_bn"], ai["actual_usd_bn"])
                 if g is not None and a is not None]
        chart = next(ex for ex in self.by_section["quarter_highlights"]
                     if ex["title"].startswith("AI 半导体收入："))
        self.assertIn(f"已有的 {len(pairs)} 对", chart["note"])
        # never claim a clean beat while a pair merely met its floor
        beat = sum(1 for guided, actual in pairs if actual > guided + 1e-9)
        met = sum(1 for guided, actual in pairs if abs(actual - guided) <= 1e-9)
        self.assertEqual(beat + met, len(pairs), "a pair came in below guidance")
        if met:
            self.assertIn("相等", chart["note"])
            self.assertNotIn("每次都", chart["note"])
        # every empty quarter is accounted for in the prose
        empty = [period for period, actual
                 in zip(ai["periods"], ai["actual_usd_bn"]) if actual is None]
        self.assertTrue(empty)
        for period in empty:
            with self.subTest(period=period):
                self.assertIn(period, chart["note"],
                              "an empty quarter the note never mentions reads as "
                              "a failed extraction rather than a disclosure gap")

    # ── the page ─────────────────────────────────────────────────────────────
    def test_page_is_chart_led(self) -> None:
        self.assertGreaterEqual(len(self.exhibits), 20)
        for exhibit in self.exhibits:
            with self.subTest(exhibit=exhibit.get("n")):
                self.assertTrue(exhibit.get("title"))
                self.assertTrue(exhibit.get("note"))
                self.assertIn("n", exhibit)

    def test_exhibit_numbers_are_sequential_and_refs_resolved(self) -> None:
        numbers = [ex["n"] for ex in self.exhibits]
        self.assertEqual(numbers, list(range(2, 2 + len(numbers))))
        for exhibit in self.exhibits:
            for field in ("title", "note", "src_extra"):
                with self.subTest(exhibit=exhibit["n"], field=field):
                    self.assertNotIn("{EX_", exhibit.get(field) or "")
                    self.assertNotIn("ref", exhibit)

    def test_the_page_has_the_sites_four_sections_in_order(self) -> None:
        """The site's fixed layout, ids and titles verbatim, none of them empty.

        This page's second section used to carry the id `highlights` and its
        first the title 「一、上季兑现了吗」: both close to the site's layout and
        neither the layout itself, so a site-wide check keyed on the ids or the
        titles could not see this page.
        """
        self.assertEqual([(s["id"], s["title"]) for s in self.payload["sections"]],
                         [("settled", "一、上季跟踪指标兑现了吗"),
                          ("quarter_highlights", "二、本季重点"),
                          ("next_quarter", "三、下季要跟踪什么"),
                          ("routine", "四、长期常规跟踪")])
        for section in self.payload["sections"]:
            with self.subTest(section=section["id"]):
                self.assertTrue(section["exhibits"])
                self.assertTrue(section["description"].strip())
        self.assertIn("本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列",
                      " ".join(self.payload["notes"]))

    def test_charts_sit_in_the_section_their_content_answers(self) -> None:
        """A 42-quarter structural line is routine; this quarter's capital allocation is a highlight."""
        where = {ex["title"].split("：")[0]: section["id"]
                 for section in self.payload["sections"] for ex in section["exhibits"]}
        self.assertEqual(where["GAAP 与 non-GAAP 营业利润率的缺口"], "routine")
        self.assertEqual(where["股东回报与其资金来源"], "quarter_highlights")

    def test_headroom_bars_reproduce_the_next_quarter_thresholds(self) -> None:
        entries = self.source["next_kpi"]["quantified"]
        chart = self.by_section["next_quarter"][0]
        self.assertEqual(chart["xlabels"], [e["metric"] for e in entries])
        for value, entry in zip(chart["values"], entries):
            with self.subTest(metric=entry["metric"]):
                self.assertAlmostEqual(
                    value, round(headroom(entry["direction"], entry["threshold"],
                                          entry["current"]), 1), places=6)

    def test_every_tracked_metric_with_a_series_gets_its_own_chart(self) -> None:
        entries = self.source["next_kpi"]["quantified"]
        charts = self.by_section["next_quarter"][1:]
        self.assertEqual(len(charts), len(entries))
        for entry, chart in zip(entries, charts):
            with self.subTest(metric=entry["metric"]):
                self.assertIn(entry["metric"], chart["title"])
        # The metrics that have no series must be named where the reader is
        # looking at the ones that do, not dropped silently.
        self.assertTrue(self.source["next_kpi"]["excluded"])
        self.assertIn(self.source["next_kpi"]["excluded"],
                      self.by_section["next_quarter"][0]["note"])

    def test_audit_tables_back_every_derived_exhibit(self) -> None:
        tables = self.payload["tables"]
        self.assertEqual([t["n"] for t in tables], list(range(1, len(tables) + 1)))
        for table in tables:
            with self.subTest(table=table["n"]):
                self.assertTrue(table["title"])
                self.assertTrue(table["rows"])
                for row in table["rows"]:
                    self.assertEqual(len(row), len(table["headers"]))

    def test_every_series_backed_prior_threshold_has_its_own_line(self) -> None:
        """A threshold whose metric has a time series is drawn against it, not only summarised."""
        entries = self.source["prior_kpi_settlement"]["quantified"]
        lines = [ex for ex in self.by_section["settled"] if ex["kind"] == "lines"]
        backed = [e for e in entries if e.get("reads") in
                  ("ai_revenue", "semi_gross_margin", "software_revenue", "buyback")]
        self.assertGreaterEqual(len(backed), 6)
        for entry in backed:
            with self.subTest(threshold=entry["id"]):
                flat = [chart for chart in lines for series in chart["series"][1:]
                        if set(series["values"]) == {entry["threshold"]}]
                self.assertEqual(len(flat), 1, "exactly one chart draws this line")
                self.assertIn(entry["line"], flat[0]["title"])
        # call-only readings have no series and so no line -- they are in the
        # overview and the table, named as call statements
        for entry in entries:
            if "reads" not in entry:
                self.assertIn("电话会", entry["metric"])
                self.assertIn("电话会", entry["value_source"])

    def test_the_guidance_split_by_line_adds_up(self) -> None:
        """AI above its guide, the other two lines below theirs, and nothing left over."""
        chart = next(ex for ex in self.by_section["settled"] if "按业务线拆开" in ex["title"])
        legs, total = chart["values"][:-1], chart["values"][-1]
        self.assertAlmostEqual(sum(legs), total, places=6)
        guide = self.guide["guide_revenue_usd_m"][self.guide["periods"].index(self.source["periods"][-1])]
        self.assertAlmostEqual(total, self.fin["revenue"][-1] - guide, places=6)
        ai = self.source["ai_semiconductor_disclosures"]
        at = ai["periods"].index(self.source["periods"][-1])
        self.assertAlmostEqual(legs[0], (ai["actual_usd_bn"][at] - ai["guided_usd_bn"][at]) * 1000, places=6)
        self.assertAlmostEqual(
            legs[2], self.seg["infrastructure_software_revenue"][-1]
            - self.source["guidance_by_line"]["infrastructure_software_usd_m"], places=6)

    def test_guidance_record_table_covers_every_guided_quarter(self) -> None:
        table = next(t for t in self.payload["tables"] if t["title"].startswith("指引兑现全表"))
        self.assertEqual(len(table["rows"]), len(self.guide["period_ends"]))
        verdicts = {row[7] for row in table["rows"]}
        self.assertNotIn("低于下限", verdicts)
        self.assertNotIn("低于", verdicts)
        self.assertIn("待披露", verdicts)

    def test_avgo_is_absent_from_the_cross_page_capex_table(self) -> None:
        """Deliberate, and recorded here so a later change is a decision.

        The shared table runs hyperscaler cash capex -> NVDA Data Center -> TSMC
        wafers. Broadcom is neither a hyperscaler nor a foundry, and its own cash
        capex is about 1% of revenue, so adding a column would say nothing about
        the cycle and would rewrite every other page's payload to do it.
        """
        table = next(t for t in self.payload["tables"] if "AI capex" in t["title"])
        self.assertNotIn("AVGO", " ".join(table["headers"]))

    def test_market_expectation_is_labelled_and_unattributed(self) -> None:
        expectation = self.source["market_expectation"]
        self.assertTrue(expectation["as_of"])
        for banned in ("摩根", "高盛", "JPMorgan", "Goldman", "Morgan Stanley",
                       "Bernstein", "HSBC", "Macquarie", "RBC"):
            self.assertNotIn(banned, json.dumps(self.payload, ensure_ascii=False))

    def test_no_rating_or_target_price_is_published(self) -> None:
        """The words appear on the page only where it says it does not publish
        them, so scanning the whole payload would flag the disclaimer itself.
        What must be clean is everywhere a rating could actually be asserted:
        the headline, the takeaways, chart titles, and every audit-table cell.
        """
        published = [self.payload["headline"], self.payload["brief"],
                     self.payload["title"], self.payload["subtitle"]]
        published += [ex.get("title", "") for ex in self.exhibits]
        published += [str(cell) for table in self.payload["tables"]
                      for row in table["rows"] for cell in row]
        published += [h for table in self.payload["tables"] for h in table["headers"]]
        for banned in ("目标价", "评级", "增持", "减持", "买入", "卖出",
                       "target price", "Overweight", "Underweight"):
            for text in published:
                with self.subTest(term=banned, text=text[:40]):
                    self.assertNotIn(banned, text)
        notes = " ".join(self.payload["notes"])
        self.assertIn("不发布评级、目标价或估值", notes)

    def test_sources_are_official_http_links(self) -> None:
        for link in self.payload["source_links"]:
            with self.subTest(link=link["label"]):
                parsed = urlparse(link["url"])
                self.assertEqual(parsed.scheme, "https")
                self.assertIn(parsed.netloc, ("www.sec.gov", "investors.broadcom.com"))

    def test_published_payload_roster_and_shell(self) -> None:
        published = js_payload(ROOT / "data" / "avgo.js", "window.DASH")
        self.assertEqual(published, self.payload)
        roster = js_payload(ROOT / "data" / "roster.js", "window.ROSTER")
        self.assertEqual(roster, roster_payload(build_all()))
        entry = next(item for item in roster["items"] if item["slug"] == "avgo")
        self.assertEqual(entry["latest_label"], self.payload["latest"]["disclosed_period_label"])
        self.assertEqual(entry["release_date"], self.payload["latest"]["release_date"])
        self.assertEqual(entry["group"], "semiconductor_ai")
        self.assertIn(entry["group"], {group["key"] for group in roster["groups"]})

    def test_home_page_carries_the_new_company(self) -> None:
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="avgo/"', home)
        self.assertIn("Broadcom", home)
        cards = home.count('class="hcard"')
        self.assertEqual(cards, len(ENTRIES))
        # The masthead used to read "N 家公司 · 8 季趋势". The window is being
        # pulled from eight quarters to forty-two, so the second half now states
        # progress instead of one number; the company count is still the first
        # number and is still pinned to the roster.
        masthead = re.search(r'<span class="meta">(\d+) 家公司 · ([^<]*)</span>', home)
        self.assertIsNotNone(masthead, "masthead count line changed shape")
        self.assertEqual(int(masthead.group(1)), len(ENTRIES))
        self.assertNotIn("8 季趋势", masthead.group(2),
                         "the eight-quarter claim is no longer true of this site")
        self.assertIn("42 季", masthead.group(2))

    def test_the_shell_links_the_payload_by_content_hash(self) -> None:
        """Every `?v=` in the committed shell must be that file's CURRENT digest.

        Checking the shape of the query string is not enough. A commit that
        updates `data/avgo.js` but leaves `avgo/index.html` out of its explicit
        path list publishes a shell that goes on stamping the previous payload's
        digest -- the bytes change, the URL does not, and a reader who already
        loaded the old payload keeps being served it from cache. This exact
        failure shipped on the SNPS page on 2026-08-29. The whole-suite run
        cannot see it, because tests run after `build/all.py` has regenerated
        the shell; asserting the digest by value is what catches it.
        """
        shell = (ROOT / "avgo" / "index.html").read_text(encoding="utf-8")
        self.assertIn("<title>AVGO Quarterly Results</title>", shell)
        sources = re.findall(r'<script src="\.\./([^"?]+)(?:\?v=([0-9a-f]+))?"', shell)
        self.assertEqual([name for name, _ in sources],
                         ["data/roster.js", "data/avgo.js", "assets/charts.js", "assets/page.js"])
        for name, digest in sources:
            with self.subTest(script=name):
                self.assertTrue(digest, f"{name} is served without a cache-busting version")
                expected = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()[: len(digest)]
                self.assertEqual(digest, expected, f"{name} carries a stale digest")

    def test_every_exhibit_matches_the_renderer_contract(self) -> None:
        """Charts that the renderer cannot draw fail silently in the browser.

        `assets/charts.js` dispatches on `kind` and looks `fmt` up in a table
        whose miss case falls back to one decimal place rather than raising, and
        it zips series values against `xlabels` positionally. So an unknown kind
        draws nothing, an unknown format quietly loses precision, and a series
        one element short shifts every point after the gap -- three failures that
        a passing build and a green suite would not otherwise notice.
        """
        js = (ROOT / "assets" / "charts.js").read_text(encoding="utf-8")
        kinds = set(re.findall(r"kind ?=== ?'([a-z_]+)'", js))
        formats = set(re.findall(r"^\s{4}([a-z0-9]+):\s*function", js, re.M))
        self.assertIn("grouped_bars", kinds)
        self.assertIn("pct1", formats)
        for exhibit in self.exhibits:
            with self.subTest(exhibit=exhibit["n"]):
                self.assertIn(exhibit["kind"], kinds)
                for key in ("fmt", "yfmt", "label_fmt"):
                    if key in exhibit:
                        self.assertIn(exhibit[key], formats)
                width = len(exhibit.get("xlabels", []))
                self.assertGreater(width, 0)
                if "values" in exhibit:
                    self.assertEqual(len(exhibit["values"]), width)
                for series in exhibit.get("groups", []) + exhibit.get("series", []):
                    self.assertEqual(len(series["values"]), width, series["name"])
                    self.assertTrue(any(v is not None for v in series["values"]),
                                    f"{series['name']} is entirely empty")
                for key in ("lo", "hi", "actual"):
                    if key in exhibit:
                        self.assertEqual(len(exhibit[key]), width)
                if exhibit.get("yoy"):
                    self.assertEqual(len(exhibit["yoy"]["values"]), width)

    def test_payload_carries_no_local_paths_or_private_material(self) -> None:
        blob = json.dumps(self.payload, ensure_ascii=False)
        for banned in ("/Users/", "OneDrive", "Obsidian", ".pptx", ".pdf", "transcript.pdf"):
            with self.subTest(term=banned):
                self.assertNotIn(banned, blob)


class AvgoChecksTest(unittest.TestCase):
    """The page's quarter against `_checks`, keyed separately from the release.

    Same contract as the other migrated pages: the builder never reads
    `_checks` (asserted in `test_data_only_roll`), a roll re-keys it from the
    new release, and nothing in this class changes with the quarter. Where the
    release prints a figure the page also computes -- free cash flow and its
    share of revenue, the semiconductor share, year-on-year growth -- the page's
    rounding must land on the printed number.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "avgo.json").read_text(encoding="utf-8"))
        cls.checks = cls.source["_checks"]
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]

    def exhibit(self, prefix: str) -> dict:
        return next(ex for ex in self.exhibits if ex["title"].startswith(prefix))

    def test_the_page_names_the_checked_quarter_both_ways(self) -> None:
        checks = self.checks
        self.assertIn(checks["period"], self.payload["title"])
        self.assertIn(f"本页 {checks['period']} 即公司所称 {checks['fiscal_label']}",
                      self.payload["subtitle"])
        self.assertIn(f"截至 {checks['period_end']} · 发布 {checks['release_date']}",
                      self.payload["subtitle"])
        self.assertEqual(self.source["fiscal_labels"][-1], checks["fiscal_label"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        checks, source = self.checks, self.source
        fin, seg = source["financials_usd_m"], source["segments_usd_m"]
        cash, capital = source["cash_flow_usd_m"], source["capital_allocation_usd_m"]
        working = source["working_capital_usd_m"]
        self.assertEqual(fin["revenue"][-1], checks["revenue_usd_m"])
        self.assertEqual(round((fin["revenue"][-1] / fin["revenue"][-5] - 1) * 100),
                         checks["revenue_yoy_pct"])
        self.assertEqual(fin["gaap_operating_income"][-1], checks["gaap_operating_income_usd_m"])
        self.assertEqual(fin["non_gaap_operating_income"][-1],
                         checks["non_gaap_operating_income_usd_m"])
        self.assertEqual(seg["semiconductor_revenue"][-1], checks["semiconductor_revenue_usd_m"])
        self.assertEqual(round(seg["semiconductor_revenue"][-1] / fin["revenue"][-1] * 100),
                         checks["semiconductor_share_pct"])
        self.assertEqual(seg["infrastructure_software_revenue"][-1],
                         checks["infrastructure_software_revenue_usd_m"])
        self.assertEqual(cash["operating_cash_flow"][-1], checks["operating_cash_flow_usd_m"])
        self.assertEqual(cash["capital_expenditures"][-1], checks["capital_expenditures_usd_m"])
        fcf = cash["operating_cash_flow"][-1] - cash["capital_expenditures"][-1]
        self.assertEqual(fcf, checks["free_cash_flow_usd_m"])
        self.assertEqual(round(fcf / fin["revenue"][-1] * 100), checks["free_cash_flow_pct_of_revenue"])
        self.assertEqual(capital["share_repurchases"][-1], checks["share_repurchases_usd_m"])
        self.assertEqual(capital["common_dividends"][-1], checks["dividends_paid_usd_m"])
        self.assertEqual(capital["cash_and_equivalents"][-1], checks["cash_and_equivalents_usd_m"])
        self.assertEqual(capital["total_debt"][-1],
                         checks["short_term_debt_usd_m"] + checks["long_term_debt_usd_m"])
        self.assertEqual(working["inventory"][-1], checks["inventory_usd_m"])
        self.assertEqual(working["accounts_receivable"][-1], checks["accounts_receivable_usd_m"])
        ai = source["ai_semiconductor_disclosures"]
        self.assertEqual(ai["actual_usd_bn"][ai["periods"].index(checks["period"])],
                         checks["ai_semiconductor_revenue_usd_bn"])

    def test_the_outlook_is_the_checked_outlook(self) -> None:
        outlook = self.checks["next_quarter"]
        guidance = self.source["guidance"]["next_quarter"]
        self.assertEqual(guidance["released"], self.checks["release_date"])
        self.assertEqual(guidance["fiscal_label"], outlook["fiscal_label"])
        self.assertEqual(guidance["period_end"], outlook["period_end"])
        self.assertEqual(guidance["revenue_usd_bn"], outlook["revenue_usd_bn"])
        self.assertEqual(guidance["non_gaap_operating_margin_pct"],
                         outlook["non_gaap_operating_margin_pct"])
        self.assertEqual(guidance["ai_semiconductor_revenue_usd_bn"],
                         outlook["ai_semiconductor_revenue_usd_bn"])
        record = self.source["quarterly_guidance_history"]
        self.assertEqual(record["period_ends"][-1], outlook["period_end"])
        self.assertEqual(record["guide_revenue_usd_m"][-1], outlook["revenue_usd_bn"] * 1000)
        margin = self.source["non_gaap_operating_margin_guidance"]
        self.assertEqual(margin["guide_pct"][margin["period_ends"].index(outlook["period_end"])],
                         outlook["non_gaap_operating_margin_pct"])
        self.assertEqual(self.source["ai_semiconductor_disclosures"]["next_quarter_guide_usd_bn"],
                         outlook["ai_semiconductor_revenue_usd_bn"])

    def test_the_series_carries_the_checked_10q(self) -> None:
        """The 10-Q the report was written without, read twice: into the series, and into `_checks`.

        The report's section 0 and its data-gap list were written on 2026-09-03,
        before the FY2026 Q3 10-Q was filed on 2026-09-10; the page said 「本季
        10-Q 尚未申报」 in four places. The filing is on EDGAR, so the page now
        carries its figures, and they must be the ones the filing prints.
        """
        tq = self.checks["ten_q"]
        source = self.source
        self.assertEqual(tq["period_end"], source["period_ends"][-1])
        reports = {row["period_end"]: row for row in source["periodic_reports_filed"]["reports"]}
        self.assertEqual(reports[tq["period_end"]]["filed"], tq["filed"])
        self.assertEqual(reports[tq["period_end"]]["accession"], tq["accession"])
        seg = source["segments_usd_m"]
        self.assertEqual(seg["semiconductor_operating_income"][-1], tq["semiconductor_operating_income_usd_m"])
        self.assertEqual(seg["infrastructure_software_operating_income"][-1],
                         tq["infrastructure_software_operating_income_usd_m"])
        self.assertEqual(seg["semiconductor_cost_of_revenue"][-1], tq["semiconductor_cost_of_revenue_usd_m"])
        self.assertEqual(seg["infrastructure_software_cost_of_revenue"][-1],
                         tq["infrastructure_software_cost_of_revenue_usd_m"])
        pc = source["purchase_commitments_usd_m"]
        self.assertEqual(pc["total"][-1], tq["purchase_commitments_total_usd_m"])
        self.assertEqual(pc["due_within_one_year"][-1], tq["purchase_commitments_fy2027_usd_m"])
        self.assertEqual(pc["due_in_year_two"][-1], tq["purchase_commitments_fy2028_usd_m"])
        notes = source["ten_q_notes"]["by_period_end"][tq["period_end"]]
        self.assertEqual(notes["backstop_max_usd_m"], tq["backstop_maximum_usd_m"])
        self.assertEqual(notes["accession"], tq["accession"])
        # The report's own diagnosis still says its answers were held up by a
        # 10-Q 「当时尚未申报」 -- true of the report. What must be gone is the
        # page asserting that this quarter's filing is still missing.
        published = json.dumps(self.payload, ensure_ascii=False)
        self.assertNotRegex(published, r"本季 10-[QK][^。]{0,12}尚未申报")

    def test_section_one_opens_with_the_reports_follow_ups(self) -> None:
        """Last quarter's questions, judged as this quarter's report judged them.

        The counts come from `_checks["note"]`, keyed from the report's section 0
        separately from the series block the builder reads: the page used to
        settle six questions of its own here, not the report's five.
        """
        note = self.checks["note"]["followup_closure"]
        settled = self.payload["sections"][0]["exhibits"]
        closure = settled[0]
        self.assertTrue(closure["title"].startswith(f"上季 {note['questions']} 条待验证问题"))
        self.assertEqual(dict(zip(closure["xlabels"], closure["values"])), note["counts"])
        self.assertEqual(sum(closure["values"]), note["judgements"])
        self.assertIn(f"{note['judgements']} 项判定", closure["title"])
        table = next(t for t in self.payload["tables"] if "条待验证问题" in t["title"])
        self.assertEqual(len(table["rows"]), note["questions"])

    def test_section_one_settles_every_threshold_of_the_prior_section_8(self) -> None:
        """Every numeric threshold of the previous report's section 8, and only those.

        The page's five 「上季跟踪线」 were thresholds this page had set itself
        (US$16,000M AI, 67% margin, US$8,900M software, US$2,000M buyback, 68%
        EBITDA). The report's were different lines on partly different metrics.
        Each entry must be one the report wrote, at the value and on the side it
        wrote it, and the report's rows that cannot be settled must be named.
        """
        note = self.checks["note"]
        expected = note["prior_thresholds"]
        block = self.source["prior_kpi_settlement"]
        entries = block["quantified"]
        self.assertEqual(len(entries), len(expected))
        for entry, want in zip(entries, expected):
            with self.subTest(metric=entry["metric"]):
                self.assertTrue(entry["metric"].startswith(want["metric"]))
                self.assertEqual(entry["threshold"], want["threshold"])
                self.assertEqual(entry["op"] in ("≥", ">"), want["direction"] == "up")
                # the chart's favourable side: a gate is favourable when it fires,
                # a floor when it does not
                fires_up = want["direction"] == "up"
                favourable_up = fires_up if entry["kind"] == "gate" else not fires_up
                self.assertEqual(entry["direction"], "up" if favourable_up else "down")
        chart = self.payload["sections"][0]["exhibits"][1]
        self.assertTrue(chart["title"].startswith(f"上季 {len(expected)} 条量化阈值"))
        self.assertEqual(chart["kind"], "diverging_bars")
        self.assertEqual(chart["xlabels"], [e["metric"] for e in entries])
        self.assertEqual(len(block["unsettled"]), len(note["prior_unquantified"]))
        for item in block["unsettled"]:
            self.assertIn(item["metric"], chart["note"])

    def test_the_prior_settlement_reads_the_filed_figures(self) -> None:
        """The readings in the settlement table are this quarter's filed numbers."""
        table = next(t for t in self.payload["tables"] if "条量化阈值的结算" in t["title"])
        by_metric = {row[1]: row for row in table["rows"]}
        checks = self.checks
        self.assertEqual(by_metric["软件收入（警示线）"][4],
                         f"US${checks['infrastructure_software_revenue_usd_m']:,}M")
        self.assertEqual(by_metric["季度回购（辅助信号）"][4], f"US${checks['share_repurchases_usd_m']:,}M")
        self.assertEqual(by_metric["Q3 AI 半导体收入（加仓线）"][4],
                         f"US${checks['ai_semiconductor_revenue_usd_bn'] * 1000:,.0f}M")
        self.assertEqual(by_metric["Q4 AI 收入（减仓线）"][4],
                         f"US${checks['next_quarter']['ai_semiconductor_revenue_usd_bn'] * 1000:,.0f}M")

    def test_the_page_prints_the_checked_figures(self) -> None:
        checks, outlook = self.checks, self.checks["next_quarter"]
        self.assertIn(f"收入 US${checks['revenue_usd_m']:,}M", self.payload["headline"])
        self.assertEqual(headline_metrics(self.source), [
            f"Revenue ${checks['revenue_usd_m'] / 1000:.2f}B",
            f"AI 半导体 ${checks['ai_semiconductor_revenue_usd_bn']:.1f}B",
            f"non-GAAP 营业利润率 "
            f"{checks['non_gaap_operating_income_usd_m'] / checks['revenue_usd_m'] * 100:.1f}%",
        ])
        rows = {row[0]: row for row in self.payload["guidance"]["rows"]}
        self.assertEqual(rows["收入"][1], f"约 US${outlook['revenue_usd_bn']:.1f}B")
        self.assertEqual(rows["non-GAAP 营业利润率"][1],
                         f"约为收入的 {outlook['non_gaap_operating_margin_pct']}%")
        self.assertEqual(rows["AI 半导体收入"][1], f"US${outlook['ai_semiconductor_revenue_usd_bn']:.1f}B")
        self.assertIn(f"US${outlook['ai_semiconductor_revenue_usd_bn']:.1f}B",
                      self.exhibit("AI 半导体收入：")["title"])
        revenue = self.exhibit("收入 US$")["title"]
        self.assertIn(f"半导体占比", revenue)
        self.assertIn(f" {checks['semiconductor_share_pct']}%", revenue)
        conversion = self.exhibit("自由现金流 US$")["title"]
        self.assertIn(f"自由现金流 US${checks['free_cash_flow_usd_m']:,}M", conversion)
        self.assertIn(f"占收入 {checks['free_cash_flow_pct_of_revenue']}%", conversion)
        self.assertIn(f"本季回购 US${checks['share_repurchases_usd_m']:,}M、"
                      f"分红 US${checks['dividends_paid_usd_m']:,}M",
                      self.exhibit("股东回报")["title"])
        debt = checks["short_term_debt_usd_m"] + checks["long_term_debt_usd_m"]
        self.assertIn(f"总债务 US${debt:,}M", next(ex["title"] for ex in self.exhibits
                                                  if "总债务 US$" in ex["title"]))
        working = self.exhibit("营运资本")["title"]
        self.assertIn(f"存货 US${checks['inventory_usd_m']:,}M", working)
        self.assertIn(f"应收 US${checks['accounts_receivable_usd_m']:,}M", working)


if __name__ == "__main__":
    unittest.main()
