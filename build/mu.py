#!/usr/bin/env python3
"""Build the Micron Technology quarterly-results page.

Same four-part, chart-led shape as the other pages (上季兑现 → 本季重点 →
下季跟踪 → 长期常规).  Micron's fiscal year ends on the Thursday nearest 31
August, so every label here is the calendar quarter the fiscal one mostly
covers: the quarter ended 2026-05-28 is the company's fiscal Q3 2026 and this
page's ``Q2 2026``.

What Micron brings to this site is a company whose own guidance has been broken
in both directions by double-digit percentage points, and recently.  Twenty-two
other pages here argue about whether a business is compounding; this one is
about a commodity, and the record says so plainly: across twenty-seven finished
quarters the non-GAAP gross-margin guidance was cleared 16 times, landed inside
its band 8 times and was **missed 3 times** -- once, in Q1 2023, by forty
percentage points, when a guided +8.5% came in at −31.4%.  Two quarters ago the
same guidance was beaten by 6.9 points.  A page that only showed the last eight
quarters would show a company that cannot stop beating itself, and would be
describing one half of a cycle as though it were a trend.

The second thing this page is for is the arithmetic under the record quarter,
and it needs no estimate of any kind.  Revenue went from US$11,315M to
US$41,456M across four quarters -- and cost of goods sold went from US$6,261M
to US$6,400M.  Both are filed lines on the same income statement.  Micron
describes the price move only in words ("a low-60% range increase in average
selling prices"), so this page never turns those words into a number; it plots
the two filed lines instead and lets the gap be the argument.

The public payload contains only Micron-reported figures and arithmetic
reproducible from the audit tables.  Where the number management says on a call
differs from the number in the filing -- the supply agreements, where the
filed remaining performance obligation is US$5.0B and the spoken figure is
US$100B -- both are published side by side and labelled.
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
    midpoint_deviation,
    number_exhibits,
    threshold_exhibit,
    threshold_table,
    unit_text,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "mu.json"
DATA_DIR = ROOT / "data"

# The dollar-band charts are drawn over a short window on purpose: revenue runs
# from US$3.7B to US$50B across the guided record, so on one linear axis the
# early ±US$200M bands collapse to a couple of pixels. The scale-free question
# is answered over the whole record by the deviation chart beside each one.
BAND_WINDOW = 12



def continuous_tail(values: list) -> int:
    """Index where this series' unbroken run to the present begins.

    Micron's press releases stopped printing several lines for years at a time
    -- cost of goods sold has a seventeen-quarter hole (FQ4-17 to FQ3-21) and
    inventory days an eighteen-quarter one. A chart drawn over the whole record
    would show a long blank stretch that reads as a collapse rather than as a
    disclosure gap, so charts that need an unbroken line take this tail. It is
    computed rather than hardcoded so the window grows by itself if the hole is
    ever filled from the 10-Qs.
    """
    start = len(values)
    while start > 0 and values[start - 1] is not None:
        start -= 1
    return start

def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100


def compact_period(period: str) -> str:
    """``'Q2 2026'`` → ``'Q2'26'``."""
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


def billions(values: list[float | None]) -> list[float | None]:
    """Millions to billions, carrying nulls through rather than crashing on them.

    Written when Micron's net-capex row lost two quarters. `[v / 1000 for v in ...]`
    had been fine only because no series in this block had ever had a hole in it,
    which is not a property anyone had checked -- it was a property of the data
    happening to be complete.
    """
    return [None if v is None else v / 1000.0 for v in values]


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
    "指引区间来自各季业绩 8-K 的 EX-99.1 新闻稿里那张 Business Outlook 表 —— "
    "公司在同一张表里用同一种句式给出下一季的收入、毛利率、营业费用与摊薄每股收益，"
    "GAAP 与 non-GAAP 两栏并列；实际值来自随后一季 8-K 的合并损益表与 GAAP/non-GAAP 对账表。"
)

# Micron reports about four weeks after its quarter ends and guides the quarter
# that has already started, so this record is not an ex-ante one. Named on every
# chart in the group, the way TJX's is.
TIMING = "该季<b>开始后 18–35 天</b>"

LAG_NOTE = (
    "<b>先读这一句，再读命中率。</b>Micron 的下一季指引是随上一季业绩一起发布的，"
    "而它在季末约四周后发业绩，所以这张 Outlook 表落在<b>它所指引的那个季度之内</b>："
    "本记录里最早的一次是第 18 天、最晚的一次是第 35 天、中位数第 26 天，"
    "即公司给出区间时该季通常已经过去五分之一到三分之一。"
    "这不是一份事前预测。"
)


