"""Reconciliation and shape tests for the NIKE page.

Same purpose as the other companies': nothing derived reaches the page until it
has been checked against a statement identity or a figure the company disclosed
separately.  NIKE gives four identities that close to the dollar in every one of
the forty quarters held here, which is what licenses publishing a series whose
fiscal fourth quarters come from a press release rather than a 10-Q:

    revenue - cost of sales                          = gross profit
    demand creation + operating overhead             = total S&A
    gross profit - S&A - interest - other            = income before taxes
    Σ segment EBIT - interest expense (income), net  = income before taxes

The three vintages of multi-year targets need their own guards, and they are
half the point of this file.  They are read out of prose in ten different 10-K
filings, they are stated in *words* rather than endpoints, and the window each
one covers has to be settled against a base year the company never names --
three places where a page can quietly make the record look cleaner, or dirtier,
than it is.  So the verdict counts are pinned by value, the two goals whose
answer turns on the reading are pinned as *not* decided, the base-year
sensitivity is pinned on the pair that actually flips, and the claim that two
targets asked for numbers NIKE has never printed is pinned against the maximum
of the thirteen-year record rather than left in the prose.

The severance arithmetic gets a test of its own because getting it wrong is the
easy path: the 10-Q prints a three-month figure and a nine-month figure side by
side, and reading the first as the second doubles the fiscal fourth quarter's
charge.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.all import CROSS_ENTRIES, ENTRIES, GROUPS  # noqa: E402
from build.board import headroom  # noqa: E402
from build.board import stamped_block  # noqa: E402
from build.nke import build_payload, compact_period, fiscal_to_calendar  # noqa: E402


def quarter_key(label: str) -> tuple[int, int]:
    """``'Q4 2026'`` → ``(2026, 4)``."""
    quarter, year = label.split()
    return int(year), int(quarter[1])


def quarters_between(first: str, last: str) -> int:
    """Calendar quarters from ``first`` to ``last`` inclusive: ``'Q3 2016'``..``'Q2 2026'`` → 40."""
    (q1, y1), (q2, y2) = (label.split() for label in (first, last))
    return (int(y2) - int(y1)) * 4 + int(q2[1]) - int(q1[1]) + 1


def latest_fiscal_year(fiscal_label: str) -> int:
    """The last fiscal year a 10-K has closed, as of the quarter ``'FY2026Q4'`` names."""
    year, quarter = int(fiscal_label[2:6]), int(fiscal_label[-1])
    return year if quarter == 4 else year - 1


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


class NkeDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "nke.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]
        cls.by_section = {s["id"]: s["exhibits"] for s in cls.payload["sections"]}
        cls.fin = cls.source["financials"]
        cls.seg = cls.source["segments_usd_m"]
        cls.history = cls.source["long_history"]
        cls.targets = cls.source["filed_targets"]
        cls.one_off = stamped_block(cls.source, "one_off_usd_m", cls.source["periods"][-1])

    # ── shape ────────────────────────────────────────────────────────────────
    def test_the_window_is_eight_quarters_and_complete(self) -> None:
        self.assertEqual(len(self.source["periods"]), 8)
        for group in ("financials", "segments_usd_m", "segment_margins_pct",
                      "growth_pct", "channels_usd_m", "product_lines_usd_m",
                      "balance_sheet_usd_m"):
            for key, values in self.source[group].items():
                if key.startswith("_") or not isinstance(values, list):
                    continue
                self.assertEqual(len(values), 8, f"{group}.{key}")

    def test_calendar_labels_map_onto_the_fiscal_ones(self) -> None:
        """NIKE's year ends 31 May, so its Q1 and Q2 fall in the previous
        calendar year and its Q3 and Q4 in the same one.  A slip here silently
        compares different three-month periods against the other pages, and the
        direction of the slip differs by quarter, so both halves are checked."""
        for period, fiscal in zip(self.source["periods"], self.source["fiscal_labels"]):
            self.assertEqual(period, fiscal_to_calendar(fiscal))
            quarter, year = period.split()
            fiscal_year, fiscal_quarter = re.match(r"FY(\d{4})Q(\d)", fiscal).groups()
            if int(fiscal_quarter) <= 2:
                self.assertEqual(quarter, f"Q{int(fiscal_quarter) + 2}")
                self.assertEqual(int(year), int(fiscal_year) - 1)
            else:
                self.assertEqual(quarter, f"Q{int(fiscal_quarter) - 2}")
                self.assertEqual(int(year), int(fiscal_year))

    def test_the_long_quarterly_record_runs_from_fy2017_to_the_page_quarter(self) -> None:
        """Forty quarters when this was written; the invariant is the span."""
        long_q = self.source["long_quarters"]
        self.assertEqual(long_q["fiscal_labels"][0], "FY2017Q1")
        self.assertEqual(long_q["periods"][-1], self.source["periods"][-1])
        self.assertEqual(long_q["fiscal_labels"][-1], self.source["fiscal_labels"][-1])
        span = quarters_between(long_q["periods"][0], long_q["periods"][-1])
        self.assertGreaterEqual(span, 40)
        for key, values in long_q.items():
            if isinstance(values, list):
                self.assertEqual(len(values), span, key)

    def test_the_channel_record_starts_at_asc_606_and_is_not_padded(self) -> None:
        """The revenue-disaggregation note begins with ASC 606 in FY2019.  The
        FY2018 10-K has no such report at all and the FY2019 Q3 10-Q's
        prior-year column carries blank member rows, so the earlier quarters
        cannot be recovered even from comparatives.  Starting the series there
        is the honest answer; padding it backwards would invent the split."""
        channel = self.source["channel_quarters"]
        self.assertEqual(channel["fiscal_labels"][0], "FY2019Q1")
        self.assertEqual(channel["periods"][0], "Q3 2018")
        self.assertEqual(channel["periods"][-1], self.source["periods"][-1])
        self.assertEqual(len(channel["fiscal_labels"]),
                         quarters_between(channel["periods"][0], channel["periods"][-1]))

    # ── statement identities, in all forty quarters ──────────────────────────
    def test_income_statement_closes_to_the_dollar(self) -> None:
        fin = self.fin
        for index, period in enumerate(self.source["periods"]):
            self.assertEqual(
                fin["revenue_usd_m"][index] - fin["cost_of_sales_usd_m"][index],
                fin["gross_profit_usd_m"][index], period)
            self.assertEqual(
                fin["demand_creation_usd_m"][index] + fin["operating_overhead_usd_m"][index],
                fin["total_sga_usd_m"][index], period)
            derived = (fin["gross_profit_usd_m"][index]
                       - fin["total_sga_usd_m"][index]
                       - fin["interest_expense_income_net_usd_m"][index]
                       - fin["other_income_expense_net_usd_m"][index])
            self.assertEqual(derived, fin["pretax_income_usd_m"][index], period)

    def test_segment_bridge_closes_to_the_dollar(self) -> None:
        """Σ segment EBIT − interest expense (income), net = income before taxes.

        NIKE sums Corporate *into* the total rather than subtracting it, which is
        the opposite of how several other filers here present the same bridge, so
        this is worth pinning rather than assuming.
        """
        seg, fin = self.seg, self.fin
        names = ("north_america", "emea", "greater_china", "apla",
                 "global_brand_divisions", "converse", "corporate")
        for index, period in enumerate(self.source["periods"]):
            total_ebit = sum(seg[f"{name}_ebit"][index] for name in names)
            self.assertEqual(total_ebit, seg["total_nike_inc_ebit"][index], period)
            self.assertEqual(
                total_ebit - fin["interest_expense_income_net_usd_m"][index],
                fin["pretax_income_usd_m"][index], period)

    def test_segment_revenue_sums_to_consolidated_revenue(self) -> None:
        seg, fin = self.seg, self.fin
        names = ("north_america", "emea", "greater_china", "apla",
                 "global_brand_divisions", "converse", "corporate")
        for index, period in enumerate(self.source["periods"]):
            self.assertEqual(sum(seg[f"{name}_revenue"][index] for name in names),
                             seg["total_nike_inc_revenue"][index], period)
            self.assertEqual(seg["total_nike_inc_revenue"][index],
                             fin["revenue_usd_m"][index], period)

    def test_channel_split_sums_to_nike_brand_revenue(self) -> None:
        channels, seg = self.source["channels_usd_m"], self.seg
        for index, period in enumerate(self.source["periods"]):
            self.assertEqual(
                channels["nike_brand_wholesale"][index] + channels["nike_brand_direct"][index]
                + seg["global_brand_divisions_revenue"][index],
                channels["nike_brand_total"][index], period)
            self.assertEqual(channels["nike_brand_total"][index],
                             seg["total_nike_brand_revenue"][index], period)

    def test_product_lines_sum_to_nike_brand_revenue(self) -> None:
        products, seg = self.source["product_lines_usd_m"], self.seg
        for index, period in enumerate(self.source["periods"]):
            total = sum(products[line][index] for line in ("footwear", "apparel", "equipment"))
            self.assertEqual(total + seg["global_brand_divisions_revenue"][index],
                             seg["total_nike_brand_revenue"][index], period)

    # ── the annual record and the derivations that hang off it ───────────────
    def test_annual_identities_hold_in_all_thirteen_years(self) -> None:
        history = self.history
        for index, year in enumerate(history["fiscal_years"]):
            self.assertEqual(
                history["revenue_usd_m"][index] - history["cost_of_sales_usd_m"][index],
                history["gross_profit_usd_m"][index], year)
            self.assertEqual(
                history["demand_creation_usd_m"][index] + history["operating_overhead_usd_m"][index],
                history["total_sga_usd_m"][index], year)
            self.assertEqual(
                history["pretax_income_usd_m"][index] - history["income_tax_usd_m"][index],
                history["net_income_usd_m"][index], year)
            self.assertEqual(
                history["wholesale_usd_m"][index] + history["nike_direct_usd_m"][index]
                + history["global_brand_divisions_usd_m"][index],
                history["nike_brand_usd_m"][index], year)

    def test_the_ebit_margin_derivation_reproduces_the_company_figure(self) -> None:
        """EBIT is a NIKE-defined non-GAAP measure the company prints only from
        FY2022 onward.  The page extends it back to FY2014 on the same
        definition, so the eight earlier years are only publishable if the five
        overlapping ones reproduce the printed figure -- which they do, to the
        tenth of a point.  If this ever fails, the extension is what to delete,
        not the assertion.
        """
        history = self.history
        checked = 0
        for index, year in enumerate(history["fiscal_years"]):
            disclosed = history["ebit_margin_disclosed_pct"][index]
            derived_ebit = (history["pretax_income_usd_m"][index]
                            + history["interest_expense_income_net_usd_m"][index])
            self.assertEqual(derived_ebit, history["ebit_usd_m"][index], year)
            if disclosed is None:
                continue
            checked += 1
            self.assertAlmostEqual(disclosed, history["ebit_margin_pct"][index], delta=0.05,
                                   msg=f"FY{year}")
        self.assertEqual(checked, 5, "the disclosed EBIT margin window moved")

    def test_direct_share_is_a_division_of_two_filed_lines(self) -> None:
        history = self.history
        for index, year in enumerate(history["fiscal_years"]):
            self.assertAlmostEqual(
                history["nike_direct_usd_m"][index] / history["nike_brand_usd_m"][index] * 100,
                history["nike_direct_share_pct"][index], places=3, msg=str(year))
        self.assertEqual(history["fiscal_years"][0], 2014)
        # The annual record ends at the last year a 10-K has closed.
        self.assertEqual(history["fiscal_years"][-1],
                         latest_fiscal_year(self.source["fiscal_labels"][-1]))
        self.assertAlmostEqual(history["nike_direct_share_pct"][0], 20.3, delta=0.05)
        self.assertAlmostEqual(max(history["nike_direct_share_pct"]), 43.7, delta=0.05)

    # ── the one-off items ────────────────────────────────────────────────────
    def test_the_tariff_refund_is_isolated_to_one_quarter(self) -> None:
        """A one-quarter story lives in a block stamped with that quarter.

        While the block is current its pieces have to add up; once a roll moves
        past it the block is dropped and no refund language may survive on the
        page -- the failure this replaces is last quarter's refund narrated under
        this quarter's label.
        """
        one_off = self.one_off
        if one_off is None:
            blob = json.dumps(self.payload, ensure_ascii=False)
            self.assertNotIn("IEEPA", blob.split('"tables"')[0])
            return
        refund = one_off["ieepa_tariff_refund_benefit"]
        self.assertEqual(refund[:-1], [None] * (len(refund) - 1),
                         "the refund is a single quarter's event, not a series of zeros")
        self.assertEqual(one_off["ieepa_refund_north_america"] + one_off["ieepa_refund_converse"],
                         refund[-1])
        self.assertEqual(one_off["ieepa_cash_received_by_period_end"]
                         + one_off["ieepa_receivable_at_period_end"], refund[-1])
        # the year's refund in the annual record is the same money
        self.assertEqual(self.history["ieepa_refund_usd_m"][-1], refund[-1])

    def test_gross_margin_ex_refund_is_the_refund_removed_and_nothing_else(self) -> None:
        fin, one_off = self.fin, self.source["one_off_usd_m"]
        for index in range(len(fin["revenue_usd_m"])):
            refund = one_off["ieepa_tariff_refund_benefit"][index] or 0
            expected = ((fin["gross_profit_usd_m"][index] - refund)
                        / fin["revenue_usd_m"][index] * 100)
            self.assertAlmostEqual(expected, fin["gross_margin_ex_tariff_refund_pct"][index],
                                   places=3, msg=self.source["periods"][index])
        # The release prints the margin and the refund's effect in basis points;
        # both are keyed separately into `_checks` and the series must agree.
        checks = self.source["_checks"]
        self.assertEqual(round(fin["gross_margin_pct"][-1], 1), checks["gross_margin_pct"])
        refund_pp = fin["gross_margin_pct"][-1] - fin["gross_margin_ex_tariff_refund_pct"][-1]
        self.assertAlmostEqual(refund_pp * 100, checks.get("refund_gross_margin_benefit_bp", 0),
                               delta=5)

    def test_the_fiscal_fourth_quarter_severance_is_a_difference_of_two_filed_figures(self) -> None:
        """The 10-Q prints "three months ... and nine months" in one sentence.

        Reading the first number as the second is the mistake this exists to
        stop: US$230M is the quarter, US$304M is the nine months, and the year
        is US$385M -- so the fiscal fourth carries US$81M, not the US$155M the
        year-minus-the-quarter gives or the US$170M an approximate year total
        gives.  The expense-line split has to close on the same subtraction, and
        it is the half that matters for the gross-margin bridge: the fourth
        quarter put MORE into cost of sales than the whole nine months before it,
        while releasing part of the operating-overhead accrual.
        """
        sev, one_off = self.source["severance"], self.one_off
        if one_off is None:
            return          # no fiscal-fourth decomposition is published this quarter
        year = sev["total_usd_m"][sev["fiscal_years"].index(sev["interim_fiscal_year"])]
        self.assertEqual(one_off["severance_q4_total"], year - sev["nine_months_total_usd_m"])
        self.assertNotEqual(one_off["severance_q4_total"], year - sev["q3_quarter_total_usd_m"],
                            "reading the quarter as the nine months gives a different fourth quarter")
        self.assertEqual(one_off["severance_q4_cost_of_sales"],
                         sev["cost_of_sales_usd_m"][-1] - sev["nine_months_cost_of_sales_usd_m"])
        self.assertEqual(one_off["severance_q4_operating_overhead"],
                         sev["operating_overhead_usd_m"][-1] - sev["nine_months_overhead_usd_m"])
        self.assertEqual(one_off["severance_q4_cost_of_sales"]
                         + one_off["severance_q4_operating_overhead"],
                         one_off["severance_q4_total"])
        self.assertLess(one_off["severance_q4_operating_overhead"], 0,
                        "the fourth quarter released part of the overhead accrual")
        self.assertEqual(sev["operating_overhead_usd_m"][-1] + sev["cost_of_sales_usd_m"][-1], year)

    # ── the filed multi-year targets ─────────────────────────────────────────
    def test_the_three_vintages_and_their_verdicts_are_pinned_by_value(self) -> None:
        vintages = {v["key"]: v for v in self.targets["vintages"]}
        self.assertEqual(set(vintages), {"fy2020", "fy2023", "fy2025"})
        counts = {key: len(v["goals"]) for key, v in vintages.items()}
        self.assertEqual(counts, {"fy2020": 3, "fy2023": 5, "fy2025": 6})
        verdicts = [goal["verdict"] for v in self.targets["vintages"] for goal in v["goals"]]
        self.assertEqual(verdicts.count("hit"), 1, "one goal in fourteen was met")
        self.assertEqual(verdicts.count("miss"), 11)
        self.assertEqual(verdicts.count("boundary"), 1)
        self.assertEqual(verdicts.count("base_dependent"), 1)
        latest = vintages["fy2025"]
        self.assertTrue(all(goal["verdict"] == "miss" for goal in latest["goals"]),
                        "the last vintage missed on every goal")
        self.assertEqual(latest["set_on"], "2021-07-20")
        self.assertEqual(latest["target_fiscal_year"], 2025)

    def test_the_two_goals_whose_answer_turns_on_a_choice_are_not_decided(self) -> None:
        """A page that resolved these would be publishing its own convention as
        the company's record.  The revenue goal lands on the edge of the band
        the words imply (7.07% against "high single-digit"), and the EPS goal
        flips outright on the base year -- +22.5% from FY2018, +4.3% from
        FY2017 -- because FY2018's earnings were cut by the Tax Act's one-off
        charge at a 55.3% effective rate.  Both are reported as undecided.
        """
        vintage = next(v for v in self.targets["vintages"] if v["key"] == "fy2023")
        by_verdict = {goal["verdict"]: goal for goal in vintage["goals"]}
        self.assertIn("boundary", by_verdict)
        self.assertIn("base_dependent", by_verdict)
        revenue = by_verdict["boundary"]
        self.assertAlmostEqual(revenue["delivered"], 7.07, delta=0.02)
        self.assertLess(abs(revenue["delivered"] - revenue["lo"]), 0.2,
                        "if it stops sitting on the bound, decide it")
        eps = by_verdict["base_dependent"]
        self.assertGreater(eps["delivered"], eps["lo"])
        self.assertLess(eps["alt_base_delivered"], eps["lo"])

    def test_two_targets_asked_for_numbers_nike_has_never_printed(self) -> None:
        """The page's sharpest claim, so it is arithmetic rather than prose.

        The fiscal-2025 vintage asked for a gross margin in the high 40s and an
        EBIT margin in the high teens.  Against the thirteen-year filed record
        both are above the maximum the company has ever reported, which is what
        makes the miss structural rather than a bad four years.
        """
        record = self.targets["record_levels"]
        history = self.history
        self.assertAlmostEqual(record["max_gross_margin_pct"],
                               max(history["gross_margin_pct"]), places=4)
        self.assertAlmostEqual(record["max_ebit_margin_pct"],
                               max(history["ebit_margin_pct"]), places=3)
        latest = next(v for v in self.targets["vintages"] if v["key"] == "fy2025")
        goals = {goal["metric"]: goal for goal in latest["goals"]}
        gross = next(g for k, g in goals.items() if "毛利率" in k)
        ebit = next(g for k, g in goals.items() if "EBIT" in k)
        self.assertLess(record["max_gross_margin_pct"], gross["lo"])
        self.assertLess(record["max_ebit_margin_pct"], ebit["lo"])
        self.assertEqual(record["max_gross_margin_fiscal_year"], 2016)
        self.assertEqual(record["max_ebit_margin_fiscal_year"], 2021)

    def test_the_withdrawal_is_recorded_as_a_census_not_an_impression(self) -> None:
        withdrawal = self.targets["withdrawal"]
        self.assertEqual(len(withdrawal["since"]), 4)
        self.assertEqual(withdrawal["since"],
                         ["FY2023 10-K", "FY2024 10-K", "FY2025 10-K", "FY2026 10-K"])
        census = self.targets["quarterly_outlook_census"]
        self.assertEqual(census["releases_examined"], 40)
        self.assertEqual(census["with_operating_outlook"], 0)
        self.assertEqual(census["with_any_forward_number"], 3)

    def test_the_only_filed_quarterly_record_breaks_in_both_directions(self) -> None:
        """Every other guidance record on this site is one-sided -- the company
        clears the same bound over and over, which is what makes those pages
        argue that the range is a floor rather than a forecast.  NIKE's is the
        exception, and the exception is only interesting if both directions are
        actually present, so that is what is asserted rather than the total.
        """
        record = self.source["filed_quarterly_guidance_2017_2018"]
        self.assertEqual(record["scoreable_bands"], 10)
        self.assertEqual(len(record["items"]), 10)
        self.assertEqual(record["landed_inside"], 2)
        self.assertEqual(record["broke_low"], 5)
        self.assertEqual(record["broke_high"], 3)
        self.assertGreater(record["broke_low"], 0)
        self.assertGreater(record["broke_high"], 0)
        self.assertEqual(record["landed_inside"] + record["broke_low"] + record["broke_high"],
                         record["scoreable_bands"])
        # A band's half-width is the unit, so |z| > 1 is outside it.
        outside = [item for item in record["items"]
                   if abs(item["half_widths_from_midpoint"]) > 1]
        self.assertEqual(len(outside), record["broke_low"] + record["broke_high"])
        forms = record["next_quarter_item_forms"]
        self.assertEqual(forms["range"], 10)
        self.assertEqual(sum(forms.values()), 34)
        self.assertGreater(forms["verbal"], forms["range"],
                           "most of what NIKE filed was words, and the page says so")

    # ── the exhibits themselves ──────────────────────────────────────────────
    def test_next_quarter_headroom_bars_match_the_thresholds_they_claim_to_plot(self) -> None:
        entries = self.source["next_kpi"]
        exhibit = next(ex for ex in self.by_section["next_quarter"] if ex["kind"] == "diverging_bars"
                       and ex["xlabels"] == [e["metric"] for e in entries])
        expected = [round(headroom(e["direction"], e["threshold"], e["current"]), 1) for e in entries]
        self.assertEqual(exhibit["values"], expected)

    def test_the_target_headroom_chart_plots_the_last_vintage_only(self) -> None:
        latest = next(v for v in self.targets["vintages"] if v["key"] == "fy2025")
        exhibit = next(ex for ex in self.by_section["settled"]
                       if ex["kind"] == "diverging_bars"
                       and ex["xlabels"] == [g["metric"] for g in latest["goals"]])
        self.assertEqual(len(exhibit["values"]), 6)
        self.assertTrue(all(value < 0 for value in exhibit["values"]),
                        "six goals, six shortfalls -- no bar should be positive")

    def test_the_page_has_the_site_s_four_sections_in_order(self) -> None:
        """The owner's four-part format, TSM's titles verbatim, and the page's
        own sentence about its structure saying the same thing."""
        self.assertEqual(
            [(section["id"], section["title"]) for section in self.payload["sections"]],
            [("settled", "一、上季跟踪指标兑现了吗"), ("quarter_highlights", "二、本季重点"),
             ("next_quarter", "三、下季要跟踪什么"), ("routine", "四、长期常规跟踪")])
        self.assertTrue(all(section["exhibits"] for section in self.payload["sections"]))
        self.assertIn("本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列",
                      self.payload["notes"][0])

    def test_sections_and_exhibit_numbering(self) -> None:
        self.assertEqual([s["id"] for s in self.payload["sections"]],
                         ["settled", "quarter_highlights", "next_quarter", "routine"])
        self.assertEqual([ex["n"] for ex in self.exhibits],
                         list(range(1, len(self.exhibits) + 1)))
        # 21 charts every quarter; one threshold-history chart per reading the
        # previous report's due thresholds are scored against; the call-guidance
        # chart while last quarter's call put numbers on this quarter; the
        # gross-margin bridge while a stamped one-off block exists; and the
        # buyback-price chart while the programme block describes the latest
        # fiscal year. Counted from the series, not remembered.
        period = self.source["periods"][-1]
        prior = stamped_block(self.source, "prior_kpi_settlement", period)
        due_readings = {e["reads"] for e in prior["quantified"]
                        if not e.get("settles") or quarter_key(e["settles"]) <= quarter_key(period)}
        guide = stamped_block(self.source, "prior_call_guidance", period)
        charted_guide = guide is not None and any("low" in i and i.get("chart") for i in guide["items"])
        buyback = self.source.get("buyback_programme")
        optional = ((self.one_off is not None) + charted_guide
                    + (buyback is not None
                       and buyback["as_of_fiscal_year"] == self.history["fiscal_years"][-1]))
        self.assertEqual(len(self.exhibits), 21 + len(due_readings) + optional)
        for exhibit in self.exhibits:
            self.assertNotIn("ref", exhibit, exhibit["n"])
            for field in ("title", "note", "src_extra"):
                self.assertNotIn("{EX_", exhibit.get(field) or "", exhibit["n"])

    def test_no_series_is_named_for_a_metric_the_company_does_not_disclose(self) -> None:
        """NIKE reports no revenue for Sportswear, Jordan Streetwear or Football,
        and no gross margin or inventory by geography.  Management describes
        them in words on the call, and turning a word into a number needs a
        self-selected ratio -- an assumption, not arithmetic.

        Jordan *Brand* is not on that list, and this docstring used to say it
        was: its full-year revenue is printed in a footnote of the fiscal-Q4
        release and of the 10-K (FY2024-FY2026 in the FY2026 10-K), and the
        FY2025 Q4 release carried it in a table. It is annual only, so the page
        does not draw it -- the notes say so instead of calling it undisclosed.

        The check is on what gets *plotted or tabulated*, not on the words
        anywhere in the payload: the notes have to be able to name these to say
        they are excluded, and a ban on the string would make the promise
        unwritable.  So it walks every series name, axis label and table header.
        """
        names: list[str] = []
        for exhibit in self.exhibits:
            names.extend(exhibit.get("xlabels") or [])
            for key in ("series", "groups", "stacks"):
                names.extend(item.get("name", "") for item in exhibit.get(key) or [])
            for key in ("bar", "line", "yoy"):
                block = exhibit.get(key)
                if isinstance(block, dict):
                    names.append(block.get("name", ""))
            names.append(exhibit.get("legend") or "")
        for table in self.payload["tables"]:
            names.extend(table["headers"])
        blob = " ".join(names)
        for banned in ("Sportswear", "Jordan Streetwear", "Football", "自由现金流"):
            self.assertNotIn(banned, blob, banned)
        notes = " ".join(self.payload["notes"])
        for promised in ("Sportswear", "自由现金流", "按地域拆的毛利率", "Jordan Brand 的全年收入"):
            self.assertIn(promised, notes, promised)
        self.assertNotIn("Sportswear/Jordan/Football 的收入与增速（无披露）", notes)

    def test_notes_carry_no_markup(self) -> None:
        """`page.js` runs every note through `esc()`, so a tag reaches the reader
        as the literal characters.  The shared gate in
        `test_content_boundary.py` deliberately excludes `notes` while two older
        pages are still red on it; this page opts itself in rather than
        inheriting the exemption.
        """
        for note in self.payload["notes"]:
            self.assertNotIn("<", note, note[:40])

    def test_nke_is_not_in_the_cross_page_capex_table(self) -> None:
        """Carrying the site-wide block and being a column in it are separate
        things, and this page is the seventh to do the first without the second.
        """
        table = next(t for t in self.payload["tables"] if "AI capex" in t["title"])
        self.assertNotIn("NKE", " ".join(table["headers"]))
        self.assertEqual(len([h for h in table["headers"] if "CapEx" in h]), 4)

    def test_the_outlook_block_is_labelled_as_not_being_from_a_filing(self) -> None:
        """It is the one block on the page that no filing carries, which is why
        it is here at all; a reader must not mistake it for the filed record the
        rest of the section settles.
        """
        guidance = self.payload["guidance"]
        if stamped_block(self.source, "guidance", self.source["periods"][-1]) is None:
            self.assertIsNone(guidance)
            return
        self.assertNotIn("period", guidance)
        self.assertIn("电话会", guidance["title"])
        self.assertIn("不在任何申报文件中", guidance["title"])
        self.assertIn("conference call", guidance["note"])

    # ── registration and publication ─────────────────────────────────────────
    def test_published_payload_and_home_card(self) -> None:
        published = js_payload(ROOT / "data" / "nke.js", "window.DASH")
        self.assertEqual(published, self.payload)
        entry = next(e for e in ENTRIES if e["slug"] == "nke")
        # The nav renders `R.groups.forEach(g => byGroup[g.key])`, so a group key
        # ENTRIES names but GROUPS does not carry makes the company unreachable
        # from every page's dropdown with the whole suite still green.
        self.assertEqual(entry["group"], self.payload["company"]["group"])
        self.assertIn(entry["group"], {g["key"] for g in GROUPS})
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="nke/"', home)
        self.assertIn("NIKE, Inc.", home)
        self.assertIn(f'{len(ENTRIES)} 家公司', home)
        self.assertEqual(home.count('class="hcard"'), len(ENTRIES))

    def test_the_shell_stamps_the_payload_it_actually_links(self) -> None:
        """`test_shell_versions_every_script_by_content` runs after
        `build/all.py` has regenerated the shell, so it only ever sees a
        consistent pair and cannot catch a stale digest that was committed.
        Checking the payload's digest by value from the file on disk does.
        """
        shell = (ROOT / "nke" / "index.html").read_text(encoding="utf-8")
        for relative in ("data/roster.js", "data/nke.js", "assets/charts.js", "assets/page.js"):
            digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()[:8]
            self.assertIn(f"../{relative}?v={digest}", shell, relative)

    def test_the_readme_url_list_matches_the_roster_item_for_item(self) -> None:
        """A hand-maintained list of every page, with nothing checking it.

        The TJX commit that landed before this one reported adding exactly this
        assertion after finding `schw` missing; the assertion was never written,
        and by the time this page was built the list had drifted again -- `msci`
        had landed two commits earlier and was absent. That is the same failure
        the slug-list guard in `test_content_boundary.py` exists for, one file
        over: a list nothing reads is a list that quietly stops being true.

        Asserted in order, so a slug appended rather than inserted is red too.
        """
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        listed = re.findall(r"http://127\.0\.0\.1:8765/([a-z]+)/", readme)
        # Company pages first, in `ENTRIES` order, then the cross-company pages
        # in theirs. Both lists are here because the check is 「every page you
        # can open is listed」, and a cross page is a page you can open.
        self.assertEqual(listed, [entry["slug"] for entry in ENTRIES]
                         + [entry["slug"] for entry in CROSS_ENTRIES])

    def test_compact_period_and_fiscal_mapping_round_trip(self) -> None:
        self.assertEqual(compact_period("Q2 2026"), "Q2'26")
        self.assertEqual(fiscal_to_calendar("FY2026Q4"), "Q2 2026")
        self.assertEqual(fiscal_to_calendar("FY2026Q1"), "Q3 2025")
        self.assertEqual(fiscal_to_calendar("FY2018Q3"), "Q1 2018")



# Where each reading lives in the series, for the tests that build a second state.
READING_PATHS = {
    "na_cn": ("growth_pct", "north_america_currency_neutral"),
    "na_rep": ("growth_pct", "north_america_reported"),
    "gc_cn": ("growth_pct", "greater_china_currency_neutral"),
    "gc_rep": ("growth_pct", "greater_china_reported"),
    "total_cn": ("growth_pct", "total_nike_inc_currency_neutral"),
    "total_rep": ("growth_pct", "total_nike_inc_reported"),
    "gm_change_ex_bp": ("release_changes", "gross_margin_change_ex_refund_bp"),
    "gm_change_bp": ("release_changes", "gross_margin_change_bp"),
    "overhead_change_pct": ("release_changes", "operating_overhead_change_pct"),
}


def readings(staging: dict) -> dict[str, float]:
    """This quarter's value of every reading a threshold or a guide is scored
    against, computed here from the series -- not through the builder's helpers."""
    values = {key: float(staging[block][name][-1]) for key, (block, name) in READING_PATHS.items()}
    fin, history = staging["financials"], staging["long_history"]
    refund = history["ieepa_refund_usd_m"][-1] or 0
    values.update({
        "fx_points": values["total_rep"] - values["total_cn"],
        "fy_ebit_margin_ex": (history["ebit_usd_m"][-1] - refund) / history["revenue_usd_m"][-1] * 100,
        "fy_ebit_margin_rep": history["ebit_margin_pct"][-1],
        "sga_change_pct": (fin["total_sga_usd_m"][-1] / fin["total_sga_usd_m"][-5] - 1) * 100,
        "other_net_expense": (fin["interest_expense_income_net_usd_m"][-1]
                              + fin["other_income_expense_net_usd_m"][-1]),
        "fy_tax_rate": history["effective_tax_rate_pct"][-1],
    })
    return values


