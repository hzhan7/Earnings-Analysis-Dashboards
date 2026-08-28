"""Checks for the AMZN page.

Four things here can break silently on a quarter roll, and each one has a test:

* the three segments must still sum to the consolidated statement, and the seven
  product lines to total net sales -- both series are stitched from two document
  types (10-Q segment notes for Q1–Q3, the Q4 press release for the fiscal
  fourth), so a mis-stitch shows up as a sum that no longer closes;
* the twelve quarterly values must still add to the filed year, within the ±1
  rounding the rest of this repo already lives with;
* the guided record must still be paired guide-to-actual on the *right*
  quarter -- the whole first section is worthless if a release's Outlook block
  ever gets matched to the quarter it reports rather than the one it guides;
* the two-leg decomposition must remain an identity rather than an
  approximation, because the page says in as many words that it is one.

The adjusted figures the thresholds settle on are pinned too: the page argues
from ex-one-off margins that the company never prints, so the arithmetic behind
them has to be reproducible from the audit tables.
"""

from __future__ import annotations

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
        is the check that the naming stayed honest."""
        snapshot = self.source["current_snapshot"]
        for offset, slot in ((-2, -2), (-1, -1)):
            self.assertEqual(
                self.q["operating_income"][offset] + self.q["total_non_operating_income"][offset],
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
        snapshot = self.source["current_snapshot"]
        self.assertEqual(self.q["net_capex"][-1], snapshot["net_capex_usd_m"][-1])

    def test_quarterly_series_reconcile_with_the_full_year(self) -> None:
        """Four quarters must add to the filed year. Companies round each
        quarter and each year independently, so ±1 US$M is the intended state
        and anything wider is a real error."""
        long = self.source["long_history"]
        by_quarter = dict(zip(long["quarters"], long["revenue_usd_m"]))
        income = dict(zip(long["quarters"], long["operating_income_usd_m"]))
        # Filed annual totals, read from the 10-K income statements.
        filed = {
            2021: (469822, 24879),
            2022: (513983, 12248),
            2023: (574785, 36852),
            2024: (637959, 68593),
            2025: (716924, 79975),
        }
        for year, (revenue_total, income_total) in filed.items():
            quarters = [f"{year}Q{n}" for n in (1, 2, 3, 4)]
            self.assertLessEqual(
                abs(sum(by_quarter[q] for q in quarters) - revenue_total), 1, year)
            self.assertLessEqual(
                abs(sum(income[q] for q in quarters) - income_total), 1, year)

    def test_long_history_agrees_with_the_reviewed_quarters(self) -> None:
        long = self.source["long_history"]
        self.assertEqual(len(long["quarters"]), 42)
        by_quarter = dict(zip(long["quarters"], long["revenue_usd_m"]))
        capex = dict(zip(long["quarters"], long["capital_expenditures_usd_m"]))
        for index, period in enumerate(self.source["periods"]):
            quarter, year = period.split()
            key = f"{year}{quarter}"
            self.assertEqual(by_quarter[key], self.q["revenue_total"][index], period)
            self.assertEqual(
                capex[key], self.q["purchases_of_property_and_equipment"][index], period)

    def test_undisclosed_quarters_stay_empty(self) -> None:
        """Holes are disclosed, not filled: 2016Q1 has no filed quarterly capex
        or depreciation, and finance-lease principal begins with ASC 842."""
        long = self.source["long_history"]
        first = long["quarters"].index(long["capex_first_reported"])
        self.assertIsNone(long["capital_expenditures_usd_m"][first - 1])
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
        self.assertEqual(len(quarters), 37)
        for name, values in self.guide.items():
            if name in ("provenance", "format_notes"):
                continue
            if isinstance(values, list):
                self.assertEqual(len(values), 37, name)
        order = [(int(q.split()[1]), int(q.split()[0][1])) for q in quarters]
        self.assertEqual(order, sorted(order), "guided quarters are not consecutive")
        for previous, current in zip(order, order[1:]):
            self.assertEqual(current[0] * 4 + current[1], previous[0] * 4 + previous[1] + 1)
        self.assertEqual(quarters[-1], "Q3 2026")
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
        self.assertEqual(checked, 12)

    def test_the_record_never_broke_the_bottom_of_either_range(self) -> None:
        """The page's headline claim about the guided record, pinned. If a
        future quarter does miss, the title recomputes and this test is what
        makes that a deliberate edit rather than a silent one."""
        lows = zip(self.guide["net_sales_low_bn"], self.guide["actual_net_sales_bn"])
        self.assertTrue(all(actual >= low for low, actual in lows if actual is not None))
        lows = zip(self.guide["operating_income_low_bn"],
                   self.guide["actual_operating_income_bn"])
        self.assertTrue(all(actual >= low for low, actual in lows if actual is not None))
        settled = self.by_section["settled"]
        self.assertIn("没有一季跌破下限", settled[0]["title"])
        self.assertIn("没有一季跌破下限", settled[2]["title"])

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
        self.assertEqual(
            one_off["tariff_refund_usd_m"] + one_off["energy_derivative_gain_usd_m"],
            one_off["total_usd_m"],
        )
        aws_adjusted = (
            (self.segments["aws_operating_income"][-1] - one_off["energy_derivative_gain_usd_m"])
            / self.segments["aws_revenue"][-1] * 100
        )
        aws_prior_year = (
            self.segments["aws_operating_income"][-5] / self.segments["aws_revenue"][-5] * 100
        )
        # The reason the page prefers the 10-Q's US$551M over the call's
        # "about US$600M": it lands within a few basis points of the change
        # management itself quoted.
        self.assertAlmostEqual(
            (aws_adjusted - aws_prior_year) * 100,
            one_off["management_ex_derivative_margin_bp"],
            delta=10,
        )
        next_kpi = {entry["metric"]: entry for entry in self.source["next_kpi"]["quantified"]}
        self.assertAlmostEqual(next_kpi["AWS 分部经营利润率"]["current"], aws_adjusted, places=1)

        na_adjusted = (
            (self.segments["na_operating_income"][-1] - one_off["tariff_refund_usd_m"])
            / self.segments["na_revenue"][-1] * 100
        )
        self.assertAlmostEqual(next_kpi["北美分部经营利润率"]["current"], na_adjusted, places=1)

    def test_settled_thresholds_carry_both_lines(self) -> None:
        """Last quarter's settings had a risk line and a bull line, and the page
        shows both. Dropping either would turn a six-for-six risk read into the
        whole story, which is exactly the reading the page argues against."""
        for entry in self.source["prior_kpi_settlement"]["quantified"]:
            for field in ("threshold", "actual", "bull_threshold", "bull_actual", "unit"):
                self.assertIn(field, entry, entry["metric"])
        risk = self.by_section["settled"][6]
        bull = self.by_section["settled"][7]
        entries = self.source["prior_kpi_settlement"]["quantified"]
        self.assertEqual(
            risk["values"],
            [round(headroom(e["direction"], e["threshold"], e["actual"]), 1) for e in entries],
        )
        self.assertEqual(
            bull["values"],
            [round(headroom(e["direction"], e["bull_threshold"], e["bull_actual"]), 1)
             for e in entries],
        )
        self.assertTrue(all(value >= 0 for value in risk["values"]))
        self.assertEqual(sum(1 for value in bull["values"] if value < 0), 1)

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
        excluded = " ".join(self.source["next_kpi"].get("excluded_from_chart", []))
        overview = self.by_section["next_quarter"][0]
        drawn = {ex["title"].split("：")[0] for ex in self.by_section["next_quarter"][1:]}
        for entry in self.source["next_kpi"]["quantified"]:
            self.assertIn(entry["metric"], drawn, entry["metric"])
        self.assertIn("Prime Day", excluded + overview["src_extra"])

    # ── the disclosed cash-flow series ───────────────────────────────────────
    def test_free_cash_flow_series_is_disclosed_not_derived(self) -> None:
        """All three trailing series are company figures. The page corrects the
        local note with them, so they must be internally consistent."""
        cash = self.source["cash_flow_disclosed"]
        self.assertEqual(len(cash["periods"]), 30)
        for index, period in enumerate(cash["periods"]):
            self.assertEqual(
                cash["operating_cash_flow_ttm"][index] - cash["net_capex_ttm"][index],
                cash["free_cash_flow_ttm"][index],
                period,
            )
        # The correction itself: this quarter is not the first negative one.
        latest = cash["free_cash_flow_ttm"][-1]
        self.assertLess(latest, 0)
        self.assertLess(min(cash["free_cash_flow_ttm"]), latest)
        chart = next(ex for ex in self.by_section["quarter_highlights"]
                     if ex["kind"] == "diverging_bars")
        self.assertIn("更深", chart["title"])

    # ── page shape and boundary ──────────────────────────────────────────────
    def test_page_is_chart_led(self) -> None:
        self.assertGreaterEqual(len(self.exhibits), 20)
        self.assertEqual(self.payload["summary"]["blocks"], [])
        for exhibit in self.exhibits:
            self.assertTrue(exhibit.get("note"), exhibit["title"])
            self.assertNotIn("{EX_", exhibit.get("note", ""), exhibit["title"])
            self.assertNotIn("{EX_", exhibit["title"])

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
        self.assertEqual(len(guided["rows"]), 37)
        self.assertEqual(guided["rows"][-1][2], "—")
        self.assertNotIn("跌破下限", {row[3] for row in guided["rows"]})
        self.assertNotIn("跌破下限", {row[6] for row in guided["rows"]})

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
        self.assertEqual(expectation["as_of"], "2026-07-30")
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


if __name__ == "__main__":
    unittest.main()
