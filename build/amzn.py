#!/usr/bin/env python3
"""Build the Amazon quarterly-results page.

Same four-part, chart-led shape as the other pages (上季兑现 → 本季重点 →
下季跟踪 → 长期常规).  Section one is built out the way TSMC's and NVIDIA's are,
and for a stronger reason than either: **Amazon is the only company on this site
that puts a range for two different metrics into every quarterly filing** — net
sales and operating income, both in the `Financial Guidance` block of the
earnings 8-K's EX-99.1, in the same sentence structure, without a break, for 37
consecutive quarters.  Microsoft's release says in as many words that guidance
is given on the call; Alphabet gives no quarterly numbers at all; Meta guides
revenue only.

The record's shape is a fourth distinct answer:

    net sales        21 of 36 above the top, 15 inside, **never below**
    operating income 27 of 36 above the top,  9 inside, **never below**

and the decomposition says which half of the guidance is the conservative one.
Guiding both a level and a profit implies an operating margin Amazon never
prints, and the distance from what it reported splits exactly two ways — a
revenue leg and a margin leg.  The revenue leg is tiny in every quarter; the
margin leg carries essentially the whole beat.  So the demand forecast is close
to honest and the *cost* forecast is the part held back, which is the opposite
of how a "beats its own guidance" record usually reads.

That matters here beyond trivia.  The thresholds settled in section one were set
a quarter earlier against management's own guided midpoint, and every one of
them held — because a framework anchored on the guidance of a company that has
never once missed the bottom of either range is anchored too low by
construction.

Published numbers are company-reported or transparent arithmetic.  Market
expectations are labelled as such, with no broker attribution.  Ratings, target
prices and valuation stay off the page.
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


STAGING_PATH = ROOT / "series" / "amzn.json"
DATA_DIR = ROOT / "data"

WINDOW = 8          # quarters drawn on the short charts
LONG_STEP = 4       # one x label per year on the ten-year axis
DEVIATION_WINDOW = 20

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


# ── section one: the guided record ──────────────────────────────────────────
def guidance_delivery_charts(staging: dict) -> tuple[list[dict], dict]:
    """The full 37-quarter guided record for both guided metrics, and its two legs.

    Amazon guides a net-sales range and an operating-income range in every
    quarterly earnings release, so "did the quarter clear the company's own bar"
    has a nine-year answer rather than an eight-quarter one.  Both answers point
    the same way — never below the bottom — which is why the interesting chart
    is not the band but the decomposition.

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

    sales_band = delivery_band(
        "EX_SALES_RANGE", "净销售额", labels, sales_lo, sales_hi, sales_actual,
        fmt="usd0", ylab="US$B", unit="US$B", venue="业绩新闻稿",
        src_extra=SOURCE_8K,
        extra_note=(
            "<b>这是全页最该先读的一张。</b>亚马逊是本站唯一把<b>两个</b>指引区间写进申报文件的公司，"
            "而且没有断过 —— 连 2020 年疫情最乱的一季也照给，只是把利润下限放到了 US$(1.5)B。"
            "九年 36 个已完结季，收入一次都没有跌破过区间下限；"
            "上穿上限 21 次、落在区间内 15 次。"
            "纵轴是绝对金额，早期的季度因此被压在底部，"
            "无量纲的读法见 Exhibit {EX_SALES_DEV}。"
        ),
    )
    sales_deviation = midpoint_deviation(
        "EX_SALES_DEV", "净销售额", quarters, sales_lo, sales_hi, sales_actual,
        mode="pct", window=DEVIATION_WINDOW, label=compact_period,
        src_extra=SOURCE_8K + "偏离为实际值相对指引中值的自算百分比。",
        axis_note=(
            f"本图只画最近 {DEVIATION_WINDOW} 个已完结季，完整的 {len(finished)} 季记录在上一张里；"
        ),
        extra_note=(
            "柱子普遍不高：收入指引其实<b>相当准</b>，绝大多数季度的偏离在 ±2% 以内。"
            "这一点是下一张利润图的前提 —— 既然收入猜得准，利润的超额就不可能来自卖得更多。"
        ),
    )

    income_band = delivery_band(
        "EX_OI_RANGE", "经营利润", labels, income_lo, income_hi, income_actual,
        fmt="usd1", ylab="US$B", unit="US$B", venue="业绩新闻稿",
        src_extra=SOURCE_8K,
        extra_note=(
            "同一批新闻稿里的第二条指引，形状比收入那条更偏：36 个已完结季里 27 季超出上限、"
            "9 季落在区间内，<b>同样一次都没有跌破下限</b>。"
            "早期几季的区间下限是负数或零（如 Q3'17 的 US$(0.4)B、Q4'21 与 Q3'22 的 $0），"
            "那是当时公司自己就把亏损放进了可能性里，不是绘图误差。"
        ),
    )
    income_deviation = midpoint_deviation(
        "EX_OI_DEV", "经营利润", quarters, income_lo, income_hi, income_actual,
        mode="pct", window=DEVIATION_WINDOW, label=compact_period,
        src_extra=SOURCE_8K + "偏离为实际值相对指引中值的自算百分比。",
        axis_note=f"本图只画最近 {DEVIATION_WINDOW} 个已完结季；",
        extra_note=(
            "把两张偏离图并排看是本节的重点：收入的柱子贴着零轴，利润的柱子成倍高于它。"
            "同一份新闻稿、同一天给出的两个数，一个接近预测、一个系统性偏低 —— "
            "偏差不在需求，在成本。拆开看是 Exhibit {EX_OI_LEGS}。"
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
    margin_dominant = sum(
        1 for index in range(len(total))
        if abs(margin_leg[index]) > abs(revenue_leg[index])
    )
    legs_chart = {
        "ref": "EX_OI_LEGS",
        "kind": "grouped_bars",
        "title": (
            f"把「超出自身指引」拆成两条腿：{margin_dominant} / {len(total)} 季由利润率腿主导，"
            "收入腿几乎看不见"
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
            f"<b>读数：</b>本季 US${total[-1]:.2f}B 的超额里，收入腿只有 US${revenue_leg[-1]:.2f}B，"
            f"利润率腿 US${margin_leg[-1]:.2f}B —— 占 {margin_leg[-1] / total[-1] * 100:.0f}%。"
            f"整段记录里收入腿的绝对值从未超过 US${max(abs(v) for v in revenue_leg):.2f}B，"
            "深蓝那组在图上几乎是一条贴着零轴的线。"
            f"没能达到自身指引中值的 {len(misses)} 季（"
            + "、".join(leg_labels[index] for index in misses)
            + "）"
            + ("也全部是利润率腿更负" if len(margin_driven) == len(misses)
               else f"里有 {len(margin_driven)} 季是利润率腿更负")
            + " —— "
            "<b>这家公司迄今为止的经营意外，无论正负，都来自成本而不是需求。</b>"
            "<b>交互项归属：</b>收入与利润率同时偏离时的交叉项按上式全部计入利润率腿；"
            "调换拆解顺序会把它移到收入腿，两种拆法的合计完全相同。"
        ),
        "src_extra": SOURCE_8K + "两条腿与隐含利润率均为自算，指引原值与实际原值见核对表。",
    }

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
            "缺口在 2022 年前后最窄（那两年公司自己也不知道成本会走到哪里），"
            "此后随着利润率整体抬升重新拉开。"
        ),
        "src_extra": SOURCE_8K + "隐含利润率与实际利润率均为自算。",
    }

    verdicts = {
        "sales_above": sum(1 for index in finished if sales_actual[index] > sales_hi[index]),
        "sales_inside": sum(1 for index in finished
                            if sales_lo[index] <= sales_actual[index] <= sales_hi[index]),
        "sales_below": sum(1 for index in finished if sales_actual[index] < sales_lo[index]),
        "income_above": sum(1 for index in finished if income_actual[index] > income_hi[index]),
        "income_inside": sum(1 for index in finished
                             if income_lo[index] <= income_actual[index] <= income_hi[index]),
        "income_below": sum(1 for index in finished if income_actual[index] < income_lo[index]),
        "finished": len(finished),
        "revenue_leg_max": max(abs(value) for value in revenue_leg),
        "margin_share_latest": margin_leg[-1] / total[-1] * 100,
        "implied_margin_latest": implied_margin[-1],
        "quarters": quarters,
    }
    return (
        [sales_band, sales_deviation, income_band, income_deviation, legs_chart, implied_chart],
        verdicts,
    )


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    quarterly = staging["quarterly_usd_m"]
    segments = staging["segments_usd_m"]
    lines = staging["product_lines_usd_m"]
    cash = staging["cash_flow_disclosed"]
    long = staging["long_history"]
    snapshot = staging["current_snapshot"]
    one_off = staging["one_off_items"]
    backlog = staging["aws_backlog"]
    guidance = staging["guidance"]
    consensus = staging["market_expectation"]
    prior_kpi = staging["prior_kpi_settlement"]
    next_kpi = staging["next_kpi"]

    shown = lambda values: values[-WINDOW:]  # noqa: E731
    labels = shown(periods)

    revenue = quarterly["revenue_total"]
    operating_income = quarterly["operating_income"]
    capex = quarterly["purchases_of_property_and_equipment"]
    operating_cash_flow = quarterly["operating_cash_flow"]
    dda = quarterly["depreciation_and_amortization"]

    revenue_shown = shown(revenue)
    revenue_yoy = shown(yoy(revenue))
    operating_margin = [
        income / total * 100 for income, total in zip(operating_income, revenue)
    ]

    # ── segments (30 quarters, the window the disclosed tables actually cover) ─
    seg_periods = segments["periods"]
    seg_labels = [compact_period(period) for period in seg_periods]
    aws_revenue = segments["aws_revenue"]
    aws_income = segments["aws_operating_income"]
    aws_margin = [income / total * 100 for income, total in zip(aws_income, aws_revenue)]
    aws_yoy = yoy(aws_revenue)
    aws_sequential = sequential(aws_revenue)
    na_margin = [
        income / total * 100
        for income, total in zip(segments["na_operating_income"], segments["na_revenue"])
    ]
    intl_margin = [
        income / total * 100
        for income, total in zip(segments["intl_operating_income"], segments["intl_revenue"])
    ]

    # ── disclosed trailing cash flow (30 quarters, all company figures) ───────
    cash_labels = [compact_period(period) for period in cash["periods"]]
    fcf_ttm = cash["free_cash_flow_ttm"]
    fcf_bn = [value / 1000 for value in fcf_ttm]
    trough_index = fcf_bn.index(min(fcf_bn))
    latest_fcf = fcf_bn[-1]
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
    line_labels = [compact_period(period) for period in line_periods]
    ads_yoy = yoy(lines["advertising_services"])
    ads_from = leading_gap(lines["advertising_services"])
    online_yoy = yoy(lines["online_stores"])
    third_party_yoy = yoy(lines["third_party_seller_services"])
    subscription_yoy = yoy(lines["subscription_services"])

    # ── ten-year routine series ──────────────────────────────────────────────
    long_labels = [compact_long(quarter) for quarter in long["quarters"]]
    long_revenue = long["revenue_usd_m"]
    long_capex = long["capital_expenditures_usd_m"]
    long_dda = long["depreciation_and_amortization_usd_m"]
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
    aws_om_reported = aws_margin[-1]
    aws_om_adjusted = (
        (aws_income[-1] - one_off["energy_derivative_gain_usd_m"]) / aws_revenue[-1] * 100
    )
    aws_om_prior_year = aws_margin[-5]
    na_om_reported = na_margin[-1]
    na_om_adjusted = (
        (segments["na_operating_income"][-1] - one_off["tariff_refund_usd_m"])
        / segments["na_revenue"][-1] * 100
    )
    na_om_prior_year = na_margin[-5]
    group_om_reported = operating_margin[-1]
    group_om_adjusted = (
        (operating_income[-1] - one_off["total_usd_m"]) / revenue[-1] * 100
    )
    group_om_previous = operating_margin[-2]
    aws_increment = aws_sequential[-1]
    aws_increment_margin = (
        (aws_income[-1] - one_off["energy_derivative_gain_usd_m"] - aws_income[-2])
        / aws_increment * 100
    )
    largest_prior_increment = max(
        value for value in aws_sequential[:-1] if value is not None
    )
    pre_tax = snapshot["pre_tax_income_usd_m"][-1]
    other_income = snapshot["other_income_expense_net_usd_m"][-1]
    operating_pre_tax = pre_tax - other_income - one_off["total_usd_m"]
    backlog_add = backlog["level_usd_bn"][-1] - backlog["level_usd_bn"][-2]
    backlog_qoq = pct_change(backlog["level_usd_bn"][-1], backlog["level_usd_bn"][-2])
    net_capex = snapshot["net_capex_usd_m"][-1]

    guidance_charts, verdicts = guidance_delivery_charts(staging)

    source = (
        'Source: <a href="https://ir.aboutamazon.com/" rel="noopener">Amazon Investor Relations</a>'
        '（Q2 2026 业绩 8-K EX-99.1 与 10-Q；历史季度经 SEC EDGAR 回源）。'
    )

    # ── the tracked metrics that have a history worth plotting ───────────────
    # Each entry is (labels, values, fmt, y label, series name, extra note). The
    # window is per metric: a threshold chart with forty-two 90-degree labels is
    # a hairbrush, so the long series are cut to the span that still answers
    # "how did it get here".
    net_capex_series = quarterly["net_capex"]
    long_group_margin = [
        income / total * 100
        for income, total in zip(long["operating_income_usd_m"], long_revenue)
    ]
    backlog_labels = [compact_period(period) for period in backlog["periods"]]
    backlog_net_add = [None] + [
        current - previous for previous, current
        in zip(backlog["level_usd_bn"], backlog["level_usd_bn"][1:])
    ]
    tracked = {
        "AWS 收入同比": (seg_labels, rounded(aws_yoy), "pct1", "同比增速", "AWS 收入同比 D", ""),
        "AWS 分部经营利润率": (seg_labels, rounded(aws_margin), "pct1", "利润率",
                              "AWS 经营利润率 D",
                              "线上是报告口径；剔除本季 US$551M 能源衍生品收益后为 "
                              f"38.1%，同样在阈值之上。"),
        "集团经营利润率": (
            [compact_long(quarter) for quarter in long["quarters"]][-24:],
            rounded(long_group_margin[-24:]),
            "pct1", "利润率", "集团经营利润率 D", "",
        ),
        "TTM 自由现金流": (cash_labels, rounded(fcf_bn), "usd0", "US$B",
                          "TTM 自由现金流（公司披露）", ""),
        "AWS 环比收入增量": (
            seg_labels,
            rounded([None if value is None else value / 1000 for value in aws_sequential]),
            "usd1", "US$B", "AWS 环比收入增量 D", "",
        ),
        "AWS backlog 单季净增": (
            backlog_labels, rounded(backlog_net_add), "usd0", "US$B", "backlog 单季净增 D",
            "公司只在最近四个季度给出过这个余额，所以净增只有三个可比点 —— "
            "这条线的斜率还不足以判断趋势，本季的 US$132B 里单笔 Anthropic 扩容就 >US$100B。",
        ),
        "北美分部经营利润率": (seg_labels, rounded(na_margin), "pct1", "利润率",
                              "北美经营利润率 D",
                              "线上是报告口径；剔除 US$640M 关税退款后本季为 7.30%，"
                              "低于去年同期的 7.51%。"),
        "单季现金 CapEx（净额，超过即偏离隐含节奏）": (
            [compact_period(period) for period in periods],
            rounded([value / 1000 for value in net_capex_series]),
            "usd0", "US$B", "单季 CapEx（净额）",
            "净额 = 购买物业及设备 − 出售与激励所得，与公司自由现金流定义里的分母同口径；"
            f"本季总额为 US${capex[-1] / 1000:.1f}B。",
        ),
    }

    def tracking_charts(entries, value_key, threshold_label, headline) -> list[dict]:
        charts = []
        for entry in entries:
            metric = entry["metric"]
            if metric not in tracked:
                continue
            xlabels, values, fmt, ylab, actual_name, extra = tracked[metric]
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
                    + (f"<br>{extra}" if extra else "")
                ),
                src_extra=(
                    "实际值来自公司季度 release / 10-Q 口径；阈值为本地研究设定，不是公司指引。"
                ),
            )
            if len(xlabels) > 20:
                chart["xstep"] = 2
            charts.append(chart)
        return charts

    settled_entries = prior_kpi["quantified"]
    bull_cleared = [
        entry for entry in settled_entries
        if headroom(entry["direction"], entry["bull_threshold"], entry["bull_actual"]) >= 0
    ]
    bull_missed = [entry for entry in settled_entries if entry not in bull_cleared]

    risk_headroom = headroom_exhibit(
        "上季 6 条风险线：一条都没有被触发",
        settled_entries,
        "actual",
        (
            "统一口径：正值 = 仍在安全侧。上季对每条指标都设了「风险线」与「多头确认线」两条，"
            "本图画的是风险线。六条全部安全，而且多数余量很大 —— "
            "这本身就是需要解释的结果，见下一张。"
        ),
        src_extra=(
            "阈值为上季本地研究设定，不是公司指引；实际值来自 Q2 2026 业绩 8-K 与 10-Q。"
            "另有 2 条定性阈值触发（Trainium 客户集中度连续两季未披露、未出现第三个 multi-GW 客户），"
            "1 条因公司未披露而无法判定（前三大客户占比），1 条已退役（AWS 同比增速阈值）。"
        ),
    )
    bull_headroom = {
        "ref": "EX_BULL",
        "kind": "diverging_bars",
        "title": (
            f"换成多头确认线再看一次：{len(bull_cleared)} / {len(settled_entries)} 条兑现，"
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
        "note": (
            "同一批指标、换成更高的那条线：仍有 "
            f"{len(bull_cleared)} 条兑现。唯一没到的是 TTM 自由现金流 —— "
            "它守住了 −US$10B 的风险线，却离 +US$5B 的确认线还差很远，"
            "<b>落在两条线中间那段没有设定任何动作的空档里</b>。"
            "上季那套阈值把「增长」与「现金流」当成同向变量，"
            "而本季实际发生的是增长兑现、现金流恶化同时成立，"
            "这个组合在上季的框架里没有位置。"
        ),
        "src_extra": (
            "多头确认线同为上季本地研究设定；backlog 与集团经营利润两条的确认线用的是绝对值口径"
            "（US$400B 与 US$24B），与风险线的百分比口径不同，故两张图不可逐条比大小。"
        ),
    }

    settled_charts = (
        guidance_charts
        + [risk_headroom, bull_headroom]
        + tracking_charts(
            settled_entries,
            "actual",
            "上季风险线",
            lambda entry: (
                f"{entry['metric']}："
                f"{'守住' if headroom(entry['direction'], entry['threshold'], entry['actual']) >= 0 else '已击穿'}"
                f"上季风险线 {unit_text(entry['unit'], entry['threshold'])}"
            ),
        )
    )

    highlights = [
        {
            "kind": "bar_line",
            "title": (
                f"AWS 收入 US${aws_revenue[-1] / 1000:.1f}B，环比增量 US${aws_increment / 1000:.2f}B —— "
                f"是此前最大单季增量的 {aws_increment / largest_prior_increment:.1f} 倍"
            ),
            "xlabels": seg_labels[-WINDOW:],
            "bar": {
                "name": "AWS 收入",
                "color": "NAVY",
                "values": [value / 1000 for value in aws_revenue[-WINDOW:]],
                "yfmt": "usd0",
            },
            "line": {
                "name": "环比绝对增量 (RHS) D",
                "color": "RED",
                "values": [None if value is None else value / 1000
                           for value in aws_sequential[-WINDOW:]],
                "yfmt": "usd1",
            },
            "fmt": "usd0",
            "yfmt": "usd0",
            "label_fmt": "usd0",
            "ylab": "US$B",
            "ylab2": "环比增量 US$B",
            "note": (
                "<b>本页把 AWS 的锚定指标从同比增速换成了环比绝对增量。</b>"
                "在产能受限的状态下增速由机柜上电的节奏决定，与同比基数关系不大 —— "
                "上季正是用「高基数所以难加速」推断出了方向相反的结论。"
                f"环比增量直接映射产能上线速度：本季 US${aws_increment / 1000:.2f}B，"
                f"同比增速 {aws_yoy[-1]:.1f}%（公司披露的固定汇率口径为 37%）。"
            ),
            "src_extra": source_note(
                "AWS 分部收入来自各期 8-K EX-99.1 的 Supplemental 表与 10-Q 分部附注；环比增量为自算"),
        },
        {
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
            "note": (
                "<b>两条线上各有一笔一次性收益，剔除后方向就变了。</b>"
                f"AWS 的 {aws_om_reported:.1f}% 含 10-Q 披露的 US${one_off['energy_derivative_gain_usd_m']}M "
                f"能源合约公允价值收益，剔除后 {aws_om_adjusted:.1f}%、同比 "
                f"{(aws_om_adjusted - aws_om_prior_year) * 100:+.0f}bp —— "
                f"与管理层在电话会上给的「约 +{one_off['management_ex_derivative_margin_bp']}bp」对得上。"
                f"北美的 {na_om_reported:.1f}% 含 US${one_off['tariff_refund_usd_m']}M 关税退款，"
                f"剔除后 {na_om_adjusted:.2f}%，<b>低于去年同期的 {na_om_prior_year:.2f}%</b>，"
                "也就是零售侧本季其实是负经营杠杆。"
            ),
            "src_extra": (
                "分部利润率为分部经营利润 ÷ 分部收入的自算值；两笔一次性金额取自 Q2 2026 10-Q 原文"
                "（关税退款 US$640M、能源衍生品净未实现收益 US$551M），不是电话会的约数。"
            ),
        },
        {
            "kind": "bars_labeled",
            "title": (
                f"US${pre_tax / 1000:.1f}B 的税前利润里，US${other_income / 1000:.1f}B 不是经营挣来的"
            ),
            "xlabels": [
                "税前利润（GAAP）",
                "其中：Other income, net",
                "其中：两笔一次性经营项",
                "经营性税前利润 D",
            ],
            "values": [
                pre_tax / 1000,
                other_income / 1000,
                one_off["total_usd_m"] / 1000,
                operating_pre_tax / 1000,
            ],
            "legend": "US$B",
            "fmt": "usd1",
            "yfmt": "usd1",
            "label_fmt": "usd1",
            "ylab": "US$B",
            "note": (
                "10-Q 明写：Other income 里 US$50.5B 是私募股权投资的向上重估，"
                "「主要来自我们持有的 Anthropic 无投票权优先股」，属 Level 3 估值。"
                f"把它和两笔一次性经营项一起剔除，剩下 US${operating_pre_tax / 1000:.1f}B 才是经营口径。"
                "<b>本页刻意在税前口径上做这道减法</b>：换算成每股要先假设一个经营性税率，"
                "而这一季的实际税率被对未实现收益计提的递延税主导"
                f"（单季递延所得税加回 US${snapshot['deferred_income_taxes_addback_usd_m'][-1] / 1000:.1f}B），"
                "无法从报表直接分离。按 21%–24% 的税率区间换算，经营性摊薄每股收益落在 "
                f"US$1.83–US$1.92，对照财报前市场预期的 US${consensus['diluted_eps_usd']:.2f}；"
                f"而账面摊薄每股收益是 US${snapshot['diluted_eps_usd'][-1]:.2f}。"
            ),
            "src_extra": (
                "税前利润与 Other income 来自 Q2 2026 合并损益表；US$50.5B 的构成与「主要来自 Anthropic」"
                "的表述来自 10-Q；每股区间为按税率假设的换算，非公司口径，也不是公司定义的 non-GAAP 指标。"
            ),
        },
        {
            "kind": "diverging_bars",
            "title": (
                f"TTM 自由现金流转为 −US${abs(latest_fcf):.1f}B —— "
                f"但 {cash_labels[trough_index]} 的 −US${abs(fcf_bn[trough_index]):.1f}B 更深"
            ),
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
            "note": (
                "<b>这条线是本页唯一一条纠正了本地分析稿的序列。</b>本地稿把 −US$7.6B 记为"
                "「2014 年以来首次转负」；按公司自己在每季新闻稿里公布的 TTM 自由现金流，"
                f"上一轮资本开支周期里它已经连续 {prior_negative_run} 个季度为负，"
                f"最深处是 {cash_labels[trough_index]} 的 −US${abs(fcf_bn[trough_index]):.1f}B，"
                "只不过公司每份新闻稿只列六个季度，看单季那张表看不到上一轮。"
                f"上一轮从转负到转正用了 {prior_negative_run} 个季度；这一轮的资本开支还在加速，"
                f"公司指引全年约 {guidance['fy2026_capex']}，上半年已用净额 "
                f"US${guidance['h1_2026_net_capex_usd_m'] / 1000:.1f}B。"
            ),
            "src_extra": (
                "30 个季度全部是公司披露值：各季 8-K EX-99.1 的 Supplemental 表直接列出 TTM 自由现金流，"
                "定义为经营现金流减「购买物业及设备，扣除出售与激励所得」。相邻两份新闻稿重叠的季度已逐个核对一致。"
            ),
        },
        {
            "kind": "lines",
            "title": (
                f"广告同比加速到 {ads_yoy[-1]:.1f}%，是四条零售线里唯一在加速的"
            ),
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
            "note": (
                f"广告本季 US${lines['advertising_services'][-1] / 1000:.1f}B、同比 {ads_yoy[-1]:.1f}%，"
                f"较上季加速 {ads_yoy[-1] - ads_yoy[-2]:.1f}pp。"
                "在线商店与第三方卖家两条同期也在加速，但那两条的加速里含 Prime Day 的日历移位 —— "
                "今年 Prime Day 落在 Q2，去年整场在 Q3。"
                "<b>公司只给了 Q3 的桥（剔除后同比高出近 400bp），没有给 Q2 的桥</b>，"
                "所以本页不发布任何「剔除 Prime Day 后的 Q2 增速」数字，只标注这个不对称披露本身。"
                "广告线的起点是 Q3 2020：在此之前它并入 Other，公司未单列。"
            ),
            "src_extra": source_note(
                "七条分项收入来自各期 8-K EX-99.1 的 Supplemental 表；同比为自算"),
        },
        {
            "kind": "grouped_bars",
            "title": (
                f"单季经营现金流 US${operating_cash_flow[-1] / 1000:.1f}B，"
                f"被 US${capex[-1] / 1000:.1f}B 的资本开支盖过"
            ),
            "xlabels": labels,
            "groups": [
                {"name": "经营现金流", "color": "NAVY",
                 "values": [value / 1000 for value in shown(operating_cash_flow)]},
                {"name": "购买物业及设备", "color": "GOLD",
                 "values": [value / 1000 for value in shown(capex)]},
            ],
            "fmt": "usd0",
            "label_fmt": "usd0",
            "ylab": "US$B",
            "note": (
                "亚马逊的 10-Q 现金流量表同时列示三个月、年初至今与滚动十二个月三栏，"
                "所以这里的单季现金流是<b>申报值本身</b>，不是两个年初至今值相减的结果。"
                f"本季资本开支总额 US${capex[-1] / 1000:.1f}B，扣除出售与激励所得后净额 "
                f"US${net_capex / 1000:.1f}B；两者的差就是自由现金流那张图的分母口径。"
                "同季计入应付账款但尚未支付的资本开支还增加了 "
                f"US${snapshot['increase_in_unpaid_capex_usd_m'][-1] / 1000:.1f}B，"
                "也就是现金口径本身还落后于已经建成的资产。"
            ),
            "src_extra": source_note("经营现金流与资本开支为各期现金流量表的三个月申报值"),
        },
    ]

    next_headroom = headroom_exhibit(
        "下季 6 条风险线：当前值全部在安全侧，CapEx 是唯一方向相反的一条",
        next_kpi["quantified"],
        "current",
        (
            "口径与第一节的风险线图相同。单季现金 CapEx 那条方向相反 —— "
            "高于 US$65B 说明支出节奏已经越过全年指引所隐含的水平，因此安全侧在下方。"
        ),
        src_extra=(
            "阈值为本地研究设定，不是公司指引；当前值为 Q2 2026 实际。"
            "另有 4 条须待披露才能判定（backlog 客户结构、Anthropic 授信额度是否被动用、"
            "OpenAI 剩余出资的现金流归属、2027 资本开支指引），"
            "1 条因缺少可比历史不入图（剔除 Prime Day 后的非 AWS 收入同比）。"
        ),
    )
    next_charts = [next_headroom] + tracking_charts(
        next_kpi["quantified"],
        "current",
        "下季风险线",
        lambda entry: (
            f"{entry['metric']}：下季风险线 {unit_text(entry['unit'], entry['threshold'])}，"
            f"当前 {unit_text(entry['unit'], entry['current'])}"
        ),
    )

    routine = [
        {
            "kind": "lines",
            "title": (
                f"总收入同比 {long_revenue_yoy[-1]:.1f}%，十年区间 "
                f"{min(v for v in long_revenue_yoy if v is not None):.0f}–"
                f"{max(v for v in long_revenue_yoy if v is not None):.0f}%"
            ),
            "xlabels": long_labels[yoy_from:],
            "xstep": LONG_STEP,
            "series": [
                {"name": "总收入同比 D", "values": rounded(long_revenue_yoy[yoy_from:]), "color": "NAVY"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "zero_base": True,
            "end_label": True,
            "ylab": "同比增速",
            "note": (
                "<b>八季的窗口里本季是一条上行线，十年的窗口里它是第三次回升</b>："
                "2020 年疫情那一次冲到 40% 上方后两年内塌到个位数，"
                "2023–2024 年那一次停在十几个百分点。"
                "这一次与前两次的区别要靠下一张资本强度图判断，不是靠这一张。"
                "本季的同比里还含 Prime Day 从 Q3 移到 Q2 的日历影响，公司未给 Q2 的还原桥。"
            ),
            "src_extra": source_note(
                "收入逐季来自各期 10-Q / 10-K（第四季为全年 − 前三季，2019 与 2020 另有直接申报的三个月事实）"),
        },
        {
            "kind": "lines",
            "title": (
                f"资本强度十年从 {long_intensity[capex_from]:.1f}% 升到 {long_intensity[-1]:.1f}%，"
                "已越过上一轮周期的高点"
            ),
            "xlabels": long_labels[capex_from:],
            "xstep": LONG_STEP,
            "series": [
                {"name": "CapEx / 收入 D", "values": rounded(long_intensity[capex_from:]), "color": "NAVY"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "zero_base": True,
            "end_label": True,
            "ylab": "占收入比",
            "note": (
                "<b>这条线是本页的主轴</b>：2020–2021 年那一轮把资本强度推到 13% 附近，"
                "随后两年回落到 8% 上下，自由现金流也随之从深负转正 —— "
                f"当前的 {long_intensity[-1]:.1f}% 是上一轮高点的两倍，且还没有回落的迹象。"
                f"公司指引全年资本开支约 {guidance['fy2026_capex']}（自约 {guidance['fy2026_capex_prior']} 上修，"
                "管理层把原因明确归为内存成本上涨），"
                f"上半年净额已用 US${guidance['h1_2026_net_capex_usd_m'] / 1000:.1f}B，"
                f"隐含下半年还要花约 US${guidance['implied_h2_2026_capex_usd_bn']:.1f}B。"
                "起点是 Q2'16：2016Q1 的季度资本开支公司只申报了年初至今口径，本页不外推。"
            ),
            "src_extra": source_note(
                "CapEx / 收入为自算；资本开支为各期现金流量表的三个月申报值，第四季为全年 − 前三季"),
        },
        {
            "kind": "lines",
            "title": (
                f"折旧摊销占收入比升到 {long_dda_intensity[-1]:.1f}%，"
                f"但资本开支已是折旧的 {capex[-1] / dda[-1]:.1f} 倍"
            ),
            "xlabels": long_labels[leading_gap(long_dda_intensity):],
            "xstep": LONG_STEP,
            "series": [
                {"name": "折旧摊销 / 收入 D",
                 "values": rounded(long_dda_intensity[leading_gap(long_dda_intensity):]),
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
                f"本季资本开支是当季折旧摊销的 {capex[-1] / dda[-1]:.1f} 倍，"
                "上一轮周期里这个倍数回到 1 附近时，折旧占收入比才见顶。"
                "换句话说，这条线未来几年只会继续上行，"
                "而它上行的速度与 AWS 收入增量的赛跑，才是 2027 年利润率方向的真正变量。"
            ),
            "src_extra": source_note(
                "折旧摊销为现金流量表的「物业设备与自制内容、经营租赁资产及其他的折旧摊销」三个月申报值"),
        },
        {
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
                "两条线十年都没有收敛过，而且在 2021–2022 年零售亏损的那两年，"
                "利润占比一度冲到 100% 以上（集团经营利润几乎全部由 AWS 提供）。"
                "本季收入占比 "
                f"{long_aws_share[-1]:.1f}%、利润占比 {long_aws_income_share[-1]:.1f}%，"
                "意味着市场对这家公司的定价越来越取决于一个占它五分之一收入的分部 —— "
                "而那个分部的合约集中度公司连续两季拒绝披露。"
                "序列起点是 2016Q1：公司 2015 年才改成三分部，且 2016 年起才把股权激励费用分摊进分部并追溯调整，"
                "更早的分部利润与今天不同口径。"
            ),
            "src_extra": source_note(
                "AWS 分部收入与经营利润来自各期 8-K EX-99.1 与 10-Q 分部附注；两条占比为自算"),
        },
    ]

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
                    staging["quarterly_guidance_history"]["net_sales_low_bn"],
                    staging["quarterly_guidance_history"]["net_sales_high_bn"],
                    staging["quarterly_guidance_history"]["actual_net_sales_bn"],
                    staging["quarterly_guidance_history"]["operating_income_low_bn"],
                    staging["quarterly_guidance_history"]["operating_income_high_bn"],
                    staging["quarterly_guidance_history"]["actual_operating_income_bn"],
                    staging["quarterly_guidance_history"]["fx_bps"],
                    staging["quarterly_guidance_history"]["fx_direction"],
                ))
            ],
        },
        {
            "n": 0,
            "title": "上季风险线 / 多头确认线与本季实际（原单位）",
            "headers": ["指标", "方向", "风险线", "多头确认线", "Q2 2026 实际", "距风险线 D", "判定"],
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
                    else "只守住风险线",
                ]
                for entry in settled_entries
            ],
        },
        threshold_table(
            0,
            "下季风险线与当前值（原单位）",
            next_kpi["quantified"],
            "current",
            "当前值",
        ),
        {
            "n": 0,
            "title": "三个分部逐季收入与经营利润（US$M，最近十二季）",
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
                for index in range(len(seg_periods) - 12, len(seg_periods))
            ],
        },
        {
            "n": 0,
            "title": "十二季基础数据（US$M；前四季只用于计算同比）",
            "headers": ["季度", "总收入", "经营利润", "OM D", "净利润",
                        "经营现金流", "购买物业及设备", "折旧摊销", "股权激励", "融资租赁本金"],
            "rows": [
                [
                    period,
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
                for index, period in enumerate(periods)
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

    return {
        "schema_version": "quarterly-dashboard/amzn-v1",
        "page": {"slug": "amzn", "language": "zh-CN"},
        "company": {
            "ticker": "AMZN",
            "name": "Amazon.com",
            "group": "internet",
            "accounting_standard": "US GAAP",
        },
        "latest": {
            "disclosed_period_label": "Q2 2026",
            "full_financial_period_label": "Q2 2026",
            "period_end": "2026-06-30",
            "release_date": "2026-07-30",
            "analysis_date": "2026-08-01",
            "audit_status": "unaudited",
            "status": "history_ready",
        },
        "tracker": "Watchlist Quarterly Tracker · AMZN",
        "title": "Amazon.com (AMZN)：Q2 2026 季报仪表盘",
        "subtitle": (
            "截至 2026-06-30 · 发布 2026-07-30 · US GAAP · 未审计 · "
            "自然年财年 · 金额单位为 US$M，另有注明除外"
        ),
        "headline": (
            f"AWS 环比增量 US${aws_increment / 1000:.2f}B 创纪录、增量利润率 "
            f"{aws_increment_margin:.0f}% 高于存量，是本季唯一真实的结构性变化；"
            f"但 US${snapshot['diluted_eps_usd'][-1]:.2f} 的摊薄每股收益背后是 "
            f"US${other_income / 1000:.1f}B 的税前 Other income，"
            "其中 US$50.5B 是 Anthropic 持仓的一次公允价值上调；"
            f"TTM 自由现金流转为 −US${abs(latest_fcf):.1f}B，"
            f"同一场电话会把全年资本开支从约 {guidance['fy2026_capex_prior']} 上修到约 "
            f"{guidance['fy2026_capex']}。"
        ),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>亮点</span><b>AWS 加速且增量利润率更高</b>'
            f'<p>环比增量 US${aws_increment / 1000:.2f}B，是此前纪录的 '
            f'{aws_increment / largest_prior_increment:.1f} 倍；增量利润率 {aws_increment_margin:.0f}% '
            f'高于存量 {aws_om_adjusted:.1f}%。</p></article>'
            '<article><span>口径</span><b>利润的质量低于账面</b>'
            f'<p>税前利润 US${pre_tax / 1000:.1f}B 里 US${other_income / 1000:.1f}B 是投资重估；'
            f'剔除后集团 OM {group_om_adjusted:.2f}%，较上季 {group_om_previous:.2f}% 实为持平略降。</p></article>'
            '<article><span>存疑</span><b>backlog 增量高度集中</b>'
            f'<p>US${backlog["level_usd_bn"][-1]:.0f}B、单季净增 US${backlog_add:.0f}B，'
            '其中单笔 Anthropic 扩容就 &gt;US$100B；前三大客户占比连续两季未披露。</p></article>'
            '</div>'
        ),
        "source": source,
        "source_url": "https://ir.aboutamazon.com/",
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": {
            "title": f"公司对 {guidance['next_quarter_label']} 的指引（业绩新闻稿原文口径）",
            "headers": ["项目", "指引", "对照"],
            "rows": [
                ["净销售额",
                 f"US${guidance['net_sales_usd_bn'][0]:.1f}B – US${guidance['net_sales_usd_bn'][1]:.1f}B",
                 f"同比 +{guidance['net_sales_growth_pct'][0]}% ~ +{guidance['net_sales_growth_pct'][1]}%；"
                 f"中值较本季实际 {pct_change(sum(guidance['net_sales_usd_bn']) / 2 * 1000, revenue[-1]):+.1f}%"],
                ["经营利润",
                 f"US${guidance['operating_income_usd_bn'][0]:.1f}B – US${guidance['operating_income_usd_bn'][1]:.1f}B",
                 # Guidance-table cells are escaped by the renderer, so no markup
                 # here: a <b> would print as literal angle brackets.
                 f"上年同期 US${guidance['prior_year_operating_income_usd_bn']:.1f}B；"
                 f"区间上限 US${guidance['operating_income_usd_bn'][1]:.1f}B 也低于本季实际 "
                 f"US${operating_income[-1] / 1000:.1f}B"],
                ["汇率假设", f"不利影响约 {abs(guidance['fx_bps'])}bp", "公司在指引段落中给出"],
                ["Prime Day 还原", f"剔除后同比高约 {guidance['prime_day_bridge_bps']}bp",
                 "公司只给了 Q3 的还原口径，未给 Q2 的"],
                ["全年现金资本开支", guidance["fy2026_capex"],
                 f"自 {guidance['fy2026_capex_prior']} 上修；"
                 f"上半年净额 US${guidance['h1_2026_net_capex_usd_m'] / 1000:.1f}B，"
                 f"隐含下半年约 US${guidance['implied_h2_2026_capex_usd_bn']:.1f}B"],
            ],
            "note": (
                "净销售额与经营利润两行来自 Q2 2026 业绩 8-K EX-99.1 的「Financial Guidance」段；"
                "全年资本开支只在电话会给出，不在申报文件的指引段里，故单独标注。"
                "指引另假设不含能源衍生品重估，也不含新增并购、重组或法律和解。"
                f"本页第一节给出这套指引过去 {verdicts['finished']} 季的兑现记录。"
            ),
        },
        "sections": [
            {
                "id": "settled",
                "title": "一、上季跟踪指标兑现了吗",
                "description": (
                    "先结算上季设下的阈值，再看本季数据。亚马逊每季在申报文件里同时给出净销售额与经营利润"
                    "两个区间，所以这一节先用九年 37 季的完整记录回答「这家公司对自己的指引兑现到什么程度」，"
                    "再看本地设定的阈值 —— 顺序反过来就看不出后者为什么会错。"
                ),
                "exhibits": exhibits[:settled_count],
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": (
                    "AWS 的产能节奏、三个分部剔除一次性后的真实利润率、"
                    "税前利润的构成、转负的自由现金流，以及广告这条被 Prime Day 掩盖的加速线。"
                ),
                "exhibits": exhibits[settled_count:settled_count + highlight_count],
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": "同一套口径向前看：当前值离下季风险线还有多远。",
                "exhibits": exhibits[settled_count + highlight_count:
                                     settled_count + highlight_count + next_count],
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": (
                    "AMZN 专属的常规序列：十年收入增速、资本强度、折旧的进度，"
                    "以及 AWS 在收入与利润里的两条占比。"
                ),
                "exhibits": exhibits[-len(routine):],
            },
        ],
        "tables": tables,
        "notes": [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            # The notes list is escaped by the renderer; markup belongs in chart
            # notes, which are not.
            "亚马逊是本站唯一一家把「两个」季度指引区间写进申报文件的公司：每季业绩 8-K 的 EX-99.1 同时给出下一季的净销售额区间与经营利润区间，"
            "本页据此建了 37 个被指引季（Q3 2017 – Q3 2026）的完整记录。微软的新闻稿明写指引只在电话会给出，Alphabet 不给季度数字指引，两页因此都没有这一节。",
            "第一节的两条腿是恒等式而非估计：公司同时指引收入与利润，两者隐含一个它从不印出来的经营利润率，实际值与指引中值的差恰好等于两条腿之和。"
            "收入与利润率同时偏离时的交叉项按该式全部计入利润率腿；调换拆解顺序会把它移到收入腿，两种拆法的合计相同。",
            "本页的阈值是本地研究设定，不是公司指引，也不构成评级或投资建议；「距阈值余量」统一为正值代表安全侧。"
            "上季对每条指标同时设了「风险线」与「多头确认线」，两张余量图分别画这两条，不可逐条比大小。",
            "两笔一次性经营项的金额取自 Q2 2026 10-Q 原文——关税退款 US$640M、能源合约净未实现收益 US$551M——而不是电话会的约数。"
            "电话会说的「约 US$600M」更接近 10-Q 里的上半年累计数 US$599M；用 US$551M 还原出的 AWS 经营利润率同比 +514bp，"
            "与管理层自己给的「约 +520bp」相差 6bp，用 US$600M 则相差 17bp。",
            "TTM 自由现金流为公司披露值，30 个季度逐季读自各季新闻稿的 Supplemental 表。本地分析稿把本季的 −US$7.6B 记为「2014 年以来首次转负」；"
            "按该序列，上一轮资本开支周期里它已连续多季为负、最深至 −US$23.5B，本页采用公司披露的完整序列。",
            "公司自 2018 年与 2019 年两次调整过自由现金流定义的分母口径（先改为扣除设备激励所得，再定为「扣除出售与激励所得」）。本页序列自 Q1 2019 起，落在最后一次变更之后，因此无跨口径拼接。",
            "AWS 分部只能回到 2015Q1（公司 2015 年才改成三分部），本页从 2016Q1 起用，因为 2016 年起公司才把股权激励费用与「其他经营损益」分摊进分部并追溯调整了历史。",
            "广告服务自 Q3 2020 起才单列，在此之前并入 Other；公司在 Q4 2021 的新闻稿里把它从 Other 中拆出并追溯调整了此前五个季度，故 Other 这条线在该处有口径断裂，本页不把更早的 Other 接成一条连续线。",
            "季度值来自各期 10-Q 与 10-K 的 XBRL 事实以及各季业绩 8-K 的 EX-99.1。亚马逊的 10-Q 现金流量表同时列示三个月、年初至今与滚动十二个月三栏，"
            "所以除第四季外的季度现金流是申报值本身；无 10-Q 的第四季度按「全年 − 前三季」倒推，2019 与 2020 两年的第四季另有直接申报的三个月事实则采用申报值。"
            "2016–2025 每年的四季之和已与申报的全年值对账，缺口全部在 ±1 US$M 的四舍五入范围内。",
            "本页只发布公司披露值、可复算的简单派生值，以及明确标注的市场预期；D 标记代表 Derived / 自算。",
            "市场预期一律标注为「市场预期」并给出取数时点，不写卖方机构名，也不发布评级、目标价或估值。经营性每股收益区间是按 21%–24% 税率假设的换算，不是公司定义的 non-GAAP 指标。",
            "Prime Day 从 Q3 移到 Q2 抬高了本季的零售增速，但公司只给了 Q3 的还原口径（近 400bp），没有给 Q2 的。本页因此不发布任何「剔除 Prime Day 后的 Q2 增速」数字，只标注这个不对称披露。",
            "本页已知未接入：分国家收入（公司不披露）、广告分部的独立利润率（公司不披露）、AWS backlog 的客户结构与前三大占比（连续两季未披露）、"
            "Anthropic 那笔总额 US$20.0B 授信安排的动用情况（只在 10-Q 披露，尚无季度序列）、Amazon Leo 与 Zoox 的收入口径（公司未量化）。",
        ],
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
