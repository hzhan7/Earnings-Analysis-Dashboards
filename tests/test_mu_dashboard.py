"""MU page: the identities that license what it publishes.

Micron's page rests on four things that could each be plausibly wrong without
anything else noticing, so each is pinned here against an identity rather than
against a remembered number.

**The quarterly series is a merge of overlapping documents.** Every earnings
release prints three quarter columns and three balance-sheet dates, so all but
the newest quarter was read out of two or three different filings. That is the
defence against a mis-aligned column -- but only if the identities inside each
quarter still close after the merge. Three of them are asserted for every
quarter: revenue less cost of goods sold equals gross margin; gross margin less
research, less selling and administrative, less the other-operating total
equals operating income; and the company's own free-cash-flow definition
(operating cash flow less its "investments in capital expenditures, net")
reproduces its printed adjusted free cash flow.

**The other-operating line is deliberately not published as itself.** Micron
splits it between `Restructure and asset impairments` and `Other operating
(income) expense, net` in some eras and merges them in others, and consecutive
releases disagree about a quarter by up to US$38M for that reason alone. The
page publishes only the total, taken from the income-statement identity. The
test below asserts that the individual line is absent from the series, so a
later pass cannot quietly reintroduce a series whose value depends on which
release it was read from.

**The guidance record's hit rates are printed in chart titles.** A tally is the
one thing on a chart that a reader cannot check, so all three are recounted
from the series here and compared against the strings the builder emitted.
The three-leg decomposition is asserted as the exact identity it claims to be.

**A bridge column with no bar is invisible to every other gate.** `charts.js`
skips a bridge segment whose value is exactly zero, which is how a labelled
column ends up empty while the payload stays finite, the build stays
deterministic and the jsdom gate stays green -- the MCO defect. The share-count
leg of this quarter's earnings bridge IS exactly zero (1,149M diluted shares in
both quarters), so the builder drops the column; this asserts that every column
the bridge's axis names carries a value, whatever the legs happen to be.

One thing is asserted by its absence: this page publishes no `gs_bar`. Every
candidate wanted two comparable dollar series side by side, which is
`grouped_bars`. That keeps `test_the_gs_bar_census_this_file_was_written_against`
in `test_chart_contract.py` untouched, and the assertion here says so out loud
so that adding one later is a deliberate act rather than an accident.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import mu  # noqa: E402
from build.all import ENTRIES, GROUPS, build_all, roster_payload  # noqa: E402
from build.board import cn_count, headroom  # noqa: E402

# From this quarter on every release prints the full statement (cost of goods
# sold, R&D, SG&A); before it the record has a seventeen-quarter hole.
FULL_STATEMENT_FROM = "Q4 2021"


def js_payload(path: Path, marker: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{marker} = ", 1)[1].rstrip().rstrip(";")
    return json.loads(body)


class MuSeriesTest(unittest.TestCase):
    """The source series, before any chart is built."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(mu.STAGING_PATH.read_text(encoding="utf-8"))
        cls.fin = cls.staging["financials"]
        cls.bal = cls.staging["balance_sheet"]
        cls.periods = cls.staging["periods"]

    def test_every_quarterly_series_is_as_long_as_the_period_axis(self) -> None:
        width = len(self.periods)
        self.assertEqual(len(self.staging["fiscal_labels"]), width)
        self.assertEqual(len(self.staging["period_ends"]), width)
        for name, values in {**self.fin, **self.bal}.items():
            if not isinstance(values, list):
                continue
            with self.subTest(series=name):
                self.assertEqual(len(values), width, name)

    def test_the_calendar_label_matches_the_fiscal_period_it_stands_for(self) -> None:
        """MU fiscal Q1 of FY(N) is calendar Q4 of (N-1), not Q1 of anything.

        Costco and NIKE both shipped a mislabelled quarter on this site before
        the rule was written down, and the failure is invisible in the numbers:
        every value is right, it is just filed under a quarter three months away
        from the one it covers. Checked against the period-end date, which is
        the only thing here that comes from the filing rather than from a rule.
        """
        month_to_quarter = {2: "Q1", 3: "Q1", 5: "Q2", 6: "Q2",
                            8: "Q3", 9: "Q3", 11: "Q4", 12: "Q4"}
        for period, fiscal, end in zip(self.periods, self.staging["fiscal_labels"],
                                       self.staging["period_ends"]):
            year, month = int(end[:4]), int(end[5:7])
            with self.subTest(period=period):
                self.assertEqual(period, f"{month_to_quarter[month]} {year}",
                                 f"{fiscal} ended {end}")

    def test_income_statement_identity_holds_each_quarter(self) -> None:
        # The record now reaches 2016 and Micron's releases in that era printed
        # far less: cost of goods sold has a seventeen-quarter hole and the
        # R&D / SG&A split was never backfilled at all. So each identity is
        # checked wherever its own inputs exist, and the count of quarters that
        # could be checked is asserted -- otherwise "every quarter passed" would
        # be satisfied by a record where almost nothing was checkable.
        gross_checked = expense_checked = 0
        for index, period in enumerate(self.periods):
            with self.subTest(period=period):
                revenue = self.fin["revenue_usd_m"][index]
                cogs = self.fin["cost_of_goods_sold_usd_m"][index]
                gross = self.fin["gross_margin_usd_m"][index]
                if None not in (revenue, cogs, gross):
                    gross_checked += 1
                    self.assertAlmostEqual(
                        revenue - cogs, gross, places=6,
                        msg="revenue - cost of goods sold must equal gross margin")
                legs = [self.fin["research_and_development_usd_m"][index],
                        self.fin["selling_general_administrative_usd_m"][index],
                        self.fin["other_operating_total_usd_m"][index]]
                operating = self.fin["gaap_operating_income_usd_m"][index]
                if gross is not None and operating is not None and None not in legs:
                    expense_checked += 1
                    self.assertAlmostEqual(
                        gross - sum(legs), operating, places=4,
                        msg="gross margin less the three expense lines must equal operating income")
        # Counted against the disclosure's own shape rather than a typed total,
        # so appending a quarter moves both sides together: cost of goods sold
        # exists for the first six quarters and for every quarter from Q4 2021
        # on (FULL_STATEMENT_FROM); the expense split only for the latter.
        tail = len(self.periods) - self.periods.index(FULL_STATEMENT_FROM)
        self.assertEqual(gross_checked, 6 + tail)
        self.assertEqual(expense_checked, tail)
        self.assertGreaterEqual(expense_checked, 19)

    def test_the_company_free_cash_flow_definition_reproduces_its_own_figure(self) -> None:
        """`adjusted free cash flow = operating cash flow - investments in capex, net`.

        Both legs and the result are printed in every release, so this is the
        filer's own arithmetic rather than the page's -- which is exactly why it
        catches a column read out of the consolidated cash-flow statement (which
        is year-to-date) instead of out of the reconciliation table (which is
        quarterly). That substitution was live in the first parse of this data
        and produced numbers four times too large in the fiscal first quarters.
        """
        for index, period in enumerate(self.periods):
            capex = self.fin["capex_net_usd_m"][index]
            with self.subTest(period=period):
                if capex is None:
                    self.assertIsNone(self.fin["adjusted_free_cash_flow_usd_m"][index],
                                      "no net capex, so no adjusted free cash flow")
                    continue
                self.assertAlmostEqual(
                    self.fin["operating_cash_flow_usd_m"][index] + capex,
                    self.fin["adjusted_free_cash_flow_usd_m"][index], places=6)
                self.assertLess(capex, 0,
                                "net capex is published as a negative number")

    def test_net_capex_is_the_net_line_in_every_quarter_that_has_one(self) -> None:
        """The identity above cannot see which capex measure sits in the row.

        Its docstring used to say both legs and the result are printed in every
        release. That is true from period-end 2018-03-01, where the earnings
        release carries a RECONCILIATION OF GAAP TO NON-GAAP MEASURES. It was
        never true before: no such table exists in the FY2016/FY2017 releases,
        adjusted free cash flow is computed here from the other two, and so the
        identity holds by construction in exactly the quarters where it is not
        evidence. It held 42 of 42 while eight of those quarters carried GROSS
        capex -- successive differences of the year-to-date gross line -- against
        a net figure everywhere else.

        So the discriminating assertion has to be by value. Micron states the net
        figure in the press-release body of each quarter's own EX-99.1, to three
        significant figures, and the six below are pinned to it. The two nulls
        are pinned too, which is the half that stops the gross values coming
        back: the phrase "net of amounts funded by partners" first appears in the
        release of 2016-10-04, so for the two quarters before it no net figure
        exists to read.

        Independent of the body sentences, the four fiscal-2017 quarters sum onto
        a year-to-date chain printed in different documents -- the FY2017 10-Qs
        and 10-K give 1.18 / 2.35 / 3.62 / 5.13 billion -- which is asserted
        below, and which a gross-basis row fails by about 120 million.
        """
        printed_net = {
            "2016-09-01": -1690.0,   # EX-99.1 of 2016-10-04, acc 0000723125-16-000225
            "2016-12-01": -1180.0,   # EX-99.1 of 2016-12-21, acc 0000723125-16-000306
            "2017-03-02": -1170.0,   # EX-99.1 of 2017-03-23, acc 0000723125-17-000031
            "2017-06-01": -1270.0,   # EX-99.1 of 2017-06-29, acc 0000723125-17-000080
            "2017-08-31": -1510.0,   # EX-99.1 of 2017-09-26, acc 0000723125-17-000106
            "2017-11-30": -1920.0,   # EX-99.1 of 2017-12-19, acc 0000723125-17-000162
        }
        ends = self.staging["period_ends"]
        for end, value in printed_net.items():
            with self.subTest(period_end=end):
                self.assertEqual(self.fin["capex_net_usd_m"][ends.index(end)], value)
        for end in ("2016-03-03", "2016-06-02"):
            with self.subTest(period_end=end):
                self.assertIsNone(self.fin["capex_net_usd_m"][ends.index(end)],
                                  "no net capex is printed for this quarter; the gross "
                                  "figure is a different measure and must not stand in")
        fiscal_2017 = ("2016-12-01", "2017-03-02", "2017-06-01", "2017-08-31")
        self.assertAlmostEqual(
            sum(-self.fin["capex_net_usd_m"][ends.index(e)] for e in fiscal_2017),
            5130.0, delta=10.0,
            msg="the four quarters must sum to the $5.13 billion the FY2017 10-K prints")

    def test_revenue_by_technology_sums_to_revenue(self) -> None:
        """DRAM + NAND + other equals the income statement, to the dollar.

        These three are filed dollar lines in the 10-Q revenue note, not
        percentages multiplied back out by this page. Asserting the sum is what
        makes that claim checkable: a percentage-derived series would miss by
        rounding in most quarters.
        """
        tech = self.staging["technology"]
        # The technology split has no quarters list of its own -- it aligns to
        # `periods` positionally, so extending the record to 2016 required
        # padding it with leading nulls. Getting that padding wrong would shift
        # every quarter's DRAM/NAND mix onto a different quarter without any
        # error, so this test both skips the pad and asserts how long it is.
        checked = 0
        for index, period in enumerate(self.periods):
            if tech["dram_revenue_usd_m"][index] is None:
                continue
            checked += 1
            with self.subTest(period=period):
                self.assertAlmostEqual(
                    tech["dram_revenue_usd_m"][index] + tech["nand_revenue_usd_m"][index]
                    + tech["other_revenue_usd_m"][index],
                    self.fin["revenue_usd_m"][index], places=6)
                self.assertAlmostEqual(
                    tech["dram_revenue_usd_m"][index] / self.fin["revenue_usd_m"][index] * 100,
                    tech["dram_share_pct"][index], places=1)
        pad = len(self.periods) - checked
        # The pad is history and does not move with a roll: the split starts
        # at Q4 2021, the 24th quarter of the record.
        self.assertEqual(pad, 23)
        self.assertEqual(self.periods[pad], FULL_STATEMENT_FROM)
        self.assertTrue(all(v is None for v in tech["dram_revenue_usd_m"][:pad]))
        self.assertTrue(all(v is not None for v in tech["dram_revenue_usd_m"][pad:]))

    def test_business_units_sum_to_revenue_within_the_all_other_line(self) -> None:
        """The four units plus `All other` are the whole company.

        `All other` is a few million dollars and is not carried as a series, so
        this asserts the residual is small AND positive rather than asserting a
        zero it cannot reach -- a residual that changed sign would mean a unit
        was being read from the wrong column.
        """
        units = self.staging["business_units"]
        by_period = dict(zip(self.periods, range(len(self.periods))))
        for index, quarter in enumerate(units["quarters"]):
            total = sum(units[f"{unit}_revenue_usd_m"][index]
                        for unit in ("CMBU", "CDBU", "MCBU", "AEBU"))
            revenue = self.fin["revenue_usd_m"][by_period[quarter]]
            with self.subTest(quarter=quarter):
                self.assertGreaterEqual(revenue - total, 0)
                self.assertLess(revenue - total, 25)

    def test_the_other_operating_line_is_published_only_as_a_total(self) -> None:
        """Its split is not stable across releases, so only the total is safe.

        Consecutive releases disagree about a single quarter's `Other operating
        (income) expense, net` by up to US$38M, because the same money moves
        between that caption and `Restructure and asset impairments` between
        eras. The total is identical in every reading. This pins the decision so
        a later pass cannot reintroduce the unstable line without going red.
        """
        self.assertIn("other_operating_total_usd_m", self.fin)
        for name in self.fin:
            self.assertNotIn("restructure", name)
            self.assertFalse(name.startswith("other_operating_")
                             and name != "other_operating_total_usd_m", name)

    def test_working_capital_days_use_the_filed_quarter_length(self) -> None:
        """DSO on revenue, DIO on cost of goods sold -- and never the reverse.

        Selling prices multiplied across this window while unit costs barely
        moved, so measuring inventory against revenue would show days-on-hand
        halving for reasons that have nothing to do with inventory. The day
        count is the difference of two filed period-end dates, not 91 assumed.
        """
        from datetime import date
        ends = [date.fromisoformat(value) for value in self.staging["period_ends"]]
        # DIO needs cost of goods sold, which Micron stopped printing between
        # FQ4-17 and FQ3-21, so it is checkable on far fewer quarters than DSO.
        # Both counts are asserted: without them, "every quarter holds" would
        # also be true of a record where almost nothing was checkable.
        dso_checked = dio_checked = 0
        for index, period in enumerate(self.periods):
            days = self.bal["days_in_quarter"][index]
            if days is None:
                continue
            with self.subTest(period=period):
                if index:
                    self.assertEqual(days, (ends[index] - ends[index - 1]).days)
                self.assertIn(days, (91, 98))
                if self.bal["dso_days"][index] is not None:
                    dso_checked += 1
                    self.assertAlmostEqual(
                        self.bal["receivables_usd_m"][index]
                        / self.fin["revenue_usd_m"][index] * days,
                        self.bal["dso_days"][index], places=2)
                if (self.bal["dio_days"][index] is not None
                        and self.fin["cost_of_goods_sold_usd_m"][index] is not None):
                    dio_checked += 1
                    self.assertAlmostEqual(
                        self.bal["inventories_usd_m"][index]
                        / self.fin["cost_of_goods_sold_usd_m"][index] * days,
                        self.bal["dio_days"][index], places=2)
        # DSO runs from the second quarter on; DIO shares the COGS hole, with
        # five early quarters and everything from Q4 2021.
        self.assertEqual(dso_checked, len(self.periods) - 1)
        self.assertEqual(dio_checked,
                         5 + len(self.periods) - self.periods.index(FULL_STATEMENT_FROM))

    def test_the_annual_cycle_covers_a_full_swing_in_both_directions(self) -> None:
        """The long series is the page's whole argument; assert it is really long.

        Fifteen fiscal years, at least one with a negative gross margin and one
        above 55%. Written as a shape rather than as two remembered numbers so
        it survives the next 10-K, but it goes red if the window is ever
        silently truncated to the recent up-leg -- which is the one edit that
        would turn this page into the opposite of what it says.
        """
        annual = self.staging["annual_cycle"]
        self.assertGreaterEqual(len(annual), 15)
        margins = [row["gross_margin_pct"] for row in annual]
        self.assertTrue(any(value < 0 for value in margins),
                        "the annual record must still contain a loss-making year")
        self.assertTrue(any(value > 55 for value in margins))
        for row in annual:
            self.assertAlmostEqual(
                row["capital_expenditures_usd_m"] / row["revenue_usd_m"] * 100,
                row["capex_intensity_pct"], places=2)
            self.assertAlmostEqual(
                row["gross_margin_usd_m"] / row["revenue_usd_m"] * 100,
                row["gross_margin_pct"], places=2)


