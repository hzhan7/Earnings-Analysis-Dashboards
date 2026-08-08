#!/usr/bin/env python3
"""Build the GOOGL quarterly-results prototype.

The source-of-truth for this prototype is ``series/googl.json``, which is an
auditable extraction of the user's latest local earnings-analysis note.  The
page deliberately excludes ratings, valuation, sell-side consensus and
unverified external estimates; every published number is either company-
reported or a transparent arithmetic derivation from reported figures.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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
    number = float(match.group(0).replace(",", ""))
    return -abs(number) if negative else number


def number(value: str | None) -> float | None:
    return parse_number(value or "")


def trend(staging: dict, title: str) -> dict:
    return next(item for item in staging["trends"] if item["title"] == title)


def column(table: dict, heading: str) -> list[float | None]:
    index = table["headers"].index(heading)
    return [number(row[index]) for row in table["rows"]]


def snapshot_row(staging: dict, label: str) -> list[str]:
    return next(row for row in staging["snapshot"]["rows"] if row[0] == label)


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


def build_payload(staging: dict) -> dict:
    revenue = trend(staging, "八季度趋势（收入侧）")
    cash = trend(staging, "八季度趋势（现金与资本强度）")

    revenue_labels = [row[0].replace("Q", "Q") for row in revenue["rows"]]
    cash_labels = [row[0] for row in cash["rows"]]

    revenue_values = column(revenue, "总收入")
    revenue_yoy = column(revenue, "YoY")
    search_yoy = [number(row[4]) for row in revenue["rows"]][-4:]
    youtube_yoy = [number(row[6]) for row in revenue["rows"]][-4:]
    cloud_values = column(revenue, "Cloud")
    cloud_opm = column(revenue, "Cloud OPM")
    fcf_values = column(cash, "自由现金流")
    capex_intensity = column(cash, "CapEx/收入")

    source = (
        'Source: <a href="https://abc.xyz/investor/" rel="noopener">Alphabet Investor Relations</a>'
        '（Q2 2026 earnings release / call；历史季度 release 经 SEC EDGAR 回源）。'
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
            "full": True,
        },
        {
            "n": 5,
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
            "full": True,
        },
        {
            "n": 6,
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
                "Q1 含 TPU hardware agreements，跨季比较标记为 limited。"
            ),
            "src_extra": (
                "backlog 来自公司季度电话会，非利润表项目；Q1 2026 纳入 TPU hardware "
                "agreements，跨季可比性有限。净增为自算，可由表格视图复核。"
            ),
            "full": True,
        },
        {
            "n": 9,
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
            "full": True,
        },
    ]

    summary_rows = [
        summary_row(staging, "总收入"),
        summary_row(staging, "— Search & other", "Search & other"),
        summary_row(staging, "— YouTube ads", "YouTube ads"),
        summary_row(staging, "Google Cloud"),
        summary_row(staging, "— Cloud OPM", "Cloud OPM", derived=True),
        summary_row(staging, "经营利润率", derived=True),
        summary_row(
            staging,
            "EPS（剔权益证券收益，简单自算）",
            "EPS（剔权益证券收益，简单自算）",
            derived=True,
        ),
        summary_row(staging, "经营现金流"),
        summary_row(staging, "CapEx"),
        summary_row(staging, "自由现金流"),
        summary_row(staging, "Cloud backlog"),
    ]

    return {
        "schema_version": "quarterly-dashboard/googl-prototype-v1",
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
        "tracker": "Watchlist Quarterly Tracker · GOOGL prototype",
        "title": "Alphabet (GOOGL)：Q2 2026 季报仪表盘",
        "subtitle": "截至 2026-06-30 · 发布 2026-07-22 · US GAAP · 未审计 · 金额单位为 $M，另有注明除外",
        "headline": (
            "经营动能创新高，但资本密度已经改变公司：Cloud 收入 +81.8%、OPM 35.6%，"
            "同时单季 FCF 转负、回购归零并完成 $49.6B 股权融资。"
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
        "summary": {
            "blocks": [{
                "id": "quarterly",
                "title": "关键财务与经营读数",
                "frequency": "quarterly",
                "heads": ["Q2 2026", "Q1 2026", "Q2 2025", "q/q", "y/y"],
                "sep": 3,
                "rows": summary_rows,
                "note": "D = Derived / 自算；当前季度仅用浅蓝底标识，不用红绿判断经营好坏。",
            }]
        },
        "sections": [
            {
                "id": "operating_momentum",
                "title": "经营动能",
                "description": "先看增长是否来自可持续的主营业务，再看增长质量。",
                "exhibits": exhibits[0:3],
            },
            {
                "id": "earnings_cash",
                "title": "盈利质量与现金转换",
                "description": "把一次性权益收益、自由现金流和资本强度分开看。",
                "exhibits": [exhibits[3], exhibits[5], exhibits[4]],
            },
            {
                "id": "leading_capital",
                "title": "前瞻指标与资本配置",
                "description": "backlog 提供收入可见度；融资与现金用途决定这轮建设的股东成本。",
                "exhibits": exhibits[6:8],
            },
        ],
        "guidance": None,
        "tables": [
            {
                "n": 10,
                "title": revenue["title"],
                "headers": revenue["headers"],
                "rows": revenue["rows"],
            },
            {
                "n": 11,
                "title": cash["title"].replace("八季度", "七季度"),
                "headers": cash["headers"],
                "rows": cash["rows"],
            },
        ],
        "notes": [
            "本页只发布公司披露值与可复算的简单派生值；D 标记代表 Derived / 自算。",
            "不发布评级、目标价、估值、卖方共识或未经 Alphabet 确认的客户集中度估算。",
            "$2.85 仅做 $9.11 − $6.26 的算术拆分，不命名为经营 EPS，也不等同公司定义的 non-GAAP 指标。",
            "Cloud backlog 来自季度电话会口径；公司未披露取消额、外汇调整或客户集中度。",
            "Q4 2025 总收入采用当季 earnings release 的 $113,828M；与最新 10-K 倒挤值存在 $1M 差异。",
            "图题采用结论式写法，图下文字控制为一句事实 + 一句解释；所有图可切换为表格核对。",
        ],
        "footer": (
            "GOOGL quarterly-results prototype · 数据来自 Alphabet 公开披露与本地已核对分析稿 · "
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
    print("GOOGL prototype: 8 charts + 1 scorecard + 2 audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
