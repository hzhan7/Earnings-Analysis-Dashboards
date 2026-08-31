#!/usr/bin/env python3
"""Build the Broadcom quarterly-results page.

Same four-part, chart-led shape as the other pages (上季兑现 → 本季重点 →
下季跟踪 → 长期常规). Broadcom is the sixth company here whose quarterly outlook
reaches a filing, and its record is a shape none of the other five have: the
interesting variable is not how far the quarter cleared the bar, it is **what
kind of bar the company was willing to publish**.

Across 33 earnings 8-Ks the outlook block changes form four times. It opens as a
full GAAP/non-GAAP table with a revenue range (`$5,047M +/- $75M`); becomes a
fiscal-year number for all of FY2019; comes back as a quarterly range through
the first COVID year; and from the FY2021 Q1 outlook onward is a bare point —
`approximately $6.6 billion` — with Adjusted EBITDA quoted as a percentage of
projected revenue rather than a dollar amount. It reverts to fiscal-year
guidance for three releases across the VMware year and then returns to
quarterly points.

What that produces is a two-sided answer of a kind no other page here has:

- In the **five** quarters Broadcom published a revenue *range*, the reported
  number landed **inside the range every time** — never above it, never below.
- In the **nineteen** finished quarters it published a *point*, the reported
  number came in **above the point every time** — nineteen for nineteen.
- Measured uniformly against the guided point or midpoint, all **24** finished
  quarters are positive, in a band from +0.17% to +3.53% with a median of
  +0.80%.
- Adjusted EBITDA margin, guided as a percentage since FY2021 Q2, has landed
  **above the guided percentage in all 18** finished quarters, by +0.04pp to
  +1.60pp.

A record with no misses in either metric would normally be the whole finding.
Here it is the setup for a different one: the beats are *small and astonishingly
regular*, and the outlook goes out a median of 31 days into the 91-day quarter
it guides — a third of the quarter is already in the book when the number is
published. So this is much less a forecast than a disclosure of something
already largely known, and every guidance chart on the page says so.

The page's own series is the decomposition. Guiding a revenue level and an
Adjusted EBITDA *margin* implies an Adjusted EBITDA dollar amount Broadcom never
prints, and the distance from what it reported splits exactly two ways — a
revenue leg and a margin leg — with no estimate anywhere. A second identity
licenses the segment view: the two reportable segments' filed operating incomes
sum to the company's non-GAAP operating income **exactly, in all 30 quarters
where the segment note carries them**, so the margin the company guides can be
attributed to the semiconductor engine and the software engine separately.

The public payload contains only Broadcom-reported figures, clearly labelled
market expectations, and arithmetic reproducible from the audit tables.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import (  # noqa: E402
    ai_capex_cycle_table,
    delivery_band,
    headroom,
    headroom_exhibit,
    midpoint_deviation,
    number_exhibits,
    threshold_exhibit,
    threshold_table,
    unit_text,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "avgo.json"
DATA_DIR = ROOT / "data"

# The eight-quarter block the standard charts use.
WINDOW = 8


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100


def compact_period(period: str) -> str:
    """``'Q1 2026'`` → ``'Q1'26'``."""
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


def rounded(values: list[float | None], digits: int = 6) -> list[float | None]:
    return [None if value is None else round(value, digits) for value in values]


def ratio(numerators: list[float | None], denominators: list[float | None],
          scale: float = 100.0) -> list[float | None]:
    out: list[float | None] = []
    for top, bottom in zip(numerators, denominators):
        out.append(None if top is None or not bottom else round(top / bottom * scale, 6))
    return out


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
    "指引取自各季业绩 8-K 的 EX-99.1 新闻稿「Business Outlook」区块；"
    "实际值取自随后一季 8-K 的合并损益表与 GAAP/non-GAAP 对账表，"
    "并与 XBRL companyfacts 逐季核对一致。"
)

# Broadcom publishes each quarter's outlook alongside the *previous* quarter's
# results, and that release lands about a month into the quarter being guided.
# A record with no misses means much less when a third of the quarter is already
# banked, so the caveat travels with every chart rather than sitting in a note.
TIMING_CAVEAT = (
    "<b>时点提醒</b>：公司是在上一季业绩发布时才给出这一季的指引，"
    "而那场发布落在被指引季度<b>已经开始之后</b>——中位数是 91 天里的第 31 天。"
    "所以「从未低于指引」描述的不是一个纯粹的事前预测，"
    "而是一个已经过掉三分之一的季度。"
)


