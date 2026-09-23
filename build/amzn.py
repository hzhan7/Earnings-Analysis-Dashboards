#!/usr/bin/env python3
"""Build the Amazon quarterly-results page.

Same four-part, chart-led shape as the other pages (上季兑现 → 本季重点 →
下季跟踪 → 长期常规).  Section one is built out further than most, because
Amazon puts a range for two metrics -- net sales and operating income -- into
the `Financial Guidance` block of every quarterly earnings 8-K's EX-99.1, in the
same sentence structure, without a break since at least the Q4 2015 release.
Microsoft's release says in as many words that guidance is given on the call;
Alphabet gives no quarterly numbers at all.

Neither range has been missed at the bottom, and the decomposition says which
half of the guidance is the conservative one.  Guiding both a level and a
profit implies an operating margin Amazon never prints, and the distance from
what it reported splits exactly two ways -- a revenue leg and a margin leg.
The counts, the exceptions and every sentence resting on them are computed from
`quarterly_guidance_history`; nothing about the record is typed here.  The
first version of this file typed them ("21 of 36 above the top") and they went
stale the day the record was backfilled to 2016.

**Rolling the page is a data edit** (`series/amzn.json` only): append a cell to
the aligned arrays, restamp `latest`, and replace the blocks stamped with a
quarter (`board.stamped_block`) -- the snapshot, the one-off items, the story of
the non-operating line, the backlog concentration, the release's forward block,
the calendar shift, the market expectation, both threshold sets, the quarter
story and the errata.  A block stamped with another quarter stops the build; a
missing block leaves its part of the page out.

Published numbers are company-reported or transparent arithmetic.  Market
expectations are labelled as such, with no broker attribution.  Ratings, target
prices and valuation stay off the page.
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
    cn_count,
    cn_fraction,
    cn_ordinal,
    delivery_band,
    fill_story,
    headroom,
    headroom_exhibit,
    latest_block,
    midpoint_deviation,
    number_exhibits,
    stamped_block,
    unit_text,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "amzn.json"
DATA_DIR = ROOT / "data"

WINDOW = 8          # quarters drawn on the short charts
LONG_STEP = 4       # one x label per year on the ten-year axis
DEVIATION_WINDOW = 20
# Consecutive year-on-year rises that make a run worth naming.  Alphabet's page
# uses the same three.
ACCELERATION_EPISODE = 3
# The operating tax rates the per-share conversion of the pre-tax figure assumes.
TAX_RANGE_PCT = (21, 24)
# The previous capex cycle, as history: the 2020 build-out through the 2023
# trough in capital intensity.  A fact about the past, not a parameter of the
# quarter; the peaks and troughs inside it are read from the data.
PREVIOUS_CYCLE = ("2020Q1", "2023Q4")
# The one year whose narrow guide-to-actual margin gap the page glosses.
COST_SHOCK_YEAR = 2022

AUDIT_WORDS = {"unaudited": "未审计", "audited": "已审计"}
# Quarters of the fiscal year elapsed → (the elapsed part, the rest).
YTD_WORDS = {1: ("一季度", "后三季"), 2: ("上半年", "下半年"), 3: ("前三季度", "第四季度")}
LINE_SHORT = {
    "advertising_services": "广告",
    "online_stores": "在线商店",
    "third_party_seller_services": "第三方卖家",
    "subscription_services": "订阅服务",
}

SOURCE_8K = (
    "指引区间来自各季业绩 8-K 的 EX-99.1「Financial Guidance」段；"
    "实际值来自随后一季 8-K 的合并损益表。"
)


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100


def compact_period(period: str) -> str:
    """``'Q1 2026'`` → ``'Q1'26'``."""
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


def compact_long(quarter: str) -> str:
    """``'2016Q1'`` → ``'Q1'16'``, matching the short charts' labels."""
    year, number = quarter.split("Q")
    return f"Q{number}'{year[-2:]}"


def quarter_key(period: str) -> str:
    """``'Q2 2026'`` → ``'2026Q2'``, the spelling `long_history` uses."""
    quarter, year = period.split()
    return f"{year}{quarter}"


def rounded(values: list[float | None], digits: int = 6) -> list[float | None]:
    return [None if value is None else round(value, digits) for value in values]


def yoy(values: list[float | None]) -> list[float | None]:
    """Year-over-year in percent, None until a year-ago quarter exists."""
    out: list[float | None] = [None] * 4
    for index in range(4, len(values)):
        base, current = values[index - 4], values[index]
        out.append(None if base in (None, 0) or current is None
                   else (current / base - 1) * 100)
    return out


def sequential(values: list[float | None]) -> list[float | None]:
    """Quarter-over-quarter absolute change, in the units given."""
    return [None] + [
        None if previous is None or current is None else current - previous
        for previous, current in zip(values, values[1:])
    ]


def leading_gap(values: list[float | None]) -> int:
    """Index of the first reported value; ``len(values)`` when there is none."""
    return next((i for i, value in enumerate(values) if value is not None), len(values))


def years_of(quarters: int) -> str:
    """A window's length in whole years, in words: 38 quarters → 「十」."""
    return cn_count(max(round(quarters / 4), 1))


def runs(flags: list[bool]) -> list[tuple[int, int]]:
    """Maximal runs of True, as (first, last) index pairs."""
    out, start = [], None
    for index, flag in enumerate(flags + [False]):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            out.append((start, index - 1))
            start = None
    return out


def span_label(labels: list[str], first: int, last: int) -> str:
    return labels[first] if first == last else f"{labels[first]}–{labels[last]}"


def money_bn(value_usd_m: float, digits: int = 1) -> str:
    """US$M → ``'−US$7.6B'`` with the page's minus sign."""
    return f"{'−' if value_usd_m < 0 else ''}US${abs(value_usd_m) / 1000:.{digits}f}B"


def paren_bn(value_bn: float) -> str:
    """A guided bound as the release prints it: ``$0`` or ``US$(1.5)B``."""
    if value_bn == 0:
        return "$0"
    return f"US$({abs(value_bn):.1f})B" if value_bn < 0 else f"US${value_bn:.1f}B"


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


def source_note(detail: str) -> str:
    return f"{detail}；历史期同口径。自算项目均可在表格视图核对。"


def source_for(staging: dict, label: str) -> dict:
    """The series' `sources` entry with this label, or a roll error naming it."""
    item = next((entry for entry in staging["sources"] if entry["label"] == label), None)
    if item is None:
        raise ValueError(f"series `sources` has no {label!r}")
    return item


def release_source(staging: dict, period: str) -> dict:
    """This quarter's earnings release in `sources`; a roll that forgot it stops here."""
    item = next((entry for entry in staging["sources"]
                 if entry["label"].startswith(f"{period} 业绩 8-K")), None)
    if item is None:
        raise ValueError(f"series `sources` has no {period} 业绩 8-K: add the quarter's release "
                         "with the roll")
    return item


