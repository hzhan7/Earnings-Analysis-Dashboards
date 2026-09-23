"""What the Intel page has to keep true.

The page's central object is a guidance record that is complete but not
uniform: an outlook for every quarter since 2016Q1, three revenue forms, a
gross-margin line with a hole where operating margin was guided instead, and an
EPS line that starts a year late. So most of
the weight here is on recounting, independently of the builder, what each
record's title says -- and on the two facts the scoring rests on:

* `test_first_print_and_reprint_differ_only_in_restated_years` -- guidance is
  scored against the non-GAAP figure the quarter's own release printed, because
  the reprint a year later can be on a different definition. That argument is
  only sound while every disagreement between the two readings falls in a year
  a recorded redefinition restated. Recomputed here from the two readings.
* `test_the_guidance_forms_agree_with_the_bounds_and_the_note` -- the revenue
  chart's note describes the runs of outlook forms (a point ± US$500M, a single
  figure, a range) and names any range whose width is not its run's usual one;
  both are recomputed here from the series, so a roll that adds a new form or a
  new width turns the sentence, not this test, into the thing to fix.

The page is rolled by editing `series/intc.json` alone (CLAUDE.md §9), so
nothing below reads a figure out of `build/intc.py`: every expected value is
computed here from the series, or from the payload by another route.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import intc  # noqa: E402
from build.all import ENTRIES  # noqa: E402
from build.board import display_period  # noqa: E402


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    return json.loads(text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0])


def text_of(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def exhibits_of(payload: dict) -> list[dict]:
    return [ex for sec in payload["sections"] for ex in sec["exhibits"]]


def by_ref(payload: dict) -> dict:
    return {ex["ref"]: ex for ex in exhibits_of(payload) if "ref" in ex}


def qlab(q: str) -> str:
    return f"Q{q[5]}'{q[2:4]}"


def next_q(q: str) -> str:
    y, n = int(q[:4]), int(q[5])
    return f"{y + 1}Q1" if n == 4 else f"{y}Q{n + 1}"


VALID_COLORS = {"NAVY", "BLUE", "MBLUE", "GRAY", "GREEN", "RED", "GOLD", "WHITE",
                "GRID", "AXIS", "INK"}
VALID_FORMATS = {"f1", "f0", "f0c", "int", "pct0", "pct1", "pct0z", "pp0", "pp1", "x0",
                 "usd0", "usd1", "usd2", "f2", "f3", "pct2", "usd3", "usd4"}
LITERAL_SLOTS = ("headline", "title", "subtitle", "tracker")
ZERO_FLOORED_KINDS = {"bars_labeled", "gs_bar", "stacked_dual"}
# Every block of the series that describes one quarter (read with stamped_block).
STAMPED_BLOCKS = ("quarter_story", "followup_closure", "prior_kpi_settlement", "thresholds")

# ── what the two research reports say, copied from them ─────────────────────
# These are the reports' facts, not filed figures: the questions last quarter's
# report left and the verdicts this quarter's report wrote in its section 0
# (2026-07-23 INTC Q2 2026 vs Q1 2026 Analysis), and the thresholds last
# quarter's report set in its section 8 (2026-04-30 INTC Q1 2026 vs Q4 2025
# Analysis). A roll replaces them together with the blocks they check.
REPORT_SECTION_ZERO_VERDICTS = ["通过", "未通过，继续追踪", "表面通过、质量未通过", "部分通过",
                                "动能通过、经济性未验证"]
PRIOR_SECTION_EIGHT = {
    # id: (row, warning line, positive line, safe side)
    "dcai_yoy": (1, 15.0, 25.0, "up"),
    "non_gaap_gm": (2, 38.5, 40.0, "up"),
    "foundry_external": (3, 200, 222, "up"),
    "adjusted_fcf": (5, -1.0, 1.0, "up"),
}
PRIOR_SECTION_EIGHT_UNQUANTIFIED_ROWS = [4]


class IntcDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.st = json.loads(intc.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = intc.build_payload(cls.st)
        cls.ex = by_ref(cls.payload)
        cls.P = cls.st["periods"]
        cls.g = cls.st["guidance"]
        cls.inc = cls.st["income_usd_m"]
        cls.ng = cls.st["non_gaap_printed"]

    # ── the axis ─────────────────────────────────────────────────────────────
    def test_the_axis_runs_from_2016q1_to_the_latest_quarter_without_a_gap(self) -> None:
        P = self.P
        self.assertEqual(P[0], "2016Q1")
        for a, b in zip(P, P[1:]):
            ya, qa, yb, qb = int(a[:4]), int(a[5]), int(b[:4]), int(b[5])
            self.assertEqual((yb * 4 + qb) - (ya * 4 + qa), 1, f"{a} -> {b}")
        for key in ("period_ends", "release_dates"):
            self.assertEqual(len(self.st[key]), len(P), key)

    def test_each_quarter_end_is_within_a_week_of_its_calendar_quarter_end(self) -> None:
        """Intel's 52/53-week quarters end on a Saturday near the calendar end;
        the page labels them by calendar quarter, which is only honest while no
        quarter end drifts into a neighbouring month's quarter."""
        for q, end in zip(self.P, self.st["period_ends"]):
            y, n = int(q[:4]), int(q[5])
            month = n * 3
            nominal = date(y, month, 30 if month in (6, 9) else 31)
            got = date.fromisoformat(end)
            with self.subTest(quarter=q):
                self.assertLessEqual(abs((got - nominal).days), 7)
                self.assertEqual(got.weekday(), 5, "Intel quarters end on a Saturday")

    def test_every_release_follows_its_quarter_end(self) -> None:
        for q, end, rel in zip(self.P, self.st["period_ends"], self.st["release_dates"]):
            gap = (date.fromisoformat(rel) - date.fromisoformat(end)).days
            with self.subTest(quarter=q):
                self.assertGreater(gap, 0)
                self.assertLess(gap, 45)

    # ── the guidance record ──────────────────────────────────────────────────
    def test_the_guidance_axis_is_every_quarter_plus_the_next(self) -> None:
        g = self.g
        self.assertEqual(g["quarters"][:len(self.P)], self.P)
        self.assertEqual(len(g["quarters"]), len(self.P) + 1)
        for key, values in g.items():
            if isinstance(values, list):
                self.assertEqual(len(values), len(g["quarters"]), key)
        # each outlook was issued by the release before its quarter ended
        rel = self.st["release_dates"]
        for k, q in enumerate(g["quarters"][1:len(self.P)], start=1):
            self.assertEqual(g["issued_in_release"][k], rel[k - 1], q)

    def test_the_guidance_forms_agree_with_the_bounds_and_the_note(self) -> None:
        """Each recorded form is what its bounds say, and the note names every run."""
        g = self.g
        for q, form, lo, hi in zip(g["quarters"], g["revenue_form"], g["revenue_lo_usd_bn"],
                                   g["revenue_hi_usd_bn"]):
            with self.subTest(quarter=q):
                self.assertIn(form, ("point_pm", "point", "range"))
                self.assertEqual(form == "point", lo == hi)
        runs, start = [], 0
        for k in range(1, len(g["quarters"]) + 1):
            if k == len(g["quarters"]) or g["revenue_form"][k] != g["revenue_form"][start]:
                runs.append((start, k - 1))
                start = k
        note = self.ex["EX_REVBAND"]["note"]
        for a, b in runs:
            span = f"{qlab(g['quarters'][a])} 到 {qlab(g['quarters'][b])}" if b > a else qlab(g["quarters"][a])
            self.assertIn(span, note)
        # a range quarter whose width differs from its run's usual width is named
        widths = [round((h - l) * 10, 1) for l, h in zip(g["revenue_lo_usd_bn"], g["revenue_hi_usd_bn"])]
        for a, b in runs:
            if g["revenue_form"][a] != "range":
                continue
            run = widths[a:b + 1]
            mode = max(set(run), key=run.count)
            for k in range(a, b + 1):
                if widths[k] != mode:
                    self.assertIn(qlab(g["quarters"][k]), note)

    def test_the_outlook_timing_is_measured(self) -> None:
        """The band's note says how far into its quarter each outlook came out;
        it used to say "before the quarter began", which was false every time."""
        g, ends = self.g, self.st["period_ends"]
        days = [(date.fromisoformat(g["issued_in_release"][k])
                 - date.fromisoformat(ends[k - 1])).days - 1 for k in range(1, len(g["quarters"]))]
        self.assertGreater(min(days), 0)
        self.assertIn(f"本季已经开始了 {min(days)}–{max(days)} 天", self.ex["EX_REVBAND"]["note"])

    def test_gross_margin_and_operating_margin_were_never_guided_in_the_same_quarter(self) -> None:
        g = self.g
        gm = g["non_gaap_gross_margin_pct"]
        om = g["non_gaap_operating_margin_pct"]
        for q, a, b in zip(g["quarters"], gm, om):
            with self.subTest(quarter=q):
                self.assertTrue((a is None) != (b is None), "exactly one margin is guided each quarter")
        om_q = [q for q, v in zip(g["quarters"], om) if v is not None]
        self.assertEqual((om_q[0], om_q[-1]), ("2018Q1", "2021Q1"))
        eps_first = next(q for q, v in zip(g["quarters"], g["non_gaap_eps_usd"]) if v is not None)
        self.assertEqual(eps_first, "2017Q1")
        self.assertTrue(all(v is not None for v in g["non_gaap_eps_usd"][g["quarters"].index(eps_first):]))

    def test_the_revenue_record_is_recounted(self) -> None:
        g, rev, P = self.g, self.inc["revenue"], self.P
        tally = {"r_above": 0, "r_in": 0, "r_below": 0, "p_above": 0, "p_below": 0, "p_eq": 0}
        for k, q in enumerate(P):
            lo, hi, a = g["revenue_lo_usd_bn"][k], g["revenue_hi_usd_bn"][k], rev[k] / 1000
            if lo == hi:
                tally["p_above" if a > hi else "p_below" if a < lo else "p_eq"] += 1
            else:
                tally["r_above" if a > hi else "r_below" if a < lo else "r_in"] += 1
        ranged = tally["r_above"] + tally["r_in"] + tally["r_below"]
        points = tally["p_above"] + tally["p_below"] + tally["p_eq"]
        title = self.ex["EX_REVBAND"]["title"]
        self.assertIn(f"{ranged + points} 个已完结季度里，给区间的 {ranged} 季有 {tally['r_above']} 季超上限、"
                      f"{tally['r_in']} 季落在区间内、{tally['r_below']} 季跌破下限", title)
        self.assertIn(f"只给单点的 {points} 季 {tally['p_above']} 季高于、{tally['p_below']} 季低于", title)
        self.assertEqual(f"{tally['p_eq']} 季持平" in title, tally["p_eq"] > 0)
        # the band draws every guided quarter, the next one included, with no actual
        band = self.ex["EX_REVBAND"]
        self.assertEqual(len(band["xlabels"]), len(g["quarters"]))
        self.assertIsNone(band["actual"][-1])
        self.assertIn("仅指引", band["annot"])

    def test_the_midpoint_deviation_is_recomputed(self) -> None:
        g, rev = self.g, self.inc["revenue"]
        dev = [(rev[k] / 1000) / ((g["revenue_lo_usd_bn"][k] + g["revenue_hi_usd_bn"][k]) / 2) * 100 - 100
               for k in range(len(self.P))]
        ex = self.ex["EX_REVDEV"]
        self.assertEqual(len(ex["groups"][0]["values"]), len(self.P))
        for got, want in zip(ex["groups"][0]["values"], dev):
            self.assertAlmostEqual(got, want, places=4)
        self.assertIn(f"{len(dev)} 季里 {sum(1 for v in dev if v > 0)} 季为正", ex["title"])

    def test_the_margin_and_eps_records_are_recounted(self) -> None:
        g, P, ng = self.g, self.P, self.ng
        gm_q = [q for q, v in zip(g["quarters"], g["non_gaap_gross_margin_pct"]) if v is not None and q in P]
        dev = [ng["gross_margin_pct_first_print"][P.index(q)]
               - g["non_gaap_gross_margin_pct"][g["quarters"].index(q)] for q in gm_q]
        up, down = sum(1 for v in dev if v > 0.05), sum(1 for v in dev if v < -0.05)
        ex = self.ex["EX_GMDEV"]
        self.assertEqual(ex["xlabels"], [qlab(q) for q in gm_q])
        self.assertIn(f"给过毛利率指引的 {len(gm_q)} 季里 {up} 季高于、{down} 季低于", ex["title"])
        if len(gm_q) - up - down:
            self.assertIn(f"{len(gm_q) - up - down} 季与指引相同", ex["title"])
        worst = gm_q[min(range(len(dev)), key=lambda k: dev[k])]
        self.assertIn(f"最差一次 {qlab(worst)}", ex["title"])

        eps_q = [q for q, v in zip(g["quarters"], g["non_gaap_eps_usd"]) if v is not None and q in P]
        edev = [ng["eps_usd_first_print"][P.index(q)] - g["non_gaap_eps_usd"][g["quarters"].index(q)]
                for q in eps_q]
        e_up, e_down = sum(1 for v in edev if v > 0.004), sum(1 for v in edev if v < -0.004)
        ex = self.ex["EX_EPSDEV"]
        self.assertIn(f"{len(eps_q)} 季里 {e_up} 季高于、{e_down} 季低于", ex["title"])
        for q in (q for q, v in zip(eps_q, edev) if v < -0.004):
            self.assertIn(qlab(q), ex["note"])

    # ── two readings of every non-GAAP figure ────────────────────────────────
    def test_first_print_and_reprint_differ_only_in_restated_years(self) -> None:
        ng, P = self.ng, self.P
        restated = {e["restated_year"] for e in self.st["restatement_events"]}
        moved_years = set()
        pairs = 0
        for k, q in enumerate(P):
            for first, again in (("gross_margin_pct_first_print", "gross_margin_pct_year_ago_reprint"),
                                 ("eps_usd_first_print", "eps_usd_year_ago_reprint")):
                b = ng[again][k]
                if b is None:
                    continue
                pairs += 1
                if abs(ng[first][k] - b) > 0.004:
                    moved_years.add(q[:4])
        self.assertGreater(pairs, 60)
        self.assertTrue(moved_years, "no reprint ever differed -- the recast chart would be empty")
        self.assertLessEqual(moved_years, restated)
        # every quarter with a reprint names the release it was reprinted in, four releases on
        for k in range(len(P) - 4):
            self.assertEqual(ng["reprinted_in_release"][k], self.st["release_dates"][k + 4])
        self.assertTrue(all(v is None for v in ng["reprinted_in_release"][-4:]))

    def test_the_recast_table_is_the_quarters_whose_figures_moved(self) -> None:
        """The reprint record is audit material -- why guidance is scored on the
        first print -- so it sits in the drawer, one row per quarter that moved."""
        ng, P = self.ng, self.P
        eps_moved = [q for k, q in enumerate(P) if ng["eps_usd_year_ago_reprint"][k] is not None
                     and abs(ng["eps_usd_first_print"][k] - ng["eps_usd_year_ago_reprint"][k]) > 0.004]
        gm_moved = [q for k, q in enumerate(P) if ng["gross_margin_pct_year_ago_reprint"][k] is not None
                    and abs(ng["gross_margin_pct_first_print"][k] - ng["gross_margin_pct_year_ago_reprint"][k]) > 0.04]
        table = next(t for t in self.payload["tables"] if t["title"].startswith(intc.RECAST_TABLE_TITLE))
        self.assertEqual([row[0] for row in table["rows"]], sorted(set(eps_moved) | set(gm_moved)))
        pairs = sum(1 for v in ng["eps_usd_year_ago_reprint"] if v is not None)
        self.assertIn(f"{pairs} 个有重印的季度里，EPS 变了 {len(eps_moved)} 个、毛利率变了 {len(gm_moved)} 个",
                      table["title"])
        restated = {e["restated_year"]: e for e in self.st["restatement_events"]}
        for row in table["rows"]:
            self.assertIn(restated[row[0][:4]]["what"], row[-1])
        # the chart that used to carry this record is gone from every section
        self.assertNotIn("EX_RECAST", self.ex)

    # ── the four parts ───────────────────────────────────────────────────────
    def test_the_page_is_in_the_four_part_format(self) -> None:
        self.assertEqual([(sec["id"], sec["title"]) for sec in self.payload["sections"]],
                         [("settled", "一、上季跟踪指标兑现了吗"), ("quarter_highlights", "二、本季重点"),
                          ("next_quarter", "三、下季要跟踪什么"), ("routine", "四、长期常规跟踪")])
        for sec in self.payload["sections"]:
            with self.subTest(section=sec["id"]):
                self.assertTrue(sec["exhibits"])
                self.assertTrue(sec["description"])

    # ── section one: what last quarter left, settled ─────────────────────────
    def test_section_one_settles_in_the_order_the_format_sets(self) -> None:
        """Last quarter's questions, then last quarter's thresholds, then the
        company's own guidance record -- nothing else."""
        refs = [ex["ref"] for ex in self.payload["sections"][0]["exhibits"]]
        lines = [f"EX_PRIOR_{e['id'].upper()}" for e in self.st["prior_kpi_settlement"]["quantified"]]
        self.assertEqual(refs, ["EX_FOLLOWUP", "EX_PRIOR_HEADROOM"] + lines
                         + ["EX_REVBAND", "EX_REVDEV", "EX_GMDEV", "EX_EPSDEV"])

    def test_the_closure_is_this_quarters_report_section_zero(self) -> None:
        closure = self.st["followup_closure"]
        items = closure["items"]
        self.assertEqual([it["verdict"] for it in items], REPORT_SECTION_ZERO_VERDICTS)
        self.assertEqual(closure["set_in"], display_period(self.P[-2]))

        # The report writes no tally. The block's rule, re-implemented here: a
        # bare 「通过」 is a pass, a verdict opening with 「未通过」 a failure, and
        # every compound half-pass and 「部分通过」 a partial.
        def bucket(verdict: str) -> str:
            if verdict == "通过":
                return "通过"
            return "未通过" if verdict.startswith("未通过") else "部分通过"

        self.assertEqual([it["bucket"] for it in items], [bucket(v) for v in REPORT_SECTION_ZERO_VERDICTS])
        counts = {b: sum(1 for v in REPORT_SECTION_ZERO_VERDICTS if bucket(v) == b)
                  for b in ("通过", "部分通过", "未通过")}
        self.assertEqual(counts, {"通过": 1, "部分通过": 3, "未通过": 1})
        ex = self.ex["EX_FOLLOWUP"]
        self.assertEqual(ex["title"], "上季 5 条待验证问题：1 条通过、3 条部分通过、1 条未通过")
        self.assertEqual(ex["xlabels"], ["通过", "部分通过", "未通过"])
        self.assertEqual(ex["values"], [1, 3, 1])
        for k, verdict in enumerate(REPORT_SECTION_ZERO_VERDICTS, start=1):
            self.assertIn(f"{k}. ", ex["note"])
            self.assertIn(f"报告判定「{verdict}」", ex["note"])
        self.assertNotIn("{", ex["note"])

    def test_last_quarters_thresholds_are_its_section_eight_settled_on_filed_figures(self) -> None:
        prior = self.st["prior_kpi_settlement"]
        got = {e["id"]: (e["row"], e["threshold"], e["positive"], e["direction"]) for e in prior["quantified"]}
        self.assertEqual(got, PRIOR_SECTION_EIGHT)
        self.assertEqual([r["row"] for r in prior["unquantified"]], PRIOR_SECTION_EIGHT_UNQUANTIFIED_ROWS)
        self.assertEqual(prior["set_in"], display_period(self.P[-2]))

        # every actual recomputed here from the series, not through the builder
        seg, ext = self.st["segments"], self.st["foundry_external"]["external_revenue_usd_m"]
        SP, q = seg["periods"], self.P[-1]
        ya = f"{int(q[:4]) - 1}{q[4:]}"
        afcf = self.st["cash_flow_usd_m"]["adjusted_fcf_printed"]
        actual = {"dcai_yoy": (seg["dcai_revenue"][SP.index(q)] / seg["dcai_revenue"][SP.index(ya)] - 1) * 100,
                  "non_gaap_gm": self.ng["gross_margin_pct_first_print"][-1],
                  "foundry_external": ext[-1],
                  "adjusted_fcf": afcf[-1] / 1000}
        previous = {"dcai_yoy": None, "non_gaap_gm": None, "foundry_external": ext[-2],
                    "adjusted_fcf": afcf[-2] / 1000}
        status = {}
        for e in prior["quantified"]:
            key, line = e["id"], e["threshold"]
            below = actual[key] < line
            if below and (e.get("consecutive", 1) == 1 or previous[key] < line):
                status[key] = "击穿"
            else:
                status[key] = "本季越线" if below else "守住"
        head = self.ex["EX_PRIOR_HEADROOM"]
        held = sum(1 for v in status.values() if v == "守住")
        broken = [e["metric"] for e in prior["quantified"] if status[e["id"]] == "击穿"]
        self.assertTrue(head["title"].startswith(
            f"上季 {len(status)} 条量化阈值：{held} 条守住、{len(broken)} 条被击穿"), head["title"])
        if broken:
            self.assertIn(f"（{'、'.join(broken)}）", head["title"])
        self.assertEqual(head["xlabels"], [e["metric"] for e in prior["quantified"]])
        for e, value in zip(prior["quantified"], head["values"]):
            with self.subTest(threshold=e["id"]):
                self.assertAlmostEqual(value, round((actual[e["id"]] - e["threshold"]) / abs(e["threshold"]) * 100, 1))
                line = self.ex[f"EX_PRIOR_{e['id'].upper()}"]
                self.assertTrue(line["title"].startswith(f"{e['metric']}：{status[e['id']]}上季阈值"), line["title"])
                self.assertEqual(set(line["series"][1]["values"]), {e["threshold"]})
                self.assertAlmostEqual(line["series"][0]["values"][-1], actual[e["id"]], places=2)
                self.assertIn(e["rule"], line["note"])
        # the row with no number is named, with its reason, rather than dropped
        for r in prior["unquantified"]:
            self.assertIn(r["metric"], head["note"])
            self.assertIn(r["metric"], self.payload["sections"][0]["description"])
        table = next(t for t in self.payload["tables"] if t["title"].startswith("上季量化阈值的原文"))
        self.assertEqual(len(table["rows"]), len(prior["quantified"]) + len(prior["unquantified"]))

    def test_the_page_describes_itself_as_four_parts(self) -> None:
        text = text_of({k: self.payload[k] for k in ("notes", "brief", "footer")})
        self.assertIn("本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列", text)
        self.assertEqual(len(re.findall(r"段排列", text)), 1)
        # no sentence still points a reader at a section of the old seven-part page
        for stale in ("第五节", "第六节", "第七节", "跟踪一节"):
            self.assertNotIn(stale, text_of(self.payload))

    # ── the quarter ──────────────────────────────────────────────────────────
    def test_the_segments_close_to_the_consolidated_statement(self) -> None:
        seg, P, inc = self.st["segments"], self.P, self.inc
        for k, q in enumerate(seg["periods"]):
            with self.subTest(quarter=q):
                rev = sum(seg[key][k] for key in ("ccpg_revenue", "dcai_revenue", "foundry_revenue",
                                                  "all_other_revenue", "eliminations_revenue"))
                oi = sum(seg[key][k] for key in ("ccpg_oi", "dcai_oi", "foundry_oi", "all_other_oi",
                                                 "corporate_oi", "eliminations_oi"))
                self.assertEqual(rev, seg["total_revenue"][k])
                self.assertEqual(oi, seg["total_oi"][k])
                self.assertEqual(seg["total_revenue"][k], inc["revenue"][P.index(q)])
                self.assertEqual(seg["total_oi"][k], inc["operating_income"][P.index(q)])

    def test_the_eps_bridge_closes_and_names_its_largest_leg(self) -> None:
        story = self.st.get("quarter_story")
        if story is None:
            self.assertNotIn("EX_EPSBRIDGE", self.ex)
            return
        rc = story["eps_reconciliation"]
        self.assertAlmostEqual(rc["gaap"] + sum(leg["value"] for leg in rc["legs"]), rc["non_gaap"], places=2)
        self.assertEqual(rc["gaap"], self.inc["eps_diluted_usd"][-1])
        self.assertEqual(rc["non_gaap"], self.ng["eps_usd_first_print"][-1])
        ex = self.ex["EX_EPSBRIDGE"]
        values = ex["groups"][0]["values"]
        self.assertAlmostEqual(values[0] + values[1] + values[2], values[3], places=2)
        big = max(rc["legs"], key=lambda leg: abs(leg["value"]))
        self.assertEqual(ex["xlabels"][1], big["name"])
        self.assertIn(big["name"], self.payload["headline"])
        # a leg worth zero at the chart's precision is not a column and is not listed
        for leg in rc["legs"]:
            if round(leg["value"], 2) == 0:
                self.assertNotIn(leg["name"], ex["xlabels"])
                self.assertNotIn(leg["name"], ex["note"])

    def test_the_foundry_break_is_declared_and_measured(self) -> None:
        old, seg = self.st["foundry_2024_basis"], self.st["segments"]
        ex = self.ex["EX_FOUNDRY"]
        early = [q for q in old["periods"] if q not in seg["periods"]]
        self.assertEqual(ex["break_at"], len(early))
        self.assertEqual(ex["xlabels"][ex["break_at"]], qlab(seg["periods"][0]))
        overlap = [q for q in old["periods"] if q in seg["periods"]]
        self.assertTrue(overlap, "no quarter on both bases -- the break would be unmeasured")
        diffs = [seg["foundry_revenue"][seg["periods"].index(q)] - old["foundry_revenue"][old["periods"].index(q)]
                 for q in overlap]
        self.assertTrue(any(diffs), "the two bases agree everywhere -- then there is no break to draw")
        total = sum(seg["foundry_oi"])
        word = "亏损" if total < 0 else "盈利"
        self.assertIn(f"现行口径 {len(seg['periods'])} 季累计经营{word} {intc.usd_bn(abs(total))}", ex["title"])

    def test_the_net_debt_sentences_are_recounted(self) -> None:
        """Net debt is this page's own measure (the company never prints one), so
        every statement about its sign or a threshold is recounted here."""
        b, P = self.st["balance_sheet_usd_m"], self.P
        nd = [(sd + ld) - (c + si + ta) for sd, ld, c, si, ta in zip(
            b["short_term_debt"], b["long_term_debt"], b["cash_and_equivalents"],
            b["short_term_investments"], b["trading_assets"])]
        net_cash = [qlab(q) for q, v in zip(P, nd) if v < 0]
        note = self.ex["EX_DEBT"]["note"]
        if net_cash:
            self.assertIn(f"是净现金的只有 {'、'.join(net_cash)}", note)
        else:
            self.assertIn("全部是净债务", note)
        self.assertIn(intc.usd_bn(nd[-1]), self.ex["EX_DEBT"]["title"])
        if "EX_NDLINE" not in self.ex:
            return
        line = self.st["thresholds"]["items"]
        limit = next(it["threshold"] for it in line if it["key"] == "net_debt")
        over = [qlab(q) for q, v in zip(P, nd) if v / 1000 > limit]
        title = self.ex["EX_NDLINE"]["title"]
        if over:
            self.assertIn(f"越线的只有 {'、'.join(over)}", title)
        else:
            self.assertNotIn("越线", title)

    def test_the_share_count_sentence_is_recounted(self) -> None:
        eq, P = self.st["equity"], self.P
        sh = self.st["balance_sheet_usd_m"]["shares_outstanding_m"]
        q_of = lambda d: f"{d[:4]}Q{(int(d[5:7]) - 1) // 3 + 1}"
        done = [it for it in eq["issuances"] if q_of(it["closed"]) <= P[-1]]
        base = P.index(q_of(min(it["closed"] for it in done))) - 1
        note = self.ex["EX_SHARES"]["note"]
        self.assertIn(f"{qlab(P[base])} 末到本季末流通股增加 {sh[-1] - sh[base]:,.0f}M", note)
        self.assertIn(f"其中 {sum(it['shares_m'] for it in done):,.0f}M 来自", note)
        for it in done:
            self.assertIn(it["counterparty"], note)
        # the escrow balance is printed only as of this quarter's end
        self.assertEqual(f"截至 {eq['escrow_remaining_as_of']}" in note,
                         eq["escrow_remaining_as_of"] == self.st["period_ends"][-1])

    def test_the_headline_figures_are_the_charts_figures(self) -> None:
        """The headline computes its growth and its beat on its own path; the
        charts compute them on theirs. Two routes, one number."""
        yoy = self.ex["EX_REV"]["yoy"]["values"][-1]
        self.assertIn(f"同比 {yoy:+.1f}%".replace("-", "−"), self.payload["headline"])
        beat = self.ex["EX_REVDEV"]["groups"][0]["values"][-1]
        self.assertIn(f"比指引中值{'高' if beat >= 0 else '低'} {abs(beat):.1f}%", self.payload["headline"])

    def test_the_plotted_net_debt_is_debt_minus_cash(self) -> None:
        series = {item["name"]: item["values"] for item in self.ex["EX_DEBT"]["series"]}
        debt, cash, net = (series[k] for k in ("总债务（短期 + 长期）", "现金、短期投资与交易性资产", "净债务"))
        for d, c, v in zip(debt, cash, net):
            self.assertAlmostEqual(d - c, v, places=2)
        self.assertIn(intc.usd_bn(net[-1] * 1000), self.ex["EX_DEBT"]["title"])

    def test_the_bridge_names_how_many_legs_it_folded(self) -> None:
        story = self.st.get("quarter_story")
        if story is None:
            return
        legs = [leg for leg in story["eps_reconciliation"]["legs"] if round(leg["value"], 2) != 0]
        folded = len(legs) - 1
        label = self.ex["EX_EPSBRIDGE"]["xlabels"][2]
        spelled = "零一两三四五六七八九"[folded] if folded < 10 else None
        self.assertEqual(label, f"其余{spelled}项合计")

    def test_the_breached_lines_are_recounted(self) -> None:
        th = self.st.get("thresholds")
        if th is None:
            self.assertNotIn("EX_HEADROOM", self.ex)
            return
        seg, b = self.st["segments"], self.st["balance_sheet_usd_m"]
        ext = self.st["foundry_external"]
        now = {"non_gaap_gm": self.ng["gross_margin_pct_first_print"][-1],
               "dcai_margin": seg["dcai_oi"][-1] / seg["dcai_revenue"][-1] * 100,
               "net_debt": (b["total_debt"][-1] - b["cash_and_investments"][-1]) / 1000,
               "foundry_external_ex_altera": (None if ext["altera_usd_m"][-1] is None else
                                              ext["external_revenue_usd_m"][-1] - ext["altera_usd_m"][-1])}
        entries = [it for it in th["items"] if now.get(it["key"]) is not None]
        breached = [it["metric"] for it in entries
                    if (now[it["key"]] < it["threshold"]) == (it["direction"] == "up")]
        ex = self.ex["EX_HEADROOM"]
        self.assertEqual(ex["xlabels"], [it["metric"] for it in entries])
        self.assertIn(f"下季 {len(entries)} 条量化阈值", ex["title"])
        if breached:
            self.assertIn("已越线的是：" + "、".join(breached), ex["note"])
        else:
            self.assertIn("全部仍在安全侧", ex["title"])

    def test_the_outlier_reason_sits_on_exactly_the_charts_whose_extreme_it_explains(self) -> None:
        P, g, ng, inc = self.P, self.g, self.ng, self.inc
        gm_q = [q for q, v in zip(g["quarters"], g["non_gaap_gross_margin_pct"]) if v is not None and q in P]
        worst_gm = min(gm_q, key=lambda q: ng["gross_margin_pct_first_print"][P.index(q)]
                       - g["non_gaap_gross_margin_pct"][g["quarters"].index(q)])
        lowest = min(P, key=lambda q: inc["gross_profit"][P.index(q)] / inc["revenue"][P.index(q)])
        old, seg = self.st["foundry_2024_basis"], self.st["segments"]
        early = [q for q in old["periods"] if q not in seg["periods"]]
        f_axis = early + seg["periods"]
        f_oi = [old["foundry_oi"][old["periods"].index(q)] for q in early] + seg["foundry_oi"]
        worst_f = f_axis[min(range(len(f_oi)), key=lambda i: f_oi[i])]
        for event in self.st["charge_events"]:
            for ref, extreme in (("EX_GMDEV", worst_gm), ("EX_MARGINS", lowest), ("EX_FOUNDRY", worst_f)):
                with self.subTest(chart=ref):
                    self.assertEqual(event["what"] in self.ex[ref]["note"], event["period"] == extreme)

    # ── what a chart can draw ────────────────────────────────────────────────
    def test_a_negative_value_sits_on_a_kind_that_can_draw_below_zero(self) -> None:
        for ex in exhibits_of(self.payload):
            if ex["kind"] not in ZERO_FLOORED_KINDS:
                continue
            values = list(ex.get("values") or [])
            for key in ("stacks", "groups", "series"):
                for group in ex.get(key, []):
                    values += group["values"]
            with self.subTest(exhibit=ex["n"]):
                self.assertTrue(all(v is None or v >= 0 for v in values), ex["title"])

    def test_every_exhibit_plots_one_point_per_x_label(self) -> None:
        for ex in exhibits_of(self.payload):
            n = len(ex["xlabels"])
            series = []
            for key in ("values", "lo", "hi", "actual"):
                if key in ex:
                    series.append(ex[key])
            for key in ("series", "groups", "stacks"):
                series += [item["values"] for item in ex.get(key, [])]
            if isinstance(ex.get("yoy"), dict):
                series.append(ex["yoy"]["values"])
            with self.subTest(exhibit=ex["n"]):
                self.assertTrue(series)
                self.assertTrue(all(len(v) == n for v in series), ex["title"])

    def test_exhibits_are_numbered_in_render_order_from_two(self) -> None:
        self.assertEqual([ex["n"] for ex in exhibits_of(self.payload)],
                         list(range(2, len(exhibits_of(self.payload)) + 2)))
        self.assertNotIn("{EX_", text_of(self.payload))

    def test_tables_follow_the_exhibits_and_end_with_the_shared_table(self) -> None:
        tables = self.payload["tables"]
        last = exhibits_of(self.payload)[-1]["n"]
        self.assertEqual([t["n"] for t in tables], list(range(last + 1, last + 1 + len(tables))))
        self.assertTrue(tables[-1]["title"].startswith("AI capex 循环"))
        self.assertEqual(len(tables[0]["rows"]), len(self.g["quarters"]))
        self.assertEqual(len(tables[1]["rows"]), len(self.P))

    def test_colour_and_formatter_names_are_ones_the_renderer_knows(self) -> None:
        for ex in exhibits_of(self.payload):
            for key in ("fmt", "yfmt", "label_fmt"):
                if key in ex:
                    self.assertIn(ex[key], VALID_FORMATS, (ex["n"], key))
            for key in ("series", "groups", "stacks"):
                for item in ex.get(key, []):
                    if "color" in item:
                        self.assertIn(item["color"], VALID_COLORS, (ex["n"], item["name"]))
            for key in ("yoy", "line", "bar"):
                if isinstance(ex.get(key), dict) and "color" in ex[key]:
                    self.assertIn(ex[key]["color"], VALID_COLORS)

    def test_no_placeholder_or_markup_leaks_into_literal_slots(self) -> None:
        for slot in LITERAL_SLOTS:
            text = self.payload[slot]
            self.assertNotRegex(text, r"</?[a-z]+>", slot)
            self.assertNotIn("{", text, slot)
        for note in self.payload["notes"]:
            self.assertNotRegex(note, r"</?[a-z]+>")
            self.assertNotIn("**", note)

    def test_sources_are_official_sec_links_and_include_the_quarter(self) -> None:
        for src in self.st["sources"]:
            self.assertTrue(src["url"].startswith("https://www.sec.gov/Archives/edgar/data/50863/"), src)
        labels = [src["label"] for src in self.st["sources"]]
        q = self.P[-1]
        self.assertTrue(any(l.startswith(f"Intel {q[:4]} 年第 {q[5]} 季度业绩新闻稿") for l in labels))
        # one release per reported quarter plus the one that guided the first
        self.assertEqual(sum(1 for l in labels if "业绩新闻稿" in l), len(self.P) + 1)

    # ── what is published ────────────────────────────────────────────────────
    def test_the_period_the_page_reports_is_the_last_quarter(self) -> None:
        self.assertEqual(self.payload["latest"]["disclosed_period_label"], display_period(self.P[-1]))
        self.assertEqual(self.payload["latest"]["period_end"], self.st["period_ends"][-1])
        self.assertEqual(self.payload["latest"]["release_date"], self.st["release_dates"][-1])

    def test_published_payload_and_shell(self) -> None:
        self.assertEqual(js_payload(ROOT / "data" / "intc.js", "window.DASH"), self.payload)
        shell = (ROOT / "intc" / "index.html").read_text(encoding="utf-8")
        self.assertIn("../data/intc.js", shell)
        self.assertIn("INTC", shell)

    def test_shell_versions_every_script_by_content(self) -> None:
        shell = (ROOT / "intc" / "index.html").read_text(encoding="utf-8")
        sources = re.findall(r'<script src="\.\./([^"?]+)(\?v=([0-9a-f]+))?"', shell)
        self.assertEqual([name for name, _, _ in sources],
                         ["data/roster.js", "data/intc.js", "assets/charts.js", "assets/page.js"])
        for name, query, digest in sources:
            with self.subTest(script=name):
                self.assertTrue(query)
                expected = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()[:len(digest)]
                self.assertEqual(digest, expected)

    def test_the_roster_entry_matches_the_payload(self) -> None:
        entry = next(e for e in ENTRIES if e["slug"] == "intc")
        self.assertEqual(entry["ticker"], self.payload["company"]["ticker"])
        self.assertEqual(entry["group"], self.payload["company"]["group"])
        self.assertNotIn("headline_metrics", entry)
        # calendar-quarter filer: it must not claim the offset-year relabelling
        self.assertNotIn("本站按自然年季度标注", entry["cadence_label"])

    def test_the_home_page_card_matches_the_payload(self) -> None:
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        card = home.split('href="intc/"', 1)[1].split("</a>", 1)[0]
        self.assertIn(self.payload["latest"]["release_date"], card)
        self.assertIn(self.payload["latest"]["disclosed_period_label"], card)
        self.assertIn(" · ".join(intc.headline_metrics(self.st)), card)

    def test_the_card_figures_are_three_and_computed(self) -> None:
        metrics = intc.headline_metrics(self.st)
        self.assertEqual(len(metrics), 3)
        self.assertIn(intc.usd_bn(self.inc["revenue"][-1]), metrics[0])
        self.assertIn(f"{self.ng['gross_margin_pct_first_print'][-1]:.1f}%", metrics[1])


