"""Checks for the MSFT page.

Two things here are worth pinning beyond the usual shape checks.  First the
calendar-quarter relabelling: this is the only company on the site whose fiscal
year is not the calendar year, so a page that quietly reverts to fiscal labels
would break every cross-company comparison without failing to render.  Second
the adjusted free-cash-flow arithmetic, which is the page's core claim and is
built from three separate disclosures that have to keep reconciling.

Sections one and three are checked against `_checks["note"]`, which records the
two local analyses (this quarter's section 0 and key metrics, the previous
one's key metrics) separately from the blocks the builder reads. Nothing below
names a quarter or a count that only this quarter has: a roll edits
`series/msft.json` and nothing else, and `MsftRollDrillTest` builds the next
quarter from the series alone to prove it.
"""

from __future__ import annotations

import copy
import json
import math
import re
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import cn_count  # noqa: E402
from build.msft import build_payload  # noqa: E402

# The eight-quarter display window of the short charts: a design constant of the
# page, not a state of the quarter.
WINDOW = 8
SECTIONS = [("settled", "一、上季跟踪指标兑现了吗"), ("quarter_highlights", "二、本季重点"),
            ("next_quarter", "三、下季要跟踪什么"), ("routine", "四、长期常规跟踪")]
TARGET_TIERS = ("期望", "加仓", "确认")


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


def load_source() -> dict:
    return json.loads((ROOT / "series" / "msft.json").read_text(encoding="utf-8"))


def section(payload: dict, key: str) -> list[dict]:
    return next(s for s in payload["sections"] if s["id"] == key)["exhibits"]


# ── readings, computed here and not borrowed from the builder ───────────────
# A threshold entry names the record it is read against (`reads`). These say
# what the latest reading of each record is, from the series, by a path of
# their own: a check that asked the builder would only agree with it.

def expected_reading(source: dict, reads: str) -> float:
    q, long = source["quarterly_usd_m"], source["long_history"]
    kpi, fy = source["operating_kpi"], source["fiscal_year_usd_m"]

    def last(values: list) -> float:
        return [value for value in values if value is not None][-1]

    if reads == "azure_cc":
        return source["azure_growth_cc_pct"][-1]
    if reads == "cloud_gm":
        return last(kpi["microsoft_cloud"]["gross_margin_pct"])
    if reads == "fy_om_change":
        # From the fiscal-year block, where the builder reads the long record.
        return (fy["operating_income"][-1] / fy["revenue"][-1]
                - fy["operating_income"][-2] / fy["revenue"][-2]) * 100
    if reads == "rpo_yoy":
        balance = long["commercial_rpo_usd_bn"]
        return (balance[-1] / balance[-5] - 1) * 100
    if reads == "rpo12_yoy":
        return last(kpi["commercial_rpo"]["twelve_month_portion_yoy_pct"])
    if reads == "bookings_ex_largest":
        return last(kpi["bookings_ex_largest_customer_yoy_pct"]["values"])
    if reads == "copilot_seats":
        return last(kpi["copilot_paid_seats_m"]["values"])
    if reads == "seats_qoq":
        seats = kpi["copilot_paid_seats_m"]["values"]
        return (seats[-1] / seats[-2] - 1) * 100
    if reads == "capex_company":
        return last(kpi["capex_incl_finance_leases_usd_bn"]["values"])
    if reads == "m365_cc_adjusted":
        return last(kpi["m365_commercial_cloud"]["adjusted_pct"])
    if reads == "fcf_quarter":
        return q["operating_cash_flow"][-1] - q["cash_paid_for_property_and_equipment"][-1]
    if reads == "opex_yoy":
        return (q["operating_expenses"][-1] / q["operating_expenses"][-5] - 1) * 100
    if reads == "buyback_quarter":
        return q["stock_repurchases"][-1]
    if reads == "depr_annualized":
        return q["depreciation"][-1] * 4
    if reads == "leases_nc_yoy":
        balance = long["leases_not_commenced_usd_bn"]
        return balance[-1] - balance[-5]
    if reads == "adj_fcf_quarter":
        unpaid = long["unpaid_capex_in_payables_usd_bn"]
        return (q["operating_cash_flow"][-1] - q["cash_paid_for_property_and_equipment"][-1]
                - (unpaid[-1] - unpaid[-2]) * 1000)
    if reads == "adj_fcf_fy":
        unpaid = [fy["unpaid_capex_in_payables_prior"]] + fy["unpaid_capex_in_payables"]
        return (fy["operating_cash_flow"][-1] - fy["cash_paid_for_property_and_equipment"][-1]
                - (unpaid[-1] - unpaid[-2]))
    if reads == "oie_ex_interest":
        return (q["other_income_expense_net"][-1] - long["interest_and_dividends_income_usd_m"][-1]
                - long["interest_expense_usd_m"][-1])
    raise KeyError(reads)


# A record gets its own line chart once it has a year of quarterly readings; a
# shorter one, or a once-a-year figure, is settled in the overview only.
DRAWABLE = 4


def record_length(source: dict, reads: str) -> int:
    long, kpi = source["long_history"], source["operating_kpi"]

    def filled(values: list) -> int:
        return sum(1 for value in values if value is not None)

    def paired(values: list, lag: int) -> int:
        return sum(1 for now, before in zip(values[lag:], values) if now is not None and before is not None)

    lengths = {
        "azure_cc": lambda: len(source["azure_growth_cc_pct"]),
        "cloud_gm": lambda: filled(kpi["microsoft_cloud"]["gross_margin_pct"]),
        "fy_om_change": lambda: 0,
        "adj_fcf_fy": lambda: 0,
        "rpo_yoy": lambda: paired(long["commercial_rpo_usd_bn"], 4),
        "rpo12_yoy": lambda: filled(kpi["commercial_rpo"]["twelve_month_portion_yoy_pct"]),
        "bookings_ex_largest": lambda: filled(kpi["bookings_ex_largest_customer_yoy_pct"]["values"]),
        "copilot_seats": lambda: filled(kpi["copilot_paid_seats_m"]["values"]),
        "seats_qoq": lambda: filled(kpi["copilot_paid_seats_m"]["values"]) - 1,
        "capex_company": lambda: filled(kpi["capex_incl_finance_leases_usd_bn"]["values"]),
        "m365_cc_adjusted": lambda: filled(kpi["m365_commercial_cloud"]["adjusted_pct"]),
        "fcf_quarter": lambda: len(long["quarters"]),
        "opex_yoy": lambda: len(long["quarters"]) - 4,
        "buyback_quarter": lambda: filled(long["stock_repurchases_usd_m"]),
        "depr_annualized": lambda: filled(long["depreciation_usd_m"]),
        "leases_nc_yoy": lambda: paired(long["leases_not_commenced_usd_bn"], 4),
        "adj_fcf_quarter": lambda: paired(long["unpaid_capex_in_payables_usd_bn"], 1),
        "oie_ex_interest": lambda: len(long["quarters"]),
    }
    return lengths[reads]()


def favourable_side(entry: dict, value: float) -> bool:
    if value == entry["threshold"]:
        return entry.get("boundary", "safe") == "safe"
    return (value > entry["threshold"]) == (entry["direction"] == "up")


