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

The four-part layout adds three more classes. `ArmFourPartTest` pins the
section ids and titles and the next quarter's thresholds; `ArmSettledTest` pins
section one's closure and last quarter's thresholds; `ArmHighlightsTest` pins
the section-two readings the local note's conclusions call for. The thresholds
and verdicts are the analysis notes' content, re-read from the two note files
into `_checks["note"]` (which the builder never reads); the payload is compared
against that block, and every value a threshold is settled on is recomputed
here from the series. A roll re-keys `_checks` with the new note and edits
nothing in this file.
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
        for block in ("quarter_story", "next_kpi", "followup_closure", "prior_kpi_settlement",
                      "current_snapshot"):
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

def note_checks(staging: dict, block: str) -> dict:
    """The analysis notes' facts for the quarter `_checks` was keyed for.

    `_checks["note"]` was re-read from the two note files, not copied from the
    series blocks the builder reads. It describes the quarter `_checks` names, so
    a block stamped for any other quarter is being compared with the wrong note.
    """
    checks = staging["_checks"]
    if staging[block]["period"] != checks["period"]:
        raise AssertionError(f"`{block}` is stamped {staging[block]['period']!r} but `_checks` was keyed "
                             f"for {checks['period']!r}: re-key `_checks` (and its `note`) with the roll")
    return checks["note"]


def by_id(entries: list[dict]) -> dict:
    return {e["id"]: (e["threshold"], e["direction"], e["unit"]) for e in entries}


def metric_values(st: dict) -> dict:
    """Every metric a threshold may name, recomputed here from the series (not via the builder)."""
    q, kpi, rp = st["quarterly"], st["kpi"], st["related_party"]
    acv = dict(zip(kpi["dates"], kpi["acv"]))
    end = q["period_ends"][-1]
    return {"royalty": q["royalty"][-1],
            "royalty_yoy": (q["royalty"][-1] / q["royalty"][-5] - 1) * 100,
            "acv_yoy": (acv[end] / acv[f"{int(end[:4]) - 1}{end[4:]}"] - 1) * 100,
            "fcf": q["cash"]["free_cash_flow"][-1],
            "softbank_consulting": rp["softbank_affiliate"][-1]}


def room(value: float, threshold: float, direction: str) -> float:
    return (value - threshold) / abs(threshold) * 100 * (1 if direction == "up" else -1)


