"""AXP page: the reconciliations that license what the page publishes.

Three groups of tests carry most of the weight.

*The identities.* Everything this page claims about "where the profit came
from" rests on `revenue - total expenses - provisions = pretax income` holding
in every quarter, so that the two-leg decomposition contains no estimate.

*The window.* The long series start at 2016Q1 on one basis: ASC 606 was
restated for 2016 in a separate 8-K, and the series that start later (VCE,
segments, the combined credit basis, the derived discount rate) start where
the company's own disclosure does. Several tests pin that the page does not
quietly reach back past a basis change.

*The guidance record.* About half of the year-metric pairs cannot be settled,
and the page's whole first section is that fact. Which years settle, the
verdicts and where each actual lands are derived from the record; the only
stored judgements are the years the page declines to settle.

A roll edits `series/axp.json` and nothing else. What the quarter's release
printed is asserted from `_checks` (`AxpChecksTest`); `AxpRollTest` rolls the
series a quarter back and two forward and tampers each stamped block; and
`AxpFindingsTest` forces each judgement true and then false and checks that the
words follow. What stays pinned by value is history a roll cannot move.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import axp  # noqa: E402
from build.all import ENTRIES, build_all, roster_payload  # noqa: E402
from build.board import cn_count, headroom  # noqa: E402


def js_payload(path: Path, marker: str) -> dict:
    text = path.read_text(encoding="utf-8")
    return json.loads(text.split(f"{marker} = ", 1)[1].rstrip().rstrip(";"))


def exhibits_of(payload: dict) -> list[dict]:
    return [ex for section in payload["sections"] for ex in section["exhibits"]]


def own_text(payload: dict) -> str:
    """Everything the page says, less the cross-page table every page carries."""
    own = dict(payload, tables=[t for t in payload["tables"] if "AI capex" not in t["title"]])
    return json.dumps(own, ensure_ascii=False)


class AxpDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(axp.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = axp.build_payload(cls.staging)
        cls.fin = cls.staging["financials"]
        cls.exhibits = exhibits_of(cls.payload)
        cls.facts = axp.record_facts(cls.staging)

    # ── the window ──────────────────────────────────────────────────────────
    def test_the_long_window_is_contiguous_from_2016q1(self) -> None:
        periods = self.staging["periods"]
        self.assertEqual(periods[0], "2016Q1")
        self.assertEqual(axp.quarter_label(periods[-1]), self.staging["latest"]["period"])
        self.assertEqual([axp.quarter_label(p) for p in periods], self.staging["period_labels"])
        self.assertEqual(len(self.staging["period_ends"]), len(periods))
        for earlier, later in zip(periods, periods[1:]):
            y1, q1 = int(earlier[:4]), int(earlier[5])
            y2, q2 = int(later[:4]), int(later[5])
            self.assertEqual((y2, q2), (y1 + 1, 1) if q1 == 4 else (y1, q1 + 1))

    def test_the_2016_quarters_are_on_the_recast_basis(self) -> None:
        """One basis for every quarter -- and it is the later one.

        This test replaced `test_the_income_statement_stops_where_the_recast_stops`,
        whose premise was that "American Express recast 2017 by quarter and never
        republished 2016 by quarter". The reasoning behind that was a pattern:
        each earnings release prints only five quarters side by side, so the last
        release carrying Q4 2016 predates the change. True of the releases, false
        of the company -- the 8-K of 2018-03-09, Item 7.01, Exhibit 99.1 prints
        As Reported / Adjustments / As Recast for Q1 2016 through Q4 2017.

        The assertions pick values where the two bases DIFFER, so the test can
        tell which one is loaded rather than merely that something is there.
        Discount revenue is the widest: the recast grosses it up by about a fifth.
        Net income is the narrowest that still moves, and it is the one that
        matters most, because the old page carried 2016 net income and EPS on the
        old basis while calling them untouched -- they move by +13, -30, 0, -16.
        """
        fin, periods = self.staging["financials"], self.staging["periods"]
        self.assertEqual(periods[0], "2016Q1")

        # (as recast, as reported) for 2016Q1, both printed in the same exhibit
        for name, recast_v, reported_v in (
            ("revenue_usd_m", 8913.0, 8088.0),
            ("discount_revenue_usd_m", 5528.0, 4643.0),
            ("total_expenses_usd_m", 6273.0, 5470.0),
            ("pretax_income_usd_m", 2206.0, 2184.0),
            ("net_income_usd_m", 1439.0, 1426.0),
            # Named because a mutation showed nothing else catches it. The
            # revenue side has a sum identity (four legs -> revenue), so a leg
            # that reverted to the old basis fails somewhere regardless. The
            # EXPENSE side has none: this page does not carry occupancy and
            # equipment, so the expense lines it does carry cannot be summed
            # against total expenses, and professional services -- which the
            # recast moved by about 3% -- is protected by this list alone.
            ("professional_services_usd_m", 584.0, 604.0),
        ):
            self.assertEqual(fin[name][0], recast_v, name)
            self.assertNotEqual(fin[name][0], reported_v,
                                f"{name} is on the superseded as-reported basis")

        # Lines the recast genuinely left alone read the same on either basis, so
        # they are not evidence of which one is loaded -- pinned here so that
        # stays visible rather than looking like more of the same.
        for name, value in (("provisions_usd_m", 434.0), ("diluted_shares_m", 963.0),
                            ("net_card_fees_usd_m", 699.0)):
            self.assertEqual(fin[name][0], value, name)

    def test_no_income_statement_series_starts_late_any_more(self) -> None:
        """The nine lines that used to be empty for 2016 are filled.

        Named individually rather than swept, because a sweep would pass if the
        file were re-cut to start at 2017 -- every remaining series would still
        be complete over its own shorter axis.
        """
        fin = self.staging["financials"]
        formerly_empty = [
            "revenue_usd_m", "discount_revenue_usd_m",
            "other_non_interest_revenue_usd_m", "total_non_interest_revenues_usd_m",
            "rewards_usd_m", "card_member_services_usd_m",
            "marketing_and_business_development_usd_m", "other_net_usd_m",
            "total_expenses_usd_m",
        ]
        for name in formerly_empty:
            self.assertEqual(len(fin[name]), len(self.staging["periods"]), name)
            self.assertTrue(all(v is not None for v in fin[name][:4]),
                            f"{name} is empty for 2016 again")

    def test_every_headline_series_is_complete_over_the_whole_axis(self) -> None:
        partial = {"business_development_usd_m", "marketing_usd_m",
                   "marketing_and_business_development_usd_m"}
        for name, values in self.fin.items():
            if not isinstance(values, list):
                continue
            self.assertEqual(len(values), len(self.staging["periods"]), name)
            if name not in partial:
                self.assertTrue(all(v is not None for v in values), name)

    def test_the_effective_tax_rate_is_the_ratio_it_claims_to_be(self) -> None:
        """Three cells used to hold the *next* quarter's rate.

        2017Q4 stored 21.5 while its own tax provision and pretax income give
        167.1 -- that is the US tax-reform charge quarter, pretax 1,798 against
        a 3,004 provision and a 1,206 loss. 2018Q1 held 2018Q2's rate and 2018Q2
        held 2018Q3's; the series came back into step at 2018Q3, so it was a
        three-cell run reading one quarter late. Nothing outside the file was
        needed to see it, which is why the identity is now asserted rather than
        the values transcribed.
        """
        fin = self.staging["financials"]
        for index, period in enumerate(self.staging["periods"]):
            tax = fin["tax_provision_usd_m"][index]
            pretax = fin["pretax_income_usd_m"][index]
            rate = fin["effective_tax_rate_pct"][index]
            if tax is None or pretax is None:
                self.assertIsNone(rate, period)
                continue
            self.assertAlmostEqual(round(tax / pretax * 100, 1), rate,
                                   places=6, msg=period)
        quarter = self.staging["periods"].index("2017Q4")
        self.assertAlmostEqual(fin["effective_tax_rate_pct"][quarter], 167.1)
        self.assertLess(fin["net_income_usd_m"][quarter], 0)

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
        self.assertEqual(present, periods[periods.index("2021Q1"):], "a hole inside the VCE run")
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
        periods = self.staging["periods"]
        self.assertEqual(seg_periods[0], "2020Q1")
        self.assertEqual(seg_periods, periods[periods.index("2020Q1"):])
        for tag, block in self.staging["segments_usd_m"].items():
            self.assertEqual(len(block["revenue_usd_m"]), len(seg_periods), tag)
            self.assertTrue(all(v is not None for v in block["revenue_usd_m"]), tag)

    def test_the_company_stopped_printing_its_average_discount_rate(self) -> None:
        periods = self.staging["periods"]
        printed = self.staging["operating_metrics"]["company_average_discount_rate_pct"]
        present = [p for p, v in zip(periods, printed) if v is not None]
        # The company's own printed rate is unaffected by ASC 606 -- it runs
        # smoothly 2.44% -> 2.43% straight across the recast boundary -- and was
        # only truncated to 2017Q1 because it rode the same `recast()` helper as
        # the revenue lines. That was a code path, not a basis limit.
        self.assertEqual(present[0], "2016Q1")
        self.assertEqual(present[-1], "2022Q4")
        self.assertEqual(len(present), 28)
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
        self.assertEqual(len(derived), len(self.staging["periods"]))
        for period, value in zip(self.staging["periods"], derived):
            if period < "2021Q1":
                self.assertIsNone(value, period)
            else:
                self.assertIsNotNone(value, period)

    def test_the_printed_discount_rate_is_drawn_on_the_axis_the_data_has(self) -> None:
        """The printed line and the derived line have different floors.

        The derived one is a basis limit (the test above). The printed one never
        was: it was truncated to 2017Q1 because the whole `operating_metrics`
        block went through `recast()`, so four filed quarters were dropped from
        a series ASC 606 does not touch. Pinning the axis here means the chart
        cannot quietly go back to reading the cut block.
        """
        rate = next(ex for ex in self.exhibits if ex.get("ref") == "EX_RATE")
        printed = self.staging["operating_metrics"]["company_average_discount_rate_pct"]
        self.assertEqual(rate["xlabels"], self.staging["period_labels"])
        self.assertEqual(rate["xlabels"][0], "Q1 2016")
        self.assertEqual(rate["series"][0]["values"][:4], printed[:4])
        # The note counts the quarters off the same list it plots.
        self.assertIn(f"印了 {sum(1 for v in printed if v is not None)} 个季度", rate["note"])

    def test_billed_business_yoy_starts_where_its_own_base_exists(self) -> None:
        """Two quarters that were being thrown away before they could be used.

        Billed business carries 2016Q3-Q4, so the first quarter with a base is
        2017Q3. Read through the old `recast()` helper the base disappeared and
        the line started at 2018Q1 -- four filed dollar figures short of what the
        record supports.

        2017Q3 is now a *disclosure* floor and not a coverage one, which is the
        opposite of what this page assumed while the entry was unchecked. The
        figure here is the proprietary (ex-GNS) total; AmEx first printed that as
        a consolidated dollar line in its Q3 2017 release, whose trailing window
        stops at 2016Q3. 2016Q1-Q2 exist only as a subtraction the company never
        published, so no later pull can reach them.
        """
        periods = self.staging["periods"]
        billed = self.staging["operating_metrics"]["billed_business_usd_bn"]
        chart = next(ex for ex in self.exhibits
                     if ex["kind"] == "lines" and ex["title"].startswith("消费额同比"))
        first = next(i for i in range(4, len(billed))
                     if billed[i] is not None and billed[i - 4] is not None)
        self.assertEqual(periods[first], "2017Q3")
        self.assertIsNone(billed[0], "2016Q1 proprietary billed business was never printed")
        self.assertIsNone(billed[1], "2016Q2 proprietary billed business was never printed")
        self.assertEqual(chart["xlabels"][0], self.staging["period_labels"][first])
        self.assertEqual(len(chart["xlabels"]), len(billed) - first)
        self.assertAlmostEqual(chart["series"][0]["values"][0],
                               round((billed[first] / billed[first - 4] - 1) * 100, 6))

    def test_the_buyback_note_counts_shares_over_the_axis_it_plots(self) -> None:
        """The note's whole argument is a comparison of two multiples.

        Reading diluted shares through `recast()` while the chart plots the
        whole axis put a 38-quarter buyback next to a 42-quarter pair of
        multiples: the residual the note calls preferred dividends and
        participating awards came out at 7.7%, not 1.0%.
        """
        buyback = next(ex for ex in self.exhibits if ex.get("ref") == "EX_BUYBACK")
        fin = self.staging["financials"]
        shares = fin["diluted_shares_m"]
        printed = re.search(r"从 ([\d,]+)M 降到 ([\d,]+)M", buyback["note"])
        self.assertEqual([float(printed.group(1).replace(",", "")),
                          float(printed.group(2).replace(",", ""))],
                         [shares[0], shares[-1]])
        multiples = ((fin["diluted_eps_usd"][-1] / fin["diluted_eps_usd"][0])
                     / (fin["net_income_usd_m"][-1] / fin["net_income_usd_m"][0]))
        self.assertLess(abs(multiples / (shares[0] / shares[-1]) - 1), 0.02)

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
            self.assertEqual(present[-1], periods[-1], name)
            self.assertEqual(len(present), len(periods) - periods.index(first),
                             f"{name} has an interior hole")
        # The four overlap quarters are named on the chart they license.
        dpd = next(ex for ex in self.exhibits if ex["title"].startswith("30+ 天逾期率"))
        overlap = credit["basis_overlap_quarters"]
        self.assertIn(f"（{overlap[0]}–{overlap[-1]}）两种口径印出来的数字完全相同", dpd["note"])

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
        """2016-2021 is a disclosure boundary, not a collection gap.

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
            # The company printed this table from 2015Q4 to 2025Q4; 2016Q1 is
            # only where this page's axis begins, and the table stopped when
            # the company merged loans and receivables into Card balances.
            self.assertEqual((present[0], present[-1]), ("2016Q1", "2025Q4"), name)
            self.assertEqual(len(present), 40, name)
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
        periods = self.staging["periods"]
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
            self.assertTrue(all(v is None for p, v in zip(periods, grey["values"]) if p >= "2026Q1"))
        self.assertEqual(found, 2)

    def test_the_loans_note_counts_the_quarters_it_covers(self) -> None:
        """The note said 36 quarters from 2017Q1 after the line reached 2016Q1."""
        loans = self.staging["credit_metrics"]["loans_basis"]
        periods = self.staging["periods"]
        covered = [p for p, v in zip(periods, loans["past_due_30_pct"]) if v is not None]
        five = [p for p, r in zip(periods, loans["readings_per_quarter"]) if r == 5]
        note = next(ex for ex in self.exhibits if ex["title"].startswith("30+ 天逾期率"))["note"]
        self.assertIn(f"覆盖 {covered[0]}–{covered[-1]} 共 {len(covered)} 季", note)
        self.assertIn(f"{five[0]}–{five[-1]} 这 {len(five)} 季各被读到 5 次", note)
        self.assertNotIn("2017Q1–2025Q4 共 36 季", note)

    # ── the annual guidance record ──────────────────────────────────────────
    def test_the_vintage_record_is_aligned_and_ordered(self) -> None:
        record = self.staging["annual_guidance_history"]
        n = len(record["vintages"])
        years = record["fiscal_years"]
        self.assertEqual(years[0], 2016)
        self.assertEqual(sorted(set(years)), list(range(2016, max(years) + 1)))
        for key in ("filed", "vintage_slots", "guide_eps_lo_usd", "guide_revenue_growth_lo_pct",
                    "guide_eps_basis"):
            self.assertEqual(len(record[key]), n, key)
        self.assertEqual(record["filed"], sorted(record["filed"]))
        for label, year, slot in zip(record["vintages"], years, record["vintage_slots"]):
            self.assertEqual(label, f"FY{str(year)[2:]} {slot}")
        # the last vintage is the quarter this page publishes
        self.assertEqual(record["filed"][-1], self.staging["latest"]["release_date"])

    def test_seven_consecutive_releases_carry_no_annual_guidance(self) -> None:
        """Withdrawn in March 2020, then never re-issued until January 2022.

        A later release (2023-10-20) is also blank -- it reaffirms FY2023
        without printing a number -- so the run has to be measured as a run and
        not as a count of blank cells.
        """
        record = self.staging["annual_guidance_history"]
        run = self.facts["longest_blank"]
        self.assertEqual(record["filed"][run[0]], "2020-04-24")
        self.assertEqual(record["filed"][run[-1]], "2021-10-22")
        self.assertEqual(len(run), 7)
        self.assertIn("2023-10-20", [record["filed"][i] for i in self.facts["blank"]])

    def test_the_withdrawal_is_recorded_outside_the_earnings_releases(self) -> None:
        withdrawal = self.staging["annual_guidance_history"]["withdrawal"]
        self.assertEqual(withdrawal["announced"], "2020-03-17")
        self.assertTrue(withdrawal["accession"])
        source = next(s for s in self.staging["sources"] if s["label"].startswith("2020-03-17"))
        self.assertTrue(source["url"].endswith(".htm"))
        self.assertNotIn("-index.htm", source["url"], "the link opens the document, not the filing index")

    def test_only_the_settleable_years_carry_an_actual(self) -> None:
        record = self.staging["annual_guidance_history"]
        for metric, ref in (("eps", "EX_EPS_BAND"), ("revenue", "EX_REV_BAND")):
            band = next(ex for ex in self.exhibits if ex.get("ref") == ref)
            m = self.facts["metrics"][metric]
            filled = {i for i, v in enumerate(band["actual"]) if v is not None}
            self.assertEqual(filled, set(m["settle"].values()), metric)
            for year, index in m["settle"].items():
                self.assertEqual(record["fiscal_years"][index], year)

    def test_the_settled_years_are_the_ones_the_record_allows(self) -> None:
        """EPS settles FY2022-FY2025 and revenue FY2018, FY2019, FY2022-FY2025.

        FY2019 EPS used to be settled too -- against the *adjusted* range
        ($7.85-$8.35, excluding a litigation charge) with the GAAP actual
        ($7.99). The company printed both ranges that year, which is the reason
        this page gives for not settling FY2016; by the page's own rule FY2019
        cannot be settled either.
        """
        eps, rev = self.facts["metrics"]["eps"], self.facts["metrics"]["revenue"]
        settled_eps = {y for y in eps["settle"] if y <= 2025}
        settled_rev = {y for y in rev["settle"] if y <= 2025}
        self.assertEqual(settled_eps, {2022, 2023, 2024, 2025})
        self.assertEqual(settled_rev, {2018, 2019, 2022, 2023, 2024, 2025})
        self.assertEqual(eps["reasons"][2019]["kind"], "two_ranges")
        # the settling vintage is the year's last range or point, never a floor
        record = self.staging["annual_guidance_history"]
        for metric, keys in axp.METRIC_KEYS.items():
            for year, i in self.facts["metrics"][metric]["settle"].items():
                later = [j for j in range(i + 1, len(record["vintages"]))
                         if record["fiscal_years"][j] == year and record[keys[0]][j] is not None]
                self.assertTrue(all(record[keys[2]][j] == "floor" for j in later), (metric, year))

    def test_every_unsettleable_year_states_why(self) -> None:
        years = set(self.facts["years"])
        for metric, m in self.facts["metrics"].items():
            self.assertEqual(set(m["settle"]) | set(m["reasons"]), years, metric)
            self.assertFalse(set(m["settle"]) & set(m["reasons"]), metric)
            for year, reason in m["reasons"].items():
                self.assertIn(reason["kind"], axp.REASON_BRIEF, (metric, year))
                self.assertTrue(reason["ledger"].strip(), f"{metric} {year}")
        # the open year is the one without an actual, and only that one
        self.assertEqual(self.facts["open"], [max(self.facts["years"])])

    def test_eps_never_landed_below_its_range_and_revenue_did_once(self) -> None:
        """The two-sided finding the page is built on, pinned by value for the
        years that had finished when it was written."""
        eps = {y: v for y, v in self.facts["metrics"]["eps"]["verdicts"].items() if y <= 2025}
        revenue = {y: v for y, v in self.facts["metrics"]["revenue"]["verdicts"].items() if y <= 2025}
        self.assertNotIn("below", eps.values())
        self.assertEqual([y for y, v in revenue.items() if v == "below"], [2023])
        self.assertEqual(revenue[2019], "inside_on_bound")
        # FY2018 also printed its floor (9%), but 9.38% was above it before rounding
        self.assertEqual(revenue[2018], "inside")
        self.assertEqual(revenue[2024], "equals_point")
        self.assertEqual(eps[2022], "above")

    def test_the_revenue_actual_is_the_company_s_own_whole_point_figure(self) -> None:
        """Settling a whole-point promise against a two-decimal quotient would
        invent a precision the guidance never had."""
        record = self.staging["annual_guidance_history"]
        band = next(ex for ex in self.exhibits if ex.get("ref") == "EX_REV_BAND")
        for value in band["actual"]:
            if value is not None:
                self.assertEqual(value, round(value), value)
        for year, index in self.facts["metrics"]["revenue"]["settle"].items():
            self.assertEqual(
                band["actual"][index],
                float(record["actual_by_year"][str(year)]["growth_reported_pct"]), year)

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
            entries = axp.kpi_entries(self.staging[block], key, self.staging)
            bar = next(ex for ex in self.exhibits
                       if ex["kind"] == "diverging_bars" and ref in ex["title"])
            self.assertEqual(bar["xlabels"], [e["metric"] for e in entries])
            for entry, value in zip(entries, bar["values"]):
                self.assertAlmostEqual(
                    value, round(headroom(entry["direction"], entry["threshold"],
                                          entry[key]), 1), places=6, msg=entry["metric"])

    def test_no_threshold_block_types_the_value_it_can_read(self) -> None:
        """A current value typed into the block went stale against its own series."""
        for block in ("next_kpi", "settled_kpi"):
            for entry in self.staging[block]["quantified"]:
                if "reads" in entry:
                    self.assertNotIn("current", entry, entry["metric"])
                    self.assertNotIn("actual", entry, entry["metric"])
                else:
                    self.assertTrue(entry.get("source"), f"{entry['metric']} is typed without a source")

    def test_the_thresholds_the_page_declines_are_named(self) -> None:
        excluded = "".join(self.staging["next_kpi"]["excluded"])
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
                self.assertNotRegex(exhibit.get(field) or "", r"\{[A-Za-z_:]+\}")
                self.assertNotRegex(exhibit.get(field) or "", r"(?<![A-Za-z{])EX_[A-Z]")

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

    def test_the_page_prints_no_markdown(self) -> None:
        """`**` survives neither slot: notes are escaped, exhibit notes are HTML."""
        self.assertNotIn("**", own_text(self.payload))

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
        eps = self.facts["metrics"]["eps"]
        note = next(n for n in self.payload["notes"] if "可以被诚实结清" in n)
        for year in eps["reasons"]:
            self.assertIn(f"FY{year}", note, year)
        # A settled year must not be listed among the reasons it could not be.
        marker = f"EPS 不能结清的{cn_count(len(eps['reasons']))}年各有原因："
        self.assertIn(marker, note)
        reasons = note.split(marker, 1)[1].split("另有一年", 1)[0]
        for year in eps["settle"]:
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
            digest = hashlib.sha256((ROOT / match.group(1)).read_bytes()).hexdigest()[:8]
            self.assertEqual(match.group(2), digest, match.group(1))