def headroom_pct(entry: dict, value: float) -> float:
    sign = 1 if entry["direction"] == "up" else -1
    return sign * (value - entry["threshold"]) / abs(entry["threshold"]) * 100


def bars_of(block: dict, settling: bool, period: str | None = None) -> list[dict]:
    """The entries a threshold overview draws as bars: every line with a nonzero
    threshold, less -- when settling -- a dated line whose quarter has not come."""
    def due(entry: dict) -> bool:
        if "settles" not in entry or period is None:
            return True
        (q1, y1), (q2, y2) = entry["settles"].split(), period.split()
        return (int(y1), int(q1[1])) <= (int(y2), int(q2[1]))
    return [e for e in block["quantified"] if e["threshold"] != 0 and (not settling or due(e))]


def drawn_reads(source: dict, block: dict) -> list[str]:
    order: list[str] = []
    for entry in block["quantified"]:
        if entry["reads"] not in order and record_length(source, entry["reads"]) >= DRAWABLE:
            order.append(entry["reads"])
    return order


def published_text(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


class MsftDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = load_source()
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for s in cls.payload["sections"] for ex in s["exhibits"]]
        cls.by_section = {s["id"]: s["exhibits"] for s in cls.payload["sections"]}
        cls.q = cls.source["quarterly_usd_m"]
        cls.segments = cls.source["segments_usd_m"]
        cls.fy = cls.source["fiscal_year_usd_m"]

    def test_the_quarterly_base_backs_every_yoy(self) -> None:
        periods = self.source["periods"]
        self.assertGreaterEqual(len(periods), WINDOW + 4)
        for name, values in self.q.items():
            self.assertEqual(len(values), len(periods), name)
            # Depreciation is only disclosed quarterly from FY2025 onwards; its
            # blanks are all at the start, every other line is complete.
            first = next(i for i, value in enumerate(values) if value is not None)
            self.assertTrue(all(value is not None for value in values[first:]), name)
            if name != "depreciation":
                self.assertEqual(first, 0, name)
            self.assertTrue(all(math.isfinite(value) for value in values if value is not None), name)
        width = len(self.segments["periods"])
        self.assertGreaterEqual(width, WINDOW)
        for name, values in self.segments.items():
            if isinstance(values, list):
                self.assertEqual(len(values), width, name)
        self.assertEqual(len(self.source["azure_growth_cc_pct"]), width)

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
        width = len(self.segments["periods"])
        self.assertEqual(self.segments["periods"], self.source["periods"][-width:])

    def test_segments_add_back_to_the_consolidated_statements(self) -> None:
        width = len(self.segments["periods"])
        for index, period in enumerate(self.segments["periods"]):
            offset = len(self.source["periods"]) - width + index
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
        quarters of the quarterly base; the two must agree exactly."""
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
        # The call's own words for the year ("over $N billion"), as `_checks` keeps them.
        said = int(re.search(r"\$(\d+) billion", checks["returned_to_shareholders_words"]).group(1))
        self.assertTrue(said * 1000 < returns[-1] < (said + 1) * 1000, checks["returned_to_shareholders_words"])
        self.assertTrue(all(program <= cash for program, cash in
                            zip(self.fy["share_repurchase_program"], self.fy["stock_repurchases"])))
        coverage = [value / base * 100 for value, base in zip(returns, adjusted)]
        self.assertIn(f"股东回报已占到调整后自由现金流的 {coverage[-1]:.1f}%", self.payload["headline"])

        exhibit = next(ex for ex in self.exhibits if "股东回报已达调整后自由现金流" in ex["title"])
        self.assertEqual(exhibit["xlabels"], self.fy["labels"])
        self.assertEqual([group["values"] for group in exhibit["groups"]],
                         [reported, adjusted, returns])
        # The analysis counted the cash-flow repurchase line; the page says what
        # that basis gives beside the company's own.
        cash_basis = (self.fy["stock_repurchases"][-1] + self.fy["dividends_paid"][-1]) / adjusted[-1] * 100
        self.assertIn(f"覆盖率为 {cash_basis:.1f}%", exhibit["note"])

    def test_intelligent_cloud_gross_margin_is_derived_from_the_segment_note(self) -> None:
        chart = next(ex for ex in self.exhibits if ex["title"].startswith("Intelligent Cloud 分部毛利率"))
        expected = [
            (revenue - cost) / revenue * 100
            for revenue, cost in zip(
                self.segments["intelligent_cloud_revenue"],
                self.segments["intelligent_cloud_cost_of_revenue"],
            )
        ]
        self.assertEqual(chart["values"], expected)
        # A run of falls and then a rise is counted from the record, and the
        # note says the record starts where the quarterly disclosure does.
        falls = 0
        for a, b in zip(reversed(expected[:-2]), reversed(expected[1:-1])):
            if b < a:
                falls += 1
            else:
                break
        if expected[-1] > expected[-2] and falls >= 2:
            self.assertIn(f"连降{cn_count(falls)}季后首次回升", chart["title"])
        self.assertIn("季度分部收入成本自", chart["note"])
        annual = self.segments["ic_annual_before_quarterly"]
        for label, revenue, cost in zip(annual["labels"], annual["revenue"], annual["cost_of_revenue"]):
            self.assertIn(f"{label} {(revenue - cost) / revenue * 100:.1f}%", chart["note"])

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
            # Titles are drawn into SVG labels; markup there prints literally.
            self.assertNotRegex(exhibit["title"], r"</?[a-z]+>", exhibit["n"])
            self.assertNotIn("**", exhibit.get("note", ""), exhibit["n"])

    def test_each_section_holds_what_it_is_named_for(self) -> None:
        prior, nxt = self.source["prior_kpi_settlement"], self.source["next_kpi"]
        self.assertEqual(
            [(s["id"], len(s["exhibits"])) for s in self.payload["sections"]],
            [("settled", 1 + 1 + len(drawn_reads(self.source, prior)) + 1),
             ("quarter_highlights", 6),
             ("next_quarter", 1 + len(drawn_reads(self.source, nxt))),
             ("routine", 5)],
        )
        # A chart whose title is a range over the whole record is not this
        # quarter's conclusion; it belongs with the long series.
        for exhibit in self.by_section["quarter_highlights"]:
            self.assertNotRegex(exhibit["title"], r"季在 .* 之间", exhibit["title"])
        self.assertTrue(any(ex["title"].startswith("其他收入（净）")
                            for ex in self.by_section["routine"]))

    def test_long_history_agrees_with_the_reviewed_quarters(self) -> None:
        """The ten-year series and the reviewed quarters must not disagree.

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
        # Every aligned array is as long as the quarter axis.
        for key, values in long.items():
            if isinstance(values, list) and key != "quarters":
                self.assertEqual(len(values), len(long["quarters"]), key)

    def test_the_filed_quarter_ends_tie_to_the_fiscal_year(self) -> None:
        """The quarter-end balances the §8 lines read -- capex still unpaid, leases
        not yet commenced -- land on the 10-K's own year-end figures, and the two
        interest lines add up to each complete fiscal year the 10-K prints."""
        long, fy = self.source["long_history"], self.fy
        index = {quarter: i for i, quarter in enumerate(long["quarters"])}
        for label, unpaid, leases in zip(fy["labels"], fy["unpaid_capex_in_payables"],
                                         fy["contracted_not_yet_commenced_leases"]):
            june = f"{label[2:]}Q2"
            self.assertEqual(round(long["unpaid_capex_in_payables_usd_bn"][index[june]] * 1000), unpaid, label)
            self.assertEqual(round(long["leases_not_commenced_usd_bn"][index[june]] * 1000), leases, label)
        components = fy["other_income_components"]
        for at, label in enumerate(components["labels"]):
            june = index.get(f"{label[2:]}Q2")
            if june is None or june < 3:
                continue
            window = slice(june - 3, june + 1)
            self.assertEqual(sum(long["interest_and_dividends_income_usd_m"][window]),
                             components["interest_and_dividends_income"][at], label)
            self.assertEqual(sum(long["interest_expense_usd_m"][window]),
                             components["interest_expense"][at], label)
            self.assertEqual(sum(long["other_income_expense_net_usd_m"][window]),
                             components["total"][at], label)

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

        depreciation_chart = next(ex for ex in self.exhibits if ex["title"].startswith("季度折旧"))
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
        lease_chart = next(ex for ex in self.exhibits if ex["title"].startswith("融资租赁新增"))
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
        prior, nxt = self.source["prior_kpi_settlement"], self.source["next_kpi"]
        self.assertEqual(len(tables[0]["rows"]), len(prior["quantified"]) + len(prior.get("unscored", [])))
        self.assertEqual(len(tables[1]["rows"]), len(nxt["quantified"]) + len(nxt.get("unscored", [])))
        segment_table = next(t for t in tables if "分部收入" in t["title"])
        self.assertEqual(len(segment_table["rows"]), len(self.segments["periods"]))
        base_table = next(t for t in tables if "季度基础数据" in t["title"])
        self.assertEqual(len(base_table["rows"]), len(self.source["periods"]))
        # The section-8 M365 line reads the adjusted rate; the reported one is
        # printed beside it.
        m365 = self.source["operating_kpi"]["m365_commercial_cloud"]
        kpi_table = next(t for t in tables if t["title"].startswith("披露不连续的运营指标"))
        m365_row = next(r for r in kpi_table["rows"] if r[0].startswith("M365 商业云收入同比"))
        self.assertIn(f"{m365['adjusted_pct'][-1]} / {m365['reported_pct'][-1]}", m365_row[2])
        # Net cash with finance-lease liabilities counted as debt, from the 10-K.
        fy = self.fy
        net = [cash - current - term - leases for cash, current, term, leases in zip(
            fy["cash_and_short_term_investments"], fy["current_portion_of_long_term_debt"],
            fy["long_term_debt"], fy["finance_lease_liabilities"])]
        fy_table = next(t for t in tables if "两个财政年度" in t["title"])
        row = next(r for r in fy_table["rows"] if r[0].startswith("净现金"))
        for value, cell in zip(net, row[1:3]):
            self.assertIn(f"${abs(value):,.0f}M", cell)

    def test_market_expectation_is_labelled_and_unattributed(self) -> None:
        text = json.dumps(self.payload, ensure_ascii=False)
        for broker in ["FactSet", "Bloomberg", "Seeking Alpha", "consensus", "Anthropic"]:
            self.assertNotIn(broker.lower(), text.lower())
        block = self.source.get("market_expectation")
        if block is None:
            # The block is one quarter's and optional: without it nothing of it prints.
            for gone in ("市场预期区间", "股价约"):
                self.assertNotIn(gone, text)
            return
        self.assertIn("市场预期", text)
        self.assertEqual(block["as_of"], self.source["latest"]["release_date"])
        # Two public sources disagree, so only the direction is published.
        low, high = block["revenue_usd_m_range"]
        self.assertIn(f"两个公开来源相差 ${high - low:,}M", text)
        self.assertIn("不发布超预期幅度", text)
        # The price move is named with when it was read, and as market data.
        self.assertIn(f"{block['post_earnings_price_when']}股价约 ", self.payload["headline"])
        self.assertIn("（市场数据，非公司披露）", self.payload["headline"])
        self.assertNotIn("财报当日股价", self.payload["headline"])

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
           "guidance_delivery", "other_income_story")