# ── section one: the guided record ──────────────────────────────────────────
def guidance_delivery_charts(staging: dict) -> tuple[list[dict], dict]:
    """Four guided numbers, and the two-sided record they leave.

    Micron guides revenue, both gross margins, both operating-expense lines and
    both earnings-per-share lines every quarter in one table, so "did the
    quarter clear the company's own bar" has a twenty-seven-quarter answer.  The
    answer differs sharply by metric and, unlike every other guided record on
    this site, it is genuinely two-sided.

    The beat decomposition at the end is an identity rather than an estimate.
    Guiding revenue, margin and expenses together implies an operating income
    the company never prints:

        implied non-GAAP OI = guided revenue × guided margin − guided opex

    and the distance from what was reported splits exactly three ways:

        actual − implied = (Ra − Rg)·mg + Ra·(ma − mg) − (Ea − Eg)

    Every term is a company-published outlook number or a company-reported
    quarterly number, so the split needs no estimate.
    """
    record = staging["quarterly_guidance_history"]
    quarters = record["quarters"]
    labels = [compact_period(quarter) for quarter in quarters]
    lag = record["publication_lag_days"]

    def band(mid_key: str) -> tuple[list[float | None], list[float | None]]:
        mids = record[mid_key]
        widths = record[f"{mid_key}_band"]
        points = record[f"{mid_key}_is_point"]
        low = [None if m is None else (m if p else m - (w or 0))
               for m, w, p in zip(mids, widths, points)]
        high = [None if m is None else (m if p else m + (w or 0))
                for m, w, p in zip(mids, widths, points)]
        return low, high

    revenue_lo, revenue_hi = band("guide_non_gaap_revenue_usd_m")
    revenue_lo = [None if v is None else v / 1000 for v in revenue_lo]
    revenue_hi = [None if v is None else v / 1000 for v in revenue_hi]
    revenue_mid = [None if v is None else v / 1000
                   for v in record["guide_non_gaap_revenue_usd_m"]]
    revenue_actual = [None if v is None else v / 1000
                      for v in record["actual_revenue_usd_m"]]

    margin_lo, margin_hi = band("guide_non_gaap_gross_margin_pct")
    margin_mid = record["guide_non_gaap_gross_margin_pct"]
    margin_actual = record["actual_non_gaap_gross_margin_pct"]

    eps_lo, eps_hi = band("guide_non_gaap_eps_usd")
    eps_mid = record["guide_non_gaap_eps_usd"]
    eps_actual = record["actual_non_gaap_eps_usd"]

    opex_mid = record["guide_non_gaap_opex_usd_m"]
    opex_actual = record["actual_non_gaap_opex_usd_m"]

    finished = [index for index, value in enumerate(revenue_actual) if value is not None]
    window = slice(len(quarters) - BAND_WINDOW, len(quarters))

    def tally(low, high, actual):
        done = [i for i, v in enumerate(actual) if v is not None and low[i] is not None]
        above = sum(1 for i in done if actual[i] > high[i])
        below = sum(1 for i in done if actual[i] < low[i])
        return len(done), above, len(done) - above - below, below

    rev_n, rev_above, rev_inside, rev_below = tally(revenue_lo, revenue_hi, revenue_actual)
    gm_n, gm_above, gm_inside, gm_below = tally(margin_lo, margin_hi, margin_actual)
    eps_n, eps_above, eps_inside, eps_below = tally(eps_lo, eps_hi, eps_actual)

    # the single worst quarter of the record, recounted rather than recalled
    gm_gaps = [(margin_actual[i] - margin_mid[i], i) for i in finished]
    worst_gap, worst_index = min(gm_gaps)
    best_gap, best_index = max(gm_gaps)

    revenue_band_chart = delivery_band(
        "EX_REV_RANGE", "收入", labels[window], revenue_lo[window], revenue_hi[window],
        revenue_actual[window],
        fmt="usd1", ylab="US$B", unit="US$B", venue="业绩发布",
        scope=f"（本图仅近 {BAND_WINDOW} 季）",
        timing=TIMING,
        src_extra=SOURCE_8K,
        extra_note=(
            LAG_NOTE
            + f"<b>这张只画最近 {BAND_WINDOW} 季，不是数据缺失</b>：本页的指引记录一路回到 2019 年，"
            "而收入在这段时间从 US$3.7B 长到 US$50B，十几倍的量级差放在一根线性美元轴上，"
            "早年那些 ±US$200M 的区间会被压成几个像素。"
            "完整 {full} 季的同一问题改用与量级无关的口径回答，见 Exhibit {EX_REV_DEV}。"
        ).replace("{full}", str(rev_n)),
    )
    revenue_dev_chart = midpoint_deviation(
        "EX_REV_DEV", "收入", quarters, revenue_lo, revenue_hi, revenue_actual,
        mode="pct", window=len(finished), label=compact_period, bar_labels=False,
        src_extra=SOURCE_8K + "偏离为实际收入除以指引中值的自算值。",
        extra_note=(
            f"<b>这是本节最该先读的一张。</b>{rev_n} 个已完结季里，"
            f"{rev_above} 季高于指引区间上限、{rev_inside} 季落在区间内、{rev_below} 季跌破下限 —— "
            "接近一半一半。<b>这与本站其他几家给多项指引的公司正好相反</b>："
            "那几家的收入指引长期是底线，Micron 的收入指引更接近一份真预测，"
            "而它两侧的尾巴都很长。"
        ),
    )

    margin_band_chart = delivery_band(
        "EX_GM_RANGE", "non-GAAP 毛利率", labels, margin_lo, margin_hi, margin_actual,
        fmt="pct0", ylab="non-GAAP 毛利率", unit="%", venue="业绩发布",
        timing=TIMING,
        src_extra=(SOURCE_8K + "实际 non-GAAP 毛利率 = 对账表的 non-GAAP 毛利 ÷ 当季收入 D。"),
        extra_note=(
            "<b>这条线的形状就是本页存在的理由。</b>"
            f"{gm_n} 个已完结季里 {gm_above} 季穿出上限、{gm_inside} 季落在区间内、"
            f"{gm_below} 季跌破下限；"
            f"而跌破的幅度和穿出的幅度完全不是一个量级 —— 最差的一次是 "
            f"{compact_period(quarters[worst_index])}，公司指引 {margin_mid[worst_index]:.1f}%、"
            f"报出来 {margin_actual[worst_index]:.1f}%，差 {abs(worst_gap):.1f} 个百分点。"
            f"最好的一次是 {compact_period(quarters[best_index])} 的 {signed(best_gap, 1, 'pp')}。"
            "<b>同一家公司、同一张 Outlook 表、同一种句式，三年之内既能差四十个百分点，"
            "也能好六个百分点。</b>把窗口截到最近八季，看到的会是一家不断超越自己的公司；"
            "这条完整的线说的是别的事。"
        ),
    )
    margin_dev_chart = midpoint_deviation(
        "EX_GM_DEV", "non-GAAP 毛利率", quarters, margin_lo, margin_hi, margin_actual,
        mode="pp", window=len(finished), label=compact_period, bar_labels=False,
        src_extra=(SOURCE_8K + "实际 non-GAAP 毛利率 = 对账表的 non-GAAP 毛利 ÷ 当季收入 D；"
                   "偏离为实际值减指引中值的自算值。"),
        extra_note=(
            "把 Exhibit {EX_GM_RANGE} 的形状量出来。"
            "<b>注意纵轴的不对称</b>：向上最大 "
            f"{signed(best_gap, 1, 'pp')}，向下最大 {signed(worst_gap, 1, 'pp')}，"
            "一根柱子就把其余二十六根压平了。"
            "本页据此把下季 non-GAAP 毛利率的警戒线设在 84.0%（公司指引约 86%），"
            "见 Exhibit {EX_GM_THRESHOLD}。"
        ),
    )

    eps_band_chart = delivery_band(
        "EX_EPS_RANGE", "non-GAAP 每股收益", labels[window], eps_lo[window], eps_hi[window],
        eps_actual[window],
        fmt="usd2", ylab="US$/股", unit="US$", venue="业绩发布",
        scope=f"（本图仅近 {BAND_WINDOW} 季）",
        timing=TIMING,
        src_extra=SOURCE_8K,
        extra_note=(
            f"完整记录里 {eps_n} 季有 {eps_above} 季高于指引上限、{eps_inside} 季落在区间内、"
            f"{eps_below} 季跌破下限，是四个指引数字里最偏向一侧的一个 —— "
            "但它偏向哪一侧几乎完全由毛利率决定，因为收入与费用两条腿的偏离都很小，"
            "见 Exhibit {EX_LEGS}。同样只画近 12 季：每股收益在整段记录里从 −US$1.91 到 US$25.11。"
        ),
    )
    # ── what the beat is made of ─────────────────────────────────────────────
    revenue_leg, margin_leg, opex_leg, leg_labels = [], [], [], []
    for index in finished:
        if None in (opex_mid[index], opex_actual[index]):
            continue
        guided_revenue = revenue_mid[index] * 1000
        guided_margin = margin_mid[index] / 100
        guided_opex = opex_mid[index]
        actual_revenue = record["actual_revenue_usd_m"][index]
        actual_margin = margin_actual[index] / 100
        actual_opex = opex_actual[index]
        revenue_leg.append((actual_revenue - guided_revenue) * guided_margin / 1000)
        margin_leg.append(actual_revenue * (actual_margin - guided_margin) / 1000)
        opex_leg.append(-(actual_opex - guided_opex) / 1000)
        leg_labels.append(compact_period(quarters[index]))

    total = [sum(legs) for legs in zip(revenue_leg, margin_leg, opex_leg)]
    misses = [index for index, value in enumerate(total) if value < 0]
    margin_driven = [
        index for index in misses
        if margin_leg[index] == min(revenue_leg[index], margin_leg[index], opex_leg[index])
    ]
    miss_labels = "、".join(leg_labels[index] for index in misses)
    biggest = max(range(len(total)), key=lambda i: abs(total[i]))

    legs_chart = {
        "ref": "EX_LEGS",
        "kind": "grouped_bars",
        "title": (
            f"把「超出自身指引」拆成三条腿：{len(total)} 季里 {len(misses)} 季为负，"
            + ("且全部是毛利率腿砸的"
               if misses and len(margin_driven) == len(misses)
               else f"其中 {len(margin_driven)} 季是毛利率腿砸的")
        ),
        "xlabels": leg_labels,
        "xrot": 90,
        "groups": [
            {"name": "收入腿", "color": "NAVY", "values": rounded(revenue_leg)},
            {"name": "毛利率腿", "color": "GOLD", "values": rounded(margin_leg)},
            {"name": "费用腿", "color": "MBLUE", "values": rounded(opex_leg)},
        ],
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
            "<b>读数：</b>浅蓝的费用腿几乎从不重要 —— 这家公司的费用是它最可预测的一条线。"
            "真正决定这一季是好是坏的是金色的毛利率腿，"
            f"窗口内最大的一次是 {leg_labels[biggest]} 的 {total[biggest]:+.1f}B，"
            f"其中毛利率腿 {margin_leg[biggest]:+.1f}B。"
            + (f"为负的 {len(misses)} 季（{miss_labels}）里，"
               + ("每一季都是金色那条塌下去。"
                  if len(margin_driven) == len(misses)
                  else f"{len(margin_driven)} 季是金色那条塌下去，"
                       f"其余 {len(misses) - len(margin_driven)} 季由收入腿主导。")
               if misses else "")
            + "<b>交互项归属：</b>收入与毛利率同时偏离时的交叉项按上式全部计入毛利率腿；"
            "调换拆解顺序会把它移到收入腿，两种拆法的合计完全相同。"
        ),
        "src_extra": SOURCE_8K + "三条腿均为自算，指引原值与实际原值见核对表。",
    }

    # There is deliberately no midpoint-deviation chart for earnings per share.
    # The guided midpoint is NEGATIVE in five of these quarters, and
    # `actual / midpoint - 1` flips sign across zero: a quarter that lost more
    # than guided would plot as a positive bar. The percentage-point version of
    # the same question is on the gross-margin deviation chart, which is where
    # the earnings-per-share record is decided anyway.
    charts = [
        revenue_band_chart, revenue_dev_chart,
        margin_band_chart, margin_dev_chart,
        eps_band_chart,
        legs_chart,
    ]
    negative_midpoints = sum(1 for value in eps_mid if value is not None and value < 0)
    eps_band_chart["note"] += (
        f"<b>这条记录没有配一张「相对指引中值的偏离」图</b>，"
        f"而收入与毛利率都有 —— 因为本记录里有 {negative_midpoints} 季的每股收益指引中值是<b>负数</b>，"
        "「实际 ÷ 中值 − 1」在跨过零时会翻符号：亏得比指引更多的季度会画成一根正的柱子。"
        "同一个问题的百分点口径在 Exhibit {EX_GM_DEV} 上，"
        "而这家公司的每股收益偏离几乎完全由毛利率偏离决定（见 Exhibit {EX_LEGS}）。"
    )

    table = {
        "title": f"指引兑现全表（{len(quarters)} 季，含尚未完结的一季）",
        "headers": ["期间", "公司财季", "指引发布日", "距该季开始",
                    "收入指引", "实际收入", "较中值",
                    "non-GAAP 毛利率指引", "实际", "费用指引", "实际费用",
                    "每股收益指引", "实际每股收益"],
        "rows": [],
    }
    for index, quarter in enumerate(quarters):
        actual_revenue = record["actual_revenue_usd_m"][index]
        done = actual_revenue is not None
        point_gm = record["guide_non_gaap_gross_margin_pct_is_point"][index]
        point_opex = record["guide_non_gaap_opex_usd_m_is_point"][index]
        table["rows"].append([
            quarter,
            record["fiscal_labels"][index],
            record["published_on"][index],
            f"第 {lag[index]} 天",
            f"US${revenue_lo[index]:.2f}–{revenue_hi[index]:.2f}B",
            f"US${actual_revenue / 1000:.2f}B" if done else "—",
            f"{pct_change(actual_revenue / 1000, revenue_mid[index]):+.2f}% D" if done else "—",
            (f"约 {margin_mid[index]:.1f}%" if point_gm
             else f"{margin_lo[index]:.1f}–{margin_hi[index]:.1f}%"),
            f"{margin_actual[index]:.2f}% D" if done and margin_actual[index] is not None else "—",
            (f"约 US${opex_mid[index]:,.0f}M" if point_opex
             else f"US${opex_mid[index]:,.0f}M"),
            f"US${opex_actual[index]:,.0f}M" if done and opex_actual[index] is not None else "—",
            (f"US${eps_lo[index]:.2f}–{eps_hi[index]:.2f}"
             if eps_lo[index] is not None else "—"),
            f"US${eps_actual[index]:.2f}" if done and eps_actual[index] is not None else "—",
        ])
    # Returned so the page's `brief` can print the same tallies instead of
    # retyping them. Hand-typed prose beside a computed chart is the shape the
    # tally gate was written for, and the brief was the one place it was still
    # happening.
    tallies = {
        "revenue": (rev_n, rev_above, rev_inside, rev_below),
        "gross_margin": (gm_n, gm_above, gm_inside, gm_below),
        "worst_gap": worst_gap,
    }
    return charts, table, tallies


