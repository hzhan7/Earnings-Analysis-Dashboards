"""Checks for the META page.

The three things worth pinning here are the ones a quarter roll can silently
break: the revenue lines must still add back to the reported total, the
volume/price bridge must still close against reported advertising growth, and
the adjusted figures the thresholds are settled on must still match the numbers
actually plotted.  Everything else on the page is a chart of a reported series.
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

from build.board import cn_count, headroom  # noqa: E402
from build.meta import build_payload  # noqa: E402

WINDOW = 8


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


class MetaDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "meta.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]
        cls.by_section = {
            section["id"]: section["exhibits"] for section in cls.payload["sections"]
        }
        cls.q = cls.source["quarterly_usd_m"]

    def test_twelve_quarter_base_backs_every_yoy(self) -> None:
        self.assertEqual(len(self.source["periods"]), 12)
        for name, values in self.q.items():
            self.assertEqual(len(values), 12, name)
            self.assertTrue(all(math.isfinite(value) for value in values), name)
        for name, values in self.source["advertising_metrics"].items():
            if isinstance(values, list):
                self.assertEqual(len(values), 12, name)

    def test_revenue_lines_add_back_to_the_reported_total(self) -> None:
        """Advertising is derived by subtraction, so it is only trustworthy if
        the three published lines reconstruct the reported total exactly."""
        table = next(t for t in self.payload["tables"] if "十二季度基础数据" in t["title"])
        self.assertEqual(len(table["rows"]), 12)
        for index, period in enumerate(self.source["periods"]):
            total = self.q["revenue_total"][index]
            parts = (
                self.q["reality_labs_revenue"][index] + self.q["foa_other_revenue"][index]
            )
            advertising = int(table["rows"][index][2].strip("$M D").replace(",", ""))
            self.assertEqual(advertising + parts, total, period)

    def test_income_statement_identity_holds_each_quarter(self) -> None:
        for index, period in enumerate(self.source["periods"]):
            derived = self.q["revenue_total"][index] - self.q["costs_and_expenses"][index]
            self.assertEqual(derived, self.q["operating_income"][index], period)

    def test_free_cash_flow_uses_the_company_definition(self) -> None:
        """META nets finance-lease principal inside free cash flow; using the
        plain OCF-minus-capex form would overstate the current quarter by
        roughly a billion dollars. The company prints the quarter's figure in
        its reconciliation table; `_checks` carries it."""
        checks = self.source["_checks"]
        derived = [
            operating - purchases - lease
            for operating, purchases, lease in zip(
                self.q["operating_cash_flow"],
                self.q["purchases_of_property_and_equipment"],
                self.q["finance_lease_principal"],
            )
        ]
        self.assertEqual(derived[-1], checks["free_cash_flow_usd_m"])
        capex = [
            purchases + lease
            for purchases, lease in zip(
                self.q["purchases_of_property_and_equipment"],
                self.q["finance_lease_principal"],
            )
        ]
        self.assertEqual(capex[-1], checks["capital_expenditures_incl_finance_leases_usd_m"])
        quality = next(t for t in self.payload["tables"] if t["title"].startswith("当季经营质量"))
        rows = {row[0]: row for row in quality["rows"]}
        self.assertEqual(rows["自由现金流 D"][1:4], [f"${derived[i]:,}M" for i in (-5, -2, -1)])
        self.assertEqual(rows["资本开支（含融资租赁）"][1:4], [f"${capex[i]:,}M" for i in (-5, -2, -1)])

    def test_quarterly_series_reconcile_with_the_full_year(self) -> None:
        """The fourth quarter of each year is a subtraction from the annual
        report, so it has to add back to the disclosed full-year figures --
        within $1M, because each quarter and each year-to-date total is rounded
        to the million on its own.

        That slack is also how a wrong quarter hides. This test used to demand
        an exact match for revenue and allow $1M only for operating income, and
        both passed while 2025Q3 was carried as revenue 51,243 and operating
        income 20,534: the 10-Q prints 51,242 and 20,535. The revenue error made
        the four quarters add to the 10-K's 200,966 exactly -- the filed quarters
        add to 200,965, because the nine-month total the fourth quarter is
        subtracted from (141,073) is itself rounded. An exact match was the
        symptom, not the proof; `MetaChecksTest` and the XBRL comparison in the
        series' provenance are what pin the quarters themselves."""
        checked = 0
        for fiscal_year, annual in self.source["annual_actuals_usd_m"].items():
            if not fiscal_year.isdigit():
                continue
            quarters = [i for i, p in enumerate(self.source["periods"]) if p.endswith(fiscal_year)]
            if len(quarters) != 4:
                continue
            checked += 1
            year = slice(quarters[0], quarters[-1] + 1)
            for quarterly_key, annual_key in (
                ("revenue_total", "revenue"),
                ("operating_income", "operating_income"),
                ("share_based_compensation", "share_based_compensation"),
                ("depreciation_and_amortization", "depreciation_and_amortization"),
                ("purchases_of_property_and_equipment", "purchases_of_property_and_equipment"),
                ("finance_lease_principal", "finance_lease_principal"),
            ):
                with self.subTest(year=fiscal_year, line=quarterly_key):
                    self.assertLessEqual(
                        abs(sum(self.q[quarterly_key][year]) - annual[annual_key]), 1)
        self.assertGreaterEqual(checked, 1, "no full fiscal year inside the twelve-quarter window")

    def test_volume_price_bridge_closes_against_reported_growth(self) -> None:
        """The page's central claim -- the deceleration is entirely volume -- is
        only defensible while impressions x price still reproduces advertising
        growth. Published rounding is to whole percent, so 1.2pp is the slack."""
        ads = self.source["advertising_metrics"]
        advertising = [
            total - reality - other
            for total, reality, other in zip(
                self.q["revenue_total"],
                self.q["reality_labs_revenue"],
                self.q["foa_other_revenue"],
            )
        ]
        for index in range(4, len(advertising)):
            product = (
                (1 + ads["ad_impressions_yoy_pct"][index] / 100)
                * (1 + ads["price_per_ad_yoy_pct"][index] / 100)
                - 1
            ) * 100
            actual = (advertising[index] / advertising[index - 4] - 1) * 100
            self.assertLess(
                abs(product - actual),
                1.2,
                f"{self.source['periods'][index]}: bridge {product:.1f}% vs actual {actual:.1f}%",
            )

    def test_page_is_chart_led(self) -> None:
        self.assertEqual(self.payload["summary"]["blocks"], [])
        self.assertIsNone(self.payload["guidance"])
        self.assertEqual(
            [ex["n"] for ex in self.exhibits], list(range(2, 2 + len(self.exhibits)))
        )
        for exhibit in self.exhibits:
            self.assertTrue(exhibit.get("kind"), exhibit["n"])
            self.assertTrue(exhibit.get("note"), f"exhibit {exhibit['n']} has no explanation")
            self.assertTrue(exhibit.get("src_extra"), f"exhibit {exhibit['n']} has no source line")

    def test_long_history_agrees_with_the_reviewed_quarters(self) -> None:
        """The ten-year series and the reviewed twelve must not disagree.

        Two windows over the same quarters is how a page ends up publishing two
        different numbers for one fact.  Every overlapping quarter is compared
        here, so a future edit to either block has to keep them equal.
        """
        long = self.source["long_history"]
        index = {quarter: i for i, quarter in enumerate(long["quarters"])}
        pairs = [
            ("revenue_usd_m", "revenue_total"),
            ("capital_expenditures_usd_m", "purchases_of_property_and_equipment"),
            ("operating_cash_flow_usd_m", "operating_cash_flow"),
            ("operating_income_usd_m", "operating_income"),
            ("depreciation_and_amortization_usd_m", "depreciation_and_amortization"),
            ("finance_lease_principal_usd_m", "finance_lease_principal"),
            ("reality_labs_revenue_usd_m", "reality_labs_revenue"),
            ("foa_other_revenue_usd_m", "foa_other_revenue"),
        ]
        for long_key, reviewed_key in pairs:
            for period, expected in zip(self.source["periods"], self.q[reviewed_key]):
                quarter, year = period.split()
                got = long[long_key][index[f"{year}Q{quarter[1]}"]]
                self.assertEqual(got, expected, f"{long_key} {period}")
        # The ad metrics are carried twice too; a roll has to append to both.
        for key, values in self.source["advertising_metrics"].items():
            if not isinstance(values, list):
                continue
            for period, expected in zip(self.source["periods"], values):
                quarter, year = period.split()
                self.assertEqual(long[key][index[f"{year}Q{quarter[1]}"]], expected, f"{key} {period}")
        # And the advertising line the long charts draw is the reported total
        # less the two other lines, quarter for quarter.
        for period, total, reality, other in zip(self.source["periods"], self.q["revenue_total"],
                                                 self.q["reality_labs_revenue"], self.q["foa_other_revenue"]):
            quarter, year = period.split()
            self.assertEqual(long["advertising_revenue_usd_m"][index[f"{year}Q{quarter[1]}"]],
                             total - reality - other, period)

    def test_the_five_fourth_quarter_ad_holes_stay_holes(self) -> None:
        """Impressions and price-per-ad have no Q4 reading for 2016-2020.

        The 10-K states only the full-year change for those years, and the 8-K
        did not carry the quarterly bullet until 2021Q4 -- so five fourth
        quarters have no published figure. Interpolating them would be
        invisible: the line would simply look continuous, and the two rates
        multiply into an implied revenue growth that this page settles a
        threshold on. The holes are pinned to exactly those five quarters.
        """
        long = self.source["long_history"]
        quarters = long["quarters"]
        expected = ["2016Q4", "2017Q4", "2018Q4", "2019Q4", "2020Q4"]
        for key in ("ad_impressions_yoy_pct", "price_per_ad_yoy_pct"):
            missing = [q for q, v in zip(quarters, long[key]) if v is None]
            self.assertEqual(missing, expected, key)
        # The two always come from the same sentence, so they are missing
        # together -- a hole in one but not the other means a mis-parse.
        for impressions, price in zip(long["ad_impressions_yoy_pct"],
                                      long["price_per_ad_yoy_pct"]):
            self.assertEqual(impressions is None, price is None)
        self.assertIn("五个第四季留空", long["ad_metrics_note"])
        # And the chart carries the holes rather than a bridged line.
        chart = next(ex for ex in self.exhibits
                     if [s["name"] for s in ex.get("series", [])][1:] == ["广告曝光 YoY", "平均每条广告价格 YoY"])
        for series in chart["series"][1:]:
            self.assertEqual(sum(1 for v in series["values"] if v is None), len(expected),
                             series["name"])

    def test_undisclosed_quarters_stay_empty(self) -> None:
        """A series may not start before the company first published it.

        META did not report segments until it reported them, and did not
        disclose finance-lease principal before ASC 842.  Back-filling either
        would invent a number the company never gave, so the holes are asserted
        to be holes and the charts are asserted to carry the shorter axis.
        """
        long = self.source["long_history"]
        quarters = long["quarters"]
        for key, first_key in (
            ("reality_labs_revenue_usd_m", "segment_first_reported"),
            ("foa_other_revenue_usd_m", "segment_first_reported"),
            ("finance_lease_principal_usd_m", "finance_lease_first_reported"),
        ):
            start = quarters.index(long[first_key])
            self.assertTrue(all(value is None for value in long[key][:start]), key)
            self.assertTrue(all(value is not None for value in long[key][start:]), key)

        # The chart starts at the disclosure, not with blank slots on the left.
        segment_chart = next(ex for ex in self.exhibits if "两条非广告收入线" in ex["title"])
        for series in segment_chart["series"]:
            self.assertNotIn(None, series["values"], segment_chart["title"])
        self.assertEqual(
            len(segment_chart["xlabels"]), len(quarters) - quarters.index(
                long["segment_first_reported"])
        )

    def test_guidance_record_is_built_from_the_filed_ranges(self) -> None:
        """Every guided quarter is the company's own range against its own actual.

        META is the only US filer on this site that puts quarterly guidance in a
        filing; the record is only worth publishing if each bar is traceable to
        one, so both legs are checked against the source block.
        """
        history = self.source["quarterly_guidance_history"]
        band = next(ex for ex in self.exhibits if ex.get("ref") == "meta_revenue_band")
        self.assertEqual(band["lo"], history["guide_low_usd_bn"])
        self.assertEqual(band["hi"], history["guide_high_usd_bn"])
        self.assertEqual(band["actual"], history["actual_revenue_usd_bn"])
        for low, high in zip(history["guide_low_usd_bn"], history["guide_high_usd_bn"]):
            self.assertLess(low, high)

        # The actual plotted against each guided quarter is the same revenue the
        # rest of the page reports for it, in US$B.
        long = self.source["long_history"]
        index = {quarter: i for i, quarter in enumerate(long["quarters"])}
        for quarter, actual in zip(history["quarters"], history["actual_revenue_usd_bn"]):
            if actual is None:
                continue
            self.assertAlmostEqual(
                actual, long["revenue_usd_m"][index[quarter]] / 1000.0, places=3, msg=quarter
            )

        # Only the quarter that has not been reported yet may be missing, and it
        # has to be the last one.
        missing = [i for i, value in enumerate(history["actual_revenue_usd_bn"]) if value is None]
        self.assertIn(missing, ([], [len(history["quarters"]) - 1]))

        deviation = next(
            ex for ex in self.exhibits if ex.get("ref") == "meta_revenue_midpoint"
        )
        settled = [value for value in history["actual_revenue_usd_bn"] if value is not None]
        self.assertEqual(len(deviation["groups"][0]["values"]), len(settled))
        for quarter, low, high, actual, got in zip(
            history["quarters"], history["guide_low_usd_bn"],
            history["guide_high_usd_bn"], history["actual_revenue_usd_bn"],
            deviation["groups"][0]["values"],
        ):
            if actual is None:
                continue
            self.assertAlmostEqual(
                got, (actual / ((low + high) / 2) - 1) * 100, places=6, msg=quarter
            )

    def test_the_page_has_the_four_sections_in_order(self) -> None:
        """Every company page carries the same four sections, ids and titles verbatim."""
        self.assertEqual(
            [(section["id"], section["title"]) for section in self.payload["sections"]],
            [("settled", "一、上季跟踪指标兑现了吗"), ("quarter_highlights", "二、本季重点"),
             ("next_quarter", "三、下季要跟踪什么"), ("routine", "四、长期常规跟踪")],
        )
        for section in self.payload["sections"]:
            self.assertTrue(section["exhibits"], section["id"])
        self.assertIn("本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列", self.payload["notes"][0])

    def test_section_one_settles_before_it_scores_the_guidance(self) -> None:
        """(a) the follow-up questions, (b) last quarter's thresholds, then (c) the
        company's own guidance record -- the guidance charts come last."""
        settled = self.by_section["settled"]
        kinds = [ex.get("ref") or ex["kind"] for ex in settled]
        self.assertEqual(kinds[0], "bars_labeled")
        self.assertIn("待验证问题", settled[0]["title"])
        self.assertEqual(kinds[-2:], ["meta_revenue_band", "meta_revenue_midpoint"])

    def test_a_one_quarter_snapshot_is_not_filed_as_a_long_series(self) -> None:
        """The regional chart is one quarter's reading: it belongs with the
        quarter's findings, not among the long series of section four."""
        routine_titles = [ex["title"] for ex in self.by_section["routine"]]
        self.assertFalse(any("区域" in title for title in routine_titles), routine_titles)
        highlight_titles = [ex["title"] for ex in self.by_section["quarter_highlights"]]
        self.assertTrue(any("区域" in title for title in highlight_titles), highlight_titles)

    def test_section_order_matches_how_the_note_is_used(self) -> None:
        """Section lengths follow the stamped blocks, not a typed 6/6/5/4."""
        prior = self.source["prior_kpi_settlement"]["quantified"]
        nxt = self.source["next_kpi"]["quantified"]
        plotted_prior = [e for e in prior if e["metric"] in ("经营利润率（调整后）", "平均每条广告价格 YoY")]
        plotted_next = [e for e in nxt if "CapEx 指引中点" not in e["metric"]]
        highlights = (4 + ("quarter_geography" in self.source)
                      + bool(self.source["quarter_snapshot"]["one_off_items"]))
        self.assertEqual(
            [(section["id"], len(section["exhibits"])) for section in self.payload["sections"]],
            [("settled", 1 + 1 + 2 + len(plotted_prior)), ("quarter_highlights", highlights + 1),
             ("next_quarter", 1 + len(plotted_next)), ("routine", 3)],
        )

    def test_headroom_bars_reproduce_the_thresholds(self) -> None:
        for section, block, key in (
            ("settled", "prior_kpi_settlement", "actual"),
            ("next_quarter", "next_kpi", "current"),
        ):
            entries = self.source[block]["quantified"]
            exhibit = next(
                ex for ex in self.by_section[section] if ex["kind"] == "diverging_bars"
            )
            self.assertEqual(exhibit["xlabels"], [entry["metric"] for entry in entries])
            for entry, plotted in zip(entries, exhibit["values"]):
                expected = headroom(entry["direction"], entry["threshold"], entry[key])
                self.assertAlmostEqual(plotted, round(expected, 1), places=6, msg=entry["metric"])
        breached = {
            label
            for label, value in zip(
                self.by_section["next_quarter"][0]["xlabels"],
                self.by_section["next_quarter"][0]["values"],
            )
            if value < 0
        }
        # The title states how many lines are already under water. It said
        # "two" over a bar chart with three negative bars.
        self.assertIn(f"{cn_count(len(breached))}条已在阈值之下",
                      self.by_section["next_quarter"][0]["title"])
        # ...and it says they "all" point at incremental profit only if they do.
        themed = {e["metric"] for e in self.source["next_kpi"]["quantified"] if e.get("theme")}
        if not breached <= themed:
            self.assertNotIn("且都直接指向", self.by_section["next_quarter"][0]["title"])

    def test_every_tracked_metric_with_a_series_gets_its_own_chart(self) -> None:
        charted = {ex["title"].split("：")[0] for ex in self.by_section["next_quarter"][1:]}
        tracked = {entry["metric"] for entry in self.source["next_kpi"]["quantified"]}
        # The capex guidance midpoint is a revision history, not a quarterly
        # series; it gets its own chart in the highlights section.
        self.assertTrue(all("CapEx 指引中点" in metric for metric in tracked - charted),
                        tracked - charted)
        for exhibit in self.by_section["next_quarter"][1:]:
            threshold = exhibit["series"][-1]["values"]
            self.assertEqual(len(set(threshold)), 1, exhibit["title"])
            # Each tracked metric runs on the longest window its own series
            # has, so the threshold line is as long as that metric's axis --
            # not a shared eight.
            self.assertEqual(len(threshold), len(exhibit["xlabels"]), exhibit["title"])

    def test_adjusted_lines_match_the_value_the_threshold_is_settled_on(self) -> None:
        """Two thresholds are settled on the adjusted basis while the plotted
        history is GAAP. If the short adjusted line drifts from the stated
        current value, the chart contradicts its own caption."""
        snapshot = self.source["quarter_snapshot"]
        checks = self.source["_checks"]
        revenue = self.q["revenue_total"]
        operating_income = self.q["operating_income"]
        adjusted = operating_income[-1] + sum(item["usd_m"] for item in snapshot["one_off_items"])
        self.assertEqual(
            adjusted,
            checks["operating_income_usd_m"]
            + checks["legal_proceedings_charge_usd_m"]
            + checks["severance_charge_usd_m"],
        )

        margin_chart = next(ex for ex in self.by_section["settled"] if "经营利润率" in ex["title"])
        tail = margin_chart["series"][1]
        self.assertEqual(tail["values"][-1], round(adjusted / revenue[-1] * 100, 2))
        self.assertEqual(tail["values"][-2], round(margin_chart["series"][0]["values"][-2], 2))
        # The gold line exists only for the two quarters that have an adjusted
        # reading; everything before it is a hole, however long the axis is now.
        self.assertEqual(tail["values"][:-2], [None] * (len(tail["values"]) - 2))
        self.assertGreaterEqual(len(tail["values"]), WINDOW)

        incremental_chart = next(
            ex for ex in self.by_section["next_quarter"] if "增量经营利润率" in ex["title"]
        )
        expected = (adjusted - operating_income[-5]) / (revenue[-1] - revenue[-5]) * 100
        self.assertEqual(incremental_chart["series"][1]["values"][-1], round(expected, 2))
        entry = next(
            item for item in self.source["next_kpi"]["quantified"]
            if item["metric"] == "同比增量经营利润率"
        )
        self.assertAlmostEqual(entry["current"], expected, places=1)

    def test_audit_tables_back_every_derived_exhibit(self) -> None:
        tables = self.payload["tables"]
        first = len(self.exhibits) + 2
        self.assertEqual([table["n"] for table in tables], list(range(first, first + len(tables))))
        self.assertIn("AI capex", tables[-1]["title"])
        self.assertEqual(
            len(tables[0]["rows"]), len(self.source["prior_kpi_settlement"]["quantified"])
        )
        self.assertEqual(len(tables[1]["rows"]), len(self.source["next_kpi"]["quantified"]))
        ad_table = next(t for t in tables if "广告量价" in t["title"])
        self.assertEqual(len(ad_table["rows"]), 12)

    def test_market_expectation_is_labelled_and_unattributed(self) -> None:
        text = json.dumps(self.payload, ensure_ascii=False)
        self.assertIn("市场预期", text)
        for broker in ["FactSet", "Bloomberg", "Visible Alpha", "Seeking Alpha", "consensus"]:
            self.assertNotIn(broker.lower(), text.lower())
        self.assertEqual(self.source["market_expectation"]["as_of"],
                         self.source["latest"]["release_date"])
        # The post-earnings move is published as the range the sources disagree
        # over, never as a single number picked from one of them.
        low, high = self.source["market_expectation"]["post_earnings_price_change_range_pct"]
        self.assertIn(f"{abs(high):.0f}%–{abs(low):.0f}%", self.payload["headline"])

    def test_sources_are_official_http_links(self) -> None:
        allowed_hosts = {"investor.atmeta.com", "www.sec.gov"}
        for source in self.payload["source_links"]:
            parsed = urlparse(source["url"])
            self.assertEqual(parsed.scheme, "https")
            self.assertIn(parsed.hostname, allowed_hosts)

    def test_published_payload_and_shell(self) -> None:
        self.assertEqual(js_payload(ROOT / "data" / "meta.js", "window.DASH"), self.payload)
        shell = (ROOT / "meta" / "index.html").read_text(encoding="utf-8")
        self.assertIn("../data/meta.js", shell)
        self.assertNotIn("../data/googl.js", shell)

    def test_public_files_exclude_private_and_broker_material(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [
                ROOT / "series" / "meta.json",
                ROOT / "data" / "meta.js",
                ROOT / "meta" / "index.html",
            ]
        ).lower()
        for forbidden in [
            "/users/",
            "/library/cloudstorage/",
            "onedrive",
            "seeking alpha",
            "factset",
            "bloomberg",
            "anthropic",
            "谨慎多",
        ]:
            self.assertNotIn(forbidden, text)
        compact = "".join(text.split())
        self.assertNotIn(":nan", compact)
        self.assertNotIn(":infinity", compact)
        self.assertNotIn(":-infinity", compact)


