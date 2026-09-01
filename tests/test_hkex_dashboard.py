"""HKEX page: the identities that license half of what it publishes.

Twenty-one of this page's forty-two quarters were never printed by anybody.
HKEX's first- and third-quarter announcements each carry a three-month column
in the condensed income statement; the interim announcement carries six months
and the annual twelve, and neither ever prints the discrete second or fourth
quarter. So every even quarter here is `H1 - Q1` or `FY - 9M`, and the whole
page rests on that subtraction being right.

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

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import hkex  # noqa: E402
from build.all import ENTRIES, GROUPS, build_all, roster_payload  # noqa: E402
from build.board import headroom  # noqa: E402

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


class HkexSeriesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(hkex.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = hkex.build_payload(cls.staging)

    # ── the window and what each quarter's number is made of ────────────────
    def test_the_window_runs_from_2016q1_and_is_contiguous(self) -> None:
        quarters = self.staging["quarters"]
        self.assertEqual(quarters[0], "2016Q1")
        self.assertEqual(quarters[-1], "2026Q2")
        self.assertEqual(len(quarters), 42)
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
        """42 documents in, 42 quarters out -- no gap, no document counted twice.

        Written as a set identity rather than a count, because the failure this
        is for is a document quietly standing in for its neighbour, which a
        count cannot see.
        """
        docs = [a["doc"] for a in self.staging["announcements"]]
        self.assertEqual(len(docs), len(set(docs)))
        expected = {f"{year}_{kind}"
                    for year in range(2016, 2026) for kind in ("Q1", "H1", "Q3", "FY")}
        expected |= {"2026_Q1", "2026_H1"}
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
                    in zip(self.staging["quarters"], residual) if value < 0]
        self.assertEqual(negative, ["2020Q1"])
        self.assertLess(min(residual), -40.0)

    # ── the company's own reading of a derived quarter ──────────────────────
    def test_every_printed_box_figure_matches_this_page_exactly(self) -> None:
        check = hkex.box_check(self.staging)
        self.assertEqual(check["mismatches"], 0)
        # 33 comparisons on the eleven derived quarters -- the ones that are
        # evidence for the subtraction -- and 72 including the printed quarters,
        # where the box only cross-checks the statement parse.
        self.assertEqual(check["derived_comparisons"], 33)
        self.assertEqual(check["comparisons"], 72)
        self.assertEqual(len(check["covered"]), 11)
        self.assertEqual(check["covered"][0], "2021Q2")
        self.assertEqual(check["derived_total"], 21)
        self.assertEqual(check["unchecked"], 10)

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
        self.assertEqual(missing, ["2016Q2", "2016Q4", "2017Q2", "2017Q4",
                                   "2018Q2", "2018Q4", "2019Q2", "2019Q4",
                                   "2020Q2", "2020Q4", "2021Q2", "2021Q4",
                                   "2026Q2"])
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
        self.assertEqual(recon["compared"], 296)
        self.assertEqual(recon["derived_compared"], 148)
        self.assertEqual(recon["years"], [str(y) for y in range(2016, 2026)])
        # every even quarter but the one just reported has a counterpart
        self.assertEqual(recon["uncovered_even"], ["2026Q2"])

    def test_the_disclosure_lag_has_the_two_clocks_the_page_describes(self) -> None:
        """Odd and even quarters are public on visibly different schedules."""
        quarters = self.staging["quarters"]
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
        for quarter in self.staging["quarters"]:
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
        self.assertEqual(self.staging["restatement_paired_readings"], 1091)
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
        self.assertEqual(halves[-1], "2026H1")
        self.assertEqual(len(halves), 21)
        for half, kind in zip(halves, basis):
            self.assertEqual(kind, "printed" if half.endswith("H1") else "derived", half)

    def test_the_rebate_share_spans_the_range_the_page_quotes(self) -> None:
        block = self.staging["half_investment"]
        share = [-r / g * 100 for r, g in zip(block["rebates"], block["gross"])]
        self.assertLess(share[0], 15.0)
        self.assertGreater(max(share), 65.0)
        self.assertGreater(share[-1], 50.0)

    # ── the volume block, and the subtraction it must never use ─────────────
    def test_the_kpi_window_starts_where_the_company_started_printing(self) -> None:
        kq = self.staging["kpi_quarters"]
        self.assertEqual(kq[0], "2021Q1")
        self.assertEqual(kq[-1], "2026Q2")
        self.assertEqual(len(kq), 22)
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
        self.assertEqual(years[-1], "2025")
        self.assertEqual(len(years), 10)
        self.assertEqual(self.staging["kpi_annual"]["adt_headline"][0], 66.9)
        for name, values in self.staging["kpi_annual"].items():
            self.assertEqual(len(values), len(years), name)

    # ── what the company does not say ───────────────────────────────────────
    def test_the_page_scores_no_company_guidance_because_there_is_none(self) -> None:
        census = self.staging["guidance_census"]
        self.assertEqual(census["documents"], 42)
        self.assertEqual(census["financial_guidance"], 0)
        self.assertGreater(census["forward_statements_with_a_number"], 0)
        self.assertIsNone(self.payload["guidance"])

    def test_the_thresholds_are_declared_local_not_company_figures(self) -> None:
        excluded = self.staging["next_kpi"]["excluded"]
        self.assertIn("本地研究阈值", excluded)
        for entry in self.staging["next_kpi"]["quantified"]:
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
        self.assertEqual(derived, 21)

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
        self.assertEqual(len(table["rows"]), 10)
        self.assertEqual(sum(int(r[3]) for r in table["rows"]), recon["compared"])
        self.assertEqual(sum(int(r[4]) for r in table["rows"]),
                         recon["derived_compared"])
        self.assertEqual(sum(int(r[5]) for r in table["rows"]), 0)
        # the generation boundary the page argues for, read off the table
        fields = {r[0]: int(r[2]) for r in table["rows"]}
        self.assertTrue(all(fields[str(y)] == 6 for y in range(2016, 2022)))
        self.assertTrue(all(fields[str(y)] == 12 for y in range(2022, 2026)))

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


if __name__ == "__main__":
    unittest.main()
