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
count, and then GAAP and non-GAAP EPS themselves.  It means the beat can be
split into its parts with no estimate anywhere: guided revenue minus guided
expenses is an operating income the company never prints, and the distance
from what it reported is exactly a revenue leg plus an expense leg.

The record reaches back to 2016Q1 and produces a shape no single quarter shows:
revenue lands *inside* its guided range more often than not, non-GAAP EPS lands
*above* it far more often.  Every count and every "only" in the sentences about
that record is recounted from it on each build.

Rolling a quarter edits `series/snps.json` and nothing else. The blocks that
describe one quarter -- the follow-up closure and verdicts, the next-quarter
thresholds, the guidance, the market expectation, the 10-Q's Ansys percentages
and `quarter_story` -- carry the quarter they were written for and are read
through `board.stamped_block`; story sentences name series numbers as
placeholders (`board.fill_story`) and list under `requires` the facts they
rest on, which the builder recomputes.

Published numbers are company-reported or transparent arithmetic.  Market
expectations are labelled as such, with no broker attribution.
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
    delivery_band,
    fill_story,
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


STAGING_PATH = ROOT / "series" / "snps.json"
DATA_DIR = ROOT / "data"

# One tick per year keeps the ten-year and forty-quarter axes readable.
LONG_STEP = 4
# Fixed history: Ansys closed on 2025-07-17, inside the fiscal quarter this site
# labels Q2 2025, so that quarter carries two weeks of it and the next is the
# first full one.
ANSYS_CLOSE = "Q2 2025"
ANSYS_CLOSE_YEAR = "FY2025"
AUDIT_WORDS = {"unaudited": "未审计", "audited": "已审计"}
VERDICT_TITLE_WORDS = {"指标设计失效": "被判为指标设计失效"}
CLOSURE_WORDS = ["完全验证", "部分验证", "仍未披露", "被证伪"]
FISCAL_YTD_WORDS = {1: "第一季", 2: "前两季", 3: "前三季", 4: "全年"}


def compact_period(period: str) -> str:
    """``'Q2 2026'`` → ``'Q2'26'``."""
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


def fiscal_words(label: str) -> str:
    """``'FY2026Q3'`` → ``'FY2026 Q3'``."""
    return f"{label[:6]} {label[6:]}"


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def rounded(values: list[float | None], digits: int = 6) -> list[float | None]:
    return [None if value is None else round(value, digits) for value in values]


def mid(low: list[float], high: list[float]) -> list[float]:
    return [(a + b) / 2 for a, b in zip(low, high)]


def middle(value) -> float:
    """A guided figure is a range ``[lo, hi]`` or a single approximate number."""
    return sum(value) / 2 if isinstance(value, list) else value


def times_words(ratio: float) -> str:
    """``3.03`` → 「三倍」, ``2.5`` → 「两倍多」, ``2.8`` → 「近三倍」."""
    whole = int(ratio)
    rest = ratio - whole
    if rest >= 0.75:
        return f"近{cn_count(whole + 1)}倍"
    return f"{cn_count(whole)}倍" + ("多" if rest >= 0.25 else "")


def joined(items: list[str]) -> str:
    """「收入、non-GAAP 费用、non-GAAP EPS 与摊薄股数」: 、 between, 与 before the last,
    with the space Chinese type puts between a Latin word and a Chinese one."""
    if len(items) == 1:
        return items[0]
    last, before = items[-1], items[-2]
    left = " " if before[-1].isascii() and before[-1].isalnum() else ""
    right = " " if last[0].isascii() and last[0].isalnum() else ""
    return "、".join(items[:-1]) + f"{left}与{right}" + last


def num(value: float, digits: int = 1) -> str:
    """A signed number in prose, with a typographic minus: ``-0.6`` → ``'−0.6'``."""
    return f"{value:+.{digits}f}".replace("-", "−")


def month_words(date: str) -> str:
    """``'2025-05-28'`` → 「5 月」."""
    return f"{int(date[5:7])} 月"


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


def require(story: dict | None, facts: dict[str, bool], block: str) -> None:
    """A story block lists the facts its sentences rest on; the data must still say them."""
    if not story:
        return
    for name in story.get("requires", []):
        if name not in facts:
            raise KeyError(f"series block `{block}` requires unknown fact {name!r}")
        if not facts[name]:
            raise ValueError(f"series block `{block}` rests on {name!r}, which the data no "
                             "longer supports: rewrite the block for this quarter")


