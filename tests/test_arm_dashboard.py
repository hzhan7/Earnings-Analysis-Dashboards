"""What the Arm page has to keep true.

The page makes four claims that a reader would repeat, and each one is
recomputed here from the series by a route that does not go through the
builder:

* `test_the_guidance_streak_is_counted_not_remembered` -- "the first N guided
  quarters all landed above the top of the range, and only M of the rest did"
  is a sentence about a record that grows every quarter. It is checked against
  the guidance rows directly, and then the rows are rewritten so the sentence
  must change.
* `test_the_statements_carry_the_rpo_the_letter_dropped` -- the letter stopped
  printing RPO; the page continues the line from the financial statements. Where
  both documents printed a quarter-end they must agree, or the splice is a
  splice of two different numbers.
* `test_related_party_split_closes_to_the_letter_total` -- the split comes from
  the statements' related-party note, the total from the letter's income
  statement. Two documents, one identity.
* `test_the_census_is_the_series_read_twice` -- the page says the non-GAAP
  recast is the only thing that changed on a second printing. The quarterly
  arrays carry both printings; the census rows are checked against them.

The page is rolled by editing `series/arm.json` alone (CLAUDE.md §9), so
nothing below reads a figure out of `build/arm.py`.
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

from build import arm  # noqa: E402
from build.all import ENTRIES  # noqa: E402
from build.board import round_half_up  # noqa: E402

ZERO_FLOORED_KINDS = {"bars_labeled", "gs_bar", "stacked_dual"}
QUARTER = re.compile(r"^\d{4}Q[1-4]$")


def calendar(fiscal: str) -> str:
    """``Q1 FYE27`` -> ``2026Q2``, written out here rather than imported."""
    quarter, year = fiscal.split()
    n, fy = int(quarter[1]), 2000 + int(year[3:])
    return f"{fy}Q1" if n == 4 else f"{fy - 1}Q{n + 1}"


def exhibits_of(payload: dict) -> list[dict]:
    return [ex for sec in payload["sections"] for ex in sec["exhibits"]]


def by_ref(payload: dict) -> dict:
    return {ex["ref"]: ex for ex in exhibits_of(payload) if "ref" in ex}


class ArmSeriesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.st = json.loads(arm.STAGING_PATH.read_text(encoding="utf-8"))
        cls.q = cls.st["quarterly"]

    # ── the axis ─────────────────────────────────────────────────────────────
    def test_the_quarterly_axis_is_contiguous_and_labelled_both_ways(self) -> None:
        q = self.q
        P = q["periods"]
        self.assertEqual(P[0], "2022Q1", "the prospectus table starts at the quarter to March 2022")
        for a, b in zip(P, P[1:]):
            year, n = int(a[:4]), int(a[5])
            self.assertEqual(b, f"{year + 1}Q1" if n == 4 else f"{year}Q{n + 1}")
        self.assertEqual([calendar(f) for f in q["fiscal_labels"]], P)
        for key in ("period_ends", "first_printed_by", "revenue", "license", "royalty",
                    "related_party_revenue"):
            self.assertEqual(len(q[key]), len(P), key)
        for block in ("gaap", "non_gaap", "non_gaap_first_printed", "cash"):
            for key, values in q[block].items():
                self.assertEqual(len(values), len(P), f"{block}.{key}")

    def test_no_quarter_was_printed_before_it_ended(self) -> None:
        q = self.q
        sources = {s["date"] for s in self.st["sources"]}
        for period, end, printed in zip(q["periods"], q["period_ends"], q["first_printed_by"]):
            with self.subTest(period=period):
                self.assertGreater(printed, end)
                self.assertIn(printed, sources, "names a document `sources` does not list")

    # ── identities ───────────────────────────────────────────────────────────
    def test_the_two_revenue_lines_close_every_quarter(self) -> None:
        q = self.q
        for k, period in enumerate(q["periods"]):
            with self.subTest(period=period):
                self.assertEqual(q["license"][k] + q["royalty"][k], q["revenue"][k])
                g = q["gaap"]
                self.assertEqual(q["revenue"][k] - g["cost_of_sales"][k], g["gross_profit"][k])
                self.assertEqual(g["gross_profit"][k] - g["operating_expenses"][k],
                                 g["operating_income"][k])

    def test_free_cash_flow_is_the_letters_definition_every_quarter(self) -> None:
        c = self.q["cash"]
        checked = 0
        for k, period in enumerate(self.q["periods"]):
            if c["free_cash_flow"][k] is None:
                continue
            with self.subTest(period=period):
                self.assertEqual(
                    c["operating_cash_flow"][k] - c["purchases_of_property_and_equipment"][k]
                    - c["purchases_of_intangible_assets"][k]
                    - c["payments_of_intangible_asset_obligations"][k],
                    c["free_cash_flow"][k])
            checked += 1
        self.assertGreaterEqual(checked, 16)

    def test_four_quarters_make_the_fiscal_year(self) -> None:
        q, a = self.q, self.st["annual"]
        checked = 0
        for year, rev, lic, roy in zip(a["years"], a["revenue"], a["license"], a["royalty"]):
            fy = int(year[2:])
            quarters = [f"{fy - 1}Q2", f"{fy - 1}Q3", f"{fy - 1}Q4", f"{fy}Q1"]
            if not all(p in q["periods"] for p in quarters):
                continue
            idx = [q["periods"].index(p) for p in quarters]
            with self.subTest(year=year):
                self.assertEqual(sum(q["revenue"][k] for k in idx), rev)
                self.assertEqual(sum(q["license"][k] for k in idx), lic)
                self.assertEqual(sum(q["royalty"][k] for k in idx), roy)
            checked += 1
        self.assertGreaterEqual(checked, 4, "fewer fiscal years close than the series holds")

    def test_related_party_split_closes_to_the_letter_total(self) -> None:
        rp, q = self.st["related_party"], self.q
        for k, period in enumerate(rp["periods"]):
            parts = (rp["arm_china"][k] + rp["softbank_controlled"][k] + rp["other"][k]
                     + rp["unattributed"][k])
            letter = q["related_party_revenue"][q["periods"].index(period)]
            with self.subTest(period=period):
                self.assertAlmostEqual(parts, rp["total"][k], delta=0.05)
                self.assertAlmostEqual(rp["license_related"][k] + rp["royalty_related"][k], rp["total"][k],
                                       delta=0.05)
                # the note prints to $0.1M, the letter to $1M
                self.assertLessEqual(abs(rp["total"][k] - letter), 0.5)

    def test_the_statements_carry_the_rpo_the_letter_dropped(self) -> None:
        kpi, rs = self.st["kpi"], self.st["rpo_statements"]
        both = 0
        for d, v in zip(kpi["dates"], kpi["rpo_letter"]):
            if v is None or d not in rs["dates"]:
                continue
            with self.subTest(date=d):
                self.assertLessEqual(abs(rs["rpo"][rs["dates"].index(d)] - v), 0.5)
            both += 1
        self.assertGreaterEqual(both, 10)
        last_letter = max(d for d, v in zip(kpi["dates"], kpi["rpo_letter"]) if v is not None)
        self.assertGreater(rs["dates"][-1], last_letter,
                           "the statements no longer run past the letter; the page's splice sentence is stale")

    # ── the census ───────────────────────────────────────────────────────────
    def test_the_census_is_the_series_read_twice(self) -> None:
        q = self.q
        rows = self.st["republication_census"]["rows"]
        for row in rows:
            self.assertEqual(row["periods_changed"], len(row["changes"]), row["row"])
            for change in row["changes"]:
                with self.subTest(row=row["row"], period=change["period"]):
                    self.assertNotEqual(change["first"], change["later"])
                    if row["basis"] == "non_gaap" and row["row"] in q["non_gaap"]:
                        k = q["periods"].index(change["period"])
                        self.assertEqual(q["non_gaap"][row["row"]][k], change["later"])
                        self.assertEqual(q["non_gaap_first_printed"][row["row"]][k], change["first"])
        # every non-GAAP difference between the two arrays is a census entry
        listed = {(r["row"], c["period"]) for r in rows if r["basis"] == "non_gaap" for c in r["changes"]}
        for key, later in q["non_gaap"].items():
            first = q["non_gaap_first_printed"][key]
            for k, period in enumerate(q["periods"]):
                if later[k] is not None and first[k] is not None and later[k] != first[k]:
                    self.assertIn((key, period), listed)
        # the page says revenue, GAAP lines, related-party revenue and cash never moved;
        # that sentence is conditional in the builder, and this pins that it is printed
        moved = [r["row"] for r in rows if (r["basis"] == "gaap" or r["basis"].startswith("cash"))
                 and r["periods_changed"]]
        self.assertEqual(moved, [])
        note = by_ref(arm.build_payload(self.st))["EX_CENSUS"]["note"]
        self.assertIn("一次都没变", note)
        patched = copy.deepcopy(self.st)
        revenue = next(r for r in patched["republication_census"]["rows"] if r["row"] == "revenue")
        revenue["changes"] = [{"period": "2024Q1", "first": 928, "later": 929, "first_in": "2024-05-08",
                               "later_in": "2025-05-07"}]
        revenue["periods_changed"] = 1
        self.assertNotIn("一次都没变", by_ref(arm.build_payload(patched))["EX_CENSUS"]["note"])

    def test_guidance_actuals_are_the_first_printing(self) -> None:
        q = self.q
        for row in self.st["guidance"]["quarterly"]:
            if row["revenue_actual"] is None:
                continue
            k = q["periods"].index(row["period"])
            with self.subTest(period=row["period"]):
                self.assertEqual(row["revenue_actual"], q["revenue"][k])
                self.assertEqual(row["eps_actual"], q["non_gaap_first_printed"]["diluted_eps"][k])
                self.assertLess(row["revenue_low"], row["revenue_high"])
                self.assertGreater(row["settled_on"], row["given_on"])


class ArmPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.st = json.loads(arm.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = arm.build_payload(cls.st)
        cls.ex = by_ref(cls.payload)

    def test_every_series_is_as_long_as_its_axis(self) -> None:
        for ex in exhibits_of(self.payload):
            n = len(ex.get("xlabels") or [])
            for key in ("series", "groups", "stacks"):
                for s in ex.get(key) or []:
                    self.assertEqual(len(s["values"]), n, f"Ex{ex['n']} {s['name']}")
            for key in ("line", "bar"):
                if isinstance(ex.get(key), dict):
                    self.assertEqual(len(ex[key]["values"]), n, f"Ex{ex['n']} {key}")

    def test_no_zero_floored_kind_carries_a_negative_value(self) -> None:
        for ex in exhibits_of(self.payload):
            if ex["kind"] not in ZERO_FLOORED_KINDS:
                continue
            values = list(ex.get("values") or [])
            for s in ex.get("stacks") or []:
                values += s["values"]
            self.assertTrue(all(v is None or v >= 0 for v in values), f"Ex{ex['n']}")

    def test_share_lines_declare_their_ceiling_where_the_renderer_reads_it(self) -> None:
        for ex in exhibits_of(self.payload):
            if ex["kind"] != "stacked_dual":
                continue
            self.assertNotIn("ymax", ex, f"Ex{ex['n']}: a top-level ymax is silently ignored")
            top = max(v for v in ex["line"]["values"] if v is not None)
            self.assertGreaterEqual(ex["line"].get("ymax", 60), top, f"Ex{ex['n']}")

    def test_the_guidance_streak_is_counted_not_remembered(self) -> None:
        rows = [r for r in self.st["guidance"]["quarterly"] if r["revenue_actual"] is not None]
        above = [r["revenue_actual"] > r["revenue_high"] for r in rows]
        lead = next((k for k, a in enumerate(above) if not a), len(above))
        rest = above[lead:]
        band = self.ex["EX_REV_BAND"]
        self.assertIn(f"{len(rows)} 个已完结季", band["title"])
        self.assertIn(f"{sum(above)} 季超出上限", band["title"])
        if lead >= 2 and rest:
            from build.board import cn_count
            self.assertIn(f"前{cn_count(lead)}个指引季", band["note"])
            self.assertIn(f"此后{cn_count(len(rest))}季只有{cn_count(sum(rest))}季", band["note"])

        # the same page on a record where every settled quarter beat the top:
        # the "此后" clause has nothing to describe and must go away
        beat = copy.deepcopy(self.st)
        for r in beat["guidance"]["quarterly"]:
            if r["revenue_actual"] is not None:
                r["revenue_actual"] = r["revenue_high"] + 1
        note = by_ref(arm.build_payload(beat))["EX_REV_BAND"]["note"]
        self.assertNotIn("此后", note)

    def test_the_widening_sentence_needs_the_widening(self) -> None:
        """「恰好在区间放宽的那一季结束」 is printed only while the two coincide."""
        note = self.ex["EX_REV_BAND"]["note"]
        rows = [r for r in self.st["guidance"]["quarterly"] if r["revenue_actual"] is not None]
        lead = next((k for k, r in enumerate(rows) if r["revenue_actual"] <= r["revenue_high"]), None)
        widths = [r["revenue_high"] - r["revenue_low"] for r in rows]
        coincide = lead is not None and lead > 0 and widths[lead] != widths[lead - 1]
        self.assertEqual("恰好在区间宽度" in note, coincide)
        moved = copy.deepcopy(self.st)
        settled = [r for r in moved["guidance"]["quarterly"] if r["revenue_actual"] is not None]
        if coincide:
            # Keep the streak running one quarter past the widening, and give the
            # range a *later* width change. Without that second edit a rule that
            # only asks "did the width change at all after the streak" prints the
            # same page as the real one ("did it change in the quarter the streak
            # ended"), and a mutation of the one into the other went green.
            settled[lead]["revenue_actual"] = settled[lead]["revenue_high"] + 1
            later = settled[lead + 3]
            later["revenue_high"] = later["revenue_low"] + 120
            self.assertLessEqual(later["revenue_actual"], later["revenue_high"])
            self.assertNotIn("恰好在区间宽度", by_ref(arm.build_payload(moved))["EX_REV_BAND"]["note"])

    def test_the_annual_chart_settles_on_the_fiscal_year_revenue(self) -> None:
        """Each vintage's diamond is that fiscal year's revenue as the income statement
        prints it -- not the letter's rounded cell ("$4.01b")."""
        ex = self.ex["EX_ANNUAL"]
        a = self.st["annual"]
        want = []
        for year in self.st["guidance"]["annual"]:
            fy = a["revenue"][a["years"].index("FY20" + year["fiscal_year"][3:])]
            want += [fy] * len(year["vintages"])
            self.assertIn(f"${fy:,.0f}M", ex["note"])
        self.assertEqual(ex["actual"], want)
        self.assertEqual(len(ex["xlabels"]), len(want))

    def test_the_rpo_title_follows_which_document_printed_the_last_point(self) -> None:
        title = self.ex["EX_ACV_RPO"]["title"]
        self.assertIn("财务报表照印", title)
        # if the letter had printed the last quarter-end too, there is no splice to report
        patched = copy.deepcopy(self.st)
        kpi, rs = patched["kpi"], patched["rpo_statements"]
        k = kpi["dates"].index(rs["dates"][-1])
        kpi["rpo_letter"][k] = round(rs["rpo"][-1])
        self.assertNotIn("财务报表照印", by_ref(arm.build_payload(patched))["EX_ACV_RPO"]["title"])

    def test_the_licence_counts_stop_where_the_letter_stopped(self) -> None:
        ex = self.ex["EX_LICENCES"]
        kpi = self.st["kpi"]
        last = max(d for d, v in zip(kpi["dates"], kpi["ata_licenses"]) if v is not None)
        self.assertEqual(ex["xlabels"][-1], f"{last[:4]}Q{(int(last[5:7]) - 1) // 3 + 1}")
        self.assertEqual("不再公布" in ex["title"], ex["xlabels"][-1] != self.st["quarterly"]["periods"][-1])

    def test_the_related_party_share_is_the_letters_ratio(self) -> None:
        q = self.st["quarterly"]
        want = q["related_party_revenue"][-1] / q["revenue"][-1] * 100
        self.assertIn(f"{want:.1f}%", self.payload["headline"])
        self.assertIn(f"{want:.1f}%", self.ex["EX_RELATED"]["title"])

    def test_home_card(self) -> None:
        entry = next(e for e in ENTRIES if e["slug"] == "arm")
        self.assertEqual(entry["group"], "semiconductor_ai")
        self.assertIn("本站按自然年季度标注", entry["cadence_label"])
        figures = arm.headline_metrics(self.st)
        self.assertEqual(len(figures), 3)
        self.assertTrue(figures[0].startswith("Revenue $"))

    def test_the_next_quarter_rolls_without_touching_the_code(self) -> None:
        """Append a synthetic quarter and rebuild: no code change, new labels."""
        rolled = copy.deepcopy(self.st)
        q = rolled["quarterly"]
        q["periods"].append("2026Q3")
        q["fiscal_labels"].append("Q2 FYE27")
        q["period_ends"].append("2026-09-30")
        q["first_printed_by"].append("2026-11-04")
        for key in ("revenue", "license", "royalty", "related_party_revenue"):
            q[key].append(q[key][-4])
        for block in ("gaap", "non_gaap", "non_gaap_first_printed", "cash"):
            for values in q[block].values():
                values.append(values[-4])
        rp = rolled["related_party"]
        rp["periods"].append("2026Q3")
        for key, values in rp.items():
            if key != "periods" and isinstance(values, list) and len(values) == len(rp["periods"]) - 1:
                values.append(values[-4])
        for block in ("rpo_statements",):
            b = rolled[block]
            b["dates"].append("2026-09-30")
            for key, values in b.items():
                if key != "dates" and isinstance(values, list) and len(values) == len(b["dates"]) - 1:
                    values.append(values[-1])
        kpi = rolled["kpi"]
        kpi["dates"].append("2026-09-30")
        for key, values in kpi.items():
            if key != "dates" and isinstance(values, list) and len(values) == len(kpi["dates"]) - 1:
                values.append(values[-4] if key == "acv" else (None if key != "printed_by" else "2026-11-04"))
        ca = rolled["contract_assets"]
        ca["dates"].append("2026-09-30")
        for key, values in ca.items():
            if key != "dates" and isinstance(values, list) and len(values) == len(ca["dates"]) - 1:
                values.append(values[-1])
        wt = rolled["withholding_tax_on_vested_shares"]
        wt["periods"].append("2026Q3")
        wt["values"].append(wt["values"][-4])
        g = rolled["guidance"]["quarterly"]
        open_row = next(r for r in g if r["revenue_actual"] is None)
        open_row.update(settled_on="2026-11-04", revenue_actual=q["revenue"][-1],
                        eps_actual=q["non_gaap_first_printed"]["diluted_eps"][-1], opex_actual=700)
        rolled["latest"] = dict(rolled["latest"], period="Q3 2026")
        # every one-quarter block is last quarter's once the arrays move on
        for block in ("quarter_story", "next_kpi", "followup_closure", "prior_kpi_settlement"):
            rolled.pop(block, None)
        rolled["sources"] = rolled["sources"] + [
            {"label": "Q2 FYE27 股东信（6-K EX-99.2，2026-11-04）",
             "url": "https://www.sec.gov/Archives/edgar/data/1973239/x/y.htm", "date": "2026-11-04",
             "kind": "letter"}]
        payload = arm.build_payload(rolled)
        self.assertEqual(payload["latest"]["disclosed_period_label"], "Q3 2026")
        self.assertIn("2026 年第三季度", payload["title"])
        self.assertIn("FY27 Q2", payload["title"])
        mix = by_ref(payload)["EX_MIX"]
        self.assertEqual(mix["xlabels"][-1], "2026Q3")
        # The letter stopped printing RPO and the licence counts in 2026Q2. A quarter
        # later that is history, and every sentence that said 「本季起」 has to say when.
        self.assertIn("本季起", json.dumps(self.payload, ensure_ascii=False))
        rolled_text = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("本季起", rolled_text)
        self.assertIn("2026Q2 起", rolled_text)


