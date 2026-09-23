"""Checks for the AMZN page.

Four things here can break silently on a quarter roll, and each one has a test:

* the three segments must still sum to the consolidated statement, and the seven
  product lines to total net sales -- both series are stitched from two document
  types (10-Q segment notes for Q1–Q3, the Q4 press release for the fiscal
  fourth), so a mis-stitch shows up as a sum that no longer closes;
* the quarterly values must still add to the filed year, within the ±1
  rounding the rest of this repo already lives with;
* the guided record must still be paired guide-to-actual on the *right*
  quarter -- the whole first section is worthless if a release's Outlook block
  ever gets matched to the quarter it reports rather than the one it guides;
* the two-leg decomposition must remain an identity rather than an
  approximation, because the page says in as many words that it is one.

The adjusted figures the thresholds settle on are pinned too: the page argues
from ex-one-off margins that the company never prints, so the arithmetic behind
them has to be reproducible from the audit tables.

Sections one and three are the local analyses' own content: section one closes
the previous analysis's follow-up questions and settles its observation table,
section three watches this analysis's. The report facts -- verdicts, every line's
tier, comparison and threshold, how a row combines its lines -- are keyed in
`_checks["note"]`, and the tests compare the published page against them; every
reading a line settles on is recomputed here from the series.

Rolling the page is a data edit, so nothing below names a quarter or a count:
lengths are read from the series, the quarter's figures from `_checks`
(`AmznChecksTest`), every sentence that states a record is tested on two states
built from the series (`AmznRollTest`), and `AmznRollRehearsalTest` rolls the
series a quarter forward in memory -- this quarter's `next_kpi` becoming next
quarter's `prior_kpi_settlement` -- and builds it without a code change.
"""

from __future__ import annotations

import collections
import copy
import json
import math
import re
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.all import build_all, roster_payload  # noqa: E402
from build.board import cn_count, cn_ordinal as cn, headroom  # noqa: E402
from build.amzn import build_payload  # noqa: E402
from build.payload_guard import check  # noqa: E402


def order(period: str) -> tuple[int, int]:
    quarter, year = period.split()
    return int(year), int(quarter[1])


def favourable_side(entry: dict) -> str:
    """A risk line written ``<`` / ``<=`` and a confirmation line written ``>`` /
    ``>=`` are both good above; the other two combinations are good below."""
    return "up" if (entry["tier"] == "bull") == (entry["op"] in (">", ">=")) else "down"


def readings(source: dict) -> dict:
    """This quarter's value of everything a threshold line can read -- a previous
    analysis's line settled in section one or this analysis's watched in section
    three, which next quarter become the same thing -- computed here from the
    series rather than by the builder's own registry. One-off amounts come from
    the 10-Q block; the constant-currency growth is the release's printed figure
    when the quarter carries it."""
    long = source["long_history"]
    aws_revenue, aws_income = long["aws_revenue_usd_m"], long["aws_operating_income_usd_m"]
    segments = source["segments_usd_m"]
    backlog = source["aws_backlog"]["level_usd_bn"]
    q = source["quarterly_usd_m"]
    one_off = source.get("one_off_items") or {}
    printed = (source.get("current_snapshot") or {}).get("aws_growth_ex_fx_pct")
    return {
        "backlog_qoq_pct": (backlog[-1] / backlog[-2] - 1) * 100,
        "backlog_level": backlog[-1],
        "backlog_add": backlog[-1] - backlog[-2],
        "aws_yoy_ex_fx": printed[-1] if printed else (aws_revenue[-1] / aws_revenue[-5] - 1) * 100,
        "aws_margin": aws_income[-1] / aws_revenue[-1] * 100,
        "aws_margin_ex_one_off": ((segments["aws_operating_income"][-1]
                                   - one_off.get("energy_derivative_gain_usd_m", 0))
                                  / segments["aws_revenue"][-1] * 100),
        "aws_increment": (aws_revenue[-1] - aws_revenue[-2]) / 1000,
        "fcf_ttm": source["cash_flow_disclosed"]["free_cash_flow_ttm"][-1] / 1000,
        "group_oi": q["operating_income"][-1] / 1000,
        "group_margin": q["operating_income"][-1] / q["revenue_total"][-1] * 100,
        "net_capex": q["net_capex"][-1] / 1000,
        "na_margin_ex_one_off": ((segments["na_operating_income"][-1] - one_off.get("tariff_refund_usd_m", 0))
                                 / segments["na_revenue"][-1] * 100),
    }


def leg_exceptions(guide: dict) -> list[int]:
    """Guided quarters whose miss or beat against the midpoint was not led by the
    margin leg -- the identity the page states, recomputed here."""
    out = []
    for i, sales in enumerate(guide["actual_net_sales_bn"]):
        if sales is None:
            continue
        guided_sales = (guide["net_sales_low_bn"][i] + guide["net_sales_high_bn"][i]) / 2
        guided_income = (guide["operating_income_low_bn"][i] + guide["operating_income_high_bn"][i]) / 2
        margin = guided_income / guided_sales
        revenue_leg = (sales - guided_sales) * margin
        margin_leg = sales * (guide["actual_operating_income_bn"][i] / sales - margin)
        if not abs(margin_leg) > abs(revenue_leg):
            out.append(i)
    return out


def reading_printed(source: dict, reads: str, value: float) -> str:
    """How the page prints a reading: whole billions for the backlog (the filings
    print it so), the release's whole percent for printed constant-currency growth,
    two decimals for one-off-adjusted margins and for the AWS increment."""
    def money(amount: float, digits: int) -> str:
        return f"{'−' if amount < 0 else ''}US${abs(amount):.{digits}f}B"

    printed = (source.get("current_snapshot") or {}).get("aws_growth_ex_fx_pct")
    if reads in ("backlog_level", "backlog_add"):
        return money(value, 0)
    if reads == "aws_increment":
        return money(value, 2)
    if reads in ("fcf_ttm", "group_oi", "net_capex"):
        return money(value, 1)
    if reads == "aws_yoy_ex_fx":
        return f"{value:.0f}%" if printed else f"{value:.1f}%"
    if reads in ("aws_margin_ex_one_off", "na_margin_ex_one_off"):
        return f"{value:.2f}%"
    return f"{value:.1f}%"


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


def quarter_key(period: str) -> str:
    quarter, year = period.split()
    return f"{year}{quarter}"


def next_quarter(period: str) -> str:
    quarter, year = period.split()
    number = int(quarter[1])
    return f"Q1 {int(year) + 1}" if number == 4 else f"Q{number + 1} {year}"


