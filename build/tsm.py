#!/usr/bin/env python3
"""Build the TSMC quarterly-results page.

Same four-part, chart-led shape as the GOOGL page (上季兑现 → 本季重点 →
下季跟踪 → 长期常规), but the routine series are the ones that actually decide
this company: volume vs price, node and platform mix, guidance delivery and
capital intensity.

The public payload contains only TSMC-reported figures, clearly labelled market
expectations, and arithmetic reproducible from the audit tables.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import (  # noqa: E402
    headroom,
    headroom_exhibit,
    number_exhibits,
    threshold_exhibit,
    threshold_table,
    unit_text,
)
from build.googl import cross_capex_table  # noqa: E402
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
    consensus = staging["market_expectation"]
    net_income_bridge = staging["net_income_bridge"]
    capex_guide = staging["capex_guidance_history"]
    delivery = staging["q2_guidance_delivery"]
    closure = staging["followup_closure"]
    next_kpi = staging["next_kpi"]

    source = (
        'Source: <a href="https://investor.tsmc.com/english/quarterly-results/2026/q2" '
        'rel="noopener">TSMC Investor Relations</a>（2Q26 earnings release、'
        'management report 与 earnings conference）。'
    )

    # Implied ASP is the cheapest honest volume/price split available: both
    # inputs are reported every quarter, and it separates "more wafers" from
    # "richer wafers" without assuming anything about node pricing.
    shipments = financials["wafer_shipments_kpcs_12in_equiv"]
    asp = [
        financials["revenue_usd_bn"][index] * 1_000_000 / shipments[index]
        for index in range(len(periods))
    ]

    q3_midpoint = sum(guidance["q3_new"]["revenue_usd_bn"]) / 2
    q3_midpoint_growth = pct_change(q3_midpoint, guidance["q2_actual"]["revenue_usd_bn"])
    q3_gm_midpoint = sum(guidance["q3_new"]["gross_margin_pct"]) / 2
    capex_guide_mid = [
        (low + high) / 2
        for low, high in zip(capex_guide["low_usd_bn"], capex_guide["high_usd_bn"])
    ]
    revenue_ntd_yoy = pct_change(snapshot["revenue_ntd_bn"][0], snapshot["revenue_ntd_bn"][2])
    capex_ntd_yoy = pct_change(
        snapshot["capital_expenditures_ntd_bn"][0], snapshot["capital_expenditures_ntd_bn"][2]
    )
    shipment_qoq = pct_change(shipments[-1], shipments[-2])
    asp_qoq = pct_change(asp[-1], asp[-2])
    core_beat = pct_change(net_income_bridge["values_ntd_bn"][2], consensus["net_income_ntd_bn"])
    headline_beat = pct_change(net_income_bridge["values_ntd_bn"][0], consensus["net_income_ntd_bn"])
    gm_floor = guidance["long_term_gross_margin_floor_pct"]

    # US-dollar CapEx carries twelve quarters so its y/y is populated from the
    # first column, and both sides of the intensity ratio stay in one currency.
    capex_usd_all = staging["capital_expenditures_usd_bn"]["values"]
    capex_usd = capex_usd_all[-len(periods):]
    capex_usd_yoy = [
        (capex_usd_all[index] / capex_usd_all[index - 4] - 1) * 100
        for index in range(len(capex_usd_all) - len(periods), len(capex_usd_all))
    ]
    capex_intensity_usd = [
        capex / revenue * 100
        for capex, revenue in zip(capex_usd, financials["revenue_usd_bn"])
    ]

    # CapEx is reported in NT$ but tracked against a US$ line, so the threshold
    # is converted at the quarter's own realised rate and marked as derived.
    capex_threshold_ntd = round(19.0 * guidance["q2_actual"]["usd_ntd"], 1)
    tracked = {
        "毛利率": (labels, financials["gross_margin_pct"], "pct1", "毛利率", "毛利率", None),
        "库存天数": (labels, working["inventory_days"], "f0", "天", "库存天数", None),
        "HPC 占比（集中度）": (labels, platform["hpc"], "pct0", "净收入占比", "HPC 占比", None),
        "2nm 占晶圆收入": (labels, technology["2nm"], "pct0", "晶圆收入占比", "2nm 占比", None),
        "单季 CapEx": (
            labels, cash["capital_expenditures"], "f0c", "NT$B", "单季 CapEx", capex_threshold_ntd,
        ),
    }

    def tracking_charts(entries, value_key, threshold_label, headline) -> list[dict]:
        charts = []
        for entry in entries:
            metric = entry["metric"]
            if metric not in tracked:
                continue
            xlabels, values, fmt, ylab, actual_name, override = tracked[metric]
            side = "上方" if entry["direction"] == "up" else "下方"
            threshold = entry["threshold"] if override is None else override
            converted = (
                ""
                if override is None
                else f"（US${entry['threshold']:.0f}B 按本季实际汇率 {guidance['q2_actual']['usd_ntd']} 折为 NT${override:,.1f}B D）"
            )
            charts.append(threshold_exhibit(
                headline(entry),
                xlabels,
                values,
                threshold,
                fmt=fmt,
                ylab=ylab,
                actual_name=actual_name,
                threshold_name=f"{threshold_label}（安全侧在{side}）",
                note=(
                    f"阈值 {unit_text(entry['unit'], entry['threshold'])}{converted}，"
                    f"当前 {unit_text(entry['unit'], entry[value_key])}，"
                    f"余量 {headroom(entry['direction'], entry['threshold'], entry[value_key]):+.1f}%。"
                ),
                src_extra=(
                    "实际值来自各季 earnings release / management report；"
                    "阈值为本地研究设定，不是公司指引。"
                ),
            ))
        return charts

    built = [
        {
            "kind": "bars_labeled",
            "title": "上季 12 条待验证问题：3 条已验证、1 条被证伪、4 条仍未披露",
            "xlabels": closure["labels"],
            "values": closure["counts"],
            "legend": "问题条数",
            "fmt": "f0",
            "yfmt": "f0",
            "label_fmt": "f0",
            "ylab": "条",
            "note": (
                "被证伪的是库存天数——上季判断会回落到 75–78 天，实际升到 87 天；"
                "仍未披露的四条集中在节点毛利率与长期目标上修。"
            ),
            "src_extra": "问题清单来自上季本地分析稿的 follow-up；验证结果依据 2Q26 earnings conference 与 management report。",
        },
        {
            "kind": "diverging_bars",
            "title": "Q2 全线优于自身指引中值，只有汇率是逆风",
            "xlabels": [item["metric"] for item in delivery],
            "values": [item["value"] for item in delivery],
            "legend": "优于指引中值的幅度",
            "positive_label": "优于指引",
            "negative_label": "逊于指引",
            "fmt": "f1",
            "yfmt": "f1",
            "label_fmt": "f1",
            "ylab": "% 或 pp",
            "zero_line": True,
            "note": (
                "毛利率与营业利润率都超出指引区间上限，且是在新台币较汇率假设小幅升值的逆风下做到的。"
            ),
            "src_extra": (
                "收入与汇率为百分比，毛利率 / 营业利润率 / 税率为百分点，两类单位并列于同一轴上，"
                "只用于比较方向与相对幅度；原值见核对表。"
            ),
        },
        {
            "kind": "range_band",
            "title": "连续八季实际收入均达到或超过指引中点",
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
            "note": "八季全部不低于中点，其中六季达到或超过区间上端；本季落在上端。",
            "src_extra": "区间为各季度开始时公司给出的美元收入指引，实际值来自随后发布的 earnings release。",
        },
        {
            "kind": "gs_bar",
            "title": "收入 US$40.20B 落指引上端，全年增速指引从 30%+ 上调到略高于 40%",
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
            "note": (
                f"环比 +12.0%、同比 +33.7%，较市场预期 US${consensus['revenue_usd_bn']:.2f}B 高 "
                f"{pct_change(financials['revenue_usd_bn'][-1], consensus['revenue_usd_bn']):.1f}%；"
                f"Q3 指引中值 US${q3_midpoint:.1f}B，环比 {signed(q3_midpoint_growth)}，不减速。"
            ),
            "src_extra": "美元收入与同比来自各季 earnings release；市场预期为财报前一致预期，不具名。",
        },
        {
            "kind": "gs_bar",
            "title": f"环比 +12.0% 里约三分之二来自价与结构：出货仅 {signed(shipment_qoq)}，隐含 ASP {signed(asp_qoq)}",
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
                f"隐含 ASP = 季度美元收入 / 晶圆出货，Q2 为 ${asp[-1]:,.0f}/片；"
                "抬价的是 2nm 首季贡献 3%、3nm 占比 +5pp 与 HPC mix，不是单纯提价。"
            ),
            "src_extra": (
                "出货量与美元收入来自各季 earnings release / management report；隐含 ASP 为两者相除的自算值，"
                "不是公司披露的定价指标，也不区分制程与封装口径。"
            ),
        },
        {
            "kind": "lines",
            "title": "毛利率 67.7% 超指引上限，但 Q3 指引中值已降到 66%",
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
            "note": (
                f"管理层首次量化 2H26 的 N2 稀释 3–4pp，叠加海外厂后期 3–4pp；"
                f"Q3 指引中值 {q3_gm_midpoint:.1f}%，较本季 -1.7pp。67.7% 大概率是本周期顶点。"
            ),
            "src_extra": "利润率与指引来自 TSMC earnings release；稀释幅度为管理层在电话会上的量化口径。",
        },
        {
            "kind": "bars_labeled",
            "title": "FY2026 CapEx 预算半年内两次上调，中点从 US$54B 抬到 US$62B",
            "xlabels": capex_guide["calls"],
            "values": capex_guide_mid,
            "legend": "FY2026 CapEx 指引中点",
            "fmt": "usd0",
            "yfmt": "usd0",
            "label_fmt": "usd0",
            "ylab": "US$B",
            "note": (
                f"新台币口径下本季 CapEx 同比 {signed(capex_ntd_yoy)}、收入同比 {signed(revenue_ntd_yoy)}；"
                "两条增速的八季美元口径对照见下一节。"
            ),
            "src_extra": (
                "三次口径依次为 1 月 US$52–56B、4 月 closer to US$56B、7 月 US$60–64B；"
                "同比增速为新台币口径自算，避免与全年美元预算混用。"
            ),
        },
        {
            "kind": "bars_labeled",
            "title": f"净利大幅超预期，但剔除 VIS 一次性后核心 beat 只有 {core_beat:+.1f}%",
            "xlabels": net_income_bridge["labels"],
            "values": net_income_bridge["values_ntd_bn"],
            "legend": "净利润",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "NT$B",
            "note": (
                f"报告净利较市场预期高 {headline_beat:+.1f}%，但处置世界先进股份与保留股份重估的"
                f"税前一次性收益 NT$63.20B 解释了其中绝大部分；真正干净的超预期在收入与毛利率。"
            ),
            "src_extra": (
                "报告净利与 VIS 相关收益来自 2Q26 management report；核心净利为两者相减的自算值（未做税务调整），"
                "市场预期为财报前一致预期，不具名。"
            ),
        },
        {
            "kind": "grouped_bars",
            "title": "CapEx 环比 +41%，自由现金流反而下降 17.5%",
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
            "note": (
                "资本强度从 30.9% 跳到 39.0%；股息年化 NT$622B，本年自由现金流仍可覆盖约两倍，"
                "现金流压缩暂未威胁股东回报。"
            ),
            "src_extra": "季度新台币现金流口径；FCF = 经营现金流 − 现金支付资本开支，按 TSMC 定义复算。",
        },
        headroom_exhibit(
            "下季 6 条量化阈值：2nm 占比是唯一需要大幅上行才能达标的一条",
            next_kpi["quantified"],
            "current",
            (
                "正值 = 仍在安全侧。2nm 当前 3%，而 Q3 的「steep ramp」需要至少 5%，"
                "是唯一明显在阈值之下的指标；库存天数离 90 天的警戒只剩 3.3%。"
            ),
            src_extra=(
                "阈值为本地研究设定，不是公司指引；当前值为 Q2 2026 实际。"
                "另有 4 条需等披露才能判定（Q3 实际收入、2027 CapEx 指引、长期毛利率目标、Smartphone 连续负增长）。"
            ),
        ),
        {
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
            "note": "此前的 0 表示未单列或整数百分比舍入为零，不代表绝对没有收入；3nm 同期升至 30%。",
            "src_extra": "制程组合分母为 total wafer revenue，来自各季 management report。",
        },
        {
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
            "note": (
                "HPC 环比 +20%、手机环比 -4%；集中度是这条曲线的另一面，"
                "HPC 站上 68% 即触发本页的集中度跟踪线。"
            ),
            "src_extra": (
                "平台组合分母为 net revenue；本页仅接入 HPC 与 Smartphone 两类，"
                "IoT / 汽车 / DCE 尚未接入。"
            ),
        },
        {
            "kind": "lines",
            "title": "N2 爬坡把库存天数推回 87 天，应收天数升至 29 天",
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
            "note": (
                "公司归因于 N2 爬坡备货；若下季 2nm 占比已跳升而库存仍不回落，备货解释即失效。"
            ),
            "src_extra": "应收与库存天数来自各季 management report。",
        },
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
            f"{shipments[index] / 1000:.3f}M",
            f"${asp[index]:,.0f} D",
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

    inventory_expectation = threshold_exhibit(
        "上季判断库存回落到 75–78 天，实际升到 87 天（被证伪）",
        labels,
        working["inventory_days"],
        78.0,
        fmt="f0",
        ylab="天",
        actual_name="库存天数",
        threshold_name="上季预期上沿 78 天",
        note=(
            "管理层归因于 N2 爬坡备货；这是上季 12 条判断里唯一被明确证伪的一条，"
            "也是本页把 90 天设为下季警戒线的由来。"
        ),
        src_extra="库存天数来自各季 management report；75–78 天为上季本地分析稿的预期区间。",
    )

    capex_intensity_chart = {
        "kind": "gs_line",
        "title": (
            f"资本强度八季从 {capex_intensity_usd[0]:.1f}% 升到 {capex_intensity_usd[-1]:.1f}%"
        ),
        "xlabels": labels,
        "values": capex_intensity_usd,
        "legend": "CapEx / 收入（美元口径）",
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "占收入比",
        "note": (
            f"本季 {capex_intensity_usd[-1]:.1f}%，较上季 {capex_intensity_usd[-2]:.1f}% 跳升；"
            "这条线与 GOOGL 页同口径，可直接对照上下游的资本强度。"
        ),
        "src_extra": (
            "美元 CapEx 来自各季 earnings conference 原句，美元收入来自各季 earnings release；"
            "比值为自算，两侧同币种，不与新台币现金流口径混用。"
        ),
    }

    growth_crossover_chart = {
        "kind": "lines",
        "title": (
            f"CapEx 增速 {capex_usd_yoy[-1]:+.0f}% 反超收入增速 "
            f"{financials['revenue_yoy_pct'][-1]:+.0f}%"
        ),
        "xlabels": labels,
        "series": [
            {"name": "收入 YoY", "values": financials["revenue_yoy_pct"], "color": "NAVY"},
            {"name": "CapEx YoY", "values": capex_usd_yoy, "color": "RED"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "同比增速",
        "note": (
            "上季管理层称「收入增速快于 CapEx 增速」；本季两条线交叉，这是股价的直接压制项。"
            "两条都是美元口径，不含汇率错配。"
        ),
        "src_extra": (
            "收入同比为公司披露，CapEx 同比按各季 earnings conference 的美元 CapEx 自算；"
            "同比需要上年同期，故序列多带四个季度，只展示最近八季。"
        ),
    }

    settled_charts = built[0:3] + [inventory_expectation]
    highlights = built[3:9] + [growth_crossover_chart]
    next_charts = [built[9]] + tracking_charts(
        next_kpi["quantified"],
        "current",
        "下季阈值",
        lambda entry: (
            f"{entry['metric']}：下季阈值 {unit_text(entry['unit'], entry['threshold'])}，"
            f"当前 {unit_text(entry['unit'], entry['current'])}"
        ),
    )
    routine = built[10:] + [capex_intensity_chart]

    exhibits = number_exhibits(settled_charts + highlights + next_charts + routine)
    next_table_number = len(exhibits) + 2

    tables = [
        {
            # Reference detail, not a lead module: the decision-relevant parts of
            # guidance are already in the settled and highlight sections.
            "n": next_table_number,
            "title": "Q2 兑现、Q3 指引与全年 outlook",
            "headers": ["指标", "Q2 原指引", "Q2 实际", "兑现", "Q3 / FY26 新口径", "变化 / 备注"],
            "rows": guide_rows,
        },
        threshold_table(
            next_table_number + 1,
            "下季阈值与当前值（原单位）",
            next_kpi["quantified"],
            "current",
            "当前值",
        ),
        {
            "n": next_table_number + 2,
            "title": "八季度财务、出货与隐含 ASP",
            "headers": ["期间", "收入", "收入 YoY", "毛利率", "营业利润率", "稀释 EPS", "晶圆出货", "隐含 ASP"],
            "rows": financial_table,
        },
        {
            "n": next_table_number + 3,
            "title": "八季度制程与平台收入组合",
            "headers": ["期间", "2nm", "3nm", "5nm", "7nm", "≤7nm", "HPC", "Smartphone"],
            "rows": mix_table,
        },
        {
            "n": next_table_number + 4,
            "title": "八季度现金流与营运资金",
            "headers": ["期间", "经营现金流", "资本开支", "自由现金流", "应收天数", "库存天数"],
            "rows": cash_table,
        },
        {
            "n": next_table_number + 5,
            "title": "八季度美元收入指引兑现",
            "headers": ["期间", "公司指引", "中值", "实际", "较中值"],
            "rows": guidance_table,
        },
        cross_capex_table(next_table_number + 6),
    ]

    return {
        "schema_version": "quarterly-dashboard/tsm-v3",
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
            "基本面全线更强——收入落指引上端、毛利率 67.7% 超上限、全年增速指引由 30%+ 上调到略高于 40%；"
            f"但股价当日 {consensus['post_earnings_price_change_pct']}%，市场卖的是资本强度："
            f"全年 CapEx 上调至 US$60–64B，新台币口径 CapEx 同比 {signed(capex_ntd_yoy)} 已快于收入的 {signed(revenue_ntd_yoy)}。"
        ),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>亮点</span><b>收入与毛利率双超指引上限</b>'
            '<p>US$40.20B 落区间上端；GM 67.7%、OM 60.3%，均超上限。</p></article>'
            '<article><span>结构</span><b>增长约三分之二来自价与 mix</b>'
            '<p>出货环比 +3.9%，隐含 ASP +7.8%；2nm 首季即贡献 3%。</p></article>'
            '<article><span>存疑</span><b>净利大 beat 含一次性</b>'
            f'<p>VIS 税前收益 NT$63.20B；核心净利较预期仅 {core_beat:+.1f}%。</p></article>'
            '</div>'
        ),
        "source": source,
        "source_url": "https://investor.tsmc.com/english/quarterly-results/2026/q2",
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {
                "id": "settled",
                "title": "一、上季跟踪指标兑现了吗",
                "description": "先看上季留的问题闭环了几条、公司自己的指引兑现得怎么样，再谈本季。",
                "exhibits": exhibits[: len(settled_charts)],
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": "收入与指引、量价拆分、毛利率拐点、资本开支上调，以及净利里的一次性成分。",
                "exhibits": exhibits[len(settled_charts): len(settled_charts) + len(highlights)],
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": "当前值离下季阈值还有多远，统一用「距阈值余量」口径。",
                "exhibits": exhibits[
                    len(settled_charts) + len(highlights):
                    len(settled_charts) + len(highlights) + len(next_charts)
                ],
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": "TSM 专属的常规序列：制程世代迁移、平台结构与营运资金。",
                "exhibits": exhibits[-len(routine):],
            },
        ],
        "tables": tables,
        "notes": [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "Exhibit 11 的阈值是本地研究设定，不是公司指引，也不构成评级或投资建议；「距阈值余量」统一为正值代表安全侧。",
            "本页只发布公司披露值、可复算的简单派生值，以及明确标注的市场预期；D 标记代表 Derived / 自算。",
            "市场预期一律标注为「市场预期」并给出取数时点，不写卖方机构名，也不发布评级、目标价或估值。",
            "隐含 ASP 为季度美元收入除以晶圆出货，仅用于量价拆分，不等同任何制程或封装的实际定价。",
            "核心净利为报告净利减 VIS 相关税前收益的算术差，未做税务调整，也不是公司定义的调整后利润。",
            "自由现金流按 TSMC 口径，以经营现金流减季度现金支付资本开支复算；不是利润表 non-GAAP 指标。",
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
    print("TSM page: 13 charts in 4 sections + 7 audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