def due_entries(staging: dict) -> list[dict]:
    """The previous report's thresholds whose window has closed by this quarter."""
    period = staging["periods"][-1]
    return [entry for entry in staging["prior_kpi_settlement"]["quantified"]
            if not entry.get("settles") or quarter_key(entry["settles"]) <= quarter_key(period)]


def check_section_one(test: unittest.TestCase, staging: dict, payload: dict) -> None:
    """Section one against `_checks["note"]` and readings computed here.

    (a) the follow-up tally, (b) the overview and one chart per reading with
    every due line on it, (c) the call-guidance chart while last quarter's call
    put numbers on this quarter, then the filed record. Nothing here names a
    quarter, so a roll does not edit it.
    """
    note = staging["_checks"]["note"]
    settled = next(section for section in payload["sections"] if section["id"] == "settled")
    exhibits = list(settled["exhibits"])
    closure = exhibits.pop(0)
    test.assertEqual(closure["kind"], "bars_labeled")
    test.assertTrue(closure["title"].startswith(f"上季 {note['followup_closure']['total']} 条待验证问题："),
                    closure["title"])
    test.assertEqual(dict(zip(closure["xlabels"], closure["values"])), note["followup_closure"]["counts"])

    now = readings(staging)
    due = due_entries(staging)
    overview = exhibits.pop(0)
    test.assertEqual(overview["kind"], "diverging_bars")
    test.assertTrue(overview["title"].startswith(f"上季 {len(due)} 条量化阈值："), overview["title"])
    bars = [entry for entry in due if entry["threshold"] != 0]
    test.assertEqual(len(overview["values"]), len(bars))
    for entry, value in zip(bars, overview["values"]):
        test.assertAlmostEqual(headroom(entry["direction"], entry["threshold"], now[entry["reads"]]),
                               value, places=1, msg=entry["id"])
    groups: dict[str, list[dict]] = {}
    for entry in due:
        groups.setdefault(entry["reads"], []).append(entry)
    for reads, group in groups.items():
        chart = exhibits.pop(0)
        test.assertEqual(chart["kind"], "lines", reads)
        test.assertRegex(chart["title"], r"：(守住|击穿)上季阈值 |：(越过|没够着)加仓门 ")
        test.assertEqual(sorted(line["values"][0] for line in chart["series"][1:]),
                         sorted(entry["threshold"] for entry in group))
        test.assertTrue(all(len(set(line["values"])) == 1 for line in chart["series"][1:]))
        test.assertAlmostEqual(chart["series"][0]["values"][-1], now[reads], places=4)

    guide = stamped_block(staging, "prior_call_guidance", staging["periods"][-1])
    drawn = [item for item in (guide or {}).get("items", []) if "low" in item and item.get("chart")]
    if drawn:
        chart = exhibits.pop(0)
        test.assertTrue(chart["title"].startswith("上季电话会给的本季指引："), chart["title"])
        test.assertEqual(chart["xlabels"], [item["metric"] for item in drawn])
        for item, value in zip(drawn, chart["values"]):
            scale = 0.01 if item["unit"] == "bps" else 1.0
            test.assertAlmostEqual((now[item["reads"]] - (item["low"] + item["high"]) / 2) * scale,
                                   value, places=2, msg=item["reads"])
    # What is left is the company's own filed record, in its fixed order.
    test.assertTrue(exhibits[0]["title"].startswith("公司自己写进 10-K 的最后一轮目标"), exhibits[0]["title"])
    test.assertTrue(exhibits[-1]["title"].startswith("NIKE 唯一一段申报过的下季指引"), exhibits[-1]["title"])