def published_text(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


class AmznDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "amzn.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]
        cls.by_section = {
            section["id"]: section["exhibits"] for section in cls.payload["sections"]
        }
        cls.q = cls.source["quarterly_usd_m"]
        cls.segments = cls.source["segments_usd_m"]
        cls.lines = cls.source["product_lines_usd_m"]
        cls.guide = cls.source["quarterly_guidance_history"]

    # ── the series itself ────────────────────────────────────────────────────
    def test_twelve_quarter_base_backs_every_yoy(self) -> None:
        """At least twelve reviewed quarters (a roll appends one), every quarterly
        line as long as the period list and finite."""
        periods = self.source["periods"]
        self.assertGreaterEqual(len(periods), 12)
        for name, values in self.q.items():
            if not isinstance(values, list):
                continue
            self.assertEqual(len(values), len(periods), name)
            self.assertTrue(all(math.isfinite(value) for value in values), name)

    def test_segments_sum_to_the_consolidated_statement(self) -> None:
        """Segment revenue and segment operating income are reported figures, not
        derived ones, so a quarter where they stop adding up means a row was
        stitched from the wrong filing."""
        by_period = {period: index for index, period in enumerate(self.source["periods"])}
        for index, period in enumerate(self.segments["periods"]):
            revenue = (
                self.segments["na_revenue"][index]
                + self.segments["intl_revenue"][index]
                + self.segments["aws_revenue"][index]
            )
            income = (
                self.segments["na_operating_income"][index]
                + self.segments["intl_operating_income"][index]
                + self.segments["aws_operating_income"][index]
            )
            if period in by_period:
                slot = by_period[period]
                self.assertEqual(revenue, self.q["revenue_total"][slot], period)
                self.assertEqual(income, self.q["operating_income"][slot], period)
            lines = sum(
                self.lines[name][index]
                for name in ("online_stores", "physical_stores",
                             "third_party_seller_services", "advertising_services",
                             "subscription_services", "aws", "other")
                if self.lines[name][index] is not None
            )
            self.assertEqual(lines, revenue, f"{period} product lines")

    def test_income_statement_identity_holds_each_quarter(self) -> None:
        """Operating income plus total non-operating income is income before
        taxes; the payload names the non-operating line for what it is, so this
        is the check that the naming stayed honest. The snapshot's columns are
        (a year ago, last quarter, this quarter), and the builder refuses any
        other order."""
        snapshot = self.source["current_snapshot"]
        periods = self.source["periods"]
        self.assertEqual(snapshot["columns"], [periods[-5], periods[-2], periods[-1]])
        for slot, index in ((0, -5), (1, -2), (2, -1)):
            self.assertEqual(
                self.q["operating_income"][index] + self.q["total_non_operating_income"][index],
                snapshot["pre_tax_income_usd_m"][slot],
            )

    def test_net_capex_is_gross_minus_proceeds(self) -> None:
        """The page plots gross purchases in the cross-company table and net
        capex against the threshold; conflating the two would move the current
        quarter by more than a billion dollars."""
        for index, period in enumerate(self.source["periods"]):
            self.assertEqual(
                self.q["purchases_of_property_and_equipment"][index]
                - self.q["proceeds_from_pe_sales_and_incentives"][index],
                self.q["net_capex"][index],
                period,
            )

    def test_quarterly_series_reconcile_with_the_full_year(self) -> None:
        """Four quarters must add to the filed year. Companies round each
        quarter and each year independently, so ±1 US$M is the intended state
        and anything wider is a real error.

        The totals below were read from the 10-K income statements by hand; the
        series' own `annual_filed_usd_m` block (which the page's reconciliation
        sentence is computed from) was read from the XBRL facts. The two
        readings have to agree, and every year the series has four quarters for
        has to reconcile against the block, on all five long lines."""
        long = self.source["long_history"]
        by_quarter = dict(zip(long["quarters"], long["revenue_usd_m"]))
        income = dict(zip(long["quarters"], long["operating_income_usd_m"]))
        filed = {
            2021: (469822, 24879),
            2022: (513983, 12248),
            2023: (574785, 36852),
            2024: (637959, 68593),
            2025: (716924, 79975),
        }
        annual = long["annual_filed_usd_m"]
        for year, (revenue_total, income_total) in filed.items():
            quarters = [f"{year}Q{n}" for n in (1, 2, 3, 4)]
            self.assertLessEqual(
                abs(sum(by_quarter[q] for q in quarters) - revenue_total), 1, year)
            self.assertLessEqual(
                abs(sum(income[q] for q in quarters) - income_total), 1, year)
            at = annual["years"].index(year)
            self.assertEqual(annual["revenue_usd_m"][at], revenue_total, year)
            self.assertEqual(annual["operating_income_usd_m"][at], income_total, year)
        checked = 0
        for key in ("revenue_usd_m", "operating_income_usd_m", "operating_cash_flow_usd_m",
                    "capital_expenditures_usd_m", "depreciation_and_amortization_usd_m",
                    "interest_expense_usd_m"):
            cells = dict(zip(long["quarters"], long[key]))
            for year, total in zip(annual["years"], annual[key]):
                values = [cells.get(f"{year}Q{n}") for n in (1, 2, 3, 4)]
                if None in values:
                    continue
                with self.subTest(line=key, year=year):
                    self.assertLessEqual(abs(sum(values) - total), 1)
                checked += 1
        self.assertGreater(checked, 0)

    def test_long_history_agrees_with_the_reviewed_quarters(self) -> None:
        long = self.source["long_history"]
        quarters = long["quarters"]
        self.assertEqual(quarters[-1], quarter_key(self.source["periods"][-1]))
        for previous, current in zip(quarters, quarters[1:]):
            year, number = int(previous[:4]), int(previous[-1])
            expected = f"{year + 1}Q1" if number == 4 else f"{year}Q{number + 1}"
            self.assertEqual(current, expected)
        for name, values in long.items():
            if isinstance(values, list):
                self.assertEqual(len(values), len(quarters), name)
        by_quarter = dict(zip(quarters, long["revenue_usd_m"]))
        capex = dict(zip(quarters, long["capital_expenditures_usd_m"]))
        for index, period in enumerate(self.source["periods"]):
            key = quarter_key(period)
            self.assertEqual(by_quarter[key], self.q["revenue_total"][index], period)
            self.assertEqual(
                capex[key], self.q["purchases_of_property_and_equipment"][index], period)

    def test_undisclosed_quarters_stay_empty(self) -> None:
        """Holes are disclosed, not filled.

        Capital expenditure now starts a full year later than it used to, and
        the reason is a basis break rather than a missing filing: Amazon's 2016
        cash-flow statements print one *net* line (after proceeds from sales and
        incentives) and only from 2017 do they split gross from proceeds. The
        four 2016 cells this series used to carry were the net measure sitting
        under a gross heading, and 2016Q4 was worse still -- the restated annual
        gross minus the old-basis nine-month net, two different quantities.
        Quarterly gross for 2016 does not exist in any filing, so the cells are
        empty and the net figures live in their own block with their sources.
        """
        long = self.source["long_history"]
        first = long["quarters"].index(long["capex_first_reported"])
        self.assertEqual(long["capex_first_reported"], "2017Q1")
        self.assertEqual(long["capital_expenditures_usd_m"][:first], [None] * 4)
        basis = long["capital_expenditures_basis"]
        self.assertEqual(basis["starts"], "2017Q1")
        self.assertEqual(len(basis["net_2016_usd_m"]), 4)
        # The net figures are kept because they are real, and checked because
        # they are the thing that was previously mistaken for gross.
        self.assertAlmostEqual(sum(basis["net_2016_usd_m"]), 6736.0, places=6)
        self.assertTrue(
            all(value is not None for value in long["capital_expenditures_usd_m"][first:]))
        lease_first = long["quarters"].index(long["finance_lease_first_reported"])
        self.assertIsNone(long["finance_lease_principal_usd_m"][lease_first - 1])
        self.assertTrue(
            all(value is not None for value in long["finance_lease_principal_usd_m"][lease_first:]))
        ads_first = self.lines["periods"].index(self.lines["advertising_first_reported"])
        self.assertIsNone(self.lines["advertising_services"][ads_first - 1])

    # ── the guided record ────────────────────────────────────────────────────
    def test_guidance_record_is_paired_on_the_guided_quarter(self) -> None:
        """Each release guides the quarter *after* the one it reports. Pairing a
        range with the quarter its own release covers would shift the entire
        record by one and still look plausible."""
        quarters = self.guide["quarters"]
        for name, values in self.guide.items():
            if name in ("provenance", "format_notes", "backfill_note_2016_2017"):
                continue
            if isinstance(values, list):
                self.assertEqual(len(values), len(quarters), name)
        order = [(int(q.split()[1]), int(q.split()[0][1])) for q in quarters]
        self.assertEqual(order, sorted(order), "guided quarters are not consecutive")
        for previous, current in zip(order, order[1:]):
            self.assertEqual(current[0] * 4 + current[1], previous[0] * 4 + previous[1] + 1)
        self.assertEqual(quarters[-1], next_quarter(self.source["periods"][-1]))
        self.assertIsNone(self.guide["actual_net_sales_bn"][-1])
        self.assertIsNone(self.guide["actual_operating_income_bn"][-1])

        # The actuals must equal the quarterly series wherever the windows meet.
        by_period = dict(zip(self.source["periods"], self.q["revenue_total"]))
        income = dict(zip(self.source["periods"], self.q["operating_income"]))
        checked = 0
        for index, period in enumerate(quarters):
            if period not in by_period:
                continue
            self.assertAlmostEqual(
                self.guide["actual_net_sales_bn"][index], by_period[period] / 1000, places=3)
            self.assertAlmostEqual(
                self.guide["actual_operating_income_bn"][index], income[period] / 1000, places=3)
            checked += 1
        self.assertEqual(checked, len(self.source["periods"]))

    def test_the_record_titles_follow_the_record(self) -> None:
        """The page's headline claim about the guided record: each band's title
        says the bottom was never broken exactly when no finished quarter came
        in below its range, and the audit table agrees row by row."""
        bands = [ex for ex in self.by_section["settled"] if ex["kind"] == "range_band"]
        self.assertEqual(len(bands), 2)
        for chart, low_key, actual_key in (
                (bands[0], "net_sales_low_bn", "actual_net_sales_bn"),
                (bands[1], "operating_income_low_bn", "actual_operating_income_bn")):
            missed = sum(1 for low, actual in zip(self.guide[low_key], self.guide[actual_key])
                         if actual is not None and actual < low)
            with self.subTest(chart=chart["title"]):
                self.assertEqual("没有一季跌破下限" in chart["title"], missed == 0)

    def test_beat_decomposition_is_an_identity(self) -> None:
        """`actual − guided midpoint = revenue leg + margin leg`, exactly. The
        chart's note claims this is not an approximation, so the sum has to
        close to floating-point noise, not to a tolerance."""
        legs = next(ex for ex in self.by_section["settled"] if "两条腿" in ex["title"])
        revenue_leg = legs["groups"][0]["values"]
        margin_leg = legs["groups"][1]["values"]
        finished = [
            index for index, value in enumerate(self.guide["actual_net_sales_bn"])
            if value is not None
        ]
        self.assertEqual(len(revenue_leg), len(finished))
        for slot, index in enumerate(finished):
            guided_sales = (self.guide["net_sales_low_bn"][index]
                            + self.guide["net_sales_high_bn"][index]) / 2
            guided_income = (self.guide["operating_income_low_bn"][index]
                             + self.guide["operating_income_high_bn"][index]) / 2
            beat = self.guide["actual_operating_income_bn"][index] - guided_income
            self.assertAlmostEqual(
                revenue_leg[slot] + margin_leg[slot], beat, places=5,
                msg=f"{self.guide['quarters'][index]} legs do not close on the beat",
            )
            self.assertGreater(guided_sales, 0)

    # ── the adjusted figures the thresholds settle on ────────────────────────
    def test_adjusted_margins_match_the_filed_one_off_amounts(self) -> None:
        """Every ex-one-off margin quoted on the page is (reported − filed
        amount) / reported revenue, using the 10-Q figures rather than the
        call's approximations. A quarter without one-off items has nothing to
        adjust, and the adjusted readings equal the reported ones."""
        one_off = self.source.get("one_off_items") or {}
        energy = one_off.get("energy_derivative_gain_usd_m", 0)
        aws_adjusted = (
            (self.segments["aws_operating_income"][-1] - energy) / self.segments["aws_revenue"][-1] * 100
        )
        aws_prior_year = (
            self.segments["aws_operating_income"][-5] / self.segments["aws_revenue"][-5] * 100
        )
        # The reason the page prefers the 10-Q's single-quarter figure over the
        # call's round number: it lands within a few basis points of the change
        # management itself quoted.
        if "management_ex_derivative_margin_bp" in one_off:
            self.assertAlmostEqual((aws_adjusted - aws_prior_year) * 100,
                                   one_off["management_ex_derivative_margin_bp"], delta=10)
            on_call = one_off["energy_derivative_gain_on_call_usd_m"]
            by_call = ((self.segments["aws_operating_income"][-1] - on_call)
                       / self.segments["aws_revenue"][-1] * 100 - aws_prior_year) * 100
            self.assertLess(abs((aws_adjusted - aws_prior_year) * 100 - one_off["management_ex_derivative_margin_bp"]),
                            abs(by_call - one_off["management_ex_derivative_margin_bp"]))
        # ...and every adjusted reading the drawer prints is the filed-amount one.
        read = readings(self.source)
        for prefix, key in (("上季阈值逐线", "prior_kpi_settlement"), ("下季阈值逐线", "next_kpi")):
            table = next(t for t in self.payload["tables"] if t["title"].startswith(prefix))
            for entry, row in zip(self.source[key]["quantified"], table["rows"]):
                if entry["reads"] in ("aws_margin_ex_one_off", "na_margin_ex_one_off"):
                    self.assertEqual(row[5], f"{read[entry['reads']]:.2f}%", entry["id"])

    # ── section one: what last quarter's analysis left open ──────────────────
    def prior_overview(self, payload: dict | None = None) -> dict:
        settled = (payload or self.payload)["sections"][0]["exhibits"]
        return next(ex for ex in settled if re.match(r"^上季 \d+ 条量化阈值：", ex["title"]))

    def test_section_one_settles_questions_then_thresholds_then_the_guided_record(self) -> None:
        """(a) the follow-up closure (when the analysis closed any), (b) the
        threshold overview and one chart per reading, (c) the company's own
        guided record -- in that order."""
        settled = self.by_section["settled"]
        kinds = [ex["kind"] for ex in settled]
        at = 0
        if "followup_closure" in self.source:
            self.assertEqual(settled[0]["kind"], "bars_labeled")
            self.assertRegex(settled[0]["title"], r"^上季 \d+ 条待验证问题：")
            at = 1
        self.assertIs(settled[at], self.prior_overview())
        first_band = kinds.index("range_band")
        for ex in settled[at + 1:first_band]:
            self.assertEqual(ex["kind"], "lines")
            self.assertRegex(ex["title"], r"(守住|越过|达到|没到)上季(风险线|多头确认线)")
        self.assertEqual(kinds[first_band:].count("range_band"), 2)

    def test_the_closure_is_the_reports_section_zero(self) -> None:
        """Counts and per-question verdicts against the report facts kept in
        `_checks.note` -- and, where the report scores its answers instead of
        naming a verdict, the rule that turns the marks into verdicts."""
        note = self.source["_checks"]["note"]["closure"]
        items = self.source["followup_closure"]["items"]
        self.assertEqual(len(items), note["total"])
        self.assertEqual([item["verdict"] for item in items], note["verdicts"])
        if "direction_marks" in note:
            # The page's rule, applied here to the report's own marks: an answer
            # that says the item is still undisclosed is 仍未披露, otherwise the
            # direction mark decides.
            derived = ["仍未披露" if undisclosed else ("已验证" if "✓" in mark else "被证伪")
                       for mark, undisclosed in zip(note["direction_marks"], note["answer_says_undisclosed"])]
            self.assertEqual(derived, note["verdicts"])
            for item, mark in zip(items, note["direction_marks"]):
                self.assertTrue(item["scores"].startswith(f"方向 {mark}｜"), item["short"])
        counts = collections.Counter(note["verdicts"])
        shown = [label for label in ("已验证", "部分验证", "被证伪", "仍未披露") if counts[label]]
        chart = next(ex for ex in self.by_section["settled"] if "条待验证问题" in ex["title"])
        self.assertEqual(chart["xlabels"], shown)
        self.assertEqual(chart["values"], [counts[label] for label in shown])
        self.assertEqual(chart["title"], f"上季 {note['total']} 条待验证问题："
                         + "、".join(f"{counts[label]} 条{label}" for label in shown))
        table = next(t for t in self.payload["tables"] if t["title"].startswith("上季（")
                     and "待验证问题" in t["title"])
        self.assertEqual([row[4] for row in table["rows"]], note["verdicts"])
        for row in table["rows"]:
            self.assertNotRegex(row[5], r"\{[a-z_]+\}", "a story placeholder was not filled")

    def test_the_prior_lines_are_the_reports_observation_table(self) -> None:
        """Every line of last quarter's observation table, verbatim: row, tier,
        comparison, threshold, unit -- and how each row combines its lines."""
        note = self.source["_checks"]["note"]
        block = self.source["prior_kpi_settlement"]
        self.assertEqual(
            [(e["row"], e["tier"], e["op"], e["threshold"], e["unit"]) for e in block["quantified"]],
            [(e["row"], e["tier"], e["op"], e["threshold"], e["unit"]) for e in note["prior_thresholds"]])
        self.assertEqual(len(block["rows"]), note["prior_rows"])
        for row in block["rows"]:
            logic = note["prior_row_logic"].get(str(row["row"]))
            if logic is None:
                self.assertIn(row["row"], note["prior_unquantified_rows"])
                self.assertTrue(row.get("qualitative") or row.get("not_drawn_reason"))
            else:
                self.assertEqual([row.get("bull_logic"), row.get("risk_logic")], logic, row["row"])
        self.assertEqual(sum(1 for e in block["quantified"] if e.get("due_from")),
                         sum(1 for e in note["prior_thresholds"] if e.get("due")))

    def test_each_due_line_is_settled_on_its_own_reading(self) -> None:
        """The overview's bars are the headroom of each line that is due, on a
        reading computed here from the series -- not typed into the block."""
        block = self.source["prior_kpi_settlement"]
        read = readings(self.source)
        period = self.source["periods"][-1]
        due = [e for e in block["quantified"]
               if not (e.get("due_from") and order(e["due_from"]) > order(period))]
        overview = self.prior_overview()
        self.assertEqual(len(overview["values"]), len(due))
        for entry, label, value in zip(due, overview["xlabels"], overview["values"]):
            with self.subTest(line=entry["id"]):
                self.assertIn(entry["metric"], label)
                self.assertEqual(value, round(headroom(favourable_side(entry), entry["threshold"],
                                                       read[entry["reads"]]), 1))
        for tier, words, good, bad in (("risk", "风险线", "守住", "越线"), ("bull", "多头确认线", "达到", "没到")):
            lines = [e for e in due if e["tier"] == tier]
            if not lines:
                continue
            fine = sum(1 for e in lines if headroom(favourable_side(e), e["threshold"], read[e["reads"]]) >= 0)
            self.assertIn(f"{len(lines)} 条{words}" + (f"都{good}" if fine == len(lines) else
                                                        f"有 {len(lines) - fine} 条{bad}"), overview["title"])
        # every due line is drawn, as its own flat series, on the chart of its reading
        charts = self.by_section["settled"]
        for entry in due:
            with self.subTest(drawn=entry["id"]):
                self.assertTrue(any(
                    series["values"] == [entry["threshold"]] * len(ex["xlabels"])
                    and series["name"].startswith("上季" + ("风险线" if entry["tier"] == "risk" else "多头确认线"))
                    for ex in charts if ex["kind"] == "lines" for series in ex["series"][1:]))

    def test_a_line_dated_later_is_named_not_settled(self) -> None:
        """A line the analysis dated after this quarter is listed with where the
        reading stands, and settled only once it is due -- both states built here."""
        period = self.source["periods"][-1]
        total = len(self.source["prior_kpi_settlement"]["quantified"])
        dated = copy.deepcopy(self.source)
        first = dated["prior_kpi_settlement"]["quantified"][0]
        first["due_from"], first["due_words"] = next_quarter(period), "下一季"
        later = [e for e in dated["prior_kpi_settlement"]["quantified"]
                 if e.get("due_from") and order(e["due_from"]) > order(period)]
        payload = build_payload(dated)
        self.assertEqual(len(self.prior_overview(payload)["values"]), total - len(later))
        self.assertIn(f"要到 {next_quarter(period)} 起才结算", self.prior_overview(payload)["note"])
        table = next(t for t in payload["tables"] if t["title"].startswith("上季阈值逐线"))
        self.assertEqual(sum(1 for row in table["rows"] if row[-1].startswith("未到期")), len(later))
        due_now = copy.deepcopy(self.source)
        for entry in due_now["prior_kpi_settlement"]["quantified"]:
            entry.pop("due_from", None)
        payload = build_payload(due_now)
        self.assertEqual(len(self.prior_overview(payload)["values"]), total)
        self.assertNotIn("起才结算", published_text(payload))

    def test_rows_combine_their_lines_the_way_the_report_wrote_them(self) -> None:
        """「且」needs every line of the tier, 「或」any one. Checked on rows built
        here on two of the block's own readings, one line put on each side of
        its reading, so the check does not depend on where this quarter landed."""
        source = copy.deepcopy(self.source)
        block = source["prior_kpi_settlement"]
        read = readings(self.source)
        a, b = [e for e in block["quantified"] if not e.get("due_from")][:2]

        def above(entry: dict) -> float:     # a threshold the reading sits below
            value = read[entry["reads"]]
            return round(value + abs(value) * 0.1 + 1, 3)

        def below(entry: dict) -> float:     # a threshold the reading sits above
            value = read[entry["reads"]]
            return round(value - abs(value) * 0.1 - 1, 3)

        def line(id_: str, row: int, tier: str, metric: str, template: dict, op: str, threshold: float) -> dict:
            return {"id": id_, "row": row, "tier": tier, "metric": metric, "reads": template["reads"],
                    "op": op, "threshold": threshold, "unit": template["unit"]}

        block["rows"] += [
            {"row": 99, "subject": "演练：联合确认", "bull": "甲且乙", "bull_logic": "and"},
            {"row": 98, "subject": "演练：联合风险", "risk": "丙且丁", "risk_logic": "and"},
            {"row": 97, "subject": "演练：任一风险", "risk": "戊或己", "risk_logic": "or"},
        ]
        block["quantified"] += [
            line("t99a", 99, "bull", "演练甲", a, ">=", below(a)),
            line("t99b", 99, "bull", "演练乙", b, ">=", above(b)),
            line("t98a", 98, "risk", "演练丙", a, "<", above(a)),
            line("t98b", 98, "risk", "演练丁", b, "<", below(b)),
            line("t97a", 97, "risk", "演练戊", a, "<", above(a)),
            line("t97b", 97, "risk", "演练己", b, "<", below(b)),
        ]
        text = published_text(build_payload(source))
        self.assertIn("第九十九行的多头条件没有成立（演练乙没到", text)
        self.assertIn("第九十八行的风险条件要几条线同时越过，本季只有演练丙越线，不算成立", text)
        self.assertRegex(text, r"第[^；。]*九十七行的风险条件成立")
        self.assertNotRegex(text, r"第[^；。]*九十八行的风险条件成立")
        # ...and once 乙 is reached too, the joint confirmation holds.
        both = copy.deepcopy(source)
        next(e for e in both["prior_kpi_settlement"]["quantified"] if e["id"] == "t99b")["threshold"] = below(b)
        text = published_text(build_payload(both))
        self.assertRegex(text, r"第[^；。]*九十九行的多头条件成立")
        self.assertNotIn("第九十九行的多头条件没有成立", text)

    # ── section three: this analysis's observation table ────────────────────
    def test_the_next_lines_are_the_reports_section_eight(self) -> None:
        """Every line of this quarter's observation table, both tiers, verbatim --
        against the report facts in `_checks.note` -- and no line typed with a
        reading of its own."""
        note = self.source["_checks"]["note"]
        block = self.source["next_kpi"]
        self.assertEqual(
            sorted((e["row"], e["tier"], e["op"], e["threshold"], e["unit"]) for e in block["quantified"]),
            sorted((e["row"], e["tier"], e["op"], e["threshold"], e["unit"]) for e in note["next_thresholds"]))
        self.assertEqual(len(block["rows"]), note["next_rows"])
        for entry in block["quantified"]:
            self.assertNotIn("current", entry, "a next-quarter line carries a typed reading")
        for fact in note["next_thresholds"]:
            if fact.get("and_also"):
                row = next(r for r in block["rows"] if r["row"] == fact["row"])
                self.assertIn(fact["and_also"], row[f"{fact['tier']}_unquantified"])
        self.assertEqual(self.source["next_kpi"]["for_period"], next_quarter(self.source["periods"][-1]))

    def test_the_next_overview_reads_each_line_on_its_own_reading(self) -> None:
        block = self.source["next_kpi"]
        read = readings(self.source)
        overview = self.by_section["next_quarter"][0]
        self.assertRegex(overview["title"], rf"^下季 {len(block['quantified'])} 条阈值：")
        self.assertEqual(len(overview["values"]), len(block["quantified"]))
        for entry, label, value in zip(block["quantified"], overview["xlabels"], overview["values"]):
            with self.subTest(line=entry["id"]):
                self.assertIn(entry["metric"], label)
                self.assertEqual(value, round(headroom(favourable_side(entry), entry["threshold"],
                                                       read[entry["reads"]]), 1))
        missed = [e for e in block["quantified"] if e["tier"] == "bull"
                  and headroom(favourable_side(e), e["threshold"], read[e["reads"]]) < 0]
        self.assertIn(f"当前有 {len(missed)} 条没到" if missed else "当前都已达到", overview["title"])

    def test_every_next_line_is_drawn_and_every_undrawn_row_says_why(self) -> None:
        note = self.source["_checks"]["note"]
        block = self.source["next_kpi"]
        overview, charts = self.by_section["next_quarter"][0], self.by_section["next_quarter"][1:]
        for entry in block["quantified"]:
            with self.subTest(drawn=entry["id"]):
                self.assertTrue(any(
                    series["values"] == [entry["threshold"]] * len(ex["xlabels"])
                    and series["name"].startswith("下季" + ("风险线" if entry["tier"] == "risk" else "多头确认线"))
                    for ex in charts for series in ex["series"][1:]))
        undrawn = [row for row in block["rows"] if not any(e["row"] == row["row"] for e in block["quantified"])]
        self.assertEqual([row["row"] for row in undrawn], note["next_not_drawn_rows"])
        for row in undrawn:
            self.assertIn(f"第{cn(row['row'])}行（{row['subject']}）不画：", overview["note"])
        rows_table = next(t for t in self.payload["tables"] if "关键观察指标" in t["title"]
                          and t["title"].startswith("本季本地分析"))
        self.assertEqual(len(rows_table["rows"]), note["next_rows"])

    def test_the_follow_ups_are_carried_into_the_drawer(self) -> None:
        """The questions this analysis leaves for the next one -- what next
        quarter's section one will close -- are on the page, numbered as the
        report numbers them, with the page's own addition marked as such."""
        note = self.source["_checks"]["note"]
        table = next(t for t in self.payload["tables"] if "留给下季" in t["title"])
        numbered = [row for row in table["rows"] if row[0].isdigit()]
        self.assertEqual(len(numbered), note["followups"])
        self.assertEqual([row[0] for row in numbered], [str(n) for n in range(1, note["followups"] + 1)])
        for row in table["rows"]:
            self.assertNotRegex(row[2], r"\{[a-z_]+\}", "a story placeholder was not filled")
        added = [row for row in table["rows"] if not row[0].isdigit()]
        for row in added:
            self.assertIn("本页补充", row[2])

    # ── the disclosed cash-flow series ───────────────────────────────────────
    def test_free_cash_flow_series_is_disclosed_not_derived(self) -> None:
        """All three trailing series are company figures. The page corrects the
        local note with them, so they must be internally consistent, and the
        title says "deeper" exactly when an earlier quarter was deeper."""
        cash = self.source["cash_flow_disclosed"]
        self.assertEqual(cash["periods"][-1], self.source["periods"][-1])
        for name, values in cash.items():
            if isinstance(values, list) and name not in ("definition_changes",):
                self.assertEqual(len(values), len(cash["periods"]), name)
        for index, period in enumerate(cash["periods"]):
            self.assertEqual(
                cash["operating_cash_flow_ttm"][index] - cash["net_capex_ttm"][index],
                cash["free_cash_flow_ttm"][index],
                period,
            )
        latest = cash["free_cash_flow_ttm"][-1]
        chart = next(ex for ex in self.by_section["quarter_highlights"]
                     if ex["kind"] == "diverging_bars")
        self.assertEqual("更深" in chart["title"],
                         latest < 0 and min(cash["free_cash_flow_ttm"]) < latest)

    # ── page shape and boundary ──────────────────────────────────────────────
    def test_page_is_chart_led(self) -> None:
        self.assertGreaterEqual(len(self.exhibits), 20)
        self.assertEqual(self.payload["summary"]["blocks"], [])
        for exhibit in self.exhibits:
            self.assertTrue(exhibit.get("note"), exhibit["title"])
            self.assertNotIn("{EX_", exhibit.get("note", ""), exhibit["title"])
            self.assertNotIn("{EX_", exhibit["title"])
            # Chart notes are innerHTML: markdown asterisks would print literally.
            self.assertNotIn("**", exhibit.get("note", ""), exhibit["title"])

    def test_section_order_matches_how_the_note_is_used(self) -> None:
        self.assertEqual(
            [section["id"] for section in self.payload["sections"]],
            ["settled", "quarter_highlights", "next_quarter", "routine"],
        )
        self.assertEqual([ex["n"] for ex in self.exhibits],
                         list(range(2, 2 + len(self.exhibits))))

    def test_audit_tables_back_every_derived_exhibit(self) -> None:
        tables = self.payload["tables"]
        first = len(self.exhibits) + 2
        self.assertEqual([table["n"] for table in tables],
                         list(range(first, first + len(tables))))
        self.assertIn("AI capex", tables[-1]["title"])
        guided = next(t for t in tables if "指引与实际逐季对照" in t["title"])
        self.assertEqual(len(guided["rows"]), len(self.guide["quarters"]))
        self.assertEqual(guided["rows"][-1][2], "—")
        for column, low_key, actual_key in ((3, "net_sales_low_bn", "actual_net_sales_bn"),
                                            (6, "operating_income_low_bn", "actual_operating_income_bn")):
            missed = [actual is not None and actual < low
                      for low, actual in zip(self.guide[low_key], self.guide[actual_key])]
            self.assertEqual([row[column] == "跌破下限" for row in guided["rows"]], missed)

    def test_amzn_is_in_the_cross_page_capex_table(self) -> None:
        """AMZN is the largest capex spender of the four, so its absence would
        understate every row of the shared table."""
        table = next(t for t in self.payload["tables"] if "AI capex" in t["title"])
        self.assertEqual(table["headers"][1], "AMZN 现金 CapEx")
        capex = dict(zip(self.source["periods"],
                         self.q["purchases_of_property_and_equipment"]))
        for row in table["rows"]:
            if row[0] in capex:
                self.assertEqual(row[1], f"${capex[row[0]]:,.0f}M", row[0])

    def test_market_expectation_is_labelled_and_unattributed(self) -> None:
        expectation = self.source.get("market_expectation")
        if expectation is not None:
            self.assertIn("市场预期", expectation["label"])
            self.assertEqual(expectation["as_of"], self.payload["latest"]["release_date"])
        text = json.dumps(self.payload, ensure_ascii=False).lower()
        for broker in ("bloomberg", "visible alpha", "factset", "s&p global",
                       "marketbeat", "seeking alpha", "jpmorgan", "morgan stanley",
                       "goldman", "barclays", "evercore", "baird", "wells fargo",
                       "oppenheimer", "wolfe", "loop capital", "moffettnathanson",
                       "td cowen"):
            self.assertNotIn(broker, text, broker)
        # 目标价 / 评级 / 估值 are deliberately not checked here: they appear in
        # the page's own boundary statement, exactly as they do on every other
        # page, so a substring test on them fires on a clean tree. What must
        # never appear is a position instruction or a valuation multiple carried
        # over from the local note.
        for banned in ("加仓", "减仓", "买入", "卖出", "止损", "ev/revenue",
                       "clean p/e", "sotp", "re-rating"):
            self.assertNotIn(banned, text, banned)

    def test_sources_are_official_http_links(self) -> None:
        allowed_hosts = {"ir.aboutamazon.com", "www.sec.gov"}
        for source in self.payload["source_links"]:
            parsed = urlparse(source["url"])
            self.assertEqual(parsed.scheme, "https")
            self.assertIn(parsed.hostname, allowed_hosts)

    def test_published_payload_roster_and_shell(self) -> None:
        self.assertEqual(js_payload(ROOT / "data" / "amzn.js", "window.DASH"), self.payload)
        roster = js_payload(ROOT / "data" / "roster.js", "window.ROSTER")
        self.assertEqual(roster, roster_payload(build_all()))
        entry = next(item for item in roster["items"] if item["slug"] == "amzn")
        self.assertEqual(entry["latest_label"], self.payload["latest"]["disclosed_period_label"])
        self.assertEqual(entry["release_date"], self.payload["latest"]["release_date"])
        self.assertEqual(entry["group"], "internet")
        shell = (ROOT / "amzn" / "index.html").read_text(encoding="utf-8")
        self.assertIn("../data/amzn.js", shell)
        self.assertNotIn("../data/googl.js", shell)

    def test_home_page_carries_the_new_company(self) -> None:
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="amzn/"', home)
        self.assertIn(self.payload["latest"]["release_date"], home)
        self.assertIn(self.payload["latest"]["disclosed_period_label"], home)

    def test_public_files_exclude_private_and_broker_material(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [
                ROOT / "series" / "amzn.json",
                ROOT / "data" / "amzn.js",
                ROOT / "amzn" / "index.html",
            ]
        ).lower()
        for forbidden in [
            "/users/",
            "/library/cloudstorage/",
            "onedrive",
            "obsidian",
            "seeking alpha",
            "visible alpha",
            "consensus",
            ".pdf",
        ]:
            self.assertNotIn(forbidden, text, forbidden)


STAMPED = ("current_snapshot", "one_off_items", "other_income_story", "backlog_concentration",
           "capital_structure", "guidance", "calendar_shift", "market_expectation", "followup_closure",
           "prior_kpi_settlement", "next_kpi", "quarter_story", "local_note_errata")
# The two blocks section one settles; required in every quarter after the first analysis.
SETTLEMENT = ("followup_closure", "prior_kpi_settlement")
# Section three's block; required every quarter.
REQUIRED = SETTLEMENT + ("next_kpi",)


class AmznChecksTest(unittest.TestCase):
    """The page's quarter against a record keyed separately from the filing.

    `_checks` is typed once per quarter from the earnings release and the 10-Q,
    with the place each figure was read from. It is not copied from the arrays
    and the builder never reads it (`test_data_only_roll`). Rolling a quarter
    re-keys `_checks`; this class does not change.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "amzn.json").read_text(encoding="utf-8"))
        cls.checks = cls.source["_checks"]
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]
        cls.q = cls.source["quarterly_usd_m"]

    def test_the_page_names_the_checked_quarter(self) -> None:
        self.assertIn(self.checks["period"], self.payload["title"])
        self.assertIn(f"截至 {self.checks['period_end']}", self.payload["subtitle"])
        self.assertIn(f"发布 {self.checks['release_date']}", self.payload["subtitle"])
        self.assertEqual(self.source["periods"][-1], self.checks["period"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        c, q = self.checks, self.q
        for key, check in (("revenue_total", "revenue_usd_m"),
                           ("operating_income", "operating_income_usd_m"),
                           ("net_income", "net_income_usd_m"),
                           ("operating_cash_flow", "operating_cash_flow_usd_m"),
                           ("purchases_of_property_and_equipment",
                            "purchases_of_property_and_equipment_usd_m"),
                           ("proceeds_from_pe_sales_and_incentives",
                            "proceeds_from_property_and_equipment_sales_and_incentives_usd_m")):
            with self.subTest(line=key):
                self.assertEqual(q[key][-1], c[check])
        self.assertEqual(q["revenue_total"][-5], c["revenue_year_ago_usd_m"])
        snapshot = self.source.get("current_snapshot")
        if snapshot is not None:
            self.assertEqual(snapshot["pre_tax_income_usd_m"][-1], c["income_before_income_taxes_usd_m"])
            self.assertEqual(snapshot["other_income_expense_net_usd_m"][-1], c["other_income_expense_net_usd_m"])
            self.assertEqual(snapshot["diluted_eps_usd"][-1], c["diluted_eps_usd"])
            self.assertEqual(snapshot["aws_growth_ex_fx_pct"][-1], c["aws_growth_printed_pct"])
        self.assertEqual(self.source["cash_flow_disclosed"]["free_cash_flow_ttm"][-1],
                         c["free_cash_flow_ttm_usd_m"])
        segments = self.source["segments_usd_m"]
        for key, value in c["segments_usd_m"].items():
            with self.subTest(segment=key):
                self.assertEqual(segments[key][-1], value)
        self.assertEqual(self.source["product_lines_usd_m"]["advertising_services"][-1],
                         c["advertising_services_usd_m"])
        self.assertEqual(self.source["aws_backlog"]["level_usd_bn"][-1],
                         c["commitments_not_yet_recognized_usd_bn"])
        guide = self.source["quarterly_guidance_history"]
        forward = c["next_quarter"]
        self.assertEqual(guide["quarters"][-1], forward["quarter"])
        self.assertEqual([guide["net_sales_low_bn"][-1], guide["net_sales_high_bn"][-1]],
                         forward["net_sales_usd_bn"])
        self.assertEqual([guide["operating_income_low_bn"][-1], guide["operating_income_high_bn"][-1]],
                         forward["operating_income_usd_bn"])
        # The checked record names the direction in its key, as the release does
        # in its sentence ("an unfavorable impact of approximately 80 basis points").
        fx_keys = [key for key in forward if key.startswith("fx_bps_")]
        if fx_keys:
            self.assertEqual((guide["fx_bps"][-1], guide["fx_direction"][-1]),
                             (forward[fx_keys[0]], fx_keys[0].removeprefix("fx_bps_")))
        one_off = self.source.get("one_off_items") or {}
        for key, check in (("tariff_refund_usd_m", "tariff_refund"),
                           ("energy_derivative_gain_usd_m", "energy_derivative_gain")):
            self.assertEqual(one_off.get(key), (c.get("one_off_items_usd_m") or {}).get(check), key)

    def test_computed_figures_round_to_what_the_release_prints(self) -> None:
        c, q = self.checks, self.q
        segments = self.source["segments_usd_m"]
        self.assertEqual(round((q["revenue_total"][-1] / q["revenue_total"][-5] - 1) * 100),
                         c["revenue_growth_printed_pct"])
        self.assertEqual(round(q["operating_income"][-1] / q["revenue_total"][-1] * 100, 1),
                         c["operating_margin_printed_pct"])
        for segment, printed in c["segment_margin_printed_pct"].items():
            with self.subTest(segment=segment):
                self.assertEqual(
                    round(segments[f"{segment}_operating_income"][-1]
                          / segments[f"{segment}_revenue"][-1] * 100, 1), printed)
        # The release's 37% is growth excluding FX; the reported-dollar growth
        # rounds to the same figure this quarter, and the page prints both.
        self.assertEqual(round((segments["aws_revenue"][-1] / segments["aws_revenue"][-5] - 1) * 100),
                         c["aws_growth_printed_pct"])

    def test_the_page_prints_the_checked_figures(self) -> None:
        c = self.checks
        aws = next(ex for ex in self.exhibits if ex["kind"] == "bar_line")
        self.assertIn(f"AWS 收入 US${c['segments_usd_m']['aws_revenue'] / 1000:.1f}B", aws["title"])
        # The headline names the diluted EPS only in a quarter whose pre-tax
        # income is mostly the non-operating line, as it is when a holding is
        # marked up; otherwise the figure would be the quarter's lead for no reason.
        if "diluted_eps_usd" in c:
            other = c["other_income_expense_net_usd_m"]
            mostly_other = other > c["income_before_income_taxes_usd_m"] - other
            self.assertEqual(f"US${c['diluted_eps_usd']:.2f} 的摊薄每股收益" in self.payload["headline"],
                             mostly_other)
            self.assertIn(f"公司披露的固定汇率口径为 {c['aws_growth_printed_pct']}%", aws["note"])
        fcf = c["free_cash_flow_ttm_usd_m"]
        self.assertIn(f"{'−' if fcf < 0 else ''}US${abs(fcf) / 1000:.1f}B", self.payload["headline"])
        self.assertIn(f"US${c['commitments_not_yet_recognized_usd_bn']:.0f}B", self.payload["brief"])

    def test_every_threshold_reading_is_the_series_arithmetic(self) -> None:
        """No threshold block carries a typed reading; the drawer tables print the
        reading each line settles on, and here each one is recomputed from the
        series (one-off amounts from the 10-Q block, the constant-currency
        growth as the release prints it) and formatted the way the page prints it."""
        read = readings(self.source)
        checked = 0
        for era, block_key, prefix in (("prior", "prior_kpi_settlement", "上季阈值逐线"),
                                       ("next", "next_kpi", "下季阈值逐线")):
            block = self.source[block_key]
            table = next(t for t in self.payload["tables"] if t["title"].startswith(prefix))
            for entry, row in zip(block["quantified"], table["rows"]):
                self.assertNotIn("actual" if era == "prior" else "current", entry, entry["id"])
                with self.subTest(era=era, line=entry["id"]):
                    self.assertEqual(row[1], entry["metric"])
                    self.assertEqual(row[5], reading_printed(self.source, entry["reads"], read[entry["reads"]]))
                checked += 1
        self.assertEqual(checked, len(self.source["prior_kpi_settlement"]["quantified"])
                         + len(self.source["next_kpi"]["quantified"]))

    def test_the_debt_chart_reads_the_filed_balance_and_interest(self) -> None:
        """The capital-structure chart's last cells are the 10-Q's balance-sheet
        long-term debt and income-statement interest expense, and its title
        prints them."""
        c, long = self.checks, self.source["long_history"]
        self.assertEqual(long["long_term_debt_usd_m"][-1], c["long_term_debt_usd_m"])
        self.assertEqual(long["interest_expense_usd_m"][-1], c["interest_expense_usd_m"])
        self.assertEqual(long["interest_expense_usd_m"][-5], c["interest_expense_year_ago_usd_m"])
        chart = next(ex for ex in self.exhibits if ex["kind"] == "bar_line_dual")
        self.assertIn(f"US${c['long_term_debt_usd_m'] / 1000:.1f}B", chart["title"])
        self.assertIn(f"US${c['interest_expense_usd_m'] / 1000:.2f}B", chart["title"])
        growth = (c["interest_expense_usd_m"] / c["interest_expense_year_ago_usd_m"] - 1) * 100
        self.assertIn(f"同比 {growth:+.0f}%", chart["title"])
        self.assertEqual(chart["bar"]["values"][-1], c["long_term_debt_usd_m"] / 1000)


class AmznRollTest(unittest.TestCase):
    """What a quarter roll can and cannot get past."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "amzn.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)

    def test_a_block_stamped_with_another_quarter_stops_the_build(self) -> None:
        present = [key for key in STAMPED if key in self.source]
        self.assertTrue(set(REQUIRED) <= set(present))
        for key in present:
            stale = copy.deepcopy(self.source)
            stale[key]["period"] = "Q1 1999"
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    build_payload(stale)
        if "current_snapshot" in self.source:
            stale = copy.deepcopy(self.source)
            stale["current_snapshot"]["columns"] = list(reversed(stale["current_snapshot"]["columns"]))
            with self.assertRaisesRegex(ValueError, "columns"):
                build_payload(stale)

    def test_a_missing_quarter_block_leaves_its_part_out(self) -> None:
        """Every one-quarter block is optional except three: the two that settle
        the previous analysis (absent only in the first analysis's quarter, the
        state built here) and section three's, which every analysis writes. With
        a one-line `next_kpi`, nothing any story block said is left on the page."""
        bare = copy.deepcopy(self.source)
        for key in STAMPED:
            if key != "next_kpi":
                bare.pop(key, None)
        bare["analysis_record"]["first_period"] = bare["periods"][-1]
        minimal = bare["next_kpi"]
        minimal["rows"] = [dict(minimal["rows"][0])]
        minimal["quantified"] = [e for e in minimal["quantified"] if e["row"] == 1][:1]
        minimal.pop("followups")
        minimal.pop("page_added")
        payload = build_payload(bare)
        self.assertIn(f"本站对亚马逊的第一份季报分析是 {bare['periods'][-1]}",
                      payload["sections"][0]["description"])
        self.assertEqual([s["id"] for s in payload["sections"]],
                         ["settled", "quarter_highlights", "next_quarter", "routine"])
        text = published_text(payload)
        for gone in ("Anthropic", "Prime Day", "市场预期的 US$", "一次性经营项", "多头确认线",
                     "本地稿", "约 US$600M", "Other income", "拒绝披露", "OpenAI", "nothing to share"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, text)
        # The guided record and the long series do not depend on any of them.
        self.assertEqual(len(payload["sections"][0]["exhibits"]), 6)
        # ...and section three cannot be left out.
        without = copy.deepcopy(bare)
        del without["next_kpi"]
        with self.assertRaisesRegex(ValueError, "next_kpi"):
            build_payload(without)
        wrong = copy.deepcopy(self.source)
        wrong["next_kpi"]["for_period"] = wrong["periods"][-1]
        with self.assertRaisesRegex(ValueError, "quarter after"):
            build_payload(wrong)

    def test_the_settlement_blocks_are_required_after_the_first_analysis(self) -> None:
        period = self.source["periods"][-1]
        for key in SETTLEMENT:
            missing = copy.deepcopy(self.source)
            del missing[key]
            with self.subTest(missing=key), self.assertRaisesRegex(ValueError, key):
                build_payload(missing)
        # An analysis that closed no questions says why, and then the page builds.
        excused = copy.deepcopy(self.source)
        del excused["followup_closure"]
        excused["prior_kpi_settlement"]["no_closure_reason"] = "上一份分析没有留下待验证问题。"
        payload = build_payload(excused)
        self.assertNotRegex(payload["sections"][0]["exhibits"][0]["title"], "待验证问题")
        # Blocks that settle an analysis other than last quarter's stop the build.
        for key in SETTLEMENT:
            stale = copy.deepcopy(self.source)
            stale[key]["set_in"] = "Q3 2025"
            with self.subTest(stale=key), self.assertRaisesRegex(ValueError, "quarter before"):
                build_payload(stale)
        # In the first analysis's quarter there is nothing to settle, so the blocks may not be there.
        first = copy.deepcopy(self.source)
        first["analysis_record"]["first_period"] = period
        with self.assertRaisesRegex(ValueError, "nothing for"):
            build_payload(first)

    def test_the_quarter_release_must_be_in_the_sources(self) -> None:
        missing = copy.deepcopy(self.source)
        period = missing["periods"][-1]
        missing["sources"] = [s for s in missing["sources"]
                              if not s["label"].startswith(f"{period} 业绩 8-K")]
        with self.assertRaisesRegex(ValueError, "sources"):
            build_payload(missing)

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        """Every sentence that states a record, a run or a direction appears when
        the data says so and disappears when it does not. Both states are built
        here from the series -- the claim is not assumed to hold in the published
        quarter, so the test holds in any quarter a roll produces."""
        source = self.source
        period = source["periods"][-1]
        cases = []

        def state(edit) -> dict:
            built = copy.deepcopy(source)
            edit(built)
            return built

        # 1. No quarter below either guided range, then one below.
        def no_miss(s: dict) -> None:
            guide = s["quarterly_guidance_history"]
            for actual, low in (("actual_net_sales_bn", "net_sales_low_bn"),
                                ("actual_operating_income_bn", "operating_income_low_bn")):
                guide[actual] = [None if value is None else max(value, guide[low][i])
                                 for i, value in enumerate(guide[actual])]

        def one_miss(s: dict) -> None:
            no_miss(s)
            guide = s["quarterly_guidance_history"]
            guide["actual_net_sales_bn"][0] = guide["net_sales_low_bn"][0] - 1

        cases.append(("a quarter below the sales range", state(no_miss), state(one_miss),
                      ["收入一次都没有跌破过区间下限", "同样一次都没有跌破下限"]))

        # 2. Revenue landing on the guided midpoint, then 5% off it.
        def on_mid(s: dict, factor: float = 1.0) -> None:
            guide = s["quarterly_guidance_history"]
            done = [i for i, v in enumerate(guide["actual_net_sales_bn"]) if v is not None]
            for i in done[-20:]:
                guide["actual_net_sales_bn"][i] = round(
                    (guide["net_sales_low_bn"][i] + guide["net_sales_high_bn"][i]) / 2 * factor, 3)

        cases.append(("sales guidance far from the midpoint", state(on_mid),
                      state(lambda s: on_mid(s, 1.05)), ["收入指引其实<b>相当准</b>"]))

        # 3. Advertising and two store lines accelerating, then only advertising.
        def pace(s: dict, name: str, up: bool) -> None:
            v = s["product_lines_usd_m"][name]
            v[-1] = round(v[-5] * v[-2] / v[-6] * (1.05 if up else 0.95), 1)

        def three_up(s: dict) -> None:
            for name, up in (("advertising_services", True), ("online_stores", True),
                             ("third_party_seller_services", True), ("subscription_services", False)):
                pace(s, name, up)

        def ads_only(s: dict) -> None:
            three_up(s)
            pace(s, "online_stores", False)
            pace(s, "third_party_seller_services", False)

        retail = state(ads_only)
        cases.append(("the store lines slow down", state(three_up), retail,
                      ["四条零售线里有三条在加速", "在线商店与第三方卖家两条同期也在加速"]))

        # 4. The largest backlog addition on record, then an earlier, larger one.
        def backlog_record(s: dict) -> None:
            levels = s["aws_backlog"]["level_usd_bn"]
            best = max(b - a for a, b in zip(levels[:-2], levels[1:-1]))
            levels[-1] = levels[-2] + best + 10

        def earlier_backlog_record(s: dict) -> None:
            backlog_record(s)
            levels = s["aws_backlog"]["level_usd_bn"]
            levels[-3] = levels[-2] - (levels[-1] - levels[-2]) - 10

        # (The sentence rides on the chart of a line that reads the net addition.)
        if any(entry["reads"] == "backlog_add" for key in ("prior_kpi_settlement", "next_kpi")
               for entry in source[key]["quantified"]):
            cases.append(("an earlier, larger backlog addition", state(backlog_record),
                          state(earlier_backlog_record), ["是其中最大的一次"]))

        # 5. Trailing free cash flow turning negative this quarter, then already negative.
        def turned(s: dict, before: float) -> None:
            cash = s["cash_flow_disclosed"]
            cash["free_cash_flow_ttm"][-1], cash["free_cash_flow_ttm"][-2] = -1000.0, before

        cases.append(("free cash flow was already negative", state(lambda s: turned(s, 1000.0)),
                      state(lambda s: turned(s, -1000.0)), ["TTM 自由现金流转为", "转负的自由现金流"]))

        # 6. A record AWS increment, then a larger one in 2018.
        def aws_record(s: dict) -> None:
            long, segments = s["long_history"], s["segments_usd_m"]
            revenue = long["aws_revenue_usd_m"]
            best = max(b - a for a, b in zip(revenue[:-2], revenue[1:-1]))
            revenue[-1] = revenue[-2] + best + 1000
            segments["aws_revenue"][-1] = revenue[-1]

        def earlier_aws_record(s: dict) -> None:
            aws_record(s)
            revenue = s["long_history"]["aws_revenue_usd_m"]
            at = s["long_history"]["quarters"].index("2018Q4")
            revenue[at] += (revenue[-1] - revenue[-2]) + 10000

        cases.append(("an earlier, larger AWS increment", state(aws_record), state(earlier_aws_record),
                      [" 创纪录", "是此前最大单季增量的", "是此前纪录的"]))

        # 7. Capital intensity above the previous cycle's peak, then a higher peak in 2021.
        def intense(s: dict) -> None:
            long = s["long_history"]
            long["capital_expenditures_usd_m"][-1] = round(long["revenue_usd_m"][-1] * 0.5)

        def higher_peak(s: dict) -> None:
            intense(s)
            long = s["long_history"]
            at = long["quarters"].index("2021Q3")
            long["capital_expenditures_usd_m"][at] = round(long["revenue_usd_m"][at] * 0.6)

        cases.append(("an earlier capex-intensity peak", state(intense), state(higher_peak),
                      ["已越过上一轮周期的高点"]))

        # 8. The 2016-2017 quarters in which AWS earned more than the group (history).
        def one_year_less(s: dict) -> None:
            long = s["long_history"]
            long["aws_operating_income_usd_m"][long["quarters"].index("2016Q3")] = 500

        cases.append(("one fewer quarter above 100%", source, state(one_year_less), ["（Q3'16、Q2'17–Q3'17"]))

        # 9. Revenue growth rising four quarters running, then the run broken.
        def rising(s: dict, last: float = 1.16) -> None:
            revenue = s["long_history"]["revenue_usd_m"]
            for back, growth in ((4, 1.10), (3, 1.12), (2, 1.14), (1, last)):
                revenue[-back] = round(revenue[-back - 4] * growth)

        cases.append(("this quarter's growth fell", state(rising), state(lambda s: rising(s, 1.0)),
                      ["连升三季以上的回升", "这一段已连升"]))

        # 10-11. Every threshold line on its safe side, then every risk line crossed.
        read = readings(source)

        def place(s: dict, key: str, crossed: bool) -> None:
            for entry in s[key]["quantified"]:
                value = read[entry["reads"]]
                over = round(value + abs(value) * 0.1 + 1, 3)
                under = round(value - abs(value) * 0.1 - 1, 3)
                safe_above = favourable_side(entry) == "up"
                if entry["tier"] == "risk" and crossed:
                    entry["threshold"] = over if safe_above else under
                else:
                    entry["threshold"] = under if safe_above else over

        risks = sum(1 for e in source["prior_kpi_settlement"]["quantified"]
                    if e["tier"] == "risk" and not e.get("due_from"))
        cases.append(("settled risk lines breached",
                      state(lambda s: place(s, "prior_kpi_settlement", False)),
                      state(lambda s: place(s, "prior_kpi_settlement", True)),
                      [f"{risks} 条风险线都守住", "没有一行的风险条件成立"]))
        watched = sum(1 for e in source["next_kpi"]["quantified"] if e["tier"] == "risk")
        cases.append(("next-quarter risk lines already crossed",
                      state(lambda s: place(s, "next_kpi", False)),
                      state(lambda s: place(s, "next_kpi", True)),
                      [f"{watched} 条风险线当前都在安全侧"]))

        # 12. A refund that turns North America from up to down on the year, then a trivial one.
        segments = source["segments_usd_m"]
        year_ago = segments["na_operating_income"][-5] / segments["na_revenue"][-5] * 100
        refund = round(segments["na_revenue"][-1] * 0.008)

        def refund_of(s: dict, amount: int) -> None:
            seg = s["segments_usd_m"]
            seg["na_operating_income"][-1] = round(seg["na_revenue"][-1] * (year_ago + 0.4) / 100)
            s["one_off_items"] = {"period": period, "tariff_refund_usd_m": amount}

        cases.append(("a refund too small to flip North America", state(lambda s: refund_of(s, refund)),
                      state(lambda s: refund_of(s, 10)),
                      ["负经营杠杆", "剔除后北美的方向就变了", f"北美剔除 US${refund}M 关税退款后"]))

        # 13. The exception quarters of the two-leg decomposition, then none.
        def cost_led_everywhere(s: dict) -> None:
            guide = s["quarterly_guidance_history"]
            for i in leg_exceptions(guide):
                guide["actual_operating_income_bn"][i] = round(
                    (guide["operating_income_low_bn"][i] + guide["operating_income_high_bn"][i]) / 2 * 3 + 1, 3)

        exceptions = leg_exceptions(source["quarterly_guidance_history"])
        if exceptions:
            first = source["quarterly_guidance_history"]["quarters"][exceptions[0]]
            quarter, year = first.split()
            cases.append(("no quarter led by revenue", source, state(cost_led_everywhere),
                          [f"例外是 {quarter}'{year[-2:]}"]))

        for name, holds, fails, claims in cases:
            with_claim = published_text(build_payload(holds))
            without = published_text(build_payload(fails))
            for claim in claims:
                with self.subTest(case=name, claim=claim):
                    self.assertIn(claim, with_claim)
                    self.assertNotIn(claim, without)

        costs_only_text = published_text(build_payload(state(cost_led_everywhere)))
        self.assertIn("无论正负，都来自成本而不是需求", costs_only_text)
        self.assertIn("是四条零售线里唯一在加速的", published_text(build_payload(retail)))

    def test_the_counted_sentences_follow_the_record(self) -> None:
        """Every count the prose states, recounted here from the series -- so the
        check holds in any quarter and a stale count still fails it."""
        text = published_text(self.payload)
        guide = self.source["quarterly_guidance_history"]
        sales, low, high = guide["actual_net_sales_bn"], guide["net_sales_low_bn"], guide["net_sales_high_bn"]
        done = [i for i, value in enumerate(sales) if value is not None]
        above = sum(1 for i in done if sales[i] > high[i])
        below = sum(1 for i in done if sales[i] < low[i])
        present = [f"{len(done)} 个已完结季，收入"
                   + ("一次都没有跌破过区间下限" if not below else f"跌破区间下限 {below} 次")
                   + f"；上穿上限 {above} 次、落在区间内 {len(done) - above - below} 次"]
        window = done[-20:]
        close = sum(1 for i in window if abs(sales[i] / ((low[i] + high[i]) / 2) - 1) * 100 <= 2)
        present.append(f"{len(window)} 季里 {close} 季的偏离在 ±2% 以内" if close * 2 > len(window)
                       else f"{len(window)} 季里只有 {close} 季的偏离在 ±2% 以内")
        negative_lows = sum(1 for value in guide["operating_income_low_bn"] if value <= 0)
        if negative_lows:
            present.append(f"有{cn_count(negative_lows)}季的区间下限是负数或零")
        income, income_low, income_high = (guide["actual_operating_income_bn"], guide["operating_income_low_bn"],
                                           guide["operating_income_high_bn"])
        exceptions = 0
        for i in done:
            guided_sales, guided_income = (low[i] + high[i]) / 2, (income_low[i] + income_high[i]) / 2
            margin = guided_income / guided_sales
            revenue_leg = (sales[i] - guided_sales) * margin
            margin_leg = sales[i] * (income[i] / sales[i] - margin)
            exceptions += not abs(margin_leg) > abs(revenue_leg)
        present.append(f"{len(done)} 季里 {len(done) - exceptions} 季来自成本而不是需求" if exceptions
                       else "无论正负，都来自成本而不是需求")
        lines = self.source["product_lines_usd_m"]
        names = ("advertising_services", "online_stores", "third_party_seller_services", "subscription_services")
        rising = [name for name in names
                  if lines[name][-1] / lines[name][-5] > lines[name][-2] / lines[name][-6]]
        if "advertising_services" in rising:
            others = len(rising) - 1
            present.append("是四条零售线里唯一在加速的" if not others else
                           "四条零售线全部在加速" if len(rising) == 4 else
                           f"四条零售线里有{cn_count(len(rising))}条在加速")
        backlog = self.source["aws_backlog"]["level_usd_bn"]
        present.append(f"净增共 {len(backlog) - 1} 个可比点")
        snapshot = self.source.get("current_snapshot")
        if snapshot is not None:
            one_off = self.source.get("one_off_items") or {}
            operating = (snapshot["pre_tax_income_usd_m"][-1] - snapshot["other_income_expense_net_usd_m"][-1]
                         - one_off.get("tariff_refund_usd_m", 0) - one_off.get("energy_derivative_gain_usd_m", 0))
            shares = snapshot["diluted_shares_m"][-1]
            present.append(f"US${operating * 0.76 / shares:.2f}–US${operating * 0.79 / shares:.2f}")
        present.append(f"{len(guide['quarters'])} 个被指引季（{guide['quarters'][0]} – {guide['quarters'][-1]}）")
        long = self.source["long_history"]
        first = long["capex_first_reported"]
        present.append(f"起点是 Q{first[-1]}'{first[2:4]}")
        present.append(f"资本开支有申报值的 {sum(1 for v in long['capital_expenditures_usd_m'] if v is not None)} 季里")
        for sentence in present:
            with self.subTest(present=sentence):
                self.assertIn(sentence, text)
        for gone in ("九年 36", "37 个被指引季", "公司只在最近四个季度", "唯一在加速",
                     "起点是 Q2'16", "本站唯一", "US$1.83–US$1.92", "十几分之一",
                     "只有这一条留在三十季", "从 2019Q1 起才有", "分国家收入（公司不披露）",
                     "高点的两倍", "绝大多数季度", "**"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, text)


