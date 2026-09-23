#!/usr/bin/env python3
"""Build the TJX quarterly-results page.

Same four-part, chart-led shape as the other company pages (上季兑现 → 本季重点
→ 下季跟踪 → 长期常规).  TJX's fiscal year ends at the end of January, so every
label here is the calendar quarter the fiscal one mostly covers: the company's
FY(N) Qk is this page's Qk (N−1).

What TJX brings is a long guidance record.  Every quarterly earnings 8-K EX-99.1
carries an Outlook paragraph, and from Q1 FY2013 onward that paragraph guides
next-quarter diluted EPS in the same sentence structure, followed by the
consolidated comp growth the EPS range rests on.  Pretax profit margin joins the
paragraph in 2022, so the records differ in length and each chart is drawn over
its own.  Two things stop "almost never below the range" from being a
tautology, and both are on the charts: the outlook goes out with the previous
quarter's results, weeks into the quarter it guides, and the company withdrew
one quarter's guidance and then withheld guidance for seven quarters in
2020-2021.

Rolling the page is a data edit (CLAUDE.md §9): every period label, date, count,
tally, rank ("以来最低", "第一次") and comparison below is computed from
``series/tjx.json``, and the sentences that claim something about a whole
record print only while the record says so.  What one quarter's release or call
says sits in blocks stamped with that quarter and read through
``board.stamped_block`` -- ``prior_kpi`` / ``next_kpi`` / ``followup_closure``
(the local thresholds, whose current values are measured from the series),
``ytd_usd_m`` (the year-to-date cash-flow columns), ``full_year_outlook``,
``one_off_usd_m``, ``adjusted_segment_margins_pct``, ``store_plan``,
``guidance`` and ``quarter_story``.  A block stamped with another quarter stops
the build; an absent story block takes its sentences with it.  A new miss in the
guidance record stops the build until ``miss_notes`` says why.

What stays in code is fixed history: the 2018 two-for-one split, the 2022 U.S.
comp basis, the e-commerce comp boundary, the pandemic fiscal year.

Published numbers are company-reported or transparent arithmetic.  Market
expectations are labelled as such, with no broker attribution.
"""

from __future__ import annotations

import datetime
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
    minus_sign,
    number_exhibits,
    stamped_block,
    threshold_exhibit,
    threshold_table,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "tjx.json"
DATA_DIR = ROOT / "data"

SEGMENTS = ("marmaxx", "homegoods", "canada", "international")
SEGMENT_NAMES = {"marmaxx": "Marmaxx", "homegoods": "HomeGoods", "canada": "Canada",
                 "international": "International"}
SEGMENT_TITLE_NAMES = {"marmaxx": "Marmaxx", "homegoods": "HomeGoods", "canada": "加拿大",
                       "international": "国际"}
AUDIT_WORDS = {"unaudited": "未审计", "audited": "已审计"}
CN_QUARTER = {1: "一", 2: "二", 3: "三", 4: "四"}
# Year-to-date wording by the fiscal quarter the page ends on: the cash-flow
# statement in a first-quarter release is the quarter itself, in a fourth-
# quarter release it is the year.
YTD_LONG = {1: "一季度", 2: "上半年", 3: "前三季", 4: "全年"}
YTD_SHORT = {1: "一季度", 2: "半年", 3: "前三季", 4: "全年"}
YTD_REST = {1: "后三季", 2: "下半年", 3: "第四季"}

# ── fixed history ────────────────────────────────────────────────────────────
# FY2021 is the year the stores shut; it is named where the long charts would
# otherwise read it as a baseline.
PANDEMIC_YEAR = "FY2021"
# Comparable sales include e-commerce from the quarter ended 2025-05-03 (FY2026
# Q1; the release footnote reads "Comparable sales for FY2026 include
# e-commerce"), and the earlier quarters were never restated.
ECOMMERCE_COMP_FROM = "Q1 2025"
QUARTER_DAYS = 91


def compact_period(period: str) -> str:
    """``'Q2 2026'`` → ``'Q2'26'``."""
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


def _ordinal(period: str) -> int:
    """``'Q2 2026'`` → a running quarter number, so gaps in the axis are findable."""
    quarter, year = period.split()
    return int(year) * 4 + int(quarter[1])


def fiscal_parts(label: str) -> tuple[int, int]:
    """``'FY2027Q2'`` → ``(2027, 2)``."""
    return int(label[2:6]), int(label[-1])


def fiscal_display(label: str) -> str:
    """``'FY2027Q2'`` → ``'FY2027 Q2'``."""
    year, quarter = fiscal_parts(label)
    return f"FY{year} Q{quarter}"


def cn_year_quarter(period: str) -> str:
    """``'Q1 2025'`` → ``'2025 年第一季'``."""
    quarter, year = period.split()
    return f"{year} 年第{CN_QUARTER[int(quarter[1])]}季"


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    # a change that rounds to nothing prints as +0.0, not -0.0
    return f"{0.0 if round(value, digits) == 0 else value:+.{digits}f}{suffix}"


def rounded(values: list[float | None], digits: int = 6) -> list[float | None]:
    return [None if value is None else round(value, digits) for value in values]


def usd_eps(value: float) -> str:
    """A per-share amount the way the record holds it: split-adjusted halves keep
    their half cent (US$0.225), everything else prints in cents."""
    return f"{value:.3f}" if abs(round(value, 2) - value) > 1e-9 else f"{value:.2f}"


def since_low(values: list[float | None], labels: list[str], index: int,
              trailing: int = 4) -> str | None:
    """The label since which ``values[index]`` is the lowest, or None.

    Returns the most recent earlier label whose value is at or below this one,
    or ``""`` when no earlier value is. Returns None unless the value is below
    every one of the ``trailing`` values before it -- a quarter that is merely
    lower than last quarter is not a low.
    """
    current = values[index]
    earlier = [(i, v) for i, v in enumerate(values[:index]) if v is not None]
    if current is None or len(earlier) < trailing:
        return None
    if any(v <= current for _, v in earlier[-trailing:]):
        return None
    below = [i for i, v in earlier if v <= current]
    return labels[below[-1]] if below else ""


def spaced(head: str, tail: str) -> str:
    """Join two pieces of prose, with the space this site puts between CJK and Latin text."""
    if head and tail and (head[-1].isascii() or tail[0].isascii()) and not tail[0].isspace():
        return f"{head} {tail}"
    return head + tail


def listed(items: list[str]) -> str:
    """``['A', 'B', 'C']`` → ``'A、B 与 C'``."""
    return items[0] if len(items) == 1 else "、".join(items[:-1]) + " 与 " + items[-1]


def cn_tenths(share: float) -> str:
    """0.600 → 「六成」."""
    return f"{cn_ordinal(round(share * 10))}成"


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
    "指引区间来自各季业绩 8-K 的 EX-99.1 新闻稿末尾那段 Outlook，下一季与全年的指引写在同一段里；"
    "实际值来自随后一季的业绩 8-K —— 每股收益与税前利润率取 Financial Summary 合并损益表，"
    "comp 取 Comparable Sales 分部表。"
)


# ── the quarter's blocks ─────────────────────────────────────────────────────
def page_period(staging: dict) -> str:
    return staging["periods"][-1]


def block(staging: dict, key: str) -> dict | None:
    return stamped_block(staging, key, page_period(staging))


def story_block(staging: dict) -> dict:
    return block(staging, "quarter_story") or {}


def fiscal_quarter(staging: dict) -> int:
    return fiscal_parts(staging["fiscal_labels"][-1])[1]


def ytd_block(staging: dict) -> dict:
    """The year-to-date columns of this quarter's release, [a year ago, now]: required.

    The cash-flow lines are the release's; net sales and corporate expense are the
    sum of the fiscal year's quarters already in the series, and capex is the filed
    year-to-date property additions the series carries for every quarter, so all
    three are read here rather than typed a second time.
    """
    ytd = block(staging, "ytd_usd_m")
    if ytd is None:
        raise ValueError("series `ytd_usd_m` is missing: every release prints its year-to-date "
                         "cash-flow columns, add this quarter's")
    fq = fiscal_quarter(staging)

    def year_to_date(values: list[float]) -> list[float]:
        return [round(sum(values[-fq - 4:-4]), 6), round(sum(values[-fq:]), 6)]
    capex = staging["financials"]["property_additions_ytd_usd_m"]
    return {**ytd,
            "net_sales": year_to_date(staging["financials"]["net_sales_usd_m"]),
            "general_corporate_expense": year_to_date(staging["segments_usd_m"]["general_corporate_expense"]),
            "capital_expenditures": [capex[-5], capex[-1]]}


def quarter_weeks(staging: dict) -> int:
    ends = staging["period_ends"]
    days = (datetime.date.fromisoformat(ends[-1]) - datetime.date.fromisoformat(ends[-2])).days
    if days % 7:
        raise ValueError(f"period_ends {ends[-2]} → {ends[-1]} is not a whole number of weeks")
    return days // 7


def release_source(staging: dict) -> dict:
    """This quarter's release in `sources`, found by its fiscal label and date."""
    fiscal = fiscal_display(staging["fiscal_labels"][-1])
    release = staging["release_dates"][-1]
    for item in staging["sources"]:
        if fiscal in item["label"] and release in item["label"]:
            return item
    raise ValueError(f"series `sources` has no entry labelled {fiscal!r} with {release!r}: "
                     "add this quarter's release")


def previous_period(period: str) -> str:
    quarter, year = int(period[1]), int(period.split()[1])
    return f"Q4 {year - 1}" if quarter == 1 else f"Q{quarter - 1} {year}"


def quarter_starts(staging: dict) -> list[datetime.date]:
    """The first day of each guided quarter: the day after the quarter before it ended.

    Quarter ends come from the series; the guided quarters before the series
    starts (2012-2015) read theirs from `early_quarter_ends`, as printed in each
    release's first paragraph.
    """
    record = staging["quarterly_guidance_history"]
    ends = {**record.get("early_quarter_ends", {}), **dict(zip(staging["periods"], staging["period_ends"]))}
    starts = []
    for quarter in record["quarters"]:
        before = previous_period(quarter)
        if before not in ends:
            raise ValueError(f"quarterly_guidance_history.early_quarter_ends has no end for {before!r}, "
                             f"the quarter before guided {quarter!r}")
        starts.append(datetime.date.fromisoformat(ends[before]) + datetime.timedelta(days=1))
    return starts


def publication_lags(staging: dict) -> list[int]:
    """Days between the start of each guided quarter and the release that guided it."""
    record = staging["quarterly_guidance_history"]
    return [(datetime.date.fromisoformat(p) - start).days
            for start, p in zip(quarter_starts(staging), record["guidance_published"])]


def lag_words(staging: dict) -> dict:
    record = staging["quarterly_guidance_history"]
    lags = publication_lags(staging)
    lo, hi = min(lags), max(lags)
    latest_q = [fiscal_parts(label)[1] for label, lag
                in zip(record["fiscal_labels"], lags) if lag == hi]
    return {
        "lo": lo, "hi": hi, "mean": statistics.fmean(lags),
        "timing": f"该季<b>开始后 {lo}–{hi} 天</b>",
        "q1_latest": all(q == 1 for q in latest_q),
        "fraction": f"{cn_fraction(lo / QUARTER_DAYS)}到{cn_fraction(hi / QUARTER_DAYS)}",
    }


def withdrawn_guidance(record: dict) -> dict:
    """Quarters whose published range the company withdrew before reporting them."""
    return record.get("withdrawn_guidance", {})


def scored_range(record: dict, lo_key: str, hi_key: str) -> tuple[list, list]:
    """One guided metric's range as it is scored.

    The endpoints a release printed stay in the series. A quarter whose range
    the company then withdrew is treated like the quarters it declined to guide:
    there is no bound left to clear, so it is neither a hit nor a miss, and the
    charts leave it out rather than drawing a bar against a withdrawn number.
    """
    gone = withdrawn_guidance(record)
    return ([None if q in gone else v for q, v in zip(record["quarters"], record[lo_key])],
            [None if q in gone else v for q, v in zip(record["quarters"], record[hi_key])])


def withheld_words(record: dict) -> dict:
    releases = record["withheld_releases"]
    gap = record["guidance_gap_quarters"]
    first, last = releases[0], releases[-1]
    quarters = record["quarters"]
    gone = withdrawn_guidance(record)
    resumed = next(index for index in range(1, len(quarters))
                   if _ordinal(quarters[index]) - _ordinal(quarters[index - 1]) > 1)
    # The last quarter before the gap that still has a range to score: a range
    # withdrawn just before the gap joins it on the axis.
    before = resumed - 1
    while before > 0 and quarters[before] in gone:
        before -= 1
    withdrawn = [q for q in quarters[before + 1:resumed] if q in gone]
    return {
        "span": (f"{int(first[:4])} 年 {int(first[5:7])} 月", f"{int(last[:4])} 年 {int(last[5:7])} 月"),
        "releases": cn_count(len(releases)),
        "gap": len(gap),
        "before": quarters[before],
        "after": quarters[resumed],
        "resumed": resumed,
        "withdrawn": withdrawn,
        "label": ((f"{'、'.join(compact_period(q) for q in withdrawn)} 指引撤回、其后" if withdrawn else "")
                  + f"指引中断 {len(gap)} 个季度（COVID-19）"),
    }


def withdrawal_sentence(record: dict) -> str:
    """What each withdrawn range was, and what the page does with it."""
    return "".join(
        f"{quarter} 的区间（{item['published']} 随上一季业绩发布）已由 {item['withdrawn']} 的 8-K"
        f"（Item {item['item']}）撤回，本页按撤回处理：与不给指引的季度一样不计分、不画柱。"
        for quarter, item in withdrawn_guidance(record).items())


def break_positions(record: dict, indices: list[int]) -> list[int]:
    """Where a chart drawn over these record indices skips quarters: the first index after each jump."""
    quarters = record["quarters"]
    return [k for k in range(1, len(indices))
            if _ordinal(quarters[indices[k]]) - _ordinal(quarters[indices[k - 1]]) > 1]


def comp_break_label(record: dict, before: int, after: int) -> str:
    """What the consolidated-comp axis skips between two record indices.

    Three different things can sit in the jump -- a withdrawn range, quarters
    the company declined to guide, and guided quarters whose comp guidance was
    for the U.S. only -- and the label names each rather than one of them.
    """
    quarters = record["quarters"]
    gone = withdrawn_guidance(record)
    between = quarters[before + 1:after]
    parts = []
    withdrawn = [q for q in between if q in gone]
    if withdrawn:
        parts.append(f"{'、'.join(compact_period(q) for q in withdrawn)} 指引撤回")
    unguided = _ordinal(quarters[after]) - _ordinal(quarters[before]) - 1 - len(between)
    if unguided:
        parts.append(f"{unguided} 季不给指引")
    us_only = [q for q in between if q not in gone]
    if us_only:
        parts.append(f"{len(us_only)} 季只指引美国 comp")
    return "、".join(parts)


def miss_note(record: dict, metric: str, index: int, values: dict) -> str:
    """Why one quarter fell below its guided range -- read from `miss_notes`.

    A roll that adds a miss has to say why in the series file; the page will
    not print a tally of misses with one of them unexplained.
    """
    quarter = record["quarters"][index]
    notes = record.get("miss_notes", {}).get(metric, {})
    if quarter not in notes:
        raise ValueError(f"quarterly_guidance_history.miss_notes.{metric} says nothing about "
                         f"{quarter!r}: a quarter below its guided range needs its reason")
    return fill_story(notes[quarter], values)


def miss_sentence(record: dict, metric: str, below: list[int], labels: list[str],
                  values: dict) -> str:
    return "，".join(labels[i] + miss_note(record, metric, i, values.get(i, {})) for i in below)


