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
belong to different metrics: revenue cleared the top of its band in 20 of 23
quarters, while gross margin sat *inside* its band in 15 of 23 and broke the
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
            "而收入在这段时间从 US$4.4B 长到 US$91B，二十多倍的量级差放在一根线性美元轴上，"
            "早年的 ±2% 区间会被压成几个像素，图就不再回答自己的问题了。"
            "完整 23 季的同一问题改用与量级无关的口径回答，见 Exhibit {EX_REV_DEV}。"
        ),
    )
    revenue_dev_chart = midpoint_deviation(
        "EX_REV_DEV", "收入", quarters, revenue_lo, revenue_hi, revenue_actual,
        mode="pct", window=len(finished), label=compact_period, bar_labels=False,
        src_extra=SOURCE_8K + "偏离为实际收入除以指引中值的自算值。",
        extra_note=(
            "<b>这是全页最该先读的一张</b>：23 个已完结季里 20 季高于指引中值 2% 以上"
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
            "15 季落在 ±50bp 的窄区间内，只有 5 季穿出上限。"
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
            "<b>本页据此把下季 non-GAAP 毛利率的警戒线设在 74.5%</b> —— "
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
            "柱子长期贴近零轴，23 季的平均绝对偏离只有个位数百分比。"
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
    diverge. They agree exactly at the operating line and split only below it,
    which localises the entire distortion to one item.
    """
    consensus = staging["market_expectation"]
    restated = staging["restated_comparatives"]
    current, prior = 0, 1

    rows = [
        ("营收 vs 市场预期",
         pct_change(staging["guidance"]["q1_actual"]["revenue_usd_m"],
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
    gains_step = (restated["equity_securities_gains_usd_m"][current]
                  - restated["equity_securities_gains_usd_m"][prior])
    net_step = (restated["gaap_net_income_usd_m"][current]
                - restated["gaap_net_income_usd_m"][prior])
    low_tax, high_tax = staging["guidance"]["fy27_tax_rate_pct"]
    share_low = gains_step * (1 - high_tax / 100) / net_step * 100
    share_high = gains_step * (1 - low_tax / 100) / net_step * 100
    gaap_eps = pct_change(restated["gaap_eps_usd"][current], restated["gaap_eps_usd"][prior])
    core_eps = pct_change(restated["non_gaap_eps_usd"][current],
                          restated["non_gaap_eps_usd"][prior])
    return {
        "ref": "EX_EXPECTATION",
        "kind": "diverging_bars",
        "title": (
            f"两套口径在营业利润上完全一致，到净利才分叉：GAAP EPS 环比 {gaap_eps:+.1f}%，"
            f"non-GAAP 只有 {core_eps:+.1f}%"
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
            "<b>这张图的重点是第三、四根柱几乎等高，而第五根开始劈叉。</b>"
            "营业利润两套口径只差 US$0.25B（non-GAAP 仅剔除并购相关摊销等小项），"
            "环比增速一个 +20.9%、一个 +20.9%，说明经营层面没有任何口径争议；"
            "分叉全部发生在营业利润<b>以下</b>，来源是股权投资收益："
            f"本季 US${restated['equity_securities_gains_usd_m'][current] / 1000:.2f}B，"
            f"上季 US${restated['equity_securities_gains_usd_m'][prior] / 1000:.2f}B，"
            f"环比多出 US${gains_step / 1000:.2f}B 税前。"
            f"按公司自己指引的 FY27 税率 {low_tax:.0f}–{high_tax:.0f}% 粗算，"
            f"税后约 US${gains_step * (1 - high_tax / 100) / 1000:.1f}–"
            f"{gains_step * (1 - low_tax / 100) / 1000:.1f}B，"
            f"占 GAAP 净利环比增量的 {share_low:.0f}–{share_high:.0f}% D。"
            "<b>结论：本季经营质量看 non-GAAP 营业利润与自由现金流，不看 GAAP 净利。</b>"
            "前两根柱是对市场预期，其余六根是环比，两类对照并列于同一轴上，"
            "只用于比较方向与相对幅度。"
        ),
        "src_extra": (
            f"实际值来自 Q1 2026 业绩 8-K；市场预期为财报前公开隐含一致预期"
            f"（{consensus['as_of']}），不具名。"
            "本组三季的 non-GAAP 数全部取自同一份 Q1 FY27 对账表，"
            "已是公司重述后的口径（含股权激励费用），与各季当时原报口径不同。"
            "税后金额与占比为按公司指引税率区间的自算值，不是公司披露的拆分。"
        ),
    }


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    labels = [compact_period(period) for period in periods]
    financials = staging["financials"]
    platform = staging["market_platform_usd_m"]
    split = staging["data_center_split_usd_m"]
    cash = staging["cash_flow_usd_m"]
    working = staging["working_capital"]
    restated = staging["restated_comparatives"]
    supply = staging["total_supply_usd_bn"]
    guidance = staging["guidance"]
    consensus = staging["market_expectation"]
    closure = staging["followup_closure"]
    next_kpi = staging["next_kpi"]
    long = staging["long_history"]

    # The IR landing page for quarterly results cannot be linked from this
    # payload: `payload_guard` rejects any string matching /inf[a-z]{0,2}/ as a
    # formatted infinity, and `financial-info` trips it. The per-release IR
    # permalink and the SEC archive copies say the same thing and pass.
    source = (
        'Source: <a href="https://investor.nvidia.com/news/press-release-details/2026/'
        'NVIDIA-Announces-Financial-Results-for-First-Quarter-Fiscal-2027/default.aspx" '
        'rel="noopener">NVIDIA Investor Relations</a>'
        '（Q1 FY2027 earnings release、CFO commentary 与业绩 8-K）。'
    )

    revenue = financials["revenue_usd_m"]
    data_center = platform["data_center"]
    acie_share = [a / d * 100 for a, d in zip(platform["acie"], data_center)]
    hyperscale_share = [h / d * 100 for h, d in zip(platform["hyperscale"], data_center)]
    networking_share = [n / d * 100 for n, d in zip(split["networking"], data_center)]
    # Reported free cash flow already nets out both capex and the principal
    # payments NVIDIA folds into its own definition, so the difference is
    # labelled for what it is rather than called "capex".
    capex_like = [ocf - fcf for ocf, fcf in zip(cash["operating_cash_flow"],
                                                cash["free_cash_flow"])]
    fcf_conversion = [
        fcf / ni * 100
        for fcf, ni in zip(cash["free_cash_flow"], financials["non_gaap_net_income_usd_m"])
    ]

    q2_guide = guidance["q2_new"]
    q2_midpoint = q2_guide["revenue_usd_bn"]
    q2_growth = pct_change(q2_midpoint * 1000, revenue[-1])
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
            f"上季 10 条待验证问题：{closure['counts'][0]} 条已验证、"
            f"{closure['counts'][1]} 条部分验证、"
            f"{closure['counts'][2]} 条仍未披露、{closure['counts'][3]} 条未兑现"
        ),
        "xlabels": closure["labels"],
        "values": closure["counts"],
        "legend": "问题条数",
        "fmt": "f0",
        "yfmt": "f0",
        "label_fmt": "f0",
        "ylab": "条",
        "note": closure["note"] + (
            "<b>没有一条被明确证伪</b>，这与上季的判断方向一致；"
            "但「仍未披露」与「未兑现」各一条都落在质量侧而不是需求侧。"
        ),
        "src_extra": (
            "问题清单来自上季本地分析稿的 follow-up；"
            "验证结果依据 Q1 2026 业绩 8-K、CFO commentary 与业绩电话会。"
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
            "两条毛利率都只比指引高 0.03pp —— 公司指引什么就交付什么，"
            "本季<b>没有</b>毛利率上行惊喜；超额几乎全部来自收入。"
            "费用一项已按「花得比承诺少为正」翻过符号，与其余各项方向统一。"
            "收入与费用为百分比，两条毛利率为百分点，两类单位并列于同一轴上，"
            "只用于比较方向与相对幅度；原值见核对表。"
            "这五项的长窗口记录见 Exhibit {EX_REV_DEV} 起的指引兑现组图。"
        ),
        "src_extra": (
            f"指引为上季业绩 8-K Outlook 段所载 Q1 2026 口径"
            f"（收入 US${guided_revenue:.1f}B ±{q2_guide['revenue_band_pct']:.0f}%、"
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
            f"{signed(financials['revenue_yoy_pct'][-1])} 连续两季重新加速"
        ),
        "xlabels": labels,
        "values": [value / 1000 for value in revenue],
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
            "yfmt": "pct0",
        },
        "note": (
            f"环比 {signed(pct_change(revenue[-1], revenue[-2]))}，"
            f"环比<b>绝对</b>增量 US${(revenue[-1] - revenue[-2]) / 1000:.1f}B 创纪录；"
            f"同比增速从上季的 {financials['revenue_yoy_pct'][-2]:.0f}% 升到 "
            f"{financials['revenue_yoy_pct'][-1]:.0f}%，是这八季里第一次连续两季加速。"
            f"Q2 指引中值 US${q2_midpoint:.1f}B，隐含环比 {signed(q2_growth)}，不减速。"
            f"较市场预期 US${consensus['revenue_usd_m'] / 1000:.2f}B 高 "
            f"{pct_change(revenue[-1], consensus['revenue_usd_m']):.1f}%。"
        ),
        "src_extra": (
            "收入与同比来自各季业绩 8-K 合并损益表；同比为自算；"
            "市场预期为财报前公开隐含一致预期，不具名。"
        ),
    }

    platform_chart = {
        "kind": "grouped_bars",
        "title": (
            f"Data Center 内部两条腿几乎等大：Hyperscale US${platform['hyperscale'][-1] / 1000:.1f}B "
            f"vs ACIE US${platform['acie'][-1] / 1000:.1f}B"
        ),
        "xlabels": labels,
        "groups": [
            {"name": "Hyperscale", "color": "NAVY",
             "values": [value / 1000 for value in platform["hyperscale"]]},
            {"name": "ACIE（AI 云 / 工业 / 企业）", "color": "GOLD",
             "values": [value / 1000 for value in platform["acie"]]},
            {"name": "Edge Computing", "color": "MBLUE",
             "values": [value / 1000 for value in platform["edge_computing"]]},
        ],
        "bar_labels": False,
        "fmt": "usd1",
        "label_fmt": "usd1",
        "ylab": "US$B",
        "note": (
            f"本季 ACIE 环比 {signed(pct_change(platform['acie'][-1], platform['acie'][-2]))}，"
            f"是 Hyperscale {signed(pct_change(platform['hyperscale'][-1], platform['hyperscale'][-2]))} 的"
            f" {pct_change(platform['acie'][-1], platform['acie'][-2]) / pct_change(platform['hyperscale'][-1], platform['hyperscale'][-2]):.1f} 倍，"
            "把「只靠 5–7 家云厂」的集中度叙事第一次拉到接近对半。"
            "<b>但这条曲线不是单边的</b>：Q4'24 到 Q3'25 之间 Hyperscale 反而一路占到近六成，"
            "所以本季的回摆要再看一到两季才能算趋势。"
            "占比口径与阈值见 Exhibit {EX_MIX_RATIO}。"
        ),
        "src_extra": (
            "市场平台口径为公司 2026 年启用的新分部（Data Center 下分 Hyperscale 与 ACIE，"
            "另设 Edge Computing）。Q1 2026 / Q4 2025 / Q1 2025 三季直接取自 Q1 FY27 "
            "CFO commentary；其余五季为公司同一次重述值，逐季与该季 8-K 所载 Data Center "
            "合计数核对相符。Edge Computing = 总收入 − Data Center D。"
        ),
    }

    mix_ratio_chart = {
        "ref": "EX_MIX_RATIO",
        "kind": "lines",
        "title": (
            f"两条护城河比率同时逼近阈值：Networking 占 DC {networking_share[-1]:.1f}%、"
            f"ACIE 占 DC {acie_share[-1]:.1f}%"
        ),
        "xlabels": labels,
        "series": [
            {"name": "Networking 占 DC", "values": rounded(networking_share), "color": "NAVY"},
            {"name": "ACIE 占 DC", "values": rounded(acie_share), "color": "GOLD"},
            {"name": "Hyperscale 占 DC", "values": rounded(hyperscale_share), "color": "MBLUE"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "占 Data Center 比重",
        "note": (
            f"Networking 从 Q4'24 的低点 {min(networking_share):.1f}% 一路升到 "
            f"{networking_share[-1]:.1f}%，是这八季里方向最干净的一条 —— "
            "价值量正在从 GPU 扩到 rack 级 fabric，本页把 20% 设为护城河强化的确认线。"
            "ACIE 与 Hyperscale 互为补数，两条线交叉即代表客户结构对半。"
            "<b>三条线的分母都是 Data Center 净收入，可以直接比较；</b>"
            "但 Networking 与 ACIE 是<b>交叉分类</b>而非互斥拆分，两者不可相加。"
        ),
        "src_extra": (
            "Data Center compute / networking 拆分逐季读自各季 CFO commentary 与新闻稿原句"
            "（公司只给到 US$0.1B 精度）；占比为自算。"
        ),
    }

    accounting_chart = {
        "kind": "grouped_bars",
        # Titles are injected unescaped and reused verbatim in the card's
        # aria-label, so they stay plain text; emphasis belongs in the note.
        "title": (
            "一年之内，GAAP 净利从低于 non-GAAP 变成高出 "
            f"US${(restated['gaap_net_income_usd_m'][0] - restated['non_gaap_net_income_usd_m'][0]) / 1000:.1f}B，"
            "差额就是股权投资收益"
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
            "一年前 GAAP 净利还<b>低于</b> non-GAAP（股权投资是净损失），本季反过来高出 "
            f"US${(restated['gaap_net_income_usd_m'][0] - restated['non_gaap_net_income_usd_m'][0]) / 1000:.1f}B。"
            "金色柱是税前股权投资收益，它把利润表与 AI 一级/二级市场的资产价格绑在了一起 —— "
            "上行期放大利润，下行期会与经营预期同向压缩。"
            "百分比拆解见 Exhibit {EX_EXPECTATION}。"
        ),
        "src_extra": (
            "三季同取 Q1 FY27 对账表，均为重述后 non-GAAP 口径（含股权激励费用）；"
            "Q4 2025 的 non-GAAP EPS 因此是 $1.59 而不是当时原报的 $1.62。"
        ),
    }

    margin_level_chart = {
        "ref": "EX_MARGIN_LEVEL",
        "kind": "lines",
        "title": (
            f"GAAP 毛利率 {financials['gaap_gross_margin_pct'][-1]:.1f}%、营业利润率 "
            f"{financials['gaap_operating_margin_pct'][-1]:.1f}%，均已回到计提前水平"
        ),
        "xlabels": labels,
        "series": [
            {"name": "GAAP 毛利率", "values": financials["gaap_gross_margin_pct"],
             "color": "NAVY"},
            {"name": "GAAP 营业利润率", "values": financials["gaap_operating_margin_pct"],
             "color": "MBLUE"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "利润率",
        "note": (
            "Q1'25 的深坑是 H20 出口管制的 US$4.5B 计提，一次性、非经营性；"
            "此后四季毛利率逐季修复并已站回 75% 附近。"
            "<b>本图用 GAAP 口径画水平</b>，因为 GAAP 的定义在整段窗口内没变过，"
            "而 non-GAAP 自本季起改为包含股权激励费用；"
            "逐季指引区间与兑现记录见 Exhibit {EX_GM_RANGE}。"
        ),
        "src_extra": "毛利率与营业利润率 = 各季 8-K 合并损益表的毛利 / 营业利益 ÷ 净收入 D。",
    }

    # ── section three ────────────────────────────────────────────────────────
    tracked = {
        "ACIE 占 Data Center": (rounded(acie_share), "pct1", "占 DC 比重", "ACIE 占比"),
        "Networking 占 Data Center": (
            rounded(networking_share), "pct1", "占 DC 比重", "Networking 占比"),
        "non-GAAP 毛利率": (
            financials["non_gaap_gross_margin_pct"], "pct1", "毛利率", "non-GAAP 毛利率"),
        "DSO": (working["dso_days"], "f0", "天", "DSO"),
    }

    def tracking_charts(entries: list[dict]) -> list[dict]:
        charts = []
        for entry in entries:
            metric = entry["metric"]
            if metric not in tracked:
                continue
            values, fmt, ylab, actual_name = tracked[metric]
            side = "上方" if entry["direction"] == "up" else "下方"
            charts.append(threshold_exhibit(
                (f"{metric}：下季阈值 {unit_text(entry['unit'], entry['threshold'])}，"
                 f"当前 {unit_text(entry['unit'], entry['current'])}"),
                labels,
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
                ),
                src_extra=(
                    "实际值来自各季业绩 8-K 与 CFO commentary；"
                    "阈值为本地研究设定，不是公司指引。"
                ),
            ))
        return charts

    headroom_chart = headroom_exhibit(
        "下季 5 条量化阈值：两条占比指标仍在阈值下方，各差 0.3pp",
        next_kpi["quantified"],
        "current",
        (
            "正值 = 仍在安全侧。<b>唯二为负的两条不是风险，是尚未达成的里程碑</b>："
            f"ACIE 占比 {acie_share[-1]:.1f}% 与 Networking 占比 {networking_share[-1]:.1f}% "
            "各差 0.3pp 就能触及 50% 与 20%，是最可能在下季翻面的两条。"
            "真正的风险侧三条都还有余量：non-GAAP 毛利率高于 74.5% 的警戒线，"
            "DSO 45 天离 60 天很远（但公司已主动预告回到 mid-50s），"
            "存货加供应承诺离 US$165B 尚有距离。"
        ),
        src_extra=(
            "阈值为本地研究设定，不是公司指引；当前值为 Q1 2026 实际。"
            + next_kpi["excluded"]
        ),
    )

    # ── section four ─────────────────────────────────────────────────────────
    long_labels = [compact_period(quarter) for quarter in long["quarters"]]
    LONG_STEP = 4
    # The 2022 de-stocking episode, measured rather than remembered: the lowest
    # operating margin in the record, and the highest reading before it.
    operating_margins = long["gaap_operating_margin_pct"]
    crash_trough = min(operating_margins)
    crash_at = operating_margins.index(crash_trough)
    pre_crash_peak = max(operating_margins[:crash_at])
    long_margin_chart = {
        "kind": "lines",
        "title": (
            f"六年毛利率与营业利润率：两次砸穿都是计提，"
            f"营业利润率从 {long['gaap_operating_margin_pct'][0]:.0f}% 抬到 "
            f"{long['gaap_operating_margin_pct'][-1]:.0f}%"
        ),
        "xlabels": long_labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": "GAAP 毛利率", "values": long["gaap_gross_margin_pct"], "color": "NAVY"},
            {"name": "GAAP 营业利润率", "values": long["gaap_operating_margin_pct"],
             "color": "MBLUE"},
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
            "24 季逐季读自各季业绩 8-K 的合并损益表；"
            "毛利率 = 毛利 ÷ 净收入，营业利润率 = 营业利益 ÷ 净收入，均为自算 D。"
        ),
    }

    opex_intensity_chart = {
        "kind": "gs_line",
        "title": (
            f"费用强度六年从 {long['opex_intensity_pct'][0]:.1f}% 降到 "
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
            f"{min(long['opex_intensity_pct']):.1f}%。"
            "<b>这条线在最近两季止跌回升</b>，与公司把 FY27 全年费用增速指引从 low-40s "
            "上调到 upper-40s 是同一件事；它是本季少数斜率向下的指标。"
            "分子分母同为 GAAP 口径，不与 non-GAAP 费用混用。"
        ),
        "src_extra": "营业费用与净收入逐季读自各季业绩 8-K 合并损益表；比值为自算 D。",
    }

    cash_chart = {
        "kind": "grouped_bars",
        "title": (
            f"自由现金流 US${cash['free_cash_flow'][-1] / 1000:.1f}B，"
            f"对 non-GAAP 净利转化率 {fcf_conversion[-1]:.0f}%"
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
            "现金转化极强，但<b>转化率本身波动很大</b>："
            f"这八季在 {min(fcf_conversion):.0f}%–{max(fcf_conversion):.0f}% 之间，"
            "主因是税款与应收的时点，不能按单季外推。"
            "公司已提示下季现金税将显著上升。"
            "<b>NVIDIA 的资本强度不在这张图里</b> —— 它的再投资走的是存货与供应承诺，"
            "见下一张。"
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
            f"环比 {signed(pct_change(total_supply[-1], total_supply[0]))}"
        ),
        "xlabels": supply["quarters"],
        "groups": [
            {"name": "存货", "color": "NAVY", "values": supply["inventory"]},
            {"name": "供应相关承诺（表外）", "color": "GOLD",
             "values": supply["supply_related_commitments"]},
        ],
        "bar_labels": True,
        "fmt": "usd1",
        "label_fmt": "usd1",
        "ylab": "US$B",
        "note": (
            "这是这家公司真正的资本强度所在：表内存货只有 "
            f"US${supply['inventory'][-1]:.1f}B，表外供应承诺却有 "
            f"US${supply['supply_related_commitments'][-1]:.1f}B。"
            "锁仓既是需求可见度，也是押注错误时的放大器 —— "
            "Q1'25 的 H20 计提就是同一台放大器反向运转的结果，"
            "在 Exhibit {EX_GM_RANGE} 上是那根 -10.0pp 的深坑。"
            "<b>本图只有两季</b>：更早的季度未以同一口径披露，本页不做回溯拼接。"
            + supply["note"]
        ),
        "src_extra": (
            "存货为各季资产负债表原值；供应相关承诺为公司在业绩电话会与 10-Q 披露的口径；"
            "合计为自算 D。"
        ),
    }

    # ── assemble ─────────────────────────────────────────────────────────────
    settled_charts = (
        [closure_chart, delivery_chart, expectation_chart(staging)] + delivery_charts
    )
    highlights = [revenue_chart, platform_chart, mix_ratio_chart,
                  accounting_chart, margin_level_chart]
    next_charts = [headroom_chart] + tracking_charts(next_kpi["quantified"])
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
        financial_table.append([
            period,
            f"US${revenue[index] / 1000:.2f}B",
            f"{financials['revenue_yoy_pct'][index]:.1f}%",
            f"{financials['gaap_gross_margin_pct'][index]:.2f}% D",
            f"{financials['non_gaap_gross_margin_pct'][index]:.2f}% D",
            f"{financials['gaap_operating_margin_pct'][index]:.2f}% D",
            f"US${financials['gaap_operating_income_usd_m'][index] / 1000:.2f}B",
            f"US${financials['non_gaap_operating_income_usd_m'][index] / 1000:.2f}B",
        ])
        platform_table.append([
            period,
            f"US${data_center[index] / 1000:.2f}B",
            f"US${platform['hyperscale'][index] / 1000:.2f}B",
            f"US${platform['acie'][index] / 1000:.2f}B",
            f"{acie_share[index]:.1f}% D",
            f"US${platform['edge_computing'][index] / 1000:.2f}B D",
            f"US${split['compute'][index] / 1000:.1f}B",
            f"US${split['networking'][index] / 1000:.1f}B",
            f"{networking_share[index]:.1f}% D",
        ])
        cash_table.append([
            period,
            f"US${cash['operating_cash_flow'][index] / 1000:.2f}B",
            f"US${cash['free_cash_flow'][index] / 1000:.2f}B",
            f"US${capex_like[index] / 1000:.2f}B D",
            f"{fcf_conversion[index]:.0f}% D",
            f"{working['dso_days'][index]:.0f}天",
            f"US${working['accounts_receivable_usd_m'][index] / 1000:.2f}B",
            f"US${working['inventories_usd_m'][index] / 1000:.2f}B",
        ])

    guide_rows = [
        ["收入", f"US${guided_revenue:.1f}B ±2%", f"US${revenue[-1] / 1000:.2f}B",
         f"高于中值 {pct_change(revenue[-1] / 1000, guided_revenue):.1f}% D",
         f"US${q2_midpoint:.1f}B ±{q2_guide['revenue_band_pct']:.0f}%",
         f"中值环比 {signed(q2_growth)} D"],
        ["GAAP 毛利率", f"{guide_history['gaap_gm_guide_pct'][current_index]:.1f}% ±50bp",
         f"{financials['gaap_gross_margin_pct'][-1]:.2f}% D", "区间内",
         f"{q2_guide['gaap_gross_margin_pct']:.1f}% ±50bp", "持平"],
        ["non-GAAP 毛利率", f"{guided_margin:.1f}% ±50bp", f"{actual_margin:.2f}% D", "区间内",
         f"{q2_guide['non_gaap_gross_margin_pct']:.1f}% ±50bp", "持平，无扩张"],
        ["GAAP 营业费用",
         f"US${guide_history['gaap_opex_guide_usd_bn'][current_index]:.1f}B",
         f"US${gaap_opex:.2f}B",
         f"低于指引 {abs(pct_change(gaap_opex, guide_history['gaap_opex_guide_usd_bn'][current_index])):.1f}% D",
         f"US${q2_guide['gaap_opex_usd_bn']:.1f}B",
         f"中值环比 {signed(pct_change(q2_guide['gaap_opex_usd_bn'], gaap_opex))} D"],
        ["non-GAAP 营业费用", f"US${guided_opex:.1f}B", f"US${actual_opex:.2f}B",
         f"低于指引 {abs(pct_change(actual_opex, guided_opex)):.1f}% D",
         f"US${q2_guide['non_gaap_opex_usd_bn']:.1f}B",
         f"中值环比 {signed(pct_change(q2_guide['non_gaap_opex_usd_bn'], actual_opex))} D"],
        ["FY 税率",
         f"{guidance['fy27_prior_tax_rate_pct'][0]:.0f}–"
         f"{guidance['fy27_prior_tax_rate_pct'][1]:.0f}%", "—", "下调 1pp",
         f"{guidance['fy27_tax_rate_pct'][0]:.0f}–{guidance['fy27_tax_rate_pct'][1]:.0f}%",
         "公司称受地区结构影响"],
        ["中国 Data Center compute", "假设为 0", "实际为 0", "符合",
         "仍假设为 0", "任何金额均为 upside"],
    ]

    tables = [
        {
            "n": next_table_number,
            "title": "Q1 2026 兑现与 Q2 2026 指引",
            "headers": ["指标", "Q1 原指引", "Q1 实际", "兑现", "Q2 新指引", "变化 / 备注"],
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
                        "GAAP 营业利润率", "GAAP 营业利润", "non-GAAP 营业利润"],
            "rows": financial_table,
        },
        {
            "n": next_table_number + 3,
            "title": "八季度市场平台与 Data Center 拆分",
            "headers": ["期间", "Data Center", "Hyperscale", "ACIE", "ACIE 占 DC",
                        "Edge Computing", "DC Compute", "DC Networking", "Networking 占 DC"],
            "rows": platform_table,
        },
        {
            "n": next_table_number + 4,
            "title": "八季度现金流与营运资金",
            "headers": ["期间", "经营现金流", "自由现金流", "资本支出及租赁本金",
                        "FCF / non-GAAP 净利", "DSO", "应收账款", "存货"],
            "rows": cash_table,
        },
        {**delivery_table, "n": next_table_number + 5},
        ai_capex_cycle_table(next_table_number + 6),
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
            "disclosed_period_label": "Q1 2026",
            "full_financial_period_label": "Q1 2026",
            "period_end": "2026-04-26",
            "release_date": "2026-05-20",
            "analysis_date": "2026-05-24",
            "audit_status": "unaudited",
            "status": "history_ready",
        },
        "tracker": "Watchlist Quarterly Tracker · NVDA",
        "title": "NVIDIA (NVDA)：Q1 2026 季报仪表盘",
        "subtitle": (
            "截至 2026-04-26 · 发布 2026-05-20 · US GAAP · 未审计 · "
            "1 月制财年，本站按自然年季度标注：本页 Q1 2026 即公司所称 FY2027 Q1"
        ),
        "headline": (
            f"收入 US${revenue[-1] / 1000:.1f}B、同比 {signed(financials['revenue_yoy_pct'][-1])}，"
            f"环比绝对增量 US${(revenue[-1] - revenue[-2]) / 1000:.1f}B 创纪录，"
            "且 ACIE 已几乎与 Hyperscale 等大；"
            "但两套口径的分叉全部落在营业利润以下 —— "
            f"GAAP 净利环比 {pct_change(restated['gaap_net_income_usd_m'][0], restated['gaap_net_income_usd_m'][1]):+.0f}% "
            f"里有一半以上来自股权投资收益，non-GAAP 只有 "
            f"{pct_change(restated['non_gaap_net_income_usd_m'][0], restated['non_gaap_net_income_usd_m'][1]):+.0f}%。"
        ),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>亮点</span><b>二阶导重新加速</b>'
            f'<p>环比增量 US${(revenue[-1] - revenue[-2]) / 1000:.1f}B 创纪录；'
            f'Q2 指引中值 US${q2_midpoint:.0f}B，隐含环比 {signed(q2_growth)}。</p></article>'
            '<article><span>结构</span><b>ACIE 追平 Hyperscale</b>'
            f'<p>ACIE 占 DC {acie_share[-1]:.1f}%，环比 '
            f'{signed(pct_change(platform["acie"][-1], platform["acie"][-2]))}；'
            f'Networking 占 DC {networking_share[-1]:.1f}%。</p></article>'
            '<article><span>存疑</span><b>利润被股权收益放大</b>'
            f'<p>税前收益 US${restated["equity_securities_gains_usd_m"][0] / 1000:.1f}B；'
            '经营质量看 non-GAAP 营业利润与 FCF。</p></article>'
            '</div>'
        ),
        "source": source,
        "source_url": (
            "https://investor.nvidia.com/news/press-release-details/2026/"
            "NVIDIA-Announces-Financial-Results-for-First-Quarter-Fiscal-2027/default.aspx"
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
                    "收入的二阶导、Data Center 内部的客户结构、"
                    "两条护城河比率，以及 GAAP 与 non-GAAP 在净利处的分叉。"
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
                    "NVDA 专属的常规序列：六年利润率与费用强度、现金转化，"
                    "以及真正承载资本强度的存货与供应承诺。"
                ),
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "本页所有季度按自然年标注。NVIDIA 财年 1 月底结束，故本页的 Q1 2026 是截至 2026-04-26 的季度，公司自己称之为 FY2027 Q1；不统一成一种约定，跨公司的资本开支对照表就会把不同的三个月放在一起比较。",
            f"Exhibit {next_ex[0]['n']} 与其后各图的阈值是本地研究设定，不是公司指引，也不构成评级或投资建议；「距阈值余量」统一为正值代表安全侧。",
            f"第一节的指引兑现组图（Exhibit {settled_ex[3]['n']}–{settled_ex[-1]['n']}）用的是同一批业绩 8-K：每份新闻稿的 Outlook 段同时给出下一季的收入区间（±2%）、GAAP 与 non-GAAP 毛利率区间（±50bp）以及两条营业费用的单点指引，实际值取自随后一季 8-K 的合并损益表与 GAAP/non-GAAP 对账表。",
            f"Exhibit {settled_ex[5]['n']} 的三条腿是恒等式而非估计：公司同时指引收入、毛利率与费用，三者隐含一个它从不印出来的营业利润，实际值与它的差恰好等于三条腿之和。收入与毛利率同时偏离时的交叉项按该式全部计入毛利率腿，调换拆解顺序会把它移到收入腿，两种拆法的合计相同。",
            "自 Q1 2026 起公司的 non-GAAP 口径不再剔除股权激励费用，并已重述历史（Q4 2025 的 non-GAAP EPS 由当时的 $1.62 重述为 $1.59）。本页凡涉及跨季比较的 non-GAAP 数一律取重述后口径；而指引兑现各图逐季比较的是当季指引与当季实际，两者始终处在同一口径下，不受这次变更影响。",
            "长期序列一律用 GAAP 口径，因为 GAAP 的定义在整个窗口内没有变过；把两种 non-GAAP 口径接成一条线会在变更处砸出纯定义性的落差。",
            "Data Center 的 Hyperscale / ACIE 拆分为公司 2026 年启用的新分部。其中 Q1 2026、Q4 2025、Q1 2025 三季直接取自 Q1 FY2027 CFO commentary，其余五季为公司同一次重述值经本地分析稿转录，逐季与该季 8-K 所载 Data Center 合计数核对相符。",
            "Data Center 的 compute / networking 拆分公司只披露到 US$0.1B 精度，故其占比为四舍五入口径。",
            "自由现金流为公司披露值，按公司定义已扣除资本支出与租赁本金；本页的「资本支出及租赁本金」是经营现金流与自由现金流之差，因此同时含两者，不等同狭义 capex。",
            "本页只发布公司披露值、可复算的简单派生值，以及明确标注的市场预期；D 标记代表 Derived / 自算。",
            "市场预期一律标注为「市场预期」并给出取数时点，不写卖方机构名，也不发布评级、目标价或估值。",
            "本页已知未接入：地区收入拆分（公司未按系统性口径披露）、客户集中度与前三大应收占比（须待 10-Q）、战略投资的规模与回报口径（公司未披露）、Vera Rubin 的出货金额（公司未给量化口径），以及 2025 年以前的供应承诺（当时未以同一口径披露）。",
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
