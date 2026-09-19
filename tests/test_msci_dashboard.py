"""MSCI page: the reconciliations that license what the page publishes.

The page's first section settles an ANNUAL, cost-side guidance record rather
than the quarterly revenue record every other page here carries, so most of
these tests are about that record holding together: the two guidance vintages
(first of the year, last of the year) are read from the same table, the actuals
come from one filed column, and free cash flow is the difference of the two
other filed lines.

A roll edits `series/msci.json` and nothing else (CLAUDE.md §9): nothing below
names a quarter, a year or a count. What the quarter's release printed is
asserted from `_checks` (`MsciChecksTest`), and `MsciRollTest` rolls the series
a quarter back and two quarters forward (the second one closes a fiscal year),
tampers each stamped block, and makes each finding false on a copy of the
series to see its words go.
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

from build import msci  # noqa: E402
from build.all import ENTRIES, build_all, roster_payload  # noqa: E402
from build.board import cn_count, headroom  # noqa: E402


def js_payload(path: Path, marker: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{marker} = ", 1)[1].rstrip().rstrip(";")
    return json.loads(body)


def exhibits(payload: dict) -> list[dict]:
    return [ex for section in payload["sections"] for ex in section["exhibits"]]


def pct(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100


def series_path(staging: dict, path: str) -> list:
    block = staging
    for part in path.split("."):
        block = block[part]
    return block


def current_of(staging: dict, reads: str) -> float:
    """A threshold's current value, recomputed here rather than taken from the builder."""
    if reads.startswith("yoy:"):
        values = series_path(staging, reads[4:])
        return pct(values[-1], values[-5])
    return series_path(staging, reads)[-1]


def settled_years(staging: dict) -> list[int]:
    items = staging["annual_guidance_history"]["items"]
    return [year for year in staging["annual_guidance_history"]["years"]
            if all(item["by_year"][str(year)]["actual"] is not None for item in items.values())]


def tally(staging: dict, key: str, vintage: int) -> tuple[int, int, int, int]:
    """(years, inside, above, below) against the first (0) or last (-1) range."""
    block = staging["annual_guidance_history"]["items"][key]["by_year"]
    inside = above = below = 0
    years = settled_years(staging)
    for year in years:
        entry = block[str(year)]
        low, high, _ = [g for g in entry["guided"] if g][vintage]
        above += entry["actual"] > high
        below += entry["actual"] < low
        inside += low <= entry["actual"] <= high
    return len(years), inside, above, below


PLACEHOLDER = r"\{[A-Za-z_]+(?::[a-z_]+)?\}"
# The blocks that describe one quarter.
QUARTER_BLOCKS = ("guidance_update", "next_kpi")


class MsciDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(msci.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = msci.build_payload(cls.staging)

    # ── the review window ───────────────────────────────────────────────────
    def test_the_window_is_complete_and_aligned(self) -> None:
        periods = self.staging["periods"]
        self.assertEqual(len(self.staging["period_ends"]), len(periods))
        self.assertEqual(len(self.staging["period_labels"]), len(periods))
        for name, values in self.staging["financials"].items():
            self.assertEqual(len(values), len(periods), name)
            if name != "diluted_shares_m":
                self.assertTrue(all(v is not None for v in values), name)
        for segment, block in self.staging["segments_usd_m"].items():
            for name, values in block.items():
                self.assertEqual(len(values), len(periods), f"{segment} {name}")

    def test_quarters_are_contiguous_calendar_labels(self) -> None:
        periods = self.staging["periods"]
        for earlier, later in zip(periods, periods[1:]):
            y1, q1 = int(earlier[:4]), int(earlier[5])
            y2, q2 = int(later[:4]), int(later[5])
            self.assertEqual((y2, q2), (y1 + 1, 1) if q1 == 4 else (y1, q1 + 1))

    def test_the_window_is_the_tail_of_the_long_series(self) -> None:
        """The two windows must not disagree about an overlapping quarter."""
        om = self.staging["operating_metrics"]
        periods = self.staging["periods"]
        self.assertEqual(om["quarters"][-len(periods):], periods)
        for offset, quarter in enumerate(periods):
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

    def test_the_identity_counts_in_prose_are_the_quarters_the_series_holds(self) -> None:
        """「31 个季度逐季核对无差」 and 「全部 42 季均成立」 were checks run on data
        this file does not keep (31) or never ran (42). The page now names the
        quarters it can check, which is the length of its own split."""
        n = len(self.staging["periods"])
        mix = next(ex for ex in exhibits(self.payload) if ex["title"].startswith("三条收入腿"))
        self.assertIn(f"三条相加等于合并收入，{n} 个季度逐季核对无差", mix["note"])
        note = next(text for text in self.payload["notes"] if "分部相加等于合并收入" in text)
        self.assertIn(f"本页收录分部收入的 {n} 季均成立", note)

    # ── the annual guidance record ──────────────────────────────────────────
    def test_every_guided_year_carries_one_range_per_release(self) -> None:
        hist = self.staging["annual_guidance_history"]
        for key, item in hist["items"].items():
            for year, block in item["by_year"].items():
                self.assertEqual(block["releases"], hist["releases_by_year"][year], f"{key} {year}")
                self.assertEqual(len(block["guided"]), len(block["releases"]),
                                 f"{key} {year}")
                for guided in block["guided"]:
                    if guided is None:
                        continue
                    low, high, _ = guided
                    self.assertLessEqual(low, high, f"{key} {year}")

    def test_every_settled_year_starts_with_its_opening_release(self) -> None:
        """FY2020 was once recorded from its October release alone -- the first
        one printed as a table -- and the page then scored that October range as
        the year's 「年初第一次」 guidance. The January 2020 release had guided
        operating expense at $840-860M, against which the year's $810.6M is a
        miss, not a hit. A settled year's record opens in its first two months,
        and has one release per quarter."""
        hist = self.staging["annual_guidance_history"]
        for year in settled_years(self.staging):
            releases = hist["releases_by_year"][str(year)]
            with self.subTest(year=year):
                self.assertLessEqual(int(releases[0][5:7]), 2)
                self.assertEqual(len(releases), 4)

    def test_only_the_latest_guided_year_is_open(self) -> None:
        hist = self.staging["annual_guidance_history"]
        latest = max(hist["years"])
        self.assertEqual(settled_years(self.staging), [y for y in hist["years"] if y != latest])
        for key, item in hist["items"].items():
            self.assertIsNone(item["by_year"][str(latest)]["actual"], key)

    def test_free_cash_flow_is_operating_cash_flow_less_capex_every_year(self) -> None:
        """The three actuals come from one filed table and must close on it."""
        items = self.staging["annual_guidance_history"]["items"]
        ocf = items["op_cash_flow"]["by_year"]
        capex = items["capex"]["by_year"]
        fcf = items["free_cash_flow"]["by_year"]
        years = settled_years(self.staging)
        for year in years:
            self.assertAlmostEqual(
                ocf[str(year)]["actual"] - capex[str(year)]["actual"],
                fcf[str(year)]["actual"], delta=0.15, msg=year)
        note = next(n for n in self.payload["notes"] if "资本开支" in n and "恒等式" in n)
        self.assertIn(f"{cn_count(len(years))}个年度逐年核对该恒等式均成立", note)

    def test_the_tally_the_page_publishes_is_the_one_in_the_data(self) -> None:
        """Expense inside its range against the last guidance far more often than
        against the first. The brief said 「六个完整年度里 … 6 次全部 … 只有 3 次
        … 4 次」 for two years after the record had grown to eleven years, because
        it was typed; the notes had been fixed by then. Both are recounted now."""
        years, last_in, _, _ = tally(self.staging, "operating_expense", -1)
        _, first_in, _, _ = tally(self.staging, "operating_expense", 0)
        note = next(n for n in self.payload["notes"] if "修订的功劳" in n)
        self.assertIn(f"最后一次是 {last_in} 年", note)
        self.assertIn(f"共 {years} 个已完结年", note)
        self.assertIn(f"第一次只有 {first_in} 年", note)
        brief = self.payload["brief"]
        self.assertIn(f"{cn_count(years)}个完整年度里", brief)
        self.assertIn(f"指引 {last_in} 次{'全部' if last_in == years else ''}落在区间内", brief)
        self.assertIn(f"指引只有 {first_in} 次", brief)
        self.assertIn(f"{cn_count(years)}个完整年度的费用与现金记录",
                      self.payload["sections"][0]["description"])

    def test_the_free_cash_flow_beat_is_counted_on_both_vintages(self) -> None:
        """The beat is not an artefact of guidance being revised late in the year
        when it is the same count whichever vintage is scored."""
        _, _, first_above, _ = tally(self.staging, "free_cash_flow", 0)
        _, _, last_above, _ = tally(self.staging, "free_cash_flow", -1)
        brief = self.payload["brief"]
        if first_above == last_above:
            self.assertIn(f"自由现金流两种口径都是 {first_above} 次穿出上限", brief)
        else:
            self.assertIn(f"对第一次指引 {first_above} 次、对最后一次 {last_above} 次穿出上限", brief)

    def test_the_record_note_counts_the_releases_it_holds(self) -> None:
        hist = self.staging["annual_guidance_history"]
        first = min(hist["years"])
        note = next(n for n in self.payload["notes"] if "本页的指引记录" in n)
        self.assertIn(f"起于 FY{first} 的第一份发布（{hist['releases_by_year'][str(first)][0]}）", note)
        self.assertIn(f"共 {sum(len(v) for v in hist['releases_by_year'].values())} 次发布", note)
        self.assertIn(f"覆盖 FY{first} 至 FY{max(hist['years'])} {cn_count(len(hist['years']))}个年度", note)
        self.assertIn(f"其中{cn_count(len(settled_years(self.staging)))}个年度已完结", note)

    def test_the_open_year_is_excluded_from_every_settled_chart(self) -> None:
        """The open year is still running; a band drawn over it would settle nothing."""
        open_year = f"FY{max(self.staging['annual_guidance_history']['years'])}"
        for exhibit in self.payload["sections"][0]["exhibits"]:
            for label in exhibit.get("xlabels", []):
                self.assertNotEqual(label, open_year)

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

    def test_the_long_series_runs_contiguously_from_2016_to_the_page_quarter(self) -> None:
        quarters = self.staging["operating_metrics"]["quarters"]
        self.assertEqual(quarters[0], "2016Q1")
        self.assertEqual(quarters[-1], self.staging["periods"][-1])
        year, number = 2016, 1
        for quarter in quarters:
            self.assertEqual(quarter, f"{year}Q{number}")
            number += 1
            if number == 5:
                year, number = year + 1, 1
        for name, values in self.staging["operating_metrics"].items():
            if isinstance(values, list):
                self.assertEqual(len(values), len(quarters), name)

    def test_series_that_start_late_are_holes_not_backfills(self) -> None:
        """A late start is a disclosure fact, an interior gap is a dropped quarter."""
        om = self.staging["operating_metrics"]
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

    def test_the_page_leads_on_scale_against_fee_only_while_the_data_does(self) -> None:
        om = self.staging["operating_metrics"]
        aum = om["aum_period_end_usd_b"]
        fee = [v for v in om["aum_basis_point_fee"] if v is not None]
        says = "规模在涨，过路费率在降" in self.payload["brief"]
        self.assertEqual(says, aum[-1] > aum[0] and fee[-1] < fee[0])

    # ── thresholds, exhibits, publication ───────────────────────────────────
    def test_every_quantified_threshold_has_a_headroom_bar(self) -> None:
        kpi = self.staging["next_kpi"]["quantified"]
        bar = self.payload["sections"][2]["exhibits"][0]
        self.assertEqual(bar["xlabels"], [entry["metric"] for entry in kpi])
        for entry, value in zip(kpi, bar["values"]):
            current = current_of(self.staging, entry["reads"])
            self.assertAlmostEqual(
                headroom(entry["direction"], entry["threshold"], current),
                value, places=1, msg=entry["metric"])

    def test_threshold_current_values_are_read_not_typed(self) -> None:
        """A typed current value flips conclusions when it drifts from the series;
        the block names the series instead."""
        for entry in self.staging["next_kpi"]["quantified"]:
            self.assertNotIn("current", entry, entry["metric"])
            self.assertIn("reads", entry, entry["metric"])

    def test_the_basis_point_fee_is_printed_in_basis_points(self) -> None:
        """The fee's unit used to be `times`, which printed 2.28 bps as 「2.28x」."""
        table = next(t for t in self.payload["tables"] if t["title"].startswith("下季阈值与当前值"))
        row = next(r for r in table["rows"] if r[0] == "期末基点费率")
        fee = self.staging["operating_metrics"]["aum_basis_point_fee"][-1]
        self.assertEqual(row[3], f"{fee:.2f}bp")
        self.assertFalse(any(cell.endswith("x") for cell in row[2:4]))

    def test_what_the_page_refuses_to_plot_is_named(self) -> None:
        excluded = self.staging["next_kpi"]["excluded"]
        for term in ["市场一致预期", "收入与每股收益的公司指引"]:
            self.assertTrue(any(term in item for item in excluded), term)
        count = cn_count(len(excluded))
        self.assertIn(f"不接入的{count}条也写在这里", self.payload["sections"][2]["description"])
        self.assertIn(f"另有{count}条本页<b>不接入</b>", self.payload["sections"][2]["exhibits"][0]["note"])

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
        self.assertNotRegex(text, r"\{EX_[A-Z_0-9]+\}")
        self.assertNotRegex(text, PLACEHOLDER)

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

    def test_the_adjusted_ebitda_gap_is_not_said_to_include_stock_compensation(self) -> None:
        """MSCI's adjusted EBITDA adds back D&A, amortisation of intangibles and, at
        times, acquisition costs -- not stock-based compensation, which the
        release reports inside operating expense. The gap between the two margin
        lines is therefore not 「折旧摊销加股权激励」."""
        margin = next(ex for ex in exhibits(self.payload) if ex["title"].endswith("经营 "
                      f"{self.staging['operating_metrics']['operating_margin_pct'][-1]:.1f}%"))
        self.assertNotIn("加股权激励", margin["note"])
        self.assertIn("股权激励不在其中", margin["note"])

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


class MsciChecksTest(unittest.TestCase):
    """The page's quarter against a record keyed separately from the release.

    `_checks` is typed once per quarter from the earnings release itself, with
    the place in the document each figure was read from -- it is not copied out
    of the arrays, and the builder never reads it (asserted in
    `test_data_only_roll`). The release prints money to a tenth of a million and
    rates to a tenth of a point; the series carries the older quarters in
    thousands, so growth rates are compared at the precision the release prints.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(msci.STAGING_PATH.read_text(encoding="utf-8"))
        cls.checks = cls.staging["_checks"]
        cls.fin = cls.staging["financials"]
        cls.om = cls.staging["operating_metrics"]
        cls.payload = msci.build_payload(cls.staging)

    def test_the_page_names_the_checked_quarter(self) -> None:
        self.assertIn(self.checks["period"], self.payload["title"])
        self.assertIn(f"截至 {self.checks['period_end']}", self.payload["subtitle"])
        self.assertIn(f"发布 {self.checks['release_date']}", self.payload["subtitle"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        c, fin, om = self.checks, self.fin, self.om
        for key in ("revenue_usd_m", "recurring_usd_m", "abf_usd_m", "nonrecurring_usd_m",
                    "adj_ebitda_usd_m", "adj_ebitda_margin_pct", "operating_margin_pct",
                    "diluted_eps_usd", "adjusted_eps_usd", "diluted_shares_m"):
            with self.subTest(key=key):
                self.assertAlmostEqual(fin[key][-1], c[key], places=6)
        seg = self.staging["segments_usd_m"]
        for name, value in c["segment_revenue_usd_m"].items():
            self.assertAlmostEqual(seg[name]["revenue"][-1], value, places=6, msg=name)
        for name, value in c["segment_adj_ebitda_margin_pct"].items():
            self.assertAlmostEqual(seg[name]["adj_ebitda_margin_pct"][-1], value, places=6, msg=name)
        for key, series in (("retention_rate_pct", "retention_rate_pct"),
                            ("aum_period_end_usd_b", "aum_period_end_usd_b"),
                            ("basis_point_fee", "aum_basis_point_fee"),
                            ("run_rate_total_usd_m", "run_rate_total_usd_m"),
                            ("run_rate_recurring_usd_m", "run_rate_recurring_usd_m"),
                            ("run_rate_abf_usd_m", "run_rate_abf_usd_m")):
            with self.subTest(key=key):
                self.assertAlmostEqual(om[series][-1], c[key], places=6)

    def test_computed_growth_rounds_to_the_printed_growth(self) -> None:
        c, fin, om = self.checks, self.fin, self.om
        self.assertEqual(round(fin["revenue_yoy_pct"][-1], 1), c["revenue_yoy_pct"])
        self.assertEqual(round(pct(fin["recurring_usd_m"][-1], fin["recurring_usd_m"][-5]), 1),
                         c["recurring_yoy_pct"])
        self.assertEqual(round(pct(fin["abf_usd_m"][-1], fin["abf_usd_m"][-5]), 1), c["abf_yoy_pct"])
        self.assertEqual(round(pct(om["run_rate_total_usd_m"][-1], om["run_rate_total_usd_m"][-5]), 1),
                         c["run_rate_growth_pct"])

    def test_the_open_year_ends_on_the_checked_guidance(self) -> None:
        hist = self.staging["annual_guidance_history"]
        year = str(max(hist["years"]))
        for key, (low, high) in self.checks["guidance_current_usd_m"].items():
            guided = hist["items"][key]["by_year"][year]["guided"]
            self.assertEqual(guided[-1][:2], [low, high], key)
            self.assertEqual(guided[-2][:2], self.checks["guidance_prior_usd_m"][key], key)

    def test_the_page_prints_the_checked_figures(self) -> None:
        c = self.checks
        headline = self.payload["headline"]
        self.assertIn(f"收入 US${c['revenue_usd_m']:,.1f}M、同比 +{c['revenue_yoy_pct']:.1f}%", headline)
        self.assertIn(f"资产型费用同比 +{c['abf_yoy_pct']:.1f}%", headline)
        self.assertIn(f"US${c['aum_period_end_usd_b']:,.0f}B", headline)
        self.assertIn(f"{c['basis_point_fee']:.2f}bp", headline)
        titles = [ex["title"] for ex in exhibits(self.payload)]
        self.assertIn(f"三条收入腿：资产型费用同比 +{c['abf_yoy_pct']:.1f}%，订阅 +{c['recurring_yoy_pct']:.1f}%",
                      titles)
        self.assertTrue(any(t.startswith(f"Run Rate 与收入的同比增速：Run Rate +{c['run_rate_growth_pct']:.1f}%，"
                                         f"收入 +{c['revenue_yoy_pct']:.1f}%") for t in titles))
        self.assertTrue(any(f"Index {c['segment_adj_ebitda_margin_pct']['index']:.1f}%" in t for t in titles))
        self.assertEqual(msci.headline_metrics(self.staging)[0], f"Revenue ${c['revenue_usd_m']:.0f}M")

    def test_the_revision_chart_moves_by_the_checked_guidance(self) -> None:
        """The chart's net move runs from the year's first range to the current
        one the release prints; its note names this release's date."""
        c = self.checks
        hist = self.staging["annual_guidance_history"]
        year = str(max(hist["years"]))
        first = {k: hist["items"][k]["by_year"][year]["guided"][0][:2] for k in c["guidance_prior_usd_m"]}
        move = {k: pct(sum(c["guidance_current_usd_m"][k]) / 2, sum(first[k]) / 2) for k in first}
        charts = [ex for ex in exhibits(self.payload) if ex["title"].startswith(f"FY{year} 指引")]
        self.assertEqual(len(charts), 1 if any(abs(v) > 1e-9 for v in move.values()) else 0)
        for chart in charts:
            verb = "上调" if move["operating_expense"] > 0 else "下调"
            self.assertIn(f"营业费用中值{verb} {move['operating_expense']:+.1f}%", chart["title"])
            self.assertIn(f"{move['free_cash_flow']:+.1f}%", chart["title"])
            self.assertIn(f"本季（{c['release_date']}）", chart["note"])


def rolled_back(staging: dict) -> dict:
    """The series one quarter earlier: every aligned array loses its last cell,
    the open year loses its last release, and the quarter's own blocks go."""
    s = copy.deepcopy(staging)
    for key in ("periods", "period_ends", "period_labels"):
        s[key] = s[key][:-1]
    for key, values in s["financials"].items():
        s["financials"][key] = values[:-1]
    for block in s["segments_usd_m"].values():
        for key, values in block.items():
            block[key] = values[:-1]
    for key, values in s["operating_metrics"].items():
        if isinstance(values, list):
            s["operating_metrics"][key] = values[:-1]
    hist = s["annual_guidance_history"]
    year = str(max(hist["years"]))
    dropped = hist["releases_by_year"][year][-1]
    hist["releases_by_year"][year] = hist["releases_by_year"][year][:-1]
    for item in hist["items"].values():
        block = item["by_year"][year]
        block["releases"] = block["releases"][:-1]
        block["guided"] = block["guided"][:-1]
    for key in ("_checks",) + QUARTER_BLOCKS:
        s.pop(key, None)
    label = s["period_labels"][-1]
    s["latest"] = dict(s["latest"], period=label, release_date=hist["releases_by_year"][year][-1])
    words = msci.quarter_words(label)
    s["sources"] = ([{"label": f"MSCI {words}业绩新闻稿（8-K EX-99.1，含全年 Guidance 表）",
                      "url": "https://example.invalid/previous-release"}]
                    + [src for src in s["sources"] if "业绩新闻稿" not in src["label"]
                       and "10-Q" not in src["label"]])
    assert dropped not in json.dumps(s["annual_guidance_history"])
    return s


def rolled_forward(staging: dict, *, close_year: bool = False) -> dict:
    """The series one quarter later, with made-up figures that keep every
    identity. With `close_year` the new quarter is a fourth quarter: its release
    settles the year and opens the next one with a single range."""
    s = copy.deepcopy(staging)
    fin, om, seg = s["financials"], s["operating_metrics"], s["segments_usd_m"]
    year, number = int(s["periods"][-1][:4]), int(s["periods"][-1][-1])
    year, number = (year + 1, 1) if number == 4 else (year, number + 1)
    if close_year:
        assert number == 4, "close_year needs the next quarter to be a fourth quarter"
    label, period = f"Q{number} {year}", f"{year}Q{number}"
    end = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}[number]
    s["periods"].append(period)
    s["period_labels"].append(label)
    s["period_ends"].append(f"{year}-{end}")
    grow = 1.02
    for key, values in fin.items():
        values.append(round(values[-1] * grow, 3) if key != "revenue_yoy_pct" else None)
    for key in ("recurring_usd_m", "abf_usd_m", "nonrecurring_usd_m"):
        fin[key][-1] = round(fin[key][-2] * grow, 3)
    fin["revenue_usd_m"][-1] = round(fin["recurring_usd_m"][-1] + fin["abf_usd_m"][-1]
                                     + fin["nonrecurring_usd_m"][-1], 3)
    fin["adj_ebitda_margin_pct"][-1] = fin["adj_ebitda_margin_pct"][-2]
    fin["operating_margin_pct"][-1] = fin["operating_margin_pct"][-2]
    fin["revenue_yoy_pct"][-1] = pct(fin["revenue_usd_m"][-1], fin["revenue_usd_m"][-5])
    for block in seg.values():
        for key, values in block.items():
            values.append(values[-1] if key == "adj_ebitda_margin_pct" else round(values[-1] * grow, 3))
    scale = fin["revenue_usd_m"][-1] / sum(block["revenue"][-1] for block in seg.values())
    for block in seg.values():
        block["revenue"][-1] = block["revenue"][-1] * scale
    for key, values in om.items():
        if not isinstance(values, list):
            continue
        if key == "quarters":
            values.append(period)
        elif key == "period_labels":
            values.append(label)
        elif key in ("retention_rate_pct", "aum_basis_point_fee", "adj_ebitda_margin_pct",
                     "operating_margin_pct"):
            values.append(values[-1])
        else:
            values.append(round(values[-1] * grow, 3))
    om["revenue_usd_m"][-1] = fin["revenue_usd_m"][-1]
    hist = s["annual_guidance_history"]
    open_year = str(max(hist["years"]))
    release = f"{year + (1 if number == 4 else 0)}-{({1: '04', 2: '07', 3: '10', 4: '01'}[number])}-25"
    if close_year:
        hist["years"].append(int(open_year) + 1)
        hist["releases_by_year"][str(int(open_year) + 1)] = [release]
        for item in hist["items"].values():
            block = item["by_year"][open_year]
            last = block["guided"][-1]
            block["actual"] = (last[0] + last[1]) / 2
            item["by_year"][str(int(open_year) + 1)] = {
                "releases": [release], "guided": [[last[0] * 1.05, last[1] * 1.05, False]],
                "actual": None}
        items = hist["items"]
        items["free_cash_flow"]["by_year"][open_year]["actual"] = (
            items["op_cash_flow"]["by_year"][open_year]["actual"]
            - items["capex"]["by_year"][open_year]["actual"])
    else:
        hist["releases_by_year"][open_year].append(release)
        for item in hist["items"].values():
            block = item["by_year"][open_year]
            block["releases"].append(release)
            block["guided"].append(list(block["guided"][-1]))
    for key in ("_checks",) + QUARTER_BLOCKS:
        s.pop(key, None)
    s["latest"] = dict(s["latest"], period=label, release_date=release)
    s["sources"] = ([{"label": f"MSCI {msci.quarter_words(label)}业绩新闻稿（8-K EX-99.1）",
                      "url": "https://example.invalid/next-release"}] + s["sources"])
    return s


