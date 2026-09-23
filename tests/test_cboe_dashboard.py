"""CBOE page: the identities that license what this page claims.

The page makes one central claim -- that market share and the money move in
opposite directions more often than not -- and that claim is a piece of
arithmetic over company-disclosed values, so most of these tests exist to keep
the arithmetic honest rather than to restate the numbers.

Three things about Cboe's disclosure are easy to get wrong, and each has a test
below because each was actually hit while building this page.

The first is the segment table's SIXTH row. Five named segments do not sum to
the printed total in 16 of 37 quarters, and the residual changes sign partway
through, because the sixth row is "Corporate" (small, positive) until 2022 and
"Digital" (NEGATIVE -- Cboe Digital, bought in 2022 and wound down) after it.
Reading five rows and trusting the total produces a chart that is quietly wrong
in those quarters. The sum identity here is what makes that loud.

The second is that the operating-metrics table is published five quarters at a
time, so consecutive releases overlap by four. Stitching them without checking
the overlap splices two vintages of the same quarter together.

The third is the guidance the page refuses to score. Organic net revenue growth
is guided as a number through 2024 and as a phrase from 2025, and the page
converts neither: the numeric years have no full-year actual to score against
(none in the four February releases or the FY2025 10-K), and a phrase is not a
range. `test_word_guidance_is_never_given_numeric_endpoints` is what keeps a
future edit from quietly turning "mid to high teens" into 15-19%.
"""

from __future__ import annotations

import copy
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import cboe  # noqa: E402
from build.all import ENTRIES, build_all, roster_payload  # noqa: E402
from build.board import cn_count, cn_ordinal, display_period, headroom, stamped_block  # noqa: E402


def js_payload(path: Path, marker: str) -> dict:
    text = path.read_text(encoding="utf-8")
    return json.loads(text.split(f"{marker} = ", 1)[1].rstrip().rstrip(";"))


def plain(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "")


def published_text(payload: dict) -> str:
    return json.dumps({key: payload[key] for key in
                       ("title", "subtitle", "headline", "brief", "sections", "notes", "tables")},
                      ensure_ascii=False)


def contiguous(quarters: list[str]) -> bool:
    for earlier, later in zip(quarters, quarters[1:]):
        y1, q1 = int(earlier[:4]), int(earlier[5])
        y2, q2 = int(later[:4]), int(later[5])
        if (y2, q2) != ((y1 + 1, 1) if q1 == 4 else (y1, q1 + 1)):
            return False
    return True


def readings(staging: dict) -> dict:
    """This quarter's reading of every metric a threshold can name (`reads`),
    computed here from the series -- not through the builder, so a builder that
    read the wrong cell cannot agree with itself."""
    kpi, kpil, long = staging["kpi"], staging["kpi_long"], staging["long"]
    net = staging["net_revenue_window"]["net_revenue"]
    money = [adv * rpc / 1000 for adv, rpc in zip(kpi["multi_listed_adv_k"], kpi["multi_listed_rpc_usd"])]
    adv = kpil["index_options_adv_k"]
    return {
        "net_revenue": net[-1],
        "net_revenue_yoy": (net[-1] / net[-5] - 1) * 100,
        "ml_share": kpi["multi_listed_share_pct"][-1],
        "ml_daily_revenue_qoq": money[-1] / money[-2],
        "adj_opex": long["adj_opex"][-1],
        "index_adv_qoq": adv[-1] / adv[-2],
    }


def due_in(entries: list[dict], period: str) -> list[dict]:
    return [e for e in entries if not e.get("settles") or display_period(e["settles"]) == period]


def check_section_one(test: unittest.TestCase, staging: dict, payload: dict) -> None:
    """Section one against `_checks["note"]`, in whichever state the quarter is.

    The note is keyed from the local analyses: its source names the previous one
    (or none), the section 0 tally of the previous Follow-up Questions, and the
    previous section 8 thresholds. A first analysis settles only the company's
    guidance and says why; any later one opens with the follow-up tally, the
    threshold overview and one history line per metric, and the company's
    guidance record comes after them. Nothing here names a quarter, so a roll
    does not edit this.
    """
    note = staging["_checks"]["note"]
    period = staging["period_labels"][-1]
    settled = next(section for section in payload["sections"] if section["id"] == "settled")
    exhibits = settled["exhibits"]
    test.assertEqual([ex.get("ref") for ex in exhibits[-3:]], ["EX_OPEX", "EX_TAX", "EX_GROWTH"])
    first = note["source"]["previous_quarter"] is None
    record = staging.get("analysis_record", {})
    test.assertEqual(first, display_period(record.get("first_period", "")) == display_period(period))
    if first:
        test.assertTrue(settled["description"].startswith(
            f"本站对该公司的第一份季报分析是 {period}，没有上季留下的跟踪指标可结算；"
            "本节结算的是公司上季给出、本季到期的指引"), settled["description"])
        test.assertEqual(len(exhibits), 3)
        for key in ("followup_closure", "prior_kpi_settlement"):
            test.assertNotIn(key, staging)
        return
    test.assertNotIn("第一份季报分析", settled["description"])
    story = exhibits[:-3]
    closure = note["followup_closure"]
    if closure["total"]:
        chart = story.pop(0)
        test.assertEqual(chart["kind"], "bars_labeled")
        test.assertTrue(chart["title"].startswith(f"上季 {closure['total']} 条待验证问题："), chart["title"])
        test.assertEqual(dict(zip(chart["xlabels"], chart["values"])), closure["counts"])
        test.assertIn(f"{closure['total']} 条待验证问题", settled["description"])
    prior = staging.get("prior_kpi_settlement", {})
    quantified = prior.get("quantified", [])
    test.assertEqual([(e["id"], e["metric"], e["direction"], e["threshold"]) for e in quantified],
                     [(t["id"], t["metric"], t["direction"], t["threshold"])
                      for t in note["prior_thresholds"]])
    test.assertEqual(len(quantified) + len(prior.get("not_carried", [])), note["prior_total"])
    if quantified:
        due = due_in(quantified, period)
        overview = story.pop(0)
        test.assertEqual(overview["kind"], "diverging_bars")
        test.assertTrue(overview["title"].startswith(f"上季 {len(due)} 条量化阈值："), overview["title"])
        test.assertEqual(overview["xlabels"], [e["metric"] for e in due])
        test.assertIn(f"申报读得到的 {len(due)} 条量化阈值", settled["description"])
        unsettled = note["prior_total"] - len(due)
        if unsettled:
            test.assertIn(f"第 8 节另有 {unsettled} 项本季不结", settled["description"])
        test.assertEqual(len(story), len({e["reads"] for e in due}))
        for chart in story:
            test.assertEqual(chart["kind"], "lines")
            test.assertRegex(chart["title"], r"：(守住|击穿)上季阈值 ")
    test.assertTrue(closure["total"] or quantified, "a later quarter settles something")


class CboeDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(cboe.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = cboe.build_payload(cls.staging)

    # ── the four sections ───────────────────────────────────────────────────
    def test_the_page_has_the_site_s_four_sections_in_order(self) -> None:
        """The owner's four-part format (TSM is the reference): ids and titles verbatim."""
        self.assertEqual(
            [(section["id"], section["title"]) for section in self.payload["sections"]],
            [("settled", "一、上季跟踪指标兑现了吗"), ("quarter_highlights", "二、本季重点"),
             ("next_quarter", "三、下季要跟踪什么"), ("routine", "四、长期常规跟踪")])
        for section in self.payload["sections"]:
            self.assertTrue(section["exhibits"], section["id"])
        self.assertTrue(self.payload["notes"][0].startswith(
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列"))

    def test_the_segment_structure_chart_is_routine_not_a_highlight(self) -> None:
        """Five segments plus the sixth row is a long structural record with no
        one-quarter conclusion, so it belongs to the routine section."""
        where = {ex.get("ref"): section["id"] for section in self.payload["sections"]
                 for ex in section["exhibits"]}
        self.assertEqual(where["EX_SEG"], "routine")
        self.assertEqual(where["EX_CATS"], "routine")

    # ── the short window ────────────────────────────────────────────────────
    def test_the_short_window_starts_in_2024q3_and_is_complete(self) -> None:
        """It grows by one quarter a roll; what stays true is where it starts."""
        fin = self.staging["financials"]
        periods = self.staging["periods"]
        self.assertEqual(periods[0], "2024Q3")
        self.assertTrue(contiguous(periods))
        for name, values in fin.items():
            self.assertEqual(len(values), len(periods), name)
            self.assertTrue(all(v is not None for v in values), name)

    def test_quarters_are_contiguous_calendar_labels(self) -> None:
        periods = self.staging["periods"]
        for earlier, later in zip(periods, periods[1:]):
            y1, q1 = int(earlier[:4]), int(earlier[5])
            y2, q2 = int(later[:4]), int(later[5])
            self.assertEqual((y2, q2), (y1 + 1, 1) if q1 == 4 else (y1, q1 + 1))

    def test_every_block_is_contiguous(self) -> None:
        """A hole in the middle of a window would draw as a gap, not as absence."""
        for name, block in self.staging.items():
            if not isinstance(block, dict) or "quarters" not in block:
                continue
            quarters = block["quarters"]
            for earlier, later in zip(quarters, quarters[1:]):
                y1, q1 = int(earlier[:4]), int(earlier[5])
                y2, q2 = int(later[:4]), int(later[5])
                self.assertEqual((y2, q2), (y1 + 1, 1) if q1 == 4 else (y1, q1 + 1),
                                 f"{name}: {earlier} -> {later}")

    def test_the_window_is_the_tail_of_the_long_series(self) -> None:
        long = self.staging["long"]
        self.assertEqual(long["quarters"][-len(self.staging["periods"]):], self.staging["periods"])
        for offset, quarter in enumerate(self.staging["periods"]):
            index = long["quarters"].index(quarter)
            self.assertAlmostEqual(long["adj_opex"][index],
                                   self.staging["financials"]["adj_opex"][offset],
                                   places=3, msg=quarter)

    # ── identities inside a quarter ─────────────────────────────────────────
    def test_net_revenue_is_total_revenue_less_the_four_cost_lines(self) -> None:
        """Cboe's own headline top line, recomputed from its own inputs."""
        nr = self.staging["net_revenue_window"]
        for index, quarter in enumerate(nr["quarters"]):
            derived = (nr["total_revenues"][index]
                       - nr["liquidity_payments"][index]
                       - nr["routing_and_clearing"][index]
                       - nr["regulatory_fees_cost"][index]
                       - nr["royalty_and_other_cost"][index])
            self.assertAlmostEqual(derived, nr["net_revenue"][index],
                                   delta=0.11, msg=quarter)

    def test_cost_of_revenues_equals_the_four_lines(self) -> None:
        nr = self.staging["net_revenue_window"]
        for index, quarter in enumerate(nr["quarters"]):
            parts = (nr["liquidity_payments"][index] + nr["routing_and_clearing"][index]
                     + nr["regulatory_fees_cost"][index] + nr["royalty_and_other_cost"][index])
            self.assertAlmostEqual(parts, nr["cost_of_revenues"][index],
                                   delta=0.11, msg=quarter)

    def test_adjusted_operating_margin_is_the_ratio_it_claims(self) -> None:
        fin = self.staging["financials"]
        for index, quarter in enumerate(self.staging["periods"]):
            ratio = fin["adj_op_income"][index] / fin["net_revenue"][index] * 100
            self.assertAlmostEqual(ratio, fin["adj_op_margin_pct"][index],
                                   delta=0.06, msg=quarter)

    def test_adjusted_operating_income_is_net_revenue_less_adjusted_opex(self) -> None:
        fin = self.staging["financials"]
        for index, quarter in enumerate(self.staging["periods"]):
            self.assertAlmostEqual(fin["net_revenue"][index] - fin["adj_opex"][index],
                                   fin["adj_op_income"][index], delta=0.11, msg=quarter)

    def test_gaap_operating_income_identity(self) -> None:
        fin = self.staging["financials"]
        for index, quarter in enumerate(self.staging["periods"]):
            self.assertAlmostEqual(fin["net_revenue"][index] - fin["opex"][index],
                                   fin["op_income"][index], delta=0.11, msg=quarter)

    def test_adjusted_margin_never_below_gaap_margin(self) -> None:
        """Non-GAAP removes costs, so its margin cannot be the lower one."""
        fin = self.staging["financials"]
        for index, quarter in enumerate(self.staging["periods"]):
            self.assertGreaterEqual(fin["adj_op_margin_pct"][index],
                                    fin["gaap_op_margin_pct"][index], quarter)

    # ── the sixth segment row ───────────────────────────────────────────────
    def test_six_segment_rows_sum_to_the_printed_total(self) -> None:
        """Five rows do not. This is the test that says which quarters have six.

        Taking only the five named segments leaves a residual in 16 of the 37
        quarters, and the residual is positive early (a "Corporate" row) and
        negative later (a "Digital" row, negative because the table is net of
        cost of revenues). Both signs are small enough to look like rounding and
        neither is.
        """
        seg = self.staging["segments"]
        for index, quarter in enumerate(seg["quarters"]):
            parts = sum(seg[key][index] for key in
                        ("options", "north_american_equities", "europe_and_apac",
                         "futures", "global_fx", "corporate_digital"))
            self.assertAlmostEqual(parts, seg["total"][index], delta=0.051, msg=quarter)

    def test_the_sixth_row_is_actually_needed(self) -> None:
        """Guards the test above from being vacuous if the row were zeroed out."""
        seg = self.staging["segments"]
        nonzero = [q for q, v in zip(seg["quarters"], seg["corporate_digital"]) if v]
        self.assertGreaterEqual(len(nonzero), 10, seg["corporate_digital"])
        self.assertTrue(any(v < 0 for v in seg["corporate_digital"]),
                        "the Digital era's negative net revenue has gone missing")
        self.assertTrue(any(v > 0 for v in seg["corporate_digital"]),
                        "the Corporate era's positive residual has gone missing")

    def test_segment_window_starts_after_the_bats_stub_quarter(self) -> None:
        """2017Q1 consolidates Bats for one month against three-month quarters."""
        self.assertEqual(self.staging["segments"]["quarters"][0], "2017Q2")

    def test_segments_agree_with_net_revenue_where_both_exist(self) -> None:
        seg = self.staging["segments"]
        nr = self.staging["net_revenue_window"]
        index = {q: i for i, q in enumerate(nr["quarters"])}
        checked = 0
        for position, quarter in enumerate(seg["quarters"]):
            if quarter not in index:
                continue
            self.assertAlmostEqual(seg["total"][position],
                                   nr["net_revenue"][index[quarter]],
                                   delta=0.11, msg=quarter)
            checked += 1
        self.assertEqual(checked, len(seg["quarters"]))

    def test_categories_sum_to_the_segment_total(self) -> None:
        """The company's second revenue split lands on the same net revenue."""
        cats = self.staging["categories"]
        seg = self.staging["segments"]
        index = {q: i for i, q in enumerate(seg["quarters"])}
        for position, quarter in enumerate(cats["quarters"]):
            parts = (cats["derivatives"][position] + cats["cash_and_spot"][position]
                     + cats["data_vantage"][position])
            self.assertAlmostEqual(parts, seg["total"][index[quarter]],
                                   delta=0.11, msg=quarter)

    # ── the page's central arithmetic ───────────────────────────────────────
    def test_daily_revenue_is_adv_times_rpc(self) -> None:
        div = self.staging["divergence"]
        for index, quarter in enumerate(div["quarters"]):
            self.assertAlmostEqual(div["adv_k"][index] * div["rpc_usd"][index] / 1000.0,
                                   div["daily_revenue_usd_m"][index],
                                   places=6, msg=quarter)

    def test_offexchange_daily_revenue_is_adv_times_net_capture(self) -> None:
        off = self.staging["offexchange"]
        for index, quarter in enumerate(off["quarters"]):
            expected = off["adv_m_shares"][index] * 1e6 / 100.0 \
                * off["net_capture_per_100"][index] / 1000.0
            self.assertAlmostEqual(expected, off["daily_revenue_usd_k"][index],
                                   places=6, msg=quarter)

    def test_the_divergence_count_is_what_the_headline_says(self) -> None:
        """The headline number is recomputed here, not copied from the copy.

        Through 2026Q2 opposite is the majority -- pinned on those quarters,
        which a roll only appends to; the page words its later record from the
        data either way.
        """
        div = self.staging["divergence"]
        steps = cboe.direction_steps(div["share_pct"], div["daily_revenue_usd_m"])
        self.assertEqual(steps["same"] + steps["opposite"], steps["steps"])
        upto = div["quarters"].index("2026Q2") + 1
        history = cboe.direction_steps(div["share_pct"][:upto], div["daily_revenue_usd_m"][:upto])
        self.assertGreater(history["opposite"], history["same"],
                           "the page's whole claim is that opposite is the majority")
        headline = self.payload["headline"]
        self.assertIn(f"{steps['steps']} 次环比", headline)
        self.assertIn(f"{steps['opposite']} 次方向相反", headline)

    def test_share_fell_while_the_money_rose_over_the_window(self) -> None:
        """The single sentence the page is built on, asserted as arithmetic
        through 2026Q2 (a roll only appends to that record)."""
        div = self.staging["divergence"]
        at = div["quarters"].index("2026Q2")
        self.assertLess(div["share_pct"][at], div["share_pct"][0])
        self.assertGreater(div["daily_revenue_usd_m"][at], div["daily_revenue_usd_m"][0])

    def test_divergence_window_starts_where_share_is_first_published(self) -> None:
        kpi = self.staging["kpi"]
        first = next(q for q, v in zip(kpi["quarters"], kpi["multi_listed_share_pct"])
                     if v is not None)
        self.assertEqual(self.staging["divergence"]["quarters"][0], first)

    def test_divergence_inputs_match_the_kpi_table(self) -> None:
        """The block is a cut of the KPI table, not a second reading of it."""
        kpi, div = self.staging["kpi"], self.staging["divergence"]
        index = {q: i for i, q in enumerate(kpi["quarters"])}
        for position, quarter in enumerate(div["quarters"]):
            source = index[quarter]
            self.assertEqual(div["adv_k"][position], kpi["multi_listed_adv_k"][source])
            self.assertEqual(div["rpc_usd"][position], kpi["multi_listed_rpc_usd"][source])
            self.assertEqual(div["share_pct"][position],
                             kpi["multi_listed_share_pct"][source])

    def test_the_long_kpi_series_carries_only_the_rows_that_survive_bats(self) -> None:
        """Index options predate the combined table; almost nothing else does.

        Bats listed no index options, so that row means the same thing on both
        sides of the 2017 acquisition. Every other row would be CBOE standalone
        before 2016 and combined after, which is not one series.
        """
        kpi_long = self.staging["kpi_long"]
        self.assertEqual(kpi_long["quarters"][0], "2011Q4")
        self.assertEqual(set(kpi_long) - {"quarters", "period_labels"},
                         {"index_options_adv_k", "index_options_rpc_usd"})
        self.assertEqual(self.staging["kpi"]["quarters"][0], "2016Q1")

    def test_no_unplotted_series_crosses_the_bats_boundary_undeclared(self) -> None:
        """The trap that removing dead data is meant to close.

        Gross revenue and total operating expenses both step by more than 2x at
        2016Q4 -> 2017Q1 -- Bats consolidated on 2017-02-28 and the presentation
        gained a cost-of-revenues block in the same quarter. Drawn as one line
        that is a false jump, and nothing on the page draws them, so they are
        not published at all. `adj_op_margin_pct` crosses the same boundary and
        IS published, because an exhibit plots it and says so in its note.
        """
        long = self.staging["long"]
        for key in ("total_revenues", "opex", "op_income"):
            self.assertNotIn(key, long, f"{key} splices at the Bats boundary")
        self.assertIn("adj_op_margin_pct", long)
        index = long["quarters"].index("2016Q4")
        step = long["adj_op_margin_pct"][index + 1] - long["adj_op_margin_pct"][index]
        self.assertGreater(abs(step), 5.0,
                           "if this stopped being a visible step, the note explaining it is stale")
        note = next(ex["note"] for section in self.payload["sections"]
                    for ex in section["exhibits"] if ex.get("ref") == "EX_MARGIN")
        self.assertIn("2017", note)

    def test_long_and_short_kpi_windows_agree_on_overlaps(self) -> None:
        kpi, kpi_long = self.staging["kpi"], self.staging["kpi_long"]
        index = {q: i for i, q in enumerate(kpi_long["quarters"])}
        for position, quarter in enumerate(kpi["quarters"]):
            source = index[quarter]
            for key in ("index_options_adv_k", "index_options_rpc_usd"):
                self.assertEqual(kpi[key][position], kpi_long[key][source],
                                 f"{quarter} {key}")

    # ── guidance: what is settled and what is refused ───────────────────────
    def test_settled_guidance_years_have_both_a_range_and_an_actual(self) -> None:
        guide = self.staging["annual_guidance_history"]
        for name in ("adjusted_operating_expenses", "adjusted_effective_tax_rate"):
            metric = guide[name]
            years = cboe.finished_years(metric)
            self.assertGreaterEqual(len(years), 10, name)
            for year in years:
                block = metric["by_year"][str(year)]
                self.assertIsNotNone(block["actual"], f"{name} FY{year}")
                for low, high, release in block["guided"]:
                    self.assertLessEqual(low, high, f"{name} FY{year} {release}")

    def test_the_2017_expense_basis_break_is_declared_on_the_chart(self) -> None:
        """February 2017 guides CBOE standalone; May 2017 guides it with Bats.

        The two are 200 million dollars apart and are not one series. The chart
        has to say so, or the step reads as an expense explosion.
        """
        band = next(ex for section in self.payload["sections"]
                    for ex in section["exhibits"]
                    if ex.get("ref") == "EX_OPEX")
        self.assertIn("break_at", band)
        years = cboe.finished_years(
            self.staging["annual_guidance_history"]["adjusted_operating_expenses"])
        self.assertEqual(years[band["break_at"]], 2017)
        self.assertIn("Bats", band["break_label"])

    def test_fy2017_actual_is_the_combined_basis_figure(self) -> None:
        """386.6 is the as-reported number and would fabricate a huge beat."""
        block = (self.staging["annual_guidance_history"]
                 ["adjusted_operating_expenses"]["by_year"]["2017"])
        self.assertAlmostEqual(block["actual"], 415.3, places=1)
        low, high, _ = block["guided"][-1]
        self.assertGreater(block["actual"], low)

    def test_word_guidance_is_never_given_numeric_endpoints(self) -> None:
        """The rule this site would most plausibly break by accident.

        "mid to high teens" is not 15-19%. A vintage carries either a numeric
        range the company printed, or a phrase -- never a phrase that someone
        has helpfully translated.
        """
        growth = self.staging["revenue_growth_guidance"]["by_year"]
        for year, row in growth.items():
            for name, vintages in row.items():
                for vintage in vintages:
                    has_number = vintage["low"] is not None
                    if not has_number:
                        self.assertIsNone(vintage["high"], f"{year} {name}")
                        continue
                    # A numeric vintage must state its number in the source text,
                    # so a translated phrase cannot masquerade as one.
                    self.assertRegex(
                        vintage["text"], r"\d",
                        f"{year} {name}: numeric endpoints with no number in the source")
                    # Both endpoints must appear verbatim in the sentence the
                    # company printed, so a translated phrase cannot pass as a
                    # numeric vintage by merely containing some other digit.
                    for endpoint in (vintage["low"], vintage["high"]):
                        self.assertRegex(
                            vintage["text"], rf"\b{endpoint:g}\b",
                            f"{year} {name}: endpoint {endpoint:g} is not in the source text")

    def test_the_growth_guidance_has_both_eras(self) -> None:
        """If either era vanished, the "cannot be settled" claim would be wrong."""
        growth = self.staging["revenue_growth_guidance"]["by_year"]
        numeric = [y for y, row in growth.items()
                   if any(v["low"] is not None for v in row.get("total", []))]
        words = [y for y, row in growth.items()
                 if row.get("total") and all(v["low"] is None for v in row["total"])]
        self.assertTrue(numeric, "the numeric era is gone")
        self.assertTrue(words, "the word era is gone")
        self.assertLess(max(numeric), min(words), "the eras are meant to be consecutive")

    def test_no_growth_guidance_year_carries_an_actual(self) -> None:
        """The page says this record cannot be settled; nothing may quietly settle it."""
        exhibit = next(ex for section in self.payload["sections"]
                       for ex in section["exhibits"] if ex.get("ref") == "EX_GROWTH")
        self.assertNotIn("actual", exhibit)
        self.assertEqual(exhibit["kind"], "grouped_bars")

    # ── section one: what the previous local analysis left open ─────────────
    def test_section_one_settles_what_the_previous_analysis_left(self) -> None:
        check_section_one(self, self.staging, self.payload)

    def test_the_closure_quotes_the_report_and_names_every_filing_correction(self) -> None:
        """Verdicts are the report's, word for word; where a filing contradicts the
        report's reasoning the chart says so (Q2 2026: the TMX sale price the report
        called undisclosed, the Cboe Predicts launch date)."""
        closure = self.staging.get("followup_closure")
        if closure is None:
            return
        charts = {ex.get("ref"): ex for section in self.payload["sections"] for ex in section["exhibits"]}
        note = charts["EX_CLOSURE"]["note"]
        table = next(t for t in self.payload["tables"] if "待验证问题" in t["title"])
        self.assertEqual([row[2] for row in table["rows"]], [item["report_verdict"] for item in closure["items"]])
        self.assertEqual([row[3] for row in table["rows"]], [item["verdict"] for item in closure["items"]])
        self.assertEqual([row[1] for row in table["rows"]], [item["question"] for item in closure["items"]])
        for number, item in enumerate(closure["items"], 1):
            if not item.get("filing_note"):
                continue
            self.assertIn(f"第 {number} 条：", note)
            for fragment in re.split(r"\{[a-z_]+\}", item["filing_note"]):
                self.assertIn(fragment, note, item["short"])
        # Placeholders are filled from the series, never left as braces.
        self.assertNotRegex(note, r"\{[a-z_]+\}")
        for row in table["rows"]:
            self.assertNotRegex(row[4], r"\{[a-z_]+\}")

    def test_the_settlement_readings_come_from_the_series(self) -> None:
        """A threshold names what it reads and carries no reading of its own;
        every reading, margin and verdict the page prints is recounted here."""
        prior = self.staging.get("prior_kpi_settlement")
        if prior is None:
            return
        period = self.staging["period_labels"][-1]
        now = readings(self.staging)
        for entry in prior["quantified"]:
            self.assertNotIn("actual", entry)
            self.assertNotIn("current", entry)
        due = due_in(prior["quantified"], period)
        charts = {ex.get("ref"): ex for section in self.payload["sections"] for ex in section["exhibits"]}
        overview = charts["EX_PRIOR_HEADROOM"]
        self.assertEqual(overview["values"],
                         [round(headroom(e["direction"], e["threshold"], now[e["reads"]]), 1) for e in due])
        table = next(t for t in self.payload["tables"]
                     if t["title"].startswith(f"上季（{prior['set_in']}）") and "阈值" in t["title"])
        rows = {row[0]: row for row in table["rows"]}
        long = self.staging["long"]
        year = self.staging["periods"][-1][:4]
        spent = [v for q, v in zip(long["quarters"], long["adj_opex"]) if q.startswith(year)]
        for entry in prior["quantified"]:
            row = rows[entry["metric"]]
            if entry in due:
                margin = headroom(entry["direction"], entry["threshold"], now[entry["reads"]])
                self.assertEqual(row[4], f"{margin:+.1f}%", entry["id"])
            else:
                self.assertEqual(row[-1], f"未到期（{entry['settles']} 结算）")
                if entry["reads"] == "fy_adj_opex":
                    self.assertEqual(row[3], f"年初至今 US${sum(spent):,.1f}M（{cn_count(len(spent))}季）")
        for item in prior.get("not_carried", []):
            self.assertIn(item["metric"], rows)
            self.assertTrue(rows[item["metric"]][-1].startswith("本页不结算："))

    def test_every_threshold_line_recounts_its_own_record(self) -> None:
        """「N 季里落在这条线下方的有 M 季」 is counted from the chart's own series
        and its own threshold line -- the check the old 「从未跌破」 sentence lacked."""
        pattern = re.compile(r"(\d+) (季|年)里落在这条线(下方|上方)的有 (\d+) (季|年)")
        seen = 0
        for section in self.payload["sections"]:
            for ex in section["exhibits"]:
                if ex["kind"] != "lines" or not re.search(r"(上季|下季)阈值", ex["title"]):
                    continue
                actual, line = ex["series"][0]["values"], ex["series"][1]["values"]
                for match in pattern.finditer(ex["note"]):
                    below = match.group(3) == "下方"
                    known = [(v, t) for v, t in zip(actual, line) if v is not None]
                    self.assertEqual(int(match.group(1)), len(known), ex["title"])
                    self.assertEqual(int(match.group(4)),
                                     sum(1 for v, t in known if (v < t if below else v > t)), ex["title"])
                    seen += 1
        self.assertGreater(seen, 0)

    def test_the_share_line_says_what_the_money_did(self) -> None:
        """The report's case against a share threshold (Q2 2026): it held while the
        money fell. Both states are built here, so the sentence follows the data
        rather than the quarter this test was written in."""
        claim = "但它守住的这一季，这门生意的日均收入环比少了"

        def with_share_line(s: dict, share_now: float, money_falls: bool) -> dict:
            period = s["period_labels"][-1]
            year, quarter = int(period[-4:]), int(period[1])
            before = f"Q4 {year - 1}" if quarter == 1 else f"Q{quarter - 1} {year}"
            s.pop("followup_closure", None)
            s["prior_kpi_settlement"] = {
                "period": period, "set_in": before, "not_carried": [],
                "quantified": [{"id": "ml_share", "reads": "ml_share", "metric": "Multi-listed 期权市占",
                                "direction": "up", "threshold": 22.0, "unit": "pct", "basis": "测试"}]}
            kpi, div = s["kpi"], s["divergence"]
            kpi["multi_listed_share_pct"][-1] = div["share_pct"][-1] = share_now
            adv = kpi["multi_listed_adv_k"][-2] * (0.5 if money_falls else 2.0)
            kpi["multi_listed_adv_k"][-1] = div["adv_k"][-1] = adv
            div["daily_revenue_usd_m"][-1] = adv * div["rpc_usd"][-1] / 1000
            return s

        for share_now, falls, expected in ((25.0, True, True), (25.0, False, False), (20.0, True, False)):
            with self.subTest(share=share_now, money_falls=falls):
                payload = cboe.build_payload(with_share_line(copy.deepcopy(self.staging), share_now, falls))
                self.assertEqual(claim in json.dumps(payload, ensure_ascii=False), expected)

    def test_next_thresholds_carry_a_current_value(self) -> None:
        kpi = stamped_block(self.staging, "next_kpi", self.staging["period_labels"][-1])
        for entry in (kpi or {}).get("quantified", []):
            self.assertIn(entry["direction"], ("up", "down"), entry["metric"])
            self.assertIsNotNone(entry["current"], entry["metric"])
            self.assertNotEqual(entry["threshold"], 0, entry["metric"])

    def test_the_rewritten_threshold_is_on_the_money_not_the_share(self) -> None:
        kpi = stamped_block(self.staging, "next_kpi", self.staging["period_labels"][-1])
        if not kpi:
            return
        metrics = [e["metric"] for e in kpi["quantified"]]
        self.assertTrue(any(m.startswith("Multi-listed 日均收入") for m in metrics), metrics)
        self.assertFalse(any("市占" in m for m in metrics),
                         "the page argues share is the wrong thing to track")

    # ── payload shape ───────────────────────────────────────────────────────
    def test_exhibits_are_numbered_in_render_order(self) -> None:
        numbers = [ex["n"] for section in self.payload["sections"]
                   for ex in section["exhibits"]]
        self.assertEqual(numbers, list(range(1, len(numbers) + 1)))

    def test_no_exhibit_caption_has_an_unresolved_reference(self) -> None:
        for section in self.payload["sections"]:
            for exhibit in section["exhibits"]:
                for key in ("title", "note", "src_extra"):
                    self.assertNotRegex(exhibit.get(key) or "", r"\{EX_[A-Z_]+\}",
                                        f"Exhibit {exhibit['n']} {key}")

    def test_raw_html_slots_carry_no_bare_comparison_signs(self) -> None:
        """Exhibit notes are raw innerHTML: a threshold copied as 「Q2 SPX < 4.5M」
        puts a bare `<` in markup, which any tag-stripping reader (and this repo's
        own scans) misreads as a tag running to the next `>`. Write the operator in
        words there; table cells are escaped and may keep the symbol."""
        for section in self.payload["sections"]:
            for exhibit in section["exhibits"]:
                for key in ("title", "note", "src_extra"):
                    self.assertEqual(re.findall(r"<(?![/a-zA-Z])", exhibit.get(key) or ""), [],
                                     f"Exhibit {exhibit['n']} {key}")
        self.assertEqual(re.findall(r"<(?![/a-zA-Z])", self.payload["brief"]), [])

    def test_every_exhibit_carries_a_note_and_a_source(self) -> None:
        for section in self.payload["sections"]:
            for exhibit in section["exhibits"]:
                self.assertTrue(exhibit.get("note"), exhibit["n"])
                self.assertTrue(exhibit.get("src_extra"), exhibit["n"])

    def test_no_series_carries_a_non_finite_value(self) -> None:
        def walk(node):
            if isinstance(node, dict):
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)
            elif isinstance(node, float):
                self.assertEqual(node, node)
                self.assertNotEqual(abs(node), float("inf"))
        walk(self.payload)

    def test_the_cross_page_table_is_published(self) -> None:
        titles = [table["title"] for table in self.payload["tables"]]
        self.assertTrue(any("跨页对照" in title for title in titles), titles)

    def test_the_audit_tables_are_numbered_after_the_exhibits(self) -> None:
        charts = sum(len(section["exhibits"]) for section in self.payload["sections"])
        self.assertEqual([table["n"] for table in self.payload["tables"]],
                         list(range(charts + 1, charts + 1 + len(self.payload["tables"]))))

    def test_every_audit_table_row_matches_its_headers(self) -> None:
        for table in self.payload["tables"]:
            width = len(table["headers"])
            for row in table["rows"]:
                self.assertEqual(len(row), width, table["title"])

    def test_the_company_block_names_the_exchanges_group(self) -> None:
        self.assertEqual(self.payload["company"]["group"], "exchanges")
        entry = next(e for e in ENTRIES if e["slug"] == "cboe")
        self.assertEqual(entry["group"], "exchanges")

    def test_published_payload_roster_and_shell(self) -> None:
        self.assertEqual(js_payload(ROOT / "data" / "cboe.js", "window.DASH"), self.payload)
        roster = js_payload(ROOT / "data" / "roster.js", "window.ROSTER")
        self.assertEqual(roster, roster_payload(build_all()))
        shell = (ROOT / "cboe" / "index.html").read_text(encoding="utf-8")
        self.assertIn("../data/cboe.js", shell)
        self.assertNotIn("../data/ndaq.js", shell)

    def test_shell_versions_every_script_by_content(self) -> None:
        import hashlib

        shell = (ROOT / "cboe" / "index.html").read_text(encoding="utf-8")
        sources = re.findall(r'<script src="\.\./([^"?]+)(\?v=([0-9a-f]+))?"', shell)
        self.assertEqual([name for name, _, _ in sources],
                         ["data/roster.js", "data/cboe.js",
                          "assets/charts.js", "assets/page.js"])
        for name, query, digest in sources:
            with self.subTest(script=name):
                self.assertTrue(query, f"{name} is served without a cache-busting version")
                expected = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()[:len(digest)]
                self.assertEqual(digest, expected, f"{name} carries a stale digest")

    def test_the_page_publishes_no_product_level_volume(self) -> None:
        """SPX and 0DTE volumes are said on the call, not filed in the KPI table.

        The local note's threshold was written on SPX ADV. The page declines it
        and says so; this keeps a later edit from quietly pulling a transcript
        number into a published series.
        """
        blob = json.dumps(self.payload, ensure_ascii=False)
        for series_key in ("spx_adv", "0dte", "spx_options_adv"):
            self.assertNotIn(series_key, blob)
        # What a threshold block cannot read is named, with its reason, where
        # the overview is -- not dropped. (Q2 2026: SPX ADV, call-only.)
        prior = self.staging.get("prior_kpi_settlement") or {}
        overview = next((ex for section in self.payload["sections"] for ex in section["exhibits"]
                         if ex.get("ref") == "EX_PRIOR_HEADROOM"), None)
        for item in prior.get("not_carried", []):
            self.assertIsNotNone(overview)
            self.assertIn(item["metric"], plain(overview["note"]))



class CboeChecksTest(unittest.TestCase):
    """The page's quarter against a record keyed separately from the release.

    `_checks` is typed once per quarter from the earnings release, with the
    place in the document each figure was read from; the builder never reads it
    (asserted in `test_data_only_roll`). Pairs are [this quarter, year-ago];
    triples are [this quarter, last quarter, year-ago], all from this release.
    Rolling a quarter re-keys `_checks`; this class does not change.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(cboe.STAGING_PATH.read_text(encoding="utf-8"))
        cls.checks = cls.staging["_checks"]
        cls.payload = cboe.build_payload(cls.staging)
        cls.period = cls.staging["period_labels"][-1]

    def test_the_page_names_the_checked_quarter(self) -> None:
        checks = self.checks
        self.assertIn(checks["period"], self.payload["title"])
        self.assertIn(f"截至 {checks['period_end']}", self.payload["subtitle"])
        self.assertIn(f"发布 {checks['release_date']}", self.payload["subtitle"])
        quarter, year = checks["period"].split()
        label = f"Cboe {year} 年第{cn_ordinal(int(quarter[1]))}季度业绩新闻稿"
        release = next(x for x in self.staging["sources"] if x["label"].startswith(label))
        self.assertEqual(self.payload["source_url"], release["url"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        """Both columns: the year-ago the page divides by is the one this
        release reprinted, not only the one first printed."""
        nr, fin = self.staging["net_revenue_window"], self.staging["financials"]
        for line, (now, ago) in self.checks["income_statement_usd_m"].items():
            block = nr if line in nr else fin
            with self.subTest(line=line):
                self.assertAlmostEqual(block[line][-1], now, places=6)
                self.assertAlmostEqual(block[line][-5], ago, places=6)
        self.assertEqual(nr["regulatory_fees_revenue"][-1], self.checks["regulatory_fees_revenue_usd_m"][0])
        for group in ("per_share", "adjusted"):
            for line, (now, ago) in self.checks[group].items():
                with self.subTest(line=line):
                    self.assertAlmostEqual(fin[line][-1], now, places=6)
                    self.assertAlmostEqual(fin[line][-5], ago, places=6)
        for block, rows in (("segments", "segments_usd_m"), ("categories", "categories_usd_m")):
            for line, (now, ago) in self.checks[rows].items():
                with self.subTest(line=line):
                    self.assertAlmostEqual(self.staging[block][line][-1], now, places=6)
                    self.assertAlmostEqual(self.staging[block][line][-5], ago, places=6)
        for block, rows in (("kpi", "kpi"), ("cash_markets", "cash_markets"), ("offexchange", "offexchange")):
            for line, (now, prior, ago) in self.checks[rows].items():
                with self.subTest(line=line):
                    values = self.staging[block][line]
                    self.assertEqual([values[-1], values[-2], values[-5]], [now, prior, ago])
        capital = self.staging["capital"]
        for line, value in self.checks["capital"].items():
            with self.subTest(line=line):
                self.assertAlmostEqual(capital[line][-1], value, places=6)
        guide = self.staging["annual_guidance_history"]
        for line in ("adjusted_operating_expenses", "adjusted_effective_tax_rate", "capex",
                     "depreciation_and_amortization"):
            with self.subTest(guide=line):
                last = guide[line]["by_year"][str(max(guide[line]["years"]))]["guided"][-1]
                self.assertEqual(last, [*self.checks["guidance"][line], self.checks["release_date"]])

    def test_the_printed_rates_agree_with_the_page_at_printed_precision(self) -> None:
        fin = self.staging["financials"]
        printed = self.checks["printed_pct"]
        now, ago = self.checks["income_statement_usd_m"]["net_revenue"]
        self.assertEqual(round((fin["net_revenue"][-1] / fin["net_revenue"][-5] - 1) * 100),
                         printed["net_revenue_growth"])
        self.assertEqual(round(fin["gaap_op_margin_pct"][-1], 1), printed["gaap_op_margin"])
        self.assertEqual(fin["tax_rate_pct"][-1], printed["tax_rate"])
        self.assertEqual(fin["adj_tax_rate_pct"][-1], printed["adj_tax_rate"])
        self.assertIn(f"净收入 US${now:,.1f}M、同比 {(now / ago - 1) * 100:+.1f}%", self.payload["headline"])

    def test_the_thresholds_current_values_are_the_series(self) -> None:
        """A typed 「当前值」 can flip a verdict; each one is read back here."""
        kpi, fin, long = self.staging["kpi"], self.staging["financials"], self.staging["long"]
        upcoming = stamped_block(self.staging, "next_kpi", self.period)
        if upcoming:
            current = {
                "Multi-listed 日均收入（US$M/日）":
                    round(kpi["multi_listed_adv_k"][-1] * kpi["multi_listed_rpc_usd"][-1] / 1000, 3),
                "指数期权日均收入（US$M/日）":
                    round(kpi["index_options_adv_k"][-1] * kpi["index_options_rpc_usd"][-1] / 1000, 3),
                "季度净收入": fin["net_revenue"][-1],
                "调整后营业费用（季）": long["adj_opex"][-1],
                "调整后营业利润率": fin["adj_op_margin_pct"][-1],
            }
            for entry in upcoming["quantified"]:
                with self.subTest(next=entry["metric"]):
                    self.assertAlmostEqual(entry["current"], current[entry["metric"]], places=6)

    def test_the_quarter_context_is_what_the_release_printed(self) -> None:
        context = stamped_block(self.staging, "quarter_context", self.period)
        if context and "opex_guidance_carve_out" in context:
            self.assertEqual(context["opex_guidance_carve_out"]["usd_m"],
                             self.checks["guidance"]["opex_reduced_for_australia_usd_m"])
        words = self.staging["revenue_growth_guidance"]["by_year"][self.period.split()[1]]
        self.assertIn(self.checks["guidance"]["organic_total_words"], words["total"][-1]["text"])
        self.assertIn(self.checks["guidance"]["data_vantage_words"], words["data_vantage"][-1]["text"])


class CboeRollTest(unittest.TestCase):
    """A roll edits the series and nothing else: the one-quarter blocks and the
    sentences about the record are held to what the series says."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(cboe.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = cboe.build_payload(cls.staging)
        cls.text = published_text(cls.payload)

    def rebuilt(self, edit) -> dict:
        changed = copy.deepcopy(self.staging)
        edit(changed)
        return cboe.build_payload(changed)

    def moves(self, claims, edit, present_before=True) -> None:
        after = published_text(self.rebuilt(edit))
        for claim in claims:
            with self.subTest(claim=claim):
                self.assertEqual(claim in self.text, present_before)
                self.assertEqual(claim in after, not present_before)

    STAMPED = ("followup_closure", "prior_kpi_settlement", "next_kpi", "quarter_context")

    def test_quarter_blocks_refuse_to_publish_under_another_quarter(self) -> None:
        present = [key for key in self.STAMPED if key in self.staging]
        self.assertTrue(present)
        for key in present:
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    self.rebuilt(lambda s, key=key: s[key].__setitem__("period", "Q1 1999"))
        quarter, year = self.staging["period_labels"][-1].split()
        label = f"Cboe {year} 年第{cn_ordinal(int(quarter[1]))}季度业绩新闻稿"
        with self.assertRaisesRegex(ValueError, "sources"):
            self.rebuilt(lambda s: s.__setitem__(
                "sources", [x for x in s["sources"] if not x["label"].startswith(label)]))

    def test_a_quarter_without_its_optional_blocks_leaves_them_out(self) -> None:
        """`next_kpi` and `quarter_context` describe one quarter; without them their
        charts, table and sentences go, and nothing that quoted them is left behind."""
        optional = [key for key in ("next_kpi", "quarter_context") if key in self.staging]

        def strip(s):
            for key in optional:
                del s[key]
        payload = self.rebuilt(strip)
        sections = {sec["id"]: sec for sec in payload["sections"]}
        if "next_kpi" in optional:
            self.assertEqual(sections["next_quarter"]["exhibits"], [])
            self.assertEqual(len(payload["tables"]), len(self.payload["tables"]) - 1)
        text = published_text(payload)
        self.assertNotRegex(text, r"\{EX_[A-Z_]+\}")

        def leaves(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if not key.startswith("_"):
                        yield from leaves(value)
            elif isinstance(node, list):
                for value in node:
                    yield from leaves(value)
            elif isinstance(node, str) and len(node) >= 12 and "{" not in node:
                yield node
        quoted = [leaf for key in optional for leaf in leaves(self.staging[key])
                  if json.dumps(leaf, ensure_ascii=False)[1:-1] in self.text]
        self.assertTrue(quoted, "the blocks' sentences are not on the page at all")
        for leaf in quoted:
            with self.subTest(gone=leaf[:30]):
                self.assertNotIn(json.dumps(leaf, ensure_ascii=False)[1:-1], text)

    def test_a_later_quarter_must_settle_the_previous_analysis(self) -> None:
        """Past the first analysis, dropping both settlement blocks is not an empty
        section one -- it is a skipped one, and the build says so."""
        record = self.staging.get("analysis_record", {})
        if display_period(record.get("first_period", "")) == display_period(self.staging["period_labels"][-1]):
            return

        def strip(s):
            s.pop("followup_closure", None)
            s.pop("prior_kpi_settlement", None)
        with self.assertRaisesRegex(ValueError, "not the first CBOE analysis"):
            self.rebuilt(strip)

    def test_a_first_analysis_settles_only_the_guidance(self) -> None:
        """The first local analysis has nothing before it: section one says so in
        the owner's words and keeps only the company's guidance record."""
        def first(s):
            s.pop("followup_closure", None)
            s.pop("prior_kpi_settlement", None)
            s["analysis_record"] = {"first_period": s["period_labels"][-1]}
            s["_checks"]["note"] = {**s["_checks"]["note"],
                                    "source": {**s["_checks"]["note"]["source"], "previous_quarter": None},
                                    "followup_closure": {"total": 0, "counts": {}},
                                    "prior_thresholds": [], "prior_total": 0}
        changed = copy.deepcopy(self.staging)
        first(changed)
        check_section_one(self, changed, cboe.build_payload(changed))
        # ...and a first analysis that carries settlement blocks is a contradiction.
        changed = copy.deepcopy(self.staging)
        changed["analysis_record"] = {"first_period": changed["period_labels"][-1]}
        if "followup_closure" in changed or "prior_kpi_settlement" in changed:
            with self.assertRaisesRegex(ValueError, "nothing for"):
                cboe.build_payload(changed)

    def test_the_settlement_blocks_are_checked_against_themselves(self) -> None:
        period = self.staging["period_labels"][-1]
        base = copy.deepcopy(self.staging)
        closure = {"period": period, "set_in": "Q1 1999", "labels": ["已验证", "部分验证"],
                   "items": [{"short": "a", "question": "a", "report_verdict": "已验证",
                              "verdict": "已验证", "evidence": "a"}]}
        entry = {"id": "t", "reads": "adj_opex", "metric": "调整后营业费用（季）", "direction": "down",
                 "threshold": 999.0, "unit": "usd_m", "basis": "测试"}

        def build(closure_block=None, prior_block=None):
            s = copy.deepcopy(base)
            s.pop("followup_closure", None)
            s.pop("prior_kpi_settlement", None)
            if closure_block is not None:
                s["followup_closure"] = closure_block
            if prior_block is not None:
                s["prior_kpi_settlement"] = prior_block
            return cboe.build_payload(s)

        prior = {"period": period, "set_in": "Q1 1999", "quantified": [entry]}
        self.assertIsNotNone(build(closure, prior))
        cases = [
            ("not labels", {**closure, "items": [{**closure["items"][0], "verdict": "别的"}]}, prior),
            ("different analyses", closure, {**prior, "set_in": "Q2 1999"}),
            ("not before", {**closure, "set_in": period}, {**prior, "set_in": period}),
            ("was due in", closure, {**prior, "quantified": [{**entry, "settles": "Q1 2000"}]}),
            ("does not know", closure, {**prior, "quantified": [{**entry, "reads": "nothing"}]}),
            ("no reading", closure, {**prior, "quantified": [{**entry, "reads": "fy_adj_opex",
                                                              "settles": period}]}),
        ]
        for message, closure_block, prior_block in cases:
            with self.subTest(message=message):
                if message == "no reading":
                    year_quarters = [q for q in base["long"]["quarters"] if q.startswith(base["periods"][-1][:4])]
                    if len(year_quarters) == 4:
                        continue    # a fourth quarter has its full-year reading
                with self.assertRaisesRegex(ValueError, message):
                    build(closure_block, prior_block)

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        # A second year over the top of the expense band: "the only overshoot" goes.
        def second_over(s):
            block = s["annual_guidance_history"]["adjusted_operating_expenses"]["by_year"]["2014"]
            block["actual"] = block["guided"][-1][1] + 5
        self.moves(("唯一一次超出上限是 FY2017",), second_over)

        # Only FY2013's last range was a reaffirmation; make all four reaffirmed.
        def all_reaffirmed(s):
            by_year = s["annual_guidance_history"]["adjusted_operating_expenses"]["by_year"]
            for year in ("2019", "2021", "2023"):
                guided = by_year[year]["guided"]
                guided[-1][:2] = list(guided[-2][:2])
                by_year[year]["actual"] = guided[-1][0] - 1
        self.moves(("刚重申过区间之后落在区间下方",), all_reaffirmed, present_before=False)
        self.moves(("FY2021 是刚上调过的区间",), all_reaffirmed)

        # Index-option RPC falls in 14 of 41 steps; make it monotone.
        def index_rpc_monotone(s):
            for block in ("kpi", "kpi_long"):
                values = s[block]["index_options_rpc_usd"]
                s[block]["index_options_rpc_usd"] = [0.5 + 0.01 * i for i in range(len(values))]
        self.moves(("几乎只往上", "RPC 同期只往上"), index_rpc_monotone, present_before=False)
        self.moves(("41 次环比里 14 次回落", "RPC 同期总体向上"), index_rpc_monotone)

        # Net revenue is just over half of gross this quarter.
        def gross_heavier(s):
            nr = s["net_revenue_window"]
            nr["cost_of_revenues"][-1] = nr["total_revenues"][-1] * 0.6
        self.moves(("「总收入」这条线一半以上不属于公司",), gross_heavier, present_before=False)
        self.moves(("「总收入」这条线本季有 49.3% 不属于公司",), gross_heavier)

        # Off-exchange share's year-on-year gain is the best of the five share lines.
        def exchange_better(s):
            s["cash_markets"]["us_share_pct"][-1] = s["cash_markets"]["us_share_pct"][-5] + 5
        self.moves(("是全公司最漂亮的一条",), exchange_better)

        # The upper bound of the expense guide leaves more than this quarter; lower it.
        def tighter_guide(s):
            guided = s["annual_guidance_history"]["adjusted_operating_expenses"]["by_year"]["2026"]["guided"]
            guided[-1][1] = 830.0
            guided[-1][0] = 815.0
        self.moves(("只比本季实际高",), tighter_guide)

    def test_the_counts_on_the_page_are_recounted_here(self) -> None:
        seg = self.staging["segments"]
        five = [sum(seg[key][i] for key in ("options", "north_american_equities",
                                            "europe_and_apac", "futures", "global_fx"))
                for i in range(len(seg["quarters"]))]
        off = sum(1 for f, t in zip(five, seg["total"]) if abs(f - t) > 0.05)
        self.assertIn(f"只取前五行会在 {len(seg['quarters'])} 个季度里的 {off} 个对不上", self.text)
        self.assertNotIn("25 个对不上", self.text)
        self.assertNotIn("窗口只画最近 20 季", self.text)
        self.assertNotIn("掉了 -", self.text)
        self.assertNotIn("同一批季度", self.text)
        self.assertNotIn("公司从不公布", self.text)
        self.assertNotIn("电话会里说明其中含", self.text)
        div = cboe.divergence_long(self.staging)
        start = cboe.share_window(div)
        self.assertIn(f"日均收入 US${div['daily_revenue_usd_m'][start]:.3f}M → ", self.payload["brief"])
        rpc = self.staging["kpi_long"]["index_options_rpc_usd"]
        falls = sum(1 for a, b in zip(rpc, rpc[1:]) if b < a)
        self.assertIn(f"{len(rpc) - 1} 次环比里 {falls} 次回落", self.text)
        guide = self.staging["annual_guidance_history"]["adjusted_operating_expenses"]
        low, high, _ = guide["by_year"][str(max(guide["years"]))]["guided"][-1]
        long = self.staging["long"]
        spent = sum(v for q, v in zip(long["quarters"], long["adj_opex"])
                    if q.startswith(str(max(guide["years"]))))
        quarters = sum(1 for q in long["quarters"] if q.startswith(str(max(guide["years"]))))
        if quarters < 4:
            self.assertIn(f"还有约 US${(high - spent) / (4 - quarters):.1f}M 的额度", self.text)
            self.assertIn(f"按指引中值倒推则是 US${((low + high) / 2 - spent) / (4 - quarters):.1f}M", self.text)


if __name__ == "__main__":
    unittest.main()
