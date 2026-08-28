"""Checks for the CDNS page.

The page rests on four claims that a quarter roll can quietly invalidate, and
each one is pinned here:

* the guided record must stay paired guide-to-actual on the *guided* quarter.
  Cadence publishes each quarter's outlook alongside the previous quarter's
  results, so an off-by-one match would read a quarter's own result back as its
  forecast and turn the whole first section into a tautology;
* the record's shape is the page's headline finding -- forty-two finished
  quarters and not one reported revenue below the guided floor. The counts are
  asserted, not narrated, so a bad parse cannot quietly soften them;
* a guidance stated as "29% to 30%" is a range, not a point. Three 2018
  quarters were originally read as points because the parser only knew the dash
  form, which overstated each beat by about a hundred basis points;
* the twelve quarterly values must still add to the filed year. Every
  cash-flow line is reconstructed from year-to-date filings and the fiscal
  fourth quarter is the year minus the nine months, so a mis-stitch shows up as
  a sum that no longer closes.

Two further tests exist because the page publishes something the company does
not print. The non-GAAP operating margin is stated as a percent and the same
release states every operating add-back in thousands, so the percent has to be
reproducible from the statements; and China revenue is a *filed* dollar line
from the segment note rather than the integer share times revenue, which is the
derivation this page deliberately does not use.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.all import build_all, roster_payload  # noqa: E402
from build.board import headroom  # noqa: E402
from build.cdns import build_payload  # noqa: E402


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


class CdnsDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "cdns.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]
        cls.by_section = {
            section["id"]: section["exhibits"] for section in cls.payload["sections"]
        }
        cls.q = cls.source["quarterly_usd_m"]
        cls.pct = cls.source["quarterly_pct"]
        cls.other = cls.source["quarterly_other"]
        cls.guide = cls.source["quarterly_guidance_history"]

    # ── the series itself ────────────────────────────────────────────────────
    def test_twelve_quarter_base_backs_every_yoy(self) -> None:
        """Eight quarters are drawn and four more exist only to divide by."""
        self.assertEqual(len(self.source["periods"]), 12)
        for name, values in self.q.items():
            with self.subTest(series=name):
                self.assertEqual(len(values), 12)

    def test_income_statement_identity_holds_each_quarter(self) -> None:
        """Revenue less total costs and expenses is operating income, filed."""
        for index, period in enumerate(self.source["periods"]):
            with self.subTest(period=period):
                self.assertAlmostEqual(
                    self.q["revenue_total"][index] - self.q["costs_and_expenses"][index],
                    self.q["operating_income"][index],
                    delta=0.002,
                )

    def test_revenue_splits_into_the_two_filed_lines(self) -> None:
        for index, period in enumerate(self.source["periods"]):
            with self.subTest(period=period):
                self.assertAlmostEqual(
                    self.q["revenue_product_and_maintenance"][index]
                    + self.q["revenue_services"][index],
                    self.q["revenue_total"][index],
                    delta=0.002,
                )

    def test_quarterly_series_reconcile_with_the_full_year(self) -> None:
        """Every cash-flow line is stitched from year-to-date filings, and the
        fiscal fourth quarter is the year minus the nine months, so the only
        way to know the stitch is right is that the four quarters still add to
        the filed annual figure."""
        annual = self.source["annual_reconciliation_usd_m"]
        periods = self.source["periods"]
        for position, year in enumerate(annual["years"]):
            quarters = [i for i, period in enumerate(periods) if period.endswith(year)]
            self.assertEqual(len(quarters), 4, year)
            for name in ("revenue_total", "operating_income", "research_and_development",
                         "net_income", "operating_cash_flow", "capital_expenditures",
                         "stock_repurchases", "china_revenue"):
                with self.subTest(year=year, series=name):
                    self.assertAlmostEqual(
                        sum(self.q[name][index] for index in quarters),
                        annual[name][position],
                        delta=0.05,
                    )

    def test_non_gaap_margin_is_reproducible_from_the_statements(self) -> None:
        """The company prints the margin as a percent and the add-backs in
        thousands; the page publishes the percent, so the two have to agree."""
        recon = self.source["non_gaap_reconciliation_usd_m"]
        for index, period in enumerate(self.source["periods"]):
            addbacks = recon["operating_addbacks"][index]
            disclosed = self.pct["non_gaap_operating_margin"][index]
            if addbacks is None or disclosed is None:
                continue
            with self.subTest(period=period):
                derived = (self.q["operating_income"][index] + addbacks) \
                    / self.q["revenue_total"][index] * 100
                self.assertAlmostEqual(derived, disclosed, delta=0.06)

    def test_mix_percentages_close_to_one_hundred(self) -> None:
        geography = ["geo_americas", "geo_china", "geo_other_asia", "geo_emea", "geo_japan"]
        category = ["category_core_eda", "category_semiconductor_ip",
                    "category_system_design_analysis"]
        for index, period in enumerate(self.source["periods"]):
            for name, keys in (("地域", geography), ("产品线", category)):
                values = [self.pct[key][index] for key in keys]
                if any(value is None for value in values):
                    continue
                with self.subTest(period=period, mix=name):
                    # integer percentages, so the sum is 100 give or take the
                    # rounding the company itself footnotes
                    self.assertLessEqual(abs(sum(values) - 100), 1)

    def test_china_is_the_filed_dollar_line_not_the_derived_one(self) -> None:
        """The segment note discloses China in dollars, so the page must not be
        plotting the integer share times revenue -- a derivation that reads the
        latest year-over-year move as +107% where the filing says +95.7%."""
        for index, period in enumerate(self.source["periods"]):
            filed = self.q["china_revenue"][index]
            share = self.pct["geo_china"][index]
            if filed is None or share is None:
                continue
            derived = share / 100 * self.q["revenue_total"][index]
            with self.subTest(period=period):
                self.assertNotAlmostEqual(filed, derived, delta=0.0005)
                # but the two must still describe the same quarter
                self.assertLess(abs(filed - derived) / filed * 100, 8.0)
        latest = self.q["china_revenue"][-1] / self.q["china_revenue"][-5] - 1
        self.assertAlmostEqual(latest * 100, 95.7, delta=0.1)

    # ── the guided record ────────────────────────────────────────────────────
    def test_guidance_record_is_paired_on_the_guided_quarter(self) -> None:
        """Cadence guides quarter N in the release that reports quarter N-1, so
        every row's guidance date has to fall after that earlier quarter ended
        and inside the quarter being guided -- never after it."""
        record = self.guide
        length = len(record["quarters"])
        for key, values in record.items():
            if isinstance(values, list):
                with self.subTest(series=key):
                    self.assertEqual(len(values), length)
        month_end = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}
        month_start = {1: "01-01", 2: "04-01", 3: "07-01", 4: "10-01"}
        for quarter, filed in zip(record["quarters"], record["guided_on"]):
            year, number = int(quarter[:4]), int(quarter[-1])
            with self.subTest(quarter=quarter):
                self.assertGreater(filed, f"{year}-{month_start[number]}")
                self.assertLess(filed, f"{year}-{month_end[number]}")

    def test_only_the_pending_quarter_lacks_an_actual(self) -> None:
        record = self.guide
        for key in ("revenue_actual_usd_m", "non_gaap_operating_margin_actual_pct",
                    "non_gaap_eps_actual"):
            missing = [q for q, v in zip(record["quarters"], record[key]) if v is None]
            with self.subTest(series=key):
                self.assertEqual(missing, [record["quarters"][-1]])

    def test_the_record_never_broke_the_floor_on_revenue_or_eps(self) -> None:
        """The page's headline claim, asserted rather than narrated."""
        record = self.guide

        def tally(low, high, actual):
            above = inside = below = 0
            for lo, hi, value in zip(record[low], record[high], record[actual]):
                if value is None:
                    continue
                if value > hi:
                    above += 1
                elif value < lo:
                    below += 1
                else:
                    inside += 1
            return above, inside, below

        self.assertEqual(
            tally("revenue_guide_low_usd_m", "revenue_guide_high_usd_m", "revenue_actual_usd_m"),
            (25, 17, 0),
        )
        self.assertEqual(
            tally("non_gaap_eps_guide_low", "non_gaap_eps_guide_high", "non_gaap_eps_actual"),
            (35, 7, 0),
        )
        above, inside, below = tally(
            "non_gaap_operating_margin_guide_low_pct",
            "non_gaap_operating_margin_guide_high_pct",
            "non_gaap_operating_margin_actual_pct",
        )
        self.assertEqual((above, inside, below), (37, 3, 2))

    def test_both_margin_shortfalls_were_against_a_point_guidance(self) -> None:
        """The page says the two misses were against a guidance with no width;
        if that ever stops being true the sentence has to change."""
        record = self.guide
        for index, quarter in enumerate(record["quarters"]):
            actual = record["non_gaap_operating_margin_actual_pct"][index]
            low = record["non_gaap_operating_margin_guide_low_pct"][index]
            if actual is None or actual >= low:
                continue
            with self.subTest(quarter=quarter):
                self.assertEqual(record["non_gaap_operating_margin_guide_form"][index], "point")
                self.assertLess(low - actual, 0.5)

    def test_a_two_sided_guidance_is_never_recorded_as_a_point(self) -> None:
        """Cadence writes some ranges as "29% to 30%" rather than with a dash.
        Reading those as a point overstated three 2018 beats by about a hundred
        basis points each, so the form flag and the endpoints have to agree."""
        record = self.guide
        for index, quarter in enumerate(record["quarters"]):
            form = record["non_gaap_operating_margin_guide_form"][index]
            low = record["non_gaap_operating_margin_guide_low_pct"][index]
            high = record["non_gaap_operating_margin_guide_high_pct"][index]
            with self.subTest(quarter=quarter):
                self.assertEqual(form == "point", low == high)
        for quarter, expected in (("2018Q2", (27.0, 28.0)), ("2018Q3", (27.0, 28.0)),
                                  ("2018Q4", (29.0, 30.0))):
            index = record["quarters"].index(quarter)
            with self.subTest(quarter=quarter):
                self.assertEqual(
                    (record["non_gaap_operating_margin_guide_low_pct"][index],
                     record["non_gaap_operating_margin_guide_high_pct"][index]),
                    expected,
                )

    def test_the_page_states_the_guidance_is_not_ex_ante(self) -> None:
        """Every delivery chart has to carry the timing caveat: the guidance is
        published inside the quarter it guides, which is what makes a perfect
        record less remarkable than it first reads."""
        delivery = [ex for ex in self.by_section["settled"]
                    if ex["kind"] in ("range_band", "grouped_bars")]
        self.assertEqual(len(delivery), 6)
        for exhibit in delivery:
            with self.subTest(exhibit=exhibit["n"]):
                self.assertIn("不是事前预测", exhibit["src_extra"])
        self.assertTrue(any("不是事前预测" in note for note in self.payload["notes"]))

    # ── the derived numbers the page argues from ─────────────────────────────
    def test_implied_fourth_quarter_margin_is_an_identity(self) -> None:
        """Full year less first half less the third quarter's guided midpoint
        leaves the fourth quarter, with no estimate anywhere in it."""
        guidance = self.source["guidance"]
        current, half = guidance["fy2026_current"], guidance["h1_2026_actual"]
        fy_revenue = sum(current["revenue_usd_m"]) / 2
        fy_income = current["non_gaap_operating_income_midpoint_usd_m"]
        q3_revenue = sum(guidance["q3_2026"]["revenue_usd_m"]) / 2
        q3_margin = sum(guidance["q3_2026"]["non_gaap_operating_margin_pct"]) / 2
        q4_revenue = fy_revenue - half["revenue_usd_m"] - q3_revenue
        q4_income = (fy_income - half["non_gaap_operating_income_usd_m"]
                     - q3_revenue * q3_margin / 100)
        self.assertAlmostEqual(q4_income / q4_revenue * 100, 42.84, delta=0.02)
        self.assertAlmostEqual(
            half["non_gaap_operating_income_usd_m"] / half["revenue_usd_m"] * 100,
            half["non_gaap_operating_margin_pct"],
            delta=0.01,
        )

    def test_backlog_coverage_is_read_against_the_same_quarter(self) -> None:
        """The multiple is drawn down every first half, so the chart must not
        argue from a sequential fall alone."""
        chart = next(ex for ex in self.by_section["quarter_highlights"]
                     if "backlog" in ex["title"] and ex["kind"] == "gs_bar")
        self.assertIn("去年同期", chart["note"])
        self.assertIn("季节性", chart["note"])

    # ── thresholds ───────────────────────────────────────────────────────────
    def test_headroom_bars_reproduce_the_thresholds(self) -> None:
        for section, block, key in (("settled", "prior_kpi_settlement", "actual"),
                                    ("next_quarter", "next_kpi", "current")):
            entries = self.source[block]["quantified"]
            chart = next(ex for ex in self.by_section[section]
                         if ex["kind"] == "diverging_bars")
            with self.subTest(section=section):
                self.assertEqual(chart["xlabels"], [e["metric"] for e in entries])
                self.assertEqual(
                    chart["values"],
                    [round(headroom(e["direction"], e["threshold"], e[key]), 1) for e in entries],
                )

    def test_book_to_bill_is_retired_rather_than_settled(self) -> None:
        """Its numerator is the difference of two figures the company rounds to
        US$0.1B, so the ratio cannot be resolved against a 1.10x line at all."""
        settlement = self.source["prior_kpi_settlement"]
        self.assertNotIn("单季 book-to-bill",
                         [entry["metric"] for entry in settlement["quantified"]])
        self.assertTrue(any("book-to-bill" in text for text in settlement["retired"]))
        chart = next(ex for ex in self.by_section["settled"] if ex["kind"] == "diverging_bars")
        self.assertIn("无法结算", chart["note"])

    def test_every_tracked_metric_with_a_series_gets_its_own_chart(self) -> None:
        """The overview bar says which line broke; only the per-metric chart
        says how it got there."""
        for section, block, key in (("settled", "prior_kpi_settlement", "actual"),
                                    ("next_quarter", "next_kpi", "current")):
            titles = " ".join(ex["title"] for ex in self.by_section[section])
            for entry in self.source[block]["quantified"]:
                if entry["metric"] in ("FY2026 非 GAAP EPS 指引中值",
                                       "Semiconductor IP 同比增速",
                                       "Q4 2026 隐含非 GAAP 营业利润率",
                                       "中国收入占比", "季末 backlog"):
                    continue
                with self.subTest(section=section, metric=entry["metric"]):
                    self.assertIn(entry["metric"], titles)

    # ── page shape and boundary ──────────────────────────────────────────────
    def test_page_is_chart_led(self) -> None:
        self.assertGreaterEqual(len(self.exhibits), 24)
        self.assertEqual(self.payload["summary"]["blocks"], [])
        for exhibit in self.exhibits:
            with self.subTest(exhibit=exhibit["n"]):
                self.assertTrue(exhibit["note"])
                self.assertTrue(exhibit["src_extra"])

    def test_section_order_matches_how_the_note_is_used(self) -> None:
        self.assertEqual(
            [section["id"] for section in self.payload["sections"]],
            ["settled", "quarter_highlights", "next_quarter", "routine"],
        )

    def test_exhibit_numbers_are_assigned_in_render_order(self) -> None:
        self.assertEqual([ex["n"] for ex in self.exhibits],
                         list(range(2, 2 + len(self.exhibits))))
        for exhibit in self.exhibits:
            with self.subTest(exhibit=exhibit["n"]):
                self.assertNotIn("{EX_", json.dumps(exhibit, ensure_ascii=False))

    def test_cdns_is_not_in_the_cross_page_capex_table(self) -> None:
        """The shared table is hyperscaler capex into foundry wafers; Cadence
        sits outside that chain and must not be spliced into it."""
        table = next(t for t in self.payload["tables"] if "AI capex" in t["title"])
        self.assertNotIn("CDNS", " ".join(table["headers"]))

    def test_market_expectation_is_labelled_and_unattributed(self) -> None:
        consensus = self.source["market_expectation"]
        self.assertIn("市场预期", consensus["label"])
        self.assertTrue(consensus["as_of"])
        blob = json.dumps(self.payload, ensure_ascii=False).lower()
        for broker in ("zacks", "marketbeat", "seeking alpha", "investing.com", "benzinga",
                       "stifel", "benchmark", "bloomberg", "visible alpha", "factset"):
            with self.subTest(broker=broker):
                self.assertNotIn(broker, blob)
        # 目标价 / 评级 / 估值 are deliberately absent from this list: they appear
        # in the page's own boundary statement, exactly as on every other page,
        # so a substring test on them fires on a clean tree. What must never
        # appear is a position instruction or a valuation multiple carried over
        # from the local note.
        for banned in ("加仓", "减仓", "买入", "卖出", "撤销条件", "情景", "概率加权",
                       "forward p/e", "ev/revenue", "terminal multiple"):
            with self.subTest(term=banned):
                self.assertNotIn(banned, blob)

    def test_sources_are_official_http_links(self) -> None:
        for source in self.source["sources"]:
            with self.subTest(label=source["label"]):
                host = urlparse(source["url"]).netloc
                self.assertTrue(host.endswith("sec.gov") or host.endswith("cadence.com"), host)

    def test_published_payload_roster_and_shell(self) -> None:
        published = js_payload(ROOT / "data" / "cdns.js", "window.DASH")
        self.assertEqual(published, self.payload)
        roster = js_payload(ROOT / "data" / "roster.js", "window.ROSTER")
        self.assertEqual(roster, roster_payload(build_all()))
        shell = (ROOT / "cdns" / "index.html").read_text(encoding="utf-8")
        self.assertIn("../data/cdns.js", shell)
        self.assertNotIn("../data/tsm.js", shell)

    def test_home_page_carries_the_new_company(self) -> None:
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="cdns/"', home)
        self.assertIn(self.payload["latest"]["disclosed_period_label"], home)
        self.assertIn(self.payload["latest"]["release_date"], home)

    def test_public_files_exclude_private_and_broker_material(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [ROOT / "series" / "cdns.json", ROOT / "data" / "cdns.js"]
        )
        for banned in ("OneDrive", "/Users/", ".pptx", "transcript.pdf", "Seeking Alpha",
                       "Zacks", "MarketBeat", "Stifel", "Benchmark"):
            with self.subTest(term=banned):
                self.assertNotIn(banned, text)


if __name__ == "__main__":
    unittest.main()
