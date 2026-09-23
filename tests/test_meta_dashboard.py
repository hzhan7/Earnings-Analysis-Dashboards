"""Checks for the META page.

The three things worth pinning here are the ones a quarter roll can silently
break: the revenue lines must still add back to the reported total, the
volume/price bridge must still close against reported advertising growth, and
the adjusted figures the thresholds are settled on must still match the numbers
actually plotted.  Everything else on the page is a chart of a reported series.
"""

from __future__ import annotations

import copy
import html
import json
import math
import re
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import cn_count, headroom  # noqa: E402
from build.meta import build_payload  # noqa: E402

WINDOW = 8

# Which threshold readings have a quarterly record to draw under their lines.
# Declared here rather than read from the builder: a test that asked the builder
# which lines it charts could not notice the builder dropping one.
CHARTED_MEASURES = {"price_per_ad_yoy", "ad_impressions_yoy", "reality_labs_revenue",
                    "foa_other_revenue", "foa_other_revenue_yoy", "operating_margin_adjusted",
                    "incremental_margin_qoq_adjusted", "operating_income"}
OPS = {"≥": lambda v, t: v >= t, ">": lambda v, t: v > t, "≤": lambda v, t: v <= t, "<": lambda v, t: v < t}


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


def one_offs_of(source: dict, period: str) -> list[dict]:
    return source.get("operating_income_one_offs", {}).get("by_period", {}).get(period, [])


def independent_readings(source: dict, entry: dict) -> list[float | None]:
    """The record a threshold line is settled on, recomputed here from the series
    without the builder's help: the last element is this quarter's reading."""
    long = source["long_history"]
    quarters, revenue, operating = long["quarters"], long["revenue_usd_m"], long["operating_income_usd_m"]
    adjusted = [income + sum(item["usd_m"] for item in one_offs_of(source, f"Q{q[-1]} {q[:4]}"))
                for q, income in zip(quarters, operating)]

    def growth(values):
        return [None] * 4 + [None if now is None or not before else (now / before - 1) * 100
                             for before, now in zip(values, values[4:])]

    margin = [a / r * 100 for a, r in zip(adjusted, revenue)]
    records = {
        "price_per_ad_yoy": long["price_per_ad_yoy_pct"],
        "ad_impressions_yoy": long["ad_impressions_yoy_pct"],
        "reality_labs_revenue": long["reality_labs_revenue_usd_m"],
        "reality_labs_revenue_yoy": growth(long["reality_labs_revenue_usd_m"]),
        "foa_other_revenue": long["foa_other_revenue_usd_m"],
        "foa_other_revenue_yoy": growth(long["foa_other_revenue_usd_m"]),
        "operating_margin_adjusted": margin,
        "operating_margin_adjusted_qoq_pp": [None] + [b - a for a, b in zip(margin, margin[1:])],
        "incremental_margin_qoq_adjusted": [None] + [
            None if r1 <= r0 else (a1 - a0) / (r1 - r0) * 100
            for a0, a1, r0, r1 in zip(adjusted, adjusted[1:], revenue, revenue[1:])],
        "operating_income": operating,
    }
    if entry["measure"] in records:
        return list(records[entry["measure"]])
    released = source["latest"]["release_date"]
    calls = [c for c in source["quarterly_guidance_history"]["capex_guidance_calls"]
             if c["year"] == entry.get("year") and c["filed"] <= released]
    calls.sort(key=lambda c: c["filed"])
    annual = source["annual_actuals_usd_m"].get(entry.get("year") or "")
    if entry["measure"] == "capex_guide_mid":
        return [(calls[-1]["low"] + calls[-1]["high"]) / 2 if calls else None]
    if entry["measure"] == "capex_guide_first_mid":
        return [(calls[0]["low"] + calls[0]["high"]) / 2 if calls else None]
    if entry["measure"] == "fy_capex":
        if annual:
            return [(annual["purchases_of_property_and_equipment"] + annual["finance_lease_principal"]) / 1000]
        return [(calls[-1]["low"] + calls[-1]["high"]) / 2 if calls else None]
    if entry["measure"] == "fy_operating_income":
        return [annual["operating_income"] if annual else None]
    if entry["measure"] == "cumulative_rvg":
        return [sum(item["usd_bn"] for item in source["off_balance_sheet"]["residual_value_guarantees"])]
    raise AssertionError(f"no independent reading for {entry['measure']}")


def threshold_text(entry: dict) -> str:
    """How the page prints a line's threshold, in its own unit."""
    value = entry["threshold"]
    text = {"pct": f"{value:g}%", "pp": f"{value:g}pp", "usd_m": f"${value:,.0f}M",
            "usd_bn": f"${value:g}B"}[entry["unit"]]
    return text.replace("-", "−")


def quarter_key(period: str) -> str:
    """``'Q2 2026'`` → ``'2026Q2'``."""
    quarter, year = period.split()
    return f"{year}{quarter}"


