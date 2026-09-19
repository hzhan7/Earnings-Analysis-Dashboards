"""Ferrari page: the reconciliations that license what the page publishes.

Two of these tests exist because a specific silent failure happened while the
series was being built, and neither would have been caught by the checks the
other company pages carry:

- `test_quarters_sum_to_the_filed_full_year` is the only check that catches the
  period-column flip. Ferrari's 2016-2018 Q2/Q3 releases print the cumulative
  block where the later ones print the quarter, and reading the wrong one puts
  half-year and nine-month figures into a quarterly series. Every other
  identity here still closed while that was true -- revenue lines summed,
  shipments summed, the EBIT bridge balanced -- because all the components were
  cumulative together.
- `test_the_guidance_column_is_not_a_fixed_position` pins the outlook-table
  layouts, which moved the guidance column three times in 31 vintages.

The page is rolled by editing `series/race.json` alone (CLAUDE.md §9), so
nothing below names the quarter the series is on: counts are recomputed from
the series, the quarter's one-release blocks are synthesised where the current
quarter has none (`with_every_block`), and `RaceChecksTest` holds the page to a
separate reading of the quarter's release (`_checks`).
"""

from __future__ import annotations

import copy
import json
import math
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import race  # noqa: E402
from build.board import cn_count, headroom, round_half_up  # noqa: E402


