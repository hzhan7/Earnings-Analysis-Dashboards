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

import hashlib
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.all import ENTRIES, GROUPS  # noqa: E402
from build.board import headroom  # noqa: E402
from build.nke import build_payload, compact_period, fiscal_to_calendar  # noqa: E402


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
        self.assertEqual(self.source["periods"][-1], "Q2 2026")
        self.assertEqual(self.source["fiscal_labels"][-1], "FY2026Q4")
        self.assertEqual(self.source["period_ends"][-1], "2026-05-31")

    def test_the_long_quarterly_record_is_forty_quarters(self) -> None:
        long_q = self.source["long_quarters"]
        self.assertEqual(len(long_q["periods"]), 40)
        self.assertEqual(long_q["fiscal_labels"][0], "FY2017Q1")
        self.assertEqual(long_q["fiscal_labels"][-1], "FY2026Q4")
        for key, values in long_q.items():
            if isinstance(values, list):
                self.assertEqual(len(values), 40, key)

    def test_the_channel_record_starts_at_asc_606_and_is_not_padded(self) -> None:
        """The revenue-disaggregation note begins with ASC 606 in FY2019.  The
        FY2018 10-K has no such report at all and the FY2019 Q3 10-Q's
        prior-year column carries blank member rows, so the earlier quarters
        cannot be recovered even from comparatives.  Starting the series there
        is the honest answer; padding it backwards would invent the split."""
        channel = self.source["channel_quarters"]
        self.assertEqual(channel["fiscal_labels"][0], "FY2019Q1")
        self.assertEqual(len(channel["fiscal_labels"]), 32)
        self.assertEqual(channel["periods"][0], "Q3 2018")

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
        self.assertEqual(history["fiscal_years"][-1], 2026)
        self.assertAlmostEqual(history["nike_direct_share_pct"][0], 20.3, delta=0.05)
        self.assertAlmostEqual(max(history["nike_direct_share_pct"]), 43.7, delta=0.05)
        self.assertAlmostEqual(history["nike_direct_share_pct"][-1], 39.2, delta=0.05)

    # ── the one-off items ────────────────────────────────────────────────────
    def test_the_tariff_refund_is_isolated_to_one_quarter(self) -> None:
        one_off = self.source["one_off_usd_m"]
        refund = one_off["ieepa_tariff_refund_benefit"]
        self.assertEqual(refund[:-1], [None] * 7,
                         "the refund is a single quarter's event, not a series of zeros")
        self.assertEqual(refund[-1], 986.0)
        self.assertEqual(one_off["ieepa_refund_north_america"] + one_off["ieepa_refund_converse"],
                         986.0)
        self.assertEqual(one_off["ieepa_cash_received_by_period_end"]
                         + one_off["ieepa_receivable_at_period_end"], 986.0)

    def test_gross_margin_ex_refund_is_the_refund_removed_and_nothing_else(self) -> None:
        fin, one_off = self.fin, self.source["one_off_usd_m"]
        for index in range(len(fin["revenue_usd_m"])):
            refund = one_off["ieepa_tariff_refund_benefit"][index] or 0
            expected = ((fin["gross_profit_usd_m"][index] - refund)
                        / fin["revenue_usd_m"][index] * 100)
            self.assertAlmostEqual(expected, fin["gross_margin_ex_tariff_refund_pct"][index],
                                   places=3, msg=self.source["periods"][index])
        self.assertAlmostEqual(fin["gross_margin_pct"][-1], 49.15, delta=0.02)
        self.assertAlmostEqual(fin["gross_margin_ex_tariff_refund_pct"][-1], 40.17, delta=0.02)
        # The company's own release says the quarter's gross margin carried an
        # "approximately 900 basis point benefit"; the subtraction gives 8.99pp.
        self.assertAlmostEqual(
            fin["gross_margin_pct"][-1] - fin["gross_margin_ex_tariff_refund_pct"][-1],
            9.0, delta=0.05)

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
        sev, one_off = self.source["severance"], self.source["one_off_usd_m"]
        year = sev["total_usd_m"][sev["fiscal_years"].index(2026)]
        self.assertEqual(year, 385.0)
        self.assertEqual(sev["fy2026_nine_months_total_usd_m"], 304.0)
        self.assertEqual(sev["fy2026_q3_quarter_total_usd_m"], 230.0)
        self.assertEqual(one_off["severance_q4_total"], year - sev["fy2026_nine_months_total_usd_m"])
        self.assertEqual(one_off["severance_q4_total"], 81)
        self.assertEqual(one_off["severance_q4_cost_of_sales"],
                         sev["cost_of_sales_usd_m"][-1] - sev["fy2026_nine_months_cost_of_sales_usd_m"])
        self.assertEqual(one_off["severance_q4_operating_overhead"],
                         sev["operating_overhead_usd_m"][-1] - sev["fy2026_nine_months_overhead_usd_m"])
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
    def test_headroom_bars_match_the_thresholds_they_claim_to_plot(self) -> None:
        for key, exhibits, value_key in (
            ("prior_kpi_settlement", self.by_section["settled"], "actual"),
            ("next_kpi", self.by_section["next_quarter"], "current"),
        ):
            entries = self.source[key]
            exhibit = next(ex for ex in exhibits if ex["kind"] == "diverging_bars"
                           and ex["xlabels"] == [e["metric"] for e in entries])
            expected = [round(headroom(e["direction"], e["threshold"], e[value_key]), 1)
                        for e in entries]
            self.assertEqual(exhibit["values"], expected, key)

    def test_every_prior_threshold_lands_between_its_two_gates(self) -> None:
        """The finding of the first section, asserted rather than described.

        Each metric contributes a bull gate and a bear gate, so a quarter that
        fires nothing shows up as one negative bar and one positive bar per
        metric.  If a later quarter breaks that pattern the page's own headline
        stops being true, and this is what says so.
        """
        entries = self.source["prior_kpi_settlement"]
        self.assertEqual(len(entries), 4)
        signs = [headroom(e["direction"], e["threshold"], e["actual"]) > 0 for e in entries]
        self.assertEqual(signs, [False, True, False, True])

    def test_the_target_headroom_chart_plots_the_last_vintage_only(self) -> None:
        latest = next(v for v in self.targets["vintages"] if v["key"] == "fy2025")
        exhibit = next(ex for ex in self.by_section["settled"]
                       if ex["kind"] == "diverging_bars"
                       and ex["xlabels"] == [g["metric"] for g in latest["goals"]])
        self.assertEqual(len(exhibit["values"]), 6)
        self.assertTrue(all(value < 0 for value in exhibit["values"]),
                        "six goals, six shortfalls -- no bar should be positive")

    def test_sections_and_exhibit_numbering(self) -> None:
        self.assertEqual([s["id"] for s in self.payload["sections"]],
                         ["settled", "quarter_highlights", "next_quarter", "routine"])
        self.assertEqual([ex["n"] for ex in self.exhibits],
                         list(range(1, len(self.exhibits) + 1)))
        self.assertEqual(len(self.exhibits), 24)
        for exhibit in self.exhibits:
            self.assertNotIn("ref", exhibit, exhibit["n"])
            for field in ("title", "note", "src_extra"):
                self.assertNotIn("{EX_", exhibit.get(field) or "", exhibit["n"])

    def test_no_series_is_named_for_a_metric_the_company_does_not_disclose(self) -> None:
        """NIKE reports no revenue for Sportswear, Jordan or Football, and no
        gross margin or inventory by geography.  Management describes them in
        words on the call, and turning a word into a number needs a
        self-selected ratio -- an assumption, not arithmetic.

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
        for banned in ("Sportswear", "Jordan", "Football", "自由现金流"):
            self.assertNotIn(banned, blob, banned)
        notes = " ".join(self.payload["notes"])
        for promised in ("Sportswear", "自由现金流", "按地域拆的毛利率"):
            self.assertIn(promised, notes, promised)

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
        self.assertEqual(listed, [entry["slug"] for entry in ENTRIES])

    def test_compact_period_and_fiscal_mapping_round_trip(self) -> None:
        self.assertEqual(compact_period("Q2 2026"), "Q2'26")
        self.assertEqual(fiscal_to_calendar("FY2026Q4"), "Q2 2026")
        self.assertEqual(fiscal_to_calendar("FY2026Q1"), "Q3 2025")
        self.assertEqual(fiscal_to_calendar("FY2018Q3"), "Q1 2018")


if __name__ == "__main__":
    unittest.main()