# ── rolling the series, the way a quarter's roll does ────────────────────────
QUARTER_END = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}
RELEASE_DAY = {1: "04-22", 2: "07-23", 3: "10-22", 4: "01-29"}
CN_QUARTER = {1: "一", 2: "二", 3: "三", 4: "四"}
QUARTER_BLOCKS = ("settled_kpi", "next_kpi", "quarter_story")
PLACEHOLDER = r"\{[a-z_:]+\}"


def quarterly_lists(s: dict) -> list[tuple[dict, str]]:
    """(container, key) for every list that runs along a quarterly axis."""
    n = len(s["periods"])
    out = [(s, "periods"), (s, "period_ends"), (s, "period_labels")]
    for block in (s["financials"], s["operating_metrics"], s["credit_metrics"],
                  s["credit_metrics"]["loans_basis"]):
        for key, values in block.items():
            if isinstance(values, list) and len(values) == n:
                out.append((block, key))
    m = len(s["segment_periods"])
    out += [(s, "segment_periods"), (s, "segment_period_labels")]
    for seg in s["segments_usd_m"].values():
        for key, values in seg.items():
            if isinstance(values, list) and len(values) == m:
                out.append((seg, key))
    return out


def vintage_keys(g: dict) -> list[str]:
    n = len(g["vintages"])
    return [key for key, values in g.items() if isinstance(values, list) and len(values) == n]