class MsftChecksTest(unittest.TestCase):
    """The page's quarter against a record keyed separately from the filing.

    `_checks` is typed once per quarter from the earnings release (and the 10-K
    and the call for the few items the release does not print), with the place
    each figure was read from. It is not copied from the arrays and the builder
    never reads it (`test_data_only_roll`).
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = load_source()
        cls.checks = cls.source["_checks"]
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for s in cls.payload["sections"] for ex in s["exhibits"]]
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
        fy = self.source["fiscal_year_usd_m"]
        returns = fy["share_repurchase_program"][-1] + fy["dividends_paid"][-1]
        said = re.search(r"over \$(\d+) billion", c["fiscal_year"]["returned_to_shareholders_words"])
        self.assertIsNotNone(said, c["fiscal_year"]["returned_to_shareholders_words"])
        self.assertEqual(int(returns // 1000), int(said.group(1)))

    def test_the_page_prints_the_checked_figures(self) -> None:
        c = self.checks
        revenue_chart = next(ex for ex in self.exhibits if ex["title"].startswith("收入 $"))
        self.assertIn(f"收入 ${c['revenue_usd_m']:,}M", revenue_chart["title"])
        grouped = next(ex for ex in self.exhibits if "股东回报已达调整后自由现金流" in ex["title"])
        cfy = c["fiscal_year"]
        self.assertEqual(grouped["groups"][2]["values"][-1],
                         cfy["share_repurchase_program_usd_m"] + cfy["dividends_paid_usd_m"])
        self.assertIn(f"+{c['azure_growth_printed_pct']}%", self.payload["brief"])

    def test_the_settlement_readings_are_the_checked_figures(self) -> None:
        """Every threshold is settled against a reading the series carries; the
        ones the release, the 10-K, the 10-Q and the call print are re-read here."""
        k, source = self.checks["kpi"], self.source
        kpi, long, q = source["operating_kpi"], source["long_history"], self.q
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
        self.assertEqual(expected_reading(source, "m365_cc_adjusted"), k["m365_commercial_cloud_adjusted_pct"])
        self.assertEqual(kpi["m365_commercial_cloud"]["reported_pct"][-1], k["m365_commercial_cloud_reported_pct"])
        self.assertEqual(long["leases_not_commenced_usd_bn"][-1], k["leases_not_commenced_usd_bn"])
        self.assertEqual(long["leases_not_commenced_usd_bn"][-2], k["leases_not_commenced_prior_quarter_usd_bn"])
        self.assertEqual(long["unpaid_capex_in_payables_usd_bn"][-1], k["unpaid_capex_quarter_end_usd_bn"])
        self.assertEqual(long["unpaid_capex_in_payables_usd_bn"][-2], k["unpaid_capex_prior_quarter_end_usd_bn"])
        components = source["fiscal_year_usd_m"]["other_income_components"]
        self.assertEqual(components["interest_and_dividends_income"][-1], k["interest_and_dividends_income_fy_usd_m"])
        self.assertEqual(components["interest_expense"][-1], k["interest_expense_fy_usd_m"])
        self.assertEqual(components["total"][-1], k["other_income_fy_usd_m"])
        self.assertEqual(components["largest_customer_equity_method_net_usd_bn"][-1],
                         k["largest_customer_equity_method_net_fy_usd_bn"])
        story = source.get("other_income_story")
        if story is None:
            self.assertNotIn("discrete_gain_usd_bn", k)
        else:
            self.assertEqual(story["discrete_gain_usd_bn"], k["discrete_gain_usd_bn"])
            self.assertEqual(story["discrete_eps_net_usd"], k["discrete_eps_net_usd"])
        rpo_chart = next(ex for ex in self.exhibits if ex["title"].startswith("商业剩余履约义务"))
        self.assertIn(f"US${k['commercial_rpo_usd_bn']}B", rpo_chart["title"])
        self.assertIn(f"余额同比 +{k['commercial_rpo_growth_printed_pct']}%", rpo_chart["note"])


class MsftSectionOneTest(unittest.TestCase):
    """Section one against the two analyses, as `_checks["note"]` records them."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = load_source()
        cls.note = cls.source["_checks"]["note"]
        cls.payload = build_payload(cls.source)
        cls.settled = section(cls.payload, "settled")
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
        for label, count in closure["counts"].items():
            if count:
                self.assertIn(f"{count} 条{label}", chart["title"])
        block = self.source["followup_closure"]
        self.assertEqual({label: len(topics) for label, topics in block["topics"].items()},
                         {label: len(numbers) for label, numbers in closure["questions"].items()})
        self.assertIn(block["rule"], chart["note"])
        for item in block.get("verdicts_in_full", []):
            self.assertIn(item["words"], chart["note"])

    def test_the_prior_lines_are_the_previous_analysis_s_rows(self) -> None:
        self.assertEqual(
            [(e["id"], e["row"], e["tier"], e["threshold"], e["direction"]) for e in self.prior["quantified"]],
            [(t["id"], t["row"], t["tier"], t["threshold"], t["direction"]) for t in self.note["prior_thresholds"]])
        rows = {e["row"] for e in self.prior["quantified"]} | {i["row"] for i in self.prior.get("unscored", [])}
        self.assertEqual(len(rows), self.note["prior_rows"])
        self.assertEqual(self.prior["rows"], self.note["prior_rows"])
        self.assertEqual(sorted({i["row"] for i in self.prior.get("unscored", [])}), self.note["prior_unscored_rows"])
        for entry in self.prior["quantified"]:
            for typed in ("actual", "reading", "current"):
                self.assertNotIn(typed, entry, entry["id"])

    def test_the_overview_settles_every_line_at_its_reading(self) -> None:
        overview = self.settled[1]
        self.assertEqual(overview["kind"], "diverging_bars")
        period = self.source["latest"]["period"]
        bars = bars_of(self.prior, settling=True, period=period)
        self.assertTrue(overview["title"].startswith(f"上季 {len(bars)} 条量化阈值："), overview["title"])
        self.assertEqual(overview["xlabels"], [e["label"] for e in bars])
        for entry, plotted in zip(bars, overview["values"]):
            reading = expected_reading(self.source, entry["reads"])
            self.assertAlmostEqual(plotted, round(headroom_pct(entry, reading), 1), places=6, msg=entry["id"])
        for entry in self.prior["quantified"]:
            if entry["threshold"] == 0:
                self.assertIn(f"「{entry['label']}」的阈值是 0", overview["note"])
        for item in self.prior.get("unscored", []):
            self.assertIn(item["text"], overview["note"])
        targets = [e for e in bars if e["tier"] in TARGET_TIERS]
        reached = [e for e in targets if favourable_side(e, expected_reading(self.source, e["reads"]))]
        if targets and len(reached) == len(targets):
            self.assertIn(f"{len(targets)} 条目标线全部达到", overview["title"])
        # A line written as an event (「不再披露」) that went off is named in the
        # title, so 「no alarm set off」 cannot stand for the whole section.
        set_off = [item for item in self.prior.get("unscored", []) if item.get("set_off")]
        self.assertEqual(sorted(item["row"] for item in set_off), self.note.get("prior_set_off_rows", []))
        for item in set_off:
            self.assertIn(f"「{item['set_off']}」", overview["title"])
        if not set_off:
            self.assertNotIn("不能量化的警戒已触发", overview["title"])

    def test_every_record_long_enough_to_draw_gets_its_lines(self) -> None:
        lines = [ex for ex in self.settled if ex["kind"] == "lines"]
        drawn = drawn_reads(self.source, self.prior)
        self.assertEqual(len(lines), len(drawn))
        by_reads: dict[str, list] = {}
        for entry in self.prior["quantified"]:
            by_reads.setdefault(entry["reads"], []).append(entry)
        for reads, chart in zip(drawn, lines):
            flat = {tuple(set(s["values"])) for s in chart["series"][1:]}
            for entry in by_reads[reads]:
                with self.subTest(line=entry["id"]):
                    self.assertIn((entry["threshold"],), flat)
                    word = "达到" if entry["tier"] in TARGET_TIERS else "触发"
                    self.assertRegex(chart["title"], rf"(未)?{word}上季{entry['tier']}线 ")
            self.assertIn(by_reads[reads][0]["basis"], chart["note"])
        overview = self.settled[1]
        for reads, entries in by_reads.items():
            if reads not in drawn:
                self.assertIn(f"{entries[0]['metric']}没有单独的线图", overview["note"])

    def test_the_verdicts_follow_the_readings(self) -> None:
        """A target and an alarm on one record, then the reading pushed past both
        the wrong way: every verdict in the titles turns. The lines are set here
        around the current reading, so the check does not lean on which lines
        this quarter's analysis happened to write."""
        shifted = copy.deepcopy(self.source)
        azure = shifted["azure_growth_cc_pct"]
        now = azure[-1]
        base = {"row": 1, "reads": "azure_cc", "metric": "Azure 固定汇率增速", "direction": "up",
                "unit": "pct", "basis": "演练"}
        shifted["prior_kpi_settlement"]["quantified"] = [
            {**base, "id": "drill_target", "tier": "期望", "label": "演练目标", "threshold": now},
            {**base, "id": "drill_alarm", "tier": "红旗", "label": "演练红旗", "threshold": now - 2}]
        shifted["prior_kpi_settlement"]["unscored"] = []

        def titles() -> tuple[str, str]:
            settled = section(build_payload(shifted), "settled")
            chart = next(ex for ex in settled if ex["kind"] == "lines" and ex["title"].startswith("Azure"))
            return chart["title"], settled[1]["title"]

        chart, overview = titles()
        self.assertIn(f"：达到上季期望线 {now:g}%，未触发上季红旗线 {now - 2:g}%", chart)
        self.assertIn("1 条目标线全部达到，1 条警戒线都没有触发", overview)
        azure[-1] = now - 3
        chart, overview = titles()
        self.assertIn(f"：未达到上季期望线 {now:g}%，触发上季红旗线 {now - 2:g}%", chart)
        self.assertIn("1 条目标线一条都没有达到，1 条警戒线全部触发", overview)

    def test_the_company_guide_is_scored_against_the_filings(self) -> None:
        block = self.source["guidance_delivery"]
        chart = self.settled[-1]
        self.assertTrue(chart["title"].startswith(f"上季电话会给本季的 {len(block['items'])} 项指引："), chart["title"])
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
        above = [item["metric"] for item in block["items"] if actual[item["reads"]] > item["high"]]
        if above:
            self.assertIn("、".join(above) + "高于区间上端", chart["title"])

    def test_the_falsified_call_is_dated_by_the_transcripts(self) -> None:
        """The analysis called last quarter's AI run-rate its first disclosure;
        the company's own transcripts carry an earlier one, and the page says so,
        with the gap counted from the two dated disclosures the block records."""
        def gap_words(disclosures: list[dict]) -> str:
            (q1, y1), (q2, y2) = (d["period"].split() for d in disclosures[-2:])
            return f"上季时隔{cn_count((int(y2) * 4 + int(q2[1])) - (int(y1) * 4 + int(q1[1])))}季再次给出"

        # A drill: two disclosures six quarters apart must read 「时隔六季」.
        period = self.source["latest"]["period"]
        quarter, year = period.split()
        at = int(year) * 4 + int(quarter[1]) - 1           # this quarter, 0-based
        drill = copy.deepcopy(self.source)
        drill["followup_closure"]["falsified_story"] = "上季时隔{gap}季再次给出（{latest}，上一次是 {first_period}（{first_fiscal}）的 {first}）。"
        drill["followup_closure"]["ai_run_rate_disclosures"] = [
            {"period": f"Q{(at - 7) % 4 + 1} {(at - 7) // 4}", "usd_bn": 5},
            {"period": f"Q{(at - 1) % 4 + 1} {(at - 1) // 4}", "usd_bn": 9}]
        note = section(build_payload(drill), "settled")[0]["note"]
        self.assertIn("上季时隔六季再次给出（$9B", note)
        self.assertEqual(gap_words(drill["followup_closure"]["ai_run_rate_disclosures"]), "上季时隔六季再次给出")

        closure = self.source["followup_closure"]
        disclosures = closure.get("ai_run_rate_disclosures", [])
        if closure.get("falsified_story") and len(disclosures) >= 2:
            self.assertIn(gap_words(disclosures), self.settled[0]["note"])
            self.assertIn(f"${disclosures[-2]['usd_bn']:g}B", self.settled[0]["note"])
        else:
            self.assertNotIn("季再次给出", self.settled[0]["note"])


