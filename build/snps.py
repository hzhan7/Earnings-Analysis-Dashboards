#!/usr/bin/env python3
"""Build the SNPS quarterly-results page.

Same four-part, chart-led shape as the other company pages (上季兑现 → 本季重点
→ 下季跟踪 → 长期常规).  Synopsys' fiscal year ends 31 October, so every label
here is the calendar quarter the fiscal one mostly covers: the quarter ended
2026-07-31 is the company's FY2026 Q3 and this page's ``Q2 2026``.

What makes this page worth building out is the guidance table.  Every Synopsys
earnings 8-K carries a "Financial Targets" block that guides **every input of
earnings per share** for the next quarter -- revenue, GAAP and non-GAAP
expenses, non-GAAP other income, the non-GAAP tax rate, the fully diluted share
count, and then GAAP and non-GAAP EPS themselves.  No other company on this site
publishes that much of its own arithmetic, and it means the beat can be split
into its parts with no estimate anywhere: guided revenue minus guided expenses
is an operating income the company never prints, and the distance from what it
reported is exactly a revenue leg plus an expense leg.

Twenty-four quarters of it produce a shape that no single quarter shows, and it
is not one shape but two.  Revenue landed *inside* the guided range 13 times in
23 finished quarters -- Synopsys forecasts its own top line about as well as a
company can, which a backlog-driven model should let it do.  Non-GAAP EPS landed
*above* the top of its range 20 times out of 23.  Same press release, same
quarter, same twelve-week horizon: the revenue number is a forecast and the
earnings number is a floor.

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


STAGING_PATH = ROOT / "series" / "snps.json"
DATA_DIR = ROOT / "data"

# One tick per year keeps the ten-year and twenty-four-quarter axes readable.
LONG_STEP = 4


def compact_period(period: str) -> str:
    """``'Q2 2026'`` → ``'Q2'26'``."""
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def rounded(values: list[float | None], digits: int = 6) -> list[float | None]:
    return [None if value is None else round(value, digits) for value in values]


def mid(low: list[float], high: list[float]) -> list[float]:
    return [(a + b) / 2 for a, b in zip(low, high)]


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
    "指引区间来自各季业绩 8-K 的 EX-99.1 新闻稿里「Financial Targets」表的"
    "「Range for Three Months Ending …」一栏，即该季<b>开始前</b>公司自己给出的数；"
    "实际值来自随后一季 8-K 的合并损益表与分部调节表。"
)

# The Software Integrity business was signed away on 2024-05-05 and moved to
# discontinued operations in the quarter ended 2024-04-30, which is guided from
# one basis and reported on another.  Named wherever a level series crosses it.
BASIS_BREAK_LABEL = "口径变更：Software Integrity 转列终止经营"
BASIS_BREAK_NOTE = (
    "<b>红色竖线是口径断点，也是本页最需要解释的一格。</b>"
    "公司在 2024-05-05 签约出售 Software Integrity，并在截至 2024-04-30 的当季把它"
    "整体移入终止经营。于是这一季的指引是在<b>含</b>该业务的口径下给出的，"
    "报出来的实际值却<b>不含</b>它 —— 两者不是同一家公司。"
)