def favourable_side(entry: dict) -> str:
    """Which side of a line is good news: above for a target it is good to reach from
    below or a warning that fires on the way down, below otherwise."""
    rising = entry["fires"] in ("≥", ">")
    return "up" if rising == (entry["kind"] == "target") else "down"


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

    def test_the_segment_lines_close_on_revenue_across_the_whole_record(self) -> None:
        """Advertising (its own filed line) plus the two segment revenue lines is total
        revenue, in every quarter the segments exist -- not only the reviewed twelve.

        The agreement check above covers the twelve-quarter window, and a wrong cell
        outside it hid: 2020Q4 carried 2021Q3's segment figures (558 / 176) while the
        Q4 2021 release prints 717 / 168 for that quarter. Only this sum saw it."""
        long = self.source["long_history"]
        for quarter, ads, reality, other, total in zip(
                long["quarters"], long["advertising_revenue_usd_m"], long["reality_labs_revenue_usd_m"],
                long["foa_other_revenue_usd_m"], long["revenue_usd_m"]):
            if reality is None:
                continue
            self.assertEqual(ads + reality + other, total, quarter)

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
        def charted(block: str) -> set:
            return {e["measure"] for e in self.source[block]["quantified"] if e["measure"] in CHARTED_MEASURES
                    and independent_readings(self.source, e)[-1] is not None}

        period = self.source["latest"]["period"]
        highlights = (4 + ("quarter_geography" in self.source) + bool(one_offs_of(self.source, period))
                      + ("market_expectation" in self.source and "quarter_snapshot" in self.source)
                      + ("leases_not_yet_commenced" in self.source) + 1)
        self.assertEqual(
            [(section["id"], len(section["exhibits"])) for section in self.payload["sections"]],
            [("settled", 1 + 1 + len(charted("prior_kpi_settlement")) + 2), ("quarter_highlights", highlights),
             ("next_quarter", 1 + len(charted("next_kpi"))), ("routine", 3)],
        )

    def test_the_prior_overview_puts_every_single_reading_line_on_its_bars(self) -> None:
        """Each bar is one line of last quarter's section 8, at the distance its own
        reading -- recomputed here -- sits from it, positive on the favourable side."""
        entries = self.source["prior_kpi_settlement"]["quantified"]
        exhibit = next(ex for ex in self.by_section["settled"] if ex["kind"] == "diverging_bars")
        expected = []
        for entry in entries:
            reading = independent_readings(self.source, entry)[-1]
            if reading is None or entry["threshold"] == 0 or entry.get("consecutive", 1) > 1:
                continue
            expected.append(round(headroom(favourable_side(entry), entry["threshold"], reading), 1))
        self.assertEqual(len(exhibit["values"]), len(expected))
        for plotted, value in zip(exhibit["values"], expected):
            self.assertAlmostEqual(plotted, value, places=6)
        # every line the bars leave out is still accounted for in the caption
        caption = html.unescape(exhibit["note"])
        for entry in entries:
            reading = independent_readings(self.source, entry)[-1]
            if reading is None or entry["threshold"] == 0 or entry.get("consecutive", 1) > 1:
                self.assertIn(entry["fires"] + threshold_text(entry), caption, entry["id"])

    def test_headroom_bars_reproduce_the_thresholds(self) -> None:
        """Section three's bars: one per line with a single current reading, at the
        distance that reading -- recomputed here -- sits from it, and a title that
        counts the two sides the way the bars show them."""
        entries = self.source["next_kpi"]["quantified"]
        exhibit = self.by_section["next_quarter"][0]
        self.assertEqual(exhibit["kind"], "diverging_bars")
        expected = []
        for entry in entries:
            reading = independent_readings(self.source, entry)[-1]
            if reading is None or entry["threshold"] == 0 or entry.get("consecutive", 1) > 1:
                continue
            expected.append(round(headroom(favourable_side(entry), entry["threshold"], reading), 1))
        self.assertEqual(len(exhibit["values"]), len(expected))
        for plotted, value in zip(exhibit["values"], expected):
            self.assertAlmostEqual(plotted, value, places=6)
        # A reading exactly on an inclusive line is on the favourable side of it:
        # the comparator decides, and the bar is drawn at zero.
        good = sum(1 for value in expected if value >= 0)
        self.assertTrue(exhibit["title"].startswith(
            f"下季 {len(expected)} 条阈值：当前 {good} 条在有利一侧、{len(expected) - good} 条在不利一侧"),
            exhibit["title"])
        self.assertFalse(any(str(v) == "-0.0" for v in exhibit["values"]), exhibit["values"])
        caption = html.unescape(exhibit["note"])
        for entry in entries:
            reading = independent_readings(self.source, entry)[-1]
            if reading is None or entry["threshold"] == 0 or entry.get("consecutive", 1) > 1:
                self.assertIn(entry["fires"] + threshold_text(entry), caption, entry["id"])
        for item in self.source["next_kpi"].get("gated", []):
            self.assertIn(item["text"], caption)

    def test_every_tracked_metric_with_a_series_gets_its_own_chart(self) -> None:
        """Each reading with a record is drawn over its whole history under every line
        the report put on it, in both section one and section three."""
        for section, block in (("settled", "prior_kpi_settlement"), ("next_quarter", "next_kpi")):
            lead = "上季" if section == "settled" else "下季"
            drawn = {}
            for exhibit in self.by_section[section]:
                if exhibit["kind"] != "lines":
                    continue
                for series in exhibit.get("series", []):
                    if series["name"].startswith(lead):
                        self.assertEqual(len(set(series["values"])), 1, exhibit["title"])
                        self.assertEqual(len(series["values"]), len(exhibit["xlabels"]), exhibit["title"])
                        drawn.setdefault(exhibit["title"], []).append(series["values"][0])
            want = sorted(e["threshold"] for e in self.source[block]["quantified"]
                          if e["measure"] in CHARTED_MEASURES and independent_readings(self.source, e)[-1] is not None)
            self.assertEqual(sorted(v for values in drawn.values() for v in values), want, section)
            # the full record, from the first quarter of the long history
            for title in drawn:
                exhibit = next(ex for ex in self.by_section[section] if ex["title"] == title)
                self.assertEqual(len(exhibit["xlabels"]), len(self.source["long_history"]["quarters"]), title)

    def test_adjusted_lines_match_the_value_the_threshold_is_settled_on(self) -> None:
        """Two thresholds are settled on the adjusted basis while the plotted
        history is GAAP. If the short adjusted line drifts from the stated
        current value, the chart contradicts its own caption."""
        checks = self.source["_checks"]
        revenue = self.q["revenue_total"]
        operating_income = self.q["operating_income"]
        one_offs = one_offs_of(self.source, self.source["latest"]["period"])
        adjusted = operating_income[-1] + sum(item["usd_m"] for item in one_offs)
        self.assertEqual(
            adjusted,
            checks["operating_income_usd_m"]
            + checks["legal_proceedings_charge_usd_m"]
            + checks["severance_charge_usd_m"],
        )

        margin_chart = next(ex for ex in self.by_section["settled"]
                            if ex["kind"] == "lines" and ex["title"].startswith("经营利润率"))
        tail = next(series for series in margin_chart["series"] if series["name"].startswith("调整后"))
        self.assertEqual(tail["values"][-1], round(adjusted / revenue[-1] * 100, 2))
        self.assertEqual(tail["values"][-2], round(margin_chart["series"][0]["values"][-2], 2))
        # The gold line exists only for the two quarters that have an adjusted
        # reading; everything before it is a hole, however long the axis is now.
        self.assertEqual(tail["values"][:-2], [None] * (len(tail["values"]) - 2))
        self.assertGreaterEqual(len(tail["values"]), WINDOW)

        # The next-quarter incremental margin is quarter on quarter, as the report
        # wrote it: last quarter's adjusted operating income is the base.
        incremental_chart = next(
            ex for ex in self.by_section["next_quarter"] if ex["title"].startswith("调整后环比增量经营利润率")
        )
        prior_adjusted = operating_income[-2] + sum(
            item["usd_m"] for item in one_offs_of(self.source, self.source["periods"][-2]))
        if revenue[-1] > revenue[-2]:
            expected = (adjusted - prior_adjusted) / (revenue[-1] - revenue[-2]) * 100
            gold = next(s for s in incremental_chart["series"] if s["name"].startswith("调整后"))
            self.assertEqual(gold["values"][-1], round(expected, 2))
            self.assertIn(f"当前 {expected:+.1f}%".replace("-", "−"), incremental_chart["title"])

    def test_audit_tables_back_every_derived_exhibit(self) -> None:
        tables = self.payload["tables"]
        first = len(self.exhibits) + 2
        self.assertEqual([table["n"] for table in tables], list(range(first, first + len(tables))))
        self.assertIn("AI capex", tables[-1]["title"])
        by_title = {table["title"]: table for table in tables}
        closure = next(t for title, t in by_title.items() if "待验证问题" in title)
        self.assertEqual(len(closure["rows"]), len(self.source["followup_closure"]["items"]))
        prior = next(t for title, t in by_title.items() if "逐档结算" in title)
        self.assertEqual(len(prior["rows"]), len(self.source["prior_kpi_settlement"]["quantified"]))
        rows = next(t for title, t in by_title.items() if "第 8 节原文" in title)
        self.assertEqual(len(rows["rows"]), len(self.source["prior_kpi_settlement"]["rows"]))
        nxt = next(t for title, t in by_title.items() if title.startswith("下季阈值"))
        self.assertEqual(len(nxt["rows"]), len(self.source["next_kpi"]["quantified"]))
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


