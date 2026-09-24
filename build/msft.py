#!/usr/bin/env python3
"""Build the MSFT quarterly-results page.

Same four-part, chart-led shape as the other company pages (上季兑现 → 本季重点
→ 下季跟踪 → 长期常规).  Everything on this page is labelled by calendar
quarter, not by Microsoft's fiscal quarter: the site compares four companies
side by side, and a page whose "Q2 2026" means a different three months from
every neighbouring page is worse than no comparison at all.  The series' own
`latest` block says which fiscal quarter the calendar quarter is.

The routine series are the ones that decide this company right now.  The
operating story (Azure, the Intelligent Cloud segment gross margin) and the
cash story (reported free cash flow against free cash flow adjusted for capex
still sitting in accounts payable, and what the shareholder returns take out of
it) can point in opposite directions, so the page carries both rather than
netting them into one number.

Published numbers are company-reported or transparent arithmetic.  Market
expectations are labelled as such, with no broker attribution.

Rolling the page to a new quarter edits `series/msft.json` and nothing else.
Every figure, period label, count and record claim is computed from the series
here; "the first time", "N quarters in a row", "has no precedent" are printed
only while the series makes them true.  What belongs to one quarter -- the
settlement of last quarter's thresholds and questions, the new thresholds, the
market's expectation, the call's outlook and its remarks -- lives in blocks
stamped with that quarter and is read through `board.stamped_block`.  The
fiscal-year block is annual: it moves when a 10-K lands, and the page names its
years from the block's own labels.

Shareholder returns are the company's own measure: repurchases under the
buyback programme plus dividends.  The cash-flow statement's repurchase line
also carries shares bought back to settle employees' tax withholding, which is
the settlement of stock compensation rather than a return of capital; counting
it made the returns look larger than the free cash flow that paid for them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import (  # noqa: E402
    ai_capex_cycle_table,
    cn_count,
    fill_story,
    headroom,
    headroom_exhibit,
    latest_block,
    number_exhibits,
    stamped_block,
    unit_text,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "msft.json"
DATA_DIR = ROOT / "data"

WINDOW = 8

AUDIT_WORDS = {"unaudited": "未审计", "audited": "已审计"}

# The year the page splits the capital-intensity record at ("2016–2019 it sat
# in a band"): the last year before the cloud build-out steepened. History.
QUIET_YEARS_END = "2019Q4"


def compact_period(period: str) -> str:
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


def quarter_label(quarter: str) -> str:
    """``'2016Q1'`` → ``'Q1'16'``, matching `compact_period`'s output."""
    year, number = quarter.split("Q")
    return f"Q{number}'{year[-2:]}"


def quarter_key(period: str) -> str:
    quarter, year = period.split()
    return f"{year}{quarter}"


def leading_gap(values: list[float | None]) -> int:
    """Index of the first reported value; ``len(values)`` when there is none."""
    return next((i for i, value in enumerate(values) if value is not None), len(values))


# One x label per year: forty-two quarterly labels at 90 degrees turn the axis
# into a hairbrush, and this axis is only ever navigated by year.
LONG_STEP = 4


def shown(values: list) -> list:
    return values[-WINDOW:]


def yoy(values: list[float]) -> list[float | None]:
    return [None] * 4 + [
        (values[index] / values[index - 4] - 1) * 100 for index in range(4, len(values))
    ]


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    q = staging["quarterly_usd_m"]
    fcf = q["operating_cash_flow"][-1] - q["cash_paid_for_property_and_equipment"][-1]
    return [f"Revenue ${q['revenue_total'][-1] / 1000:.1f}B",
            f"Azure {staging['azure_growth_cc_pct'][-1]:+.0f}%",
            f"FCF {'-' if fcf < 0 else ''}${abs(fcf) / 1000:.1f}B"]


def falling_streak(values: list[float], end: int) -> int:
    """How many consecutive declines end at index ``end``."""
    streak = 0
    for index in range(end, 0, -1):
        if values[index] < values[index - 1]:
            streak += 1
        else:
            break
    return streak


def fiscal_label(period: str) -> str:
    """``'Q2 2026'`` → ``'FY2026 Q4'``: Microsoft's fiscal year ends in June, so a
    calendar third quarter opens the next fiscal year."""
    quarter, year = period.split()
    number, year = int(quarter[1]), int(year)
    return f"FY{year + 1} Q{number - 2}" if number >= 3 else f"FY{year} Q{number + 2}"


def calendar_period(label: str) -> str:
    """``"Q2'26"`` → ``'Q2 2026'``: the inverse of `compact_period` (and of
    `quarter_label`, which prints the same form)."""
    quarter, year = label.split("'")
    return f"{quarter} 20{year}"


def shift_period(period: str, step: int) -> str:
    """``'Q2 2026'`` moved ``step`` calendar quarters."""
    quarter, year = period.split()
    index = int(year) * 4 + int(quarter[1]) - 1 + step
    return f"Q{index % 4 + 1} {index // 4}"


def period_order(period: str) -> int:
    quarter, year = period.split()
    return int(year) * 4 + int(quarter[1])


def value_text(unit: str, value: float) -> str:
    """A threshold or a reading the way this page prints it: whole numbers without
    a trailing ``.0``, money with its sign outside the currency symbol."""
    whole = float(value).is_integer()
    sign = "−" if value < 0 else ""
    if unit == "pct":
        return f"{value:.0f}%" if whole else f"{value:.1f}%"
    if unit == "pp":
        return "0pp" if value == 0 else (f"{value:+.0f}pp" if whole else f"{value:+.2f}pp")
    if unit == "usd_m":
        return f"{sign}${abs(value):,.0f}M"
    if unit == "usd_bn":
        return f"{sign}${abs(value):,.0f}B" if whole else f"{sign}${abs(value):,.1f}B"
    if unit == "million":
        return f"{value:.0f}M" if whole else f"{value:.1f}M"
    return unit_text(unit, value)


# ── Threshold readings ──────────────────────────────────────────────────────
# A threshold entry in `prior_kpi_settlement` or `next_kpi` names the record it
# is read against (`reads`), never the reading itself: the value is taken off
# the end of that record at build time, so a roll cannot leave last quarter's
# number under this quarter's line. `next_kpi` moves into
# `prior_kpi_settlement` as it stands at the next roll, so one reader serves
# both sections, and an entry naming a record this builder does not know stops
# the build instead of silently dropping its chart.

# A quarterly record gets its own line chart once it holds a year of readings;
# a shorter one, or a once-a-year figure, is settled in the overview only, and
# the overview says why -- with the count and the first quarter read off the
# record, so a roll that lengthens it cannot leave the reason behind.
DRAWABLE = 4


def reading_history(staging: dict, reads: str) -> tuple[list[str], list[float | None], dict]:
    """(x labels, values, spec) of the record a threshold entry reads.

    ``spec`` carries how to draw and word it: ``fmt`` / ``ylab`` / ``name`` for
    the chart, ``per`` for counting readings in prose, ``now`` for naming the
    latest one, ``source`` for the source line, and ``chart`` with ``why``: a
    once-a-year figure is never drawn, a quarterly one is drawn once it has
    `DRAWABLE` readings; either way an undrawn entry is settled in the overview
    only, and the overview says why (``short`` starts that sentence for a
    quarterly record, the count and the first quarter are added here).
    """
    long = staging["long_history"]
    quarters = long["quarters"]
    long_labels = [quarter_label(quarter) for quarter in quarters]
    kpi = staging["operating_kpi"]
    segments = staging["segments_usd_m"]

    def from_first(labels: list[str], values: list[float | None]):
        start = leading_gap(values)
        return labels[start:], values[start:]

    def year_on_year(values: list[float | None]) -> list[float | None]:
        return [None if index < 4 or values[index] is None or values[index - 4] is None
                else (values[index] / values[index - 4] - 1) * 100 for index in range(len(values))]

    def kpi_series(key: str, field: str):
        block = kpi[key]
        return [compact_period(p) for p in block["periods"]], block[field]

    def unanswered_calls(key: str, field: str) -> str:
        # The calls that did not give a figure the others did, named off the
        # record's own blanks.
        block = kpi[key]
        gaps = [fiscal_label(p) for p, value in zip(block["periods"], block[field]) if value is None]
        return ("、".join(gaps) + f" 电话会没有给这个数，{'那一格' if len(gaps) == 1 else '那几格'}留空。"
                if gaps else "")

    def fiscal_margin_change():
        # Operating margin per complete fiscal year (July-June) off the long
        # record; the first fiscal year has no year before it to change from.
        years: dict[int, list[tuple[float, float]]] = {}
        for quarter, revenue, income in zip(quarters, long["revenue_usd_m"], long["operating_income_usd_m"]):
            year, number = int(quarter[:4]), int(quarter[-1])
            years.setdefault(year + 1 if number >= 3 else year, []).append((revenue, income))
        margins = [(fy, sum(i for _, i in rows) / sum(r for r, _ in rows) * 100)
                   for fy, rows in sorted(years.items()) if len(rows) == 4]
        return ([f"FY{fy}" for fy, _ in margins[1:]],
                [now - before for (_, before), (_, now) in zip(margins, margins[1:])])

    def year_on_year_change(values: list[float | None]) -> list[float | None]:
        return [None if index < 4 or values[index] is None or values[index - 4] is None
                else values[index] - values[index - 4] for index in range(len(values))]

    def adjusted_quarters() -> list[float | None]:
        # Free cash flow less the quarter's increase in capex still unpaid in
        # accounts payable; only where both quarter-ends are disclosed.
        unpaid = long["unpaid_capex_in_payables_usd_bn"]
        return [None if index == 0 or unpaid[index] is None or unpaid[index - 1] is None
                else operating - spend - (unpaid[index] - unpaid[index - 1]) * 1000
                for index, (operating, spend) in enumerate(
                    zip(long["operating_cash_flow_usd_m"], long["capital_expenditures_usd_m"]))]

    def adjusted_years():
        fy = staging["fiscal_year_usd_m"]
        unpaid = [fy["unpaid_capex_in_payables_prior"]] + fy["unpaid_capex_in_payables"]
        return fy["labels"], [operating - spend - (unpaid[index + 1] - unpaid[index])
                              for index, (operating, spend) in enumerate(
                                  zip(fy["operating_cash_flow"], fy["cash_paid_for_property_and_equipment"]))]

    def seats_growth():
        block = kpi["copilot_paid_seats_m"]
        return ([compact_period(p) for p in block["periods"]][1:],
                [(now / before - 1) * 100 for before, now in zip(block["values"], block["values"][1:])])

    azure_annual = staging["azure_growth_provenance"]["annual_crosscheck_pct"]
    call = "逐季读自各季电话会 CFO 陈述（官方逐字稿），不在申报文件里；"
    histories = {
        "azure_cc": lambda: ([compact_period(p) for p in segments["periods"]], staging["azure_growth_cc_pct"], {
            "fmt": "pct0", "ylab": "同比（固定汇率）", "name": "Azure 增速（固定汇率）",
            "source": ("Azure 增速逐季读自各季业绩新闻稿（8-K EX-99.1）与电话会；公司只公布 Azure 的增速、不公布它的收入，"
                       "年度对照为 10-K 原句 " + "、".join(f"{year} +{value}%" for year, value in azure_annual.items())
                       + "（报告口径）。")}),
        "cloud_gm": lambda: (*kpi_series("microsoft_cloud", "gross_margin_pct"), {
            "fmt": "pct0", "ylab": "毛利率", "name": "Microsoft Cloud 毛利率",
            "source": "Microsoft Cloud 毛利率" + call + "公司只印到整数。"}),
        "fy_om_change": lambda: (*fiscal_margin_change(), {
            "fmt": "pp1", "ylab": "pp", "name": "财年营业利润率同比", "per": "个财年",
            "why": "一个财年只有一个读数，不画季度线",
            "source": "营业利润率按各财年利润表自算（D）。"}),
        "rpo_yoy": lambda: (*from_first(long_labels, year_on_year(long["commercial_rpo_usd_bn"])), {
            "fmt": "pct0", "ylab": "同比", "name": "商业 RPO 同比 D",
            "source": ("商业剩余履约义务余额逐季读自 10-Q / 10-K 的收入附注（2019-09-30 起才拆出商业部分），"
                       "同比为自算（D）。")}),
        "rpo12_yoy": lambda: (*kpi_series("commercial_rpo", "twelve_month_portion_yoy_pct"), {
            "fmt": "pct0", "ylab": "同比", "name": "12 个月内确认部分同比",
            "source": ("12 个月内确认的商业 RPO 同比" + call
                       + unanswered_calls("commercial_rpo", "twelve_month_portion_yoy_pct"))}),
        "bookings_ex_largest": lambda: (*kpi_series("bookings_ex_largest_customer_yoy_pct", "values"), {
            "fmt": "pct0", "ylab": "同比", "name": "商业签约额同比（剔除单一大客户）",
            "short": "公司自 {first}起才给出剔除单一大客户的签约额增速，更早的签约额增速都含该客户的合约",
            "source": "签约额增速" + call}),
        "copilot_seats": lambda: (*kpi_series("copilot_paid_seats_m", "values"), {
            "fmt": "f0", "ylab": "百万席位", "name": "M365 Copilot 付费席位",
            "short": "公司自 {first}起才披露付费席位数",
            "source": "付费席位读自各季新闻稿与电话会。"}),
        "capex_company": lambda: (*kpi_series("capex_incl_finance_leases_usd_bn", "values"), {
            "fmt": "usd1", "ylab": "US$B", "name": "资本开支（公司口径，含融资租赁）",
            "context": [{
                "name": "现金支付的物业及设备（申报）",
                "values": [value / 1000 for value in long["capital_expenditures_usd_m"][
                    -len(kpi["capex_incl_finance_leases_usd_bn"]["values"]):]],
                "color": "GRAY"}],
            "source": ("公司口径资本开支" + call + "灰线为现金流量表的现金资本开支（10-Q / 10-K），"
                       "两者差在融资租赁与付现时点。")}),
        "fcf_quarter": lambda: (long_labels, [
            operating - spend for operating, spend
            in zip(long["operating_cash_flow_usd_m"], long["capital_expenditures_usd_m"])], {
            "fmt": "f0c", "ylab": "$M", "name": "自由现金流（报告口径）D",
            "source": ("自由现金流 = 经营现金流 − 现金支付的物业及设备，逐季由各期现金流量表的年初至今值相减（D）。")}),
        "opex_yoy": lambda: (long_labels, year_on_year(long["operating_expenses_usd_m"]), {
            "fmt": "pct1", "ylab": "同比", "name": "经营费用同比 D",
            "source": "经营费用 = 毛利 − 营业利润，两条腿都是申报值；同比为自算（D）。"}),
        "adj_fcf_quarter": lambda: (long_labels, adjusted_quarters(), {
            "fmt": "f0c", "ylab": "$M", "name": "调整后自由现金流 D",
            "context": [{"name": "自由现金流（报告口径）D", "color": "GRAY", "values": [
                operating - spend for operating, spend
                in zip(long["operating_cash_flow_usd_m"], long["capital_expenditures_usd_m"])]}],
            "source": ("调整后自由现金流 = 经营现金流 − 现金支付的物业及设备 − 当季「仍计入应付账款的物业及设备采购」的增量"
                       "（D）；该余额的季末值自 FY2026 Q1 的 10-Q 起才披露，所以调整后口径只有这几季，灰线是报告口径的完整记录。")}),
        "adj_fcf_fy": lambda: (*adjusted_years(), {
            "fmt": "f0c", "ylab": "$M", "name": "财年调整后自由现金流 D", "per": "个财年",
            "why": "一个财年只有一个读数，全年要到该财年的 10-K 才结算",
            "source": "财年口径同上，年末未付资本开支读自 10-K 物业及设备附注。"}),
        "buyback_quarter": lambda: (long_labels, long["stock_repurchases_usd_m"], {
            "fmt": "f0c", "ylab": "$M", "name": "单季回购（现金流量表）",
            "source": ("回购为现金流量表「Common stock repurchased」逐季值（含为员工代扣税回购的股份），财政第四季为全年减前三季；"
                       "报告的 $4.579B 也是这一行。")}),
        "depr_annualized": lambda: (*from_first(long_labels, [
            None if value is None else value * 4 for value in long["depreciation_usd_m"]]), {
            "fmt": "f0c", "ylab": "$M", "name": "年化折旧（单季 × 4）D",
            "source": ("季度折旧读自各期 10-Q / 10-K 物业及设备附注（公司印到 $0.1B，2024Q3 起才有季度值），年化为乘 4（D）。")}),
        "leases_nc_yoy": lambda: (*from_first(long_labels, year_on_year_change(long["leases_not_commenced_usd_bn"])), {
            "fmt": "usd1", "ylab": "US$B", "name": "未起租租约余额一年增加 D",
            "source": ("已签约未起租租约余额逐季读自 10-Q / 10-K 租赁附注（2017-09-30 起才有），年增量为季末余额减一年前余额（D）。")}),
        "seats_qoq": lambda: (*seats_growth(), {
            "fmt": "pct0", "ylab": "环比", "name": "Copilot 付费席位环比 D",
            "short": "付费席位披露得晚，环比自 {first}起才有",
            "source": "付费席位读自各季新闻稿与电话会（「over 20 million」「over 30 million」），环比为自算（D）。"}),
        "m365_cc_adjusted": lambda: (*kpi_series("m365_commercial_cloud", "adjusted_pct"), {
            "fmt": "pct0", "ylab": "同比", "name": "M365 商业云增速（调整后）",
            "short": "公司按「剔除上年同期一次性确认」调整的增速自 {first}起才给",
            "source": "M365 商业云增速读自本季业绩新闻稿（8-K EX-99.1）。"}),
        "oie_ex_interest": lambda: (long_labels, [
            total - income - expense for total, income, expense in zip(
                long["other_income_expense_net_usd_m"], long["interest_and_dividends_income_usd_m"],
                long["interest_expense_usd_m"])], {
            "fmt": "f0c", "ylab": "$M", "name": "其他收入（剔除利息）D",
            "source": ("其他收入（净）减去附注里的利息与股息收入、利息费用两行（D）；两行逐季读自各期 10-Q / 10-K 附注"
                       "「Other income (expense), net」，财政第四季为全年减九个月。")}),
    }
    if reads not in histories:
        raise ValueError(f"a threshold entry reads {reads!r}, which build/msft.py does not know")
    labels, values, spec = histories[reads]()
    spec = {"per": "季", "now": "本季", **spec}
    if spec["per"] != "季":
        spec.update(now=labels[-1], chart=False)
        return labels, values, spec
    read = [label for label, value in zip(labels, values) if value is not None]
    spec["chart"] = len(read) >= DRAWABLE
    if not spec["chart"]:
        first = calendar_period(read[0])
        spec["why"] = (fill_story(spec.get("short", "这条序列太短"), {"first": f"{first}（{fiscal_label(first)}）"})
                       + f"，本文件只有{cn_count(len(read))}个读数")
    return labels, values, spec


# The analysis writes two kinds of line: one the metric is meant to reach
# (期望 / 加仓 / 确认) and one it must not cross (红旗 / 警示 / 减仓 / 重新评估 /
# 撤销). "Reached" and "set off" are the words the analysis itself uses.
TARGET_TIERS = ("期望", "加仓", "确认")
TIER_COLOURS = {"期望": "GOLD", "加仓": "GREEN", "确认": "GREEN"}


def is_target(entry: dict) -> bool:
    return entry["tier"] in TARGET_TIERS


def favourable(entry: dict, value: float) -> bool:
    """Is ``value`` on the favourable side of the entry's line?  A value on the
    line counts as favourable unless the analysis wrote the comparison the other
    way round (``boundary: unsafe`` -- 「>$40B」, 「flat or down」)."""
    if value == entry["threshold"]:
        return entry.get("boundary", "safe") == "safe"
    return (value > entry["threshold"]) == (entry["direction"] == "up")


def event_met(entry: dict, values: list[float | None]) -> bool:
    """Did the line's event happen -- a target reached, an alarm set off -- over as
    many consecutive readings as the analysis asked for."""
    readings = [value for value in values if value is not None]
    need = entry.get("consecutive", 1)
    last = readings[-need:]
    if len(last) < need:
        return False
    if is_target(entry):
        return all(favourable(entry, value) for value in last)
    return all(not favourable(entry, value) for value in last)


def verdict(entry: dict, values: list[float | None]) -> str:
    met = event_met(entry, values)
    if is_target(entry):
        return "达到" if met else "未达到"
    return "触发" if met else "未触发"


def is_due(entry: dict, period: str) -> bool:
    """A dated line (``settles``) is settled only once its quarter has come."""
    return "settles" not in entry or period_order(entry["settles"]) <= period_order(period)


def tier_chart(word: str, entries: list[dict], xlabels: list[str], values: list[float | None],
               spec: dict, notes: dict[str, str], section: str) -> dict:
    """One record with every line the analysis drew on it.

    ``word`` is 「上季」 in section one (last quarter's lines, settled against
    this quarter's reading) and 「下季」 in section three (this quarter's lines,
    against the current reading). ``notes`` supplies the filled-in
    ``reading_note`` of each entry, by id; ``section`` names the part of the
    analysis the lines come from, as the series block records it.
    """
    unit = entries[0]["unit"]
    readings = [(label, value) for label, value in zip(xlabels, values) if value is not None]
    now = readings[-1][1]
    previous = readings[-2] if len(readings) > 1 else None
    metric = entries[0]["metric"]

    def line_words(entry: dict) -> str:
        need = entry.get("consecutive", 1)
        return (f"{entry['tier']}线 {value_text(unit, entry['threshold'])}"
                + (f"（要连续{cn_count(need)}{spec['per']}）" if need > 1 else ""))

    # Two lines at the same level (a warning and one leg of a compound
    # condition, say) are one line on the chart, named for both.
    levels: dict[float, list[dict]] = {}
    for entry in entries:
        levels.setdefault(entry["threshold"], []).append(entry)
    if word == "上季":
        title = (f"{metric} {value_text(unit, now)}："
                 + "，".join(f"{verdict(entry, values)}上季{line_words(entry)}" for entry in entries))
    else:
        title = (f"{metric}：下季阈值 "
                 + " / ".join(f"{value_text(unit, level)}（{'、'.join(e['tier'] for e in same)}）"
                              for level, same in levels.items())
                 + f"，当前 {value_text(unit, now)}")
    rows = {}
    for entry in entries:
        rows.setdefault(entry["row"], entry["basis"])
    analysis = "上季分析" if word == "上季" else "本季分析"

    def row_words(row) -> str:
        # A revocation condition is named, not numbered, in the analysis.
        return (f"{analysis}立场撤销条件{row[2:]}原文" if isinstance(row, str)
                else f"{analysis}{section.split('「')[0]}第 {row} 行原文")

    counts = []
    for level, same in levels.items():
        entry = same[0]
        if entry.get("no_history_count"):
            continue
        against = sum(1 for _, value in readings if not favourable(entry, value))
        counts.append(f"{'、'.join(e['tier'] for e in same)}线 {value_text(unit, level)}："
                      f"{cn_count(len(readings))}{spec['per']}里"
                      + (f"没有一{spec['per']}落在不利一侧" if against == 0 else
                         f"有{cn_count(against)}{spec['per']}落在不利一侧"))
    guided = [entry for entry in entries if entry.get("company_guide")]
    series = ([{"name": spec["name"], "values": values, "color": "NAVY"}]
              + spec.get("context", [])
              + [{"name": f"{word}{'、'.join(e['tier'] for e in same)}线 {value_text(unit, level)}",
                  "values": [level] * len(xlabels),
                  "color": TIER_COLOURS.get(same[0]["tier"], "RED")} for level, same in levels.items()])
    chart = {
        "kind": "lines",
        "title": title,
        "xlabels": xlabels,
        "series": series,
        "fmt": spec["fmt"],
        "yfmt": spec["fmt"],
        "label_fmt": spec["fmt"],
        "end_label": True,
        "ylab": spec["ylab"],
        "note": (
            "；".join(f"{row_words(row)}：{basis}" for row, basis in rows.items()) + "。"
            + f"{spec['now']} {value_text(unit, now)}"
            + (f"（{previous[0]} 为 {value_text(unit, previous[1])}）" if previous else "")
            + "。" + ("；".join(counts) + "。" if counts else "")
            + "".join(notes.get(entry["id"], "") for entry in entries)
        ),
        "src_extra": (
            spec["source"]
            + (f"其中{cn_count(len(guided))}条阈值就是公司自己的指引。" if guided else "")
            + f"阈值取自{analysis}{section}。"
        ),
    }
    if len(xlabels) > 16:
        chart["xstep"] = LONG_STEP
    return chart


def headroom_words(entry: dict, value: float) -> str:
    return "—（阈值为 0）" if entry["threshold"] == 0 else \
        f"{headroom(entry['direction'], entry['threshold'], value):+.1f}%"


def settlement_exhibits(staging: dict, block: dict, word: str,
                        period: str) -> tuple[dict, list[dict], list[list[str]]]:
    """A threshold block drawn as an overview plus one chart per record.

    The same code draws last quarter's lines in section one (``word`` 「上季」,
    judged against this quarter's reading) and this quarter's in section three
    (「下季」, against the current reading): at the next roll `next_kpi` moves
    into `prior_kpi_settlement` as it stands, and this is what reads it.
    Returns the overview, the line charts and the audit-table rows.
    """
    read = []
    for entry in block["quantified"]:
        xlabels, values, spec = reading_history(staging, entry["reads"])
        readings = [value for value in values if value is not None]
        read.append(({**entry, "reading": readings[-1]}, xlabels, values, spec))
    long = staging["long_history"]
    fills = {"cash_capex": value_text("usd_bn", long["capital_expenditures_usd_m"][-1] / 1000)}
    notes = {entry["id"]: fill_story(entry["reading_note"], fills)
             for entry, *_ in read if entry.get("reading_note")}
    settling = word == "上季"
    shown = [item for item in read if not settling or is_due(item[0], period)]
    later = [item[0] for item in read if settling and not is_due(item[0], period)]

    bars = [(entry, values) for entry, _, values, _ in shown if entry["threshold"] != 0]
    zero = [(entry, values, spec) for entry, _, values, spec in shown if entry["threshold"] == 0]

    def bar_label(entry: dict) -> str:
        return entry["label"] + (f"（{entry['settles']} 结算）" if "settles" in entry and not settling else "")

    if settling:
        targets = [entry for entry, _ in bars if is_target(entry)]
        reached = [entry for entry, values in bars if is_target(entry) and event_met(entry, values)]
        alarms = [entry for entry, _ in bars if not is_target(entry)]
        set_off = [entry for entry, values in bars if not is_target(entry) and event_met(entry, values)]
        parts = []
        if targets:
            parts.append(f"{len(targets)} 条目标线" + ("全部达到" if len(reached) == len(targets) else
                                                     "一条都没有达到" if not reached else f"达到 {len(reached)} 条"))
        if alarms:
            parts.append(f"{len(alarms)} 条警戒线" + ("都没有触发" if not set_off else
                                                    "全部触发" if len(set_off) == len(alarms) else
                                                    f"触发 {len(set_off)} 条"))
        title = f"上季 {len(bars)} 条量化阈值：" + "，".join(parts)
        # A line the analysis wrote as an event (「不再披露」) has no bar, but
        # when it went off the title must not read as if nothing did.
        set_off_events = [item["set_off"] for item in block.get("unscored", []) if item.get("set_off")]
        if set_off_events:
            title += (f"；另有{cn_count(len(set_off_events))}条不能量化的警戒已触发："
                      + "、".join(f"「{event}」" for event in set_off_events))
    else:
        good = sum(1 for entry, _ in bars if favourable(entry, entry["reading"]))
        title = (f"下季 {len(bars)} 条量化阈值：" + ("当前全部在有利一侧" if good == len(bars) else
                                                f"当前 {good} 条在有利一侧、{len(bars) - good} 条在不利一侧"))

    groups: dict[str, list[dict]] = {}
    for entry, *_ in shown:
        if entry.get("group"):
            groups.setdefault(entry["group"], []).append(entry)
    note = ("正值 = 读数落在这条线的有利一侧（警戒线未触发、目标线已达到），负值 = 不利一侧。"
            + ("" if settling else "当前值是本季的读数，这些线结算的是下一季（标了结算季的除外）。"))
    for entry, values, spec in zero:
        note += (f"「{entry['label']}」的阈值是 0，没有百分比余量，不进柱图：{spec['now']} "
                 f"{value_text(entry['unit'], entry['reading'])}，"
                 + (verdict(entry, values) if settling else
                    ("在有利一侧" if favourable(entry, entry["reading"]) else "在不利一侧")) + "。")
    for entry, _ in bars:
        if entry["reading"] == entry["threshold"]:
            note += (f"「{entry['label']}」{'本季' if settling else '当前'}恰好压在线上"
                     f"（{value_text(entry['unit'], entry['reading'])}），柱长为零；按原文的比较符算"
                     + ("在有利一侧" if favourable(entry, entry["reading"]) else "在不利一侧") + "。")
    for key, legs in groups.items():
        both = all(not favourable(leg, leg["reading"]) for leg in legs)
        note += (f"「{'」与「'.join(leg['label'] for leg in legs)}」要同时成立才算{legs[0]['tier']}："
                 + (("本季两腿同时成立，触发" if both else "本季没有同时成立，未触发") if settling else
                    ("当前两腿都已在触发一侧" if both else
                     "当前" + "、".join(f"「{leg['label']}」" + ("在触发一侧" if not favourable(leg, leg["reading"])
                                                               else "未到") for leg in legs)))
                 + "。")
    undrawn = []
    seen = set()
    for entry, _, _, spec in shown:
        if not spec["chart"] and entry["reads"] not in seen:
            seen.add(entry["reads"])
            undrawn.append(f"{entry['metric']}没有单独的线图——{spec['why']}")
    if undrawn:
        note += "；".join(undrawn) + "。"
    if later:
        note += ("尚未到期、下季继续跟踪的：" + "；".join(f"{entry['label']}（{entry['settles']} 结算）"
                                                for entry in later) + "。")
    unscored = []
    for item in block.get("unscored", []):
        now = "—"
        if item.get("reads"):
            _, values, _ = reading_history(staging, item["reads"])
            reading = [value for value in values if value is not None][-1]
            unit = next((entry["unit"] for entry, *_ in read if entry["reads"] == item["reads"]),
                        item.get("unit", "pct"))
            now = value_text(unit, reading)
        unscored.append((item, now, fill_story(item["why"], {"now": now})))
    if unscored:
        analysis = "上季" if settling else "本季"

        def where(row) -> str:
            return f"立场撤销条件{row[2:]}" if isinstance(row, str) else f"第 {row} 行"

        note += (f"{analysis}{block['section'].split('「')[0]}另有{cn_count(len(unscored))}档不进柱图："
                 + "；".join(f"{where(item['row'])}「{item['text']}」——{why}" for item, _, why in unscored) + "。")
    if block.get("calibration"):
        note += block["calibration"]
    overview = headroom_exhibit(
        title,
        [{**entry, "metric": bar_label(entry)} for entry, _ in bars],
        "reading",
        note,
        src_extra=(f"阈值逐字取自{'上季' if settling else '本季'}本地分析{block['section']}；"
                   + "其中标「公司指引」的就是公司自己在电话会上给的指引，其余不是公司指引。"
                   + "读数为申报值、公司电话会原值或据其现算的自算值（D），逐条来源见各线图。"),
    )
    # A reading exactly on its line rounds to −0.0, which the renderer prints
    # with a minus sign; the bar is zero either way.
    overview["values"] = [0.0 if value == 0 else value for value in overview["values"]]

    by_reads: dict[str, list] = {}
    for item in shown:
        by_reads.setdefault(item[0]["reads"], []).append(item)
    lines = []
    for items in by_reads.values():
        _, xlabels, values, spec = items[0]
        if spec["chart"]:
            lines.append(tier_chart(word, [entry for entry, *_ in items], xlabels, values, spec, notes,
                                    block["section"]))

    rows = []
    for entry, _, values, spec in read:
        rows.append([
            entry["label"],
            "高于阈值为有利" if entry["direction"] == "up" else "低于阈值为有利",
            value_text(entry["unit"], entry["threshold"]),
            value_text(entry["unit"], entry["reading"]),
            headroom_words(entry, entry["reading"]),
            (verdict(entry, values) if is_due(entry, period) else f"{entry['settles']} 结算") if settling else
            ("有利一侧" if favourable(entry, entry["reading"]) else "不利一侧"),
        ])
    for item, now, why in unscored:
        rows.append([item["short"], "—", item["text"], now, "—", why])
    return overview, lines, rows


def closure_exhibit(closure: dict, source_line: str) -> dict:
    """The analysis's section 0 as one chart: every category it used, in order,
    each with the questions it holds, and the rule the chart counted by."""
    judged = [(label, count) for label, count in zip(closure["labels"], closure["counts"]) if count]
    for label, count in judged:
        if len(closure["topics"].get(label, [])) != count:
            raise ValueError(f"series block `followup_closure` counts {count} {label!r} "
                             f"but names {len(closure['topics'].get(label, []))}")

    def category_words(label: str, count: int) -> str:
        names = "".join(f"「{topic}」" for topic in closure["topics"][label])
        return f"{label}的是{names}" if count == 1 else f"{label}的{cn_count(count)}条是{names}"

    disclosures = closure.get("ai_run_rate_disclosures", [])
    story = bool(closure.get("falsified_story")) and len(disclosures) >= 2
    # The falsified call gets its own sentence below, so it is not listed twice.
    listed = [(label, count) for label, count in judged if not (story and label == "被证伪")]
    note = closure["rule"] + "：" + "；".join(category_words(label, count) for label, count in listed) + "。"
    if closure.get("verdicts_in_full"):
        note += ("其中" + "；".join(f"「{item['topic']}」的原文判定是「{item['words']}」"
                                   for item in closure["verdicts_in_full"]) + "。")
    if story:
        first, last = disclosures[-2], disclosures[-1]
        note += fill_story(closure["falsified_story"], {
            "gap": cn_count(period_order(last["period"]) - period_order(first["period"])),
            "latest": f"${last['usd_bn']:g}B",
            "first_period": first["period"],
            "first_fiscal": fiscal_label(first["period"]),
            "first": f"${first['usd_bn']:g}B",
        })
    return {
        "kind": "bars_labeled",
        # Every category the analysis used, in its order.
        "title": (f"上季 {sum(closure['counts'])} 条待验证问题："
                  + "、".join(f"{count} 条{label}" for label, count in judged)),
        "xlabels": closure["labels"],
        "values": closure["counts"],
        "legend": "问题条数",
        "fmt": "f0",
        "yfmt": "f0",
        "label_fmt": "f0",
        "ylab": "条",
        "note": note,
        "src_extra": source_line,
    }


def quarter_readings(staging: dict) -> dict[str, float]:
    """This quarter's figures a company guide is scored against, in US$M."""
    q = staging["quarterly_usd_m"]
    segments = staging["segments_usd_m"]
    return {
        "revenue": q["revenue_total"][-1],
        "pbp_revenue": segments["productivity_revenue"][-1],
        "ic_revenue": segments["intelligent_cloud_revenue"][-1],
        "mpc_revenue": segments["more_personal_computing_revenue"][-1],
        "cogs": q["revenue_total"][-1] - q["gross_profit"][-1],
        "opex": q["operating_expenses"][-1],
    }


