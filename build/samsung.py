#!/usr/bin/env python3
"""Build the Samsung Electronics quarterly-results page.

Same four-part, chart-led shape as the other pages (上季兑现 → 本季重点 →
下季跟踪 → 长期常规), but the first section has to be built differently here,
because Samsung guides almost nothing a reader would expect.

Two facts drive the whole layout:

1. **Samsung is not an SEC registrant.** Every other page in this repo can be
   traced to EDGAR -- even Ferrari, through its 6-K exhibits. Samsung cannot:
   CIK 0000879316 holds 251 filings that are all beneficial-ownership and
   tender-offer forms, the newest from 2015. There is no 20-F, no 6-K, no
   F-1. The numbers here come from the company's own quarterly Earnings
   Release and from DART, and the two are used as independent readings of each
   other rather than as one source quoted twice.

2. **The company guides the quantity, not the price.** The only forward number
   management gives is next quarter's DRAM and NAND bit shipment growth, and
   even that is a phrase rather than a figure. Average selling price -- which
   is what actually moved earnings this cycle -- is described only in
   retrospect and never guided. So section one is not "did it beat its
   revenue guidance"; it is the narrower,真实 question: the one thing it
   guides, does it hit, and does hitting it explain anything.

Everything in the payload is a Samsung-disclosed figure, a DART-disclosed
figure, or arithmetic reproducible from the audit tables and marked D.
Currency is Korean won throughout; nothing is converted to dollars, because
Samsung publishes no dollar figures and a conversion would put a number on the
page that no filing contains -- and would fold the won's own move against the
dollar into every growth rate the page is trying to read.

Rolling a quarter is a data edit (see CLAUDE.md §9): every period label, count
and figure in the prose below is computed from ``series/samsung.json``; what
belongs to one quarter only -- call quotes, the bonus accrual, the accrual-basis
capex, the currency effect, the sell-side assumption behind a threshold -- sits
in blocks stamped with that quarter and read through ``board.stamped_block``,
and every "only / first / all / never" sentence is printed only while the data
still says so.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import (  # noqa: E402
    ai_capex_cycle_table,
    cn_count,
    cn_ordinal,
    delivery_band,
    headroom_exhibit,
    latest_block,
    minus_sign,
    number_exhibits,
    stamped_block,
    threshold_exhibit,
    threshold_table,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "samsung.json"
DATA_DIR = ROOT / "data"

# The four divisions the segment charts draw, in the company's table order.
DIVISIONS = ("ds", "dx", "sdc", "harman")


def _quarter_days(period_ends: list[str]) -> list[int]:
    """Days in each calendar quarter, from the period-end dates themselves.

    This used to be a literal eight-element list. It was correct for an
    eight-quarter window and became an IndexError the moment the record grew --
    which is the good outcome; the bad one would have been a list long enough to
    index but wrong about which quarter is which. Derived from the dates, it
    also answers the leap-February question by itself.
    """
    from datetime import date
    days = []
    for value in period_ends:
        end = date.fromisoformat(value)
        start = date(end.year, end.month - 2, 1)   # 3->1, 6->4, 9->7, 12->10
        days.append((end - start).days + 1)
    return days


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100


def _quarter_year(period: str) -> tuple[int, int]:
    quarter, year = period.split()
    return int(quarter[1]), int(year)


def compact_period(period: str) -> str:
    """``'Q2 2026'`` → ``"Q2'26"``."""
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


def deck_period(period: str) -> str:
    """``'Q2 2026'`` → ``'2Q 2026'``, the way Samsung's own documents name it."""
    quarter, year = _quarter_year(period)
    return f"{quarter}Q {year}"


def deck_short(period: str) -> str:
    """``'Q2 2026'`` → ``'2Q26'``."""
    quarter, year = _quarter_year(period)
    return f"{quarter}Q{str(year)[-2:]}"


def quarter_only(period: str) -> str:
    """``'Q3 2026'`` → ``'3Q'``: a quarter named inside its own year's sentence."""
    return f"{_quarter_year(period)[0]}Q"


def iso_period(period: str) -> str:
    """``'Q2 2026'`` → ``'2026Q2'``."""
    quarter, year = _quarter_year(period)
    return f"{year}Q{quarter}"


def shift_period(period: str, step: int) -> str:
    """``shift_period('Q4 2026', 1)`` → ``'Q1 2027'``."""
    quarter, year = _quarter_year(period)
    index = year * 4 + quarter - 1 + step
    return f"Q{index % 4 + 1} {index // 4}"


def rounded(values: list[float | None], digits: int = 6) -> list[float | None]:
    """Round for the payload so a rebuild is idempotent, keeping ``None`` holes."""
    return [None if value is None else round(value, digits) for value in values]


def resolve_exhibit_refs(exhibits: list[dict]) -> list[dict]:
    """Substitute ``{ref}`` placeholders with the numbers `number_exhibits` assigned.

    Cross-references written as literal numbers break the moment a chart is
    inserted, so captions that point at an exhibit follow the same rule the
    exhibits themselves do.
    """
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


def growth_words(ratio: float) -> str:
    """How a level moved, for 「收入两年翻了一倍多」: ``2.17`` → 「翻了一倍多」."""
    if ratio >= 3:
        return f"涨到原来的 {ratio:.1f} 倍"
    if ratio >= 2:
        return "翻了一倍多"
    if ratio >= 1:
        return f"涨了 {(ratio - 1) * 100:.0f}%"
    return f"降了 {(1 - ratio) * 100:.0f}%"


def multiple_words(ratio: float) -> str:
    """``2.07`` → 「两倍多」, ``4.5`` → 「四倍多」: one multiple against another."""
    whole = int(ratio)
    return f"{cn_count(whole)}倍" + ("多" if ratio - whole >= 0.05 else "")


def magnitude_word(value: float) -> str:
    """A quarter-on-quarter move in words: ``2.5`` → 「个位数」, ``11.5`` → 「十几个百分点」."""
    size = abs(value)
    if size < 10:
        return "个位数"
    if size < 20:
        return "十几个百分点"
    return f"{cn_count(int(size // 10) * 10)}几个百分点"


def magnitude_range(values: list[float]) -> str:
    low, high = magnitude_word(min(values, key=abs)), magnitude_word(max(values, key=abs))
    return low if low == high else f"{low}到{high}"


def rise_or_fall(start: float, end: float, up: str = "涨到", down: str = "降到") -> str:
    return up if end >= start else down


# ── Sources reused across several captions ────────────────────────────────────
SRC_DECK = (
    "来自公司每季自行发布的 Earnings Release（IR 网站英文版）四页财务附录："
    "Appendix 1 合并损益表、Appendix 2 分部经营实绩、Appendix 3 资产负债表、"
    "Appendix 4 现金流量表。"
)


def src_dart(quarters: int) -> str:
    """The DART half of the sourcing line.

    It states that the two chains agree quarter by quarter over the whole
    window. Each roll re-proves that for the new quarter: `_checks` holds the
    deck's own trillions and the Samsung checks test compares them with the
    DART-based billions in the series.
    """
    return (
        "来自 DART 电子公告的「연결재무제표 기준 영업(잠정)실적(공정공시)」，"
        f"与公司 Earnings Release 互为独立读数：{cn_count(quarters)}个季度的合并营业收入与营业利润两边逐季吻合。"
    )


SRC_CALL = "来自该季电话会英文逐字稿，措辞照抄，未改词序。"

# The segment footnote is the single most load-bearing caveat on this page and
# gets repeated wherever a segment number is drawn, because a reader who lands
# on one chart cannot see the others' captions.
SEG_FOOTNOTE = (
    "公司分部表的脚注原文：「the sales of business units include intersegment sales」，"
    "所以<b>四个分部收入之和大于合并收入</b>，差额是分部间抵销；"
    "而<b>分部营业利润侧没有抵销</b>，可以直接加总。"
)