class MsftSectionTwoTest(unittest.TestCase):
    """This quarter's conclusions, each drawn from filed numbers."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = load_source()
        cls.payload = build_payload(cls.source)
        cls.highlights = section(cls.payload, "quarter_highlights")

    def test_other_income_is_the_10k_note_and_its_share_of_the_profit_increase(self) -> None:
        fy = self.source["fiscal_year_usd_m"]
        components = fy["other_income_components"]
        chart = next(ex for ex in self.highlights if ex["title"].startswith(f"{fy['labels'][-1]} 其他收入（净）"))
        keys = ["interest_and_dividends_income", "interest_expense", "net_recognized_gains_on_investments",
                "net_gains_on_derivatives", "net_gains_on_foreign_currency_remeasurements", "other_net"]
        for at, _ in enumerate(components["labels"]):
            self.assertEqual(sum(components[key][at] for key in keys), components["total"][at])
        now, before = (components["labels"].index(fy["labels"][-1]), components["labels"].index(fy["labels"][-2]))
        self.assertEqual([group["values"] for group in chart["groups"]],
                         [[components[key][before] for key in keys], [components[key][now] for key in keys]])
        swing = components["total"][now] - components["total"][before]
        pretax_increase = (fy["operating_income"][-1] + components["total"][now]
                           - fy["operating_income"][-2] - components["total"][before])
        self.assertIn(f"占税前利润增量的 {swing / pretax_increase * 100:.1f}%", chart["title"])

    def test_first_is_checked_against_every_quarter_on_the_current_basis(self) -> None:
        segments = self.source["segments_usd_m"]
        recast = segments["recast_before_window"]
        ic = recast["intelligent_cloud_revenue"] + segments["intelligent_cloud_revenue"]
        pbp = recast["productivity_revenue"] + segments["productivity_revenue"]
        first = ic[-1] > pbp[-1] and all(a <= b for a, b in zip(ic[:-1], pbp[:-1]))
        chart = next(ex for ex in self.highlights if "Intelligent Cloud" in ex["title"]
                     and "Productivity" in ex["title"])
        self.assertEqual("首次超过" in chart["title"], first)
        if first:
            self.assertIn("现行分部口径", chart["title"])
            old = segments["pre_recast_crossover"]
            self.assertIn(f"IC ${old['intelligent_cloud_revenue']:,}M、PBP ${old['productivity_revenue']:,}M",
                          chart["note"])
            # The old basis's crossover year is named as such only with the
            # year before it on the page, PBP still ahead.
            before = (f"{old['prior_fiscal_year']} 还是 ${old['prior_intelligent_cloud_revenue']:,}M 对 "
                      f"${old['prior_productivity_revenue']:,}M")
            self.assertEqual(before in chart["note"],
                             old["prior_intelligent_cloud_revenue"] <= old["prior_productivity_revenue"])
            self.assertNotIn("起就大于", chart["note"])
        # A quarter of the recast year in which IC led would take 「first」 away.
        led = copy.deepcopy(self.source)
        led["segments_usd_m"]["recast_before_window"]["intelligent_cloud_revenue"][0] = 30000
        text = published_text(build_payload(led))
        self.assertNotIn("首次超过 Productivity", text)
        self.assertNotIn("首次成为最大分部", text)

    def test_the_rpo_shares_are_the_company_s_own(self) -> None:
        rpo = self.source["operating_kpi"]["commercial_rpo"]
        chart = next(ex for ex in self.highlights if ex["title"].startswith("商业剩余履约义务"))
        period = self.source["latest"]["period"]
        quarter, year = period.split()
        year_ago = f"{quarter} {int(year) - 1}"
        shares = dict(zip(rpo["periods"], rpo["twelve_month_share_pct"]))
        if shares.get(year_ago) is not None and shares.get(period) is not None:
            self.assertIn(f"一年前的约 {shares[year_ago]}%", chart["note"])
            self.assertIn(f"约 {shares[period]}%", chart["note"])
        long = self.source["long_history"]["commercial_rpo_usd_bn"]
        self.assertEqual(chart["values"], [value for value in long if value is not None])


class MsftSectionThreeTest(unittest.TestCase):
    """Section three against this quarter's section 8, as `_checks["note"]` has it."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = load_source()
        cls.note = cls.source["_checks"]["note"]
        cls.payload = build_payload(cls.source)
        cls.next = section(cls.payload, "next_quarter")
        cls.block = cls.source["next_kpi"]

    def test_the_lines_are_the_analysis_s_section_8(self) -> None:
        self.assertEqual(
            [(e["id"], e["row"], e["tier"], e["threshold"], e["direction"]) for e in self.block["quantified"]],
            [(t["id"], t["row"], t["tier"], t["threshold"], t["direction"]) for t in self.note["next_thresholds"]])
        self.assertEqual(self.block["rows"], self.note["next_rows"])
        numbered = {e["row"] for e in self.block["quantified"] if isinstance(e["row"], int)}
        self.assertEqual(len(numbered), self.note["next_rows"])
        self.assertEqual([i["row"] for i in self.block.get("unscored", [])], self.note["next_unscored_rows"])
        for entry in self.block["quantified"]:
            for typed in ("actual", "reading", "current"):
                self.assertNotIn(typed, entry, entry["id"])
        # The page sets no lines of its own; the four it once carried are gone.
        text = published_text(self.payload)
        for invented in ("股东回报 / 调整后自由现金流：下季阈值", "已签约未起租租约 / 年收入",
                         "Intelligent Cloud 分部毛利率：下季阈值", "单季自由现金流（报告口径）：下季阈值"):
            self.assertNotIn(invented, text)

    def test_the_overview_is_the_current_reading_against_every_line(self) -> None:
        overview = self.next[0]
        bars = bars_of(self.block, settling=False)
        self.assertTrue(overview["title"].startswith(f"下季 {len(bars)} 条量化阈值："), overview["title"])
        self.assertEqual([label.split("（")[0] if "settles" in entry else label
                          for label, entry in zip(overview["xlabels"], bars)],
                         [entry["label"].split("（")[0] if "settles" in entry else entry["label"]
                          for entry in bars])
        for entry, plotted in zip(bars, overview["values"]):
            reading = expected_reading(self.source, entry["reads"])
            expected = round(headroom_pct(entry, reading), 1)
            self.assertAlmostEqual(plotted, expected + 0.0, places=6, msg=entry["id"])
            self.assertNotEqual(str(plotted), "-0.0", entry["id"])
        good = sum(1 for e in bars if favourable_side(e, expected_reading(self.source, e["reads"])))
        if good == len(bars):
            self.assertIn("当前全部在有利一侧", overview["title"])
        else:
            self.assertIn(f"当前 {good} 条在有利一侧、{len(bars) - good} 条在不利一侧", overview["title"])
        for entry in self.block["quantified"]:
            if "settles" in entry:
                self.assertIn(f"（{entry['settles']} 结算）", " ".join(overview["xlabels"]))
            if entry["threshold"] == 0:
                self.assertIn(f"「{entry['label']}」的阈值是 0", overview["note"])
        for item in self.block.get("unscored", []):
            self.assertIn(item["text"], overview["note"])

    def test_a_compound_condition_is_read_leg_by_leg(self) -> None:
        overview = self.next[0]
        groups: dict[str, list] = {}
        for entry in self.block["quantified"]:
            if entry.get("group"):
                groups.setdefault(entry["group"], []).append(entry)
        self.assertTrue(groups)
        for legs in groups.values():
            self.assertIn("」与「".join(leg["label"] for leg in legs), overview["note"])
            both = all(not favourable_side(leg, expected_reading(self.source, leg["reads"])) for leg in legs)
            self.assertEqual("当前两腿都已在触发一侧" in overview["note"].split("」与「".join(
                leg["label"] for leg in legs), 1)[1][:80], both)

    def test_every_record_long_enough_to_draw_gets_its_lines(self) -> None:
        lines = self.next[1:]
        drawn = drawn_reads(self.source, self.block)
        self.assertEqual(len(lines), len(drawn))
        by_reads: dict[str, list] = {}
        for entry in self.block["quantified"]:
            by_reads.setdefault(entry["reads"], []).append(entry)
        for reads, chart in zip(drawn, lines):
            self.assertEqual(chart["kind"], "lines")
            self.assertIn("：下季阈值 ", chart["title"])
            flat = {tuple(set(s["values"])) for s in chart["series"][1:]}
            for entry in by_reads[reads]:
                self.assertIn((entry["threshold"],), flat, entry["id"])
            reading = expected_reading(self.source, reads)
            self.assertTrue(chart["title"].endswith("，当前 " + chart["title"].rsplit("，当前 ", 1)[1]))
            self.assertAlmostEqual([v for v in chart["series"][0]["values"] if v is not None][-1], reading, places=6)
        for reads, entries in by_reads.items():
            if reads not in drawn:
                self.assertIn(f"{entries[0]['metric']}没有单独的线图", self.next[0]["note"])


