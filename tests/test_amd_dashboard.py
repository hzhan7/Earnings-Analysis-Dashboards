"""What the AMD page has to keep true.

The page rests on three records that could each be plausibly wrong without
anything else noticing, so each is pinned here against an identity or a second
reading rather than against a remembered number.

**The guidance record changes form twice and is scored on first prints.** Until
the Q4 2017 outlook AMD guided revenue as a sequential percentage, so the
2016-2017 dollar ranges are this page's arithmetic; they are recomputed here from
the base, the percentage and the band the series records. Each guided quarter is
scored against its own first print -- ASC 605 for 2017, the pre-recast opex for
2024, and the company's own ex-Xilinx figures for Q1 2022 -- and every tally a
chart title or the section description prints is recounted from those inputs,
including the two places where the scoring basis changes the answer (the 2-decimal
margin rule and the like-for-like quarter).

**The long series are a merge of overlapping releases.** Four identities are
asserted for every quarter they cover: the four segments sum to revenue, segment
operating income plus All Other closes to GAAP operating income, the two legacy
segments sum to revenue, and free cash flow is operating cash flow less capex.

**Universal sentences are computed, so they are broken on purpose here.** A
record ("42 季最高", "最大跳升", "四分部口径以来最高", "这条序列的新高"), a streak
and an acceleration are each made false in a copy of the series and the
sentence is asserted to go -- beside a positive control on the real series,
because a counterexample test whose phrase never appears proves nothing
(CLAUDE.md §9.3).

Nothing below imports a computing function from `build/amd.py`: the builder is
only called (`build_payload`, `headline_metrics`) to get its output. Every
expected value is recomputed in this file from `series/amd.json`, and `_checks`
-- an independent re-read of the quarter's 8-K and 10-Q that the builder never
sees -- is the second reading for the newest quarter.
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
import re
import statistics
import sys
import unittest
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import amd  # noqa: E402  (build_payload / headline_metrics only)
from build.all import ENTRIES, GROUPS  # noqa: E402

SERIES = ROOT / "series" / "amd.json"
CHARTS = ROOT / "assets" / "charts.js"
DAYS_PER_QUARTER = 91

TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9]*(?:\s[^<>]*)?/?>")
PLACEHOLDER = re.compile(r"\{[A-Za-z_][A-Za-z0-9_:]*\}")
ZERO_FLOORED_KINDS = {"bars_labeled", "gs_bar", "stacked_dual"}


# ── reading ──────────────────────────────────────────────────────────────────
def load() -> dict:
    return json.loads(SERIES.read_text(encoding="utf-8"))


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    return json.loads(text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0])


def text_of(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def exhibits_of(payload: dict) -> list[dict]:
    return [ex for section in payload["sections"] for ex in section["exhibits"]]


def one(payload: dict, prefix: str, kind: str | None = None) -> dict:
    hits = [ex for ex in exhibits_of(payload)
            if ex["title"].startswith(prefix) and (kind is None or ex["kind"] == kind)]
    if len(hits) != 1:
        raise AssertionError(f"{len(hits)} exhibits start with {prefix!r}: "
                             f"{[ex['title'] for ex in hits]}")
    return hits[0]


def table(payload: dict, fragment: str) -> dict:
    hits = [t for t in payload["tables"] if fragment in t["title"]]
    if len(hits) != 1:
        raise AssertionError(f"{len(hits)} tables contain {fragment!r}")
    return hits[0]


def strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from strings(value)


def renderer_names(block_start: str) -> set[str]:
    """Keys of one object literal in `assets/charts.js`, read from source."""
    source = CHARTS.read_text(encoding="utf-8")
    body = source.split(block_start, 1)[1].split("};", 1)[0]
    return set(re.findall(r"^\s*([A-Za-z0-9_]+)\s*:", body, flags=re.M)) | \
        set(re.findall(r",\s*([A-Za-z0-9_]+)\s*:", body))


# ── formatting, written here rather than borrowed from the builder ───────────
def minus(text: str) -> str:
    return text.replace("-", "−")


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return minus(f"{value:+.{digits}f}{suffix}")


def usd_m(value: float) -> str:
    return f"{'−' if value < 0 else ''}US${abs(value):,.0f}M"


def usd_b(value_m: float, digits: int = 1) -> str:
    return f"{'−' if value_m < 0 else ''}US${abs(value_m) / 1000:,.{digits}f}B"


def compact(period: str) -> str:
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


def pct(current: float, base: float) -> float:
    return (current / base - 1) * 100


def half_up(value: float, digits: int = 0) -> Decimal:
    return Decimal(repr(value)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)


_CN = "零一二三四五六七八九"


def cn(value: int) -> str:
    """A count in words, as the page's prose spells it (2 → 两)."""
    if value == 2:
        return "两"
    if value < 10:
        return _CN[value]
    tens, ones = divmod(value, 10)
    return ("" if tens == 1 else _CN[tens]) + "十" + (_CN[ones] if ones else "")


def order(period: str) -> int:
    quarter, year = period.split()
    return int(year) * 4 + int(quarter[1]) - 1


def year_ago(period: str) -> str:
    return f"{period[:2]} {int(period[-4:]) - 1}"


def close(a: float | None, b: float | None, tol: float = 1e-5) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tol


# ── the page's quantities, recomputed ────────────────────────────────────────
def scored_record(st: dict) -> list[dict]:
    """One row per guided quarter, each actual on the basis it was guided on."""
    g = st["guidance_history"]
    like = g.get("like_for_like_actuals", {})
    rows = []
    for i, quarter in enumerate(g["quarters"]):
        revenue = g["actual_revenue_usd_m"][i]
        gross = g["actual_non_gaap_gross_profit_usd_m"][i]
        opex = g["actual_non_gaap_opex_usd_m"][i]
        if quarter in like:
            revenue = like[quarter]["revenue_usd_m"]
            gross = like[quarter]["non_gaap_gross_profit_usd_m"]
            opex = gross - like[quarter]["non_gaap_operating_income_usd_m"]
        rows.append({
            "q": quarter,
            "low": g["revenue_low_usd_m"][i], "mid": g["revenue_mid_usd_m"][i],
            "high": g["revenue_high_usd_m"][i], "rev": revenue,
            "gm": None if revenue is None else round(gross / revenue * 100, 2),
            "gm_raw": None if revenue is None else gross / revenue * 100,
            "gm_guide": g["non_gaap_gm_guide_pct"][i],
            "opex": opex, "opex_guide": g["non_gaap_opex_guide_usd_m"][i],
        })
    return rows


def revenue_tally(rows: list[dict]) -> tuple[int, int, int, int]:
    done = [r for r in rows if r["rev"] is not None]
    above = sum(1 for r in done if r["rev"] > r["high"])
    below = sum(1 for r in done if r["rev"] < r["low"])
    return len(done), above, len(done) - above - below, below


def opex_scored(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["rev"] is not None and r["opex_guide"] is not None]


def opex_streak(rows: list[dict]) -> int:
    streak = 0
    for r in reversed(opex_scored(rows)):
        if r["opex"] <= r["opex_guide"]:
            break
        streak += 1
    return streak


def revenue_growth(st: dict) -> list[float]:
    """YoY on one basis at a time: ASC 605 both ends for 2016 and 2017."""
    periods, fin = st["periods"], st["financials"]
    revenue = fin["revenue_usd_m"]
    index = {q: i for i, q in enumerate(periods)}
    asc605 = dict(zip(st["asc605_2017"]["quarters"], st["asc605_2017"]["revenue_usd_m"]))
    out = []
    for i, quarter in enumerate(periods):
        year = int(quarter[-4:])
        if year == 2016:
            out.append(pct(revenue[i], fin["revenue_prior_year_2015_usd_m"][int(quarter[1]) - 1]))
        elif year == 2017:
            out.append(pct(asc605[quarter], revenue[index[year_ago(quarter)]]))
        else:
            out.append(pct(revenue[i], revenue[index[year_ago(quarter)]]))
    return out


def gross_margin(st: dict) -> list[float]:
    fin = st["financials"]
    return [g / r * 100 for g, r in zip(fin["non_gaap_gross_profit_usd_m"], fin["revenue_usd_m"])]


def payable_days(st: dict) -> list[float]:
    cost = st["financials"]["cost_of_sales_usd_m"]
    return [p / c * DAYS_PER_QUARTER
            for p, c in zip(st["balance_sheet_usd_m"]["payables_incl_related"], cost)]


def inventory_days(st: dict) -> list[float]:
    cost = st["financials"]["cost_of_sales_usd_m"]
    return [v / c * DAYS_PER_QUARTER for v, c in zip(st["balance_sheet_usd_m"]["inventory"], cost)]


