#!/usr/bin/env python3
"""Build the GOOGL quarterly-results page.

The page is meant to be scanned, not read: it replaces the slide deck that used
to accompany the local earnings note, so almost everything is a chart with one
or two sentences under it.  Charts are ordered the way the note is used --

    1. 上季兑现   did last quarter's tracked lines hold?
    2. 本季重点   what actually moved this quarter
    3. 下季跟踪   what to watch next
    4. 长期常规   the routine multi-quarter series for this specific company

-- and the tables that back them stay collapsed in the audit drawer.

Published numbers are company-reported or transparent arithmetic.  Market
expectations are labelled as such, with no broker attribution.  Ratings, target
prices and valuation stay off the page.
"""

from __future__ import annotations

import json
import re
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


STAGING_PATH = ROOT / "series" / "googl.json"
DATA_DIR = ROOT / "data"


def parse_number(value: str) -> float | None:
    """Parse the compact financial-number strings used by the GOOGL source table."""
    text = re.sub(r"<[^>]+>", "", value).strip()
    if not text or re.fullmatch(r"—+|-+|NM|N/?A|不适用|未披露|n\.m\.", text, re.I):
        return None
    if re.search(r"\d\s*[-–—~]\s*\d", text):
        return None
    text = re.sub(r"\[[^]]*\]", "", text)
    negative = bool(
        re.search(r"\(\s*[$€£¥]?[\d,.]+\s*[A-Za-z]{0,3}\s*\)", text)
        or re.search(r"(?:^|[^A-Za-z0-9_])-\s*[$€£¥]?\s*\d", text)
    )
    match = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", text)
    if not match:
        return None
    parsed = float(match.group(0).replace(",", ""))
    return -abs(parsed) if negative else parsed


def number(value: str | None) -> float | None:
    return parse_number(value or "")


def trend(staging: dict, title: str) -> dict:
    return next(item for item in staging["trends"] if item["title"] == title)


def column(table: dict, heading: str) -> list[float | None]:
    index = table["headers"].index(heading)
    return [number(row[index]) for row in table["rows"]]


def snapshot_row(staging: dict, label: str) -> list[str]:
    return next(row for row in staging["snapshot"]["rows"] if row[0] == label)


def snap(staging: dict, label: str) -> tuple[float | None, float | None, float | None]:
    """Return (current, previous, prior-year) for one snapshot row."""
    row = snapshot_row(staging, label)
    return number(row[3]), number(row[2]), number(row[1])


def change(current: float | None, base: float | None, digits: int = 1) -> str:
    if current is None or base in (None, 0):
        return "—"
    return f"{(current / base - 1) * 100:+.{digits}f}%"


def source_note(detail: str) -> str:
    return f"{detail}；历史期同口径。自算项目均可在表格视图核对。"


def cross_capex_table(n: int) -> dict:
    """Return the shared AI-capex cross reference used by both company pages."""
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    tsm_series = json.loads((ROOT / "series" / "tsm.json").read_text(encoding="utf-8"))
    cash = trend(staging, "八季度趋势（现金与资本强度）")
    capex_by_period = {row[0]: (number(row[2]), row[4]) for row in cash["rows"]}
    return ai_capex_cycle_table(n, capex_by_period, tsm_series)


WINDOW = 8


def yoy(values: list[float]) -> list[float | None]:
    """Year-over-year in percent, None until a year-ago quarter exists."""
    return [None] * 4 + [
        (values[index] / values[index - 4] - 1) * 100 for index in range(4, len(values))
    ]


def trailing(values: list[float]) -> list[float | None]:
    """Rolling four-quarter sum, None until four quarters exist."""
    return [None] * 3 + [sum(values[index - 3:index + 1]) for index in range(3, len(values))]


def shown(values: list) -> list:
    return values[-WINDOW:]