def rolled_back(staging: dict) -> dict:
    """The series one quarter earlier, on the Q1 2026 figures the file already
    holds. The Q1 page's own thresholds are the three the 2026-04-24 note set,
    with the ICS figure as the Q1 release printed it."""
    s = copy.deepcopy(staging)
    for container, key in quarterly_lists(s):
        container[key] = container[key][:-1]
    g = s["annual_guidance_history"]
    for key in vintage_keys(g):
        g[key] = g[key][:-1]
    for key in ("_checks",) + QUARTER_BLOCKS:
        s.pop(key, None)
    label = s["period_labels"][-1]
    s["latest"] = {"period": label, "release_date": g["filed"][-1],
                   "analysis_date": "2026-04-25", "audit_status": "unaudited"}
    s["next_kpi"] = {
        "period": label,
        "quantified": [
            {"metric": "ICS 消费同比（报告口径）", "direction": "up", "threshold": 15.0, "unit": "pct",
             "current": 20.0, "source": "Q1 2026 EX-99.2 Network Volumes Related Growth"},
            {"metric": "拨备同比", "direction": "down", "threshold": 5.0, "unit": "pct",
             "reads": "yoy:financials.provisions_usd_m"},
            {"metric": "净核销率（本金口径）", "direction": "down", "threshold": 2.1, "unit": "pct",
             "reads": "credit_metrics.net_write_off_rate_principal_pct"},
        ],
    }
    folder = "https://www.sec.gov/Archives/edgar/data/4962/000000496226000188/"
    s["sources"] = ([{"label": "American Express 2026 年第一季度业绩新闻稿（8-K EX-99.1）",
                      "url": folder + "q126exhibit991.htm"},
                     {"label": "同一份 8-K 的统计表（EX-99.2，本页全部季度序列的来源）",
                      "url": folder + "q126exhibit992.htm"}]
                    + [src for src in s["sources"]
                       if "业绩新闻稿" not in src["label"] and "EX-99.2" not in src["label"]
                       and "10-Q" not in src["label"]])
    return s