REQUIRED = ("followup_closure", "prior_kpi_settlement", "next_kpi")
OPTIONAL = ("market_expectation", "outlook", "quarter_snapshot", "quarter_geography",
            "quarter_expense_lines_usd_m", "off_balance_sheet")
STAMPED = REQUIRED + OPTIONAL


def published_text(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def scrubbed(source: dict, keys: list[str]) -> dict:
    """The series with the story placeholders ``{key}`` blanked out of every text."""
    text = json.dumps(source, ensure_ascii=False)
    for key in keys:
        text = text.replace("{" + key + "}", "—")
    return json.loads(text)


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
        one_offs = {item["name"]: item["usd_m"] for item in one_offs_of(self.source, c["period"])}
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
        chart = next(ex for ex in self.exhibits
                     if ex["kind"] == "bars_labeled" and "美国与加拿大" in ex.get("xlabels", []))
        printed = self.checks["user_geography_yoy_pct"]
        self.assertEqual(dict(zip(chart["xlabels"], chart["values"])), printed)
        self.assertIn("客户所在地", chart["note"])
        # the title's reading is the growth of the region the 10-Q names, and its rank
        led = self.source["quarter_geography"].get("impressions_led_by")
        if led:
            self.assertIn(f"{led}收入同比", chart["title"])
            self.assertIn(f"{printed[led]:g}%", chart["title"])
            if printed[led] == min(printed.values()):
                self.assertIn("最低", chart["title"])
            else:
                self.assertNotIn("最低", chart["title"])

    def test_every_threshold_value_matches_the_series(self) -> None:
        """No threshold carries a typed reading: a typed current value next to the
        series is a second copy that can disagree -- lesson of the SCHW roll, where
        a typed current value flipped the verdict. The page prints each reading the
        series gives, recomputed here."""
        for block, key, title in (("prior_kpi_settlement", "actual", "逐档结算"),
                                  ("next_kpi", "current", "下季阈值与当前值")):
            table = next(t for t in self.payload["tables"] if title in t["title"])
            entries = self.source[block]["quantified"]
            self.assertEqual(len(table["rows"]), len(entries))
            for entry, row in zip(entries, table["rows"]):
                with self.subTest(block=block, line=entry["id"]):
                    self.assertFalse({"actual", "current"} & set(entry))
                    reading = independent_readings(self.source, entry)[-1]
                    if reading is None:
                        self.assertEqual(row[3], "—")
                        continue
                    printed = float(re.sub(r"[^\d.−-]", "", row[3]).replace("−", "-"))
                    digits = len(row[3].split(".")[1].rstrip("%BMpp")) if "." in row[3] else 0
                    self.assertAlmostEqual(printed, reading, delta=0.5 * 10 ** -digits + 1e-9)

    def test_the_10q_facts_behind_the_off_balance_lines(self) -> None:
        """The guarantee line and the lease chart read what the 10-Q prints."""
        c = self.checks
        rvg = {item["key"]: item["usd_bn"] for item in self.source["off_balance_sheet"]["residual_value_guarantees"]}
        self.assertEqual(rvg, {"rvg_louisiana": c["louisiana_rvg_threshold_usd_bn"],
                               "rvg_el_paso": c["el_paso_rvg_max_usd_bn"]})
        leases = self.source["leases_not_yet_commenced"]
        self.assertEqual(leases["total_usd_bn"][-1], c["leases_not_yet_commenced_usd_bn"])
        year_end = leases["quarters"].index(f"{int(c['period'][-4:]) - 1}Q4")
        self.assertEqual(leases["total_usd_bn"][year_end], c["leases_not_yet_commenced_year_end_usd_bn"])
        self.assertEqual(self.source["off_balance_sheet"]["leases_signed_after_quarter_usd_bn"],
                         c["leases_signed_after_quarter_usd_bn"])
        self.assertEqual(self.source["off_balance_sheet"]["restricted_escrow_usd_bn"], c["restricted_escrow_usd_bn"])
        # the record adds the two legs where the filing gives two
        for total, op, fin in zip(leases["total_usd_bn"], leases["operating_usd_bn"], leases["finance_usd_bn"]):
            if op is not None and fin is not None:
                self.assertAlmostEqual(total, op + fin, places=6)
        chart = next(ex for ex in self.exhibits if ex["title"].startswith("已签约未起租的租赁义务"))
        self.assertIn(f"US${c['leases_not_yet_commenced_usd_bn']:.2f}B", chart["title"])
        self.assertEqual(chart["xlabels"][0], "Q1'19")
        quality = next(t for t in self.payload["tables"] if t["title"].startswith("当季经营质量"))
        restricted = next(row for row in quality["rows"] if row[0].startswith("其他资产项下的受限现金"))
        self.assertIn(f"${c['restricted_escrow_usd_bn']:.2f}B", restricted[-1])
        self.assertNotIn("未解释", json.dumps(self.payload, ensure_ascii=False))

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


class MetaReportTest(unittest.TestCase):
    """Section one and three against the two local analyses, as `_checks.note` records them.

    The note is typed from the reports themselves -- this quarter's section 0 and
    section 8, last quarter's section 8 -- separately from the stamped blocks the
    builder reads, and the builder never reads it. A roll re-keys the note with
    the new reports; this class does not change.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "meta.json").read_text(encoding="utf-8"))
        cls.note = cls.source["_checks"]["note"]
        cls.payload = build_payload(cls.source)
        cls.by_section = {s["id"]: s["exhibits"] for s in cls.payload["sections"]}
        cls.tables = {t["title"]: t for t in cls.payload["tables"]}

    def test_the_note_names_the_reports_for_this_quarter_and_the_last(self) -> None:
        latest = self.source["latest"]
        self.assertEqual(self.note["report"], {"period_end": latest["period_end"],
                                               "release_date": latest["release_date"]})
        self.assertIn(latest["period"], self.note["source"]["this_quarter"])
        prior = self.source["prior_kpi_settlement"]["set_in"]
        self.assertIn(prior, self.note["source"]["previous_quarter"])
        self.assertEqual(self.source["followup_closure"]["set_in"], prior)

    def test_the_closure_is_section_zero_as_written(self) -> None:
        closure = self.source["followup_closure"]
        expected = self.note["followup_closure"]
        self.assertEqual([item["wording"] for item in closure["items"]], expected["wordings"])
        self.assertEqual(len(closure["items"]), expected["total"])
        chart = self.by_section["settled"][0]
        counts = dict(zip(chart["xlabels"], chart["values"]))
        self.assertEqual({k: v for k, v in counts.items() if v}, expected["counts"])
        self.assertEqual(sum(chart["values"]), expected["total"])
        # the title names every verdict the section uses, not just the flattering ones
        self.assertTrue(chart["title"].startswith(f"上季 {expected['total']} 条待验证问题："))
        for label, count in expected["counts"].items():
            self.assertIn(f"{count} 条{label}", chart["title"])
        # the classification rule is printed, since the section has no tally row
        self.assertIn("归类", chart["note"])
        table = next(t for title, t in self.tables.items() if "待验证问题" in title)
        self.assertEqual([row[2] for row in table["rows"]], expected["wordings"])

    def test_last_quarters_lines_are_its_section_8_tier_by_tier(self) -> None:
        prior = self.source["prior_kpi_settlement"]
        self.assertEqual(len(prior["rows"]), self.note["prior_rows"])
        got = sorted((str(e["row"]), e["fires"], e["threshold"], e.get("consecutive", 1))
                     for e in prior["quantified"])
        want = sorted((str(e["row"]), e["fires"], e["threshold"], e.get("consecutive", 1))
                      for e in self.note["prior_thresholds"])
        self.assertEqual(got, want)

    def test_this_quarters_lines_are_its_section_8_tier_by_tier(self) -> None:
        """Section three is this report's section 8 and revocation conditions, every tier
        a line; nothing the page set itself (the old 「FY2025 季均线」 is gone)."""
        nxt = self.source["next_kpi"]
        self.assertEqual(len(nxt["rows"]), self.note["next_rows"])
        got = sorted((str(e["row"]), e["fires"], e["threshold"], e.get("consecutive", 1))
                     for e in nxt["quantified"])
        got += sorted((str(g["row"]), g["fires"], g["threshold"], 1) for g in nxt.get("gated", []))
        want = sorted((str(e["row"]), e["fires"], e["threshold"], e.get("consecutive", 1))
                      for e in self.note["next_thresholds"])
        self.assertEqual(sorted(got), want)
        self.assertNotIn("季均线", json.dumps(self.payload, ensure_ascii=False))
        # the incremental margin is settled quarter on quarter, as the row says
        rows = {row["row"]: row for row in nxt["rows"]}
        for entry in nxt["quantified"]:
            if entry["measure"] == "incremental_margin_qoq_adjusted":
                self.assertIn("QoQ", rows[entry["row"]]["text"])
        # every revocation condition names lines the block carries (or a gated item)
        ids = {e["id"] for e in nxt["quantified"]}
        for item in nxt.get("revocation", []):
            self.assertTrue(set(item["lines"]) <= ids, item)

    def test_a_target_is_reached_or_missed_and_a_warning_held_or_broken(self) -> None:
        """A line set above where the metric stood is a target: missing it is not a breach."""
        table = next(t for title, t in self.tables.items() if "逐档结算" in title)
        entries = self.source["prior_kpi_settlement"]["quantified"]
        self.assertEqual(len(table["rows"]), len(entries))
        for entry, row in zip(entries, table["rows"]):
            verdict = row[-1]
            reading = independent_readings(self.source, entry)[-1]
            with self.subTest(line=entry["id"]):
                if reading is None:
                    self.assertTrue(verdict.startswith(("读不到", "待 ")), verdict)
                    continue
                if entry.get("consecutive", 1) > 1:
                    run = independent_readings(self.source, entry)[-entry["consecutive"]:]
                    fired = all(v is not None and OPS[entry["fires"]](round(v, 6), entry["threshold"]) for v in run)
                    self.assertTrue(verdict.endswith("未触发" if not fired else "触发"), verdict)
                    continue
                fired = OPS[entry["fires"]](round(reading, 6), entry["threshold"])
                if entry["kind"] == "target":
                    self.assertNotIn("击穿", verdict)
                    self.assertNotIn("守住", verdict)
                    if fired:
                        self.assertIn("达到", verdict)
                        self.assertNotIn("未达到", verdict)
                    else:
                        self.assertIn("未达到", verdict)
                else:
                    self.assertNotIn("达到", verdict)
                    if fired:
                        self.assertTrue("击穿" in verdict or "压线触发" in verdict, verdict)
                    else:
                        self.assertIn("守住", verdict)


class MetaRollTest(unittest.TestCase):
    """What a quarter roll can and cannot get past."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "meta.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)
        cls.q_income = cls.source["quarterly_usd_m"]["operating_income"]
        cls.year = cls.source["latest"]["period"][-4:]

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

    def test_a_missing_optional_block_leaves_its_part_out(self) -> None:
        # This quarter's closure evidence names the snapshot's headcount cut by key;
        # blank it, since a quarter without the snapshot would say something else.
        bare = scrubbed(copy.deepcopy(self.source), ["positions"])
        for key in OPTIONAL:
            del bare[key]
        # the guarantee line reads the off-balance block; without it the line has no reading
        bare["next_kpi"]["quantified"] = [e for e in bare["next_kpi"]["quantified"]
                                          if e["measure"] != "cumulative_rvg"]
        payload = build_payload(bare)
        self.assertEqual([s["id"] for s in payload["sections"]],
                         ["settled", "quarter_highlights", "next_quarter", "routine"])
        text = published_text(payload)
        for gone in ("财报后股价", "当季经营质量", "曝光增长尤其在", "费用线", "对市场预期", "残值担保（RVG）"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, text)

    def test_a_missing_required_block_stops_the_build(self) -> None:
        """Every quarter settles the previous analysis and places its own: a roll that
        leaves one of the three blocks out stops rather than dropping a section."""
        for key in REQUIRED:
            bare = copy.deepcopy(self.source)
            del bare[key]
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "required every quarter"):
                    build_payload(bare)
        stale = copy.deepcopy(self.source)
        stale["next_kpi"]["for_period"] = stale["latest"]["period"]
        with self.assertRaisesRegex(ValueError, "set for"):
            build_payload(stale)
        stale = copy.deepcopy(self.source)
        stale["prior_kpi_settlement"]["set_in"] = stale["latest"]["period"]
        with self.assertRaisesRegex(ValueError, "settles what"):
            build_payload(stale)

    def test_a_line_that_falls_due_without_a_reading_stops_the_build(self) -> None:
        """A full-year line waits for its quarter; once that quarter comes, the figure
        it settles on has to be in the series."""
        due = copy.deepcopy(self.source)
        period = due["latest"]["period"]
        entry = next(e for e in due["next_kpi"]["quantified"] if e.get("settles"))
        entry["settles"] = period
        with self.assertRaisesRegex(ValueError, "settles in"):
            build_payload(due)
        unexplained = copy.deepcopy(self.source)
        entry = next(e for e in unexplained["next_kpi"]["quantified"] if e.get("settles"))
        del entry["settles"]
        with self.assertRaisesRegex(ValueError, "no reading"):
            build_payload(unexplained)
        mute = copy.deepcopy(self.source)
        self.assertTrue(any(e["measure"] == "cumulative_rvg" for e in mute["next_kpi"]["quantified"]))
        del mute["off_balance_sheet"]
        with self.assertRaisesRegex(ValueError, "off_balance_sheet"):
            build_payload(mute)

    def test_a_quarter_without_one_offs_draws_no_adjusted_figures(self) -> None:
        """The one-off record is keyed by quarter; a quarter it does not list is GAAP throughout."""
        period = self.source["latest"]["period"]
        total = sum(item["usd_m"] for item in one_offs_of(self.source, period))
        plain = copy.deepcopy(self.source)
        plain["operating_income_one_offs"]["by_period"].pop(period, None)
        # This quarter's story text names the one-offs by key; a quarter without
        # them would come with its own text, so the keys are blanked here.
        keys = [item["key"] for item in one_offs_of(self.source, period) if item.get("key")]
        plain = scrubbed(plain, keys)
        after = published_text(build_payload(plain))
        self.assertNotIn("一次性项后，经营利润", after)
        if total:
            self.assertIn(f"剔除 ${total:,}M", published_text(self.payload))
            self.assertNotIn(f"剔除 ${total:,}M", after)

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
        cases.append(("a capex cut", cut, ["半年内两次上调", "资本开支指引的两次上调", "收窄的方式是抬高下限"]))

        # The joint add line on the ad bridge: both legs sit exactly on it this quarter.
        bridge = copy.deepcopy(self.source)
        bridge["long_history"]["ad_impressions_yoy_pct"][-1] -= 1
        bridge["advertising_metrics"]["ad_impressions_yoy_pct"][-1] -= 1
        cases.append(("impressions one point lower", bridge, ["两腿都已到"]))

        # How far the year's operating income still has to go is read off the half year.
        slower = copy.deepcopy(self.source)
        at = slower["long_history"]["quarters"].index(quarter_key(slower["latest"]["period"]))
        slower["long_history"]["operating_income_usd_m"][at] -= 1000
        slower["quarterly_usd_m"]["operating_income"][-1] -= 1000
        slower["quarterly_usd_m"]["costs_and_expenses"][-1] += 1000
        ytd = sum(v for p, v in zip(self.source["periods"], self.q_income) if p.endswith(self.year))
        need = self.source["annual_actuals_usd_m"][str(int(self.year) - 1)]["operating_income"] - ytd
        cases.append(("a weaker half year", slower, [f"至少要 ${need:,}M"]))

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
        """Counts the page used to type -- the regimes of the ad engine, the stretches
        where depreciation outgrew revenue, the RL sign change -- recounted here from
        the series, so the test says nothing that holds only this quarter."""
        text = published_text(self.payload)
        long = self.source["long_history"]
        leaders = [("价" if p > i else "量") for i, p in
                   zip(long["ad_impressions_yoy_pct"], long["price_per_ad_yoy_pct"])
                   if i is not None and p is not None and i != p]
        switches = sum(1 for a, b in zip(leaders, leaders[1:]) if a != b)
        self.assertIn(f"答案换过{cn_count(switches)}次", text)

        def growth(values):
            return [None] * 4 + [None if a is None or not b else (a / b - 1) * 100 for b, a in zip(values, values[4:])]

        gaps = [None if d is None or r is None else d - r for d, r in
                zip(growth(long["depreciation_and_amortization_usd_m"]), growth(long["revenue_usd_m"]))]
        stretches, inside = 0, False
        for gap in gaps:
            ahead = gap is not None and gap > 0
            stretches += ahead and not inside
            inside = ahead
        self.assertIn(f"折旧跑赢收入的有{cn_count(stretches)}段", text)

        rl = growth(long["reality_labs_revenue_usd_m"])
        now, before = rl[-1], rl[-2]
        word = ("首次转正" if now > 0 and all(v is None or v <= 0 for v in rl[:-1])
                else "转正" if now > 0 and before <= 0 else "为正" if now > 0
                else "转负" if before > 0 else "仍为负")
        self.assertIn(f"Reality Labs 收入同比 {now:+.1f}% {word}", text)
        # The 2025Q2 and 2025Q3 readings were already positive, so this quarter's
        # turn is not a first -- the local analysis wrote 「首次转正」.
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


