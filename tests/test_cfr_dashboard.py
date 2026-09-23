"""Richemont page: the identities that license what it publishes.

Richemont prints sales every quarter and profit only for the half-years ending
30 September and 31 March, and its quarterly record has two kinds of hole. Most
of what can go wrong here is silent, so the tests below are grouped by the
failure each one exists to see.

**A quarter that does not exist could be filled.** Before July 2019 the company
reported April to August as a five-month period, in growth rates. Calendar
2016Q2, 2016Q3, 2017Q2 and 2017Q3 are therefore unrecoverable, and the
single most tempting edit to this page is to spread the half-year over them.
`test_the_four_quarters_nobody_can_separate_are_the_five_month_years` pins them
as empty on the series, and `test_missing_quarters_are_empty_not_zero_on_every_chart`
pins them as empty on every chart that draws a quarterly axis.

**A derived quarter could subtract across two bases.** Five quarters were never
printed and are `full year - nine months` or `half-year - first quarter`. Each
stores both legs, so `test_every_derived_quarter_is_its_two_legs` recomputes
every line. What the legs cannot show is whether they share a basis; that is
what `test_the_quarters_add_up_to_the_half_years_the_results_printed` is for.
The quarters come from the sales tables and the half-years from the
income-statement and segment readings of the results announcements -- two
different readings, so the identity is not circular the way `Q1 + Q2 == H1` on
one table would be.

**The subtraction could be the wrong idea.** Eventually the company printed
most quarters itself. `test_every_later_print_matches_the_subtraction_but_one`
holds the subtraction available before each print against the print, and
insists that the only disagreement is July-September 2022 -- the quarter whose
first-quarter leg was published before YNAP was moved to discontinued
operations. A second disagreement anywhere would mean a transcription error,
not a basis change, and would be red here.

**A computed number could be typed.** The headline, brief, titles and the home
card all print counts and percentages; the payload tests recompute each from the
series rather than trusting the sentence.

**A roll could leave last quarter's words behind.** The page is rolled by editing
`series/cfr.json` alone (CLAUDE.md §9), so nothing here names the page's quarter:
`CfrRollTest` holds what a roll must change and what the page does when a block is
stale or absent -- including the first interim roll, whose fiscal year has a
first half and no annual yet -- and `CfrChecksTest` holds the quarter against
`_checks`, a separate reading of the announcement. Rolling re-keys `_checks`; this
file does not change.
"""

from __future__ import annotations

import collections
import copy
import datetime
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import cfr  # noqa: E402
from build.all import ENTRIES  # noqa: E402
from build.board import UNIT_FORMATS, cn_count, cn_ordinal, display_period, headroom  # noqa: E402

REGIONS = ("europe", "asia_pacific", "americas", "japan", "middle_east_africa")
CHANNELS = ("retail", "online_retail", "wholesale")
AREAS = ("jewellery_maisons", "specialist_watchmakers", "online_distributors", "other",
         "inter_segment_eliminations")
QUARTER_END = {"1": "03-31", "2": "06-30", "3": "09-30", "4": "12-31"}
UNSEPARABLE = ["2016Q2", "2016Q3", "2017Q2", "2017Q3"]


def js_payload(path: Path, marker: str) -> dict:
    text = path.read_text(encoding="utf-8")
    return json.loads(text.split(f"{marker} = ", 1)[1].rstrip().rstrip(";"))


def quarter_step(earlier: str, later: str) -> bool:
    y1, q1 = int(earlier[:4]), int(earlier[5])
    y2, q2 = int(later[:4]), int(later[5])
    return (y2, q2) == ((y1 + 1, 1) if q1 == 4 else (y1, q1 + 1))


def load() -> dict:
    return json.loads(cfr.STAGING_PATH.read_text(encoding="utf-8"))


class CfrSeriesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.s = load()
        cls.q = cls.s["quarters"]
        cls.e = cls.s["quarterly_eur_m"]

    # ── the window and the calendar ─────────────────────────────────────────
    def test_the_window_runs_from_2016q1_and_is_contiguous(self) -> None:
        self.assertEqual(self.q[0], "2016Q1")
        self.assertEqual(display_period(self.q[-1]), self.s["latest"]["disclosed_period_label"])
        for key in ("fiscal_quarters", "quarter_basis"):
            self.assertEqual(len(self.s[key]), len(self.q), key)
        for block in ("quarterly_eur_m", "quarterly_cer_pct", "quarterly_actual_pct"):
            for line, values in self.s[block].items():
                self.assertEqual(len(values), len(self.q), f"{block} {line}")
        for a, b in zip(self.q, self.q[1:]):
            self.assertTrue(quarter_step(a, b), (a, b))

    def test_calendar_quarters_map_onto_a_march_fiscal_year(self) -> None:
        """Fiscal Q1 is April-June, so it is the calendar Q2 of the year before
        the fiscal year's number; fiscal Q4 is January-March of that same year."""
        expected = {"2026Q2": "FY27Q1", "2025Q3": "FY26Q2", "2025Q4": "FY26Q3",
                    "2026Q1": "FY26Q4", "2016Q1": "FY16Q4"}
        mapping = dict(zip(self.q, self.s["fiscal_quarters"]))
        for quarter, fiscal in expected.items():
            self.assertEqual(mapping.get(quarter, fiscal), fiscal)
        for quarter, fiscal in mapping.items():
            year, number = int(quarter[:4]), int(quarter[5])
            fy = year if number == 1 else year + 1
            self.assertEqual(fiscal, f"FY{fy % 100:02d}Q{4 if number == 1 else number - 1}", quarter)
        fy, number = mapping[self.q[-1]][:4], int(mapping[self.q[-1]][-1])
        self.assertIn(f"（公司 {fy} 第{cn_ordinal(number)}季）", cfr.build_payload(self.s)["title"])

    # ── the holes ────────────────────────────────────────────────────────────
    def test_the_four_quarters_nobody_can_separate_are_the_five_month_years(self) -> None:
        basis = self.s["quarter_basis"]
        missing = [q for q, b in zip(self.q, basis) if b == "missing"]
        self.assertEqual(missing, UNSEPARABLE)
        fiscal = [self.s["fiscal_quarters"][self.q.index(q)] for q in missing]
        self.assertEqual(fiscal, ["FY17Q1", "FY17Q2", "FY18Q1", "FY18Q2"])
        for quarter in missing:
            i = self.q.index(quarter)
            for key, values in self.e.items():
                self.assertIsNone(values[i], f"{quarter} {key} was filled")
            for key, values in self.s["quarterly_cer_pct"].items():
                self.assertIsNone(values[i], f"{quarter} growth {key} was filled")

    def test_the_basis_census_is_the_one_the_page_prints(self) -> None:
        """The five derived and four missing quarters are history; every quarter
        since is printed, so a roll adds one printed quarter and nothing else."""
        basis = self.s["quarter_basis"]
        self.assertEqual([q for q, b in zip(self.q, basis) if b == "derived"],
                         ["2016Q1", "2017Q1", "2018Q1", "2018Q3", "2019Q1"])
        self.assertEqual([q for q, b in zip(self.q, basis) if b == "missing"], UNSEPARABLE)
        self.assertEqual(basis.count("printed"), len(self.q) - 9)
        self.assertTrue(all(b == "printed" for b in basis[self.q.index("2019Q2"):]))

    def test_every_derived_quarter_is_its_two_legs(self) -> None:
        checked = 0
        for i, quarter in enumerate(self.q):
            if self.s["quarter_basis"][i] != "derived":
                continue
            src = self.s["quarter_sources"][quarter]
            full, part = src["legs_eur_m"]
            fiscal = self.s["fiscal_quarters"][i]
            fy = fiscal[:4]
            if fiscal.endswith("Q4"):
                self.assertEqual(src["periods"], [fy, fy + "_9M"])
            else:
                self.assertEqual(src["periods"], [fy + "H1", fy + "Q1"])
            for key, values in self.e.items():
                if full.get(key) is None or part.get(key) is None:
                    self.assertIsNone(values[i], f"{quarter} {key}")
                    continue
                self.assertEqual(values[i], full[key] - part[key], f"{quarter} {key}")
                checked += 1
        self.assertGreaterEqual(checked, 5 * 10)

    def test_growth_rates_are_never_derived(self) -> None:
        """A constant-currency rate is not additive; a subtracted quarter has none."""
        for i, quarter in enumerate(self.q):
            if self.s["quarter_basis"][i] == "printed":
                continue
            for key, values in self.s["quarterly_cer_pct"].items():
                self.assertIsNone(values[i], f"{quarter} {key}")

    # ── identities ───────────────────────────────────────────────────────────
    def test_every_quarter_closes_three_ways(self) -> None:
        for i, quarter in enumerate(self.q):
            total = self.e["total"][i]
            if total is None:
                continue
            for name, keys in (("regions", REGIONS), ("channels", CHANNELS), ("business areas", AREAS)):
                parts = [self.e[k][i] for k in keys if self.e[k][i] is not None]
                self.assertLessEqual(abs(sum(parts) - total), 2, f"{quarter} {name}")

    def test_the_quarters_add_up_to_the_half_years_the_results_printed(self) -> None:
        """Sales tables against the results announcements' own half-year figures."""
        halves = self.s["halves"]
        pairs = {"total": self.s["half_eur_m"]["sales"]}
        for key in ("jewellery_maisons", "specialist_watchmakers", "other"):
            pairs[key] = self.s["half_segment_sales_eur_m"][key]
        compared = 0
        for i, label in enumerate(halves):
            fy = 2000 + int(label[2:4])
            legs = (f"{fy - 1}Q2", f"{fy - 1}Q3") if label.endswith("H1") else (f"{fy - 1}Q4", f"{fy}Q1")
            if not all(leg in self.q for leg in legs):
                continue
            a, b = (self.q.index(leg) for leg in legs)
            for key, half in pairs.items():
                if None in (self.e[key][a], self.e[key][b], half[i]):
                    continue
                self.assertEqual(self.e[key][a] + self.e[key][b], half[i], f"{label} {key}")
                compared += 1
        # 72 comparisons up to FY26H2; every half since adds four more
        self.assertGreaterEqual(compared, 72)

    def test_every_later_print_matches_the_subtraction_but_one(self) -> None:
        checks = self.s["derived_checks"]
        self.assertGreaterEqual(len(checks), 180)
        differ = [c for c in checks if c["derived"] != c["printed"]]
        self.assertEqual({c["quarter"] for c in differ}, {"2022Q3"})
        docs = {d["doc_id"]: d for d in self.s["documents"]}
        for check in differ:
            dates = [docs[d]["release_date"] for d in check["derived_docs"]]
            self.assertTrue(any(date < "2022-11-11" for date in dates),
                            "the 2022Q3 disagreement must come from a leg printed before YNAP was reclassified")
        self.assertTrue(all(not c["same_document"] for c in checks))

    def test_the_trap_quarter_is_the_one_the_page_describes(self) -> None:
        misses = [d for d in self.s["first_print_derivations"] if d["derived_total"] != d["printed_total"]]
        self.assertEqual(len(misses), 1)
        trap = misses[0]
        self.assertEqual(trap["quarter"], "2022Q3")
        self.assertEqual(trap["printed_total"] - trap["derived_total"], 610)
        self.assertLess(trap["online_retail"], 0)

    def test_the_restatement_census_only_touches_the_two_reclassifications(self) -> None:
        periods = {c["period"] for c in self.s["restatement_census"]}
        for period in periods:
            self.assertTrue(period.startswith("FY18") or period.startswith("FY22") or period == "FY23Q1", period)
        self.assertGreaterEqual(len(self.s["restatement_census"]), 194)
        self.assertGreaterEqual(self.s["restatement_paired_readings"], 1930)
        # the census names how far it read, and never further than the corpus
        self.assertLessEqual(self.s["restatement_census_documents"], len(self.s["documents"]))

    def test_a_printed_second_half_matches_the_subtraction(self) -> None:
        checks = self.s["half_checks"]
        self.assertGreaterEqual(len({c["half"] for c in checks}), 5)
        for check in checks:
            self.assertEqual(check["printed_total"], check["derived_total"], check["half"])

    def test_each_half_year_pair_comes_from_one_generation_of_documents(self) -> None:
        docs = {d["doc_id"]: d for d in self.s["documents"]}
        for fy, src in self.s["half_sources"].items():
            h1_doc = docs[src["h1_doc"]]
            self.assertEqual(h1_doc["kind"], "interim_results")
            expected = f"FY{int(fy[2:]) + 1}" if src["mode"] == "next_year" else fy
            self.assertEqual(h1_doc["fiscal_year"], expected, fy)
            if src.get("year_doc") is None:
                # a fiscal year whose annual has not come yet: its first half only
                self.assertEqual(fy, list(self.s["half_sources"])[-1])
                self.assertEqual(self.s["halves"][-1], f"{fy}H1")
                continue
            year_doc = docs[src["year_doc"]]
            self.assertEqual(year_doc["kind"], "annual_results")
            self.assertEqual(year_doc["fiscal_year"], expected, fy)
        # the two years that fall back do so for a recorded reason; the latest
        # year falls back because nothing later exists
        latest_fy = list(self.s["half_sources"])[-1]
        own = sorted(fy for fy, v in self.s["half_sources"].items() if v["mode"] == "own_year" and fy != latest_fy)
        self.assertEqual(own, ["FY19", "FY21"])
        self.assertEqual(self.s["half_sources"][latest_fy]["mode"], "own_year")

    # ── what the disclosure shape says ───────────────────────────────────────
    def test_the_disclosure_lags_are_measured_from_release_dates(self) -> None:
        docs = {d["doc_id"]: d for d in self.s["documents"]}
        for quarter, first in self.s["first_printed"].items():
            self.assertEqual(docs[first["doc"]]["release_date"], first["published"])
            end = datetime.date.fromisoformat(f"{quarter[:4]}-{QUARTER_END[quarter[5]]}")
            self.assertEqual((datetime.date.fromisoformat(first["published"]) - end).days,
                             first["lag_days"], quarter)
        printed = [q for q, b in zip(self.q, self.s["quarter_basis"]) if b == "printed"]
        self.assertEqual(sorted(self.s["first_printed"]), sorted(printed))

    def test_the_company_streak_claim_holds_on_its_own_printed_rates(self) -> None:
        """When the quarter's announcement makes the claim, the page counts it again
        on the company's own printed rates and says whether it holds."""
        block = self.s.get("company_claims")
        claims = [] if block is None else [c for c in block["items"] if c["key"] == "jewellery_streak"]
        payload = cfr.build_payload(self.s)
        for claim in claims:
            rates = self.s["quarterly_cer_pct"][claim["line"]]
            streak = 0
            for v in reversed(rates):
                if v is None or v < claim["threshold_pct"]:
                    break
                streak += 1
            self.assertIn("consecutive quarter of double-digit growth", claim["quote"])
            area = next(ex for section in payload["sections"] for ex in section["exhibits"]
                        if ex["ref"] == "EX_AREA_CER")
            verdict = "成立" if streak == claim["count"] else f"不成立，本页逐季数到 {streak} 个"
            self.assertIn(f"「第{cn_ordinal(claim['count'])}个连续双位数季度」", area["note"])
            self.assertIn(f"本页逐季核过：{verdict}。", area["note"])

    def test_the_jewellery_range_break_is_named_only_the_first_time(self) -> None:
        hv = cfr.half_view(self.s)
        margin = hv["margin"]["jewellery_maisons"]
        rng = next(x for x in self.s["statements"] if x["key"] == "jewellery_margin_range")
        below = [i for i in hv["jewel_after"] if margin[i] < rng["low"]]
        payload = cfr.build_payload(self.s)
        first_time = below == [hv["last"]]
        self.assertEqual(hv["jewel_first_break"], first_time)
        self.assertEqual("在这句话之后第一次被跌破" in payload["headline"], first_time)
        seg = self.s["half_segment_result_eur_m"]["jewellery_maisons"][hv["last"]]
        sales = self.s["half_segment_sales_eur_m"]["jewellery_maisons"][hv["last"]]
        self.assertIn(f"珠宝经营利润率是 {seg / sales * 100:.1f}%", payload["headline"])


class CfrPayloadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.s = load()
        cls.q = cls.s["quarters"]
        cls.payload = cfr.build_payload(cls.s)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]
        cls.qv = cfr.quarter_view(cls.s)
        cls.hv = cfr.half_view(cls.s)

    def quarterly(self) -> list[dict]:
        return [ex for ex in self.exhibits if ex.get("xlabels") == self.s["quarters"]]

    def test_the_page_is_in_the_four_part_format(self) -> None:
        """The site's four parts, in order, with their exact titles, none empty; and
        the page's own sentence about its layout says the same thing."""
        self.assertEqual([(s["id"], s["title"]) for s in self.payload["sections"]],
                         [("settled", "一、上季跟踪指标兑现了吗"), ("quarter_highlights", "二、本季重点"),
                          ("next_quarter", "三、下季要跟踪什么"), ("routine", "四、长期常规跟踪")])
        for section in self.payload["sections"]:
            self.assertTrue(section["exhibits"], section["id"])
        self.assertIn("本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列", self.payload["notes"][0])
        self.assertNotIn("五段", text_of(self.payload))
        self.assertNotIn("第五节", text_of(self.payload))

    def test_the_long_records_sit_in_the_routine_part(self) -> None:
        """The quarter's part carries the quarter. The half-year profit record, the
        structure shares, the currency gap and the disclosure lag are routine series:
        Richemont publishes no profit for a sales-only quarter, so a half-year chart
        in the highlights would present last half's profit as this quarter's news."""
        by_section = {s["id"]: s["exhibits"] for s in self.payload["sections"]}
        routine = [ex["ref"] for ex in by_section["routine"]]
        for ref in ("EX_AREA_MIX", "EX_REGION_MIX", "EX_DTC", "EX_MARGINS", "EX_JEWEL_OP", "EX_CASH",
                    "EX_FX_GAP", "EX_LAG"):
            self.assertIn(ref, routine)
        for exhibit in by_section["quarter_highlights"]:
            self.assertFalse(re.fullmatch(r"\d{4}-\d{2}", str(exhibit["xlabels"][0])), exhibit["title"])
            self.assertNotIn("利润", exhibit["title"], exhibit["title"])

    def test_exhibits_are_numbered_from_one_and_tables_follow(self) -> None:
        self.assertEqual([ex["n"] for ex in self.exhibits], list(range(1, len(self.exhibits) + 1)))
        self.assertEqual([t["n"] for t in self.payload["tables"]],
                         list(range(len(self.exhibits) + 1, len(self.exhibits) + 1 + len(self.payload["tables"]))))
        self.assertIn("跨页对照", self.payload["tables"][-1]["title"])

    def test_every_series_is_as_long_as_the_axis_it_is_drawn_against(self) -> None:
        for exhibit in self.exhibits:
            n = len(exhibit["xlabels"])
            if "values" in exhibit:
                self.assertEqual(len(exhibit["values"]), n, exhibit["title"])
            for key in ("series", "stacks", "groups"):
                for member in exhibit.get(key, []):
                    self.assertEqual(len(member["values"]), n, f"{exhibit['title']} {member['name']}")
            for key in ("bar", "line", "yoy"):
                block = exhibit.get(key)
                if isinstance(block, dict):
                    self.assertEqual(len(block["values"]), n, f"{exhibit['title']} {key}")

    def test_half_year_charts_are_labelled_by_the_month_each_half_ends(self) -> None:
        """Every half-year axis is labelled by the month the half ends. The one chart
        allowed a point past the last half is the net-cash threshold chart, whose last
        point is the quarter-end figure the trading update printed."""
        half = [ex for ex in self.exhibits if ex["xlabels"] and re.fullmatch(r"\d{4}-\d{2}", ex["xlabels"][0])]
        self.assertGreaterEqual(len(half), 5)
        expected = ["09" if label.endswith("H1") else "03" for label in self.s["halves"]]
        for exhibit in half:
            months = [label[5:] for label in exhibit["xlabels"]]
            self.assertEqual(months[:len(expected)], expected, exhibit["title"])
            extra = exhibit["xlabels"][len(expected):]
            if extra:
                self.assertEqual(exhibit["ref"], "EX_NEXT_NET_CASH", exhibit["title"])
                self.assertEqual(extra, [self.s["latest"]["period_end"][:7]])
                self.assertNotEqual(self.s["balance"][-1]["date"], self.s["latest"]["period_end"])

    def test_no_quarterly_chart_carries_a_profit_figure(self) -> None:
        for exhibit in self.quarterly():
            self.assertNotIn("利润", exhibit["title"], exhibit["title"])

    def test_missing_quarters_are_empty_not_zero_on_every_chart(self) -> None:
        missing = [self.s["quarters"].index(q) for q in UNSEPARABLE]
        charts = self.quarterly()
        self.assertGreaterEqual(len(charts), 8)
        for exhibit in charts:
            blocks = ([exhibit["values"]] if "values" in exhibit else []) + \
                     [m["values"] for m in exhibit.get("series", [])] + \
                     [exhibit[k]["values"] for k in ("yoy",) if k in exhibit]
            for values in blocks:
                for i in missing:
                    if values[i] is not None:
                        # a flat threshold line is not data
                        self.assertEqual(len(set(values)), 1, exhibit["title"])

    def test_no_smoothed_series_crosses_a_hole(self) -> None:
        """`stacked_dual`, `gs_line` and `lines_endlabels` draw a spline through
        every index; a null inside one bends the curve toward zero with no NaN
        and nothing off-canvas. This page's share chart shipped that way in its
        first build, so no smoothed kind may carry a hole here."""
        for exhibit in self.exhibits:
            if exhibit["kind"] == "stacked_dual":
                self.assertNotIn(None, exhibit["line"]["values"], exhibit["title"])
            if exhibit["kind"] in ("gs_line", "gs_line_avg"):
                self.assertNotIn(None, exhibit["values"], exhibit["title"])
            if exhibit["kind"] == "lines_endlabels":
                for member in exhibit["series"]:
                    self.assertNotIn(None, member["values"], exhibit["title"])

    def test_long_axes_carry_a_step(self) -> None:
        for exhibit in self.exhibits:
            if len(exhibit["xlabels"]) > 30:
                self.assertIn("xstep", exhibit, exhibit["title"])

    def test_the_single_gs_bar_carries_a_yoy_line_and_hatches_the_derived_quarters(self) -> None:
        bars = [ex for ex in self.exhibits if ex["kind"] == "gs_bar"]
        self.assertEqual(len(bars), 1)
        bar = bars[0]
        self.assertTrue(any(v is not None for v in bar["yoy"]["values"]))
        derived = [i for i, b in enumerate(self.s["quarter_basis"]) if b == "derived"]
        self.assertEqual(bar["bar_marks"], derived)
        self.assertEqual(bar["break_at"], [self.s["quarters"].index("2018Q2"), self.s["quarters"].index("2021Q2")])

    def test_the_headline_counts_are_recomputed_not_typed(self) -> None:
        basis = self.s["quarter_basis"]
        brief = self.payload["brief"]
        for count in (basis.count("printed"), basis.count("derived"), basis.count("missing"),
                      len(self.s["derived_checks"])):
            self.assertIn(str(count), brief)
        headline = self.payload["headline"]
        if self.qv["streak"]:
            self.assertIn(f"连续第 {self.qv['streak']} 个", headline)
        jm = self.hv["margin"]["jewellery_maisons"][self.hv["last"]]
        self.assertIn(f"{jm:.1f}%", headline)
        e = self.s["quarterly_eur_m"]
        self.assertIn(f"€{e['total'][-1]:,.0f}M", headline)
        # the base effect and where the extra euros came from, recomputed here
        cer = self.s["quarterly_cer_pct"]["total"]
        two = ((1 + cer[-5] / 100) * (1 + cer[-1] / 100)) ** 0.5 * 100 - 100
        self.assertIn(f"上年同季恒定汇率只有 {cfr.signed(cer[-5])}，两年叠加年化 {cfr.signed(two, 1)}", headline)
        gain = e["total"][-1] - e["total"][-5]
        jewel = e["jewellery_maisons"][-1] - e["jewellery_maisons"][-5]
        self.assertIn(f"多卖的 €{gain:,.0f}M 里珠宝占 {jewel / gain * 100:.0f}%", headline)
        gross = self.hv["gross"][self.hv["last"]]
        self.assertIn(f"集团毛利率 {round(gross, 1):.1f}%", headline)

    def test_the_section_one_tallies_are_counted_not_typed(self) -> None:
        jewel = next(ex for ex in self.exhibits if ex["ref"] == "EX_JEWEL_BAND")
        margin = self.hv["margin"]["jewellery_maisons"]
        after = self.hv["jewel_after"]
        inside = sum(1 for i in after if 30 <= margin[i] <= 35)
        self.assertIn(f"那之后的 {len(after)} 个半年里 {inside} 个在区间内", jewel["title"])
        watch = next(ex for ex in self.exhibits if ex["ref"] == "EX_WATCH_BAND")
        wm = self.hv["margin"]["specialist_watchmakers"]
        wafter = self.hv["watch_after"]
        self.assertIn(f"此后 {len(wafter)} 个半年只有 {sum(1 for i in wafter if 17 <= wm[i] <= 20)} 个", watch["title"])
        op = next(ex for ex in self.exhibits if ex["ref"] == "EX_JEWEL_OP")
        over = sum(1 for v in self.hv["jewel_of_op"] if v > 100)
        self.assertIn(f"{len(self.s['halves'])} 个半年里 {over} 个", op["title"])

    def test_the_growth_gaps_are_counted_from_the_record(self) -> None:
        """The note under the business-area chart once said the fiscal Q2 and Q4
        gaps before 2021Q2 were "mostly printed years later": four of those eleven
        were ever printed as quarters, and three of the gaps had a single-quarter
        group rate printed in the announcements' text. Every count in the sentence
        is now read off the record."""
        area = next(ex for ex in self.exhibits if ex["ref"] == "EX_AREA_CER")
        cer = self.s["quarterly_cer_pct"]["jewellery_maisons"]
        basis = self.s["quarter_basis"]
        gaps = [i for i, v in enumerate(cer) if v is None]
        later = [i for i in gaps if basis[i] == "printed"]
        self.assertIn(f"{len(gaps)} 个缺口里 {len(later)} 个", area["note"])
        self.assertIn(f"{sum(1 for i in gaps if basis[i] == 'derived')} 个只能减出，"
                      f"{sum(1 for i in gaps if basis[i] == 'missing')} 个连金额也拆不出来", area["note"])
        if later and min(self.qv["lags"][i] for i in later) > 365:
            self.assertIn("在季末一年多以后才第一次被印成单独季度", area["note"])
        for rate in self.s["text_quarter_rates"]:
            if rate["line"] == "total" and self.q.index(rate["quarter"]) in gaps:
                self.assertIn(f"{rate['quarter']} {cfr.signed(rate['cer_pct'])}", area["note"])
        self.assertIn("没有在销售表里按单独季度印过增速", area["note"])
        self.assertNotIn("多数是几年后才印", area["note"])

    def test_a_region_that_sold_less_is_drawn_below_zero(self) -> None:
        """`bars_labeled` has a zero floor; the rollback drill put Middle East & Africa's
        −€65M under the plot. A negative increment switches the chart to the grouped
        form, which draws below zero with the same labels."""
        shrinking = copy.deepcopy(self.s)
        e = shrinking["quarterly_eur_m"]["middle_east_africa"]
        e[-1] = e[-5] - 50
        chart = next(ex for section in cfr.build_payload(shrinking)["sections"] for ex in section["exhibits"]
                     if ex["ref"] == "EX_INCREMENT")
        self.assertEqual(chart["kind"], "grouped_bars")
        self.assertLess(min(chart["groups"][0]["values"]), 0)
        self.assertTrue(chart["bar_labels"])
        mine = next(ex for ex in self.exhibits if ex["ref"] == "EX_INCREMENT")
        values = mine.get("values") or mine["groups"][0]["values"]
        self.assertEqual(mine["kind"], "bars_labeled" if min(values) >= 0 else "grouped_bars")

    def test_the_increment_title_ranks_the_regions(self) -> None:
        """The title used to name Asia Pacific, the Americas and Middle East & Africa
        by hand; it now names the two largest increments and the smallest, whichever
        regions they are."""
        e = self.s["quarterly_eur_m"]
        inc = {k: e[k][-1] - e[k][-5] for k in REGIONS}
        ranked = sorted(REGIONS, key=lambda k: inc[k], reverse=True)
        names = {"europe": "欧洲", "asia_pacific": "亚太", "americas": "美洲", "japan": "日本",
                 "middle_east_africa": "中东与非洲"}
        title = next(ex for ex in self.exhibits if ex["ref"] == "EX_INCREMENT")["title"]
        first, second, least = ranked[0], ranked[1], ranked[-1]
        self.assertIn(f"：{names[first]} {cfr.eur(inc[first])}、{names[second]} {cfr.eur(inc[second])}，"
                      f"{names[least]}", title)

    def test_the_tracking_note_says_when_the_thresholds_settle(self) -> None:
        """The second and fourth fiscal quarters have no sales announcement: their
        sales come with the half's results, so every threshold settles on that date.
        After a first or third fiscal quarter the sales lines settle earlier."""
        chart = next(ex for ex in self.exhibits if ex["ref"] == "EX_HEADROOM")
        count = len(self.s["next_kpi"]["quantified"])
        following = int(self.s["fiscal_quarters"][-1][-1]) % 4 + 1
        date = self.s["latest"]["next_release"]["date"]
        if following in (2, 4):
            self.assertIn(f"{cn_count(count)}条都要等 {date} 的", chart["note"])
        else:
            self.assertIn(f"利润与资产负债表类的要等 {date} 的", chart["note"])

    def test_literal_slots_and_page_notes_carry_no_markup(self) -> None:
        for key in ("title", "subtitle", "headline", "tracker"):
            self.assertIsNone(re.search(r"</?[a-z][a-z0-9]*>", self.payload[key]), key)
        for note in self.payload["notes"]:
            self.assertIsNone(re.search(r"</?[a-z][a-z0-9]*>", note), note[:40])

    def test_sources_are_richemont_https_links_and_none_point_at_edgar(self) -> None:
        links = [link["url"] for link in self.payload["source_links"]] + [self.payload["source_url"]]
        for url in links:
            self.assertTrue(url.startswith("https://www.richemont.com/"), url)
        for document in self.s["documents"]:
            self.assertTrue(document["url"].startswith("https://www.richemont.com/media/"), document["doc_id"])
        self.assertNotIn("sec.gov", json.dumps(self.payload))

    def test_the_guidance_slot_is_empty_because_the_company_issues_none(self) -> None:
        self.assertIsNone(self.payload["guidance"])
        self.assertEqual(self.s["guidance_census"]["sales_or_growth_targets"], 0)
        census = self.s["guidance_census"]
        self.assertLessEqual(census["documents"], len(self.s["documents"]))
        self.assertTrue(any(f"在 {census['documents']} 份公告里" in note for note in self.payload["notes"]),
                        "the census prints its own scope, not the corpus size")

    def test_thresholds_use_known_units_and_the_chart_agrees_with_the_table(self) -> None:
        chart = next(ex for ex in self.exhibits if ex["ref"] == "EX_HEADROOM")
        table = next(t for t in self.payload["tables"] if "下季阈值的原始单位" in t["title"])
        entries = self.s["next_kpi"]["quantified"]
        self.assertEqual(len(chart["values"]), len(entries))
        self.assertEqual(len(table["rows"]), len(entries))
        for entry, value, row in zip(entries, chart["values"], table["rows"]):
            self.assertIn(entry["unit"], UNIT_FORMATS)
            self.assertEqual(row[0], entry["metric"])
            self.assertEqual(f"{value:+.1f}%", row[4])

    def test_threshold_current_values_are_read_from_the_series(self) -> None:
        cer = self.s["quarterly_cer_pct"]
        chart = next(ex for ex in self.exhibits if ex["ref"] == "EX_HEADROOM")
        jewellery = cer["jewellery_maisons"]
        current = {
            "cer_total": cer["total"][-1],
            "cer_watchmakers": cer["specialist_watchmakers"][-1],
            "cer_wholesale": cer["wholesale"][-1],
            "jewellery_two_year": round(((1 + jewellery[-5] / 100) * (1 + jewellery[-1] / 100)) ** 0.5 * 100 - 100, 1),
            "half_gross_margin": round(self.hv["gross"][-1], 1),
            # the trading update's own figure, or the balance sheet when the quarter ends a half
            "net_cash": ((self.s.get("net_cash_quarter_end") or {}).get("eur_bn")
                         or (self.s["balance"][-1]["net_cash_position"] / 1000
                             if self.s["balance"][-1]["date"] == self.s["latest"]["period_end"] else None)),
        }
        for entry, value in zip(self.s["next_kpi"]["quantified"], chart["values"]):
            self.assertEqual(value, round(headroom(entry["direction"], entry["threshold"],
                                                   current[entry["id"]]), 1), entry["metric"])

    def test_published_payload_and_shell(self) -> None:
        self.assertEqual(js_payload(ROOT / "data" / "cfr.js", "window.DASH"), self.payload)
        shell = (ROOT / "cfr" / "index.html").read_text(encoding="utf-8")
        self.assertIn("../data/cfr.js", shell)
        self.assertIn("CFR", shell)

    def test_the_roster_entry_matches_the_payload(self) -> None:
        entry = next(e for e in ENTRIES if e["slug"] == "cfr")
        self.assertEqual(entry["ticker"], self.payload["company"]["ticker"])
        self.assertEqual(entry["group"], self.payload["company"]["group"])
        self.assertIn("本站按自然年季度标注", entry["cadence_label"])
        self.assertIn("半年", entry["cadence_label"])
        e = self.s["quarterly_eur_m"]["total"][-1]
        cer = self.s["quarterly_cer_pct"]["total"][-1]
        jm = self.hv["margin"]["jewellery_maisons"][self.hv["last"]]
        half = self.s["halves"][-1][-2:]
        # The card figures are computed by the builder from the series (no
        # longer typed into ENTRIES); recomputed here from the half-year view.
        self.assertEqual(cfr.headline_metrics(self.s),
                         [f"Sales €{e:,.0f}M", f"恒定汇率 {cer:+.0f}%", f"珠宝 {half} 利润率 {jm:.1f}%"])

    def test_the_home_page_card_matches_the_payload(self) -> None:
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        card = home.split('href="cfr/"', 1)[1].split("</a>", 1)[0]
        self.assertIn(self.payload["latest"]["release_date"], card)
        self.assertIn(self.payload["latest"]["disclosed_period_label"], card)
        self.assertIn(" · ".join(cfr.headline_metrics(self.s)), card)