def release_sources(staging: dict, fiscal: str, period_end: str) -> tuple[dict, dict | None]:
    """The quarter's own earnings release (required) and its 10-Q (when filed)."""
    release = next((item for item in staging["sources"]
                    if item["label"].startswith(f"Synopsys {fiscal} 业绩新闻稿")), None)
    if release is None:
        raise ValueError(f"series `sources` has no entry for the {fiscal} earnings release: "
                         "add it with the roll")
    filing = next((item for item in staging["sources"]
                   if f"截至 {period_end} 的 10-Q" in item["label"]), None)
    return release, filing


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
def guidance_delivery_charts(staging: dict, ip_turned: bool) -> tuple[list[dict], dict, dict]:
    """The guided-versus-reported record, and what the beats are made of.

    Synopsys guides revenue, non-GAAP expenses, non-GAAP other income, the
    non-GAAP tax rate and the fully diluted share count, and then guides the EPS
    those five imply.  Running the five midpoints through

        (revenue − expenses + other income) × (1 − tax rate) ÷ shares

    reproduces the company's own printed EPS midpoint closely in the recent
    quarters and more loosely in the early ones (the counts are printed in the
    notes, recomputed).  So the guided operating income below -- guided revenue
    minus guided expenses -- is the company's own number in everything but name,
    and the distance from what it reported splits exactly two ways:

        actual − implied = (Ra − Rg)  −  (Ea − Eg)

    where the actual expense leg is itself reported revenue minus the reported
    "total adjusted segment operating income" every release prints.
    """
    record = staging["quarterly_guidance_history"]
    quarters = record["quarters"]
    labels = [compact_period(quarter) for quarter in quarters]
    break_at = record["basis_break_at"]
    addback = record["basis_break_addback_usd_m"]
    close = quarters.index(ANSYS_CLOSE)

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
    eps_mid = mid(eps_lo, eps_hi)

    finished = [index for index, value in enumerate(revenue_actual) if value is not None]
    n = len(finished)
    revenue_dev = {i: pct_change(revenue_actual[i], revenue_mid[i]) for i in finished}
    eps_dev = {i: pct_change(eps_actual[i], eps_mid[i]) for i in finished}

    # ── revenue ──────────────────────────────────────────────────────────────
    inside = sum(1 for index in finished
                 if revenue_lo[index] <= revenue_actual[index] <= revenue_hi[index])
    eps_above = sum(1 for index in finished if eps_actual[index] > eps_hi[index])
    below = {i: pct_change(revenue_actual[i], revenue_lo[i]) for i in finished
             if revenue_actual[i] < revenue_lo[i]}
    restored = revenue_actual[break_at] + addback
    restored_high = revenue_lo[break_at] + (revenue_hi[break_at] - revenue_lo[break_at]) * 2 / 3
    deepest = min(below, key=below.get) if below else None
    revenue_band = delivery_band(
        "EX_REV_RANGE", "收入", labels, revenue_lo, revenue_hi, revenue_actual,
        fmt="f0c", ylab="US$M", unit="US$M", venue="业绩发布",
        break_at=break_at, break_label=BASIS_BREAK_LABEL,
        src_extra=SOURCE_8K,
        extra_note=(
            f"<b>先读这张的中间一栏</b>：{n} 个已完结季里有 {inside} 季"
            "落在自己给的区间<b>内</b>，而不是穿出去。"
            + ("这在本站是少见的形状 —— 一家把收入指引当预测用、而且大部分时候预测对了的公司，"
               "背后是以 backlog 与按期确认收入为主的模型。" if inside * 2 > n else "")
            + BASIS_BREAK_NOTE
            + f"当季实际 US${revenue_actual[break_at]:,.0f}M 对指引 "
            f"US${revenue_lo[break_at]:,.0f}–{revenue_hi[break_at]:,.0f}M，"
            + ("看上去是本记录里最大的一次跌破，" if deepest == break_at else "看上去是一次跌破，")
            + ("但把被移走的那块加回去就落回区间内、而且靠近上沿："
               if revenue_lo[break_at] <= restored <= revenue_hi[break_at] and restored >= restored_high else
               "但把被移走的那块加回去就落回区间内：" if revenue_lo[break_at] <= restored <= revenue_hi[break_at]
               else "把被移走的那块加回去：")
            + "该季 10-Q 的终止经营附注载明 Software Integrity 三个月收入 "
            f"US${addback:,.1f}M，"
            f"{revenue_actual[break_at]:,.0f} + {addback:,.0f} = "
            f"<b>US${restored:,.0f}M</b>，"
            "公司自己在当天的新闻稿里也把这一季称作「at the high-end of guidance」。"
            "本页保留这根跌破的柱子并在这里说明原因，而不是把它悄悄改掉。"
        ),
    )
    within_one = sum(1 for i in finished if abs(revenue_dev[i]) <= 1)
    mean_abs = statistics.fmean(abs(revenue_dev[i]) for i in finished)
    early, late = finished[:n // 2], finished[n // 2:]
    widened = (statistics.fmean(abs(revenue_dev[i]) for i in late)
               > statistics.fmean(abs(revenue_dev[i]) for i in early) * 1.5)
    clear_misses = [i for i in finished if revenue_dev[i] <= -1]
    miss_words = ""
    if clear_misses == [break_at, close]:
        miss_words = (
            "两根明显的负柱各有各的原因，不是同一类事："
            "左边那根是上一张说的终止经营口径变更；"
            f"右边那根 {labels[close]} 是真的没做到，公司 CEO 在当天的新闻稿里写的是"
            "「our IP business underperformed expectations」"
            + ("，而 Design IP 正是本季重新转正的那条线（见 Exhibit {EX_SEG_REV}）。" if ip_turned else "。")
        )
    elif clear_misses:
        miss_words = ("低于中值 1% 以上的季度有 "
                      + "、".join(labels[i] for i in clear_misses) + "。")
    revenue_dev_chart = midpoint_deviation(
        "EX_REV_DEV", "收入", quarters, revenue_lo, revenue_hi, revenue_actual,
        mode="pct", window=n, label=compact_period, bar_labels=False,
        src_extra=SOURCE_8K + "偏离为实际收入除以指引中值的自算值。",
        extra_note=(
            f"换成与量级无关的口径看同一件事：{n} 季里 {within_one} 季的预测误差在 ±1% 以内、"
            f"平均绝对偏离 {mean_abs:.1f}% —— "
            f"收入在这 {n} 季里从 US${revenue_actual[finished[0]] / 1000:.2f}B 长到 "
            f"US${revenue_actual[finished[-1]] / 1000:.2f}B，"
            + ("误差却没有跟着放大。" if not widened else "误差也跟着放大了。")
            + miss_words
        ),
    )

    # ── the two legs of the operating-income beat ────────────────────────────
    # The expense leg is revenue minus non-GAAP operating income, and Synopsys's
    # reconciliation did not carry an operating-income line until the release of
    # 2019-02-20 -- before that it bridges GAAP net income straight to non-GAAP
    # net income. So this decomposition starts later than the bands above it,
    # and the title says which quarters it covers rather than implying the gap
    # is a shorter record.
    operating = record["actual_non_gaap_operating_income_usd_m"]
    decomposable = [index for index in finished if operating[index] is not None]
    revenue_leg, expense_leg, leg_labels = [], [], []
    for index in decomposable:
        actual_expense = revenue_actual[index] - operating[index]
        revenue_leg.append(revenue_actual[index] - revenue_mid[index])
        expense_leg.append(expense_mid[index] - actual_expense)
        leg_labels.append(compact_period(quarters[index]))
    totals = [a + b for a, b in zip(revenue_leg, expense_leg)]
    misses = [index for index, value in enumerate(totals) if value < 0]
    expense_positive = sum(1 for value in expense_leg if value > 0)
    latest_share = revenue_leg[-1] / totals[-1] * 100
    revenue_led = sum(1 for a, b in zip(revenue_leg, expense_leg) if abs(a) > abs(b))
    both_negative = [position for position, (a, b) in enumerate(zip(revenue_leg, expense_leg))
                     if a < 0 and b < 0]
    at_break = decomposable.index(break_at) if break_at in decomposable else None
    clean = revenue_leg[-1] > 0 and expense_leg[-1] > 0
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
            f"<b>读数：</b>本季{'超额' if totals[-1] >= 0 else '差额'} US${abs(totals[-1]):,.0f}M 里"
            f"收入腿占 {latest_share:.0f}%、费用腿占 {100 - latest_share:.0f}%"
            + ("，是一次干净的经营超额，不靠税率也不靠股数。" if clean else "。")
            + f"整段记录里 {len(totals)} 季有 {revenue_led} 季深蓝的收入腿大于金色的费用腿"
            + (" —— 换句话说，<b>这家公司的意外多半来自卖了多少，不来自省了多少</b>。"
               if revenue_led * 10 >= len(totals) * 7 else "。")
            + ("两条腿同时为负的只有 " + "、".join(
                f"{leg_labels[p]}（{num(revenue_leg[p])} / {num(expense_leg[p])}）" for p in both_negative)
               + "；" if both_negative else "没有一季两条腿同时为负；")
            + (f"口径断点那一季是收入腿 {num(revenue_leg[at_break], 0)}、费用腿 {num(expense_leg[at_break], 0)} —— "
               "被移走的业务连同它的费用一起从实际值里消失了，原因见 Exhibit {EX_REV_RANGE}。"
               if at_break is not None else "")
        ),
        "src_extra": SOURCE_8K + "两条腿均为自算，指引原值与实际原值见核对表。",
    }

    # ── non-GAAP EPS ─────────────────────────────────────────────────────────
    widths = [round(hi - lo, 2) for lo, hi in zip(eps_lo, eps_hi)]
    common = max(set(widths), key=widths.count)
    eps_band = delivery_band(
        "EX_EPS_RANGE", "non-GAAP EPS", labels, eps_lo, eps_hi, eps_actual,
        fmt="usd2", ylab="US$/股", unit="US$", venue="业绩发布",
        break_at=break_at, break_label=BASIS_BREAK_LABEL,
        src_extra=SOURCE_8K,
        extra_note=(
            "<b>把这张和收入那张并排读，是本页存在的理由。</b>"
            "同一份新闻稿、同一个季度、同一个十二周的预测窗口，"
            f"收入指引 {n} 季里 {inside} 季被<b>命中</b>，EPS 指引却有 {eps_above} 季被<b>穿透</b>。"
            + ("一个是预测，另一个是底线，而公司把它们印在同一张表上。" if eps_above > inside else "")
            + f"区间宽度在 US${min(widths):.2f}–{max(widths):.2f} 之间，{len(widths)} 季里 "
            f"{widths.count(common)} 季是 US${common:.2f}，本身就说明公司认为自己算得很准。"
        ),
    )
    eps_negative = [i for i in finished if eps_dev[i] < 0]
    others = [i for i in eps_negative if i not in (break_at, close)]
    same_two = {break_at, close} <= set(eps_negative)
    if not eps_negative:
        negative_words = "没有一季为负。"
    elif same_two and not others:
        negative_words = "两次为负仍是同样的两季：一次是口径变更，一次是 Design IP 真的没做到。"
    elif same_two:
        negative_words = (
            f"{cn_count(len(eps_negative))}次为负："
            + "、".join(f"{labels[i]} 差 {abs(eps_dev[i]):.1f}%" for i in others)
            + "，另两次仍是收入那张的同样两季 —— 一次是口径变更，一次是 Design IP 真的没做到。"
        )
    else:
        negative_words = ("为负的季度是 " + "、".join(
            f"{labels[i]}（{eps_dev[i]:+.1f}%）" for i in eps_negative) + "。")
    eps_dev_chart = midpoint_deviation(
        "EX_EPS_DEV", "non-GAAP EPS", quarters, eps_lo, eps_hi, eps_actual,
        mode="pct", window=n, label=compact_period, bar_labels=False,
        src_extra=SOURCE_8K + "偏离为实际 non-GAAP EPS 除以指引中值的自算值。",
        extra_note=(
            "与收入那张（Exhibit {EX_REV_DEV}）的柱高不在一个量级上："
            f"收入偏离的中位数是 {statistics.median(revenue_dev.values()):+.1f}%，"
            f"EPS 偏离的中位数是 {statistics.median(eps_dev.values()):+.1f}%，"
            f"{n} 季里有 {sum(1 for v in eps_dev.values() if v >= 4)} 季在 +4% 以上。"
            "同样的收入落点能产出这么大的 EPS 超额，说明超额来自收入以下的各行 —— "
            "费用、非经营项与税率，其中费用那一腿见 Exhibit {EX_OI_LEGS}。"
            + negative_words
        ),
    )

    # ── the guided share count ───────────────────────────────────────────────
    share_inside = sum(1 for index in finished
                       if shares_lo[index] <= shares_actual[index] <= shares_hi[index])
    share_below = [compact_period(quarters[index]) for index in finished
                   if shares_actual[index] < shares_lo[index]]
    share_above = [index for index in finished if shares_actual[index] > shares_hi[index]]
    shares_band = delivery_band(
        "EX_SHARES_RANGE", "摊薄股数", labels, shares_lo, shares_hi, shares_actual,
        fmt="f0c", ylab="百万股", unit="百万股", venue="业绩发布",
        src_extra=SOURCE_8K + "实际摊薄股数来自各季 8-K 合并损益表的每股计算股数。",
        extra_note=(
            "<b>本站少有的把自己的股数也一并指引的公司，而且是唯一按季给出股数区间的</b>，"
            f"{n} 季里 {share_inside} 季落在区间内、{len(share_below)} 季低于下限。"
            + ("低于下限不是失误而是好事 —— 那几季（" + "、".join(share_below)
               + "）公司回购买回的股比自己预告的还多，图上金色区间下方的菱形就是这个意思。"
               if share_below else "")
            + f"这条线本来是全页最平的一条，直到 2025 年 7 月 Ansys 交割：台阶从 "
            f"{shares_actual[close - 1]:.0f} 百万股一次抬到 {shares_actual[close + 1]:.0f} 百万股。"
            + (f"<b>唯一一次冲出上限的 {labels[close]} 正是交割当季</b>："
               f"公司 {month_words(record['guided_in_release'][close])}给的区间是 "
               f"{shares_lo[close]:.0f}–{shares_hi[close]:.0f}，实际报出 {shares_actual[close]:.1f}，"
               "多出来的是并购当季新发的股，指引给的时候还不知道会落在哪一天。"
               if share_above == [close] else "")
            + "股数是 EPS 的分母，所以这张图必须和上面两张 EPS 图一起看："
            "收入与利润的超额是分子的事，这里是分母的事。"
        ),
    )

    charts = [revenue_band, revenue_dev_chart, legs_chart, eps_band, eps_dev_chart, shares_band]

    table = {
        "title": f"指引兑现全表（{len(quarters)} 季）：五项指引、实际值与超额的两条腿",
        "headers": ["期间", "公司口径", "收入指引", "实际收入", "较中值",
                    "non-GAAP 费用指引", "实际费用 D", "隐含营业利润 D", "实际营业利润",
                    "收入腿 D", "费用腿 D",
                    "non-GAAP EPS 指引", "实际 EPS", "股数指引", "实际股数"],
        "rows": [],
    }
    leg_at = {index: position for position, index in enumerate(decomposable)}
    for index, quarter in enumerate(quarters):
        done = revenue_actual[index] is not None
        # An early quarter can be reported and still have no operating-income
        # line, so "reported" and "decomposable" are two different questions.
        split = operating[index] is not None
        position = leg_at.get(index)
        implied = revenue_mid[index] - expense_mid[index]
        actual_expense = (revenue_actual[index] - operating[index]) if split else None
        table["rows"].append([
            quarter,
            record["fiscal_labels"][index],
            f"${revenue_lo[index]:,.0f}–{revenue_hi[index]:,.0f}M",
            f"${revenue_actual[index]:,.1f}M" if done else "—",
            f"{pct_change(revenue_actual[index], revenue_mid[index]):+.2f}% D" if done else "—",
            f"${record['guide_non_gaap_expenses_lo_usd_m'][index]:,.0f}–"
            f"{record['guide_non_gaap_expenses_hi_usd_m'][index]:,.0f}M",
            f"${actual_expense:,.1f}M D" if split else "—",
            f"${implied:,.1f}M D",
            (f"${operating[index]:,.1f}M" if split else "—"),
            f"{revenue_leg[position]:+,.1f} D" if position is not None else "—",
            f"{expense_leg[position]:+,.1f} D" if position is not None else "—",
            f"${eps_lo[index]:.2f}–{eps_hi[index]:.2f}",
            f"${eps_actual[index]:.2f}" if done else "—",
            f"{shares_lo[index]:.0f}–{shares_hi[index]:.0f}M",
            f"{shares_actual[index]:.3f}M" if done else "—",
        ])
    facts = {"finished": n, "inside": inside, "eps_above": eps_above}
    return charts, table, facts


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    ip = staging["segments_usd_m"]["design_ip_revenue"]
    return [f"Revenue ${staging['financials']['revenue_usd_m'][-1] / 1000:.2f}B",
            f"Design IP {(ip[-1] / ip[-5] - 1) * 100:+.1f}%",
            f"Non-GAAP OpM {staging['financials']['non_gaap_operating_margin_pct'][-1]:.1f}%"]


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    period = periods[-1]
    labels = [compact_period(p) for p in periods]
    fiscal = fiscal_words(staging["fiscal_labels"][-1])
    period_end = staging["period_ends"][-1]
    latest = latest_block(staging, period=period, period_end=period_end)
    release_date = latest["release_date"]
    release, filing = release_sources(staging, fiscal, period_end)
    financials = staging["financials"]
    segments = staging["segments_usd_m"]
    backlog = staging["backlog"]
    disagg = staging["disaggregation_usd_m"]
    capital = staging["capital_allocation_usd_m"]
    long = staging["long_history"]
    record = staging["quarterly_guidance_history"]

    guidance = stamped_block(staging, "guidance", period)
    consensus = stamped_block(staging, "market_expectation", period)
    verdicts = stamped_block(staging, "tracked_metric_verdicts", period)
    closure = stamped_block(staging, "followup_closure", period)
    next_kpi = stamped_block(staging, "next_kpi", period)
    ansys_split = stamped_block(staging, "ansys_split_note", period)
    story = stamped_block(staging, "quarter_story", period)
    story_or = story or {}

    revenue = financials["revenue_usd_m"]
    da_revenue = segments["design_automation_revenue"]
    ip_revenue = segments["design_ip_revenue"]
    da_margin = [oi / rev * 100 for oi, rev
                 in zip(segments["design_automation_adj_op_income"], da_revenue)]
    ip_margin = [oi / rev * 100 for oi, rev
                 in zip(segments["design_ip_adj_op_income"], ip_revenue)]
    amortization = financials["acquisition_amortization_usd_m"]
    amortization_share = [a / rev * 100 for a, rev in zip(amortization, revenue)]
    # Design IP's growth needs a year-ago base for the first four window
    # quarters too; those come from each release's prior-year column.
    ip_base_outside = segments.get("design_ip_revenue_prior_year_outside_window", {})
    ip_yoy = []
    for index, label in enumerate(periods):
        base = ip_revenue[index - 4] if index >= 4 else ip_base_outside.get(label)
        ip_yoy.append(None if base is None else pct_change(ip_revenue[index], base))
    ip_streak = 0
    while (ip_streak + 2 <= len(ip_yoy) and ip_yoy[-2 - ip_streak] is not None
           and ip_yoy[-2 - ip_streak] < 0):
        ip_streak += 1
    ip_turned = ip_yoy[-1] is not None and ip_yoy[-1] > 0 and ip_streak > 0

    record_index = record["quarters"].index(period)

    next_quarter = guidance["next_quarter"] if guidance else None
    full = guidance["full_year"] if guidance else None
    full_year = full["current"] if full else None
    previous_year = full.get("previous") if full else None
    footnote = guidance.get("full_year_revenue_footnote") if guidance else None
    if footnote is not None and footnote["releases"][-1] != release_date:
        raise ValueError("series block `guidance.full_year_revenue_footnote` ends on the "
                         f"{footnote['releases'][-1]} release, not {release_date}: add this quarter's")
    implied_next_margin = None
    if next_quarter:
        implied_next_margin = (
            (sum(next_quarter["revenue_usd_m"]) / 2 - sum(next_quarter["non_gaap_expenses_usd_m"]) / 2)
            / (sum(next_quarter["revenue_usd_m"]) / 2) * 100)

    # ── section one ──────────────────────────────────────────────────────────
    delivery_charts, delivery_table, record_facts = guidance_delivery_charts(staging, ip_turned)
    current = record_index
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
    guided_other = (record["guide_non_gaap_other_income_lo_usd_m"][current]
                    + record["guide_non_gaap_other_income_hi_usd_m"][current]) / 2
    guided_tax = record["guide_non_gaap_tax_rate_pct"][current]
    actual_expense = revenue[-1] - financials["non_gaap_operating_income_usd_m"][-1]
    implied_oi = guided_revenue - guided_expense
    actual_tax = story_or.get("non_gaap_tax_rate_actual_pct")

    fy_split = footnote is not None and len(footnote["releases"]) >= 2
    values = {"release_date": release_date,
              "record_quarters": cn_count(record_facts["finished"]),
              "prev_restructuring": f"US${financials['restructuring_usd_m'][-2]:,.1f}M"}

    def told(key: str, default: str = "") -> str:
        text = story_or.get(key)
        return fill_story(text, values) if text else default

    verdict_chart = None
    if verdicts is not None:
        closure_words = ""
        if closure is not None:
            counts = closure["counts"]
            settled_none, falsified_none = counts[0] == 0, counts[3] == 0
            closure_words = (
                "<b>另有一组数是本季闭环质量的直接读数</b>："
                f"上季留下的 {sum(counts)} 条待验证问题里，"
                + "、".join(f"{count} 条{word}" for word, count in zip(CLOSURE_WORDS, counts)) + "。"
                + ("一条都没闭环，也一条都没被推翻 —— " if settled_none and falsified_none else
                   "一条都没闭环 —— " if settled_none else
                   "一条都没被推翻 —— " if falsified_none else "")
                + told("closure_reading")
            )
        verdict_chart = {
            "kind": "bars_labeled",
            "title": (f"上季 {sum(verdicts['counts'])} 条跟踪指标：" + "、".join(
                f"{count} 条{VERDICT_TITLE_WORDS.get(label, label)}"
                for label, count in zip(verdicts["labels"], verdicts["counts"]))),
            "xlabels": verdicts["labels"],
            "values": verdicts["counts"],
            "legend": "指标条数",
            "fmt": "f0",
            "yfmt": "f0",
            "label_fmt": "f0",
            "ylab": "条",
            "note": verdicts["note"] + closure_words,
            "src_extra": (
                "指标与阈值为本地研究设定，不是公司指引；"
                f"判定依据 {release_date} 业绩 8-K、截至 {period_end} 的 10-Q 与业绩电话会。"
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
    gaap_eps_beat = pct_change(financials["gaap_eps_usd"][-1], guided_gaap_eps)
    gaap_lo = record["guide_gaap_expenses_lo_usd_m"][current]
    gaap_hi = record["guide_gaap_expenses_hi_usd_m"][current]
    gaap_expense = revenue[-1] - financials["gaap_operating_income_usd_m"][-1]
    gaap_expense_gap = pct_change(gaap_expense, (gaap_lo + gaap_hi) / 2)
    # The non-GAAP other-income line, backed out of the printed net income at
    # the quarter's non-GAAP tax rate.
    actual_other = (financials["non_gaap_net_income_usd_m"][-1] / (1 - actual_tax / 100)
                    - financials["non_gaap_operating_income_usd_m"][-1]) if actual_tax is not None else None
    # Every guided line the page can check, and whether it did at least as well
    # as its midpoint (lower is better for the two expense lines and shares).
    lines_met = {
        "收入": revenue[-1] >= guided_revenue,
        "GAAP 费用": gaap_expense <= (gaap_lo + gaap_hi) / 2,
        "non-GAAP 费用": actual_expense <= guided_expense,
        "non-GAAP EPS": financials["non_gaap_eps_usd"][-1] >= guided_eps,
        "GAAP EPS": financials["gaap_eps_usd"][-1] >= guided_gaap_eps,
        "摊薄股数": financials["diluted_shares_m"][-1] <= guided_shares,
    }
    if actual_tax is not None:
        lines_met["non-GAAP 税率"] = actual_tax <= guided_tax
        lines_met["non-GAAP 非经营项"] = actual_other >= guided_other
    missed = [name for name, met in lines_met.items() if not met]
    all_five = all(value > 0 for _, value in delivery)
    rising = delivery[0][1] < delivery[2][1] < delivery[3][1]
    gaap_eps_huge = gaap_eps_beat > 3 * max(abs(value) for _, value in delivery)
    if missed == ["GAAP 费用"] and gaap_lo <= gaap_expense <= gaap_hi:
        missed_words = (
            "<b>并非每一条指引都优于中值</b>：公司同时指引的 GAAP 费用报出 "
            f"US${gaap_expense:,.0f}M，落在 US${gaap_lo:,.0f}–{gaap_hi:,.0f}M 的区间内，"
            f"但比中值高 {gaap_expense_gap:.1f}%，是本季唯一一条没做到中值的。它没有画在这根轴上，"
            "因为它与 non-GAAP 费用衡量的是同一件事的两种口径，并列会重复计数。"
        )
    elif missed:
        missed_words = "<b>没做到中值的指引</b>：" + "、".join(missed) + "。"
    else:
        missed_words = "本页能核对的各条指引全部做到了中值。"
    delivery_chart = {
        "ref": "EX_DELIVERY",
        "kind": "diverging_bars",
        "title": (
            (f"本季这五项全部优于指引中值" if all_five else
             f"本季这五项里 {sum(1 for _, value in delivery if value > 0)} 项优于指引中值")
            + f"：收入 {signed(delivery[0][1])}，non-GAAP EPS {signed(delivery[3][1])}"
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
            ("<b>五根柱的高度差本身就是结论</b>：收入只比中值高 "
             f"{delivery[0][1]:.1f}%，non-GAAP EPS 却高 {delivery[3][1]:.1f}% —— "
             "越往损益表下方走，超额越大，而中间那根「隐含营业利润」正是两者之间的那一步。"
             if rising and all_five else
             f"收入较中值 {signed(delivery[0][1])}，隐含营业利润 {signed(delivery[2][1])}，"
             f"non-GAAP EPS {signed(delivery[3][1])}。")
            + ((f"<b>GAAP EPS 同样超出指引，而且超出 {gaap_eps_beat:.0f}%，但本图刻意不画它</b>："
                "一根那么长的柱会把其余四根压平，而且这个数本身不可比 —— "
                + told("gaap_eps_note") + "，见 Exhibit {EX_WEDGE}。")
               if gaap_eps_huge and story_or.get("gaap_eps_note")
               and financials["gaap_eps_usd"][-1] > record["guide_gaap_eps_hi_usd"][current] else
               f"GAAP EPS 较指引中值 {signed(gaap_eps_beat, 0)}，本图不画 GAAP 口径。")
            + "费用与股数两项已按「比承诺少为正」翻过符号，与其余各项方向统一。"
            + missed_words
            + "这几项的长窗口记录见 Exhibit {EX_REV_RANGE} 起的指引兑现组图。"
        ),
        "src_extra": (
            f"指引为上季（{record['guided_in_release'][current]}）业绩 8-K 的 Financial Targets 表所载本季口径："
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
    expectation_chart = None
    expectation = None
    if consensus is not None and next_quarter is not None:
        next_eps_mid = (next_quarter["non_gaap_eps_usd"][0] + next_quarter["non_gaap_eps_usd"][1]) / 2
        expectation = [
            ("营收 vs 市场预期", pct_change(revenue[-1], consensus["revenue_usd_m"])),
            ("non-GAAP EPS vs 市场预期",
             pct_change(financials["non_gaap_eps_usd"][-1], consensus["non_gaap_eps_usd"])),
            ("下季 non-GAAP EPS 指引中值 vs 市场预期",
             pct_change(next_eps_mid, consensus["next_quarter_non_gaap_eps_usd"])),
            ("non-GAAP 营业利润 环比",
             pct_change(financials["non_gaap_operating_income_usd_m"][-1],
                        financials["non_gaap_operating_income_usd_m"][-2])),
            ("non-GAAP EPS 环比",
             pct_change(financials["non_gaap_eps_usd"][-1], financials["non_gaap_eps_usd"][-2])),
        ]
        guide_leads = expectation[2][1] > max(expectation[0][1], expectation[1][1])
        gaap_wild = max(abs(gaap_oi_qoq), abs(gaap_eps_qoq)) > 100
        expectation_chart = {
            "ref": "EX_EXPECTATION",
            "kind": "diverging_bars",
            "title": (
                (story_or["expectation_lead"] + "：" if story_or.get("expectation_lead") and guide_leads
                 else "本季与下季指引对照市场预期：")
                + f"EPS 指引中值{'高出' if expectation[2][1] >= 0 else '低于'}预期 {abs(expectation[2][1]):.1f}%"
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
                ("<b>真正的意外不在本季，在下季指引</b>：本季收入与 EPS 对市场预期的超出各为 "
                 f"{expectation[0][1]:.1f}% 与 {expectation[1][1]:.1f}%，属常规幅度；"
                 f"下一季 non-GAAP EPS 指引中值 US${next_eps_mid:.2f} "
                 f"却比同一时点的公开隐含预期高出 {expectation[2][1]:.1f}%，这才是本季信息量最大的一格。"
                 if story_or.get("expectation_lead") and guide_leads and expectation[0][1] > 0
                 and expectation[1][1] > 0 else
                 f"本季收入与 EPS 对市场预期分别 {signed(expectation[0][1])} 与 {signed(expectation[1][1])}；"
                 f"下一季 non-GAAP EPS 指引中值 US${next_eps_mid:.2f} 对同一时点的公开隐含预期 "
                 f"{signed(expectation[2][1])}。")
                + (("<b>GAAP 口径的环比被刻意排除在本图之外</b>，因为它会撑爆这根轴而且没有含义："
                    f"GAAP 营业利润环比 {gaap_oi_qoq:+.0f}%、GAAP EPS 从 "
                    f"US${financials['gaap_eps_usd'][-2]:.2f} 到 US${financials['gaap_eps_usd'][-1]:.2f}（"
                    f"{gaap_eps_qoq:+.0f}%）—— " + told("expectation_note"))
                   if gaap_wild and story_or.get("expectation_note") else
                   f"GAAP 口径的环比不在本图：营业利润 {gaap_oi_qoq:+.0f}%、EPS {gaap_eps_qoq:+.0f}%。")
                + f"同期 non-GAAP 营业利润环比 {expectation[3][1]:+.1f}%，那才是经营斜率。"
                "前三根柱对的是市场预期，后两根是环比，两类对照并列于同一轴上，"
                "只用于比较方向与相对幅度。"
            ),
            "src_extra": (
                f"实际值来自 {release_date} 业绩 8-K；市场预期为财报前公开隐含一致预期"
                f"（{consensus['as_of']}），不具名、不引用任何机构。"
            ),
        }

    # ── section two ──────────────────────────────────────────────────────────
    close = periods.index(ANSYS_CLOSE) if ANSYS_CLOSE in periods else None
    fy_mid_now = middle(full_year["revenue_usd_m"]) if full_year else None
    if ansys_split is not None:
        shares_pct = ansys_split["percentages_pct"]
        values.update({
            "ansys_share": f"{shares_pct['Ansys']:.1f}%",
            "ansys_shares": "、".join(f"{name} {value:.1f}%" for name, value in shares_pct.items()),
            "ansys_base": f"${ansys_split['revenue_usd_m']:,.1f}M",
            "ansys_implied": f"${ansys_split['revenue_usd_m'] * shares_pct['Ansys'] / 100:,.1f}M",
            "ansys_rest": f"${da_revenue[-1] - ansys_split['revenue_usd_m'] * shares_pct['Ansys'] / 100:,.0f}M",
            "ansys_precision": f"${ansys_split['revenue_usd_m'] * 0.0005:,.1f}M",
        })
    if footnote is not None:
        values["fy_ansys_expected"] = f"${footnote['expected_ansys_revenue_usd_m'][-1] / 1000:.2f}B"
    anchors = ""
    if footnote is not None and fy_mid_now:
        anchors = (
            ("<b>公司自己给的口径有两处可核对</b>：本季 10-Q 收入分解附注里 Ansys 占 "
             f"{values['ansys_share']}（≈ {values['ansys_implied']}，见第三节）；" if ansys_split is not None else
             "<b>公司自己给的全年口径</b>：")
            + f"{full['fiscal_year']} 收入指引的脚注写明其中含 "
            f"US${footnote['expected_ansys_revenue_usd_m'][-1]:,.0f}M 的 Ansys 收入，"
            f"占指引中点的 {footnote['expected_ansys_revenue_usd_m'][-1] / fy_mid_now * 100:.1f}%"
            + ("，拆解见 Exhibit {EX_FY_SPLIT}。" if fy_split else "。")
        )
    revenue_chart = {
        "ref": "EX_REVENUE",
        "kind": "gs_bar",
        "title": (
            f"收入 US${revenue[-1]:,.0f}M、同比 {signed(financials['revenue_yoy_pct'][-1])}"
            + (f"，{story_or['revenue_title_tail']}" if story_or.get("revenue_title_tail") else "")
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
            + told("revenue_note")
            + anchors
            + told("ansys_quarterly_note")
        ),
        "src_extra": "收入来自各季业绩 8-K 合并损益表；同比为自算 D，分母见口径说明。",
    }

    ip_now = ip_revenue[-1]
    after_close = [ip_revenue[i] for i in range(close + 1, len(periods))] if close is not None else []
    falls = 0
    if close is not None:
        while (close + falls + 1 < len(periods)
               and ip_revenue[close + falls + 1] < ip_revenue[close + falls]):
            falls += 1
    ip_title = (
        f"Design IP 连续{cn_count(ip_streak)}季同比负增长后重新转正：US${ip_now:,.0f}M，同比 {signed(ip_yoy[-1])}"
        if ip_turned else
        f"Design IP US${ip_now:,.0f}M，同比 {signed(ip_yoy[-1])}"
    )
    segment_chart = {
        "ref": "EX_SEG_REV",
        "kind": "grouped_bars",
        "title": ip_title,
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
            ("<b>金色那条是本季最该看的一条线</b>，因为它正是 Exhibit {EX_REV_DEV} 里"
             "那次真实跌破指引的原因：" if ip_turned else "金色那条是 Exhibit {EX_REV_DEV} 里那次真实跌破指引的原因：")
            + (f"{labels[close]} 公司在新闻稿里直接写「IP 业务低于预期」，" if close is not None else "")
            + (f"随后{cn_count(falls)}季降到 US${min(after_close[:falls]):,.0f}M，" if falls else "")
            + f"本季{'回到' if ip_turned else '为'} US${ip_now:,.0f}M、同比 {signed(ip_yoy[-1])}。"
            "深蓝的 Design Automation 从 Q3'25 起的台阶是 Ansys 并入该分部造成的，"
            "不是这条线自己的斜率。两个分部的口径自 2024 年起为两分部制，"
            "此前还有第三个 Software Integrity 分部，见口径说明。"
        ),
        "src_extra": (
            "分部收入来自各季业绩 8-K 的 Business Segment Reporting 表；"
            "会计季 Q4 无 10-Q，其值为财年数减九个月数 D，两端均为申报值。"
            + (f"{'、'.join(ip_base_outside)} 的同比分母取自各该季新闻稿分部表的上年同期列。"
               if ip_base_outside else "")
        ),
    }

    ip_cost_yoy = pct_change(ip_revenue[-1] - segments["design_ip_adj_op_income"][-1],
                             ip_revenue[-5] - segments["design_ip_adj_op_income"][-5])
    both_up = da_margin[-1] > da_margin[-5] and ip_margin[-1] > ip_margin[-5]
    ip_trough = min(range(len(ip_margin)), key=lambda i: ip_margin[i])
    segment_margin_chart = {
        "ref": "EX_SEG_MARGIN",
        "kind": "lines",
        "title": (
            f"两个分部的调整后营业利润率{'同时改善' if both_up else ''}：Design Automation {da_margin[-1]:.1f}%、"
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
            (f"Design IP 的利润率从 {labels[ip_trough]} 的 {ip_margin[ip_trough]:.1f}% 低点回到 {ip_margin[-1]:.1f}%，"
             if ip_trough != len(ip_margin) - 1 else f"Design IP 的利润率 {ip_margin[-1]:.1f}% 是窗口低点，")
            + f"同比 {ip_margin[-1] - ip_margin[-5]:+.1f}pp"
            + (" —— <b>回升由收入杠杆驱动</b>："
               f"同期该分部收入同比 {signed(pct_change(ip_revenue[-1], ip_revenue[-5]))}，"
               "利润率与收入同向，不是砍费用砍出来的。"
               if ip_margin[-1] > ip_margin[-5] and ip_yoy[-1] > 0 and ip_cost_yoy >= 0 else "。")
            + "两条线相除的分母是各自分部的收入，"
            "分子是公司披露的 adjusted operating income（在集团层面剔除摊销、股权激励、"
            "重组与并购项之前的分部口径），因此<b>不能</b>与合并层面的 GAAP 营业利润率相比，"
            "两者的差额见 Exhibit {EX_WEDGE}。"
        ),
        "src_extra": (
            "分部调整后营业利润来自各季业绩 8-K 的 Business Segment Reporting 表；"
            "利润率为自算 D（公司同表也披露该比率，四舍五入到 0.1pp，与自算一致）。"
        ),
    }

    before_close = [amortization[i] for i in range(close)] if close else []
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
            ("<b>金色柱在 Q3'25 之后的跳升是这一页最重要的一个台阶</b>："
             f"收购无形资产摊销从并购前的季均 US${sum(before_close) / len(before_close):,.0f}M "
             f"一次跳到 US${amortization[-1]:,.0f}M，相当于本季收入的 {amortization_share[-1]:.1f}%。"
             if before_close else
             f"收购无形资产摊销本季 US${amortization[-1]:,.0f}M，相当于收入的 {amortization_share[-1]:.1f}%。")
            + "它同时出现在营业成本与营业费用两行，本图取两行之和。"
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
    ni_yoy = pct_change(financials["non_gaap_net_income_usd_m"][-1], financials["non_gaap_net_income_usd_m"][-5])
    eps_yoy = pct_change(financials["non_gaap_eps_usd"][-1], financials["non_gaap_eps_usd"][-5])
    dilution_chart = {
        "ref": "EX_DILUTION",
        "kind": "lines",
        "title": (
            f"{cn_count(len(periods))}季里收入指数化到 {revenue[-1] / base_revenue * 100:.0f}、"
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
            f"{signed(financials['revenue_yoy_pct'][-1])}、non-GAAP 净利同比 {signed(ni_yoy)}、"
            f"每股同比只有 {signed(eps_yoy)}。"
            # Fixed history: the Ansys consideration paid in stock.
            "股数的台阶来自 Ansys 对价里以股份支付的那一半（公司为该交易发行 3,000 万股），"
            "而不是逐季的股权激励；十年维度上的股数与回购见 Exhibit {EX_BUYBACK}。"
        ),
        "src_extra": (
            "四条线均由各季 8-K 的合并损益表与 GAAP/non-GAAP 对账数指数化 D，"
            "基期为本窗口第一季。"
        ),
    }

    fy_split_chart = None

    def moved(first: float, last: float) -> str:
        return "抬到" if last > first else "降到" if last < first else "仍是"

    if fy_split:
        fy_mid = [(lo + hi) / 2 for lo, hi
                  in zip(footnote["revenue_lo_usd_m"], footnote["revenue_hi_usd_m"])]
        ansys = footnote["expected_ansys_revenue_usd_m"]
        core = [total - a for total, a in zip(fy_mid, ansys)]
        raises = sum(1 for a, b in zip(fy_mid, fy_mid[1:]) if b > a)
        vintages = len(footnote["releases"])
        channel = [(release_at, amount) for release_at, amount
                   in zip(footnote["releases"], footnote.get("ansys_channel_accounting_usd_m", []))
                   if amount is not None]
        divest = footnote["divestiture_impact_usd_m"]
        first_run = 1
        while first_run < len(divest) and divest[first_run] == divest[0]:
            first_run += 1
        channel_words = ""
        if len(channel) == 1:
            at = footnote["releases"].index(channel[0][0])
            channel_words = (
                f"<b>脚注里还有一句更值得记的话</b>：{channel[0][0]} 那份写明 US${ansys[at]:,.0f}M 里含 "
                f"US${channel[0][1]:,.0f}M 是 Ansys 渠道伙伴的会计影响 —— 这是公司唯一一次在申报文件里给该会计项标价，"
                "它进收入、不进利润。"
            )
        fy_split_chart = {
            "ref": "EX_FY_SPLIT",
            "kind": "grouped_bars",
            "title": (
                f"{footnote['fiscal_year']} 收入指引"
                + (f"{cn_count(raises)}次上调共 US${fy_mid[-1] - fy_mid[0]:,.0f}M，" if fy_mid[-1] > fy_mid[0] else
                   f"累计下调 US${fy_mid[0] - fy_mid[-1]:,.0f}M，" if fy_mid[-1] < fy_mid[0] else "中点没有变，")
                + 
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
            "ylab": f"{footnote['fiscal_year']} 收入指引中点 US$M",
            "note": (
                "<b>这是全页唯一能把并购与原生分开的地方，而且分法是公司自己给的。</b>"
                f"每份新闻稿的 {footnote['fiscal_year']} 收入指引下面都挂着一条脚注，写明这个数里含多少 Ansys 收入。"
                f"把{cn_count(vintages)}次指引并排：中点从 US${fy_mid[0]:,.0f}M {moved(fy_mid[0], fy_mid[-1])} US${fy_mid[-1]:,.0f}M，"
                f"共 US${fy_mid[-1] - fy_mid[0]:+,.0f}M；同期脚注里的 Ansys 从 "
                f"US${ansys[0]:,.0f}M {moved(ansys[0], ansys[-1])} US${ansys[-1]:,.0f}M，"
                f"即 US${ansys[-1] - ansys[0]:+,.0f}M。"
                f"两者相减，其余业务这{cn_count(vintages - 1)}次合计"
                + (f"只上修了 US${core[-1] - core[0]:,.0f}M。" if core[-1] > core[0] else
                   f"反而下修了 US${abs(core[-1] - core[0]):,.0f}M。" if core[-1] < core[0] else "没有变。")
                + channel_words
                + (f"前{cn_count(first_run)}次脚注只提 OSG 与 PowerArtist RTL 约 US${abs(divest[0]):,.0f}M 的剥离影响，"
                   f"后{cn_count(vintages - first_run)}次加上 Processor IP Solutions 的 "
                   f"US${abs(divest[-1]) - abs(divest[0]):,.0f}M。" if first_run < vintages else "")
            ),
            "src_extra": (
                f"{cn_count(vintages)}个指引中点与其脚注均取自 {'、'.join(footnote['releases'])} "
                f"{cn_count(vintages)}份业绩 8-K 的 EX-99.1；「其余业务」为中点减脚注 Ansys 数的自算值 D，"
                "不是公司披露的分部拆分。"
            ),
        }

    # ── section three ────────────────────────────────────────────────────────
    twelve_month = [(b - f) * p / 100 for b, f, p
                    in zip(backlog["backlog_usd_b"], backlog["fsa_usd_b"],
                           backlog["next_12m_pct_of_ex_fsa"])]
    fsa_share = [f / b * 100 for f, b in zip(backlog["fsa_usd_b"], backlog["backlog_usd_b"])]
    backlog_labels = [compact_period(quarter) for quarter in backlog["quarters"]]

    tracked = {
        "ng_margin": (labels, rounded(financials["non_gaap_operating_margin_pct"]),
                      "pct1", "营业利润率", "non-GAAP 营业利润率"),
        "ip_yoy": (labels, rounded(ip_yoy), "pct1", "同比", "Design IP 同比"),
        "backlog_12m": (backlog_labels, rounded(twelve_month), "f1",
                        "US$B", "未来 12 个月可确认额 D"),
        "fsa_share": (backlog_labels, rounded(fsa_share), "pct1", "占 backlog 比重", "FSA 占比 D"),
        "shares": (labels, financials["diluted_shares_m"], "f0c", "百万股", "摊薄股数"),
    }
    computed_now = {
        "ng_margin": financials["non_gaap_operating_margin_pct"][-1],
        "ip_yoy": ip_yoy[-1],
        "backlog_12m": twelve_month[-1],
        "fsa_share": fsa_share[-1],
        "shares": financials["diluted_shares_m"][-1],
    }

    def current_of(entry: dict) -> float:
        """A threshold's current value, computed from the series rather than typed."""
        if entry["id"] in computed_now:
            if "current" in entry:
                raise ValueError(f"threshold `{entry['id']}` is computed from the series; "
                                 "remove its typed value")
            return computed_now[entry["id"]]
        if "current" not in entry:
            raise ValueError(f"threshold `{entry['id']}` has no value and no way to compute one")
        return entry["current"]

    next_charts = []
    if next_kpi is not None:
        entries = [{**entry, "current": current_of(entry)} for entry in next_kpi["quantified"]]
        margins = {entry["id"]: headroom(entry["direction"], entry["threshold"], entry["current"])
                   for entry in entries}
        names = {entry["id"]: entry["metric"] for entry in entries}
        breached = [key for key, value in margins.items() if value < 0]
        thinnest = min(margins, key=margins.get)
        ordered = sorted(margins, key=margins.get)
        if next_kpi.get("thinnest_two") and sorted(ordered[:2]) != sorted(next_kpi["thinnest_two"]):
            raise ValueError(f"series block `next_kpi` says the two thinnest are {next_kpi['thinnest_two']}, "
                             f"the data says {ordered[:2]}: rewrite its note for this quarter")
        for entry in entries:
            values[f"next_margin:{entry['id']}"] = f"{margins[entry['id']]:.1f}%"
            values[f"next_current:{entry['id']}"] = unit_text(entry["unit"], entry["current"])
            values[f"next_threshold:{entry['id']}"] = unit_text(entry["unit"], entry["threshold"])
        fsa_now, fsa_prev = backlog["fsa_usd_b"][-1], backlog["fsa_usd_b"][-2]
        values.update({
            "fsa_now": f"{fsa_now:.1f}", "fsa_prev": f"{fsa_prev:.1f}",
            "fsa_prev_high": f"{fsa_prev + 0.04:.2f}", "fsa_now_low": f"{fsa_now - 0.04:.2f}",
        })
        if full is not None:
            values["fy_label"] = full["fiscal_year"]
            values["fy_ng_margin_mid"] = f"{full_year['non_gaap_operating_margin_midpoint_pct']:.1f}%"
        excluded = next_kpi.get("excluded", [])
        excluded_text = (
            f"另有{cn_count(len(excluded))}条本页<b>不接入</b>，原因各不相同，都写在这里而不是省略掉："
            + "；".join(f"（{i}）{fill_story(item, values)}" for i, item in enumerate(excluded, 1)) + "。"
            if excluded else "")
        share_entry = next((e for e in entries if e["id"] == "shares"), None)
        own_ceiling = (share_entry is not None and next_quarter is not None
                       and share_entry["threshold"] == next_quarter["diluted_shares_m"][1])
        headroom_chart = headroom_exhibit(
            (f"下季 {len(entries)} 条量化阈值：{len(entries) - len(breached)} 条仍在安全侧，"
             f"{len(breached)} 条已越线"
             if breached else
             f"下季 {len(entries)} 条量化阈值：全部仍在安全侧，最薄的「{names[thinnest]}」只剩 {margins[thinnest]:.1f}%"),
            entries,
            "current",
            "正值 = 仍在安全侧。" + fill_story(next_kpi.get("note", ""), values),
            src_extra=(
                "阈值为本地研究设定，不是公司指引"
                + (f"（股数一条的 {unit_text(share_entry['unit'], share_entry['threshold'])} 取自公司自己的指引上限）"
                   if own_ceiling else "")
                + f"；当前值为截至 {period_end} 的实际。"
                + excluded_text
            ),
        )
        next_charts = [headroom_chart]
        for entry in entries:
            if entry["id"] not in tracked:
                continue
            xlabels, series_values, fmt, ylab, actual_name = tracked[entry["id"]]
            side = "上方" if entry["direction"] == "up" else "下方"
            next_charts.append(threshold_exhibit(
                (f"{entry['metric']}：下季阈值 {unit_text(entry['unit'], entry['threshold'])}，"
                 f"当前 {unit_text(entry['unit'], entry['current'])}"),
                xlabels,
                series_values,
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
    else:
        entries = []

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
    trough = min(range(len(long_amort_share)), key=lambda i: long_amort_share[i])
    trough_year = long_labels[trough]
    monotonic = all(b < a for a, b in zip(long_amort_share[:trough + 1], long_amort_share[1:trough + 1]))
    way = "一路降到" if monotonic else "降到"
    ten = cn_count(len(long_labels))
    fy26_amort_share = (amortization[-1] * 4 / fy_mid_now * 100) if fy_mid_now else None
    close_year_last = long_labels[-1] == ANSYS_CLOSE_YEAR
    amort_chart = {
        "ref": "EX_AMORT_LONG",
        "kind": "gs_line",
        "title": (
            f"收购摊销强度从 {long_labels[0]} 的 {long_amort_share[0]:.1f}% {way} {trough_year} 的 "
            f"{long_amort_share[trough]:.1f}%，Ansys 一笔又把它推到 {amortization_share[-1]:.1f}%"
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
            f"从 {long_labels[0]} 的 {long_amort_share[0]:.1f}% {way} "
            f"{trough_year} 的 {long_amort_share[trough]:.1f}%"
            + ("" if monotonic else
               "（中间只有 " + "、".join(long_labels[i] for i in range(1, trough + 1)
                                   if long_amort_share[i] > long_amort_share[i - 1]) + " 小幅回升）")
            + " —— 旧并购的无形资产逐年摊完，而收入在长大，"
            "GAAP 与 non-GAAP 之间的距离因此越来越小，两套口径几乎收敛。"
            + (f"{long_labels[-1]} 因 Ansys 在 7 月并入而回到 {long_amort_share[-1]:.1f}%，"
               if close_year_last else f"{long_labels[-1]} 为 {long_amort_share[-1]:.1f}%，")
            + f"而本季（{labels[-1]}）单季{'已是' if amortization_share[-1] > long_amort_share[-1] else '为'} "
            f"{amortization_share[-1]:.1f}%"
            + (f"，按公司自己的 {full['fiscal_year']} 收入指引中点年化约 {fy26_amort_share:.1f}%。"
               if fy26_amort_share is not None else "。")
            + (f"<b>换句话说，{ten}年里被摊完的东西被一笔交易一次性加了回来，而且量级是过去的"
               f"{times_words(amortization_share[-1] / long_amort_share[0])}。</b>"
               if amortization_share[-1] > long_amort_share[0] else "")
            + ("这决定了未来若干年 GAAP 与 non-GAAP 的距离不会自己收窄："
               f"本页这{ten}年里没有任何一年接近过现在的水平。"
               if max(long_amort_share) < amortization_share[-1] / 2 else "")
        ),
        "src_extra": (
            "逐年读自各年 10-K 合并损益表的两行「Amortization of acquired intangible assets」"
            "（营业成本内与营业费用内）之和 D，除以当年收入；每年取该年 10-K 首次印出的数。"
            f"本季的 {amortization_share[-1]:.1f}% 是八季窗口最新一季的单季值，与年度值不可直接连读。"
        ),
    }

    gaap_drop = long_margin[-1] - long_margin[-2]
    ex_drop = long_margin_ex[-1] - long_margin_ex[-2]
    amort_step = long_amort_share[-1] - long_amort_share[-2]
    margin_wedge_chart = {
        "ref": "EX_MARGIN_LONG",
        "kind": "lines",
        "title": (
            f"GAAP 营业利润率一年之内从 {long_margin[-2]:.1f}% {'掉到' if gaap_drop < 0 else '升到'} "
            f"{long_margin[-1]:.1f}%"
            + (f"，其中 {amort_step:.1f}pp 是收购摊销" if gaap_drop < 0 < amort_step <= abs(gaap_drop) + 0.05 else "")
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
            f"GAAP 营业利润率从 {long_labels[-2]} 的 {long_margin[-2]:.1f}% "
            f"{'掉到' if gaap_drop < 0 else '升到'} {long_labels[-1]} 的 "
            f"{long_margin[-1]:.1f}%，一年 {gaap_drop:.1f}pp。"
            f"金线同期从 {long_margin_ex[-2]:.1f}% 到 {long_margin_ex[-1]:.1f}%，"
            + (f"只掉 {abs(ex_drop):.1f}pp —— "
               f"<b>也就是说这 {abs(gaap_drop):.1f}pp 的跌幅里，{amort_step:.1f}pp 是收购摊销，"
               f"剩下的 {abs(ex_drop):.1f}pp 才是别的东西</b>"
               + ("（重组费用与并购完成当年抬高的股权激励）。" if close_year_last else "。")
               if gaap_drop < ex_drop < 0 else f"变动 {ex_drop:+.1f}pp。")
            + "<b>本图刻意只加回收购摊销这一项，不加股权激励也不加重组</b>："
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

    buybacks_long = long["share_repurchases_usd_m"]
    # The last block of zero years, the paying run before it, and what came after.
    end = len(buybacks_long)
    while end > 0 and buybacks_long[end - 1] > 0:
        end -= 1
    resumed = long_labels[end:]
    zero_end = end
    zero_run = 0
    while zero_end - zero_run > 0 and buybacks_long[zero_end - 1 - zero_run] == 0:
        zero_run += 1
    start = zero_end - zero_run
    positive_run = 0
    while start - positive_run > 0 and buybacks_long[start - 1 - positive_run] > 0:
        positive_run += 1
    if zero_run == 0:
        start, positive_run, resumed = len(buybacks_long), len(buybacks_long), []
        while positive_run > 0 and buybacks_long[start - positive_run] <= 0:
            positive_run -= 1
    paid = buybacks_long[start - positive_run:start]
    paid_years = long_labels[start - positive_run:start]
    paid_shares = long["diluted_shares_m"][start - positive_run:start]
    zero_years = long_labels[start:start + zero_run]
    # How long the share line stays inside the band the buybacks held it in.
    low, high = min(paid_shares) * 0.99, max(paid_shares) * 1.01
    flat_n = 0
    while flat_n < len(long_labels) and low <= long["diluted_shares_m"][flat_n] <= high:
        flat_n += 1
    flat_words = f"{ten}年" if flat_n == len(long_labels) else f"前{cn_count(flat_n)}年"
    fiscal_now = staging["fiscal_labels"][-1]
    fiscal_q = int(fiscal_now[-1])
    ytd = [i for i, label in enumerate(capital["fiscal_labels"]) if label[:6] == fiscal_now[:6]]
    ytd_buyback = sum(capital["buyback_usd_m"][i] or 0 for i in ytd)
    untouched = capital["remaining_authorization_usd_m"][-1] == capital["remaining_authorization_usd_m"][-2]
    buyback_chart = {
        "ref": "EX_BUYBACK",
        "kind": "grouped_bars",
        "title": (
            f"连续{cn_count(positive_run)}年每年买回 US${min(paid):,.0f}M "
            + ((f"以上，然后连着{cn_count(zero_run)}年归零"
                + (f" —— 股数{ten}年首次上台阶" if not resumed else f"，{resumed[0]} 恢复回购"))
               if zero_run else "以上")
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
            f"<b>金线{flat_words}几乎是一条平线，这本身就是深蓝柱子的功劳。</b>"
            f"{paid_years[0]}–{paid_years[-1]} 每年回购 US${min(paid):,.0f}M "
            f"到 US${max(paid):,.0f}M，"
            f"把摊薄股数按在 {min(paid_shares):.0f}–{max(paid_shares):.0f} 百万股之间，"
            "股权激励发多少就买回多少。"
            + (f"<b>然后 {' 与 '.join(zero_years)} 连着{cn_count(zero_run)}年一股未买</b>"
               + (" —— 那是为 Ansys 攒钱与去杠杆的两年，"
                  f"而 {zero_years[-1]} 的股数一次抬到 "
                  f"{long['diluted_shares_m'][long_labels.index(zero_years[-1])]:.0f} 百万股。"
                  if zero_years[-1] == ANSYS_CLOSE_YEAR else "。")
               if zero_run else "")
            + told("buyback_authorization_note")
            + f"本财年{FISCAL_YTD_WORDS[fiscal_q]}实际动用 US${ytd_buyback:,.0f}M，"
            f"{int(period_end[5:7])} 月 {int(period_end[8:10])} 日仍余 "
            f"US${capital['remaining_authorization_usd_m'][-1]:,.0f}M；"
            + (f"最近一季的现金流出 US${capital['buyback_usd_m'][-1]:,.1f}M"
               + (" " + told("last_quarter_buyback_note") if story_or.get("last_quarter_buyback_note") else "")
               + ("，授权余额整个季度<b>一美元未动</b>。" if untouched else "。")
               if capital["buyback_usd_m"][-1] else "最近一季没有回购。")
            + "每股口径这两年为什么走不动，见 Exhibit {EX_DILUTION}。"
        ),
        "src_extra": (
            f"回购金额与摊薄股数逐年读自各年 10-K；{fiscal_now[:6]} 各季回购与授权余额来自各季 10-Q 的"
            "现金流量表与 Item 2(c)，会计季 Q4 与季度差分为自算 D。"
        ),
    }

    # The page reads the backlog against the last fiscal year-end it holds
    # (fiscal Q4 is the calendar Q3 on this page's labels).
    year_ends = [i for i, label in enumerate(backlog["fiscal_labels"]) if label.endswith("Q4")]
    year_end = year_ends[-1] if year_ends[-1] != len(backlog["fiscal_labels"]) - 1 else year_ends[-2]
    year_end_label = backlog["fiscal_labels"][year_end][:6]
    since = backlog["backlog_usd_b"][year_end:]
    falling = all(b < a for a, b in zip(since, since[1:]))
    backlog_chart = {
        "ref": "EX_BACKLOG",
        "kind": "lines",
        "title": (
            f"backlog 自 {year_end_label} 年末的 US${since[0]:.1f}B "
            + (f"连降{cn_count(len(since) - 1)}季至 " if falling and len(since) > 1 else "到 ")
            + f"US${since[-1]:.1f}B"
            + (f"，但可确认的那一半从 US${twelve_month[year_end]:.2f}B 升到 US${twelve_month[-1]:.2f}B"
               if twelve_month[-1] > twelve_month[year_end] and since[-1] < since[0] else "")
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
            ("<b>深蓝在降、金色在升，这两件事同时为真，而且不矛盾。</b>"
             if since[-1] < since[0] and twelve_month[-1] > twelve_month[year_end] else "")
            + f"总额从 {year_end_label} 年末的 US${since[0]:.1f}B {'降到' if since[-1] < since[0] else '到'} "
            f"US${since[-1]:.1f}B，同比{'仍' if since[-1] < since[0] and pct_change(since[-1], backlog['backlog_usd_b'][-5]) > 0 else ''}是 "
            f"{signed(pct_change(backlog['backlog_usd_b'][-1], backlog['backlog_usd_b'][-5]))}；"
            "而公司在同一句话里披露的「未来 12 个月内可确认的比例」从 "
            f"{backlog['next_12m_pct_of_ex_fsa'][year_end]:.0f}% "
            f"{'升到' if backlog['next_12m_pct_of_ex_fsa'][-1] > backlog['next_12m_pct_of_ex_fsa'][year_end] else '到'} "
            f"{backlog['next_12m_pct_of_ex_fsa'][-1]:.0f}%，"
            f"于是可确认额{('反而升到' if since[-1] < since[0] else '升到') if twelve_month[-1] > twelve_month[year_end] else ('降到' if twelve_month[-1] < twelve_month[year_end] else '为')} "
            f"US${twelve_month[-1]:.2f}B（年末 US${twelve_month[year_end]:.2f}B）。"
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
    geo_n = cn_count(len(disagg["quarters"]))
    qoq_moves = {key: geo_shares[key][-1] - geo_shares[key][-2] for _, key, _ in geo_series}
    korea_leads = max(qoq_moves, key=qoq_moves.get) == "korea"
    full_quarter = disagg["quarters"].index(ANSYS_CLOSE) + 1 if ANSYS_CLOSE in disagg["quarters"] else None
    last_four = disagg["china"][-4:]
    europe_jump = (geo_shares["europe"][full_quarter] - geo_shares["europe"][full_quarter - 1]
                   if full_quarter is not None else None)
    gap = [c - k for c, k in zip(geo_shares["china"], geo_shares["korea"])]
    crossed = any(a > 0 > b for a, b in zip(gap, gap[1:]))

    def share_move(key: str, first: int = 0) -> str:
        a, b = geo_shares[key][first], geo_shares[key][-1]
        verb = "升到" if round(b, 1) > round(a, 1) else "降到" if round(b, 1) < round(a, 1) else "持平于"
        return f"从 {a:.1f}% {verb} {b:.1f}%"

    geography_chart = {
        "ref": "EX_GEO",
        "kind": "lines",
        "title": (
            f"中国占比 {len(geo_shares['china'])} 季{share_move('china')}，"
            f"韩国同期{share_move('korea')}"
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
            (f"<b>红线与金线的交叉是这{geo_n}季地域结构里最实的一件事</b>：" if crossed else
             f"<b>红线与金线是这{geo_n}季地域结构里最该对照读的两条</b>：")
            + f"中国占比从 {max(geo_shares['china']):.1f}% 的高点降到 {geo_shares['china'][-1]:.1f}%，"
            f"韩国{share_move('korea')}，本季环比 "
            f"{qoq_moves['korea']:+.1f}pp"
            + ("，是全公司最强的一格。" if korea_leads else "。")
            + "<b>但占比的变化里混着两件事</b>：Ansys 自 Q2'25 起并入，"
            + (f"把欧洲的分子一次抬高（欧洲占比在 {geo_labels[full_quarter]} 单季跳升 {europe_jump:.1f}pp），"
               if europe_jump is not None and europe_jump > 0 else "把欧洲的分子一次抬高，")
            + "同时也稀释了所有其他地区的占比。所以跨 Q2'25 的占比变化不能当有机结构变化读；"
            f"中国的绝对金额同期从 US${disagg['china'][0]:,.0f}M 到 "
            f"US${disagg['china'][-1]:,.0f}M，{cn_count(len(last_four))}个季度的运行率基本停在 "
            f"US${int(min(last_four) // 10 * 10)}–{int(-(-max(last_four) // 10) * 10)}M 之间，"
            "这才是不受并表影响的读法。"
        ),
        "src_extra": (
            "分地区收入逐季读自各期 10-Q / 10-K 分部附注的"
            "「Revenue related to operations in the United States and other geographic areas」表；"
            "占比为自算 D；会计季 Q4 为财年数减九个月数 D。"
            f"全部{geo_n}季均为剔除 Software Integrity 后的持续经营口径。"
        ),
    }

    # ── what the story blocks may assume, recomputed ─────────────────────────
    facts = {
        "guide_beats_quarter": bool(expectation) and expectation[2][1] > max(expectation[0][1], expectation[1][1]),
        "gaap_gain_quarter": financials["gaap_eps_usd"][-1] > record["guide_gaap_eps_hi_usd"][current],
        "ansys_base_partial": close is not None and len(periods) - 1 - close == 4,
    }
    require(story, facts, "quarter_story")

    # ── assemble ─────────────────────────────────────────────────────────────
    settled_charts = ([verdict_chart] if verdict_chart else []) + [delivery_chart] \
        + ([expectation_chart] if expectation_chart else []) + delivery_charts
    highlights = [revenue_chart, segment_chart, segment_margin_chart, wedge_chart,
                  dilution_chart] + ([fy_split_chart] if fy_split_chart else [])
    routine = [amort_chart, margin_wedge_chart, buyback_chart, backlog_chart, geography_chart]

    refs = {ex.get("ref"): ex for ex in settled_charts + highlights + next_charts + routine if ex.get("ref")}
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
    for index, label in enumerate(periods):
        quarterly_rows.append([
            label,
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
            label,
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
    cap_at = {q: i for i, q in enumerate(capital["quarters"])}
    for index, quarter in enumerate(backlog["quarters"]):
        backlog_rows.append([
            quarter,
            backlog["fiscal_labels"][index],
            f"US${backlog['backlog_usd_b'][index]:.1f}B",
            f"US${backlog['fsa_usd_b'][index]:.1f}B",
            f"{fsa_share[index]:.1f}% D",
            f"{backlog['next_12m_pct_of_ex_fsa'][index]:.0f}%",
            f"US${twelve_month[index]:.2f}B D",
            # Capital allocation is a shorter block with its own quarters list,
            # looked up by quarter so a length change can never silently pair
            # the wrong two rows.
            (f"${capital['buyback_usd_m'][cap_at[quarter]]:,.1f}M"
             if quarter in cap_at and capital["buyback_usd_m"][cap_at[quarter]] is not None else "—"),
            (f"${capital['capex_usd_m'][cap_at[quarter]]:,.1f}M"
             if quarter in cap_at and capital["capex_usd_m"][cap_at[quarter]] is not None else "—"),
            ("是" if capital["derived"][cap_at[quarter]] else "否") if quarter in cap_at else "—",
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
            # The two earliest quarters were recovered from a later filing's
            # comparative columns, which carry the geography split but not the
            # revenue-type split. Empty, not zero.
            *[f"${disagg[name][index]:,.1f}M" if disagg[name][index] is not None else "—"
              for name in ("time_based", "upfront", "maintenance_and_service")],
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

    def against(actual: float, low: float, high: float, lower_is_better: bool = False) -> str:
        """Where an actual landed against its guided range, in the table's words."""
        if actual > high:
            return "高于上限" if lower_is_better else "超出上限"
        if actual < low:
            return "低于下限"
        third = (high - low) / 3
        if lower_is_better:
            return "落在区间下沿" if actual <= low + third else "落在区间上沿" if actual >= high - third else "区间内"
        return "区间内"

    guide_rows = []
    lo_rev, hi_rev = record["guide_revenue_lo_usd_m"][current], record["guide_revenue_hi_usd_m"][current]
    lo_exp = record["guide_non_gaap_expenses_lo_usd_m"][current]
    hi_exp = record["guide_non_gaap_expenses_hi_usd_m"][current]
    lo_eps, hi_eps = record["guide_non_gaap_eps_lo_usd"][current], record["guide_non_gaap_eps_hi_usd"][current]
    lo_gaap, hi_gaap = record["guide_gaap_eps_lo_usd"][current], record["guide_gaap_eps_hi_usd"][current]
    lo_sh, hi_sh = record["guide_shares_lo_m"][current], record["guide_shares_hi_m"][current]
    if next_quarter is not None:
        gaap_verdict = against(financials["gaap_eps_usd"][-1], lo_gaap, hi_gaap)
        if gaap_verdict == "超出上限" and gaap_eps_huge:
            gaap_verdict = "远超上限" + (f"（{story_or['gaap_eps_table_note']}）"
                                          if story_or.get("gaap_eps_table_note") else "")
        guide_rows = [
            ["收入", f"${lo_rev:,.0f}–{hi_rev:,.0f}M",
             f"${revenue[-1]:,.1f}M", against(revenue[-1], lo_rev, hi_rev),
             f"${next_quarter['revenue_usd_m'][0]:,.0f}–{next_quarter['revenue_usd_m'][1]:,.0f}M",
             f"中值环比 {signed(pct_change(sum(next_quarter['revenue_usd_m']) / 2, revenue[-1]))} D"],
            # The release gives no quarterly margin. What it does give is a
            # revenue range and an expense range, and their midpoints imply one
            # -- so the implied figure is computed here and labelled D.
            ["non-GAAP 费用", f"${lo_exp:,.0f}–{hi_exp:,.0f}M",
             f"${actual_expense:,.1f}M D", against(actual_expense, lo_exp, hi_exp, lower_is_better=True),
             f"${next_quarter['non_gaap_expenses_usd_m'][0]:,.0f}–"
             f"{next_quarter['non_gaap_expenses_usd_m'][1]:,.0f}M",
             f"中值环比 {signed(pct_change(sum(next_quarter['non_gaap_expenses_usd_m']) / 2, actual_expense))} D"],
            ["non-GAAP 营业利润率", "指引未直接给出该季比率",
             f"{financials['non_gaap_operating_margin_pct'][-1]:.2f}% D", "—",
             f"隐含中点 {implied_next_margin:.2f}% D",
             f"较本季 {implied_next_margin - financials['non_gaap_operating_margin_pct'][-1]:+.1f}pp D"],
            ["non-GAAP EPS", f"${lo_eps:.2f}–{hi_eps:.2f}",
             f"${financials['non_gaap_eps_usd'][-1]:.2f}", against(financials["non_gaap_eps_usd"][-1], lo_eps, hi_eps),
             f"${next_quarter['non_gaap_eps_usd'][0]:.2f}–{next_quarter['non_gaap_eps_usd'][1]:.2f}",
             f"中值 ${sum(next_quarter['non_gaap_eps_usd']) / 2:.2f}"],
            ["GAAP EPS", f"${lo_gaap:.2f}–{hi_gaap:.2f}",
             f"${financials['gaap_eps_usd'][-1]:.2f}", gaap_verdict,
             f"${next_quarter['gaap_eps_usd'][0]:.2f}–{next_quarter['gaap_eps_usd'][1]:.2f}",
             story_or.get("gaap_eps_next_note", "—")],
            ["摊薄股数", f"{lo_sh:.0f}–{hi_sh:.0f}M",
             f"{financials['diluted_shares_m'][-1]:.3f}M",
             against(financials["diluted_shares_m"][-1], lo_sh, hi_sh),
             f"{next_quarter['diluted_shares_m'][0]:.0f}–{next_quarter['diluted_shares_m'][1]:.0f}M",
             "持平" if next_quarter["diluted_shares_m"] == [lo_sh, hi_sh] else
             f"中值{'上移' if sum(next_quarter['diluted_shares_m']) > lo_sh + hi_sh else '下移'}"],
        ]
        if actual_tax is not None:
            guide_rows.append(["non-GAAP 税率", f"{guided_tax:.1f}%", f"{actual_tax:.1f}%",
                               "符合" if actual_tax == guided_tax else ("低于指引" if actual_tax < guided_tax else "高于指引"),
                               f"{next_quarter['non_gaap_tax_rate_pct']:.1f}%",
                               story_or.get("tax_note", "—")])
    if full_year is not None:
        guide_rows.append([f"{full['fiscal_year']} 收入", "—", "—", "—",
                           f"${full_year['revenue_usd_m'][0]:,.0f}–{full_year['revenue_usd_m'][1]:,.0f}M",
                           (f"含脚注载明的 Ansys ${footnote['expected_ansys_revenue_usd_m'][-1]:,.0f}M"
                            if footnote is not None else "—")])
        eps_move = (middle(full_year["non_gaap_eps_usd"]) - middle(previous_year["non_gaap_eps_usd"])
                    if previous_year else None)
        guide_rows.append([f"{full['fiscal_year']} non-GAAP EPS", "—", "—", "—",
                           f"${full_year['non_gaap_eps_usd'][0]:.2f}–{full_year['non_gaap_eps_usd'][1]:.2f}",
                           (f"较上一次指引中值{'上调' if eps_move > 0 else '下调'} ${abs(eps_move):.2f} D"
                            if eps_move else "—")])
        guide_rows.append([f"{full['fiscal_year']} 自由现金流", "—", "—", "—",
                           f"约 ${full_year['free_cash_flow_usd_m']:,.0f}M",
                           f"经营现金流约 ${full_year['operating_cash_flow_usd_m']:,.0f}M、"
                           f"资本开支约 ${full_year['capex_usd_m']:,.0f}M"])

    tables = []
    if guide_rows:
        tables.append({
            "n": 0,
            "title": "本季兑现与下季／全年指引",
            "headers": ["指标", "本季原指引", "本季实际", "兑现", "新指引", "变化 / 备注"],
            "rows": guide_rows,
        })
    if entries:
        tables.append(threshold_table(0, "下季阈值与当前值（原单位）", entries, "current", "当前值"))
    tables += [
        {
            "n": 0,
            "title": f"{cn_count(len(periods))}季度收入、利润率与每股口径",
            "headers": ["期间", "公司口径", "收入", "收入 YoY", "GAAP 营业利润",
                        "GAAP 营业利润率", "调整后营业利润", "调整后营业利润率",
                        "GAAP EPS", "non-GAAP EPS", "摊薄股数"],
            "rows": quarterly_rows,
        },
        {
            "n": 0,
            "title": f"{cn_count(len(periods))}季度分部与非 GAAP 调整项",
            "headers": ["期间", "Design Automation 收入", "调整后营业利润", "调整后利润率",
                        "Design IP 收入", "调整后营业利润", "调整后利润率",
                        "收购摊销", "股权激励", "重组费用"],
            "rows": segment_rows,
        },
        {
            "n": 0,
            "title": f"{cn_count(len(backlog['quarters']))}季度 backlog 与资本配置",
            "headers": ["期间", "公司口径", "backlog", "其中 FSA", "FSA 占比",
                        "未来 12 个月可确认比例", "可确认额", "回购", "资本开支", "季度值为差分"],
            "rows": backlog_rows,
        },
        {
            "n": 0,
            "title": f"{geo_n}季度分地区与收入类型（持续经营口径）",
            "headers": ["期间", "总收入", "United States", "Europe", "Korea", "China",
                        "China 占比", "Other", "Time-based", "Upfront", "Maintenance & service"],
            "rows": geo_rows,
        },
        {
            "n": 0,
            "title": f"{ten}年年度记录（各年取该年 10-K 首次印出的数）",
            "headers": ["财年", "收入", "后被重述为", "GAAP 营业利润", "GAAP 营业利润率",
                        "收购摊销", "摊销占收入", "加回摊销后利润率", "摊薄股数", "GAAP EPS",
                        "回购", "经营现金流", "资本开支"],
            "rows": long_rows,
        },
        {**delivery_table, "n": 0},
        ai_capex_cycle_table(0),
    ]
    for offset, table in enumerate(tables):
        table["n"] = first_table + offset

    # ── headline, brief, notes ──────────────────────────────────────────────
    four = {"收入": delivery[0][1], "non-GAAP 费用": delivery[1][1],
            "non-GAAP EPS": delivery[3][1], "摊薄股数": delivery[4][1]}
    beat = [name for name, value in four.items() if value > 0]
    raised = []
    if full_year is not None and previous_year is not None:
        margin_now = ((middle(full_year["revenue_usd_m"]) - middle(full_year["non_gaap_expenses_usd_m"]))
                      / middle(full_year["revenue_usd_m"]))
        margin_before = ((middle(previous_year["revenue_usd_m"]) - middle(previous_year["non_gaap_expenses_usd_m"]))
                         / middle(previous_year["revenue_usd_m"]))
        for name, now, before in (
                ("收入", middle(full_year["revenue_usd_m"]), middle(previous_year["revenue_usd_m"])),
                ("利润率", margin_now, margin_before),
                ("EPS", middle(full_year["non_gaap_eps_usd"]), middle(previous_year["non_gaap_eps_usd"])),
                ("现金流", full_year["operating_cash_flow_usd_m"], previous_year["operating_cash_flow_usd_m"])):
            if now > before:
                raised.append(name)
    shares_yoy = pct_change(financials["diluted_shares_m"][-1], financials["diluted_shares_m"][-5])
    headline = (
        f"收入 US${revenue[-1]:,.0f}M、同比 {signed(financials['revenue_yoy_pct'][-1])}，"
        + (f"{joined(beat)}{cn_count(len(beat))}条指引全部优于中值" if len(beat) == 4 else
           f"{joined(beat)}优于指引中值" if beat else "四条指引都没做到中值")
        + (f"，公司同时上调 {full['fiscal_year']} 的{joined(raised)}" if raised else "")
        + "；"
        + f"但同一季里，收购摊销吃掉收入的 {amortization_share[-1]:.1f}%、"
        f"股数同比多出 {shares_yoy:.1f}%，于是 non-GAAP 净利同比 {signed(ni_yoy)} "
        f"落到每股{'只剩' if eps_yoy < ni_yoy else '为'} {signed(eps_yoy)}。"
    )
    amort_record = amortization_share[-1] > max(long_amort_share)
    brief = (
        '<h4>本季三条主线</h4><div class="takeaway-grid">'
        '<article><span>记录</span><b>收入是预测，EPS 是底线</b>'
        f'<p>{record_facts["finished"]} 季指引记录里，收入落在自己区间内 {record_facts["inside"]} 次，'
        f'non-GAAP EPS 却 {record_facts["eps_above"]} 次穿出上限。同一张表，两种性质。</p></article>'
        + ('<article><span>亮点</span><b>Design IP 重新转正</b>' if ip_turned else
           '<article><span>分部</span><b>Design IP</b>')
        + f'<p>US${ip_revenue[-1]:,.0f}M、同比 {signed(ip_yoy[-1])}；'
        f'分部利润率 {ip_margin[-1]:.1f}%，同比 {ip_margin[-1] - ip_margin[-5]:+.1f}pp。</p></article>'
        '<article><span>代价</span><b>摊销与股数同时变重</b>'
        f'<p>收购摊销占收入 {amortization_share[-1]:.1f}%'
        + (f"，{ten}年最高" if amort_record else "")
        + f'；股数同比 {signed(shares_yoy)}'
        + (f"，回购连着{cn_count(zero_run)}个财年为零" if zero_run and not resumed else "")
        + '。</p></article>'
        '</div>'
    )

    identity = []
    for index in range(len(record["quarters"])):
        rev_mid = (record["guide_revenue_lo_usd_m"][index] + record["guide_revenue_hi_usd_m"][index]) / 2
        exp_mid = (record["guide_non_gaap_expenses_lo_usd_m"][index]
                   + record["guide_non_gaap_expenses_hi_usd_m"][index]) / 2
        other = (record["guide_non_gaap_other_income_lo_usd_m"][index]
                 + record["guide_non_gaap_other_income_hi_usd_m"][index]) / 2
        shares = (record["guide_shares_lo_m"][index] + record["guide_shares_hi_m"][index]) / 2
        printed = (record["guide_non_gaap_eps_lo_usd"][index] + record["guide_non_gaap_eps_hi_usd"][index]) / 2
        identity.append(abs((rev_mid - exp_mid + other)
                            * (1 - record["guide_non_gaap_tax_rate_pct"][index] / 100) / shares - printed))
    worst = max(range(len(identity)), key=lambda i: identity[i])
    break_at = record["basis_break_at"]
    addback = record["basis_break_addback_usd_m"]
    restated = [(year, original - later) for year, original, later
                in zip(long_labels, long["revenue_usd_m"], long["restated_revenue_usd_m"])
                if later is not None and abs(original - later) >= 1]

    notes = [
        "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
        f"本页所有季度按自然年标注。Synopsys 财年 10 月底结束，故本页的 {period} 是截至 {period_end} 的季度，"
        f"公司自己称之为 {fiscal}；映射规则为公司 FY 的 Q1→上一自然年 Q4、Q2→Q1、Q3→Q2、Q4→Q3。"
        "不统一成一种约定，跨公司的资本开支对照表就会把不同的三个月放在一起比较。",
        f"第一节的指引兑现组图（Exhibit {refs['EX_REV_RANGE']['n']}–{refs['EX_SHARES_RANGE']['n']}）"
        "用的是同一批业绩 8-K：每份 EX-99.1 新闻稿的「Financial Targets」表同时给出下一季的收入区间、"
        "GAAP 与 non-GAAP 费用区间、非 GAAP 非经营项区间、非 GAAP 税率、摊薄股数区间与两条 EPS 区间；"
        "实际值取自随后一季 8-K 的合并损益表与分部调节表。",
        f"Exhibit {refs['EX_OI_LEGS']['n']} 的两条腿是恒等式而非估计：指引收入中值减指引费用中值隐含一个公司"
        "从不单独印出的非 GAAP 营业利润，实际值与它的差恰好等于收入腿加费用腿。实际非 GAAP 费用本身也不是估计，"
        "它等于实际收入减去每份新闻稿都印的「total adjusted segment operating income」。",
        "把五个指引中值代回「（收入 − 费用 + 非经营项）×（1 − 税率）÷ 股数」，能复现公司自己印出来的 "
        f"non-GAAP EPS 中值：{len(identity)} 季里 {sum(1 for gap in identity if gap <= 0.02)} 季误差在 US$0.02 以内、"
        f"{sum(1 for gap in identity if gap <= 0.06)} 季在 US$0.06 以内，最大的一次是 "
        f"{record['quarters'][worst]} 的 US${identity[worst]:.3f}。多数残差来自公司把区间端点四舍五入到分"
        "与把股数区间取整到百万股；早年几季更松，说明那时的 EPS 中值并不是用各项中值直接算出来的。"
        "这是本页把「指引隐含营业利润」当作公司自己的数来用的依据。",
        "公司在 2024-05-05 签约出售 Software Integrity 业务，并在截至 2024-04-30 的当季把它整体移入终止经营、"
        f"同时从分部结果中移除。因此 {record['quarters'][break_at]} 这一季的指引与实际不在同一口径上："
        "指引含该业务、实际不含。指引记录的水平图在该季打断点，本页不改写任何一端；"
        f"该季 10-Q 终止经营附注所载 Software Integrity 三个月收入 US${addback:,.1f}M 加回后"
        f"（US${record['actual_revenue_usd_m'][break_at] + addback:,.0f}M），实际值落回指引区间内、靠近上沿。"
        "同一季的 non-GAAP EPS 指引与实际同样跨口径，但公司未披露该业务的 non-GAAP 贡献，"
        "因此本页只对收入做这一步还原，不对 EPS 做。",
        "十年年度序列一律取该年 10-K 首次印出的数，即公司当年自己报出的口径。"
        + (" 与 ".join(year for year, _ in restated)
           + " 后来在 FY2024 10-K 中因同一笔剥离被重述（收入分别降 "
           + " 与 ".join(f"US${gap:,.0f}M" for _, gap in restated)
           + "），核对表把重述后的收入并列，图上不做追溯改写。" if restated else ""),
        "会计季 Q4 没有 10-Q，其分部、分地区与现金流量值均为财年数减去九个月数，两端都是申报值；"
        "核对表逐行标注哪些季是差分得来的。",
        "backlog 相关的三个数各有各的口径：总额与不可撤销 FSA 承诺是公司披露值（精度 US$0.1B），"
        "「未来 12 个月内可确认的比例」在申报原文里是对扣除 FSA 之后的 backlog 说的，"
        "因此本页的可确认额 =（总额 − FSA）× 该比例，为自算值。",
        "本页不发布剔除 Ansys 之后的季度 EDA 收入序列。公司不印 Ansys 的季度收入金额；10-Q 的收入分解附注"
        "只按产品组印占比"
        + (f"（本季 Ansys {values['ansys_share']}）" if ansys_split is not None else "")
        + "，只覆盖并入之后的几季，拉不出与本页其余序列并排的线；全年收入指引的脚注给的是预期口径。"
        + ("能复算的两处 —— 本季占比推导出的单季值与年度指引层面的并购与原生拆分 —— 分别写在第三节与单独成图。"
           if ansys_split is not None and fy_split else
           "能复算的本季占比推导出的单季值写在第三节。" if ansys_split is not None else
           "能复算的年度指引层面的并购与原生拆分单独成图。" if fy_split else ""),
        "本页只发布公司披露值、可复算的简单派生值，以及明确标注的市场预期；D 标记代表 Derived / 自算。",
        "市场预期一律标注为「市场预期」并给出取数时点，不写卖方机构名，也不发布评级、目标价或估值。",
    ]
    if story_or.get("not_tracked"):
        notes.append(told("not_tracked"))
    notes.append("业绩电话会文字稿仅链接官方 IR 与 SEC 托管版本，公开仓不复制原件或逐字内容。")

    return {
        "schema_version": "quarterly-dashboard/snps-v1",
        "page": {"slug": "snps", "language": "zh-CN"},
        "company": {
            "ticker": "SNPS",
            "name": "Synopsys",
            "group": "semiconductor_ai",
            "accounting_standard": "US GAAP",
        },
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · SNPS",
        "title": f"Synopsys (SNPS)：{period} 季报仪表盘",
        "subtitle": (
            f"截至 {period_end} · 发布 {release_date} · US GAAP · {AUDIT_WORDS[latest['audit_status']]} · "
            f"10 月制财年，本站按自然年季度标注：本页 {period} 即公司所称 {fiscal}"
        ),
        "headline": headline,
        "brief": brief,
        "source": (
            f'Source: <a href="{release["url"]}" rel="noopener">Synopsys {fiscal} '
            '业绩新闻稿（8-K EX-99.1）</a>'
            + (f"与截至 {period_end} 的 10-Q。" if filing is not None else "。")
        ),
        "source_url": release["url"],
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {
                "id": "settled",
                "title": "一、上季跟踪指标兑现了吗",
                "description": (
                    ("先结清上季设下的阈值，再看新数字。" if verdicts is not None else "")
                    + "公司每季在业绩新闻稿里给出下一季的"
                    "收入、GAAP 与 non-GAAP 费用、非经营项、税率、摊薄股数与两条 EPS —— "
                    "本站唯一一家把每股收益的每一个输入都指引出来的公司，"
                    f"所以「有没有做到」在这里有 {record_facts['finished']} 季的完整答案，且超额可以被拆开而无需任何估计。"
                ),
                "exhibits": settled_ex,
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": (
                    "两个分部各自的收入与利润率、GAAP 与 non-GAAP 之间那道由收购摊销撑开的裂口、"
                    "股数对每股口径的吞噬"
                    + ("，以及公司自己在指引脚注里给出的并购与原生拆分。" if fy_split_chart else "。")
                ),
                "exhibits": highlight_ex,
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": (
                    ("当前值离下季阈值还有多远，统一用「距阈值余量」口径"
                     + (f"；不接入的{cn_count(len(next_kpi['excluded']))}条也写在这里。"
                        if next_kpi.get("excluded") else "。"))
                    if next_kpi is not None else "本季没有设定下季阈值。"),
                "exhibits": next_ex,
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": (
                    f"SNPS 专属的常规序列：{ten}年收购摊销强度与它撑开的利润率裂口、"
                    f"{ten}年回购与股数、{cn_count(len(backlog['quarters']))}季 backlog 与它可确认的那一半，"
                    f"以及{geo_n}季地域结构。"
                ),
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": notes,
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
