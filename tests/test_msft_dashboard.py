"""Checks for the MSFT page.

Two things here are worth pinning beyond the usual shape checks.  First the
calendar-quarter relabelling: this is the only company on the site whose fiscal
year is not the calendar year, so a page that quietly reverts to fiscal labels
would break every cross-company comparison without failing to render.  Second
the adjusted free-cash-flow arithmetic, which is the page's core claim and is
built from three separate disclosures that have to keep reconciling.
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
from build.msft import build_payload  # noqa: E402

WINDOW = 8


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


# ── readings, computed here and not borrowed from the builder ───────────────
# A threshold entry names the record it is read against (`reads`). These say
# what the latest reading of each record is, from the series, by a path of
# their own: a check that asked the builder would only agree with it.

def expected_reading(source: dict, reads: str) -> float:
    q, long = source["quarterly_usd_m"], source["long_history"]
    kpi, fy = source["operating_kpi"], source["fiscal_year_usd_m"]
    if reads == "azure_cc":
        return source["azure_growth_cc_pct"][-1]
    if reads == "cloud_gm":
        return kpi["microsoft_cloud"]["gross_margin_pct"][-1]
    if reads == "fy_om_change":
        # From the fiscal-year block, where the builder reads the long record.
        return (fy["operating_income"][-1] / fy["revenue"][-1]
                - fy["operating_income"][-2] / fy["revenue"][-2]) * 100
    if reads == "rpo_yoy":
        balance = long["commercial_rpo_usd_bn"]
        return (balance[-1] / balance[-5] - 1) * 100
    if reads == "rpo12_yoy":
        return [v for v in kpi["commercial_rpo"]["twelve_month_portion_yoy_pct"] if v is not None][-1]
    if reads == "bookings_ex_largest":
        return kpi["bookings_ex_largest_customer_yoy_pct"]["values"][-1]
    if reads == "copilot_seats":
        return kpi["copilot_paid_seats_m"]["values"][-1]
    if reads == "capex_company":
        return kpi["capex_incl_finance_leases_usd_bn"]["values"][-1]
    if reads == "fcf_quarter":
        return q["operating_cash_flow"][-1] - q["cash_paid_for_property_and_equipment"][-1]
    if reads == "opex_yoy":
        return (q["operating_expenses"][-1] / q["operating_expenses"][-5] - 1) * 100
    raise KeyError(reads)


# A record gets its own line chart once it has this many quarterly readings;
# a shorter one, or a once-a-year ratio, is settled in the overview only.
DRAWABLE = 5


def record_length(source: dict, reads: str) -> int:
    long, kpi = source["long_history"], source["operating_kpi"]

    def filled(values: list) -> int:
        return sum(1 for value in values if value is not None)

    lengths = {
        "azure_cc": lambda: len(source["azure_growth_cc_pct"]),
        "cloud_gm": lambda: filled(kpi["microsoft_cloud"]["gross_margin_pct"]),
        "fy_om_change": lambda: 0,
        "rpo_yoy": lambda: sum(1 for now, before in zip(long["commercial_rpo_usd_bn"][4:],
                                                        long["commercial_rpo_usd_bn"])
                               if now is not None and before is not None),
        "rpo12_yoy": lambda: filled(kpi["commercial_rpo"]["twelve_month_portion_yoy_pct"]),
        "bookings_ex_largest": lambda: filled(kpi["bookings_ex_largest_customer_yoy_pct"]["values"]),
        "copilot_seats": lambda: filled(kpi["copilot_paid_seats_m"]["values"]),
        "capex_company": lambda: filled(kpi["capex_incl_finance_leases_usd_bn"]["values"]),
        "fcf_quarter": lambda: len(long["quarters"]),
        "opex_yoy": lambda: len(long["quarters"]) - 4,
    }
    return lengths[reads]()


def favourable_side(entry: dict, value: float) -> bool:
    if value == entry["threshold"]:
        return entry.get("boundary", "safe") == "safe"
    return (value > entry["threshold"]) == (entry["direction"] == "up")


def headroom_pct(entry: dict, value: float) -> float:
    sign = 1 if entry["direction"] == "up" else -1
    return sign * (value - entry["threshold"]) / abs(entry["threshold"]) * 100


SECTIONS = [("settled", "一、上季跟踪指标兑现了吗"), ("quarter_highlights", "二、本季重点"),
            ("next_quarter", "三、下季要跟踪什么"), ("routine", "四、长期常规跟踪")]


class MsftDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "msft.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]
        cls.by_section = {
            section["id"]: section["exhibits"] for section in cls.payload["sections"]
        }
        cls.q = cls.source["quarterly_usd_m"]
        cls.segments = cls.source["segments_usd_m"]
        cls.fy = cls.source["fiscal_year_usd_m"]

    def test_twelve_quarter_base_backs_every_yoy(self) -> None:
        self.assertEqual(len(self.source["periods"]), 12)
        for name, values in self.q.items():
            self.assertEqual(len(values), 12, name)
            # Depreciation is only tagged from FY2025 onwards; every other line
            # has to be complete or a y/y curve would start mid-axis.
            expected_nulls = 4 if name == "depreciation" else 0
            self.assertEqual(sum(value is None for value in values), expected_nulls, name)
            self.assertTrue(
                all(math.isfinite(value) for value in values if value is not None), name
            )
        for name, values in self.segments.items():
            if isinstance(values, list):
                self.assertEqual(len(values), WINDOW, name)
        self.assertEqual(len(self.source["azure_growth_cc_pct"]), WINDOW)

    def test_periods_are_calendar_quarters_not_fiscal_ones(self) -> None:
        """The page's quarter has to mean the same three months every other
        company page calls by that name; the fiscal name rides alongside."""
        checks = self.source["_checks"]
        self.assertEqual(self.payload["latest"]["disclosed_period_label"], checks["period"])
        self.assertEqual(self.payload["latest"]["period_end"], checks["period_end"])
        self.assertIn(checks["fiscal_period"], self.payload["latest"]["full_financial_period_label"])
        self.assertIn(checks["fiscal_period"], self.payload["subtitle"])
        self.assertTrue(
            any("自然年季度" in note for note in self.payload["notes"]),
            "the labelling convention must be stated on the page, not only in the source",
        )
        self.assertEqual(self.segments["periods"], self.source["periods"][-WINDOW:])

    def test_segments_add_back_to_the_consolidated_statements(self) -> None:
        revenue = self.source["periods"][-WINDOW:]
        for index, period in enumerate(revenue):
            offset = len(self.source["periods"]) - WINDOW + index
            self.assertEqual(
                self.segments["productivity_revenue"][index]
                + self.segments["intelligent_cloud_revenue"][index]
                + self.segments["more_personal_computing_revenue"][index],
                self.q["revenue_total"][offset],
                period,
            )
            self.assertEqual(
                self.segments["productivity_operating_income"][index]
                + self.segments["intelligent_cloud_operating_income"][index]
                + self.segments["more_personal_computing_operating_income"][index],
                self.q["operating_income"][offset],
                period,
            )

    def test_quarterly_series_reconcile_with_both_fiscal_years(self) -> None:
        """Fiscal years end in June, so each one is four consecutive calendar
        quarters of the twelve-quarter base; the two must agree exactly."""
        pairs = {
            "revenue_total": "revenue",
            "operating_income": "operating_income",
            "operating_cash_flow": "operating_cash_flow",
            "cash_paid_for_property_and_equipment": "cash_paid_for_property_and_equipment",
            "finance_lease_additions": "finance_lease_additions",
            "stock_repurchases": "stock_repurchases",
            "dividends_paid": "dividends_paid",
            "depreciation": "depreciation",
        }
        # A fiscal year ending in June is the calendar Q3 and Q4 of the year
        # before and Q1 and Q2 of its own year -- read off the labels, not off
        # fixed positions, so the check survives a roll.
        def quarters_of(label: str) -> list[str]:
            year = int(label[2:])
            return [f"Q3 {year - 1}", f"Q4 {year - 1}", f"Q1 {year}", f"Q2 {year}"]
        years = {}
        for label in self.fy["labels"]:
            wanted = quarters_of(label)
            if all(p in self.source["periods"] for p in wanted):
                at = [self.source["periods"].index(p) for p in wanted]
                years[label] = slice(at[0], at[-1] + 1)
        self.assertTrue(years)
        for quarterly_key, annual_key in pairs.items():
            for label, window in years.items():
                self.assertEqual(
                    sum(self.q[quarterly_key][window]),
                    self.fy[annual_key][self.fy["labels"].index(label)],
                    f"{label} {quarterly_key}",
                )

    def test_adjusted_free_cash_flow_arithmetic(self) -> None:
        """Reported free cash flow only counts capex that was paid. The adjusted
        line subtracts the year's increase in unpaid capex -- three disclosed
        numbers, no estimate -- and is the page's central claim."""
        reported = [
            operating - spend
            for operating, spend in zip(
                self.fy["operating_cash_flow"], self.fy["cash_paid_for_property_and_equipment"]
            )
        ]
        checks = self.source["_checks"]["fiscal_year"]
        self.assertEqual(self.fy["labels"][-1], checks["label"])
        self.assertEqual(reported[-1], checks["operating_cash_flow_usd_m"]
                         - checks["additions_to_property_and_equipment_usd_m"])
        unpaid = [self.fy["unpaid_capex_in_payables_prior"]] + self.fy["unpaid_capex_in_payables"]
        self.assertEqual(unpaid[-2:], [checks["unpaid_capex_in_payables_prior_usd_m"],
                                       checks["unpaid_capex_in_payables_usd_m"]])
        adjusted = [
            value - (unpaid[index + 1] - unpaid[index]) for index, value in enumerate(reported)
        ]
        # Shareholder returns are the company's own measure: programme buybacks
        # plus dividends. The cash-flow repurchase line also carries shares
        # withheld for employees' taxes; counting them put the FY2026 coverage
        # at 103.2% where the company's own "over $43 billion" gives 91.5%.
        returns = [
            repurchase + dividend
            for repurchase, dividend in zip(self.fy["share_repurchase_program"], self.fy["dividends_paid"])
        ]
        self.assertEqual(self.fy["share_repurchase_program"][-1], checks["share_repurchase_program_usd_m"])
        self.assertEqual(self.fy["stock_repurchases"][-1], checks["common_stock_repurchased_usd_m"])
        self.assertTrue(43000 < returns[-1] < 44000, "the company says it returned over $43 billion")
        self.assertTrue(all(program <= cash for program, cash in
                            zip(self.fy["share_repurchase_program"], self.fy["stock_repurchases"])))
        coverage = [value / base * 100 for value, base in zip(returns, adjusted)]
        self.assertIn(f"股东回报已占到调整后自由现金流的 {coverage[-1]:.1f}%", self.payload["headline"])

        exhibit = next(ex for ex in self.exhibits if ex["kind"] == "grouped_bars")
        self.assertEqual(exhibit["xlabels"], self.fy["labels"])
        self.assertEqual([group["values"] for group in exhibit["groups"]],
                         [reported, adjusted, returns])

    def test_intelligent_cloud_gross_margin_is_derived_from_the_segment_note(self) -> None:
        chart = next(ex for ex in self.exhibits if "分部毛利率连降" in ex["title"])
        expected = [
            (revenue - cost) / revenue * 100
            for revenue, cost in zip(
                self.segments["intelligent_cloud_revenue"],
                self.segments["intelligent_cloud_cost_of_revenue"],
            )
        ]
        self.assertEqual(chart["values"], expected)
        # The whole point of the exhibit: a run of falls, then one rise -- and
        # the title counts the run. It said five while the record showed six.
        self.assertGreater(expected[-1], expected[-2])
        falls = 0
        for a, b in zip(reversed(expected[:-2]), reversed(expected[1:-1])):
            if b < a:
                falls += 1
            else:
                break
        self.assertIn(f"连降{cn_count(falls)}季后首次回升", chart["title"])

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

    def test_section_order_matches_how_the_note_is_used(self) -> None:
        # Section one: the closure, the overview of last quarter's lines, one
        # chart per record long enough to draw, the company's own guide.
        drawn = {entry["reads"] for entry in self.source["prior_kpi_settlement"]["quantified"]
                 if record_length(self.source, entry["reads"]) >= DRAWABLE}
        nxt = [e for e in self.source["next_kpi"]["quantified"] if not e.get("annual")]
        self.assertEqual(
            [(section["id"], len(section["exhibits"])) for section in self.payload["sections"]],
            [("settled", 1 + 1 + len(drawn) + 1), ("quarter_highlights", 5),
             ("next_quarter", 1 + len(nxt)), ("routine", 5)],
        )
        # A chart whose title is a range over the whole record is not this
        # quarter's conclusion; it belongs with the long series.
        for exhibit in self.by_section["quarter_highlights"]:
            self.assertNotRegex(exhibit["title"], r"季在 .* 之间", exhibit["title"])
        self.assertTrue(any(ex["title"].startswith("其他收入（净）")
                            for ex in self.by_section["routine"]))

    def test_headroom_bars_reproduce_the_thresholds(self) -> None:
        for section, block, key in (
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
        title = self.by_section["next_quarter"][0]["title"]
        if not breached:
            self.assertIn("当前值全部在安全侧", title)
        else:
            self.assertNotIn("全部在安全侧", title.replace("经营类全部在安全侧", ""))

    def test_every_tracked_metric_with_a_series_gets_its_own_chart(self) -> None:
        charted = {ex["title"].split("：")[0] for ex in self.by_section["next_quarter"][1:]}
        tracked = {entry["metric"] for entry in self.source["next_kpi"]["quantified"]}
        # The annual ratios built from the 10-K are not quarterly series.
        annual = {entry["metric"] for entry in self.source["next_kpi"]["quantified"] if entry.get("annual")}
        self.assertEqual(tracked - charted, annual)
        # Two windows now, and which one a metric gets is decided by what is
        # filed rather than by preference: Azure publishes a growth rate and no
        # revenue, and Intelligent Cloud's segment cost of revenue -- the
        # denominator of its gross margin -- only exists for the reviewed eight.
        # Everything else is a filed number or a difference of filed numbers all
        # the way back, so it runs the ten years.
        SHORT_BY_DISCLOSURE = {"Azure 固定汇率增速", "Intelligent Cloud 分部毛利率"}
        long_window = len(self.source["long_history"]["quarters"])
        for exhibit in self.by_section["next_quarter"][1:]:
            threshold = exhibit["series"][-1]["values"]
            metric = exhibit["title"].split("：")[0]
            self.assertEqual(len(set(threshold)), 1, exhibit["title"])
            expected = WINDOW if metric in SHORT_BY_DISCLOSURE else long_window
            self.assertEqual(len(threshold), expected, exhibit["title"])
            self.assertEqual(len(exhibit["xlabels"]), expected, exhibit["title"])
        # And the short ones say on themselves why they are short, so a reader
        # does not have to guess whether the page just failed to fetch.
        for exhibit in self.by_section["next_quarter"][1:]:
            if exhibit["title"].split("：")[0] in SHORT_BY_DISCLOSURE:
                self.assertIn(f"只有{cn_count(WINDOW)}季", exhibit["note"], exhibit["title"])

    def test_long_history_agrees_with_the_reviewed_quarters(self) -> None:
        """The ten-year series and the reviewed twelve must not disagree.

        Microsoft's fiscal fourth quarter is never filed on its own -- it is the
        year minus the nine-month year-to-date -- so this is also the check that
        the subtraction still lands on the number a human already reviewed.
        """
        long = self.source["long_history"]
        index = {quarter: i for i, quarter in enumerate(long["quarters"])}
        pairs = [
            ("revenue_usd_m", "revenue_total"),
            ("gross_profit_usd_m", "gross_profit"),
            ("operating_income_usd_m", "operating_income"),
            ("capital_expenditures_usd_m", "cash_paid_for_property_and_equipment"),
            ("operating_cash_flow_usd_m", "operating_cash_flow"),
            ("depreciation_usd_m", "depreciation"),
            ("finance_lease_additions_usd_m", "finance_lease_additions"),
            # Added when the threshold charts moved onto the ten-year record.
            # Buybacks and other income are their own XBRL facts (the June
            # quarters derived as year minus nine months); operating expenses is
            # gross profit minus operating income, both of which are in the same
            # block. All three overlap the reviewed twelve, so all three are
            # checked here rather than trusted.
            ("stock_repurchases_usd_m", "stock_repurchases"),
            ("other_income_expense_net_usd_m", "other_income_expense_net"),
            ("operating_expenses_usd_m", "operating_expenses"),
        ]
        for long_key, reviewed_key in pairs:
            self.assertIn(long_key, long, long_key)
            for period, expected in zip(self.source["periods"], self.q[reviewed_key]):
                quarter, year = period.split()
                got = long[long_key][index[f"{year}Q{quarter[1]}"]]
                self.assertEqual(got, expected, f"{long_key} {period}")
        # Operating expenses is a derived line, so the identity it was derived
        # from is asserted over the whole record, not only where it overlaps.
        for i, quarter in enumerate(long["quarters"]):
            self.assertAlmostEqual(
                long["gross_profit_usd_m"][i] - long["operating_income_usd_m"][i],
                long["operating_expenses_usd_m"][i], places=6, msg=quarter)

    def test_quarterly_depreciation_is_not_invented_before_disclosure(self) -> None:
        """Microsoft publishes depreciation annually far further back than it
        publishes it quarterly.  Spreading a year over four quarters would draw a
        curve the company never gave, so that chart keeps its short window and
        the page says why rather than leaving the reader to notice."""
        long = self.source["long_history"]
        quarters = long["quarters"]
        start = quarters.index(long["depreciation_first_reported"])
        self.assertTrue(all(v is None for v in long["depreciation_usd_m"][:start]))
        self.assertTrue(all(v is not None for v in long["depreciation_usd_m"][start:]))

        depreciation_chart = next(ex for ex in self.exhibits if "季度折旧" in ex["title"])
        self.assertEqual(len(depreciation_chart["xlabels"]), WINDOW)
        self.assertIn("只有这张没有", depreciation_chart["note"])

        # Every other routine chart did make it back to the start, and the note
        # counts them rather than naming a number that was true once.
        routine = self.by_section["routine"]
        long_axes = [ex for ex in routine if len(ex["xlabels"]) > WINDOW]
        self.assertEqual(len(long_axes), len(routine) - 1)
        self.assertIn(f"本节其余{cn_count(len(long_axes))}张都拉到了", depreciation_chart["note"])

    def test_finance_leases_are_never_added_to_cash_capex(self) -> None:
        """The two spending channels take different routes through the cash flow
        statement, so the page charts them separately and says why."""
        long = self.source["long_history"]
        capex_chart = next(ex for ex in self.exhibits if "资本强度" in ex["title"])
        lease_chart = next(ex for ex in self.exhibits if "融资租赁新增" in ex["title"])
        intensity = [
            round(spend / total * 100, 6)
            for spend, total in zip(long["capital_expenditures_usd_m"], long["revenue_usd_m"])
        ]
        self.assertEqual(
            [round(v, 6) for v in capex_chart["series"][0]["values"]], intensity
        )
        leases = long["finance_lease_additions_usd_m"]
        self.assertEqual(
            lease_chart["series"][0]["values"], [v for v in leases if v is not None]
        )
        self.assertIn("不把它与现金资本开支相加", lease_chart["src_extra"])
        # The two channels stay on separate charts: neither series may be the
        # sum of the two, which is the mistake the note exists to prevent.
        combined = [
            spend + (lease or 0)
            for spend, lease in zip(long["capital_expenditures_usd_m"], leases)
        ]
        self.assertNotEqual(lease_chart["series"][0]["values"], combined)

    def test_audit_tables_back_every_derived_exhibit(self) -> None:
        tables = self.payload["tables"]
        first = len(self.exhibits) + 2
        self.assertEqual([table["n"] for table in tables], list(range(first, first + len(tables))))
        self.assertIn("AI capex", tables[-1]["title"])
        prior = self.source["prior_kpi_settlement"]
        self.assertEqual(len(tables[0]["rows"]), len(prior["quantified"]) + len(prior["unscored"]))
        self.assertEqual(len(tables[1]["rows"]), len(self.source["next_kpi"]["quantified"]))
        segment_table = next(t for t in tables if "分部收入" in t["title"])
        self.assertEqual(len(segment_table["rows"]), WINDOW)
        base_table = next(t for t in tables if "十二季度基础数据" in t["title"])
        self.assertEqual(len(base_table["rows"]), 12)

    def test_market_expectation_is_labelled_and_unattributed(self) -> None:
        text = json.dumps(self.payload, ensure_ascii=False)
        self.assertIn("市场预期", text)
        for broker in ["FactSet", "Bloomberg", "Seeking Alpha", "consensus", "Anthropic"]:
            self.assertNotIn(broker.lower(), text.lower())
        self.assertEqual(self.source["market_expectation"]["as_of"], self.source["latest"]["release_date"])
        # Two public sources disagree by $1.75B, so only the direction is published.
        self.assertIn("不发布超预期幅度", text)

    def test_sources_are_official_http_links(self) -> None:
        allowed_hosts = {"www.microsoft.com", "www.sec.gov"}
        for source in self.payload["source_links"]:
            parsed = urlparse(source["url"])
            self.assertEqual(parsed.scheme, "https")
            self.assertIn(parsed.hostname, allowed_hosts)

    def test_published_payload_and_shell(self) -> None:
        self.assertEqual(js_payload(ROOT / "data" / "msft.js", "window.DASH"), self.payload)
        shell = (ROOT / "msft" / "index.html").read_text(encoding="utf-8")
        self.assertIn("../data/msft.js", shell)
        self.assertNotIn("../data/tsm.js", shell)

    def test_public_files_exclude_private_and_broker_material(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [
                ROOT / "series" / "msft.json",
                ROOT / "data" / "msft.js",
                ROOT / "msft" / "index.html",
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
            "openai",
            "谨慎多",
        ]:
            self.assertNotIn(forbidden, text)
        compact = "".join(text.split())
        self.assertNotIn(":nan", compact)
        self.assertNotIn(":infinity", compact)
        self.assertNotIn(":-infinity", compact)


STAMPED = ("outlook", "market_expectation", "followup_closure", "prior_kpi_settlement", "next_kpi",
           "guidance_delivery")


def published_text(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


class MsftChecksTest(unittest.TestCase):
    """The page's quarter against a record keyed separately from the filing.

    `_checks` is typed once per quarter from the earnings release (and the 10-K
    and the call for the few items the release does not print), with the place
    each figure was read from. It is not copied from the arrays and the builder
    never reads it (`test_data_only_roll`).
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "msft.json").read_text(encoding="utf-8"))
        cls.checks = cls.source["_checks"]
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]
        cls.q = cls.source["quarterly_usd_m"]

    def test_the_page_names_the_checked_quarter(self) -> None:
        self.assertIn(self.checks["period"], self.payload["title"])
        self.assertIn(f"截至 {self.checks['period_end']}（微软 {self.checks['fiscal_period']}）",
                      self.payload["subtitle"])
        self.assertIn(f"发布 {self.checks['release_date']}", self.payload["subtitle"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        c, q = self.checks, self.q
        for key, check in (("revenue_total", "revenue_usd_m"), ("gross_profit", "gross_margin_usd_m"),
                           ("operating_income", "operating_income_usd_m"),
                           ("operating_expenses", "operating_expenses_usd_m"),
                           ("other_income_expense_net", "other_income_expense_net_usd_m"),
                           ("operating_cash_flow", "operating_cash_flow_usd_m"),
                           ("cash_paid_for_property_and_equipment", "additions_to_property_and_equipment_usd_m"),
                           ("stock_repurchases", "common_stock_repurchased_usd_m"),
                           ("dividends_paid", "dividends_paid_usd_m")):
            with self.subTest(line=key):
                self.assertEqual(q[key][-1], c[check])
        self.assertEqual(q["revenue_total"][-5], c["revenue_year_ago_usd_m"])
        segments = self.source["segments_usd_m"]
        for key, value in c["segments_usd_m"].items():
            with self.subTest(segment=key):
                self.assertEqual(segments[key][-1], value)
        self.assertEqual(self.source["azure_growth_cc_pct"][-1], c["azure_growth_printed_pct"])
        fy, cfy = self.source["fiscal_year_usd_m"], c["fiscal_year"]
        self.assertEqual(fy["labels"][-1], cfy["label"])
        for key, check in (("revenue", "revenue_usd_m"), ("operating_income", "operating_income_usd_m"),
                           ("operating_cash_flow", "operating_cash_flow_usd_m"),
                           ("cash_paid_for_property_and_equipment", "additions_to_property_and_equipment_usd_m"),
                           ("stock_repurchases", "common_stock_repurchased_usd_m"),
                           ("share_repurchase_program", "share_repurchase_program_usd_m"),
                           ("dividends_paid", "dividends_paid_usd_m"),
                           ("unpaid_capex_in_payables", "unpaid_capex_in_payables_usd_m"),
                           ("depreciation", "depreciation_usd_m"),
                           ("contracted_not_yet_commenced_leases", "contracted_not_yet_commenced_leases_usd_m")):
            with self.subTest(fiscal=key):
                self.assertEqual(fy[key][-1], cfy[check])
        outlook = self.source["outlook"]
        for key, value in c["next_quarter"].items():
            with self.subTest(guide=key):
                self.assertEqual(outlook[key], value)

    def test_computed_figures_round_to_what_the_release_prints(self) -> None:
        c, q = self.checks, self.q
        self.assertEqual(round((q["revenue_total"][-1] / q["revenue_total"][-5] - 1) * 100),
                         c["revenue_growth_printed_pct"])
        # "returned $10.2 billion to shareholders ... in the fourth quarter" is
        # programme buybacks plus dividends; the quarter's programme buyback is
        # the 10-K's fourth-quarter row.
        fy = self.source["fiscal_year_usd_m"]
        returns = fy["share_repurchase_program"][-1] + fy["dividends_paid"][-1]
        self.assertIn("43", c["fiscal_year"]["returned_to_shareholders_words"])
        self.assertEqual(int(returns // 1000), 43)

    def test_the_page_prints_the_checked_figures(self) -> None:
        c = self.checks
        revenue_chart = next(ex for ex in self.exhibits if ex["title"].startswith("收入 $"))
        self.assertIn(f"收入 ${c['revenue_usd_m']:,}M", revenue_chart["title"])
        grouped = next(ex for ex in self.exhibits if ex["kind"] == "grouped_bars")
        cfy = c["fiscal_year"]
        self.assertEqual(grouped["groups"][2]["values"][-1],
                         cfy["share_repurchase_program_usd_m"] + cfy["dividends_paid_usd_m"])
        self.assertIn(f"+{c['azure_growth_printed_pct']}%", self.payload["brief"])

    def test_every_threshold_value_matches_the_series(self) -> None:
        """The coverage threshold's `current` was typed as 103.2 -- the cash-flow
        repurchase line over adjusted free cash flow -- and flipped the chart's
        verdict; on the company's own measure it is 91.5."""
        fy = self.source["fiscal_year_usd_m"]
        reported = fy["operating_cash_flow"][-1] - fy["cash_paid_for_property_and_equipment"][-1]
        adjusted = reported - (fy["unpaid_capex_in_payables"][-1] - fy["unpaid_capex_in_payables"][-2])
        returns = fy["share_repurchase_program"][-1] + fy["dividends_paid"][-1]
        segments = self.source["segments_usd_m"]
        q = self.q
        expected = {
            "Azure 固定汇率增速": self.source["azure_growth_cc_pct"][-1],
            "Intelligent Cloud 分部毛利率": (segments["intelligent_cloud_revenue"][-1]
                                        - segments["intelligent_cloud_cost_of_revenue"][-1])
                                       / segments["intelligent_cloud_revenue"][-1] * 100,
            "单季回购金额": q["stock_repurchases"][-1],
            "单季自由现金流（报告口径）": q["operating_cash_flow"][-1] - q["cash_paid_for_property_and_equipment"][-1],
            "股东回报 / 调整后自由现金流": returns / adjusted * 100,
            "已签约未起租租约 / 年收入": fy["contracted_not_yet_commenced_leases"][-1] / fy["revenue"][-1] * 100,
            "经营费用同比": (q["operating_expenses"][-1] / q["operating_expenses"][-5] - 1) * 100,
        }
        for entry in self.source["next_kpi"]["quantified"]:
            with self.subTest(metric=entry["metric"]):
                self.assertAlmostEqual(entry["current"], expected[entry["metric"]], places=1)

    def test_the_settlement_readings_are_the_checked_figures(self) -> None:
        """Last quarter's lines are settled against readings the series carries;
        the ones the release, the 10-K and the call print are re-read here."""
        k, source = self.checks["kpi"], self.source
        kpi, long = source["operating_kpi"], source["long_history"]
        self.assertEqual(long["commercial_rpo_usd_bn"][-1], k["commercial_rpo_usd_bn"])
        self.assertEqual(round(expected_reading(source, "rpo_yoy")), k["commercial_rpo_growth_printed_pct"])
        self.assertEqual(kpi["microsoft_cloud"]["revenue_usd_bn"][-1], k["microsoft_cloud_revenue_usd_bn"])
        self.assertEqual(expected_reading(source, "cloud_gm"), k["microsoft_cloud_gross_margin_pct"])
        self.assertEqual(expected_reading(source, "copilot_seats"), k["copilot_paid_seats_m_over"])
        self.assertEqual(expected_reading(source, "capex_company"), k["capex_incl_finance_leases_usd_bn"])
        self.assertEqual(expected_reading(source, "rpo12_yoy"), k["twelve_month_portion_growth_pct"])
        self.assertEqual(kpi["commercial_rpo"]["twelve_month_share_pct"][-1], k["twelve_month_share_pct"])
        self.assertEqual(expected_reading(source, "bookings_ex_largest"),
                         k["bookings_growth_excluding_largest_customer_pct"])
        rpo_chart = next(ex for ex in self.exhibits if ex["title"].startswith("商业剩余履约义务"))
        self.assertIn(f"US${k['commercial_rpo_usd_bn']}B", rpo_chart["title"])
        self.assertIn(f"余额同比 +{k['commercial_rpo_growth_printed_pct']}%", rpo_chart["note"])


class MsftSectionOneTest(unittest.TestCase):
    """Section one against the two analyses, as `_checks["note"]` records them.

    The note is keyed from the analyses themselves -- this quarter's section 0
    and the previous one's key-metric section -- separately from the blocks the
    builder reads, so a threshold retyped wrong in either place turns red here.
    Nothing below names a quarter or a count: a roll edits the series and the
    note, and this file stays as it is.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "msft.json").read_text(encoding="utf-8"))
        cls.note = cls.source["_checks"]["note"]
        cls.payload = build_payload(cls.source)
        cls.settled = next(s for s in cls.payload["sections"] if s["id"] == "settled")["exhibits"]
        cls.prior = cls.source["prior_kpi_settlement"]

    def test_the_four_sections_are_the_site_s(self) -> None:
        self.assertEqual([(s["id"], s["title"]) for s in self.payload["sections"]], SECTIONS)
        self.assertTrue(any("上季兑现 → 本季重点 → 下季跟踪 → 长期常规" in n for n in self.payload["notes"]))

    def test_the_closure_is_the_analysis_s_section_0(self) -> None:
        closure = self.note["followup_closure"]
        chart = self.settled[0]
        self.assertEqual(chart["kind"], "bars_labeled")
        self.assertTrue(chart["title"].startswith(f"上季 {closure['total']} 条待验证问题："), chart["title"])
        self.assertEqual(dict(zip(chart["xlabels"], chart["values"])), closure["counts"])
        self.assertEqual(sum(chart["values"]), closure["total"])
        # Every category the analysis used is in the title, not only some.
        for label, count in closure["counts"].items():
            if count:
                self.assertIn(f"{count} 条{label}", chart["title"])
        block = self.source["followup_closure"]
        self.assertEqual({label: len(topics) for label, topics in block["topics"].items()},
                         {label: len(numbers) for label, numbers in closure["questions"].items()})
        # With no tally row in the analysis, the chart says how it counted.
        self.assertIn(block["rule"], chart["note"])
        for item in block.get("verdicts_in_full", []):
            self.assertIn(item["words"], chart["note"])

    def test_the_prior_lines_are_the_previous_analysis_s_rows(self) -> None:
        self.assertEqual(
            [(e["id"], e["row"], e["tier"], e["threshold"], e["direction"]) for e in self.prior["quantified"]],
            [(t["id"], t["row"], t["tier"], t["threshold"], t["direction"]) for t in self.note["prior_thresholds"]])
        rows = {e["row"] for e in self.prior["quantified"]} | {i["row"] for i in self.prior["unscored"]}
        self.assertEqual(len(rows), self.note["prior_rows"])
        self.assertEqual(self.prior["rows"], self.note["prior_rows"])
        self.assertEqual(sorted({i["row"] for i in self.prior["unscored"]}), self.note["prior_unscored_rows"])
        # The reading is never typed beside the line; it is read off the record.
        for entry in self.prior["quantified"]:
            for typed in ("actual", "reading", "current"):
                self.assertNotIn(typed, entry, entry["id"])

    def test_the_overview_settles_every_line_at_its_reading(self) -> None:
        overview = self.settled[1]
        self.assertEqual(overview["kind"], "diverging_bars")
        bars = [e for e in self.prior["quantified"] if e["threshold"] != 0]
        self.assertTrue(overview["title"].startswith(f"上季 {len(bars)} 条量化阈值："), overview["title"])
        self.assertEqual(overview["xlabels"], [e["label"] for e in bars])
        for entry, plotted in zip(bars, overview["values"]):
            reading = expected_reading(self.source, entry["reads"])
            self.assertAlmostEqual(plotted, round(headroom_pct(entry, reading), 1), places=6, msg=entry["id"])
        # A line at zero has no percentage headroom; the note settles it instead.
        for entry in self.prior["quantified"]:
            if entry["threshold"] == 0:
                self.assertIn(f"「{entry['label']}」的阈值是 0", overview["note"])
        for item in self.prior["unscored"]:
            self.assertIn(item["text"], overview["note"])
        targets = [e for e in bars if e["tier"] in ("期望", "加仓", "确认")]
        reached = [e for e in targets if favourable_side(e, expected_reading(self.source, e["reads"]))]
        if targets and len(reached) == len(targets):
            self.assertIn(f"{len(targets)} 条目标线全部达到", overview["title"])

    def test_every_record_long_enough_to_draw_gets_its_lines(self) -> None:
        lines = [ex for ex in self.settled if ex["kind"] == "lines"]
        by_reads: dict[str, list] = {}
        for entry in self.prior["quantified"]:
            by_reads.setdefault(entry["reads"], []).append(entry)
        drawn = [reads for reads in by_reads if record_length(self.source, reads) >= DRAWABLE]
        self.assertEqual(len(lines), len(drawn))
        for reads, chart in zip(drawn, lines):
            entries = by_reads[reads]
            flat = {tuple(set(s["values"])) for s in chart["series"][1:]}
            for entry in entries:
                with self.subTest(line=entry["id"]):
                    self.assertIn((entry["threshold"],), flat)
                    word = "达到" if entry["tier"] in ("期望", "加仓", "确认") else "触发"
                    self.assertRegex(chart["title"], rf"(未)?{word}上季{entry['tier']}线 ")
            self.assertIn(entries[0]["basis"], chart["note"])
        overview = self.settled[1]
        for reads, entries in by_reads.items():
            if reads not in drawn:
                self.assertIn(f"{entries[0]['metric']}没有单独的线图", overview["note"])

    def test_the_verdicts_follow_the_readings(self) -> None:
        """Push one reading across its red line and the titles must say so."""
        shifted = copy.deepcopy(self.source)
        shifted["azure_growth_cc_pct"][-1] = 37
        settled = next(s for s in build_payload(shifted)["sections"] if s["id"] == "settled")["exhibits"]
        azure = next(ex for ex in settled if ex["kind"] == "lines" and ex["title"].startswith("Azure"))
        self.assertIn("未达到上季期望线 40%", azure["title"])
        self.assertIn("触发上季红旗线 38%", azure["title"])
        self.assertNotIn("未触发上季红旗线 38%", azure["title"])
        self.assertNotIn("全部达到", settled[1]["title"])

    def test_the_company_guide_is_scored_against_the_filings(self) -> None:
        block = self.source["guidance_delivery"]
        chart = next(ex for ex in self.settled if ex["title"].startswith("上季电话会给本季的"))
        self.assertIs(chart, self.settled[-1])
        q, segments = self.source["quarterly_usd_m"], self.source["segments_usd_m"]
        actual = {"revenue": q["revenue_total"][-1], "pbp_revenue": segments["productivity_revenue"][-1],
                  "ic_revenue": segments["intelligent_cloud_revenue"][-1],
                  "mpc_revenue": segments["more_personal_computing_revenue"][-1],
                  "cogs": q["revenue_total"][-1] - q["gross_profit"][-1], "opex": q["operating_expenses"][-1]}
        for item, plotted in zip(block["items"], chart["values"]):
            middle = (item["low"] + item["high"]) / 2
            self.assertAlmostEqual(plotted, round((actual[item["reads"]] / middle - 1) * 100, 1), places=6)
        self.assertEqual(len(block["items"]), self.note["guidance_delivery"]["items"])
        self.assertEqual(block["given_on"], self.note["guidance_delivery"]["given_on"])
        above = sum(1 for item in block["items"] if actual[item["reads"]] > item["high"])
        self.assertEqual(chart["title"].count("高于区间上端"), 1 if above else 0)

    def test_the_falsified_call_is_dated_by_the_transcripts(self) -> None:
        """The analysis called last quarter's AI run-rate its first disclosure;
        the company's own transcripts carry an earlier one, and the page says so."""
        closure = self.source["followup_closure"]
        first, last = closure["ai_run_rate_disclosures"][-2:]
        quarter, year = first["period"].split()
        gap = (int(last["period"][-4:]) * 4 + int(last["period"][1])) - (int(year) * 4 + int(quarter[1]))
        self.assertIn(f"上季时隔{cn_count(gap)}季再次给出", self.settled[0]["note"])
        self.assertIn(f"${first['usd_bn']:g}B", self.settled[0]["note"])


class MsftRollTest(unittest.TestCase):
    """What a quarter roll can and cannot get past."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "msft.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)

    def test_a_block_stamped_with_another_quarter_stops_the_build(self) -> None:
        for key in STAMPED:
            stale = copy.deepcopy(self.source)
            stale[key]["period"] = "Q1 1999"
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    build_payload(stale)

    def test_a_missing_quarter_block_leaves_its_part_out(self) -> None:
        bare = copy.deepcopy(self.source)
        for key in STAMPED:
            del bare[key]
        payload = build_payload(bare)
        self.assertEqual([s["id"] for s in payload["sections"]], ["quarter_highlights", "routine"])
        text = published_text(payload)
        for gone in ("财报当日股价", "下季与 FY", "市场预期区间", "待验证问题", "超自身指引"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, text)

    def test_the_quarter_release_must_be_in_the_sources(self) -> None:
        missing = copy.deepcopy(self.source)
        fiscal = missing["latest"]["fiscal_period"]
        missing["sources"] = [s for s in missing["sources"] if not s["label"].startswith(fiscal)]
        with self.assertRaisesRegex(ValueError, "sources"):
            build_payload(missing)

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        before = published_text(self.payload)
        cases = []

        led_before = copy.deepcopy(self.source)
        led_before["segments_usd_m"]["intelligent_cloud_revenue"][0] = 40000
        cases.append(("IC led PBP earlier", led_before,
                      ["本季首次超过 Productivity", "收入首次超过 Productivity", "首次成为最大分部"]))

        one_rise = copy.deepcopy(self.source)
        costs = one_rise["segments_usd_m"]["intelligent_cloud_cost_of_revenue"]
        costs[3] = 9000   # 2025Q2's margin now above 2025Q1's: the run of falls is broken
        cases.append(("the run of falls is shorter", one_rise, ["连降六季", "六季来首次回升"]))

        over = copy.deepcopy(self.source)
        over["fiscal_year_usd_m"]["share_repurchase_program"][-1] = 22271
        for entry in over["next_kpi"]["quantified"]:
            if entry["metric"].startswith("股东回报"):
                entry["current"] = 103.2
        cases.append(("returns over free cash flow", over, ["回报逼近真实自由现金流"]))

        under = copy.deepcopy(self.source)
        under["fiscal_year_usd_m"]["share_repurchase_program"][-1] = 1000
        cases.append(("returns well under free cash flow", under, ["回报逼近真实自由现金流"]))

        not_top = copy.deepcopy(self.source)
        not_top["long_history"]["capital_expenditures_usd_m"][5] = 20000.0
        cases.append(("an earlier capex-intensity peak", not_top, ["拉长看才知道当前这一档没有先例"]))

        loss_year = copy.deepcopy(self.source)
        long = loss_year["long_history"]
        at = long["quarters"].index("2025Q2")
        long["other_income_expense_net_usd_m"][at] = 9000.0
        cases.append(("last fiscal year's other income positive", loss_year, ["上一财年产生的是净损失"]))

        for name, series, claims in cases:
            after = published_text(build_payload(series))
            for claim in claims:
                with self.subTest(case=name, claim=claim):
                    self.assertIn(claim, before)
                    self.assertNotIn(claim, after)

        over_text = published_text(build_payload(over))
        self.assertIn("回报已超过真实自由现金流", over_text)
        self.assertIn("被击穿的是现金分配那条", over_text)

    def test_the_counted_sentences_follow_the_record(self) -> None:
        text = published_text(self.payload)
        self.assertIn("七次环比里五次下降", text)
        self.assertNotIn("单向下滑", text)
        self.assertIn("上季时隔五季再次给出", text)
        self.assertNotIn("上季首次给出", text)


if __name__ == "__main__":
    unittest.main()