def guidance_exhibit(staging: dict, block: dict, fiscal_year: str) -> dict:
    """Last quarter's call guide for this quarter against what was reported.

    Microsoft does not put its outlook in any filing; the CFO reads it on the
    call. The ranges are the call's, the actuals the filings'."""
    readings = quarter_readings(staging)
    rows = []
    for item in block["items"]:
        actual = readings[item["reads"]]
        middle = (item["low"] + item["high"]) / 2
        where = ("高于区间上端" if actual > item["high"] else
                 "低于区间下端" if actual < item["low"] else "落在区间内")
        rows.append((item, actual, (actual / middle - 1) * 100, where))
    parts = []
    for where in ("高于区间上端", "落在区间内", "低于区间下端"):
        names = [item["metric"] for item, _, _, place in rows if place == where]
        if names:
            parts.append("、".join(names) + where)
    return {
        "kind": "diverging_bars",
        "title": f"上季电话会给本季的 {len(rows)} 项指引：" + "，".join(parts),
        "xlabels": [item["metric"] for item, *_ in rows],
        "values": [round(deviation, 1) for _, _, deviation, _ in rows],
        "legend": "实际相对指引区间中值",
        "positive_label": "高于中值",
        "negative_label": "低于中值",
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "相对中值 %",
        "zero_line": True,
        "note": (
            "柱 = 实际相对指引区间中值的偏离；收入类为正是超出指引，成本类为正是花得比指引多。"
            + "；".join(f"{item['metric']}：指引 ${item['low']:,}–{item['high']:,}M，实际 ${actual:,.0f}M（{where}）"
                       for item, actual, _, where in rows)
            + "。" + block.get("one_offs", "")
        ),
        "src_extra": (f"指引是 {block['given_on']} 电话会上 CFO 给出的（官方逐字稿），不在任何申报文件里；"
                      f"实际值读自本季 8-K 新闻稿与 {fiscal_year} 10-K，销货成本为收入减毛利（D）。"),
    }


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    period = periods[-1]
    latest = latest_block(staging, period=period,
                          full_label=f'{period}（{staging["latest"]["fiscal_period"]}）')
    fiscal_period = staging["latest"]["fiscal_period"]
    fiscal_year = fiscal_period.split()[0]
    release_label = f"{fiscal_period} 业绩发布 8-K"
    if not any(item["label"] == release_label for item in staging["sources"]):
        raise ValueError(f"series `sources` has no {release_label!r}: add the quarter's release "
                         "with the roll")
    labels = [compact_period(p) for p in shown(periods)]
    q = staging["quarterly_usd_m"]
    segments = staging["segments_usd_m"]
    if segments["periods"][-1] != period:
        raise ValueError(f"segments end at {segments['periods'][-1]} but the page is {period}")
    # The segment block and the Azure series run on their own (recast) window;
    # their charts are labelled from it, not from the twelve-quarter base.
    seg_labels = [compact_period(p) for p in segments["periods"]]
    kpi = staging["operating_kpi"]
    fy = staging["fiscal_year_usd_m"]
    guidance = stamped_block(staging, "outlook", period)
    consensus = stamped_block(staging, "market_expectation", period)
    closure = stamped_block(staging, "followup_closure", period)
    prior_kpi = stamped_block(staging, "prior_kpi_settlement", period)
    next_kpi = stamped_block(staging, "next_kpi", period)
    guidance_given = stamped_block(staging, "guidance_delivery", period)
    if closure is not None and closure["set_in"] != shift_period(period, -1):
        raise ValueError(f"series block `followup_closure` closes questions set in {closure['set_in']!r}, "
                         f"but last quarter was {shift_period(period, -1)!r}")
    azure = staging["azure_growth_cc_pct"]

    revenue = q["revenue_total"]
    revenue_shown = shown(revenue)
    revenue_yoy = shown(yoy(revenue))

    capex = shown(q["cash_paid_for_property_and_equipment"])
    # Quarterly depreciation only exists from its first disclosed quarter; the
    # chart starts there rather than drawing empty slots.
    dep_from = leading_gap(shown(q["depreciation"]))
    depreciation = shown(q["depreciation"])[dep_from:]
    depreciation_ratio = [
        value / total * 100 for value, total in zip(depreciation, revenue_shown[dep_from:])
    ]
    other_income = shown(q["other_income_expense_net"])

    # ── The routine charts run on the ten-year record, not the eight ─────────
    # Eight quarters is barely one build cycle, which is the wrong window for
    # every question this section asks.  Everything below is a filed number or
    # the difference of two filed numbers; see long_history.provenance.
    long = staging["long_history"]
    quarters = long["quarters"]
    if quarters[-1] != quarter_key(period):
        raise ValueError(f"long_history ends at {quarters[-1]} but the page is {period}")
    years = len(quarters) // 4
    long_labels = [quarter_label(quarter) for quarter in quarters]
    long_revenue = long["revenue_usd_m"]
    long_capex = long["capital_expenditures_usd_m"]
    long_intensity = [
        spend / total * 100 for spend, total in zip(long_capex, long_revenue)
    ]
    long_gross_margin = [
        profit / total * 100
        for profit, total in zip(long["gross_profit_usd_m"], long_revenue)
    ]
    long_operating_margin = [
        income / total * 100
        for income, total in zip(long["operating_income_usd_m"], long_revenue)
    ]
    long_revenue_yoy = yoy(long_revenue)
    long_other_income = long["other_income_expense_net_usd_m"]
    # Finance leases start a couple of quarters into the window rather than at
    # 2016Q1, so the chart carries its own shorter axis instead of two blanks.
    long_leases = long["finance_lease_additions_usd_m"]
    lease_from = leading_gap(long_leases)

    # Intelligent Cloud is the only segment that publishes its own cost of
    # revenue every quarter, which makes its gross margin the one AI-mix series
    # on this page that needs no management-defined aggregate.
    ic_gross_margin = [
        (revenue_value - cost) / revenue_value * 100
        for revenue_value, cost in zip(
            segments["intelligent_cloud_revenue"], segments["intelligent_cloud_cost_of_revenue"]
        )
    ]
    ic_turned_up = ic_gross_margin[-1] > ic_gross_margin[-2]
    ic_falls = falling_streak(ic_gross_margin, len(ic_gross_margin) - 2) if ic_turned_up else 0

    # Reported free cash flow counts only capex that was actually paid. The
    # 10-K discloses how much sat unpaid in accounts payable at each year end,
    # so the adjusted line is the reported one less the year's increase in that
    # balance -- same inputs, no estimate.
    reported_fy_fcf = [
        operating - spend
        for operating, spend in zip(fy["operating_cash_flow"], fy["cash_paid_for_property_and_equipment"])
    ]
    unpaid_series = [fy["unpaid_capex_in_payables_prior"]] + fy["unpaid_capex_in_payables"]
    adjusted_fy_fcf = [
        reported - (unpaid_series[index + 1] - unpaid_series[index])
        for index, reported in enumerate(reported_fy_fcf)
    ]
    # Shareholder returns on the company's own measure: programme buybacks plus
    # dividends. The cash-flow repurchase line minus the programme is the tax
    # withholding on vested awards, which is not a return of capital.
    shareholder_returns = [
        repurchase + dividend
        for repurchase, dividend in zip(fy["share_repurchase_program"], fy["dividends_paid"])
    ]
    withholding = [cash - program for cash, program in
                   zip(fy["stock_repurchases"], fy["share_repurchase_program"])]
    return_coverage = [
        returns / adjusted * 100 for returns, adjusted in zip(shareholder_returns, adjusted_fy_fcf)
    ]
    # The same ratio with the cash-flow repurchase line, withholding included:
    # the basis the local analysis used, printed beside the company's own.
    cash_basis_coverage = ((fy["stock_repurchases"][-1] + fy["dividends_paid"][-1])
                           / adjusted_fy_fcf[-1] * 100)
    this_fy, last_fy = fy["labels"][-1], fy["labels"][-2]
    unpaid_increase = fy["unpaid_capex_in_payables"][-1] - fy["unpaid_capex_in_payables"][-2]

    guidance_revenue_mid = sum(guidance["revenue_usd_m"]) / 2 if guidance else None
    guidance_revenue_yoy = pct_change(guidance_revenue_mid, revenue[-4]) if guidance else None

    source = (
        'Source: <a href="https://www.microsoft.com/en-us/investor" rel="noopener">'
        f'Microsoft Investor Relations</a>（{fiscal_period} earnings release 与电话会；'
        '历史季度经 SEC EDGAR 的 10-Q / 10-K 回源）。'
    )

    def source_note(detail: str) -> str:
        return f"{detail}；历史期同口径。自算项目均可在核对表中复核。"

    # ── section one ──────────────────────────────────────────────────────────
    # What last quarter left, in the order it was left: the follow-up list the
    # analysis closed in its section 0, then the previous analysis's section-7
    # lines settled against this quarter's readings, then the company's own
    # guide for the quarter.
    settled_charts: list[dict] = []
    prior_overview = None
    prior_rows: list[list[str]] = []
    if closure is not None:
        settled_charts.append(closure_exhibit(
            closure,
            "问题清单来自上季本地分析稿的 Follow-up Questions，判定取自本季本地分析第 0 节；"
            f"判定依据本季新闻稿、电话会与 {fiscal_year} {'10-K' if fiscal_period.endswith('Q4') else '10-Q'}。"))
    if prior_kpi is not None:
        if prior_kpi["set_in"] != shift_period(period, -1):
            raise ValueError(f"series block `prior_kpi_settlement` settles lines set in {prior_kpi['set_in']!r}, "
                             f"but last quarter was {shift_period(period, -1)!r}")
        prior_overview, prior_lines, prior_rows = settlement_exhibits(staging, prior_kpi, "上季", period)
        settled_charts += [prior_overview] + prior_lines
    if guidance_given is not None:
        settled_charts.append(guidance_exhibit(staging, guidance_given, fiscal_year))

    # ── section two ──────────────────────────────────────────────────────────
    reported_yoy = [v for v in long_revenue_yoy if v is not None]
    upper_quartile = sorted(reported_yoy)[int(0.75 * len(reported_yoy))]
    ic, pbp, mpc = (segments["intelligent_cloud_revenue"], segments["productivity_revenue"],
                    segments["more_personal_computing_revenue"])
    # 「First」 is checked against every quarter on the current segment basis,
    # including the recast year before the eight-quarter window; the older
    # basis is a different set of segments and is named, not compared.
    recast = segments.get("recast_before_window") or {}
    ic_first_lead = ic[-1] > pbp[-1] and all(
        a <= b for a, b in zip(recast.get("intelligent_cloud_revenue", []) + ic[:-1],
                               recast.get("productivity_revenue", []) + pbp[:-1]))
    basis_quarters = len(recast.get("periods", [])) + len(ic)
    basis_from = (recast.get("periods") or segments["periods"])[0]
    old_basis = segments.get("pre_recast_crossover")
    ic_annual = segments.get("ic_annual_before_quarterly")
    segment_growth = [pct_change(line[-1], line[-5]) for line in (ic, pbp, mpc)]
    mpc_margin = [income / sales * 100 for income, sales in
                  zip(segments["more_personal_computing_operating_income"], mpc)]
    ic_cost_yoy = pct_change(segments["intelligent_cloud_cost_of_revenue"][-1],
                             segments["intelligent_cloud_cost_of_revenue"][-5])
    ic_revenue_yoy = pct_change(ic[-1], ic[-5])
    rpo = kpi["commercial_rpo"]
    # The balance is a filed number back to 2019Q3; the shares and the
    # twelve-month growth are the call's, on the eight quarters the file holds.
    rpo_from = leading_gap(long["commercial_rpo_usd_bn"])
    rpo_labels = long_labels[rpo_from:]
    rpo_levels = long["commercial_rpo_usd_bn"][rpo_from:]
    rpo_yoy = pct_change(rpo_levels[-1], rpo_levels[-5]) if len(rpo_levels) > 4 else None
    year_ago_label = shift_period(period, -4)
    shares = dict(zip(rpo["periods"], rpo["twelve_month_share_pct"]))
    share_now, share_before = shares.get(period), shares.get(year_ago_label)
    near_yoy = (rpo.get("twelve_month_portion_yoy_pct") or [None])[-1]
    ex_largest = (rpo.get("ex_largest_customer_yoy_pct") or [None])[-1]
    filing_years = segments["filings"]
    other_by_fy_start = quarters.index(f"{int(this_fy[2:]) - 1}Q3") if f"{int(this_fy[2:]) - 1}Q3" in quarters else None
    last_fy_other = (sum(long_other_income[other_by_fy_start - 4:other_by_fy_start])
                     if other_by_fy_start and other_by_fy_start >= 4 else None)
    quiet_end = quarters.index("2022Q4") + 1
    quiet = long_other_income[:quiet_end]
    recent = long_other_income[quiet_end:]

    # The fiscal year's other income by the 10-K's own lines: what moved the
    # year's pre-tax profit that operations did not.
    components = fy["other_income_components"]
    now_at, before_at = components["labels"].index(this_fy), components["labels"].index(last_fy)
    component_rows = [
        ("interest_and_dividends_income", "利息与股息收入"),
        ("interest_expense", "利息费用"),
        ("net_recognized_gains_on_investments", "投资净收益"),
        ("net_gains_on_derivatives", "衍生品净收益"),
        ("net_gains_on_foreign_currency_remeasurements", "汇兑净损益"),
        ("other_net", "其他（含权益法投资）"),
    ]
    other_total_now, other_total_before = components["total"][now_at], components["total"][before_at]
    pretax_now = fy["operating_income"][-1] + other_total_now
    pretax_before = fy["operating_income"][-2] + other_total_before
    other_swing = other_total_now - other_total_before
    equity_method = components["largest_customer_equity_method_net_usd_bn"]
    story = stamped_block(staging, "other_income_story", period)

    def money(value: float) -> str:
        return f"{'−' if value < 0 else '+'}${abs(value):,.0f}M"

    other_income_fy_chart = {
        "kind": "grouped_bars",
        "title": (f"{this_fy} 其他收入（净）{money(other_total_now)}、上年 {money(other_total_before)}："
                  f"摆动 ${other_swing:,.0f}M，占税前利润增量的 "
                  f"{other_swing / (pretax_now - pretax_before) * 100:.1f}%"),
        "xlabels": [name for _, name in component_rows],
        "groups": [
            {"name": last_fy, "values": [components[key][before_at] for key, _ in component_rows], "color": "GRAY"},
            {"name": this_fy, "values": [components[key][now_at] for key, _ in component_rows], "color": "NAVY"},
        ],
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "$M",
        "bar_labels": False,
        "note": (
            f"税前利润 = 营业利润 + 其他收入（净）：{this_fy} ${pretax_now:,.0f}M、{last_fy} ${pretax_before:,.0f}M，"
            f"增量 ${pretax_now - pretax_before:,.0f}M 里有 ${other_swing:,.0f}M 不是经营挣来的。"
            f"摆动最大的是「其他」一行（{money(components['other_net'][before_at])} → "
            f"{money(components['other_net'][now_at])}），那一行是权益法投资的损益：10-K 附注 3 说其中来自单一大客户"
            f"（也是权益法被投公司）的净额 {this_fy} {'+' if equity_method[now_at] >= 0 else '−'}"
            f"${abs(equity_method[now_at]):g}B、{last_fy} {'+' if equity_method[before_at] >= 0 else '−'}"
            f"${abs(equity_method[before_at]):g}B，{this_fy} 的收益主要是该公司重组带来的稀释收益，按 HLBV 法计量，"
            "方向可逆。其次是投资净收益与衍生品。"
            + (fill_story(story["words"], {"gain": f"${story['discrete_gain_usd_bn']:g}B",
                                           "eps": f"${story['discrete_eps_net_usd']:.2f}"}) if story else "")
            + "所以本页把经营利润与现金流放在前面：跨期比较 GAAP 每股收益会被这一行带偏。"
        ),
        "src_extra": (
            "分项读自 10-K 附注 3「Other income (expense), net」；税前利润为营业利润加其他收入（净），"
            "增量占比为自算（D）。季度的其他收入见第四板块。"
        ),
    }
    highlights = [
        {
            "kind": "gs_bar",
            "title": (
                f"收入 ${revenue_shown[-1]:,.0f}M、同比 {revenue_yoy[-1]:.1f}%"
                + (f"，下季指引中点隐含 {signed(guidance_revenue_yoy)}" if guidance else "")
            ),
            "xlabels": long_labels,
            "xstep": LONG_STEP,
            "values": long_revenue,
            "legend": "总收入",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "ylab2": "同比增速",
            "yoy": {
                "name": "同比增速 (RHS)",
                "values": long_revenue_yoy,
                "color": "GREEN",
                "yfmt": "pct1",
            },
            "note": (
                ((f"{'高于' if revenue_shown[-1] > consensus['revenue_usd_m_range'][1] else '低于' if revenue_shown[-1] < consensus['revenue_usd_m_range'][0] else '落在'}"
                  f"市场预期区间 ${consensus['revenue_usd_m_range'][0]:,}–"
                  f"{consensus['revenue_usd_m_range'][1]:,}M"
                  + ("之内" if consensus['revenue_usd_m_range'][0] <= revenue_shown[-1] <= consensus['revenue_usd_m_range'][1] else "")
                  + f"；两个公开来源相差 ${consensus['revenue_usd_m_range'][1] - consensus['revenue_usd_m_range'][0]:,}M，"
                  "因此本页只确认「超预期方向」，不发布超预期幅度。") if consensus else "")
                + f"<b>{cn_count(years)}年的窗口里这条同比线走过 "
                f"{min(reported_yoy):.0f}% 到 {max(reported_yoy):.0f}%</b>，"
                f"本季 {long_revenue_yoy[-1]:.1f}% 在这个区间的"
                + ("上四分之一" if long_revenue_yoy[-1] >= upper_quartile else "中段") + "。"
            ),
            "src_extra": source_note("收入来自各期 10-Q / 10-K；同比与下季隐含同比为自算"),
        },
        {
            "kind": "lines",
            "title": (
                (f"现行分部口径下 Intelligent Cloud 本季首次超过 Productivity：" if ic_first_lead else
                 f"Intelligent Cloud 对 Productivity：")
                + f"${ic[-1]:,}M vs ${pbp[-1]:,}M"
            ),
            "xlabels": seg_labels,
            "series": [
                {"name": "Intelligent Cloud", "values": ic, "color": "NAVY"},
                {"name": "Productivity & Business Processes", "values": pbp, "color": "MBLUE"},
                {"name": "More Personal Computing", "values": mpc, "color": "GRAY"},
            ],
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "zero_base": True,
            "end_label": True,
            "ylab": "$M",
            "note": (
                ("三条线彻底分道：" if max(segment_growth) - min(segment_growth) >= 20 else "三条线同比：")
                + f"IC 同比 {pct_change(ic[-1], ic[-5]):+.1f}%，"
                f"PBP {pct_change(pbp[-1], pbp[-5]):+.1f}%，"
                f"MPC {pct_change(mpc[-1], mpc[-5]):+.1f}%；"
                f"MPC 的分部经营利润率同时从 {mpc_margin[-2]:.1f}% "
                f"{'掉' if mpc_margin[-1] < mpc_margin[-2] else '升'}到 {mpc_margin[-1]:.1f}%。"
                + ((f"「首次」只对现行口径成立：公司自 FY2025 起重划分部，重述后的数回到 {basis_from}，"
                    f"这{cn_count(basis_quarters)}季里此前每一季都是 PBP 更大；"
                    # The old basis is named by its crossover year, and that year
                    # is called the crossover only while the year before still
                    # had PBP ahead.
                    + ((f"按重划前的旧口径，IC 在 {old_basis['fiscal_year']} 就已超过 PBP（{old_basis['fiscal_year']} 10-K："
                        f"IC ${old_basis['intelligent_cloud_revenue']:,}M、PBP ${old_basis['productivity_revenue']:,}M"
                        + (f"；{old_basis['prior_fiscal_year']} 还是 ${old_basis['prior_intelligent_cloud_revenue']:,}M 对 "
                           f"${old_basis['prior_productivity_revenue']:,}M"
                           if old_basis["prior_intelligent_cloud_revenue"] <= old_basis["prior_productivity_revenue"] else "")
                        + "），两套口径不能接起来比。") if old_basis else ""))
                   if ic_first_lead else "")
            ),
            "src_extra": (
                f"分部收入取自 {filing_years} 各期 10-Q / 10-K 的重述后可比列，{cn_count(len(ic))}季口径一致；同比为自算。"
                + ("更早的现行口径季度取自 FY2025 各期 10-Q 的去年同期列与 FY2025 10-K。" if recast else "")
            ),
        },
        {
            "kind": "gs_line",
            "title": (
                f"Intelligent Cloud 分部毛利率连降{cn_count(ic_falls)}季后首次回升至 {ic_gross_margin[-1]:.2f}%"
                if ic_turned_up and ic_falls >= 2 else
                f"Intelligent Cloud 分部毛利率 {ic_gross_margin[-1]:.2f}%，环比"
                + ("回升" if ic_turned_up else "下降")
            ),
            "xlabels": seg_labels,
            "values": ic_gross_margin,
            "legend": "IC 分部毛利率 D",
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "ylab": "分部毛利率",
            "note": (
                f"环比 {ic_gross_margin[-1] - ic_gross_margin[-2]:+.2f}pp，"
                f"{'但' if ic_turned_up and ic_gross_margin[-1] < ic_gross_margin[-5] else ''}同比"
                f"{'仍' if ic_gross_margin[-1] < ic_gross_margin[-5] else ''} {ic_gross_margin[-1] - ic_gross_margin[-5]:+.2f}pp；"
                + (("分部收入成本同比增速仍快于分部收入，结构性压力只是被减速、没有被逆转。"
                    if ic_turned_up else
                    "分部收入成本同比增速仍快于分部收入，结构性压力还在加深。")
                   if ic_cost_yoy > ic_revenue_yoy else
                   "分部收入成本同比增速已不快于分部收入。")
                + (f"季度分部收入成本自 {seg_labels[0]} 起才有（FY2026 各期 10-Q 的比较列），"
                   f"这{cn_count(len(ic_gross_margin))}季就是整段季度记录；更早只有年度数："
                   + "、".join(f"{label} {(revenue_value - cost) / revenue_value * 100:.1f}%"
                              for label, revenue_value, cost in zip(ic_annual["labels"], ic_annual["revenue"],
                                                                    ic_annual["cost_of_revenue"]))
                   + "。" if ic_annual else "")
            ),
            "src_extra": (
                "分部收入与分部收入成本来自各期 10-Q / 10-K 的分部附注，毛利率为两者相除的自算值，"
                "不是公司披露的 Microsoft Cloud 毛利率。"
            ),
        },
        {
            "kind": "bars_labeled",
            "title": (
                f"商业剩余履约义务{'升' if rpo_levels[-1] > rpo_levels[-2] else '降'}至 US${rpo_levels[-1]}B，"
                "但 12 个月内可确认的比例才是近端可见度"
            ),
            "xlabels": rpo_labels,
            "xstep": LONG_STEP,
            "values": rpo_levels,
            "legend": "商业 RPO 余额",
            "fmt": "usd0",
            "yfmt": "usd0",
            "label_fmt": "usd0",
            "ylab": "US$B",
            "note": (
                (f"余额同比 {rpo_yoy:+.0f}%，" if rpo_yoy is not None else "")
                + (f"{'但 ' if rpo_yoy is not None and near_yoy < rpo_yoy else ''}12 个月内可确认的部分"
                   f"{'只' if rpo_yoy is not None and near_yoy < rpo_yoy else ''}同比 {near_yoy:+.0f}%"
                   if near_yoy is not None else "")
                + (f"，占比由一年前的约 {share_before}% "
                   f"{'降' if share_now < share_before else '升' if share_now > share_before else '持平'}到约 "
                   f"{share_now}%" if share_now is not None and share_before is not None else "")
                + (f"；剔除单一大客户后余额同比仅 {ex_largest:+.0f}%，"
                   + ("低于" if ex_largest < azure[-1] else "不低于") + " Azure 自身的增速。"
                   if ex_largest is not None else "。")
            ),
            "src_extra": (
                f"余额逐季读自各期 10-Q / 10-K 的收入附注（{rpo_labels[0]} 起才拆出商业部分，更早只有全公司口径）；"
                f"12 个月内确认比例、该部分同比与剔除单一大客户的同比来自各季电话会 CFO 陈述，"
                f"本文件接了近{cn_count(len(rpo['periods']))}季，"
                "逐格出处见核对表。比例一列只画在核对表里，不画曲线：电话会说的是商业口径，10-Q 在 2025-12-31 之前只印全公司口径。"
            ),
        },
        {
            "kind": "grouped_bars",
            "title": (
                f"{this_fy} 股东回报已达调整后自由现金流的 {return_coverage[-1]:.1f}%"
            ),
            "xlabels": fy["labels"],
            "groups": [
                {"name": "自由现金流（报告口径）D", "values": reported_fy_fcf, "color": "BLUE"},
                {"name": "自由现金流（扣未付资本开支）D", "values": adjusted_fy_fcf, "color": "NAVY"},
                {"name": "股东回报（计划内回购 + 分红）", "values": shareholder_returns, "color": "GOLD"},
            ],
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "bar_labels": False,
            "note": (
                f"年报披露仍留在应付账款里的资本开支由 ${fy['unpaid_capex_in_payables'][-2]:,}M 升到 "
                f"${fy['unpaid_capex_in_payables'][-1]:,}M，扣掉这 "
                f"${unpaid_increase:,}M 增量后，"
                f"{this_fy} 自由现金流同比 {pct_change(adjusted_fy_fcf[-1], adjusted_fy_fcf[-2]):+.1f}%，"
                f"而报告口径{'只有' if abs(pct_change(reported_fy_fcf[-1], reported_fy_fcf[-2])) < abs(pct_change(adjusted_fy_fcf[-1], adjusted_fy_fcf[-2])) else '是'} "
                f"{pct_change(reported_fy_fcf[-1], reported_fy_fcf[-2]):+.1f}%。"
                f"股东回报按公司口径计：计划内回购加分红；现金流量表的回购一行另含为员工代扣税回购的 "
                f"${withholding[-1]:,}M，那是股权激励的结算，不计入；按含它的现金流量表回购一行计，覆盖率为 "
                f"{cash_basis_coverage:.1f}%（本季分析用的是这一口径）。"
            ),
            "src_extra": (
                "经营现金流、现金资本开支、回购与分红来自现金流量表；计划内回购来自 10-K 股东权益附注；"
                "未付资本开支来自 10-K 的物业及设备附注。调整后口径为报告值减该余额的年度增量，是算术调整，不是公司定义的指标。"
            ),
        },
        other_income_fy_chart,
    ]
    # A range over the whole record is not this quarter's conclusion, so the
    # long other-income line sits with the other long series in section four.
    other_income_chart = {
        "kind": "diverging_bars",
        "title": (
            f"其他收入（净）{cn_count(len(long_other_income))}季在 ${min(long_other_income):,.0f}M 与 "
            f"+${max(long_other_income):,.0f}M 之间摆动，本季 "
            f"{'+' if other_income[-1] >= 0 else '-'}${abs(other_income[-1]):,}M"
        ),
        "xlabels": long_labels,
        "xstep": LONG_STEP,
        "values": long_other_income,
        "legend": "其他收入（净）",
        "positive_label": "净收益",
        "negative_label": "净损失",
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "$M",
        "zero_line": True,
        "note": (
            "这条线几乎全部是非现金的权益法与估值变动，方向可逆"
            + ("——同一套会计方法在上一财年产生的是净损失。" if last_fy_other is not None and last_fy_other < 0
               else "。")
            + "跨期比较 GAAP 每股收益会被它系统性带偏，本页因此把经营利润与现金流放在前面。"
            f"<b>八季的窗口把这条线画成一个「最近变大了」的故事，{cn_count(len(long_other_income))}季不是。</b>"
            f"{quarters[0][:4]}–{quarters[quiet_end - 1][:4]} 年它长期在 ${min(quiet):,.0f}M 到 "
            f"${max(quiet):,.0f}M 的窄带里，"
            f"绝对值超过 $2,000M 的只有 {sum(1 for v in quiet if abs(v) > 2000)} 季；"
            f"最近{cn_count(len(recent))}季里有 {sum(1 for v in recent if abs(v) > 2000)} 季超过。"
            "变大的是波幅，不是水平。"
            "同一个季度会被多份申报重印，且数会变（2016 年 9 月止季 100 → 112），"
            "本页一律取最后一次申报的值。"
        ),
        "src_extra": source_note("其他收入（净）来自各期利润表；本页不拆分其中的单笔投资"),
    }

    # ── section three ────────────────────────────────────────────────────────
    # This quarter's section 8 and its revocation conditions, drawn by the same
    # code that settles last quarter's lines in section one: at the next roll
    # this block moves into `prior_kpi_settlement` as it stands.
    next_charts: list[dict] = []
    next_rows: list[list[str]] = []
    if next_kpi is not None:
        if next_kpi["for_period"] != shift_period(period, 1):
            raise ValueError(f"series block `next_kpi` is stamped for {next_kpi['for_period']!r}, "
                             f"but the next quarter is {shift_period(period, 1)!r}: update it with the roll")
        next_overview, next_lines, next_rows = settlement_exhibits(staging, next_kpi, "下季", period)
        next_charts = [next_overview] + next_lines
    next_description = ""
    if next_kpi is not None:
        entries = next_kpi["quantified"]
        revocations = {entry["row"] for entry in entries if isinstance(entry["row"], str)} | \
                      {item["row"] for item in next_kpi.get("unscored", []) if isinstance(item["row"], str)}
        next_description = (
            f"本季分析{next_kpi['section'].split('「')[0]}的 {next_kpi['rows']} 行"
            + (f"与{cn_count(len(revocations))}条立场撤销条件" if revocations else "")
            + f"，每一档拆成独立的线，共 {len(entries)} 条：柱图是当前读数离每条线还有多远，"
            f"有序列的读数（{cn_count(len(next_lines))}个）逐条画在历史线上；"
            "「且」条件拆成两腿，阈值为零、只在财年末结算或读数太短的线写在总览图注里。"
            "阈值都来自本季分析，页面没有自设的线。"
        )

    # ── section four ─────────────────────────────────────────────────────────
    quiet_to = quarters.index(QUIET_YEARS_END) + 1
    intensity_top = long_intensity[-1] >= max(long_intensity)
    early_gm = long_gross_margin[:quarters.index("2018Q4") + 1]
    eight_gm = long_gross_margin[-WINDOW:]
    eight_falls = sum(1 for a, b in zip(eight_gm, eight_gm[1:]) if b < a)
    depreciation_known = depreciation
    implied_gm = ((guidance_revenue_mid - sum(guidance["cost_of_revenue_usd_m"]) / 2) / guidance_revenue_mid * 100
                  if guidance else None)
    year_ago_next = q["gross_profit"][-4] / revenue[-4] * 100
    routine = [
        {
            "kind": "lines",
            "title": (
                f"资本强度{cn_count(years)}年从 {long_intensity[0]:.1f}% "
                f"{'升' if long_intensity[-1] > long_intensity[0] else '降'}到 {long_intensity[-1]:.1f}%，"
                f"本季现金资本开支 ${capex[-1]:,.0f}M"
            ),
            "xlabels": long_labels,
            "xstep": LONG_STEP,
            "series": [
                {"name": "现金 CapEx / 收入 D", "values": long_intensity, "color": "NAVY"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "zero_base": True,
            "end_label": True,
            "ylab": "占收入比",
            "note": (
                f"同比 {pct_change(capex[-1], capex[-5]):+.1f}%"
                # The call guides on its own basis (finance leases included), not
                # on the cash line this chart draws.
                + (f"；下季指引（公司口径，含融资租赁）{guidance['capex_next_quarter']}。" if guidance else "。")
                + ((f"<b>拉长看才知道当前这一档没有先例</b>：{quarters[0][:4]}–{QUIET_YEARS_END[:4]} 年这条线长期在 "
                    f"{min(long_intensity[:quiet_to]):.0f}–{max(long_intensity[:quiet_to]):.0f}%，"
                    f"当前 {long_intensity[-1]:.1f}% 是{cn_count(years)}年区间的顶点。")
                   if intensity_top else
                   f"{quarters[0][:4]}–{QUIET_YEARS_END[:4]} 年这条线长期在 "
                   f"{min(long_intensity[:quiet_to]):.0f}–{max(long_intensity[:quiet_to]):.0f}%。")
                + "这条线只含已付现的部分，口径与本站其他公司页的现金资本开支一致，可直接横向比较；"
                "公司口径的资本开支还要加上下面那张融资租赁新增。"
            ),
            "src_extra": source_note(
                "现金资本开支逐季来自各期现金流量表（10-Q 只按年初至今披露，逐季由相邻两个"
                "年初至今值相减，财政第四季为全年 − 前三季）；占收入比为自算"),
        },
        {
            "kind": "lines",
            "title": (
                f"毛利率{cn_count(years)}年从 {long_gross_margin[0]:.1f}% 走到 {long_gross_margin[-1]:.1f}%，"
                f"营业利润率 {long_operating_margin[-1]:.1f}%"
            ),
            "xlabels": long_labels,
            "xstep": LONG_STEP,
            "series": [
                {"name": "毛利率", "values": long_gross_margin, "color": "NAVY"},
                {"name": "营业利润率", "values": long_operating_margin, "color": "MBLUE"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "end_label": True,
            "ylab": "利润率",
            "note": (
                ((f"下季指引隐含毛利率约 {implied_gm:.1f}%，较去年同期再"
                  f"{'降' if implied_gm < year_ago_next else '升'}约 {abs(implied_gm - year_ago_next):.0f}pp；"
                  f"公司对 FY{int(fiscal_year[2:]) + 1} 的口径是「营业利润率{guidance['fy2027_operating_margin']}」。")
                 if guidance else "")
                + (f"<b>{cn_count(len(eight_gm))}季的窗口会把这段读成下滑"
                   f"（{cn_count(len(eight_gm) - 1)}次环比里{cn_count(eight_falls)}次下降），"
                   f"{cn_count(years)}年的窗口说的是另一回事</b>："
                   if eight_falls < len(eight_gm) - 1 else
                   f"<b>{cn_count(len(eight_gm))}季的窗口会把这段读成单向下滑，"
                   f"{cn_count(years)}年的窗口说的是另一回事</b>：")
                + f"毛利率 {quarters[0][:4]}–2018 年在 {min(early_gm):.0f}–{max(early_gm):.0f}% 之间，"
                f"到 {max(long_gross_margin):.0f}% 见顶后才回落到今天的 "
                f"{long_gross_margin[-1]:.1f}%"
                + ("，当前值仍高于窗口起点。" if long_gross_margin[-1] > long_gross_margin[0] else "。")
            ),
            "src_extra": source_note("毛利率与营业利润率按利润表口径自算，指引隐含值取区间中点"),
        },
        {
            "kind": "gs_bar",
            "title": (
                f"季度折旧 ${depreciation[-1]:,.0f}M、占收入 {depreciation_ratio[-1]:.1f}%，"
                f"{cn_count(len(depreciation_known))}季"
                + ("翻了一倍以上" if depreciation_known[-1] >= 2 * depreciation_known[0] else
                   f"增长 {pct_change(depreciation_known[-1], depreciation_known[0]):.0f}%")
            ),
            "xlabels": labels[dep_from:],
            "values": depreciation,
            "legend": "季度折旧",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "ylab2": "占收入比",
            "yoy": {
                "name": "折旧 / 收入 (RHS) D",
                "values": depreciation_ratio,
                "color": "RED",
                "yfmt": "pct1",
            },
            "note": (
                f"{this_fy} 折旧 ${fy['depreciation'][-1]:,}M，较 {last_fy} 的 ${fy['depreciation'][-2]:,}M 增 "
                f"{pct_change(fy['depreciation'][-1], fy['depreciation'][-2]):.0f}%。"
                + (f"数据中心与办公楼的估计可使用年限自 {guidance['useful_life_effective']} 起由 "
                   f"{guidance['useful_life_years'][0]} 年延长到 "
                   f"{guidance['useful_life_years'][1]} 年，这条线的下一段斜率因此不再可比。"
                   if guidance else "")
            ),
            "src_extra": source_note("季度折旧来自各期现金流量表，按公司披露精度到 $100M；占收入比为自算"),
        },
        {
            "kind": "lines",
            "title": (
                f"融资租赁新增{cn_count(years)}年累计 ${sum(v for v in long_leases if v is not None):,.0f}M，"
                "是资本开支口径之外的第二条通道"
            ),
            "xlabels": long_labels[lease_from:],
            "xstep": LONG_STEP,
            "series": [
                {"name": "融资租赁新增", "values": long_leases[lease_from:], "color": "NAVY"},
            ],
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "zero_base": True,
            "end_label": True,
            "ylab": "$M",
            "note": (
                f"{this_fy} 新增 ${fy['finance_lease_additions'][-1]:,}M。"
                + ("年限延长后，一份 15 年期数据中心租约"
                   "占资产经济寿命的比例下降，会从融资租赁重分类为经营租赁——公司口径的自然年资本开支"
                   f"因此由约 US${guidance['cy2026_capex_prior_usd_bn']}B 调整为约 "
                   f"US${guidance['cy2026_capex_usd_bn']}B，而管理层同时说明支出预期本身没有变。"
                   if guidance else "")
                + f"<b>{cn_count(years)}年窗口正是读这次重分类的前提</b>：这条通道在 {quarters[0][:4]}–{QUIET_YEARS_END[:4]} 年几乎是平的，"
                "本轮建设周期才把它抬成与现金资本开支同一量级的第二条腿，"
                "所以口径一动就能改写「公司资本开支」这个数。"
            ),
            "src_extra": (
                "融资租赁新增为「以租赁负债交换的使用权资产」，逐季来自各期现金流量表的补充披露；"
                "本页不把它与现金资本开支相加，因为两者的现金路径不同。"
            ),
        },
        other_income_chart,
    ]
    # The depreciation chart says why it alone is short; how many of its
    # neighbours do reach the record's first year is counted, not typed.
    depreciation_chart = next(ex for ex in routine if ex["kind"] == "gs_bar")
    reaching = [ex for ex in routine if ex is not depreciation_chart
                and ex["xlabels"][0].endswith(f"'{quarters[0][2:4]}")]
    depreciation_chart["note"] += (
        f"<b>本节其余{cn_count(len(reaching))}张都拉到了 {quarters[0][:4]} 年，只有这张没有</b>："
        f"{long['depreciation_note']}"
    )

    exhibits = number_exhibits(settled_charts + highlights + next_charts + routine)
    first_table = len(exhibits) + 2

    quarterly_rows = []
    for index, p in enumerate(periods):
        quarterly_rows.append([
            p,
            f"${revenue[index]:,.0f}M",
            f"${q['gross_profit'][index]:,.0f}M",
            f"${q['operating_income'][index]:,.0f}M",
            f"${q['operating_expenses'][index]:,.0f}M",
            (lambda value: f"-${abs(value):,.0f}M" if value < 0 else f"${value:,.0f}M")(
                q["other_income_expense_net"][index]
            ),
            f"${q['operating_cash_flow'][index]:,.0f}M",
            f"${q['cash_paid_for_property_and_equipment'][index]:,.0f}M",
            f"${q['operating_cash_flow'][index] - q['cash_paid_for_property_and_equipment'][index]:,.0f}M D",
            f"${q['finance_lease_additions'][index]:,.0f}M",
            f"${q['stock_repurchases'][index]:,.0f}M",
            "—" if q["depreciation"][index] is None else f"${q['depreciation'][index]:,.0f}M",
        ])

    segment_rows = []
    for index, p in enumerate(segments["periods"]):
        segment_rows.append([
            p,
            f"${segments['productivity_revenue'][index]:,}M",
            f"{segments['productivity_operating_income'][index] / segments['productivity_revenue'][index] * 100:.1f}% D",
            f"${segments['intelligent_cloud_revenue'][index]:,}M",
            f"{segments['intelligent_cloud_operating_income'][index] / segments['intelligent_cloud_revenue'][index] * 100:.1f}% D",
            f"{ic_gross_margin[index]:.2f}% D",
            f"${segments['more_personal_computing_revenue'][index]:,}M",
            f"{segments['more_personal_computing_operating_income'][index] / segments['more_personal_computing_revenue'][index] * 100:.1f}% D",
            f"{azure[index]:+d}%",
        ])

    def fy_row(label: str, key: str) -> list[str]:
        return [label, f"${fy[key][-2]:,}M", f"${fy[key][-1]:,}M",
                f"{pct_change(fy[key][-1], fy[key][-2]):+.1f}%"]

    # Net cash counting finance-lease liabilities as debt: the analysis's point
    # that the balance sheet stopped being net cash once the leases are in.
    debt = [current + term for current, term in
            zip(fy["current_portion_of_long_term_debt"], fy["long_term_debt"])]
    net_cash = [cash - owed - leases for cash, owed, leases in
                zip(fy["cash_and_short_term_investments"], debt, fy["finance_lease_liabilities"])]

    fy_rows = [
        fy_row("收入", "revenue"),
        fy_row("经营利润", "operating_income"),
        fy_row("经营现金流", "operating_cash_flow"),
        fy_row("现金资本开支", "cash_paid_for_property_and_equipment"),
        fy_row("融资租赁新增", "finance_lease_additions"),
        ["自由现金流（报告口径）D", f"${reported_fy_fcf[-2]:,.0f}M", f"${reported_fy_fcf[-1]:,.0f}M",
         f"{pct_change(reported_fy_fcf[-1], reported_fy_fcf[-2]):+.1f}%"],
        fy_row("计入应付账款的未付资本开支", "unpaid_capex_in_payables"),
        ["自由现金流（扣未付资本开支增量）D", f"${adjusted_fy_fcf[-2]:,.0f}M", f"${adjusted_fy_fcf[-1]:,.0f}M",
         f"{pct_change(adjusted_fy_fcf[-1], adjusted_fy_fcf[-2]):+.1f}%"],
        fy_row("回购", "stock_repurchases"),
        fy_row("其中计划内回购", "share_repurchase_program"),
        fy_row("分红", "dividends_paid"),
        ["股东回报 / 调整后自由现金流 D", f"{return_coverage[-2]:.1f}%", f"{return_coverage[-1]:.1f}%",
         f"{return_coverage[-1] - return_coverage[-2]:+.1f}pp"],
        fy_row("折旧", "depreciation"),
        fy_row("折旧、摊销及其他（现金流量表）", "depreciation_amortization_and_other"),
        fy_row("已签约但尚未起租的租约", "contracted_not_yet_commenced_leases"),
        fy_row("现金及短期投资", "cash_and_short_term_investments"),
        ["债务（含一年内到期）", f"${debt[-2]:,}M", f"${debt[-1]:,}M", f"{pct_change(debt[-1], debt[-2]):+.1f}%"],
        fy_row("融资租赁负债", "finance_lease_liabilities"),
        ["净现金（现金及短期投资 − 债务 − 融资租赁负债）D", money(net_cash[-2]), money(net_cash[-1]),
         f"{'由正转负' if net_cash[-2] >= 0 > net_cash[-1] else '变化'} {money(net_cash[-1] - net_cash[-2])}"],
    ]

    guidance_rows = []
    capex_company_now = kpi["capex_incl_finance_leases_usd_bn"]["values"][-1]
    if guidance is not None:
        remarks = guidance.get("remarks", {})
        ic_guide_mid = sum(guidance["intelligent_cloud_usd_m"]) / 2
        ic_guide_growth = pct_change(ic_guide_mid, ic[-4])
        mpc_guide_growth = pct_change(sum(guidance["more_personal_computing_usd_m"]) / 2, mpc[-4])
        guidance_rows = [
            ["下季总收入", "—",
             f"US${guidance['revenue_usd_m'][0] / 1000:.2f}–{guidance['revenue_usd_m'][1] / 1000:.2f}B",
             f"中点 ${guidance_revenue_mid:,.0f}M，隐含同比 {signed(guidance_revenue_yoy)} D"],
            ["下季 Azure（固定汇率）", f"{azure[-1]}%（本季实际）",
             f"约 +{guidance['azure_cc_growth_pct']}%", remarks.get("azure", "")],
            ["下季 Intelligent Cloud", f"${ic[-1]:,}M（本季实际）",
             f"US${guidance['intelligent_cloud_usd_m'][0] / 1000:.2f}–{guidance['intelligent_cloud_usd_m'][1] / 1000:.2f}B",
             "分部指引增速" + ("高于" if ic_guide_growth > pct_change(ic[-1], ic[-5]) else "不高于") + "本季实际增速"],
            ["下季 Productivity and Business Processes", f"${pbp[-1]:,}M（本季实际）",
             f"US${guidance['productivity_usd_m'][0] / 1000:.2f}–{guidance['productivity_usd_m'][1] / 1000:.2f}B",
             f"中点隐含同比 {signed(pct_change(sum(guidance['productivity_usd_m']) / 2, pbp[-4]))} D"],
            ["下季 More Personal Computing", f"${mpc[-1]:,}M（本季实际）",
             f"US${guidance['more_personal_computing_usd_m'][0] / 1000:.2f}–{guidance['more_personal_computing_usd_m'][1] / 1000:.2f}B",
             ("继续下滑，" if mpc_guide_growth < 0 else "恢复增长，") + remarks.get("more_personal_computing", "")],
            ["下季资本开支（公司口径，含融资租赁）",
             f"约 US${capex_company_now:g}B（本季公司口径；现金口径 ${capex[-1]:,}M）", guidance["capex_next_quarter"],
             remarks.get("capex", "")],
            [f"FY{int(fiscal_year[2:]) + 1} 收入", "—", guidance["fy2027_revenue"], remarks.get("fy2027_revenue", "")],
            [f"FY{int(fiscal_year[2:]) + 1} 营业利润率", "—", guidance["fy2027_operating_margin"],
             remarks.get("fy2027_operating_margin", "")],
            [f"FY{int(fiscal_year[2:]) + 1} 自由现金流", "—", guidance["fy2027_free_cash_flow"],
             remarks.get("fy2027_free_cash_flow", "")],
            [f"FY{int(fiscal_year[2:]) + 1} 有效税率", "—", f"约 {guidance['fy2027_tax_rate_pct']:g}%", "电话会口径"],
            ["自然年 2026 资本开支", f"约 US${guidance['cy2026_capex_prior_usd_bn']}B",
             f"约 US${guidance['cy2026_capex_usd_bn']}B", guidance["capex_restatement_reason"]],
            ["数据中心与办公楼折旧年限",
             f"{guidance['useful_life_years'][0]} 年", f"{guidance['useful_life_years'][1]} 年",
             remarks.get("useful_life", "")],
        ]

    def listed(values: list, digits: int = 0) -> str:
        return " / ".join("—" if value is None else f"{value:.{digits}f}" for value in values)

    capex_company = kpi["capex_incl_finance_leases_usd_bn"]
    kpi_rows = [
        ["商业剩余履约义务（季末余额）", "US$B", listed(rpo_levels[-len(rpo["periods"]):]),
         " / ".join(rpo["periods"]) + f"；10-Q / 10-K 收入附注，{rpo_labels[0]} 起的完整序列见图"],
        ["其中 12 个月内可确认占比", "%", listed(rpo["twelve_month_share_pct"]), rpo["share_note"]],
        ["12 个月内可确认部分同比", "%", listed(rpo["twelve_month_portion_yoy_pct"]),
         " / ".join(rpo["periods"]) + "；电话会"],
        ["剔除单一大客户的商业 RPO 同比", "%", listed(rpo["ex_largest_customer_yoy_pct"]), rpo["yoy_provenance"]],
        ["M365 Copilot 付费席位", "百万", listed(kpi["copilot_paid_seats_m"]["values"]),
         " / ".join(kpi["copilot_paid_seats_m"]["periods"])],
        ["Microsoft Cloud 收入", "US$B", listed(kpi["microsoft_cloud"]["revenue_usd_bn"], 1),
         " / ".join(kpi["microsoft_cloud"]["periods"])],
        ["Microsoft Cloud 毛利率", "%", listed(kpi["microsoft_cloud"]["gross_margin_pct"]),
         kpi["microsoft_cloud"]["provenance"]],
        ["资本开支（公司口径，含融资租赁）", "US$B", listed(capex_company["values"], 1),
         " / ".join(capex_company["periods"]) + "；" + capex_company["provenance"]],
        ["商业签约额（剔除单一大客户）同比", "%",
         listed(kpi["bookings_ex_largest_customer_yoy_pct"]["values"]),
         " / ".join(kpi["bookings_ex_largest_customer_yoy_pct"]["periods"])],
        # The section-8 line reads the adjusted rate; the release prints the
        # reported one beside it, so both are in the drawer.
        ["M365 商业云收入同比（调整后 / 报告口径）", "%",
         " ; ".join(f"{adjusted} / {reported}" for adjusted, reported in zip(
             kpi["m365_commercial_cloud"]["adjusted_pct"], kpi["m365_commercial_cloud"]["reported_pct"])),
         " / ".join(kpi["m365_commercial_cloud"]["periods"])
         + "；新闻稿（8-K EX-99.1）原句，调整后口径剔除上年同期的一次性确认"],
    ]

    tables = []
    if prior_kpi is not None:
        tables.append({
            "n": 0,
            "title": "上季阈值与本季实际（原单位）",
            "headers": ["指标", "有利一侧", "阈值", f"{period} 实际", "余量 D", "判定"],
            "rows": prior_rows,
        })
    if next_kpi is not None:
        tables.append({
            "n": 0,
            "title": "下季阈值与当前值（原单位）",
            "headers": ["指标", "有利一侧", "阈值", "当前值", "余量 D", "当前位置"],
            "rows": next_rows,
        })
    if guidance_rows:
        tables.append({
            "n": 0,
            "title": f"下季与 FY{int(fiscal_year[2:]) + 1} 指引",
            "headers": ["指标", "上季 / 本季实际", "新口径", "变化 / 备注"],
            "rows": guidance_rows,
        })
    tables += [
        {
            "n": 0,
            "title": (f"两个财政年度的现金与股东回报（{last_fy} = 截至 {fy['period_end'][-2]}）"),
            "headers": ["指标", last_fy, this_fy, "变化"],
            "rows": fy_rows,
        },
        {
            "n": 0,
            "title": f"{cn_count(len(segments['periods']))}季度分部收入、分部利润率与 Azure 增速",
            "headers": ["期间", "PBP 收入", "PBP 利润率", "IC 收入", "IC 利润率", "IC 毛利率",
                        "MPC 收入", "MPC 利润率", "Azure（固定汇率）"],
            "rows": segment_rows,
        },
        {
            "n": 0,
            "title": f"{cn_count(len(periods))}季度基础数据（前四季只用于计算同比）",
            "headers": ["期间", "总收入", "毛利", "经营利润", "经营费用", "其他收入（净）",
                        "经营现金流", "现金资本开支", "自由现金流 D", "融资租赁新增", "回购", "折旧"],
            "rows": quarterly_rows,
        },
        {
            "n": 0,
            "title": "披露不连续的运营指标（只在公司给出的期间存在）",
            "headers": ["指标", "单位", "已披露值", "对应期间 / 口径说明"],
            "rows": kpi_rows,
        },
        ai_capex_cycle_table(0),
    ]
    for offset, table in enumerate(tables):
        table["n"] = first_table + offset

    # ── the lines the page leads with ───────────────────────────────────────
    adjusted_change = pct_change(adjusted_fy_fcf[-1], adjusted_fy_fcf[-2])
    operating_words = []
    if azure[-1] > azure[-2]:
        operating_words.append(f"Azure 固定汇率增速由 {azure[-2]}% 加速到 {azure[-1]}%")
    else:
        operating_words.append(f"Azure 固定汇率增速 {azure[-1]}%")
    if ic_first_lead:
        operating_words.append("按现行分部口径 Intelligent Cloud 收入首次超过 Productivity")
    if ic_turned_up and ic_falls >= 2:
        operating_words.append(f"分部毛利率{cn_count(ic_falls)}季来首次回升")
    headline = (
        ("经营端确实更强了——" if azure[-1] > azure[-2] and ic_turned_up else "经营端：")
        + "，".join(operating_words) + "；"
        + ("但财务端同时在恶化：" if adjusted_change < 0 else "财务端：")
        + f"{this_fy} 报告口径自由现金流同比 {pct_change(reported_fy_fcf[-1], reported_fy_fcf[-2]):.1f}%，"
        f"扣掉仍留在应付账款里的 ${unpaid_increase:,}M "
        f"未付资本开支后是 {adjusted_change:.1f}%，"
        f"股东回报已占到调整后自由现金流的 {return_coverage[-1]:.1f}%。"
        + (f"{consensus.get('post_earnings_price_when', '财报后')}股价约 "
           f"{signed(consensus['post_earnings_price_change_pct'], 0)}（市场数据，非公司披露）。" if consensus else "")
    )
    low, high = (guidance_given or {}).get("azure_cc_guide_pct", (None, None))
    if return_coverage[-1] >= 100:
        return_head = "回报已超过真实自由现金流"
    elif return_coverage[-1] >= 80:
        return_head = "回报逼近真实自由现金流"
    else:
        return_head = f"回报占真实自由现金流的 {return_coverage[-1]:.0f}%"
    brief = (
        '<h4>本季三条主线</h4><div class="takeaway-grid">'
        + ('<article><span>亮点</span><b>Azure 加速且分部毛利率转向</b>'
           if azure[-1] > azure[-2] and ic_turned_up else
           '<article><span>观察</span><b>Azure 与分部毛利率</b>')
        + f'<p>固定汇率 +{azure[-1]}%'
        + (f'，超自身指引 {azure[-1] - high:.0f}–{azure[-1] - low:.0f}pt' if low is not None and azure[-1] > high else '')
        + f'；IC 分部毛利率环比 {ic_gross_margin[-1] - ic_gross_margin[-2]:+.2f}pp。</p></article>'
        + ('<article><span>结构</span><b>现行口径下 Intelligent Cloud 首次成为最大分部</b>' if ic_first_lead and ic[-1] >= max(pbp[-1], mpc[-1])
           else '<article><span>结构</span><b>三个分部</b>')
        + f'<p>${ic[-1]:,}M vs ${pbp[-1]:,}M；MPC 同比 {pct_change(mpc[-1], mpc[-5]):.1f}%。</p></article>'
        + f'<article><span>存疑</span><b>{return_head}</b>'
        f'<p>调整后 ${adjusted_fy_fcf[-1]:,.0f}M，股东回报 ${shareholder_returns[-1]:,}M，'
        f'覆盖率 {return_coverage[-1]:.1f}%。</p></article>'
        '</div>'
    )

    parts = ((["上季兑现"] if settled_charts else []) + ["本季重点"]
             + (["下季跟踪"] if next_charts else []) + ["长期常规"])
    notes = [
        f"本页统一用自然年季度标注：{period} 指截至 {latest['period_end']} 的季度，微软自己称之为 {fiscal_period}；"
        f"{this_fy} 指截至 {fy['period_end'][-1]} 的财政年度。这样标注是为了与本站其他公司页逐季可比。",
        f"本页按「{' → '.join(parts)}」{cn_count(len(parts))}段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
    ]
    if prior_overview is not None and next_kpi is not None:
        notes.append(f"Exhibit {prior_overview['n']} 与 Exhibit {next_charts[0]['n']} 的阈值取自本地季报分析"
                     f"（上季分析{prior_kpi['section'].split('「')[0]}、本季分析{next_kpi['section'].split('「')[0]}），"
                     "其中标「公司指引」的几条就是公司自己的指引，其余不是；"
                     "都不构成评级或投资建议。「距阈值余量」统一为正值代表有利一侧。")
    notes += [
        "本页只发布公司披露值、可复算的简单派生值，以及明确标注的市场预期；D 标记代表 Derived / 自算。",
        "市场预期一律标注为「市场预期」并给出取数时点，不写卖方机构名，也不发布评级、目标价或估值。"
        + (f"本季两个公开来源的收入预期相差 ${consensus['revenue_usd_m_range'][1] - consensus['revenue_usd_m_range'][0]:,}M，"
           "因此本页只发布区间与超预期方向，不发布超预期幅度。" if consensus else ""),
        "自由现金流（报告口径）= 经营现金流 − 现金支付的物业及设备，与公司口径一致；"
        "调整后口径再减去年报披露的「仍计入应付账款的物业及设备采购」的年度增量，是算术调整，"
        "不是公司定义的 non-GAAP 指标。股东回报 = 回购计划内的回购 + 分红，与公司「returned to shareholders」"
        "的口径一致，不含为员工代扣税而回购的股份。",
        "Intelligent Cloud 分部毛利率为分部收入减分部收入成本后相除的自算值，不等同公司披露的 Microsoft Cloud 毛利率；"
        "后者只在核对表中按公司给出的期间列示。",
        f"分部数据取自 {filing_years} 各期 10-Q / 10-K 的重述后可比列，{cn_count(len(segments['periods']))}季口径一致；"
        + (f"图外另核了现行口径重述回 {recast['periods'][0]} 的季度，只用于判断「首次」；" if recast else "")
        + "FY2025 重划分部之前的旧口径不可直接连接。",
        "融资租赁新增与现金资本开支在本页不相加：前者的本金偿付走筹资活动，后者走投资活动，"
        "两者对自由现金流的影响路径不同。",
        "季度折旧按公司披露精度到 $100M"
        + (f"；{guidance['useful_life_effective']} 起数据中心与办公楼的估计可使用年限由 "
           f"{guidance['useful_life_years'][0]} 年延长至 {guidance['useful_life_years'][1]} 年，"
           "折旧曲线的下一段与历史不可比。" if guidance else "。"),
        f"本页已知未接入：近{cn_count(len(kpi['microsoft_cloud']['periods']))}季以前的 Microsoft Cloud 收入与毛利率、"
        "公司口径资本开支（都在各季电话会里，本页只接了近期）；"
        f"近{cn_count(len(segments['periods']))}季以前的 Azure 增速（新闻稿与 10-Q / 10-K 都印，但名称与口径随分部重划变过，"
        "接长要标出断点）；Copilot 每席位收入（公司未披露）、分地区收入、AI 年化收入（公司只在个别季度的电话会上给过，"
        "不是常规披露），以及未起租租约按年度的起租节奏（10-K 只给起租年份区间）。",
    ]

    sections = []
    if settled_charts:
        sections.append({
            "id": "settled",
            "title": "一、上季跟踪指标兑现了吗",
            "description": "".join([
                (f"先按本季分析第 0 节结清上季留下的 {sum(closure['counts'])} 条待验证问题；" if closure else ""),
                (f"再用本季读数结算上季分析{prior_kpi['section'].split('「')[0]}的 {prior_kpi['rows']} 行阈值，"
                 "每行的各档拆开，有序列的逐条画在各自的历史线上；" if prior_kpi else ""),
                ("最后是公司上季电话会给本季的指引 —— 微软不把指引写进任何申报文件，区间取自官方电话会逐字稿。"
                 if guidance_given else "微软的指引只在电话会上给，本季没有接入。"),
            ]),
            "exhibits": exhibits[: len(settled_charts)],
        })
    sections.append({
        "id": "quarter_highlights",
        "title": "二、本季重点",
        "description": (
            "本季分析第 1、2、3、7 节的结论里能用申报数画的：收入与分部结构、Intelligent Cloud 的毛利率拐点、"
            "剩余履约义务的近端可见度、两个财年的现金与股东回报，以及其他收入对税前利润的贡献。"
            + (f"分析的核心矛盾——自然年资本开支口径由约 US${guidance['cy2026_capex_prior_usd_bn']}B 改为约 "
               f"US${guidance['cy2026_capex_usd_bn']}B，只是折旧年限延长后融资租赁改列经营租赁（管理层说支出预期不变）"
               "——只有电话会上的两个口径数、没有可画的序列，写在下季指引表与第四板块的融资租赁图注里。" if guidance else "")
            + "分析对下一财年每股收益的推算是它自己的模型，本页不画。"
        ),
        "exhibits": exhibits[len(settled_charts): len(settled_charts) + len(highlights)],
    })
    if next_charts:
        sections.append({
            "id": "next_quarter",
            "title": "三、下季要跟踪什么",
            "description": next_description,
            "exhibits": exhibits[
                len(settled_charts) + len(highlights):
                len(settled_charts) + len(highlights) + len(next_charts)
            ],
        })
    sections.append({
        "id": "routine",
        "title": "四、长期常规跟踪",
        "description": ("MSFT 专属的常规序列：资本强度、利润率、折旧曲线、资本开支口径之外的融资租赁通道，"
                        "以及其他收入（净）的长期波幅。"),
        "exhibits": exhibits[-len(routine):],
    })

    return {
        "schema_version": "quarterly-dashboard/msft-v1",
        "page": {"slug": "msft", "language": "zh-CN"},
        "company": {
            "ticker": "MSFT",
            "name": "Microsoft",
            "group": "software_cloud",
            "accounting_standard": "US GAAP",
        },
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · MSFT",
        "title": f"Microsoft (MSFT)：{period} 季报仪表盘",
        "subtitle": (
            f"截至 {latest['period_end']}（微软 {fiscal_period}）· 发布 {latest['release_date']} · US GAAP · "
            f"{AUDIT_WORDS[latest['audit_status']]} · 金额单位为 $M，另有注明除外"
        ),
        "headline": headline,
        "brief": brief,
        "source": source,
        "source_url": "https://www.microsoft.com/en-us/investor",
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": sections,
        "tables": tables,
        "notes": notes,
        "footer": (
            "MSFT quarterly results · 数据来自 Microsoft 公开披露与透明自算 · "
            "仅供研究，不构成投资建议"
        ),
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "msft.js"), payload, "msft")
    shell_dir = ROOT / "msft"
    shell_dir.mkdir(exist_ok=True)
    # Rendered here, not at import: the shell stamps the payload's content
    # hash into its <script src>, so it has to be built after write_dash.
    (shell_dir / "index.html").write_text(
        render_shell("MSFT", "msft"), encoding="utf-8")
    exhibits = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"MSFT page: {exhibits} charts in {len(payload['sections'])} sections + "
          f"{len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
