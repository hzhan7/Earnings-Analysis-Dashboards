"""Checks for the IBKR page.

Four things here are worth pinning beyond the usual shape checks.

First, **the two derived revenue lines**. Interactive Brokers prints "Other fees
and services" and "Other income" in its income statement, but neither is a
separate XBRL fact in the companyfacts API -- the page recovers them by
subtraction (revenue from contracts with customers minus commissions, and total
net revenues minus the other three legs). Both subtractions have to reproduce
the printed figures exactly, in every quarter, or the page is publishing an
estimate while presenting it as a filed number. That is a test rather than a
comment.

Second, **the structural break at 1Q2020**. The company renamed its per-order
commission metric, and started publishing period-end customer credits, at
exactly that quarter. Those series therefore begin there rather than being
carried back, and the holes must be exactly the quarters before it -- not one
fewer, not one more, and not filled in.

Third, **the absence of any per-share series**. The 4-for-1 split declared
2025-04-15 restated only those quarters that later served as a comparative, so
the EPS facts on the public interface are two bases spliced together. The page
publishes net income available for common stockholders in dollars instead, and
this file asserts that no exhibit anywhere plots a per-share line -- because the
failure mode is someone adding one later and it drawing a cliff that looks like
a business event.

Fourth, **the Up-C wedge**. Most of this company's consolidated net income does
not belong to its listed shareholders, and every profit figure on the page has
to distinguish the two. The identity net income − noncontrolling = common is
checked in every quarter.

**Rolling a quarter edits the series and nothing else, including this file.**
Nothing below names the page's quarter or its figures: the window is asserted
as "Q1 2016 to the last quarter, without a gap", and the quarter's own numbers
are held to `_checks`, a separate reading of that quarter's release
(`IbkrChecksTest`). The sentences that state a record, a streak or an "all of
them" are tested by making the series disagree and asserting the sentence goes.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
import unittest
from pathlib import Path
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.all import ENTRIES, GROUPS, build_all, roster_payload  # noqa: E402
from build.board import cn_count, headroom  # noqa: E402
from build.ibkr import build_payload, compact_period, headline_metrics  # noqa: E402

FIRST_QUARTER = "Q1 2016"
BREAK_QUARTER = "Q1 2020"


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


def quarters_between(first: str, last: str) -> list[str]:
    quarter, year = int(first[1]), int(first[-4:])
    out = []
    while True:
        out.append(f"Q{quarter} {year}")
        if out[-1] == last:
            return out
        quarter += 1
        if quarter == 5:
            year, quarter = year + 1, 1
        if year > 2100:
            raise ValueError(f"{last} does not follow {first}")


def published_text(payload: dict) -> str:
    """Every string a reader can see, in one blob."""
    return json.dumps({key: payload[key] for key in
                       ("title", "subtitle", "headline", "brief", "sections", "notes")},
                      ensure_ascii=False)


class IbkrDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads(
            (ROOT / "series" / "ibkr.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for section in cls.payload["sections"]
                        for ex in section["exhibits"]]
        cls.financials = cls.source["financials_usd_m"]
        cls.operating = cls.source["operating"]
        cls.nim = cls.source["nim"]
        cls.periods = cls.source["periods"]

    # ── source series ───────────────────────────────────────────────────────

    def test_the_nim_components_are_the_conformed_basis(self) -> None:
        """Recategorisations move dollars between components, so every sum holds.

        Interactive Brokers conformed prior periods twice -- negative-rate
        currency components out of segregated funds (2Q2018 and 4Q2018 releases),
        U.S. Treasury and reverse-repo components into other net interest income
        (3Q2018 release, naming 1Q2017-2Q2018 as affected) -- and the "FDIC
        sweeps" component enters average interest-earning assets at 1Q2018,
        restating the four 2017 quarters.

        None of it changes total net interest income or the overall margin, which
        is why the page carried the original figures for years with nothing
        failing: the transfers are between components, so the identities this
        file already asserts are satisfied on either basis. The only assertion
        that can see it is a value pin against the later release that reprints
        the quarter, which is what this is.

        The four 2016 quarters are deliberately not pinned: no document reprints
        them after either change, so there is nothing to pin them to. That is
        recorded in `_2016_not_confirmed_note` and asserted here, so the gap
        stays visible rather than being closed by assumption.
        """
        nim, periods = self.nim, self.source["periods"]
        conformed_yield = {"Q1 2017": 0.64, "Q2 2017": 0.78, "Q3 2017": 0.99,
                           "Q4 2017": 1.01, "Q1 2018": 1.37, "Q2 2018": 1.46,
                           "Q3 2018": 1.73}
        for label, value in conformed_yield.items():
            with self.subTest(period=label):
                self.assertEqual(nim["yield_segregated_pct"][periods.index(label)], value)
        conformed_assets = {"Q1 2017": 50705.0, "Q2 2017": 53001.0,
                            "Q3 2017": 55489.0, "Q4 2017": 57387.0}
        for label, value in conformed_assets.items():
            with self.subTest(period=label):
                self.assertEqual(nim["avg_earning_assets_usd_m"][periods.index(label)], value)
        self.assertEqual(nim["nim_pct"][periods.index("Q4 2017")], 1.43)

        note = nim["_2016_not_confirmed_note"]
        self.assertIn("1Q2017", note)
        self.assertIn("2016", note)
        for label in ("Q1 2016", "Q2 2016", "Q3 2016", "Q4 2016"):
            with self.subTest(period=label):
                self.assertIsNotNone(nim["yield_segregated_pct"][periods.index(label)],
                                     "kept on the original basis, with the boundary declared")

    def test_the_base_starts_in_2016_and_names_its_own_holes(self) -> None:
        """Twelve quarters were added in front, and two lines stay empty there.

        `other_fees_and_services` is defined here as the ASC 606 "revenue from
        contracts with customers by major type of service" total minus
        commissions. IBKR adopted ASC 606 on 2018-01-01 using the modified
        retrospective method, so that table does not exist for 2016-2017 and
        there is no same-basis figure to read. `other_income` is defined as
        non-interest income minus commissions minus that line, so it goes with
        it. Every other income-statement line is complete over the whole window.
        """
        quarters = len(self.periods)
        self.assertEqual(self.periods[0], FIRST_QUARTER)
        self.assertEqual(self.periods[-1], self.source["_checks"]["period"])
        asc606 = self.periods.index("Q1 2018")
        gated = {"other_fees_and_services", "other_income"}
        for name, values in self.financials.items():
            with self.subTest(line=name):
                self.assertEqual(len(values), quarters)
                if name in gated:
                    self.assertEqual(values[:asc606], [None] * asc606, name)
                    self.assertTrue(all(v is not None for v in values[asc606:]), name)
                else:
                    self.assertTrue(all(v is not None for v in values), name)
        for name in gated:
            self.assertIn(f"financials_usd_m.{name}",
                          self.source["not_backfilled_2016_2018"])

    def test_calendar_quarters_run_without_a_gap(self) -> None:
        """IBKR's fiscal year is the calendar year, so no label needs remapping."""
        self.assertEqual(self.periods, quarters_between(FIRST_QUARTER, self.periods[-1]))
        for key in ("quarter_keys", "basis"):
            self.assertEqual(len(self.source[key]), len(self.periods), key)
        self.assertEqual(self.source["quarter_keys"],
                         [f"{p[-4:]}{p[:2]}" for p in self.periods])

    def test_only_fiscal_fourth_quarters_are_differenced(self) -> None:
        """Q1-Q3 come from the 10-Q's own three-month column; Q4 has no 10-Q."""
        for period, basis in zip(self.periods, self.source["basis"]):
            with self.subTest(period=period):
                self.assertEqual(
                    basis,
                    "fy_minus_9m" if period.startswith("Q4") else "filed_3m")

    # ── income-statement identities ─────────────────────────────────────────

    def test_revenue_legs_add_to_total_net_revenues(self) -> None:
        """commissions + other fees + other income + net interest = total.

        Two of the four legs only exist from ASC 606 on, so the identity is
        asserted exactly where all four exist -- and the quarters where it
        cannot be asserted are pinned as exactly the pre-ASC-606 ones, so a
        future hole cannot hide inside the same exemption.
        """
        checked = 0
        for index, period in enumerate(self.periods):
            parts = [self.financials[name][index] for name in
                     ("commissions", "other_fees_and_services",
                      "other_income", "net_interest_income")]
            if any(value is None for value in parts):
                self.assertLess(period[-4:], "2018", period)
                continue
            checked += 1
            with self.subTest(period=period):
                self.assertAlmostEqual(
                    sum(parts), self.financials["total_net_revenues"][index], places=6)
        self.assertEqual(checked, len(self.periods) - self.periods.index("Q1 2018"))
        # The notes state how many quarters the two derived lines close in.
        derived = [note for note in self.payload["notes"] if "两条恒等式" in note]
        self.assertEqual(len(derived), 1)
        self.assertIn(f"两行都有值的全部{cn_count(checked)}季逐季成立", derived[0])

    def test_net_interest_is_the_two_filed_legs_subtracted(self) -> None:
        for index, period in enumerate(self.periods):
            with self.subTest(period=period):
                self.assertAlmostEqual(
                    self.financials["interest_income"][index]
                    - self.financials["interest_expense"][index],
                    self.financials["net_interest_income"][index], places=6)

    def test_income_statement_identity_holds_each_quarter(self) -> None:
        """revenue − non-interest expense = pretax, and pretax − tax = net income.

        A broker's income statement has a single expense subtotal below total net
        revenues, so both identities are exact rather than approximate.
        """
        for index, period in enumerate(self.periods):
            with self.subTest(period=period):
                self.assertAlmostEqual(
                    self.financials["total_net_revenues"][index]
                    - self.financials["total_non_interest_expenses"][index],
                    self.financials["pretax_income"][index], places=6)
                self.assertAlmostEqual(
                    self.financials["pretax_income"][index]
                    - self.financials["income_tax"][index],
                    self.financials["net_income"][index], places=6)

    def test_upc_split_closes_every_quarter(self) -> None:
        for index, period in enumerate(self.periods):
            with self.subTest(period=period):
                self.assertAlmostEqual(
                    self.financials["net_income"][index]
                    - self.financials["net_income_noncontrolling"][index],
                    self.financials["net_income_common"][index], places=6)

    def test_most_of_the_profit_belongs_to_the_noncontrolling_holders(self) -> None:
        """The wedge is the point: it has never been below two thirds."""
        shares = [nci / net * 100 for nci, net
                  in zip(self.financials["net_income_noncontrolling"],
                         self.financials["net_income"])]
        self.assertGreater(min(shares), 66.0)
        self.assertLess(shares[-1], shares[0], "the wedge should be narrowing")

    # ── the quarter's figures against the release, via `_checks` ────────────

    def test_latest_quarter_matches_the_printed_release(self) -> None:
        """Every line of the quarter's income statement, read separately."""
        for line, (this_quarter, _year_ago) in \
                self.source["_checks"]["income_statement_usd_m"].items():
            with self.subTest(line=line):
                self.assertAlmostEqual(self.financials[line][-1], this_quarter, places=6)

    def test_year_ago_quarter_matches_the_same_release(self) -> None:
        """The comparative column of the same document, so one source checks two."""
        for line, (_this_quarter, year_ago) in \
                self.source["_checks"]["income_statement_usd_m"].items():
            with self.subTest(line=line):
                self.assertAlmostEqual(self.financials[line][-5], year_ago, places=6)

    def test_latest_operating_metrics_match_the_release(self) -> None:
        checks = self.source["_checks"]
        for key in ("accounts_thousands", "customer_equity_usd_bn", "darts_thousands"):
            with self.subTest(metric=key):
                self.assertAlmostEqual(self.operating[key][-1], checks[key]["this_quarter"])
                self.assertAlmostEqual(self.operating[key][-5], checks[key]["year_ago"])
                self.assertAlmostEqual(self.operating[key][-2], checks[key]["prior_quarter"])
        commission = checks["commission_per_order_usd"]
        self.assertAlmostEqual(self.operating["commission_per_order_usd"][-1],
                               commission["this_quarter"])
        self.assertAlmostEqual(self.operating["commission_per_order_usd"][-5],
                               commission["year_ago"])
        self.assertAlmostEqual(self.operating["customer_credits_usd_bn"][-1],
                               checks["customer_credits_usd_bn"])
        self.assertAlmostEqual(self.operating["customer_margin_loans_usd_bn"][-1],
                               checks["customer_margin_loans_usd_bn"])

    def test_latest_net_interest_margin_table_matches_the_release(self) -> None:
        # The comparative column is the second of each pair, which the parser
        # reached by a different path than the quarter's own.
        for key, (this_quarter, year_ago) in \
                self.source["_checks"]["net_interest_margin_table"].items():
            with self.subTest(line=key):
                self.assertAlmostEqual(self.nim[key][-1], this_quarter)
                self.assertAlmostEqual(self.nim[key][-5], year_ago)

    def test_average_earning_assets_only_ever_grow(self) -> None:
        """A parser that grabbed the wrong row of that table produced dips.

        The subtotal is read backwards from the next block header, and the
        number of columns differs between a first-quarter release (two) and
        every other release (four). Reading a fixed four columns silently
        returned a *component* row as the subtotal in every Q1, which showed up
        as this series collapsing by an order of magnitude four times over.
        Monotonic growth is the cheap invariant that catches it.
        """
        values = self.nim["avg_earning_assets_usd_m"]
        self.assertTrue(all(value is not None for value in values))
        for index in range(1, len(values)):
            with self.subTest(period=self.periods[index]):
                self.assertGreater(values[index], values[index - 1] * 0.9)

    # ── structural breaks ───────────────────────────────────────────────────

    def test_the_three_gated_series_start_exactly_at_the_rename(self) -> None:
        """1Q2020 is where the company renamed the metric and began the balances.

        The holes must be the quarters before it exactly: filling them would
        splice two different definitions, and starting later would throw away
        filed data.
        """
        start = self.periods.index(BREAK_QUARTER)
        for name in ("commission_per_order_usd", "customer_credits_usd_bn"):
            values = self.operating[name]
            with self.subTest(series=name):
                self.assertTrue(all(value is None for value in values[:start]))
                self.assertTrue(all(value is not None for value in values[start:]))
                self.assertEqual(sum(1 for v in values if v is None), start)
            self.assertIn(f"operating.{name}", self.source["not_backfilled_2016_2018"])
        self.assertEqual(self.operating["commission_metric_from"], BREAK_QUARTER)

    def test_customer_margin_loans_is_one_line_under_two_names(self) -> None:
        """It used to have a one-year hole, and the hole was a rename.

        IBKR printed this balance as "customer debits" through 2019 and renamed
        it "Customer margin loans" in the 1Q2020 release. The definition did not
        change -- the 2020 releases' year-ago comparatives reproduce the 2019
        figures -- so the four 2019 quarters are the same series and were empty
        only because the earlier name was never read. Unlike the two series
        above, this one runs the whole record, and the page's prose must say so
        rather than repeat the "from 2020Q1" of the other two.
        """
        values = self.operating["customer_margin_loans_usd_bn"]
        self.assertEqual(len(values), len(self.periods))
        self.assertTrue(all(value is not None for value in values))
        for period, value in zip(self.periods, values):
            if period.endswith("2019"):
                self.assertGreater(value, 20.0, period)
        # Every place the page says where this line starts says it runs the
        # whole window, under the old name first.
        places = [note for note in self.payload["notes"] if "客户保证金贷款" in note]
        places += [ex["note"] for ex in self.exhibits if ex["title"].startswith("客户保证金贷款")]
        self.assertTrue(places)
        for text in places:
            with self.subTest(text=text[:30]):
                self.assertIn("跑满全窗口", text)
                self.assertIn("customer debits", text)
                self.assertNotIn(f"{BREAK_QUARTER[-4:]}{BREAK_QUARTER[:2]} 起算", text.split("客户保证金贷款", 1)[-1])

    def test_both_commission_charts_explain_their_short_axis(self) -> None:
        """Every chart that draws this series explains where it starts.

        A reader can arrive at either the long chart or the threshold one first,
        so the definition change has to be on each rather than only on the one
        that happens to come later.
        """
        charts = [ex for ex in self.exhibits if "每笔已清算订单佣金" in ex["title"]]
        tracked = any(entry["metric"] == "每笔已清算订单佣金"
                      for entry in (self.source.get("next_kpi") or {}).get("quantified", []))
        self.assertEqual(len(charts), 1 + tracked)
        for chart in charts:
            with self.subTest(exhibit=chart["n"]):
                self.assertIn(BREAK_QUARTER, chart["note"])
                self.assertIn("Commission per DART", chart["note"])

    def test_no_exhibit_publishes_a_per_share_series(self) -> None:
        """The split restated only the quarters that became comparatives.

        Plotting the public EPS facts as one line would draw a step at the
        quarter the restatement stops, which reads as a business event and is
        not one. The page carries dollars of net income instead.
        """
        for exhibit in self.exhibits:
            names = []
            for key in ("series", "stacks", "groups"):
                names += [item.get("name", "") for item in exhibit.get(key, [])]
            if isinstance(exhibit.get("line"), dict):
                names.append(exhibit["line"].get("name", ""))
            for name in names:
                with self.subTest(exhibit=exhibit["title"][:40], series=name):
                    self.assertNotIn("EPS", name.upper())
                    self.assertNotIn("每股", name)

    def test_the_notes_explain_why_there_is_no_eps_line(self) -> None:
        notes = "\n".join(self.payload["notes"])
        self.assertIn("4 拆 1", notes)
        self.assertIn("2025-04-15", notes)

    # ── the missing guidance record ─────────────────────────────────────────

    def test_the_page_publishes_no_guidance_record_and_says_why(self) -> None:
        self.assertIsNone(self.payload["guidance"])
        notes = "\n".join(self.payload["notes"])
        self.assertIn("从不在申报文件里给季度数字指引", notes)
        settled = next(section for section in self.payload["sections"]
                       if section["id"] == "settled")
        first = self.periods[-1] == self.source["meta"]["coverage_start"]
        # "First coverage" is true of one quarter only; on every other quarter
        # it must be gone from the page, not just from this description.
        self.assertEqual("首次覆盖" in settled["description"], first)
        self.assertEqual("首次覆盖" in published_text(self.payload), first)
        for exhibit in self.exhibits:
            with self.subTest(exhibit=exhibit["title"][:40]):
                self.assertNotEqual(exhibit["kind"], "range_band",
                                    "a guidance band implies a record this filer never filed")

    # ── section three ───────────────────────────────────────────────────────

    def test_headroom_bars_agree_with_the_thresholds_they_draw(self) -> None:
        entries = (self.source.get("next_kpi") or {}).get("quantified", [])
        charts = [ex for ex in self.exhibits
                  if ex["kind"] == "diverging_bars" and ex["title"].startswith("下季")]
        self.assertEqual(len(charts), 1 if entries else 0)
        if not entries:
            return
        chart = charts[0]
        self.assertEqual(chart["xlabels"], [entry["metric"] for entry in entries])
        for entry, drawn in zip(entries, chart["values"]):
            with self.subTest(metric=entry["metric"]):
                self.assertAlmostEqual(
                    drawn,
                    round(headroom(entry["direction"], entry["threshold"],
                                   entry["current"]), 1),
                    places=6)

    def test_every_threshold_current_value_matches_the_series(self) -> None:
        """A threshold whose `current` drifted from the series it is drawn against
        would put the bar and the line in different places on the same page."""
        entries = {entry["metric"]: entry
                   for entry in (self.source.get("next_kpi") or {}).get("quantified", [])}
        accounts = self.operating["accounts_thousands"]
        expected = {
            "净息差 NIM": self.nim["nim_pct"][-1],
            "账户数环比增速": (accounts[-1] / accounts[-2] - 1) * 100,
            "每笔已清算订单佣金": self.operating["commission_per_order_usd"][-1],
            "非息费用 / 总净收入": (self.financials["total_non_interest_expenses"][-1]
                            / self.financials["total_net_revenues"][-1] * 100),
            "少数股东占净利润比": (self.financials["net_income_noncontrolling"][-1]
                          / self.financials["net_income"][-1] * 100),
            "客户保证金贷款": self.operating["customer_margin_loans_usd_bn"][-1],
        }
        self.assertTrue(set(entries) <= set(expected), set(entries) - set(expected))
        for metric, entry in entries.items():
            with self.subTest(metric=metric):
                self.assertAlmostEqual(entry["current"], expected[metric], places=1)

    def test_every_threshold_gets_its_own_history_chart(self) -> None:
        """The overview bar says which line broke; only the per-metric chart says
        how it got there. Nothing here is a single unplottable point."""
        thresholds = {entry["threshold"]
                      for entry in (self.source.get("next_kpi") or {}).get("quantified", [])}
        drawn = set()
        for exhibit in self.exhibits:
            if exhibit["kind"] != "lines":
                continue
            for series in exhibit.get("series", []):
                values = [value for value in series["values"] if value is not None]
                if len(set(values)) == 1 and values:
                    drawn.add(values[0])
        self.assertTrue(thresholds <= drawn, thresholds - drawn)

    def test_a_threshold_sentence_restates_the_threshold_it_sits_under(self) -> None:
        """The note's words for a threshold are the quarter's, the number is the entry's.

        Where a threshold's reasoning restates the threshold, the series writes a
        placeholder and the builder fills it; move the threshold and every
        sentence that names it must move with it.
        """
        moved = copy.deepcopy(self.source)
        entry = next(e for e in moved["next_kpi"]["quantified"]
                     if e["metric"] == "非息费用 / 总净收入")
        entry["threshold"] = 31.0
        chart = next(ex for section in build_payload(moved)["sections"]
                     for ex in section["exhibits"] if ex["title"].startswith("非息费用 / 总净收入"))
        self.assertIn("距 31.0% 的阈值还有", chart["note"])
        self.assertIn("越过 31% 不必然", chart["note"])
        self.assertNotIn("25", chart["note"])

    # ── a roll edits the series and nothing else ────────────────────────────

    def test_quarter_blocks_refuse_to_publish_under_another_quarter(self) -> None:
        """Last quarter's thresholds or settlement under this quarter's label stop the build."""
        for key in ("next_kpi", "prior_kpi"):
            stale = copy.deepcopy(self.source)
            stale[key] = copy.deepcopy(self.source["next_kpi"])
            stale[key]["period"] = "Q1 1999"
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    build_payload(stale)
        stale = copy.deepcopy(self.source)
        label = f"IBKR {self.source['_checks']['company_label']} 业绩新闻稿"
        stale["sources"] = [s for s in stale["sources"] if not s["label"].startswith(label)]
        self.assertLess(len(stale["sources"]), len(self.source["sources"]))
        with self.assertRaisesRegex(ValueError, "sources"):
            build_payload(stale)

    def test_a_quarter_without_thresholds_leaves_them_out(self) -> None:
        """Absent, the one-quarter threshold block drops its charts and its table."""
        bare = copy.deepcopy(self.source)
        del bare["next_kpi"]
        payload = build_payload(bare)
        titles = [ex["title"] for s in payload["sections"] for ex in s["exhibits"]]
        self.assertFalse([t for t in titles if t.startswith("下季")])
        self.assertEqual(len(titles),
                         len(self.exhibits) - 1 - len(self.source["next_kpi"]["quantified"]))
        self.assertEqual(len(payload["tables"]), len(self.payload["tables"]) - 1)
        self.assertEqual([s["id"] for s in payload["sections"]],
                         [s["id"] for s in self.payload["sections"]])
        self.assertNotIn("第一组阈值", published_text(payload))

    def test_a_settlement_block_closes_last_quarters_thresholds(self) -> None:
        """From the second quarter on, section one settles what section three set.

        Built here from this quarter's own thresholds, re-stamped: the settlement
        chart comes first, its bars are this quarter's series values against
        those thresholds, and "first coverage" is gone from every part of the page.
        """
        rolled = copy.deepcopy(self.source)
        rolled["meta"]["coverage_start"] = "Q1 1999"
        rolled["prior_kpi"] = {
            "period": self.periods[-1],
            "quantified": [{key: entry[key] for key in ("metric", "direction", "threshold", "unit")}
                           for entry in self.source["next_kpi"]["quantified"]],
        }
        payload = build_payload(rolled)
        settled = next(s for s in payload["sections"] if s["id"] == "settled")
        first = settled["exhibits"][0]
        count = len(rolled["prior_kpi"]["quantified"])
        self.assertTrue(first["title"].startswith(f"上季 {count} 条阈值"))
        current = {e["metric"]: e["current"] for e in self.source["next_kpi"]["quantified"]}
        for metric, value in zip(first["xlabels"], first["values"]):
            entry = next(e for e in rolled["prior_kpi"]["quantified"] if e["metric"] == metric)
            with self.subTest(metric=metric):
                self.assertAlmostEqual(
                    value, headroom(entry["direction"], entry["threshold"], current[metric]),
                    delta=0.15)
        self.assertNotIn("首次覆盖", published_text(payload))
        self.assertIn("先结算上一份笔记留下的", settled["description"])

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        """Make the series disagree with each claim; the claim must leave the page."""
        def without(claims: tuple[str, ...], edit) -> None:
            changed = copy.deepcopy(self.source)
            edit(changed)
            before = published_text(self.payload)
            after = published_text(build_payload(changed))
            for claim in claims:
                with self.subTest(claim=claim):
                    self.assertIn(claim, before)
                    self.assertNotIn(claim, after)

        def one_account_dip(s):
            accounts = s["operating"]["accounts_thousands"]
            accounts[10] = accounts[9] - 1
        without(("账户数从未环比下滑",), one_account_dip)

        def lower_than_a_past_quarter(s):
            s["financials_usd_m"]["total_net_revenues"][-9] = \
                s["financials_usd_m"]["total_net_revenues"][-1] + 1
        without(("本季创纪录", "创纪录的总净收入", "的纪录是量堆出来的"), lower_than_a_past_quarter)

        def one_yield_up(s):
            s["nim"]["yield_credits_pct"][-1] = s["nim"]["yield_credits_pct"][-5] + 0.01
        without(("全线下行", "无一例外", "四条线没有一条在往上走", "四条利率线没有一条在往上走"),
                one_yield_up)

        def slower_darts(s):
            s["operating"]["darts_thousands"][-1] = s["operating"]["darts_thousands"][-5] * 1.05
        without(("客户端每一项都在爆发", "三项同比都在三成以上"), slower_darts)

        # "First coverage" is true of one quarter only -- the quarter of the
        # first note in the owner's vault. The page once printed it on a
        # quarter that already had two notes behind it, so the direction that
        # matters is the reverse one: absent on this page, present only when
        # the series says this quarter is the first.
        first = copy.deepcopy(self.source)
        first["meta"]["coverage_start"] = self.periods[-1]
        first_text = published_text(build_payload(first))
        for claim in ("首次覆盖", "第一组阈值"):
            with self.subTest(claim=claim):
                self.assertNotIn(claim, published_text(self.payload))
                self.assertIn(claim, first_text)

    def test_the_crossings_are_counted_from_the_series(self) -> None:
        """The revenue-mix note once said the lines crossed twice; it is recounted here."""
        revenue = self.financials["total_net_revenues"]
        commission_leads = [c / r > n / r for c, n, r in
                            zip(self.financials["commissions"],
                                self.financials["net_interest_income"], revenue)]
        crossings = sum(1 for a, b in zip(commission_leads, commission_leads[1:]) if a != b)
        stretches, start = [], 0
        for index in range(1, len(commission_leads) + 1):
            if index == len(commission_leads) or commission_leads[index] != commission_leads[start]:
                if commission_leads[start]:
                    stretches.append(index - start)
                start = index
        chart = next(ex for ex in self.exhibits if ex["title"].startswith("利率周期改写了收入结构"))
        self.assertIn(f"交叉过<b>{cn_count(crossings)}次</b>", chart["note"])
        self.assertIn(f"中间整整 {max(stretches)} 个季度", chart["note"])

    def test_accounts_are_printed_the_way_the_filer_rounds_them(self) -> None:
        """5,185 thousand is "5.19 million" in the release; float formatting says 5.18."""
        checks = self.source["_checks"]
        printed = checks["accounts_printed_millions"]
        self.assertIn(f"账户数 {printed} 百万", self.payload["headline"])
        self.assertIn(f"账户 {printed}M", headline_metrics(self.source))
        # Every accounts figure the page prints in millions is the decimal
        # half-up of the filed thousands -- the first quarter's 345 thousand
        # (0.345) falls into the same float trap as 5,185 does.
        long_chart = next(ex for ex in self.exhibits if ex["title"].startswith("账户数 "))
        first, last = (self.operating["accounts_thousands"][i] for i in (0, -1))
        half_up = [str((Decimal(str(v)) / 1000).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
                   for v in (first, last)]
        self.assertTrue(long_chart["title"].startswith(f"账户数 {half_up[0]} → {half_up[1]} 百万"),
                        long_chart["title"])
        self.assertEqual(half_up[1], printed)

    # ── payload shape ───────────────────────────────────────────────────────

    def test_exhibit_numbers_follow_render_order(self) -> None:
        numbers = [exhibit["n"] for exhibit in self.exhibits]
        self.assertEqual(numbers, list(range(2, 2 + len(numbers))))
        table_numbers = [table["n"] for table in self.payload["tables"]]
        self.assertEqual(
            table_numbers,
            list(range(numbers[-1] + 1, numbers[-1] + 1 + len(table_numbers))))

    def test_no_exhibit_reference_placeholder_survives(self) -> None:
        for exhibit in self.exhibits:
            for field in ("title", "note", "src_extra"):
                with self.subTest(exhibit=exhibit["title"][:40], field=field):
                    self.assertNotRegex(str(exhibit.get(field, "")), r"\{EX_[A-Z_]+\}")
                    self.assertNotRegex(str(exhibit.get(field, "")), r"\{(threshold|count)")

    def test_section_descriptions_carry_no_markup(self) -> None:
        """`page.js` escapes these two slots rather than parsing them."""
        for section in self.payload["sections"]:
            with self.subTest(section=section["id"]):
                self.assertNotIn("<", section["description"])
        for note in self.payload["notes"]:
            self.assertNotIn("<", note)

    def test_labels_are_calendar_quarters(self) -> None:
        self.assertEqual(compact_period("Q2 2026"), "Q2'26")
        metrics = [entry["metric"] for block in ("next_kpi", "prior_kpi")
                   for entry in (self.source.get(block) or {}).get("quantified", [])]
        for exhibit in self.exhibits:
            for label in exhibit.get("xlabels", []):
                if re.fullmatch(r"Q[1-4]'\d{2}", label):
                    continue
                self.assertIn(label, metrics)

    def test_sources_are_official_http_links(self) -> None:
        self.assertTrue(self.payload["source_links"])
        for link in self.payload["source_links"]:
            with self.subTest(url=link["url"]):
                parsed = urlparse(link["url"])
                self.assertEqual(parsed.scheme, "https")
                self.assertIn(parsed.netloc,
                              {"www.sec.gov", "www.interactivebrokers.com"})

    # ── registration in the shared files ────────────────────────────────────

    def test_the_roster_entry_names_a_group_that_exists(self) -> None:
        entry = next(item for item in ENTRIES if item["slug"] == "ibkr")
        self.assertEqual(entry["group"], "brokerage_wealth")
        keys = [group["key"] for group in GROUPS]
        self.assertIn("brokerage_wealth", keys)
        self.assertEqual(len(keys), len(set(keys)))
        roster = roster_payload(build_all())
        item = next(row for row in roster["items"] if row["slug"] == "ibkr")
        self.assertEqual(item["latest_label"],
                         self.payload["latest"]["disclosed_period_label"])
        self.assertEqual(item["release_date"],
                         self.payload["latest"]["release_date"])

    def test_published_payload_and_home_card(self) -> None:
        self.assertEqual(js_payload(ROOT / "data" / "ibkr.js", "window.DASH"),
                         self.payload)
        roster = js_payload(ROOT / "data" / "roster.js", "window.ROSTER")
        item = next(row for row in roster["items"] if row["slug"] == "ibkr")
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="ibkr/"', home)
        self.assertIn(item["latest_label"], home)
        self.assertIn(item["release_date"], home)
        self.assertIn("券商与财富管理", home)
        # Hand-written and read by nothing: count it, never increment it.
        self.assertIn(f'{len(roster["items"])} 家公司', home)
        self.assertEqual(home.count('class="hcard"'), len(roster["items"]))

    def test_the_shell_links_the_payload_by_content_hash(self) -> None:
        """Every `?v=` in the committed shell must be that file's CURRENT digest.

        This passes trivially in a tree that has just been rebuilt, because the
        build writes both files. What it actually guards is the *committed*
        pair: run against a `git archive` extract of the commit, a shell whose
        path was left out of the commit's explicit path list stamps the previous
        payload's digest and fails here.
        """
        shell = (ROOT / "ibkr" / "index.html").read_text(encoding="utf-8")
        self.assertIn("<title>IBKR Quarterly Results</title>", shell)
        sources = re.findall(r'<script src="\.\./([^"?]+)(?:\?v=([0-9a-f]+))?"', shell)
        self.assertEqual(
            [name for name, _ in sources],
            ["data/roster.js", "data/ibkr.js", "assets/charts.js", "assets/page.js"])
        for name, digest in sources:
            with self.subTest(script=name):
                self.assertTrue(digest, f"{name} is served without a cache-buster")
                expected = hashlib.sha256(
                    (ROOT / name).read_bytes()).hexdigest()[: len(digest)]
                self.assertEqual(digest, expected)

    def test_public_files_exclude_private_and_broker_material(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [ROOT / "series" / "ibkr.json",
                         ROOT / "data" / "ibkr.js",
                         ROOT / "ibkr" / "index.html"]
        ).lower()
        for forbidden in ["/users/", "/library/cloudstorage/", "onedrive",
                          "seeking alpha", "alphastreet", "factset", "bloomberg",
                          "yahoo finance", "target price", "price target",
                          "consensus", "谨慎多"]:
            with self.subTest(term=forbidden):
                self.assertNotIn(forbidden, text)
        compact = "".join(text.split())
        self.assertNotIn(":nan", compact)
        self.assertNotIn(":infinity", compact)
        self.assertNotIn(":-infinity", compact)


class IbkrChecksTest(unittest.TestCase):
    """The page's quarter against a record keyed separately from the filing.

    `_checks` in the series file is typed once per quarter from the earnings
    release itself, with the place in the document it was read from -- it is
    not copied out of the arrays, and the builder never reads it (asserted in
    `test_data_only_roll`). Every assertion here compares what the builder
    computed from the arrays with that separate reading, so a roll that
    misaligns a column, drops the new quarter or keeps last quarter's sentence
    fails here. Rolling a quarter re-keys `_checks`; this file does not change.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "ibkr.json").read_text(encoding="utf-8"))
        cls.checks = cls.source["_checks"]
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for section in cls.payload["sections"]
                        for ex in section["exhibits"]]

    def test_the_page_names_the_checked_quarter_both_ways(self) -> None:
        checks = self.checks
        self.assertIn(checks["period"], self.payload["title"])
        self.assertIn(f"截至 {checks['period_end']}", self.payload["subtitle"])
        self.assertIn(f"发布 {checks['release_date']}", self.payload["subtitle"])
        notes = "\n".join(self.payload["notes"])
        self.assertIn(f"本页的 {checks['period']} 就是公司所称的 {checks['company_label']}", notes)
        self.assertIn(f"IBKR {checks['company_label']} 业绩新闻稿", self.payload["source"])

    def test_the_headline_prints_the_checked_figures_the_way_the_release_does(self) -> None:
        """Every rate the page computes rounds to the one the release prints."""
        checks = self.checks
        headline = self.payload["headline"]
        income = checks["income_statement_usd_m"]
        self.assertIn(f"账户数 {checks['accounts_printed_millions']} 百万", headline)
        self.assertIn(f"客户权益 US${checks['customer_equity_usd_bn']['this_quarter']:,.1f}B",
                      headline)
        self.assertIn(f"总净收入 US${income['total_net_revenues'][0]:,.0f}M", headline)
        self.assertIn(f"而这 US${income['net_income'][0]:,.0f}M 净利润里，只有 "
                      f"US${income['net_income_common'][0]:,.0f}M", headline)
        printed = re.findall(r"同比 ([+−-]\d+\.\d)%", headline)
        self.assertEqual(len(printed), 3)
        for value, key in zip(printed, ("accounts", "customer_equity", "darts")):
            with self.subTest(metric=key):
                self.assertEqual(round(float(value.replace("−", "-"))),
                                 checks["printed_yoy_pct"][key])

    def test_the_charts_print_the_checked_figures(self) -> None:
        checks = self.checks
        nim = checks["net_interest_margin_table"]["nim_pct"]
        margin = next(ex for ex in self.exhibits if ex["title"].startswith("税前利润率"))
        self.assertEqual(round(float(re.match(r"税前利润率 (\d+\.\d)%", margin["title"]).group(1))),
                         checks["pretax_margin_printed_pct"])
        yields = next(ex for ex in self.exhibits if re.match(r"净息差 \d", ex["title"]))
        self.assertIn(f"净息差 {nim[0]:.2f}%，同比 {nim[0] - nim[1]:+.2f}pp", yields["title"])
        loans = next((ex for ex in self.exhibits if ex["title"].startswith("客户保证金贷款")), None)
        if loans is not None:
            match = re.search(r"本季 US\$([\d.]+)B，同比 ([+−-]\d+\.\d)%", loans["note"])
            self.assertEqual(float(match.group(1)), checks["customer_margin_loans_usd_bn"])
            self.assertEqual(round(float(match.group(2))),
                             checks["printed_yoy_pct"]["customer_margin_loans"])
        growth = next((ex for ex in self.exhibits if ex["title"].startswith("账户数环比增速")), None)
        if growth is not None:
            value = float(re.match(r"本季 (\d+\.\d+)%", growth["note"]).group(1))
            self.assertEqual(round(value), checks["printed_qoq_pct"]["accounts"])

    def test_the_card_prints_the_checked_figures(self) -> None:
        checks = self.checks
        revenue = checks["income_statement_usd_m"]["total_net_revenues"][0]
        self.assertEqual(headline_metrics(self.source), [
            f"Revenue ${revenue / 1000:.2f}B",
            f"NIM {checks['net_interest_margin_table']['nim_pct'][0]:.2f}%",
            f"账户 {checks['accounts_printed_millions']}M",
        ])


if __name__ == "__main__":
    unittest.main()