STAMPED = ("followup_closure", "prior_kpi_settlement", "next_kpi", "market_expectation", "outlook",
           "quarter_snapshot", "quarter_geography", "quarter_expense_lines_usd_m")


def published_text(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


class MetaChecksTest(unittest.TestCase):
    """The page's quarter against a record keyed separately from the filing.

    `_checks` is typed once per quarter from the earnings release (and, for the
    regional growth, the quarter's 10-Q), with the place each figure was read
    from. It is not copied from the arrays and the builder never reads it
    (`test_data_only_roll`). Rolling a quarter re-keys `_checks`; this class
    does not change.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "meta.json").read_text(encoding="utf-8"))
        cls.checks = cls.source["_checks"]
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]
        cls.q = cls.source["quarterly_usd_m"]

    def test_the_page_names_the_checked_quarter(self) -> None:
        self.assertIn(self.checks["period"], self.payload["title"])
        self.assertIn(f"截至 {self.checks['period_end']}", self.payload["subtitle"])
        self.assertIn(f"发布 {self.checks['release_date']}", self.payload["subtitle"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        c, q = self.checks, self.q
        pairs = [
            ("revenue_total", "revenue_usd_m"), ("costs_and_expenses", "costs_and_expenses_usd_m"),
            ("operating_income", "operating_income_usd_m"), ("foa_other_revenue", "foa_other_revenue_usd_m"),
            ("reality_labs_revenue", "reality_labs_revenue_usd_m"),
            ("operating_cash_flow", "operating_cash_flow_usd_m"),
            ("purchases_of_property_and_equipment", "purchases_of_property_and_equipment_usd_m"),
            ("finance_lease_principal", "finance_lease_principal_usd_m"),
            ("depreciation_and_amortization", "depreciation_and_amortization_usd_m"),
            ("share_based_compensation", "share_based_compensation_usd_m"),
            ("stock_repurchases", "repurchases_usd_m"),
        ]
        for key, check in pairs:
            with self.subTest(line=key):
                self.assertEqual(q[key][-1], c[check])
        self.assertEqual(q["revenue_total"][-5], c["revenue_year_ago_usd_m"])
        self.assertEqual(q["operating_income"][-5], c["operating_income_year_ago_usd_m"])
        ads = self.source["advertising_metrics"]
        self.assertEqual(ads["ad_impressions_yoy_pct"][-1], c["ad_impressions_yoy_pct"])
        self.assertEqual(ads["price_per_ad_yoy_pct"][-1], c["price_per_ad_yoy_pct"])
        self.assertEqual(ads["family_daily_active_people_bn"][-1], c["family_daily_active_people_bn"])
        # The advertising line is derived by subtraction; it has to land on the
        # segment table's printed advertising revenue, both years.
        self.assertEqual(q["revenue_total"][-1] - q["reality_labs_revenue"][-1] - q["foa_other_revenue"][-1],
                         c["advertising_revenue_usd_m"])
        self.assertEqual(q["revenue_total"][-5] - q["reality_labs_revenue"][-5] - q["foa_other_revenue"][-5],
                         c["advertising_revenue_year_ago_usd_m"])
        snap = self.source["quarter_snapshot"]
        self.assertEqual(snap["family_of_apps_operating_income_usd_m"][0], c["family_of_apps_operating_income_usd_m"])
        self.assertEqual(snap["reality_labs_operating_loss_usd_m"][0], c["reality_labs_operating_loss_usd_m"])
        self.assertEqual(snap["diluted_eps_usd"][0], c["diluted_eps_usd"])
        self.assertEqual(snap["headcount"][0], c["headcount"])
        self.assertEqual(snap["net_debt_issuance_usd_m"], c["net_long_term_debt_issuance_usd_m"])
        one_offs = {item["name"]: item["usd_m"] for item in snap["one_off_items"]}
        self.assertEqual(one_offs, {"法律计提": c["legal_proceedings_charge_usd_m"],
                                    "遣散费": c["severance_charge_usd_m"]})

    def test_the_guidance_records_carry_the_checked_outlook(self) -> None:
        c, history = self.checks, self.source["quarterly_guidance_history"]
        self.assertEqual([history["guide_low_usd_bn"][-1], history["guide_high_usd_bn"][-1]],
                         c["next_quarter_revenue_guide_usd_bn"])
        self.assertIsNone(history["actual_revenue_usd_bn"][-1])
        year = self.checks["period"].split()[1]
        capex = [call for call in history["capex_guidance_calls"] if call["year"] == year]
        expense = [call for call in history["expense_guidance_calls"] if call["year"] == year]
        self.assertEqual([capex[-1]["low"], capex[-1]["high"]], c["full_year_capex_guide_usd_bn"])
        self.assertEqual([capex[-2]["low"], capex[-2]["high"]], c["full_year_capex_guide_prior_usd_bn"])
        self.assertEqual([expense[-1]["low"], expense[-1]["high"]], c["full_year_expense_guide_usd_bn"])
        self.assertEqual(capex[-1]["filed"], c["release_date"])
        outlook = self.source["outlook"]
        self.assertEqual(outlook["tax_rate_pct"], c["tax_rate_guide_pct"])
        self.assertEqual(outlook["tax_rate_prior_pct"], c["tax_rate_guide_prior_pct"])

    def test_computed_figures_round_to_what_the_release_prints(self) -> None:
        c, q = self.checks, self.q
        self.assertEqual(round(pct(q["revenue_total"][-1], q["revenue_total"][-5])), c["revenue_growth_printed_pct"])
        self.assertEqual(round(q["operating_income"][-1] / q["revenue_total"][-1] * 100),
                         c["operating_margin_printed_pct"])
        self.assertEqual(round(pct(c["advertising_revenue_usd_m"], c["advertising_revenue_year_ago_usd_m"])),
                         c["advertising_growth_printed_pct"])

    def test_the_regional_chart_draws_the_printed_growth(self) -> None:
        """The chart used to draw growth computed from the customer-address
        table (29.3 / 25.9 / 25.0 / 35.1) under a title about growth, while the
        10-Q prints 32 / 24 / 19 / 36 on the user-geography basis. The page now
        draws what the company prints, and names the other basis."""
        chart = next(ex for ex in self.exhibits if ex["title"].startswith("本季四大区域收入同比"))
        printed = self.checks["user_geography_yoy_pct"]
        self.assertEqual(dict(zip(chart["xlabels"], chart["values"])), printed)
        self.assertIn("客户所在地", chart["note"])

    def test_every_threshold_value_matches_the_series(self) -> None:
        """A threshold's `actual` / `current` typed into the stamped block has to
        be the number the series gives -- lesson of the SCHW roll, where a typed
        current value flipped the verdict."""
        q = self.q
        revenue, oi = q["revenue_total"], q["operating_income"]
        snap = self.source["quarter_snapshot"]
        adjusted = oi[-1] + sum(item["usd_m"] for item in snap["one_off_items"])
        ads = self.source["advertising_metrics"]
        history = self.source["quarterly_guidance_history"]
        year = self.checks["period"].split()[1]
        capex = [call for call in history["capex_guidance_calls"] if call["year"] == year][-1]
        base = self.source["annual_actuals_usd_m"][str(int(year) - 1)]
        expected = {
            "FY2026 CapEx 指引中点": (capex["low"] + capex["high"]) / 2,
            "平均每条广告价格 YoY": ads["price_per_ad_yoy_pct"][-1],
            "Reality Labs 单季收入": q["reality_labs_revenue"][-1],
            "FoA Other 收入 YoY": pct(q["foa_other_revenue"][-1], q["foa_other_revenue"][-5]),
            "经营利润率（调整后）": adjusted / revenue[-1] * 100,
            "同比增量经营利润率": (adjusted - oi[-5]) / (revenue[-1] - revenue[-5]) * 100,
            "广告量价乘积（隐含收入增速）": ((1 + ads["ad_impressions_yoy_pct"][-1] / 100)
                                   * (1 + ads["price_per_ad_yoy_pct"][-1] / 100) - 1) * 100,
            "FoA Other 单季收入": q["foa_other_revenue"][-1],
            "单季经营利润 vs FY2025 季均线": oi[-1],
        }
        for block, key in (("prior_kpi_settlement", "actual"), ("next_kpi", "current")):
            for entry in self.source[block]["quantified"]:
                with self.subTest(block=block, metric=entry["metric"]):
                    self.assertIn(entry["metric"], expected)
                    self.assertAlmostEqual(entry[key], expected[entry["metric"]], places=1)
        threshold = next(e for e in self.source["next_kpi"]["quantified"] if "季均线" in e["metric"])
        self.assertAlmostEqual(threshold["threshold"], base["operating_income"] / 4, places=0)

    def test_the_page_prints_the_checked_figures(self) -> None:
        c = self.checks
        self.assertIn(f"收入 ${c['revenue_usd_m']:,}M", self.payload["headline"])
        fcf = next(ex for ex in self.exhibits if ex["title"].startswith("单季自由现金流"))
        self.assertIn(f"${c['free_cash_flow_usd_m']:,}M", fcf["title"])
        quality = next(t for t in self.payload["tables"] if t["title"].startswith("当季经营质量"))
        rows = {row[0]: row for row in quality["rows"]}
        self.assertEqual(rows["稀释 EPS"][3], f"${c['diluted_eps_usd']:.2f}")
        self.assertEqual(rows["员工数"][3], f"{c['headcount']:,}")
        self.assertEqual(rows["广告收入"][3], f"${c['advertising_revenue_usd_m']:,}M")


def pct(current: float, base: float) -> float:
    return (current / base - 1) * 100


class MetaRollTest(unittest.TestCase):
    """What a quarter roll can and cannot get past."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "meta.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)

    def test_a_block_stamped_with_another_quarter_stops_the_build(self) -> None:
        for key in STAMPED:
            stale = copy.deepcopy(self.source)
            stale[key]["period"] = "Q1 1999"
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    build_payload(stale)
        stale = copy.deepcopy(self.source)
        stale["quarter_snapshot"]["columns"] = ["Q1 2026", "Q4 2025", "Q1 2025"]
        with self.assertRaisesRegex(ValueError, "columns"):
            build_payload(stale)

    def test_a_missing_quarter_block_leaves_its_part_out(self) -> None:
        bare = copy.deepcopy(self.source)
        for key in STAMPED:
            del bare[key]
        payload = build_payload(bare)
        self.assertEqual([s["id"] for s in payload["sections"]], ["settled", "quarter_highlights", "routine"])
        text = published_text(payload)
        for gone in ("财报后股价", "当季经营质量", "本季四大区域", "费用线", "待验证问题", "剔除 $3,580M"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, text)

    def test_the_quarter_release_must_be_in_the_sources(self) -> None:
        missing = copy.deepcopy(self.source)
        period = missing["latest"]["period"]
        missing["sources"] = [s for s in missing["sources"] if not s["label"].startswith(period)]
        with self.assertRaisesRegex(ValueError, "sources"):
            build_payload(missing)

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        """Change the one fact each claim rests on; the claim must go with it."""
        before = published_text(self.payload)
        cases = []

        missed = copy.deepcopy(self.source)
        history = missed["quarterly_guidance_history"]
        at = history["quarters"].index("2023Q1")
        history["actual_revenue_usd_bn"][at] = history["guide_low_usd_bn"][at] - 0.5
        cases.append(("a quarter under the guided floor", missed,
                      ["下限从未被测试过", "没有一季跌破下限"]))

        no_precedent = copy.deepcopy(self.source)
        long = no_precedent["long_history"]
        long["operating_cash_flow_usd_m"][long["quarters"].index("2020Q2")] += 5000
        cases.append(("no earlier low-FCF quarter while growing", no_precedent, ["此前还有 Q2'20"]))

        foa = copy.deepcopy(self.source)
        long = foa["long_history"]
        long["foa_other_revenue_usd_m"][long["quarters"].index("2025Q4")] = 1100.0
        cases.append(("FoA Other past $1B before", foa, ["首破 $10 亿"]))

        price_fell = copy.deepcopy(self.source)
        price_fell["long_history"]["price_per_ad_yoy_pct"][-1] = 10.0
        cases.append(("price slowed too", price_fell, ["广告减速全部来自量"]))

        cut = copy.deepcopy(self.source)
        calls = cut["quarterly_guidance_history"]["capex_guidance_calls"]
        calls[-1]["low"], calls[-1]["high"] = 110.0, 130.0
        cases.append(("a capex cut", cut, ["半年内两次上调", "资本开支的两次上调", "抬高下限"]))

        three = copy.deepcopy(self.source)
        for entry in three["next_kpi"]["quantified"]:
            if entry["metric"] == "FoA Other 单季收入":
                entry["current"] = entry["threshold"] + 100
        cases.append(("only the two profit lines below", three, ["三条已在阈值之下"]))

        ttm = copy.deepcopy(self.source)
        long = ttm["long_history"]
        long["operating_cash_flow_usd_m"][-1] += 20000
        cases.append(("TTM kept rising", ttm, ["拐点出现在上一季"]))

        for name, series, claims in cases:
            after = published_text(build_payload(series))
            for claim in claims:
                with self.subTest(case=name, claim=claim):
                    self.assertIn(claim, before)
                    self.assertNotIn(claim, after)

    def test_the_counted_sentences_follow_the_record(self) -> None:
        """Counts the page used to type: the regimes of the ad engine, the
        stretches where depreciation outgrew revenue, the RL sign change."""
        text = published_text(self.payload)
        self.assertIn("答案换过六次", text)
        self.assertIn("折旧跑赢收入的有四段", text)
        self.assertIn("Reality Labs 收入同比 +16.5% 转正", text)
        self.assertNotIn("首次转正", text)
        # A Reality Labs record with no earlier positive quarter would say 首次.
        first = copy.deepcopy(self.source)
        long = first["long_history"]
        reality = long["reality_labs_revenue_usd_m"]
        start = long["quarters"].index(long["segment_first_reported"])
        for index in range(start, len(reality) - 1):
            reality[index] = 1000.0 - 10 * (index - start)     # shrinking every quarter
        reality[-1] = 5000.0
        first["quarterly_usd_m"]["reality_labs_revenue"] = reality[-12:]
        self.assertIn("首次转正", published_text(build_payload(first)))


if __name__ == "__main__":
    unittest.main()