def derived(staging: dict) -> dict:
    """Every number the charts need that is not a disclosed line item.

    Kept in one place so the audit tables and the charts cannot drift: each
    table below prints the same list the chart above it plots.
    """
    fin = staging["financials_krw_bn"]
    rev_tn = [value / 1000 for value in fin["revenue"]]
    cogs_tn = [value / 1000 for value in fin["cost_of_sales"]]
    seg_rev = staging["segment_revenue_krw_tn"]
    seg_op = staging["segment_operating_profit_krw_tn"]
    cash = staging["cash_flow_krw_tn"]
    bs = staging["balance_sheet_krw_bn"]
    quarter_days = _quarter_days(staging["period_ends"])

    segment_sum = [
        seg_rev["dx"][i] + seg_rev["ds"][i] + seg_rev["sdc"][i] + seg_rev["harman"][i]
        for i in range(len(rev_tn))
    ]
    return {
        "revenue_tn": rev_tn,
        "cogs_tn": cogs_tn,
        "gross_margin": [g / r * 100 for g, r in zip(fin["gross_profit"], fin["revenue"])],
        "operating_margin": [o / r * 100 for o, r in zip(fin["operating_profit"], fin["revenue"])],
        "net_margin": [n / r * 100 for n, r in zip(fin["profit_owners"], fin["revenue"])],
        "effective_tax": [t / p * 100 for t, p in zip(fin["income_tax"], fin["profit_before_tax"])],
        "memory_share": [m / r * 100 for m, r in zip(seg_rev["memory"], rev_tn)],
        "ds_non_memory": [d - m for d, m in zip(seg_rev["ds"], seg_rev["memory"])],
        "segment_sum": segment_sum,
        "elimination": [s - r for s, r in zip(segment_sum, rev_tn)],
        "elimination_share": [(s - r) / r * 100 for s, r in zip(segment_sum, rev_tn)],
        "dx_margin": [o / r * 100 for o, r in zip(seg_op["dx"], seg_rev["dx"])],
        "ds_margin": [o / r * 100 for o, r in zip(seg_op["ds"], seg_rev["ds"])],
        "sdc_margin": [o / r * 100 for o, r in zip(seg_op["sdc"], seg_rev["sdc"])],
        "fcf": [c - k for c, k in zip(cash["operating"], cash["capex_ppe"])],
        "capex_to_cfo": [k / c * 100 for k, c in zip(cash["capex_ppe"], cash["operating"])],
        "inventory_days": [
            bs["inventories"][i] / 1000 / cogs_tn[i] * quarter_days[i] for i in range(len(rev_tn))
        ],
        "receivable_days": [
            bs["receivables"][i] / 1000 / rev_tn[i] * quarter_days[i] for i in range(len(rev_tn))
        ],
        "rnd_intensity": [d / r * 100 for d, r in zip(fin["rnd_expenses"], fin["revenue"])],
        "net_cash_to_assets": [
            n * 1000 / a * 100 for n, a in zip(staging["net_cash_krw_tn"], bs["total_assets"])
        ],
    }


def quarter_facts(staging: dict, der: dict) -> dict:
    """The quarter's comparative facts, each one a sentence the page may print.

    Every "first", "only", "all" and "record" on this page is decided here from
    the arrays, so a quarter that breaks one of them changes the sentence
    instead of leaving last quarter's claim in place.
    """
    periods = staging["periods"]
    seg_op = staging["segment_operating_profit_krw_tn"]
    bits = staging["memory_bit_and_price"]
    delta_rev = der["revenue_tn"][-1] - der["revenue_tn"][-2]
    delta_cogs = der["cogs_tn"][-1] - der["cogs_tn"][-2]
    division_losses = [(i, key) for i in range(len(periods)) for key in DIVISIONS
                       if seg_op[key][i] < 0]
    dx_losses = [i for i in range(len(periods)) if seg_op["dx"][i] < 0]
    verdicts = [bits[f"{name}_bit_vs_guide"][i] for name in ("dram", "nand")
                for i in range(len(bits["quarters"]))]
    price_moves = [abs(v) for name in ("dram", "nand") for v in bits[f"{name}_asp_qoq_pct"]]
    bit_moves = [abs(v) for name in ("dram", "nand") for v in bits[f"{name}_bit_actual"]
                 if v is not None]
    price_dominates = all(
        min(abs(bits["dram_asp_qoq_pct"][i]), abs(bits["nand_asp_qoq_pct"][i]))
        > max([abs(bits[f"{name}_bit_actual"][i]) for name in ("dram", "nand")
               if bits[f"{name}_bit_actual"][i] is not None], default=0)
        for i in range(len(bits["quarters"]))
    )
    return {
        "delta_rev": delta_rev,
        "delta_cogs": delta_cogs,
        "incremental_gm": (delta_rev - delta_cogs) / delta_rev * 100 if delta_rev > 0 else None,
        "dx_negative": seg_op["dx"][-1] < 0,
        "dx_only_division_loss": division_losses == [(len(periods) - 1, "dx")],
        "dx_loss_ordinal": len(dx_losses),
        "bits_all_met": all(v in ("met", "exceeded") for v in verdicts),
        "bits_missed_quarters": sum(
            1 for i in range(len(bits["quarters"]))
            if "missed" in (bits["dram_bit_vs_guide"][i], bits["nand_bit_vs_guide"][i])),
        "price_dominates": price_dominates and bool(price_moves) and bool(bit_moves),
        "non_memory_flat": der["ds_non_memory"][-1] <= der["ds_non_memory"][0],
        "memory_took_all_ds_growth": (
            staging["segment_revenue_krw_tn"]["memory"][-1] - staging["segment_revenue_krw_tn"]["memory"][0]
            >= staging["segment_revenue_krw_tn"]["ds"][-1] - staging["segment_revenue_krw_tn"]["ds"][0]),
    }


def dx_loss_words(facts: dict, quarters: int) -> str:
    """「八季首次」 while the DX loss is the window's first, 「八季里第二次」 after."""
    if facts["dx_loss_ordinal"] == 1:
        return f"{cn_count(quarters)}季首次"
    return f"{cn_count(quarters)}季里第{cn_ordinal(facts['dx_loss_ordinal'])}次"


# ── Section 1: what the company actually guided ───────────────────────────────
def bit_delivery_charts(staging: dict, facts: dict, guidance: dict | None) -> list[dict]:
    """The only guided number Samsung publishes, and the number that mattered.

    The pairing is the point. The bit-shipment band is the whole of the
    company's forward disclosure; the price line beside it, which the company
    never guides, is what moved earnings by an order of magnitude. A page that
    showed only the first would report a company in complete control of its
    own outlook.
    """
    periods = staging["periods"]
    bits = staging["memory_bit_and_price"]
    quarters = bits["quarters"]
    if quarters[-1] != periods[-1]:
        raise ValueError(f"series block `memory_bit_and_price` is stamped {quarters[-1]!r}, "
                         f"but the series ends at {periods[-1]!r}: update it with the roll")
    labels = [compact_period(q) for q in quarters]
    guide = bits["next_quarter_guide"]
    if guide["quarter"] != shift_period(periods[-1], 1):
        raise ValueError(f"series block `memory_bit_and_price.next_quarter_guide` is stamped "
                         f"{guide['quarter']!r}, but the quarter after {periods[-1]!r} is "
                         f"{shift_period(periods[-1], 1)!r}: update it with the roll")

    # A quarter whose guide this page does not hold is left off the band chart
    # rather than drawn as a zero-width band at zero -- a shape that stands for
    # "no data" is exactly the confusion a band chart cannot survive. It still
    # appears in the price chart and in the audit table, where the missing
    # wording is written out in words.
    guided = [i for i, low in enumerate(bits["dram_bit_guide_low"]) if low is not None]
    missing = [i for i, low in enumerate(bits["dram_bit_guide_low"]) if low is None]
    band_labels = [labels[i] for i in guided] + [compact_period(guide["quarter"])]
    missing_note = ""
    if missing:
        quotes = [bits["dram_bit_vs_guide_quote"][i] for i in missing]
        missing_note = (
            f"<b>{'、'.join(labels[i] for i in missing)} 不在这张图上</b>：给出"
            + ("它" if len(missing) == 1 else "它们")
            + f"的是 {'、'.join(deck_short(shift_period(quarters[i], -1)) for i in missing)} 电话会，"
            + ("本页没有那份逐字稿，" if len(missing) == 1 else "本页没有那几份逐字稿，")
            + ("只有该季公司自述" + "".join(f"「{quote}」" for quote in quotes if quote) + "。"
               if any(quotes) else "该季公司也没有自述是否达标。")
            + "宁可让那一格缺席，也不画一条代表「没有数据」的零宽区间。"
        )
    mapping = bits["band_mapping"]
    dram = delivery_band(
        "EX_BIT", "DRAM 出货 bit 环比", band_labels,
        [bits["dram_bit_guide_low"][i] for i in guided] + [guide["dram_low"]],
        [bits["dram_bit_guide_high"][i] for i in guided] + [guide["dram_high"]],
        [bits["dram_bit_actual"][i] for i in guided] + [None],
        fmt="pct1", ylab="环比 %", unit="%",
        src_extra=(
            SRC_CALL
            + "区间与实际都是本页对公司定性措辞的数值化读数 D，公司本身从未给过数字："
            + "、".join(f"{words}={low}–{high}%" for words, (low, high) in mapping.items())
            + "；实际值取该措辞区间的中点。"
            "对照表见数据核对抽屉。"
        ),
        extra_note=missing_note,
    )

    asp_unguided = guidance is not None and not guidance["asp_guided"]
    dram_asp, nand_asp = bits["dram_asp_qoq_pct"], bits["nand_asp_qoq_pct"]
    moves = dram_asp + nand_asp
    dram_bits = [v for v in bits["dram_bit_actual"] if v is not None]
    readings = [(bits[f"{name}_asp_qoq_phrase"][i], bits[f"{name}_asp_qoq_pct"][i])
                for name in ("dram", "nand") for i in range(len(quarters))]
    price = {
        "ref": "EX_ASP",
        "kind": "grouped_bars",
        "title": (
            "同期公司自述的环比 ASP：DRAM "
            + "、".join(f"{v:+.0f}%" for v in dram_asp)
            + (" —— 公司对价格从不给指引" if asp_unguided else "")
        ),
        "xlabels": labels,
        "groups": [
            {"name": "DRAM 环比 ASP", "color": "NAVY", "values": rounded(dram_asp)},
            {"name": "NAND 环比 ASP", "color": "GOLD", "values": rounded(nand_asp)},
        ],
        "bar_labels": True,
        "fmt": "pct0",
        "label_fmt": "pct0",
        "ylab": "环比 %",
        "note": (
            "把这张图和 Exhibit {EX_BIT} 并排看：公司唯一指引的<b>量</b>，"
            + (f"{cn_count(len(quarters))}季全部达标或超标"
               if facts["bits_all_met"] else
               f"{cn_count(len(quarters))}季里{cn_count(facts['bits_missed_quarters'])}季未达标")
            + (f"，环比幅度{magnitude_range(dram_bits)}" if dram_bits else "")
            + "；公司"
            + ("从不指引" if asp_unguided else "")
            + f"的<b>价</b>，同期环比 {min(moves):.0f}% 到 {max(moves):.0f}%。"
            + ("<b>本轮业绩不是由被指引的那个变量决定的</b> —— 这也是为什么这一页没有「收入指引兑现」"
               "那类图：" if facts["price_dominates"] else
               "这一页没有「收入指引兑现」那类图，因为")
            + "三星不提供收入、毛利率或营业利润的数字指引，一条都没有。"
            "柱高是公司措辞的数值化 D："
            + "、".join(f"「{phrase}」取 {value:.0f}" for phrase, value in readings)
            + "。"
        ),
        "src_extra": SRC_CALL + "逐季原话见数据核对抽屉的量价对照表。",
    }

    prov = staging["provisional_vs_final"]
    if prov["quarters"][-1] != periods[-1]:
        raise ValueError(f"series block `provisional_vs_final` is stamped {prov['quarters'][-1]!r}, "
                         f"but the series ends at {periods[-1]!r}: update it with the roll")
    gap = [
        f - p
        for f, p in zip(prov["final_operating_profit_krw_tn"], prov["flash_operating_profit_krw_tn"])
    ]
    upward = sum(1 for value in gap if value > 0)
    downward = sum(1 for value in gap if value < 0)
    from datetime import date
    period_end = dict(zip(periods, staging["period_ends"]))
    flash_weeks = [round((date.fromisoformat(flash) - date.fromisoformat(period_end[quarter])).days / 7)
                   for quarter, flash in zip(prov["quarters"], prov["flash_date"])]
    weeks = (f"{min(flash_weeks)}–{max(flash_weeks)}" if min(flash_weeks) != max(flash_weeks)
             else f"{min(flash_weeks)}")
    provisional = {
        "ref": "EX_PROV",
        "kind": "diverging_bars",
        "title": (
            f"速报数到确定数的营业利润修正：有记录的 {len(gap)} 季"
            + ("全部为正" if upward == len(gap) else
               f"里 {upward} 季为正、{downward} 季为负")
            + f"，幅度 {min(gap):+.2f}～{max(gap):+.2f} 兆韩元"
        ),
        "xlabels": [compact_period(q) for q in prov["quarters"]],
        "values": rounded(gap, 2),
        "legend": "确定数 − 速报数",
        "positive_label": "确定数更高",
        "negative_label": "确定数更低",
        "fmt": "f2",
        "yfmt": "f2",
        "label_fmt": "f2",
        "ylab": "兆韩元",
        "zero_line": True,
        "note": (
            f"三星每季披露两次：季末后 {weeks} 周先发速报（잠정실적，只给营业收入与营业利润），"
            "月末再发完整财报。这张图量的是两次之间营业利润被改动了多少。"
            "<b>只画营业利润，不画收入</b>：速报的收入按兆韩元<b>取整</b>发布（"
            + " / ".join(f"{value:.0f}" for value in prov["flash_revenue_krw_tn"])
            + "），所以收入那一栏的「差额」几乎全是取整而不是修正，画出来会是一张读者会误读的图。"
            + (f"<b>{len(gap)} 季不足以支撑「总是上修」这个结论</b>，"
               f"只够说明这{cn_count(len(gap))}次都没有下修 —— "
               if downward == 0 else
               f"<b>{len(gap)} 季里有 {downward} 季下修，「总是上修」不成立</b> —— ")
            + "更早的季度本页没有拿到速报公告原文，缺口写在口径说明里。"
        ),
        "src_extra": src_dart(len(periods)) + "速报与确定数的发布日期逐季列在数据核对抽屉里。",
    }
    return [dram, price, provisional]