def rolled_forward(staging: dict, revenue_growth: int | None = None) -> dict:
    """One quarter later with made-up figures. A fourth quarter's release
    settles the open year and opens the next."""
    s = copy.deepcopy(staging)
    last = s["periods"][-1]
    year, quarter = int(last[:4]), int(last[5])
    year, quarter = (year + 1, 1) if quarter == 4 else (year, quarter + 1)
    period, label = f"{year}Q{quarter}", f"Q{quarter} {year}"
    release = f"{year + 1 if quarter == 4 else year}-{RELEASE_DAY[quarter]}"
    for container, key in quarterly_lists(s):
        values = container[key]
        if key in ("periods", "segment_periods"):
            values.append(period)
        elif key in ("period_labels", "segment_period_labels"):
            values.append(label)
        elif key == "period_ends":
            values.append(f"{year}-{QUARTER_END[quarter]}")
        elif key == "readings_per_quarter":
            values.append(0)
        else:
            values.append(None if values[-1] is None else round(values[-1] * 1.02, 4))
    fin = s["financials"]
    fin["total_expenses_usd_m"][-1] = round(fin["revenue_usd_m"][-1] * 0.74, 4)
    fin["ppop_usd_m"][-1] = fin["revenue_usd_m"][-1] - fin["total_expenses_usd_m"][-1]
    fin["pretax_income_usd_m"][-1] = fin["ppop_usd_m"][-1] - fin["provisions_usd_m"][-1]
    g = s["annual_guidance_history"]
    keys = vintage_keys(g)
    open_year = max(g["fiscal_years"])

    def add_vintage(fiscal_year: int, slot: str) -> None:
        for key in keys:
            value = {"vintages": f"FY{str(fiscal_year)[2:]} {slot}", "fiscal_years": fiscal_year,
                     "vintage_slots": slot, "filed": release}.get(key, g[key][-1])
            g[key].append(value)
        if g["guide_revenue_form"][-1] == "point":
            g["point_quotes"][g["vintages"][-1]] = "about 10 percent"

    if quarter == 4:
        prior = g["actual_by_year"][str(open_year - 1)]["revenue_usd_m"]
        revenue = sum(fin["revenue_usd_m"][-4:])
        exact = (revenue / prior - 1) * 100
        g["actual_by_year"][str(open_year)] = {
            "revenue_usd_m": revenue, "eps": round(sum(fin["diluted_eps_usd"][-4:]), 2),
            "growth_reported_pct": round(exact) if revenue_growth is None else revenue_growth,
            "growth_fx_pct": round(exact), "growth_exact_pct": round(exact, 4)}
        add_vintage(open_year + 1, "初")
        g["guide_revenue_growth_lo_pct"][-1], g["guide_revenue_growth_hi_pct"][-1] = 8.0, 10.0
        g["guide_revenue_form"][-1] = "range"
        g["guide_eps_lo_usd"][-1], g["guide_eps_hi_usd"][-1] = 19.5, 20.1
        g["guide_eps_basis"][-1] = None
    else:
        add_vintage(open_year, f"Q{quarter}")
    for key in ("_checks",) + QUARTER_BLOCKS:
        s.pop(key, None)
    s["latest"] = {"period": label, "release_date": release,
                   "analysis_date": release, "audit_status": "unaudited"}
    folder = f"https://www.sec.gov/Archives/edgar/data/4962/next{period}/"
    s["sources"] = ([{"label": f"American Express {year} 年第{CN_QUARTER[quarter]}季度业绩新闻稿（8-K EX-99.1）",
                      "url": folder + "exhibit991.htm"}]
                    + [src for src in s["sources"]
                       if "业绩新闻稿" not in src["label"] and "EX-99.2" not in src["label"]
                       and "10-Q" not in src["label"]])
    return s


