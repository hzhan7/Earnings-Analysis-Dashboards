#!/usr/bin/env python3
"""Build the TSMC Q2 2026 quarterly-results page.

Same two-layer shape as the GOOGL page: a tracking board carrying thresholds and
trigger actions, then a fixed operating panel that keeps the eight-quarter view
stable from quarter to quarter.  The public payload contains only TSMC-reported
figures, links to official source material, and arithmetic that can be
reproduced from the panel.  It intentionally omits ratings, valuation, consensus
and local source paths.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import board_block, board_row, panel_group, panel_row  # noqa: E402
from build.googl import cross_capex_table  # noqa: E402
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "tsm.json"
DATA_DIR = ROOT / "data"
SHELL = render_shell("TSM", "tsm")

PANEL_HEADS = ["Q2 2026", "Q1 2026", "Q2 2025", "q/q", "y/y"]


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


def trend_row(label: str, values: list, formatter, derived: bool = False) -> dict:
    return panel_row(
        label,
        ["—" if value is None else formatter(value) for value in values],
        derived,
    )


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

    # Implied ASP is the cheapest honest volume/price split available: the two
    # inputs are both reported every quarter, and it separates "more wafers" from
    # "richer wafers" without any assumption about node pricing.
    shipments = financials["wafer_shipments_kpcs_12in_equiv"]
    asp = [
        financials["revenue_usd_bn"][index] * 1_000_000 / shipments[index]
        for index in range(len(periods))
    ]
    asp_yoy = [None] * 4 + [pct_change(asp[i], asp[i - 4]) for i in range(4, len(periods))]
    shipment_yoy = [None] * 4 + [
        pct_change(shipments[i], shipments[i - 4]) for i in range(4, len(periods))
    ]

    vis_residual = round(
        snapshot["non_operating_items_ntd_bn"][0]
        - snapshot["vis_disposal_and_mark_to_market_gain_pretax_ntd_bn"],
        2,
    )
    q3_midpoint = sum(guidance["q3_new"]["revenue_usd_bn"]) / 2
    q3_midpoint_growth = pct_change(q3_midpoint, guidance["q2_actual"]["revenue_usd_bn"])
    q3_gm_midpoint = sum(guidance["q3_new"]["gross_margin_pct"]) / 2
    implied_monthly_ntd = q3_midpoint * guidance["q3_new"]["usd_ntd"] / 3

    revenue_ntd_yoy = pct_change(snapshot["revenue_ntd_bn"][0], snapshot["revenue_ntd_bn"][2])
    capex_ntd_yoy = pct_change(
        snapshot["capital_expenditures_ntd_bn"][0], snapshot["capital_expenditures_ntd_bn"][2]
    )
    shipment_qoq = pct_change(shipments[-1], shipments[-2])
    net_margin = [
        snapshot["net_income_ntd_bn"][index] / snapshot["revenue_ntd_bn"][index] * 100
        for index in range(3)
    ]
    gm_floor = guidance["long_term_gross_margin_floor_pct"]

    # --- layer 2: tracking board -------------------------------------------
    board = board_block(
        [
            board_row(
                "月度营收 vs 当季指引隐含月均",
                f"本页未接入月度数据；Q3 指引中值 US${q3_midpoint:.1f}B、汇率假设 "
                f"{guidance['q3_new']['usd_ntd']:.1f} → 隐含月均 NT${implied_monthly_ntd:,.0f}B D",
                "单月低于隐含月均 10% 且连续两月",
                "待接入后再判定",
                "na",
            ),
            board_row(
                "毛利率与稀释项目对账",
                f"Q2 实际 {financials['gross_margin_pct'][-1]:.1f}%（超原指引上限 "
                f"{financials['gross_margin_pct'][-1] - guidance['q2_prior']['gross_margin_pct'][1]:.1f}pp）；"
                f"Q3 指引中值 {q3_gm_midpoint:.1f}%；2H26 N2 稀释 "
                f"{guidance['n2_h2_gross_margin_dilution_pp'][0]}–{guidance['n2_h2_gross_margin_dilution_pp'][1]}pp、"
                f"海外厂后期 {guidance['overseas_fab_gross_margin_dilution_latter_pp'][0]}–"
                f"{guidance['overseas_fab_gross_margin_dilution_latter_pp'][1]}pp",
                "实际低于当季指引中值，且管理层上调稀释幅度",
                "警示",
                "watch",
            ),
            board_row(
                "收入增速 vs CapEx 增速",
                f"新台币口径：收入同比 {signed(revenue_ntd_yoy)}、CapEx 同比 {signed(capex_ntd_yoy)} D",
                "连续两季 CapEx 增速高于收入增速",
                "重估资本强度与 FCF 路径",
                "hit",
            ),
            board_row(
                "FY2026 CapEx 指引修订",
                f"US${guidance['fy2026_capex_usd_bn'][0]}–{guidance['fy2026_capex_usd_bn'][1]}B"
                f"（前次 US${guidance['fy2026_capex_prior_usd_bn'][0]}–"
                f"{guidance['fy2026_capex_prior_usd_bn'][1]}B 并指向上端）",
                "再度上修，且全年收入增速口径未同步上修",
                "警示",
                "watch",
            ),
            board_row(
                "库存天数 × 晶圆出货",
                f"库存 {working['inventory_days'][-1]} 天"
                f"（环比 {working['inventory_days'][-1] - working['inventory_days'][-2]:+d} 天）；"
                f"出货 {shipments[-1] / 1000:.3f}M，环比 {signed(shipment_qoq)} D",
                "库存天数连续两季上升，且出货环比走平或转负",
                "警示",
                "watch",
            ),
            board_row(
                "N3 毛利率 crossover",
                "管理层指向 2H 2026；本页尚无按节点的毛利率披露",
                "至 Q4 2026 仍未确认即视为承诺滑期",
                "跟踪",
                "pending",
            ),
            board_row(
                "平台集中度",
                f"HPC {platform['hpc'][-1]}%（八季最高）、Smartphone {platform['smartphone'][-1]}%（八季最低）",
                "HPC > 70%，或非 HPC 平台合计 < 30%",
                "跟踪集中度风险",
                "watch",
            ),
            board_row(
                "毛利率 vs 长期 through-cycle 目标",
                f"{financials['gross_margin_pct'][-1]:.1f}% vs 目标 {gm_floor}% 及以上，"
                f"高出 {financials['gross_margin_pct'][-1] - gm_floor:.1f}pp D",
                "公司下修任一长期目标（毛利率 / ROE / 收入 CAGR）",
                "重估",
                "ok",
            ),
        ],
        "阈值为本地研究设定，不是公司指引，也不是评级；状态灯只反映该行阈值的机械判定。"
        "当前值均可由下方经营面板复算。",
    )

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
        },
        {
            "n": 4,
            "kind": "gs_bar",
            "title": f"量价同步：八季出货 +{pct_change(shipments[-1], shipments[0]):.0f}%、隐含 ASP +{pct_change(asp[-1], asp[0]):.0f}%",
            "xlabels": labels,
            "values": shipments,
            "legend": "晶圆出货（12 吋等值）",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "千片",
            "ylab2": "隐含 ASP（美元 / 片）",
            "yoy": {
                "name": "隐含 ASP（美元/片，RHS） D",
                "values": asp,
                "color": "GOLD",
                "yfmt": "f0c",
            },
            "note": (
                f"隐含 ASP = 季度美元收入 / 晶圆出货（自算），Q2 为 ${asp[-1]:,.0f}/片；"
                "八季增长中量与价的贡献大致相当，不是单靠涨价。"
            ),
            "src_extra": (
                "出货量与美元收入均来自各季 TSMC earnings release / management report；"
                "隐含 ASP 是两者相除的自算值，不是公司披露的定价指标，也不区分制程与封装口径。"
            ),
        },
        {
            "n": 5,
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
        },
        {
            "n": 6,
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
            "src_extra": (
                "平台组合分母为 net revenue；本页仅接入 HPC 与 Smartphone 两类，"
                "IoT / 汽车 / DCE 尚未接入。"
            ),
        },
        {
            "n": 7,
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
        },
        {
            "n": 8,
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
        },
        {
            "n": 9,
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
        },
        {
            "n": 10,
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
        },
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
        [
            "长期 through-cycle 毛利率",
            f"{gm_floor}% 及以上",
            "67.7%",
            f"高出 {financials['gross_margin_pct'][-1] - gm_floor:.1f}pp D",
            f"{gm_floor}% 及以上",
            "长期目标未上修，也未下修",
        ],
    ]

    # --- layer 1: the fixed operating panel --------------------------------
    panel_groups = [
        panel_group(
            "trend_scale",
            "八季趋势 · 规模与量价",
            labels,
            [
                trend_row("收入（美元）", financials["revenue_usd_bn"], lambda v: f"US${v:.2f}B"),
                trend_row("收入 YoY", financials["revenue_yoy_pct"], lambda v: f"{v:+.1f}%"),
                trend_row("晶圆出货（12 吋等值）", shipments, lambda v: f"{v / 1000:.3f}M"),
                trend_row("出货 YoY", shipment_yoy, lambda v: f"{v:+.1f}%", derived=True),
                trend_row("隐含 ASP", asp, lambda v: f"${v:,.0f}", derived=True),
                trend_row("隐含 ASP YoY", asp_yoy, lambda v: f"{v:+.1f}%", derived=True),
            ],
            "隐含 ASP = 季度美元收入 / 晶圆出货（自算），只作量价拆分参考，不是公司披露的定价指标；"
            "同比列自第五季起才有四季前的可比基数。",
            open_by_default=True,
        ),
        panel_group(
            "trend_margin",
            "八季趋势 · 盈利",
            labels,
            [
                trend_row("毛利率", financials["gross_margin_pct"], lambda v: f"{v:.1f}%"),
                trend_row("营业利润率", financials["operating_margin_pct"], lambda v: f"{v:.1f}%"),
                trend_row("稀释 EPS", financials["eps_ntd"], lambda v: f"NT${v:.2f}"),
            ],
            "净利率与 ROE 目前只有本季与对比季，未接入八季序列；EPS 为新台币口径。",
            open_by_default=True,
        ),
        panel_group(
            "trend_mix",
            "八季趋势 · 制程与平台组合",
            labels,
            [
                trend_row("2nm", technology["2nm"], lambda v: f"{v:.0f}%"),
                trend_row("3nm", technology["3nm"], lambda v: f"{v:.0f}%"),
                trend_row("5nm", technology["5nm"], lambda v: f"{v:.0f}%"),
                trend_row("7nm", technology["7nm"], lambda v: f"{v:.0f}%"),
                trend_row("7nm 及以下", technology["advanced_7nm_and_below"], lambda v: f"{v:.0f}%"),
                trend_row("HPC", platform["hpc"], lambda v: f"{v:.0f}%"),
                trend_row("Smartphone", platform["smartphone"], lambda v: f"{v:.0f}%"),
            ],
            "制程占比的分母为晶圆收入，平台占比的分母为净收入，两组不可直接相加；"
            "IoT / 汽车 / DCE 与地区组合尚未接入。",
        ),
        panel_group(
            "trend_cash",
            "八季趋势 · 现金流与营运资金",
            labels,
            [
                trend_row("经营现金流", cash["operating_cash_flow"], lambda v: f"NT${v:,.2f}B"),
                trend_row("资本开支", cash["capital_expenditures"], lambda v: f"NT${v:,.2f}B"),
                trend_row("自由现金流", cash["free_cash_flow"], lambda v: f"NT${v:,.2f}B", derived=True),
                trend_row("应收天数", working["receivable_days"], lambda v: f"{v:.0f}天"),
                trend_row("库存天数", working["inventory_days"], lambda v: f"{v:.0f}天"),
            ],
            "现金流为新台币口径；八季新台币收入尚未接入，因此 CapEx/收入、FCF/收入 两项比率暂不提供。",
        ),
        panel_group(
            "trend_guidance",
            "八季趋势 · 美元收入指引兑现",
            labels,
            [
                panel_row(
                    "公司指引区间",
                    [
                        f"US${low:.1f}–{high:.1f}B"
                        for low, high in zip(guide_history["low"], guide_history["high"])
                    ],
                ),
                trend_row(
                    "指引中值",
                    [(low + high) / 2 for low, high in zip(guide_history["low"], guide_history["high"])],
                    lambda v: f"US${v:.2f}B",
                    derived=True,
                ),
                trend_row("实际收入", guide_history["actual"], lambda v: f"US${v:.2f}B"),
                trend_row(
                    "较中值",
                    [
                        pct_change(actual, (low + high) / 2)
                        for low, high, actual in zip(
                            guide_history["low"], guide_history["high"], guide_history["actual"]
                        )
                    ],
                    lambda v: f"{v:+.1f}%",
                    derived=True,
                ),
            ],
            "区间为各季度开始时公司给出的美元收入指引；中值与偏离度为自算。",
        ),
        panel_group(
            "quarter_detail",
            "本季明细 · 财务、制造与现金读数",
            PANEL_HEADS,
            [
                summary_row("收入（美元）", snapshot["revenue_usd_bn"], lambda value: f"US${value:.2f}B"),
                summary_row("收入（新台币）", snapshot["revenue_ntd_bn"], lambda value: f"NT${value:,.2f}B"),
                summary_row(
                    "晶圆出货（12吋等值）",
                    snapshot["wafer_shipments_kpcs_12in_equiv"],
                    lambda value: f"{value / 1000:.3f}M",
                ),
                summary_row("7nm 及以下占比", snapshot["advanced_mix_pct"], lambda value: f"{value:.0f}%", change="pp"),
                summary_row("HPC 占比", snapshot["hpc_mix_pct"], lambda value: f"{value:.0f}%", change="pp"),
                summary_row("毛利率", snapshot["gross_margin_pct"], lambda value: f"{value:.1f}%", change="pp"),
                summary_row("营业利润率", snapshot["operating_margin_pct"], lambda value: f"{value:.1f}%", change="pp"),
                summary_row("归母净利润", snapshot["net_income_ntd_bn"], lambda value: f"NT${value:,.2f}B"),
                summary_row("净利率", net_margin, lambda value: f"{value:.1f}%", change="pp", derived_values=True),
                summary_row("稀释 EPS", snapshot["eps_ntd"], lambda value: f"NT${value:.2f}"),
                summary_row(
                    "非营业项目",
                    snapshot["non_operating_items_ntd_bn"],
                    lambda value: f"NT${value:,.2f}B",
                ),
                panel_row(
                    "其中：VIS 出售及盯市收益（税前）",
                    [
                        f"NT${snapshot['vis_disposal_and_mark_to_market_gain_pretax_ntd_bn']:,.2f}B",
                        "—",
                        "—",
                        "—",
                        "—",
                    ],
                ),
                summary_row("经营现金流", snapshot["operating_cash_flow_ntd_bn"], lambda value: f"NT${value:,.2f}B"),
                summary_row("资本开支", snapshot["capital_expenditures_ntd_bn"], lambda value: f"NT${value:,.2f}B"),
                summary_row(
                    "自由现金流",
                    snapshot["free_cash_flow_ntd_bn"],
                    lambda value: f"NT${value:,.2f}B",
                    derived_values=True,
                ),
                summary_row("应收天数", snapshot["receivable_days"], lambda value: f"{value:.0f}天", change="days"),
                summary_row("库存天数", snapshot["inventory_days"], lambda value: f"{value:.0f}天", change="days"),
            ],
            "净利率为归母净利润 / 新台币收入（自算），Q2 含 VIS 相关一次性收益，不代表主营盈利能力；"
            "D = Derived / 自算。",
            open_by_default=True,
            sep=3,
        ),
    ]

    return {
        "schema_version": "quarterly-dashboard/tsm-v2",
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
            "增长与利润率同时创新高——收入 US$40.20B、毛利率 67.7%；但本季真正的变化是资本强度："
            f"新台币口径 CapEx 同比 {signed(capex_ntd_yoy)}，已快于收入的 {signed(revenue_ntd_yoy)}，"
            "与上季“收入增速快于 CapEx 增速”的口径相反。"
        ),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>增长</span><b>量价同步，不是单靠涨价</b>'
            '<p>收入 US$40.20B、环比 +12.0%；出货 4.336M 片，隐含 ASP $9,272/片。</p></article>'
            '<article><span>质量</span><b>主营利润率强，但净利润含一次性收益</b>'
            '<p>GM / OM 均超指引上限；VIS 税前相关收益 NT$63.20B 抬高非营业项目。</p></article>'
            '<article><span>资本</span><b>CapEx 增速已经反超收入增速</b>'
            '<p>CapEx 环比 +41.4%，FCF 环比 -17.5%；全年 CapEx 上调至 US$60–64B。</p></article>'
            '</div>'
        ),
        "source": source,
        "source_url": "https://investor.tsmc.com/english/quarterly-results/2026/q2",
        "source_links": staging["sources"],
        "summary": {"blocks": [board]},
        "guidance": {
            "title": "Q2 兑现、Q3 指引与全年 outlook",
            "headers": ["指标", "Q2 原指引", "Q2 实际", "兑现", "Q3 / FY26 新口径", "变化 / 备注"],
            "rows": guide_rows,
            "note": "Q3 收入中值和所有区间差额标 D；公司指引不等同外部市场预期。",
        },
        "sections": [
            {
                "id": "growth_mix",
                "title": "增长、量价与结构",
                "description": "先确认收入增长，再拆开量与价，最后看先进制程与 HPC mix 支撑了多少。",
                "exhibits": exhibits[0:5],
            },
            {
                "id": "quality_capital",
                "title": "盈利质量与资本强度",
                "description": "把主营利润率、一次性非营业收益和自由现金流拆开。",
                "exhibits": exhibits[5:7],
            },
            {
                "id": "leading_indicators",
                "title": "前瞻约束与兑现记录",
                "description": "营运资金显示爬坡成本，历史指引记录检验管理层兑现度。",
                "exhibits": exhibits[7:9],
            },
        ],
        "panel": {
            "title": "季度经营面板",
            "description": "固定字段、每季只填数：先看八季趋势，再看本季与上季、去年同期的明细。",
            "groups": panel_groups,
        },
        "tables": [cross_capex_table(11)],
        "notes": [
            "本页分两层：Exhibit 1 跟踪盘只放带阈值与触发动作的指标；季度经营面板是固定字段的全景表，字段不随季度主题变化。",
            "跟踪盘的阈值是本地研究设定，不是公司指引，也不构成评级或投资建议。",
            "本页只发布公司披露值与可复算的简单派生值；D 标记代表 Derived / 自算。",
            "不发布评级、目标价、估值、卖方共识或未经 TSMC 确认的客户集中度估算。",
            "隐含 ASP 为季度美元收入除以晶圆出货，仅用于量价拆分，不等同任何制程或封装的实际定价。",
            "自由现金流按 TSMC 口径，以经营现金流减季度现金支付资本开支复算；不是利润表 non-GAAP 指标。",
            "VIS 相关收益为公司披露的股份出售及保留股份按市值重估收益；本页不假设税后影响，也不构造‘核心 EPS’。",
            "收入趋势采用美元口径，现金流采用新台币口径；季度现金支付 CapEx 不与全年美元 CapEx 预算相加。",
            "制程占比的分母为晶圆收入，平台占比的分母为净收入；两组 mix 不可直接相加。",
            "本页已知未接入：月度营收、ROE、折旧、R&D / SG&A 费用线、IoT / 汽车 / DCE 平台占比、地区与客户类型组合。",
            "电话会文字稿仅链接 TSMC 官方 IR 托管版本，公开仓不复制原件或逐字内容。",
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
    print("TSM page: tracking board + 9 charts + guidance + 6 panel groups")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
