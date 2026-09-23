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
    headroom,
    headroom_exhibit,
    latest_block,
    midpoint_deviation,
    number_exhibits,
    stamped_block,
    threshold_exhibit,
    threshold_table,
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
# 「多数余量很大」: more than half the settled lines at least this far (in the
# headroom chart's own percent) on the safe side.
WIDE_HEADROOM_PCT = 20.0
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


def line_words(unit: str, value: float) -> str:
    """A threshold in words: ``−US$10B`` / ``+US$5B`` for dollars, else the unit's format."""
    if unit == "usd_bn":
        return f"{'−' if value < 0 else '+'}US${abs(value):g}B"
    return unit_text(unit, value)


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
            "<b>这是全页最该先读的一张。</b>亚马逊每季在申报文件里同时写进<b>两个</b>指引区间"
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
            "把两张偏离图并排看是本节的重点："
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
    guidance = stamped_block(staging, "guidance", period)
    shift = stamped_block(staging, "calendar_shift", period)
    consensus = stamped_block(staging, "market_expectation", period)
    prior_kpi = stamped_block(staging, "prior_kpi_settlement", period)
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

    # ── the tracked metrics that have a history worth plotting ───────────────
    # Each entry is (labels, values, fmt, y label, series name, extra note for an
    # entry). The window is per metric: a threshold chart with forty-two
    # 90-degree labels is a hairbrush, so the long series are cut to the span
    # that still answers "how did it get here".
    # AWS revenue and AWS segment operating income are in `long_history` for all
    # its quarters -- the `segments` block is the *three* segment tables, and it
    # is the North America / International half of that block that starts later,
    # not AWS. So every AWS line here runs the full record and only the North
    # America line keeps the shorter window.
    long_group_margin = [
        income / total * 100
        for income, total in zip(long["operating_income_usd_m"], long_revenue)
    ]
    aws_peak = max((value, index) for index, value in enumerate(long_aws_yoy) if value is not None)[1]

    def aws_yoy_extra(entry: dict) -> str:
        text = ""
        if long_quarters[aws_peak] < quarter_key(seg_periods[0]):
            text = (f"<b>这条线的{cn_count(len(seg_periods))}季版本看不到 AWS 增速最高的那一段</b>：")
        return text + (
            f"窗口内最高是 {long_aws_yoy[aws_peak]:.0f}%，出现在 {long_labels[aws_peak]}，"
            f"那一季的收入只有本季的{cn_fraction(long_aws_revenue[aws_peak] / long_aws_revenue[-1])}。"
        )

    def aws_margin_extra(entry: dict) -> str:
        text = ""
        if energy:
            above = aws_om_adjusted >= entry["threshold"]
            text = (
                f"线上是报告口径；剔除本季 US${energy}M 能源衍生品收益后为 {aws_om_adjusted:.1f}%，"
                + (("同样在阈值之上" if aws_om_reported >= entry["threshold"] else "在阈值之上")
                   if above else "已在阈值之下")
                + "。"
            )
        return text + (f"{cn_count(len(long_aws_margin))}季区间 "
                       f"{min(long_aws_margin):.1f}–{max(long_aws_margin):.1f}%。")

    def backlog_extra(entry: dict) -> str:
        comparable = [(value, index) for index, value in enumerate(backlog_net_add) if value is not None]
        prior_max, prior_at = max(comparable[:-1])
        text = (f"余额自 {backlog_labels[0]} 起逐季披露，净增共 {len(comparable)} 个可比点；"
                f"本季 US${backlog_add:.0f}B "
                + ("是其中最大的一次" if backlog_add > prior_max else
                   f"低于 {backlog_labels[prior_at]} 的 US${prior_max:.0f}B"))
        if concentration is not None:
            single = concentration["largest_single_addition"]
            text += f"，里面单笔 {single['customer']} 扩容就 >US${single['more_than_usd_bn']:.0f}B"
        return text + "。"

    def north_america_extra(entry: dict) -> str:
        text = (f"北美与国际两个分部的季度表本页只回补到 {quarter_key(seg_periods[0])}"
                f"（更早的季度申报里有，还没有接入），AWS 那几条则回到 {long_quarters[0]}。")
        if tariff:
            text += (f"线上是报告口径；剔除 US${tariff}M 关税退款后本季为 {na_om_adjusted:.2f}%，"
                     f"{'低于' if na_om_adjusted < na_om_prior_year else '高于'}去年同期的 "
                     f"{na_om_prior_year:.2f}%。")
        return text

    tracked = {
        "AWS 收入同比": (long_labels, rounded(long_aws_yoy), "pct1", "同比增速",
                        "AWS 收入同比 D", aws_yoy_extra),
        "AWS 分部经营利润率": (long_labels, rounded(long_aws_margin), "pct1", "利润率",
                              "AWS 经营利润率 D", aws_margin_extra),
        "集团经营利润率": (long_labels, rounded(long_group_margin),
                          "pct1", "利润率", "集团经营利润率 D", None),
        "TTM 自由现金流": (cash_labels, rounded(fcf_bn), "usd0", "US$B",
                          "TTM 自由现金流（公司披露）", None),
        "AWS 环比收入增量": (
            long_labels,
            rounded([None if value is None else value / 1000 for value in long_aws_sequential]),
            "usd1", "US$B", "AWS 环比收入增量 D", None,
        ),
        "AWS backlog 单季净增": (backlog_labels, rounded(backlog_net_add), "usd0", "US$B",
                                "backlog 单季净增 D", backlog_extra),
        "北美分部经营利润率": (seg_labels, rounded(na_margin), "pct1", "利润率",
                              "北美经营利润率 D", north_america_extra),
        "单季现金 CapEx（净额，超过即偏离隐含节奏）": (
            [compact_period(p) for p in periods],
            rounded([value / 1000 for value in quarterly["net_capex"]]),
            "usd0", "US$B", "单季 CapEx（净额）",
            lambda entry: ("净额 = 购买物业及设备 − 出售与激励所得，与公司自由现金流定义里的分母同口径；"
                           f"本季总额为 US${capex[-1] / 1000:.1f}B。"),
        ),
    }

    def tracking_charts(entries, value_key, threshold_label, headline) -> list[dict]:
        charts = []
        for entry in entries:
            metric = entry["metric"]
            if metric not in tracked:
                continue
            xlabels, values, fmt, ylab, actual_name, extra = tracked[metric]
            extra_text = extra(entry) if extra else ""
            side = "上方" if entry["direction"] == "up" else "下方"
            chart = threshold_exhibit(
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
                    + (f"<br>{extra_text}" if extra_text else "")
                ),
                src_extra=(
                    "实际值来自公司季度 release / 10-Q 口径；阈值为本地研究设定，不是公司指引。"
                ),
            )
            if len(xlabels) > 20:
                chart["xstep"] = 2
            charts.append(chart)
        return charts

    # ── section one: last quarter's two threshold sets, then the guided record ──
    settled_charts = []
    settled_entries = prior_kpi["quantified"] if prior_kpi else []
    if prior_kpi is not None:
        risk_margins = [headroom(e["direction"], e["threshold"], e["actual"]) for e in settled_entries]
        breached = [e for e, m in zip(settled_entries, risk_margins) if m < 0]
        wide = sum(1 for m in risk_margins if m > WIDE_HEADROOM_PCT)
        n_settled = len(settled_entries)
        bull_cleared = [
            entry for entry in settled_entries
            if headroom(entry["direction"], entry["bull_threshold"], entry["bull_actual"]) >= 0
        ]
        bull_missed = [entry for entry in settled_entries if entry not in bull_cleared]
        extras = []
        for key, words in (("qualitative_triggered", "条定性阈值触发"),
                           ("excluded_from_chart", "条因公司未披露而无法判定"),
                           ("retired", "条已退役")):
            items = prior_kpi.get(key) or []
            if items:
                extras.append(f"{len(items)} {words}（{'、'.join(item['short'] for item in items)}）")
        risk_headroom = headroom_exhibit(
            f"上季 {n_settled} 条风险线："
            + ("一条都没有被触发" if not breached else f"{len(breached)} 条被触发"),
            settled_entries,
            "actual",
            (
                "统一口径：正值 = 仍在安全侧。上季对每条指标都设了「风险线」与「多头确认线」两条，"
                "本图画的是风险线。"
                + (f"{cn_count(n_settled)}条全部安全"
                   + ("，而且多数余量很大" if wide * 2 > n_settled else "")
                   + " —— 这本身就是需要解释的结果，见下一张。"
                   if not breached else
                   f"{cn_count(n_settled)}条里{cn_count(len(breached))}条被触发，下一张换成多头确认线再看。")
            ),
            src_extra=(
                f"阈值为上季本地研究设定，不是公司指引；实际值来自 {period} 业绩 8-K 与 10-Q。"
                + (f"另有 {'，'.join(extras)}。" if extras else "")
            ),
        )
        bull_note = (f"同一批指标、换成更高的那条线：仍有 {len(bull_cleared)} 条兑现。" if bull_cleared
                     else "同一批指标、换成更高的那条线：没有一条兑现。")
        if len(bull_missed) == 1:
            missed = bull_missed[0]
            held = headroom(missed["direction"], missed["threshold"], missed["actual"]) >= 0
            bull_note += (
                f"唯一没到的是 {missed['metric']} —— "
                + (f"它守住了 {line_words(missed['unit'], missed['threshold'])} 的风险线，却离 "
                   f"{line_words(missed.get('bull_unit', missed['unit']), missed['bull_threshold'])} "
                   "的确认线还差很远，<b>落在两条线中间那段没有设定任何动作的空档里</b>。"
                   if held else
                   f"它连 {line_words(missed['unit'], missed['threshold'])} 的风险线也没有守住。")
            )
        bull_note += prior_kpi.get("bull_lesson", "")
        mixed = [e for e in settled_entries if e.get("bull_unit", e["unit"]) != e["unit"]]
        bull_headroom = {
            "kind": "diverging_bars",
            "title": (
                f"换成多头确认线再看一次：{len(bull_cleared)} / {n_settled} 条兑现，"
                + (f"只有「{bull_missed[0]['metric']}」没到" if len(bull_missed) == 1
                   else f"{len(bull_missed)} 条没到")
            ),
            "xlabels": [entry["metric"] for entry in settled_entries],
            "values": [
                round(headroom(entry["direction"], entry["bull_threshold"], entry["bull_actual"]), 1)
                for entry in settled_entries
            ],
            "legend": "距多头确认线的余量",
            "positive_label": "多头论证被兑现",
            "negative_label": "未达确认线",
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "ylab": "距确认线 %",
            "zero_line": True,
            "note": bull_note,
            "src_extra": (
                "多头确认线同为上季本地研究设定"
                + "".join(
                    f"；{e['metric']}那条的确认线用的是绝对值口径"
                    f"（{line_words(e['bull_unit'], e['bull_threshold']).lstrip('+')}），"
                    f"风险线用的是{'百分比' if e['unit'] == 'pct' else '另一种'}口径"
                    f"（{unit_text(e['unit'], e['threshold'])}）"
                    for e in mixed)
                + "，故两张图不可逐条比大小。"
            ),
        }
        settled_charts += [risk_headroom, bull_headroom] + tracking_charts(
            settled_entries,
            "actual",
            "上季风险线",
            lambda entry: (
                f"{entry['metric']}："
                f"{'守住' if headroom(entry['direction'], entry['threshold'], entry['actual']) >= 0 else '已击穿'}"
                f"上季风险线 {unit_text(entry['unit'], entry['threshold'])}"
            ),
        )
    # (c) after (a)(b): the company's own guided record closes the section.
    settled_charts += guidance_charts

    # ── section two: this quarter ────────────────────────────────────────────
    early = [value for quarter, value in zip(long_quarters, long_aws_sequential)
             if value is not None and quarter < "2019"]
    negative_increments = sum(1 for v in long_aws_sequential if v is not None and v < 0)
    in_short_window = largest_prior_at >= len(long_quarters) - WINDOW
    aws_note = (
        story.get("aws_anchor_note", "")
        + f"环比增量直接映射产能上线速度：本季 US${aws_increment / 1000:.2f}B，"
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
                f"AWS 收入 US${aws_revenue[-1] / 1000:.1f}B，环比增量 US${aws_increment / 1000:.2f}B —— "
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
    one_off_words = [f"{words} US${one_off[key]}M" for key, words in one_off_items]
    highlights.append({
        "kind": "lines",
        "title": (
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
    })

    # ── section three: next quarter's thresholds ─────────────────────────────
    next_charts = []
    if next_kpi is not None:
        next_entries = next_kpi["quantified"]
        unsafe = [e for e in next_entries if headroom(e["direction"], e["threshold"], e["current"]) < 0]
        downs = [e for e in next_entries if e["direction"] == "down"]
        next_note = ("口径与第一节的风险线图相同。" if prior_kpi is not None
                     else "统一口径：正值 = 仍在安全侧。")
        for entry in downs:
            next_note += (
                f"{entry.get('label', entry['metric'])} 那条方向相反 —— "
                + (f"高于 {line_words(entry['unit'], entry['threshold']).lstrip('+')} "
                   f"{entry['down_reason']}，因此安全侧在下方。" if entry.get("down_reason")
                   else "安全侧在下方。")
            )
        gated = next_kpi.get("disclosure_gated") or []
        excluded = next_kpi.get("excluded_from_chart") or []
        next_extras = []
        if gated:
            next_extras.append(f"{len(gated)} 条须待披露才能判定（{'、'.join(item['short'] for item in gated)}）")
        if excluded:
            next_extras.append(f"{len(excluded)} 条因缺少可比历史不入图"
                               f"（{'、'.join(item['short'] for item in excluded)}）")
        next_headroom = headroom_exhibit(
            f"下季 {len(next_entries)} 条风险线："
            + ("当前值全部在安全侧" if not unsafe else f"{len(unsafe)} 条当前值已越线")
            + (f"，{downs[0].get('short', downs[0]['metric'])} 是唯一方向相反的一条" if len(downs) == 1 else ""),
            next_entries,
            "current",
            next_note,
            src_extra=(
                f"阈值为本地研究设定，不是公司指引；当前值为 {period} 实际。"
                + (f"另有 {'，'.join(next_extras)}。" if next_extras else "")
            ),
        )
        next_charts = [next_headroom] + tracking_charts(
            next_entries,
            "current",
            "下季风险线",
            lambda entry: (
                f"{entry['metric']}：下季风险线 {unit_text(entry['unit'], entry['threshold'])}，"
                f"当前 {unit_text(entry['unit'], entry['current'])}"
            ),
        )

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

    tables = [
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
    if prior_kpi is not None:
        tables.append({
            "n": 0,
            "title": "上季风险线 / 多头确认线与本季实际（原单位）",
            "headers": ["指标", "方向", "风险线", "多头确认线", f"{period} 实际", "距风险线 D", "判定"],
            "rows": [
                [
                    entry["metric"],
                    "高于阈值为安全" if entry["direction"] == "up" else "低于阈值为安全",
                    unit_text(entry["unit"], entry["threshold"]),
                    unit_text(entry.get("bull_unit", entry["unit"]), entry["bull_threshold"]),
                    unit_text(entry["unit"], entry["actual"]),
                    f"{headroom(entry['direction'], entry['threshold'], entry['actual']):+.1f}%",
                    "两条线都过" if headroom(
                        entry["direction"], entry["bull_threshold"], entry["bull_actual"]) >= 0
                    else ("只守住风险线" if headroom(
                        entry["direction"], entry["threshold"], entry["actual"]) >= 0 else "两条线都没过"),
                ]
                for entry in settled_entries
            ],
        })
    if next_kpi is not None:
        tables.append(threshold_table(
            0,
            "下季风险线与当前值（原单位）",
            next_kpi["quantified"],
            "current",
            "当前值",
        ))
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
    aws_clause = (
        f"AWS 环比增量 US${aws_increment / 1000:.2f}B"
        + (" 创纪录" if aws_record else "")
        + f"、增量利润率 {aws_increment_margin:.0f}% {'高于' if aws_increment_margin > stock_margin else '低于'}存量"
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

    cards = [
        '<article><span>' + ("亮点" if aws_accelerating and aws_increment_margin > stock_margin else "观察")
        + f'</span><b>AWS {"加速" if aws_accelerating else "减速"}'
        + ("且增量利润率更高" if aws_increment_margin > stock_margin else "，增量利润率低于存量") + "</b>"
        + f'<p>环比增量 US${aws_increment / 1000:.2f}B，'
        + (f"是此前纪录的 {aws_increment / largest_prior_increment:.1f} 倍" if aws_record else
           f"此前纪录是 {long_labels[largest_prior_at]} 的 US${largest_prior_increment / 1000:.2f}B")
        + f"；增量利润率 {aws_increment_margin:.0f}% "
        + f"{'高于' if aws_increment_margin > stock_margin else '低于'}存量 {stock_margin:.1f}%。</p></article>"
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
            "本页的阈值是本地研究设定，不是公司指引，也不构成评级或投资建议；「距阈值余量」统一为正值代表安全侧。"
            + ("上季对每条指标同时设了「风险线」与「多头确认线」，两张余量图分别画这两条，不可逐条比大小。"
               if prior_kpi is not None else "")
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
                "capital_expenditures_usd_m", "depreciation_and_amortization_usd_m"):
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
    focus = ["AWS 的产能节奏",
             "三个分部剔除一次性后的真实利润率" if one_off_items else "三个分部的利润率"]
    if pre_tax_chart is not None:
        focus.append("税前利润的构成")
    focus.append(("转负的" if turned_negative else "为负的" if latest_fcf < 0 else "") + "自由现金流")
    focus.append(f"广告这条被 {shift['event']} 掩盖的加速线"
                 if shift is not None and "advertising_services" in accelerating else "广告的增速")

    sections = [
        {
            "id": "settled",
            "title": "一、上季跟踪指标兑现了吗",
            "description": (
                ("先结算上季本地分析设下的阈值，再看公司自己的指引兑现记录：" if prior_kpi is not None else "")
                + "亚马逊每季在申报文件里同时给出净销售额与经营利润两个区间，"
                f"本节用 {guided[0]}–{guided[-1]} 共 {len(guided)} 季的完整记录"
                "回答「这家公司对自己的指引兑现到什么程度」。"
            ),
            "exhibits": exhibits[:settled_count],
        },
        {
            "id": "quarter_highlights",
            "title": "二、本季重点",
            "description": "、".join(focus[:-1]) + "，以及" + focus[-1] + "。",
            "exhibits": exhibits[settled_count:settled_count + highlight_count],
        },
    ]
    if next_charts:
        sections.append({
            "id": "next_quarter",
            "title": "三、下季要跟踪什么",
            "description": "同一套口径向前看：当前值离下季风险线还有多远。",
            "exhibits": exhibits[settled_count + highlight_count:
                                 settled_count + highlight_count + next_count],
        })
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
