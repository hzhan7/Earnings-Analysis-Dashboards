"""Checks for the AMZN page.

Four things here can break silently on a quarter roll, and each one has a test:

* the three segments must still sum to the consolidated statement, and the seven
  product lines to total net sales -- both series are stitched from two document
  types (10-Q segment notes for Q1–Q3, the Q4 press release for the fiscal
  fourth), so a mis-stitch shows up as a sum that no longer closes;
* the quarterly values must still add to the filed year, within the ±1
  rounding the rest of this repo already lives with;
* the guided record must still be paired guide-to-actual on the *right*
  quarter -- the whole first section is worthless if a release's Outlook block
  ever gets matched to the quarter it reports rather than the one it guides;
* the two-leg decomposition must remain an identity rather than an
  approximation, because the page says in as many words that it is one.

The adjusted figures the thresholds settle on are pinned too: the page argues
from ex-one-off margins that the company never prints, so the arithmetic behind
them has to be reproducible from the audit tables.

Rolling the page is a data edit, so nothing below names a quarter or a count:
lengths are read from the series, the quarter's figures from `_checks`
(`AmznChecksTest`), and every sentence that states a record is tested against
a counterexample (`AmznRollTest`).
"""

from __future__ import annotations

import copy
import json
import math
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.all import build_all, roster_payload  # noqa: E402
from build.board import headroom  # noqa: E402
from build.amzn import build_payload  # noqa: E402


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


def quarter_key(period: str) -> str:
    quarter, year = period.split()
    return f"{year}{quarter}"


def next_quarter(period: str) -> str:
    quarter, year = period.split()
    number = int(quarter[1])
    return f"Q1 {int(year) + 1}" if number == 4 else f"Q{number + 1} {year}"


