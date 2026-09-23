"""PM page: the reconciliations that license what the page publishes.

This page's first section settles FOUR guidance records rather than one -- the
full year on the reported basis and on the adjusted basis, and the next quarter
on whichever basis applied at the time. Most of these tests exist because the
four records are only worth putting beside each other if each leg is read on
its own basis: a pro-forma guidance scored against a group actual, or a fiscal
fourth quarter's EPS derived by subtraction, would produce a plausible number
and a wrong finding.

The page is rolled by editing `series/pm.json` alone (CLAUDE.md §9), so nothing
here pins a count the next quarter changes: tallies are recomputed from the
series and looked for on the page, the sentences that claim something about
the whole record are made true and then false (`PmRollTest`), and the page's
quarter is held to a separate reading of the release (`PmChecksTest`). What is
pinned is closed history -- the reported-basis quarterly era, the pre-2009
releases, 2016 -- which no roll can reopen.
"""

from __future__ import annotations

import collections
import copy
import datetime
import hashlib
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import pm  # noqa: E402
from build.all import ENTRIES, GROUPS, build_all, roster_payload  # noqa: E402
from build.board import cn_count, headroom  # noqa: E402


def js_payload(path: Path, marker: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{marker} = ", 1)[1].rstrip().rstrip(";")
    return json.loads(body)


def load() -> dict:
    return json.loads(pm.STAGING_PATH.read_text(encoding="utf-8"))


def text_of(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def composed(payload: dict) -> str:
    """The prose the builder composes; the audit tables are left out."""
    return text_of({key: value for key, value in payload.items() if key != "tables"})


def exhibits_of(payload: dict) -> dict:
    return {ex["ref"]: ex for section in payload["sections"] for ex in section["exhibits"] if "ref" in ex}


def quarter_label(year: int, number: int) -> str:
    return f"{year}Q{number}"


def next_quarter(label: str) -> str:
    year, number = pm.yq(label)
    return quarter_label(year + 1, 1) if number == 4 else quarter_label(year, number + 1)


def released_record(staging: dict) -> dict:
    """The annual record this quarter's release updated (a Q4 release opens the next year)."""
    released = staging["latest"]["release_date"]
    return next(r for r in staging["annual_guidance"]["records"]
                if r["vintages"] and r["vintages"][-1]["release_date"] == released)


class PmDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = load()
        cls.payload = pm.build_payload(cls.staging)
        cls.exhibits = exhibits_of(cls.payload)

    # ── the eight-quarter window ────────────────────────────────────────────
    def test_the_window_is_eight_quarters_and_complete(self) -> None:
        fin = self.staging["financials"]
        self.assertEqual(len(self.staging["periods"]), 8)
        for name, values in fin.items():
            self.assertEqual(len(values), 8, name)
            self.assertTrue(all(v is not None for v in values), name)

    def test_quarters_are_contiguous_calendar_labels(self) -> None:
        for periods in (self.staging["periods"], self.staging["long"]["periods"]):
            for earlier, later in zip(periods, periods[1:]):
                self.assertEqual(next_quarter(earlier), later)
        for period, label in zip(self.staging["long"]["periods"], self.staging["long"]["period_labels"]):
            self.assertEqual(pm.display(period), label)

    def test_the_window_is_the_tail_of_the_long_series(self) -> None:
        """The two windows must not disagree about an overlapping quarter."""
        long = self.staging["long"]
        self.assertEqual(long["periods"][-8:], self.staging["periods"])
        for key in ("net_revenues_usd_m", "gross_profit_usd_m", "operating_income_usd_m",
                    "gross_margin_pct", "operating_margin_pct"):
            self.assertEqual(long[key][-8:], self.staging["financials"][key], key)

    def test_margins_are_the_ratio_of_the_two_filed_lines(self) -> None:
        fin = self.staging["financials"]
        for index, period in enumerate(self.staging["periods"]):
            revenue = fin["net_revenues_usd_m"][index]
            self.assertAlmostEqual(fin["gross_profit_usd_m"][index] / revenue * 100,
                                   fin["gross_margin_pct"][index], places=2, msg=period)
            self.assertAlmostEqual(fin["operating_income_usd_m"][index] / revenue * 100,
                                   fin["operating_margin_pct"][index], places=2, msg=period)

    def test_the_two_copies_of_each_guided_quarters_eps_agree(self) -> None:
        """A settled quarterly guidance carries its actual, and the eight-quarter
        table carries the same quarter's EPS: two typed copies of one number."""
        fin = self.staging["financials"]
        for row in self.staging["quarterly_guidance"]:
            if row["guided_period"] not in self.staging["periods"] or row["basis"] == "pro_forma_adjusted":
                continue
            index = self.staging["periods"].index(row["guided_period"])
            key = "reported_diluted_eps_usd" if row["basis"] == "reported" else "adjusted_diluted_eps_usd"
            self.assertEqual(row["actual_eps"], fin[key][index], row["guided_period"])

    # ── the fiscal fourth quarter, which has no 10-Q ────────────────────────
    def test_the_four_quarters_of_a_year_sum_to_the_filed_year(self) -> None:
        """Q4 here is the filed year minus the filed nine months, so this is the
        identity that has to hold for the derivation to be worth publishing.
        Gross profit is on one basis per year, the one PMI adopted in 2026, for
        every year the recast 8-K of 2026-03-13 reprinted: 2023 22,298, 2024
        24,568 (the 10-K's old basis was 24,549), 2025 27,304. 2025Q3 and Q4
        were once the old basis while Q1 and Q2 were the new one, and 2023-2024
        stayed on the old one until the recast was taken in."""
        long = self.staging["long"]
        by = {key: dict(zip(long["periods"], long[key]))
              for key in ("net_revenues_usd_m", "operating_income_usd_m", "gross_profit_usd_m")}
        filed = {2023: (35174.0, 11556.0, 22298.0), 2024: (37878.0, 13402.0, 24568.0),
                 2025: (40648.0, 14892.0, 27304.0)}
        for year, totals in filed.items():
            quarters = [f"{year}Q{q}" for q in (1, 2, 3, 4)]
            for key, total in zip(("net_revenues_usd_m", "operating_income_usd_m", "gross_profit_usd_m"), totals):
                self.assertAlmostEqual(sum(by[key][q] for q in quarters), total, delta=0.01,
                                       msg=f"{year} {key}")
        annual = self.staging["annual"]
        for year, revenue in zip(annual["years"], annual["net_revenues_usd_m"]):
            quarters = [f"{year}Q{q}" for q in (1, 2, 3, 4)]
            self.assertAlmostEqual(sum(by["net_revenues_usd_m"][q] for q in quarters), revenue,
                                   delta=0.5, msg=str(year))
        self.assertIn("净收入四个季度相加等于全年，逐年核对无差", self.exhibits["EX_REV"]["note"])
        note = next(n for n in self.payload["notes"] if "四季相加逐项与" in n)
        self.assertIn(f"{min(filed)}–{max(filed)} 年的净收入、毛利、经营利润四季相加逐项与", note)
        # the series' own record of the printed years is the same three rows
        self.assertEqual({int(y): tuple(row[k] for k in ("net_revenues_usd_m", "operating_income_usd_m",
                                                          "gross_profit_usd_m"))
                          for y, row in long["filed_year_totals"]["years"].items()}, filed)

    def test_a_year_that_does_not_tie_is_named_not_smoothed(self) -> None:
        st = copy.deepcopy(self.staging)
        long = st["long"]
        long["gross_profit_usd_m"][long["periods"].index("2024Q2")] += 5
        note = next(n for n in pm.build_payload(st)["notes"] if "四季相加" in n)
        self.assertIn("2024 年的四季相加与", note)
        self.assertIn("有出入", note)
        self.assertIn("2023 年、2025 年的净收入", note)

    def test_the_gross_profit_seam_is_where_the_recast_begins(self) -> None:
        """The recast 8-K reprinted consolidated gross profit on the 2026 basis for
        each quarter it covers; before it the page is on the old basis."""
        long = self.staging["long"]
        recast = self.staging["segments"]["recast_filing"]
        first = pm.yq(recast["first"])[0]
        profit = dict(zip(long["periods"], long["gross_profit_usd_m"]))
        # four quarters the recast moved, against the old-basis values they replaced
        for quarter, old, new in (("2023Q1", 4981.0, 4987.0), ("2024Q1", 5598.0, 5604.0),
                                  ("2024Q4", 6283.0, 6288.0), ("2025Q3", 7358.0, 7361.0)):
            self.assertEqual(profit[quarter], new, quarter)
            self.assertNotEqual(profit[quarter], old, quarter)
        words = f"{first}–{pm.yq(recast['last'])[0]} 年的毛利取公司 {recast['date']} 按 2026 年新口径重印的各季数，" \
                f"{first - 1} 年及以前仍是原口径"
        self.assertIn(words, self.exhibits["EX_REV"]["note"])
        self.assertIn(words, " ".join(self.payload["notes"]))

    def test_a_fourth_quarter_eps_is_not_a_subtraction(self) -> None:
        """EPS is not additive, so a Q4 derived by subtraction would be wrong in
        a way no other identity on this page would notice. Q4 2024's reported
        EPS is negative and its adjusted EPS positive -- a subtraction cannot
        produce that pair. Checked while that quarter is in the window."""
        periods = self.staging["periods"]
        fin = self.staging["financials"]
        if "2024Q4" in periods:
            index = periods.index("2024Q4")
            self.assertLess(fin["reported_diluted_eps_usd"][index], 0)
            self.assertGreater(fin["adjusted_diluted_eps_usd"][index], 1.0)
        self.assertIn("第四季读自当期新闻稿的 EPS 调节表", " ".join(self.payload["notes"]))

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
        self.assertEqual(years, list(range(2009, years[-1] + 1)))
        self.assertIn("FY2008 不在记录内", " ".join(self.payload["notes"]))

    def test_the_floor_years_are_out_of_the_band_chart_and_in_the_table(self) -> None:
        """A floor has no upper bound; drawing it as a zero-width range would
        invent a ceiling the company never published."""
        banded, floors = pm.annual_records(self.staging)
        self.assertEqual([r["year"] for r in floors], [2019])
        band = self.exhibits["EX_FY_BAND"]
        self.assertNotIn("FY2019", band["xlabels"])
        self.assertEqual(band["break_label"], "2019 年只给下限，不在本图")
        self.assertIn("横轴从 FY2018 跳到 FY2020", band["note"])
        table = next(t for t in self.payload["tables"] if "只给下限" in t["title"])
        self.assertIn("FY2019", [row[0] for row in table["rows"]])
        self.assertTrue(any(row[2].startswith("至少") for row in table["rows"]))

    def test_the_reported_annual_record_is_two_sided_and_the_page_counts_it(self) -> None:
        """The page's headline: a record that misses on both sides."""
        banded, _ = pm.annual_records(self.staging)
        rows = [(r["actual_reported_eps"], r["last_guided"]["low"], r["last_guided"]["high"])
                for r in banded]
        n, above, inside, below = pm.tally(rows)
        self.assertGreater(above, 0)
        self.assertGreater(below, 0)
        self.assertIn(f"{n} 个完整年度里 {above} 年高于上限、{inside} 年落在区间内、{below} 年跌破下限",
                      self.payload["brief"])
        self.assertIn(f"{n} 个已完结年里 {above} 年超出上限、{inside} 年落在区间内、{below} 年跌破下限",
                      self.exhibits["EX_FY_BAND"]["title"])
        self.assertIn(f"报告口径那条自 {banded[0]['year']} 年起有 {n} 个完整年度",
                      self.exhibits["EX_ADJ_BAND"]["note"])

    def test_the_adjusted_annual_record_is_the_same_years_read_differently(self) -> None:
        rows = [(actual, low, high) for _, low, high, actual in pm.adjusted_rows(self.staging)]
        n, above, inside, below = pm.tally(rows)
        banded, _ = pm.annual_records(self.staging)
        self.assertLess(n, len([r for r in banded if r["actual_reported_eps"] is not None]))
        title = self.exhibits["EX_ADJ_BAND"]["title"]
        if above and below:
            self.assertIn(f"{n} 个已完结年里 {above} 年超出上限、{inside} 年落在区间内、{below} 年跌破下限", title)
        else:
            self.assertIn(f"{n} 个已完结年", title)

    def test_the_worst_reported_year_is_the_one_the_exclusion_clause_explains(self) -> None:
        """FY2024: reported EPS US$4.52 against a final guidance of
        US$6.20-6.26, and the adjusted line for the same year cleared its
        range. If those two ever stop disagreeing the page's argument is gone."""
        record = next(r for r in self.staging["annual_guidance"]["records"] if r["year"] == 2024)
        self.assertEqual(record["actual_reported_eps"], 4.52)
        self.assertLess(record["actual_reported_eps"], record["last_guided"]["low"])
        adjusted = [v for v in record["vintages"] if v.get("adj_low") is not None][-1]
        actual = self.staging["annual_guidance"]["annual_adjusted_eps_actual"]["2024"]
        self.assertGreater(actual, adjusted["adj_high"])

    def test_the_2020_withdrawal_is_recorded_rather_than_smoothed(self) -> None:
        record = next(r for r in self.staging["annual_guidance"]["records"] if r["year"] == 2020)
        self.assertEqual(record["withdrawn"], ["2020-04-21"])
        withdrawn = [d for r in self.staging["annual_guidance"]["records"] for d in r["withdrawn"]]
        notes = " ".join(self.payload["notes"])
        self.assertIn("撤回", notes)
        self.assertEqual("这是记录里唯一一次撤回" in notes, len(withdrawn) == 1)

    def test_the_exclusion_clause_is_counted_release_by_release(self) -> None:
        """The page said 54 of 56, with 2008-10-22 and 2020-04-21 as the
        exceptions. Read one by one, the three-part clause first appears on
        2009-04-23: the four releases before it name acquisitions at most, and
        the 2020-04-21 release -- which withdrew the full-year forecast -- carries
        the clause on the forecasts it gave instead. The census covers
        2008-04 to 2022-02, after which the clause gave way to an itemised
        table, so it is closed history and pinned."""
        hist = self.staging["annual_guidance"]
        census = hist["exclusion_clause_census"]
        releases, without = census["releases"], census["without_clause"]
        self.assertEqual(releases, sorted(set(releases)))
        self.assertEqual((len(releases), tuple(without)), (56, pm.PRE_CLAUSE))
        self.assertNotIn("2020-04-21", without)
        # every full-year release inside the census window is in the census
        vintages = {v["release_date"] for r in hist["records"] for v in r["vintages"]
                    if v["release_date"] <= releases[-1]}
        self.assertTrue(vintages <= set(releases))
        counted = f"{len(releases)} 份新闻稿里有 {len(releases) - len(without)} 份写明该预测不含"
        for text in (self.exhibits["EX_FY_BAND"]["note"], self.payload["notes"][5]):
            self.assertIn(counted, text)
            self.assertIn("2020-04-21 那份撤回了全年预测", text)
            self.assertIn("点名排除的最多只有并购", text)
            self.assertNotIn("未预料到的", text)

    # ── the quarterly guidance record ───────────────────────────────────────
    def test_no_quarter_is_scored_across_a_basis_change(self) -> None:
        """A pro-forma guidance scored against the group actual printed beside
        it in the same release is the plausible-and-wrong version of this
        chart."""
        for row in self.staging["quarterly_guidance"]:
            self.assertIn(row["basis"], {"reported", "adjusted", "pro_forma_adjusted"})
        pro_forma = [r for r in self.staging["quarterly_guidance"] if r["basis"] == "pro_forma_adjusted"]
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

    def test_the_fourth_quarter_gap_is_stated_while_it_holds(self) -> None:
        """A record that silently skips every Q4 measures its own filter, so the
        gap is stated on the chart -- and only while the record says so."""
        guided = {r["guided_period"] for r in self.staging["quarterly_guidance"]}
        fourth = sorted(p for p in guided if p.endswith("Q4"))
        note = self.exhibits["EX_Q_BAND"]["note"]
        self.assertEqual("从不指引第四季" in note, len(fourth) == 1)
        if len(fourth) == 1:
            self.assertIn(f"唯一的例外是 {pm.cn_quarter(fourth[0], '季')}", note)

    def test_the_adjusted_quarter_tally_is_the_one_the_page_prints(self) -> None:
        rows = [(r["actual_eps"], r["low"], r["high"])
                for r in self.staging["quarterly_guidance"] if r["basis"] != "reported"]
        finished, above, inside, below = pm.tally(rows)
        note = self.exhibits["EX_Q_DEV"]["note"]
        self.assertEqual("全部高于上限" in note, above == finished)
        self.assertEqual(f"{finished} 季<b>全部</b>高于上限" in self.payload["brief"], above == finished)

    def test_the_quarterly_band_names_every_basis_on_each_side_of_its_break(self) -> None:
        """The break sits at the first non-reported quarter (2022Q2, pro forma);
        the page said everything to its right was adjusted, but 2023Q1 was
        guided on reported EPS again (US$1.28-1.33, 2023-02-09)."""
        rows = self.staging["quarterly_guidance"]
        first = next(i for i, r in enumerate(rows) if r["basis"] != "reported")
        note = self.exhibits["EX_Q_BAND"]["note"]
        back = [r for r in rows[first:] if r["basis"] == "reported"]
        self.assertEqual([r["guided_period"] for r in back], ["2023Q1"])
        for row in back:
            self.assertIn(pm.cn_quarter(row["guided_period"], "季"), note.split("右段", 1)[1])
        self.assertIn(f"那{cn_count(len(back))}格又回到报告口径", note)

    def test_the_reported_era_has_one_miss_and_the_page_names_it(self) -> None:
        """The quarterly guidance moved to the adjusted basis in 2022; the
        reported-basis quarters are a closed record and pinned."""
        reported = [r for r in self.staging["quarterly_guidance"] if r["basis"] == "reported"]
        misses = [r["guided_period"] for r in reported if r["actual_eps"] < r["low"]]
        self.assertEqual(misses, ["2021Q2"])
        self.assertIn("唯一一次跌破下限是 2021 年第二季", self.exhibits["EX_Q_DEV"]["note"])

    def test_the_guidance_timing_is_stated_rather_than_assumed(self) -> None:
        """PMI publishes each quarter's outlook with the previous quarter's
        results, so the range is already under way when it is guided. The window
        is recomputed here from the release dates rather than read back out of
        the caption, so a caption that drifts from the record goes red."""
        starts = {"1": "-01-01", "2": "-04-01", "3": "-07-01", "4": "-10-01"}
        days = []
        for row in self.staging["quarterly_guidance"]:
            period = row["guided_period"]
            start = datetime.date.fromisoformat(period[:4] + starts[period[-1]])
            days.append((datetime.date.fromisoformat(row["release_date"]) - start).days)
        self.assertGreater(min(days), 0, "a guidance published before its quarter began")
        self.assertIn(f"开始后 {min(days)}–{max(days)} 天", self.exhibits["EX_Q_BAND"]["note"])

    # ── the currency decomposition ──────────────────────────────────────────
    def test_the_currency_chart_skips_the_year_whose_two_rows_were_two_bases(self) -> None:
        """FY2022's dollar row was the group and its ex-currency row the pro
        forma, so subtracting one from the other compares two companies."""
        chart = self.exhibits["EX_FX"]
        self.assertNotIn("FY2022", chart["xlabels"])
        self.assertIn("FY2022 不在图上", chart["note"])

    def test_the_currency_directions_are_counted(self) -> None:
        """The page said the two rows "often move in opposite directions"; in
        the record that happens in one year of five."""
        moves = pm.currency_moves(self.staging)
        opposite = [y for y, d, x, _ in moves if d * x < 0]
        note = self.exhibits["EX_FX"]["note"]
        self.assertEqual("经常朝相反方向走" in note, len(opposite) * 2 > len(moves))
        same = [y for y, d, x, _ in moves if d * x > 0]
        self.assertEqual("更常见的是同向" in note, bool(opposite) and len(opposite) * 2 <= len(moves)
                         and len(same) * 2 > len(moves))
        for year in opposite:
            self.assertIn(f"FY{year}（美元口径", note)
        self.assertEqual([f"FY{y}" for y, _, _, _ in moves], self.exhibits["EX_FX"]["xlabels"])

    def test_the_open_year_ex_currency_band_is_called_unchanged_only_while_it_is(self) -> None:
        year, _, _, vintages = pm.currency_moves(self.staging)[-1]
        record = next(r for r in self.staging["annual_guidance"]["records"] if r["year"] == year)
        bands = {(v["xfx_low"], v["xfx_high"]) for v in vintages}
        unchanged = record["actual_reported_eps"] is None and len(bands) == 1
        note = self.exhibits["EX_FX"]["note"]
        self.assertEqual("逐字未动" in note, unchanged)
        if unchanged:
            self.assertIn(f"FY{year} 到目前为止剔除汇率的区间{cn_count(len(vintages))}次发布", note)

    # ── the quarter's own arithmetic ────────────────────────────────────────
    def test_the_revenue_bridge_walks_from_base_to_end(self) -> None:
        bridge = self.staging["revenue_bridge"]
        for period in bridge["periods"]:
            block = bridge[period]
            for index, column in enumerate(bridge["columns"]):
                walk = (block["base"][index] + block["price"][index]
                        + block["volume_mix_other"][index] + block["acq_div"][index]
                        + block["currency"][index])
                self.assertAlmostEqual(walk, block["end"][index], delta=1.0, msg=f"{period} {column}")

    def test_the_bridge_ends_where_the_filed_quarter_does(self) -> None:
        bridge = self.staging["revenue_bridge"]
        fin = self.staging["financials"]
        long = self.staging["long"]
        self.assertEqual(bridge["periods"][-1], self.staging["periods"][-1])
        for period in bridge["periods"]:
            index = self.staging["periods"].index(period)
            self.assertAlmostEqual(bridge[period]["end"][0], fin["net_revenues_usd_m"][index],
                                   delta=1.0, msg=period)
            ago = long["periods"].index(quarter_label(pm.yq(period)[0] - 1, pm.yq(period)[1]))
            self.assertAlmostEqual(bridge[period]["base"][0], long["net_revenues_usd_m"][ago],
                                   delta=1.0, msg=period)

    def test_the_bridge_caption_describes_each_segment_from_its_own_column(self) -> None:
        """The page said the U.S. had price and volume both negative; that
        quarter its price was +US$15M."""
        bridge = self.staging["revenue_bridge"]
        latest = bridge[bridge["periods"][-1]]
        note = self.exhibits["EX_BRIDGE"]["note"]
        for index, name in ((1, "国际无烟"), (2, "国际组合烟草"), (3, "美国")):
            shape = pm.segment_shape(name, latest, index, first=(index == 1))
            self.assertIn(shape, note)
            if latest["price"][index] > 0:
                self.assertNotIn("价格是负的", shape)
                self.assertNotIn("价格和量与结构都是负的", shape)
        self.assertNotIn("两项都是负的", note)

    def test_the_three_segments_sum_to_the_filed_quarter(self) -> None:
        seg = self.staging["segments"]
        long = self.staging["long"]
        revenue = dict(zip(long["periods"], long["net_revenues_usd_m"]))
        profit = dict(zip(long["periods"], long["gross_profit_usd_m"]))
        for index, period in enumerate(seg["periods"]):
            self.assertAlmostEqual(sum(seg["net_revenues_usd_m"][key][index] for key in pm.SEG_KEYS),
                                   revenue[period], delta=1.0, msg=period)
            self.assertAlmostEqual(sum(seg["gross_profit_usd_m"][key][index] for key in pm.SEG_KEYS),
                                   profit[period], delta=1.0, msg=period)

    def test_the_segment_series_says_what_exists_and_what_it_took_in(self) -> None:
        """PMI reorganised its reportable segments in 2026Q1. The page once said the
        history was never restated into a filing and "there will be no more";
        the 8-K of 2026-03-13 recasts 2023-2025 on the new segments, and the page
        now draws them. And the segments it replaced were four geographic ones,
        not six."""
        seg = self.staging["segments"]
        recast = seg["recast_filing"]
        self.assertEqual(seg["periods"][0], recast["first"])
        self.assertEqual(seg["periods"][-1], self.staging["periods"][-1])
        for earlier, later in zip(seg["periods"], seg["periods"][1:]):
            self.assertEqual(next_quarter(earlier), later)
        chart = self.exhibits["EX_SEG_REV"]
        notes = " ".join(self.payload["notes"])
        self.assertEqual(len(chart["xlabels"]), len(seg["periods"]))
        self.assertNotIn("不会再多", chart["note"])
        self.assertNotIn("尚未接入", chart["note"] + notes)
        self.assertNotIn("只画了", chart["note"] + notes)
        self.assertNotIn("六个地理分部", chart["note"] + notes)
        self.assertIn(recast["date"], chart["note"])
        self.assertIn(recast["accession"], chart["src_extra"])
        self.assertIn(recast["accession"], notes)
        self.assertIn(f"{cn_count(len(seg['periods']))}个季度", chart["note"])
        self.assertIn(pm.segment_releases(self.staging), chart["src_extra"])
        # a label on each of 3 x 14 bars is a hairbrush
        self.assertFalse(chart["bar_labels"])

    def test_every_recast_cell_is_sourced_and_the_three_segments_foot(self) -> None:
        """Each quarter taken from the recast names its accession, exhibit and the
        tables each figure was read from; the new-basis quarters name their release."""
        seg = self.staging["segments"]
        recast = seg["recast_filing"]
        for period in seg["periods"]:
            with self.subTest(period=period):
                cell = seg["cell_sources"][period]
                if pm.yq(recast["first"]) <= pm.yq(period) <= pm.yq(recast["last"]):
                    self.assertEqual(cell["accession"], recast["accession"])
                    self.assertEqual(cell["exhibit"], "EX-99.1" if period.startswith("2025") else "EX-99.2")
                    for key in ("net_revenues_usd_m", "gross_profit_usd_m", "adjusted_gross_margin_pct"):
                        self.assertIn("Schedule", cell[key])
                else:
                    self.assertIn("EX-99.1", cell["source"])
        # four figures read straight from the recast, independently of the series
        gm = seg["adjusted_gross_margin_pct"]
        at = {p: i for i, p in enumerate(seg["periods"])}
        self.assertEqual(seg["net_revenues_usd_m"]["us"][at["2023Q1"]], 509)
        self.assertEqual(seg["gross_profit_usd_m"]["international_smoke_free"][at["2024Q4"]], 2058)
        self.assertEqual(gm["us"][at["2025Q3"]], 63.7)
        self.assertEqual(gm["pmi"][at["2023Q4"]], 61.9)
        # the adjusted OI line is not in the recast: holes, not zeros
        self.assertIsNone(seg["adjusted_oi_margin_pct"][at["2024Q4"]])
        self.assertIn("adjusted_oi_margin", recast["not_printed"])

    def test_the_us_margin_card_follows_the_year_ago_comparison(self) -> None:
        seg = self.staging["segments"]
        us = seg["adjusted_gross_margin_pct"]["us"]
        ago = pm.year_ago_index(seg["periods"], len(seg["periods"]) - 1)
        self.assertEqual("美国分部的单位经济性还在恶化" in self.payload["brief"], us[-1] < us[ago])
        self.assertIn(f"同比 {us[-1] - us[ago]:+.1f}pp", self.payload["headline"])

    def test_the_missing_offtake_reading_is_a_hole_not_a_zero(self) -> None:
        """The company described a quarter in words; filling a zero would turn a
        phrase into a number a model could use."""
        zyn = self.staging["zyn"]
        chart = self.exhibits["EX_ZYN"]
        self.assertEqual(zyn["periods"][-1], self.staging["periods"][-1])
        self.assertEqual(len(zyn["offtake_yoy_pct"]), len(zyn["periods"]))
        self.assertEqual(len(zyn["shipment_words"]), len(zyn["periods"]))
        self.assertEqual(len(zyn["offtake_words"]), len(zyn["periods"]))
        for value, words in zip(zyn["offtake_yoy_pct"], zyn["offtake_words"]):
            self.assertEqual(value is None, bool(words))
        if zyn["offtake_yoy_pct"][-1] is None:
            self.assertIn(f"「{zyn['offtake_words'][-1]}」", chart["note"])
            self.assertIn(zyn["period_labels"][-1], chart["annot"])
        else:
            self.assertNotIn("annot", chart)

    # ── the smoke-free transition ───────────────────────────────────────────
    def test_the_product_categories_sum_to_filed_net_revenues_every_year(self) -> None:
        annual = self.staging["annual"]
        for index, year in enumerate(annual["years"]):
            total = annual["combustible_usd_m"][index] + annual["smoke_free_usd_m"][index]
            self.assertAlmostEqual(total, annual["net_revenues_usd_m"][index], delta=1.0, msg=str(year))

    def test_the_smoke_free_share_is_the_ratio_of_two_filed_lines(self) -> None:
        annual = self.staging["annual"]
        for index, year in enumerate(annual["years"]):
            share = annual["smoke_free_usd_m"][index] / annual["net_revenues_usd_m"][index] * 100
            self.assertAlmostEqual(share, annual["smoke_free_share_pct"][index], places=3, msg=str(year))

    def test_the_transition_is_additive_not_substitutional(self) -> None:
        """The page says combustible revenue barely moved while smoke-free grew;
        the words are printed only while that is true."""
        annual = self.staging["annual"]
        combustible = annual["combustible_usd_m"]
        flat = abs(combustible[-1] / combustible[0] - 1) < 0.10
        note = self.exhibits["EX_SF"]["note"]
        self.assertEqual("几乎没动" in note, flat)
        self.assertEqual("转型是加出来的" in note, flat)
        self.assertGreater(annual["smoke_free_usd_m"][-1] / annual["smoke_free_usd_m"][0], 20)

    def test_the_excise_tax_story_is_a_label_trap_not_a_basis_change(self) -> None:
        """The reason this series used to stop at 2017Q1 was not true.

        The old note said PMI reported revenue including excise taxes "before
        2016" and switched afterwards, citing 2015's US$73.9B against 2016's
        US$26.7B. Those are two different measures of two different years:
        73.9B is 2015 gross, 26.7B is 2016 net. PMI's income statement carries
        both lines in both years -- 2015 net is 73,908 - 47,114 = 26,794, right
        next to 2016's 26,685. The page's notes kept repeating the old claim
        until this migration.
        """
        long = self.staging["long"]
        self.assertEqual(long["periods"][0], "2016Q1")
        self.assertEqual(sum(long["net_revenues_usd_m"][:4]), 26685.0)
        gross_2015, excise_2015 = 73908.0, 47114.0
        self.assertAlmostEqual(gross_2015 - excise_2015, 26794.0, places=6)
        self.assertLess(abs(26794.0 - sum(long["net_revenues_usd_m"][:4])), 1000.0,
                        "2015 net and 2016 net are the same order of magnitude; "
                        "the cliff only appears if you compare gross to net")
        # A year-sum check alone cannot see a compensating swap between two
        # quarters, so the four quarters are pinned against a second reading:
        # the earnings-release Schedule 1, whose fourth quarter is printed as a
        # standalone column rather than derived by subtraction.
        route_b = long["route_b_2016"]
        self.assertEqual(route_b["quarters"], ["2016Q1", "2016Q2", "2016Q3", "2016Q4"])
        self.assertEqual(long["net_revenues_usd_m"][:4], route_b["net_revenues_usd_m"])
        self.assertEqual(long["gross_profit_usd_m"][:4], route_b["gross_profit_usd_m"])
        self.assertEqual(len(route_b["accessions"]), 4)
        for index in range(4):
            self.assertAlmostEqual(
                long["gross_profit_usd_m"][index] / long["net_revenues_usd_m"][index] * 100,
                long["gross_margin_pct"][index], places=2, msg=long["periods"][index])
        self.assertIn("那句话是错的", self.exhibits["EX_REV"]["note"])
        notes = " ".join(self.payload["notes"])
        self.assertNotIn("不向前回补", notes)
        self.assertIn(f"长期季度序列自 {pm.cn_quarter(long['periods'][0])}起", notes)

    def test_the_2016_operating_margin_is_a_hole_and_says_why(self) -> None:
        """Read, then deliberately not published -- and the two are different.

        All four 2016 operating-income figures exist and were read twice. They
        are still not on the chart, because PMI adopted ASU 2017-07
        retrospectively on 2018-01-01 and restated 2017 by quarter but never
        restated 2016 by quarter -- so the 2016Q4/2017Q1 seam would carry a step
        that is purely an accounting-standard change.
        """
        long = self.staging["long"]
        margin = long["operating_margin_pct"]
        income = long["operating_income_usd_m"]
        self.assertEqual(margin[:4], [None] * 4)
        self.assertEqual(income[:4], [None] * 4)
        self.assertTrue(all(value is not None for value in margin[4:]))
        for key in ("net_revenues_usd_m", "gross_profit_usd_m", "gross_margin_pct"):
            self.assertTrue(all(value is not None for value in long[key]), key)
        self.assertIn("ASU 2017-07", long["operating_income_hole_2016"])
        chart = self.exhibits["EX_MARGIN"]
        gross_line = next(series for series in chart["series"] if series["name"] == "毛利率")
        margin_line = next(series for series in chart["series"] if "经营利润率" in series["name"])
        self.assertEqual(len(gross_line["values"]), len(chart["xlabels"]))
        self.assertEqual(len(margin_line["values"]), len(chart["xlabels"]))
        reported = sum(1 for value in margin_line["values"] if value is not None)
        self.assertEqual(len(chart["xlabels"]) - reported, 4)
        self.assertIn("这条线的左端比毛利率短四格", chart["note"])

    def test_the_long_window_is_counted_where_it_is_described(self) -> None:
        """The section description said 38 quarters while its charts drew 42."""
        n = len(self.staging["long"]["periods"])
        self.assertIn(f"{n} 个季度的收入", self.payload["sections"][3]["description"])
        self.assertEqual(len(self.exhibits["EX_REV"]["xlabels"]), n)
        self.assertTrue(self.exhibits["EX_REV"]["title"].startswith(f"{n} 个季度的净收入"))

    def test_the_seasonality_sentence_is_counted(self) -> None:
        """The page said "every year Q1 is the low and Q2-Q3 the high"; 2020's
        low was Q2 and the two highest quarters are usually Q3 and Q4."""
        long = self.staging["long"]
        by = dict(zip(long["periods"], long["net_revenues_usd_m"]))
        years = [y for y in self.staging["annual"]["years"] if all(f"{y}Q{q}" in by for q in (1, 2, 3, 4))]
        q1_low = [y for y in years if min(range(4), key=lambda i: by[f"{y}Q{i + 1}"]) == 0]
        note = self.exhibits["EX_REV"]["note"]
        seasonal = note.split("季节性明显", 1)[1]
        self.assertIn(f"{cn_count(len(years))}年里有{cn_count(len(q1_low))}年第一季是低点", seasonal)
        for year in sorted(set(years) - set(q1_low)):
            self.assertIn(f"{year} 年", seasonal)
        self.assertNotIn("每年第一季是低点", note)

    # ── thresholds, exhibits, publication ───────────────────────────────────
    def test_every_quantified_threshold_has_a_headroom_bar(self) -> None:
        _, entries, worded = pm.kpi_entries(self.staging)
        bar = self.payload["sections"][2]["exhibits"][0]
        self.assertEqual(bar["xlabels"], [entry["metric"] for entry in entries])
        for entry, value in zip(entries, bar["values"]):
            self.assertAlmostEqual(headroom(entry["direction"], entry["threshold"], entry["current"]),
                                   value, places=1, msg=entry["metric"])
        for entry in worded:
            self.assertNotIn(entry["metric"], bar["xlabels"])
        for entry in self.staging["next_kpi"]["quantified"]:
            self.assertNotIn("current", entry, "a typed current value goes stale with the roll")

    def test_threshold_current_values_are_measured_from_the_series(self) -> None:
        """Each bar reads the quarter's own figure. The ZYN offtake line used to be
        measured at the last quarter that printed a figure (Q1's 10%) and drawn as
        25% on the safe side, while the quarter's own reading was a sentence."""
        _, entries, worded = pm.kpi_entries(self.staging)
        seg, printed = self.staging["segments"], self.staging["quarter_printed"]
        expected = {
            "segment_gm_us": seg["adjusted_gross_margin_pct"]["us"][-1],
            "segment_gm_isf": seg["adjusted_gross_margin_pct"]["international_smoke_free"][-1],
            "zyn_share": printed["zyn_retail_value_share_pct"],
            "isf_organic_growth": printed["isf_organic_revenue_growth_pct"],
            "isf_gp_lead": round(printed["isf_organic_gross_profit_growth_pct"]
                                 - printed["isf_organic_revenue_growth_pct"], 1),
            "organic_oi_growth": printed["organic_operating_income_growth_pct"],
            "leverage": self.staging["leverage"]["net_debt_to_adjusted_ebitda"][-1],
        }
        for entry in entries:
            self.assertEqual(entry["current"], expected[entry["measure"]], entry["metric"])
        words_only = self.staging["zyn"]["offtake_yoy_pct"][-1] is None
        self.assertEqual([e["measure"] for e in worded], ["zyn_offtake"] if words_only else [])
        self.assertEqual("zyn_offtake" in [e["measure"] for e in entries], not words_only)

    def test_the_capex_contrast_reads_the_shared_table(self) -> None:
        """The cross-page table's four-cloud total is a ratio, so it "grew to"
        N times; the page said "grew by"."""
        count, ratio = pm.hyperscaler_growth()
        note = self.exhibits["EX_CASH"]["note"]
        self.assertIn(f"{cn_count(count)}个季度里它们合计增长到 {ratio:.1f} 倍", note)
        self.assertNotIn("增长了", note)

    def test_threshold_source_lines_name_the_releases_the_lines_came_from(self) -> None:
        """A segment margin line starts in the recast 8-K and says so before it
        names the releases; the ZYN line is each quarter's own release; the
        leverage line names both exhibits its schedule lived in; the second half
        of the year is a 10-K less a 10-Q."""
        charts = {ex["title"].split("：")[0]: ex for ex in self.payload["sections"][2]["exhibits"][1:]}
        own = [p for p in self.staging["segments"]["periods"] if pm.yq(p) >= pm.yq(pm.NEW_SEGMENTS_FROM)]
        years = sorted({pm.yq(p)[0] for p in own})
        span = str(years[0]) if len(years) == 1 else f"{years[0]}–{years[-1]}"
        recast = self.staging["segments"]["recast_filing"]
        recast_years = f"{pm.yq(recast['first'])[0]}–{pm.yq(recast['last'])[0]}"
        for name in ("美国分部调整后毛利率", "国际无烟分部调整后毛利率"):
            src = charts[name]["src_extra"]
            self.assertTrue(src.startswith(f"{recast_years} 年各季取自 {recast['date']}"), name)
            self.assertIn(recast["accession"], src)
            self.assertIn(f"；{span} 年各季业绩 8-K", src)
        zyn = charts["美国 ZYN 零售出货同比"]["src_extra"]
        self.assertTrue(zyn.startswith("各季业绩 8-K EX-99.1"))
        self.assertNotIn(recast["accession"], zyn)
        leverage = charts["净债务 / 调整后 EBITDA"]["src_extra"]
        self.assertIn("EX-99.1", leverage)
        self.assertIn("EX-99.2", leverage)
        second_half = charts["下半年经营现金流"]["src_extra"]
        self.assertIn("10-K", second_half)
        self.assertIn("10-Q", second_half)

    def test_what_the_page_refuses_to_plot_is_named(self) -> None:
        kpi = self.staging["next_kpi"]
        overview = self.payload["sections"][2]["exhibits"][0]
        excluded = pm.not_tracked_text(kpi)
        self.assertIn(excluded, overview["note"])
        for item in kpi["not_tracked"]:
            self.assertIn(item["name"], excluded)
        for item in kpi["awaiting"] + kpi["unmeasurable"]:
            self.assertIn(item["metric"], overview["note"])
        self.assertIn(f"不接入的{cn_count(len(kpi['not_tracked']))}条", self.payload["sections"][2]["description"])
        # PMI prints the net debt to adjusted EBITDA ratio every quarter, and the
        # ZYN retail value share is printed in the earnings presentation: the page
        # used to call the first annual-only and the second call-only.
        text = text_of(self.payload)
        self.assertNotIn("只按年披露", text)
        self.assertNotIn("只出现在业绩电话会上", text)
        # the notes list the same items, from the same stamped block
        listed = next(n for n in self.payload["notes"] if n.startswith("本页已知未接入："))
        for item in kpi["not_tracked"]:
            self.assertIn(item.get("note", item["name"]), listed)

    def test_no_market_expectation_is_published(self) -> None:
        self.assertNotIn("market_expectation", self.staging)
        text = text_of(self.payload)
        self.assertNotIn("市场预期", text)
        self.assertNotIn("一致预期", text.replace("本页不发布市场一致预期", ""))

    def test_exhibits_are_numbered_in_render_order_and_refs_resolve(self) -> None:
        numbers = [ex["n"] for section in self.payload["sections"] for ex in section["exhibits"]]
        self.assertEqual(numbers, list(range(2, 2 + len(numbers))))
        self.assertNotRegex(text_of(self.payload), r"\{EX_[A-Z_]+\}")
        self.assertIn(f"调整后口径见 Exhibit {self.exhibits['EX_ADJ_BAND']['n']}",
                      self.exhibits["EX_FY_BAND"]["note"])
        if pm.next_quarter_guidance(self.staging) is not None:
            self.assertIn(f"Exhibit {self.exhibits['EX_Q_BAND']['n']} 上",
                          self.payload["sections"][2]["exhibits"][0]["note"])

    def test_tables_are_numbered_after_the_exhibits(self) -> None:
        last = max(ex["n"] for section in self.payload["sections"] for ex in section["exhibits"])
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
            self.assertEqual(set(table), {"n", "title", "headers", "rows"}, table["title"][:40])

    def test_the_guidance_block_has_the_shape_the_renderer_reads(self) -> None:
        guidance = self.payload["guidance"]
        self.assertEqual(set(guidance), {"title", "headers", "rows", "note"})
        for row in guidance["rows"]:
            self.assertEqual(len(row), len(guidance["headers"]))

    def test_the_guidance_block_is_the_record_and_the_release(self) -> None:
        """The EPS rows are the record's last two vintages; the rest is the
        stamped block. The capital-return row used to promise dividend
        increases the release never mentioned."""
        guidance = self.payload["guidance"]
        record = released_record(self.staging)
        now, before = record["vintages"][-1], record["vintages"][-2]
        self.assertIn(now["release_date"], guidance["title"])
        self.assertIn(before["release_date"], guidance["headers"][2])
        y = record["year"]
        rows = {row[0]: row for row in guidance["rows"]}
        for label, key in ((f"{y} 全年报告口径摊薄 EPS", ""), (f"{y} 全年调整后摊薄 EPS", "adj_"),
                           (f"{y} 全年调整后摊薄 EPS（剔除汇率）", "xfx_")):
            self.assertEqual(rows[label][1], f"${now[key + 'low']:.2f} – ${now[key + 'high']:.2f}")
            self.assertEqual(rows[label][2], f"${before[key + 'low']:.2f} – ${before[key + 'high']:.2f}")
            same = (now[key + "low"], now[key + "high"]) == (before[key + "low"], before[key + "high"])
            self.assertEqual(rows[label][3] == "逐字未变", same)
        upcoming = pm.next_quarter_guidance(self.staging)
        if upcoming is not None:
            self.assertEqual(guidance["rows"][0][1], f"${upcoming['low']:.2f} – ${upcoming['high']:.2f}")
        self.assertNotIn("股息", " ".join(" ".join(row) for row in guidance["rows"]))

    def test_no_per_share_series_is_plotted_below_the_guidance_section(self) -> None:
        """PMI's EPS is only comparable inside one adjustment basis, which the
        guidance charts handle explicitly. A per-share line drawn anywhere else
        would splice reported and adjusted quarters into one series."""
        for section in self.payload["sections"][1:]:
            for exhibit in section["exhibits"]:
                self.assertNotIn("每股", exhibit["title"], exhibit["title"])

    def test_the_published_payload_matches_a_fresh_build(self) -> None:
        self.assertEqual(js_payload(ROOT / "data" / "pm.js", "window.DASH"), self.payload)

    def test_the_page_declares_the_calendar_convention_in_its_subtitle(self) -> None:
        self.assertIn("自然年财年", self.payload["subtitle"])

    def test_the_notes_say_what_the_two_bases_are(self) -> None:
        notes = " ".join(self.payload["notes"])
        self.assertIn("排除条款", self.exhibits["EX_FY_BAND"]["note"])
        self.assertIn("下季指引的口径在记录中期发生变化", notes)
        released = self.staging["latest"]["release_date"]
        self.assertIn(f"以及 {int(released[:4])} 年 {int(released[5:7])} 月 {int(released[8:])} 日申报之后", notes)

    def test_sources_are_official_http_links(self) -> None:
        allowed_hosts = {"www.sec.gov", "www.pmi.com"}
        for source in self.payload["source_links"]:
            url = source["url"]
            self.assertTrue(url.startswith("https://"), url)
            self.assertIn(url.split("/")[2], allowed_hosts)
            if "browse-edgar" in url:
                # the query without dateb/owner/count answers 503 File Unavailable
                self.assertIn("&count=", url)

    def test_the_source_link_is_this_quarters_release(self) -> None:
        name, url, report = pm.release_source(self.staging)
        self.assertEqual(self.payload["source_url"], url)
        self.assertIn(f'href="{url}"', self.payload["source"])
        self.assertIn(report, self.payload["source"])
        accession = re.search(r"\d{10}-\d{2}-\d{6}", self.staging["_checks"]["source"]).group(0)
        self.assertIn(accession.replace("-", ""), url)

    def test_the_roster_carries_pm_with_the_payload_s_own_labels(self) -> None:
        roster = roster_payload(build_all())
        entry = next(item for item in roster["items"] if item["slug"] == "pm")
        self.assertEqual(entry["latest_label"], self.payload["latest"]["disclosed_period_label"])
        self.assertEqual(entry["release_date"], self.payload["latest"]["release_date"])
        self.assertEqual(entry["group"], self.payload["company"]["group"])
        self.assertIn(entry["group"], {group["key"] for group in roster["groups"]})

    def test_the_entry_group_exists_and_sits_where_its_order_says(self) -> None:
        keys = [group["key"] for group in GROUPS]
        self.assertIn(self.payload["company"]["group"], keys)
        orders = [group["order"] for group in GROUPS]
        self.assertEqual(orders, sorted(orders))
        entry = next(e for e in ENTRIES if e["slug"] == "pm")
        self.assertEqual(entry["group"], self.payload["company"]["group"])

    def test_the_shell_links_the_payload_by_content_hash(self) -> None:
        shell = (ROOT / "pm" / "index.html").read_text(encoding="utf-8")
        sources = re.findall(r'<script src="\.\./([^"?]+)(\?v=([0-9a-f]+))?"', shell)
        self.assertEqual([name for name, _, _ in sources],
                         ["data/roster.js", "data/pm.js", "assets/charts.js", "assets/page.js"])
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


class PmSectionOneTest(unittest.TestCase):
    """The page's four parts, and section one in the order the site's format asks.

    Section one settles what last quarter left due: (a) the questions last
    quarter's note left open, as this quarter's note answered them; (b) the
    thresholds last quarter's note set, against this quarter's filed figures;
    (c) the company's own guidance record. The verdicts and thresholds are the
    notes' facts, not filed figures -- `_checks` carries them typed a second time
    from the notes, so a roll re-keys them there and this file does not change.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.s = load()
        cls.payload = pm.build_payload(cls.s)
        cls.exhibits = exhibits_of(cls.payload)
        cls.section = cls.payload["sections"][0]

    def test_the_page_is_in_the_four_part_format(self) -> None:
        self.assertEqual([(s["id"], s["title"]) for s in self.payload["sections"]],
                         [("settled", "一、上季跟踪指标兑现了吗"), ("quarter_highlights", "二、本季重点"),
                          ("next_quarter", "三、下季要跟踪什么"), ("routine", "四、长期常规跟踪")])
        for section in self.payload["sections"]:
            self.assertTrue(section["exhibits"], section["id"])
        self.assertIn("本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列", " ".join(self.payload["notes"]))

    def test_section_one_runs_questions_then_thresholds_then_guidance(self) -> None:
        refs = [ex.get("ref") for ex in self.section["exhibits"]]
        self.assertEqual(refs[:2], ["EX_CLOSURE", "EX_PRIOR"])
        self.assertEqual(refs[-6:], ["EX_FY_BAND", "EX_FY_DEV", "EX_ADJ_BAND", "EX_FX", "EX_Q_BAND", "EX_Q_DEV"])
        description = self.section["description"]
        self.assertIn(f"{len(self.s['followup_closure']['items'])} 条待验证问题", description)
        prior = self.s["prior_kpi_settlement"]
        self.assertIn(f"{len(prior['quantified']) + len(prior['unsettleable'])} 条量化阈值", description)
        self.assertIn("第一节先结算上季本地分析稿留下的待验证问题与量化阈值", " ".join(self.payload["notes"]))

    def test_the_closure_is_the_notes_own_verdicts_counted(self) -> None:
        block, note = self.s["followup_closure"], self.s["_checks"]["note"]["followup_closure"]
        self.assertEqual([item["verdict"] for item in block["items"]], note["verdicts"])
        for item in block["items"]:
            # a label is the verdict's own words, never a regrouping of them
            self.assertIn(item["label"], item["verdict"], item["question"])
        chart = self.exhibits["EX_CLOSURE"]
        counted = collections.Counter(item["label"] for item in block["items"])
        self.assertEqual(dict(zip(chart["xlabels"], chart["values"])), note["verdict_counts"])
        self.assertEqual(dict(counted), note["verdict_counts"])
        self.assertEqual(chart["xlabels"], [label for label in block["labels"] if counted[label]])
        self.assertEqual(sum(chart["values"]), note["total"])
        self.assertTrue(chart["title"].startswith(f"上季 {len(block['items'])} 条待验证问题："), chart["title"])
        for label, count in counted.items():
            self.assertIn(f"{count} 条{label}", chart["title"])
        for number, item in enumerate(block["items"], 1):
            self.assertIn(f"<br>{number}. {item['question']} —— <b>{item['verdict']}</b>：", chart["note"])
        self.assertNotRegex(chart["note"], r"\{[a-z_:]+\}")
        self.assertIn(block["set_in"], chart["src_extra"])

    def test_the_prior_thresholds_are_the_prior_notes_settled_on_filed_figures(self) -> None:
        block, note = self.s["prior_kpi_settlement"], self.s["_checks"]["note"]["prior_thresholds"]
        lines = block["quantified"] + block["unsettleable"]
        self.assertEqual({e["metric"]: (e["threshold"], e["direction"]) for e in lines},
                         {t["metric"]: (t["threshold"], t["direction"]) for t in note})
        self.assertEqual(len(lines), len(note))
        self.assertEqual(pm.yq(block["set_in"]), pm.yq(pm.previous_quarter(self.s["period_labels"][-1])))
        chart = self.exhibits["EX_PRIOR"]
        printed = self.s["quarter_printed"]
        reading = {"organic_growth": printed["organic_revenue_growth_pct"],
                   "organic_oi_growth": printed["organic_operating_income_growth_pct"],
                   "combustible_pricing": printed["combustible_pricing_pct"],
                   "zyn_offtake": self.s["zyn"]["offtake_yoy_pct"][-1]}
        drawn = [e for e in block["quantified"] if reading[e["measure"]] is not None]
        self.assertEqual(chart["xlabels"], [e["metric"] for e in drawn])
        for entry, value in zip(drawn, chart["values"]):
            self.assertAlmostEqual(headroom(entry["direction"], entry["threshold"], reading[entry["measure"]]),
                                   value, places=1, msg=entry["metric"])
        total = len(block["quantified"]) + len(block["unsettleable"])
        self.assertTrue(chart["title"].startswith(f"上季 {total} 条量化阈值："), chart["title"])
        held = sum(1 for v in chart["values"] if v >= 0)
        self.assertIn(f"{held} 条守住", chart["title"])
        worded = [e for e in block["quantified"] if reading[e["measure"]] is None]
        self.assertEqual([e for e in block["quantified"] if "words_verdict" in e], worded)
        for entry in worded:
            self.assertIn(f"{pm.base_name(entry['metric'])} {pm.threshold_words(entry)} {entry['words_verdict']}",
                          chart["title"])
            self.assertIn(f"「{self.s['zyn']['offtake_words'][-1]}」", chart["note"])
        for item in block["unsettleable"]:
            self.assertIn(item["metric"], chart["note"])
        for item in block["qualitative"]:
            self.assertIn(item["name"], chart["note"])
        table = next(t for t in self.payload["tables"] if t["title"].startswith("上季阈值与本季实际"))
        self.assertEqual([row[0] for row in table["rows"]], chart["xlabels"])

    def test_a_worded_threshold_is_drawn_as_its_own_line_and_nowhere_as_a_point(self) -> None:
        """The quarter's ZYN reading is a sentence; the line stops at the last figure."""
        lines = [ex for ex in self.section["exhibits"] if ex["kind"] == "lines"]
        zyn = self.s["zyn"]
        if zyn["offtake_yoy_pct"][-1] is not None:
            self.assertEqual(lines, [])
            return
        self.assertEqual(len(lines), 1)
        line = lines[0]
        entry = next(e for e in self.s["prior_kpi_settlement"]["quantified"] if e["measure"] == "zyn_offtake")
        self.assertEqual(line["xlabels"], zyn["period_labels"])
        self.assertIsNone(line["series"][0]["values"][-1])
        self.assertEqual(set(line["series"][1]["values"]), {entry["threshold"]})
        self.assertIn(f"{entry['words_verdict']}上季阈值 {pm.unit_text(entry['unit'], entry['threshold'])}",
                      line["title"])
        self.assertIn(zyn["offtake_words"][-1], line["annot"])


class PmNextQuarterTest(unittest.TestCase):
    """Section three is this quarter's note's section 8, line by line, and the
    sections either side read the filed figures the note's conclusions rest on.
    The thresholds are the note's facts: `_checks["note"]` carries them typed a
    second time from the note, so a roll re-keys them there."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.s = load()
        cls.payload = pm.build_payload(cls.s)
        cls.exhibits = exhibits_of(cls.payload)
        cls.section = cls.payload["sections"][2]
        cls.charts = {ex["title"].split("：")[0]: ex for ex in cls.section["exhibits"][1:]}

    def test_the_thresholds_are_the_notes_section_eight(self) -> None:
        kpi = self.s["next_kpi"]
        note = self.s["_checks"]["note"]["next_thresholds"]
        lines = kpi["quantified"] + kpi["awaiting"] + kpi["unmeasurable"]
        self.assertEqual({e["metric"]: (e["threshold"], e["direction"]) for e in lines},
                         {t["metric"]: (t["threshold"], t["direction"]) for t in note})
        self.assertEqual(len(lines), len(note))
        overview = self.section["exhibits"][0]
        self.assertEqual(overview.get("ref"), "EX_NEXT")
        self.assertTrue(overview["title"].startswith(f"下季 {len(note)} 条阈值："), overview["title"])
        self.assertIn(f"共 {len(note)} 条", self.section["description"])

    def test_no_threshold_is_a_local_setting_any_more(self) -> None:
        """The page carried 集团调整后经营利润率 ≥41% -- in neither note -- and
        called every threshold 本地研究设定."""
        text = text_of(self.section)
        for gone in ("本地研究设定", "本地阈值", "集团调整后经营利润率"):
            self.assertNotIn(gone, text)
        self.assertIn("本季本地分析稿第 8 节", self.section["exhibits"][0]["note"])

    def test_a_metric_with_two_lines_is_one_chart_with_both(self) -> None:
        chart = self.charts["美国分部调整后毛利率"]
        thresholds = sorted(e["threshold"] for e in self.s["next_kpi"]["quantified"]
                            if e["measure"] == "segment_gm_us")
        self.assertEqual(sorted(series["values"][0] for series in chart["series"][1:]), thresholds)
        for series in chart["series"][1:]:
            self.assertEqual(len(set(series["values"])), 1)
            self.assertEqual(len(series["values"]), len(chart["xlabels"]))
        self.assertEqual({series["color"] for series in chart["series"][1:]}, {"RED", "GOLD"})

    def test_the_leverage_line_is_what_each_release_printed(self) -> None:
        lev = self.s["leverage"]
        self.assertEqual(lev["periods"][0], "2016Q1")
        self.assertEqual(pm.yq(lev["periods"][-1]), pm.yq(self.s["periods"][-1]))
        for quarter, ratio, debt, ebitda in zip(lev["periods"], lev["net_debt_to_adjusted_ebitda"],
                                                 lev["net_debt_usd_m"], lev["adjusted_ebitda_ttm_usd_m"]):
            self.assertLessEqual(abs(debt / ebitda - ratio), 0.005 + 1e-9, quarter)
        c = self.s["_checks"]
        self.assertEqual(lev["net_debt_to_adjusted_ebitda"][-1], c["net_debt_to_adjusted_ebitda"])
        year_end = lev["periods"].index(f"{pm.yq(self.s['periods'][-1])[0] - 1}Q4")
        self.assertEqual(lev["net_debt_to_adjusted_ebitda"][year_end], c["prior_year_end_net_debt_to_adjusted_ebitda"])
        chart = self.charts["净债务 / 调整后 EBITDA"]
        self.assertEqual(chart["xlabels"], lev["period_labels"])
        self.assertIn(f"当前 {lev['net_debt_to_adjusted_ebitda'][-1]:.2f}×", chart["title"])

    def test_the_second_half_is_the_year_less_the_first_half(self) -> None:
        half, annual, c = self.s["half_year_cash"], self.s["annual"], self.s["_checks"]
        self.assertEqual(half["h1_operating_cash_flow_usd_m"][-1], c["h1_operating_cash_flow_usd_m"])
        self.assertEqual(half["h1_capex_usd_m"][-1], c["h1_capex_usd_m"])
        full = dict(zip(annual["years"], annual["operating_cash_flow_usd_m"]))
        first = dict(zip(half["years"], half["h1_operating_cash_flow_usd_m"]))
        years = [y for y in half["years"] if y in full]
        chart = self.charts["下半年经营现金流"]
        self.assertEqual(chart["xlabels"], [f"H2 {y}" for y in years])
        self.assertEqual(chart["series"][0]["values"], [full[y] - first[y] for y in years])
        threshold = next(e["threshold"] for e in self.s["next_kpi"]["awaiting"] if e["measure"] == "h2_ocf")
        reached = [y for y in years if full[y] - first[y] >= threshold]
        self.assertEqual(f"年里只有 {reached[0]} 年达到" in chart["title"], len(reached) == 1)
        guide = self.s["guidance_other"]["operating_cash_flow_usd_m"]
        self.assertIn(f"隐含 US${guide - first[half['years'][-1]]:,.0f}M", chart["title"])

    def test_the_bridge_names_both_lines_last_quarter_printed(self) -> None:
        """Last quarter's note read volume/mix as −346 and this page read −206.
        Both are filed: the first 2026 release printed Volume/Mix (−346) and
        Other (+140) on two lines, the second release one line. The page now says so."""
        bridge = self.s["revenue_bridge"]
        previous = bridge[bridge["periods"][-2]]
        split = previous["printed_split"]
        for i, total in enumerate(previous["volume_mix_other"]):
            self.assertEqual(split["volume_mix"][i] + split["other"][i], total)
        note = self.exhibits["EX_BRIDGE"]["note"]
        self.assertIn(f"量与结构（{pm.money_m(split['volume_mix'][0])}）和其他（{pm.money_m(split['other'][0])}）",
                      note)
        self.assertIn(pm.money_m(split["volume_mix"][0]), self.payload["brief"])
        latest = bridge[bridge["periods"][-1]]
        printed = self.s["quarter_printed"]["organic_revenue_growth_pct"]
        self.assertEqual(f"{pm.organic_rate(latest):.1f}", f"{printed:.1f}")
        self.assertIn(f"本季的 {pm.organic_rate(latest):.1f}%", note)

    def test_a_quarterly_bar_names_the_year_to_date_beside_it(self) -> None:
        """The organic operating-income lines are read on the quarter (10.7% at Q2
        2026); the release's year to date sits on the other side of both of them."""
        printed = self.s["quarter_printed"]
        ytd = printed["ytd_organic_operating_income_growth_pct"]
        lines = [e for e in self.s["next_kpi"]["quantified"] if e["measure"] == "organic_oi_growth"]
        note = self.section["exhibits"][0]["note"]
        self.assertIn(f"本季单季的 {printed['organic_operating_income_growth_pct']:.1f}%", note)
        self.assertIn(f"年初至今累计是 {ytd:.1f}%", note)
        under = [e for e in lines if ytd < e["threshold"]]
        self.assertEqual("在两条线之上" in note, not under)
        for entry in under:
            self.assertIn(f"{pm.role_of(entry['metric'])} {pm.unit_words(entry['unit'], entry['threshold'])}", note)

    def test_the_headline_names_the_one_off_behind_the_gaap_decline(self) -> None:
        one_off = self.s["quarter_story"]["gaap_one_off"]
        eps = self.s["financials"]["reported_diluted_eps_usd"]
        self.assertLess(eps[-1], eps[-5])
        self.assertIn(f"同比下降（其中 {one_off['name']}拿走 US${one_off['eps_usd']:.2f}）", self.payload["headline"])

    def test_the_first_half_capex_is_read_now_that_the_10q_is_filed(self) -> None:
        """The note could not check capital expenditure: the 10-Q came two days
        after the release. The page now reads the filed first half."""
        capex = self.s["half_year_cash"]["h1_capex_usd_m"]
        self.assertIn(f"上半年资本开支是 US${capex[-1]:,.0f}M，上年同期 US${capex[-2]:,.0f}M",
                      self.exhibits["EX_CASH"]["note"])


def with_every_block(source: dict) -> dict:
    """The series with every optional one-release block present and stamped for
    the quarter it ends on, synthesised with placeholder words where absent."""
    st = copy.deepcopy(source)
    period = st["period_labels"][-1]
    story = st.setdefault("quarter_story", {"period": period})
    story.setdefault("us_gross_margin_reason", "测试用的美国毛利率原因。")
    story.setdefault("us_investment", "测试用的投入说法")
    other = st.setdefault("guidance_other", {"period": period, "rows": [["测试行", "1", "1", "重申"]]})
    other.setdefault("headline_quote", "测试用的标题")
    other.setdefault("capex_low_usd_m", 1400.0)
    other.setdefault("capex_high_usd_m", 1600.0)
    st.setdefault("quarter_printed", {"period": period, "organic_revenue_growth_pct": 6.0,
                                      "isf_organic_revenue_growth_pct": 11.0})
    return st


def roll_forward(source: dict) -> dict:
    """Append the next quarter with invented figures -- a shape test, nothing
    here is published. A Q4 release settles the year and opens the next."""
    st = copy.deepcopy(source)
    long, fin = st["long"], st["financials"]
    new = next_quarter(long["periods"][-1])
    year, number = pm.yq(new)
    end = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}[number]
    release = {1: f"{year}-04-22", 2: f"{year}-07-22", 3: f"{year}-10-21", 4: f"{year + 1}-02-06"}[number]
    label = f"Q{number} {year}"
    prior = quarter_label(year - 1, number)
    ago = long["periods"].index(prior)
    long["periods"].append(new)
    long["period_labels"].append(label)
    for key in ("net_revenues_usd_m", "gross_profit_usd_m", "operating_income_usd_m"):
        long[key].append(round(long[key][ago] * 1.05))
    long["gross_margin_pct"].append(round(long["gross_profit_usd_m"][-1] / long["net_revenues_usd_m"][-1] * 100, 2))
    long["operating_margin_pct"].append(
        round(long["operating_income_usd_m"][-1] / long["net_revenues_usd_m"][-1] * 100, 2))
    st["periods"] = long["periods"][-8:]
    st["period_labels"] = long["period_labels"][-8:]
    st["period_ends"] = st["period_ends"][1:] + [f"{year}-{end}"]
    for key in fin:
        fin[key] = long[key][-8:] if key in long else fin[key][1:] + [round(fin[key][-4] + 0.1, 2)]
    # the quarterly record: settle the guided quarter; PMI does not guide a Q4
    for row in st["quarterly_guidance"]:
        if row["guided_period"] == new:
            row["actual_eps"] = fin["adjusted_diluted_eps_usd"][-1] = round(row["high"] + 0.05, 2)
    following = next_quarter(new)
    if pm.yq(following)[1] != 4:
        st["quarterly_guidance"].append({
            "release_date": release, "guided_period": following, "period_label": pm.display(following),
            "basis": "adjusted", "point": False, "low": 2.3, "high": 2.35, "currency_eps": 0.01,
            "actual_eps": None})
    records = st["annual_guidance"]["records"]
    record = next(r for r in records if r["year"] == year)
    base = dict(record["vintages"][-1], release_date=release)
    if number == 4:
        record["actual_reported_eps"] = 7.3
        st["annual_guidance"]["annual_adjusted_eps_actual"][str(year)] = 8.4
        first = dict(base, low=8.0, high=8.2, adj_low=9.0, adj_high=9.2, xfx_low=9.0, xfx_high=9.2)
        records.append({"year": year + 1, "vintages": [first], "withdrawn": [], "actual_reported_eps": None,
                        "first_guided": first, "last_guided": first})
        st["annual_guidance"]["years"].append(year + 1)
        annual = st["annual"]
        for key in annual:
            annual[key].append(year if key == "years" else annual[key][-1])
        annual["net_revenues_usd_m"][-1] = sum(long["net_revenues_usd_m"][long["periods"].index(f"{year}Q1"):])
        annual["combustible_usd_m"][-1] = annual["net_revenues_usd_m"][-1] - annual["smoke_free_usd_m"][-1]
        annual["smoke_free_share_pct"][-1] = annual["smoke_free_usd_m"][-1] / annual["net_revenues_usd_m"][-1] * 100
    else:
        record["vintages"].append(base)
        record["last_guided"] = base
    # segments: the new quarter and, printed beside it, the year-ago one
    seg = st["segments"]
    for quarter in (prior, new):
        if quarter in seg["periods"]:
            continue
        position = sorted(seg["periods"] + [quarter], key=pm.yq).index(quarter)
        seg["periods"].insert(position, quarter)
        seg["period_labels"].insert(position, pm.display(quarter))
        for group in ("net_revenues_usd_m", "gross_profit_usd_m", "adjusted_gross_margin_pct"):
            for part in seg[group].values():
                part.insert(position, part[-1])
        for key in ("adjusted_operating_income_usd_m", "adjusted_oi_margin_pct"):
            seg[key].insert(position, seg[key][-1])
    total = dict(zip(long["periods"], long["net_revenues_usd_m"]))
    gross = dict(zip(long["periods"], long["gross_profit_usd_m"]))
    for index, quarter in enumerate(seg["periods"]):
        for group, whole in (("net_revenues_usd_m", total), ("gross_profit_usd_m", gross)):
            parts = seg[group]
            parts["us"][index] = (whole[quarter] - parts["international_smoke_free"][index]
                                  - parts["international_combustibles"][index])
    # the bridge and ZYN carry the new quarter
    bridge = st["revenue_bridge"]
    previous = bridge[bridge["periods"][-1]]
    step = {key: list(previous[key]) for key in ("price", "volume_mix_other", "currency")}
    step["acq_div"] = [0, 0, 0, 0]
    step["base"] = [total[prior]] + list(previous["end"][1:])
    step["end"] = [sum(step[key][i] for key in ("base", "price", "volume_mix_other", "acq_div", "currency"))
                   for i in range(4)]
    step["currency"][0] += total[new] - step["end"][0]
    step["end"][0] = total[new]
    bridge["periods"].append(new)
    bridge["period_labels"].append(label)
    bridge[new] = step
    zyn = st["zyn"]
    zyn["periods"].append(new)
    zyn["period_labels"].append(label)
    zyn["offtake_yoy_pct"].append(5.0)
    zyn["offtake_words"].append(None)
    zyn["shipment_words"].append("测试用的出货说法")
    words = f"PMI {year} 年第{pm.CN_Q[number]}季度" + ("及全年" if number == 4 else "") + "业绩新闻稿"
    st["sources"].insert(0, {"label": words + "（测试）",
                             "url": f"https://www.sec.gov/Archives/edgar/data/1413329/test/{new}.htm"})
    st["latest"].update(period=label, release_date=release)
    st["next_kpi"]["period"] = label
    # last quarter's questions and thresholds were closed by last quarter's note;
    # a rolled quarter without a note of its own has nothing to settle
    for key in ("quarter_story", "guidance_other", "followup_closure", "prior_kpi_settlement"):
        st.pop(key, None)
    st["quarter_printed"] = {"period": label, "organic_revenue_growth_pct": 5.5,
                             "isf_organic_revenue_growth_pct": 10.5, "isf_organic_gross_profit_growth_pct": 13.0,
                             "organic_operating_income_growth_pct": 8.0, "zyn_retail_value_share_pct": 56.0}
    # the leverage schedule of the new release
    leverage = st["leverage"]
    leverage["periods"].append(new)
    leverage["period_labels"].append(label)
    for key in ("net_debt_to_adjusted_ebitda", "net_debt_usd_m", "adjusted_ebitda_ttm_usd_m"):
        leverage[key].append(leverage[key][-1])
    return st


class PmRollTest(unittest.TestCase):
    """What a roll has to change in `series/pm.json`, and what the page does when it does not.

    Four blocks describe one release and carry its quarter: the thresholds
    (`next_kpi`), the printed organic growth rates (`quarter_printed`), the
    non-EPS forecast rows (`guidance_other`) and the quarter's explanations
    (`quarter_story`). The bridge, the segment table and the ZYN block must end
    on the page's quarter, and the annual record must carry this release's
    vintage. A stale block stops the build; an absent story or forecast block
    takes its sentences with it.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = load()
        cls.full = with_every_block(cls.source)
        cls.payload = pm.build_payload(cls.full)
        cls.blob = text_of(cls.payload)

    def test_a_block_stamped_with_another_quarter_stops_the_build(self) -> None:
        for key in ("next_kpi", "quarter_printed", "guidance_other", "quarter_story",
                    "followup_closure", "prior_kpi_settlement"):
            stale = copy.deepcopy(self.full)
            stale[key]["period"] = "Q1 1999"
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    pm.build_payload(stale)
        for key in ("revenue_bridge", "segments", "zyn", "leverage"):
            behind = copy.deepcopy(self.full)
            behind[key]["periods"][-1] = "1999Q1"
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    pm.build_payload(behind)

    def test_what_a_roll_forgets_stops_the_build(self) -> None:
        cases = {}
        bare = copy.deepcopy(self.full)
        del bare["next_kpi"]
        cases["`next_kpi` is missing"] = bare
        unknown = copy.deepcopy(self.full)
        unknown["next_kpi"]["quantified"][0]["measure"] = "not_a_measure"
        cases["does not know how to measure"] = unknown
        waiting = copy.deepcopy(self.full)
        waiting["next_kpi"]["awaiting"][0]["measure"] = "not_a_measure"
        cases["next_kpi awaiting entry"] = waiting
        unshared = copy.deepcopy(self.full)
        del unshared["quarter_printed"]["zyn_retail_value_share_pct"]
        cases["has no 'zyn_retail_value_share_pct'"] = unshared
        unprinted = copy.deepcopy(self.full)
        del unprinted["quarter_printed"]
        cases["`quarter_printed` has no"] = unprinted
        orphan = copy.deepcopy(self.full)
        _, url, _ = pm.release_source(orphan)
        orphan["sources"] = [s for s in orphan["sources"] if s["url"] != url]
        cases["`sources` has no"] = orphan
        audited = copy.deepcopy(self.full)
        audited["latest"]["audit_status"] = "reviewed"
        cases["audit_status"] = audited
        unsettled = copy.deepcopy(self.full)
        row = next(r for r in unsettled["quarterly_guidance"] if r["guided_period"] == unsettled["periods"][-1])
        row["actual_eps"] = None
        cases["has no actual"] = unsettled
        unvintaged = copy.deepcopy(self.full)
        released_record(unvintaged)["vintages"].pop()
        cases["has no vintage released"] = unvintaged
        short = copy.deepcopy(self.full)
        short["long"]["periods"].pop()
        cases["append the quarter to both"] = short
        wordless = copy.deepcopy(self.full)
        wordless["zyn"]["offtake_yoy_pct"][-1] = None
        wordless["zyn"]["offtake_words"][-1] = None
        cases["no offtake figure and no offtake words"] = wordless
        unpaired = copy.deepcopy(self.full)
        unpaired["zyn"]["offtake_words"].pop()
        cases["one entry per quarter"] = unpaired
        stray = copy.deepcopy(self.full)
        stray["annual_guidance"]["exclusion_clause_census"]["without_clause"].append("1999-01-01")
        cases["outside its own releases"] = stray
        for message, staging in cases.items():
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, re.escape(message)):
                    pm.build_payload(staging)

    def test_a_quarter_without_a_story_leaves_it_out(self) -> None:
        story, other = self.full["quarter_story"], self.full["guidance_other"]
        cases = {
            # the capex judgement and the first half that tests it go with the story
            "quarter_story": [story["us_gross_margin_reason"][:10], story["us_investment"][:10], "上半年资本开支是"],
            "guidance_other": [other["rows"][0][0], other["headline_quote"], "上半年资本开支是"],
        }
        for key, texts in cases.items():
            bare = copy.deepcopy(self.full)
            del bare[key]
            after = text_of(pm.build_payload(bare))
            for text in texts:
                with self.subTest(block=key, text=text):
                    self.assertIn(text, self.blob)
                    self.assertNotIn(text, after)

    def test_a_quarter_with_nothing_left_to_settle_says_so(self) -> None:
        bare = copy.deepcopy(self.full)
        del bare["followup_closure"], bare["prior_kpi_settlement"]
        payload = pm.build_payload(bare)
        section = payload["sections"][0]
        self.assertEqual(section["exhibits"][0]["ref"], "EX_FY_BAND")
        self.assertTrue(section["description"].startswith("本季没有上季分析稿留下的问题与阈值可结算。"))
        self.assertFalse(any(t["title"].startswith("上季阈值") for t in payload["tables"]))
        notes = " ".join(payload["notes"])
        self.assertIn("第一节结清公司自己的指引：", notes)
        self.assertNotIn("第一节先结算", notes)

    def test_the_settlement_blocks_refuse_what_the_series_no_longer_supports(self) -> None:
        cases = {}
        stale = copy.deepcopy(self.full)
        stale["followup_closure"]["set_in"] = "Q3 2025"
        cases["closes questions set in 'Q3 2025'"] = stale
        stale = copy.deepcopy(self.full)
        stale["prior_kpi_settlement"]["set_in"] = "Q3 2025"
        cases["settles thresholds set in 'Q3 2025'"] = stale
        stray = copy.deepcopy(self.full)
        stray["followup_closure"]["items"][0]["label"] = "测试标签"
        cases["that `labels` does not list"] = stray
        moved = copy.deepcopy(self.full)
        released_record(moved)["vintages"][-1]["xfx_low"] += 0.05
        cases["assumes 'fy_change_all_currency'"] = moved
        figured = copy.deepcopy(self.full)
        figured["zyn"]["offtake_yoy_pct"][-1], figured["zyn"]["offtake_words"][-1] = 3.0, None
        cases["assumes 'zyn_words_only'"] = figured
        figured = copy.deepcopy(figured)
        del figured["followup_closure"]
        cases["remove its `words_verdict`"] = figured
        wordless = copy.deepcopy(self.full)
        del wordless["followup_closure"]
        next(e for e in wordless["prior_kpi_settlement"]["quantified"] if "words_verdict" in e).pop("words_verdict")
        cases["settle it from the release's words"] = wordless
        unknown = copy.deepcopy(self.full)
        unknown["prior_kpi_settlement"]["quantified"][0]["measure"] = "not_a_measure"
        cases["prior_kpi_settlement entry"] = unknown
        unprinted = copy.deepcopy(self.full)
        del unprinted["quarter_printed"]["combustible_pricing_pct"]
        cases["has no 'combustible_pricing_pct'"] = unprinted
        for message, staging in cases.items():
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, re.escape(message)):
                    pm.build_payload(staging)

    def test_a_settled_threshold_follows_the_figure(self) -> None:
        """A ZYN figure turns the worded entry into a bar; a pricing miss is named."""
        st = copy.deepcopy(self.full)
        del st["followup_closure"]
        st["zyn"]["offtake_yoy_pct"][-1], st["zyn"]["offtake_words"][-1] = 18.0, None
        entry = next(e for e in st["prior_kpi_settlement"]["quantified"] if e["measure"] == "zyn_offtake")
        entry.pop("words_verdict")
        st["quarter_printed"]["combustible_pricing_pct"] = 3.5
        payload = pm.build_payload(st)
        chart = exhibits_of(payload)["EX_PRIOR"]
        self.assertIn(entry["metric"], chart["xlabels"])
        self.assertIn("2 条没有守住（国际组合烟草定价（加仓线）、国际组合烟草定价（警示线））", chart["title"])
        self.assertIn(f"{len(chart['xlabels']) - 2} 条守住", chart["title"])
        self.assertNotIn("画不成柱", chart["note"])
        self.assertEqual([ex["kind"] for ex in payload["sections"][0]["exhibits"][:2]], ["diverging_bars", "range_band"])

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        """Make each "only / every / all / usually / often" claim true in the data,
        then break it once: the sentence that made it must go."""
        def page_row(d):
            return next(r for r in d["quarterly_guidance"] if r["guided_period"] == d["periods"][-1])

        def adjusted_all_above(d):
            for r in d["quarterly_guidance"]:
                if r["basis"] != "reported" and r["actual_eps"] is not None:
                    r["actual_eps"] = round(r["high"] + 0.05, 2)

        def one_adjusted_inside(d):
            adjusted_all_above(d)
            r = next(r for r in d["quarterly_guidance"] if r["basis"] == "adjusted" and r["actual_eps"] is not None)
            r["actual_eps"] = r["low"]

        def second_reported_miss(d):
            r = next(r for r in d["quarterly_guidance"] if r["guided_period"] == "2021Q3")
            r["actual_eps"] = round(r["low"] - 0.05, 2)

        def reported_all_positive(d):
            for r in d["quarterly_guidance"]:
                if r["basis"] == "reported":
                    r["actual_eps"] = round(r["high"] + 0.05, 2)

        def q4_guided_twice(d):
            d["quarterly_guidance"].append({"release_date": "2021-10-19", "guided_period": "2021Q4",
                                            "period_label": "Q4 2021", "basis": "reported", "point": False,
                                            "low": 1.3, "high": 1.35, "currency_eps": 0.0, "actual_eps": 1.4})
            d["quarterly_guidance"].sort(key=lambda r: pm.yq(r["guided_period"]))

        def xfx_moves(d):
            released_record(d)["vintages"][-1]["xfx_low"] += 0.05

        def fx_mostly_opposite(d):
            for record in d["annual_guidance"]["records"]:
                vs = [v for v in record["vintages"] if v.get("adj_low") is not None and v.get("xfx_low") is not None]
                if len(vs) >= 2 and record["year"] != 2022:
                    vs[-1]["xfx_low"], vs[-1]["xfx_high"] = vs[0]["xfx_low"] + 0.3, vs[0]["xfx_high"] + 0.3
                    vs[-1]["adj_low"], vs[-1]["adj_high"] = vs[0]["adj_low"] - 0.3, vs[0]["adj_high"] - 0.3

        def fx_mostly_flat(d):
            for record in d["annual_guidance"]["records"]:
                if record["year"] in (2021, 2025):
                    vs = [v for v in record["vintages"] if v.get("xfx_low") is not None]
                    vs[-1]["xfx_low"], vs[-1]["xfx_high"] = vs[0]["xfx_low"], vs[0]["xfx_high"]

        def bridge_price_led(d):
            b = d["revenue_bridge"][d["revenue_bridge"]["periods"][-1]]
            b["price"][2], b["volume_mix_other"][2] = 900, -200
            b["currency"][2] = b["end"][2] - b["base"][2] - 700 - b["acq_div"][2]

        def bridge_volume_led(d):
            b = d["revenue_bridge"][d["revenue_bridge"]["periods"][-1]]
            b["price"][2], b["volume_mix_other"][2] = 50, 400
            b["currency"][2] = b["end"][2] - b["base"][2] - 450 - b["acq_div"][2]

        def vmo_turns(d):
            bridge = d["revenue_bridge"]
            if len(bridge["periods"]) < 2:
                # the first quarter of the segment bridge has no previous one; lend it one
                first = bridge["periods"][0]
                year, number = pm.yq(first)
                before = quarter_label(year - 1, 4) if number == 1 else quarter_label(year, number - 1)
                bridge[before] = copy.deepcopy(bridge[first])
                bridge["periods"].insert(0, before)
                bridge["period_labels"].insert(0, pm.display(before))
            bridge[bridge["periods"][-2]]["volume_mix_other"][0] = -100
            bridge[bridge["periods"][-1]]["volume_mix_other"][0] = 100
            # the rewritten quarter no longer adds up to the two lines it printed
            for quarter in bridge["periods"][-2:]:
                bridge[quarter].pop("printed_split", None)

        def vmo_stays(d):
            vmo_turns(d)
            bridge = d["revenue_bridge"]
            bridge[bridge["periods"][-2]]["volume_mix_other"][0] = 50

        def us_only_down(d):
            seg = d["segments"]
            rev = seg["net_revenues_usd_m"]
            ago = pm.year_ago_index(seg["periods"], len(seg["periods"]) - 1)
            rev["international_smoke_free"][-1] = rev["international_smoke_free"][ago] + 100
            rev["international_combustibles"][-1] = rev["international_combustibles"][ago] + 100
            rev["us"][-1] = rev["us"][ago] - 50

        def two_segments_down(d):
            us_only_down(d)
            seg = d["segments"]
            ago = pm.year_ago_index(seg["periods"], len(seg["periods"]) - 1)
            rev = seg["net_revenues_usd_m"]
            rev["international_combustibles"][-1] = rev["international_combustibles"][ago] - 10

        def us_gm_alone_falls(d):
            seg = d["segments"]
            gm = seg["adjusted_gross_margin_pct"]
            ago = pm.year_ago_index(seg["periods"], len(seg["periods"]) - 1)
            for key in ("pmi", "international_smoke_free", "international_combustibles"):
                gm[key][-1] = gm[key][ago] + 1
            gm["us"][-1] = gm["us"][ago] - 3

        def us_gm_recovers(d):
            us_gm_alone_falls(d)
            seg = d["segments"]
            ago = pm.year_ago_index(seg["periods"], len(seg["periods"]) - 1)
            seg["adjusted_gross_margin_pct"]["us"][-1] = seg["adjusted_gross_margin_pct"]["us"][ago] + 1

        def zyn_slides(d):
            z = d["zyn"]["offtake_yoy_pct"]
            for i in range(len(z) - 1):
                z[i] = 40.0 - i * 5
            z[-1] = None
            d["zyn"]["offtake_words"] = [None] * (len(z) - 1) + ["测试用的措辞"]

        def zyn_words_twice(d):
            zyn = d["zyn"]
            zyn["offtake_yoy_pct"][-2] = None
            zyn["offtake_words"][-2] = "测试用的上一季措辞"

        def zyn_bounces(d):
            zyn_slides(d)
            z = d["zyn"]["offtake_yoy_pct"]
            z[-2] = z[-3] + 1

        def withdrawn_twice(d):
            record = next(r for r in d["annual_guidance"]["records"] if r["year"] == 2014)
            record["withdrawn"] = [record["vintages"][1]["release_date"]]

        def no_withdrawal(d):
            next(r for r in d["annual_guidance"]["records"] if r["year"] == 2020)["withdrawn"] = []

        def q1_2023_adjusted(d):
            next(r for r in d["quarterly_guidance"] if r["guided_period"] == "2023Q1")["basis"] = "adjusted"

        def add_untracked(d):
            d["next_kpi"]["not_tracked"].append({"name": "测试不接入项", "why": "测试用的原因。",
                                                 "note": "测试不接入项（测试用的原因）"})

        def drop_untracked(d):
            d["next_kpi"]["not_tracked"] = [x for x in d["next_kpi"]["not_tracked"] if x["name"] != "测试不接入项"]

        def sums_off(d):
            d["annual"]["combustible_usd_m"][3] += 1

        def combustible_moves(d):
            a = d["annual"]
            a["combustible_usd_m"][-1] = a["combustible_usd_m"][0] * 1.3
            a["net_revenues_usd_m"][-1] = a["combustible_usd_m"][-1] + a["smoke_free_usd_m"][-1]

        def gm_trend_down(d):
            d["long"]["gross_margin_pct"][-1] = d["long"]["gross_margin_pct"][0] - 1

        def adjusted_beat(d):
            d["financials"]["adjusted_diluted_eps_usd"][-1] = round(page_row(d)["high"] + 0.1, 2)

        def adjusted_inside(d):
            d["financials"]["adjusted_diluted_eps_usd"][-1] = page_row(d)["low"]

        def reported_falls(d):
            eps = d["financials"]["reported_diluted_eps_usd"]
            eps[-1] = round(eps[-5] - 0.1, 2)

        def reported_rises(d):
            eps = d["financials"]["reported_diluted_eps_usd"]
            eps[-1] = round(eps[-5] + 0.1, 2)

        def more_clause_gaps(d):
            census = d["annual_guidance"]["exclusion_clause_census"]
            census["without_clause"] = census["without_clause"] + ["2015-02-05"]

        def census_scope_moves(d):
            census = d["annual_guidance"]["exclusion_clause_census"]
            census["releases"] = [r for r in census["releases"] if r != "2008-04-23"]
            census["without_clause"] = [r for r in census["without_clause"] if r != "2008-04-23"]

        def october_moved(d, months):
            banded, _ = pm.annual_records(d)
            finished = [r for r in banded if r["actual_reported_eps"] is not None
                        and r["last_guided"]["release_date"][5:7] == "10"]
            for record, month in zip(finished, months):
                last = record["last_guided"]
                record["last_guided"] = dict(last, release_date=f"{last['release_date'][:5]}{month}-20")

        def october_plurality(d):
            # October stays the most common month but is no longer the majority
            october_moved(d, ["07"] * 5 + ["04"] * 4)

        def october_gone(d):
            october_moved(d, ["07"] * 40)

        def isf_all_volume(d):
            b = d["revenue_bridge"][d["revenue_bridge"]["periods"][-1]]
            total = b["end"][1] - b["base"][1]
            b["price"][1], b["currency"][1], b["acq_div"][1] = 0, 0, 0
            b["volume_mix_other"][1] = total

        def seasonal_breaks(d):
            long = d["long"]
            for year in (2017, 2018, 2019, 2021, 2022, 2023):
                i = long["periods"].index(f"{year}Q1")
                long["net_revenues_usd_m"][i] = long["net_revenues_usd_m"][i + 1] + 500

        def noop(d):
            return None

        cases = {
            "adjusted quarters all above": (adjusted_all_above, one_adjusted_inside,
                                            ("<b>全部</b>高于上限", "全部高于上限")),
            "the only reported miss": (noop, second_reported_miss, ("唯一一次跌破下限",)),
            "reported both signs": (noop, reported_all_positive, ("有正有负",)),
            "the only Q4 guided": (noop, q4_guided_twice, ("从不指引第四季", "唯一的例外是 2020 年第四季")),
            "ex-currency unchanged": (noop, xfx_moves, ("逐字未动", "逐字未变」")),
            "opposite directions rare": (noop, fx_mostly_opposite, ("方向相反的只有", "更常见的是同向")),
            "same direction the commoner": (noop, fx_mostly_flat, ("更常见的是同向",)),
            "combustibles price-led": (bridge_price_led, bridge_volume_led, ("国际组合烟草几乎全部来自价格",)),
            "volume turns positive": (vmo_turns, vmo_stays, ("本季转正", "变成「价格＋正的量与结构」")),
            "the only segment down": (us_only_down, two_segments_down, ("是唯一同比下降的",)),
            "only the U.S. margin falls": (us_gm_alone_falls, us_gm_recovers,
                                           ("只有美国一条在塌", "单位经济性还在恶化")),
            "ZYN slides to words": (zyn_slides, zyn_bounces, ("一路降到公司只肯用措辞描述",)),
            # the section-three line no longer borrows last quarter's figure as the
            # current one; the section-one line says when that figure was read
            "the last figure is last quarter's": (zyn_slides, zyn_words_twice, ("上季设这条线时，最近一格读数是",)),
            "the only withdrawal": (noop, withdrawn_twice, ("这是记录里唯一一次撤回",)),
            "the withdrawal that kept the clause": (noop, no_withdrawal, ("撤回了全年预测，这句话跟着", "撤回除外")),
            "a reported quarter after the switch": (noop, q1_2023_adjusted, ("又回到报告口径",)),
            "what is not tracked is this quarter's": (add_untracked, drop_untracked,
                                                      ("测试不接入项（测试用的原因）", "<b>测试不接入项</b>")),
            "the one-million gap": (noop, sums_off, ("只有 2017 年差 US$1M",)),
            "combustibles flat": (noop, combustible_moves, ("几乎没动", "转型是加出来的")),
            "gross margin trends up": (noop, gm_trend_down, ("毛利率的趋势向上",)),
            "beat the quarter's own range": (adjusted_beat, adjusted_inside,
                                             ("高于公司自己给的", "GAAP 那个数在被一次性项目拿走")),
            "reported EPS down": (reported_falls, reported_rises, ("；但报告口径",)),
            "every release since 2009-04": (noop, more_clause_gaps, ("起每一份都有", "点名排除的最多只有并购")),
            "the census scope is its own": (noop, census_scope_moves, ("2008 年 4 月到", "点名排除的最多只有并购")),
            "usually published in October": (noop, october_plurality, ("通常发布于 10 月",)),
            "three quarters gone only in October": (noop, october_gone, ("此时全年已过去四分之三",)),
            "mostly, not almost all": (noop, isf_all_volume, ("国际无烟的增量主要来自量与结构",)),
            "Q1 is the usual low": (noop, seasonal_breaks, ("年第一季是低点",)),
        }
        for name, (make_true, make_false, claims) in cases.items():
            held = copy.deepcopy(self.full)
            # The closure's evidence describes this release's guidance change and
            # declares it (`requires`), so a series rewritten here would stop the
            # build there first; the closure has its own tests, and none of the
            # claims below is in it.
            held.pop("followup_closure")
            make_true(held)
            before = composed(pm.build_payload(held))
            broken = copy.deepcopy(held)
            make_false(broken)
            after = composed(pm.build_payload(broken))
            for claim in claims:
                with self.subTest(case=name, claim=claim):
                    self.assertIn(claim, before)
                    self.assertNotIn(claim, after)

    def test_the_reported_eps_direction_is_read_from_the_two_quarters(self) -> None:
        for delta, word in ((-0.1, "下降"), (0.0, "持平"), (0.1, "上升")):
            st = copy.deepcopy(self.full)
            eps = st["financials"]["reported_diluted_eps_usd"]
            eps[-1] = round(eps[-5] + delta, 2)
            with self.subTest(word=word):
                self.assertIn(f"报告口径每股收益 US${eps[-1]:.2f} 同比{word}", pm.build_payload(st)["headline"])

    def test_each_threshold_line_names_its_own_window(self) -> None:
        """The three segment-block lines used to share one sentence -- "本节前三条线
        因此只有四个季度" -- which the recast made false for two of them and true
        for the third. Each line now states its own window, and the adjusted
        operating margin, which the recast does not print, is drawn only over
        the quarters that have it rather than as a line of holes."""
        charts = {ex["title"].split("：")[0]: ex for ex in self.payload["sections"][2]["exhibits"][1:]}
        seg = self.full["segments"]
        for name in ("美国分部调整后毛利率", "国际无烟分部调整后毛利率"):
            chart = charts[name]
            self.assertEqual(len(chart["xlabels"]), len(seg["periods"]))
            self.assertIn(f"最早一季（{seg['period_labels'][0]}）起画", chart["note"])
        for chart in charts.values():
            self.assertNotIn("本节前", chart["note"])
        # once the recast is gone the segment lines fall back to the releases' window
        st = copy.deepcopy(self.full)
        st["segments"].pop("recast_filing")
        rebuilt = {ex["title"].split("：")[0]: ex for ex in pm.build_payload(st)["sections"][2]["exhibits"][1:]}
        self.assertNotIn("最早一季", rebuilt["美国分部调整后毛利率"]["note"])
        self.assertIn(f"这条线只有{cn_count(len(seg['periods']))}个季度", rebuilt["美国分部调整后毛利率"]["note"])

    def test_the_fourth_quarter_remark_follows_a_third_quarter_guidance(self) -> None:
        """"Only Q3 is guided: PMI never guides Q4" reads as a reason only when
        the guided quarter is the third; after a Q4 or a Q1 release it is a non
        sequitur."""
        remark = "PMI 从不指引第四季"
        upcoming = pm.next_quarter_guidance(self.full)
        self.assertEqual(remark in self.payload["guidance"]["note"], pm.yq(upcoming["guided_period"])[1] == 3)
        st = copy.deepcopy(self.full)
        row = pm.next_quarter_guidance(st)
        year = pm.yq(st["periods"][-1])[0]
        row["guided_period"], row["period_label"] = f"{year + 1}Q1", f"Q1 {year + 1}"
        note = pm.build_payload(st)["guidance"]["note"]
        self.assertIn("下季指引只覆盖第一季。", note)
        self.assertNotIn(remark, note)

    def test_a_currency_record_mostly_opposed_is_not_illustrated_by_a_same_direction_year(self) -> None:
        st = copy.deepcopy(self.full)
        st.pop("followup_closure")  # its evidence declares this release's guidance change; rewritten here
        for record in st["annual_guidance"]["records"]:
            vs = [v for v in record["vintages"] if v.get("adj_low") is not None and v.get("xfx_low") is not None]
            if len(vs) >= 2 and record["year"] not in (2022, 2024):
                vs[-1]["xfx_low"], vs[-1]["xfx_high"] = vs[0]["xfx_low"] + 0.3, vs[0]["xfx_high"] + 0.3
                vs[-1]["adj_low"], vs[-1]["adj_high"] = vs[0]["adj_low"] - 0.3, vs[0]["adj_high"] - 0.3
        note = exhibits_of(pm.build_payload(st))["EX_FX"]["note"]
        moves = pm.currency_moves(st)
        opposite = [y for y, d, x, _ in moves if d * x < 0]
        self.assertGreater(len(opposite) * 2, len(moves))
        self.assertIn(f"{cn_count(len(moves))}年里有{cn_count(len(opposite))}年方向相反", note)
        self.assertNotIn("FY2024 剔除汇率的指引一年抬了", note)

    def test_the_next_quarter_rolls_without_touching_the_code(self) -> None:
        rolled = roll_forward(self.full)
        payload = pm.build_payload(rolled)
        period = rolled["period_labels"][-1]
        self.assertEqual(payload["title"], f"Philip Morris International (PM)：{period} 季报仪表盘")
        self.assertIn(f"截至 {rolled['period_ends'][-1]} · 发布 {rolled['latest']['release_date']}",
                      payload["subtitle"])
        self.assertEqual(payload["source_url"], rolled["sources"][0]["url"])
        self.assertIn(f"{len(rolled['long']['periods'])} 个季度的收入", payload["sections"][3]["description"])
        self.assertIn(rolled["latest"]["release_date"], payload["guidance"]["title"])
        blob = text_of(payload)
        self.assertNotIn(self.full["quarter_story"]["us_gross_margin_reason"][:10], blob)
        self.assertNotIn(self.full["guidance_other"]["headline_quote"], blob)
        exhibits = exhibits_of(payload)
        self.assertNotIn("annot", exhibits["EX_ZYN"])
        self.assertNotIn("最后一格是空的", exhibits["EX_ZYN"]["note"])

    def test_no_segment_margin_is_back_computed_once_the_recast_prints_them(self) -> None:
        """The 2025 segment margins used to be back-computed from the pp change the
        2026 releases printed. The recast 8-K prints every 2023-2025 quarter's
        margin itself (and agrees with the back-computation to the digit), so the
        caption no longer says any figure was derived -- including after a roll."""
        gm = exhibits_of(self.payload)["EX_SEG_GM"]
        self.assertNotIn("倒推", gm["note"] + gm["src_extra"])
        self.assertIn(self.full["segments"]["recast_filing"]["tables"]["adjusted_gross_margin"], gm["src_extra"])
        st = self.full
        while pm.yq(st["periods"][-1]) < (2027, 1):
            st = roll_forward(st)
        rolled = exhibits_of(pm.build_payload(st))["EX_SEG_GM"]
        self.assertNotIn("倒推", rolled["note"] + rolled["src_extra"])

    def test_the_us_margin_run_is_the_one_that_ends_this_quarter(self) -> None:
        """The caption lists the run of same-direction year-on-year moves that ends
        at the page's quarter, not the whole record; one more falling quarter
        lengthens it, a rising one cuts it to one."""
        seg = self.full["segments"]
        us, periods = seg["adjusted_gross_margin_pct"]["us"], seg["periods"]
        moves = [us[i] - us[j] for i in range(len(periods))
                 for j in [pm.year_ago_index(periods, i)] if j is not None]
        run = 1
        while run < len(moves) and (moves[-run - 1] < 0) == (moves[-1] < 0):
            run += 1
        note = exhibits_of(self.payload)["EX_SEG_GM"]["note"]
        word = "下降" if moves[-1] < 0 else "上升"
        self.assertIn(f"已连续{cn_count(run)}个季度同比{word}", note)
        rolled = roll_forward(self.full)
        rseg = rolled["segments"]
        ago = pm.year_ago_index(rseg["periods"], len(rseg["periods"]) - 1)
        rseg["adjusted_gross_margin_pct"]["us"][-1] = rseg["adjusted_gross_margin_pct"]["us"][ago] + 2
        rnote = exhibits_of(pm.build_payload(rolled))["EX_SEG_GM"]["note"]
        self.assertNotIn("已连续", rnote)
        self.assertIn(f"{rseg['period_labels'][-1]} 同比 +2.0pp", rnote)

    def test_a_fourth_quarter_settles_the_year_and_opens_the_next(self) -> None:
        st = self.full
        while not st["periods"][-1].endswith("Q4"):
            st = roll_forward(st)
        payload = pm.build_payload(st)
        year = pm.yq(st["periods"][-1])[0]
        self.assertIn("第四季度及全年业绩新闻稿", payload["source"])
        self.assertIn(f"与 {year} 年度 Form 10-K", payload["source"])
        banded, _ = pm.annual_records(st)
        n = pm.tally([(r["actual_reported_eps"], r["last_guided"]["low"], r["last_guided"]["high"])
                      for r in banded])[0]
        self.assertIn(f"{n} 个完整年度里", payload["brief"])
        # the February release's forecast table is the new year's first vintage
        guidance = payload["guidance"]
        self.assertIn(st["latest"]["release_date"], guidance["title"])
        self.assertIn(f"{year + 1} 全年报告口径摊薄 EPS", [row[0] for row in guidance["rows"]])
        self.assertEqual(guidance["headers"][2], "上一期指引")
        exhibits = exhibits_of(payload)
        self.assertNotIn("逐字未动", exhibits["EX_FX"]["note"])
        # the fourth quarter has a 10-K, not a 10-Q
        self.assertIn(pm.segment_releases(st), exhibits["EX_SEG_REV"]["src_extra"])
        self.assertIn(f"{year} 年第一、二、三、四季度业绩 8-K", exhibits["EX_SEG_REV"]["src_extra"])
        self.assertIn("同期 10-Q / 10-K 分部附注", exhibits["EX_SEG_REV"]["src_extra"])
        # one more quarter and the segment releases span two years
        after = pm.build_payload(roll_forward(st))
        self.assertIn(f"{pm.cn_quarter(pm.NEW_SEGMENTS_FROM)}至{year + 1} 年第一季度各季业绩 8-K",
                      exhibits_of(after)["EX_SEG_REV"]["src_extra"])


class PmChecksTest(unittest.TestCase):
    """The page's quarter against a record keyed separately from the series.

    `_checks` is typed once per quarter from the quarter's earnings release --
    the headline, the EPS reconciliation, the forecast table and assumptions,
    and the operating-review tables -- with where each figure was read. The
    builder never reads it (asserted in `test_data_only_roll`).
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.s = load()
        cls.c = cls.s["_checks"]
        cls.payload = pm.build_payload(cls.s)
        cls.exhibits = exhibits_of(cls.payload)

    def test_the_page_names_the_checked_quarter(self) -> None:
        c = self.c
        self.assertEqual(self.payload["title"], f"Philip Morris International (PM)：{c['period']} 季报仪表盘")
        self.assertIn(f"截至 {c['period_end']} · 发布 {c['release_date']}", self.payload["subtitle"])
        self.assertEqual(self.s["period_labels"][-1], c["period"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        c, s = self.c, self.s
        fin = s["financials"]
        for key in ("net_revenues_usd_m", "gross_profit_usd_m", "operating_income_usd_m",
                    "reported_diluted_eps_usd", "adjusted_diluted_eps_usd"):
            with self.subTest(figure=key):
                self.assertEqual(fin[key][-1], c[key])
                self.assertEqual(fin[key][-5], c[f"prior_year_{key}"])
        seg = s["segments"]
        ago = pm.year_ago_index(seg["periods"], len(seg["periods"]) - 1)
        for key in pm.SEG_KEYS:
            with self.subTest(segment=key):
                self.assertEqual(seg["net_revenues_usd_m"][key][-1], c["segment_net_revenues_usd_m"][key])
                self.assertEqual(seg["net_revenues_usd_m"][key][ago], c["prior_year_segment_net_revenues_usd_m"][key])
                self.assertEqual(seg["gross_profit_usd_m"][key][-1], c["segment_gross_profit_usd_m"][key])
        gm = seg["adjusted_gross_margin_pct"]
        for key, value in c["adjusted_gross_margin_pct"].items():
            with self.subTest(margin=key):
                self.assertEqual(gm[key][-1], value)
                self.assertAlmostEqual(gm[key][-1] - gm[key][ago], c["adjusted_gross_margin_change_pp"][key], places=6)
        self.assertEqual(seg["adjusted_operating_income_usd_m"][-1], c["adjusted_operating_income_usd_m"])
        self.assertEqual(seg["adjusted_oi_margin_pct"][-1], c["adjusted_oi_margin_pct"])
        self.assertEqual(seg["adjusted_oi_margin_pct"][ago], c["prior_year_adjusted_oi_margin_pct"])
        bridge = s["revenue_bridge"][s["revenue_bridge"]["periods"][-1]]
        for key, value in c["bridge_pmi"].items():
            self.assertEqual(bridge[key][0], value, key)
        printed = s["quarter_printed"]
        for key in ("organic_revenue_growth_pct", "isf_organic_revenue_growth_pct",
                    "organic_operating_income_growth_pct", "combustible_pricing_pct",
                    "isf_organic_gross_profit_growth_pct", "zyn_retail_value_share_pct",
                    "ytd_organic_operating_income_growth_pct"):
            with self.subTest(printed=key):
                self.assertEqual(printed[key], c[key])

    def test_the_guidance_is_the_checked_forecast_table(self) -> None:
        c, s = self.c, self.s
        now = released_record(s)["vintages"][-1]
        self.assertEqual(now["release_date"], c["release_date"])
        fy = c["guidance_full_year"]
        self.assertEqual([now["low"], now["high"]], fy["reported"])
        self.assertEqual([now["adj_low"], now["adj_high"]], fy["adjusted"])
        self.assertEqual([now["xfx_low"], now["xfx_high"]], fy["excluding_currency"])
        self.assertEqual(now["currency_eps"], fy["currency"])
        upcoming = pm.next_quarter_guidance(s)
        nq = c.get("guidance_next_quarter")
        if nq is None:
            self.assertIsNone(upcoming)
        else:
            self.assertEqual(upcoming["guided_period"], nq["period"])
            self.assertEqual([upcoming["low"], upcoming["high"]], nq["adjusted"])
            self.assertEqual(upcoming["currency_eps"], nq["currency"])
        this_q = next((r for r in s["quarterly_guidance"] if r["guided_period"] == s["periods"][-1]), None)
        if this_q is not None:
            self.assertEqual(this_q["actual_eps"], c["adjusted_diluted_eps_usd"])

    def test_the_rounding_the_page_uses_is_the_companys(self) -> None:
        c = self.c
        growth = (c["net_revenues_usd_m"] / c["prior_year_net_revenues_usd_m"] - 1) * 100
        self.assertEqual(f"{growth:.1f}", f"{c['net_revenues_growth_pct_printed']:.1f}")
        self.assertEqual(sum(c["segment_net_revenues_usd_m"].values()), c["net_revenues_usd_m"])
        # the release's own note: "Sums might not foot to total due to rounding" (Q1 2026: 6,906 vs 6,905)
        self.assertAlmostEqual(sum(c["segment_gross_profit_usd_m"].values()), c["gross_profit_usd_m"], delta=1)
        self.assertEqual(round(c["adjusted_operating_income_usd_m"] / c["net_revenues_usd_m"] * 100, 1),
                         c["adjusted_oi_margin_pct"])
        self.assertEqual(sum(c["bridge_pmi"].values()), c["net_revenues_usd_m"] - c["prior_year_net_revenues_usd_m"])

    def test_the_page_prints_the_checked_figures(self) -> None:
        c = self.c
        headline = self.payload["headline"]
        self.assertIn(f"净收入 US${c['net_revenues_usd_m']:,.0f}M、同比 +{c['net_revenues_growth_pct_printed']:.1f}%",
                      headline)
        self.assertIn(f"调整后摊薄每股收益 US${c['adjusted_diluted_eps_usd']:.2f}", headline)
        self.assertIn(f"报告口径每股收益 US${c['reported_diluted_eps_usd']:.2f}", headline)
        self.assertIn(f"美国分部调整后毛利率 {c['adjusted_gross_margin_pct']['us']:.1f}%、"
                      f"同比 {c['adjusted_gross_margin_change_pp']['us']:+.1f}pp", headline)
        bridge = self.exhibits["EX_BRIDGE"]
        self.assertIn(f"US${c['net_revenues_usd_m'] - c['prior_year_net_revenues_usd_m']:,.0f}M", bridge["title"])
        rows = {row[0]: row for row in self.payload["guidance"]["rows"]}
        fy = c["guidance_full_year"]
        year = released_record(self.s)["year"]
        self.assertEqual(rows[f"{year} 全年报告口径摊薄 EPS"][1], f"${fy['reported'][0]:.2f} – ${fy['reported'][1]:.2f}")
        self.assertEqual(rows[f"{year} 全年调整后摊薄 EPS"][1], f"${fy['adjusted'][0]:.2f} – ${fy['adjusted'][1]:.2f}")
        thresholds = next(t for t in self.payload["tables"] if "下季阈值" in t["title"])
        isf = next(r for r in thresholds["rows"] if r[0].startswith("国际无烟有机收入增速"))
        self.assertEqual(isf[3], f"{c['isf_organic_revenue_growth_pct']:.1f}%")
        leverage = next(r for r in thresholds["rows"] if r[0].startswith("净债务 / 调整后 EBITDA"))
        self.assertEqual(leverage[3], f"{c['net_debt_to_adjusted_ebitda']:.2f}x")
        settled = next(t for t in self.payload["tables"] if t["title"].startswith("上季阈值与本季实际"))
        organic = next(r for r in settled["rows"] if r[0].startswith("集团有机收入增速"))
        self.assertEqual(organic[3], f"{c['organic_revenue_growth_pct']:.1f}%")
        for number in re.findall(r"\d+(?:\.\d+)?%", c["zyn_shipments_words"]):
            self.assertIn(number, self.s["zyn"]["shipment_words"][-1])


if __name__ == "__main__":
    unittest.main()