FOUR_PARTS = [("settled", "一、上季跟踪指标兑现了吗"), ("quarter_highlights", "二、本季重点"),
              ("next_quarter", "三、下季要跟踪什么"), ("routine", "四、长期常规跟踪")]

# Section 8 of the 2026-07-29 analysis note (「关键观察指标」, 本季 KPI 表), copied by
# hand: these are the note's thresholds, not filed figures, so writing them out
# here is the check that the series block carries what the note says.
NEXT_THRESHOLDS = {"royalty": (690.0, "up", "usd_m"), "acv_yoy": (10.0, "up", "pct"),
                   "fcf": (250.0, "up", "usd_m")}
NEXT_GATED = ("AGI CPU", "智能手机")

# Section 0 of the same note: the five follow-ups the 2026-05-06 note left, and
# the verdict it gave each. The note prints no tally line; this is the tally of
# its verdict column, with #5 「已验证且恶化」 counted as verified.
CLOSURE_VERDICTS = {1: "已验证", 2: "未兑现", 3: "已验证", 4: "部分验证", 5: "已验证"}
CLOSURE_COUNTS = {"已验证": 3, "部分验证": 1, "未兑现": 1}

# Section 8 of the 2026-05-06 note: two of its five thresholds are numbers this
# quarter can settle, three cannot (no figure / not yet due).
PRIOR_THRESHOLDS = {"royalty_yoy": (15.0, "up", "pct"), "softbank_consulting": (180.0, "up", "usd_m")}
PRIOR_UNSETTLED = ("数据中心 royalty", "FY27 Q4 芯片收入", "累计需求")