# ── section two: what the quarter is made of ────────────────────────────────
def quarter_charts(staging: dict) -> list[dict]:
    """The price-only quarter, in filed lines only.

    Micron states the price and volume moves only as words, so nothing here
    turns "a low-60% range increase in average selling prices" into a number.
    What it does instead is plot revenue against cost of goods sold: the two
    lines are filed, they sit on the same statement, and the gap between them
    is the whole argument.
    """
    periods = staging["periods"]
    labels = [compact_period(period) for period in periods]
    fin = staging["financials"]
    bal = staging["balance_sheet"]
    tech = staging["technology"]
    units = staging["business_units"]

    revenue = fin["revenue_usd_m"]
    cogs = fin["cost_of_goods_sold_usd_m"]
    four_back = -5

    # Cost of goods sold is not continuous across the record: Micron's releases
    # printed it through FQ3-17 and then stopped until FQ4-21, leaving a
    # seventeen-quarter hole in the middle. A chart of revenue *against* COGS has
    # to live on the span where both exist, so it takes the continuous tail --
    # computed, not a hardcoded 19, so it grows on its own if the hole is ever
    # filled from the 10-Qs.
    cogs_start = continuous_tail(cogs)
    rc_labels = labels[cogs_start:]
    rc_revenue = revenue[cogs_start:]
    rc_cogs = cogs[cogs_start:]

    revenue_cogs = {
        "ref": "EX_REV_COGS",
        "kind": "grouped_bars",
        "title": (
            f"一年之间收入 {signed(pct_change(revenue[-1], revenue[four_back]), 0)}，"
            f"销货成本 {signed(pct_change(cogs[-1], cogs[four_back]), 0)}"
            f"（本图 {len(rc_labels)} 季）"
        ),
        "xlabels": rc_labels,
        "xrot": 90,
        "groups": [
            {"name": "收入", "color": "NAVY", "values": rounded([v / 1000 for v in rc_revenue])},
            {"name": "销货成本", "color": "GOLD", "values": rounded([v / 1000 for v in rc_cogs])},
        ],
        "bar_labels": False,
        "fmt": "usd1",
        "label_fmt": "usd1",
        "ylab": "US$B",
        "note": (
            "<b>本页最重要的一张，而它只用了同一张损益表上的两行。</b>"
            f"{periods[four_back]} 到 {periods[-1]}（同一个季度，隔一年），"
            f"收入从 US${revenue[four_back] / 1000:.2f}B "
            f"长到 US${revenue[-1] / 1000:.2f}B，而销货成本从 US${cogs[four_back] / 1000:.2f}B "
            f"只走到 US${cogs[-1] / 1000:.2f}B。最近一季销货成本环比 "
            f"{signed(fin['cost_of_goods_sold_qoq_pct'][-1])}，收入环比 "
            f"{signed(fin['revenue_qoq_pct'][-1])}。"
            "<b>公司自己对价格与出货量只给文字，不给数字</b> —— 10-Q 的原话是"
            "「DRAM 平均售价上升 low-60% range、出货位元上升 low-single-digit percentage range」。"
            "把这种措辞折算成一个百分比需要自选一个中点，那是假设不是算术，所以本页不发布那个数。"
            "但这两条<b>申报</b>的线摆在一起，已经把同一件事说完了：涨的是价，不是量。"
        ),
        "src_extra": "收入与销货成本取自各季业绩 8-K EX-99.1 的合并损益表。",
    }

    # The technology split has no quarters list of its own -- it aligns to the
    # top-level `periods` by position -- so it carries leading nulls back to the
    # record's start. Draw it over its own continuous tail.
    tech_start = continuous_tail(tech["dram_revenue_usd_m"])
    tech_labels = labels[tech_start:]
    dram = tech["dram_revenue_usd_m"][tech_start:]
    nand = tech["nand_revenue_usd_m"][tech_start:]
    other = tech["other_revenue_usd_m"][tech_start:]
    dram_share = tech["dram_share_pct"][tech_start:]
    technology_chart = {
        "ref": "EX_TECH",
        "kind": "stacked_dual",
        "title": (
            f"按技术拆收入：DRAM US${dram[-1] / 1000:.2f}B、NAND US${nand[-1] / 1000:.2f}B，"
            f"DRAM 占 {dram_share[-1]:.1f}%（本图 {len(tech_labels)} 季）"
        ),
        "xlabels": tech_labels,
        "xrot": 90,
        "stacks": [
            {"name": "DRAM", "color": "NAVY", "values": rounded([v / 1000 for v in dram])},
            {"name": "NAND", "color": "MBLUE", "values": rounded([v / 1000 for v in nand])},
            {"name": "其他（主要为 NOR）", "color": "BLUE",
             "values": rounded([v / 1000 for v in other])},
        ],
        # `stacked_dual` scales its right axis with `ticks(0, ymax || 60, 6)`,
        # which never looks at the data. This share sits near 75%, so without
        # an explicit ymax the line would be drawn above the top of the canvas
        # and silently clipped while the legend went on naming it.
        "line": {"name": "DRAM 占收入 (RHS)", "color": "GOLD",
                 "values": rounded(dram_share), "yfmt": "pct1", "ymax": 100},
        "fmt": "usd1", "yfmt": "usd1", "label_fmt": "usd1",
        "ylab": "US$B", "rhs_label": "%",
        "note": (
            "<b>三段之和逐季等于合并损益表的收入，差额为零</b> —— "
            "这三行是 10-Q 收入注释里印出来的美元数（Revenue by Technology），"
            "不是用百分比乘总额倒推的。"
            f"最近一季 NAND 收入环比 {signed(pct_change(nand[-1], nand[-2]), 0)}、"
            f"DRAM 环比 {signed(pct_change(dram[-1], dram[-2]), 0)}，"
            "所以金色的 DRAM 占比线在收入创纪录的同一季<b>下滑</b>："
            f"{dram_share[-2]:.1f}% → {dram_share[-1]:.1f}%。"
            "公司口径里 NAND 的售价涨幅（mid-80% range）高于 DRAM（low-60% range），"
            "而两者的出货位元都只是低个位数到中个位数的增长。"
        ),
        "src_extra": "各季 10-Q / 10-K 收入注释的 Revenue by Technology 表。",
    }

    unit_labels = [compact_period(period) for period in units["quarters"]]
    unit_revenue = {
        "ref": "EX_BU_REV",
        "kind": "grouped_bars",
        "title": (
            "四个业务单元的收入：数据中心两条腿（云内存 + 核心数据中心）"
            f"合计 US${(units['CMBU_revenue_usd_m'][-1] + units['CDBU_revenue_usd_m'][-1]) / 1000:.1f}B，"
            f"占 {(units['CMBU_revenue_usd_m'][-1] + units['CDBU_revenue_usd_m'][-1]) / staging['financials']['revenue_usd_m'][-1] * 100:.0f}%"
        ),
        "xlabels": unit_labels,
        "groups": [
            {"name": "云内存 CMBU", "color": "NAVY",
             "values": rounded([v / 1000 for v in units["CMBU_revenue_usd_m"]])},
            {"name": "核心数据中心 CDBU", "color": "MBLUE",
             "values": rounded([v / 1000 for v in units["CDBU_revenue_usd_m"]])},
            {"name": "移动与客户端 MCBU", "color": "GOLD",
             "values": rounded([v / 1000 for v in units["MCBU_revenue_usd_m"]])},
            {"name": "汽车与嵌入式 AEBU", "color": "ORANGE",
             "values": rounded([v / 1000 for v in units["AEBU_revenue_usd_m"]])},
        ],
        "bar_labels": False,
        "fmt": "usd1",
        "label_fmt": "usd1",
        "ylab": "US$B",
        "note": (
            "<b>这条序列只有八个季度，而且不会更长。</b>公司从 FY2025 Q4 那份业绩稿起"
            "才在新闻稿里印出这张四单元表，此前的业绩稿里没有任何分部表；"
            "更早的分部是 CNBU / MBU / SBU / EBU 四个完全不同的口径，"
            "把两套拼成一条线会画出一段谁都没报过的历史，所以本页从新口径开始，不往前补。"
            f"最近一季四个单元的环比分别是 "
            f"CMBU {signed(pct_change(units['CMBU_revenue_usd_m'][-1], units['CMBU_revenue_usd_m'][-2]), 0)}、"
            f"CDBU {signed(pct_change(units['CDBU_revenue_usd_m'][-1], units['CDBU_revenue_usd_m'][-2]), 0)}、"
            f"MCBU {signed(pct_change(units['MCBU_revenue_usd_m'][-1], units['MCBU_revenue_usd_m'][-2]), 0)}、"
            f"AEBU {signed(pct_change(units['AEBU_revenue_usd_m'][-1], units['AEBU_revenue_usd_m'][-2]), 0)}。"
        ),
        "src_extra": "各季业绩 8-K EX-99.1 的 Quarterly Business Unit Financial Results 表。",
    }

    unit_margin = {
        "ref": "EX_BU_GM",
        "kind": "lines_endlabels",
        "title": (
            f"业务单元毛利率：HBM 最重的云内存 {units['CMBU_gross_margin_pct'][-1]:.0f}%，"
            f"低于核心数据中心与移动客户端的 {units['CDBU_gross_margin_pct'][-1]:.0f}%"
        ),
        "xlabels": unit_labels,
        "series": [
            {"name": "云内存 CMBU", "values": rounded(units["CMBU_gross_margin_pct"]),
             "color": "NAVY"},
            {"name": "核心数据中心 CDBU", "values": rounded(units["CDBU_gross_margin_pct"]),
             "color": "MBLUE"},
            {"name": "移动与客户端 MCBU", "values": rounded(units["MCBU_gross_margin_pct"]),
             "color": "GOLD"},
            {"name": "汽车与嵌入式 AEBU", "values": rounded(units["AEBU_gross_margin_pct"]),
             "color": "ORANGE"},
        ],
        "fmt": "pct0", "yfmt": "pct0", "label_fmt": "pct0",
        "end_label": True,
        "ylab": "毛利率",
        "note": (
            "<b>这一张悄悄证伪了「HBM = 最高利润」的直觉。</b>"
            f"承载 HBM 与高性能云 DRAM 的 CMBU 毛利率 {units['CMBU_gross_margin_pct'][-1]:.0f}%，"
            f"低于不含 HBM 的核心数据中心 {units['CDBU_gross_margin_pct'][-1]:.0f}% "
            f"与移动客户端 {units['MCBU_gross_margin_pct'][-1]:.0f}%；"
            "八个季度里 CMBU 只有前三季领先，此后一路被另外两条超过。"
            "如果 HBM 占比继续按公司说的向 DRAM 占比靠拢，"
            "这张图的读法是：那对合并毛利率是<b>稀释</b>而不是增厚。"
            "<b>这四条是公司自己印出来的百分比</b>（新闻稿里就是整数），不是本页用美元数除出来的；"
            "它们对应的是各单元的口径，与合并 GAAP 毛利率不完全同一定义。"
        ),
        "src_extra": "各季业绩 8-K EX-99.1 的 Quarterly Business Unit Financial Results 表。",
    }

    margins = {
        "ref": "EX_MARGINS",
        "kind": "lines_endlabels",
        "title": (
            f"{len(labels)} 个季度的两条利润率：GAAP 毛利率从 {min(fin['gaap_gross_margin_pct']):.1f}% "
            f"到 {fin['gaap_gross_margin_pct'][-1]:.1f}%"
        ),
        "xlabels": labels,
        "series": [
            {"name": "GAAP 毛利率", "values": rounded(fin["gaap_gross_margin_pct"]),
             "color": "NAVY"},
            {"name": "GAAP 营业利润率", "values": rounded(fin["gaap_operating_margin_pct"]),
             "color": "GOLD"},
        ],
        "fmt": "pct0", "yfmt": "pct0", "label_fmt": "pct0",
        "end_label": True,
        "ylab": "占收入",
        "zero_line": True,
        "note": (
            "<b>这不是一条趋势线，是一个周期的一整程。</b>"
            f"GAAP 毛利率在 {periods[fin['gaap_gross_margin_pct'].index(min(fin['gaap_gross_margin_pct']))]} "
            f"是 {min(fin['gaap_gross_margin_pct']):.1f}%（卖一美元的货亏三成），"
            f"到 {periods[-1]} 是 {fin['gaap_gross_margin_pct'][-1]:.1f}%；"
            "十三个季度走完一百多个百分点。"
            "两条线之间的距离是营业费用占收入的比重，它在整段窗口里几乎没有变化 —— "
            "这家公司的利润率<b>不是</b>被费用管出来的。"
            "零线画出来是因为这条序列真的穿过它："
            f"窗口内有 {sum(1 for v in fin['gaap_operating_margin_pct'] if v < 0)} 个季度营业利润为负。"
        ),
        "src_extra": "毛利率与营业利润率 = 合并损益表的毛利、营业利润各自除以当季收入 D。",
    }

    # ── the earnings-per-share bridge, exact ────────────────────────────────
    prior_gm = fin["non_gaap_gross_margin_usd_m"][-2]
    this_gm = fin["non_gaap_gross_margin_usd_m"][-1]
    prior_opex = fin["non_gaap_operating_expenses_usd_m"][-2]
    this_opex = fin["non_gaap_operating_expenses_usd_m"][-1]
    prior_ni = fin["non_gaap_net_income_usd_m"][-2]
    this_ni = fin["non_gaap_net_income_usd_m"][-1]
    prior_shares = fin["non_gaap_diluted_shares_m"][-2]
    this_shares = fin["non_gaap_diluted_shares_m"][-1]
    prior_eps = fin["non_gaap_diluted_eps_usd"][-2]
    this_eps = fin["non_gaap_diluted_eps_usd"][-1]

    prior_oi = fin["non_gaap_operating_income_usd_m"][-2]
    this_oi = fin["non_gaap_operating_income_usd_m"][-1]
    below_prior = prior_ni - prior_oi
    below_this = this_ni - this_oi

    gm_leg = (this_gm - prior_gm) / this_shares
    opex_leg = -(this_opex - prior_opex) / this_shares
    below_leg = (below_this - below_prior) / this_shares
    share_leg = prior_ni * (1 / this_shares - 1 / prior_shares)
    residual = this_eps - (prior_eps + gm_leg + opex_leg + below_leg + share_leg)

    # `charts.js` skips a bridge segment whose value is exactly zero
    # (`if (!isNum(vb) || vb === 0) continue`), so a leg worth nothing leaves a
    # labelled column with no bar in it -- the chart then contradicts its own
    # axis, which is exactly the defect this repo found on the MCO page. The
    # share-count leg IS exactly zero this quarter (1,149M both quarters), so
    # the column is dropped rather than drawn empty, and the note says why.
    # Filtered generically: if the share count moves next quarter the leg comes
    # back on its own.
    legs = [("毛利变动", gm_leg), ("营业费用变动", opex_leg),
            ("税与线下项变动", below_leg), ("摊薄股数变动", share_leg)]
    drawn = [(name, value) for name, value in legs if round(value, 2) != 0]
    dropped = [name for name, value in legs if round(value, 2) == 0]

    bridge = {
        "ref": "EX_EPS_BRIDGE",
        "kind": "bridge_bar",
        "title": (
            f"non-GAAP 每股收益 US${prior_eps:.2f} → US${this_eps:.2f}："
            f"US${gm_leg:.2f} 来自毛利，其余合计 US${this_eps - prior_eps - gm_leg:+.2f}"
        ),
        "xlabels": ([f"{periods[-2]} non-GAAP EPS"] + [name for name, _ in drawn]
                    + [f"{periods[-1]} non-GAAP EPS"]),
        "stacks": [{"name": "环比拆解", "color": "NAVY",
                    "values": rounded([prior_eps] + [value for _, value in drawn]
                                      + [None])}],
        # `bridgeNet` reads `ex.net.values`, so a BARE LIST here is truthy at
        # `ex.net &&` but yields `undefined` at `.values` -- it falls through to
        # the "no net supplied" branch and sums the stacks instead. The result
        # column has no stack segment (its whole value IS the net), so the sum is
        # null and the diamond is never drawn: a labelled column with nothing in
        # it, under a title that names the number. Same outcome as the zero-leg
        # defect one comment up, reached a different way, and an aggregate
        # "marks == columns" count does NOT see it -- the count came out right
        # while the mark sat in the wrong column. The legend reads
        # `ex.net.name` from the same object.
        "net": {"name": f"{periods[-1]} 结果", "values":
                rounded([None] * (len(drawn) + 1) + [this_eps])},
        "fmt": "usd2", "yfmt": "usd2", "label_fmt": "usd2",
        "ylab": "US$/股",
        "note": (
            f"<b>这一季每股收益增加 US${this_eps - prior_eps:.2f}，其中 "
            f"US${gm_leg:.2f} 是毛利。</b>"
            f"毛利从 US${prior_gm:,.0f}M 到 US${this_gm:,.0f}M，"
            f"营业费用从 US${prior_opex:,.0f}M 到 US${this_opex:,.0f}M，"
            f"税与线下项合计从 US${below_prior:,.0f}M 到 US${below_this:,.0f}M，"
            f"摊薄股数 {prior_shares:,.0f}M → {this_shares:,.0f}M。"
            "<b>没有回购的贡献，也没有一次性收益</b> —— "
            + (f"「{'、'.join(dropped)}」这一项恰好为零（摊薄股数两季都是 "
               f"{this_shares:,.0f}M），所以横轴上没有它的位置；"
               if dropped else "")
            + "线下项那一格是负的（税随利润走）。"
            "各项加上季末每股收益等于本季每股收益，"
            f"残差 US${residual:.4f}，只来自公司各自四舍五入到分与百万。"
        ),
        "src_extra": ("各项均取自业绩 8-K EX-99.1 的 GAAP/non-GAAP 对账表；"
                      "每股口径 = 各项美元数除以当季 non-GAAP 摊薄股数 D。"),
    }

    return [revenue_cogs, technology_chart, unit_revenue, unit_margin, margins, bridge]