# ═════════════════════════════════════════════════════════════════════════════
class AmdSeriesTest(unittest.TestCase):
    """The source series, before any chart is built."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.st = load()
        cls.periods = cls.st["periods"]
        cls.fin = cls.st["financials"]
        cls.index = {q: i for i, q in enumerate(cls.periods)}

    def test_every_quarterly_array_is_as_long_as_the_period_axis(self) -> None:
        width = len(self.periods)
        for key in ("period_ends", "release_dates", "release_accessions"):
            self.assertEqual(len(self.st[key]), width, key)
        for group in ("financials", "cash_flow_usd_m", "balance_sheet_usd_m"):
            for name, values in self.st[group].items():
                if name == "revenue_prior_year_2015_usd_m":
                    continue
                with self.subTest(series=f"{group}.{name}"):
                    self.assertEqual(len(values), width)
                    self.assertNotIn(None, values)
        # the one short array is the 2015 base for the 2016 growth rates
        self.assertEqual(len(self.fin["revenue_prior_year_2015_usd_m"]),
                         sum(1 for q in self.periods if q.endswith("2016")))
        for block in ("segments", "segments_legacy", "working_capital_cash_flow_usd_m",
                      "purchase_commitments_usd_m", "asc605_2017"):
            b = self.st[block]
            for name, values in b.items():
                if isinstance(values, list):
                    with self.subTest(series=f"{block}.{name}"):
                        self.assertEqual(len(values), len(b["quarters"]))

    def test_quarters_are_contiguous_and_end_on_the_saturday_the_notes_describe(self) -> None:
        """AMD's quarter ends on a Saturday; two fourth quarters ran 14 weeks.

        The page's notes say which two. That is checked against the gaps
        between the filed period-end dates rather than trusted.
        """
        numbers = [order(q) for q in self.periods]
        self.assertEqual(numbers, list(range(numbers[0], numbers[0] + len(numbers))))
        self.assertEqual(self.periods[0], "Q1 2016")
        ends = [datetime.date.fromisoformat(e) for e in self.st["period_ends"]]
        for quarter, end in zip(self.periods, ends):
            calendar_end = datetime.date(int(quarter[-4:]), int(quarter[1]) * 3, 1)
            calendar_end = (calendar_end.replace(day=28) + datetime.timedelta(days=4))
            calendar_end -= datetime.timedelta(days=calendar_end.day)
            with self.subTest(quarter=quarter):
                self.assertEqual(end.weekday(), 5, "not a Saturday")
                self.assertLessEqual(abs((end - calendar_end).days), 6)
        lengths = {self.periods[i]: (ends[i] - ends[i - 1]).days for i in range(1, len(ends))}
        long = sorted(q for q, days in lengths.items() if days == 98)
        self.assertTrue(set(lengths.values()) <= {91, 98})
        self.assertTrue(all(q.startswith("Q4") for q in long))
        years = " 年与 ".join(q[-4:] for q in long)
        notes = " ".join(amd.build_payload(self.st)["notes"])
        self.assertIn(f"{years} 年的第四季各为 14 周", notes)

    def test_every_release_follows_its_quarter_and_names_its_own_accession(self) -> None:
        for quarter, end, released, accession in zip(self.periods, self.st["period_ends"],
                                                      self.st["release_dates"],
                                                      self.st["release_accessions"]):
            with self.subTest(quarter=quarter):
                self.assertGreater(released, end)
                self.assertRegex(accession, rf"^0000002488-{released[2:4]}-\d{{6}}$")
        # The release that reports a quarter is the one that guides the next.
        guided = self.st["guidance_history"]
        for k in range(1, len(guided["quarters"])):
            with self.subTest(guided=guided["quarters"][k]):
                self.assertEqual(guided["release_dates"][k], self.st["release_dates"][k - 1])

    def test_gaap_gross_profit_is_revenue_less_total_cost_of_sales(self) -> None:
        """And the ex-amortisation cost line the day-counts use sits under it.

        `cost_of_sales_usd_m` excludes amortisation of acquired intangibles; it
        equals the total until Xilinx closed, and is below it every quarter
        after (the margin chart's note says the gap opened in 2022).
        """
        fin = self.fin
        for i, quarter in enumerate(self.periods):
            with self.subTest(quarter=quarter):
                self.assertEqual(fin["revenue_usd_m"][i] - fin["total_cost_of_sales_usd_m"][i],
                                 fin["gaap_gross_profit_usd_m"][i])
                if int(quarter[-4:]) < 2022:
                    self.assertEqual(fin["cost_of_sales_usd_m"][i], fin["total_cost_of_sales_usd_m"][i])
                else:
                    self.assertLess(fin["cost_of_sales_usd_m"][i], fin["total_cost_of_sales_usd_m"][i])

    def test_the_four_segments_sum_to_revenue_every_quarter(self) -> None:
        seg = self.st["segments"]
        self.assertEqual(seg["quarters"][-1], self.periods[-1])
        self.assertEqual(seg["quarters"], self.periods[self.index[seg["quarters"][0]]:])
        for k, quarter in enumerate(seg["quarters"]):
            parts = sum(seg[key][k] for key in ("data_center_usd_m", "client_usd_m",
                                                 "gaming_usd_m", "embedded_usd_m"))
            with self.subTest(quarter=quarter):
                self.assertEqual(parts, self.fin["revenue_usd_m"][self.index[quarter]])

    def test_segment_operating_income_closes_to_gaap_operating_income(self) -> None:
        """All Other carries what the segments exclude, so the four close exactly."""
        seg = self.st["segments"]
        for k, quarter in enumerate(seg["quarters"]):
            parts = sum(seg[key][k] for key in ("data_center_oi_usd_m", "client_gaming_oi_usd_m",
                                                 "embedded_oi_usd_m", "all_other_oi_usd_m"))
            with self.subTest(quarter=quarter):
                self.assertEqual(parts, self.fin["gaap_operating_income_usd_m"][self.index[quarter]])

    def test_the_two_old_segments_sum_to_revenue_every_quarter(self) -> None:
        """Including the three quarters both structures print."""
        old = self.st["segments_legacy"]
        self.assertEqual(old["quarters"], self.periods[:len(old["quarters"])])
        for k, quarter in enumerate(old["quarters"]):
            with self.subTest(quarter=quarter):
                self.assertEqual(old["computing_graphics_revenue_usd_m"][k] + old["eesc_revenue_usd_m"][k],
                                 self.fin["revenue_usd_m"][self.index[quarter]])
        overlap = set(old["quarters"]) & set(self.st["segments"]["quarters"])
        self.assertGreaterEqual(len(overlap), 1, "the two structures stopped overlapping")

    def test_free_cash_flow_is_operating_cash_flow_less_capex(self) -> None:
        cash = self.st["cash_flow_usd_m"]
        for i, quarter in enumerate(self.periods):
            with self.subTest(quarter=quarter):
                self.assertEqual(cash["operating"][i] - cash["capex"][i], cash["free_cash_flow"][i])

    def test_the_payables_basis_is_consistent_across_the_reclassification(self) -> None:
        """Related-party payables were folded into accounts payable; once the
        two lines agree they must keep agreeing, and before that the combined
        line the day-count uses must be the larger."""
        bal = self.st["balance_sheet_usd_m"]
        both, ap = bal["payables_incl_related"], bal["accounts_payable"]
        merged = next(i for i in range(len(both)) if all(both[j] == ap[j] for j in range(i, len(both))))
        self.assertGreater(merged, 0)
        for i in range(merged):
            with self.subTest(quarter=self.periods[i]):
                self.assertGreater(both[i], ap[i])

    def test_the_eps_block_agrees_with_the_series_it_sits_beside(self) -> None:
        """Two readings of the same three quarters: the reconciliation table and
        the income-statement arrays. Matched by label, never by position."""
        block = self.st.get("eps_reconciliation")
        if block is None:
            self.skipTest("this quarter has no EPS reconciliation block")
        fin, shares = self.fin, self.fin["diluted_shares_m"]
        for k, quarter in enumerate(block["quarters"]):
            i = self.index[quarter]
            with self.subTest(quarter=quarter):
                self.assertEqual(block["gaap_eps_usd"][k], fin["gaap_eps_diluted_usd"][i])
                self.assertEqual(block["non_gaap_eps_usd"][k], fin["non_gaap_eps_usd"][i])
                self.assertEqual(block["gaap_net_income_usd_m"][k], fin["gaap_net_income_usd_m"][i])
                per_share = block["long_term_investment_gains_usd_m"][k] / shares[i]
                self.assertLessEqual(abs(per_share - block["long_term_investment_gains_per_share_usd"][k]),
                                     0.005 + 1e-9)
        self.assertEqual(set(block["quarters"]),
                         {self.periods[-1], self.periods[-2], year_ago(self.periods[-1])})


# ═════════════════════════════════════════════════════════════════════════════
class AmdGuidanceRecordTest(unittest.TestCase):
    """The guided record, and every tally the page prints from it."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.st = load()
        cls.g = cls.st["guidance_history"]
        cls.rows = scored_record(cls.st)
        cls.payload = amd.build_payload(cls.st)
        cls.done = [r for r in cls.rows if r["rev"] is not None]

    def assert_tally(self, text: str, word: str, count: int) -> None:
        if count:
            self.assertRegex(text, rf"(?<!\d){count} 季{word}")
        else:
            self.assertNotRegex(text, rf"\d+ 季{word}")

    def test_the_record_ends_one_quarter_past_the_series(self) -> None:
        g, periods = self.g, self.st["periods"]
        self.assertEqual(g["quarters"][:-1], periods)
        self.assertEqual(order(g["quarters"][-1]), order(periods[-1]) + 1)
        for name, values in g.items():
            if isinstance(values, list):
                with self.subTest(series=name):
                    self.assertEqual(len(values), len(g["quarters"]))
        for key in ("actual_revenue_usd_m", "actual_non_gaap_gross_profit_usd_m",
                    "actual_non_gaap_opex_usd_m"):
            self.assertIsNone(g[key][-1], key)
            self.assertNotIn(None, g[key][:-1], key)
        self.assertEqual(self.st["guidance"]["next_quarter"]["period"], g["quarters"][-1])

    def test_the_sequential_era_ranges_are_computed_from_the_printed_base(self) -> None:
        """Through the Q4 2017 outlook the release gave a percentage, not dollars.

        The dollar range is this page's arithmetic on the base that release
        itself printed -- the prior quarter's first print (for Q1 2016, Q4
        2015 as printed). Recomputed here to the cent.
        """
        g = self.g
        forms = g["form"]
        first_usd = forms.index("usd")
        self.assertEqual(forms, ["sequential_pct"] * first_usd + ["usd"] * (len(forms) - first_usd))
        self.assertGreater(first_usd, 0)
        for i in range(len(forms)):
            low, mid, high = g["revenue_low_usd_m"][i], g["revenue_mid_usd_m"][i], g["revenue_high_usd_m"][i]
            with self.subTest(quarter=g["quarters"][i]):
                if forms[i] == "sequential_pct":
                    base, step, band = (g["sequential_base_usd_m"][i], g["sequential_pct"][i],
                                        g["sequential_band_pct"][i])
                    self.assertAlmostEqual(mid, base * (1 + step / 100), places=2)
                    self.assertAlmostEqual(low, base * (1 + (step - band) / 100), places=2)
                    self.assertAlmostEqual(high, base * (1 + (step + band) / 100), places=2)
                    printed_base = (self.st["financials"]["revenue_prior_year_2015_usd_m"][3] if i == 0
                                    else g["actual_revenue_usd_m"][i - 1])
                    self.assertEqual(base, printed_base)
                else:
                    for key in ("sequential_base_usd_m", "sequential_pct", "sequential_band_pct"):
                        self.assertIsNone(g[key][i], key)
                    self.assertGreater(high - mid, 0)
                    self.assertEqual(high - mid, mid - low)
        band = one(self.payload, "收入：", "range_band")
        self.assertIn(f"{compact(g['quarters'][0])}–{compact(g['quarters'][first_usd - 1])} 的指引是"
                      f"「环比 ±{g['sequential_band_pct'][0]} 个百分点」", band["note"])
        self.assertIn(f"自 {compact(g['quarters'][first_usd])} 起公司直接给美元区间", band["note"])

    def test_each_quarter_is_scored_against_its_own_first_print(self) -> None:
        """The record's actuals are first prints; the level series are latest prints.

        Where the two differ the reason has to be one the page names: the 2017
        quarters (ASC 605 as first printed, ASC 606 as restated) and one year of
        opex that a later release printed lower.
        """
        g, fin, periods = self.g, self.st["financials"], self.st["periods"]
        asc605 = self.st["asc605_2017"]
        revenue_diff, gross_diff, opex_diff = set(), set(), {}
        for i, quarter in enumerate(periods):
            if g["actual_revenue_usd_m"][i] != fin["revenue_usd_m"][i]:
                revenue_diff.add(quarter)
            if g["actual_non_gaap_gross_profit_usd_m"][i] != fin["non_gaap_gross_profit_usd_m"][i]:
                gross_diff.add(quarter)
            if g["actual_non_gaap_opex_usd_m"][i] != fin["non_gaap_opex_usd_m"][i]:
                opex_diff[quarter] = (g["actual_non_gaap_opex_usd_m"][i], fin["non_gaap_opex_usd_m"][i])
        self.assertEqual(revenue_diff, set(asc605["quarters"]))
        self.assertTrue(gross_diff <= set(asc605["quarters"]))
        for k, quarter in enumerate(asc605["quarters"]):
            i = periods.index(quarter)
            self.assertEqual(g["actual_revenue_usd_m"][i], asc605["revenue_usd_m"][k], quarter)
            self.assertEqual(g["actual_non_gaap_gross_profit_usd_m"][i],
                             asc605["non_gaap_gross_profit_usd_m"][k], quarter)
        years = {int(q[-4:]) for q in opex_diff}
        self.assertEqual(len(years), 1, opex_diff)
        (year,) = years
        self.assertEqual(sorted(opex_diff), [f"Q{n} {year}" for n in (1, 2, 3, 4)])
        for quarter, (first, latest) in opex_diff.items():
            self.assertGreater(first, latest, f"{quarter} was re-printed lower, per the note")
        opex = one(self.payload, "non-GAAP 营业费用：", "range_band")
        self.assertIn(f"{year + 1} 年的新闻稿曾把 {year} 年各季的 non-GAAP 营业费用下调重印", opex["note"])

    def test_the_revenue_tally_is_recounted_in_the_title_and_the_section(self) -> None:
        finished, above, inside, below = revenue_tally(self.rows)
        band = one(self.payload, "收入：", "range_band")
        self.assertIn(f"{finished} 个已完结季", band["title"])
        self.assert_tally(band["title"], "超出上限", above)
        self.assert_tally(band["title"], "落在区间内", inside)
        self.assert_tally(band["title"], "跌破下限", below)
        for key, got in (("lo", "low"), ("hi", "high"), ("actual", "rev")):
            wanted = [None if r[got] is None else r[got] / 1000 for r in self.rows]
            for a, b in zip(band[key], wanted):
                self.assertTrue(close(a, b), (key, a, b))
        scored = opex_scored(self.rows)
        over = sum(1 for r in scored if r["opex"] > r["opex_guide"])
        description = self.payload["sections"][0]["description"]
        self.assertIn(f"{cn(finished)}个已完结季里收入 {above} 季超出上限、{inside} 季落在区间内、"
                      f"{below} 季跌破下限；有费用指引的 {len(scored)} 季里 {over} 季花得比指引多",
                      description)
        last = self.done[-1]
        word = ("超出上限" if last["rev"] > last["high"] else
                "跌破下限" if last["rev"] < last["low"] else "落在区间内")
        self.assertIn(f"本季 {compact(last['q'])} 实际 {usd_m(last['rev'])}，{word}", band["note"])

    def test_the_revenue_deviation_chart_is_recomputed(self) -> None:
        chart = one(self.payload, "收入相对指引中值的偏离", "grouped_bars")
        mids = [(r["low"] + r["high"]) / 2 for r in self.done]
        for r, m in zip(self.done, mids):
            self.assertAlmostEqual(r["mid"], m, places=2, msg=r["q"])
        deviation = [pct(r["rev"], m) for r, m in zip(self.done, mids)]
        self.assertEqual(chart["xlabels"], [compact(r["q"]) for r in self.done])
        for got, wanted in zip(chart["groups"][0]["values"], deviation):
            self.assertTrue(close(got, wanted), (got, wanted))
        positive = sum(1 for d in deviation if d > 0)
        mean = statistics.fmean(abs(d) for d in deviation)
        self.assertIn(f"{len(deviation)} 季里 {positive} 季为正，平均绝对偏离 {mean:.1f}%", chart["title"])

    def test_the_annotations_that_make_claims_are_arithmetic(self) -> None:
        """Annotations in the series that state things the record can check.

        A 「唯一」 is a universal claim over the record, so if one is ever
        written it is recounted; the two arithmetic ones are always checked.
        """
        band = one(self.payload, "收入：", "range_band")
        g = self.g
        by_q = {r["q"]: r for r in self.rows}
        below = [r["q"] for r in self.done if r["rev"] < r["low"]]
        seen = {"only": 0, "net": 0, "like": 0}
        for quarter, text in g["revenue_annotations"].items():
            self.assertIn(f"{compact(quarter)}：{text}", band["note"])
            if "唯一跌破下限" in text:
                seen["only"] += 1
                self.assertEqual(below, [quarter], "「唯一」 is a universal claim over the record")
            m = re.search(r"约 US\$([\d,]+)M 是.*?扣掉它约为 US\$([\d,]+)M（D），落在区间内", text)
            if m:
                seen["net"] += 1
                first = g["actual_revenue_usd_m"][g["quarters"].index(quarter)]
                excluded, net = (int(x.replace(",", "")) for x in m.groups())
                self.assertEqual(first - excluded, net)
                self.assertTrue(by_q[quarter]["low"] <= net <= by_q[quarter]["high"])
        for quarter, like in g["like_for_like_actuals"].items():
            seen["like"] += 1
            text = g["revenue_annotations"][quarter]
            reported = g["actual_revenue_usd_m"][g["quarters"].index(quarter)]
            self.assertIn(usd_m(like["revenue_usd_m"]), text)
            self.assertIn(usd_m(reported), text)
            if "仍高于区间上限" in text:
                self.assertGreater(like["revenue_usd_m"], by_q[quarter]["high"])
        self.assertGreaterEqual(seen["net"], 1, "an annotation this test reads went away")
        self.assertGreaterEqual(seen["like"], 1, "an annotation this test reads went away")

    def test_the_gross_margin_tally_is_scored_at_two_decimals(self) -> None:
        """Scored at the two decimals the page prints -- and that rule changes
        the answer, which is why it is pinned rather than assumed."""
        done = self.done
        dev = [r["gm"] - r["gm_guide"] for r in done]
        above, below, same = (sum(1 for d in dev if d > 0), sum(1 for d in dev if d < 0),
                              sum(1 for d in dev if d == 0))
        raw = [r["gm_raw"] - r["gm_guide"] for r in done]
        self.assertNotEqual((above, below, same),
                            (sum(1 for d in raw if d > 0), sum(1 for d in raw if d < 0),
                             sum(1 for d in raw if d == 0)),
                            "the two-decimal rule no longer matters; this test went quiet")
        band = one(self.payload, "non-GAAP 毛利率：", "range_band")
        self.assertIn(f"{len(done)} 个已完结季", band["title"])
        self.assert_tally(band["title"], "高于指引", above)
        self.assert_tally(band["title"], "低于指引", below)
        self.assert_tally(band["title"], "与指引完全相同", same)
        near = sum(1 for d in dev if abs(d) < 0.5)
        self.assertIn(f"{cn(len(done))}季里 {near} 季与指引相差不到 0.5pp", band["note"])
        up = max(range(len(done)), key=lambda i: dev[i])
        down = min(range(len(done)), key=lambda i: dev[i])
        self.assertIn(f"最大的正偏离是 {compact(done[up]['q'])} 的 {signed(dev[up], 2, 'pp')}", band["note"])
        self.assertIn(f"最大的负偏离是 {compact(done[down]['q'])} 的 {signed(dev[down], 2, 'pp')}",
                      band["note"])
        chart = one(self.payload, "non-GAAP 毛利率相对指引中值的偏离", "grouped_bars")
        for got, wanted in zip(chart["groups"][0]["values"], dev):
            self.assertTrue(close(got, wanted), (got, wanted))
        mean = statistics.fmean(abs(d) for d in dev)
        self.assertIn(f"{len(dev)} 季里 {above} 季为正，平均绝对偏离 {mean:.1f}pp", chart["title"])

    def test_the_opex_tally_and_streak_are_recounted(self) -> None:
        """Opex is scored on the like-for-like quarter too, and there it flips."""
        scored = opex_scored(self.rows)
        over = [r for r in scored if r["opex"] > r["opex_guide"]]
        under = [r for r in scored if r["opex"] < r["opex_guide"]]
        same = len(scored) - len(over) - len(under)
        band = one(self.payload, "non-GAAP 营业费用：", "range_band")
        self.assertIn(f"{len(scored)} 个已完结季", band["title"])
        self.assert_tally(band["title"], "高于指引", len(over))
        self.assert_tally(band["title"], "低于指引", len(under))
        self.assert_tally(band["title"], "与指引完全相同", same)
        # the like-for-like basis decides at least one quarter's side
        g = self.g
        flipped = [q for q, like in g["like_for_like_actuals"].items()
                   if (g["actual_non_gaap_opex_usd_m"][g["quarters"].index(q)] >
                       g["non_gaap_opex_guide_usd_m"][g["quarters"].index(q)])
                   != (like["non_gaap_gross_profit_usd_m"] - like["non_gaap_operating_income_usd_m"] >
                       g["non_gaap_opex_guide_usd_m"][g["quarters"].index(q)])]
        self.assertTrue(flipped, "no quarter's opex side depends on the like-for-like basis any more")
        streak = opex_streak(self.rows)
        run = (f"（{compact(scored[-streak]['q'])}–{compact(scored[-1]['q'])}）" if streak > 1 else "")
        self.assertIn(f"<b>最近 {streak} 季连续高于自己的指引</b>{run}", band["note"])
        gaps = [r["q"] for r in self.done if r["opex_guide"] is None]
        if gaps:
            self.assertEqual([order(q) for q in gaps], list(range(order(gaps[0]), order(gaps[0]) + len(gaps))))
            self.assertIn(f"{compact(gaps[0])}–{compact(gaps[-1])} 这 {len(gaps)} 季", band["note"])
        docs = g["opex_guide_document"]
        self.assertEqual([d is None for d in docs], [v is None for v in g["non_gaap_opex_guide_usd_m"]])
        first_slides = next(i for i, d in enumerate(docs) if d and d.startswith("业绩幻灯片"))
        self.assertIn(f"{compact(g['quarters'][first_slides])} 起写在业绩幻灯片", band["note"])
        chart = one(self.payload, "non-GAAP 营业费用相对指引中值的偏离", "grouped_bars")
        deviation = [pct(r["opex"], r["opex_guide"]) for r in scored]
        for got, wanted in zip(chart["groups"][0]["values"], deviation):
            self.assertTrue(close(got, wanted), (got, wanted))
        mean = statistics.fmean(abs(d) for d in deviation)
        self.assertIn(f"{len(deviation)} 季里 {sum(1 for d in deviation if d > 0)} 季为正，"
                      f"平均绝对偏离 {mean:.1f}%", chart["title"])
        if self.st.get("followup_closure") is not None:
            closure = one(self.payload, "上季 ", "bars_labeled")
            self.assertIn(f"连续{cn(streak)}季花得比自己的费用指引多", closure["note"])

    def test_every_guide_was_published_after_its_quarter_began(self) -> None:
        """The record is not ex-ante, and every band chart says by how much."""
        ends = dict(zip(self.st["periods"], self.st["period_ends"]))
        lags = []
        for k in range(1, len(self.g["quarters"])):
            previous = self.g["quarters"][k - 1]
            start = datetime.date.fromisoformat(ends[previous]) + datetime.timedelta(days=1)
            lags.append((datetime.date.fromisoformat(self.g["release_dates"][k]) - start).days)
        self.assertTrue(all(lag > 0 for lag in lags), lags)
        bands = [ex for ex in exhibits_of(self.payload) if ex["kind"] == "range_band"]
        self.assertEqual(len(bands), 3)
        for band in bands:
            with self.subTest(chart=band["title"][:12]):
                self.assertIn(f"被指引季度开始 {min(lags)}–{max(lags)} 天后", band["note"])

    def test_the_full_record_table_covers_every_guided_quarter(self) -> None:
        g = self.g
        tbl = table(self.payload, "指引兑现全表")
        self.assertIn(f"（{len(g['quarters'])} 季，含尚未完结的一季）", tbl["title"])
        self.assertEqual([row[0] for row in tbl["rows"]], g["quarters"])
        for i, (row, r) in enumerate(zip(tbl["rows"], self.rows)):
            with self.subTest(quarter=r["q"]):
                self.assertEqual(len(row), len(tbl["headers"]))
                sequential = g["form"][i] == "sequential_pct"
                self.assertEqual(row[2], f"{usd_m(r['low'])} – {usd_m(r['high'])}" + (" D" if sequential else ""))
                if sequential:
                    self.assertEqual(row[1], f"环比 {signed(g['sequential_pct'][i], 0)} "
                                             f"±{g['sequential_band_pct'][i]}pp")
                else:
                    self.assertTrue(row[1].endswith(f"± US${r['high'] - r['mid']:.0f}M"), row[1])
                if r["rev"] is None:
                    self.assertEqual(row[3:5] + row[6:8], ["—"] * 4)
                    continue
                self.assertEqual(row[3], usd_m(r["rev"]))
                self.assertEqual(row[4], "高于上限" if r["rev"] > r["high"] else
                                 "低于下限" if r["rev"] < r["low"] else "区间内")
                self.assertEqual(row[6], f"{r['gm']:.2f}% D")
                self.assertEqual(row[7], signed(r["gm"] - r["gm_guide"], 2, "pp") + " D")
                if r["opex_guide"] is None:
                    self.assertEqual(row[8:], ["—", "—"])
                else:
                    self.assertEqual(row[9], usd_m(r["opex"]))

    def test_the_quarter_table_and_the_guidance_box_are_recomputed(self) -> None:
        st, rows = self.st, self.rows
        fin = st["financials"]
        revenue = fin["revenue_usd_m"]
        index = {q: i for i, q in enumerate(st["periods"])}
        now = rows[-2]
        gm_now = fin["non_gaap_gross_profit_usd_m"][-1] / revenue[-1] * 100
        nq = st["guidance"]["next_quarter"]
        tbl = table(self.payload, "兑现与")
        self.assertEqual(tbl["title"], f"{st['periods'][-1]} 兑现与 {nq['period']} 指引")
        rev_row, gm_row = tbl["rows"]
        dev = pct(now["rev"], now["mid"])
        self.assertEqual(rev_row, [
            "收入", f"{usd_m(now['low'])} – {usd_m(now['high'])}", usd_m(revenue[-1]),
            (f"高于中值 {dev:.1f}% D" if dev > 0 else f"低于中值 {abs(dev):.1f}% D"),
            f"US${nq['revenue_usd_m'] / 1000:g}B ± US${nq['revenue_band_usd_m']}M"])
        self.assertEqual(gm_row[2], f"{gm_now:.2f}% D")
        self.assertEqual(gm_row[3], signed(now["gm"] - now["gm_guide"], 2, "pp") + " D")
        # The box: the outlook block and the record's last row are one outlook.
        last = rows[-1]
        self.assertEqual(nq["revenue_usd_m"], last["mid"])
        self.assertEqual(nq["revenue_band_usd_m"], last["high"] - last["mid"])
        self.assertEqual(nq["non_gaap_gm_pct"], last["gm_guide"])
        box = self.payload["guidance"]
        self.assertEqual(box["title"], f"下季指引（{nq['period']}）")
        rows_by = {row[0]: row for row in box["rows"]}
        ya = index[year_ago(nq["period"])]
        self.assertEqual(rows_by["收入"][2], signed(pct(nq["revenue_usd_m"], revenue[-1])) + " D")
        self.assertEqual(rows_by["收入"][3], signed(pct(nq["revenue_usd_m"], revenue[ya])) + " D")
        self.assertEqual(rows_by["non-GAAP 毛利率"][2], signed(nq["non_gaap_gm_pct"] - gm_now, 2, "pp") + " D")
        # the slides line for opex is the record's opex guide, in another spelling
        self.assertEqual(rows_by["non-GAAP 营业费用"][1], f"约 US${last['opex_guide'] / 1000:.2f}B")
        self.assertEqual(len(box["rows"]), 2 + len(st["guidance"]["slides_only"]["items"]))


# ═════════════════════════════════════════════════════════════════════════════
class AmdExhibitContractTest(unittest.TestCase):
    """What the renderer needs from every exhibit, and what the page may not print."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.st = load()
        cls.payload = amd.build_payload(cls.st)
        cls.exhibits = exhibits_of(cls.payload)

    def test_four_sections_in_order_and_every_chart_is_sourced(self) -> None:
        self.assertEqual([s["id"] for s in self.payload["sections"]],
                         ["settled", "quarter_highlights", "next_quarter", "routine"])
        for section in self.payload["sections"]:
            self.assertTrue(section["exhibits"], section["id"])
        for ex in self.exhibits:
            with self.subTest(exhibit=ex["n"]):
                self.assertTrue(ex.get("note"))
                self.assertTrue(ex.get("src_extra"))
                self.assertNotIn("ref", ex)

    def test_section_descriptions_name_only_the_charts_present(self) -> None:
        """Sections two and three describe what they hold; their clauses are
        tied to the charts, and the drop cases are exercised in AmdRollTest."""
        sections = {s["id"]: s for s in self.payload["sections"]}
        titles = [ex["title"] for ex in sections["quarter_highlights"]["exhibits"]]
        self.assertEqual("在净利处的分叉" in sections["quarter_highlights"]["description"],
                         any(t.startswith("GAAP 每股收益环比") for t in titles))
        self.assertEqual("没有上表的承诺" in sections["quarter_highlights"]["description"],
                         any(t.startswith("无条件采购承诺一季") for t in titles))
        nxt = sections["next_quarter"]
        thresholds = [ex for ex in nxt["exhibits"] if "警戒线" in ex["title"]]
        self.assertEqual(len(thresholds), len(self.st["next_kpi"]["quantified"]))
        self.assertIn(f"{cn(len(thresholds))}条能从 AMD 自己的申报文件算出水平的阈值", nxt["description"])
        self.assertEqual("「加速」翻成算术" in nxt["description"],
                         any("数据中心会「加速」" in ex["title"] for ex in nxt["exhibits"]))
        self.assertEqual("无条件采购承诺走到了哪里" in nxt["description"],
                         any(ex["title"].startswith("无条件采购承诺 US$") for ex in nxt["exhibits"]))
        routine = sections["routine"]["description"]
        self.assertIn(f"{compact(self.st['periods'][0])} 起 {len(self.st['periods'])} 季", routine)

    def test_every_kind_colour_and_format_is_one_the_renderer_knows(self) -> None:
        """All three sets are read from `assets/charts.js`, not typed here."""
        source = CHARTS.read_text(encoding="utf-8")
        kinds = set(re.findall(r"kind === '([a-z_0-9]+)'", source))
        colours = renderer_names("var C = {")
        formats = renderer_names("var FMT = {")
        self.assertTrue({"NAVY", "GOLD", "RED"} <= colours and {"usd1", "pct1", "f0"} <= formats,
                        "the renderer tables moved; this test stopped reading them")
        for ex in self.exhibits:
            self.assertIn(ex["kind"], kinds, ex["title"])

        def walk(node, where):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in ("color", "actual_color") and isinstance(value, str):
                        self.assertIn(value, colours, where)
                    if key in ("fmt", "yfmt", "label_fmt") and isinstance(value, str):
                        self.assertIn(value, formats, where)
                    walk(value, where)
            elif isinstance(node, list):
                for item in node:
                    walk(item, where)
        for ex in self.exhibits:
            walk(ex, ex["title"])

    def test_every_index_addressed_series_is_as_long_as_its_axis(self) -> None:
        for ex in self.exhibits:
            n = len(ex["xlabels"])
            blocks = [(key, ex[key]) for key in ("values", "lo", "hi", "actual") if isinstance(ex.get(key), list)]
            for key in ("yoy", "line", "bar"):
                if isinstance(ex.get(key), dict):
                    blocks.append((key, ex[key]["values"]))
            for key in ("groups", "series", "stacks"):
                for i, block in enumerate(ex.get(key) or []):
                    blocks.append((f"{key}[{i}]", block["values"]))
            self.assertTrue(blocks, ex["title"])
            for name, values in blocks:
                with self.subTest(exhibit=ex["n"], block=name):
                    self.assertEqual(len(values), n)

    def test_exhibits_and_tables_are_numbered_in_render_order(self) -> None:
        numbers = [ex["n"] for ex in self.exhibits]
        self.assertEqual(numbers, list(range(2, 2 + len(numbers))))
        tables = self.payload["tables"]
        self.assertEqual([t["n"] for t in tables], list(range(numbers[-1] + 1, numbers[-1] + 1 + len(tables))))
        cross = [t for t in tables if "跨页对照" in t["title"]]
        self.assertEqual(len(cross), 1)
        self.assertIs(tables[-1], cross[0], "the shared table closes the drawer")
        for t in tables:
            for row in t["rows"]:
                self.assertEqual(len(row), len(t["headers"]), t["title"])

    def test_the_renderer_branches_this_page_reaches_are_safe(self) -> None:
        """Zero-floored kinds carry no negative bar; each stacked_dual declares
        its ceiling inside `line` (a top-level ymax is read by nothing); the one
        gs_bar carries a yoy line and no average (CLAUDE.md §6)."""
        for ex in self.exhibits:
            if ex["kind"] in ZERO_FLOORED_KINDS:
                values = list(ex.get("values") or [])
                for block in ex.get("stacks") or []:
                    values += block["values"]
                with self.subTest(exhibit=ex["n"]):
                    self.assertEqual([v for v in values if v is not None and v < 0], [])
        duals = [ex for ex in self.exhibits if ex["kind"] == "stacked_dual"]
        self.assertEqual(len(duals), 2)
        for ex in duals:
            self.assertNotIn("ymax", ex)
            self.assertGreaterEqual(ex["line"]["ymax"], max(ex["line"]["values"]))
        bars = [ex for ex in self.exhibits if ex["kind"] == "gs_bar"]
        self.assertEqual(len(bars), 1, "a second gs_bar changes the census in test_chart_contract")
        self.assertIn("yoy", bars[0])
        self.assertNotIn("avg12", bars[0])

    def test_literal_slots_carry_no_markup(self) -> None:
        """Slots written with textContent or esc() print a tag as six characters
        (CLAUDE.md §7); exhibit titles also land in aria-labels."""
        p = self.payload
        literal = [("headline", p["headline"]), ("title", p["title"]), ("subtitle", p["subtitle"]),
                   ("tracker", p["tracker"])]
        literal += [("notes", n) for n in p["notes"]]
        for s in p["sections"]:
            literal += [("section.title", s["title"]), ("section.description", s["description"])]
        for t in p["tables"]:
            literal += [("table.title", t["title"])]
            literal += [("table.cell", c) for c in t["headers"] + [c for row in t["rows"] for c in row]]
        if p["guidance"]:
            literal += [("guidance", c) for c in strings(p["guidance"])]
        for ex in self.exhibits:
            literal += [("exhibit.title", ex["title"])]
            literal += [("exhibit.label", ex[k]) for k in ("legend", "ylab", "ylab2", "annot") if k in ex]
            literal += [("exhibit.xlabel", x) for x in ex["xlabels"]]
            for key in ("groups", "series", "stacks"):
                literal += [("exhibit.name", b["name"]) for b in ex.get(key) or []]
            for key in ("yoy", "line", "bar"):
                if isinstance(ex.get(key), dict):
                    literal.append(("exhibit.name", ex[key]["name"]))
            literal += [("exhibit.name", v) for v in (ex.get("names") or {}).values()]
        self.assertGreater(len(literal), 200)
        for slot, value in literal:
            with self.subTest(slot=slot, value=str(value)[:40]):
                self.assertIsInstance(value, str)
                self.assertIsNone(TAG.search(value))
                self.assertNotIn("**", value)

    def test_no_placeholder_survives_anywhere(self) -> None:
        """Neither a story field (`{dc_yoy}`) nor an exhibit reference (`{EX_…}`)."""
        leaks = [s for s in strings(self.payload) if PLACEHOLDER.search(s)]
        self.assertEqual(leaks, [])
        self.assertNotIn('"ref"', text_of(self.payload))

    def test_every_exhibit_reference_lands_on_the_chart_it_names(self) -> None:
        """A note that says "见 Exhibit N" must reach the right chart after numbering."""
        refers = {"上季 ": "non-GAAP 营业费用：", "数据中心 ": "旧的两分部口径",
                  "经营现金流 ": "应付天数 ", "资本开支 ": "无条件采购承诺一季",
                  "non-GAAP 营业费用占收入": "non-GAAP 营业费用："}
        by_n = {ex["n"]: ex for ex in self.exhibits}
        seen = 0
        for ex in self.exhibits:
            numbers = [int(n) for n in re.findall(r"Exhibit (\d+)", ex["note"])]
            if not numbers:
                continue
            owner = [key for key in refers if ex["title"].startswith(key)]
            self.assertEqual(len(owner), 1, f"undeclared reference in {ex['title']}")
            for n in numbers:
                seen += 1
                with self.subTest(source=ex["n"], target=n):
                    self.assertNotEqual(n, ex["n"])
                    self.assertTrue(by_n[n]["title"].startswith(refers[owner[0]]), by_n[n]["title"])
        self.assertEqual(seen, len(refers), "a cross-reference went missing")

    def test_call_only_statements_and_ratings_stay_off_the_charts(self) -> None:
        """The forward numbers only said on the call are named in the notes as
        excluded, and appear in no chart; the analysis carries no rating."""
        exhibits_text = text_of(self.exhibits)
        for phrase in ("超过翻倍", "2030"):
            self.assertNotIn(phrase, exhibits_text, phrase)
        self.assertTrue(any("只在电话会上说过" in n and "超过翻倍" in n for n in self.payload["notes"]),
                        "the call-only boundary is not declared in the notes")
        analysis = text_of([self.payload["sections"], self.payload["tables"],
                            self.payload["headline"], self.payload["brief"]])
        for term in ("目标价", "评级", "增持", "减持", "市盈率", "估值"):
            self.assertNotIn(term, analysis, term)


# ═════════════════════════════════════════════════════════════════════════════
SECTIONS = [("settled", "一、上季跟踪指标兑现了吗"), ("quarter_highlights", "二、本季重点"),
            ("next_quarter", "三、下季要跟踪什么"), ("routine", "四、长期常规跟踪")]
STATE_WORDS = {"加仓": ("达到加仓线", "没到加仓线"), "减仓": ("没有触发减仓", "触发减仓"),
               "警示": ("没有触发警示", "触发警示"), "核验": ("兑现", "没有兑现")}


def shift(period: str, step: int) -> str:
    k = order(period) + step
    return f"Q{k % 4 + 1} {k // 4}"


def opex_growth_as_printed(st: dict) -> list[float | None]:
    """Each quarter's first print over the year-ago quarter as the series last printed it."""
    g, fin, periods = st["guidance_history"], st["financials"], st["periods"]
    first = dict(zip(g["quarters"], g["actual_non_gaap_opex_usd_m"]))
    newest = dict(zip(periods, fin["non_gaap_opex_usd_m"]))
    return [None if shift(q, -4) not in newest else pct(first[q], newest[shift(q, -4)]) for q in periods]


def favourable_side(direction: str, threshold: float, value: float, strict: bool = False) -> bool:
    if direction == "up":
        return value > threshold if strict else value >= threshold
    return value < threshold if strict else value <= threshold


def direction_from_trigger(trigger: str, action: str) -> str:
    """The note records the side that *triggers* the action; the series the favourable side."""
    triggered_up = trigger in ("≥", ">")
    if action == "加仓":
        return "up" if triggered_up else "down"
    return "down" if triggered_up else "up"


class AmdSettlementTest(unittest.TestCase):
    """Section one against the two analyses: the closure is the Q2 report's section 0,
    the settled lines are the Q1 report's key-metric section, each figure read
    from the series and each report fact from `_checks["note"]`."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.st = load()
        cls.note = cls.st["_checks"]["note"]
        cls.payload = amd.build_payload(cls.st)
        cls.sections = {s["id"]: s for s in cls.payload["sections"]}
        cls.settled = cls.sections["settled"]["exhibits"]
        cls.period = cls.st["periods"][-1]

    def rebuilt(self, edit) -> dict:
        changed = copy.deepcopy(self.st)
        edit(changed)
        self.assertNotEqual(changed, self.st, "the edit changed nothing")
        return amd.build_payload(changed)

    def test_the_four_sections_carry_the_site_s_titles(self) -> None:
        self.assertEqual([(s["id"], s["title"]) for s in self.payload["sections"]], SECTIONS)
        self.assertIn("本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列", self.payload["notes"][0])

    def test_the_closure_is_the_report_s_section_zero(self) -> None:
        wanted = self.note["followup_closure"]
        block = self.st["followup_closure"]
        self.assertEqual(block["set_in"], shift(self.period, -1))
        self.assertEqual([item["verdict"] for item in block["items"]], wanted["verdicts"])
        chart = self.settled[0]
        self.assertEqual(chart["kind"], "bars_labeled")
        self.assertEqual(dict(zip(chart["xlabels"], chart["values"])), wanted["counts"])
        self.assertEqual(sum(chart["values"]), wanted["total"])
        self.assertEqual(chart["title"], f"上季 {wanted['total']} 条待验证问题："
                         + "、".join(f"{n} 条{label}" for label, n in wanted["counts"].items() if n))
        for i, item in enumerate(block["items"], start=1):
            self.assertIn(f"{i}. {item['question']} —— <b>{item['verdict']}</b>", chart["note"])

    def test_the_closure_prints_the_filed_figures_not_the_report_s(self) -> None:
        """Question 3: the report's +32.9% rests on a reverse-engineered base; the page
        prints the guide over the year-ago quarter the release printed, and the
        streak the filed first prints give, not the report's 「连续两季」."""
        g, fin, periods = self.st["guidance_history"], self.st["financials"], self.st["periods"]
        base = fin["non_gaap_opex_usd_m"][periods.index(shift(g["quarters"][-1], -4))]
        growth = pct(g["non_gaap_opex_guide_usd_m"][-1], base)
        note = self.settled[0]["note"]
        self.assertIn(f"较去年同季的印出值高 {signed(growth)}", note)
        self.assertIn(f"新闻稿印的是 {usd_m(base)}", note)
        streak = opex_streak(scored_record(self.st))
        self.assertIn(f"连续{cn(streak)}季花得比自己的费用指引多", note)
        self.assertGreater(streak, 2, "the report's 「连续两季」 is what this sentence corrects")

    def test_the_prior_lines_are_the_prior_report_s(self) -> None:
        block = self.st["prior_kpi_settlement"]
        self.assertEqual(block["set_in"], shift(self.period, -1))
        self.assertEqual(len(block["rows"]), self.note["prior_rows"])
        self.assertEqual(len(block["dispositions"]), self.note["prior_rows"])
        self.assertEqual(sorted(item["row"] for item in block["not_drawn"]), self.note["prior_unquantified_rows"])
        wanted = self.note["prior_thresholds"]
        self.assertEqual(len(block["quantified"]), len(wanted))
        for entry, fact in zip(block["quantified"], wanted):
            with self.subTest(line=entry["id"]):
                self.assertEqual(entry["threshold"], fact["threshold"])
                self.assertEqual(entry["action"], fact["action"])
                self.assertEqual(entry["direction"], direction_from_trigger(fact["trigger"], fact["action"]))
                self.assertNotIn("value", entry)
        rows = {entry["row"] for entry in block["quantified"]} | {item["row"] for item in block["not_drawn"]}
        self.assertEqual(rows, set(range(1, len(block["rows"]) + 1)))

    def readings(self) -> dict[str, float]:
        """Every prior line's reading, recomputed here from the arrays."""
        g, fin, periods = self.st["guidance_history"], self.st["financials"], self.st["periods"]
        base = fin["non_gaap_opex_usd_m"][periods.index(shift(g["quarters"][-1], -4))]
        return {"opex_yoy": opex_growth_as_printed(self.st)[-1],
                "opex_guide_yoy": pct(g["non_gaap_opex_guide_usd_m"][-1], base)}

    def test_the_prior_overview_settles_every_due_line_on_this_quarter_s_reading(self) -> None:
        block = self.st["prior_kpi_settlement"]
        readings = self.readings()
        due = [e for e in block["quantified"] if e["settles"] == self.period and e["threshold"] != 0]
        overview = next(ex for ex in self.settled if ex["kind"] == "diverging_bars")
        self.assertIs(self.settled[1], overview, "the overview follows the closure")
        self.assertTrue(overview["title"].startswith(f"上季{cn(len(block['rows']))}条监控指标的量化阈值："))
        self.assertEqual(overview["xlabels"], [e["metric"] for e in due])
        for entry, bar in zip(due, overview["values"]):
            value = readings[entry["reads"]]
            sign = 1 if entry["direction"] == "up" else -1
            with self.subTest(line=entry["id"]):
                self.assertAlmostEqual(bar, round(sign * (value - entry["threshold"]) / abs(entry["threshold"]) * 100, 1))
                good, bad = STATE_WORDS[entry["action"]]
                state = good if favourable_side(entry["direction"], entry["threshold"], value) else bad
                self.assertIn(f"{entry['metric']} {signed(value)}，{state}", overview["note"])
        states = {STATE_WORDS[e["action"]][0 if favourable_side(e["direction"], e["threshold"],
                                                                   readings[e["reads"]]) else 1] for e in due}
        if len(states) == 1 and len(due) > 1:
            self.assertIn(f"{cn(len(due))}个读数都{states.pop()}", overview["title"])

    def test_the_opex_growth_line_is_the_company_s_own_comparison(self) -> None:
        growth = opex_growth_as_printed(self.st)
        chart = next(ex for ex in self.settled if ex["title"].startswith("non-GAAP 营业费用同比"))
        self.assertTrue(all(close(a, None if b is None else round(b, 6)) for a, b in zip(chart["series"][0]["values"], growth)))
        self.assertEqual(sum(1 for v in growth if v is None), 4, "only 2016 lacks a year-ago quarter")
        entry = next(e for e in self.st["prior_kpi_settlement"]["quantified"] if e["reads"] == "opex_yoy")
        self.assertEqual(chart["series"][1]["values"], [entry["threshold"]] * len(growth))
        good = favourable_side(entry["direction"], entry["threshold"], growth[-1])
        self.assertEqual(chart["title"], f"non-GAAP 营业费用同比 {compact(self.period)} {signed(growth[-1])}："
                                         f"{'守住' if good else '击穿'}上季阈值 {signed(entry['threshold'])}")
        known = [v for v in growth if v is not None]
        against = sum(1 for v in known if not favourable_side(entry["direction"], entry["threshold"], v))
        self.assertIn(f"{len(known)} 季里有 {against} 季落在这条线的不利一侧", chart["note"])
        # The 2024 reprint is where the two bases part: the page's rate for a 2024
        # quarter is its own first print, not the lowered 2025 reprint.
        g = self.st["guidance_history"]
        first = dict(zip(g["quarters"], g["actual_non_gaap_opex_usd_m"]))
        reprinted = [q for q, v in zip(self.st["periods"], self.st["financials"]["non_gaap_opex_usd_m"]) if first[q] != v]
        self.assertTrue(reprinted, "the positive control needs a reprinted quarter")
        for quarter in reprinted:
            i = self.st["periods"].index(quarter)
            self.assertNotAlmostEqual(growth[i], pct(self.st["financials"]["non_gaap_opex_usd_m"][i],
                                                     self.st["financials"]["non_gaap_opex_usd_m"][i - 4]))

    def test_every_row_of_the_prior_section_lands_in_the_drawer(self) -> None:
        block = self.st["prior_kpi_settlement"]
        tbl = table(self.payload, "原文、本页结算与本季报告的处置")
        self.assertEqual([row[1] for row in tbl["rows"]], block["rows"])
        self.assertEqual([row[3] for row in tbl["rows"]], block["dispositions"])
        for item in block["not_drawn"]:
            self.assertIn(f"（不作图：{item['why']}）", tbl["rows"][item["row"] - 1][2])
        self.assertIs(self.payload["tables"][0], tbl, "section one's table leads the drawer")

    def test_a_settlement_quarter_must_carry_the_previous_analysis(self) -> None:
        first = self.st["analysis_coverage"]["first_period"]
        self.assertLess(order(first), order(self.period))
        with self.assertRaisesRegex(ValueError, "prior_kpi_settlement"):
            self.rebuilt(lambda s: s.pop("prior_kpi_settlement"))
        cases = (
            ("set in", lambda s: s["prior_kpi_settlement"].__setitem__("set_in", shift(self.period, -2))),
            ("closes questions set in", lambda s: s["followup_closure"].__setitem__("set_in", shift(self.period, -2))),
            ("accounted for", lambda s: s["prior_kpi_settlement"]["not_drawn"].pop()),
            ("remove its typed value", lambda s: s["prior_kpi_settlement"]["quantified"][0].__setitem__("value", 1.0)),
            ("map it in build/amd.py", lambda s: s["prior_kpi_settlement"]["quantified"][0].__setitem__("reads", "dso")),
            ("one disposition per row", lambda s: s["prior_kpi_settlement"]["dispositions"].pop()),
            ("should have been settled then",
             lambda s: s["prior_kpi_settlement"]["quantified"][0].__setitem__("settles", shift(self.period, -1))),
        )
        for message, edit in cases:
            with self.subTest(case=message):
                with self.assertRaisesRegex(ValueError, message):
                    self.rebuilt(edit)

    def test_a_line_that_settles_later_is_listed_not_drawn(self) -> None:
        def postpone(s):
            s["prior_kpi_settlement"]["quantified"][1]["settles"] = shift(self.period, 1)
        payload = self.rebuilt(postpone)
        exhibits = payload["sections"][0]["exhibits"]
        overview = next(ex for ex in exhibits if ex["kind"] == "diverging_bars")
        later = self.st["prior_kpi_settlement"]["quantified"][1]
        self.assertNotIn(later["metric"], overview["xlabels"])
        self.assertIn(f"未到期（{shift(self.period, 1)} 结算）", overview["note"])
        self.assertIn("一条未到期", overview["title"])


class AmdChartClaimsTest(unittest.TestCase):
    """Each chart's numbers and sentences, recomputed from the series."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.st = load()
        cls.payload = amd.build_payload(cls.st)
        cls.periods = cls.st["periods"]
        cls.index = {q: i for i, q in enumerate(cls.periods)}
        cls.fin = cls.st["financials"]
        cls.revenue = cls.fin["revenue_usd_m"]
        cls.n = len(cls.periods)
        cls.ya = cls.index[year_ago(cls.periods[-1])]

    def test_revenue_growth_is_computed_on_one_basis_at_a_time(self) -> None:
        yoy = revenue_growth(self.st)
        chart = one(self.payload, "收入 ", "gs_bar")
        self.assertEqual(chart["xlabels"], [compact(q) for q in self.periods])
        for got, r in zip(chart["values"], self.revenue):
            self.assertTrue(close(got, r / 1000))
        for got, wanted in zip(chart["yoy"]["values"], yoy):
            self.assertTrue(close(got, wanted), (got, wanted))
        # the basis choice is visible: a mixed-basis 2017 would differ
        for q in self.st["asc605_2017"]["quarters"]:
            i = self.index[q]
            self.assertGreater(abs(yoy[i] - pct(self.revenue[i], self.revenue[i - 4])), 1.0, q)
        now, prev = yoy[-1], yoy[-2]
        self.assertTrue(chart["title"].startswith(f"收入 {usd_b(self.revenue[-1])}、同比 {signed(now)}，"))
        if now > prev:
            higher = [k for k in range(self.n - 1) if yoy[k] >= now]
            if higher:
                # The quarter named is the last one that grew at least as fast --
                # "the highest after X" -- not the quarter following it.
                named = higher[-1]
                self.assertIn(f"同比增速是 {compact(self.periods[named])}（{signed(yoy[named])}）之后最高",
                              chart["title"])
                self.assertTrue(all(yoy[k] < now for k in range(named + 1, self.n - 1)))
            else:
                self.assertIn(f"同比增速是 {self.n} 季最高", chart["title"])
        else:
            self.assertIn(f"同比增速较上季的 {prev:.1f}% 回落", chart["title"])
        peak = max(range(self.n), key=lambda i: yoy[i])
        self.assertIn(f"{self.n} 季里同比最高的是 {compact(self.periods[peak])} 的 {yoy[peak]:.1f}%", chart["note"])
        self.assertIn(f"环比 {signed(pct(self.revenue[-1], self.revenue[-2]))}", chart["note"])

    def test_the_segment_chart_is_recomputed(self) -> None:
        seg = self.st["segments"]
        rev = [self.revenue[self.index[q]] for q in seg["quarters"]]
        dc, client, gaming = seg["data_center_usd_m"], seg["client_usd_m"], seg["gaming_usd_m"]
        share = [d / r * 100 for d, r in zip(dc, rev)]
        chart = one(self.payload, "数据中心 ", "stacked_dual")
        for block, key in zip(chart["stacks"], ("data_center_usd_m", "client_usd_m", "gaming_usd_m",
                                                "embedded_usd_m")):
            self.assertTrue(all(close(a, b / 1000) for a, b in zip(block["values"], seg[key])), key)
        self.assertTrue(all(close(a, b) for a, b in zip(chart["line"]["values"], share)))
        k = len(dc) - 1
        ya = seg["quarters"].index(year_ago(seg["quarters"][-1]))
        self.assertTrue(chart["title"].startswith(
            f"数据中心 {usd_b(dc[k], 2)}、同比 {signed(pct(dc[k], dc[ya]), 0)}，占收入 {share[k]:.1f}%"))
        record = share[-1] > max(share[:-1])
        self.assertEqual("是四分部口径以来最高" in chart["title"], record)
        self.assertIn(f"游戏本季 {usd_m(gaming[k])}、同比 {signed(pct(gaming[k], gaming[ya]), 0)}", chart["note"])
        self.assertIn(f"客户端 {usd_m(client[k])}、同比 {signed(pct(client[k], client[ya]), 0)}", chart["note"])

    def test_the_segment_margins_are_recomputed(self) -> None:
        seg = self.st["segments"]
        dc_m = [o / r * 100 for o, r in zip(seg["data_center_oi_usd_m"], seg["data_center_usd_m"])]
        cg_m = [o / (c + g) * 100 for o, c, g in zip(seg["client_gaming_oi_usd_m"], seg["client_usd_m"],
                                                    seg["gaming_usd_m"])]
        emb_m = [o / r * 100 for o, r in zip(seg["embedded_oi_usd_m"], seg["embedded_usd_m"])]
        chart = one(self.payload, "分部营业利润率：", "lines")
        for block, line in zip(chart["series"], (dc_m, cg_m, emb_m)):
            self.assertTrue(all(close(a, b) for a, b in zip(block["values"], line)), block["name"])
        ya = seg["quarters"].index(year_ago(seg["quarters"][-1]))
        self.assertEqual(chart["title"],
                         f"分部营业利润率：数据中心 {dc_m[-1]:.1f}%，客户端与游戏 {cg_m[-1]:.1f}%"
                         f"（同比 {signed(cg_m[-1] - cg_m[ya], 1, 'pp')}），嵌入式 {emb_m[-1]:.1f}%")
        worst = min(range(len(dc_m)), key=lambda i: dc_m[i])
        self.assertIn(f"数据中心最低的一格是 {compact(seg['quarters'][worst])} 的 {minus(f'{dc_m[worst]:.1f}')}%",
                      chart["note"])
        episode = seg.get("episodes", {}).get(seg["quarters"][worst])
        if episode:
            self.assertIn(episode, chart["note"])

    def test_the_eps_chart_reads_the_block_by_quarter(self) -> None:
        block = self.st.get("eps_reconciliation")
        if block is None:
            self.skipTest("no EPS block this quarter")
        chart = one(self.payload, "GAAP 每股收益环比", "grouped_bars")
        chronological = sorted(block["quarters"], key=order)
        self.assertEqual(chart["xlabels"], [compact(q) for q in chronological])
        for group, key in zip(chart["groups"], ("gaap_eps_usd", "non_gaap_eps_usd")):
            self.assertEqual(group["values"], [block[key][block["quarters"].index(q)] for q in chronological])
        now, prior = (block["quarters"].index(self.periods[-1]), block["quarters"].index(self.periods[-2]))
        gains = block["long_term_investment_gains_usd_m"]
        self.assertEqual(chart["title"],
                         f"GAAP 每股收益环比 {signed(pct(block['gaap_eps_usd'][now], block['gaap_eps_usd'][prior]))}"
                         f"、non-GAAP {signed(pct(block['non_gaap_eps_usd'][now], block['non_gaap_eps_usd'][prior]))}"
                         + (f"：GAAP 里有 {usd_m(gains[now])} 长期投资净收益，non-GAAP 不含" if gains[now] else ""))
        self.assertIn(f"GAAP 净利 {usd_m(block['gaap_net_income_usd_m'][now])} 里有 {usd_m(gains[now])}", chart["note"])
        self.assertIn(f"上季这一项只有 {usd_m(gains[prior])}", chart["note"])

    def test_the_cash_quality_chart_is_recomputed(self) -> None:
        wc = self.st["working_capital_cash_flow_usd_m"]
        self.assertEqual(wc["quarters"][-1], self.periods[-1])
        quarters = wc["quarters"][-8:]
        ocf = [self.st["cash_flow_usd_m"]["operating"][self.index[q]] for q in quarters]
        ap = [wc["accounts_payable_change"][wc["quarters"].index(q)] for q in quarters]
        chart = one(self.payload, "经营现金流 ", "grouped_bars")
        self.assertEqual(chart["xlabels"], [compact(q) for q in quarters])
        self.assertEqual([g["values"] for g in chart["groups"]], [ocf, ap, [o - a for o, a in zip(ocf, ap)]])
        if ap[-1] > 0:
            self.assertEqual(chart["title"], f"经营现金流 {usd_m(ocf[-1])}，其中 {usd_m(ap[-1])} 来自应付账款增加；"
                                             f"扣掉这一项是 {usd_m(ocf[-1] - ap[-1])} D")
            self.assertIn(f"应付账款的增加相当于本季经营现金流的 {ap[-1] / ocf[-1] * 100:.0f}%", chart["note"])
        else:
            self.assertEqual(chart["title"], f"经营现金流 {usd_m(ocf[-1])}，应付账款减少占用了 {usd_m(-ap[-1])}；"
                                             f"不计这一项是 {usd_m(ocf[-1] - ap[-1])} D")
        self.assertIn(f"图里 {len(quarters)} 季有 {sum(1 for v in ap if v < 0)} 季应付账款是减少的", chart["note"])

    def test_the_capex_chart_is_recomputed(self) -> None:
        capex = self.st["cash_flow_usd_m"]["capex"]
        intensity = [c / r * 100 for c, r in zip(capex, self.revenue)]
        chart = one(self.payload, "资本开支 ", "bar_line_dual")
        self.assertEqual(chart["bar"]["values"], capex)
        self.assertTrue(all(close(a, b) for a, b in zip(chart["line"]["values"], intensity)))
        level, share = capex[-1] > max(capex[:-1]), intensity[-1] > max(intensity[:-1])
        head = (f"资本开支 {usd_m(capex[-1])}（环比 {signed(pct(capex[-1], capex[-2]), 0)}）、"
                f"占收入 {intensity[-1]:.1f}%")
        suffix = (f"，两项都是 {self.n} 季最高" if level and share else
                  f"，金额是 {self.n} 季最高" if level else
                  f"，占比是 {self.n} 季最高" if share else "")
        self.assertEqual(chart["title"], head + suffix)
        banded = sum(1 for v in intensity if 1 <= v <= 4)
        self.assertIn(f"{self.n} 季里有 {banded} 季资本开支占收入在 1%–4% 之间", chart["note"])
        top = max(range(self.n - 1), key=lambda i: intensity[i])
        self.assertIn(f"的最高点是 {compact(self.periods[top])} 的 {intensity[top]:.1f}%", chart["note"])
        self.assertEqual(f"、为 {self.n} 季最高" in self.payload["headline"], level)

    def test_the_exposure_chart_is_recomputed(self) -> None:
        block = self.st.get("balance_sheet_exposure")
        if block is None:
            self.skipTest("no exposure block this quarter")
        pc = self.st["purchase_commitments_usd_m"]
        total, later = block["items"][0]["values"], block["items"][1]["values"]
        for k, quarter in enumerate(block["quarters"]):
            self.assertEqual(total[k], pc["total"][pc["quarters"].index(quarter)], quarter)
            self.assertLessEqual(later[k], total[k])
        self.assertEqual(block["quarters"], [self.periods[-2], self.periods[-1]])
        chart = one(self.payload, "无条件采购承诺一季", "grouped_bars")
        self.assertEqual(chart["title"],
                         f"无条件采购承诺一季 {signed(pct(total[1], total[0]), 0)} 到 {usd_b(total[1])}，"
                         f"其中 {block['items'][1]['short']}那一段 {signed(pct(later[1], later[0]), 0)}")
        for k, group in enumerate(chart["groups"]):
            self.assertTrue(all(close(v, item["values"][k] / 1000) for v, item in zip(group["values"], block["items"])))
        tbl = table(self.payload, "表外与或有敞口")
        self.assertEqual(len(tbl["rows"]), len(block["items"]) + len(block["table_extra"]))

    def test_payable_and_inventory_days_are_the_stated_definition(self) -> None:
        """(payables + related-party payables) ÷ cost of sales ex-amortisation × 91."""
        dpo, dio = payable_days(self.st), inventory_days(self.st)
        chart = one(self.payload, "应付天数 ", "lines")
        self.assertTrue(all(close(a, b) for a, b in zip(chart["series"][0]["values"], dpo)))
        inventory = one(self.payload, "存货 ", "bar_line_dual")
        self.assertTrue(all(close(a, b) for a, b in zip(inventory["line"]["values"], dio)))
        # the denominator is visible: on the total cost line the last value would differ
        total = self.fin["total_cost_of_sales_usd_m"][-1]
        self.assertGreater(abs(dpo[-1] - self.st["balance_sheet_usd_m"]["payables_incl_related"][-1]
                               / total * DAYS_PER_QUARTER), 1.0)
        self.assertIn(f"× {DAYS_PER_QUARTER}（D）", chart["note"])
        self.assertIn(f"× {DAYS_PER_QUARTER}（D）", inventory["note"])
        jumps = [dpo[i] - dpo[i - 1] for i in range(1, self.n)]
        jump_record = jumps[-1] > max(jumps[:-1])
        peak = max(range(self.n), key=lambda i: dpo[i])
        rank = 1 + sum(1 for v in dpo[:-1] if v > dpo[-1])
        kpi = next(q for q in self.st["next_kpi"]["quantified"] if q["id"] == "dpo")
        self.assertTrue(chart["title"].startswith(
            f"应付天数 {dpo[-1]:.1f} 天对 {kpi['threshold']:.0f} 天警戒线：单季 {signed(jumps[-1], 1, ' 天')}"))
        self.assertEqual(f"是 {self.n} 季最大跳升" in chart["title"], jump_record)
        self.assertEqual("<b>罕见的是速度</b>" in chart["note"], jump_record)
        if peak == self.n - 1:
            self.assertIn("水平本身也是纪录", chart["title"])
        elif jump_record:
            self.assertIn(f"但水平不是纪录（{compact(self.periods[peak])} {dpo[peak]:.1f} 天）", chart["title"])
        else:
            self.assertIn(f"水平排第 {rank}（最高是 {compact(self.periods[peak])} 的 {dpo[peak]:.1f} 天）",
                          chart["title"])
        self.assertIn(f"本季水平在 {self.n} 季里排第 {rank}", chart["note"])
        early = [v for q, v in zip(self.periods, dpo) if int(q[-4:]) <= 2019]
        self.assertEqual(f"2016–2019 年 AMD 的应付天数在 {min(early):.0f}–{max(early):.0f} 天之间" in chart["note"],
                         min(early) <= dpo[-1] <= max(early))
        self.assertIn(f"应付天数 {dpo[-2]:.0f} → {dpo[-1]:.0f} 天", self.payload["headline"])
        self.assertIn(f"应付天数单季 {signed(jumps[-1], 1, ' 天')}", self.payload["brief"])
        peak_i = max(range(self.n), key=lambda i: dio[i])
        self.assertIn(f"存货天数 {dio[-1]:.0f} 天：{self.n} 季里最高是 {compact(self.periods[peak_i])} 的 "
                      f"{dio[peak_i]:.0f} 天", inventory["title"])

    def test_the_margin_threshold_chart_is_recomputed(self) -> None:
        gm = gross_margin(self.st)
        spec = next(q for q in self.st["next_kpi"]["quantified"] if q["id"] == "non_gaap_gm")
        chart = one(self.payload, "non-GAAP 毛利率对 ", "lines")
        self.assertTrue(all(close(a, b) for a, b in zip(chart["series"][0]["values"], gm)))
        self.assertEqual(chart["series"][1]["values"], [spec["threshold"]] * self.n)
        guide = self.st["guidance_history"]["non_gaap_gm_guide_pct"][-1]
        self.assertEqual(chart["title"], f"non-GAAP 毛利率对 {spec['threshold']:.1f}% 警戒线：本季 {gm[-1]:.1f}%，"
                                         f"下季公司指引约 {guide:g}%")
        # counted at the one decimal the chart prints: 53.99% reads 54.0%, on the line
        under = [compact(q) for q, v in zip(self.periods[-8:], gm[-8:])
                 if half_up(v, 1) < Decimal(repr(spec["threshold"]))]
        strictly = [compact(q) for q, v in zip(self.periods[-8:], gm[-8:]) if v < spec["threshold"]]
        self.assertIn(f"最近八季里这条线被跌破 {len(under)} 次（{'、'.join(under)}）" if under
                      else "最近八季没有一季跌破这条线", chart["note"])
        if strictly != under:
            self.assertNotIn(f"被跌破 {len(strictly)} 次", chart["note"])

    def test_the_data_center_half_threshold_is_arithmetic(self) -> None:
        """A filed "accelerates" turned into a floor, from segment figures alone.

        The chart exists only while a stamped `dc_acceleration_claim` says the
        company wrote it; the floor is last year's same half grown at the rate
        of the half just finished.
        """
        seg = self.st["segments"]
        last = seg["quarters"][-1]
        halves = [ex for ex in exhibits_of(self.payload)
                  if ex["title"].startswith("公司说 ") and "数据中心会「加速」" in ex["title"]]
        claim = self.st.get("dc_acceleration_claim")
        if claim is None:
            self.assertEqual(halves, [])
            return
        dc = dict(zip(seg["quarters"], seg["data_center_usd_m"]))
        year, which = claim["year"], claim["half"]
        base_half, base_year = (1, year) if which == 2 else (2, year - 1)
        name = lambda y, h: f"{y} {'上' if h == 1 else '下'}半年"  # noqa: E731
        half = lambda y, h: sum(dc[f"Q{n} {y}"] for n in ((1, 2) if h == 1 else (3, 4)))  # noqa: E731
        done_now, done_prev = half(base_year, base_half), half(base_year - 1, base_half)
        target_prev = half(year - 1, which)
        growth = pct(done_now, done_prev)
        floor = target_prev * (1 + growth / 100)
        (chart,) = halves
        self.assertEqual(chart["xlabels"][-1], name(year, which) + "门槛 D")
        self.assertTrue(all(close(a, b / 1000)
                            for a, b in zip(chart["values"], (done_prev, target_prev, done_now, floor))))
        self.assertEqual(chart["title"], f"公司说 {name(year, which)}数据中心会「加速」：同比要高过 {signed(growth)}，"
                                         f"至少 {usd_b(floor, 2)} D")
        self.assertIn(f"{name(year, which)}要超过 {usd_m(floor)} 才算加速", chart["note"])
        self.assertIn(f"比 {compact(last)} 的 {usd_m(dc[last])} 高 {pct(floor / 2, dc[last]):.0f}%", chart["note"])
        self.assertTrue(chart["note"].startswith(claim["said"]))
        self.assertIn(claim["where"], chart["src_extra"])
        if "{dc_floor}" in self.st["quarter_story"]["brief"]:
            self.assertIn(usd_b(floor, 2), self.payload["brief"])

    def test_the_commitments_line_is_recomputed(self) -> None:
        pc = self.st["purchase_commitments_usd_m"]
        self.assertEqual(pc["quarters"], self.periods[self.index[pc["quarters"][0]]:])
        total = pc["total"]
        holes = [q for q, v in zip(pc["quarters"], total) if v is None]
        self.assertEqual(holes, list(pc["not_comparable"]))
        chart = one(self.payload, "无条件采购承诺 US$", "lines")
        self.assertTrue(all(close(a, None if b is None else b / 1000)
                            for a, b in zip(chart["series"][0]["values"], total)))
        known = [i for i, v in enumerate(total) if v is not None]
        trough = min(known, key=lambda i: total[i])
        before = [i for i in known if i < trough]
        peak = max(before, key=lambda i: total[i]) if before else trough
        record = total[-1] > max(total[i] for i in known[:-1])
        labels = [compact(q) for q in pc["quarters"]]
        self.assertEqual(chart["title"],
                         f"无条件采购承诺 {usd_b(total[-1])}" + ("，是这条序列的新高" if record else "")
                         + (f"：上一轮高点是 {labels[peak]} 的 {usd_b(total[peak])}，"
                            f"低点是 {labels[trough]} 的 {usd_b(total[trough])}" if peak != trough else ""))
        for back, word in ((1, "上季"), (4, "一年前")):
            target = len(total) - 1 - back
            nearest = max(i for i in known if i <= target)
            wanted = (f"{labels[target]} 的 {usd_b(total[target])}" if nearest == target else
                      f"{labels[target]} 不可比，取更早的 {labels[nearest]} {usd_b(total[nearest])}")
            self.assertIn(f"{word}：{wanted}", chart["note"])
        for quarter in list(pc["breaks"]) + list(pc["not_comparable"]):
            self.assertIn(compact(quarter), chart["note"])

    def test_the_routine_long_series_are_recomputed(self) -> None:
        n, fin, revenue = self.n, self.fin, self.revenue
        gm = gross_margin(self.st)
        op = [o / r * 100 for o, r in zip(fin["non_gaap_operating_income_usd_m"], revenue)]
        margin = next(ex for ex in exhibits_of(self.payload)
                      if ex["kind"] == "lines" and ex["title"].startswith(f"{n} 季 non-GAAP 毛利率由"))
        self.assertEqual(margin["title"], f"{n} 季 non-GAAP 毛利率由 {minus(f'{gm[0]:.1f}')}% 到 {minus(f'{gm[-1]:.1f}')}%、"
                                          f"营业利润率由 {minus(f'{op[0]:.1f}')}% 到 {minus(f'{op[-1]:.1f}')}%")
        top = max(range(n), key=lambda i: op[i])
        self.assertIn(f"{n} 季里 non-GAAP 营业利润率的最高点是 {compact(self.periods[top])} 的 {op[top]:.1f}%"
                      + ("，就是本季" if top == n - 1 else "，不是本季"), margin["note"])

        old = self.st["segments_legacy"]
        cg, ee = old["computing_graphics_revenue_usd_m"], old["eesc_revenue_usd_m"]
        legacy = one(self.payload, "旧的两分部口径", "stacked_dual")
        self.assertEqual(legacy["title"],
                         f"旧的两分部口径（{compact(old['quarters'][0])}–{compact(old['quarters'][-1])}）："
                         f"计算与图形由 {usd_b(cg[0], 2)} 到 {usd_b(cg[-1], 2)}，"
                         f"企业、嵌入式与半定制由 {usd_b(ee[0], 2)} 到 {usd_b(ee[-1], 2)}")
        self.assertTrue(all(close(a, c / (c + e) * 100) for a, c, e in zip(legacy["line"]["values"], cg, ee)))

        fcf = self.st["cash_flow_usd_m"]["free_cash_flow"]
        fm = [f / r * 100 for f, r in zip(fcf, revenue)]
        chart = one(self.payload, "自由现金流 ", "bar_line_dual")
        self.assertEqual(chart["bar"]["values"], fcf)
        self.assertEqual(chart["title"], f"自由现金流 {n} 季：本季 {usd_m(fcf[-1])}、占收入 {fm[-1]:.1f}%，"
                                         f"上季是 {fm[-2]:.1f}%")
        negative = [int(q[-4:]) for q, v in zip(self.periods, fcf) if v < 0]
        self.assertIn(f"{n} 季里有 {len(negative)} 季自由现金流为负，都在 {min(negative)}–{max(negative)} 年之间"
                      if negative else f"{n} 季里没有一季自由现金流为负", chart["note"])

        opex = fin["non_gaap_opex_usd_m"]
        intensity = [o / r * 100 for o, r in zip(opex, revenue)]
        line = one(self.payload, "non-GAAP 营业费用占收入", "gs_line")
        self.assertTrue(all(close(a, b) for a, b in zip(line["values"], intensity)))
        low = min(range(n), key=lambda i: intensity[i])
        self.assertIn(f"最低的一格是 {compact(self.periods[low])} 的 {intensity[low]:.1f}%。"
                      f"本季费用 {usd_m(opex[-1])}、同比 {signed(pct(opex[-1], opex[self.ya]))}，"
                      f"收入同比 {signed(pct(revenue[-1], revenue[self.ya]))}", line["note"])

        shares = fin["diluted_shares_m"]
        chart = one(self.payload, "摊薄股数 ", "lines")
        self.assertEqual(chart["series"][0]["values"], shares)
        self.assertTrue(chart["title"].startswith(f"摊薄股数 {n} 季由 {shares[0]:,}M 到 {shares[-1]:,}M"))
        steps = [(shares[i] - shares[i - 1], i) for i in range(1, n)]
        if "最大的一级台阶是 2022 年一季度到二季度" in chart["note"]:
            self.assertEqual(self.periods[max(steps)[1]], "Q2 2022")

    def test_the_eight_quarter_and_threshold_tables_are_recomputed(self) -> None:
        fin, cash = self.fin, self.st["cash_flow_usd_m"]
        yoy, gm = revenue_growth(self.st), gross_margin(self.st)
        core = table(self.payload, "八季核心")
        for row, i in zip(core["rows"], range(self.n - 8, self.n), strict=True):
            self.assertEqual(row, [
                self.periods[i], usd_m(self.revenue[i]), signed(yoy[i]) + " D", f"{gm[i]:.2f}% D",
                usd_m(fin["non_gaap_opex_usd_m"][i]), usd_m(fin["non_gaap_operating_income_usd_m"][i]),
                f"${fin['non_gaap_eps_usd'][i]:.2f}", f"${fin['gaap_eps_diluted_usd'][i]:.2f}",
                usd_m(cash["free_cash_flow"][i])])
        seg = self.st["segments"]
        segt = table(self.payload, "分部八季")
        keys = ("data_center_usd_m", "data_center_oi_usd_m", "client_usd_m", "gaming_usd_m",
                "client_gaming_oi_usd_m", "embedded_usd_m", "embedded_oi_usd_m", "all_other_oi_usd_m")
        for row, k in zip(segt["rows"], range(len(seg["quarters"]) - 8, len(seg["quarters"])), strict=True):
            self.assertEqual(row, [seg["quarters"][k]] + [usd_m(seg[key][k]) for key in keys])
        kpi = self.st["next_kpi"]
        tbl = table(self.payload, "下季阈值与当前值")
        self.assertEqual([r[0] for r in tbl["rows"]],
                         [q["metric"] for q in kpi["quantified"]] + [t["metric"] for t in kpi["table_only"]])
        current = {"non_gaap_gm": gross_margin(self.st)[-1], "dpo": payable_days(self.st)[-1]}
        for row, spec in zip(tbl["rows"], kpi["quantified"]):
            self.assertIn(f"{current[spec['id']]:.1f}", row[3], spec["metric"])
        for row, item in zip(tbl["rows"][len(kpi["quantified"]):], kpi["table_only"]):
            self.assertEqual(row[4], "不作图：" + item["why"])


# ═════════════════════════════════════════════════════════════════════════════
class AmdChecksTest(unittest.TestCase):
    """The newest quarter against `_checks`, a separate reading of its 8-K and 10-Q.

    The builder never reads `_checks` (`tests/test_data_only_roll.py`), so each
    assertion here compares what was built from the arrays with a record keyed
    from the filing, and a roll that misaligns a column fails here.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.st = load()
        cls.c = cls.st["_checks"]
        cls.payload = amd.build_payload(cls.st)
        cls.periods = cls.st["periods"]

    def test_the_page_names_the_checked_quarter(self) -> None:
        c, latest = self.c, self.payload["latest"]
        self.assertEqual(c["period"], self.periods[-1])
        self.assertEqual(c["period"], latest["disclosed_period_label"])
        self.assertEqual(c["period_end"], latest["period_end"])
        self.assertEqual(c["release_date"], latest["release_date"])
        self.assertIn(f"截至 {c['period_end']}", self.payload["subtitle"])
        self.assertIn(f"发布 {c['release_date']}", self.payload["subtitle"])
        self.assertIn(c["period"], self.payload["title"])
        # the release the page links to is the release that was checked
        accession = self.st["release_accessions"][-1]
        self.assertIn(accession, c["source"])
        self.assertIn(accession.replace("-", ""), self.payload["source_url"])
        current = [s for s in self.payload["source_links"]
                   if c["period"] in s["label"] and "业绩新闻稿" in s["label"]]
        self.assertEqual([s["url"] for s in current], [self.payload["source_url"]])
        for s in self.payload["source_links"]:
            self.assertTrue(s["url"].startswith("https://www.sec.gov/Archives/edgar/data/2488/"), s["url"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        c, st = self.c, self.st
        fin, cash, seg = st["financials"], st["cash_flow_usd_m"], st["segments"]
        ya = self.periods.index(year_ago(self.periods[-1]))
        wc = st["working_capital_cash_flow_usd_m"]
        pairs = [
            ("revenue current", fin["revenue_usd_m"][-1], c["revenue_usd_m"]["current"]),
            ("revenue prior", fin["revenue_usd_m"][-2], c["revenue_usd_m"]["prior_quarter"]),
            ("revenue year ago", fin["revenue_usd_m"][ya], c["revenue_usd_m"]["year_ago"]),
            ("non-GAAP gross profit", fin["non_gaap_gross_profit_usd_m"][-1], c["non_gaap_gross_profit_usd_m"]),
            ("non-GAAP opex", fin["non_gaap_opex_usd_m"][-1], c["non_gaap_opex_usd_m"]),
            ("non-GAAP operating income", fin["non_gaap_operating_income_usd_m"][-1],
             c["non_gaap_operating_income_usd_m"]),
            ("GAAP EPS", fin["gaap_eps_diluted_usd"][-1], c["diluted_eps_usd"]["gaap"]),
            ("non-GAAP EPS", fin["non_gaap_eps_usd"][-1], c["diluted_eps_usd"]["non_gaap"]),
            ("operating cash flow", cash["operating"][-1], c["cash_flow_usd_m"]["operating_continuing"]),
            ("capex", cash["capex"][-1], c["cash_flow_usd_m"]["capex"]),
            ("free cash flow", cash["free_cash_flow"][-1], c["cash_flow_usd_m"]["free_cash_flow"]),
            ("AP change", wc["accounts_payable_change"][-1], c["cash_flow_usd_m"]["accounts_payable_change"]),
            ("accounts payable", st["balance_sheet_usd_m"]["accounts_payable"][-1],
             c["balance_sheet_usd_m"]["accounts_payable"]),
            ("inventory", st["balance_sheet_usd_m"]["inventory"][-1], c["balance_sheet_usd_m"]["inventory"]),
        ]
        for key, series_key in (("data_center", "data_center_usd_m"), ("client", "client_usd_m"),
                                ("gaming", "gaming_usd_m"), ("embedded", "embedded_usd_m"),
                                ("data_center_oi", "data_center_oi_usd_m"),
                                ("client_gaming_oi", "client_gaming_oi_usd_m"),
                                ("embedded_oi", "embedded_oi_usd_m")):
            pairs.append((key, seg[series_key][-1], c["segments_usd_m"][key]))
        pc = st["purchase_commitments_usd_m"]["total"]
        pairs += [("commitments", pc[-1], c["unconditional_commitments_usd_m"]["current"]),
                  ("commitments prior", pc[-2], c["unconditional_commitments_usd_m"]["prior_quarter"])]
        exposure = st.get("balance_sheet_exposure")
        if exposure is not None:
            pairs.append(("exposure total", exposure["items"][0]["values"],
                          [c["unconditional_commitments_usd_m"]["prior_quarter"],
                           c["unconditional_commitments_usd_m"]["current"]]))
        warrants = st.get("warrants")
        if warrants is not None:
            pairs.append(("warrant shares", warrants["shares_m"],
                          c["warrant_shares_m"]["openai"] + c["warrant_shares_m"]["meta"]))
        for key, got, wanted in pairs:
            with self.subTest(key=key):
                self.assertEqual(got, wanted)

    def test_the_printed_percentages_round_to_the_checked_digits(self) -> None:
        """The page prints one decimal; the release prints whole percents, rounded half up."""
        c = self.c
        rev = c["revenue_usd_m"]["current"]
        non_gaap = c["non_gaap_gross_profit_usd_m"] / rev * 100
        gaap = self.st["financials"]["gaap_gross_profit_usd_m"][-1] / rev * 100
        fcf = c["cash_flow_usd_m"]["free_cash_flow"] / rev * 100
        self.assertEqual(int(half_up(non_gaap)), c["gross_margin_printed_pct"]["non_gaap"])
        self.assertEqual(int(half_up(gaap)), c["gross_margin_printed_pct"]["gaap"])
        self.assertEqual(int(half_up(fcf)), c["free_cash_flow_margin_printed_pct"])
        self.assertIn(f"non-GAAP 毛利率 {non_gaap:.1f}%", self.payload["headline"])
        self.assertIn(f"占收入 {fcf:.1f}%", one(self.payload, "自由现金流 ", "bar_line_dual")["title"])

    def test_the_guidance_is_the_checked_guidance(self) -> None:
        c, g = self.c, self.st["guidance_history"]
        this, nxt = c["this_quarter_guide"], c["next_quarter_guide"]
        i = g["quarters"].index(c["period"])
        self.assertEqual(g["revenue_mid_usd_m"][i], this["revenue_usd_m"])
        self.assertEqual(g["revenue_high_usd_m"][i] - g["revenue_mid_usd_m"][i], this["band_usd_m"])
        self.assertEqual(g["non_gaap_gm_guide_pct"][i], this["non_gaap_gm_pct"])
        self.assertEqual(g["non_gaap_opex_guide_usd_m"][i], this["non_gaap_opex_usd_m"])
        self.assertEqual(g["quarters"][-1], nxt["period"])
        self.assertEqual(g["revenue_mid_usd_m"][-1], nxt["revenue_usd_m"])
        self.assertEqual(g["revenue_high_usd_m"][-1] - g["revenue_mid_usd_m"][-1], nxt["band_usd_m"])
        self.assertEqual(g["non_gaap_gm_guide_pct"][-1], nxt["non_gaap_gm_pct"])
        self.assertEqual(g["non_gaap_opex_guide_usd_m"][-1], nxt["non_gaap_opex_usd_m"])
        block = self.st["guidance"]["next_quarter"]
        self.assertEqual((block["period"], block["revenue_usd_m"], block["revenue_band_usd_m"],
                          block["non_gaap_gm_pct"]),
                         (nxt["period"], nxt["revenue_usd_m"], nxt["band_usd_m"], nxt["non_gaap_gm_pct"]))

    def test_the_page_prints_the_checked_figures(self) -> None:
        c, p = self.c, self.payload
        cash = c["cash_flow_usd_m"]
        head = p["headline"]
        self.assertIn(f"收入 {usd_b(c['revenue_usd_m']['current'])}", head)
        self.assertIn(f"经营现金流 {usd_m(cash['operating_continuing'])} 里有 {usd_m(cash['accounts_payable_change'])}",
                      head)
        self.assertIn(f"资本开支 {usd_m(cash['capex'])}", head)
        self.assertIn(f"由 {usd_b(c['unconditional_commitments_usd_m']['prior_quarter'])} 升到 "
                      f"{usd_b(c['unconditional_commitments_usd_m']['current'])}", head)
        self.assertIn(f"本季 {usd_m(cash['free_cash_flow'])}", one(p, "自由现金流 ", "bar_line_dual")["title"])
        self.assertIn(f"存货 {usd_b(c['balance_sheet_usd_m']['inventory'])}", one(p, "存货 ", "bar_line_dual")["title"])
        eps = one(p, "GAAP 每股收益环比", "grouped_bars")
        self.assertEqual([g["values"][-1] for g in eps["groups"]],
                         [c["diluted_eps_usd"]["gaap"], c["diluted_eps_usd"]["non_gaap"]])
        seg_row = table(p, "分部八季")["rows"][-1]
        s = c["segments_usd_m"]
        self.assertEqual(seg_row[1:8], [usd_m(s[k]) for k in ("data_center", "data_center_oi", "client", "gaming",
                                                             "client_gaming_oi", "embedded", "embedded_oi")])
        this, nxt = c["this_quarter_guide"], c["next_quarter_guide"]
        rev_row = table(p, "兑现与")["rows"][0]
        self.assertEqual(rev_row[1], f"{usd_m(this['revenue_usd_m'] - this['band_usd_m'])} – "
                                     f"{usd_m(this['revenue_usd_m'] + this['band_usd_m'])}")
        box = {row[0]: row for row in p["guidance"]["rows"]}
        self.assertEqual(box["收入"][1], f"US${nxt['revenue_usd_m'] / 1000:g}B ± US${nxt['band_usd_m']}M")
        self.assertEqual(box["non-GAAP 毛利率"][1], f"约 {nxt['non_gaap_gm_pct']:g}%")
        self.assertEqual(box["non-GAAP 营业费用"][1], f"约 US${nxt['non_gaap_opex_usd_m'] / 1000:.2f}B")
        w = c["warrant_shares_m"]
        shares = one(p, "摊薄股数 ", "lines")
        self.assertIn(f"另有 {w['openai'] + w['meta']:,}M 股认股权证未归属", shares["title"])
        if w["vested"] == 0:
            self.assertIn("零归属", shares["note"])


# ═════════════════════════════════════════════════════════════════════════════
class AmdRollTest(unittest.TestCase):
    """A roll edits the series and nothing else: stale blocks stop the build,
    absent ones drop their part, and every record sentence answers to the data."""

    STAMPED = ("followup_closure", "prior_kpi_settlement", "eps_reconciliation", "balance_sheet_exposure",
               "next_kpi", "guidance", "quarter_story", "warrants", "dc_acceleration_claim", "latest")

    @classmethod
    def setUpClass(cls) -> None:
        cls.st = load()
        cls.payload = amd.build_payload(cls.st)
        cls.text = text_of(cls.payload)

    def rebuilt(self, edit) -> dict:
        changed = copy.deepcopy(self.st)
        edit(changed)
        self.assertNotEqual(changed, self.st, "the edit changed nothing")
        return amd.build_payload(changed)

    @staticmethod
    def plain_story(s: dict) -> None:
        """A story that names only numbers every quarter has."""
        s["quarter_story"]["headline"] = "收入 {revenue}、同比 {revenue_yoy}。"
        s["quarter_story"]["brief"] = "<p>数据中心同比 {dc_yoy}。</p>"

    def test_each_stamped_block_refuses_another_quarter(self) -> None:
        for key in self.STAMPED:
            with self.subTest(block=key):
                self.assertIn(key, self.st)
                with self.assertRaisesRegex(ValueError, "stamped"):
                    self.rebuilt(lambda s, key=key: s[key].__setitem__("period", "Q1 1999"))

    def test_an_absent_optional_block_leaves_its_part_out(self) -> None:
        """Each optional block drops its chart, its table and the words that
        describe them -- and leaves no dangling `Exhibit {EX_…}` behind."""
        full = exhibits_of(self.payload)
        cases = (("followup_closure", ("条待验证问题",), 1, False),
                 ("eps_reconciliation", ("长期投资净收益，non-GAAP 不含", "在净利处的分叉"), 1, False),
                 ("warrants", ("认股权证未归属",), 0, False),
                 ("guidance", ("下季指引（", " 兑现与 "), 0, False),
                 ("purchase_commitments_usd_m", ("是这条序列的新高", "无条件采购承诺走到了哪里"), 1, False),
                 ("next_kpi", ("警戒线", "不能作图的阈值", "应付天数的完整历史见", "下季阈值与当前值"), 2, False),
                 ("balance_sheet_exposure", ("无条件采购承诺一季", "表外与或有敞口", "没有上表的承诺"), 1, True),
                 ("dc_acceleration_claim", ("数据中心会「加速」", "「加速」翻成算术"), 1, True))
        for key, phrases, dropped, plain in cases:
            with self.subTest(block=key):
                def strip(s, key=key, plain=plain):
                    s.pop(key)
                    if plain:
                        self.plain_story(s)
                payload = self.rebuilt(strip)
                text = text_of(payload)
                for phrase in phrases:
                    self.assertIn(phrase, self.text)
                    self.assertNotIn(phrase, text)
                exhibits = exhibits_of(payload)
                self.assertEqual(len(exhibits), len(full) - dropped)
                self.assertEqual([ex["n"] for ex in exhibits], list(range(2, 2 + len(exhibits))))
                self.assertEqual(payload["tables"][0]["n"], exhibits[-1]["n"] + 1)
                self.assertEqual([s for s in strings(payload) if PLACEHOLDER.search(s)], [])
                by_n = {ex["n"] for ex in exhibits}
                for ex in exhibits:
                    for n in re.findall(r"Exhibit (\d+)", ex["note"]):
                        self.assertIn(int(n), by_n, ex["title"])
        self.assertIsNone(self.rebuilt(lambda s: s.pop("guidance"))["guidance"])

    def test_structure_the_page_depends_on_stops_the_build(self) -> None:
        def unguided(s):
            g = s["guidance_history"]
            for key, values in g.items():
                if isinstance(values, list):
                    g[key] = values[:-1]

        def short_block(key):
            def edit(s):
                block = s[key]
                for name, values in block.items():
                    if isinstance(values, list):
                        block[name] = values[:-1]
            return edit

        cases = (
            ("quarter_story", lambda s: s.pop("quarter_story")),
            ("one quarter past", unguided),
            ("do not sum", lambda s: s["segments"]["data_center_usd_m"].__setitem__(
                -1, s["segments"]["data_center_usd_m"][-1] + 1)),
            ("working_capital", short_block("working_capital_cash_flow_usd_m")),
            ("purchase_commitments", short_block("purchase_commitments_usd_m")),
            ("followup_closure", lambda s: s["followup_closure"]["counts"].__setitem__(
                0, s["followup_closure"]["counts"][0] + 1)),
            ("unknown metric", lambda s: s["next_kpi"]["quantified"][0].__setitem__("id", "dso")),
            ("release_accessions", lambda s: s["latest"].__setitem__("source_url", s["latest"]["source_url"].replace(
                s["release_accessions"][-1].replace("-", ""), s["release_accessions"][-2].replace("-", "")))),
            ("disagree", lambda s: s["balance_sheet_exposure"]["items"][0]["values"].__setitem__(
                0, s["balance_sheet_exposure"]["items"][0]["values"][0] + 1)),
            ("with a value", lambda s: (s.pop("balance_sheet_exposure"), self.plain_story(s),
                                        s["purchase_commitments_usd_m"]["total"].__setitem__(-1, None))),
        )
        for message, edit in cases:
            with self.subTest(case=message):
                with self.assertRaisesRegex(ValueError, message):
                    self.rebuilt(edit)
        # The story may only name numbers some block on this page supplies.
        for key, placeholder in (("balance_sheet_exposure", "commit_"), ("dc_acceleration_claim", "dc_")):
            with self.subTest(story_needs=key):
                self.assertIn("{" + placeholder, self.st["quarter_story"]["headline"]
                              + self.st["quarter_story"]["brief"])
                with self.assertRaisesRegex(KeyError, placeholder):
                    self.rebuilt(lambda s, key=key: s.pop(key))

    def test_the_capex_record_sentence_is_computed(self) -> None:
        n = len(self.st["periods"])
        title = one(self.payload, "资本开支 ", "bar_line_dual")["title"]
        capex = self.st["cash_flow_usd_m"]["capex"]
        self.assertTrue(capex[-1] > max(capex[:-1]), "the positive control needs a record quarter")
        self.assertIn(f"两项都是 {n} 季最高", title)
        self.assertIn(f"、为 {n} 季最高", self.payload["headline"])

        def to(value):
            def edit(s):
                c = s["cash_flow_usd_m"]
                c["capex"][-1] = value
                c["free_cash_flow"][-1] = c["operating"][-1] - value
            return edit
        revenue = self.st["financials"]["revenue_usd_m"]
        prior_top = max(capex[:-1])
        intensity_top = max(c / r * 100 for c, r in zip(capex[:-1], revenue[:-1]))
        # neither a record: both sentences go
        payload = self.rebuilt(to(prior_top - 1))
        self.assertNotIn("季最高", one(payload, "资本开支 ", "bar_line_dual")["title"])
        self.assertNotIn(f"、为 {n} 季最高", payload["headline"])
        # a dollar record that is not an intensity record: only the amount is claimed
        amount = prior_top + 1
        self.assertLess(amount / revenue[-1] * 100, intensity_top)
        title = one(self.rebuilt(to(amount)), "资本开支 ", "bar_line_dual")["title"]
        self.assertIn(f"金额是 {n} 季最高", title)
        self.assertNotIn("两项都是", title)

    def test_the_dpo_jump_and_level_sentences_are_computed(self) -> None:
        n = len(self.st["periods"])
        chart = one(self.payload, "应付天数 ", "lines")
        dpo = payable_days(self.st)
        self.assertIn(f"是 {n} 季最大跳升", chart["title"])
        self.assertIn(f"是 {n} 季最大的单季跳升", self.payload["brief"])
        self.assertIn("但水平不是纪录", chart["title"])

        self.assertIn("<b>罕见的是速度</b>", chart["note"])

        def earlier_jump(s):
            cost = s["financials"]["cost_of_sales_usd_m"]
            s["balance_sheet_usd_m"]["payables_incl_related"][1] = round((dpo[0] + 50) * cost[1] / DAYS_PER_QUARTER)
        changed = copy.deepcopy(self.st)
        earlier_jump(changed)
        moved = payable_days(changed)
        rank = 1 + sum(1 for v in moved[:-1] if v > moved[-1])
        payload = amd.build_payload(changed)
        chart = one(payload, "应付天数 ", "lines")
        self.assertNotIn("最大跳升", chart["title"])
        self.assertIn(f"水平排第 {rank}", chart["title"])
        self.assertNotIn("最大的单季跳升", payload["brief"])
        self.assertIn(f"，{n} 季里水平不是最高", payload["brief"])
        self.assertNotIn("罕见的是速度", chart["note"])

        def level_record(s):
            cost = s["financials"]["cost_of_sales_usd_m"][-1]
            s["balance_sheet_usd_m"]["payables_incl_related"][-1] = round((max(dpo) + 10) * cost / DAYS_PER_QUARTER)
        payload = self.rebuilt(level_record)
        chart = one(payload, "应付天数 ", "lines")
        self.assertIn("水平本身也是纪录", chart["title"])
        self.assertNotIn("水平不是纪录", chart["title"])
        self.assertIn(f"水平本身也是 {n} 季最高", payload["brief"])
        self.assertIn(f"本季水平在 {n} 季里排第 1", chart["note"])

    def test_the_data_center_share_record_is_computed(self) -> None:
        self.assertIn("是四分部口径以来最高", one(self.payload, "数据中心 ", "stacked_dual")["title"])
        seg = self.st["segments"]
        revenue = self.st["financials"]["revenue_usd_m"]
        offset = self.st["periods"].index(seg["quarters"][0])
        prior_top = max(d / revenue[offset + k] for k, d in enumerate(seg["data_center_usd_m"][:-1]))
        moved = seg["data_center_usd_m"][-1] - int(prior_top * revenue[-1]) + 1

        def shift(s):
            sg = s["segments"]
            sg["data_center_usd_m"][-1] -= moved
            sg["client_usd_m"][-1] += moved
        payload = self.rebuilt(shift)
        self.assertNotIn("以来最高", one(payload, "数据中心 ", "stacked_dual")["title"])

    def test_the_opex_streak_is_computed(self) -> None:
        rows = scored_record(self.st)
        streak = opex_streak(rows)
        self.assertGreater(streak, 2, "the positive control needs a running streak")
        opex_title = "non-GAAP 营业费用："
        self.assertIn(f"最近 {streak} 季连续高于自己的指引", one(self.payload, opex_title)["note"])
        scored = opex_scored(rows)
        breaker = scored[-3]["q"]

        def broken(s):
            g = s["guidance_history"]
            i = g["quarters"].index(breaker)
            g["actual_non_gaap_opex_usd_m"][i] = g["non_gaap_opex_guide_usd_m"][i] - 1
        changed = copy.deepcopy(self.st)
        broken(changed)
        new = opex_streak(scored_record(changed))
        self.assertEqual(new, 2)
        payload = amd.build_payload(changed)
        note = one(payload, opex_title)["note"]
        self.assertIn(f"<b>最近 {new} 季连续高于自己的指引</b>（{compact(scored[-2]['q'])}–{compact(scored[-1]['q'])}）",
                      note)
        self.assertNotIn(f"最近 {streak} 季", note)
        self.assertIn(f"连续{cn(new)}季花得比自己的费用指引多", one(payload, "上季 ", "bars_labeled")["note"])

        def last_under(s):
            g = s["guidance_history"]
            i = len(g["quarters"]) - 2
            g["actual_non_gaap_opex_usd_m"][i] = g["non_gaap_opex_guide_usd_m"][i] - 1
        payload = self.rebuilt(last_under)
        note = one(payload, opex_title)["note"]
        self.assertNotIn(f"最近 {streak} 季连续高于", note)
        # A streak of zero is not a streak: the note says the last quarter did not
        # overrun instead of printing 「最近 0 季连续高于」.
        self.assertNotIn("最近 0 季", note)
        self.assertIn(f"最近一季 {compact(scored[-1]['q'])} 没有超出指引", note)

    def test_the_commitments_record_and_comparisons_are_computed(self) -> None:
        self.assertIn("是这条序列的新高", one(self.payload, "无条件采购承诺 US$", "lines")["title"])
        pc = self.st["purchase_commitments_usd_m"]
        total = pc["total"]
        prior_top = max(v for v in total[:-1] if v is not None)

        def smaller(s):
            s["purchase_commitments_usd_m"]["total"][-1] = prior_top - 1
            exposure = s.get("balance_sheet_exposure")
            if exposure is not None:
                exposure["items"][0]["values"][-1] = prior_top - 1
        self.assertNotIn("新高", one(self.rebuilt(smaller), "无条件采购承诺 US$", "lines")["title"])

        # a year-ago quarter that is not comparable falls back to the nearest earlier one
        labels = [compact(q) for q in pc["quarters"]]
        target = len(total) - 5
        nearest = max(i for i, v in enumerate(total[:target]) if v is not None)
        self.assertNotIn("不可比", one(self.payload, "无条件采购承诺 US$", "lines")["note"].split("口径变化")[0])
        note = one(self.rebuilt(lambda s: s["purchase_commitments_usd_m"]["total"].__setitem__(target, None)),
                   "无条件采购承诺 US$", "lines")["note"]
        self.assertIn(f"一年前：{labels[target]} 不可比，取更早的 {labels[nearest]} {usd_b(total[nearest])}", note)

    def test_the_cash_title_follows_the_sign_of_the_payables_change(self) -> None:
        wc = self.st["working_capital_cash_flow_usd_m"]
        self.assertGreater(wc["accounts_payable_change"][-1], 0, "the positive control needs a rising quarter")
        self.assertIn("来自应付账款增加", one(self.payload, "经营现金流 ", "grouped_bars")["title"])
        payload = self.rebuilt(lambda s: s["working_capital_cash_flow_usd_m"]["accounts_payable_change"]
                               .__setitem__(-1, -500))
        chart = one(payload, "经营现金流 ", "grouped_bars")
        ocf = self.st["cash_flow_usd_m"]["operating"][-1]
        self.assertEqual(chart["title"], f"经营现金流 {usd_m(ocf)}，应付账款减少占用了 {usd_m(500)}；"
                                         f"不计这一项是 {usd_m(ocf + 500)} D")
        self.assertNotIn("来自应付账款增加", chart["title"])
        self.assertNotIn("来自付款节奏", chart["note"])

    def test_the_routine_notes_answer_to_the_data(self) -> None:
        """「不是本季」 and the years of the negative free-cash-flow quarters."""
        n = len(self.st["periods"])
        margin_title = f"{n} 季 non-GAAP 毛利率由"
        self.assertIn("不是本季", one(self.payload, margin_title, "lines")["note"])

        def peak(s):
            f = s["financials"]
            best = max(o / r for o, r in zip(f["non_gaap_operating_income_usd_m"], f["revenue_usd_m"]))
            f["non_gaap_operating_income_usd_m"][-1] = int(best * f["revenue_usd_m"][-1]) + 50
        note = one(self.rebuilt(peak), margin_title, "lines")["note"]
        self.assertIn("就是本季", note)
        self.assertNotIn("不是本季", note)

        fcf = self.st["cash_flow_usd_m"]["free_cash_flow"]
        negative = [i for i, v in enumerate(fcf) if v < 0]
        years = sorted({int(self.st["periods"][i][-4:]) for i in negative})
        self.assertGreater(len(years), 1)
        last = negative[-1]
        remaining = [int(self.st["periods"][i][-4:]) for i in negative[:-1]]

        def repaid(s):
            c = s["cash_flow_usd_m"]
            c["free_cash_flow"][last] = 1
            c["operating"][last] = c["capex"][last] + 1
        note = one(self.rebuilt(repaid), "自由现金流 ", "bar_line_dual")["note"]
        self.assertIn(f"有 {len(negative) - 1} 季自由现金流为负，都在 {min(remaining)}–{max(remaining)} 年之间", note)

    def test_the_revenue_acceleration_sentence_is_computed(self) -> None:
        title = one(self.payload, "收入 ", "gs_bar")["title"]
        yoy = revenue_growth(self.st)
        self.assertGreater(yoy[-1], yoy[-2], "the positive control needs an accelerating quarter")
        self.assertIn("之后最高", title)
        periods = self.st["periods"]
        ya = periods.index(year_ago(periods[-1]))
        seg_k = self.st["segments"]["quarters"].index(periods[ya])
        revenue = self.st["financials"]["revenue_usd_m"]
        # lift the year-ago quarter until this quarter's growth drops below last quarter's
        lift = int(revenue[-1] / (1 + yoy[-2] / 100) - revenue[ya]) + 1

        def slower(s):
            s["financials"]["revenue_usd_m"][ya] += lift
            s["segments"]["client_usd_m"][seg_k] += lift
        changed = copy.deepcopy(self.st)
        slower(changed)
        new = revenue_growth(changed)
        self.assertLess(new[-1], new[-2])
        title = one(amd.build_payload(changed), "收入 ", "gs_bar")["title"]
        self.assertNotIn("之后最高", title)
        self.assertIn(f"同比增速较上季的 {new[-2]:.1f}% 回落", title)

    def test_the_margin_threshold_breaches_are_computed(self) -> None:
        note = one(self.payload, "non-GAAP 毛利率对 ", "lines")["note"]
        self.assertIn("最近八季里这条线被跌破", note)
        floor = min(gross_margin(self.st)[-8:]) - 1

        def lower(s):
            spec = next(q for q in s["next_kpi"]["quantified"] if q["id"] == "non_gaap_gm")
            spec["threshold"] = floor
        note = one(self.rebuilt(lower), "non-GAAP 毛利率对 ", "lines")["note"]
        self.assertIn("最近八季没有一季跌破这条线", note)
        self.assertNotIn("被跌破", note)


# ═════════════════════════════════════════════════════════════════════════════
class AmdPublishedTest(unittest.TestCase):
    """The files the site serves, and the home-page card."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.st = load()
        cls.payload = amd.build_payload(cls.st)

    def test_the_card_figures_are_recomputed(self) -> None:
        st = self.st
        fin, seg = st["financials"], st["segments"]
        dc = dict(zip(seg["quarters"], seg["data_center_usd_m"]))
        last = st["periods"][-1]
        wanted = [f"Revenue ${fin['revenue_usd_m'][-1] / 1000:.1f}B",
                  f"Data Center {pct(dc[last], dc[year_ago(last)]):+.0f}%",
                  f"Gross margin {fin['non_gaap_gross_profit_usd_m'][-1] / fin['revenue_usd_m'][-1] * 100:.1f}%"]
        self.assertEqual(amd.headline_metrics(st), wanted)
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        card = home.split('href="amd/"', 1)[1].split("</a>", 1)[0]
        self.assertIn(" · ".join(wanted), card)
        self.assertIn(self.payload["latest"]["disclosed_period_label"], card)
        self.assertIn(self.payload["latest"]["release_date"], card)

    def test_published_payload_and_shell(self) -> None:
        self.assertEqual(js_payload(ROOT / "data" / "amd.js", "window.DASH"), self.payload)
        shell = (ROOT / "amd" / "index.html").read_text(encoding="utf-8")
        sources = re.findall(r'<script src="\.\./([^"?]+)(\?v=([0-9a-f]+))?"', shell)
        self.assertEqual([name for name, _, _ in sources],
                         ["data/roster.js", "data/amd.js", "assets/charts.js", "assets/page.js"])
        for name, query, digest in sources:
            with self.subTest(script=name):
                self.assertTrue(query, f"{name} is served without a cache-busting version")
                expected = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()[:len(digest)]
                self.assertEqual(digest, expected, f"{name} carries a stale digest")

    def test_the_registry_entry_matches_the_payload(self) -> None:
        entry = next(e for e in ENTRIES if e["slug"] == "amd")
        company = self.payload["company"]
        self.assertEqual(entry["ticker"], company["ticker"])
        self.assertEqual(entry["name"], company["name"])
        self.assertEqual(entry["group"], company["group"])
        self.assertIn(entry["group"], {g["key"] for g in GROUPS})
        self.assertNotIn("headline_metrics", entry)
        # AMD's quarters are calendar quarters, so no relabelling is claimed
        self.assertNotIn("本站按自然年季度标注", entry["cadence_label"])
        self.assertIn("自然年季度", self.payload["subtitle"])


if __name__ == "__main__":
    unittest.main()