class CfrSettledTest(unittest.TestCase):
    """Section one settles what the previous note left: its follow-up questions, as
    this quarter's note (section 0) judged them, and the quantified thresholds of its
    section 8, measured with this quarter's printed figures.

    What the notes say is typed a second time into `_checks["note"]` -- which no
    builder reads -- so the blocks the page is built from are held against a separate
    copy of the two notes, and the page against the blocks.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.s = load()
        cls.note = cls.s["_checks"]["note"]
        cls.payload = cfr.build_payload(cls.s)
        cls.settled = next(sec for sec in cls.payload["sections"] if sec["id"] == "settled")["exhibits"]
        cls.qv = cfr.quarter_view(cls.s)
        cls.hv = cfr.half_view(cls.s)

    def test_the_closure_is_the_notes_section_zero(self) -> None:
        block = self.s["followup_closure"]
        tally = collections.Counter(item["verdict"] for item in block["items"])
        self.assertEqual(len(block["items"]), self.note["followup_total"])
        self.assertEqual(dict(tally), self.note["followup_counts"])
        self.assertEqual(sum(1 for item in block["items"] if item.get("structural")),
                         self.note["followup_structural"])
        chart = self.settled[0]
        self.assertEqual(chart["kind"], "bars_labeled")
        shown = [(label, tally[label]) for label in block["labels"] if tally[label]]
        self.assertEqual(chart["xlabels"], [label for label, _ in shown])
        self.assertEqual(chart["values"], [count for _, count in shown])
        self.assertEqual(chart["title"], f"上季 {len(block['items'])} 条待验证问题："
                         + "、".join(f"{count} 条{label}" for label, count in shown))
        # the note prints this quarter's printed rates, not typed ones
        cer = self.s["quarterly_cer_pct"]
        for line in ("jewellery_maisons", "specialist_watchmakers", "other"):
            self.assertIn(cfr.signed(cer[line][-1]), chart["note"])
        self.assertNotIn("{", chart["note"])

    def test_a_verdict_outside_the_labels_stops_the_build(self) -> None:
        stray = copy.deepcopy(self.s)
        stray["followup_closure"]["items"][0]["verdict"] = "被证伪"
        with self.assertRaisesRegex(ValueError, "outside its labels"):
            cfr.build_payload(stray)

    def test_the_prior_thresholds_are_the_previous_notes_section_eight(self) -> None:
        block = self.s["prior_kpi_settlement"]
        self.assertEqual([{k: e[k] for k in ("id", "metric", "direction", "threshold")} for e in block["quantified"]],
                         self.note["prior_thresholds"])
        self.assertEqual([p["metric"] for p in block["pending"]], [p["metric"] for p in self.note["prior_pending"]])
        for pending, noted in zip(block["pending"], self.note["prior_pending"]):
            # the note names the month; the block carries the date the company's calendar gives
            self.assertTrue(pending["settles"].startswith(noted["settles"]), pending["metric"])
        total = len(block["quantified"]) + len(block["pending"])
        overview = self.settled[1]
        self.assertEqual(overview["kind"], "diverging_bars")
        self.assertTrue(overview["title"].startswith(f"上季 {total} 条量化阈值："), overview["title"])
        self.assertIn(f"本季能结算的 {len(block['quantified'])} 条", overview["title"])
        cer = self.s["quarterly_cer_pct"]
        lines = {"cer_jewellery": "jewellery_maisons", "cer_americas": "americas"}
        for entry, value in zip(block["quantified"], overview["values"]):
            actual = cer[lines[entry["id"]]][-1]
            self.assertEqual(value, round(headroom(entry["direction"], entry["threshold"], actual), 1), entry["id"])
        # one line chart per settled threshold, drawn over the whole record, titled with its verdict
        for entry, chart in zip(block["quantified"], self.settled[2:2 + len(block["quantified"])]):
            actual = cer[lines[entry["id"]]][-1]
            word = "守住" if headroom(entry["direction"], entry["threshold"], actual) >= 0 else "已击穿"
            self.assertEqual(chart["title"], f"{entry['metric']}：{word}上季阈值 {entry['threshold']:.1f}%")
            self.assertEqual(chart["xlabels"], self.s["quarters"])
            self.assertEqual(chart["series"][0]["values"], cer[lines[entry["id"]]])
            self.assertEqual(set(chart["series"][1]["values"]), {entry["threshold"]})

    def test_the_held_list_has_to_be_what_the_numbers_say(self) -> None:
        wrong = copy.deepcopy(self.s)
        entry = wrong["prior_kpi_settlement"]["quantified"][0]
        entry["threshold"] = self.s["quarterly_cer_pct"]["jewellery_maisons"][-1] + 1.0
        with self.assertRaisesRegex(ValueError, "the data says"):
            cfr.build_payload(wrong)
        typed = copy.deepcopy(self.s)
        typed["prior_kpi_settlement"]["quantified"][0]["actual"] = 24.0
        with self.assertRaisesRegex(ValueError, "computed from the series"):
            cfr.build_payload(typed)

    def test_a_pending_interim_threshold_follows_the_next_results_date(self) -> None:
        moved = copy.deepcopy(self.s)
        moved["latest"]["next_release"]["date"] = "2099-11-13"
        with self.assertRaisesRegex(ValueError, "latest.next_release"):
            cfr.build_payload(moved)

    def test_a_threshold_chart_draws_every_printed_rate(self) -> None:
        """Before 2021Q2 most printed rates stand between two gaps, and a line with no
        neighbour draws nothing: the threshold charts carry markers, and any rate past
        the capped axis is named in the cap note."""
        for chart in self.settled[2:4]:
            values = chart["series"][0]["values"]
            self.assertTrue(chart.get("markers"), chart["title"])
            beyond = [label for label, v in zip(chart["xlabels"], values)
                      if v is not None and abs(v) > cfr.RATE_CAP]
            if beyond:
                for label in beyond:
                    self.assertIn(label, chart["cap_note"])
            else:
                self.assertNotIn("cap_note", chart)

    def test_the_company_ranges_follow_the_settlement(self) -> None:
        refs = [ex.get("ref") for ex in self.settled]
        self.assertEqual(refs[-2:], ["EX_JEWEL_BAND", "EX_WATCH_BAND"])
        self.assertEqual(refs[0], "EX_CLOSURE")

    def test_the_baume_mercier_sale_is_reported_as_completed(self) -> None:
        """The page used to say the sale was expected to close in the summer; Richemont
        announced its completion on 1 July 2026, before the page was built."""
        bm = self.s["baume_mercier"]
        blob = text_of(self.payload)
        self.assertIn(f"{bm['completed_on']} 完成出售", blob)
        self.assertNotIn("预计 2026 年夏天完成", blob)
        self.assertNotIn("预计在 2026 年夏天完成", blob)
        self.assertIn(bm["completion_url"], [x["url"] for x in self.payload["source_links"]])


class CfrQuarterAndNextTest(unittest.TestCase):
    """Section two carries the note's conclusions that the company's own figures can
    draw; section three is the note's section 8 for the next quarter."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.s = load()
        cls.note = cls.s["_checks"]["note"]
        cls.payload = cfr.build_payload(cls.s)
        cls.by_section = {sec["id"]: sec for sec in cls.payload["sections"]}
        cls.exhibits = {ex["ref"]: ex for sec in cls.payload["sections"] for ex in sec["exhibits"]}

    def test_the_next_thresholds_are_the_notes_section_eight(self) -> None:
        block = self.s["next_kpi"]
        self.assertEqual([{k: e[k] for k in ("id", "metric", "direction", "threshold")} for e in block["quantified"]],
                         self.note["next_thresholds"])
        self.assertEqual(block["for_period"], display_period(cfr.next_quarter(self.s["quarters"][-1])))
        charts = self.by_section["next_quarter"]["exhibits"]
        overview = charts[0]
        self.assertEqual(overview["kind"], "diverging_bars")
        self.assertTrue(overview["title"].startswith(f"下季 {len(block['quantified'])} 条阈值："), overview["title"])
        # one line chart per threshold, in the note's order, titled with the threshold and the current value
        self.assertEqual(len(charts), 1 + len(block["quantified"]))
        table = next(t for t in self.payload["tables"] if "下季阈值的原始单位" in t["title"])
        for entry, chart, row in zip(block["quantified"], charts[1:], table["rows"]):
            self.assertEqual(chart["ref"], f"EX_NEXT_{entry['id'].upper()}")
            self.assertEqual(chart["title"], f"{entry['metric']}：下季阈值 {row[2].replace('-', '−')}，"
                                             f"当前 {row[3].replace('-', '−')}")
            self.assertEqual(set(chart["series"][1]["values"]), {entry["threshold"]})
            self.assertIn(entry["levels"], chart["note"])

    def test_what_section_eight_cannot_draw_is_listed_not_dropped(self) -> None:
        block = self.s["next_kpi"]
        description = self.by_section["next_quarter"]["description"]
        levels = next(t for t in self.payload["tables"] if "各档阈值与动作" in t["title"])
        for item in block.get("unquantified", []):
            self.assertIn(item["text"], description)
            self.assertTrue(any(row[1] == item["text"] and row[3].startswith("不画") for row in levels["rows"]),
                            item["text"])
        metrics = {e["id"]: e["metric"] for e in block["quantified"]}
        for key in block.get("revocation_ids", []):
            self.assertIn(metrics[key], description)

    def test_the_base_effect_is_recomputed_from_the_printed_rates(self) -> None:
        cer = self.s["quarterly_cer_pct"]
        lines = ["total", "jewellery_maisons", "specialist_watchmakers", "other"]
        two = [((1 + cer[k][-5] / 100) * (1 + cer[k][-1] / 100)) ** 0.5 * 100 - 100 for k in lines]
        chart = self.exhibits["EX_TWO_YEAR"]
        self.assertEqual(chart["groups"][0]["values"], [cer[k][-5] for k in lines])
        self.assertEqual(chart["groups"][1]["values"], [cer[k][-1] for k in lines])
        self.assertEqual(chart["groups"][2]["values"], [round(v, 2) for v in two])
        self.assertIn(f"两年叠加年化 {cfr.signed(two[0], 1)}", chart["title"])
        # the rate the next quarter needs to hold the two-year stack, on its own base
        keep = (1 + cer["total"][-5] / 100) * (1 + cer["total"][-1] / 100) / (1 + cer["total"][-4] / 100) * 100 - 100
        self.assertIn(f"下一季要约 {cfr.signed(keep, 1)}（D）", chart["note"])
        self.assertIn(f"下一季要约 {cfr.signed(keep, 1)} 才能", self.payload["brief"])

    def test_the_area_increment_adds_up_to_the_group(self) -> None:
        e = self.s["quarterly_eur_m"]
        chart = self.exhibits["EX_AREA_INCREMENT"]
        areas = ["jewellery_maisons", "specialist_watchmakers", "other"]
        values = [e[k][-1] - e[k][-5] for k in areas] + [e["total"][-1] - e["total"][-5]]
        self.assertEqual(chart["values"], values)
        self.assertEqual(sum(values[:-1]), values[-1])
        self.assertIn(f"（{values[0] / values[-1] * 100:.1f}%）", chart["title"])

    def test_the_quarter_names_what_it_cannot_draw_only_while_the_story_says_so(self) -> None:
        description = self.by_section["quarter_highlights"]["description"]
        self.assertIn("画不出来", description)
        cash = self.s.get("net_cash_quarter_end")
        if cash is not None:
            self.assertIn(f"季末净现金 €{cash['eur_bn']:.1f}B", description)
        bare = copy.deepcopy(self.s)
        del bare["quarter_story"]["undrawn"]
        after = next(sec for sec in cfr.build_payload(bare)["sections"] if sec["id"] == "quarter_highlights")
        self.assertNotIn("画不出来", after["description"])


