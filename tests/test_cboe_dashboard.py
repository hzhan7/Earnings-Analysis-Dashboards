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
    test.assertEqual([(e["id"], e["metric"], e["direction"], e["threshold"], e.get("consecutive", 1))
                      for e in quantified],
                     [(t["id"], t["metric"], t["direction"], t["threshold"], t.get("consecutive", 1))
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


def history(staging: dict, reads: str) -> list:
    """A threshold metric's record, computed here (not through the builder), for
    recounting how many readings in a row sit past a line."""
    kpi, kpil, long = staging["kpi"], staging["kpi_long"], staging["long"]
    nr = staging["net_revenue_window"]
    net = nr["net_revenue"][nr["quarters"].index("2017Q2"):]      # the first full combined quarter
    money = [adv * rpc / 1000 for adv, rpc in zip(kpi["multi_listed_adv_k"], kpi["multi_listed_rpc_usd"])]
    adv = kpil["index_options_adv_k"]
    return {
        "net_revenue": net,
        "net_revenue_yoy": [(net[i] / net[i - 4] - 1) * 100 for i in range(4, len(net))],
        "ml_share": [v for v in kpi["multi_listed_share_pct"] if v is not None],
        "ml_daily_revenue_qoq": [money[i] / money[i - 1] for i in range(1, len(money))],
        "adj_opex": long["adj_opex"],
        "index_adv_qoq": [adv[i] / adv[i - 1] for i in range(1, len(adv))],
    }[reads]


def following_quarter(period: str) -> str:
    quarter, year = period.split()
    return f"Q1 {int(year) + 1}" if quarter == "Q4" else f"Q{int(quarter[1]) + 1} {year}"


def check_section_three(test: unittest.TestCase, staging: dict, payload: dict) -> None:
    """Section three against `_checks["note"]`: the report's section 8 thresholds,
    verbatim, one overview and one history line per metric, the overview's tally
    recounted here -- including the analysis's own "N quarters in a row" rule.
    Nothing here names a quarter, so a roll does not edit this."""
    note = staging["_checks"]["note"]
    kpi = staging["next_kpi"]
    period = staging["period_labels"][-1]
    following = following_quarter(period)
    test.assertEqual(display_period(kpi["for_period"]), following)
    section = next(s for s in payload["sections"] if s["id"] == "next_quarter")
    quantified = kpi["quantified"]
    test.assertEqual([(e["id"], e["metric"], e["direction"], e["threshold"],
                       (e.get("upside") or {}).get("above"), e.get("consecutive", 1))
                      for e in quantified],
                     [(t["id"], t["metric"], t["direction"], t["threshold"],
                       t.get("upside_above"), t.get("consecutive", 1))
                      for t in note["next_thresholds"]])
    rows = sorted({e["row"] for e in quantified} | {i["row"] for i in kpi.get("not_carried", [])})
    test.assertEqual(len(rows), note["next_rows"])
    test.assertIn(f"第 8 节「关键观察指标」的 {note['next_rows']} 条", section["description"])
    now = readings(staging)
    # A full-year line has no reading before its year is over; it waits in the table.
    due = [e for e in due_in(quantified, following) if e["reads"] in now]
    overview, lines = section["exhibits"][0], section["exhibits"][1:]
    test.assertEqual(overview["kind"], "diverging_bars")
    test.assertTrue(overview["title"].startswith(f"下季 {len(due)} 条阈值："), overview["title"])
    crossed = firing = 0
    for entry in due:
        run = 0
        for value in reversed(history(staging, entry["reads"])):
            if headroom(entry["direction"], entry["threshold"], value) >= 0:
                break
            run += 1
        if headroom(entry["direction"], entry["threshold"], now[entry["reads"]]) < 0:
            crossed += 1
            firing += run >= entry.get("consecutive", 1)
    if crossed:
        test.assertIn(("本季全部已越线" if len(due) > 1 else "本季已越线") if crossed == len(due) else
                      f"{len(due) - crossed} 条仍在安全侧、{crossed} 条本季已越线", overview["title"])
        test.assertEqual("按触发条件" in overview["title"], firing != crossed)
    else:
        test.assertNotIn("越线", overview["title"])
    test.assertEqual(len(lines), len({e["reads"] for e in due}))
    for chart in lines:
        test.assertEqual(chart["kind"], "lines")
        test.assertRegex(chart["title"], r"：下季阈值 .+，当前 ")
    table = next(t for t in payload["tables"] if t["title"] == "下季阈值与当前值（原始单位）")
    test.assertEqual(len(table["rows"]), len(quantified) + len(kpi.get("not_carried", [])))
    for item in kpi.get("not_carried", []):
        test.assertIn(item["metric"], plain(overview["note"]))


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

    # ── section two: this quarter's conclusions ─────────────────────────────
    def charts(self, payload: dict | None = None) -> dict:
        return {ex.get("ref"): ex for section in (payload or self.payload)["sections"]
                for ex in section["exhibits"]}

    def test_section_two_leads_every_title_with_the_quarter(self) -> None:
        """「本季重点」 is one conclusion per chart about this quarter -- a chart that
        only shows a long range belongs to the routine section."""
        section = next(s for s in self.payload["sections"] if s["id"] == "quarter_highlights")
        self.assertEqual(section["exhibits"][0].get("ref"), "EX_QOQ")
        for exhibit in section["exhibits"]:
            self.assertIn("本季", exhibit["title"], exhibit["title"])

    def test_the_quarter_moves_are_recounted_here(self) -> None:
        seg, fin = self.staging["segments"], self.staging["financials"]
        keys = ["options", "north_american_equities", "europe_and_apac", "futures", "global_fx"]
        rows = [fin["net_revenue"]] + [seg[key] for key in keys] + [fin["adj_opex"]]
        chart = self.charts()["EX_QOQ"]
        self.assertEqual(chart["groups"][0]["values"], [round((v[-1] / v[-5] - 1) * 100, 6) for v in rows])
        self.assertEqual(chart["groups"][1]["values"], [round((v[-1] / v[-2] - 1) * 100, 6) for v in rows])
        up = sum(1 for key in keys if seg[key][-1] > seg[key][-2])
        self.assertIn(f"五个分部{cn_count(up)}个环比增长" if up else "五个分部没有一个环比增长", chart["title"])

    def test_the_data_vantage_increase_is_split_by_caption(self) -> None:
        captions = self.staging.get("data_vantage_captions")
        if not captions:
            self.assertNotIn("EX_DV", self.charts())
            return
        chart = self.charts()["EX_DV"]
        parts = ["access_and_capacity", "market_data", "other"]
        self.assertEqual(chart["groups"][0]["values"], [round(captions[p][1], 6) for p in parts])
        self.assertEqual(chart["groups"][1]["values"], [round(captions[p][0], 6) for p in parts])
        increase = captions["total_revenues"][0] - captions["total_revenues"][1]
        moves = [captions[p][0] - captions[p][1] for p in parts]
        lead = max(range(len(parts)), key=lambda i: moves[i])
        if increase > 0:
            self.assertIn(f"{moves[lead] / increase * 100:.0f}% 来自{chart['xlabels'][lead]}", chart["title"])

    def test_the_guidance_chart_follows_the_vintages(self) -> None:
        """Built in four states here -- capex up with D&A down, both up, capex held,
        and a moved expense guide -- so no word in the title is the quarter's own."""
        base = copy.deepcopy(self.staging)
        guide = base["annual_guidance_history"]
        year = str(max(guide["capex"]["years"]))
        cv = guide["capex"]["by_year"][year]["guided"]
        dv = guide["depreciation_and_amortization"]["by_year"][year]["guided"]
        ov = guide["adjusted_operating_expenses"]["by_year"][year]["guided"]
        if len(cv) < 2 or cv[-1][2] != base["release_dates"][-1]:
            self.assertNotIn("EX_GUIDE", self.charts())
            return

        def title() -> str:
            return self.charts(cboe.build_payload(base))["EX_GUIDE"]["title"]

        cv[-1][:2] = [cv[-2][0] + 10, cv[-2][1] + 10]
        dv[-1][:2] = [dv[-2][0] - 2, dv[-2][1] - 2]
        middle = (cv[-2][0] + cv[-2][1]) / 2
        self.assertIn(f"上调到 US${cv[-1][0]:,.0f}–{cv[-1][1]:,.0f}M（中点 +{((middle + 10) / middle - 1) * 100:.0f}%）",
                      title())
        self.assertIn("折旧摊销指引反而下调", title())
        dv[-1][:2] = [dv[-2][0] + 2, dv[-2][1] + 2]
        self.assertIn("折旧摊销指引上调", title())
        self.assertNotIn("反而", title())
        cv[-1][:2] = list(cv[-2][:2])
        self.assertIn("资本开支指引本季维持", title())
        ov[-1][:2] = [ov[-2][0] + 5, ov[-2][1] + 5]
        note = self.charts(cboe.build_payload(base))["EX_GUIDE"]["note"]
        self.assertIn(f"调整后营业费用指引从 US${ov[-2][0]:,.0f}–{ov[-2][1]:,.0f}M 调到", note)
        self.assertNotIn("同口径其实是上调", note)

    def test_no_story_placeholder_is_left_unfilled(self) -> None:
        """A one-quarter sentence names a series number as {name}; every one must be
        filled from the series, never printed as braces."""
        self.assertNotRegex(published_text(self.payload), r"\{[a-z][a-z_]*(?::[a-z0-9_]+)?\}")

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
                    self.assertEqual(row[3], f"年初至今 ${sum(spent):,.1f}M（{cn_count(len(spent))}季）")
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

    def test_next_thresholds_name_what_they_read_and_store_no_reading(self) -> None:
        """A threshold carries the series it reads, never a typed reading -- so a roll
        cannot leave last quarter's number under this quarter's line."""
        kpi = stamped_block(self.staging, "next_kpi", self.staging["period_labels"][-1])
        known = set(readings(self.staging)) | {"fy_adj_opex"}
        for entry in (kpi or {}).get("quantified", []):
            with self.subTest(metric=entry["metric"]):
                self.assertIn(entry["reads"], known)
                self.assertNotIn("current", entry)
                self.assertNotIn("actual", entry)
                self.assertIn(entry["direction"], ("up", "down"))
                self.assertNotEqual(entry["threshold"], 0)
                self.assertIsInstance(entry["row"], int)

    def test_section_three_tracks_the_report_s_section_8(self) -> None:
        check_section_three(self, self.staging, self.payload)

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
        """A typed 「当前值」 can flip a verdict; every margin on the next-quarter
        overview is recomputed here from the series."""
        upcoming = stamped_block(self.staging, "next_kpi", self.period)
        if not upcoming:
            return
        now = readings(self.staging)
        quarter, year = self.period.split()
        following = f"Q1 {int(year) + 1}" if quarter == "Q4" else f"Q{int(quarter[1]) + 1} {year}"
        due = due_in(upcoming["quantified"], following)
        overview = next(ex for section in self.payload["sections"] for ex in section["exhibits"]
                        if ex.get("ref") == "EX_NEXT_HEADROOM")
        self.assertEqual(overview["xlabels"], [e["metric"] for e in due])
        self.assertEqual(overview["values"],
                         [round(headroom(e["direction"], e["threshold"], now[e["reads"]]), 1) for e in due])

    def test_the_data_vantage_captions_are_the_release_s(self) -> None:
        """The caption pairs on the page are the ones keyed separately from Table 4,
        and they land on the categories series the page already publishes."""
        captions = stamped_block(self.staging, "data_vantage_captions", self.period)
        if captions is None:
            return
        for key, pair in self.checks["data_vantage_usd_m"].items():
            with self.subTest(caption=key):
                self.assertEqual(captions[key], pair)
        cats = self.staging["categories"]["data_vantage"]
        total, cost = self.checks["data_vantage_usd_m"]["total_revenues"], self.checks["data_vantage_usd_m"]["cost_of_revenues"]
        self.assertAlmostEqual(total[0] - cost[0], cats[-1], delta=0.11)
        self.assertAlmostEqual(total[1] - cost[1], cats[-5], delta=0.11)

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
        # A sentence the remaining blocks also carry (a roll moves last quarter's
        # next-quarter lines into the settlement block as they stood) may stay.
        kept = {leaf for key, block in self.staging.items() if key not in optional
                for leaf in leaves(block)}
        quoted = [leaf for key in optional for leaf in leaves(self.staging[key])
                  if leaf not in kept and json.dumps(leaf, ensure_ascii=False)[1:-1] in self.text]
        self.assertNotEqual(text, self.text, "stripping the blocks changed nothing on the page")
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

    def built(self, edit) -> str:
        return published_text(self.rebuilt(edit))

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        """Each sentence that states a record is checked in states built here (or
        against a count taken here), never against the quarter it was written in."""
        expense = self.staging["annual_guidance_history"]["adjusted_operating_expenses"]

        def overs(s: dict) -> list[int]:
            item = s["annual_guidance_history"]["adjusted_operating_expenses"]
            return [y for y in cboe.finished_years(item)
                    if item["by_year"][str(y)]["actual"] > item["by_year"][str(y)]["guided"][-1][1]]

        # 「唯一一次超出上限」 is printed exactly while one finished year overshot.
        only = f"唯一一次超出上限是 FY{overs(self.staging)[0]}" if len(overs(self.staging)) == 1 else None
        if only:
            self.assertIn(only, self.text)

            def second_over(s):
                first = min(cboe.finished_years(s["annual_guidance_history"]["adjusted_operating_expenses"]))
                block = s["annual_guidance_history"]["adjusted_operating_expenses"]["by_year"][str(first)]
                block["actual"] = block["guided"][-1][1] + 5
            self.assertNotIn(only, self.built(second_over))
        else:
            self.assertNotIn("唯一一次超出上限", self.text)

        # Make every unflagged undershoot a reaffirmed range: the 「刚重申过」 wording
        # appears; FY2021's own history (raised, then missed) is named before that.
        def all_reaffirmed(s):
            item = s["annual_guidance_history"]["adjusted_operating_expenses"]
            for y in cboe.finished_years(item):
                block = item["by_year"][str(y)]
                guided = block["guided"]
                flagged = any(w in block["texts"][-1].lower() for w in ("below", "lower end", "low end"))
                if len(guided) > 1 and block["actual"] < guided[-1][0] and not flagged:
                    guided[-1][:2] = list(guided[-2][:2])
                    block["actual"] = guided[-1][0] - 1
        self.moves(("刚重申过区间之后落在区间下方",), all_reaffirmed, present_before=False)
        self.moves(("FY2021 是刚上调过的区间",), all_reaffirmed)

        # Index-option RPC: a choppy record prints its count of falls, a monotone
        # one says it only went up.
        def index_rpc(values_of):
            def edit(s):
                for block in ("kpi", "kpi_long"):
                    n = len(s[block]["index_options_rpc_usd"])
                    s[block]["index_options_rpc_usd"] = [values_of(i) for i in range(n)]
            return edit
        choppy = self.built(index_rpc(lambda i: 0.5 + 0.01 * i - (0.03 if i % 3 == 2 else 0)))
        n = len(self.staging["kpi_long"]["index_options_rpc_usd"])
        values = [0.5 + 0.01 * i - (0.03 if i % 3 == 2 else 0) for i in range(n)]
        falls = sum(1 for a, b in zip(values, values[1:]) if b < a)
        self.assertIn(f"{n - 1} 次环比里 {falls} 次回落", choppy)
        self.assertIn("RPC 同期总体向上", choppy)
        monotone = self.built(index_rpc(lambda i: 0.5 + 0.01 * i))
        for claim in ("几乎只往上", "RPC 同期只往上"):
            self.assertIn(claim, monotone)
            self.assertNotIn(claim, choppy)

        # Net revenue against gross: a stated share under half, 「一半以上」 over it.
        def gross_share(share):
            def edit(s):
                nr = s["net_revenue_window"]
                nr["cost_of_revenues"][-1] = nr["total_revenues"][-1] * share
            return edit
        self.assertIn("「总收入」这条线本季有 40.0% 不属于公司", self.built(gross_share(0.4)))
        self.assertIn("「总收入」这条线一半以上不属于公司", self.built(gross_share(0.6)))
        self.assertNotIn("一半以上不属于公司", self.built(gross_share(0.4)))

        # 「全公司最漂亮的一条」 is the off-exchange share line only while its gain is the best of five.
        def off_best(s):
            off = s["offexchange"]
            off["share_pct"][-1] = off["share_pct"][-5] + 30
            off["net_capture_per_100"][-1] = off["net_capture_per_100"][-5] * 0.5
        def exchange_best(s):
            off_best(s)
            s["cash_markets"]["us_share_pct"][-1] = s["cash_markets"]["us_share_pct"][-5] + 40
        self.assertIn("是全公司最漂亮的一条", self.built(off_best))
        self.assertNotIn("是全公司最漂亮的一条", self.built(exchange_best))

        # The expense budget sentence (under section three's expense line), while the
        # open year has one to three quarters in.
        year = max(expense["years"])
        spent = [v for q, v in zip(self.staging["long"]["quarters"], self.staging["long"]["adj_opex"])
                 if q.startswith(str(year))]
        expense_line = any(e["reads"] == "adj_opex"
                           for e in (self.staging.get("next_kpi") or {}).get("quantified", []))
        if expense_line and 0 < len(spent) < 4:
            def guide(low, high):
                def edit(s):
                    guided = s["annual_guidance_history"]["adjusted_operating_expenses"]["by_year"][str(year)]["guided"]
                    guided[-1][0], guided[-1][1] = low, high
                return edit
            roomy = sum(spent) + (4 - len(spent)) * (self.staging["long"]["adj_opex"][-1] + 50)
            tight = sum(spent) + (4 - len(spent)) * (self.staging["long"]["adj_opex"][-1] - 50)
            self.assertIn("只比本季实际高", self.built(guide(roomy - 15, roomy)))
            self.assertNotIn("只比本季实际高", self.built(guide(tight - 15, tight)))

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
        if falls:
            self.assertIn(f"{len(rpc) - 1} 次环比里 {falls} 次回落", self.text)
        guide = self.staging["annual_guidance_history"]["adjusted_operating_expenses"]
        low, high, _ = guide["by_year"][str(max(guide["years"]))]["guided"][-1]
        long = self.staging["long"]
        spent = sum(v for q, v in zip(long["quarters"], long["adj_opex"])
                    if q.startswith(str(max(guide["years"]))))
        quarters = sum(1 for q in long["quarters"] if q.startswith(str(max(guide["years"]))))
        if 0 < quarters < 4:
            self.assertIn(f"还有约 US${(high - spent) / (4 - quarters):.1f}M 的额度", self.text)
            self.assertIn(f"按指引中值倒推则是 US${((low + high) / 2 - spent) / (4 - quarters):.1f}M", self.text)


# ── the next quarter, rolled in memory ────────────────────────────────────────
QUARTER_END = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}
RELEASE_DAY = {1: "05-01", 2: "07-31", 3: "10-30"}      # a fourth quarter reports in February

# Rates, ratios, prices and share counts are carried unscaled when a rehearsal
# grows a quarter, so every product and ratio identity the real quarters satisfy
# still holds.
UNSCALED = {
    "financials": {"adj_op_margin_pct", "adj_ebitda_margin_pct", "diluted_eps", "adj_diluted_eps",
                   "diluted_shares_m", "tax_rate_pct", "adj_tax_rate_pct", "gaap_op_margin_pct"},
    "long": {"adj_op_margin_pct", "diluted_eps", "adj_diluted_eps", "diluted_shares_m"},
    "kpi": {"total_options_share_pct", "multi_listed_share_pct", "total_options_rpc_usd",
            "multi_listed_rpc_usd", "index_options_rpc_usd"},
    "kpi_long": {"index_options_rpc_usd"},
    "cash_markets": {"us_share_pct", "us_net_capture_per_100", "european_share_pct",
                     "european_net_capture_bps", "global_fx_net_capture_per_musd"},
    "offexchange": {"share_pct", "net_capture_per_100"},
    "capital": {"buyback_avg_price_usd", "dividend_per_share_usd", "diluted_shares_m"},
}


def rolled_forward(staging: dict, growth: float = 1.0) -> dict:
    """The series as a data-only roll to the next quarter would leave it, in memory.

    Every aligned array gains one cell -- the same quarter a year earlier, flows
    scaled by ``growth``, rates and ratios kept -- so the rehearsal tests the
    mechanics, not invented figures. The one-quarter blocks go the way a roll
    takes them: the previous `next_kpi` moves, as it stood, into
    `prior_kpi_settlement`; a `followup_closure` judges five questions;
    `next_kpi` is re-stamped; `quarter_context` and the caption pairs (read from
    a release a rehearsal does not have) are dropped. The annual guidance gains
    the release's vintage, and a fourth quarter closes the year and opens the
    next. `_checks` is re-keyed from the rolled cells. Nothing is written to disk.
    """
    s = copy.deepcopy(staging)
    period = s["period_labels"][-1]
    new = following_quarter(period)
    quarter, year = int(new[1]), int(new[-4:])
    key = f"{year}Q{quarter}"
    release = f"{year + 1}-02-06" if quarter == 4 else f"{year}-{RELEASE_DAY[quarter]}"

    def cell(block: str, name: str, value):
        return value if value is None or name in UNSCALED.get(block, ()) else round(value * growth, 6)

    s["periods"].append(key)
    s["period_labels"].append(new)
    s["period_ends"].append(f"{year}-{QUARTER_END[quarter]}")
    s["release_dates"].append(release)
    for name, values in s["financials"].items():
        values.append(cell("financials", name, values[-4]))
    for block in ("long", "net_revenue_window", "segments", "categories", "kpi", "kpi_long",
                  "cash_markets", "offexchange", "capital"):
        data = s[block]
        width = len(data["quarters"])
        for name, values in data.items():
            if name in ("quarters", "period_labels") or not isinstance(values, list) or len(values) != width:
                continue
            values.append(release if name == "release_read" else cell(block, name, values[-4]))
        data["quarters"].append(key)
        data["period_labels"].append(new)
    off = s["offexchange"]
    off["daily_revenue_usd_k"][-1] = off["adv_m_shares"][-1] * 1e6 / 100 * off["net_capture_per_100"][-1] / 1000
    kpi, div = s["kpi"], s["divergence"]
    div["quarters"].append(key)
    div["period_labels"].append(new)
    div["share_pct"].append(kpi["multi_listed_share_pct"][-1])
    div["adv_k"].append(kpi["multi_listed_adv_k"][-1])
    div["rpc_usd"].append(kpi["multi_listed_rpc_usd"][-1])
    div["daily_revenue_usd_m"].append(div["adv_k"][-1] * div["rpc_usd"][-1] / 1000)

    guide = s["annual_guidance_history"]
    growth_guide = s["revenue_growth_guidance"]["by_year"]
    if quarter == 4:
        spent = [v for q, v in zip(s["long"]["quarters"], s["long"]["adj_opex"]) if q.startswith(str(year))]
        guide["adjusted_operating_expenses"]["by_year"][str(year)]["actual"] = round(sum(spent), 1)
        tax = guide["adjusted_effective_tax_rate"]["by_year"]
        tax[str(year)]["actual"] = tax[str(year - 1)]["actual"]
        for item in guide.values():
            last = item["by_year"][str(year)]
            item["years"].append(year + 1)
            item["by_year"][str(year + 1)] = {"releases": [release], "guided": [[*last["guided"][-1][:2], release]],
                                              "actual": None, "texts": [last["texts"][-1]]}
        growth_guide[str(year + 1)] = {name: [{**v[-1], "release": release}]
                                       for name, v in growth_guide[str(year)].items()}
    else:
        for item in guide.values():
            block = item["by_year"][str(year)]
            block["guided"].append([*block["guided"][-1][:2], release])
            block["releases"].append(release)
            block["texts"].append(block["texts"][-1])
        for vintages in growth_guide[str(year)].values():
            vintages.append({**vintages[-1], "release": release})

    s["sources"].insert(0, {"label": f"Cboe {year} 年第{cn_ordinal(quarter)}季度业绩新闻稿（换季演练）",
                            "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=1374310&type=8-K"})
    s["latest"] = {**s["latest"], "period": new}

    kpi_block = s["next_kpi"]
    labels = ["已验证", "部分验证", "被证伪", "仍未披露"]
    items = [{"short": f"演练问题 {i}", "question": f"演练问题 {i}", "report_verdict": verdict,
              "verdict": verdict, "evidence": "换季演练"}
             for i, verdict in enumerate(["已验证", "已验证", "部分验证", "仍未披露", "被证伪"], 1)]
    s["followup_closure"] = {"period": new, "set_in": period, "labels": labels, "items": items}
    s["prior_kpi_settlement"] = {"period": new, "set_in": period,
                                 "quantified": copy.deepcopy(kpi_block["quantified"]),
                                 "not_carried": copy.deepcopy(kpi_block.get("not_carried", []))}

    def still_open(entry: dict) -> bool:
        """A dated line whose quarter has come is settled now, so it is not carried on."""
        if not entry.get("settles"):
            return True
        q, y = display_period(entry["settles"]).split()
        return (int(y), int(q[1])) > (year, quarter)
    # A rehearsal has no new analysis, so the next quarter tracks the same lines again.
    s["next_kpi"] = {**kpi_block, "period": new, "for_period": following_quarter(new),
                     "quantified": [copy.deepcopy(e) for e in kpi_block["quantified"] if still_open(e)]}
    for gone in ("quarter_context", "data_vantage_captions"):
        s.pop(gone, None)

    checks = s["_checks"]
    nr, fin = s["net_revenue_window"], s["financials"]

    def pair(values):
        return [values[-1], values[-5]]

    def triple(values):
        return [values[-1], values[-2], values[-5]]
    checks.update({
        "period": new, "period_end": s["period_ends"][-1], "release_date": release,
        "income_statement_usd_m": {k: pair(nr[k] if k in nr else fin[k]) for k in checks["income_statement_usd_m"]},
        "regulatory_fees_revenue_usd_m": pair(nr["regulatory_fees_revenue"]),
        "per_share": {k: pair(fin[k]) for k in checks["per_share"]},
        "adjusted": {k: pair(fin[k]) for k in checks["adjusted"]},
        "printed_pct": {"net_revenue_growth": round((nr["net_revenue"][-1] / nr["net_revenue"][-5] - 1) * 100),
                        "gaap_op_margin": round(fin["gaap_op_margin_pct"][-1], 1),
                        "tax_rate": fin["tax_rate_pct"][-1], "adj_tax_rate": fin["adj_tax_rate_pct"][-1]},
        "segments_usd_m": {k: pair(s["segments"][k]) for k in checks["segments_usd_m"]},
        "categories_usd_m": {k: pair(s["categories"][k]) for k in checks["categories_usd_m"]},
        "kpi": {k: triple(s["kpi"][k]) for k in checks["kpi"]},
        "cash_markets": {k: triple(s["cash_markets"][k]) for k in checks["cash_markets"]},
        "offexchange": {k: triple(s["offexchange"][k]) for k in checks["offexchange"]},
        "capital": {k: s["capital"][k][-1] for k in checks["capital"]},
        "guidance": {**checks["guidance"],
                     **{line: guide[line]["by_year"][str(max(guide[line]["years"]))]["guided"][-1][:2]
                        for line in ("adjusted_operating_expenses", "adjusted_effective_tax_rate",
                                     "capex", "depreciation_and_amortization")}},
        "source": "换季演练：各格取自去年同季，不是申报读数",
    })
    checks.pop("data_vantage_usd_m", None)
    note = checks["note"]
    carried = {e["id"] for e in s["next_kpi"]["quantified"]}
    checks["note"] = {
        **note,
        "source": {"this_quarter": "换季演练", "previous_quarter": note["source"]["this_quarter"]},
        "followup_closure": {"total": len(items),
                             "counts": {label: sum(1 for item in items if item["verdict"] == label)
                                        for label in labels}},
        "prior_total": len(kpi_block["quantified"]) + len(kpi_block.get("not_carried", [])),
        "prior_thresholds": copy.deepcopy(note["next_thresholds"]),
        "prior_not_carried": {"count": len(kpi_block.get("not_carried", []))},
        "next_thresholds": [t for t in note["next_thresholds"] if t["id"] in carried],
        "next_rows": len({e["row"] for e in s["next_kpi"]["quantified"]}
                         | {i["row"] for i in s["next_kpi"].get("not_carried", [])}),
    }
    return s


class CboeRollRehearsalTest(unittest.TestCase):
    """The next quarter, rolled in memory by editing the series alone (CLAUDE.md §9).

    `rolled_forward` appends a quarter to every aligned array, re-stamps `latest`,
    `_checks` and the one-quarter blocks, and moves this quarter's `next_kpi` into
    `prior_kpi_settlement`. The builder must take that without a code change;
    section one must settle what this quarter's analysis set; section three must
    keep reading its lines from the series; and the shared window census must
    still hold, because section one's charts move every exhibit number after them.
    """

    GROWTH = (1.0, 1.03)

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(cboe.STAGING_PATH.read_text(encoding="utf-8"))
        cls.variants = []
        for growth in cls.GROWTH:
            rolled = rolled_forward(cls.staging, growth)
            cls.variants.append((f"growth {growth}", rolled, cboe.build_payload(rolled)))
        # The stress puts every line on its wrong side -- and, for a line that needs
        # two quarters in a row, the quarter before it too -- so the triggers fire.
        stressed = rolled_forward(cls.staging)
        for entry in stressed["prior_kpi_settlement"]["quantified"]:
            stress(stressed, entry)
        cls.variants.append(("stressed", stressed, cboe.build_payload(stressed)))

    def test_the_next_quarter_builds_from_the_series_alone(self) -> None:
        from build.payload_guard import check as guard_payload

        for name, rolled, payload in self.variants:
            with self.subTest(variant=name):
                guard_payload(payload)
                period = rolled["period_labels"][-1]
                self.assertEqual(period, following_quarter(self.staging["period_labels"][-1]))
                self.assertIn(period, payload["title"])
                self.assertEqual([(s["id"], s["title"]) for s in payload["sections"]],
                                 [(s["id"], s["title"]) for s in cboe.build_payload(self.staging)["sections"]])
                self.assertTrue(all(section["exhibits"] for section in payload["sections"]))
                exhibits = [ex for section in payload["sections"] for ex in section["exhibits"]]
                self.assertEqual([ex["n"] for ex in exhibits], list(range(1, len(exhibits) + 1)))
                text = published_text(payload)
                self.assertNotRegex(text, r"\{EX_[A-Z_]+\}")
                self.assertNotRegex(text, r"\{[a-z][a-z_]*(?::[a-z0-9_]+)?\}")
                for ex in exhibits:
                    series = [ex.get("values")]
                    for key in ("bar", "line"):
                        if isinstance(ex.get(key), dict):
                            series.append(ex[key].get("values"))
                    for key in ("series", "groups", "stacks"):
                        series.extend(item.get("values") for item in ex.get(key) or [])
                    for values in series:
                        if values is not None:
                            self.assertEqual(len(values), len(ex["xlabels"]), ex["title"])
                # ...and the builder still never reads `_checks`.
                self.assertEqual(cboe.build_payload({k: v for k, v in rolled.items() if k != "_checks"}), payload)

    def test_section_one_settles_what_this_quarter_set(self) -> None:
        for name, rolled, payload in self.variants:
            with self.subTest(variant=name):
                check_section_one(self, rolled, payload)
                check_section_three(self, rolled, payload)
                settled = payload["sections"][0]
                self.assertNotIn("第一份季报分析", settled["description"])
                prior = rolled["prior_kpi_settlement"]["quantified"]
                period = rolled["period_labels"][-1]
                now = readings(rolled)
                due = due_in(prior, period)
                overview = next(ex for ex in settled["exhibits"] if ex.get("ref") == "EX_PRIOR_HEADROOM")
                self.assertEqual(overview["values"],
                                 [round(headroom(e["direction"], e["threshold"], now[e["reads"]]), 1) for e in due])
                expected = []
                for entry in due:
                    run = 0
                    for value in reversed(history(rolled, entry["reads"])):
                        if headroom(entry["direction"], entry["threshold"], value) >= 0:
                            break
                        run += 1
                    crossed = headroom(entry["direction"], entry["threshold"], now[entry["reads"]]) < 0
                    expected.append("触发" if crossed and run >= entry.get("consecutive", 1) else
                                    "越线未触发" if crossed else "守住")
                table = next(t for t in payload["tables"]
                             if t["title"].startswith("上季（") and "阈值" in t["title"])
                self.assertEqual([row[-1] for row in table["rows"][:len(due)]], expected)
                if name == "stressed":
                    self.assertIn("触发", expected)
                    self.assertTrue(all(verdict == "触发" for verdict in expected), expected)

    def test_three_rolls_walk_into_the_next_year(self) -> None:
        """Q3 (a vintage of the open year), Q4 (the year closes, the next opens, a
        full-year line comes due) and Q1 of the next year, each by data alone."""
        staging = copy.deepcopy(self.staging)
        # The year end the walk must reach: the fourth quarter of the year the next
        # quarter falls in, and one quarter past it.
        target = following_quarter(staging["period_labels"][-1])
        year_end = f"Q4 {target[-4:]}"
        walk, label = 1, target
        while label != year_end:
            label, walk = following_quarter(label), walk + 1
        dated = {"id": "rehearsal_fy", "reads": "fy_adj_opex", "row": 9, "settles": year_end,
                 "metric": "全年调整后营业费用（演练）", "direction": "down", "threshold": 900.0,
                 "unit": "usd_m", "basis": "换季演练"}
        staging["next_kpi"]["quantified"].append(dated)
        staging["_checks"]["note"]["next_thresholds"].append(
            {"id": dated["id"], "metric": dated["metric"], "threshold": dated["threshold"],
             "direction": dated["direction"], "row": dated["row"]})
        staging["_checks"]["note"]["next_rows"] += 1
        before_year_end = True
        for _ in range(walk + 1):
            staging = rolled_forward(staging)
            payload = cboe.build_payload(staging)
            period = staging["period_labels"][-1]
            with self.subTest(period=period):
                check_section_one(self, staging, payload)
                check_section_three(self, staging, payload)
                self.assert_window_census(staging, payload)
                table = next(t for t in payload["tables"]
                             if t["title"].startswith("上季（") and "阈值" in t["title"])
                rows = {r[0]: r for r in table["rows"]}
                if period == year_end:
                    # due: settled on the finished year, drawn on its own annual record
                    self.assertIn(rows[dated["metric"]][-1], ("守住", "越线未触发", "触发"))
                    self.assertTrue(any(ex.get("ref") == "EX_PRIOR_FY_ADJ_OPEX"
                                        for ex in payload["sections"][0]["exhibits"]))
                    before_year_end = False
                elif before_year_end:
                    self.assertEqual(rows[dated["metric"]][-1], f"未到期（{year_end} 结算）")
                else:
                    self.assertNotIn(dated["metric"], rows, "a settled line is not carried on")
        self.assertFalse(before_year_end, "the walk never reached the year end")

    def assert_window_census(self, rolled: dict, payload: dict) -> None:
        """What `test_chart_window` would say of a rolled page, run on it here: its
        ratchet, its short-axis exemptions (each short chart matched by exactly one
        cboe key, and every key still matching one), and its prose quarter counts."""
        import tests.test_chart_window as window    # a module, so no TestCase is re-collected

        published = js_payload(ROOT / "data" / "cboe.js", "window.DASH")
        exhibits = [ex for section in payload["sections"] for ex in section["exhibits"]]
        timed = [(ex, window.first_year(ex)) for ex in exhibits]
        timed = [(ex, year) for ex, year in timed if year is not None]
        reached = sum(1 for _, year in timed if year <= window.TARGET_YEAR)
        self.assertEqual(reached, window.REACH_2016["cboe"] - window.cboe_threshold_reach(published)
                         + window.cboe_threshold_reach(payload))
        used = set()
        for ex, year in timed:
            if year > window.TARGET_YEAR:
                matched = [key for key in window.CONVERTED["cboe"] if window.key_matches(key, ex["title"])]
                self.assertEqual(len(matched), 1, ex["title"])
                used |= set(matched)
        self.assertEqual(used, set(window.CONVERTED["cboe"]))
        census = window.ProseQuarterCountTest
        page_ok = set()
        for ex in exhibits:
            page_ok |= census._derivable(ex)[1]
        for ex in exhibits:
            n, ok = census._derivable(ex)
            if n < 12:
                continue
            prose = " ".join(ex.get(field) or "" for field in ("title", "note", "subtitle")
                             if isinstance(ex.get(field), str))
            if {int(m.group(1)) for m in census.ANCHOR.finditer(prose)} & (ok | page_ok):
                continue
            loose = sorted({int(m.group(1)) for m in census.COUNT.finditer(prose)
                            if int(m.group(1)) >= 12} - (ok | page_ok))
            self.assertEqual(loose, [], ex["title"])

    def test_the_rolled_page_keeps_the_shared_window_census_green(self) -> None:
        for name, rolled, payload in self.variants:
            with self.subTest(variant=name):
                self.assert_window_census(rolled, payload)


def stress(staging: dict, entry: dict) -> None:
    """Put one threshold's metric on its wrong side this quarter -- and for a line
    that needs a run, the quarters before it too -- by editing its source cells."""
    kpi, kpil, long, nr = staging["kpi"], staging["kpi_long"], staging["long"], staging["net_revenue_window"]
    need = entry.get("consecutive", 1)
    up = entry["direction"] == "up"
    if entry["reads"] == "net_revenue":
        target = entry["threshold"] * (0.9 if up else 1.1)
        factor = target / nr["net_revenue"][-1]
        for name in ("net_revenue", "total_revenues", "cost_of_revenues", "liquidity_payments",
                     "routing_and_clearing", "regulatory_fees_cost", "royalty_and_other_cost",
                     "regulatory_fees_revenue"):
            nr[name][-1] = round(nr[name][-1] * factor, 6)
    elif entry["reads"] == "adj_opex":
        long["adj_opex"][-1] = entry["threshold"] * (0.9 if up else 1.1)
    elif entry["reads"] == "ml_daily_revenue_qoq":
        for back in range(need, 0, -1):
            i = len(kpi["multi_listed_adv_k"]) - back
            kpi["multi_listed_adv_k"][i] = kpi["multi_listed_adv_k"][i - 1] * kpi["multi_listed_rpc_usd"][i - 1] \
                / kpi["multi_listed_rpc_usd"][i] * 0.9
        div = staging["divergence"]
        at = {q: i for i, q in enumerate(kpi["quarters"])}
        for j, quarter in enumerate(div["quarters"]):
            div["adv_k"][j] = kpi["multi_listed_adv_k"][at[quarter]]
            div["daily_revenue_usd_m"][j] = div["adv_k"][j] * div["rpc_usd"][j] / 1000
    elif entry["reads"] == "index_adv_qoq":
        for back in range(need, 0, -1):
            i = len(kpil["index_options_adv_k"]) - back
            kpil["index_options_adv_k"][i] = round(kpil["index_options_adv_k"][i - 1] * 0.9)
        at = {q: i for i, q in enumerate(kpil["quarters"])}
        for j, quarter in enumerate(kpi["quarters"]):
            kpi["index_options_adv_k"][j] = kpil["index_options_adv_k"][at[quarter]]


if __name__ == "__main__":
    unittest.main()