def rolled_forward(source: dict) -> dict:
    """The series as a data-only roll to the next quarter would leave it, in memory.

    Every aligned array gains one cell -- the same quarter a year earlier -- so
    the identities the real quarters satisfy still hold and the drill tests the
    mechanics, not invented figures. The one-quarter blocks go the way a roll
    takes them: `next_kpi` moves, as it stands, into `prior_kpi_settlement`;
    this quarter's call guide (`outlook`) becomes the guide the next quarter is
    scored against; a new section-0 closure is stamped; the blocks that only
    this quarter had are dropped. Nothing is written to disk.
    """
    s = copy.deepcopy(source)
    period = s["periods"][-1]
    quarter, year = period.split()
    index = int(year) * 4 + int(quarter[1])          # next quarter, 1-based
    new_q, new_y = index % 4 + 1, index // 4
    new = f"Q{new_q} {new_y}"
    fiscal = f"FY{new_y + 1} Q{new_q - 2}" if new_q >= 3 else f"FY{new_y} Q{new_q + 2}"
    s["periods"].append(new)
    for values in s["quarterly_usd_m"].values():
        values.append(values[-4])
    seg = s["segments_usd_m"]
    width = len(seg["periods"])
    for key, values in seg.items():
        if isinstance(values, list) and key != "periods" and len(values) == width:
            values.append(values[-4])
    seg["periods"].append(new)
    s["azure_growth_cc_pct"].append(s["azure_growth_cc_pct"][-4])
    long = s["long_history"]
    width = len(long["quarters"])
    for key, values in long.items():
        if isinstance(values, list) and key != "quarters" and len(values) == width:
            values.append(values[-4])
    long["quarters"].append(f"{new_y}Q{new_q}")
    for block in s["operating_kpi"].values():
        if isinstance(block, dict) and "periods" in block:
            width = len(block["periods"])
            for key, values in block.items():
                if isinstance(values, list) and key != "periods" and len(values) == width:
                    values.append(values[-1])
            block["periods"].append(new)
    end = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}[new_q]
    s["latest"] = {**s["latest"], "period": new, "fiscal_period": fiscal,
                   "period_end": f"{new_y}-{end}", "release_date": f"{new_y}-{int(end[:2]) + 1:02d}-28"}
    s["sources"].insert(0, {"label": f"{fiscal} 业绩发布 8-K",
                            "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=789019&type=8-K"})
    kpi = s["next_kpi"]
    s["prior_kpi_settlement"] = {**{k: v for k, v in kpi.items() if k != "for_period"},
                                 "period": new, "set_in": period}
    s["next_kpi"] = {**kpi, "period": new, "for_period": f"Q{new_q % 4 + 1} {new_y + (new_q == 4)}"}
    s["followup_closure"] = {
        "period": new, "set_in": period, "labels": ["已验证", "部分验证", "被证伪"], "counts": [2, 1, 0],
        "topics": {"已验证": ["演练问题 1", "演练问题 2"], "部分验证": ["演练问题 3"], "被证伪": []},
        "rule": "演练：按第 0 节判定词归类"}
    outlook = s.pop("outlook")
    s["guidance_delivery"] = {
        "period": new, "given_on": source["latest"]["release_date"],
        "items": [{"metric": "总收入", "reads": "revenue", "low": outlook["revenue_usd_m"][0],
                   "high": outlook["revenue_usd_m"][1]},
                  {"metric": "PBP", "reads": "pbp_revenue", "low": outlook["productivity_usd_m"][0],
                   "high": outlook["productivity_usd_m"][1]},
                  {"metric": "IC", "reads": "ic_revenue", "low": outlook["intelligent_cloud_usd_m"][0],
                   "high": outlook["intelligent_cloud_usd_m"][1]},
                  {"metric": "MPC", "reads": "mpc_revenue", "low": outlook["more_personal_computing_usd_m"][0],
                   "high": outlook["more_personal_computing_usd_m"][1]},
                  {"metric": "销货成本", "reads": "cogs", "low": outlook["cost_of_revenue_usd_m"][0],
                   "high": outlook["cost_of_revenue_usd_m"][1], "cost": True},
                  {"metric": "经营费用", "reads": "opex", "low": outlook["operating_expenses_usd_m"][0],
                   "high": outlook["operating_expenses_usd_m"][1], "cost": True}],
        "azure_cc_guide_pct": [outlook["azure_cc_growth_pct"], outlook["azure_cc_growth_pct"]]}
    for gone in ("market_expectation", "other_income_story"):
        s.pop(gone, None)
    return s