def text_of(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def composed(payload: dict) -> str:
    """The prose the builder composes; the typed rules and verdicts sit in the tables."""
    return text_of({key: value for key, value in payload.items() if key != "tables"})


def with_every_block(source: dict) -> dict:
    """The series with every optional one-release block present and stamped for its
    own periods, synthesised (with placeholder words) where this quarter has none,
    so the tests below do not depend on which quarter the page is on."""
    st = copy.deepcopy(source)
    quarter = display_period(st["quarters"][-1])
    half = st["halves"][-1]
    st.setdefault("quarter_story", {"period": quarter})
    story = st["quarter_story"]
    story.setdefault("region_explanation", {"region": "middle_east_africa", "text": "测试用的地区解释"})
    story.setdefault("china", "测试用的中国说明。")
    story.setdefault("baume_mercier_brief", "测试用的简报句，下一次在 {next_month}。")
    story.setdefault("baume_mercier_note", "测试用的注释，下一次在 {next_date}。")
    st.setdefault("half_story", {"period": half, "margins": "测试用的毛利率说明。",
                                 "watchmakers": "测试用的腕表说明，{announced}。"})
    rates = st["quarterly_cer_pct"]["jewellery_maisons"]
    streak = 0
    for v in reversed(rates):
        if v is None or v < 10:
            break
        streak += 1
    st.setdefault("company_claims", {"period": quarter, "items": [
        {"key": "jewellery_streak", "quote": "a test consecutive quarter of double-digit growth",
         "count": streak, "line": "jewellery_maisons", "threshold_pct": 10}]})
    st.setdefault("net_cash_quarter_end", {"period": quarter, "date": st["latest"]["period_end"], "eur_bn": 9.0,
                                           "includes": [], "dividend_note": "测试用的股息说明。"})
    before = display_period(cfr.previous_quarter(st["quarters"][-1]))
    st.setdefault("followup_closure", {"period": quarter, "set_in": before, "labels": ["已验证", "仍未披露"],
                                       "items": [{"topic": "测试甲", "question": "测试问题甲", "verdict": "已验证",
                                                  "note_verdict": "已验证"},
                                                 {"topic": "测试乙", "question": "测试问题乙", "verdict": "仍未披露",
                                                  "note_verdict": "仍未披露", "structural": True}],
                                       "note": "测试用的闭环说明，{structural_count}条要等 {next_date}。"})
    jewellery_now = st["quarterly_cer_pct"]["jewellery_maisons"][-1]
    st.setdefault("prior_kpi_settlement", {
        "period": quarter, "set_in": before, "set_on": "2000-01-01",
        "quantified": [{"id": "cer_jewellery", "metric": "测试珠宝增速", "direction": "up",
                        "threshold": jewellery_now - 1.0, "unit": "pct", "rule": "测试规则",
                        "note_verdict": "测试判定", "disposal": "测试处置"}],
        "held": ["cer_jewellery"], "breached": [], "pending": []})
    return st


def roll_forward(source: dict) -> tuple[dict, str, bool]:
    """Append the next quarter with invented figures -- a shape test, nothing here is
    published. An interim or annual announcement brings a half-year with it; the
    first interim of a fiscal year brings a year with no annual behind it."""
    st = copy.deepcopy(source)
    q = st["quarters"]
    year, number = int(q[-1][:4]), int(q[-1][5])
    nxt = f"{year + (number == 4)}Q{number % 4 + 1}"
    y, n = int(nxt[:4]), int(nxt[5])
    fy = y if n == 1 else y + 1
    fiscal = f"FY{fy % 100:02d}Q{4 if n == 1 else n - 1}"
    f_number = int(fiscal[-1])
    kind = {1: "q1_trading_update", 2: "interim_results", 3: "q3_trading_update", 4: "annual_results"}[f_number]
    end = f"{y}-{QUARTER_END[str(n)]}"
    release = (datetime.date.fromisoformat(end) + datetime.timedelta(days=15)).isoformat()
    doc_id = f"test-{fiscal.lower()}"
    url = f"https://www.richemont.com/media/test/{doc_id}.pdf"
    st["documents"].append({"doc_id": doc_id, "kind": kind, "fiscal_year": fiscal[:4],
                            "release_date": release, "title": "test", "url": url})
    st["sources"].append({"label": f"Richemont {fiscal} 测试公告（{release}）", "url": url})
    q.append(nxt)
    st["fiscal_quarters"].append(fiscal)
    st["quarter_basis"].append("printed")
    st["quarter_sources"][nxt] = {"method": "printed", "value_doc": doc_id, "value_column": "current",
                                  "docs": [doc_id]}
    st["first_printed"][nxt] = {"doc": doc_id, "published": release, "column": "current", "lag_days": 15}
    for block in ("quarterly_eur_m", "quarterly_cer_pct", "quarterly_actual_pct"):
        for values in st[block].values():
            values.append(values[-4])
    adds_half = f_number in (2, 4)
    if adds_half:
        half = f"{fiscal[:4]}H{1 if f_number == 2 else 2}"
        st["halves"].append(half)
        st["half_basis"].append("printed" if f_number == 2 else "derived")
        for block in ("half_eur_m", "half_segment_sales_eur_m", "half_segment_result_eur_m"):
            for values in st[block].values():
                values.append(values[-2])
        previous = st["balance"][-2]
        st["balance"].append({"date": end, "doc": doc_id, "net_cash_position": previous["net_cash_position"],
                              "inventories": previous["inventories"]})
        if f_number == 2:
            st["half_sources"][fiscal[:4]] = {"mode": "own_year", "why": "test", "year_doc": None, "h1_doc": doc_id}
        else:
            st["half_sources"][fiscal[:4]]["year_doc"] = doc_id
        st.pop("half_story", None)
    stamp = display_period(nxt)
    st["latest"].update(disclosed_period_label=stamp, period_end=end, release_date=release)
    if "next_kpi" in st:
        # the next note would set new thresholds; the shape test keeps these, re-stamped
        st["next_kpi"].update(period=stamp, for_period=display_period(cfr.next_quarter(nxt)))
    if "net_cash_quarter_end" in st:
        st["net_cash_quarter_end"].update(period=stamp, date=end)
    # what the note settles is the next note's to write; a roll without it leaves section one
    # with the company's own ranges only
    for key in ("company_claims", "quarter_story", "followup_closure", "prior_kpi_settlement"):
        st.pop(key, None)
    return st, fiscal, adds_half


class CfrRollTest(unittest.TestCase):
    """What a roll has to change in `series/cfr.json`, and what the page does when it does not.

    Six blocks describe one release: the thresholds, the previous note's thresholds,
    the company's own streak claim, the quarter-end net cash and the quarter's story
    are stamped with the quarter; the half's story with the half. A block stamped for
    another period stops the build; an absent optional one takes its sentences with it.
    Every case below first puts the series into the state it tests, so the file holds
    whichever quarter the series is on.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = load()
        cls.full = with_every_block(cls.source)
        cls.payload = cfr.build_payload(cls.full)
        cls.blob = text_of(cls.payload)

    def test_a_block_stamped_with_another_period_stops_the_build(self) -> None:
        for key, stale_period in (("next_kpi", "Q1 1999"), ("followup_closure", "Q1 1999"),
                                  ("prior_kpi_settlement", "Q1 1999"),
                                  ("company_claims", "Q1 1999"), ("net_cash_quarter_end", "Q1 1999"),
                                  ("quarter_story", "Q1 1999"), ("half_story", "FY99H1")):
            stale = copy.deepcopy(self.full)
            stale[key]["period"] = stale_period
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    cfr.build_payload(stale)
        # what the previous note set is settled only in the quarter after it
        for key in ("followup_closure", "prior_kpi_settlement"):
            skipped = copy.deepcopy(self.full)
            skipped[key]["set_in"] = "Q1 1999"
            with self.subTest(set_in=key):
                with self.assertRaisesRegex(ValueError, "settles what was set in"):
                    cfr.build_payload(skipped)
        # the thresholds are set for the quarter after the page's, and nothing else
        later = copy.deepcopy(self.full)
        later["next_kpi"]["for_period"] = "Q1 1999"
        with self.assertRaisesRegex(ValueError, "is set for"):
            cfr.build_payload(later)
        bare = copy.deepcopy(self.full)
        del bare["next_kpi"]
        with self.assertRaisesRegex(ValueError, "`next_kpi` is missing"):
            cfr.build_payload(bare)
        unknown = copy.deepcopy(self.full)
        unknown["next_kpi"]["quantified"][0]["id"] = "not_a_measure"
        with self.assertRaisesRegex(ValueError, "does not know how to measure"):
            cfr.build_payload(unknown)
        typed = copy.deepcopy(self.full)
        typed["next_kpi"]["quantified"][0]["current"] = 20.0
        with self.assertRaisesRegex(ValueError, "computed from the series"):
            cfr.build_payload(typed)
        dated = copy.deepcopy(self.full)
        dated["net_cash_quarter_end"]["date"] = "1999-03-31"
        with self.assertRaisesRegex(ValueError, "net_cash_quarter_end"):
            cfr.build_payload(dated)
        uncashed = copy.deepcopy(self.full)
        del uncashed["net_cash_quarter_end"]
        ends_half = uncashed["balance"][-1]["date"] == uncashed["latest"]["period_end"]
        if any(t["id"] == "net_cash" for t in uncashed["next_kpi"]["quantified"]) and not ends_half:
            with self.assertRaisesRegex(ValueError, "net_cash_quarter_end"):
                cfr.build_payload(uncashed)
        orphan = copy.deepcopy(self.full)
        doc = orphan["first_printed"][orphan["quarters"][-1]]["doc"]
        url = next(d["url"] for d in orphan["documents"] if d["doc_id"] == doc)
        orphan["sources"] = [x for x in orphan["sources"] if x["url"] != url]
        with self.assertRaisesRegex(ValueError, "sources"):
            cfr.build_payload(orphan)
        typo = copy.deepcopy(self.full)
        typo["quarter_story"]["china"] = "要看 {next_datee} 的公告。"
        with self.assertRaisesRegex(ValueError, "does not fill"):
            cfr.build_payload(typo)
        # the rollback drill put a sales-only update here and the page promised
        # profit on a date that has none
        sales_only = copy.deepcopy(self.full)
        sales_only["latest"]["next_release"] = {"label": "FY27 Q1 sales", "date": "2026-07-15"}
        with self.assertRaisesRegex(ValueError, "next results announcement"):
            cfr.build_payload(sales_only)

    def test_a_half_end_quarter_reads_net_cash_off_the_balance_sheet(self) -> None:
        """A quarter that ends a half is published with the half's balance sheet;
        its net cash is that figure, not a trading update's (the rollback drill
        printed 「季度公告另给过一个季末净现金」 for the annual results)."""
        half_end = copy.deepcopy(self.full)
        del half_end["net_cash_quarter_end"]
        balance = half_end["balance"][-1]
        half_end["latest"]["period_end"] = balance["date"]
        payload = cfr.build_payload(half_end)
        chart = next(ex for section in payload["sections"] for ex in section["exhibits"]
                     if ex["ref"] == "EX_HEADROOM")
        cash = next(ex for section in payload["sections"] for ex in section["exhibits"] if ex["ref"] == "EX_CASH")
        if any(t["id"] == "net_cash" for t in half_end["next_kpi"]["quantified"]):
            self.assertIn(f"净现金取 {balance['date']} 的半年末值", chart["note"])
        self.assertNotIn("季度公告另给过一个季末净现金", cash["note"])

    def test_a_period_without_a_story_leaves_it_out(self) -> None:
        full = self.full
        story, half = full["quarter_story"], full["half_story"]
        region = story["region_explanation"]
        cases = {
            "quarter_story": (region["text"], story["china"].split("。")[0],
                              story["baume_mercier_note"].split("，")[0]),
            "half_story": (half["margins"].split("。")[0], half["watchmakers"].split("{")[0]),
            "company_claims": ("是公司在本季公告里的原话", "公司说是连续第"),
            "followup_closure": ("条待验证问题", "闭环了几条"),
            "prior_kpi_settlement": ("条量化阈值：本季能结算", "上季阈值"),
        }
        for key, texts in cases.items():
            bare = copy.deepcopy(full)
            del bare[key]
            payload = cfr.build_payload(bare)
            after = text_of(payload)
            for text in texts:
                with self.subTest(block=key, text=text):
                    self.assertIn(text, self.blob)
                    self.assertNotIn(text, after)
            numbers = [ex["n"] for section in payload["sections"] for ex in section["exhibits"]]
            self.assertEqual(numbers, list(range(1, 1 + len(numbers))))
            tables = [t["n"] for t in payload["tables"]]
            self.assertEqual(tables, list(range(len(numbers) + 1, len(numbers) + 1 + len(tables))))
        # the quarter-end net cash goes with its sentence once no threshold needs it
        bare = copy.deepcopy(full)
        del bare["net_cash_quarter_end"]
        bare["next_kpi"]["quantified"] = [t for t in bare["next_kpi"]["quantified"] if t["id"] != "net_cash"]
        self.assertIn("季度公告另给过一个季末净现金", self.blob)
        self.assertNotIn("季度公告另给过一个季末净现金", text_of(cfr.build_payload(bare)))

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        """Make each "first / all / only / lowest" claim true in the data, then break
        it once: the sentence that made it must go."""
        def jewellery_margin(d, i, pct):
            sales = d["half_segment_sales_eur_m"]["jewellery_maisons"][i]
            d["half_segment_result_eur_m"]["jewellery_maisons"][i] = round(sales * pct / 100)

        def after_halves(d):
            return cfr.half_view(d)["jewel_after"]

        def first_break(d):
            for i in after_halves(d)[:-1]:
                jewellery_margin(d, i, 32)
            jewellery_margin(d, len(d["halves"]) - 1, 28)

        def earlier_break(d):
            jewellery_margin(d, after_halves(d)[0], 28)

        def claim_matches(d):
            d["company_claims"]["items"][0]["count"] = cfr.quarter_view(d)["streak"]

        def claim_overstates(d):
            d["company_claims"]["items"][0]["count"] = cfr.quarter_view(d)["streak"] + 1

        def accelerating(d):
            cj = d["quarterly_cer_pct"]["jewellery_maisons"]
            cj[-2], cj[-1] = 12, 20

        def decelerating(d):
            accelerating(d)
            d["quarterly_cer_pct"]["jewellery_maisons"][-1] = 11

        def jewellery_carries(d, halves=2):
            op = d["half_eur_m"]["operating_profit"]
            for i in range(len(op) - halves, len(op)):
                d["half_segment_result_eur_m"]["jewellery_maisons"][i] = op[i] + 100

        def jewellery_no_longer(d):
            jewellery_carries(d)
            op = d["half_eur_m"]["operating_profit"]
            d["half_segment_result_eur_m"]["jewellery_maisons"][-1] = op[-1] - 100

        def full_years(d):
            h = d["halves"]
            return [(i, i + 1) for i in range(len(h) - 1) if h[i].endswith("H1") and h[i + 1] == h[i][:4] + "H2"]

        def h2_lower(d):
            for a, b in full_years(d):
                jewellery_margin(d, a, 33)
                jewellery_margin(d, b, 30)

        def h2_higher(d):
            for a, b in full_years(d):
                jewellery_margin(d, a, 30)
                jewellery_margin(d, b, 33)

        def one_trap(d):
            trap = next(x for x in d["first_print_derivations"] if x["derived_total"] != x["printed_total"])
            d["derived_checks"] = [c for c in d["derived_checks"]
                                   if c["derived"] == c["printed"] or c["quarter"] == trap["quarter"]]

        def second_trap(d):
            one_trap(d)
            other = next(c for c in d["derived_checks"] if c["derived"] == c["printed"])
            d["derived_checks"].append(dict(other, printed=other["printed"] + 1))

        def japan_fx(d):
            last = len(d["quarters"]) - 1
            for k in REGIONS:
                d["quarterly_actual_pct"][k][last] = d["quarterly_cer_pct"][k][last] - (16 if k == "japan" else 1)

        def no_fx(d):
            last = len(d["quarters"]) - 1
            for k in REGIONS:
                d["quarterly_actual_pct"][k][last] = d["quarterly_cer_pct"][k][last]

        def mea_falls(d):
            cer = d["quarterly_cer_pct"]["middle_east_africa"]
            cer[-1] = cer[-5] - 10

        def mea_rises(d):
            cer = d["quarterly_cer_pct"]["middle_east_africa"]
            cer[-1] = cer[-5] + 10

        def mea_smallest_gain(d):
            e = d["quarterly_eur_m"]
            for k in REGIONS:
                e[k][-1] = e[k][-5] + (5 if k == "middle_east_africa" else 100)

        def mea_loses(d):
            mea_smallest_gain(d)
            e = d["quarterly_eur_m"]["middle_east_africa"]
            e[-1] = e[-5] - 50

        def ap_peak_moves(d):
            e = d["quarterly_eur_m"]
            e["asia_pacific"][-1] = e["total"][-1] * 0.9

        def other_document(d):
            ya = d["quarters"][-5]
            d["quarter_sources"][ya] = dict(d["quarter_sources"][ya], value_doc=d["documents"][0]["doc_id"])

        def lowest_ever(d):
            jewellery_margin(d, len(d["halves"]) - 1, 5)

        def gross_margin_breaks_after_ynap(d):
            # the latest half's gross margin falls under the note's line on the continuing basis
            h = d["half_eur_m"]
            h["gross_profit"][-1] = round(h["sales"][-1] * 0.55)

        noop = lambda d: None
        trap = next(x for x in self.full["first_print_derivations"]
                    if x["derived_total"] != x["printed_total"])["quarter"]
        cases = {
            "first break of the range": (first_break, earlier_break,
                                         ("在这句话之后第一次被跌破", "是这句话之后第一次跌破下沿")),
            "the company's count holds": (claim_matches, claim_overstates, ("本页逐季核过成立", "本页逐季核过：成立")),
            "jewellery accelerating": (accelerating, decelerating, ("销售在加速",)),
            "jewellery carries the group": (jewellery_carries, jewellery_no_longer,
                                            ("集团的利润越来越等于珠宝的利润", "连续如此")),
            "second halves lower": (h2_lower, h2_higher, ("下半年系统性低于上半年",)),
            "one quarter disagrees": (one_trap, second_trap, (f"全部在 {trap}",)),
            "the yen": (japan_fx, no_fx, ("日本那一格要和实际汇率一起读", "日本那一根比恒定汇率口径小得多")),
            "Middle East falls": (mea_falls, mea_rises, ("中东与非洲从上年同季的",)),
            "smallest gain": (mea_smallest_gain, mea_loses, ("中东与非洲只有 €",)),
            "Asia Pacific peak in 2020Q2": (noop, ap_peak_moves, ("是疫情那一季",)),
            "both quarters from one document": (noop, other_document, ("取自同一份公告的本期列与上年同期列",)),
            "lowest since an earlier half": (noop, lowest_ever, ("以来最低",)),
            "every half under the margin line carries YNAP": (noop, gross_margin_breaks_after_ynap,
                                                              ("全部在两道断点之间含 YNAP 的那一段",)),
        }
        for name, (make_true, make_false, claims) in cases.items():
            held = copy.deepcopy(self.full)
            # The settlement block states which of last note's lines held; a case that
            # moves the jewellery rate across one makes that statement false and stops
            # the build, which is `test_the_held_list_has_to_be_what_the_numbers_say`'s
            # subject, not this one's.
            held.pop("prior_kpi_settlement")
            make_true(held)
            before = composed(cfr.build_payload(held))
            broken = copy.deepcopy(held)
            make_false(broken)
            after = composed(cfr.build_payload(broken))
            for claim in claims:
                with self.subTest(case=name, claim=claim):
                    self.assertIn(claim, before)
                    if name == "Middle East falls":
                        self.assertIn("掉到", before)
                        self.assertNotIn("掉到", after)
                    else:
                        self.assertNotIn(claim, after)

    def test_the_next_quarter_rolls_without_touching_the_code(self) -> None:
        rolled, fiscal, adds_half = roll_forward(self.full)
        payload = cfr.build_payload(rolled)
        stamp = display_period(rolled["quarters"][-1])
        self.assertIn(f"{stamp}（公司 {fiscal[:4]} 第{cn_ordinal(int(fiscal[-1]))}季）", payload["title"])
        self.assertEqual(payload["latest"]["disclosed_period_label"], stamp)
        half = rolled["halves"][-1]
        self.assertIn(cfr.half_name(half), payload["title"])
        self.assertIn(f"利润截至 {cfr.half_end_date(half)} 半年", payload["subtitle"])
        self.assertEqual(payload["latest"]["full_financial_period_label"], f"H{half[-1]} FY{half[2:4]}")
        source_table = next(t for t in payload["tables"] if "半年数据各取自哪一对文件" in t["title"])
        if adds_half and half.endswith("H1"):
            self.assertEqual(source_table["rows"][-1][2], "—（全年尚未公布）")
        # nothing the quarter's own story said survives it
        for text in ("是公司在本季公告里的原话", "公司说是连续第", self.full["quarter_story"]["china"][:20]):
            self.assertNotIn(text, text_of(payload))

    def test_the_first_interim_of_a_year_rolls_too(self) -> None:
        """Roll forward until an interim announcement adds a half with no annual
        behind it, whatever quarter the series is on now."""
        st = self.full
        for _ in range(4):
            st, fiscal, adds_half = roll_forward(st)
            if fiscal.endswith("Q2"):
                break
        payload = cfr.build_payload(st)
        self.assertTrue(st["halves"][-1].endswith("H1"))
        self.assertIsNone(st["half_sources"][st["halves"][-1][:4]]["year_doc"])
        self.assertIn(cfr.half_name(st["halves"][-1]), payload["headline"])
        # a first half is printed, not derived: nothing on the page may call it D
        self.assertNotIn("（本页减出）", payload["headline"])
        jewel = next(ex for section in payload["sections"] for ex in section["exhibits"]
                     if ex["ref"] == "EX_JEWEL_BAND")
        self.assertNotIn("% D", jewel["title"])


class CfrChecksTest(unittest.TestCase):
    """The page's quarter against a record keyed separately from the series.

    `_checks` is typed once per quarter from the announcement that first prints the
    quarter -- its sales table (both columns, both growth rates), its prose and its
    corporate calendar -- with the place each figure was read. The builder never
    reads it (asserted in `test_data_only_roll`). Richemont prints its growth rates
    as whole percentages and the retail share of sales as a whole percentage, so the
    page's arithmetic has to round to those.

    `_checks["note"]` is the same kind of second reading, of the owner's two notes
    rather than the announcement: section 0's verdict tally and both notes' section 8
    thresholds, re-keyed with every roll like the rest of `_checks` (see `CfrSettledTest`).
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.s = load()
        cls.c = cls.s["_checks"]
        cls.payload = cfr.build_payload(cls.s)
        cls.exhibits = {ex["ref"]: ex for section in cls.payload["sections"] for ex in section["exhibits"]}

    def test_the_page_names_the_checked_quarter(self) -> None:
        c = self.c
        fy, number = c["fiscal_quarter"][:4], int(c["fiscal_quarter"][-1])
        self.assertIn(f"{c['period']}（公司 {fy} 第{cn_ordinal(number)}季）", self.payload["title"])
        self.assertIn(f"销售截至 {c['period_end']}", self.payload["subtitle"])
        self.assertIn(f"发布 {c['release_date']}", self.payload["subtitle"])
        self.assertEqual(self.s["fiscal_quarters"][-1], c["fiscal_quarter"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        c, s = self.c, self.s
        e, cer, act = s["quarterly_eur_m"], s["quarterly_cer_pct"], s["quarterly_actual_pct"]
        self.assertEqual(e["total"][-1], c["sales_eur_m"])
        self.assertEqual(e["total"][-5], c["prior_year_sales_eur_m"])
        self.assertEqual((cer["total"][-1], act["total"][-1]), (c["sales_cer_pct"], c["sales_actual_pct"]))
        for key in REGIONS:
            with self.subTest(region=key):
                self.assertEqual(e[key][-1], c["regions_eur_m"][key])
                self.assertEqual(cer[key][-1], c["regions_cer_pct"][key])
                self.assertEqual(act[key][-1], c["regions_actual_pct"][key])
        for key in CHANNELS:
            with self.subTest(channel=key):
                self.assertEqual(e[key][-1], c["channels_eur_m"][key])
                self.assertEqual(cer[key][-1], c["channels_cer_pct"][key])
        for key, value in c["areas_eur_m"].items():
            with self.subTest(area=key):
                self.assertEqual(e[key][-1], value)
                self.assertEqual(cer[key][-1], c["areas_cer_pct"][key])
        if "jewellery_streak_count" in c:
            claim = next(x for x in s["company_claims"]["items"] if x["key"] == "jewellery_streak")
            self.assertEqual(claim["count"], c["jewellery_streak_count"])
            self.assertIn(c["jewellery_streak_quote"], claim["quote"])
        if "net_cash_eur_bn" in c:
            block = s["net_cash_quarter_end"]
            self.assertEqual(block["eur_bn"], c["net_cash_eur_bn"])
            self.assertEqual(block["prior_year_eur_bn"], c["net_cash_prior_year_eur_bn"])
        self.assertEqual(s["latest"]["next_release"]["date"], c["next_results_date"])

    def test_the_rounding_the_page_uses_is_the_companys(self) -> None:
        c, e = self.c, self.s["quarterly_eur_m"]
        self.assertEqual(round(e["retail"][-1] / e["total"][-1] * 100), c["retail_share_pct_printed"])
        for parts in (REGIONS, CHANNELS, list(c["areas_eur_m"])):
            self.assertEqual(sum(e[k][-1] for k in parts), c["sales_eur_m"])

    def test_the_page_prints_the_checked_figures(self) -> None:
        c = self.c
        headline = self.payload["headline"]
        self.assertIn(f"本季集团销售 €{c['sales_eur_m']:,}M，恒定汇率 +{c['sales_cer_pct']}%、"
                      f"实际汇率 +{c['sales_actual_pct']}%", headline)
        self.assertIn(f"珠宝 €{c['areas_eur_m']['jewellery_maisons']:,}M、"
                      f"+{c['areas_cer_pct']['jewellery_maisons']}%", headline)
        self.assertIn(f"下一次利润数据在 {c['next_results_date']}", headline)
        increment = self.exhibits["EX_INCREMENT"]
        self.assertIn(f"€{c['sales_eur_m'] - c['prior_year_sales_eur_m']:,}M", increment["title"])
        region = self.exhibits["EX_REGION_NOW"]
        self.assertEqual(region["groups"][0]["values"],
                         [c["regions_cer_pct"][k] for k in REGIONS] + [c["sales_cer_pct"]])
        if "net_cash_eur_bn" in c:
            self.assertIn(f"€{c['net_cash_eur_bn']:.1f}B", self.exhibits["EX_CASH"]["note"])


if __name__ == "__main__":
    unittest.main()
