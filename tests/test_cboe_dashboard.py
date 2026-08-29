"""CBOE page: the identities that license what this page claims.

The page makes one central claim -- that market share and the money move in
opposite directions more often than not -- and that claim is a piece of
arithmetic over company-disclosed values, so most of these tests exist to keep
the arithmetic honest rather than to restate the numbers.

Three things about Cboe's disclosure are easy to get wrong, and each has a test
below because each was actually hit while building this page.

The first is the segment table's SIXTH row. Five named segments do not sum to
the printed total in 25 of 37 quarters, and the residual changes sign partway
through, because the sixth row is "Corporate" (small, positive) until 2022 and
"Digital" (NEGATIVE -- Cboe Digital, bought in 2022 and wound down) after it.
Reading five rows and trusting the total produces a chart that is quietly wrong
in two thirds of its window. The sum identity here is what makes that loud.

The second is that the operating-metrics table is published five quarters at a
time, so consecutive releases overlap by four. Stitching them without checking
the overlap splices two vintages of the same quarter together.

The third is the guidance the page refuses to score. Organic net revenue growth
is guided as a number through 2024 and as a phrase from 2025, and the page
converts neither: the numeric years have no published actual to score against
("organic" is never restated as a full-year figure), and a phrase is not a
range. `test_word_guidance_is_never_given_numeric_endpoints` is what keeps a
future edit from quietly turning "mid to high teens" into 15-19%.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import cboe  # noqa: E402
from build.all import ENTRIES, build_all, roster_payload  # noqa: E402
from build.board import headroom  # noqa: E402


def js_payload(path: Path, marker: str) -> dict:
    text = path.read_text(encoding="utf-8")
    return json.loads(text.split(f"{marker} = ", 1)[1].rstrip().rstrip(";"))


class CboeDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(cboe.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = cboe.build_payload(cls.staging)

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
        self.assertEqual(long["quarters"][-8:], self.staging["periods"])
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

        Taking only the five named segments leaves a residual in 25 of the 37
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
        """The headline number is recomputed here, not copied from the copy."""
        div = self.staging["divergence"]
        steps = cboe.direction_steps(div["share_pct"], div["daily_revenue_usd_m"])
        self.assertEqual(steps["same"] + steps["opposite"], steps["steps"])
        self.assertGreater(steps["opposite"], steps["same"],
                           "the page's whole claim is that opposite is the majority")
        headline = self.payload["headline"]
        self.assertIn(f"{steps['steps']} 次环比", headline)
        self.assertIn(f"{steps['opposite']} 次方向相反", headline)

    def test_share_fell_while_the_money_rose_over_the_window(self) -> None:
        """The single sentence the page is built on, asserted as arithmetic."""
        div = self.staging["divergence"]
        self.assertLess(div["share_pct"][-1], div["share_pct"][0])
        self.assertGreater(div["daily_revenue_usd_m"][-1], div["daily_revenue_usd_m"][0])

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

    # ── thresholds ──────────────────────────────────────────────────────────
    def test_settled_thresholds_carry_a_filed_actual(self) -> None:
        fin = self.staging["financials"]
        div = self.staging["divergence"]
        entries = {e["metric"]: e for e in self.staging["settled_kpi"]["quantified"]}
        self.assertAlmostEqual(entries["Multi-listed 期权市占"]["actual"],
                               div["share_pct"][-1], places=6)
        self.assertAlmostEqual(entries["调整后营业费用（季）"]["actual"],
                               fin["adj_opex"][-1], places=6)

    def test_the_share_threshold_cleared_while_the_money_fell(self) -> None:
        """The page's reason for rewriting the metric, asserted rather than asserted at.

        Last quarter's threshold sat on market share and did not trigger. Over
        the same quarter the money fell. Both halves have to stay true or the
        page's argument for changing the metric evaporates.
        """
        entry = next(e for e in self.staging["settled_kpi"]["quantified"]
                     if e["metric"] == "Multi-listed 期权市占")
        self.assertGreaterEqual(
            headroom(entry["direction"], entry["threshold"], entry["actual"]), 0,
            "the share threshold is supposed to have cleared")
        div = self.staging["divergence"]
        self.assertLess(div["daily_revenue_usd_m"][-1], div["daily_revenue_usd_m"][-2],
                        "daily revenue is supposed to have fallen in the same quarter")

    def test_next_thresholds_carry_a_current_value(self) -> None:
        for entry in self.staging["next_kpi"]["quantified"]:
            self.assertIn(entry["direction"], ("up", "down"), entry["metric"])
            self.assertIsNotNone(entry["current"], entry["metric"])
            self.assertNotEqual(entry["threshold"], 0, entry["metric"])

    def test_the_rewritten_threshold_is_on_the_money_not_the_share(self) -> None:
        metrics = [e["metric"] for e in self.staging["next_kpi"]["quantified"]]
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
        self.assertIn("SPX", self.staging["settled_kpi"]["excluded"])


if __name__ == "__main__":
    unittest.main()
