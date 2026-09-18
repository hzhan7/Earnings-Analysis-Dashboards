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
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import ker  # noqa: E402
from build.all import ENTRIES  # noqa: E402
from build.board import UNIT_FORMATS, headroom  # noqa: E402


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
        self.assertEqual(self.st["long_quarters"][last_non_negative + 1], "2023Q3")
        self.assertIn(f"连续 {streak} 个季度为负", self.by_ref["EX_GUCCI_Q"]["title"])
        self.assertIn(f"连续 {streak} 个季度为负", self.payload["headline"])

    def test_the_group_turned_positive_for_the_first_time_since_the_quarter_named(self) -> None:
        comp = self.st["quarterly_comparable_pct"]["group_first_published"]
        self.assertGreater(comp[-1], 0)
        previous_positive = max(i for i in range(len(comp) - 1) if comp[i] > 0)
        self.assertTrue(all(v <= 0 for v in comp[previous_positive + 1:-1]))
        label = ker.compact_quarter(self.st["long_quarters"][previous_positive])
        self.assertIn(f"{label} 之后第一次为正", self.by_ref["EX_GROUP_COMP"]["title"])

    def test_the_margin_bridge_legs_close_exactly(self) -> None:
        ex = self.by_ref["EX_H1_BRIDGE"]
        legs = [v for v in ex["stacks"][0]["values"] if v is not None]
        net = next(v for v in ex["net"]["values"] if v is not None)
        self.assertAlmostEqual(sum(legs), net, places=5)
        is_ = self.st["h1_income_statement"]
        m = lambda row: row["recurring_operating_income"] / row["revenue"] * 100
        self.assertAlmostEqual(net, m(is_["H1 2026"]) - m(is_["H1 2025 restated"]), places=5)
        self.assertLess(legs[0], 0, "the page says gross margin fell")

    def test_the_revenue_bridge_closes_on_the_group_change(self) -> None:
        ex = self.by_ref["EX_Q2_BRIDGE"]
        legs = [v for v in ex["stacks"][0]["values"] if v is not None]
        net = next(v for v in ex["net"]["values"] if v is not None)
        g = self.st["new_grid"]
        i26, i25 = g["quarters"].index("2026Q2"), g["quarters"].index("2025Q2")
        self.assertAlmostEqual(sum(legs), net, places=6)
        self.assertEqual(net, g["revenue_eur_m"]["total"][i26] - g["revenue_eur_m"]["total"][i25])
        self.assertTrue(all(v != 0 for v in legs), "a zero leg draws nothing")

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

    # ── thresholds ───────────────────────────────────────────────────────────
    def test_thresholds_use_units_the_shared_formatter_carries(self) -> None:
        for entry in self.st["next_kpi"]["entries"]:
            self.assertIn(entry["unit"], UNIT_FORMATS, entry["metric"])
            self.assertIn(entry["direction"], ("up", "down"))
            self.assertNotEqual(entry["threshold"], 0)
            self.assertTrue(entry["why"].strip())

    def test_threshold_current_values_are_read_from_the_series(self) -> None:
        cur = {e["metric"]: e["current"] for e in self.st["next_kpi"]["entries"]}
        comp = self.st["quarterly_comparable_pct"]
        grid = self.st["new_grid"]
        self.assertEqual(cur["集团季度可比增速"], comp["group_first_published"][-1])
        self.assertEqual(cur["Gucci 季度可比增速"], comp["gucci"][-1])
        self.assertEqual(cur["珠宝季度可比增速"], grid["comparable_pct"]["jewelry"][-1])
        self.assertEqual(cur["眼镜季度可比增速"], grid["comparable_pct"]["eyewear"][-1])
        self.assertAlmostEqual(cur["半年毛利率（对上年同期重述值）"], self.der["gross_rate"][-1], places=2)
        self.assertAlmostEqual(cur["半年经常性营业利润率（对上年同期重述值）"], self.der["group_margin"][-1], places=2)
        self.assertEqual(cur["期末净负债"], self.st["net_debt_eur_m"][-1])

    def test_the_headroom_chart_agrees_with_the_audit_table_and_names_its_breach(self) -> None:
        ex = next(e for e in self.exhibits if e["kind"] == "diverging_bars")
        entries = self.st["next_kpi"]["entries"]
        self.assertEqual(ex["xlabels"], [e["metric"] for e in entries])
        self.assertEqual(ex["values"], [round(headroom(e["direction"], e["threshold"], e["current"]), 1)
                                        for e in entries])
        breached = [label for label, v in zip(ex["xlabels"], ex["values"]) if v < 0]
        self.assertEqual(breached, ["半年毛利率（对上年同期重述值）"])
        self.assertIn(f"{len(entries)} 条里 {len(entries) - len(breached)} 条在安全侧", ex["title"])

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
        self.assertEqual(len(bridges), 2)
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
        self.assertEqual(self.st["long_quarters"][-1], "2026Q2")
        self.assertEqual(self.st["halves"][-1], "H1 2026")
        self.assertEqual(self.payload["latest"]["disclosed_period_label"], "Q2 2026")
        self.assertEqual(self.payload["latest"]["full_financial_period_label"], "H1 2026")

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


if __name__ == "__main__":
    unittest.main()
