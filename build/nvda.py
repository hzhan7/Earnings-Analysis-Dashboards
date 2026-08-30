#!/usr/bin/env python3
"""Build the NVIDIA quarterly-results page.

Same four-part, chart-led shape as the other pages (上季兑现 → 本季重点 →
下季跟踪 → 长期常规), with section one built out the way TSMC's is, because
NVIDIA is the other company on this site that guides several numbers every
quarter in the same sentence structure: revenue ±2%, GAAP and non-GAAP gross
margin ±50bp, and GAAP and non-GAAP operating expenses as point numbers.

The comparison with TSMC is the reason this page is worth the build-out. TSMC's
operating-margin guidance turned out to be a floor -- fifteen quarters, not one
landing back inside the range. NVIDIA's record is two-sided, and the two sides
belong to different metrics: revenue cleared the top of its band in 21 of 24
quarters, while gross margin sat *inside* its band in 16 of 24 and broke the
bottom three times. Every one of those three breaks was a write-down, not a
demand miss -- which is exactly what the operating-income decomposition shows.

The public payload contains only NVIDIA-reported figures, clearly labelled
market expectations, and arithmetic reproducible from the audit tables.
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


STAGING_PATH = ROOT / "series" / "nvda.json"
DATA_DIR = ROOT / "data"

# The dollar band chart is drawn over a short window on purpose; see
# `guidance_delivery_charts`.
REVENUE_BAND_WINDOW = 8


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


# ── section one: the guided record ──────────────────────────────────────────
SOURCE_8K = (
    "指引区间来自各季业绩 8-K 的 EX-99.1 新闻稿 Outlook 段；"
    "实际值来自随后一季 8-K 的合并损益表与 GAAP/non-GAAP 对账表。"
)


def guidance_delivery_charts(staging: dict) -> tuple[list[dict], dict]:
    """The full guided record for all three guided metrics, and what the beats are made of.

    NVIDIA guides revenue (±2%), both gross margins (±50bp) and both operating
    expense lines every quarter, so "did the quarter clear the company's own
    bar" has a 23-quarter answer rather than an eight-quarter one -- and the
    answer differs sharply by metric, which is the whole reason for one chart
    per metric.

    The beat decomposition is an identity rather than an estimate. Guiding all
    three components implies an operating income the company never prints:

        implied non-GAAP OI = guided revenue × guided margin − guided opex

    and the distance from what was reported splits exactly three ways:

        actual − implied = (Ra − Rg)·mg  +  Ra·(ma − mg)  −  (Ea − Eg)

    Every term is a company-reported quarterly number or a company-published
    outlook number, so the split needs no estimate of any kind.
    """
    guide = staging["quarterly_guidance_history"]
    quarters = guide["quarters"]
    labels = [compact_period(quarter) for quarter in quarters]

    revenue_guide = guide["guide_revenue_usd_bn"]
    band = guide["revenue_band_pct"]
    revenue_lo = [value * (1 - width / 100) for value, width in zip(revenue_guide, band)]
    revenue_hi = [value * (1 + width / 100) for value, width in zip(revenue_guide, band)]
    revenue_actual = [
        None if value is None else value / 1000 for value in guide["actual_revenue_usd_m"]
    ]

    margin_guide = guide["non_gaap_gm_guide_pct"]
    margin_band = [value / 100 for value in guide["gm_band_bp"]]
    margin_lo = [value - width for value, width in zip(margin_guide, margin_band)]
    margin_hi = [value + width for value, width in zip(margin_guide, margin_band)]
    margin_actual = guide["actual_non_gaap_gm_pct"]

    finished = [index for index, value in enumerate(revenue_actual) if value is not None]

    # ── revenue ──────────────────────────────────────────────────────────────
    # The band is drawn over the last eight quarters only. NVIDIA's revenue went
    # from US$4.4B to US$91B across this record, so on one linear dollar axis the
    # early bands collapse to a few pixels and the chart stops answering its own
    # question. The scale-free version of the same question -- distance from the
    # guided midpoint, in percent -- carries the *whole* record in the next
    # chart, which is where the long-window reading belongs.
    window = slice(len(quarters) - REVENUE_BAND_WINDOW, len(quarters))
    revenue_band_chart = delivery_band(
        "EX_REV_RANGE", "收入", labels[window], revenue_lo[window], revenue_hi[window],
        revenue_actual[window],
        fmt="usd0", ylab="US$B", unit="US$B", venue="业绩发布",
        scope=f"（本图仅近 {REVENUE_BAND_WINDOW} 季）",
        src_extra=SOURCE_8K,
        extra_note=(
            "<b>这张只画最近八季，不是数据缺失</b>：本页的指引记录一路回到 2020 年，"
            "而收入在这段时间从 US$4.4B 长到 US$108B，二十多倍的量级差放在一根线性美元轴上，"
            "早年的 ±2% 区间会被压成几个像素，图就不再回答自己的问题了。"
            "完整 24 季的同一问题改用与量级无关的口径回答，见 Exhibit {EX_REV_DEV}。"
        ),
    )
    revenue_dev_chart = midpoint_deviation(
        "EX_REV_DEV", "收入", quarters, revenue_lo, revenue_hi, revenue_actual,
        mode="pct", window=len(finished), label=compact_period, bar_labels=False,
        src_extra=SOURCE_8K + "偏离为实际收入除以指引中值的自算值。",
        extra_note=(
            "<b>这是全页最该先读的一张</b>：24 个已完结季里 21 季高于指引中值 2% 以上"
            "（也就是穿出区间上限），公司的收入指引在这个窗口里更接近底线而不是预测。"
            "但它<b>不是</b>不可破的底线 —— Q2'22 一季 -17.2%，是本页唯一一次收入跌破下限，"
            "那一季游戏渠道去库存把已经给出的指引直接作废。"
            "柱高在这里可比，因为口径是百分比，不受收入量级二十倍变化的影响。"
        ),
    )

    # ── what the beat is made of ─────────────────────────────────────────────
    revenue_leg, margin_leg, opex_leg, leg_labels = [], [], [], []
    for index in finished:
        guided_revenue = revenue_guide[index] * 1000
        guided_margin = margin_guide[index] / 100
        guided_opex = guide["non_gaap_opex_guide_usd_bn"][index] * 1000
        actual_revenue = guide["actual_revenue_usd_m"][index]
        actual_margin = margin_actual[index] / 100
        actual_opex = guide["actual_non_gaap_opex_usd_m"][index]
        revenue_leg.append((actual_revenue - guided_revenue) * guided_margin / 1000)
        margin_leg.append(actual_revenue * (actual_margin - guided_margin) / 1000)
        opex_leg.append(-(actual_opex - guided_opex) / 1000)
        leg_labels.append(compact_period(quarters[index]))

    total = [sum(legs) for legs in zip(revenue_leg, margin_leg, opex_leg)]
    misses = [index for index, value in enumerate(total) if value < 0]
    # "Margin-driven" means the margin leg is the most negative of the three, so
    # the shortfall cannot be blamed on demand.
    margin_driven = [
        index for index in misses
        if margin_leg[index] == min(revenue_leg[index], margin_leg[index], opex_leg[index])
    ]
    miss_labels = "、".join(leg_labels[index] for index in misses)
    legs_chart = {
        "ref": "EX_OI_LEGS",
        "kind": "grouped_bars",
        "title": (
            f"把「超出自身指引」拆成三条腿：{len(total)} 季里只有 {len(misses)} 季为负，"
            + ("且全部是毛利率腿砸的，不是收入腿"
               if len(margin_driven) == len(misses)
               else f"其中 {len(margin_driven)} 季是毛利率腿砸的")
        ),
        "xlabels": leg_labels,
        "xrot": 90,
        "groups": [
            {"name": "收入腿", "color": "NAVY", "values": rounded(revenue_leg)},
            {"name": "毛利率腿", "color": "GOLD", "values": rounded(margin_leg)},
            {"name": "费用腿", "color": "MBLUE", "values": rounded(opex_leg)},
        ],
        # 69 bars in one card cannot carry 69 labels; the原值 live in this
        # card's own table view and in the guided-record audit table.
        "bar_labels": False,
        "fmt": "usd1",
        "label_fmt": "usd1",
        "ylab": "US$B vs 指引隐含营业利润",
        "note": (
            "公司同时给出收入、毛利率与营业费用三个数，于是<b>隐含</b>了一个自己从不印出来的"
            "营业利润：指引收入 × 指引毛利率 − 指引费用。实际 non-GAAP 营业利润与它的差"
            "<b>恰好</b>拆成三项之和（不是近似）："
            "收入腿 =（实际收入 − 指引收入）× 指引毛利率；"
            "毛利率腿 = 实际收入 ×（实际毛利率 − 指引毛利率）；"
            "费用腿 = −（实际费用 − 指引费用）。"
            "<b>读数：</b>正常季度里深蓝的收入腿几乎解释全部超额，金色与浅蓝小到看不见；"
            f"而没能达到自身隐含营业利润的 {len(misses)} 季（{miss_labels}），"
            "无一例外都是金色的毛利率腿塌下去 —— "
            "前两季是同一轮游戏渠道去库存的存货计提，"
            f"{leg_labels[misses[-1]]} 是 H20 出口管制的 US$4.5B 计提。"
            "<b>这几季的收入腿其实都不算差</b>："
            + "、".join(
                f"{leg_labels[index]} 收入腿 {revenue_leg[index]:+.1f}B / "
                f"毛利率腿 {margin_leg[index]:+.1f}B"
                for index in misses
            )
            + "。换句话说，这家公司迄今为止的经营意外来自成本与计提，不是来自需求 —— "
            "<b>这与 TSM 页第一节的读数正好互补</b>：那边是指引从不被打破，"
            "这边是指引会被打破，但打破它的从来不是需求那条腿。"
            "<b>交互项归属：</b>收入与毛利率同时偏离时的交叉项按上式全部计入毛利率腿；"
            "调换拆解顺序会把它移到收入腿，两种拆法的合计完全相同。"
        ),
        "src_extra": SOURCE_8K + "三条腿均为自算，指引原值与实际原值见核对表。",
    }

    # ── gross margin ─────────────────────────────────────────────────────────
    margin_band_chart = delivery_band(
        "EX_GM_RANGE", "non-GAAP 毛利率", labels, margin_lo, margin_hi, margin_actual,
        fmt="pct0", ylab="non-GAAP 毛利率", unit="%", venue="业绩发布",
        src_extra=(SOURCE_8K + "实际 non-GAAP 毛利率 = 对账表的 non-GAAP 毛利 ÷ 净收入 D。"),
        extra_note=(
            "<b>和收入那条完全相反</b>：毛利率的指引大部分时候是<b>真预测</b>而不是底线 —— "
            "16 季落在 ±50bp 的窄区间内，只有 5 季穿出上限。"
            "但它破起来极狠：三次跌破下限分别是 -21.3pp（Q2'22 游戏库存计提）、"
            "-8.9pp（Q3'22 同一轮去库存）与 -10.0pp（Q1'25 H20 出口管制计提），"
            "三次都是一次性计提，不是经营性下滑。"
            "这条线的形状本身就是本页的风险提示：这家公司的毛利率不会慢慢变坏，只会一次砸穿。"
        ),
    )
    margin_dev_chart = midpoint_deviation(
        "EX_GM_DEV", "non-GAAP 毛利率", quarters, margin_lo, margin_hi, margin_actual,
        mode="pp", window=len(finished), label=compact_period, bar_labels=False,
        src_extra=(SOURCE_8K + "实际 non-GAAP 毛利率 = 对账表的 non-GAAP 毛利 ÷ 净收入 D；"
                   "偏离为实际值减指引中值的自算值。"),
        extra_note=(
            "把 Exhibit {EX_GM_RANGE} 的三次跌破放到同一根轴上量幅度：正常季度的柱几乎贴着零轴"
            "（区间只有 ±0.5pp，公司命中率很高），三根深坑一眼可辨。"
            "<b>本页据此把下季 non-GAAP 毛利率的警戒线设在 73.5%</b> —— "
            "不是因为 0.5pp 的正常波动，而是因为一旦这条线明显下破，历史上都不是波动而是计提。"
        ),
    )

    # ── operating expenses ───────────────────────────────────────────────────
    # Opex is guided as a point number, not a range, so there is no band to
    # draw: the only question it can answer is by how much, which is this chart.
    opex_guide = guide["non_gaap_opex_guide_usd_bn"]
    opex_actual = [
        None if value is None else value / 1000 for value in guide["actual_non_gaap_opex_usd_m"]
    ]
    # The non-GAAP definition changed in Q1'26 to include stock-based
    # compensation, so the *level* series has a real discontinuity even though
    # each quarter's guidance and actual moved together. The break marker says
    # "not comparable across here" rather than drawing one continuous line.
    sbc_break = quarters.index("Q1 2026")
    opex_band_chart = delivery_band(
        "EX_OPEX_RANGE", "non-GAAP 营业费用", labels, opex_guide, opex_guide, opex_actual,
        fmt="usd1", ylab="US$B", unit="US$B", venue="业绩发布", point=True,
        break_at=sbc_break,
        break_label="口径变更：non-GAAP 起含股权激励费用",
        src_extra=SOURCE_8K + "费用指引为单点数，非区间。",
        extra_note=(
            "<b>和另外两条指引最大的不同是它没有宽度</b> —— 收入给 ±2%、毛利率给 ±50bp，"
            "费用只给一个数，所以这条线上不存在「区间内」这回事，只有高于或低于。"
            "菱形几乎粘在细线上，说明费用是这家公司最可预测的一条线；"
            "本图看的是<b>水平与斜率</b>，具体差多少见 Exhibit {EX_OPEX_DEV}。"
            "<b>红色竖线是口径断点</b>：自 Q1'26 起 non-GAAP 不再剔除股权激励费用，"
            "费用水平一次性抬高（Q4'25 US$5.10B → Q1'26 US$7.45B），"
            "断点左右的<b>绝对水平不可直接连着读</b>；"
            "但该季的指引与实际同在新口径下给出与报出，所以指引与实际的<b>相对关系</b>不受影响。"
        ),
    )
    opex_dev_chart = midpoint_deviation(
        "EX_OPEX_DEV", "non-GAAP 营业费用", quarters, opex_guide, opex_guide, opex_actual,
        mode="pct", window=len(finished), label=compact_period, bar_labels=False,
        src_extra=SOURCE_8K + "费用指引是单点数，偏离为实际除以该点的自算值。",
        extra_note=(
            "承接 Exhibit {EX_OPEX_RANGE}：那张画水平，这张只画差额。"
            "读法与另外两个指标相反：<b>负值才是好消息</b>（实际花得比承诺少）。"
            "柱子长期贴近零轴，24 季的平均绝对偏离只有个位数百分比。"
            "<b>这张图不受口径变更影响</b> —— 每一季的指引与实际都在同一口径下给出与报出，"
            "相除之后股权激励费用在分子分母里同时出现，"
            "所以这里没有 Exhibit {EX_OPEX_RANGE} 上那道断点。"
        ),
    )

    # Grouped by metric: each guided number's level chart is followed straight
    # away by its own deviation chart, so one metric is read through before the
    # next starts. Revenue's FX-free beat decomposition sits with revenue.
    charts = [
        revenue_band_chart, revenue_dev_chart, legs_chart,
        margin_band_chart, margin_dev_chart,
        opex_band_chart, opex_dev_chart,
    ]

    table = {
        "title": f"指引兑现全表（{len(quarters)} 季）：三项指引、实际值与超额的三条腿",
        "headers": ["期间", "收入指引", "实际收入", "较中值",
                    "non-GAAP 毛利率指引", "实际", "费用指引", "实际费用",
                    "隐含营业利润", "实际营业利润", "收入腿 D", "毛利率腿 D", "费用腿 D"],
        "rows": [],
    }
    leg_at = {label: index for index, label in enumerate(leg_labels)}
    for index, quarter in enumerate(quarters):
        actual_revenue = guide["actual_revenue_usd_m"][index]
        done = actual_revenue is not None
        label = compact_period(quarter)
        position = leg_at.get(label)
        implied = (revenue_guide[index] * margin_guide[index] / 100
                   - guide["non_gaap_opex_guide_usd_bn"][index])
        table["rows"].append([
            quarter,
            f"US${revenue_lo[index]:.2f}–{revenue_hi[index]:.2f}B",
            f"US${actual_revenue / 1000:.2f}B" if done else "—",
            f"{pct_change(actual_revenue / 1000, revenue_guide[index]):+.2f}% D" if done else "—",
            f"{margin_lo[index]:.1f}–{margin_hi[index]:.1f}%",
            f"{margin_actual[index]:.2f}% D" if done else "—",
            f"US${guide['non_gaap_opex_guide_usd_bn'][index]:.2f}B",
            f"US${guide['actual_non_gaap_opex_usd_m'][index] / 1000:.2f}B" if done else "—",
            f"US${implied:.2f}B D",
            (f"US${guide['actual_non_gaap_operating_income_usd_m'][index] / 1000:.2f}B"
             if done else "—"),
            f"{revenue_leg[position]:+.2f}B D" if position is not None else "—",
            f"{margin_leg[position]:+.2f}B D" if position is not None else "—",
            f"{opex_leg[position]:+.2f}B D" if position is not None else "—",
        ])
    return charts, table


def expectation_chart(staging: dict) -> dict:
    """Where the GAAP and non-GAAP readings of the same quarter part company.

    The other section-one charts ask whether the quarter cleared NVIDIA's own
    bar. This asks whether it cleared the market's -- and then keeps going,
    because the more interesting fact is *where* the two accounting bases
    diverge. They agree almost exactly at the operating line and split only
    below it, which localises the entire distortion to one item.

    Last quarter that item flattered GAAP; this quarter the same item runs the
    other way, and the sign flip is the point. Equity-securities gains fell from
    US$15.9B to US$7.8B, so GAAP net income grew 2% on a quarter whose operating
    income grew 19%. Strip the item out of both quarters and the GAAP series
    moves with the non-GAAP one again.
    """
    consensus = staging["market_expectation"]
    restated = staging["restated_comparatives"]
    current, prior = 0, 1

    rows = [
        ("营收 vs 市场预期",
         pct_change(staging["guidance"]["q2_actual"]["revenue_usd_m"],
                    consensus["revenue_usd_m"])),
        ("non-GAAP EPS vs 市场预期",
         pct_change(restated["non_gaap_eps_usd"][current], consensus["non_gaap_eps_usd"])),
        ("GAAP 营业利润 环比",
         pct_change(restated["gaap_operating_income_usd_m"][current],
                    restated["gaap_operating_income_usd_m"][prior])),
        ("non-GAAP 营业利润 环比",
         pct_change(restated["non_gaap_operating_income_usd_m"][current],
                    restated["non_gaap_operating_income_usd_m"][prior])),
        ("GAAP 净利 环比",
         pct_change(restated["gaap_net_income_usd_m"][current],
                    restated["gaap_net_income_usd_m"][prior])),
        ("non-GAAP 净利 环比",
         pct_change(restated["non_gaap_net_income_usd_m"][current],
                    restated["non_gaap_net_income_usd_m"][prior])),
        ("GAAP EPS 环比",
         pct_change(restated["gaap_eps_usd"][current], restated["gaap_eps_usd"][prior])),
        ("non-GAAP EPS 环比",
         pct_change(restated["non_gaap_eps_usd"][current], restated["non_gaap_eps_usd"][prior])),
    ]
    gains_now = restated["equity_securities_gains_usd_m"][current]
    gains_prior = restated["equity_securities_gains_usd_m"][prior]
    gains_step = gains_now - gains_prior
    low_tax, high_tax = staging["guidance"]["fy27_tax_rate_pct"]
    # Strip the item from both quarters at the company's own guided tax range,
    # so the two ends of the band are the two ends of that range rather than an
    # assumption of this page's own.
    def ex_gains(index: int, rate: float) -> float:
        return (restated["gaap_net_income_usd_m"][index]
                - restated["equity_securities_gains_usd_m"][index] * (1 - rate / 100))
    ex_low = pct_change(ex_gains(current, low_tax), ex_gains(prior, low_tax))
    ex_high = pct_change(ex_gains(current, high_tax), ex_gains(prior, high_tax))
    gaap_eps = pct_change(restated["gaap_eps_usd"][current], restated["gaap_eps_usd"][prior])
    core_eps = pct_change(restated["non_gaap_eps_usd"][current],
                          restated["non_gaap_eps_usd"][prior])
    gaap_net = pct_change(restated["gaap_net_income_usd_m"][current],
                          restated["gaap_net_income_usd_m"][prior])
    gaap_oi = pct_change(restated["gaap_operating_income_usd_m"][current],
                         restated["gaap_operating_income_usd_m"][prior])
    return {
        "ref": "EX_EXPECTATION",
        "kind": "diverging_bars",
        "title": (
            f"两套口径在营业利润上几乎一致，到净利才分叉：GAAP EPS 环比 {gaap_eps:+.1f}%，"
            f"non-GAAP {core_eps:+.1f}%"
        ),
        "xlabels": [label for label, _ in rows],
        "values": [round(value, 2) for _, value in rows],
        "legend": "较市场预期 / 环比",
        "positive_label": "高于对照",
        "negative_label": "低于对照",
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "%",
        "zero_line": True,
        "note": (
            "<b>这张图的重点是第三、四根柱几乎等高，而第五根开始劈叉 —— 而且这一季是往下劈。</b>"
            f"营业利润两套口径的环比一个 {gaap_oi:+.1f}%、一个 "
            f"{pct_change(restated['non_gaap_operating_income_usd_m'][current], restated['non_gaap_operating_income_usd_m'][prior]):+.1f}%，"
            "经营层面没有任何口径争议；分叉全部发生在营业利润<b>以下</b>，来源仍是股权投资收益，"
            "但方向与上季相反："
            f"本季 US${gains_now / 1000:.2f}B，上季 US${gains_prior / 1000:.2f}B，"
            f"环比<b>少</b> US${abs(gains_step) / 1000:.2f}B 税前。"
            f"于是 GAAP 净利环比只有 {gaap_net:+.1f}%，而营业利润 {gaap_oi:+.1f}%。"
            f"按公司自己指引的 FY27 税率 {low_tax:.0f}–{high_tax:.0f}% 把这一项从两季<b>同时</b>剔除，"
            f"GAAP 净利环比回到 {min(ex_low, ex_high):+.1f}–{max(ex_low, ex_high):+.1f}% D，"
            f"与 non-GAAP 的 {pct_change(restated['non_gaap_net_income_usd_m'][current], restated['non_gaap_net_income_usd_m'][prior]):+.1f}% 基本重合。"
            "<b>结论没变，只是这次它保护的是读者的下行判断而不是上行：</b>"
            "本季经营质量看 non-GAAP 营业利润与自由现金流，不看 GAAP 净利 —— "
            "上季这一项把 GAAP 抬高，本季把它压低，两次都不是经营。"
            "前两根柱是对市场预期，其余六根是环比，两类对照并列于同一轴上，"
            "只用于比较方向与相对幅度。"
        ),
        "src_extra": (
            f"实际值来自 Q2 2026 业绩 8-K；市场预期为财报前公开隐含一致预期"
            f"（{consensus['as_of']}），不具名。"
            "本组三季的 non-GAAP 数全部取自同一份 Q2 FY27 对账表，"
            "已是公司重述后的口径（含股权激励费用）。"
            "剔除股权收益后的环比为按公司指引税率区间的自算值，不是公司披露的拆分。"
        ),
    }


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    labels = [compact_period(period) for period in periods]
    financials = staging["financials"]
    platform = staging["market_platform_usd_m"]
    mix = staging["dc_customer_mix"]
    dropped = staging["discontinued_dc_split_usd_m"]
    cash = staging["cash_flow_usd_m"]
    working = staging["working_capital"]
    restated = staging["restated_comparatives"]
    supply = staging["total_supply_usd_bn"]
    exposure = staging["balance_sheet_exposure"]
    concentration = staging["customer_concentration"]
    conversion = staging["fcf_conversion"]
    capital = staging["capital_return_usd_m"]
    guidance = staging["guidance"]
    consensus = staging["market_expectation"]
    closure = staging["followup_closure"]
    next_kpi = staging["next_kpi"]
    long = staging["long_history"]
    # The ten-year record is unpacked here rather than beside the routine charts
    # because section two reads from it too: a revenue bar and a margin line are
    # the two things eight quarters cannot say anything about.
    long_labels = [compact_period(quarter) for quarter in long["quarters"]]
    LONG_STEP = 4
    long_revenue = long["revenue_usd_m"]
    # 2015 is not in this record, so the first four year-on-year cells have no
    # denominator. None, not zero -- a zero would draw a fabricated point at the
    # left edge of the growth line.
    long_revenue_yoy = [
        None if index < 4 else (long_revenue[index] / long_revenue[index - 4] - 1) * 100
        for index in range(len(long_revenue))
    ]

    # The IR landing page for quarterly results cannot be linked from this
    # payload: `payload_guard` rejects any string matching /inf[a-z]{0,2}/ as a
    # formatted infinity, and `financial-info` trips it. The per-release IR
    # permalink and the SEC archive copies say the same thing and pass.
    source = (
        'Source: <a href="https://investor.nvidia.com/news/press-release-details/2026/'
        'NVIDIA-Announces-Financial-Results-for-Second-Quarter-Fiscal-2027/default.aspx" '
        'rel="noopener">NVIDIA Investor Relations</a>'
        '（Q2 FY2027 earnings release、CFO commentary、业绩 8-K 与 10-Q）。'
    )

    revenue = financials["revenue_usd_m"]
    data_center = platform["data_center"]
    edge = platform["edge_computing"]
    # Reported free cash flow already nets out both capex and the principal
    # payments NVIDIA folds into its own definition, so the difference is
    # labelled for what it is rather than called "capex".
    capex_like = [ocf - fcf for ocf, fcf in zip(cash["operating_cash_flow"],
                                                cash["free_cash_flow"])]
    # Four quarters back is index -5 when -1 is the current quarter. Writing
    # -4 gives the quarter *three* back and still produces a plausible number,
    # which is exactly the kind of wrong that survives a read-through.
    YEAR_AGO = -5
    assert periods[YEAR_AGO].split()[0] == periods[-1].split()[0], periods
    fcf_intensity = [f / r * 100 for f, r in zip(cash["free_cash_flow"], revenue)]

    q3_guide = guidance["q3_new"]
    q3_midpoint = q3_guide["revenue_usd_bn"]
    q3_growth = pct_change(q3_midpoint * 1000, revenue[-1])

    total_supply = [
        inventory + commitments
        for inventory, commitments in zip(supply["inventory"],
                                          supply["supply_related_commitments"])
    ]

    # ── section one ──────────────────────────────────────────────────────────
    delivery_charts, delivery_table = guidance_delivery_charts(staging)
    guide_history = staging["quarterly_guidance_history"]
    current_index = guide_history["quarters"].index(periods[-1])
    guided_revenue = guide_history["guide_revenue_usd_bn"][current_index]
    guided_margin = guide_history["non_gaap_gm_guide_pct"][current_index]
    guided_opex = guide_history["non_gaap_opex_guide_usd_bn"][current_index]
    actual_margin = guide_history["actual_non_gaap_gm_pct"][current_index]
    actual_opex = guide_history["actual_non_gaap_opex_usd_m"][current_index] / 1000
    gaap_opex = financials["gaap_opex_usd_m"][-1] / 1000
    implied_oi = guided_revenue * guided_margin / 100 - guided_opex
    actual_oi = guide_history["actual_non_gaap_operating_income_usd_m"][current_index] / 1000

    delivery = [
        ("收入", pct_change(revenue[-1] / 1000, guided_revenue)),
        ("non-GAAP 毛利率", actual_margin - guided_margin),
        ("GAAP 毛利率", financials["gaap_gross_margin_pct"][-1]
         - guide_history["gaap_gm_guide_pct"][current_index]),
        # Spending less than promised is the safe side, so the sign is flipped
        # to keep "positive means better than guided" true across the whole bar.
        ("non-GAAP 营业费用", -pct_change(actual_opex, guided_opex)),
        ("隐含 non-GAAP 营业利润", pct_change(actual_oi, implied_oi)),
    ]

    closure_chart = {
        "kind": "bars_labeled",
        "title": (
            f"上季 {closure['total']} 条待验证问题："
            f"{closure['counts'][0]} 条已验证、{closure['counts'][1]} 条部分验证、"
            f"{closure['counts'][2]} 条被证伪、{closure['counts'][3]} 条未兑现"
        ),
        "xlabels": closure["labels"],
        "values": closure["counts"],
        "legend": "问题条数",
        "fmt": "f0",
        "yfmt": "f0",
        "label_fmt": "f0",
        "ylab": "条",
        "note": closure["note"] + (
            "<b>本季第一次出现「被证伪」这一格，而且它值得单独读</b>："
            "被证伪的不只是那条判断，是那条判断赖以成立的<b>序列本身</b> —— "
            "公司在本季把一家客户由 ACIE 重分类进 Hyperscale 并追溯重述历史，"
            "同一个季度在两套口径下给出方向相反的结论。"
            "加上停止披露的 Networking 拆分，上季的两条占比阈值本季一起退役，"
            "详见 Exhibit {EX_RECAST} 与第三节。"
        ),
        "src_extra": (
            "问题清单来自上季本地分析稿的 follow-up；"
            "验证结果依据 Q2 2026 业绩 8-K、CFO commentary、10-Q 与业绩电话会。"
        ),
    }

    delivery_chart = {
        "kind": "diverging_bars",
        "title": (
            f"本季全线优于自身指引：收入 {signed(delivery[0][1])}，"
            f"隐含营业利润 {signed(delivery[4][1])}"
        ),
        "xlabels": [metric for metric, _ in delivery],
        "values": [round(value, 2) for _, value in delivery],
        "legend": "优于指引的幅度",
        "positive_label": "优于指引",
        "negative_label": "逊于指引",
        "fmt": "f1",
        "yfmt": "f1",
        "label_fmt": "f1",
        "ylab": "% 或 pp",
        "zero_line": True,
        "note": (
            f"超额几乎全部来自收入：收入比指引中值高 {delivery[0][1]:.1f}%，"
            f"两条毛利率合计只比指引高 {delivery[1][1]:.2f}pp 与 {delivery[2][1]:.2f}pp，"
            "<b>本季依然没有毛利率上行惊喜</b>。"
            "费用一项已按「花得比承诺少为正」翻过符号，与其余各项方向统一；"
            f"本季实际 non-GAAP 费用 US${actual_opex:.2f}B，指引 US${guided_opex:.1f}B，"
            "是这条线上少见的<b>超支</b>季。"
            "收入与费用为百分比，两条毛利率为百分点，两类单位并列于同一轴上，"
            "只用于比较方向与相对幅度；原值见核对表。"
            "这五项的长窗口记录见 Exhibit {EX_REV_DEV} 起的指引兑现组图。"
        ),
        "src_extra": (
            f"指引为上季业绩 8-K Outlook 段所载 Q2 2026 口径"
            f"（收入 US${guided_revenue:.1f}B ±{guide_history['revenue_band_pct'][current_index]:.0f}%、"
            f"non-GAAP 毛利率 {guided_margin:.1f}% ±50bp、"
            f"non-GAAP 营业费用 US${guided_opex:.1f}B）；"
            "隐含营业利润为三者的自算组合，不是公司披露值。"
        ),
    }

    # ── section two ──────────────────────────────────────────────────────────
    revenue_chart = {
        "kind": "gs_bar",
        "title": (
            f"收入 US${revenue[-1] / 1000:.1f}B，同比 "
            f"{signed(financials['revenue_yoy_pct'][-1])} 连续四季重新加速"
        ),
        "xlabels": long_labels,
        "xstep": LONG_STEP,
        "values": [value / 1000 for value in long_revenue],
        "legend": "季度收入",
        "fmt": "usd1",
        "yfmt": "usd1",
        "label_fmt": "usd1",
        "ylab": "US$B",
        "ylab2": "同比增速",
        "yoy": {
            "name": "收入 YoY (RHS) D",
            "values": rounded(long_revenue_yoy),
            "color": "GREEN",
            "yfmt": "pct0",
        },
        "note": (
            f"环比 {signed(pct_change(revenue[-1], revenue[-2]))}，"
            f"环比<b>绝对</b>增量 US${(revenue[-1] - revenue[-2]) / 1000:.1f}B 再创纪录"
            f"（上季 US${(revenue[-2] - revenue[-3]) / 1000:.1f}B）；"
            f"同比增速从上季的 {financials['revenue_yoy_pct'][-2]:.0f}% 升到 "
            f"{financials['revenue_yoy_pct'][-1]:.0f}%，"
            "是连续第四季加速。"
            "<b>十年的窗口里这条同比线两次跌破零轴</b>："
            f"最低 {min(v for v in long_revenue_yoy if v is not None):.0f}%"
            f"（{long_labels[long_revenue_yoy.index(min(v for v in long_revenue_yoy if v is not None))]}，"
            "游戏渠道去库存），"
            f"最高 {max(v for v in long_revenue_yoy if v is not None):.0f}%"
            f"（{long_labels[long_revenue_yoy.index(max(v for v in long_revenue_yoy if v is not None))]}）。"
            "八季的窗口只看得到最近这一段单边上行；前四格没有同比线，2015 年不在本记录内。"
            f"Q3 指引中值 US${q3_midpoint:.1f}B，隐含环比 {signed(q3_growth)}，不减速。"
            f"较市场预期 US${consensus['revenue_usd_m'] / 1000:.1f}B 高 "
            f"{pct_change(revenue[-1], consensus['revenue_usd_m']):.1f}%。"
        ),
        "src_extra": (
            "42 季收入逐季读自各季业绩 8-K 的合并损益表三个月列（财年第四季取每年 2 月"
            "全年 8-K 里与全年列并排印出的 Q4 列），并与各财年 10-K 全年数逐年勾稽；"
            "同比为自算 D；市场预期为财报前公开隐含一致预期，不具名。"
        ),
    }

    platform_chart = {
        "kind": "grouped_bars",
        "title": (
            f"Data Center US${data_center[-1] / 1000:.1f}B 占收入 "
            f"{data_center[-1] / revenue[-1] * 100:.1f}%，Edge Computing 是唯一增速平庸的一块"
        ),
        "xlabels": labels,
        "groups": [
            {"name": "Data Center", "color": "NAVY",
             "values": [value / 1000 for value in data_center]},
            {"name": "Edge Computing", "color": "MBLUE",
             "values": [value / 1000 for value in edge]},
        ],
        "bar_labels": False,
        "fmt": "usd1",
        "label_fmt": "usd1",
        "ylab": "US$B",
        "note": (
            f"Data Center 环比 {signed(pct_change(data_center[-1], data_center[-2]))}、"
            f"同比 {signed(pct_change(data_center[-1], data_center[YEAR_AGO]))}；"
            f"Edge Computing 环比 {signed(pct_change(edge[-1], edge[-2]))}、"
            f"同比 {signed(pct_change(edge[-1], edge[YEAR_AGO]))}，"
            f"占收入已降到 {edge[-1] / revenue[-1] * 100:.1f}%。"
            "<b>本图刻意只画这两条</b>：Data Center 内部的客户类型拆分本季被公司重述过，"
            "而这两行在重述前后完全相同 —— 只看这张图察觉不到重分类发生过，"
            "这正是把它单独画一张的理由，见 Exhibit {EX_RECAST}。"
        ),
        "src_extra": (
            "市场平台口径为公司自 FY2027 Q1 启用的呈现方式（Data Center 与 Edge Computing）；"
            "逐季读自各季 8-K 的 CFO commentary，Edge Computing = 总收入 − Data Center，"
            "八季逐季核对相符 D。"
        ),
    }

    as_filed = mix["q1_2026_as_originally_filed"]
    filed_index = mix["quarters"].index("Q1 2026")
    recast_chart = {
        "ref": "EX_RECAST",
        "kind": "grouped_bars",
        "title": (
            "同一个 Q1 2026，两套口径给出相反的故事：Hyperscale 占 DC 由 "
            f"{as_filed['hyperscale'] / (as_filed['hyperscale'] + as_filed['acie']) * 100:.1f}% "
            f"被改写成 {mix['hyperscale'][filed_index] / (mix['hyperscale'][filed_index] + mix['acie'][filed_index]) * 100:.1f}%"
        ),
        "xlabels": ["Q1'26 原披露", "Q1'26 重述后", "Q2'26 本季"],
        "groups": [
            {"name": "Hyperscale", "color": "NAVY",
             "values": [as_filed["hyperscale"] / 1000,
                        mix["hyperscale"][filed_index] / 1000,
                        mix["hyperscale"][-1] / 1000]},
            {"name": "ACIE（AI 云 / 工业 / 企业）", "color": "GOLD",
             "values": [as_filed["acie"] / 1000,
                        mix["acie"][filed_index] / 1000,
                        mix["acie"][-1] / 1000]},
        ],
        "bar_labels": True,
        "fmt": "usd1",
        "label_fmt": "usd1",
        "ylab": "US$B",
        "note": (
            "公司在本季把一家客户由 ACIE 重分类进 Hyperscale，并<b>追溯重述</b>了历史。"
            f"迁移额 US${(mix['hyperscale'][filed_index] - as_filed['hyperscale']) / 1000:.3f}B。"
            "<b>两根柱子的高度合计完全相同</b>，Data Center 合计一分不差，"
            "所以任何只看 Data Center 的读数都察觉不到这件事。"
            "但它改写的是结论本身：按原口径，本季 ACIE 环比 "
            f"{pct_change(mix['acie'][-1], as_filed['acie']):+.1f}%、Hyperscale "
            f"{pct_change(mix['hyperscale'][-1], as_filed['hyperscale']):+.1f}%；"
            "按重述后口径，两者变成 "
            f"{pct_change(mix['acie'][-1], mix['acie'][filed_index]):+.1f}% 与 "
            f"{pct_change(mix['hyperscale'][-1], mix['hyperscale'][filed_index]):+.1f}% —— "
            "「客户结构正在分散」与「重新集中」是同一组数字的两种读法。"
            "<b>上季本页把阈值设在 ACIE 占 DC 上，本季它随基数一起作废</b>，"
            "第三节的五条阈值因此全部改建在 10-Q 的原始项上。"
        ),
        "src_extra": (
            "重述后的三季值印在 Q2 FY2027 10-Q 的 MD&A（Revenue by Market Platform）；"
            "原披露值印在 Q1 FY2027 10-Q。Q3 2025 与 Q4 2025 在新口径下不存在于任何申报，"
            "也无法由两个已披露数相减得到，本页不做拼接。"
        ),
    }

    accounting_chart = {
        "kind": "grouped_bars",
        # Titles are injected unescaped and reused verbatim in the card's
        # aria-label, so they stay plain text; emphasis belongs in the note.
        "title": (
            "GAAP 净利环比几乎没动，而营业利润涨了近两成 —— 差额是股权投资收益少了 "
            f"US${(restated['equity_securities_gains_usd_m'][1] - restated['equity_securities_gains_usd_m'][0]) / 1000:.1f}B"
        ),
        "xlabels": restated["quarters"][::-1],
        "groups": [
            {"name": "GAAP 净利", "color": "NAVY",
             "values": [value / 1000 for value in restated["gaap_net_income_usd_m"][::-1]]},
            {"name": "non-GAAP 净利", "color": "MBLUE",
             "values": [value / 1000 for value in restated["non_gaap_net_income_usd_m"][::-1]]},
            {"name": "其中：股权投资收益（税前）", "color": "GOLD",
             "values": [value / 1000
                        for value in restated["equity_securities_gains_usd_m"][::-1]]},
        ],
        "bar_labels": True,
        "fmt": "usd1",
        "label_fmt": "usd1",
        "ylab": "US$B",
        "note": (
            "金色柱是税前股权投资收益。上季它把 GAAP 净利抬到 non-GAAP 之上，本季回落 "
            f"US${(restated['equity_securities_gains_usd_m'][1] - restated['equity_securities_gains_usd_m'][0]) / 1000:.1f}B，"
            f"于是 GAAP 净利环比只有 "
            f"{pct_change(restated['gaap_net_income_usd_m'][0], restated['gaap_net_income_usd_m'][1]):+.1f}%，"
            f"而 non-GAAP 净利 "
            f"{pct_change(restated['non_gaap_net_income_usd_m'][0], restated['non_gaap_net_income_usd_m'][1]):+.1f}%。"
            "<b>这一项把利润表与 AI 一级/二级市场的资产价格绑在了一起</b> —— "
            "上行期放大利润，回落期同样放大，两个方向都不是经营。"
            "百分比拆解见 Exhibit {EX_EXPECTATION}。"
        ),
        "src_extra": restated["note"],
    }

    # Whether "highest of the eight" is true is measured, not remembered: gross
    # margin is 74.98 this quarter against 75.00 two quarters ago, a gap that a
    # one-decimal read-through cannot see.
    long_gross = long["gaap_gross_margin_pct"]
    long_operating = long["gaap_operating_margin_pct"]
    gross_is_high = long_gross[-1] == max(long_gross)
    operating_is_high = long_operating[-1] == max(long_operating)
    margin_level_chart = {
        "ref": "EX_MARGIN_LEVEL",
        "kind": "lines",
        "title": (
            f"GAAP 毛利率 {financials['gaap_gross_margin_pct'][-1]:.1f}%、营业利润率 "
            f"{financials['gaap_operating_margin_pct'][-1]:.1f}%，"
            + ("两条都是十年新高"
               if (gross_is_high and operating_is_high)
               else "营业利润率是十年新高，毛利率不是"
               if operating_is_high
               else "毛利率是十年新高，营业利润率不是"
               if gross_is_high
               else "两条都还没回到十年高点")
        ),
        "xlabels": long_labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": "GAAP 毛利率", "values": long["gaap_gross_margin_pct"], "color": "NAVY"},
            {"name": "GAAP 营业利润率", "values": long["gaap_operating_margin_pct"],
             "color": "MBLUE"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "利润率",
        "note": (
            f"最深的两个坑不是一回事：{long_labels[long_operating.index(min(long_operating))]} 的 "
            f"{min(long_operating):.0f}% 是 2022 年游戏渠道去库存的存货计提，"
            "Q1'25 的那个是 H20 出口管制的 US$4.5B 计提，两次都是一次性、非经营性；"
            f"此后五季毛利率逐季修复，营业利润率已抬到 {long_operating[-1]:.1f}%，"
            f"是这 {len(long_labels)} 季的最高。"
            f"<b>毛利率不是</b>：本季 {long_gross[-1]:.1f}%，"
            f"而十年高点是 {long_labels[long_gross.index(max(long_gross))]} 的 "
            f"{max(long_gross):.1f}% —— <b>八季的窗口看不到这件事</b>，"
            "因为那个高点就落在窗口的前一格。"
            "两条线之间的距离在收窄，差额就是营业杠杆（见下一节的费用强度）。"
            "<b>本图用 GAAP 口径画水平</b>，因为 GAAP 的定义在整段窗口内没变过。"
            "<b>但要读的是前瞻而不是水平</b>：公司本季主动把 Q3 毛利率指引下修到 "
            f"{q3_guide['non_gaap_gross_margin_pct']:.1f}%（本季实际 "
            f"{financials['non_gaap_gross_margin_pct'][-1]:.1f}%），"
            "理由是存储成本，且明说这是在提价已经生效之后的水平。"
            "逐季指引区间与兑现记录见 Exhibit {EX_GM_RANGE}。"
        ),
        "src_extra": "毛利率与营业利润率 = 各季 8-K 合并损益表的毛利 / 营业利益 ÷ 净收入 D。",
    }

    cash_quality_chart = {
        "ref": "EX_CASH_QUALITY",
        "kind": "bar_line_dual",
        "title": (
            f"自由现金流环比 {pct_change(cash['free_cash_flow'][-1], cash['free_cash_flow'][-2]):+.0f}%，"
            f"占收入由 {fcf_intensity[-2]:.0f}% 掉到 {fcf_intensity[-1]:.0f}%"
        ),
        "xlabels": labels,
        "bar": {
            "name": "自由现金流",
            "values": [value / 1000 for value in cash["free_cash_flow"]],
            "color": "NAVY",
        },
        "line": {
            "name": "自由现金流 / 收入 (RHS)",
            "values": rounded(fcf_intensity),
            "color": "GOLD",
            "yfmt": "pct0",
            "ymax": 100,
        },
        "fmt": "usd1",
        "yfmt": "usd1",
        "label_fmt": "usd1",
        "ylab": "US$B",
        "ylab2": "占收入比",
        "note": (
            "<b>这是本季真正变坏的一项，而且它不在利润表上。</b>"
            f"经营现金流 US${cash['operating_cash_flow'][-1] / 1000:.1f}B（环比 "
            f"{pct_change(cash['operating_cash_flow'][-1], cash['operating_cash_flow'][-2]):+.0f}%）、"
            f"自由现金流 US${cash['free_cash_flow'][-1] / 1000:.1f}B，"
            f"而同期收入还在环比 {pct_change(revenue[-1], revenue[-2]):+.0f}%。"
            f"应收账款一项本季就占用了 US${(working['accounts_receivable_usd_m'][-1] - working['accounts_receivable_usd_m'][-2]) / 1000:.1f}B，"
            f"DSO 由 {working['dso_days'][-2]:.1f} 天升到 {working['dso_days'][-1]:.1f} 天 —— "
            "公司自己的解释是给若干投资级客户的大额、跨多季出货延长了账期。"
            f"同一季仍然回购加分红 US${capital['total'][-1] / 1000:.1f}B，"
            f"相当于当季自由现金流的 {capital['total'][-1] / cash['free_cash_flow'][-1] * 100:.0f}%，"
            f"并在 6 月发行 US${exposure['senior_notes_issued_june_2026_usd_m'] / 1000:.0f}B 优先无担保票据"
            f"（{exposure['senior_notes_tranches']} 只券）。"
            "<b>右轴的占比线才是本页要跟踪的那条</b>，阈值见第三节。"
        ),
        "src_extra": (
            "经营现金流与自由现金流为公司披露值（FCF 按公司定义已扣除资本支出与租赁本金）；"
            "应收账款与回购分红取自 10-Q 的资产负债表与现金流量表；占比为自算 D。"
        ),
    }

    exposure_chart = {
        "kind": "grouped_bars",
        "title": (
            f"供应与产能承诺单季由 US${exposure['supply_and_capacity_commitments_usd_bn']['prior_quarter']:.0f}B "
            f"升到 US${exposure['supply_and_capacity_commitments_usd_bn']['current']:.0f}B，"
            f"另有 US${exposure['guarantee_max_exposure_usd_bn']['total']:.1f}B 表外担保"
        ),
        "xlabels": ["供应与产能承诺", "承诺总额", "担保最大总敞口", "长期债务", "非上市 + 上市股权证券"],
        "groups": [
            {"name": "Q2 2026", "color": "NAVY", "values": [
                exposure["supply_and_capacity_commitments_usd_bn"]["current"],
                exposure["total_future_commitments_usd_bn"],
                exposure["guarantee_max_exposure_usd_bn"]["total"],
                exposure["long_term_debt_usd_m"] / 1000
                if isinstance(exposure["long_term_debt_usd_m"], (int, float))
                else exposure["long_term_debt_usd_m"]["current"] / 1000,
                (exposure["non_marketable_securities_usd_m"]
                 + exposure["marketable_equity_securities_usd_m"]) / 1000,
            ]},
        ],
        "bar_labels": True,
        "fmt": "usd1",
        "label_fmt": "usd1",
        "ylab": "US$B",
        "note": (
            "<b>这五根柱不是同一种东西，放在一起是为了看量级。</b>"
            f"承诺总额 US${exposure['total_future_commitments_usd_bn']:.0f}B 相当于股东权益的 "
            f"{exposure['total_future_commitments_usd_bn'] * 1000 / exposure['shareholders_equity_usd_m'] * 100:.0f}%；"
            f"担保最大总敞口 US${exposure['guarantee_max_exposure_usd_bn']['total']:.1f}B 里有 "
            f"US${exposure['guarantee_max_exposure_usd_bn']['sb_energy']:.0f}B 是本季新增的单一一笔。"
            "<b>担保这一项要读清楚</b>：原有的 AI 云土地/电力/厂房担保是 "
            f"US${exposure['guarantee_max_exposure_usd_bn']['land_power_shell_ai_clouds_current'] :.3f}B 对 "
            f"US${exposure['guarantee_max_exposure_usd_bn']['land_power_shell_ai_clouds_prior_fy_end']:.3f}B，"
            "基本持平；新增的那笔签在资产负债表日之后，公司把它并进了标题注明含期后事项的表里。"
            "上一季 10-Q 没有任何担保上限披露，所以<b>本项没有可比的上季基数，也不存在「单季暴增 N 倍」这个说法</b>。"
        ),
        "src_extra": exposure["note"],
    }

    # ── section three ────────────────────────────────────────────────────────
    tracked = {
        "DSO": (labels, working["dso_days"], "f1", "天", "DSO"),
        "FCF / non-GAAP 净利转化率": (
            [compact_period(q) for q in conversion["quarters"]],
            conversion["values_pct"], "pct0", "转化率", "FCF / non-GAAP 净利"),
        "non-GAAP 毛利率": (
            labels, financials["non_gaap_gross_margin_pct"], "pct1", "毛利率", "non-GAAP 毛利率"),
        "单一最大直接客户占比": (
            [compact_period(q) for q in concentration["quarters"]],
            [float(v) for v in concentration["largest_direct_customer_pct"]],
            "pct0", "占总收入", "最大单一直接客户"),
    }
    extra_note = {
        "FCF / non-GAAP 净利转化率": conversion["note"],
        "单一最大直接客户占比": concentration["note"],
        "non-GAAP 毛利率": financials["non_gaap_basis_note"],
        "DSO": working["dso_note"],
    }

    def tracking_charts(entries: list[dict]) -> list[dict]:
        charts = []
        table_only = set(next_kpi["table_only"])
        for entry in entries:
            metric = entry["metric"]
            if metric in table_only:
                continue
            # A KPI with no series is a page defect, not something to skip
            # quietly: the old version dropped it from the section and left no
            # trace anywhere that it had done so.
            if metric not in tracked:
                raise KeyError(
                    f"KPI {metric!r} has no series in `tracked` and is not declared "
                    "table-only; add the series or add it to next_kpi.table_only"
                )
            xlabels, values, fmt, ylab, actual_name = tracked[metric]
            side = "上方" if entry["direction"] == "up" else "下方"
            charts.append(threshold_exhibit(
                (f"{metric}：下季阈值 {unit_text(entry['unit'], entry['threshold'])}，"
                 f"当前 {unit_text(entry['unit'], entry['current'])}"),
                xlabels,
                values,
                entry["threshold"],
                fmt=fmt,
                ylab=ylab,
                actual_name=actual_name,
                threshold_name=f"下季阈值（安全侧在{side}）",
                note=(
                    f"阈值 {unit_text(entry['unit'], entry['threshold'])}，"
                    f"当前 {unit_text(entry['unit'], entry['current'])}，"
                    f"余量 {headroom(entry['direction'], entry['threshold'], entry['current']):+.1f}%。"
                    + extra_note.get(metric, "")
                ),
                src_extra=(
                    "实际值来自各季业绩 8-K、CFO commentary 与 10-Q；"
                    "阈值为本地研究设定，不是公司指引。"
                ),
            ))
        return charts

    kpi_entries = next_kpi["quantified"]
    breached = [entry for entry in kpi_entries
                if headroom(entry["direction"], entry["threshold"], entry["current"]) < 0]
    headroom_chart = headroom_exhibit(
        (f"下季 {len(kpi_entries)} 条量化阈值："
         + (f"{len(breached)} 条已经越线" if breached else "全部仍在安全侧")),
        kpi_entries,
        "current",
        (
            "正值 = 仍在安全侧。"
            + (
                "<b>越线的那条是现金转化</b>：本季 FCF 只有 non-GAAP 净利的 "
                f"{conversion['values_pct'][-1]:.0f}%，"
                "而本页把「连续两季低于 50%」定为需要重新评估商业模式的门槛 —— "
                "所以它现在是一条计时器，不是一次读数。"
                if breached else ""
            )
            + f"DSO {working['dso_days'][-1]:.1f} 天离 "
            f"{next_kpi['quantified'][0]['threshold']:.0f} 天的行动线还有余量，但已经比上季多了 "
            f"{working['dso_days'][-1] - working['dso_days'][-2]:.1f} 天，是这八季最大的单季跳升。"
            "<b>本季五条阈值全部换了地基</b>：" + next_kpi["retired"]
        ),
        src_extra=(
            "阈值为本地研究设定，不是公司指引；当前值为 Q2 2026 实际。"
            + next_kpi["excluded"]
        ),
    )

    # ── section four ─────────────────────────────────────────────────────────
    # The 2022 de-stocking episode, measured rather than remembered: the lowest
    # operating margin in the record, and the highest reading before it.
    operating_margins = long["gaap_operating_margin_pct"]
    crash_trough = min(operating_margins)
    crash_at = operating_margins.index(crash_trough)
    pre_crash_peak = max(operating_margins[:crash_at])
    long_margin_chart = {
        "kind": "lines",
        "title": (
            f"{long_labels[0]} 起 {len(long_labels)} 季的毛利率与营业利润率：两次砸穿都是计提，"
            f"营业利润率从 {operating_margins[0]:.0f}% 抬到 {operating_margins[-1]:.0f}%"
        ),
        "xlabels": long_labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": "GAAP 毛利率", "values": long["gaap_gross_margin_pct"], "color": "NAVY"},
            {"name": "GAAP 营业利润率", "values": operating_margins, "color": "MBLUE"},
        ],
        "fmt": "pct0",
        "yfmt": "pct0",
        "label_fmt": "pct0",
        "end_label": True,
        "ylab": "占净收入比",
        "note": (
            "两条线的形状说明这家公司的利润率不是缓慢磨损型："
            f"2022 年那一轮游戏渠道去库存把营业利润率从 {pre_crash_peak:.0f}% 打到 "
            f"{crash_trough:.0f}%，2025 年 H20 计提又打掉一次，"
            "但两次都在两到三个季度内完全修复。"
            "<b>结构性的部分是营业利润率与毛利率之间的距离在收窄</b> —— "
            f"费用强度从 {long['opex_intensity_pct'][0]:.0f}% 降到 "
            f"{long['opex_intensity_pct'][-1]:.0f}%（见下一张），"
            "所以同样的毛利率今天能落下更多营业利润。"
            + long["provenance"]
        ),
        "src_extra": (
            f"{len(long_labels)} 季逐季读自各季业绩 8-K 的合并损益表三个月列"
            "（财年第四季取每年 2 月全年 8-K 里与全年列并排印出的 Q4 列），"
            "并与各财年 10-K 全年数逐年勾稽；"
            "毛利率 = 毛利 ÷ 净收入，营业利润率 = 营业利益 ÷ 净收入，均为自算 D。"
        ),
    }

    opex_intensity_chart = {
        "kind": "gs_line",
        "title": (
            f"费用强度 {len(long_labels)} 季从 {long['opex_intensity_pct'][0]:.1f}% 降到 "
            f"{long['opex_intensity_pct'][-1]:.1f}%，是营业杠杆的全部来源"
        ),
        "xlabels": long_labels,
        "xstep": LONG_STEP,
        "values": long["opex_intensity_pct"],
        "legend": "营业费用 / 净收入（GAAP）",
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "占净收入比",
        "note": (
            f"峰值 {max(long['opex_intensity_pct']):.1f}%（"
            f"{long_labels[long['opex_intensity_pct'].index(max(long['opex_intensity_pct']))]}，"
            "含 Arm 交易终止的一次性费用），最低 "
            f"{min(long['opex_intensity_pct']):.1f}%（本季）。"
            "<b>这条线本季继续下行</b>，但公司把 FY2027 全年费用增速指引从 high-30s 上调到 low-50s，"
            "所以分子的斜率正在变陡，只是分母更陡；一旦收入增速回落，这条线会先反应。"
            "分子分母同为 GAAP 口径，不与 non-GAAP 费用混用。"
        ),
        "src_extra": "营业费用与净收入逐季读自各季业绩 8-K 合并损益表；比值为自算 D。",
    }

    cash_chart = {
        "kind": "grouped_bars",
        "title": (
            f"经营现金流 US${cash['operating_cash_flow'][-1] / 1000:.1f}B，"
            f"资本支出及租赁本金 US${capex_like[-1] / 1000:.1f}B"
        ),
        "xlabels": labels,
        "groups": [
            {"name": "经营现金流", "color": "BLUE", "values":
             [value / 1000 for value in cash["operating_cash_flow"]]},
            {"name": "自由现金流", "color": "NAVY", "values":
             [value / 1000 for value in cash["free_cash_flow"]]},
            {"name": "资本支出及租赁本金 D", "color": "MBLUE",
             "values": [value / 1000 for value in capex_like]},
        ],
        "bar_labels": False,
        "fmt": "usd1",
        "label_fmt": "usd1",
        "ylab": "US$B",
        "note": (
            "<b>这张图的第三组柱一直很矮，而那正是要点</b>：这家公司的资本强度不在自己的资产负债表上 —— "
            f"本季资本支出及租赁本金合计只有 US${capex_like[-1] / 1000:.1f}B，"
            f"占收入 {capex_like[-1] / revenue[-1] * 100:.1f}%，"
            "而同期表外的供应与产能承诺是它的几十倍，见下一张。"
            f"前两组柱本季同时掉头（经营现金流 "
            f"{pct_change(cash['operating_cash_flow'][-1], cash['operating_cash_flow'][-2]):+.0f}%），"
            "原因在营运资金不在盈利，拆解见 Exhibit {EX_CASH_QUALITY}。"
        ),
        "src_extra": (
            "经营现金流与自由现金流为公司披露值（FCF 按公司定义已扣除资本支出与租赁本金）；"
            "第三组为两者之差 D，因此同时含资本支出与租赁本金，不等同狭义 capex。"
        ),
    }

    supply_chart = {
        "kind": "grouped_bars",
        "title": (
            f"存货 + 供应承诺合计 US${total_supply[-1]:.1f}B，"
            f"环比 {signed(pct_change(total_supply[-1], total_supply[-2]))}"
        ),
        "xlabels": supply["quarters"],
        "groups": [
            {"name": "存货", "color": "NAVY", "values": supply["inventory"]},
            {"name": "供应与产能承诺（表外）", "color": "GOLD",
             "values": supply["supply_related_commitments"]},
        ],
        "bar_labels": True,
        "fmt": "usd1",
        "label_fmt": "usd1",
        "ylab": "US$B",
        "note": (
            "这是这家公司真正的资本强度所在：表内存货只有 "
            f"US${supply['inventory'][-1]:.1f}B，表外供应与产能承诺却有 "
            f"US${supply['supply_related_commitments'][-1]:.1f}B，"
            f"本季单季增加 US${supply['supply_related_commitments'][-1] - supply['supply_related_commitments'][-2]:.0f}B。"
            "锁仓既是需求可见度，也是押注错误时的放大器 —— "
            "Q1'25 的 H20 计提就是同一台放大器反向运转的结果，"
            "在 Exhibit {EX_GM_RANGE} 上是那根 -10.0pp 的深坑。"
            "<b>本图只有三季</b>：更早的季度未以同一口径披露，本页不做回溯拼接。"
            + supply["note"]
        ),
        "src_extra": (
            "存货为各季资产负债表原值；供应与产能承诺为公司在 10-Q 与业绩电话会披露的口径；"
            "合计为自算 D。"
        ),
    }

    # ── assemble ─────────────────────────────────────────────────────────────
    settled_charts = (
        [closure_chart, delivery_chart, expectation_chart(staging)] + delivery_charts
    )
    highlights = [revenue_chart, platform_chart, recast_chart,
                  accounting_chart, margin_level_chart, cash_quality_chart, exposure_chart]
    next_charts = [headroom_chart] + tracking_charts(kpi_entries)
    routine = [long_margin_chart, opex_intensity_chart, cash_chart, supply_chart]

    exhibits = resolve_exhibit_refs(
        number_exhibits(settled_charts + highlights + next_charts + routine)
    )
    grouped = []
    cursor = 0
    for group in (settled_charts, highlights, next_charts, routine):
        grouped.append(exhibits[cursor:cursor + len(group)])
        cursor += len(group)
    settled_ex, highlight_ex, next_ex, routine_ex = grouped
    next_table_number = len(exhibits) + 2

    financial_table = []
    platform_table = []
    cash_table = []
    for index, period in enumerate(periods):
        non_gaap_ni = financials["non_gaap_net_income_usd_m"][index]
        financial_table.append([
            period,
            f"US${revenue[index] / 1000:.2f}B",
            f"{financials['revenue_yoy_pct'][index]:.1f}%",
            f"{financials['gaap_gross_margin_pct'][index]:.2f}% D",
            f"{financials['non_gaap_gross_margin_pct'][index]:.2f}% D",
            f"{financials['gaap_operating_margin_pct'][index]:.2f}% D",
            f"US${financials['gaap_operating_income_usd_m'][index] / 1000:.2f}B",
            f"US${financials['non_gaap_operating_income_usd_m'][index] / 1000:.2f}B",
            (f"US${non_gaap_ni / 1000:.2f}B" if non_gaap_ni is not None else "—"),
        ])
        largest = None
        if period in concentration["quarters"]:
            largest = concentration["largest_direct_customer_pct"][
                concentration["quarters"].index(period)]
        platform_table.append([
            period,
            f"US${data_center[index] / 1000:.2f}B",
            f"{data_center[index] / revenue[index] * 100:.1f}% D",
            f"US${edge[index] / 1000:.2f}B D",
            (f"{largest:.0f}%" if largest is not None else "—"),
        ])
        cash_table.append([
            period,
            f"US${cash['operating_cash_flow'][index] / 1000:.2f}B",
            f"US${cash['free_cash_flow'][index] / 1000:.2f}B",
            f"US${capex_like[index] / 1000:.2f}B D",
            f"{fcf_intensity[index]:.1f}% D",
            f"{working['dso_days'][index]:.1f}天 D",
            f"US${working['accounts_receivable_usd_m'][index] / 1000:.2f}B",
            f"US${working['inventories_usd_m'][index] / 1000:.2f}B",
        ])

    mix_table = []
    for index, quarter in enumerate(mix["quarters"]):
        total_dc = mix["hyperscale"][index] + mix["acie"][index]
        mix_table.append([
            quarter,
            f"US${mix['hyperscale'][index] / 1000:.2f}B",
            f"US${mix['acie'][index] / 1000:.2f}B",
            f"{mix['hyperscale'][index] / total_dc * 100:.1f}% D",
            f"US${total_dc / 1000:.2f}B",
            "重述后",
        ])
    mix_table.insert(len(mix_table) - 1, [
        "Q1 2026（原披露）",
        f"US${as_filed['hyperscale'] / 1000:.2f}B",
        f"US${as_filed['acie'] / 1000:.2f}B",
        f"{as_filed['hyperscale'] / (as_filed['hyperscale'] + as_filed['acie']) * 100:.1f}% D",
        f"US${(as_filed['hyperscale'] + as_filed['acie']) / 1000:.2f}B",
        "Q1 FY2027 10-Q 原口径",
    ])

    dropped_table = [
        [quarter,
         f"US${compute / 1000:.1f}B",
         f"US${networking / 1000:.1f}B",
         f"{networking / (compute + networking) * 100:.1f}% D"]
        for quarter, compute, networking in zip(
            dropped["quarters"], dropped["compute"], dropped["networking"])
    ]

    guide_rows = [
        ["收入", f"US${guided_revenue:.1f}B ±2%", f"US${revenue[-1] / 1000:.2f}B",
         f"高于中值 {pct_change(revenue[-1] / 1000, guided_revenue):.1f}% D",
         f"US${q3_midpoint:.1f}B ±{q3_guide['revenue_band_pct']:.0f}%",
         f"中值环比 {signed(q3_growth)} D"],
        ["GAAP 毛利率", f"{guide_history['gaap_gm_guide_pct'][current_index]:.1f}% ±50bp",
         f"{financials['gaap_gross_margin_pct'][-1]:.2f}% D", "区间内",
         f"{q3_guide['gaap_gross_margin_pct']:.1f}% ±50bp",
         f"下修 {q3_guide['gaap_gross_margin_pct'] - guide_history['gaap_gm_guide_pct'][current_index]:+.1f}pp"],
        ["non-GAAP 毛利率", f"{guided_margin:.1f}% ±50bp", f"{actual_margin:.2f}% D", "区间内",
         f"{q3_guide['non_gaap_gross_margin_pct']:.1f}% ±50bp",
         f"下修 {q3_guide['non_gaap_gross_margin_pct'] - guided_margin:+.1f}pp，公司归因于存储成本"],
        ["GAAP 营业费用",
         f"US${guide_history['gaap_opex_guide_usd_bn'][current_index]:.1f}B",
         f"US${gaap_opex:.2f}B",
         f"低于指引 {abs(pct_change(gaap_opex, guide_history['gaap_opex_guide_usd_bn'][current_index])):.1f}% D",
         f"US${q3_guide['gaap_opex_usd_bn']:.1f}B",
         f"中值环比 {signed(pct_change(q3_guide['gaap_opex_usd_bn'], gaap_opex))} D"],
        ["non-GAAP 营业费用", f"US${guided_opex:.1f}B", f"US${actual_opex:.2f}B",
         f"高于指引 {abs(pct_change(actual_opex, guided_opex)):.1f}% D",
         f"US${q3_guide['non_gaap_opex_usd_bn']:.1f}B",
         f"中值环比 {signed(pct_change(q3_guide['non_gaap_opex_usd_bn'], actual_opex))} D"],
        ["FY 税率",
         f"{guidance['fy27_prior_tax_rate_pct'][0]:.0f}–"
         f"{guidance['fy27_prior_tax_rate_pct'][1]:.0f}%", "—", "—",
         f"{guidance['fy27_tax_rate_pct'][0]:.0f}–{guidance['fy27_tax_rate_pct'][1]:.0f}%",
         guidance["tax_rate_change"]],
        ["中国 Data Center compute", "假设为 0", "低于 Data Center 收入的 1%", "基本符合",
         "仍假设为 0", "公司称现有 Hopper 出货摊薄毛利率"],
    ]

    tables = [
        {
            "n": next_table_number,
            "title": "Q2 2026 兑现与 Q3 2026 指引",
            "headers": ["指标", "Q2 原指引", "Q2 实际", "兑现", "Q3 新指引", "变化 / 备注"],
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
            "title": "八季度收入与利润率",
            "headers": ["期间", "收入", "收入 YoY", "GAAP 毛利率", "non-GAAP 毛利率",
                        "GAAP 营业利润率", "GAAP 营业利润", "non-GAAP 营业利润",
                        "non-GAAP 净利"],
            "rows": financial_table,
        },
        {
            "n": next_table_number + 3,
            "title": "八季度市场平台与客户集中度",
            "headers": ["期间", "Data Center", "占收入", "Edge Computing",
                        "最大单一直接客户占总收入"],
            "rows": platform_table,
        },
        {
            "n": next_table_number + 4,
            "title": "Data Center 客户类型拆分：重述前后",
            "headers": ["期间", "Hyperscale", "ACIE", "Hyperscale 占 DC", "Data Center 合计", "口径"],
            "rows": mix_table,
        },
        {
            "n": next_table_number + 5,
            "title": "已停止披露：Data Center 的 compute / networking 拆分",
            "headers": ["期间", "DC Compute", "DC Networking", "Networking 占 DC"],
            "rows": dropped_table,
        },
        {
            "n": next_table_number + 6,
            "title": "八季度现金流与营运资金",
            "headers": ["期间", "经营现金流", "自由现金流", "资本支出及租赁本金",
                        "FCF / 收入", "DSO", "应收账款", "存货"],
            "rows": cash_table,
        },
        {**delivery_table, "n": next_table_number + 7},
        ai_capex_cycle_table(next_table_number + 8),
    ]

    return {
        "schema_version": "quarterly-dashboard/nvda-v1",
        "page": {"slug": "nvda", "language": "zh-CN"},
        "company": {
            "ticker": "NVDA",
            "name": "NVIDIA",
            "group": "semiconductor_ai",
            "accounting_standard": "US GAAP",
        },
        "latest": {
            "disclosed_period_label": "Q2 2026",
            "full_financial_period_label": "Q2 2026",
            "period_end": "2026-07-26",
            "release_date": "2026-08-26",
            "analysis_date": "2026-08-30",
            "audit_status": "unaudited",
            "status": "history_ready",
        },
        "tracker": "Watchlist Quarterly Tracker · NVDA",
        "title": "NVIDIA (NVDA)：Q2 2026 季报仪表盘",
        "subtitle": (
            "截至 2026-07-26 · 发布 2026-08-26 · US GAAP · 未审计 · "
            "1 月制财年，本站按自然年季度标注：本页 Q2 2026 即公司所称 FY2027 Q2"
        ),
        "headline": (
            f"收入 US${revenue[-1] / 1000:.1f}B、同比 {signed(financials['revenue_yoy_pct'][-1])}，"
            f"环比绝对增量 US${(revenue[-1] - revenue[-2]) / 1000:.1f}B 再创纪录；"
            "但本页的对象不是这个季度的利润表 —— "
            f"自由现金流环比 {pct_change(cash['free_cash_flow'][-1], cash['free_cash_flow'][-2]):+.0f}%、"
            f"DSO 由 {working['dso_days'][-2]:.1f} 天跳到 {working['dso_days'][-1]:.1f} 天、"
            f"表外供应与产能承诺由 US${exposure['supply_and_capacity_commitments_usd_bn']['prior_quarter']:.0f}B "
            f"升到 US${exposure['supply_and_capacity_commitments_usd_bn']['current']:.0f}B，"
            f"另有 US${exposure['guarantee_max_exposure_usd_bn']['total']:.1f}B 表外担保。"
            "同一季公司还把上季这张页面用来判断客户结构的那条序列重分类并追溯重述了。"
        ),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>亮点</span><b>二阶导连续第四季加速</b>'
            f'<p>同比 {financials["revenue_yoy_pct"][-1]:.0f}%，环比增量 '
            f'US${(revenue[-1] - revenue[-2]) / 1000:.1f}B 创纪录；'
            f'Q3 指引中值 US${q3_midpoint:.0f}B，隐含环比 {signed(q3_growth)}。</p></article>'
            '<article><span>存疑</span><b>现金转化腰斩</b>'
            f'<p>FCF 占收入由 {fcf_intensity[-2]:.0f}% 掉到 {fcf_intensity[-1]:.0f}%，'
            f'DSO {working["dso_days"][-1]:.1f} 天；'
            f'同季仍回报 US${capital["total"][-1] / 1000:.1f}B。</p></article>'
            '<article><span>口径</span><b>一条 KPI 被重述掉</b>'
            f'<p>Hyperscale 占 DC 的 Q1 2026 由 '
            f'{as_filed["hyperscale"] / (as_filed["hyperscale"] + as_filed["acie"]) * 100:.1f}% '
            f'改写为 {mix["hyperscale"][filed_index] / (mix["hyperscale"][filed_index] + mix["acie"][filed_index]) * 100:.1f}%；'
            '阈值已改建在 10-Q 原始项上。</p></article>'
            '</div>'
        ),
        "source": source,
        "source_url": (
            "https://investor.nvidia.com/news/press-release-details/2026/"
            "NVIDIA-Announces-Financial-Results-for-Second-Quarter-Fiscal-2027/default.aspx"
        ),
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {
                "id": "settled",
                "title": "一、上季跟踪指标兑现了吗",
                "description": (
                    "先看上季留的问题闭环了几条、这一季对公司自己的指引和对市场预期各兑现到什么程度，"
                    "再谈本季。公司每季给三个数——收入、两条毛利率、两条营业费用——"
                    "本节按指标逐个给出完整记录，最后把「超出自身指引」拆成收入、毛利率与费用三条腿。"
                ),
                "exhibits": settled_ex,
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": (
                    "收入的二阶导、市场平台构成、被重述掉的那条客户结构序列、"
                    "GAAP 与 non-GAAP 在净利处的分叉，以及本季真正变坏的现金转化与表外敞口。"
                ),
                "exhibits": highlight_ex,
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": (
                    "当前值离下季阈值还有多远，统一用「距阈值余量」口径。"
                    "本季五条阈值全部建在 10-Q 的原始项上 —— 应收、现金流、承诺与担保、客户集中度 —— "
                    "而不是建在公司可以重新划分的呈现层上。"
                ),
                "exhibits": next_ex,
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": (
                    f"NVDA 专属的常规序列：{long_labels[0]} 起 {len(long_labels)} 季的利润率与费用强度、"
                    "现金转化，以及真正承载资本强度的存货与供应承诺。"
                ),
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "本页所有季度按自然年标注。NVIDIA 财年 1 月底结束，故本页的 Q2 2026 是截至 2026-07-26 的季度，公司自己称之为 FY2027 Q2；不统一成一种约定，跨公司的资本开支对照表就会把不同的三个月放在一起比较。",
            f"Exhibit {next_ex[0]['n']} 与其后各图的阈值是本地研究设定，不是公司指引，也不构成评级或投资建议；「距阈值余量」统一为正值代表安全侧。",
            f"第一节的指引兑现组图（Exhibit {settled_ex[3]['n']}–{settled_ex[-1]['n']}）用的是同一批业绩 8-K：每份新闻稿的 Outlook 段同时给出下一季的收入区间（±2%）、GAAP 与 non-GAAP 毛利率区间（±50bp）以及两条营业费用的单点指引，实际值取自随后一季 8-K 的合并损益表与 GAAP/non-GAAP 对账表。",
            f"Exhibit {settled_ex[5]['n']} 的三条腿是恒等式而非估计：公司同时指引收入、毛利率与费用，三者隐含一个它从不印出来的营业利润，实际值与它的差恰好等于三条腿之和。收入与毛利率同时偏离时的交叉项按该式全部计入毛利率腿，调换拆解顺序会把它移到收入腿，两种拆法的合计相同。",
            "自 Q1 2026 起公司的 non-GAAP 口径不再剔除股权激励费用。本页八季的 non-GAAP 毛利率、营业费用与营业利润一律为重述后口径：其中 Q1 2025–Q2 2026 六季为公司印出值，Q3 2024 与 Q4 2024 两季公司从未按新口径印出，本页按同一机械规则自算（原口径值加减当季印在对账表上的股权激励费用），该规则在公司印出的四个季度上逐百万精确复现。non-GAAP 净利与每股收益不适用该规则——非 GAAP 调整的所得税影响换了算法——故那两季留空，第三节的现金转化率图因此只有六季。",
            "指引兑现各图逐季比较的是当季指引与当季实际，两者始终处在同一口径下，不受 non-GAAP 口径变更影响；受影响的只有费用的绝对水平，图上已标出断点。",
            "长期序列一律用 GAAP 口径，因为 GAAP 的定义在整个窗口内没有变过；把两种 non-GAAP 口径接成一条线会在变更处砸出纯定义性的落差。",
            "Data Center 的 Hyperscale / ACIE 拆分本季被公司重分类并追溯重述（一家客户由 ACIE 改入 Hyperscale）。重述后的值只在本季 10-Q 的三列里印出，Q3 2025 与 Q4 2025 在新口径下不存在于任何申报，也无法由两个已披露数相减得到，因此本页不再画这条八季序列，改为一张重述前后对照图加一张核对表。",
            "公司自本季起不再披露 Data Center 内部的 compute / networking 拆分，业绩 8-K、CFO commentary 与 10-Q 三处都没有；该序列冻结在 Q1 2026，收在核对表里，不做外推。",
            "单一最大直接客户占总收入的比重逐季读自各季 10-Q 的 Concentration of Revenue 附注三个月列。两个财年第四季没有季度值：10-K 只印全年，而公司自己说明客户字母代号不跨期可比，全年减前九个月既没有确定的被减数，四舍五入也会把结果撑成约 5pp 宽的区间。本页留空，不推算。",
            "自由现金流为公司披露值，按公司定义已扣除资本支出与租赁本金；本页的「资本支出及租赁本金」是经营现金流与自由现金流之差，因此同时含两者，不等同狭义 capex。",
            "担保最大总敞口没有可比的上季基数：上一季 10-Q 没有任何担保上限披露。本季表内含期后事项，其中单一一笔占绝大部分，且原有的 AI 云土地/电力/厂房担保在两个资产负债表日之间基本持平。",
            "本页只发布公司披露值、可复算的简单派生值，以及明确标注的市场预期；D 标记代表 Derived / 自算。",
            "市场预期一律标注为「市场预期」并给出取数时点，不写卖方机构名，也不发布评级、目标价或估值。本季所用的一致预期来自二手转述而非终端原始值，因此「超出预期」的绝对幅度有 ±1% 量级的不确定性。",
            "本页已知未接入：公司在业绩电话会上给出的下一财年收入增速、Q4 与 FY2028 毛利率区间、全年费用增速措辞——这四条只出现在电话会，任何申报里都没有，故不进本页任何图；Vera Rubin 的出货金额（公司只给占比口径）；战略投资的逐笔规模与回报口径（公司未披露）。",
            "业绩电话会文字稿仅链接官方 IR 与 SEC 托管版本，公开仓不复制原件或逐字内容。",
        ],
        "footer": "NVDA quarterly results · 数据来自 NVIDIA 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "nvda.js"), payload, "nvda")
    shell_dir = ROOT / "nvda"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(
        render_shell("NVDA", "nvda"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(
        f"NVDA page: {charts} charts in {len(payload['sections'])} sections "
        f"+ {len(payload['tables'])} audit tables"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