class ArmFourPartTest(unittest.TestCase):
    """The page is cut into the site's four sections, and each one holds what its title says."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.st = json.loads(arm.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = arm.build_payload(cls.st)
        cls.sections = {sec["id"]: sec for sec in cls.payload["sections"]}

    def rebuilt(self, edit) -> dict:
        changed = copy.deepcopy(self.st)
        edit(changed)
        self.assertNotEqual(changed, self.st, "the edit changed nothing")
        return arm.build_payload(changed)

    def test_four_sections_in_order_and_the_page_says_so(self) -> None:
        self.assertEqual([(sec["id"], sec["title"]) for sec in self.payload["sections"]], FOUR_PARTS)
        for sec in self.payload["sections"]:
            self.assertTrue(sec["exhibits"], sec["id"])
        self.assertTrue(self.payload["notes"][0].startswith(
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列"), self.payload["notes"][0])
        text = json.dumps(self.payload, ensure_ascii=False)
        self.assertNotIn("六段", text)
        numbers = [ex["n"] for sec in self.payload["sections"] for ex in sec["exhibits"]]
        self.assertEqual(numbers, list(range(2, 2 + len(numbers))))
        self.assertEqual(self.payload["tables"][0]["n"], numbers[-1] + 1)

    def test_the_guidance_record_sits_in_the_settled_section(self) -> None:
        """What the company guided last quarter is settled in section one, not called 本季重点."""
        refs = [ex["ref"] for ex in self.sections["settled"]["exhibits"]]
        for ref in ("EX_REV_BAND", "EX_EPS_BAND", "EX_ANNUAL"):
            self.assertIn(ref, refs)
        routine = [ex["ref"] for ex in self.sections["routine"]["exhibits"]]
        self.assertIn("EX_MIX", routine)
        self.assertIn("EX_CENSUS", routine)

    def test_next_quarter_thresholds_are_the_notes(self) -> None:
        kpi = self.st["next_kpi"]
        self.assertEqual(kpi["period"], "Q2 2026")
        self.assertEqual(kpi["for_period"], "Q3 2026")
        got = {e["id"]: (e["threshold"], e["direction"], e["unit"]) for e in kpi["quantified"]}
        self.assertEqual(got, NEXT_THRESHOLDS)
        gated = [g["metric"] for g in kpi["disclosure_gated"]]
        self.assertEqual(len(gated), len(NEXT_GATED))
        for word, metric in zip(NEXT_GATED, gated):
            self.assertIn(word, metric)
        for entry in kpi["quantified"]:
            self.assertNotIn("current", entry, "the current value is computed, never typed")

    def test_the_current_values_are_recomputed_from_the_series(self) -> None:
        q, kpi = self.st["quarterly"], self.st["kpi"]
        acv = dict(zip(kpi["dates"], kpi["acv"]))
        want = {"royalty": q["royalty"][-1],
                "acv_yoy": (acv["2026-06-30"] / acv["2025-06-30"] - 1) * 100,
                "fcf": q["cash"]["free_cash_flow"][-1]}
        bars = next(ex for ex in self.sections["next_quarter"]["exhibits"] if ex["kind"] == "diverging_bars")
        self.assertTrue(bars["title"].startswith(f"下季 {len(want)} 条量化阈值："))
        for entry, value in zip(self.st["next_kpi"]["quantified"], bars["values"]):
            threshold, direction, _ = NEXT_THRESHOLDS[entry["id"]]
            room = (want[entry["id"]] - threshold) / threshold * 100 * (1 if direction == "up" else -1)
            self.assertAlmostEqual(value, round(room, 1), places=6, msg=entry["id"])
        lines = [ex for ex in self.sections["next_quarter"]["exhibits"] if ex["kind"] == "lines"]
        self.assertEqual(len(lines), sum(1 for e in self.st["next_kpi"]["quantified"] if e.get("chart")))
        for ex in lines:
            self.assertIn("下季阈值", ex["title"])
            self.assertEqual(ex["xlabels"][-1], q["periods"][-1])
            threshold = ex["series"][1]["values"]
            self.assertEqual(len(set(threshold)), 1)

    def test_the_headroom_title_counts_the_breaches(self) -> None:
        bars = next(ex for ex in self.sections["next_quarter"]["exhibits"] if ex["kind"] == "diverging_bars")
        self.assertIn("3 条在安全侧", bars["title"])
        self.assertIn("离阈值最近的是 royalty 收入", bars["title"])
        # push the royalty line above today's value: the title must now name it as breached
        def breach(s):
            next(e for e in s["next_kpi"]["quantified"] if e["id"] == "royalty")["threshold"] = 720.0
        payload = self.rebuilt(breach)
        title = next(ex["title"] for ex in exhibits_of(payload) if ex.get("ref") == "EX_NEXT_HEADROOM")
        self.assertIn("2 条在安全侧、1 条已越线（royalty 收入）", title)

    def test_a_threshold_block_that_cannot_be_settled_stops_the_build(self) -> None:
        cases = (
            ("typed", lambda s: s["next_kpi"]["quantified"][0].__setitem__("current", 700.0)),
            ("names no series", lambda s: s["next_kpi"]["quantified"][0].__setitem__("id", "dso")),
            ("stamped for", lambda s: s["next_kpi"].__setitem__("for_period", "Q4 2026")),
            ("stamped", lambda s: s["next_kpi"].__setitem__("period", "Q1 2026")),
        )
        for message, edit in cases:
            with self.subTest(case=message):
                with self.assertRaisesRegex(ValueError, message):
                    self.rebuilt(edit)

    def test_an_absent_next_block_leaves_the_section_empty_not_stale(self) -> None:
        payload = self.rebuilt(lambda s: s.pop("next_kpi"))
        section = next(sec for sec in payload["sections"] if sec["id"] == "next_quarter")
        self.assertEqual(section["exhibits"], [])
        self.assertIn("还没有设定", section["description"])
        rest = {k: v for k, v in payload.items() if k != "sections"}
        self.assertNotIn("下季阈值", json.dumps(rest, ensure_ascii=False))
        for sec in payload["sections"]:
            self.assertNotIn("下季阈值", json.dumps(sec["exhibits"], ensure_ascii=False))


class ArmSettledTest(unittest.TestCase):
    """Section one settles what last quarter left: its questions, then its thresholds."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.st = json.loads(arm.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = arm.build_payload(cls.st)
        cls.settled = cls.payload["sections"][0]["exhibits"]
        cls.ex = by_ref(cls.payload)

    def rebuilt(self, edit) -> dict:
        changed = copy.deepcopy(self.st)
        edit(changed)
        self.assertNotEqual(changed, self.st, "the edit changed nothing")
        return arm.build_payload(changed)

    def test_section_one_opens_with_the_closure_then_the_thresholds(self) -> None:
        refs = [ex["ref"] for ex in self.settled]
        self.assertEqual(refs[:4], ["EX_CLOSURE", "EX_PRIOR_HEADROOM", "EX_PRIOR_ROYALTY_YOY",
                                    "EX_PRIOR_SOFTBANK_CONSULTING"])
        self.assertLess(refs.index("EX_PRIOR_HEADROOM"), refs.index("EX_REV_BAND"))

    def test_the_closure_is_the_notes_section_zero(self) -> None:
        block = self.st["followup_closure"]
        self.assertEqual((block["period"], block["set_in"]), ("Q2 2026", "Q1 2026"))
        self.assertEqual({item["n"]: item["verdict"] for item in block["items"]}, CLOSURE_VERDICTS)
        ex = self.ex["EX_CLOSURE"]
        self.assertEqual(dict(zip(ex["xlabels"], ex["values"])), CLOSURE_COUNTS)
        self.assertEqual(ex["title"], "上季 5 条待验证问题：3 条已验证、1 条部分验证、1 条未兑现")
        # the evidence names numbers the builder computes; recompute them here
        q, rp, kpi = self.st["quarterly"], self.st["related_party"], self.st["kpi"]
        acv = dict(zip(kpi["dates"], kpi["acv"]))
        for text in (f"+{(q['royalty'][-1] / q['royalty'][-5] - 1) * 100:.1f}%",
                     f"+{(q['royalty'][-2] / q['royalty'][-6] - 1) * 100:.1f}%",
                     f"${rp['softbank_affiliate'][-1]:.1f}M",
                     f"+{(acv['2026-06-30'] / acv['2025-06-30'] - 1) * 100:.1f}%",
                     f"+{(acv['2026-03-31'] / acv['2025-03-31'] - 1) * 100:.1f}%"):
            self.assertIn(text, ex["note"])
        self.assertNotRegex(ex["note"], r"\{[a-z_]+\}", "an evidence placeholder was left unfilled")
        for word in ("方向对", "幅度低估", "归因部分错", "时点错一个季度"):
            self.assertIn(word, ex["note"])

    def test_the_closure_counts_follow_the_items(self) -> None:
        def verify_two(s):
            next(i for i in s["followup_closure"]["items"] if i["n"] == 2)["verdict"] = "已验证"
        title = by_ref(self.rebuilt(verify_two))["EX_CLOSURE"]["title"]
        self.assertEqual(title, "上季 5 条待验证问题：4 条已验证、1 条部分验证")

    def test_prior_thresholds_are_last_quarters_notes(self) -> None:
        block = self.st["prior_kpi_settlement"]
        self.assertEqual((block["period"], block["set_in"]), ("Q2 2026", "Q1 2026"))
        got = {e["id"]: (e["threshold"], e["direction"], e["unit"]) for e in block["quantified"]}
        self.assertEqual(got, PRIOR_THRESHOLDS)
        self.assertEqual(len(block["quantified"]) + len(block["unsettled"]), 5, "the note's section 8 has five")
        for word, item in zip(PRIOR_UNSETTLED, block["unsettled"]):
            self.assertIn(word, item["metric"])
        for entry in block["quantified"]:
            self.assertNotIn("actual", entry, "the settled value is computed, never typed")

    def test_the_settlement_is_recomputed_from_the_series(self) -> None:
        q, rp = self.st["quarterly"], self.st["related_party"]
        actual = {"royalty_yoy": (q["royalty"][-1] / q["royalty"][-5] - 1) * 100,
                  "softbank_consulting": rp["softbank_affiliate"][-1]}
        bars = self.ex["EX_PRIOR_HEADROOM"]
        self.assertEqual(bars["title"], "上季 2 条量化阈值：2 条守住、0 条被击穿")
        for entry, value in zip(self.st["prior_kpi_settlement"]["quantified"], bars["values"]):
            threshold = PRIOR_THRESHOLDS[entry["id"]][0]
            self.assertAlmostEqual(value, round((actual[entry["id"]] - threshold) / threshold * 100, 1))
        self.assertEqual(self.ex["EX_PRIOR_ROYALTY_YOY"]["title"], "royalty 同比：守住上季阈值 15.0%")
        self.assertEqual(self.ex["EX_PRIOR_SOFTBANK_CONSULTING"]["title"],
                         "软银咨询协议季度收入：守住上季阈值 $180M")
        # the SoftBank line keeps its zeros: the agreement began in 2024Q3
        line = self.ex["EX_PRIOR_SOFTBANK_CONSULTING"]["series"][0]["values"]
        first = next(k for k, v in enumerate(line) if v)
        self.assertEqual(self.ex["EX_PRIOR_SOFTBANK_CONSULTING"]["xlabels"][first], "2024Q3")
        self.assertTrue(all(v == 0 for v in line[:first]))

    def test_a_breached_threshold_reads_as_breached(self) -> None:
        def raise_bar(s):
            next(e for e in s["prior_kpi_settlement"]["quantified"] if e["id"] == "royalty_yoy")["threshold"] = 25.0
        ex = by_ref(self.rebuilt(raise_bar))
        self.assertEqual(ex["EX_PRIOR_ROYALTY_YOY"]["title"], "royalty 同比：已击穿上季阈值 25.0%")
        self.assertEqual(ex["EX_PRIOR_HEADROOM"]["title"], "上季 2 条量化阈值：1 条守住、1 条被击穿（royalty 同比）")

    def test_the_notes_point_at_both_threshold_charts(self) -> None:
        pattern = re.compile(r"Exhibit (\d+) 与 Exhibit (\d+) 的阈值")
        found = [m.groups() for note in self.payload["notes"] for m in pattern.finditer(note)]
        self.assertEqual(found, [(str(self.ex["EX_PRIOR_HEADROOM"]["n"]), str(self.ex["EX_NEXT_HEADROOM"]["n"]))])

    def test_a_block_that_settles_another_quarter_stops_the_build(self) -> None:
        cases = (
            ("settles what was set in", lambda s: s["followup_closure"].__setitem__("set_in", "Q4 2025")),
            ("settles what was set in", lambda s: s["prior_kpi_settlement"].__setitem__("set_in", "Q4 2025")),
            ("not among its labels", lambda s: s["followup_closure"]["items"][0].__setitem__("verdict", "存疑")),
            ("stamped", lambda s: s["followup_closure"].__setitem__("period", "Q1 2026")),
            ("typed", lambda s: s["prior_kpi_settlement"]["quantified"][0].__setitem__("actual", 20.0)),
        )
        for message, edit in cases:
            with self.subTest(case=message):
                with self.assertRaisesRegex(ValueError, message):
                    self.rebuilt(edit)

    def test_absent_blocks_drop_their_charts_and_the_words_about_them(self) -> None:
        for key, ref, phrase in (("followup_closure", "EX_CLOSURE", "条待验证问题"),
                                 ("prior_kpi_settlement", "EX_PRIOR_HEADROOM", "上季阈值")):
            with self.subTest(block=key):
                payload = self.rebuilt(lambda s, key=key: s.pop(key))
                self.assertNotIn(ref, by_ref(payload))
                self.assertNotIn(phrase, json.dumps(payload, ensure_ascii=False))
                numbers = [ex["n"] for ex in exhibits_of(payload)]
                self.assertEqual(numbers, list(range(2, 2 + len(numbers))))


