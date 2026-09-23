"""What the ASML page has to keep true.

The page's claims rest on three kinds of arithmetic, and each is recomputed here
from `series/asml.json` by a different route than `build/asml.py` takes -- nothing
below calls the builder's settlement, reconciliation or ratio helpers:

* **guidance settlement** -- every quarter's guidance, taken from the release
  before it, against the figure reported for it. The titles print counts
  (「给了指引的 41 季里 25 季高于上限」); those counts are recounted here.
* **slide percentages against euro figures** -- the quarterly technology and
  end-use mix exists only as whole-number percentages on slide images, read by
  hand. Multiplied back into each quarter's net system sales and summed, they
  have to land on the euro figures the 20-F prints, within what whole-number
  rounding can explain. That is two documents that do not derive from each
  other, and it is the only check on a reading taken from a picture.
* **universal sentences** -- 「没有一年下半年少于上半年」「每一年的第四季度都占到
  全年一半以上」「四十季里最高」. Recomputing numbers cannot see a universal
  statement turn false, so `AsmlRollTest` breaks each one in the data and asserts
  the wording goes.

The page is rolled by editing `series/asml.json` alone (CLAUDE.md §9);
`AsmlRollTest.test_the_next_quarter_rolls_without_touching_the_code` appends a
synthetic quarter to prove it.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import asml  # noqa: E402
from build.all import ENTRIES  # noqa: E402
from build.board import display_period, round_half_up  # noqa: E402


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    return json.loads(text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0])


def text_of(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def exhibits_of(payload: dict) -> list[dict]:
    return [ex for sec in payload["sections"] for ex in sec["exhibits"]]


def by_ref(payload: dict) -> dict:
    return {ex["ref"]: ex for ex in exhibits_of(payload) if "ref" in ex}


VALID_COLORS = {"NAVY", "BLUE", "MBLUE", "GRAY", "GREEN", "RED", "GOLD", "WHITE",
                "GRID", "AXIS", "INK"}
VALID_FORMATS = {"f1", "f0", "f0c", "int", "pct0", "pct1", "pct0z", "pp0", "pp1", "x0",
                 "usd0", "usd1", "usd2", "f2", "f3", "pct2", "usd3", "usd4"}
LITERAL_SLOTS = ("headline", "title", "subtitle", "tracker")
# Bar kinds whose y floor is pinned at zero (assets/charts.js), so a negative
# value is drawn off the canvas rather than below the axis.
ZERO_FLOORED_KINDS = {"bars_labeled", "gs_bar", "stacked_dual"}


def guided_rows(s: dict, metric: str, actual_key: str) -> list[tuple[str, float, float, float]]:
    """(quarter, low, high, actual) for every quarter that was guided -- read
    straight from the series, one release before the quarter it guides."""
    q = s["quarterly"]
    P = q["periods"]
    rows = []
    for g in s["guidance"]:
        block = g.get(metric)
        if block is None or g["guided_quarter"] not in P:
            continue
        i = P.index(g["guided_quarter"])
        rows.append((g["guided_quarter"], block["low"], block["high"], q[actual_key][i]))
    return rows


def tally(rows) -> tuple[int, int, int]:
    above = sum(1 for _, lo, hi, a in rows if a > hi)
    below = sum(1 for _, lo, hi, a in rows if a < lo)
    return above, len(rows) - above - below, below


def h2_over_h1(q: dict, year: int) -> float:
    P, t = q["periods"], q["total_net_sales"]
    h1 = t[P.index(f"{year}Q1")] + t[P.index(f"{year}Q2")]
    h2 = t[P.index(f"{year}Q3")] + t[P.index(f"{year}Q4")]
    return (h2 / h1 - 1) * 100


class AsmlDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.st = json.loads(asml.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = asml.build_payload(cls.st)
        cls.exhibits = exhibits_of(cls.payload)
        cls.ref = by_ref(cls.payload)
        cls.q = cls.st["quarterly"]
        cls.P = cls.q["periods"]

    # ── the statements close ─────────────────────────────────────────────────
    def test_every_quarter_closes_line_by_line(self) -> None:
        q = self.q
        for i, p in enumerate(self.P):
            with self.subTest(quarter=p):
                self.assertAlmostEqual(q["net_system_sales"][i] + q["ibm_sales"][i],
                                       q["total_net_sales"][i], delta=0.15)
                self.assertAlmostEqual(q["total_net_sales"][i] - q["cost_of_sales"][i],
                                       q["gross_profit"][i], delta=0.15)
                # the printed ratio is the company's own, to one decimal
                self.assertAlmostEqual(q["gross_profit"][i] / q["total_net_sales"][i] * 100,
                                       q["gross_margin_printed_pct"][i], delta=0.051)

    def test_the_quarters_add_to_the_20f_year_except_where_the_page_says_they_do_not(self) -> None:
        """2018 onward the four quarters are the 20-F's year. 2017 is not, and that
        gap -- ASC 606 applied to the year but never to its quarters -- is what
        the page's break line and its note are about. If a later quarterly exhibit
        ever restated 2017, the gap would close and this would go red."""
        q, am = self.q, self.st["annual_mix"]
        for year in range(2018, int(self.P[-1][:4])):
            with self.subTest(year=year):
                total = sum(q["total_net_sales"][self.P.index(f"{year}Q{n}")] for n in range(1, 5))
                self.assertAlmostEqual(total, am[str(year)]["total_net_sales"], delta=0.25)
        q2017 = sum(q["total_net_sales"][self.P.index(f"2017Q{n}")] for n in range(1, 5))
        self.assertGreater(abs(q2017 - am["2017"]["total_net_sales"]), 50)
        self.assertIn(asml.eur_m(q2017), text_of(self.payload["notes"]))
        self.assertIn(asml.eur_m(am["2017"]["total_net_sales"]), text_of(self.payload["notes"]))

    def test_the_asc606_break_sits_on_2018q1(self) -> None:
        for ref in ("EX_MIX", "EX_MARGIN"):
            with self.subTest(ref=ref):
                ex = self.ref[ref]
                self.assertEqual(ex["xlabels"][ex["break_at"]], "2018Q1")

    def test_every_restated_cell_is_one_of_the_documented_changes(self) -> None:
        """The page takes each quarter's last printed basis. Every cell where that
        differs from the first print is one of three documented changes: the 2017
        metrology reclass of the 2016 quarters, the ASU 2016-15 cash-flow reclass
        of 2017Q4-2018Q3, or a re-rounding of at most 0.1."""
        explained = []
        for d in self.q["first_print_diffs"]:
            metrology = d["quarter"].startswith("2016") and d["line"] in (
                "net_system_sales", "net_service_field_option_sales")
            cash_flow = (d["quarter"] in ("2017Q4", "2018Q1", "2018Q2", "2018Q3")
                         and d["restated_in"] == "2019-01-23")
            rounding = abs(d["restated"] - d["first_print"]) <= 0.1 + 1e-9
            explained.append(metrology or cash_flow or rounding)
        self.assertTrue(all(explained), [d for d, ok in zip(self.q["first_print_diffs"], explained) if not ok])
        table = next(t for t in self.payload["tables"] if "首次印出之后" in t["title"])
        self.assertEqual(len(table["rows"]),
                         sum(1 for d in self.q["first_print_diffs"] if d["quarter"] in self.P))

    # ── guidance settlement, recounted ───────────────────────────────────────
    def test_the_sales_settlement_is_recounted(self) -> None:
        rows = guided_rows(self.st, "sales", "total_net_sales")
        above, inside, below = tally(rows)
        title = self.ref["EX_SALESDEV"]["title"]
        self.assertIn(f"给了指引的 {len(rows)} 季里 {above} 季高于上限、{inside} 季落在区间内、{below} 季低于下限",
                      title)
        values = self.ref["EX_SALESDEV"]["groups"][0]["values"]
        self.assertEqual(sum(1 for v in values if v is not None), len(rows))
        # the withdrawn quarter keeps its slot on the axis, empty
        withdrawn = [g["guided_quarter"] for g in self.st["guidance"] if g["withdrawn"]
                     and g["guided_quarter"] in self.P]
        self.assertEqual(withdrawn, ["2020Q2"])
        self.assertIsNone(values[self.P.index("2020Q2")])

    def test_the_gross_margin_settlement_is_recounted(self) -> None:
        rows = guided_rows(self.st, "gross_margin", "gross_margin_printed_pct")
        above, inside, below = tally(rows)
        self.assertIn(f"{len(rows)} 季里 {above} 季高于上限、{inside} 季落在区间内、{below} 季低于下限",
                      self.ref["EX_GMDEV"]["title"])
        misses = [p for p, lo, hi, a in rows if a < lo]
        for p in misses:
            self.assertIn(p, self.ref["EX_GMDEV"]["note"])

    def test_the_installed_base_settlement_is_recounted(self) -> None:
        rows = guided_rows(self.st, "ibm", "ibm_sales")
        above, inside, below = tally(rows)
        title = self.ref["EX_IBMDEV"]["title"]
        self.assertIn(f"{len(rows)} 季里 {above} 季高于", title)
        self.assertIn(f"{below} 季低于", title)
        self.assertNotRegex(title, r"(?<!\d)0 季")
        self.assertIn(f"自 {rows[0][0]} 起", title)
        # every installed-base guide is a single figure
        self.assertTrue(all(lo == hi for _, lo, hi, _ in rows))

    def test_the_latest_quarter_against_its_guidance(self) -> None:
        rows = {p: (lo, hi, a) for p, lo, hi, a in guided_rows(self.st, "sales", "total_net_sales")}
        lo, hi, actual = rows[self.P[-1]]
        mid = (lo + hi) / 2
        dev = (actual / mid - 1) * 100
        note = self.ref["EX_SALESDEV"]["note"]
        self.assertIn(f"本季 {asml.signed(dev)}", note)
        # "the largest since P": the last earlier quarter in the range era that reached it
        earlier = [p for p, (l2, h2, a2) in rows.items()
                   if p < self.P[-1] and p >= "2020Q1" and (a2 / ((l2 + h2) / 2) - 1) * 100 >= dev]
        self.assertIn(f"是 {max(earlier)} 以来偏离最大的一次", note)

    def test_the_full_year_path_is_every_release_that_guided_the_year(self) -> None:
        year = int(self.P[-1][:4])
        path = [(g["filed"], it) for g in self.st["guidance"] for it in g["full_year"]
                if it["year"] == year and it["metric"] == "total_net_sales" and it["unit"] == "eur_m"]
        ex = self.ref["EX_FYPATH"]
        self.assertEqual(ex["xlabels"], [f"{filed} 发布" for filed, _ in path])
        self.assertEqual(ex["groups"][0]["values"], [it["low"] for _, it in path])
        self.assertEqual(ex["groups"][1]["values"], [it["high"] for _, it in path])
        shift = ((path[-1][1]["low"] + path[-1][1]["high"]) - (path[0][1]["low"] + path[0][1]["high"])) / 2
        self.assertIn(f"中值累计上移 €{shift / 1000:.1f}B", ex["title"])

    def test_guidance_ranges_print_at_the_companys_own_precision(self) -> None:
        """The Q2 guide was "€8.4 billion and €9.0 billion"; the page must not
        print "€8.4–9B". The full-year one was "€43 billion and €45 billion"."""
        self.assertIn("€8.4–9.0B", self.payload["headline"])
        self.assertIn("€43–45B", self.payload["headline"])
        self.assertNotRegex(text_of(self.payload), r"€\d+\.\d–\d+B")
        # the next quarter's guide is whole billions written with a decimal
        # ("€11.0 billion and €12.0 billion"): only the company's sentence can
        # say it wants the ".0", arithmetic on the figures cannot
        ahead = [g for g in self.st["guidance"] if g["guided_quarter"] not in self.P and g.get("sales")][-1]
        lo, hi = ahead["sales"]["low"], ahead["sales"]["high"]
        decimals = 1 if re.search(r"\d\.\d+\s*billion", ahead["sales"]["verbatim"]) else 0
        self.assertIn(f"对 {ahead['guided_quarter']} 的指引是总净销售 €{lo / 1000:.{decimals}f}–{hi / 1000:.{decimals}f}B",
                      self.payload["headline"])

    # ── the second half against the first ────────────────────────────────────
    def test_the_second_half_ratio_is_recomputed(self) -> None:
        q, year = self.q, int(self.P[-1][:4])
        years = [y for y in range(2016, year) if f"{y}Q4" in self.P]
        ratios = {y: h2_over_h1(q, y) for y in years}
        h1 = q["total_net_sales"][self.P.index(f"{year}Q1")] + q["total_net_sales"][self.P.index(f"{year}Q2")]
        last = [it for g in self.st["guidance"] for it in g["full_year"]
                if it["year"] == year and it["metric"] == "total_net_sales" and it["unit"] == "eur_m"][-1]
        implied = (((last["low"] + last["high"]) / 2 - h1) / h1 - 1) * 100
        ex = self.ref["EX_H2H1"]
        self.assertEqual(ex["xlabels"], [str(y) for y in years] + [f"{year} 指引隐含"])
        self.assertIn(f"多 {implied:.1f}%", ex["title"])
        higher = [y for y in years if ratios[y] > implied]
        self.assertIn(f"有{asml.cn_count(len(higher))}年比这更高", ex["title"])
        for y in higher:
            self.assertIn(f"{y} 年 {asml.signed(ratios[y])}", ex["title"])
        self.assertIn(asml.eur_m(h1), ex["note"])

    # ── slide percentages against the 20-F's euros ───────────────────────────
    def _reconcile(self, pct_key: str, table: dict, tech: str | None, quarters_of) -> list[tuple]:
        q, d = self.q, self.st["deck_mix"]
        out = []
        for y in sorted(table):
            qs = quarters_of(int(y))
            if not all(p in self.P and d[pct_key][self.P.index(p)] is not None for p in qs):
                continue
            euro = (table[y]["technology_eur_m"].get(tech) if tech else
                    (table[y].get("end_use_eur_m") or {}).get("Memory"))
            if euro is None:
                continue
            implied = sum(d[pct_key][self.P.index(p)] * q["net_system_sales"][self.P.index(p)] / 100 for p in qs)
            allowance = sum(0.005 * q["net_system_sales"][self.P.index(p)] for p in qs)
            out.append((y, implied, euro, allowance))
        return out

    def test_the_slide_percentages_land_on_the_20f_euros(self) -> None:
        years = self._reconcile("euv_pct", self.st["annual_mix"], "EUV",
                                lambda y: [f"{y}Q{n}" for n in range(1, 5)])
        self.assertGreaterEqual(len(years), 10)
        for y, implied, euro, allowance in years:
            with self.subTest(year=y):
                self.assertLessEqual(abs(implied - euro), allowance)
        # Memory: the slides split Logic/Memory from 2018; before that the three-way
        # split's Memory slice is the same slice, but the 20-F year is the ASC 606
        # restatement, so only 2018 on is on one basis at both ends.
        d = self.st["deck_mix"]
        memory = [r for r in self._reconcile("memory_pct", self.st["annual_mix"], None,
                                             lambda y: [f"{y}Q{n}" for n in range(1, 5)])
                  if int(r[0]) >= 2018]
        self.assertGreaterEqual(len(memory), 8)
        for y, implied, euro, allowance in memory:
            with self.subTest(year=y, line="memory"):
                self.assertLessEqual(abs(implied - euro), allowance)
        self.assertTrue(all(t == "Logic/Memory" for t, p in zip(d["end_use_taxonomy"], self.P) if p >= "2018Q1"))

    def test_the_page_states_the_reconciliation_it_can_earn(self) -> None:
        years = self._reconcile("euv_pct", self.st["annual_mix"], "EUV",
                                lambda y: [f"{y}Q{n}" for n in range(1, 5)])
        halves = self._reconcile("euv_pct", self.st["h1_mix"], "EUV", lambda y: [f"{y}Q1", f"{y}Q2"])
        ok_y = sum(1 for _, i, e, a in years if abs(i - e) <= a)
        ok_h = sum(1 for _, i, e, a in halves if abs(i - e) <= a)
        note = self.ref["EX_EUVQ"]["note"]
        self.assertIn(f"{asml.cn_count(len(years))}个年份里{asml.cn_count(ok_y)}个", note)
        self.assertIn(f"{asml.cn_count(len(halves))}个半年里{asml.cn_count(ok_h)}个", note)
        for y, implied, euro, allowance in halves:
            if abs(implied - euro) > allowance:
                self.assertIn(asml.eur_m(implied - euro), note)

    def test_a_pie_without_an_euv_slice_is_zero_only_when_the_rest_sum_to_100(self) -> None:
        d = self.st["deck_mix"]
        for p in d["no_euv_slice"]:
            i = self.P.index(p)
            self.assertNotIn("EUV", d["technology_pct"][i])
            self.assertEqual(sum(d["technology_pct"][i].values()), 100)
            self.assertEqual(d["euv_pct"][i], 0)
            self.assertIn(p, self.ref["EX_EUVQ"]["note"])

    def test_the_two_region_bases_never_share_a_chart(self) -> None:
        quarterly, annual = self.ref["EX_REGIONQ"], self.ref["EX_REGIONY"]
        self.assertIn("发货地", quarterly["note"])
        self.assertIn("客户工厂所在地", annual["note"])
        self.assertEqual(quarterly["xlabels"], self.P)
        self.assertEqual(annual["xlabels"], sorted(self.st["annual_mix"]))
        # the quarterly one is shares of net system sales, the annual one euros of total net sales
        am = self.st["annual_mix"]
        for y, v in zip(annual["xlabels"], [sum(s["values"][k] for s in annual["stacks"])
                                            for k in range(len(annual["xlabels"]))]):
            with self.subTest(year=y):
                self.assertAlmostEqual(v, am[y]["total_net_sales"], delta=0.5)

    # ── orders ───────────────────────────────────────────────────────────────
    def test_the_bookings_axis_stops_where_the_company_stopped(self) -> None:
        bk = self.st["bookings"]
        ex = self.ref["EX_BOOK"]
        self.assertEqual(ex["xlabels"], bk["periods"])
        self.assertEqual(bk["periods"][-1], "2025Q4")
        self.assertLess(bk["periods"][-1], self.P[-1])
        self.assertIn(f"{bk['periods'][-1]} 的 {asml.eur_m(bk['net_bookings'][-1], 0)}", ex["title"])
        self.assertIn("此后公司不再公布", ex["title"])
        self.assertFalse(bk["announcement_found_on_edgar"])
        # the page bounds the claim to what it searched
        self.assertIn("本页检索", ex["note"])
        self.assertNotIn("EDGAR 上的任何一份申报", text_of(self.payload))

    def test_the_backlog_chart_names_every_missing_year_end(self) -> None:
        printed = {int(e["as_of"][:4]) for e in self.st["backlog"] if e["as_of"].endswith("-12-31")}
        ex = self.ref["EX_BACKLOG"]
        years = [int(y) for y in ex["xlabels"]]
        missing = [y for y in years if y not in printed]
        self.assertEqual([ex["values"][years.index(y)] for y in missing], [None] * len(missing))
        self.assertIn("、".join(str(y) for y in missing), ex["title"])

    # ── cash ─────────────────────────────────────────────────────────────────
    def test_the_fourth_quarter_cash_share_is_recomputed(self) -> None:
        q = self.q
        years = [y for y in range(2016, int(self.P[-1][:4]) + 1) if f"{y}Q4" in self.P]
        shares = {}
        for y in years:
            total = sum(q["cfo"][self.P.index(f"{y}Q{n}")] for n in range(1, 5))
            shares[y] = q["cfo"][self.P.index(f"{y}Q4")] / total * 100
        title = self.ref["EX_CFO"]["title"]
        self.assertIn(f"{years[-1]} 年全年的 {shares[years[-1]]:.1f}% 落在第四季度", title)
        if all(v > 50 for v in shares.values()):
            self.assertIn("每一年的第四季度都占到全年一半以上", title)

    def test_free_cash_flow_and_returns_are_the_statement_lines(self) -> None:
        q = self.q
        years = [int(y) for y in self.ref["EX_RETURN"]["xlabels"]]
        fcf = [sum(q["cfo"][self.P.index(f"{y}Q{n}")] + q["capex_ppe"][self.P.index(f"{y}Q{n}")]
                   + q["capex_intangibles"][self.P.index(f"{y}Q{n}")] for n in range(1, 5)) for y in years]
        groups = self.ref["EX_RETURN"]["groups"]
        for got, want in zip(groups[0]["values"], fcf):
            self.assertAlmostEqual(got, want, places=4)
        self.assertTrue(all(v >= 0 for v in groups[1]["values"] + groups[2]["values"]))

    # ── shape and render contract ────────────────────────────────────────────
    def test_every_exhibit_plots_one_point_per_x_label(self) -> None:
        for ex in self.exhibits:
            n = len(ex["xlabels"])
            series = []
            for key in ("groups", "series", "stacks"):
                series += [s["values"] for s in ex.get(key, [])]
            for key in ("values", "lo", "hi", "actual"):
                if key in ex:
                    series.append(ex[key])
            if ex.get("line"):
                series.append(ex["line"]["values"])
            with self.subTest(exhibit=ex["n"]):
                self.assertTrue(series)
                for values in series:
                    self.assertEqual(len(values), n)

    def test_a_negative_bar_sits_on_a_kind_that_can_draw_below_zero(self) -> None:
        for ex in self.exhibits:
            if ex["kind"] not in ZERO_FLOORED_KINDS:
                continue
            values = list(ex.get("values") or [])
            for s in ex.get("stacks", []):
                values += s["values"]
            with self.subTest(exhibit=ex["n"]):
                self.assertTrue(all(v is None or v >= 0 for v in values))
        # the one chart that has to go negative is on a kind that can
        cfo = self.ref["EX_CFO"]
        self.assertEqual(cfo["kind"], "grouped_bars")
        self.assertTrue(any(v < 0 for v in cfo["groups"][0]["values"]))

    def test_every_stacked_dual_declares_a_ceiling_its_line_stays_under(self) -> None:
        for ex in self.exhibits:
            if ex["kind"] != "stacked_dual":
                continue
            with self.subTest(exhibit=ex["n"]):
                self.assertNotIn("ymax", ex)
                self.assertIn("ymax", ex["line"])
                self.assertLessEqual(max(v for v in ex["line"]["values"] if v is not None),
                                     ex["line"]["ymax"])
                self.assertTrue(all(v is not None for s in ex["stacks"] for v in s["values"]))

    def test_exhibits_are_numbered_in_render_order_from_two(self) -> None:
        self.assertEqual([ex["n"] for ex in self.exhibits], list(range(2, len(self.exhibits) + 2)))
        self.assertNotIn("{EX_", text_of(self.payload))

    def test_tables_are_numbered_after_the_exhibits_and_carry_the_shared_table(self) -> None:
        tables = self.payload["tables"]
        self.assertEqual([t["n"] for t in tables],
                         list(range(self.exhibits[-1]["n"] + 1, self.exhibits[-1]["n"] + 1 + len(tables))))
        self.assertTrue(any("跨页对照" in t["title"] for t in tables))
        quarterly = tables[0]
        self.assertEqual([r[0] for r in quarterly["rows"]], self.P)

    def test_colour_and_formatter_names_are_ones_the_renderer_knows(self) -> None:
        for ex in self.exhibits:
            colours = [s.get("color") for key in ("groups", "series", "stacks") for s in ex.get(key, [])]
            if ex.get("line"):
                colours.append(ex["line"].get("color"))
            formats = [ex.get(k) for k in ("fmt", "yfmt", "label_fmt") if ex.get(k)]
            if ex.get("line") and ex["line"].get("yfmt"):
                formats.append(ex["line"]["yfmt"])
            with self.subTest(exhibit=ex["n"]):
                self.assertTrue(set(c for c in colours if c) <= VALID_COLORS, colours)
                self.assertTrue(set(formats) <= VALID_FORMATS, formats)

    def test_long_axes_are_thinned(self) -> None:
        for ex in self.exhibits:
            if len(ex["xlabels"]) > 30:
                with self.subTest(exhibit=ex["n"]):
                    self.assertGreaterEqual(ex.get("xstep", 1), 2)

    def test_no_placeholder_or_markup_leaks_into_literal_slots(self) -> None:
        for slot in LITERAL_SLOTS:
            with self.subTest(slot=slot):
                self.assertNotRegex(self.payload[slot], r"</?[a-z]+>")
                self.assertNotIn("**", self.payload[slot])
        for ex in self.exhibits:
            self.assertNotRegex(ex["title"], r"</?[a-z]+>")
        for note in self.payload["notes"]:
            self.assertNotRegex(note, r"</?[a-z]+>")
            self.assertNotIn("**", note)

    def test_the_card_quarter_beat_is_measured_against_the_upper_bound(self) -> None:
        """The first card says how much of the beat installed base management
        explains. Against the midpoint it is well under half; against the upper
        bound it is most of it -- so the card must say which one it measured."""
        rows = {p: (lo, hi, a) for p, lo, hi, a in guided_rows(self.st, "sales", "total_net_sales")}
        ibm = {p: (lo, hi, a) for p, lo, hi, a in guided_rows(self.st, "ibm", "ibm_sales")}
        lo, hi, actual = rows[self.P[-1]]
        ilo, ihi, iact = ibm[self.P[-1]]
        share = (iact - ilo) / (actual - hi) * 100
        self.assertIn(f"总净销售比指引上限多 {asml.eur_m(actual - hi)}", self.payload["brief"])
        self.assertIn(f"相当于前者的 {share:.0f}%", self.payload["brief"])
        self.assertIn("大半" if share >= 50 else "一部分", self.payload["brief"])

    def test_sources_are_official_sec_links(self) -> None:
        links = self.payload["source_links"]
        releases = [l for l in links if "季度业绩新闻稿" in l["label"]]
        annual = [l for l in links if "20-F" in l["label"]]
        self.assertEqual(len(releases), len(self.P))
        self.assertGreaterEqual(len(annual), 10)
        for link in links:
            with self.subTest(url=link["url"]):
                self.assertTrue(link["url"].startswith("https://www.sec.gov/Archives/edgar/data/937966/"))
        self.assertEqual(sorted(l["date"] for l in releases), sorted(self.q["release_dates"]))

    def test_the_only_dollars_on_the_page_are_the_shared_cross_page_table(self) -> None:
        cross = next(t for t in self.payload["tables"] if "跨页对照" in t["title"])
        body = copy.deepcopy(self.payload)
        body["tables"] = [t for t in body["tables"] if t["n"] != cross["n"]]
        self.assertNotIn("US$", text_of(body))

    def test_the_guidance_slot_is_empty(self) -> None:
        """Guidance is settled in its own section; the shared guidance block is not used."""
        self.assertIsNone(self.payload["guidance"])

    # ── what is published ────────────────────────────────────────────────────
    def test_the_period_the_page_reports_is_the_last_quarter_in_the_series(self) -> None:
        self.assertEqual(self.payload["latest"]["disclosed_period_label"], display_period(self.P[-1]))
        self.assertIn(asml.quarter_cn(self.P[-1]), self.payload["title"])

    def test_published_payload_and_shell(self) -> None:
        self.assertEqual(js_payload(ROOT / "data" / "asml.js", "window.DASH"), self.payload)
        shell = (ROOT / "asml" / "index.html").read_text(encoding="utf-8")
        self.assertIn("../data/asml.js", shell)
        self.assertIn("ASML", shell)

    def test_shell_versions_every_script_by_content(self) -> None:
        shell = (ROOT / "asml" / "index.html").read_text(encoding="utf-8")
        sources = re.findall(r'<script src="\.\./([^"?]+)(\?v=([0-9a-f]+))?"', shell)
        self.assertEqual([name for name, _, _ in sources],
                         ["data/roster.js", "data/asml.js", "assets/charts.js", "assets/page.js"])
        for name, query, digest in sources:
            with self.subTest(script=name):
                self.assertTrue(query, f"{name} is served without a cache-busting version")
                expected = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()[:len(digest)]
                self.assertEqual(digest, expected, f"{name} carries a stale digest")

    def test_the_roster_entry_matches_the_payload(self) -> None:
        entry = next(e for e in ENTRIES if e["slug"] == "asml")
        self.assertEqual(entry["ticker"], self.payload["company"]["ticker"])
        self.assertEqual(entry["group"], self.payload["company"]["group"])
        self.assertEqual(entry["group"], "semiconductor_ai")
        self.assertNotIn("headline_metrics", entry)
        # the fiscal year is the calendar year: no offset relabelling claimed
        self.assertNotIn("本站按自然年季度标注", entry["cadence_label"])

    def test_the_home_page_card_matches_the_payload(self) -> None:
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        card = home.split('href="asml/"', 1)[1].split("</a>", 1)[0]
        self.assertIn(self.payload["latest"]["release_date"], card)
        self.assertIn(self.payload["latest"]["disclosed_period_label"], card)
        self.assertIn(" · ".join(asml.headline_metrics(self.st)), card)

    def test_the_card_figures_are_three_and_computed(self) -> None:
        metrics = asml.headline_metrics(self.st)
        self.assertEqual(len(metrics), 3)
        self.assertIn(asml.eur_m(self.q["total_net_sales"][-1]), metrics[0])
        self.assertIn(f"{self.q['gross_margin_printed_pct'][-1]:.1f}%", metrics[1])


class AsmlRollTest(unittest.TestCase):
    """What a roll has to change in `series/asml.json`, and what the page does
    when it does not."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads(asml.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = asml.build_payload(cls.source)

    def title(self, payload: dict, ref: str) -> str:
        return by_ref(payload)[ref]["title"]

    def test_a_block_stamped_with_another_period_stops_the_build(self) -> None:
        stale = copy.deepcopy(self.source)
        stale["quarter_story"]["period"] = "Q1 1999"
        with self.assertRaisesRegex(ValueError, "stamped"):
            asml.build_payload(stale)

        stale_latest = copy.deepcopy(self.source)
        stale_latest["latest"]["period"] = "Q1 1999"
        with self.assertRaisesRegex(ValueError, "stamped"):
            asml.build_payload(stale_latest)

        orphan = copy.deepcopy(self.source)
        last = orphan["quarterly"]["periods"][-1]
        label = asml.quarter_cn(last) + "业绩新闻稿"
        orphan["sources"] = [src for src in orphan["sources"] if not src["label"].startswith(label)]
        with self.assertRaisesRegex(ValueError, "sources"):
            asml.build_payload(orphan)

    def test_a_quarter_without_its_story_leaves_the_capacity_bars_out(self) -> None:
        bare = asml.build_payload({k: v for k, v in self.source.items() if k != "quarter_story"})
        full_ex, bare_ex = exhibits_of(self.payload), exhibits_of(bare)
        self.assertEqual(len(bare_ex), len(full_ex))
        units = by_ref(bare)["EX_UNITSY"]
        self.assertFalse(any("产能" in label or "计划" in label for label in units["xlabels"]))
        self.assertNotIn("产能", units["title"])
        self.assertIn("产能", by_ref(self.payload)["EX_UNITSY"]["title"])

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        """Break each universal claim in the data and watch its sentence go."""
        # 1. "没有一年下半年少于上半年": make one year's second half smaller
        shrunk = copy.deepcopy(self.source)
        q = shrunk["quarterly"]
        for n in (3, 4):
            i = q["periods"].index(f"2016Q{n}")
            q["total_net_sales"][i] *= 0.5
        note = by_ref(asml.build_payload(shrunk))["EX_H2H1"]["note"]
        self.assertNotIn("没有一年下半年少于上半年", note)
        self.assertIn("下半年少于上半年的有一年", note)
        self.assertIn("没有一年下半年少于上半年", by_ref(self.payload)["EX_H2H1"]["note"])

        # 2. "每一年的第四季度都占到全年一半以上": move one year's cash into Q1
        moved = copy.deepcopy(self.source)
        q = moved["quarterly"]
        i4, i1 = q["periods"].index("2019Q4"), q["periods"].index("2019Q1")
        q["cfo"][i1] += q["cfo"][i4]
        q["cfo"][i4] = 0.0
        title = self.title(asml.build_payload(moved), "EX_CFO")
        self.assertNotIn("每一年的第四季度", title)
        self.assertRegex(title, r"年里.+年第四季度占到全年一半以上")

        # 3. "四十季里最高": another quarter's bookings above the last one
        topped = copy.deepcopy(self.source)
        b = topped["bookings"]
        b["net_bookings"][0] = b["net_bookings"][-1] + 1
        self.assertNotIn("季里最高", self.title(asml.build_payload(topped), "EX_BOOK"))
        self.assertIn("季里最高", self.title(self.payload, "EX_BOOK"))

        # 4. "有两年比这更高": lower those years and the list empties
        flat = copy.deepcopy(self.source)
        q = flat["quarterly"]
        for year in range(2016, 2026):
            for n in (3, 4):
                i = q["periods"].index(f"{year}Q{n}")
                j = q["periods"].index(f"{year}Q{n - 2}")
                q["total_net_sales"][i] = q["total_net_sales"][j]
        title = self.title(asml.build_payload(flat), "EX_H2H1")
        self.assertIn("没有一年比这更高", title)

        # 5. "此后 N 季有 1 季低于下限" -- the positive control: put the one
        # range-era miss inside its range and the sentence becomes "没有一季"
        inside = copy.deepcopy(self.source)
        q = inside["quarterly"]
        i = q["periods"].index("2020Q1")
        g = next(g for g in inside["guidance"] if g["guided_quarter"] == "2020Q1")
        gap = g["sales"]["low"] - q["total_net_sales"][i]
        q["total_net_sales"][i] += gap
        q["net_system_sales"][i] += gap
        note = by_ref(asml.build_payload(inside))["EX_SALESDEV"]["note"]
        self.assertIn("没有一季低于下限", note)
        self.assertNotIn("没有一季低于下限", by_ref(self.payload)["EX_SALESDEV"]["note"])

    def test_the_next_quarter_rolls_without_touching_the_code(self) -> None:
        """Append a synthetic 2026Q3 and rebuild: no code change, new labels."""
        rolled = copy.deepcopy(self.source)
        q = rolled["quarterly"]
        n = len(q["periods"])
        q["periods"].append("2026Q3")
        q["period_ends"].append("2026-09-27")
        q["release_dates"].append("2026-10-14")
        for key, values in q.items():
            if isinstance(values, list) and len(values) == n and key not in ("periods", "period_ends",
                                                                               "release_dates"):
                values.append(values[-4])
        d = rolled["deck_mix"]
        for key, values in d.items():
            if isinstance(values, list) and len(values) == n:
                values.append(values[-4])
        rolled["guidance"].append({
            "filed": "2026-10-14", "reported_quarter": "2026Q3", "guided_quarter": "2026Q4",
            "withdrawn": False,
            "sales": {"form": "range", "low": 13000, "high": 14000, "verbatim": "between €13.0 billion and €14.0 billion"},
            "gross_margin": {"form": "range", "low": 55, "high": 57, "verbatim": "between 55% and 57%"},
            "ibm": {"form": "around", "low": 3000, "high": 3000, "verbatim": "around €3.0 billion"},
            "rd": None, "sga": None, "full_year": [
                {"year": 2026, "metric": "total_net_sales", "form": "range", "low": 44000, "high": 45000,
                 "point": None, "unit": "eur_m", "verbatim": "between €44 billion and €45 billion"}],
            "flags": []})
        rolled["latest"] = dict(rolled["latest"], period="Q3 2026")
        rolled.pop("quarter_story")
        rolled["sources"] = rolled["sources"] + [
            {"label": "2026 年第三季度业绩新闻稿（6-K EX-99.1，2026-10-14）",
             "url": "https://www.sec.gov/Archives/edgar/data/937966/x/y.htm", "date": "2026-10-14"}]
        payload = asml.build_payload(rolled)
        self.assertEqual(payload["latest"]["disclosed_period_label"], "Q3 2026")
        self.assertIn("2026 年第三季度", payload["title"])
        ref = by_ref(payload)
        self.assertEqual(ref["EX_MIX"]["xlabels"][-1], "2026Q3")
        self.assertEqual(len(ref["EX_MIX"]["stacks"][0]["values"]), len(ref["EX_MIX"]["xlabels"]))
        # four releases now guide the year, and the implied half still uses the latest one
        self.assertEqual(len(ref["EX_FYPATH"]["xlabels"]), 4)
        self.assertIn("€44–45B", ref["EX_H2H1"]["note"])