# Flows scale with the season; rates and counts carry the same quarter a year back.
CARRIED = {"ad_impressions_yoy_pct", "price_per_ad_yoy_pct", "family_daily_active_people_bn"}
QUARTER_END = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}


def rolled_forward(source: dict) -> dict:
    """The series as a data-only roll to the next quarter would leave it, in memory.

    Every quarterly array gains one cell: a flow is last quarter's value times the
    move from the same quarter a year back to the one after it (so a quarter keeps
    its seasonal step), a rate or count carries the value a year back, and costs are
    revenue less operating income so the income statement still adds up. The
    twelve-quarter window drops its oldest cell; the ten-year record and the lease
    record just grow. The quarter just reported gets its guided-quarter actual and
    the next one a guide; the capex and expense calls gain the new release's (a
    fourth-quarter release also guides the next year's capex, and the closed year
    gets its annual totals). The one-quarter blocks go the way a roll takes them:
    the previous `next_kpi` moves, as it stood, into `prior_kpi_settlement`; a
    `followup_closure` judges rehearsal questions; `next_kpi` is re-stamped without
    the lines that have fallen due; the off-balance block is re-stamped; the
    narrative blocks are left out (a missing optional block leaves its part out).
    The quarter's story text that names this quarter's one-offs is blanked, since a
    real roll rewrites it. Nothing is written to disk.
    """
    one_off_keys = [item["key"] for items in source["operating_income_one_offs"]["by_period"].values()
                    for item in items if item.get("key")]
    s = scrubbed(copy.deepcopy(source), one_off_keys)
    period = s["latest"]["period"]
    quarter, year = int(period[1]), int(period[-4:])
    nq, ny = (1, year + 1) if quarter == 4 else (quarter + 1, year)
    new, key = f"Q{nq} {ny}", f"{ny}Q{nq}"
    fq, fy = (1, ny + 1) if nq == 4 else (nq + 1, ny)
    following, following_key = f"Q{fq} {fy}", f"{fy}Q{fq}"
    release = f"{ny + 1}-01-28" if nq == 4 else f"{ny}-{3 * nq + 1:02d}-28"

    def step(values: list, name: str):
        if name in CARRIED:
            return values[-4]
        return round(values[-1] * values[-4] / values[-5]) if values[-5] else values[-4]

    q = s["quarterly_usd_m"]
    new_q = {name: step(values, name) for name, values in q.items()}
    new_q["costs_and_expenses"] = new_q["revenue_total"] - new_q["operating_income"]
    new_q["stock_repurchases"] = 0
    for name in q:
        q[name] = q[name][1:] + [new_q[name]]
    ads = s["advertising_metrics"]
    for name, values in ads.items():
        if isinstance(values, list):
            ads[name] = values[1:] + [values[-4]]
    s["periods"] = s["periods"][1:] + [new]

    long = s["long_history"]
    tie = {"revenue_usd_m": "revenue_total", "operating_income_usd_m": "operating_income",
           "operating_cash_flow_usd_m": "operating_cash_flow",
           "capital_expenditures_usd_m": "purchases_of_property_and_equipment",
           "depreciation_and_amortization_usd_m": "depreciation_and_amortization",
           "finance_lease_principal_usd_m": "finance_lease_principal",
           "reality_labs_revenue_usd_m": "reality_labs_revenue", "foa_other_revenue_usd_m": "foa_other_revenue"}
    width = len(long["quarters"])
    for name, values in long.items():
        if not isinstance(values, list) or len(values) != width or name == "quarters":
            continue
        if name in tie:
            values.append(new_q[tie[name]])
        elif name in CARRIED:
            values.append(values[-4])
        elif name == "advertising_revenue_usd_m":
            values.append(new_q["revenue_total"] - new_q["reality_labs_revenue"] - new_q["foa_other_revenue"])
        else:
            values.append(values[-4])
    long["quarters"].append(key)
    leases = s["leases_not_yet_commenced"]
    lw = len(leases["quarters"])
    for name, values in leases.items():
        if isinstance(values, list) and len(values) == lw and name != "quarters":
            values.append(values[-1])
    leases["quarters"].append(key)

    history = s["quarterly_guidance_history"]
    history["actual_revenue_usd_bn"][history["quarters"].index(key)] = new_q["revenue_total"] / 1000
    guide = round(new_q["revenue_total"] / 1000)
    history["quarters"].append(following_key)
    history["guide_low_usd_bn"].append(float(guide))
    history["guide_high_usd_bn"].append(float(guide + 3))
    history["actual_revenue_usd_bn"].append(None)
    for calls in (history["capex_guidance_calls"], history["expense_guidance_calls"]):
        last = [c for c in calls if c["year"] == str(ny)][-1]
        calls.append({**last, "filed": release})
        if nq == 4:
            calls.append({"filed": release, "year": str(ny + 1), "low": last["low"] + 10, "high": last["high"] + 10})
    if nq == 4:
        in_year = [i for i, p in enumerate(s["periods"]) if p.endswith(str(ny))]
        s["annual_actuals_usd_m"][str(ny)] = {
            "revenue": sum(q["revenue_total"][i] for i in in_year),
            "operating_income": sum(q["operating_income"][i] for i in in_year),
            "depreciation_and_amortization": sum(q["depreciation_and_amortization"][i] for i in in_year),
            "share_based_compensation": sum(q["share_based_compensation"][i] for i in in_year),
            "purchases_of_property_and_equipment": sum(q["purchases_of_property_and_equipment"][i] for i in in_year),
            "finance_lease_principal": sum(q["finance_lease_principal"][i] for i in in_year),
        }

    s["latest"] = {**s["latest"], "period": new, "period_end": f"{ny}-{QUARTER_END[nq]}",
                   "release_date": release, "analysis_date": release}
    s["sources"].insert(0, {"label": f"{new} 业绩发布 8-K",
                            "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=1326801&type=8-K"})
    kpi = s["next_kpi"]
    labels = ["已验证", "部分验证", "被证伪", "仍未披露"]
    verdicts = ["已验证", "部分验证", "部分验证", "被证伪", "仍未披露"]
    s["followup_closure"] = {
        "period": new, "set_in": period, "labels": labels, "rule": "换季演练",
        "items": [{"n": n, "short": f"演练问题 {n}", "question": f"演练问题 {n}？", "wording": f"{v}（演练）",
                   "verdict": v, "evidence": "换季演练"} for n, v in enumerate(verdicts, 1)]}
    s["prior_kpi_settlement"] = {
        "period": new, "set_in": period,
        "rows": [{**row, "report_reading": "换季演练", "handling": "换季演练"} for row in kpi["rows"]],
        "quantified": copy.deepcopy(kpi["quantified"]),
        "text_legs": copy.deepcopy(kpi.get("text_legs", [])),
        "gated": copy.deepcopy(kpi.get("gated", [])),
    }

    def open_after(entry: dict) -> bool:
        if not entry.get("settles"):
            return True
        sq, sy = entry["settles"].split()
        return (int(sy), int(sq[1])) > (ny, nq)

    s["next_kpi"] = {**kpi, "period": new, "for_period": following,
                     "quantified": [e for e in kpi["quantified"] if open_after(e)]}
    s["off_balance_sheet"] = {**s["off_balance_sheet"], "period": new}
    for name in ("market_expectation", "outlook", "quarter_snapshot", "quarter_geography",
                 "quarter_expense_lines_usd_m"):
        s.pop(name, None)
    return s


