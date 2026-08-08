#!/usr/bin/env python3
"""Build the GOOGL quarterly-results page.

The source-of-truth is ``series/googl.json``, an auditable extraction of the
user's local earnings-analysis note.  The page is built in two layers:

* **Tracking board** (Exhibit 1) -- the handful of metrics that carry a
  threshold and a trigger action.  It answers "what changed in the things I
  actually track".
* **Operating panel** (after the charts) -- fixed fields, same rows every
  quarter, so the eight-quarter trend stays comparable.  It answers "what did
  the last few quarters look like".

The page deliberately excludes ratings, valuation, sell-side consensus and
unverified external estimates; every published number is either company-reported
or a transparent arithmetic derivation from reported figures.
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
    board_block,
    board_row,
    panel_group,
    panel_row,
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
    number_value = float(match.group(0).replace(",", ""))
    return -abs(number_value) if negative else number_value


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


def compact(period: str) -> str:
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


def money(value: float | None) -> str:
    if value is None:
        return "—"
    return f"-${abs(value):,.0f}M" if value < 0 else f"${value:,.0f}M"


def pct(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value:.{digits}f}%"


def pp(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value:+.{digits}f}pp"


def change(current: float | None, base: float | None, digits: int = 1) -> str:
    if current is None or base in (None, 0):
        return "—"
    return f"{(current / base - 1) * 100:+.{digits}f}%"


def gap(current: float | None, base: float | None, digits: int = 2) -> str:
    if current is None or base is None:
        return "—"
    return pp(current - base, digits)


def ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator * 100


def summary_row(staging: dict, label: str, display_label: str | None = None,
                derived: bool = False) -> dict:
    row = snapshot_row(staging, label)
    # Source table order: metric, Q2'25, Q1'26, Q2'26, QoQ, YoY, source.
    values = [row[3], row[2], row[1], row[4], row[5]]
    cells = []
    for index, value in enumerate(values):
        is_derived = derived or (index >= 3 and value not in ("", "—"))
        cells.append({
            "v": value or "—",
            "cls": "cur" if index == 0 else "",
            "status": "derived" if is_derived else "reported",
        })
    return {"label": display_label or label.lstrip("— "), "cells": cells}


def source_note(detail: str) -> str:
    return f"{detail}；历史期同口径。自算项目均可由表格视图复核。"


def cross_capex_table(n: int) -> dict:
    """Return the shared AI-capex cross reference used by both company pages.

    It lives here because this module owns the GOOGL number parser; the TSM
    builder imports it so both pages publish an identical table.
    """
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    tsm_series = json.loads((ROOT / "series" / "tsm.json").read_text(encoding="utf-8"))
    cash = trend(staging, "八季度趋势（现金与资本强度）")
    capex_by_period = {row[0]: (number(row[2]), row[4]) for row in cash["rows"]}
    return ai_capex_cycle_table(n, capex_by_period, tsm_series)


PANEL_HEADS = ["Q2 2026", "Q1 2026", "Q2 2025", "q/q", "y/y"]


def build_payload(staging: dict) -> dict:
    revenue = trend(staging, "八季度趋势（收入侧）")
    cash = trend(staging, "八季度趋势（现金与资本强度）")

    revenue_labels = [row[0] for row in revenue["rows"]]
    cash_labels = [row[0] for row in cash["rows"]]

    revenue_values = column(revenue, "总收入")
    revenue_yoy = column(revenue, "YoY")
    search_yoy = [number(row[4]) for row in revenue["rows"]][-4:]
    youtube_yoy = [number(row[6]) for row in revenue["rows"]][-4:]
    cloud_values = column(revenue, "Cloud")
    cloud_yoy = [number(row[8]) for row in revenue["rows"]]
    cloud_opm = column(revenue, "Cloud OPM")
    fcf_values = column(cash, "自由现金流")
    capex_intensity = column(cash, "CapEx/收入")
    capex_values = column(cash, "CapEx")
    ocf_values = column(cash, "经营现金流")

    # --- reported levels used by both layers -------------------------------
    rev_cur, rev_prev, rev_prior = snap(staging, "总收入")
    dep_cur, dep_prev, dep_prior = snap(staging, "折旧")
    sbc_cur, sbc_prev, sbc_prior = snap(staging, "股权激励费用")
    tac_cur, tac_prev, tac_prior = snap(staging, "总 TAC")
    heads_cur, heads_prev, heads_prior = snap(staging, "员工人数")
    equity_cur, equity_prev, equity_prior = snap(staging, "— 权益证券收益")
    net_cur, net_prev, net_prior = snap(staging, "净利润（归属普通股）")
    ttm_fcf_cur, ttm_fcf_prev, ttm_fcf_prior = snap(staging, "TTM 自由现金流")
    backlog_cur, backlog_prev, _ = snap(staging, "Cloud backlog")
    buyback_cur, _, buyback_prior = snap(staging, "股票回购")
    services_opm_cur, _, _ = snap(staging, "— Services OPM")
    cloud_opm_cur = cloud_opm[-1]

    # Advertising revenue is the honest TAC denominator: dividing by total
    # revenue lets Cloud growth flatter the rate without anything improving.
    ads_cur, ads_prev, ads_prior = (
        sum(values)
        for values in zip(
            snap(staging, "— Search & other"),
            snap(staging, "— YouTube ads"),
            snap(staging, "— Google Network"),
        )
    )

    def cloud_ttm(end_index: int) -> float:
        return sum(cloud_values[end_index - 3:end_index + 1])

    cloud_ttm_cur = cloud_ttm(len(cloud_values) - 1)
    cloud_ttm_prev = cloud_ttm(len(cloud_values) - 2)
    coverage_cur = backlog_cur / cloud_ttm_cur
    coverage_prev = backlog_prev / cloud_ttm_prev

    dep_ratio = [ratio(dep_cur, rev_cur), ratio(dep_prev, rev_prev), ratio(dep_prior, rev_prior)]
    sbc_ratio = [ratio(sbc_cur, rev_cur), ratio(sbc_prev, rev_prev), ratio(sbc_prior, rev_prior)]
    tac_ratio = [ratio(tac_cur, ads_cur), ratio(tac_prev, ads_prev), ratio(tac_prior, ads_prior)]
    equity_share = [
        ratio(equity_cur, net_cur), ratio(equity_prev, net_prev), ratio(equity_prior, net_prior)
    ]
    revenue_per_head = [
        rev_cur / heads_cur * 1000 if heads_cur else None,
        rev_prev / heads_prev * 1000 if heads_prev else None,
        rev_prior / heads_prior * 1000 if heads_prior else None,
    ]

    dep_yoy = (dep_cur / dep_prior - 1) * 100
    cloud_yoy_cur = cloud_yoy[-1]
    scissors = cloud_yoy_cur - dep_yoy
    capex_h1 = capex_values[-1] + capex_values[-2]
    capex_ttm = sum(capex_values[-4:])
    equity_raise = 30.499 + 19.063  # Q2 common + preferred issuance, US$B.

    source = (
        'Source: <a href="https://abc.xyz/investor/" rel="noopener">Alphabet Investor Relations</a>'
        '（Q2 2026 earnings release / call；历史季度 release 经 SEC EDGAR 回源）。'
    )

    # --- layer 2: tracking board -------------------------------------------
    board = board_block(
        [
            board_row(
                "Cloud 收入 YoY − 折旧 YoY 剪刀差",
                f"{scissors:+.1f}pp（Cloud {cloud_yoy_cur:+.1f}% − 折旧 {dep_yoy:+.1f}%）",
                "< +10pp = 折旧追平增长；< 0 = 规模杠杆逆转",
                "减仓",
                "ok",
            ),
            board_row(
                "折旧 / 收入",
                f"{dep_ratio[0]:.2f}%（Q2 2025 {dep_ratio[2]:.2f}%）",
                "> 8% 且经营利润率同比转负",
                "警示",
                "ok",
            ),
            board_row(
                "Cloud 经营利润率",
                f"{cloud_opm_cur:.2f}%，八季连续上行",
                "环比首次回落 ≥ 1pp 且折旧/收入同步上行",
                "重新评估规模经济",
                "ok",
            ),
            board_row(
                "TTM 自由现金流与外部融资依赖",
                f"TTM {money(ttm_fcf_cur)}（较上季 {change(ttm_fcf_cur, ttm_fcf_prev)}）；"
                f"单季 FCF {money(fcf_values[-1])}；回购 {money(buyback_cur)}（连续两季）；"
                f"本季股权融资 ${equity_raise:,.1f}B",
                "TTM FCF < $40,000M；或单季出现大额外部股权融资",
                "重估资本结构与估值框架",
                "hit",
            ),
            board_row(
                "GAAP 净利润中权益证券收益占比",
                f"{equity_share[0]:.1f}%（{money(equity_cur)} / {money(net_cur)}）",
                "> 30% 时 headline EPS 不可作估值锚",
                "改看剔除后 EPS",
                "hit",
            ),
            board_row(
                "Cloud backlog 净增与覆盖倍数",
                f"净增 {money(backlog_cur - backlog_prev)}（上季 +$222,000M）；"
                f"覆盖 TTM Cloud 收入 {coverage_cur:.2f}x",
                "连续两季净增 < $30,000M，或覆盖倍数持续下行",
                "跟踪",
                "watch",
            ),
            board_row(
                "Services 经营利润率与 TAC 率",
                f"Services OPM {services_opm_cur:.2f}%；TAC/广告收入 {tac_ratio[0]:.2f}%"
                f"（Q2 2025 {tac_ratio[2]:.2f}%）",
                "Services OPM 同比下降 > 2pp 连续两季",
                "警示",
                "ok",
            ),
            board_row(
                "Search 货币化：paid clicks 与 CPC",
                "本页未接入（10-Q 披露口径）",
                "CPC 同比转负且 paid clicks 增速低于 Search 收入增速",
                "待接入后再判定",
                "na",
            ),
        ],
        "阈值为本地研究设定，不是公司指引，也不是评级；状态灯只反映该行阈值的机械判定。"
        "当前值均可由下方经营面板与核对表复算。",
    )

    exhibits = [
        {
            "n": 2,
            "kind": "gs_bar",
            "title": "总收入增长连续四季加速，Q2 同比达 24.2%",
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
            "note": "收入体量已接近 $120B；最近四季同比由 15.9% 逐季升至 24.2%。",
            "src_extra": source_note("收入与同比来自公司季度 release"),
        },
        {
            "n": 3,
            "kind": "gs_bar",
            "title": "Cloud 收入八季翻倍，利润率同步升至 35.6%",
            "xlabels": revenue_labels,
            "values": cloud_values,
            "legend": "Cloud 收入",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "ylab2": "Cloud OPM",
            "yoy": {
                "name": "Cloud OPM (RHS)",
                "values": cloud_opm,
                "color": "GOLD",
                "yfmt": "pct1",
            },
            "note": "Q2 Cloud 收入 $24.8B、同比 +81.8%；OPM 八季连续上升，说明规模杠杆仍跑赢新增折旧。",
            "src_extra": source_note("Cloud 收入和经营利润来自公司分部表；OPM 为自算"),
        },
        {
            "n": 4,
            "kind": "lines",
            "title": "Search 仍双位数增长，YouTube 广告增速回升",
            "xlabels": revenue_labels[-4:],
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
            "note": "Search Q2 同比 +16.8%，较 Q1 的 19.1% 放缓；YouTube ads 回升至 +12.9%。",
            "src_extra": source_note("分项收入与同比来自公司季度 release"),
        },
        {
            "n": 5,
            "kind": "grouped_bars",
            "title": f"折旧同比 +{dep_yoy:.1f}%，快于收入的 +24.2%",
            "xlabels": ["Q2 2025", "Q1 2026", "Q2 2026"],
            "groups": [
                {"name": "折旧", "values": [dep_prior, dep_prev, dep_cur], "color": "NAVY"},
                {"name": "股权激励费用", "values": [sbc_prior, sbc_prev, sbc_cur], "color": "MBLUE"},
            ],
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "bar_labels": False,
            "note": (
                f"折旧占收入由 {dep_ratio[2]:.2f}% 升至 {dep_ratio[0]:.2f}%，SBC 占收入 "
                f"{sbc_ratio[0]:.2f}%；公司未按季给出八季折旧序列，本图只用可回源的三期。"
            ),
            "src_extra": source_note("折旧与股权激励费用来自季度现金流量表；占比为自算"),
        },
        {
            "n": 6,
            "kind": "bars_labeled",
            "title": "$9.11 GAAP EPS 中，$6.26 来自权益证券收益",
            "xlabels": ["GAAP EPS", "其中：权益收益", "简单扣除后（自算）"],
            "values": [9.11, 6.26, 2.85],
            "legend": "每股收益",
            "fmt": "usd2",
            "yfmt": "usd2",
            "label_fmt": "usd2",
            "ylab": "美元 / 股",
            "note": (
                "公司披露权益证券净收益贡献 EPS $6.26；$2.85 = $9.11 − $6.26 "
                "只是透明算术，不是公司定义的 non-GAAP 或‘经营 EPS’。"
            ),
            "src_extra": source_note("GAAP EPS 与权益收益的 EPS 贡献来自 Q2 release 脚注"),
        },
        {
            "n": 7,
            "kind": "gs_line",
            "title": "CapEx 强度七季由 14.8% 升至 37.5%",
            "xlabels": cash_labels,
            "values": capex_intensity,
            "legend": "CapEx / 收入",
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "ylab": "占收入比",
            "note": "Q2 CapEx $44.9B，同比翻倍；资本强度的上升比利润表更早反映 AI 基础设施周期。",
            "src_extra": source_note("CapEx / 收入为自算"),
        },
        {
            "n": 8,
            "kind": "diverging_bars",
            "title": "单季自由现金流从 $24.6B 下滑至 -$5.9B",
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
            "note": "Q2 经营现金流同比增加 $11.3B，但 CapEx 同比增加 $22.5B，现金增量被资本开支完全吞没。",
            "src_extra": source_note("FCF = 经营现金流 − 购买物业及设备"),
        },
        {
            "n": 9,
            "kind": "bars_labeled",
            "title": "TTM 自由现金流由 $66.7B 降至 $53.3B",
            "xlabels": ["Q2 2025", "Q1 2026", "Q2 2026"],
            "values": [ttm_fcf_prior, ttm_fcf_prev, ttm_fcf_cur],
            "legend": "TTM 自由现金流",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "note": (
                "只使用公司在各季 release 现金流附注中给出的 TTM 口径，不自行拼接未披露季度；"
                f"较上季 {change(ttm_fcf_cur, ttm_fcf_prev)}，与单季 FCF 转负方向一致。"
            ),
            "src_extra": source_note("TTM 自由现金流为公司披露口径"),
        },
        {
            "n": 10,
            "kind": "bars_labeled",
            "title": "Cloud backlog 创 $514B 新高，但单季净增降至 $52B",
            "xlabels": ["Q4 2025", "Q1 2026", "Q2 2026"],
            "values": [240, 462, 514],
            "legend": "Cloud backlog",
            "fmt": "usd0",
            "yfmt": "usd0",
            "label_fmt": "usd0",
            "ylab": "$B",
            "note": (
                "backlog 绝对值仍强，但净增由 Q1 的 +$222B 正常化至 +$52B；"
                f"覆盖 TTM Cloud 收入 {coverage_cur:.2f}x（上季 {coverage_prev:.2f}x）。"
            ),
            "src_extra": (
                "backlog 来自公司季度电话会，非利润表项目；Q1 2026 纳入 TPU hardware "
                "agreements，跨季可比性有限。净增与覆盖倍数为自算，可由经营面板复核。"
            ),
        },
        {
            "n": 11,
            "kind": "diverging_bars",
            "title": "Q2 选择性资本项目：股权融资 $49.6B、CapEx $44.9B",
            "xlabels": ["普通股增发", "优先股", "净发债", "CapEx", "非上市股权", "普通股股息", "SBC 税款"],
            "values": [30.499, 19.063, 21.071, -44.924, -21.145, -2.689, -6.573],
            "legend": "资金来源为正 / 现金用途为负",
            "positive_label": "资金来源",
            "negative_label": "现金用途",
            "fmt": "usd1",
            "yfmt": "usd1",
            "label_fmt": "usd1",
            "ylab": "$B",
            "zero_line": True,
            "note": (
                "回购连续第二季为 $0；图中是选择性融资与用途项目，并非完整现金桥，"
                "正负柱不应被相加为期末现金变动。"
            ),
            "src_extra": source_note("普通股、优先股、债务及主要用途来自 Q2 cash-flow / equity disclosures"),
        },
    ]

    # --- layer 1: the fixed operating panel --------------------------------
    revenue_heads = [compact(label) for label in revenue_labels]
    cash_heads = [compact(label) for label in cash_labels]

    def trend_row(label: str, values: list[float | None], formatter, derived: bool = False) -> dict:
        return panel_row(
            label,
            ["—" if value is None else formatter(value) for value in values],
            derived,
        )

    panel_groups = [
        panel_group(
            "trend_revenue",
            "八季趋势 · 收入结构",
            revenue_heads,
            [
                trend_row("总收入", revenue_values, lambda v: f"${v:,.0f}M"),
                trend_row("总收入 YoY", revenue_yoy, lambda v: f"{v:+.1f}%"),
                trend_row("Search & other", column(revenue, "Search & other"), lambda v: f"${v:,.0f}M"),
                trend_row("YouTube ads", column(revenue, "YouTube ads"), lambda v: f"${v:,.0f}M"),
                trend_row("Google Cloud", cloud_values, lambda v: f"${v:,.0f}M"),
                trend_row("Cloud YoY", cloud_yoy, lambda v: f"{v:+.1f}%"),
                trend_row("Cloud 经营利润率", cloud_opm, lambda v: f"{v:.2f}%", derived=True),
            ],
            "分项 YoY 只在公司披露口径可回源的季度给出；空白表示该季未在本页数据中回源。",
            open_by_default=True,
        ),
        panel_group(
            "trend_cash",
            "七季趋势 · 现金流与资本强度",
            cash_heads,
            [
                trend_row("经营现金流", ocf_values, lambda v: f"${v:,.0f}M"),
                trend_row("CapEx", capex_values, lambda v: f"${v:,.0f}M"),
                trend_row("自由现金流", fcf_values, lambda v: f"${v:,.0f}M", derived=True),
                trend_row("CapEx / 收入", capex_intensity, lambda v: f"{v:.1f}%", derived=True),
            ],
            "自由现金流 = 经营现金流 − 购买物业及设备；Q3 2024 现金流未在本页数据中回源。",
            open_by_default=True,
        ),
        panel_group(
            "quarter_segments",
            "本季明细 · 收入与分部盈利",
            PANEL_HEADS,
            [
                summary_row(staging, "总收入"),
                summary_row(staging, "固定汇率收入 YoY"),
                summary_row(staging, "Google Services"),
                summary_row(staging, "— Search & other", "Search & other"),
                summary_row(staging, "— YouTube ads", "YouTube ads"),
                summary_row(staging, "— Google Network", "Google Network"),
                summary_row(staging, "— 订阅/平台/设备", "订阅 / 平台 / 设备"),
                panel_row(
                    "广告收入合计",
                    [money(ads_cur), money(ads_prev), money(ads_prior),
                     change(ads_cur, ads_prev), change(ads_cur, ads_prior)],
                    derived=True,
                ),
                summary_row(staging, "Google Cloud"),
                summary_row(staging, "Other Bets"),
                summary_row(staging, "经营利润"),
                summary_row(staging, "经营利润率", derived=True),
                summary_row(staging, "— Services OPM", "Services OPM", derived=True),
                summary_row(staging, "— Cloud OPM", "Cloud OPM", derived=True),
                summary_row(staging, "— Other Bets OI", "Other Bets 经营损益"),
                summary_row(staging, "— Alphabet-level", "Alphabet-level 成本"),
            ],
            "广告收入合计 = Search & other + YouTube ads + Google Network（自算），用于 TAC 率的分母。",
            open_by_default=True,
        ),
        panel_group(
            "quarter_cost",
            "本季明细 · 成本与效率",
            PANEL_HEADS,
            [
                summary_row(staging, "折旧"),
                panel_row(
                    "折旧 / 收入",
                    [pct(dep_ratio[0]), pct(dep_ratio[1]), pct(dep_ratio[2]),
                     gap(dep_ratio[0], dep_ratio[1]), gap(dep_ratio[0], dep_ratio[2])],
                    derived=True,
                ),
                summary_row(staging, "股权激励费用"),
                panel_row(
                    "股权激励 / 收入",
                    [pct(sbc_ratio[0]), pct(sbc_ratio[1]), pct(sbc_ratio[2]),
                     gap(sbc_ratio[0], sbc_ratio[1]), gap(sbc_ratio[0], sbc_ratio[2])],
                    derived=True,
                ),
                summary_row(staging, "总 TAC"),
                panel_row(
                    "TAC / 广告收入",
                    [pct(tac_ratio[0]), pct(tac_ratio[1]), pct(tac_ratio[2]),
                     gap(tac_ratio[0], tac_ratio[1]), gap(tac_ratio[0], tac_ratio[2])],
                    derived=True,
                ),
                summary_row(staging, "员工人数"),
                panel_row(
                    "人均季度收入",
                    [
                        "—" if revenue_per_head[0] is None else f"${revenue_per_head[0]:,.0f}K",
                        "—" if revenue_per_head[1] is None else f"${revenue_per_head[1]:,.0f}K",
                        "—" if revenue_per_head[2] is None else f"${revenue_per_head[2]:,.0f}K",
                        change(revenue_per_head[0], revenue_per_head[1]),
                        change(revenue_per_head[0], revenue_per_head[2]),
                    ],
                    derived=True,
                ),
            ],
            "公司未按季披露收入成本 / R&D / S&M / G&A 四条费用线的本页回源值，本组暂不包含；"
            "TAC 率用广告收入作分母，避免被 Cloud 增长稀释。",
        ),
        panel_group(
            "quarter_quality",
            "本季明细 · 盈利质量",
            PANEL_HEADS,
            [
                summary_row(staging, "OI&E"),
                summary_row(staging, "— 权益证券收益", "其中：权益证券收益"),
                panel_row(
                    "权益证券收益 / 净利润",
                    [pct(equity_share[0], 1), pct(equity_share[1], 1), pct(equity_share[2], 1),
                     gap(equity_share[0], equity_share[1], 1), gap(equity_share[0], equity_share[2], 1)],
                    derived=True,
                ),
                summary_row(staging, "净利润（归属普通股）"),
                summary_row(staging, "GAAP 摊薄 EPS"),
                summary_row(
                    staging,
                    "EPS（剔权益证券收益，简单自算）",
                    "EPS（剔权益证券收益，简单自算）",
                    derived=True,
                ),
            ],
            "剔除口径只做 GAAP EPS 减去公司披露的权益收益每股贡献，不构造 non-GAAP 或‘经营 EPS’。",
        ),
        panel_group(
            "quarter_capital",
            "本季明细 · 现金、资本配置与前瞻",
            PANEL_HEADS,
            [
                summary_row(staging, "经营现金流"),
                summary_row(staging, "CapEx"),
                summary_row(staging, "自由现金流"),
                summary_row(staging, "TTM 自由现金流"),
                summary_row(staging, "股票回购"),
                summary_row(staging, "长期债务"),
                summary_row(staging, "Cloud backlog"),
                panel_row(
                    "backlog / TTM Cloud 收入",
                    [f"{coverage_cur:.2f}x", f"{coverage_prev:.2f}x", "—",
                     f"{coverage_cur - coverage_prev:+.2f}x", "—"],
                    derived=True,
                ),
            ],
            "Cloud backlog 来自季度电话会口径，Q1 2026 纳入 TPU hardware agreements，跨季可比性有限；"
            "覆盖倍数分母为最近四季 Cloud 收入（自算）。"
            f"TTM 自由现金流的 y/y 沿用源表口径 -27.6%，与本表 Q2 2025 列的简单比值"
            f"（{change(ttm_fcf_cur, ttm_fcf_prior)}）不一致，已标记待回源核对。",
        ),
    ]

    return {
        "schema_version": "quarterly-dashboard/googl-v2",
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
            "经营端仍在加速——Cloud 收入 +81.8%、OPM 35.6%；但本季真正改变这家公司的是资金结构："
            "单季 FCF 转负、回购归零、外部股权融资 $49.6B。两条线由 Cloud 收入增速与折旧增速的相对位置决定收敛还是背离。"
        ),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>经营</span><b>Cloud 的收入与利润率同步加速</b>'
            '<p>$24.8B 收入、35.6% OPM；两项指标已连续八季同向上升。</p></article>'
            '<article><span>质量</span><b>GAAP EPS 受权益证券收益显著影响</b>'
            '<p>$9.11 中 $6.26 来自权益证券收益；简单扣除后约 $2.85。</p></article>'
            '<article><span>资本</span><b>本季使用大额外部股权融资</b>'
            '<p>CapEx $44.9B、FCF -$5.9B、回购 $0，股权融资合计 $49.6B。</p></article>'
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
        "summary": {"blocks": [board]},
        "guidance": {
            "title": "资本开支节奏与指引口径",
            "headers": ["项目", "数值", "说明"],
            "rows": [
                ["Q2 2026 CapEx", money(capex_values[-1]),
                 f"同比 {change(capex_values[-1], capex_values[-5])}；"
                 f"占收入 {capex_intensity[-1]:.1f}% D"],
                ["H1 2026 CapEx 合计", money(capex_h1),
                 f"Q1 {money(capex_values[-2])} + Q2 {money(capex_values[-1])} D"],
                ["最近四季 CapEx 合计", money(capex_ttm), "Q3 2025 起滚动四季合计 D"],
                ["FY2026 CapEx 指引", "本页未接入",
                 "全年区间由公司在电话会给出；本页只发布能在来源清单里回源的披露值，待补录后上线"],
                ["股票回购", money(buyback_cur),
                 f"连续两季为 $0；Q2 2025 为 {money(buyback_prior)}"],
                ["本季股权融资", f"${equity_raise:,.1f}B",
                 "普通股增发 $30.5B + 优先股 $19.1B D"],
            ],
            "note": "本表不含公司未在本页来源清单回源的前瞻区间；D = Derived / 自算。",
        },
        "sections": [
            {
                "id": "operating_momentum",
                "title": "经营动能",
                "description": "先看增长是否来自可持续的主营业务，再看增长质量。",
                "exhibits": exhibits[0:3],
            },
            {
                "id": "cost_quality",
                "title": "成本结构与盈利质量",
                "description": "折旧与 SBC 决定利润的底噪，一次性权益收益决定 headline 能不能用。",
                "exhibits": exhibits[3:5],
            },
            {
                "id": "capital_cash",
                "title": "资本强度与现金转换",
                "description": "增长的现金成本：资本强度、单季自由现金流与 TTM 口径三条线一起看。",
                "exhibits": exhibits[5:8],
            },
            {
                "id": "leading_capital",
                "title": "前瞻指标与资本配置",
                "description": "backlog 提供收入可见度；融资与现金用途决定这轮建设的股东成本。",
                "exhibits": exhibits[8:10],
            },
        ],
        "panel": {
            "title": "季度经营面板",
            "description": "固定字段、每季只填数：先看八季趋势，再看本季与上季、去年同期的明细。",
            "groups": panel_groups,
        },
        "tables": [cross_capex_table(12)],
        "notes": [
            "本页分两层：Exhibit 1 跟踪盘只放带阈值与触发动作的指标；季度经营面板是固定字段的全景表，字段不随季度主题变化。",
            "跟踪盘的阈值是本地研究设定，不是公司指引，也不构成评级或投资建议。",
            "本页只发布公司披露值与可复算的简单派生值；D 标记代表 Derived / 自算。",
            "不发布评级、目标价、估值、卖方共识或未经 Alphabet 确认的客户集中度估算。",
            "$2.85 仅做 $9.11 − $6.26 的算术拆分，不命名为经营 EPS，也不等同公司定义的 non-GAAP 指标。",
            "TTM 自由现金流只使用公司在 release 中披露的 TTM 口径，不自行拼接未披露季度。",
            "Cloud backlog 来自季度电话会口径；公司未披露取消额、外汇调整或客户集中度。",
            "Q4 2025 总收入采用当季 earnings release 的 $113,828M；与最新 10-K 倒挤值存在 $1M 差异。",
            "本页已知未接入：收入成本 / R&D / S&M / G&A 四条费用线、有效税率、稀释股数、paid clicks 与 CPC、"
            "以及电话会口径的 Gemini、订阅、Waymo 等运营 KPI。",
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
    print("GOOGL page: tracking board + 10 charts + 6 panel groups")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
