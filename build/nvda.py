#!/usr/bin/env python3
"""Build the NVIDIA quarterly-results page.

Same four-part, chart-led shape as the other pages (上季兑现 → 本季重点 →
下季跟踪 → 长期常规), with section one built out the way TSMC's is, because
NVIDIA is the other company on this site that guides several numbers every
quarter in the same sentence structure: revenue ±2%, GAAP and non-GAAP gross
margin ±50bp, and GAAP and non-GAAP operating expenses as point numbers.

A roll edits ``series/nvda.json`` and nothing else. Every number the prose
prints is computed here from the series; what only one quarter has -- the
recast of the Data Center customer split, the call's explanation of the DSO
jump, the page's reading of it -- lives in period-stamped blocks read through
`board.stamped_block`, with the series' numbers as placeholders and the facts a
sentence rests on listed under ``requires``. A block stamped for another quarter
stops the build; a missing block leaves its part of the page out.

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
    cn_count,
    cn_ordinal,
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


STAGING_PATH = ROOT / "series" / "nvda.json"
DATA_DIR = ROOT / "data"

# The dollar band chart is drawn over a short window on purpose; see
# `guidance_delivery_charts`.
REVENUE_BAND_WINDOW = 8

AUDIT_WORDS = {"unaudited": "未审计", "audited": "已审计"}

# ── fixed history, named here and in the commit that introduced it ──────────
# The window this page drew before the record was backfilled to 2016. Section
# one says what that window hid, so its two ends are history, not data.
OLD_WINDOW = ("Q3 2020", "Q2 2026")
# The non-GAAP definition changed in Q1 2026 (FY2027 Q1) to include stock-based
# compensation.
SBC_BREAK = "Q1 2026"
# The market-platform presentation (Data Center / Edge Computing) starts here.
PLATFORM_SINCE = "FY2027 Q1"
# Arm acquisition termination charge: US$1.35B inside Q1 FY2023 GAAP operating
# expenses (CFO Commentary, acc 0001045810-22-000073).
ARM_QUARTER, ARM_CHARGE_USD_BN = "Q1 2022", 1.35
# Causes the prose names for dated episodes; the amounts come from the series.
YOY_LOW_CAUSE = {"Q1 2019": "游戏渠道去库存"}
EPISODE_CAUSE = {"Q2 2022": "2022 年游戏渠道去库存的存货计提"}
CRYPTO_MISSES = ("Q3 2018", "Q4 2018")


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100


def compact_period(period: str) -> str:
    """``'Q1 2026'`` → ``'Q1'26'``."""
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


def quarter_order(period: str) -> int:
    quarter, year = period.split()
    return int(year) * 4 + int(quarter[1]) - 1


def fiscal_long(label: str) -> str:
    """``'FY2027Q2'`` → ``'Q2 FY2027'``."""
    return f"{label[6:]} {label[:6]}"


def fiscal_short(label: str) -> str:
    """``'FY2027Q2'`` → ``'Q2 FY27'``."""
    return f"{label[6:]} FY{label[4:6]}"


def fiscal_spaced(label: str) -> str:
    """``'FY2027Q2'`` → ``'FY2027 Q2'``."""
    return f"{label[:6]} {label[6:]}"


def rounded(values: list[float | None], digits: int = 6) -> list[float | None]:
    # `+ 0.0` turns a negative zero into zero: "-0.0" is not a number anyone printed.
    return [None if value is None else round(value, digits) + 0.0 for value in values]


def leg_cell(value: float) -> str:
    return f"{round(value, 2) + 0.0:+.2f}B D"


def tens_times(ratio: float) -> str:
    """``73.7`` → ``七十多倍``; ``101.7`` → ``一百多倍``."""
    if ratio >= 20:
        tens = int(ratio) // 10 * 10
        return f"{cn_count(tens)}{'多' if ratio > tens else ''}倍"
    whole = int(ratio)
    return f"{cn_count(whole)}倍{'多' if ratio - whole >= 0.25 else ''}"


def decade_words(quarters: int) -> str:
    """How the prose names a window in years: 42 quarters → 十年."""
    return f"{cn_count(quarters // 4)}年"


def span_words(quarters: list[str]) -> str:
    """``['Q3 2024', 'Q4 2024']`` → ``'Q3–Q4 2024'``."""
    first, last = quarters[0], quarters[-1]
    if first == last:
        return first
    if first.split()[1] == last.split()[1]:
        return f"{first.split()[0]}–{last.split()[0]} {last.split()[1]}"
    return f"{first}–{last}"


def fiscal_groups(periods: list[str], fiscal_labels: list[str], chosen: list[str]) -> str:
    """``FY2026 四季（本页 Q1–Q4 2025）与 FY2027 两季（Q1–Q2 2026）``."""
    groups: list[tuple[str, list[str]]] = []
    for period, label in zip(periods, fiscal_labels):
        if period not in chosen:
            continue
        if groups and groups[-1][0] == label[:6]:
            groups[-1][1].append(period)
        else:
            groups.append((label[:6], [period]))
    return "与 ".join(f"{fy} {cn_count(len(qs))}季（{'本页 ' if i == 0 else ''}{span_words(qs)}）"
                    for i, (fy, qs) in enumerate(groups))


def moved(first: float, last: float, up: str = "升到", down: str = "降到", flat: str = "持平于") -> str:
    return up if last > first else down if last < first else flat


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


def release_source(staging: dict, fiscal: str) -> dict:
    """This quarter's own earnings release has to be among the sources."""
    wanted = f"NVIDIA {fiscal_long(fiscal)} 业绩新闻稿"
    entry = next((item for item in staging["sources"] if item["label"].startswith(wanted)), None)
    if entry is None:
        raise ValueError(f"series `sources` has no entry for the {fiscal_long(fiscal)} earnings "
                         "release: add it with the roll")
    return entry


def ends_at(block: dict, key: str, period: str) -> None:
    """A short series that carries its own quarter list must end on this quarter."""
    if block["quarters"][-1] != period:
        raise ValueError(f"series `{key}` ends at {block['quarters'][-1]!r}, not {period!r}: "
                         "append this quarter's value with the roll")


# ── section one: the guided record ──────────────────────────────────────────
SOURCE_8K = (
    "指引区间来自各季业绩 8-K 的 EX-99.1 新闻稿 Outlook 段；"
    "实际值来自随后一季 8-K 的合并损益表与 GAAP/non-GAAP 对账表。"
)


