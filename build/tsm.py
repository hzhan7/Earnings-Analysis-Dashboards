#!/usr/bin/env python3
"""Build the TSMC Q2 2026 quarterly-results dashboard.

The public payload contains only TSMC-reported figures, links to official
source material, and arithmetic that can be reproduced from the audit tables.
It intentionally omits ratings, valuation, consensus and local source paths.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "tsm.json"
DATA_DIR = ROOT / "data"
SHELL = render_shell("TSM", "tsm")


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100


def compact_period(period: str) -> str:
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


def summary_row(
    label: str,
    values: list[float],
    formatter,
    change: str = "pct",
    derived_values: bool = False,
) -> dict:
    current, previous, prior_year = values
    if change == "pp":
        qoq = signed(current - previous, 1, "pp")
        yoy = signed(current - prior_year, 1, "pp")
    elif change == "days":
        qoq = signed(current - previous, 0, "天")
        yoy = signed(current - prior_year, 0, "天")
    else:
        qoq = signed(pct_change(current, previous))
        yoy = signed(pct_change(current, prior_year))
    cells = [
        {
            "v": formatter(value),
            "cls": "cur" if index == 0 else "",
            "status": "derived" if derived_values else "reported",
        }
        for index, value in enumerate(values)
    ]
    cells.extend([
        {"v": qoq, "cls": "", "status": "derived"},
        {"v": yoy, "cls": "", "status": "derived"},
    ])
    return {"label": label, "cells": cells}


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    labels = [compact_period(period) for period in periods]
    financials = staging["financials"]
    technology = staging["technology_mix_pct"]
    platform = staging["platform_mix_pct"]
    cash = staging["cash_flow_ntd_bn"]
    working = staging["working_capital_days"]
    guide_history = staging["revenue_guidance_history_usd_bn"]
    snapshot = staging["current_snapshot"]
    guidance = staging["guidance"]

    source = (
        'Source: <a href="https://investor.tsmc.com/english/quarterly-results/2026/q2" '
        'rel="noopener">TSMC Investor Relations</a>（2Q26 earnings release、'
        'management report 与 earnings conference）。'
    )

    vis_residual = round(
        snapshot["non_operating_items_ntd_bn"][0]
        - snapshot["vis_disposal_and_mark_to_market_gain_pretax_ntd_bn"],
        2,
    )
    q3_midpoint = sum(guidance["q3_new"]["revenue_usd_bn"]) / 2
    q3_midpoint_growth = pct_change(q3_midpoint, guidance["q2_actual"]["revenue_usd_bn"])

    exhibits = [
        {
            "n": 2,
            "kind": "gs_bar",
            "title": "美元收入八季增长 71%，Q2 同比仍达 33.7%",
            "xlabels": labels,
            "values": financials["revenue_usd_bn"],
            "legend": "季度收入",
            "fmt": "usd1",
            "yfmt": "usd1",
            "label_fmt": "usd1",
            "ylab": "US$B",
            "ylab2": "同比增速",
            "yoy": {
                "name": "收入 YoY (RHS)",
                "values": financials["revenue_yoy_pct"],
                "color": "GREEN",
                "yfmt": "pct1",
            },
            "note": "Q2 收入 US$40.20B，环比 +12.0%、同比 +33.7%；八季累计增幅为 71.1%（D）。",
            "src_extra": "美元收入与同比来自各季 TSMC earnings release；八季累计增幅为自算。",
            "full": True,
        },
        {
            "n": 3,
            "kind": "lines",
            "title": "毛利率 67.7%、营业利润率 60.3%，均高于 Q2 指引上限",
            "xlabels": labels,
            "series": [
                {"name": "毛利率", "values": financials["gross_margin_pct"], "color": "NAVY"},
                {"name": "营业利润率", "values": financials["operating_margin_pct"], "color": "MBLUE"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "end_label": True,
            "ylab": "利润率",
            "note": "毛利率超原指引上限 0.2pp，营业利润率超 1.8pp；Q3 两项指引中值分别降至 66% 与 57%。",
            "src_extra": "利润率与指引来自 TSMC earnings release；相对指引上限的差额为自算。",
            "full": True,
        },
        {
            "n": 4,
            "kind": "lines",
            "title": "2nm 首次单列为 3%，7nm 及以下占比回到 77%",
            "xlabels": labels,
            "series": [
                {"name": "2nm", "values": technology["2nm"], "color": "GOLD"},
                {"name": "3nm", "values": technology["3nm"], "color": "NAVY"},
                {"name": "5nm", "values": technology["5nm"], "color": "MBLUE"},
                {"name": "7nm", "values": technology["7nm"], "color": "GRAY"},
            ],
            "fmt": "pct0",
            "yfmt": "pct0",
            "label_fmt": "pct0",
            "zero_base": True,
            "end_label": True,
            "ylab": "晶圆收入占比",
            "note": "2nm 首次单列为 3%，3nm 升至 30%；此前的 0 表示未单列或整数百分比舍入为零，不代表绝对没有收入。",
            "src_extra": "制程组合分母为 total wafer revenue，来自 TSMC 各季 management report。",
            "full": True,
        },
        {
            "n": 5,
            "kind": "lines",
            "title": "HPC 占比升至 66%，智能手机降至 22%",
            "xlabels": labels,
            "series": [
                {"name": "HPC", "values": platform["hpc"], "color": "NAVY"},
                {"name": "Smartphone", "values": platform["smartphone"], "color": "MBLUE"},
            ],
            "fmt": "pct0",
            "yfmt": "pct0",
            "label_fmt": "pct0",
            "zero_base": True,
            "end_label": True,
            "ylab": "净收入占比",
            "note": "Q2 HPC 环比增长 20%，Smartphone 环比下降 4%；收入结构继续向高性能计算集中。",
            "src_extra": "平台组合分母为 net revenue；占比与环比变化来自 2Q26 management report。",
            "full": True,
        },
        {
            "n": 6,
            "kind": "bars_labeled",
            "title": "Q2 非营业收益升至 NT$95.83B，VIS 相关收益贡献 NT$63.20B",
            "xlabels": ["Q1'26 非营业", "Q2'26 其他/残余 D", "Q2'26 VIS 相关"],
            "values": [
                snapshot["non_operating_items_ntd_bn"][1],
                vis_residual,
                snapshot["vis_disposal_and_mark_to_market_gain_pretax_ntd_bn"],
            ],
            "legend": "非营业项目",
            "fmt": "f1",
            "yfmt": "f1",
            "label_fmt": "f1",
            "ylab": "NT$B",
            "note": "Q2 后两柱合计 NT$95.83B；其他/残余 NT$32.63B = 95.83 − 63.20（D），不是公司定义的调整后利润。",
            "src_extra": "非营业项目总额与 VIS 股份出售及盯市收益来自 2Q26 management report。",
            "full": True,
        },
        {
            "n": 7,
            "kind": "grouped_bars",
            "title": "CapEx 环比增 41%，自由现金流反而下降 17.5%",
            "xlabels": labels,
            "groups": [
                {"name": "经营现金流", "values": cash["operating_cash_flow"], "color": "BLUE"},
                {"name": "资本开支", "values": cash["capital_expenditures"], "color": "NAVY"},
                {"name": "自由现金流 D", "values": cash["free_cash_flow"], "color": "MBLUE"},
            ],
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "NT$B",
            "bar_labels": False,
            "note": "Q2 经营现金流 NT$783.36B、现金支付 CapEx NT$496.00B；FCF = OCF − cash CapEx = NT$287.36B（D）。",
            "src_extra": "均为季度 NT$B 现金流口径，不与全年美元 CapEx 预算混用；FCF 按 TSMC 定义复算。",
            "full": True,
        },
        {
            "n": 8,
            "kind": "lines",
            "title": "N2 爬坡伴随库存天数回到 87 天，应收天数升至 29 天",
            "xlabels": labels,
            "series": [
                {"name": "库存天数", "values": working["inventory_days"], "color": "NAVY"},
                {"name": "应收天数", "values": working["receivable_days"], "color": "MBLUE"},
            ],
            "fmt": "f0",
            "yfmt": "f0",
            "label_fmt": "f0",
            "end_label": True,
            "ylab": "天",
            "note": "公司将库存天数上升主要归因于 N2 爬坡；应收天数环比增加 3 天。",
            "src_extra": "应收与库存天数来自各季 TSMC management report。",
            "full": True,
        },
        {
            "n": 9,
            "kind": "range_band",
            "title": "连续八季实际收入均达到或超过公司指引中点",
            "xlabels": labels,
            "lo": guide_history["low"],
            "hi": guide_history["high"],
            "actual": guide_history["actual"],
            "names": {"range": "公司收入指引区间", "actual": "实际收入"},
            "fmt": "usd1",
            "yfmt": "usd1",
            "label_fmt": "usd1",
            "ylab": "US$B",
            "bar_labels": False,
            "note": "八季实际收入全部不低于指引中点；其中六季达到或超过区间上端（D）。",
            "src_extra": "区间为各季度开始时公司给出的美元收入指引，实际值来自随后发布的 earnings release。",
            "full": True,
        },
    ]

    summary_rows = [
        summary_row("收入（美元）", snapshot["revenue_usd_bn"], lambda value: f"US${value:.2f}B"),
        summary_row("收入（新台币）", snapshot["revenue_ntd_bn"], lambda value: f"NT${value:,.2f}B"),
        summary_row("晶圆出货（12吋等值）", snapshot["wafer_shipments_kpcs_12in_equiv"], lambda value: f"{value / 1000:.3f}M"),
        summary_row("7nm 及以下占比", snapshot["advanced_mix_pct"], lambda value: f"{value:.0f}%", change="pp"),
        summary_row("HPC 占比", snapshot["hpc_mix_pct"], lambda value: f"{value:.0f}%", change="pp"),
        summary_row("毛利率", snapshot["gross_margin_pct"], lambda value: f"{value:.1f}%", change="pp"),
        summary_row("营业利润率", snapshot["operating_margin_pct"], lambda value: f"{value:.1f}%", change="pp"),
        summary_row("归母净利润", snapshot["net_income_ntd_bn"], lambda value: f"NT${value:,.2f}B"),
        summary_row("稀释 EPS", snapshot["eps_ntd"], lambda value: f"NT${value:.2f}"),
        summary_row("经营现金流", snapshot["operating_cash_flow_ntd_bn"], lambda value: f"NT${value:,.2f}B"),
        summary_row("资本开支", snapshot["capital_expenditures_ntd_bn"], lambda value: f"NT${value:,.2f}B"),
        summary_row("自由现金流", snapshot["free_cash_flow_ntd_bn"], lambda value: f"NT${value:,.2f}B", derived_values=True),
        summary_row("应收天数", snapshot["receivable_days"], lambda value: f"{value:.0f}天", change="days"),
        summary_row("库存天数", snapshot["inventory_days"], lambda value: f"{value:.0f}天", change="days"),
    ]

    guide_rows = [
        [
            "收入（美元）",
            "US$39.0–40.2B",
            "US$40.20B",
            "区间上端",
            "US$44.6–45.8B",
            f"中值 US${q3_midpoint:.1f}B；环比 {signed(q3_midpoint_growth)} D",
        ],
        ["毛利率", "65.5–67.5%", "67.7%", "高于上端 0.2pp D", "65.0–67.0%", "中值环比 -1.7pp D"],
        ["营业利润率", "56.5–58.5%", "60.3%", "高于上端 1.8pp D", "56.0–58.0%", "中值环比 -3.3pp D"],
        ["USD / NTD", "31.7", "31.60", "较假设低 0.3% D", "32.0", "较 Q2 实际高 1.3% D"],
        ["FY2026 美元收入增速", "高于 30%", "—", "上调", "略高于 40%", "公司年度 outlook"],
        ["FY2026 CapEx", "US$52–56B；接近上端", "—", "上调", "US$60–64B", "中值较先前高端锚点 +US$6B D"],
        ["2H26 N2 毛利率稀释", "—", "—", "—", "3–4pp", "管理层量化"],
        ["海外厂毛利率稀释", "—", "—", "—", "初期 2–3pp", "后期扩大至 3–4pp"],
    ]

    financial_table = []
    mix_table = []
    cash_table = []
    guidance_table = []
    for index, period in enumerate(periods):
        financial_table.append([
            period,
            f"US${financials['revenue_usd_bn'][index]:.2f}B",
            f"{financials['revenue_yoy_pct'][index]:.1f}%",
            f"{financials['gross_margin_pct'][index]:.1f}%",
            f"{financials['operating_margin_pct'][index]:.1f}%",
            f"NT${financials['eps_ntd'][index]:.2f}",
            f"{financials['wafer_shipments_kpcs_12in_equiv'][index] / 1000:.3f}M",
        ])
        mix_table.append([
            period,
            f"{technology['2nm'][index]:.0f}%",
            f"{technology['3nm'][index]:.0f}%",
            f"{technology['5nm'][index]:.0f}%",
            f"{technology['7nm'][index]:.0f}%",
            f"{technology['advanced_7nm_and_below'][index]:.0f}%",
            f"{platform['hpc'][index]:.0f}%",
            f"{platform['smartphone'][index]:.0f}%",
        ])
        cash_table.append([
            period,
            f"NT${cash['operating_cash_flow'][index]:,.2f}B",
            f"NT${cash['capital_expenditures'][index]:,.2f}B",
            f"NT${cash['free_cash_flow'][index]:,.2f}B D",
            f"{working['receivable_days'][index]}天",
            f"{working['inventory_days'][index]}天",
        ])
        midpoint = (guide_history["low"][index] + guide_history["high"][index]) / 2
        guidance_table.append([
            period,
            f"US${guide_history['low'][index]:.1f}–{guide_history['high'][index]:.1f}B",
            f"US${midpoint:.2f}B D",
            f"US${guide_history['actual'][index]:.2f}B",
            f"{signed(pct_change(guide_history['actual'][index], midpoint))} D",
        ])

    return {
        "schema_version": "quarterly-dashboard/tsm-v1",
        "page": {"slug": "tsm", "language": "zh-CN"},
        "company": {
            "ticker": "TSM",
            "name": "TSMC",
            "group": "semiconductor_ai",
            "accounting_standard": "TIFRS",
        },
        "latest": {
            "disclosed_period_label": "Q2 2026",
            "full_financial_period_label": "Q2 2026",
            "period_end": "2026-06-30",
            "release_date": "2026-07-16",
            "analysis_date": "2026-07-18",
            "audit_status": "unaudited",
            "status": "history_ready",
        },
        "tracker": "Watchlist Quarterly Tracker · TSM",
        "title": "TSMC (TSM)：Q2 2026 季报仪表盘",
        "subtitle": "截至 2026-06-30 · 发布 2026-07-16 · TIFRS · 未审计 · 收入为美元，现金流为新台币，另有注明除外",
        "headline": (
            "增长与利润率同时创新高，但真正变化是资本强度：HPC 占比升至 66%、毛利率 67.7%，"
            "同时单季 CapEx NT$496.00B 吞掉经营现金流增量，FCF 环比下降 17.5%。"
        ),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>增长</span><b>HPC 与先进制程继续抬升收入 mix</b>'
            '<p>收入 US$40.20B、环比 +12.0%；HPC 占 66%，2nm 首次单列为 3%。</p></article>'
            '<article><span>质量</span><b>主营利润率强，但净利润含一次性收益</b>'
            '<p>GM / OM 均超指引上限；VIS 税前相关收益 NT$63.20B 抬高非营业项目。</p></article>'
            '<article><span>资本</span><b>增长的现金成本进入更高台阶</b>'
            '<p>CapEx 环比 +41.4%，FCF 环比 -17.5%；全年 CapEx 上调至 US$60–64B。</p></article>'
            '</div>'
        ),
        "source": source,
        "source_url": "https://investor.tsmc.com/english/quarterly-results/2026/q2",
        "source_links": staging["sources"],
        "summary": {
            "blocks": [{
                "id": "quarterly",
                "title": "关键财务、制造与现金读数",
                "frequency": "quarterly",
                "heads": ["Q2 2026", "Q1 2026", "Q2 2025", "q/q", "y/y"],
                "sep": 3,
                "rows": summary_rows,
                "note": "D = Derived / 自算；变化列均为简单算术，当前季度仅用浅蓝底标识。",
            }]
        },
        "guidance": {
            "title": "Q2 兑现、Q3 指引与全年 outlook",
            "headers": ["指标", "Q2 原指引", "Q2 实际", "兑现", "Q3 / FY26 新口径", "变化 / 备注"],
            "rows": guide_rows,
            "note": "Q3 收入中值和所有区间差额标 D；公司指引不等同外部市场预期。",
        },
        "sections": [
            {
                "id": "growth_mix",
                "title": "增长、制程与平台结构",
                "description": "先确认收入增长，再看增长由多少先进制程与 HPC mix 支撑。",
                "exhibits": exhibits[0:4],
            },
            {
                "id": "quality_capital",
                "title": "盈利质量与资本强度",
                "description": "把主营利润率、一次性非营业收益和自由现金流拆开。",
                "exhibits": exhibits[4:6],
            },
            {
                "id": "leading_indicators",
                "title": "前瞻约束与兑现记录",
                "description": "营运资金显示爬坡成本，历史指引记录检验管理层兑现度。",
                "exhibits": exhibits[6:8],
            },
        ],
        "tables": [
            {
                "n": 10,
                "title": "八季度财务与晶圆出货",
                "headers": ["期间", "收入", "收入 YoY", "毛利率", "营业利润率", "稀释 EPS", "晶圆出货"],
                "rows": financial_table,
            },
            {
                "n": 11,
                "title": "八季度制程与平台收入组合",
                "headers": ["期间", "2nm", "3nm", "5nm", "7nm", "≤7nm", "HPC", "Smartphone"],
                "rows": mix_table,
            },
            {
                "n": 12,
                "title": "八季度现金流与营运资金",
                "headers": ["期间", "经营现金流", "资本开支", "自由现金流", "应收天数", "库存天数"],
                "rows": cash_table,
            },
            {
                "n": 13,
                "title": "八季度美元收入指引兑现",
                "headers": ["期间", "公司指引", "中值", "实际", "较中值"],
                "rows": guidance_table,
            },
        ],
        "notes": [
            "本页只发布公司披露值与可复算的简单派生值；D 标记代表 Derived / 自算。",
            "不发布评级、目标价、估值、卖方共识或未经 TSMC 确认的客户集中度估算。",
            "自由现金流按 TSMC 口径，以经营现金流减季度现金支付资本开支复算；不是利润表 non-GAAP 指标。",
            "VIS 相关收益为公司披露的股份出售及保留股份按市值重估收益；本页不假设税后影响，也不构造‘核心 EPS’。",
            "收入趋势采用美元口径，现金流采用新台币口径；季度现金支付 CapEx 不与全年美元 CapEx 预算相加。",
            "制程占比的分母为晶圆收入，平台占比的分母为净收入；两组 mix 不可直接相加。",
            "电话会文字稿仅链接 TSMC 官方 IR 托管版本，公开仓不复制原件或逐字内容。",
            "所有图均可切换为表格，数值与图表使用同一份静态 payload。",
        ],
        "footer": "TSM quarterly results · 数据来自 TSMC 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "tsm.js"), payload, "tsm")
    shell_dir = ROOT / "tsm"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(SHELL, encoding="utf-8")
    print("TSM dashboard: 8 charts + 1 scorecard + guidance + 4 audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