QUARTER_END = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}


def rolled_forward(source: dict) -> dict:
    """The series one quarter on, built in memory the way a roll edits
    `series/amzn.json` and nothing else: every aligned array gets a cell (the
    same quarter a year earlier, grown 10%), `latest` and the sources move on,
    the one-quarter story blocks are dropped, this quarter's `next_kpi` moves
    into `prior_kpi_settlement` as it stands, a `followup_closure` closes this
    quarter's follow-up questions, and a `next_kpi` is written for the quarter
    after. The builder is not touched."""
    rolled = copy.deepcopy(source)
    period = rolled["periods"][-1]
    new = next_quarter(period)

    def extend(values: list) -> None:
        base = values[-4]
        values.append(None if base is None else round(base * 1.1, 3))

    rolled["periods"].append(new)
    q = rolled["quarterly_usd_m"]
    for values in q.values():
        if isinstance(values, list):
            extend(values)
    q["net_capex"][-1] = q["purchases_of_property_and_equipment"][-1] - q["proceeds_from_pe_sales_and_incentives"][-1]
    for block in ("segments_usd_m", "product_lines_usd_m", "cash_flow_disclosed"):
        for name, values in rolled[block].items():
            if name == "periods":
                values.append(new)
            elif isinstance(values, list) and name != "definition_changes":
                extend(values)
    cash = rolled["cash_flow_disclosed"]
    cash["free_cash_flow_ttm"][-1] = cash["operating_cash_flow_ttm"][-1] - cash["net_capex_ttm"][-1]
    long = rolled["long_history"]
    for name, values in long.items():
        if name == "quarters":
            values.append(quarter_key(new))
        elif isinstance(values, list):
            extend(values)
    # The blocks that overlap have to agree, as they do in a real roll.
    segments = rolled["segments_usd_m"]
    long["aws_revenue_usd_m"][-1] = segments["aws_revenue"][-1]
    long["aws_operating_income_usd_m"][-1] = segments["aws_operating_income"][-1]
    long["revenue_usd_m"][-1] = q["revenue_total"][-1]
    long["operating_income_usd_m"][-1] = q["operating_income"][-1]
    backlog = rolled["aws_backlog"]
    backlog["periods"].append(new)
    backlog["level_usd_bn"].append(backlog["level_usd_bn"][-1] + 60)
    backlog["weighted_average_life_years"].append(backlog["weighted_average_life_years"][-1])
    guide = rolled["quarterly_guidance_history"]
    guide["actual_net_sales_bn"][-1] = round(q["revenue_total"][-1] / 1000, 3)
    guide["actual_operating_income_bn"][-1] = round(q["operating_income"][-1] / 1000, 3)
    guide["quarters"].append(next_quarter(new))
    for name in ("net_sales_low_bn", "net_sales_high_bn", "operating_income_low_bn", "operating_income_high_bn"):
        guide[name].append(round(guide[name][-4] * 1.1, 1))
    for name in ("actual_net_sales_bn", "actual_operating_income_bn", "fx_bps", "fx_direction"):
        guide[name].append(None)
    year, number = order(new)
    period_end = f"{year}-{QUARTER_END[number]}"
    rolled["latest"].update(period=new, period_end=period_end, release_date=period_end,
                            analysis_date=period_end)
    for name in ("current_snapshot", "one_off_items", "other_income_story", "backlog_concentration",
                 "capital_structure", "guidance", "calendar_shift", "market_expectation", "quarter_story",
                 "local_note_errata"):
        rolled.pop(name, None)
    rolled["sources"].append({"label": f"{new} 业绩 8-K EX-99.1（换季演练）", "url": "https://www.sec.gov/"})
    moved = copy.deepcopy(source["next_kpi"])
    rolled["prior_kpi_settlement"] = {
        "period": new, "set_in": moved["set_in"], "section": moved["section"],
        "rows": moved["rows"], "quantified": moved["quantified"],
    }
    rolled["followup_closure"] = {
        "period": new, "set_in": moved["set_in"],
        "labels": ["已验证", "部分验证", "被证伪", "仍未披露"],
        "rule": "（换季演练的归类规则。）",
        "items": [{"question": item["question"], "short": f"第 {index} 题", "answer": "（换季演练）",
                   "scores": "方向 ✓｜幅度 —｜归因 —｜时点 —",
                   "verdict": "已验证" if index % 2 else "仍未披露",
                   "evidence": "本季 AWS 环比增量 {aws_increment}。"}
                  for index, item in enumerate(moved["followups"], 1)],
    }
    rolled["next_kpi"] = dict(copy.deepcopy(moved), period=new, for_period=next_quarter(new), set_in=new)
    return rolled


