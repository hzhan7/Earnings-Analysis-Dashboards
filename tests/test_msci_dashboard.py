"""MSCI page: the reconciliations that license what the page publishes.

The page's first section settles an ANNUAL, cost-side guidance record rather
than the quarterly revenue record every other page here carries, so most of
these tests are about that record holding together: the two guidance vintages
(first of the year, last of the year) are read from the same table, the actuals
come from one filed column, and free cash flow is the difference of the two
other filed lines.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import msci  # noqa: E402
from build.all import ENTRIES, build_all, roster_payload  # noqa: E402
from build.board import headroom  # noqa: E402


def js_payload(path: Path, marker: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{marker} = ", 1)[1].rstrip().rstrip(";")
    return json.loads(body)


class MsciDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(msci.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = msci.build_payload(cls.staging)

    # ── the eight-quarter window ────────────────────────────────────────────
    def test_the_window_is_eight_quarters_and_complete(self) -> None:
        fin = self.staging["financials"]
        self.assertEqual(len(self.staging["periods"]), 8)
        for name, values in fin.items():
            if name == "diluted_shares_m":
                continue
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
        om = self.staging["operating_metrics"]
        self.assertEqual(om["quarters"][-8:], self.staging["periods"])
        for offset, quarter in enumerate(self.staging["periods"]):
            index = om["quarters"].index(quarter)
            self.assertAlmostEqual(
                om["revenue_usd_m"][index],
                self.staging["financials"]["revenue_usd_m"][offset],
                places=3, msg=quarter)

    # ── identities inside a quarter ─────────────────────────────────────────
    def test_revenue_types_sum_to_total_revenue_every_quarter(self) -> None:
        fin = self.staging["financials"]
        for index, period in enumerate(self.staging["periods"]):
            total = (fin["recurring_usd_m"][index] + fin["abf_usd_m"][index]
                     + fin["nonrecurring_usd_m"][index])
            self.assertAlmostEqual(total, fin["revenue_usd_m"][index],
                                   delta=0.15, msg=period)

    def test_segments_sum_to_total_revenue_every_quarter(self) -> None:
        seg = self.staging["segments_usd_m"]
        fin = self.staging["financials"]
        for index, period in enumerate(self.staging["periods"]):
            total = sum(seg[name]["revenue"][index] for name in seg)
            self.assertAlmostEqual(total, fin["revenue_usd_m"][index],
                                   delta=0.15, msg=period)

    def test_operating_margin_is_the_ratio_it_claims_to_be(self) -> None:
        fin = self.staging["financials"]
        for index, period in enumerate(self.staging["periods"]):
            derived = fin["operating_income_usd_m"][index] / fin["revenue_usd_m"][index] * 100
            self.assertAlmostEqual(derived, fin["operating_margin_pct"][index],
                                   delta=0.12, msg=period)

    def test_adjusted_ebitda_is_revenue_less_adjusted_ebitda_expenses(self) -> None:
        fin = self.staging["financials"]
        for index, period in enumerate(self.staging["periods"]):
            derived = fin["revenue_usd_m"][index] - fin["adj_ebitda_expenses_usd_m"][index]
            self.assertAlmostEqual(derived, fin["adj_ebitda_usd_m"][index],
                                   delta=0.15, msg=period)

    def test_adjusted_ebitda_margin_exceeds_operating_margin_every_quarter(self) -> None:
        """Adjusted EBITDA adds back costs, so its margin cannot be the lower one."""
        fin = self.staging["financials"]
        for index, period in enumerate(self.staging["periods"]):
            self.assertGreater(fin["adj_ebitda_margin_pct"][index],
                               fin["operating_margin_pct"][index], period)

    def test_segment_margins_are_the_ratio_they_claim_to_be(self) -> None:
        seg = self.staging["segments_usd_m"]
        for name, block in seg.items():
            for index, period in enumerate(self.staging["periods"]):
                derived = block["adj_ebitda"][index] / block["revenue"][index] * 100
                self.assertAlmostEqual(derived, block["adj_ebitda_margin_pct"][index],
                                       delta=0.12, msg=f"{name} {period}")

    # ── the annual guidance record ──────────────────────────────────────────
    def test_every_guided_year_carries_one_range_per_release(self) -> None:
        hist = self.staging["annual_guidance_history"]
        for key, item in hist["items"].items():
            for year, block in item["by_year"].items():
                self.assertEqual(len(block["guided"]), len(block["releases"]),
                                 f"{key} {year}")
                for guided in block["guided"]:
                    if guided is None:
                        continue
                    low, high, _ = guided
                    self.assertLessEqual(low, high, f"{key} {year}")

    def test_finished_years_have_an_actual_and_the_open_year_does_not(self) -> None:
        hist = self.staging["annual_guidance_history"]
        for key, item in hist["items"].items():
            for year, block in item["by_year"].items():
                if int(year) < 2026:
                    self.assertIsNotNone(block["actual"], f"{key} {year}")
                else:
                    self.assertIsNone(block["actual"], f"{key} {year}")

    def test_free_cash_flow_is_operating_cash_flow_less_capex_every_year(self) -> None:
        """The three actuals come from one filed table and must close on it."""
        items = self.staging["annual_guidance_history"]["items"]
        ocf = items["op_cash_flow"]["by_year"]
        capex = items["capex"]["by_year"]
        fcf = items["free_cash_flow"]["by_year"]
        checked = 0
        for year in ocf:
            if ocf[year]["actual"] is None:
                continue
            self.assertAlmostEqual(
                ocf[year]["actual"] - capex[year]["actual"],
                fcf[year]["actual"], delta=0.15, msg=year)
            checked += 1
        self.assertGreaterEqual(checked, 6)

    def test_the_tally_the_page_publishes_is_the_one_in_the_data(self) -> None:
        """The headline claim: expense inside 6/6 against the last guidance,
        3/6 against the first. If the data stops saying that, the page must not
        keep saying it either."""
        items = self.staging["annual_guidance_history"]["items"]

        def tally(key, vintage):
            inside = 0
            for year, block in items[key]["by_year"].items():
                if block["actual"] is None:
                    continue
                guided = [g for g in block["guided"] if g]
                low, high, _ = guided[0] if vintage == "first" else guided[-1]
                if low <= block["actual"] <= high:
                    inside += 1
            return inside

        self.assertEqual(tally("operating_expense", "last"), 6)
        self.assertEqual(tally("operating_expense", "first"), 3)
        self.assertEqual(tally("free_cash_flow", "last"), 1)
        self.assertEqual(tally("free_cash_flow", "first"), 1)

    def test_free_cash_flow_beat_the_top_four_times_on_both_vintages(self) -> None:
        block = self.staging["annual_guidance_history"]["items"]["free_cash_flow"]["by_year"]
        for vintage in (0, -1):
            above = 0
            for year, year_block in block.items():
                if year_block["actual"] is None:
                    continue
                guided = [g for g in year_block["guided"] if g]
                if year_block["actual"] > guided[vintage][1]:
                    above += 1
            self.assertEqual(above, 4, f"vintage {vintage}")

    def test_the_open_year_is_excluded_from_every_settled_chart(self) -> None:
        """FY2026 is still running; a band drawn over it would settle nothing."""
        for exhibit in self.payload["sections"][0]["exhibits"]:
            for label in exhibit.get("xlabels", []):
                self.assertNotEqual(label, "FY2026")

    # ── operating metrics ───────────────────────────────────────────────────
    def test_run_rate_legs_sum_to_the_total(self) -> None:
        om = self.staging["operating_metrics"]
        for index, quarter in enumerate(om["quarters"]):
            legs = om["run_rate_recurring_usd_m"][index] + om["run_rate_abf_usd_m"][index]
            self.assertAlmostEqual(legs, om["run_rate_total_usd_m"][index],
                                   delta=0.2, msg=quarter)

    def test_run_rate_segments_sum_to_the_total(self) -> None:
        om = self.staging["operating_metrics"]
        names = ["run_rate_index_usd_m", "run_rate_analytics_usd_m",
                 "run_rate_sustainability_usd_m", "run_rate_private_assets_usd_m"]
        for index, quarter in enumerate(om["quarters"]):
            values = [om[name][index] for name in names]
            if any(v is None for v in values):
                continue
            self.assertAlmostEqual(sum(values), om["run_rate_total_usd_m"][index],
                                   delta=0.2, msg=quarter)

    def test_the_long_series_is_forty_two_contiguous_quarters(self) -> None:
        quarters = self.staging["operating_metrics"]["quarters"]
        self.assertEqual(len(quarters), 42)
        self.assertEqual(quarters[0], "2016Q1")
        self.assertEqual(quarters[-1], "2026Q2")
        year, number = 2016, 1
        for quarter in quarters:
            self.assertEqual(quarter, f"{year}Q{number}")
            number += 1
            if number == 5:
                year, number = year + 1, 1
        for name, values in self.staging["operating_metrics"].items():
            if isinstance(values, list):
                self.assertEqual(len(values), 42, name)

    def test_series_that_start_late_are_holes_not_backfills(self) -> None:
        """The basis-point fee and the share count begin where disclosure does.

        Padding either one backwards would invent a number; the charts start
        where the company's own figure starts and the notes say so.
        """
        om = self.staging["operating_metrics"]
        # Every run-rate sub-line and the basis-point fee start where MSCI began
        # printing them. What must never happen is a hole in the middle: a late
        # start is a disclosure fact, an interior gap is a dropped quarter.
        for name, values in om.items():
            if not isinstance(values, list) or not values:
                continue
            if all(isinstance(v, str) for v in values):
                continue
            reported = [i for i, v in enumerate(values) if v is not None]
            self.assertTrue(reported, name)
            span = range(reported[0], reported[-1] + 1)
            self.assertEqual([i for i in span if values[i] is None], [], name)
            self.assertEqual(reported[-1], len(values) - 1, name)
        shares = self.staging["financials"]["diluted_shares_m"]
        self.assertTrue(all(v is not None for v in shares[-6:]))

    def test_the_basis_point_fee_fell_while_aum_rose(self) -> None:
        """The page leads on this pair; it must survive a data refresh."""
        om = self.staging["operating_metrics"]
        aum = om["aum_period_end_usd_b"]
        fee = [v for v in om["aum_basis_point_fee"] if v is not None]
        self.assertGreater(aum[-1], aum[0] * 3)
        self.assertLess(fee[-1], fee[0])

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
        for term in ["市场一致预期", "收入与每股收益的公司指引"]:
            self.assertIn(term, excluded)

    def test_no_market_expectation_is_published(self) -> None:
        """Other pages carry a dated `市场预期`; this one has no checkable source."""
        self.assertNotIn("market_expectation", self.staging)
        text = json.dumps(self.payload, ensure_ascii=False)
        self.assertNotIn("市场预期高", text)

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

    def test_table_dicts_carry_only_the_keys_the_renderer_reads(self) -> None:
        """`tableHTML(title, headers, rows, cls)` is all of it; a `note` is dropped."""
        for table in self.payload["tables"]:
            self.assertEqual(set(table), {"n", "title", "headers", "rows"},
                             table["title"][:40])

    def test_the_published_payload_matches_a_fresh_build(self) -> None:
        published = js_payload(ROOT / "data" / "msci.js", "window.DASH")
        self.assertEqual(published, self.payload)

    def test_the_page_declares_the_calendar_convention_in_its_subtitle(self) -> None:
        self.assertIn("自然年财年", self.payload["subtitle"])

    def test_the_notes_say_the_guidance_is_annual_and_cost_side(self) -> None:
        notes = " ".join(self.payload["notes"])
        self.assertIn("从不给季度指引", notes)
        self.assertIn("从不指引收入与每股收益", notes)

    def test_the_roster_carries_msci_with_the_payload_s_own_labels(self) -> None:
        payloads = build_all()
        roster = roster_payload(payloads)
        entry = next(item for item in roster["items"] if item["slug"] == "msci")
        self.assertEqual(entry["latest_label"], self.payload["latest"]["disclosed_period_label"])
        self.assertEqual(entry["release_date"], self.payload["latest"]["release_date"])
        self.assertEqual(entry["group"], "financial_data_indices")
        self.assertIn(entry["group"], {group["key"] for group in roster["groups"]})

    def test_the_entry_group_exists_and_sits_where_its_order_says(self) -> None:
        from build.all import GROUPS
        keys = [group["key"] for group in GROUPS]
        self.assertIn("financial_data_indices", keys)
        orders = [group["order"] for group in GROUPS]
        self.assertEqual(orders, sorted(orders))
        entry = next(e for e in ENTRIES if e["slug"] == "msci")
        self.assertEqual(entry["group"], "financial_data_indices")

    def test_the_shell_links_the_payload_by_content_hash(self) -> None:
        import hashlib

        shell = (ROOT / "msci" / "index.html").read_text(encoding="utf-8")
        sources = re.findall(r'<script src="\.\./([^"?]+)(\?v=([0-9a-f]+))?"', shell)
        self.assertEqual([name for name, _, _ in sources],
                         ["data/roster.js", "data/msci.js",
                          "assets/charts.js", "assets/page.js"])
        for name, _, digest in sources:
            expected = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()[:8]
            self.assertEqual(digest, expected, name)


if __name__ == "__main__":
    unittest.main()