# ── section one: the guided record ──────────────────────────────────────────
def guidance_delivery_charts(staging: dict) -> tuple[list[dict], dict]:
    """Three guided metrics, their own windows, one shape.

    TJX guides next-quarter diluted EPS, pretax profit margin and consolidated
    comparable sales in the same Outlook paragraph, but the three records do not
    all start at the same quarter.  Each chart is drawn over its own metric's
    record rather than over the shortest one they share, and each title says how
    long that record is.

    Where the adjusting event postdated the range (or the range said it left the
    item out) and the company printed an adjusted figure that removes only that
    item -- the basis it judged the quarter against plan on -- the adjusted
    figure is what the chart compares (``scored_on_adjusted``).  A range the
    company withdrew is not scored at all (``withdrawn_guidance``).
    """
    record = staging["quarterly_guidance_history"]
    quarters = record["quarters"]
    labels = [compact_period(quarter) for quarter in quarters]
    lag = lag_words(staging)
    timing = lag["timing"]
    dev_timing = f"（口径提醒：本组每张图的指引都是在{timing}才发布的。）"
    held = withheld_words(record)
    covid_note = (
        "<b>红色竖线是记录里的断口。</b>"
        f"公司在 {held['span'][0]}到 {held['span'][1]}的{held['releases']}份业绩稿里"
        f"写明 is not providing guidance at this time，连续 {held['gap']} 个会计季没有给出任何数字指引"
        + (f"；在那之前，{withdrawal_sentence(record)}" if held["withdrawn"] else "。")
        + f"横轴在这里从 {held['before']} 直接跳到 {held['after']}，中间的季度不是漏掉，而是本来就没有指引可对。"
        "一份只数「没跌破过多少次」的记录会把这段一起删掉，这里保留它。"
    )
    lag_note = (
        "<b>先读这一句，再读命中率。</b>TJX 的下一季指引是随上一季业绩一起发布的，"
        "而它在季末约三周后发业绩，所以这段 Outlook 落在<b>它所指引的那个季度之内</b>："
        f"本记录里最早的一次是第 {lag['lo']} 天、最晚的一次是第 {lag['hi']} 天，平均第 {lag['mean']:.0f} 天，"
        f"即公司给出区间时该季已经过去{lag['fraction']}。"
        + (f"会计季 Q1 最迟（{lag['hi']} 天），因为它要等 2 月的年度业绩发布。" if lag["q1_latest"] else "")
        + "这不是一份事前预测；"
        "一页把「几乎没跌破过」放着不加这句话，就是把同义反复当成发现。"
    )

    eps_lo, eps_hi = scored_range(record, "guide_eps_lo_usd", "guide_eps_hi_usd")
    eps_actual = record["actual_eps_usd"]
    eps_finished = [index for index, value in enumerate(eps_actual)
                    if value is not None and eps_lo[index] is not None]

    above = [i for i in eps_finished if eps_actual[i] > eps_hi[i]]
    below = [i for i in eps_finished if eps_actual[i] < eps_lo[i]]
    inside = len(eps_finished) - len(above) - len(below)

    # ── EPS: level over a readable window, distance over the whole record ────
    # Post-split EPS runs from under a quarter of a dollar to well over a dollar
    # across the full record, so a linear axis over all of it collapses the
    # early ranges to a hairline. The band chart takes the recent window and the
    # scale-free deviation chart carries the rest -- the same split NVIDIA's
    # page makes for the same reason.
    window = 16
    levels = [v for v in eps_lo + eps_hi + eps_actual if v is not None and v > 0]
    eps_band = delivery_band(
        "EX_EPS_RANGE", "摊薄每股收益", labels[-window:], eps_lo[-window:], eps_hi[-window:],
        eps_actual[-window:], fmt="usd2", ylab="US$", unit="US$",
        venue="业绩发布", timing=timing, scope=f"（近 {window} 季）",
        src_extra=SOURCE_8K,
        extra_note=(
            f"<b>整段记录（{len(quarters)} 季指引、{len(eps_finished)} 季已完结并计分）不在这张图上，"
            f"在它的下一张。</b>本图只画最近 {window} 季，因为拆股调整后的每股数"
            f"从 US${usd_eps(min(levels))} 长到 US${usd_eps(max(levels))}，"
            "一条线性纵轴放不下整段记录而不把早年的区间压成一根发丝。"
            + lag_note
        ),
    )

    deviations = [eps_actual[i] / ((eps_lo[i] + eps_hi[i]) / 2) - 1 for i in eps_finished]
    half = len(deviations) // 2
    positive = sum(1 for value in deviations if value > 0)
    years = int(quarters[-1].split()[1]) - int(quarters[0].split()[1])
    if (positive >= 0.9 * len(deviations)
            and statistics.median(deviations[half:]) >= statistics.median(deviations[:half])):
        shape = ("柱子几乎清一色朝上，而且没有随时间收窄 —— 这家公司"
                 + ("十几年来" if 10 <= years < 20 else f"{cn_count(years)}年来")
                 + "一直把下一季的每股收益指引设在自己大概率能过的位置。")
    else:
        shape = ""
    shortfalls = {i: {"shortfall": usd_eps(round(eps_lo[i] - eps_actual[i], 6))} for i in below}
    if len(below) > 1:
        misses = (f"{cn_count(len(below))}次跌破各有各的原因，不是同一类事："
                  + miss_sentence(record, "eps", below, labels, shortfalls) + "。")
    elif below:
        misses = "唯一一次跌破是 " + miss_sentence(record, "eps", below, labels, shortfalls) + "。"
    else:
        misses = ""
    eps_dev = midpoint_deviation(
        "EX_EPS_DEV", "摊薄每股收益", quarters, eps_lo, eps_hi, eps_actual,
        mode="pct", window=len(eps_finished), label=compact_period, bar_labels=False,
        src_extra=SOURCE_8K + "偏离为实际每股收益除以指引中值的自算值。",
        extra_note=(
            f"<b>这才是完整记录：{len(eps_finished)} 个已完结季里 {len(above)} 季高于指引上限、"
            f"{inside} 季落在区间内、{len(below)} 季跌破下限。</b>"
            + shape + misses
            + "2018 年 11 月一拆二之前公布的指引与实际都已除以 2 换算到当前股本，"
            "该换算是精确的；本图取的是比值，拆股本来也约掉了。"
            + covid_note
            + dev_timing
        ),
    )

    # ── pretax profit margin ─────────────────────────────────────────────────
    margin_lo, margin_hi = scored_range(record, "guide_pretax_margin_lo_pct",
                                        "guide_pretax_margin_hi_pct")
    margin_actual = record["actual_pretax_margin_pct"]
    m_start = next(i for i, value in enumerate(margin_lo) if value is not None)
    m_labels = labels[m_start:]
    m_lo, m_hi = margin_lo[m_start:], margin_hi[m_start:]
    m_actual = margin_actual[m_start:]
    m_finished = [i for i, value in enumerate(m_actual) if value is not None]
    m_below = [m_start + i for i in m_finished if m_actual[i] < m_lo[i]]
    if len(m_below) == 1:
        index = m_below[0]
        margin_miss = (f"<b>唯一一次跌破是 {labels[index]} 的 {margin_actual[index]:.1f}% 对 "
                       f"{margin_lo[index]:.1f}–{margin_hi[index]:.1f}%</b>，"
                       + miss_note(record, "pretax_margin", index, {}))
    elif m_below:
        margin_miss = (f"<b>{cn_count(len(m_below))}次跌破：</b>"
                       + miss_sentence(record, "pretax_margin", m_below, labels, {}) + "。")
    else:
        margin_miss = "<b>一次都没有跌破过下限。</b>"

    margin_band = delivery_band(
        "EX_PTM_RANGE", "税前利润率", m_labels, m_lo, m_hi, m_actual,
        fmt="pct1", ylab="%", unit="%", venue="业绩发布", timing=timing,
        src_extra=SOURCE_8K,
        extra_note=(
            f"税前利润率的指引从 {labels[m_start]} 才开始出现在这段 Outlook 里，所以它的记录只有 "
            f"{len(m_labels)} 季，比上面每股收益那条短得多 —— 图只画到数字存在的地方，不往前补。"
            + margin_miss
        ),
    )
    adjusted = [(quarter, item) for quarter, item in scored_adjusted(record).items()
                if quarter in quarters[m_start:] and "pretax_margin" in item["metrics"]]
    verdicts = {item["company_verdict"] for _, item in adjusted}
    margin_dev = midpoint_deviation(
        "EX_PTM_DEV", "税前利润率", quarters[m_start:], m_lo, m_hi, m_actual,
        mode="pp", window=len(m_finished), label=compact_period,
        src_extra=SOURCE_8K + "偏离为实际税前利润率减去指引中值的自算值。",
        extra_note=(
            (f"有{cn_count(len(adjusted))}个季度用的是公司自己的调整后口径，而不是报表口径，因为指引给出时"
             "那件事还不存在："
             + "与 ".join(spaced(f"{compact_period(quarter)} 的", item["event"]) for quarter, item in adjusted)
             + ("都是" if len(adjusted) > 1 else "是") + "指引之后发生的，"
             "拿报表值去对当初的区间，等于让指引为它装不下的事负责。"
             + (f"公司自己也是按调整后口径判定这{cn_count(len(adjusted))}季 {verdicts.pop()} 的。"
                if len(verdicts) == 1 else "")
             if adjusted else "")
            + dev_timing
        ),
    )

    # ── consolidated comparable sales ────────────────────────────────────────
    # The axis carries the quarters that have a consolidated range to score:
    # the withdrawn range, the quarters the company declined to guide and the
    # 2022 quarters guided on U.S. comp only are all left off it, and the jump
    # is marked with what it skips.
    comp_lo, comp_hi = scored_range(record, "guide_comp_lo_pct", "guide_comp_hi_pct")
    comp_actual = record["actual_comp_pct"]
    c_index = [i for i, value in enumerate(comp_lo) if value is not None]
    c_labels = [labels[i] for i in c_index]
    c_lo, c_hi = [comp_lo[i] for i in c_index], [comp_hi[i] for i in c_index]
    c_actual = [None if comp_actual[i] is None else float(comp_actual[i]) for i in c_index]
    c_finished = [i for i, value in enumerate(c_actual) if value is not None]
    c_above = [i for i in c_finished if c_actual[i] > c_hi[i]]
    c_below = [i for i in c_finished if c_actual[i] < c_lo[i]]
    c_inside = [i for i in c_finished if i not in c_above and i not in c_below]
    c_breaks = break_positions(record, c_index)
    c_break_labels = [comp_break_label(record, c_index[k - 1], c_index[k]) for k in c_breaks]
    us_only = [i for i in range(c_index[0], len(quarters))
               if record["guide_comp_lo_pct"][i] is None and quarters[i] not in withdrawn_guidance(record)]
    edge = ""
    if c_inside and all(c_actual[i] == c_hi[i] for i in c_inside) \
            and len({(c_lo[i], c_hi[i]) for i in c_inside}) == 1:
        lo, hi = c_lo[c_inside[0]], c_hi[c_inside[0]]
        edge = (f"落在 {lo:.0f}–{hi:.0f}% 区间上沿的那几季报的都是「+{hi:.0f}%」，"
                f"真值区间是 {hi - 0.5:.1f}–{hi + 0.5:.1f}%，其中一半在区间外 —— "
                "所以「落在区间内」这一格在本图上比在其他图上软。")

    def comp_pct(value: float) -> str:
        return f"{value:+.0f}%" if value else "0%"

    if len(c_below) == 1:
        j = c_below[0]
        comp_misses = (f"<b>唯一一次跌破是 {c_labels[j]} 的 {comp_pct(c_actual[j])} 对 "
                       f"{c_lo[j]:.0f}–{c_hi[j]:.0f}%</b>"
                       + miss_note(record, "comp", c_index[j], {}) + "。")
    elif c_below:
        comp_misses = (f"<b>{cn_count(len(c_below))}次跌破：</b>"
                       + miss_sentence(record, "comp", [c_index[j] for j in c_below], labels, {}) + "。")
    else:
        comp_misses = "<b>一次都没有跌破过下限</b>。"

    comp_band = delivery_band(
        "EX_COMP_RANGE", "合并同店销售", c_labels, c_lo, c_hi, c_actual,
        fmt="pct0", ylab="%", unit="%", venue="业绩发布", timing=timing,
        src_extra=SOURCE_8K,
        break_at=(c_breaks[0] if len(c_breaks) == 1 else c_breaks) if c_breaks else None,
        break_label=(c_break_labels[0] if len(c_break_labels) == 1 else c_break_labels),
        extra_note=(
            "Outlook 段在每股收益区间之后写一句它所依据的合并 comp 区间"
            "（如 This outlook is based upon estimated consolidated comparable store sales growth of …），"
            f"本页从 {c_labels[0]} 起逐季接入，这条记录 {len(c_labels)} 季。"
            f"{len(c_finished)} 个已完结季里 {len(c_above)} 季超出上限、{len(c_inside)} 季落在区间内；"
            + comp_misses
            + "<b>但这张图要打一个折扣：comp 是按整数百分点披露的。</b>"
            + edge
            + (f"{labels[us_only[0]]}–{labels[us_only[-1]]} 公司指引的是<b>美国</b> comp 而不是合并 comp，"
               "口径不同，本页不接进来，横轴在断点处跳过它们。" if us_only else "")
        ),
    )
    mids = [(c_lo[i] + c_hi[i]) / 2 for i in c_finished]
    mode_mid, mode_count = max(((m, mids.count(m)) for m in set(mids)), key=lambda pair: pair[1]) \
        if mids else (None, 0)
    comp_dev = midpoint_deviation(
        "EX_COMP_DEV", "合并同店销售", [quarters[i] for i in c_index], c_lo, c_hi, c_actual,
        mode="pp", window=len(c_finished), label=compact_period,
        src_extra=SOURCE_8K + "偏离为实际 comp 减去指引中值的自算值。",
        extra_note=(
            (f"指引中值这 {len(c_finished)} 季里有 {mode_count} 季是同一个数（{mode_mid:.1f}%），"
             "所以这张图基本等于把实际 comp 重画了一遍 —— 这本身就是读数："
             "公司几乎每季都给同一个区间，真正在动的只有实际值。"
             if mode_count >= 0.9 * len(c_finished) else "")
            + dev_timing
        ),
    )
    # the deviation chart draws finished quarters only, so its breaks are
    # counted along its own axis
    dev_breaks = [k for k in range(1, len(c_finished))
                  if any(c_finished[k - 1] < b <= c_finished[k] for b in c_breaks)]
    if dev_breaks:
        dev_labels = [c_break_labels[next(n for n, b in enumerate(c_breaks)
                                          if c_finished[k - 1] < b <= c_finished[k])]
                      for k in dev_breaks]
        comp_dev["break_at"] = dev_breaks[0] if len(dev_breaks) == 1 else dev_breaks
        comp_dev["break_label"] = dev_labels[0] if len(dev_labels) == 1 else dev_labels

    delivery_rows = []
    for index in range(len(quarters) - 1, -1, -1):
        if len(delivery_rows) >= 20:
            break
        actual_eps = eps_actual[index]
        delivery_rows.append([
            quarters[index],
            record["fiscal_labels"][index],
            record["guidance_published"][index],
            f"${record['guide_eps_lo_usd'][index]:.2f}–{record['guide_eps_hi_usd'][index]:.2f}",
            f"${actual_eps:.2f}" if actual_eps is not None else "待披露",
            (f"{record['guide_pretax_margin_lo_pct'][index]:.1f}–"
             f"{record['guide_pretax_margin_hi_pct'][index]:.1f}%"
             if record["guide_pretax_margin_lo_pct"][index] is not None else "—"),
            (f"{margin_actual[index]:.2f}%"
             if margin_actual[index] is not None else "待披露"),
            (f"{record['guide_comp_lo_pct'][index]:.0f}–{record['guide_comp_hi_pct'][index]:.0f}%"
             if record["guide_comp_lo_pct"][index] is not None else "—"),
            (f"{comp_actual[index]:.0f}%" if comp_actual[index] is not None else "待披露"),
        ])
    delivery_table = {
        "title": (
            f"指引兑现明细（最近 20 季；完整记录 {len(quarters)} 季，"
            f"发布时该季已过去 {lag['lo']}–{lag['hi']} 天）"
        ),
        "headers": ["自然年季度", "公司财季", "指引发布日", "EPS 指引", "EPS 实际",
                    "税前利润率指引", "税前利润率实际", "comp 指引", "comp 实际"],
        "rows": delivery_rows,
    }
    # The deviation chart draws finished, scored quarters only, so the gap is
    # found along its own axis -- the first bar after it -- not at the record
    # index, which the two unreported quarters and the withdrawn one shift.
    eps_dev["break_at"] = next(k for k, i in enumerate(eps_finished) if i >= held["resumed"])
    eps_dev["break_label"] = held["label"]
    charts = [eps_band, eps_dev, margin_band, margin_dev, comp_band, comp_dev]
    return charts, delivery_table


