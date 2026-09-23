"""Kering page: the reconciliations that license what the page publishes.

Three tests carry the page, each because a failure it catches would leave every
other gate green:

- `test_no_profit_series_is_carried_on_the_quarterly_axis`. Kering publishes
  revenue four times a year and profit twice, so no quarter on this page has a
  profit figure of its own. The most damaging edit a future quarter could make is
  to invent one -- halve a half, or put a half-year series on the quarterly axis,
  where it would line up against the wrong periods at the right length. Asserted
  from each exhibit's own axis shape, not from a list of exhibit names.
- `test_every_basis_switch_is_marked_exactly_where_it_happens`. The group
  half-year lines cross three basis changes (PUMA's exit, IFRS 16, Kering Beauté's
  sale). A splice moves a long line without breaking any sum -- every half still
  closes on its own basis -- so the only protection is that the axis says so.
  The expected break positions are derived from the basis labels the series
  carries, independently of the `break_at` the builder wrote.
- `test_the_guidance_settlement_is_recomputed_from_the_halves`. The page's
  sharpest claim is that the H2 2024 guide of "approximately 30%" was a -51.6%
  outcome. That figure is H2 = FY - H1 on the published basis for both years; this
  test rebuilds it from the half-year series by a different route (summing the
  halves into full years) and checks the title, the note and the table verdicts.

Everything else below is the shared skeleton plus the findings the titles state,
each recomputed without calling the builder's helper that produced it.

The page is rolled by editing `series/ker.json` alone (CLAUDE.md §9), so nothing
here names the page's quarter: `KerRollTest` holds what a roll must change and what
the page does when a block is stale or absent, and `KerChecksTest` holds the quarter
against `_checks`, a separate reading of the release -- and, in `_checks["note"]`, of
the local analyses whose questions and thresholds sections one and three settle.
Rolling a quarter re-keys `_checks`; this file does not change.
"""

from __future__ import annotations

import collections
import copy
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import ker  # noqa: E402
from build.all import ENTRIES  # noqa: E402
from build.board import UNIT_FORMATS, display_period, headroom, round_half_up, unit_text  # noqa: E402