# ── section three: what to watch next quarter ───────────────────────────────
def next_quarter_charts(staging: dict) -> list[dict]:
    periods = staging["periods"]
    labels = [compact_period(period) for period in periods]
    fin = staging["financials"]
    bal = staging["balance_sheet"]
    kpi = staging["next_kpi"]["quantified"]
    filed = staging["filed_vs_spoken"]

    margin_line = threshold_exhibit(
        "non-GAAP 毛利率对 84.0% 警戒线：本季 "
        f"{fin['non_gaap_gross_margin_pct'][-1]:.1f}%，下季公司指引约 86%",
        labels,
        rounded(fin["non_gaap_gross_margin_pct"]),
        84.0,
        fmt="pct1",
        ylab="non-GAAP 毛利率",
        actual_name="实际 non-GAAP 毛利率",
        threshold_name="警戒线 84.0%",
        note=(
            f"<b>这条警戒线在 {len(labels)} 个季度里被跨越过两次，方向相反。</b>"
            "深蓝线在 2023 年整整一年待在零以下，随后一路回到 84.9%。"
            "把警戒线设在 84.0% 而不是别的数，是因为公司下季指引约 86%："
            "低于 84% 意味着不是「涨价放缓」而是「指引本身没兑现」，"
            "而 Exhibit {EX_GM_RANGE} 显示这家公司的毛利率指引真的会没兑现。"
        ),
        src_extra="实际值 = 对账表的 non-GAAP 毛利 ÷ 当季收入 D；阈值来自本地分析稿。",
    )
    margin_line["ref"] = "EX_GM_THRESHOLD"

    dso_start = continuous_tail(bal["dso_days"])
    dso_labels = labels[dso_start:]
    dso_days = bal["dso_days"][dso_start:]
    dso_line = threshold_exhibit(
        f"应收账款周转天数对 80 天警戒线：本季 {dso_days[-1]:.1f} 天",
        dso_labels,
        rounded(dso_days),
        80.0,
        fmt="f1",
        ylab="天",
        actual_name="DSO（自算）",
        threshold_name="警戒线 80 天",
        note=(
            "<b>本季应收账款环比增加 "
            f"US${(bal['receivables_usd_m'][-1] - bal['receivables_usd_m'][-2]) / 1000:.1f}B，"
            "看上去像回款恶化，但周转天数说的是另一回事。</b>"
            f"DSO 从 {bal['dso_days'][-2]:.1f} 天走到 {bal['dso_days'][-1]:.1f} 天，只多了 "
            f"{bal['dso_days'][-1] - bal['dso_days'][-2]:.1f} 天；"
            f"而本窗口的最高点是 {dso_labels[dso_days.index(max(dso_days))]} 的 "
            f"{max(dso_days):.1f} 天 —— 也就是说，"
            "<b>应收占用相对收入的水平比两年前还低。</b>"
            "换个说法：如果 DSO 完全不动地停在上季的水平，本季收入也需要 "
            f"US${bal['dso_days'][-2] / bal['days_in_quarter'][-1] * fin['revenue_usd_m'][-1] / 1000:.1f}B "
            f"的应收，实际是 US${bal['receivables_usd_m'][-1] / 1000:.1f}B。"
            "增量的绝大部分来自「卖得多」，不是「收得慢」。"
            "DSO = 期末应收 ÷ 当季收入 × 当季天数，窗口内每一季都是 91 天。"
        ),
        src_extra="应收账款取自各季业绩 8-K EX-99.1 的合并资产负债表；DSO 为自算 D。",
    )
    dso_line["ref"] = "EX_DSO"

    items = filed["items"]
    sca = {
        "ref": "EX_SCA",
        "kind": "grouped_bars",
        "title": (
            "长期供货协议：申报文件里的数与电话会上的数差两个数量级"
        ),
        "xlabels": [item["metric"] for item in items],
        "groups": [
            {"name": "申报值（10-Q）", "color": "NAVY",
             "values": rounded([item["filed_usd_m"] / 1000 for item in items])},
            {"name": "管理层口径（电话会 / 书面发言稿）", "color": "GOLD",
             "values": rounded([item["spoken_usd_m"] / 1000 for item in items])},
        ],
        "bar_labels": True,
        "fmt": "usd1",
        "label_fmt": "usd1",
        "ylab": "US$B",
        "note": (
            "<b>深蓝那两根几乎看不见，而这正是本图要说的事。</b>"
            "截至 2026-05-28 的 10-Q 里，剩余履约义务是 "
            f"US${items[0]['filed_usd_m'] / 1000:.1f}B、合同负债（客户存款）是 "
            f"US${items[1]['filed_usd_m'] / 1000:.3f}B；"
            f"管理层在同一天的电话会上说的是 US${items[0]['spoken_usd_m'] / 1000:.0f}B 与 "
            f"US${items[1]['spoken_usd_m'] / 1000:.0f}B。"
            "<b>两边都不是错的，它们是不同的东西</b>："
            "申报口径只计入季末已签、且有固定价或价格带的协议，按<b>最低承诺量 × 最低合同价</b>计量，"
            "并排除原始期限一年以内的合同；管理层那个数含季末<b>之后</b>签署的协议，"
            "现金存款也要到下一季才陆续入表。"
            "公司自己在 10-Q 里写明这个口径「不代表这些合同下的未来收入」。"
            "<b>本页把两边都画出来，是因为一页只画其中一个都会误导</b> —— "
            "只画申报值会漏掉已经发生的商业事实，只画管理层口径会把还没进报表的东西当成已实现。"
            "上一财年末（2025-08-28）公司称剩余履约义务 not material，所以这条序列只有一个观测点，"
            "下一季的 10-Q 才会给出第二个。"
        ),
        "src_extra": ("申报值取自 10-Q（截至 2026-05-28）Note 14 Revenue and Customer Agreements；"
                      "管理层口径取自 2026-06-24 业绩电话会与公司书面发言稿，已标注为非申报值。"),
    }

    net_cash = {
        "ref": "EX_NETCASH",
        "kind": "bar_line_dual",
        "title": (
            f"净现金 US${bal['net_cash_usd_m'][-1] / 1000:.1f}B，总债务降到 "
            f"US${bal['total_debt_usd_m'][-1] / 1000:.1f}B"
        ),
        "xlabels": labels,
        "xrot": 90,
        "bar": {"name": "净现金（现金及投资 − 总债务）", "color": "NAVY",
                "values": rounded([v / 1000 for v in bal["net_cash_usd_m"]])},
        "line": {"name": "总债务 (RHS)", "color": "RED",
                 "values": rounded([v / 1000 for v in bal["total_debt_usd_m"]]),
                 "yfmt": "usd1"},
        "fmt": "usd1", "yfmt": "usd1", "label_fmt": "usd1",
        "ylab": "US$B", "rhs_label": "US$B",
        "zero_line": True,
        "note": (
            "<b>这张图是上一轮周期留下的账单被还掉的过程。</b>"
            f"净现金在 {periods[bal['net_cash_usd_m'].index(min(bal['net_cash_usd_m']))]} 最低到 "
            f"−US${abs(min(bal['net_cash_usd_m'])) / 1000:.1f}B，"
            f"到本季是 +US${bal['net_cash_usd_m'][-1] / 1000:.1f}B；"
            f"总债务从窗口内最高的 US${max(bal['total_debt_usd_m']) / 1000:.1f}B 降到 "
            f"US${bal['total_debt_usd_m'][-1] / 1000:.1f}B。"
            "本季合并损益表上的<b>利息支出是零</b>（上一季 US$32M，一年前 US$123M）。"
            "读这张图时值得记住 Exhibit {EX_CYCLE}："
            "上一轮下行里这家公司是靠借钱扛过去的，而现在它没有净债务了 —— "
            "这是下一次下行时和上一次最不一样的一件事，"
            "也是唯一一件已经<b>在报表上</b>、不需要相信任何协议条款的事。"
        ),
        "src_extra": ("现金及投资 = 现金及等价物 + 短期投资 + 长期有价投资；"
                      "总债务 = 流动负债端债务 + 长期债务；两者相减为自算 D。"),
    }

    return [margin_line, dso_line, sca, net_cash]


