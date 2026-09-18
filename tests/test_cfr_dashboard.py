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
"""

from __future__ import annotations

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
from build.board import UNIT_FORMATS, headroom  # noqa: E402

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
        self.assertEqual(self.q[-1], "2026Q2")
        self.assertEqual(len(self.q), 42)
        for a, b in zip(self.q, self.q[1:]):
            self.assertTrue(quarter_step(a, b), (a, b))

    def test_calendar_quarters_map_onto_a_march_fiscal_year(self) -> None:
        """Fiscal Q1 is April-June, so it is the calendar Q2 of the year before
        the fiscal year's number; fiscal Q4 is January-March of that same year."""
        expected = {"2026Q2": "FY27Q1", "2025Q3": "FY26Q2", "2025Q4": "FY26Q3",
                    "2026Q1": "FY26Q4", "2016Q1": "FY16Q4"}
        mapping = dict(zip(self.q, self.s["fiscal_quarters"]))
        for quarter, fiscal in expected.items():
            self.assertEqual(mapping[quarter], fiscal)
        self.assertEqual(self.s["latest"]["fiscal_label"], "FY27 Q1")

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
        basis = self.s["quarter_basis"]
        self.assertEqual((basis.count("printed"), basis.count("derived"), basis.count("missing")), (33, 5, 4))
        self.assertEqual([q for q, b in zip(self.q, basis) if b == "derived"],
                         ["2016Q1", "2017Q1", "2018Q1", "2018Q3", "2019Q1"])

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
        self.assertEqual(compared, 72)

    def test_every_later_print_matches_the_subtraction_but_one(self) -> None:
        checks = self.s["derived_checks"]
        self.assertEqual(len(checks), 180)
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
        self.assertEqual(len(self.s["restatement_census"]), 194)
        self.assertEqual(self.s["restatement_paired_readings"], 1930)

    def test_a_printed_second_half_matches_the_subtraction(self) -> None:
        checks = self.s["half_checks"]
        self.assertGreaterEqual(len({c["half"] for c in checks}), 5)
        for check in checks:
            self.assertEqual(check["printed_total"], check["derived_total"], check["half"])

    def test_each_half_year_pair_comes_from_one_generation_of_documents(self) -> None:
        docs = {d["doc_id"]: d for d in self.s["documents"]}
        for fy, src in self.s["half_sources"].items():
            year_doc, h1_doc = docs[src["year_doc"]], docs[src["h1_doc"]]
            self.assertEqual(year_doc["kind"], "annual_results")
            self.assertEqual(h1_doc["kind"], "interim_results")
            expected = f"FY{int(fy[2:]) + 1}" if src["mode"] == "next_year" else fy
            self.assertEqual(year_doc["fiscal_year"], expected, fy)
            self.assertEqual(h1_doc["fiscal_year"], expected, fy)
        # the two years that fall back do so for a recorded reason
        own = sorted(fy for fy, v in self.s["half_sources"].items() if v["mode"] == "own_year")
        self.assertEqual(own, ["FY19", "FY21", "FY26"])

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
        claim = next(c for c in self.s["company_claims"] if c["key"] == "jewellery_streak")
        rates = self.s["quarterly_cer_pct"][claim["line"]]
        streak = 0
        for v in reversed(rates):
            if v is None or v < claim["threshold_pct"]:
                break
            streak += 1
        self.assertEqual(streak, claim["count"])
        self.assertIn("seventh consecutive quarter of double-digit growth", claim["quote"])

    def test_the_jewellery_range_breaks_for_the_first_time_in_the_latest_half(self) -> None:
        hv = cfr.half_view(self.s)
        margin = hv["margin"]["jewellery_maisons"]
        below = [i for i in hv["jewel_after"] if margin[i] < 30.0]
        self.assertEqual(below, [hv["last"]])
        self.assertTrue(hv["jewel_first_break"])
        seg = self.s["half_segment_result_eur_m"]["jewellery_maisons"][hv["last"]]
        sales = self.s["half_segment_sales_eur_m"]["jewellery_maisons"][hv["last"]]
        self.assertAlmostEqual(seg / sales * 100, 28.4, delta=0.05)


class CfrPayloadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.s = load()
        cls.payload = cfr.build_payload(cls.s)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]
        cls.qv = cfr.quarter_view(cls.s)
        cls.hv = cfr.half_view(cls.s)

    def quarterly(self) -> list[dict]:
        return [ex for ex in self.exhibits if ex.get("xlabels") == self.s["quarters"]]

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
        half = [ex for ex in self.exhibits if ex["xlabels"] and re.fullmatch(r"\d{4}-\d{2}", ex["xlabels"][0])]
        self.assertEqual(len(half), 5)
        for exhibit in half:
            months = [label[5:] for label in exhibit["xlabels"]]
            self.assertEqual(len(months), len(self.s["halves"]))
            self.assertEqual(months, ["09", "03"] * (len(months) // 2), exhibit["title"])

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
        self.assertIn(f"连续第 {self.qv['streak']} 个", headline)
        jm = self.hv["margin"]["jewellery_maisons"][self.hv["last"]]
        self.assertIn(f"{jm:.1f}%", headline)
        self.assertIn(f"{self.hv['jewel_of_op'][self.hv['last']]:.0f}%", headline)
        e = self.s["quarterly_eur_m"]["total"][-1]
        self.assertIn(f"€{e:,.0f}M", headline)

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
        self.assertEqual(self.s["guidance_census"]["documents"], len(self.s["documents"]))

    def test_thresholds_use_known_units_and_the_chart_agrees_with_the_table(self) -> None:
        chart = next(ex for ex in self.exhibits if ex["ref"] == "EX_HEADROOM")
        table = next(t for t in self.payload["tables"] if "本地阈值的原始单位" in t["title"])
        entries = [{**t, "current": None} for t in self.s["thresholds"]]
        self.assertEqual(len(chart["values"]), len(entries))
        for entry, value, row in zip(self.s["thresholds"], chart["values"], table["rows"]):
            self.assertIn(entry["unit"], UNIT_FORMATS)
            self.assertEqual(row[0], entry["metric"])
            self.assertEqual(f"{value:+.1f}%", row[4])
        del entries

    def test_threshold_current_values_are_read_from_the_series(self) -> None:
        cer = self.s["quarterly_cer_pct"]
        chart = next(ex for ex in self.exhibits if ex["ref"] == "EX_HEADROOM")
        current = {
            "cer_total": cer["total"][-1],
            "cer_watchmakers": cer["specialist_watchmakers"][-1],
            "cer_wholesale": cer["wholesale"][-1],
            "jewellery_two_year": round(self.qv["jewellery_two_year"], 1),
            "half_gross_margin": round(self.hv["gross"][-1], 1),
            "net_cash": self.s["net_cash_quarter_end"]["eur_bn"],
        }
        for entry, value in zip(self.s["thresholds"], chart["values"]):
            self.assertEqual(value, round(headroom(entry["direction"], entry["threshold"],
                                                   current[entry["current_key"]]), 1), entry["metric"])

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


if __name__ == "__main__":
    unittest.main()