class MuGuidanceRecordTest(unittest.TestCase):
    """The guided record, and the tallies the charts print from it."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(mu.STAGING_PATH.read_text(encoding="utf-8"))
        cls.record = cls.staging["quarterly_guidance_history"]
        cls.payload = mu.build_payload(cls.staging)
        cls.exhibits = [exhibit for section in cls.payload["sections"]
                        for exhibit in section["exhibits"]]

    def bands(self, key: str):
        mids = self.record[key]
        widths = self.record[f"{key}_band"]
        points = self.record[f"{key}_is_point"]
        low = [None if m is None else (m if p else m - (w or 0))
               for m, w, p in zip(mids, widths, points)]
        high = [None if m is None else (m if p else m + (w or 0))
                for m, w, p in zip(mids, widths, points)]
        return low, high

    def test_every_guided_quarter_carries_every_field(self) -> None:
        width = len(self.record["quarters"])
        for name, values in self.record.items():
            if not isinstance(values, list):
                continue
            with self.subTest(series=name):
                self.assertEqual(len(values), width, name)

    def test_the_guidance_lands_inside_the_quarter_it_guides(self) -> None:
        """The record is not ex-ante, and every chart in section one says so.

        Micron reports about four weeks after a quarter ends and guides the
        quarter already running, so a hit rate here means something weaker than
        one measured on a forecast published before the period began. The charts
        state the range; this pins that the range is real, and that the caveat
        text on the charts still matches it.
        """
        lags = self.record["publication_lag_days"]
        self.assertTrue(all(value > 0 for value in lags))
        self.assertGreaterEqual(min(lags), 15)
        self.assertLessEqual(max(lags), 40)
        note = next(exhibit["note"] for exhibit in self.exhibits
                    if exhibit.get("kind") == "range_band")
        self.assertIn(f"第 {min(lags)} 天", note)
        self.assertIn(f"第 {max(lags)} 天", note)

    # Every phrase on this page that counts quarters against a guided band.
    # The prose deliberately varies -- `delivery_band` writes 超出上限 in a
    # title while the hand-written note beside it says 穿出上限 -- so the check
    # is keyed on the meaning, not on one spelling.
    ABOVE = ("超出上限", "穿出上限", "高于指引区间上限", "高于指引上限")
    INSIDE = ("落在区间内",)
    BELOW = ("跌破下限",)

    def tally(self, key: str, actual_key: str, scope: int | None = None):
        """(above, inside, below) over the LAST `scope` finished quarters.

        Scope matters because two charts here are deliberately drawn over a
        short window while their notes describe the whole record, so the same
        chart legitimately prints two different tallies of the same metric.
        Both are recounted; what must never happen is a number that matches
        neither.
        """
        low, high = self.bands(key)
        actual = self.record[actual_key]
        done = [i for i, value in enumerate(actual) if value is not None]
        if scope is not None:
            done = done[-scope:]
        above = sum(1 for i in done if actual[i] > high[i])
        below = sum(1 for i in done if actual[i] < low[i])
        return above, len(done) - above - below, below

    def test_every_tally_printed_on_a_chart_recounts_from_the_series(self) -> None:
        """A tally is the one thing on a chart a reader cannot check.

        The first version of this compared only the *title* that
        `delivery_band` generates -- and a mutation that made the same tally
        wrong in the *note* underneath it left the suite green, because the two
        sentences count the same thing in different words and only one was being
        read. So this scans title AND note, and it reads each sentence's own
        stated scope ("11 个已完结季里 ...", "27 季有 ...") rather than assuming
        every tally covers the whole record: the revenue and earnings charts are
        drawn over the last twelve quarters while their notes describe all
        twenty-seven, so a check that assumed one scope would either miss half
        the numbers or false-fail on the other half.
        """
        metrics = {
            "收入": ("guide_non_gaap_revenue_usd_m", "actual_revenue_usd_m"),
            "non-GAAP 毛利率": ("guide_non_gaap_gross_margin_pct",
                                "actual_non_gaap_gross_margin_pct"),
            "non-GAAP 每股收益": ("guide_non_gaap_eps_usd", "actual_non_gaap_eps_usd"),
        }
        markers = {**{word: 0 for word in self.ABOVE},
                   **{word: 1 for word in self.INSIDE},
                   **{word: 2 for word in self.BELOW}}
        # A scope marker is a quarter COUNT that is not itself a verdict --
        # keyed on that rather than on the particles that happened to follow it
        # in the sentences written first. Pinning `季里|季有` silently skipped
        # `同样 27 季，收入指引 ...`, so the brief's revenue tally went unread
        # and a mutation of it stayed green. The wording of prose is not a
        # stable key; "is this number followed by a verdict?" is.
        verdicts = "|".join(markers)
        scope_re = re.compile(r"(\d+)\s*(?:个已完结)?季(?!\s*(?:" + verdicts + "))")
        mark_re = re.compile(r"(\d+)\s*季\s*(" + "|".join(markers) + ")")

        # The `brief` prints the same tallies in its own words. It was hand-typed
        # prose beside computed charts until this test reached it, which is the
        # same shape as the note the gate had not been reading -- one layer up.
        blocks = [(name, [exhibit["title"], exhibit.get("note", "")])
                  for exhibit in self.exhibits
                  for name in metrics if exhibit["title"].startswith(name)]
        brief = self.payload["brief"]
        # The brief states two tallies in two sentences, so it is split and each
        # sentence attributed by the metric it names -- scanning the whole block
        # against one metric would compare the revenue counts to the margin ones
        # and fail for a reason that has nothing to do with either.
        for sentence in re.split(r"[。]", re.sub(r"<[^>]+>", " ", brief)):
            for name in metrics:
                if name in sentence or (name == "收入" and "收入指引" in sentence):
                    blocks.append((name, [sentence]))
                    break

        seen = 0
        for metric, texts in blocks:
            keys = metrics[metric]
            for text in texts:
                # Split into sentences that each declare their own scope.
                bounds = [match for match in scope_re.finditer(text)]
                for position, match in enumerate(bounds):
                    scope = int(match.group(1))
                    stop = (bounds[position + 1].start()
                            if position + 1 < len(bounds) else len(text))
                    counts = self.tally(*keys, scope=scope)
                    self.assertEqual(sum(counts), scope,
                                     f"{metric}: a scope of {scope} finished quarters "
                                     "is longer than the record")
                    for number, marker in mark_re.findall(text[match.end():stop]):
                        seen += 1
                        with self.subTest(metric=metric, scope=scope, marker=marker):
                            self.assertEqual(
                                int(number), counts[markers[marker]],
                                f"{metric} over {scope} quarters: chart says "
                                f"{number} 季{marker}, the series says "
                                f"{counts[markers[marker]]}")
        self.assertGreaterEqual(seen, 12, "the tally phrases stopped being found")
        self.assertGreaterEqual(
            sum(1 for _, texts in blocks if texts and texts[0] in
                re.sub(r"<[^>]+>", " ", brief)), 2,
            "the brief no longer states the tallies this test can check")
        self.assertGreater(self.tally(*metrics["non-GAAP 毛利率"])[2], 0,
                           "this page exists because the record is two-sided")

    def test_the_worst_quarter_named_in_the_headline_is_the_worst_quarter(self) -> None:
        """The headline names one quarter out of twenty-seven; recount which.

        It was originally pinned by list index, which is right until the record
        grows at the front and then silently names a different quarter with a
        real-looking pair of numbers beside it.
        """
        guided = self.record["guide_non_gaap_gross_margin_pct"]
        actual = self.record["actual_non_gaap_gross_margin_pct"]
        gaps = [(actual[i] - guided[i], i) for i, value in enumerate(actual)
                if value is not None]
        worst_gap, worst = min(gaps)
        self.assertLess(worst_gap, -30, "the worst miss is a forty-point one")
        self.assertIn(f"{guided[worst]:.1f}%", self.payload["headline"])
        self.assertIn(f"{actual[worst]:.1f}%", self.payload["headline"])

    def test_the_three_legs_reproduce_the_distance_from_implied_operating_income(self) -> None:
        """The decomposition claims to be exact, so assert that it is.

        implied non-GAAP operating income = guided revenue x guided margin -
        guided opex, and actual minus implied splits into a revenue leg, a
        margin leg and an expense leg with no residual. If it were an
        approximation the chart would have to say so; it says it is an identity.
        """
        legs = next(exhibit for exhibit in self.exhibits
                    if exhibit.get("kind") == "grouped_bars"
                    and exhibit["title"].startswith("把「超出自身指引」"))
        names = [group["name"] for group in legs["groups"]]
        self.assertEqual(names, ["收入腿", "毛利率腿", "费用腿"])
        revenue_leg, margin_leg, opex_leg = (group["values"] for group in legs["groups"])

        guided_revenue = self.record["guide_non_gaap_revenue_usd_m"]
        guided_margin = self.record["guide_non_gaap_gross_margin_pct"]
        guided_opex = self.record["guide_non_gaap_opex_usd_m"]
        actual_revenue = self.record["actual_revenue_usd_m"]
        actual_margin = self.record["actual_non_gaap_gross_margin_pct"]
        actual_opex = self.record["actual_non_gaap_opex_usd_m"]
        actual_income = self.record["actual_non_gaap_operating_income_usd_m"]

        drawn = [i for i, value in enumerate(actual_revenue)
                 if value is not None and actual_opex[i] is not None]
        self.assertEqual(len(drawn), len(revenue_leg))
        for position, index in enumerate(drawn):
            implied = (guided_revenue[index] * guided_margin[index] / 100
                       - guided_opex[index]) / 1000
            with self.subTest(quarter=self.record["quarters"][index]):
                # `places=4` is US$100k on figures in US$B: the payload rounds
                # each leg to six decimals of a billion, so a tighter tolerance
                # would be asserting the rounding rather than the identity.
                self.assertAlmostEqual(
                    revenue_leg[position] + margin_leg[position] + opex_leg[position],
                    actual_income[index] / 1000 - implied, places=4)


class MuExhibitContractTest(unittest.TestCase):
    """What each chart promises its own axis."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(mu.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = mu.build_payload(cls.staging)
        cls.exhibits = [exhibit for section in cls.payload["sections"]
                        for exhibit in section["exhibits"]]

    def test_every_bridge_column_has_something_drawn_in_it(self) -> None:
        """Per column, not in aggregate -- and the aggregate version was green
        while the chart was broken.

        Two separate ways a bridge column ends up labelled and empty, both live
        on this page at some point:

        1. **A leg worth exactly zero.** `charts.js` runs
           `if (!isNum(vb) || vb === 0) continue`, so a zero-valued segment
           draws nothing while its label stays. The diluted share count did not
           move between these two quarters, so that leg was exactly zero.
        2. **`net` passed as a bare list.** `bridgeNet` starts
           `if (ex.net && ex.net.values) return ex.net.values` -- a list is
           truthy but `.values` is `undefined`, so it falls through to the
           branch that sums the stacks. The result column has no stack segment
           (its whole value IS the net), the sum is null, and the diamond is
           never drawn. The title still names the number.

        The first version of this test counted marks against columns **in
        total**: 4 stack segments + 1 net = 5 promised, 5 filled elements found,
        green -- while the fifth element was somewhere else entirely and the
        result column was empty. An aggregate is satisfied by a mark in the
        wrong place, which is the same mistake as counting SVGs instead of
        checking each chart. So this walks the columns.
        """
        for exhibit in self.exhibits:
            if exhibit.get("kind") != "bridge_bar":
                continue
            net = exhibit.get("net")
            # The shape, asserted directly: this is the mechanism, and it is
            # invisible in the rendered output until you look column by column.
            self.assertIsInstance(
                net, dict,
                "bridge `net` must be {'name': ..., 'values': [...]}; a bare "
                "list is truthy at `ex.net &&` and undefined at `.values`, so "
                "the renderer silently ignores it")
            self.assertIn("values", net)
            self.assertIn("name", net)
            width = len(exhibit["xlabels"])
            self.assertEqual(len(net["values"]), width)
            for column, label in enumerate(exhibit["xlabels"]):
                segments = [stack["values"][column] for stack in exhibit["stacks"]]
                drawn = any(value is not None and round(value, 2) != 0
                            for value in segments)
                netted = net["values"][column] is not None
                with self.subTest(column=label):
                    self.assertTrue(
                        drawn or netted,
                        f"column {column} is labelled {label!r} and has neither a "
                        "non-zero stack segment nor a net value: the renderer "
                        "draws nothing there")

    def test_the_bridge_adds_up_to_the_quarter_it_names(self) -> None:
        exhibit = next(e for e in self.exhibits if e.get("kind") == "bridge_bar")
        legs = [value for value in exhibit["stacks"][0]["values"] if value is not None]
        result = next(value for value in exhibit["net"]["values"] if value is not None)
        self.assertAlmostEqual(sum(legs), result, places=2)
        fin = self.staging["financials"]
        self.assertAlmostEqual(result, fin["non_gaap_diluted_eps_usd"][-1], places=6)
        self.assertAlmostEqual(legs[0], fin["non_gaap_diluted_eps_usd"][-2], places=6)

    def test_every_share_line_on_a_dual_axis_declares_its_ceiling(self) -> None:
        """`stacked_dual` hardcodes the right axis to `ticks(0, ymax || 60, 6)`.

        It never looks at the data, so a percentage line above 60 is drawn at a
        negative y and clipped by the browser without a word while the legend
        goes on naming it. Every number in the payload stays finite, so the
        payload guard, the render gate's NaN scan and the build's drift check
        are all blind to it -- `ibkr` Exhibit 8 shipped that way for a long time.
        """
        for exhibit in self.exhibits:
            if exhibit.get("kind") != "stacked_dual":
                continue
            line = exhibit.get("line") or {}
            self.assertIn("ymax", line, exhibit["title"])
            self.assertGreaterEqual(line["ymax"], max(line["values"]))

    def test_this_page_publishes_no_gs_bar(self) -> None:
        """Stated out loud, because its absence is load-bearing elsewhere.

        `test_chart_contract.py` pins a census of every `gs_bar` on the site and
        asserts that exactly one carries neither a `yoy` block nor an `avg12`.
        That census is the evidence for the claim that the `avg12` branch has
        never been exercised by real data, which is in turn the reason several
        guards around it are believed to hold. This page adds none, so the
        census is unchanged -- and adding one later should be a deliberate act
        that starts by turning this red.
        """
        kinds = {exhibit.get("kind") for exhibit in self.exhibits}
        self.assertNotIn("gs_bar", kinds)
        self.assertNotIn("avg12", json.dumps(self.payload))

    def test_no_exhibit_reaches_a_renderer_branch_nothing_else_reaches(self) -> None:
        """Adding one is fine; doing it unnoticed is not.

        `UNEXERCISED_KINDS` in `test_chart_contract.py` lists the branches no
        published payload reaches. Lighting one up from here would turn that
        test red with a message about the site rather than about this page, so
        this says it locally first.
        """
        from tests.test_chart_contract import UNEXERCISED_KINDS
        for exhibit in self.exhibits:
            self.assertNotIn(exhibit.get("kind"), UNEXERCISED_KINDS, exhibit["title"])

    def test_the_threshold_table_round_trips_its_own_headroom(self) -> None:
        table = next(item for item in self.payload["tables"]
                     if item["title"].startswith("下季阈值"))
        quantified = self.staging["next_kpi"]["quantified"]
        charted = [row for row in table["rows"] if row[5].startswith("作图")]
        self.assertEqual(len(charted), len(quantified))
        fin, bal = self.staging["financials"], self.staging["balance_sheet"]
        readings = {"gross_margin": fin["non_gaap_gross_margin_pct"][-1],
                    "dso": bal["dso_days"][-1]}
        numbers = {exhibit["n"]: exhibit for exhibit in self.exhibits}
        for row, entry in zip(charted, quantified):
            self.assertEqual(row[0], entry["metric"])
            self.assertEqual(
                row[4],
                f"{headroom(entry['direction'], entry['threshold'], readings[entry['id']]):+.1f}%")
            drawn = int(re.search(r"Exhibit (\d+)", row[5]).group(1))
            self.assertTrue(numbers[drawn]["title"].startswith(entry["metric"] + "："),
                            "the row names the wrong chart")
        excluded = [row for row in table["rows"] if not row[5].startswith("作图")]
        self.assertEqual(len(excluded), len(self.staging["next_kpi"]["excluded"]))

    def test_the_quarter_end_and_all_signed_agreement_figures_stay_apart(self) -> None:
        """The page's most easily blurred distinction, pinned.

        The supply agreements are US$5.0B of remaining performance obligation in
        the 10-Q's note and US$100B in the prepared remarks; US$0.422B of
        contract liabilities in the note and US$22B of expected deposits and
        commitments. Publishing either side alone misleads, and publishing their
        difference would invent a number neither source states.

        It used to be pinned as "filed versus spoken", with the right-hand side
        asserted to carry no 10-Q -- and the US$22B deposit figure is printed in
        that same 10-Q's liquidity section. The real split is quarter end versus
        every agreement signed to date, and each right-hand figure names its own
        source, which is what is asserted now.
        """
        exhibit = next(e for e in self.exhibits
                       if e["title"].startswith("长期供货协议"))
        quarter_end, all_signed = exhibit["groups"]
        self.assertIn("10-Q", quarter_end["name"])
        self.assertIn("季末", quarter_end["name"])
        self.assertIn("季末后", all_signed["name"])
        items = self.staging["supply_agreements"]["items"]
        self.assertNotIn("filed_vs_spoken", self.staging)
        for index, item in enumerate(items):
            with self.subTest(item=item["metric"]):
                self.assertAlmostEqual(quarter_end["values"][index],
                                       item["quarter_end_usd_m"] / 1000, places=6)
                self.assertAlmostEqual(all_signed["values"][index],
                                       item["company_usd_m"] / 1000, places=6)
                self.assertIn("10-Q", item["quarter_end_source"])
                self.assertIn(item["company_source"], exhibit["src_extra"])
                self.assertLess(item["quarter_end_usd_m"], item["company_usd_m"])
        deposits = next(item for item in items if "存款" in item["metric"])
        self.assertIn("10-Q", deposits["company_source"])

    def test_no_number_in_the_payload_came_from_a_qualitative_bucket(self) -> None:
        """Micron states price and volume only in words; the page keeps them words.

        The bucket-to-midpoint mapping ("low-60% range" -> 62) exists in the
        harvest and is deliberately not carried into the series: a midpoint is
        an assumption wearing the clothes of a measurement. The wording is
        published verbatim in the audit table instead, so this asserts that the
        text survived and that no numeric twin of it did.
        """
        technology = self.staging["technology"]
        self.assertTrue(any("range" in (text or "")
                            for text in technology["dram_asp_text"]))
        for name in technology:
            self.assertFalse(name.endswith("_midpoint_pct"), name)
            self.assertFalse(name.endswith("_asp_qoq_pct"), name)
            self.assertFalse(name.endswith("_bit_qoq_pct"), name)
        table = next(item for item in self.payload["tables"]
                     if "公司对价与量的原始措辞" in item["title"])
        self.assertTrue(any("range" in cell for row in table["rows"] for cell in row))