def record_tallies(record: dict) -> dict:
    """The three hit rates the brief quotes, counted the way the charts count them."""
    def tally(lo_key: str, hi_key: str, actual_key: str) -> tuple[int, int, int]:
        low, high = scored_range(record, lo_key, hi_key)
        rows = [(a, lo, hi) for lo, hi, a in zip(low, high, record[actual_key])
                if lo is not None and a is not None]
        return (len(rows), sum(1 for a, _, hi in rows if a > hi), sum(1 for a, lo, _ in rows if a < lo))
    return {
        "eps": tally("guide_eps_lo_usd", "guide_eps_hi_usd", "actual_eps_usd"),
        "margin": tally("guide_pretax_margin_lo_pct", "guide_pretax_margin_hi_pct",
                        "actual_pretax_margin_pct"),
        "comp": tally("guide_comp_lo_pct", "guide_comp_hi_pct", "actual_comp_pct"),
    }


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    fin = staging["financials"]
    # A quarter with no adjusting item has no adjusted EPS of its own: the
    # reported figure is the adjusted one, and the card says which it shows.
    adjusted = fin["adjusted_diluted_eps_usd"][-1]
    return [f"Revenue ${fin['net_sales_usd_m'][-1] / 1000:.2f}B",
            f"Comp {staging['comparable_sales_pct']['consolidated'][-1]:+.0f}%",
            f"Adjusted EPS ${adjusted:.2f}" if adjusted is not None
            else f"Diluted EPS ${fin['diluted_eps_usd'][-1]:.2f}"]


# ── thresholds: the two reports' section 8, line by line ─────────────────────
# A report writes each line as the condition that fires it -- 「<2% = 警示」,
# 「≥4% = 加仓」 -- so an entry carries that comparator as written (`fires`) and
# whether firing is a warning or a target (`kind`). Which side of the line is the
# favourable one follows from the two and is not typed a third time; and it is the
# comparator, not the sign of a headroom, that decides a reading landing exactly on
# an inclusive line (「≤+1%」 fires at +1%, where the headroom is zero).
OPERATORS = {"≥": lambda value, line: value >= line, ">": lambda value, line: value > line,
             "≤": lambda value, line: value <= line, "<": lambda value, line: value < line}

# name on the page, how a reading prints, how a threshold prints
MEASURE_LOOK = {
    "comp_consolidated": ("合并同店销售", "{:+.0f}%", "{:g}%"),
    "comp_marmaxx": ("Marmaxx 同店销售", "{:+.0f}%", "{:+g}%"),
    "gross_margin_adjusted": ("毛利率（有调整项的季度取调整后）", "{:.1f}%", "{:g}%"),
    "pretax_margin_adjusted": ("调整后税前利润率", "{:.1f}%", "{:g}%"),
    "homegoods_margin_adjusted": ("HomeGoods 调整后分部利润率", "{:.1f}%", "{:g}%"),
    "inventory_per_store_yoy": ("每店库存同比", "{:+.0f}%", "{:+g}%"),
    "ross_gap": ("Marmaxx 落后 Ross 的同店差距", "{:.0f}pp", "{:g}pp"),
    "adjusted_eps": ("调整后每股收益", "${:.2f}", "${:.2f}"),
    "ytd_capex_intensity": ("年初至今资本开支 / 销售额", "{:.2f}%", "{:g}%"),
    "fy_capex_plan_high": ("全年资本开支计划上沿", "US${:.1f}B", "US${:g}B"),
}


def threshold_direction(entry: dict) -> str:
    rising = entry["fires"] in ("≥", ">")
    return "up" if rising == (entry["kind"] == "target") else "down"


def reading_words(measure: str, value: float) -> str:
    return minus_sign(MEASURE_LOOK[measure][1].format(value))


def threshold_words(entry: dict) -> str:
    look = MEASURE_LOOK[entry["measure"]][2]
    # a zero line carries no sign: 「≤0%」, not 「≤+0%」
    return minus_sign((look.replace("+", "") if entry["threshold"] == 0 else look).format(entry["threshold"]))


def fiscal_year_to_date(values: list[float | None], fiscal_labels: list[str],
                        index: int) -> float | None:
    """Sum of the fiscal year's quarters through ``index``, or None if one is missing."""
    fq = fiscal_parts(fiscal_labels[index])[1]
    if index - fq + 1 < 0:
        return None
    part = values[index - fq + 1:index + 1]
    return None if any(value is None for value in part) else sum(part)


def quarterly_property_additions(staging: dict) -> list[float | None]:
    """Each quarter's capex: the filed year-to-date figure less the one before it in the year."""
    ytd = staging["financials"]["property_additions_ytd_usd_m"]
    out = []
    for index, label in enumerate(staging["fiscal_labels"]):
        if fiscal_parts(label)[1] == 1:
            out.append(ytd[index])
        elif index == 0 or ytd[index] is None or ytd[index - 1] is None:
            out.append(None)
        else:
            out.append(round(ytd[index] - ytd[index - 1], 6))
    return out


def measure_series(staging: dict) -> dict[str, list[float | None]]:
    """Every quarterly reading a threshold can be settled on, aligned with `periods`."""
    fin, comp = staging["financials"], staging["comparable_sales_pct"]
    segm, ops = staging["segment_margins_pct"], staging["operations"]
    adj_seg = block(staging, "adjusted_segment_margins_pct")
    ross = staging["peer_comparable_sales_pct"]["ross"]
    sales, labels = fin["net_sales_usd_m"], staging["fiscal_labels"]

    def either(adjusted_key: str, reported_key: str) -> list[float | None]:
        return [a if a is not None else r for a, r in zip(fin[adjusted_key], fin[reported_key])]

    def floats(values: list) -> list[float | None]:
        return [None if value is None else float(value) for value in values]

    homegoods = list(segm["homegoods_margin_pct"])
    if adj_seg:
        homegoods[-1] = adj_seg["homegoods"]["adjusted"]
    ytd_capex = fin["property_additions_ytd_usd_m"]
    intensity = []
    for index in range(len(sales)):
        ytd_sales = fiscal_year_to_date(sales, labels, index)
        intensity.append(None if ytd_sales is None or ytd_capex[index] is None
                         else ytd_capex[index] / ytd_sales * 100)
    return {
        "comp_consolidated": floats(comp["consolidated"]),
        "comp_marmaxx": floats(comp["marmaxx"]),
        "gross_margin_adjusted": either("adjusted_gross_margin_pct", "gross_margin_pct"),
        "pretax_margin_adjusted": either("adjusted_pretax_margin_pct", "pretax_margin_pct"),
        "homegoods_margin_adjusted": homegoods,
        "inventory_per_store_yoy": floats(ops["inventory_per_store_yoy_pct"]),
        "ross_gap": [None if r is None or m is None else float(r - m)
                     for r, m in zip(ross, comp["marmaxx"])],
        "adjusted_eps": either("adjusted_diluted_eps_usd", "diluted_eps_usd"),
        "ytd_capex_intensity": intensity,
    }


def point_measure(staging: dict, name: str) -> float:
    """A reading that is not a quarterly series: it lives in the quarter's own block."""
    if name == "fy_capex_plan_high":
        readings = block(staging, "threshold_readings")
        if readings is None or "fy_capex_plan_usd_bn" not in readings:
            raise ValueError("a threshold measures `fy_capex_plan_high`: add the quarter's filed "
                             "full-year capex plan to `threshold_readings.fy_capex_plan_usd_bn`")
        return float(readings["fy_capex_plan_usd_bn"][1])
    raise ValueError(f"this page does not know how to measure {name!r}")


def evaluate(staging: dict, key: str, value_key: str) -> tuple[dict | None, list[dict]]:
    """A stamped threshold block and its lines, each read now and settled by its comparator.

    `consecutive: n` fires only if the last n readings all fire. An entry with a
    `no_current` reason is listed with no reading (its number exists only once the
    quarter it settles on is reported).
    """
    kpi = block(staging, key)
    if kpi is None:
        return None, []
    series = measure_series(staging)
    entries = []
    for entry in kpi["quantified"]:
        name = entry["measure"]
        if name not in MEASURE_LOOK:
            raise ValueError(f"{key} entry {entry['metric']!r}: this page does not know how to "
                             f"measure {name!r}")
        if entry["fires"] not in OPERATORS or entry["kind"] not in ("warn", "target"):
            raise ValueError(f"{key} entry {entry['metric']!r}: fires must be one of "
                             f"{''.join(OPERATORS)} and kind warn or target")
        item = {**entry, "direction": threshold_direction(entry)}
        if entry.get("no_current"):
            entries.append({**item, value_key: None})
            continue
        values = series.get(name)
        value = values[-1] if values is not None else point_measure(staging, name)
        if value is None:
            raise ValueError(f"{key} entry {entry['metric']!r}: {name!r} has no reading "
                             f"for {page_period(staging)}")
        run = values[-entry.get("consecutive", 1):] if values is not None else [value]
        fired = all(v is not None and OPERATORS[entry["fires"]](round(v, 6), entry["threshold"])
                    for v in run)
        entries.append({**item, value_key: value, "fired": fired, "run": run,
                        "favourable": fired if entry["kind"] == "target" else not fired})
    return kpi, entries


def drawn(entries: list[dict], value_key: str) -> list[dict]:
    """The lines that go on a headroom axis: read now, and not a zero threshold
    (a percentage distance from zero does not exist)."""
    return [entry for entry in entries if entry[value_key] is not None and entry["threshold"] != 0]


def settle_words(entry: dict, value_key: str) -> str:
    """How one line settled, the way a section-one title says it: 「守住上季警示线 2%」."""
    line = f"{spaced('上季', entry['line'])} {threshold_words(entry)}"
    on_line = round(entry[value_key], 6) == entry["threshold"]
    streak = entry.get("consecutive", 1)
    if entry["kind"] == "warn":
        if not entry["fired"]:
            return f"守住{line}"
        return ((f"连续{cn_count(streak)}季" if streak > 1 else "")
                + ("压线触发" if on_line else "击穿") + line)
    return ("压线" if on_line and entry["fired"] else "") + ("达到" if entry["fired"] else "未达到") + line