class IntcRollTest(unittest.TestCase):
    """What a roll has to change in `series/intc.json`, and what the page does
    when it does not."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads(intc.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = intc.build_payload(cls.source)

    def test_a_block_stamped_with_another_period_stops_the_build(self) -> None:
        for key in STAMPED_BLOCKS:
            if key not in self.source:
                continue
            stale = copy.deepcopy(self.source)
            stale[key]["period"] = "Q1 1999"
            with self.subTest(block=key), self.assertRaisesRegex(ValueError, "stamped"):
                intc.build_payload(stale)
        orphan = copy.deepcopy(self.source)
        q = orphan["periods"][-1]
        orphan["sources"] = [s for s in orphan["sources"]
                             if not s["label"].startswith(f"Intel {q[:4]} 年第 {q[5]} 季度业绩新闻稿")]
        with self.assertRaisesRegex(ValueError, "sources"):
            intc.build_payload(orphan)

    def test_a_quarter_without_its_stories_leaves_them_out(self) -> None:
        bare_src = {k: v for k, v in self.source.items()
                    if k not in ("quarter_story", "followup_closure", "prior_kpi_settlement")}
        bare = intc.build_payload(bare_src)
        full_ex, bare_ex = exhibits_of(self.payload), exhibits_of(bare)
        story_refs = {"EX_EPSBRIDGE", "EX_FOLLOWUP", "EX_PRIOR_HEADROOM"} | {
            ex["ref"] for ex in full_ex if ex["ref"].startswith("EX_PRIOR_")}
        # with nothing left over from last quarter, section one says so and settles the guidance
        self.assertIn("本季没有上季留下的待验证问题与量化阈值可结算", bare["sections"][0]["description"])
        # still four parts, none of them empty
        self.assertEqual([sec["id"] for sec in bare["sections"]],
                         ["settled", "quarter_highlights", "next_quarter", "routine"])
        self.assertTrue(all(sec["exhibits"] for sec in bare["sections"]))
        refs = {ex["ref"] for ex in bare_ex}
        self.assertFalse(refs & story_refs)
        present = {ex["ref"] for ex in full_ex} & story_refs
        self.assertEqual(len(bare_ex), len(full_ex) - len(present))
        self.assertEqual([ex["n"] for ex in bare_ex], list(range(2, len(bare_ex) + 2)))
        self.assertNotIn("托管股份按市值重估在净利润里", text_of(bare))
        self.assertNotIn("{EX_", text_of(bare))

    def test_an_unexplained_reprint_stops_the_build(self) -> None:
        """The recast chart says every difference falls in a restated year; drop
        the event that explains one and the build must refuse, not print."""
        broken = copy.deepcopy(self.source)
        broken["restatement_events"] = [e for e in broken["restatement_events"]
                                        if e["restated_year"] != "2021"]
        with self.assertRaisesRegex(ValueError, "restatement_events"):
            intc.build_payload(broken)

    def test_the_outlier_reason_is_printed_only_for_the_quarter_it_belongs_to(self) -> None:
        """A sourced reason is printed beside a chart's extreme only while that
        extreme is the event's quarter."""
        src, P = self.source, self.source["periods"]
        g, ng, inc = src["guidance"], src["non_gaap_printed"], src["income_usd_m"]
        gm_q = [q for q, v in zip(g["quarters"], g["non_gaap_gross_margin_pct"]) if v is not None and q in P]
        worst_gm = min(gm_q, key=lambda q: ng["gross_margin_pct_first_print"][P.index(q)]
                       - g["non_gaap_gross_margin_pct"][g["quarters"].index(q)])
        lowest = min(P, key=lambda q: inc["gross_profit"][P.index(q)] / inc["revenue"][P.index(q)])
        extremes = {worst_gm, lowest}
        for k, event in enumerate(src["charge_events"]):
            if event["period"] in extremes:
                self.assertIn(event["what"], text_of(self.payload))
            moved = copy.deepcopy(src)
            moved["charge_events"][k]["period"] = P[0]
            self.assertNotEqual(moved["charge_events"], src["charge_events"], "the move did not happen")
            if P[0] not in extremes:
                self.assertNotIn(event["what"], text_of(intc.build_payload(moved)))

    def test_a_quarter_without_next_quarters_thresholds_stops_the_build(self) -> None:
        """Section three is the thresholds; without them the page would publish
        an empty part, so the roll has to write them."""
        missing = {k: v for k, v in self.source.items() if k != "thresholds"}
        with self.assertRaisesRegex(ValueError, "required every quarter"):
            intc.build_payload(missing)

    def test_a_follow_up_verdict_the_data_contradicts_stops_the_build(self) -> None:
        if "followup_closure" not in self.source:
            return
        broken = copy.deepcopy(self.source)
        item = next(it for it in broken["followup_closure"]["items"] if it.get("metric") == "non_gaap_gm")
        item["threshold"] = 99.0
        with self.assertRaisesRegex(ValueError, "contradicts"):
            intc.build_payload(broken)

    def test_a_settlement_of_another_quarters_questions_stops_the_build(self) -> None:
        """Both blocks settle what the quarter before this one set; one written
        for any other quarter is somebody else's settlement."""
        for key in ("followup_closure", "prior_kpi_settlement"):
            if key not in self.source:
                continue
            stale = copy.deepcopy(self.source)
            stale[key]["set_in"] = "Q4 2025"
            with self.subTest(block=key), self.assertRaisesRegex(ValueError, "last quarter was"):
                intc.build_payload(stale)

    def test_a_single_quarter_below_a_two_quarter_line_is_not_a_break(self) -> None:
        """「连续 2 季 ≤ −US$1B」breaks only when both quarters are below it. With
        the previous quarter lifted above the line the latest alone is 「本季越线」,
        and the headroom title counts it apart from the breaks."""
        if "prior_kpi_settlement" not in self.source:
            return
        lifted = copy.deepcopy(self.source)
        afcf = lifted["cash_flow_usd_m"]["adjusted_fcf_printed"]
        self.assertLess(afcf[-2], -1000, "the real previous quarter is already below the line")
        afcf[-2] = 500.0
        ex = by_ref(intc.build_payload(lifted))
        self.assertIn("1 条本季越线但未满连续", ex["EX_PRIOR_HEADROOM"]["title"])
        self.assertTrue(ex["EX_PRIOR_ADJUSTED_FCF"]["title"].startswith("调整后自由现金流：本季越线上季阈值"))
        self.assertNotIn("被击穿（调整后自由现金流）", ex["EX_PRIOR_HEADROOM"]["title"])

    def _rolled(self) -> dict:
        """The series with one synthetic quarter appended the way a roll would."""
        rolled = copy.deepcopy(self.source)
        n = len(rolled["periods"])
        new, after = next_q(rolled["periods"][-1]), next_q(next_q(rolled["periods"][-1]))
        rolled["periods"].append(new)
        rolled["period_ends"].append("2099-01-01")
        rolled["release_dates"].append("2099-02-01")
        rolled["filing_accessions"].append("0000000000-99-000000")
        for key in ("income_usd_m", "non_gaap_printed", "cash_flow_usd_m", "balance_sheet_usd_m"):
            for name, values in rolled[key].items():
                if isinstance(values, list) and len(values) == n:
                    values.append(values[-4])
        rolled["non_gaap_printed"]["reprinted_in_release"][-1] = None
        g = rolled["guidance"]
        g["quarters"].append(after)
        for name, values in g.items():
            if isinstance(values, list) and name != "quarters":
                values.append(values[-1])
        g["issued_in_release"][-1] = "2099-02-01"
        seg = rolled["segments"]
        seg["periods"].append(new)
        for name, values in seg.items():
            if isinstance(values, list) and name != "periods" and len(values) == len(seg["periods"]) - 1:
                values.append(values[-1])
        seg["total_revenue"][-1] = rolled["income_usd_m"]["revenue"][-1]
        seg["total_oi"][-1] = rolled["income_usd_m"]["operating_income"][-1]
        ext = rolled["foundry_external"]
        ext["periods"].append(new)
        for name in ("external_revenue_usd_m", "altera_usd_m"):
            ext[name].append(ext[name][-1])
        for key in STAMPED_BLOCKS + ("_checks",):
            rolled.pop(key, None)
        # section three is required every quarter: a roll writes the new
        # quarter's thresholds, here the old ones restamped
        rolled["thresholds"] = dict(copy.deepcopy(self.source["thresholds"]), period=display_period(new))
        rolled["latest"] = dict(rolled["latest"], period=display_period(new))
        rolled["sources"] = rolled["sources"] + [{
            "label": f"Intel {new[:4]} 年第 {new[5]} 季度业绩新闻稿（8-K EX-99.1，2099-02-01）",
            "url": "https://www.sec.gov/Archives/edgar/data/50863/x/y.htm", "date": "2099-02-01"}]
        return rolled

    def test_the_next_quarter_rolls_without_touching_the_code(self) -> None:
        rolled = self._rolled()
        new = rolled["periods"][-1]
        payload = intc.build_payload(rolled)
        self.assertEqual(payload["latest"]["disclosed_period_label"], display_period(new))
        self.assertIn(display_period(new), payload["title"])
        ex = by_ref(payload)
        self.assertEqual(ex["EX_REV"]["xlabels"][-1], qlab(new))
        self.assertEqual(ex["EX_REVBAND"]["xlabels"][-1], qlab(next_q(new)))
        self.assertEqual(len(ex["EX_REVBAND"]["actual"]), len(ex["EX_REVBAND"]["xlabels"]))
        # a balance read as of the previous quarter's end is not this quarter's
        eq = rolled["equity"]
        self.assertNotIn(f"截至 {eq['escrow_remaining_as_of']}", ex["EX_SHARES"]["note"])
        # and a story block of the previous quarter does not leak into the new one
        self.assertNotIn("托管股份按市值重估在净利润里", text_of(payload))

    def test_a_block_that_was_not_rolled_stops_the_build(self) -> None:
        """Forgetting one block would print last quarter's figures as this quarter's."""
        for block in ("segments", "foundry_external"):
            rolled = self._rolled()
            rolled[block] = copy.deepcopy(self.source[block])
            with self.subTest(block=block), self.assertRaisesRegex(ValueError, block):
                intc.build_payload(rolled)
        rolled = self._rolled()
        rolled["guidance"] = copy.deepcopy(self.source["guidance"])
        with self.assertRaisesRegex(ValueError, "guidance"):
            intc.build_payload(rolled)
        rolled = self._rolled()
        rolled["periods"][-1] = rolled["periods"][-2]
        with self.assertRaisesRegex(ValueError, "consecutive"):
            intc.build_payload(rolled)

    def test_a_point_outlook_hit_exactly_is_counted_as_a_tie(self) -> None:
        """The real record has no exact hit, so the tie branch needs a built one:
        without its own bucket such a quarter falls out of the title's counts."""
        tied = copy.deepcopy(self.source)
        g, P = tied["guidance"], tied["periods"]
        k = next(i for i, form in enumerate(g["revenue_form"]) if form == "point" and g["quarters"][i] in P)
        actual = tied["income_usd_m"]["revenue"][P.index(g["quarters"][k])] / 1000
        g["revenue_lo_usd_bn"][k] = g["revenue_hi_usd_bn"][k] = actual
        title = by_ref(intc.build_payload(tied))["EX_REVBAND"]["title"]
        points = sum(1 for i, form in enumerate(g["revenue_form"]) if form == "point" and g["quarters"][i] in P)
        counts = [int(x) for x in re.findall(r"只给单点的 (\d+) 季 (\d+) 季高于、(\d+) 季低于、(\d+) 季持平", title)[0]]
        self.assertEqual(counts[0], points)
        self.assertEqual(sum(counts[1:]), points)
        self.assertGreaterEqual(counts[3], 1)

    def test_an_undisclosed_altera_share_is_said_not_guessed(self) -> None:
        rolled = self._rolled()
        rolled["foundry_external"]["altera_usd_m"][-1] = None
        ex = by_ref(intc.build_payload(rolled))["EX_FOUNDRYEXT"]
        self.assertIn("Altera 的份额未披露", ex["title"])

    def test_the_wording_follows_the_sign(self) -> None:
        """A miss, a profitable Foundry quarter and a breached line each read as such."""
        rolled = self._rolled()
        g = rolled["guidance"]
        k = g["quarters"].index(rolled["periods"][-1])
        g["revenue_lo_usd_bn"][k] = g["revenue_hi_usd_bn"][k] = rolled["income_usd_m"]["revenue"][-1] / 1000 * 1.2
        seg = rolled["segments"]
        seg["foundry_oi"][-1] = 150.0
        seg["eliminations_oi"][-1] = seg["total_oi"][-1] - sum(
            seg[key][-1] for key in ("ccpg_oi", "dcai_oi", "foundry_oi", "all_other_oi", "corporate_oi"))
        payload = intc.build_payload(rolled)
        self.assertIn("比指引中值低", payload["headline"])
        self.assertNotIn("高 −", payload["headline"])
        self.assertIn("本季盈利", by_ref(payload)["EX_FOUNDRY"]["title"])
        self.assertNotIn("亏损是现行口径", by_ref(payload)["EX_FOUNDRY"]["title"])

        over = copy.deepcopy(self.source)
        if "thresholds" in over:
            item = next(it for it in over["thresholds"]["items"] if it["key"] == "net_debt")
            item["threshold"] = 1.0
            title = by_ref(intc.build_payload(over))["EX_NDLINE"]["title"]
            self.assertIn("已越线", title)
            self.assertNotIn("离线还有", title)


