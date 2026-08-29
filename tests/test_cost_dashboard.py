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

import json
import re
import sys
import unittest
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.all import ENTRIES, build_all, roster_payload  # noqa: E402
from build.board import headroom  # noqa: E402
from build.cost import build_payload, compact_period  # noqa: E402


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


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
        self.assertEqual(self.source["periods"][-1], "Q2 2026")
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
        self.assertEqual(weeks, [16, 12, 12, 12, 16, 12, 12, 12])
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
        mismatch = [period for period, flag
                    in zip(self.source["periods"], self.source["yoy_week_mismatch"]) if flag]
        self.assertEqual(mismatch, ["Q3 2024"])
        contribution = self.source["merchandise_categories"]["net_sales_yoy_pct"]
        index = self.source["periods"].index("Q3 2024")
        self.assertLess(contribution[index], 2.0)
        self.assertGreater(min(v for i, v in enumerate(contribution) if i != index), 6.0)
        cats = next(ex for ex in self.by_section["quarter_highlights"]
                    if "四条商品线" in ex["title"])
        self.assertIn("Q3'24", cats.get("annot", ""))
        self.assertIn("17 周", cats["note"])

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
        self.assertEqual(derived, ["Q3 2024", "Q3 2025"])
        for period in derived:
            index = self.source["periods"].index(period)
            total = sum(self.seg[key]["revenue_usd_m"][index]
                        for key in ("united_states", "canada", "other_international"))
            self.assertEqual(total, self.fin["total_revenue_usd_m"][index])
        chart = next(ex for ex in self.by_section["quarter_highlights"]
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
        self.assertEqual(len(bridge["periods"]), 11)
        self.assertEqual(bridge["periods"][-1], "Q2 2026")
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
        self.assertEqual(len(ann["fiscal_years"]), 13)
        for index, year in enumerate(ann["fiscal_years"]):
            with self.subTest(year=year):
                self.assertAlmostEqual(
                    ann["merchandising_leg_pct_of_net_sales"][index]
                    + ann["membership_leg_pct_of_net_sales"][index],
                    ann["operating_margin_on_net_sales_pct"][index],
                    places=4)
        # And the finding the chart states, pinned by value rather than by prose.
        self.assertGreater(ann["membership_fee_share_of_operating_income_pct"][0], 74.0)
        self.assertLess(ann["membership_fee_share_of_operating_income_pct"][-1], 52.0)
        self.assertLess(ann["membership_leg_pct_of_net_sales"][-1]
                        - ann["merchandising_leg_pct_of_net_sales"][-1], 0.15)

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
        # No sixteen-week spike survives the normalisation.
        values = [v for v in mem["annualised_fee_per_paid_member_usd"] if v is not None]
        self.assertLess(max(values) / min(values), 1.2)

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
        self.assertEqual(self.hist["periods"][0], "Q4 2019")
        self.assertEqual(len(self.hist["periods"]), 27)
        self.assertEqual(set(self.hist["adjustment_basis"]), {"gasoline_and_fx"})
        for index in range(len(self.hist["periods"])):
            self.assertAlmostEqual(
                self.hist["reported_total_pct"][index]
                - self.hist["adjusted_total_pct"][index],
                self.hist["gap_pp"][index], places=6)

    def test_the_gap_finding_is_pinned_by_value(self) -> None:
        """The page's sharpest claim: gasoline and currency have suppressed the
        headline more often than they have flattered it."""
        gap = self.hist["gap_pp"]
        negative = sum(1 for value in gap if value < 0)
        self.assertEqual((negative, len(gap)), (15, 27))
        self.assertAlmostEqual(gap[-1], 3.2, places=6)
        self.assertEqual([round(value, 1) for value in gap[-4:]], [-0.7, 0.0, 0.7, 3.2])
        chart = next(ex for ex in self.by_section["quarter_highlights"]
                     if "抬高（或压低）" in ex["title"])
        self.assertIn(f"{negative} 季", chart["title"])

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
        self.assertEqual([round(v, 1) for v in release[-3:]], [6.4, 6.7, 6.6])
        self.assertEqual(filed[-3:], [6.0, 7.0, 7.0])
        table = next(t for t in self.payload["tables"] if "同店销售完整记录" in t["title"])
        self.assertEqual(len(table["rows"]), 27)

    def test_the_digital_metric_break_is_marked_not_spliced(self) -> None:
        names = self.hist["digital_metric_name"]
        index = self.hist["digital_break_index"]
        self.assertEqual(set(names[:index]), {"E-commerce"})
        self.assertEqual(set(names[index:]), {"Digitally-Enabled"})
        self.assertEqual(self.hist["periods"][index], "Q4 2025")

    def test_renewal_rates_are_plotted_only_where_they_have_a_decimal(self) -> None:
        mem = self.source["membership"]
        start = mem["renewal_decimal_from_index"]
        self.assertEqual(mem["periods"][start], "Q1 2023")
        for value in mem["renewal_rate_us_canada_pct"][:start]:
            self.assertEqual(value, round(value), "pre-decimal era is whole points")
        chart = next(ex for ex in self.by_section["settled"] if "会员续费率" in ex["title"])
        self.assertEqual(len(chart["xlabels"]), len(mem["periods"]) - start)

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
    def test_threshold_current_values_come_from_the_series(self) -> None:
        current = {entry["metric"]: entry["current"]
                   for entry in self.source["next_kpi"]["quantified"]}
        self.assertAlmostEqual(current["调整后合并 comp"],
                               self.hist["adjusted_total_pct"][-1], places=6)
        self.assertAlmostEqual(current["美加会员续费率"],
                               self.source["membership"]["renewal_rate_us_canada_pct"][-1],
                               places=6)

    def test_every_threshold_entry_is_renderable(self) -> None:
        for block, key in (("prior_kpi", "actual"), ("next_kpi", "current")):
            for entry in self.source[block]["quantified"]:
                with self.subTest(block=block, metric=entry["metric"]):
                    self.assertIn(entry["direction"], ("up", "down"))
                    self.assertNotEqual(entry["threshold"], 0)
                    self.assertIsInstance(headroom(entry["direction"], entry["threshold"],
                                                   entry[key]), float)

    # ── page mechanics ──────────────────────────────────────────────────────
    def test_section_order_and_sizes(self) -> None:
        self.assertEqual([section["id"] for section in self.payload["sections"]],
                         ["settled", "quarter_highlights", "next_quarter", "routine"])
        for section in self.payload["sections"]:
            self.assertGreaterEqual(len(section["exhibits"]), 4, section["id"])

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


if __name__ == "__main__":
    unittest.main()
