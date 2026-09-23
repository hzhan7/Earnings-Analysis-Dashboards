"""NDAQ page: the reconciliations that license what the page publishes.

Two things make this page's data unusually easy to get wrong, and most of these
tests exist for one of them.

The first is that Nasdaq restates. It has run four different segment structures
since 2015 and it reclassifies businesses between them without always saying so,
so a series assembled by taking each line's earliest sighting silently splices
two bases together. Two such splices were caught while building this page -- the
segment revenues came out US$9M short of net revenue, and Capital Access ARR grew
a fictitious 2.4x in one quarter -- and both are pinned here as sum identities
that only close if every line of a quarter came from one release.

The second is that the company's gross revenue line carries a government fee. The
Section 31 pass-through is not in the earnings release at all; it is parsed out of
the 10-Q MD&A. What licenses that split is that the residual -- the real
brokerage and clearing cost -- sits in a narrow band in every quarter, so the
band is asserted rather than described.
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

from build import ndaq  # noqa: E402
from build.all import ENTRIES, build_all, roster_payload  # noqa: E402
from build.board import cn_count, cn_ordinal, headroom, stamped_block  # noqa: E402


def js_payload(path: Path, marker: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{marker} = ", 1)[1].rstrip().rstrip(";")
    return json.loads(body)


def published_text(payload: dict) -> str:
    return json.dumps({key: payload[key] for key in
                       ("title", "subtitle", "headline", "brief", "sections", "notes", "tables")},
                      ensure_ascii=False)


def contiguous(quarters: list[str]) -> bool:
    for earlier, later in zip(quarters, quarters[1:]):
        y1, q1 = int(earlier[:4]), int(earlier[5])
        y2, q2 = int(later[:4]), int(later[5])
        if (y2, q2) != ((y1 + 1, 1) if q1 == 4 else (y1, q1 + 1)):
            return False
    return True


class NdaqDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(ndaq.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = ndaq.build_payload(cls.staging)

    # ── the four sections ───────────────────────────────────────────────────
    def test_the_page_has_the_four_sections_in_order(self) -> None:
        self.assertEqual([(s["id"], s["title"]) for s in self.payload["sections"]],
                         [("settled", "一、上季跟踪指标兑现了吗"),
                          ("quarter_highlights", "二、本季重点"),
                          ("next_quarter", "三、下季要跟踪什么"),
                          ("routine", "四、长期常规跟踪")])
        for section in self.payload["sections"]:
            self.assertTrue(section["exhibits"], section["id"])
        self.assertIn("本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列",
                      " ".join(self.payload["notes"]))

    def test_section_one_settles_what_the_report_left_and_invents_nothing(self) -> None:
        """What there is to settle comes from the report, keyed in `_checks["note"]`.

        For Q2 2026 that is nothing: the site's first NDAQ analysis is this quarter's,
        and its section 0 found no earlier questions. So section one settles no
        follow-up list and no thresholds -- it says why -- and carries the company's
        own guidance record. From the next quarter the note names a prior report,
        and the same test then asks for the settlement charts instead.
        """
        note = self.staging["_checks"]["note"]
        settled = self.payload["sections"][0]
        if note["source"]["prior_quarter"] is None:
            self.assertEqual(note["report_period"], ndaq.FIRST_REPORT_PERIOD)
            self.assertIsNone(note["followup_closure"])
            self.assertEqual(note["prior_thresholds"], [])
            self.assertIn(f"本站对纳斯达克的第一份季报分析是 {note['report_period']}", settled["description"])
            self.assertIn("没有上季留下的跟踪指标可结算", settled["description"])
            for exhibit in settled["exhibits"]:
                self.assertFalse(exhibit["title"].startswith("上季"), exhibit["title"])
            self.assertEqual({ex["ref"] for ex in settled["exhibits"]},
                             {"EX_OPEX_LAST", "EX_OPEX_FIRST", "EX_OPEX_DEV", "EX_TAX"})
            # A settlement block stamped for the first-report quarter is a contradiction.
            changed = copy.deepcopy(self.staging)
            changed["prior_kpi_settlement"] = {"period": self.staging["period_labels"][-1], "quantified": []}
            with self.assertRaisesRegex(ValueError, "nothing"):
                ndaq.build_payload(changed)
            return
        prior = note["prior_thresholds"]
        titles = [ex["title"] for ex in settled["exhibits"]]
        self.assertTrue(any(t.startswith(f"上季 {len(prior)} 条量化阈值") for t in titles), titles)
        self.assertEqual({(e["metric"], e["direction"], e["threshold"])
                          for e in self.staging["prior_kpi_settlement"]["quantified"]},
                         {(t["metric"], t["direction"], t["threshold"]) for t in prior})
        if note["followup_closure"]:
            total = note["followup_closure"]["total"]
            self.assertTrue(any(t.startswith(f"上季 {total} 条待验证问题") for t in titles), titles)

    def test_the_open_year_and_the_gross_net_structure_sit_where_they_belong(self) -> None:
        """A year still running settles nothing (it is this quarter's news), and the
        gross-to-net split argues the same structural point every quarter."""
        by_section = {ex.get("ref"): section["id"] for section in self.payload["sections"]
                      for ex in section["exhibits"]}
        self.assertEqual(by_section["EX_FY26"], "quarter_highlights")
        self.assertEqual(by_section["EX_GROSSNET"], "routine")

    def test_section_two_opens_with_the_reports_core_finding(self) -> None:
        """The report's core contradiction (section 1, insight 1): the headline rate
        rose while net revenue without Index fell. The page draws it from each
        release's own two columns, and at the report's precision its numbers must be
        the report's -- which are keyed in `_checks["note"]`, not typed here."""
        findings = self.staging["_checks"]["note"]["core_findings"]
        core = self.payload["sections"][1]["exhibits"][0]
        self.assertEqual(core.get("ref"), "EX_EXINDEX")
        printed = self.staging["yoy_printed"]
        pairs = list(zip(printed["net_revenue_usd_m"], printed["index_usd_m"], printed["solutions_usd_m"]))
        total = [(n / a - 1) * 100 for (n, a), _, _ in pairs]
        without = [((n - i) / (a - j) - 1) * 100 for (n, a), (i, j), _ in pairs]
        solutions = [((s - i) / (t - j) - 1) * 100 for _, (i, j), (s, t) in pairs]
        self.assertEqual(core["xlabels"], printed["period_labels"])
        self.assertEqual(core["series"][0]["values"], [round(v, 6) for v in total])
        self.assertEqual(core["series"][1]["values"], [round(v, 6) for v in without])
        self.assertEqual(round(without[-2], 1), findings["ex_index_net_revenue_yoy_pct"]["prior"])
        self.assertEqual(round(without[-1], 1), findings["ex_index_net_revenue_yoy_pct"]["now"])
        self.assertEqual(round(solutions[-2], 1), findings["ex_index_solutions_yoy_pct"]["prior"])
        self.assertEqual(round(solutions[-1], 1), findings["ex_index_solutions_yoy_pct"]["now"])
        self.assertEqual(round(total[-2]), findings["net_revenue_yoy_pct"]["prior"])
        self.assertEqual(round(total[-1]), findings["net_revenue_yoy_pct"]["now"])
        self.assertIn(f"本季 {without[-1]:+.1f}%、上季 {without[-2]:+.1f}%", core["title"])
        self.assertIn(f"{solutions[-2]:+.1f} 到本季 {solutions[-1]:+.1f}", core["note"].replace("%", ""))
        self.assertIn(f"（剔除 Index 后 {without[-1]:+.1f}%，上季 {without[-2]:+.1f}%）", self.payload["headline"])
        self.assertIn("核心结论", self.payload["sections"][1]["description"])

    # ── the short window ────────────────────────────────────────────────────
    def test_the_short_window_starts_in_2024q3_and_is_complete(self) -> None:
        """It grows by one quarter a roll; what stays true is where it starts."""
        fin = self.staging["financials"]
        periods = self.staging["periods"]
        self.assertEqual(periods[0], "2024Q3")
        self.assertTrue(contiguous(periods))
        for name, values in fin.items():
            self.assertEqual(len(values), len(periods), name)
            self.assertTrue(all(v is not None for v in values), name)

    def test_quarters_are_contiguous_calendar_labels(self) -> None:
        for series in ("periods", ):
            periods = self.staging[series]
            for earlier, later in zip(periods, periods[1:]):
                y1, q1 = int(earlier[:4]), int(earlier[5])
                y2, q2 = int(later[:4]), int(later[5])
                self.assertEqual((y2, q2), (y1 + 1, 1) if q1 == 4 else (y1, q1 + 1))

    def test_the_window_is_the_tail_of_the_long_series(self) -> None:
        """The two windows must not disagree about an overlapping quarter."""
        long = self.staging["long"]
        self.assertEqual(long["quarters"][-len(self.staging["periods"]):], self.staging["periods"])
        for offset, quarter in enumerate(self.staging["periods"]):
            index = long["quarters"].index(quarter)
            self.assertAlmostEqual(long["net_revenue"][index],
                                   self.staging["financials"]["net_revenue"][offset],
                                   places=3, msg=quarter)

    def test_the_long_series_runs_from_2015q1_to_the_page_quarter_without_a_gap(self) -> None:
        quarters = self.staging["long"]["quarters"]
        self.assertEqual(quarters[0], "2015Q1")
        self.assertEqual(quarters[-1], self.staging["periods"][-1])
        self.assertTrue(contiguous(quarters))

    # ── identities inside a quarter ─────────────────────────────────────────
    def test_net_revenue_is_total_revenue_less_the_two_expense_lines(self) -> None:
        """The company's own headline top line, recomputed from its own inputs."""
        fin = self.staging["financials"]
        for index, period in enumerate(self.staging["periods"]):
            derived = (fin["total_revenues"][index]
                       - abs(fin["rebates"][index]) - abs(fin["bcef"][index]))
            self.assertAlmostEqual(derived, fin["net_revenue"][index],
                                   delta=0.6, msg=period)

    def test_income_statement_identity_holds_each_quarter(self) -> None:
        fin = self.staging["financials"]
        for index, period in enumerate(self.staging["periods"]):
            self.assertAlmostEqual(fin["net_revenue"][index] - fin["opex"][index],
                                   fin["op_income"][index], delta=0.6, msg=period)

    def test_operating_margins_are_the_ratios_they_claim_to_be(self) -> None:
        """Non-GAAP margin divides by NON-GAAP net revenue, the company's own definition.

        The two denominators differ in 2024Q3 only (the 34 AxiomSL ratable
        adjustment), and this test used to pin the wrong one: it divided by GAAP net
        revenue and so held the series at 55.6% for a quarter the release prints as 54%.
        """
        fin = self.staging["financials"]
        adjustments = self.staging["nongaap_revenue_adjustments_usd_m"]
        for index, period in enumerate(self.staging["periods"]):
            gaap = fin["op_income"][index] / fin["net_revenue"][index] * 100
            self.assertAlmostEqual(gaap, fin["gaap_margin_pct"][index],
                                   delta=0.12, msg=period)
            denominator = fin["net_revenue"][index] + adjustments.get(period, 0)
            non_gaap = fin["nongaap_opinc"][index] / denominator * 100
            self.assertAlmostEqual(non_gaap, fin["nongaap_margin_pct"][index],
                                   delta=0.12, msg=period)
        # the long record carries the same corrected figure, and it is the printed one
        long = dict(zip(self.staging["long"]["quarters"], self.staging["long"]["nongaap_margin_pct"]))
        short = dict(zip(self.staging["periods"], fin["nongaap_margin_pct"]))
        for quarter in (q for q in adjustments if q in short):
            self.assertEqual(long[quarter], short[quarter], quarter)
        self.assertEqual(round(long["2024Q3"]), 54)

    def test_non_gaap_margin_exceeds_gaap_margin_every_quarter(self) -> None:
        """Non-GAAP removes costs, so its margin cannot be the lower one."""
        long = self.staging["long"]
        for index, quarter in enumerate(long["quarters"]):
            self.assertGreater(long["nongaap_margin_pct"][index],
                               long["gaap_margin_pct"][index], quarter)

    # ── the restatement traps, pinned as identities ─────────────────────────
    def test_segments_sum_to_net_revenue_every_quarter(self) -> None:
        """Nine dollars short here means two reporting bases got spliced.

        Taking each segment line's earliest sighting independently pulls Capital
        Access from a January 2023 release still on the Market Platforms /
        Capital Access / Anti-Financial Crime basis, and Financial Technology
        from the 2024 release that restated the same quarter. The sum then misses
        net revenue by exactly the reclassified amount.
        """
        seg = self.staging["segments"]
        for index, quarter in enumerate(seg["quarters"]):
            total = (seg["cap"][index] + seg["fin"][index]
                     + seg["ms_net"][index] + seg["other"][index])
            self.assertAlmostEqual(total, seg["net_revenue"][index],
                                   delta=0.6, msg=quarter)

    def test_capital_access_subdivisions_sum_to_the_segment(self) -> None:
        seg = self.staging["segments"]
        for index, quarter in enumerate(seg["quarters"]):
            parts = [seg[k][index] for k in ("cap_dls", "cap_index", "cap_wi")]
            if any(p is None for p in parts):
                continue
            self.assertAlmostEqual(sum(parts), seg["cap"][index],
                                   delta=0.6, msg=quarter)

    def test_financial_technology_subdivisions_sum_to_the_segment(self) -> None:
        """The January 2024 release lists only two of the three subdivisions.

        Financial Crime Management Technology was split out of Regulatory
        Technology in the April 2024 release, which restated the earlier
        quarters; a quarter taken from the wrong release sums to 459 against a
        printed 399.
        """
        seg = self.staging["segments"]
        checked = 0
        for index, quarter in enumerate(seg["quarters"]):
            parts = [seg[k][index] for k in ("fin_fcmt", "fin_reg", "fin_cmt")]
            if any(p is None for p in parts):
                continue
            self.assertAlmostEqual(sum(parts), seg["fin"][index],
                                   delta=0.6, msg=quarter)
            checked += 1
        self.assertGreaterEqual(checked, 14)

    def test_market_services_gross_less_expenses_is_the_net_line(self) -> None:
        seg = self.staging["segments"]
        long = self.staging["long"]
        index_of = {q: i for i, q in enumerate(long["quarters"])}
        for index, quarter in enumerate(seg["quarters"]):
            i = index_of[quarter]
            derived = (seg["ms_gross"][index]
                       - abs(long["rebates"][i]) - abs(long["bcef"][i]))
            self.assertAlmostEqual(derived, seg["ms_net"][index],
                                   delta=0.6, msg=quarter)

    def test_arr_subdivisions_sum_to_the_financial_technology_total(self) -> None:
        arr = self.staging["arr"]
        for index, quarter in enumerate(arr["quarters"]):
            parts = [arr[k][index] for k in ("arr_fcmt", "arr_reg", "arr_cmt")]
            self.assertTrue(all(p is not None for p in parts), quarter)
            self.assertAlmostEqual(sum(parts), arr["arr_fin"][index],
                                   delta=0.6, msg=quarter)

    def test_the_arr_window_starts_where_one_basis_starts(self) -> None:
        """2022Q4 is excluded on purpose: it has no restated counterpart.

        Its Capital Access ARR exists only on the superseded basis, about US$510M
        against the US$1,200M the 2024 releases restate the neighbouring quarters
        to. Plotting it would draw a 2.4x jump into a segment the Adenza
        acquisition never touched.
        """
        arr = self.staging["arr"]
        self.assertEqual(arr["quarters"][0], "2023Q1")
        self.assertNotIn("2022Q4", arr["quarters"])
        self.assertGreater(arr["arr_cap"][0], 1000)

    # ── the Section 31 split ────────────────────────────────────────────────
    def test_the_section_31_residual_is_a_narrow_band(self) -> None:
        """This band is the whole evidence that the pass-through split is real.

        Subtracting the SEC fee parsed out of the 10-Q leaves a real
        brokerage-and-clearing cost that barely moves; if that residual ever
        wandered, the fee series would be measuring something else.

        The band was 3.0-9.0, fitted to the eighteen quarters this record used to
        hold. Reaching back to 2016 brings in four quarters above it -- 2020Q1
        (11), 2020Q2 and 2020Q4 (10), 2021Q1 (15) -- clustered in the retail
        trading surge, which is exactly when brokerage and clearing costs should
        move. So the band was measuring the window, not the pass-through. It is
        now sized to the record, and the count above the old ceiling is pinned
        so that "still narrow" stays a measured claim rather than a wide bound.
        """
        s31 = self.staging["section_31"]
        for index, quarter in enumerate(s31["quarters"]):
            residual = s31["residual_usd_m"][index]
            self.assertAlmostEqual(residual,
                                   s31["bcef_usd_m"][index] - s31["fees_usd_m"][index],
                                   delta=0.15, msg=quarter)
            self.assertGreaterEqual(residual, 3.0, quarter)
            self.assertLessEqual(residual, 16.0, quarter)
        # and it is still narrow: through 2026Q2 only four of forty-two quarters
        # clear the old ceiling, and all four sit in the 2020-2021 retail surge.
        # Pinned on the record up to that quarter, which a roll only appends to.
        wide = [q for q, v in zip(s31["quarters"], s31["residual_usd_m"])
                if v > 9.0 and q <= "2026Q2"]
        self.assertEqual(wide, ["2020Q1", "2020Q2", "2020Q4", "2021Q1"])

    def test_the_fee_never_exceeds_the_line_it_sits_inside(self) -> None:
        s31 = self.staging["section_31"]
        for index, quarter in enumerate(s31["quarters"]):
            self.assertLessEqual(s31["fees_usd_m"][index],
                                 s31["bcef_usd_m"][index], quarter)
            self.assertGreaterEqual(s31["fees_usd_m"][index], 0.0, quarter)

    def test_the_fee_went_to_zero_and_came_back(self) -> None:
        """The page leads on this; it must survive a data refresh."""
        s31 = self.staging["section_31"]
        by_quarter = dict(zip(s31["quarters"], s31["fees_usd_m"]))
        for quarter in ("2025Q3", "2025Q4", "2026Q1"):
            self.assertEqual(by_quarter[quarter], 0.0, quarter)
        self.assertGreater(by_quarter["2026Q2"], 300.0)

    # ── the annual guidance record ──────────────────────────────────────────
    def test_every_guided_year_carries_ordered_ranges(self) -> None:
        for key, item in self.staging["annual_guidance_history"].items():
            for year, block in item["by_year"].items():
                self.assertEqual(len(block["guided"]), len(block["releases"]),
                                 f"{key} {year}")
                for low, high, date in block["guided"]:
                    self.assertLessEqual(low, high, f"{key} {year} {date}")

    def test_finished_years_have_an_actual_and_the_open_year_does_not(self) -> None:
        for key, item in self.staging["annual_guidance_history"].items():
            open_year = max(item["years"])
            for year, block in item["by_year"].items():
                if int(year) == open_year:
                    self.assertIsNone(block["actual"], f"{key} {year}")
                elif key == "operating_expense" or int(year) >= 2019:
                    self.assertIsNotNone(block["actual"], f"{key} {year}")

    def test_the_tallies_the_page_publishes_are_the_ones_in_the_data(self) -> None:
        """The headline claim, in both directions.

        Through FY2025 expense never landed below its final range and the tax
        rate never above its final range -- pinned on those years, which a roll
        only appends to. What the page prints is recounted from the data, so if
        a later year breaks the pattern the page must stop saying it.
        """
        hist = self.staging["annual_guidance_history"]

        def through_2025(item: dict) -> dict:
            kept = [y for y in item["years"] if y <= 2025]
            return {**item, "years": kept}

        opex, tax = hist["operating_expense"], hist["tax_rate"]
        self.assertEqual(ndaq.tally(through_2025(opex), 1), {"inside": 7, "above": 4, "below": 0})
        self.assertEqual(ndaq.tally(through_2025(opex), 0), {"inside": 5, "above": 3, "below": 3})
        self.assertEqual(ndaq.tally(through_2025(tax), 1), {"inside": 5, "above": 0, "below": 2})
        self.assertEqual(ndaq.tally(through_2025(tax), 0), {"inside": 4, "above": 0, "below": 3})
        t_last, t_first = ndaq.tally(opex, 1), ndaq.tally(opex, 0)
        brief = self.payload["brief"]
        self.assertIn(f"{t_last['inside']} 次落在区间内、{t_last['above']} 次高于上限、"
                      f"{t_last['below']} 次低于下限", brief)
        self.assertIn(f"换成年初那次是 {t_first['inside']}/{t_first['above']}/{t_first['below']}", brief)

    def test_the_expense_record_runs_from_fy2015_without_a_gap(self) -> None:
        """Every year from FY2015 up to the open one is finished, and the page's
        count of releases is the count in the record (43 through July 2026)."""
        opex = self.staging["annual_guidance_history"]["operating_expense"]
        open_year = max(opex["years"])
        self.assertEqual(ndaq.finished_years(opex), list(range(2015, open_year)))
        vintages = sum(len(block["guided"])
                       for block in opex["by_year"].values())
        self.assertGreaterEqual(vintages, 43)
        self.assertIn(f"共 {vintages} 次发布", " ".join(self.payload["notes"]))

    def test_the_two_years_with_only_two_vintages_are_the_ones_named(self) -> None:
        """2015 and 2016 published no guidance in their third and fourth quarters.

        Four releases were read end to end to confirm that is a real absence and
        not a parse miss, so the page says "last guidance of the year" means
        April for those two years. A silent third vintage appearing here would
        mean the opposite was true all along.
        """
        opex = self.staging["annual_guidance_history"]["operating_expense"]
        counts = {int(year): len(block["guided"])
                  for year, block in opex["by_year"].items()}
        self.assertEqual(counts[2015], 2)
        self.assertEqual(counts[2016], 2)
        open_year = max(counts)
        for year in range(2017, open_year):
            self.assertEqual(counts[year], 4, year)
        self.assertLessEqual(counts[open_year], 4)

    def test_the_tax_record_starts_where_the_disclosure_does(self) -> None:
        """FY2018 was guided but its actual is not disclosed anywhere."""
        tax = self.staging["annual_guidance_history"]["tax_rate"]
        self.assertIn("2018", tax["by_year"])
        self.assertIsNone(tax["by_year"]["2018"]["actual"])
        self.assertEqual(ndaq.finished_years(tax), list(range(2019, max(tax["years"]))))

    def test_the_open_year_is_excluded_from_every_settled_band(self) -> None:
        """The open year is still running; a band drawn over it would settle nothing."""
        open_year = max(self.staging["annual_guidance_history"]["operating_expense"]["years"])
        for exhibit in self.payload["sections"][0]["exhibits"]:
            if exhibit["kind"] != "range_band":
                continue
            for label in exhibit.get("xlabels", []):
                self.assertNotEqual(label, f"FY{open_year}")

    # ── structural breaks are marked, not smoothed ──────────────────────────
    def test_the_charts_that_cross_a_reclassification_carry_a_break(self) -> None:
        by_ref = {ex.get("ref"): ex for section in self.payload["sections"]
                  for ex in section["exhibits"]}
        for ref, quarter in (("EX_FINSUB", "2023Q4"), ("EX_ARR", "2023Q4"),
                             ("EX_MIX", "2022Q4")):
            exhibit = by_ref[ref]
            self.assertIn("break_at", exhibit, ref)
            self.assertTrue(exhibit.get("break_label"), ref)

    def test_the_pass_through_chart_stays_on_one_definition(self) -> None:
        """Before 2022Q4 the Market Services line carried businesses with no
        transaction-based expense, so the ratio is not comparable across it."""
        by_ref = {ex.get("ref"): ex for section in self.payload["sections"]
                  for ex in section["exhibits"]}
        exhibit = by_ref["EX_GROSSNET"]
        self.assertEqual(exhibit["xlabels"], self.staging["segments"]["period_labels"])
        self.assertEqual(self.staging["segments"]["quarters"][0], "2022Q4")
        self.assertTrue(contiguous(self.staging["segments"]["quarters"]))
        stacks = {stack["name"]: stack["values"] for stack in exhibit["stacks"]}
        self.assertEqual(len(stacks), 3)
        for index, quarter in enumerate(self.staging["segments"]["quarters"]):
            total = sum(values[index] for values in stacks.values())
            self.assertAlmostEqual(total, self.staging["segments"]["ms_gross"][index],
                                   delta=0.6, msg=quarter)

    def test_series_that_start_late_are_holes_not_backfills(self) -> None:
        aum = self.staging["etp_aum"]
        self.assertEqual(aum["quarters"][0], "2015Q4")
        self.assertEqual(aum["quarters"][-1], self.staging["periods"][-1])
        self.assertTrue(contiguous(aum["quarters"]))
        self.assertTrue(all(v is not None for v in aum["period_end_usd_b"]))
        for name in ("average_usd_b", "index_revenue_usd_m", "net_inflows_usd_b"):
            values = aum[name]
            first = next(i for i, v in enumerate(values) if v is not None)
            self.assertGreater(first, 0, name)
            self.assertTrue(all(v is not None for v in values[first:]), name)

    def test_the_page_refuses_to_divide_index_revenue_by_aum(self) -> None:
        """It would print as a fee rate and it is not one.

        Asserted as "nothing plots one", not as "the words never appear": the
        notes have to be free to say which number the page is declining to
        publish and why, and a bare string ban would make that disclosure fail.
        """
        by_ref = {ex.get("ref"): ex for section in self.payload["sections"]
                  for ex in section["exhibits"]}
        note = by_ref["EX_INDEX"]["note"]
        self.assertIn("不把这两条线相除", note)
        self.assertIn("指数期权", note)
        for section in self.payload["sections"]:
            for exhibit in section["exhibits"]:
                named = [series.get("name", "") for series in exhibit.get("series", [])]
                named += [group.get("name", "") for group in exhibit.get("groups", [])]
                named += [stack.get("name", "") for stack in exhibit.get("stacks", [])]
                for key in ("bar", "line"):
                    if isinstance(exhibit.get(key), dict):
                        named.append(exhibit[key].get("name", ""))
                for name in named:
                    self.assertNotIn("基点", name, exhibit["title"])

    def test_net_income_reconciles_with_eps_and_the_share_count(self) -> None:
        """Three filed numbers per quarter, checked against each other.

        The April 2026 release prints "Net income" with no "attributable to
        Nasdaq" row, so the label had to be aliased; this is what catches an
        alias picking up the wrong row. Two consecutive quarters both come to
        US$519M, which is a coincidence, and this test is why that is known
        rather than assumed.
        """
        fin = self.staging["financials"]
        for index, period in enumerate(self.staging["periods"]):
            implied = fin["net_income"][index] / fin["diluted_shares"][index]
            self.assertAlmostEqual(implied, fin["diluted_eps"][index],
                                   delta=0.011, msg=period)

    def test_the_headline_index_growth_carries_the_adjusted_figure(self) -> None:
        """Q2 2026: reported +38% includes a one-time contract benefit; adjusted is +35%,
        and the release prints the amount (US$6M) in its organic/adjusted table."""
        context = stamped_block(self.staging, "quarter_context", self.staging["period_labels"][-1])
        by_ref = {ex.get("ref"): ex for section in self.payload["sections"]
                  for ex in section["exhibits"]}
        if context and "index_adjusted" in context:
            adjusted = context["index_adjusted"]
            self.assertIn(f"+{adjusted['adjusted_yoy_pct']:.0f}%", by_ref["EX_INDEX"]["note"])
            self.assertIn(f"US${adjusted['one_time_usd_m']:,.0f}M", by_ref["EX_INDEX"]["note"])
            self.assertNotIn("没有披露金额", by_ref["EX_INDEX"]["note"])

    # ── thresholds, exhibits, publication ───────────────────────────────────
    @staticmethod
    def reading(staging: dict, reads: str) -> float:
        """This quarter's value of a section-8 metric, resolved here and not by the builder."""
        printed, aum = staging["yoy_printed"], staging["etp_aum"]
        return {
            "arr_organic_pct": printed["arr_organic_pct"][-1],
            "fin_organic_pct": printed["fin_organic_pct"][-1],
            "cmt_organic_pct": printed["cmt_organic_pct"][-1],
            "etp_aum_period_end": aum["period_end_usd_b"][-1],
            "nongaap_opex": staging["financials"]["nongaap_opex"][-1],
            "net_inflows": aum["net_inflows_usd_b"][-1],
        }[reads]

    def test_the_thresholds_are_the_reports_section_8(self) -> None:
        """Every threshold the report's section 8 sets is on the page with the report's
        direction and number, and the page scores no threshold of its own.

        The report's thresholds are keyed by hand in `_checks["note"]` (the builder
        never reads it). The page used to score six locally set thresholds instead --
        a 55% margin floor, FinTech ARR (not revenue) at 12%, Market Services growth
        at 5%, AUM at 1,000 -- none of which section 8 asks for.
        """
        note = self.staging["_checks"]["note"]
        kpi = self.staging["next_kpi"]
        self.assertIn("第 8 节", kpi["set_in"])
        safe = {e["reads"]: e for e in kpi["quantified"]}
        upside = {u["reads"]: u for u in kpi["upside"]}
        unplotted = {n["reads"]: n for n in kpi["not_connected"]}
        zero = kpi["zero_line"]
        matched = set()
        for t in note["next_thresholds"]:
            key = (t["id"], t["role"], t["threshold"])
            with self.subTest(threshold=key):
                if t["id"] in unplotted:
                    self.assertIn(f"{t['threshold']:g}%", unplotted[t["id"]]["report"])
                elif t["role"] == "警戒" and t["id"] == zero["reads"]:
                    self.assertEqual((t["direction"], t["threshold"]), ("up", 0.0))
                elif t["role"] == "警戒" and t["id"] == "nongaap_opex":
                    # the report states the half-year total; the page draws its quarterly average
                    entry = safe[t["id"]]
                    self.assertEqual(entry["direction"], t["direction"])
                    self.assertEqual(entry["half_year"], t["threshold"])
                    self.assertEqual(entry["threshold"], t["threshold"] / 2)
                elif t["role"] == "警戒":
                    entry = safe[t["id"]]
                    self.assertEqual((entry["direction"], entry["threshold"]), (t["direction"], t["threshold"]))
                    self.assertEqual(entry.get("consecutive", 1), t.get("consecutive", 1))
                elif t["role"] == "上行":
                    self.assertEqual(safe[t["id"]]["upside"], t["threshold"])
                else:
                    self.assertEqual(t["role"], "上行撤销")
                    self.assertEqual(upside[t["id"]]["threshold"], t["threshold"])
                matched.add(key)
        # ...and nothing the page scores is missing from the report
        page = ({(e["reads"], "警戒", e.get("half_year", e["threshold"])) for e in kpi["quantified"]}
                | {(e["reads"], "上行", e["upside"]) for e in kpi["quantified"] if e.get("upside") is not None}
                | {(u["reads"], "上行撤销", u["threshold"]) for u in kpi["upside"]}
                | {(zero["reads"], "警戒", 0.0)})
        self.assertLessEqual(page, matched)
        for entry in kpi["quantified"] + kpi["upside"] + kpi["not_connected"] + [zero]:
            self.assertTrue(entry["report"], entry["metric"])
        text = published_text(self.payload)
        for gone in ("本地阈值", "本地研究设定", "Market Services 净收入同比"):
            self.assertNotIn(gone, text)

    def test_every_quantified_threshold_has_a_headroom_bar(self) -> None:
        kpi = self.staging["next_kpi"]["quantified"]
        bar = self.payload["sections"][2]["exhibits"][0]
        self.assertEqual(bar["kind"], "diverging_bars")
        self.assertTrue(bar["title"].startswith(f"下季 {len(kpi)} 条阈值："), bar["title"])
        self.assertEqual(bar["xlabels"], [entry["metric"] for entry in kpi])
        for entry, value in zip(kpi, bar["values"]):
            now = self.reading(self.staging, entry["reads"])
            self.assertAlmostEqual(headroom(entry["direction"], entry["threshold"], now),
                                   value, places=1, msg=entry["metric"])

    def test_each_threshold_has_its_own_line_against_its_own_series(self) -> None:
        """「X：下季阈值 A，当前 B」, one chart per threshold, drawn over the metric's own record."""
        charts = {ex["title"].split("：")[0]: ex for ex in self.payload["sections"][2]["exhibits"][1:]}
        kpi = self.staging["next_kpi"]
        expected = {e["metric"]: (e["threshold"], e["reads"]) for e in kpi["quantified"]}
        expected[kpi["zero_line"]["metric"]] = (0.0, kpi["zero_line"]["reads"])
        self.assertEqual(set(charts), set(expected))
        series_of = {
            "arr_organic_pct": self.staging["yoy_printed"]["arr_organic_pct"],
            "fin_organic_pct": self.staging["yoy_printed"]["fin_organic_pct"],
            "cmt_organic_pct": self.staging["yoy_printed"]["cmt_organic_pct"],
            "etp_aum_period_end": self.staging["etp_aum"]["period_end_usd_b"],
            "nongaap_opex": self.staging["long"]["nongaap_opex"],
            "net_inflows": [v for v in self.staging["etp_aum"]["net_inflows_usd_b"] if v is not None],
        }
        for metric, (threshold, reads) in expected.items():
            with self.subTest(metric=metric):
                chart = charts[metric]
                self.assertEqual(chart["kind"], "lines")
                actual, line = chart["series"][0], chart["series"][1]
                self.assertEqual(actual["values"], series_of[reads])
                self.assertEqual(line["values"], [threshold] * len(chart["xlabels"]))
                self.assertEqual(line["color"], "RED")
                self.assertIn("下季阈值", chart["title"])
                self.assertEqual(actual["values"][-1], self.reading(self.staging, reads))
        arr_entry = next(e for e in kpi["quantified"] if e["reads"] == "arr_organic_pct")
        arr = charts[arr_entry["metric"]]
        self.assertEqual(arr["series"][2]["values"], [arr_entry["upside"]] * len(arr["xlabels"]))
        organic_now = self.staging["_checks"]["growth_printed_pct"]["arr_total_organic"]
        self.assertTrue(arr["title"].endswith(f"当前 {organic_now}%"), arr["title"])

    def test_the_opex_threshold_is_the_guide_top_less_the_printed_year_to_date(self) -> None:
        """Section 8 says H2 above US$1,320M: the year's guided top (2,570) less the
        six months the release printed (1,250) -- not less the two quarters added up
        (608 + 641 = 1,249), which is what the page used to divide."""
        entry = next(e for e in self.staging["next_kpi"]["quantified"] if e["reads"] == "nongaap_opex")
        context = self.staging["quarter_context"]
        record = self.staging["annual_guidance_history"]["operating_expense"]
        top = record["by_year"][str(max(record["years"]))]["guided"][-1][1]
        ytd = context["nongaap_opex_ytd_usd_m"]
        quarters = int(self.staging["periods"][-1][5])
        self.assertEqual(top - ytd, entry["half_year"])
        self.assertEqual(entry["half_year"] / (4 - quarters), entry["threshold"])
        added = sum(self.staging["financials"]["nongaap_opex"][-quarters:])
        self.assertLessEqual(abs(added - ytd), quarters)
        chart = next(ex for ex in self.payload["sections"][2]["exhibits"]
                     if ex["title"].startswith(entry["metric"]))
        self.assertIn(f"公司印的上半年 US${ytd:,.0f}M", chart["note"])
        # and the in-flight guidance chart states the same figure
        fy26 = next(ex for s in self.payload["sections"] for ex in s["exhibits"] if ex.get("ref") == "EX_FY26")
        self.assertIn(f"已发生的非 GAAP 营业费用是 US${ytd:,.0f}M（公司印的年初至今数）", fy26["note"])
        self.assertIn(f"还剩 US${top - ytd:,.0f}M 的额度，折合每季 US${entry['threshold']:,.0f}M", fy26["note"])

    def test_the_long_opex_record_is_the_first_prints(self) -> None:
        """Four quarters add up to the filed year within rounding (2022 is the widest,
        3), and the tail is the page's short window to the dollar. 2024Q3 is the one
        quarter where net revenue less non-GAAP operating income is not the expense:
        that quarter's non-GAAP income sits on non-GAAP revenue (1,146 + 34)."""
        long = self.staging["long"]
        opex = dict(zip(long["quarters"], long["nongaap_opex"]))
        record = self.staging["annual_guidance_history"]["operating_expense"]["by_year"]
        for year in ndaq.finished_years(self.staging["annual_guidance_history"]["operating_expense"]):
            total = sum(opex[f"{year}Q{q}"] for q in range(1, 5))
            self.assertLessEqual(abs(total - record[str(year)]["actual"]), 3, year)
        for quarter, value in zip(self.staging["periods"], self.staging["financials"]["nongaap_opex"]):
            self.assertEqual(opex[quarter], value, quarter)
        self.assertEqual(opex["2024Q3"], 543)

    def test_quarterly_net_inflows_add_up_to_the_printed_trailing_twelve_months(self) -> None:
        """A second reading of the same flows: every release also prints the
        trailing-twelve-month figure, and four quarters must sum to it within each
        quarter's rounding. The history is pinned as read from the 2025-01-29 to
        2026-07-23 releases' text; the latest quarter is read from its own context."""
        printed_ttm = {"2024Q4": 80, "2025Q1": 86, "2025Q2": 88, "2025Q3": 91,
                       "2025Q4": 99, "2026Q1": 79, "2026Q2": 109}
        aum = self.staging["etp_aum"]
        flows = dict(zip(aum["quarters"], aum["net_inflows_usd_b"]))
        order = aum["quarters"]
        printed_ttm[order[-1]] = self.staging["quarter_context"]["aum_ttm_usd_b"]["net_inflows"]
        for quarter, ttm in printed_ttm.items():
            i = order.index(quarter)
            four = [flows[q] for q in order[i - 3:i + 1]]
            self.assertLessEqual(abs(sum(four) - ttm), 2, quarter)

    def test_the_organic_block_agrees_with_the_segment_series(self) -> None:
        """Each row of `yoy_printed` is one release's two columns. The current column
        must be the page's own segment figure; the year-ago column the first print,
        except 2025Q3, where the release's table sits on non-GAAP revenue (2024Q3
        net revenue 1,146 + the 34 AxiomSL ratable adjustment = 1,180)."""
        printed = self.staging["yoy_printed"]
        seg = self.staging["segments"]
        self.assertEqual(printed["quarters"][-1], self.staging["periods"][-1])
        self.assertTrue(contiguous(printed["quarters"]))
        for i, quarter in enumerate(printed["quarters"]):
            k = seg["quarters"].index(quarter)
            now, ago = printed["net_revenue_usd_m"][i]
            self.assertEqual(now, seg["net_revenue"][k], quarter)
            self.assertEqual(ago - seg["net_revenue"][k - 4], 34 if quarter == "2025Q3" else 0, quarter)
            self.assertEqual(printed["index_usd_m"][i], [seg["cap_index"][k], seg["cap_index"][k - 4]], quarter)
            for key in ("fin_organic_pct", "cmt_organic_pct", "arr_organic_pct"):
                self.assertEqual(len(printed[key]), len(printed["quarters"]), key)

    def test_a_block_that_stops_short_of_the_page_stops_the_build(self) -> None:
        """A roll that appends a quarter everywhere but here would score next
        quarter's thresholds against this quarter's printed rates."""
        changed = copy.deepcopy(self.staging)
        for key in ("quarters", "period_labels", "release_dates", "net_revenue_usd_m", "index_usd_m",
                    "solutions_usd_m", "fin_organic_pct", "cmt_organic_pct", "arr_organic_pct"):
            changed["yoy_printed"][key] = changed["yoy_printed"][key][:-1]
        with self.assertRaisesRegex(ValueError, "yoy_printed"):
            ndaq.build_payload(changed)

    def test_what_the_page_refuses_to_plot_is_named(self) -> None:
        excluded = self.staging["next_kpi"]["excluded"]
        for term in ["市场一致预期", "只指引费用与税率", "Section 31 规费"]:
            self.assertIn(term, excluded)

    def test_no_market_expectation_is_published(self) -> None:
        self.assertNotIn("market_expectation", self.staging)
        text = json.dumps(self.payload, ensure_ascii=False)
        self.assertNotIn("市场预期高", text)

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

    def test_table_dicts_carry_only_the_keys_the_renderer_reads(self) -> None:
        """`tableHTML(title, headers, rows, cls)` is all of it; a `note` is dropped."""
        for table in self.payload["tables"]:
            self.assertEqual(set(table), {"n", "title", "headers", "rows"},
                             table["title"][:40])

    def test_the_published_payload_matches_a_fresh_build(self) -> None:
        published = js_payload(ROOT / "data" / "ndaq.js", "window.DASH")
        self.assertEqual(published, self.payload)

    def test_the_page_declares_the_calendar_convention_in_its_subtitle(self) -> None:
        self.assertIn("自然年财年", self.payload["subtitle"])

    def test_the_notes_say_the_guidance_is_annual_and_cost_side(self) -> None:
        notes = " ".join(self.payload["notes"])
        self.assertIn("从不指引收入、每股收益或利润率", notes)
        self.assertIn("不提供 GAAP 口径", notes)

    def test_the_notes_name_the_restated_year(self) -> None:
        """FY2017 is the one year whose actual moved; both readings are stated."""
        notes = " ".join(self.payload["notes"])
        self.assertIn("ASC 606", notes)
        self.assertIn("1,271", notes)
        self.assertIn("1,280", notes)

    def test_the_roster_carries_ndaq_with_the_payload_s_own_labels(self) -> None:
        payloads = build_all()
        roster = roster_payload(payloads)
        entry = next(item for item in roster["items"] if item["slug"] == "ndaq")
        self.assertEqual(entry["latest_label"],
                         self.payload["latest"]["disclosed_period_label"])
        self.assertEqual(entry["release_date"], self.payload["latest"]["release_date"])
        self.assertEqual(entry["group"], "financial_data_indices")
        self.assertIn(entry["group"], {group["key"] for group in roster["groups"]})

    def test_the_entry_group_exists_and_sits_where_its_order_says(self) -> None:
        from build.all import GROUPS

        keys = [group["key"] for group in GROUPS]
        self.assertIn("financial_data_indices", keys)
        orders = [group["order"] for group in GROUPS]
        self.assertEqual(orders, sorted(orders))
        entry = next(e for e in ENTRIES if e["slug"] == "ndaq")
        self.assertEqual(entry["group"], "financial_data_indices")

    def test_the_shell_links_the_payload_by_content_hash(self) -> None:
        import hashlib

        shell = (ROOT / "ndaq" / "index.html").read_text(encoding="utf-8")
        sources = re.findall(r'<script src="\.\./([^"?]+)(\?v=([0-9a-f]+))?"', shell)
        self.assertEqual([name for name, _, _ in sources],
                         ["data/roster.js", "data/ndaq.js",
                          "assets/charts.js", "assets/page.js"])
        for name, _, digest in sources:
            expected = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()[:8]
            self.assertEqual(digest, expected, name)



class NdaqChecksTest(unittest.TestCase):
    """The page's quarter against a record keyed separately from the filing.

    `_checks` is typed once per quarter from the release (and the 10-Q for the
    Section 31 fee), with the place in the document each figure was read from;
    the builder never reads it (asserted in `test_data_only_roll`). Every pair
    in it is [this quarter, the year-ago quarter as reprinted in this release].
    Rolling a quarter re-keys `_checks`; this class does not change.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(ndaq.STAGING_PATH.read_text(encoding="utf-8"))
        cls.checks = cls.staging["_checks"]
        cls.payload = ndaq.build_payload(cls.staging)
        cls.by_ref = {ex.get("ref"): ex for section in cls.payload["sections"]
                      for ex in section["exhibits"]}
        period = cls.staging["period_labels"][-1]
        cls.year_ago = ndaq.YearAgo(stamped_block(cls.staging, "year_ago_reprinted", period))

    def test_the_page_names_the_checked_quarter(self) -> None:
        checks = self.checks
        self.assertIn(checks["period"], self.payload["title"])
        self.assertIn(f"截至 {checks['period_end']}", self.payload["subtitle"])
        self.assertIn(f"发布 {checks['release_date']}", self.payload["subtitle"])
        quarter, year = checks["period"].split()
        self.assertIn(f"Nasdaq {year} 年第{cn_ordinal(int(quarter[1]))}季度业绩新闻稿",
                      self.payload["source"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        fin, seg, arr = self.staging["financials"], self.staging["segments"], self.staging["arr"]
        checks = self.checks
        for line, (now, _ago) in checks["income_statement_usd_m"].items():
            with self.subTest(line=line):
                self.assertEqual(abs(fin[line][-1]), now)
        for line, (now, _ago) in checks["non_gaap_usd_m"].items():
            with self.subTest(line=line):
                self.assertEqual(fin[line][-1], now)
        self.assertEqual(fin["diluted_eps"][-1], checks["per_share"]["diluted_eps"][0])
        self.assertEqual(fin["nongaap_eps"][-1], checks["per_share"]["nongaap_eps"][0])
        self.assertEqual(fin["diluted_shares"][-1], checks["per_share"]["diluted_shares_m"][0])
        for line, (now, _ago) in checks["revenue_detail_usd_m"].items():
            with self.subTest(line=line):
                self.assertEqual(seg[line][-1], now)
        for line, pair in checks["arr_usd_m"].items():
            if line == "total":
                continue
            with self.subTest(arr=line):
                self.assertEqual(arr[line][-1], pair[0])
        self.assertEqual(arr["arr_cap"][-1] + arr["arr_fin"][-1], checks["arr_usd_m"]["total"])
        self.assertEqual(arr["cap_prior_year_same_release"][-1], checks["arr_usd_m"]["arr_cap"][1])
        self.assertAlmostEqual(arr["fin_yoy_pct"][-1],
                               (checks["arr_usd_m"]["arr_fin"][0] / checks["arr_usd_m"]["arr_fin"][1] - 1) * 100,
                               places=1)
        aum = self.staging["etp_aum"]
        self.assertEqual(aum["period_end_usd_b"][-1], checks["etp_aum_usd_b"]["period_end"][0])
        self.assertEqual(aum["average_usd_b"][-1], checks["etp_aum_usd_b"]["average"][0])
        opex = self.staging["annual_guidance_history"]["operating_expense"]
        latest_guide = opex["by_year"][str(max(opex["years"]))]["guided"][-1]
        self.assertEqual(latest_guide, [*checks["guidance"]["opex_usd_m"], checks["release_date"]])
        tax = self.staging["annual_guidance_history"]["tax_rate"]
        self.assertEqual(tax["by_year"][str(max(tax["years"]))]["guided"][-1],
                         [*checks["guidance"]["tax_rate_pct"], checks["release_date"]])
        s31 = dict(zip(self.staging["section_31"]["quarters"], self.staging["section_31"]["fees_usd_m"]))
        parts = checks["section_31_usd_m"].values()
        self.assertEqual(s31[self.staging["periods"][-1]], sum(now for now, _ in parts))
        self.assertEqual(s31[self.staging["periods"][-5]], sum(ago for _, ago in parts))

    def test_the_section_31_payable_sentence_is_the_filed_balance(self) -> None:
        """The cash-flow leg of the fee: `quarter_context` took the year-to-date change
        from the 10-Q cash-flow statement; `_checks` took the two balances from the
        release's balance sheet. The page's sentence must be both at once."""
        payable = self.checks["section_31_payable_usd_m"]
        cash = self.staging["quarter_context"]["cash_flow"]
        self.assertEqual(cash["s31_payable_ytd_change_usd_m"], payable["end"] - payable["start"])
        note = self.by_ref["EX_S31"]["note"]
        self.assertIn(f"增加 US${payable['end'] - payable['start']:,.0f}M，{self.checks['period_end']} 的余额是 "
                      f"US${payable['end']:,.0f}M（上年末 US${payable['start']:,.0f}M）", note)

    def test_the_fintech_sub_lines_carry_the_printed_organic_rates(self) -> None:
        printed = self.staging["yoy_printed"]
        cmt = printed["cmt_organic_pct"]
        self.assertEqual(cmt[-1], self.checks["organic_printed_pct"]["cmt_revenue"])
        verb = "降到" if cmt[-1] < cmt[-2] else ("升到" if cmt[-1] > cmt[-2] else "持平于")
        self.assertIn(f"Capital Markets Technology 从上季 {cmt[-2]:g}% {verb}本季 {cmt[-1]:g}%",
                      self.by_ref["EX_FINSUB"]["note"])

    def test_the_section_8_readings_are_the_checked_figures(self) -> None:
        """Every reading section three scores is the figure keyed separately into
        `_checks` -- the organic rates from the release's text, where `yoy_printed`
        took them from its table -- and a typed 「当前值」 no longer exists to drift."""
        checks = self.checks
        printed = self.staging["yoy_printed"]
        for entry in self.staging["next_kpi"]["quantified"]:
            self.assertNotIn("current", entry, entry["metric"])
        self.assertEqual(printed["fin_organic_pct"][-1], checks["organic_printed_pct"]["fin_revenue"])
        self.assertEqual(printed["cmt_organic_pct"][-1], checks["organic_printed_pct"]["cmt_revenue"])
        self.assertEqual(printed["arr_organic_pct"][-1], checks["growth_printed_pct"]["arr_total_organic"])
        self.assertEqual(self.staging["quarter_context"]["arr_printed"]["fin_organic_pct"],
                         checks["growth_printed_pct"]["arr_fin"])
        aum = self.staging["etp_aum"]
        self.assertEqual(aum["net_inflows_usd_b"][-1], checks["etp_aum_usd_b"]["quarter_net_inflows"])
        self.assertEqual(aum["period_end_usd_b"][-1], checks["etp_aum_usd_b"]["period_end"][0])
        self.assertEqual(self.staging["quarter_context"]["nongaap_opex_ytd_usd_m"],
                         checks["nongaap_opex_six_months_usd_m"][0])
        last = self.staging["periods"][-1]
        spent, quarters, printed_ytd = ndaq.spent_in_year(self.staging, int(last[:4]),
                                                          self.staging["quarter_context"])
        self.assertEqual((spent, quarters, printed_ytd),
                         (checks["nongaap_opex_six_months_usd_m"][0], int(last[5]), True))
        high = checks["guidance"]["opex_usd_m"][1]
        entry = next(e for e in self.staging["next_kpi"]["quantified"] if e["reads"] == "nongaap_opex")
        self.assertEqual(entry["half_year"], high - spent)
        # the same two rows of the release, read as dollars, give the ex-Index Solutions reading
        sol_now, sol_ago = printed["solutions_usd_m"][-1]
        idx_now, idx_ago = printed["index_usd_m"][-1]
        self.assertEqual((idx_now, idx_ago), tuple(checks["revenue_detail_usd_m"]["cap_index"]))
        self.assertEqual(sol_now, checks["revenue_detail_usd_m"]["cap"][0] + checks["revenue_detail_usd_m"]["fin"][0])
        table = next(t for t in self.payload["tables"] if t["title"].startswith("第 8 节"))
        row = next(r for r in table["rows"] if r[0].startswith("剔除 Index 的 Solutions"))
        self.assertEqual(row[3], f"{((sol_now - idx_now) / (sol_ago - idx_ago) - 1) * 100:.1f}%")

    def test_every_year_on_year_rate_divides_by_the_reprinted_year_ago(self) -> None:
        """Solovis left Capital Access and Market Services was regrossed: the
        release's year-ago column is not the first print, and the page's
        rates must divide by the column the release printed beside them."""
        for block in ("income_statement_usd_m", "revenue_detail_usd_m"):
            for line, (_now, ago) in self.checks[block].items():
                series = (self.staging["financials"] if block == "income_statement_usd_m"
                          else self.staging["segments"])[line]
                with self.subTest(line=line):
                    self.assertEqual(abs(self.year_ago.of(line, series)), ago)
        cap_now, cap_ago = self.checks["revenue_detail_usd_m"]["cap"]
        self.assertIn(f"本季三条腿同比分别为 {(cap_now / cap_ago - 1) * 100:+.1f}%",
                      self.by_ref["EX_SEG"]["note"])
        gross_now, gross_ago = self.checks["revenue_detail_usd_m"]["ms_gross"]
        self.assertIn(f"毛收入同比 {(gross_now / gross_ago - 1) * 100:+.1f}%", self.payload["brief"])

    def test_the_printed_rates_agree_with_the_page_at_printed_precision(self) -> None:
        fin, seg, arr = self.staging["financials"], self.staging["segments"], self.staging["arr"]
        printed = self.checks["growth_printed_pct"]
        for key, series in (("net_revenue", fin["net_revenue"]), ("cap", seg["cap"]),
                            ("fin", seg["fin"]), ("ms_net", seg["ms_net"]),
                            ("cap_index", seg["cap_index"])):
            with self.subTest(growth=key):
                self.assertEqual(round(self.year_ago.growth(key, series)), printed[key])
        self.assertEqual(round(arr["fin_yoy_pct"][-1]), printed["arr_fin"])
        self.assertEqual(round(arr["cap_yoy_pct"][-1]), printed["arr_cap"])
        self.assertEqual(round(arr["total_yoy_pct"][-1]), printed["arr_total_organic"])
        margins = self.checks["margins_printed_pct"]
        self.assertEqual(round(fin["gaap_margin_pct"][-1]), margins["gaap_margin_pct"][0])
        self.assertEqual(round(fin["nongaap_margin_pct"][-1]), margins["nongaap_margin_pct"][0])

    def test_the_quarter_context_is_what_the_release_printed(self) -> None:
        context = stamped_block(self.staging, "quarter_context", self.staging["period_labels"][-1])
        if not context:
            return
        adjusted = context["index_adjusted"]
        printed = self.checks["growth_printed_pct"]
        self.assertEqual(adjusted["adjusted_yoy_pct"], printed["cap_index_adjusted"])
        self.assertEqual(adjusted["one_time_usd_m"], self.checks["index_one_time_usd_m"])
        now, ago = self.checks["revenue_detail_usd_m"]["cap_index"]
        self.assertEqual(round(((now - adjusted["one_time_usd_m"]) / ago - 1) * 100),
                         adjusted["adjusted_yoy_pct"])
        self.assertEqual(context["arr_printed"]["total_reported_pct"], printed["arr_total_reported"])
        self.assertEqual(context["arr_printed"]["total_organic_pct"], printed["arr_total_organic"])
        self.assertEqual(context["arr_printed"]["cap_pct"], printed["arr_cap"])
        aum = self.checks["etp_aum_usd_b"]
        self.assertEqual(context["aum_ttm_usd_b"]["net_inflows"], aum["ttm_net_inflows"])
        self.assertEqual(context["aum_ttm_usd_b"]["net_appreciation"], aum["ttm_net_appreciation"])

    def test_the_headline_prints_the_checked_figures(self) -> None:
        now, ago = self.checks["income_statement_usd_m"]["net_revenue"]
        self.assertIn(f"净收入 US${now:,.0f}M、同比 {(now / ago - 1) * 100:+.1f}%", self.payload["headline"])
        now, ago = self.checks["revenue_detail_usd_m"]["cap_index"]
        self.assertIn(f"Index 收入同比 {(now / ago - 1) * 100:+.1f}%", self.payload["headline"])


class NdaqRollTest(unittest.TestCase):
    """A roll edits the series and nothing else: the one-quarter blocks and the
    sentences about the record are held to what the series says."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(ndaq.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = ndaq.build_payload(cls.staging)
        cls.text = published_text(cls.payload)

    def rebuilt(self, edit) -> dict:
        changed = copy.deepcopy(self.staging)
        edit(changed)
        return ndaq.build_payload(changed)

    def moves(self, claims, edit, present_before=True) -> None:
        after = published_text(self.rebuilt(edit))
        for claim in claims:
            with self.subTest(claim=claim):
                self.assertEqual(claim in self.text, present_before)
                self.assertEqual(claim in after, not present_before)

    def test_quarter_blocks_refuse_to_publish_under_another_quarter(self) -> None:
        for key in ("next_kpi", "quarter_context", "year_ago_reprinted"):
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    self.rebuilt(lambda s, key=key: s[key].__setitem__("period", "Q1 1999"))
        quarter, year = self.staging["period_labels"][-1].split()
        label = f"Nasdaq {year} 年第{cn_ordinal(int(quarter[1]))}季度业绩新闻稿"
        with self.assertRaisesRegex(ValueError, "sources"):
            self.rebuilt(lambda s: s.__setitem__(
                "sources", [x for x in s["sources"] if not x["label"].startswith(label)]))

    def test_a_quarter_without_its_blocks_leaves_them_out(self) -> None:
        def strip(s):
            for key in ("next_kpi", "quarter_context", "year_ago_reprinted"):
                del s[key]
        payload = self.rebuilt(strip)
        sections = {sec["id"]: sec for sec in payload["sections"]}
        self.assertEqual(sections["next_quarter"]["exhibits"], [])
        self.assertEqual(len(payload["tables"]), len(self.payload["tables"]) - 1)
        text = published_text(payload)
        for gone in ("调整后口径", "Reconciliation of Organic and Adjusted Impacts",
                     "由公司自行报送", "交叉销售运行率", "滚动十二个月数据里", "报告口径 11%"):
            with self.subTest(gone=gone):
                self.assertIn(gone, self.text)
                self.assertNotIn(gone, text)

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        # One finished year below its final expense range: the one-sided claims go.
        def under(s):
            block = s["annual_guidance_history"]["operating_expense"]["by_year"]["2021"]
            block["actual"] = block["guided"][-1][0] - 10
        self.moves(("没有一年低于指引下限", "费用指引的下限从来没有约束过这家公司",
                    "只指引成本，而且是单边的", "这是另一条单边记录，而且方向相反"), under)

        # The October range lands farther than January's in FY2022 and FY2023;
        # put both actuals on their October midpoints and "always" comes back.
        def october_closer(s):
            by_year = s["annual_guidance_history"]["operating_expense"]["by_year"]
            for year in ("2022", "2023"):
                low, high, _ = by_year[year]["guided"][-1]
                by_year[year]["actual"] = (low + high) / 2
        self.moves(("FY2022、FY2023 相反",), october_closer)
        self.moves(("年末那次总是更贴近实际",), october_closer, present_before=False)

        # Another quarter already over US$1,000B: nothing is "the first" any more.
        def not_first(s):
            s["etp_aum"]["period_end_usd_b"][-3] = 1001.0
        self.moves(("首次突破一万亿美元", "首次站上一万亿", "本季是这条序列首次站上一万亿美元"), not_first)

        # FinTech's ARR and revenue growth slowed in Q2 2026; make them speed up.
        def fintech_faster(s):
            s["arr"]["fin_yoy_pct"][-2] = s["arr"]["fin_yoy_pct"][-1] - 1
            s["segments"]["fin"][-2] = s["segments"]["fin"][-6] * 1.01
        self.moves(("Index 在加速，FinTech 放缓", "放缓的是 Financial Technology"), fintech_faster)
        self.moves(("Index 与 FinTech 是加速的两条腿", "Index 与 Financial Technology 是本季加速的来源"),
                   fintech_faster, present_before=False)

        # 17 of 45 quarter-on-quarter changes are falls; make the line monotone.
        def monotone(s):
            values = s["long"]["nongaap_margin_pct"]
            s["long"]["nongaap_margin_pct"] = [values[0] + 0.25 * i for i in range(len(values))]
        self.moves(("次回落",), monotone)
        self.moves(("几乎单调向上",), monotone, present_before=False)

        # Index carried the whole acceleration in Q2 2026; lift the rest of the company
        # past its prior-quarter rate and the core-finding sentences must go.
        def index_not_the_story(s):
            now, ago = s["yoy_printed"]["net_revenue_usd_m"][-1]
            s["yoy_printed"]["net_revenue_usd_m"][-1] = [now + 60, ago]
        self.moves(("合并净收入的加速全部来自 Index", "剔除 Index 之后却在放缓", "合并口径却从"),
                   index_not_the_story)

        # The fee was zero for the three quarters before this one.
        def fee_never_stopped(s):
            s31 = s["section_31"]
            for i in (-4, -3, -2):
                s31["fees_usd_m"][i] = 100.0
                s31["residual_usd_m"][i] = s31["bcef_usd_m"][i] - 100.0
        self.moves(("连续三个季度为零", "前三个季度是 US$0M", "上一季是 US$0M"), fee_never_stopped)

        # Past years rarely both raised the midpoint and narrowed the range.
        def every_year_same_shape(s):
            by_year = s["annual_guidance_history"]["operating_expense"]["by_year"]
            for year, block in by_year.items():
                guided = [g for g in block["guided"] if g]
                if block["actual"] is None or len(guided) < 2:
                    continue
                low, high, date = guided[0]
                guided[-1][:2] = [low + 20, high + 10]
        self.moves(("和前十一年每一年的形状一样",), every_year_same_shape, present_before=False)
        self.moves(("同样既抬中值又收区间的只有",), every_year_same_shape)

    def test_the_counts_on_the_page_are_recounted_here(self) -> None:
        s31 = self.staging["section_31"]
        self.assertIn(f"{len(s31['quarters'])} 个季度全部落在 US${min(s31['residual_usd_m']):.0f}M 至 "
                      f"US${max(s31['residual_usd_m']):.0f}M 之间", self.text)
        self.assertNotIn("18 个季度", self.text)
        values = self.staging["long"]["nongaap_margin_pct"]
        falls = sum(1 for a, b in zip(values, values[1:]) if b < a)
        self.assertIn(f"{len(values) - 1} 次环比里 {falls} 次回落", self.text)
        open_year = max(self.staging["annual_guidance_history"]["operating_expense"]["years"])
        guided = self.staging["annual_guidance_history"]["operating_expense"]["by_year"][str(open_year)]["guided"]
        self.assertIn(f"FY{open_year} 费用指引的{cn_count(len(guided))}次发布", self.text)
        basis = self.staging["ms_reclassification"]
        self.assertIn(f"新口径 US${basis['new_usd_m']:,.0f}M", self.text)
        self.assertNotIn("US$245M", self.text)
        self.assertNotIn("几乎原地踏步", self.text)
        self.assertNotIn("没有披露金额", self.text)

    def test_the_open_year_arithmetic_follows_the_quarter(self) -> None:
        """Q3 leaves one quarter of budget; after Q4 the open year is the next one."""
        def third_quarter(s):
            s["periods"].append("2026Q3")
            s["period_labels"].append("Q3 2026")
            s["period_ends"].append("2026-09-30")
            for values in s["financials"].values():
                values.append(values[-1])
            s["latest"]["period"] = "Q3 2026"
            for key in ("next_kpi", "quarter_context", "year_ago_reprinted"):
                del s[key]
            s["sources"].append({"label": "Nasdaq 2026 年第三季度业绩新闻稿（8-K EX-99.1）", "url": "https://x/"})
            s["long"]["quarters"].append("2026Q3")
            s["long"]["period_labels"].append("Q3 2026")
            for key, values in s["long"].items():
                if key not in ("quarters", "period_labels"):
                    values.append(values[-1])
            for block in ("segments", "section_31", "etp_aum"):
                s[block]["quarters"].append("2026Q3")
                s[block]["period_labels"].append("Q3 2026")
                for key, values in s[block].items():
                    if isinstance(values, list) and key not in ("quarters", "period_labels"):
                        values.append(values[-1])
            arr = s["arr"]
            for key in ("quarters", "yoy_quarters"):
                arr[key].append("2026Q3")
            for key in ("period_labels", "yoy_period_labels"):
                arr[key].append("Q3 2026")
            for key, values in arr.items():
                if isinstance(values, list) and key not in ("quarters", "yoy_quarters",
                                                            "period_labels", "yoy_period_labels"):
                    values.append(values[-1])
            opex = s["annual_guidance_history"]["operating_expense"]["by_year"]["2026"]
            opex["releases"].append("2026-10-22")
            opex["guided"].append([2540, 2560, "2026-10-22"])
            tax = s["annual_guidance_history"]["tax_rate"]["by_year"]["2026"]
            tax["releases"].append("2026-10-22")
            tax["guided"].append([22.5, 23.5, "2026-10-22"])

        # The Q2 2026 report set thresholds, so a Q3 page that settles none of them
        # does not build: that is the roll guard on section one.
        with self.assertRaisesRegex(ValueError, "prior_kpi_settlement"):
            self.rebuilt(third_quarter)

        def settled_third_quarter(s):
            third_quarter(s)
            s["prior_kpi_settlement"] = {
                "period": "Q3 2026", "set_in": "Q2 2026",
                "quantified": [{"metric": "期末 ETP AUM", "direction": "up", "threshold": 950.0,
                                "unit": "usd_bn", "actual": 1114.0}]}
        payload = self.rebuilt(settled_third_quarter)
        text = published_text(payload)
        self.assertIn("Q3 2026", payload["title"])
        self.assertIn("前三季已发生的非 GAAP 营业费用", text)
        self.assertIn("第四季度还剩", text)
        self.assertNotIn("上半年已发生", text)
        self.assertIn("FY2026 费用指引的四次发布", text)
        settled = payload["sections"][0]
        self.assertTrue(settled["exhibits"][0]["title"].startswith("上季 1 条量化阈值"))
        self.assertNotIn("第一份季报分析", settled["description"])


if __name__ == "__main__":
    unittest.main()