# ── section one: the guided record ──────────────────────────────────────────
def guidance_delivery_charts(staging: dict) -> tuple[list[dict], dict]:
    """Twenty-four quarters of guided-versus-reported, and what the beats are made of.

    Synopsys guides revenue, non-GAAP expenses, non-GAAP other income, the
    non-GAAP tax rate and the fully diluted share count, and then guides the EPS
    those five imply.  The implication is exact rather than approximate: running
    the five midpoints through

        (revenue − expenses + other income) × (1 − tax rate) ÷ shares

    reproduces the company's own printed EPS midpoint to within US$0.02 in 15 of
    the 24 quarters and within US$0.06 in all of them, the residual being the
    rounding of the published range endpoints.  So the guided operating income
    below -- guided revenue minus guided expenses -- is the company's own number
    in everything but name, and the distance from what it reported splits
    exactly two ways with no estimate:

        actual − implied = (Ra − Rg)  −  (Ea − Eg)

    where the actual expense leg is itself reported revenue minus the reported
    "total adjusted segment operating income" every release prints.
    """
    record = staging["quarterly_guidance_history"]
    quarters = record["quarters"]
    labels = [compact_period(quarter) for quarter in quarters]
    break_at = record["basis_break_at"]
    addback = record["basis_break_addback_usd_m"]

    revenue_lo = record["guide_revenue_lo_usd_m"]
    revenue_hi = record["guide_revenue_hi_usd_m"]
    revenue_actual = record["actual_revenue_usd_m"]
    eps_lo = record["guide_non_gaap_eps_lo_usd"]
    eps_hi = record["guide_non_gaap_eps_hi_usd"]
    eps_actual = record["actual_non_gaap_eps_usd"]
    shares_lo = record["guide_shares_lo_m"]
    shares_hi = record["guide_shares_hi_m"]
    shares_actual = record["actual_diluted_shares_m"]
    expense_mid = mid(record["guide_non_gaap_expenses_lo_usd_m"],
                      record["guide_non_gaap_expenses_hi_usd_m"])
    revenue_mid = mid(revenue_lo, revenue_hi)

    finished = [index for index, value in enumerate(revenue_actual) if value is not None]

    # ── revenue ──────────────────────────────────────────────────────────────
    inside = sum(1 for index in finished
                 if revenue_lo[index] <= revenue_actual[index] <= revenue_hi[index])
    revenue_band = delivery_band(
        "EX_REV_RANGE", "收入", labels, revenue_lo, revenue_hi, revenue_actual,
        fmt="f0c", ylab="US$M", unit="US$M", venue="业绩发布",
        break_at=break_at, break_label=BASIS_BREAK_LABEL,
        src_extra=SOURCE_8K,
        extra_note=(
            f"<b>先读这张的中间一栏</b>：{len(finished)} 个已完结季里有 {inside} 季"
            "落在自己给的区间<b>内</b>，而不是穿出去。"
            "这在本站是少见的形状 —— 一家把收入指引当预测用、而且大部分时候预测对了的公司，"
            "背后是以 backlog 与按期确认收入为主的模型。"
            + BASIS_BREAK_NOTE
            + f"当季实际 US${revenue_actual[break_at]:,.0f}M 对指引 "
            f"US${revenue_lo[break_at]:,.0f}–{revenue_hi[break_at]:,.0f}M，"
            "看上去是本记录里最大的一次跌破，但把被移走的那块加回去就落回区间内、而且靠近上沿："
            "该季 10-Q 的终止经营附注载明 Software Integrity 三个月收入 "
            f"US${addback:,.1f}M，"
            f"{revenue_actual[break_at]:,.0f} + {addback:,.0f} = "
            f"<b>US${revenue_actual[break_at] + addback:,.0f}M</b>，"
            "公司自己在当天的新闻稿里也把这一季称作「at the high-end of guidance」。"
            "本页保留这根跌破的柱子并在这里说明原因，而不是把它悄悄改掉。"
        ),
    )
    revenue_dev = midpoint_deviation(
        "EX_REV_DEV", "收入", quarters, revenue_lo, revenue_hi, revenue_actual,
        mode="pct", window=len(finished), label=compact_period, bar_labels=False,
        src_extra=SOURCE_8K + "偏离为实际收入除以指引中值的自算值。",
        extra_note=(
            "换成与量级无关的口径看同一件事：柱子长期贴着零轴，"
            "说明这家公司对自己下一季收入的预测误差常年在 ±1% 以内 —— "
            "收入在这 24 季里从 US$0.95B 长到 US$2.5B，误差却没有跟着放大。"
            "两根明显的负柱各有各的原因，不是同一类事："
            "左边那根是上一张说的终止经营口径变更；"
            "右边那根 Q2'25 是真的没做到，公司 CEO 在当天的新闻稿里写的是"
            "「our IP business underperformed expectations」，"
            "而 Design IP 正是本季重新转正的那条线（见 Exhibit {EX_SEG_REV}）。"
        ),
    )

    # ── the two legs of the operating-income beat ────────────────────────────
    revenue_leg, expense_leg, leg_labels = [], [], []
    for index in finished:
        actual_expense = revenue_actual[index] - record[
            "actual_non_gaap_operating_income_usd_m"][index]
        revenue_leg.append(revenue_actual[index] - revenue_mid[index])
        expense_leg.append(expense_mid[index] - actual_expense)
        leg_labels.append(compact_period(quarters[index]))
    totals = [a + b for a, b in zip(revenue_leg, expense_leg)]
    misses = [index for index, value in enumerate(totals) if value < 0]
    expense_positive = sum(1 for value in expense_leg if value > 0)
    latest_share = revenue_leg[-1] / totals[-1] * 100
    legs_chart = {
        "ref": "EX_OI_LEGS",
        "kind": "grouped_bars",
        "title": (
            f"把「超出自身指引」拆成两条腿：{len(totals)} 季里 {len(totals) - len(misses)} 季为正，"
            f"费用腿 {expense_positive} 季省出钱来"
        ),
        "xlabels": leg_labels,
        "xrot": 90,
        "groups": [
            {"name": "收入腿", "color": "NAVY", "values": rounded(revenue_leg)},
            {"name": "费用腿", "color": "GOLD", "values": rounded(expense_leg)},
        ],
        "bar_labels": False,
        "fmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$M vs 指引隐含营业利润",
        "note": (
            "公司在同一张表里同时给出下一季的收入区间与非 GAAP 费用区间，"
            "于是<b>隐含</b>了一个它从不单独印出来的非 GAAP 营业利润：指引收入 − 指引费用。"
            "实际值与它的差<b>恰好</b>等于两项之和（不是近似）："
            "收入腿 = 实际收入 − 指引收入中值；费用腿 = 指引费用中值 − 实际费用。"
            "实际费用本身也不是估计 —— 它是实际收入减去每份新闻稿都印的"
            "「total adjusted segment operating income」。"
            f"<b>读数：</b>本季超额 US${totals[-1]:,.0f}M 里收入腿占 {latest_share:.0f}%、"
            f"费用腿占 {100 - latest_share:.0f}%，"
            "是一次干净的经营超额，不靠税率也不靠股数。"
            "整段记录里深蓝的收入腿几乎总是主导项，金色的费用腿只在小幅摆动 —— "
            "换句话说，<b>这家公司的意外来自卖了多少，不来自省了多少</b>。"
            "唯一一次两条腿同时深负的是口径断点那一季，原因见 Exhibit {EX_REV_RANGE}。"
        ),
        "src_extra": SOURCE_8K + "两条腿均为自算，指引原值与实际原值见核对表。",
    }

    # ── non-GAAP EPS ─────────────────────────────────────────────────────────
    eps_band = delivery_band(
        "EX_EPS_RANGE", "non-GAAP EPS", labels, eps_lo, eps_hi, eps_actual,
        fmt="usd2", ylab="US$/股", unit="US$", venue="业绩发布",
        break_at=break_at, break_label=BASIS_BREAK_LABEL,
        src_extra=SOURCE_8K,
        extra_note=(
            "<b>把这张和收入那张并排读，是本页存在的理由。</b>"
            "同一份新闻稿、同一个季度、同一个十二周的预测窗口，"
            "收入指引大多数时候被<b>命中</b>，EPS 指引却几乎每一季都被<b>穿透</b>。"
            "一个是预测，另一个是底线，而公司把它们印在同一张表上。"
            "区间宽度长期只有 US$0.05–0.06，本身就说明公司认为自己算得很准。"
        ),
    )
    eps_dev = midpoint_deviation(
        "EX_EPS_DEV", "non-GAAP EPS", quarters, eps_lo, eps_hi, eps_actual,
        mode="pct", window=len(finished), label=compact_period, bar_labels=False,
        src_extra=SOURCE_8K + "偏离为实际 non-GAAP EPS 除以指引中值的自算值。",
        extra_note=(
            "与收入那张（Exhibit {EX_REV_DEV}）的柱高不在一个量级上："
            "收入的偏离常年在 ±1% 以内，EPS 的偏离经常在 +4% 到 +8%。"
            "同样的收入落点能产出这么大的 EPS 超额，说明超额来自收入以下的各行 —— "
            "费用、非经营项与税率，其中费用那一腿见 Exhibit {EX_OI_LEGS}。"
            "两次为负仍是同样的两季：一次是口径变更，一次是 Design IP 真的没做到。"
        ),
    )

    # ── the guided share count ───────────────────────────────────────────────
    share_inside = sum(1 for index in finished
                       if shares_lo[index] <= shares_actual[index] <= shares_hi[index])
    share_below = [compact_period(quarters[index]) for index in finished
                   if shares_actual[index] < shares_lo[index]]
    shares_band = delivery_band(
        "EX_SHARES_RANGE", "摊薄股数", labels, shares_lo, shares_hi, shares_actual,
        fmt="f0c", ylab="百万股", unit="百万股", venue="业绩发布",
        src_extra=SOURCE_8K + "实际摊薄股数来自各季 8-K 合并损益表的每股计算股数。",
        extra_note=(
            f"<b>本站唯一一家把自己的股数也一并指引的公司</b>，{len(finished)} 季里"
            f"{share_inside} 季落在区间内、{len(share_below)} 季低于下限。"
            "低于下限不是失误而是好事 —— 那几季（"
            + "、".join(share_below)
            + "）公司回购买回的股比自己预告的还多，图上金色区间下方的菱形就是这个意思。"
            "这条线本来是全页最平的一条，直到 2025 年 7 月 Ansys 交割：台阶从 156 百万股"
            "一次抬到 187 百万股。<b>唯一一次冲出上限的 Q2'25 正是交割当季</b>："
            "公司 5 月给的区间是 156–158，实际报出 161.7，多出来的是并购当季新发的股，"
            "指引给的时候还不知道会落在哪一天。"
            "股数是 EPS 的分母，所以这张图必须和上面两张 EPS 图一起看："
            "收入与利润的超额是分子的事，这里是分母的事。"
        ),
    )

    charts = [revenue_band, revenue_dev, legs_chart, eps_band, eps_dev, shares_band]

    table = {
        "title": f"指引兑现全表（{len(quarters)} 季）：五项指引、实际值与超额的两条腿",
        "headers": ["期间", "公司口径", "收入指引", "实际收入", "较中值",
                    "non-GAAP 费用指引", "实际费用 D", "隐含营业利润 D", "实际营业利润",
                    "收入腿 D", "费用腿 D",
                    "non-GAAP EPS 指引", "实际 EPS", "股数指引", "实际股数"],
        "rows": [],
    }
    leg_at = {index: position for position, index in enumerate(finished)}
    for index, quarter in enumerate(quarters):
        done = revenue_actual[index] is not None
        position = leg_at.get(index)
        implied = revenue_mid[index] - expense_mid[index]
        actual_expense = (revenue_actual[index]
                          - record["actual_non_gaap_operating_income_usd_m"][index]) if done else None
        table["rows"].append([
            quarter,
            record["fiscal_labels"][index],
            f"${revenue_lo[index]:,.0f}–{revenue_hi[index]:,.0f}M",
            f"${revenue_actual[index]:,.1f}M" if done else "—",
            f"{pct_change(revenue_actual[index], revenue_mid[index]):+.2f}% D" if done else "—",
            f"${record['guide_non_gaap_expenses_lo_usd_m'][index]:,.0f}–"
            f"{record['guide_non_gaap_expenses_hi_usd_m'][index]:,.0f}M",
            f"${actual_expense:,.1f}M D" if done else "—",
            f"${implied:,.1f}M D",
            (f"${record['actual_non_gaap_operating_income_usd_m'][index]:,.1f}M"
             if done else "—"),
            f"{revenue_leg[position]:+,.1f} D" if position is not None else "—",
            f"{expense_leg[position]:+,.1f} D" if position is not None else "—",
            f"${eps_lo[index]:.2f}–{eps_hi[index]:.2f}",
            f"${eps_actual[index]:.2f}" if done else "—",
            f"{shares_lo[index]:.0f}–{shares_hi[index]:.0f}M",
            f"{shares_actual[index]:.3f}M" if done else "—",
        ])
    return charts, table


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    labels = [compact_period(period) for period in periods]
    financials = staging["financials"]
    segments = staging["segments_usd_m"]
    backlog = staging["backlog"]
    disagg = staging["disaggregation_usd_m"]
    capital = staging["capital_allocation_usd_m"]
    long = staging["long_history"]
    guidance = staging["guidance"]
    consensus = staging["market_expectation"]
    verdicts = staging["tracked_metric_verdicts"]
    closure = staging["followup_closure"]
    next_kpi = staging["next_kpi"]
    record = staging["quarterly_guidance_history"]

    revenue = financials["revenue_usd_m"]
    da_revenue = segments["design_automation_revenue"]
    ip_revenue = segments["design_ip_revenue"]
    da_margin = [oi / rev * 100 for oi, rev
                 in zip(segments["design_automation_adj_op_income"], da_revenue)]
    ip_margin = [oi / rev * 100 for oi, rev
                 in zip(segments["design_ip_adj_op_income"], ip_revenue)]
    amortization = financials["acquisition_amortization_usd_m"]
    amortization_share = [a / rev * 100 for a, rev in zip(amortization, revenue)]

    next_quarter = guidance["q3_2026_next_quarter"]
    # Synopsys does not guide a quarterly operating margin. The two midpoint
    # fields that used to sit in this block were the *full year*'s, and the page
    # printed one of them as the next quarter's -- understating the guided
    # margin by about 1.2pp and reversing its direction against this quarter.
    # They now live under `fy2026`, where the release puts them, and what the
    # table shows is the ratio the two guided ranges actually imply.
    implied_next_margin = (
        (sum(next_quarter["revenue_usd_m"]) / 2
         - sum(next_quarter["non_gaap_expenses_usd_m"]) / 2)
        / (sum(next_quarter["revenue_usd_m"]) / 2) * 100
    )
    full_year = guidance["fy2026"]
    footnote = guidance["fy2026_revenue_footnote"]

    # ── section one ──────────────────────────────────────────────────────────
    delivery_charts, delivery_table = guidance_delivery_charts(staging)
    current = record["fiscal_labels"].index("FY2026Q3")
    guided_revenue = (record["guide_revenue_lo_usd_m"][current]
                      + record["guide_revenue_hi_usd_m"][current]) / 2
    guided_expense = (record["guide_non_gaap_expenses_lo_usd_m"][current]
                      + record["guide_non_gaap_expenses_hi_usd_m"][current]) / 2
    guided_eps = (record["guide_non_gaap_eps_lo_usd"][current]
                  + record["guide_non_gaap_eps_hi_usd"][current]) / 2
    guided_gaap_eps = (record["guide_gaap_eps_lo_usd"][current]
                       + record["guide_gaap_eps_hi_usd"][current]) / 2
    guided_shares = (record["guide_shares_lo_m"][current]
                     + record["guide_shares_hi_m"][current]) / 2
    actual_expense = revenue[-1] - financials["non_gaap_operating_income_usd_m"][-1]
    implied_oi = guided_revenue - guided_expense

    verdict_chart = {
        "kind": "bars_labeled",
        "title": (
            f"上季 5 条跟踪指标：{verdicts['counts'][0]} 条触发（正面）、"
            f"{verdicts['counts'][1]} 条部分触发、{verdicts['counts'][2]} 条未触发、"
            f"{verdicts['counts'][3]} 条被判为指标设计失效"
        ),
        "xlabels": verdicts["labels"],
        "values": verdicts["counts"],
        "legend": "指标条数",
        "fmt": "f0",
        "yfmt": "f0",
        "label_fmt": "f0",
        "ylab": "条",
        "note": verdicts["note"] + (
            "<b>另有一组数是本季闭环质量的直接读数</b>：上季留下的 5 条待验证问题里，"
            f"{closure['counts'][0]} 条完全验证、{closure['counts'][1]} 条部分验证、"
            f"{closure['counts'][2]} 条仍未披露、{closure['counts'][3]} 条被证伪。"
            "一条都没闭环，也一条都没被推翻 —— 本季的信息增量在财务执行，不在结构性举证。"
        ),
        "src_extra": (
            "指标与阈值为本地研究设定，不是公司指引；"
            "判定依据 2026-08-26 业绩 8-K、截至 2026-07-31 的 10-Q 与业绩电话会。"
        ),
    }

    delivery = [
        ("收入", pct_change(revenue[-1], guided_revenue)),
        # Spending less than guided is the safe side, so the sign is flipped to
        # keep "positive means better than guided" true across the whole bar.
        ("non-GAAP 费用", -pct_change(actual_expense, guided_expense)),
        ("隐含 non-GAAP 营业利润",
         pct_change(financials["non_gaap_operating_income_usd_m"][-1], implied_oi)),
        ("non-GAAP EPS", pct_change(financials["non_gaap_eps_usd"][-1], guided_eps)),
        ("摊薄股数", -pct_change(financials["diluted_shares_m"][-1], guided_shares)),
    ]
    # GAAP EPS also cleared its guided range, by +212%, but a bar that long makes
    # every other bar on this axis unreadable -- and the number is not comparable
    # anyway, because a one-off divestiture gain sits inside it. It is stated in
    # the note instead of drawn.
    gaap_eps_beat = pct_change(financials["gaap_eps_usd"][-1], guided_gaap_eps)
    # The GAAP expense line is the one guided number that did not beat its
    # midpoint. It is not on the bar -- it measures the same thing as the
    # non-GAAP expense line on a different basis -- so the note has to say it.
    next_quarter_gaap_lo = record["guide_gaap_expenses_lo_usd_m"][current]
    next_quarter_gaap_hi = record["guide_gaap_expenses_hi_usd_m"][current]
    gaap_expense = revenue[-1] - financials["gaap_operating_income_usd_m"][-1]
    gaap_expense_gap = pct_change(gaap_expense,
                                  (next_quarter_gaap_lo + next_quarter_gaap_hi) / 2)
    delivery_chart = {
        "ref": "EX_DELIVERY",
        "kind": "diverging_bars",
        "title": (
            f"本季这五项全部优于指引中值：收入 {signed(delivery[0][1])}，"
            f"non-GAAP EPS {signed(delivery[3][1])}"
        ),
        "xlabels": [metric for metric, _ in delivery],
        "values": [round(value, 2) for _, value in delivery],
        "legend": "优于指引中值的幅度",
        "positive_label": "优于指引",
        "negative_label": "逊于指引",
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "% vs 指引中值",
        "zero_line": True,
        "note": (
            "<b>五根柱的高度差本身就是结论</b>：收入只比中值高 "
            f"{delivery[0][1]:.1f}%，non-GAAP EPS 却高 {delivery[3][1]:.1f}% —— "
            "越往损益表下方走，超额越大，而中间那根「隐含营业利润」正是两者之间的那一步。"
            f"<b>GAAP EPS 同样超出指引，而且超出 {gaap_eps_beat:.0f}%，但本图刻意不画它</b>："
            "一根那么长的柱会把其余四根压平，而且这个数本身不可比 —— "
            "本季 GAAP 利润里含一笔 Processor IP Solutions 出售的税前收益，"
            "它不进 non-GAAP，却全额进 GAAP，见 Exhibit {EX_WEDGE}。"
            "费用与股数两项已按「比承诺少为正」翻过符号，与其余各项方向统一。"
            f"<b>并非每一条指引都优于中值</b>：公司同时指引的 GAAP 费用报出 "
            f"US${gaap_expense:,.0f}M，落在 US${next_quarter_gaap_lo:,.0f}–"
            f"{next_quarter_gaap_hi:,.0f}M 的区间内，但比中值高 {gaap_expense_gap:.1f}%，"
            "是本季唯一一条没做到中值的。它没有画在这根轴上，因为它与 non-GAAP 费用"
            "衡量的是同一件事的两种口径，并列会重复计数。"
            "这几项的长窗口记录见 Exhibit {EX_REV_RANGE} 起的指引兑现组图。"
        ),
        "src_extra": (
            f"指引为上季（2026-05-27）业绩 8-K 的 Financial Targets 表所载本季口径："
            f"收入 US${record['guide_revenue_lo_usd_m'][current]:,.0f}–"
            f"{record['guide_revenue_hi_usd_m'][current]:,.0f}M、"
            f"non-GAAP 费用 US${record['guide_non_gaap_expenses_lo_usd_m'][current]:,.0f}–"
            f"{record['guide_non_gaap_expenses_hi_usd_m'][current]:,.0f}M、"
            f"non-GAAP EPS ${record['guide_non_gaap_eps_lo_usd'][current]:.2f}–"
            f"{record['guide_non_gaap_eps_hi_usd'][current]:.2f}、"
            f"摊薄股数 {record['guide_shares_lo_m'][current]:.0f}–"
            f"{record['guide_shares_hi_m'][current]:.0f}M；"
            "隐含营业利润为收入与费用两个中值之差，不是公司披露值。"
        ),
    }

    gaap_eps_qoq = pct_change(financials["gaap_eps_usd"][-1], financials["gaap_eps_usd"][-2])
    gaap_oi_qoq = pct_change(financials["gaap_operating_income_usd_m"][-1],
                             financials["gaap_operating_income_usd_m"][-2])
    expectation = [
        ("营收 vs 市场预期", pct_change(revenue[-1], consensus["revenue_usd_m"])),
        ("non-GAAP EPS vs 市场预期",
         pct_change(financials["non_gaap_eps_usd"][-1], consensus["non_gaap_eps_usd"])),
        ("下季 non-GAAP EPS 指引中值 vs 市场预期",
         pct_change((next_quarter["non_gaap_eps_usd"][0] + next_quarter["non_gaap_eps_usd"][1]) / 2,
                    consensus["next_quarter_non_gaap_eps_usd"])),
        ("non-GAAP 营业利润 环比",
         pct_change(financials["non_gaap_operating_income_usd_m"][-1],
                    financials["non_gaap_operating_income_usd_m"][-2])),
        ("non-GAAP EPS 环比",
         pct_change(financials["non_gaap_eps_usd"][-1], financials["non_gaap_eps_usd"][-2])),
    ]
    expectation_chart = {
        "ref": "EX_EXPECTATION",
        "kind": "diverging_bars",
        "title": (
            f"本季对市场预期只是常规幅度，真正超出的是下季指引："
            f"EPS 指引中值高出预期 {expectation[2][1]:.1f}%"
        ),
        "xlabels": [metric for metric, _ in expectation],
        "values": [round(value, 2) for _, value in expectation],
        "legend": "较对照的幅度",
        "positive_label": "高于对照",
        "negative_label": "低于对照",
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "zero_line": True,
        "ylab": "%",
        "note": (
            "<b>真正的意外不在本季，在下季指引</b>：本季收入与 EPS 对市场预期的超出各为 "
            f"{expectation[0][1]:.1f}% 与 {expectation[1][1]:.1f}%，属常规幅度；"
            f"下一季 non-GAAP EPS 指引中值 US${(next_quarter['non_gaap_eps_usd'][0] + next_quarter['non_gaap_eps_usd'][1]) / 2:.2f} "
            f"却比同一时点的公开隐含预期高出 {expectation[2][1]:.1f}%，这才是本季信息量最大的一格。"
            "<b>GAAP 口径的环比被刻意排除在本图之外</b>，因为它会撑爆这根轴而且没有含义："
            f"GAAP 营业利润环比 {gaap_oi_qoq:+.0f}%、GAAP EPS 从 "
            f"US${financials['gaap_eps_usd'][-2]:.2f} 到 US${financials['gaap_eps_usd'][-1]:.2f}（"
            f"{gaap_eps_qoq:+.0f}%）—— 上一季被 US$115.9M 重组费用压平、"
            "本季被一笔出售业务的税前收益推高，两季都不干净。"
            f"同期 non-GAAP 营业利润环比 {expectation[3][1]:+.1f}%，那才是经营斜率。"
            "前三根柱对的是市场预期，后两根是环比，两类对照并列于同一轴上，"
            "只用于比较方向与相对幅度。"
        ),
        "src_extra": (
            f"实际值来自 2026-08-26 业绩 8-K；市场预期为财报前公开隐含一致预期"
            f"（{consensus['as_of']}），不具名、不引用任何机构。"
        ),
    }

    # ── section two ──────────────────────────────────────────────────────────
    revenue_chart = {
        "ref": "EX_REVENUE",
        "kind": "gs_bar",
        "title": (
            f"收入 US${revenue[-1]:,.0f}M、同比 {signed(financials['revenue_yoy_pct'][-1])}，"
            "但同比里有一大半不是自己长出来的"
        ),
        "xlabels": labels,
        "values": revenue,
        "legend": "季度收入",
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$M",
        "ylab2": "同比增速",
        "yoy": {
            "name": "收入 YoY (RHS)",
            "values": rounded(financials["revenue_yoy_pct"]),
            "color": "GREEN",
            "yfmt": "pct0",
        },
        "note": (
            f"环比 {signed(pct_change(revenue[-1], revenue[-2]))}。"
            "绿线从 Q3'25 起的抬升几乎全部是 Ansys 并表的机械结果 —— 该笔交易在 2025 年 7 月 17 日交割，"
            "所以 Q2'25 只并进两周、Q2'26 是第一个两边都是全季的比较。"
            "<b>公司自己给的口径是这条线唯一可核对的锚</b>："
            f"FY2026 收入指引的脚注写明其中含 US${footnote['expected_ansys_revenue_usd_m'][-1]:,.0f}M 的 Ansys 收入，"
            f"占指引中点的 {footnote['expected_ansys_revenue_usd_m'][-1] / ((full_year['revenue_usd_m'][0] + full_year['revenue_usd_m'][1]) / 2) * 100:.1f}%，"
            "拆解见 Exhibit {EX_FY_SPLIT}。"
            "公司未按季披露 Ansys 的实际收入，所以本页不画季度级的「剔除 Ansys」曲线。"
        ),
        "src_extra": "收入来自各季业绩 8-K 合并损益表；同比为自算 D，分母见口径说明。",
    }

    segment_chart = {
        "ref": "EX_SEG_REV",
        "kind": "grouped_bars",
        "title": (
            f"Design IP 连续三季同比负增长后重新转正：US${ip_revenue[-1]:,.0f}M，同比 "
            f"{signed(pct_change(ip_revenue[-1], ip_revenue[-5]))}"
        ),
        "xlabels": labels,
        "groups": [
            {"name": "Design Automation", "color": "NAVY", "values": da_revenue},
            {"name": "Design IP", "color": "GOLD", "values": ip_revenue},
        ],
        "bar_labels": False,
        "fmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$M",
        "note": (
            "<b>金色那条是本季最该看的一条线</b>，因为它正是 Exhibit {EX_REV_DEV} 里"
            "那次真实跌破指引的原因：Q2'25 公司在新闻稿里直接写「IP 业务低于预期」，"
            f"随后三季 Design IP 一路下滑到 US${min(ip_revenue):,.0f}M，"
            f"本季回到 US${ip_revenue[-1]:,.0f}M、同比 "
            f"{signed(pct_change(ip_revenue[-1], ip_revenue[-5]))}。"
            "深蓝的 Design Automation 从 Q3'25 起的台阶是 Ansys 并入该分部造成的，"
            "不是这条线自己的斜率。两个分部的口径自 2024 年起为两分部制，"
            "此前还有第三个 Software Integrity 分部，见口径说明。"
        ),
        "src_extra": (
            "分部收入来自各季业绩 8-K 的 Business Segment Reporting 表；"
            "会计季 Q4 无 10-Q，其值为财年数减九个月数 D，两端均为申报值。"
        ),
    }

    segment_margin_chart = {
        "ref": "EX_SEG_MARGIN",
        "kind": "lines",
        "title": (
            f"两个分部的调整后营业利润率同时改善：Design Automation {da_margin[-1]:.1f}%、"
            f"Design IP {ip_margin[-1]:.1f}%"
        ),
        "xlabels": labels,
        "series": [
            {"name": "Design Automation 调整后营业利润率", "values": rounded(da_margin),
             "color": "NAVY"},
            {"name": "Design IP 调整后营业利润率", "values": rounded(ip_margin), "color": "GOLD"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "调整后营业利润率",
        "note": (
            f"Design IP 的利润率从 Q3'25 的 {min(ip_margin):.1f}% 低点回到 {ip_margin[-1]:.1f}%，"
            f"同比 {ip_margin[-1] - ip_margin[-5]:+.1f}pp —— <b>回升由收入杠杆驱动</b>："
            f"同期该分部收入同比 {signed(pct_change(ip_revenue[-1], ip_revenue[-5]))}，"
            "利润率与收入同向，不是砍费用砍出来的。"
            "两条线相除的分母是各自分部的收入，"
            "分子是公司披露的 adjusted operating income（在集团层面剔除摊销、股权激励、"
            "重组与并购项之前的分部口径），因此<b>不能</b>与合并层面的 GAAP 营业利润率相比，"
            "两者的差额见 Exhibit {EX_WEDGE}。"
        ),
        "src_extra": (
            "分部调整后营业利润来自各季业绩 8-K 的 Business Segment Reporting 表；"
            "利润率为自算 D（公司同表也披露该比率，四舍五入到 0.1pp，与自算一致）。"
        ),
    }

    wedge_chart = {
        "ref": "EX_WEDGE",
        "kind": "grouped_bars",
        "title": (
            f"GAAP 与 non-GAAP 营业利润之间隔着 US${financials['non_gaap_operating_income_usd_m'][-1] - financials['gaap_operating_income_usd_m'][-1]:,.0f}M，"
            f"其中收购摊销一项就占收入的 {amortization_share[-1]:.1f}%"
        ),
        "xlabels": labels,
        "groups": [
            {"name": "GAAP 营业利润", "color": "NAVY",
             "values": financials["gaap_operating_income_usd_m"]},
            {"name": "调整后（non-GAAP）营业利润", "color": "MBLUE",
             "values": financials["non_gaap_operating_income_usd_m"]},
            {"name": "其中：收购无形资产摊销", "color": "GOLD", "values": amortization},
            {"name": "其中：股权激励费用", "color": "GRAY",
             "values": financials["stock_based_compensation_usd_m"]},
        ],
        "bar_labels": False,
        "fmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$M",
        "note": (
            "<b>金色柱在 Q3'25 之后的跳升是这一页最重要的一个台阶</b>："
            f"收购无形资产摊销从并购前的季均 US${sum(amortization[:3]) / 3:,.0f}M "
            f"一次跳到 US${amortization[-1]:,.0f}M，相当于本季收入的 {amortization_share[-1]:.1f}%。"
            "它同时出现在营业成本与营业费用两行，本图取两行之和。"
            "深蓝与浅蓝之间的距离就是 non-GAAP 口径剔除掉的全部东西 —— "
            "摊销、股权激励、重组与并购项。"
            "<b>这不是在质疑 non-GAAP 的合理性，而是提醒它的量级</b>："
            "同一个季度，一套口径的营业利润率是 "
            f"{financials['gaap_operating_margin_pct'][-1]:.1f}%，另一套是 "
            f"{financials['non_gaap_operating_margin_pct'][-1]:.1f}%，相差 "
            f"{financials['non_gaap_operating_margin_pct'][-1] - financials['gaap_operating_margin_pct'][-1]:.1f}pp。"
            "十年维度上这道裂口是怎么长出来的，见 Exhibit {EX_AMORT_LONG}。"
        ),
        "src_extra": (
            "GAAP 营业利润来自各季 8-K 合并损益表；调整后营业利润为同一份新闻稿的"
            "「total adjusted segment operating income」；"
            "收购摊销为合并损益表中营业成本与营业费用两行之和 D。"
        ),
    }

    base_revenue, base_income, base_eps, base_shares = (
        revenue[0], financials["non_gaap_net_income_usd_m"][0],
        financials["non_gaap_eps_usd"][0], financials["diluted_shares_m"][0])
    dilution_chart = {
        "ref": "EX_DILUTION",
        "kind": "lines",
        "title": (
            f"八季里收入指数化到 {revenue[-1] / base_revenue * 100:.0f}、"
            f"non-GAAP 净利到 {financials['non_gaap_net_income_usd_m'][-1] / base_income * 100:.0f}，"
            f"而每股只到 {financials['non_gaap_eps_usd'][-1] / base_eps * 100:.0f}"
        ),
        "xlabels": labels,
        "series": [
            {"name": "收入", "values": rounded([v / base_revenue * 100 for v in revenue]),
             "color": "NAVY"},
            {"name": "non-GAAP 净利",
             "values": rounded([v / base_income * 100
                                for v in financials["non_gaap_net_income_usd_m"]]),
             "color": "MBLUE"},
            {"name": "摊薄股数",
             "values": rounded([v / base_shares * 100 for v in financials["diluted_shares_m"]]),
             "color": "GOLD"},
            {"name": "non-GAAP EPS",
             "values": rounded([v / base_eps * 100 for v in financials["non_gaap_eps_usd"]]),
             "color": "GREEN"},
        ],
        "fmt": "f0",
        "yfmt": "f0",
        "label_fmt": "f0",
        "end_label": True,
        "ylab": f"指数（{periods[0]} = 100）",
        "note": (
            "<b>这张图只说一件事：金色线是绿线为什么走不上去的原因。</b>"
            f"以 {periods[0]} 为 100，收入走到 {revenue[-1] / base_revenue * 100:.0f}、"
            f"non-GAAP 净利走到 {financials['non_gaap_net_income_usd_m'][-1] / base_income * 100:.0f}，"
            f"但摊薄股数同时走到 {financials['diluted_shares_m'][-1] / base_shares * 100:.0f} —— "
            f"于是每股口径只到 {financials['non_gaap_eps_usd'][-1] / base_eps * 100:.0f}。"
            "对本季单季来说是同一件事的另一种说法：收入同比 "
            f"{signed(financials['revenue_yoy_pct'][-1])}、non-GAAP 净利同比 "
            f"{signed(pct_change(financials['non_gaap_net_income_usd_m'][-1], financials['non_gaap_net_income_usd_m'][-5]))}、"
            f"每股同比只有 {signed(pct_change(financials['non_gaap_eps_usd'][-1], financials['non_gaap_eps_usd'][-5]))}。"
            "股数的台阶来自 Ansys 对价里以股份支付的那一半（公司为该交易发行 3,000 万股），"
            "而不是逐季的股权激励；十年维度上的股数与回购见 Exhibit {EX_BUYBACK}。"
        ),
        "src_extra": (
            "四条线均由各季 8-K 的合并损益表与 GAAP/non-GAAP 对账数指数化 D，"
            "基期为本窗口第一季。"
        ),
    }

    fy_mid = [(lo + hi) / 2 for lo, hi
              in zip(footnote["revenue_lo_usd_m"], footnote["revenue_hi_usd_m"])]
    ansys = footnote["expected_ansys_revenue_usd_m"]
    core = [total - a for total, a in zip(fy_mid, ansys)]
    fy_split_chart = {
        "ref": "EX_FY_SPLIT",
        "kind": "grouped_bars",
        "title": (
            f"FY2026 收入指引四次上调共 US${fy_mid[-1] - fy_mid[0]:+,.0f}M，"
            f"其中 Ansys 那块贡献 US${ansys[-1] - ansys[0]:+,.0f}M"
        ),
        "xlabels": footnote["releases"],
        "groups": [
            {"name": "其余业务 D", "color": "NAVY", "values": rounded(core)},
            {"name": "指引脚注载明的 Ansys 收入", "color": "GOLD", "values": ansys},
        ],
        "bar_labels": True,
        "fmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "FY2026 收入指引中点 US$M",
        "note": (
            "<b>这是全页唯一能把并购与原生分开的地方，而且分法是公司自己给的。</b>"
            "每份新闻稿的 FY2026 收入指引下面都挂着一条脚注，写明这个数里含多少 Ansys 收入。"
            f"把四次指引并排：中点从 US${fy_mid[0]:,.0f}M 抬到 US${fy_mid[-1]:,.0f}M，"
            f"共 US${fy_mid[-1] - fy_mid[0]:+,.0f}M；同期脚注里的 Ansys 从 "
            f"US${ansys[0]:,.0f}M 抬到 US${ansys[-1]:,.0f}M，"
            f"即 US${ansys[-1] - ansys[0]:+,.0f}M。"
            f"两者相减，其余业务这三次合计只上修了 US${core[-1] - core[0]:+,.0f}M。"
            "<b>脚注里还有一句更值得记的话</b>：2026-05-27 那份写明 US$2,960M 里含 "
            "US$60M 是 Ansys 渠道伙伴的会计影响 —— 这是公司唯一一次在申报文件里给该会计项标价，"
            "它进收入、不进利润。前两次脚注只提 OSG 与 PowerArtist RTL 约 US$110M 的剥离影响，"
            "后两次加上 Processor IP Solutions 的 US$40M。"
        ),
        "src_extra": (
            "四个指引中点与其脚注均取自 2025-12-10、2026-02-25、2026-05-27、2026-08-26 "
            "四份业绩 8-K 的 EX-99.1；「其余业务」为中点减脚注 Ansys 数的自算值 D，"
            "不是公司披露的分部拆分。"
        ),
    }

    # ── section three ────────────────────────────────────────────────────────
    ip_yoy = [None] * 4 + [pct_change(ip_revenue[i], ip_revenue[i - 4])
                           for i in range(4, len(ip_revenue))]
    twelve_month = [(b - f) * p / 100 for b, f, p
                    in zip(backlog["backlog_usd_b"], backlog["fsa_usd_b"],
                           backlog["next_12m_pct_of_ex_fsa"])]
    fsa_share = [f / b * 100 for f, b in zip(backlog["fsa_usd_b"], backlog["backlog_usd_b"])]
    backlog_labels = [compact_period(quarter) for quarter in backlog["quarters"]]

    tracked = {
        "non-GAAP 营业利润率": (labels, rounded(financials["non_gaap_operating_margin_pct"]),
                                "pct1", "营业利润率", "non-GAAP 营业利润率"),
        "Design IP 收入同比": (labels, rounded(ip_yoy), "pct1", "同比", "Design IP 同比"),
        "未来 12 个月可确认 backlog": (backlog_labels, rounded(twelve_month), "f1",
                                       "US$B", "未来 12 个月可确认额 D"),
        "FSA 占 backlog": (backlog_labels, rounded(fsa_share), "pct1", "占 backlog 比重",
                           "FSA 占比 D"),
        "摊薄股数": (labels, financials["diluted_shares_m"], "f0c", "百万股", "摊薄股数"),
    }

    def tracking_charts(entries: list[dict]) -> list[dict]:
        charts = []
        for entry in entries:
            metric = entry["metric"]
            if metric not in tracked:
                continue
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
                ),
                src_extra=(
                    "实际值来自各季业绩 8-K 与 10-Q；阈值为本地研究设定，不是公司指引。"
                ),
            ))
        return charts

    margins = {entry["metric"]: headroom(entry["direction"], entry["threshold"], entry["current"])
               for entry in next_kpi["quantified"]}
    breached = [metric for metric, value in margins.items() if value < 0]
    thinnest = min(margins, key=margins.get)
    headroom_chart = headroom_exhibit(
        (f"下季 5 条量化阈值：{len(margins) - len(breached)} 条仍在安全侧，"
         f"{len(breached)} 条已越线"
         if breached else
         f"下季 5 条量化阈值：全部仍在安全侧，最薄的「{thinnest}」只剩 {margins[thinnest]:.1f}%"),
        next_kpi["quantified"],
        "current",
        (
            "正值 = 仍在安全侧。<b>余量最薄的两条最值得盯，而且性质完全不同</b>："
            f"<b>摊薄股数</b>只剩 {margins['摊薄股数']:.1f}% —— 这是全表唯一一条阈值不是本地设定的，"
            "194M 就是公司自己在同一张指引表里写的上限，所以越线等于公司没做到自己的数；"
            f"<b>non-GAAP 营业利润率</b> {financials['non_gaap_operating_margin_pct'][-1]:.1f}% "
            f"对 41.0% 的警戒线剩 {margins['non-GAAP 营业利润率']:.1f}%，"
            "而公司把 FY2026 全年中点定在 41.5%，这条线现在既是研究阈值也是公司承诺。"
            f"另一条值得看的是 FSA 占 backlog：{fsa_share[-1]:.1f}% 对 18.0% 剩 "
            f"{margins['FSA 占 backlog']:.1f}%，它是 backlog 里客户可自由调配的那部分，"
            "占比连续上行才算信号 —— 单季变化建立在 US$0.1B 的取整精度上，"
            "1.8 到 1.9 有可能只是 1.84 到 1.86（见 Exhibit {EX_BACKLOG}）。"
        ),
        src_extra=(
            "阈值为本地研究设定，不是公司指引（股数一条的 194M 取自公司自己的指引上限）；"
            "当前值为截至 2026-07-31 的实际。" + next_kpi["excluded"]
        ),
    )

    # ── section four ─────────────────────────────────────────────────────────
    long_labels = long["fiscal_years"]
    long_amortization = [c + o for c, o in zip(long["amortization_cost_of_revenue_usd_m"],
                                               long["amortization_opex_usd_m"])]
    long_amort_share = [a / r * 100 for a, r in zip(long_amortization, long["revenue_usd_m"])]
    long_margin = [oi / r * 100 for oi, r
                   in zip(long["operating_income_usd_m"], long["revenue_usd_m"])]
    long_margin_ex = [(oi + a) / r * 100 for oi, a, r
                      in zip(long["operating_income_usd_m"], long_amortization,
                             long["revenue_usd_m"])]
    fy26_amort_share = (amortization[-1] * 4
                        / ((full_year["revenue_usd_m"][0] + full_year["revenue_usd_m"][1]) / 2) * 100)
    trough_year = long_labels[long_amort_share.index(min(long_amort_share))]

    amort_chart = {
        "ref": "EX_AMORT_LONG",
        "kind": "gs_line",
        "title": (
            f"收购摊销强度从 FY2016 的 {long_amort_share[0]:.1f}% 一路降到 {trough_year} 的 "
            f"{min(long_amort_share):.1f}%，Ansys 一笔又把它推到 {amortization_share[-1]:.1f}%"
        ),
        "xlabels": long_labels,
        "values": rounded(long_amort_share),
        "legend": "收购无形资产摊销 / 收入",
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "占收入比",
        "note": (
            "<b>这条线是本页四张长图里最该先看的一张。</b>"
            f"从 FY2016 的 {long_amort_share[0]:.1f}% 一路降到 "
            f"{trough_year} 的 {min(long_amort_share):.1f}% —— "
            "旧并购的无形资产逐年摊完，而收入在长大，"
            "GAAP 与 non-GAAP 之间的距离因此越来越小，两套口径几乎收敛。"
            f"FY2025 因 Ansys 在 7 月并入而回到 {long_amort_share[-1]:.1f}%，"
            f"而本季（{labels[-1]}）单季已是 {amortization_share[-1]:.1f}%，"
            f"按公司自己的 FY2026 收入指引中点年化约 {fy26_amort_share:.1f}%。"
            "<b>换句话说，十年里被摊完的东西被一笔交易一次性加了回来，而且量级是过去的三倍。</b>"
            "这决定了未来若干年 GAAP 与 non-GAAP 的距离不会自己收窄："
            "本页这十年里没有任何一年接近过现在的水平。"
        ),
        "src_extra": (
            "逐年读自各年 10-K 合并损益表的两行「Amortization of acquired intangible assets」"
            "（营业成本内与营业费用内）之和 D，除以当年收入；每年取该年 10-K 首次印出的数。"
            "FY2026 一栏为本页八季窗口的最新一季，与年度值不可直接连读。"
        ),
    }

    margin_wedge_chart = {
        "ref": "EX_MARGIN_LONG",
        "kind": "lines",
        "title": (
            f"GAAP 营业利润率一年之内从 {long_margin[-2]:.1f}% 掉到 {long_margin[-1]:.1f}%，"
            f"其中 {long_amort_share[-1] - long_amort_share[-2]:.1f}pp 是收购摊销"
        ),
        "xlabels": long_labels,
        "series": [
            {"name": "GAAP 营业利润率", "values": rounded(long_margin), "color": "NAVY"},
            {"name": "加回收购摊销后的营业利润率 D", "values": rounded(long_margin_ex),
             "color": "GOLD"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "营业利润率",
        "note": (
            "<b>上一张画裂口，这一张画水平 —— 而水平才是掉下去的那个。</b>"
            f"GAAP 营业利润率从 FY2024 的 {long_margin[-2]:.1f}% 掉到 FY2025 的 "
            f"{long_margin[-1]:.1f}%，一年 {long_margin[-1] - long_margin[-2]:.1f}pp。"
            f"金线同期从 {long_margin_ex[-2]:.1f}% 到 {long_margin_ex[-1]:.1f}%，只掉 "
            f"{long_margin_ex[-1] - long_margin_ex[-2]:.1f}pp —— "
            f"<b>也就是说这 {abs(long_margin[-1] - long_margin[-2]):.1f}pp 的跌幅里，"
            f"{long_amort_share[-1] - long_amort_share[-2]:.1f}pp 是收购摊销，"
            f"剩下的 {abs(long_margin_ex[-1] - long_margin_ex[-2]):.1f}pp 才是别的东西</b>"
            "（重组费用与并购完成当年抬高的股权激励）。"
            "<b>本图刻意只加回收购摊销这一项，不加股权激励也不加重组</b>："
            "只有摊销是「已经付过的钱在往后年份里摊」，"
            "把它单独拿出来，两条线的距离才对应一个可解释的东西 —— "
            "为收购付出的对价，还剩多少没走完损益表。"
            "公司自己的 non-GAAP 口径比这里剔得更多，因此其利润率高于金线："
            "本季两者分别是 "
            f"{financials['non_gaap_operating_margin_pct'][-1]:.1f}% 与 "
            f"{(financials['gaap_operating_income_usd_m'][-1] + amortization[-1]) / revenue[-1] * 100:.1f}%。"
        ),
        "src_extra": (
            "两条线的分子分母同为各年 10-K 合并损益表数；加回项为该表两行收购摊销之和 D。"
        ),
    }

    buyback_chart = {
        "ref": "EX_BUYBACK",
        "kind": "grouped_bars",
        "title": (
            f"连续八年每年买回 US${min(v for v in long['share_repurchases_usd_m'] if v > 0):,.0f}M "
            f"以上，然后连着两年归零 —— 股数十年首次上台阶"
        ),
        "xlabels": long_labels,
        "groups": [
            {"name": "当年回购金额", "color": "NAVY",
             "values": rounded(long["share_repurchases_usd_m"])},
        ],
        "line": {
            "name": "摊薄股数 (RHS)",
            "values": rounded(long["diluted_shares_m"]),
            "color": "GOLD",
            "yfmt": "f0c",
        },
        "bar_labels": False,
        "fmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "回购金额 US$M",
        "ylab2": "摊薄股数（百万股）",
        "note": (
            "<b>金线十年几乎是一条平线，这本身就是深蓝柱子的功劳。</b>"
            f"FY2016–FY2023 每年回购 US${min(v for v in long['share_repurchases_usd_m'] if v > 0):,.0f}M "
            f"到 US${max(long['share_repurchases_usd_m']):,.0f}M，"
            f"把摊薄股数按在 {min(long['diluted_shares_m']):.0f}–{max(long['diluted_shares_m'][:8]):.0f} 百万股之间，"
            "股权激励发多少就买回多少。"
            "<b>然后 FY2024 与 FY2025 连着两年一股未买</b> —— 那是为 Ansys 攒钱与去杠杆的两年，"
            f"而 FY2025 的股数一次抬到 {long['diluted_shares_m'][-1]:.0f} 百万股。"
            f"进入 FY2026 后公司在 2 月把授权补到 US$2.0B，本财年前三季实际动用 US${sum(v for v in capital['buyback_usd_m'][-3:] if v):,.0f}M，"
            f"7 月 31 日仍余 US${capital['remaining_authorization_usd_m'][-1]:,.0f}M；"
            "最近一季的现金流出 US$37.5M 是上一季那笔加速回购的交割尾款，"
            "授权余额整个季度<b>一美元未动</b>。"
            "每股口径这两年为什么走不动，见 Exhibit {EX_DILUTION}。"
        ),
        "src_extra": (
            "回购金额与摊薄股数逐年读自各年 10-K；FY2026 各季回购与授权余额来自各季 10-Q 的"
            "现金流量表与 Item 2(c)，会计季 Q4 与季度差分为自算 D。"
        ),
    }

    backlog_chart = {
        "ref": "EX_BACKLOG",
        "kind": "lines",
        "title": (
            f"backlog 自 FY2025 年末的 US${max(backlog['backlog_usd_b']):.1f}B 连降三季至 "
            f"US${backlog['backlog_usd_b'][-1]:.1f}B，但可确认的那一半还在创新高"
        ),
        "xlabels": backlog_labels,
        "series": [
            {"name": "backlog（含 FSA）", "values": backlog["backlog_usd_b"], "color": "NAVY"},
            {"name": "其中：不可撤销 FSA 承诺", "values": backlog["fsa_usd_b"], "color": "GRAY"},
            {"name": "未来 12 个月可确认额 D", "values": rounded(twelve_month), "color": "GOLD"},
        ],
        "fmt": "f1",
        "yfmt": "f1",
        "label_fmt": "f1",
        "end_label": True,
        "ylab": "US$B",
        "note": (
            "<b>深蓝在降、金色在升，这两件事同时为真，而且不矛盾。</b>"
            f"总额从 US${max(backlog['backlog_usd_b']):.1f}B 降到 "
            f"US${backlog['backlog_usd_b'][-1]:.1f}B，同比仍是 "
            f"{signed(pct_change(backlog['backlog_usd_b'][-1], backlog['backlog_usd_b'][-5]))}；"
            "而公司在同一句话里披露的「未来 12 个月内可确认的比例」从 40% 一路升到 "
            f"{backlog['next_12m_pct_of_ex_fsa'][-1]:.0f}%，"
            f"于是可确认额反而升到 US${twelve_month[-1]:.2f}B。"
            "<b>口径必须说清楚</b>：那个百分比在申报文件里是对<b>扣除 FSA 之后</b>的 backlog 说的，"
            "所以金线 = （深蓝 − 灰）× 该百分比，不是深蓝乘以它。"
            "灰线是客户可自由调配额度的不可撤销承诺，占比见第三节的阈值图。"
            "本图为各季申报当时的数：FY2024 10-K 曾把 2023-10-31 的 8.6 重述为 8.1，"
            "差额来自 Software Integrity 剥离，本页画当时申报值而不追溯改写。"
        ),
        "src_extra": (
            "backlog、FSA 与百分比逐季读自各期 10-Q / 10-K 的收入附注原句"
            "（公司披露精度为 US$0.1B 与整数百分点）；可确认额为自算 D。"
        ),
    }

    geo_labels = [compact_period(quarter) for quarter in disagg["quarters"]]
    geo_series = [
        ("United States", "united_states", "NAVY"),
        ("Europe", "europe", "MBLUE"),
        ("Korea", "korea", "GOLD"),
        ("China", "china", "RED"),
        ("Other", "other", "GRAY"),
    ]
    geo_shares = {key: [v / t * 100 for v, t in zip(disagg[key], disagg["revenue_usd_m"])]
                  for _, key, _ in geo_series}
    geography_chart = {
        "ref": "EX_GEO",
        "kind": "lines",
        "title": (
            f"中国占比十三季从 {geo_shares['china'][0]:.1f}% 降到 {geo_shares['china'][-1]:.1f}%，"
            f"韩国同期从 {geo_shares['korea'][0]:.1f}% 升到 {geo_shares['korea'][-1]:.1f}%"
        ),
        "xlabels": geo_labels,
        "series": [
            {"name": name, "values": rounded(geo_shares[key]), "color": color}
            for name, key, color in geo_series
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "占季度收入比重",
        "note": (
            "<b>红线与金线的交叉是这十三季地域结构里最实的一件事</b>："
            f"中国占比从 {max(geo_shares['china']):.1f}% 的高点降到 {geo_shares['china'][-1]:.1f}%，"
            f"韩国从 {geo_shares['korea'][0]:.1f}% 升到 {geo_shares['korea'][-1]:.1f}%，本季环比 "
            f"{geo_shares['korea'][-1] - geo_shares['korea'][-2]:+.1f}pp，是全公司最强的一格。"
            "<b>但占比的变化里混着两件事</b>：Ansys 自 Q2'25 起并入，"
            "把欧洲的分子一次抬高（欧洲占比在 Q3'25 单季跳升近 "
            f"{geo_shares['europe'][9] - geo_shares['europe'][8]:+.1f}pp），"
            "同时也稀释了所有其他地区的占比。所以跨 Q2'25 的占比变化不能当有机结构变化读；"
            f"中国的绝对金额同期从 US${disagg['china'][0]:,.0f}M 到 "
            f"US${disagg['china'][-1]:,.0f}M，四个季度的运行率基本停在 "
            "US$210–260M 之间，这才是不受并表影响的读法。"
        ),
        "src_extra": (
            "分地区收入逐季读自各期 10-Q / 10-K 分部附注的"
            "「Revenue related to operations in the United States and other geographic areas」表；"
            "占比为自算 D；会计季 Q4 为财年数减九个月数 D。"
            "全部十三季均为剔除 Software Integrity 后的持续经营口径。"
        ),
    }

    # ── assemble ─────────────────────────────────────────────────────────────
    settled_charts = [verdict_chart, delivery_chart, expectation_chart] + delivery_charts
    highlights = [revenue_chart, segment_chart, segment_margin_chart, wedge_chart,
                  dilution_chart, fy_split_chart]
    next_charts = [headroom_chart] + tracking_charts(next_kpi["quantified"])
    routine = [amort_chart, margin_wedge_chart, buyback_chart, backlog_chart, geography_chart]

    exhibits = resolve_exhibit_refs(
        number_exhibits(settled_charts + highlights + next_charts + routine)
    )
    grouped, cursor = [], 0
    for group in (settled_charts, highlights, next_charts, routine):
        grouped.append(exhibits[cursor:cursor + len(group)])
        cursor += len(group)
    settled_ex, highlight_ex, next_ex, routine_ex = grouped
    first_table = len(exhibits) + 2

    quarterly_rows, segment_rows, backlog_rows, geo_rows, long_rows = [], [], [], [], []
    for index, period in enumerate(periods):
        quarterly_rows.append([
            period,
            staging["fiscal_labels"][index],
            f"${revenue[index]:,.1f}M",
            f"{financials['revenue_yoy_pct'][index]:.1f}% D",
            f"${financials['gaap_operating_income_usd_m'][index]:,.1f}M",
            f"{financials['gaap_operating_margin_pct'][index]:.2f}% D",
            f"${financials['non_gaap_operating_income_usd_m'][index]:,.1f}M",
            f"{financials['non_gaap_operating_margin_pct'][index]:.2f}% D",
            f"${financials['gaap_eps_usd'][index]:.2f}",
            f"${financials['non_gaap_eps_usd'][index]:.2f}",
            f"{financials['diluted_shares_m'][index]:.3f}M",
        ])
        segment_rows.append([
            period,
            f"${da_revenue[index]:,.1f}M",
            f"${segments['design_automation_adj_op_income'][index]:,.1f}M",
            f"{da_margin[index]:.1f}% D",
            f"${ip_revenue[index]:,.1f}M",
            f"${segments['design_ip_adj_op_income'][index]:,.1f}M",
            f"{ip_margin[index]:.1f}% D",
            f"${amortization[index]:,.1f}M",
            f"${financials['stock_based_compensation_usd_m'][index]:,.1f}M",
            f"${financials['restructuring_usd_m'][index]:,.1f}M",
        ])
    for index, quarter in enumerate(backlog["quarters"]):
        backlog_rows.append([
            quarter,
            backlog["fiscal_labels"][index],
            f"US${backlog['backlog_usd_b'][index]:.1f}B",
            f"US${backlog['fsa_usd_b'][index]:.1f}B",
            f"{fsa_share[index]:.1f}% D",
            f"{backlog['next_12m_pct_of_ex_fsa'][index]:.0f}%",
            f"US${twelve_month[index]:.2f}B D",
            f"${capital['buyback_usd_m'][index]:,.1f}M" if capital["buyback_usd_m"][index] is not None else "—",
            f"${capital['capex_usd_m'][index]:,.1f}M" if capital["capex_usd_m"][index] is not None else "—",
            "是" if capital["derived"][index] else "否",
        ])
    for index, quarter in enumerate(disagg["quarters"]):
        geo_rows.append([
            quarter,
            f"${disagg['revenue_usd_m'][index]:,.1f}M",
            f"${disagg['united_states'][index]:,.1f}M",
            f"${disagg['europe'][index]:,.1f}M",
            f"${disagg['korea'][index]:,.1f}M",
            f"${disagg['china'][index]:,.1f}M",
            f"{geo_shares['china'][index]:.2f}% D",
            f"${disagg['other'][index]:,.1f}M",
            f"${disagg['time_based'][index]:,.1f}M",
            f"${disagg['upfront'][index]:,.1f}M",
            f"${disagg['maintenance_and_service'][index]:,.1f}M",
        ])
    for index, year in enumerate(long_labels):
        restated = long["restated_revenue_usd_m"][index]
        long_rows.append([
            year,
            f"${long['revenue_usd_m'][index]:,.1f}M",
            f"${restated:,.1f}M" if restated is not None else "—",
            f"${long['operating_income_usd_m'][index]:,.1f}M",
            f"{long_margin[index]:.2f}% D",
            f"${long_amortization[index]:,.1f}M D",
            f"{long_amort_share[index]:.2f}% D",
            f"{long_margin_ex[index]:.2f}% D",
            f"{long['diluted_shares_m'][index]:.3f}M",
            f"${long['diluted_eps_usd'][index]:.2f}",
            f"${long['share_repurchases_usd_m'][index]:,.0f}M",
            f"${long['operating_cash_flow_usd_m'][index]:,.1f}M",
            f"${long['capex_usd_m'][index]:,.1f}M",
        ])

    guide_rows = [
        ["收入", f"${record['guide_revenue_lo_usd_m'][current]:,.0f}–"
                 f"{record['guide_revenue_hi_usd_m'][current]:,.0f}M",
         f"${revenue[-1]:,.1f}M", "超出上限",
         f"${next_quarter['revenue_usd_m'][0]:,.0f}–{next_quarter['revenue_usd_m'][1]:,.0f}M",
         f"中值环比 {signed(pct_change(sum(next_quarter['revenue_usd_m']) / 2, revenue[-1]))} D"],
        # The release gives no quarterly margin. What it does give is a revenue
        # range and an expense range, and their midpoints imply one -- so the
        # implied figure is computed here and labelled D, rather than reading a
        # "midpoint" field that turned out to hold the *full-year* number.
        ["non-GAAP 费用",
         f"${record['guide_non_gaap_expenses_lo_usd_m'][current]:,.0f}–"
         f"{record['guide_non_gaap_expenses_hi_usd_m'][current]:,.0f}M",
         f"${actual_expense:,.1f}M D", "落在区间下沿",
         f"${next_quarter['non_gaap_expenses_usd_m'][0]:,.0f}–"
         f"{next_quarter['non_gaap_expenses_usd_m'][1]:,.0f}M",
         f"中值环比 {signed(pct_change(sum(next_quarter['non_gaap_expenses_usd_m']) / 2, actual_expense))} D"],
        ["non-GAAP 营业利润率", "指引未直接给出该季比率",
         f"{financials['non_gaap_operating_margin_pct'][-1]:.2f}% D", "—",
         f"隐含中点 {implied_next_margin:.2f}% D",
         f"较本季 {implied_next_margin - financials['non_gaap_operating_margin_pct'][-1]:+.1f}pp D"],
        ["non-GAAP EPS",
         f"${record['guide_non_gaap_eps_lo_usd'][current]:.2f}–"
         f"{record['guide_non_gaap_eps_hi_usd'][current]:.2f}",
         f"${financials['non_gaap_eps_usd'][-1]:.2f}", "超出上限",
         f"${next_quarter['non_gaap_eps_usd'][0]:.2f}–{next_quarter['non_gaap_eps_usd'][1]:.2f}",
         f"中值 ${sum(next_quarter['non_gaap_eps_usd']) / 2:.2f}"],
        ["GAAP EPS",
         f"${record['guide_gaap_eps_lo_usd'][current]:.2f}–"
         f"{record['guide_gaap_eps_hi_usd'][current]:.2f}",
         f"${financials['gaap_eps_usd'][-1]:.2f}", "远超上限（含出售收益）",
         f"${next_quarter['gaap_eps_usd'][0]:.2f}–{next_quarter['gaap_eps_usd'][1]:.2f}",
         "重组费用回归，口径不可与本季连读"],
        ["摊薄股数",
         f"{record['guide_shares_lo_m'][current]:.0f}–{record['guide_shares_hi_m'][current]:.0f}M",
         f"{financials['diluted_shares_m'][-1]:.3f}M", "区间内",
         f"{next_quarter['diluted_shares_m'][0]:.0f}–{next_quarter['diluted_shares_m'][1]:.0f}M",
         "持平"],
        ["non-GAAP 税率", "18.0%", "18.0%", "符合", "18.0%", "FY2026 起改用三年归一化税率"],
        ["FY2026 收入", "—", "—", "—",
         f"${full_year['revenue_usd_m'][0]:,.0f}–{full_year['revenue_usd_m'][1]:,.0f}M",
         f"含脚注载明的 Ansys ${footnote['expected_ansys_revenue_usd_m'][-1]:,.0f}M"],
        ["FY2026 non-GAAP EPS", "—", "—", "—",
         f"${full_year['non_gaap_eps_usd'][0]:.2f}–{full_year['non_gaap_eps_usd'][1]:.2f}",
         "较上一次指引中值上调 $0.31 D"],
        ["FY2026 自由现金流", "—", "—", "—",
         f"约 ${full_year['free_cash_flow_usd_m']:,.0f}M",
         f"经营现金流约 ${full_year['operating_cash_flow_usd_m']:,.0f}M、"
         f"资本开支约 ${full_year['capex_usd_m']:,.0f}M"],
    ]

    tables = [
        {
            "n": first_table,
            "title": "本季兑现与下季／全年指引",
            "headers": ["指标", "本季原指引", "本季实际", "兑现", "新指引", "变化 / 备注"],
            "rows": guide_rows,
        },
        threshold_table(first_table + 1, "下季阈值与当前值（原单位）",
                        next_kpi["quantified"], "current", "当前值"),
        {
            "n": first_table + 2,
            "title": "八季度收入、利润率与每股口径",
            "headers": ["期间", "公司口径", "收入", "收入 YoY", "GAAP 营业利润",
                        "GAAP 营业利润率", "调整后营业利润", "调整后营业利润率",
                        "GAAP EPS", "non-GAAP EPS", "摊薄股数"],
            "rows": quarterly_rows,
        },
        {
            "n": first_table + 3,
            "title": "八季度分部与非 GAAP 调整项",
            "headers": ["期间", "Design Automation 收入", "调整后营业利润", "调整后利润率",
                        "Design IP 收入", "调整后营业利润", "调整后利润率",
                        "收购摊销", "股权激励", "重组费用"],
            "rows": segment_rows,
        },
        {
            "n": first_table + 4,
            "title": "十五季度 backlog 与资本配置",
            "headers": ["期间", "公司口径", "backlog", "其中 FSA", "FSA 占比",
                        "未来 12 个月可确认比例", "可确认额", "回购", "资本开支", "季度值为差分"],
            "rows": backlog_rows,
        },
        {
            "n": first_table + 5,
            "title": "十三季度分地区与收入类型（持续经营口径）",
            "headers": ["期间", "总收入", "United States", "Europe", "Korea", "China",
                        "China 占比", "Other", "Time-based", "Upfront", "Maintenance & service"],
            "rows": geo_rows,
        },
        {
            "n": first_table + 6,
            "title": "十年年度记录（各年取该年 10-K 首次印出的数）",
            "headers": ["财年", "收入", "后被重述为", "GAAP 营业利润", "GAAP 营业利润率",
                        "收购摊销", "摊销占收入", "加回摊销后利润率", "摊薄股数", "GAAP EPS",
                        "回购", "经营现金流", "资本开支"],
            "rows": long_rows,
        },
        {**delivery_table, "n": first_table + 7},
        ai_capex_cycle_table(first_table + 8),
    ]

    return {
        "schema_version": "quarterly-dashboard/snps-v1",
        "page": {"slug": "snps", "language": "zh-CN"},
        "company": {
            "ticker": "SNPS",
            "name": "Synopsys",
            "group": "semiconductor_ai",
            "accounting_standard": "US GAAP",
        },
        "latest": {
            "disclosed_period_label": "Q2 2026",
            "full_financial_period_label": "Q2 2026",
            "period_end": "2026-07-31",
            "release_date": "2026-08-26",
            "analysis_date": "2026-08-27",
            "audit_status": "unaudited",
            "status": "history_ready",
        },
        "tracker": "Watchlist Quarterly Tracker · SNPS",
        "title": "Synopsys (SNPS)：Q2 2026 季报仪表盘",
        "subtitle": (
            "截至 2026-07-31 · 发布 2026-08-26 · US GAAP · 未审计 · "
            "10 月制财年，本站按自然年季度标注：本页 Q2 2026 即公司所称 FY2026 Q3"
        ),
        "headline": (
            f"收入 US${revenue[-1]:,.0f}M、同比 {signed(financials['revenue_yoy_pct'][-1])}，"
            f"收入、non-GAAP 费用、non-GAAP EPS 与摊薄股数四条指引全部优于中值，"
            f"公司同时上调 FY2026 的收入、利润率、EPS 与现金流；"
            f"但同一季里，收购摊销吃掉收入的 {amortization_share[-1]:.1f}%、"
            f"股数同比多出 {pct_change(financials['diluted_shares_m'][-1], financials['diluted_shares_m'][-5]):.1f}%，"
            f"于是 non-GAAP 净利同比 "
            f"{signed(pct_change(financials['non_gaap_net_income_usd_m'][-1], financials['non_gaap_net_income_usd_m'][-5]))} "
            f"落到每股只剩 "
            f"{signed(pct_change(financials['non_gaap_eps_usd'][-1], financials['non_gaap_eps_usd'][-5]))}。"
        ),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>记录</span><b>收入是预测，EPS 是底线</b>'
            f'<p>24 季指引记录里，收入落在自己区间内 13 次，'
            f'non-GAAP EPS 却 20 次穿出上限。同一张表，两种性质。</p></article>'
            '<article><span>亮点</span><b>Design IP 重新转正</b>'
            f'<p>US${ip_revenue[-1]:,.0f}M、同比 '
            f'{signed(pct_change(ip_revenue[-1], ip_revenue[-5]))}；'
            f'分部利润率 {ip_margin[-1]:.1f}%，同比 {ip_margin[-1] - ip_margin[-5]:+.1f}pp。</p></article>'
            '<article><span>代价</span><b>摊销与股数同时变重</b>'
            f'<p>收购摊销占收入 {amortization_share[-1]:.1f}%，十年最高；'
            f'股数同比 +{pct_change(financials["diluted_shares_m"][-1], financials["diluted_shares_m"][-5]):.1f}%，'
            f'回购连着两个财年为零。</p></article>'
            '</div>'
        ),
        "source": (
            'Source: <a href="https://www.sec.gov/Archives/edgar/data/883241/'
            '000119312526368620/d157153dex991.htm" rel="noopener">Synopsys FY2026 Q3 '
            '业绩新闻稿（8-K EX-99.1）</a>与截至 2026-07-31 的 10-Q。'
        ),
        "source_url": (
            "https://www.sec.gov/Archives/edgar/data/883241/"
            "000119312526368620/d157153dex991.htm"
        ),
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {
                "id": "settled",
                "title": "一、上季跟踪指标兑现了吗",
                "description": (
                    "先结清上季设下的阈值，再看新数字。公司每季在业绩新闻稿里给出下一季的"
                    "收入、GAAP 与 non-GAAP 费用、非经营项、税率、摊薄股数与两条 EPS —— "
                    "本站唯一一家把每股收益的每一个输入都指引出来的公司，"
                    "所以「有没有做到」在这里有 24 季的完整答案，且超额可以被拆开而无需任何估计。"
                ),
                "exhibits": settled_ex,
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": (
                    "两个分部各自的收入与利润率、GAAP 与 non-GAAP 之间那道由收购摊销撑开的裂口、"
                    "股数对每股口径的吞噬，以及公司自己在指引脚注里给出的并购与原生拆分。"
                ),
                "exhibits": highlight_ex,
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": "当前值离下季阈值还有多远，统一用「距阈值余量」口径；不接入的三条也写在这里。",
                "exhibits": next_ex,
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": (
                    "SNPS 专属的常规序列：十年收购摊销强度与它撑开的利润率裂口、"
                    "十年回购与股数、十五季 backlog 与它可确认的那一半，以及十三季地域结构。"
                ),
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "本页所有季度按自然年标注。Synopsys 财年 10 月底结束，故本页的 Q2 2026 是截至 2026-07-31 的季度，公司自己称之为 FY2026 Q3；映射规则为公司 FY 的 Q1→上一自然年 Q4、Q2→Q1、Q3→Q2、Q4→Q3。不统一成一种约定，跨公司的资本开支对照表就会把不同的三个月放在一起比较。",
            f"第一节的指引兑现组图（Exhibit {settled_ex[3]['n']}–{settled_ex[-1]['n']}）用的是同一批业绩 8-K：每份 EX-99.1 新闻稿的「Financial Targets」表同时给出下一季的收入区间、GAAP 与 non-GAAP 费用区间、非 GAAP 非经营项区间、非 GAAP 税率、摊薄股数区间与两条 EPS 区间；实际值取自随后一季 8-K 的合并损益表与分部调节表。",
            f"Exhibit {settled_ex[5]['n']} 的两条腿是恒等式而非估计：指引收入中值减指引费用中值隐含一个公司从不单独印出的非 GAAP 营业利润，实际值与它的差恰好等于收入腿加费用腿。实际非 GAAP 费用本身也不是估计，它等于实际收入减去每份新闻稿都印的「total adjusted segment operating income」。",
            "把五个指引中值代回「（收入 − 费用 + 非经营项）×（1 − 税率）÷ 股数」，能复现公司自己印出来的 non-GAAP EPS 中值：24 季里 15 季误差在 US$0.02 以内、全部 24 季在 US$0.06 以内，残差来自公司把区间端点四舍五入到分与把股数区间取整到百万股。这是本页把「指引隐含营业利润」当作公司自己的数来用的依据。",
            "公司在 2024-05-05 签约出售 Software Integrity 业务，并在截至 2024-04-30 的当季把它整体移入终止经营、同时从分部结果中移除。因此 Q1 2024 这一季的指引与实际不在同一口径上：指引含该业务、实际不含。指引记录的水平图在该季打断点，本页不改写任何一端；该季 10-Q 终止经营附注所载 Software Integrity 三个月收入 US$126.4M 加回后（US$1,581M），实际值落回指引区间内、靠近上沿。同一季的 non-GAAP EPS 指引与实际同样跨口径，但公司未披露该业务的 non-GAAP 贡献，因此本页只对收入做这一步还原，不对 EPS 做。",
            "十年年度序列一律取该年 10-K 首次印出的数，即公司当年自己报出的口径。FY2022 与 FY2023 后来在 FY2024 10-K 中因同一笔剥离被重述（收入分别降 US$466M 与 US$525M），核对表把重述后的收入并列，图上不做追溯改写。",
            "会计季 Q4 没有 10-Q，其分部、分地区与现金流量值均为财年数减去九个月数，两端都是申报值；核对表逐行标注哪些季是差分得来的。",
            "backlog 相关的三个数各有各的口径：总额与不可撤销 FSA 承诺是公司披露值（精度 US$0.1B），「未来 12 个月内可确认的比例」在申报原文里是对扣除 FSA 之后的 backlog 说的，因此本页的可确认额 =（总额 − FSA）× 该比例，为自算值。",
            "本页不发布剔除 Ansys 之后的季度 EDA 收入或其增速。公司从未在任何申报文件中单列 Ansys 的实际季度收入，只在 FY2026 收入指引的脚注里给出预期口径，因此该拆分在公开申报文件里无法复算；能复算的那一部分（年度指引层面的并购与原生拆分）已单独成图。",
            "本页只发布公司披露值、可复算的简单派生值，以及明确标注的市场预期；D 标记代表 Derived / 自算。",
            "市场预期一律标注为「市场预期」并给出取数时点，不写卖方机构名，也不发布评级、目标价或估值。",
            "本页已知未接入：Ansys 的季度实际收入与其渠道会计的单季金额（公司拒绝按季披露）、EDA 软件与硬件的拆分（公司未披露）、Factory 2 与 agentic 产品的任何量化口径（公司尚未给出）、客户集中度，以及 2026 年 9 月 30 日投资者日的内容（本页数据截至 2026-08-26 的申报）。",
            "业绩电话会文字稿仅链接官方 IR 与 SEC 托管版本，公开仓不复制原件或逐字内容。",
        ],
        "footer": "SNPS quarterly results · 数据来自 Synopsys 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "snps.js"), payload, "snps")
    shell_dir = ROOT / "snps"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("SNPS", "snps"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(
        f"SNPS page: {charts} charts in {len(payload['sections'])} sections "
        f"+ {len(payload['tables'])} audit tables"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