# ── section one: the guided record ──────────────────────────────────────────
def guidance_delivery_charts(staging: dict) -> tuple[list[dict], list[dict]]:
    """The full guided record, split by the form of the guidance itself.

    Broadcom's record cannot go on one band chart, because for five of its
    quarters the guidance has width and for twenty it has none. Forcing both
    onto one chart would have to pick a verdict sentence that is wrong for one
    of the two halves: "cleared the upper bound" is a category error against a
    point, and "identical to the guidance" is a category error against a range
    the quarter landed inside. So the level charts are split by form and the
    scale-free deviation chart, where the distinction does not matter, carries
    the whole record.
    """
    record = staging["quarterly_guidance_history"]
    periods = record["periods"]
    labels = [compact_period(period) for period in periods]
    forms = record["revenue_form"]
    guide = record["guide_revenue_usd_m"]
    lo = record["guide_revenue_lo_usd_m"]
    hi = record["guide_revenue_hi_usd_m"]
    actual = record["actual_revenue_usd_m"]

    range_idx = [i for i, form in enumerate(forms) if form == "range"]
    point_idx = [i for i, form in enumerate(forms) if form == "point"]
    finished = [i for i, value in enumerate(actual) if value is not None]
    point_finished = [i for i in point_idx if actual[i] is not None]

    def take(values, idx):
        return [values[i] for i in idx]

    # ── revenue, the range era ───────────────────────────────────────────────
    range_chart = delivery_band(
        "EX_REV_RANGE", "收入", take(labels, range_idx),
        take(lo, range_idx), take(hi, range_idx), take(actual, range_idx),
        fmt="f0c", ylab="US$M", unit="US$M", venue="业绩发布", timing="该季<b>开始约一个月后</b>",
        scope="（仅公司给过区间的 5 季）",
        src_extra=SOURCE_8K + TIMING_CAVEAT,
        extra_note=(
            "这五季是 Broadcom 唯一给过<b>收入区间</b>的时期："
            "2018 年两季写作 <code>$5,047M +/- $75M</code>，"
            "2020 年三季写作 <code>$5.7 billion plus or minus $150 million</code>。"
            "五季<b>全部落在自己的区间之内</b>，既没有穿出上限，也没有跌破下限——"
            "而且五季全部落在中值<b>之上</b>。"
            "此后公司不再给区间，改给单点，见 Exhibit {EX_REV_POINT}。"
        ),
    )

    # ── revenue, the point era ───────────────────────────────────────────────
    point_chart = delivery_band(
        "EX_REV_POINT", "收入", take(labels, point_idx),
        take(guide, point_idx), take(guide, point_idx), take(actual, point_idx),
        fmt="f0c", ylab="US$M", unit="US$M", venue="业绩发布", timing="该季<b>开始约一个月后</b>",
        scope="（公司只给单点的 20 季）", point=True,
        src_extra=SOURCE_8K + TIMING_CAVEAT,
        extra_note=(
            f"自 FY2021 Q1 的指引起，公司把区间换成了一个数——新闻稿原文是 "
            "<code>approximately $6.6 billion</code> 这种写法，"
            "所以图上的细线<b>没有宽度可言，这不是渲染问题，是指引本身没有宽度</b>。"
            f"{len(point_finished)} 个已完结季<b>全部高于</b>那个点，一次例外都没有。"
            "但要注意这两件事的顺序：公司是先停止给区间，才有了这条「全部高于」的记录——"
            "一个没有下限的指引，本来也就不存在「跌破下限」这回事。"
            "量级无关的完整读法见 Exhibit {EX_REV_DEV}。"
        ),
    )

    # ── revenue, the whole record on one scale-free axis ─────────────────────
    deviation = [(actual[i] / guide[i] - 1) * 100 for i in finished]
    dev_chart = midpoint_deviation(
        "EX_REV_DEV", "收入", periods, guide, guide, actual,
        mode="pct", window=len(finished), label=compact_period, bar_labels=False,
        src_extra=SOURCE_8K + "偏离为实际收入除以指引单点或区间中值的自算值。" + TIMING_CAVEAT,
        extra_note=(
            f"<b>这是全页最该先读的一张</b>：{len(finished)} 个已完结季里，"
            f"实际收入<b>一次都没有低于指引的点或中值</b>——"
            f"最小的一次也有 {min(deviation):+.2f}%，最大 {max(deviation):+.2f}%，"
            f"中位数 {statistics.median(deviation):+.2f}%。"
            "真正值得注意的不是「零次低于」，而是<b>这条带子有多窄</b>："
            "八年、一次会计年度口径切换、一次 COVID、一次 US$69B 的 VMware 收购、"
            "以及 AI 让收入翻了四倍，偏离却几乎从没超过 +2%。"
            "把它读成「公司预测得准」是读反了；"
            "结合上面的时点提醒，更像是公司只在数字基本落袋之后才把它写进新闻稿。"
        ),
    )

    # ── Adjusted EBITDA margin, the percent era ──────────────────────────────
    margin_guide = record["guide_ebitda_margin_pct"]
    margin_actual = record["actual_ebitda_margin_pct"]
    margin_idx = [i for i, value in enumerate(margin_guide) if value is not None]
    margin_finished = [i for i in margin_idx if margin_actual[i] is not None]
    margin_gap = [margin_actual[i] - margin_guide[i] for i in margin_finished]
    at_least = [i for i, q in enumerate(record["ebitda_qualifier"]) if q == "at least"]

    margin_chart = delivery_band(
        "EX_EBITDA_POINT", "Adjusted EBITDA 利润率", take(labels, margin_idx),
        take(margin_guide, margin_idx), take(margin_guide, margin_idx),
        take(margin_actual, margin_idx),
        fmt="pct1", ylab="占收入 %", unit="%", venue="业绩发布", timing="该季<b>开始约一个月后</b>",
        point=True, src_extra=SOURCE_8K + (
            "公司对 Adjusted EBITDA 的指引写法是「约为预计收入的 N%」，是单点、不是区间；"
            "实际值为该季 Adjusted EBITDA 除以该季收入的自算值，两项都取自同一份新闻稿。"
        ) + TIMING_CAVEAT,
        extra_note=(
            f"{len(margin_finished)} 个已完结季<b>全部高于</b>指引的百分比，"
            f"幅度从 {min(margin_gap):+.2f}pp 到 {max(margin_gap):+.2f}pp，"
            f"平均 {statistics.fmean(margin_gap):+.2f}pp。"
            "注意 Adjusted EBITDA 是公司自定义口径（在 GAAP 净利上加回利息、税、折旧、"
            "无形摊销、股权激励、重组与收购相关费用），因此这里的每一对"
            "「指引 vs 实际」都必须在<b>当时那一套口径内部</b>比较，本图正是如此。"
            + (f"另有 {len(at_least)} 季公司的措辞是 <code>at least</code> 而不是 "
               "<code>approximately</code>——那一季严格说是下限而不是点，"
               "但仍按点画，因为它没有上界。" if at_least else "")
        ),
    )
    margin_dev = midpoint_deviation(
        "EX_EBITDA_DEV", "Adjusted EBITDA 利润率", periods, margin_guide, margin_guide,
        [margin_actual[i] if margin_guide[i] is not None else None
         for i in range(len(periods))],
        mode="pp", window=len(margin_finished), label=compact_period, bar_labels=False,
        src_extra=SOURCE_8K + "偏离为实际利润率减指引百分比的算术差。" + TIMING_CAVEAT,
        extra_note=(
            "与收入那条一样是单向的，而且幅度更小：这条线上公司几乎从不给自己留出可见的余量。"
            "两条合起来说明的是同一件事——Broadcom 的指引是一条它确定能过的线，"
            "而不是一个居中的预测。"
        ),
    )

    # ── what the beat is made of ─────────────────────────────────────────────
    # Guiding a revenue level and an EBITDA margin implies an Adjusted EBITDA
    # dollar amount the company never prints, and the distance from what it
    # reported splits exactly two ways with no estimate:
    #     actual − implied = (Ra − Rg)·mg  +  Ra·(ma − mg)
    revenue_leg, margin_leg, leg_labels = [], [], []
    for i in margin_finished:
        guided_revenue = guide[i]
        guided_margin = margin_guide[i] / 100
        actual_revenue = actual[i]
        actual_margin = margin_actual[i] / 100
        revenue_leg.append((actual_revenue - guided_revenue) * guided_margin)
        margin_leg.append(actual_revenue * (actual_margin - guided_margin))
        leg_labels.append(compact_period(periods[i]))
    totals = [a + b for a, b in zip(revenue_leg, margin_leg)]
    margin_led = sum(1 for a, b in zip(revenue_leg, margin_leg) if b > a)
    legs_chart = {
        "ref": "EX_LEGS",
        "kind": "grouped_bars",
        "title": (
            f"把「超出自身指引」拆成两条腿：{len(totals)} 季里没有一条腿为负，"
            f"利润率腿在 {margin_led} 季是更大的那半"
        ),
        "xlabels": leg_labels,
        "xrot": 90,
        "groups": [
            {"name": "收入腿（多做的收入 × 指引利润率）", "values": rounded(revenue_leg, 3), "color": "BLUE"},
            {"name": "利润率腿（实际收入 × 多出的利润率）", "values": rounded(margin_leg, 3), "color": "NAVY"},
        ],
        "bar_labels": False,
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$M",
        "note": (
            "公司同时指引收入水平与 Adjusted EBITDA 利润率，两者相乘隐含一个它从不印出来的"
            "Adjusted EBITDA 金额；实际值与它的差<b>恰好</b>等于这两条腿之和，"
            "是恒等式而不是估计（收入与利润率同时偏离时的交叉项按该式全部计入利润率腿，"
            "调换拆解顺序会把它移到收入腿，合计不变）。"
            f"这里的答案与本站另外两家不同：Amazon 的超额几乎全在利润率腿，"
            f"Synopsys 几乎全在收入腿，而 Broadcom 是<b>两条腿都在贡献</b>——"
            f"{len(totals)} 季里利润率腿更大的有 {margin_led} 季，收入腿更大的有 "
            f"{len(totals) - margin_led} 季。"
            f"最大的一季是 {leg_labels[totals.index(max(totals))]}，合计 "
            f"US${max(totals):,.0f}M。"
        ),
        "src_extra": SOURCE_8K + "两条腿均为按上式自算，可由指引兑现全表复算。" + TIMING_CAVEAT,
    }

    # ── the audit tables behind the record ──────────────────────────────────
    rows = []
    for i, period in enumerate(periods):
        band = (f"{lo[i]:,.0f}–{hi[i]:,.0f}" if forms[i] == "range" else f"{guide[i]:,.0f}（单点）")
        act_text = "—" if actual[i] is None else f"{actual[i]:,.0f}"
        dev_text = "—" if actual[i] is None else f"{(actual[i] / guide[i] - 1) * 100:+.2f}%"
        if actual[i] is None:
            verdict = "待披露"
        elif forms[i] == "range":
            verdict = ("区间内" if lo[i] <= actual[i] <= hi[i]
                       else ("高于上限" if actual[i] > hi[i] else "低于下限"))
        else:
            verdict = "高于" if actual[i] > guide[i] else ("低于" if actual[i] < guide[i] else "相同")
        margin_text = "—" if margin_guide[i] is None else f"{margin_guide[i]:.1f}%"
        margin_act = "—" if margin_actual[i] is None else f"{margin_actual[i]:.2f}%"
        rows.append([
            period, record["fiscal_labels"][i], record["guided_in_release"][i],
            f"{record['days_into_quarter_at_release'][i]}/{record['quarter_length_days'][i]} 天",
            band, act_text, dev_text, verdict, margin_text, margin_act,
        ])
    record_table = {
        "title": f"指引兑现全表（{len(periods)} 季）：区间时代、单点时代与两者的实际值",
        "headers": ["本站季度", "公司财季", "指引发布日", "发布时该季已过",
                    "收入指引 US$M", "实际收入 US$M", "偏离 D", "判定",
                    "EBITDA 利润率指引", "实际 D"],
        "rows": rows,
    }
    gap_rows = [
        [entry["released"], entry["fiscal_year_end"], f"{entry['revenue_usd_m']:,.0f}",
         "区间" if entry["revenue_form"] == "range" else "单点",
         "—" if entry["ebitda"] is None else
         (f"{entry['ebitda']:,.0f} US$M" if entry["ebitda_unit"] == "usd_m"
          else f"{entry['ebitda']:.0f}% of revenue")]
        for entry in staging["annual_only_guidance"]
    ]
    gap_table = {
        "title": "只按财年给过、因而结算不了任何单季的 8 份指引",
        "headers": ["发布日", "所指引财年结束日", "收入指引 US$M", "形式", "EBITDA 指引"],
        "rows": gap_rows,
    }
    return [range_chart, point_chart, dev_chart, margin_chart, margin_dev, legs_chart], \
           [record_table, gap_table]


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    fiscal = staging["fiscal_labels"]
    ends = staging["period_ends"]
    financials = staging["financials_usd_m"]
    segments = staging["segments_usd_m"]
    cash = staging["cash_flow_usd_m"]
    capital = staging["capital_allocation_usd_m"]
    working = staging["working_capital_usd_m"]
    commitments = staging["purchase_commitments_usd_m"]
    guidance = staging["guidance"]["next_quarter"]
    ai = staging["ai_semiconductor_disclosures"]

    revenue = financials["revenue"]
    gaap_oi = financials["gaap_operating_income"]
    ng_oi = financials["non_gaap_operating_income"]
    ebitda = financials["adjusted_ebitda"]
    semi_rev = segments["semiconductor_revenue"]
    isg_rev = segments["infrastructure_software_revenue"]
    semi_oi = segments["semiconductor_operating_income"]
    isg_oi = segments["infrastructure_software_operating_income"]
    ocf = cash["operating_cash_flow"]
    capex = cash["capital_expenditures"]
    rnd = cash["research_and_development"]

    gaap_margin = ratio(gaap_oi, revenue)
    ng_margin = ratio(ng_oi, revenue)
    ebitda_margin = ratio(ebitda, revenue)
    fcf = [o - c for o, c in zip(ocf, capex)]
    fcf_margin = ratio(fcf, revenue)
    capex_intensity = ratio(capex, revenue)
    rnd_intensity = ratio(rnd, revenue)
    semi_share = ratio(semi_rev, revenue)
    semi_margin = ratio(semi_oi, semi_rev)
    isg_margin = ratio(isg_oi, isg_rev)
    net_debt = [d - c for d, c in zip(capital["total_debt"], capital["cash_and_equivalents"])]
    yoy = [None if index < 4 else pct_change(revenue[index], revenue[index - 4])
           for index in range(len(revenue))]

    tail = slice(len(periods) - WINDOW, len(periods))
    labels = [compact_period(period) for period in periods[tail]]
    long_labels = [compact_period(period) for period in periods]

    source = (
        'Source: <a href="https://www.sec.gov/Archives/edgar/data/1730168/'
        '000173016826000051/avgo-05032026x8kxex99.htm" rel="noopener">Broadcom FY2026 Q2 '
        '业绩新闻稿（8-K EX-99.1）</a>与截至 2026-05-03 的 10-Q。'
    )

    # ── section one ──────────────────────────────────────────────────────────
    closure = staging["followup_closure"]
    closure_chart = {
        "kind": "bars_labeled",
        "title": (
            f"上季 6 条待验证问题：{closure['counts'][0]} 条已验证、"
            f"{closure['counts'][1]} 条部分验证、{closure['counts'][2]} 条仍未披露、"
            f"{closure['counts'][3]} 条被证伪"
        ),
        "xlabels": closure["labels"],
        "values": closure["counts"],
        "legend": "问题条数",
        "fmt": "f0", "yfmt": "f0", "label_fmt": "f0", "ylab": "条",
        "note": closure["note"],
        "src_extra": (
            "问题清单来自上季本地分析稿的 follow-up；"
            "验证结果依据本季业绩 8-K、截至 2026-05-03 的 10-Q 与业绩电话会。"
        ),
    }

    verdicts = staging["tracked_metric_verdicts"]
    verdict_chart = {
        "kind": "bars_labeled",
        "title": (
            f"上季 5 条跟踪线的判定：{verdicts['counts'][0]} 条优于阈值、"
            f"{verdicts['counts'][1]} 条符合、{verdicts['counts'][2]} 条逊于、"
            f"{verdicts['counts'][3]} 条无法判定"
        ),
        "xlabels": verdicts["labels"],
        "values": verdicts["counts"],
        "legend": "指标条数",
        "fmt": "f0", "yfmt": "f0", "label_fmt": "f0", "ylab": "条",
        "note": verdicts["note"],
        "src_extra": "阈值为上季本地研究设定；判定依据本季申报值。",
    }

    record = staging["quarterly_guidance_history"]
    last = record["periods"].index(periods[-1])
    delivery = [
        ("收入", pct_change(revenue[-1], record["guide_revenue_usd_m"][last])),
        ("Adjusted EBITDA 利润率",
         record["actual_ebitda_margin_pct"][last] - record["guide_ebitda_margin_pct"][last]),
        ("半导体分部收入", pct_change(semi_rev[-1], semi_rev[-2])),
        ("基础设施软件收入", pct_change(isg_rev[-1], isg_rev[-2])),
        ("自由现金流利润率", fcf_margin[-1] - fcf_margin[-2]),
    ]
    delivery_chart = {
        "kind": "diverging_bars",
        "title": (
            f"本季两条指引都过了，但都只多出一点点："
            f"收入 {signed(delivery[0][1], 2)}、EBITDA 利润率 {signed(delivery[1][1], 2, 'pp')}"
        ),
        "xlabels": [metric for metric, _ in delivery],
        "values": [round(value, 2) for _, value in delivery],
        "legend": "本季表现",
        "positive_label": "优于指引 / 环比改善",
        "negative_label": "逊于指引 / 环比转弱",
        "fmt": "f1", "yfmt": "f1", "label_fmt": "f1",
        "ylab": "% 或 pp", "zero_line": True,
        "note": (
            f"前两条是与公司自身指引的比较（指引 US${record['guide_revenue_usd_m'][last]:,.0f}M、"
            f"EBITDA 利润率 {record['guide_ebitda_margin_pct'][last]:.0f}%），"
            "后三条是环比变化，放在同一根轴上只是为了一次看完，口径已在标签里区分。"
            f"收入超出指引 {delivery[0][1]:+.2f}%——这个幅度落在过去 24 季 "
            f"+0.17% 到 +3.53% 的常态带里，属于「照例过线」而不是意外。"
        ),
        "src_extra": SOURCE_8K,
    }

    delivery_charts, delivery_tables = guidance_delivery_charts(staging)
    settled_ex = number_exhibits(
        [closure_chart, verdict_chart, delivery_chart] + delivery_charts, start=2)

    # ── section two ──────────────────────────────────────────────────────────
    revenue_chart = {
        "ref": "EX_REVENUE",
        "kind": "gs_bar",
        "title": (
            f"收入 US${revenue[-1]:,.0f}M、同比 {signed(yoy[-1])}，"
            f"半导体占比升到 {semi_share[-1]:.0f}%"
        ),
        "xlabels": labels,
        "values": revenue[tail],
        "legend": "季度收入",
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M", "ylab2": "同比增速",
        "yoy": {"name": "收入 YoY (RHS)", "values": rounded(yoy[tail]), "color": "GREEN", "yfmt": "pct0"},
        "note": (
            f"环比 {signed(pct_change(revenue[-1], revenue[-2]), 1)}。"
            f"半导体分部收入同比 {signed(pct_change(semi_rev[-1], semi_rev[-5]))}，"
            f"基础设施软件同比 {signed(pct_change(isg_rev[-1], isg_rev[-5]))}——"
            "同一家公司里两条增速差着一个数量级，这正是下一张图要拆的东西。"
        ),
        "src_extra": "收入与分部收入取自各季业绩 8-K；与 XBRL companyfacts 逐季一致。",
    }

    mix_chart = {
        "ref": "EX_MIX",
        "kind": "grouped_bars",
        "title": (
            f"两个引擎：半导体 US${semi_rev[-1]:,.0f}M、软件 US${isg_rev[-1]:,.0f}M，"
            f"半导体占比从 {semi_share[-WINDOW]:.0f}% 回到 {semi_share[-1]:.0f}%"
        ),
        "xlabels": labels,
        "groups": [
            {"name": "半导体解决方案", "values": semi_rev[tail], "color": "NAVY"},
            {"name": "基础设施软件", "values": isg_rev[tail], "color": "BLUE"},
        ],
        "bar_labels": False,
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c", "ylab": "US$M",
        "note": (
            "VMware 并入后软件一度把半导体的占比压到六成以下；"
            f"AI 放量把它推了回去，本季 {semi_share[-1]:.1f}%，"
            f"是八季里最高的一季。两条线的利润结构完全不同，见 Exhibit {{EX_SEG_MARGIN}}。"
        ),
        "src_extra": "分部收入为公司申报的两个报告分部，取自各季业绩 8-K 与 10-Q 分部附注（两处一致）。",
    }

    ai_labels = [compact_period(period) for period in ai["periods"]]
    ai_chart = {
        "ref": "EX_AI",
        "kind": "grouped_bars",
        "title": (
            f"AI 半导体收入：公司口头指引与随后报出的实际值，"
            f"下季的口头目标是 US${ai['next_quarter_guide_usd_bn']:.1f}B"
        ),
        "xlabels": ai_labels,
        "groups": [
            {"name": "上一季给出的口头指引", "values": ai["guided_usd_bn"], "color": "GRAY"},
            {"name": "随后报出的实际值", "values": ai["actual_usd_bn"], "color": "NAVY"},
        ],
        "bar_labels": True,
        "fmt": "usd1", "yfmt": "usd1", "label_fmt": "usd1", "ylab": "US$B",
        "note": (
            "<b>这张图的口径与第一节那几张不同，不要放在一起读。</b>"
            "AI 半导体收入<b>不是</b>公司的申报分部，这些数字出自业绩新闻稿里的 CEO 引语，"
            "精度只有 US$0.1B；下季的 US$16.0B 同样出自引语，"
            "不在正式的 Business Outlook 区块内。"
            f"Q1 2025 一季公司的原话是「over $4.4 billion」，是下限不是点值；"
            f"Q3 2025 一季新闻稿只给了同比增速、没有给水平值，因此留空——"
            "这个洞是披露本身的洞，不是取数失败。"
            "就已有的四对而言，实际值每次都略高于口头指引，与正式指引的形态一致。"
        ),
        "src_extra": (
            "取自各季业绩 8-K EX-99.1 新闻稿的 CEO 引语。"
            "公司不按 AI / 非 AI 拆分申报收入，故无法与分部附注交叉验证。"
        ),
    }

    seg_profit_chart = {
        "ref": "EX_SEG_PROFIT",
        "kind": "grouped_bars",
        "title": (
            f"两个分部的申报营业利润：半导体 US${semi_oi[-1]:,.0f}M、"
            f"软件 US${isg_oi[-1]:,.0f}M，两者相加恰好等于公司的 non-GAAP 营业利润"
        ),
        "xlabels": labels,
        "groups": [
            {"name": "半导体分部营业利润", "values": semi_oi[tail], "color": "NAVY"},
            {"name": "软件分部营业利润", "values": isg_oi[tail], "color": "BLUE"},
        ],
        "bar_labels": False,
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c", "ylab": "US$M",
        "note": (
            "<b>这不是巧合，是可核对的恒等式</b>：在分部附注给出分部营业利润的全部 30 个季度里，"
            "两个（FY2019 之前是三个）分部的申报营业利润之和<b>逐季精确等于</b>"
            "公司当季的 non-GAAP 营业利润，一分不差。"
            "所以公司指引的那条 non-GAAP 营业利润率，可以毫无估计地拆到两个引擎上——"
            f"本季软件分部只贡献了 {isg_rev[-1] / revenue[-1] * 100:.0f}% 的收入，"
            f"却贡献了 {isg_oi[-1] / (semi_oi[-1] + isg_oi[-1]) * 100:.0f}% 的分部营业利润。"
        ),
        "src_extra": (
            "分部营业利润逐季读自 10-Q / 10-K 的分部附注 R 文件；"
            "财年第四季为该财年数减去前三季。"
        ),
    }

    wedge_chart = {
        "ref": "EX_WEDGE",
        "kind": "lines",
        "title": (
            f"GAAP 与 non-GAAP 营业利润率的缺口：本季 "
            f"{ng_margin[-1] - gaap_margin[-1]:.1f}pp，收购摊销与股权激励是主要内容"
        ),
        "xlabels": long_labels,
        "series": [
            {"name": "non-GAAP 营业利润率", "values": rounded(ng_margin), "color": "NAVY"},
            {"name": "GAAP 营业利润率", "values": rounded(gaap_margin), "color": "BLUE"},
            {"name": "Adjusted EBITDA 利润率", "values": rounded(ebitda_margin), "color": "GREEN"},
        ],
        "fmt": "pct0", "yfmt": "pct0", "label_fmt": "pct1",
        "end_label": True, "ylab": "占收入 %",
        "note": (
            "三条线画在一起是为了说明公司指引的是哪一条："
            "Adjusted EBITDA 利润率（绿）和 non-GAAP 营业利润率（深蓝）都是公司自定义口径，"
            "而它<b>从不指引</b> GAAP 利润率（浅蓝）。"
            f"两条口径之间的缺口在 VMware 并表后一度扩大到 "
            f"{max(n - g for n, g in zip(ng_margin, gaap_margin) if n is not None and g is not None):.0f}pp 以上，"
            f"本季 {ng_margin[-1] - gaap_margin[-1]:.1f}pp。"
            "长期序列一律用 GAAP，因为 GAAP 的定义在整个窗口内没有变过。"
        ),
        "src_extra": (
            "GAAP 营业利润取自合并损益表；non-GAAP 营业利润与 Adjusted EBITDA "
            "取自同一份新闻稿的对账表。"
        ),
    }

    commit_chart = {
        "ref": "EX_COMMIT",
        "kind": "gs_bar",
        "title": (
            f"无条件采购承诺一季之内从 US${commitments['total'][-2]:,.0f}M 跳到 "
            f"US${commitments['total'][-1]:,.0f}M"
        ),
        "xlabels": long_labels,
        "values": rounded(commitments["total"]),
        "legend": "无条件采购承诺（期末余额）",
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c", "ylab": "US$M",
        "note": (
            f"前 32 个季度这条线一直在 "
            f"US${min(v for v in commitments['total'][:-1] if v is not None):,.0f}M–"
            f"US${max(v for v in commitments['total'][:-1] if v is not None):,.0f}M 之间，"
            f"本季一次性跳到 US${commitments['total'][-1]:,.0f}M——"
            f"其中 US${commitments['due_within_one_year'][-1]:,.0f}M 落在一年内、"
            f"US${commitments['due_in_year_two'][-1]:,.0f}M 落在第二年。"
            "这是本季信息量最大的一条申报数：把「产能锁到 2028」从电话会上的说法"
            "变成了资产负债表附注里的合同金额。"
            "它同时是两件事——基线情形下是收入的前瞻指标，"
            "需求不及预期时则是 take-or-pay 的刚性成本。"
            "注意纵轴是线性的，所以前 32 季在图上几乎贴着零，那不是没有数据。"
        ),
        "src_extra": "取自各季 10-Q / 10-K 承诺与或有事项附注的 XBRL 标签，逐季申报值。",
    }

    working_chart = {
        "ref": "EX_WORKING",
        "kind": "grouped_bars",
        "title": (
            f"营运资本随 AI 放量变重：存货 US${working['inventory'][-1]:,.0f}M、"
            f"应收 US${working['accounts_receivable'][-1]:,.0f}M，两项同比合计多占用 "
            f"US${(working['inventory'][-1] + working['accounts_receivable'][-1]) - (working['inventory'][-5] + working['accounts_receivable'][-5]):,.0f}M"
        ),
        "xlabels": labels,
        "groups": [
            {"name": "存货", "values": working["inventory"][tail], "color": "BLUE"},
            {"name": "应收账款", "values": working["accounts_receivable"][tail], "color": "NAVY"},
        ],
        "bar_labels": False,
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c", "ylab": "US$M",
        "note": (
            f"存货环比 {signed(pct_change(working['inventory'][-1], working['inventory'][-2]))}、"
            f"应收环比 {signed(pct_change(working['accounts_receivable'][-1], working['accounts_receivable'][-2]))}。"
            "一家资本开支只占收入 1% 的公司，它的产能扩张成本不体现在 capex 上，"
            "而是体现在这两条线上——这是读 fab-lite 报表时最容易漏掉的一处。"
        ),
        "src_extra": "取自各季 10-Q / 10-K 资产负债表。",
    }

    highlight_ex = number_exhibits(
        [revenue_chart, mix_chart, ai_chart, seg_profit_chart, wedge_chart,
         commit_chart, working_chart],
        start=settled_ex[-1]["n"] + 1)

    # ── section three ────────────────────────────────────────────────────────
    next_kpi = staging["next_kpi"]["quantified"]
    headroom_chart = headroom_exhibit(
        "下季五条跟踪线：当前值离阈值还有多远",
        next_kpi, "current",
        note=(
            "正值表示当前已在安全侧，负值表示还要走一段才够。"
            "前两条是<b>增长型</b>阈值——公司对下季给出的收入指引本身就是触发线，"
            "所以本季的水平天然低于它，负值在这里读作「下季需要爬升的幅度」，不是警报。"
            "后三条是<b>水平型</b>阈值，当前值直接可比。"
            + staging["next_kpi"]["excluded"]
        ),
        src_extra="阈值为本地研究设定，不是公司指引；当前值为本季申报值或自算值。",
    )

    def tracking_charts(entries: list[dict]) -> list[dict]:
        charts = []
        series_for = {
            "AI 半导体收入（季）": (
                ai_labels,
                [None if v is None else v * 1000 for v in ai["actual_usd_bn"]],
                "AI 半导体收入（US$M）",
                "本页仅有的六季来自新闻稿 CEO 引语，其中一季公司只给了增速、故留空。"),
            "基础设施软件收入": (
                labels, isg_rev[tail], "软件分部收入（US$M）",
                "公司申报分部，逐季可比。"),
            "Adjusted EBITDA 利润率": (
                labels, rounded(ebitda_margin[tail]), "Adjusted EBITDA 利润率",
                "公司自定义口径，实际值为 Adjusted EBITDA 除以收入的自算值。"),
            "non-GAAP 营业利润率": (
                labels, rounded(ng_margin[tail]), "non-GAAP 营业利润率",
                "公司首次为这条给出指引，因此没有历史兑现记录可比。"),
            "季度回购": (
                labels, capital["share_repurchases"][tail], "季度回购（US$M）",
                "取自现金流量表融资活动。"),
        }
        for entry in entries:
            xlabels, values, name, extra = series_for[entry["metric"]]
            charts.append(threshold_exhibit(
                f"{entry['metric']}：阈值 {unit_text(entry['unit'], entry['threshold'])}",
                xlabels, values, entry["threshold"],
                fmt="f0c" if entry["unit"] == "usd_m" else "pct1",
                ylab=name, actual_name=name, threshold_name="阈值",
                note=entry["note"] + extra,
                src_extra="阈值为本地研究设定；实际值为公司申报值或自算值。",
            ))
        return charts

    next_ex = number_exhibits(
        [headroom_chart] + tracking_charts(next_kpi),
        start=highlight_ex[-1]["n"] + 1)

    # ── section four ─────────────────────────────────────────────────────────
    seg_margin_chart = {
        "ref": "EX_SEG_MARGIN",
        "kind": "lines",
        "title": (
            f"两个引擎的分部营业利润率：软件 {isg_margin[-1]:.0f}%、"
            f"半导体 {semi_margin[-1]:.0f}%，软件在 VMware 并入后追平并反超"
        ),
        "xlabels": long_labels,
        "series": [
            {"name": "半导体分部", "values": rounded(semi_margin), "color": "NAVY"},
            {"name": "基础设施软件分部", "values": rounded(isg_margin), "color": "BLUE"},
        ],
        "fmt": "pct0", "yfmt": "pct0", "label_fmt": "pct1",
        "end_label": True, "ylab": "分部营业利润率",
        "note": (
            "两条线讲的是这家公司为什么长成现在这样：软件分部的利润率在 VMware 并入后从"
            f"七成出头一路抬到 {max(v for v in isg_margin if v is not None):.0f}% 上下，"
            "靠的是把收购来的产品并进现有渠道而几乎不增加成本；"
            "半导体分部则在 AI 放量下保持在六成上下。"
            "最左边的两三季只有半导体与软件两条、没有第三条，"
            "是因为当时还有一个很小的 IP licensing 分部，其收入与利润已并入核对表。"
            "分部<b>毛利率</b>本页不画：公司到 FY2025 10-K 才首次按 ASU 2023-07 披露分部成本，"
            "季度序列只有两个点，画不成线。"
        ),
        "src_extra": "分部收入与分部营业利润逐季取自 10-Q / 10-K 分部附注。",
    }

    intensity_chart = {
        "ref": "EX_INTENSITY",
        "kind": "lines",
        "title": (
            f"资本强度：资本开支只占收入 {capex_intensity[-1]:.1f}%，"
            f"研发占 {rnd_intensity[-1]:.1f}%——钱花在人身上，不花在厂房上"
        ),
        "xlabels": long_labels,
        "series": [
            {"name": "研发费用 / 收入", "values": rounded(rnd_intensity), "color": "NAVY"},
            {"name": "资本开支 / 收入", "values": rounded(capex_intensity), "color": "RED"},
        ],
        "fmt": "pct0", "yfmt": "pct0", "label_fmt": "pct1",
        "end_label": True, "ylab": "占收入 %",
        "note": (
            "这张图是本页与页尾那张 AI capex 循环表的接口。"
            f"表里四家云厂的现金资本开支占收入普遍在两成以上，Broadcom 是 "
            f"{capex_intensity[-1]:.1f}%——"
            "同一条 AI 产业链上，上游花的是别人的资本开支，自己几乎不花。"
            f"研发强度从窗口初的 {rnd_intensity[0]:.0f}% 降到 {rnd_intensity[-1]:.0f}%，"
            "分母涨得比分子快，不是研发投入在收缩（绝对额同期从 "
            f"US${rnd[0]:,.0f}M 涨到 US${rnd[-1]:,.0f}M）。"
            "真正的产能成本落在营运资本上，见前面的存货与应收那张。"
        ),
        "src_extra": "资本开支与研发费用逐季取自现金流量表与损益表（财年第四季为年度数减前三季）。",
    }

    conversion_chart = {
        "ref": "EX_FCF",
        "kind": "gs_bar",
        "title": (
            f"自由现金流 US${fcf[-1]:,.0f}M、占收入 {fcf_margin[-1]:.0f}%，"
            f"为本页 {len(periods)} 季记录中最高"
        ),
        "xlabels": long_labels,
        "values": rounded(fcf),
        "legend": "自由现金流 D",
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M", "ylab2": "占收入",
        "yoy": {"name": "FCF 利润率 (RHS)", "values": rounded(fcf_margin), "color": "GREEN", "yfmt": "pct0"},
        "note": (
            "自由现金流在这里是<b>自算值</b>：经营现金流减去资本开支，"
            "与公司在新闻稿里印出来的同名数字定义一致，逐季核对相符。"
            f"占收入的比重从窗口初的 {fcf_margin[0]:.0f}% 抬到 {fcf_margin[-1]:.0f}%，"
            "抬升几乎全部来自利润率而不是资本开支的节省——后者本来就只有 1% 上下，省无可省。"
        ),
        "src_extra": "经营现金流与资本开支取自现金流量表；两项均与新闻稿披露的当季数一致。",
    }

    debt_chart = {
        "ref": "EX_DEBT",
        "kind": "lines",
        "title": (
            f"VMware 之后的去杠杆：总债务 US${capital['total_debt'][-1]:,.0f}M、"
            f"净债务 US${net_debt[-1]:,.0f}M，净债务较峰值下降 "
            f"US${max(v for v in net_debt if v is not None) - net_debt[-1]:,.0f}M"
        ),
        "xlabels": long_labels,
        "series": [
            {"name": "总债务（长期＋一年内到期）", "values": rounded(capital["total_debt"]), "color": "NAVY"},
            {"name": "净债务 D（总债务 − 现金）", "values": rounded(net_debt), "color": "RED"},
            {"name": "现金及等价物", "values": rounded(capital["cash_and_equivalents"]), "color": "GREEN"},
        ],
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "end_label": True, "ylab": "US$M",
        "note": (
            "两级台阶都看得见：2019 年的 CA / Symantec，以及 2024 年初 VMware 把总债务一次抬到 "
            f"US${max(v for v in capital['total_debt'] if v is not None):,.0f}M。"
            f"此后净债务从峰值 US${max(v for v in net_debt if v is not None):,.0f}M "
            f"降到 US${net_debt[-1]:,.0f}M。"
            "本季的去杠杆有一半不是还债换来的，而是现金堆积——"
            f"回购从上季的 US${capital['share_repurchases'][-2]:,.0f}M 砍到 "
            f"US${capital['share_repurchases'][-1]:,.0f}M，公司没有解释原因。"
        ),
        "src_extra": (
            "总债务为资产负债表长期债务与一年内到期部分之和。"
            "公司在 FY2023–FY2025 期间改用了含融资租赁的标签、FY2026 又改回，"
            "两套标签在重叠期取值一致，本页按同一口径接续。"
        ),
    }

    payout_chart = {
        "ref": "EX_PAYOUT",
        "kind": "grouped_bars",
        "title": (
            f"股东回报与其资金来源：本季回购 US${capital['share_repurchases'][-1]:,.0f}M、"
            f"分红 US${capital['common_dividends'][-1]:,.0f}M，合计只占自由现金流 "
            f"{(capital['share_repurchases'][-1] + capital['common_dividends'][-1]) / fcf[-1] * 100:.0f}%"
        ),
        "xlabels": labels,
        "groups": [
            {"name": "自由现金流 D", "values": rounded(fcf[tail]), "color": "GREEN"},
            {"name": "回购", "values": capital["share_repurchases"][tail], "color": "NAVY"},
            {"name": "普通股分红", "values": capital["common_dividends"][tail], "color": "BLUE"},
        ],
        "bar_labels": False,
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c", "ylab": "US$M",
        "note": (
            "分红这条线八季几乎是平的，回购则在两季之间从 "
            f"US${capital['share_repurchases'][-2]:,.0f}M 掉到 "
            f"US${capital['share_repurchases'][-1]:,.0f}M，"
            "同一季自由现金流创了新高、现金余额多出 "
            f"US${capital['cash_and_equivalents'][-1] - capital['cash_and_equivalents'][-2]:,.0f}M。"
            "钱没有还给股东，也没有花在资本开支上（那一项只有 1%），它留在了资产负债表上。"
            "本页不推测原因——公司未作说明，这里只把三条线并排放着。"
        ),
        "src_extra": "回购与分红取自现金流量表融资活动；自由现金流为经营现金流减资本开支。",
    }

    routine_ex = number_exhibits(
        [seg_margin_chart, intensity_chart, conversion_chart, debt_chart, payout_chart],
        start=next_ex[-1]["n"] + 1)

    all_ex = settled_ex + highlight_ex + next_ex + routine_ex
    resolve_exhibit_refs(all_ex)

    # ── audit tables ─────────────────────────────────────────────────────────
    def fmt_row(values, spec="{:,.0f}"):
        return ["—" if v is None else spec.format(v) for v in values]

    tables = []
    for index, table in enumerate(delivery_tables):
        tables.append({"n": index + 1, **table})
    tables.append({
        "n": len(tables) + 1,
        "title": f"八季度收入、利润率与现金流（US$M，利润率为自算）",
        "headers": ["项目"] + [f"{p}（{f}）" for p, f in zip(periods[tail], fiscal[tail])],
        "rows": [
            ["收入"] + fmt_row(revenue[tail]),
            ["GAAP 营业利润"] + fmt_row(gaap_oi[tail]),
            ["non-GAAP 营业利润"] + fmt_row(ng_oi[tail]),
            ["Adjusted EBITDA"] + fmt_row(ebitda[tail]),
            ["GAAP 营业利润率 D"] + fmt_row(gaap_margin[tail], "{:.2f}%"),
            ["non-GAAP 营业利润率 D"] + fmt_row(ng_margin[tail], "{:.2f}%"),
            ["Adjusted EBITDA 利润率 D"] + fmt_row(ebitda_margin[tail], "{:.2f}%"),
            ["经营现金流"] + fmt_row(ocf[tail]),
            ["资本开支"] + fmt_row(capex[tail]),
            ["自由现金流 D"] + fmt_row(fcf[tail]),
        ],
    })
    tables.append({
        "n": len(tables) + 1,
        "title": "八季度分部收入与分部营业利润（US$M）",
        "headers": ["项目"] + [f"{p}（{f}）" for p, f in zip(periods[tail], fiscal[tail])],
        "rows": [
            ["半导体解决方案 收入"] + fmt_row(semi_rev[tail]),
            ["基础设施软件 收入"] + fmt_row(isg_rev[tail]),
            ["半导体 分部营业利润"] + fmt_row(semi_oi[tail]),
            ["基础设施软件 分部营业利润"] + fmt_row(isg_oi[tail]),
            ["两分部合计营业利润 D"] + fmt_row(
                [None if a is None or b is None else a + b for a, b in zip(semi_oi[tail], isg_oi[tail])]),
            ["公司 non-GAAP 营业利润（对照）"] + fmt_row(ng_oi[tail]),
            ["半导体 分部营业利润率 D"] + fmt_row(semi_margin[tail], "{:.1f}%"),
            ["基础设施软件 分部营业利润率 D"] + fmt_row(isg_margin[tail], "{:.1f}%"),
        ],
    })
    tables.append({
        "n": len(tables) + 1,
        "title": "八季度资本配置、营运资本与采购承诺（US$M）",
        "headers": ["项目"] + [f"{p}（{f}）" for p, f in zip(periods[tail], fiscal[tail])],
        "rows": [
            ["回购"] + fmt_row(capital["share_repurchases"][tail]),
            ["普通股分红"] + fmt_row(capital["common_dividends"][tail]),
            ["现金及等价物"] + fmt_row(capital["cash_and_equivalents"][tail]),
            ["总债务"] + fmt_row(capital["total_debt"][tail]),
            ["净债务 D"] + fmt_row(net_debt[tail]),
            ["存货"] + fmt_row(working["inventory"][tail]),
            ["应收账款"] + fmt_row(working["accounts_receivable"][tail]),
            ["无条件采购承诺"] + fmt_row(commitments["total"][tail]),
            ["其中一年内到期"] + fmt_row(commitments["due_within_one_year"][tail]),
            ["其中第二年到期"] + fmt_row(commitments["due_in_year_two"][tail]),
        ],
    })
    tables.append({
        "n": len(tables) + 1,
        "title": "AI 半导体收入的口头指引与实际值（US$B，出自新闻稿 CEO 引语，非申报分部）",
        "headers": ["本站季度", "上一季给出的口头指引", "随后报出的实际值", "指引所在新闻稿"],
        "rows": [
            [period,
             "—" if g is None else f"{g:.1f}",
             "—" if a is None else (f"≥{a:.1f}" if floor else f"{a:.1f}"),
             rel or "—"]
            for period, g, a, floor, rel in zip(
                ai["periods"], ai["guided_usd_bn"], ai["actual_usd_bn"],
                ai["actual_is_floor"], ai["guided_in_release"])
        ] + [[ai["next_quarter_period"], f"{ai['next_quarter_guide_usd_bn']:.1f}", "待披露",
              ai["next_quarter_guided_in_release"]]],
    })
    tables.append(threshold_table(
        len(tables) + 1, "下季跟踪线（原始单位）", next_kpi, "current", "当前值"))
    tables.append(ai_capex_cycle_table(len(tables) + 1))

    finished_count = sum(1 for v in record["actual_revenue_usd_m"] if v is not None)
    point_count = sum(1 for form, actual in zip(record["revenue_form"], record["actual_revenue_usd_m"])
                      if form == "point" and actual is not None)
    range_count = sum(1 for form in record["revenue_form"] if form == "range")
    margin_count = sum(1 for g, a in zip(record["guide_ebitda_margin_pct"],
                                         record["actual_ebitda_margin_pct"])
                       if g is not None and a is not None)
    median_days = statistics.median(record["days_into_quarter_at_release"])

    return {
        "schema_version": "quarterly-dashboard/avgo-v1",
        "page": {"slug": "avgo", "language": "zh-CN"},
        "company": {
            "ticker": "AVGO",
            "name": "Broadcom",
            "group": "semiconductor_ai",
            "accounting_standard": "US GAAP",
        },
        "latest": {
            "disclosed_period_label": periods[-1],
            "full_financial_period_label": periods[-1],
            "period_end": ends[-1],
            "release_date": staging["release_dates"][-1],
            "analysis_date": "2026-08-29",
            "audit_status": "unaudited",
            "status": "history_ready",
        },
        "tracker": "Watchlist Quarterly Tracker · AVGO",
        "title": f"Broadcom (AVGO)：{periods[-1]} 季报仪表盘",
        "subtitle": (
            f"截至 {ends[-1]} · 发布 {staging['release_dates'][-1]} · US GAAP · 未审计 · "
            f"11 月制财年，本站按自然年季度标注：本页 {periods[-1]} 即公司所称 {fiscal[-1]}"
        ),
        "headline": (
            f"收入 US${revenue[-1]:,.0f}M、同比 {signed(yoy[-1])}，"
            f"Adjusted EBITDA 利润率 {ebitda_margin[-1]:.1f}%，"
            f"两条指引照例都过了——而这正是问题所在："
            # `headline` is written with `node.textContent`, so a tag here reaches
            # the reader as the literal characters `<b>`. Emphasis belongs in
            # `brief` or an exhibit's `note`, which are raw innerHTML.
            f"{finished_count} 个已完结季里实际收入一次都没有低于指引的点或中值，"
            f"偏离却始终挤在 +0.17% 到 +3.53% 这条窄带里，"
            f"且指引是在被指引季度已经过了中位 {median_days:.0f} 天时才发布的；"
            f"同一季，无条件采购承诺从 US${commitments['total'][-2]:,.0f}M 跳到 "
            f"US${commitments['total'][-1]:,.0f}M，回购从 "
            f"US${capital['share_repurchases'][-2]:,.0f}M 砍到 "
            f"US${capital['share_repurchases'][-1]:,.0f}M。"
        ),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>记录</span><b>指引的形式变了，答案也跟着变</b>'
            f'<p>给区间的 {range_count} 季，实际值季季落在<b>区间之内</b>；'
            f'改给单点后的 {point_count} 季，季季落在<b>点之上</b>。'
            f'Adjusted EBITDA 利润率 {margin_count} 季全部高于指引。</p></article>'
            '<article><span>转折</span><b>承诺一夜之间上了两个数量级</b>'
            f'<p>无条件采购承诺 US${commitments["total"][-1]:,.0f}M，'
            f'其中 US${commitments["due_within_one_year"][-1]:,.0f}M 在一年内、'
            f'US${commitments["due_in_year_two"][-1]:,.0f}M 在第二年。'
            f'前 32 季这条线从没超过 US$1.5B。</p></article>'
            '<article><span>结构</span><b>两个引擎，利润在软件那边</b>'
            f'<p>软件贡献 {isg_rev[-1] / revenue[-1] * 100:.0f}% 的收入、'
            f'{isg_oi[-1] / (semi_oi[-1] + isg_oi[-1]) * 100:.0f}% 的分部营业利润；'
            f'两个分部利润相加逐季<b>精确等于</b>公司的 non-GAAP 营业利润。</p></article>'
            '</div>'
        ),
        "source": source,
        "source_url": (
            "https://www.sec.gov/Archives/edgar/data/1730168/"
            "000173016826000051/avgo-05032026x8kxex99.htm"
        ),
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": {
            "title": f"下季（本站 {guidance['period']}，公司 {guidance['fiscal_label']}）指引",
            "headers": ["指标", "指引", "形式", "出处"],
            "rows": [
                ["收入", f"约 US${guidance['revenue_usd_bn']:.1f}B", "单点",
                 "Business Outlook 区块"],
                ["non-GAAP 营业利润率",
                 f"约为收入的 {guidance['non_gaap_operating_margin_pct']:.0f}%", "单点",
                 "Business Outlook 区块（史上第一次）"],
                ["Adjusted EBITDA 利润率",
                 f"约为收入的 {guidance['adjusted_ebitda_margin_pct']:.0f}%", "单点",
                 "Business Outlook 区块"],
                ["AI 半导体收入",
                 f"US${guidance['ai_semiconductor_revenue_usd_bn']:.1f}B", "单点",
                 "CEO 引语，不在 Business Outlook 区块内"],
            ],
            "note": guidance["note"] + f" 该季于 {guidance['period_end']} 结束，预计 {guidance['expected_release']}发布。",
        },
        "sections": [
            {
                "id": "settled",
                "title": "一、上季兑现了吗",
                "description": (
                    "先结清上季设下的阈值，再看新数字。Broadcom 每季在业绩新闻稿的 "
                    "Business Outlook 区块给出下一季的收入与 Adjusted EBITDA 利润率，"
                    "所以「有没有做到」在这里有八年的答案——"
                    "而这段记录里真正会变的，是公司愿意公布哪一种形式的指引。"
                ),
                "exhibits": settled_ex,
            },
            {
                "id": "highlights",
                "title": "二、本季重点",
                "description": (
                    "收入结构、两个分部各自的利润、GAAP 与自定义口径之间的缺口，"
                    "以及本季信息量最大的一条申报数：采购承诺。"
                ),
                "exhibits": highlight_ex,
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": "当前值离下季阈值还有多远，统一用「距阈值余量」口径。",
                "exhibits": next_ex,
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": (
                    "AVGO 专属的常规序列：两个引擎的分部利润率、fab-lite 的资本强度、"
                    "现金转化，以及 VMware 之后的去杠杆路径。"
                ),
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            (f"本页所有季度按自然年标注。Broadcom 财年 11 月初结束，故本页的 {periods[-1]} "
             f"是截至 {ends[-1]} 的季度，公司自己称之为 {fiscal[-1]}；"
             "映射规则为公司 FY 的 Q1→上一自然年 Q4、Q2→Q1、Q3→Q2、Q4→Q3，"
             "与本站 Synopsys 页（10 月制财年）用的是同一条规则。"
             "不统一成一种约定，跨公司的资本开支对照表就会把不同的三个月放在一起比较。"),
            (f"第一节的指引兑现组图（Exhibit {settled_ex[3]['n']}–{settled_ex[-1]['n']}）"
             "用的是同一批业绩 8-K 的 EX-99.1「Business Outlook」区块。"
             f"公司在这 33 份新闻稿里换过四次指引形式：FY2018 是含 GAAP/non-GAAP 对照表的收入区间；"
             f"整个 FY2019 只给财年数；FY2020 前三季回到季度区间；"
             f"自 FY2021 Q1 的指引起改为单点，且 Adjusted EBITDA 从美元金额改为「占预计收入的百分比」；"
             f"VMware 并表那一年又有三份新闻稿只给财年数。"
             f"因此已完结的季度收入指引共 {finished_count} 条，"
             f"其中 {range_count} 条是区间、{point_count} 条是单点。"),
            (f"窗口内有 8 个已申报季度从未被单独指引过（FY2019 四季、FY2020 Q1，"
             f"以及 VMware 并表年的 FY2024 前三季），它们在偏离图上是空档而不是零。"
             "这些只按财年给出的指引单列在核对抽屉的第 2 张表里。"),
            (f"指引发布时点：公司在上一季业绩发布时才给出这一季的指引，"
             f"而那场发布落在被指引季度开始之后，中位数为 91 天里的第 {median_days:.0f} 天。"
             "所以「从未低于指引」不是一句纯粹的事前预测记录；这条提醒印在每一张指引图上，"
             "而不是只放在这里。"),
            ("Adjusted EBITDA 与 non-GAAP 营业利润都是公司自定义口径（在 GAAP 基础上加回"
             "收购无形资产摊销、股权激励、重组与收购相关费用等）。"
             "每一对「指引 vs 实际」都在当时适用的同一套口径内部比较；"
             "长期水平序列一律用 GAAP，因为 GAAP 的定义在整个窗口内没有变过。"),
            ("分部营业利润之和等于 non-GAAP 营业利润，这是本页几张分部图的前提，"
             "并非假设：在分部附注给出分部营业利润的全部 30 个季度里逐季精确相等"
             "（FY2019 及以前需把已停止披露的第三个分部 IP licensing 一并计入）。"
             "这条恒等式已写成测试。"),
            ("财年第四季在 XBRL 里没有单独的季度事实，本页的第四季值取自该季业绩新闻稿；"
             "分部数据的第四季则为该财年数减去前三季。两条路径在 7 个完整财年上互相验证一致。"),
            ("AI 半导体收入不是公司的申报分部。本页相关数字出自各季业绩新闻稿的 CEO 引语，"
             "精度为 US$0.1B，其中一季公司只给了同比增速、没有给水平值（图上留空），"
             "另一季的措辞是「over $4.4 billion」（下限而非点值）。"
             "这条口径与 Business Outlook 区块里的三条正式指引不同级，本页分开画、不合并统计。"),
            ("分部毛利率本页不画。公司到 FY2025 10-K 才首次按 ASU 2023-07 披露分部成本，"
             "可用的季度点只有两个。上季本地研究把「半导体分部毛利率 68%」设成过阈值，"
             "本页据此把该条判为无法判定，而不是折算成通过或失败。"),
            ("自由现金流为自算值：经营现金流减去资本开支，与公司在新闻稿里印出的同名数字定义一致，"
             "逐季核对相符。"),
            "本页只发布公司披露值、可复算的简单派生值，以及明确标注的市场预期；D 标记代表 Derived / 自算。",
            "市场预期一律标注为「市场预期」并给出取数时点，不写卖方机构名，也不发布评级、目标价或估值。",
            ("本页已知未接入：客户租赁 backstop 的实际敞口路径与会计处理（10-Q 只给了最大敞口一个时点，"
             "构不成序列）；AI networking 占 AI 收入的比例（只在电话会上以「almost 40%」这种精度出现）；"
             "单一客户的收入占比与最大客户的份额（公司从不点名客户、也不披露单客户占比，"
             "第三方估计不在本页可发布范围内）；地区收入拆分（口径逐年变动，未按同一口径接续）；"
             "以及 FY2018 及以前的半导体/软件两分部拆分（当时的报告分部是按产品线划分的四个，不可接续）。"),
            "业绩电话会文字稿仅链接官方 IR 与 SEC 托管版本，公开仓不复制原件或逐字内容。",
        ],
        "footer": "AVGO quarterly results · 数据来自 Broadcom 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "avgo.js"), payload, "avgo")
    shell_dir = ROOT / "avgo"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("AVGO", "avgo"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(
        f"AVGO page: {charts} charts in {len(payload['sections'])} sections "
        f"+ {len(payload['tables'])} audit tables"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