# ── section one: the guided record ──────────────────────────────────────────
def guidance_delivery_charts(staging: dict) -> tuple[list[dict], dict]:
    """The full guided record for both guided metrics, and its two legs.

    Amazon guides a net-sales range and an operating-income range in every
    quarterly earnings release, so "did the quarter clear the company's own bar"
    has a ten-year answer rather than an eight-quarter one.

    Guiding a level and a profit implies an operating margin Amazon never
    prints, and the distance from what it reported splits exactly two ways:

        actual OI − guided OI = (Ra − Rg)·mg  +  Ra·(ma − mg)

    with ``mg = Og/Rg`` the guided midpoint margin.  Every term is a company
    number, so the split needs no estimate of any kind.
    """
    guide = staging["quarterly_guidance_history"]
    quarters = guide["quarters"]
    labels = [compact_period(quarter) for quarter in quarters]

    sales_lo, sales_hi = guide["net_sales_low_bn"], guide["net_sales_high_bn"]
    sales_actual = guide["actual_net_sales_bn"]
    income_lo, income_hi = guide["operating_income_low_bn"], guide["operating_income_high_bn"]
    income_actual = guide["actual_operating_income_bn"]
    finished = [index for index, value in enumerate(sales_actual) if value is not None]

    def tally(low: list, high: list, actual: list) -> tuple[int, int, int]:
        above = sum(1 for index in finished if actual[index] > high[index])
        below = sum(1 for index in finished if actual[index] < low[index])
        return above, len(finished) - above - below, below

    sales_above, sales_inside, sales_below = tally(sales_lo, sales_hi, sales_actual)
    income_above, income_inside, income_below = tally(income_lo, income_hi, income_actual)
    unbroken = all(value is not None for value in sales_lo + sales_hi + income_lo + income_hi)
    pandemic = quarters.index("Q2 2020") if "Q2 2020" in quarters else None

    sales_band = delivery_band(
        "EX_SALES_RANGE", "净销售额", labels, sales_lo, sales_hi, sales_actual,
        fmt="usd0", ylab="US$B", unit="US$B", venue="业绩新闻稿",
        src_extra=SOURCE_8K,
        extra_note=(
            "亚马逊每季在申报文件里同时写进<b>两个</b>指引区间"
            "（净销售额与经营利润）"
            + ("，而且没有断过" if unbroken else "")
            + (" —— 连 2020 年疫情最乱的一季也照给，只是把利润下限放到了 "
               f"{paren_bn(income_lo[pandemic])}" if pandemic is not None else "")
            + "。"
            + f"{len(finished)} 个已完结季，收入"
            + ("一次都没有跌破过区间下限" if sales_below == 0 else f"跌破区间下限 {sales_below} 次")
            + f"；上穿上限 {sales_above} 次、落在区间内 {sales_inside} 次。"
            "纵轴是绝对金额，早期的季度因此被压在底部，"
            "无量纲的读法见 Exhibit {EX_SALES_DEV}。"
        ),
    )

    # The deviation charts' own window, so the counts below describe the bars drawn.
    window = finished[-DEVIATION_WINDOW:]

    def deviations(low: list, high: list, actual: list) -> list[float]:
        return [(actual[index] / ((low[index] + high[index]) / 2) - 1) * 100 for index in window]

    sales_dev = deviations(sales_lo, sales_hi, sales_actual)
    income_dev = deviations(income_lo, income_hi, income_actual)
    close = sum(1 for value in sales_dev if abs(value) <= 2)
    sales_deviation = midpoint_deviation(
        "EX_SALES_DEV", "净销售额", quarters, sales_lo, sales_hi, sales_actual,
        mode="pct", window=DEVIATION_WINDOW, label=compact_period,
        src_extra=SOURCE_8K + "偏离为实际值相对指引中值的自算百分比。",
        axis_note=(
            f"本图只画最近 {DEVIATION_WINDOW} 个已完结季，完整的 {len(finished)} 季记录在上一张里；"
        ),
        extra_note=(
            f"柱子普遍不高：收入指引其实<b>相当准</b>，{len(sales_dev)} 季里 {close} 季的偏离在 ±2% 以内。"
            "这一点是下一张利润图的前提 —— 既然收入猜得准，利润的超额就不可能来自卖得更多。"
            if close * 2 > len(sales_dev) else
            f"{len(sales_dev)} 季里只有 {close} 季的偏离在 ±2% 以内。"
        ),
    )

    income_lows = [index for index, value in enumerate(income_lo) if value <= 0]
    deepest = min(income_lows, key=lambda index: income_lo[index]) if income_lows else None
    income_band = delivery_band(
        "EX_OI_RANGE", "经营利润", labels, income_lo, income_hi, income_actual,
        fmt="usd1", ylab="US$B", unit="US$B", venue="业绩新闻稿",
        src_extra=SOURCE_8K,
        extra_note=(
            "同一批新闻稿里的第二条指引"
            + ("，形状比收入那条更偏" if income_above > sales_above else "")
            + f"：{len(finished)} 个已完结季里 {income_above} 季超出上限、"
            f"{income_inside} 季落在区间内，"
            + ("<b>同样一次都没有跌破下限</b>" if income_below == 0 and sales_below == 0 else
               "<b>一次都没有跌破下限</b>" if income_below == 0 else
               f"{income_below} 季跌破下限")
            + "。"
            + (f"有{cn_count(len(income_lows))}季的区间下限是负数或零（最低是 {labels[deepest]} 的 "
               f"{paren_bn(income_lo[deepest])}，最近一次是 {labels[income_lows[-1]]} 的 "
               f"{paren_bn(income_lo[income_lows[-1]])}），"
               "那是当时公司自己就把亏损放进了可能性里，不是绘图误差。" if income_lows else "")
        ),
    )
    sales_mean = statistics.fmean(abs(value) for value in sales_dev)
    income_mean = statistics.fmean(abs(value) for value in income_dev)
    income_positive = sum(1 for value in income_dev if value > 0)
    income_deviation = midpoint_deviation(
        "EX_OI_DEV", "经营利润", quarters, income_lo, income_hi, income_actual,
        mode="pct", window=DEVIATION_WINDOW, label=compact_period,
        src_extra=SOURCE_8K + "偏离为实际值相对指引中值的自算百分比。",
        axis_note=f"本图只画最近 {DEVIATION_WINDOW} 个已完结季；",
        extra_note=(
            "把两张偏离图并排看："
            + ("收入的柱子贴着零轴，利润的柱子成倍高于它。"
               "同一份新闻稿、同一天给出的两个数，一个接近预测、一个系统性偏低 —— "
               "偏差不在需求，在成本。"
               if income_mean > 2 * sales_mean and income_positive * 4 >= len(income_dev) * 3 else
               f"收入的平均绝对偏离 {sales_mean:.1f}%，利润 {income_mean:.1f}%。")
            + "拆开看是 Exhibit {EX_OI_LEGS}。"
        ),
    )

    # ── what the beat is made of ─────────────────────────────────────────────
    revenue_leg, margin_leg, leg_labels, implied_margin, actual_margin = [], [], [], [], []
    for index in finished:
        guided_sales = (sales_lo[index] + sales_hi[index]) / 2
        guided_income = (income_lo[index] + income_hi[index]) / 2
        guided_margin = guided_income / guided_sales
        realised_sales, realised_income = sales_actual[index], income_actual[index]
        realised_margin = realised_income / realised_sales
        revenue_leg.append((realised_sales - guided_sales) * guided_margin)
        margin_leg.append(realised_sales * (realised_margin - guided_margin))
        implied_margin.append(guided_margin * 100)
        actual_margin.append(realised_margin * 100)
        leg_labels.append(compact_period(quarters[index]))

    total = [revenue + margin for revenue, margin in zip(revenue_leg, margin_leg)]
    misses = [index for index, value in enumerate(total) if value < 0]
    margin_driven = [index for index in misses if margin_leg[index] < revenue_leg[index]]
    exceptions = [index for index in range(len(total))
                  if not abs(margin_leg[index]) > abs(revenue_leg[index])]
    margin_dominant = len(total) - len(exceptions)
    if exceptions:
        verdict = (
            f"<b>这家公司迄今为止的经营意外，{len(total)} 季里 {margin_dominant} 季来自成本而不是需求</b>；"
            "例外是 "
            + "、".join(f"{leg_labels[index]}（收入腿 US${revenue_leg[index]:.2f}B，"
                       f"利润率腿 US${margin_leg[index]:.2f}B）" for index in exceptions)
            + "。"
        )
    else:
        verdict = "<b>这家公司迄今为止的经营意外，无论正负，都来自成本而不是需求。</b>"
    reading = (
        f"<b>读数：</b>本季 US${total[-1]:.2f}B 的超额里，收入腿只有 US${revenue_leg[-1]:.2f}B，"
        f"利润率腿 US${margin_leg[-1]:.2f}B —— 占 {margin_leg[-1] / total[-1] * 100:.0f}%。"
        if total[-1] > 0 and abs(revenue_leg[-1]) < abs(margin_leg[-1]) else
        f"<b>读数：</b>本季相对指引中值 {'+' if total[-1] >= 0 else '−'}US${abs(total[-1]):.2f}B，"
        f"收入腿 US${revenue_leg[-1]:.2f}B，利润率腿 US${margin_leg[-1]:.2f}B。"
    )
    legs_chart = {
        "ref": "EX_OI_LEGS",
        "kind": "grouped_bars",
        "title": (
            f"把「超出自身指引」拆成两条腿：{margin_dominant} / {len(total)} 季由利润率腿主导"
            + ("，收入腿几乎看不见" if margin_dominant * 10 >= len(total) * 9 else "")
        ),
        "xlabels": leg_labels,
        "xrot": 90,
        "groups": [
            {"name": "收入腿", "color": "NAVY", "values": rounded(revenue_leg)},
            {"name": "利润率腿", "color": "GOLD", "values": rounded(margin_leg)},
        ],
        "bar_labels": False,
        "fmt": "usd1",
        "label_fmt": "usd1",
        "ylab": "US$B vs 指引中值隐含的经营利润",
        "note": (
            "公司同时给出净销售额与经营利润两个区间，于是<b>隐含</b>了一个自己从不印出来的经营利润率："
            "指引中值利润 ÷ 指引中值收入。实际经营利润与指引中值的差<b>恰好</b>拆成两项之和（不是近似）："
            "收入腿 =（实际收入 − 指引中值收入）× 隐含指引利润率；"
            "利润率腿 = 实际收入 ×（实际利润率 − 隐含指引利润率）。"
            + reading
            + f"整段记录里收入腿的绝对值从未超过 US${max(abs(v) for v in revenue_leg):.2f}B"
            + ("，深蓝那组在图上几乎是一条贴着零轴的线。" if margin_dominant * 10 >= len(total) * 9 else "。")
            + (f"没能达到自身指引中值的 {len(misses)} 季（"
               + "、".join(leg_labels[index] for index in misses)
               + "）"
               + ("也全部是利润率腿更负" if len(margin_driven) == len(misses)
                  else f"里有 {len(margin_driven)} 季是利润率腿更负")
               + " —— " if misses else "")
            + verdict
            + "<b>交互项归属：</b>收入与利润率同时偏离时的交叉项按上式全部计入利润率腿；"
            "调换拆解顺序会把它移到收入腿，两种拆法的合计完全相同。"
        ),
        "src_extra": SOURCE_8K + "两条腿与隐含利润率均为自算，指引原值与实际原值见核对表。",
    }

    # Where the guided and the reported margin sat closest, by calendar year.
    # Only complete years: a half year against full ones would rank on two points.
    gap_by_year: dict[int, list[float]] = {}
    for index, actual, implied in zip(finished, actual_margin, implied_margin):
        gap_by_year.setdefault(int(quarters[index].split()[1]), []).append(actual - implied)
    year_gaps = sorted((statistics.fmean(gaps), year) for year, gaps in gap_by_year.items()
                       if len(gaps) == 4)
    narrowest = ""
    if len(year_gaps) >= 2:
        (first_gap, first_year), (second_gap, second_year) = year_gaps[0], year_gaps[1]
        narrowest = (
            f"按年平均，缺口最窄的是 {first_year} 年（{first_gap:.2f}pp"
            + ("，那一年公司自己也不知道成本会走到哪里" if first_year == COST_SHOCK_YEAR else "")
            + f"），其次是 {second_year} 年（{second_gap:.2f}pp）。"
        )
    implied_chart = {
        "ref": "EX_OI_IMPLIED",
        "kind": "lines",
        "title": (
            f"指引隐含的经营利润率与实际经营利润率：{len(finished)} 季里实际值 "
            f"{sum(1 for a, i in zip(actual_margin, implied_margin) if a > i)} 季高于隐含值"
        ),
        "xlabels": leg_labels,
        "xrot": 90,
        "xstep": 2,
        "series": [
            {"name": "指引中值隐含利润率 D", "values": rounded(implied_margin), "color": "GOLD"},
            {"name": "实际经营利润率", "values": rounded(actual_margin), "color": "NAVY"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "zero_base": True,
        "end_label": True,
        "ylab": "经营利润率",
        "note": (
            "亚马逊从不指引利润率，但同时指引收入与利润就等于指引了一个利润率，"
            "本图把它画出来与实际值对照。两条线的缺口就是上一张的利润率腿，"
            f"本季为 {actual_margin[-1]:.2f}% vs {implied_margin[-1]:.2f}%，"
            f"差 {actual_margin[-1] - implied_margin[-1]:.2f}pp。"
            + narrowest
        ),
        "src_extra": SOURCE_8K + "隐含利润率与实际利润率均为自算。",
    }

    verdicts = {
        "finished": len(finished),
        "quarters": quarters,
    }
    return (
        [sales_band, sales_deviation, income_band, income_deviation, legs_chart, implied_chart],
        verdicts,
    )


# ── the local analyses' thresholds, read against the series ─────────────────
#
# Both threshold blocks -- `prior_kpi_settlement` (last quarter's analysis, settled
# here) and `next_kpi` (this quarter's, watched in section three) -- carry the
# analysis's lines as data: which row of its observation table a line comes
# from, which tier (the analysis gives most metrics a line that triggers a
# warning and a line that confirms the bull case), the comparison the analysis
# wrote, the threshold and the series it is read against (`reads`). No reading
# is typed into a block: every one is computed here from the series, so a roll
# moves this quarter's `next_kpi` into next quarter's `prior_kpi_settlement` as
# it stands and the page settles it without a code change.
TIER_WORDS = {"risk": "风险线", "bull": "多头确认线"}
TIER_SHORT = {"risk": "风险", "bull": "确认"}
TIER_COLOR = {"risk": "RED", "bull": "GREEN"}
TRIGGERS = {
    "<": lambda value, line: value < line,
    "<=": lambda value, line: value <= line,
    ">": lambda value, line: value > line,
    ">=": lambda value, line: value >= line,
}
TRIGGER_WORDS = {"<": "低于", "<=": "不高于", ">": "高于", ">=": "不低于"}
# The closure chart's categories, in the order the site uses; an empty one is
# left off the chart rather than drawn as a zero-height bar.
VERDICT_ORDER = ("已验证", "部分验证", "被证伪", "仍未披露")


def quarter_order(period: str) -> tuple[int, int]:
    """``'Q2 2026'`` → ``(2026, 2)``."""
    quarter, year = period.split()
    return int(year), int(quarter[1])


def previous_period(period: str) -> str:
    year, number = quarter_order(period)
    return f"Q4 {year - 1}" if number == 1 else f"Q{number - 1} {year}"


def following_period(period: str) -> str:
    year, number = quarter_order(period)
    return f"Q1 {year + 1}" if number == 4 else f"Q{number + 1} {year}"


def line_direction(entry: dict) -> str:
    """The favourable side of a line, from what the analysis says happens there.

    A risk line fires when the reading crosses it, a confirmation line is met
    when the reading reaches it; `op` is the comparison the analysis wrote for
    that event. So a risk line written ``<`` and a confirmation line written
    ``>=`` both have their favourable side above.
    """
    if entry.get("tier") not in TIER_WORDS:
        raise ValueError(f"threshold {entry.get('id')!r} has no tier the page knows: {entry.get('tier')!r}")
    if entry.get("op") not in TRIGGERS:
        raise ValueError(f"threshold {entry.get('id')!r} has no comparison the page knows: {entry.get('op')!r}")
    up = (entry["tier"] == "bull") == (entry["op"] in (">", ">="))
    return "up" if up else "down"


def line_hit(entry: dict, value: float) -> bool:
    """Whether the event the analysis wrote for this line happened."""
    return TRIGGERS[entry["op"]](value, entry["threshold"])


def line_state(entry: dict, value: float) -> str:
    if entry["tier"] == "bull":
        return "达到" if line_hit(entry, value) else "没到"
    return "越线" if line_hit(entry, value) else "守住"


def value_text(spec: dict, value: float) -> str:
    """A reading as the page prints it, at the precision the company prints it."""
    if spec.get("digits") is not None:
        if spec["unit"] == "pct":
            return f"{value:.{spec['digits']}f}%"
        if spec["unit"] == "usd_bn":
            return f"{'−' if value < 0 else ''}US${abs(value):.{spec['digits']}f}B"
    return unit_text(spec["unit"], value)


def reading_specs(staging: dict) -> dict[str, dict]:
    """Every series a threshold line can be read against, keyed by its `reads` id.

    Each entry is what the line chart draws (labels, values, name, format) and
    the one number the line settles on (`current`) -- which is not always the
    last point drawn: a threshold the analysis wrote on the company's
    constant-currency growth, or on a margin with this quarter's one-off items
    taken out, settles on that figure while the chart keeps the reported
    series the company prints every quarter. `basis` says so on the chart.
    """
    period = staging["periods"][-1]
    quarterly = staging["quarterly_usd_m"]
    segments = staging["segments_usd_m"]
    long = staging["long_history"]
    cash = staging["cash_flow_disclosed"]
    backlog = staging["aws_backlog"]
    one_off = stamped_block(staging, "one_off_items", period) or {}
    snapshot = stamped_block(staging, "current_snapshot", period)
    energy = one_off.get("energy_derivative_gain_usd_m", 0)
    tariff = one_off.get("tariff_refund_usd_m", 0)

    long_labels = [compact_long(quarter) for quarter in long["quarters"]]
    aws_revenue, aws_income = long["aws_revenue_usd_m"], long["aws_operating_income_usd_m"]
    aws_margin = [income / total * 100 for income, total in zip(aws_income, aws_revenue)]
    aws_yoy = yoy(aws_revenue)
    group_income = long["operating_income_usd_m"]
    group_margin = [income / total * 100 for income, total in zip(group_income, long["revenue_usd_m"])]
    levels = backlog["level_usd_bn"]
    backlog_labels = [compact_period(p) for p in backlog["periods"]]
    net_add = [None] + [current - previous for previous, current in zip(levels, levels[1:])]
    growth = [None] + [(current / previous - 1) * 100 for previous, current in zip(levels, levels[1:])]
    seg_labels = [compact_period(p) for p in segments["periods"]]
    na_margin = [income / total * 100
                 for income, total in zip(segments["na_operating_income"], segments["na_revenue"])]
    cash_labels = [compact_period(p) for p in cash["periods"]]

    printed_fx = (snapshot or {}).get("aws_growth_ex_fx_pct")
    aws_fx = printed_fx[-1] if printed_fx else None
    aws_ex = (aws_income[-1] - energy) / aws_revenue[-1] * 100
    na_ex = (segments["na_operating_income"][-1] - tariff) / segments["na_revenue"][-1] * 100
    group_ex = (quarterly["operating_income"][-1] - energy - tariff) / quarterly["revenue_total"][-1] * 100
    items = [(key, words) for key, words in (
        ("tariff_refund_usd_m", "关税退款"), ("energy_derivative_gain_usd_m", "能源合约净未实现收益"))
        if one_off.get(key)]
    one_off_words = "、".join(f"{words} US${one_off[key]}M" for key, words in items)
    on_call = one_off.get("energy_derivative_gain_on_call_usd_m")
    concentration = stamped_block(staging, "backlog_concentration", period)

    # The run of accelerating quarters the growth line ends on, and the last
    # quarter that grew faster -- read off the line, so a claim like 「连续第五季加速、
    # 十八个季度以来最快」 is checked rather than repeated.
    run = 0
    for index in range(len(aws_yoy) - 1, 0, -1):
        if aws_yoy[index] is None or aws_yoy[index - 1] is None or aws_yoy[index] <= aws_yoy[index - 1]:
            break
        run += 1
    faster = [index for index, value in enumerate(aws_yoy[:-1]) if value is not None and value >= aws_yoy[-1]]
    comparable = [(value, index) for index, value in enumerate(net_add) if value is not None]
    prior_best, prior_best_at = max(comparable[:-1])

    # Where a line could be settled on more than one basis, the page settles on
    # the filed one and says -- computed, per line -- whether the others would
    # have given the same answer (`alternatives`).
    release = "各期 8-K EX-99.1 与 10-Q"
    specs = {
        # The filings print the balance in whole billions (「approximately $496
        # billion」) from 2024Q3 on, so the readings do not add a decimal.
        "backlog_level": {
            "name": "AWS backlog 余额", "line_name": "backlog 余额",
            "labels": backlog_labels, "values": levels, "current": levels[-1], "digits": 0,
            "fmt": "usd0", "ylab": "US$B", "unit": "usd_bn",
            "src": "backlog 为各期 10-Q / 10-K 承诺附注里「主要与 AWS 相关、尚未确认的客户合约承诺」。",
        },
        "backlog_qoq_pct": {
            "name": "AWS backlog 环比增速", "line_name": "backlog 环比增速 D",
            "labels": backlog_labels, "values": growth, "current": growth[-1],
            "fmt": "pct1", "ylab": "环比增速", "unit": "pct",
            "src": "环比增速为相邻两期承诺附注余额的自算值。",
        },
        "backlog_add": {
            "name": "AWS backlog 单季净增", "line_name": "backlog 单季净增 D",
            "labels": backlog_labels, "values": net_add, "current": net_add[-1], "digits": 0,
            "fmt": "usd0", "ylab": "US$B", "unit": "usd_bn",
            "context": (
                f"余额自 {backlog_labels[0]} 起逐季披露，净增共 {len(comparable)} 个可比点；本季 US${net_add[-1]:.0f}B "
                + ("是其中最大的一次" if net_add[-1] > prior_best else
                   f"低于 {backlog_labels[prior_best_at]} 的 US${prior_best:.0f}B")
                + (f"，里面单笔 {concentration['largest_single_addition']['customer']} 扩容就 "
                   f">US${concentration['largest_single_addition']['more_than_usd_bn']:.0f}B"
                   if concentration is not None else "")
                + "。"
            ),
            "src": "单季净增为相邻两期承诺附注余额之差（自算）。",
        },
        "aws_yoy_ex_fx": {
            "name": "AWS 收入同比（固定汇率）", "line_name": "AWS 收入同比（美元口径）D",
            "labels": long_labels, "values": aws_yoy,
            "current": aws_fx if aws_fx is not None else aws_yoy[-1],
            "digits": 0 if aws_fx is not None else 1,
            "fmt": "pct1", "ylab": "同比增速", "unit": "pct",
            "basis": (
                (f"阈值写的是固定汇率口径：公司在新闻稿 Supplemental 表里印出的本季固定汇率同比是 {aws_fx}%（整数），"
                 "本页按它结算；线上画的是按两期美元收入自算的同比 —— 各季新闻稿也都印固定汇率同比，"
                 "本页还没有把它回补成长序列。")
                if aws_fx is not None else
                "公司本季没有印出固定汇率口径，本页按美元口径结算。"
            ),
            "alternatives": ([{"words": "按美元口径自算", "value": aws_yoy[-1], "digits": 1}]
                             if aws_fx is not None else []),
            "context": (
                (f"按美元口径，这条线已连续{cn_count(run)}季加速，" if run >= 2 else "")
                + (f"本季是 {long_labels[faster[-1]]}（{aws_yoy[faster[-1]]:.1f}%）以来最高。" if faster else
                   "本季是窗口内最高。")
            ),
            "src": f"AWS 分部收入来自{release}；美元口径同比为自算，固定汇率同比为公司印出的数。",
        },
        "aws_margin": {
            "name": "AWS 分部经营利润率", "line_name": "AWS 经营利润率 D",
            "labels": long_labels, "values": aws_margin, "current": aws_margin[-1],
            "fmt": "pct1", "ylab": "利润率", "unit": "pct",
            "basis": "阈值没写口径，本页按报告口径结算。",
            "alternatives": ([{"words": f"剔除 10-Q 披露的 US${energy}M 能源合约净未实现收益", "value": aws_ex,
                               "digits": 2}] if energy else []),
            "src": f"AWS 分部收入与经营利润来自{release}；利润率为自算。",
        },
        "aws_margin_ex_one_off": {
            "name": "AWS 分部经营利润率（剔除一次性）", "line_name": "AWS 经营利润率（报告口径）D",
            "labels": long_labels, "values": aws_margin, "current": aws_ex, "digits": 2,
            "fmt": "pct1", "ylab": "利润率", "unit": "pct",
            "basis": (
                (f"阈值写的是剔除一次性后的口径，本页剔除 10-Q 披露的 US${energy}M 能源合约净未实现收益结算；"
                 "线上画的是报告口径。")
                if energy else "本季没有需要剔除的一次性项，报告口径即结算口径。"
            ),
            "alternatives": (
                [{"words": "报告口径（不剔除）", "value": aws_margin[-1], "digits": 1}]
                + ([{"words": f"按电话会的「约 US${on_call}M」剔除",
                     "value": (aws_income[-1] - on_call) / aws_revenue[-1] * 100, "digits": 2}]
                   if on_call and on_call != energy else [])
                if energy else []),
            "src": f"AWS 分部收入与经营利润来自{release}；一次性金额取自 10-Q 原文，利润率为自算。",
        },
        "group_oi": {
            "name": "集团单季经营利润", "line_name": "集团经营利润",
            "labels": long_labels, "values": [value / 1000 for value in group_income],
            "current": group_income[-1] / 1000,
            "fmt": "usd1", "ylab": "US$B", "unit": "usd_bn",
            "src": f"经营利润来自{release}（第四季为全年 − 前三季）。",
        },
        "group_margin": {
            "name": "集团经营利润率", "line_name": "集团经营利润率 D",
            "labels": long_labels, "values": group_margin, "current": group_margin[-1],
            "fmt": "pct1", "ylab": "利润率", "unit": "pct",
            "basis": "阈值没写口径，本页按报告口径结算。",
            "alternatives": ([{"words": f"剔除本季{cn_count(len(items))}笔一次性经营项（{one_off_words}，均取 10-Q 原文）",
                               "value": group_ex, "digits": 2}] if items else []),
            "src": f"经营利润与收入来自{release}；利润率为自算。",
        },
        "fcf_ttm": {
            "name": "TTM 自由现金流", "line_name": "TTM 自由现金流（公司披露）",
            "labels": cash_labels, "values": [value / 1000 for value in cash["free_cash_flow_ttm"]],
            "current": cash["free_cash_flow_ttm"][-1] / 1000,
            "fmt": "usd0", "ylab": "US$B", "unit": "usd_bn",
            "src": "TTM 自由现金流为公司在各季新闻稿 Supplemental 表里直接印出的数。",
        },
        "aws_increment": {
            "name": "AWS 环比收入增量", "line_name": "AWS 环比收入增量 D",
            "labels": long_labels,
            "values": [None if value is None else value / 1000 for value in sequential(aws_revenue)],
            "current": (aws_revenue[-1] - aws_revenue[-2]) / 1000, "digits": 2,
            "fmt": "usd1", "ylab": "US$B", "unit": "usd_bn",
            "src": f"AWS 分部收入来自{release}；环比增量为自算。",
        },
        "net_capex": {
            "name": "单季现金 CapEx（净额）", "line_name": "单季 CapEx（净额）",
            "labels": [compact_period(p) for p in staging["periods"]],
            "values": [value / 1000 for value in quarterly["net_capex"]],
            "current": quarterly["net_capex"][-1] / 1000,
            "fmt": "usd0", "ylab": "US$B", "unit": "usd_bn",
            "context": (f"本季总额（gross）US${quarterly['purchases_of_property_and_equipment'][-1] / 1000:.1f}B，"
                        "与净额之差是出售与激励所得。"),
            "src": "净额 = 购买物业及设备 − 出售与激励所得，与公司自由现金流定义的分母同口径（10-Q 现金流量表）。",
        },
        "na_margin_ex_one_off": {
            "name": "北美分部经营利润率（剔除一次性）", "line_name": "北美经营利润率（报告口径）D",
            "labels": seg_labels, "values": na_margin, "current": na_ex, "digits": 2,
            "fmt": "pct1", "ylab": "利润率", "unit": "pct",
            "basis": (
                (f"阈值写的是剔除一次性后的口径，本页剔除 10-Q 披露的 US${tariff}M 关税退款结算；线上画的是报告口径。")
                if tariff else "本季没有需要剔除的一次性项，报告口径即结算口径。"
            ),
            "alternatives": ([{"words": "报告口径（不剔除）", "value": na_margin[-1], "digits": 1}]
                             if tariff else []),
            "context": (f"北美与国际两个分部的季度表本页只回补到 {quarter_key(segments['periods'][0])}"
                        f"（更早的季度申报里有，还没有接入），AWS 那几条则回到 {long['quarters'][0]}。"),
            "src": f"北美分部收入与经营利润来自{release}；关税退款金额取自 10-Q 原文，利润率为自算。",
        },
    }
    return specs


def commitment_words(item: dict) -> str:
    """A named customer commitment as the 10-Q states it:
    「OpenAI US$138.0B（原有 US$38.0B + Q1 2026 扩容 US$100.0B，扩容部分 8 年）」."""
    parts, words = item["parts_usd_bn"], item["parts_words"]
    total = sum(parts)
    head = f"{item['customer']} {'超过 ' if item.get('more_than') else ''}US${total:.1f}B"
    if len(parts) == 1:
        return f"{head}（{words[0]}，{item['years']:g} 年）"
    return (f"{head}（" + " + ".join(f"{word} US${part:.1f}B" for word, part in zip(words, parts))
            + f"，{item.get('years_of', '')}{item['years']:g} 年）")


def reading_text(unit: str, value: float, digits: int | None = None) -> str:
    if unit == "pct" and digits is not None:
        return f"{value:.{digits}f}%"
    if unit == "usd_bn" and digits is not None:
        return f"{'−' if value < 0 else ''}US${abs(value):.{digits}f}B"
    return unit_text(unit, value)


def threshold_text(unit: str, value: float) -> str:
    """A threshold the way the analysis wrote it: 「US$400B」「15%」「−US$10B」, not 「US$400.0B」."""
    if unit == "pct":
        return f"{value:g}%"
    if unit == "usd_bn":
        return f"{'−' if value < 0 else ''}US${abs(value):g}B"
    return unit_text(unit, value)


def signed_pct(value: float) -> str:
    """``-252.1`` → ``'−252.1%'``, with the page's minus sign."""
    return f"{value:+.1f}%".replace("-", "−")


def settlement_blocks(staging: dict, period: str) -> tuple[bool, dict | None, dict | None]:
    """Whether this quarter has a previous local analysis, and what it left open.

    Section one is 「上季跟踪指标兑现了吗」: the previous analysis's follow-up
    questions (`followup_closure`, closed by this quarter's analysis in its
    section 0) and its observation-table thresholds (`prior_kpi_settlement`).
    Up to `analysis_record.first_period` there was no previous analysis and the
    section says so; after it there always is, so a roll that leaves the
    thresholds out stops the build instead of publishing a section one that
    quietly skipped them. A quarter whose analysis closed no questions says why
    in `prior_kpi_settlement.no_closure_reason`.
    """
    first = (staging.get("analysis_record") or {}).get("first_period")
    closure = stamped_block(staging, "followup_closure", period)
    prior = stamped_block(staging, "prior_kpi_settlement", period)
    if first is not None and quarter_order(period) <= quarter_order(first):
        present = [name for name, block in (("followup_closure", closure),
                                            ("prior_kpi_settlement", prior)) if block is not None]
        if present:
            raise ValueError(f"{period} has no earlier AMZN analysis, so there is nothing for "
                             f"{', '.join(present)} to settle")
        return True, None, None
    if prior is None:
        raise ValueError(f"the analysis before {period} set thresholds: stamp `prior_kpi_settlement` "
                         f"(and `followup_closure`) for {period}")
    if closure is None and not prior.get("no_closure_reason"):
        raise ValueError(f"`followup_closure` is missing for {period}: add this quarter's section-0 "
                         "verdicts, or say in `prior_kpi_settlement.no_closure_reason` why there are none")
    expected = previous_period(period)
    for name, block in (("followup_closure", closure), ("prior_kpi_settlement", prior)):
        if block is not None and block.get("set_in") != expected:
            raise ValueError(f"series block `{name}` settles an analysis stamped {block.get('set_in')!r}, "
                             f"but the quarter before {period} is {expected!r}")
    return False, closure, prior


def closure_parts(closure: dict, values: dict) -> tuple[dict, dict]:
    """(a): the previous analysis's follow-up questions and this quarter's verdicts.

    The categories are counted from the block's items, never typed as totals, so
    the title cannot disagree with the table under it.
    """
    items = closure["items"]
    labels = list(closure.get("labels") or VERDICT_ORDER)
    unknown = sorted({item["verdict"] for item in items} - set(labels))
    if unknown:
        raise ValueError(f"`followup_closure` items carry verdicts that are not labels: {unknown}")
    counts = [(label, sum(1 for item in items if item["verdict"] == label)) for label in labels]
    shown = [(label, count) for label, count in counts if count]
    detail = "；".join(
        f"{label}的{cn_count(count)}条是" + "、".join(
            f"「{item['short']}」" for item in items if item["verdict"] == label)
        for label, count in shown if label != labels[0])
    chart = {
        "ref": "EX_CLOSURE",
        "kind": "bars_labeled",
        "title": (f"上季 {len(items)} 条待验证问题："
                  + "、".join(f"{count} 条{label}" for label, count in shown)),
        "xlabels": [label for label, _ in shown],
        "values": [count for _, count in shown],
        "legend": "问题条数",
        "fmt": "f0",
        "yfmt": "f0",
        "label_fmt": "f0",
        "ylab": "条",
        "note": (
            f"上季（{closure['set_in']}）那一份本地分析在文末留下 {len(items)} 条待验证问题，"
            "本季那一份在第 0 节逐条回答。"
            + fill_story(closure["rule"], values)
            + (detail + "。" if detail else "")
            + fill_story(closure.get("diagnosis", ""), values)
        ),
        "src_extra": (
            f"问题原文来自上季（{closure['set_in']}）本地分析稿的 Follow-up Questions；答复与打分照录本季本地"
            "分析稿第 0 节，本页只按上述规则归类、不改判；每条的申报证据已回本季业绩 8-K 与 10-Q 核对，"
            "逐条见核对抽屉。"
        ),
    }
    table = {
        "n": 0,
        "title": f"上季（{closure['set_in']}）留下的 {len(items)} 条待验证问题：本季第 0 节的答复与申报证据",
        "headers": ["#", "上季问题", "本季第 0 节的答复（原文）", "四维打分（原文）", "本页归类", "申报证据"],
        "rows": [[str(index), item["question"], item["answer"], item["scores"], item["verdict"],
                  fill_story(item["evidence"], values)]
                 for index, item in enumerate(items, 1)],
    }
    return chart, table


def threshold_lines(block: dict, specs: dict, value_key: str, period: str) -> tuple[list[dict], list[dict]]:
    """(due, later): a threshold block's lines, each with its reading under ``value_key``.

    A line the analysis dated later than this quarter (``due_from``) is carried,
    and listed, but not settled: the reading is where the metric stands now, not
    a verdict.
    """
    due, later, seen = [], [], set()
    for entry in block["quantified"]:
        if entry["id"] in seen:
            raise ValueError(f"threshold id {entry['id']!r} appears twice")
        seen.add(entry["id"])
        if entry["reads"] not in specs:
            raise ValueError(f"threshold {entry['id']!r} reads {entry['reads']!r}, which the page does not know")
        line = dict(entry, direction=line_direction(entry))
        line[value_key] = specs[entry["reads"]]["current"]
        dated = entry.get("due_from")
        (later if dated and quarter_order(dated) > quarter_order(period) else due).append(line)
    return due, later


def row_findings(block: dict, due: list[dict], later: list[dict], value_key: str) -> list[dict]:
    """Each observation-table row, its lines combined the way the analysis wrote them.

    A row's tier is either every line at once (``and``) or any one (``or``); a
    condition the company does not disclose (``*_unquantified``) can neither be
    confirmed nor ruled out, so an ``and`` tier that needs one is not met.
    """
    rows = block.get("rows") or []
    numbers = [row["row"] for row in rows]
    orphans = sorted({line["row"] for line in due + later} - set(numbers))
    if orphans:
        raise ValueError(f"threshold lines name rows {orphans} that the block's `rows` does not describe")
    findings = []
    for row in rows:
        finding = {"row": row["row"], "source": row}
        for tier in ("bull", "risk"):
            lines = [line for line in due if line["row"] == row["row"] and line["tier"] == tier]
            pending = [line for line in later if line["row"] == row["row"] and line["tier"] == tier]
            hits = [line_hit(line, line[value_key]) for line in lines]
            logic = row.get(f"{tier}_logic", "and")
            if logic not in ("and", "or"):
                raise ValueError(f"row {row['row']} {tier} logic must be 'and' or 'or', not {logic!r}")
            unquantified = row.get(f"{tier}_unquantified")
            if not lines:
                status = "pending" if pending else "none"
            elif logic == "and":
                status = ("met" if all(hits) and not unquantified else
                          "blocked" if all(hits) else "not_met")
            else:
                status = "met" if any(hits) else "not_met"
            finding[tier] = {"status": status, "lines": lines, "hits": hits, "pending": pending,
                             "logic": logic, "unquantified": unquantified}
        findings.append(finding)
    return findings


def row_words(findings: list[dict], values: dict, value_key: str, specs: dict) -> str:
    """The rows, read the way the analysis wrote them, in one paragraph."""
    def rows_text(group: list[dict]) -> str:
        return "第" + "、".join(cn_ordinal(finding["row"]) for finding in group) + "行"

    parts = []
    bull_met = [f for f in findings if f["bull"]["status"] == "met"]
    if bull_met:
        joint = any(len(f["bull"]["lines"]) > 1 for f in bull_met)
        parts.append(f"{rows_text(bull_met)}的多头条件成立" + ("（同一行的线要同时达到）" if joint else ""))
    for finding in findings:
        bull = finding["bull"]
        if bull["status"] == "blocked":
            parts.append(f"第{cn_ordinal(finding['row'])}行的数值线达到了，但多头条件的另一半"
                         f"「{bull['unquantified']}」公司没有披露，不算成立")
        elif bull["status"] == "not_met":
            missed = [line for line, hit in zip(bull["lines"], bull["hits"]) if not hit]
            parts.append(f"第{cn_ordinal(finding['row'])}行的多头条件没有成立（"
                         + "、".join(f"{line['metric']}没到 {threshold_text(line['unit'], line['threshold'])}"
                                     for line in missed) + "）")
    risk_met = [f for f in findings if f["risk"]["status"] == "met"]
    if risk_met:
        parts.append(f"{rows_text(risk_met)}的风险条件成立")
    elif any(f["risk"]["status"] != "none" for f in findings):
        parts.append("没有一行的风险条件成立")
    for finding in findings:
        risk = finding["risk"]
        crossed = [line for line, hit in zip(risk["lines"], risk["hits"]) if hit]
        if risk["status"] == "not_met" and crossed and risk["logic"] == "and":
            parts.append(f"第{cn_ordinal(finding['row'])}行的风险条件要几条线同时越过，本季只有"
                         + "、".join(line["metric"] for line in crossed) + "越线，不算成立")
        if risk["unquantified"] and risk["status"] != "met":
            parts.append(f"第{cn_ordinal(finding['row'])}行风险一侧的「{risk['unquantified']}」同样无法判定")
    text = "按原文把同一行的线合起来读：" + "；".join(parts) + "。" if parts else ""
    for finding in findings:
        for line in finding["bull"]["pending"] + finding["risk"]["pending"]:
            spec = specs[line["reads"]]
            text += (f"另有一条要到 {line['due_from']} 起才结算（原文写的是{line.get('due_words', '以后')}）："
                     f"{line['metric']}{TIER_WORDS[line['tier']]} {threshold_text(line['unit'], line['threshold'])}，"
                     f"当前 {value_text(spec, line[value_key])}，不进这张图。")
    for finding in findings:
        source = finding["source"]
        if source.get("qualitative"):
            text += (f"第{cn_ordinal(finding['row'])}行是定性条件："
                     + fill_story(source["qualitative"], values))
        elif source.get("not_drawn_reason") and finding["bull"]["status"] == finding["risk"]["status"] == "none":
            text += (f"第{cn_ordinal(finding['row'])}行（{source['subject']}）不结算："
                     + fill_story(source["not_drawn_reason"], values) + "。")
    return text


def alternative_words(spec: dict, group: list[dict], value_key: str) -> str:
    """For each other basis a line could be read on: the value, and whether it changes a verdict."""
    text = ""
    for alternative in spec.get("alternatives", []):
        value = alternative["value"]
        changed = [line for line in group
                   if line_state(line, value) != line_state(line, line[value_key])]
        text += (f"{alternative['words']}为 {reading_text(spec['unit'], value, alternative.get('digits'))}，"
                 + ("结果相同。" if not changed else
                    "那样的话" + "、".join(
                        f"{TIER_WORDS[line['tier']]} {threshold_text(line['unit'], line['threshold'])} "
                        f"就{line_state(line, value)}" for line in changed) + "。"))
    return text


def reading_charts(lines: list[dict], specs: dict, value_key: str, era: str, set_in: str,
                   later: list[dict] | None = None) -> list[dict]:
    """One chart per reading, every line of this era on it as its own flat series.

    ``era`` is ``prior`` (the line is settled: 守住 / 越线 / 达到 / 没到) or
    ``next`` (the line is watched: the title names the lines and where the
    reading stands now). A line dated later than this quarter is named under
    the chart of its reading, not drawn.
    """
    groups: dict[str, list[dict]] = {}
    for line in lines:
        groups.setdefault(line["reads"], []).append(line)
    charts = []
    for reads, group in groups.items():
        spec = specs[reads]
        group = sorted(group, key=lambda line: (line["tier"] != "risk", line["threshold"]))
        now = value_text(spec, group[0][value_key])
        if era == "prior":
            # 「越线」 is the state; before the line's name the verb is 「越过」.
            verbs = {"守住": "守住", "越线": "越过", "达到": "达到", "没到": "没到"}
            title = (f"{spec['name']}：" + "、".join(
                f"{verbs[line_state(line, line[value_key])]}上季{TIER_WORDS[line['tier']]} "
                f"{threshold_text(line['unit'], line['threshold'])}" for line in group) + f"，本季 {now}")
        else:
            title = (f"{spec['name']}：下季" + "、".join(
                f"{TIER_WORDS[line['tier']]} {threshold_text(line['unit'], line['threshold'])}" for line in group)
                + f"，当前 {now}")
        filled = [value for value in spec["values"] if value is not None]
        counts = (f"线上有值的 {len(filled)} 季里，" + "、".join(
            f"{TRIGGER_WORDS[line['op']]} {threshold_text(line['unit'], line['threshold'])} 的有 "
            f"{sum(1 for value in filled if line_hit(line, value))} 季" for line in group) + "。")
        pending = [line for line in (later or []) if line["reads"] == reads]
        series = [{"name": spec["line_name"], "values": rounded(spec["values"]), "color": "NAVY"}]
        for line in group:
            series.append({
                "name": (f"{'上季' if era == 'prior' else '下季'}{TIER_WORDS[line['tier']]} "
                         f"{threshold_text(line['unit'], line['threshold'])}"
                         f"（{TRIGGER_WORDS[line['op']]}它即{'达到' if line['tier'] == 'bull' else '越线'}）"),
                "values": [line["threshold"]] * len(spec["labels"]),
                "color": TIER_COLOR[line["tier"]],
            })
        chart = {
            "ref": f"EX_{era.upper()}_{reads.upper()}",
            "kind": "lines",
            "title": title,
            "xlabels": spec["labels"],
            "series": series,
            "fmt": spec["fmt"],
            "yfmt": spec["fmt"],
            "label_fmt": spec["fmt"],
            "end_label": True,
            "ylab": spec["ylab"],
            "note": (
                spec.get("basis", "")
                + alternative_words(spec, group, value_key)
                + "".join(
                    f"{TIER_WORDS[line['tier']]} {threshold_text(line['unit'], line['threshold'])}："
                    f"余量 {signed_pct(headroom(line['direction'], line['threshold'], line[value_key]))}"
                    + ("" if era == "next" else f"，{line_state(line, line[value_key])}")
                    + "。" for line in group)
                + "".join(
                    f"同一行的{TIER_WORDS[line['tier']]} {threshold_text(line['unit'], line['threshold'])} "
                    f"原文写的是{line.get('due_words', '以后')}，要到 {line['due_from']} 起才结算，这里不画。"
                    for line in pending)
                + spec.get("context", "")
                + counts
            ),
            "src_extra": (spec["src"] + f"阈值取自{'上季' if era == 'prior' else '本季'}（{set_in}）本地分析稿的"
                          "关键观察指标，不是公司指引。"),
        }
        if len(spec["labels"]) > 20:
            chart["xstep"] = LONG_STEP
        charts.append(chart)
    return charts


def threshold_tables(block: dict, due: list[dict], later: list[dict], findings: list[dict], specs: dict,
                     value_key: str, era: str) -> list[dict]:
    """The drawer's two views of a threshold block: line by line, and row by row."""
    now_head = "本季实际" if era == "prior" else "当前值"
    lines_table = {
        "n": 0,
        "title": (f"{'上季' if era == 'prior' else '下季'}阈值逐线（{block['set_in'] if era == 'prior' else block['period']}"
                  " 本地分析，原单位）"),
        "headers": ["行", "指标", "档", "原文写法", "阈值", now_head, "余量 D", "判定" if era == "prior" else "现状"],
        "rows": [],
    }
    order = {entry["id"]: index for index, entry in enumerate(block["quantified"])}
    for line in sorted(due + later, key=lambda line: order[line["id"]]):
        spec = specs[line["reads"]]
        pending = line in later
        lines_table["rows"].append([
            cn_ordinal(line["row"]),
            line["metric"],
            TIER_WORDS[line["tier"]],
            f"{TRIGGER_WORDS[line['op']]} {threshold_text(line['unit'], line['threshold'])} 即"
            + ("达到" if line["tier"] == "bull" else "越线"),
            threshold_text(line["unit"], line["threshold"]),
            value_text(spec, line[value_key]),
            signed_pct(headroom(line["direction"], line["threshold"], line[value_key])),
            (f"未到期（{line['due_from']} 起结算）" if pending else line_state(line, line[value_key])),
        ])
    status_words = {"met": "成立",
                    "blocked": ("数值线达到，另一半无法从申报确认，不成立" if era == "prior"
                                else "数值线当前已达到，另一半要看下季申报"),
                    "not_met": "不成立", "pending": "未到期"}

    def status(finding: dict, tier: str) -> str:
        state = finding[tier]["status"]
        if state != "none":
            return status_words[state]
        source = finding["source"]
        if not source.get(tier):
            return "—"
        return "定性，见图注" if source.get("qualitative") else source.get("not_drawn", "—")

    rows_table = {
        "n": 0,
        "title": (f"{'上季' if era == 'prior' else '本季'}本地分析的关键观察指标{cn_count(len(findings))}行："
                  "原文条件与本页的合成"),
        "headers": ["行", "指标", "多头档（原文）", "风险档（原文）",
                    "多头条件" if era == "prior" else "多头条件（按当前值）",
                    "风险条件" if era == "prior" else "风险条件（按当前值）"],
        "rows": [[cn_ordinal(finding["row"]), finding["source"]["subject"],
                  finding["source"].get("bull") or "—", finding["source"].get("risk") or "—",
                  status(finding, "bull"), status(finding, "risk")]
                 for finding in findings],
    }
    return [lines_table, rows_table]


def tier_summary(lines: list[dict], value_key: str, era: str) -> str:
    """「6 条风险线都守住、5 条多头确认线都达到」, counted from the lines."""
    parts = []
    for tier in ("risk", "bull"):
        group = [line for line in lines if line["tier"] == tier]
        if not group:
            continue
        good = sum(1 for line in group if line_state(line, line[value_key]) in ("守住", "达到"))
        bad_verb = "越线" if tier == "risk" else "没到"
        if era == "prior":
            state = ("都守住" if tier == "risk" else "都达到") if good == len(group) else \
                f"有 {len(group) - good} 条{bad_verb}"
        else:
            state = ("当前都在安全侧" if tier == "risk" else "当前都已达到") if good == len(group) else \
                f"当前有 {len(group) - good} 条{bad_verb}"
        parts.append(f"{len(group)} 条{TIER_WORDS[tier]}{state}")
    return "、".join(parts)


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    q = staging["quarterly_usd_m"]
    aws = staging["segments_usd_m"]["aws_revenue"]
    ttm = staging["cash_flow_disclosed"]["free_cash_flow_ttm"][-1]
    return [f"Revenue ${q['revenue_total'][-1] / 1000:.1f}B",
            f"AWS {(aws[-1] / aws[-5] - 1) * 100:+.0f}%",
            f"TTM FCF {'-' if ttm < 0 else ''}${abs(ttm) / 1000:.1f}B"]


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    period = periods[-1]
    quarter_word, year_word = period.split()
    latest = latest_block(staging, period=period)
    release_source(staging, period)
    ir = source_for(staging, "Amazon Investor Relations")
    filed_10q = any(item["label"].startswith(f"{period} Form 10-Q") for item in staging["sources"])

    snapshot = stamped_block(staging, "current_snapshot", period)
    if snapshot is not None and snapshot["columns"] != [periods[-5], periods[-2], period]:
        raise ValueError(f"current_snapshot columns {snapshot['columns']} are not "
                         f"(a year ago, last quarter, this quarter) of {period}")
    one_off = stamped_block(staging, "one_off_items", period) or {}
    other_story = stamped_block(staging, "other_income_story", period)
    concentration = stamped_block(staging, "backlog_concentration", period)
    capital = stamped_block(staging, "capital_structure", period)
    guidance = stamped_block(staging, "guidance", period)
    shift = stamped_block(staging, "calendar_shift", period)
    consensus = stamped_block(staging, "market_expectation", period)
    first_analysis, closure, prior_kpi = settlement_blocks(staging, period)
    next_kpi = stamped_block(staging, "next_kpi", period)
    story = stamped_block(staging, "quarter_story", period) or {}
    errata = stamped_block(staging, "local_note_errata", period)

    quarterly = staging["quarterly_usd_m"]
    segments = staging["segments_usd_m"]
    lines = staging["product_lines_usd_m"]
    cash = staging["cash_flow_disclosed"]
    long = staging["long_history"]
    backlog = staging["aws_backlog"]
    guide = staging["quarterly_guidance_history"]

    revenue = quarterly["revenue_total"]
    operating_income = quarterly["operating_income"]
    capex = quarterly["purchases_of_property_and_equipment"]
    operating_cash_flow = quarterly["operating_cash_flow"]
    dda = quarterly["depreciation_and_amortization"]
    net_capex = quarterly["net_capex"][-1]
    operating_margin = [
        income / total * 100 for income, total in zip(operating_income, revenue)
    ]

    # ── segments (the three-segment block; North America / International start later) ─
    seg_periods = segments["periods"]
    seg_labels = [compact_period(p) for p in seg_periods]
    aws_revenue = segments["aws_revenue"]
    aws_income = segments["aws_operating_income"]
    aws_margin = [income / total * 100 for income, total in zip(aws_income, aws_revenue)]
    aws_yoy = yoy(aws_revenue)
    na_margin = [
        income / total * 100
        for income, total in zip(segments["na_operating_income"], segments["na_revenue"])
    ]
    intl_margin = [
        income / total * 100
        for income, total in zip(segments["intl_operating_income"], segments["intl_revenue"])
    ]

    # ── disclosed trailing cash flow (all company figures) ──────────────────
    cash_labels = [compact_period(p) for p in cash["periods"]]
    fcf_ttm = cash["free_cash_flow_ttm"]
    fcf_bn = [value / 1000 for value in fcf_ttm]
    trough_index = fcf_bn.index(min(fcf_bn))
    latest_fcf = fcf_ttm[-1]
    turned_negative = latest_fcf < 0 <= fcf_ttm[-2]
    # Longest run of consecutive negative quarters that ended before the
    # current one -- the local note missed it because each release prints only
    # six quarters. Counting all negatives instead would silently fold this
    # quarter into the previous trough the moment the run continues.
    prior_negative_run, run = 0, 0
    for value in fcf_bn[:-1]:
        run = run + 1 if value < 0 else 0
        prior_negative_run = max(prior_negative_run, run)

    # ── product lines ────────────────────────────────────────────────────────
    line_periods = lines["periods"]
    line_labels = [compact_period(p) for p in line_periods]
    ads_yoy = yoy(lines["advertising_services"])
    ads_from = leading_gap(lines["advertising_services"])
    online_yoy = yoy(lines["online_stores"])
    third_party_yoy = yoy(lines["third_party_seller_services"])
    subscription_yoy = yoy(lines["subscription_services"])
    drawn_lines = {"advertising_services": ads_yoy, "online_stores": online_yoy,
                   "third_party_seller_services": third_party_yoy,
                   "subscription_services": subscription_yoy}
    accelerating = [name for name, values in drawn_lines.items() if values[-1] > values[-2]]

    # ── ten-year routine series ──────────────────────────────────────────────
    long_quarters = long["quarters"]
    if long_quarters[-1] != quarter_key(period):
        raise ValueError(f"long_history ends at {long_quarters[-1]}, the series at {period}")
    long_labels = [compact_long(quarter) for quarter in long_quarters]
    long_revenue = long["revenue_usd_m"]
    long_capex = long["capital_expenditures_usd_m"]
    long_dda = long["depreciation_and_amortization_usd_m"]
    long_ocf = long["operating_cash_flow_usd_m"]
    long_revenue_yoy = yoy(long_revenue)
    yoy_from = leading_gap(long_revenue_yoy)
    capex_from = leading_gap(long_capex)
    long_intensity = [
        None if capital is None else capital / total * 100
        for capital, total in zip(long_capex, long_revenue)
    ]
    long_dda_intensity = [
        None if value is None else value / total * 100
        for value, total in zip(long_dda, long_revenue)
    ]
    long_aws_share = [
        value / total * 100 for value, total in zip(long["aws_revenue_usd_m"], long_revenue)
    ]
    long_aws_income_share = [
        value / total * 100
        for value, total in zip(long["aws_operating_income_usd_m"],
                                long["operating_income_usd_m"])
    ]

    # ── this quarter's arithmetic, all of it reproducible from the tables ────
    energy = one_off.get("energy_derivative_gain_usd_m", 0)
    tariff = one_off.get("tariff_refund_usd_m", 0)
    one_off_items = [(key, words) for key, words in (
        ("tariff_refund_usd_m", "关税退款"), ("energy_derivative_gain_usd_m", "能源衍生品净未实现收益"))
        if key in one_off]
    one_off_total = energy + tariff
    aws_om_reported = aws_margin[-1]
    aws_om_adjusted = (aws_income[-1] - energy) / aws_revenue[-1] * 100
    aws_om_prior_year = aws_margin[-5]
    na_om_reported = na_margin[-1]
    na_om_adjusted = (segments["na_operating_income"][-1] - tariff) / segments["na_revenue"][-1] * 100
    na_om_prior_year = na_margin[-5]
    group_om_adjusted = (operating_income[-1] - one_off_total) / revenue[-1] * 100
    group_om_previous = operating_margin[-2]

    long_aws_revenue = long["aws_revenue_usd_m"]
    long_aws_income = long["aws_operating_income_usd_m"]
    long_aws_margin = [income / total * 100
                       for income, total in zip(long_aws_income, long_aws_revenue)]
    long_aws_yoy = yoy(long_aws_revenue)
    long_aws_sequential = sequential(long_aws_revenue)
    # Where the two blocks overlap they have to agree, or one of them is wrong.
    seg_at = {quarter_key(p): index for index, p in enumerate(seg_periods)}
    for index, quarter in enumerate(long_quarters):
        if quarter in seg_at:
            assert abs(long_aws_revenue[index]
                       - aws_revenue[seg_at[quarter]]) < 0.01, quarter
            assert abs(long_aws_income[index]
                       - aws_income[seg_at[quarter]]) < 0.01, quarter

    # The increment record is read over every quarter the chart draws, not the
    # thirty-quarter segment block: a record is a claim about the whole line.
    aws_increment = long_aws_sequential[-1]
    earlier_increments = [(value, index) for index, value in enumerate(long_aws_sequential[:-1])
                          if value is not None]
    largest_prior_increment, largest_prior_at = max(earlier_increments)
    aws_record = aws_increment > largest_prior_increment
    aws_increment_margin = (
        (aws_income[-1] - energy - aws_income[-2]) / aws_increment * 100
    )
    aws_accelerating = aws_yoy[-1] > aws_yoy[-2]

    backlog_levels = backlog["level_usd_bn"]
    backlog_labels = [compact_period(p) for p in backlog["periods"]]
    backlog_add = backlog_levels[-1] - backlog_levels[-2]
    backlog_net_add = [None] + [
        current - previous for previous, current in zip(backlog_levels, backlog_levels[1:])
    ]

    # Net capex spent so far in the fiscal year the full-year guide covers.
    fy_capex = (guidance or {}).get("fy_capex")
    ytd = None
    if fy_capex is not None:
        elapsed = [index for index, p in enumerate(periods) if p.split()[1] == str(fy_capex["year"])]
        if elapsed and len(elapsed) in YTD_WORDS:
            spent = sum(quarterly["net_capex"][index] for index in elapsed)
            done_words, rest_words = YTD_WORDS[len(elapsed)]
            ytd = {"spent": spent, "done": done_words, "rest": rest_words,
                   "rest_bn": fy_capex["usd_bn"] - spent / 1000}
    capex_accelerating = capex[-1] - capex[-2] > capex[-2] - capex[-3]

    guidance_charts, verdicts = guidance_delivery_charts(staging)

    source = (
        f'Source: <a href="{ir["url"]}" rel="noopener">{ir["label"]}</a>'
        f"（{period} 业绩 8-K EX-99.1{' 与 10-Q' if filed_10q else ''}；历史季度经 SEC EDGAR 回源）。"
    )

    # ── section one: (a) the previous analysis's questions, (b) its thresholds,
    #    (c) the company's own guided record ───────────────────────────────────
    specs = reading_specs(staging)
    named = (concentration or {}).get("named_commitments") or []
    named_floor = sum(sum(item["parts_usd_bn"]) for item in named)
    at_least = "≥" if any(item.get("more_than") for item in named) else ""
    story_values = {
        "backlog": f"US${backlog_levels[-1]:.0f}B",
        "backlog_add": f"US${backlog_add:.0f}B",
        "named_commitments": "、".join(commitment_words(item) for item in named),
        "named_floor": f"{at_least}US${named_floor:.0f}B",
        "named_share": f"{at_least}{named_floor / backlog_levels[-1] * 100:.0f}%",
        "fcf": money_bn(latest_fcf),
        "fcf_year_ago": money_bn(fcf_ttm[-5]),
        "aws_yoy_usd": f"{aws_yoy[-1]:.1f}%",
        "aws_yoy_fx": (f"{snapshot['aws_growth_ex_fx_pct'][-1]}%"
                       if snapshot is not None and "aws_growth_ex_fx_pct" in snapshot else "未印出"),
        "aws_increment": money_bn(aws_increment, 2),
        "aws_record": f"US${largest_prior_increment / 1000:.2f}B",
        "aws_record_at": long_labels[largest_prior_at],
        "aws_record_ratio": f"{aws_increment / largest_prior_increment:.1f}",
        "aws_om": f"{aws_om_reported:.1f}%",
        "aws_om_ex": f"{aws_om_adjusted:.2f}%",
        "energy": f"US${energy}M",
        "energy_on_call": (f"US${one_off['energy_derivative_gain_on_call_usd_m']}M"
                           if one_off.get("energy_derivative_gain_on_call_usd_m") else "未给出"),
        "aws_om_ex_call": (
            f"{(aws_income[-1] - one_off['energy_derivative_gain_on_call_usd_m']) / aws_revenue[-1] * 100:.1f}%"
            if one_off.get("energy_derivative_gain_on_call_usd_m") else "未给出"),
        "fy_capex": f"US${fy_capex['usd_bn']:.0f}B" if fy_capex else "未给出",
        "fy_capex_prior": (f"US${fy_capex['prior_usd_bn']:.0f}B"
                           if fy_capex and "prior_usd_bn" in fy_capex else "未给出"),
        "pe_upward": (f"US${other_story['private_equity_upward_adjustment_usd_bn']:.1f}B"
                      if other_story is not None else "未披露"),
        "bridge_bps": str(shift["bridge_bps"]) if shift is not None else "未给出",
        "top_three_undisclosed": (cn_count(concentration["top_three_share_undisclosed_quarters"])
                                  if concentration is not None else "未知"),
    }
    settled_charts, settled_tables = [], []
    settled_counts = {}
    if closure is not None:
        closure_chart, closure_table = closure_parts(closure, story_values)
        settled_charts.append(closure_chart)
        settled_tables.append(closure_table)
        settled_counts["questions"] = len(closure["items"])
    prior_due = []
    if prior_kpi is not None:
        prior_due, prior_later = threshold_lines(prior_kpi, specs, "actual", period)
        findings = row_findings(prior_kpi, prior_due, prior_later, "actual")
        prior_charts = reading_charts(prior_due, specs, "actual", "prior", prior_kpi["set_in"], prior_later)
        overview = headroom_exhibit(
            f"上季 {len(prior_due)} 条量化阈值：" + tier_summary(prior_due, "actual", "prior"),
            [dict(line, metric=f"{TIER_SHORT[line['tier']]}：{line['metric']}") for line in prior_due],
            "actual",
            (
                "正值 = 有利一侧（" + "、".join(
                    {"risk": "风险线没有越过", "bull": "多头确认线已经达到"}[tier]
                    for tier in ("risk", "bull") if any(line["tier"] == tier for line in prior_due))
                + "），负值 = 不利一侧。"
                f"阈值逐字取自上季（{prior_kpi['set_in']}）本地分析的{prior_kpi['section']}"
                + ("：那一节对多数指标写了两档 —— 越过即须警觉的风险线、兑现多头论证的确认线 —— "
                   "本页逐档拆成独立的线，" if {line["tier"] for line in prior_due} == {"risk", "bull"} else "，")
                + f"实际值取自 {period} 的申报。"
                + row_words(findings, story_values, "actual", specs)
                + (f"有时间序列的{cn_count(len(prior_charts))}个读数各画一张图（Exhibit "
                   + "、".join("{" + chart["ref"] + "}" for chart in prior_charts) + "）。" if prior_charts else "")
            ),
            src_extra=(
                f"阈值取自上季（{prior_kpi['set_in']}）本地分析稿，不是公司指引；实际值来自 {period} 业绩 8-K "
                "与 10-Q，逐线与逐行的对照见核对抽屉。"
            ),
        )
        overview["ref"] = "EX_PRIOR"
        overview["legend"] = "距上季阈值的余量"
        overview["positive_label"] = "守住 / 达到"
        overview["negative_label"] = "越线 / 没到"
        settled_charts += [overview] + prior_charts
        settled_tables += threshold_tables(prior_kpi, prior_due, prior_later, findings, specs, "actual", "prior")
        settled_counts["lines"] = len(prior_due)
    # (c) after (a)(b): the company's own guided record closes the section.
    settled_charts += guidance_charts

    # ── section two: this quarter ────────────────────────────────────────────
    early = [value for quarter, value in zip(long_quarters, long_aws_sequential)
             if value is not None and quarter < "2019"]
    negative_increments = sum(1 for v in long_aws_sequential if v is not None and v < 0)
    in_short_window = largest_prior_at >= len(long_quarters) - WINDOW
    aws_note = (
        story.get("aws_anchor_note", "")
        + f"环比增量直接映射产能上线速度：本季 {money_bn(aws_increment, 2)}，"
        f"同比增速 {aws_yoy[-1]:.1f}%"
        + (f"（公司披露的固定汇率口径为 {snapshot['aws_growth_ex_fx_pct'][-1]}%）"
           if snapshot is not None and "aws_growth_ex_fx_pct" in snapshot else "")
        + "。"
        + f"拉到{cn_count(len(long_quarters))}季，此前最大的单季增量"
        + ("仍是" if in_short_window else "是")
        + f" {long_labels[largest_prior_at]} 的 US${largest_prior_increment / 1000:.2f}B"
        + ("" if in_short_window else "，八季的窗口看不到它")
        + "，"
        + ("这条红线在 2016–2018 年长期只有几亿美元一格，" if early and max(early) < 1000 else "")
        + (f"整个窗口的负增量只有 {negative_increments} 次。" if negative_increments
           else "整个窗口没有一次负增量。")
    )
    highlights = [
        {
            "kind": "bar_line",
            "title": (
                f"AWS 收入 US${aws_revenue[-1] / 1000:.1f}B，环比增量 {money_bn(aws_increment, 2)} —— "
                + (f"是此前最大单季增量的 {aws_increment / largest_prior_increment:.1f} 倍" if aws_record
                   else f"低于 {long_labels[largest_prior_at]} 的纪录 "
                        f"US${largest_prior_increment / 1000:.2f}B")
            ),
            "xlabels": long_labels,
            "xstep": LONG_STEP,
            "bar": {
                "name": "AWS 收入",
                "color": "NAVY",
                "values": [value / 1000 for value in long_aws_revenue],
                "yfmt": "usd0",
            },
            "line": {
                "name": "环比绝对增量 (RHS) D",
                "color": "RED",
                "values": [None if value is None else value / 1000
                           for value in long_aws_sequential],
                "yfmt": "usd1",
            },
            "fmt": "usd0",
            "yfmt": "usd0",
            "label_fmt": "usd0",
            "ylab": "US$B",
            "ylab2": "环比增量 US$B",
            "note": aws_note,
            "src_extra": source_note(
                "AWS 分部收入来自各期 8-K EX-99.1 的 Supplemental 表与 10-Q 分部附注；环比增量为自算"),
        },
    ]

    # Segment margins, with this quarter's one-offs taken out where there are any.
    segment_note = ""
    if energy or tariff:
        flips = []
        if energy and (aws_om_reported - aws_om_prior_year) * (aws_om_adjusted - aws_om_prior_year) < 0:
            flips.append("AWS")
        if tariff and (na_om_reported - na_om_prior_year) * (na_om_adjusted - na_om_prior_year) < 0:
            flips.append("北美")
        segment_note = (
            "<b>" + ("两条线上各有一笔一次性收益" if energy and tariff else "有一条线上有一笔一次性收益")
            + (f"，剔除后{'与'.join(flips)}的方向就变了。</b>" if flips else "，剔除后同比方向都没变。</b>")
        )
        if energy:
            aws_bp = (aws_om_adjusted - aws_om_prior_year) * 100
            management = one_off.get("management_ex_derivative_margin_bp")
            segment_note += (
                f"AWS 的 {aws_om_reported:.1f}% 含 10-Q 披露的 US${energy}M "
                f"能源合约公允价值收益，剔除后 {aws_om_adjusted:.1f}%、同比 {aws_bp:+.0f}bp"
                + ("" if management is None else
                   f" —— 与管理层在电话会上给的「约 {management:+d}bp」对得上" if abs(aws_bp - management) <= 10
                   else f"，管理层在电话会上给的是「约 {management:+d}bp」")
                + "。"
            )
        if tariff:
            segment_note += (
                f"北美的 {na_om_reported:.1f}% 含 US${tariff}M 关税退款，"
                f"剔除后 {na_om_adjusted:.2f}%，"
                + (f"<b>低于去年同期的 {na_om_prior_year:.2f}%</b>，也就是零售侧本季其实是负经营杠杆。"
                   if na_om_adjusted < na_om_prior_year else
                   f"仍高于去年同期的 {na_om_prior_year:.2f}%。")
            )
    else:
        segment_note = "线上都是报告口径。"
    if one_off_items:
        reported_step = operating_margin[-1] - operating_margin[-2]
        adjusted_step = group_om_adjusted - group_om_previous
        segment_note += (
            f"集团层面剔除这{cn_count(len(one_off_items))}笔后经营利润率 {group_om_adjusted:.2f}%，上季 "
            f"{group_om_previous:.2f}%，"
            + ("环比实为持平略降" if -0.1 < adjusted_step < 0 else "环比实为持平略升" if 0 <= adjusted_step < 0.1
               else f"环比{'下降' if adjusted_step < 0 else '上升'} {abs(adjusted_step):.2f}pp")
            + (f" —— 账面上 {reported_step:+.2f}pp 的环比改善全部来自这{cn_count(len(one_off_items))}笔。"
               if reported_step > 0 >= adjusted_step else "。")
        )
    one_off_words = [f"{words} US${one_off[key]}M" for key, words in one_off_items]
    highlights.append({
        "kind": "lines",
        "title": (
            f"三个分部的经营利润率：北美剔除 US${tariff}M 关税退款后 {na_om_adjusted:.2f}%，"
            f"低于去年同期的 {na_om_prior_year:.2f}%"
            if tariff and na_om_adjusted < na_om_prior_year else
            f"三个分部的经营利润率：AWS {aws_om_reported:.1f}%、"
            f"北美 {na_om_reported:.1f}%、国际 {intl_margin[-1]:.1f}%"
        ),
        "xlabels": seg_labels[-12:],
        "series": [
            {"name": "AWS", "values": rounded(aws_margin[-12:]), "color": "NAVY"},
            {"name": "北美", "values": rounded(na_margin[-12:]), "color": "MBLUE"},
            {"name": "国际", "values": rounded(intl_margin[-12:]), "color": "GOLD"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "zero_base": True,
        "end_label": True,
        "ylab": "分部经营利润率",
        "note": segment_note,
        "src_extra": (
            "分部利润率为分部经营利润 ÷ 分部收入的自算值"
            + (f"；{cn_count(len(one_off_words))}笔一次性金额取自 {period} 10-Q 原文"
               f"（{'、'.join(one_off_words)}），不是电话会的约数" if one_off_words else "")
            + "。"
        ),
    })

    pre_tax_chart = None
    if snapshot is not None:
        pre_tax = snapshot["pre_tax_income_usd_m"][-1]
        other_income = snapshot["other_income_expense_net_usd_m"][-1]
        operating_pre_tax = pre_tax - other_income - one_off_total
        shares = snapshot["diluted_shares_m"][-1]
        deferred = snapshot["deferred_income_taxes_addback_usd_m"][-1]
        provision = -snapshot["provision_for_income_taxes_usd_m"][-1]
        low_rate, high_rate = TAX_RANGE_PCT
        eps_low = operating_pre_tax * (1 - high_rate / 100) / shares
        eps_high = operating_pre_tax * (1 - low_rate / 100) / shares
        note = ""
        if other_story is not None:
            note += (
                f"10-Q 明写：Other income 里 US${other_story['private_equity_upward_adjustment_usd_bn']:.1f}B "
                "是私募股权投资的向上重估，"
                f"「主要来自{other_story['primarily_from']}」，属 {other_story['fair_value_level']} 估值。"
            )
        note += (
            ("把它" if other_story is not None else "把 Other income ")
            + (f"和{cn_count(len(one_off_items))}笔一次性经营项一起剔除，" if one_off_items else "剔除，")
            + f"剩下 US${operating_pre_tax / 1000:.1f}B 才是经营口径。"
            "<b>本页刻意在税前口径上做这道减法</b>：换算成每股要先假设一个经营性税率，"
            + ("而这一季的实际税率被对未实现收益计提的递延税主导"
               f"（单季递延所得税加回 US${deferred / 1000:.1f}B），无法从报表直接分离。"
               if deferred * 2 > provision else "")
            + f"按 {low_rate}%–{high_rate}% 的税率区间换算，经营性摊薄每股收益落在 "
            f"US${eps_low:.2f}–US${eps_high:.2f}"
            + (f"，对照财报前市场预期的 US${consensus['diluted_eps_usd']:.2f}"
               if consensus is not None and "diluted_eps_usd" in consensus else "")
            + f"；而账面摊薄每股收益是 US${snapshot['diluted_eps_usd'][-1]:.2f}。"
        )
        cash_taxes = snapshot.get("cash_paid_for_income_taxes_ttm_usd_m") or []
        if (len(cash_taxes) == 3 and cash_taxes[0] and cash_taxes[-1] is not None
                and cash_taxes[-1] < cash_taxes[0]):
            note += (
                f"现金口径正好相反：滚动十二个月实付所得税 US${cash_taxes[-1] / 1000:.1f}B，去年同期 "
                f"US${cash_taxes[0] / 1000:.1f}B，少了 {(1 - cash_taxes[-1] / cash_taxes[0]) * 100:.0f}% —— "
                "税前利润大涨的同时，递延所得税把一部分税款推到了以后，经营现金流也因此被抬高了一块。"
            )
        pre_tax_chart = {
            "kind": "bars_labeled",
            "title": (
                f"US${pre_tax / 1000:.1f}B 的税前利润里，US${other_income / 1000:.1f}B 不是经营挣来的"
            ),
            "xlabels": (["税前利润（GAAP）", "其中：Other income, net"]
                        + ([f"其中：{cn_count(len(one_off_items))}笔一次性经营项"] if one_off_items else [])
                        + ["经营性税前利润 D"]),
            "values": ([pre_tax / 1000, other_income / 1000]
                       + ([one_off_total / 1000] if one_off_items else [])
                       + [operating_pre_tax / 1000]),
            "legend": "US$B",
            "fmt": "usd1",
            "yfmt": "usd1",
            "label_fmt": "usd1",
            "ylab": "US$B",
            "note": note,
            "src_extra": (
                f"税前利润与 Other income 来自 {period} 合并损益表；"
                + (f"US${other_story['private_equity_upward_adjustment_usd_bn']:.1f}B 的构成与"
                   f"「主要来自 {other_story['short']}」的表述来自 10-Q；" if other_story is not None else "")
                + "每股区间为按税率假设的换算，非公司口径，也不是公司定义的 non-GAAP 指标。"
            ),
        }
        highlights.append(pre_tax_chart)

    fcf_note = ""
    if errata is not None:
        fcf_note += (errata.get("lead", "")
                     + f"本地稿把 {money_bn(latest_fcf)} 记为「{errata['claim']}」；")
    fcf_note += "按公司自己在每季新闻稿里公布的 TTM 自由现金流，"
    if prior_negative_run:
        fcf_note += (
            f"上一轮资本开支周期里它{'已经' if latest_fcf < 0 else '曾'}连续 {prior_negative_run} 个季度为负，"
            f"最深处是 {cash_labels[trough_index]} 的 {money_bn(fcf_ttm[trough_index])}，"
            "只不过公司每份新闻稿只列六个季度，看单季那张表看不到上一轮。"
        )
        if latest_fcf < 0:
            fcf_note += (
                f"上一轮从转负到转正用了 {prior_negative_run} 个季度；"
                + ("这一轮的资本开支还在加速，" if capex_accelerating else "")
                + (f"公司指引全年约 US${fy_capex['usd_bn']:.0f}B，{ytd['done']}已用净额 "
                   f"US${ytd['spent'] / 1000:.1f}B。" if ytd else "")
            )
    else:
        fcf_note += f"它在这 {len(fcf_ttm)} 个季度里此前没有为负过。"
    if latest_fcf < 0 and trough_index != len(fcf_bn) - 1:
        fcf_tail = f" —— 但 {cash_labels[trough_index]} 的 {money_bn(fcf_ttm[trough_index])} 更深"
    elif latest_fcf < 0:
        fcf_tail = " —— 是这条序列里最深的一格"
    else:
        fcf_tail = ""
    highlights.append({
        "kind": "diverging_bars",
        "title": (f"TTM 自由现金流{'转为' if turned_negative else '为'} {money_bn(latest_fcf)}"
                  + fcf_tail),
        "xlabels": cash_labels,
        "values": rounded(fcf_bn, 3),
        "legend": "TTM 自由现金流（公司披露）",
        "positive_label": "正自由现金流",
        "negative_label": "负自由现金流",
        "fmt": "usd0",
        "yfmt": "usd0",
        "label_fmt": "usd0",
        "ylab": "US$B",
        "zero_line": True,
        "xstep": 2,
        "note": fcf_note,
        "src_extra": (
            f"{len(fcf_ttm)} 个季度全部是公司披露值：各季 8-K EX-99.1 的 Supplemental 表直接列出 TTM 自由现金流，"
            "定义为经营现金流减「购买物业及设备，扣除出售与激励所得」。相邻两份新闻稿重叠的季度已逐个核对一致。"
        ),
    })

    others = [LINE_SHORT[name] for name in accelerating if name != "advertising_services"]
    ads_step = ads_yoy[-1] - ads_yoy[-2]
    if "advertising_services" in accelerating:
        ads_title = (f"广告同比加速到 {ads_yoy[-1]:.1f}%，"
                     + (f"是{cn_count(len(drawn_lines))}条零售线里唯一在加速的" if not others else
                        f"{cn_count(len(drawn_lines))}条零售线全部在加速" if len(accelerating) == len(drawn_lines) else
                        f"{cn_count(len(drawn_lines))}条零售线里有{cn_count(len(accelerating))}条在加速"))
    else:
        ads_title = f"广告同比 {ads_yoy[-1]:.1f}%，较上季放缓"
    ads_note = (
        f"广告本季 US${lines['advertising_services'][-1] / 1000:.1f}B、同比 {ads_yoy[-1]:.1f}%，"
        f"较上季{'加速' if ads_step > 0 else '放缓'} {abs(ads_step):.1f}pp。"
    )
    if others:
        ads_note += (("与".join(others) if len(others) == 2 else "、".join(others))
                     + f"{cn_count(len(others))}条同期也在加速")
        if shift is not None:
            ads_note += (
                f"，但那{cn_count(len(others))}条的加速里含 {shift['event']} 的日历移位 —— "
                f"今年 {shift['event']} 落在 {quarter_word}，去年整场在 {shift['out_of']}。"
                f"<b>公司只给了 {shift['bridge_for']} 的桥（剔除后同比高出近 {shift['bridge_bps']}bp），"
                f"没有给 {quarter_word} 的桥</b>，"
                f"所以本页不发布任何「剔除 {shift['event']} 后的 {quarter_word} 增速」数字，只标注这个不对称披露本身。"
            )
        else:
            ads_note += "。"
    ads_note += f"广告线的起点是 {lines['advertising_first_reported']}：在此之前它并入 Other，公司未单列。"
    highlights.append({
        "kind": "lines",
        "title": ads_title,
        "xlabels": line_labels[ads_from:],
        "xstep": 2,
        "series": [
            {"name": "广告服务 D", "values": rounded(ads_yoy[ads_from:]), "color": "NAVY"},
            {"name": "在线商店 D", "values": rounded(online_yoy[ads_from:]), "color": "MBLUE"},
            {"name": "第三方卖家服务 D", "values": rounded(third_party_yoy[ads_from:]), "color": "GOLD"},
            {"name": "订阅服务 D", "values": rounded(subscription_yoy[ads_from:]), "color": "GRAY"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "zero_base": True,
        "end_label": True,
        "ylab": "同比增速",
        "note": ads_note,
        "src_extra": source_note(
            "七条分项收入来自各期 8-K EX-99.1 的 Supplemental 表；同比为自算"),
    })

    # Quarters in which gross capex exceeded operating cash flow, over the
    # quarters the capex line has a filed number for.
    reported = [index for index, value in enumerate(long_capex) if value is not None]
    over = [index for index in reported if long_capex[index] > long_ocf[index]]
    over_runs = runs([index in over for index in range(len(long_quarters))])
    unpaid = snapshot["increase_in_unpaid_capex_usd_m"][-1] if snapshot is not None else None
    last_run = over_runs[-1] if over_runs else None
    capex_basis = long["capital_expenditures_basis"]
    ocf_note = (
        "亚马逊的 10-Q 现金流量表同时列示三个月、年初至今与滚动十二个月三栏，"
        "所以这里的单季现金流是<b>申报值本身</b>，不是两个年初至今值相减的结果。"
        f"本季资本开支总额 US${capex[-1] / 1000:.1f}B，扣除出售与激励所得后净额 "
        f"US${net_capex / 1000:.1f}B；两者的差就是自由现金流那张图的分母口径。"
        + ("" if unpaid is None else
           f"同季计入应付账款但尚未支付的资本开支还{'增加' if unpaid > 0 else '减少'}了 "
           f"US${abs(unpaid) / 1000:.1f}B"
           + ("，也就是现金口径本身还落后于已经建成的资产。" if unpaid > 0 else "。"))
        + f"资本开支有申报值的 {len(reported)} 季里，它高于经营现金流的季度共有 {len(over)} 个"
        + ("" if last_run is None else
           (f"，最近一段是 {span_label(long_labels, *last_run)}（连续{cn_count(last_run[1] - last_run[0] + 1)}季）"
            if last_run[0] != last_run[1] else f"，最近一次是 {long_labels[last_run[0]]}"))
        + "。"
        + f"<b>资本开支那条柱子在 {int(long_quarters[capex_from][:4]) - 1} 年是空的，那是修掉的一处混口径</b>："
        + capex_basis["why_2016_is_empty"]
    )
    highlights.append({
        "kind": "grouped_bars",
        "title": (
            f"单季经营现金流 US${operating_cash_flow[-1] / 1000:.1f}B，"
            + (f"被 US${capex[-1] / 1000:.1f}B 的资本开支盖过" if capex[-1] > operating_cash_flow[-1]
               else f"盖过 US${capex[-1] / 1000:.1f}B 的资本开支")
        ),
        "xlabels": long_labels,
        "xstep": LONG_STEP,
        "groups": [
            {"name": "经营现金流", "color": "NAVY",
             "values": [value / 1000 for value in long_ocf]},
            {"name": "购买物业及设备（gross）", "color": "GOLD",
             "values": [None if value is None else value / 1000
                        for value in long_capex]},
        ],
        "fmt": "usd0",
        "label_fmt": "usd0",
        "ylab": "US$B",
        "note": ocf_note,
        "src_extra": source_note("经营现金流与资本开支为各期现金流量表的三个月申报值"),
        "ref": "EX_OCF",
    })

    # Capital structure: the balance sheet's long-term debt and the income
    # statement's interest expense, on the same ten-year axis. The comparison
    # point is the last year-end balance, the one the 10-K printed.
    long_debt = long["long_term_debt_usd_m"]
    long_interest = long["interest_expense_usd_m"]
    year_end = long_quarters.index(f"{int(year_word) - 1}Q4")
    since = len(long_quarters) - 1 - year_end
    since_words = {1: "一个季度", 2: "半年", 3: "九个月", 4: "一年"}[since]
    interest_yoy = pct_change(long_interest[-1], long_interest[-5])
    debt_peak = max(range(len(long_debt) - 1), key=lambda index: long_debt[index])
    interest_peak = max(range(len(long_interest) - 1), key=lambda index: long_interest[index])
    debt_record = long_debt[-1] > long_debt[debt_peak]
    interest_record = long_interest[-1] > long_interest[interest_peak]
    # The high-water marks before this fiscal year began: the quarter just
    # before this one is part of the same climb and says nothing about it.
    earlier_debt = max(range(year_end + 1), key=lambda index: long_debt[index])
    earlier_interest = max(range(year_end + 1), key=lambda index: long_interest[index])
    debt_note = (
        ("<b>两项都是这 " + f"{len(long_quarters)} 季里最高。</b>" if debt_record and interest_record else "")
        + ("" if debt_record else f"长期负债仍低于 {long_labels[debt_peak]} 的 {money_bn(long_debt[debt_peak])}。")
        + (f"今年以前长期负债的高点是 {long_labels[earlier_debt]} 的 {money_bn(long_debt[earlier_debt])}，"
           f"利息费用的高点是 {long_labels[earlier_interest]} 的 US${long_interest[earlier_interest]:,.0f}M。")
        + (f"{YTD_WORDS[int(quarter_word[1])][0]}新发长期债 "
           f"US${capital['proceeds_from_long_term_debt_ytd_usd_m'] / 1000:.1f}B（10-Q 现金流量表）。"
           if capital is not None and int(quarter_word[1]) in YTD_WORDS else "")
        + ("同一季经营现金流盖不住资本开支（Exhibit {EX_OCF}）。" if capex[-1] > operating_cash_flow[-1] else "")
        + (f"电话会上被问到未来两年扩建的资金从哪来，CFO 的回答停在「{capital['funding_answer']}」。"
           if capital is not None and capital.get("funding_answer") else "")
        + "长期负债为资产负债表期末值，不含一年内到期的部分；利息费用为损益表的三个月值，第四季按全年 − 前三季倒推。"
    )
    highlights.append({
        "ref": "EX_DEBT",
        "kind": "bar_line_dual",
        "title": (
            f"长期负债{since_words}从 {money_bn(long_debt[year_end])} "
            f"{'升到' if long_debt[-1] > long_debt[year_end] else '降到'} {money_bn(long_debt[-1])}，"
            f"单季利息费用 US${long_interest[-1] / 1000:.2f}B、同比 {interest_yoy:+.0f}%"
        ),
        "xlabels": long_labels,
        "xstep": LONG_STEP,
        "bar": {"name": "长期负债（期末）", "values": [value / 1000 for value in long_debt], "color": "NAVY"},
        "line": {"name": "单季利息费用 (RHS)", "values": [value / 1000 for value in long_interest],
                 "color": "GOLD", "yfmt": "usd1"},
        "fmt": "usd0",
        "yfmt": "usd0",
        "label_fmt": "usd0",
        "ylab": "US$B",
        "ylab2": "利息费用 US$B",
        "note": debt_note,
        "src_extra": source_note(
            "长期负债与利息费用来自各期 10-Q / 10-K 的资产负债表与损益表（XBRL LongTermDebtNoncurrent、"
            "InterestExpense / InterestExpenseNonoperating），2016–2025 每年四季之和与 10-K 全年相等"),
    })

    # ── section three: this quarter's analysis, watched into the next one ─────
    # Every quarter's analysis ends with an observation table, and the page is
    # the four sections or it is not the page: a roll without `next_kpi` stops.
    if next_kpi is None:
        raise ValueError(f"series block `next_kpi` is missing for {period}: section three is this quarter's "
                         "analysis's observation table")
    if next_kpi.get("for_period") != following_period(period):
        raise ValueError(f"series block `next_kpi` is stamped for {next_kpi.get('for_period')!r}, "
                         f"but the quarter after {period} is {following_period(period)!r}")
    if next_kpi.get("set_in") != period:
        raise ValueError(f"series block `next_kpi` says it was set in {next_kpi.get('set_in')!r}, not {period!r}")
    next_due, next_later = threshold_lines(next_kpi, specs, "current", period)
    next_findings = row_findings(next_kpi, next_due, next_later, "current")
    next_reading_charts = reading_charts(next_due, specs, "current", "next", next_kpi["set_in"], next_later)
    not_drawn = [row for row in next_kpi["rows"] if row.get("not_drawn_reason")]
    half_known = [row for row in next_kpi["rows"] if row.get("bull_unquantified") or row.get("risk_unquantified")]
    reversed_lines = [line for line in next_due if line["direction"] == "down"]
    next_overview = headroom_exhibit(
        f"下季 {len(next_due)} 条阈值：" + tier_summary(next_due, "current", "next"),
        [dict(line, metric=f"{TIER_SHORT[line['tier']]}：{line['metric']}") for line in next_due],
        "current",
        (
            "正值 = 当前值在有利一侧（" + "、".join(
                {"risk": "风险线之内", "bull": "多头确认线之上"}[tier]
                for tier in ("risk", "bull") if any(line["tier"] == tier for line in next_due))
            + "），负值 = 在不利一侧；"
            f"阈值逐字取自本季（{next_kpi['set_in']}）本地分析的{next_kpi['section']}，当前值是 {period} 的申报值"
            + ("，口径与第一节的总览相同。" if prior_kpi is not None else "。")
            + "".join(f"{line['metric']}那条方向相反：{TRIGGER_WORDS[line['op']]} "
                      f"{threshold_text(line['unit'], line['threshold'])} 即越线，安全侧在下方。"
                      for line in reversed_lines)
            + "".join(f"第{cn_ordinal(row['row'])}行的"
                      + ("多头条件" if row.get("bull_unquantified") else "风险条件")
                      + f"还要求「{row.get('bull_unquantified') or row.get('risk_unquantified')}」，这一半要看下季申报。"
                      for row in half_known)
            + "".join(f"第{cn_ordinal(row['row'])}行（{row['subject']}）不画："
                      f"{fill_story(row['not_drawn_reason'], story_values)}。" for row in not_drawn)
            + (f"有时间序列的{cn_count(len(next_reading_charts))}个读数各画一张图（Exhibit "
               + "、".join("{" + chart["ref"] + "}" for chart in next_reading_charts) + "）。"
               if next_reading_charts else "")
        ),
        src_extra=(
            f"阈值取自本季（{next_kpi['set_in']}）本地分析稿，不是公司指引；当前值为 {period} 的申报值与自算值，"
            "逐线、逐行与报告留给下季的待验证问题见核对抽屉。"
        ),
    )
    next_overview["ref"] = "EX_NEXT"
    next_overview["legend"] = "当前值距下季阈值的余量"
    next_overview["positive_label"] = "在有利一侧"
    next_overview["negative_label"] = "在不利一侧"
    next_charts = [next_overview] + next_reading_charts
    next_tables = threshold_tables(next_kpi, next_due, next_later, next_findings, specs, "current", "next")
    followups = next_kpi.get("followups") or []
    added = next_kpi.get("page_added") or []
    if followups or added:
        next_tables.append({
            "n": 0,
            "title": (f"本季（{next_kpi['set_in']}）本地分析留给下季的 {len(followups)} 条待验证问题"
                      "（下季第 0 节闭环）" + ("，另附本页补充" if added else "")),
            "headers": ["#", "问题（原文节录）", "读法与现状"],
            "rows": ([[str(index), item["question"], fill_story(item["reading"], story_values)]
                      for index, item in enumerate(followups, 1)]
                     + [["补", item["question"], fill_story(item["reading"], story_values)] for item in added]),
        })

    # ── section four: the routine record ─────────────────────────────────────
    revenue_yoy_shown = long_revenue_yoy[yoy_from:]
    yoy_labels = long_labels[yoy_from:]
    printed = [round(value, 1) for value in revenue_yoy_shown]
    rises = runs([False] + [b > a for a, b in zip(printed, printed[1:])])
    episodes = [r for r in rises if r[1] - r[0] + 1 >= ACCELERATION_EPISODE]
    revenue_years = years_of(len(revenue_yoy_shown))
    current_episode = episodes[-1] if episodes and episodes[-1][1] == len(printed) - 1 else None

    def episode_words(episode: tuple[int, int]) -> str:
        return (f"{span_label(yoy_labels, *episode)} 那一段最高到 "
                f"{max(printed[episode[0]:episode[1] + 1]):.1f}%")

    if current_episode is not None:
        earlier = episodes[:-1]
        length = current_episode[1] - current_episode[0] + 1
        revenue_note = (
            f"<b>八季的窗口里本季是一条上行线，{revenue_years}年的窗口里它是第{cn_ordinal(len(episodes))}段"
            f"连升{cn_count(ACCELERATION_EPISODE)}季以上的回升</b>"
            + ("：" + "，".join(episode_words(e) for e in earlier) + "；" if earlier else "：")
            + f"这一段已连升{cn_count(length)}季、到 {printed[-1]:.1f}%"
            + (f"，是{cn_count(len(episodes))}段里最长的" if earlier and
               length > max(e[1] - e[0] + 1 for e in earlier) else "")
            + "。"
            + (f"这一次与前{cn_count(len(earlier))}次的区别要靠下一张资本强度图判断，不是靠这一张。"
               if earlier else "")
        )
    else:
        revenue_note = (
            f"{revenue_years}年的窗口里同比连升{cn_count(ACCELERATION_EPISODE)}季以上的一共"
            f"{cn_count(len(episodes))}段"
            + ("（" + "，".join(episode_words(e) for e in episodes) + "）" if episodes else "")
            + "，本季不在其中。"
        )
    if shift is not None:
        revenue_note += (f"本季的同比里还含 {shift['event']} 从 {shift['out_of']} 移到 {quarter_word} "
                         f"的日历影响，公司未给 {quarter_word} 的还原桥。")

    intensity_shown = long_intensity[capex_from:]
    cycle = [index for index, quarter in enumerate(long_quarters)
             if PREVIOUS_CYCLE[0] <= quarter <= PREVIOUS_CYCLE[1] and long_intensity[index] is not None]
    cycle_peak = max(cycle, key=lambda index: long_intensity[index])
    cycle_trough = min((index for index in cycle if index > cycle_peak),
                       key=lambda index: long_intensity[index])
    cycle_fcf = {quarter_key(p): value for p, value in zip(cash["periods"], fcf_ttm)}
    cycle_fcf_values = [cycle_fcf.get(long_quarters[index]) for index in cycle]
    fcf_turned = (min(value for value in cycle_fcf_values if value is not None) < 0
                  and (cycle_fcf.get(long_quarters[cycle_trough]) or 0) > 0)
    intensity_now = long_intensity[-1]
    intensity_note = (
        f"<b>这条线是本页的主轴</b>：{PREVIOUS_CYCLE[0][:4]}–{long_quarters[cycle_peak][:4]} 年那一轮"
        f"把资本强度推到 {long_intensity[cycle_peak]:.1f}%（{long_labels[cycle_peak]}），"
        f"随后回落到 {long_intensity[cycle_trough]:.1f}%（{long_labels[cycle_trough]}）"
        + ("，自由现金流也随之从深负转正" if fcf_turned else "")
        + f" —— 当前的 {intensity_now:.1f}% 是上一轮高点的 {intensity_now / long_intensity[cycle_peak]:.1f} 倍"
        + ("，且还没有回落的迹象" if intensity_now >= max(intensity_shown) else "")
        + "。"
        + (f"公司指引全年资本开支约 US${fy_capex['usd_bn']:.0f}B（自约 US${fy_capex['prior_usd_bn']:.0f}B "
           f"{'上修' if fy_capex['usd_bn'] > fy_capex['prior_usd_bn'] else '下修'}，{fy_capex['reason']}），"
           if fy_capex is not None and "prior_usd_bn" in fy_capex else
           f"公司指引全年资本开支约 US${fy_capex['usd_bn']:.0f}B，" if fy_capex is not None else "")
        + (f"{ytd['done']}净额已用 US${ytd['spent'] / 1000:.1f}B，"
           f"隐含{ytd['rest']}还要花约 US${ytd['rest_bn']:.1f}B。" if ytd else "")
        + f"起点是 {long_labels[capex_from]}：{capex_basis['chart_start_reason']}。"
    )

    dda_from = leading_gap(long_dda_intensity)
    multiple = capex[-1] / dda[-1]
    routine = [
        {
            "kind": "lines",
            "title": (
                f"总收入同比 {long_revenue_yoy[-1]:.1f}%，{revenue_years}年区间 "
                f"{min(revenue_yoy_shown):.0f}–{max(revenue_yoy_shown):.0f}%"
            ),
            "xlabels": yoy_labels,
            "xstep": LONG_STEP,
            "series": [
                {"name": "总收入同比 D", "values": rounded(revenue_yoy_shown), "color": "NAVY"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "zero_base": True,
            "end_label": True,
            "ylab": "同比增速",
            "note": revenue_note,
            "src_extra": source_note(
                "收入逐季来自各期 10-Q / 10-K（第四季为全年 − 前三季，2019 与 2020 另有直接申报的三个月事实）"),
        },
        {
            "kind": "lines",
            "title": (
                f"资本强度{years_of(len(intensity_shown))}年从 {long_intensity[capex_from]:.1f}% "
                f"{'升到' if intensity_now > long_intensity[capex_from] else '降到'} {intensity_now:.1f}%，"
                + ("已越过上一轮周期的高点" if intensity_now > long_intensity[cycle_peak]
                   else "仍低于上一轮周期的高点")
            ),
            "xlabels": long_labels[capex_from:],
            "xstep": LONG_STEP,
            "series": [
                {"name": "CapEx / 收入 D", "values": rounded(intensity_shown), "color": "NAVY"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "zero_base": True,
            "end_label": True,
            "ylab": "占收入比",
            "note": intensity_note,
            "src_extra": source_note(
                "CapEx / 收入为自算；资本开支为各期现金流量表的三个月申报值，第四季为全年 − 前三季"),
        },
        {
            "kind": "lines",
            "title": (
                f"折旧摊销占收入比{'升到' if long_dda_intensity[-1] > long_dda_intensity[-5] else '降到'} "
                f"{long_dda_intensity[-1]:.1f}%，"
                f"{'但资本开支已是折旧的' if multiple > 1 else '资本开支是折旧的'} {multiple:.1f} 倍"
            ),
            "xlabels": long_labels[dda_from:],
            "xstep": LONG_STEP,
            "series": [
                {"name": "折旧摊销 / 收入 D",
                 "values": rounded(long_dda_intensity[dda_from:]),
                 "color": "NAVY"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "zero_base": True,
            "end_label": True,
            "ylab": "占收入比",
            "note": (
                "折旧是资本强度进入利润表的通道，而它<b>还没有走完</b>："
                f"本季资本开支是当季折旧摊销的 {multiple:.1f} 倍，"
                "上一轮周期里这个倍数回到 1 附近时，折旧占收入比才见顶。"
                + ("换句话说，这条线未来几年只会继续上行，" if multiple > 1 else "")
                + f"而它{'上行' if multiple > 1 else '走'}的速度与 AWS 收入增量的赛跑，"
                f"才是 {int(year_word) + 1} 年利润率方向的真正变量。"
            ) if multiple > 1 else (
                f"本季资本开支是当季折旧摊销的 {multiple:.1f} 倍，折旧占收入比的上行已失去新增资本开支的推力。"
            ),
            "src_extra": source_note(
                "折旧摊销为现金流量表的「物业设备与自制内容、经营租赁资产及其他的折旧摊销」三个月申报值"),
        },
    ]

    gap = min(income - revenue_share for income, revenue_share
              in zip(long_aws_income_share, long_aws_share))
    over_hundred = [index for index, value in enumerate(long_aws_income_share) if value > 100]
    over_hundred_runs = runs([index in over_hundred for index in range(len(long_quarters))])
    share_top = max(over_hundred, key=lambda index: long_aws_income_share[index]) if over_hundred else None
    share_years = years_of(len(long_quarters))
    routine.append({
        "kind": "lines",
        "title": (
            f"AWS 占收入 {long_aws_share[-1]:.1f}%，却占了集团经营利润的 "
            f"{long_aws_income_share[-1]:.1f}%"
        ),
        "xlabels": long_labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": "AWS 占总收入 D", "values": rounded(long_aws_share), "color": "NAVY"},
            {"name": "AWS 占集团经营利润 D", "values": rounded(long_aws_income_share), "color": "GOLD"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "zero_base": True,
        "end_label": True,
        "ylab": "占比",
        "note": (
            (f"两条线{share_years}年都没有收敛过" if gap > 0 else "两条线曾经交会")
            + (f"；利润占比超过 100% 的有 {len(over_hundred)} 季（"
               + "、".join(span_label(long_labels, *r) for r in over_hundred_runs)
               + f"），也就是那几季北美与国际两个分部合计亏损，最高是 {long_labels[share_top]} 的 "
               f"{long_aws_income_share[share_top]:.0f}%" if over_hundred else "")
            + "。"
            + "本季收入占比 "
            f"{long_aws_share[-1]:.1f}%、利润占比 {long_aws_income_share[-1]:.1f}%，"
            + ("意味着市场对这家公司的定价越来越取决于"
               if long_aws_income_share[-1] > long_aws_income_share[-5] else "市场对这家公司的定价仍取决于")
            + f"一个占它{cn_fraction(long_aws_share[-1] / 100)}收入的分部"
            + (f" —— 而那个分部的合约集中度公司连续"
               f"{cn_count(concentration['top_three_share_undisclosed_quarters'])}季拒绝披露"
               if concentration is not None else "")
            + "。"
            + f"序列起点是 {long_quarters[0]}：公司 2015 年才改成三分部，"
            "且 2016 年起才把股权激励费用分摊进分部并追溯调整，"
            "更早的分部利润与今天不同口径。"
        ),
        "src_extra": source_note(
            "AWS 分部收入与经营利润来自各期 8-K EX-99.1 与 10-Q 分部附注；两条占比为自算"),
    })

    exhibits = number_exhibits(settled_charts + highlights + next_charts + routine)
    exhibits = resolve_exhibit_refs(exhibits)
    settled_count, highlight_count = len(settled_charts), len(highlights)
    next_count = len(next_charts)
    next_table_number = len(exhibits) + 2

    tables = settled_tables + [
        {
            "n": 0,
            "title": "指引与实际逐季对照（US$B，全部为公司披露值）",
            "headers": ["季度", "净销售额指引", "净销售额实际", "判定",
                        "经营利润指引", "经营利润实际", "判定", "汇率假设"],
            "rows": [
                [
                    verdicts["quarters"][index],
                    f"{low:.1f}–{high:.1f}",
                    "—" if actual is None else f"{actual:.3f}",
                    "待披露" if actual is None else (
                        "超上限" if actual > high else ("跌破下限" if actual < low else "区间内")),
                    f"{income_low:.1f}–{income_high:.1f}",
                    "—" if income_actual is None else f"{income_actual:.3f}",
                    "待披露" if income_actual is None else (
                        "超上限" if income_actual > income_high
                        else ("跌破下限" if income_actual < income_low else "区间内")),
                    "—" if bps is None else
                    f"{'有利' if direction == 'favorable' else '不利'} {bps}bp",
                ]
                for index, (low, high, actual, income_low, income_high, income_actual, bps, direction)
                in enumerate(zip(
                    guide["net_sales_low_bn"],
                    guide["net_sales_high_bn"],
                    guide["actual_net_sales_bn"],
                    guide["operating_income_low_bn"],
                    guide["operating_income_high_bn"],
                    guide["actual_operating_income_bn"],
                    guide["fx_bps"],
                    guide["fx_direction"],
                ))
            ],
        },
    ]
    tables += next_tables
    segment_rows = min(12, len(seg_periods))
    tables += [
        {
            "n": 0,
            "title": f"三个分部逐季收入与经营利润（US$M，最近{cn_count(segment_rows)}季）",
            "headers": ["季度", "北美收入", "北美经营利润", "北美 OM D",
                        "国际收入", "国际经营利润", "国际 OM D",
                        "AWS 收入", "AWS 经营利润", "AWS OM D"],
            "rows": [
                [
                    seg_periods[index],
                    f"${segments['na_revenue'][index]:,.0f}M",
                    f"${segments['na_operating_income'][index]:,.0f}M",
                    f"{na_margin[index]:.2f}%",
                    f"${segments['intl_revenue'][index]:,.0f}M",
                    f"${segments['intl_operating_income'][index]:,.0f}M",
                    f"{intl_margin[index]:.2f}%",
                    f"${segments['aws_revenue'][index]:,.0f}M",
                    f"${segments['aws_operating_income'][index]:,.0f}M",
                    f"{aws_margin[index]:.2f}%",
                ]
                for index in range(len(seg_periods) - segment_rows, len(seg_periods))
            ],
        },
        {
            "n": 0,
            "title": f"{cn_count(len(periods))}季基础数据（US$M；前四季只用于计算同比）",
            "headers": ["季度", "总收入", "经营利润", "OM D", "净利润",
                        "经营现金流", "购买物业及设备", "折旧摊销", "股权激励", "融资租赁本金"],
            "rows": [
                [
                    p,
                    f"${revenue[index]:,.0f}M",
                    f"${operating_income[index]:,.0f}M",
                    f"{operating_margin[index]:.2f}%",
                    f"${quarterly['net_income'][index]:,.0f}M",
                    f"${operating_cash_flow[index]:,.0f}M",
                    f"${capex[index]:,.0f}M",
                    f"${dda[index]:,.0f}M",
                    f"${quarterly['share_based_compensation'][index]:,.0f}M",
                    f"${quarterly['finance_lease_principal'][index]:,.0f}M",
                ]
                for index, p in enumerate(periods)
            ],
        },
        {
            "n": 0,
            "title": "公司披露的滚动十二个月现金流（US$M）",
            "headers": ["季度", "TTM 经营现金流", "TTM 资本开支净额", "TTM 自由现金流", "全球运输成本", "员工数"],
            "rows": [
                [
                    cash["periods"][index],
                    f"${cash['operating_cash_flow_ttm'][index]:,.0f}M",
                    f"${cash['net_capex_ttm'][index]:,.0f}M",
                    (lambda value: f"-${abs(value):,.0f}M" if value < 0 else f"${value:,.0f}M")(
                        cash["free_cash_flow_ttm"][index]),
                    f"${cash['worldwide_shipping_costs'][index]:,.0f}M"
                    if cash["worldwide_shipping_costs"][index] is not None else "—",
                    f"{cash['employees'][index]:,.0f}"
                    if cash["employees"][index] is not None else "—",
                ]
                for index in range(len(cash["periods"]) - 12, len(cash["periods"]))
            ],
        },
        ai_capex_cycle_table(0),
    ]
    for offset, table in enumerate(tables):
        table["n"] = next_table_number + offset

    # ── the release's forward block ──────────────────────────────────────────
    guided = guide["quarters"]
    guidance_payload = None
    if guide["actual_net_sales_bn"][-1] is None:
        next_quarter = guided[-1]
        sales_range = (guide["net_sales_low_bn"][-1], guide["net_sales_high_bn"][-1])
        income_range = (guide["operating_income_low_bn"][-1], guide["operating_income_high_bn"][-1])
        forward = guidance if guidance is not None and guidance["for_period"] == next_quarter else None
        year_ago = f"{next_quarter.split()[0]} {int(next_quarter.split()[1]) - 1}"
        rows = [
            ["净销售额",
             f"US${sales_range[0]:.1f}B – US${sales_range[1]:.1f}B",
             (f"同比 +{forward['net_sales_growth_pct'][0]}% ~ +{forward['net_sales_growth_pct'][1]}%；"
              if forward is not None else "")
             + f"中值较本季实际 {pct_change(sum(sales_range) / 2 * 1000, revenue[-1]):+.1f}%"],
            ["经营利润",
             f"US${income_range[0]:.1f}B – US${income_range[1]:.1f}B",
             # Guidance-table cells are escaped by the renderer, so no markup
             # here: a <b> would print as literal angle brackets.
             (f"上年同期 US${operating_income[periods.index(year_ago)] / 1000:.1f}B；"
              if year_ago in periods else "")
             + f"区间上限 US${income_range[1]:.1f}B "
             f"{'也低于' if income_range[1] * 1000 < operating_income[-1] else '高于'}本季实际 "
             f"US${operating_income[-1] / 1000:.1f}B"],
        ]
        if guide["fx_bps"][-1] is not None:
            rows.append(["汇率假设",
                         f"{'有利' if guide['fx_direction'][-1] == 'favorable' else '不利'}影响约 "
                         f"{guide['fx_bps'][-1]}bp",
                         "公司在指引段落中给出"])
        if shift is not None and shift["bridge_for"] == next_quarter.split()[0]:
            rows.append([f"{shift['event']} 还原", f"剔除后同比高近 {shift['bridge_bps']}bp",
                         f"公司只给了 {shift['bridge_for']} 的还原口径，未给 {quarter_word} 的"])
        if fy_capex is not None:
            rows.append(["全年现金资本开支", f"US${fy_capex['usd_bn']:.0f}B",
                         (f"自 US${fy_capex['prior_usd_bn']:.0f}B "
                          f"{'上修' if fy_capex['usd_bn'] > fy_capex['prior_usd_bn'] else '下修'}"
                          if "prior_usd_bn" in fy_capex else "")
                         + (f"；{ytd['done']}净额 US${ytd['spent'] / 1000:.1f}B，"
                            f"隐含{ytd['rest']}约 US${ytd['rest_bn']:.1f}B" if ytd else "")])
        guidance_payload = {
            "title": f"公司对 {next_quarter} 的指引（业绩新闻稿原文口径）",
            "headers": ["项目", "指引", "对照"],
            "rows": rows,
            "note": (
                f"净销售额与经营利润两行来自 {period} 业绩 8-K EX-99.1 的「Financial Guidance」段；"
                + ("全年资本开支只在电话会给出，不在申报文件的指引段里，故单独标注。" if fy_capex is not None else "")
                + (f"指引另假设{forward['assumptions_short']}。" if forward is not None else "")
                + f"本页第一节给出这套指引过去 {verdicts['finished']} 季的兑现记录。"
            ),
        }

    # ── headline and the three cards ─────────────────────────────────────────
    stock_margin = aws_om_adjusted
    # An incremental margin only means something on an increment: a quarter in
    # which AWS revenue fell says so instead.
    grew = aws_increment > 0
    aws_clause = (
        f"AWS 环比{'增量' if grew else '减少'} {money_bn(abs(aws_increment), 2)}"
        + (" 创纪录" if aws_record else "")
        + (f"、增量利润率 {aws_increment_margin:.0f}% {'高于' if aws_increment_margin > stock_margin else '低于'}存量"
           if grew else "")
        + (f"，{story['headline_verdict']}" if story.get("headline_verdict") else "")
    )
    clauses = [aws_clause]
    if snapshot is not None:
        pre_tax = snapshot["pre_tax_income_usd_m"][-1]
        other_income = snapshot["other_income_expense_net_usd_m"][-1]
        if other_income > pre_tax - other_income:
            clauses.append(
                f"但 US${snapshot['diluted_eps_usd'][-1]:.2f} 的摊薄每股收益背后是 "
                f"US${other_income / 1000:.1f}B 的税前 Other income"
                + (f"，其中 US${other_story['private_equity_upward_adjustment_usd_bn']:.1f}B 是 "
                   f"{other_story['holding']}的一次公允价值上调" if other_story is not None else "")
            )
    fcf_clause = f"TTM 自由现金流{'转为' if turned_negative else '为'} {money_bn(latest_fcf)}"
    if fy_capex is not None and "prior_usd_bn" in fy_capex:
        fcf_clause += (f"，同一场电话会把全年资本开支从约 US${fy_capex['prior_usd_bn']:.0f}B "
                       f"{'上修' if fy_capex['usd_bn'] > fy_capex['prior_usd_bn'] else '下修'}到约 "
                       f"US${fy_capex['usd_bn']:.0f}B")
    clauses.append(fcf_clause)
    headline = "；".join(clauses) + "。"

    richer = grew and aws_increment_margin > stock_margin
    cards = [
        '<article><span>' + ("亮点" if aws_accelerating and richer else "观察")
        + f'</span><b>AWS {"加速" if aws_accelerating else "减速"}'
        + (("且增量利润率更高" if richer else "，增量利润率低于存量") if grew else "，收入环比减少") + "</b>"
        + f'<p>环比{"增量" if grew else "减少"} {money_bn(abs(aws_increment), 2)}，'
        + (f"是此前纪录的 {aws_increment / largest_prior_increment:.1f} 倍" if aws_record else
           f"此前纪录是 {long_labels[largest_prior_at]} 的 US${largest_prior_increment / 1000:.2f}B")
        + (f"；增量利润率 {aws_increment_margin:.0f}% "
           f"{'高于' if richer else '低于'}存量 {stock_margin:.1f}%。</p></article>" if grew else "。</p></article>")
    ]
    if snapshot is not None:
        step = group_om_adjusted - group_om_previous
        cards.append(
            '<article><span>口径</span><b>'
            + (other_story["brief_title"] if other_story is not None else "税前利润的构成") + "</b>"
            + f'<p>税前利润 US${snapshot["pre_tax_income_usd_m"][-1] / 1000:.1f}B 里 '
            f'US${snapshot["other_income_expense_net_usd_m"][-1] / 1000:.1f}B 是投资重估；'
            + ("剔除后集团 OM" if one_off_items else "集团 OM")
            + f" {group_om_adjusted:.2f}%，较上季 {group_om_previous:.2f}% "
            + ("实为持平略降" if -0.1 < step < 0 else "实为持平略升" if 0 <= step < 0.1 else
               f"{'下降' if step < 0 else '上升'} {abs(step):.2f}pp")
            + "。</p></article>"
        )
    if concentration is not None:
        single = concentration["largest_single_addition"]
        cards.append(
            f'<article><span>存疑</span><b>{concentration["brief_title"]}</b>'
            f'<p>US${backlog_levels[-1]:.0f}B、单季净增 US${backlog_add:.0f}B，'
            f"其中单笔 {single['customer']} 扩容就 &gt;US${single['more_than_usd_bn']:.0f}B；"
            f"前三大客户占比连续{cn_count(concentration['top_three_share_undisclosed_quarters'])}季未披露。"
            "</p></article>"
        )
    else:
        cards.append(
            f'<article><span>观察</span><b>AWS backlog US${backlog_levels[-1]:.0f}B</b>'
            f'<p>单季净增 US${backlog_add:.0f}B。</p></article>'
        )
    brief = (f'<h4>本季{cn_count(len(cards))}条主线</h4><div class="takeaway-grid">'
             + "".join(cards) + "</div>")

    # ── notes ────────────────────────────────────────────────────────────────
    parts = ["上季兑现", "本季重点"] + (["下季跟踪"] if next_charts else []) + ["长期常规"]
    notes = [
        f"本页按「{' → '.join(parts)}」{cn_count(len(parts))}段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
        # The notes list is escaped by the renderer; markup belongs in chart
        # notes, which are not.
        "亚马逊每季业绩 8-K 的 EX-99.1 同时给出下一季的净销售额区间与经营利润区间，"
        f"本页据此建了 {len(guided)} 个被指引季（{guided[0]} – {guided[-1]}）的完整记录。"
        "微软的新闻稿明写指引只在电话会给出，Alphabet 不给季度数字指引，两页因此都没有这一节。",
        "第一节的两条腿是恒等式而非估计：公司同时指引收入与利润，两者隐含一个它从不印出来的经营利润率，实际值与指引中值的差恰好等于两条腿之和。"
        "收入与利润率同时偏离时的交叉项按该式全部计入利润率腿；调换拆解顺序会把它移到收入腿，两种拆法的合计相同。",
    ]
    if prior_kpi is not None or next_kpi is not None:
        notes.append(
            "本页的阈值来自本地季报分析的关键观察指标（第一节结算上季那一份的，第三节跟踪本季那一份的），"
            "不是公司指引，也不构成评级或投资建议。那一节对多数指标写了两档：越过即须警觉的风险线、"
            "兑现多头论证的确认线；第一、三两节都逐档拆成独立的线，「距阈值余量」统一为正值代表有利一侧。"
        )
    if one_off_items:
        note = (f"{cn_count(len(one_off_items))}笔一次性经营项的金额取自 {period} 10-Q 原文——"
                + "、".join(f"{'关税退款' if key.startswith('tariff') else '能源合约净未实现收益'} "
                           f"US${one_off[key]}M" for key, _ in one_off_items)
                + "——而不是电话会的约数。")
        on_call = one_off.get("energy_derivative_gain_on_call_usd_m")
        year_to_date = one_off.get("energy_derivative_gain_ytd_usd_m")
        management = one_off.get("management_ex_derivative_margin_bp")
        if energy and on_call and year_to_date and management is not None:
            bp_filed = ((aws_income[-1] - energy) / aws_revenue[-1] * 100 - aws_om_prior_year) * 100
            bp_call = ((aws_income[-1] - on_call) / aws_revenue[-1] * 100 - aws_om_prior_year) * 100
            done_words = YTD_WORDS.get(int(quarter_word[1]), ("年初至今", ""))[0]
            note += (
                f"电话会说的「约 US${on_call}M」"
                + (f"更接近 10-Q 里的{done_words}累计数 US${year_to_date}M"
                   if abs(on_call - year_to_date) < abs(on_call - energy) else
                   f"更接近 10-Q 的单季数 US${energy}M")
                + f"；用 US${energy}M 还原出的 AWS 经营利润率同比 {bp_filed:+.0f}bp，"
                f"与管理层自己给的「约 {management:+d}bp」相差 {abs(bp_filed - management):.0f}bp，"
                f"用 US${on_call}M 则相差 {abs(bp_call - management):.0f}bp。"
            )
        notes.append(note)
    notes.append(
        f"TTM 自由现金流为公司披露值，{len(fcf_ttm)} 个季度逐季读自各季新闻稿的 Supplemental 表。"
        + (f"本地分析稿把本季的 {money_bn(latest_fcf)} 记为「{errata['claim']}」；"
           f"按该序列，上一轮资本开支周期里它已连续多季为负、最深至 {money_bn(fcf_ttm[trough_index])}，"
           "本页采用公司披露的完整序列。" if errata is not None and prior_negative_run else "")
    )
    notes += [
        "公司自 2018 年与 2019 年两次调整过自由现金流定义的分母口径（先改为扣除设备激励所得，"
        "再定为「扣除出售与激励所得」）。"
        f"本页序列自 {cash['periods'][0]} 起"
        + ("，晚于 2018 年那次变更；2019 年那次只改了措辞 —— Q1 2019 的 TTM 资本开支净额在变更前后的"
           "两份新闻稿里同为 US$11,316M —— 因此无跨口径拼接。"
           if quarter_key(cash["periods"][0]) >= "2018Q1" else "，跨过了口径变更。"),
        f"AWS 分部只能回到 2015Q1（公司 2015 年才改成三分部），本页从 {long_quarters[0]} 起用，"
        "因为 2016 年起公司才把股权激励费用与「其他经营损益」分摊进分部并追溯调整了历史。",
        f"广告服务自 {lines['advertising_first_reported']} 起才单列，在此之前并入 Other；"
        "公司在 Q4 2021 的新闻稿里把它从 Other 中拆出并追溯调整了此前五个季度，"
        "故 Other 这条线在该处有口径断裂，本页不把更早的 Other 接成一条连续线。",
    ]
    filed = long["annual_filed_usd_m"]
    reconciled_years, widest = [], 0
    for key in ("revenue_usd_m", "operating_income_usd_m", "operating_cash_flow_usd_m",
                "capital_expenditures_usd_m", "depreciation_and_amortization_usd_m", "interest_expense_usd_m"):
        by_quarter = dict(zip(long_quarters, long[key]))
        for year, total in zip(filed["years"], filed[key]):
            cells = [by_quarter.get(f"{year}Q{n}") for n in (1, 2, 3, 4)]
            if total is None or None in cells:
                continue
            reconciled_years.append(year)
            widest = max(widest, abs(sum(cells) - total))
    notes.append(
        "季度值来自各期 10-Q 与 10-K 的 XBRL 事实以及各季业绩 8-K 的 EX-99.1。亚马逊的 10-Q 现金流量表同时列示三个月、年初至今与滚动十二个月三栏，"
        "所以除第四季外的季度现金流是申报值本身；无 10-Q 的第四季度按「全年 − 前三季」倒推，2019 与 2020 两年的第四季另有直接申报的三个月事实则采用申报值。"
        + (f"{min(reconciled_years)}–{max(reconciled_years)} 每年的四季之和已与申报的全年值对账，"
           f"缺口全部在 ±{widest:.0f} US$M 的四舍五入范围内。" if reconciled_years else "")
    )
    notes += [
        "本页只发布公司披露值、可复算的简单派生值，以及明确标注的市场预期；D 标记代表 Derived / 自算。",
        "市场预期一律标注为「市场预期」并给出取数时点，不写卖方机构名，也不发布评级、目标价或估值。"
        + (f"经营性每股收益区间是按 {TAX_RANGE_PCT[0]}%–{TAX_RANGE_PCT[1]}% 税率假设的换算，"
           "不是公司定义的 non-GAAP 指标。" if pre_tax_chart is not None else ""),
    ]
    if shift is not None:
        notes.append(
            f"{shift['event']} 从 {shift['out_of']} 移到 {quarter_word} 抬高了本季的零售增速，"
            f"但公司只给了 {shift['bridge_for']} 的还原口径（近 {shift['bridge_bps']}bp），没有给 {quarter_word} 的。"
            f"本页因此不发布任何「剔除 {shift['event']} 后的 {quarter_word} 增速」数字，只标注这个不对称披露。"
        )
    untracked = [
        "分国家收入（10-K 只按年披露美国、德国、英国、日本与其他地区，没有季度数，本页未接入）",
        "广告分部的独立利润率（公司不披露）",
    ]
    if concentration is not None:
        untracked.append("AWS backlog 的客户结构与前三大占比"
                         f"（连续{cn_count(concentration['top_three_share_undisclosed_quarters'])}季未披露）")
    untracked += story.get("not_yet_tracked", [])
    notes.append("本页已知未接入：" + "、".join(untracked) + "。")

    # ── section descriptions ─────────────────────────────────────────────────
    record = (
        "亚马逊每季在业绩 8-K 里同时给出净销售额与经营利润两个区间，"
        f"本节用 {guided[0]}–{guided[-1]} 共 {len(guided)} 季的完整记录回答「这家公司对自己的指引兑现到什么程度」。"
    )
    if first_analysis:
        settled_description = (f"本站对亚马逊的第一份季报分析是 {period}，没有上季留下的跟踪指标可结算；"
                               "本节结算的是公司上季给出、本季到期的指引：" + record)
    else:
        settled_description = (
            f"先结清上季（{prior_kpi['set_in']}）那一份本地分析留下的"
            + (f" {settled_counts['questions']} 条待验证问题与" if "questions" in settled_counts else "")
            + f" {settled_counts['lines']} 条量化阈值，再看公司自己给出、本季到期的指引：" + record
        )
        # The previous analysis's operating-income line, when it sat on the
        # company's own guided midpoint for this quarter, is the link between (b)
        # and (c): the record says how often that midpoint was beaten.
        at = guided.index(period) if period in guided else None
        if at is not None:
            midpoint = (guide["operating_income_low_bn"][at] + guide["operating_income_high_bn"][at]) / 2
            anchored = [line for line in prior_due if line["reads"] == "group_oi"
                        and abs(line["threshold"] - midpoint) < 1e-9]
            done = [i for i, value in enumerate(guide["actual_operating_income_bn"]) if value is not None]
            beaten = sum(1 for i in done
                         if guide["actual_operating_income_bn"][i] > guide["operating_income_high_bn"][i])
            if anchored:
                settled_description += (
                    f"上季的经营利润{TIER_WORDS[anchored[0]['tier']]} "
                    f"{threshold_text('usd_bn', anchored[0]['threshold'])} 恰好是公司对本季指引区间的中值，"
                    f"而这份记录里经营利润 {beaten} / {len(done)} 季超出了区间上限。"
                )
    focus = ["AWS 的产能节奏",
             "三个分部剔除一次性后的真实利润率" if one_off_items else "三个分部的利润率"]
    if pre_tax_chart is not None:
        focus.append("税前利润的构成")
    focus.append(("转负的" if turned_negative else "为负的" if latest_fcf < 0 else "") + "自由现金流")
    focus.append(f"广告这条被 {shift['event']} 掩盖的加速线"
                 if shift is not None and "advertising_services" in accelerating else "广告的增速")
    focus.append("盖不住资本开支的经营现金流" if capex[-1] > operating_cash_flow[-1] else "经营现金流与资本开支")
    focus.append("长期负债与利息费用")
    unplotted = story.get("not_drawn") or []
    highlights_description = (
        "按本季报告的结论排：" + "、".join(focus[:-1]) + "，以及" + focus[-1] + "。"
        + ("报告另有几条结论本页没有单独成图：" + "；".join(
            f"{item['what']}（{fill_story(item['why'], story_values)}）" for item in unplotted) + "。"
           if unplotted else "")
    )
    next_rows = next_kpi["rows"]
    drawn_rows = sorted({line["row"] for line in next_due})
    next_description = (
        f"本季（{next_kpi['set_in']}）本地分析的{next_kpi['section']}一共{cn_count(len(next_rows))}行："
        f"能量化的{cn_count(len(drawn_rows))}行拆成 {len(next_due)} 根线（"
        + "、".join(f"{TIER_WORDS[tier]} {count} 根" for tier, count in (
            (tier, sum(1 for line in next_due if line["tier"] == tier)) for tier in ("risk", "bull")) if count)
        + "），每个读数一张图"
        + (("；第" + "、".join(cn_ordinal(row["row"]) for row in not_drawn) + "行不画，原因写在总览图注")
           if not_drawn else "")
        + "。"
        + (f"文末 {len(followups)} 条 Follow-up 是下季第 0 节要逐条回答的问题，连同读法列在核对抽屉。"
           if followups else "")
    )

    sections = [
        {
            "id": "settled",
            "title": "一、上季跟踪指标兑现了吗",
            "description": settled_description,
            "exhibits": exhibits[:settled_count],
        },
        {
            "id": "quarter_highlights",
            "title": "二、本季重点",
            "description": highlights_description,
            "exhibits": exhibits[settled_count:settled_count + highlight_count],
        },
        {
            "id": "next_quarter",
            "title": "三、下季要跟踪什么",
            "description": next_description,
            "exhibits": exhibits[settled_count + highlight_count:
                                 settled_count + highlight_count + next_count],
        },
    ]
    sections.append({
        "id": "routine",
        "title": "四、长期常规跟踪",
        "description": (
            f"AMZN 专属的常规序列：{revenue_years}年收入增速、资本强度、折旧的进度，"
            "以及 AWS 在收入与利润里的两条占比。"
        ),
        "exhibits": exhibits[-len(routine):],
    })

    return {
        "schema_version": "quarterly-dashboard/amzn-v1",
        "page": {"slug": "amzn", "language": "zh-CN"},
        "company": {
            "ticker": "AMZN",
            "name": "Amazon.com",
            "group": "internet",
            "accounting_standard": "US GAAP",
        },
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · AMZN",
        "title": f"Amazon.com (AMZN)：{period} 季报仪表盘",
        "subtitle": (
            f"截至 {latest['period_end']} · 发布 {latest['release_date']} · US GAAP · "
            f"{AUDIT_WORDS[latest['audit_status']]} · 自然年财年 · 金额单位为 US$M，另有注明除外"
        ),
        "headline": headline,
        "brief": brief,
        "source": source,
        "source_url": ir["url"],
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": guidance_payload,
        "sections": sections,
        "tables": tables,
        "notes": notes,
        "footer": (
            "AMZN quarterly results · 数据来自 Amazon 公开披露与透明自算 · 仅供研究，不构成投资建议"
        ),
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "amzn.js"), payload, "amzn")
    shell_dir = ROOT / "amzn"
    shell_dir.mkdir(exist_ok=True)
    # Rendered here, not at import: the shell stamps the payload's content hash
    # into its <script src>, so it has to be built after write_dash.
    (shell_dir / "index.html").write_text(
        render_shell("AMZN", "amzn"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(
        f"AMZN page: {charts} charts in {len(payload['sections'])} sections "
        f"+ {len(payload['tables'])} audit tables"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