class MuFourPartFormatTest(unittest.TestCase):
    """The site-wide four-part layout (TSM is the reference), by id and title."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(mu.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = mu.build_payload(cls.staging)
        cls.sections = {section["id"]: section for section in cls.payload["sections"]}

    def test_the_sections_are_the_four_parts_in_order(self) -> None:
        self.assertEqual(
            [(section["id"], section["title"]) for section in self.payload["sections"]],
            [("settled", "一、上季跟踪指标兑现了吗"),
             ("quarter_highlights", "二、本季重点"),
             ("next_quarter", "三、下季要跟踪什么"),
             ("routine", "四、长期常规跟踪")])
        for section in self.payload["sections"]:
            with self.subTest(section=section["id"]):
                self.assertTrue(section["exhibits"])
        self.assertIn("本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列",
                      self.payload["notes"][0])

    def test_the_quarter_findings_are_not_filed_under_next_quarter(self) -> None:
        """The supply agreements and the net-cash chart are this quarter's
        findings, not thresholds; they sat in section three until the format
        pass, which made that section promise more tracking than it has."""
        highlight = [exhibit["title"] for exhibit in self.sections["quarter_highlights"]["exhibits"]]
        tracked = [exhibit["title"] for exhibit in self.sections["next_quarter"]["exhibits"]]
        for word in ("长期供货协议", "净现金"):
            with self.subTest(chart=word):
                self.assertTrue(any(word in title for title in highlight))
                self.assertFalse(any(word in title for title in tracked))
        # Section three is thresholds only: an overview and one line per level.
        for exhibit in self.sections["next_quarter"]["exhibits"]:
            with self.subTest(chart=exhibit["title"]):
                self.assertTrue(exhibit["title"].startswith("下季 ") or "：下季阈值 " in exhibit["title"],
                                exhibit["title"])


class MuSettlementTest(unittest.TestCase):
    """Section one settles what the owner's previous analysis left for this quarter.

    Pinned against the two analyses, not against the builder. What the
    analyses say -- how many questions, which verdict each got, where each line
    was drawn -- is transcribed a second time into `_checks["note"]` in the
    series file, independently of the blocks the builder reads (the builder
    never reads `_checks`). Every reading those lines are settled against is
    recomputed here from the arrays, never read back from the builder's helpers.
    Rolling a quarter re-keys `_checks`; this file does not change.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(mu.STAGING_PATH.read_text(encoding="utf-8"))
        cls.note = cls.staging["_checks"]["note"]
        cls.payload = mu.build_payload(cls.staging)
        cls.settled = cls.payload["sections"][0]["exhibits"]
        cls.period = cls.staging["periods"][-1]

    def test_the_blocks_settle_last_quarter_for_this_quarter(self) -> None:
        self.assertEqual(self.staging["_checks"]["period"], self.period)
        for key in ("followup_closure", "prior_kpi_settlement"):
            with self.subTest(block=key):
                self.assertEqual(self.staging[key]["period"], self.period)
                self.assertEqual(self.staging[key]["set_in"], self.staging["periods"][-2])
        stale = json.loads(json.dumps(self.staging))
        stale["prior_kpi_settlement"]["set_in"] = self.staging["periods"][-3]
        with self.assertRaisesRegex(ValueError, "settles what was set in"):
            mu.build_payload(stale)

    def test_the_closure_counts_are_the_analysis_verdicts(self) -> None:
        expected = self.note["followup_closure"]
        chart = self.settled[0]
        self.assertEqual(chart["kind"], "bars_labeled")
        self.assertEqual(dict(zip(chart["xlabels"], chart["values"])), expected["counts"])
        self.assertEqual(sum(chart["values"]), expected["total"])
        counts = expected["counts"]
        self.assertTrue(chart["title"].startswith(
            f"上季 {expected['total']} 条待验证问题：{counts['已验证']} 条已验证、"
            f"{counts['部分验证']} 条部分验证"), chart["title"])
        self.assertEqual(len(self.staging["followup_closure"]["items"]), expected["total"])
        table = next(item for item in self.payload["tables"]
                     if item["title"].startswith("上季") and "待验证问题" in item["title"])
        self.assertEqual([row[3] for row in table["rows"]],
                         [item["verdict"] for item in self.staging["followup_closure"]["items"]])
        for row in table["rows"]:
            self.assertNotIn("{", "".join(row), "an unfilled placeholder was published")

    def test_the_prior_thresholds_are_the_analysis_section_eight(self) -> None:
        expected = {item["metric"]: item for item in self.note["prior_thresholds"]}
        block = self.staging["prior_kpi_settlement"]
        entries = block["quantified"] + block["by_words"] + block["unsettled"]
        self.assertEqual(sorted(entry["metric"] for entry in entries), sorted(expected))
        for entry in block["quantified"]:
            with self.subTest(metric=entry["metric"]):
                self.assertEqual((entry["direction"], entry["threshold"]),
                                 (expected[entry["metric"]]["direction"],
                                  expected[entry["metric"]]["threshold"]))
        for entry in block["by_words"]:
            line = expected[entry["metric"]]
            with self.subTest(metric=entry["metric"]):
                # The verdict is recorded in the series, not decided in code, so
                # it is checked against the second transcription in `_checks`.
                self.assertEqual(entry["settled_by_wording"]["verdict"], line["verdict"])
                if "threshold" in entry:
                    self.assertEqual((entry["direction"], entry["threshold"]),
                                     (line["direction"], line["threshold"]))
        # 「当前 1 份」: the analysis's own count, supplied as a named story value.
        self.assertEqual(block["story_values"]["sca_prior"],
                         str(expected["第二份长期供货协议"]["threshold"]))
        # No reading is typed into the block: every one is computed.
        for group in ("quantified", "by_words"):
            for entry in block[group]:
                self.assertNotIn("actual", entry)
                self.assertNotIn("current", entry)

    def test_the_settlement_readings_recompute_from_the_arrays(self) -> None:
        fin = self.staging["financials"]
        readings = {
            "本季收入": fin["revenue_usd_m"][-1] / 1000,
            "本季 non-GAAP 毛利率": fin["non_gaap_gross_margin_pct"][-1],
            "下季收入指引中值": self.staging["next_quarter_guidance"]["revenue_usd_m"] / 1000,
        }
        expected = {item["metric"]: item for item in self.note["prior_thresholds"]}
        chart = self.settled[1]
        self.assertEqual(chart["kind"], "diverging_bars")
        self.assertEqual(sorted(chart["xlabels"]), sorted(readings))
        margins = []
        for metric, drawn in zip(chart["xlabels"], chart["values"]):
            line = expected[metric]
            sign = 1 if line["direction"] == "up" else -1
            margin = sign * (readings[metric] - line["threshold"]) / abs(line["threshold"]) * 100
            margins.append(margin)
            with self.subTest(metric=metric):
                self.assertAlmostEqual(drawn, margin, delta=0.051)
        # The guide line had a second trigger, a guided sequential decline.
        self.assertGreater(readings["下季收入指引中值"] * 1000, fin["revenue_usd_m"][-1])
        self.assertEqual(all(margin >= 0 for margin in margins), "全部守住" in chart["title"])
        self.assertTrue(chart["title"].startswith(f"上季 {len(readings)} 条量化阈值："))
        # The one line crossed this quarter is settled by the company's words:
        # "higher than the mid-40s" (US$B) against the analysis's ceiling.
        capex = expected["FY27 资本开支"]
        self.assertGreaterEqual(self.staging["spoken_outlook"]["capex_floor_usd_bn"], capex["threshold"])
        self.assertIn("FY27 资本开支按公司措辞已越过", chart["title"])
        self.assertNotIn("FY27 资本开支", chart["xlabels"])

    def test_every_prior_level_with_a_history_is_drawn_against_its_line(self) -> None:
        fin = self.staging["financials"]
        expected = {item["metric"]: item for item in self.note["prior_thresholds"]}
        lines = {exhibit["title"].split("：")[0]: exhibit for exhibit in self.settled
                 if exhibit["kind"] == "lines" and "上季阈值" in exhibit["title"]}
        histories = {"本季收入": [v / 1000 for v in fin["revenue_usd_m"]],
                     "本季 non-GAAP 毛利率": fin["non_gaap_gross_margin_pct"]}
        self.assertEqual(sorted(lines), sorted(histories))
        for name, series in histories.items():
            chart = lines[name]
            line = expected[name]
            sign = 1 if line["direction"] == "up" else -1
            held = sign * (series[-1] - line["threshold"]) >= 0
            with self.subTest(chart=name):
                self.assertIn(f"：{'守住' if held else '已击穿'}上季阈值", chart["title"])
                actual, drawn_line = chart["series"]
                self.assertEqual(len(actual["values"]), len(self.staging["periods"]))
                for drawn, value in zip(actual["values"], series):
                    self.assertAlmostEqual(drawn, value, places=5)
                self.assertEqual(set(drawn_line["values"]), {line["threshold"]})

    def test_next_quarters_levels_settle_with_a_series_edit_only(self) -> None:
        """What section three sets this quarter, section one settles next quarter.

        The owner's rule is that a roll edits the series file only, so both of
        this quarter's levels must already be mapped in the settlement code. The
        blocks are rolled here the way a roll would roll them -- next_kpi's lines
        copied into prior_kpi_settlement -- and the page must settle them.
        """
        rolled = json.loads(json.dumps(self.staging))
        rolled["prior_kpi_settlement"]["quantified"] = [
            dict(entry) for entry in self.staging["next_kpi"]["quantified"]]
        section = mu.build_payload(rolled)["sections"][0]
        titles = [exhibit["title"] for exhibit in section["exhibits"]]
        for entry in self.staging["next_kpi"]["quantified"]:
            with self.subTest(metric=entry["metric"]):
                self.assertTrue(any(title.startswith(entry["metric"] + "：") and "上季阈值" in title
                                    for title in titles), titles)
        self.assertEqual(re.findall(r"\{[a-z_]+\}", json.dumps(section, ensure_ascii=False)), [],
                         "a placeholder was left unfilled")

    def test_a_new_worded_line_settles_with_a_series_edit_only(self) -> None:
        """A kind of worded line no code has seen must build from the series alone.

        The verdicts of the lines that only the company's words can settle used
        to be decided in the builder, in a table keyed by metric, so a new one
        needed a code edit on a roll. They now live in each entry's
        `settled_by_wording`; this adds an entry nothing maps and checks the page
        prints its verdict and the company's words, and that a verdict outside
        the vocabulary stops the build instead of printing.
        """
        rolled = json.loads(json.dumps(self.staging))
        rolled["prior_kpi_settlement"]["by_words"].append({
            "id": "hbm_majority_new",
            "metric": "HBM4 占 HBM 出货",
            "rule": "本季仍未过半即警示",
            "why_not_charted": "公司只给了措辞，没有给占比",
            "settled_by_wording": {"verdict": "已越线",
                                   "quote": "the majority of our HBM shipments",
                                   "source": "某季业绩电话会书面发言稿"},
        })
        section = mu.build_payload(rolled)["sections"][0]
        overview = next(e for e in section["exhibits"] if e["kind"] == "diverging_bars")
        self.assertIn("HBM4 占 HBM 出货按公司措辞已越线", overview["title"])
        self.assertIn("「the majority of our HBM shipments」，<b>已越线</b>", overview["note"])
        self.assertIn("HBM4 占 HBM 出货</b>（本季仍未过半即警示）", overview["note"])
        self.assertNotIn("HBM4 占 HBM 出货", overview["xlabels"])
        rolled["prior_kpi_settlement"]["by_words"][-1]["settled_by_wording"]["verdict"] = "大概越线"
        with self.assertRaisesRegex(ValueError, "verdict"):
            mu.build_payload(rolled)

    def test_section_one_is_closure_then_thresholds_then_the_guided_record(self) -> None:
        kinds = [exhibit["kind"] for exhibit in self.settled]
        self.assertEqual(kinds[:4], ["bars_labeled", "diverging_bars", "lines", "lines"])
        self.assertEqual(kinds[4], "range_band")
        self.assertTrue(all(kind not in ("bars_labeled", "diverging_bars") for kind in kinds[4:]))