def guidance_delivery_charts(staging: dict, gm_line: float | None) -> tuple[list[dict], dict, dict]:
    """The full guided record for all three guided metrics, and what the beats are made of.

    NVIDIA guides revenue (±2%), both gross margins (±50bp) and both operating
    expense lines every quarter, so "did the quarter clear the company's own
    bar" has a long answer rather than an eight-quarter one -- and the answer
    differs sharply by metric, which is the whole reason for one chart per
    metric.

    The beat decomposition is an identity rather than an estimate. Guiding all
    three components implies an operating income the company never prints:

        implied non-GAAP OI = guided revenue × guided margin − guided opex

    and the distance from what was reported splits exactly three ways:

        actual − implied = (Ra − Rg)·mg  +  Ra·(ma − mg)  −  (Ea − Eg)

    Every term is a company-reported quarterly number or a company-published
    outlook number, so the split needs no estimate of any kind.
    """
    guide = staging["quarterly_guidance_history"]
    charges = staging["gross_margin_charges"]
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
    n_done = len(finished)
    # Every count these charts print is derived here, because the window has
    # moved more than once and each move silently invalidated a hand-typed
    # number in the copy below.
    rev_dev = {i: (revenue_actual[i] / revenue_guide[i] - 1) * 100 for i in finished}
    bands = {band[i] for i in finished}
    band_words = f"{bands.pop():.0f}%" if len(bands) == 1 else "区间半宽"
    rev_beat = sum(1 for i in finished if rev_dev[i] > band[i])
    rev_misses = [i for i in finished if rev_dev[i] < -band[i]]
    rev_worst = min(finished, key=lambda i: rev_dev[i])
    old_lo, old_hi = (quarters.index(q) for q in OLD_WINDOW)
    old_misses = [i for i in rev_misses if old_lo <= i <= old_hi]
    growth = revenue_actual[finished[-1]] / revenue_actual[finished[0]]

    gm_above = gm_narrow = 0
    gm_misses = []
    for i in finished:
        actual = margin_actual[i]
        if actual > margin_hi[i]:
            gm_above += 1
        elif actual < margin_lo[i]:
            gm_misses.append(i)
        if abs(actual - margin_guide[i]) <= margin_band[i]:
            gm_narrow += 1
    gm_dev = {i: margin_actual[i] - margin_guide[i] for i in finished}
    charged = {quarter: index for index, quarter in enumerate(charges["quarters"])}
    all_charged = all(quarters[i] in charged for i in gm_misses)
    old_gm = [i for i in gm_misses if old_lo <= i <= old_hi]
    added_gm = [i for i in gm_misses if i < old_lo]
    deep = [i for i in gm_misses if gm_dev[i] < -5]
    gm_band_words = f"±{margin_band[finished[-1]]:.1f}pp"
    gm_band_bp = f"±{guide['gm_band_bp'][finished[-1]]:.0f}bp"

    opex_mad = sum(
        abs(guide["actual_non_gaap_opex_usd_m"][i]
            / (guide["non_gaap_opex_guide_usd_bn"][i] * 1000) - 1) * 100
        for i in finished) / n_done

    # ── revenue ──────────────────────────────────────────────────────────────
    # The band is drawn over the last eight quarters only. On one linear dollar
    # axis the early bands collapse to a few pixels and the chart stops
    # answering its own question. The scale-free version of the same question --
    # distance from the guided midpoint, in percent -- carries the *whole*
    # record in the next chart, which is where the long-window reading belongs.
    window = slice(len(quarters) - REVENUE_BAND_WINDOW, len(quarters))
    revenue_band_chart = delivery_band(
        "EX_REV_RANGE", "收入", labels[window], revenue_lo[window], revenue_hi[window],
        revenue_actual[window],
        fmt="usd0", ylab="US$B", unit="US$B", venue="业绩发布",
        scope=f"（本图仅近 {REVENUE_BAND_WINDOW} 季）",
        src_extra=SOURCE_8K,
        extra_note=(
            f"<b>这张只画最近{cn_count(REVENUE_BAND_WINDOW)}季，不是数据缺失</b>："
            f"本页的指引记录一路回到 {quarters[0]}，"
            f"而收入在这段时间从 US${revenue_actual[finished[0]]:.1f}B 长到 "
            f"US${revenue_actual[finished[-1]]:.1f}B，{tens_times(growth)}的量级差放在一根线性美元轴上，"
            f"早年的 ±{band_words.rstrip('%')}% 区间会被压成几个像素，图就不再回答自己的问题了。"
            f"完整 {len(quarters)} 季的同一问题改用与量级无关的口径回答，见 Exhibit {{EX_REV_DEV}}。"
        ),
    )

    miss_run = [rev_worst]
    while miss_run[0] - 1 in rev_misses:
        miss_run.insert(0, miss_run[0] - 1)
    while miss_run[-1] + 1 in rev_misses:
        miss_run.append(miss_run[-1] + 1)
    revenue_dev_chart = midpoint_deviation(
        "EX_REV_DEV", "收入", quarters, revenue_lo, revenue_hi, revenue_actual,
        mode="pct", window=n_done, label=compact_period, bar_labels=False,
        src_extra=SOURCE_8K + "偏离为实际收入除以指引中值的自算值。",
        extra_note=(
            f"<b>这是全页最该先读的一张</b>：{n_done} 个已完结季里 {rev_beat} 季"
            f"高于指引中值 {band_words} 以上（也就是穿出区间上限），"
            + ("公司的收入指引在这个窗口里更接近底线而不是预测。" if rev_beat * 2 > n_done
               else "公司的收入指引在这个窗口里更像预测而不是底线。")
            + ((f"但它<b>不是</b>不可破的底线 —— <b>窗口拉到 {n_done} 季之后，"
                f"跌破下限的不止一季，而是 {len(rev_misses)} 季</b>："
                + "、".join(f"{labels[i]} {rev_dev[i]:+.1f}%" for i in rev_misses) + "。")
               if len(rev_misses) > 1 else "")
            + ((f"此前本页只画到 {labels[old_lo]} 起的 {old_hi - old_lo + 1} 季，"
                f"那扇窗口里只剩 {labels[old_misses[0]]} 一次，于是「唯一一次」这个说法成立；"
                "它成立靠的是窗口的左边界，不是这家公司的记录。")
               if len(old_misses) == 1 and len(rev_misses) > 1 else "")
            + ((f"而且最深的那次不是 {labels[old_misses[0]]}，是 {labels[rev_worst]} 的 "
                f"{rev_dev[rev_worst]:+.1f}% —— ")
               if len(old_misses) == 1 and rev_worst not in old_misses else "")
            + (("2018 年底加密货币矿卡需求塌方、渠道里堆着卖不掉的游戏卡，"
                f"公司连着{cn_count(len(miss_run))}季（{'、'.join(labels[i] for i in miss_run)}）"
                "没能守住自己给的下限。")
               if len(miss_run) > 1 and all(quarters[i] in CRYPTO_MISSES for i in miss_run) else "")
            + f"柱高在这里可比，因为口径是百分比，不受收入量级{tens_times(growth)}变化的影响。"
        ),
    )

    # ── what the beat is made of ─────────────────────────────────────────────
    revenue_leg, margin_leg, opex_leg, leg_quarters = [], [], [], []
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
        leg_quarters.append(index)
    leg_labels = [labels[index] for index in leg_quarters]

    total = [sum(legs) for legs in zip(revenue_leg, margin_leg, opex_leg)]
    misses = [k for k, value in enumerate(total) if value < 0]
    # "Margin-driven" means the margin leg is the most negative of the three, so
    # the shortfall cannot be blamed on demand.
    margin_driven = [
        k for k in misses
        if margin_leg[k] == min(revenue_leg[k], margin_leg[k], opex_leg[k])
    ]
    demand_driven = [k for k in misses if k not in margin_driven]
    below_band = [k for k in misses if leg_quarters[k] in rev_misses and margin_leg[k] < 0]
    held_band = [k for k in misses if leg_quarters[k] not in rev_misses and k in margin_driven]
    other = [k for k in misses if k not in below_band and k not in held_band
             and not (k in demand_driven and leg_quarters[k] in rev_misses)]
    charged_misses = [k for k in misses if quarters[leg_quarters[k]] in charged]

    def pair(k: int) -> str:
        return (f"{leg_labels[k]} 收入腿 {revenue_leg[k]:+.2f}B / "
                f"毛利率腿 {margin_leg[k]:+.2f}B")

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
        # Too many bars for one card to carry labels; the 原值 live in this
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
            f"而没能达到自身隐含营业利润的 {len(misses)} 季（{'、'.join(leg_labels[k] for k in misses)}）里，"
            + ("无一例外都是金色的毛利率腿塌得最深" if not demand_driven
               else f"{cn_count(len(margin_driven))}季是金色的毛利率腿塌得最深")
            + ((f"，而且{'每一季' if len(charged_misses) == len(misses) else cn_count(len(charged_misses)) + '季'}"
                "公司都在当季点名了计提（明细见 Exhibit {EX_GM_RANGE}）。")
               if charged_misses else "。")
            + "".join(
                f"<b>例外是 {leg_labels[k]}</b>：收入腿 {revenue_leg[k]:+.2f}B 比毛利率腿 "
                f"{margin_leg[k]:+.2f}B 更深 —— 那一季收入比指引中值低 "
                f"{abs(rev_dev[leg_quarters[k]]):.1f}%，是需求本身塌了。"
                for k in demand_driven if leg_quarters[k] in rev_misses)
            + (f"<b>按收入腿分{cn_count(sum(1 for group in (held_band, below_band, other) if group))}类</b>："
               + (f"{'、'.join(pair(k) for k in held_band)}，收入落在指引区间内或之上，"
                  "是毛利率腿独自把它们拉成负数；" if held_band else "")
               + (f"{'、'.join(pair(k) for k in below_band)}，收入本身也跌破了下限，"
                  "两条腿一起为负。" if below_band else "")
               + (f"另有 {'、'.join(pair(k) for k in other)}，毛利率腿不是最深的一条，"
                  "差额来自收入腿与费用腿。" if other else "")
               if misses else "")
            + ("换句话说，这家公司迄今为止的经营意外多半来自成本与计提，但需求并非无辜 —— "
               if below_band and len(margin_driven) * 2 > len(misses) else
               "换句话说，这家公司迄今为止的经营意外来自成本与计提，不是来自需求 —— "
               if not below_band else "")
            + ("<b>这与 TSM 页第一节的读数正好互补</b>：那边是指引从不被打破，"
               "这边是指引会被打破，"
               + ("但打破它的从来不是需求那条腿。" if not below_band and not demand_driven
                  else "而打破它的多半是毛利率那条腿。" if len(margin_driven) * 2 > len(misses)
                  else "打破它的腿各不相同。")
               if misses else "")
            + "<b>交互项归属：</b>收入与毛利率同时偏离时的交叉项按上式全部计入毛利率腿；"
            "调换拆解顺序会把它移到收入腿，两种拆法的合计完全相同。"
        ),
        "src_extra": SOURCE_8K + "三条腿均为自算，指引原值与实际原值见核对表。",
    }

    # ── gross margin ─────────────────────────────────────────────────────────
    def charge_words(i: int) -> str:
        k = charged[quarters[i]]
        amount = charges["charge_usd_m"][k]
        size = f"US${amount / 1000:.2f}B".replace("0B", "B") if amount >= 1000 else f"US${amount:,.0f}M"
        return f"{labels[i]} {size}（{charges['what'][k]}）"

    margin_band_chart = delivery_band(
        "EX_GM_RANGE", "non-GAAP 毛利率", labels, margin_lo, margin_hi, margin_actual,
        fmt="pct0", ylab="non-GAAP 毛利率", unit="%", venue="业绩发布",
        src_extra=(SOURCE_8K + "实际 non-GAAP 毛利率 = 对账表的 non-GAAP 毛利 ÷ 净收入 D。"
                   "计提金额取自各该季 CFO Commentary 的「Gross Margin」段。"),
        extra_note=(
            ("<b>和收入那条完全相反</b>：毛利率的指引大部分时候是<b>真预测</b>而不是底线 —— "
             if gm_narrow * 2 > n_done else "<b>和收入那条不同</b>：")
            + f"{gm_narrow} 季落在中值 {gm_band_bp} 的窄区间内，{gm_above} 季穿出上限。"
            + ((f"但它破起来极狠，而且<b>次数比本页此前写的多</b>：{len(gm_misses)} 次跌破下限，"
                + "、".join(f"{labels[i]} {gm_dev[i]:+.1f}pp" for i in gm_misses) + "。")
               if gm_misses else "")
            + ((f"此前本页写的是「{cn_count(len(old_gm))}次，且{cn_count(len(old_gm))}次都是一次性计提」—— "
                f"次数只在 {labels[old_lo]} 起的 {old_hi - old_lo + 1} 季窗口里对；"
                f"「都是计提」那半句拉到 {n_done} 季之后仍然成立：多出来的 "
                + " 与 ".join(labels[i] for i in added_gm)
                + "，公司同样在当季 CFO commentary 里点名了计提。"
                + f"{cn_count(len(gm_misses))}次跌破各自对应的计提是："
                + "、".join(charge_words(i) for i in gm_misses) + "。")
               if added_gm and all_charged else "")
            + ("这条线的形状本身就是本页的风险提示：这家公司的毛利率不会慢慢变坏，只会一次砸穿。"
               if gm_misses and all_charged else "")
        ),
    )
    margin_dev_chart = midpoint_deviation(
        "EX_GM_DEV", "non-GAAP 毛利率", quarters, margin_lo, margin_hi, margin_actual,
        mode="pp", window=n_done, label=compact_period, bar_labels=False,
        src_extra=(SOURCE_8K + "实际 non-GAAP 毛利率 = 对账表的 non-GAAP 毛利 ÷ 净收入 D；"
                   "偏离为实际值减指引中值的自算值。"),
        extra_note=(
            (f"把 Exhibit {{EX_GM_RANGE}} 的{cn_count(len(gm_misses))}次跌破放到同一根轴上量幅度："
             f"正常季度的柱几乎贴着零轴（区间只有 {gm_band_words}，公司命中率很高），"
             f"{cn_count(len(deep))}根深坑一眼可辨。" if gm_misses else "")
            + ((f"<b>本页据此把下季 non-GAAP 毛利率的警戒线设在 {gm_line:.1f}%</b> —— "
                f"不是因为 {margin_band[finished[-1]]:.1f}pp 的正常波动，而是因为一旦这条线明显下破，"
                "历史上都不是波动而是计提。")
               if gm_line is not None and gm_misses and all_charged else "")
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
    sbc_break = quarters.index(SBC_BREAK)
    opex_band_chart = delivery_band(
        "EX_OPEX_RANGE", "non-GAAP 营业费用", labels, opex_guide, opex_guide, opex_actual,
        fmt="usd1", ylab="US$B", unit="US$B", venue="业绩发布", point=True,
        break_at=sbc_break,
        break_label="口径变更：non-GAAP 起含股权激励费用",
        src_extra=SOURCE_8K + "费用指引为单点数，非区间。",
        extra_note=(
            "<b>和另外两条指引最大的不同是它没有宽度</b> —— "
            f"收入给 ±{band_words.rstrip('%')}%、毛利率给 {gm_band_bp}，"
            "费用只给一个数，所以这条线上不存在「区间内」这回事，只有高于或低于。"
            "菱形几乎粘在细线上，说明费用是这家公司最可预测的一条线；"
            "本图看的是<b>水平与斜率</b>，具体差多少见 Exhibit {EX_OPEX_DEV}。"
            f"<b>红色竖线是口径断点</b>：自 {labels[sbc_break]} 起 non-GAAP 不再剔除股权激励费用，"
            f"费用水平一次性抬高（{labels[sbc_break - 1]} US${opex_actual[sbc_break - 1]:.2f}B → "
            f"{labels[sbc_break]} US${opex_actual[sbc_break]:.2f}B），"
            "断点左右的<b>绝对水平不可直接连着读</b>；"
            "但该季的指引与实际同在新口径下给出与报出，所以指引与实际的<b>相对关系</b>不受影响。"
        ),
    )
    opex_dev_chart = midpoint_deviation(
        "EX_OPEX_DEV", "non-GAAP 营业费用", quarters, opex_guide, opex_guide, opex_actual,
        mode="pct", window=n_done, label=compact_period, bar_labels=False,
        src_extra=SOURCE_8K + "费用指引是单点数，偏离为实际除以该点的自算值。",
        extra_note=(
            "承接 Exhibit {EX_OPEX_RANGE}：那张画水平，这张只画差额。"
            "读法与另外两个指标相反：<b>负值才是好消息</b>（实际花得比承诺少）。"
            f"柱子长期贴近零轴，{n_done} 季的平均绝对偏离只有 {opex_mad:.1f}%。"
            "<b>这张图不受口径变更影响</b> —— 每一季的指引与实际都在同一口径下给出与报出，"
            "相除之后股权激励费用在分子分母里同时出现，"
            "所以这里没有 Exhibit {EX_OPEX_RANGE} 上那道断点。"
        ),
    )
    # The shared deviation chart opens with the reading that fits revenue and
    # margin ("positive = the guide was conservative"). For a cost line guided
    # as a point that sentence is wrong twice: positive means spending more
    # than promised, and it is not persistently positive.
    generic = "正值 = 高于指引区间的中值；长期为正说明公司指引偏保守，不是一连串意外。"
    assert opex_dev_chart["note"].startswith(generic)
    opex_dev_chart["note"] = "正值 = 实际费用高于指引。" + opex_dev_chart["note"][len(generic):]

    # Grouped by metric: each guided number's level chart is followed straight
    # away by its own deviation chart, so one metric is read through before the
    # next starts. Revenue's beat decomposition sits with revenue.
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
    leg_at = {index: k for k, index in enumerate(leg_quarters)}
    for index, quarter in enumerate(quarters):
        actual_revenue = guide["actual_revenue_usd_m"][index]
        done = actual_revenue is not None
        position = leg_at.get(index)
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
            leg_cell(revenue_leg[position]) if position is not None else "—",
            leg_cell(margin_leg[position]) if position is not None else "—",
            leg_cell(opex_leg[position]) if position is not None else "—",
        ])
    facts = {"gm_misses": [quarters[i] for i in gm_misses], "gm_dev": gm_dev, "labels": labels}
    return charts, table, facts


