"""Reconciliation and shape tests for the TJX page.

Same purpose as the other companies': nothing derived reaches the page until it
has been checked against a statement identity or a figure the company disclosed
separately.  TJX gives two identities that close exactly, which is what licenses
the eight-quarter series to be published without a single estimate in it:

    net sales − cost of sales − SG&A + net interest income = income before taxes
    Σ segment profit − general corporate expense + net interest income = income before taxes

Both hold to the dollar in all eight quarters, including the two fiscal fourths
that have no 10-Q behind them, because TJX prints a thirteen-week column in its
Q4 release rather than leaving the quarter to be differenced out of the year.

The guidance record needs its own guards, and they are the point of this file.
It runs 52 guided quarters across a stock split, a seven-quarter withdrawal and
two quarters whose adjusting item did not exist when the range was set, and the
tempting mistake in every one of those places is to make the record look
cleaner than it is.  So the counts are pinned by value, the withdrawal is pinned
as a gap rather than a run of misses, the split conversion is pinned on the one
pair that straddles it, and the publication lag -- the fact that the outlook
goes out *after* the quarter has begun -- is pinned as a number rather than left
to the prose.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.all import ENTRIES, GROUPS, build_all, roster_payload  # noqa: E402
from build.board import headroom  # noqa: E402
from build.tjx import build_payload, compact_period  # noqa: E402


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


class TjxDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "tjx.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]
        cls.by_section = {
            section["id"]: section["exhibits"] for section in cls.payload["sections"]
        }
        cls.record = cls.source["quarterly_guidance_history"]
        cls.fin = cls.source["financials"]
        cls.seg = cls.source["segments_usd_m"]

    # ── shape ────────────────────────────────────────────────────────────────
    def test_the_comp_series_declares_its_e_commerce_boundary(self) -> None:
        """One seam the filings footnote and the page did not.

        TJX began including e-commerce in comparable sales with the quarter ended
        2025-05-03 and has never restated the earlier quarters, so the line joins
        two populations. Nothing here is provably wrong -- e-commerce is about 2%
        of sales, the company calls the consolidated impact immaterial, and comps
        print as whole integers, so no cell can be shown to differ. That is
        exactly why it needs saying rather than fixing: an unprovable seam is one
        no arithmetic check will ever raise.

        A refutation pass killed the other half of the original report: the 2019
        Sierra footnote change is NOT a second seam, because TJX printed all four
        FY2019 quarters under both footnote regimes and all twenty division cells
        are identical. Only this one survived.
        """
        drawn = " ".join(
            ex.get("src_extra", "") for section in self.payload["sections"]
            for ex in section["exhibits"])
        self.assertIn("2025-05-03", drawn,
                      "the e-commerce boundary is not stated anywhere a reader sees")
        self.assertIn("电商", drawn)

    def test_the_window_is_forty_two_quarters_and_says_where_it_is_thin(self) -> None:
        """Every block is on one axis; six series are thin and are named.

        The six carried for the reviewed eight quarters only are listed in
        `short_series_notes`, each with its reason. Comparable sales is thin in
        a different way and for a stated reason too: twelve of the forty-two
        quarters have no consolidated comp at all -- one release printed none,
        seven published only an "open-only" comp against stores that were
        actually open, and the 2022 releases gave U.S. comps only.
        """
        periods = self.source["periods"]
        self.assertEqual(len(periods), 42)
        self.assertEqual(periods[0], "Q1 2016")
        self.assertEqual(periods[-1], "Q2 2026")
        thin = set(self.source["short_series_notes"])
        for group in ("financials", "segments_usd_m", "segment_margins_pct",
                      "comparable_sales_pct", "operations"):
            for key, values in self.source[group].items():
                if key.startswith("_") or not isinstance(values, list):
                    continue
                self.assertEqual(len(values), 42, f"{group}.{key}")
                reported = sum(1 for value in values if value is not None)
                if key in thin:
                    # Thin means "only within the reviewed eight"; some of these
                    # are sparser still, because the company gives an adjusted
                    # figure only in quarters that have an adjusting item.
                    self.assertLessEqual(reported, 8, f"{group}.{key}")
                    self.assertEqual(
                        [i for i, v in enumerate(values) if v is not None],
                        [i for i in range(len(values) - 8, len(values))
                         if values[i] is not None],
                        f"{group}.{key}: values must sit inside the last eight")
                elif group == "comparable_sales_pct":
                    self.assertGreaterEqual(reported, 30, f"{group}.{key}")
                elif key in ("other_charges_usd_m", "adjusted_pretax_margin_pct"):
                    continue
                elif key == "net_sales_yoy_pct":
                    self.assertEqual(reported, 38, "no year-ago base for 2016")
                else:
                    self.assertEqual(reported, 42, f"{group}.{key}")

    def test_calendar_labels_map_onto_the_fiscal_ones(self) -> None:
        """TJX's FY(N) Qk is this page's Qk (N-1); a slip here silently

        compares different three-month periods against the other pages."""
        for period, fiscal in zip(self.source["periods"], self.source["fiscal_labels"]):
            quarter, year = period.split()
            fiscal_year, fiscal_quarter = re.match(r"FY(\d{4})Q(\d)", fiscal).groups()
            self.assertEqual(quarter, f"Q{fiscal_quarter}")
            self.assertEqual(int(year), int(fiscal_year) - 1)

    # ── statement identities ─────────────────────────────────────────────────
    def test_income_statement_closes_to_the_dollar(self) -> None:
        """Sales - cost - SG&A - other charges + net interest = pretax income.

        The "other charges" term is the one the eight-quarter window never
        needed: six of the forty-two quarters carry a named line between SG&A
        and pretax (impairment, litigation, restructuring), and without it the
        identity misses by the whole charge -- 82.9 in Q3 2016, 312.2 in Q4 2020.
        """
        fin = self.fin
        for index, period in enumerate(self.source["periods"]):
            derived = (fin["net_sales_usd_m"][index]
                       - fin["cost_of_sales_usd_m"][index]
                       - fin["sga_usd_m"][index]
                       - (fin["other_charges_usd_m"][index] or 0.0)
                       + fin["interest_income_net_usd_m"][index])
            # assertEqual on floats: this passed on eight quarters and started
            # failing at 824.9689999999998 != 824.969 the moment the record grew.
            # The identity is exact in the filing; binary addition of
            # three-decimal dollars is not, so the tolerance is a hundredth of a
            # million -- far tighter than any real misread.
            self.assertAlmostEqual(derived, fin["pretax_income_usd_m"][index],
                                   delta=0.01, msg=period)

    def test_segment_bridge_closes_to_the_dollar(self) -> None:
        """Σ segment profit − corporate expense + net interest = pretax income.

        This is the bridge the page warns is unreadable *quarter to quarter*,
        because general corporate expense swings by US$60-70M. That warning is
        about comparability across quarters, not about the arithmetic: within a
        single quarter it closes exactly, and if it ever stopped closing the
        corporate-expense line would be the first thing to have been misread.
        """
        seg, fin = self.seg, self.fin
        for index, period in enumerate(self.source["periods"]):
            total = sum(seg[f"{name}_profit"][index] for name in
                        ("marmaxx", "homegoods", "canada", "international"))
            self.assertAlmostEqual(total, seg["total_segment_profit"][index],
                                   delta=0.01, msg=period)
            # ...and the "other charges" term sits below total segment profit in
            # five of the six quarters that have one -- but not in Q4 2017,
            # where the impairment was booked *inside* Marmaxx and is therefore
            # already in the segment total. A fixed formula misses that quarter
            # by 99.25, which is 8.9% of its pretax income and would look like a
            # data error rather than a presentation one.
            charge = fin["other_charges_usd_m"][index] or 0.0
            if period in self.source["other_charges_note"]["inside_a_segment"]:
                charge = 0.0
            derived = (total - seg["general_corporate_expense"][index] - charge
                       + fin["interest_income_net_usd_m"][index])
            self.assertAlmostEqual(derived, fin["pretax_income_usd_m"][index],
                                   delta=0.01, msg=period)

    def test_segment_sales_sum_to_consolidated_net_sales(self) -> None:
        seg, fin = self.seg, self.fin
        for index, period in enumerate(self.source["periods"]):
            total = sum(seg[f"{name}_sales"][index] for name in
                        ("marmaxx", "homegoods", "canada", "international"))
            self.assertAlmostEqual(total, fin["net_sales_usd_m"][index],
                                   delta=0.01, msg=period)

    def test_half_year_sales_match_the_two_quarters_the_company_printed(self) -> None:
        """The H1 figures are used for the corporate-expense argument, so they

        have to be the same H1 the company printed, not a re-add of the pieces."""
        half = self.source["half_year_usd_m"]
        self.assertEqual(half["net_sales"][1],
                         self.fin["net_sales_usd_m"][-2] + self.fin["net_sales_usd_m"][-1])
        self.assertEqual(half["net_sales"][0],
                         self.fin["net_sales_usd_m"][-6] + self.fin["net_sales_usd_m"][-5])
        self.assertEqual(half["general_corporate_expense"][1],
                         self.seg["general_corporate_expense"][-2]
                         + self.seg["general_corporate_expense"][-1])

    def test_the_prior_year_corporate_expense_column_agrees_with_our_own_series(self) -> None:
        """Each release prints last year's corporate expense beside this year's.

        Four of those printed comparatives are quarters this page already
        carries, so they are a free check on the extraction: if the two ever
        disagree, one of the eight quarters was read out of the wrong column.
        """
        seg = self.seg
        current, prior = (seg["general_corporate_expense"],
                          seg["general_corporate_expense_prior_year"])
        reported = [i for i, value in enumerate(prior) if value is not None]
        self.assertEqual(len(reported), 8)
        self.assertEqual(reported[-1], len(prior) - 1)
        for index in reported[4:]:
            self.assertAlmostEqual(prior[index], current[index - 4], delta=0.01,
                                   msg=self.source["periods"][index])

    def test_the_corporate_expense_chart_carries_a_yoy_line(self) -> None:
        """`gs_bar` draws a twelve-period moving average unless a `yoy` block is

        supplied, and twelve periods do not exist in an eight-quarter series --
        it renders as NaN and the browser drops the line. Every other page here
        passes `yoy`; this pins that this one does too.
        """
        chart = next(ex for ex in self.by_section["quarter_highlights"]
                     if ex["kind"] == "gs_bar")
        self.assertIn("yoy", chart)
        values = chart["yoy"]["values"]
        self.assertEqual(len(values), len(chart["xlabels"]))
        reported = [value for value in values if value is not None]
        self.assertEqual(len(reported), 8,
                         "the line needs both this year's and last year's "
                         "corporate expense, and the prior-year column is only "
                         "carried for the reviewed eight quarters")
        self.assertEqual(
            [index for index, value in enumerate(values) if value is not None],
            list(range(len(values) - 8, len(values))),
            "and they are the last eight, not a scattered set")
        for value in reported:
            self.assertIsInstance(value, float)
        self.assertAlmostEqual(values[-1], (242 / 182 - 1) * 100, places=3)

    def test_derived_ratios_match_their_own_inputs(self) -> None:
        fin, ops = self.fin, self.source["operations"]
        for index, period in enumerate(self.source["periods"]):
            sales = fin["net_sales_usd_m"][index]
            self.assertAlmostEqual(
                fin["gross_margin_pct"][index],
                (sales - fin["cost_of_sales_usd_m"][index]) / sales * 100, places=3, msg=period)
            self.assertAlmostEqual(
                fin["pretax_margin_pct"][index],
                fin["pretax_income_usd_m"][index] / sales * 100, places=3, msg=period)
            if ops["merchandise_inventories_usd_m"][index] is None:
                self.assertIsNone(ops["inventory_per_store_usd_k"][index], period)
                continue
            self.assertAlmostEqual(
                ops["inventory_per_store_usd_k"][index],
                ops["merchandise_inventories_usd_m"][index] * 1000
                / ops["store_count"][index], places=1, msg=period)

    def test_the_quarter_the_page_leads_with(self) -> None:
        """Pinned by value: the headline is written off these and nothing else."""
        fin = self.fin
        self.assertEqual(fin["net_sales_usd_m"][-1], 15180)
        self.assertEqual(fin["diluted_eps_usd"][-1], 1.36)
        self.assertEqual(fin["adjusted_diluted_eps_usd"][-1], 1.22)
        self.assertEqual(fin["adjusted_pretax_margin_pct"][-1], 11.9)
        self.assertEqual(fin["adjusted_gross_margin_pct"][-1], 31.4)
        self.assertEqual(self.source["comparable_sales_pct"]["consolidated"][-1], 4)
        self.assertEqual(self.source["comparable_sales_pct"]["marmaxx"][-1], 1)
        self.assertEqual(self.source["operations"]["store_count"][-1], 5285)
        self.assertAlmostEqual(fin["pretax_margin_pct"][-1], 13.2938, places=3)

    def test_the_adjusted_segment_margins_are_the_companys_own_arithmetic(self) -> None:
        """reported + disclosed tariff impact = disclosed adjusted, per segment."""
        adj = self.source["adjusted_segment_margins_pct"]
        for name in ("marmaxx", "homegoods", "canada", "international"):
            block = adj[name]
            self.assertAlmostEqual(
                block["reported"] + block["tariff_refund_pp"], block["adjusted"],
                places=6, msg=name)
        # …and the reported half agrees with the filed dollars it comes from.
        segm = self.source["segment_margins_pct"]
        for name in ("marmaxx", "homegoods", "canada", "international"):
            self.assertAlmostEqual(segm[f"{name}_margin_pct"][-1],
                                   adj[name]["reported"], places=1, msg=name)

    # ── the guidance record ──────────────────────────────────────────────────
    def test_the_record_is_the_length_the_page_claims(self) -> None:
        record = self.record
        self.assertEqual(len(record["quarters"]), 52)
        finished = [v for v in record["actual_eps_usd"] if v is not None]
        self.assertEqual(len(finished), 49)
        for key in ("guide_eps_lo_usd", "guide_eps_hi_usd", "actual_eps_usd",
                    "guide_pretax_margin_lo_pct", "actual_pretax_margin_pct",
                    "guide_comp_lo_pct", "actual_comp_pct", "guidance_published",
                    "fiscal_labels"):
            self.assertEqual(len(record[key]), 52, key)

    def test_eps_hit_rate_is_pinned_by_value(self) -> None:
        """38 above / 8 inside / 3 below. The whole page turns on this split, so

        it is asserted rather than recomputed into the prose and forgotten."""
        record = self.record
        lo, hi = record["guide_eps_lo_usd"], record["guide_eps_hi_usd"]
        actual = record["actual_eps_usd"]
        finished = [i for i, v in enumerate(actual) if v is not None]
        above = [i for i in finished if actual[i] > hi[i]]
        below = [i for i in finished if actual[i] < lo[i]]
        self.assertEqual((len(above), len(finished) - len(above) - len(below), len(below)),
                         (38, 8, 3))
        # The three breaches, named on the chart, are these three quarters.
        self.assertEqual([record["quarters"][i] for i in below],
                         ["Q1 2014", "Q1 2020", "Q1 2022"])

    def test_pretax_margin_and_comp_hit_rates_are_pinned_by_value(self) -> None:
        record = self.record
        lo, hi = record["guide_pretax_margin_lo_pct"], record["guide_pretax_margin_hi_pct"]
        actual = record["actual_pretax_margin_pct"]
        finished = [i for i, v in enumerate(actual) if v is not None and lo[i] is not None]
        above = [i for i in finished if actual[i] > hi[i]]
        below = [i for i in finished if actual[i] < lo[i]]
        self.assertEqual((len(above), len(finished) - len(above) - len(below), len(below)),
                         (15, 0, 1))
        self.assertEqual([record["quarters"][i] for i in below], ["Q4 2022"])

        clo, chi = record["guide_comp_lo_pct"], record["guide_comp_hi_pct"]
        cactual = record["actual_comp_pct"]
        cfinished = [i for i, v in enumerate(cactual) if v is not None and clo[i] is not None]
        cabove = [i for i in cfinished if cactual[i] > chi[i]]
        cbelow = [i for i in cfinished if cactual[i] < clo[i]]
        self.assertEqual((len(cabove), len(cfinished) - len(cabove) - len(cbelow), len(cbelow)),
                         (10, 4, 0))

    def test_the_withdrawal_is_a_gap_and_not_a_run_of_misses(self) -> None:
        """Seven quarters have no guidance at all, and the axis has to show it.

        Counting "never missed" over a record that quietly drops the quarters a
        company refused to guide is the failure this test exists to prevent.
        """
        record = self.record
        self.assertEqual(len(record["guidance_gap_quarters"]), 7)
        for quarter in record["guidance_gap_quarters"]:
            self.assertNotIn(quarter, record["quarters"])
        ordinals = [int(y) * 4 + int(q[1]) for q, y in
                    (period.split() for period in record["quarters"])]
        jumps = [i for i in range(1, len(ordinals)) if ordinals[i] - ordinals[i - 1] > 1]
        self.assertEqual(len(jumps), 1, "the record has exactly one discontinuity")
        self.assertEqual(ordinals[jumps[0]] - ordinals[jumps[0] - 1] - 1, 7)
        self.assertEqual(record["quarters"][jumps[0] - 1], "Q1 2020")
        self.assertEqual(record["quarters"][jumps[0]], "Q1 2022")
        deviation = self.by_section["settled"][5]
        self.assertEqual(deviation["break_at"], jumps[0])

    def test_the_split_conversion_is_pinned_on_the_pair_that_straddles_it(self) -> None:
        """Guidance for Q3 2018 was published before the 2018-11-06 two-for-one

        and the quarter was reported after it. Converted, US$1.18-1.20 becomes
        US$0.59-0.60 against a reported US$0.61 -- above the range, as the
        unconverted comparison would never have shown.
        """
        record = self.record
        index = record["quarters"].index("Q3 2018")
        self.assertAlmostEqual(record["guide_eps_lo_usd"][index], 0.59, places=6)
        self.assertAlmostEqual(record["guide_eps_hi_usd"][index], 0.60, places=6)
        self.assertEqual(record["actual_eps_usd"][index], 0.61)
        self.assertEqual(record["split_adjusted_before"], "Q3 2018")
        # Every pre-split guidance endpoint is a clean half-cent multiple, which
        # is what a division by two of a cent-quoted range leaves behind.
        for value in record["guide_eps_lo_usd"][:index]:
            self.assertAlmostEqual(value * 200, round(value * 200), places=6)

    def test_the_publication_lag_is_carried_as_a_number(self) -> None:
        """The outlook goes out with the previous quarter's results, so it lands

        inside the quarter it guides. Without this the hit rates read as a
        forecasting record rather than a partly-banked one.
        """
        lag = self.record["publication_lag_days"]
        self.assertEqual((lag["min"], lag["max"]), (9, 24))
        self.assertGreater(lag["mean"], 15)
        settled = self.by_section["settled"]
        for exhibit in settled[4:]:
            haystack = exhibit.get("note", "") + exhibit.get("title", "")
            self.assertTrue("9–24" in haystack or "开始后" in haystack,
                            f"{exhibit['n']} does not carry the timing caveat")

    def test_adjusted_basis_is_used_only_where_the_company_judged_on_it(self) -> None:
        """Q4 2025 (litigation settlement) and Q2 2026 (tariff refunds) are

        scored on the company's adjusted figures, because neither event existed
        when the range was set. Everywhere else the reported figure is used.
        """
        record = self.record
        for quarter, eps, margin in (("Q4 2025", 1.43, 12.2), ("Q2 2026", 1.22, 11.9)):
            index = record["quarters"].index(quarter)
            self.assertEqual(record["actual_eps_usd"][index], eps, quarter)
            self.assertAlmostEqual(record["actual_pretax_margin_pct"][index], margin,
                                   places=6, msg=quarter)
        # …and those two are exactly the quarters the series marks as adjusted.
        adjusted = [self.source["periods"][i] for i, v
                    in enumerate(self.fin["adjusted_diluted_eps_usd"]) if v is not None]
        self.assertEqual(adjusted, ["Q4 2025", "Q2 2026"])

    def test_the_half_and_half_arithmetic_behind_the_slope_chart(self) -> None:
        """H2 implied = full-year guided midpoint − H1 reported, both filed."""
        chart = next(ex for ex in self.by_section["quarter_highlights"]
                     if "上半年" in ex["title"] and "下半年" in ex["title"])
        prior, current = chart["groups"][0]["values"], chart["groups"][1]["values"]
        self.assertAlmostEqual(current[0], 2.41, places=6)
        self.assertAlmostEqual(current[1], (5.15 + 5.20) / 2 - 2.41, places=6)
        self.assertAlmostEqual(prior[1], 4.73 - 2.02, places=6)
        self.assertAlmostEqual((current[0] / prior[0] - 1) * 100, 19.3, places=1)
        self.assertAlmostEqual((current[1] / prior[1] - 1) * 100, 2.0, places=1)

    def test_the_full_year_raise_equals_the_quarter_beat(self) -> None:
        """The page says the raise moved nothing into H2. Both midpoints minus

        their own H1 have to land on the same number for that to be true."""
        old_mid, new_mid = (5.08 + 5.15) / 2, (5.15 + 5.20) / 2
        guided_mid = (1.15 + 1.17) / 2
        beat = 1.22 - guided_mid
        self.assertAlmostEqual(new_mid - old_mid, beat, places=6)
        self.assertAlmostEqual(new_mid - 2.41, old_mid - 1.19 - guided_mid, places=6)

    # ── thresholds ───────────────────────────────────────────────────────────
    def test_threshold_current_values_come_from_the_series(self) -> None:
        ops, half = self.source["operations"], self.source["half_year_usd_m"]
        inventory_yoy = (ops["inventory_per_store_usd_k"][-1]
                         / ops["inventory_per_store_usd_k"][-5] - 1) * 100
        capex_intensity = half["capital_expenditures"][1] / half["net_sales"][1] * 100
        by_metric = {item["metric"]: item for item in self.source["prior_kpi_settlement"]}
        self.assertAlmostEqual(by_metric["每店存货同比 D"]["actual"], inventory_yoy, places=3)
        self.assertAlmostEqual(by_metric["半年资本开支 / 销售额 D"]["actual"],
                               capex_intensity, places=3)
        self.assertEqual(by_metric["合并同店销售"]["actual"],
                         self.source["comparable_sales_pct"]["consolidated"][-1])
        self.assertEqual(by_metric["Marmaxx 同店销售"]["actual"],
                         self.source["comparable_sales_pct"]["marmaxx"][-1])

    def test_the_two_breached_thresholds_are_the_ones_the_page_names(self) -> None:
        breached = [item["metric"] for item in self.source["prior_kpi_settlement"]
                    if headroom(item["direction"], item["threshold"], item["actual"]) < 0]
        self.assertEqual(breached, ["Marmaxx 同店销售", "半年资本开支 / 销售额 D"])
        forward = [item["metric"] for item in self.source["next_kpi"]
                   if headroom(item["direction"], item["threshold"], item["current"]) < 0]
        self.assertEqual(forward, ["Marmaxx 同店销售", "调整后税前利润率 vs 下季指引下限",
                                   "半年资本开支 / 销售额 D"])

    def test_every_threshold_entry_is_renderable(self) -> None:
        for key, value_key in (("prior_kpi_settlement", "actual"), ("next_kpi", "current")):
            for item in self.source[key]:
                self.assertIn(item["direction"], ("up", "down"), item["metric"])
                self.assertNotEqual(item["threshold"], 0, item["metric"])
                self.assertIsInstance(item[value_key], (int, float))

    # ── page wiring ──────────────────────────────────────────────────────────
    def test_exhibit_numbers_run_without_a_gap(self) -> None:
        numbers = [ex["n"] for ex in self.exhibits]
        self.assertEqual(numbers, list(range(1, len(numbers) + 1)))
        table_numbers = [table["n"] for table in self.payload["tables"]]
        self.assertEqual(table_numbers,
                         list(range(numbers[-1] + 1, numbers[-1] + 1 + len(table_numbers))))

    def test_no_exhibit_carries_an_unresolved_reference(self) -> None:
        for exhibit in self.exhibits:
            for field in ("title", "note", "src_extra", "annot"):
                text = exhibit.get(field)
                if isinstance(text, str):
                    self.assertNotIn("{EX_", text, f"exhibit {exhibit['n']} {field}")

    def test_the_page_refuses_to_publish_the_de_tariffed_earnings(self) -> None:
        """The company says "mostly" and never a number, so neither does the

        page. This pins the refusal: turning "mostly" into a figure needs a
        self-chosen ratio, which is an assumption and not arithmetic.
        """
        notes = " ".join(self.payload["notes"])
        self.assertIn("不发布", notes)
        self.assertIn("mostly", notes)
        blob = json.dumps(self.payload, ensure_ascii=False)
        # The local research note puts the de-tariffed figure at roughly
        # US$1.16-1.18 against a reported US$1.22. None of that may be
        # published -- but US$1.17 legitimately appears as the top of the
        # quarter's *guided* range, so the assertion has to name the estimate
        # rather than a bare number that also occurs for an honest reason.
        for invented in ("$1.16", "1.16–1.18", "1.16-1.18", "去关税"):
            self.assertNotIn(invented, blob,
                             "an estimated de-tariffed EPS reached the payload")
        self.assertIn("$1.15–1.17", blob, "the guided range itself is publishable")

    def test_the_cross_page_capex_table_is_carried_and_explained(self) -> None:
        """TJX carries the shared AI-capex block like every other page, and says

        what it is. Carrying the table and being a *column* in it are separate
        things -- Cadence, Synopsys, TSMC and NVIDIA all publish it without
        appearing in `_CASH_CAPEX_SOURCES` either. It renders in the collapsed
        audit drawer rather than the chart flow, which is why it does not owe
        the page's "every chart must earn its place" justification. What it does
        owe the reader is one sentence saying it is a site-wide cross-reference
        and not a claim about an off-price retailer; the first pages outside the
        chain shipped it with no note at all, which is the gap this pins.
        """
        titles = [table["title"] for table in self.payload["tables"]]
        self.assertTrue(any("AI capex" in title for title in titles))
        explained = [note for note in self.payload["notes"] if "AI capex" in note]
        self.assertEqual(len(explained), 1)
        self.assertIn("跨页对照", explained[0])
        blob = json.dumps(self.payload, ensure_ascii=False)
        self.assertNotIn("TJX 不在这条链上的任何一环；每张图", blob)

    def test_published_payload_matches_a_fresh_build(self) -> None:
        self.assertEqual(js_payload(ROOT / "data" / "tjx.js", "window.DASH"), self.payload)

    def test_roster_and_shell(self) -> None:
        roster = js_payload(ROOT / "data" / "roster.js", "window.ROSTER")
        self.assertEqual(roster, roster_payload(build_all()))
        entry = next(item for item in roster["items"] if item["slug"] == "tjx")
        self.assertEqual(entry["latest_label"], self.payload["latest"]["disclosed_period_label"])
        self.assertEqual(entry["release_date"], self.payload["latest"]["release_date"])
        shell = (ROOT / "tjx" / "index.html").read_text(encoding="utf-8")
        self.assertIn("../data/tjx.js", shell)
        self.assertNotIn("../data/tsm.js", shell)

    def test_the_home_page_counts_the_companies_it_renders(self) -> None:
        """The masthead number is hand-written and merges cleanly when two

        people both increment it. Counting is the only thing that survives.

        `test_v_dashboard` already checks the masthead against the rendered card
        count, which catches the two disagreeing. It cannot catch both being
        stale together -- add an ENTRIES row and forget `index.html` entirely and
        that assertion still passes. This one ties both to `len(ENTRIES)`.
        """
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertEqual(home.count('class="hcard"'), len(ENTRIES))
        self.assertIn(f'<span class="meta">{len(ENTRIES)} 家公司', home)
        self.assertIn('href="tjx/"', home)
        for group in GROUPS:
            self.assertIn(group["label"], home, group["key"])

    def test_compact_period(self) -> None:
        self.assertEqual(compact_period("Q2 2026"), "Q2'26")


if __name__ == "__main__":
    unittest.main()
