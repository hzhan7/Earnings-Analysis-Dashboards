#!/usr/bin/env python3
"""Build the TJX quarterly-results page.

Same four-part, chart-led shape as the other company pages (上季兑现 → 本季重点
→ 下季跟踪 → 长期常规).  TJX's fiscal year ends at the end of January, so every
label here is the calendar quarter the fiscal one mostly covers: the thirteen
weeks ended 2026-08-01 are the company's FY2027 Q2 and this page's ``Q2 2026``.

TJX is the first non-technology company on this site, and what it brings is the
longest guidance record here by a wide margin.  Every quarterly earnings 8-K
EX-99.1 carries an Outlook paragraph, and from Q1 FY2013 onward that paragraph
guides next-quarter diluted EPS in the same sentence structure -- fifty-two
guided quarters, forty-nine of them finished.  Pretax profit margin joins the
paragraph in 2022 and consolidated comparable sales in 2023, so the three
records have three different lengths and each chart is drawn over its own.

The answer is the most one-sided on this site, and it is one shape rather than
two: reported EPS cleared the top of its guided range in 38 of 49 quarters,
landed inside it 8 times, and broke the bottom **three** times -- a half-cent
miss in 2014, the pandemic quarter, and the 2022 inflation shock.  Pretax margin
cleared the top 15 times in 16 and missed once, for a reason the company names
in the same release (an unplanned shrink charge).  Consolidated comp never once
landed below its floor.  All three guided numbers behave like floors.

Two things stop that from being a tautology, and both are on the charts.  TJX
publishes each quarter's outlook **9 to 24 days into the quarter it guides** --
the release goes out with the previous quarter's results -- so this is not an
ex-ante forecast.  And the company withdrew guidance entirely for seven quarters
in 2020-2021, which is the stretch a "never missed" count would otherwise
delete.

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
    delivery_band,
    headroom_exhibit,
    midpoint_deviation,
    number_exhibits,
    threshold_exhibit,
    threshold_table,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "tjx.json"
DATA_DIR = ROOT / "data"


def compact_period(period: str) -> str:
    """``'Q2 2026'`` → ``'Q2'26'``."""
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


def _ordinal(period: str) -> int:
    """``'Q2 2026'`` → a running quarter number, so gaps in the axis are findable."""
    quarter, year = period.split()
    return int(year) * 4 + int(quarter[1])


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def rounded(values: list[float | None], digits: int = 6) -> list[float | None]:
    return [None if value is None else round(value, digits) for value in values]


def resolve_exhibit_refs(exhibits: list[dict]) -> list[dict]:
    """Substitute ``{ref}`` placeholders with the numbers `number_exhibits` assigned."""
    numbers = {exhibit["ref"]: exhibit["n"] for exhibit in exhibits if exhibit.get("ref")}
    for exhibit in exhibits:
        exhibit.pop("ref", None)
        for field in ("title", "note", "src_extra", "annot"):
            text = exhibit.get(field)
            if not isinstance(text, str):
                continue
            for key, number in numbers.items():
                text = text.replace("{" + key + "}", str(number))
            exhibit[field] = text
    return exhibits


SOURCE_8K = (
    "指引区间来自各季业绩 8-K 的 EX-99.1 新闻稿末尾那段 Outlook —— 公司在同一段里"
    "用同一种句式给出下一季与全年的 comp、税前利润率与每股收益；"
    "实际值来自随后一季 8-K 的 Financial Summary 合并损益表。"
)

# The outlook goes out with the *previous* quarter's results, and TJX reports
# about three weeks after a quarter ends, so the release lands inside the
# quarter being guided. Named on every chart in this group: a record of never
# missing means something weaker when part of the quarter is already banked.
TIMING = "该季<b>开始后 9–24 天</b>"

LAG_NOTE = (
    "<b>先读这一句，再读命中率。</b>TJX 的下一季指引是随上一季业绩一起发布的，"
    "而它在季末约三周后发业绩，所以这段 Outlook 落在<b>它所指引的那个季度之内</b>："
    "本记录里最早的一次是第 9 天、最晚的一次是第 24 天，平均第 18 天，"
    "即公司给出区间时该季已经过去一到四分之一。"
    "会计季 Q1 最迟（24 天），因为它要等 2 月的年度业绩发布。"
    "这不是一份事前预测；"
    "一页把「几乎没跌破过」放着不加这句话，就是把同义反复当成发现。"
)

DEV_TIMING = "（口径提醒：本组每张图的指引都是在该季<b>开始后 9–24 天</b>才发布的。）"

COVID_BREAK_LABEL = "指引中断 7 个季度（COVID-19）"
COVID_BREAK_NOTE = (
    "<b>红色竖线是记录里的断口。</b>公司在 2020 年 5 月到 2021 年 11 月的五份业绩稿里"
    "写明 is not providing guidance at this time，连续 7 个会计季没有给出任何数字指引；"
    "横轴在这里从 Q1 2020 直接跳到 Q1 2022，中间的季度不是漏掉，而是本来就没有指引可对。"
    "一份只数「没跌破过多少次」的记录会把这段一起删掉，这里保留它。"
)


