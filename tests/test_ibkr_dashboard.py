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
commission metric, and started publishing period-end customer credits and margin
loans, at exactly that quarter. The three series therefore begin there rather
than being carried back, and the holes must be exactly the four 2019 quarters --
not three, not five, and not filled in.

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
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.all import ENTRIES, GROUPS, build_all, roster_payload  # noqa: E402
from build.board import headroom  # noqa: E402
from build.ibkr import build_payload, compact_period  # noqa: E402

QUARTERS = 42
BREAK_QUARTER = "Q1 2020"


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


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

    def test_the_base_is_forty_two_quarters_and_names_its_own_holes(self) -> None:
        """Twelve quarters were added in front, and two lines stay empty there.

        `other_fees_and_services` is defined here as the ASC 606 "revenue from
        contracts with customers by major type of service" total minus
        commissions. IBKR adopted ASC 606 on 2018-01-01 using the modified
        retrospective method, so that table does not exist for 2016-2017 and
        there is no same-basis figure to read. `other_income` is defined as
        non-interest income minus commissions minus that line, so it goes with
        it. Every other income-statement line is complete over all 42.
        """
        self.assertEqual(len(self.periods), QUARTERS)
        self.assertEqual(self.periods[0], "Q1 2016")
        self.assertEqual(self.periods[-1], "Q2 2026")
        asc606 = self.periods.index("Q1 2018")
        gated = {"other_fees_and_services", "other_income"}
        for name, values in self.financials.items():
            with self.subTest(line=name):
                self.assertEqual(len(values), QUARTERS)
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
        expected = []
        year, quarter = 2016, 1
        for _ in range(QUARTERS):
            expected.append(f"Q{quarter} {year}")
            quarter += 1
            if quarter == 5:
                year, quarter = year + 1, 1
        self.assertEqual(self.periods, expected)

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
        self.assertEqual(checked, QUARTERS - self.periods.index("Q1 2018"))

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

    # ── values pinned against the company's own printed release ─────────────

    def test_latest_quarter_matches_the_printed_release(self) -> None:
        """Every figure here is read off the 2Q2026 EX-99.1 income statement."""
        expected = {
            "total_net_revenues": 1896.0,
            "commissions": 673.0,
            "other_fees_and_services": 87.0,
            "other_income": 79.0,
            "interest_income": 2236.0,
            "interest_expense": 1179.0,
            "net_interest_income": 1057.0,
            "total_non_interest_expenses": 440.0,
            "employee_compensation": 182.0,
            "pretax_income": 1456.0,
            "income_tax": 118.0,
            "net_income": 1338.0,
            "net_income_noncontrolling": 1026.0,
            "net_income_common": 312.0,
        }
        for line, value in expected.items():
            with self.subTest(line=line):
                self.assertAlmostEqual(self.financials[line][-1], value, places=6)

    def test_year_ago_quarter_matches_the_same_release(self) -> None:
        """The comparative column of the same document, so one source checks two."""
        expected = {
            "total_net_revenues": 1480.0,
            "commissions": 516.0,
            "other_fees_and_services": 62.0,
            "other_income": 42.0,
            "net_interest_income": 860.0,
            "total_non_interest_expenses": 376.0,
            "pretax_income": 1104.0,
            "net_income": 1006.0,
            "net_income_noncontrolling": 782.0,
            "net_income_common": 224.0,
        }
        for line, value in expected.items():
            with self.subTest(line=line):
                self.assertAlmostEqual(self.financials[line][-5], value, places=6)

    def test_latest_operating_metrics_match_the_release(self) -> None:
        self.assertAlmostEqual(self.operating["accounts_thousands"][-1], 5185.0)
        self.assertAlmostEqual(self.operating["customer_equity_usd_bn"][-1], 930.3)
        self.assertAlmostEqual(self.operating["darts_thousands"][-1], 4824.0)
        self.assertAlmostEqual(self.operating["commission_per_order_usd"][-1], 2.64)
        self.assertAlmostEqual(self.operating["customer_credits_usd_bn"][-1], 182.4)
        self.assertAlmostEqual(
            self.operating["customer_margin_loans_usd_bn"][-1], 108.5)

    def test_latest_net_interest_margin_table_matches_the_release(self) -> None:
        self.assertAlmostEqual(self.nim["nim_pct"][-1], 1.93)
        self.assertAlmostEqual(self.nim["yield_segregated_pct"][-1], 3.32)
        self.assertAlmostEqual(self.nim["yield_margin_loans_pct"][-1], 4.10)
        self.assertAlmostEqual(self.nim["yield_credits_pct"][-1], 2.23)
        self.assertAlmostEqual(self.nim["avg_earning_assets_usd_m"][-1], 228615.0)
        # The comparative column, which the parser reached by a different path.
        self.assertAlmostEqual(self.nim["nim_pct"][-5], 2.07)
        self.assertAlmostEqual(self.nim["yield_margin_loans_pct"][-5], 4.67)
        self.assertAlmostEqual(self.nim["avg_earning_assets_usd_m"][-5], 166621.0)

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

        The holes must be the four 2019 quarters exactly: filling them would
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
        above, this one runs the whole record.
        """
        values = self.operating["customer_margin_loans_usd_bn"]
        self.assertEqual(len(values), QUARTERS)
        self.assertTrue(all(value is not None for value in values))
        for period, value in zip(self.periods, values):
            if period.endswith("2019"):
                self.assertGreater(value, 20.0, period)

    def test_both_commission_charts_explain_their_short_axis(self) -> None:
        """Two charts draw this series -- the threshold one and the long one.

        A reader can arrive at either first, so the definition change has to be
        on both rather than only on the one that happens to come later.
        """
        charts = [ex for ex in self.exhibits if "每笔已清算订单佣金" in ex["title"]]
        self.assertEqual(len(charts), 2)
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
        self.assertIn("首次覆盖", settled["description"])
        for exhibit in self.exhibits:
            with self.subTest(exhibit=exhibit["title"][:40]):
                self.assertNotEqual(exhibit["kind"], "range_band",
                                    "a guidance band implies a record this filer never filed")

    # ── section three ───────────────────────────────────────────────────────

    def test_headroom_bars_agree_with_the_thresholds_they_draw(self) -> None:
        entries = self.source["next_kpi"]["quantified"]
        chart = next(ex for ex in self.exhibits if ex["kind"] == "diverging_bars")
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
                   for entry in self.source["next_kpi"]["quantified"]}
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
        self.assertEqual(set(expected), set(entries))
        for metric, value in expected.items():
            with self.subTest(metric=metric):
                self.assertAlmostEqual(entries[metric]["current"], value, places=1)

    def test_every_threshold_gets_its_own_history_chart(self) -> None:
        """The overview bar says which line broke; only the per-metric chart says
        how it got there. Nothing here is a single unplottable point."""
        thresholds = {entry["threshold"]
                      for entry in self.source["next_kpi"]["quantified"]}
        drawn = set()
        for exhibit in self.exhibits:
            if exhibit["kind"] != "lines":
                continue
            for series in exhibit.get("series", []):
                values = [value for value in series["values"] if value is not None]
                if len(set(values)) == 1 and values:
                    drawn.add(values[0])
        self.assertTrue(thresholds <= drawn, thresholds - drawn)

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

    def test_section_descriptions_carry_no_markup(self) -> None:
        """`page.js` escapes these two slots rather than parsing them."""
        for section in self.payload["sections"]:
            with self.subTest(section=section["id"]):
                self.assertNotIn("<", section["description"])
        for note in self.payload["notes"]:
            self.assertNotIn("<", note)

    def test_labels_are_calendar_quarters(self) -> None:
        self.assertEqual(compact_period("Q2 2026"), "Q2'26")
        for exhibit in self.exhibits:
            for label in exhibit.get("xlabels", []):
                if re.fullmatch(r"Q[1-4]'\d{2}", label):
                    continue
                self.assertIn(label, [entry["metric"] for entry
                                      in self.source["next_kpi"]["quantified"]])

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


if __name__ == "__main__":
    unittest.main()
