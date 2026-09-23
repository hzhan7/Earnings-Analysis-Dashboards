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
    headroom,
    headroom_exhibit,
    latest_block,
    number_exhibits,
    stamped_block,
    threshold_exhibit,
    threshold_table,
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
    lease_commitment_ratio = fy["contracted_not_yet_commenced_leases"][-1] / fy["revenue"][-1] * 100
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

    # Azure revenue itself is never broken out in the statements, only its growth
    # rate, so the series has no statement-level identity to check against. The
    # annual growth figures in each 10-K are the one external anchor it has.
    azure_annual = staging["azure_growth_provenance"]["annual_crosscheck_pct"]
    azure_provenance = (
        "Azure 只披露增速、不披露收入，因此这条线没有报表恒等式可核；"
        "年度对照为 10-K 原句 "
        + "、".join(f"{year} +{value}%" for year, value in azure_annual.items())
        + "（报告口径）。"
    )

    # Three of these five run the ten-year record and two do not, and the split
    # is a disclosure split rather than a preference: Azure publishes a growth
    # rate and no revenue, so there is no filed series to lengthen; Intelligent
    # Cloud's *cost of revenue* -- the denominator of a segment gross margin --
    # is only in the last eight quarters of this file. The other three are
    # filed numbers or differences of filed numbers all the way back.
    long_opex_yoy = yoy(long["operating_expenses_usd_m"])
    long_buybacks = long["stock_repurchases_usd_m"]
    long_free_cash_flow = [
        operating - spend for operating, spend
        in zip(long["operating_cash_flow_usd_m"], long_capex)
    ]
    tracked = {
        "Azure 固定汇率增速": (seg_labels, azure, "pct0", "同比（固定汇率）", "Azure 增速"),
        "经营费用同比": (long_labels, long_opex_yoy, "pct1", "同比", "经营费用 YoY D"),
        "Intelligent Cloud 分部毛利率": (
            seg_labels, ic_gross_margin, "pct1", "分部毛利率", "IC 分部毛利率 D"),
        "单季回购金额": (long_labels, long_buybacks, "f0c", "$M", "单季回购"),
        "单季自由现金流（报告口径）": (
            long_labels, long_free_cash_flow, "f0c", "$M", "自由现金流 D"),
    }
    short_window = cn_count(len(seg_labels))
    FLOOR_NOTE = {
        "Azure 固定汇率增速": f"这条线只有{short_window}季，因为微软只公布 Azure 的增速、不公布它的收入，"
                          "没有可以往回拉的申报序列。",
        "Intelligent Cloud 分部毛利率": f"这条线只有{short_window}季，因为分部**销货成本**只在最近{short_window}季里，"
                                  "而它是这个毛利率的分母。",
    }

    def tracking_charts(entries, value_key, threshold_label, headline) -> list[dict]:
        charts = []
        for entry in entries:
            metric = entry["metric"]
            if metric not in tracked:
                continue
            metric_labels, values, fmt, ylab, actual_name = tracked[metric]
            side = "上方" if entry["direction"] == "up" else "下方"
            reported = [value for value in values if value is not None]
            unsafe = ((lambda value: value < entry["threshold"])
                      if entry["direction"] == "up"
                      else (lambda value: value > entry["threshold"]))
            crossed = sum(1 for value in reported if unsafe(value))
            charts.append(threshold_exhibit(
                headline(entry),
                metric_labels,
                values,
                entry["threshold"],
                fmt=fmt,
                ylab=ylab,
                actual_name=actual_name,
                threshold_name=f"{threshold_label}（安全侧在{side}）",
                xstep=LONG_STEP if len(metric_labels) > 16 else None,
                note=(
                    f"阈值 {unit_text(entry['unit'], entry['threshold'])}，"
                    f"当前 {unit_text(entry['unit'], entry[value_key])}，"
                    f"余量 {headroom(entry['direction'], entry['threshold'], entry[value_key]):+.1f}%。"
                    f"这条线自己的记录有 {len(reported)} 个季度，"
                    f"其中 {crossed} 个落在阈值的不安全一侧。"
                    + FLOOR_NOTE.get(metric, "")
                ),
                src_extra=(
                    "实际值来自各期 10-Q / 10-K 与当季 earnings release；"
                    "阈值为本地研究设定，不是公司指引。"
                    + (azure_provenance if metric == "Azure 固定汇率增速" else "")
                ),
            ))
        return charts

    def margin_of(entry: dict, value_key: str) -> float:
        return headroom(entry["direction"], entry["threshold"], entry[value_key])

    # ── section one ──────────────────────────────────────────────────────────
    settled_charts: list[dict] = []
    if closure is not None:
        counts = dict(zip(closure["labels"], closure["counts"]))
        disclosures = closure.get("ai_run_rate_disclosures", [])
        note_words = {}
        if len(disclosures) >= 2:
            first, last = disclosures[-2], disclosures[-1]
            gap = (int(last["period"][-4:]) * 4 + int(last["period"][1])) - \
                  (int(first["period"][-4:]) * 4 + int(first["period"][1]))
            note_words = {"gap": cn_count(gap), "latest": f"${last['usd_bn']:g}B",
                          "first_period": first["period"], "first": f"${first['usd_bn']:g}B"}
        settled_charts.append({
            "kind": "bars_labeled",
            "title": (
                f"上季 {sum(closure['counts'])} 条待验证问题："
                + "、".join(f"{count} 条{label}" for label, count in counts.items())
            ),
            "xlabels": closure["labels"],
            "values": closure["counts"],
            "legend": "问题条数",
            "fmt": "f0",
            "yfmt": "f0",
            "label_fmt": "f0",
            "ylab": "条",
            "note": closure["note"].format(**note_words),
            "src_extra": (
                "问题清单来自上季本地分析稿的 follow-up；验证结果依据本季 earnings release、"
                f"电话会与 {fiscal_year} {'10-K' if fiscal_period.endswith('Q4') else '10-Q'}。"
            ),
        })
    if prior_kpi is not None:
        entries = prior_kpi["quantified"]
        broken = [entry for entry in entries if margin_of(entry, "actual") < 0]
        guided = [entry for entry in entries if entry.get("threshold_is_company_guide")]
        if not broken:
            verdict = f"上季 {len(entries)} 条量化阈值全部守住"
            if guided and all(entry["actual"] > entry["threshold"] for entry in guided):
                verdict += f"，其中{cn_count(len(guided))}条的阈值就是公司自己的指引"
        else:
            verdict = (f"上季 {len(entries)} 条量化阈值：{len(entries) - len(broken)} 条守住、"
                       f"{len(broken)} 条被击穿")
        azure_entry = next((entry for entry in entries if entry["metric"] == "Azure 固定汇率增速"), None)
        bookings_entry = next((entry for entry in entries if "签约额" in entry["metric"]), None)
        low, high = prior_kpi.get("azure_guide_pct", (None, None))
        lead = ""
        operating_clean = all(margin_of(entry, "actual") >= 0 for entry in entries if entry["kind"] == "operating")
        if operating_clean and azure_entry and low is not None and azure_entry["actual"] > high:
            beat_low, beat_high = azure_entry["actual"] - high, azure_entry["actual"] - low
            lead = prior_kpi["lead"].format(
                azure_beat=f"{beat_low:.0f}–{beat_high:.0f}pt" if beat_low != beat_high else f"{beat_low:.0f}pt",
                cloud_guide=f"{prior_kpi['cloud_gross_margin_guide_pct']:g}",
                bookings=f"{bookings_entry['actual']:+.0f}%" if bookings_entry else "",
                count=cn_count(len(entries)),
            )
        retired = prior_kpi.get("retired", [])
        settled_charts.append(headroom_exhibit(
            verdict,
            entries,
            "actual",
            "正值 = 仍在安全侧。" + lead,
            src_extra=(
                "阈值为上季本地研究设定，不是公司指引；实际值为本季披露值。"
                + (f"另有{cn_count(len(retired))}条上季指标已退役："
                   + "、".join(f"{item['short']}（{item['reason']}）" for item in retired) + "。"
                   if retired else "")
            ),
        ))
        settled_charts += tracking_charts(
            [entry for entry in entries
             if entry["metric"] in ("Azure 固定汇率增速", "经营费用同比")],
            "actual",
            "上季阈值",
            lambda entry: (
                f"{entry['metric']}："
                f"{'守住' if margin_of(entry, 'actual') >= 0 else '已击穿'}"
                f"上季阈值 {unit_text(entry['unit'], entry['threshold'])}"
            ),
        )

    # ── section two ──────────────────────────────────────────────────────────
    reported_yoy = [v for v in long_revenue_yoy if v is not None]
    upper_quartile = sorted(reported_yoy)[int(0.75 * len(reported_yoy))]
    ic, pbp, mpc = (segments["intelligent_cloud_revenue"], segments["productivity_revenue"],
                    segments["more_personal_computing_revenue"])
    ic_first_lead = ic[-1] > pbp[-1] and all(a <= b for a, b in zip(ic[:-1], pbp[:-1]))
    segment_growth = [pct_change(line[-1], line[-5]) for line in (ic, pbp, mpc)]
    mpc_margin = [income / sales * 100 for income, sales in
                  zip(segments["more_personal_computing_operating_income"], mpc)]
    ic_cost_yoy = pct_change(segments["intelligent_cloud_cost_of_revenue"][-1],
                             segments["intelligent_cloud_cost_of_revenue"][-5])
    ic_revenue_yoy = pct_change(ic[-1], ic[-5])
    rpo = kpi["commercial_rpo"]
    rpo_levels = rpo["level_usd_bn"]
    year_ago_label = f"{period.split()[0]} {int(period.split()[1]) - 1}"
    rpo_yoy = (pct_change(rpo_levels[-1], rpo_levels[rpo["periods"].index(year_ago_label)])
               if year_ago_label in rpo["periods"] else None)
    near_yoy = (rpo.get("twelve_month_portion_yoy_pct") or [None])[-1]
    ex_largest = (rpo.get("ex_largest_customer_yoy_pct") or [None])[-1]
    filing_years = segments["filings"]
    other_by_fy_start = quarters.index(f"{int(this_fy[2:]) - 1}Q3") if f"{int(this_fy[2:]) - 1}Q3" in quarters else None
    last_fy_other = (sum(long_other_income[other_by_fy_start - 4:other_by_fy_start])
                     if other_by_fy_start and other_by_fy_start >= 4 else None)
    quiet_end = quarters.index("2022Q4") + 1
    quiet = long_other_income[:quiet_end]
    recent = long_other_income[quiet_end:]
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
                (f"Intelligent Cloud 本季首次超过 Productivity：" if ic_first_lead else
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
            ),
            "src_extra": (
                f"分部收入取自 {filing_years} 各期 10-Q / 10-K 的重述后可比列，{cn_count(len(ic))}季口径一致；同比为自算。"
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
            "xlabels": [compact_period(p) for p in rpo["periods"]],
            "values": rpo_levels,
            "legend": "商业 RPO 余额",
            "fmt": "usd0",
            "yfmt": "usd0",
            "label_fmt": "usd0",
            "ylab": "US$B",
            "note": (
                (f"余额同比 {rpo_yoy:+.0f}%，" if rpo_yoy is not None else "")
                + (f"{'但 ' if rpo_yoy is not None and near_yoy < rpo_yoy else ''}12 个月内可确认的部分"
                   f"{'只' if rpo_yoy is not None and near_yoy < rpo_yoy else ''}同比 {near_yoy:+.0f}%，"
                   if near_yoy is not None else "")
                + f"占比由约 {rpo['twelve_month_share_pct'][0]}% "
                f"{'降' if rpo['twelve_month_share_pct'][-1] < rpo['twelve_month_share_pct'][0] else '升'}到约 "
                f"{rpo['twelve_month_share_pct'][-1]}%"
                + (f"；剔除单一大客户后余额同比仅 {ex_largest:+.0f}%，"
                   + ("低于" if ex_largest < azure[-1] else "不低于") + " Azure 自身的增速。"
                   if ex_largest is not None else "。")
            ),
            "src_extra": (
                "余额与 12 个月内确认比例来自各季 earnings call 与 10-Q；"
                "占比一列口径不完全一致，已在源数据中注明，故本页只画余额、不画占比曲线。"
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
                f"${withholding[-1]:,}M，那是股权激励的结算，不计入。"
            ),
            "src_extra": (
                "经营现金流、现金资本开支、回购与分红来自现金流量表；计划内回购来自 10-K 股东权益附注；"
                "未付资本开支来自 10-K 的物业及设备附注。调整后口径为报告值减该余额的年度增量，是算术调整，不是公司定义的指标。"
            ),
        },
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
    next_charts: list[dict] = []
    if next_kpi is not None:
        entries = next_kpi["quantified"]
        below = [entry for entry in entries if margin_of(entry, "current") < 0]
        operating_safe = all(margin_of(entry, "current") >= 0 for entry in entries if entry["kind"] == "operating")
        if not below:
            state = "当前值全部在安全侧"
        elif operating_safe and len(below) == 1 and below[0]["kind"] == "cash":
            state = "经营类全部在安全侧，被击穿的是现金分配那条"
        else:
            state = f"{len(entries) - len(below)} 条在安全侧，{len(below)} 条已越线"
        coverage_entry = next((entry for entry in entries if entry["metric"].startswith("股东回报")), None)
        lease_entry = next((entry for entry in entries if entry["metric"].startswith("已签约未起租")), None)
        note = "正值 = 仍在安全侧。"
        if coverage_entry is not None:
            if margin_of(coverage_entry, "current") < 0:
                note += ("唯一为负的是股东回报对调整后自由现金流的覆盖：" if len(below) == 1 else
                         "股东回报对调整后自由现金流的覆盖已越线：")
                note += (f"{this_fy} 为 {return_coverage[-1]:.1f}%，即回购加分红已经超过真实自由现金流，"
                         "差额由现金储备与供应商账期补足。")
            else:
                note += (f"股东回报对调整后自由现金流的覆盖 {this_fy} 为 {return_coverage[-1]:.1f}%"
                         f"（{last_fy} {return_coverage[-2]:.1f}%），离 "
                         f"{coverage_entry['threshold']:.0f}% 的阈值还有 "
                         f"{coverage_entry['threshold'] - return_coverage[-1]:.1f}pp。")
        if lease_entry is not None:
            lease_gap = margin_of(lease_entry, "current")
            note += (f"已签约未起租的租约余额 "
                     f"US${fy['contracted_not_yet_commenced_leases'][-1] / 1000:.1f}B "
                     f"相当于全年收入的 {lease_commitment_ratio:.1f}%"
                     + ("，仅一步之遥。" if 0 <= lease_gap < 2 else "。"))
        gated = next_kpi.get("disclosure_gated", [])
        next_charts.append(headroom_exhibit(
            f"下季 {len(entries)} 条量化阈值：{state}",
            entries,
            "current",
            note,
            src_extra=(
                f"阈值为本地研究设定，不是公司指引；当前值为本季或 {this_fy} 实际。"
                + (f"另有 {len(gated)} 条需等披露才能判定（"
                   + "、".join(item["short"] for item in gated) + "）。" if gated else "")
            ),
        ))
        next_charts += tracking_charts(
            entries,
            "current",
            "下季阈值",
            lambda entry: (
                f"{entry['metric']}：下季阈值 {unit_text(entry['unit'], entry['threshold'])}，"
                f"当前 {unit_text(entry['unit'], entry['current'])}"
            ),
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
                + (f"；下季指引仍在 {guidance['capex_next_quarter']}。" if guidance else "。")
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
                + (f"<b>八季的窗口会把这段读成下滑（{cn_count(len(eight_gm) - 1)}次环比里{cn_count(eight_falls)}次下降），"
                   "十年的窗口说的是另一回事</b>："
                   if eight_falls < len(eight_gm) - 1 else
                   "<b>八季的窗口会把这段读成单向下滑，十年的窗口说的是另一回事</b>：")
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
        fy_row("已签约但尚未起租的租约", "contracted_not_yet_commenced_leases"),
        fy_row("现金及短期投资", "cash_and_short_term_investments"),
    ]

    guidance_rows = []
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
            ["下季 More Personal Computing", f"${mpc[-1]:,}M（本季实际）",
             f"US${guidance['more_personal_computing_usd_m'][0] / 1000:.2f}–{guidance['more_personal_computing_usd_m'][1] / 1000:.2f}B",
             ("继续下滑，" if mpc_guide_growth < 0 else "恢复增长，") + remarks.get("more_personal_computing", "")],
            ["下季资本开支", f"${capex[-1]:,}M（本季现金口径）", guidance["capex_next_quarter"],
             remarks.get("capex", "")],
            [f"FY{int(fiscal_year[2:]) + 1} 收入", "—", guidance["fy2027_revenue"], remarks.get("fy2027_revenue", "")],
            [f"FY{int(fiscal_year[2:]) + 1} 营业利润率", "—", guidance["fy2027_operating_margin"],
             remarks.get("fy2027_operating_margin", "")],
            [f"FY{int(fiscal_year[2:]) + 1} 自由现金流", "—", guidance["fy2027_free_cash_flow"],
             remarks.get("fy2027_free_cash_flow", "")],
            ["自然年 2026 资本开支", f"约 US${guidance['cy2026_capex_prior_usd_bn']}B",
             f"约 US${guidance['cy2026_capex_usd_bn']}B", guidance["capex_restatement_reason"]],
            ["数据中心与办公楼折旧年限",
             f"{guidance['useful_life_years'][0]} 年", f"{guidance['useful_life_years'][1]} 年",
             remarks.get("useful_life", "")],
        ]

    kpi_rows = [
        ["商业剩余履约义务", "US$B",
         " / ".join(f"{value}" for value in rpo["level_usd_bn"]),
         " / ".join(rpo["periods"])],
        ["其中 12 个月内可确认占比", "%",
         " / ".join(f"{value}" for value in rpo["twelve_month_share_pct"]),
         rpo["share_note"]],
        ["M365 Copilot 付费席位", "百万",
         " / ".join(f"{value}" for value in kpi["copilot_paid_seats_m"]["values"]),
         " / ".join(kpi["copilot_paid_seats_m"]["periods"])],
        ["Microsoft Cloud 收入", "US$B",
         " / ".join(f"{value:.1f}" for value in kpi["microsoft_cloud"]["revenue_usd_bn"]),
         " / ".join(kpi["microsoft_cloud"]["periods"])],
        ["Microsoft Cloud 毛利率", "%",
         " / ".join(f"{value}" for value in kpi["microsoft_cloud"]["gross_margin_pct"]),
         " / ".join(kpi["microsoft_cloud"]["periods"])],
        ["商业签约额（剔除单一大客户）同比", "%",
         " / ".join(f"{value}" for value in kpi["bookings_ex_largest_customer_yoy_pct"]["values"]),
         " / ".join(kpi["bookings_ex_largest_customer_yoy_pct"]["periods"])],
    ]

    tables = []
    if prior_kpi is not None:
        tables.append(threshold_table(0, "上季阈值与本季实际（原单位）",
                                      prior_kpi["quantified"], "actual", f"{period} 实际"))
    if next_kpi is not None:
        tables.append(threshold_table(0, "下季阈值与当前值（原单位）",
                                      next_kpi["quantified"], "current", "当前值"))
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
        operating_words.append("Intelligent Cloud 收入首次超过 Productivity")
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
        + (f"财报当日股价 {signed(consensus['post_earnings_price_change_pct'], 0)}。" if consensus else "")
    )
    low, high = (prior_kpi or {}).get("azure_guide_pct", (None, None))
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
        + ('<article><span>结构</span><b>Intelligent Cloud 首次成为最大分部</b>' if ic_first_lead and ic[-1] >= max(pbp[-1], mpc[-1])
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
    if prior_kpi is not None and next_kpi is not None:
        settled_bar = next(ex for ex in settled_charts if ex["kind"] == "diverging_bars")
        notes.append(f"Exhibit {settled_bar['n']} 与 Exhibit {next_charts[0]['n']} 的阈值是本地研究设定，"
                     "不是公司指引，也不构成评级或投资建议；「距阈值余量」统一为正值代表安全侧。")
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
        "更早期间因分部重述不可直接连接。",
        "融资租赁新增与现金资本开支在本页不相加：前者的本金偿付走筹资活动，后者走投资活动，"
        "两者对自由现金流的影响路径不同。",
        "季度折旧按公司披露精度到 $100M"
        + (f"；{guidance['useful_life_effective']} 起数据中心与办公楼的估计可使用年限由 "
           f"{guidance['useful_life_years'][0]} 年延长至 {guidance['useful_life_years'][1]} 年，"
           "折旧曲线的下一段与历史不可比。" if guidance else "。"),
        "本页已知未接入：Microsoft Cloud 收入与毛利率的完整八季序列、Copilot 每席位收入、"
        "分地区收入、AI 年化收入（公司已停止披露），以及未起租租约按年度的起租节奏。",
    ]

    sections = []
    if settled_charts:
        sections.append({
            "id": "settled",
            "title": "一、上季跟踪指标兑现了吗",
            "description": "先结算上季留下的问题与阈值，再看本季数据——本季的关键正在于阈值没有覆盖的地方。",
            "exhibits": exhibits[: len(settled_charts)],
        })
    sections.append({
        "id": "quarter_highlights",
        "title": "二、本季重点",
        "description": "收入与分部结构、Intelligent Cloud 的毛利率拐点、剩余履约义务的近端可见度，以及两个财年的现金对照。",
        "exhibits": exhibits[len(settled_charts): len(settled_charts) + len(highlights)],
    })
    if next_charts:
        sections.append({
            "id": "next_quarter",
            "title": "三、下季要跟踪什么",
            "description": "同一套口径向前看：当前值离下季阈值还有多远，统一用「距阈值余量」表示。",
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