class MsciRollTest(unittest.TestCase):
    """What a roll can change without touching the builder."""

    # Words that exist only because a stamped block said them.
    STORY_ONLY = ("4 月只把折旧摊销", "利息与折旧摊销", "判断为可吸收")

    @classmethod
    def setUpClass(cls) -> None:
        cls.s = json.loads(msci.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = msci.build_payload(cls.s)
        cls.text = json.dumps(cls.payload, ensure_ascii=False)

    def test_a_block_stamped_for_another_quarter_stops_the_build(self) -> None:
        for key in QUARTER_BLOCKS:
            stale = copy.deepcopy(self.s)
            stale[key]["period"] = "Q1 1999"
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    msci.build_payload(stale)

    def test_the_quarters_own_release_must_be_in_the_sources(self) -> None:
        bare = copy.deepcopy(self.s)
        prefix = f"MSCI {msci.quarter_words(self.s['period_labels'][-1])}业绩新闻稿"
        bare["sources"] = [src for src in bare["sources"] if not src["label"].startswith(prefix)]
        self.assertLess(len(bare["sources"]), len(self.s["sources"]))
        with self.assertRaisesRegex(ValueError, "sources"):
            msci.build_payload(bare)

    def test_a_quarter_without_its_blocks_leaves_them_out(self) -> None:
        bare = copy.deepcopy(self.s)
        for key in QUARTER_BLOCKS:
            del bare[key]
        payload = msci.build_payload(bare)
        text = json.dumps(payload, ensure_ascii=False)
        for phrase in self.STORY_ONLY:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)
                self.assertNotIn(phrase, text)
        section = next(s for s in payload["sections"] if s["id"] == "next_quarter")
        self.assertEqual(section["exhibits"], [])
        self.assertIn("没有设定下季阈值", section["description"])
        self.assertFalse(any(t["title"].startswith("下季阈值") for t in payload["tables"]))
        numbers = [ex["n"] for ex in exhibits(payload)]
        self.assertEqual(numbers, list(range(2, 2 + len(numbers))))
        self.assertEqual([t["n"] for t in payload["tables"]],
                         list(range(numbers[-1] + 1, numbers[-1] + 1 + len(payload["tables"]))))
        self.assertNotRegex(text, PLACEHOLDER)
        self.assertNotRegex(text, r"\{EX_[A-Z_0-9]+\}")
        # The revision chart still has a note: what the series alone can say.
        revision = exhibits(payload)[0]
        self.assertIn("一起上调", revision["note"])

    def test_the_quarter_before_builds_from_the_series_alone(self) -> None:
        rolled = rolled_back(self.s)
        payload = msci.build_payload(rolled)
        label = rolled["period_labels"][-1]
        self.assertEqual(payload["latest"]["disclosed_period_label"], label)
        self.assertIn(f"{label} 季报仪表盘", payload["title"])
        self.assertIn(f"{msci.quarter_words(label)}之后的任何数据", payload["notes"][-2])
        self.assertNotIn(self.s["period_labels"][-1], own_text(payload))
        # The year's two releases repeat each other on all five lines, so there
        # is no revision chart and the headline says the guidance held.
        hist = rolled["annual_guidance_history"]
        year = max(hist["years"])
        self.assertIn(f"维持 FY{year} 费用指引", payload["headline"])
        self.assertFalse(any(ex["title"].startswith(f"FY{year} 指引") for ex in exhibits(payload)))

    def test_two_quarters_forward_close_the_year_and_open_the_next(self) -> None:
        once = rolled_forward(self.s)
        payload = msci.build_payload(once)
        self.assertIn(f"{once['period_labels'][-1]} 季报仪表盘", payload["title"])
        twice = rolled_forward(once, close_year=True)
        payload = msci.build_payload(twice)
        hist = twice["annual_guidance_history"]
        closed, opened = max(hist["years"]) - 1, max(hist["years"])
        settled = exhibits(payload)[0]
        self.assertEqual(settled["xlabels"][-1], f"FY{closed}")
        self.assertIn(f"给出 FY{opened} 的第一份全年指引", payload["headline"])
        self.assertFalse(any(ex["title"].startswith(f"FY{opened} 指引") for ex in exhibits(payload)))
        years = len(settled_years(twice))
        self.assertIn(f"{cn_count(years)}个完整年度", payload["brief"])
        self.assertNotRegex(json.dumps(payload, ensure_ascii=False), PLACEHOLDER)