class IntcChecksTest(unittest.TestCase):
    """`_checks` is an independent re-read of the quarter's primary filings.

    The series was built from XBRL facts and the earnings releases by one
    reader; `_checks` was keyed by a second reader from the 10-Q's statements
    and notes (and the 8-K for what only the release prints), without opening
    the series. The builder never reads it (`tests/test_data_only_roll.py`).
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.st = json.loads(intc.STAGING_PATH.read_text(encoding="utf-8"))
        cls.c = cls.st["_checks"]
        cls.payload = intc.build_payload(cls.st)

    def test_the_page_names_the_checked_period(self) -> None:
        c, latest = self.c, self.payload["latest"]
        self.assertEqual(c["period"], latest["disclosed_period_label"])
        self.assertEqual(c["period_end"], latest["period_end"])
        self.assertEqual(c["release_date"], latest["release_date"])
        self.assertIn(f"截至 {c['period_end']}", self.payload["subtitle"])
        self.assertIn("10-Q", c["source"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        c, st = self.c, self.st
        inc, seg, ng = st["income_usd_m"], st["segments"], st["non_gaap_printed"]
        pairs = [
            ("revenue_usd_m", inc["revenue"][-1]),
            ("gross_margin_usd_m", inc["gross_profit"][-1]),
            ("operating_income_usd_m", inc["operating_income"][-1]),
            ("net_income_attributable_to_intel_usd_m", inc["net_income_attributable_to_intel"][-1]),
            ("gaap_diluted_eps_usd", inc["eps_diluted_usd"][-1]),
            ("diluted_weighted_shares_m", inc["diluted_shares_m"][-1]),
            ("ccpg_revenue_usd_m", seg["ccpg_revenue"][-1]),
            ("dcai_revenue_usd_m", seg["dcai_revenue"][-1]),
            ("intel_foundry_revenue_usd_m", seg["foundry_revenue"][-1]),
            ("all_other_revenue_usd_m", seg["all_other_revenue"][-1]),
            ("ccpg_operating_income_usd_m", seg["ccpg_oi"][-1]),
            ("dcai_operating_income_usd_m", seg["dcai_oi"][-1]),
            ("intel_foundry_operating_income_usd_m", seg["foundry_oi"][-1]),
            ("corporate_unallocated_operating_income_usd_m", seg["corporate_oi"][-1]),
            ("non_gaap_gross_margin_pct", ng["gross_margin_pct_first_print"][-1]),
            ("non_gaap_diluted_eps_usd", ng["eps_usd_first_print"][-1]),
            ("intel_foundry_external_revenue_usd_m", st["foundry_external"]["external_revenue_usd_m"][-1]),
            ("operating_cash_flow_usd_m_release", st["cash_flow_usd_m"]["ocf"][-1]),
            ("gross_capex_usd_m_release", st["cash_flow_usd_m"]["capex_gross"][-1]),
            ("adjusted_free_cash_flow_usd_m", st["cash_flow_usd_m"]["adjusted_fcf_printed"][-1]),
            ("total_debt_usd_m_printed", st["balance_sheet_usd_m"]["total_debt"][-1]),
        ]
        if st.get("quarter_story"):
            pairs.append(("escrowed_shares_mtm_loss_usd_m", st["quarter_story"]["escrow_mtm_loss_usd_m"]))
        for key, got in pairs:
            with self.subTest(key=key):
                self.assertEqual(got, c[key])
        cash = c["cash_and_equivalents_usd_m"] + c["short_term_investments_usd_m"]
        self.assertEqual(st["balance_sheet_usd_m"]["cash_and_investments"][-1], cash)

    def test_every_historical_cell_matches_its_second_reading(self) -> None:
        """The page scores 42 quarters of history, and a wrong old cell changes a
        count in a title with every other test green. `_checks.history` holds a
        second reading of that history from another layer of the release (the
        summary bullet, the CFO commentary, the outlook reconciliation table,
        the release's own income statement); each cell it has must agree."""
        h, g, inc, P = self.c["history"], self.st["guidance"], self.st["income_usd_m"], self.st["periods"]
        gs = h["guidance_second_reading"]
        self.assertEqual(gs["quarters"], g["quarters"])
        compared = 0
        for key in ("revenue_lo_usd_bn", "revenue_hi_usd_bn", "non_gaap_gross_margin_pct", "non_gaap_eps_usd"):
            for q, a, b in zip(g["quarters"], g[key], gs[key]):
                if b is None:
                    continue
                compared += 1
                with self.subTest(field=key, quarter=q):
                    self.assertEqual(a, b)
        # every guided margin and EPS outlook has its reconciliation-table reading
        for key in ("non_gaap_gross_margin_pct", "non_gaap_eps_usd"):
            self.assertEqual([q for q, a, b in zip(g["quarters"], g[key], gs[key]) if a is not None and b is None], [])
        ir = h["income_from_releases"]
        self.assertEqual(ir["periods"], P)
        for mine, theirs in (("revenue", "revenue"), ("gross_profit", "gross_profit"),
                             ("operating_income", "operating_income"),
                             ("net_income_attributable_to_intel", "net_income_attributable_to_intel"),
                             ("eps_diluted_usd", "eps_diluted"), ("diluted_shares_m", "diluted_shares_m")):
            for q, a, b in zip(P, inc[mine], ir[theirs]):
                compared += 1
                with self.subTest(field=mine, quarter=q):
                    self.assertEqual(a, b)
        self.assertGreater(compared, 300)

    def test_the_outlooks_are_the_checked_ones(self) -> None:
        g, c = self.st["guidance"], self.c
        nxt, now = c["next_quarter_outlook"], c["this_quarter_outlook"]
        self.assertEqual(g["quarters"][-1], nxt["quarter"])
        self.assertEqual(now["quarter"], self.st["periods"][-1])
        self.assertEqual(g["revenue_lo_usd_bn"][-1] * 1000, nxt["revenue_low_usd_m"])
        self.assertEqual(g["revenue_hi_usd_bn"][-1] * 1000, nxt["revenue_high_usd_m"])
        self.assertEqual(g["non_gaap_gross_margin_pct"][-1], nxt["non_gaap_gross_margin_pct"])
        self.assertEqual(g["non_gaap_eps_usd"][-1], nxt["non_gaap_diluted_eps_usd"])
        k = g["quarters"].index(now["quarter"])
        self.assertEqual(g["revenue_lo_usd_bn"][k] * 1000, now["revenue_low_usd_m"])
        self.assertEqual(g["revenue_hi_usd_bn"][k] * 1000, now["revenue_high_usd_m"])
        self.assertEqual(g["non_gaap_gross_margin_pct"][k], now["non_gaap_gross_margin_pct"])
        self.assertEqual(g["non_gaap_eps_usd"][k], now["non_gaap_diluted_eps_usd"])

    def test_the_page_prints_the_checked_figures(self) -> None:
        c, text = self.c, text_of(self.payload)
        self.assertIn(intc.usd_bn(c["revenue_usd_m"]), self.payload["headline"])
        self.assertIn(f"{c['non_gaap_gross_margin_pct']:.1f}%", self.payload["headline"])
        self.assertIn(intc.usd_eps(c["gaap_diluted_eps_usd"]), self.payload["headline"])
        self.assertIn(intc.usd_eps(c["non_gaap_diluted_eps_usd"]), self.payload["headline"])
        if self.st.get("quarter_story"):
            self.assertIn(intc.usd_m(c["escrowed_shares_mtm_loss_usd_m"]), text)
        self.assertIn(intc.usd_bn(c["adjusted_free_cash_flow_usd_m"]), self.payload["headline"])


if __name__ == "__main__":
    unittest.main()