def expectation_chart(staging: dict, period: str, prior: str, fiscal: str,
                      consensus: dict, restated: dict, tax: dict) -> dict:
    """Where the GAAP and non-GAAP readings of the same quarter part company.

    The other section-one charts ask whether the quarter cleared NVIDIA's own
    bar. This asks whether it cleared the market's -- and then keeps going,
    because the more interesting fact is *where* the two accounting bases
    diverge. They agree almost exactly at the operating line and split only
    below it, which localises the entire distortion to one item.
    """
    current = restated["quarters"].index(period)
    before = restated["quarters"].index(prior)
    financials = staging["financials"]

    def step(key: str) -> float:
        return pct_change(restated[key][current], restated[key][before])

    rows = [
        ("营收 vs 市场预期", pct_change(financials["revenue_usd_m"][-1], consensus["revenue_usd_m"])),
        ("non-GAAP EPS vs 市场预期",
         pct_change(restated["non_gaap_eps_usd"][current], consensus["non_gaap_eps_usd"])),
        ("GAAP 营业利润 环比", step("gaap_operating_income_usd_m")),
        ("non-GAAP 营业利润 环比", step("non_gaap_operating_income_usd_m")),
        ("GAAP 净利 环比", step("gaap_net_income_usd_m")),
        ("non-GAAP 净利 环比", step("non_gaap_net_income_usd_m")),
        ("GAAP EPS 环比", step("gaap_eps_usd")),
        ("non-GAAP EPS 环比", step("non_gaap_eps_usd")),
    ]
    gains_now = restated["equity_securities_gains_usd_m"][current]
    gains_prior = restated["equity_securities_gains_usd_m"][before]
    gains_step = gains_now - gains_prior
    low_tax, high_tax = tax["current_pct"]
    # Strip the item from both quarters at the company's own guided tax range,
    # so the two ends of the band are the two ends of that range rather than an
    # assumption of this page's own.
    def ex_gains(index: int, rate: float) -> float:
        return (restated["gaap_net_income_usd_m"][index]
                - restated["equity_securities_gains_usd_m"][index] * (1 - rate / 100))
    ex_low = pct_change(ex_gains(current, low_tax), ex_gains(before, low_tax))
    ex_high = pct_change(ex_gains(current, high_tax), ex_gains(before, high_tax))
    gaap_eps, core_eps = step("gaap_eps_usd"), step("non_gaap_eps_usd")
    gaap_net, core_net = step("gaap_net_income_usd_m"), step("non_gaap_net_income_usd_m")
    gaap_oi, core_oi = step("gaap_operating_income_usd_m"), step("non_gaap_operating_income_usd_m")
    agree_at_oi = abs(gaap_oi - core_oi) < 1
    split_below = abs(gaap_net - core_net) > 5
    # Last quarter the item lifted GAAP above non-GAAP; this quarter it shrank.
    reversed_down = (gains_step < 0 and restated["gaap_net_income_usd_m"][before]
                     > restated["non_gaap_net_income_usd_m"][before])
    fy_short = f"FY{tax['fiscal_year'][-2:]}"
    return {
        "ref": "EX_EXPECTATION",
        "kind": "diverging_bars",
        "title": (
            ("两套口径在营业利润上几乎一致，到净利才分叉：" if agree_at_oi and split_below
             else "两套口径的环比：")
            + f"GAAP EPS 环比 {gaap_eps:+.1f}%，non-GAAP {core_eps:+.1f}%"
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
            ("<b>这张图的重点是第三、四根柱几乎等高，而第五根开始劈叉"
             + (" —— 而且这一季是往下劈。</b>" if gaap_net < core_net else "。</b>")
             if agree_at_oi and split_below else "")
            + f"营业利润两套口径的环比一个 {gaap_oi:+.1f}%、一个 {core_oi:+.1f}%，"
            + ("经营层面没有任何口径争议；分叉全部发生在营业利润<b>以下</b>，"
               if agree_at_oi else "")
            + ("来源仍是股权投资收益，但方向与上季相反：" if reversed_down
               else "来源是股权投资收益：")
            + f"本季 US${gains_now / 1000:.2f}B，上季 US${gains_prior / 1000:.2f}B，"
            f"环比<b>{'少' if gains_step < 0 else '多'}</b> US${abs(gains_step) / 1000:.2f}B 税前。"
            f"于是 GAAP 净利环比{'只有' if gaap_net < gaap_oi else '达到'} {gaap_net:+.1f}%，"
            f"而营业利润 {gaap_oi:+.1f}%。"
            f"按公司自己指引的 {fy_short} 税率 {low_tax:.0f}–{high_tax:.0f}% 把这一项从两季<b>同时</b>剔除，"
            f"GAAP 净利环比回到 {min(ex_low, ex_high):+.1f}–{max(ex_low, ex_high):+.1f}% D，"
            f"与 non-GAAP 的 {core_net:+.1f}% "
            + ("基本重合。" if min(ex_low, ex_high) - 1 <= core_net <= max(ex_low, ex_high) + 1
               else "仍有差距。")
            + ("<b>结论没变，只是这次它保护的是读者的下行判断而不是上行：</b>"
               "本季经营质量看 non-GAAP 营业利润与自由现金流，不看 GAAP 净利 —— "
               "上季这一项把 GAAP 抬高，本季把它压低，两次都不是经营。"
               if reversed_down else
               "本季经营质量看 non-GAAP 营业利润与自由现金流，不看 GAAP 净利。")
            + "前两根柱是对市场预期，其余六根是环比，两类对照并列于同一轴上，"
            "只用于比较方向与相对幅度。"
        ),
        "src_extra": (
            f"实际值来自 {period} 业绩 8-K；市场预期为财报前公开隐含一致预期"
            f"（{consensus['as_of']}），不具名。"
            f"本组{cn_count(len(restated['quarters']))}季的 non-GAAP 数全部取自同一份 "
            f"{fiscal_short(fiscal)} 对账表，已是公司重述后的口径（含股权激励费用）。"
            "剔除股权收益后的环比为按公司指引税率区间的自算值，不是公司披露的拆分。"
        ),
    }


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    fin = staging["financials"]
    dc = staging["market_platform_usd_m"]["data_center"]
    return [f"Revenue ${fin['revenue_usd_m'][-1] / 1000:.1f}B",
            f"Data Center {(dc[-1] / dc[-5] - 1) * 100:+.0f}%",
            f"Gross margin {fin['non_gaap_gross_margin_pct'][-1]:.1f}%"]


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    period, prior = periods[-1], periods[-2]
    period_end = staging["period_ends"][-1]
    fiscal = staging["fiscal_labels"][-1]
    latest = latest_block(staging, period=period, period_end=period_end)
    labels = [compact_period(p) for p in periods]
    n_window = len(periods)
    financials = staging["financials"]
    platform = staging["market_platform_usd_m"]
    dropped = staging["discontinued_dc_split_usd_m"]
    cash = staging["cash_flow_usd_m"]
    working = staging["working_capital"]
    supply = staging["total_supply_usd_bn"]
    concentration = staging["customer_concentration"]
    conversion = staging["fcf_conversion"]
    charges = staging["gross_margin_charges"]
    long = staging["long_history"]
    for key, block in (("total_supply_usd_bn", supply), ("fcf_conversion", conversion)):
        ends_at(block, key, period)
    if long["quarters"][-1] != period:
        raise ValueError(f"series `long_history` ends at {long['quarters'][-1]!r}, not {period!r}")

    # Blocks that describe one quarter; each one is None when absent.
    guidance = stamped_block(staging, "guidance", period)
    consensus = stamped_block(staging, "market_expectation", period)
    closure = stamped_block(staging, "followup_closure", period)
    next_kpi = stamped_block(staging, "next_kpi", period)
    mix = stamped_block(staging, "dc_customer_mix", period)
    restated = stamped_block(staging, "restated_comparatives", period)
    exposure = stamped_block(staging, "balance_sheet_exposure", period)
    capital = stamped_block(staging, "capital_return_usd_m", period)
    story = stamped_block(staging, "quarter_story", period)
    story_or = story or {}
    release_source(staging, fiscal)
    if capital is not None:
        ends_at(capital, "capital_return_usd_m", period)

    # The ten-year record is unpacked here rather than beside the routine charts
    # because section two reads from it too.
    long_labels = [compact_period(quarter) for quarter in long["quarters"]]
    long_n = len(long_labels)
    decade = decade_words(long_n)
    LONG_STEP = 4
    long_revenue = long["revenue_usd_m"]
    # The year before the record has no denominator for the first four
    # year-on-year cells. None, not zero -- a zero would draw a fabricated point
    # at the left edge of the growth line.
    long_revenue_yoy = [
        None if index < 4 else (long_revenue[index] / long_revenue[index - 4] - 1) * 100
        for index in range(long_n)
    ]

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
    qoq = pct_change(revenue[-1], revenue[-2])
    steps = [b - a for a, b in zip(long_revenue, long_revenue[1:])]
    step_now, step_prior = steps[-1], steps[-2]
    step_record = step_now == max(steps)
    yoy = financials["revenue_yoy_pct"]
    accel_run = 0
    while accel_run + 1 < long_n - 4 and \
            long_revenue_yoy[-1 - accel_run] > long_revenue_yoy[-2 - accel_run]:
        accel_run += 1

    total_supply = [
        inventory + commitments
        for inventory, commitments in zip(supply["inventory"],
                                          supply["supply_related_commitments"])
    ]

    next_q = guidance["next_quarter"] if guidance else None
    guide_history = staging["quarterly_guidance_history"]
    if next_q is not None:
        pending = guide_history["quarters"][-1]
        if pending != next_q["period"] or \
                guide_history["guide_revenue_usd_bn"][-1] != next_q["revenue_usd_bn"] or \
                guide_history["non_gaap_opex_guide_usd_bn"][-1] != next_q["non_gaap_opex_usd_bn"]:
            raise ValueError("guidance.next_quarter and the last row of quarterly_guidance_history "
                             "disagree: append the new outlook to the record with the roll")
        next_mid = next_q["revenue_usd_bn"]
        next_growth = pct_change(next_mid * 1000, revenue[-1])
        # The quarter a year before next quarter is three back from this one.
        next_yoy = pct_change(next_mid * 1000, revenue[-4])
        next_short = next_q["period"].split()[0]

    # ── thresholds: current values are computed, never typed ────────────────
    exposure_total = (exposure["guarantee_max_exposure_usd_bn"]["total"]
                      if exposure is not None else None)

    def current_of(entry: dict) -> float:
        ident = entry["id"]
        if ident == "dso":
            return working["dso_days"][-1]
        if ident == "fcf_conversion":
            return conversion["values_pct"][-1]
        if ident == "ng_gross_margin":
            return financials["non_gaap_gross_margin_pct"][-1]
        if ident == "guarantee":
            if exposure_total is None:
                raise KeyError("next_kpi `guarantee` needs this quarter's balance_sheet_exposure block")
            return exposure_total
        if ident == "top_customer":
            if concentration["quarters"][-1] != period:
                raise ValueError(f"customer_concentration has no value for {period} (a fiscal Q4 has "
                                 "none): drop the top_customer threshold or add the value")
            return float(concentration["largest_direct_customer_pct"][-1])
        raise KeyError(f"next_kpi entry {ident!r} has no series in this builder")

    kpi_entries = []
    if next_kpi is not None:
        for entry in next_kpi["quantified"]:
            if "current" in entry:
                raise ValueError(f"next_kpi entry {entry['id']!r} types a current value: it is "
                                 "computed from the series; delete it")
            kpi_entries.append({**entry, "current": current_of(entry)})
    gm_entry = next((e for e in kpi_entries if e["id"] == "ng_gross_margin"), None)

    # ── section one ──────────────────────────────────────────────────────────
    delivery_charts, delivery_table, record = guidance_delivery_charts(
        staging, gm_entry["threshold"] if gm_entry else None)
    current_index = guide_history["quarters"].index(period)
    guided_revenue = guide_history["guide_revenue_usd_bn"][current_index]
    guided_band = guide_history["revenue_band_pct"][current_index]
    guided_margin = guide_history["non_gaap_gm_guide_pct"][current_index]
    guided_gaap_margin = guide_history["gaap_gm_guide_pct"][current_index]
    gm_band = guide_history["gm_band_bp"][current_index] / 100
    guided_opex = guide_history["non_gaap_opex_guide_usd_bn"][current_index]
    guided_gaap_opex = guide_history["gaap_opex_guide_usd_bn"][current_index]
    actual_margin = guide_history["actual_non_gaap_gm_pct"][current_index]
    actual_opex = guide_history["actual_non_gaap_opex_usd_m"][current_index] / 1000
    gaap_opex = financials["gaap_opex_usd_m"][-1] / 1000
    implied_oi = guided_revenue * guided_margin / 100 - guided_opex
    actual_oi = guide_history["actual_non_gaap_operating_income_usd_m"][current_index] / 1000
    gm_delta = actual_margin - guided_margin
    gaap_gm_delta = financials["gaap_gross_margin_pct"][-1] - guided_gaap_margin
    prior_index = current_index - 1
    prior_gm_delta = (guide_history["actual_non_gaap_gm_pct"][prior_index]
                      - guide_history["non_gaap_gm_guide_pct"][prior_index])

    delivery = [
        ("收入", pct_change(revenue[-1] / 1000, guided_revenue)),
        ("non-GAAP 毛利率", gm_delta),
        ("GAAP 毛利率", gaap_gm_delta),
        # Spending less than promised is the safe side, so the sign is flipped
        # to keep "positive means better than guided" true across the whole bar.
        ("non-GAAP 营业费用", -pct_change(actual_opex, guided_opex)),
        ("隐含 non-GAAP 营业利润", pct_change(actual_oi, implied_oi)),
    ]
    better = sum(1 for _, value in delivery if value > 0)
    worse = sum(1 for _, value in delivery if value < 0)

    closure_chart = None
    if closure is not None:
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
            "note": closure["note"] + closure.get("note_tail", ""),
            "src_extra": (
                "问题清单来自上季本地分析稿的 follow-up；"
                f"验证结果依据 {period} 业绩 8-K、CFO commentary、10-Q 与业绩电话会。"
            ),
        }
        if mix is None and "{EX_RECAST}" in closure_chart["note"]:
            raise ValueError("followup_closure.note_tail points at the recast chart, "
                             "but this quarter has no dc_customer_mix block")

    opex_words = (f"比承诺多花 {abs(pct_change(actual_opex, guided_opex)):.1f}%，是<b>超支</b>季"
                  if actual_opex > guided_opex
                  else f"比承诺少花 {abs(pct_change(actual_opex, guided_opex)):.1f}%"
                  if actual_opex < guided_opex else "与承诺持平")
    no_gm_surprise = gm_delta < gm_band and gaap_gm_delta < gm_band
    delivery_chart = {
        "kind": "diverging_bars",
        "title": (
            ("本季全线优于自身指引：" if better == len(delivery)
             else "本季全线逊于自身指引：" if worse == len(delivery)
             else f"本季 {len(delivery)} 项里 {better} 项优于、{worse} 项逊于自身指引：")
            + f"收入 {signed(delivery[0][1])}，隐含营业利润 {signed(delivery[4][1])}"
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
            (f"超额几乎全部来自收入：收入比指引中值高 {delivery[0][1]:.1f}%，"
             f"两条毛利率合计只比指引高 {gm_delta:.2f}pp 与 {gaap_gm_delta:.2f}pp，"
             if no_gm_surprise and delivery[0][1] > 0 and gm_delta >= 0 and gaap_gm_delta >= 0 else
             f"收入较指引中值 {signed(delivery[0][1])}，两条毛利率较指引 {gm_delta:+.2f}pp 与 "
             f"{gaap_gm_delta:+.2f}pp，")
            + ("<b>本季依然没有毛利率上行惊喜</b>。" if no_gm_surprise and prior_gm_delta < gm_band
               else "<b>本季没有毛利率上行惊喜</b>。" if no_gm_surprise else "")
            + "费用一项已按「花得比承诺少为正」翻过符号，与其余各项方向统一；"
            f"本季实际 non-GAAP 费用 US${actual_opex:.2f}B，指引 US${guided_opex:.1f}B，{opex_words}。"
            "收入与费用为百分比，两条毛利率为百分点，两类单位并列于同一轴上，"
            "只用于比较方向与相对幅度；原值见核对表。"
            f"这{cn_count(len(delivery))}项的长窗口记录见 Exhibit {{EX_REV_DEV}} 起的指引兑现组图。"
        ),
        "src_extra": (
            f"指引为上季业绩 8-K Outlook 段所载 {period} 口径"
            f"（收入 US${guided_revenue:.1f}B ±{guided_band:.0f}%、"
            f"non-GAAP 毛利率 {guided_margin:.1f}% ±{gm_band * 100:.0f}bp、"
            f"non-GAAP 营业费用 US${guided_opex:.1f}B）；"
            "隐含营业利润为三者的自算组合，不是公司披露值。"
        ),
    }

    # ── section two ──────────────────────────────────────────────────────────
    yoy_values = [v for v in long_revenue_yoy if v is not None]
    yoy_low, yoy_high = min(yoy_values), max(yoy_values)
    low_at = long_revenue_yoy.index(yoy_low)
    high_at = long_revenue_yoy.index(yoy_high)
    negative_runs = sum(
        1 for i, v in enumerate(long_revenue_yoy)
        if v is not None and v < 0 and (long_revenue_yoy[i - 1] is None or long_revenue_yoy[i - 1] >= 0))
    window_rising = all(b > a for a, b in zip(revenue, revenue[1:]))
    re_accel = accel_run >= 2 and long_revenue_yoy[-1 - accel_run] < long_revenue_yoy[-2 - accel_run]
    revenue_chart = {
        "kind": "gs_bar",
        "title": (
            f"收入 US${revenue[-1] / 1000:.1f}B，同比 {signed(yoy[-1])}"
            + (f" 连续{cn_count(accel_run)}季{'重新' if re_accel else ''}加速" if accel_run >= 2 else "")
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
            f"环比 {signed(qoq)}，"
            f"环比<b>绝对</b>增量 US${step_now / 1000:.1f}B{' 再创纪录' if step_record else ''}"
            f"（上季 US${step_prior / 1000:.1f}B）；"
            f"同比增速从上季的 {yoy[-2]:.0f}% {moved(yoy[-2], yoy[-1])} {yoy[-1]:.0f}%"
            + (f"，是连续第{cn_ordinal(accel_run)}季加速。" if accel_run >= 2 else "。")
            + (f"<b>{decade}的窗口里这条同比线{cn_count(negative_runs)}次跌破零轴</b>："
               if negative_runs else f"<b>{decade}的窗口里这条同比线没有跌破过零轴</b>：")
            + f"最低 {yoy_low:.0f}%"
            f"（{long_labels[low_at]}"
            + (f"，{YOY_LOW_CAUSE[long['quarters'][low_at]]}" if long["quarters"][low_at] in YOY_LOW_CAUSE else "")
            + f"），最高 {yoy_high:.0f}%（{long_labels[high_at]}）。"
            + (f"{cn_count(n_window)}季的窗口只看得到最近这一段单边上行；" if window_rising else "")
            + f"前四格没有同比线，{int(long['quarters'][0].split()[1]) - 1} 年不在本记录内。"
            + ((f"{next_short} 指引中值 US${next_mid:.1f}B，隐含环比 {signed(next_growth)}"
                + ("，不减速。" if next_growth >= qoq and next_yoy >= yoy[-1] else
                   f"（本季 {signed(qoq)}）、隐含同比 {signed(next_yoy)}（本季 {signed(yoy[-1])}），"
                   + ("环比与同比都比本季慢。" if next_growth < qoq and next_yoy < yoy[-1]
                      else "两个口径一快一慢。")))
               if next_q is not None else "")
            + (f"较市场预期 US${consensus['revenue_usd_m'] / 1000:.1f}B "
               f"{'高' if revenue[-1] >= consensus['revenue_usd_m'] else '低'} "
               f"{abs(pct_change(revenue[-1], consensus['revenue_usd_m'])):.1f}%。"
               if consensus is not None else "")
        ),
        "src_extra": (
            f"{long_n} 季收入逐季读自各季业绩 8-K 的合并损益表三个月列（财年第四季取每年 2 月"
            "全年 8-K 里与全年列并排印出的 Q4 列），并与各财年 10-K 全年数逐年勾稽；"
            "同比为自算 D"
            + ("；市场预期为财报前公开隐含一致预期，不具名。" if consensus is not None else "。")
        ),
    }

    dc_yoy = pct_change(data_center[-1], data_center[YEAR_AGO])
    edge_yoy = pct_change(edge[-1], edge[YEAR_AGO])
    edge_share, edge_share_ago = edge[-1] / revenue[-1] * 100, edge[YEAR_AGO] / revenue[YEAR_AGO] * 100
    platform_chart = {
        "kind": "grouped_bars",
        "title": (
            f"Data Center US${data_center[-1] / 1000:.1f}B 占收入 "
            f"{data_center[-1] / revenue[-1] * 100:.1f}%"
            + ("，Edge Computing 是唯一增速平庸的一块" if edge_yoy < dc_yoy / 2 else "")
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
            f"同比 {signed(dc_yoy)}；"
            f"Edge Computing 环比 {signed(pct_change(edge[-1], edge[-2]))}、"
            f"同比 {signed(edge_yoy)}，"
            f"占收入{'已降到' if edge_share < edge_share_ago else '为'} {edge_share:.1f}%。"
            + (mix.get("platform_note_tail", "") if mix is not None else "")
        ),
        "src_extra": (
            f"市场平台口径为公司自 {PLATFORM_SINCE} 启用的呈现方式（Data Center 与 Edge Computing）；"
            "逐季读自各季 8-K 的 CFO commentary，Edge Computing = 总收入 − Data Center，"
            f"{cn_count(n_window)}季逐季核对相符 D。"
        ),
    }

    # How many thresholds stand on raw 10-Q items, recounted from the block.
    tenq = [e for e in kpi_entries if e.get("layer") == "10-Q"]
    eightk = [e for e in kpi_entries if e.get("layer") != "10-Q"]
    tenq_share = (f"{cn_count(len(kpi_entries))}条全部" if not eightk
                  else f"{cn_count(len(kpi_entries))}条里{cn_count(len(tenq))}条")
    values = {
        "tenq_share": tenq_share,
        "tenq_items": "、".join(e["layer_noun"] for e in tenq),
        "eightk_clause": ("；" + "、".join(e["layer_noun"] for e in eightk)
                          + f"{'一条' if len(eightk) == 1 else cn_count(len(eightk)) + '条'}取自 8-K 的 non-GAAP 口径"
                          if eightk else ""),
        "kpi_count": cn_count(len(kpi_entries)),
    }

    recast_chart = None
    mix_table = None
    if mix is not None:
        as_filed = mix["as_originally_filed"]
        filed_period = as_filed["period"]
        filed_index = mix["quarters"].index(filed_period)
        filed_fiscal = staging["fiscal_labels"][periods.index(filed_period)]

        def share(hyper: float, acie: float) -> float:
            return hyper / (hyper + acie) * 100
        filed_share = share(as_filed["hyperscale"], as_filed["acie"])
        recast_share = share(mix["hyperscale"][filed_index], mix["acie"][filed_index])
        acie_old = pct_change(mix["acie"][-1], as_filed["acie"])
        hyper_old = pct_change(mix["hyperscale"][-1], as_filed["hyperscale"])
        acie_new = pct_change(mix["acie"][-1], mix["acie"][filed_index])
        hyper_new = pct_change(mix["hyperscale"][-1], mix["hyperscale"][filed_index])
        flipped = (acie_old > hyper_old) != (acie_new > hyper_new)
        gap = [p for p in periods
               if quarter_order(mix["quarters"][0]) < quarter_order(p) < quarter_order(filed_period)
               and p not in mix["quarters"]]
        values.update({
            "filed_period": filed_period,
            "filed_share": f"{filed_share:.1f}%",
            "recast_share": f"{recast_share:.1f}%",
        })
        recast_chart = {
            "ref": "EX_RECAST",
            "kind": "grouped_bars",
            "title": (
                f"同一个 {filed_period}，两套口径给出"
                + ("相反的故事" if flipped else "不同的读数")
                + f"：Hyperscale 占 DC 由 {filed_share:.1f}% 被改写成 {recast_share:.1f}%"
            ),
            "xlabels": [f"{compact_period(filed_period)} 原披露", f"{compact_period(filed_period)} 重述后",
                        f"{compact_period(period)} 本季"],
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
                f"{acie_old:+.1f}%、Hyperscale {hyper_old:+.1f}%；"
                f"按重述后口径，两者变成 {acie_new:+.1f}% 与 {hyper_new:+.1f}%"
                + (" —— 「客户结构正在分散」与「重新集中」是同一组数字的两种读法。" if flipped else "。")
                + fill_story(mix.get("chart_note_tail", ""), values)
            ),
            "src_extra": (
                f"重述后的{cn_count(len(mix['quarters']))}季值印在 {fiscal_long(fiscal)} 10-Q 的 MD&A"
                "（Revenue by Market Platform）；"
                f"原披露值印在 {fiscal_long(filed_fiscal)} 10-Q。"
                + (f"{' 与 '.join(gap)} 在新口径下不存在于任何申报，"
                   "也无法由两个已披露数相减得到，本页不做拼接。" if gap else "")
            ),
        }
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
        mix_table.insert(filed_index + 1, [
            f"{filed_period}（原披露）",
            f"US${as_filed['hyperscale'] / 1000:.2f}B",
            f"US${as_filed['acie'] / 1000:.2f}B",
            f"{filed_share:.1f}% D",
            f"US${(as_filed['hyperscale'] + as_filed['acie']) / 1000:.2f}B",
            f"{fiscal_long(filed_fiscal)} 10-Q 原口径",
        ])

    accounting_chart = None
    if restated is not None:
        cur = restated["quarters"].index(period)
        before = restated["quarters"].index(prior)
        gains_step = (restated["equity_securities_gains_usd_m"][cur]
                      - restated["equity_securities_gains_usd_m"][before])
        ni_step = pct_change(restated["gaap_net_income_usd_m"][cur], restated["gaap_net_income_usd_m"][before])
        ng_step = pct_change(restated["non_gaap_net_income_usd_m"][cur],
                             restated["non_gaap_net_income_usd_m"][before])
        oi_step = pct_change(restated["gaap_operating_income_usd_m"][cur],
                             restated["gaap_operating_income_usd_m"][before])
        was_above = (restated["gaap_net_income_usd_m"][before]
                     > restated["non_gaap_net_income_usd_m"][before])
        order = sorted(range(len(restated["quarters"])), key=lambda i: quarter_order(restated["quarters"][i]))
        accounting_chart = {
            "kind": "grouped_bars",
            # Titles are injected unescaped and reused verbatim in the card's
            # aria-label, so they stay plain text; emphasis belongs in the note.
            "title": (
                ("GAAP 净利环比几乎没动，而营业利润涨了近两成"
                 if abs(ni_step) < 5 and 17.5 <= oi_step < 20 else
                 f"GAAP 净利环比 {ni_step:+.1f}%，营业利润 {oi_step:+.1f}%")
                + f" —— 差额是股权投资收益{'少' if gains_step < 0 else '多'}了 "
                f"US${abs(gains_step) / 1000:.1f}B"
            ),
            "xlabels": [restated["quarters"][i] for i in order],
            "groups": [
                {"name": "GAAP 净利", "color": "NAVY",
                 "values": [restated["gaap_net_income_usd_m"][i] / 1000 for i in order]},
                {"name": "non-GAAP 净利", "color": "MBLUE",
                 "values": [restated["non_gaap_net_income_usd_m"][i] / 1000 for i in order]},
                {"name": "其中：股权投资收益（税前）", "color": "GOLD",
                 "values": [restated["equity_securities_gains_usd_m"][i] / 1000 for i in order]},
            ],
            "bar_labels": True,
            "fmt": "usd1",
            "label_fmt": "usd1",
            "ylab": "US$B",
            "note": (
                "金色柱是税前股权投资收益。"
                + (f"上季它把 GAAP 净利抬到 non-GAAP 之上，本季回落 US${abs(gains_step) / 1000:.1f}B，"
                   if was_above and gains_step < 0 else
                   f"本季它{'回落' if gains_step < 0 else '增加'} US${abs(gains_step) / 1000:.1f}B，")
                + f"于是 GAAP 净利环比{'只有' if ni_step < ng_step else ''} {ni_step:+.1f}%，"
                f"而 non-GAAP 净利 {ng_step:+.1f}%。"
                "<b>这一项把利润表与 AI 一级/二级市场的资产价格绑在了一起</b> —— "
                "上行期放大利润，回落期同样放大，两个方向都不是经营。"
                + ("百分比拆解见 Exhibit {EX_EXPECTATION}。" if consensus is not None else "")
            ),
            "src_extra": restated["note"],
        }

    # Whether "highest in the record" is true is measured, not remembered: gross
    # margin is 74.98 this quarter against 75.00 two quarters ago, a gap that a
    # one-decimal read-through cannot see.
    long_gross = long["gaap_gross_margin_pct"]
    long_operating = long["gaap_operating_margin_pct"]
    gross_is_high = long_gross[-1] == max(long_gross)
    operating_is_high = long_operating[-1] == max(long_operating)
    trough_at = long_operating.index(min(long_operating))
    recent = max((q for q in charges["quarters"] if q in long["quarters"]), key=quarter_order)
    recent_at = long["quarters"].index(recent)
    recent_charge = charges["charge_usd_m"][charges["quarters"].index(recent)]
    after = long_gross[recent_at:]
    rises = 0
    while rises + 1 < len(after) and after[rises + 1] > after[rises]:
        rises += 1
    rest = after[rises + 1:]
    peak_at = long_gross.index(max(long_gross))
    window_start = long["quarters"].index(periods[0])
    gm_outlook = ""
    if story and story.get("gm_outlook") and next_q is not None:
        gm_outlook = fill_story(story["gm_outlook"], {
            "next_q": next_short,
            "next_gm": f"{next_q['non_gaap_gross_margin_pct']:.1f}%",
            "gm_now": f"{financials['non_gaap_gross_margin_pct'][-1]:.1f}%",
        })
    margin_level_chart = {
        "ref": "EX_MARGIN_LEVEL",
        "kind": "lines",
        "title": (
            f"GAAP 毛利率 {financials['gaap_gross_margin_pct'][-1]:.1f}%、营业利润率 "
            f"{financials['gaap_operating_margin_pct'][-1]:.1f}%，"
            + (f"两条都是{decade}新高"
               if (gross_is_high and operating_is_high)
               else f"营业利润率是{decade}新高，毛利率不是"
               if operating_is_high
               else f"毛利率是{decade}新高，营业利润率不是"
               if gross_is_high
               else f"两条都还没回到{decade}高点")
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
            (f"最深的坑与最近的坑不是一回事：{long_labels[trough_at]} 的 "
             f"{min(long_operating):.0f}% 是 {EPISODE_CAUSE[long['quarters'][trough_at]]}，"
             f"{long_labels[recent_at]} 的那个是 H20 出口管制的 US${recent_charge / 1000:.1f}B 计提，"
             "两次都是一次性、非经营性；"
             if long["quarters"][trough_at] in EPISODE_CAUSE and "H20" in
             charges["what"][charges["quarters"].index(recent)] and trough_at != recent_at else "")
            + ((f"此后{cn_count(rises)}季毛利率逐季修复，" if not rest else
                f"此后毛利率{cn_count(rises)}季修复到 {after[rises]:.1f}%、"
                + (f"随后{cn_count(len(rest))}季停在 {min(rest):.1f}%–{max(rest):.1f}%，"
                   if f"{min(rest):.1f}" != f"{max(rest):.1f}" else
                   f"随后{cn_count(len(rest))}季为 {rest[0]:.1f}%，"))
               if rises else "")
            + f"营业利润率已抬到 {long_operating[-1]:.1f}%"
            + (f"，是这 {long_n} 季的最高。" if operating_is_high else "。")
            + ((("<b>毛利率不是</b>：本季" if operating_is_high else "毛利率本季")
                + f" {long_gross[-1]:.1f}%，"
                f"而{decade}高点是 {long_labels[peak_at]} 的 {max(long_gross):.1f}%"
                + ((f" —— <b>{cn_count(n_window)}季的窗口看不到这件事</b>，因为那个高点就落在窗口的前"
                    f"{'一' if window_start - peak_at == 1 else cn_count(window_start - peak_at)}格。")
                   if 0 < window_start - peak_at <= 4 else "。"))
               if not gross_is_high else "")
            + ("两条线之间的距离在收窄，差额就是营业杠杆（见下一节的费用强度）。"
               if long["opex_intensity_pct"][-1] < long["opex_intensity_pct"][YEAR_AGO] else "")
            + "<b>本图用 GAAP 口径画水平</b>，因为 GAAP 的定义在整段窗口内没变过。"
            + gm_outlook
            + "逐季指引区间与兑现记录见 Exhibit {EX_GM_RANGE}。"
        ),
        "src_extra": "毛利率与营业利润率 = 各季 8-K 合并损益表的毛利 / 营业利益 ÷ 净收入 D。",
    }

    fcf_step = pct_change(cash["free_cash_flow"][-1], cash["free_cash_flow"][-2])
    ocf_step = pct_change(cash["operating_cash_flow"][-1], cash["operating_cash_flow"][-2])
    receivable_step = working["accounts_receivable_usd_m"][-1] - working["accounts_receivable_usd_m"][-2]
    dso_moves = [b - a for a, b in zip(working["dso_days"], working["dso_days"][1:])]
    fcf_kpi = next((e for e in kpi_entries if e["id"] == "fcf_conversion"), None)
    notes_issued = exposure.get("senior_notes_issued") if exposure is not None else None
    cash_quality_chart = {
        "ref": "EX_CASH_QUALITY",
        "kind": "bar_line_dual",
        "title": (
            f"自由现金流环比 {fcf_step:+.0f}%，"
            f"占收入由 {fcf_intensity[-2]:.0f}% {moved(fcf_intensity[-2], fcf_intensity[-1], '升到', '掉到')} "
            f"{fcf_intensity[-1]:.0f}%"
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
            story_or.get("cash_quality_lead", "")
            + f"经营现金流 US${cash['operating_cash_flow'][-1] / 1000:.1f}B（环比 {ocf_step:+.0f}%）、"
            f"自由现金流 US${cash['free_cash_flow'][-1] / 1000:.1f}B，"
            + (f"而同期收入还在环比 {qoq:+.0f}%。" if fcf_step < 0 < qoq else f"同期收入环比 {qoq:+.0f}%。")
            + ((f"应收账款一项本季就占用了 US${receivable_step / 1000:.1f}B，" if fcf_step < 0 else
                f"应收账款本季增加 US${receivable_step / 1000:.1f}B，") if receivable_step > 0 else "")
            + f"DSO 由 {working['dso_days'][-2]:.1f} 天{moved(working['dso_days'][-2], working['dso_days'][-1])} "
            f"{working['dso_days'][-1]:.1f} 天"
            + (" —— " + story_or["dso_reason"] if story_or.get("dso_reason") else "。")
            + ((f"同一季仍然回购加分红 US${capital['total'][-1] / 1000:.1f}B，"
                f"相当于当季自由现金流的 {capital['total'][-1] / cash['free_cash_flow'][-1] * 100:.0f}%"
                + (f"，并在 {notes_issued['month']} 月发行 US${notes_issued['usd_m'] / 1000:.0f}B 优先无担保票据"
                   f"（{notes_issued['tranches']} 只券）。" if notes_issued else "。"))
               if capital is not None else "")
            + ("<b>右轴的占比线是本页要跟踪的那件事</b>；第三节的阈值换用另一个分母 —— "
               "FCF / non-GAAP 净利。" if fcf_kpi is not None else "")
        ),
        "src_extra": (
            "经营现金流与自由现金流为公司披露值（FCF 按公司定义已扣除资本支出与租赁本金）；"
            "应收账款与回购分红取自 10-Q 的资产负债表与现金流量表；占比为自算 D。"
        ),
    }

    exposure_chart = None
    if exposure is not None:
        commitments = exposure["supply_and_capacity_commitments_usd_bn"]
        guarantee = exposure["guarantee_max_exposure_usd_bn"]
        land_now = guarantee["land_power_shell_ai_clouds_current"]
        land_prev = guarantee["land_power_shell_ai_clouds_prior_fy_end"]
        if abs(land_now / land_prev - 1) > 0.01:
            raise ValueError("balance_sheet_exposure.guarantee_note says the land/power/shell "
                             "guarantee is flat; the data no longer says so")
        exposure_chart = {
            "kind": "grouped_bars",
            "title": (
                f"供应与产能承诺单季由 US${commitments['prior_quarter']:.0f}B "
                f"{moved(commitments['prior_quarter'], commitments['current'])} "
                f"US${commitments['current']:.0f}B，"
                f"另有 US${guarantee['total']:.1f}B 表外担保"
            ),
            "xlabels": ["供应与产能承诺", "承诺总额", "担保最大总敞口", "长期债务", "非上市 + 上市股权证券"],
            "groups": [
                {"name": period, "color": "NAVY", "values": [
                    commitments["current"],
                    exposure["total_future_commitments_usd_bn"],
                    guarantee["total"],
                    exposure["long_term_debt_usd_m"]["current"] / 1000,
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
                + (f"担保最大总敞口 US${guarantee['total']:.1f}B 里有 "
                   f"US${guarantee['sb_energy']:.0f}B 是本季新增的单一一笔。" if "sb_energy" in guarantee else "")
                + fill_story(exposure.get("guarantee_note", ""), {
                    "land_now": f"US${land_now:.3f}B", "land_prev": f"US${land_prev:.3f}B"})
            ),
            "src_extra": exposure["note"],
        }

    # ── section three ────────────────────────────────────────────────────────
    derived = [p for p, v in zip(periods, financials["non_gaap_net_income_usd_m"]) if v is None]
    printed = [p for p in periods if p not in derived]
    if not derived and "{derived" in financials["non_gaap_basis_note"]:
        raise ValueError("financials.non_gaap_basis_note still describes self-derived quarters, "
                         "but none are left in the window: rewrite the note")
    basis_note = fill_story(financials["non_gaap_basis_note"], {
        "window_words": cn_count(n_window),
        "printed_groups": fiscal_groups(periods, staging["fiscal_labels"], printed),
        "derived_groups": fiscal_groups(periods, staging["fiscal_labels"], derived) if derived else "",
        "derived_span": span_words(derived) if derived else "",
        "derived_count": cn_count(len(derived)),
    })
    dso_note = fill_story(working["dso_note"], {"window_words": cn_count(n_window)})
    if story and story.get("dso_printed_note"):
        dso_note += fill_story(story["dso_printed_note"], {"dso_printed": f"{story['dso_printed_days']:.0f}"})
    missing_q4 = [p for p, label in zip(periods, staging["fiscal_labels"])
                  if label.endswith("Q4") and p not in concentration["quarters"]]
    if not set(missing_q4) <= set(concentration["missing_quarters"]):
        raise ValueError("customer_concentration.missing_quarters (and its note) do not name every "
                         f"fiscal Q4 in the window without a value: {missing_q4}")
    tracked = {
        "dso": (labels, working["dso_days"], "f1", "天", "DSO", dso_note),
        "fcf_conversion": (
            [compact_period(q) for q in conversion["quarters"]],
            conversion["values_pct"], "pct0", "转化率", "FCF / non-GAAP 净利", conversion["note"]),
        "ng_gross_margin": (
            labels, financials["non_gaap_gross_margin_pct"], "pct1", "毛利率", "non-GAAP 毛利率",
            basis_note),
        "top_customer": (
            [compact_period(q) for q in concentration["quarters"]],
            [float(v) for v in concentration["largest_direct_customer_pct"]],
            "pct0", "占总收入", "最大单一直接客户", concentration["note"]),
    }

    next_charts = []
    threshold_tbl = None
    if next_kpi is not None:
        table_only = set(next_kpi["table_only"])
        breached = [e for e in kpi_entries
                    if headroom(e["direction"], e["threshold"], e["current"]) < 0]
        margins = {e["id"]: headroom(e["direction"], e["threshold"], e["current"]) for e in kpi_entries}
        values.update({
            "fcf_conversion_now": f"{conversion['values_pct'][-1]:.0f}%",
            "fcf_conversion_line": (f"{fcf_kpi['threshold']:.0f}%" if fcf_kpi else ""),
        })
        dso_kpi = next((e for e in kpi_entries if e["id"] == "dso"), None)
        dso_move = dso_moves[-1]
        headroom_chart = headroom_exhibit(
            (f"下季 {len(kpi_entries)} 条量化阈值："
             + (f"{len(breached)} 条已经越线" if breached else "全部仍在安全侧")),
            kpi_entries,
            "current",
            (
                "正值 = 仍在安全侧。"
                + "".join(fill_story(e["breach_note"], values) if e.get("breach_note")
                          else f"<b>「{e['metric']}」已经越线</b>，余量 {margins[e['id']]:+.1f}%。"
                          for e in breached)
                + ((f"DSO {dso_kpi['current']:.1f} 天离 {dso_kpi['threshold']:.0f} 天的行动线"
                    + ("还有余量" if margins["dso"] > 0 else "已经越过")
                    + (f"，但已经比上季多了 {dso_move:.1f} 天" if dso_move > 0 else "")
                    + (f"，是这{cn_count(n_window)}季最大的单季跳升" if dso_move > 0 and dso_move == max(dso_moves)
                       else "")
                    + "。")
                   if dso_kpi is not None else "")
                + fill_story(next_kpi.get("retired_lead", ""), values)
                + fill_story(next_kpi.get("retired", ""), values)
            ),
            src_extra=(
                f"阈值为本地研究设定，不是公司指引；当前值为 {period} 实际。"
                + next_kpi.get("excluded", "")
            ),
        )
        headroom_chart["ref"] = "EX_HEADROOM"
        next_charts.append(headroom_chart)
        for entry in kpi_entries:
            if entry["metric"] in table_only:
                continue
            # A KPI with no series is a page defect, not something to skip
            # quietly: an older version dropped it from the section and left no
            # trace anywhere that it had done so.
            if entry["id"] not in tracked:
                raise KeyError(
                    f"KPI {entry['metric']!r} has no series in `tracked` and is not declared "
                    "table-only; add the series or add it to next_kpi.table_only"
                )
            xlabels, series_values, fmt, ylab, actual_name, extra = tracked[entry["id"]]
            side = "上方" if entry["direction"] == "up" else "下方"
            chart = threshold_exhibit(
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
                    f"余量 {margins[entry['id']]:+.1f}%。"
                    + extra
                ),
                src_extra=(
                    "实际值来自各季业绩 8-K、CFO commentary 与 10-Q；"
                    "阈值为本地研究设定，不是公司指引。"
                ),
            )
            next_charts.append(chart)

    # ── section four ─────────────────────────────────────────────────────────
    # Every quarter the operating margin fell ten points or more in one step,
    # grouped into episodes, and how long each took to get back to where it
    # was the quarter before the fall.
    drops = [i for i in range(1, long_n) if long_operating[i] - long_operating[i - 1] <= -10]
    episodes: list[list[int]] = []
    for i in drops:
        if episodes and i == episodes[-1][-1] + 1:
            episodes[-1].append(i)
        else:
            episodes.append([i])
    recoveries = []
    for episode in episodes:
        before_level = long_operating[episode[0] - 1]
        regain = next((j for j in range(episode[-1] + 1, long_n) if long_operating[j] >= before_level), None)
        if regain is None:
            recoveries.append(None)
            continue
        low = min(range(episode[0], regain), key=lambda j: long_operating[j])
        recoveries.append(regain - low)
    crisis = next((e for e in episodes if trough_at in e or trough_at - 1 in e), None)
    crisis_before = long_operating[crisis[0] - 1] if crisis else None
    long_margin_chart = {
        "kind": "lines",
        "title": (
            f"{long_labels[0]} 起 {long_n} 季的毛利率与营业利润率："
            + (f"{cn_count(len(drops))}个季度单季掉 10pp 以上，" if drops else "")
            + f"营业利润率从 {long_operating[0]:.0f}% 抬到 {long_operating[-1]:.0f}%"
        ),
        "xlabels": long_labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": "GAAP 毛利率", "values": long["gaap_gross_margin_pct"], "color": "NAVY"},
            {"name": "GAAP 营业利润率", "values": long_operating, "color": "MBLUE"},
        ],
        "fmt": "pct0",
        "yfmt": "pct0",
        "label_fmt": "pct0",
        "end_label": True,
        "ylab": "占净收入比",
        "note": (
            ("两条线的形状说明这家公司的利润率不是缓慢磨损型："
             f"营业利润率单季掉 10pp 以上的有{cn_count(len(drops))}个季度"
             f"（{'、'.join(long_labels[i] for i in drops)}），每一次都是一步砸下去"
             + ("；从谷底回到砸之前的水平，"
                + (f"{cn_count(len(episodes))}轮分别用了 "
                   + "、".join(str(r) for r in recoveries) + " 个季度。"
                   if len(episodes) > 1 else f"用了 {recoveries[0]} 个季度。")
                if all(r is not None for r in recoveries) else "。")
             if drops else "")
            + ("其中 2022 年那一轮"
               + (f"（{compact_period(ARM_QUARTER)} 的 Arm 交易终止费用，随后游戏渠道去库存的存货计提）"
                  if ARM_QUARTER in [long["quarters"][i] for i in crisis] else "游戏渠道去库存")
               + f"把营业利润率从 {crisis_before:.0f}% 打到 {long_operating[trough_at]:.0f}%，"
               "2025 年 H20 计提又打掉一次。"
               if crisis and long["quarters"][trough_at] in EPISODE_CAUSE else "")
            + "<b>结构性的部分是营业利润率与毛利率之间的距离在收窄</b> —— "
            f"费用强度从 {long['opex_intensity_pct'][0]:.0f}% 降到 "
            f"{long['opex_intensity_pct'][-1]:.0f}%（见下一张），"
            "所以同样的毛利率今天能落下更多营业利润。"
            + fill_story(long["provenance"], {"long_quarters": str(long_n)})
        ),
        "src_extra": (
            f"{long_n} 季逐季读自各季业绩 8-K 的合并损益表三个月列"
            "（财年第四季取每年 2 月全年 8-K 里与全年列并排印出的 Q4 列），"
            "并与各财年 10-K 全年数逐年勾稽；"
            "毛利率 = 毛利 ÷ 净收入，营业利润率 = 营业利益 ÷ 净收入，均为自算 D。"
        ),
    }

    intensity = long["opex_intensity_pct"]
    peak_i = intensity.index(max(intensity))
    low_i = intensity.index(min(intensity))
    arm_i = long["quarters"].index(ARM_QUARTER) if ARM_QUARTER in long["quarters"] else None
    opex_yoy = pct_change(financials["gaap_opex_usd_m"][-1], financials["gaap_opex_usd_m"][YEAR_AGO])
    opex_yoy_prior = pct_change(financials["gaap_opex_usd_m"][-2], financials["gaap_opex_usd_m"][YEAR_AGO - 1])
    opex_intensity_chart = {
        "kind": "gs_line",
        "title": (
            f"费用强度 {long_n} 季从 {intensity[0]:.1f}% 降到 "
            f"{intensity[-1]:.1f}%，是营业杠杆的全部来源"
        ),
        "xlabels": long_labels,
        "xstep": LONG_STEP,
        "values": intensity,
        "legend": "营业费用 / 净收入（GAAP）",
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "占净收入比",
        "note": (
            f"峰值 {intensity[peak_i]:.1f}%（{long_labels[peak_i]}"
            + ("，含 Arm 交易终止的一次性费用）" if peak_i == arm_i else
               f"，收入跌到 US${long_revenue[peak_i] / 1000:.1f}B 的那一季；"
               f"Arm 交易终止的 US${ARM_CHARGE_USD_BN:.2f}B 一次性费用在 {long_labels[arm_i]}，"
               f"当季 {intensity[arm_i]:.1f}%）" if arm_i is not None else "）")
            + f"，最低 {intensity[low_i]:.1f}%（{'本季' if low_i == long_n - 1 else long_labels[low_i]}）。"
            + ("<b>这条线本季继续下行</b>，" if intensity[-1] < intensity[-2] else "")
            + ((("但" if intensity[-1] < intensity[-2] else "")
                + f"分子的斜率正在变陡：GAAP 营业费用同比 {opex_yoy:+.0f}%（上季 {opex_yoy_prior:+.0f}%），"
                f"只是分母更陡（收入同比 {yoy[-1]:+.0f}%）；一旦收入增速回落，这条线会先反应。")
               if opex_yoy > opex_yoy_prior and yoy[-1] > opex_yoy else "")
            + "分子分母同为 GAAP 口径，不与 non-GAAP 费用混用。"
        ),
        "src_extra": "营业费用与净收入逐季读自各季业绩 8-K 合并损益表；比值为自算 D。",
    }

    commitments_now = supply["supply_related_commitments"][-1]
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
            f"而同期表外的供应与产能承诺是它的{tens_times(commitments_now * 1000 / capex_like[-1])}，见下一张。"
            + ((f"前两组柱本季同时掉头（经营现金流 {ocf_step:+.0f}%），"
                "原因在营运资金不在盈利，拆解见 Exhibit {EX_CASH_QUALITY}。")
               if ocf_step < 0 and fcf_step < 0 else "现金流的拆解见 Exhibit {EX_CASH_QUALITY}。")
        ),
        "src_extra": (
            "经营现金流与自由现金流为公司披露值（FCF 按公司定义已扣除资本支出与租赁本金）；"
            "第三组为两者之差 D，因此同时含资本支出与租赁本金，不等同狭义 capex。"
        ),
    }

    h20 = next((q for q, what in zip(charges["quarters"], charges["what"]) if "H20" in what), None)
    commit_step = supply["supply_related_commitments"][-1] - supply["supply_related_commitments"][-2]
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
            f"US${commitments_now:.1f}B，"
            f"本季单季{'增加' if commit_step >= 0 else '减少'} US${abs(commit_step):.0f}B。"
            "锁仓既是需求可见度，也是押注错误时的放大器"
            + ((f" —— {compact_period(h20)} 的 H20 计提就是同一台放大器反向运转的结果，"
                f"在 Exhibit {{EX_GM_RANGE}} 上是那根 {record['gm_dev'][guide_history['quarters'].index(h20)]:+.1f}pp 的深坑。")
               if h20 in record["gm_misses"] else "。")
            + f"<b>本图只有{cn_count(len(supply['quarters']))}季</b>：更早的季度未以同一口径披露，本页不做回溯拼接。"
            + supply["note"]
        ),
        "src_extra": (
            "存货为各季资产负债表原值；供应与产能承诺为公司在 10-Q 与业绩电话会披露的口径；"
            "合计为自算 D。"
        ),
    }

    # ── assemble ─────────────────────────────────────────────────────────────
    # Section one settles what last quarter left and what the company guided;
    # the market's consensus is neither, so the chart that reads the quarter
    # against it sits in section two beside the GAAP / non-GAAP split it
    # explains (the report's 「盈利质量」 conclusion), the way TSM's page does.
    settled_charts = ([closure_chart] if closure_chart else []) + [delivery_chart] + delivery_charts
    market_chart = (
        [expectation_chart(staging, period, prior, fiscal, consensus, restated, guidance["tax_rate"])]
        if consensus is not None and restated is not None and guidance is not None else [])
    highlights = ([revenue_chart, platform_chart]
                  + ([recast_chart] if recast_chart else [])
                  + ([accounting_chart] if accounting_chart else [])
                  + market_chart
                  + [margin_level_chart, cash_quality_chart]
                  + ([exposure_chart] if exposure_chart else []))
    routine = [long_margin_chart, opex_intensity_chart, cash_chart, supply_chart]

    numbered = number_exhibits(settled_charts + highlights + next_charts + routine)
    ref_numbers = {ex["ref"]: ex["n"] for ex in numbered if ex.get("ref")}
    exhibits = resolve_exhibit_refs(numbered)
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
    for index, p in enumerate(periods):
        non_gaap_ni = financials["non_gaap_net_income_usd_m"][index]
        financial_table.append([
            p,
            f"US${revenue[index] / 1000:.2f}B",
            f"{yoy[index]:.1f}%",
            f"{financials['gaap_gross_margin_pct'][index]:.2f}% D",
            f"{financials['non_gaap_gross_margin_pct'][index]:.2f}% D",
            f"{financials['gaap_operating_margin_pct'][index]:.2f}% D",
            f"US${financials['gaap_operating_income_usd_m'][index] / 1000:.2f}B",
            f"US${financials['non_gaap_operating_income_usd_m'][index] / 1000:.2f}B",
            (f"US${non_gaap_ni / 1000:.2f}B" if non_gaap_ni is not None else "—"),
        ])
        largest = None
        if p in concentration["quarters"]:
            largest = concentration["largest_direct_customer_pct"][concentration["quarters"].index(p)]
        platform_table.append([
            p,
            f"US${data_center[index] / 1000:.2f}B",
            f"{data_center[index] / revenue[index] * 100:.1f}% D",
            f"US${edge[index] / 1000:.2f}B D",
            (f"{largest:.0f}%" if largest is not None else "—"),
        ])
        cash_table.append([
            p,
            f"US${cash['operating_cash_flow'][index] / 1000:.2f}B",
            f"US${cash['free_cash_flow'][index] / 1000:.2f}B",
            f"US${capex_like[index] / 1000:.2f}B D",
            f"{fcf_intensity[index]:.1f}% D",
            f"{working['dso_days'][index]:.1f}天 D",
            f"US${working['accounts_receivable_usd_m'][index] / 1000:.2f}B",
            f"US${working['inventories_usd_m'][index] / 1000:.2f}B",
        ])

    dropped_table = [
        [quarter,
         f"US${compute / 1000:.1f}B",
         f"US${networking / 1000:.1f}B",
         f"{networking / (compute + networking) * 100:.1f}% D"]
        for quarter, compute, networking in zip(
            dropped["quarters"], dropped["compute"], dropped["networking"])
    ]

    def inside(actual: float, mid: float, half: float) -> str:
        return "区间内" if abs(actual - mid) <= half else "高于上限" if actual > mid else "低于下限"

    def revised(new: float, old: float, digits: int = 1) -> str:
        step = round(new, digits) - round(old, digits)
        return (f"上修 {abs(step):.{digits}f}pp" if step > 0 else
                f"下修 {abs(step):.{digits}f}pp" if step < 0 else "持平")

    guide_table = None
    if next_q is not None:
        q, nq = period.split()[0], next_q["period"].split()[0]
        gaap_opex_gap = pct_change(gaap_opex, guided_gaap_opex)
        ng_opex_gap = pct_change(actual_opex, guided_opex)
        tax = guidance["tax_rate"]
        ng_cut = next_q["non_gaap_gross_margin_pct"] < guided_margin
        guide_rows = [
            ["收入", f"US${guided_revenue:.1f}B ±{guided_band:.0f}%", f"US${revenue[-1] / 1000:.2f}B",
             f"{'高于' if revenue[-1] / 1000 >= guided_revenue else '低于'}中值 "
             f"{abs(pct_change(revenue[-1] / 1000, guided_revenue)):.1f}% D",
             f"US${next_mid:.1f}B ±{next_q['revenue_band_pct']:.0f}%",
             f"中值环比 {signed(next_growth)} D"],
            ["GAAP 毛利率", f"{guided_gaap_margin:.1f}% ±{gm_band * 100:.0f}bp",
             f"{financials['gaap_gross_margin_pct'][-1]:.2f}% D",
             inside(financials["gaap_gross_margin_pct"][-1], guided_gaap_margin, gm_band),
             f"{next_q['gaap_gross_margin_pct']:.1f}% ±{next_q['gross_margin_band_bp']:.0f}bp",
             revised(next_q["gaap_gross_margin_pct"], guided_gaap_margin)],
            ["non-GAAP 毛利率", f"{guided_margin:.1f}% ±{gm_band * 100:.0f}bp", f"{actual_margin:.2f}% D",
             inside(actual_margin, guided_margin, gm_band),
             f"{next_q['non_gaap_gross_margin_pct']:.1f}% ±{next_q['gross_margin_band_bp']:.0f}bp",
             revised(next_q["non_gaap_gross_margin_pct"], guided_margin)
             + (f"，{story_or['gm_cut_reason']}" if ng_cut and story_or.get("gm_cut_reason") else "")],
            ["GAAP 营业费用",
             f"US${guided_gaap_opex:.1f}B",
             f"US${gaap_opex:.2f}B",
             f"{'低于' if gaap_opex_gap < 0 else '高于'}指引 {abs(gaap_opex_gap):.1f}% D",
             f"US${next_q['gaap_opex_usd_bn']:.1f}B",
             f"中值环比 {signed(pct_change(next_q['gaap_opex_usd_bn'], gaap_opex))} D"],
            ["non-GAAP 营业费用", f"US${guided_opex:.1f}B", f"US${actual_opex:.2f}B",
             f"{'低于' if ng_opex_gap < 0 else '高于'}指引 {abs(ng_opex_gap):.1f}% D",
             f"US${next_q['non_gaap_opex_usd_bn']:.1f}B",
             f"中值环比 {signed(pct_change(next_q['non_gaap_opex_usd_bn'], actual_opex))} D"],
            ["FY 税率",
             f"{tax['previous_pct'][0]:.0f}–{tax['previous_pct'][1]:.0f}%", "—", "—",
             f"{tax['current_pct'][0]:.0f}–{tax['current_pct'][1]:.0f}%",
             "重申" if tax["current_pct"] == tax["previous_pct"] else "调整"],
        ]
        if story_or.get("china_row"):
            guide_rows.append(list(story_or["china_row"]))
        guide_table = {
            "title": f"{period} 兑现与 {next_q['period']} 指引",
            "headers": ["指标", f"{q} 原指引", f"{q} 实际", "兑现", f"{nq} 新指引", "变化 / 备注"],
            "rows": guide_rows,
        }

    # The compute / networking split stopped after its last quarter; while that
    # quarter is still the newest one, it has not stopped yet.
    frozen_at = dropped["quarters"][-1]
    discontinued = frozen_at != period
    frozen_next = periods[periods.index(frozen_at) + 1] if frozen_at in periods[:-1] else None
    window_words = cn_count(n_window)
    specs = (
        ([guide_table] if guide_table else [])
        + (["THRESHOLDS"] if next_kpi is not None else [])
        + [
            {
                "title": f"{window_words}季度收入与利润率",
                "headers": ["期间", "收入", "收入 YoY", "GAAP 毛利率", "non-GAAP 毛利率",
                            "GAAP 营业利润率", "GAAP 营业利润", "non-GAAP 营业利润",
                            "non-GAAP 净利"],
                "rows": financial_table,
            },
            {
                "title": f"{window_words}季度市场平台与客户集中度",
                "headers": ["期间", "Data Center", "占收入", "Edge Computing",
                            "最大单一直接客户占总收入"],
                "rows": platform_table,
            },
        ]
        + ([{
            "title": "Data Center 客户类型拆分：重述前后",
            "headers": ["期间", "Hyperscale", "ACIE", "Hyperscale 占 DC", "Data Center 合计", "口径"],
            "rows": mix_table,
        }] if mix_table else [])
        + [
            {
                "title": ("已停止披露：" if discontinued else "") + "Data Center 的 compute / networking 拆分",
                "headers": ["期间", "DC Compute", "DC Networking", "Networking 占 DC"],
                "rows": dropped_table,
            },
            {
                "title": f"{window_words}季度现金流与营运资金",
                "headers": ["期间", "经营现金流", "自由现金流", "资本支出及租赁本金",
                            "FCF / 收入", "DSO", "应收账款", "存货"],
                "rows": cash_table,
            },
            "DELIVERY",
            "CAPEX",
        ]
    )
    tables = []
    for offset, spec in enumerate(specs):
        n = next_table_number + offset
        if spec == "THRESHOLDS":
            tables.append(threshold_table(n, "下季阈值与当前值（原单位）", kpi_entries, "current", "当前值"))
        elif spec == "DELIVERY":
            tables.append({**delivery_table, "n": n})
        elif spec == "CAPEX":
            tables.append(ai_capex_cycle_table(n))
        else:
            tables.append({"n": n, **spec})

    cards = (
        (fill_story(story["brief_cards"], {
            "accel_run": cn_ordinal(accel_run),
            "revenue_yoy_whole": f"{yoy[-1]:.0f}%",
            "revenue_step": f"US${step_now / 1000:.1f}B",
            "next_q": next_short,
            "next_mid_whole": f"US${next_mid:.0f}B",
            "next_qoq": signed(next_growth),
            "fcf_share_prev": f"{fcf_intensity[-2]:.0f}%",
            "fcf_share_now": f"{fcf_intensity[-1]:.0f}%",
            "dso_now": f"{working['dso_days'][-1]:.1f}",
            "returned": f"US${capital['total'][-1] / 1000:.1f}B",
        }) if story and story.get("brief_cards") else
            '<article><span>收入</span><b>本季收入</b>'
            f'<p>US${revenue[-1] / 1000:.1f}B，同比 {yoy[-1]:.0f}%，环比 {signed(qoq)}。</p></article>')
        + (fill_story(mix["brief_card"], values) if mix is not None and mix.get("brief_card") else "")
    )
    brief = (
        f'<h4>本季{"三条" if cards.count("<article>") == 3 else ""}主线</h4><div class="takeaway-grid">'
        + cards + '</div>'
    )
    facts = {
        "revenue_step_record": step_record,
        "fcf_fell": fcf_step < 0,
        "dso_rose": working["dso_days"][-1] > working["dso_days"][-2],
        "commitments_rose": (exposure is not None and
                             exposure["supply_and_capacity_commitments_usd_bn"]["current"]
                             > exposure["supply_and_capacity_commitments_usd_bn"]["prior_quarter"]),
        "yoy_accelerating": accel_run >= 2,
        "fcf_share_halved": fcf_intensity[-1] <= fcf_intensity[-2] / 2,
        "gm_guide_cut": next_q is not None and next_q["non_gaap_gross_margin_pct"] < guided_margin,
        "recast_this_quarter": mix is not None,
        "dso_matches_print": (story is None or "dso_printed_days" not in story
                              or round(working["dso_days"][-1]) == story["dso_printed_days"]),
    }
    require(story, facts, "quarter_story")
    if story and story.get("brief_cards") and capital is None:
        raise ValueError("quarter_story.brief_cards names the capital returned; "
                         "this quarter has no capital_return_usd_m block")
    headline = (
        fill_story(story["headline"], {
            "revenue": f"US${revenue[-1] / 1000:.1f}B",
            "revenue_yoy": signed(yoy[-1]),
            "revenue_step": f"US${step_now / 1000:.1f}B",
            "fcf_qoq": f"{fcf_step:+.0f}%",
            "dso_prev": f"{working['dso_days'][-2]:.1f}",
            "dso_now": f"{working['dso_days'][-1]:.1f}",
            "commit_prev": f"US${exposure['supply_and_capacity_commitments_usd_bn']['prior_quarter']:.0f}B",
            "commit_now": f"US${exposure['supply_and_capacity_commitments_usd_bn']['current']:.0f}B",
            "guarantee_total": f"US${exposure['guarantee_max_exposure_usd_bn']['total']:.1f}B",
        }) if story and story.get("headline") else
        f"收入 US${revenue[-1] / 1000:.1f}B、同比 {signed(yoy[-1])}，"
        f"环比绝对增量 US${step_now / 1000:.1f}B{'，再创纪录' if step_record else ''}；"
        f"自由现金流环比 {fcf_step:+.0f}%，DSO {working['dso_days'][-1]:.1f} 天。"
    )

    notes = [
        "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
        f"本页所有季度按自然年标注。NVIDIA 财年 1 月底结束，故本页的 {period} 是截至 {period_end} 的季度，"
        f"公司自己称之为 {fiscal_spaced(fiscal)}；不统一成一种约定，跨公司的资本开支对照表就会把不同的三个月放在一起比较。",
    ]
    if "EX_HEADROOM" in ref_numbers:
        notes.append(f"Exhibit {ref_numbers['EX_HEADROOM']} 与其后各图的阈值是本地研究设定，不是公司指引，"
                     "也不构成评级或投资建议；「距阈值余量」统一为正值代表安全侧。")
    notes += [
        f"第一节的指引兑现组图（Exhibit {ref_numbers['EX_REV_RANGE']}–{ref_numbers['EX_OPEX_DEV']}）"
        "用的是同一批业绩 8-K：每份新闻稿的 Outlook 段同时给出下一季的收入区间（±2%）、"
        "GAAP 与 non-GAAP 毛利率区间（±50bp）以及两条营业费用的单点指引，"
        "实际值取自随后一季 8-K 的合并损益表与 GAAP/non-GAAP 对账表。",
        f"Exhibit {ref_numbers['EX_OI_LEGS']} 的三条腿是恒等式而非估计：公司同时指引收入、毛利率与费用，"
        "三者隐含一个它从不印出来的营业利润，实际值与它的差恰好等于三条腿之和。"
        "收入与毛利率同时偏离时的交叉项按该式全部计入毛利率腿，调换拆解顺序会把它移到收入腿，两种拆法的合计相同。",
        f"自 {SBC_BREAK} 起公司的 non-GAAP 口径不再剔除股权激励费用。"
        f"本页{window_words}季的 non-GAAP 毛利率、营业费用与营业利润一律为重述后口径："
        + (f"其中 {printed[0]}–{printed[-1]} {cn_count(len(printed))}季为公司印出值，"
           f"{' 与 '.join(derived)} {cn_count(len(derived))}季公司从未按新口径印出，"
           "本页按同一机械规则自算（原口径值加减当季印在对账表上的股权激励费用），"
           "该规则在公司印出的四个季度上逐百万精确复现。"
           "non-GAAP 净利与每股收益不适用该规则——非 GAAP 调整的所得税影响换了算法——"
           f"故那{cn_count(len(derived))}季留空"
           + (f"，第三节的现金转化率图因此只有{cn_count(len(conversion['quarters']))}季。"
              if fcf_kpi is not None and fcf_kpi["metric"] not in next_kpi["table_only"] else "。")
           if derived else f"{window_words}季均为公司印出值。"),
        "指引兑现各图逐季比较的是当季指引与当季实际，两者始终处在同一口径下，不受 non-GAAP 口径变更影响；"
        "受影响的只有费用的绝对水平，图上已标出断点。",
        "长期序列一律用 GAAP 口径，因为 GAAP 的定义在整个窗口内没有变过；"
        "把两种 non-GAAP 口径接成一条线会在变更处砸出纯定义性的落差。",
    ]
    if mix is not None and mix.get("page_note"):
        notes.append(mix["page_note"])
    if discontinued:
        notes.append(
            f"公司自{'本季' if frozen_next == period else ' ' + (frozen_next or '') + ' '}起不再披露 Data Center 内部的 "
            "compute / networking 拆分，业绩 8-K、CFO commentary 与 10-Q 三处都没有；"
            f"该序列冻结在 {frozen_at}，收在核对表里，不做外推。")
    notes += [
        "单一最大直接客户占总收入的比重逐季读自各季 10-Q 的 Concentration of Revenue 附注三个月列。"
        "两个财年第四季没有季度值：10-K 只印全年，而公司自己说明客户字母代号不跨期可比，"
        "全年减前九个月既没有确定的被减数，四舍五入也会把结果撑成约 5pp 宽的区间。本页留空，不推算。",
        "自由现金流为公司披露值，按公司定义已扣除资本支出与租赁本金；本页的「资本支出及租赁本金」"
        "是经营现金流与自由现金流之差，因此同时含两者，不等同狭义 capex。",
    ]
    if exposure is not None and exposure.get("page_note"):
        notes.append(exposure["page_note"])
    notes.append("本页只发布公司披露值、可复算的简单派生值，以及明确标注的市场预期；D 标记代表 Derived / 自算。")
    notes.append("市场预期一律标注为「市场预期」并给出取数时点，不写卖方机构名，也不发布评级、目标价或估值。"
                 + (consensus.get("page_note", "") if consensus is not None else ""))
    if guidance is not None and guidance.get("call_only", {}).get("page_note"):
        notes.append(guidance["call_only"]["page_note"])
    notes.append("业绩电话会文字稿仅链接官方 IR 与 SEC 托管版本，公开仓不复制原件或逐字内容。")

    source_url = staging["latest"]["source_url"]
    return {
        "schema_version": "quarterly-dashboard/nvda-v1",
        "page": {"slug": "nvda", "language": "zh-CN"},
        "company": {
            "ticker": "NVDA",
            "name": "NVIDIA",
            "group": "semiconductor_ai",
            "accounting_standard": "US GAAP",
        },
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · NVDA",
        "title": f"NVIDIA (NVDA)：{period} 季报仪表盘",
        "subtitle": (
            f"截至 {period_end} · 发布 {latest['release_date']} · US GAAP · "
            f"{AUDIT_WORDS[latest['audit_status']]} · "
            f"1 月制财年，本站按自然年季度标注：本页 {period} 即公司所称 {fiscal_spaced(fiscal)}"
        ),
        "headline": headline,
        "brief": brief,
        # The IR landing page for quarterly results cannot be linked from this
        # payload: `payload_guard` rejects any string matching /inf[a-z]{0,2}/ as
        # a formatted infinity, and `financial-info` trips it. The per-release IR
        # permalink and the SEC archive copies say the same thing and pass.
        "source": (
            f'Source: <a href="{source_url}" rel="noopener">NVIDIA Investor Relations</a>'
            f"（{fiscal_long(fiscal)} earnings release、CFO commentary、业绩 8-K 与 10-Q）。"
        ),
        "source_url": source_url,
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {
                "id": "settled",
                "title": "一、上季跟踪指标兑现了吗",
                "description": (
                    "先看上季留的问题闭环了几条、这一季对公司自己的指引兑现到什么程度，再谈本季。"
                    "公司每季给三个数——收入、两条毛利率、两条营业费用——"
                    "本节按指标逐个给出完整记录，收入那一组把「超出自身指引」拆成收入、毛利率与费用三条腿。"
                ),
                "exhibits": settled_ex,
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": (
                    "、".join(["收入的二阶导", "市场平台构成"]
                             + (["被重述掉的那条客户结构序列"] if recast_chart else [])
                             + (["GAAP 与 non-GAAP 在净利处的分叉"] if accounting_chart else [])
                             + (["对市场预期"] if market_chart else []))
                    + "，以及"
                    + ("本季真正变坏的" if fcf_step < 0 else "")
                    + ("现金转化与表外敞口。" if exposure_chart else "现金转化。")
                ),
                "exhibits": highlight_ex,
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": (
                    ("当前值离下季阈值还有多远，统一用「距阈值余量」口径。"
                     + (f"本季{cn_count(len(kpi_entries))}条阈值"
                        + ("全部" if not eightk else f"里有{cn_count(len(tenq))}条")
                        + f"建在 10-Q 的原始项上 —— {values['tenq_items']} —— "
                        "而不是建在公司可以重新划分的呈现层上"
                        + (f"；{values['eightk_clause'][1:]}。" if eightk else "。")))
                    if next_kpi is not None else "本季没有设定下季阈值。"
                ),
                "exhibits": next_ex,
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": (
                    f"NVDA 专属的常规序列：{long_labels[0]} 起 {long_n} 季的利润率与费用强度、"
                    "现金转化，以及真正承载资本强度的存货与供应承诺。"
                ),
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": notes,
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