# ── section one: the guided record ──────────────────────────────────────────
def guidance_delivery_charts(staging: dict) -> tuple[list[dict], dict]:
    """Three guided metrics, three different windows, one shape.

    TJX guides next-quarter diluted EPS, pretax profit margin and consolidated
    comparable sales in the same Outlook paragraph, but it did not start guiding
    them at the same time -- EPS runs back to Q1 FY2013, the margin to Q3 FY2023
    and comp to Q1 FY2024.  Each chart is drawn over its own metric's record
    rather than over the shortest one they share, and each title says how long
    that record is.

    Where the company published an adjusted figure *and* judged the quarter
    against plan on that basis, the adjusted figure is what the chart compares:
    the tariff refunds of FY2027 and the litigation settlement of FY2026 Q4 did
    not exist when the range was set, so scoring them against the reported
    number would score the guidance against an event it could not contain.  The
    release says which basis in as many words ("adjusted diluted earnings per
    share of $1.22 ... well above the Company's plan").
    """
    record = staging["quarterly_guidance_history"]
    quarters = record["quarters"]
    labels = [compact_period(quarter) for quarter in quarters]
    lag = record["publication_lag_days"]

    eps_lo = record["guide_eps_lo_usd"]
    eps_hi = record["guide_eps_hi_usd"]
    eps_actual = record["actual_eps_usd"]

    # The withdrawn quarters are absent from these arrays -- there was no
    # guidance to plot -- so the break marker goes where the axis jumps.
    resumed = next(index for index in range(1, len(quarters))
                   if _ordinal(quarters[index]) - _ordinal(quarters[index - 1]) > 1)
    eps_finished = [index for index, value in enumerate(eps_actual) if value is not None]

    above = [i for i in eps_finished if eps_actual[i] > eps_hi[i]]
    below = [i for i in eps_finished if eps_actual[i] < eps_lo[i]]
    inside = len(eps_finished) - len(above) - len(below)

    # ── EPS: level over a readable window, distance over the whole record ────
    # Post-split EPS runs from US$0.22 to US$1.43 across the full record, so a
    # linear axis over all of it collapses the early ranges to a hairline. The
    # band chart takes the recent window and the scale-free deviation chart
    # carries the rest -- the same split NVIDIA's page makes for the same reason.
    window = 16
    eps_band = delivery_band(
        "EX_EPS_RANGE", "摊薄每股收益", labels[-window:], eps_lo[-window:], eps_hi[-window:],
        eps_actual[-window:], fmt="usd2", ylab="US$", unit="US$",
        venue="业绩发布", timing=TIMING, scope=f"（近 {window} 季）",
        src_extra=SOURCE_8K,
        extra_note=(
            f"<b>整段记录（{len(quarters)} 季指引、{len(eps_finished)} 季已完结）不在这张图上，"
            f"在它的下一张。</b>本图只画最近 {window} 季，因为拆股调整后的每股数"
            "从 US$0.22 长到 US$1.43，一条线性纵轴放不下整段记录而不把早年的区间压成一根发丝。"
            + LAG_NOTE
        ),
    )
    eps_dev = midpoint_deviation(
        "EX_EPS_DEV", "摊薄每股收益", quarters, eps_lo, eps_hi, eps_actual,
        mode="pct", window=len(eps_finished), label=compact_period, bar_labels=False,
        src_extra=SOURCE_8K + "偏离为实际每股收益除以指引中值的自算值。",
        extra_note=(
            f"<b>这才是完整记录：{len(eps_finished)} 个已完结季里 {len(above)} 季高于指引上限、"
            f"{inside} 季落在区间内、{len(below)} 季跌破下限。</b>"
            "柱子几乎清一色朝上，而且没有随时间收窄 —— 这家公司十几年来一直把"
            "下一季的每股收益指引设在自己大概率能过的位置。"
            "三次跌破各有各的原因，不是同一类事：Q1'14 差 US$0.005（拆股调整后），"
            "Q1'20 是门店大面积关闭的疫情季，Q1'22 是 2022 年的成本冲击。"
            "2018 年 11 月一拆二之前公布的指引与实际都已除以 2 换算到当前股本，"
            "该换算是精确的；本图取的是比值，拆股本来也约掉了。"
            + COVID_BREAK_NOTE
            + DEV_TIMING
        ),
    )

    # ── pretax profit margin ─────────────────────────────────────────────────
    margin_lo = record["guide_pretax_margin_lo_pct"]
    margin_hi = record["guide_pretax_margin_hi_pct"]
    margin_actual = record["actual_pretax_margin_pct"]
    m_start = next(i for i, value in enumerate(margin_lo) if value is not None)
    m_labels = labels[m_start:]
    m_lo, m_hi = margin_lo[m_start:], margin_hi[m_start:]
    m_actual = margin_actual[m_start:]
    m_finished = [i for i, value in enumerate(m_actual) if value is not None]

    margin_band = delivery_band(
        "EX_PTM_RANGE", "税前利润率", m_labels, m_lo, m_hi, m_actual,
        fmt="pct1", ylab="%", unit="%", venue="业绩发布", timing=TIMING,
        src_extra=SOURCE_8K,
        extra_note=(
            f"税前利润率的指引从 Q3'22 才开始出现在这段 Outlook 里，所以它的记录只有 "
            f"{len(m_labels)} 季，比上面每股收益那条短得多 —— 图只画到数字存在的地方，不往前补。"
            "<b>唯一一次跌破是 Q4'22 的 9.2% 对 9.5–9.8%</b>，"
            "公司在同一份新闻稿里自己写了原因："
            "below the Company's plan due to an unplanned shrink charge，"
            "并说指引原本假设存货损耗会带来 0.5 个百分点的<b>顺风</b>，实际是 0.6 个百分点的逆风。"
            "这是本站少见的一次「公司自报没做到并给出科目」。"
        ),
    )
    margin_dev = midpoint_deviation(
        "EX_PTM_DEV", "税前利润率", quarters[m_start:], m_lo, m_hi, m_actual,
        mode="pp", window=len(m_finished), label=compact_period,
        src_extra=SOURCE_8K + "偏离为实际税前利润率减去指引中值的自算值。",
        extra_note=(
            "有两个季度用的是公司自己的调整后口径，而不是报表口径，因为指引给出时"
            "那件事还不存在：Q4'25 的诉讼和解与 Q2'26 的 IEEPA 关税退款都是指引之后发生的，"
            "拿报表值去对当初的区间，等于让指引为它装不下的事负责。"
            "公司自己也是按调整后口径判定这两季 well above the Company's plan 的。"
            + DEV_TIMING
        ),
    )

    # ── consolidated comparable sales ────────────────────────────────────────
    comp_lo = record["guide_comp_lo_pct"]
    comp_hi = record["guide_comp_hi_pct"]
    comp_actual = record["actual_comp_pct"]
    c_start = next(i for i, value in enumerate(comp_lo) if value is not None)
    c_labels = labels[c_start:]
    c_lo, c_hi = comp_lo[c_start:], comp_hi[c_start:]
    c_actual = [None if value is None else float(value) for value in comp_actual[c_start:]]
    c_finished = [i for i, value in enumerate(c_actual) if value is not None]
    c_above = [i for i in c_finished if c_actual[i] > c_hi[i]]
    c_inside = len(c_finished) - len(c_above)

    comp_band = delivery_band(
        "EX_COMP_RANGE", "合并同店销售", c_labels, c_lo, c_hi, c_actual,
        fmt="pct0", ylab="%", unit="%", venue="业绩发布", timing=TIMING,
        src_extra=SOURCE_8K,
        extra_note=(
            f"合并口径的 comp 指引从 Q1'23 才开始，因此这条记录只有 {len(c_labels)} 季。"
            f"{len(c_finished)} 个已完结季里 {len(c_above)} 季超出上限、{c_inside} 季落在区间内，"
            "<b>一次都没有跌破过下限</b>。"
            "<b>但这张图要打一个折扣：comp 是按整数百分点披露的。</b>"
            "落在 2–3% 区间上沿的那几季报的都是「+3%」，真值区间是 2.5–3.5%，"
            "其中一半在区间外 —— 所以「落在区间内」这一格在本图上比在其他图上软。"
            "更早的 Q1'22–Q4'22 公司指引的是<b>美国</b> comp 而不是合并 comp，口径不同，本页不接进来。"
        ),
    )
    comp_dev = midpoint_deviation(
        "EX_COMP_DEV", "合并同店销售", quarters[c_start:], c_lo, c_hi, c_actual,
        mode="pp", window=len(c_finished), label=compact_period,
        src_extra=SOURCE_8K + "偏离为实际 comp 减去指引中值的自算值。",
        extra_note=(
            f"指引中值这 {len(c_finished)} 季里有 12 季是同一个数（2.5%），"
            "所以这张图基本等于把实际 comp 重画了一遍 —— 这本身就是读数："
            "公司几乎每季都给同一个区间，真正在动的只有实际值。"
            + DEV_TIMING
        ),
    )

    delivery_rows = []
    for index in range(len(quarters) - 1, -1, -1):
        if len(delivery_rows) >= 20:
            break
        actual_eps = eps_actual[index]
        delivery_rows.append([
            quarters[index],
            record["fiscal_labels"][index],
            record["guidance_published"][index],
            f"${eps_lo[index]:.2f}–{eps_hi[index]:.2f}",
            f"${actual_eps:.2f}" if actual_eps is not None else "待披露",
            (f"{margin_lo[index]:.1f}–{margin_hi[index]:.1f}%"
             if margin_lo[index] is not None else "—"),
            (f"{margin_actual[index]:.2f}%"
             if margin_actual[index] is not None else "待披露"),
            (f"{comp_lo[index]:.0f}–{comp_hi[index]:.0f}%"
             if comp_lo[index] is not None else "—"),
            (f"{comp_actual[index]:.0f}%" if comp_actual[index] is not None else "待披露"),
        ])
    delivery_table = {
        "title": (
            f"指引兑现明细（最近 20 季；完整记录 {len(quarters)} 季，"
            f"发布时该季已过去 {lag['min']}–{lag['max']} 天）"
        ),
        "headers": ["自然年季度", "公司财季", "指引发布日", "EPS 指引", "EPS 实际",
                    "税前利润率指引", "税前利润率实际", "comp 指引", "comp 实际"],
        "rows": delivery_rows,
    }
    eps_dev["break_at"] = resumed
    eps_dev["break_label"] = COVID_BREAK_LABEL
    charts = [eps_band, eps_dev, margin_band, margin_dev, comp_band, comp_dev]
    return charts, delivery_table


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    labels = [compact_period(period) for period in periods]
    fin = staging["financials"]
    seg = staging["segments_usd_m"]
    segm = staging["segment_margins_pct"]
    comp = staging["comparable_sales_pct"]
    ops = staging["operations"]
    half = staging["half_year_usd_m"]
    long = staging["long_history"]
    adj_seg = staging["adjusted_segment_margins_pct"]
    guidance = staging["guidance"]
    closure = staging["followup_closure"]
    settled = staging["prior_kpi_settlement"]
    next_kpi = staging["next_kpi"]
    record = staging["quarterly_guidance_history"]

    sales = fin["net_sales_usd_m"]
    gross = fin["gross_margin_pct"]
    pretax_margin = fin["pretax_margin_pct"]
    eps = fin["diluted_eps_usd"]
    shares = fin["diluted_shares_m"]
    adjusted_gross = fin["adjusted_gross_margin_pct"]
    inventory_per_store = ops["inventory_per_store_usd_k"]
    stores = ops["store_count"]

    eps_finished = [index for index, value in enumerate(record["actual_eps_usd"])
                    if value is not None]
    eps_above = sum(1 for index in eps_finished
                    if record["actual_eps_usd"][index] > record["guide_eps_hi_usd"][index])
    eps_below = sum(1 for index in eps_finished
                    if record["actual_eps_usd"][index] < record["guide_eps_lo_usd"][index])
    margin_finished = sum(1 for lo, value in zip(record["guide_pretax_margin_lo_pct"],
                                                 record["actual_pretax_margin_pct"])
                          if lo is not None and value is not None)
    margin_above = sum(1 for lo, hi, value in zip(record["guide_pretax_margin_lo_pct"],
                                                  record["guide_pretax_margin_hi_pct"],
                                                  record["actual_pretax_margin_pct"])
                       if lo is not None and value is not None and value > hi)
    comp_finished = sum(1 for lo, value in zip(record["guide_comp_lo_pct"],
                                               record["actual_comp_pct"])
                        if lo is not None and value is not None)

    # Reported gross margin is the eight-quarter series; the company publishes an
    # adjusted one only in the two quarters that have an adjusting item. Both are
    # drawn rather than one being plotted and the other captioned.
    gross_settled = [adjusted_gross[i] if adjusted_gross[i] is not None else gross[i]
                     for i in range(len(gross))]
    # Inventory per store is one of the six series this file carries for the
    # reviewed eight quarters only, so its year-on-year line is a hole wherever
    # either leg is.
    inventory_yoy = [
        None if index < 4
        or inventory_per_store[index] is None
        or inventory_per_store[index - 4] is None
        else pct_change(inventory_per_store[index], inventory_per_store[index - 4])
        for index in range(len(inventory_per_store))
    ]

    # ── section 1: last quarter's thresholds, then the guided record ─────────
    settled_ex = [
        headroom_exhibit(
            "上季设下的五条阈值：两条已越线，三条仍在安全侧",
            settled, "actual",
            note=(
                "正值是仍在安全侧的余量，负值是已经越过阈值。"
                "<b>越线的两条指向同一件事：</b>"
                "占销售额六成的 Marmaxx，comp 只有 +1%，低于上季设的 +2% 门槛；"
                "而半年资本开支占销售额 3.93%，高于 3.8% 的纪律线 —— "
                "单店增长最弱的一季，恰好是资本强度最高的一季。"
                "<b>第六条阈值没有画进来，因为它不是 TJX 自己的数：</b>"
                "上季设的「Marmaxx 与同业同期 comp 差距连续两季 ≥8pp」要用另一家公司的申报值，"
                "该阈值本季确实触发（差距 9pp，两家的数各自见其 8-K），"
                "但本页只画能从 TJX 自身申报文件复算的序列，因此它只出现在核对表与说明里。"
            ),
            src_extra="阈值为上季本地研究设定，不是公司指引；当前值取自本季业绩 8-K 与自算。",
        ),
        threshold_exhibit(
            # Twelve of the forty-two quarters have no consolidated comp at all:
            # the Q1 FY2021 release printed none, seven quarters of 2020-2021
            # published only an "open-only" comp (sales measured against stores
            # that were actually open, which is a different measure), and the
            # 2022 releases gave U.S. comps only. Those are holes, not zeros.
            f"合并同店销售 {sum(1 for v in comp['consolidated'] if v is not None)} 季"
            f"（共 {len(labels)} 季）：本季 +4%，压着阈值过线",
            labels,
            [None if value is None else float(value) for value in comp["consolidated"]],
            4.0,
            fmt="pct0", ylab="%", actual_name="合并 comp", threshold_name="上季阈值 4%",
            note=(
                "上季设的门槛是「≥4% 才算指引折价的模式延续」。本季报出来正好 +4%，"
                "数值上过线，但构成变了：过线全靠 Marmaxx 以外的三个分部（+6~7%），见下一张。"
                "合并 comp 按整数披露，「+4%」的真值区间是 3.5–4.5%。"
            ),
            src_extra="comp 为公司披露的整数百分比，见各季 8-K 的 Comparable Sales by Division。",
        ),
        threshold_exhibit(
            "Marmaxx 同店销售八季：本季 +1%，八季最低，且是唯一交易笔数为负的分部",
            labels, [None if value is None else float(value) for value in comp["marmaxx"]], 2.0,
            fmt="pct0", ylab="%", actual_name="Marmaxx comp",
            threshold_name="管理层承诺的 Q4 下沿 2%",
            note=(
                "红线是管理层自己给的修复目标（会计季 Q4 回到 2–3%）的下沿。"
                "本季 +1%，环比从 +6% 掉下来 5 个百分点，是这八季的最低点。"
                "公司在新闻稿里把它写成 sales were below our expectations，"
                "并说这一分部的 comp entirely driven by a higher average basket, "
                "partially offset by a small decrease in customer transactions —— "
                "即客单价扛住了、来客数掉了。"
            ),
            src_extra="comp 与其驱动的定性描述均为公司披露；阈值为本地研究设定。",
        ),
        threshold_exhibit(
            f"毛利率八季：本季调整后 {adjusted_gross[-1]:.1f}%，高于上季设的 31.2%",
            labels, gross_settled, 31.2,
            fmt="pct1", ylab="%", actual_name="毛利率（有调整项的季度取调整后）",
            threshold_name="上季阈值 31.2%",
            note=(
                "上季的判断门槛设在调整后口径上，而八季历史只有报表口径存在，"
                "所以这条线在两个有调整项的季度（Q4'25、Q2'26）取公司自己披露的调整后值、"
                f"其余季度取报表值 —— 本季报表毛利率 {gross[-1]:.1f}%，调整后 {adjusted_gross[-1]:.1f}%，"
                "差的 2.0 个百分点是计入销货成本的关税退款。"
                "<b>阈值过线了，但归因换了轨：</b>公司把商品毛利率的改善主因写成 "
                "mostly due to tariff favorability，不是干净的商品力。"
            ),
            src_extra="报表毛利率为收入减销货成本的自算值；调整后毛利率为公司披露值。",
        ),
    ]
    guided_charts, delivery_table = guidance_delivery_charts(staging)
    settled_ex.extend(guided_charts)

    # ── section 2: what actually moved ──────────────────────────────────────
    highlight_ex = [
        {
            "kind": "grouped_bars",
            "title": "四个分部三强一弱：Marmaxx +1%，其余三个 +6~7%，国际是唯一环比加速的分部",
            "xlabels": ["Marmaxx", "HomeGoods", "TJX Canada", "TJX International"],
            "groups": [
                {"name": "去年同期 comp", "color": "GRAY",
                 "values": [float(comp[key][-5]) for key in
                            ("marmaxx", "homegoods", "canada", "international")]},
                {"name": "上季 comp", "color": "BLUE",
                 "values": [float(comp[key][-2]) for key in
                            ("marmaxx", "homegoods", "canada", "international")]},
                {"name": "本季 comp", "color": "NAVY",
                 "values": [float(comp[key][-1]) for key in
                            ("marmaxx", "homegoods", "canada", "international")]},
            ],
            "fmt": "pct0",
            "yfmt": "pct0",
            "label_fmt": "pct0",
            "ylab": "%",
            "note": (
                "把三根柱并排看，本季的分化比任何单季数字都清楚："
                "Marmaxx 从 +6% 掉到 +1%，International 从 +4% 升到 +7%（唯一加速的），"
                "Canada 与 HomeGoods 分别停在 +6% 与 +7%。"
                f"Marmaxx 占本季销售额 {seg['marmaxx_sales'][-1] / sales[-1] * 100:.1f}%，"
                "所以合并 comp 的 +4% 是被另外四成销售额扛出来的。"
            ),
            "src_extra": "各季 8-K 的 Comparable Sales by Division，公司披露的整数百分比。",
        },
        {
            "kind": "lines",
            "title": (
                f"分部利润率八季（报表口径）：HomeGoods 本季 {segm['homegoods_margin_pct'][-1]:.1f}%，"
                f"第一次高过 Marmaxx 的 {segm['marmaxx_margin_pct'][-1]:.1f}%"
            ),
            "xlabels": labels,
            "series": [
                {"name": "Marmaxx", "values": rounded(segm["marmaxx_margin_pct"]), "color": "NAVY"},
                {"name": "HomeGoods", "values": rounded(segm["homegoods_margin_pct"]), "color": "MBLUE"},
                {"name": "TJX Canada", "values": rounded(segm["canada_margin_pct"]), "color": "GOLD"},
                {"name": "TJX International", "values": rounded(segm["international_margin_pct"]), "color": "GRAY"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "end_label": True,
            "ylab": "%",
            "note": (
                "这是<b>报表</b>分部利润率（分部利润 ÷ 分部销售额，两端都是申报值）。"
                "本季它被关税退款推歪了：公司同时披露了退款对每个分部利润率的影响，"
                f"HomeGoods 被推高 {abs(adj_seg['homegoods']['tariff_refund_pp']):.1f} 个百分点、"
                f"Marmaxx {abs(adj_seg['marmaxx']['tariff_refund_pp']):.1f} 个百分点，"
                f"剔除后分别是 {adj_seg['homegoods']['adjusted']:.1f}% 与 {adj_seg['marmaxx']['adjusted']:.1f}%。"
                "<b>也就是说这张图上 HomeGoods 反超 Marmaxx 的那一笔，是退款画出来的，不是经营画出来的。</b>"
                "两个海外分部收到的是反方向的影响（计提了相关薪酬费用而没有退款），"
                f"所以 Canada 的调整后利润率 {adj_seg['canada']['adjusted']:.1f}% 反而高于报表值。"
            ),
            "src_extra": "分部销售额与分部利润来自各季 8-K 的分部表；退款对分部利润率的影响为公司披露值。",
        },
        {
            "kind": "grouped_bars",
            "title": "本季每股收益有两层壳，本页只画得出一层：报表 $1.36 → 公司调整后 $1.22",
            "xlabels": ["GAAP 报表", "扣关税退款净额", "公司调整后"],
            "groups": [{
                "name": "本季摊薄每股收益",
                "color": "NAVY",
                "values": [eps[-1], -round(eps[-1] - fin["adjusted_diluted_eps_usd"][-1], 2),
                           fin["adjusted_diluted_eps_usd"][-1]],
            }],
            "fmt": "usd2",
            "yfmt": "usd2",
            "label_fmt": "usd2",
            "ylab": "US$",
            "note": (
                "第一层是公司自己做的：$331M 关税退款减 $112M 相关增量薪酬计提，净 $219M 税前、"
                "每股 $0.14，报表 $1.36 因此调整为 $1.22。"
                "<b>第二层本页拒绝画：</b>公司说调整后毛利率的改善 mostly due to tariff favorability，"
                "即 $1.22 里仍然含着一段关税成本顺风 —— 但公司只给了 mostly 这个词，"
                "没有给过任何金额或百分点。把它换算成一个数需要自己挑一个比例，"
                "那是假设不是算术，本页不发布这种数（同 SNPS 页对 Ansys 季度收入的处理）。"
                "它被写在最后一节「本页不接入」里。"
            ),
            "src_extra": "退款金额、薪酬计提与每股影响均为本季 8-K 的披露值。",
        },
        {
            "kind": "grouped_bars",
            "title": "全年指引拆成两半：上半年调整后每股收益同比 +19.3%，下半年按指引中值隐含只有 +2.0%",
            "xlabels": ["上半年", "下半年（指引隐含）"],
            "groups": [
                {"name": "去年同期调整后每股收益", "color": "GRAY", "values": [2.02, 2.71]},
                {"name": "本年调整后每股收益", "color": "NAVY", "values": [2.41, 2.765]},
            ],
            "fmt": "usd2",
            "yfmt": "usd2",
            "label_fmt": "usd2",
            "ylab": "US$",
            "note": (
                "四个数全是申报值或减法：上半年 $2.41 是本季新闻稿印的；"
                "全年调整后指引中值 $5.175 减去它得到下半年隐含 $2.765；"
                "去年上半年 $2.02 与去年全年 $4.73 同样是公司印的，相减得去年下半年 $2.71。"
                "<b>17.3 个百分点的落差是本季最硬的一条。</b>"
                "而且公司这次把全年调整后指引从 $5.08–5.15 上调到 $5.15–5.20，"
                "上调幅度 $0.05–0.07 恰好等于本季超出指引中值的幅度 —— "
                "把上调前的中值同样拆一次，下半年隐含仍然是 $2.765，<b>一分没动</b>。"
            ),
            "src_extra": "各季与各年每股收益、全年指引区间均为公司披露值；上下半年拆分为减法。",
        },
        {
            "kind": "gs_bar",
            "title": (
                f"一般公司费用八季在 ${min(seg['general_corporate_expense'])}M–"
                f"${max(seg['general_corporate_expense'])}M 之间摆动，"
                "分部利润之和到税前利润的桥在单季维度不可读"
            ),
            "xlabels": labels,
            "values": seg["general_corporate_expense"],
            "legend": "一般公司费用",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "US$M",
            "ylab2": "同比",
            # The twelve-period average line is opt-in: the engine never
            # computes that average, it only draws a finite `avg12` handed to
            # it by the payload, and the line, its contribution to the y-axis
            # range and the legend key are all gated on that one condition
            # (see the `avg12` entry in the assets/charts.js header). A
            # `gs_bar` given neither field is simply a clean bar chart.
            # So `yoy` is not here to suppress an average -- it is here
            # because this one has a filed prior-year column to build it from,
            # and the resulting line is the argument the chart is making.
            "yoy": {
                "name": "同比增速 (RHS)",
                # The prior-year column is one of the six series carried for the
                # reviewed eight quarters only, so this line is a hole wherever
                # its own comparison base is.
                "values": [None if current is None or prior is None
                           else round(pct_change(current, prior), 4)
                           for current, prior
                           in zip(seg["general_corporate_expense"],
                                  seg["general_corporate_expense_prior_year"])],
                "color": "GREEN",
                "yfmt": "pct1",
            },
            "note": (
                f"本季 ${seg['general_corporate_expense'][-1]}M，去年同期 "
                f"${seg['general_corporate_expense'][-5]}M，同比多出 "
                f"${seg['general_corporate_expense'][-1] - seg['general_corporate_expense'][-5]}M；"
                f"但上半年累计 ${half['general_corporate_expense'][-1]}M 反而低于去年的 "
                f"${half['general_corporate_expense'][0]}M。"
                "<b>同一条费用线，单季同比 +33%，半年同比 −3%。</b>"
                "右轴那条绿线是它八季的单季同比：在 −33% 到 +44% 之间来回甩，没有方向可言。"
                "所以任何用「分部利润之和 − 公司费用 = 税前利润」做的单季推断都会被这条线带偏，"
                "跨季只能用半年口径。上季的 $143M 是这条线的八季低点，"
                "而且是从分部表直接读到的申报值，不必用半年数减本季数反推。"
            ),
            "src_extra": "各季 8-K 分部表的 General corporate expense 行，申报值。",
        },
        {
            "kind": "bar_line",
            "title": (
                f"每店存货八季：本季 ${inventory_per_store[-1] / 1000:.2f}M/店，"
                f"同比 {signed(inventory_yoy[-1])}，与 comp 的张力解除"
            ),
            "xlabels": labels,
            "bar": {"name": "每店存货 D", "color": "BLUE",
                    "values": [None if value is None else round(value / 1000, 4)
                       for value in inventory_per_store]},
            "line": {"name": "合并 comp", "color": "RED",
                     "values": [None if value is None else float(value) for value in comp["consolidated"]]},
            "fmt": "usd2",
            "yfmt": "usd2",
            "label_fmt": "usd2",
            "ylab": "US$M/店",
            "note": (
                "柱是资产负债表存货除以期末门店数，两端都是申报值，除法是本页做的（D）；"
                "线是同期合并 comp。上季设的警示条件是「comp < 3% 且每店存货同比 > +5%」，"
                f"本季 comp +4%、每店存货同比 {inventory_yoy[-1]:.1f}%，两条都没有触发。"
                "<b>注意口径：</b>公司自己在电话会上给的是固定汇率下的 per-store 库存 +2%，"
                "与这里的 +3.6% 不是同一个定义 —— 本页画的是能从申报文件复算的那一个，"
                "并在这里说明两者不同。"
                "第三、七格的高点是进入假日季前的季节性备货，不是纪律松动。"
            ),
            "src_extra": "存货与门店数为各季 8-K 披露值；每店存货为两者相除的自算值。",
        },
    ]

    # ── section 3: what to track next ───────────────────────────────────────
    hg_margin = segm["homegoods_margin_pct"]
    hg_settled = hg_margin[:-1] + [adj_seg["homegoods"]["adjusted"]]
    next_ex = [
        headroom_exhibit(
            "下季五条阈值：三条已经在触发侧",
            next_kpi, "current",
            note=(
                "同样以正值为安全侧。<b>已经在触发侧的三条讲的是同一个故事的三端：</b>"
                "Marmaxx 的 comp 还在门槛之下，本季调整后税前利润率低于公司自己给下一季的下沿，"
                "而资本开支强度已经越过纪律线。"
                "<b>另外两条本页不画：</b>"
                "「Q3 关税退款实际净贡献 vs 指引的每股 $0.06」目前只有指引没有实际，还没有序列；"
                "「全年指引上调幅度 vs 当季超额幅度」是两个差值的比较，"
                "本季两者都等于 $0.05–0.07、落在同一个数上，画成柱子只会得到一根零柱。"
                "两条都写在核对表里。"
            ),
            src_extra="阈值为本地研究设定，不是公司指引；当前值取自本季业绩 8-K 与自算。",
        ),
        threshold_exhibit(
            f"HomeGoods 分部利润率八季：本季调整后 {adj_seg['homegoods']['adjusted']:.1f}%，"
            f"报表 {hg_margin[-1]:.1f}%",
            labels, rounded(hg_settled), 11.5,
            fmt="pct1", ylab="%", actual_name="HomeGoods 分部利润率（本季取调整后）",
            threshold_name="下季警示线 11.5%",
            note=(
                "本季这一格取公司披露的调整后值 12.4%，而不是报表的 17.6% —— "
                "两者差 5.2 个百分点，全部是关税退款，这是四个分部里最大的一格，"
                "而 HomeGoods 只占本季销售额的 "
                f"{seg['homegoods_sales'][-1] / sales[-1] * 100:.1f}%。"
                "阈值问的是关税顺风退去以后这条线停在哪里：跌破 11.5% 说明本季的改善主要是关税，"
                "守在 12.0% 以上才说明里面有真实的非关税成分。"
            ),
            src_extra="分部利润率为分部利润除以分部销售额的自算值；调整后值为公司披露值。",
        ),
        {
            "kind": "grouped_bars",
            "title": (
                f"资本强度：上半年资本开支占销售额 "
                f"{half['capital_expenditures'][1] / half['net_sales'][1] * 100:.2f}%，"
                f"去年同期 {half['capital_expenditures'][0] / half['net_sales'][0] * 100:.2f}%"
            ),
            "xlabels": ["经营现金流", "资本开支", "回购", "分红"],
            "groups": [
                {"name": "去年上半年", "color": "GRAY",
                 "values": [half[key][0] for key in
                            ("operating_cash_flow", "capital_expenditures",
                             "share_repurchases", "dividends_paid")]},
                {"name": "今年上半年", "color": "NAVY",
                 "values": [half[key][1] for key in
                            ("operating_cash_flow", "capital_expenditures",
                             "share_repurchases", "dividends_paid")]},
            ],
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "US$M",
            "note": (
                f"上半年经营现金流 ${half['operating_cash_flow'][1]:,}M，同比 "
                f"{signed(pct_change(half['operating_cash_flow'][1], half['operating_cash_flow'][0]))}；"
                f"资本开支 ${half['capital_expenditures'][1]:,}M，同比 "
                f"{signed(pct_change(half['capital_expenditures'][1], half['capital_expenditures'][0]))}。"
                "<b>现金流这一格要打折：</b>它含营运资本，而本季应收项的改善大概率含关税退款的收款，"
                "属于不可重复的来源；本页不发布营运资本对增量的逐项拆分，"
                "因为业绩 8-K 的半年现金流量表只有汇总行。"
                "资本开支那一格才是要跟的：占销售额已经从 3.48% 升到 3.93%，"
                "而公司同一天宣布 FY2028 起开店增速从 3% 提到 4%、长期门店目标从 7,000 提到 7,500。"
            ),
            "src_extra": "上半年现金流量与销售额均为公司披露的累计值；占比为自算。",
        },
    ]

    # ── section 4: the long routine ─────────────────────────────────────────
    fy_labels = long["fiscal_years"]
    routine_ex = [
        {
            "kind": "bar_line",
            # The ten-year endpoints of capital intensity are 3.1% and 3.2% and
            # look flat, which would read as contradicting the rest of the page.
            # The move that matters is off the post-pandemic FY2022 level, so
            # the title says that and the chart still draws all ten years. The
            # series minimum is FY2021, but a year of shut stores is not a
            # baseline anything should be measured from.
            "title": (
                f"十年税前利润率与资本强度：利润率 {long['pretax_margin_pct'][0]:.1f}% → "
                f"{long['pretax_margin_pct'][-1]:.1f}% 创十年高；"
                f"资本开支占销售额自 FY2022 的 {long['capex_intensity_pct'][5]:.1f}% 回到 "
                f"{long['capex_intensity_pct'][-1]:.1f}%"
            ),
            "xlabels": fy_labels,
            "bar": {"name": "税前利润率", "color": "NAVY",
                    "values": rounded(long["pretax_margin_pct"])},
            "line": {"name": "资本开支 / 销售额 D", "color": "RED",
                     "values": rounded(long["capex_intensity_pct"])},
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "ylab": "%",
            "note": (
                "十年是这条线最短的可读窗口：八个季度分不清趋势与抖动，"
                "而资本强度的一个建店周期本来就跨年。"
                f"FY2021 的 {long['pretax_margin_pct'][4]:.1f}% 是疫情年，门店大面积关闭；"
                f"此后利润率连年抬升到 FY2026 的 {long['pretax_margin_pct'][-1]:.1f}%，是十年最高。"
                "<b>但两条线在最近几年一起往上走：</b>资本强度从 FY2022 的 "
                f"{long['capex_intensity_pct'][5]:.1f}% 升到 FY2026 的 "
                f"{long['capex_intensity_pct'][-1]:.1f}%，而本年上半年已经是 3.93%。"
                "利润率与资本强度同时创十年高，是这一页的长期背景。"
                "FY2018 与 FY2024 是 53 周财年，销售额多一周，两个比率因此略被稀释。"
            ),
            "src_extra": "各年 10-K 的合并损益表与现金流量表；两个比率为自算。",
        },
        {
            "kind": "bar_line",
            "title": (
                f"十年门店数与总面积：{long['store_count'][0]:,} 家 → "
                f"{long['store_count'][-1]:,} 家，长期目标刚从 7,000 提到 7,500"
            ),
            "xlabels": fy_labels,
            "bar": {"name": "财年末门店数", "color": "BLUE", "values": long["store_count"]},
            "line": {"name": "财年末总面积（百万平方英尺）", "color": "NAVY",
                     "values": long["square_feet_m"]},
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "家 / 百万平方英尺",
            "note": (
                f"十年净增 {long['store_count'][-1] - long['store_count'][0]:,} 家，"
                f"年化 {((long['store_count'][-1] / long['store_count'][0]) ** (1 / 9) - 1) * 100:.1f}%；"
                f"面积年化 {((long['square_feet_m'][-1] / long['square_feet_m'][0]) ** (1 / 9) - 1) * 100:.1f}%，"
                "低于门店数 —— 新开的店平均比存量店小，公司自己也确认了这一点。"
                f"本季末 {stores[-1]:,} 家，距新的 7,500 家长期目标还有 "
                f"{7500 - stores[-1]:,} 家（+{(7500 / stores[-1] - 1) * 100:.1f}%）。"
                "这张图是上一张资本强度线的分母侧：门店目标与开店增速同时上调，"
                "资本开支的台阶就不是一次性的。"
            ),
            "src_extra": "各年 Q4 业绩 8-K 的 Stores by Concept 表，财年末申报值。",
        },
        {
            "kind": "bar_line",
            "title": (
                f"十年回购与股数：累计回购 US${sum(long['share_repurchases_usd_m']) / 1000:.1f}B，"
                f"股数 {long['diluted_shares_m'][0]:,.0f}M → {long['diluted_shares_m'][-1]:,.0f}M"
            ),
            "xlabels": fy_labels,
            "bar": {"name": "回购金额", "color": "GOLD",
                    "values": long["share_repurchases_usd_m"]},
            "line": {"name": "摊薄股数（百万股）", "color": "NAVY",
                     "values": long["diluted_shares_m"]},
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "US$M / 百万股",
            "note": (
                f"十年股数减少 {(1 - long['diluted_shares_m'][-1] / long['diluted_shares_m'][0]) * 100:.1f}%，"
                f"年化约 {abs(((long['diluted_shares_m'][-1] / long['diluted_shares_m'][0]) ** (1 / 9) - 1) * 100):.1f}%；"
                f"本季同比 {signed(pct_change(shares[-1], shares[-5]))}，"
                "也就是说每股收益的同比增长里大约有一个百分点来自股数而不是利润。"
                f"FY2021 的 US${long['share_repurchases_usd_m'][4]:,.0f}M 是疫情年暂停回购留下的缺口，"
                "此后每年都在 US$2.2B 以上。"
                "股数一律换算到 2018 年 11 月一拆二之后的口径。"
            ),
            "src_extra": "各年 10-K 现金流量表的回购支出与损益表的摊薄股数。",
        },
        {
            "kind": "grouped_bars",
            "title": (
                f"十年经营现金流、资本开支与股东回报：FY2026 分别为 "
                f"US${long['operating_cash_flow_usd_m'][-1] / 1000:.1f}B、"
                f"US${long['capital_expenditures_usd_m'][-1] / 1000:.1f}B 与 "
                f"US${(long['share_repurchases_usd_m'][-1] + long['dividends_paid_usd_m'][-1]) / 1000:.1f}B"
            ),
            "xlabels": fy_labels,
            "groups": [
                {"name": "经营现金流", "color": "NAVY", "values": long["operating_cash_flow_usd_m"]},
                {"name": "资本开支", "color": "BLUE", "values": long["capital_expenditures_usd_m"]},
                {"name": "回购 + 分红", "color": "GOLD",
                 "values": [b + d for b, d in zip(long["share_repurchases_usd_m"],
                                                  long["dividends_paid_usd_m"])]},
            ],
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "bar_labels": False,
            "ylab": "US$M",
            "note": (
                "三根柱放在一起才看得出这家公司的资本配置结构："
                "经营现金流覆盖资本开支之后剩下的，基本原样还给了股东 —— "
                f"最近五年回购加分红合计 US${(sum(long['share_repurchases_usd_m'][-5:]) + sum(long['dividends_paid_usd_m'][-5:])) / 1000:.1f}B，"
                f"同期经营现金流减资本开支 US${sum(o - c for o, c in zip(long['operating_cash_flow_usd_m'][-5:], long['capital_expenditures_usd_m'][-5:])) / 1000:.1f}B。"
                "FY2021 是唯一一年三者脱节：现金流因为压缩存货反而不低，"
                "而资本开支与股东回报同时被砍。"
            ),
            "src_extra": "各年 10-K 现金流量表，申报值。",
        },
    ]

    number_exhibits(settled_ex, start=1)
    number_exhibits(highlight_ex, start=settled_ex[-1]["n"] + 1)
    number_exhibits(next_ex, start=highlight_ex[-1]["n"] + 1)
    number_exhibits(routine_ex, start=next_ex[-1]["n"] + 1)
    for group in (settled_ex, highlight_ex, next_ex, routine_ex):
        resolve_exhibit_refs(group)

    first_table = routine_ex[-1]["n"] + 1
    core_rows = []
    for index, period in enumerate(periods):
        core_rows.append([
            period,
            staging["fiscal_labels"][index],
            staging["period_ends"][index],
            f"${sales[index]:,}M",
            ("—" if fin["net_sales_yoy_pct"][index] is None else ("—" if fin['net_sales_yoy_pct'][index] is None else f"{fin['net_sales_yoy_pct'][index]:+.1f}%")),
            ("—" if comp['consolidated'][index] is None else f"{comp['consolidated'][index]:+.0f}%"),
            f"{gross[index]:.2f}%",
            ("—" if fin['sga_pct_of_sales'][index] is None else f"{fin['sga_pct_of_sales'][index]:.2f}%"),
            f"{pretax_margin[index]:.2f}%",
            f"${eps[index]:.2f}",
            (f"${fin['adjusted_diluted_eps_usd'][index]:.2f}"
             if fin["adjusted_diluted_eps_usd"][index] is not None else "同 GAAP"),
            f"{shares[index]:,}M",
            f"{stores[index]:,}",
        ])
    long_rows = []
    for index, year in enumerate(fy_labels):
        long_rows.append([
            year,
            long["year_ends"][index],
            f"{long['weeks'][index]} 周",
            f"${long['net_sales_usd_m'][index]:,.0f}M",
            f"{long['pretax_margin_pct'][index]:.2f}%",
            f"${long['diluted_eps_usd'][index]:.2f}",
            f"{long['diluted_shares_m'][index]:,.0f}M",
            f"${long['capital_expenditures_usd_m'][index]:,.0f}M",
            f"{long['capex_intensity_pct'][index]:.2f}%",
            f"${long['operating_cash_flow_usd_m'][index]:,.0f}M",
            f"${long['share_repurchases_usd_m'][index]:,.0f}M",
            f"{long['store_count'][index]:,}",
        ])
    closure_rows = [[item["question"], item["evidence"], item["verdict"]] for item in closure]

    tables = [
        threshold_table(first_table, "上季阈值核对（原始单位）", settled, "actual", "本季实际"),
        threshold_table(first_table + 1, "下季阈值（原始单位）", next_kpi, "current", "当前值"),
        {
            "n": first_table + 2,
            "title": "上季五条待验证问题的结清情况",
            "headers": ["上季问题", "本季证据", "判定"],
            "rows": closure_rows,
        },
        {**delivery_table, "n": first_table + 3},
        {
            "n": first_table + 4,
            "title": "八季核心（自然年季度标注；公司财季见第二列）",
            "headers": ["自然年季度", "公司财季", "季末", "净销售额", "同比", "合并 comp",
                        "毛利率", "SG&A 占比", "税前利润率", "GAAP EPS", "调整后 EPS",
                        "摊薄股数", "门店数"],
            "rows": core_rows,
        },
        {
            "n": first_table + 5,
            "title": "十年年度记录（各年取该年 10-K 印出的数；股数与每股数换算到一拆二之后）",
            "headers": ["财年", "财年末", "周数", "净销售额", "税前利润率", "GAAP EPS",
                        "摊薄股数", "资本开支", "资本开支占销售额", "经营现金流", "回购", "财年末门店数"],
            "rows": long_rows,
        },
        # The one object published byte-identically on every page. TJX is not on
        # the chain it draws and is not a column in it -- neither are Cadence,
        # Synopsys, TSMC or NVIDIA, which carry it on the same terms. It lives in
        # the collapsed audit drawer rather than the chart flow, so it does not
        # spend the page's "every chart must earn its place" budget; the notes
        # say what it is, which the first pages outside the chain did not.
        ai_capex_cycle_table(first_table + 6),
    ]

    return {
        "schema_version": "quarterly-dashboard/tjx-v1",
        "page": {"slug": "tjx", "language": "zh-CN"},
        "company": {
            "ticker": "TJX",
            "name": "The TJX Companies",
            "group": "consumer_retail",
            "accounting_standard": "US GAAP",
        },
        "latest": {
            "disclosed_period_label": "Q2 2026",
            "full_financial_period_label": "Q2 2026",
            "period_end": "2026-08-01",
            "release_date": "2026-08-19",
            "analysis_date": "2026-08-29",
            "audit_status": "unaudited",
            "status": "history_ready",
        },
        "tracker": "Watchlist Quarterly Tracker · TJX",
        "title": "The TJX Companies (TJX)：Q2 2026 季报仪表盘",
        "subtitle": (
            "十三周截至 2026-08-01 · 发布 2026-08-19 · US GAAP · 未审计 · "
            "财年末为最接近 1 月 31 日的星期六，本站按自然年季度标注：本页 Q2 2026 即公司所称 FY2027 Q2"
        ),
        "headline": (
            f"净销售额 US${sales[-1]:,}M、同比 {signed(fin['net_sales_yoy_pct'][-1])}，"
            f"合并 comp +{comp['consolidated'][-1]:.0f}%、税前利润率 {pretax_margin[-1]:.1f}% 双双高于自身指引，"
            "全年指引与长期门店目标同时上调；"
            f"但占销售额 {seg['marmaxx_sales'][-1] / sales[-1] * 100:.0f}% 的 Marmaxx 只有 +1% 且交易笔数转负，"
            "而公司自己给的下半年调整后每股收益只隐含 +2.0%，对上半年的 +19.3%。"
        ),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>记录</span><b>三个指引数字都是地板</b>'
            f'<p>{len(eps_finished)} 季已完结的每股收益指引里 {eps_above} 季穿出上限、'
            f'只有 {eps_below} 季跌破；税前利润率 {margin_finished} 季里 {margin_above} 季超上限；'
            f'合并 comp {comp_finished} 季一次没跌破过。'
            '但指引是在该季开始后 9–24 天才发布的。</p></article>'
            '<article><span>裂口</span><b>最大的分部在失速</b>'
            '<p>Marmaxx comp 从 +6% 掉到 +1%，是唯一交易笔数为负的分部；'
            '其余三个分部 +6~7%，合并 +4% 是它们扛出来的。</p></article>'
            '<article><span>代价</span><b>单店增长转弱的同一季，开店提速</b>'
            '<p>长期门店目标 7,000 → 7,500，FY2028 起开店增速 3% → 4%；'
            '上半年资本开支占销售额已从 3.48% 升到 3.93%。</p></article>'
            '</div>'
        ),
        "source": (
            'Source: <a href="https://www.sec.gov/Archives/edgar/data/109198/'
            '000010919826000045/tjxq2fy27earningspressrele.htm" rel="noopener">TJX FY2027 Q2 '
            '业绩新闻稿（8-K EX-99.1）</a>与截至 2026-08-01 的 10-Q。'
        ),
        "source_url": (
            "https://www.sec.gov/Archives/edgar/data/109198/"
            "000010919826000045/tjxq2fy27earningspressrele.htm"
        ),
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": guidance,
        "sections": [
            {
                "id": "settled",
                "title": "一、上季兑现与指引记录",
                "description": (
                    "先结清上季设下的阈值，再看新数字。公司每季在业绩新闻稿末尾的 Outlook 段里"
                    "给出下一季的合并 comp、税前利润率与摊薄每股收益 —— "
                    "每股收益这条记录能一直回到 2012 年，是本站最长的一份；"
                    "但它是在被指引的那个季度开始之后才发布的，这一点写在每张图上。"
                ),
                "exhibits": settled_ex,
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": (
                    "四个分部的分化、关税退款把分部利润率推歪了多少、"
                    "上下半年之间那道 17 个百分点的斜率断崖，以及一条只能按半年读的公司费用线。"
                ),
                "exhibits": highlight_ex,
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": "当前值离下季阈值还有多远，统一用「距阈值余量」口径；不接入的两条也写在这里。",
                "exhibits": next_ex,
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": (
                    "TJX 专属的常规序列：十年税前利润率与资本强度、门店与面积这台单位增长机器、"
                    "十年回购与股数，以及经营现金流、资本开支与股东回报的三柱结构。"
                ),
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "本页所有季度按自然年标注。TJX 财年在 1 月底或 2 月初结束，故本页的 Q2 2026 是十三周截至 2026-08-01 的季度，公司自己称之为 FY2027 Q2；映射规则为公司 FY(N) 的 Qk 即本页的 Qk (N−1)。不统一成一种约定，跨公司对照就会把不同的三个月放在一起比较。",
            "第一节的指引兑现组图用的是同一批业绩 8-K：每份 EX-99.1 新闻稿末尾的 Outlook 段落用同一种句式给出下一季的合并 comp、税前利润率与摊薄每股收益区间；实际值取自随后一季 8-K 的 Financial Summary 合并损益表。三条记录起点不同（每股收益 Q1 2012、税前利润率 Q3 2022、合并 comp Q1 2023），各图按自己的记录长度画，不往前补。",
            "TJX 的下一季指引随上一季业绩一起发布，而它在季末约三周后发业绩，因此这段 Outlook 落在它所指引的那个季度之内：本记录里最早第 9 天、最晚第 24 天、平均第 18 天。这不是一份事前预测，命中率必须连同这句话一起读。",
            "公司在 2020 年 5 月至 2021 年 11 月的五份业绩稿里写明不提供指引，连续 7 个会计季没有任何数字指引。本页的记录在横轴上从 Q1 2020 直接跳到 Q1 2022，并在图上打断点；这段空白不计入任何命中率的分母。",
            "2018 年 11 月一拆二：在此之前公布的每股收益指引与实际值一律除以 2，换算到当前股本口径。二比一的换算是精确的，不是估计。跨拆股的只有一个季度（Q3 2018，指引在拆股前给出、实际在拆股后报出），换算后指引为 US$0.59–0.60、实际 US$0.61。",
            "FY2018 与 FY2024 是 53 周财年，多出来的一周落在会计季 Q4。FY2024 Q4 的指引本身就是按 14 周给的，公司同时另给了一份剔除多出一周的口径，本页取与指引同口径的那一个；十年年度表里标注了周数。",
            "有调整项的季度，指引兑现按公司自己判定「相对 plan」时所用的口径比较：Q4 2025 的诉讼和解与 Q2 2026 的 IEEPA 关税退款都发生在指引给出之后，用报表值去对当初的区间等于让指引为它装不下的事负责。其余季度公司未披露调整项，报表值即调整后值。",
            "会计季 Q4 没有 10-Q，其损益与分部数值取自 Q4 业绩 8-K 里印出的「Thirteen Weeks Ended」一栏，是申报的季度值而不是财年数减九个月数的差分值。八季核心表与分部序列因此全部是申报值，两条恒等式（收入 − 销货成本 − SG&A + 净利息收入 = 税前利润；分部利润之和 − 公司费用 + 净利息收入 = 税前利润）在八个季度里逐季对得上，差额为零。",
            "本页不发布剔除关税成本顺风之后的每股收益或利润率。公司把本季调整后毛利率的改善归因为 mostly due to tariff favorability，但从未给出金额或百分点；把这个词换算成一个数需要自选一个比例，那是假设不是算术。同理，各分部「持续性关税顺风」的分摊也不发布。",
            "每店存货是资产负债表存货除以期末门店数的自算值，与公司在电话会上口头给出的固定汇率 per-store 口径不是同一个定义，两者本季分别为 +3.6% 与 +2%；本页只画能从申报文件复算的那一个，并在图上说明差异。",
            "上季阈值中「Marmaxx 与同业同期 comp 差距」需要另一家公司的申报值才能计算，本页不画该序列，只在核对表与说明中记录其触发状态；余量图里因此只有五条。",
            "核对抽屉最后那张「AI capex 循环」是全站逐字节一致的跨页对照块，不是对 TJX 的判断：它把四家云厂的现金资本开支、NVDA 的数据中心收入与 TSM 的晶圆季度串成一条链，而 TJX 不在这条链的任何一环上。本站有若干页同样只是承载它而不出现在它的列里（Cadence、Synopsys、TSMC、NVIDIA 都是如此，且有测试专门钉住这一点）。它放在折叠抽屉里而不是图表区，所以不占本页「每张图都要自证」的额度；在这里写明它是什么，是因为在一家折扣零售商的抽屉里遇到一张晶圆代工对照表的读者，值得有一句话说明它的性质。",
            "本页只发布公司披露值、可复算的简单派生值，以及明确标注的市场预期；D 标记代表 Derived / 自算。",
            "市场预期一律标注为「市场预期」并给出取数时点，不写卖方机构名，也不发布评级、目标价或估值。",
            "本页已知未接入：各分部的交易笔数与客单价的数值拆分（公司只在电话会上定性描述）、Marmaxx 失手的具体品类（公司在问答中四次拒绝披露）、剩余可收回的 IEEPA 退款金额（公司称金额、时点与可能性均不确定）、新店回报率与 7,500 家目标对应的资本开支（公司未量化）。",
            "业绩电话会文字稿仅链接官方 IR 与 SEC 托管版本，公开仓不复制原件或逐字内容。",
        ],
        "footer": "TJX quarterly results · 数据来自 The TJX Companies 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "tjx.js"), payload, "tjx")
    shell_dir = ROOT / "tjx"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("TJX", "tjx"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(
        f"TJX page: {charts} charts in {len(payload['sections'])} sections "
        f"+ {len(payload['tables'])} audit tables"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