class AxpChecksTest(unittest.TestCase):
    """The page's quarter against a record keyed separately from the release.

    `_checks` is typed once per quarter from the earnings 8-K itself, with the
    place in the document each figure was read from; the builder never reads it
    (asserted in `test_data_only_roll`). The release prints growth as whole
    percentages, so computed growth is compared at that precision.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(axp.STAGING_PATH.read_text(encoding="utf-8"))
        cls.checks = cls.staging["_checks"]
        cls.payload = axp.build_payload(cls.staging)
        cls.exhibits = exhibits_of(cls.payload)

    def test_the_page_names_the_checked_quarter(self) -> None:
        self.assertIn(f"{self.checks['period']} 季报仪表盘", self.payload["title"])
        self.assertIn(f"截至 {self.checks['period_end']}", self.payload["subtitle"])
        self.assertIn(f"发布 {self.checks['release_date']}", self.payload["subtitle"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        fin, om, c = self.staging["financials"], self.staging["operating_metrics"], self.checks
        for key, check in (("revenue_usd_m", "revenue_usd_m"),
                           ("discount_revenue_usd_m", "discount_revenue_usd_m"),
                           ("net_card_fees_usd_m", "net_card_fees_usd_m"),
                           ("net_interest_income_usd_m", "net_interest_income_usd_m"),
                           ("provisions_usd_m", "total_provisions_usd_m"),
                           ("total_expenses_usd_m", "total_expenses_usd_m"),
                           ("pretax_income_usd_m", "pretax_income_usd_m"),
                           ("net_income_usd_m", "net_income_usd_m"),
                           ("diluted_eps_usd", "diluted_eps_usd"),
                           ("diluted_shares_m", "diluted_shares_m")):
            with self.subTest(key=key):
                self.assertEqual(fin[key][-1], c[check])
        for key, check in (("rewards_usd_m", "rewards"), ("business_development_usd_m", "business_development"),
                           ("card_member_services_usd_m", "card_member_services")):
            self.assertEqual(fin[key][-1], c["vce_usd_m"][check], key)
        for key, check in (("billed_business_usd_bn", "billed_business_usd_bn"),
                           ("average_fee_per_card_usd", "average_fee_per_card_usd"),
                           ("proprietary_cards_in_force_m", "proprietary_cards_in_force_m"),
                           ("cet1_ratio_pct", "cet1_ratio_pct")):
            self.assertEqual(om[key][-1], c[check], key)
        credit = self.staging["credit_metrics"]
        self.assertEqual(credit["net_write_off_rate_principal_pct"][-1], c["net_write_off_rate_principal_pct"])
        self.assertEqual(credit["past_due_30_pct"][-1], c["past_due_30_pct"])

    def test_computed_growth_rounds_to_the_printed_growth(self) -> None:
        fin, c = self.staging["financials"], self.checks
        billed = self.staging["operating_metrics"]["billed_business_usd_bn"]
        for values, printed in ((fin["revenue_usd_m"], c["revenue_growth_printed_pct"]),
                                (fin["pretax_income_usd_m"], c["pretax_growth_printed_pct"]),
                                (fin["diluted_eps_usd"], c["diluted_eps_growth_printed_pct"]),
                                (billed, c["billed_business_growth_printed_pct"]["reported"])):
            self.assertEqual(round((values[-1] / values[-5] - 1) * 100), printed)

    def test_the_open_year_ends_on_the_checked_guidance(self) -> None:
        g, c = self.staging["annual_guidance_history"], self.checks["guidance"]
        self.assertEqual(g["fiscal_years"][-1], c["fiscal_year"])
        self.assertEqual(g["guide_revenue_growth_lo_pct"][-1], c["revenue_growth_pct"])
        self.assertEqual(g["guide_revenue_growth_hi_pct"][-1], c["revenue_growth_pct"])
        self.assertEqual(g["guide_revenue_form"][-1], "point")
        self.assertEqual([g["guide_eps_lo_usd"][-1], g["guide_eps_hi_usd"][-1]], c["eps_usd"])
        self.assertEqual(g["point_quotes"][g["vintages"][-1]], f"{c['revenue_growth_pct']} percent")

    def test_the_page_prints_the_checked_figures(self) -> None:
        c = self.checks
        self.assertIn(f"收入 US${c['revenue_usd_m']:,.0f}M", self.payload["headline"])
        self.assertIn(f"摊薄 EPS ${c['diluted_eps_usd']:.2f}", self.payload["headline"])
        price = next(ex for ex in self.exhibits if ex.get("ref") == "EX_PRICE")
        self.assertIn(f"卡费 US${c['net_card_fees_usd_m']:,.0f}M", price["title"])
        self.assertIn(f"每卡年费 US${c['average_fee_per_card_usd']:.0f}", price["title"])
        cet1 = next(ex for ex in self.exhibits if ex["title"].startswith("CET1 比率"))
        self.assertIn(f"当前 {c['cet1_ratio_pct']:.2f}%", cet1["title"])

    def test_the_threshold_readings_match_the_release(self) -> None:
        """Each current value, recomputed from `_checks` alone and compared at the
        precision the audit table prints -- not through the builder's own reader,
        which would only be checking itself."""
        c, prior = self.checks, self.checks["prior_year"]
        vce = sum(c["vce_usd_m"].values())
        growth = lambda now, then: (now / then - 1) * 100  # noqa: E731
        expected = {
            "净卡费（季度额）": f"${c['net_card_fees_usd_m']:,.0f}M",
            "消费额同比（报告口径）": f"{growth(c['billed_business_usd_bn'], prior['billed_business_usd_bn']):.1f}%",
            "30+ 天逾期率": f"{c['past_due_30_pct']:.1f}%",
            "净核销率（本金口径）": f"{c['net_write_off_rate_principal_pct']:.1f}%",
            "VCE 占收入比": f"{vce / c['revenue_usd_m'] * 100:.1f}%",
            "jaws（收入增速 − 费用增速）": f"{growth(c['revenue_usd_m'], prior['revenue_usd_m']) - growth(c['total_expenses_usd_m'], prior['total_expenses_usd_m']):+.1f}pp",
            "CET1 比率": f"{c['cet1_ratio_pct']:.1f}%",
        }
        table = next(t for t in self.payload["tables"] if t["title"].startswith("下季阈值与当前值"))
        self.assertEqual({row[0]: row[3] for row in table["rows"]}, expected)
        settled = next(t for t in self.payload["tables"] if t["title"].startswith("上季阈值与本季实际值"))
        rows = {row[0]: row[3] for row in settled["rows"]}
        self.assertEqual(rows["拨备同比"],
                         f"{growth(c['total_provisions_usd_m'], prior['total_provisions_usd_m']):.1f}%")
        self.assertEqual(rows["净核销率（本金口径）"], f"{c['net_write_off_rate_principal_pct']:.1f}%")

    def test_the_prior_year_quarter_is_the_series_one(self) -> None:
        fin, prior = self.staging["financials"], self.checks["prior_year"]
        self.assertEqual(self.staging["period_labels"][-5], prior["period"])
        for key, check in (("revenue_usd_m", "revenue_usd_m"), ("total_expenses_usd_m", "total_expenses_usd_m"),
                           ("provisions_usd_m", "total_provisions_usd_m"),
                           ("pretax_income_usd_m", "pretax_income_usd_m"),
                           ("diluted_eps_usd", "diluted_eps_usd"), ("net_card_fees_usd_m", "net_card_fees_usd_m")):
            self.assertEqual(fin[key][-5], prior[check], key)
        self.assertEqual(self.staging["operating_metrics"]["billed_business_usd_bn"][-5],
                         prior["billed_business_usd_bn"])

    def test_the_settled_ics_reading_is_the_printed_one(self) -> None:
        block = self.staging["settled_kpi"]
        ics = next(e for e in block["quantified"] if e["metric"].startswith("ICS"))
        printed = self.checks["ics_billed_business_growth_printed_pct"]
        self.assertEqual(ics["actual"], printed["reported"][1])
        figures = block["figures"]
        self.assertEqual([figures["ics_reported_prior"], figures["ics_reported"]], printed["reported"])
        self.assertEqual([figures["ics_fx_prior"], figures["ics_fx"]], printed["fx_adjusted"])
        self.assertEqual(self.staging["next_kpi"]["figures"]["fx_adjusted_billed_growth_pct"],
                         self.checks["billed_business_growth_printed_pct"]["fx_adjusted"])


class AxpRollTest(unittest.TestCase):
    """What a roll can change without touching the builder."""

    STORY_ONLY = ("预计将面临执法行动", "因为口径错了才触发", "上季那份分析一共立了")

    @classmethod
    def setUpClass(cls) -> None:
        cls.s = json.loads(axp.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = axp.build_payload(cls.s)
        cls.text = own_text(cls.payload)

    def test_a_block_stamped_for_another_quarter_stops_the_build(self) -> None:
        for key in QUARTER_BLOCKS:
            stale = copy.deepcopy(self.s)
            stale[key]["period"] = "Q1 1999"
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    axp.build_payload(stale)

    def test_the_quarters_own_release_must_be_in_the_sources(self) -> None:
        bare = copy.deepcopy(self.s)
        bare["sources"] = [src for src in bare["sources"] if "第二季度业绩新闻稿" not in src["label"]]
        self.assertLess(len(bare["sources"]), len(self.s["sources"]))
        with self.assertRaisesRegex(ValueError, "sources"):
            axp.build_payload(bare)

    def test_a_quarter_without_its_blocks_leaves_them_out(self) -> None:
        bare = copy.deepcopy(self.s)
        for key in QUARTER_BLOCKS:
            del bare[key]
        payload = axp.build_payload(bare)
        text = own_text(payload)
        for phrase in self.STORY_ONLY:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)
                self.assertNotIn(phrase, text)
        sections = {section["id"]: section for section in payload["sections"]}
        self.assertEqual(sections["next_quarter"]["exhibits"], [])
        self.assertIn("本节没有图", sections["next_quarter"]["description"])
        self.assertFalse(any(ex["kind"] == "diverging_bars"
                             for ex in sections["settled"]["exhibits"]))
        self.assertNotIn("两样东西", sections["settled"]["description"])
        numbers = [ex["n"] for ex in exhibits_of(payload)]
        self.assertEqual(numbers, list(range(2, 2 + len(numbers))))
        self.assertNotRegex(text, PLACEHOLDER)
        self.assertNotRegex(text, r"\{EX_[A-Z_]+\}")

    def test_a_point_vintage_without_the_companys_words_stops_the_build(self) -> None:
        bare = copy.deepcopy(self.s)
        bare["annual_guidance_history"]["point_quotes"].pop(bare["annual_guidance_history"]["vintages"][-1])
        with self.assertRaisesRegex(ValueError, "point revenue vintages"):
            axp.build_payload(bare)

    def test_the_quarter_before_builds_from_the_series_alone(self) -> None:
        rolled = rolled_back(self.s)
        payload = axp.build_payload(rolled)
        label = rolled["period_labels"][-1]
        self.assertEqual(payload["latest"]["disclosed_period_label"], label)
        self.assertIn(f"{label} 季报仪表盘", payload["title"])
        text = own_text(payload)
        for token in (self.s["period_labels"][-1], self.s["periods"][-1],
                      self.s["latest"]["release_date"], "第二季度", "反洗钱"):
            self.assertNotIn(token, text)
        self.assertNotRegex(text, PLACEHOLDER)
        self.assertNotRegex(text, r"\{EX_[A-Z_]+\}")
        # Q1 2026: the provision leg was negative, so the headline has no "但"
        self.assertNotIn("；但税前利润", payload["headline"])
        self.assertIn("税前增量全部来自经营", payload["brief"])
        self.assertIn("拨备腿 −US$101M", payload["brief"])
        self.assertIn("本季 jaws 为正", own_text(payload))

    def test_the_quarters_after_build_from_the_series_alone(self) -> None:
        s = self.s
        for _ in range(2):
            s = rolled_forward(s, revenue_growth=9)
            payload = axp.build_payload(s)
            text = own_text(payload)
            self.assertIn(f"{s['period_labels'][-1]} 季报仪表盘", payload["title"])
            self.assertNotRegex(text, PLACEHOLDER)
            self.assertNotRegex(text, r"\{EX_[A-Z_]+\}")
        # the fourth quarter settles FY2026 against its last point (10%) and opens FY2027
        facts = axp.record_facts(s)
        self.assertIn(2026, facts["metrics"]["revenue"]["settle"])
        self.assertEqual(facts["metrics"]["revenue"]["verdicts"][2026], "below")
        self.assertEqual(facts["open"], [2027])
        self.assertIn("FY2027 还没结束", text)
        self.assertNotIn("唯一一次真正跌破下限", text)
        self.assertIn("真正跌破下限（或低于单点）的有两年", text)
        self.assertIn("FY2026 修订也没能把它救回来", text)


class AxpFindingsTest(unittest.TestCase):
    """Every judgement on the page says what the series says, both ways.

    Each case forces the series into a state where a finding is true, then into
    one where it is false, and checks that the words follow. Forcing rather than
    flipping today's data keeps these valid after a roll.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.s = json.loads(axp.STAGING_PATH.read_text(encoding="utf-8"))

    def page(self, *edits) -> str:
        staged = copy.deepcopy(self.s)
        for edit in edits:
            edit(staged)
        return own_text(axp.build_payload(staged))

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        """Make one settled EPS year miss its range: every sentence that says
        EPS never broke its floor must stop saying it."""
        def eps_miss(s):
            s["annual_guidance_history"]["actual_by_year"]["2023"]["eps"] = 10.9

        clean = self.page()
        claims = ("能结清的部分是两面的", "四年里一次都没有跌破下限", "也是唯一一条被跌破过的",
                  "EPS 0 次跌破下限")
        missed = self.page(eps_miss)
        for claim in claims:
            with self.subTest(claim=claim):
                self.assertIn(claim, clean)
                self.assertNotIn(claim, missed)

    def test_the_only_revenue_miss_is_counted(self) -> None:
        def second_miss(s):
            s["annual_guidance_history"]["actual_by_year"]["2024"]["growth_reported_pct"] = 8

        clean, missed = self.page(), self.page(second_miss)
        for claim in ("唯一一次真正跌破下限是 FY2023", "FY2023 是窗口内唯一一次收入增速真正跌破下限"):
            self.assertIn(claim, clean)
            self.assertNotIn(claim, missed)
        self.assertIn("真正跌破下限（或低于单点）的有两年", missed)

    def test_the_mix_note_names_every_leg_that_outgrew_revenue(self) -> None:
        """「卡费是唯一一条跑赢总收入的腿」 printed beside NII at 2.94x against 2.20x."""
        def slow_nii(s):
            fin = s["financials"]
            nii, discount = fin["net_interest_income_usd_m"], fin["discount_revenue_usd_m"]
            target = nii[0] * 2.0
            discount[-1] += nii[-1] - target
            nii[-1] = target

        clean, slowed = self.page(), self.page(slow_nii)
        self.assertIn("跑赢总收入的是净卡费与净利息收入", clean)
        self.assertNotIn("卡费是唯一一条跑赢总收入的腿", clean)
        self.assertIn("卡费是唯一一条跑赢总收入的腿", slowed)

    def test_the_jaws_note_reads_its_runs_and_its_streak(self) -> None:
        """「自 2024 年第三季度起转负并停在负区间」 stood beside three positive quarters."""
        def negative_run(s):
            fin = s["financials"]
            for back in (2, 3):
                fin["total_expenses_usd_m"][-back] = fin["total_expenses_usd_m"][-back - 4] * 1.3
                fin["ppop_usd_m"][-back] = fin["revenue_usd_m"][-back] - fin["total_expenses_usd_m"][-back]

        clean, run = self.page(), self.page(negative_run)
        self.assertIn("本季转负", clean)
        self.assertIn("出现过两次：2017Q3–2018Q3", clean)
        self.assertNotIn("停在负区间", clean)
        self.assertIn("已连续 3 季为负", run)
        self.assertNotIn("本季转负", run)

    def test_the_vce_tail_is_measured_against_the_whole_line(self) -> None:
        """「是三个季度以来的高位」 described the lowest of the last three quarters."""
        def earlier_peak(s):
            fin = s["financials"]
            i = s["periods"].index("2023Q1")
            fin["rewards_usd_m"][i] += 2000

        clean, peaked = self.page(), self.page(earlier_peak)
        self.assertIn("这三季是这条线上最高的三格", clean)
        self.assertNotIn("三个季度以来的高位", clean)
        self.assertNotIn("这三季是这条线上最高的三格", peaked)

    def test_the_vce_is_the_source_only_when_the_data_says_so(self) -> None:
        def everything_else_faster(s):
            fin = s["financials"]
            fin["salaries_usd_m"][-1] += 1500
            fin["total_expenses_usd_m"][-1] += 1500
            fin["ppop_usd_m"][-1] -= 1500
            fin["pretax_income_usd_m"][-1] -= 1500

        clean, other = self.page(), self.page(everything_else_faster)
        self.assertIn("这条线是本季负 jaws 的来源", clean)
        self.assertIn("本季负 jaws 不只来自这条线", other)

    def test_the_segment_title_counts_the_quarters_above_half(self) -> None:
        """「GMNS 长期在 50% 以上，其余三个在 20% 上下」: 11 of 26, and ICS ~10%."""
        clean = self.page()
        seg = self.s["segments_usd_m"]["GMNS"]
        above = sum(1 for p, r in zip(seg["pretax_usd_m"], seg["revenue_usd_m"]) if p / r > 0.5)
        self.assertIn(f"{len(seg['revenue_usd_m'])} 季里 {above} 季在 50% 以上", clean)
        self.assertNotIn("GMNS 长期在 50% 以上", clean)

        def rich(s):
            block = s["segments_usd_m"]["GMNS"]
            block["pretax_usd_m"] = [r * 0.6 for r in block["revenue_usd_m"]]

        n = len(seg["revenue_usd_m"])
        self.assertIn(f"{n} 季里 {n} 季在 50% 以上", self.page(rich))

    def test_the_revision_note_names_the_years_below_both_vintages(self) -> None:
        """It said FY2023 and FY2024; FY2024 lands on its final point (0pp) and
        FY2019 is the other year below both -- and neither year was revised."""
        clean = self.page()
        self.assertIn("反过来，FY2019 与 FY2023 两年<b>对两档都是负的</b>：这两年全年都没有修订过区间", clean)

        def fy2024_misses(s):
            s["annual_guidance_history"]["actual_by_year"]["2024"]["growth_reported_pct"] = 8

        missed = self.page(fy2024_misses)
        self.assertIn("FY2019、FY2023 与 FY2024 三年", missed)
        self.assertIn("FY2024 修订也没能把它救回来", missed)
        self.assertIn("FY2018 年初那一档没有收入指引，这一年左边那根柱子对的是 4 月那一档（只有下限 8%）", clean)

    def test_the_eps_record_does_not_settle_an_adjusted_range_against_gaap(self) -> None:
        payload = axp.build_payload(copy.deepcopy(self.s))
        band = next(ex for ex in exhibits_of(payload) if ex.get("ref") == "EX_EPS_BAND")
        g = self.s["annual_guidance_history"]
        for i, label in enumerate(g["vintages"]):
            if g["fiscal_years"][i] == 2019:
                self.assertIsNone(band["actual"][i], label)
        ledger = payload["tables"][0]
        row = next(r for r in ledger["rows"] if r[0] == "FY2019")
        self.assertEqual(row[6], "无法判定")
        self.assertIn("FY2016、FY2019 同一年印了 GAAP 与调整后两条区间", band["note"])

        def settle_2019(s):
            del s["annual_guidance_history"]["unsettleable"]["eps"]["2019"]

        restored = self.page(settle_2019)
        self.assertIn("五年里四年在中值之上、一年（FY2019）在中值之下但仍落在区间内", restored)

    def test_the_credit_line_count_follows_the_thresholds(self) -> None:
        """「第三节的三条信用阈值」 counted CET1 as credit."""
        def one_credit(s):
            s["next_kpi"]["quantified"] = [e for e in s["next_kpi"]["quantified"]
                                           if e.get("reads") != "credit_metrics.past_due_30_pct"]

        self.assertIn("第三节的两条信用阈值才分得出来", self.page())
        self.assertIn("第三节的一条信用阈值才分得出来", self.page(one_credit))

    def test_the_headline_says_but_only_when_the_provision_leg_leads(self) -> None:
        def operating_leads(s):
            fin = s["financials"]
            fin["provisions_usd_m"][-1] = fin["provisions_usd_m"][-5] - 50
            fin["pretax_income_usd_m"][-1] = fin["ppop_usd_m"][-1] - fin["provisions_usd_m"][-1]

        self.assertIn("；但税前利润", self.page())
        self.assertNotIn("；但税前利润", self.page(operating_leads))

    def test_the_price_note_multiplies_over_one_span(self) -> None:
        """3.27 x 1.44 = 4.73 was set beside 4.09 as 「约等于」: two spans in one sentence."""
        clean = self.page()
        self.assertNotIn("两个倍数相乘约等于卡费那个倍数", clean)
        self.assertIn("同从 Q3 2016 算起", clean)
        self.assertNotIn("翻了近三倍", clean)

        def skewed(s):
            s["operating_metrics"]["average_fee_per_card_usd"][-1] *= 1.3

        self.assertNotIn("约等于同期卡费", self.page(skewed))

    def test_the_share_words_follow_the_shares(self) -> None:
        clean = self.page()
        self.assertIn("从占收入六成以上降到略高于一半", clean)

        def below_half(s):
            fin = s["financials"]
            fin["discount_revenue_usd_m"][-1] -= 800
            fin["other_non_interest_revenue_usd_m"][-1] += 800

        self.assertNotIn("略高于一半", self.page(below_half))

    def test_stale_window_claims_are_gone(self) -> None:
        """Written when the income statement started at 2017Q1."""
        payload = axp.build_payload(copy.deepcopy(self.s))
        for exhibit in exhibits_of(payload):
            exhibit.pop("ref", None)
        clean = own_text(payload)
        for stale in ("本页大多数图只能回到 2017Q1", "比本页收入侧的长序列早四季", "本页最长",
                      "而同一份文件里的收入、折扣收入、奖励成本都不能", "2017Q1–2021Q3 的空缺",
                      "本站其余 2016 数据都是两条路径", "以及资本比率", "其余三张",
                      "欧洲增值税诉讼", "公司从不发布季度指引", "见上一张图的说明", "EX_RATE"):
            self.assertNotIn(stale, clean)

    def test_the_quarterly_guidance_exceptions_are_named(self) -> None:
        notes = axp.build_payload(copy.deepcopy(self.s))["notes"]
        note = next(n for n in notes if n.startswith("第一节结清的是年度指引"))
        self.assertIn("2019-10-18", note)
        self.assertIn("2020-03-17", note)
        self.assertIn("至少", note)

    def test_the_settled_block_counts_its_own_items(self) -> None:
        """「只结清得了其中三条，另外两条……第三条」 added up to six of five."""
        clean = self.page()
        self.assertIn("上季那份分析一共立了五条阈值，本页结清了其中两条（拆成三根阈值线）", clean)

        def one_line_each(s):
            q = s["settled_kpi"]["quantified"]
            q[2]["note_item"] = 6

        self.assertIn("一共立了六条阈值，本页结清了其中三条", self.page(one_line_each))

    def test_the_timing_warning_is_read_from_the_filing_dates(self) -> None:
        clean = self.page()
        self.assertIn("分别随该年 1 月、4 月、7 月、10 月的业绩发布出去", clean)
        self.assertIn("年初那一档发布时全年还剩十一个多月", clean)

        def late_opening(s):
            g = s["annual_guidance_history"]
            for i, slot in enumerate(g["vintage_slots"]):
                if slot == "初":
                    g["filed"][i] = g["filed"][i][:5] + "02-20"

        self.assertIn("全年还剩十个多月", self.page(late_opening))


if __name__ == "__main__":
    unittest.main()
