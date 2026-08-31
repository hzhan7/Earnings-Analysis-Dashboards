"""AXP page: the reconciliations that license what the page publishes.

Three groups of tests carry most of the weight.

*The identities.* Everything this page claims about "where the profit came
from" rests on `revenue - total expenses - provisions = pretax income` holding
in every quarter, so that the two-leg decomposition contains no estimate.

*The window.* The long series start at 2017Q1 because ASC 606 restated 2017 in
the company's own tables and never restated 2016. Several tests pin that the
page does not quietly reach back past a basis change -- for the income
statement, for the segments, for VCE, and for the derived discount rate.

*The guidance record.* Six of eleven fiscal years cannot be settled, and the
page's whole first section is that fact. These tests pin which years settle,
that the unsettleable ones carry a stated reason, and that no chart puts an
actual on a year the data says is unsettleable.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import axp  # noqa: E402
from build.all import ENTRIES, build_all, roster_payload  # noqa: E402
from build.board import headroom  # noqa: E402


def js_payload(path: Path, marker: str) -> dict:
    text = path.read_text(encoding="utf-8")
    return json.loads(text.split(f"{marker} = ", 1)[1].rstrip().rstrip(";"))


class AxpDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(axp.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = axp.build_payload(cls.staging)
        cls.fin = cls.staging["financials"]
        cls.exhibits = [ex for section in cls.payload["sections"]
                        for ex in section["exhibits"]]

    # ── the window ──────────────────────────────────────────────────────────
    def test_the_long_window_is_thirty_eight_contiguous_quarters(self) -> None:
        periods = self.staging["periods"]
        self.assertEqual(len(periods), 38)
        self.assertEqual(periods[0], "2017Q1")
        self.assertEqual(periods[-1], "2026Q2")
        for earlier, later in zip(periods, periods[1:]):
            y1, q1 = int(earlier[:4]), int(earlier[5])
            y2, q2 = int(later[:4]), int(later[5])
            self.assertEqual((y2, q2), (y1 + 1, 1) if q1 == 4 else (y1, q1 + 1))

    def test_the_window_does_not_reach_back_past_asc_606(self) -> None:
        """2016 was never restated in the statistical tables, so it is not here.

        The Q1'17 discount revenue printed in the January 2018 release is 4,519
        and the same quarter in the April 2018 release is 5,387. 2017 exists on
        both bases and the page takes the restated one; 2016 exists only on the
        old one, so joining it would draw a ~10% revenue step that is a
        presentation change and nothing else.
        """
        self.assertNotIn("2016Q4", self.staging["periods"])
        self.assertEqual(self.staging["financials"]["discount_revenue_usd_m"][0], 5387.0)

    def test_every_headline_series_is_complete_over_the_window(self) -> None:
        partial = {"business_development_usd_m", "marketing_usd_m",
                   "marketing_and_business_development_usd_m"}
        for name, values in self.fin.items():
            self.assertEqual(len(values), 38, name)
            if name not in partial:
                self.assertTrue(all(v is not None for v in values), name)

    # ── the identities the page's arguments rest on ─────────────────────────
    def test_income_statement_identity_holds_every_quarter(self) -> None:
        fin = self.fin
        for i, period in enumerate(self.staging["periods"]):
            self.assertAlmostEqual(
                fin["revenue_usd_m"][i] - fin["total_expenses_usd_m"][i]
                - fin["provisions_usd_m"][i],
                fin["pretax_income_usd_m"][i], places=6, msg=period)

    def test_pre_provision_profit_is_revenue_less_total_expenses(self) -> None:
        fin = self.fin
        for i, period in enumerate(self.staging["periods"]):
            self.assertAlmostEqual(
                fin["ppop_usd_m"][i],
                fin["revenue_usd_m"][i] - fin["total_expenses_usd_m"][i],
                places=6, msg=period)

    def test_the_two_legs_sum_to_the_pretax_change_every_quarter(self) -> None:
        """The decomposition in section two is an identity, not an estimate."""
        fin = self.fin
        for i in range(4, len(self.staging["periods"])):
            operating = fin["ppop_usd_m"][i] - fin["ppop_usd_m"][i - 4]
            provision = -(fin["provisions_usd_m"][i] - fin["provisions_usd_m"][i - 4])
            self.assertAlmostEqual(
                operating + provision,
                fin["pretax_income_usd_m"][i] - fin["pretax_income_usd_m"][i - 4],
                places=6, msg=self.staging["periods"][i])

    def test_the_four_revenue_legs_sum_to_revenue_every_quarter(self) -> None:
        fin = self.fin
        for i, period in enumerate(self.staging["periods"]):
            self.assertAlmostEqual(
                fin["discount_revenue_usd_m"][i] + fin["net_card_fees_usd_m"][i]
                + fin["other_non_interest_revenue_usd_m"][i]
                + fin["net_interest_income_usd_m"][i],
                fin["revenue_usd_m"][i], places=6, msg=period)

    def test_non_interest_revenue_reconciles_to_the_filed_total(self) -> None:
        fin = self.fin
        for i, period in enumerate(self.staging["periods"]):
            self.assertAlmostEqual(
                fin["total_non_interest_revenues_usd_m"][i]
                + fin["total_interest_income_usd_m"][i]
                - fin["total_interest_expense_usd_m"][i],
                fin["revenue_usd_m"][i], places=6, msg=period)

    def test_pretax_less_tax_is_net_income_every_quarter(self) -> None:
        fin = self.fin
        for i, period in enumerate(self.staging["periods"]):
            self.assertAlmostEqual(
                fin["pretax_income_usd_m"][i] - fin["tax_provision_usd_m"][i],
                fin["net_income_usd_m"][i], places=6, msg=period)

    # ── series that start late are holes, not backfills ─────────────────────
    def test_vce_components_start_where_the_company_split_the_line(self) -> None:
        """`business development` left `Marketing` only in the 2022-04-22 release."""
        periods = self.staging["periods"]
        bizdev = self.fin["business_development_usd_m"]
        present = [p for p, v in zip(periods, bizdev) if v is not None]
        self.assertEqual(present[0], "2021Q1")
        self.assertEqual(len(present), 22)
        legacy = self.fin["marketing_and_business_development_usd_m"]
        legacy_present = [p for p, v in zip(periods, legacy) if v is not None]
        self.assertEqual(legacy_present[-1], "2021Q4")

    def test_the_legacy_combined_line_equals_the_split_where_both_exist(self) -> None:
        """The overlap is what licenses treating them as one quantity."""
        overlap = 0
        for i, period in enumerate(self.staging["periods"]):
            combined = self.fin["marketing_and_business_development_usd_m"][i]
            marketing = self.fin["marketing_usd_m"][i]
            bizdev = self.fin["business_development_usd_m"][i]
            if None in (combined, marketing, bizdev):
                continue
            overlap += 1
            self.assertAlmostEqual(marketing + bizdev, combined, places=6, msg=period)
        self.assertEqual(overlap, 4)

    def test_segments_start_at_the_recast_and_are_not_padded_backwards(self) -> None:
        seg_periods = self.staging["segment_periods"]
        self.assertEqual(seg_periods[0], "2020Q1")
        self.assertEqual(len(seg_periods), 26)
        for tag, block in self.staging["segments_usd_m"].items():
            self.assertEqual(len(block["revenue_usd_m"]), 26, tag)
            self.assertTrue(all(v is not None for v in block["revenue_usd_m"]), tag)

    def test_the_company_stopped_printing_its_average_discount_rate(self) -> None:
        periods = self.staging["periods"]
        printed = self.staging["operating_metrics"]["company_average_discount_rate_pct"]
        present = [p for p, v in zip(periods, printed) if v is not None]
        self.assertEqual(present[0], "2017Q1")
        self.assertEqual(present[-1], "2022Q4")
        self.assertEqual(len(present), 24)
        for period, value in zip(periods, printed):
            if period > "2022Q4":
                self.assertIsNone(value, period)

    def test_the_derived_discount_rate_starts_after_the_carve_out(self) -> None:
        """2020's numerator still contains processed revenue; its denominator does not.

        The 2021-04-23 release recast billed business onto a proprietary-only
        basis back through 2020, and the 2022-04-22 release carved processed
        revenue out of discount revenue only back through 2021Q1. Dividing the
        old numerator by the new denominator reads as a price rise that never
        happened, and no filed identity catches it -- so the chart starts at
        2021Q1 rather than being extended.
        """
        rate = next(ex for ex in self.exhibits if ex.get("ref") == "EX_RATE")
        derived = rate["series"][1]["values"]
        for period, value in zip(self.staging["periods"], derived):
            if period < "2021Q1":
                self.assertIsNone(value, period)
            else:
                self.assertIsNotNone(value, period)

    def test_the_printed_and_derived_rates_are_two_series_not_one(self) -> None:
        rate = next(ex for ex in self.exhibits if ex.get("ref") == "EX_RATE")
        self.assertEqual(len(rate["series"]), 2)
        printed, derived = rate["series"][0]["values"], rate["series"][1]["values"]
        gaps = [(d - p) * 100 for p, d in zip(printed, derived)
                if p is not None and d is not None]
        self.assertEqual(len(gaps), 8)
        # A steady 4-5bp level offset. Splicing them would put that offset on
        # the page as a step at the quarter the company stopped publishing.
        self.assertTrue(all(-6.0 < g < -3.0 for g in gaps), gaps)

    def test_the_credit_splice_is_defended_by_an_overlap(self) -> None:
        credit = self.staging["credit_metrics"]
        self.assertEqual(len(credit["basis_overlap_quarters"]), 4)
        periods = self.staging["periods"]
        # The tracked basis is loans *and* receivables combined. The company
        # first printed it with the 2023Q1 release, five trailing quarters back
        # to 2022Q1; the write-off rate starts there. The delinquency rate is a
        # point-in-time figure, so the FY2023 10-K's three-year table licenses
        # one quarter more -- and nothing licenses a second one.
        starts = {"past_due_30_pct": "2021Q4",
                  "net_write_off_rate_principal_pct": "2022Q1"}
        self.assertEqual(credit["combined_basis_first_quarter"], "2022Q1")
        for name, first in starts.items():
            present = [p for p, v in zip(periods, credit[name]) if v is not None]
            self.assertEqual(present[0], first, name)
            self.assertEqual(present[-1], "2026Q2", name)
            self.assertEqual(len(present), periods.index("2026Q2") - periods.index(first) + 1,
                             f"{name} has an interior hole")

    def test_the_annual_delinquency_column_is_the_fourth_quarter(self) -> None:
        """What licenses the one quarter the tracked series reaches back.

        30+ days past due is a point-in-time ratio, so the 10-K's annual column
        should be the fourth quarter's value -- and in every year where both
        exist it is, while in every one of those years it differs from the
        loans-only reading for the same quarter. That second half is what makes
        it a test and not a coincidence: it tells the two bases apart.
        """
        credit = self.staging["credit_metrics"]
        annual = credit["annual_past_due_30_pct"]["values"]
        periods = self.staging["periods"]
        checked = 0
        for year, value in annual.items():
            if f"{year}Q4" not in periods:
                continue
            index = periods.index(f"{year}Q4")
            quarterly = credit["past_due_30_pct"][index]
            if quarterly is None:
                continue
            self.assertEqual(quarterly, value, year)
            if year != "2021":                    # the year being licensed
                self.assertNotEqual(credit["loans_basis"]["past_due_30_pct"][index], value,
                                    f"{year} cannot tell the two bases apart")
                checked += 1
        self.assertEqual(checked, 4)
        self.assertEqual(credit["past_due_30_pct"][periods.index("2021Q4")], annual["2021"])

    def test_ten_k_year_ends_pin_the_pre_2022_half_of_the_loans_basis(self) -> None:
        """The half of the credit data that no other check reaches.

        Reproducing the eighteen already-published quarters only gates 2022Q1
        onward; everything before it comes out of two older supplement formats
        where reading one column across would go unnoticed. Nine 10-Ks print
        the same loans-basis delinquency at each year end, and it is a
        point-in-time ratio, so each must equal that year's fourth quarter.
        """
        loans = self.staging["credit_metrics"]["loans_basis"]
        annual = loans["annual_past_due_30_pct"]["values"]
        periods = self.staging["periods"]
        self.assertEqual(sorted(annual), [str(y) for y in range(2017, 2026)])
        for year, value in annual.items():
            index = periods.index(f"{year}Q4")
            self.assertEqual(loans["past_due_30_pct"][index], value, year)

    def test_the_two_credit_bases_are_two_series_not_one(self) -> None:
        """2017-2021 is a disclosure boundary, not a collection gap.

        The loans-only basis runs the whole window and would look like a
        backfill, but over the sixteen quarters where the company prints both
        it agrees with the tracked basis in exactly one, and the sign of the
        difference flips partway -- so there is no offset to splice away.
        """
        credit = self.staging["credit_metrics"]
        loans = credit["loans_basis"]
        periods = self.staging["periods"]
        pairs = (("past_due_30_pct", 0.1), ("net_write_off_rate_principal_pct", 0.3))
        gaps: dict[str, dict[str, float]] = {}
        signs = set()
        for name, widest in pairs:
            self.assertEqual(len(loans[name]), len(periods), name)
            present = [p for p, v in zip(periods, loans[name]) if v is not None]
            self.assertEqual((present[0], present[-1]), ("2017Q1", "2025Q4"), name)
            self.assertEqual(len(present), 36, name)
            for period, tracked, other in zip(periods, credit[name], loans[name]):
                if tracked is None or other is None:
                    continue
                gap = round(other - tracked, 10)
                gaps.setdefault(period, {})[name] = gap
                if gap:
                    signs.add(gap > 0)
                self.assertLessEqual(abs(gap), widest + 1e-9, name)
        # Both metrics are printed on both bases for 2022Q1-2025Q4; 2021Q4 is
        # the delinquency rate reaching back on its own.
        both = {p: g for p, g in gaps.items() if len(g) == 2}
        self.assertEqual(len(both), loans["overlap_quarters"])
        self.assertEqual(sum(1 for g in both.values() if set(g.values()) == {0.0}),
                         loans["overlap_quarters_identical"])
        self.assertEqual(signs, {True, False})

    def test_the_credit_charts_carry_the_older_basis_as_its_own_line(self) -> None:
        titles = ("30+ 天逾期率", "净核销率（本金口径）")
        loans = self.staging["credit_metrics"]["loans_basis"]
        found = 0
        for ex in self.exhibits:
            if not ex.get("title", "").startswith(titles):
                continue
            found += 1
            self.assertEqual(len(ex["series"]), 3, ex["title"])
            self.assertEqual([s["color"] for s in ex["series"]], ["NAVY", "RED", "GRAY"])
            grey = ex["series"][2]
            self.assertIn(loans["label"], grey["name"])
            self.assertEqual(len(grey["values"]), len(ex["xlabels"]))
            # The grey line stops where the company stopped printing it.
            self.assertEqual([v is None for v in grey["values"]][-2:], [True, True])
        self.assertEqual(found, 2)

    # ── the annual guidance record ──────────────────────────────────────────
    def test_forty_three_vintages_across_eleven_fiscal_years(self) -> None:
        record = self.staging["annual_guidance_history"]
        self.assertEqual(len(record["vintages"]), 43)
        self.assertEqual(sorted(set(record["fiscal_years"])), list(range(2016, 2027)))
        for key in ("filed", "vintage_slots", "guide_eps_lo_usd",
                    "guide_revenue_growth_lo_pct"):
            self.assertEqual(len(record[key]), 43, key)

    def test_seven_consecutive_releases_carry_no_annual_guidance(self) -> None:
        """Withdrawn in March 2020, then never re-issued until January 2022.

        A later release (2023-10-20) is also blank -- it reaffirms FY2023
        without printing a number -- so the run has to be measured as a run and
        not as a count of blank cells.
        """
        record = self.staging["annual_guidance_history"]
        blank = [i for i, (eps, rev) in enumerate(zip(record["guide_eps_lo_usd"],
                                                      record["guide_revenue_growth_lo_pct"]))
                 if eps is None and rev is None]
        run = [blank[0]]
        for index in blank[1:]:
            if index != run[-1] + 1:
                break
            run.append(index)
        self.assertEqual(record["filed"][run[0]], "2020-04-24")
        self.assertEqual(record["filed"][run[-1]], "2021-10-22")
        self.assertEqual(len(run), 7)

    def test_the_withdrawal_is_recorded_outside_the_earnings_releases(self) -> None:
        withdrawal = self.staging["annual_guidance_history"]["withdrawal"]
        self.assertEqual(withdrawal["announced"], "2020-03-17")
        self.assertTrue(withdrawal["accession"])

    def test_only_the_settleable_years_carry_an_actual(self) -> None:
        record = self.staging["annual_guidance_history"]
        for metric, actual_key in (("eps", "actual_diluted_eps_usd"),
                                   ("revenue", "actual_revenue_growth_pct")):
            settled = record["verdicts"][metric]
            filled = {record["fiscal_years"][i]
                      for i, v in enumerate(record[actual_key]) if v is not None}
            self.assertEqual(filled, {int(y) for y in settled}, metric)

    def test_five_eps_years_and_six_revenue_years_settle(self) -> None:
        record = self.staging["annual_guidance_history"]
        self.assertEqual(len(record["verdicts"]["eps"]), 5)
        self.assertEqual(len(record["verdicts"]["revenue"]), 6)

    def test_every_unsettleable_year_states_why(self) -> None:
        record = self.staging["annual_guidance_history"]
        for metric in ("eps", "revenue"):
            settled = set(record["verdicts"][metric])
            reasons = record["unsettleable"][metric]
            years = {str(y) for y in record["fiscal_years"]}
            self.assertEqual(settled | set(reasons), years, metric)
            self.assertFalse(settled & set(reasons), metric)
            for year, reason in reasons.items():
                self.assertTrue(reason.strip(), f"{metric} {year}")

    def test_eps_never_landed_below_its_range_and_revenue_did_once(self) -> None:
        """The two-sided finding the page is built on, pinned by value."""
        verdicts = self.staging["annual_guidance_history"]["verdicts"]
        eps = [v["verdict"] for v in verdicts["eps"].values()]
        revenue = [v["verdict"] for v in verdicts["revenue"].values()]
        self.assertEqual(eps.count("below"), 0)
        self.assertEqual(revenue.count("below"), 1)
        self.assertEqual(verdicts["revenue"]["2023"]["verdict"], "below")

    def test_the_revenue_actual_is_the_company_s_own_whole_point_figure(self) -> None:
        """Settling a whole-point promise against a two-decimal quotient would
        invent a precision the guidance never had."""
        record = self.staging["annual_guidance_history"]
        band = next(ex for ex in self.exhibits if ex.get("ref") == "EX_REV_BAND")
        for value in band["actual"]:
            if value is not None:
                self.assertEqual(value, round(value), value)
        for year, block in record["verdicts"]["revenue"].items():
            index = record["filed"].index(block["settling_release"])
            self.assertEqual(
                band["actual"][index],
                float(record["actual_by_year"][year]["growth_reported_pct"]), year)

    def test_fy2023_is_a_miss_on_one_basis_and_not_on_the_other(self) -> None:
        block = self.staging["annual_guidance_history"]["actual_by_year"]["2023"]
        self.assertEqual(block["growth_reported_pct"], 14)
        self.assertEqual(block["growth_fx_pct"], 15)

    def test_the_full_year_revenue_reproduces_the_quoted_growth(self) -> None:
        record = self.staging["annual_guidance_history"]
        years = record["actual_by_year"]
        for year in sorted(years):
            prior = years.get(str(int(year) - 1))
            block = years[year]
            if prior is None or block["growth_exact_pct"] is None:
                continue
            self.assertAlmostEqual(
                block["growth_exact_pct"],
                (block["revenue_usd_m"] / prior["revenue_usd_m"] - 1) * 100,
                places=3, msg=year)

    # ── thresholds ──────────────────────────────────────────────────────────
    def test_every_quantified_threshold_has_a_headroom_bar(self) -> None:
        for block, key, ref in (("next_kpi", "current", "下季"),
                                ("settled_kpi", "actual", "上季")):
            entries = self.staging[block]["quantified"]
            bar = next(ex for ex in self.exhibits
                       if ex["kind"] == "diverging_bars" and ref in ex["title"])
            self.assertEqual(bar["xlabels"], [e["metric"] for e in entries])
            for entry, value in zip(entries, bar["values"]):
                self.assertAlmostEqual(
                    value, round(headroom(entry["direction"], entry["threshold"],
                                          entry[key]), 1), places=6, msg=entry["metric"])

    def test_the_thresholds_the_page_declines_are_named(self) -> None:
        excluded = self.staging["next_kpi"]["excluded"]
        self.assertIn("整数", excluded)
        self.assertIn("市场一致预期", excluded)

    def test_no_market_expectation_is_published(self) -> None:
        blob = json.dumps(self.payload, ensure_ascii=False)
        for banned in ("目标价", "评级", "买入", "卖出", "共识 EPS"):
            self.assertNotIn(banned, blob.replace("不发布评级、目标价与估值", "")
                             .replace("不放评级、目标价", ""))

    # ── renderer contract ───────────────────────────────────────────────────
    def test_exhibits_are_numbered_in_render_order_and_refs_resolve(self) -> None:
        numbers = [ex["n"] for ex in self.exhibits]
        self.assertEqual(numbers, list(range(2, 2 + len(numbers))))
        for exhibit in self.exhibits:
            for field in ("title", "note", "src_extra"):
                self.assertNotRegex(exhibit.get(field) or "", r"\{[A-Z_]+\}")

    def test_tables_are_numbered_after_the_exhibits(self) -> None:
        first = self.payload["tables"][0]["n"]
        self.assertEqual(first, self.exhibits[-1]["n"] + 1)
        self.assertEqual([t["n"] for t in self.payload["tables"]],
                         list(range(first, first + len(self.payload["tables"]))))

    def test_every_exhibit_carries_a_note_and_a_source_line(self) -> None:
        for exhibit in self.exhibits:
            self.assertTrue((exhibit.get("note") or "").strip(), exhibit["title"])
            self.assertTrue((exhibit.get("src_extra") or "").strip(), exhibit["title"])

    def test_literal_text_fields_carry_no_markup(self) -> None:
        """`page.js` writes these with textContent or through esc()."""
        for field in ("headline", "title", "subtitle", "tracker"):
            self.assertNotIn("<", self.payload[field], field)
        for section in self.payload["sections"]:
            self.assertNotIn("<", section["title"])
            self.assertNotIn("<", section["description"])
        for note in self.payload["notes"]:
            self.assertNotIn("<", note)
        for table in self.payload["tables"]:
            self.assertNotIn("<", table["title"])

    def test_table_dicts_carry_only_the_keys_the_renderer_reads(self) -> None:
        for table in self.payload["tables"]:
            self.assertEqual(set(table), {"n", "title", "headers", "rows"}, table["title"])
            for row in table["rows"]:
                self.assertEqual(len(row), len(table["headers"]), table["title"])

    def test_the_cross_page_capex_table_is_carried(self) -> None:
        titles = [t["title"] for t in self.payload["tables"]]
        self.assertTrue(any("AI capex 循环" in t for t in titles))

    def test_axp_is_not_a_column_in_the_cross_page_capex_table(self) -> None:
        table = next(t for t in self.payload["tables"] if "AI capex 循环" in t["title"])
        self.assertNotIn("AXP", " ".join(table["headers"]))

    def test_the_notes_name_the_unsettleable_years_correctly(self) -> None:
        """A hand-written year list in prose is exactly what drifts silently."""
        record = self.staging["annual_guidance_history"]
        note = next(n for n in self.payload["notes"] if "可以被诚实结清" in n)
        unsettleable = set(record["unsettleable"]["eps"])
        settled = set(record["verdicts"]["eps"])
        for year in unsettleable:
            self.assertIn(f"FY{year}", note, year)
        # A settled year must not be listed among the reasons it could not be.
        reasons = note.split("EPS 不能结清的六年各有原因：", 1)[1].split("另有一年", 1)[0]
        for year in settled:
            self.assertNotIn(f"FY{year}", reasons, year)

    def test_the_notes_say_why_the_window_starts_where_it_does(self) -> None:
        notes = " ".join(self.payload["notes"])
        self.assertIn("ASC 606", notes)
        self.assertIn("2017", notes)
        self.assertIn("2020-03-17", notes)

    def test_the_published_payload_matches_a_fresh_build(self) -> None:
        published = js_payload(ROOT / "data" / "axp.js", "window.DASH")
        self.assertEqual(published, self.payload)

    def test_the_roster_carries_axp_with_the_payload_s_own_labels(self) -> None:
        roster = roster_payload(build_all())
        entry = next(i for i in roster["items"] if i["slug"] == "axp")
        self.assertEqual(entry["latest_label"],
                         self.payload["latest"]["disclosed_period_label"])
        self.assertEqual(entry["release_date"], self.payload["latest"]["release_date"])
        self.assertEqual(entry["group"], self.payload["company"]["group"])

    def test_the_entry_group_exists_and_sits_where_its_order_says(self) -> None:
        entry = next(e for e in ENTRIES if e["slug"] == "axp")
        self.assertEqual(entry["group"], "payment_networks")
        self.assertEqual(entry["ticker"], "AXP")

    def test_the_shell_links_the_payload_by_content_hash(self) -> None:
        shell = (ROOT / "axp" / "index.html").read_text(encoding="utf-8")
        self.assertIn("../data/axp.js?v=", shell)
        self.assertIn("../data/roster.js?v=", shell)
        self.assertNotIn("../data/msci.js", shell)
        for match in re.finditer(r'src="\.\./([^"?]+)\?v=([0-9a-f]{8})"', shell):
            import hashlib
            digest = hashlib.sha256((ROOT / match.group(1)).read_bytes()).hexdigest()[:8]
            self.assertEqual(match.group(2), digest, match.group(1))


if __name__ == "__main__":
    unittest.main()