def unit(kind: str, value: float) -> str:
    return {"pct": f"{value:.1f}%", "usd_m": f"${value:,.0f}M"}[kind]


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
        kpi, note = self.st["next_kpi"], note_checks(self.st, "next_kpi")
        self.assertEqual(kpi["period"], self.payload["latest"]["disclosed_period_label"])
        last = self.st["quarterly"]["periods"][-1]
        year, n = int(last[:4]), int(last[5])
        self.assertEqual(kpi["for_period"], f"Q1 {year + 1}" if n == 4 else f"Q{n + 1} {year}")
        self.assertEqual(by_id(kpi["quantified"]), by_id(note["next_thresholds"]))
        for entry in kpi["quantified"]:
            self.assertNotIn("current", entry, "the current value is computed, never typed")
        # the payload draws each of the note's thresholds, at its value, on its side
        ex = by_ref(self.payload)
        table = next(t for t in self.payload["tables"] if t["title"].startswith("下季阈值"))
        for fact in note["next_thresholds"]:
            with self.subTest(threshold=fact["id"]):
                chart = ex[f"EX_NEXT_{fact['id'].upper()}"]
                self.assertEqual(set(chart["series"][1]["values"]), {fact["threshold"]})
                self.assertIn(f"下季阈值 {unit(fact['unit'], fact['threshold'])}", chart["title"])
                side = "上方" if fact["direction"] == "up" else "下方"
                self.assertIn(f"安全侧在{side}", chart["series"][1]["name"])
                row = next(r for r in table["rows"] if r[0] == chart["title"].split("：", 1)[0])
                self.assertEqual(row[1:3], ["高于阈值为安全" if fact["direction"] == "up" else "低于阈值为安全",
                                            unit(fact["unit"], fact["threshold"])])
        # the note's items that cannot be drawn are named on the page, not dropped
        description = self.sections["next_quarter"]["description"]
        self.assertEqual(len(kpi["disclosure_gated"]), len(note["next_unquantified"]))
        for item in note["next_unquantified"]:
            self.assertIn(item["keyword"], description)
            self.assertTrue(any(item["keyword"] in row[0] for row in table["rows"]), item["keyword"])

    def test_the_current_values_are_recomputed_from_the_series(self) -> None:
        q = self.st["quarterly"]
        values = metric_values(self.st)
        facts = {fact["id"]: fact for fact in note_checks(self.st, "next_kpi")["next_thresholds"]}
        bars = next(ex for ex in self.sections["next_quarter"]["exhibits"] if ex["kind"] == "diverging_bars")
        self.assertTrue(bars["title"].startswith(f"下季 {len(facts)} 条量化阈值："))
        self.assertEqual(len(bars["values"]), len(facts))
        for entry, value in zip(self.st["next_kpi"]["quantified"], bars["values"]):
            fact = facts[entry["id"]]
            self.assertAlmostEqual(value, round(room(values[entry["id"]], fact["threshold"], fact["direction"]), 1),
                                   places=6, msg=entry["id"])
        lines = [ex for ex in self.sections["next_quarter"]["exhibits"] if ex["kind"] == "lines"]
        self.assertEqual(len(lines), sum(1 for e in self.st["next_kpi"]["quantified"] if e.get("chart")))
        for ex in lines:
            self.assertIn("下季阈值", ex["title"])
            self.assertEqual(ex["xlabels"][-1], q["periods"][-1])
            threshold = ex["series"][1]["values"]
            self.assertEqual(len(set(threshold)), 1)

    def test_the_headroom_title_counts_the_breaches(self) -> None:
        entries = self.st["next_kpi"]["quantified"]
        values = metric_values(self.st)
        rooms = {e["id"]: room(values[e["id"]], e["threshold"], e["direction"]) for e in entries}
        over = [e for e in entries if rooms[e["id"]] < 0]
        bars = next(ex for ex in self.sections["next_quarter"]["exhibits"] if ex["kind"] == "diverging_bars")
        self.assertIn(f"{len(entries) - len(over)} 条在安全侧", bars["title"])
        if not over:
            closest = min(entries, key=lambda e: rooms[e["id"]])["metric"]
            gap = " " if closest[0].isascii() and closest[0].isalpha() else ""
            self.assertIn(f"离阈值最近的是{gap}{closest}", bars["title"])
        # push the first safe line past today's value: the title must now name it as breached
        target = next(e for e in entries if rooms[e["id"]] >= 0)

        def breach(s):
            entry = next(e for e in s["next_kpi"]["quantified"] if e["id"] == target["id"])
            entry["threshold"] = values[target["id"]] * (1.5 if target["direction"] == "up" else 0.5)
        payload = self.rebuilt(breach)
        title = next(ex["title"] for ex in exhibits_of(payload) if ex.get("ref") == "EX_NEXT_HEADROOM")
        self.assertIn(f"{len(entries) - len(over) - 1} 条在安全侧、{len(over) + 1} 条已越线", title)
        self.assertIn(target["metric"], title.split("已越线", 1)[1])

    def test_a_threshold_block_that_cannot_be_settled_stops_the_build(self) -> None:
        cases = (
            ("typed", lambda s: s["next_kpi"]["quantified"][0].__setitem__("current", 700.0)),
            ("names no series", lambda s: s["next_kpi"]["quantified"][0].__setitem__("id", "dso")),
            ("stamped for", lambda s: s["next_kpi"].__setitem__("for_period", "Q1 1999")),
            ("stamped", lambda s: s["next_kpi"].__setitem__("period", "Q1 1999")),
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
        lines = [f"EX_PRIOR_{e['id'].upper()}" for e in self.st["prior_kpi_settlement"]["quantified"]
                 if e.get("chart")]
        self.assertEqual(refs[:2 + len(lines)], ["EX_CLOSURE", "EX_PRIOR_HEADROOM"] + lines)
        self.assertEqual(refs[2 + len(lines)], "EX_REV_BAND", "the company's own record comes last")

    def test_the_closure_is_the_notes_section_zero(self) -> None:
        block, note = self.st["followup_closure"], note_checks(self.st, "followup_closure")
        self.assertEqual({item["n"]: item["verdict"] for item in block["items"]},
                         {item["n"]: item["verdict"] for item in note["closure"]})
        ex = self.ex["EX_CLOSURE"]
        self.assertEqual(dict(zip(ex["xlabels"], ex["values"])), note["closure_counts"])
        self.assertEqual(ex["title"], f"上季 {note['closure_items']} 条待验证问题："
                         + "、".join(f"{n} 条{label}" for label, n in note["closure_counts"].items()))
        # the note's own verdict for each item is on the page, in the category it was counted in
        for item in note["closure"]:
            self.assertIn(f"—— <b>{item['verdict']}</b>", ex["note"])
            self.assertIn(item["as_printed"].split("（", 1)[0][:2], item["verdict"])
        # the evidence names numbers the builder computes; recompute them here
        q, rp, kpi = self.st["quarterly"], self.st["related_party"], self.st["kpi"]
        acv = dict(zip(kpi["dates"], kpi["acv"]))
        ends = q["period_ends"]
        texts = [f"{(q['royalty'][-1] / q['royalty'][-5] - 1) * 100:+.1f}%",
                 f"{(q['royalty'][-2] / q['royalty'][-6] - 1) * 100:+.1f}%",
                 f"${rp['softbank_affiliate'][-1]:.1f}M",
                 f"{(acv[ends[-1]] / acv[ends[-5]] - 1) * 100:+.1f}%",
                 f"{(acv[ends[-2]] / acv[ends[-6]] - 1) * 100:+.1f}%"]
        for text in texts:
            self.assertIn(text.replace("-", "−"), ex["note"])
        self.assertNotRegex(ex["note"], r"\{[a-z_]+\}", "an evidence placeholder was left unfilled")
        for d in note["scorecard"]:
            self.assertIn(d["dimension"] + d["verdict"], ex["note"])

    def test_the_closure_counts_follow_the_items(self) -> None:
        labels = self.st["followup_closure"]["labels"]
        target = next(i for i in self.st["followup_closure"]["items"] if i["verdict"] != labels[0])

        def verify(s):
            next(i for i in s["followup_closure"]["items"] if i["n"] == target["n"])["verdict"] = labels[0]
        items = [dict(i, verdict=labels[0]) if i["n"] == target["n"] else i
                 for i in self.st["followup_closure"]["items"]]
        counts = [(label, sum(1 for i in items if i["verdict"] == label)) for label in labels]
        title = by_ref(self.rebuilt(verify))["EX_CLOSURE"]["title"]
        self.assertEqual(title, f"上季 {len(items)} 条待验证问题：" + "、".join(f"{n} 条{l}" for l, n in counts if n))

    def test_prior_thresholds_are_last_quarters_notes(self) -> None:
        block, note = self.st["prior_kpi_settlement"], note_checks(self.st, "prior_kpi_settlement")
        self.assertEqual(by_id(block["quantified"]), by_id(note["prior_thresholds"]))
        for entry in block["quantified"]:
            self.assertNotIn("actual", entry, "the settled value is computed, never typed")
        # the payload settles each of the note's thresholds at its value, on its side
        table = next(t for t in self.payload["tables"] if t["title"].startswith("上季阈值"))
        for fact in note["prior_thresholds"]:
            with self.subTest(threshold=fact["id"]):
                chart = self.ex[f"EX_PRIOR_{fact['id'].upper()}"]
                self.assertEqual(set(chart["series"][1]["values"]), {fact["threshold"]})
                self.assertIn(f"上季阈值 {unit(fact['unit'], fact['threshold'])}", chart["title"])
                side = "上方" if fact["direction"] == "up" else "下方"
                self.assertIn(f"安全侧在{side}", chart["series"][1]["name"])
                row = next(r for r in table["rows"] if r[0] == chart["title"].split("：", 1)[0])
                self.assertEqual(row[1:3], ["高于阈值为安全" if fact["direction"] == "up" else "低于阈值为安全",
                                            unit(fact["unit"], fact["threshold"])])
        # the note's section 8 items this quarter cannot settle are named, not dropped
        self.assertEqual(len(block["unsettled"]), len(note["prior_unquantified"]))
        description = self.payload["sections"][0]["description"]
        for item in note["prior_unquantified"]:
            self.assertIn(item["keyword"], description)
            self.assertTrue(any(item["keyword"] in row[0] for row in table["rows"]), item["keyword"])

    def test_the_settlement_is_recomputed_from_the_series(self) -> None:
        entries = self.st["prior_kpi_settlement"]["quantified"]
        values = metric_values(self.st)
        rooms = {e["id"]: room(values[e["id"]], e["threshold"], e["direction"]) for e in entries}
        broken = [e for e in entries if rooms[e["id"]] < 0]
        bars = self.ex["EX_PRIOR_HEADROOM"]
        self.assertTrue(bars["title"].startswith(
            f"上季 {len(entries)} 条量化阈值：{len(entries) - len(broken)} 条守住、{len(broken)} 条被击穿"))
        for entry, value in zip(entries, bars["values"]):
            self.assertAlmostEqual(value, round(rooms[entry["id"]], 1))
        for entry in entries:
            verdict = "守住" if rooms[entry["id"]] >= 0 else "已击穿"
            self.assertEqual(self.ex[f"EX_PRIOR_{entry['id'].upper()}"]["title"],
                             f"{entry['metric']}：{verdict}上季阈值 {unit(entry['unit'], entry['threshold'])}")
        # the SoftBank line keeps its zeros: the agreement earned nothing before 2024Q3
        if "EX_PRIOR_SOFTBANK_CONSULTING" in self.ex:
            ex = self.ex["EX_PRIOR_SOFTBANK_CONSULTING"]
            line = ex["series"][0]["values"]
            first = next(k for k, v in enumerate(line) if v)
            self.assertEqual(ex["xlabels"][first], "2024Q3")
            self.assertEqual(ex["xlabels"][0], self.st["related_party"]["periods"][0])
            self.assertTrue(all(v == 0 for v in line[:first]))

    def test_a_breached_threshold_reads_as_breached(self) -> None:
        entries = self.st["prior_kpi_settlement"]["quantified"]
        values = metric_values(self.st)
        target = next(e for e in entries if room(values[e["id"]], e["threshold"], e["direction"]) >= 0)

        def raise_bar(s):
            entry = next(e for e in s["prior_kpi_settlement"]["quantified"] if e["id"] == target["id"])
            entry["threshold"] = values[target["id"]] * (1.5 if target["direction"] == "up" else 0.5)
        ex = by_ref(self.rebuilt(raise_bar))
        self.assertIn(f"{target['metric']}：已击穿上季阈值", ex[f"EX_PRIOR_{target['id'].upper()}"]["title"])
        self.assertIn(f"被击穿（{target['metric']}", ex["EX_PRIOR_HEADROOM"]["title"])

    def test_the_notes_point_at_both_threshold_charts(self) -> None:
        pattern = re.compile(r"Exhibit (\d+) 与 Exhibit (\d+) 的阈值")
        found = [m.groups() for note in self.payload["notes"] for m in pattern.finditer(note)]
        self.assertEqual(found, [(str(self.ex["EX_PRIOR_HEADROOM"]["n"]), str(self.ex["EX_NEXT_HEADROOM"]["n"]))])

    def test_a_block_that_settles_another_quarter_stops_the_build(self) -> None:
        cases = (
            ("settles what was set in", lambda s: s["followup_closure"].__setitem__("set_in", "Q1 1999")),
            ("settles what was set in", lambda s: s["prior_kpi_settlement"].__setitem__("set_in", "Q1 1999")),
            ("not among its labels", lambda s: s["followup_closure"]["items"][0].__setitem__("verdict", "存疑")),
            ("stamped", lambda s: s["followup_closure"].__setitem__("period", "Q1 1999")),
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


class ArmHighlightsTest(unittest.TestCase):
    """Section two carries the note's conclusions that primary figures can draw."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.st = json.loads(arm.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = arm.build_payload(cls.st)
        cls.ex = by_ref(cls.payload)
        cls.q = cls.st["quarterly"]

    def rebuilt(self, edit) -> dict:
        changed = copy.deepcopy(self.st)
        edit(changed)
        self.assertNotEqual(changed, self.st, "the edit changed nothing")
        return arm.build_payload(changed)

    def test_the_highlights_are_this_quarters_readings(self) -> None:
        refs = [ex["ref"] for ex in self.payload["sections"][1]["exhibits"]]
        self.assertEqual(refs, ["EX_YOY", "EX_SOFTBANK", "EX_ACV_RPO", "EX_MARGIN", "EX_CAPEX", "EX_FCF",
                                "EX_CONTRACT"])
        for ref in refs:
            self.assertRegex(self.ex[ref]["title"], r"本季", ref)
        self.assertEqual(self.payload["brief"].count("<article>"), 4)

    def test_capex_is_the_three_lines_the_fcf_definition_takes_off(self) -> None:
        q, cash = self.q, self.q["cash"]
        three = [a + b + c for a, b, c in zip(cash["purchases_of_property_and_equipment"][1:],
                                               cash["purchases_of_intangible_assets"][1:],
                                               cash["payments_of_intangible_asset_obligations"][1:])]
        # the fiscal year that ended with the last fiscal Q4 on the axis, recounted by label
        last_q4 = max(k for k, label in enumerate(q["fiscal_labels"]) if label.startswith("Q4 "))
        year = q["fiscal_labels"][last_q4].split()[1]
        fy = [k for k, label in enumerate(q["fiscal_labels"]) if label.endswith(year)]
        self.assertEqual(fy, list(range(last_q4 - 3, last_q4 + 1)))
        fy_share = (sum(three[k - 1] for k in fy) / sum(q["revenue"][k] for k in fy)) * 100
        now_share = three[-1] / q["revenue"][-1] * 100
        ex = self.ex["EX_CAPEX"]
        self.assertEqual(ex["title"], f"资本性支出三项本季 ${three[-1]:,}M、占收入 {now_share:.1f}%；"
                                      f"FY{year[3:]} 全年 {fy_share:.1f}%")
        self.assertEqual([sum(v) for v in zip(*(s["values"] for s in ex["stacks"]))], three)
        self.assertEqual(len(ex["xlabels"]), len(three))
        # FCF identity: the three lines are exactly OCF minus FCF
        self.assertEqual(three, [o - f for o, f in zip(cash["operating_cash_flow"][1:], cash["free_cash_flow"][1:])])

    def test_softbank_is_read_against_license(self) -> None:
        rp, q = self.st["related_party"], self.q
        lic = dict(zip(q["periods"], q["license"]))
        share_now = rp["softbank_affiliate"][-1] / lic[rp["periods"][-1]] * 100
        share_then = rp["softbank_affiliate"][-5] / lic[rp["periods"][-5]] * 100
        ex = self.ex["EX_SOFTBANK"]
        self.assertTrue(ex["title"].startswith(
            f"软银咨询协议本季确认 ${rp['softbank_affiliate'][-1]:.1f}M，占 license and other 的 {share_now:.1f}%；"
            f"一年前 {share_then:.1f}%"), ex["title"])
        self.assertEqual(ex["xlabels"], rp["periods"])
        self.assertEqual(ex["line"]["values"][:9], [0.0] * 9, "the zeros before the agreement are drawn")

    def test_the_snapshot_closes_to_the_series(self) -> None:
        snap, q = self.st["current_snapshot"], self.q
        i, j = len(q["periods"]) - 1, q["periods"].index(snap["columns"][1])
        self.assertEqual(snap["columns"], [q["periods"][i], q["periods"][j]])
        rec = snap["reconciliation_operating_income"]
        for col, k in ((0, i), (1, j)):
            with self.subTest(column=snap["columns"][col]):
                self.assertEqual(q["gaap"]["operating_income"][k] + sum(v[col] for key, v in rec.items() if key != "row"),
                                 q["non_gaap"]["operating_income"][k])
                self.assertEqual(q["gaap"]["net_income"][k]
                                 + sum(v[col] for v in snap["non_cash_adjustments"].values())
                                 + sum(v[col] for v in snap["working_capital_changes"].values()),
                                 q["cash"]["operating_cash_flow"][k])

    def test_the_notes_print_the_snapshot(self) -> None:
        snap, q = self.st["current_snapshot"], self.q
        wc = [sum(v[col] for v in snap["working_capital_changes"].values()) for col in (0, 1)]
        fcf, j = q["cash"]["free_cash_flow"], q["periods"].index(snap["columns"][1])
        note = self.ex["EX_FCF"]["note"]
        for text in (arm.usd_m(wc[0]), arm.usd_m(wc[1]), arm.usd_m(fcf[-1] - wc[0]),
                     arm.usd_m(fcf[-1] - fcf[j]), arm.usd_m(wc[0] - wc[1])):
            self.assertIn(text, note)
        below = snap["below_operating_income"]
        ni = q["gaap"]["net_income"]
        margin = self.ex["EX_MARGIN"]["note"]
        sbc = snap["reconciliation_operating_income"]["share_based_compensation"][0]
        self.assertIn(f"{arm.usd_m(sbc)}（占收入 {sbc / q['revenue'][-1] * 100:.1f}%", margin)
        self.assertIn(arm.usd_m(ni[-1] - below["income_from_equity_investments"][0]
                                - below["income_tax_benefit_expense"][0]), margin)
        self.assertIn(arm.usd_m(ni[j] - below["income_from_equity_investments"][1]
                                - below["income_tax_benefit_expense"][1]), margin)

    def test_a_snapshot_that_does_not_close_stops_the_build(self) -> None:
        cases = (
            ("operating cash flow", lambda s: s["current_snapshot"]["working_capital_changes"]["other_liabilities"]
             .__setitem__(0, 284)),
            ("reconciliation does not close", lambda s: s["current_snapshot"]["reconciliation_operating_income"]
             ["share_based_compensation"].__setitem__(1, 240)),
            ("columns", lambda s: s["current_snapshot"].__setitem__(
                "columns", [s["current_snapshot"]["columns"][0], "1999Q1"])),
            ("stamped", lambda s: s["current_snapshot"].__setitem__("period", "Q1 1999")),
        )
        for message, edit in cases:
            with self.subTest(case=message):
                with self.assertRaisesRegex(ValueError, message):
                    self.rebuilt(edit)

    def test_one_quarter_words_leave_with_their_block(self) -> None:
        text = json.dumps(self.payload, ensure_ascii=False)
        for phrase in ("营运资本变动贡献", "税前、不含股权投资的利润"):
            self.assertIn(phrase, text)
        no_snap = json.dumps(self.rebuilt(lambda s: s.pop("current_snapshot")), ensure_ascii=False)
        for phrase in ("营运资本变动贡献", "税前、不含股权投资的利润", "<span>现金</span>"):
            self.assertNotIn(phrase, no_snap)
        call = self.st["quarter_story"]["call"]
        words = (f"royalty 同比 {call['next_quarter_royalty_yoy']}", call["fy_royalty_now"],
                 call["agi_gross_margin"], call["softbank_run_rate"])
        for word in words:
            self.assertIn(word, text)
        no_call = json.dumps(self.rebuilt(lambda s: s["quarter_story"].pop("call")), ensure_ascii=False)
        for word in words + ("电话会的说法",):
            self.assertNotIn(word, no_call)


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

    def test_the_snapshot_agrees_with_the_statements_reread(self) -> None:
        """`current_snapshot` was keyed from the shareholder letter; these `_checks` fields were
        read from the interim statements (arm-20260630.htm). Two documents, one set of numbers."""
        c, snap = self.c, self.st["current_snapshot"]
        rec, below = snap["reconciliation_operating_income"], snap["below_operating_income"]
        self.assertEqual(rec["share_based_compensation"],
                         [c["share_based_compensation_usd_m"], c["share_based_compensation_prior_year_usd_m"]])
        self.assertEqual(snap["non_cash_adjustments"]["share_based_compensation_cost"],
                         rec["share_based_compensation"])
        self.assertEqual(below["income_from_equity_investments"],
                         [c["income_from_equity_investments_usd_m"],
                          c["income_from_equity_investments_prior_year_usd_m"]])
        self.assertEqual(below["income_tax_benefit_expense"],
                         [c["income_tax_benefit_usd_m"], c["income_tax_benefit_prior_year_usd_m"]])
        wc = [sum(values[col] for values in snap["working_capital_changes"].values()) for col in (0, 1)]
        self.assertEqual(wc, [c["working_capital_change_usd_m"], c["working_capital_change_prior_year_usd_m"]])

    def test_the_page_prints_the_checked_figures(self) -> None:
        c, head = self.c, self.payload["headline"]
        self.assertIn(arm.usd_m(c["revenue_usd_m"]), head)
        self.assertIn(arm.usd_m(c["rpo_usd_m"], 1), head)
        ex = by_ref(self.payload)
        capex3 = (c["purchases_of_property_and_equipment_usd_m"] + c["purchases_of_intangible_assets_usd_m"]
                  + c["payments_of_intangible_asset_obligations_usd_m"])
        self.assertIn(arm.usd_m(capex3), ex["EX_CAPEX"]["title"])
        self.assertIn(arm.usd_m(c["purchases_of_property_and_equipment_usd_m"]), ex["EX_CAPEX"]["note"])
        self.assertIn(arm.usd_m(c["withholding_tax_on_vested_shares_usd_m"]), ex["EX_FCF"]["title"])
        self.assertIn(arm.usd_m(c["arm_china_revenue_usd_m"], 1), ex["EX_RELATED_SPLIT"]["title"])
        self.assertIn(arm.usd_m(c["softbank_common_control_revenue_usd_m"], 1), ex["EX_RELATED_SPLIT"]["title"])


if __name__ == "__main__":
    unittest.main()