class MsftRollDrillTest(unittest.TestCase):
    """A roll is a data edit: the next quarter builds from the series alone, and
    section one then settles this quarter's section-8 lines."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = load_source()
        cls.rolled = rolled_forward(cls.source)
        cls.payload = build_payload(cls.rolled)

    def test_the_next_quarter_builds_in_the_four_sections(self) -> None:
        self.assertEqual([(s["id"], s["title"]) for s in self.payload["sections"]], SECTIONS)
        self.assertEqual(self.payload["latest"]["disclosed_period_label"], self.rolled["latest"]["period"])

    def test_section_one_settles_this_quarter_s_lines(self) -> None:
        settled = section(self.payload, "settled")
        prior = self.rolled["prior_kpi_settlement"]
        closure = self.rolled["followup_closure"]
        self.assertTrue(settled[0]["title"].startswith(f"上季 {sum(closure['counts'])} 条待验证问题："))
        bars = bars_of(prior, settling=True, period=self.rolled["latest"]["period"])
        overview = settled[1]
        self.assertTrue(overview["title"].startswith(f"上季 {len(bars)} 条量化阈值："), overview["title"])
        self.assertEqual(overview["xlabels"], [e["label"] for e in bars])
        for entry, plotted in zip(bars, overview["values"]):
            reading = expected_reading(self.rolled, entry["reads"])
            self.assertAlmostEqual(plotted, round(headroom_pct(entry, reading), 1) + 0.0, places=6, msg=entry["id"])
        # A line dated later than the new quarter is carried, not judged.
        for entry in prior["quantified"]:
            if "settles" in entry:
                self.assertIn(f"{entry['label']}（{entry['settles']} 结算）", overview["note"])
        lines = [ex for ex in settled if ex["kind"] == "lines"]
        self.assertTrue(lines)
        for chart in lines:
            self.assertIn("上季", chart["title"])
        self.assertTrue(settled[-1]["title"].startswith("上季电话会给本季的"))
        # A compound condition carried over from section three is settled leg by leg.
        groups: dict[str, list] = {}
        for entry in prior["quantified"]:
            if entry.get("group"):
                groups.setdefault(entry["group"], []).append(entry)
        for legs in groups.values():
            both = all(not favourable_side(leg, expected_reading(self.rolled, leg["reads"])) for leg in legs)
            self.assertIn("」与「".join(leg["label"] for leg in legs) + f"」要同时成立才算{legs[0]['tier']}："
                          + ("本季两腿同时成立，触发" if both else "本季没有同时成立，未触发"), overview["note"])
        # Nothing stamped for the quarter before leaks into the one after it:
        # not its section-0 story, not its table header, not its market reading.
        text = published_text(self.payload)
        story = self.source["followup_closure"]
        disclosures = story.get("ai_run_rate_disclosures", [])
        if story.get("falsified_story") and len(disclosures) >= 2:
            self.assertIn("季再次给出", published_text(build_payload(self.source)))
            self.assertNotIn("季再次给出", text)
        self.assertNotIn(self.source["latest"]["period"] + " 实际", text)
        self.assertNotIn("市场预期区间", text)


class MsftRollTest(unittest.TestCase):
    """What a quarter roll can and cannot get past."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = load_source()
        cls.payload = build_payload(cls.source)

    def test_a_block_stamped_with_another_quarter_stops_the_build(self) -> None:
        for key in STAMPED:
            stale = copy.deepcopy(self.source)
            stale[key]["period"] = "Q1 1999"
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    build_payload(stale)

    def test_the_settlement_blocks_must_point_at_the_neighbouring_quarters(self) -> None:
        for key, field, words in (("prior_kpi_settlement", "set_in", "last quarter"),
                                  ("followup_closure", "set_in", "last quarter"),
                                  ("next_kpi", "for_period", "next quarter")):
            stale = copy.deepcopy(self.source)
            stale[key][field] = "Q1 1999"
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, words):
                    build_payload(stale)

    def test_a_threshold_that_reads_an_unknown_record_stops_the_build(self) -> None:
        broken = copy.deepcopy(self.source)
        broken["next_kpi"]["quantified"][0]["reads"] = "no_such_record"
        with self.assertRaisesRegex(ValueError, "does not know"):
            build_payload(broken)

    def test_a_missing_quarter_block_leaves_its_part_out(self) -> None:
        bare = copy.deepcopy(self.source)
        for key in STAMPED:
            del bare[key]
        payload = build_payload(bare)
        self.assertEqual([s["id"] for s in payload["sections"]], ["quarter_highlights", "routine"])
        text = published_text(payload)
        for gone in ("股价约", "下季与 FY", "市场预期区间", "待验证问题", "超自身指引", "离散项"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, text)

    def test_the_quarter_release_must_be_in_the_sources(self) -> None:
        missing = copy.deepcopy(self.source)
        fiscal = missing["latest"]["fiscal_period"]
        missing["sources"] = [s for s in missing["sources"] if not s["label"].startswith(fiscal)]
        with self.assertRaisesRegex(ValueError, "sources"):
            build_payload(missing)

    def assert_claims_follow(self, name: str, true_tree: dict, false_tree: dict, claims: list[str]) -> None:
        """Each claim prints on the tree built to make it true and is gone from
        the one built to make it false. Both trees are made here, from the
        series, so neither side leans on what this quarter happens to be."""
        yes, no = published_text(build_payload(true_tree)), published_text(build_payload(false_tree))
        for claim in claims:
            with self.subTest(case=name, claim=claim):
                self.assertIn(claim, yes)
                self.assertNotIn(claim, no)

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        source = self.source

        # 「First」: every earlier quarter on the current segment basis had PBP
        # ahead, including the recast year before the window.
        def ic_first(led_earlier: bool) -> dict:
            tree = copy.deepcopy(source)
            segments = tree["segments_usd_m"]
            recast = segments.get("recast_before_window")
            for pool in [segments] + ([recast] if recast else []):
                pool["intelligent_cloud_revenue"] = [pbp - 1 for pbp in pool["productivity_revenue"]]
            segments["intelligent_cloud_revenue"][-1] = max(segments["productivity_revenue"][-1],
                                                            segments["more_personal_computing_revenue"][-1]) + 1
            if led_earlier:
                earliest = recast or segments
                earliest["intelligent_cloud_revenue"][0] = earliest["productivity_revenue"][0] + 1
            return tree
        self.assert_claims_follow("IC first ahead of PBP", ic_first(False), ic_first(True),
                                  ["本季首次超过 Productivity", "收入首次超过 Productivity", "首次成为最大分部"])

        # 「N 季连降后首次回升」: a run of falls over the whole segment record and
        # a rise, against the same run broken one quarter in.
        def ic_margins(margins: list[float]) -> dict:
            tree = copy.deepcopy(source)
            segments = tree["segments_usd_m"]
            segments["intelligent_cloud_cost_of_revenue"] = [
                revenue * (1 - margin / 100) for revenue, margin in zip(segments["intelligent_cloud_revenue"], margins)]
            return tree
        width = len(source["segments_usd_m"]["periods"])
        run = [60.0 - i for i in range(width - 1)] + [60.0 - (width - 2) + 0.5]
        broken = [run[0], run[0] + 1] + run[2:]
        self.assert_claims_follow("the run of falls", ic_margins(run), ic_margins(broken),
                                  [f"连降{cn_count(width - 2)}季后首次回升", f"分部毛利率{cn_count(width - 2)}季来首次回升"])
        self.assertIn(f"连降{cn_count(width - 3)}季后首次回升", published_text(build_payload(ic_margins(broken))))

        # The returns headline in the brief: three bands of the same ratio.
        def coverage(share: float) -> dict:
            tree = copy.deepcopy(source)
            fy = tree["fiscal_year_usd_m"]
            unpaid = [fy["unpaid_capex_in_payables_prior"]] + fy["unpaid_capex_in_payables"]
            adjusted = (fy["operating_cash_flow"][-1] - fy["cash_paid_for_property_and_equipment"][-1]
                        - (unpaid[-1] - unpaid[-2]))
            fy["dividends_paid"][-1] = round(adjusted * 0.1)
            fy["share_repurchase_program"][-1] = round(adjusted * share) - fy["dividends_paid"][-1]
            return tree
        self.assert_claims_follow("returns close to free cash flow", coverage(0.9), coverage(1.1),
                                  ["回报逼近真实自由现金流"])
        self.assert_claims_follow("returns over free cash flow", coverage(1.1), coverage(0.5),
                                  ["回报已超过真实自由现金流"])
        self.assert_claims_follow("returns well under free cash flow", coverage(0.5), coverage(0.9),
                                  ["回报占真实自由现金流的 50%"])

        # 「No precedent」: the latest capital intensity is the top of the record.
        top = copy.deepcopy(source)
        top["long_history"]["capital_expenditures_usd_m"][-1] = top["long_history"]["revenue_usd_m"][-1] * 0.9
        earlier_peak = copy.deepcopy(top)
        long = earlier_peak["long_history"]
        long["capital_expenditures_usd_m"][5] = long["revenue_usd_m"][5] * 2
        self.assert_claims_follow("capex intensity at its peak", top, earlier_peak,
                                  ["拉长看才知道当前这一档没有先例"])

        # 「The fiscal year before made a loss」: the four quarters of the fiscal
        # year before the latest one, named from the fiscal-year labels.
        def last_year_other_income(value: float) -> dict:
            tree = copy.deepcopy(source)
            year = int(tree["fiscal_year_usd_m"]["labels"][-1][2:]) - 1
            long = tree["long_history"]
            for quarter in (f"{year - 1}Q3", f"{year - 1}Q4", f"{year}Q1", f"{year}Q2"):
                long["other_income_expense_net_usd_m"][long["quarters"].index(quarter)] = value
            return tree
        self.assert_claims_follow("other income lost money the year before", last_year_other_income(-1000.0),
                                  last_year_other_income(1000.0), ["上一财年产生的是净损失"])

        # A compound condition: both legs on the trigger side, or one short of it,
        # on two lines set here around the current readings.
        def legs(second_triggered: bool, block: str) -> dict:
            tree = copy.deepcopy(source)
            azure_now, opex_now = tree["azure_growth_cc_pct"][-1], expected_reading(tree, "opex_yoy")
            base = {"row": 1, "tier": "减仓", "basis": "演练", "group": "drill", "unit": "pct"}
            tree[block]["quantified"] = [
                {**base, "id": "leg_a", "reads": "azure_cc", "metric": "Azure 固定汇率增速", "label": "演练腿甲",
                 "direction": "up", "threshold": azure_now + 1},
                {**base, "id": "leg_b", "reads": "opex_yoy", "metric": "经营费用同比", "label": "演练腿乙",
                 "direction": "down", "threshold": opex_now + (-1 if second_triggered else 1)}]
            tree[block]["unscored"] = []
            return tree
        self.assert_claims_follow("both legs on the trigger side", legs(True, "next_kpi"), legs(False, "next_kpi"),
                                  ["当前两腿都已在触发一侧"])
        self.assertIn("「演练腿乙」未到", published_text(build_payload(legs(False, "next_kpi"))))
        self.assert_claims_follow("both legs set off", legs(True, "prior_kpi_settlement"),
                                  legs(False, "prior_kpi_settlement"), ["本季两腿同时成立，触发"])
        self.assertIn("本季没有同时成立，未触发",
                      published_text(build_payload(legs(False, "prior_kpi_settlement"))))

    def test_the_counted_sentences_follow_the_record(self) -> None:
        """「N 次环比里 M 次下降」 is counted off the short window's gross margin;
        when every change in it is a fall the sentence says so instead."""
        def check(source: dict) -> int:
            long = source["long_history"]
            margins = [profit / revenue * 100 for profit, revenue
                       in zip(long["gross_profit_usd_m"], long["revenue_usd_m"])][-WINDOW:]
            falls = sum(1 for a, b in zip(margins, margins[1:]) if b < a)
            text = published_text(build_payload(source))
            if falls < len(margins) - 1:
                self.assertIn(f"{cn_count(len(margins) - 1)}次环比里{cn_count(falls)}次下降", text)
                self.assertNotIn("单向下滑", text)
            else:
                self.assertIn(f"{cn_count(len(margins))}季的窗口会把这段读成单向下滑", text)
                self.assertNotIn("次环比里", text)
            return falls

        check(self.source)
        falling = copy.deepcopy(self.source)
        long = falling["long_history"]
        count = len(long["quarters"])
        for step, at in enumerate(range(count - WINDOW, count)):
            long["gross_profit_usd_m"][at] = long["revenue_usd_m"][at] * (0.70 - 0.01 * step)
        self.assertEqual(check(falling), WINDOW - 1)

if __name__ == "__main__":
    unittest.main()