# ── section four: the long routine ──────────────────────────────────────────
def routine_charts(staging: dict) -> list[dict]:
    periods = staging["periods"]
    labels = [compact_period(period) for period in periods]
    fin = staging["financials"]
    bal = staging["balance_sheet"]
    annual = staging["annual_cycle"]

    years = [f"FY{row['fiscal_year']}" for row in annual]
    revenue = [row["revenue_usd_m"] / 1000 for row in annual]
    margin = [row["gross_margin_pct"] for row in annual]
    capex = [row["capital_expenditures_usd_m"] / 1000 for row in annual]
    intensity = [row["capex_intensity_pct"] for row in annual]
    ocf = [row["operating_cash_flow_usd_m"] / 1000 for row in annual]

    worst = min(range(len(margin)), key=lambda i: margin[i])
    best = max(range(len(margin)), key=lambda i: margin[i])

    cycle = {
        "ref": "EX_CYCLE",
        "kind": "bar_line_dual",
        "title": (
            f"十五个财年的营收与毛利率：最低 {margin[worst]:.1f}%（{years[worst]}），"
            f"最高 {margin[best]:.1f}%（{years[best]}）"
        ),
        "xlabels": years,
        "xrot": 90,
        "bar": {"name": "营收", "color": "NAVY", "values": rounded(revenue)},
        "line": {"name": "毛利率 (RHS)", "color": "GOLD",
                 "values": rounded(margin), "yfmt": "pct0"},
        "fmt": "usd1", "yfmt": "usd1", "label_fmt": "usd1",
        "ylab": "US$B", "rhs_label": "毛利率",
        "zero_line": True,
        "note": (
            "<b>本页所有判断都应该放在这张图上读。</b>十五个财年里毛利率的完整区间是 "
            f"{margin[worst]:.1f}% 到 {margin[best]:.1f}%，"
            f"其中 {sum(1 for v in margin if v < 0)} 个财年为负、"
            f"{sum(1 for row in annual if row['operating_margin_pct'] < 0)} 个财年营业利润为负。"
            f"上一轮周期顶（{years[best]}）的毛利率是 {margin[best]:.1f}%，"
            f"而本页最新一季是 {fin['gaap_gross_margin_pct'][-1]:.1f}% —— "
            "<b>比历史上任何一个完整财年都高出二十多个百分点。</b>"
            "这既是「这次不一样」那套说法的全部依据，也是它最大的风险："
            "一个从未在这条序列上出现过的水平，没有历史可以告诉你它能待多久。"
            f"FY2026 只有前三季在表内（营收 US$79.0B、毛利率 76.6%），"
            "本图不画未完结的财年。"
        ),
        "src_extra": "各财年取自该年 10-K 的合并损益表；毛利率 = 毛利 ÷ 营收 D。",
    }

    capex_chart = {
        "ref": "EX_CAPEX",
        "kind": "bar_line_dual",
        "title": (
            f"资本开支与资本强度：{years[-1]} 支出 US${capex[-1]:.1f}B，"
            f"占营收 {intensity[-1]:.1f}%"
        ),
        "xlabels": years,
        "xrot": 90,
        "bar": {"name": "资本开支（购建固定资产的现金支出）", "color": "NAVY",
                "values": rounded(capex)},
        "line": {"name": "资本开支 ÷ 营收 (RHS)", "color": "RED",
                 "values": rounded(intensity), "yfmt": "pct0"},
        "fmt": "usd1", "yfmt": "usd1", "label_fmt": "usd1",
        "ylab": "US$B", "rhs_label": "资本强度",
        "note": (
            "<b>红线才是这张图的主角。</b>十五个财年里资本强度的区间是 "
            f"{min(intensity):.1f}%（{years[intensity.index(min(intensity))]}）到 "
            f"{max(intensity):.1f}%（{years[intensity.index(max(intensity))]}），"
            "而它的高点<b>全部落在营收的低点上</b> —— "
            f"{years[intensity.index(max(intensity))]} 那一年营收 US${revenue[intensity.index(max(intensity))]:.1f}B、"
            f"毛利率 {margin[intensity.index(max(intensity))]:.1f}%，"
            "支出却是营收的一半。这是内存行业最难的一件事：产能要在看不见需求的时候建。"
            "管理层已经说 FY2027 的资本开支会「高于 mid-40s」（约 450 亿美元以上），"
            "而 FY2025 是 US$15.9B —— <b>那个数只在电话会上给过，没有出现在任何申报文件里</b>，"
            "所以本图不画它；等 FY2026 的 10-K 出来，这条柱子才会有第十六格。"
        ),
        "src_extra": "各财年现金流量表的「购建固定资产支出」；资本强度为自算 D。",
    }

    fcf = fin["adjusted_free_cash_flow_usd_m"]
    deepest = min(v for v in fcf if v is not None)

    cash_generation = {
        "ref": "EX_CASHGEN",
        "kind": "grouped_bars",
        "title": (
            f"{len(labels)} 季的现金三条：经营现金流 US${fin['operating_cash_flow_usd_m'][-1] / 1000:.1f}B、"
            f"净资本开支 US${abs(fin['capex_net_usd_m'][-1]) / 1000:.1f}B、"
            f"调整后自由现金流 US${fcf[-1] / 1000:.1f}B"
        ),
        "xlabels": labels,
        "xrot": 90,
        "groups": [
            {"name": "经营现金流", "color": "NAVY",
             "values": rounded(billions(fin["operating_cash_flow_usd_m"]))},
            {"name": "净资本开支（公司口径）", "color": "RED",
             "values": rounded(billions(fin["capex_net_usd_m"]))},
            {"name": "调整后自由现金流（公司口径）", "color": "GOLD",
             "values": rounded(billions(fin["adjusted_free_cash_flow_usd_m"]))},
        ],
        "bar_labels": False,
        "fmt": "usd1",
        "label_fmt": "usd1",
        "ylab": "US$B",
        "zero_line": True,
        "note": (
            "<b>三条都是公司自己印在业绩稿里的口径，不是本页凑的。</b>"
            "公司定义的「净资本开支」= 购建固定资产支出 − 出售固定资产所得 − 收到的政府补助，"
            "「调整后自由现金流」= 经营现金流 − 净资本开支；"
            f"窗口内有 {sum(1 for v in fcf if v is not None and v < 0)} 个季度"
            "调整后自由现金流为负，最深的一次是 "
            f"{periods[fcf.index(deepest)]} 的 −US${abs(deepest) / 1000:.1f}B。"
            "<b>红色那条有两格是空的</b>（2016 年第一、二季）：公司「扣除合作方出资后」"
            "这个口径的措辞最早出现在 2016-10-04 那份发布里，更早两份只印毛额，"
            "10-Q 也只给毛额的年初至今数，所以那两季没有可读的净值，本页不用毛额顶替 —— "
            "在此之前它们装的正是毛额，两个不同的计量摆在同一行上。"
            "<b>另外，「等式逐季闭合」不是一次检验</b>：调整后自由现金流本页就是由"
            "另外两条相减得到的，所以它必然闭合，看不出资本开支那一行装的是哪个口径。"
            "<b>注意红色那条在整段窗口里几乎是平的</b>：资本开支并没有跟着现金流一起暴涨，"
            "所以本季 US$18.3B 的自由现金流几乎全部来自经营端。"
            "这也是 Exhibit {EX_CAPEX} 那句话的季度版本 —— 支出的拐点还没到表里来。"
        ),
        "src_extra": "2018 年第一季度起取自各季业绩 8-K EX-99.1 的非 GAAP 对账表；更早的六季该表尚不存在，净资本开支取自同一份发布正文里公司自己写的那句「扣除合作方出资后……」（三位有效数字），调整后自由现金流按同两条相减得到。",
    }

    # Inventory days shares cost of goods sold's eighteen-quarter hole, so this
    # pair is drawn over the tail where both legs exist.
    dio_start = continuous_tail(bal["dio_days"])
    inv_labels = labels[dio_start:]
    inv_days = bal["dio_days"][dio_start:]
    inv_level = bal["inventories_usd_m"][dio_start:]
    inv_revenue = fin["revenue_usd_m"][dio_start:]
    inventory = {
        "ref": "EX_INVENTORY",
        "kind": "bar_line_dual",
        "title": (
            f"存货 US${inv_level[-1] / 1000:.1f}B、存货天数 "
            f"{inv_days[-1]:.0f} 天：{len(inv_labels)} 季里收入 "
            f"{signed(pct_change(inv_revenue[-1], inv_revenue[0]), 0)}，"
            f"存货 {signed(pct_change(inv_level[-1], inv_level[0]), 0)}"
        ),
        "xlabels": inv_labels,
        "xrot": 90,
        "bar": {"name": "期末存货", "color": "NAVY",
                "values": rounded([v / 1000 for v in inv_level])},
        "line": {"name": "存货天数 DIO (RHS)", "color": "GOLD",
                 "values": rounded(inv_days), "yfmt": "f0"},
        "fmt": "usd1", "yfmt": "usd1", "label_fmt": "usd1",
        "ylab": "US$B", "rhs_label": "天",
        "note": (
            "<b>存货这条柱子近两年是平的，而它本来最该动。</b>"
            f"从 {periods[0]} 到 {periods[-1]}，收入涨了 "
            f"{pct_change(fin['revenue_usd_m'][-1], fin['revenue_usd_m'][0]):.0f}%（"
            f"{fin['revenue_usd_m'][-1] / fin['revenue_usd_m'][0]:.1f} 倍），"
            f"期末存货从 US${bal['inventories_usd_m'][0] / 1000:.1f}B 只走到 "
            f"US${bal['inventories_usd_m'][-1] / 1000:.1f}B。"
            f"存货天数的高点在 {inv_labels[inv_days.index(max(inv_days))]}，"
            f"{max(inv_days):.0f} 天 —— 那是上一轮下行最深的时候，"
            "货堆在仓库里而收入在掉；现在是 "
            f"{inv_days[-1]:.0f} 天。"
            "<b>存货天数用销货成本作分母</b>（期末存货 ÷ 当季销货成本 × 当季天数），"
            "所以它不受售价暴涨的影响，这一点在本页尤其要紧："
            "换成用收入作分母，同一组数字会显示存货天数「腰斩」，那只是价格的影子。"
        ),
        "src_extra": "存货取自各季业绩 8-K EX-99.1 的合并资产负债表；存货天数为自算 D。",
    }

    return [cycle, capex_chart, cash_generation, inventory]


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    fin = staging["financials"]
    bal = staging["balance_sheet"]
    tech = staging["technology"]
    units = staging["business_units"]
    record = staging["quarterly_guidance_history"]
    outlook = staging["next_quarter_guidance"]
    annual = staging["annual_cycle"]

    settled_ex, delivery_table, tallies = guidance_delivery_charts(staging)
    rev_n, rev_above, rev_inside, rev_below = tallies["revenue"]
    gm_n, gm_above, gm_inside, gm_below = tallies["gross_margin"]
    worst_gap = tallies["worst_gap"]
    highlight_ex = quarter_charts(staging)
    next_ex = next_quarter_charts(staging)
    routine_ex = routine_charts(staging)

    exhibits = settled_ex + highlight_ex + next_ex + routine_ex
    number_exhibits(exhibits)
    resolve_exhibit_refs(exhibits)
    settled_ex = exhibits[:len(settled_ex)]
    highlight_ex = exhibits[len(settled_ex):len(settled_ex) + len(highlight_ex)]
    next_ex = exhibits[len(settled_ex) + len(highlight_ex):
                       len(settled_ex) + len(highlight_ex) + len(next_ex)]
    routine_ex = exhibits[len(settled_ex) + len(highlight_ex) + len(next_ex):]

    first_table = exhibits[-1]["n"] + 1

    guidance = {
        "title": f"下季指引（{outlook['period_label']}，公司称 {outlook['fiscal_label']}）",
        "headers": ["指标", "GAAP 指引", "non-GAAP 指引", "隐含环比"],
        "rows": [
            ["收入",
             f"US${outlook['revenue_usd_m'] / 1000:.1f}B ± US${outlook['revenue_band_usd_m'] / 1000:.1f}B",
             f"US${outlook['revenue_usd_m'] / 1000:.1f}B ± US${outlook['revenue_band_usd_m'] / 1000:.1f}B",
             f"{pct_change(outlook['revenue_usd_m'], fin['revenue_usd_m'][-1]):+.1f}%"],
            ["毛利率",
             f"约 {outlook['gaap_gross_margin_pct']:.1f}%",
             f"约 {outlook['non_gaap_gross_margin_pct']:.1f}%",
             f"{outlook['non_gaap_gross_margin_pct'] - fin['non_gaap_gross_margin_pct'][-1]:+.1f}pp"],
            ["营业费用",
             f"约 US${outlook['gaap_opex_usd_m']:,.0f}M",
             f"约 US${outlook['non_gaap_opex_usd_m']:,.0f}M",
             f"{pct_change(outlook['non_gaap_opex_usd_m'], fin['non_gaap_operating_expenses_usd_m'][-1]):+.1f}%"],
            ["摊薄每股收益",
             f"US${outlook['gaap_eps_usd']:.2f} ± US${outlook['eps_band_usd']:.2f}",
             f"US${outlook['non_gaap_eps_usd']:.2f} ± US${outlook['eps_band_usd']:.2f}",
             f"{pct_change(outlook['non_gaap_eps_usd'], fin['non_gaap_diluted_eps_usd'][-1]):+.1f}%"],
        ],
        "note": (
            "毛利率与营业费用是单点数（公司写的是 Approximately），不是区间；收入与每股收益是区间。"
            "本表按公司在 2026-06-24 业绩新闻稿里的 Business Outlook 原样转录，"
            "隐含环比为自算。指引以约 11.5 亿股摊薄股数为基础。"
        ),
    }

    kpi = staging["next_kpi"]
    core_rows = []
    for index in range(-8, 0):
        core_rows.append([
            periods[index],
            staging["fiscal_labels"][index],
            staging["period_ends"][index],
            f"US${fin['revenue_usd_m'][index]:,.0f}M",
            (f"{fin['revenue_qoq_pct'][index]:+.1f}%"
             if fin["revenue_qoq_pct"][index] is not None else "—"),
            f"US${fin['cost_of_goods_sold_usd_m'][index]:,.0f}M",
            f"{fin['gaap_gross_margin_pct'][index]:.2f}%",
            f"{fin['non_gaap_gross_margin_pct'][index]:.2f}%",
            f"{fin['gaap_operating_margin_pct'][index]:.2f}%",
            f"US${fin['gaap_diluted_eps_usd'][index]:.2f}",
            f"US${fin['non_gaap_diluted_eps_usd'][index]:.2f}",
            f"US${fin['operating_cash_flow_usd_m'][index]:,.0f}M",
            f"US${fin['adjusted_free_cash_flow_usd_m'][index]:,.0f}M",
            f"US${bal['net_cash_usd_m'][index]:,.0f}M",
        ])

    unit_rows = []
    for index, quarter in enumerate(units["quarters"]):
        row = [quarter, units["fiscal_labels"][index]]
        for unit in ("CMBU", "CDBU", "MCBU", "AEBU"):
            row.append(f"US${units[f'{unit}_revenue_usd_m'][index]:,.0f}M")
            row.append(f"{units[f'{unit}_gross_margin_pct'][index]:.0f}%")
            row.append(f"{units[f'{unit}_operating_margin_pct'][index]:.0f}%")
        unit_rows.append(row)

    annual_rows = []
    for row in annual:
        annual_rows.append([
            f"FY{row['fiscal_year']}",
            row["fiscal_year_end_date"],
            f"{row['weeks_in_year']} 周",
            f"US${row['revenue_usd_m']:,.0f}M",
            f"{row['gross_margin_pct']:.2f}%",
            f"{row['operating_margin_pct']:.2f}%",
            f"US${row['diluted_eps_usd']:.2f}",
            f"US${row['operating_cash_flow_usd_m']:,.0f}M",
            f"US${row['capital_expenditures_usd_m']:,.0f}M",
            f"{row['capex_intensity_pct']:.2f}%",
            f"US${row['inventories_usd_m']:,.0f}M",
            f"US${row['total_debt_usd_m']:,.0f}M",
        ])

    technology_rows = []
    for index in range(-8, 0):
        technology_rows.append([
            periods[index],
            f"US${tech['dram_revenue_usd_m'][index]:,.0f}M",
            f"{tech['dram_share_pct'][index]:.1f}%",
            f"US${tech['nand_revenue_usd_m'][index]:,.0f}M",
            f"{tech['nand_share_pct'][index]:.1f}%",
            f"US${tech['other_revenue_usd_m'][index]:,.0f}M",
            tech["dram_asp_text"][index] or "—",
            tech["dram_bit_text"][index] or "—",
            tech["nand_asp_text"][index] or "—",
            tech["nand_bit_text"][index] or "—",
        ])

    kpi_rows = [[
        item["metric"],
        "高于阈值为安全" if item["direction"] == "up" else "低于阈值为安全",
        unit_text("pct" if item["unit"] == "pct" else "days", item["threshold"]),
        unit_text("pct" if item["unit"] == "pct" else "days", item["current"]),
        f"{headroom(item['direction'], item['threshold'], item['current']):+.1f}%",
        "本页作图",
    ] for item in kpi["quantified"]]
    for reason in kpi["excluded"]:
        kpi_rows.append([reason.split("（")[0], "—", "—", "—", "—", "本页不作图，原因见左"])

    filed_rows = []
    for item in staging["filed_vs_spoken"]["items"]:
        filed_rows.append([
            item["metric"],
            f"US${item['filed_usd_m']:,.0f}M",
            item["filed_source"],
            f"US${item['spoken_usd_m']:,.0f}M",
            item["spoken_basis"],
        ])

    tables = [
        {**delivery_table, "n": first_table},
        {
            "n": first_table + 1,
            "title": "八季核心（自然年季度标注；公司财季见第二列）",
            "headers": ["自然年季度", "公司财季", "季末", "收入", "环比", "销货成本",
                        "GAAP 毛利率", "non-GAAP 毛利率", "GAAP 营业利润率",
                        "GAAP 每股收益", "non-GAAP 每股收益", "经营现金流",
                        "调整后自由现金流", "净现金"],
            "rows": core_rows,
        },
        {
            "n": first_table + 2,
            "title": "八季按技术拆分，以及公司对价与量的原始措辞",
            "headers": ["自然年季度", "DRAM 收入", "DRAM 占比", "NAND 收入", "NAND 占比",
                        "其他", "DRAM 售价（公司原话）", "DRAM 出货位元（公司原话）",
                        "NAND 售价（公司原话）", "NAND 出货位元（公司原话）"],
            "rows": technology_rows,
        },
        {
            "n": first_table + 3,
            "title": "业务单元八季（公司自 FY2025 Q4 业绩稿起披露的四单元口径）",
            "headers": ["自然年季度", "公司财季",
                        "CMBU 收入", "CMBU 毛利率", "CMBU 营业利润率",
                        "CDBU 收入", "CDBU 毛利率", "CDBU 营业利润率",
                        "MCBU 收入", "MCBU 毛利率", "MCBU 营业利润率",
                        "AEBU 收入", "AEBU 毛利率", "AEBU 营业利润率"],
            "rows": unit_rows,
        },
        {
            "n": first_table + 4,
            "title": "十五财年记录（各年取该年 10-K 印出的数）",
            "headers": ["财年", "财年末", "周数", "营收", "毛利率", "营业利润率",
                        "摊薄每股收益", "经营现金流", "资本开支", "资本强度",
                        "期末存货", "总债务"],
            "rows": annual_rows,
        },
        {
            "n": first_table + 5,
            "title": "下季阈值：哪些本页能作图，哪些不能",
            "headers": ["指标", "方向", "阈值", "当前值", "余量 D", "本页处理"],
            "rows": kpi_rows,
        },
        {
            "n": first_table + 6,
            "title": "长期供货协议：申报值与管理层口径逐项对照",
            "headers": ["项目", "申报值", "申报出处", "管理层口径", "管理层口径的说明"],
            "rows": filed_rows,
        },
        # The one object published byte-identically on every page. Micron is
        # neither a column in it nor on the chain it draws -- it sits upstream
        # of all four, which is exactly why it is not added: the table has to
        # stay identical on all twenty-six pages, and a column here would
        # rewrite it everywhere.
        ai_capex_cycle_table(first_table + 7),
    ]

    revenue = fin["revenue_usd_m"]
    cogs = fin["cost_of_goods_sold_usd_m"]
    # The worst gross-margin quarter of the guided record, recounted here rather
    # than pinned by index: an index is correct until the record grows at the
    # front, and then it silently names a different quarter.
    worst = min(
        (index for index, value in enumerate(record["actual_non_gaap_gross_margin_pct"])
         if value is not None),
        key=lambda index: (record["actual_non_gaap_gross_margin_pct"][index]
                           - record["guide_non_gaap_gross_margin_pct"][index]),
    )

    return {
        "schema_version": "quarterly-dashboard/mu-v1",
        "page": {"slug": "mu", "language": "zh-CN"},
        "company": {
            "ticker": "MU",
            "name": "Micron Technology, Inc.",
            "group": "semiconductor_ai",
            "accounting_standard": "US GAAP",
        },
        "latest": {
            "disclosed_period_label": "Q2 2026",
            "full_financial_period_label": "Q2 2026",
            "period_end": "2026-05-28",
            "release_date": "2026-06-24",
            "analysis_date": "2026-08-29",
            "audit_status": "unaudited",
            "status": "history_ready",
        },
        "tracker": "Watchlist Quarterly Tracker · MU",
        "title": "Micron Technology (MU)：Q2 2026 季报仪表盘",
        "subtitle": (
            "季度截至 2026-05-28 · 发布 2026-06-24 · US GAAP · 未审计 · "
            "财年末为最接近 8 月 31 日的星期四（申报人记录 09-03，FY2026 即 2026-09-03），"
            "本站按自然年季度标注：本页 Q2 2026 即公司所称 FY2026 Q3"
        ),
        "headline": (
            f"收入 US${revenue[-1]:,.0f}M、环比 {signed(fin['revenue_qoq_pct'][-1])}，"
            f"non-GAAP 毛利率 {fin['non_gaap_gross_margin_pct'][-1]:.1f}%、"
            f"每股收益 US${fin['non_gaap_diluted_eps_usd'][-1]:.2f} 双双创纪录；"
            f"但同一张损益表上销货成本环比只有 {signed(fin['cost_of_goods_sold_qoq_pct'][-1])}，"
            f"而这家公司三年前刚把自己 {record['guide_non_gaap_gross_margin_pct'][worst]:.1f}% 的"
            f"毛利率指引报成 {record['actual_non_gaap_gross_margin_pct'][worst]:.1f}%。"
        ),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>算术</span><b>涨的是价，不是量</b>'
            f'<p>一年之间收入 {signed(pct_change(revenue[-1], revenue[-5]), 0)}，'
            f'销货成本 {signed(pct_change(cogs[-1], cogs[-5]), 0)}；'
            f'最近一季收入环比 {signed(fin["revenue_qoq_pct"][-1], 0)}，'
            f'销货成本环比 {signed(fin["cost_of_goods_sold_qoq_pct"][-1], 0)}。'
            '两条都是同一张损益表上的申报值，'
            '公司对售价与出货位元只给文字口径，本页不把文字折成数字。</p></article>'
            '<article><span>记录</span><b>它的指引两个方向都破过</b>'
            f'<p>{gm_n} 个已完结季里，non-GAAP 毛利率指引 {gm_above} 季穿出上限、'
            f'{gm_inside} 季落在区间内、{gm_below} 季跌破下限，'
            f'最差的一次差 {abs(worst_gap):.0f} 个百分点。'
            f'同样 {rev_n} 季，收入指引 {rev_above} 季穿出上限、'
            f'{rev_inside} 季落在区间内、{rev_below} 季跌破下限 —— '
            '接近一半一半，不是底线。</p></article>'
            '<article><span>口径</span><b>协议：申报 US$5.0B，口头 US$100B</b>'
            '<p>10-Q 里的剩余履约义务是 50 亿美元、客户存款 4.22 亿美元；'
            '管理层同日在电话会上说的是 1,000 亿与 220 亿。'
            '两个数都对，量的是不同的东西。</p></article>'
            '</div>'
        ),
        "source": (
            'Source: <a href="https://www.sec.gov/Archives/edgar/data/723125/'
            '000072312526000013/a2026q3ex991-pressrelease.htm" rel="noopener">Micron FY2026 Q3 '
            '业绩新闻稿（8-K EX-99.1）</a>与截至 2026-05-28 的 10-Q。'
        ),
        "source_url": (
            "https://www.sec.gov/Archives/edgar/data/723125/"
            "000072312526000013/a2026q3ex991-pressrelease.htm"
        ),
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": guidance,
        "sections": [
            {
                "id": "settled",
                "title": "一、上季兑现与指引记录",
                "description": (
                    "公司每季在业绩新闻稿的 Business Outlook 表里给出下一季的收入、毛利率、"
                    "营业费用与每股收益，GAAP 与 non-GAAP 两栏并列，这份记录能一直回到 2019 年。"
                    "本节先把这份记录读完再看新数字 —— 因为它是本站唯一一份"
                    "两个方向都被打破过、且打破幅度以十个百分点计的指引记录。"
                    "另外：这些区间是在被指引的那个季度开始之后才发布的，这一点写在每张图上。"
                ),
                "exhibits": settled_ex,
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": (
                    "收入与销货成本的分岔、按技术与按业务单元的两种拆法、"
                    "十九个季度的利润率轨迹，以及每股收益从上季到本季的完整桥。"
                    "公司对价格与出货量只给定性措辞，本页把原话放进核对表，不折算成数字。"
                ),
                "exhibits": highlight_ex,
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": (
                    "两条能从 Micron 自己的申报文件算出水平的阈值，各自画在自己的历史上；"
                    "长期供货协议的申报值与管理层口径并列；以及这轮周期里唯一已经落到报表上的"
                    "结构性变化 —— 净现金转正。不能作图的阈值列在核对抽屉里并说明原因。"
                ),
                "exhibits": next_ex,
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": (
                    "十五个财年的营收与毛利率、资本开支与资本强度，"
                    "以及十九个季度的现金三条与存货。这一节存在的理由是给上面三节一个纵深："
                    "本季的每一个纪录都要放在一条走过两次负毛利率的序列上读。"
                ),
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "本页所有季度按自然年标注。Micron 财年在最接近 8 月 31 日的那个星期四结束，故本页的 Q2 2026 是截至 2026-05-28 的季度，公司自己称之为 FY2026 Q3；映射规则为公司 FY(N) 的 Q1 即本页的 Q4 (N−1)，FY(N) 的 Q2/Q3/Q4 即本页的 Q1/Q2/Q3 (N)。不统一成一种约定，跨公司对照就会把不同的三个月放在一起比较。",
            "季度数值逐季读自 SEC EDGAR 上 Micron（CIK 723125）的 36 份季度业绩 8-K EX-99.1 新闻稿。每份新闻稿并排印出三个季度（本季、上季、去年同季）与三个资产负债表日期，所以除最新一季外的每个季度都被两到三份不同的文件各读了一遍；读数不一致的地方按最新一份为准并已逐条记录，本窗口内的分歧只出现在「其他经营（收益）费用」一行（各期在「重组与资产减值」和「其他经营」两行之间的归类不同）与 FY2021 年报对 FY2020 存货的重分类。",
            "因为上一条，本页不发布「其他经营（收益）费用」这一行本身，只发布它的合计值，且合计值取自恒等式：毛利 − 研发 − 销售管理及行政 − 营业利润。这个合计在每个季度、每份新闻稿里都精确闭合。",
            "第一节的指引兑现组图用的是同一批业绩 8-K：每份 EX-99.1 里那张 Business Outlook 表用同一种句式给出下一季的收入、毛利率、营业费用与每股收益；实际值取自随后一季 8-K 的合并损益表与 GAAP/non-GAAP 对账表。毛利率与营业费用在最近两季改为单点数（Approximately），图上按零宽度的区间画，核对表里标注了哪几季是单点。",
            "Micron 的下一季指引随上一季业绩一起发布，而它在季末约四周后发业绩，因此这张 Outlook 表落在它所指引的那个季度之内：本记录里最早第 18 天、最晚第 35 天、中位数第 26 天。这不是一份事前预测，命中率必须连同这句话一起读。",
            "本页不发布任何由公司定性措辞折算出来的数字。Micron 对售价与出货位元只给区间性措辞（如「low-60% range」「mid-single-digit percentage range」），把这类措辞换算成一个百分比需要自选一个中点，那是假设不是算术。原话逐季收在核对抽屉的技术拆分表里；本页用来说明同一件事的，是收入与销货成本这两条申报值。",
            "按技术拆分的 DRAM / NAND / 其他三行取自各季 10-Q、10-K 收入注释里印出的美元数（Revenue by Technology），不是用百分比乘总额倒推的；三行之和逐季等于合并损益表的收入，差额为零。",
            "业务单元序列只有八个季度，因为公司从 FY2025 Q4 那份业绩新闻稿起才在稿里印出这张四单元表（CMBU / CDBU / MCBU / AEBU），此前的业绩稿没有分部表，而更早的分部是 CNBU / MBU / SBU / EBU 四个不同口径。两套口径不可拼接，本页不往前补。各单元的毛利率与营业利润率是公司印出来的整数百分比，不是本页用美元数除出来的。",
            "「调整后自由现金流」与「净资本开支」是公司自己的口径，不是本页的定义：净资本开支 = 购建固定资产支出 − 出售固定资产所得 − 收到的政府补助；调整后自由现金流 = 经营现金流 − 净资本开支。十九个季度逐季验算，全部闭合。",
            "长期供货协议一图把申报值与管理层口径并列，并逐项标明出处。申报口径只计入季末已签、有固定价或价格带的协议，按最低承诺量乘最低合同价计量，并排除原始期限一年以内的合同；公司在 10-Q 里明确写明该口径不代表这些合同下的未来收入。管理层口径含季末之后签署的协议。本页不发布这两者的差额，也不发布任何由此推出的收入覆盖率。",
            "上一季本地分析稿设下七条观察指标，其中只有两条能约化成一个可以从 Micron 自己的申报文件算出的水平（non-GAAP 毛利率、DSO），本页各画一张。其余五条要么是跨季条件、要么依赖公司从不给的数字、要么需要另外几家公司的申报值，全部列在核对抽屉里并写明原因，不作图也不折算。因为可作图的只有两条，本页没有其他公司页上那张「距阈值余量」的横向对比图 —— 两根柱子不构成一个分布。",
            "存货天数用销货成本作分母（期末存货 ÷ 当季销货成本 × 当季天数），不是用收入。在本页这一点尤其要紧：售价在窗口内涨了数倍，换成收入作分母会显示存货天数腰斩，那只是价格的影子而不是周转的改善。窗口内每个季度都是 91 天，取自申报的两个期末日期之差。",
            "十五财年记录中的每一年取自该财年自己的 10-K，不取自后来年报里的比较列。FY2026 只有前三季在表内，本页不画未完结的财年，也不把三季年化。",
            "核对抽屉最后那张「AI capex 循环」是全站逐字节一致的跨页对照块，不是对 Micron 的判断：它把四家云厂的现金资本开支、NVDA 的数据中心收入与 TSM 的晶圆季度串成一条链。Micron 在这条链的更上游 —— 它是内存供给方 —— 但本页刻意没有把它加成这张表的一列：那张表必须在每一页上逐字节相同，加一列等于改掉现存所有页面的同一张表。本站有若干页同样只是承载它而不出现在它的列里（Cadence、Synopsys、TSMC、NVIDIA 都是如此，且有测试专门钉住这一点）。",
            "本页只发布公司披露值、可复算的简单派生值，以及明确标注为管理层口径（非申报）的数字；D 标记代表 Derived / 自算。",
            "本页不发布评级、目标价、估值倍数或任何市场预期数字。",
            "本页已知未接入：HBM 单产品的收入与利润率（公司从未披露）、Micron 在中国的收入敞口（连续两季被问到、连续两季未量化）、FY2027 的资本开支金额（只在电话会上给过区间性措辞，没有出现在任何申报文件里）、按地域的收入拆分（季报口径不披露）、以及十六份长期供货协议的份数与客户构成（只在电话会上给过）。",
            "业绩电话会文字稿仅链接官方 IR 与 SEC 托管版本，公开仓不复制原件或逐字内容。",
        ],
        "footer": "Micron quarterly results · 数据来自 Micron Technology 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "mu.js"), payload, "mu")
    shell_dir = ROOT / "mu"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("MU", "mu"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(
        f"MU page: {charts} charts in {len(payload['sections'])} sections "
        f"+ {len(payload['tables'])} audit tables"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