class AmznRollRehearsalTest(unittest.TestCase):
    """Next quarter builds from the series alone: this quarter's observation
    table becomes next quarter's section one without a line of code changing."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "amzn.json").read_text(encoding="utf-8"))
        cls.rolled = rolled_forward(cls.source)
        cls.payload = build_payload(cls.rolled)

    def test_the_rolled_quarter_builds_in_four_sections(self) -> None:
        check(self.payload)
        self.assertEqual([s["id"] for s in self.payload["sections"]],
                         ["settled", "quarter_highlights", "next_quarter", "routine"])
        self.assertIn(self.rolled["periods"][-1], self.payload["title"])
        text = published_text(self.payload)
        self.assertNotRegex(text, r"\{[a-z_]+\}", "a story placeholder was not filled")

    def test_section_one_settles_this_quarters_lines(self) -> None:
        moved = self.source["next_kpi"]
        settled = self.payload["sections"][0]["exhibits"]
        closure, overview = settled[0], settled[1]
        self.assertTrue(closure["title"].startswith(f"上季 {len(moved['followups'])} 条待验证问题："))
        self.assertTrue(overview["title"].startswith(f"上季 {len(moved['quantified'])} 条量化阈值："))
        read = readings(self.rolled)
        for entry, value in zip(moved["quantified"], overview["values"]):
            with self.subTest(line=entry["id"]):
                self.assertEqual(value, round(headroom(favourable_side(entry), entry["threshold"],
                                                       read[entry["reads"]]), 1))
        for row in moved["rows"]:
            if row.get("not_drawn_reason"):
                self.assertIn(f"第{cn(row['row'])}行（{row['subject']}）不结算：", overview["note"])
        charts = [ex for ex in settled if ex["kind"] == "lines" and "上季" in ex["title"]]
        self.assertEqual(len(charts), len({entry["reads"] for entry in moved["quantified"]}))
        self.assertIn(f"先结清上季（{moved['set_in']}）", self.payload["sections"][0]["description"])