class MuNextQuarterTest(unittest.TestCase):
    """Section three is this quarter's analysis's section 8, and nothing else."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(mu.STAGING_PATH.read_text(encoding="utf-8"))
        cls.note = cls.staging["_checks"]["note"]
        cls.payload = mu.build_payload(cls.staging)
        cls.tracked = cls.payload["sections"][2]["exhibits"]

    def current(self, metric: str) -> float:
        """Where a line stands now, recomputed here from the arrays."""
        if metric == "non-GAAP 毛利率":
            return self.staging["financials"]["non_gaap_gross_margin_pct"][-1]
        if metric.startswith("应收账款周转天数"):
            bal = self.staging["balance_sheet"]
            return (bal["receivables_usd_m"][-1] / self.staging["financials"]["revenue_usd_m"][-1]
                    * bal["days_in_quarter"][-1])
        raise KeyError(metric)

    def test_the_block_is_stamped_for_the_quarter_it_tracks(self) -> None:
        block = self.staging["next_kpi"]
        self.assertEqual(block["period"], self.staging["periods"][-1])
        self.assertEqual(block["for_period"], self.staging["next_quarter_guidance"]["period_label"])
        stale = json.loads(json.dumps(self.staging))
        stale["next_kpi"]["period"] = self.staging["periods"][-2]
        with self.assertRaisesRegex(ValueError, "stamped"):
            mu.build_payload(stale)

    def test_the_lines_are_the_analysis_section_eight(self) -> None:
        expected = self.note["next_thresholds"]
        block = self.staging["next_kpi"]
        self.assertEqual(len(block["quantified"]) + len(block["excluded"]), len(expected))
        by_metric = {item["metric"]: item for item in expected}
        self.assertEqual(sorted(entry["metric"] for entry in block["quantified"] + block["excluded"]),
                         sorted(by_metric))
        for entry in block["quantified"]:
            with self.subTest(metric=entry["metric"]):
                self.assertEqual((entry["direction"], entry["threshold"]),
                                 (by_metric[entry["metric"]]["direction"],
                                  by_metric[entry["metric"]]["threshold"]))
                self.assertNotIn("current", entry)

    def test_section_three_is_the_overview_then_one_line_per_level(self) -> None:
        block = self.staging["next_kpi"]
        overview, *lines = self.tracked
        self.assertEqual(overview["kind"], "diverging_bars")
        self.assertTrue(overview["title"].startswith(f"下季 {len(block['quantified'])} 条阈值："))
        expected = {item["metric"]: item for item in self.note["next_thresholds"]}
        for metric, drawn in zip(overview["xlabels"], overview["values"]):
            line = expected[metric]
            sign = 1 if line["direction"] == "up" else -1
            with self.subTest(metric=metric):
                self.assertAlmostEqual(
                    drawn, sign * (self.current(metric) - line["threshold"]) / line["threshold"] * 100,
                    delta=0.051)
        self.assertEqual([exhibit["kind"] for exhibit in lines], ["lines"] * len(block["quantified"]))
        for exhibit, entry in zip(lines, block["quantified"]):
            with self.subTest(chart=entry["metric"]):
                self.assertTrue(exhibit["title"].startswith(f"{entry['metric']}：下季阈值 "),
                                exhibit["title"])
                self.assertIn("，当前 ", exhibit["title"])
                self.assertEqual(set(exhibit["series"][1]["values"]), {entry["threshold"]})

    def test_every_line_not_drawn_says_why_in_the_drawer(self) -> None:
        """The table used to print the metric name beside 「原因见左」 with the
        reason cut off at the first bracket, so no reason was published."""
        table = next(item for item in self.payload["tables"] if item["title"].startswith("下季阈值"))
        block = self.staging["next_kpi"]
        self.assertEqual(len(table["rows"]), len(block["quantified"]) + len(block["excluded"]))
        for row in table["rows"]:
            with self.subTest(metric=row[0]):
                self.assertNotIn("原因见左", row[5])
                self.assertNotIn("{", "".join(row), "an unfilled placeholder was published")
                self.assertTrue(row[1], "the trigger is missing")
        excluded = [row for row in table["rows"] if row[5].startswith("不作图：")]
        self.assertEqual(len(excluded), len(block["excluded"]))
        for row in excluded:
            self.assertGreater(len(row[5]), len("不作图：") + 10)


class MuQuarterHighlightsTest(unittest.TestCase):
    """What section two added from this quarter's analysis, pinned to the arrays."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(mu.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = mu.build_payload(cls.staging)
        cls.highlights = cls.payload["sections"][1]["exhibits"]
        cls.exhibits = [exhibit for section in cls.payload["sections"]
                        for exhibit in section["exhibits"]]

    def test_the_guided_margin_step_stands_beside_the_steps_actually_taken(self) -> None:
        """The analysis reads this quarter as the price move's second derivative
        turning. The guided step is the one bar that is not an actual, so it is
        the hatched one, and it is the guide minus this quarter -- not a figure
        from the call."""
        margin = self.staging["financials"]["non_gaap_gross_margin_pct"]
        guide = self.staging["next_quarter_guidance"]["non_gaap_gross_margin_pct"]
        chart = next(e for e in self.highlights if e["title"].startswith("毛利率环比"))
        periods = len(self.staging["periods"])
        self.assertEqual(len(chart["xlabels"]), periods + 1)
        self.assertEqual(len(chart["values"]), periods + 1)
        self.assertEqual(chart["bar_marks"], [periods])
        self.assertTrue(chart["xlabels"][-1].endswith("指引"))
        self.assertIsNone(chart["values"][0])
        for index in range(1, periods):
            self.assertAlmostEqual(chart["values"][index], margin[index] - margin[index - 1], places=5)
        self.assertAlmostEqual(chart["values"][-1], guide - margin[-1], places=5)
        self.assertIn(f"下季指引只隐含 {guide - margin[-1]:+.1f}pp", chart["title"])

    def test_the_inventory_title_prints_the_company_days(self) -> None:
        """Official figures win: the prepared remarks say 120 days, this page's
        own arithmetic says 122, and the title used to print the 122."""
        chart = next(e for e in self.exhibits if e["title"].startswith("存货 US$"))
        stated = self.staging["_checks"]["days_of_inventory"]
        self.assertIn(f"存货天数 {stated} 天（公司口径）", chart["title"])
        computed = self.staging["balance_sheet"]["dio_days"][-1]
        caveat = f"现在是 {computed:.0f} 天（本页自算"
        if round(computed) != stated:
            self.assertIn(caveat, chart["note"])
        else:
            self.assertNotIn(caveat, chart["note"])