def row_fired(entries: list[dict], row) -> bool:
    """A row whose legs are joint fires only when every leg fires."""
    legs = [entry for entry in entries if entry["row"] == row]
    return all(entry["fired"] for entry in legs)


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    labels = [compact_period(period) for period in periods]
    period = periods[-1]
    fiscal = fiscal_display(staging["fiscal_labels"][-1])
    fq = fiscal_quarter(staging)
    weeks = quarter_weeks(staging)
    fin = staging["financials"]
    seg = staging["segments_usd_m"]
    segm = staging["segment_margins_pct"]
    comp = staging["comparable_sales_pct"]
    ops = staging["operations"]
    long = staging["long_history"]
    record = staging["quarterly_guidance_history"]
    latest = latest_block(
        staging,
        period=period,
        period_end=staging["period_ends"][-1],
        release_date=staging["release_dates"][-1])
    audit = AUDIT_WORDS.get(latest["audit_status"])
    if audit is None:
        raise ValueError(f"latest.audit_status {latest['audit_status']!r} is neither "
                         f"{' nor '.join(AUDIT_WORDS)}")
    story = story_block(staging)
    ytd = ytd_block(staging)
    adj_seg = block(staging, "adjusted_segment_margins_pct")
    one_off = block(staging, "one_off_usd_m")
    outlook = block(staging, "full_year_outlook")
    store_plan = block(staging, "store_plan")
    guidance = block(staging, "guidance")
    followup = block(staging, "followup_closure")
    prior_kpi, settled = evaluate(staging, "prior_kpi", "actual")
    next_kpi, forward = interim_next_entries(staging)
    for key, stamped in (("followup_closure", followup), ("prior_kpi", prior_kpi)):
        if stamped is not None and stamped["set_in"] != previous_period(period):
            raise ValueError(f"series block `{key}` settles what was set in {stamped['set_in']!r}, "
                             f"but the quarter before {period!r} is {previous_period(period)!r}")
    source = release_source(staging)
    ytd_long, ytd_short = YTD_LONG[fq], YTD_SHORT[fq]
    lag = lag_words(staging)

    sales = fin["net_sales_usd_m"]
    gross = fin["gross_margin_pct"]
    pretax_margin = fin["pretax_margin_pct"]
    eps = fin["diluted_eps_usd"]
    shares = fin["diluted_shares_m"]
    adjusted_gross = fin["adjusted_gross_margin_pct"]
    stores = ops["store_count"]
    marmaxx_share = seg["marmaxx_sales"][-1] / sales[-1]
    tallies = record_tallies(record)
    eps_n, eps_above, eps_below = tallies["eps"]
    margin_n, margin_above, margin_below = tallies["margin"]
    comp_n, comp_above, comp_below = tallies["comp"]
    raised_today = bool(store_plan) and store_plan["announced"] == staging["release_dates"][-1]

    # Reported gross margin is the long series; the company publishes an adjusted
    # one only in the quarters that have an adjusting item. Both are drawn rather
    # than one being plotted and the other captioned.
    gross_settled = [adjusted_gross[i] if adjusted_gross[i] is not None else gross[i]
                     for i in range(len(gross))]
    mmx = comp["marmaxx"]
    mmx_low = since_low(mmx, labels, len(mmx) - 1)
    capex_now = ytd["capital_expenditures"][-1] / ytd["net_sales"][-1] * 100
    capex_prior = ytd["capital_expenditures"][0] / ytd["net_sales"][0] * 100
    values = {
        "marmaxx_share_tenths": cn_tenths(marmaxx_share),
        "marmaxx_comp": f"{mmx[-1]:+.0f}%",
        "marmaxx_low_since": mmx_low or "",
        "ytd": ytd_short,
        "ytd_long": ytd_long,
        "ytd_capex_intensity": f"{capex_now:.2f}%",
        "ytd_capex_delta": f"{capex_now - capex_prior:.2f}",
        "adjusted_eps": (f"${fin['adjusted_diluted_eps_usd'][-1]:.2f}"
                         if fin["adjusted_diluted_eps_usd"][-1] is not None else f"${eps[-1]:.2f}"),
    }

    # ── section 1: last quarter's local analysis, settled; then the guided record ──
    # (a) the follow-up questions as this quarter's report judged them, (b) the
    # previous report's section-8 lines against this quarter's readings, (c) the
    # company's own guidance record.
    settled_ex = []
    closure_rows = []
    if followup is not None:
        filled = closure_values(staging, record, store_plan)
        settled_ex.append(closure_chart(followup, period))
        closure_rows = [[str(item["n"]), fill_story(item["question"], filled),
                         fill_story(item["evidence"], filled), item["wording"], item["verdict"]]
                        for item in followup["items"]]
    if prior_kpi is not None:
        settled_ex.append(prior_overview(staging, prior_kpi, settled))
        settled_ex.extend(track_charts(staging, prior_kpi, settled, "actual", "prior", labels))
    guided_charts, delivery_table = guidance_delivery_charts(staging)
    settled_ex.extend(guided_charts)
    ecom_end = staging["period_ends"][periods.index(ECOMMERCE_COMP_FROM)]

    # ── section 2: what actually moved ──────────────────────────────────────
    highlight_ex = [segment_comp_chart(staging), segment_margin_chart(staging, labels, adj_seg)]
    if one_off is not None:
        highlight_ex.append(eps_layers_chart(staging, one_off, values))
    outlook_chart = full_year_split_chart(staging, outlook) if outlook and fq in YTD_REST else None
    if outlook_chart is not None:
        highlight_ex.append(outlook_chart["exhibit"])
        values["raise"] = outlook_chart["raise"]
    highlight_ex.append(corporate_expense_chart(staging, labels, ytd))
    # The year to date's cash uses are this quarter's reading, not a threshold line.
    highlight_ex.append(capital_intensity_chart(staging, ytd, store_plan, raised_today))

    # ── section 3: what to track next ───────────────────────────────────────
    next_ex = []
    if next_kpi is not None:
        breached_next = [entry for entry in forward
                         if headroom(entry["direction"], entry["threshold"], entry["current"]) < 0]
        skipped = next_kpi.get("not_plotted", [])
        next_ex.append(headroom_exhibit(
            f"下季{cn_count(len(forward))}条阈值："
            + (f"{cn_count(len(breached_next))}条已经在触发侧" if breached_next else "全部在安全侧"),
            forward, "current",
            note=(
                "同样以正值为安全侧。"
                + fill_story(next_kpi.get("note", ""), {**values,
                                                        "breached": cn_count(len(breached_next))})
                + (f"<b>另外{cn_count(len(skipped))}条本页不画：</b>"
                   + "；".join(f"「{item['metric']}」{fill_story(item['why'], values)}"
                              for item in skipped) + "。"
                   if skipped else "")
            ),
            src_extra="阈值为本地研究设定，不是公司指引；当前值取自本季业绩 8-K 与自算。",
        ))
    next_ex.append(marmaxx_comp_chart(staging, next((e for e in forward if e["measure"] == "comp_marmaxx"), None),
                                      labels, ecom_end, mmx_low))
    next_ex.append(homegoods_chart(staging, next((e for e in forward
                                                  if e["measure"] == "homegoods_margin_adjusted"), None),
                                   labels, adj_seg))

    # ── section 4: the long routine ─────────────────────────────────────────
    routine_ex = long_charts(staging, ytd_long, store_plan, raised_today)

    number_exhibits(settled_ex, start=1)
    number_exhibits(highlight_ex, start=settled_ex[-1]["n"] + 1)
    number_exhibits(next_ex, start=highlight_ex[-1]["n"] + 1)
    number_exhibits(routine_ex, start=next_ex[-1]["n"] + 1)
    # one pass over the whole page: a note in one section may point into another
    resolve_exhibit_refs(settled_ex + highlight_ex + next_ex + routine_ex)

    first_table = routine_ex[-1]["n"] + 1
    # The adjusted-EPS series is carried for the reviewed quarters only; an older
    # quarter the guidance record scores on the company's adjusted figure prints
    # that figure rather than claiming it had none.
    scored_eps = {quarter: item["adjusted"] for quarter, item in scored_adjusted(record).items()}
    core_rows = []
    for index, label in enumerate(periods):
        core_rows.append([
            label,
            staging["fiscal_labels"][index],
            staging["period_ends"][index],
            f"${sales[index]:,}M",
            ("—" if fin["net_sales_yoy_pct"][index] is None else ("—" if fin['net_sales_yoy_pct'][index] is None else f"{fin['net_sales_yoy_pct'][index]:+.1f}%")),
            ("—" if comp['consolidated'][index] is None else f"{comp['consolidated'][index]:+.0f}%"),
            f"{gross[index]:.2f}%",
            ("—" if fin['sga_pct_of_sales'][index] is None else f"{fin['sga_pct_of_sales'][index]:.2f}%"),
            f"{pretax_margin[index]:.2f}%",
            f"${eps[index]:.2f}",
            (f"${fin['adjusted_diluted_eps_usd'][index]:.2f}"
             if fin["adjusted_diluted_eps_usd"][index] is not None
             else f"${scored_eps[label]:.2f}" if label in scored_eps else "同 GAAP"),
            f"{shares[index]:,}M",
            f"{stores[index]:,}",
        ])
    fy_labels = long["fiscal_years"]
    long_rows = []
    for index, year in enumerate(fy_labels):
        long_rows.append([
            year,
            long["year_ends"][index],
            f"{long['weeks'][index]} 周",
            f"${long['net_sales_usd_m'][index]:,.0f}M",
            f"{long['pretax_margin_pct'][index]:.2f}%",
            f"${long['diluted_eps_usd'][index]:.2f}",
            f"{long['diluted_shares_m'][index]:,.0f}M",
            f"${long['capital_expenditures_usd_m'][index]:,.0f}M",
            f"{long['capex_intensity_pct'][index]:.2f}%",
            f"${long['operating_cash_flow_usd_m'][index]:,.0f}M",
            f"${long['share_repurchases_usd_m'][index]:,.0f}M",
            f"{long['store_count'][index]:,}",
        ])

    tables = []
    if followup is not None:
        tables.append({
            "n": 0,
            "title": f"上季 {len(followup['items'])} 条待验证问题：问题、本季证据与报告原文判定",
            "headers": ["#", "上季问题", "本季证据", "报告原文判定", "本页归类"],
            "rows": closure_rows,
        })
    if prior_kpi is not None:
        tables.append(settlement_table("上季第 8 节逐条结算（原始单位）", prior_kpi, settled, "actual",
                                       "本季实际"))
        tables.append(row_reading_table(prior_kpi))
    if next_kpi is not None:
        tables.append(threshold_table(0, "下季阈值（原始单位）", forward, "current", "当前值"))
    tables.extend([
        {**delivery_table, "n": 0},
        {
            "n": 0,
            "title": f"{len(periods)} 季核心（自然年季度标注；公司财季见第二列）",
            "headers": ["自然年季度", "公司财季", "季末", "净销售额", "同比", "合并 comp",
                        "毛利率", "SG&A 占比", "税前利润率", "GAAP EPS", "调整后 EPS",
                        "摊薄股数", "门店数"],
            "rows": core_rows,
        },
        {
            "n": 0,
            "title": "十年年度记录（各年取该年 10-K 印出的数；股数与每股数换算到一拆二之后）"
            if len(fy_labels) == 10 else
            f"{cn_count(len(fy_labels))}年年度记录（各年取该年 10-K 印出的数；股数与每股数换算到一拆二之后）",
            "headers": ["财年", "财年末", "周数", "净销售额", "税前利润率", "GAAP EPS",
                        "摊薄股数", "资本开支", "资本开支占销售额", "经营现金流", "回购", "财年末门店数"],
            "rows": long_rows,
        },
        # The one object published byte-identically on every page. TJX is not on
        # the chain it draws and is not a column in it -- neither are Cadence,
        # Synopsys, TSMC or NVIDIA, which carry it on the same terms. It lives in
        # the collapsed audit drawer rather than the chart flow, so it does not
        # spend the page's "every chart must earn its place" budget; the notes
        # say what it is, which the first pages outside the chain did not.
        ai_capex_cycle_table(0),
    ])
    for offset, table in enumerate(tables):
        table["n"] = first_table + offset

    # ── the page's words ─────────────────────────────────────────────────────
    q_guide = record["quarters"].index(period)
    beat_both = (record["actual_comp_pct"][q_guide] is not None
                 and record["actual_comp_pct"][q_guide] > record["guide_comp_hi_pct"][q_guide]
                 and record["actual_pretax_margin_pct"][q_guide] is not None
                 and record["actual_pretax_margin_pct"][q_guide] > record["guide_pretax_margin_hi_pct"][q_guide])
    lagging = mmx[-1] < comp["consolidated"][-1]
    slowing = bool(outlook_chart) and outlook_chart["rest_growth"] < outlook_chart["ytd_growth"]
    headline = (
        f"净销售额 US${sales[-1]:,}M、同比 {signed(fin['net_sales_yoy_pct'][-1])}，"
        f"合并 comp {comp['consolidated'][-1]:+.0f}%、税前利润率 {pretax_margin[-1]:.1f}%"
        + (" 双双高于自身指引" if beat_both else "")
        + (f"，{story['headline_events']}" if story.get("headline_events") else "")
    )
    if lagging or slowing:
        headline += "；"
    if lagging:
        headline += (f"但占销售额 {marmaxx_share * 100:.0f}% 的 Marmaxx 只有 {mmx[-1]:+.0f}%"
                     + story.get("marmaxx_headline_tail", ""))
    if slowing:
        headline += (("，而" if lagging else "但")
                     + f"公司自己给的{outlook_chart['rest']}{outlook_chart['basis']}每股收益只隐含 "
                     f"{outlook_chart['rest_growth']:+.1f}%，对{outlook_chart['ytd']}的 "
                     f"{outlook_chart['ytd_growth']:+.1f}%")
    headline += "。"

    floors = (eps_below <= 0.1 * eps_n and margin_below <= 0.1 * margin_n and comp_below == 0)
    brief = (
        '<h4>本季三条主线</h4><div class="takeaway-grid">'
        '<article><span>记录</span><b>'
        + ("三个指引数字都是地板" if floors else "三个指引数字的兑现记录")
        + "</b>"
        f'<p>{eps_n} 季已完结的每股收益指引里 {eps_above} 季穿出上限、'
        f'只有 {eps_below} 季跌破；税前利润率 {margin_n} 季里 {margin_above} 季超上限；'
        f'合并 comp {comp_n} 季'
        + ("一次没跌破过。" if comp_below == 0 else f"里 {comp_below} 季跌破。")
        + f"但指引是在该季开始后 {lag['lo']}–{lag['hi']} 天才发布的。</p></article>"
    )
    others = [key for key in SEGMENTS if key != "marmaxx"]
    other_comps = [comp[key][-1] for key in others]
    if mmx[-1] < min(other_comps) and mmx[-1] < mmx[-2]:
        brief += (
            '<article><span>裂口</span><b>最大的分部在失速</b>'
            f"<p>Marmaxx comp 从 {mmx[-2]:+.0f}% 掉到 {mmx[-1]:+.0f}%"
            + (f"，{story['marmaxx_brief_tail']}" if story.get("marmaxx_brief_tail") else "")
            + f"；其余{cn_count(len(others))}个分部 {min(other_comps):+.0f}~{max(other_comps):.0f}%，"
            f"合并 {comp['consolidated'][-1]:+.0f}% 是它们扛出来的。</p></article>"
        )
    if raised_today and story.get("store_brief_title"):
        brief += (
            f"<article><span>代价</span><b>{story['store_brief_title']}</b>"
            f"<p>长期门店目标 {store_plan['previous_target']:,} → {store_plan['target']:,}，"
            f"FY{store_plan['growth_from_fy']} 起开店增速 {store_plan['previous_growth_pct']:.0f}% → "
            f"{store_plan['growth_pct']:.0f}%；"
            f"{ytd_long}资本开支占销售额已从 {capex_prior:.2f}% 升到 {capex_now:.2f}%。</p></article>"
        )
    brief += "</div>"

    record_start = record["quarters"][0].split()[1]
    reaching = [name for key, name in (("guide_eps_lo_usd", "每股收益"), ("guide_comp_lo_pct", "合并 comp"))
                if record[key][0] is not None]
    highlight_parts = ["四个分部的分化"]
    if adj_seg:
        highlight_parts.append(f"{story.get('adjustment_name', '调整项')}把分部利润率推歪了多少")
    if slowing:
        pair = "上下半年" if fq == 2 else f"{outlook_chart['ytd']}与{outlook_chart['rest']}"
        highlight_parts.append(f"{pair}之间那道 {outlook_chart['gap']:.0f} 个百分点的斜率断崖")
    highlight_description = (
        "、".join(highlight_parts)
        + (f"，一条只能按{ytd_short}读的公司费用线" if fq > 1
           else "，一条单季摆动很大的公司费用线")
        + f"，以及{ytd_long}的资本强度。"
    )
    not_plotted_next = next_kpi.get("not_plotted", []) if next_kpi else []

    fiscal_end = "财年末为最接近 1 月 31 日的星期六"
    notes = [
        "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
        f"本页所有季度按自然年标注。TJX 财年在 1 月底或 2 月初结束，故本页的 {period} 是{cn_count(weeks)}周截至 {staging['period_ends'][-1]} 的季度，公司自己称之为 {fiscal}；映射规则为公司 FY(N) 的 Qk 即本页的 Qk (N−1)。不统一成一种约定，跨公司对照就会把不同的三个月放在一起比较。",
        record_starts_note(record),
        f"TJX 的下一季指引随上一季业绩一起发布，而它在季末约三周后发业绩，因此这段 Outlook 落在它所指引的那个季度之内：本记录里最早第 {lag['lo']} 天、最晚第 {lag['hi']} 天、平均第 {lag['mean']:.0f} 天。这不是一份事前预测，命中率必须连同这句话一起读。",
        withheld_note(record),
        split_note(record),
        fifty_three_week_note(long),
        adjusted_basis_note(record),
        identity_note(staging),
    ]
    if story.get("not_published_note"):
        notes.append(story["not_published_note"])
    notes.append(inventory_definition_note(staging))
    notes.append(peer_note(staging))
    notes.extend([
        "核对抽屉最后那张「AI capex 循环」是全站逐字节一致的跨页对照块，不是对 TJX 的判断：它把四家云厂的现金资本开支、NVDA 的数据中心收入与 TSM 的晶圆季度串成一条链，而 TJX 不在这条链的任何一环上。本站有若干页同样只是承载它而不出现在它的列里（Cadence、Synopsys、TSMC、NVIDIA 都是如此，且有测试专门钉住这一点）。它放在折叠抽屉里而不是图表区，所以不占本页「每张图都要自证」的额度；在这里写明它是什么，是因为在一家折扣零售商的抽屉里遇到一张晶圆代工对照表的读者，值得有一句话说明它的性质。",
        "本页只发布公司披露值、可复算的简单派生值，以及明确标注的市场预期；D 标记代表 Derived / 自算。",
        "市场预期一律标注为「市场预期」并给出取数时点，不写卖方机构名，也不发布评级、目标价或估值。",
    ])
    if story.get("not_ingested"):
        notes.append("本页已知未接入：" + "、".join(story["not_ingested"]) + "。")
    notes.append("业绩电话会文字稿仅链接官方 IR 与 SEC 托管版本，公开仓不复制原件或逐字内容。")

    periodic = "10-K" if fq == 4 else "10-Q"
    source_text = (
        f'Source: <a href="{source["url"]}" rel="noopener">TJX {fiscal} '
        f'业绩新闻稿（8-K EX-99.1）</a>与截至 {staging["period_ends"][-1]} 的 {periodic}。'
    )

    return {
        "schema_version": "quarterly-dashboard/tjx-v1",
        "page": {"slug": "tjx", "language": "zh-CN"},
        "company": {
            "ticker": "TJX",
            "name": "The TJX Companies",
            "group": "consumer_retail",
            "accounting_standard": "US GAAP",
        },
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · TJX",
        "title": f"The TJX Companies (TJX)：{period} 季报仪表盘",
        "subtitle": (
            f"{cn_count(weeks)}周截至 {staging['period_ends'][-1]} · 发布 {staging['release_dates'][-1]} · "
            f"US GAAP · {audit} · "
            f"{fiscal_end}，本站按自然年季度标注：本页 {period} 即公司所称 {fiscal}"
        ),
        "headline": headline,
        "brief": brief,
        "source": source_text,
        "source_url": source["url"],
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": guidance_table(guidance, outlook_chart),
        "sections": [
            {
                "id": "settled",
                "title": "一、上季跟踪指标兑现了吗",
                "description": (
                    settled_lead(followup, prior_kpi, settled)
                    + "公司在业绩新闻稿末尾的 Outlook 段里给出下一季的指引 —— "
                    + spaced("与".join(reaching), f"{'两条记录都' if len(reaching) == 2 else '这条记录'}"
                             f"能一直回到 {record_start} 年；")
                    + "但指引是在被指引的那个季度开始之后才发布的，这一点写在每张图上。"
                ),
                "exhibits": settled_ex,
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": highlight_description,
                "exhibits": highlight_ex,
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": (
                    ("当前值离下季阈值还有多远，统一用「距阈值余量」口径"
                     + (f"；不接入的{cn_count(len(not_plotted_next))}条也写在这里。"
                        if not_plotted_next else "。"))
                    if next_kpi is not None else
                    "本季没有设下季阈值；这一节只跟 HomeGoods 分部利润率。"
                ),
                "exhibits": next_ex,
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": (
                    "TJX 专属的常规序列：十年税前利润率与资本强度、门店与面积这台单位增长机器、"
                    "十年回购与股数，以及经营现金流、资本开支与股东回报的三柱结构。"
                    if len(fy_labels) == 10 else
                    f"TJX 专属的常规序列：{cn_count(len(fy_labels))}年税前利润率与资本强度、门店与面积这台单位增长机器、"
                    f"{cn_count(len(fy_labels))}年回购与股数，以及经营现金流、资本开支与股东回报的三柱结构。"
                ),
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": notes,
        "footer": "TJX quarterly results · 数据来自 The TJX Companies 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


# ── section-one threshold charts ─────────────────────────────────────────────
def record_line(title: str, labels: list[str], values: list[float | None], *, fmt: str, ylab: str,
                name: str, note: str, src_extra: str, threshold: float | None = None,
                threshold_name: str = "") -> dict:
    """A long record, with a threshold line when a stamped block sets one."""
    if threshold is not None:
        return threshold_exhibit(title, labels, values, threshold, fmt=fmt, ylab=ylab,
                                 actual_name=name, threshold_name=threshold_name,
                                 note=note, src_extra=src_extra)
    return {"kind": "lines", "title": title, "xlabels": labels,
            "series": [{"name": name, "values": values, "color": "NAVY"}],
            "fmt": fmt, "yfmt": fmt, "label_fmt": fmt, "end_label": True, "ylab": ylab,
            "note": note, "src_extra": src_extra}


def interim_next_entries(staging: dict) -> tuple[dict | None, list[dict]]:
    """Section three's block, each entry read now (the block keeps its own `direction`)."""
    kpi = block(staging, "next_kpi")
    if kpi is None:
        return None, []
    series = measure_series(staging)
    entries = []
    for entry in kpi["quantified"]:
        if entry["measure"] not in series:
            raise ValueError(f"next_kpi entry {entry['metric']!r}: this page does not know how to "
                             f"measure {entry['measure']!r}")
        entries.append({**entry, "current": series[entry["measure"]][-1]})
    return kpi, entries


# (a) the follow-up questions ────────────────────────────────────────────────
def closure_counts(closure: dict) -> list[int]:
    labels = closure["labels"]
    unknown = sorted({item["verdict"] for item in closure["items"]} - set(labels))
    if unknown:
        raise ValueError(f"followup_closure verdicts {unknown} are not among its labels {labels}")
    return [sum(1 for item in closure["items"] if item["verdict"] == label) for label in labels]


def closure_chart(closure: dict, period: str) -> dict:
    """Last report's follow-up questions, counted by the verdict this quarter's report wrote."""
    labels, items = closure["labels"], closure["items"]
    counts = closure_counts(closure)
    groups = "；".join(
        f"{label}{cn_count(count)}条（" + "、".join(item["short"] for item in items if item["verdict"] == label) + "）"
        for label, count in zip(labels, counts) if count)
    return {
        "ref": "EX_CLOSURE",
        "kind": "bars_labeled",
        "title": (f"上季 {len(items)} 条待验证问题："
                  + "、".join(f"{count} 条{label}" for label, count in zip(labels, counts))),
        "xlabels": labels,
        "values": counts,
        "legend": "问题条数",
        "fmt": "f0",
        "yfmt": "f0",
        "label_fmt": "f0",
        "ylab": "条",
        "note": (closure["rule"] + groups + "。" + closure.get("scorecard", "")
                 + "逐条的问题、本季证据与报告原文判定见核对表。"),
        "src_extra": (f"问题清单来自上季（{closure['set_in']}）本地季报分析的 Follow-up Questions，判定取自本季"
                      f"（{period}）分析第 0 节；证据里的数取自本页序列与申报，只在电话会上出现的说法注明是电话会口径。"),
    }


def closure_values(staging: dict, record: dict, store_plan: dict | None) -> dict[str, str]:
    """The numbers the follow-up evidence names, computed rather than typed into the block."""
    period = page_period(staging)
    comp, fin = staging["comparable_sales_pct"], staging["financials"]
    gce = staging["segments_usd_m"]["general_corporate_expense"]
    series = measure_series(staging)
    ross = staging["peer_comparable_sales_pct"]["ross"]

    def beat(quarter: str) -> str:
        i = record["quarters"].index(quarter)
        mid = (record["guide_eps_lo_usd"][i] + record["guide_eps_hi_usd"][i]) / 2
        return signed(pct_change(record["actual_eps_usd"][i], mid))

    q = record["quarters"].index(period)
    ytd = ytd_block(staging)
    values = {
        "q_guide": f"${record['guide_eps_lo_usd'][q]:.2f}–{record['guide_eps_hi_usd'][q]:.2f}",
        "q_beat": beat(period),
        "prior_q_beat": beat(previous_period(period)),
        "comp": f"{comp['consolidated'][-1]:+.0f}%",
        "marmaxx_comp": f"{comp['marmaxx'][-1]:+.0f}%",
        "adj_eps": f"${series['adjusted_eps'][-1]:.2f}",
        "adj_gm": f"{series['gross_margin_adjusted'][-1]:.1f}%",
        "ross_comp": f"{ross[-1]:+.0f}%",
        "ross_prior": f"{ross[-2]:+.0f}%",
        "gap": reading_words("ross_gap", series["ross_gap"][-1]),
        "gap_prior": reading_words("ross_gap", series["ross_gap"][-2]),
        "gce": f"${gce[-1]:,.0f}M",
        "gce_yago": f"${gce[-5]:,.0f}M",
        "gce_prior_q": f"${gce[-2]:,.0f}M",
        "gce_prior_q_yago": f"${gce[-6]:,.0f}M",
        "gce_ytd": f"${ytd['general_corporate_expense'][1]:,.0f}M",
        "gce_ytd_prior": f"${ytd['general_corporate_expense'][0]:,.0f}M",
    }
    if store_plan:
        values.update({"old_target": f"{store_plan['previous_target']:,}",
                       "new_target": f"{store_plan['target']:,}",
                       "growth_from_fy": str(store_plan["growth_from_fy"]),
                       "new_growth": f"{store_plan['growth_pct']:.0f}%",
                       "old_growth": f"{store_plan['previous_growth_pct']:.0f}%"})
    readings = block(staging, "threshold_readings")
    if readings and "fy_capex_plan_usd_bn" in readings:
        lo, hi = readings["fy_capex_plan_usd_bn"]
        values["capex_plan"] = f"${lo:g}–{hi:g}B"
    return values


def settled_lead(followup: dict | None, prior_kpi: dict | None, settled: list[dict]) -> str:
    parts = []
    if followup:
        parts.append(f"{len(followup['items'])} 条待验证问题按本季分析第 0 节的判定计数")
    if prior_kpi:
        parts.append(f"第 8 节的 {len(settled)} 条阈值逐条用本季实际值结算")
    if not parts:
        return "本季没有上季分析留下的待验证问题与阈值可结算，本节只看公司自己的指引记录。"
    set_in = (followup or prior_kpi)["set_in"]
    return (f"先结清上季（{set_in}）本地季报分析留下的东西：" + "，".join(parts)
            + "；再看公司自己的指引记录。")


# (b) the section-8 lines ────────────────────────────────────────────────────
LINE_COLORS = ("RED", "GOLD", "GREEN")
# measures a threshold can be settled on that have no chart of their own, and why
UNCHARTED = {
    "fy_capex_plan_high": "全年资本开支计划不是季度序列：公司只在 10-K 与各季 10-Q 的 Liquidity 段各印一次全年区间",
}


def row_label(row) -> str:
    return f"第 {row} 行" if isinstance(row, int) else f"撤销条件{str(row).replace('撤销', '')}"


def rows_of(kpi: dict) -> dict:
    return {row["row"]: row for row in kpi.get("rows", [])}


def verdict_words(entry: dict) -> str:
    if entry["kind"] == "warn":
        return "触发" if entry["fired"] else "未触发"
    return "达到" if entry["fired"] else "未达到"


def headroom_axis(title: str, entries: list[dict], value_key: str, note: str, src_extra: str) -> dict:
    """The headroom bars, with legend words that fit a warning line and a target line alike."""
    exhibit = headroom_exhibit(title, entries, value_key, note=note, src_extra=src_extra)
    exhibit["positive_label"] = "落在有利一侧"
    exhibit["negative_label"] = "落在不利一侧"
    return exhibit


def rule_sentences(kpi: dict, entries: list[dict], value_key: str) -> str:
    """What the bars cannot show on their own: joint rows, runs, zero lines, uncharted readings."""
    words = []
    joint_rows = sorted({entry["row"] for entry in entries if entry.get("joint")}, key=str)
    for row in joint_rows:
        legs = [entry for entry in entries if entry["row"] == row]
        words.append(f"{row_label(row)}要两腿同时触发才算警示（"
                     + "；".join(f"「{leg['metric']}」本季 {reading_words(leg['measure'], leg[value_key])}"
                                f"，{verdict_words(leg)}" for leg in legs)
                     + f"），这一行{'触发' if row_fired(entries, row) else '未触发'}。")
    for entry in entries:
        run = entry.get("consecutive", 1)
        if run > 1 and entry.get("run"):
            words.append(f"「{entry['metric']}」要连续{cn_count(run)}季才算：最近{cn_count(run)}季是 "
                         + " 与 ".join(reading_words(entry["measure"], v) for v in entry["run"])
                         + f"，{verdict_words(entry)}。")
    for entry in entries:
        if entry[value_key] is not None and entry["threshold"] == 0:
            words.append(f"{row_label(entry['row'])}的「{entry['metric']}」阈值是 0，没有百分比余量，不进柱图："
                         f"本季 {reading_words(entry['measure'], entry[value_key])}，{verdict_words(entry)}。")
    for entry in entries:
        if entry[value_key] is not None and entry["measure"] in UNCHARTED and entry["threshold"] != 0:
            words.append(f"「{entry['metric']}」没有单独的线图 —— {UNCHARTED[entry['measure']]}；"
                         f"本季 {reading_words(entry['measure'], entry[value_key])}，{verdict_words(entry)}。")
    return "".join(words)


def prior_overview(staging: dict, prior_kpi: dict, settled: list[dict]) -> dict:
    """(b) Last report's section 8, every quantified line on one headroom axis."""
    bars = drawn(settled, "actual")
    favourable = sum(1 for entry in bars if entry["favourable"])
    verdict = ("全部落在有利一侧" if favourable == len(bars) else "全部落在不利一侧" if not favourable
               else f"{favourable} 条落在有利一侧、{len(bars) - favourable} 条在不利一侧")
    exhibit = headroom_axis(
        f"上季 {len(bars)} 条量化阈值：{verdict}",
        bars, "actual",
        note=("正值＝落在这条线的有利一侧（警示线守住、目标线达到），负值＝不利一侧（警示线击穿、目标线未达到）；"
              "恰好压在线上的一格余量为 0，是否算触发由原文的比较符决定（≥ 与 ≤ 含等号）。"
              + rule_sentences(prior_kpi, settled, "actual")
              + "报告本季对每一行的读法与处理见核对表。"),
        src_extra=(f"阈值数值与触发方向逐字取自上季（{prior_kpi['set_in']}）本地季报分析第 8 节「本季指标表」与立场撤销条件，"
                   "是研究设定，不是公司指引；本季实际值取自本页序列（TJX 与 Ross 的业绩 8-K、TJX 10-Q）。"),
    )
    exhibit["ref"] = "EX_PRIOR_BAR"
    return exhibit


def settlement_table(title: str, kpi: dict, entries: list[dict], value_key: str, value_head: str) -> dict:
    """Every line of a section-8 block in its own units, with the comparator the report wrote."""
    rows = rows_of(kpi)
    revoked = {line: item for item in kpi.get("revocation", []) for line in item["lines"]}
    out = []
    for entry in entries:
        value = entry[value_key]
        source = rows[entry["row"]]["text"] if entry["row"] in rows else revoked[entry["id"]]["text"]
        room = ("—" if value is None or entry["threshold"] == 0
                else f"{headroom(entry['direction'], entry['threshold'], value):+.1f}%")
        out.append([row_label(entry["row"]), source, entry["metric"],
                    entry["fires"] + threshold_words(entry),
                    "—" if value is None else reading_words(entry["measure"], value),
                    room, "—" if value is None else verdict_words(entry)])
    return {"n": 0, "title": title,
            "headers": ["行", "报告原文", "这条线", "阈值", value_head, "余量 D", "判定"],
            "rows": out}


def row_reading_table(prior_kpi: dict) -> dict:
    """The previous report's rows, as this quarter's report read and handled them."""
    rows = [[row_label(row["row"]), row["metric"], row["text"], row["report_reading"], row["handling"]]
            for row in prior_kpi.get("rows", [])]
    rows += [[f"撤销条件{item['n']}", item["text"], "—", "见上表同线", "—"]
             for item in prior_kpi.get("revocation", [])]
    return {"n": 0, "title": "上季第 8 节：本季分析「先校准上季指标」的读法与处理",
            "headers": ["行", "指标", "原文阈值", "本季报告的读法", "处理"], "rows": rows}


def track_title(measure: str, entries: list[dict], value_key: str, mode: str) -> str:
    name = MEASURE_LOOK[measure][0]
    now = reading_words(measure, entries[0][value_key])
    if mode == "prior":
        return f"{name} {now}：" + "，".join(settle_words(entry, value_key) for entry in entries)
    return (f"{name}：下季阈值 " + " / ".join(f"{threshold_words(entry)}（{entry['line']}）" for entry in entries)
            + f"，当前 {now}")


def track_lines(entries: list[dict], mode: str, length: int) -> list[dict]:
    lead = "上季" if mode == "prior" else "下季"
    return [{"name": f"{spaced(lead, entry['line'])} {threshold_words(entry)}", "values": [entry["threshold"]] * length,
             "color": LINE_COLORS[i % len(LINE_COLORS)]} for i, entry in enumerate(entries)]


def report_words(kpi: dict, entries: list[dict]) -> str:
    """The report's own reading of the rows these lines belong to (section one only)."""
    rows = rows_of(kpi)
    seen = []
    for entry in entries:
        if entry["row"] in rows and entry["row"] not in seen:
            seen.append(entry["row"])
    return "".join(f"{row_label(row)}报告本季的读法：{rows[row]['report_reading']}；处理：{rows[row]['handling']}。"
                   for row in seen if rows[row].get("report_reading"))


def track_exhibit(ref: str, title: str, labels: list[str], series: list[dict], *, fmt: str, ylab: str,
                  note: str, src_extra: str) -> dict:
    return {"ref": ref, "kind": "lines", "title": title, "xlabels": labels, "series": series,
            "fmt": fmt, "yfmt": fmt, "label_fmt": fmt, "end_label": True, "ylab": ylab,
            "note": note, "src_extra": src_extra}


def comp_track_chart(staging: dict, kpi: dict, entries: list[dict], value_key: str, mode: str,
                     labels: list[str]) -> dict:
    # Twelve of the quarters to 2026 have no consolidated comp at all: the Q1
    # FY2021 release printed none, seven quarters of 2020-2021 published only an
    # "open-only" comp (sales measured against stores that were actually open,
    # which is a different measure), and the 2022 releases gave U.S. comps only.
    # Those are holes, not zeros.
    comp = staging["comparable_sales_pct"]
    values = [None if v is None else float(v) for v in comp["consolidated"]]
    value = values[-1]
    others = [comp[key][-1] for key in SEGMENTS if key != "marmaxx"]
    mmx = comp["marmaxx"]
    reached = [entry for entry in entries if entry["kind"] == "target" and entry["fired"]]
    carried = bool(reached) and (mmx[-1] < reached[0]["threshold"] <= mmx[-2]
                                 and all(other >= reached[0]["threshold"] for other in others))
    ecom_end = staging["period_ends"][staging["periods"].index(ECOMMERCE_COMP_FROM)]
    return track_exhibit(
        "EX_TRACK_COMP", track_title("comp_consolidated", entries, value_key, mode), labels,
        [{"name": "合并 comp", "values": values, "color": "NAVY"}] + track_lines(entries, mode, len(labels)),
        fmt="pct0", ylab="%",
        note=(f"{'上季' if mode == 'prior' else '本季'}第 8 节在合并 comp 上设了{cn_count(len(entries))}道线："
              + "、".join(f"{row_label(entry['row'])}的{entry['line']} {threshold_words(entry)}" for entry in entries)
              + "。"
              + (f"本季 {value:+.0f}% 过了加仓线，但构成变了：过线全靠 Marmaxx 以外的{cn_count(len(others))}个分部"
                 f"（{min(others):+.0f}~{max(others):.0f}%），Marmaxx 只有 {mmx[-1]:+.0f}%（Exhibit {{EX_SEG_COMP}}）。"
                 if carried else "")
              + (report_words(kpi, entries) if mode == "prior" else "")
              + f"合并 comp 按整数披露，「{value:+.0f}%」的真值区间是 {value - 0.5:.1f}–{value + 0.5:.1f}%，"
              "压在线上的一格两边都有可能。"),
        src_extra=("comp 为公司披露的整数百分比，见各季 8-K 的 Comparable Sales by Division。"
                   f"<b>{cn_year_quarter(ECOMMERCE_COMP_FROM)}（截至 {ecom_end}）起这条口径含电商</b>，在此之前不含；"
                   "公司在自己的表里加了脚注标出这道边界，且<b>从未重述</b>更早的季度，所以线上这一处是"
                   "两个总体接在一起。电商约占销售额 2%，公司称对合并 comp 的影响不重大，而 comp 本身"
                   "只印到整数，所以没有哪一格可以被证明是错的 —— 但边界在这里，不在图上看不出来。"),
    )


def gap_track_chart(staging: dict, kpi: dict, entries: list[dict], value_key: str, mode: str,
                    labels: list[str]) -> dict:
    gap = measure_series(staging)["ross_gap"]
    mmx = staging["comparable_sales_pct"]["marmaxx"]
    ross = staging["peer_comparable_sales_pct"]["ross"]
    seen = [(i, v) for i, v in enumerate(gap) if v is not None]
    earlier = seen[:-2]
    last_two = seen[-2:]
    record_pair = (len(earlier) > 0 and [i for i, _ in last_two] == [len(gap) - 2, len(gap) - 1]
                   and all(v > max(e for _, e in earlier) for _, v in last_two))
    top = max(earlier, key=lambda pair: pair[1]) if earlier else None
    return track_exhibit(
        "EX_TRACK_GAP", track_title("ross_gap", entries, value_key, mode), labels,
        [{"name": "Ross comp − Marmaxx comp", "values": gap, "color": "NAVY"}]
        + track_lines(entries, mode, len(labels)),
        fmt="f0", ylab="pp",
        note=("差距 = Ross 同十三周 comp − Marmaxx comp，两家都取各自 8-K 印的整数，正值是 Marmaxx 落后；"
              "两家的会计季截至同一个星期六，所以是同一段十三周。"
              f"本季 Ross {ross[-1]:+.0f}%、Marmaxx {mmx[-1]:+.0f}%，上季 {ross[-2]:+.0f}% 与 {mmx[-2]:+.0f}%。"
              + (f"{len(seen)} 个两家都有同比 comp 的季度里，本季与上季是最大的两格；此前最大是 "
                 f"{labels[top[0]]} 的 {top[1]:.0f}pp。" if record_pair and top else "")
              + "2020–2021 年两家都没有可比的同比 comp（TJX 只报开店口径或不报，Ross 两季不报或只报重开门店、"
              "2021 年对比的是 2019 年），图上是空档。"
              + (report_words(kpi, entries) if mode == "prior" else "")),
        src_extra=("Ross 的 comp 读自 Ross Stores 各季业绩 8-K 的 EX-99.1（逐季出处见 series 的 "
                   "peer_comparable_sales_pct._sources）；Marmaxx 的 comp 读自 TJX 各季 8-K 的分部 comp 表；差为自算。"),
    )


def gm_track_chart(staging: dict, kpi: dict, entries: list[dict], value_key: str, mode: str,
                   labels: list[str]) -> dict:
    fin = staging["financials"]
    adjusted, gross = fin["adjusted_gross_margin_pct"], fin["gross_margin_pct"]
    values = measure_series(staging)["gross_margin_adjusted"]
    story = story_block(staging)
    one_off = block(staging, "one_off_usd_m")
    this_adjusted = adjusted[-1] is not None
    adj_quarters = [compact_period(p) for p, v in zip(staging["periods"], adjusted) if v is not None]
    return track_exhibit(
        "EX_TRACK_GM", track_title("gross_margin_adjusted", entries, value_key, mode), labels,
        [{"name": "毛利率（有调整项的季度取调整后）", "values": rounded(values), "color": "NAVY"}]
        + track_lines(entries, mode, len(labels)),
        fmt="pct1", ylab="%",
        note=(f"上季的门槛设在调整后口径上，而 {len(labels)} 季历史只有报表口径存在，所以这条线在"
              f"{cn_count(len(adj_quarters))}个有调整项的季度（{'、'.join(adj_quarters)}）"
              "取公司自己披露的调整后值、其余季度取报表值"
              + (f" —— 本季报表毛利率 {gross[-1]:.1f}%，调整后 {adjusted[-1]:.1f}%，"
                 f"差的 {abs(one_off['gross_margin_effect_pp']):.1f} 个百分点是{one_off['gross_margin_item']}。"
                 if this_adjusted and one_off else "。")
              + ("30.9–31.0% 的 Q2 毛利率指引是上季电话会的口径，Q1 新闻稿 Outlook 段只指引了 comp、税前利润率与每股收益。"
                 if mode == "prior" else "")
              + story.get("gross_margin_words", "")
              + (report_words(kpi, entries) if mode == "prior" else "")),
        src_extra="报表毛利率为收入减销货成本的自算值；调整后毛利率为公司披露值。",
    )


def inventory_track_chart(staging: dict, kpi: dict, entries: list[dict], value_key: str, mode: str,
                          labels: list[str]) -> dict:
    ops = staging["operations"]
    reported = [None if v is None else float(v) for v in ops["inventory_per_store_yoy_pct"]]
    constant = [None if v is None else float(v) for v in ops["inventory_per_store_yoy_cc_pct"]]
    note_block = staging["inventory_per_store_note"]
    inventory = ops["merchandise_inventories_usd_m"]
    holes = sum(1 for v in reported if v is None)
    return track_exhibit(
        "EX_TRACK_INVENTORY", track_title("inventory_per_store_yoy", entries, value_key, mode), labels,
        [{"name": "每店库存同比（报表口径）", "values": reported, "color": "NAVY"},
         {"name": "每店库存同比（固定汇率）", "values": constant, "color": "GRAY"}]
        + track_lines(entries, mode, len(labels)),
        fmt="pct0", ylab="同比 %",
        note=("这是公司自己在每份新闻稿 Inventory 段印出的每店库存同比（含配送中心，不含在途与电商），"
              f"本季报表口径 {reported[-1]:+.0f}%、固定汇率 {constant[-1]:+.0f}%；页面按报表口径结算。"
              + (f"资产负债表上的总存货本季 ${inventory[-1]:,.0f}M、同比 {signed(pct_change(inventory[-1], inventory[-5]))}，"
                 "它含在途与电商、也不除以店数，所以不是同一个量。"
                 if inventory[-1] is not None and inventory[-5] is not None else "")
              + "口径边界：" + "；".join(f"{item['from']} {item['change']}" for item in note_block["scope_changes"])
              + f"（每一格都是同一口径下的同比）。{holes} 个空档是 2020–2021 年新闻稿不印这一句的季度。"
              + (report_words(kpi, entries) if mode == "prior" else "")),
        src_extra=("各季业绩 8-K EX-99.1 的 Inventory 段「Consolidated inventories on a per-store basis」一句，"
                   "公司印出的整数百分比；逐季出处见 series 的 inventory_per_store_note.filings。"),
    )


TRACK_CHARTS = {
    "comp_consolidated": comp_track_chart,
    "ross_gap": gap_track_chart,
    "gross_margin_adjusted": gm_track_chart,
    "inventory_per_store_yoy": inventory_track_chart,
}


def track_charts(staging: dict, kpi: dict, entries: list[dict], value_key: str, mode: str,
                 labels: list[str]) -> list[dict]:
    """One line chart per measure the drawn lines settle on, in the order the rows name them."""
    groups: dict[str, list[dict]] = {}
    for entry in drawn(entries, value_key):
        groups.setdefault(entry["measure"], []).append(entry)
    return [TRACK_CHARTS[measure](staging, kpi, group, value_key, mode, labels)
            for measure, group in groups.items() if measure in TRACK_CHARTS]


def marmaxx_comp_chart(staging: dict, entry: dict | None, labels: list[str], ecom_end: str,
                       low: str | None) -> dict:
    mmx = staging["comparable_sales_pct"]["marmaxx"]
    story = story_block(staging)
    count = sum(1 for v in mmx if v is not None)
    value, prior = mmx[-1], mmx[-2]
    low_words = f"{low} 以来最低" if low else f"{count} 季最低" if low == "" else ""
    return record_line(
        f"Marmaxx 同店销售 {count} 季（共 {len(labels)} 季）：本季 {value:+.0f}%"
        + (f"，{low_words}" if low_words else "")
        + story.get("marmaxx_title_tail", ""),
        labels, [None if v is None else float(v) for v in mmx],
        fmt="pct0", ylab="%", name="Marmaxx comp",
        threshold=entry["threshold"] if entry else None,
        threshold_name=(entry.get("threshold_name", f"下季阈值 {entry['threshold']:.0f}%")
                        if entry else ""),
        note=(
            (entry.get("line_note", "") if entry else "")
            + f"本季 {value:+.0f}%，环比从 {prior:+.0f}% "
            f"{'掉下来' if value < prior else '升上来'} {abs(value - prior):.0f} 个百分点"
            + (f"，是 {low} 以来的最低点" if low else "")
            + ("，是这条线的最低点" if low == "" else "")
            + "。"
            + story.get("marmaxx_words", "")
        ),
        src_extra=("comp 与其驱动的定性描述均为公司披露"
                   + ("；阈值为本地研究设定。" if entry else "。")
                   + f"口径边界同上：{ecom_end} 那一季起含电商，更早不含，公司未重述。"),
    )


def segment_comp_chart(staging: dict) -> dict:
    comp = staging["comparable_sales_pct"]
    sales = staging["financials"]["net_sales_usd_m"]
    seg = staging["segments_usd_m"]
    now = {key: comp[key][-1] for key in SEGMENTS}
    before = {key: comp[key][-2] for key in SEGMENTS}
    consolidated = comp["consolidated"][-1]
    weak = [key for key in SEGMENTS if now[key] < consolidated]
    strong = [key for key in SEGMENTS if key not in weak]
    rising = [key for key in SEGMENTS if now[key] > before[key]]
    share = seg["marmaxx_sales"][-1] / sales[-1]
    if weak == ["marmaxx"]:
        others = [now[key] for key in strong]
        title = (f"四个分部{cn_count(len(strong))}强一弱：Marmaxx {now['marmaxx']:+.0f}%，"
                 f"其余{cn_count(len(strong))}个 {min(others):+.0f}~{max(others):.0f}%"
                 + ("，" + spaced(SEGMENT_TITLE_NAMES[rising[0]], "是唯一环比加速的分部")
                    if len(rising) == 1 else ""))
    else:
        title = "四个分部本季 comp：" + "、".join(
            f"{SEGMENT_NAMES[key]} {now[key]:+.0f}%" for key in SEGMENTS)
    moves = []
    for key in SEGMENTS:
        if key in weak and now[key] < before[key]:
            moves.append(f"{SEGMENT_NAMES[key]} 从 {before[key]:+.0f}% 掉到 {now[key]:+.0f}%")
        elif key in rising:
            moves.append(f"{SEGMENT_NAMES[key]} 从 {before[key]:+.0f}% 升到 {now[key]:+.0f}%"
                         + ("（唯一加速的）" if len(rising) == 1 else ""))
    rest = [key for key in reversed(SEGMENTS)
            if not (key in weak and now[key] < before[key]) and key not in rising]
    if rest:
        moves.append(listed([SEGMENT_NAMES[key] for key in rest])
                     + (" 分别停在 " if len(rest) > 1 else " 停在 ")
                     + listed([f"{now[key]:+.0f}%" for key in rest]))
    return {
        "ref": "EX_SEG_COMP",
        "kind": "grouped_bars",
        "title": title,
        "xlabels": ["Marmaxx", "HomeGoods", "TJX Canada", "TJX International"],
        "groups": [
            {"name": "去年同期 comp", "color": "GRAY",
             "values": [float(comp[key][-5]) for key in SEGMENTS]},
            {"name": "上季 comp", "color": "BLUE",
             "values": [float(comp[key][-2]) for key in SEGMENTS]},
            {"name": "本季 comp", "color": "NAVY",
             "values": [float(comp[key][-1]) for key in SEGMENTS]},
        ],
        "fmt": "pct0",
        "yfmt": "pct0",
        "label_fmt": "pct0",
        "ylab": "%",
        "note": (
            "把三根柱并排看，本季的分化比任何单季数字都清楚："
            + "，".join(moves) + "。"
            f"Marmaxx 占本季销售额 {share * 100:.1f}%"
            + (f"，所以合并 comp 的 {consolidated:+.0f}% 是被另外{cn_tenths(1 - share)}销售额扛出来的。"
               if weak == ["marmaxx"] else "。")
        ),
        "src_extra": "各季 8-K 的 Comparable Sales by Division，公司披露的整数百分比。",
    }


def segment_margin_chart(staging: dict, labels: list[str], adj_seg: dict | None) -> dict:
    segm = staging["segment_margins_pct"]
    hg, mmx = segm["homegoods_margin_pct"], segm["marmaxx_margin_pct"]
    if hg[-1] > mmx[-1]:
        earlier = [i for i in range(len(hg) - 1) if hg[i] > mmx[i]]
        first = f"{labels[earlier[-1]]} 以来第一次" if earlier else "第一次"
        if earlier and earlier[-1] == len(hg) - 2:
            first = "继续"
        title = (f"分部利润率 {len(labels)} 季（报表口径）：HomeGoods 本季 {hg[-1]:.1f}%，"
                 f"{first}高过 Marmaxx 的 {mmx[-1]:.1f}%")
    else:
        title = (f"分部利润率 {len(labels)} 季（报表口径）：HomeGoods 本季 {hg[-1]:.1f}%，"
                 f"Marmaxx {mmx[-1]:.1f}%")
    note = "这是<b>报表</b>分部利润率（分部利润 ÷ 分部销售额，两端都是申报值）。"
    if adj_seg:
        story = story_block(staging)
        abroad = [key for key in ("canada", "international") if adj_seg[key]["tariff_refund_pp"] > 0]
        note += (
            f"本季它被{story.get('adjustment_name', '调整项')}推歪了：公司同时披露了"
            f"{story.get('adjustment_short', '调整项')}对每个分部利润率的影响，"
            f"HomeGoods 被推高 {abs(adj_seg['homegoods']['tariff_refund_pp']):.1f} 个百分点、"
            f"Marmaxx {abs(adj_seg['marmaxx']['tariff_refund_pp']):.1f} 个百分点，"
            f"剔除后分别是 {adj_seg['homegoods']['adjusted']:.1f}% 与 {adj_seg['marmaxx']['adjusted']:.1f}%。"
            + (f"<b>也就是说这张图上 HomeGoods 反超 Marmaxx 的那一笔，是{story.get('adjustment_short', '调整项')}"
               "画出来的，不是经营画出来的。</b>"
               if hg[-1] > mmx[-1] and adj_seg["homegoods"]["adjusted"] < adj_seg["marmaxx"]["adjusted"]
               else "")
            + (f"两个海外分部收到的是反方向的影响（{story['abroad_reason']}），"
               f"所以 Canada 的调整后利润率 {adj_seg['canada']['adjusted']:.1f}% 反而高于报表值。"
               if len(abroad) == 2 and story.get("abroad_reason") else "")
        )
    return {
        "kind": "lines",
        "title": title,
        "xlabels": labels,
        "series": [
            {"name": "Marmaxx", "values": rounded(segm["marmaxx_margin_pct"]), "color": "NAVY"},
            {"name": "HomeGoods", "values": rounded(segm["homegoods_margin_pct"]), "color": "MBLUE"},
            {"name": "TJX Canada", "values": rounded(segm["canada_margin_pct"]), "color": "GOLD"},
            {"name": "TJX International", "values": rounded(segm["international_margin_pct"]), "color": "GRAY"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "%",
        "note": note,
        "src_extra": ("分部销售额与分部利润来自各季 8-K 的分部表"
                      + (f"；{story_block(staging).get('adjustment_short', '调整项')}对分部利润率的影响为公司披露值。"
                         if adj_seg else "。")),
    }


def eps_layers_chart(staging: dict, one_off: dict, values: dict) -> dict:
    fin = staging["financials"]
    eps, adjusted = fin["diluted_eps_usd"][-1], fin["adjusted_diluted_eps_usd"][-1]
    if adjusted is None or abs(round(eps - adjusted, 2) - one_off["eps_impact_usd"]) > 1e-9:
        raise ValueError("one_off_usd_m.eps_impact_usd must be the gap between reported and "
                         "adjusted diluted EPS of the page's quarter")
    story = story_block(staging)
    return {
        "kind": "grouped_bars",
        # The second shell is a quarter's story (an effect the company named but
        # never sized); without one the chart is simply the company's bridge.
        "title": (f"本季每股收益有两层壳，本页只画得出一层：报表 ${eps:.2f} → 公司调整后 ${adjusted:.2f}"
                  if story.get("eps_second_layer") else
                  f"本季每股收益：报表 ${eps:.2f} → 公司调整后 ${adjusted:.2f}"),
        "xlabels": ["GAAP 报表", f"扣{one_off['item']}净额", "公司调整后"],
        "groups": [{
            "name": "本季摊薄每股收益",
            "color": "NAVY",
            "values": [eps, -round(eps - adjusted, 2), adjusted],
        }],
        "fmt": "usd2",
        "yfmt": "usd2",
        "label_fmt": "usd2",
        "ylab": "US$",
        "note": (
            f"第一层是公司自己做的：${one_off['gross_usd_m']:,.0f}M {one_off['item']}减 "
            f"${one_off['related_expense_usd_m']:,.0f}M {one_off['related_expense']}，"
            f"净 ${one_off['net_pretax_usd_m']:,.0f}M 税前、每股 ${one_off['eps_impact_usd']:.2f}，"
            f"报表 ${eps:.2f} 因此调整为 ${adjusted:.2f}。"
            + fill_story(story.get("eps_second_layer", ""), values)
        ),
        "src_extra": one_off["src_extra"],
    }


def full_year_split_chart(staging: dict, outlook: dict) -> dict:
    """Year-to-date reported against the rest of the year the full-year guide implies."""
    record = staging["quarterly_guidance_history"]
    fq = fiscal_quarter(staging)
    ytd_word, rest_word = YTD_LONG[fq], YTD_REST[fq]
    i = record["quarters"].index(staging["periods"][-1])
    q_lo, q_hi, q_actual = (record["guide_eps_lo_usd"][i], record["guide_eps_hi_usd"][i],
                            record["actual_eps_usd"][i])
    ytd_eps, prior_ytd, prior_fy = (outlook["ytd_eps_usd"], outlook["prior_ytd_eps_usd"],
                                    outlook["prior_fy_eps_usd"])
    new_lo, new_hi = outlook["fy_guide_usd"]
    old_lo, old_hi = outlook["prior_fy_guide_usd"]
    new_mid, old_mid, q_mid = (new_lo + new_hi) / 2, (old_lo + old_hi) / 2, (q_lo + q_hi) / 2
    rest_now = new_mid - ytd_eps
    rest_prior = prior_fy - prior_ytd
    # The old guide split the same way: what the year-to-date would have been had
    # this quarter landed on its guided midpoint.
    rest_old = old_mid - (ytd_eps - q_actual + q_mid)
    ytd_growth = pct_change(ytd_eps, prior_ytd)
    rest_growth = pct_change(rest_now, rest_prior)
    gap = ytd_growth - rest_growth
    raise_lo, raise_hi = round(new_lo - old_lo, 4), round(new_hi - old_hi, 4)
    beat_lo, beat_hi = round(q_actual - q_hi, 4), round(q_actual - q_lo, 4)
    raise_words = f"${min(raise_lo, raise_hi):.2f}–{max(raise_lo, raise_hi):.2f}"
    story = story_block(staging)
    split = "拆成两半" if fq == 2 else f"拆成{ytd_word}与{rest_word}"
    same_mid = abs((new_mid - old_mid) - (q_actual - q_mid)) < 5e-4
    note = (
        f"四个数全是申报值或减法：{ytd_word} ${ytd_eps:.2f} 是本季新闻稿印的；"
        f"全年{outlook['basis']}指引中值 ${new_mid:.3f} 减去它得到{rest_word}隐含 ${rest_now:.3f}；"
        f"去年{ytd_word} ${prior_ytd:.2f} 与去年全年 ${prior_fy:.2f} 同样是公司印的，"
        f"相减得去年{rest_word} ${rest_prior:.2f}。"
        + fill_story(story.get("outlook_verdict", ""), {"gap": f"{gap:.1f}"})
    )
    if new_mid > old_mid:
        note += (f"而且公司这次把全年{outlook['basis']}指引从 ${old_lo:.2f}–{old_hi:.2f} "
                 f"上调到 ${new_lo:.2f}–{new_hi:.2f}，上调幅度 {raise_words}"
                 + (" 恰好等于本季超出指引中值的幅度" if same_mid else "")
                 + (f" —— 把上调前的中值同样拆一次，{rest_word}隐含仍然是 ${rest_old:.3f}，<b>一分没动</b>。"
                    if abs(rest_old - rest_now) < 5e-4 else "。"))
    exhibit = {
        "kind": "grouped_bars",
        "title": (f"全年指引{split}：{ytd_word}{outlook['basis']}每股收益同比 {ytd_growth:+.1f}%，"
                  f"{rest_word}按指引中值隐含{'只有 ' if rest_growth < ytd_growth else ' '}{rest_growth:+.1f}%"),
        "xlabels": [ytd_word, f"{rest_word}（指引隐含）"],
        "groups": [
            {"name": f"去年同期{outlook['basis']}每股收益", "color": "GRAY",
             "values": [prior_ytd, round(rest_prior, 6)]},
            {"name": f"本年{outlook['basis']}每股收益", "color": "NAVY",
             "values": [ytd_eps, round(rest_now, 6)]},
        ],
        "fmt": "usd2",
        "yfmt": "usd2",
        "label_fmt": "usd2",
        "ylab": "US$",
        "note": note,
        "src_extra": "各季与各年每股收益、全年指引区间均为公司披露值；上下半年拆分为减法。"
        if fq == 2 else "各季与各年每股收益、全年指引区间均为公司披露值；拆分为减法。",
    }
    return {"exhibit": exhibit, "ytd": ytd_word, "rest": rest_word, "gap": gap, "basis": outlook["basis"],
            "ytd_growth": ytd_growth, "rest_growth": rest_growth,
            "new_mid": new_mid, "old_mid": old_mid, "rest_now": rest_now, "rest_old": rest_old,
            "raise": raise_words, "beat": (beat_lo, beat_hi)}


def corporate_expense_chart(staging: dict, labels: list[str], ytd: dict) -> dict:
    seg = staging["segments_usd_m"]
    gce = seg["general_corporate_expense"]
    fq = fiscal_quarter(staging)
    yoy = [None if current is None or prior is None
           else round(pct_change(current, prior), 4)
           for current, prior in zip(gce, seg["general_corporate_expense_prior_year"])]
    drawn = [value for value in yoy if value is not None]
    q_yoy = pct_change(gce[-1], gce[-5])
    ytd_now, ytd_prior = ytd["general_corporate_expense"][-1], ytd["general_corporate_expense"][0]
    ytd_yoy = pct_change(ytd_now, ytd_prior)
    note = (f"本季 ${gce[-1]:,.1f}M，去年同期 ${gce[-5]:,.1f}M，"
            f"同比{'多出' if gce[-1] >= gce[-5] else '少了'} ${abs(gce[-1] - gce[-5]):,.1f}M")
    if fq > 1:
        opposite = round(q_yoy) * round(ytd_yoy) < 0
        note += (f"；但{YTD_LONG[fq]}累计 ${ytd_now:,.0f}M 反而{'低于' if ytd_yoy < 0 else '高于'}去年的 ${ytd_prior:,.0f}M。"
                 f"<b>同一条费用线，单季同比 {q_yoy:+.0f}%，{YTD_SHORT[fq]}同比 {minus_sign(f'{ytd_yoy:+.0f}')}%。</b>"
                 if opposite else
                 f"；{YTD_LONG[fq]}累计 ${ytd_now:,.0f}M，去年 ${ytd_prior:,.0f}M。")
    else:
        note += "。"
    if min(drawn) < 0 < max(drawn):
        note += (f"右轴那条绿线是它{cn_count(len(drawn))}季的单季同比："
                 f"在 {minus_sign(f'{min(drawn):.0f}')}% 到 {max(drawn):+.0f}% 之间来回甩，没有方向可言。")
    note += ("所以任何用「分部利润之和 − 公司费用 = 税前利润」做的单季推断都会被这条线带偏，"
             f"跨季只能用{YTD_SHORT[fq] if fq > 1 else '累计'}口径。")
    low = since_low(gce, labels, len(gce) - 2)
    if low:
        note += (f"上季的 ${gce[-2]:,.0f}M 是 {low} 以来的低点，"
                 "而且是从分部表直接读到的申报值，不必用半年数减本季数反推。")
    return {
        "kind": "gs_bar",
        "title": (
            f"一般公司费用 {len(labels)} 季在 ${min(gce):,.0f}M–"
            f"${max(gce):,.0f}M 之间摆动，"
            "分部利润之和到税前利润的桥在单季维度不可读"
        ),
        "xlabels": labels,
        "values": gce,
        "legend": "一般公司费用",
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$M",
        "ylab2": "同比",
        # The twelve-period average line is opt-in: the engine never computes
        # that average, it only draws a finite `avg12` handed to it by the
        # payload, and the line, its contribution to the y-axis range and the
        # legend key are all gated on that one condition (see the `avg12` entry
        # in the assets/charts.js header). A `gs_bar` given neither field is
        # simply a clean bar chart. So `yoy` is not here to suppress an average
        # -- it is here because this one has a filed prior-year column to build
        # it from, and the resulting line is the argument the chart is making.
        "yoy": {
            "name": "同比增速 (RHS)",
            # The prior-year column is carried for the reviewed quarters only,
            # so this line is a hole wherever its own comparison base is.
            "values": yoy,
            "color": "GREEN",
            "yfmt": "pct1",
        },
        "note": note,
        "src_extra": "各季 8-K 分部表的 General corporate expense 行，申报值。",
    }


# ── section three ────────────────────────────────────────────────────────────
def homegoods_chart(staging: dict, entry: dict | None, labels: list[str],
                    adj_seg: dict | None) -> dict:
    segm = staging["segment_margins_pct"]
    seg = staging["segments_usd_m"]
    sales = staging["financials"]["net_sales_usd_m"]
    hg = segm["homegoods_margin_pct"]
    values = hg[:-1] + [adj_seg["homegoods"]["adjusted"]] if adj_seg else list(hg)
    share = seg["homegoods_sales"][-1] / sales[-1] * 100
    if adj_seg:
        impacts = {key: abs(adj_seg[key]["tariff_refund_pp"]) for key in SEGMENTS}
        title_tail = f"本季调整后 {adj_seg['homegoods']['adjusted']:.1f}%，报表 {hg[-1]:.1f}%"
        note = (f"本季这一格取公司披露的调整后值 {adj_seg['homegoods']['adjusted']:.1f}%，"
                f"而不是报表的 {hg[-1]:.1f}% —— 两者差 {impacts['homegoods']:.1f} 个百分点，"
                f"全部是{story_block(staging).get('adjustment_name', '调整项')}"
                + ("，这是四个分部里最大的一格，而 HomeGoods 只占本季销售额的 "
                   if impacts["homegoods"] == max(impacts.values()) else "，HomeGoods 占本季销售额的 ")
                + f"{share:.1f}%。")
    else:
        title_tail = f"本季 {hg[-1]:.1f}%"
        note = f"HomeGoods 占本季销售额的 {share:.1f}%。"
    if entry is not None:
        note += fill_story(entry.get("reading", ""),
                           {"threshold": f"{entry['threshold']:.1f}%",
                            "hold_above": f"{entry.get('hold_above', entry['threshold']):.1f}%"})
    return record_line(
        f"HomeGoods 分部利润率 {len(labels)} 季：{title_tail}",
        labels, rounded(values),
        fmt="pct1", ylab="%", name=("HomeGoods 分部利润率（本季取调整后）" if adj_seg
                                    else "HomeGoods 分部利润率"),
        threshold=entry["threshold"] if entry else None,
        threshold_name=f"下季警示线 {entry['threshold']:.1f}%" if entry else "",
        note=note,
        src_extra=("分部利润率为分部利润除以分部销售额的自算值"
                   + ("；调整后值为公司披露值。" if adj_seg else "。")),
    )


def capital_intensity_chart(staging: dict, ytd: dict, store_plan: dict | None,
                            raised_today: bool) -> dict:
    fq = fiscal_quarter(staging)
    word = YTD_LONG[fq]
    now = ytd["capital_expenditures"][1] / ytd["net_sales"][1] * 100
    prior = ytd["capital_expenditures"][0] / ytd["net_sales"][0] * 100
    ar_prior, ar_now = ytd["receivables_and_other_assets_change"]
    inv_prior, inv_now = ytd["inventories_change"]
    one_off = block(staging, "one_off_usd_m")

    def money(value: float) -> str:
        return f"{'−' if value < 0 else '+'}${abs(value):,.0f}M"

    note = (
        f"{word}经营现金流 ${ytd['operating_cash_flow'][1]:,}M，同比 "
        f"{signed(pct_change(ytd['operating_cash_flow'][1], ytd['operating_cash_flow'][0]))}；"
        f"资本开支 ${ytd['capital_expenditures'][1]:,}M，同比 "
        f"{signed(pct_change(ytd['capital_expenditures'][1], ytd['capital_expenditures'][0]))}。"
        "<b>现金流这一格要打折：</b>它含营运资本的摆动 —— 业绩 8-K 的"
        f"{word}现金流量表逐行印出了营运资本各项，其中应收及其他资产由去年同期的 {money(ar_prior)} "
        f"转为 {money(ar_now)}、存货占用由 {money(inv_prior)} 变为 {money(inv_now)}"
        + (f"；也含本季一次性的{one_off['item']}，{one_off['cash_note']}，属于不可重复的来源。"
           if one_off and one_off.get("cash_note") else "。")
        + f"资本开支那一格才是要跟的：占销售额{'已经从' if now > prior else '从'} {prior:.2f}% "
        f"{'升到' if now > prior else '降到'} {now:.2f}%"
    )
    if raised_today:
        note += (f"，而公司同一天宣布 FY{store_plan['growth_from_fy']} 起开店增速从 "
                 f"{store_plan['previous_growth_pct']:.0f}% 提到 {store_plan['growth_pct']:.0f}%、"
                 f"长期门店目标从 {store_plan['previous_target']:,} 提到 {store_plan['target']:,}。")
    else:
        note += "。"
    return {
        "kind": "grouped_bars",
        "title": (
            f"资本强度：{word}资本开支占销售额 {now:.2f}%，去年同期 {prior:.2f}%"
        ),
        "xlabels": ["经营现金流", "资本开支", "回购", "分红"],
        "groups": [
            {"name": f"去年{word}", "color": "GRAY",
             "values": [ytd[key][0] for key in
                        ("operating_cash_flow", "capital_expenditures",
                         "share_repurchases", "dividends_paid")]},
            {"name": f"今年{word}", "color": "NAVY",
             "values": [ytd[key][1] for key in
                        ("operating_cash_flow", "capital_expenditures",
                         "share_repurchases", "dividends_paid")]},
        ],
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$M",
        "note": note,
        "src_extra": f"{word}现金流量与销售额均为公司披露的累计值；占比为自算。",
    }


# ── section four ─────────────────────────────────────────────────────────────
def long_charts(staging: dict, ytd_word: str, store_plan: dict | None,
                raised_today: bool) -> list[dict]:
    fiscal_year, fiscal_q = fiscal_parts(staging["fiscal_labels"][-1])
    this_year = f"本年{ytd_word}" if fiscal_q < 4 else f" FY{fiscal_year} 全年"
    # The year to date is news only while the annual record has not reached it.
    ytd_is_new = fiscal_year > int(staging["long_history"]["fiscal_years"][-1][2:])
    long = staging["long_history"]
    fy_labels = long["fiscal_years"]
    n_years = len(fy_labels)
    years = "十年" if n_years == 10 else f"{cn_count(n_years)}年"
    margin, intensity = long["pretax_margin_pct"], long["capex_intensity_pct"]
    pandemic = fy_labels.index(PANDEMIC_YEAR)
    # The post-pandemic trough of capital intensity: a year of shut stores is not
    # a baseline anything should be measured from.
    base = min((i for i in range(n_years) if i != pandemic), key=lambda i: intensity[i])
    ytd = ytd_block(staging)
    ytd_intensity = ytd["capital_expenditures"][1] / ytd["net_sales"][1] * 100
    margin_top = margin[-1] == max(margin)
    capex_top = intensity[-1] == max(intensity)
    top = max(range(n_years), key=lambda i: intensity[i])
    rising = all(margin[i] > margin[i - 1] for i in range(pandemic + 1, n_years))
    long_weeks = [fy for fy, w in zip(fy_labels, long["weeks"]) if w == 53]
    stores = staging["operations"]["store_count"]
    shares = staging["financials"]["diluted_shares_m"]
    buyback = long["share_repurchases_usd_m"]
    after = buyback[pandemic + 1:]
    fcf = [o - c for o, c in zip(long["operating_cash_flow_usd_m"], long["capital_expenditures_usd_m"])]
    returned = [b + d for b, d in zip(buyback, long["dividends_paid_usd_m"])]
    apart = [i for i in range(n_years) if returned[i] < 0.5 * fcf[i]]
    growth = ((long["store_count"][-1] / long["store_count"][0]) ** (1 / (n_years - 1)) - 1) * 100
    area = ((long["square_feet_m"][-1] / long["square_feet_m"][0]) ** (1 / (n_years - 1)) - 1) * 100
    target = store_plan["target"] if store_plan else None
    story = story_block(staging)
    share_yoy = pct_change(shares[-1], shares[-5])
    return [
        {
            "kind": "bar_line",
            # The endpoints of capital intensity can look flat, which would read
            # as contradicting the rest of the page. The move that matters is off
            # the post-pandemic trough, so the title says that and the chart
            # still draws every year.
            "title": (
                f"{years}税前利润率与资本强度：利润率 {margin[0]:.1f}% → "
                f"{margin[-1]:.1f}%" + (f" 创{years}高" if margin_top else "") + "；"
                f"资本开支占销售额自 {fy_labels[base]} 的 {intensity[base]:.1f}% 回到 "
                f"{intensity[-1]:.1f}%"
            ),
            "xlabels": fy_labels,
            "bar": {"name": "税前利润率", "color": "NAVY",
                    "values": rounded(margin)},
            "line": {"name": "资本开支 / 销售额 D", "color": "RED",
                     "values": rounded(intensity)},
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "ylab": "%",
            "note": (
                f"{years}是这条线最短的可读窗口：八个季度分不清趋势与抖动，"
                "而资本强度的一个建店周期本来就跨年。"
                f"{PANDEMIC_YEAR} 的 {margin[pandemic]:.1f}% 是疫情年，门店大面积关闭；"
                f"此后利润率{'连年抬升' if rising else '回升'}到 {fy_labels[-1]} 的 {margin[-1]:.1f}%"
                + (f"，是{years}最高。" if margin_top else "。")
                + "<b>但两条线在最近几年一起往上走：</b>资本强度从 "
                f"{fy_labels[base]} 的 {intensity[base]:.1f}% 升到 {fy_labels[-1]} 的 "
                f"{intensity[-1]:.1f}%"
                + (f"，而{this_year}{'已经' if ytd_intensity > intensity[-1] else ''}是 {ytd_intensity:.2f}%。"
                   if ytd_is_new else "。")
                + (f"利润率与资本强度同时创{years}高，是这一页的长期背景。" if margin_top and capex_top
                   else f"利润率创{years}高，资本强度的{years}高点则是 {fy_labels[top]} 的 {intensity[top]:.1f}%，"
                   "是这一页的长期背景。" if margin_top
                   else "")
                + (f"{' 与 '.join(long_weeks)} 是 53 周财年，销售额多一周，两个比率因此略被稀释。"
                   if long_weeks else "")
            ),
            "src_extra": "各年 10-K 的合并损益表与现金流量表；两个比率为自算。",
        },
        {
            "kind": "bar_line",
            "title": (
                f"{years}门店数与总面积：{long['store_count'][0]:,} 家 → "
                f"{long['store_count'][-1]:,} 家"
                + (f"，长期目标刚从 {store_plan['previous_target']:,} 提到 {target:,}" if raised_today
                   else f"，长期目标 {target:,} 家" if target else "")
            ),
            "xlabels": fy_labels,
            "bar": {"name": "财年末门店数", "color": "BLUE", "values": long["store_count"]},
            "line": {"name": "财年末总面积（百万平方英尺）", "color": "NAVY",
                     "values": long["square_feet_m"]},
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "家 / 百万平方英尺",
            "note": (
                f"{years}净增 {long['store_count'][-1] - long['store_count'][0]:,} 家，"
                f"年化 {growth:.1f}%；"
                f"面积年化 {area:.1f}%"
                + ("，低于门店数 —— 新开的店平均比存量店小，公司自己也确认了这一点。" if area < growth else "。")
                + (f"本季末 {stores[-1]:,} 家，距{'新的 ' if raised_today else ''}{target:,} 家长期目标还有 "
                   f"{target - stores[-1]:,} 家（+{(target / stores[-1] - 1) * 100:.1f}%）。" if target else "")
                + (story.get("store_chart_tail", "") if raised_today else "")
            ),
            "src_extra": "各年 Q4 业绩 8-K 的 Stores by Concept 表，财年末申报值。",
        },
        {
            "kind": "bar_line",
            "title": (
                f"{years}回购与股数：累计回购 US${sum(buyback) / 1000:.1f}B，"
                f"股数 {long['diluted_shares_m'][0]:,.0f}M → {long['diluted_shares_m'][-1]:,.0f}M"
            ),
            "xlabels": fy_labels,
            "bar": {"name": "回购金额", "color": "GOLD",
                    "values": buyback},
            "line": {"name": "摊薄股数（百万股）", "color": "NAVY",
                     "values": long["diluted_shares_m"]},
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "US$M / 百万股",
            "note": (
                f"{years}股数减少 {(1 - long['diluted_shares_m'][-1] / long['diluted_shares_m'][0]) * 100:.1f}%，"
                f"年化约 {abs(((long['diluted_shares_m'][-1] / long['diluted_shares_m'][0]) ** (1 / (n_years - 1)) - 1) * 100):.1f}%；"
                f"本季同比 {signed(share_yoy)}"
                + (f"，也就是说每股收益的同比增长里大约有{cn_count(round(abs(share_yoy)))}个百分点来自股数而不是利润。"
                   if share_yoy < 0 and round(abs(share_yoy)) >= 1 else "。")
                + f"{PANDEMIC_YEAR} 的 US${buyback[pandemic]:,.0f}M 是疫情年暂停回购留下的缺口，"
                f"此后每年都在 US${int(min(after) / 100) / 10:.1f}B 以上。"
                "股数一律换算到 2018 年 11 月一拆二之后的口径。"
            ),
            "src_extra": "各年 10-K 现金流量表的回购支出与损益表的摊薄股数。",
        },
        {
            "kind": "grouped_bars",
            "title": (
                f"{years}经营现金流、资本开支与股东回报：{fy_labels[-1]} 分别为 "
                f"US${long['operating_cash_flow_usd_m'][-1] / 1000:.1f}B、"
                f"US${long['capital_expenditures_usd_m'][-1] / 1000:.1f}B 与 "
                f"US${returned[-1] / 1000:.1f}B"
            ),
            "xlabels": fy_labels,
            "groups": [
                {"name": "经营现金流", "color": "NAVY", "values": long["operating_cash_flow_usd_m"]},
                {"name": "资本开支", "color": "BLUE", "values": long["capital_expenditures_usd_m"]},
                {"name": "回购 + 分红", "color": "GOLD", "values": returned},
            ],
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "bar_labels": False,
            "ylab": "US$M",
            "note": (
                "三根柱放在一起才看得出这家公司的资本配置结构："
                "经营现金流覆盖资本开支之后剩下的，基本原样还给了股东 —— "
                f"最近五年回购加分红合计 US${sum(returned[-5:]) / 1000:.1f}B，"
                f"同期经营现金流减资本开支 US${sum(fcf[-5:]) / 1000:.1f}B。"
                + (f"{PANDEMIC_YEAR} 是唯一一年三者脱节：现金流因为压缩存货反而不低，"
                   "而资本开支与股东回报同时被砍。" if apart == [pandemic] else "")
            ),
            "src_extra": "各年 10-K 现金流量表，申报值。",
        },
    ]


# ── the notes that describe the record ───────────────────────────────────────
def record_starts_note(record: dict) -> str:
    def start(key: str) -> str:
        return record["quarters"][next(i for i, v in enumerate(record[key]) if v is not None)]
    starts: dict[str, list[str]] = {}
    for key, name in (("guide_eps_lo_usd", "每股收益"), ("guide_pretax_margin_lo_pct", "税前利润率"),
                      ("guide_comp_lo_pct", "合并 comp")):
        starts.setdefault(start(key), []).append(name)
    if len(starts) == 3:
        where = "三条记录起点不同（" + "、".join(f"{names[0]} {q}" for q, names in starts.items()) + "）"
    elif len(starts) == 2:
        where = "；".join(spaced("与".join(names), f"{'都' if len(names) > 1 else ''}从 {q} 起")
                         for q, names in starts.items())
    else:
        where = f"三条记录都从 {next(iter(starts))} 起"
    return ("第一节的指引兑现组图用的是同一批业绩 8-K：EX-99.1 新闻稿末尾的 Outlook 段落给出下一季的指引区间，"
            "实际值取自随后一季的业绩 8-K（每股收益与税前利润率取 Financial Summary 合并损益表，"
            f"comp 取 Comparable Sales 分部表）。{where}，各图按自己的记录长度画，不往前补。")


def withheld_note(record: dict) -> str:
    held = withheld_words(record)
    return (f"公司在 {held['span'][0]}至 {held['span'][1]}的{held['releases']}份业绩稿里写明不提供指引，"
            f"连续 {held['gap']} 个会计季没有任何数字指引。"
            + withdrawal_sentence(record)
            + f"图在这里打断点（每股收益的横轴从 {held['before']} 直接跳到 {held['after']}）；"
            "这段空白不计入任何命中率的分母。")


def split_note(record: dict) -> str:
    split = record["split_adjusted_before"]
    i = record["quarters"].index(split)
    return ("2018 年 11 月一拆二：在此之前公布的每股收益指引与实际值一律除以 2，换算到当前股本口径。"
            "二比一的换算是精确的，不是估计。"
            f"跨拆股的只有一个季度（{split}，指引在拆股前给出、实际在拆股后报出），"
            f"换算后指引为 US${record['guide_eps_lo_usd'][i]:.2f}–{record['guide_eps_hi_usd'][i]:.2f}、"
            f"实际 US${record['actual_eps_usd'][i]:.2f}。")


def fifty_three_week_note(long: dict) -> str:
    years = [fy for fy, w in zip(long["fiscal_years"], long["weeks"]) if w == 53]
    return (f"{' 与 '.join(years)} 是 53 周财年，多出来的一周落在会计季 Q4。"
            "FY2024 Q4 的指引本身就是按 14 周给的，公司同时另给了一份剔除多出一周的口径，"
            "本页取与指引同口径的那一个；十年年度表里标注了周数。")


def scored_adjusted(record: dict) -> dict:
    """The quarters scored on the company's adjusted figure -- among those already reported."""
    reported = {q for q, a in zip(record["quarters"], record["actual_eps_usd"]) if a is not None}
    return {q: item for q, item in record["scored_on_adjusted"].items() if q in reported}


def adjusted_basis_note(record: dict) -> str:
    adjusted = scored_adjusted(record)
    rule = ("调整项在指引给出之后才出现（或指引原文写明不含它）、公司又印了只剔除这一项的调整后数的季度，"
            "指引兑现按调整后口径比较 —— 那也是公司自己判定「相对 plan」时所用的口径；"
            "用报表值去对当初的区间，等于让指引为它装不下的事负责。")
    if not adjusted:
        return rule + "本记录里还没有这样的季度，一律按报表口径计。"
    return (rule + "这样计的有" + cn_count(len(adjusted)) + "季："
            + "、".join(spaced(f"{quarter} 的", item["event"]) for quarter, item in adjusted.items())
            + "。其余季度按报表口径计。")


def identity_note(staging: dict) -> str:
    n = len(staging["periods"])
    charged = [p for p, v in zip(staging["periods"], staging["financials"]["other_charges_usd_m"])
               if v is not None]
    inside = staging["other_charges_note"]["inside_a_segment"]
    return ("会计季 Q4 没有 10-Q，其损益与分部数值取自 Q4 业绩 8-K 里印出的「Thirteen Weeks Ended」一栏，"
            f"是申报的季度值而不是财年数减九个月数的差分值。{n} 季核心表与分部序列因此全部是申报值，"
            "两条恒等式（收入 − 销货成本 − SG&A + 净利息收入 = 税前利润；分部利润之和 − 公司费用 + 净利息收入 = 税前利润）"
            f"在 {n} 个季度里逐季对得上，差额为零"
            + (f"（其中{cn_count(len(charged))}季在 SG&A 与税前之间多一条具名费用行，恒等式要把它算进去"
               + (f"；{'、'.join(inside)} 那一笔计在分部利润之内，分部那条不再减它" if inside else "")
               + "）" if charged else "")
            + "。")


def inventory_definition_note(staging: dict) -> str:
    """The per-store inventory line is the company's own figure, and its scope moved twice."""
    note = staging["inventory_per_store_note"]
    return ("每店库存同比取公司在每份业绩新闻稿 Inventory 段印出的「per-store basis」同比（含配送中心，不含在途与电商），"
            "报表口径与固定汇率口径各一个整数，页面按报表口径结算阈值。它的口径边界："
            + "；".join(f"{item['from']} {item['change']}" for item in note["scope_changes"])
            + "；每一格都是同一口径下的同比。" + note["holes"]
            + "本页以前画的「资产负债表存货 ÷ 期末门店数」是自算值，与公司口径不是同一个定义，已不再发布。")


def peer_note(staging: dict) -> str:
    # The six Ross holes are fixed history: 2020 Q1 (no comp reported), 2020 Q2
    # (reopened stores only) and the four 2021 quarters (stated against 2019).
    return ("同业对照只取 Ross Stores，用的是它自己申报的 comp：两家的会计季截至同一个星期六，所以是同一段十三周；"
            "每格读自 Ross 当季业绩 8-K 的 EX-99.1，逐季出处与原文在 series 里。Ross 2020 年一季不报 comp、"
            "一季只报重开门店的 comp，2021 年四季对比的是 2019 年，这六季不是同比，留空。")


def guidance_table(guidance: dict | None, outlook_chart: dict | None) -> dict | None:
    if guidance is None:
        return None
    values = {}
    if outlook_chart:
        values = {"old_mid": f"${outlook_chart['old_mid']:.3f}", "new_mid": f"${outlook_chart['new_mid']:.3f}",
                  "raise": outlook_chart["raise"], "rest_now": f"${outlook_chart['rest_now']:.3f}",
                  "rest": outlook_chart["rest"], "ytd": outlook_chart["ytd"]}
    return {
        "title": guidance["title"],
        "headers": guidance["headers"],
        "rows": guidance["rows"],
        "note": fill_story(guidance["note"], values),
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "tjx.js"), payload, "tjx")
    shell_dir = ROOT / "tjx"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("TJX", "tjx"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(
        f"TJX page: {charts} charts in {len(payload['sections'])} sections "
        f"+ {len(payload['tables'])} audit tables"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
