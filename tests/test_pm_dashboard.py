"""PM page: the reconciliations that license what the page publishes.

This page's first section settles FOUR guidance records rather than one -- the
full year on the reported basis and on the adjusted basis, and the next quarter
on whichever basis applied at the time. Most of these tests exist because the
four records are only worth putting beside each other if each leg is read on
its own basis: a pro-forma guidance scored against a group actual, or a fiscal
fourth quarter's EPS derived by subtraction, would produce a plausible number
and a wrong finding.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import pm  # noqa: E402
from build.all import ENTRIES, build_all, roster_payload  # noqa: E402
from build.board import headroom  # noqa: E402


def js_payload(path: Path, marker: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{marker} = ", 1)[1].rstrip().rstrip(";")
    return json.loads(body)


class PmDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(pm.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = pm.build_payload(cls.staging)

    # ── the eight-quarter window ────────────────────────────────────────────
    def test_the_window_is_eight_quarters_and_complete(self) -> None:
        fin = self.staging["financials"]
        self.assertEqual(len(self.staging["periods"]), 8)
        for name, values in fin.items():
            self.assertEqual(len(values), 8, name)
            self.assertTrue(all(v is not None for v in values), name)

    def test_quarters_are_contiguous_calendar_labels(self) -> None:
        periods = self.staging["periods"]
        for earlier, later in zip(periods, periods[1:]):
            y1, q1 = int(earlier[:4]), int(earlier[5])
            y2, q2 = int(later[:4]), int(later[5])
            self.assertEqual((y2, q2), (y1 + 1, 1) if q1 == 4 else (y1, q1 + 1))

    def test_the_window_is_the_tail_of_the_long_series(self) -> None:
        """The two windows must not disagree about an overlapping quarter."""
        long = self.staging["long"]
        self.assertEqual(long["periods"][-8:], self.staging["periods"])
        for offset, quarter in enumerate(self.staging["periods"]):
            index = long["periods"].index(quarter)
            self.assertAlmostEqual(long["net_revenues_usd_m"][index],
                                   self.staging["financials"]["net_revenues_usd_m"][offset],
                                   places=3, msg=quarter)

    def test_margins_are_the_ratio_of_the_two_filed_lines(self) -> None:
        fin = self.staging["financials"]
        for index, period in enumerate(self.staging["periods"]):
            revenue = fin["net_revenues_usd_m"][index]
            self.assertAlmostEqual(fin["gross_profit_usd_m"][index] / revenue * 100,
                                   fin["gross_margin_pct"][index], places=2, msg=period)
            self.assertAlmostEqual(fin["operating_income_usd_m"][index] / revenue * 100,
                                   fin["operating_margin_pct"][index], places=2, msg=period)

    # ── the fiscal fourth quarter, which has no 10-Q ────────────────────────
    def test_the_four_quarters_of_a_year_sum_to_the_filed_year(self) -> None:
        """Q4 here is the filed year minus the filed nine months, so this is the
        identity that has to hold for the derivation to be worth publishing."""
        long = self.staging["long"]
        by_period = dict(zip(long["periods"], long["net_revenues_usd_m"]))
        income = dict(zip(long["periods"], long["operating_income_usd_m"]))
        # Filed annual totals, read from companyfacts at build time.
        for year, revenue, operating in ((2024, 37878.0, 13402.0), (2025, 40648.0, 14892.0)):
            quarters = [f"{year}Q{q}" for q in (1, 2, 3, 4)]
            self.assertAlmostEqual(sum(by_period[q] for q in quarters), revenue,
                                   delta=0.01, msg=str(year))
            self.assertAlmostEqual(sum(income[q] for q in quarters), operating,
                                   delta=0.01, msg=str(year))

    def test_a_fourth_quarter_eps_is_not_a_subtraction(self) -> None:
        """EPS is not additive, so a Q4 derived by subtraction would be wrong in
        a way no other identity on this page would notice. Q4 2024's reported
        EPS is negative and its adjusted EPS positive -- a subtraction cannot
        produce that pair."""
        periods = self.staging["periods"]
        fin = self.staging["financials"]
        index = periods.index("2024Q4")
        self.assertLess(fin["reported_diluted_eps_usd"][index], 0)
        self.assertGreater(fin["adjusted_diluted_eps_usd"][index], 1.0)

    # ── the annual guidance record ──────────────────────────────────────────
    def test_every_annual_vintage_belongs_to_the_year_it_was_filed_in(self) -> None:
        """PMI's February release reports the year just finished and guides the
        one that has started, so reading the year out of the text picks up the
        comparative and files four vintages under the wrong year."""
        for record in self.staging["annual_guidance"]["records"]:
            for vintage in record["vintages"]:
                self.assertEqual(int(vintage["release_date"][:4]), record["year"],
                                 vintage["release_date"])

    def test_the_annual_record_starts_at_2009_not_2008(self) -> None:
        """FY2008's forecast was published on a pro-forma ADJUSTED basis against
        a pro-forma 2007 base, so scoring it against reported EPS is a basis
        error rather than a miss."""
        years = [r["year"] for r in self.staging["annual_guidance"]["records"]]
        self.assertEqual(min(years), 2009)
        notes = " ".join(self.payload["notes"])
        self.assertIn("FY2008 不在记录内", notes)

    def test_the_floor_years_are_out_of_the_band_chart_and_in_the_table(self) -> None:
        """A floor has no upper bound; drawing it as a zero-width range would
        invent a ceiling the company never published."""
        banded, floors = pm.annual_records(self.staging)
        self.assertEqual([r["year"] for r in floors], [2019])
        band = self.payload["sections"][0]["exhibits"][0]
        self.assertNotIn("FY2019", band["xlabels"])
        self.assertEqual(band["break_label"], "2019 年只给下限，不在本图")
        table = next(t for t in self.payload["tables"] if "只给下限" in t["title"])
        self.assertIn("FY2019", [row[0] for row in table["rows"]])
        self.assertTrue(any(row[2].startswith("至少") for row in table["rows"]))

    def test_the_reported_annual_record_is_two_sided(self) -> None:
        """This is the page's headline and the only two-sided delivery record on
        the site, so it is pinned rather than left to a recount."""
        banded, _ = pm.annual_records(self.staging)
        rows = [(r["actual_reported_eps"], r["last_guided"]["low"], r["last_guided"]["high"])
                for r in banded]
        self.assertEqual(pm.tally(rows), (16, 7, 4, 5))

    def test_the_adjusted_annual_record_is_the_same_years_read_differently(self) -> None:
        hist = self.staging["annual_guidance"]
        actuals = hist["annual_adjusted_eps_actual"]
        rows = []
        for record in hist["records"]:
            vintages = [v for v in record["vintages"] if v.get("adj_low") is not None]
            if not vintages:
                continue
            last = vintages[-1]
            rows.append((actuals.get(str(record["year"])), last["adj_low"], last["adj_high"]))
        self.assertEqual(pm.tally(rows), (6, 4, 1, 1))

    def test_the_worst_reported_year_is_the_one_the_exclusion_clause_explains(self) -> None:
        """FY2024: reported EPS US$4.52 against a final guidance of
        US$6.20-6.26, and the adjusted line for the same year cleared its
        range. If those two ever stop disagreeing the page's argument is gone."""
        record = next(r for r in self.staging["annual_guidance"]["records"]
                      if r["year"] == 2024)
        self.assertEqual(record["actual_reported_eps"], 4.52)
        self.assertLess(record["actual_reported_eps"], record["last_guided"]["low"])
        adjusted = [v for v in record["vintages"] if v.get("adj_low") is not None][-1]
        actual = self.staging["annual_guidance"]["annual_adjusted_eps_actual"]["2024"]
        self.assertGreater(actual, adjusted["adj_high"])

    def test_the_2020_withdrawal_is_recorded_rather_than_smoothed(self) -> None:
        record = next(r for r in self.staging["annual_guidance"]["records"]
                      if r["year"] == 2020)
        self.assertEqual(record["withdrawn"], ["2020-04-21"])
        self.assertIn("撤回", " ".join(self.payload["notes"]))

    # ── the quarterly guidance record ───────────────────────────────────────
    def test_no_quarter_is_scored_across_a_basis_change(self) -> None:
        """A pro-forma guidance scored against the group actual printed beside
        it in the same release is the plausible-and-wrong version of this
        chart."""
        for row in self.staging["quarterly_guidance"]:
            self.assertIn(row["basis"], {"reported", "adjusted", "pro_forma_adjusted"})
        pro_forma = [r for r in self.staging["quarterly_guidance"]
                     if r["basis"] == "pro_forma_adjusted"]
        self.assertEqual([r["guided_period"] for r in pro_forma], ["2022Q2", "2022Q3"])
        for row in pro_forma:
            # The group adjusted EPS for those quarters was 1.32 and 1.53; the
            # pro-forma figures the guidance was set on are 1.32 and 1.33.
            self.assertIn(row["actual_eps"], (1.32, 1.33))

    def test_the_two_point_guidances_are_marked_as_points(self) -> None:
        points = [r for r in self.staging["quarterly_guidance"] if r["point"]]
        self.assertEqual([r["guided_period"] for r in points], ["2020Q4", "2021Q1"])
        for row in points:
            self.assertEqual(row["low"], row["high"])

    def test_the_fourth_quarter_is_never_guided_except_once(self) -> None:
        """A record that silently skips every Q4 measures its own filter, so the
        gap is asserted here and stated on the chart."""
        guided = {r["guided_period"] for r in self.staging["quarterly_guidance"]}
        fourth = {p for p in guided if p.endswith("Q4")}
        self.assertEqual(fourth, {"2020Q4"})
        for year in range(2021, 2026):
            self.assertNotIn(f"{year}Q4", guided)
        band = next(ex for section in self.payload["sections"]
                    for ex in section["exhibits"] if ex.get("ref") == "EX_Q_BAND")
        self.assertIn("从不指引第四季", band["note"])

    def test_the_adjusted_quarters_have_never_landed_inside_the_range(self) -> None:
        rows = [(r["actual_eps"], r["low"], r["high"])
                for r in self.staging["quarterly_guidance"] if r["basis"] != "reported"]
        finished, above, inside, below = pm.tally(rows)
        self.assertEqual((finished, above, inside, below), (12, 12, 0, 0))

    def test_the_only_quarterly_miss_is_on_the_reported_basis(self) -> None:
        misses = [r for r in self.staging["quarterly_guidance"]
                  if r["actual_eps"] is not None and r["actual_eps"] < r["low"]]
        self.assertEqual([r["guided_period"] for r in misses], ["2021Q2"])
        self.assertEqual(misses[0]["basis"], "reported")

    def test_the_guidance_timing_is_stated_rather_than_assumed(self) -> None:
        """PMI publishes each quarter's outlook with the previous quarter's
        results, so the range is already under way when it is guided. The window
        is recomputed here from the release dates rather than read back out of
        the caption, so a caption that drifts from the record goes red."""
        import datetime

        starts = {"1": "-01-01", "2": "-04-01", "3": "-07-01", "4": "-10-01"}
        days = []
        for row in self.staging["quarterly_guidance"]:
            period = row["guided_period"]
            start = datetime.date.fromisoformat(period[:4] + starts[period[-1]])
            released = datetime.date.fromisoformat(row["release_date"])
            days.append((released - start).days)
        self.assertGreater(min(days), 0, "a guidance published before its quarter began")
        band = next(ex for section in self.payload["sections"]
                    for ex in section["exhibits"] if ex.get("ref") == "EX_Q_BAND")
        self.assertIn(f"开始后 {min(days)}–{max(days)} 天", band["note"])

    # ── the currency decomposition ──────────────────────────────────────────
    def test_the_currency_chart_skips_the_year_whose_two_rows_were_two_bases(self) -> None:
        """FY2022's dollar row was the group and its ex-currency row the pro
        forma, so subtracting one from the other compares two companies."""
        chart = next(ex for section in self.payload["sections"]
                     for ex in section["exhibits"] if ex.get("ref") == "EX_FX")
        self.assertNotIn("FY2022", chart["xlabels"])
        self.assertIn("FY2022 不在图上", chart["note"])

    def test_the_2026_ex_currency_band_has_not_moved(self) -> None:
        """The page leads on this; it is three filed rows, not a claim."""
        record = next(r for r in self.staging["annual_guidance"]["records"]
                      if r["year"] == 2026)
        bands = [(v["xfx_low"], v["xfx_high"]) for v in record["vintages"]
                 if v.get("xfx_low") is not None]
        self.assertEqual(len(bands), 3)
        self.assertEqual(len(set(bands)), 1)

    # ── the quarter's own arithmetic ────────────────────────────────────────
    def test_the_revenue_bridge_walks_from_base_to_end(self) -> None:
        bridge = self.staging["revenue_bridge"]
        for period in bridge["periods"]:
            block = bridge[period]
            for index, column in enumerate(bridge["columns"]):
                walk = (block["base"][index] + block["price"][index]
                        + block["volume_mix_other"][index] + block["acq_div"][index]
                        + block["currency"][index])
                self.assertAlmostEqual(walk, block["end"][index], delta=1.0,
                                       msg=f"{period} {column}")

    def test_the_bridge_ends_where_the_filed_quarter_does(self) -> None:
        bridge = self.staging["revenue_bridge"]
        fin = self.staging["financials"]
        for period in bridge["periods"]:
            index = self.staging["periods"].index(period)
            self.assertAlmostEqual(bridge[period]["end"][0],
                                   fin["net_revenues_usd_m"][index], delta=1.0, msg=period)

    def test_the_three_segments_sum_to_the_filed_quarter(self) -> None:
        seg = self.staging["segments"]
        long = self.staging["long"]
        revenue = dict(zip(long["periods"], long["net_revenues_usd_m"]))
        profit = dict(zip(long["periods"], long["gross_profit_usd_m"]))
        for index, period in enumerate(seg["periods"]):
            self.assertAlmostEqual(
                sum(seg["net_revenues_usd_m"][key][index] for key in pm.SEG_KEYS),
                revenue[period], delta=1.0, msg=period)
            self.assertAlmostEqual(
                sum(seg["gross_profit_usd_m"][key][index] for key in pm.SEG_KEYS),
                profit[period], delta=1.0, msg=period)

    def test_the_segment_series_is_four_quarters_and_says_why(self) -> None:
        """PMI reorganised its reportable segments in 2026Q1 and did not restate
        the history into a filing, so this series cannot be extended backwards
        and must not be spliced onto the six geographic segments it replaced."""
        seg = self.staging["segments"]
        self.assertEqual(seg["periods"], ["2025Q1", "2025Q2", "2026Q1", "2026Q2"])
        chart = next(ex for section in self.payload["sections"]
                     for ex in section["exhibits"] if ex.get("ref") == "EX_SEG_REV")
        self.assertIn("不会再多", chart["note"])

    def test_the_us_gross_margin_fell_year_over_year(self) -> None:
        """The page's second section leads on this pair."""
        us = self.staging["segments"]["adjusted_gross_margin_pct"]["us"]
        self.assertLess(us[2], us[0])      # Q1 2026 below Q1 2025
        self.assertLess(us[3], us[1])      # Q2 2026 below Q2 2025

    def test_the_missing_offtake_reading_is_a_hole_not_a_zero(self) -> None:
        """The company described the latest quarter in words; filling a zero
        would turn a phrase into a number a model could use."""
        zyn = self.staging["zyn"]
        self.assertIsNone(zyn["offtake_yoy_pct"][-1])
        self.assertTrue(zyn["offtake_latest_words"])
        chart = next(ex for section in self.payload["sections"]
                     for ex in section["exhibits"] if ex.get("ref") == "EX_ZYN")
        self.assertIn(zyn["offtake_latest_words"], chart["note"])

    # ── the smoke-free transition ───────────────────────────────────────────
    def test_the_product_categories_sum_to_filed_net_revenues_every_year(self) -> None:
        annual = self.staging["annual"]
        for index, year in enumerate(annual["years"]):
            total = annual["combustible_usd_m"][index] + annual["smoke_free_usd_m"][index]
            self.assertAlmostEqual(total, annual["net_revenues_usd_m"][index],
                                   delta=1.0, msg=str(year))

    def test_the_smoke_free_share_is_the_ratio_of_two_filed_lines(self) -> None:
        annual = self.staging["annual"]
        for index, year in enumerate(annual["years"]):
            share = (annual["smoke_free_usd_m"][index]
                     / annual["net_revenues_usd_m"][index] * 100)
            self.assertAlmostEqual(share, annual["smoke_free_share_pct"][index],
                                   places=3, msg=str(year))

    def test_the_transition_is_additive_not_substitutional(self) -> None:
        """The page says combustible revenue barely moved while smoke-free grew;
        if that ever stops being true the caption has to change."""
        annual = self.staging["annual"]
        combustible = annual["combustible_usd_m"]
        smoke_free = annual["smoke_free_usd_m"]
        self.assertLess(abs(combustible[-1] / combustible[0] - 1), 0.15)
        self.assertGreater(smoke_free[-1] / smoke_free[0], 20)

    def test_the_excise_tax_story_is_a_label_trap_not_a_basis_change(self) -> None:
        """The reason this series used to stop at 2017Q1 was not true.

        The old note said PMI reported revenue including excise taxes "before
        2016" and switched afterwards, citing 2015's US$73.9B against 2016's
        US$26.7B. Those are two different measures of two different years:
        73.9B is 2015 gross, 26.7B is 2016 net. PMI's income statement carries
        both lines in both years -- 2015 net is 73,908 - 47,114 = 26,794, right
        next to 2016's 26,685.

        What is real is a *labelling* trap: in the 2016/2017 filings the line
        captioned "Net revenues" is tagged us-gaap:SalesRevenueNet and is gross
        of excise. Reading the tag by its caption is what produces the phantom
        cliff. This test pins the arithmetic that settles it, so the claim
        cannot come back as prose.
        """
        long = self.staging["long"]
        self.assertEqual(long["periods"][0], "2016Q1")
        self.assertEqual(sum(long["net_revenues_usd_m"][:4]), 26685.0)
        # The gross and net FY2015 figures are both filed; the difference
        # between them is the excise tax, not a change of basis.
        gross_2015, excise_2015 = 73908.0, 47114.0
        self.assertAlmostEqual(gross_2015 - excise_2015, 26794.0, places=6)
        self.assertLess(abs(26794.0 - sum(long["net_revenues_usd_m"][:4])), 1000.0,
                        "2015 net and 2016 net are the same order of magnitude; "
                        "the cliff only appears if you compare gross to net")
        # A year-sum check alone cannot see a compensating swap between two
        # quarters, so the four quarters are pinned against a second, genuinely
        # independent reading: the earnings-release Schedule 1, whose fourth
        # quarter is printed as a standalone column rather than derived by
        # subtraction the way the R-file route derives it.
        route_b = long["route_b_2016"]
        self.assertEqual(route_b["quarters"], ["2016Q1", "2016Q2", "2016Q3", "2016Q4"])
        self.assertEqual(long["net_revenues_usd_m"][:4], route_b["net_revenues_usd_m"])
        self.assertEqual(long["gross_profit_usd_m"][:4], route_b["gross_profit_usd_m"])
        self.assertEqual(len(route_b["accessions"]), 4)
        # ...and the margin each quarter carries is that quarter's own ratio.
        for index in range(4):
            self.assertAlmostEqual(
                long["gross_profit_usd_m"][index] / long["net_revenues_usd_m"][index] * 100,
                long["gross_margin_pct"][index], places=2,
                msg=long["periods"][index])
        chart = next(ex for section in self.payload["sections"]
                     for ex in section["exhibits"] if ex.get("ref") == "EX_REV")
        self.assertIn("那句话是错的", chart["note"])

    def test_the_2016_operating_margin_is_a_hole_and_says_why(self) -> None:
        """Read, then deliberately not published -- and the two are different.

        All four 2016 operating-income figures exist and were read twice, by two
        independent routes that agree to the cent and sum to the filed FY2016.
        They are still not on the chart, because PMI adopted ASU 2017-07
        retrospectively on 2018-01-01 and restated 2017 by quarter but never
        restated 2016 by quarter -- so the 2016Q4/2017Q1 seam would carry a step
        that is purely an accounting-standard change. Revenue and gross profit
        are unaffected and do run the whole window, which is what makes the four
        holes specific rather than a blanket "no 2016 data".
        """
        long = self.staging["long"]
        margin = long["operating_margin_pct"]
        income = long["operating_income_usd_m"]
        self.assertEqual(margin[:4], [None] * 4)
        self.assertEqual(income[:4], [None] * 4)
        self.assertTrue(all(value is not None for value in margin[4:]))
        # ...while the two series that the restatement did not touch are whole.
        for key in ("net_revenues_usd_m", "gross_profit_usd_m", "gross_margin_pct"):
            self.assertTrue(all(value is not None for value in long[key]), key)
        self.assertIn("ASU 2017-07", long["operating_income_hole_2016"])
        chart = next(ex for section in self.payload["sections"]
                     for ex in section["exhibits"] if ex.get("ref") == "EX_MARGIN")
        gross_line = next(series for series in chart["series"]
                          if series["name"] == "毛利率")
        margin_line = next(series for series in chart["series"]
                           if "经营利润率" in series["name"])
        self.assertEqual(len(gross_line["values"]), len(chart["xlabels"]))
        self.assertEqual(len(margin_line["values"]), len(chart["xlabels"]))
        reported = sum(1 for value in margin_line["values"] if value is not None)
        self.assertEqual(len(chart["xlabels"]) - reported, 4)

    # ── thresholds, exhibits, publication ───────────────────────────────────
    def test_every_quantified_threshold_has_a_headroom_bar(self) -> None:
        kpi = self.staging["next_kpi"]["quantified"]
        bar = self.payload["sections"][2]["exhibits"][0]
        self.assertEqual(bar["xlabels"], [entry["metric"] for entry in kpi])
        for entry, value in zip(kpi, bar["values"]):
            self.assertAlmostEqual(
                headroom(entry["direction"], entry["threshold"], entry["current"]),
                value, places=1, msg=entry["metric"])

    def test_what_the_page_refuses_to_plot_is_named(self) -> None:
        excluded = self.staging["next_kpi"]["excluded"]
        for term in ["零售价值份额", "调整后 EBITDA", "自由现金流"]:
            self.assertIn(term, excluded)

    def test_no_market_expectation_is_published(self) -> None:
        self.assertNotIn("market_expectation", self.staging)
        text = json.dumps(self.payload, ensure_ascii=False)
        self.assertNotIn("市场预期", text)
        self.assertNotIn("一致预期", text.replace("本页不发布市场一致预期", ""))

    def test_exhibits_are_numbered_in_render_order_and_refs_resolve(self) -> None:
        numbers = [ex["n"] for section in self.payload["sections"]
                   for ex in section["exhibits"]]
        self.assertEqual(numbers, list(range(2, 2 + len(numbers))))
        text = json.dumps(self.payload, ensure_ascii=False)
        self.assertNotRegex(text, r"\{EX_[A-Z_]+\}")

    def test_tables_are_numbered_after_the_exhibits(self) -> None:
        last = max(ex["n"] for section in self.payload["sections"]
                   for ex in section["exhibits"])
        self.assertEqual([table["n"] for table in self.payload["tables"]],
                         list(range(last + 1, last + 1 + len(self.payload["tables"]))))

    def test_every_exhibit_carries_a_note_and_a_source_line(self) -> None:
        for section in self.payload["sections"]:
            for exhibit in section["exhibits"]:
                self.assertTrue(exhibit.get("note"), exhibit["title"])
                self.assertTrue(exhibit.get("src_extra"), exhibit["title"])

    def test_literal_text_fields_carry_no_markup(self) -> None:
        """`page.js` escapes or textContents these, so a tag would print raw."""
        for key in ("headline", "title", "subtitle", "tracker"):
            self.assertNotIn("<", self.payload[key], key)
        for section in self.payload["sections"]:
            self.assertNotIn("<", section["title"], section["id"])
            self.assertNotIn("<", section["description"], section["id"])
        for note in self.payload["notes"]:
            self.assertNotIn("<", note, note[:40])
        for table in self.payload["tables"]:
            self.assertNotIn("<", table["title"], table["title"][:40])
        self.assertNotIn("<", self.payload["guidance"]["note"])

    def test_table_dicts_carry_only_the_keys_the_renderer_reads(self) -> None:
        """`tableHTML(title, headers, rows, cls)` is all of it; a `note` is dropped."""
        for table in self.payload["tables"]:
            self.assertEqual(set(table), {"n", "title", "headers", "rows"},
                             table["title"][:40])

    def test_the_guidance_block_has_the_shape_the_renderer_reads(self) -> None:
        guidance = self.payload["guidance"]
        self.assertEqual(set(guidance), {"title", "headers", "rows", "note"})
        for row in guidance["rows"]:
            self.assertEqual(len(row), len(guidance["headers"]))

    def test_no_per_share_series_is_plotted_below_the_guidance_section(self) -> None:
        """PMI's EPS is only comparable inside one adjustment basis, which the
        guidance charts handle explicitly. A per-share line drawn anywhere else
        would splice reported and adjusted quarters into one series."""
        for section in self.payload["sections"][1:]:
            for exhibit in section["exhibits"]:
                self.assertNotIn("每股", exhibit["title"], exhibit["title"])

    def test_the_published_payload_matches_a_fresh_build(self) -> None:
        published = js_payload(ROOT / "data" / "pm.js", "window.DASH")
        self.assertEqual(published, self.payload)

    def test_the_page_declares_the_calendar_convention_in_its_subtitle(self) -> None:
        self.assertIn("自然年财年", self.payload["subtitle"])

    def test_the_notes_say_what_the_two_bases_are(self) -> None:
        notes = " ".join(self.payload["notes"])
        self.assertIn("排除条款", notes)
        self.assertIn("下季指引的口径在记录中期发生变化", notes)

    def test_sources_are_official_http_links(self) -> None:
        allowed_hosts = {"www.sec.gov", "www.pmi.com"}
        for source in self.payload["source_links"]:
            parsed = source["url"]
            self.assertTrue(parsed.startswith("https://"), parsed)
            host = parsed.split("/")[2]
            self.assertIn(host, allowed_hosts)

    def test_the_roster_carries_pm_with_the_payload_s_own_labels(self) -> None:
        payloads = build_all()
        roster = roster_payload(payloads)
        entry = next(item for item in roster["items"] if item["slug"] == "pm")
        self.assertEqual(entry["latest_label"], self.payload["latest"]["disclosed_period_label"])
        self.assertEqual(entry["release_date"], self.payload["latest"]["release_date"])
        self.assertEqual(entry["group"], self.payload["company"]["group"])
        self.assertIn(entry["group"], {group["key"] for group in roster["groups"]})

    def test_the_entry_group_exists_and_sits_where_its_order_says(self) -> None:
        from build.all import GROUPS
        keys = [group["key"] for group in GROUPS]
        self.assertIn(self.payload["company"]["group"], keys)
        orders = [group["order"] for group in GROUPS]
        self.assertEqual(orders, sorted(orders))
        entry = next(e for e in ENTRIES if e["slug"] == "pm")
        self.assertEqual(entry["group"], self.payload["company"]["group"])

    def test_the_shell_links_the_payload_by_content_hash(self) -> None:
        import hashlib

        shell = (ROOT / "pm" / "index.html").read_text(encoding="utf-8")
        sources = re.findall(r'<script src="\.\./([^"?]+)(\?v=([0-9a-f]+))?"', shell)
        self.assertEqual([name for name, _, _ in sources],
                         ["data/roster.js", "data/pm.js",
                          "assets/charts.js", "assets/page.js"])
        for name, _, digest in sources:
            expected = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()[:8]
            self.assertEqual(digest, expected, name)

    def test_public_files_exclude_private_and_broker_material(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [ROOT / "series" / "pm.json", ROOT / "data" / "pm.js",
                         ROOT / "pm" / "index.html"]).lower()
        for forbidden in ["/users/", "/library/cloudstorage/", "onedrive",
                          "seeking alpha", "alphastreet", "factset", "bloomberg",
                          "yahoo finance", "nielsen 估计的具体门店"]:
            self.assertNotIn(forbidden, text)
        compact = "".join(text.split())
        self.assertNotIn(":nan", compact)
        self.assertNotIn(":infinity", compact)
        self.assertNotIn(":-infinity", compact)


if __name__ == "__main__":
    unittest.main()