def js_payload(path: Path, marker: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{marker} = ", 1)[1].rstrip().rstrip(";")
    return json.loads(body)


def load() -> dict:
    return json.loads(race.STAGING_PATH.read_text(encoding="utf-8"))


def text_of(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def composed(payload: dict) -> str:
    """The prose the builder composes; the audit tables are left out."""
    return text_of({key: value for key, value in payload.items() if key != "tables"})


def exhibits_of(payload: dict) -> dict:
    return {ex["ref"]: ex for section in payload["sections"] for ex in section["exhibits"] if "ref" in ex}


METRICS = ["revenue", "adj_ebitda", "adj_ebit", "adj_eps", "ifcf"]
QUARTER_END = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}


def next_label(label: str) -> str:
    year, number = race.qparts(label)
    return f"Q1 {year + 1}" if number == 4 else f"Q{number + 1} {year}"


class RaceDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = load()
        cls.payload = race.build_payload(cls.staging)
        cls.long = cls.staging["long_history"]

    # ── the windows ─────────────────────────────────────────────────────────
    def test_the_window_is_eight_contiguous_quarters(self) -> None:
        periods = self.staging["periods"]
        self.assertEqual(len(periods), 8)
        for earlier, later in zip(periods, periods[1:]):
            self.assertEqual(next_label(earlier), later)

    def test_the_long_series_runs_contiguously_from_2016q1_to_the_latest_quarter(self) -> None:
        quarters = self.long["quarters"]
        self.assertEqual(quarters[0], "Q1 2016")
        self.assertEqual(quarters[-1], self.staging["periods"][-1])
        for earlier, later in zip(quarters, quarters[1:]):
            self.assertEqual(next_label(earlier), later)
        for key, values in self.long.items():
            if isinstance(values, list):
                self.assertEqual(len(values), len(quarters), key)

    def test_the_window_is_the_tail_of_the_long_series(self) -> None:
        """The two windows must not disagree about an overlapping quarter."""
        self.assertEqual(self.long["quarters"][-8:], self.staging["periods"])
        for key, values in self.staging["financials"].items():
            self.assertEqual(values, self.long[key][-8:], key)

    # ── identities inside a quarter ─────────────────────────────────────────
    def test_regions_sum_to_total_shipments_every_quarter(self) -> None:
        long = self.long
        for index, quarter in enumerate(long["quarters"]):
            total = (long["shipments_emea"][index] + long["shipments_americas"][index]
                     + long["shipments_china_hk_taiwan"][index]
                     + long["shipments_rest_of_apac"][index])
            self.assertEqual(total, long["shipments_units"][index], quarter)

    def test_revenue_lines_sum_to_total_revenue_every_quarter(self) -> None:
        long = self.long
        for index, quarter in enumerate(long["quarters"]):
            legs = [long["cars_and_spare_parts_eur_m"][index],
                    long["sponsorship_commercial_brand_eur_m"][index],
                    long["other_revenues_eur_m"][index]]
            engines = long["engines_eur_m"][index]
            if engines is not None:
                legs.append(engines)
            self.assertAlmostEqual(sum(legs), long["net_revenues_eur_m"][index],
                                   delta=1.5, msg=quarter)

    def test_ebitda_less_depreciation_is_ebit_every_quarter(self) -> None:
        long = self.long
        for index, quarter in enumerate(long["quarters"]):
            self.assertAlmostEqual(long["ebitda_eur_m"][index] - long["da_eur_m"][index],
                                   long["ebit_eur_m"][index], delta=1.5, msg=quarter)

    def test_quarters_sum_to_the_filed_full_year(self) -> None:
        """The check that catches the period-column flip, and the only one that does.

        Ferrari prints the cumulative block LEFT of the label in the 2016-2018
        Q2 and Q3 releases and RIGHT of it from 2019, so a positional read puts
        H1 and 9M figures into three years of quarterly slots. Every other
        identity in this file still passed while that was true.

        One year may be off by exactly a reprint the series records: the Q2 2026
        release re-presented Q2 2025 industrial free cash flow without the
        withholding taxes paid in later quarters, and those later quarters have
        not been reprinted yet.
        """
        long = self.long
        reprints = self.staging["reprints"]
        checked = years = 0
        for year, filed in long["full_year_actuals"].items():
            indices = [long["quarters"].index(f"Q{q} {year}") for q in range(1, 5)
                       if f"Q{q} {year}" in long["quarters"]]
            if len(indices) != 4:
                continue
            years += 1
            for series_key, _ in race.SUM_KEYS:
                total = sum(long[series_key][i] for i in indices)
                shift = sum(r["first_print"] - r["reprint"] for r in reprints
                            if r["key"] == series_key and r.get("offset_pending")
                            and race.qparts(r["quarter"])[0] == int(year))
                self.assertAlmostEqual(total + shift, filed[series_key], delta=1.5,
                                       msg=f"{year} {series_key}")
                checked += 1
        self.assertEqual(checked, years * len(race.SUM_KEYS))
        self.assertGreaterEqual(years, 10)
        census = race.quarter_sum_census(long, reprints)
        self.assertEqual(census["checked"], checked)
        note = next(n for n in self.payload["notes"] if "四个季度相加等于公司印出的全年" in n)
        self.assertIn(f"{years} 个财年 × {len(race.SUM_KEYS)} 个指标共 {checked} 项", note)

    def test_every_recorded_reprint_is_the_value_the_series_holds(self) -> None:
        long = self.long
        for r in self.staging["reprints"]:
            with self.subTest(quarter=r["quarter"], key=r["key"]):
                index = long["quarters"].index(r["quarter"])
                self.assertEqual(long[r["key"]][index], r["reprint"])
                self.assertNotEqual(r["first_print"], r["reprint"])
                self.assertGreater(race.qparts(r["reprinted_in"]), race.qparts(r["quarter"]))

    def test_margins_are_the_ratio_they_claim_to_be(self) -> None:
        long = self.long
        for index, quarter in enumerate(long["quarters"]):
            revenue = long["net_revenues_eur_m"][index]
            self.assertAlmostEqual(long["ebit_eur_m"][index] / revenue * 100,
                                   long["ebit_margin_pct"][index], places=3, msg=quarter)
            self.assertAlmostEqual(long["ebitda_eur_m"][index] / revenue * 100,
                                   long["ebitda_margin_pct"][index], places=3, msg=quarter)

    def test_the_printed_margins_are_within_a_few_tenths_of_the_ratio(self) -> None:
        """A transcription slip in the printed margins would show as a gap far
        beyond anything rounding makes; the census names the two quarters where
        rounding does not explain the gap, and the page says which."""
        long = self.long
        for index, quarter in enumerate(long["quarters"]):
            adjusted = long["margin_printed_basis"][index] == "adjusted"
            revenue = long["net_revenues_eur_m"][index]
            for kind in ("ebit", "ebitda"):
                printed = long[f"{kind}_margin_printed_pct"][index]
                own = long[f"adj_{kind}_eur_m" if adjusted else f"{kind}_eur_m"][index] / revenue * 100
                self.assertLess(abs(printed - own), 0.25, f"{quarter} {kind}")
        printed = sum(1 for e, b in zip(long["ebit_margin_printed_pct"], long["ebitda_margin_printed_pct"])
                      if e is not None or b is not None)
        census = race.margin_census(long)
        note = next(n for n in self.payload["notes"] if "逐季比对" in n)
        self.assertIn(f"{printed} 个季度逐季比对", note)
        self.assertIn(f"最大差 {census['worst']['gap']:.2f}pp", note)
        for quarter in census["beyond"]:
            self.assertIn(race.compact(quarter), note)

    def test_revenue_per_unit_is_cars_revenue_over_shipments(self) -> None:
        long = self.long
        for index, quarter in enumerate(long["quarters"]):
            derived = (long["cars_and_spare_parts_eur_m"][index] * 1000
                       / long["shipments_units"][index])
            self.assertAlmostEqual(derived, long["cars_revenue_per_unit_eur_k"][index],
                                   places=3, msg=quarter)

    # ── series that start or stop where disclosure does ─────────────────────
    def test_engines_is_a_hole_after_the_presentation_change_not_a_zero(self) -> None:
        """Filling it with zero would draw a reporting change as a business exit."""
        long = self.long
        engines = long["engines_eur_m"]
        first_gap = engines.index(None)
        self.assertEqual(long["quarters"][first_gap], "Q1 2024")
        self.assertTrue(all(value is None for value in engines[first_gap:]))
        self.assertTrue(all(value is not None for value in engines[:first_gap]))

    def test_net_industrial_debt_is_the_level_not_the_change(self) -> None:
        """Q2 2016 was published as +19 for a while. It is -763.

        The Q2 2016 release prints `Net industrial debt (763) (782) 19` across
        three columns -- Jun 30, Mar 31, and the *change* between them. This
        page held the change as if it were the level, which turned EUR 763M of
        net debt into EUR 19M of net cash and put a spike between two quarters
        of -782 and -585.

        The assertion is deliberately built on the arithmetic that explains the
        mistake rather than on the corrected number alone: the value the old
        page carried is exactly this quarter's change, so pinning both makes a
        silent revert impossible and says what went wrong.
        """
        long = self.long
        index = long["quarters"].index("Q2 2016")
        level = long["net_industrial_debt_eur_m"]
        self.assertEqual(level[index], -763.0)
        self.assertEqual(level[index - 1], -782.0)
        self.assertAlmostEqual(level[index] - level[index - 1], 19.0, places=6,
                               msg="the number this page used to publish was the change")
        # And the series does not swing across zero between neighbours anywhere
        # else in 2016-2017, which is what made the old value look wrong.
        for i in range(1, long["quarters"].index("Q4 2017") + 1):
            self.assertFalse(
                level[i - 1] < -300 < 0 < level[i],
                f"{long['quarters'][i]}: net industrial debt jumped from deep net debt "
                "to net cash in one quarter -- check whether a change column was read "
                "as a level",
            )
        self.assertIn("Change", long["backfill_note"])

    def test_capex_now_runs_the_whole_record_and_says_how(self) -> None:
        """The quarterly Capex and R&D table only starts in 2019 -- the earlier
        quarters are reconstructed, and the reconstruction has to be checkable.

        Ferrari prints cumulative capex in each interim report and the full year
        in the 20-F, so 2016-2018 comes out by differencing: Q1 is the printed
        three-month column, Q2 and Q3 are cumulative differences, Q4 is the
        20-F year less nine months. That is a derivation, so what is pinned here
        is not the values but the two identities that make them publishable --
        each year's four quarters summing to the printed full year, and the 2018
        quarters matching the prior-year columns that the 2019 releases printed
        independently.
        """
        long = self.long
        capex = long["capex_eur_m"]
        development = long["capitalised_development_eur_m"]
        self.assertEqual(long["quarters"][0], "Q1 2016")
        self.assertTrue(all(v is not None for v in capex), "capex has a hole")
        # Q1 2025 used to be a hole here, described as a disclosure gap. The Q1
        # 2025 release prints EUR 110M in its Capex and R&D table and the Q1 2026
        # release prints it again as the prior-year column.
        self.assertTrue(all(v is not None for v in development), "capitalised development has a hole")
        # The reconstruction identity, for the three years that needed it.
        printed_full_year = {2016: (342, 141), 2017: (392, 185), 2018: (639, 318)}
        for year, (capex_year, dev_year) in printed_full_year.items():
            rows = [i for i, q in enumerate(long["quarters"]) if q.endswith(str(year))]
            self.assertEqual(len(rows), 4, year)
            self.assertAlmostEqual(sum(capex[i] for i in rows), capex_year, places=6, msg=year)
            self.assertAlmostEqual(sum(development[i] for i in rows), dev_year, places=6, msg=year)
        # FY2020 capex excluding right-of-use assets is 709 (FY2020 release); the
        # quarters add to it only with the 2021 releases' reprints of Q1-Q3.
        rows = [i for i, q in enumerate(long["quarters"]) if q.endswith("2020")]
        self.assertAlmostEqual(sum(capex[i] for i in rows), 709, places=6)
        # And the page says the early quarters are derived rather than printed.
        self.assertIn("累计相减", long["backfill_note"])
        chart = exhibits_of(self.payload)["EX_L_CAPEX"]
        # The note may quote the old sentence -- it does, in order to correct
        # it -- but it may not assert it.
        self.assertIn("那句话是错的", chart["note"])
        self.assertIn("中报 6-K 附件", chart["note"])
        self.assertIn("中报", chart["src_extra"])
        self.assertIn("重印值", chart["src_extra"])
        self.assertNotIn("没有读到明文条款", chart["src_extra"])
        self.assertEqual(len(chart["xlabels"]), len(long["quarters"]))
        note = next(n for n in self.payload["notes"] if n.startswith("资本开支与资本化研发的序列"))
        self.assertIn(f"自 {race.compact(long['quarters'][0])} 起", note)
        self.assertNotIn("不向前回补", note)

    def test_the_fourth_quarter_share_count_is_the_printed_one(self) -> None:
        """Q4 2016 was left null as "not obtainable". It is printed.

        Ferrari's own FY2016 release prints EPS without a share count, and the
        2017 interim reports carry Q1 2016 as their comparative -- which is how
        the quarter came to be treated as unavailable. The figure is in the
        FY2017 release, in the prior-year column of its three-months-ended
        table, exactly where this page already takes Q4 2017 and Q4 2018 from.
        """
        long = self.long
        shares = long["diluted_shares_k"]
        self.assertTrue(all(v is not None for v in shares))
        index = long["quarters"].index("Q4 2016")
        self.assertEqual(shares[index], 188946.0)
        self.assertEqual(shares[index - 1], 188923.0)
        self.assertIn("保留", long["diluted_shares_note"])
        self.assertEqual(shares[long["quarters"].index("Q4 2017")], 189759.0)

    # ── the annual guidance record ──────────────────────────────────────────
    def test_the_record_runs_initial_q1_q2_q3_for_every_fiscal_year(self) -> None:
        record = self.staging["annual_guidance_history"]
        n = len(record["vintages"])
        for key in ("vintage_slots", "release_dates", "fiscal_years", "source_quarters", "layout"):
            self.assertEqual(len(record[key]), n, key)
        for metric in METRICS:
            for key in ("lo", "hi", "form", "actual"):
                self.assertEqual(len(record["items"][metric][key]), n, f"{metric} {key}")
        years = sorted(set(record["fiscal_years"]))
        self.assertEqual(years, list(range(2019, years[-1] + 1)))
        for year in years:
            slots = [s for s, fy in zip(record["vintage_slots"], record["fiscal_years"]) if fy == year]
            self.assertEqual(slots, race.SLOTS[:len(slots)], year)
            if year != years[-1]:
                self.assertEqual(len(slots), 4, year)
        for label, year, slot in zip(record["vintages"], record["fiscal_years"], record["vintage_slots"]):
            self.assertEqual(label, f"FY{year} {slot}")
        self.assertEqual(record["release_dates"], sorted(record["release_dates"]))

    def test_only_the_final_vintage_of_a_finished_year_carries_an_actual(self) -> None:
        record = self.staging["annual_guidance_history"]
        finished = {int(y) for y in self.long["full_year_actuals"]}
        for metric in METRICS:
            actual = record["items"][metric]["actual"]
            for index, value in enumerate(actual):
                year = record["fiscal_years"][index]
                is_last = (index + 1 == len(actual)
                           or record["fiscal_years"][index + 1] != year)
                if year in finished and is_last:
                    self.assertIsNotNone(value, f"{metric} {year}")
                else:
                    self.assertIsNone(value, f"{metric} {year} index {index}")

    def test_a_range_has_its_endpoints_the_right_way_round(self) -> None:
        record = self.staging["annual_guidance_history"]
        for metric in METRICS:
            item = record["items"][metric]
            for low, high, form in zip(item["lo"], item["hi"], item["form"]):
                if low is None:
                    continue
                self.assertLessEqual(low, high, metric)
                if form != "range":
                    self.assertEqual(low, high, f"{metric} {form}")

    def test_the_form_tally_the_page_publishes_is_the_one_in_the_data(self) -> None:
        """The headline claim: how many ranges the settling vintage carries.

        If the data stops saying that, the page must not keep saying it.
        """
        record = self.staging["annual_guidance_history"]
        counts: dict[str, dict[str, int]] = {}
        for index, slot in enumerate(record["vintage_slots"]):
            bucket = counts.setdefault(slot, {})
            for metric in METRICS:
                form = record["items"][metric]["form"][index]
                if form:
                    bucket[form] = bucket.get(form, 0) + 1
        q3_ranges, q3_total = counts["q3"].get("range", 0), sum(counts["q3"].values())
        initial_ranges, initial_total = counts["initial"].get("range", 0), sum(counts["initial"].values())
        chart = exhibits_of(self.payload)["EX_FORM"]
        self.assertIn(f"年初那一档 {initial_total} 个读数里 {initial_ranges} 个是两端区间", chart["title"])
        self.assertIn(f"Q3 那一档 {q3_total} 个读数里只有 {q3_ranges} 个", chart["title"])
        self.assertIn(f"{len(record['vintages'])} 档 vintage 里，年初那一档有 {initial_ranges} 个读数是两端区间",
                      self.payload["brief"])
        early = [counts[s].get("range", 0) for s in ("initial", "q1", "q2")]
        shed = q3_ranges < min(early)
        self.assertEqual("卸掉了上界" in chart["note"], shed)
        self.assertEqual("指引在最确定的时候卸掉上界" in self.payload["brief"], shed)

    def test_the_guidance_column_is_not_a_fixed_position(self) -> None:
        """The outlook table has put the guidance column in three places.

        2019 and early-2025 tables carry a growth column to its right, one 2019
        vintage has no table at all, and from May 2026 the guidance comes
        FIRST -- taking the right-most column there would have published the
        prior-year actual (EUR 7.15B) as FY2026 revenue guidance. The layouts
        were read vintage by vintage; the values below are fixed history.
        """
        record = self.staging["annual_guidance_history"]
        layout = dict(zip(record["vintages"], record["layout"]))
        self.assertEqual(layout["FY2019 initial"], "before_growth")
        self.assertEqual(layout["FY2019 q3"], "text")
        self.assertEqual(layout["FY2025 initial"], "before_growth")
        self.assertEqual(layout["FY2026 initial"], "last")
        self.assertEqual(layout["FY2026 q1"], "first")
        revenue = dict(zip(record["vintages"], record["items"]["revenue"]["hi"]))
        eps = dict(zip(record["vintages"], record["items"]["adj_eps"]["hi"]))
        printed = {"FY2026 initial": (7.5, 9.45), "FY2026 q1": (7.5, 9.45), "FY2026 q2": (7.6, 9.68)}
        for vintage, (revenue_guide, eps_guide) in printed.items():
            if vintage in revenue:
                self.assertEqual((revenue[vintage], eps[vintage]), (revenue_guide, eps_guide), vintage)
        for vintage, kind in layout.items():
            if kind == "first":
                year = int(vintage[2:6])
                prior = self.long["full_year_actuals"][str(year - 1)]["net_revenues_eur_m"] / 1000
                self.assertNotEqual(revenue[vintage], round(prior, 2), vintage)
        for text in (self.payload["notes"][4], exhibits_of(self.payload)["EX_FORM"]["src_extra"]):
            self.assertIn(f"{len(record['vintages'])} 档里 {record['layout'].count('last')} 档的指引列排在最右", text)
            self.assertNotIn("2018", text)

    def test_the_open_year_is_never_drawn_as_settled(self) -> None:
        record = self.staging["annual_guidance_history"]
        finished = {int(y) for y in self.long["full_year_actuals"]}
        for index, year in enumerate(record["fiscal_years"]):
            if year not in finished:
                for metric in METRICS:
                    self.assertIsNone(record["items"][metric]["actual"][index], metric)

    def test_no_finished_year_landed_below_its_final_guidance(self) -> None:
        record = self.staging["annual_guidance_history"]
        for metric in METRICS:
            item = record["items"][metric]
            for low, high, form, actual in zip(item["lo"], item["hi"],
                                               item["form"], item["actual"]):
                if actual is None or low is None:
                    continue
                self.assertNotEqual(race.verdict(low, high, form, actual), "below",
                                    f"{metric} {actual}")

    def test_a_point_guidance_is_settled_at_its_printed_precision(self) -> None:
        """FY2019 adjusted EBITDA is 1.269 against a guided ~1.27, i.e. on it.

        Scoring that as a miss would apply a threshold finer than the
        disclosure it is measured against.
        """
        self.assertEqual(race.verdict(1.27, 1.27, "point", 1.269), "met")
        self.assertEqual(race.verdict(1.27, 1.27, "point", 1.30), "above")
        self.assertEqual(race.verdict(1.27, 1.27, "point", 1.20), "below")

    def test_the_release_months_the_page_prints_are_the_records(self) -> None:
        """The page used to say 「2 月、5 月、7–8 月与 10–11 月」; the record's first
        vintage came out on 31 January and every settling vintage in November."""
        record = self.staging["annual_guidance_history"]
        months = race.slot_months(record)
        for slot, text in zip(race.SLOTS, months.replace("与 ", "、").split("、")):
            dates = [d for d, s in zip(record["release_dates"], record["vintage_slots"]) if s == slot]
            wanted = sorted({int(d[5:7]) for d in dates})
            self.assertTrue(text.startswith(str(wanted[0])), slot)
            self.assertIn(str(wanted[-1]), text, slot)
        self.assertIn(f"四档分别发布于当年的 {months}", exhibits_of(self.payload)["EX_EBITDA"]["note"])

    # ── thresholds ──────────────────────────────────────────────────────────
    def test_every_quantified_threshold_has_a_headroom_bar(self) -> None:
        _, entries = race.kpi_entries(self.staging)
        bar = self.payload["sections"][2]["exhibits"][0]
        self.assertEqual(bar["xlabels"], [entry["metric"] for entry in entries])
        for entry, value in zip(entries, bar["values"]):
            self.assertAlmostEqual(
                headroom(entry["direction"], entry["threshold"], entry["current"]),
                value, places=1, msg=entry["metric"])

    def test_threshold_current_values_are_measured_from_the_series(self) -> None:
        """The block used to carry typed currents; 31.22 was the page's own ratio
        where the company printed 31.2, and -20.75 printed as -20.8% in the table
        beside a chart that said -20.7%."""
        _, entries = race.kpi_entries(self.staging)
        long = self.long
        current = {entry["measure"]: entry["current"] for entry in entries}
        self.assertEqual(current["ebit_margin"], long["ebit_margin_printed_pct"][-1])
        self.assertEqual(current["da"], long["da_eur_m"][-1])
        americas = long["shipments_americas"]
        self.assertAlmostEqual(current["americas_yoy"], (americas[-1] / americas[-5] - 1) * 100, places=9)
        for entry in self.staging["next_kpi"]["quantified"]:
            self.assertNotIn("current", entry, "a typed current value goes stale with the roll")

    def test_the_da_threshold_is_the_level_managements_figure_implies(self) -> None:
        guide = race.da_guidance(self.staging)
        entry = next(e for e in self.staging["next_kpi"]["quantified"] if e["measure"] == "da")
        if guide is not None:
            self.assertEqual(entry["threshold"], guide["per_quarter"])

    def test_what_the_page_refuses_to_publish_is_named(self) -> None:
        block = self.staging["next_kpi"]
        excluded = race.excluded_text(block)
        for term in ["个性化", "订单簿", "对冲", "车型级"]:
            self.assertIn(term, excluded)
        self.assertIn(excluded, self.payload["sections"][2]["exhibits"][0]["note"])
        self.assertIn(f"本页不接入的{cn_count(len(block['not_tracked']))}条",
                      self.payload["sections"][2]["description"])
        # The order book is in every release as the CEO's own sentence; it is
        # not a figure the company withholds.
        self.assertNotIn("因为公司结构性不披露", excluded)

    def test_no_market_expectation_or_rating_is_published(self) -> None:
        """No plotted or tabulated figure may be a consensus, rating or target.

        Scanning the whole payload for those words was the first version of
        this test and it failed on the note that says the page does not publish
        them -- a check that cannot distinguish a disclaimer from the thing it
        disclaims. So it looks at the places a number would actually appear.
        """
        self.assertNotIn("market_expectation", self.staging)
        forbidden = ["市场预期", "目标价", "一致预期", "评级"]
        surfaces: list[str] = []
        for section in self.payload["sections"]:
            for exhibit in section["exhibits"]:
                surfaces.append(exhibit["title"])
                surfaces.extend(s["name"] for s in exhibit.get("series", []))
                surfaces.extend(g["name"] for g in exhibit.get("groups", []))
                surfaces.extend(exhibit.get("xlabels", []))
        for table in self.payload["tables"]:
            surfaces.append(table["title"])
            surfaces.extend(table["headers"])
            surfaces.extend(str(cell) for row in table["rows"] for cell in row)
        for surface in surfaces:
            for term in forbidden:
                self.assertNotIn(term, surface, surface[:60])

    # ── currency ────────────────────────────────────────────────────────────
    def test_money_is_printed_in_euro_not_dollars(self) -> None:
        """Ferrari reports in euro; a dollar sign here is a unit error."""
        quarterly = next(table for table in self.payload["tables"]
                         if "季合并损益" in table["title"])
        for row in quarterly["rows"]:
            for cell in row:
                self.assertNotIn("$", cell, cell)
        self.assertTrue(any("€" in cell for row in quarterly["rows"] for cell in row))

    def test_the_quarter_table_prints_the_margins_the_company_printed(self) -> None:
        quarterly = next(table for table in self.payload["tables"] if "季合并损益" in table["title"])
        self.assertEqual(quarterly["title"][:1 + len(cn_count(8))], "近" + cn_count(len(self.staging["periods"])))
        column = quarterly["headers"].index("EBIT 利润率")
        printed = self.long["ebit_margin_printed_pct"][-len(self.staging["periods"]):]
        self.assertEqual([row[column] for row in quarterly["rows"]], [f"{v:.1f}%" for v in printed])

    # ── exhibits and publication ────────────────────────────────────────────
    def test_the_page_carries_the_cross_page_capex_table(self) -> None:
        """Published byte-identically on every page, including pages outside the chain."""
        titles = [table["title"] for table in self.payload["tables"]]
        self.assertTrue(any("AI capex" in title for title in titles), titles)

    def test_exhibits_are_numbered_in_render_order_and_refs_resolve(self) -> None:
        numbers = [ex["n"] for section in self.payload["sections"]
                   for ex in section["exhibits"]]
        self.assertEqual(numbers, list(range(2, 2 + len(numbers))))
        text = json.dumps(self.payload, ensure_ascii=False)
        self.assertNotRegex(text, r"\{EX_[A-Z_]+\}")

    def test_tables_are_numbered_after_the_exhibits(self) -> None:
        last = max(ex["n"] for section in self.payload["sections"]
                   for ex in section["exhibits"])
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
            for row in table["rows"]:
                for cell in row:
                    self.assertNotIn("<", str(cell), str(cell)[:40])

    def test_table_dicts_carry_only_the_keys_the_renderer_reads(self) -> None:
        """`tableHTML(title, headers, rows, cls)` is all of it; a `note` is dropped."""
        for table in self.payload["tables"]:
            self.assertEqual(set(table), {"n", "title", "headers", "rows"},
                             table["title"][:40])

    def test_every_table_row_matches_its_header_width(self) -> None:
        for table in self.payload["tables"]:
            for row in table["rows"]:
                self.assertEqual(len(row), len(table["headers"]), table["title"][:40])

    def test_the_page_declares_its_filing_and_currency_basis(self) -> None:
        subtitle = self.payload["subtitle"]
        self.assertIn("IFRS", subtitle)
        self.assertIn("欧元", subtitle)
        self.assertIn("6-K", subtitle)
        joined = " ".join(self.payload["notes"])
        self.assertIn("20-F", joined)
        self.assertIn("10-Q", joined)

    def test_the_source_link_is_this_quarters_release(self) -> None:
        name, url = race.release_source(self.staging)
        self.assertEqual(self.payload["source_url"], url)
        self.assertIn(f'href="{url}"', self.payload["source"])
        self.assertTrue(url.startswith("https://www.sec.gov/Archives/edgar/data/1648416/"))
        label = next(s["label"] for s in self.staging["sources"] if s["url"] == url)
        self.assertIn(self.staging["release_dates"][-1], label)

    def test_the_published_payload_matches_a_fresh_build(self) -> None:
        published = js_payload(ROOT / "data" / "race.js", "window.DASH")
        self.assertEqual(published, self.payload)


def with_every_block(source: dict) -> dict:
    """The series with every optional one-quarter block present and stamped for
    the quarter it ends on, synthesised (with placeholder words) where this
    quarter has none, so the tests below do not depend on the quarter."""
    st = copy.deepcopy(source)
    period = st["periods"][-1]
    story = st.setdefault("quarter_story", {"period": period})
    story.setdefault("americas", "测试用的美洲解释。")
    story.setdefault("regions", "测试用的地区口径。")
    story.setdefault("other_revenue", {"leg": "other_revenues_eur_m", "text": "测试用的 Other 解释。"})
    if race.qparts(period)[1] < 4:
        long = st["long_history"]
        done = [i for i, q in enumerate(long["quarters"]) if race.qparts(q)[0] == race.qparts(period)[0]]
        ytd = sum(long["da_eur_m"][i] for i in done)
        story.setdefault("da_guidance", {"full_year_floor_eur_m": ytd + 180.0 * (4 - len(done)),
                                         "said_on": "测试电话会", "first_time": True})
        guide = race.da_guidance(st)
        for entry in st["next_kpi"]["quantified"]:
            if entry["measure"] == "da":
                entry["threshold"] = guide["per_quarter"]
    st.setdefault("printed_yoy_pct", {"period": period})
    return st


def roll_forward(source: dict) -> dict:
    """Append the next quarter with invented figures -- a shape test, nothing here
    is published. Every results release carries a guidance vintage: a Q1-Q3
    release revises the year, a Q4 release settles it and opens the next."""
    st = copy.deepcopy(source)
    long, fin = st["long_history"], st["financials"]
    last = long["quarters"][-1]
    new = next_label(last)
    year, number = race.qparts(new)
    end = f"{year}-{QUARTER_END[number]}"
    release = f"{year + (number == 4)}-{'02' if number == 4 else {1: '05', 2: '07', 3: '11'}[number]}-05"
    for key, values in long.items():
        if not isinstance(values, list):
            continue
        if key == "quarters":
            values.append(new)
        elif key == "period_ends":
            values.append(end)
        elif key == "release_dates":
            values.append(release)
        elif key == "margin_printed_basis":
            values.append("reported")
        else:
            values.append(values[-4])
    long["ebit_margin_pct"][-1] = long["ebit_eur_m"][-1] / long["net_revenues_eur_m"][-1] * 100
    long["ebitda_margin_pct"][-1] = long["ebitda_eur_m"][-1] / long["net_revenues_eur_m"][-1] * 100
    long["ebit_margin_printed_pct"][-1] = float(round_half_up(long["ebit_margin_pct"][-1], 1))
    long["ebitda_margin_printed_pct"][-1] = float(round_half_up(long["ebitda_margin_pct"][-1], 1))
    for key in fin:
        fin[key] = long[key][-8:]
    st["periods"] = long["quarters"][-8:]
    st["period_ends"] = st["periods"] and [f"{race.qparts(q)[0]}-{QUARTER_END[race.qparts(q)[1]]}"
                                           for q in st["periods"]]
    st["release_dates"] = st["release_dates"][1:] + [release]
    record = st["annual_guidance_history"]

    def add_vintage(fy: int, slot: str) -> None:
        record["vintages"].append(f"FY{fy} {slot}")
        record["fiscal_years"].append(fy)
        record["vintage_slots"].append(slot)
        record["release_dates"].append(release)
        record["source_quarters"].append(new)
        record["layout"].append("first")
        for item in record["items"].values():
            item["lo"].append(item["lo"][-1])
            item["hi"].append(item["hi"][-1])
            item["form"].append(item["form"][-1])
            item["actual"].append(None)

    if number < 4:
        add_vintage(year, race.SLOTS[number])
    else:
        idx = [long["quarters"].index(f"Q{k} {year}") for k in range(1, 5)]
        row = {key: sum(long[key][i] for i in idx) for key, _ in race.SUM_KEYS}
        row.update(adj_ebitda_eur_m=row["ebitda_eur_m"], adj_ebit_eur_m=row["ebit_eur_m"],
                   diluted_eps_eur=9.9, adj_diluted_eps_eur=9.9)
        long["full_year_actuals"][str(year)] = row
        last_vintage = max(i for i, fy in enumerate(record["fiscal_years"]) if fy == year)
        actuals = {"revenue": row["net_revenues_eur_m"] / 1000, "adj_ebitda": row["ebitda_eur_m"] / 1000,
                   "adj_ebit": row["ebit_eur_m"] / 1000, "adj_eps": 9.9, "ifcf": row["industrial_fcf_eur_m"] / 1000}
        for metric, item in record["items"].items():
            item["actual"][last_vintage] = actuals[metric]
        add_vintage(year + 1, "initial")
    url = f"https://www.sec.gov/Archives/edgar/data/1648416/test/{new.replace(' ', '')}.htm"
    label = (f"Ferrari FY{year} 业绩新闻稿（6-K EX-99.1，{release}）" if number == 4
             else f"Ferrari Q{number} {year} 业绩新闻稿（6-K EX-99.1，{release}）")
    st["sources"].insert(0, {"label": label, "url": url})
    st["latest"].update(period=new, period_end=end, release_date=release)
    st["next_kpi"]["period"] = new
    st.pop("quarter_story", None)
    st.pop("printed_yoy_pct", None)
    return st


class RaceRollTest(unittest.TestCase):
    """What a roll has to change in `series/race.json`, and what the page does when it does not.

    Three blocks describe one release and are stamped with its quarter: the
    thresholds (`next_kpi`), the quarter's story (`quarter_story`) and the growth
    rates the release printed (`printed_yoy_pct`). A block stamped for another
    quarter stops the build; the story and the printed rates are optional, and
    their sentences go with them.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = load()
        cls.full = with_every_block(cls.source)
        cls.payload = race.build_payload(cls.full)
        cls.blob = text_of(cls.payload)

    def test_a_block_stamped_with_another_quarter_stops_the_build(self) -> None:
        for key in ("next_kpi", "quarter_story", "printed_yoy_pct"):
            stale = copy.deepcopy(self.full)
            stale[key]["period"] = "Q1 1999"
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    race.build_payload(stale)
        bare = copy.deepcopy(self.full)
        del bare["next_kpi"]
        with self.assertRaisesRegex(ValueError, "`next_kpi` is missing"):
            race.build_payload(bare)
        unknown = copy.deepcopy(self.full)
        unknown["next_kpi"]["quantified"][0]["measure"] = "not_a_measure"
        with self.assertRaisesRegex(ValueError, "does not know how to measure"):
            race.build_payload(unknown)
        drifted = copy.deepcopy(self.full)
        entry = next(e for e in drifted["next_kpi"]["quantified"] if e["measure"] == "da")
        entry["threshold"] += 5
        with self.assertRaisesRegex(ValueError, "implies"):
            race.build_payload(drifted)
        orphan = copy.deepcopy(self.full)
        _, url = race.release_source(orphan)
        orphan["sources"] = [s for s in orphan["sources"] if s["url"] != url]
        with self.assertRaisesRegex(ValueError, "sources"):
            race.build_payload(orphan)
        audited = copy.deepcopy(self.full)
        audited["latest"]["audit_status"] = "reviewed"
        with self.assertRaisesRegex(ValueError, "audit_status"):
            race.build_payload(audited)
        short = copy.deepcopy(self.full)
        short["long_history"]["quarters"][-1] = "Q4 1999"
        with self.assertRaisesRegex(ValueError, "append the quarter"):
            race.build_payload(short)

    def test_a_quarter_without_a_story_leaves_it_out(self) -> None:
        story = self.full["quarter_story"]
        cases = {
            "quarter_story": [story["americas"][:12], story["regions"][:12], story["other_revenue"]["text"][:12],
                              "季均是 €", "把全年 D&A 量化为"],
            "printed_yoy_pct": [story["other_revenue"]["text"][:12], "是三条腿里最快的一条"],
        }
        for key, texts in cases.items():
            bare = copy.deepcopy(self.full)
            del bare[key]
            if key == "quarter_story":
                for entry in bare["next_kpi"]["quantified"]:
                    if entry["measure"] == "da":
                        entry["threshold"] = 1.0
            payload = race.build_payload(bare)
            after = text_of(payload)
            for text in texts:
                with self.subTest(block=key, text=text):
                    self.assertIn(text, self.blob)
                    self.assertNotIn(text, after)
            chart = exhibits_of(payload)["EX_DA"]
            if key == "quarter_story":
                self.assertEqual(len(chart["series"]), 1)
            numbers = [ex["n"] for section in payload["sections"] for ex in section["exhibits"]]
            self.assertEqual(numbers, list(range(2, 2 + len(numbers))))

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        """Make each "record / only / every / usually" claim true in the data, then
        break it once: the sentence that made it must go."""
        def lower_latest_margin(d):
            long = d["long_history"]
            long["ebit_margin_printed_pct"][-1] = max(long["ebit_margin_printed_pct"][:-1]) - 0.5

        def raise_latest_ebitda(d):
            long = d["long_history"]
            long["ebitda_margin_printed_pct"][-1] = long["ebitda_margin_printed_pct"][-2] + 0.5

        def diverge(d):
            long = d["long_history"]
            long["ebit_margin_printed_pct"][-1] = max(long["ebit_margin_printed_pct"][:-1]) + 0.5
            long["ebitda_margin_printed_pct"][-1] = long["ebitda_margin_printed_pct"][-2] - 0.5

        def one_region_up(d):
            long = d["long_history"]
            for key, _, _ in race.REGIONS:
                long[key][-1] = long[key][-5] * (1.1 if key == "shipments_emea" else 0.9)

        def two_regions_up(d):
            one_region_up(d)
            long = d["long_history"]
            long["shipments_rest_of_apac"][-1] = long["shipments_rest_of_apac"][-5] * 1.1

        def china_smallest(d):
            long = d["long_history"]
            for i in range(len(long["quarters"])):
                others = min(long[key][i] for key, _, _ in race.REGIONS if key != "shipments_china_hk_taiwan")
                long["shipments_china_hk_taiwan"][i] = min(long["shipments_china_hk_taiwan"][i], others - 1)

        def china_not_smallest(d):
            china_smallest(d)
            long = d["long_history"]
            long["shipments_china_hk_taiwan"][0] = max(long[key][0] for key, _, _ in race.REGIONS) + 1

        def ranges_shed(d):
            pass

        def ranges_kept(d):
            record = d["annual_guidance_history"]
            for index, slot in enumerate(record["vintage_slots"]):
                if slot == "q3":
                    for item in record["items"].values():
                        if item["form"][index] and item["form"][index] != "range":
                            item["form"][index] = "range"
                            item["lo"][index] = item["hi"][index] * 0.95

        def second_cut(d):
            record = d["annual_guidance_history"]
            index = record["vintages"].index("FY2023 q1")
            record["items"]["ifcf"]["lo"][index] = record["items"]["ifcf"]["lo"][index - 1] - 0.05
            record["items"]["ifcf"]["hi"][index] = max(record["items"]["ifcf"]["hi"][index],
                                                       record["items"]["ifcf"]["lo"][index])
            record["items"]["ifcf"]["form"][index] = "range"

        def second_miss(d):
            record = d["annual_guidance_history"]
            index = record["vintages"].index("FY2021 initial")
            eps = record["items"]["adj_eps"]
            eps["lo"][index], eps["hi"][index] = 9.0, 9.2

        def a_year_ends_as_a_range(d):
            record = d["annual_guidance_history"]
            index = record["vintages"].index("FY2021 q3")
            item = record["items"]["adj_ebitda"]
            item["form"][index], item["lo"][index] = "range", item["hi"][index] - 0.05

        def move_q2(d, lowest):
            """Shift cash between Q2 and Q3 of every year, so each year still adds up."""
            long = d["long_history"]
            ifcf = long["industrial_fcf_eur_m"]
            for year in long["full_year_actuals"]:
                idx = {k: long["quarters"].index(f"Q{k} {year}") for k in range(1, 5)}
                others = [ifcf[idx[k]] for k in (1, 3, 4)]
                target = min(others) - 10 if lowest else max(others) + 10
                ifcf[idx[3]] += ifcf[idx[2]] - target
                ifcf[idx[2]] = target

        def q2_usually_lowest(d):
            move_q2(d, True)

        def no_usual_lowest(d):
            """Rotate the weakest quarter through the year numbers, so no quarter is the
            weakest in more than half of the years."""
            long = d["long_history"]
            ifcf = long["industrial_fcf_eur_m"]
            for k, year in enumerate(long["full_year_actuals"]):
                idx = [long["quarters"].index(f"Q{q} {year}") for q in range(1, 5)]
                weak, donor = idx[k % 4], idx[(k + 1) % 4]
                target = min(ifcf[i] for i in idx if i != weak) - 10
                ifcf[donor] += ifcf[weak] - target
                ifcf[weak] = target

        def another_fall(d):
            long = d["long_history"]
            fy = long["full_year_actuals"]
            delta = fy["2022"]["industrial_fcf_eur_m"] - 1 - fy["2023"]["industrial_fcf_eur_m"]
            fy["2023"]["industrial_fcf_eur_m"] += delta
            long["industrial_fcf_eur_m"][long["quarters"].index("Q4 2023")] += delta

        def sync_da_threshold(d):
            guide = race.da_guidance(d)
            for entry in d["next_kpi"]["quantified"]:
                if entry["measure"] == "da" and guide is not None:
                    entry["threshold"] = guide["per_quarter"]

        def da_low(d):
            long = d["long_history"]
            long["da_eur_m"][-1] = min(long["da_eur_m"][-6:-1]) - 1
            long["ebitda_eur_m"][-1] = long["ebit_eur_m"][-1] + long["da_eur_m"][-1]
            sync_da_threshold(d)

        def da_high(d):
            long = d["long_history"]
            long["da_eur_m"][-1] = long["da_eur_m"][-2] + 1
            long["ebitda_eur_m"][-1] = long["ebit_eur_m"][-1] + long["da_eur_m"][-1]
            sync_da_threshold(d)

        def ifcf_loosest(d):
            pass

        def eps_loosest(d):
            record = d["annual_guidance_history"]
            for index, actual in enumerate(record["items"]["adj_eps"]["actual"]):
                if actual is not None:
                    record["items"]["adj_eps"]["actual"][index] = actual * 1.5

        def eps_differs_once(d):
            pass

        def eps_differs_twice(d):
            fy = d["long_history"]["full_year_actuals"]
            for year in ("2021", "2022", "2023"):
                fy[year]["diluted_eps_eur"] = fy[year]["adj_diluted_eps_eur"] + 0.3

        def opposite_twice(d):
            long = d["long_history"]
            for i in (-1, -2):
                long["shipments_units"][i] = long["shipments_units"][i - 4] * 0.95
                long["cars_revenue_per_unit_eur_k"][i] = long["cars_revenue_per_unit_eur_k"][i - 4] * 1.1

        def same_before(d):
            opposite_twice(d)
            long = d["long_history"]
            long["cars_revenue_per_unit_eur_k"][-2] = long["cars_revenue_per_unit_eur_k"][-6] * 0.9

        noop = lambda d: None
        cases = {
            "EBIT margin record": (diverge, lower_latest_margin, ("创窗口新高", "创下这", "创新高")),
            "margins diverge": (diverge, raise_latest_ebitda, ("但同一季 EBITDA 利润率", "背离本身就是答案")),
            "only region up": (one_region_up, two_regions_up, ("是唯一同比正增长的地区",)),
            "China smallest every quarter": (china_smallest, china_not_smallest, ("<b>每一季</b>都是四个地区中",
                                                                                  "都是四个地区中最小的一个")),
            "Q3 sheds the upper bound": (ranges_shed, ranges_kept, ("卸掉了上界", "卸掉上界")),
            "the only cut": (noop, second_cut, ("是这段记录里唯一一次下修",)),
            "the only miss": (noop, second_miss, ("唯一低于年初指引的是",)),
            "no year ends as a range": (noop, a_year_ends_as_a_range, ("没有一年是以区间收尾的",)),
            "Q2 usually lowest": (q2_usually_lowest, no_usual_lowest, ("季通常最低",)),
            "cash rose but once": (noop, another_fall, ("其间只有 2020 年比上一年低",)),
            "D&A lowest since": (da_low, da_high, ("以来最低",)),
            "IFCF the loosest": (ifcf_loosest, eps_loosest, ("五条里最松的一条",)),
            "EPS differs in a minority of years": (eps_differs_once, eps_differs_twice, ("两者在多数年份相同，但",)),
            "volume and price still apart": (opposite_twice, same_before, ("仍在走反方向",)),
        }
        def resync(d):
            """Refile each complete year as the sum of its quarters, so a counterexample
            that moves a quarter does not trip the quarters-add-to-the-year check."""
            long = d["long_history"]
            for year, row in long["full_year_actuals"].items():
                idx = [long["quarters"].index(f"Q{k} {year}") for k in range(1, 5)
                       if f"Q{k} {year}" in long["quarters"]]
                if len(idx) != 4:
                    continue
                for key, _ in race.SUM_KEYS:
                    shift = sum(r["first_print"] - r["reprint"] for r in d["reprints"]
                                if r["key"] == key and r.get("offset_pending")
                                and race.qparts(r["quarter"])[0] == int(year))
                    row[key] = sum(long[key][i] for i in idx) + shift

        for name, (make_true, make_false, claims) in cases.items():
            held = copy.deepcopy(self.full)
            make_true(held)
            resync(held)
            before = composed(race.build_payload(held))
            broken = copy.deepcopy(held)
            make_false(broken)
            resync(broken)
            after = composed(race.build_payload(broken))
            for claim in claims:
                with self.subTest(case=name, claim=claim):
                    self.assertIn(claim, before)
                    self.assertNotIn(claim, after)

    def test_an_unexplained_year_that_does_not_add_up_stops_the_build(self) -> None:
        broken = copy.deepcopy(self.full)
        long = broken["long_history"]
        long["net_revenues_eur_m"][long["quarters"].index("Q3 2019")] += 50
        with self.assertRaisesRegex(ValueError, "add to"):
            race.build_payload(broken)
        # Take the reprint record away and the FY2025 cash-flow gap is unexplained.
        unrecorded = copy.deepcopy(self.full)
        unrecorded["reprints"] = [r for r in unrecorded["reprints"] if not r.get("offset_pending")]
        if race.quarter_sum_census(self.full["long_history"], self.full["reprints"])["explained"]:
            with self.assertRaisesRegex(ValueError, "add to"):
                race.build_payload(unrecorded)

    def test_the_next_quarter_rolls_without_touching_the_code(self) -> None:
        rolled = roll_forward(self.full)
        payload = race.build_payload(rolled)
        period = rolled["periods"][-1]
        self.assertEqual(payload["title"], f"Ferrari N.V. (RACE)：{period} 季报仪表盘")
        self.assertIn(f"截至 {rolled['period_ends'][-1]} · 发布 {rolled['release_dates'][-1]}", payload["subtitle"])
        self.assertEqual(payload["latest"]["disclosed_period_label"], period)
        self.assertEqual(payload["source_url"], rolled["sources"][0]["url"])
        n = len(rolled["long_history"]["quarters"])
        self.assertIn(f"{cn_count(n)}季的量与价", text_of(payload))
        self.assertIn(f"{cn_count(n)}个季度的工业自由现金流", payload["sections"][3]["description"])
        # nothing the previous quarter's story said survives it
        story = self.full["quarter_story"]
        for text in (story["americas"][:12], story["regions"][:12], "把全年 D&A 量化为"):
            self.assertNotIn(text, text_of(payload))
        self.assertEqual(len(exhibits_of(payload)["EX_DA"]["series"]), 1)

    def test_a_fourth_quarter_settles_the_year_and_opens_the_next(self) -> None:
        st = self.full
        for _ in range(4):
            st = roll_forward(st)
            if st["periods"][-1].startswith("Q4"):
                break
        payload = race.build_payload(st)
        record = st["annual_guidance_history"]
        finished = len({fy for fy, a in zip(record["fiscal_years"], record["items"]["adj_eps"]["actual"])
                        if a is not None})
        self.assertIn(f"再看{cn_count(finished)}个已完结年度", payload["sections"][0]["description"])
        self.assertTrue(payload["source"].count("第四季度及全年业绩新闻稿") == 1)
        self.assertNotIn("季均是 €", payload["headline"])


class RaceChecksTest(unittest.TestCase):
    """The page's quarter against a record keyed separately from the series.

    `_checks` is typed once per quarter from the quarter's results release -- the
    summary table, the revenue, shipments, EBITDA, capex and cash-flow tables,
    the net industrial debt table and the outlook table -- with where each
    figure was read. The builder never reads it (asserted in
    `test_data_only_roll`). Ferrari prints margins to a tenth and growth rates
    as whole percentages; the page's prose has to use those.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.s = load()
        cls.c = cls.s["_checks"]
        cls.payload = race.build_payload(cls.s)
        cls.exhibits = exhibits_of(cls.payload)
        cls.long = cls.s["long_history"]

    def test_the_page_names_the_checked_quarter(self) -> None:
        c = self.c
        self.assertEqual(self.payload["title"], f"Ferrari N.V. (RACE)：{c['period']} 季报仪表盘")
        self.assertIn(f"截至 {c['period_end']} · 发布 {c['release_date']}", self.payload["subtitle"])
        self.assertEqual(self.s["periods"][-1], c["period"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        c, long = self.c, self.long
        for key in ("net_revenues_eur_m", "ebit_eur_m", "ebitda_eur_m", "da_eur_m", "net_profit_eur_m",
                    "diluted_eps_eur", "industrial_fcf_eur_m", "cash_from_operations_eur_m", "capex_eur_m",
                    "capitalised_development_eur_m", "shipments_units", "net_industrial_debt_eur_m"):
            with self.subTest(key=key):
                self.assertEqual(long[key][-1], c[key])
        self.assertEqual(long["net_revenues_eur_m"][-5], c["prior_year_net_revenues_eur_m"])
        self.assertEqual(long["industrial_fcf_eur_m"][-5], c["prior_year_industrial_fcf_eur_m_reprinted"])
        self.assertEqual(long["cash_from_operations_eur_m"][-5], c["prior_year_cash_from_operations_eur_m_reprinted"])
        regions = {"emea": "shipments_emea", "americas": "shipments_americas",
                   "china_hk_taiwan": "shipments_china_hk_taiwan", "rest_of_apac": "shipments_rest_of_apac"}
        for name, key in regions.items():
            with self.subTest(region=name):
                self.assertEqual(long[key][-1], c["shipments_by_region"][name])
                self.assertEqual(long[key][-5], c["prior_year_shipments_by_region"][name])
        legs = {"cars_and_spare_parts": "cars_and_spare_parts_eur_m",
                "sponsorship_commercial_brand": "sponsorship_commercial_brand_eur_m", "other": "other_revenues_eur_m"}
        for name, key in legs.items():
            with self.subTest(leg=name):
                self.assertEqual(long[key][-1], c["revenue_lines_eur_m"][name])
                self.assertEqual(self.s["printed_yoy_pct"][key], c["revenue_lines_yoy_pct_printed"][name])
        self.assertEqual(self.s["printed_yoy_pct"]["net_revenues_eur_m"], c["net_revenues_yoy_pct_printed"])
        self.assertEqual(long["ebit_margin_printed_pct"][-1], c["ebit_margin_pct_printed"])
        self.assertEqual(long["ebitda_margin_printed_pct"][-1], c["ebitda_margin_pct_printed"])
        self.assertEqual(long["ebit_margin_printed_pct"][-2], c["prior_quarter_ebit_margin_pct_printed"])
        self.assertEqual(long["ebitda_margin_printed_pct"][-2], c["prior_quarter_ebitda_margin_pct_printed"])
        year = race.qparts(c["period"])[0]
        ytd = race.ytd_indices(long["quarters"])
        self.assertTrue(all(race.qparts(long["quarters"][i])[0] == year for i in ytd))
        if len(ytd) == 2:
            self.assertEqual(sum(long["da_eur_m"][i] for i in ytd), c["six_month_da_eur_m"])
            self.assertEqual(sum(long["industrial_fcf_eur_m"][i] for i in ytd), c["six_month_industrial_fcf_eur_m"])
        record = self.s["annual_guidance_history"]
        last = len(record["vintages"]) - 1
        self.assertEqual(record["source_quarters"][last], c["period"])
        self.assertEqual(record["layout"][last], c["guidance_layout"])
        for metric, (form, value) in c["guidance"].items():
            with self.subTest(guidance=metric):
                item = record["items"][metric]
                self.assertEqual(item["form"][last], form)
                self.assertEqual(item["hi"][last], value)

    def test_the_rounding_the_page_uses_is_the_companys(self) -> None:
        c, long = self.c, self.long
        self.assertEqual(round_half_up(c["ebit_eur_m"] / c["net_revenues_eur_m"] * 100, 1),
                         f"{c['ebit_margin_pct_printed']:.1f}")
        self.assertEqual(round_half_up(c["ebitda_eur_m"] / c["net_revenues_eur_m"] * 100, 1),
                         f"{c['ebitda_margin_pct_printed']:.1f}")
        self.assertEqual(sum(c["shipments_by_region"].values()), c["shipments_units"])
        self.assertEqual(sum(c["revenue_lines_eur_m"].values()), c["net_revenues_eur_m"])

    def test_the_page_prints_the_checked_figures(self) -> None:
        c = self.c
        headline = self.payload["headline"]
        self.assertIn(f"净收入 €{c['net_revenues_eur_m']:,}M", headline)
        self.assertIn(f"EBIT 利润率 {c['ebit_margin_pct_printed']:.1f}%", headline)
        mix = self.exhibits["EX_L_MIX"]["note"]
        other_rate = (c["revenue_lines_eur_m"]["other"] / (self.long["other_revenues_eur_m"][-5]) - 1) * 100
        if int(round_half_up(other_rate, 0)) != c["revenue_lines_yoy_pct_printed"]["other"]:
            self.assertIn(f"Other 同比 {c['revenue_lines_yoy_pct_printed']['other']:+d}%", mix)
        margin = self.exhibits["EX_L_MARGIN"]
        change = c["ebit_margin_pct_printed"] - c["prior_quarter_ebit_margin_pct_printed"]
        self.assertIn(f"EBIT 利润率环比 {change:+.1f}pp", margin["note"])
        quarterly = next(t for t in self.payload["tables"] if "季合并损益" in t["title"])
        self.assertEqual(quarterly["rows"][-1][quarterly["headers"].index("EBIT 利润率")],
                         f"{c['ebit_margin_pct_printed']:.1f}%")
        self.assertEqual(quarterly["rows"][-5][quarterly["headers"].index("工业自由现金流")],
                         f"€{c['prior_year_industrial_fcf_eur_m_reprinted']:,}M")
        thresholds = next(t for t in self.payload["tables"] if "下季阈值" in t["title"])
        ebit_row = next(r for r in thresholds["rows"] if r[0] == "EBIT 利润率")
        self.assertEqual(ebit_row[3], f"{c['ebit_margin_pct_printed']:.1f}%")


if __name__ == "__main__":
    unittest.main()