class AsmlChecksTest(unittest.TestCase):
    """`_checks` is an independent re-read of the primary filing.

    The quarterly series is built from the EX-99.3 statement exhibit, which
    prints euro millions to one decimal. `_checks` was typed from the EX-99.1
    press release of the same 6-K -- a different document with its own summary
    table, printing whole millions -- so the two agreeing after the company's own
    rounding is evidence rather than a tautology. The builder never reads the
    block (`tests/test_data_only_roll.py` proves that).
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.st = json.loads(asml.STAGING_PATH.read_text(encoding="utf-8"))
        cls.c = cls.st["_checks"]
        cls.payload = asml.build_payload(cls.st)
        cls.q = cls.st["quarterly"]

    def test_the_page_names_the_checked_period(self) -> None:
        c, latest = self.c, self.payload["latest"]
        self.assertEqual(c["period"], latest["disclosed_period_label"])
        self.assertEqual(c["period_end"], latest["period_end"])
        self.assertEqual(c["release_date"], latest["release_date"])
        self.assertIn(f"截至 {c['period_end']}", self.payload["subtitle"])
        self.assertIn(f"发布 {c['release_date']}", self.payload["subtitle"])
        self.assertIn("EX-99.1", c["source"])
        self.assertNotIn("financialstatementsusgaa", c["source"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        """The exhibit prints one decimal, the release whole millions, and each is
        rounded from the company's own unrounded figure -- so they agree to within
        half a million, not under any one rounding of the other. Q2 2026 total net
        sales is the case that shows it: 9,326.5 in the exhibit, 9,326 in the
        release, where rounding the exhibit's figure half-up would say 9,327. The
        page prints the exhibit's figure."""
        c, q = self.c, self.q
        for key, series_key in (("total_net_sales_eur_m", "total_net_sales"),
                                ("ibm_sales_eur_m", "ibm_sales"),
                                ("gross_profit_eur_m", "gross_profit"),
                                ("net_income_eur_m", "net_income")):
            with self.subTest(key=key):
                self.assertLessEqual(abs(q[series_key][-1] - c[key]), 0.5 + 1e-9)
        self.assertEqual(q["gross_margin_printed_pct"][-1], c["gross_margin_pct"])
        self.assertEqual(q["eps_basic"][-1], c["eps_basic_eur"])

    def test_the_page_prints_the_checked_figures(self) -> None:
        c, payload = self.c, self.payload
        head = payload["headline"]
        printed = float(re.search(r"总净销售 €([\d,]+\.\d)M", head).group(1).replace(",", ""))
        self.assertLessEqual(abs(printed - c["total_net_sales_eur_m"]), 0.5 + 1e-9)
        self.assertIn(f"毛利率 {c['gross_margin_pct']:.1f}%", head)
        metrics = asml.headline_metrics(self.st)
        self.assertIn(f"{c['gross_margin_pct']:.1f}%", metrics[1])
        table = self.payload["tables"][0]
        self.assertEqual(table["rows"][-1][0], self.q["periods"][-1])
        self.assertEqual(table["rows"][-1][-2], f"{c['eps_basic_eur']:.2f}")


if __name__ == "__main__":
    unittest.main()
