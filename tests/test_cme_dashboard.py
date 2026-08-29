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
"""

from __future__ import annotations

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
from build.board import headroom  # noqa: E402

CLASS_KEYS = ("rates", "equity", "fx", "energy", "ags", "metals")


def js_payload(path: Path, marker: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{marker} = ", 1)[1].rstrip().rstrip(";")
    return json.loads(body)


class CmeDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(cme.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = cme.build_payload(cls.staging)

    # ── the two windows ─────────────────────────────────────────────────────
    def test_the_window_is_eight_quarters_and_complete(self) -> None:
        fin = self.staging["financials"]
        self.assertEqual(len(self.staging["periods"]), 8)
        for name, values in fin.items():
            self.assertEqual(len(values), 8, name)
            self.assertTrue(all(v is not None for v in values), name)

    def test_quarters_are_contiguous_calendar_labels(self) -> None:
        for series in (self.staging["periods"], self.staging["long"]["quarters"]):
            for earlier, later in zip(series, series[1:]):
                y1, q1 = int(earlier[:4]), int(earlier[5])
                y2, q2 = int(later[:4]), int(later[5])
                self.assertEqual((y2, q2), (y1 + 1, 1) if q1 == 4 else (y1, q1 + 1))

    def test_the_long_series_is_fifty_four_contiguous_quarters(self) -> None:
        quarters = self.staging["long"]["quarters"]
        self.assertEqual(len(quarters), 54)
        self.assertEqual(quarters[0], "2013Q1")
        self.assertEqual(quarters[-1], "2026Q2")
        for name, values in self.staging["long"].items():
            self.assertEqual(len(values), 54, name)
            if name == "access_comm":
                # A line the company retired at 2018Q4. Holes, not backfills --
                # see the fold test below.
                continue
            self.assertTrue(all(v is not None for v in values), name)

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
        self.assertEqual(len(contracts), 53)
        self.assertIn(f"{slope:.2f}", self.payload["headline"])
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
        self.assertEqual(len(capex["years"]), 17)
        self.assertEqual(capex["years"][0], "2010")
        self.assertEqual(capex["years"][-1], "2026")
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
        self.assertEqual(len(finished), 16)
        self.assertEqual(finished[-1], "2025")
        self.assertIsNone(capex["by_year"]["2026"]["actual"])

    def test_the_tally_the_page_publishes_is_the_one_in_the_data(self) -> None:
        capex = self.staging["capex_guidance"]
        tally = cme.capex_tally(capex)
        self.assertEqual(sum(tally.values()), 16)
        self.assertEqual(tally, {"below": 11, "above": 4, "inside": 1})
        brief = self.payload["brief"]
        self.assertIn(f'{tally["below"]} 年低于下限', brief)
        self.assertIn(f'{tally["above"]} 年高于上限', brief)
        self.assertIn(f'{tally["inside"]} 年落在区间内', brief)

    def test_the_overshoots_are_the_build_years_and_one_more(self) -> None:
        """Three consecutive, then a fourth -- and the fourth is easy to miss.

        The page's own prose was first written saying the overshoots were the
        three consecutive build years, which is what a reader scanning the
        chart sees. FY2024 is the fourth and it is small (US$94.0M against a
        US$85M point), so it does not stand out on an axis that runs to
        US$245M. It is asserted separately from the tally for that reason.
        """
        capex = self.staging["capex_guidance"]
        above = [y for y in cme.finished_capex_years(capex)
                 if capex["by_year"][y]["actual"] > capex["by_year"][y]["high"]]
        self.assertEqual(above, ["2018", "2019", "2020", "2024"])
        below_mid = [y for y in cme.finished_capex_years(capex)
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
        self.assertEqual(len(post_zirp), 12)
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

    # ── what the page will and will not publish ─────────────────────────────
    def test_every_quantified_threshold_has_a_headroom_bar(self) -> None:
        entries = self.staging["next_kpi"]["quantified"]
        bar = self.exhibit_by_ref("EX_HEADROOM")
        self.assertEqual(bar["xlabels"], [e["metric"] for e in entries])
        for entry, value in zip(entries, bar["values"]):
            self.assertNotEqual(entry["threshold"], 0.0, entry["metric"])
            self.assertAlmostEqual(
                headroom(entry["direction"], entry["threshold"], entry["current"]),
                value, places=1, msg=entry["metric"])

    def test_the_call_only_expense_guidance_is_named_and_not_published(self) -> None:
        notes = " ".join(self.payload["notes"])
        self.assertIn("只在业绩电话会上出现", notes)
        self.assertIn("16.95", notes)
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
                for key in ("bar", "line", "yoy", "actual", "lo", "hi"):
                    block = exhibit.get(key)
                    blocks.append(block.get("values") if isinstance(block, dict) else block)
                for key in ("series", "groups", "stacks"):
                    blocks.extend(b.get("values") for b in exhibit.get(key) or [])
                blocks.append(exhibit.get("net"))
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
        self.assertIn(" · ".join(entry["headline_metrics"]), home)

    def test_the_shell_links_the_payload_by_content_hash(self) -> None:
        shell = (ROOT / "cme" / "index.html").read_text(encoding="utf-8")
        sources = re.findall(r'<script src="\.\./([^"?]+)(\?v=([0-9a-f]+))?"', shell)
        self.assertEqual([name for name, _, _ in sources],
                         ["data/roster.js", "data/cme.js",
                          "assets/charts.js", "assets/page.js"])
        for name, _, digest in sources:
            expected = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()[:8]
            self.assertEqual(digest, expected, name)


if __name__ == "__main__":
    unittest.main()
