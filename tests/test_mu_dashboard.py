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
from build.board import headroom  # noqa: E402


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
        for index, period in enumerate(self.periods):
            with self.subTest(period=period):
                self.assertAlmostEqual(
                    self.fin["revenue_usd_m"][index] - self.fin["cost_of_goods_sold_usd_m"][index],
                    self.fin["gross_margin_usd_m"][index], places=6,
                    msg="revenue - cost of goods sold must equal gross margin")
                self.assertAlmostEqual(
                    self.fin["gross_margin_usd_m"][index]
                    - self.fin["research_and_development_usd_m"][index]
                    - self.fin["selling_general_administrative_usd_m"][index]
                    - self.fin["other_operating_total_usd_m"][index],
                    self.fin["gaap_operating_income_usd_m"][index], places=4,
                    msg="gross margin less the three expense lines must equal operating income")

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
            with self.subTest(period=period):
                self.assertAlmostEqual(
                    self.fin["operating_cash_flow_usd_m"][index]
                    + self.fin["capex_net_usd_m"][index],
                    self.fin["adjusted_free_cash_flow_usd_m"][index], places=6)
                self.assertLess(self.fin["capex_net_usd_m"][index], 0,
                                "net capex is published as a negative number")

    def test_revenue_by_technology_sums_to_revenue(self) -> None:
        """DRAM + NAND + other equals the income statement, to the dollar.

        These three are filed dollar lines in the 10-Q revenue note, not
        percentages multiplied back out by this page. Asserting the sum is what
        makes that claim checkable: a percentage-derived series would miss by
        rounding in most quarters.
        """
        tech = self.staging["technology"]
        for index, period in enumerate(self.periods):
            with self.subTest(period=period):
                self.assertAlmostEqual(
                    tech["dram_revenue_usd_m"][index] + tech["nand_revenue_usd_m"][index]
                    + tech["other_revenue_usd_m"][index],
                    self.fin["revenue_usd_m"][index], places=6)
                self.assertAlmostEqual(
                    tech["dram_revenue_usd_m"][index] / self.fin["revenue_usd_m"][index] * 100,
                    tech["dram_share_pct"][index], places=1)

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
        for index, period in enumerate(self.periods):
            days = self.bal["days_in_quarter"][index]
            with self.subTest(period=period):
                if index:
                    self.assertEqual(days, (ends[index] - ends[index - 1]).days)
                self.assertIn(days, (91, 98))
                self.assertAlmostEqual(
                    self.bal["receivables_usd_m"][index]
                    / self.fin["revenue_usd_m"][index] * days,
                    self.bal["dso_days"][index], places=2)
                self.assertAlmostEqual(
                    self.bal["inventories_usd_m"][index]
                    / self.fin["cost_of_goods_sold_usd_m"][index] * days,
                    self.bal["dio_days"][index], places=2)

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
        scope_re = re.compile(r"(\d+)\s*(?:个已完结)?季(?:里|有)")
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
        charted = [row for row in table["rows"] if row[5] == "本页作图"]
        self.assertEqual(len(charted), len(quantified))
        for row, entry in zip(charted, quantified):
            self.assertEqual(row[0], entry["metric"])
            self.assertEqual(
                row[4],
                f"{headroom(entry['direction'], entry['threshold'], entry['current']):+.1f}%")
        excluded = [row for row in table["rows"] if row[5] != "本页作图"]
        self.assertEqual(len(excluded), len(self.staging["next_kpi"]["excluded"]))

    def test_the_filed_and_spoken_agreement_figures_stay_apart(self) -> None:
        """The page's most easily blurred distinction, pinned.

        The supply agreements are US$5.0B of remaining performance obligation in
        the 10-Q and US$100B on the call. Publishing either alone misleads, and
        publishing their difference would invent a number neither source states.
        So: both are on the chart, the filed one is labelled with the document it
        came from, and no arithmetic joins them.
        """
        exhibit = next(e for e in self.exhibits
                       if e["title"].startswith("长期供货协议"))
        filed, spoken = exhibit["groups"]
        self.assertIn("10-Q", filed["name"])
        self.assertNotIn("10-Q", spoken["name"])
        items = self.staging["filed_vs_spoken"]["items"]
        for index, item in enumerate(items):
            self.assertAlmostEqual(filed["values"][index], item["filed_usd_m"] / 1000, places=6)
            self.assertAlmostEqual(spoken["values"][index], item["spoken_usd_m"] / 1000, places=6)
            self.assertIn("10-Q", item["filed_source"])
            self.assertLess(item["filed_usd_m"], item["spoken_usd_m"])

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
        self.assertIn("8 月底制财年", entry["cadence_label"])
        self.assertIn("8 月底制财年", self.payload["subtitle"])

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
        self.assertIn("业务单元序列只有八个季度", notes)
        self.assertIn("不往前补", notes)
        self.assertIn("不画未完结的财年", notes)
        units = self.staging["business_units"]
        self.assertEqual(len(units["quarters"]), 8)


if __name__ == "__main__":
    unittest.main()
