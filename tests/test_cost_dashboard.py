"""Reconciliation and shape tests for the Costco page.

Same purpose as the other companies': nothing derived reaches the page until it
has been checked against a statement identity or a figure the company disclosed
separately.  Costco gives three identities that close exactly, and each one
licenses a different chart:

    net sales + membership fees − merchandise costs − SG&A = operating income
    Σ segment revenue = total revenue, Σ segment operating income = operating income
    Σ four merchandise categories = net sales

and one more that is the whole point of the long section:

    (net sales − merchandise costs − SG&A − preopening) / net sales
        + membership fees / net sales
        = operating income / net sales

The traps this file exists to pin are Costco's own, and they are mostly about
*length* rather than about arithmetic.  Its fiscal fourth quarter is 16 weeks
against 12 for the others, and in one year of the window it is 16 against a
prior-year 17, so a year-over-year figure there is short by a week.  Its
comparable sales are published at two different precisions.  Its renewal rate
changed precision mid-record.  Its "adjusted" comp meant something else for four
quarters of fiscal 2019.  Every one of those is a place where the page could be
made to look cleaner than the disclosure is, so every one of them is pinned by
value here rather than left to the prose.
"""

from __future__ import annotations

import copy
import json
import re
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import cost  # noqa: E402
from build.all import ENTRIES, build_all, roster_payload  # noqa: E402
from build.board import headroom  # noqa: E402
from build.cost import build_payload, compact_period, headline_metrics  # noqa: E402
from build.payload_guard import check as guard_payload  # noqa: E402

# The quarter the history pins below were read through. A roll appends quarters
# and fiscal years after it; the pins are bounded here so they stay true of the
# record they were checked against instead of being retyped each quarter.
PINNED_THROUGH = "Q2 2026"
PINNED_FISCAL_YEAR = 2025      # last fiscal year whose capex actual was pinned
PINNED_GUIDED_YEAR = 2026      # last guided year whose opening plan was pinned


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


def readings(source: dict) -> dict[str, float]:
    """This quarter's reading of every metric a threshold may read, computed here.

    Written from the series arrays directly, not through the builder's
    `kpi_history`: a check that borrowed the builder's idea of which cell is
    "this quarter" could not catch the builder picking the wrong one.
    """
    hist = source["comp_history_pct"]
    mem = source["membership"]
    deck = source["supplement"]
    us, world = mem["renewal_rate_us_canada_pct"], mem["renewal_rate_worldwide_pct"]
    executive, paid = deck["executive_members_mm"], deck["paid_members_mm"]
    assert hist["digital_metric_name"][-1] == "Digitally-Enabled"
    return {
        "adjusted_comp": hist["adjusted_total_pct"][-1],
        "digital_comp": hist["digital_reported_pct"][-1],
        "renewal_us": us[-1],
        "renewal_ww": world[-1],
        "renewal_us_change_bp": round((us[-1] - us[-2]) * 100),
        "renewal_ww_change_bp": round((world[-1] - world[-2]) * 100),
        "executive_share": executive[-1] / paid[-1] * 100,
        "executive_yoy": (executive[-1] / executive[-5] - 1) * 100,
        "core_on_core": source["core_on_core"]["change_bps"][-1],
        "us_traffic": deck["comp_traffic_us_pct"][-1],
    }


def on_wrong_side(entry: dict, value: float) -> bool:
    """The analysis's own rule: a line written as「≤ X」breaks at X."""
    margin = headroom(entry["direction"], entry["threshold"], value)
    return margin < 0 or (margin == 0 and bool(entry.get("breach_on_equal")))


def check_section_one(test: unittest.TestCase, source: dict, payload: dict) -> None:
    """Section one against `_checks["note"]`, in whichever state the quarter is.

    The note is transcribed from the two local reports, separately from the
    blocks the builder reads: which report is being settled, its follow-up
    tally, its section 8 thresholds. A first analysis settles only the
    company's guidance and says why; any later one opens with the follow-up
    tally and the threshold overview. Nothing here names a quarter.
    """
    note = source["_checks"]["note"]
    period = source["periods"][-1]
    settled = next(section for section in payload["sections"] if section["id"] == "settled")
    exhibits = settled["exhibits"]
    own = ("资本开支计划与实际", "实际资本开支相对计划中值的偏离", "计划开店数与实际开店数",
           "公司自己估的财年末仓库数")
    # section one ends with the company's own records, in this order
    for exhibit, prefix in zip(exhibits[-4:], own):
        test.assertTrue(exhibit["title"].startswith(prefix), exhibit["title"])
    story = exhibits[:-4]
    if note.get("previous_covers") is None:
        test.assertTrue(settled["description"].startswith(
            f"本站对该公司的第一份季报分析是 {period}，没有上季留下的跟踪指标可结算；"))
        test.assertEqual(story, [])
        for key in ("followup_closure", "prior_kpi_settlement"):
            test.assertNotIn(key, source)
        return
    previous = note["previous_covers"]
    test.assertNotIn("第一份季报分析", settled["description"])
    test.assertIn(f"正文分析的是 {previous['fiscal_label']}（本站 {previous['period']}", settled["description"])
    closure = note["followup_closure"]
    chart = story.pop(0)
    test.assertEqual(chart["kind"], "bars_labeled")
    test.assertTrue(chart["title"].startswith(f"上季 {closure['total']} 条待验证问题："), chart["title"])
    test.assertEqual(dict(zip(chart["xlabels"], chart["values"])), closure["counts"])
    table = next(t for t in payload["tables"] if "待验证问题" in t["title"])
    test.assertEqual([row[2] for row in table["rows"]], closure["verdicts"])
    charted = [t for t in note["prior_thresholds"] if t["settled_on"] == "chart"]
    overview = story.pop(0)
    test.assertEqual(overview["kind"], "diverging_bars")
    test.assertTrue(overview["title"].startswith(f"上季 {len(charted)} 条量化阈值"), overview["title"])
    test.assertEqual(overview["xlabels"], [t["metric"] for t in charted])
    prior_table = next(t for t in payload["tables"] if t["title"].startswith("上季阈值与本季读数"))
    test.assertEqual([row[0] for row in prior_table["rows"]], [t["metric"] for t in note["prior_thresholds"]])
    for chart in story:
        test.assertEqual(chart["kind"], "lines")
        test.assertRegex(chart["title"], r"：本季 .+，(守住|击穿)上季阈值 ")


class CostDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "cost.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]
        cls.by_section = {
            section["id"]: section["exhibits"] for section in cls.payload["sections"]
        }
        cls.fin = cls.source["financials"]
        cls.seg = cls.source["segments_usd_m"]
        cls.ann = cls.source["annual"]
        cls.hist = cls.source["comp_history_pct"]

    # ── shape ───────────────────────────────────────────────────────────────
    def test_the_window_is_eight_quarters_and_complete(self) -> None:
        self.assertEqual(len(self.source["periods"]), 8)
        self.assertEqual(self.source["periods"][-1], self.source["latest"]["period"])
        for name, values in self.fin.items():
            self.assertEqual(len(values), 8, name)
            self.assertIsNotNone(values[-1], f"{name} has no current value")

    def test_calendar_labels_are_the_quarter_the_period_ends_in(self) -> None:
        """The page's own labelling rule, applied to every quarter in the window.

        Costco's twelve-week quarters drift, so the site's usual "whichever
        calendar quarter the fiscal one mostly covers" rule is not one-to-one
        here -- fiscal 2026 Q2 and Q3 both have more days in calendar Q1 2026.
        The rule the page states instead is the period-end one, and this pins it.
        """
        for period, end in zip(self.source["periods"], self.source["period_ends"]):
            quarter, year = period.split()
            ends = date.fromisoformat(end)
            self.assertEqual(int(year), ends.year, period)
            self.assertEqual(int(quarter[1]), (ends.month - 1) // 3 + 1, period)

    def test_the_sixteen_week_quarters_are_where_the_fiscal_fourths_are(self) -> None:
        weeks = self.source["weeks"]
        self.assertTrue(set(weeks) <= {12, 16, 17}, weeks)
        self.assertEqual(sum(1 for week in weeks if week > 12), 2,
                         "eight quarters hold exactly two fiscal fourth quarters")
        for index, week in enumerate(weeks):
            fiscal = self.source["fiscal_labels"][index]
            self.assertEqual(week > 12, fiscal.endswith("Q4"), fiscal)

    def test_the_one_quarter_whose_comparative_had_a_different_length(self) -> None:
        """Fiscal 2023 was a 53-week year, so its fourth quarter ran 17 weeks.

        Q3 2024 therefore compares 16 weeks with 17, and every year-over-year
        figure in that column is short by roughly a week. The page marks it; a
        page that did not would show a growth collapse that is a calendar
        artefact.
        """
        by_period = self.source["weeks_by_period"]
        for index, period in enumerate(self.source["periods"]):
            quarter, year = period.split()
            comparative = f"{quarter} {int(year) - 1}"
            with self.subTest(period=period):
                self.assertEqual(self.source["yoy_week_mismatch"][index],
                                 by_period[period] != by_period[comparative])
        mismatch = [period for period, flag
                    in zip(self.source["periods"], self.source["yoy_week_mismatch"]) if flag]
        cats = next(ex for ex in self.by_section["quarter_highlights"]
                    if "四条商品线" in ex["title"])
        if "Q3 2024" in self.source["periods"]:
            # the one such quarter the record has, pinned by value while it is in the window
            self.assertEqual(mismatch, ["Q3 2024"])
            contribution = self.source["merchandise_categories"]["net_sales_yoy_pct"]
            index = self.source["periods"].index("Q3 2024")
            self.assertLess(contribution[index], 2.0)
        for period in mismatch:
            quarter, year = period.split()
            self.assertIn(compact_period(period), cats.get("annot", ""))
            self.assertIn(f"{by_period[f'{quarter} {int(year) - 1}']} 周", cats["note"])

    # ── identities ──────────────────────────────────────────────────────────
    def test_income_statement_closes_to_the_dollar(self) -> None:
        for index in range(8):
            with self.subTest(period=self.source["periods"][index]):
                self.assertEqual(
                    self.fin["net_sales_usd_m"][index] + self.fin["membership_fees_usd_m"][index],
                    self.fin["total_revenue_usd_m"][index])
                self.assertEqual(
                    self.fin["total_revenue_usd_m"][index]
                    - self.fin["merchandise_costs_usd_m"][index]
                    - self.fin["sga_usd_m"][index],
                    self.fin["operating_income_usd_m"][index])
                self.assertEqual(
                    self.fin["operating_income_usd_m"][index]
                    + self.fin["interest_expense_usd_m"][index]
                    + self.fin["interest_income_and_other_usd_m"][index],
                    self.fin["pretax_income_usd_m"][index])
                self.assertEqual(
                    self.fin["pretax_income_usd_m"][index] - self.fin["income_tax_usd_m"][index],
                    self.fin["net_income_usd_m"][index])

    def test_segments_sum_to_the_consolidated_figures(self) -> None:
        for index in range(8):
            with self.subTest(period=self.source["periods"][index]):
                revenue = sum(self.seg[key]["revenue_usd_m"][index]
                              for key in ("united_states", "canada", "other_international"))
                operating = sum(self.seg[key]["operating_income_usd_m"][index]
                                for key in ("united_states", "canada", "other_international"))
                self.assertEqual(revenue, self.fin["total_revenue_usd_m"][index])
                self.assertEqual(operating, self.fin["operating_income_usd_m"][index])

    def test_the_derived_fiscal_fourth_quarters_are_marked(self) -> None:
        """Two of the eight segment columns are a subtraction, not a filing.

        Costco files no 10-Q for its fiscal fourth quarter, so the segment note
        for that period exists only inside the annual figures. The page derives
        it and says so; this pins which columns those are, and that the same
        subtraction reproduces the consolidated figures the Q4 release *does*
        print -- which is what licenses using it on the segments.
        """
        derived = [period for period, flag
                   in zip(self.seg["periods"], self.seg["is_derived"]) if flag]
        self.assertEqual(derived, [period for period, fiscal
                                   in zip(self.source["periods"], self.source["fiscal_labels"])
                                   if fiscal.endswith("Q4")])
        for period in derived:
            index = self.source["periods"].index(period)
            total = sum(self.seg[key]["revenue_usd_m"][index]
                        for key in ("united_states", "canada", "other_international"))
            self.assertEqual(total, self.fin["total_revenue_usd_m"][index])
        chart = next(ex for ex in self.by_section["routine"]
                     if "分部的营业利润率" in ex["title"])
        for period in derived:
            self.assertIn(compact_period(period), chart["note"])

    def test_merchandise_categories_sum_to_net_sales(self) -> None:
        cats = self.source["merchandise_categories"]
        keys = ["foods_and_sundries_usd_m", "non_foods_usd_m", "fresh_foods_usd_m",
                "warehouse_ancillary_and_other_usd_m"]
        for index in range(8):
            with self.subTest(period=cats["periods"][index]):
                self.assertEqual(sum(cats[key][index] for key in keys),
                                 self.fin["net_sales_usd_m"][index])

    def test_category_growth_contributions_sum_to_the_reported_growth(self) -> None:
        """The contribution chart is an identity, so it has to close exactly."""
        cats = self.source["merchandise_categories"]
        for index in range(8):
            legs = [cats["growth_contribution_pp"][key][index]
                    for key in cats["growth_contribution_pp"]]
            if any(leg is None for leg in legs):
                continue
            with self.subTest(period=cats["periods"][index]):
                self.assertAlmostEqual(sum(legs), cats["net_sales_yoy_pct"][index], places=4)

    def test_the_eps_bridge_multiplies_back_to_the_reported_growth(self) -> None:
        """Four multiplicative legs, no residual beyond the printed cents.

        EPS = (operating income + other) x (1 - tax rate) / diluted shares, so
        the year-over-year ratio factors exactly. The window deliberately starts
        where the noncontrolling-interest line is nil in both the quarter and its
        comparative; before that a fifth leg would be needed and the page says so.
        """
        bridge = self.source["eps_growth_bridge_pct"]
        self.assertEqual(bridge["periods"][0], "Q4 2023")
        self.assertEqual(bridge["periods"][-1], self.source["periods"][-1])
        for index, period in enumerate(bridge["periods"]):
            with self.subTest(period=period):
                product = 1.0
                for key in ("operating_leg_pct", "below_the_line_leg_pct",
                            "tax_leg_pct", "share_count_leg_pct"):
                    product *= 1 + bridge[key][index] / 100
                self.assertAlmostEqual((product - 1) * 100, bridge["product_pct"][index],
                                       places=4)
                self.assertAlmostEqual(bridge["product_pct"][index],
                                       bridge["reported_eps_yoy_pct"][index], places=4)

    def test_the_two_legs_of_the_operating_margin_close_every_year(self) -> None:
        """The page's signature long series is an identity, in all thirteen years."""
        ann = self.ann
        self.assertEqual(ann["fiscal_years"],
                         [f"FY{year}" for year in range(2013, 2013 + len(ann["fiscal_years"]))])
        for index, year in enumerate(ann["fiscal_years"]):
            with self.subTest(year=year):
                self.assertAlmostEqual(
                    ann["merchandising_leg_pct_of_net_sales"][index]
                    + ann["membership_leg_pct_of_net_sales"][index],
                    ann["operating_margin_on_net_sales_pct"][index],
                    places=4)
        # And the finding the chart states, pinned by value rather than by prose.
        pinned = ann["fiscal_years"].index(f"FY{PINNED_FISCAL_YEAR}")
        self.assertGreater(ann["membership_fee_share_of_operating_income_pct"][0], 74.0)
        self.assertLess(ann["membership_fee_share_of_operating_income_pct"][pinned], 52.0)
        self.assertLess(ann["membership_leg_pct_of_net_sales"][pinned]
                        - ann["merchandising_leg_pct_of_net_sales"][pinned], 0.15)

    def test_membership_fee_per_member_is_week_normalised(self) -> None:
        """A 16-week quarter would otherwise print a third more fee per member."""
        mem = self.source["membership"]
        for index, period in enumerate(mem["periods"]):
            fee = mem["membership_fees_usd_m"][index]
            weeks = mem["weeks"][index]
            members = mem["paid_members_000s"][index]
            if None in (fee, weeks, members):
                continue
            with self.subTest(period=period):
                self.assertAlmostEqual(
                    mem["annualised_fee_per_paid_member_usd"][index],
                    round(fee / weeks * 52 / (members / 1000), 2), places=2)
        # No sixteen- or seventeen-week quarter survives the normalisation as a
        # spike. This used to be `max/min < 1.2` across the whole series, which
        # answered the question only by accident: over 27 quarters the fee per
        # member happened to grow less than 20%, over 42 it grows 27% (56.68 to
        # 71.77, two fee increases), and the assertion started failing on real
        # growth rather than on a seasonal artefact. Compare each long quarter
        # with its own neighbours instead, which is what "spike" meant.
        values = mem["annualised_fee_per_paid_member_usd"]
        weeks = mem["weeks"]
        long_quarters = [i for i, w in enumerate(weeks)
                         if w > 12 and 0 < i < len(values) - 1]
        self.assertGreaterEqual(len(long_quarters), 8)
        for index in long_quarters:
            around = (values[index - 1] + values[index + 1]) / 2
            with self.subTest(period=mem["periods"][index]):
                self.assertLess(abs(values[index] / around - 1), 0.05)

    def test_the_quarterly_fee_line_is_the_discrete_period_not_the_year(self) -> None:
        """The 10-K's MD&A prints the fiscal YEAR's membership fees, so a fourth
        quarter taken from there is twelve months wearing a quarterly label."""
        mem = self.source["membership"]
        for index, period in enumerate(mem["periods"]):
            if mem["weeks"][index] <= 12:
                continue
            with self.subTest(period=period):
                self.assertLess(mem["membership_fees_usd_m"][index], 2500)

    # ── the comparable-sales record ─────────────────────────────────────────
    def test_the_comp_record_is_one_basis_throughout(self) -> None:
        """Fiscal 2019's "Adjusted" column also stripped an accounting change.

        The plotted record therefore starts after it. A record that reached
        further back would be two definitions under one label.
        """
        self.assertEqual(self.hist["periods"][0], "Q1 2016")
        self.assertEqual(self.hist["periods"][-1], self.source["periods"][-1])
        # The record now reaches through fiscal 2019 rather than starting after
        # it, and the one-basis rule is kept where it actually matters: every
        # quarter that carries an adjusted figure carries it on the gasoline-and-
        # FX basis. Fiscal 2019's four quarters are empty on this line, not
        # spliced -- their printed "Adjusted" also strips the ASC 606 transition.
        for index, basis in enumerate(self.hist["adjustment_basis"]):
            period = self.hist["periods"][index]
            with self.subTest(period=period):
                if basis == "gasoline_and_fx":
                    self.assertIsNotNone(self.hist["adjusted_total_pct"][index])
                    self.assertAlmostEqual(
                        self.hist["reported_total_pct"][index]
                        - self.hist["adjusted_total_pct"][index],
                        self.hist["gap_pp"][index], places=6)
                else:
                    self.assertIn("asc606", basis)
                    self.assertIsNone(self.hist["adjusted_total_pct"][index])
                    self.assertIsNone(self.hist["gap_pp"][index])
        wider = self.hist["asc606_era_as_disclosed"]
        self.assertEqual(wider["periods"],
                         ["Q4 2018", "Q1 2019", "Q2 2019", "Q3 2019"])
        # the wider-basis figures are kept, so nothing the company printed is lost
        self.assertEqual(len(wider["as_disclosed_adjusted_total_pct"]), 4)

    def test_the_gap_finding_is_pinned_by_value(self) -> None:
        """The page's sharpest claim: gasoline and currency have suppressed the
        headline more often than they have flattered it."""
        through = self.hist["periods"].index(PINNED_THROUGH) + 1
        pinned = [value for value in self.hist["gap_pp"][:through] if value is not None]
        # 19 of the 38 quarters that have this basis through Q2 2026 -- the record
        # ran 42 quarters then, four of which (fiscal 2019) carry no adjusted figure.
        self.assertEqual((sum(1 for value in pinned if value < 0), len(pinned)), (19, 38))
        self.assertEqual([round(value, 1) for value in pinned[-4:]], [-0.7, 0.0, 0.7, 3.2])
        gap = [value for value in self.hist["gap_pp"] if value is not None]
        negative = sum(1 for value in gap if value < 0)
        chart = next(ex for ex in self.by_section["quarter_highlights"]
                     if ex["title"].startswith("汽油与汇率"))
        self.assertIn(f"{negative} 季是压低", chart["title"])
        # the title leads with this quarter's gap and where it ranks
        this = self.hist["gap_pp"][-1]
        if this > 0:
            rank = sorted(gap, reverse=True).index(this) + 1
            self.assertIn(f"本季把 headline 抬高 {this:.1f} 个百分点，是 {len(gap)} 季里第 {rank} 大",
                          chart["title"])

    def test_the_two_precisions_of_comparable_sales_are_both_carried(self) -> None:
        """The press release gives one decimal, the 10-Q whole percentages, and
        the page's claim about a flat line only survives at the finer one."""
        comp = self.source["comparable_sales_pct"]
        filed = comp["filed_integer_adjusted_total_pct"]
        release = comp["adjusted_total_pct"]
        for index in range(8):
            # A fiscal fourth quarter has no 10-Q, and the 10-K prints the
            # fiscal YEAR's comp rather than the sixteen-week quarter's, so
            # there is no filed integer to compare against. The series stores
            # None there rather than the annual figure wearing a quarterly
            # label -- which is the defect this assertion exists to catch.
            if filed[index] is None:
                self.assertGreater(self.source["weeks"][index], 12,
                                   "only a fiscal fourth quarter may be missing")
                continue
            with self.subTest(period=comp["periods"][index]):
                self.assertEqual(filed[index], round(release[index]))
                self.assertEqual(filed[index], int(filed[index]))
        # The claim about the two precisions is printed from the last three
        # quarters, both ways, and the page must print exactly those numbers.
        # A fiscal fourth quarter has no whole-number reading, so the three are
        # the last three quarters that have both precisions.
        both = [i for i, value in enumerate(filed) if value is not None][-3:]
        chart = next(ex for ex in self.by_section["next_quarter"] if ex["title"].startswith("调整后合并 comp："))
        self.assertIn("、".join(f"{filed[i]:.0f}%" for i in both), chart["note"])
        self.assertIn("、".join(f"{release[i]:.1f}%" for i in both), chart["note"])
        if max(release[i] for i in both) - min(release[i] for i in both) > 0.5:
            self.assertNotIn("是一条平线", chart["note"])
        table = next(t for t in self.payload["tables"] if "同店销售完整记录" in t["title"])
        self.assertEqual(len(table["rows"]), len(self.hist["periods"]))

    def test_the_digital_metric_break_is_marked_not_spliced(self) -> None:
        names = self.hist["digital_metric_name"]
        index = self.hist["digital_break_index"]
        # Three states now, not two: before Costco published a digital comp at
        # all there is no metric name to give. Extending the record back to 2016
        # brought six such quarters in, and a test that only knew two states
        # would have been satisfied by calling them E-commerce.
        first = next(i for i, name in enumerate(names) if name is not None)
        self.assertEqual(self.hist["periods"][first], "Q3 2017")
        self.assertEqual(set(names[:first]), {None})
        for i in range(first):
            with self.subTest(period=self.hist["periods"][i]):
                self.assertIsNone(self.hist["digital_reported_pct"][i])
        self.assertEqual(set(names[first:index]), {"E-commerce"})
        self.assertEqual(set(names[index:]), {"Digitally-Enabled"})
        self.assertEqual(self.hist["periods"][index], "Q4 2025")

    def test_renewal_rates_are_plotted_only_where_they_have_a_decimal(self) -> None:
        mem = self.source["membership"]
        start = mem["renewal_decimal_from_index"]
        self.assertEqual(mem["periods"][start], "Q1 2023")
        for value in mem["renewal_rate_us_canada_pct"][:start]:
            self.assertEqual(value, round(value), "pre-decimal era is whole points")
        level = next(ex for ex in self.by_section["next_quarter"] if ex["title"].startswith("会员续费率："))
        self.assertEqual(len(level["xlabels"]), len(mem["periods"]) - start)
        # A change needs two one-decimal readings, so it starts one quarter later.
        change = next(ex for ex in self.by_section["settled"] if ex["title"].startswith("会员续费率季度变化"))
        self.assertEqual(len(change["xlabels"]), len(mem["periods"]) - start - 1)

    # ── the guidance record ─────────────────────────────────────────────────
    def test_the_capex_record_is_two_sided(self) -> None:
        """Every other guidance record on this site is one-sided. This one is
        not, and the count is what says so."""
        record = self.source["capex_guidance"]
        low = record["guided_low_usd_m"]
        high = record["guided_high_usd_m"]
        actual = record["actual_capex_usd_m"]
        finished = [i for i in range(len(actual))
                    if actual[i] is not None and low[i] is not None]
        above = sum(1 for i in finished if actual[i] > high[i])
        below = sum(1 for i in finished if actual[i] < low[i])
        inside = len(finished) - above - below
        self.assertGreaterEqual(above, 3)
        self.assertGreaterEqual(below, 3)
        self.assertEqual(above + below + inside, len(finished))
        band = next(ex for ex in self.by_section["settled"] if "资本开支计划与实际" in ex["title"])
        self.assertIn(f"{above} 年高于上限", band["title"])
        self.assertIn(f"{below} 年低于下限", band["title"])

    def test_both_vintages_are_tallied_and_both_are_on_the_chart(self) -> None:
        """The symmetry belongs to the opening vintage only.

        Scored against each year's final 10-Q the same record leans one way.
        Publishing only the opening tally would be choosing the vintage that
        makes the finding, so both counts are pinned here and the band chart is
        required to carry the second one.
        """
        record = self.source["capex_guidance"]

        def tally(key):
            counts = {"ABOVE": 0, "BELOW": 0, "INSIDE": 0}
            for verdict, actual in zip(record[key], record["actual_capex_usd_m"]):
                if actual is not None and verdict in counts:
                    counts[verdict] += 1
            return counts

        opening, final = tally("verdict_vs_opening"), tally("verdict_vs_final")
        through = record["guided_fiscal_years"].index(PINNED_FISCAL_YEAR) + 1
        pinned = {key: record[key][:through] for key in record}
        pinned_opening = {"ABOVE": 0, "BELOW": 0, "INSIDE": 0}
        pinned_final = {"ABOVE": 0, "BELOW": 0, "INSIDE": 0}
        for o, f, actual in zip(pinned["verdict_vs_opening"], pinned["verdict_vs_final"],
                                pinned["actual_capex_usd_m"]):
            if actual is not None:
                pinned_opening[o] = pinned_opening.get(o, 0) + (o in pinned_opening)
                pinned_final[f] = pinned_final.get(f, 0) + (f in pinned_final)
        self.assertEqual({k: pinned_opening[k] for k in ("ABOVE", "BELOW", "INSIDE")},
                         {"ABOVE": 5, "BELOW": 5, "INSIDE": 2})
        self.assertEqual({k: pinned_final[k] for k in ("ABOVE", "BELOW", "INSIDE")},
                         {"ABOVE": 6, "BELOW": 3, "INSIDE": 4})
        opening, final = ({k: pinned_opening[k] for k in ("ABOVE", "BELOW", "INSIDE")},
                          {k: pinned_final[k] for k in ("ABOVE", "BELOW", "INSIDE")})
        live_final = tally("verdict_vs_final")
        self.assertNotEqual(opening["ABOVE"] == opening["BELOW"],
                            final["ABOVE"] == final["BELOW"],
                            "the two vintages must not tell the same story")
        band = next(ex for ex in self.by_section["settled"] if "资本开支计划与实际" in ex["title"])
        self.assertIn("只对年初那一版成立", band["note"])
        self.assertIn(f"{live_final['ABOVE']} 年高于上限", band["note"])

    def test_the_full_record_is_drawn_and_contradicts_the_short_window(self) -> None:
        """The symmetry is a property of the recent twelve years.

        Over the whole filed record the misses lean one way, so the deviation
        chart carries all thirty settled years and says so. Publishing only the
        window in which the finding holds would be choosing the window that
        makes it.
        """
        full = self.source["capex_record_full"]
        years = full["guided_fiscal_years"]
        self.assertEqual(years[0], 1995)
        self.assertEqual(years[-1], self.source["capex_guidance"]["guided_fiscal_years"][-1])
        self.assertEqual(years, list(range(1995, years[-1] + 1)), "contiguous, no gaps")

        live = [i for i, v in enumerate(full["deviation_vs_opening_pct"]) if v is not None]
        settled = [i for i in live if years[i] <= PINNED_FISCAL_YEAR]
        self.assertEqual(len(settled), 30)

        def tally(indexes):
            counts = {"ABOVE": 0, "BELOW": 0, "INSIDE": 0}
            for i in indexes:
                counts[full["verdict_vs_opening"][i]] += 1
            return counts

        whole = tally(settled)
        early = tally([i for i in settled if years[i] < 2013])
        late = tally([i for i in settled if years[i] >= 2013])
        self.assertEqual(whole, {"BELOW": 15, "INSIDE": 5, "ABOVE": 10})
        self.assertEqual(early, {"BELOW": 10, "INSIDE": 3, "ABOVE": 5})
        self.assertEqual(late, {"BELOW": 5, "INSIDE": 2, "ABOVE": 5})
        # The point of drawing both: the halves must not agree, or the short
        # window would have been a fair sample after all.
        self.assertEqual(late["ABOVE"], late["BELOW"])
        self.assertNotEqual(early["ABOVE"], early["BELOW"])

        # Every verdict is recomputable from the endpoints it was scored on.
        for i in settled:
            actual = full["actual_usd_m"][i]
            lo, hi = full["guided_low_usd_m"][i], full["guided_high_usd_m"][i]
            expected = "ABOVE" if actual > hi else "BELOW" if actual < lo else "INSIDE"
            with self.subTest(year=years[i]):
                self.assertEqual(full["verdict_vs_opening"][i], expected)

        dev = next(ex for ex in self.by_section["settled"] if "相对计划中值的偏离" in ex["title"])
        self.assertEqual(len(dev["xlabels"]), len(years))
        self.assertIn(f"{len(live)} 个已完结年度", dev["title"])
        self.assertIn("不是这家公司的性质", dev["note"])
        band = next(ex for ex in self.by_section["settled"] if "资本开支计划与实际" in ex["title"])
        self.assertIn("但这只是最近这一段", band["note"])

    def test_the_hit_rate_excludes_the_years_with_no_range_to_hit(self) -> None:
        """Three years are guided as a single number. A point has no width, so
        counting those as "missed the range" is what makes the two eras look
        identical -- the same category error the NVIDIA page avoids for opex."""
        full = self.source["capex_record_full"]
        years = full["guided_fiscal_years"]
        settled = [i for i, v in enumerate(full["deviation_vs_opening_pct"])
                   if v is not None and years[i] <= PINNED_FISCAL_YEAR]
        points = [years[i] for i in settled if full["guidance_shape"][i] == "point"]
        self.assertEqual(points, [2009, 2010, 2011])
        for i in settled:
            if full["guidance_shape"][i] == "point":
                self.assertEqual(full["guided_low_usd_m"][i], full["guided_high_usd_m"][i])
                self.assertNotEqual(full["verdict_vs_opening"][i], "INSIDE")

        def rate(lo, hi):
            ranged = [i for i in settled if full["guidance_shape"][i] == "range"
                      and lo <= years[i] <= hi]
            return sum(1 for i in ranged
                       if full["verdict_vs_opening"][i] == "INSIDE"), len(ranged)

        self.assertEqual(rate(0, 2012), (3, 15))
        self.assertEqual(rate(2013, 9999), (2, 12))
        dev = next(ex for ex in self.by_section["settled"] if "相对计划中值的偏离" in ex["title"])
        for year in points:
            self.assertIn(f"FY{year}", dev["note"])

    def test_the_two_averages_are_taken_over_the_same_years(self) -> None:
        """The revision only narrows the error on the years that have both
        vintages; comparing the thirty-year spread against the recent window's
        would flatter the revision by changing the sample underneath it."""
        full = self.source["capex_record_full"]
        both = [i for i, (a, b) in enumerate(zip(full["deviation_vs_opening_pct"],
                                                 full["deviation_vs_final_pct"]))
                if a is not None and b is not None]
        self.assertEqual(sum(1 for i in both if full["guided_fiscal_years"][i] <= PINNED_FISCAL_YEAR), 12)
        opening = sum(abs(full["deviation_vs_opening_pct"][i]) for i in both) / len(both)
        final = sum(abs(full["deviation_vs_final_pct"][i]) for i in both) / len(both)
        self.assertGreater(opening, final)
        self.assertLess(opening / final, 2.0, "the funnel closes by less than half")
        dev = next(ex for ex in self.by_section["settled"] if "相对计划中值的偏离" in ex["title"])
        self.assertIn(f"在两条腿都有的那 {len(both)} 年里", dev["note"])
        self.assertIn("不要并排比", dev["note"])

    def test_the_opening_plan_record_is_not_extended_and_says_why(self) -> None:
        """The pre-2010 opening plans are scoped to the US and Canada while the
        filed opening count is worldwide, and the promised measure -- gross
        openings in the US and Canada -- was never filed in any year. That is a
        stronger reason to stop than "the wording changed", and the chart says
        it rather than drawing a line across it."""
        plan = self.source["warehouse_plan"]
        self.assertGreaterEqual(min(plan["guided_fiscal_years"]), 2015)
        chart = next(ex for ex in self.by_section["settled"] if "计划开店数" in ex["title"])
        self.assertIn("美国与加拿大", chart["note"])
        self.assertIn("从没申报过", chart["note"])

    def test_the_hedged_wording_is_counted_not_assumed_away(self) -> None:
        """"approximately $X to $Y" is not a hard bound; two overshoots sit
        inside what the word plausibly covers, and the chart says which."""
        record = self.source["capex_guidance"]
        numeric = [i for i, lo in enumerate(record["guided_low_usd_m"])
                   if lo is not None and record["guided_fiscal_years"][i] <= PINNED_GUIDED_YEAR]
        hedged = [i for i in numeric
                  if "approximately" in (record["figure_as_printed"][i] or "").lower()]
        self.assertEqual((len(hedged), len(numeric)), (12, 13))
        soft = [record["guided_fiscal_years"][i] for i in numeric
                if record["actual_capex_usd_m"][i] is not None
                and record["verdict_vs_opening"][i] == "ABOVE"
                and record["actual_capex_usd_m"][i] / record["guided_high_usd_m"][i] - 1 < 0.05]
        self.assertEqual(soft, [2013, 2024])
        band = next(ex for ex in self.by_section["settled"] if "资本开支计划与实际" in ex["title"])
        self.assertIn("approximately", band["note"])

    def test_the_core_on_core_axis_describes_its_own_holes(self) -> None:
        """A fiscal fourth quarter has no 10-Q sentence, but the supplemental
        deck prints one from FY2024 Q3 on — so some annual holes are filled and
        some are not, and the caption has to match the data rather than assert a
        hole every year."""
        core = self.source["core_on_core"]
        through = core["periods"].index(PINNED_THROUGH) + 1
        pinned_q4 = [i for i, period in enumerate(core["periods"][:through]) if period.startswith("Q3 ")]
        self.assertEqual((sum(1 for i in pinned_q4 if core["change_bps"][i] is not None), len(pinned_q4)),
                         (2, 10))
        q4 = [i for i, period in enumerate(core["periods"]) if period.startswith("Q3 ")]
        filled = [i for i in q4 if core["change_bps"][i] is not None]
        for index in filled:
            self.assertIn("EX-99.2", core["value_source"][index])
        for index in set(q4) - set(filled):
            self.assertIsNone(core["value_source"][index])
        chart = next(ex for ex in self.by_section["next_quarter"] if "核心商品" in ex["title"])
        self.assertIn(f"{len(q4)} 个会计 Q4 有 {len(filled)} 个由它填上", chart["note"])
        disclosed = sum(1 for value in core["change_bps"] if value is not None)
        self.assertIn(f"{disclosed} 个有披露的季度", chart["note"])
        # The holes are drawn as holes: a marker on every reading, a gap at every
        # fiscal fourth quarter the deck does not fill.
        self.assertTrue(chart["markers"])
        self.assertEqual(chart["series"][0]["values"], core["change_bps"])

    def test_the_qualitative_year_gets_no_band(self) -> None:
        """One 10-K guides "a similar amount" and gives no number. Turning a word
        into a range would be the page inventing the company's guidance."""
        record = self.source["capex_guidance"]
        qualitative = [i for i, flag in enumerate(record["is_qualitative"]) if flag]
        self.assertTrue(qualitative)
        for index in qualitative:
            self.assertIsNone(record["guided_low_usd_m"][index])
            self.assertIsNone(record["guided_high_usd_m"][index])
            self.assertIsNotNone(record["actual_capex_usd_m"][index])

    def test_the_publication_lag_is_carried_as_a_number(self) -> None:
        """The plan goes out after the year it guides has already started."""
        lag = self.source["capex_guidance"]["lag_days_into_guided_year"]
        self.assertTrue(all(0 < value < 90 for value in lag if value is not None), lag)
        band = next(ex for ex in self.by_section["settled"] if "资本开支计划与实际" in ex["title"])
        self.assertIn("开始后", band["note"])

    def test_the_opening_plan_is_not_drawn_as_one_promise(self) -> None:
        """The number is comparable across the record; the promise is not.

        Costco's opening sentence carries four different qualifiers over the
        window -- a range, "up to", "approximately", "approximately up to" --
        and the relocation clause flips between naming relocations as part of
        the plan and as an addition to it. The page draws the quantity (planned
        openings against actual openings) and refuses to call it a ceiling; a
        band chart would invent a floor and a single "never breached" tally
        would be counting four different objects.
        """
        chart = next(ex for ex in self.by_section["settled"] if "计划开店数" in ex["title"])
        self.assertEqual(chart["kind"], "grouped_bars")
        self.assertNotIn("上限", chart["title"])
        plan = self.source["warehouse_plan"]
        qualifiers = {q for q in plan["planned_qualifier"] if q}
        self.assertGreaterEqual(len(qualifiers), 3, "the wording really does move")
        self.assertIn("限定词换过四次", chart["note"])
        # Where relocations are additional the comparable plan is N + M.
        for index, additional in enumerate(plan["relocations_are_additional"]):
            expected = plan["planned_as_stated"][index] + (
                (plan["planned_relocations"][index] or 0) if additional else 0)
            with self.subTest(year=plan["guided_fiscal_years"][index]):
                self.assertEqual(plan["planned_total"][index], expected)
        # The two earliest guided years are excluded outright, not smoothed.
        self.assertNotIn(2013, plan["guided_fiscal_years"])
        self.assertNotIn(2014, plan["guided_fiscal_years"])

    def test_the_warehouse_count_estimate_lands_exactly(self) -> None:
        """The contrast the page draws: the store count is a schedule Costco
        controls and hits; the dollar plan is not."""
        est = self.source["warehouse_estimate"]
        settled = {}
        for year, estimate, actual in zip(est["target_fiscal_year"],
                                          est["fy_end_estimate"], est["actual_fy_end"]):
            if actual is not None:
                settled[year] = (estimate, actual)
        self.assertGreaterEqual(len(settled), 2)
        for year, (estimate, actual) in settled.items():
            with self.subTest(year=year):
                self.assertEqual(estimate, actual, "the final vintage lands exactly")

    # ── what the page refuses ───────────────────────────────────────────────
    def test_the_page_carries_no_monthly_series(self) -> None:
        """Costco reports a sales figure every retail month; the site's cadence
        is quarterly, so none of it may reach the payload."""
        text = json.dumps(self.source, ensure_ascii=False)
        for banned in ("monthly_sales", "retail_month", "four_week", "five_week"):
            self.assertNotIn(banned, text)
        for exhibit in self.exhibits:
            self.assertNotEqual(exhibit["kind"], "year_lines", f"exhibit {exhibit['n']}")
            for label in exhibit.get("xlabels", []):
                self.assertNotRegex(str(label), r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)")

    def test_section_two_leads_with_this_quarter(self) -> None:
        """「本季重点」 charts say this quarter's reading first; a title whose first
        claim is a long-run count (「38 季里 19 季…」) belongs to section four."""
        for exhibit in self.by_section["quarter_highlights"]:
            with self.subTest(title=exhibit["title"]):
                self.assertNotRegex(exhibit["title"], r"^[^：]*：\d+ ?季(里|记录)")
        description = next(s for s in self.payload["sections"] if s["id"] == "quarter_highlights")["description"]
        story = self.source.get("quarter_story")
        if story:
            for item in story.get("undrawn", []):
                self.assertIn(item, description)
            # the exhibit numbers it names are the charts they name
            numbers = {ex["title"].split("：")[0]: ex["n"] for ex in self.exhibits}
            if "{ex:next_core_on_core}" in story["elsewhere"]:
                self.assertIn(f"第三节（Exhibit {numbers['核心商品毛利率同比变动']}）", description)
            prior = [ex["n"] for ex in self.by_section["settled"]
                     if ex["kind"] == "lines" and "上季阈值" in ex["title"]]
            if "{prior_charts}" in story["elsewhere"]:
                self.assertIn(f"Exhibit {prior[0]}–{prior[-1]}", description)
        bare = copy.deepcopy(self.source)
        bare.pop("quarter_story", None)
        stripped = next(s for s in build_payload(bare)["sections"] if s["id"] == "quarter_highlights")
        self.assertNotIn("本页不画的", stripped["description"])

    def test_the_call_only_quantities_are_named_and_not_plotted(self) -> None:
        """Three quantities the local note leans on reach no filing. The page has
        to say so rather than quietly omitting them."""
        notes = "\n".join(self.payload["notes"])
        for term in ("retail media", "有机会员费增速", "汽油对 comp 的百分点贡献"):
            self.assertIn(term, notes)
        # The call's own gasoline/currency split is quoted once, in the note
        # that refuses it. Anywhere else it would read as a published figure.
        self.assertEqual(sum(1 for note in self.payload["notes"] if "2.2pp" in note), 1)
        for exhibit in self.exhibits:
            # Naming a refused quantity in a caption is the point; plotting it
            # is what must not happen. So the gate is on titles and series
            # names, not on the prose that explains the refusal.
            self.assertNotIn("2.2pp", exhibit["title"])
            self.assertNotIn("retail media", exhibit["title"].lower())
            for series in exhibit.get("series", []) + exhibit.get("groups", []):
                self.assertNotIn("retail media", series["name"].lower())
            for field in ("title", "note", "src_extra"):
                self.assertNotIn("2.2pp", exhibit.get(field) or "")

    def test_no_market_expectation_is_published(self) -> None:
        """The page may SAY it publishes none; it may not publish one.

        The site's rules allow a dated, unattributed 市场预期 comparison point.
        Costco's consensus is not consistent across sources for this quarter, so
        the page carries none and says so -- which means the phrase appears in
        the notes and must not appear anywhere a reader would read as data.
        """
        self.assertIsNone(self.source["market_expectation"])
        self.assertIsNone(self.payload["guidance"])
        for exhibit in self.exhibits:
            self.assertNotIn("市场预期", exhibit["title"])
            for series in exhibit.get("series", []) + exhibit.get("groups", []):
                self.assertNotIn("市场预期", series["name"])
        for table in self.payload["tables"]:
            self.assertNotIn("市场预期", " ".join(table["headers"]))
        text = json.dumps(self.payload, ensure_ascii=False)
        for broker in ["FactSet", "Bloomberg", "LSEG", "consensus", "whisper"]:
            self.assertNotIn(broker.lower(), text.lower())

    # ── thresholds ──────────────────────────────────────────────────────────
    def test_section_one_settles_what_the_previous_report_left_open(self) -> None:
        """Held to `_checks["note"]`, the reports transcribed separately."""
        check_section_one(self, self.source, self.payload)

    def test_the_blocks_carry_the_reports_thresholds_verbatim(self) -> None:
        """The builder reads the blocks; the note was transcribed from the reports.

        Every threshold, direction and metric in the two blocks is the one the
        report wrote -- the previous report's section 8 for the settlement, this
        report's for the next quarter -- and nothing the page set for itself.
        """
        note = self.source["_checks"]["note"]
        prior = self.source["prior_kpi_settlement"]
        self.assertEqual(
            [(e["metric"], e["threshold"], e["direction"]) for e in prior["quantified"]]
            + [(item["metric"],) for item in prior["not_charted"]],
            [(t["metric"], t["threshold"], t["direction"]) for t in note["prior_thresholds"]
             if t["settled_on"] == "chart"]
            + [(t["metric"],) for t in note["prior_thresholds"] if t["settled_on"] == "table"])
        nxt = self.source["next_kpi"]
        self.assertEqual([(e["metric"], e["threshold"], e["direction"]) for e in nxt["quantified"]],
                         [(t["metric"], t["threshold"], t["direction"]) for t in note["next_thresholds"]])
        self.assertEqual([item["metric"] for item in nxt["not_charted"]], note["next_not_charted"])
        for block in (prior, nxt):
            for entry in block["quantified"]:
                with self.subTest(metric=entry["metric"]):
                    # a reading is computed, never typed into the block
                    self.assertNotIn("actual", entry)
                    self.assertNotIn("current", entry)
                    self.assertTrue(entry["quote"].strip())
        # The previous report is the one whose text says it covers the quarter
        # the settlement block names -- not the one its file name suggests.
        self.assertEqual(prior["set_in"], note["previous_covers"]["period"])
        self.assertEqual(self.source["followup_closure"]["set_in"], note["previous_covers"]["period"])

    def test_next_quarter_carries_this_report_s_section_8(self) -> None:
        note = self.source["_checks"]["note"]
        overview = self.by_section["next_quarter"][0]
        self.assertEqual(overview["kind"], "diverging_bars")
        self.assertTrue(overview["title"].startswith(f"下季 {len(note['next_thresholds'])} 条阈值："))
        self.assertEqual(overview["xlabels"], [t["metric"] for t in note["next_thresholds"]])
        table = next(t for t in self.payload["tables"] if t["title"].startswith("下季阈值"))
        self.assertEqual([row[0] for row in table["rows"]],
                         [t["metric"] for t in note["next_thresholds"]] + note["next_not_charted"])
        charts = self.by_section["next_quarter"][1:]
        self.assertTrue(charts[-1]["title"].startswith("现金及短期投资"), "the event line's tracking chart")
        for chart in charts[:-1]:
            self.assertRegex(chart["title"], r"：下季阈值 .+，当前 ")
        # Every quantified line is drawn: each threshold is a flat series of its own.
        drawn = {series["values"][0] for chart in charts[:-1] for series in chart["series"]
                 if series["name"].startswith("下季阈值") and len(set(series["values"])) == 1}
        self.assertEqual(drawn, {t["threshold"] for t in note["next_thresholds"]})
        description = next(s for s in self.payload["sections"] if s["id"] == "next_quarter")["description"]
        for metric in note["next_not_charted"]:
            self.assertIn(metric, description)

    def test_readings_are_computed_from_the_series(self) -> None:
        """Each bar is headroom against a reading computed here, not one the block typed."""
        now = readings(self.source)
        for key, section in (("prior_kpi_settlement", "settled"), ("next_kpi", "next_quarter")):
            entries = self.source[key]["quantified"]
            overview = next(ex for ex in self.by_section[section] if ex["kind"] == "diverging_bars")
            for entry, value in zip(entries, overview["values"]):
                with self.subTest(block=key, metric=entry["metric"]):
                    self.assertAlmostEqual(
                        headroom(entry["direction"], entry["threshold"], now[entry["reads"]]),
                        value, places=1)

    def test_the_verdict_words_follow_the_readings(self) -> None:
        """Both states, built here: a line held and a line broken.

        The page's words -- 守住 / 击穿 in section one, 没有一条越线 / 已越线 in
        section three -- have to come from the readings. Push the digital comp
        under its line, the US traffic under its line, and the core-on-core
        reading onto its line (which the analysis wrote as「≤ −10bp」, so equal
        breaks it); the titles must turn with them.
        """
        turned = copy.deepcopy(self.source)
        turned["comp_history_pct"]["digital_reported_pct"][-1] = 12.0
        turned["supplement"]["comp_traffic_us_pct"][-1] = 1.4
        turned["core_on_core"]["change_bps"][-1] = -10
        turned["supplement"]["core_on_core_bps"][-1] = -10
        payload = build_payload(turned)
        settled = next(s for s in payload["sections"] if s["id"] == "settled")["exhibits"]
        nxt = next(s for s in payload["sections"] if s["id"] == "next_quarter")["exhibits"]
        before_settled = self.by_section["settled"]
        digital = next(ex for ex in settled if ex["title"].startswith("数字化同店销售"))
        self.assertIn("击穿上季阈值", digital["title"])
        self.assertIn("守住上季阈值", next(ex for ex in before_settled
                                       if ex["title"].startswith("数字化同店销售"))["title"])
        self.assertIn("1 条击穿", settled[1]["title"])
        # +12% is still above the analysis's harsher +10% line
        self.assertNotIn("碰到了更严的那条线", settled[1]["title"])
        self.assertIn("已越线", nxt[0]["title"])
        self.assertIn("美国同店客流（补充跟踪）", nxt[0]["title"].split("已越线")[0])
        self.assertIn("核心商品毛利率同比变动", nxt[0]["title"].split("已越线")[0])
        core = next(ex for ex in nxt if ex["title"].startswith("核心商品毛利率同比变动"))
        self.assertIn("连续第一季，还不够", core["note"])
        # a second quarter in a row on the line fires the analysis's own trigger
        turned["core_on_core"]["change_bps"][-2] = -12
        again = build_payload(turned)
        core = next(ex for ex in next(s for s in again["sections"] if s["id"] == "next_quarter")["exhibits"]
                    if ex["title"].startswith("核心商品毛利率同比变动"))
        self.assertIn("连续第二季，触发", core["note"])

    def test_the_closure_tally_is_counted_from_the_items(self) -> None:
        moved = copy.deepcopy(self.source)
        moved["followup_closure"]["items"][3]["verdict"] = "部分确认"
        chart = next(s for s in build_payload(moved)["sections"] if s["id"] == "settled")["exhibits"][0]
        counts = dict(zip(chart["xlabels"], chart["values"]))
        before = dict(zip(self.by_section["settled"][0]["xlabels"], self.by_section["settled"][0]["values"]))
        self.assertEqual(counts["部分确认"], before["部分确认"] + 1)
        self.assertEqual(counts["仍在跟踪"], before["仍在跟踪"] - 1)
        moved["followup_closure"]["items"][0]["verdict"] = "已兑现"
        with self.assertRaisesRegex(ValueError, "not labels"):
            build_payload(moved)

    # ── page mechanics ──────────────────────────────────────────────────────
    def test_the_page_has_the_site_s_four_sections_in_order(self) -> None:
        """The owner's four-part format, titles verbatim (TSM is the reference)."""
        self.assertEqual(
            [(section["id"], section["title"]) for section in self.payload["sections"]],
            [("settled", "一、上季跟踪指标兑现了吗"), ("quarter_highlights", "二、本季重点"),
             ("next_quarter", "三、下季要跟踪什么"), ("routine", "四、长期常规跟踪")])
        for section in self.payload["sections"]:
            self.assertTrue(section["exhibits"], section["id"])
        self.assertIn("本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列",
                      self.payload["notes"][0])

    def test_the_company_s_own_guidance_closes_section_one(self) -> None:
        """Section one settles what the previous analysis left open first and the
        company's own records -- capital plan, opening plan, year-end store count --
        after it; the store-count estimate is guidance, not a next-quarter line."""
        titles = [ex["title"] for ex in self.by_section["settled"]]
        own = [i for i, title in enumerate(titles)
               if title.startswith(("资本开支计划与实际", "实际资本开支相对计划中值的偏离",
                                    "计划开店数与实际开店数", "公司自己估的财年末仓库数"))]
        self.assertEqual(len(own), 4)
        self.assertEqual(own, list(range(len(titles) - 4, len(titles))))
        for section in ("quarter_highlights", "next_quarter", "routine"):
            self.assertFalse(any(ex["title"].startswith("公司自己估的财年末仓库数")
                                 for ex in self.by_section[section]), section)

    def test_exhibit_numbers_run_without_a_gap(self) -> None:
        self.assertEqual([ex["n"] for ex in self.exhibits],
                         list(range(1, len(self.exhibits) + 1)))
        first = self.exhibits[-1]["n"] + 1
        self.assertEqual([table["n"] for table in self.payload["tables"]],
                         list(range(first, first + len(self.payload["tables"]))))

    def test_no_exhibit_carries_an_unresolved_reference(self) -> None:
        for exhibit in self.exhibits:
            self.assertNotIn("ref", exhibit, f"exhibit {exhibit['n']}")
            for field in ("title", "note", "src_extra", "annot"):
                self.assertNotIn("{EX_", exhibit.get(field) or "", f"exhibit {exhibit['n']}")

    def test_escaped_text_fields_carry_no_markup(self) -> None:
        """`page.js` runs these through esc(), so a tag prints as literal text."""
        for key in ("headline", "title", "subtitle", "tracker"):
            self.assertNotIn("<", self.payload[key])
        for note in self.payload["notes"]:
            self.assertNotIn("<", note)
        for section in self.payload["sections"]:
            self.assertNotIn("<", section["title"])
            self.assertNotIn("<", section["description"])
        for table in self.payload["tables"]:
            self.assertNotIn("<", table["title"])

    def test_the_cross_page_capex_table_is_carried_and_explained(self) -> None:
        table = next(t for t in self.payload["tables"] if "AI capex" in t["title"])
        self.assertEqual(len(table["rows"]), 8)
        explanation = "\n".join(self.payload["notes"])
        self.assertIn("AI capex", explanation)
        self.assertIn("不在这条链", explanation)

    def test_sources_are_official_http_links(self) -> None:
        for source in self.payload["source_links"]:
            parsed = urlparse(source["url"])
            self.assertEqual(parsed.scheme, "https")
            self.assertEqual(parsed.hostname, "www.sec.gov")

    def test_published_payload_matches_a_fresh_build(self) -> None:
        self.assertEqual(js_payload(ROOT / "data" / "cost.js", "window.DASH"), self.payload)

    def test_roster_and_shell(self) -> None:
        roster = js_payload(ROOT / "data" / "roster.js", "window.ROSTER")
        self.assertEqual(roster, roster_payload(build_all()))
        entry = next(item for item in roster["items"] if item["slug"] == "cost")
        self.assertEqual(entry["group"], "consumer_retail")
        self.assertEqual(entry["latest_label"], self.payload["latest"]["disclosed_period_label"])
        shell = (ROOT / "cost" / "index.html").read_text(encoding="utf-8")
        self.assertIn("../data/cost.js", shell)
        self.assertNotIn("../data/tjx.js", shell)

    def test_the_home_page_lists_and_counts_this_company(self) -> None:
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="cost/"', home)
        self.assertIn(self.payload["latest"]["release_date"], home)
        self.assertIn(f'{len(ENTRIES)} 家公司', home)
        self.assertEqual(home.count('class="hcard"'), len(ENTRIES))

    def test_compact_period(self) -> None:
        self.assertEqual(compact_period("Q2 2026"), "Q2'26")

    # ── a roll edits the series and nothing else ─────────────────────────────
    def test_the_fy1995_plan_is_the_filed_aggregate(self) -> None:
        """The FY1994 10-K says "approximately $600 million to $700 million during
        fiscal 1995", one aggregate; the record held 550 for the low end until
        2026-09-19. The note that quotes it and the chart that draws it now agree."""
        full = self.source["capex_record_full"]
        at = full["guided_fiscal_years"].index(1995)
        self.assertEqual((full["guided_low_usd_m"][at], full["guided_high_usd_m"][at]), (600.0, 700.0))
        self.assertAlmostEqual(full["deviation_vs_opening_pct"][at],
                               (full["actual_usd_m"][at] / 650.0 - 1) * 100, places=5)
        band = next(ex for ex in self.by_section["settled"] if "资本开支计划与实际" in ex["title"])
        self.assertIn("US$600–700M", band["note"])
        self.assertIn("$600 million to $700 million", "\n".join(self.payload["notes"]))

    def test_the_filing_lags_come_from_the_filings(self) -> None:
        """Every lag is a filing date less a fiscal year's first day, and the two
        records that carry one agree wherever both do."""
        full, recent = self.source["capex_record_full"], self.source["capex_guidance"]
        by_year = dict(zip(full["guided_fiscal_years"], zip(full["guidance_filed_on"],
                                                          full["lag_days_into_guided_year"])))
        for year, filed, lag in zip(recent["guided_fiscal_years"], recent["guidance_filed_on"],
                                    recent["lag_days_into_guided_year"]):
            with self.subTest(year=year):
                self.assertEqual(by_year[year], (filed, lag))
        early = [lag for year, (_, lag) in by_year.items() if year <= 2007]
        band = next(ex for ex in self.by_section["settled"] if "资本开支计划与实际" in ex["title"])
        self.assertIn(f"第 {min(early)} 到 {max(early)} 天", band["note"])

    def test_quarter_blocks_refuse_to_publish_under_another_quarter(self) -> None:
        for key in ("prior_kpi_settlement", "next_kpi", "local_note", "followup_closure"):
            stale = copy.deepcopy(self.source)
            stale[key]["period"] = "Q1 1999"
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    build_payload(stale)

    def test_a_later_quarter_cannot_skip_the_settlement(self) -> None:
        """Any quarter after the first analysis has a previous one by construction,
        so a roll that drops both settlement blocks stops the build; so does one
        that drops the next quarter's thresholds."""
        bare = copy.deepcopy(self.source)
        for key in ("followup_closure", "prior_kpi_settlement"):
            del bare[key]
        with self.assertRaisesRegex(ValueError, "not the first Costco analysis"):
            build_payload(bare)
        bare = copy.deepcopy(self.source)
        del bare["next_kpi"]
        with self.assertRaisesRegex(ValueError, "next_kpi"):
            build_payload(bare)

    def test_the_first_analysis_settles_only_the_company_s_guidance(self) -> None:
        """The other state, built here: the quarter of the first analysis."""
        first = copy.deepcopy(self.source)
        first["analysis_record"]["first_period"] = first["periods"][-1]
        # the quarter's story points at the settlement charts, so it goes with them
        for key in ("followup_closure", "prior_kpi_settlement", "quarter_story"):
            del first[key]
        first["_checks"]["note"]["previous_covers"] = None
        payload = build_payload(first)
        check_section_one(self, first, payload)
        with self.assertRaisesRegex(ValueError, "nothing for"):
            with_blocks = copy.deepcopy(first)
            with_blocks["followup_closure"] = self.source["followup_closure"]
            build_payload(with_blocks)

    def test_the_local_report_s_own_claims_leave_with_their_block(self) -> None:
        bare = copy.deepcopy(self.source)
        del bare["local_note"]
        text = json.dumps(build_payload(bare), ensure_ascii=False)
        self.assertNotIn("「结构性", text)
        self.assertIn("「结构性", json.dumps(self.payload, ensure_ascii=False))

    def test_the_prose_claims_follow_the_data(self) -> None:
        """Turn two readings around and the sentences that described them must go."""
        turned = copy.deepcopy(self.source)
        deck = turned["supplement"]
        deck["comp_traffic_pct"][-1] = deck["comp_traffic_pct"][-2] + 1.0
        deck["comp_ticket_pct"][-1] = deck["comp_ticket_pct"][-2] - 1.0
        before = json.dumps(self.payload, ensure_ascii=False)
        after = json.dumps(build_payload(turned), ensure_ascii=False)
        for claim in ("客流在走软", "缺口由客单补上", "客单在补位"):
            with self.subTest(claim=claim):
                self.assertIn(claim, before)
                self.assertNotIn(claim, after)


def next_quarter(label: str) -> str:
    quarter, year = label.split()
    number = int(quarter[1])
    return f"Q{number % 4 + 1} {int(year) + (number == 4)}"


def later(day: str, days: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()


def rolled_forward(staging: dict) -> dict:
    """The series as a data-only roll to the next quarter would leave it, in memory.

    Every aligned block gains one cell -- the same quarter a year earlier, so the
    identities the real quarters satisfy still hold and the rehearsal tests the
    mechanics rather than invented figures. The eight-quarter window slides; the
    long records grow. The one-quarter blocks go the way a roll takes them: this
    quarter's `next_kpi` list moves, as it stood, into `prior_kpi_settlement`, a
    `followup_closure` judges three rehearsal questions, `next_kpi` is
    re-stamped, and the local report's own claims (`local_note`, `quarter_story`)
    are dropped. `_checks` and its note are re-keyed from the new cells. Nothing
    is written to disk.
    """
    s = copy.deepcopy(staging)
    period = s["periods"][-1]
    new = next_quarter(period)
    quarter, year = new.split()
    year_ago = f"{quarter} {int(year) - 1}"
    fiscal = cost.fiscal_label_of(new)

    def slide(block: dict, key: str, at: int) -> None:
        value = copy.deepcopy(block[key][at])
        block[key].pop(0)
        block[key].append(value)

    # the eight-quarter window
    at = s["periods"].index(year_ago)
    end = later(s["period_ends"][at], 364)
    release = later(s["release_dates"][at], 364)
    for key in ("periods", "fiscal_labels", "period_ends", "release_dates", "weeks", "yoy_week_mismatch"):
        slide(s, key, at)
    s["periods"][-1], s["fiscal_labels"][-1] = new, fiscal
    s["period_ends"][-1], s["release_dates"][-1], s["yoy_week_mismatch"][-1] = end, release, False
    s["weeks_by_period"][new] = s["weeks_by_period"][year_ago]
    for name in s["financials"]:
        slide(s["financials"], name, at)

    def windowed(block: dict) -> None:
        where = block["periods"].index(year_ago)
        for key, value in list(block.items()):
            if isinstance(value, list) and len(value) == len(block["periods"]):
                slide(block, key, where)
            elif isinstance(value, dict):
                for inner in value:
                    if isinstance(value[inner], list) and len(value[inner]) == len(block["periods"]):
                        slide(value, inner, where)
        block["periods"][-1] = new

    for name in ("comparable_sales_pct", "segments_usd_m", "merchandise_categories", "cash_flow_usd_m"):
        windowed(s[name])

    # the long records
    def grown(block: dict) -> None:
        where = block["periods"].index(year_ago)
        width = len(block["periods"])
        for key, value in list(block.items()):
            if isinstance(value, list) and len(value) == width and key != "periods":
                value.append(copy.deepcopy(value[where]))
        block["periods"].append(new)
        if "fiscal_labels" in block:
            block["fiscal_labels"][-1] = fiscal
        if "period_ends" in block:
            block["period_ends"][-1] = end

    for name in ("comp_history_pct", "eps_growth_bridge_pct", "mdna_margins_pct", "membership",
                 "balance_sheet_usd_m", "supplement", "core_on_core", "warehouse_estimate"):
        grown(s[name])
    hist = s["comp_history_pct"]
    # the digital line stays on the definition it has now
    hist["digital_metric_name"][-1] = hist["digital_metric_name"][-2]
    hist["digital_reported_pct"][-1] = hist["digital_reported_pct"][-2]
    est = s["warehouse_estimate"]
    est["target_fiscal_year"][-1] += 1

    s["latest"] = {**s["latest"], "period": new, "fiscal_label": fiscal, "period_end": end,
                   "release_date": release, "weeks": s["weeks"][-1]}
    s["sources"].insert(0, {"label": f"Costco {fiscal} 业绩新闻稿（换季演练）",
                            "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000909832&type=8-K"})

    kpi = s["next_kpi"]
    labels = ["看多确认", "部分确认", "证伪"]
    items = [{"question": f"演练问题 {i}", "short": f"演练 {i}", "verdict": verdict, "evidence": "换季演练"}
             for i, verdict in enumerate(["看多确认", "看多确认", "证伪"], 1)]
    s["followup_closure"] = {"period": new, "set_in": period, "set_in_file": kpi["set_in_file"],
                             "closed_in": "换季演练", "labels": labels, "rule": "换季演练。", "reading": "",
                             "items": items}
    s["prior_kpi_settlement"] = {
        "period": new, "set_in": period, "set_in_file": kpi["set_in_file"],
        "quantified": copy.deepcopy(kpi["quantified"]),
        "not_charted": [{"metric": item["metric"], "threshold_text": item["threshold_text"],
                         "reading": "换季演练", "verdict": "换季演练", "quote": item["quote"]}
                        for item in kpi["not_charted"]],
    }
    s["next_kpi"] = {**copy.deepcopy(kpi), "period": new, "set_in": new, "set_in_file": "换季演练"}
    for name in ("local_note", "quarter_story"):
        s.pop(name, None)

    fin = s["financials"]
    checks = s["_checks"]
    checks.update({
        "period": new, "fiscal_label": fiscal, "period_end": end, "release_date": release,
        "weeks": s["weeks"][-1], "source": "换季演练：各格取自去年同季，不是申报读数",
        **{key: fin[key][-1] for key in ("net_sales_usd_m", "membership_fees_usd_m", "total_revenue_usd_m",
                                         "operating_income_usd_m", "net_income_usd_m", "diluted_eps_usd")},
    })
    note = checks["note"]
    checks["note"] = {
        **note,
        "source": {"this_quarter": "换季演练", "previous_quarter": note["source"]["this_quarter"]},
        "previous_covers": {"period": period, "fiscal_label": staging["fiscal_labels"][-1], "why": "换季演练"},
        "followup_closure": {"total": len(items),
                             "counts": {label: sum(1 for item in items if item["verdict"] == label)
                                        for label in labels},
                             "verdicts": [item["verdict"] for item in items]},
        "prior_thresholds": ([{**t, "settled_on": "chart"} for t in note["next_thresholds"]]
                             + [{"metric": metric, "settled_on": "table"} for metric in note["next_not_charted"]]),
    }
    return s


class CostRollRehearsalTest(unittest.TestCase):
    """The next quarters, rolled in memory by editing the series alone (CLAUDE.md §9).

    The builder must take a rolled series without a code change: section one
    then settles this quarter's section-three lines against the new readings,
    and the shared window census must still hold, because the settlement
    charts it adds move every exhibit number after them. Two rolls, so the
    second settles a block that the first one wrote.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads((ROOT / "series" / "cost.json").read_text(encoding="utf-8"))
        cls.rolls = []
        staging = cls.staging
        for _ in range(2):
            staging = rolled_forward(staging)
            cls.rolls.append((staging, build_payload(staging)))
        # a stressed quarter: every reading the settlement reads pushed to the wrong side
        stressed = rolled_forward(cls.staging)
        stressed["comp_history_pct"]["adjusted_total_pct"][-1] = 5.2
        stressed["comp_history_pct"]["gap_pp"][-1] = round(
            stressed["comp_history_pct"]["reported_total_pct"][-1] - 5.2, 6)
        stressed["membership"]["renewal_rate_us_canada_pct"][-1] = 91.9
        stressed["core_on_core"]["change_bps"][-1] = -12
        stressed["supplement"]["core_on_core_bps"][-1] = -12
        stressed["supplement"]["comp_traffic_us_pct"][-1] = 1.2
        cls.stressed = (stressed, build_payload(stressed))

    def variants(self):
        return self.rolls + [self.stressed]

    def test_the_next_quarters_build_from_the_series_alone(self) -> None:
        previous = self.staging["periods"][-1]
        for staging, payload in self.rolls:
            period = staging["periods"][-1]
            with self.subTest(period=period):
                self.assertEqual(period, next_quarter(previous))
                previous = period
        for staging, payload in self.variants():
            with self.subTest(period=staging["periods"][-1]):
                guard_payload(payload)
                self.assertIn(staging["periods"][-1], payload["title"])
                self.assertEqual([(s["id"], s["title"]) for s in payload["sections"]],
                                 [("settled", "一、上季跟踪指标兑现了吗"), ("quarter_highlights", "二、本季重点"),
                                  ("next_quarter", "三、下季要跟踪什么"), ("routine", "四、长期常规跟踪")])
                exhibits = [ex for section in payload["sections"] for ex in section["exhibits"]]
                self.assertTrue(all(section["exhibits"] for section in payload["sections"]))
                self.assertEqual([ex["n"] for ex in exhibits], list(range(1, len(exhibits) + 1)))
                for ex in exhibits:
                    for key in ("title", "note", "src_extra"):
                        self.assertNotIn("{", ex.get(key) or "", ex["title"])
                    for series in ex.get("series", []) + ex.get("groups", []):
                        self.assertEqual(len(series["values"]), len(ex["xlabels"]), ex["title"])
                # ...and the builder still never reads `_checks`.
                self.assertEqual(build_payload({k: v for k, v in staging.items() if k != "_checks"}), payload)

    def test_section_one_settles_this_quarter_s_lines(self) -> None:
        """Held to the rolled note, with every verdict recomputed here from the rolled readings."""
        for staging, payload in self.variants():
            with self.subTest(period=staging["periods"][-1]):
                check_section_one(self, staging, payload)
                settled = payload["sections"][0]
                self.assertNotIn("第一份季报分析", settled["description"])
                entries = staging["prior_kpi_settlement"]["quantified"]
                now = readings(staging)
                broken = [entry for entry in entries if on_wrong_side(entry, now[entry["reads"]])]
                overview = settled["exhibits"][1]
                for entry, value in zip(entries, overview["values"]):
                    self.assertAlmostEqual(headroom(entry["direction"], entry["threshold"], now[entry["reads"]]),
                                           value, places=1, msg=entry["id"])
                if broken:
                    self.assertIn(f"{len(entries) - len(broken)} 条守住、{len(broken)} 条击穿", overview["title"])
                else:
                    self.assertIn("全部守住", overview["title"])
                table = next(t for t in payload["tables"] if t["title"].startswith("上季阈值与本季读数"))
                self.assertEqual([row[5].split("，")[0] for row in table["rows"][:len(entries)]],
                                 ["击穿" if entry in broken else "守住" for entry in entries])
        # the stressed quarter really is stressed, and the consecutive rule is applied
        staging, payload = self.stressed
        self.assertIn("击穿", payload["sections"][0]["exhibits"][1]["title"])
        core = next(ex for ex in payload["sections"][0]["exhibits"]
                    if ex["title"].startswith("核心商品毛利率同比变动"))
        self.assertIn("击穿上季阈值", core["title"])
        self.assertIn("连续第一季，还不够", core["note"])

    def test_the_rolled_pages_keep_the_shared_window_census(self) -> None:
        """What `test_chart_window` would say of each rolled page, run on it here."""
        import tests.test_chart_window as window   # a module, so no TestCase is re-collected

        published = js_payload(ROOT / "data" / "cost.js", "window.DASH")
        for staging, payload in self.variants():
            with self.subTest(period=staging["periods"][-1]):
                exhibits = [ex for section in payload["sections"] for ex in section["exhibits"]]
                timed = [(ex, window.first_year(ex)) for ex in exhibits]
                timed = [(ex, year) for ex, year in timed if year is not None]
                reached = sum(1 for _, year in timed if year <= window.TARGET_YEAR)
                self.assertEqual(reached, window.REACH_2016["cost"] - window.cost_threshold_reach(published)
                                 + window.cost_threshold_reach(payload))
                for ex, year in timed:
                    if year > window.TARGET_YEAR:
                        matched = [key for key in window.CONVERTED["cost"] if window.key_matches(key, ex["title"])]
                        self.assertEqual(len(matched), 1, ex["title"])
                census = window.ProseQuarterCountTest
                page_ok = set()
                for ex in exhibits:
                    page_ok |= census._derivable(ex)[1]
                for ex in exhibits:
                    n, ok = census._derivable(ex)
                    if n < 12:
                        continue
                    ok |= page_ok
                    prose = " ".join(ex.get(field) or "" for field in ("title", "note", "subtitle")
                                     if isinstance(ex.get(field), str))
                    if {int(m.group(1)) for m in census.ANCHOR.finditer(prose)} & ok:
                        continue
                    loose = sorted({int(m.group(1)) for m in census.COUNT.finditer(prose)
                                    if int(m.group(1)) >= 12} - ok)
                    self.assertEqual(loose, [], ex["title"])


class CostChecksTest(unittest.TestCase):
    """The page's quarter against `_checks`, keyed separately from the release.

    Same contract as the other migrated pages: the builder never reads `_checks`
    (asserted in `test_data_only_roll`), a roll re-keys it from the new release
    and deck, and nothing in this class changes with the quarter. Where the
    company prints a figure the page also computes -- the margin changes in
    basis points, the comp gap, the Executive share's two legs -- the page must
    land on what the company printed.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "cost.json").read_text(encoding="utf-8"))
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
        self.assertIn(f"周截至 {checks['period_end']} · 发布 {checks['release_date']}",
                      self.payload["subtitle"])
        self.assertEqual(self.source["weeks"][-1], checks["weeks"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        checks, source = self.checks, self.source
        fin = source["financials"]
        for key, check in (("net_sales_usd_m", "net_sales_usd_m"),
                           ("membership_fees_usd_m", "membership_fees_usd_m"),
                           ("total_revenue_usd_m", "total_revenue_usd_m"),
                           ("operating_income_usd_m", "operating_income_usd_m"),
                           ("net_income_usd_m", "net_income_usd_m"),
                           ("diluted_eps_usd", "diluted_eps_usd")):
            with self.subTest(field=key):
                self.assertEqual(fin[key][-1], checks[check])
        self.assertEqual(round(fin["net_sales_yoy_pct"][-1], 1), checks["net_sales_yoy_pct"])
        hist = source["comp_history_pct"]
        self.assertEqual(hist["reported_total_pct"][-1], checks["comparable_sales_total_pct"])
        self.assertEqual(hist["adjusted_total_pct"][-1], checks["comparable_sales_adjusted_total_pct"])
        self.assertEqual(hist["digital_reported_pct"][-1], checks["digitally_enabled_comparable_sales_pct"])
        bal = source["balance_sheet_usd_m"]
        self.assertEqual(bal["cash_and_short_term_investments_usd_m"][-1],
                         checks["cash_and_equivalents_usd_m"] + checks["short_term_investments_usd_m"])
        deck = source["supplement"]
        self.assertEqual(deck["comp_traffic_pct"][-1], checks["comparable_traffic_pct"])
        self.assertEqual(deck["comp_ticket_pct"][-1], checks["comparable_ticket_pct"])
        self.assertEqual(deck["adjusted_comp_ticket_pct"][-1], checks["adjusted_comparable_ticket_pct"])
        self.assertEqual(deck["executive_members_mm"][-1], checks["executive_members_mm"])
        self.assertEqual(deck["paid_members_mm"][-1], checks["paid_members_mm"])
        self.assertEqual(deck["core_on_core_bps"][-1], checks["core_on_core_bps"])
        mem = source["membership"]
        self.assertEqual(mem["renewal_rate_us_canada_pct"][-1], checks["renewal_rate_us_canada_pct"])
        self.assertEqual(mem["renewal_rate_worldwide_pct"][-1], checks["renewal_rate_worldwide_pct"])
        mdna = source["mdna_margins_pct"]
        at = mdna["periods"].index(checks["period"])
        # A fiscal fourth quarter has no 10-Q, so the MD&A block holds no figure
        # there; the page then prints the dollars' bps, and the assertion in
        # `test_the_page_prints_what_the_company_printed` still holds it to the
        # figure `_checks` read off the deck.
        if mdna["gross_margin_change_bps"][at] is not None:
            self.assertEqual(mdna["gross_margin_change_bps"][at], checks["gross_margin_change_bps"])
            self.assertEqual(mdna["sga_change_bps"][at], checks["sga_rate_change_bps"])
        else:
            self.assertTrue(checks["fiscal_label"].endswith("Q4"), "only a fiscal Q4 has no MD&A figure")
        self.assertEqual(source["warehouse_estimate"]["fy_end_estimate"][-1], checks["fy_end_warehouse_estimate"])

    def test_the_page_prints_what_the_company_printed(self) -> None:
        checks = self.checks
        self.assertIn(f"总收入 US${checks['total_revenue_usd_m']:,}M", self.payload["headline"])
        self.assertIn(f"报告 comp {checks['comparable_sales_total_pct']:+.1f}%", self.payload["headline"])
        self.assertIn(f"comp 是 {checks['comparable_sales_adjusted_total_pct']:+.1f}%", self.payload["headline"])
        self.assertEqual(headline_metrics(self.source)[0],
                         f"Revenue ${checks['total_revenue_usd_m'] / 1000:.1f}B")
        self.assertEqual(headline_metrics(self.source)[1],
                         f"调整后 comp {checks['comparable_sales_adjusted_total_pct']:+.1f}%")
        # The margin bridge quotes the company's own basis points, not the ones the
        # dollars round to: SG&A comes to -20.9bp from the statement, the MD&A says 20.
        margins = self.exhibit("毛利率 ")
        self.assertIn(f"毛利率 {checks['gross_margin_change_bps']:+d}bp".replace("-", "−"), margins["note"])
        self.assertIn(f"SG&A 率 {checks['sga_rate_change_bps']:+d}bp".replace("-", "−"), margins["note"])
        traffic = self.exhibit("客流与客单")
        self.assertIn(f"本季客流 {checks['comparable_traffic_pct']:+.1f}%", traffic["title"])
        self.assertIn(f"客单 {checks['adjusted_comparable_ticket_pct']:+.1f}%", traffic["title"])
        execs = self.exhibit(f"Executive 会员 {checks['executive_members_mm']:.1f}MM")
        self.assertIn(f"{checks['executive_members_mm'] / checks['paid_members_mm'] * 100:.1f}%", execs["title"])
        share = self.exhibit("Executive 会员占付费会员：")
        self.assertIn(f"本季 {checks['executive_members_mm'] / checks['paid_members_mm'] * 100:.1f}%",
                      share["title"])
        us_traffic = self.exhibit("美国同店客流")
        self.assertIn(f"当前 {checks['comparable_traffic_us_pct']:+.1f}%", us_traffic["title"])
        core = next(ex for ex in self.exhibits if ex["title"].startswith("核心商品"))
        self.assertIn(f"当前 {checks['core_on_core_bps']:+.0f}bp".replace("-", "−"), core["title"])
        # EPS growth is the rate the company prints (the deck's「+15.2% Growth」),
        # not the four legs' unrounded product a few hundredths away.
        bridge = self.exhibit("每股收益增速拆成四条腿")
        self.assertIn(f"本季 {checks['diluted_eps_growth_printed_pct']:+.1f}% 里", bridge["title"])
        self.assertIn(f"每股收益 {checks['diluted_eps_growth_printed_pct']:+.1f}% 对营业利润",
                      self.payload["headline"])
        estimate = next(ex for ex in self.exhibits if ex["title"].startswith("公司自己估的财年末仓库数"))
        self.assertIn(f"{checks['fy_end_warehouse_estimate']} 家", estimate["title"])


if __name__ == "__main__":
    unittest.main()
