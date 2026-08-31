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

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import ndaq  # noqa: E402
from build.all import ENTRIES, build_all, roster_payload  # noqa: E402
from build.board import headroom  # noqa: E402


def js_payload(path: Path, marker: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{marker} = ", 1)[1].rstrip().rstrip(";")
    return json.loads(body)


class NdaqDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(ndaq.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = ndaq.build_payload(cls.staging)

    # ── the eight-quarter window ────────────────────────────────────────────
    def test_the_window_is_eight_quarters_and_complete(self) -> None:
        fin = self.staging["financials"]
        self.assertEqual(len(self.staging["periods"]), 8)
        for name, values in fin.items():
            self.assertEqual(len(values), 8, name)
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
        self.assertEqual(long["quarters"][-8:], self.staging["periods"])
        for offset, quarter in enumerate(self.staging["periods"]):
            index = long["quarters"].index(quarter)
            self.assertAlmostEqual(long["net_revenue"][index],
                                   self.staging["financials"]["net_revenue"][offset],
                                   places=3, msg=quarter)

    def test_the_long_series_is_forty_six_contiguous_quarters(self) -> None:
        quarters = self.staging["long"]["quarters"]
        self.assertEqual(len(quarters), 46)
        self.assertEqual(quarters[0], "2015Q1")
        self.assertEqual(quarters[-1], "2026Q2")

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
        fin = self.staging["financials"]
        for index, period in enumerate(self.staging["periods"]):
            gaap = fin["op_income"][index] / fin["net_revenue"][index] * 100
            self.assertAlmostEqual(gaap, fin["gaap_margin_pct"][index],
                                   delta=0.12, msg=period)
            non_gaap = fin["nongaap_opinc"][index] / fin["net_revenue"][index] * 100
            self.assertAlmostEqual(non_gaap, fin["nongaap_margin_pct"][index],
                                   delta=0.12, msg=period)

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
        # and it is still narrow: only four of forty-two quarters clear the old
        # ceiling, and all four sit in the 2020-2021 retail surge.
        wide = [q for q, v in zip(s31["quarters"], s31["residual_usd_m"]) if v > 9.0]
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
            for year, block in item["by_year"].items():
                if int(year) == 2026:
                    self.assertIsNone(block["actual"], f"{key} {year}")
                elif key == "operating_expense" or int(year) >= 2019:
                    self.assertIsNotNone(block["actual"], f"{key} {year}")

    def test_the_tallies_the_page_publishes_are_the_ones_in_the_data(self) -> None:
        """The headline claim, in both directions.

        Expense has never landed below its final range in eleven years; the tax
        rate has never landed above its final range in seven. If the data stops
        saying that, the page must not keep saying it either.
        """
        opex = self.staging["annual_guidance_history"]["operating_expense"]
        self.assertEqual(ndaq.tally(opex, 1), {"inside": 7, "above": 4, "below": 0})
        self.assertEqual(ndaq.tally(opex, 0), {"inside": 5, "above": 3, "below": 3})
        tax = self.staging["annual_guidance_history"]["tax_rate"]
        self.assertEqual(ndaq.tally(tax, 1), {"inside": 5, "above": 0, "below": 2})
        self.assertEqual(ndaq.tally(tax, 0), {"inside": 4, "above": 0, "below": 3})

    def test_the_expense_record_covers_eleven_finished_years(self) -> None:
        opex = self.staging["annual_guidance_history"]["operating_expense"]
        self.assertEqual(ndaq.finished_years(opex),
                         list(range(2015, 2026)))
        vintages = sum(len(block["guided"])
                       for block in opex["by_year"].values())
        self.assertEqual(vintages, 43)

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
        for year in range(2017, 2026):
            self.assertEqual(counts[year], 4, year)
        self.assertEqual(counts[2026], 3)

    def test_the_tax_record_starts_where_the_disclosure_does(self) -> None:
        """FY2018 was guided but its actual is not disclosed anywhere."""
        tax = self.staging["annual_guidance_history"]["tax_rate"]
        self.assertIn("2018", tax["by_year"])
        self.assertIsNone(tax["by_year"]["2018"]["actual"])
        self.assertEqual(ndaq.finished_years(tax), list(range(2019, 2026)))

    def test_the_open_year_is_excluded_from_every_settled_band(self) -> None:
        """FY2026 is still running; a band drawn over it would settle nothing."""
        for exhibit in self.payload["sections"][0]["exhibits"]:
            if exhibit["kind"] != "range_band":
                continue
            for label in exhibit.get("xlabels", []):
                self.assertNotEqual(label, "FY2026")

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
        self.assertEqual(len(exhibit["xlabels"]), 15)
        stacks = {stack["name"]: stack["values"] for stack in exhibit["stacks"]}
        self.assertEqual(len(stacks), 3)
        for index, quarter in enumerate(self.staging["segments"]["quarters"]):
            total = sum(values[index] for values in stacks.values())
            self.assertAlmostEqual(total, self.staging["segments"]["ms_gross"][index],
                                   delta=0.6, msg=quarter)

    def test_series_that_start_late_are_holes_not_backfills(self) -> None:
        aum = self.staging["etp_aum"]
        self.assertEqual(len(aum["quarters"]), 43)
        self.assertTrue(all(v is not None for v in aum["period_end_usd_b"]))
        for name in ("average_usd_b", "index_revenue_usd_m"):
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
        """Reported +38% includes a one-time contract benefit; adjusted is +35%."""
        by_ref = {ex.get("ref"): ex for section in self.payload["sections"]
                  for ex in section["exhibits"]}
        self.assertIn("35%", by_ref["EX_INDEX"]["note"])

    # ── thresholds, exhibits, publication ───────────────────────────────────
    def test_every_quantified_threshold_has_a_headroom_bar(self) -> None:
        kpi = self.staging["next_kpi"]["quantified"]
        bar = self.payload["sections"][2]["exhibits"][0]
        self.assertEqual(bar["xlabels"], [entry["metric"] for entry in kpi])
        for entry, value in zip(kpi, bar["values"]):
            self.assertAlmostEqual(
                headroom(entry["direction"], entry["threshold"], entry["current"]),
                value, places=1, msg=entry["metric"])

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


if __name__ == "__main__":
    unittest.main()