class ArmChecksTest(unittest.TestCase):
    """`_checks` is an independent re-read of the primary filing.

    The series is built from the shareholder letters (EX-99.2) and the XBRL
    R-files. `_checks` was read from the human-readable body of the interim
    financial statements furnished the same day (`arm-20260630.htm`) -- a
    different document from the letter, and a different layer from the XBRL --
    by a reader that did not see the series. The builder never reads the block
    (`tests/test_data_only_roll.py` proves that).
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.st = json.loads(arm.STAGING_PATH.read_text(encoding="utf-8"))
        cls.c = cls.st["_checks"]
        cls.payload = arm.build_payload(cls.st)
        cls.q = cls.st["quarterly"]

    def test_the_page_names_the_checked_period(self) -> None:
        c, latest = self.c, self.payload["latest"]
        self.assertEqual(c["period"], latest["disclosed_period_label"])
        self.assertEqual(c["period_end"], latest["period_end"])
        self.assertEqual(c["release_date"], latest["release_date"])
        self.assertIn(f"截至 {c['period_end']}", self.payload["subtitle"])
        self.assertIn(f"发布 {c['release_date']}", self.payload["subtitle"])
        self.assertIn("arm-20260630.htm", c["source"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        c, q = self.c, self.q
        k = len(q["periods"]) - 1
        j = q["periods"].index(f"{int(q['periods'][k][:4]) - 1}{q['periods'][k][4:]}")
        for key, got in (("revenue_usd_m", q["revenue"][k]), ("license_usd_m", q["license"][k]),
                         ("royalty_usd_m", q["royalty"][k]),
                         ("revenue_prior_year_usd_m", q["revenue"][j]),
                         ("license_prior_year_usd_m", q["license"][j]),
                         ("royalty_prior_year_usd_m", q["royalty"][j]),
                         ("revenue_related_parties_usd_m", q["related_party_revenue"][k]),
                         ("revenue_related_parties_prior_year_usd_m", q["related_party_revenue"][j]),
                         ("cost_of_sales_usd_m", q["gaap"]["cost_of_sales"][k]),
                         ("operating_income_usd_m", q["gaap"]["operating_income"][k]),
                         ("operating_income_prior_year_usd_m", q["gaap"]["operating_income"][j]),
                         ("net_income_usd_m", q["gaap"]["net_income"][k]),
                         ("diluted_eps_usd", q["gaap"]["diluted_eps"][k]),
                         ("operating_cash_flow_usd_m", q["cash"]["operating_cash_flow"][k]),
                         ("purchases_of_property_and_equipment_usd_m",
                          q["cash"]["purchases_of_property_and_equipment"][k]),
                         ("purchases_of_intangible_assets_usd_m", q["cash"]["purchases_of_intangible_assets"][k]),
                         ("payments_of_intangible_asset_obligations_usd_m",
                          q["cash"]["payments_of_intangible_asset_obligations"][k])):
            with self.subTest(key=key):
                self.assertEqual(got, c[key])
        rp = self.st["related_party"]
        self.assertEqual(rp["periods"][-1], q["periods"][k])
        self.assertAlmostEqual(rp["arm_china"][-1], c["arm_china_revenue_usd_m"], places=6)
        self.assertAlmostEqual(rp["softbank_controlled"][-1], c["softbank_common_control_revenue_usd_m"],
                               places=6)
        self.assertEqual(rp["license_related"][-1], c["license_related_usd_m"])
        self.assertEqual(rp["royalty_related"][-1], c["royalty_related_usd_m"])
        rs = self.st["rpo_statements"]
        self.assertEqual(rs["dates"][-1], c["period_end"])
        self.assertEqual(rs["rpo"][-1], c["rpo_usd_m"])
        self.assertEqual(rs["within_12m_pct"][-1], c["rpo_within_12_months_pct"])
        ca = self.st["contract_assets"]
        self.assertEqual(ca["current_total"][-1], c["contract_assets_current_usd_m"])
        self.assertEqual(ca["current_related"][-1], c["contract_assets_current_related_usd_m"])
        wt = self.st["withholding_tax_on_vested_shares"]
        self.assertEqual(wt["values"][-1], c["withholding_tax_on_vested_shares_usd_m"])

    def test_the_rounding_the_page_uses_is_the_companys(self) -> None:
        """Ratios the page prints, recomputed from the checked figures and rounded half-up
        the way the letter rounds its margins (7.1%, 30.1%)."""
        c, head = self.c, self.payload["headline"]
        gaap = round_half_up(c["operating_income_usd_m"] / c["revenue_usd_m"] * 100, 1)
        self.assertIn(f"GAAP {gaap}%", head)
        related = round_half_up(c["revenue_related_parties_usd_m"] / c["revenue_usd_m"] * 100, 1)
        self.assertIn(f"关联方收入占 {related}%", head)
        related_ca = round_half_up(c["contract_assets_current_related_usd_m"]
                                   / c["contract_assets_current_usd_m"] * 100, 1)
        self.assertIn(f"占 {related_ca}%", by_ref(self.payload)["EX_CONTRACT"]["title"])

    def test_the_page_prints_the_checked_figures(self) -> None:
        c, head = self.c, self.payload["headline"]
        self.assertIn(arm.usd_m(c["revenue_usd_m"]), head)
        self.assertIn(arm.usd_m(c["rpo_usd_m"], 1), head)
        ex = by_ref(self.payload)
        self.assertIn(arm.usd_m(c["purchases_of_property_and_equipment_usd_m"]), ex["EX_CAPEX"]["title"])
        self.assertIn(arm.usd_m(c["withholding_tax_on_vested_shares_usd_m"]), ex["EX_FCF"]["title"])
        self.assertIn(arm.usd_m(c["arm_china_revenue_usd_m"], 1), ex["EX_RELATED_SPLIT"]["title"])
        self.assertIn(arm.usd_m(c["softbank_common_control_revenue_usd_m"], 1), ex["EX_RELATED_SPLIT"]["title"])


if __name__ == "__main__":
    unittest.main()