# ── Section 2: the quarter ────────────────────────────────────────────────────
def quarter_charts(staging: dict, der: dict, labels: list[str], facts: dict,
                   story: dict | None) -> list[dict]:
    periods = staging["periods"]
    n = len(periods)
    fin = staging["financials_krw_bn"]
    seg_rev = staging["segment_revenue_krw_tn"]
    seg_op = staging["segment_operating_profit_krw_tn"]
    rev, opm = der["revenue_tn"], der["operating_margin"]
    first = labels[0]

    revenue_ratio = rev[-1] / rev[0]
    margin_ratio = opm[-1] / opm[0] if opm[0] > 0 else None
    margin_outran = margin_ratio is not None and margin_ratio > revenue_ratio
    headline_chart = {
        "ref": "EX_TOP",
        "kind": "bar_line_dual",
        "title": (
            f"合并收入 {rev[-1]:.1f} 兆韩元、营业利润率 {opm[-1]:.1f}%"
            f"（{first} 为 {opm[0]:.1f}%）"
        ),
        "xlabels": labels,
        "bar": {"name": "合并收入（兆韩元）", "color": "NAVY",
                "values": rounded(rev, 2), "yfmt": "f1"},
        "line": {"name": "营业利润率", "color": "GOLD",
                 "values": rounded(opm, 2), "yfmt": "pct0"},
        "ylab": "兆韩元",
        "ylab2": "营业利润率",
        "yfmt": "f0",
        "note": (
            f"收入{cn_count(n)}季里{growth_words(revenue_ratio)}"
            f"（{rev[0]:.1f} → {rev[-1]:.1f} 兆韩元），"
            f"{'但' if margin_outran else ''}营业利润率从 {opm[0]:.1f}% 走到 {opm[-1]:.1f}%"
            + (f"，是收入倍数的{multiple_words(margin_ratio / revenue_ratio)}" if margin_outran else "")
            + (" —— 这一轮的增量几乎不带成本" if (facts["incremental_gm"] or 0) >= 90 else "")
            + "，拆解见 Exhibit {EX_BRIDGE}。"
            "本页全部以韩元列示，不折美元。"
        ),
        "src_extra": SRC_DECK + src_dart(n),
    }

    mix_chart = {
        "ref": "EX_MIX",
        "kind": "stacked_dual",
        "title": (
            f"分部收入结构：Memory 占合并收入从 {der['memory_share'][0]:.1f}% "
            f"{rise_or_fall(der['memory_share'][0], der['memory_share'][-1], '升到', '降到')} "
            f"{der['memory_share'][-1]:.1f}%"
        ),
        "xlabels": labels,
        "stacks": [
            {"name": "DS（半导体）", "color": "NAVY", "values": rounded(seg_rev["ds"], 1)},
            {"name": "DX（手机与家电）", "color": "BLUE", "values": rounded(seg_rev["dx"], 1)},
            {"name": "SDC（显示）", "color": "MBLUE", "values": rounded(seg_rev["sdc"], 1)},
            {"name": "Harman", "color": "GRAY", "values": rounded(seg_rev["harman"], 1)},
        ],
        # 右轴上界必须显式给：渲染器在没有 ymax 时把上界写死在 60，
        # 而 Memory 占比早已越过 60%，越界的线会被画到负 y、被浏览器裁掉，
        # 而图例照常写着它，且坐标全是合法有限数字，只查 NaN 的断言看不见。
        "line": {"name": "Memory 占合并收入", "color": "GOLD",
                 "values": rounded(der["memory_share"], 1), "yfmt": "pct0", "ymax": 100},
        "ylab2": "Memory 占合并收入",
        "note": (
            "堆叠的是四个分部的收入，" + SEG_FOOTNOTE
            + f"所以柱高（本季 {der['segment_sum'][-1]:.1f}）高于合并收入"
            f"（{rev[-1]:.1f}），差额 {der['elimination'][-1]:.1f} 兆韩元见 "
            "Exhibit {EX_ELIM}。金色线的分母是<b>合并</b>收入，不是柱高。"
        ),
        "src_extra": SRC_DECK,
    }

    ds = seg_op["ds"]
    trough = min(range(n), key=lambda i: ds[i])
    dx_verb = ("转为" if seg_op["dx"][-1] < 0 <= seg_op["dx"][-2] else
               "仍为" if seg_op["dx"][-1] < 0 else "为")
    orders = (math.floor(math.log10(ds[-1] / abs(seg_op["dx"][-1])))
              if facts["dx_negative"] and ds[-1] > 0 else 0)
    losses_note = ""
    if facts["dx_negative"]:
        losses_note = (
            "<b>本季最该看的一格是 DX 那根负柱</b>："
            + (f"{cn_count(n)}季里唯一一次分部亏损" if facts["dx_only_division_loss"] else
               f"DX 的{dx_loss_words(facts, n)}亏损")
            + ("，公司给的原因是「" + story["dx_reason_quote"] + "」—— 推高它成本的正是"
               "自家 DS 卖出的存储" if story and story.get("dx_reason_quote") else "")
            + "。集团内部同时坐在这轮涨价的两边，"
            + (f"一边赚的比另一边亏的多{cn_count(orders)}个数量级，" if orders >= 1 else "")
            + "但对手机业务而言这是真实的利润损失"
            + (f"，{story['dx_outlook_words']}" if story and story.get("dx_outlook_words") else "")
            + "。"
        )
    worst_gap = max(abs(fin["operating_profit"][i] / 1000 - sum(seg_op[key][i] for key in DIVISIONS))
                    for i in range(n))
    bound = max(0.1, math.ceil(worst_gap * 10) / 10)
    op_chart = {
        "ref": "EX_SEGOP",
        "kind": "grouped_bars",
        "title": (
            "分部营业利润："
            + (f"DS 从 {ds[trough]:.1f} 走到 {ds[-1]:.1f} 兆韩元" if trough < n - 1 else
               f"DS {ds[-1]:.1f} 兆韩元")
            + f"，同一季 DX {dx_verb} {seg_op['dx'][-1]:.1f}"
        ),
        "xlabels": labels,
        "groups": [
            {"name": "DS（半导体）", "color": "NAVY", "values": rounded(seg_op["ds"], 2)},
            {"name": "DX（手机与家电）", "color": "BLUE", "values": rounded(seg_op["dx"], 2)},
            {"name": "SDC（显示）", "color": "MBLUE", "values": rounded(seg_op["sdc"], 2)},
            {"name": "Harman", "color": "GRAY", "values": rounded(seg_op["harman"], 2)},
        ],
        "bar_labels": False,
        "fmt": "f1",
        "label_fmt": "f1",
        "ylab": "兆韩元",
        "note": (
            losses_note
            + SEG_FOOTNOTE + f"分部营业利润逐季加总与合并数的差在 ±{bound:.1f} 兆韩元以内，见核对表。"
        ),
        "src_extra": SRC_DECK,
    }

    gm, nm, tax = der["gross_margin"], der["net_margin"], der["effective_tax"]
    cost_gap = [g - o for g, o in zip(gm, opm)]
    tax_gap = [o - m for o, m in zip(opm, nm)]
    narrowing = cost_gap[-1] < cost_gap[0]
    margin_chart = {
        "ref": "EX_MARGIN",
        "kind": "lines",
        "title": (
            f"三条利润率：毛利率 {gm[-1]:.1f}%、"
            f"营业利润率 {opm[-1]:.1f}%、归母净利率 {nm[-1]:.1f}%"
        ),
        "xlabels": labels,
        "series": [
            {"name": "毛利率", "values": rounded(gm, 2), "color": "NAVY"},
            {"name": "营业利润率", "values": rounded(opm, 2), "color": "BLUE"},
            {"name": "归母净利率", "values": rounded(nm, 2), "color": "GOLD"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "zero_base": True,
        "ylab": "占收入 %",
        "note": (
            ("三条线的间距在收窄：" if narrowing else "")
            + f"毛利率与营业利润率之间是费用率，本季 {cost_gap[-1]:.1f}pp，"
            f"{first} 是 {cost_gap[0]:.1f}pp。"
            + (f"营业利润率与净利率之间{'反而' if narrowing else '也在'}拉开，主因是有效税率从 "
               f"{tax[0]:.1f}% 升到 {tax[-1]:.1f}%"
               if tax_gap[-1] > tax_gap[0] and tax[-1] > tax[0] else
               f"有效税率本季 {tax[-1]:.1f}%")
            + "（见 Exhibit {EX_HEADROOM} 的阈值列表）。"
            "纵轴自 0 起，没有截轴。"
        ),
        "src_extra": SRC_DECK + src_dart(n) + "三条比率均为各利润行除以合并收入 D。",
    }

    delta_rev, delta_cogs = facts["delta_rev"], facts["delta_cogs"]
    delta_sga = (fin["sga_expenses"][-1] - fin["sga_expenses"][-2]) / 1000
    delta_op = (fin["operating_profit"][-1] - fin["operating_profit"][-2]) / 1000
    incremental = facts["incremental_gm"]
    bonus = (story or {}).get("special_bonus")
    bridge_chart = {
        "ref": "EX_BRIDGE",
        "kind": "grouped_bars",
        "title": (
            f"本季环比增量拆解：收入 {delta_rev:+.1f} 兆韩元，销货成本"
            + ("只 " if incremental is not None and incremental >= 75 else " ")
            + f"{delta_cogs:+.1f}"
            + (f"，增量毛利率 {incremental:.1f}%" if incremental is not None else "")
        ),
        "xlabels": ["合并收入", "销货成本", "销管费用（含 R&D）", "营业利润"],
        "groups": [{
            "name": f"{iso_period(periods[-1])} 较 {iso_period(periods[-2])} 的绝对变动",
            "color": "NAVY",
            "values": rounded([delta_rev, delta_cogs, delta_sga, delta_op], 2),
        }],
        "bar_labels": True,
        "fmt": "f1",
        "label_fmt": "f1",
        "ylab": "兆韩元",
        "note": (
            (f"这是本季度最反常的一格：收入环比多了 {delta_rev:.1f} 兆韩元，而销货成本只多了 "
             f"{delta_cogs:.1f} —— <b>增量里 {incremental:.1f}% 直接落进毛利</b>。"
             "存储涨价不需要多投一片晶圆，这是价格驱动周期与产量驱动周期在报表上的分界线。"
             if incremental is not None and incremental >= 90 else
             f"收入环比 {delta_rev:+.1f} 兆韩元，销货成本 {delta_cogs:+.1f}。")
            + f"销管费用同期 {delta_sga:+.1f}"
            + (f"，其中含公司口径为「{bonus['basis']}的 {bonus['pct']:.1f}%」的"
               f"特别绩效奖金一次性补提（{deck_short(bonus['prior_quarter'])} "
               f"{bonus['prior_quarter_accrual']}）"
               + ("" if bonus["capitalized_split_disclosed"] else
                  "；公司未拆分其中多少被资本化进在产品存货，所以这根柱不是纯费用增长")
               if bonus else "")
            + "。四根柱不是瀑布图，不相互加总。"
        ),
        "src_extra": (SRC_DECK + "四项均为公司披露值的相邻两季算术差 D"
                      + (f"；奖金口径来自 {deck_short(periods[-1])} 电话会 CFO 原话。" if bonus else "。")),
    }

    memory = seg_rev["memory"]
    non_memory = der["ds_non_memory"]
    stuck = max(non_memory) - min(non_memory) <= 0.25 * min(non_memory)
    disclosed_below_ds = {key for key in seg_rev if key not in ("dx", "mx_nw", "mx", "vd_da", "vd",
                                                                 "ds", "memory", "sdc", "harman")}
    memory_chart = {
        "ref": "EX_NONMEM",
        "kind": "lines",
        "title": (
            f"Memory 收入 {memory[0]:.1f} → {memory[-1]:.1f} 兆韩元，"
            f"DS 里的非存储部分{cn_count(n)}季"
            + ("一直卡在 " if stuck else "在 ")
            + f"{min(non_memory):.1f}–{max(non_memory):.1f}"
            + ("" if stuck else " 之间")
        ),
        "xlabels": labels,
        "series": [
            {"name": "Memory 收入", "values": rounded(memory, 1), "color": "NAVY"},
            {"name": "DS 减 Memory（System LSI + Foundry）D",
             "values": rounded(non_memory, 1), "color": "GOLD"},
        ],
        "fmt": "f1",
        "yfmt": "f0",
        "label_fmt": "f1",
        "end_label": True,
        "zero_base": True,
        "ylab": "兆韩元",
        "note": (
            "<b>金色那条线是本页唯一能说明代工与非存储芯片的数字，而它是减出来的。</b>"
            + ("公司在 DS 之下只披露 Memory 一行收入，System LSI 与 Foundry 的收入、利润"
               "<b>一个季度都没有单独披露过</b>，Memory 自己的营业利润也没有。"
               "所以市面上「代工亏损 X 兆」这类数字全部是卖方估计，不是公司口径，本页不采用。"
               if not disclosed_below_ds else "")
            + "另有一层失真：Foundry 为自家 HBM 生产 base die 的收入计入 Foundry 再在合并时抵销，"
            "所以这条残值线含内部收入，绝对水平不精确 —— "
            + (f"它能说明的只有一件事：{cn_count(n)}季来它没有增长，DS 的全部增量都是存储。"
               if facts["non_memory_flat"] and facts["memory_took_all_ds_growth"] else
               f"它能说明的只有方向：{cn_count(n)}季来它从 {non_memory[0]:.1f} 走到 {non_memory[-1]:.1f}。")
        ),
        "src_extra": SRC_DECK + "残值 = 披露的 DS 收入减披露的 Memory 收入 D。",
    }
    return [headline_chart, mix_chart, op_chart, margin_chart, bridge_chart, memory_chart]


# ── Section 3: thresholds ─────────────────────────────────────────────────────
def tracking_charts(staging: dict, der: dict, labels: list[str], facts: dict,
                    kpi: dict, story: dict | None, guidance: dict | None) -> list[dict]:
    n = len(staging["periods"])
    entries = kpi["entries"]
    by_metric = {entry["metric"]: entry for entry in entries}
    headroom = headroom_exhibit(
        f"距阈值余量：{cn_count(len(entries))}条跟踪线里 "
        f"{sum(1 for e in entries if (e['current'] - e['threshold']) * (1 if e['direction'] == 'up' else -1) < 0)}"
        " 条已经越过",
        entries, "current",
        note=(
            "阈值是<b>本地研究设定</b>，不是公司指引 —— 三星不提供收入、毛利率或营业利润的数字指引，"
            "所以这一节没有可兑现的公司承诺可用。正值代表仍在安全侧；口径统一为「距阈值百分之多少」，"
            "好让百分比、天数这些不同单位的线并排可读。原始单位的阈值与当前值见核对表。"
            "每条线为什么选这个阈值，写在同一张表的最后一列。"
        ),
        src_extra=SRC_DECK + f"当前值全部由公司披露值算出 D，算式见{cn_count(n)}季核对表。",
    )
    headroom["ref"] = "EX_HEADROOM"

    opm = der["operating_margin"]
    opm_line = by_metric["合并营业利润率"]["threshold"]
    sellside = kpi.get("sellside_asp_assumption")
    next_quarter = shift_period(staging["periods"][-1], 1)
    if sellside and sellside["quarter"] != next_quarter:
        raise ValueError(f"series block `next_kpi.sellside_asp_assumption` is stamped "
                         f"{sellside['quarter']!r}, but the next quarter is {next_quarter!r}: "
                         "update it or remove it")
    asp_unguided = guidance is not None and not guidance["asp_guided"]
    trough = min(range(n), key=lambda i: opm[i])
    opm_chart = threshold_exhibit(
        f"合并营业利润率对 {opm_line:.0f}% 的阈值：本季 {opm[-1]:.1f}%",
        labels, rounded(opm, 2), opm_line,
        fmt="pct1", ylab="营业利润率",
        actual_name="合并营业利润率", threshold_name=f"阈值 {opm_line:.0f}%",
        note=(
            f"选 {opm_line:.0f}% 不是因为它是某个共识，而是因为它把「涨价减速」和「周期翻转」分开"
            + (f"：卖方对 {deck_short(sellside['quarter'])} 存储混合 ASP 的假设落在 "
               f"{sellside['low_pct']:+.0f}% 到 {sellside['high_pct']:+.0f}% 之间"
               + ("，<b>没有一家假设转负</b>" if sellside["low_pct"] > 0 else "")
               if sellside else "")
            + (f"，而公司自己对 {quarter_only(next_quarter)} ASP 一个字都没给" if asp_unguided else "")
            + f"。若真跌破 {opm_line:.0f}%，说明减速的假设本身错了。"
            + (f"{cn_count(n)}季里这条线从 {opm[trough]:.1f}% 的谷底走到 {opm[-1]:.1f}%"
               + ("，本季是窗口内最高。" if opm[-1] == max(opm) else "。")
               if trough < n - 1 else
               f"本季 {opm[-1]:.1f}% 是{cn_count(n)}季里最低的一季。")
        ),
        src_extra=SRC_DECK + "阈值为本地设定；实际值 = 合并营业利润 ÷ 合并收入 D。",
    )
    opm_chart["ref"] = "EX_OPM"

    dx_margin = der["dx_margin"]
    dx_line = by_metric["DX 分部营业利润率"]["threshold"]
    dx_profit = staging["segment_operating_profit_krw_tn"]["dx"][-1]
    dx_chart = threshold_exhibit(
        f"DX 分部营业利润率对 {dx_line:.0f}% 的阈值：本季 {dx_margin[-1]:.2f}%"
        + (f"，{dx_loss_words(facts, n)}为负" if facts["dx_negative"] else ""),
        labels, rounded(dx_margin, 2), dx_line,
        fmt="pct1", ylab="DX 营业利润率",
        actual_name="DX 分部营业利润率", threshold_name=f"阈值 {dx_line:.0f}%",
        note=(
            "这条线是集团内部矛盾的温度计：DX 买存储，DS 卖存储，两者在同一张合并报表里。"
            f"本季 DX 营业利润 {dx_profit:.1f} 兆韩元"
            + ((f"，是{cn_count(n)}季唯一的负值。" if facts["dx_loss_ordinal"] == 1 else
                f"，是{cn_count(n)}季里第{cn_ordinal(facts['dx_loss_ordinal'])}个负值。")
               if facts["dx_negative"] else "。")
            + f"阈值取 {dx_line:.0f}% 而不是 0，是因为「距零阈值的百分比余量」在算术上没有定义。"
            + (f"管理层对下半年的说法是 <b>{story['dx_outlook_quote']}</b>"
               + ("，" + story["handset_outlook_words"] if story.get("handset_outlook_words") else "")
               + " —— 也就是说这条线在公司自己的预期里还会往下。"
               if story and story.get("dx_outlook_quote") else "")
        ),
        src_extra=SRC_DECK + "实际值 = DX 分部营业利润 ÷ DX 分部收入（含分部间销售）D。",
    )
    dx_chart["ref"] = "EX_DX"
    return [headroom, opm_chart, dx_chart]


# ── Section 4: the routine series ─────────────────────────────────────────────
def routine_charts(staging: dict, der: dict, labels: list[str], story: dict | None) -> list[dict]:
    n = len(staging["periods"])
    cash = staging["cash_flow_krw_tn"]
    fin = staging["financials_krw_bn"]
    first = labels[0]

    cfo, capex = cash["operating"], cash["capex_ppe"]
    capex_ratio = capex[-1] / capex[0]
    cfo_ratio = cfo[-1] / cfo[0]
    capex_flat = max(capex) / min(capex) < 2
    capex_qoq = capex[-1] - capex[-2]
    capex_qoq_text = minus_sign(f"{capex_qoq:+.1f}")
    accrual = story.get("accrual_capex_krw_tn") if story else None
    accrual_qoq = story["accrual_capex_qoq_krw_tn"] if accrual is not None else 0.0
    accrual_qoq_text = minus_sign(f"{accrual_qoq:+.1f}")
    opposite = accrual is not None and (accrual_qoq > 0) != (capex_qoq > 0)
    cash_chart = {
        "ref": "EX_CASH",
        "kind": "lines",
        "title": (
            f"经营现金流 {cfo[-1]:.1f} 兆韩元，自由现金流 {der['fcf'][-1]:.1f}，"
            + (f"而现金资本开支 {capex[-1]:.1f} 只是 {first} 的 {capex_ratio:.1f} 倍"
               if capex_ratio < cfo_ratio / 2 else
               f"现金资本开支 {capex[-1]:.1f}")
        ),
        "xlabels": labels,
        "series": [
            {"name": "经营现金流", "values": rounded(cfo, 2), "color": "NAVY"},
            {"name": "自由现金流 D", "values": rounded(der["fcf"], 2), "color": "GOLD"},
            {"name": "现金资本开支（购置 PP&E）", "values": rounded(capex, 2), "color": "MBLUE"},
            {"name": "折旧", "values": rounded(cash["depreciation"], 2), "color": "GRAY"},
        ],
        "fmt": "f1",
        "yfmt": "f0",
        "label_fmt": "f1",
        "end_label": True,
        "zero_base": True,
        "ylab": "兆韩元",
        "note": (
            ("<b>这张图最该注意的是那条几乎水平的浅蓝线。</b>" if capex_flat else "")
            + f"{cn_count(n)}个季度里经营现金流从 {cfo[0]:.1f} {rise_or_fall(cfo[0], cfo[-1])} {cfo[-1]:.1f} 兆韩元，"
            f"现金资本开支却在 {min(capex):.1f}–{max(capex):.1f} 之间"
            + ("横着走" if capex_flat else "")
            + (f"，本季甚至环比下降 {abs(capex_qoq):.1f}。" if capex_qoq < 0 else
               f"，本季环比 {capex_qoq_text}。")
            + ((("公司在电话会上给的口径与此相反 —— " if opposite else "公司在电话会上另给了一个口径 —— ")
                + f"IR 口径的应计资本开支本季 {accrual:.1f} 兆韩元、环比 "
                f"<b>{accrual_qoq_text}</b>，"
                f"现金流量表的购置 PP&E {'却' if opposite else ''}是环比 "
                f"<b>{capex_qoq_text}</b>。"
                + ("<b>两个口径同时由公司给出，方向相反，公司没有作调节。</b>"
                   if opposite and not story["accrual_capex_reconciled"] else ""))
               if accrual is not None else "")
            + f"本页画的是现金流量表那一条，因为它是{cn_count(n)}季都有、口径一致的那条"
            + ("；但读者不该由此得出「资本开支在降」的结论。" if opposite and capex_qoq < 0 else "。")
        ),
        "src_extra": (SRC_DECK + "自由现金流 = 经营现金流 − 购置 PP&E D，不是公司定义的指标"
                      + ("；应计口径来自电话会。" if accrual is not None else "。")),
    }

    net_cash = staging["net_cash_krw_tn"]
    assets = staging["balance_sheet_krw_bn"]["total_assets"]
    share = der["net_cash_to_assets"]
    cash_move = net_cash[-1] - net_cash[-2]
    net_cash_chart = {
        "ref": "EX_NETCASH",
        "kind": "bar_line_dual",
        "title": (
            f"净现金 {net_cash[-1]:.1f} 兆韩元，一个季度{'增加' if cash_move >= 0 else '减少'} "
            f"{abs(cash_move):.1f}"
        ),
        "xlabels": labels,
        "bar": {"name": "净现金（现金及等价物减有息负债）", "color": "NAVY",
                "values": rounded(net_cash, 2), "yfmt": "f1"},
        "line": {"name": "净现金 / 总资产", "color": "GOLD",
                 "values": rounded(share, 2), "yfmt": "pct0"},
        "ylab": "兆韩元",
        "ylab2": "净现金 / 总资产",
        "yfmt": "f0",
        "note": (
            "净现金是公司自己在资产负债表页给出的行（Cash − Debts，其中 Cash 含短期金融工具），"
            f"不是本页算的。{first} 时它是 {net_cash[0]:.1f} 兆韩元、占总资产 {share[0]:.1f}%，"
            f"本季 {net_cash[-1]:.1f} 兆韩元、占 {share[-1]:.1f}%。"
            + ("注意这个分母也在膨胀：" if assets[-1] > assets[0] else "")
            + f"总资产同期从 {assets[0] / 1000:.0f} 兆{rise_or_fall(assets[0], assets[-1], '涨', '降')}到 "
            f"{assets[-1] / 1000:.0f} 兆韩元"
            + ("，所以占比的上升比绝对额的上升温和得多。"
               if net_cash[-1] > net_cash[0] and share[-1] > share[0]
               and share[-1] / share[0] < net_cash[-1] / net_cash[0] else "。")
        ),
        "src_extra": SRC_DECK + "占比为净现金除以总资产 D。",
    }

    inventory, receivable = der["inventory_days"], der["receivable_days"]
    inventory_up = inventory[-1] > inventory[-2]
    receivable_up = receivable[-1] > receivable[-2]
    trend = ("两条同时在涨" if inventory_up and receivable_up else
             "两条同时在降" if not inventory_up and not receivable_up else
             "库存在涨、应收在降" if inventory_up else "库存在降、应收在涨")
    bonus = (story or {}).get("special_bonus")
    days_chart = {
        "ref": "EX_DAYS",
        "kind": "lines",
        "title": (
            f"库存天数 {inventory[-1]:.0f} 天、应收天数 {receivable[-1]:.0f} 天，{trend}"
        ),
        "xlabels": labels,
        "series": [
            {"name": "库存天数 D", "values": rounded(inventory, 1), "color": "NAVY"},
            {"name": "应收天数 D", "values": rounded(receivable, 1), "color": "GOLD"},
        ],
        "fmt": "f0",
        "yfmt": "f0",
        "label_fmt": "f0",
        "end_label": True,
        "zero_base": True,
        "ylab": "天",
        "note": (
            (("在一个公司自称缺货的季度里" if story and story.get("supply_shortage_claimed") else "本季")
             + f"库存天数从 {inventory[-2]:.0f} 天{'涨' if inventory_up else '降'}到 {inventory[-1]:.0f} 天"
             + ("，值得停一下。" if inventory_up and story and story.get("supply_shortage_claimed") else "。"))
            + ("两个解释都被公司自己的披露支持，且公司没有拆分："
               "一是特别绩效奖金中被<b>资本化进在产品存货</b>的部分"
               f"（CFO 说从 {quarter_only(bonus['released_from'])} 起随销售结转），"
               "二是存储涨价同时抬高了在产品的账面单价。"
               if inventory_up and bonus and not bonus["capitalized_split_disclosed"] else "")
            + "分母用当季销货成本、按实际日历天数年化 D。"
        ),
        "src_extra": SRC_DECK + "库存与应收为资产负债表披露值；天数为本页自算 D。",
    }

    elimination, elimination_share = der["elimination"], der["elimination_share"]
    narrow = max(elimination_share) - min(elimination_share) <= 2
    elim_chart = {
        "ref": "EX_ELIM",
        "kind": "bar_line_dual",
        "title": (
            f"分部间抵销额从 {elimination[0]:.1f} {rise_or_fall(elimination[0], elimination[-1])} "
            f"{elimination[-1]:.1f} 兆韩元，但占合并收入始终在 {min(elimination_share):.1f}%–"
            f"{max(elimination_share):.1f}% 之间"
        ),
        "xlabels": labels,
        "bar": {"name": "分部间抵销额 D", "color": "NAVY",
                "values": rounded(elimination, 2), "yfmt": "f1"},
        "line": {"name": "占合并收入", "color": "GOLD",
                 "values": rounded(elimination_share, 2), "yfmt": "pct0"},
        "ylab": "兆韩元",
        "ylab2": "占合并收入",
        "yfmt": "f0",
        "note": (
            "<b>这一整张图都是减出来的：公司的分部表里没有抵销这一行。</b>"
            + SEG_FOOTNOTE
            + "所以抵销额 = 四个分部收入之和 − 合并收入，是本页的算术，不是三星披露的数字。"
            f"绝对额{cn_count(n)}季里{growth_words(elimination[-1] / elimination[0])}，"
            + ("而占合并收入的比例一直待在一条窄带里 —— "
               "这说明内部供货的<b>物量</b>没有暴增，是内部转移价随存储价格一起被抬高了。"
               "（最后这句是本页的判断，不是公司说法。）"
               if narrow and elimination[-1] > elimination[0] else
               f"占合并收入在 {min(elimination_share):.1f}%–{max(elimination_share):.1f}% 之间。")
        ),
        "src_extra": SRC_DECK + "抵销额与占比均为本页自算 D。",
    }

    rnd = fin["rnd_expenses"]
    intensity = der["rnd_intensity"]
    record = bool(story and story.get("rnd_quarterly_record_claimed")) and rnd[-1] == max(rnd)
    opposite_ways = rnd[-1] > rnd[0] and intensity[-1] < intensity[0]
    rnd_chart = {
        "ref": "EX_RND",
        "kind": "bar_line_dual",
        "title": (
            f"研发支出 {rnd[-1] / 1000:.1f} 兆韩元"
            + ("创季度新高" if record else "")
            + (f"，但占收入降到 {intensity[-1]:.1f}%" if opposite_ways else
               f"，占收入 {intensity[-1]:.1f}%")
        ),
        "xlabels": labels,
        "bar": {"name": "研发支出（销管费用之内）", "color": "NAVY",
                "values": rounded([v / 1000 for v in rnd], 2), "yfmt": "f1"},
        "line": {"name": "研发 / 收入", "color": "GOLD",
                 "values": rounded(intensity, 2), "yfmt": "pct0"},
        "ylab": "兆韩元",
        "ylab2": "研发 / 收入",
        "yfmt": "f0",
        "note": (
            ("两条线方向相反，是这一页反复出现的同一件事：分子在涨，分母涨得更快。"
             if opposite_ways else "")
            + f"研发支出本季 {rnd[-1] / 1000:.1f} 兆韩元、环比 "
            f"{pct_change(rnd[-1], rnd[-2]):+.0f}%"
            + ("，是季度历史新高" if record else "")
            + f"；{'但' if opposite_ways else ''}研发强度从 {first} 的 {intensity[0]:.1f}% "
            f"{rise_or_fall(intensity[0], intensity[-1], '升到', '降到')} {intensity[-1]:.1f}%。"
            "研发列在销管费用之内，不是单独的报表行。"
        ),
        "src_extra": SRC_DECK + src_dart(n) + "研发强度为研发支出除以合并收入 D。",
    }
    return [cash_chart, net_cash_chart, days_chart, elim_chart, rnd_chart]


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    fin = staging["financials_krw_bn"]
    memory = staging["segment_revenue_krw_tn"]["memory"][-1]
    return [f"合并收入 {fin['revenue'][-1] / 1000:.1f} 兆韩元",
            f"营业利润率 {fin['operating_profit'][-1] / fin['revenue'][-1] * 100:.1f}%",
            f"Memory 占收入 {memory * 1000 / fin['revenue'][-1] * 100:.1f}%"]


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    n = len(periods)
    labels = [compact_period(period) for period in periods]
    der = derived(staging)
    fin = staging["financials_krw_bn"]
    seg_rev = staging["segment_revenue_krw_tn"]
    seg_op = staging["segment_operating_profit_krw_tn"]
    cash = staging["cash_flow_krw_tn"]
    bits = staging["memory_bit_and_price"]
    prov = staging["provisional_vs_final"]

    latest = latest_block(
        staging,
        period=periods[-1],
        period_end=staging["period_ends"][-1],
        release_date=staging["final_release_dates"][-1])
    # One-quarter blocks: absent means this quarter has no such story and the
    # page leaves that part out; stamped with another quarter stops the build.
    story = stamped_block(staging, "quarter_story", periods[-1])
    guidance = stamped_block(staging, "guidance", periods[-1])
    kpi = stamped_block(staging, "next_kpi", periods[-1])
    if kpi is None:
        raise ValueError("series block `next_kpi` is missing: the tracking section has no thresholds")
    if guidance is not None:
        if guidance["quarter"] != shift_period(periods[-1], 1):
            raise ValueError(f"series block `guidance` guides {guidance['quarter']!r}, but the quarter "
                             f"after {periods[-1]!r} is {shift_period(periods[-1], 1)!r}: "
                             "update it or remove it")
        if guidance["guides_financials"] or guidance["asp_guided"]:
            # Every section of this page is built on the company giving no
            # revenue, margin or profit guidance and never guiding price. A
            # quarter where it does needs the guided-record charts the other
            # pages have, not a changed sentence.
            raise ValueError("series block `guidance` says the company guided a financial figure or "
                             "a price; this page's first section is built on it guiding neither")
    release_label = f"Samsung {deck_period(periods[-1])} Earnings Release"
    if not any(item["label"].startswith(release_label) for item in staging["sources"]):
        raise ValueError(f"series `sources` has no entry labelled {release_label!r}: "
                         "add this quarter's release with the roll")
    ir_page = next(item for item in staging["sources"]
                   if item["label"].startswith("Samsung IR — Earnings Release"))

    facts = quarter_facts(staging, der)
    settled_ex = bit_delivery_charts(staging, facts, guidance)
    highlight_ex = quarter_charts(staging, der, labels, facts, story)
    next_ex = tracking_charts(staging, der, labels, facts, kpi, story, guidance)
    routine_ex = routine_charts(staging, der, labels, story)
    resolve_exhibit_refs(
        number_exhibits(settled_ex + highlight_ex + next_ex + routine_ex)
    )

    # ── audit tables ──────────────────────────────────────────────────────────
    income_rows = [
        [
            periods[i],
            f"{der['revenue_tn'][i]:,.2f}",
            f"{fin['gross_profit'][i] / 1000:,.2f}",
            f"{fin['operating_profit'][i] / 1000:,.2f}",
            f"{fin['profit_owners'][i] / 1000:,.2f}",
            f"{fin['eps_krw'][i]:,}",
            f"{der['operating_margin'][i]:.1f}%",
        ]
        for i in range(n)
    ]
    segment_rev_rows = [
        [
            periods[i],
            f"{seg_rev['ds'][i]:.1f}",
            f"{seg_rev['memory'][i]:.1f}",
            f"{der['ds_non_memory'][i]:.1f}",
            f"{seg_rev['dx'][i]:.1f}",
            f"{seg_rev['sdc'][i]:.1f}",
            f"{seg_rev['harman'][i]:.1f}",
            f"{der['segment_sum'][i]:.1f}",
            f"{der['elimination'][i]:.1f}",
        ]
        for i in range(n)
    ]
    segment_op_rows = [
        [
            periods[i],
            f"{seg_op['ds'][i]:.2f}",
            f"{seg_op['dx'][i]:.2f}",
            f"{seg_op['sdc'][i]:.2f}",
            f"{seg_op['harman'][i]:.2f}",
            f"{seg_op['ds'][i] + seg_op['dx'][i] + seg_op['sdc'][i] + seg_op['harman'][i]:.2f}",
            f"{fin['operating_profit'][i] / 1000:.2f}",
            f"{fin['operating_profit'][i] / 1000 - (seg_op['ds'][i] + seg_op['dx'][i] + seg_op['sdc'][i] + seg_op['harman'][i]):+.2f}",
        ]
        for i in range(n)
    ]
    cash_rows = [
        [
            periods[i],
            f"{cash['operating'][i]:.2f}",
            f"{cash['capex_ppe'][i]:.2f}",
            f"{der['fcf'][i]:.2f}",
            f"{cash['depreciation'][i]:.2f}",
            f"{staging['net_cash_krw_tn'][i]:.2f}",
            f"{der['inventory_days'][i]:.0f} 天",
            f"{der['receivable_days'][i]:.0f} 天",
        ]
        for i in range(n)
    ]
    provisional_rows = [
        [
            prov["quarters"][i],
            prov["flash_date"][i],
            f"{prov['flash_revenue_krw_tn'][i]:.2f}",
            f"{prov['flash_operating_profit_krw_tn'][i]:.2f}",
            prov["final_date"][i],
            f"{prov['final_revenue_krw_tn'][i]:.2f}",
            f"{prov['final_operating_profit_krw_tn'][i]:.2f}",
            f"{prov['final_operating_profit_krw_tn'][i] - prov['flash_operating_profit_krw_tn'][i]:+.2f}",
        ]
        for i in range(len(prov["quarters"]))
    ]
    bit_rows = [
        [
            bits["quarters"][i],
            bits["dram_bit_guide_wording"][i] or "本页未取得该季指引原文",
            bits["dram_bit_actual_wording"][i],
            bits["dram_asp_qoq_wording"][i],
            bits["nand_bit_actual_wording"][i],
            bits["nand_asp_qoq_wording"][i],
        ]
        for i in range(len(bits["quarters"]))
    ]
    threshold_entries = kpi["entries"]
    threshold = threshold_table(
        0, "下季跟踪阈值与当前值（原始单位）", threshold_entries, "current", "本季值",
    )
    threshold["headers"] = threshold["headers"] + ["为什么是这条线"]
    threshold["rows"] = [
        row + [entry["why"]] for row, entry in zip(threshold["rows"], threshold_entries)
    ]

    count = cn_count(n)
    tables = [
        {"title": f"{count}季合并损益（兆韩元，EPS 为韩元）",
         "headers": ["期间", "合并收入", "毛利", "营业利润", "归母净利", "基本 EPS", "营业利润率 D"],
         "rows": income_rows},
        {"title": f"{count}季分部收入（兆韩元，含分部间销售）",
         "headers": ["期间", "DS", "其中 Memory", "DS 减 Memory D", "DX", "SDC", "Harman",
                     "四分部合计 D", "抵销额 D"],
         "rows": segment_rev_rows},
        {"title": f"{count}季分部营业利润与加总校验（兆韩元）",
         "headers": ["期间", "DS", "DX", "SDC", "Harman", "分部合计 D", "合并营业利润", "差额 D"],
         "rows": segment_op_rows},
        {"title": f"{count}季现金流与营运资金（兆韩元）",
         "headers": ["期间", "经营现金流", "现金 CapEx", "自由现金流 D", "折旧", "净现金",
                     "库存天数 D", "应收天数 D"],
         "rows": cash_rows},
        {"title": "速报（잠정）与确定数对照（兆韩元）",
         "headers": ["期间", "速报日", "速报收入", "速报营业利润", "确定日", "确定收入",
                     "确定营业利润", "营业利润修正 D"],
         "rows": provisional_rows},
        {"title": "存储量价：公司逐季原话（英文照抄）",
         "headers": ["期间", "上季给出的 DRAM bit 指引", "该季 DRAM bit 实际",
                     "该季 DRAM ASP", "该季 NAND bit 实际", "该季 NAND ASP"],
         "rows": bit_rows},
        threshold,
    ]
    if guidance is not None:
        tables.append({
            "title": f"公司对 {deck_period(guidance['quarter'])} 与全年给出的全部前瞻（原话）",
            "headers": ["项目", "公司原话", "可数字化的部分"],
            "rows": [[item["metric"], item["wording"], item["quantified"]]
                     for item in guidance["items"]],
        })
    tables.append(ai_capex_cycle_table(0))
    for number, table in enumerate(tables, start=1):
        table["n"] = number
    tables = [{"n": table.pop("n"), **table} for table in tables]

    memory_share = der["memory_share"]
    incremental = facts["incremental_gm"]
    articles = []
    if incremental is not None and incremental >= 90:
        articles.append(
            '<article><span>亮点</span><b>增量几乎不带成本</b>'
            f'<p>收入环比 {facts["delta_rev"]:+.1f} 兆韩元，'
            f'销货成本只 {facts["delta_cogs"]:+.1f}，增量毛利率'
            + ("近 100%" if incremental >= 99 else f" {incremental:.0f}%")
            + '。</p></article>')
    if memory_share[-1] > 50:
        articles.append(
            '<article><span>结构</span><b>集团已经是一家存储公司</b>'
            f'<p>Memory 占合并收入 {memory_share[-1]:.1f}%（{labels[0]} {memory_share[0]:.1f}%）'
            + (f'；DS 里的非存储部分{count}季没有增长' if facts["non_memory_flat"] else "")
            + '。</p></article>')
    if guidance is not None and not guidance["asp_guided"] and facts["price_dominates"]:
        articles.append(
            '<article><span>存疑</span><b>公司指引的是量，决定业绩的是价</b>'
            '<p>唯一前瞻数字是下季 bit 出货的定性区间；对 ASP 一个字都不给。</p></article>')

    headline = (
        f"合并收入 {der['revenue_tn'][-1]:.1f} 兆韩元、营业利润 "
        f"{fin['operating_profit'][-1] / 1000:.1f} 兆韩元，营业利润率 "
        f"{der['operating_margin'][-1]:.1f}%；"
        + (f"环比增量里 {incremental:.0f}% 直接落进毛利；" if incremental is not None else "")
        + f"Memory {'已' if memory_share[-1] > memory_share[0] else ''}占合并收入 {memory_share[-1]:.1f}%"
        + (f"，而同一季 DX 分部录得{dx_loss_words(facts, n)}营业亏损 {seg_op['dx'][-1]:.1f} 兆韩元 —— "
           "集团同时坐在这轮存储涨价的两边。" if facts["dx_negative"] else
           f"，DX 分部营业利润 {seg_op['dx'][-1]:.1f} 兆韩元。")
    )

    fx_note = "全页以韩元列示，不折算美元。三星本身不发布美元财务数字，折算会在页面上制造一个任何申报里都不存在的数"
    if story and story.get("krw_usd_average_yoy_depreciation_pct") is not None:
        fx_note += (f"；而 {iso_period(periods[-1])} 韩元兑美元季度均价较去年同期贬值 "
                    f"{story['krw_usd_average_yoy_depreciation_pct']:.1f}%，"
                    "折算还会把汇率腿混进本页真正想读的价格周期里")
    fx_note += "。"
    if story and story.get("fx_operating_profit_qoq_krw_tn") is not None:
        impact = story["fx_operating_profit_qoq_krw_tn"]
        fx_note += (f"公司自己披露的汇率影响是：{iso_period(periods[-1])} 美元{story['usd_move']}对营业利润的"
                    f"环比{'正向' if impact > 0 else '负向'}影响约 {abs(impact):.1f} 兆韩元。")

    seg_gap = max(abs(fin["operating_profit"][i] / 1000 - sum(seg_op[key][i] for key in DIVISIONS))
                  for i in range(n))
    seg_bound = max(0.1, math.ceil(seg_gap * 10) / 10)
    mapping_words = "、".join(f"{words} 记 {low}–{high}%"
                             for words, (low, high) in bits["band_mapping"].items())
    gap = [f - p for f, p in zip(prov["final_operating_profit_krw_tn"],
                                 prov["flash_operating_profit_krw_tn"])]
    prov_count = cn_count(len(gap))
    capex_qoq = cash["capex_ppe"][-1] - cash["capex_ppe"][-2]
    notes = [
        "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
        "三星电子不是 SEC 注册人。EDGAR 上 CIK 0000879316 名下 251 份申报全部是 SC 13D/13G、SC 14D1/14D9、Form 3/4 这类持股与要约表格，最新一份停在 2015-01-20，没有 20-F、没有 6-K、没有 F-1。本页因此没有任何 EDGAR 来源，全部数据来自公司自行发布的季度 Earnings Release 与 DART 电子公告，两者互为独立读数。",
        fx_note,
        "合并损益按十亿韩元记录、分部与现金流按公司披露的兆韩元记录，两套精度不同是因为公司本身用两种精度发布，本页不做统一。",
        f"分部收入含分部间销售，四个分部之和大于合并收入；分部营业利润侧没有抵销，可以直接加总，逐季加总与合并数的差在 ±{seg_bound:.1f} 兆韩元以内。抵销额一行公司没有披露，本页由减法得出并标注 D。",
        "公司在 DS 之下只披露 Memory 一行收入。Memory 的营业利润、System LSI 与 Foundry 的收入和利润、DRAM 与 NAND 的分别口径、HBM 的收入与占比，"
        f"{count}个季度一次都没有披露过。页面上出现的「DS 减 Memory」是减法残值，且含 Foundry 为自家 HBM 生产 base die 的内部收入，绝对水平不精确。",
        f"第一节 bit 出货图的区间与实际值，是本页对公司定性措辞的数值化读数，公司从未给过数字：{mapping_words}，实际值取所述措辞区间的中点。原话逐季列在核对表里，读者可以自行改用别的映射。",
        f"速报与确定数的对照只有{prov_count}个季度，因为更早季度的速报公告原文本页没有取得。"
        + (f"{prov_count}季全部为正上修，但{prov_count}个观测不足以支撑「总是上修」这一结论。"
           if all(value > 0 for value in gap) else
           f"{prov_count}季里 {sum(1 for value in gap if value > 0)} 季上修、{sum(1 for value in gap if value < 0)} 季下修。")
        + "速报的营业收入按兆韩元取整发布，所以收入两次之间的差主要是取整而非修正，本页因此只对营业利润作图。",
        f"第三节的阈值是本地研究设定，不是公司指引，也不构成评级或投资建议；「距阈值余量」统一为正值代表安全侧。DX 分部那条阈值取 {next(e['threshold'] for e in kpi['entries'] if e['metric'] == 'DX 分部营业利润率'):.0f}% 而不是 0，是因为距零阈值的百分比余量在算术上没有定义。",
    ]
    bonus = (story or {}).get("special_bonus")
    if bonus:
        notes.append(
            f"本季销管费用含公司口径为「{bonus['basis']}的 {bonus['pct']:.1f}%」的特别绩效奖金一次性补提，"
            f"{deck_short(bonus['prior_quarter'])} 为{bonus['prior_quarter_accrual']}，两季费用基数因此不可比。"
            + ("" if bonus["capitalized_split_disclosed"] else
               "公司未拆分其中被资本化进在产品存货、递延至下半年的金额，本页也不估算。"))
    if story and story.get("accrual_capex_krw_tn") is not None:
        accrual_qoq = story["accrual_capex_qoq_krw_tn"]
        opposite = (accrual_qoq > 0) != (capex_qoq > 0)
        accrual_qoq_text = minus_sign(f"{accrual_qoq:+.1f}")
        capex_qoq_text = minus_sign(f"{capex_qoq:+.1f}")
        notes.append(
            f"资本开支存在两个口径{'且方向相反' if opposite else ''}：公司电话会给的应计口径本季 "
            f"{story['accrual_capex_krw_tn']:.1f} 兆韩元、环比 {accrual_qoq_text}，"
            f"现金流量表的购置 PP&E 为 {cash['capex_ppe'][-1]:.2f} 兆韩元、环比 {capex_qoq_text}。"
            + ("" if story["accrual_capex_reconciled"] else "公司没有提供两者的调节。")
            + f"本页图上画的是现金流量表口径，因为它{count}季齐全且定义一致。")
    notes += [
        "三星每季披露两次，且两次在 DART 上都标注为「잠정」（暂定），因为完整财报同样发布于外部审阅完成之前。本页 release_date 取月末完整财报日，不取季末速报日。",
        "本页只发布公司披露值、可复算的简单派生值，以及明确标注为卖方估计的第三方数字；D 标记代表 Derived / 自算。市面上流传的 Foundry 亏损额、HBM 收入、DRAM 与 NAND 分别收入均为卖方估计，本页不予采用。",
        f"本页已知未接入：HBM 的任何量化序列（公司不披露）、DRAM 与 NAND 的分别收入、智能手机出货量的完整{count}季序列（仅个别季度在电话会上给过绝对数）、地区与客户结构、股份回购的完整{count}季序列（现金流量表该行只在部分季度的简报中单列）、以及 {iso_period(periods[0])} 之前的历史。",
        "电话会文字稿仅链接公司官方 IR 托管版本，公开仓不复制原件或逐字全文；页面内引用的英文原话为逐字短句引用。",
    ]

    audit_words = {"unaudited": "外部审阅前的初步数", "reviewed": "外部审阅后的数"}[latest["audit_status"]]
    return {
        "schema_version": "quarterly-dashboard/samsung-v1",
        "page": {"slug": "samsung", "language": "zh-CN"},
        "company": {
            "ticker": "005930.KS",
            "name": "Samsung Electronics Co., Ltd.",
            "group": "semiconductor_ai",
            "accounting_standard": "K-IFRS",
        },
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · 005930.KS",
        "title": f"Samsung Electronics（005930.KS）：{periods[-1]} 季报仪表盘",
        "subtitle": (
            f"截至 {latest['period_end']} · 发布 {latest['release_date']} · K-IFRS 合并 · {audit_words} · "
            "全部以韩元列示，不折美元"
        ),
        "headline": headline,
        "brief": (
            f'<h4>本季{cn_count(len(articles))}条主线</h4><div class="takeaway-grid">'
            + "".join(articles)
            + '</div>'
        ),
        "source": (
            f'Source: <a href="{ir_page["url"]}" '
            'rel="noopener">Samsung Electronics Investor Relations</a>'
            f'（{deck_period(periods[-1])} Earnings Release 与电话会）与 '
            '<a href="https://dart.fss.or.kr/dsab007/main.do" rel="noopener">DART 电子公告</a>。'
            '三星不是 SEC 注册人，本页没有任何 EDGAR 来源。'
        ),
        "source_url": ir_page["url"],
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {
                "id": "settled",
                "title": "一、公司到底指引了什么，兑现了吗",
                "description": (
                    "三星不提供收入、毛利率或营业利润的数字指引，所以这一节不是常规的指引兑现。"
                    "公司唯一给的前瞻数字是下一季 DRAM 与 NAND 的出货 bit 增速，而且是定性措辞；"
                    f"价格只在事后回顾时说。{cn_count(len(settled_ex))}张图分别是：这条唯一的指引兑现得怎么样、"
                    "同期没有被指引的价格走了多少、以及季末速报数到月末确定数之间被改动了多少。"
                ),
                "exhibits": settled_ex,
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": (
                    "收入与利润率、分部结构、增量的成本构成，以及 DS 之下那条唯一披露的 Memory 收入线。"
                ),
                "exhibits": highlight_ex,
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": "当前值离阈值还有多远，统一用「距阈值余量」口径；阈值为本地设定，不是公司指引。",
                "exhibits": next_ex,
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": "现金流与资本强度、净现金、营运资金、分部间抵销与研发强度。",
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": notes,
        "footer": "Samsung Electronics quarterly results · 数据来自公司公开披露、DART 公告与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "samsung.js"), payload, "samsung")
    shell_dir = ROOT / "samsung"
    shell_dir.mkdir(exist_ok=True)
    # Rendered here, not at import: the shell stamps the payload's content hash
    # into its <script src>, so it has to be built after write_dash.
    (shell_dir / "index.html").write_text(
        render_shell("005930.KS", "samsung"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(
        f"Samsung page: {charts} charts in {len(payload['sections'])} sections "
        f"+ {len(payload['tables'])} audit tables"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