def published_text(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


class AmznDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "amzn.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]
        cls.by_section = {
            section["id"]: section["exhibits"] for section in cls.payload["sections"]
        }
        cls.q = cls.source["quarterly_usd_m"]
        cls.segments = cls.source["segments_usd_m"]
        cls.lines = cls.source["product_lines_usd_m"]
        cls.guide = cls.source["quarterly_guidance_history"]

    # ── the series itself ────────────────────────────────────────────────────
    def test_twelve_quarter_base_backs_every_yoy(self) -> None:
        self.assertEqual(len(self.source["periods"]), 12)
        for name, values in self.q.items():
            if not isinstance(values, list):
                continue
            self.assertEqual(len(values), 12, name)
            self.assertTrue(all(math.isfinite(value) for value in values), name)

    def test_segments_sum_to_the_consolidated_statement(self) -> None:
        """Segment revenue and segment operating income are reported figures, not
        derived ones, so a quarter where they stop adding up means a row was
        stitched from the wrong filing."""
        by_period = dict(zip(self.source["periods"], range(12)))
        for index, period in enumerate(self.segments["periods"]):
            revenue = (
                self.segments["na_revenue"][index]
                + self.segments["intl_revenue"][index]
                + self.segments["aws_revenue"][index]
            )
            income = (
                self.segments["na_operating_income"][index]
                + self.segments["intl_operating_income"][index]
                + self.segments["aws_operating_income"][index]
            )
            if period in by_period:
                slot = by_period[period]
                self.assertEqual(revenue, self.q["revenue_total"][slot], period)
                self.assertEqual(income, self.q["operating_income"][slot], period)
            lines = sum(
                self.lines[name][index]
                for name in ("online_stores", "physical_stores",
                             "third_party_seller_services", "advertising_services",
                             "subscription_services", "aws", "other")
                if self.lines[name][index] is not None
            )
            self.assertEqual(lines, revenue, f"{period} product lines")

    def test_income_statement_identity_holds_each_quarter(self) -> None:
        """Operating income plus total non-operating income is income before
        taxes; the payload names the non-operating line for what it is, so this
        is the check that the naming stayed honest. The snapshot's columns are
        (a year ago, last quarter, this quarter), and the builder refuses any
        other order."""
        snapshot = self.source["current_snapshot"]
        periods = self.source["periods"]
        self.assertEqual(snapshot["columns"], [periods[-5], periods[-2], periods[-1]])
        for slot, index in ((0, -5), (1, -2), (2, -1)):
            self.assertEqual(
                self.q["operating_income"][index] + self.q["total_non_operating_income"][index],
                snapshot["pre_tax_income_usd_m"][slot],
            )

    def test_net_capex_is_gross_minus_proceeds(self) -> None:
        """The page plots gross purchases in the cross-company table and net
        capex against the threshold; conflating the two would move the current
        quarter by more than a billion dollars."""
        for index, period in enumerate(self.source["periods"]):
            self.assertEqual(
                self.q["purchases_of_property_and_equipment"][index]
                - self.q["proceeds_from_pe_sales_and_incentives"][index],
                self.q["net_capex"][index],
                period,
            )

    def test_quarterly_series_reconcile_with_the_full_year(self) -> None:
        """Four quarters must add to the filed year. Companies round each
        quarter and each year independently, so ±1 US$M is the intended state
        and anything wider is a real error.

        The totals below were read from the 10-K income statements by hand; the
        series' own `annual_filed_usd_m` block (which the page's reconciliation
        sentence is computed from) was read from the XBRL facts. The two
        readings have to agree, and every year the series has four quarters for
        has to reconcile against the block, on all five long lines."""
        long = self.source["long_history"]
        by_quarter = dict(zip(long["quarters"], long["revenue_usd_m"]))
        income = dict(zip(long["quarters"], long["operating_income_usd_m"]))
        filed = {
            2021: (469822, 24879),
            2022: (513983, 12248),
            2023: (574785, 36852),
            2024: (637959, 68593),
            2025: (716924, 79975),
        }
        annual = long["annual_filed_usd_m"]
        for year, (revenue_total, income_total) in filed.items():
            quarters = [f"{year}Q{n}" for n in (1, 2, 3, 4)]
            self.assertLessEqual(
                abs(sum(by_quarter[q] for q in quarters) - revenue_total), 1, year)
            self.assertLessEqual(
                abs(sum(income[q] for q in quarters) - income_total), 1, year)
            at = annual["years"].index(year)
            self.assertEqual(annual["revenue_usd_m"][at], revenue_total, year)
            self.assertEqual(annual["operating_income_usd_m"][at], income_total, year)
        checked = 0
        for key in ("revenue_usd_m", "operating_income_usd_m", "operating_cash_flow_usd_m",
                    "capital_expenditures_usd_m", "depreciation_and_amortization_usd_m"):
            cells = dict(zip(long["quarters"], long[key]))
            for year, total in zip(annual["years"], annual[key]):
                values = [cells.get(f"{year}Q{n}") for n in (1, 2, 3, 4)]
                if None in values:
                    continue
                with self.subTest(line=key, year=year):
                    self.assertLessEqual(abs(sum(values) - total), 1)
                checked += 1
        self.assertGreater(checked, 0)

    def test_long_history_agrees_with_the_reviewed_quarters(self) -> None:
        long = self.source["long_history"]
        quarters = long["quarters"]
        self.assertEqual(quarters[-1], quarter_key(self.source["periods"][-1]))
        for previous, current in zip(quarters, quarters[1:]):
            year, number = int(previous[:4]), int(previous[-1])
            expected = f"{year + 1}Q1" if number == 4 else f"{year}Q{number + 1}"
            self.assertEqual(current, expected)
        for name, values in long.items():
            if isinstance(values, list):
                self.assertEqual(len(values), len(quarters), name)
        by_quarter = dict(zip(quarters, long["revenue_usd_m"]))
        capex = dict(zip(quarters, long["capital_expenditures_usd_m"]))
        for index, period in enumerate(self.source["periods"]):
            key = quarter_key(period)
            self.assertEqual(by_quarter[key], self.q["revenue_total"][index], period)
            self.assertEqual(
                capex[key], self.q["purchases_of_property_and_equipment"][index], period)

    def test_undisclosed_quarters_stay_empty(self) -> None:
        """Holes are disclosed, not filled.

        Capital expenditure now starts a full year later than it used to, and
        the reason is a basis break rather than a missing filing: Amazon's 2016
        cash-flow statements print one *net* line (after proceeds from sales and
        incentives) and only from 2017 do they split gross from proceeds. The
        four 2016 cells this series used to carry were the net measure sitting
        under a gross heading, and 2016Q4 was worse still -- the restated annual
        gross minus the old-basis nine-month net, two different quantities.
        Quarterly gross for 2016 does not exist in any filing, so the cells are
        empty and the net figures live in their own block with their sources.
        """
        long = self.source["long_history"]
        first = long["quarters"].index(long["capex_first_reported"])
        self.assertEqual(long["capex_first_reported"], "2017Q1")
        self.assertEqual(long["capital_expenditures_usd_m"][:first], [None] * 4)
        basis = long["capital_expenditures_basis"]
        self.assertEqual(basis["starts"], "2017Q1")
        self.assertEqual(len(basis["net_2016_usd_m"]), 4)
        # The net figures are kept because they are real, and checked because
        # they are the thing that was previously mistaken for gross.
        self.assertAlmostEqual(sum(basis["net_2016_usd_m"]), 6736.0, places=6)
        self.assertTrue(
            all(value is not None for value in long["capital_expenditures_usd_m"][first:]))
        lease_first = long["quarters"].index(long["finance_lease_first_reported"])
        self.assertIsNone(long["finance_lease_principal_usd_m"][lease_first - 1])
        self.assertTrue(
            all(value is not None for value in long["finance_lease_principal_usd_m"][lease_first:]))
        ads_first = self.lines["periods"].index(self.lines["advertising_first_reported"])
        self.assertIsNone(self.lines["advertising_services"][ads_first - 1])

    # ── the guided record ────────────────────────────────────────────────────
    def test_guidance_record_is_paired_on_the_guided_quarter(self) -> None:
        """Each release guides the quarter *after* the one it reports. Pairing a
        range with the quarter its own release covers would shift the entire
        record by one and still look plausible."""
        quarters = self.guide["quarters"]
        for name, values in self.guide.items():
            if name in ("provenance", "format_notes", "backfill_note_2016_2017"):
                continue
            if isinstance(values, list):
                self.assertEqual(len(values), len(quarters), name)
        order = [(int(q.split()[1]), int(q.split()[0][1])) for q in quarters]
        self.assertEqual(order, sorted(order), "guided quarters are not consecutive")
        for previous, current in zip(order, order[1:]):
            self.assertEqual(current[0] * 4 + current[1], previous[0] * 4 + previous[1] + 1)
        self.assertEqual(quarters[-1], next_quarter(self.source["periods"][-1]))
        self.assertIsNone(self.guide["actual_net_sales_bn"][-1])
        self.assertIsNone(self.guide["actual_operating_income_bn"][-1])

        # The actuals must equal the quarterly series wherever the windows meet.
        by_period = dict(zip(self.source["periods"], self.q["revenue_total"]))
        income = dict(zip(self.source["periods"], self.q["operating_income"]))
        checked = 0
        for index, period in enumerate(quarters):
            if period not in by_period:
                continue
            self.assertAlmostEqual(
                self.guide["actual_net_sales_bn"][index], by_period[period] / 1000, places=3)
            self.assertAlmostEqual(
                self.guide["actual_operating_income_bn"][index], income[period] / 1000, places=3)
            checked += 1
        self.assertEqual(checked, len(self.source["periods"]))

    def test_the_record_titles_follow_the_record(self) -> None:
        """The page's headline claim about the guided record: each band's title
        says the bottom was never broken exactly when no finished quarter came
        in below its range, and the audit table agrees row by row."""
        bands = [ex for ex in self.by_section["settled"] if ex["kind"] == "range_band"]
        self.assertEqual(len(bands), 2)
        for chart, low_key, actual_key in (
                (bands[0], "net_sales_low_bn", "actual_net_sales_bn"),
                (bands[1], "operating_income_low_bn", "actual_operating_income_bn")):
            missed = sum(1 for low, actual in zip(self.guide[low_key], self.guide[actual_key])
                         if actual is not None and actual < low)
            with self.subTest(chart=chart["title"]):
                self.assertEqual("没有一季跌破下限" in chart["title"], missed == 0)

    def test_beat_decomposition_is_an_identity(self) -> None:
        """`actual − guided midpoint = revenue leg + margin leg`, exactly. The
        chart's note claims this is not an approximation, so the sum has to
        close to floating-point noise, not to a tolerance."""
        legs = next(ex for ex in self.by_section["settled"] if "两条腿" in ex["title"])
        revenue_leg = legs["groups"][0]["values"]
        margin_leg = legs["groups"][1]["values"]
        finished = [
            index for index, value in enumerate(self.guide["actual_net_sales_bn"])
            if value is not None
        ]
        self.assertEqual(len(revenue_leg), len(finished))
        for slot, index in enumerate(finished):
            guided_sales = (self.guide["net_sales_low_bn"][index]
                            + self.guide["net_sales_high_bn"][index]) / 2
            guided_income = (self.guide["operating_income_low_bn"][index]
                             + self.guide["operating_income_high_bn"][index]) / 2
            beat = self.guide["actual_operating_income_bn"][index] - guided_income
            self.assertAlmostEqual(
                revenue_leg[slot] + margin_leg[slot], beat, places=5,
                msg=f"{self.guide['quarters'][index]} legs do not close on the beat",
            )
            self.assertGreater(guided_sales, 0)

    # ── the adjusted figures the thresholds settle on ────────────────────────
    def test_adjusted_margins_match_the_filed_one_off_amounts(self) -> None:
        """Every ex-one-off margin quoted on the page is (reported − filed
        amount) / reported revenue, using the 10-Q figures rather than the
        call's approximations."""
        one_off = self.source["one_off_items"]
        aws_adjusted = (
            (self.segments["aws_operating_income"][-1] - one_off["energy_derivative_gain_usd_m"])
            / self.segments["aws_revenue"][-1] * 100
        )
        aws_prior_year = (
            self.segments["aws_operating_income"][-5] / self.segments["aws_revenue"][-5] * 100
        )
        # The reason the page prefers the 10-Q's single-quarter figure over the
        # call's round number: it lands within a few basis points of the change
        # management itself quoted.
        self.assertAlmostEqual(
            (aws_adjusted - aws_prior_year) * 100,
            one_off["management_ex_derivative_margin_bp"],
            delta=10,
        )
        na_adjusted = (
            (self.segments["na_operating_income"][-1] - one_off["tariff_refund_usd_m"])
            / self.segments["na_revenue"][-1] * 100
        )
        expected = {"AWS 分部经营利润率": aws_adjusted, "北美分部经营利润率": na_adjusted}
        checked = 0
        for entry in self.source["next_kpi"]["quantified"]:
            if entry["metric"] in expected:
                self.assertAlmostEqual(entry["current"], expected[entry["metric"]], places=1)
                checked += 1
        self.assertGreater(checked, 0)

    def test_settled_thresholds_carry_both_lines(self) -> None:
        """Last quarter's settings had a risk line and a bull line, and the page
        shows both. Dropping either would turn an all-safe risk read into the
        whole story, which is exactly the reading the page argues against."""
        entries = self.source["prior_kpi_settlement"]["quantified"]
        for entry in entries:
            for field in ("threshold", "actual", "bull_threshold", "bull_actual", "unit"):
                self.assertIn(field, entry, entry["metric"])
        settled = self.by_section["settled"]
        risk = next(ex for ex in settled if ex["title"].startswith("上季") and "风险线" in ex["title"])
        bull = next(ex for ex in settled if ex["title"].startswith("换成多头确认线"))
        self.assertEqual(
            risk["values"],
            [round(headroom(e["direction"], e["threshold"], e["actual"]), 1) for e in entries],
        )
        self.assertEqual(
            bull["values"],
            [round(headroom(e["direction"], e["bull_threshold"], e["bull_actual"]), 1)
             for e in entries],
        )
        missed = sum(1 for e in entries
                     if headroom(e["direction"], e["bull_threshold"], e["bull_actual"]) < 0)
        self.assertEqual(sum(1 for value in bull["values"] if value < 0), missed)
        self.assertIn(f"{len(entries) - missed} / {len(entries)} 条兑现", bull["title"])

    def test_headroom_bars_reproduce_the_next_quarter_thresholds(self) -> None:
        entries = self.source["next_kpi"]["quantified"]
        chart = self.by_section["next_quarter"][0]
        self.assertEqual(
            chart["values"],
            [round(headroom(e["direction"], e["threshold"], e["current"]), 1) for e in entries],
        )
        self.assertEqual(chart["xlabels"], [entry["metric"] for entry in entries])

    def test_every_tracked_metric_with_a_series_gets_its_own_chart(self) -> None:
        """A metric left out of the per-metric charts has to be named in the
        overview's source note, so the omission is visible."""
        overview = self.by_section["next_quarter"][0]
        drawn = {ex["title"].split("：")[0] for ex in self.by_section["next_quarter"][1:]}
        for entry in self.source["next_kpi"]["quantified"]:
            self.assertIn(entry["metric"], drawn, entry["metric"])
        for item in (self.source["next_kpi"].get("excluded_from_chart", [])
                     + self.source["next_kpi"].get("disclosure_gated", [])):
            self.assertIn(item["short"], overview["src_extra"])

    # ── the disclosed cash-flow series ───────────────────────────────────────
    def test_free_cash_flow_series_is_disclosed_not_derived(self) -> None:
        """All three trailing series are company figures. The page corrects the
        local note with them, so they must be internally consistent, and the
        title says "deeper" exactly when an earlier quarter was deeper."""
        cash = self.source["cash_flow_disclosed"]
        self.assertEqual(cash["periods"][-1], self.source["periods"][-1])
        for name, values in cash.items():
            if isinstance(values, list) and name not in ("definition_changes",):
                self.assertEqual(len(values), len(cash["periods"]), name)
        for index, period in enumerate(cash["periods"]):
            self.assertEqual(
                cash["operating_cash_flow_ttm"][index] - cash["net_capex_ttm"][index],
                cash["free_cash_flow_ttm"][index],
                period,
            )
        latest = cash["free_cash_flow_ttm"][-1]
        chart = next(ex for ex in self.by_section["quarter_highlights"]
                     if ex["kind"] == "diverging_bars")
        self.assertEqual("更深" in chart["title"],
                         latest < 0 and min(cash["free_cash_flow_ttm"]) < latest)

    # ── page shape and boundary ──────────────────────────────────────────────
    def test_page_is_chart_led(self) -> None:
        self.assertGreaterEqual(len(self.exhibits), 20)
        self.assertEqual(self.payload["summary"]["blocks"], [])
        for exhibit in self.exhibits:
            self.assertTrue(exhibit.get("note"), exhibit["title"])
            self.assertNotIn("{EX_", exhibit.get("note", ""), exhibit["title"])
            self.assertNotIn("{EX_", exhibit["title"])
            # Chart notes are innerHTML: markdown asterisks would print literally.
            self.assertNotIn("**", exhibit.get("note", ""), exhibit["title"])

    def test_section_order_matches_how_the_note_is_used(self) -> None:
        self.assertEqual(
            [section["id"] for section in self.payload["sections"]],
            ["settled", "quarter_highlights", "next_quarter", "routine"],
        )
        self.assertEqual([ex["n"] for ex in self.exhibits],
                         list(range(2, 2 + len(self.exhibits))))

    def test_audit_tables_back_every_derived_exhibit(self) -> None:
        tables = self.payload["tables"]
        first = len(self.exhibits) + 2
        self.assertEqual([table["n"] for table in tables],
                         list(range(first, first + len(tables))))
        self.assertIn("AI capex", tables[-1]["title"])
        guided = next(t for t in tables if "指引与实际逐季对照" in t["title"])
        self.assertEqual(len(guided["rows"]), len(self.guide["quarters"]))
        self.assertEqual(guided["rows"][-1][2], "—")
        for column, low_key, actual_key in ((3, "net_sales_low_bn", "actual_net_sales_bn"),
                                            (6, "operating_income_low_bn", "actual_operating_income_bn")):
            missed = [actual is not None and actual < low
                      for low, actual in zip(self.guide[low_key], self.guide[actual_key])]
            self.assertEqual([row[column] == "跌破下限" for row in guided["rows"]], missed)

    def test_amzn_is_in_the_cross_page_capex_table(self) -> None:
        """AMZN is the largest capex spender of the four, so its absence would
        understate every row of the shared table."""
        table = next(t for t in self.payload["tables"] if "AI capex" in t["title"])
        self.assertEqual(table["headers"][1], "AMZN 现金 CapEx")
        capex = dict(zip(self.source["periods"],
                         self.q["purchases_of_property_and_equipment"]))
        for row in table["rows"]:
            if row[0] in capex:
                self.assertEqual(row[1], f"${capex[row[0]]:,.0f}M", row[0])

    def test_market_expectation_is_labelled_and_unattributed(self) -> None:
        expectation = self.source["market_expectation"]
        self.assertIn("市场预期", expectation["label"])
        self.assertEqual(expectation["as_of"], self.payload["latest"]["release_date"])
        text = json.dumps(self.payload, ensure_ascii=False).lower()
        for broker in ("bloomberg", "visible alpha", "factset", "s&p global",
                       "marketbeat", "seeking alpha", "jpmorgan", "morgan stanley",
                       "goldman", "barclays", "evercore", "baird", "wells fargo",
                       "oppenheimer", "wolfe", "loop capital", "moffettnathanson",
                       "td cowen"):
            self.assertNotIn(broker, text, broker)
        # 目标价 / 评级 / 估值 are deliberately not checked here: they appear in
        # the page's own boundary statement, exactly as they do on every other
        # page, so a substring test on them fires on a clean tree. What must
        # never appear is a position instruction or a valuation multiple carried
        # over from the local note.
        for banned in ("加仓", "减仓", "买入", "卖出", "止损", "ev/revenue",
                       "clean p/e", "sotp", "re-rating"):
            self.assertNotIn(banned, text, banned)

    def test_sources_are_official_http_links(self) -> None:
        allowed_hosts = {"ir.aboutamazon.com", "www.sec.gov"}
        for source in self.payload["source_links"]:
            parsed = urlparse(source["url"])
            self.assertEqual(parsed.scheme, "https")
            self.assertIn(parsed.hostname, allowed_hosts)

    def test_published_payload_roster_and_shell(self) -> None:
        self.assertEqual(js_payload(ROOT / "data" / "amzn.js", "window.DASH"), self.payload)
        roster = js_payload(ROOT / "data" / "roster.js", "window.ROSTER")
        self.assertEqual(roster, roster_payload(build_all()))
        entry = next(item for item in roster["items"] if item["slug"] == "amzn")
        self.assertEqual(entry["latest_label"], self.payload["latest"]["disclosed_period_label"])
        self.assertEqual(entry["release_date"], self.payload["latest"]["release_date"])
        self.assertEqual(entry["group"], "internet")
        shell = (ROOT / "amzn" / "index.html").read_text(encoding="utf-8")
        self.assertIn("../data/amzn.js", shell)
        self.assertNotIn("../data/googl.js", shell)

    def test_home_page_carries_the_new_company(self) -> None:
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="amzn/"', home)
        self.assertIn(self.payload["latest"]["release_date"], home)
        self.assertIn(self.payload["latest"]["disclosed_period_label"], home)

    def test_public_files_exclude_private_and_broker_material(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [
                ROOT / "series" / "amzn.json",
                ROOT / "data" / "amzn.js",
                ROOT / "amzn" / "index.html",
            ]
        ).lower()
        for forbidden in [
            "/users/",
            "/library/cloudstorage/",
            "onedrive",
            "obsidian",
            "seeking alpha",
            "visible alpha",
            "consensus",
            ".pdf",
        ]:
            self.assertNotIn(forbidden, text, forbidden)


STAMPED = ("current_snapshot", "one_off_items", "other_income_story", "backlog_concentration",
           "guidance", "calendar_shift", "market_expectation", "prior_kpi_settlement", "next_kpi",
           "quarter_story", "local_note_errata")


class AmznChecksTest(unittest.TestCase):
    """The page's quarter against a record keyed separately from the filing.

    `_checks` is typed once per quarter from the earnings release and the 10-Q,
    with the place each figure was read from. It is not copied from the arrays
    and the builder never reads it (`test_data_only_roll`). Rolling a quarter
    re-keys `_checks`; this class does not change.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "amzn.json").read_text(encoding="utf-8"))
        cls.checks = cls.source["_checks"]
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]
        cls.q = cls.source["quarterly_usd_m"]

    def test_the_page_names_the_checked_quarter(self) -> None:
        self.assertIn(self.checks["period"], self.payload["title"])
        self.assertIn(f"截至 {self.checks['period_end']}", self.payload["subtitle"])
        self.assertIn(f"发布 {self.checks['release_date']}", self.payload["subtitle"])
        self.assertEqual(self.source["periods"][-1], self.checks["period"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        c, q = self.checks, self.q
        for key, check in (("revenue_total", "revenue_usd_m"),
                           ("operating_income", "operating_income_usd_m"),
                           ("net_income", "net_income_usd_m"),
                           ("operating_cash_flow", "operating_cash_flow_usd_m"),
                           ("purchases_of_property_and_equipment",
                            "purchases_of_property_and_equipment_usd_m"),
                           ("proceeds_from_pe_sales_and_incentives",
                            "proceeds_from_property_and_equipment_sales_and_incentives_usd_m")):
            with self.subTest(line=key):
                self.assertEqual(q[key][-1], c[check])
        self.assertEqual(q["revenue_total"][-5], c["revenue_year_ago_usd_m"])
        snapshot = self.source["current_snapshot"]
        self.assertEqual(snapshot["pre_tax_income_usd_m"][-1], c["income_before_income_taxes_usd_m"])
        self.assertEqual(snapshot["other_income_expense_net_usd_m"][-1], c["other_income_expense_net_usd_m"])
        self.assertEqual(snapshot["diluted_eps_usd"][-1], c["diluted_eps_usd"])
        self.assertEqual(snapshot["aws_growth_ex_fx_pct"][-1], c["aws_growth_printed_pct"])
        self.assertEqual(self.source["cash_flow_disclosed"]["free_cash_flow_ttm"][-1],
                         c["free_cash_flow_ttm_usd_m"])
        segments = self.source["segments_usd_m"]
        for key, value in c["segments_usd_m"].items():
            with self.subTest(segment=key):
                self.assertEqual(segments[key][-1], value)
        self.assertEqual(self.source["product_lines_usd_m"]["advertising_services"][-1],
                         c["advertising_services_usd_m"])
        self.assertEqual(self.source["aws_backlog"]["level_usd_bn"][-1],
                         c["commitments_not_yet_recognized_usd_bn"])
        guide = self.source["quarterly_guidance_history"]
        forward = c["next_quarter"]
        self.assertEqual(guide["quarters"][-1], forward["quarter"])
        self.assertEqual([guide["net_sales_low_bn"][-1], guide["net_sales_high_bn"][-1]],
                         forward["net_sales_usd_bn"])
        self.assertEqual([guide["operating_income_low_bn"][-1], guide["operating_income_high_bn"][-1]],
                         forward["operating_income_usd_bn"])
        self.assertEqual((guide["fx_bps"][-1], guide["fx_direction"][-1]),
                         (forward["fx_bps_unfavorable"], "unfavorable"))
        one_off = self.source["one_off_items"]
        self.assertEqual(one_off["tariff_refund_usd_m"], c["one_off_items_usd_m"]["tariff_refund"])
        self.assertEqual(one_off["energy_derivative_gain_usd_m"],
                         c["one_off_items_usd_m"]["energy_derivative_gain"])

    def test_computed_figures_round_to_what_the_release_prints(self) -> None:
        c, q = self.checks, self.q
        segments = self.source["segments_usd_m"]
        self.assertEqual(round((q["revenue_total"][-1] / q["revenue_total"][-5] - 1) * 100),
                         c["revenue_growth_printed_pct"])
        self.assertEqual(round(q["operating_income"][-1] / q["revenue_total"][-1] * 100, 1),
                         c["operating_margin_printed_pct"])
        for segment, printed in c["segment_margin_printed_pct"].items():
            with self.subTest(segment=segment):
                self.assertEqual(
                    round(segments[f"{segment}_operating_income"][-1]
                          / segments[f"{segment}_revenue"][-1] * 100, 1), printed)
        # The release's 37% is growth excluding FX; the reported-dollar growth
        # rounds to the same figure this quarter, and the page prints both.
        self.assertEqual(round((segments["aws_revenue"][-1] / segments["aws_revenue"][-5] - 1) * 100),
                         c["aws_growth_printed_pct"])

    def test_the_page_prints_the_checked_figures(self) -> None:
        c = self.checks
        aws = next(ex for ex in self.exhibits if ex["kind"] == "bar_line")
        self.assertIn(f"AWS 收入 US${c['segments_usd_m']['aws_revenue'] / 1000:.1f}B", aws["title"])
        self.assertIn(f"US${c['diluted_eps_usd']:.2f} 的摊薄每股收益", self.payload["headline"])
        fcf = c["free_cash_flow_ttm_usd_m"]
        self.assertIn(f"{'−' if fcf < 0 else ''}US${abs(fcf) / 1000:.1f}B", self.payload["headline"])
        self.assertIn(f"公司披露的固定汇率口径为 {c['aws_growth_printed_pct']}%", aws["note"])
        self.assertIn(f"US${c['commitments_not_yet_recognized_usd_bn']:.0f}B", self.payload["brief"])

    def test_every_threshold_value_matches_the_series(self) -> None:
        """Each typed `actual` / `current` against the arithmetic that should
        produce it. The one-off-adjusted margins are recomputed from the filed
        one-off amounts, not from the call's round numbers."""
        q, segments = self.q, self.source["segments_usd_m"]
        one_off = self.source["one_off_items"]
        backlog = self.source["aws_backlog"]["level_usd_bn"]
        aws = self.source["long_history"]["aws_revenue_usd_m"]
        expected = {
            "AWS backlog 环比增速": (backlog[-1] / backlog[-2] - 1) * 100,
            "AWS backlog 单季净增": backlog[-1] - backlog[-2],
            "AWS 收入同比": (segments["aws_revenue"][-1] / segments["aws_revenue"][-5] - 1) * 100,
            "AWS 环比收入增量": (aws[-1] - aws[-2]) / 1000,
            "集团单季经营利润": q["operating_income"][-1] / 1000,
            "集团经营利润率": q["operating_income"][-1] / q["revenue_total"][-1] * 100,
            "TTM 自由现金流": self.source["cash_flow_disclosed"]["free_cash_flow_ttm"][-1] / 1000,
            "单季现金 CapEx（净额，超过即偏离隐含节奏）": q["net_capex"][-1] / 1000,
            "北美分部经营利润率": (segments["na_operating_income"][-1] - one_off["tariff_refund_usd_m"])
                               / segments["na_revenue"][-1] * 100,
        }
        reported_aws_margin = segments["aws_operating_income"][-1] / segments["aws_revenue"][-1] * 100
        adjusted_aws_margin = ((segments["aws_operating_income"][-1] - one_off["energy_derivative_gain_usd_m"])
                               / segments["aws_revenue"][-1] * 100)
        checked = 0
        for entry in self.source["next_kpi"]["quantified"]:
            value = adjusted_aws_margin if entry["metric"] == "AWS 分部经营利润率" else expected.get(entry["metric"])
            if value is not None:
                with self.subTest(metric=entry["metric"]):
                    self.assertAlmostEqual(entry["current"], value, places=1)
                checked += 1
        for entry in self.source["prior_kpi_settlement"]["quantified"]:
            value = reported_aws_margin if entry["metric"] == "AWS 分部经营利润率" else expected.get(entry["metric"])
            if value is not None:
                with self.subTest(prior=entry["metric"]):
                    self.assertAlmostEqual(entry["actual"], value, places=1)
                checked += 1
        self.assertGreater(checked, 0)


class AmznRollTest(unittest.TestCase):
    """What a quarter roll can and cannot get past."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "amzn.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)

    def test_a_block_stamped_with_another_quarter_stops_the_build(self) -> None:
        for key in STAMPED:
            stale = copy.deepcopy(self.source)
            stale[key]["period"] = "Q1 1999"
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    build_payload(stale)
        stale = copy.deepcopy(self.source)
        stale["current_snapshot"]["columns"] = list(reversed(stale["current_snapshot"]["columns"]))
        with self.assertRaisesRegex(ValueError, "columns"):
            build_payload(stale)

    def test_a_missing_quarter_block_leaves_its_part_out(self) -> None:
        bare = copy.deepcopy(self.source)
        for key in STAMPED:
            del bare[key]
        payload = build_payload(bare)
        self.assertEqual([s["id"] for s in payload["sections"]],
                         ["settled", "quarter_highlights", "routine"])
        text = published_text(payload)
        for gone in ("Anthropic", "Prime Day", "市场预期的 US$", "风险线", "一次性经营项",
                     "本地稿", "约 US$600M", "Other income", "拒绝披露", "OpenAI"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, text)
        # The guided record and the long series do not depend on any of them.
        self.assertEqual(len(payload["sections"][0]["exhibits"]), 6)

    def test_the_quarter_release_must_be_in_the_sources(self) -> None:
        missing = copy.deepcopy(self.source)
        period = missing["periods"][-1]
        missing["sources"] = [s for s in missing["sources"]
                              if not s["label"].startswith(f"{period} 业绩 8-K")]
        with self.assertRaisesRegex(ValueError, "sources"):
            build_payload(missing)

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        before = published_text(self.payload)
        cases = []

        sales_miss = copy.deepcopy(self.source)
        sales_miss["quarterly_guidance_history"]["actual_net_sales_bn"][0] = 20.0
        cases.append(("a quarter below the sales range", sales_miss,
                      ["收入一次都没有跌破过区间下限", "同样一次都没有跌破下限"]))

        loose = copy.deepcopy(self.source)
        guide = loose["quarterly_guidance_history"]
        finished = [i for i, v in enumerate(guide["actual_net_sales_bn"]) if v is not None]
        for index in finished[-20:]:
            guide["actual_net_sales_bn"][index] = round(guide["actual_net_sales_bn"][index] * 1.05, 3)
        cases.append(("sales guidance far from the midpoint", loose, ["收入指引其实<b>相当准</b>"]))

        retail = copy.deepcopy(self.source)
        retail["product_lines_usd_m"]["online_stores"][-1] = 64000.0
        retail["product_lines_usd_m"]["third_party_seller_services"][-1] = 42000.0
        cases.append(("the store lines slow down", retail,
                      ["四条零售线里有三条在加速", "在线商店与第三方卖家两条同期也在加速"]))

        backlog = copy.deepcopy(self.source)
        backlog["aws_backlog"]["level_usd_bn"][-3] = 60.0
        cases.append(("an earlier, larger backlog addition", backlog, ["是其中最大的一次"]))

        still_negative = copy.deepcopy(self.source)
        cash = still_negative["cash_flow_disclosed"]
        cash["free_cash_flow_ttm"][-2] = -1000.0
        cash["net_capex_ttm"][-2] = cash["operating_cash_flow_ttm"][-2] + 1000.0
        cases.append(("free cash flow was already negative", still_negative,
                      ["TTM 自由现金流转为", "转负的自由现金流"]))

        big_step = copy.deepcopy(self.source)
        long = big_step["long_history"]
        at = long["quarters"].index("2018Q4")
        long["aws_revenue_usd_m"][at] += 6000
        cases.append(("an earlier, larger AWS increment", big_step,
                      [" 创纪录", "是此前最大单季增量的", "是此前纪录的"]))

        earlier_peak = copy.deepcopy(self.source)
        long = earlier_peak["long_history"]
        at = long["quarters"].index("2021Q3")
        long["capital_expenditures_usd_m"][at] = 40000
        cases.append(("an earlier capex-intensity peak", earlier_peak,
                      ["已越过上一轮周期的高点", "是上一轮高点的 1.9 倍"]))

        one_year_less = copy.deepcopy(self.source)
        long = one_year_less["long_history"]
        at = long["quarters"].index("2016Q3")
        long["aws_operating_income_usd_m"][at] = 500
        cases.append(("one fewer quarter above 100%", one_year_less, ["（Q3'16、Q2'17–Q3'17"]))

        broken_run = copy.deepcopy(self.source)
        long = broken_run["long_history"]
        long["revenue_usd_m"][long["quarters"].index("2026Q1")] = 200000
        cases.append(("this quarter's growth fell", broken_run,
                      ["是第三段连升三季以上的回升", "是三段里最长的"]))

        breached = copy.deepcopy(self.source)
        for entry in breached["prior_kpi_settlement"]["quantified"]:
            if entry["metric"] == "AWS 收入同比":
                entry["actual"] = 20.0
        cases.append(("a settled risk line breached", breached,
                      ["一条都没有被触发", "六条全部安全"]))

        crossing = copy.deepcopy(self.source)
        for entry in crossing["next_kpi"]["quantified"]:
            if entry["metric"] == "北美分部经营利润率":
                entry["current"] = 6.5
        cases.append(("a next-quarter line already crossed", crossing, ["当前值全部在安全侧"]))

        small_refund = copy.deepcopy(self.source)
        small_refund["one_off_items"]["tariff_refund_usd_m"] = 10
        cases.append(("a refund too small to flip North America", small_refund,
                      ["负经营杠杆", "剔除后北美的方向就变了"]))

        costs_only = copy.deepcopy(self.source)
        guide = costs_only["quarterly_guidance_history"]
        guide["actual_operating_income_bn"][guide["quarters"].index("Q1 2020")] = 5.0
        cases.append(("no quarter led by revenue", costs_only, ["例外是 Q1'20"]))

        for name, series, claims in cases:
            after = published_text(build_payload(series))
            for claim in claims:
                with self.subTest(case=name, claim=claim):
                    self.assertIn(claim, before)
                    self.assertNotIn(claim, after)

        costs_only_text = published_text(build_payload(costs_only))
        self.assertIn("无论正负，都来自成本而不是需求", costs_only_text)
        self.assertNotIn("无论正负，都来自成本而不是需求", before)
        retail_text = published_text(build_payload(retail))
        self.assertIn("是四条零售线里唯一在加速的", retail_text)

    def test_the_counted_sentences_follow_the_record(self) -> None:
        text = published_text(self.payload)
        for present in ("42 个已完结季，收入一次都没有跌破过区间下限；上穿上限 23 次、落在区间内 19 次",
                        "20 季里 12 季的偏离在 ±2% 以内",
                        "有八季的区间下限是负数或零",
                        "42 季里 41 季来自成本而不是需求",
                        "四条零售线里有三条在加速",
                        "净增共 33 个可比点",
                        "US$1.83–US$1.90",
                        "43 个被指引季（Q1 2016 – Q3 2026）",
                        "起点是 Q1'17",
                        "资本开支有申报值的 38 季里"):
            with self.subTest(present=present):
                self.assertIn(present, text)
        for gone in ("九年 36", "37 个被指引季", "公司只在最近四个季度", "唯一在加速",
                     "起点是 Q2'16", "本站唯一", "US$1.83–US$1.92", "十几分之一",
                     "只有这一条留在三十季", "从 2019Q1 起才有", "分国家收入（公司不披露）",
                     "高点的两倍", "绝大多数季度", "**"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, text)


if __name__ == "__main__":
    unittest.main()