class MetaRollDrillTest(unittest.TestCase):
    """Two quarters rolled forward by editing the series alone.

    From Q2 2026 that is Q3 2026, where last quarter's section 8 -- moved in as it
    stood -- is settled for the first time, and Q4 2026, where the two full-year
    operating-income lines fall due and settle on the year's totals. Neither roll
    touches build/meta.py or this file.
    """

    @classmethod
    def setUpClass(cls) -> None:
        source = json.loads((ROOT / "series" / "meta.json").read_text(encoding="utf-8"))
        cls.rolls = []
        for _ in range(2):
            source = rolled_forward(source)
            cls.rolls.append((source, build_payload(source)))

    def test_each_roll_builds_the_four_sections(self) -> None:
        for source, payload in self.rolls:
            with self.subTest(period=source["latest"]["period"]):
                self.assertEqual([(s["id"], s["title"]) for s in payload["sections"]],
                                 [("settled", "一、上季跟踪指标兑现了吗"), ("quarter_highlights", "二、本季重点"),
                                  ("next_quarter", "三、下季要跟踪什么"), ("routine", "四、长期常规跟踪")])
                self.assertIn(source["latest"]["period"], payload["title"])
                for section in payload["sections"]:
                    self.assertTrue(section["exhibits"], section["id"])

    def test_last_quarters_lines_are_settled_on_this_quarters_readings(self) -> None:
        for source, payload in self.rolls:
            with self.subTest(period=source["latest"]["period"]):
                settled = payload["sections"][0]["exhibits"]
                closure, overview = settled[0], settled[1]
                items = source["followup_closure"]["items"]
                self.assertTrue(closure["title"].startswith(f"上季 {len(items)} 条待验证问题："))
                entries = source["prior_kpi_settlement"]["quantified"]
                expected = []
                for entry in entries:
                    reading = independent_readings(source, entry)[-1]
                    if reading is None or entry["threshold"] == 0 or entry.get("consecutive", 1) > 1:
                        continue
                    expected.append(round(headroom(favourable_side(entry), entry["threshold"], reading), 1))
                self.assertEqual(len(overview["values"]), len(expected))
                for plotted, value in zip(overview["values"], expected):
                    self.assertAlmostEqual(plotted, value, places=6)
                # a charted reading gets its own line chart in section one, with 上季 lines
                charted = {e["measure"] for e in entries if e["measure"] in CHARTED_MEASURES
                           and independent_readings(source, e)[-1] is not None}
                lined = [ex for ex in settled if ex["kind"] == "lines"
                         and any(s["name"].startswith("上季") for s in ex.get("series", []))]
                self.assertEqual(len(lined), len(charted))

    def test_the_full_year_lines_wait_for_their_quarter_then_settle(self) -> None:
        def order(label: str) -> tuple[int, int]:
            quarter, year = label.split()
            return int(year), int(quarter[1])

        (q3, q3_payload), (q4, q4_payload) = self.rolls
        table = next(t for t in q3_payload["tables"] if "逐档结算" in t["title"])
        dated = [e for e in q3["prior_kpi_settlement"]["quantified"]
                 if e.get("settles") and order(e["settles"]) > order(q3["latest"]["period"])]
        self.assertTrue(dated)
        waiting = [row for row in table["rows"] if row[-1].startswith("待 ")]
        self.assertEqual(len(waiting), len(dated))
        # A quarter later the year has closed: the same lines are settled, not pending.
        table = next(t for t in q4_payload["tables"] if "逐档结算" in t["title"])
        self.assertFalse([row for row in table["rows"] if row[-1].startswith("待 ")])
        year = q4["latest"]["period"][-4:]
        settled = [e for e in q4["prior_kpi_settlement"]["quantified"] if e["measure"] == "fy_operating_income"]
        self.assertTrue(settled)
        for entry in settled:
            total = q4["annual_actuals_usd_m"][year]["operating_income"]
            fired = OPS[entry["fires"]](total, entry["threshold"])
            row = next(r for r in table["rows"] if r[2] == entry["fires"] + threshold_text(entry))
            if entry["kind"] == "warn":
                self.assertIn("击穿" if fired else "守住", row[-1])
            else:
                self.assertIn("达到" if fired else "未达到", row[-1])
        # ...and they left section three, which is set for the quarter after.
        self.assertFalse([e for e in q4["next_kpi"]["quantified"]
                          if e.get("settles") and order(e["settles"]) <= order(q4["latest"]["period"])])

    def test_a_rolled_page_keeps_the_window_ratchet_formula(self) -> None:
        """What `test_chart_window` pins for this page -- five permanent charts reaching
        2016 plus the threshold charts -- holds on the rolled pages too, and every
        short time axis still has a named reason."""
        import tests.test_chart_window as window

        for source, payload in self.rolls:
            with self.subTest(period=source["latest"]["period"]):
                exhibits = [ex for s in payload["sections"] for ex in s["exhibits"]]
                timed = [(ex, window.first_year(ex)) for ex in exhibits]
                timed = [(ex, y) for ex, y in timed if y is not None]
                threshold = sum(1 for ex, y in timed if y <= window.TARGET_YEAR and ex["kind"] == "lines"
                                and any(s["name"].startswith(("上季", "下季")) for s in ex.get("series", [])))
                reached = sum(1 for _, y in timed if y <= window.TARGET_YEAR)
                self.assertEqual(reached, 5 + threshold)
                for ex, y in timed:
                    if y > window.TARGET_YEAR:
                        matched = [k for k in window.CONVERTED["meta"] if window.key_matches(k, ex["title"])]
                        self.assertEqual(len(matched), 1, ex["title"])


if __name__ == "__main__":
    unittest.main()
