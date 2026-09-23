"""CME page: the reconciliations that license what the page publishes.

Three of this page's objects are derived rather than read, and each one is a
place where a plausible-looking series could be wrong without anything else
noticing. All three are pinned here against an identity rather than against a
remembered number.

**The futures-and-options fee line.** CME publishes average daily volume and an
average rate per contract that cover futures and options only, while the income
statement's clearing-and-transaction-fees line also carries BrokerTec's cash
Treasuries and EBS's FX. The page multiplies ADV by trading days by RPC and
plots the remainder separately. What licenses that split is not that the numbers
look sensible: it is that the remainder sits under US$25M in all twenty-three
quarters before NEX closed and over US$85M in every quarter after, i.e. the step
lands exactly on the acquisition that added those businesses. That is asserted
below, and so is the tighter identity underneath it -- the six per-class rates,
weighted by the six per-class volumes, reproduce the published average RPC.

**The capital-expenditure record.** Seventeen years of guidance parsed out of
seventeen 10-K sentences, matched against seventeen cash-flow lines. Two things
can silently go wrong: a range year read as a point (three of the seventeen are
ranges) and a year's actual taken from the wrong column of a three-year
comparative. Both are pinned -- the forms are asserted per year, and the tallies
the page prints in its own headline are recomputed from the data.

**The retained collateral spread.** Two prose figures per quarter out of the
10-Q, divided by a balance-sheet line. The trap the memory of this repo warns
about is live here: the same sentence carries the quarter and then either a
year-to-date, a prior-year quarter or a prior full year depending on which of
four shapes it takes. The check that catches a swap is that the retained spread
lands in a narrow band while the gross yield on the same balance moves by a
factor of two and a half -- a mis-paired numerator would not do that.

**Rolling a quarter edits `series/cme.json` and nothing else, including this
file.** The windows are asserted by where they start (2013Q1, 2016Q1, 2024Q3
for the adjusted table) and that they run without a gap to the checked quarter;
the quarter's own figures are held to `_checks` (`CmeChecksTest`); and every
sentence that states a first, a record, an "all six" or a ranking is recounted
or made false on purpose (`CmeRollTest`).
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

from build import cme  # noqa: E402
from build.all import ENTRIES, GROUPS, build_all, roster_payload  # noqa: E402
from build.board import cn_count, cn_ordinal, headroom  # noqa: E402

CLASS_KEYS = ("rates", "equity", "fx", "energy", "ags", "metals")


def period_key(label: str) -> str:
    """``'Q2 2026'`` -> ``'2026Q2'``, the form the `long` block uses."""
    quarter, year = label.split()
    return f"{year}{quarter}"


def quarters_from(first: str, last: str) -> list[str]:
    year, quarter = int(first[:4]), int(first[-1])
    out = [first]
    while out[-1] != last:
        quarter += 1
        if quarter == 5:
            year, quarter = year + 1, 1
        out.append(f"{year}Q{quarter}")
        if year > 2100:
            raise ValueError(f"{last} does not follow {first}")
    return out


def published_text(payload: dict) -> str:
    return json.dumps({key: payload[key] for key in
                       ("title", "subtitle", "headline", "brief", "sections", "notes", "tables")},
                      ensure_ascii=False)


def js_payload(path: Path, marker: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{marker} = ", 1)[1].rstrip().rstrip(";")
    return json.loads(body)


class CmeDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(cme.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = cme.build_payload(cls.staging)

    # ── the four sections ───────────────────────────────────────────────────
    def test_the_page_has_the_site_s_four_sections_in_order(self) -> None:
        self.assertEqual(
            [(section["id"], section["title"]) for section in self.payload["sections"]],
            [("settled", "一、上季跟踪指标兑现了吗"), ("quarter_highlights", "二、本季重点"),
             ("next_quarter", "三、下季要跟踪什么"), ("routine", "四、长期常规跟踪")])
        self.assertTrue(all(section["exhibits"] for section in self.payload["sections"]))
        self.assertIn("本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列",
                      self.payload["notes"][0])

    def test_the_first_analysis_settles_only_the_company_s_guidance_and_says_so(self) -> None:
        """The local analysis of Q2 2026 is the first one on CME.

        Its section 0 reads "未找到上季遗留问题" and its section 8 "首次覆盖，无上季
        KPI 可校准", so there is no follow-up list and no threshold to settle:
        section one carries the capital-expenditure record alone and has to say
        why, rather than look like a section that forgot its first half.
        """
        # What the report says about itself lives in `_checks["note"]`, keyed
        # from the report; the series' own record has to agree with it.
        note = self.staging["_checks"]["note"]
        period = self.staging["period_labels"][-1]
        first = note["source"]["previous_quarter"] is None
        self.assertEqual(first, self.staging["analysis_record"]["first_period"] == period)
        self.assertTrue(first, "this quarter's analysis has a previous one: section one must settle it")
        self.assertEqual(note["followup_closure"]["total"], 0)
        self.assertEqual(note["prior_thresholds"], [])
        settled = next(s for s in self.payload["sections"] if s["id"] == "settled")
        self.assertTrue(settled["description"].startswith(
            f"本站对该公司的第一份季报分析是 {period}，没有上季留下的跟踪指标可结算；"))
        self.assertEqual([ex["ref"] for ex in settled["exhibits"]], ["EX_CAPEX", "EX_CAPEX_DEV"])
        for key in ("followup_closure", "prior_kpi_settlement"):
            self.assertNotIn(key, self.staging)

    def test_each_section_carries_the_charts_that_belong_to_it(self) -> None:
        """Section two is the local analysis's conclusions about this quarter;
        section four is the long record.

        The collateral chart is that analysis's third insight -- a claim about
        this quarter (what CME keeps rose while gross investment income fell)
        -- and it used to sit among the ten-year series.
        """
        refs = {section["id"]: [ex["ref"] for ex in section["exhibits"]]
                for section in self.payload["sections"]}
        self.assertEqual(refs["quarter_highlights"],
                         ["EX_MIX", "EX_BRIDGE", "EX_CLASS_RPC", "EX_MARGIN", "EX_OPEX",
                          "EX_MKTDATA", "EX_EPS", "EX_SPREAD"])
        self.assertEqual(refs["routine"],
                         ["EX_ADV_LONG", "EX_BETA", "EX_RESIDUAL", "EX_INVEST",
                          "EX_MKTDATA_LONG", "EX_CLASS_ADV", "EX_TAX"])

    def test_the_quarter_charts_lead_with_the_quarter(self) -> None:
        """A section-two title says this quarter's reading first, not a ten-year range."""
        fin = self.staging["financials"]

        def yoy(key: str) -> float:
            return (fin[key][-1] / fin[key][-5] - 1) * 100

        mix = self.exhibit_by_ref("EX_MIX")["title"]
        self.assertTrue(mix.startswith(f"总收入同比 {yoy('total_revenues'):+.1f}%".replace("-", "−")), mix)
        self.assertIn(f"清算与交易费同比 {yoy('clearing_fees'):+.1f}%".replace("-", "−"), mix)
        self.assertNotIn("区间", mix)
        coll = self.staging["collateral"]
        this = coll["quarters"][-1]
        prior = coll["quarters"].index(f"{int(this[:4]) - 1}{this[4:]}")
        spread = self.exhibit_by_ref("EX_SPREAD")["title"]
        self.assertIn(f"同比 {(coll['net'][-1] / coll['net'][prior] - 1) * 100:+.1f}%".replace("-", "−"),
                      spread)
        income = self.staging["long"]["investment_income"]
        self.assertIn(f"投资收益同比 {(income[-1] / income[-5] - 1) * 100:+.1f}%".replace("-", "−"), spread)

    def test_the_brief_leads_with_the_quarter_not_the_capex_record(self) -> None:
        """「本季三条主线」: the first used to be the sixteen-year capex record."""
        fin = self.staging["financials"]
        brief = self.payload["brief"]
        self.assertNotIn("<span>记录</span>", brief)
        first = brief.split("</article>")[0]
        self.assertIn("<span>增长</span>", first)
        for key, name in (("clearing_fees", "清算与交易费"), ("market_data", "行情数据"),
                          ("other_revenue", "其他收入")):
            change = fin[key][-1] - fin[key][-5]
            self.assertIn(f"{name} {'−' if change < 0 else '+'}US${abs(change):,.1f}M", first)

    def test_section_two_names_what_it_cannot_draw(self) -> None:
        undrawn = self.staging["quarter_context"]["undrawn"]
        highlights = next(s for s in self.payload["sections"] if s["id"] == "quarter_highlights")
        self.assertIn(f"另有{cn_count(len(undrawn))}条画不了：", highlights["description"])
        for item in undrawn:
            self.assertIn(item, highlights["description"])

    # ── the two windows ─────────────────────────────────────────────────────
    def test_the_short_window_starts_where_the_adjusted_table_does(self) -> None:
        """2024Q3 is the year-ago column of the first release that printed it."""
        fin = self.staging["financials"]
        periods = self.staging["periods"]
        self.assertEqual(periods[0], "2024Q3")
        self.assertEqual(periods, quarters_from("2024Q3", period_key(self.staging["_checks"]["period"])))
        for name, values in fin.items():
            self.assertEqual(len(values), len(periods), name)
            self.assertTrue(all(v is not None for v in values), name)

    def test_quarters_are_contiguous_calendar_labels(self) -> None:
        for series in (self.staging["periods"], self.staging["long"]["quarters"]):
            for earlier, later in zip(series, series[1:]):
                y1, q1 = int(earlier[:4]), int(earlier[5])
                y2, q2 = int(later[:4]), int(later[5])
                self.assertEqual((y2, q2), (y1 + 1, 1) if q1 == 4 else (y1, q1 + 1))

    def test_the_long_series_runs_from_2013_without_a_gap(self) -> None:
        quarters = self.staging["long"]["quarters"]
        last = period_key(self.staging["_checks"]["period"])
        self.assertEqual(quarters, quarters_from("2013Q1", last))
        # Where a series is allowed to have holes, and where the holes are. A
        # series not listed here must be complete; a series listed here must
        # actually have its holes in the stated range, so an entry cannot be
        # used to wave through a gap somewhere else.
        holes = {
            # A line the company retired at 2018Q4. Holes, not backfills --
            # see the fold test below.
            "access_comm": ("2018Q4", last),
            # Adjusted figures were backfilled to 2016Q1, which is where this
            # site's window starts; 2013Q1-2015Q4 was not fetched. That is a
            # scope decision, not a disclosure limit -- the reconciliation
            # tables exist for those quarters too.
            "adj_net_income": ("2013Q1", "2015Q4"),
            "adj_diluted_eps": ("2013Q1", "2015Q4"),
            "adj_basic_eps": ("2013Q1", "2015Q4"),
        }
        for name, values in self.staging["long"].items():
            if not isinstance(values, list):
                continue          # provenance strings and the outlier record
            self.assertEqual(len(values), len(quarters), name)
            missing = [quarters[i] for i, v in enumerate(values) if v is None]
            if name not in holes:
                self.assertEqual(missing, [], name)
                continue
            low, high = holes[name]
            # Equality, not containment. "The holes sit inside this range" would
            # let a value appear in the middle of a declared gap without anyone
            # noticing -- and a value that appears where the data was said not to
            # exist is the one thing this check is for. Filling part of a hole
            # is fine; it just has to be recorded here in the same commit.
            self.assertEqual(missing, [q for q in quarters if low <= q <= high], name)

    def test_the_tax_outlier_is_left_as_a_hole(self) -> None:
        """2017Q4 is not a tax rate, so it is not drawn.

        The deferred-tax remeasurement under the Tax Cuts and Jobs Act made that
        quarter's income tax a large net credit; the effective rate computes to
        -411%. Drawn on one axis with the rest it squeezes forty-one quarters
        into the top few percent of the canvas -- a chart that passes every gate
        and shows nothing. Nothing else on this page would notice if somebody
        "fixed" the hole, so it is pinned here.
        """
        outlier = self.staging["long"]["effective_tax_outlier"]
        self.assertEqual(outlier["quarter"], "2017Q4")
        self.assertLess(outlier["value"], -100)
        exhibits = [ex for section in self.payload["sections"] for ex in section["exhibits"]]
        chart = next(ex for ex in exhibits if "GAAP 有效税率" in ex["title"])
        drawn = [v for v in chart["series"][0]["values"] if v is not None]
        self.assertEqual(len(chart["series"][0]["values"]) - len(drawn), 1)
        self.assertNotIn(outlier["value"], chart["series"][0]["values"])
        # With it out, the axis spans something a reader can use.
        self.assertLess(max(drawn) - min(drawn), 40, "the drawn range blew up again")
        self.assertGreater(min(drawn), 0)
        # And the hole is where the record says it is.
        index = chart["series"][0]["values"].index(None)
        self.assertEqual(chart["xlabels"][index], "Q4 2017")

    def test_the_window_is_the_tail_of_the_long_series(self) -> None:
        """The two windows must not disagree about an overlapping quarter."""
        long = self.staging["long"]
        self.assertEqual(long["quarters"][-8:], self.staging["periods"])
        for offset, quarter in enumerate(self.staging["periods"]):
            index = long["quarters"].index(quarter)
            for key in ("total_revenues", "clearing_fees", "market_data"):
                self.assertAlmostEqual(long[key][index],
                                       self.staging["financials"][key][offset],
                                       places=3, msg=f"{quarter} {key}")

    # ── income-statement identities ─────────────────────────────────────────
    def test_the_three_revenue_lines_sum_to_total_revenue(self) -> None:
        long = self.staging["long"]
        for i, quarter in enumerate(long["quarters"]):
            parts = long["clearing_fees"][i] + long["market_data"][i] + long["other_revenue"][i]
            self.assertAlmostEqual(parts, long["total_revenues"][i], places=1, msg=quarter)

    def test_the_pre_2019_other_line_is_the_two_disclosed_lines_added(self) -> None:
        """Access and communication fees were folded into Other at 2018Q4.

        The page draws one basis across that change by adding the two lines the
        older releases printed. The addition is only legitimate while both are
        present, so this asserts the fold happens exactly where the disclosure
        changed and nowhere else.
        """
        long = self.staging["long"]
        split = [q for q, v in zip(long["quarters"], long["access_comm"]) if v is not None]
        self.assertEqual(split[0], "2013Q1")
        self.assertEqual(split[-1], "2018Q3")
        self.assertEqual(len(split), long["quarters"].index("2018Q4"))

    def test_operating_income_is_revenue_less_expenses(self) -> None:
        long = self.staging["long"]
        for i, quarter in enumerate(long["quarters"]):
            self.assertAlmostEqual(long["total_revenues"][i] - long["total_expenses"][i],
                                   long["operating_income"][i], places=1, msg=quarter)

    def test_the_non_operating_subtotal_closes_every_quarter(self) -> None:
        long = self.staging["long"]
        for i, quarter in enumerate(long["quarters"]):
            parts = (long["investment_income"][i] + long["interest_cost"][i]
                     + long["equity_earnings"][i] + long["other_nonop"][i]
                     + long["derivative_gains"][i])
            self.assertAlmostEqual(parts, long["total_nonop"][i], places=1, msg=quarter)

    def test_pretax_and_net_income_close_every_quarter(self) -> None:
        long = self.staging["long"]
        for i, quarter in enumerate(long["quarters"]):
            self.assertAlmostEqual(long["operating_income"][i] + long["total_nonop"][i],
                                   long["pretax_income"][i], places=1, msg=quarter)
            self.assertAlmostEqual(long["pretax_income"][i] - long["tax_provision"][i],
                                   long["net_income"][i], places=1, msg=quarter)

    def test_margins_and_the_tax_rate_are_the_ratios_they_claim_to_be(self) -> None:
        long = self.staging["long"]
        fin = self.staging["financials"]
        for i, quarter in enumerate(long["quarters"]):
            self.assertAlmostEqual(
                100 * long["operating_income"][i] / long["total_revenues"][i],
                long["gaap_margin_pct"][i], places=4, msg=quarter)
            self.assertAlmostEqual(
                100 * long["tax_provision"][i] / long["pretax_income"][i],
                long["effective_tax_pct"][i], places=4, msg=quarter)
        for i, quarter in enumerate(self.staging["periods"]):
            self.assertAlmostEqual(
                100 * fin["adj_operating_income"][i] / fin["total_revenues"][i],
                fin["adj_margin_pct"][i], places=4, msg=quarter)

    def test_the_adjusted_margin_exceeds_the_gaap_margin_every_quarter(self) -> None:
        fin = self.staging["financials"]
        for i, quarter in enumerate(self.staging["periods"]):
            self.assertGreater(fin["adj_margin_pct"][i], fin["gaap_margin_pct"][i], quarter)

    def test_the_ex_licence_expense_is_the_two_disclosed_lines_subtracted(self) -> None:
        fin = self.staging["financials"]
        for i, quarter in enumerate(self.staging["periods"]):
            self.assertAlmostEqual(
                fin["adj_total_expenses"][i] - fin["licensing_expense"][i],
                fin["adj_opex_ex_license"][i], places=3, msg=quarter)

    # ── volume, rate and the fee split ──────────────────────────────────────
    def test_the_six_asset_classes_sum_to_the_published_total_volume(self) -> None:
        long = self.staging["long"]
        for i, quarter in enumerate(long["quarters"]):
            parts = sum(long[f"adv_{key}"][i] for key in CLASS_KEYS)
            # The release rounds each line to a whole thousand contracts, so the
            # parts can miss the printed total by a couple of thousand.
            self.assertLessEqual(abs(parts - long["adv_k"][i]), 3, quarter)

    def test_the_class_rates_weighted_by_class_volume_reproduce_the_average(self) -> None:
        """Classes and total must be on one basis, or every split below is wrong."""
        long = self.staging["long"]
        for i, quarter in enumerate(long["quarters"]):
            volume = sum(long[f"adv_{key}"][i] for key in CLASS_KEYS)
            weighted = sum(long[f"adv_{key}"][i] * long[f"rpc_{key}"][i]
                           for key in CLASS_KEYS) / volume
            self.assertAlmostEqual(weighted, long["rpc"][i], places=2, msg=quarter)

    def test_contracts_and_the_futures_fee_are_the_product_they_claim(self) -> None:
        long = self.staging["long"]
        for i, quarter in enumerate(long["quarters"]):
            self.assertAlmostEqual(long["adv_k"][i] * long["trading_days"][i] / 1000,
                                   long["contracts_m"][i], places=3, msg=quarter)
            self.assertAlmostEqual(long["contracts_m"][i] * long["rpc"][i],
                                   long["fo_clearing_fees"][i], places=3, msg=quarter)
            self.assertAlmostEqual(long["clearing_fees"][i] - long["fo_clearing_fees"][i],
                                   long["other_clearing_fees"][i], places=3, msg=quarter)

    def test_the_fee_remainder_steps_at_the_acquisition_that_created_it(self) -> None:
        """The remainder is BrokerTec and EBS, so it must appear when they do."""
        long = self.staging["long"]
        split = long["quarters"].index("2018Q4")
        before = long["other_clearing_fees"][:split]
        after = long["other_clearing_fees"][split:]
        self.assertEqual(split, 23)
        self.assertLess(max(before), 25.0)
        self.assertGreater(min(after), 85.0)
        self.assertTrue(all(v > 0 for v in long["other_clearing_fees"]))

    def test_the_remainder_chart_marks_that_step_as_a_break(self) -> None:
        exhibit = self.exhibit_by_ref("EX_RESIDUAL")
        self.assertEqual(exhibit["break_at"], self.staging["long"]["quarters"].index("2018Q4"))
        self.assertIn("NEX", exhibit["break_label"])

    def test_the_published_beta_is_the_regression_on_the_published_series(self) -> None:
        long = self.staging["long"]
        contracts = cme.qoq(long["contracts_m"])
        slope, r2 = cme.slope_and_r2(contracts, cme.qoq(long["total_revenues"]))
        self.assertEqual(len(contracts), len(long["quarters"]) - 1)
        self.assertIn(f"{slope:.2f}", self.payload["headline"])
        self.assertIn(f"{cn_count(len(contracts))}次环比变动测出来的同一条斜率", self.payload["headline"])
        self.assertLess(slope, 1.0)
        self.assertGreater(r2, 0.85)

    def test_volume_and_rate_move_against_each_other_more_often_than_not(self) -> None:
        long = self.staging["long"]
        opposite = cme.opposite_moves(long)
        self.assertGreater(opposite, len(long["quarters"]) // 2)
        self.assertLess(cme.rpc_slope(long), 0.0)

    # ── the capital-expenditure record ──────────────────────────────────────
    def test_every_guided_year_carries_an_ordered_range_and_a_named_form(self) -> None:
        capex = self.staging["capex_guidance"]
        self.assertEqual(capex["years"][0], "2010")
        self.assertEqual(capex["years"],
                         [str(y) for y in range(2010, int(capex["years"][-1]) + 1)])
        for year in capex["years"]:
            block = capex["by_year"][year]
            self.assertLessEqual(block["low"], block["high"], year)
            self.assertIn(block["form"], ("point", "range"), year)
            if block["form"] == "point":
                self.assertEqual(block["low"], block["high"], year)
            else:
                self.assertLess(block["low"], block["high"], year)

    def test_the_three_range_years_are_the_ones_the_page_names(self) -> None:
        capex = self.staging["capex_guidance"]
        ranges = [y for y in capex["years"] if capex["by_year"][y]["form"] == "range"]
        self.assertEqual(ranges, ["2010", "2012", "2013"])

    def test_finished_years_have_an_actual_and_the_open_year_does_not(self) -> None:
        capex = self.staging["capex_guidance"]
        finished = cme.finished_capex_years(capex)
        self.assertEqual(finished, capex["years"][:-1])
        self.assertIsNone(capex["by_year"][capex["years"][-1]]["actual"])

    def test_the_tally_the_page_publishes_is_the_one_in_the_data(self) -> None:
        """Section one's own chart carries the record; the brief is this quarter's."""
        capex = self.staging["capex_guidance"]
        tally = cme.capex_tally(capex)
        self.assertEqual(sum(tally.values()), len(cme.finished_capex_years(capex)))
        title = self.exhibit_by_ref("EX_CAPEX")["title"]
        self.assertIn(f'{tally["below"]} 年跌破下限', title)
        self.assertIn(f'{tally["above"]} 年超出上限', title)
        self.assertIn(f'{tally["inside"]} 年落在区间内', title)

    def test_the_overshoots_are_the_build_years_and_one_more(self) -> None:
        """Three consecutive, then a fourth -- and the fourth is easy to miss.

        The page's own prose was first written saying the overshoots were the
        three consecutive build years, which is what a reader scanning the
        chart sees. FY2024 is the fourth and it is small (US$94.0M against a
        US$85M point), so it does not stand out on an axis that runs to
        US$245M. It is asserted separately from the tally for that reason.
        """
        capex = self.staging["capex_guidance"]
        # Pinned to the years this was checked through; later years only add.
        through = [y for y in cme.finished_capex_years(capex) if y <= "2025"]
        above = [y for y in through
                 if capex["by_year"][y]["actual"] > capex["by_year"][y]["high"]]
        self.assertEqual(above, ["2018", "2019", "2020", "2024"])
        below_mid = [y for y in through
                     if capex["by_year"][y]["actual"]
                     < cme.mid(capex["by_year"][y]["low"], capex["by_year"][y]["high"])]
        self.assertEqual(len(below_mid), 12)

    def test_the_guidance_sentence_is_carried_for_every_year(self) -> None:
        capex = self.staging["capex_guidance"]
        for year in capex["years"]:
            sentence = capex["by_year"][year]["sentence"]
            self.assertIn(year, sentence)
            self.assertIn("capital expenditures", sentence.lower())
            self.assertRegex(capex["by_year"][year]["source_filed"], r"^\d{4}-\d{2}-\d{2}$")

    # ── the collateral spread ───────────────────────────────────────────────
    def test_the_collateral_net_is_the_two_disclosed_figures_subtracted(self) -> None:
        coll = self.staging["collateral"]
        for i, quarter in enumerate(coll["quarters"]):
            self.assertAlmostEqual(coll["earnings"][i] - coll["distribution"][i],
                                   coll["net"][i], places=3, msg=quarter)
            self.assertGreater(coll["earnings"][i], coll["distribution"][i], quarter)

    def test_the_spread_series_is_annualised_against_the_average_balance(self) -> None:
        coll = self.staging["collateral"]
        for i, quarter in enumerate(coll["quarters"]):
            balance = coll["avg_balance_usd_m"][i]
            self.assertIsNotNone(balance, quarter)
            self.assertAlmostEqual(1e4 * coll["net"][i] * 4 / balance,
                                   coll["retained_bp"][i], places=3, msg=quarter)
            self.assertAlmostEqual(1e4 * coll["earnings"][i] * 4 / balance,
                                   coll["gross_bp"][i], places=3, msg=quarter)

    def test_the_retained_spread_is_narrow_while_the_gross_yield_is_not(self) -> None:
        """A numerator paired with the wrong period would not hold this shape.

        The four sentence shapes that carry these two figures each put a second
        number beside the quarter's -- a year-to-date, a prior-year quarter or a
        prior full year. Taking the wrong one moves the numerator by tens of
        percent while the denominator stays put, which would widen this band
        immediately.
        """
        coll = self.staging["collateral"]
        post_zirp = coll["retained_bp"][2:]
        gross = coll["gross_bp"][2:]
        self.assertGreaterEqual(len(post_zirp), 12)
        self.assertGreater(min(post_zirp), 20.0)
        self.assertLess(max(post_zirp), 40.0)
        self.assertGreater(max(gross) / min(gross), 2.0)

    def test_the_zero_rate_quarters_are_the_ones_at_the_left_edge(self) -> None:
        coll = self.staging["collateral"]
        self.assertEqual(coll["quarters"][:2], ["2021Q3", "2022Q1"])
        for bp in coll["retained_bp"][:2]:
            self.assertLess(bp, 10.0)

    def test_the_page_refuses_to_call_the_income_statement_difference_a_spread(self) -> None:
        """2021's other non-operating line is positive; subtracting would lie."""
        long = self.staging["long"]
        index = long["quarters"].index("2021Q3")
        self.assertGreater(long["other_nonop"][index], 0)
        note = self.exhibit_by_ref("EX_INVEST")["note"]
        self.assertIn("本页不把这两条相减当成利差", note)

    # ── section three: the local analysis's thresholds ──────────────────────
    def test_the_thresholds_are_the_local_analysis_s_own(self) -> None:
        """Held to a second keying of the same report section, not to the builder.

        `_checks["note"]` is typed separately from the report's section 8 (its
        observation table and its three stance-reversal conditions), the way
        `_checks` is typed separately from the release. A roll re-keys both;
        this test does not change.
        """
        kpi = self.staging["next_kpi"]
        note = self.staging["_checks"]["note"]
        self.assertEqual(kpi["period"], self.staging["period_labels"][-1])
        self.assertEqual(
            [(e["id"], e["metric"], e["direction"], e["threshold"]) for e in kpi["quantified"]],
            [(t["id"], t["metric"], t["direction"], t["threshold"]) for t in note["next_thresholds"]])
        upside = {}
        for entry in kpi["quantified"]:
            for key, value in entry.get("upside", {}).items():
                if key != "basis":
                    upside[f"{entry['id']}_{key}" if key == "below" else key] = value
        self.assertEqual(upside, {k: v for k, v in note["next_upside"].items() if not k.startswith("_")})
        self.assertEqual(len(kpi["not_carried"]), note["next_not_carried"]["count"])
        for entry in kpi["quantified"]:
            # Nothing the page could go stale on is stored beside a threshold.
            self.assertNotIn("current", entry, entry["id"])
            self.assertTrue(entry["basis"], entry["id"])

    @staticmethod
    def readings(staging: dict) -> dict:
        """This quarter's value of each tracked metric, computed here from the
        disclosed lines rather than through the builder's own helpers."""
        fin, long = staging["financials"], staging["long"]
        return {
            "adj_margin": 100 * fin["adj_operating_income"][-1] / fin["total_revenues"][-1],
            "adj_opex": fin["adj_total_expenses"][-1] - fin["licensing_expense"][-1],
            "adv": long["adv_k"][-1],
            "rpc": long["rpc"][-1],
            "rates_adv_yoy": long["adv_rates"][-1] / long["adv_rates"][-5],
            "market_data_qoq": long["market_data"][-1] / long["market_data"][-2],
            "market_data_yoy": 100 * (long["market_data"][-1] / long["market_data"][-5] - 1),
        }

    def test_every_next_quarter_threshold_has_a_headroom_bar(self) -> None:
        entries = self.staging["next_kpi"]["quantified"]
        upcoming = [e for e in entries if not e.get("settles")]
        self.assertLess(len(upcoming), len(entries), "the Q1 2027 line is not a next-quarter bar")
        now = self.readings(self.staging)
        bar = self.exhibit_by_ref("EX_HEADROOM")
        self.assertTrue(bar["title"].startswith(f"下季 {len(upcoming)} 条阈值："))
        self.assertEqual(bar["xlabels"], [e["metric"] for e in upcoming])
        for entry, value in zip(upcoming, bar["values"]):
            self.assertNotEqual(entry["threshold"], 0.0, entry["metric"])
            self.assertAlmostEqual(headroom(entry["direction"], entry["threshold"], now[entry["reads"]]),
                                   value, places=1, msg=entry["metric"])

    def test_every_next_quarter_threshold_is_drawn_against_its_own_history(self) -> None:
        """「X：下季阈值 A，当前 B」, one chart per metric, every threshold on it."""
        section = next(s for s in self.payload["sections"] if s["id"] == "next_quarter")
        charts = section["exhibits"][1:]
        upcoming = [e for e in self.staging["next_kpi"]["quantified"] if not e.get("settles")]
        by_metric = {}
        for entry in upcoming:
            by_metric.setdefault(entry["reads"], []).append(entry)
        self.assertEqual(len(charts), len(by_metric))
        now = self.readings(self.staging)
        for chart, (reads, group) in zip(charts, by_metric.items()):
            with self.subTest(metric=reads):
                self.assertEqual(chart["kind"], "lines")
                self.assertIn("：下季阈值 ", chart["title"])
                self.assertIn("，当前 ", chart["title"])
                lines = [s["values"] for s in chart["series"][1:]]
                self.assertEqual([line[0] for line in lines], [e["threshold"] for e in group])
                self.assertTrue(all(len(set(line)) == 1 for line in lines))
                self.assertAlmostEqual(chart["series"][0]["values"][-1], now[reads], places=4)

    def test_the_rest_of_section_8_is_named_with_the_reason_it_is_not_drawn(self) -> None:
        kpi = self.staging["next_kpi"]
        note = self.exhibit_by_ref("EX_HEADROOM")["note"]
        for item in kpi["not_carried"]:
            self.assertIn(item["text"], note)
        later = [e for e in kpi["quantified"] if e.get("settles")]
        table = next(t for t in self.payload["tables"] if t["title"].startswith("下季阈值"))
        self.assertEqual([row[0] for row in table["rows"]],
                         [e["metric"] + (f"（{e['settles']} 结算）" if e.get("settles") else "")
                          for e in kpi["quantified"]])
        self.assertEqual(table["headers"][-1], "出处（本地研究）")
        for entry in later:
            self.assertIn(f"另有一条要到 {entry['settles']} 才结算", note)
        blob = json.dumps(self.payload, ensure_ascii=False)
        for stale in ("本页设定", "本页自己设的", "阈值为本页"):
            self.assertNotIn(stale, blob)

    # ── what the page will and will not publish ─────────────────────────────

    def test_the_call_only_expense_guidance_is_named_and_not_published(self) -> None:
        notes = " ".join(self.payload["notes"])
        self.assertIn("只在业绩电话会上出现", notes)
        guidance = self.staging["quarter_context"]["call_expense_guidance"]
        self.assertIn(f"{guidance['adj_opex_ex_license_usd_m'] / 100:.2f}", notes)
        blob = json.dumps(self.payload, ensure_ascii=False)
        self.assertNotIn("1,695", blob)
        self.assertNotIn("1695", blob)

    def test_no_market_expectation_is_published(self) -> None:
        blob = json.dumps(self.payload, ensure_ascii=False)
        for term in ("一致预期", "目标价", "评级"):
            self.assertNotIn(term + "为", blob)
        self.assertIn("本页不发布市场一致预期", " ".join(self.payload["notes"]))

    def test_the_label_drift_that_would_have_gone_unnoticed_is_written_down(self) -> None:
        notes = " ".join(self.payload["notes"])
        self.assertIn("Equities", notes)
        self.assertIn("二十一个季度", notes)

    def test_the_venue_split_is_excluded_and_says_why(self) -> None:
        self.assertNotIn("adv_globex", json.dumps(self.staging))
        notes = " ".join(self.payload["notes"])
        self.assertIn("275 千手", notes)

    # ── page mechanics ──────────────────────────────────────────────────────
    def exhibit_by_ref(self, ref: str) -> dict:
        for section in self.payload["sections"]:
            for exhibit in section["exhibits"]:
                if exhibit.get("ref") == ref:
                    return exhibit
        raise AssertionError(f"no exhibit with ref {ref}")

    def test_exhibits_are_numbered_in_render_order_and_refs_resolve(self) -> None:
        numbers = [ex["n"] for section in self.payload["sections"]
                   for ex in section["exhibits"]]
        self.assertEqual(numbers, list(range(2, 2 + len(numbers))))
        for section in self.payload["sections"]:
            for exhibit in section["exhibits"]:
                for key in ("title", "note", "src_extra"):
                    self.assertNotIn("{EX_", exhibit.get(key) or "", exhibit["title"])

    def test_tables_are_numbered_after_the_exhibits(self) -> None:
        last = max(ex["n"] for section in self.payload["sections"]
                   for ex in section["exhibits"])
        self.assertEqual([t["n"] for t in self.payload["tables"]],
                         list(range(last + 1, last + 1 + len(self.payload["tables"]))))

    def test_every_exhibit_carries_a_note_and_a_source_line(self) -> None:
        for section in self.payload["sections"]:
            for exhibit in section["exhibits"]:
                self.assertTrue(exhibit.get("note"), exhibit["title"])
                self.assertTrue(exhibit.get("src_extra"), exhibit["title"])

    def test_every_series_is_as_long_as_its_axis(self) -> None:
        for section in self.payload["sections"]:
            for exhibit in section["exhibits"]:
                width = len(exhibit["xlabels"])
                blocks = [exhibit.get("values")]
                # `net` belongs in this group, not appended raw: `bridgeNet` in
                # charts.js reads `ex.net.values`, so a bare list is the broken
                # shape and this test used to require it.
                for key in ("bar", "line", "yoy", "actual", "lo", "hi", "net"):
                    block = exhibit.get(key)
                    blocks.append(block.get("values") if isinstance(block, dict) else block)
                for key in ("series", "groups", "stacks"):
                    blocks.extend(b.get("values") for b in exhibit.get(key) or [])
                for values in blocks:
                    if values is not None:
                        self.assertEqual(len(values), width, exhibit["title"])

    def test_literal_text_fields_carry_no_markup(self) -> None:
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
        for table in self.payload["tables"]:
            self.assertEqual(set(table), {"n", "title", "headers", "rows"},
                             table["title"][:40])
            for row in table["rows"]:
                self.assertEqual(len(row), len(table["headers"]), table["title"][:40])

    def test_the_published_payload_matches_a_fresh_build(self) -> None:
        self.assertEqual(js_payload(ROOT / "data" / "cme.js", "window.DASH"), self.payload)

    def test_the_page_declares_the_calendar_convention_in_its_subtitle(self) -> None:
        self.assertIn("自然年财年", self.payload["subtitle"])

    def test_the_roster_carries_cme_with_the_payload_s_own_labels(self) -> None:
        roster = roster_payload(build_all())
        entry = next(item for item in roster["items"] if item["slug"] == "cme")
        self.assertEqual(entry["latest_label"],
                         self.payload["latest"]["disclosed_period_label"])
        self.assertEqual(entry["release_date"], self.payload["latest"]["release_date"])
        self.assertEqual(entry["group"], "exchanges")
        self.assertIn(entry["group"], {group["key"] for group in roster["groups"]})

    def test_the_exchanges_group_is_appended_once_and_keeps_the_order_sorted(self) -> None:
        keys = [group["key"] for group in GROUPS]
        self.assertEqual(keys.count("exchanges"), 1)
        self.assertEqual(keys[-1], "exchanges")
        orders = [group["order"] for group in GROUPS]
        self.assertEqual(orders, sorted(orders))
        self.assertEqual(len(set(orders)), len(orders))
        entry = next(e for e in ENTRIES if e["slug"] == "cme")
        self.assertEqual(entry["group"], "exchanges")

    def test_the_home_page_card_matches_the_entry(self) -> None:
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        entry = next(e for e in ENTRIES if e["slug"] == "cme")
        self.assertIn('href="cme/"', home)
        self.assertIn(entry["name"], home)
        staging = json.loads(cme.STAGING_PATH.read_text(encoding="utf-8"))
        self.assertIn(" · ".join(cme.headline_metrics(staging)), home)

    def test_the_shell_links_the_payload_by_content_hash(self) -> None:
        shell = (ROOT / "cme" / "index.html").read_text(encoding="utf-8")
        sources = re.findall(r'<script src="\.\./([^"?]+)(\?v=([0-9a-f]+))?"', shell)
        self.assertEqual([name for name, _, _ in sources],
                         ["data/roster.js", "data/cme.js",
                          "assets/charts.js", "assets/page.js"])
        for name, _, digest in sources:
            expected = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()[:8]
            self.assertEqual(digest, expected, name)



class CmeChecksTest(unittest.TestCase):
    """The page's quarter against a record keyed separately from the filing.

    `_checks` is typed once per quarter from the release, with the place in it
    each figure was read from; the builder never reads it (asserted in
    `test_data_only_roll`). Rolling a quarter re-keys `_checks`; this class does
    not change.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(cme.STAGING_PATH.read_text(encoding="utf-8"))
        cls.checks = cls.staging["_checks"]
        cls.payload = cme.build_payload(cls.staging)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]

    def test_the_page_names_the_checked_quarter_both_ways(self) -> None:
        checks = self.checks
        self.assertIn(checks["period"], self.payload["title"])
        self.assertIn(f"截至 {checks['period_end']}", self.payload["subtitle"])
        self.assertIn(f"发布 {checks['release_date']}", self.payload["subtitle"])
        quarter, year = checks["period"].split()
        self.assertIn(f"CME Group {year} 年第{cn_ordinal(int(quarter[1]))}季度业绩新闻稿",
                      self.payload["source"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        long, fin, checks = self.staging["long"], self.staging["financials"], self.checks
        for line, (now, year_ago) in checks["income_statement_usd_m"].items():
            with self.subTest(line=line):
                self.assertAlmostEqual(long[line][-1], now, places=6)
                self.assertAlmostEqual(long[line][-5], year_ago, places=6)
        for line, (now, year_ago) in checks["adjusted_usd_m"].items():
            with self.subTest(line=line):
                self.assertAlmostEqual(fin[line][-1], now, places=6)
                self.assertAlmostEqual(fin[line][-5], year_ago, places=6)
        for key, (now, prior, year_ago) in checks["adv_k"].items():
            name = "adv_k" if key == "total" else f"adv_{key}"
            with self.subTest(adv=key):
                self.assertEqual([long[name][-1], long[name][-2], long[name][-5]], [now, prior, year_ago])
        for key, (now, prior, year_ago) in checks["rpc"].items():
            name = "rpc" if key == "total" else f"rpc_{key}"
            with self.subTest(rpc=key):
                self.assertEqual([long[name][-1], long[name][-2], long[name][-5]], [now, prior, year_ago])
        self.assertEqual([long["trading_days"][-1], long["trading_days"][-2], long["trading_days"][-5]],
                         checks["trading_days"])
        self.assertEqual(self.staging["window_collateral_balance_usd_m"][-1],
                         checks["performance_bonds_usd_m"])

    def test_what_the_release_says_about_its_quarter_the_series_says_too(self) -> None:
        """"The third highest quarterly ADV" and "a record" market data line."""
        long = self.staging["long"]
        rank = sorted(long["adv_k"], reverse=True).index(long["adv_k"][-1]) + 1
        self.assertEqual(rank, self.checks["adv_rank_printed"])
        if self.checks["market_data_record_printed"]:
            self.assertEqual(long["market_data"][-1], max(long["market_data"]))

    def test_the_headline_prints_the_checked_figures(self) -> None:
        income = self.checks["income_statement_usd_m"]
        headline = self.payload["headline"]
        now, before = income["total_revenues"]
        self.assertIn(f"总收入 US${now:,.1f}M、同比 {(now / before - 1) * 100:+.1f}%", headline)
        now, before = income["clearing_fees"]
        self.assertIn(f"清算与交易费同比 {(now / before - 1) * 100:+.1f}%", headline)
        adjusted = self.checks["adjusted_usd_m"]["adj_operating_income"][0]
        self.assertIn(f"调整后 {adjusted / income['total_revenues'][0] * 100:.1f}%",
                      next(ex["title"] for ex in self.exhibits if ex["title"].startswith("两条营业利润率")))


class CmeRollTest(unittest.TestCase):
    """A roll edits the series and nothing else: the one-quarter blocks and the
    sentences about the record are held to what the series says."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(cme.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = cme.build_payload(cls.staging)
        cls.text = published_text(cls.payload)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]

    def rebuilt(self, edit) -> dict:
        changed = copy.deepcopy(self.staging)
        edit(changed)
        return cme.build_payload(changed)

    def test_quarter_blocks_refuse_to_publish_under_another_quarter(self) -> None:
        for key in ("next_kpi", "quarter_context"):
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    self.rebuilt(lambda s, key=key: s[key].__setitem__("period", "Q1 1999"))
        quarter, year = self.staging["period_labels"][-1].split()
        label = f"CME Group {year} 年第{cn_ordinal(int(quarter[1]))}季度业绩新闻稿"
        with self.assertRaisesRegex(ValueError, "sources"):
            self.rebuilt(lambda s: s.__setitem__(
                "sources", [x for x in s["sources"] if not x["label"].startswith(label)]))

    def test_the_first_cell_is_counted_not_remembered(self) -> None:
        """「这是第一格」holds only while the quarter before was on the safe side.

        The local analysis wrote "Q2 已 −6.1%，这是第一格" about rates volume
        falling year on year; the page prints the same kind of sentence from the
        series. Both states are built here, so the test does not depend on
        which one the current quarter happens to be in.
        """
        def rates_down_for(quarters: int):
            def edit(s):
                rates = s["long"]["adv_rates"]
                for back in range(1, 4):
                    i = len(rates) - back
                    rates[i] = rates[i - 4] + (-1 if back <= quarters else 1)
            return edit
        once = published_text(self.rebuilt(rates_down_for(1)))
        twice = published_text(self.rebuilt(rates_down_for(2)))
        self.assertIn("这是第一格", once)
        self.assertNotIn("已经触发", once)
        self.assertNotIn("这是第一格", twice)
        self.assertIn("已经触发", twice)

    def test_the_quarter_claims_follow_the_data(self) -> None:
        """Two sentences this commit added are printed only while the series says so."""
        # 「行情数据一条线扛下全部增量」: market data's own year-on-year change
        # has to exceed the whole company's while the clearing line shrinks.
        def legs(clearing: float, market: float, other: float):
            def edit(s):
                fin = s["financials"]
                for key, change in (("clearing_fees", clearing), ("market_data", market),
                                    ("other_revenue", other)):
                    fin[key][-1] = fin[key][-5] + change
                fin["total_revenues"][-1] = sum(fin[key][-1] for key in
                                                ("clearing_fees", "market_data", "other_revenue"))
            return edit
        carried = published_text(self.rebuilt(legs(-30.0, 40.0, 5.0)))
        shared = published_text(self.rebuilt(legs(-30.0, 40.0, 100.0)))
        for claim in ("比全公司的", "行情数据一条线扛下全部增量", "行情数据一条线的增量就比全公司多"):
            with self.subTest(claim=claim):
                self.assertIn(claim, carried)
                self.assertNotIn(claim, shared)

        # 「落在这条长期关系上」: put the last quarter on the fitted line of the
        # other fifty-two changes, then far off it.
        def revenue_move(fitted: bool):
            def edit(s):
                long = s["long"]
                x = [(b / a - 1) * 100 for a, b in zip(long["contracts_m"], long["contracts_m"][1:])]
                y = [(b / a - 1) * 100 for a, b in zip(long["total_revenues"], long["total_revenues"][1:])]
                xs, ys = x[:-1], y[:-1]
                mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
                slope = (sum((a - mx) * (b - my) for a, b in zip(xs, ys))
                         / sum((a - mx) ** 2 for a in xs))
                move = my + slope * (x[-1] - mx) if fitted else y[-1] + 30
                long["total_revenues"][-1] = long["total_revenues"][-2] * (1 + move / 100)
            return edit
        on_line = published_text(self.rebuilt(revenue_move(True)))
        off_line = published_text(self.rebuilt(revenue_move(False)))
        self.assertIn("落在这条长期关系上", on_line)
        self.assertNotIn("落在这条长期关系上", off_line)
        self.assertIn("偏离了这条长期关系", off_line)

    def test_a_later_quarter_must_settle_the_previous_analysis(self) -> None:
        """「第一份分析」is true of one quarter only; after it, section one owes a settlement."""
        with self.assertRaisesRegex(ValueError, "prior_kpi_settlement"):
            self.rebuilt(lambda s: s["analysis_record"].__setitem__("first_period", "Q1 2026"))
        with self.assertRaisesRegex(ValueError, "not the first CME analysis"):
            self.rebuilt(lambda s: s.pop("analysis_record"))

    def test_a_quarter_without_its_blocks_leaves_them_out(self) -> None:
        def strip(s):
            del s["next_kpi"]
            del s["quarter_context"]
        payload = self.rebuilt(strip)
        sections = {sec["id"]: sec for sec in payload["sections"]}
        self.assertEqual(sections["next_quarter"]["exhibits"], [])
        self.assertEqual(len(payload["tables"]), len(self.payload["tables"]) - 1)
        text = published_text(payload)
        for gone in ("逐字检索过", "逐份检索过", "逐字搜过", "亿美元；", "本页数据截至", "条画不了"):
            with self.subTest(gone=gone):
                self.assertIn(gone, self.text)
                self.assertNotIn(gone, text)

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        def moves(claims, edit, present_before=True):
            after = published_text(self.rebuilt(edit))
            for claim in claims:
                with self.subTest(claim=claim):
                    self.assertEqual(claim in self.text, present_before)
                    self.assertEqual(claim in after, not present_before)

        # The clearing line's earlier negative quarter is what makes this one the second.
        def earlier_quarter_positive(s):
            i = s["periods"].index("2025Q3")
            s["financials"]["clearing_fees"][i] = s["financials"]["clearing_fees"][i - 4] + 1
        moves(("第二次同比转负", "第二次转负"), earlier_quarter_positive)
        moves(("是本窗口内第一次转负",), earlier_quarter_positive, present_before=False)

        # Agricultural ADV rose with its rate; make it fall and all six move against rate.
        def ags_down(s):
            s["long"]["adv_ags"][-1] = s["long"]["adv_ags"][-2] - 100
        moves(("六个品种的量与价同时反向",), ags_down, present_before=False)

        # The market-data line has carried all the growth once before (2018Q3).
        def not_before(s):
            i = s["long"]["quarters"].index("2018Q3")
            s["long"]["total_revenues"][i] = s["long"]["total_revenues"][i - 4] + 100
        moves(("第一次单独扛起全公司的同比增长",), not_before, present_before=False)

    def test_the_rankings_and_counts_are_recounted_here(self) -> None:
        staging, text = self.staging, self.text
        long, fin, capex = staging["long"], staging["financials"], staging["capex_guidance"]
        finished = cme.finished_capex_years(capex)
        under = sum(1 for y in finished if capex["by_year"][y]["actual"]
                    < cme.mid(capex["by_year"][y]["low"], capex["by_year"][y]["high"]))
        deviation = next(ex for ex in self.exhibits if ex.get("ref") == "EX_CAPEX_DEV")
        self.assertIn(f"{cn_count(len(finished))}年里有{cn_count(under)}年往同一个方向不准", deviation["note"])
        self.assertNotIn("一直偏高", text)
        self.assertNotIn("一直往同一个方向不准", text)
        # The EPS gap: the tax-reform quarter is the narrowest, not the widest.
        start = long["quarters"].index("2016Q1")
        gaps = [a - g for a, g in zip(long["adj_diluted_eps"][start:], long["diluted_eps"][start:])]
        eps = next(ex for ex in self.exhibits if "两条摊薄每股收益" in ex["title"])
        widest = long["quarters"][start + gaps.index(max(gaps))]
        self.assertIn(f"最宽 ${max(gaps):.2f}（{widest}）", eps["note"])
        self.assertIn(f"最窄的是 ${min(gaps):.2f}（{long['effective_tax_outlier']['quarter']}", eps["note"])
        # Investment income peaked before this quarter.
        income = long["investment_income"]
        invest = next(ex for ex in self.exhibits if "投资收益与利息分配支出" in ex["title"])
        self.assertIn(f"US${max(income):,.0f}M", invest["title"])
        # The biggest riser among the six classes is named, not the biggest mover.
        yoy = {name: long[f"adv_{key}"][-1] / long[f"adv_{key}"][-5] - 1 for key, name, _ in cme.CLASSES}
        riser = max(yoy, key=yoy.get)
        self.assertIn(f"{riser}同比", text)
        self.assertIn("同比涨得最多的一条", text)
        self.assertNotIn("同比幅度最大的一条", text)
        # The margin threshold has been broken inside the window.
        entry = next(e for e in staging["next_kpi"]["quantified"] if e["metric"] == "调整后营业利润率")
        below = sum(1 for v in fin["adj_margin_pct"] if v < entry["threshold"])
        self.assertIn(f"窗口里有{cn_count(below)}季低于它", text)
        self.assertNotIn("最低的一格再往下一点", text)
        # The run of quarters under the RPC line is 2021-2023.
        rpc_entry = next(e for e in staging["next_kpi"]["quantified"] if e["metric"] == "平均每手费率 RPC")
        self.assertNotIn("2019–2021 年的常态", text)
        rpc = long["rpc"][start:]
        years = sorted({long["quarters"][start + i][:4] for i, v in enumerate(rpc) if v < rpc_entry["threshold"]})
        self.assertTrue(set(years) >= {"2021", "2022", "2023"})
        # Every count of filings searched is the same count everywhere.
        searched = staging["quarter_context"]["searched"]
        self.assertEqual(text.count(searched), 4)
        for stale in ("三份 10-Q", "两份 10-Q"):
            self.assertNotIn(stale, text)


if __name__ == "__main__":
    unittest.main()