def own_text(payload: dict) -> str:
    """Everything the page says, less the cross-page table every page carries."""
    own = dict(payload, tables=[t for t in payload["tables"] if "AI capex" not in t["title"]])
    return json.dumps(own, ensure_ascii=False)


class MsciFindingsTest(unittest.TestCase):
    """Every judgement on the page says what the series says, both ways.

    Each case forces the series into a state where a finding is true, then into
    one where it is false, and checks the words follow. Forcing -- rather than
    flipping whatever today's data happens to say -- keeps these tests valid
    after a roll changes the underlying facts.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.s = json.loads(msci.STAGING_PATH.read_text(encoding="utf-8"))

    def page(self, *edits) -> str:
        staged = copy.deepcopy(self.s)
        for edit in edits:
            edit(staged)
        return own_text(msci.build_payload(staged))

    # ── the long routine series ─────────────────────────────────────────────
    def test_the_fourth_quarter_retention_claim(self) -> None:
        def q4_lowest(s):
            om = s["operating_metrics"]
            for i, quarter in enumerate(om["quarters"]):
                if quarter.endswith("Q4") and i >= 3:
                    om["retention_rate_pct"][i] = min(om["retention_rate_pct"][i - 3:i]) - 0.5

        def one_first_quarter_lower(s):
            q4_lowest(s)
            om = s["operating_metrics"]
            q4 = om["quarters"].index("2017Q4")
            om["retention_rate_pct"][q4 - 3] = om["retention_rate_pct"][q4] - 0.5

        always = self.page(q4_lowest)
        self.assertIn("每年第四季是合同集中续约的季度，读数系统性低于其余三季", always)
        broken = self.page(one_first_quarter_lower)
        self.assertNotIn("系统性低于其余三季", broken)
        self.assertIn("（2017 年第一季更低）", broken)

    def test_the_first_quarter_dip_claim(self) -> None:
        def dips(years):
            def edit(s):
                om = s["operating_metrics"]
                for i, quarter in enumerate(om["quarters"]):
                    if quarter.endswith("Q1") and i:
                        step = -1 if int(quarter[:4]) in years else 1
                        om["adj_ebitda_margin_pct"][i] = om["adj_ebitda_margin_pct"][i - 1] + step
                        om["operating_margin_pct"][i] = om["operating_margin_pct"][i - 1] + step
            return edit

        years = [int(q[:4]) for i, q in enumerate(self.s["operating_metrics"]["quarters"])
                 if q.endswith("Q1") and i]
        self.assertIn("pp。每年第一季两条线同时下沉，是", self.page(dips(set(years))))
        recent = self.page(dips(set(years[-2:])))
        self.assertIn(f"pp。{years[-2]} 年起每年第一季两条线同时下沉", recent)
        self.assertIn(f"此前{cn_count(len(years) - 2)}个第一季没有一个", recent)
        scattered = self.page(dips({years[0]}))
        self.assertIn(f"{cn_count(len(years))}个第一季里有一个两条线同时下沉，不构成每年都有的季节性", scattered)
        self.assertNotIn("属于季节性而非趋势", scattered)

    def test_the_asset_based_run_rate_decline_claim(self) -> None:
        def runs(*starts):
            def edit(s):
                om = s["operating_metrics"]
                falling = {start + k for start in starts for k in range(3)}
                value, abf, rec = 100.0, [], []
                for i in range(len(om["quarters"])):
                    value += -1 if i in falling else 2
                    abf.append(value)
                    rec.append(1000.0 + 5 * i)
                om["run_rate_abf_usd_m"], om["run_rate_recurring_usd_m"] = abf, rec
            return edit

        quarters = self.s["operating_metrics"]["quarters"]
        one = self.page(runs(quarters.index("2022Q1")))
        self.assertIn("2022 年的市场回撤在这张图上是唯一一次资产型 Run Rate 连续三季下行，"
                      "而订阅腿在同期继续上行", one)
        two = self.page(runs(quarters.index("2018Q2"), quarters.index("2022Q1")))
        self.assertIn("资产型 Run Rate 连续三季下行在这张图上出现过两次（2018Q2–2018Q4、2022Q1–2022Q3），"
                      "订阅腿在这两段里都继续上行", two)
        self.assertNotIn("唯一一次", two)

    # ── this quarter's highlights ───────────────────────────────────────────
    def test_the_segment_speed_claim(self) -> None:
        def rising(keys):
            def edit(s):
                for key, block in s["segments_usd_m"].items():
                    revenue = block["revenue"]
                    revenue[4] = revenue[0] * 1.10
                    revenue[-1] = revenue[-5] * (1.20 if key in keys else 1.05)
            return edit

        self.assertIn("也是唯一在本窗口内加速的分部", self.page(rising({"index"})))
        two = self.page(rising({"index", "analytics"}))
        self.assertNotIn("唯一在本窗口内加速", two)
        self.assertIn("同比增速抬升的是 Index（+10.0% → +20.0%）与 Analytics（+10.0% → +20.0%），其余两个放缓", two)
        self.assertIn("四个分部的同比增速都在放缓", self.page(rising(set())))

    def test_the_segment_margin_spread_claim(self) -> None:
        def spread(s):
            for block, level in zip(s["segments_usd_m"].values(), (80.0, 50.0, 35.0, 20.0)):
                block["adj_ebitda_margin_pct"] = [level + i % 2 for i in range(len(s["periods"]))]

        def converge(s):
            for block in s["segments_usd_m"].values():
                block["adj_ebitda_margin_pct"] = [50.0 + i % 2 * 20 for i in range(len(s["periods"]))]

        wide = self.page(spread)
        self.assertIn("四条线之间的差距，比任何一条自己的变化都大：Index 的分部利润率在 80.0%–81.0% 之间", wide)
        self.assertIn("合并利润率因此主要由收入落在哪个分部决定", wide)
        narrow = self.page(converge)
        self.assertIn("四条线各自的起伏与它们之间的差距同一量级", narrow)
        self.assertNotIn("合并利润率因此主要由收入落在哪个分部决定", narrow)

    def test_the_asset_based_fee_role_claim(self) -> None:
        def legs(total_step, rec_step, abf_step, non_step):
            """Set this quarter's growth relative to last quarter's, leg by leg."""
            def edit(s):
                fin = s["financials"]
                fin["revenue_yoy_pct"][-1] = fin["revenue_yoy_pct"][-2] + total_step
                for key, step in (("recurring_usd_m", rec_step), ("abf_usd_m", abf_step),
                                  ("nonrecurring_usd_m", non_step)):
                    before = pct(fin[key][-2], fin[key][-6])
                    fin[key][-1] = fin[key][-5] * (1 + (before + step) / 100)
            return edit

        sped = self.page(legs(+1, -1, +1, -1))
        self.assertIn("是全部加速的来源；", sped)
        self.assertIn("<b>资产型费用是唯一的加速腿</b>", sped)

        def only_fees_outgrow(s):
            fin = s["financials"]
            fin["revenue_yoy_pct"][-1] = fin["revenue_yoy_pct"][-2] - 1
            now = fin["revenue_yoy_pct"][-1]
            for key, rate in (("recurring_usd_m", now - 2), ("abf_usd_m", now + 10),
                              ("nonrecurring_usd_m", now - 10)):
                fin[key][-1] = fin[key][-5] * (1 + rate / 100)

        faster = self.page(only_fees_outgrow)
        self.assertIn("是三条收入腿里唯一快过总收入的；", faster)
        self.assertNotIn("全部加速的来源", faster)

        def fees_lag(s):
            fin = s["financials"]
            fin["revenue_yoy_pct"][-1] = fin["revenue_yoy_pct"][-2] - 1
            now = fin["revenue_yoy_pct"][-1]
            for key, rate in (("recurring_usd_m", now + 1), ("abf_usd_m", now - 1),
                              ("nonrecurring_usd_m", now - 1)):
                fin[key][-1] = fin[key][-5] * (1 + rate / 100)

        lagging = self.page(fees_lag)
        self.assertNotIn("快过总收入", lagging)
        self.assertIn("<b>三条收入腿各走各的</b>", lagging)

        def fees_and_one_time(s):
            only_fees_outgrow(s)
            fin = s["financials"]
            fin["nonrecurring_usd_m"][-1] = fin["nonrecurring_usd_m"][-5] * (1 + (fin["revenue_yoy_pct"][-1] + 5) / 100)

        shared = self.page(fees_and_one_time)
        self.assertIn("，与非经常性收入一样快过总收入；", shared)
        self.assertIn("<b>资产型费用与非经常性收入都快过总收入</b>", shared)

    def test_the_record_and_lowest_fee_claims(self) -> None:
        def aum(delta):
            def edit(s):
                values = s["operating_metrics"]["aum_period_end_usd_b"]
                values[-1] = max(values[:-1]) + delta
            return edit

        def fee(value_of):
            def edit(s):
                values = s["operating_metrics"]["aum_basis_point_fee"]
                values[-1] = value_of(values)
            return edit

        self.assertIn("的 AUM 创 US$", self.page(aum(+1)))
        self.assertNotIn("新高", self.page(aum(-1)))
        low = self.page(fee(lambda v: min(x for x in v[:-1] if x is not None) - 0.01))
        first = self.s["operating_metrics"]["period_labels"][0]
        self.assertIn(f"为 {first} 以来最低；", low)
        self.assertNotIn("有披露以来", low)
        self.assertNotIn("以来最低", self.page(fee(lambda v: v[-2] + 0.01)))

    # ── the annual record ───────────────────────────────────────────────────
    def test_the_all_inside_claim(self) -> None:
        def inside(every):
            def edit(s):
                by_year = s["annual_guidance_history"]["items"]["operating_expense"]["by_year"]
                for index, block in enumerate(b for b in by_year.values() if b["actual"] is not None):
                    low, high, _ = block["guided"][-1]
                    block["actual"] = (low + high) / 2 if every or index else high + 10
            return edit

        years = len(settled_years(self.s))
        self.assertIn(f"指引 {years} 次全部落在区间内", self.page(inside(True)))
        some = self.page(inside(False))
        self.assertIn(f"指引 {years - 1} 次落在区间内", some)
        self.assertNotIn("全部落在区间内", some)

    def test_the_revision_chart_says_which_move_this_is(self) -> None:
        hist = self.s["annual_guidance_history"]
        year = str(max(hist["years"]))

        def ranges(*steps):
            """Rewrite the open year: release r moves every range by steps[r]."""
            def edit(s):
                h = s["annual_guidance_history"]
                count = len(steps)
                dates = [f"{year}-{m:02d}-20" for m in (1, 4, 7, 10)][:count]
                h["releases_by_year"][year] = dates
                for item in h["items"].values():
                    block = item["by_year"][year]
                    low, high, flag = block["guided"][0]
                    shift, guided = 0.0, []
                    for step in steps:
                        shift += step
                        guided.append([low + shift, high + shift, flag])
                    block["releases"], block["guided"] = list(dates), guided
                s["latest"]["release_date"] = dates[-1]
            return edit

        still = self.page(ranges(0, 0, 0))
        self.assertIn(f"公司本季维持 FY{year} 费用指引。", still)
        self.assertNotIn(f"FY{year} 指引三次发布后的净移动", still)
        first = self.page(ranges(0, 0, 10))
        self.assertIn(f"是 FY{year} 指引里本图五项第一次移动", first)
        self.assertIn(f"公司本季首次上调 FY{year} 费用指引", first)
        second = self.page(ranges(0, 10, 10))
        self.assertIn(f"FY{year} 指引第二次移动", second)
        self.assertIn(f"公司本季第二次上调 FY{year} 费用指引", second)
        held = self.page(ranges(0, 10, 0))
        self.assertIn(f"FY{year} 指引没有再动", held)
        self.assertIn(f"公司本季维持 FY{year} 费用指引。", held)
        down = self.page(ranges(0, 0, -10))
        self.assertIn(f"公司本季首次下调 FY{year} 费用指引", down)
        self.assertIn("营业费用中值下调 -", down)


if __name__ == "__main__":
    unittest.main()
