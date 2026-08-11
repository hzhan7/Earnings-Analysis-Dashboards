#!/usr/bin/env python3
"""Build the MSFT quarterly-results page.

Same four-part, chart-led shape as the other company pages (上季兑现 → 本季重点
→ 下季跟踪 → 长期常规).  Everything on this page is labelled by calendar
quarter, not by Microsoft's fiscal quarter: the site compares four companies
side by side, and a page whose "Q2 2026" means a different three months from
every neighbouring page is worse than no comparison at all.  Q2 2026 here is
the quarter ended 2026-06-30, which Microsoft reports as FY2026 Q4.

The routine series are the ones that decide this company right now.  The
operating story (Azure re-accelerating, the segment gross margin turning up for
the first time in five quarters) and the cash story (reported free cash flow
falling 6.5% while the same year's free cash flow adjusted for capex still
sitting in accounts payable falls 31.6%) point in opposite directions, so the
page carries both rather than netting them into one number.

Published numbers are company-reported or transparent arithmetic.  Market
expectations are labelled as such, with no broker attribution.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import (  # noqa: E402
    ai_capex_cycle_table,
    headroom,
    headroom_exhibit,
    number_exhibits,
    threshold_exhibit,
    threshold_table,
    unit_text,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "msft.json"
DATA_DIR = ROOT / "data"

WINDOW = 8


def compact_period(period: str) -> str:
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


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


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    labels = [compact_period(period) for period in shown(periods)]
    q = staging["quarterly_usd_m"]
    segments = staging["segments_usd_m"]
    kpi = staging["operating_kpi"]
    fy = staging["fiscal_year_usd_m"]
    guidance = staging["guidance"]
    consensus = staging["market_expectation"]
    closure = staging["followup_closure"]
    prior_kpi = staging["prior_kpi_settlement"]
    next_kpi = staging["next_kpi"]

    revenue = q["revenue_total"]
    revenue_shown = shown(revenue)
    revenue_yoy = shown(yoy(revenue))
    gross_margin = [
        profit / total * 100 for profit, total in zip(shown(q["gross_profit"]), revenue_shown)
    ]
    operating_margin = [
        income / total * 100 for income, total in zip(shown(q["operating_income"]), revenue_shown)
    ]
    opex_yoy = shown(yoy(q["operating_expenses"]))

    capex = shown(q["cash_paid_for_property_and_equipment"])
    capex_intensity = [value / total * 100 for value, total in zip(capex, revenue_shown)]
    free_cash_flow = [
        operating - spend
        for operating, spend in zip(
            shown(q["operating_cash_flow"]), capex
        )
    ]
    buybacks = shown(q["stock_repurchases"])
    depreciation = shown(q["depreciation"])
    depreciation_ratio = [
        value / total * 100 for value, total in zip(depreciation, revenue_shown)
    ]
    finance_leases = shown(q["finance_lease_additions"])
    other_income = shown(q["other_income_expense_net"])

    # Intelligent Cloud is the only segment that publishes its own cost of
    # revenue every quarter, which makes its gross margin the one AI-mix series
    # on this page that needs no management-defined aggregate.
    ic_gross_margin = [
        (revenue_value - cost) / revenue_value * 100
        for revenue_value, cost in zip(
            segments["intelligent_cloud_revenue"], segments["intelligent_cloud_cost_of_revenue"]
        )
    ]

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
    shareholder_returns = [
        repurchase + dividend
        for repurchase, dividend in zip(fy["stock_repurchases"], fy["dividends_paid"])
    ]
    return_coverage = [
        returns / adjusted * 100 for returns, adjusted in zip(shareholder_returns, adjusted_fy_fcf)
    ]
    lease_commitment_ratio = fy["contracted_not_yet_commenced_leases"][-1] / fy["revenue"][-1] * 100

    guidance_revenue_mid = sum(guidance["revenue_usd_m"]) / 2
    guidance_revenue_yoy = pct_change(guidance_revenue_mid, revenue[-4])

    source = (
        'Source: <a href="https://www.microsoft.com/en-us/investor" rel="noopener">'
        'Microsoft Investor Relations</a>（FY2026 Q4 earnings release 与电话会；'
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
        f"年度对照为 10-K 原句 FY2025 +{azure_annual['FY2025']}%、FY2026 +{azure_annual['FY2026']}%（报告口径）。"
    )

    tracked = {
        "Azure 固定汇率增速": (
            staging["azure_growth_cc_pct"], "pct0", "同比（固定汇率）", "Azure 增速",
        ),
        "经营费用同比": (opex_yoy, "pct1", "同比", "经营费用 YoY D"),
        "Intelligent Cloud 分部毛利率": (ic_gross_margin, "pct1", "分部毛利率", "IC 分部毛利率 D"),
        "单季回购金额": (buybacks, "f0c", "$M", "单季回购"),
        "单季自由现金流（报告口径）": (free_cash_flow, "f0c", "$M", "自由现金流 D"),
    }

    def tracking_charts(entries, value_key, threshold_label, headline) -> list[dict]:
        charts = []
        for entry in entries:
            metric = entry["metric"]
            if metric not in tracked:
                continue
            values, fmt, ylab, actual_name = tracked[metric]
            side = "上方" if entry["direction"] == "up" else "下方"
            charts.append(threshold_exhibit(
                headline(entry),
                labels,
                values,
                entry["threshold"],
                fmt=fmt,
                ylab=ylab,
                actual_name=actual_name,
                threshold_name=f"{threshold_label}（安全侧在{side}）",
                note=(
                    f"阈值 {unit_text(entry['unit'], entry['threshold'])}，"
                    f"当前 {unit_text(entry['unit'], entry[value_key])}，"
                    f"余量 {headroom(entry['direction'], entry['threshold'], entry[value_key]):+.1f}%。"
                ),
                src_extra=(
                    "实际值来自各期 10-Q / 10-K 与当季 earnings release；"
                    "阈值为本地研究设定，不是公司指引。"
                    + (azure_provenance if metric == "Azure 固定汇率增速" else "")
                ),
            ))
        return charts

    settled_charts = [
        {
            "kind": "bars_labeled",
            "title": "上季 5 条待验证问题：2 条已验证、2 条部分验证、1 条被证伪",
            "xlabels": closure["labels"],
            "values": closure["counts"],
            "legend": "问题条数",
            "fmt": "f0",
            "yfmt": "f0",
            "label_fmt": "f0",
            "ylab": "条",
            "note": (
                "被证伪的是「AI 年化收入会成为常态披露」——上季首次给出后本季完全消失，"
                "新闻稿、年报与全部问答里都没有再出现，本页据此把该指标退役而非外推。"
            ),
            "src_extra": (
                "问题清单来自上季本地分析稿的 follow-up；验证结果依据本季 earnings release、"
                "电话会与 FY2026 10-K。"
            ),
        },
        headroom_exhibit(
            "上季 6 条量化阈值全部守住，其中两条是被自己的指引大幅超越",
            prior_kpi["quantified"],
            "actual",
            (
                "正值 = 仍在安全侧。经营层面这是干净的一季：Azure 超出自身指引 3–4pt，"
                "云毛利率好于「约 64%」的指引，剔除单一大客户的签约额同比 +18%。"
                "本季的问题不在这六条里，而在它们没有覆盖的现金口径。"
            ),
            src_extra=(
                "阈值为上季本地研究设定，不是公司指引；实际值为本季披露值。"
                "另有三条上季指标已退役：商业 RPO 总额（被单一大客户合约主导）、"
                "单季报告口径自由现金流（未捕捉未付资本开支）、AI 年化收入（已停止披露）。"
            ),
        ),
    ]
    settled_charts += tracking_charts(
        [entry for entry in prior_kpi["quantified"]
         if entry["metric"] in ("Azure 固定汇率增速", "经营费用同比")],
        "actual",
        "上季阈值",
        lambda entry: (
            f"{entry['metric']}："
            f"{'守住' if headroom(entry['direction'], entry['threshold'], entry['actual']) >= 0 else '已击穿'}"
            f"上季阈值 {unit_text(entry['unit'], entry['threshold'])}"
        ),
    )

    highlights = [
        {
            "kind": "gs_bar",
            "title": (
                f"收入 ${revenue_shown[-1]:,.0f}M、同比 {revenue_yoy[-1]:.1f}%，"
                f"下季指引中点隐含 {signed(guidance_revenue_yoy)}"
            ),
            "xlabels": labels,
            "values": revenue_shown,
            "legend": "总收入",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "ylab2": "同比增速",
            "yoy": {
                "name": "同比增速 (RHS)",
                "values": revenue_yoy,
                "color": "GREEN",
                "yfmt": "pct1",
            },
            "note": (
                f"高于市场预期区间 ${consensus['revenue_usd_m_range'][0]:,}–"
                f"{consensus['revenue_usd_m_range'][1]:,}M；两个公开来源相差 $1,750M，"
                "因此本页只确认「超预期方向」，不发布超预期幅度。"
            ),
            "src_extra": source_note("收入来自各期 10-Q / 10-K；同比与下季隐含同比为自算"),
        },
        {
            "kind": "lines",
            "title": (
                f"Intelligent Cloud 本季首次超过 Productivity："
                f"${segments['intelligent_cloud_revenue'][-1]:,}M vs "
                f"${segments['productivity_revenue'][-1]:,}M"
            ),
            "xlabels": labels,
            "series": [
                {"name": "Intelligent Cloud", "values": segments["intelligent_cloud_revenue"], "color": "NAVY"},
                {"name": "Productivity & Business Processes", "values": segments["productivity_revenue"], "color": "MBLUE"},
                {"name": "More Personal Computing", "values": segments["more_personal_computing_revenue"], "color": "GRAY"},
            ],
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "zero_base": True,
            "end_label": True,
            "ylab": "$M",
            "note": (
                f"三条线彻底分道：IC 同比 "
                f"{pct_change(segments['intelligent_cloud_revenue'][-1], segments['intelligent_cloud_revenue'][-5]):+.1f}%，"
                f"PBP {pct_change(segments['productivity_revenue'][-1], segments['productivity_revenue'][-5]):+.1f}%，"
                f"MPC {pct_change(segments['more_personal_computing_revenue'][-1], segments['more_personal_computing_revenue'][-5]):+.1f}%；"
                f"MPC 的分部经营利润率同时从 "
                f"{segments['more_personal_computing_operating_income'][-2] / segments['more_personal_computing_revenue'][-2] * 100:.1f}% 掉到 "
                f"{segments['more_personal_computing_operating_income'][-1] / segments['more_personal_computing_revenue'][-1] * 100:.1f}%。"
            ),
            "src_extra": (
                "分部收入取自 FY2026 各期 10-Q / 10-K 的重述后可比列，八季口径一致；同比为自算。"
            ),
        },
        {
            "kind": "gs_line",
            "title": (
                f"Intelligent Cloud 分部毛利率连降五季后首次回升至 {ic_gross_margin[-1]:.2f}%"
            ),
            "xlabels": labels,
            "values": ic_gross_margin,
            "legend": "IC 分部毛利率 D",
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "ylab": "分部毛利率",
            "note": (
                f"环比 {ic_gross_margin[-1] - ic_gross_margin[-2]:+.2f}pp，"
                f"但同比仍 {ic_gross_margin[-1] - ic_gross_margin[-5]:+.2f}pp；"
                "分部收入成本同比增速仍快于分部收入，结构性压力只是被减速、没有被逆转。"
            ),
            "src_extra": (
                "分部收入与分部收入成本来自各期 10-Q / 10-K 的分部附注，毛利率为两者相除的自算值，"
                "不是公司披露的 Microsoft Cloud 毛利率。"
            ),
        },
        {
            "kind": "bars_labeled",
            "title": (
                f"商业剩余履约义务升至 US${kpi['commercial_rpo']['level_usd_bn'][-1]}B，"
                "但 12 个月内可确认的比例才是近端可见度"
            ),
            "xlabels": [compact_period(period) for period in kpi["commercial_rpo"]["periods"]],
            "values": kpi["commercial_rpo"]["level_usd_bn"],
            "legend": "商业 RPO 余额",
            "fmt": "usd0",
            "yfmt": "usd0",
            "label_fmt": "usd0",
            "ylab": "US$B",
            "note": (
                f"余额同比 +84%，但 12 个月内可确认的部分只同比 +37%，"
                f"占比由约 {kpi['commercial_rpo']['twelve_month_share_pct'][0]}% 降到约 "
                f"{kpi['commercial_rpo']['twelve_month_share_pct'][-1]}%；"
                "剔除单一大客户后余额同比仅 +25%，低于 Azure 自身的增速。"
            ),
            "src_extra": (
                "余额与 12 个月内确认比例来自各季 earnings call 与 10-Q；"
                "占比一列口径不完全一致，已在源数据中注明，故本页只画余额、不画占比曲线。"
            ),
        },
        {
            "kind": "grouped_bars",
            "title": (
                f"FY2026 股东回报已达调整后自由现金流的 {return_coverage[-1]:.1f}%"
            ),
            "xlabels": fy["labels"],
            "groups": [
                {"name": "自由现金流（报告口径）D", "values": reported_fy_fcf, "color": "BLUE"},
                {"name": "自由现金流（扣未付资本开支）D", "values": adjusted_fy_fcf, "color": "NAVY"},
                {"name": "股东回报现金（回购 + 分红）", "values": shareholder_returns, "color": "GOLD"},
            ],
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "bar_labels": False,
            "note": (
                f"年报披露仍留在应付账款里的资本开支由 ${fy['unpaid_capex_in_payables'][0]:,}M 升到 "
                f"${fy['unpaid_capex_in_payables'][1]:,}M，扣掉这 "
                f"${fy['unpaid_capex_in_payables'][1] - fy['unpaid_capex_in_payables'][0]:,}M 增量后，"
                f"FY2026 自由现金流同比 {pct_change(adjusted_fy_fcf[1], adjusted_fy_fcf[0]):+.1f}%，"
                f"而报告口径只有 {pct_change(reported_fy_fcf[1], reported_fy_fcf[0]):+.1f}%。"
            ),
            "src_extra": (
                "经营现金流、现金资本开支、回购与分红来自现金流量表；未付资本开支来自 10-K 的"
                "物业及设备附注。调整后口径为报告值减该余额的年度增量，是算术调整，不是公司定义的指标。"
            ),
        },
        {
            "kind": "diverging_bars",
            "title": (
                f"其他收入（净）八季在 -$3,660M 与 +$9,971M 之间摆动，本季 "
                f"{'+' if other_income[-1] >= 0 else '-'}${abs(other_income[-1]):,}M"
            ),
            "xlabels": labels,
            "values": other_income,
            "legend": "其他收入（净）",
            "positive_label": "净收益",
            "negative_label": "净损失",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "zero_line": True,
            "note": (
                "这条线几乎全部是非现金的权益法与估值变动，方向可逆——同一套会计方法在上一财年产生的是净损失。"
                "跨期比较 GAAP 每股收益会被它系统性带偏，本页因此把经营利润与现金流放在前面。"
            ),
            "src_extra": source_note("其他收入（净）来自各期利润表；本页不拆分其中的单笔投资"),
        },
    ]

    next_charts = [
        headroom_exhibit(
            "下季 6 条量化阈值：经营类全部在安全侧，被击穿的是现金分配那条",
            next_kpi["quantified"],
            "current",
            (
                f"正值 = 仍在安全侧。唯一为负的是股东回报对调整后自由现金流的覆盖："
                f"FY2026 为 {return_coverage[-1]:.1f}%，即回购加分红已经超过真实自由现金流，"
                f"差额由现金储备与供应商账期补足。已签约未起租的租约余额 "
                f"US${fy['contracted_not_yet_commenced_leases'][-1] / 1000:.1f}B "
                f"相当于全年收入的 {lease_commitment_ratio:.1f}%，仅一步之遥。"
            ),
            src_extra=(
                "阈值为本地研究设定，不是公司指引；当前值为本季或 FY2026 实际。"
                "另有 4 条需等披露才能判定（折旧年限变更的实际影响、未付资本开支走向、"
                "Copilot 每席位收入、AI 年化收入是否恢复披露）。"
            ),
        ),
    ]
    next_charts += tracking_charts(
        next_kpi["quantified"],
        "current",
        "下季阈值",
        lambda entry: (
            f"{entry['metric']}：下季阈值 {unit_text(entry['unit'], entry['threshold'])}，"
            f"当前 {unit_text(entry['unit'], entry['current'])}"
        ),
    )

    routine = [
        {
            "kind": "gs_bar",
            "title": (
                f"现金资本开支 ${capex[-1]:,.0f}M、占收入 {capex_intensity[-1]:.1f}%，"
                f"八季从 {capex_intensity[0]:.1f}% 一路抬升"
            ),
            "xlabels": labels,
            "values": capex,
            "legend": "现金支付的物业及设备",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "ylab2": "占收入比",
            "yoy": {
                "name": "现金 CapEx / 收入 (RHS) D",
                "values": capex_intensity,
                "color": "GOLD",
                "yfmt": "pct1",
            },
            "note": (
                f"同比 {pct_change(capex[-1], capex[-5]):+.1f}%；下季指引仍在 "
                f"{guidance['capex_next_quarter']}。这条线只含已付现的部分，"
                "口径与本站其他公司页的现金资本开支一致，可直接横向比较。"
            ),
            "src_extra": source_note("现金资本开支来自各期现金流量表；占收入比为自算"),
        },
        {
            "kind": "lines",
            "title": (
                f"毛利率八季从 {gross_margin[0]:.1f}% 降到 {gross_margin[-1]:.1f}%，"
                f"营业利润率 {operating_margin[-1]:.1f}%"
            ),
            "xlabels": labels,
            "series": [
                {"name": "毛利率", "values": gross_margin, "color": "NAVY"},
                {"name": "营业利润率", "values": operating_margin, "color": "MBLUE"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "end_label": True,
            "ylab": "利润率",
            "note": (
                f"下季指引隐含毛利率约 "
                f"{(guidance_revenue_mid - sum(guidance['cost_of_revenue_usd_m']) / 2) / guidance_revenue_mid * 100:.1f}%，"
                "较去年同期再降约 2pp；公司对 FY2027 的口径是「营业利润率同比下降不足 1 个百分点」。"
            ),
            "src_extra": source_note("毛利率与营业利润率按利润表口径自算，指引隐含值取区间中点"),
        },
        {
            "kind": "gs_bar",
            "title": (
                f"季度折旧 ${depreciation[-1]:,.0f}M、占收入 {depreciation_ratio[-1]:.1f}%，"
                f"八季翻了一倍以上"
            ),
            "xlabels": labels,
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
                f"FY2026 折旧 ${fy['depreciation'][1]:,}M，较 FY2025 的 ${fy['depreciation'][0]:,}M 增 "
                f"{pct_change(fy['depreciation'][1], fy['depreciation'][0]):.0f}%。"
                f"数据中心与办公楼的估计可使用年限自 FY2027 起由 {guidance['useful_life_years'][0]} 年延长到 "
                f"{guidance['useful_life_years'][1]} 年，这条线的下一段斜率因此不再可比。"
            ),
            "src_extra": source_note("季度折旧来自各期现金流量表，按公司披露精度到 $100M；占收入比为自算"),
        },
        {
            "kind": "gs_bar",
            "title": (
                f"融资租赁新增八季合计 ${sum(finance_leases):,.0f}M，是资本开支口径之外的第二条通道"
            ),
            "xlabels": labels,
            "values": finance_leases,
            "legend": "融资租赁新增",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "note": (
                f"FY2026 新增 ${fy['finance_lease_additions'][1]:,}M。年限延长后，一份 15 年期数据中心租约"
                "占资产经济寿命的比例下降，会从融资租赁重分类为经营租赁——公司口径的自然年资本开支"
                f"因此由约 US${guidance['cy2026_capex_prior_usd_bn']}B 调整为约 "
                f"US${guidance['cy2026_capex_usd_bn']}B，而管理层同时说明支出预期本身没有变。"
            ),
            "src_extra": (
                "融资租赁新增为「以租赁负债交换的使用权资产」，来自各期现金流量表的补充披露；"
                "本页不把它与现金资本开支相加，因为两者的现金路径不同。"
            ),
        },
    ]

    exhibits = number_exhibits(settled_charts + highlights + next_charts + routine)
    first_table = len(exhibits) + 2

    quarterly_rows = []
    for index, period in enumerate(periods):
        quarterly_rows.append([
            period,
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
    for index, period in enumerate(segments["periods"]):
        segment_rows.append([
            period,
            f"${segments['productivity_revenue'][index]:,}M",
            f"{segments['productivity_operating_income'][index] / segments['productivity_revenue'][index] * 100:.1f}% D",
            f"${segments['intelligent_cloud_revenue'][index]:,}M",
            f"{segments['intelligent_cloud_operating_income'][index] / segments['intelligent_cloud_revenue'][index] * 100:.1f}% D",
            f"{ic_gross_margin[index]:.2f}% D",
            f"${segments['more_personal_computing_revenue'][index]:,}M",
            f"{segments['more_personal_computing_operating_income'][index] / segments['more_personal_computing_revenue'][index] * 100:.1f}% D",
            f"{staging['azure_growth_cc_pct'][index]:+d}%",
        ])

    fy_rows = [
        ["收入", f"${fy['revenue'][0]:,}M", f"${fy['revenue'][1]:,}M",
         f"{pct_change(fy['revenue'][1], fy['revenue'][0]):+.1f}%"],
        ["经营利润", f"${fy['operating_income'][0]:,}M", f"${fy['operating_income'][1]:,}M",
         f"{pct_change(fy['operating_income'][1], fy['operating_income'][0]):+.1f}%"],
        ["经营现金流", f"${fy['operating_cash_flow'][0]:,}M", f"${fy['operating_cash_flow'][1]:,}M",
         f"{pct_change(fy['operating_cash_flow'][1], fy['operating_cash_flow'][0]):+.1f}%"],
        ["现金资本开支", f"${fy['cash_paid_for_property_and_equipment'][0]:,}M",
         f"${fy['cash_paid_for_property_and_equipment'][1]:,}M",
         f"{pct_change(fy['cash_paid_for_property_and_equipment'][1], fy['cash_paid_for_property_and_equipment'][0]):+.1f}%"],
        ["融资租赁新增", f"${fy['finance_lease_additions'][0]:,}M", f"${fy['finance_lease_additions'][1]:,}M",
         f"{pct_change(fy['finance_lease_additions'][1], fy['finance_lease_additions'][0]):+.1f}%"],
        ["自由现金流（报告口径）D", f"${reported_fy_fcf[0]:,.0f}M", f"${reported_fy_fcf[1]:,.0f}M",
         f"{pct_change(reported_fy_fcf[1], reported_fy_fcf[0]):+.1f}%"],
        ["计入应付账款的未付资本开支", f"${fy['unpaid_capex_in_payables'][0]:,}M",
         f"${fy['unpaid_capex_in_payables'][1]:,}M",
         f"{pct_change(fy['unpaid_capex_in_payables'][1], fy['unpaid_capex_in_payables'][0]):+.1f}%"],
        ["自由现金流（扣未付资本开支增量）D", f"${adjusted_fy_fcf[0]:,.0f}M", f"${adjusted_fy_fcf[1]:,.0f}M",
         f"{pct_change(adjusted_fy_fcf[1], adjusted_fy_fcf[0]):+.1f}%"],
        ["回购", f"${fy['stock_repurchases'][0]:,}M", f"${fy['stock_repurchases'][1]:,}M",
         f"{pct_change(fy['stock_repurchases'][1], fy['stock_repurchases'][0]):+.1f}%"],
        ["分红", f"${fy['dividends_paid'][0]:,}M", f"${fy['dividends_paid'][1]:,}M",
         f"{pct_change(fy['dividends_paid'][1], fy['dividends_paid'][0]):+.1f}%"],
        ["股东回报 / 调整后自由现金流 D", f"{return_coverage[0]:.1f}%", f"{return_coverage[1]:.1f}%",
         f"{return_coverage[1] - return_coverage[0]:+.1f}pp"],
        ["折旧", f"${fy['depreciation'][0]:,}M", f"${fy['depreciation'][1]:,}M",
         f"{pct_change(fy['depreciation'][1], fy['depreciation'][0]):+.1f}%"],
        ["已签约但尚未起租的租约", f"${fy['contracted_not_yet_commenced_leases'][0]:,}M",
         f"${fy['contracted_not_yet_commenced_leases'][1]:,}M",
         f"{pct_change(fy['contracted_not_yet_commenced_leases'][1], fy['contracted_not_yet_commenced_leases'][0]):+.1f}%"],
        ["现金及短期投资", f"${fy['cash_and_short_term_investments'][0]:,}M",
         f"${fy['cash_and_short_term_investments'][1]:,}M",
         f"{pct_change(fy['cash_and_short_term_investments'][1], fy['cash_and_short_term_investments'][0]):+.1f}%"],
    ]

    guidance_rows = [
        ["下季总收入", "—",
         f"US${guidance['revenue_usd_m'][0] / 1000:.2f}–{guidance['revenue_usd_m'][1] / 1000:.2f}B",
         f"中点 ${guidance_revenue_mid:,.0f}M，隐含同比 {signed(guidance_revenue_yoy)} D"],
        ["下季 Azure（固定汇率）", f"{staging['azure_growth_cc_pct'][-1]}%（本季实际）",
         f"约 +{guidance['azure_cc_growth_pct']}%", "首次给出「上半财年逐季加速」的口径"],
        ["下季 Intelligent Cloud", f"${segments['intelligent_cloud_revenue'][-1]:,}M（本季实际）",
         f"US${guidance['intelligent_cloud_usd_m'][0] / 1000:.2f}–{guidance['intelligent_cloud_usd_m'][1] / 1000:.2f}B",
         "分部指引增速高于本季实际增速"],
        ["下季 More Personal Computing", f"${segments['more_personal_computing_revenue'][-1]:,}M（本季实际）",
         f"US${guidance['more_personal_computing_usd_m'][0] / 1000:.2f}–{guidance['more_personal_computing_usd_m'][1] / 1000:.2f}B",
         "继续下滑，主因个人电脑零部件涨价与渠道库存"],
        ["下季资本开支", f"${capex[-1]:,}M（本季现金口径）", guidance["capex_next_quarter"],
         "含融资租赁重分类之后仍高于 US$50B"],
        ["FY2027 收入", "—", guidance["fy2027_revenue"], "定性口径，可建模性偏低"],
        ["FY2027 营业利润率", "—", guidance["fy2027_operating_margin"], "首次给出"],
        ["FY2027 自由现金流", "—", guidance["fy2027_free_cash_flow"],
         "只给了零下限措辞，本季可建模性最差的一项"],
        ["自然年 2026 资本开支", f"约 US${guidance['cy2026_capex_prior_usd_bn']}B",
         f"约 US${guidance['cy2026_capex_usd_bn']}B", guidance["capex_restatement_reason"]],
        ["数据中心与办公楼折旧年限",
         f"{guidance['useful_life_years'][0]} 年", f"{guidance['useful_life_years'][1]} 年",
         "自 FY2027 起生效；管理层称对 FY2027 经营利润影响很小，但未给金额"],
    ]

    kpi_rows = [
        ["商业剩余履约义务", "US$B",
         " / ".join(f"{value}" for value in kpi["commercial_rpo"]["level_usd_bn"]),
         " / ".join(kpi["commercial_rpo"]["periods"])],
        ["其中 12 个月内可确认占比", "%",
         " / ".join(f"{value}" for value in kpi["commercial_rpo"]["twelve_month_share_pct"]),
         kpi["commercial_rpo"]["share_note"]],
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

    tables = [
        threshold_table(
            first_table,
            "上季阈值与本季实际（原单位）",
            prior_kpi["quantified"],
            "actual",
            "Q2 2026 实际",
        ),
        threshold_table(
            first_table + 1,
            "下季阈值与当前值（原单位）",
            next_kpi["quantified"],
            "current",
            "当前值",
        ),
        {
            "n": first_table + 2,
            "title": "下季与 FY2027 指引",
            "headers": ["指标", "上季 / 本季实际", "新口径", "变化 / 备注"],
            "rows": guidance_rows,
        },
        {
            "n": first_table + 3,
            "title": "两个财政年度的现金与股东回报（FY2025 = 截至 2025-06-30）",
            "headers": ["指标", "FY2025", "FY2026", "变化"],
            "rows": fy_rows,
        },
        {
            "n": first_table + 4,
            "title": "八季度分部收入、分部利润率与 Azure 增速",
            "headers": ["期间", "PBP 收入", "PBP 利润率", "IC 收入", "IC 利润率", "IC 毛利率",
                        "MPC 收入", "MPC 利润率", "Azure（固定汇率）"],
            "rows": segment_rows,
        },
        {
            "n": first_table + 5,
            "title": "十二季度基础数据（前四季只用于计算同比）",
            "headers": ["期间", "总收入", "毛利", "经营利润", "经营费用", "其他收入（净）",
                        "经营现金流", "现金资本开支", "自由现金流 D", "融资租赁新增", "回购", "折旧"],
            "rows": quarterly_rows,
        },
        {
            "n": first_table + 6,
            "title": "披露不连续的运营指标（只在公司给出的期间存在）",
            "headers": ["指标", "单位", "已披露值", "对应期间 / 口径说明"],
            "rows": kpi_rows,
        },
        ai_capex_cycle_table(first_table + 7),
    ]

    return {
        "schema_version": "quarterly-dashboard/msft-v1",
        "page": {"slug": "msft", "language": "zh-CN"},
        "company": {
            "ticker": "MSFT",
            "name": "Microsoft",
            "group": "software_cloud",
            "accounting_standard": "US GAAP",
        },
        "latest": {
            "disclosed_period_label": "Q2 2026",
            "full_financial_period_label": "Q2 2026（FY2026 Q4）",
            "period_end": "2026-06-30",
            "release_date": "2026-07-29",
            "analysis_date": "2026-07-30",
            "audit_status": "audited",
            "status": "history_ready",
        },
        "tracker": "Watchlist Quarterly Tracker · MSFT",
        "title": "Microsoft (MSFT)：Q2 2026 季报仪表盘",
        "subtitle": (
            "截至 2026-06-30（微软 FY2026 Q4）· 发布 2026-07-29 · US GAAP · 已审计 · "
            "金额单位为 $M，另有注明除外"
        ),
        "headline": (
            f"经营端确实更强了——Azure 固定汇率增速由 {staging['azure_growth_cc_pct'][-2]}% 加速到 "
            f"{staging['azure_growth_cc_pct'][-1]}%，Intelligent Cloud 收入首次超过 Productivity，"
            "分部毛利率五季来首次回升；但财务端同时在恶化："
            f"FY2026 报告口径自由现金流同比 {pct_change(reported_fy_fcf[1], reported_fy_fcf[0]):.1f}%，"
            f"扣掉仍留在应付账款里的 ${fy['unpaid_capex_in_payables'][1] - fy['unpaid_capex_in_payables'][0]:,}M "
            f"未付资本开支后是 {pct_change(adjusted_fy_fcf[1], adjusted_fy_fcf[0]):.1f}%，"
            f"股东回报已占到调整后自由现金流的 {return_coverage[-1]:.1f}%。"
            f"财报当日股价 {signed(consensus['post_earnings_price_change_pct'], 0)}。"
        ),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>亮点</span><b>Azure 加速且分部毛利率转向</b>'
            f'<p>固定汇率 +{staging["azure_growth_cc_pct"][-1]}%，超自身指引 3–4pt；'
            f'IC 分部毛利率环比 {ic_gross_margin[-1] - ic_gross_margin[-2]:+.2f}pp。</p></article>'
            '<article><span>结构</span><b>Intelligent Cloud 首次成为最大分部</b>'
            f'<p>${segments["intelligent_cloud_revenue"][-1]:,}M vs '
            f'${segments["productivity_revenue"][-1]:,}M；MPC 同比 '
            f'{pct_change(segments["more_personal_computing_revenue"][-1], segments["more_personal_computing_revenue"][-5]):.1f}%。</p></article>'
            '<article><span>存疑</span><b>回报已超过真实自由现金流</b>'
            f'<p>调整后 ${adjusted_fy_fcf[1]:,.0f}M，股东回报 ${shareholder_returns[1]:,}M，'
            f'覆盖率 {return_coverage[-1]:.1f}%。</p></article>'
            '</div>'
        ),
        "source": source,
        "source_url": "https://www.microsoft.com/en-us/investor",
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {
                "id": "settled",
                "title": "一、上季跟踪指标兑现了吗",
                "description": "先结算上季留下的问题与阈值，再看本季数据——本季的关键正在于阈值没有覆盖的地方。",
                "exhibits": exhibits[: len(settled_charts)],
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": "收入与分部结构、Intelligent Cloud 的毛利率拐点、剩余履约义务的近端可见度，以及两个财年的现金对照。",
                "exhibits": exhibits[len(settled_charts): len(settled_charts) + len(highlights)],
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": "同一套口径向前看：当前值离下季阈值还有多远，统一用「距阈值余量」表示。",
                "exhibits": exhibits[
                    len(settled_charts) + len(highlights):
                    len(settled_charts) + len(highlights) + len(next_charts)
                ],
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": "MSFT 专属的常规序列：资本强度、利润率、折旧曲线，以及资本开支口径之外的融资租赁通道。",
                "exhibits": exhibits[-len(routine):],
            },
        ],
        "tables": tables,
        "notes": [
            "本页统一用自然年季度标注：Q2 2026 指截至 2026-06-30 的季度，微软自己称之为 FY2026 Q4；"
            "FY2026 指截至 2026-06-30 的财政年度。这样标注是为了与本站其他公司页逐季可比。",
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            f"Exhibit 3 与 Exhibit {len(settled_charts) + len(highlights) + 2} 的阈值是本地研究设定，"
            "不是公司指引，也不构成评级或投资建议；「距阈值余量」统一为正值代表安全侧。",
            "本页只发布公司披露值、可复算的简单派生值，以及明确标注的市场预期；D 标记代表 Derived / 自算。",
            "市场预期一律标注为「市场预期」并给出取数时点，不写卖方机构名，也不发布评级、目标价或估值。"
            "本季两个公开来源的收入预期相差 $1,750M，因此本页只发布区间与超预期方向，不发布超预期幅度。",
            "自由现金流（报告口径）= 经营现金流 − 现金支付的物业及设备，与公司口径一致；"
            "调整后口径再减去年报披露的「仍计入应付账款的物业及设备采购」的年度增量，是算术调整，"
            "不是公司定义的 non-GAAP 指标。",
            "Intelligent Cloud 分部毛利率为分部收入减分部收入成本后相除的自算值，不等同公司披露的 Microsoft Cloud 毛利率；"
            "后者只在核对表中按公司给出的期间列示。",
            "分部数据取自 FY2026 各期 10-Q / 10-K 的重述后可比列，八季口径一致；更早期间因分部重述不可直接连接。",
            "融资租赁新增与现金资本开支在本页不相加：前者的本金偿付走筹资活动，后者走投资活动，"
            "两者对自由现金流的影响路径不同。",
            "季度折旧按公司披露精度到 $100M；FY2027 起数据中心与办公楼的估计可使用年限由 15 年延长至 25 年，"
            "折旧曲线的下一段与历史不可比。",
            "本页已知未接入：Microsoft Cloud 收入与毛利率的完整八季序列、Copilot 每席位收入、"
            "分地区收入、AI 年化收入（公司已停止披露），以及未起租租约按年度的起租节奏。",
        ],
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
    print(f"MSFT page: {exhibits} charts in 4 sections + {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