class MuPublishedArtefactTest(unittest.TestCase):
    """The files the site actually serves."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(mu.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = mu.build_payload(cls.staging)

    def test_published_payload_roster_and_shell(self) -> None:
        self.assertEqual(js_payload(ROOT / "data" / "mu.js", "window.DASH"), self.payload)
        roster = js_payload(ROOT / "data" / "roster.js", "window.ROSTER")
        self.assertEqual(roster, roster_payload(build_all()))
        entry = next(item for item in roster["items"] if item["slug"] == "mu")
        self.assertEqual(entry["latest_label"], self.payload["latest"]["disclosed_period_label"])
        self.assertEqual(entry["release_date"], self.payload["latest"]["release_date"])
        self.assertEqual(entry["group"], "semiconductor_ai")
        self.assertIn(entry["group"], {group["key"] for group in GROUPS})
        shell = (ROOT / "mu" / "index.html").read_text(encoding="utf-8")
        self.assertIn("../data/mu.js", shell)
        self.assertNotIn("../data/msft.js", shell)

    def test_shell_versions_every_script_by_content(self) -> None:
        shell = (ROOT / "mu" / "index.html").read_text(encoding="utf-8")
        sources = re.findall(r'<script src="\.\./([^"?]+)(\?v=([0-9a-f]+))?"', shell)
        self.assertEqual(
            [name for name, _, _ in sources],
            ["data/roster.js", "data/mu.js", "assets/charts.js", "assets/page.js"])
        for name, query, digest in sources:
            with self.subTest(script=name):
                self.assertTrue(query, f"{name} is served without a cache-busting version")
                expected = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()[: len(digest)]
                self.assertEqual(digest, expected, f"{name} carries a stale digest")

    def test_the_page_carries_the_cross_page_table_without_joining_it(self) -> None:
        """Carrying the shared table and being a column in it are two things.

        Micron sits upstream of every company in that table -- it supplies the
        memory the accelerators need -- which makes adding a column the single
        most tempting edit on this page. It must not happen here: the object is
        published byte-identically on every page, so a column added from this
        builder rewrites the same table on twenty-five others.
        """
        table = next(item for item in self.payload["tables"]
                     if "AI capex 循环" in item["title"])
        self.assertNotIn("MU", " ".join(table["headers"]))
        self.assertNotIn("Micron", " ".join(table["headers"]))
        from build.board import _CASH_CAPEX_SOURCES
        self.assertNotIn("mu", [slug for slug, _, _ in _CASH_CAPEX_SOURCES])

    def test_the_entry_and_the_payload_agree_about_the_company(self) -> None:
        entry = next(item for item in ENTRIES if item["slug"] == "mu")
        self.assertEqual(entry["ticker"], self.payload["company"]["ticker"])
        self.assertEqual(entry["name"], self.payload["company"]["name"])
        self.assertEqual(entry["group"], self.payload["company"]["group"])
        # Not "late August": the year ends the Thursday nearest 31 August, which
        # fell in September in three of the nine filed years and does so again in
        # FY2026 (2026-09-03 -- SEC records this filer's fiscalYearEnd as 0903).
        # The shorthand was copied out of here into README prose, where it became
        # a claim about specific dates; an approximation in a short field does not
        # stay in the short field.
        for text in (entry["cadence_label"], self.payload["subtitle"]):
            self.assertIn("最接近 8 月 31 日的星期四", text)
            self.assertNotIn("8 月底制财年", text)
            # the site-wide README gate keys on this phrase in cadence_label
            self.assertIn("本站按自然年季度标注", text)
        self.assertIn(self.staging["_checks"]["fiscal_year_end"], self.payload["subtitle"])
        # No count of how many past years ended in September: that number moves
        # with the next 10-K and nothing on the page recomputes it. The rule and
        # the filer record do not move, and the page is pinned to a quarter
        # inside FY2026, so its year-end date does not either.
        self.assertNotIn("近九个", self.payload["subtitle"])
        self.assertIn("申报人记录 09-03", self.payload["subtitle"])

    def test_source_links_are_public_and_absolute(self) -> None:
        for item in self.payload["source_links"]:
            with self.subTest(label=item["label"]):
                self.assertTrue(item["url"].startswith("https://"), item["url"])
                self.assertTrue(item["label"])
        self.assertTrue(self.payload["source_url"].startswith("https://www.sec.gov/"))

    def test_the_notes_say_which_series_are_short_and_why(self) -> None:
        """Three windows on this page are deliberately shorter than the others.

        The business units start at the release that first printed them, the
        supply-agreement figures have one filed observation, and the annual
        record stops at the last completed fiscal year. Each is a decision, not
        a gap, and a page that does not say so reads as though the data ran out.
        """
        notes = " ".join(self.payload["notes"])
        units = self.staging["business_units"]
        self.assertIn(f"业务单元序列只有{cn_count(len(units['quarters']))}个季度", notes)
        self.assertIn("不往前补", notes)
        self.assertIn("不画未完结的财年", notes)
        # The unit table starts at the release that first printed it and runs
        # to the page's quarter, one column per quarter, with no gap.
        self.assertEqual(units["quarters"][0], "Q3 2024")
        self.assertEqual(units["quarters"],
                         self.staging["periods"][self.staging["periods"].index("Q3 2024"):])


class MuChecksTest(unittest.TestCase):
    """The page's quarter against a record keyed separately from the filing.

    `_checks` in the series file is typed once per quarter from the earnings
    release itself, with the place in the document it was read from -- it is
    not copied out of the arrays, and the builder never reads it (asserted in
    `test_data_only_roll`). Every assertion here compares what the builder
    computed from the arrays with that separate reading, so a roll that
    misaligns a column, drops the new quarter or keeps last quarter's sentence
    fails here. Rolling a quarter re-keys `_checks`; this file does not change.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(mu.STAGING_PATH.read_text(encoding="utf-8"))
        cls.checks = cls.staging["_checks"]
        cls.fin = cls.staging["financials"]
        cls.payload = mu.build_payload(cls.staging)
        cls.exhibits = [exhibit for section in cls.payload["sections"]
                        for exhibit in section["exhibits"]]

    def test_the_page_names_the_checked_quarter_both_ways(self) -> None:
        self.assertIn(self.checks["period"], self.payload["title"])
        self.assertIn(f"本页 {self.checks['period']} 即公司所称 {self.checks['fiscal_label']}",
                      self.payload["subtitle"])
        self.assertIn(f"季度截至 {self.checks['period_end']}", self.payload["subtitle"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        checks, fin = self.checks, self.fin
        self.assertEqual(fin["revenue_usd_m"][-1], checks["revenue_usd_m"])
        # The release prints both margins to one decimal; the series carries
        # them unrounded, so they must round to what was printed.
        self.assertEqual(round(fin["gaap_gross_margin_pct"][-1], 1), checks["gaap_gross_margin_pct"])
        self.assertEqual(round(fin["non_gaap_gross_margin_pct"][-1], 1),
                         checks["non_gaap_gross_margin_pct"])
        self.assertEqual(fin["gaap_diluted_eps_usd"][-1], checks["gaap_diluted_eps_usd"])
        self.assertEqual(fin["non_gaap_diluted_eps_usd"][-1], checks["non_gaap_diluted_eps_usd"])
        self.assertEqual(round(fin["adjusted_free_cash_flow_usd_m"][-1] / 1000, 1),
                         checks["adjusted_free_cash_flow_usd_bn"])
        outlook = self.staging["next_quarter_guidance"]
        self.assertEqual(outlook["revenue_usd_m"], checks["next_quarter_revenue_guide_usd_m"])
        self.assertEqual(outlook["non_gaap_gross_margin_pct"],
                         checks["next_quarter_non_gaap_gross_margin_guide_pct"])

    def test_the_headline_prints_the_checked_figures(self) -> None:
        headline = self.payload["headline"]
        self.assertIn(f"收入 US${self.checks['revenue_usd_m']:,.0f}M", headline)
        self.assertIn(f"non-GAAP 毛利率 {self.checks['non_gaap_gross_margin_pct']:.1f}%", headline)
        self.assertIn(f"每股收益 US${self.checks['non_gaap_diluted_eps_usd']:.2f}", headline)

    def test_the_cash_chart_and_the_outlook_table_print_the_checked_figures(self) -> None:
        cash = next(e for e in self.exhibits if "的现金三条" in e["title"])
        self.assertIn(f"调整后自由现金流 US${self.checks['adjusted_free_cash_flow_usd_bn']:.1f}B",
                      cash["title"])
        rows = {row[0]: row for row in self.payload["guidance"]["rows"]}
        self.assertIn(f"US${self.checks['next_quarter_revenue_guide_usd_m'] / 1000:.1f}B", rows["收入"][2])
        self.assertIn(f"{self.checks['next_quarter_non_gaap_gross_margin_guide_pct']:.1f}%",
                      rows["毛利率"][2])


if __name__ == "__main__":
    unittest.main()