class NkeSettledSectionTest(unittest.TestCase):
    """Section one, 「上季跟踪指标兑现了吗」, held to the two reports.

    The expected values come from `_checks["note"]`, keyed a second time from
    the reports themselves (this quarter's section 0, last quarter's section 8
    and the call it quotes) -- never from the blocks the builder reads -- and
    from readings computed here out of the series.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "nke.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)

    def rebuilt(self, edit) -> dict:
        changed = copy.deepcopy(self.source)
        edit(changed)
        return build_payload(changed)

    def test_section_one_settles_what_the_previous_report_left(self) -> None:
        check_section_one(self, self.source, self.payload)

    def test_the_closure_is_this_report_s_section_0(self) -> None:
        """Seven questions, judged as section 0 wrote them. Section 0 has no tally
        row, so the note records the grouping rule next to the counts."""
        closure = self.source["followup_closure"]
        note = self.source["_checks"]["note"]["followup_closure"]
        counts = {label: sum(1 for item in closure["items"] if item["verdict"] == label)
                  for label in closure["labels"]}
        self.assertEqual(counts, note["counts"])
        self.assertEqual(len(closure["items"]), note["total"])
        table = next(t for t in self.payload["tables"] if "待验证问题" in t["title"])
        self.assertEqual([row[2] for row in table["rows"]], [item["verdict"] for item in closure["items"]])
        self.assertTrue(all(row[3] for row in table["rows"]))

    def test_the_prior_thresholds_are_the_previous_report_s_own(self) -> None:
        prior = self.source["prior_kpi_settlement"]
        note = self.source["_checks"]["note"]
        self.assertEqual(
            [(e["id"], e["item"], e["threshold"], e["direction"], e["gate"], e["unit"]) for e in prior["quantified"]],
            [(t["id"], t["item"], t["threshold"], t["direction"], t["gate"], t["unit"])
             for t in note["prior_thresholds"]])
        self.assertEqual(len(prior["not_quantified"]), note["prior_not_quantified"]["count"])
        for entry in prior["quantified"]:
            # Nothing the page could go stale on is stored beside a threshold.
            self.assertNotIn("actual", entry, entry["id"])
            self.assertNotIn("current", entry, entry["id"])
            self.assertTrue("reads" in entry or "settles" in entry, entry["id"])
        table = next(t for t in self.payload["tables"] if t["title"].startswith("上季（") and "阈值" in t["title"])
        self.assertEqual(len(table["rows"]), len(prior["quantified"]) + len(prior["not_quantified"]))

    def test_the_call_guidance_is_the_previous_call_s_own(self) -> None:
        guide = stamped_block(self.source, "prior_call_guidance", self.source["periods"][-1])
        if guide is None:
            return
        numeric = [(item["reads"], item["low"], item["high"]) for item in guide["items"] if "low" in item]
        self.assertEqual(numeric, [(g["reads"], g["low"], g["high"])
                                   for g in self.source["_checks"]["note"]["prior_call_guidance"]["numeric"]])

    def test_a_basis_that_flips_a_verdict_is_named_and_only_then(self) -> None:
        """The report did not say which basis its lines are on; the page settles on
        one and must say so when the other would have given a different answer.
        Both states are built here, so this does not depend on the quarter."""
        now = readings(self.source)
        candidates = [e for e in due_entries(self.source) if e.get("alt_reads") in READING_PATHS]
        if not candidates:
            return
        entry = candidates[0]
        main_good = (now[entry["reads"]] >= entry["threshold"] if entry["direction"] == "up"
                     else now[entry["reads"]] <= entry["threshold"])
        opposite = entry["threshold"] + (-1 if main_good == (entry["direction"] == "up") else 1)

        def aligned(s: dict) -> None:
            """Every alternative reading set equal to its main one: no line can flip."""
            for other in candidates:
                block, name = READING_PATHS[other["alt_reads"]]
                s[block][name][-1] = now[other["reads"]]

        def flipped_one(s: dict) -> None:
            aligned(s)
            block, name = READING_PATHS[entry["alt_reads"]]
            s[block][name][-1] = opposite

        def overview_note(payload: dict) -> str:
            return next(s for s in payload["sections"] if s["id"] == "settled")["exhibits"][1]["note"]

        flipped = overview_note(self.rebuilt(flipped_one))
        self.assertEqual(flipped.count("口径会翻转这一条"), 1)
        self.assertIn(entry["metric"] + "按报表口径", flipped)
        self.assertNotIn("口径会翻转", overview_note(self.rebuilt(aligned)))

    def test_section_one_refuses_a_roll_that_skips_the_settlement(self) -> None:
        for key in ("followup_closure", "prior_kpi_settlement"):
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, key):
                    self.rebuilt(lambda s, key=key: s.pop(key))
                with self.assertRaisesRegex(ValueError, "stamped"):
                    self.rebuilt(lambda s, key=key: s[key].__setitem__("period", "Q1 1999"))
                with self.assertRaisesRegex(ValueError, "settles what"):
                    self.rebuilt(lambda s, key=key: s[key].__setitem__("set_in", "Q1 1999"))
        with self.assertRaisesRegex(ValueError, "stores a reading"):
            self.rebuilt(lambda s: s["prior_kpi_settlement"]["quantified"][0].__setitem__("actual", 1.0))

    def test_no_story_placeholder_survives_into_the_page(self) -> None:
        """`fill_story` only matches lower-case names without digits; a name it
        cannot match passes through as literal braces. So the page is scanned."""
        blob = json.dumps(self.payload, ensure_ascii=False)
        self.assertIsNone(re.search(r"\{[a-z][a-z0-9_:]*\}", blob))


class NkeChecksTest(unittest.TestCase):
    """The page's quarter against `_checks`, keyed separately from the release.

    Same contract as the other migrated pages: the builder never reads
    `_checks` (asserted in `test_data_only_roll`), a roll re-keys it from the
    new release, and nothing in this class changes with the quarter.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "nke.json").read_text(encoding="utf-8"))
        cls.checks = cls.source["_checks"]
        cls.payload = build_payload(cls.source)
        cls.fin = cls.source["financials"]
        cls.history = cls.source["long_history"]

    def test_the_page_names_the_checked_quarter_both_ways(self) -> None:
        self.assertIn(self.checks["period"], self.payload["title"])
        self.assertIn(f"本页 {self.checks['period']} 即公司所称 {self.checks['fiscal_label']}",
                      self.payload["subtitle"])
        self.assertIn(f"三个月截至 {self.checks['period_end']}", self.payload["subtitle"])
        self.assertIn(self.checks["fiscal_label"].replace(" ", ""), self.source["fiscal_labels"][-1])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        checks, fin = self.checks, self.fin
        self.assertEqual(fin["revenue_usd_m"][-1], checks["revenue_usd_m"])
        self.assertEqual(fin["diluted_eps_usd"][-1], checks["diluted_eps_usd"])
        self.assertAlmostEqual((fin["gross_margin_pct"][-1] - fin["gross_margin_pct"][-5]) * 100,
                               checks["gross_margin_yoy_bp"], delta=5)
        self.assertEqual(self.source["segments_usd_m"]["north_america_ebit"][-1],
                         checks["north_america_ebit_usd_m"])
        growth = self.source["growth_pct"]
        self.assertEqual(growth["north_america_currency_neutral"][-1],
                         checks["north_america_revenue_cn_pct"])
        self.assertEqual(growth["greater_china_currency_neutral"][-1],
                         checks["greater_china_revenue_cn_pct"])
        at = self.history["fiscal_years"].index(checks["fiscal_year"])
        self.assertEqual(self.history["revenue_usd_m"][at], checks["fiscal_year_revenue_usd_m"])
        self.assertEqual(round(self.history["gross_margin_pct"][at], 1),
                         checks["fiscal_year_gross_margin_pct"])
        self.assertEqual(round(self.history["ebit_margin_pct"][at], 1),
                         checks["fiscal_year_ebit_margin_pct"])
        refund = self.history["ieepa_refund_usd_m"][at] or 0
        self.assertEqual(refund, checks.get("ieepa_refund_usd_m", 0))

    def test_the_head_prints_the_checked_figures(self) -> None:
        checks = self.checks
        self.assertIn(f"报表毛利率 {checks['gross_margin_pct']:.1f}%", self.payload["headline"])
        settled = next(s for s in self.payload["sections"] if s["id"] == "settled")["exhibits"]
        for prefix, key in (("北美收入同比（固定汇率）：", "north_america_revenue_cn_pct"),
                            ("大中华区收入同比（固定汇率）：", "greater_china_revenue_cn_pct")):
            chart = next(e for e in settled if e["title"].startswith(prefix))
            self.assertEqual(chart["series"][0]["values"][-1], checks[key], prefix)
            self.assertIn(f"本季 {checks[key]:+.0f}%".replace("-", "−"), chart["note"], prefix)


if __name__ == "__main__":
    unittest.main()