def build_payload(staging: dict) -> dict:
    revenue = trend(staging, "八季度趋势（收入侧）")
    cash = trend(staging, "八季度趋势（现金与资本强度）")

    # The series carries twelve quarters so that every displayed quarter has a
    # year-ago base.  Charts show the last eight; the four extra only exist to
    # make the y/y lines complete rather than starting halfway across the axis.
    q = staging["quarterly"]
    revenue_labels = shown(q["periods"])
    cash_labels = revenue_labels

    revenue_values = shown(q["revenue_total"])
    revenue_yoy = shown(yoy(q["revenue_total"]))
    search_values = shown(q["search_and_other"])
    search_yoy = shown(yoy(q["search_and_other"]))
    youtube_yoy = shown(yoy(q["youtube_ads"]))
    cloud_values = shown(q["cloud"])
    cloud_yoy = shown(yoy(q["cloud"]))
    cloud_opm = column(revenue, "Cloud OPM")
    dep_values = shown(q["depreciation"])
    dep_yoy = shown(yoy(q["depreciation"]))
    ocf_values = shown(q["operating_cash_flow"])
    capex_values = shown(q["capital_expenditures"])
    fcf_all = [
        operating - capex
        for operating, capex in zip(q["operating_cash_flow"], q["capital_expenditures"])
    ]
    fcf_values = shown(fcf_all)
    ttm_fcf_values = shown(trailing(fcf_all))
    capex_intensity = [
        capex / revenue_value * 100
        for capex, revenue_value in zip(capex_values, revenue_values)
    ]
    accel_streak = 0
    for index in range(len(revenue_yoy) - 1, 0, -1):
        if revenue_yoy[index] is None or revenue_yoy[index - 1] is None:
            break
        if revenue_yoy[index] <= revenue_yoy[index - 1]:
            break
        accel_streak += 1
    geography_yoy_series = {
        region: shown(yoy(values)) for region, values in q["geography_usd_m"].items()
    }

    dep_cur, dep_prev, dep_prior = snap(staging, "折旧")
    sbc_cur, sbc_prev, sbc_prior = snap(staging, "股权激励费用")
    ttm_fcf_cur, ttm_fcf_prev = ttm_fcf_values[-1], ttm_fcf_values[-2]
    ttm_fcf_prior = ttm_fcf_values[-5]

    consensus = staging["market_expectation"]
    eps_bridge = staging["eps_bridge"]
    capex_guide = staging["capex_guidance_history"]
    backlog = staging["backlog"]
    geography = staging["geography"]
    prior_kpi = staging["prior_kpi_settlement"]
    next_kpi = staging["next_kpi"]

    capex_guide_mid = [
        (low + high) / 2
        for low, high in zip(capex_guide["low_usd_bn"], capex_guide["high_usd_bn"])
    ]
    eps_gap = (eps_bridge["values"][2] / consensus["operating_eps_mid"] - 1) * 100
    backlog_levels = backlog["level_usd_bn"]
    backlog_labels = shown(backlog["periods"])
    backlog_shown = shown(backlog_levels)
    backlog_qoq = shown([None] + [
        (current / previous - 1) * 100
        for previous, current in zip(backlog_levels, backlog_levels[1:])
    ])
    backlog_net_add = shown([None] + [
        current - previous
        for previous, current in zip(backlog_levels, backlog_levels[1:])
    ])

    # One entry per tracked metric, so §1 and §3 can each draw the metric's own
    # history under its own threshold instead of a single normalised bar.
    tracked = {
        "Cloud 收入 YoY": (revenue_labels, cloud_yoy, "pct1", "同比增速", "Cloud 收入 YoY"),
        "Cloud 经营利润率": (revenue_labels, cloud_opm, "pct1", "利润率", "Cloud OPM"),
        "Search & other YoY": (revenue_labels, search_yoy, "pct1", "同比增速", "Search & other YoY"),
        "Cloud backlog 环比": (backlog_labels, backlog_qoq, "pct1", "环比", "backlog 环比"),
        "Cloud backlog 单季净增": (backlog_labels, backlog_net_add, "usd0", "$B", "单季净增"),
        "TTM 自由现金流": (revenue_labels, ttm_fcf_values, "f0c", "$M", "TTM 自由现金流"),
        "折旧 YoY": (revenue_labels, dep_yoy, "pct1", "同比增速", "折旧 YoY"),
        "Q2 CapEx（不超上限）": (cash_labels, capex_values, "f0c", "$M", "单季 CapEx"),
        "Q3 CapEx（不低于此值否则全年指引下修）": (
            cash_labels, capex_values, "f0c", "$M", "单季 CapEx",
        ),
    }

    def tracking_charts(entries, value_key, threshold_label, headline) -> list[dict]:
        """Return one threshold chart per tracked metric that has a history."""
        charts = []
        for entry in entries:
            metric = entry["metric"]
            if metric not in tracked:
                continue
            xlabels, values, fmt, ylab, actual_name = tracked[metric]
            side = "上方" if entry["direction"] == "up" else "下方"
            charts.append(threshold_exhibit(
                headline(entry),
                xlabels,
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
                    "实际值来自公司季度 release / 电话会口径；阈值为本地研究设定，不是公司指引。"
                ),
            ))
        return charts
    geography_yoy = [
        (current / prior - 1) * 100
        for current, prior in zip(geography["current_usd_m"], geography["prior_year_usd_m"])
    ]

    source = (
        'Source: <a href="https://abc.xyz/investor/" rel="noopener">Alphabet Investor Relations</a>'
        '（Q2 2026 earnings release / call；历史季度 release 经 SEC EDGAR 回源）。'
    )

    settled = headroom_exhibit(
        "上季 7 条量化阈值：经营类全部安全，被击穿的是现金类",
        prior_kpi["quantified"],
        "actual",
        (
            "统一口径：正值 = 仍在安全侧，负值 = 已越过阈值。Cloud 两条大幅超出，"
            "唯一被击穿的是 TTM 自由现金流（$53,273M vs $55,000M）。"
        ),
        src_extra=(
            "阈值为上季本地研究设定，不是公司指引；实际值来自 Q2 2026 release。"
            "另有 3 条定性阈值同时触发（AI Mode 变现披露、回购归零、Waymo 披露倒退），"
            "1 条因可被增发规避而退役（净现金），1 条（Network ads）因阈值接近零会使百分比失真而不入图。"
            "下面逐条给出各指标自身八季走势与阈值线。"
        ),
    )

    built = [
        settled,
        {
            # Growth and margin are the two curves that decide this segment; the
            # revenue level is a scale fact and belongs in the note, not the axis.
            "kind": "lines",
            "title": (
                f"Cloud 增速八季由 {cloud_yoy[0]:.1f}% 升到 {cloud_yoy[-1]:.1f}%，"
                f"利润率同步升到 {cloud_opm[-1]:.2f}%"
            ),
            "xlabels": revenue_labels,
            "series": [
                {"name": "Cloud 收入 YoY", "values": cloud_yoy, "color": "NAVY"},
                {"name": "Cloud 经营利润率", "values": cloud_opm, "color": "GOLD"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "zero_base": True,
            "end_label": True,
            "ylab": "同比增速 / 利润率",
            "note": (
                f"两条线八季同向上行，是最难被叙事伪造的组合；本季收入 "
                f"${cloud_values[-1]:,.0f}M，利润率累计 +{cloud_opm[-1] - cloud_opm[0]:.2f}pp。"
            ),
            "src_extra": source_note("Cloud 收入与经营利润来自公司分部表；同比与 OPM 为自算"),
        },
        {
            "kind": "lines",
            "title": "Search 增速从 19.1% 回落到 16.8%，与市场预期基本一致",
            "xlabels": revenue_labels,
            "series": [
                {"name": "Search & other YoY", "values": search_yoy, "color": "NAVY"},
                {"name": "YouTube ads YoY", "values": youtube_yoy, "color": "MBLUE"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "zero_base": True,
            "end_label": True,
            "ylab": "同比增速",
            "note": (
                "Search 减速 2.3pp，市场预期约 +17%，属符合；YouTube +12.9% 由世界杯驱动，"
                "下季无对应赛事。"
            ),
            "src_extra": source_note("分项收入与同比来自公司季度 release；市场预期为财报前一致预期，不具名"),
        },
        {
            "kind": "bar_line",
            "title": "backlog 创 $514B 新高，但单季净增从 $222B 降到 $52B",
            "xlabels": backlog_labels,
            "bar": {
                "name": "backlog 余额",
                "color": "NAVY",
                "values": backlog_shown,
                "yfmt": "usd0",
            },
            "line": {
                "name": "单季净增 (RHS)",
                "color": "RED",
                "values": backlog_net_add,
                "yfmt": "usd0",
            },
            "fmt": "usd0",
            "yfmt": "usd0",
            "label_fmt": "usd0",
            "ylab": "$B",
            "ylab2": "单季净增 $B",
            "note": (
                "余额与净增方向相反：Q1 的 +$222B 是一次性大单，Q2 的 +$52B 才是常态化水平。"
                "TPU 系统销售已计入 backlog，但公司拒绝给出占比。"
            ),
            "src_extra": (
                "backlog 为合同剩余履约义务，来自各期 10-Q / 10-K；Q2 2026 尚无 10-Q，采用当季电话会口径。"
                "公司未披露取消额与客户集中度，Q1 2026 起纳入 TPU hardware agreements。口径细节见核对表。"
            ),
        },
        {
            "kind": "bars_labeled",
            "title": "FY2026 CapEx 指引半年内三次上调，中点从 $180B 抬到 $200B",
            "xlabels": capex_guide["calls"],
            "values": capex_guide_mid,
            "legend": "FY2026 CapEx 指引中点",
            "fmt": "usd0",
            "yfmt": "usd0",
            "label_fmt": "usd0",
            "ylab": "$B",
            "note": (
                "区间依次为 $175–185B、$180–190B、$195–205B；H1 已花 $80.6B，"
                "隐含 H2 需再花 $114–124B。"
            ),
            "src_extra": source_note("三次指引区间来自对应季度电话会；中点与 H2 隐含额为自算"),
        },
        {
            "kind": "diverging_bars",
            "title": "单季自由现金流首次转负至 -$5.9B",
            "xlabels": cash_labels,
            "values": fcf_values,
            "legend": "自由现金流",
            "positive_label": "正自由现金流",
            "negative_label": "负自由现金流",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "zero_line": True,
            "note": (
                "经营现金流同比增 $11.3B，被同比增 $22.5B 的 CapEx 完全吞没；"
                "本季所得税现金流实为净流入，转负不能用季节性解释。"
            ),
            "src_extra": source_note("FCF = 经营现金流 − 购买物业及设备"),
        },
        {
            "kind": "bars_labeled",
            "title": "$9.11 的 GAAP EPS 里只有 $2.85 是经营的，且略低于市场预期",
            "xlabels": eps_bridge["labels"],
            "values": eps_bridge["values"],
            "legend": "每股收益",
            "fmt": "usd2",
            "yfmt": "usd2",
            "label_fmt": "usd2",
            "ylab": "美元 / 股",
            "note": (
                f"公司披露权益证券收益贡献 EPS $6.26；剔除后 $2.85，较市场预期 "
                f"${consensus['operating_eps_mid']:.2f} 低 {abs(eps_gap):.1f}%。"
                f"同期收入 {change(revenue_values[-1], consensus['revenue_usd_m'])} 于预期。"
            ),
            "src_extra": (
                "GAAP EPS 与权益收益的每股贡献来自 Q2 release 脚注；$2.85 是 $9.11 − $6.26 的算术拆分，"
                "不是公司定义的 non-GAAP。市场预期为财报前一致预期区间 $2.87–$2.91 的中值，不具名。"
            ),
        },
        headroom_exhibit(
            "下季 7 条量化阈值：当前值全部在安全侧，Q3 CapEx 是唯一需要往上走的一条",
            next_kpi["quantified"],
            "current",
            (
                "口径与上一节的余量图相同。Q3 CapEx 那条方向相反——低于 $52B 反而说明全年指引有下修风险，"
                "当前 Q2 实际值离该线还差 13.6%。"
            ),
            src_extra=(
                "阈值为本地研究设定，不是公司指引；当前值为 Q2 2026 实际。"
                "另有 5 条需等披露才能判定（backlog 客户集中度、2027 CapEx 指引、ATM 发行额、"
                "TPU 系统收入、AI Mode 变现指标）。"
            ),
        ),
        {
            "kind": "gs_bar",
            "title": f"总收入同比连续 {accel_streak} 季加速至 {revenue_yoy[-1]:.1f}%",
            "xlabels": revenue_labels,
            "values": revenue_values,
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
                f"在约 $4,000 亿的年收入体量上连续 {accel_streak} 季加速，"
                f"本季收入较市场预期高 {change(revenue_values[-1], consensus['revenue_usd_m'])}。"
            ),
            "src_extra": source_note("收入与同比来自公司季度 release"),
        },
        {
            "kind": "gs_line",
            "title": (
                f"资本强度八季从 {capex_intensity[0]:.1f}% 升到 {capex_intensity[-1]:.1f}%，且尚未见顶"
            ),
            "xlabels": cash_labels,
            "values": capex_intensity,
            "legend": "CapEx / 收入",
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "ylab": "占收入比",
            "note": "按 FY2026 指引中点与全年收入估算，全年资本强度约 41%；这条线比利润表更早反映建设周期。",
            "src_extra": source_note("CapEx / 收入为自算"),
        },
        {
            "kind": "gs_bar",
            "title": f"折旧同比 {dep_yoy[-1]:+.1f}%，快于收入的 {revenue_yoy[-1]:+.1f}%",
            "xlabels": revenue_labels,
            "values": dep_values,
            "legend": "季度折旧",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "ylab2": "同比增速",
            "yoy": {
                "name": "折旧 YoY (RHS)",
                "values": dep_yoy,
                "color": "RED",
                "yfmt": "pct1",
            },
            "note": (
                f"折旧同比已连续多季高于收入同比；当季 CapEx 是折旧的 "
                f"{capex_values[-1] / dep_values[-1]:.1f} 倍，意味着这条线的上行才刚开始。"
            ),
            "src_extra": source_note("季度折旧来自各期 10-Q / 10-K 现金流量表，第四季按全年减前三季倒推"),
        },
        {
            "kind": "gs_line",
            "title": (
                f"TTM 自由现金流见顶回落：${max(ttm_fcf_values):,.0f}M → ${ttm_fcf_cur:,.0f}M"
            ),
            "xlabels": revenue_labels,
            "values": ttm_fcf_values,
            "legend": "TTM 自由现金流",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "note": (
                f"同比 {change(ttm_fcf_cur, ttm_fcf_prior)}、较上季 {change(ttm_fcf_cur, ttm_fcf_prev)}；"
                "滚动四季口径把单季的税款与季节性摊平，拐点出现在 Q1 2026。"
            ),
            "src_extra": source_note("按各季经营现金流减资本开支滚动四季求和（自算），逐季原值见核对表"),
        },
        {
            "kind": "lines",
            "title": (
                f"美国收入同比 {geography_yoy_series['美国'][-1]:+.0f}%，与其余地区的差距在拉大"
            ),
            "xlabels": revenue_labels,
            "series": [
                {"name": "美国", "values": geography_yoy_series["美国"], "color": "NAVY"},
                {"name": "EMEA", "values": geography_yoy_series["EMEA"], "color": "MBLUE"},
                {"name": "APAC", "values": geography_yoy_series["APAC"], "color": "GOLD"},
                {"name": "其他美洲", "values": geography_yoy_series["其他美洲"], "color": "GRAY"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "zero_base": True,
            "end_label": True,
            "ylab": "同比增速",
            "note": (
                f"美国自 Q4 2025 起与其余三个地区分道扬镳，本季占总收入 "
                f"{geography['current_usd_m'][0] / revenue_values[-1] * 100:.1f}%；"
                "地域集中度与 AI 基础设施客户的集中度是同一件事的两个视角。"
            ),
            "src_extra": source_note("分地域收入来自各期 10-Q / 10-K，第四季按全年减前三季倒推；同比为自算"),
        },
    ]
    highlights = built[1:7]
    next_headroom = built[7]
    routine = [built[8], built[9], built[10], built[12]]

    settled_charts = [built[0]] + tracking_charts(
        prior_kpi["quantified"],
        "actual",
        "上季阈值",
        lambda entry: (
            f"{entry['metric']}：{'守住' if headroom(entry['direction'], entry['threshold'], entry['actual']) >= 0 else '已击穿'}"
            f"上季阈值 {unit_text(entry['unit'], entry['threshold'])}"
        ),
    )
    next_charts = [next_headroom] + tracking_charts(
        next_kpi["quantified"],
        "current",
        "下季阈值",
        lambda entry: (
            f"{entry['metric']}：下季阈值 {unit_text(entry['unit'], entry['threshold'])}，"
            f"当前 {unit_text(entry['unit'], entry['current'])}"
        ),
    )

    exhibits = number_exhibits(settled_charts + highlights + next_charts + routine)
    next_table_number = len(exhibits) + 2

    tables = [
        threshold_table(
            next_table_number,
            "上季阈值与本季实际（原单位）",
            prior_kpi["quantified"],
            "actual",
            "Q2 2026 实际",
        ),
        threshold_table(
            next_table_number + 1,
            "下季阈值与当前值（原单位）",
            next_kpi["quantified"],
            "current",
            "当前值",
        ),
        {
            "n": 0,
            "title": "十二季度基础数据（前四季只用于计算同比）",
            "headers": ["季度", "总收入", "Search & other", "YouTube ads", "Cloud",
                        "折旧", "经营现金流", "CapEx", "自由现金流 D", "美国", "EMEA", "APAC", "其他美洲"],
            "rows": [
                [
                    period,
                    f"${q['revenue_total'][i]:,.0f}M",
                    f"${q['search_and_other'][i]:,.0f}M",
                    f"${q['youtube_ads'][i]:,.0f}M",
                    f"${q['cloud'][i]:,.0f}M",
                    f"${q['depreciation'][i]:,.0f}M",
                    f"${q['operating_cash_flow'][i]:,.0f}M",
                    f"${q['capital_expenditures'][i]:,.0f}M",
                    (lambda v: f"-${abs(v):,.0f}M" if v < 0 else f"${v:,.0f}M")(
                        q["operating_cash_flow"][i] - q["capital_expenditures"][i]
                    ),
                    f"${q['geography_usd_m']['美国'][i]:,.0f}M",
                    f"${q['geography_usd_m']['EMEA'][i]:,.0f}M",
                    f"${q['geography_usd_m']['APAC'][i]:,.0f}M",
                    f"${q['geography_usd_m']['其他美洲'][i]:,.0f}M",
                ]
                for i, period in enumerate(q["periods"])
            ],
        },
        {
            "n": 0,
            "title": staging["snapshot"]["title"],
            "headers": staging["snapshot"]["headers"],
            "rows": staging["snapshot"]["rows"],
        },
        cross_capex_table(0),
    ]
    for offset, table in enumerate(tables):
        table["n"] = next_table_number + offset

    return {
        "schema_version": "quarterly-dashboard/googl-v3",
        "page": {"slug": "googl", "language": "zh-CN"},
        "company": {
            "ticker": "GOOGL",
            "name": "Alphabet",
            "group": "internet",
            "accounting_standard": "US GAAP",
        },
        "latest": {
            "disclosed_period_label": "Q2 2026",
            "full_financial_period_label": "Q2 2026",
            "period_end": "2026-06-30",
            "release_date": "2026-07-22",
            "analysis_date": "2026-07-23",
            "audit_status": "unaudited",
            "status": "history_ready",
        },
        "tracker": "Watchlist Quarterly Tracker · GOOGL",
        "title": "Alphabet (GOOGL)：Q2 2026 季报仪表盘",
        "subtitle": "截至 2026-06-30 · 发布 2026-07-22 · US GAAP · 未审计 · 金额单位为 $M，另有注明除外",
        "headline": (
            "经营端交出史上最强一季——收入 +24.2%、Cloud +81.8% 且利润率创 35.59% 新高；"
            "但市场交易的是另一件事：单季自由现金流转负 -$5.9B、回购连续两季归零、"
            f"FY2026 CapEx 指引半年内三次上调至 $195–205B，财报当日股价 {consensus['post_earnings_price_change_pct']}%。"
        ),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>亮点</span><b>Cloud 收入与利润率同步创新高</b>'
            '<p>$24.8B、同比 +81.8%；OPM 35.59%，连续八季上行。</p></article>'
            '<article><span>符合</span><b>Search 减速但落在预期上</b>'
            '<p>+16.8%，较上季 -2.3pp，市场预期约 +17%。</p></article>'
            '<article><span>存疑</span><b>backlog 新高，净增却降 77%</b>'
            '<p>$514B；净增 $222B → $52B。TPU 已计入，公司拒绝给占比。</p></article>'
            '</div>'
        ),
        "source": source,
        "source_url": "https://abc.xyz/investor/",
        "source_links": [
            {
                "label": "Q2 2026 SEC Exhibit 99.1",
                "url": "https://www.sec.gov/Archives/edgar/data/1652044/000165204426000066/googexhibit991q22026.htm",
            },
            {
                "label": "Q1 2026 SEC Exhibit 99.1",
                "url": "https://www.sec.gov/Archives/edgar/data/1652044/000165204426000043/googexhibit991q12026.htm",
            },
            {
                "label": "Q4 2025 Alphabet earnings release",
                "url": "https://s206.q4cdn.com/479360582/files/doc_news/2026/Feb/04/attachments/2025q4-alphabet-earnings-release.pdf",
            },
            {
                "label": "Q3 2025 Alphabet earnings release",
                "url": "https://s206.q4cdn.com/479360582/files/doc_news/2025/Oct/29/attachments/2025q3-alphabet-earnings-release.pdf",
            },
            {
                "label": "Q2 2025 SEC Exhibit 99.1",
                "url": "https://www.sec.gov/Archives/edgar/data/1652044/000165204425000056/googexhibit991q22025.htm",
            },
            {
                "label": "Q2 2026 Alphabet earnings call webcast",
                "url": "https://www.youtube.com/watch?v=LzExSq9DU9w",
            },
            {
                "label": "Q1 2026 Alphabet earnings call webcast",
                "url": "https://www.youtube.com/watch?v=LPJoiDiVkTI",
            },
            {
                "label": "Q4 2025 Alphabet earnings call webcast",
                "url": "https://www.youtube.com/watch?v=mIK5-yi7a-c",
            },
        ],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {
                "id": "settled",
                "title": "一、上季跟踪指标兑现了吗",
                "description": "先结算上季设下的阈值，再看本季数据——否则每季只会新增判断、从不闭环。",
                "exhibits": exhibits[: len(settled_charts)],
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": "四个亮点与存疑项：Cloud、Search、backlog、资本开支与现金流，外加一张盈利质量拆解。",
                "exhibits": exhibits[len(settled_charts): len(settled_charts) + len(highlights)],
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": "同一套口径向前看：当前值离下季阈值还有多远。",
                "exhibits": exhibits[
                    len(settled_charts) + len(highlights):
                    len(settled_charts) + len(highlights) + len(next_charts)
                ],
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": "GOOGL 专属的常规序列：总量增长、资本强度、折旧与现金转换、地域结构。",
                "exhibits": exhibits[-len(routine):],
            },
        ],
        "tables": tables,
        "notes": [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "Exhibit 2 与 Exhibit 9 的阈值是本地研究设定，不是公司指引，也不构成评级或投资建议；「距阈值余量」统一为正值代表安全侧。",
            "本页只发布公司披露值、可复算的简单派生值，以及明确标注的市场预期；D 标记代表 Derived / 自算。",
            "市场预期一律标注为「市场预期」并给出取数时点，不写卖方机构名，也不发布评级、目标价或估值。",
            "$2.85 仅做 $9.11 − $6.26 的算术拆分，不命名为经营 EPS，也不等同公司定义的 non-GAAP 指标。",
            "TTM 自由现金流按各季经营现金流减资本开支滚动四季自算。本地分析稿曾记 Q2 2025 的 TTM 为 $73,552M、"
            "同比 -27.6%；按 10-Q 逐季倒推，$73,552M 实为 Q3 2025 的 TTM，Q2 2025 应为 $66,728M，同比 -20.2%。本页采用后者。",
            "Cloud backlog 来自季度电话会口径；公司未披露取消额、外汇调整或客户集中度。",
            "Q4 2025 总收入采用当季 earnings release 的 $113,828M；与最新 10-K 倒挤值存在 $1M 差异。",
            "所有同比曲线用十二个季度的基础数据计算（展示最近八季，另四季只为让同比从第一格就有值），逐季原值见核对表。",
            "季度值来自各期 10-Q 与 10-K；无 10-Q 的第四季度按「全年 − 前三季」倒推，Q2 2026 采用当季 earnings release。",
            "本页已知未接入：收入成本 / R&D / S&M / G&A 四条费用线、有效税率、稀释股数、paid clicks 与 CPC，以及电话会口径的 Gemini、订阅、Waymo 等运营 KPI。",
        ],
        "footer": (
            "GOOGL quarterly results · 数据来自 Alphabet 公开披露与本地已核对分析稿 · "
            "仅供研究，不构成投资建议"
        ),
    }


SHELL = render_shell("GOOGL", "googl")


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "googl.js"), payload, "googl")
    shell_dir = ROOT / "googl"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(SHELL, encoding="utf-8")
    print("GOOGL page: 13 charts in 4 sections + 6 audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
