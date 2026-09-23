"""HKEX page: the identities that license half of what it publishes.

Half of this page's quarters are this page's own arithmetic. HKEX's first- and
third-quarter announcements each carry a three-month column in the condensed
income statement; the interim announcement carries six months and the annual
twelve. So every even quarter here is `H1 - Q1` or `FY - 9M`. The company does
print those quarters too -- in the annual report's quarterly table since
FY2016, and from 2022 in a summary box in the interim announcement -- only
later; the page's first draft said they were never printed, and that was the
error the page was rewritten to fix.

Rolling a quarter appends to these records; the tests below pin what was true
through 2026Q2 (a roll only adds to that history) and hold the rest as
invariants, so a data-only roll does not have to edit this file.

Three separate things could make it wrong without anything else noticing, and
each has a test below.

**The subtraction could span two bases.** The two legs come from documents
published six months apart, so a reclassification in between would be absorbed
silently -- and a sum identity cannot see it, because a reclassification moves
money *between* lines and both bases still add up. What can see it is that
every period is printed twice: once as the current period and once, a year
later, as the comparative column of the same kind of announcement. All 1,091
paired readings are compared, and the two that differ are pinned by name.

**The parse could have taken the wrong column.** The Q3 announcement prints
four columns -- nine months current, nine months prior, three months current,
three months prior -- and picking the wrong one produces a number that is the
right order of magnitude and wrong. `H1 + Q3 == 9M` catches that: the three
components come from two different documents and are not derived from each
other, so the identity is not circular the way `Q1 + Q2 == H1` would be.

**The subtraction could simply be the wrong idea.** From 2022 the company began
printing the even quarters as summary totals, with comparatives reaching back
to 2021Q2. Eleven derived quarters therefore have a company-printed figure to
be checked against, and this file recounts that check rather than trusting the
number quoted in the page's own headline.

One further thing this file pins is a *negative*: the market statistics are
averages per trading day, so the subtraction that produces the even quarters
for money is not valid for volume. The KPI block must therefore never extend
below the quarter the company started printing, and no KPI value may be marked
derived. A future edit that "fills the gap" would produce a page that looks
complete and is fabricated.
"""

from __future__ import annotations

import copy
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import hkex  # noqa: E402
from build.all import ENTRIES, GROUPS, build_all, roster_payload  # noqa: E402
from build.board import cn_count, display_period, headroom, stamped_block  # noqa: E402

FEE_LINES = ("trading_fees", "clearing_fees", "listing_fees", "depository_fees",
             "market_data_fees", "other_revenue")
BOX_LINES = ("revenue_and_other_income", "ebitda", "profit_attributable")


def js_payload(path: Path, marker: str) -> dict:
    text = path.read_text(encoding="utf-8")
    return json.loads(text.split(f"{marker} = ", 1)[1].rstrip().rstrip(";"))


def quarter_step(earlier: str, later: str) -> bool:
    y1, q1 = int(earlier[:4]), int(earlier[5])
    y2, q2 = int(later[:4]), int(later[5])
    return (y2, q2) == ((y1 + 1, 1) if q1 == 4 else (y1, q1 + 1))


# The record this file's exact pins were written against. A roll appends to it;
# nothing at or before this quarter may change.
PINNED_THROUGH = "2026Q2"

DOC_KIND = {"1": "Q1", "2": "H1", "3": "Q3", "4": "FY"}


def published_text(payload: dict) -> str:
    return json.dumps({key: payload[key] for key in
                       ("title", "subtitle", "headline", "brief", "sections", "notes", "tables")},
                      ensure_ascii=False)


class HkexSeriesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(hkex.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = hkex.build_payload(cls.staging)

    # ── the window and what each quarter's number is made of ────────────────
    def test_the_window_runs_from_2016q1_and_is_contiguous(self) -> None:
        quarters = self.staging["quarters"]
        self.assertEqual(quarters[0], "2016Q1")
        self.assertEqual(display_period(quarters[-1]),
                         self.staging["latest"]["disclosed_period_label"])
        self.assertIn(PINNED_THROUGH, quarters)
        for earlier, later in zip(quarters, quarters[1:]):
            self.assertTrue(quarter_step(earlier, later), f"{earlier} -> {later}")

    def test_odd_quarters_are_printed_and_even_quarters_are_derived(self) -> None:
        """The basis is a fact about the announcement calendar, not a judgement.

        Q1 and Q3 announcements each carry a three-month column; the interim and
        annual announcements do not. If a future quarter arrives marked the
        other way round, either the company changed what it prints or the
        pipeline mislabelled it, and both need a person.
        """
        for quarter, basis in zip(self.staging["quarters"], self.staging["quarter_basis"]):
            expected = "printed" if quarter[-1] in "13" else "derived"
            self.assertEqual(basis, expected, quarter)

    def test_every_quarter_names_the_documents_it_came_from(self) -> None:
        roster = {a["doc"] for a in self.staging["announcements"]}
        for quarter in self.staging["quarters"]:
            sources = self.staging["quarter_sources"][quarter]
            index = self.staging["quarters"].index(quarter)
            expected = 1 if self.staging["quarter_basis"][index] == "printed" else 2
            self.assertEqual(len(sources), expected, quarter)
            for doc in sources:
                self.assertIn(doc, roster, quarter)

    def test_the_announcement_roster_covers_the_window_exactly(self) -> None:
        """One document per quarter -- no gap, no document counted twice.

        Written as a set identity rather than a count, because the failure this
        is for is a document quietly standing in for its neighbour, which a
        count cannot see.
        """
        docs = [a["doc"] for a in self.staging["announcements"]]
        self.assertEqual(len(docs), len(set(docs)))
        expected = {f"{quarter[:4]}_{DOC_KIND[quarter[5]]}" for quarter in self.staging["quarters"]}
        self.assertEqual(set(docs), expected)
        for entry in self.staging["announcements"]:
            self.assertTrue(entry["url"].startswith("https://"), entry["doc"])
            self.assertRegex(entry["release_date"], r"^20\d\d-\d\d-\d\d$")

    # ── the identities that license the subtraction ─────────────────────────
    def test_the_printed_third_quarter_closes_the_nine_months(self) -> None:
        """`H1 + Q3 == 9M`, and none of the three is derived from another.

        This is the check the trivially-true one is not: `Q1 + Q2 == H1` holds
        by construction because Q2 was defined as the difference. Here the half,
        the printed three-month column and the nine months come from two
        different announcements and are read independently, so a column taken
        from the wrong place in the four-column Q3 statement shows up.
        """
        readings = self.staging["period_readings"]
        checked = 0
        for year in range(2016, 2026):
            half, quarter, ytd = f"{year}H1", f"{year}Q3", f"{year}9M"
            if not all(tag in readings for tag in (half, quarter, ytd)):
                continue
            for field, value in readings[ytd]["vals"].items():
                a = readings[half]["vals"][field]
                b = readings[quarter]["vals"][field]
                if None in (value, a, b):
                    continue
                self.assertAlmostEqual(a + b, value, delta=0.5, msg=f"{year} {field}")
                checked += 1
        self.assertGreaterEqual(checked, 100)

    def test_the_four_quarters_of_a_year_sum_to_the_printed_year(self) -> None:
        readings = self.staging["period_readings"]
        quarters = self.staging["quarters"]
        checked = 0
        for year in range(2016, 2026):
            if f"{year}FY" not in readings:
                continue
            indices = [quarters.index(f"{year}Q{n}") for n in (1, 2, 3, 4)]
            for field, total in readings[f"{year}FY"]["vals"].items():
                parts = [self.staging["quarterly"][field][i] for i in indices
                         if field in self.staging["quarterly"]]
                if total is None or not parts or any(p is None for p in parts):
                    continue
                self.assertAlmostEqual(sum(parts), total, delta=0.5, msg=f"{year} {field}")
                checked += 1
        self.assertGreaterEqual(checked, 100)

    def test_the_six_fee_lines_sum_to_revenue_in_every_quarter(self) -> None:
        q = self.staging["quarterly"]
        for index, quarter in enumerate(self.staging["quarters"]):
            parts = [q[field][index] for field in FEE_LINES]
            self.assertNotIn(None, parts, quarter)
            self.assertAlmostEqual(sum(parts), q["revenue"][index], delta=0.5, msg=quarter)

    def test_the_investment_residual_goes_negative_in_exactly_one_quarter(self) -> None:
        """2020Q1 is a net investment LOSS, and that decides a chart kind.

        `revenue and other income` minus the six fee lines is what the page
        calls 投资及其他收益, and in 2020Q1 it is −HK$46M. `stacked_dual` scales
        its right axis from zero regardless of the data, so a share of −1.15%
        would be drawn outside the plot area while the legend went on naming it
        -- the same defect that shipped on CME Ex4 and ibkr Ex8, in the other
        direction. Pinned here so a future edit that moves this series onto a
        stacked right axis has to argue with a test.
        """
        q = self.staging["quarterly"]
        residual = [roi - rev for roi, rev
                    in zip(q["revenue_and_other_income"], q["revenue"])]
        negative = [quarter for quarter, value
                    in zip(self.staging["quarters"], residual)
                    if value < 0 and quarter <= PINNED_THROUGH]
        self.assertEqual(negative, ["2020Q1"])
        self.assertLess(min(residual), -40.0)

    # ── the company's own reading of a derived quarter ──────────────────────
    def test_every_printed_box_figure_matches_this_page_exactly(self) -> None:
        check = hkex.box_check(self.staging)
        self.assertEqual(check["mismatches"], 0)
        self.assertEqual(check["covered"][0], "2021Q2")
        # Through 2026Q2: 33 comparisons on the eleven derived quarters -- the
        # ones that are evidence for the subtraction -- and 72 including the
        # printed quarters, where the box only cross-checks the statement parse.
        history = copy.deepcopy(self.staging)
        history["printed_box"] = {q: box for q, box in history["printed_box"].items()
                                  if q <= PINNED_THROUGH}
        pinned = hkex.box_check(history)
        self.assertEqual(pinned["derived_comparisons"], 33)
        self.assertEqual(pinned["comparisons"], 72)
        self.assertEqual(len(pinned["covered"]), 11)

    def test_the_only_cells_resting_on_arithmetic_alone_are_the_fee_lines(self) -> None:
        """The page's first draft asserted ten quarters had no counterpart.

        They do -- the annual report's quarterly table covers every year from
        FY2016. What genuinely has no counterpart is narrower: the revenue
        decomposition of an even quarter before FY2022 added the fee lines to
        that table, plus the quarter just reported, which waits for the next
        annual announcement. This test replaces one that asserted the wrong
        set, and would have gone on passing, because `box_check` still reports
        the same thing about a question that is no longer the page's claim.
        """
        missing = hkex.never_printed(self.staging, hkex.FEE_LINES)
        self.assertEqual([q for q in missing if q < "2022"],
                         ["2016Q2", "2016Q4", "2017Q2", "2017Q4",
                          "2018Q2", "2018Q4", "2019Q2", "2019Q4",
                          "2020Q2", "2020Q4", "2021Q2", "2021Q4"])
        # from FY2022 an even quarter waits only for the annual table of its year
        tables = self.staging["ar_quarter_tables"]["by_year"]
        self.assertEqual([q for q in missing if q >= "2022"],
                         [q for q in self.staging["quarters"]
                          if q >= "2022" and q[5] in "24" and q[:4] not in tables])
        # every headline line, by contrast, has been printed for every quarter
        self.assertEqual(hkex.never_printed(self.staging, hkex.HEADLINE_LINES), [])

    def test_every_derived_cell_reproduces_the_company_printed_one(self) -> None:
        """The page's central evidence, and it is arithmetic against a document.

        Each even quarter here is `H1 - Q1` or `FY - 9M`. Each one is also
        printed, as a discrete column, in the annual report's `Analysis of
        Results by Quarter`. The two are obtained from different documents by
        different routes, so agreement is evidence rather than a tautology --
        unlike `Q1 + Q2 == H1`, which this page's arithmetic makes true by
        construction and which therefore proves nothing.
        """
        recon = hkex.reconcile_against_printed(self.staging)
        self.assertEqual(recon["mismatches"], 0, recon["bad"][:5])
        # 296 and 148 through FY2025; a new annual table only adds to them
        self.assertGreaterEqual(recon["compared"], 296)
        self.assertGreaterEqual(recon["derived_compared"], 148)
        years = recon["years"]
        self.assertEqual(years, [str(y) for y in range(2016, int(years[-1]) + 1)])
        # every even quarter has a counterpart except those whose year's table is not out
        self.assertEqual(recon["uncovered_even"],
                         [q for q in self.staging["quarters"]
                          if q[5] in "24" and q[:4] not in years])

    def test_the_disclosure_lag_has_the_two_clocks_the_page_describes(self) -> None:
        """Odd and even quarters are public on visibly different schedules."""
        quarters = [q for q in self.staging["quarters"] if q <= PINNED_THROUGH]
        odd, even = [], []
        for quarter in quarters:
            lag = hkex.disclosure_lag(self.staging, quarter, hkex.HEADLINE_LINES)
            self.assertIsNotNone(lag, quarter)   # every quarter has been printed
            (odd if quarter[-1] in "13" else even).append(lag)
        self.assertEqual(len(odd), 21)
        self.assertEqual(len(even), 21)
        self.assertEqual((min(odd), max(odd)), (19, 42))
        self.assertEqual((min(even), max(even)), (47, 263))
        # the two clocks never overlap: the slowest odd quarter still beats the
        # fastest even one, which is the whole reason the page draws this
        self.assertLess(max(odd), min(even))

    def test_the_second_quarter_is_the_one_that_waited(self) -> None:
        """It is Q2, not "even quarters", and the box ended it in one step.

        The looser claim -- that both even quarters were slow -- is false and
        this test exists because the page made it: a fourth quarter has always
        arrived with the annual results announcement, 54 to 79 days out. Only
        the second quarter waited for the annual report, and it waited about
        eight and a half months, six years running, until the summary box
        appeared in the 2022 interim announcement.
        """
        lags = {n: [] for n in (1, 2, 3, 4)}
        for quarter in [q for q in self.staging["quarters"] if q <= PINNED_THROUGH]:
            lags[int(quarter[5])].append(
                (quarter, hkex.disclosure_lag(self.staging, quarter,
                                              hkex.HEADLINE_LINES)))
        q4 = [v for _, v in lags[4]]
        self.assertEqual((min(q4), max(q4)), (54, 79))     # never the outlier

        before = [v for q, v in lags[2] if q < "2022"]
        after = [v for q, v in lags[2] if q >= "2022"]
        self.assertEqual(len(before), 6)
        self.assertEqual((min(before), max(before)), (257, 263))
        self.assertEqual((min(after), max(after)), (47, 52))
        # the step is a cliff, not a trend: no Q2 ever landed between them
        self.assertTrue(all(v < 60 or v > 250 for _, v in lags[2]))

    def test_the_annual_series_carries_only_the_one_basis_it_verified(self) -> None:
        """The derivatives volumes are absent by decision, and it is recorded.

        They changed basis three times inside this window -- chargeable at
        FY2018 with 2017 restated, units at FY2019, calculation at FY2021 with
        every comparative restated. The page shipped them spliced into one line
        once, in raw contracts against an axis labelled thousands; the fix is
        not to convert the cell but to not publish a series whose own issuer
        has restated it under three definitions.
        """
        annual = self.staging["kpi_annual"]
        self.assertEqual(sorted(annual), ["adt_headline"])
        for name, values in annual.items():
            self.assertEqual(len(values), len(self.staging["kpi_years"]), name)
            self.assertTrue(all(v is not None for v in values), name)
            self.assertTrue(all(0 < v < 1000 for v in values), name)
        basis = self.staging["kpi_annual_basis"]
        self.assertIn("derivatives_not_published", basis)
        for marker in ("FY2018", "FY2019", "FY2021", "624,480", "601,067"):
            self.assertIn(marker, basis["derivatives_not_published"], marker)

    def test_the_restatement_census_is_the_one_the_page_describes(self) -> None:
        """Every period read twice, a year apart; the two that differ are named.

        This is the check a sum identity structurally cannot do. The 2020
        reclassification moved HK$34M out of sundry income into a newly created
        donation-income line, and revenue and other income did not move -- so
        every total still added up on both sides of it.
        """
        census = self.staging["restatement_census"]
        self.assertGreaterEqual(self.staging["restatement_paired_readings"], 1091)
        self.assertEqual(len(census), 2)
        self.assertEqual({row["field"] for row in census}, {"sundry_income"})
        self.assertEqual({row["period"] for row in census}, {"2020Q3", "20209M"})
        for row in census:
            self.assertEqual(row["again"] - row["first"], -34.0, row["period"])
            self.assertEqual(row["first_doc"], "2020_Q3")
            self.assertEqual(row["again_doc"], "2021_Q3")

    def test_the_derived_expense_total_reconciles_to_the_printed_one(self) -> None:
        """`ROI - EBITDA` is expenses PLUS transaction-related expenses.

        The page plots the difference because it is the one definition that has
        not moved in ten years, but it is HK$67M larger than the operating
        expense line the company prints, and a chart captioned 营业开支 with
        that number on it contradicts the company's own release. Pinned as an
        identity so the caption cannot drift back.
        """
        q = self.staging["quarterly"]
        checked = 0
        for index, quarter in enumerate(self.staging["quarters"]):
            box = self.staging["printed_box"].get(quarter, {})
            printed = box.get("operating_expenses")
            txn = q["transaction_expenses"][index]
            if printed is None or txn is None:
                continue
            derived = q["revenue_and_other_income"][index] - q["ebitda"][index]
            self.assertAlmostEqual(derived + txn, printed, delta=0.5, msg=quarter)
            checked += 1
        self.assertGreaterEqual(checked, 20)

    # ── the half-yearly rebate ──────────────────────────────────────────────
    def test_gross_investment_income_less_the_rebate_is_the_net(self) -> None:
        block = self.staging["half_investment"]
        for index, half in enumerate(self.staging["halves"]):
            gross, rebate, net = (block["gross"][index], block["rebates"][index],
                                  block["net"][index])
            self.assertIsNotNone(gross, half)
            self.assertLessEqual(rebate, 0, half)
            self.assertAlmostEqual(gross + rebate, net, delta=0.5, msg=half)

    def test_the_halves_alternate_printed_and_derived(self) -> None:
        halves, basis = self.staging["halves"], self.staging["half_basis"]
        self.assertEqual(halves[0], "2016H1")
        last = self.staging["quarters"][-1]
        # the last half is the one the latest reported quarter completes
        expected_last = (f"{last[:4]}H1" if last[5] in "23" else
                         (f"{last[:4]}H2" if last[5] == "4" else f"{int(last[:4]) - 1}H2"))
        self.assertEqual(halves[-1], expected_last)
        self.assertEqual(len(halves), 2 * (int(expected_last[:4]) - 2016) + int(expected_last[5]))
        for half, kind in zip(halves, basis):
            self.assertEqual(kind, "printed" if half.endswith("H1") else "derived", half)

    def test_the_rebate_share_spans_the_range_the_page_quotes(self) -> None:
        block = self.staging["half_investment"]
        share = [-r / g * 100 for r, g in zip(block["rebates"], block["gross"])]
        self.assertLess(share[0], 15.0)
        self.assertGreater(max(share), 65.0)
        self.assertGreater(share[self.staging["halves"].index("2026H1")], 50.0)

    # ── the volume block, and the subtraction it must never use ─────────────
    def test_the_kpi_window_starts_where_the_company_started_printing(self) -> None:
        kq = self.staging["kpi_quarters"]
        self.assertEqual(kq[0], "2021Q1")
        self.assertEqual(kq[-1], self.staging["quarters"][-1])
        for earlier, later in zip(kq, kq[1:]):
            self.assertTrue(quarter_step(earlier, later), f"{earlier} -> {later}")
        self.assertEqual(kq, self.staging["quarters"][-len(kq):])

    def test_no_market_statistic_is_ever_derived(self) -> None:
        """An average per trading day cannot be subtracted, so none of these is.

        The failure this is for is a future edit extending the volume series
        backwards with `H1 - Q1`, which would produce a full-looking chart of
        numbers that mean nothing.
        """
        kpi = self.staging["kpi_quarterly"]
        self.assertEqual(len(kpi), 9)
        for name, values in kpi.items():
            self.assertEqual(len(values), len(self.staging["kpi_quarters"]), name)
            self.assertNotIn(None, values, name)
        self.assertNotIn("kpi_basis", self.staging)

    def test_southbound_is_inside_the_headline_turnover(self) -> None:
        """Headline ADT includes southbound; equity plus warrants must not exceed it."""
        kpi = self.staging["kpi_quarterly"]
        for index, quarter in enumerate(self.staging["kpi_quarters"]):
            self.assertLessEqual(kpi["adt_equity"][index] + kpi["adt_dw_cbbc"][index],
                                 kpi["adt_headline"][index] + 0.05, quarter)

    def test_the_annual_volume_series_states_its_own_floor(self) -> None:
        """2016 is readable; the first draft dropped it and blamed the parser.

        The claim in the note was that the FY2016 and FY2017 announcements put
        the market statistics in a layout whose columns could not be placed.
        FY2016 prints `ADT traded on the Stock Exchange ($bn)  66.9  105.6`,
        which is the same shape as every later year, so the series starts there.
        """
        years = self.staging["kpi_years"]
        self.assertEqual(years[0], "2016")
        self.assertEqual(years, [str(y) for y in range(2016, int(years[-1]) + 1)])
        self.assertLessEqual(int(years[-1]), int(self.staging["quarters"][-1][:4]))
        self.assertEqual(self.staging["kpi_annual"]["adt_headline"][0], 66.9)
        for name, values in self.staging["kpi_annual"].items():
            self.assertEqual(len(values), len(years), name)

    # ── what the company does not say ───────────────────────────────────────
    def test_the_page_scores_no_company_guidance_because_there_is_none(self) -> None:
        census = self.staging["guidance_census"]
        # a census that has not read the latest announcement must not be printed as current
        self.assertEqual(census["documents"], len(self.staging["announcements"]))
        self.assertEqual(self.staging["statement_identities"]["documents"],
                         len(self.staging["announcements"]))
        self.assertEqual(census["financial_guidance"], 0)
        self.assertGreater(census["forward_statements_with_a_number"], 0)
        self.assertIsNone(self.payload["guidance"])

    def test_the_thresholds_are_declared_local_not_company_figures(self) -> None:
        kpi = stamped_block(self.staging, "next_kpi", self.staging["latest"]["disclosed_period_label"])
        if not kpi:
            return
        excluded = kpi["excluded"]
        self.assertIn("本地研究阈值", excluded)
        for entry in kpi["quantified"]:
            self.assertIn(entry["direction"], ("up", "down"))
            self.assertIsInstance(entry["current"], (int, float))
            headroom(entry["direction"], entry["threshold"], entry["current"])

    def test_the_text_layer_census_is_a_measurement_not_a_warning(self) -> None:
        layer = self.staging["text_layer"]
        self.assertGreater(layer["figures_compared"], 500)
        self.assertGreater(layer["corrupted_by_glued_marker"], 0)
        self.assertLess(layer["corrupted_by_glued_marker"], layer["figures_compared"])


class HkexPayloadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(hkex.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = hkex.build_payload(cls.staging)
        cls.exhibits = [ex for section in cls.payload["sections"]
                        for ex in section["exhibits"]]

    def test_the_headline_calls_a_record_only_what_is_one(self) -> None:
        """Three figures led the headline as records; one was third of 42.

        Derived from what the sentence promises rather than from how it broke:
        any quarterly series the headline calls a 新高 must actually be at its
        maximum in the published series.
        """
        q = self.staging["quarterly"]
        headline = self.payload["headline"]
        margins = [e / r * 100 for e, r
                   in zip(q["ebitda"], q["revenue_and_other_income"])]

        # Key on structure, not on a word. An earlier version of this test
        # asserted `"不是" in headline`, which a mutant satisfied from an
        # unrelated clause ("本页的对象不是这个季度") while the headline went on
        # calling a third-place margin a record. What must be true is narrower:
        # the clause that carries the margin figure may not claim a record
        # unless the margin actually is one.
        RECORD = ("新高", "纪录", "最高", "史上")
        figure = f"{margins[-1]:.1f}%"
        self.assertIn(figure, headline)
        if margins[-1] != max(margins):
            # what the figure itself is said to be: the window immediately
            # after it. A whole-clause scan false-reds on the correct sentence
            # "最高的是 2021Q1 的 80.7%", which names the real holder rather
            # than claiming the record for this quarter.
            after = headline[headline.index(figure) + len(figure):][:12]
            for word in RECORD:
                self.assertNotIn(word, after,
                                 f"margin is #{sorted(margins, reverse=True).index(margins[-1]) + 1}"
                                 f" of {len(margins)} but is called {word}: ...{figure}{after}")
            # and the true holder must be named, so the reader is not left to
            # infer it -- a positive requirement a vague hedge cannot satisfy
            best = max(range(len(margins)), key=lambda i: margins[i])
            self.assertIn(self.staging["quarters"][best], headline)
            self.assertIn(f"{max(margins):.1f}%", headline)
        # and the two that genuinely are records must still be claimed as such
        for field in ("revenue_and_other_income", "profit_attributable"):
            series = [v for v in q[field] if v is not None]
            self.assertEqual(series[-1], max(series), field)
        self.assertTrue(any(w in headline for w in RECORD))

    def test_every_section_description_counts_its_own_exhibits(self) -> None:
        """A description that names a number of charts must name the right one."""
        digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                  "六": 6, "七": 7, "八": 8, "九": 9}
        checked = 0
        for section in self.payload["sections"]:
            text = section.get("description", "")
            # "张图" only ever counts charts; a bare "张" appears in ordinary
            # prose ("各印一张三个月的损益表") and keying on it makes this gate
            # go red on a correct page, which is how a gate gets bypassed.
            for word, value in digits.items():
                if f"{word}张图" in text:
                    checked += 1
                    self.assertEqual(value, len(section["exhibits"]),
                                     f"{section['title']}: {word}张图")
        self.assertGreaterEqual(checked, 1)

    def test_a_note_counting_lines_counts_the_lines_that_are_drawn(self) -> None:
        """「两条线」 on a chart that draws three is a caption contradicting itself."""
        words = {"两条线": 2, "三条线": 3, "四条线": 4}
        checked = 0
        for exhibit in self.exhibits:
            drawn = len(exhibit.get("series") or exhibit.get("stacks") or [])
            if not drawn:
                continue
            text = (exhibit.get("note") or "") + (exhibit.get("title") or "")
            for word, value in words.items():
                if word in text:
                    checked += 1
                    self.assertEqual(value, drawn,
                                     f"Ex{exhibit['n']} says {word}, draws {drawn}")
        self.assertGreaterEqual(checked, 3)

    def test_every_series_is_as_long_as_the_axis_it_is_drawn_against(self) -> None:
        """One mark per label, checked on this page's own exhibits.

        `test_chart_contract.py` runs the same identity site-wide off the built
        payload; this runs off the builder, so a length bug is red before
        anything is written to `data/`.
        """
        for exhibit in self.exhibits:
            n = len(exhibit["xlabels"])
            for key in ("values", "lo", "hi", "actual"):
                if key in exhibit:
                    self.assertEqual(len(exhibit[key]), n, f"{exhibit['title']} {key}")
            for key in ("series", "stacks", "groups"):
                for member in exhibit.get(key, []):
                    self.assertEqual(len(member["values"]), n,
                                     f"{exhibit['title']} {key} {member['name']}")
            for key in ("bar", "line", "yoy"):
                block = exhibit.get(key)
                if isinstance(block, dict) and block.get("values") is not None:
                    self.assertEqual(len(block["values"]), n, f"{exhibit['title']} {key}")

    def test_the_investment_residual_is_never_on_a_zero_floored_right_axis(self) -> None:
        """Whichever exhibit carries the residual must scale its axis from data."""
        residual_names = ("投资及其他收益",)
        for exhibit in self.exhibits:
            if exhibit["kind"] != "stacked_dual":
                continue
            for name in residual_names:
                self.assertNotIn(name, exhibit["line"]["name"], exhibit["title"])
            for member in exhibit["stacks"]:
                self.assertGreaterEqual(min(member["values"]), 0, exhibit["title"])

    def test_every_right_axis_share_line_declares_its_ceiling(self) -> None:
        """`stacked_dual` scales its right axis to `ymax || 60` and never looks
        at the data, so a share line above 60 is drawn off-canvas while the
        legend still names it. `ymax` belongs in `ex.line`, not at the top."""
        for exhibit in self.exhibits:
            if exhibit["kind"] != "stacked_dual":
                continue
            line = exhibit["line"]
            self.assertNotIn("ymax", exhibit, exhibit["title"])
            self.assertIn("ymax", line, exhibit["title"])
            self.assertGreaterEqual(line["ymax"], max(line["values"]), exhibit["title"])

    def test_every_column_the_axis_names_carries_a_mark(self) -> None:
        """A stack that is zero in some column leaves a labelled empty slot."""
        for exhibit in self.exhibits:
            if exhibit["kind"] != "stacked_dual":
                continue
            for index, label in enumerate(exhibit["xlabels"]):
                drawn = sum(1 for stack in exhibit["stacks"]
                            if stack["values"][index] not in (None, 0))
                self.assertGreater(drawn, 0, f"{exhibit['title']} @ {label}")

    def test_long_axes_carry_a_step_so_the_labels_stay_readable(self) -> None:
        for exhibit in self.exhibits:
            if len(exhibit["xlabels"]) > 30:
                self.assertIn("xstep", exhibit, exhibit["title"])

    def test_no_exhibit_uses_a_renderer_branch_this_page_cannot_feed(self) -> None:
        """`gs_bar` without `yoy` draws a dashed line at an `avg12` no builder
        emits; this page's one `gs_bar` must carry `yoy`."""
        for exhibit in self.exhibits:
            if exhibit["kind"] == "gs_bar":
                self.assertTrue(exhibit.get("yoy", {}).get("values"), exhibit["title"])

    def test_the_headline_counts_are_recomputed_not_typed(self) -> None:
        recon = hkex.reconcile_against_printed(self.staging)
        headline = self.payload["headline"]
        self.assertIn(str(recon["compared"]), headline)
        self.assertIn(str(recon["mismatches"]), headline)
        self.assertIn(str(len(hkex.never_printed(self.staging, hkex.FEE_LINES))),
                      headline)
        derived = sum(1 for b in self.staging["quarter_basis"] if b == "derived")
        self.assertIn(str(derived), headline)

    def test_the_literal_text_slots_carry_no_markup(self) -> None:
        for key in ("title", "subtitle", "headline", "tracker"):
            self.assertNotRegex(self.payload[key], r"<[a-z/]")
        for note in self.payload["notes"]:
            self.assertNotRegex(note, r"<[a-z/]")
        for section in self.payload["sections"]:
            self.assertNotRegex(section["title"], r"<[a-z/]")
            self.assertNotRegex(section["description"], r"<[a-z/]")

    def test_the_page_carries_the_cross_page_capex_table(self) -> None:
        """Every page publishes it; missing it raises StopIteration elsewhere."""
        table = next(t for t in self.payload["tables"] if "AI capex" in t["title"])
        self.assertGreater(len(table["rows"]), 0)

    def test_the_audit_ledger_lists_every_quarter_with_its_basis(self) -> None:
        ledger = next(t for t in self.payload["tables"] if "原值与来历" in t["title"])
        self.assertEqual(len(ledger["rows"]), len(self.staging["quarters"]))
        derived = sum(1 for row in ledger["rows"] if row[1].endswith("D"))
        self.assertEqual(derived, sum(1 for b in self.staging["quarter_basis"] if b == "derived"))

    def test_the_reconciliation_table_accounts_for_every_compared_cell(self) -> None:
        """The drawer must add up to the number the page's headline claims.

        The table it replaces showed 33 rows from the summary box and called
        that the reconciliation. It was true and far too narrow: the annual
        report's quarterly table covers every year from FY2016, and the two
        disclosure generations -- six line items until FY2021, twelve after --
        are visible in the table's own 科目数 column.
        """
        recon = hkex.reconcile_against_printed(self.staging)
        table = next(t for t in self.payload["tables"] if "逐格对照" in t["title"])
        self.assertEqual(len(table["rows"]), len(self.staging["ar_quarter_tables"]["by_year"]))
        self.assertEqual(sum(int(r[3]) for r in table["rows"]), recon["compared"])
        self.assertEqual(sum(int(r[4]) for r in table["rows"]),
                         recon["derived_compared"])
        self.assertEqual(sum(int(r[5]) for r in table["rows"]), 0)
        # the generation boundary the page argues for, read off the table
        fields = {r[0]: int(r[2]) for r in table["rows"]}
        self.assertTrue(all(fields[str(y)] == 6 for y in range(2016, 2022)))
        self.assertTrue(all(count == 12 for year, count in fields.items() if year >= "2022"))

    def test_the_entry_matches_the_payload_and_the_group_exists(self) -> None:
        entry = next(e for e in ENTRIES if e["slug"] == "hkex")
        self.assertEqual(entry["ticker"], self.payload["company"]["ticker"])
        self.assertEqual(entry["group"], self.payload["company"]["group"])
        self.assertIn(entry["group"], {g["key"] for g in GROUPS})

    def test_published_payload_and_shell(self) -> None:
        self.assertEqual(js_payload(ROOT / "data" / "hkex.js", "window.DASH"), self.payload)
        roster = js_payload(ROOT / "data" / "roster.js", "window.ROSTER")
        self.assertEqual(roster, roster_payload(build_all()))
        self.assertIn("hkex", [item["slug"] for item in roster["items"]])
        shell = (ROOT / "hkex" / "index.html").read_text(encoding="utf-8")
        self.assertIn("../data/hkex.js", shell)
        self.assertNotIn("../data/cme.js", shell)

    def test_sources_are_hkex_hosts_over_https(self) -> None:
        allowed = {"www.hkexgroup.com", "www1.hkexnews.hk", "www.hkex.com.hk"}
        urls = [item["url"] for item in self.payload["source_links"]]
        urls += [a["url"] for a in self.staging["announcements"]]
        urls.append(self.payload["source_url"])
        for url in urls:
            self.assertTrue(url.startswith("https://"), url)
            host = re.match(r"https://([^/]+)/", url).group(1)
            self.assertIn(host, allowed, url)



class HkexChecksTest(unittest.TestCase):
    """The page's quarter against a record keyed separately from the announcement.

    `_checks` is typed once per quarter from the results announcement, with the
    place in it each figure was read from; the builder never reads it (asserted
    in `test_data_only_roll`). For an interim quarter the statement prints six
    months, so the check on the derived quarter is the one that matters here:
    this page's Q1 and Q2 must add up to the six months the announcement prints,
    in both columns. Rolling a quarter re-keys `_checks`; this class does not change.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(hkex.STAGING_PATH.read_text(encoding="utf-8"))
        cls.checks = cls.staging["_checks"]
        cls.payload = hkex.build_payload(cls.staging)
        cls.quarters = cls.staging["quarters"]

    def test_the_page_names_the_checked_quarter(self) -> None:
        checks = self.checks
        self.assertIn(checks["period"], self.payload["title"])
        self.assertIn(f"截至 {checks['period_end']}", self.payload["subtitle"])
        self.assertIn(f"发布 {checks['release_date']}", self.payload["subtitle"])
        label = hkex.announcement_label(checks["period"])
        release = next(x for x in self.staging["sources"] if x["label"].startswith(label))
        self.assertIn(release["url"], self.payload["source"])
        self.assertIn(label, self.payload["source"])

    def test_the_two_quarters_add_up_to_the_printed_six_months(self) -> None:
        """Both columns: this year's H1 and the H1 a year earlier."""
        if "six_months_hkd_m" not in self.checks:
            return
        q = self.staging["quarterly"]
        year = int(self.checks["period"].split()[1])
        for line, (now, ago) in self.checks["six_months_hkd_m"].items():
            if line not in q:
                continue
            for column, (y, value) in enumerate(((year, now), (year - 1, ago))):
                first, second = (self.quarters.index(f"{y}Q1"), self.quarters.index(f"{y}Q2"))
                with self.subTest(line=line, year=y):
                    self.assertAlmostEqual(q[line][first] + q[line][second], value, delta=0.5)
        half = self.staging["half_investment"]
        index = self.staging["halves"].index(f"{year}H1")
        six = self.checks["six_months_hkd_m"]
        self.assertEqual(half["gross"][index], six["investment_income"][0])
        self.assertEqual(half["rebates"][index], six["interest_rebates"][0])
        self.assertEqual(half["net"][index], six["net_investment_income"][0])

    def test_the_printed_quarter_box_is_the_series(self) -> None:
        q = self.staging["quarterly"]
        box = self.staging["printed_box"][self.quarters[-1]]
        for line, (now, ago) in self.checks["key_financials_q2_hkd_m"].items():
            with self.subTest(line=line):
                self.assertEqual(box[line], now)
                if line in q:
                    self.assertEqual(q[line][-1], now)
                    self.assertEqual(q[line][-5], ago)

    def test_the_market_statistics_are_the_series(self) -> None:
        kpi = self.staging["kpi_quarterly"]
        for line, (now, ago) in self.checks["market_statistics_q2"].items():
            with self.subTest(line=line):
                self.assertEqual(kpi[line][-1], now)
                self.assertEqual(kpi[line][-5], ago)

    def test_the_printed_rates_agree_with_the_page_at_printed_precision(self) -> None:
        q = self.staging["quarterly"]
        printed = self.checks["printed"]
        roi, profit = q["revenue_and_other_income"], q["profit_attributable"]
        self.assertEqual(round(hkex.pct(roi[-1], roi[-5])), printed["q2_revenue_and_other_income_growth_pct"])
        self.assertEqual(round(hkex.pct(profit[-1], profit[-5])), printed["q2_profit_growth_pct"])
        company = q["ebitda"][-1] / (roi[-1] + q["transaction_expenses"][-1]) * 100
        self.assertEqual(round(company), printed["q2_ebitda_margin_pct"])
        context = stamped_block(self.staging, "quarter_context", self.checks["period"])
        if context:
            self.assertEqual(context["printed_ebitda_margin_pct"], printed["q2_ebitda_margin_pct"])
        if printed["record_quarterly_revenue_and_profit"]:
            self.assertEqual(roi[-1], max(roi))
            self.assertEqual(profit[-1], max(profit))
            self.assertIn("新高", self.payload["headline"])

    def test_the_thresholds_current_values_are_the_series(self) -> None:
        kpi = stamped_block(self.staging, "next_kpi", self.checks["period"])
        if not kpi:
            return
        q = self.staging["quarterly"]
        half = self.staging["half_investment"]
        non_trading = q["listing_fees"][-1] + q["depository_fees"][-1] + q["market_data_fees"][-1]
        current = {
            "EBITDA 利润率": q["ebitda"][-1] / q["revenue_and_other_income"][-1] * 100,
            "现货市场日均成交额": self.staging["kpi_quarterly"]["adt_headline"][-1],
            "保证金投资收益返还比例（半年）": -half["rebates"][-1] / half["gross"][-1] * 100,
            "非交易类收入占收入": non_trading / q["revenue"][-1] * 100,
            "LME 计费日均手数": self.staging["kpi_quarterly"]["adv_lme"][-1],
            "有效税率": -q["taxation"][-1] / q["profit_before_tax"][-1] * 100,
        }
        for entry in kpi["quantified"]:
            with self.subTest(metric=entry["metric"]):
                self.assertAlmostEqual(entry["current"], current[entry["metric"]], places=2)


SECTIONS = [("settled", "一、上季跟踪指标兑现了吗"),
            ("quarter_highlights", "二、本季重点"),
            ("next_quarter", "三、下季要跟踪什么"),
            ("routine", "四、长期常规跟踪")]

def report_note(staging: dict) -> dict:
    """The owner's two analyses, keyed from the reports into `_checks["note"]`.

    Report facts -- question counts, verdicts, thresholds -- are held there and
    not in this file, so a roll re-keys them with the series and this file does
    not change (CLAUDE.md §9). The builder never reads `_checks`; the blocks it
    does read (`followup_closure`, `prior_kpi_settlement`, `next_kpi`) are held
    against this independent keying.
    """
    return staging["_checks"]["note"]


class HkexFourSectionTest(unittest.TestCase):
    """The page runs in the site's four sections, and section one settles what
    last quarter's analysis left open -- counted from the block, never typed."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(hkex.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = hkex.build_payload(cls.staging)
        cls.sections = cls.payload["sections"]
        cls.note = report_note(cls.staging)

    def test_the_page_runs_in_the_four_sections(self) -> None:
        self.assertEqual([(s["id"], s["title"]) for s in self.sections], SECTIONS)
        for section in self.sections:
            self.assertTrue(section["exhibits"], section["id"])
        self.assertIn("本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列",
                      self.payload["notes"][0])
        # the old self-description must not survive anywhere on the page
        self.assertNotIn("披露结构 → 本季重点", published_text(self.payload))

    def test_section_one_says_why_there_is_no_guidance_record(self) -> None:
        """(c) has nothing to settle: the company publishes no financial guidance."""
        description = self.sections[0]["description"]
        self.assertIn("不发布任何财务指引", description)
        census = self.staging["guidance_census"]
        self.assertIn(f"{census['documents']} 份业绩公告", description)
        self.assertIn(f"{census['forward_statements_with_a_number']} 处", description)

    def test_the_closure_is_the_reports_section_zero(self) -> None:
        expected = self.note["followup_closure"]
        closure = self.staging["followup_closure"]
        self.assertEqual(len(closure["items"]), expected["total"])
        counted = {label: sum(1 for item in closure["items"] if item["verdict"] == label)
                   for label in closure["labels"]}
        self.assertEqual(counted, expected["counts"])
        self.assertEqual([item["n"] for item in closure["items"] if item["verdict"] == "仍未披露"],
                         expected["open"])
        self.assertEqual([item["n"] for item in closure["items"] if item.get("against_prior") == "worse"],
                         expected["worse_than_prior"])
        chart = self.sections[0]["exhibits"][0]
        self.assertEqual(chart["kind"], "bars_labeled")
        drawn = {label: count for label, count in expected["counts"].items() if count}
        self.assertEqual(
            chart["title"],
            f"上季 {expected['total']} 条待验证问题："
            + "、".join(f"{count} 条{label}" for label, count in drawn.items())
            + "".join(f"，没有一条{label}" for label, count in expected["counts"].items() if not count))
        # a verdict nobody received is named in the title, never drawn as an empty column
        self.assertEqual(dict(zip(chart["xlabels"], chart["values"])), drawn)
        self.assertNotIn(0, chart["values"])

    def test_the_closure_title_is_counted_from_the_items(self) -> None:
        changed = copy.deepcopy(self.staging)
        before = hkex.build_payload(changed)["sections"][0]["exhibits"][0]
        closure = changed["followup_closure"]
        item = closure["items"][0]
        item["verdict"] = next(label for label in closure["labels"] if label != item["verdict"])
        counts = {label: sum(1 for i in closure["items"] if i["verdict"] == label)
                  for label in closure["labels"]}
        chart = hkex.build_payload(changed)["sections"][0]["exhibits"][0]
        self.assertNotEqual(chart["title"], before["title"])
        self.assertIn(f"{counts[item['verdict']]} 条{item['verdict']}", chart["title"])
        self.assertEqual(sum(chart["values"]), sum(before["values"]))

    def test_a_verdict_outside_the_labels_stops_the_build(self) -> None:
        changed = copy.deepcopy(self.staging)
        changed["followup_closure"]["items"][0]["verdict"] = "部分验证"
        with self.assertRaisesRegex(ValueError, "followup_closure"):
            hkex.build_payload(changed)

    def test_every_built_chart_lands_in_exactly_one_section(self) -> None:
        refs = [ex.get("ref") for section in self.sections for ex in section["exhibits"]]
        self.assertEqual(len(refs), len(set(refs)))
        numbers = [ex["n"] for section in self.sections for ex in section["exhibits"]]
        self.assertEqual(numbers, list(range(1, len(numbers) + 1)))
        # captions point at charts by number, and every number they name exists
        text = published_text(self.payload)
        self.assertNotRegex(text, r"\{EX_[A-Z]+\}")
        for match in re.finditer(r"Exhibit (\d+)", text):
            self.assertLessEqual(int(match.group(1)), len(numbers))


def by_ref(payload: dict) -> dict:
    return {ex["ref"]: ex for section in payload["sections"] for ex in section["exhibits"] if ex.get("ref")}


def cumulative(readings: list[dict], value) -> dict:
    """Period -> value, asserting every period printed twice was printed the same."""
    out: dict = {}
    for reading in readings:
        v = value(reading)
        if reading["period"] in out and out[reading["period"]] != v:
            raise AssertionError(f"{reading['period']} printed as {out[reading['period']]} and {v}")
        out[reading["period"]] = v
    return out


def quarter_of(cum: dict, quarter: str):
    """Recomputed here, not with the builder's helper: Q2 = H1 − Q1 and so on."""
    year, n = quarter[:4], quarter[5]
    span = {"1": "Q1", "2": "H1", "3": "9M", "4": "FY"}[n]
    before = {"1": None, "2": "Q1", "3": "H1", "4": "9M"}[n]
    return cum[year + span] - (cum[year + before] if before else 0)


class HkexPriorSettlementTest(unittest.TestCase):
    """Section one (b): last quarter's quantified lines, settled on this quarter.

    Thresholds and verdicts are held against `_checks["note"]`, keyed from the
    two reports; the actuals are recomputed here from the readings, without the
    builder's own helpers (a check that derives its expectation from the code
    under test cannot fail).
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(hkex.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = hkex.build_payload(cls.staging)
        cls.note = report_note(cls.staging)
        cls.prior = cls.staging["prior_kpi_settlement"]
        cls.charts = by_ref(cls.payload)

    def lines_of(self, indicator: int) -> list[tuple]:
        out = []
        for entry in self.prior["quantified"]:
            if entry["indicator"] != indicator:
                continue
            if "threshold" in entry:
                out.append(("risk", entry["threshold"], entry["direction"], 1))
            if "bull_threshold" in entry:
                out.append(("bull", entry["bull_threshold"], entry["direction"], entry.get("bull_quarters", 1)))
        return sorted(out)

    def test_the_lines_are_the_prior_reports_section_eight(self) -> None:
        indicators = sorted({line["indicator"] for line in self.note["prior_thresholds"]})
        self.assertEqual(indicators, [i["n"] for i in self.prior["indicators"]])
        for n in indicators:
            expected = sorted((line["role"], line["threshold"], line["direction"], line.get("quarters", 1))
                              for line in self.note["prior_thresholds"] if line["indicator"] == n)
            with self.subTest(indicator=n):
                self.assertEqual(self.lines_of(n), expected)

    def test_the_verdicts_are_the_reports(self) -> None:
        self.assertEqual({str(i["n"]): i["report_verdict"] for i in self.prior["indicators"]},
                         self.note["prior_verdicts"])

    def actuals(self) -> dict[str, list[float]]:
        """The settled quarter and the one before, recomputed from the readings."""
        s = self.staging
        quarters = s["quarters"]
        prev, last = quarters[-2], quarters[-1]
        roi = dict(zip(quarters, s["quarterly"]["revenue_and_other_income"]))
        r = self.prior["readings"]
        connect = cumulative(r["connect_revenue_hkd_m"], lambda x: x["value"])
        funds = cumulative(r["ipo_funds_hkd_bn"], lambda x: x["value"])
        listed = cumulative(r["newly_listed"], lambda x: x["main_board"] + x["gem"])
        seg = s["segment_readings"]["readings"]
        rev = cumulative(seg, lambda x: x["roi_less_txn"]["commodities"])
        ebitda = cumulative(seg, lambda x: x["ebitda"]["commodities"])
        eq = cumulative([x for x in s["unlisted_equity"]["readings"]
                         if not x["column"].startswith("three months")], lambda x: x["value"])
        adt = s["kpi_quarterly"]["adt_headline"]
        return {
            "adt_vs_prior": [adt[-2] / adt[-3] * 100, adt[-1] / adt[-2] * 100],
            "connect_share": [quarter_of(connect, q) / roi[q] * 100 for q in (prev, last)],
            "ipo_funds": [quarter_of(funds, q) for q in (prev, last)],
            "ipo_listings": [quarter_of(listed, q) for q in (prev, last)],
            "commodities_margin": [quarter_of(ebitda, q) / quarter_of(rev, q) * 100 for q in (prev, last)],
            "commodities_revenue": [quarter_of(rev, q) for q in (prev, last)],
            "unlisted_equity": [abs(quarter_of(eq, q)) for q in (prev, last)],
        }

    @staticmethod
    def margin(entry: dict, threshold: float, actual: float) -> float:
        sign = 1 if entry["direction"] == "up" else -1
        return round(sign * (actual - threshold) / threshold * 100, 1)

    def test_the_two_headroom_charts_are_recomputed_here(self) -> None:
        actuals = self.actuals()
        risk_chart, bull_chart = self.charts["EX_PRIOR_RISK"], self.charts["EX_PRIOR_BULL"]
        risk = [e for e in self.prior["quantified"] if "threshold" in e]
        bull = [e for e in self.prior["quantified"] if "bull_threshold" in e]
        self.assertEqual(risk_chart["xlabels"], [e["metric"] for e in risk])
        self.assertEqual(risk_chart["values"],
                         [self.margin(e, e["threshold"], actuals[e["id"]][-1]) for e in risk])
        worst = {e["id"]: (min if e["direction"] == "up" else max)(actuals[e["id"]][-e.get("bull_quarters", 1):])
                 for e in bull}
        self.assertEqual(bull_chart["values"], [self.margin(e, e["bull_threshold"], worst[e["id"]]) for e in bull])
        held = sum(1 for v in risk_chart["values"] if v >= 0)
        self.assertTrue(risk_chart["title"].startswith(
            f"上季 {len(risk)} 条量化阈值：{held} 条守住、{len(risk) - held} 条被击穿"))
        cleared = sum(1 for v in bull_chart["values"] if v >= 0)
        self.assertIn(f"{len(bull)} 条里 {cleared} 条兑现", bull_chart["title"])

    def test_each_indicator_lands_where_the_report_put_it(self) -> None:
        """Risk line breached -> the risk verdict; every bull line cleared -> the bull
        verdict; neither -> 未触发. The report's five verdicts, reproduced."""
        actuals = self.actuals()
        kinds = {"加仓": "bull", "多元化里程碑": "bull", "警示": "risk", "重新评估": "risk", "未触发": "none"}
        for indicator in self.prior["indicators"]:
            rows = [e for e in self.prior["quantified"] if e["indicator"] == indicator["n"]]
            risk = any("threshold" in e and self.margin(e, e["threshold"], actuals[e["id"]][-1]) < 0
                       for e in rows)
            bulls = [e for e in rows if "bull_threshold" in e]
            bull = bool(bulls) and all(
                self.margin(e, e["bull_threshold"],
                            (min if e["direction"] == "up" else max)(actuals[e["id"]][-e.get("bull_quarters", 1):])) >= 0
                for e in bulls)
            got = "risk" if risk else ("bull" if bull else "none")
            with self.subTest(indicator=indicator["n"]):
                self.assertEqual(got, kinds[self.note["prior_verdicts"][str(indicator["n"])]])

    def test_a_verdict_the_numbers_no_longer_support_stops_the_build(self) -> None:
        changed = copy.deepcopy(self.staging)
        entry = next(e for e in changed["prior_kpi_settlement"]["quantified"] if e["id"] == "commodities_margin")
        entry["threshold"] = 60.0       # now held, but the block still says 警示
        with self.assertRaisesRegex(ValueError, "prior_kpi_settlement indicator 4"):
            hkex.build_payload(changed)

    def test_the_three_line_charts_carry_their_lines(self) -> None:
        adt = self.charts["EX_PRIOR_ADT"]
        commod = self.charts["EX_PRIOR_COMMOD"]
        equity = self.charts["EX_PRIOR_EQUITY"]
        by_id = {e["id"]: e for e in self.prior["quantified"]}
        self.assertEqual({s["values"][0] for s in adt["series"][1:]},
                         {by_id["adt_vs_prior"]["threshold"], by_id["adt_vs_prior"]["bull_threshold"]})
        self.assertEqual({s["values"][0] for s in commod["series"][1:]},
                         {by_id["commodities_margin"]["threshold"], by_id["commodities_margin"]["bull_threshold"]})
        self.assertEqual({s["values"][0] for s in equity["series"][1:]},
                         {by_id["unlisted_equity"]["threshold"], -by_id["unlisted_equity"]["threshold"]})
        actuals = self.actuals()
        self.assertAlmostEqual(adt["series"][0]["values"][-1], actuals["adt_vs_prior"][-1], places=4)
        self.assertAlmostEqual(commod["series"][0]["values"][-1], actuals["commodities_margin"][-1], places=4)
        self.assertEqual(abs(equity["series"][0]["values"][-1]), actuals["unlisted_equity"][-1])
        for chart in (adt, commod, equity):
            self.assertEqual(chart["xlabels"][-1], self.staging["quarters"][-1])
            word = "守住" if "守住上季阈值" in chart["title"] else "击穿"
            self.assertIn(f"{word}上季阈值", chart["title"])

    # ── the two new reading blocks ───────────────────────────────────────────
    def test_every_segment_reading_adds_up_and_agrees_with_its_second_printing(self) -> None:
        readings = self.staging["segment_readings"]["readings"]
        segments = list(self.staging["segment_readings"]["segments"])
        seen: dict = {}
        for r in readings:
            for field in ("roi_less_txn", "ebitda"):
                self.assertEqual(sum(r[field][s] for s in segments), r[field]["group"], (r["doc"], field))
            key = (r["period"],)
            pair = (r["roi_less_txn"], r["ebitda"])
            if key in seen:
                self.assertEqual(seen[key], pair, r["period"])
            seen[key] = pair
        twice = {r["period"] for r in readings if r["column"] == "prior-year comparative"}
        self.assertGreaterEqual(len(twice), 10)

    def test_the_segment_totals_are_this_pages_income_statement(self) -> None:
        """The group column of every segment table equals the page's own quarters.

        Two different tables of the same announcements -- the segment note and
        the condensed income statement the rest of this page is built from --
        so this ties the new block to twelve years of reconciled series.
        """
        quarters = self.staging["quarters"]
        q = self.staging["quarterly"]
        spans = {"Q1": (1,), "H1": (1, 2), "9M": (1, 2, 3), "FY": (1, 2, 3, 4)}
        checked = 0
        for r in self.staging["segment_readings"]["readings"]:
            year, span = r["period"][:4], r["period"][4:]
            idx = [quarters.index(f"{year}Q{n}") for n in spans[span]]
            ebitda = sum(q["ebitda"][i] for i in idx)
            less = sum(q["revenue_and_other_income"][i] + q["transaction_expenses"][i] for i in idx)
            self.assertAlmostEqual(r["ebitda"]["group"], ebitda, delta=0.5, msg=r["period"])
            self.assertAlmostEqual(r["roi_less_txn"]["group"], less, delta=0.5, msg=r["period"])
            checked += 1
        self.assertGreaterEqual(checked, 28)

    def test_the_commodities_series_starts_where_the_2023_basis_starts(self) -> None:
        """2022 exists on this basis only as the restated comparatives of 2023."""
        readings = self.staging["segment_readings"]["readings"]
        self.assertEqual(min(r["period"][:4] for r in readings), "2022")
        restated = [r for r in readings if r["period"].startswith("2022")]
        self.assertEqual(sorted(r["period"] for r in restated), sorted(["2022Q1", "2022H1", "20229M", "2022FY"]))
        self.assertTrue(all(r["doc"].startswith("2023_") for r in restated))
        chart = self.charts["EX_PRIOR_COMMOD"]
        self.assertEqual(chart["xlabels"][0], "2022Q1")

    def test_the_unlisted_equity_line_agrees_with_every_other_printing(self) -> None:
        block = self.staging["unlisted_equity"]
        cum = cumulative([r for r in block["readings"] if not r["column"].startswith("three months")],
                         lambda r: r["value"])
        printed = [(r["period"], r["value"]) for r in block["readings"] if r["column"].startswith("three months")]
        printed += [(p["quarter"], p["value"]) for p in block["prose_quarters"] if "differs" not in p]
        self.assertGreaterEqual(len(printed), 8)
        for quarter, value in printed:
            with self.subTest(quarter=quarter):
                self.assertEqual(quarter_of(cum, quarter), value)
        # the one printing that does not agree is named, with the size of the gap
        differs = [p for p in block["prose_quarters"] if "differs" in p]
        self.assertEqual([(p["quarter"], p["value"] - quarter_of(cum, p["quarter"])) for p in differs],
                         [("2023Q4", -4)])
        chart = self.charts["EX_PRIOR_EQUITY"]
        self.assertEqual(chart["xlabels"][0], "2021Q1")
        self.assertEqual(len(chart["xlabels"]), len(chart["series"][0]["values"]))


class HkexRollTest(unittest.TestCase):
    """A roll edits the series and nothing else: the one-quarter blocks and the
    sentences about the record are held to what the series says."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(hkex.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = hkex.build_payload(cls.staging)
        cls.text = published_text(cls.payload)

    def rebuilt(self, edit) -> dict:
        changed = copy.deepcopy(self.staging)
        edit(changed)
        return hkex.build_payload(changed)

    def moves(self, claims, edit, present_before=True) -> None:
        after = published_text(self.rebuilt(edit))
        for claim in claims:
            with self.subTest(claim=claim):
                self.assertEqual(claim in self.text, present_before)
                self.assertEqual(claim in after, not present_before)

    def test_quarter_blocks_refuse_to_publish_under_another_quarter(self) -> None:
        for key in ("next_kpi", "quarter_context", "followup_closure", "prior_kpi_settlement"):
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    self.rebuilt(lambda s, key=key: s[key].__setitem__("period", "Q1 1999"))
        label = hkex.announcement_label(self.staging["latest"]["disclosed_period_label"])
        with self.assertRaisesRegex(ValueError, "sources"):
            self.rebuilt(lambda s: s.__setitem__(
                "sources", [x for x in s["sources"] if not x["label"].startswith(label)]))

    def test_a_quarter_without_its_blocks_leaves_them_out(self) -> None:
        def strip(s):
            del s["next_kpi"]
            del s["quarter_context"]
            del s["followup_closure"]
            del s["prior_kpi_settlement"]
        payload = self.rebuilt(strip)
        # the next-quarter unit table, and the prior-settlement table with its two ledgers
        self.assertEqual(len(payload["tables"]), len(self.payload["tables"]) - 4)
        text = published_text(payload)
        for gone in ("条本地阈值离触发还有多远", "公司在同一份公告里印的是", "条本地阈值的原始单位",
                     "条待验证问题", "条量化阈值", "上季阈值与本季实际"):
            with self.subTest(gone=gone):
                self.assertIn(gone, self.text)
                self.assertNotIn(gone, text)

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        # Profit is a 42-quarter high this quarter; make an earlier quarter higher.
        def profit_not_record(s):
            s["quarterly"]["profit_attributable"][-3] = s["quarterly"]["profit_attributable"][-1] + 1
        self.moves(("两者都是",), profit_not_record)

        # The quarter before had the higher margin; lower it.
        def last_quarter_lower(s):
            q = s["quarterly"]
            q["ebitda"][-2] = q["revenue_and_other_income"][-2] * 0.5
        self.moves(("上一季也比它高",), last_quarter_lower)

        # The rebate share dipped to 1.4% on its way to the peak; take the dip out.
        def no_dip(s):
            block = s["half_investment"]
            for i in range(len(block["gross"])):
                block["rebates"][i] = -block["gross"][i] * (0.1 + 0.03 * i)
                block["net"][i] = block["gross"][i] + block["rebates"][i]
        self.moves(("（中间在 2020H2 低到 1.4%）",), no_dip)

        # Once FY2026 prints its quarter table, the quarter just published is no longer waiting.
        def annual_table_out(s):
            for field in hkex.FEE_LINES:
                s["first_printed"][f"2026Q2|{field}"] = {"doc": "2026_FY", "published": "2027-02-25"}
            s["ar_quarter_tables"]["by_year"]["2026"] = {
                "source": "2026_FY",
                "values": {"revenue_and_other_income": [
                    s["quarterly"]["revenue_and_other_income"][-2],
                    s["quarterly"]["revenue_and_other_income"][-1], 0, 0]}}
        self.moves(("加上刚发布的 2026Q2", "刚发布的 2026Q2 要等到", "唯一还没有对照物的是刚发布的"),
                   annual_table_out)

    def test_the_counts_on_the_page_are_recounted_here(self) -> None:
        q = self.staging["quarterly"]
        gaps = [e / (r + t) * 100 - e / r * 100 for e, r, t in
                zip(q["ebitda"], q["revenue_and_other_income"], q["transaction_expenses"])
                if t is not None]
        self.assertIn(f"两者的差在 {min(gaps):.1f}–{max(gaps):.1f} 个百分点之间", self.text)
        gross, net = self.staging["half_investment"]["gross"], self.staging["half_investment"]["net"]
        moves = [((g1 > g0) - (g1 < g0), (n1 > n0) - (n1 < n0))
                 for g0, g1, n0, n1 in zip(gross, gross[1:], net, net[1:])]
        opposite = sum(1 for a, b in moves if a * b < 0)
        self.assertIn(f"毛额与净额在 {len(moves)} 次半年环比里有 {opposite} 次走出相反方向", self.text)
        before_fy2022 = [x for x in self.staging["quarters"] if x < "2022" and x[5] in "24"]
        self.assertIn(f"{len(before_fy2022)} 个更早的季度没有", self.text)
        for stale in ("一路降到", "一路走到", "毛额腰斩", "公司自 2021Q1 起按季印出",
                      "下面两张图分别是", "两者的差在 1 个百分点以内", "两次走出相反方向",
                      "13 个更早的季度没有"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, self.text)
        # The regression recomputed here, not by calling the builder's own
        # function -- a check that derives its expectation from the code under
        # test cannot fail (CLAUDE.md §5).
        kq, quarters, q = self.staging["kpi_quarters"], self.staging["quarters"], self.staging["quarterly"]
        rows = [quarters.index(x) for x in kq]

        def changes(values):
            return [(b / a - 1) * 100 for a, b in zip(values, values[1:])]

        def slope(xs, ys):
            mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
            return (sum((x - mx) * (y - my) for x, y in zip(xs, ys))
                    / sum((x - mx) ** 2 for x in xs))

        turnover = changes(self.staging["kpi_quarterly"]["adt_headline"])
        slopes = [slope(turnover, changes(values)) for values in (
            [q["trading_fees"][i] + q["clearing_fees"][i] for i in rows],
            [q["revenue"][i] for i in rows],
            [q["revenue_and_other_income"][i] for i in rows])]
        self.assertIn("斜率 " + " → ".join(f"{v:.2f}" for v in slopes), self.text)
        self.assertNotIn("fee_elasticity", self.staging,
                         "the regression is computed from the arrays; a stored copy goes stale")


if __name__ == "__main__":
    unittest.main()