def js_payload(path: Path, marker: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{marker} = ", 1)[1].rstrip().rstrip(";")
    return json.loads(body)


VALID_COLORS = {"NAVY", "BLUE", "MBLUE", "GRAY", "GREEN", "RED", "GOLD"}
VALID_FORMATS = {"f1", "f0", "f0c", "int", "pct0", "pct1", "pct0z", "pp0", "pp1",
                 "x0", "usd0", "usd1", "usd2", "f2", "f3", "pct2", "usd3", "usd4"}
LITERAL_SLOTS = ("headline", "title", "subtitle", "tracker")
QUARTER_LABEL = re.compile(r"^Q[1-4]'\d\d$")
HALF_LABEL = re.compile(r"^H[12] \d{4}$")


class KerDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.st = json.loads(ker.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = ker.build_payload(cls.st)
        cls.der = ker.derived(cls.st)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]
        cls.by_ref = {ex["ref"]: ex for ex in cls.exhibits if "ref" in ex}

    # ── the four sections of the reference page ──────────────────────────────
    def test_the_page_runs_in_the_four_sections_of_the_reference_page(self) -> None:
        """TSM's four sections, in order, with the ids and titles the format check
        reads -- and the page's own sentence about its layout says four, not the
        five it used to."""
        self.assertEqual([(s["id"], s["title"]) for s in self.payload["sections"]], [
            ("settled", "一、上季跟踪指标兑现了吗"), ("quarter_highlights", "二、本季重点"),
            ("next_quarter", "三、下季要跟踪什么"), ("routine", "四、长期常规跟踪")])
        for section in self.payload["sections"]:
            self.assertTrue(section["exhibits"], section["id"])
        notes = " ".join(self.payload["notes"])
        self.assertIn("本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列", notes)
        self.assertNotRegex(composed(self.payload), r"[五六]段排列|第五节")

    def test_each_chart_sits_where_its_content_belongs(self) -> None:
        """A half-year profit line is part of the record; the bridge of the half that
        ends with this quarter is a finding of this quarter. The company's own
        targets are settled in section one; the long brand record is routine."""
        where = {ex["ref"]: section["id"] for section in self.payload["sections"]
                 for ex in section["exhibits"] if "ref" in ex}
        for ref in ("EX_G2024", "EX_GUCCI_TARGET", "EX_YSL_TARGET", "EX_TARGETS_2022"):
            self.assertEqual(where[ref], "settled", ref)
        for ref in ("EX_GROUP_COMP", "EX_Q2_BRIDGE", "EX_GRID", "EX_GUCCI_Q"):
            self.assertEqual(where[ref], "quarter_highlights", ref)
        if "EX_H1_BRIDGE" in where:
            self.assertEqual(where["EX_H1_BRIDGE"], "quarter_highlights")
        for ref in ("EX_HOUSES", "EX_HOUSE_COMP", "EX_HOUSE_MARGIN", "EX_GROUP_MARGIN", "EX_GROSS",
                    "EX_NET_DEBT", "EX_CMD_LINE"):
            self.assertEqual(where[ref], "routine", ref)
        # section one runs (a) the closure, (b) last quarter's thresholds, (c) the
        # company's own targets -- in that order
        settled = [ex.get("ref") for ex in self.payload["sections"][0]["exhibits"]]
        order = ["EX_CLOSURE", "EX_PRIOR_HEADROOM"] + [r for r in settled if r.startswith("EX_PRIOR_")
                                                         and r != "EX_PRIOR_HEADROOM"]
        present = [r for r in order if r in settled]
        self.assertEqual(settled[:len(present)], present)
        self.assertEqual(settled[len(present):],
                         ["EX_G2024", "EX_GUCCI_TARGET", "EX_YSL_TARGET", "EX_TARGETS_2022"])

    # ── section one (a): report §0's closure of last quarter's questions ─────
    def test_the_closure_chart_counts_the_verdicts_it_lists(self) -> None:
        """The report gives a verdict per question and no tally, so the page counts
        the labels itself: the bars, the title and the table are one count."""
        closure = self.st["followup_closure"]
        ex = self.by_ref["EX_CLOSURE"]
        counts = collections.Counter(item["label"] for item in closure["items"])
        self.assertLessEqual(set(counts), set(closure["labels"]))
        shown = [label for label in closure["labels"] if counts[label]]
        self.assertEqual(ex["xlabels"], shown)
        self.assertEqual(ex["values"], [counts[label] for label in shown])
        self.assertTrue(ex["title"].startswith(f"上季 {len(closure['items'])} 条待验证问题："))
        for label in shown:
            self.assertIn(f"{counts[label]} 条{label}", ex["title"])
        for item in closure["items"]:
            if item["label"] in ("上季判断失效", "未回答"):
                self.assertIn(item["question"], ex["note"])
        table = next(t for t in self.payload["tables"] if "待验证问题的闭环" in t["title"])
        self.assertEqual([row[1:] for row in table["rows"]],
                         [[item["question"], item["verdict"], item["label"]] for item in closure["items"]])

    # ── section one (b): last quarter's thresholds ───────────────────────────
    def prior_values(self) -> dict:
        """This quarter's value for each measure a prior threshold names, read here
        from the series; a measure the series does not carry is the entry's own
        typed figure, which then has to name where it was read."""
        values = self.current_values()
        regions = self.st["new_grid_retail_regions"]["gucci"]
        values["gucci_na_retail"] = regions["north_america"][-1]
        values["gucci_retail"] = regions["total"][-1]
        return values

    def test_last_quarters_thresholds_are_settled_on_this_quarters_figures(self) -> None:
        block = self.st["prior_kpi_settlement"]
        values = self.prior_values()
        actual = []
        for entry in block["entries"]:
            if entry["measure"] in values:
                self.assertNotIn("actual", entry, f"{entry['measure']} is measured; a typed copy would drift")
                actual.append(values[entry["measure"]])
            else:
                self.assertTrue(entry.get("source"), f"{entry['measure']} is typed without a source")
                actual.append(entry["actual"])
        ex = self.by_ref["EX_PRIOR_HEADROOM"]
        self.assertEqual(ex["kind"], "diverging_bars")
        self.assertEqual(ex["values"], [round(headroom(e["direction"], e["threshold"], a), 1)
                                        for e, a in zip(block["entries"], actual)])
        for label, entry in zip(ex["xlabels"], block["entries"]):
            self.assertTrue(label.startswith(entry["metric"]), label)
            self.assertTrue(label.endswith(f"（{entry['gate']}）"), label)
        good = [headroom(e["direction"], e["threshold"], a) >= 0 for e, a in zip(block["entries"], actual)]
        bull = [g for e, g in zip(block["entries"], good) if e["gate"] == "加仓"]
        rest = [g for e, g in zip(block["entries"], good) if e["gate"] != "加仓"]
        title = ex["title"]
        self.assertTrue(title.startswith(f"上季 {len(block['entries'])} 条量化阈值："), title)
        self.assertIn(f"{len(bull)} 条加仓线", title)
        if any(bull):
            self.assertIn(f"{sum(bull)} 条达到", title)
        if not all(bull):
            self.assertIn(f"{len(bull) - sum(bull)} 条没够着", title)
            self.assertIn("没够着的加仓线", ex["note"])
        self.assertIn("一条都没碰到" if all(rest) else f"有 {len(rest) - sum(rest)} 条被触发", title)
        table = next(t for t in self.payload["tables"] if t["title"].startswith("上季量化阈值的结算"))
        self.assertEqual([row[4] for row in table["rows"]], [e["quote"] for e in block["entries"]])

    def test_each_prior_threshold_line_draws_every_threshold_set_on_its_measure(self) -> None:
        block = self.st["prior_kpi_settlement"]
        charts = [ex for ex in self.payload["sections"][0]["exhibits"]
                  if ex.get("ref", "").startswith("EX_PRIOR_") and ex["kind"] == "lines"]
        self.assertTrue(charts)
        for ex in charts:
            measure = ex["ref"][len("EX_PRIOR_"):].lower()
            entries = [e for e in block["entries"] if e["measure"] == measure]
            self.assertTrue(entries, measure)
            lines = ex["series"][1:]
            self.assertEqual([line["values"] for line in lines],
                             [[e["threshold"]] * len(ex["xlabels"]) for e in entries])
            self.assertEqual([line["color"] for line in lines],
                             ["GREEN" if e["gate"] == "加仓" else "RED" for e in entries])
            for e in entries:
                self.assertIn(f"上季{e['gate']}线", ex["title"])
            # drawn on the whole record, not on a recent window
            self.assertIn(ex["xlabels"][0], (ker.compact_quarter(self.st["long_quarters"][0]),
                                             self.st["halves"][0], self.st["balance_dates"][0]), ex["ref"])

    # ── the disclosure shape this page exists to respect ─────────────────────
    def test_no_profit_series_is_carried_on_the_quarterly_axis(self) -> None:
        profit_words = ("利润", "利润率", "毛利", "净负债")
        quarterly = [ex for ex in self.exhibits
                     if ex.get("xlabels") and all(QUARTER_LABEL.match(x) for x in ex["xlabels"])]
        self.assertGreaterEqual(len(quarterly), 5, "the quarterly charts moved; the scan found too few")
        for ex in quarterly:
            names = [ex.get("legend") or ""] + [ex.get("ylab") or "", ex.get("ylab2") or ""]
            for key in ("groups", "series", "stacks"):
                names += [b.get("name") or "" for b in ex.get(key) or []]
            for key in ("yoy", "line", "bar"):
                if isinstance(ex.get(key), dict):
                    names.append(ex[key].get("name") or "")
            for name in names:
                for word in profit_words:
                    self.assertNotIn(word, name, f"Ex{ex['n']} puts {name!r} on a quarterly axis")
        # every half-year series in the staging file is exactly as long as the halves
        halves = len(self.st["halves"])
        for key, block in self.st["half_group"].items():
            self.assertEqual(len(block["values"]), halves, key)

    def test_every_half_year_chart_says_so_on_its_own_axis(self) -> None:
        charts = [ex for ex in self.exhibits
                  if ex.get("xlabels") and all(HALF_LABEL.match(x) for x in ex["xlabels"])]
        self.assertGreaterEqual(len(charts), 4)
        for ex in charts:
            axis = (ex.get("ylab") or "") + (ex.get("ylab2") or "")
            self.assertIn("半年", axis, f"Ex{ex['n']} plots halves without saying so on its axis")

    def test_no_axis_mixes_quarters_and_halves(self) -> None:
        for ex in self.exhibits:
            labels = ex.get("xlabels") or []
            q = sum(1 for x in labels if QUARTER_LABEL.match(x))
            h = sum(1 for x in labels if HALF_LABEL.match(x))
            self.assertFalse(q and h, f"Ex{ex['n']} mixes quarters and halves")

    def test_every_basis_switch_is_marked_exactly_where_it_happens(self) -> None:
        """Family = what actually changes the numbers; a label rename is not a switch."""
        family = {
            "published_incl_sport_lifestyle": "incl_sport_lifestyle",
            "continuing_restated_ifrs5": "continuing_ias17",
            "ifrs16_restated": "continuing_ifrs16", "published": "continuing_ifrs16",
            "published_incl_beaute": "continuing_ifrs16",
            "restated_ex_beaute": "ex_beaute", "published_new_grid": "ex_beaute",
        }
        basis = [family[b] for b in self.st["half_group"]["recurring_operating_income"]["basis"]]
        switches = [i for i in range(1, len(basis)) if basis[i] != basis[i - 1]]
        self.assertEqual(len(switches), 3, "the page's note says three switches")
        self.assertEqual(self.by_ref["EX_GROUP_MARGIN"]["break_at"], switches)
        # gross margin is not touched by IFRS 16, so only the two perimeter switches apply
        gross_switches = [i for i in switches if basis[i] != "continuing_ifrs16"]
        self.assertEqual(self.by_ref["EX_GROSS"]["break_at"], gross_switches)
        # Other Houses re-presentation: the stacked chart breaks where 2022 starts
        houses = self.by_ref["EX_HOUSES"]
        self.assertEqual(houses["xlabels"][houses["break_at"]], "Q1'22")

    def test_the_other_houses_perimeter_is_the_2018_one_and_the_splices_are_declared(self) -> None:
        rev = self.st["quarterly_revenue_eur_m"]["other_houses"]
        q = self.st["long_quarters"]
        for row in self.st["other_houses_perimeter_2016_2018"]:
            i = q.index(row["period"])
            self.assertEqual(rev[i], row["ifrs5_june_2018"])
            self.assertLess(row["ifrs5_june_2018"], row["first_published"],
                            "the IFRS 5 perimeter removes brands, so it must be smaller")
        for row in self.st["other_houses_representation_2021"]:
            i = q.index(row["period"])
            self.assertEqual(rev[i], row["first_published"], "2021 keeps its first publication")
            gap = row["represented_2022"] - row["first_published"]
            self.assertGreater(gap, 3.5, row)
            self.assertLess(gap, 6.5, row)

    def test_brand_lines_stop_where_disclosure_stops(self) -> None:
        rev = self.st["quarterly_revenue_eur_m"]
        q = self.st["long_quarters"]
        last = q.index("2025Q4")
        for h in ("saint_laurent", "bottega_veneta", "other_houses"):
            self.assertIsNotNone(rev[h][last], h)
            self.assertEqual(rev[h][last + 1:], [None] * (len(q) - last - 1), h)
        self.assertTrue(all(v is not None for v in rev["gucci"]))
        self.assertEqual(self.by_ref["EX_HOUSES"]["xlabels"][-1], "Q4'25")

    def test_each_quarter_comes_from_the_release_that_first_published_it(self) -> None:
        q = self.st["long_quarters"]
        for h in ("gucci", "saint_laurent", "bottega_veneta"):
            for i, p in enumerate(q):
                src = self.st["quarterly_revenue_src"][h][i]
                if self.st["quarterly_revenue_eur_m"][h][i] is None:
                    continue
                year, quarter = p[:4], p[4:]
                expected = {"Q1": f"KER_{year}Q1_revenue_release", "Q3": f"KER_{year}Q3_revenue_release",
                            "Q2": f"KER_H1_{year}_results_release", "Q4": f"KER_FY_{year}_results_release"}[quarter]
                self.assertEqual(src, expected, (h, p))

    def test_the_new_grid_closes_to_the_group_every_quarter(self) -> None:
        g = self.st["new_grid"]["revenue_eur_m"]
        for i, p in enumerate(self.st["new_grid"]["quarters"]):
            parts = sum(g[k][i] for k in ("fashion_leather_goods", "jewelry", "eyewear",
                                           "corporate_and_other", "eliminations"))
            self.assertLessEqual(abs(parts - g["total"][i]), 1, p)
            self.assertLessEqual(g["gucci"][i], g["fashion_leather_goods"][i], "Gucci is inside F&LG")

    def test_h2_is_always_the_full_year_minus_the_first_half(self) -> None:
        flags = self.st["half_group"]["revenue"]["flag"]
        for i, half in enumerate(self.st["halves"]):
            self.assertEqual(flags[i], "D" if half.startswith("H2") else "printed", half)

    def test_a_period_of_net_cash_is_drawn_below_zero(self) -> None:
        """`bars_labeled` draws from a zero floor (Richemont's rollback drill put a
        negative bar under the plot). Kering's net debt was €168M at the end of 2021;
        a period of net cash switches the chart to the grouped form."""
        cash = copy.deepcopy(self.st)
        cash["net_debt_eur_m"][-1] = -500.0
        chart = next(ex for section in ker.build_payload(cash)["sections"] for ex in section["exhibits"]
                     if ex.get("ref") == "EX_NET_DEBT")
        self.assertEqual(chart["kind"], "grouped_bars")
        self.assertEqual(chart["groups"][0]["values"][-1], -500.0)
        self.assertEqual(self.by_ref["EX_NET_DEBT"]["kind"],
                         "bars_labeled" if min(self.st["net_debt_eur_m"]) >= 0 else "grouped_bars")

    def test_net_debt_is_the_exact_table_figure_not_the_rounded_prose(self) -> None:
        nd = self.st["net_debt_eur_m"]
        self.assertEqual(len(nd), len(self.st["balance_dates"]))
        rounded_to_100 = [d for d, v in zip(self.st["balance_dates"], nd) if v % 100 == 0]
        self.assertEqual(rounded_to_100, [], "a prose-rounded net debt slipped into the series")

    # ── the findings the page states ─────────────────────────────────────────
    def test_the_guidance_settlement_is_recomputed_from_the_halves(self) -> None:
        halves = self.st["halves"]
        roi = self.st["half_group"]["recurring_operating_income"]["values"]
        fy = lambda y: roi[halves.index(f"H1 {y}")] + roi[halves.index(f"H2 {y}")]
        h1 = (roi[halves.index("H1 2024")] / roi[halves.index("H1 2023")] - 1) * 100
        h2 = ((fy(2024) - roi[halves.index("H1 2024")]) / (fy(2023) - roi[halves.index("H1 2023")]) - 1) * 100
        self.assertTrue(-45 <= h1 <= -40, f"H1 2024 {h1:.2f}% is no longer inside the guided range")
        self.assertLess(h2, -45, "the H2 miss is the page's lead finding")
        self.assertAlmostEqual(fy(2024), 2554, places=6)
        ex = self.by_ref["EX_G2024"]
        self.assertIn(f"{h2:.1f}%", ex["title"])
        self.assertIn(f"{h1:.1f}%", ex["note"])
        self.assertIn("Based on the scope of consolidation and exchange rates", ex["note"])
        table = next(t for t in self.payload["tables"] if "数字目标" in t["title"])
        verdicts = {row[0]: row[-1] for row in table["rows"]}
        self.assertEqual(verdicts["2024 上半年经常性营业利润"], "兑现")
        self.assertEqual(verdicts["2024 下半年经常性营业利润"], "未兑现")
        self.assertEqual(verdicts["2024 全年经常性营业利润"], "兑现")
        for row in table["rows"]:
            self.assertRegex(row[2], r"[A-Za-z]", "the quote column must hold the original wording")

    def test_gucci_hit_each_target_in_a_different_year(self) -> None:
        ann = self.st["annual_house"]["gucci"]
        years = ann["years"]
        margins = [r / v * 100 for r, v in zip(ann["roi_eur_m"], ann["revenue_eur_m"])]
        rev_years = [y for y, v in zip(years, ann["revenue_eur_m"]) if v >= 10000]
        margin_years = [y for y, m in zip(years, margins) if m >= 40]
        self.assertTrue(rev_years and margin_years)
        self.assertFalse(set(rev_years) & set(margin_years), "the page says never in the same year")
        title = self.by_ref["EX_GUCCI_TARGET"]["title"]
        self.assertIn(rev_years[0], title)
        self.assertIn(margin_years[0], title)
        self.assertIn("从未同一年", title)

    def test_saint_laurent_margin_was_above_target_when_revenue_crossed_each_line(self) -> None:
        ann = self.st["annual_house"]["saint_laurent"]
        for target_rev, target_margin in ((2000, 25), (3000, 27)):
            i = next(j for j, v in enumerate(ann["revenue_eur_m"]) if v >= target_rev)
            margin = ann["roi_eur_m"][i] / ann["revenue_eur_m"][i] * 100
            self.assertGreater(margin, target_margin, ann["years"][i])
            self.assertIn(ann["years"][i], self.by_ref["EX_YSL_TARGET"]["title"])

    def test_gucci_negative_streak_is_counted_not_typed(self) -> None:
        comp = self.st["quarterly_comparable_pct"]["gucci"]
        last_non_negative = max(i for i, v in enumerate(comp) if v >= 0)
        streak = len(comp) - 1 - last_non_negative
        title = self.by_ref["EX_GUCCI_Q"]["title"]
        if streak:
            start = ker.compact_quarter(self.st["long_quarters"][last_non_negative + 1])
            self.assertIn(f"连续 {streak} 个季度为负", title)
            self.assertIn(f"连续 {streak} 个季度为负", self.payload["headline"])
            self.assertIn(f"自 {start} 起每一季为负", self.by_ref["EX_GUCCI_Q"]["note"])
        else:
            self.assertNotIn("个季度为负（本季", title)
            self.assertNotIn("起每一季为负", self.by_ref["EX_GUCCI_Q"]["note"])

    def test_the_group_turned_positive_for_the_first_time_since_the_quarter_named(self) -> None:
        comp = self.st["quarterly_comparable_pct"]["group_first_published"]
        title = self.by_ref["EX_GROUP_COMP"]["title"]
        positives = [i for i in range(len(comp) - 1) if comp[i] > 0]
        if comp[-1] > 0 and positives and positives[-1] < len(comp) - 2:
            previous_positive = positives[-1]
            self.assertTrue(all(v <= 0 for v in comp[previous_positive + 1:-1]))
            label = ker.compact_quarter(self.st["long_quarters"][previous_positive])
            self.assertIn(f"{label} 之后第一次为正", title)
        else:
            self.assertNotIn("之后第一次为正", title)

    def test_the_margin_bridge_legs_close_exactly(self) -> None:
        block = self.st.get("half_bridge")
        if block is None or block["period"] != self.st["halves"][-1]:
            self.assertNotIn("EX_H1_BRIDGE", self.by_ref)
            return
        ex = self.by_ref["EX_H1_BRIDGE"]
        legs = [v for v in ex["stacks"][0]["values"] if v is not None]
        net = next(v for v in ex["net"]["values"] if v is not None)
        self.assertAlmostEqual(sum(legs), net, places=5)
        m = lambda row: row["recurring_operating_income"] / row["revenue"] * 100
        self.assertAlmostEqual(net, m(block["current"]) - m(block["prior"]), places=5)
        # the bridge is the half the page's other half-year charts end on
        self.assertEqual(block["current"]["revenue"], self.st["half_group"]["revenue"]["values"][-1])
        if legs[0] < 0 and net > 0:
            self.assertIn("被两项费用率抵掉还有余", ex["title"])
            self.assertIn("全部来自费用", ex["note"])

    def test_the_revenue_bridge_closes_on_the_group_change(self) -> None:
        ex = self.by_ref["EX_Q2_BRIDGE"]
        legs = [v for v in ex["stacks"][0]["values"] if v is not None]
        net = next(v for v in ex["net"]["values"] if v is not None)
        g = self.st["new_grid"]
        quarters = g["quarters"]
        self.assertEqual(quarters[-1], self.st["long_quarters"][-1])
        year, number = quarters[-1][:4], quarters[-1][-1]
        now, ago = len(quarters) - 1, quarters.index(f"{int(year) - 1}Q{number}")
        self.assertAlmostEqual(sum(legs), net, places=6)
        self.assertEqual(net, g["revenue_eur_m"]["total"][now] - g["revenue_eur_m"]["total"][ago])
        self.assertTrue(all(v != 0 for v in legs), "a zero leg draws nothing")
        self.assertEqual(ex["xlabels"][-1], f"Q{number} 收入同比变动")
        self.assertIn(display_period(quarters[now]), ex["net"]["name"])
        self.assertIn(display_period(quarters[ago]), ex["net"]["name"])

    def test_the_new_grid_halves_are_the_quarters_and_the_group_lines(self) -> None:
        """The half-year segment table is typed from two documents; it has to be the
        two quarters of the new grid added up, the group's half-year lines, and
        Gucci's own half-year line -- three readings it was not copied from."""
        gh = self.st["new_grid_halves"]
        grid = self.st["new_grid"]
        hg, hh = self.st["half_group"], self.st["half_house"]["gucci"]
        for i, half in enumerate(gh["halves"]):
            first = 1 if half.startswith("H1") else 3
            quarters = [grid["quarters"].index(f"{half[-4:]}Q{first}"), grid["quarters"].index(f"{half[-4:]}Q{first + 1}")]
            j = self.st["halves"].index(half)
            with self.subTest(half=half):
                for key in ("fashion_leather_goods", "gucci", "jewelry", "eyewear", "corporate_and_other",
                            "eliminations", "total"):
                    self.assertEqual(gh["revenue_eur_m"][key][i],
                                     sum(grid["revenue_eur_m"][key][q] for q in quarters), key)
                self.assertEqual(gh["revenue_eur_m"]["total"][i], hg["revenue"]["values"][j])
                self.assertEqual(gh["roi_eur_m"]["total"][i], hg["recurring_operating_income"]["values"][j])
                self.assertEqual(gh["roi_eur_m"]["gucci"][i], hh["roi_eur_m"][j])
                # a printed margin can differ from the ratio of two rounded amounts, but
                # by no more than one euro-million of profit over the half's revenue
                for key, printed in gh["margin_printed_pct"].items():
                    rev, roi = gh["revenue_eur_m"][key][i], gh["roi_eur_m"][key][i]
                    self.assertLessEqual(abs(printed[i] - roi / rev * 100), 100 / rev + 0.05, (key, printed[i]))

    def test_the_half_segment_bridge_closes_on_the_group_change(self) -> None:
        ex = self.by_ref["EX_H1_SEGMENTS"]
        gh = self.st["new_grid_halves"]
        legs = [v for v in ex["stacks"][0]["values"] if v is not None]
        net = next(v for v in ex["net"]["values"] if v is not None)
        roi = self.st["half_group"]["recurring_operating_income"]["values"]
        self.assertEqual(net, roi[-1] - roi[-3])
        self.assertAlmostEqual(sum(legs), net, places=6)
        self.assertTrue(all(v != 0 for v in legs), "a zero leg draws nothing")
        je = sum(gh["roi_eur_m"][k][-1] - gh["roi_eur_m"][k][-3] for k in ("jewelry", "eyewear"))
        self.assertIn(f"珠宝与眼镜合计 {'+' if je >= 0 else '−'}€{abs(je):,}M", ex["title"])
        self.assertEqual(ex["xlabels"][-1], "经常性营业利润变动")

    def test_the_half_cash_bridge_closes_on_the_operating_cash_flow(self) -> None:
        block = self.st.get("half_cash_bridge")
        if block is None or block["period"] != self.st["halves"][-1]:
            self.assertNotIn("EX_H1_CASH", self.by_ref)
            return
        ex = self.by_ref["EX_H1_CASH"]
        cur, pri = block["current"], block["prior"]
        for row in (cur, pri):
            self.assertEqual(row["cash_flow_before_tax_dividends_interest"] + row["change_in_working_capital"]
                             + row["income_tax_paid"], row["net_cash_from_operating_activities"])
            self.assertEqual(row["net_cash_from_operating_activities"] + row["capex"] + row["disposals"],
                             row["free_cash_flow_from_operations"])
        legs = [v for v in ex["stacks"][0]["values"] if v is not None]
        net = next(v for v in ex["net"]["values"] if v is not None)
        self.assertEqual(net, cur["net_cash_from_operating_activities"] - pri["net_cash_from_operating_activities"])
        self.assertAlmostEqual(sum(legs), net, places=6)
        wcr = cur["change_in_working_capital"] - pri["change_in_working_capital"]
        self.assertEqual("比全部增量还多" in ex["title"], wcr > net > 0)

    def test_the_cmd_line_count_is_recounted(self) -> None:
        ex = self.by_ref["EX_CMD_LINE"] if "EX_CMD_LINE" in self.by_ref else next(
            e for e in self.exhibits if "资本市场日的中期目标" in e["title"])
        line = ex["series"][1]["values"][0]
        margins = ex["series"][0]["values"]
        above = [h for h, m in zip(ex["xlabels"], margins) if m is not None and m > line]
        self.assertIn(f"有 {len(above)} 个高于这条线，最近一次是 {above[-1]}", ex["note"])
        halves = self.st["halves"]
        hg = self.st["half_group"]
        fy25 = sum(hg["recurring_operating_income"]["values"][halves.index(h)] for h in ("H1 2025", "H2 2025")) / \
            sum(hg["revenue"]["values"][halves.index(h)] for h in ("H1 2025", "H2 2025")) * 100
        self.assertAlmostEqual(line, round(2 * fy25, 2), places=6)

    # ── section three: report §8's thresholds ─────────────────────────────────
    TRIGGERS = {"减仓", "警示", "降温", "跟踪"}

    def favourable(self, entry: dict) -> str:
        """The side a line wants, read off the report's comparator and action: an
        action like 减仓 names what sets it off, anything else what is wanted."""
        above = entry["rule"] in ("≥", ">")
        return "up" if above != (entry["gate"] in self.TRIGGERS) else "down"

    def satisfied(self, entry: dict, value: float, threshold: float) -> bool:
        holds = {"≥": value >= threshold, ">": value > threshold,
                 "≤": value <= threshold, "<": value < threshold}[entry["rule"]]
        return not holds if entry["gate"] in self.TRIGGERS else holds

    def test_thresholds_use_units_the_shared_formatter_carries(self) -> None:
        for entry in self.st["next_kpi"]["entries"]:
            with self.subTest(entry=entry["metric"], gate=entry["gate"]):
                self.assertIn(entry["unit"], UNIT_FORMATS)
                self.assertEqual(entry["direction"], self.favourable(entry))
                self.assertNotEqual("threshold" in entry, "threshold_rule" in entry,
                                    "a threshold is a number or a rule, not both and not neither")
                for key in ("item", "quote", "why"):
                    self.assertTrue(entry[key].strip(), key)

    def current_values(self) -> dict:
        """What each threshold is measured against, read from the series here
        rather than through the builder: comparable growth from the latest quarter,
        the half-year margins from the latest half (the recurring margins at the
        one decimal Kering prints, the gross margin -- which it does not print --
        unrounded), net debt from the latest period end."""
        comp = self.st["quarterly_comparable_pct"]
        grid = self.st["new_grid"]["comparable_pct"]
        hg = self.st["half_group"]
        roi, rev, gross = (hg[k]["values"][-1] for k in ("recurring_operating_income", "revenue", "gross_margin"))
        regions = self.st["new_grid_retail_regions"]["gucci"]
        return {
            "group_comparable": comp["group_first_published"][-1],
            "gucci_comparable": comp["gucci"][-1],
            "gucci_retail": regions["total"][-1],
            "gucci_na_retail": regions["north_america"][-1],
            "jewelry_comparable": grid["jewelry"][-1],
            "eyewear_comparable": grid["eyewear"][-1],
            "half_gross_margin": gross / rev * 100,
            "half_recurring_margin": float(round_half_up(roi / rev * 100, 1)),
            "half_eyewear_margin": self.st["new_grid_halves"]["margin_printed_pct"]["eyewear"][-1],
            "net_debt": self.st["net_debt_eur_m"][-1],
        }

    def next_thresholds(self) -> list[tuple[dict, float, float]]:
        """(entry, threshold, current) for every §8 threshold, the rule-stated one
        («H2同比不再下降») worked out here as the gross margin of the half before."""
        hg = self.st["half_group"]
        gross_before = hg["gross_margin"]["values"][-2] / hg["revenue"]["values"][-2] * 100
        values = self.current_values()
        out = []
        for entry in self.st["next_kpi"]["entries"]:
            threshold = entry.get("threshold")
            if threshold is None:
                self.assertEqual(entry["threshold_rule"], "same_half_last_year")
                threshold = gross_before
            out.append((entry, threshold, values[entry["measure"]]))
        return out

    def test_threshold_current_values_are_read_from_the_series(self) -> None:
        """The block types thresholds and reasons only; every current value on
        the page is measured from the series, so a roll cannot leave last
        quarter's reading beside this quarter's threshold."""
        for entry in self.st["next_kpi"]["entries"]:
            self.assertNotIn("current", entry, "a typed current value is last quarter's number waiting to happen")
        table = next(t for t in self.payload["tables"] if t["title"].startswith("下季阈值与当前值"))
        rows = self.next_thresholds()
        self.assertEqual(len(table["rows"]), len(rows))
        for row, (entry, threshold, current) in zip(table["rows"], rows):
            with self.subTest(metric=entry["metric"], gate=entry["gate"]):
                self.assertEqual(row[0], str(entry["row"]))
                self.assertTrue(row[1].startswith(entry["metric"]) and row[1].endswith(f"（{entry['gate']}）"))
                shown = (f"€{current:,.0f}M" if entry["unit"] == "eur_m" else
                         f"{current:.1f}%" if not entry["signed"] else
                         ("0%" if current == 0 else f"{current:+.0f}%").replace("-", "−"))
                self.assertEqual(row[2], shown)
                self.assertEqual(row[5], entry["quote"])
                self.assertEqual(row[6], entry["why"])
                if threshold == 0:
                    self.assertTrue(row[4].startswith("—"))
                else:
                    self.assertEqual(row[4], f"{headroom(entry['direction'], threshold, current):+.1f}%")

    def test_the_headroom_chart_agrees_with_the_audit_table_and_names_its_breach(self) -> None:
        ex = self.by_ref["EX_NEXT_HEADROOM"]
        self.assertIn(ex, self.payload["sections"][2]["exhibits"])
        rows = [(e, t, c) for e, t, c in self.next_thresholds() if t != 0]
        self.assertEqual(len(ex["xlabels"]), len(rows), "a zero threshold has no headroom and stays off the chart")
        for label, (entry, threshold, current) in zip(ex["xlabels"], rows):
            self.assertTrue(label.startswith(entry["metric"]) and label.endswith(f"（{entry['gate']}）"), label)
        self.assertEqual(ex["values"], [round(headroom(e["direction"], t, c), 1) for e, t, c in rows])
        good = [self.satisfied(e, c, t) for e, t, c in rows]
        online = [c == t and not g for (e, t, c), g in zip(rows, good)]
        other = sum(1 for g, o in zip(good, online) if not g and not o)
        title = ex["title"]
        self.assertTrue(title.startswith(f"下季 {len(rows)} 条阈值：{sum(good)} 条已在有利一侧"), title)
        if other:
            self.assertIn(f"{other} 条还在另一侧", title)
        if any(online):
            self.assertIn(f"{sum(online)} 条正好压线", title)
        else:
            self.assertNotIn("压线", title)

    def test_each_measure_with_a_long_line_is_drawn_against_every_threshold_on_it(self) -> None:
        """Section three draws each measure it has a long line for; section one does
        not repeat a measure against exactly the same thresholds, and says where it is."""
        entries = self.st["next_kpi"]["entries"]
        thresholds = {id(e): t for e, t, _ in self.next_thresholds()}
        nexts = {ex["ref"][len("EX_NEXT_"):].lower(): ex for ex in self.payload["sections"][2]["exhibits"]
                 if ex.get("ref", "").startswith("EX_NEXT_") and ex["kind"] == "lines"}
        self.assertTrue(nexts)
        for measure, ex in nexts.items():
            group = [e for e in entries if e["measure"] == measure]
            self.assertTrue(group, measure)
            self.assertEqual([line["values"] for line in ex["series"][1:]],
                             [[round(thresholds[id(e)], 6)] * len(ex["xlabels"]) for e in group])
            self.assertTrue(ex["title"].startswith(f"{ker.MEASURE_NAMES[measure]}：下季阈值 "), ex["title"])
            self.assertIn(ex["xlabels"][0], (ker.compact_quarter(self.st["long_quarters"][0]),
                                             self.st["halves"][0], self.st["balance_dates"][0]))
        prior = self.st["prior_kpi_settlement"]["entries"]
        prior_lines = {ex["ref"][len("EX_PRIOR_"):].lower() for ex in self.payload["sections"][0]["exhibits"]
                       if ex.get("ref", "").startswith("EX_PRIOR_") and ex["kind"] == "lines"}
        headroom_note = self.by_ref["EX_PRIOR_HEADROOM"]["note"]
        for measure in {e["measure"] for e in prior}:
            before = {e["threshold"] for e in prior if e["measure"] == measure}
            after = {thresholds[id(e)] for e in entries if e["measure"] == measure}
            if measure in nexts and before == after:
                self.assertNotIn(measure, prior_lines, f"{measure} is drawn twice against the same lines")
                self.assertIn(f"Exhibit {nexts[measure]['n']}", headroom_note)
            elif measure in nexts or measure in ("half_recurring_margin", "gucci_comparable", "net_debt",
                                                 "group_comparable", "half_gross_margin"):
                self.assertIn(measure, prior_lines, measure)

    def test_every_row_of_section_8_is_either_drawn_or_said_why_not(self) -> None:
        entries = self.st["next_kpi"]["entries"]
        skipped = self.st["next_kpi"]["not_plotted"]
        rows = sorted({e["row"] for e in entries} | {x["row"] for x in skipped})
        self.assertEqual(rows, list(range(1, rows[-1] + 1)), "a row of §8 went missing")
        self.assertFalse({e["row"] for e in entries} & {x["row"] for x in skipped})
        table = next(t for t in self.payload["tables"] if t["title"] == "第 8 节里没有画进图的条目")
        self.assertEqual([row[0] for row in table["rows"]], [str(x["row"]) for x in skipped])
        for row, x in zip(table["rows"], skipped):
            self.assertTrue(x["why"].strip())
            self.assertEqual(row[1:], [x["item"], x["quote"], x["why"]])
        description = self.payload["sections"][2]["description"]
        self.assertIn(f"「关键观察指标」的{ker.cn_count(len(rows))}行", description)
        self.assertIn(f"其余{ker.cn_count(len(skipped))}行", description)

    # ── exhibit structure ────────────────────────────────────────────────────
    def test_exhibits_are_numbered_in_render_order_from_two(self) -> None:
        self.assertEqual([ex["n"] for ex in self.exhibits], list(range(2, len(self.exhibits) + 2)))

    def test_tables_are_numbered_after_the_exhibits_and_carry_the_shared_capex_table(self) -> None:
        tables = self.payload["tables"]
        first = self.exhibits[-1]["n"] + 1
        self.assertEqual([t["n"] for t in tables], list(range(first, first + len(tables))))
        self.assertEqual(sum(1 for t in tables if "跨页对照" in t["title"]), 1)
        for t in tables:
            self.assertEqual(set(t), {"n", "title", "headers", "rows"})
            for row in t["rows"]:
                self.assertEqual(len(row), len(t["headers"]), t["title"])

    def test_every_exhibit_plots_one_point_per_x_label(self) -> None:
        for ex in self.exhibits:
            width = len(ex.get("xlabels") or [])
            self.assertGreater(width, 0)
            named = [("values", ex.get("values"))]
            for key in ("yoy", "line", "net", "bar"):
                if isinstance(ex.get(key), dict):
                    named.append((key, ex[key].get("values")))
            for key in ("groups", "series", "stacks"):
                named += [(f"{key}:{b.get('name')}", b.get("values")) for b in ex.get(key) or []]
            for name, values in named:
                if values is not None:
                    self.assertEqual(len(values), width, f"Ex{ex['n']} {name}")

    def test_every_column_of_every_bar_chart_has_something_to_draw(self) -> None:
        for ex in self.exhibits:
            blocks = (ex.get("groups") or []) + (ex.get("stacks") or [])
            if not blocks:
                continue
            netvals = (ex.get("net") or {}).get("values") or []
            for i, label in enumerate(ex["xlabels"]):
                drawn = [b["values"][i] for b in blocks
                         if isinstance(b["values"][i], (int, float)) and b["values"][i] != 0]
                netv = netvals[i] if i < len(netvals) else None
                self.assertTrue(drawn or isinstance(netv, (int, float)),
                                f"Ex{ex['n']} column {label!r} draws nothing")

    def test_bridges_hand_the_renderer_the_shape_it_reads(self) -> None:
        bridges = [ex for ex in self.exhibits if ex["kind"] == "bridge_bar"]
        # the quarter's revenue bridge always; the half's margin bridge and cash bridge while
        # their blocks are stamped; the segment bridge while the half has a year-ago half
        halves = self.st["new_grid_halves"]["halves"]
        year_ago = f"{halves[-1][:2]} {int(halves[-1][-4:]) - 1}"
        self.assertEqual(len(bridges), 1 + ("half_bridge" in self.st) + ("half_cash_bridge" in self.st)
                         + (year_ago in halves))
        for ex in bridges:
            self.assertIsInstance(ex["net"], dict)
            self.assertTrue(ex["net"].get("name"))
            self.assertEqual(sum(1 for v in ex["net"]["values"] if isinstance(v, (int, float))), 1)

    def test_the_single_gs_bar_carries_a_yoy_line_and_no_average(self) -> None:
        bars = [ex for ex in self.exhibits if ex["kind"] == "gs_bar"]
        self.assertEqual(len(bars), 1)
        self.assertTrue(bars[0]["yoy"]["values"])
        self.assertNotIn("avg12", bars[0])
        self.assertTrue(all(v >= 0 for v in bars[0]["values"]), "a negative gs_bar draws off the canvas")

    def test_the_stacked_dual_declares_its_ceiling_inside_the_line(self) -> None:
        for ex in self.exhibits:
            if ex["kind"] != "stacked_dual":
                continue
            self.assertEqual(ex["line"]["ymax"], 100)
            self.assertNotIn("ymax", {k for k in ex if k != "line"})
            self.assertLessEqual(max(v for v in ex["line"]["values"] if v is not None), 100)

    def test_long_axes_thin_their_labels(self) -> None:
        for ex in self.exhibits:
            if len(ex.get("xlabels") or []) > 30:
                self.assertTrue(ex.get("xstep"), f"Ex{ex['n']} has {len(ex['xlabels'])} labels and no xstep")

    def test_colour_and_formatter_names_are_ones_the_renderer_knows(self) -> None:
        def walk(node):
            if isinstance(node, dict):
                if isinstance(node.get("color"), str):
                    self.assertIn(node["color"], VALID_COLORS)
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
        walk(self.payload)
        for ex in self.exhibits:
            for key in ("fmt", "yfmt", "label_fmt"):
                if ex.get(key):
                    self.assertIn(ex[key], VALID_FORMATS, f"Ex{ex['n']}.{key}")
            for block in (ex.get("line"), ex.get("yoy"), ex.get("bar")):
                if isinstance(block, dict) and block.get("yfmt"):
                    self.assertIn(block["yfmt"], VALID_FORMATS)

    def test_no_placeholder_or_markup_leaks_into_literal_slots(self) -> None:
        for ex in self.exhibits:
            for key in ("title", "note", "src_extra"):
                self.assertNotRegex(ex.get(key) or "", r"\{[A-Z_0-9]+\}", f"Ex{ex['n']}.{key}")
            self.assertNotRegex(ex["title"], r"</?[a-z][a-z0-9]*>", f"Ex{ex['n']} title")
            for label in ex.get("xlabels") or []:
                self.assertNotIn("<", str(label))
        for slot in LITERAL_SLOTS:
            self.assertNotRegex(self.payload[slot], r"</?[a-z][a-z0-9]*>", slot)
        for note in self.payload["notes"]:
            self.assertNotRegex(note, r"</?[a-z][a-z0-9]*>")
        for section in self.payload["sections"]:
            for key in ("title", "description"):
                self.assertNotRegex(section[key], r"</?[a-z][a-z0-9]*>")
        self.assertNotIn("**", json.dumps(self.payload, ensure_ascii=False))

    # ── sourcing ─────────────────────────────────────────────────────────────
    def test_no_link_on_this_page_points_at_edgar(self) -> None:
        urls = re.findall(r'href="([^"]+)"', json.dumps(self.payload, ensure_ascii=False))
        urls += [s["url"] for s in self.payload["source_links"]]
        urls.append(self.payload["source_url"])
        self.assertGreaterEqual(len(urls), 20)
        for url in urls:
            self.assertNotIn("sec.gov", url)

    def test_sources_are_official_https_kering_links(self) -> None:
        for s in self.payload["source_links"]:
            self.assertTrue(s["url"].startswith("https://www.kering.com/"), s["url"])
            self.assertTrue(s["label"].startswith("Kering "), s["label"])

    def test_the_only_dollars_on_the_page_are_the_shared_cross_page_table(self) -> None:
        shared = next(t for t in self.payload["tables"] if "跨页对照" in t["title"])
        self.assertRegex(json.dumps(shared, ensure_ascii=False), r"US\$|\$\d")
        rest = {k: v for k, v in self.payload.items() if k != "tables"}
        rest["tables"] = [t for t in self.payload["tables"] if t is not shared]
        self.assertNotRegex(json.dumps(rest, ensure_ascii=False), r"US\$|\$\d")

    def test_the_guidance_slot_is_empty(self) -> None:
        self.assertIsNone(self.payload["guidance"])

    # ── payload, registry, home card ─────────────────────────────────────────
    def test_the_quarter_the_page_reports_is_the_last_one_in_the_series(self) -> None:
        quarter, half = self.st["long_quarters"][-1], self.st["halves"][-1]
        self.assertEqual(self.payload["latest"]["disclosed_period_label"], display_period(quarter))
        self.assertEqual(self.payload["latest"]["full_financial_period_label"], half)
        self.assertEqual(self.payload["title"], f"Kering（KER.PA）：{display_period(quarter)} / {half} 季报仪表盘")
        # the latest half is the one the latest quarter's year has reached: Q1 still
        # stands on last year's H2, Q2 and Q3 on this year's H1, Q4 on this year's H2
        year, number = int(quarter[:4]), int(quarter[-1])
        self.assertEqual(half, {1: f"H2 {year - 1}", 2: f"H1 {year}", 3: f"H1 {year}", 4: f"H2 {year}"}[number])
        self.assertEqual(self.st["balance_dates"][-1][:4], half[-4:])
        self.assertEqual(len(self.st["balance_dates"]), len(self.st["halves"]))

    def test_published_payload_and_shell(self) -> None:
        self.assertEqual(js_payload(ROOT / "data" / "ker.js", "window.DASH"), self.payload)
        shell = (ROOT / "ker" / "index.html").read_text(encoding="utf-8")
        self.assertIn("../data/ker.js", shell)
        self.assertIn("KER.PA", shell)

    def test_the_roster_entry_matches_the_payload(self) -> None:
        entry = next(e for e in ENTRIES if e["slug"] == "ker")
        self.assertEqual(entry["ticker"], self.payload["company"]["ticker"])
        self.assertEqual(entry["group"], self.payload["company"]["group"])
        self.assertNotIn("本站按自然年季度标注", entry["cadence_label"])
        self.assertIn("半年", entry["cadence_label"])

    def test_the_home_page_card_matches_the_payload(self) -> None:
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        card = home.split('href="ker/"', 1)[1].split("</a>", 1)[0]
        self.assertIn(self.payload["latest"]["release_date"], card)
        self.assertIn(self.payload["latest"]["disclosed_period_label"], card)
        self.assertIn("KER.PA", card)
        staging = json.loads(ker.STAGING_PATH.read_text(encoding="utf-8"))
        self.assertIn(" · ".join(ker.headline_metrics(staging)), card)


def text_of(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def composed(payload: dict) -> str:
    """The prose the builder composes. The threshold reasons in `next_kpi` are the
    quarter's own words, typed with the roll, and sit only in the tables."""
    return text_of({key: value for key, value in payload.items() if key != "tables"})


def with_every_block(source: dict) -> dict:
    """The series with every optional one-release block present and stamped for
    the series' own periods.

    A quarter's blocks come and go with the quarter -- a first-quarter series has
    no half-year bridge and no net-debt story -- so the tests below synthesise the
    ones this series does not carry (from its own figures, with placeholder words)
    instead of depending on which quarter the page happens to be on.
    """
    st = copy.deepcopy(source)
    quarter, half = st["long_quarters"][-1], st["halves"][-1]
    stamp = display_period(quarter)
    half_doc = (f"KER_H1_{half[-4:]}_results_release" if half.startswith("H1")
                else f"KER_FY_{half[-4:]}_results_release")
    st.setdefault("outlook", {"period": stamp, "doc": ker.release_doc(quarter), "has_figures": False,
                              "quote": "a placeholder outlook with no figures"})
    st.setdefault("corpus_audit", {"period": stamp, "double_read": True, "reprint_census": True})
    st.setdefault("net_debt_story", {"period": half, "doc": half_doc, "headline": "测试用的净负债说明",
                                     "note": "测试用的净负债注释。"})
    st.setdefault("report_gaps", {"period": stamp, "text": "测试用的一句交代：这条结论只在电话会上。"})

    def cash(wcr: int) -> dict:
        row = {"cash_flow_before_tax_dividends_interest": 1000, "change_in_working_capital": wcr,
               "income_tax_paid": -100, "capex": -200, "disposals": 50}
        row["net_cash_from_operating_activities"] = 900 + wcr
        row["free_cash_flow_from_operations"] = row["net_cash_from_operating_activities"] - 150
        row["fcf_ex_real_estate_and_gucci_beauty"] = row["free_cash_flow_from_operations"] - 50
        return row

    st.setdefault("half_cash_bridge", {"period": half, "compare": st["halves"][-3], "doc": half_doc,
                                       "fcf_ex_doc": half_doc, "current": cash(300), "prior": cash(-100)})
    if "half_bridge" not in st:
        hg = st["half_group"]

        def statement(i: int) -> dict:
            revenue, gross, roi = (hg[k]["values"][i] for k in ("revenue", "gross_margin",
                                                                "recurring_operating_income"))
            personnel = -round((gross - roi) * 0.3)
            return {"revenue": revenue, "gross_margin": gross, "personnel_expenses": personnel,
                    "other_recurring_operating_income_expenses": roi - gross - personnel,
                    "recurring_operating_income": roi}

        st["half_bridge"] = {"period": half, "compare": st["halves"][-3], "prior_restated": "",
                             "doc": half_doc, "current": statement(-1), "prior": statement(-3)}
    return st


def set_half(d: dict, key: str, value: float) -> None:
    """Change the latest half's figure in both places that must agree on it."""
    d["half_group"][key]["values"][-1] = value
    d["half_bridge"]["current"][key] = value


def sync_grid_halves(d: dict) -> None:
    """After a case rewrites the group's half-year lines, carry the change into the
    new-grid half table -- whose totals the builder holds to those lines -- through
    the corporate line, so the segments still add up."""
    gh = d["new_grid_halves"]
    hg = d["half_group"]
    for i, half in enumerate(gh["halves"]):
        if half not in d["halves"]:
            continue
        j = d["halves"].index(half)
        for key, line in (("revenue_eur_m", "revenue"), ("roi_eur_m", "recurring_operating_income")):
            gap = hg[line]["values"][j] - gh[key]["total"][i]
            gh[key]["total"][i] += gap
            gh[key]["corporate_and_other"][i] += gap


class KerRollTest(unittest.TestCase):
    """What a roll has to change in `series/ker.json`, and what the page does when it does not.

    Nine blocks describe one release. `next_kpi`, `outlook`, `corpus_audit`,
    `report_gaps`, `followup_closure` and `prior_kpi_settlement` are stamped with the
    quarter (the last two also name the quarter whose questions and thresholds they
    settle); `half_bridge`, `half_cash_bridge` and `net_debt_story` with the half,
    because a first- or third-quarter release prints no profit and leaves the last
    half standing. A block stamped for another period stops the build; an absent
    optional one takes its chart or its sentences with it. Every case below first
    puts the series into the state it tests -- a block present, a claim true -- so
    the file holds whichever quarter the series is on.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads(ker.STAGING_PATH.read_text(encoding="utf-8"))
        cls.full = with_every_block(cls.source)
        cls.payload = ker.build_payload(cls.full)
        cls.blob = text_of(cls.payload)

    def test_a_block_stamped_with_another_period_stops_the_build(self) -> None:
        for key, stale_period in (("next_kpi", "Q1 1999"), ("outlook", "Q1 1999"), ("corpus_audit", "Q1 1999"),
                                  ("followup_closure", "Q1 1999"), ("prior_kpi_settlement", "Q1 1999"),
                                  ("report_gaps", "Q1 1999"), ("half_cash_bridge", "H1 1999"),
                                  ("half_bridge", "H1 1999"), ("net_debt_story", "H1 1999")):
            stale = copy.deepcopy(self.full)
            stale[key]["period"] = stale_period
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    ker.build_payload(stale)
        bare = copy.deepcopy(self.full)
        del bare["next_kpi"]
        with self.assertRaisesRegex(ValueError, "`next_kpi` is missing"):
            ker.build_payload(bare)
        unknown = copy.deepcopy(self.full)
        unknown["next_kpi"]["entries"][0]["measure"] = "not_a_measure"
        with self.assertRaisesRegex(ValueError, "does not know how to measure"):
            ker.build_payload(unknown)
        orphan = copy.deepcopy(self.full)
        quarter_doc = ker.release_doc(orphan["long_quarters"][-1])
        orphan["sources"] = [item for item in orphan["sources"] if item["doc"] != quarter_doc]
        self.assertLess(len(orphan["sources"]), len(self.full["sources"]))
        with self.assertRaisesRegex(ValueError, "sources"):
            ker.build_payload(orphan)
        drift = copy.deepcopy(self.full)
        drift["half_bridge"]["current"]["revenue"] += 1
        with self.assertRaisesRegex(ValueError, "half_bridge"):
            ker.build_payload(drift)
        lagging = copy.deepcopy(self.full)
        del lagging["half_bridge"], lagging["net_debt_story"]
        for block in lagging["half_group"].values():
            for key in ("values", "flag", "src", "basis"):
                block[key] = block[key][:-1]
        lagging["halves"] = lagging["halves"][:-1]
        with self.assertRaisesRegex(ValueError, "release carries"):
            ker.build_payload(lagging)
        # last quarter's questions and thresholds have to be last quarter's
        for key in ("followup_closure", "prior_kpi_settlement"):
            wrong = copy.deepcopy(self.full)
            wrong[key]["set_in"] = "Q1 1999"
            with self.subTest(block=key, case="set_in"):
                with self.assertRaisesRegex(ValueError, "last quarter was"):
                    ker.build_payload(wrong)
        undeclared = copy.deepcopy(self.full)
        undeclared["followup_closure"]["items"][0]["label"] = "不在清单里的类"
        with self.assertRaisesRegex(ValueError, "does not declare"):
            ker.build_payload(undeclared)
        # a measured value typed beside its threshold is a second copy; an unmeasured
        # one with no source is a number from nowhere
        entries = self.full["prior_kpi_settlement"]["entries"]
        measured = next(i for i, e in enumerate(entries) if e["measure"] == "net_debt")
        typed = copy.deepcopy(self.full)
        typed["prior_kpi_settlement"]["entries"][measured]["actual"] = 1
        with self.assertRaisesRegex(ValueError, "remove its typed actual"):
            ker.build_payload(typed)
        unmeasured = next(i for i, e in enumerate(entries) if "actual" in e)
        sourceless = copy.deepcopy(self.full)
        del sourceless["prior_kpi_settlement"]["entries"][unmeasured]["source"]
        with self.assertRaisesRegex(ValueError, "no source"):
            ker.build_payload(sourceless)
        behind = copy.deepcopy(self.full)
        regions = behind["new_grid_retail_regions"]
        regions["quarters"] = regions["quarters"][:-1]
        for values in regions["gucci"].values():
            values.pop()
        with self.assertRaisesRegex(ValueError, "new_grid_retail_regions"):
            ker.build_payload(behind)
        # the next quarter's thresholds: measured, never typed; a rule the page can work
        # out or nothing; a direction that agrees with the report's own comparator
        typed_now = copy.deepcopy(self.full)
        typed_now["next_kpi"]["entries"][0]["current"] = 1
        with self.assertRaisesRegex(ValueError, "types a current value"):
            ker.build_payload(typed_now)
        ruled = copy.deepcopy(self.full)
        rule_entry = next(e for e in ruled["next_kpi"]["entries"] if "threshold_rule" in e)
        rule_entry["threshold_rule"] = "a_rule_nobody_wrote"
        with self.assertRaisesRegex(ValueError, "no way to compute"):
            ker.build_payload(ruled)
        for key in ("next_kpi", "prior_kpi_settlement"):
            flipped = copy.deepcopy(self.full)
            entry = flipped[key]["entries"][0]
            entry["direction"] = "down" if entry["direction"] == "up" else "up"
            with self.subTest(block=key, case="direction"):
                with self.assertRaisesRegex(ValueError, "wants"):
                    ker.build_payload(flipped)
        # the new-grid half table is held to the group's own half-year lines
        drifted = copy.deepcopy(self.full)
        drifted["new_grid_halves"]["roi_eur_m"]["total"][-1] += 1
        with self.assertRaisesRegex(ValueError, "new_grid_halves"):
            ker.build_payload(drifted)
        unbalanced = copy.deepcopy(self.full)
        unbalanced["half_cash_bridge"]["current"]["income_tax_paid"] -= 1
        with self.assertRaisesRegex(ValueError, "do not add up"):
            ker.build_payload(unbalanced)

    def test_a_period_without_a_story_leaves_it_out(self) -> None:
        full = self.full
        cases = {
            "outlook": ("的展望段落", full["outlook"]["quote"]),
            "half_bridge": ("EX_H1_BRIDGE", "三项之差相加恰好等于利润率之差"),
            "net_debt_story": (full["net_debt_story"]["headline"], full["net_debt_story"]["note"]),
            "corpus_audit": ("每一次被后续公告重印都与首次公布相同", "两个互不知情的转录者",
                             "与首次公布不同的重印")
                            + (("例外是后来接入的",) if full["corpus_audit"].get("single_read") else ()),
            "followup_closure": ("条待验证问题：", "待验证问题的闭环", "条问题闭环到哪一步"),
            "prior_kpi_settlement": ("条量化阈值：", "上季量化阈值的结算", "上季加仓线",
                                     "条阈值落在哪一侧"),
            "half_cash_bridge": ("EX_H1_CASH", "经营现金流变动", "<span>现金</span>"),
            "report_gaps": (full["report_gaps"]["text"],),
        }
        for key, texts in cases.items():
            bare = copy.deepcopy(full)
            del bare[key]
            payload = ker.build_payload(bare)
            after = text_of(payload)
            for text in texts:
                with self.subTest(block=key, text=text):
                    self.assertIn(text, self.blob)
                    self.assertNotIn(text, after)
            numbers = [ex["n"] for section in payload["sections"] for ex in section["exhibits"]]
            self.assertEqual(numbers, list(range(2, 2 + len(numbers))))
            self.assertNotIn("{EX_", after)
        bare = copy.deepcopy(full)
        del bare["half_bridge"]
        self.assertIn("上年同期", self.payload["headline"])
        self.assertNotIn("上年同期", ker.build_payload(bare)["headline"])
        # the reprint itself is history, not census: it stays when the census goes
        bare = copy.deepcopy(full)
        del bare["corpus_audit"]
        first = full["reprint_exceptions"][0]
        self.assertIn(f"收入首次公布为 {first['first_published']:g} 百万欧元", text_of(ker.build_payload(bare)))
        # a brief with one story fewer says so
        bare = copy.deepcopy(full)
        del bare["half_bridge"]
        stories = self.payload["brief"].count("<article>")
        self.assertIn(f"本季{ker.cn_count(stories)}条主线", self.payload["brief"])
        self.assertIn(f"本季{ker.cn_count(stories - 1)}条主线", ker.build_payload(bare)["brief"])

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        """Make each "first / all / only / lowest" claim true in the data, then
        break it once: the sentence that made it must go. A sentence that survived
        this would be a remembered claim, not a computed one."""
        comp = lambda d: d["quarterly_comparable_pct"]
        grid = lambda d: d["new_grid"]

        def group_back(d):
            c = comp(d)["group_first_published"]
            c[-3], c[-2], c[-1] = 3, -1, 2
            comp(d)["gucci"][-1] = -2

        def gucci_run(d):
            g = comp(d)["gucci"]
            g[-2], g[-1] = -3, -2

        def grid_gucci_negative(d):
            g = grid(d)["comparable_pct"]["gucci"]
            g[:] = [-1] * len(g)

        def jewelry_run(d):
            j = grid(d)["comparable_pct"]["jewelry"]
            j[-2] = j[-1] = 15

        def gross_at_low(d):
            hg = d["half_group"]
            rates = [g / r * 100 for g, r in zip(hg["gross_margin"]["values"], hg["revenue"]["values"])]
            set_half(d, "gross_margin", round(hg["revenue"]["values"][-1] * (min(rates[2:-1]) - 1) / 100))

        def gross_off_low(d):
            set_half(d, "gross_margin", round(d["half_group"]["revenue"]["values"][-1] * 0.8))

        def previous_half_lowest(d):
            d["half_group"]["recurring_operating_income"]["values"][-2] = 1

        def previous_half_not_lowest(d):
            hg = d["half_group"]
            hg["recurring_operating_income"]["values"][-2] = round(hg["revenue"]["values"][-2] * 0.5)

        def gucci_falls(d):
            ann = d["annual_house"]["gucci"]
            rev, roi = ann["revenue_eur_m"], ann["roi_eur_m"]
            margins = [r / v * 100 for r, v in zip(roi, rev)]
            after = max(next(i for i, v in enumerate(rev) if v >= 10000),
                        next(i for i, m in enumerate(margins) if m >= 40))
            for i in range(after + 1, len(rev)):
                rev[i] = rev[i - 1] - 100
                roi[i] = round(rev[i] * (roi[i - 1] / rev[i - 1] * 100 - 1) / 100)

        def gucci_recovers(d):
            ann = d["annual_house"]["gucci"]
            ann["revenue_eur_m"][-1] = ann["revenue_eur_m"][-2] + 100

        def net_debt_down_from_high(d):
            nd = d["net_debt_eur_m"]
            nd[-1] = max(nd[:-1]) - 1

        def net_debt_at_high(d):
            nd = d["net_debt_eur_m"]
            nd[-1] = max(nd) + 1000

        def eyewear_alone(d):
            ey = d["targets_2022"]["eyewear_fy2025"]
            ey["roi_eur_m"] = round(ey["revenue_eur_m"] * 0.2)

        def eyewear_below(d):
            ey = d["targets_2022"]["eyewear_fy2025"]
            ey["roi_eur_m"] = round(ey["revenue_eur_m"] * 0.1)

        def revenue_back(d):
            g = grid(d)
            quarters, rev = g["quarters"], g["revenue_eur_m"]
            ago = lambda i: quarters.index(f"{int(quarters[i][:4]) - 1}Q{quarters[i][-1]}")
            rev["total"][-1] = rev["total"][ago(-1)] + 26
            rev["gucci"][-1] = rev["gucci"][ago(-1)] - 1
            if f"{int(quarters[-2][:4]) - 1}Q{quarters[-2][-1]}" in quarters:
                rev["total"][-2] = rev["total"][ago(-2)] - 1

        def revenue_down(d):
            g = grid(d)
            quarters, rev = g["quarters"], g["revenue_eur_m"]
            rev["total"][-1] = rev["total"][quarters.index(f"{int(quarters[-1][:4]) - 1}Q{quarters[-1][-1]}")] - 200

        def one_reprint(d):
            d["reprint_exceptions"] = d["reprint_exceptions"][:1]

        def second_reprint(d):
            d["reprint_exceptions"].append(dict(d["reprint_exceptions"][0], period="2021Q4",
                                                first_published=735.0, reprinted=736))

        def extremes_move(d):
            c = comp(d)
            c["group_first_published"][d["long_quarters"].index("2020Q2")] = -10
            c["bottega_veneta"][d["long_quarters"].index("2020Q2")] = 0

        def bottega_negative_lately(d):
            bv = comp(d)["bottega_veneta"]
            end = max(i for i, v in enumerate(bv) if v is not None) + 1
            for i in range(end - 12, end):
                bv[i] = -1

        def costs_carry_margin(d):
            b = d["half_bridge"]
            cur, prior = b["current"], b["prior"]
            revenue = cur["revenue"]
            gross = round(revenue * (prior["gross_margin"] / prior["revenue"] - 0.01))
            roi = round(revenue * (prior["recurring_operating_income"] / prior["revenue"] + 0.01))
            personnel = -round((gross - roi) * 0.3)
            cur.update(gross_margin=gross, recurring_operating_income=roi, personnel_expenses=personnel,
                       other_recurring_operating_income_expenses=roi - gross - personnel)
            d["half_group"]["gross_margin"]["values"][-1] = gross
            d["half_group"]["recurring_operating_income"]["values"][-1] = roi

        def gross_carries_margin(d):
            costs_carry_margin(d)
            cur, prior = d["half_bridge"]["current"], d["half_bridge"]["prior"]
            gross = round(cur["revenue"] * (prior["gross_margin"] / prior["revenue"] + 0.02))
            cur["other_recurring_operating_income_expenses"] -= gross - cur["gross_margin"]
            set_half(d, "gross_margin", gross)

        regions = lambda d: d["new_grid_retail_regions"]["gucci"]

        def one_region_up(d):
            for key, values in regions(d).items():
                values[-1] = 9 if key == "north_america" else -5
                values[-2] = values[-1] - 3

        def second_region_up(d):
            regions(d)["japan"][-1] = 2

        def one_region_worse(d):
            r = regions(d)["western_europe"]
            r[-1] = r[-2] - 1

        def a_warning_line_hit(d):
            gucci = comp(d)["gucci"]
            gucci[-1] = -9

        def every_buy_line_reached(d):
            for entry in d["prior_kpi_settlement"]["entries"]:
                if "actual" in entry:
                    entry["actual"] = max(entry["actual"], entry["threshold"]) + 1
            d["net_debt_eur_m"][-1] = 2900.0
            regions(d)["north_america"][-1] = 9

        def cash_led_by(working_capital_share: float):
            def edit(d):
                cur, pri = d["half_cash_bridge"]["current"], d["half_cash_bridge"]["prior"]
                net = 100
                cur["net_cash_from_operating_activities"] = pri["net_cash_from_operating_activities"] + net
                cur["change_in_working_capital"] = pri["change_in_working_capital"] + round(net * working_capital_share)
                cur["income_tax_paid"] = pri["income_tax_paid"]
                cur["cash_flow_before_tax_dividends_interest"] = (cur["net_cash_from_operating_activities"]
                                                                  - cur["change_in_working_capital"]
                                                                  - cur["income_tax_paid"])
                cur["free_cash_flow_from_operations"] = (cur["net_cash_from_operating_activities"]
                                                         + cur["capex"] + cur["disposals"])
            return edit

        def segments_eaten(d):
            """Jewelry and eyewear each gain more than the group's whole change, and the
            corporate line takes it back; the totals -- held to the group's lines -- stay."""
            gh = d["new_grid_halves"]["roi_eur_m"]
            net = gh["total"][-1] - gh["total"][-3]
            step = abs(net) + 5
            gh["jewelry"][-1] = gh["jewelry"][-3] + step
            gh["eyewear"][-1] = gh["eyewear"][-3] + step
            gh["eliminations"][-1] = gh["eliminations"][-3]
            gh["corporate_and_other"][-1] = gh["corporate_and_other"][-3] - (2 * step - net) - 5
            gh["fashion_leather_goods"][-1] = gh["total"][-1] - sum(
                gh[k][-1] for k in ("jewelry", "eyewear", "corporate_and_other", "eliminations"))

        def segments_not_eaten(d):
            gh = d["new_grid_halves"]["roi_eur_m"]
            for k in ("jewelry", "eyewear"):
                gain = gh[k][-1] - gh[k][-3]
                gh[k][-1] -= gain + 1
                gh["fashion_leather_goods"][-1] += gain + 1

        def margin_on_the_line(d):
            hg = d["half_group"]
            printed = float(round_half_up(hg["recurring_operating_income"]["values"][-1]
                                          / hg["revenue"]["values"][-1] * 100, 1))
            for entry in d["next_kpi"]["entries"]:
                if entry["measure"] == "half_recurring_margin" and entry["rule"] == ">":
                    entry["threshold"] = printed

        def margin_off_the_line(d):
            revenue = d["half_group"]["revenue"]["values"][-1]
            ceiling = max(e["threshold"] for e in d["next_kpi"]["entries"]
                          if e["measure"] == "half_recurring_margin" and e["rule"] == ">")
            set_half(d, "recurring_operating_income", round(revenue * (ceiling + 0.1) / 100) + 1)

        noop = lambda d: None
        halves = len(self.full["halves"])
        cases = {
            "group back above zero": (group_back, lambda d: comp(d)["group_first_published"].__setitem__(-1, -1),
                                      ("之后第一次为正", "集团转正了", "集团回到增长")),
            "Gucci run": (gucci_run, lambda d: comp(d)["gucci"].__setitem__(-1, 1),
                          ("个季度为负（本季", "起每一季为负", "个季度为负；")),
            "Gucci negative on the whole grid": (grid_gucci_negative,
                                                 lambda d: grid(d)["comparable_pct"]["gucci"].__setitem__(0, 1),
                                                 ("季全负，珠宝",)),
            "jewelry run": (jewelry_run, lambda d: grid(d)["comparable_pct"]["jewelry"].__setitem__(-1, 5),
                            ("起两位数",)),
            "gross margin at its low": (gross_at_low, gross_off_low, ("以来最低",)),
            "previous half the lowest": (previous_half_lowest, previous_half_not_lowest,
                                         (f"%，也是这 {halves} 个半年里最低的",)),
            "Gucci falls after its peak years": (gucci_falls, gucci_recovers, ("之后两条线一起往下走",)),
            "net debt off its high": (net_debt_down_from_high, net_debt_at_high, ("再降回来",)),
            "eyewear alone on target": (eyewear_alone, eyewear_below, ("只有眼镜的利润率站在目标上",)),
            "reported revenue back": (revenue_back, revenue_down, ("本季报告口径收入多了", "报告口径收入回到增长")),
            "one reprint": (one_reprint, second_reprint, ("唯一一处与首次公布不同的重印",)),
            "extremes in 2020Q2 and 2021Q2": (noop, extremes_move, ("是门店关闭，2021 年二季度的", "三个品牌同时出现")),
            "Bottega mostly positive lately": (noop, bottega_negative_lately, ("近年多为正",)),
            "costs carry the margin": (costs_carry_margin, gross_carries_margin,
                                       ("利润率的改善全部来自费用", "但毛利率低了", "利润率改善来自费用")),
            "one region above zero": (one_region_up, second_region_up, ("是唯一为正的地区",)),
            "every region better than last quarter": (one_region_up, one_region_worse,
                                                      ("个地区都比上季好",)),
            "no warning line touched": (noop, a_warning_line_hit, ("一条都没碰到",)),
            "a buy line missed": (noop, every_buy_line_reached, ("没够着的加仓线", "条没够着")),
            "cash led by working capital": (cash_led_by(1.5), cash_led_by(0.1),
                                            ("比全部增量还多", "增量全部来自营运资金", "经营现金流的增量全靠营运资金")),
            "jewelry and eyewear eaten": (segments_eaten, segments_not_eaten, ("珠宝与眼镜多赚的", "）吃掉")),
            "a margin on the line": (margin_on_the_line, margin_off_the_line, ("正好压线", "<b>压线的：")),
        }
        for name, (make_true, make_false, claims) in cases.items():
            held = copy.deepcopy(self.full)
            make_true(held)
            sync_grid_halves(held)
            before = composed(ker.build_payload(held))
            broken = copy.deepcopy(held)
            make_false(broken)
            sync_grid_halves(broken)
            after = composed(ker.build_payload(broken))
            for claim in claims:
                with self.subTest(case=name, claim=claim):
                    self.assertIn(claim, before)
                    self.assertNotIn(claim, after)

    def test_the_next_quarter_rolls_without_touching_the_code(self) -> None:
        """Append the next quarter -- with invented figures; this is a shape test --
        and the page must build. A first- or third-quarter release prints revenue
        and nothing else, so the half-year arrays, the margin bridge and the
        net-debt story stay on the last half; a second- or fourth-quarter release
        brings a half with it, and until its stories are written the page leaves
        them out. Only the quarter's own blocks are re-stamped."""
        rolled = copy.deepcopy(self.full)
        last = rolled["long_quarters"][-1]
        year, number = int(last[:4]), int(last[-1])
        nxt = f"{year + (number == 4)}Q{number % 4 + 1}"
        rolled["long_quarters"].append(nxt)
        for block in (rolled["quarterly_revenue_eur_m"], rolled["quarterly_comparable_pct"]):
            for values in block.values():
                values.append(values[-1])
        for values in rolled["quarterly_revenue_src"].values():
            values.append(ker.release_doc(nxt))
        grid = rolled["new_grid"]
        grid["quarters"].append(nxt)
        for block in (grid["revenue_eur_m"], grid["comparable_pct"]):
            for values in block.values():
                values.append(values[-1])
        grid["src"].append(ker.release_doc(nxt))
        regions = rolled["new_grid_retail_regions"]
        regions["quarters"].append(nxt)
        for values in regions["gucci"].values():
            values.append(values[-1])
        regions["src"].append(ker.release_doc(nxt))
        rolled["sources"].append({"doc": ker.release_doc(nxt), "url": "https://www.kering.com/"})
        adds_half = nxt[-1] in "24"
        if adds_half:
            half = f"{'H1' if nxt[-1] == '2' else 'H2'} {nxt[:4]}"
            rolled["halves"].append(half)
            for block in rolled["half_group"].values():
                block["values"].append(block["values"][-1])
                block["flag"].append("printed" if half.startswith("H1") else "D")
                block["src"].append(ker.release_doc(nxt))
                block["basis"].append(block["basis"][-1])
            for house in rolled["half_house"].values():
                for key in ("roi_eur_m", "revenue_eur_m", "flag"):
                    house[key].append(house[key][-1])
            rolled["balance_dates"].append(f"{nxt[:4]}-{'06-30' if half.startswith('H1') else '12-31'}")
            rolled["net_debt_eur_m"].append(rolled["net_debt_eur_m"][-1] + 1)
            rolled["net_debt_src"].append(ker.release_doc(nxt))
            gh = rolled["new_grid_halves"]
            gh["halves"].append(half)
            gh["flag"].append("printed" if half.startswith("H1") else "D")
            gh["src"].append(ker.release_doc(nxt))
            for table in (gh["revenue_eur_m"], gh["roi_eur_m"], gh["margin_printed_pct"]):
                for values in table.values():
                    values.append(values[-1])
            rolled.pop("half_bridge", None)
            rolled.pop("net_debt_story", None)
            rolled.pop("half_cash_bridge", None)
        stamp = display_period(nxt)
        rolled["latest"].update(period=stamp)
        for key in ("next_kpi", "outlook", "corpus_audit", "followup_closure", "prior_kpi_settlement",
                    "report_gaps"):
            if key in rolled:
                rolled[key]["period"] = stamp
        # last quarter's questions and thresholds are now the ones set in the quarter just left
        for key in ("followup_closure", "prior_kpi_settlement"):
            if key in rolled:
                rolled[key]["set_in"] = display_period(last)
        payload = ker.build_payload(rolled)
        self.assertEqual(payload["title"], f"Kering（KER.PA）：{stamp} / {rolled['halves'][-1]} 季报仪表盘")
        refs = [ex.get("ref") for section in payload["sections"] for ex in section["exhibits"]]
        self.assertEqual("EX_H1_BRIDGE" in refs, not adds_half)
        bridge = next(ex for section in payload["sections"] for ex in section["exhibits"]
                      if ex.get("ref") == "EX_Q2_BRIDGE")
        self.assertEqual(bridge["xlabels"][-1], f"Q{nxt[-1]} 收入同比变动")
        year_ago = display_period(f"{int(nxt[:4]) - 1}Q{nxt[-1]}")
        self.assertIn(f"{stamp} 对 {year_ago}", bridge["net"]["name"])
        self.assertIn(f"{stamp} 集团", bridge["note"])
        self.assertEqual(payload["latest"]["disclosed_period_label"], stamp)


class KerChecksTest(unittest.TestCase):
    """The page's quarter against a record keyed separately from the series.

    `_checks` is typed once per quarter from the release itself, with the place each
    figure was read; the builder never reads it (asserted in `test_data_only_roll`).
    What a release prints depends on the quarter: a first- or third-quarter release
    prints revenue only (`q_*`), the first-half release adds the half (`h_*`) and the
    net debt, the full-year release adds the year (`fy_*`, checked against the two
    halves that sum to it) and the net debt. Each group is checked when it is keyed,
    so a roll re-keys `_checks` and this file does not change. Kering prints its
    margins to one decimal and net debt to a tenth of a billion in the text, so
    where the page computes a figure from the series, it has to round to the print.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.st = json.loads(ker.STAGING_PATH.read_text(encoding="utf-8"))
        cls.checks = cls.st["_checks"]
        cls.payload = ker.build_payload(cls.st)
        cls.exhibits = {ex["ref"]: ex for section in cls.payload["sections"] for ex in section["exhibits"]
                        if "ref" in ex}

    def half_margin(self, i: int) -> float:
        hg = self.st["half_group"]
        return hg["recurring_operating_income"]["values"][i] / hg["revenue"]["values"][i] * 100

    def test_the_page_names_the_checked_quarter(self) -> None:
        c = self.checks
        self.assertIn(c["period"], self.payload["title"])
        self.assertIn(f"截至 {c['period_end']}", self.payload["subtitle"])
        self.assertIn(f"发布 {c['release_date']}", self.payload["subtitle"])
        if "half" in c:
            self.assertIn(f"{c['period']} / {c['half']}", self.payload["title"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        c, st = self.checks, self.st
        rev, comp = st["quarterly_revenue_eur_m"], st["quarterly_comparable_pct"]
        self.assertEqual(display_period(st["long_quarters"][-1]), c["period"])
        self.assertEqual(rev["group_first_published"][-1], c["q_revenue_eur_m"])
        self.assertEqual(comp["group_first_published"][-1], c["q_comparable_pct"])
        self.assertEqual(rev["gucci"][-1], c["q_gucci_revenue_eur_m"])
        self.assertEqual(comp["gucci"][-1], c["q_gucci_comparable_pct"])
        grid = st["new_grid"]
        g, gc = grid["revenue_eur_m"], grid["comparable_pct"]
        ago = grid["quarters"].index(f"{int(grid['quarters'][-1][:4]) - 1}Q{grid['quarters'][-1][-1]}")
        self.assertEqual(g["total"][-1], c["q_revenue_eur_m"])
        self.assertEqual(g["total"][ago], c["q_prior_year_revenue_eur_m"])
        self.assertEqual(gc["total"][-1], c["q_comparable_pct"])
        self.assertEqual(g["fashion_leather_goods"][-1], c["q_fashion_leather_goods_eur_m"])
        self.assertEqual(g["gucci"][-1], c["q_gucci_revenue_eur_m"])
        self.assertEqual((g["jewelry"][-1], gc["jewelry"][-1]), (c["q_jewelry_eur_m"], c["q_jewelry_comparable_pct"]))
        self.assertEqual((g["eyewear"][-1], gc["eyewear"][-1]), (c["q_eyewear_eur_m"], c["q_eyewear_comparable_pct"]))
        hg, halves = st["half_group"], st["halves"]
        if "h_revenue_eur_m" in c:
            self.assertEqual(halves[-1], c["half"])
            self.assertEqual(hg["revenue"]["values"][-1], c["h_revenue_eur_m"])
            self.assertEqual(hg["gross_margin"]["values"][-1], c["h_gross_margin_eur_m"])
            self.assertEqual(hg["recurring_operating_income"]["values"][-1], c["h_recurring_operating_income_eur_m"])
            self.assertEqual(hg["revenue"]["values"][-3], c["h_prior_revenue_eur_m"])
            self.assertEqual(hg["recurring_operating_income"]["values"][-3],
                             c["h_prior_recurring_operating_income_eur_m"])
            gucci = st["half_house"]["gucci"]
            self.assertEqual(gucci["revenue_eur_m"][-1], c["h_gucci_revenue_eur_m"])
            self.assertEqual(gucci["roi_eur_m"][-1], c["h_gucci_recurring_operating_income_eur_m"])
        if "fy_revenue_eur_m" in c:
            self.assertTrue(halves[-1].startswith("H2"))
            for key, block in (("fy_revenue_eur_m", "revenue"), ("fy_gross_margin_eur_m", "gross_margin"),
                               ("fy_recurring_operating_income_eur_m", "recurring_operating_income")):
                values = hg[block]["values"]
                self.assertEqual(values[-2] + values[-1], c[key], key)
        if "net_debt_eur_m" in c:
            nd, dates = st["net_debt_eur_m"], st["balance_dates"]
            self.assertEqual(nd[-1], c["net_debt_eur_m"])
            self.assertEqual(nd[dates.index(c["net_debt_compare_date"])], c["net_debt_compare_eur_m"])
        if "outlook_quote" in c:
            self.assertEqual(st["outlook"]["quote"], c["outlook_quote"])
        if "q_gucci_na_retail_comparable_pct" in c:
            regions = st["new_grid_retail_regions"]
            self.assertEqual(regions["quarters"][-1], st["long_quarters"][-1])
            self.assertEqual(regions["gucci"]["north_america"][-1], c["q_gucci_na_retail_comparable_pct"])
            self.assertEqual(regions["gucci"]["total"][-1], c["q_gucci_retail_comparable_pct"])
        if "h_eyewear_recurring_operating_margin_pct" in c:
            gh = st["new_grid_halves"]
            self.assertEqual(gh["halves"][-1], c["half"])
            self.assertEqual(gh["margin_printed_pct"]["eyewear"][-1], c["h_eyewear_recurring_operating_margin_pct"])
        if "h_net_cash_from_operating_activities_eur_m" in c:
            cash = st["half_cash_bridge"]
            self.assertEqual(cash["period"], c["half"])
            self.assertEqual(cash["current"]["net_cash_from_operating_activities"],
                             c["h_net_cash_from_operating_activities_eur_m"])
            self.assertEqual(cash["prior"]["net_cash_from_operating_activities"],
                             c["h_prior_net_cash_from_operating_activities_eur_m"])
            self.assertEqual(cash["current"]["change_in_working_capital"], c["h_change_in_working_capital_eur_m"])
            self.assertEqual(cash["prior"]["change_in_working_capital"], c["h_prior_change_in_working_capital_eur_m"])

    def test_the_report_blocks_are_the_report_reading(self) -> None:
        """What the local analyses decide -- the verdict on each of last quarter's
        questions, the thresholds last quarter set and the ones this quarter sets --
        is typed a second time in `_checks["note"]`, read off the reports
        themselves, so this file holds no report's numbers and a roll edits the
        series only. The report gives no tally of its verdicts, so the reading
        records the count per label."""
        note = self.checks.get("note")
        if note is None:
            for key in ("followup_closure", "prior_kpi_settlement"):
                self.assertNotIn(key, self.st)
            return
        self.assertTrue(note["source"].strip() and note["checked_on"])
        if "followup_closure" in self.st:
            items = self.st["followup_closure"]["items"]
            counts = dict(collections.Counter(item["label"] for item in items))
            self.assertEqual(counts, note["followup"]["counts"])
            self.assertEqual(len(items), note["followup"]["total"])
            title = self.exhibits["EX_CLOSURE"]["title"]
            self.assertIn(f"上季 {note['followup']['total']} 条待验证问题", title)
            for label, count in note["followup"]["counts"].items():
                self.assertIn(f"{count} 条{label}", title)
        if "prior_kpi_settlement" in self.st:
            entries = self.st["prior_kpi_settlement"]["entries"]
            self.assertEqual([{"metric": e["metric"], "measure": e["measure"], "threshold": e["threshold"],
                               "direction": e["direction"], "gate": e["gate"]} for e in entries],
                             note["prior_thresholds"])
            self.assertIn(f"上季 {len(note['prior_thresholds'])} 条量化阈值", self.exhibits["EX_PRIOR_HEADROOM"]["title"])
        kpi = self.st["next_kpi"]
        self.assertEqual([{"row": e["row"], "metric": e["metric"], "measure": e["measure"],
                           "threshold": e.get("threshold", e.get("threshold_rule")),
                           "direction": e["direction"], "gate": e["gate"]} for e in kpi["entries"]],
                         note["next_thresholds"])
        self.assertEqual([x["row"] for x in kpi.get("not_plotted", [])], note["next_rows_not_plotted"])
        rows = {e["row"] for e in kpi["entries"]} | set(note["next_rows_not_plotted"])
        self.assertEqual(len(rows), note["next_rows_total"])
        # every typed threshold is the number its own quoted words carry
        quoted = list(self.st.get("prior_kpi_settlement", {}).get("entries", [])) + [
            e for e in kpi["entries"] if "threshold" in e]
        for e in quoted:
            t = e["threshold"]
            number = (rf"€{t / 1000:g}(\.0)?(B|bn)" if e["unit"] == "eur_m"
                      else rf"(?<![\d.]){abs(t):g}%")
            with self.subTest(quote=e["quote"], threshold=t):
                # 「转正」 says zero in words
                if not (t == 0 and "转正" in e["quote"]):
                    self.assertRegex(e["quote"], number)
                # 「要求」 is the page's word for a row that names no action
                if e["gate"] != "要求":
                    self.assertIn(e["gate"], e["quote"])

    def test_the_rounding_the_page_uses_is_the_companys(self) -> None:
        c = self.checks
        if "h_recurring_operating_margin_pct" in c:
            self.assertEqual(float(round_half_up(self.half_margin(-1), 1)), c["h_recurring_operating_margin_pct"])
            self.assertEqual(float(round_half_up(self.half_margin(-3), 1)),
                             c["h_prior_recurring_operating_margin_pct"])
            self.assertEqual(round(c["h_recurring_operating_margin_pct"]
                                   - c["h_prior_recurring_operating_margin_pct"], 1), c["h_margin_change_pts"])
            gucci = self.st["half_house"]["gucci"]
            self.assertEqual(float(round_half_up(gucci["roi_eur_m"][-1] / gucci["revenue_eur_m"][-1] * 100, 1)),
                             c["h_gucci_recurring_operating_margin_pct"])
        if "net_debt_eur_bn_printed" in c:
            nd, dates = self.st["net_debt_eur_m"], self.st["balance_dates"]
            compare = nd[dates.index(c["net_debt_compare_date"])]
            self.assertEqual(float(round_half_up(nd[-1] / 1000, 1)), c["net_debt_eur_bn_printed"])
            self.assertEqual(float(round_half_up(abs(compare - nd[-1]) / 1000, 1)),
                             c["net_debt_change_eur_bn_printed"])

    def test_the_page_prints_the_checked_figures(self) -> None:
        c = self.checks
        headline = self.payload["headline"]
        self.assertIn(f"本季集团可比增速 {ker.flat_signed(c['q_comparable_pct'])}", headline)
        self.assertIn(f"Gucci {ker.flat_signed(c['q_gucci_comparable_pct'])}", headline)
        self.assertIn(f"Gucci 本季收入 €{c['q_gucci_revenue_eur_m']:,}M", self.exhibits["EX_GUCCI_Q"]["title"])
        bridge = self.exhibits["EX_Q2_BRIDGE"]["note"]
        self.assertIn(f"€{c['q_revenue_eur_m']:,}M", bridge)
        self.assertIn(f"€{c['q_prior_year_revenue_eur_m']:,}M", bridge)
        self.assertIn(f"珠宝本季 {ker.signed(c['q_jewelry_comparable_pct'], 0)}、"
                      f"眼镜 {ker.signed(c['q_eyewear_comparable_pct'], 0)}", self.exhibits["EX_GRID"]["note"])
        table = next(t for t in self.payload["tables"] if t["title"].startswith("下季阈值与当前值"))
        rows = dict(zip((e["measure"] for e in self.st["next_kpi"]["entries"]), table["rows"]))
        if "h_recurring_operating_margin_pct" in c:
            self.assertIn(f"利润率 {c['h_recurring_operating_margin_pct']:.1f}%", headline)
            self.assertIn(f"利润率 {c['h_recurring_operating_margin_pct']:.1f}%",
                          self.exhibits["EX_GROUP_MARGIN"]["title"])
            if "half_recurring_margin" in rows:
                self.assertEqual(rows["half_recurring_margin"][2], f"{c['h_recurring_operating_margin_pct']:.1f}%")
        if "net_debt_eur_m" in c:
            self.assertIn(f"€{c['net_debt_eur_m']:,}M", headline)
            if "net_debt" in rows:
                self.assertEqual(rows["net_debt"][2], f"€{c['net_debt_eur_m']:,}M")
        if "h_eyewear_recurring_operating_margin_pct" in c and "half_eyewear_margin" in rows:
            self.assertEqual(rows["half_eyewear_margin"][2], f"{c['h_eyewear_recurring_operating_margin_pct']:.1f}%")
        if "q_gucci_na_retail_comparable_pct" in c and "gucci_na_retail" in rows:
            self.assertEqual(rows["gucci_na_retail"][2],
                             ker.minus_sign(ker.flat_signed(c["q_gucci_na_retail_comparable_pct"])))
        if "h_net_cash_from_operating_activities_eur_m" in c:
            cash = self.exhibits["EX_H1_CASH"]
            self.assertIn(f"€{c['h_net_cash_from_operating_activities_eur_m']:,}M 对 "
                          f"€{c['h_prior_net_cash_from_operating_activities_eur_m']:,}M", cash["note"])
            swing = c["h_change_in_working_capital_eur_m"] - c["h_prior_change_in_working_capital_eur_m"]
            self.assertIn(f"营运资金变动一项 +€{swing:,}M", cash["title"])


if __name__ == "__main__":
    unittest.main()
