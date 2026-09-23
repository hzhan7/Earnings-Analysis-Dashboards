#!/usr/bin/env python3
"""Build the Broadcom quarterly-results page.

Same four-part, chart-led shape as the other pages (上季兑现 → 本季重点 →
下季跟踪 → 长期常规). Broadcom's outlook reaches a filing every quarter, and its
record is a shape none of the other pages have: the interesting variable is not
how far the quarter cleared the bar, it is **what kind of bar the company was
willing to publish**.

The outlook block changes form several times across the earnings 8-Ks. It
opens as a full GAAP/non-GAAP table with a revenue range (`$5,047M +/- $75M`);
becomes a fiscal-year number for all of FY2019; comes back as a quarterly range
through the first COVID year; from the FY2021 Q1 outlook onward is a bare point
(`approximately $6.6 billion`), with Adjusted EBITDA soon quoted as a
percentage of projected revenue rather than a dollar amount; reverts to
fiscal-year guidance for three releases across the VMware year; and then returns
to quarterly points. The 2026-09-02 release dropped Adjusted EBITDA altogether
and guides a non-GAAP operating margin instead.

What that produces is a two-sided answer: in every quarter Broadcom published a
revenue *range*, the reported number landed inside it; in every finished quarter
it published a *point*, the reported number came in above it; and read against
the guided point or midpoint, the beats sit in a narrow positive band. The
outlook goes out about a month into the quarter it guides, so this is much less
a forecast than a disclosure of something already largely known, and every
guidance chart on the page says so.

Every count, band, date and verdict in the prose is computed from
`series/avgo.json` -- a quarter roll edits that file and nothing here. The
universal claims ("never below", "all inside the range") are guarded by the
data they describe, so a quarter that broke one would change the sentence
rather than leave it false. What only one quarter has (the follow-up closure,
the settlement of the previous report's section-8 thresholds, the guidance by
business line, this report's thresholds, the quarter's story, the buyback
story, the outlook's wording) lives in blocks stamped with the quarter they
describe; a block stamped for another quarter stops the build
(`board.stamped_block`). At the roll, `next_kpi` moves into
`prior_kpi_settlement` with the same fields: its `unquantified` rows are
rewritten as `unsettled` and its call-only readings re-read from the new call,
or the build stops and says which. A threshold whose reading lives only in the
10-Q / 10-K waits, named, until that filing lands (`AvgoRollTest`).

The page's own series is the decomposition. Guiding a revenue level and an
Adjusted EBITDA *margin* implies an Adjusted EBITDA dollar amount Broadcom never
prints, and the distance from what it reported splits exactly two ways — a
revenue leg and a margin leg — with no estimate anywhere. A second identity
licenses the segment view: the two reportable segments' filed operating incomes
sum to the company's non-GAAP operating income **exactly, in every quarter the
segment note carries them**, so the margin the company guides can be attributed
to the semiconductor engine and the software engine separately.

The public payload contains only Broadcom-reported figures, clearly labelled
market expectations, and arithmetic reproducible from the audit tables.
"""

from __future__ import annotations

import datetime
import json
import math
import statistics
import sys
from dataclasses import dataclass
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
    hyperscaler_capex_share,
    latest_block,
    midpoint_deviation,
    number_exhibits,
    stamped_block,
    threshold_exhibit,
    unit_text,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "avgo.json"
DATA_DIR = ROOT / "data"

# The eight-quarter block the standard charts use.
WINDOW = 8

# Fixed history the prose names. VMware closed on 2023-11-22, inside Broadcom's
# FY2024 Q1 -- this site's Q4 2023 -- so that is the first quarter it
# consolidates and the fiscal year its annual-only guidance covered.
VMWARE_FIRST_PERIOD = "Q4 2023"
VMWARE_FISCAL_YEAR = "FY2024"

# How the company wrote its revenue range, quoted from the first release of each
# range year (2018-06-07 and 2020-03-12). The range era is closed history; a
# range year with no quote here is still counted, just not quoted.
RANGE_WORDING = {
    2018: "$5,047M +/- $75M",
    2020: "$5.7 billion plus or minus $150 million",
}

# What the outlook phases carry beyond their form, keyed by the phase's first
# release. Also closed history.
PHASE_DETAIL = {
    "2018-06-07": "含 GAAP/non-GAAP 对照表的",
    "2023-12-07": "VMware 并表那一年",
}

AUDIT_WORDS = {"unaudited": "未审计", "audited": "已审计"}


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100


def compact_period(period: str) -> str:
    """``'Q1 2026'`` → ``'Q1'26'``."""
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


def year_of(period: str) -> int:
    return int(period.split()[1])


def rounded(values: list[float | None], digits: int = 6) -> list[float | None]:
    return [None if value is None else round(value, digits) for value in values]


def ratio(numerators: list[float | None], denominators: list[float | None],
          scale: float = 100.0) -> list[float | None]:
    out: list[float | None] = []
    for top, bottom in zip(numerators, denominators):
        out.append(None if top is None or not bottom else round(top / bottom * scale, 6))
    return out


def moved(new: float, old: float, up: str = "升到", down: str = "降到") -> str:
    return up if new > old else (down if new < old else "持平在")


def spaced(left: str, right: str) -> str:
    """Join two runs of text with the space this site puts between Han and Latin."""
    gap = " " if left and right and (left[-1].isascii() and left[-1].isalnum()
                                     or right[0].isascii() and right[0].isalnum()) else ""
    return left + gap + right


def joined(names: list[str]) -> str:
    """``['A', 'B', 'C']`` → ``'A、B与C'``; ``['收入', 'non-GAAP …']`` → ``'收入与 non-GAAP …'``."""
    if len(names) == 1:
        return names[0]
    return spaced(spaced("、".join(names[:-1]), "与"), names[-1])


def filed_form(fiscal_label: str) -> str:
    """The periodic report a fiscal quarter's notes arrive in."""
    return "10-K" if fiscal_label.endswith("Q4") else "10-Q"


def days_between(start: str, end: str) -> int:
    return (datetime.date.fromisoformat(end) - datetime.date.fromisoformat(start)).days


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
    "指引取自各季业绩 8-K 的 EX-99.1 新闻稿「Business Outlook」区块；"
    "实际值取自随后一季 8-K 的合并损益表与 GAAP/non-GAAP 对账表，"
    "并与 XBRL companyfacts 逐季核对一致。"
)


# Broadcom publishes each quarter's outlook alongside the *previous* quarter's
# results, and that release lands about a month into the quarter being guided.
# A record with no misses means much less when part of the quarter is already
# banked, so the caveat travels with every chart rather than sitting in a note.
def release_timing(record: dict) -> tuple[float, float]:
    """(median day of the guided quarter the outlook goes out on, its median length)."""
    return (statistics.median(record["days_into_quarter_at_release"]),
            statistics.median(record["quarter_length_days"]))


def timing_caveat(record: dict, never_below: bool) -> str:
    days, length = release_timing(record)
    return (
        "<b>时点提醒</b>：公司是在上一季业绩发布时才给出这一季的指引，"
        "而那场发布落在被指引季度<b>已经开始之后</b>——"
        f"中位数是 {length:.0f} 天里的第 {days:.0f} 天。"
        + ("所以「从未低于指引」描述的不是一个纯粹的事前预测，"
           if never_below else "所以这份兑现记录描述的不是一个纯粹的事前预测，")
        + f"而是一个已经过掉{cn_fraction(days / length)}的季度。"
    )


def timing_phrase(record: dict) -> str:
    days, _ = release_timing(record)
    return f"该季<b>开始约{cn_count(max(1, round(days / 30)))}个月后</b>"


def revenue_deviation(record: dict) -> list[tuple[int, float]]:
    """(row, actual ÷ guided point or midpoint − 1, in %) for every finished row."""
    return [
        (index, (actual / (mid if mid is not None else (lo + hi) / 2) - 1) * 100)
        for index, (lo, hi, mid, actual) in enumerate(zip(
            record["guide_revenue_lo_usd_m"], record["guide_revenue_hi_usd_m"],
            record["guide_revenue_usd_m"], record["actual_revenue_usd_m"]))
        if actual is not None
    ]


def outlook_phases(record: dict, annual: list[dict]) -> list[dict]:
    """Every outlook release in date order, grouped into runs of one form.

    A form is 「区间」 or 「单点」 for a quarterly outlook and 「财年」 for a
    release that guided only the fiscal year. The note that narrates the record
    counts its changes of form from these runs, so a release that changes the
    form again changes the count without anyone rewriting it.
    """
    releases = [(released, form, label) for released, form, label in zip(
        record["guided_in_release"], record["revenue_form"], record["fiscal_labels"])]
    releases += [(entry["released"], "annual", "FY" + entry["fiscal_year_end"][:4])
                 for entry in annual]
    phases: list[dict] = []
    for released, form, label in sorted(releases):
        if phases and phases[-1]["form"] == form:
            phases[-1]["releases"].append(released)
            phases[-1]["labels"].append(label)
        else:
            phases.append({"form": form, "releases": [released], "labels": [label]})
    return phases


def quarter_span(labels: list[str], open_ended: bool) -> str:
    """``['FY2018 Q3', 'FY2018 Q4']`` → ``'FY2018 Q3–Q4'``; open → ``'FY2024 Q4 起'``."""
    first, last = labels[0], labels[-1]
    if open_ended:
        return f"{first} 起"
    if first.split()[0] == last.split()[0]:
        return f"{first}–{last.split()[1]}"
    return f"{first}–{last}"


def phase_words(phases: list[dict], record: dict) -> str:
    pct_start = next((label for label, unit in zip(record["fiscal_labels"], record["ebitda_unit"])
                      if unit == "pct"), None)
    words = []
    seen = set()
    for index, phase in enumerate(phases):
        form, labels = phase["form"], phase["labels"]
        detail = PHASE_DETAIL.get(phase["releases"][0], "")
        again = form in seen
        seen.add(form)
        if form == "annual":
            years = list(dict.fromkeys(labels))
            count = cn_count(len(phase["releases"]))
            if detail:
                words.append(f"{detail}{'又' if again else ''}有{count}份新闻稿只给财年数")
            else:
                words.append(f"此后{count}份新闻稿只给财年数（{joined(years)}）")
            continue
        span = quarter_span(labels, open_ended=index == len(phases) - 1)
        if form == "range":
            words.append(spaced(span, "回到季度区间") if again
                         else spaced(span, f"是{detail}季度收入区间"))
        elif again:
            words.append(spaced(span, "回到季度单点"))
        else:
            text = spaced(span, "改为单点")
            if pct_start and pct_start in labels:
                text += f"，Adjusted EBITDA 自 {pct_start} 起从美元金额改为「占预计收入的百分比」"
            words.append(text)
    return "；".join(words)


def unguided_quarters(staging: dict) -> list[tuple[str, list[int]]]:
    """Reported quarters the company never guided as quarters, by fiscal year."""
    record = staging["quarterly_guidance_history"]
    guided = set(record["period_ends"])
    first = min(guided)
    groups: dict[str, list[int]] = {}
    for end, label in zip(staging["period_ends"], staging["fiscal_labels"]):
        if end >= first and end not in guided:
            year, quarter = label.split()
            groups.setdefault(year, []).append(int(quarter[1:]))
    return list(groups.items())


def unguided_words(groups: list[tuple[str, list[int]]]) -> str:
    parts = []
    for year, quarters in groups:
        prefix = f"VMware 并表年的 {year}" if year == VMWARE_FISCAL_YEAR else year
        if len(quarters) == 1:
            parts.append(f"{prefix} Q{quarters[0]}")
        elif quarters == list(range(1, len(quarters) + 1)):
            parts.append(f"{prefix} {cn_count(len(quarters))}季" if len(quarters) == 4
                         else f"{prefix} 前{cn_count(len(quarters))}季")
        else:
            parts.append(f"{prefix} Q{quarters[0]}–Q{quarters[-1]}")
    return parts[0] if len(parts) == 1 else "、".join(parts[:-1]) + "，以及 " + parts[-1]


# ── section one: the guided record ──────────────────────────────────────────
def guidance_delivery_charts(staging: dict) -> tuple[list[dict], list[dict]]:
    """The full guided record, split by the form of the guidance itself.

    Broadcom's record cannot go on one band chart, because for some of its
    quarters the guidance has width and for the rest it has none. Forcing both
    onto one chart would have to pick a verdict sentence that is wrong for one
    of the two halves: "cleared the upper bound" is a category error against a
    point, and "identical to the guidance" is a category error against a range
    the quarter landed inside. So the level charts are split by form and the
    scale-free deviation chart, where the distinction does not matter, carries
    the whole record.
    """
    record = staging["quarterly_guidance_history"]
    stop = staging.get("adjusted_ebitda_disclosure_stop")
    periods = record["periods"]
    labels = [compact_period(period) for period in periods]
    forms = record["revenue_form"]
    guide = record["guide_revenue_usd_m"]
    lo = record["guide_revenue_lo_usd_m"]
    hi = record["guide_revenue_hi_usd_m"]
    actual = record["actual_revenue_usd_m"]

    range_idx = [i for i, form in enumerate(forms) if form == "range"]
    point_idx = [i for i, form in enumerate(forms) if form == "point"]
    finished = [i for i, value in enumerate(actual) if value is not None]
    range_finished = [i for i in range_idx if actual[i] is not None]
    point_finished = [i for i in point_idx if actual[i] is not None]
    deviation = [value for _, value in revenue_deviation(record)]
    never_below = all(value >= 0 for value in deviation)
    caveat = timing_caveat(record, never_below)
    timing = timing_phrase(record)

    def take(values, idx):
        return [values[i] for i in idx]

    # ── revenue, the range era ───────────────────────────────────────────────
    by_year: dict[int, int] = {}
    for i in range_idx:
        by_year[year_of(periods[i])] = by_year.get(year_of(periods[i]), 0) + 1
    wording = "，".join(
        f"{year} 年{cn_count(count)}季"
        + (f"写作 <code>{RANGE_WORDING[year]}</code>" if year in RANGE_WORDING else "")
        for year, count in by_year.items())
    inside = [i for i in range_finished if lo[i] <= actual[i] <= hi[i]]
    over_mid = [i for i in range_finished if actual[i] > guide[i]]
    count = cn_count(len(range_finished))
    if len(inside) == len(range_finished):
        range_verdict = (f"{count}季<b>全部落在自己的区间之内</b>，"
                         "既没有穿出上限，也没有跌破下限")
    else:
        range_verdict = f"{count}季里有{cn_count(len(inside))}季落在自己的区间之内"
    range_verdict += (f"——而且{count}季全部落在中值<b>之上</b>。"
                      if len(over_mid) == len(range_finished) else "。")
    range_after = ("此后公司不再给区间，改给单点，见 Exhibit {EX_REV_POINT}。"
                   if point_idx and range_idx[-1] < point_idx[0]
                   else "单点时期见 Exhibit {EX_REV_POINT}。")
    range_chart = delivery_band(
        "EX_REV_RANGE", "收入", take(labels, range_idx),
        take(lo, range_idx), take(hi, range_idx), take(actual, range_idx),
        fmt="f0c", ylab="US$M", unit="US$M", venue="业绩发布", timing=timing,
        scope=f"（仅公司给过区间的 {len(range_idx)} 季）",
        src_extra=SOURCE_8K + caveat,
        extra_note=(
            f"这{cn_count(len(range_idx))}季是 Broadcom 唯一给过<b>收入区间</b>的时期："
            f"{wording}。" + range_verdict + range_after
        ),
    )

    # ── revenue, the point era ───────────────────────────────────────────────
    first_point = point_idx[0]
    above = [i for i in point_finished if actual[i] > guide[i]]
    if len(above) == len(point_finished):
        point_verdict = (
            f"{len(point_finished)} 个已完结季<b>全部高于</b>那个点，一次例外都没有。"
            "但要注意这两件事的顺序：公司是先停止给区间，才有了这条「全部高于」的记录——"
            "一个没有下限的指引，本来也就不存在「跌破下限」这回事。"
        )
    else:
        point_verdict = (f"{len(point_finished)} 个已完结季里有 {len(above)} 季高于那个点、"
                         f"{len(point_finished) - len(above)} 季没有。")
    point_chart = delivery_band(
        "EX_REV_POINT", "收入", take(labels, point_idx),
        take(guide, point_idx), take(guide, point_idx), take(actual, point_idx),
        fmt="f0c", ylab="US$M", unit="US$M", venue="业绩发布", timing=timing,
        scope=f"（公司只给单点的 {len(point_idx)} 季）", point=True,
        src_extra=SOURCE_8K + caveat,
        extra_note=(
            f"自 {record['fiscal_labels'][first_point]} 的指引起，公司把区间换成了一个数——新闻稿原文是 "
            f"<code>approximately ${guide[first_point] / 1000:.1f} billion</code> 这种写法，"
            "所以图上的细线<b>没有宽度可言，这不是渲染问题，是指引本身没有宽度</b>。"
            + point_verdict
            + "量级无关的完整读法见 Exhibit {EX_REV_DEV}。"
        ),
    )

    # ── revenue, the whole record on one scale-free axis ─────────────────────
    span_years = year_of(periods[finished[-1]]) - year_of(periods[finished[0]])
    multiple = actual[finished[-1]] / actual[finished[0]]
    above_two = sum(1 for value in deviation if value > 2)
    spread = (f"最小的一次也有 {min(deviation):+.2f}%，最大 {max(deviation):+.2f}%，"
              f"中位数 {statistics.median(deviation):+.2f}%。")
    if never_below:
        dev_note = (
            f"<b>这是全页最该先读的一张</b>：{len(finished)} 个已完结季里，"
            "实际收入<b>一次都没有低于指引的点或中值</b>——" + spread
            + "真正值得注意的不是「零次低于」，而是<b>这条带子有多窄</b>："
            f"{cn_count(span_years)}年、一次会计年度口径切换、一次 COVID、一次 US$69B 的 VMware 收购、"
            f"以及收入涨到期初的 {multiple:.1f} 倍，"
            + ("偏离却几乎从没超过 +2%。" if above_two <= 0.15 * len(deviation)
               else f"偏离超过 +2% 的也只有 {above_two} 季。")
            + "把它读成「公司预测得准」是读反了；"
            "结合上面的时点提醒，更像是公司只在数字基本落袋之后才把它写进新闻稿。"
        )
    else:
        misses = sum(1 for value in deviation if value < 0)
        dev_note = (
            f"<b>这是全页最该先读的一张</b>：{len(finished)} 个已完结季里，"
            f"实际收入有 {misses} 季低于指引的点或中值——"
            f"最小 {min(deviation):+.2f}%，最大 {max(deviation):+.2f}%，"
            f"中位数 {statistics.median(deviation):+.2f}%。"
        )
    dev_chart = midpoint_deviation(
        "EX_REV_DEV", "收入", periods, guide, guide, actual,
        mode="pct", window=len(finished), label=compact_period, bar_labels=False,
        src_extra=SOURCE_8K + "偏离为实际收入除以指引单点或区间中值的自算值。" + caveat,
        extra_note=dev_note,
    )

    # ── Adjusted EBITDA margin, the percent era ──────────────────────────────
    margin_guide = record["guide_ebitda_margin_pct"]
    margin_actual = record["actual_ebitda_margin_pct"]
    margin_idx = [i for i, value in enumerate(margin_guide) if value is not None]
    margin_finished = [i for i in margin_idx if margin_actual[i] is not None]
    margin_gap = [margin_actual[i] - margin_guide[i] for i in margin_finished]
    margin_all_above = all(gap > 0 for gap in margin_gap)
    at_least = [i for i, q in enumerate(record["ebitda_qualifier"]) if q == "at least"]

    # The trailing cell here is not waiting on a filing when Broadcom retired the
    # measure with the release that would have settled it: the default
    # 「实际值待披露」 would point the reader at a disclosure that is never coming.
    retired = (stop is not None and margin_idx
               and margin_actual[margin_idx[-1]] is None
               and periods[margin_idx[-1]] == stop["first_missing_period"])
    margin_chart = delivery_band(
        "EX_EBITDA_POINT", "Adjusted EBITDA 利润率", take(labels, margin_idx),
        take(margin_guide, margin_idx), take(margin_guide, margin_idx),
        take(margin_actual, margin_idx),
        fmt="pct1", ylab="占收入 %", unit="%", venue="业绩发布", timing=timing,
        point=True, src_extra=SOURCE_8K + (
            "公司对 Adjusted EBITDA 的指引写法是「约为预计收入的 N%」，是单点、不是区间；"
            "实际值为该季 Adjusted EBITDA 除以该季收入的自算值，两项都取自同一份新闻稿。"
        ) + caveat,
        extra_note=(
            (f"{len(margin_finished)} 个已完结季<b>全部高于</b>指引的百分比，"
             if margin_all_above else
             f"{len(margin_finished)} 个已完结季里有 "
             f"{sum(1 for gap in margin_gap if gap > 0)} 季高于指引的百分比，")
            + f"幅度从 {min(margin_gap):+.2f}pp 到 {max(margin_gap):+.2f}pp，"
            f"平均 {statistics.fmean(margin_gap):+.2f}pp。"
            "注意 Adjusted EBITDA 是公司自定义口径（在 GAAP 净利上加回利息、税、折旧、"
            "无形摊销、股权激励、重组与收购相关费用），因此这里的每一对"
            "「指引 vs 实际」都必须在<b>当时那一套口径内部</b>比较，本图正是如此。"
            + (f"另有 {len(at_least)} 季公司的措辞是 <code>at least</code> 而不是 "
               "<code>approximately</code>——那一季严格说是下限而不是点，"
               "但仍按点画，因为它没有上界。" if at_least else "")
        ),
        **({"pending_label": "实际值不会再有（该指标已停止披露）"} if retired else {}),
    )
    one_sided = margin_all_above and never_below
    margin_dev = midpoint_deviation(
        "EX_EBITDA_DEV", "Adjusted EBITDA 利润率", periods, margin_guide, margin_guide,
        [margin_actual[i] if margin_guide[i] is not None else None
         for i in range(len(periods))],
        mode="pp", window=len(margin_finished), label=compact_period, bar_labels=False,
        src_extra=SOURCE_8K + "偏离为实际利润率减指引百分比的算术差。" + caveat,
        extra_note=(
            ("与收入那条一样是单向的"
             + ("，而且幅度更小" if max(margin_gap) < max(deviation) else "")
             + "：这条线上公司几乎从不给自己留出可见的余量。"
             "两条合起来说明的是同一件事——Broadcom 的指引是一条它确定能过的线，"
             "而不是一个居中的预测。")
            if one_sided else
            "与收入那条放在一起读：两条线都不是单向的，指引不再是一条它确定能过的线。"
        ),
    )

    # ── what the beat is made of ─────────────────────────────────────────────
    # Guiding a revenue level and an EBITDA margin implies an Adjusted EBITDA
    # dollar amount the company never prints, and the distance from what it
    # reported splits exactly two ways with no estimate:
    #     actual − implied = (Ra − Rg)·mg  +  Ra·(ma − mg)
    revenue_leg, margin_leg, leg_labels = [], [], []
    for i in margin_finished:
        guided_revenue = guide[i]
        guided_margin = margin_guide[i] / 100
        actual_revenue = actual[i]
        actual_margin = margin_actual[i] / 100
        revenue_leg.append((actual_revenue - guided_revenue) * guided_margin)
        margin_leg.append(actual_revenue * (actual_margin - guided_margin))
        leg_labels.append(compact_period(periods[i]))
    totals = [a + b for a, b in zip(revenue_leg, margin_leg)]
    margin_led = sum(1 for a, b in zip(revenue_leg, margin_leg) if b > a)
    negative_legs = sum(1 for a, b in zip(revenue_leg, margin_leg) if a < 0 or b < 0)
    legs_chart = {
        "ref": "EX_LEGS",
        "kind": "grouped_bars",
        "title": (
            f"把「超出自身指引」拆成两条腿：{len(totals)} 季里"
            + ("没有一条腿为负" if not negative_legs else f"有 {negative_legs} 季出现负的一条腿")
            + f"，利润率腿在 {margin_led} 季是更大的那半"
        ),
        "xlabels": leg_labels,
        "xrot": 90,
        "groups": [
            {"name": "收入腿（多做的收入 × 指引利润率）", "values": rounded(revenue_leg, 3), "color": "BLUE"},
            {"name": "利润率腿（实际收入 × 多出的利润率）", "values": rounded(margin_leg, 3), "color": "NAVY"},
        ],
        "bar_labels": False,
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$M",
        "note": (
            "公司同时指引收入水平与 Adjusted EBITDA 利润率，两者相乘隐含一个它从不印出来的"
            "Adjusted EBITDA 金额；实际值与它的差<b>恰好</b>等于这两条腿之和，"
            "是恒等式而不是估计（收入与利润率同时偏离时的交叉项按该式全部计入利润率腿，"
            "调换拆解顺序会把它移到收入腿，合计不变）。"
            "这里的答案与本站另外两家不同：Amazon 的超额几乎全在利润率腿，"
            "Synopsys 几乎全在收入腿，而 Broadcom 是"
            + ("<b>两条腿都在贡献</b>——" if 0 < margin_led < len(totals) else "只有一条腿在贡献——")
            + f"{len(totals)} 季里利润率腿更大的有 {margin_led} 季，收入腿更大的有 "
            f"{len(totals) - margin_led} 季。"
            f"最大的一季是 {leg_labels[totals.index(max(totals))]}，合计 "
            f"US${max(totals):,.0f}M。"
        ),
        "src_extra": SOURCE_8K + "两条腿均为按上式自算，可由指引兑现全表复算。" + caveat,
    }

    # ── the audit tables behind the record ──────────────────────────────────
    rows = []
    for i, period in enumerate(periods):
        band = (f"{lo[i]:,.0f}–{hi[i]:,.0f}" if forms[i] == "range" else f"{guide[i]:,.0f}（单点）")
        act_text = "—" if actual[i] is None else f"{actual[i]:,.0f}"
        dev_text = "—" if actual[i] is None else f"{(actual[i] / guide[i] - 1) * 100:+.2f}%"
        if actual[i] is None:
            verdict = "待披露"
        elif forms[i] == "range":
            verdict = ("区间内" if lo[i] <= actual[i] <= hi[i]
                       else ("高于上限" if actual[i] > hi[i] else "低于下限"))
        else:
            verdict = "高于" if actual[i] > guide[i] else ("低于" if actual[i] < guide[i] else "相同")
        margin_text = "—" if margin_guide[i] is None else f"{margin_guide[i]:.1f}%"
        margin_act = "—" if margin_actual[i] is None else f"{margin_actual[i]:.2f}%"
        rows.append([
            period, record["fiscal_labels"][i], record["guided_in_release"][i],
            f"{record['days_into_quarter_at_release'][i]}/{record['quarter_length_days'][i]} 天",
            band, act_text, dev_text, verdict, margin_text, margin_act,
        ])
    record_table = {
        "title": f"指引兑现全表（{len(periods)} 季）：区间时代、单点时代与两者的实际值",
        "headers": ["本站季度", "公司财季", "指引发布日", "发布时该季已过",
                    "收入指引 US$M", "实际收入 US$M", "偏离 D", "判定",
                    "EBITDA 利润率指引", "实际 D"],
        "rows": rows,
    }
    gap_rows = [
        [entry["released"], entry["fiscal_year_end"], f"{entry['revenue_usd_m']:,.0f}",
         "区间" if entry["revenue_form"] == "range" else "单点",
         "—" if entry["ebitda"] is None else
         (f"{entry['ebitda']:,.0f} US$M" if entry["ebitda_unit"] == "usd_m"
          else f"{entry['ebitda']:.0f}% of revenue")]
        for entry in staging["annual_only_guidance"]
    ]
    gap_table = {
        "title": f"只按财年给过、因而结算不了任何单季的 {len(gap_rows)} 份指引",
        "headers": ["发布日", "所指引财年结束日", "收入指引 US$M", "形式", "EBITDA 指引"],
        "rows": gap_rows,
    }
    return [range_chart, point_chart, dev_chart, margin_chart, margin_dev, legs_chart], \
           [record_table, gap_table]


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    fin = staging["financials_usd_m"]
    ai = staging["ai_semiconductor_disclosures"]
    ai_now = ai["actual_usd_bn"][ai["periods"].index(staging["periods"][-1])]
    return [f"Revenue ${fin['revenue'][-1] / 1000:.2f}B",
            f"AI 半导体 ${ai_now:.1f}B",
            f"non-GAAP 营业利润率 {fin['non_gaap_operating_income'][-1] / fin['revenue'][-1] * 100:.1f}%"]


# ── settling what the previous report left ──────────────────────────────────
# The first quarter this site has a local analysis for: the note dated
# 2026-03-25 covers Broadcom's FY2026 Q1, which is this page's Q4 2025. That
# quarter has no earlier report to settle. Every later quarter must stamp both
# settlement blocks or the build stops -- a page that quietly dropped last
# quarter's questions and thresholds would be the stale-prose failure again.
FIRST_REPORT_PERIOD = "Q4 2025"

COMPARE = {"≥": lambda value, line: value >= line, ">": lambda value, line: value > line,
           "≤": lambda value, line: value <= line, "<": lambda value, line: value < line}


@dataclass
class Reading:
    """One metric a threshold can be read against.

    A threshold entry in the series names its metric by key (`reads`); this is
    the only code a threshold needs. Which metric, which line, which side and
    which comparison are all data, so a quarter that carries this quarter's
    `next_kpi` forward into next quarter's `prior_kpi_settlement` edits the
    series and nothing here.
    """
    label: str
    unit: str
    current: float | None
    source: str
    xlabels: list[str] | None = None
    values: list[float | None] | None = None


def text_number(unit: str, value: float) -> str:
    """A reading as prose writes it: ``US$16.7B``, ``US$600M``, ``27%``."""
    if unit == "usd_m":
        if abs(value) >= 1000:
            return f"US${value / 1000:,.1f}B".replace(".0B", "B")
        return f"US${value:,.0f}M"
    if unit == "pct":
        return f"{value:.1f}%".replace(".0%", "%")
    return unit_text(unit, value)


def exact_number(unit: str, value: float) -> str:
    """A reading as a title or a table cell writes it: ``US$16,700M``, ``66.9%``."""
    if unit == "usd_m":
        return f"{'−' if value < 0 else ''}US${abs(value):,.0f}M"
    if unit == "pct":
        return f"{value:.1f}%"
    return unit_text(unit, value)


def readings(staging: dict) -> dict[str, Reading]:
    """Every metric on this page a threshold can be settled against."""
    periods, ends = staging["periods"], staging["period_ends"]
    long_labels = [compact_period(period) for period in periods]
    seg = staging["segments_usd_m"]
    capital = staging["capital_allocation_usd_m"]
    ai = staging["ai_semiconductor_disclosures"]
    notes = staging.get("ten_q_notes", {}).get("by_period_end", {})
    semi_gm = [None if cost is None or not sales else (sales - cost) / sales * 100
               for sales, cost in zip(seg["semiconductor_revenue"],
                                      seg["semiconductor_cost_of_revenue"])]
    first_gm = next(i for i, value in enumerate(semi_gm) if value is not None)
    ai_now = (ai["actual_usd_bn"][ai["periods"].index(periods[-1])]
              if periods[-1] in ai["periods"] else None)
    recon = staging["release_reconciliation_usd_m"]
    cash_tax_ratio = [None if paid is None or not booked else paid / booked * 100
                      for paid, booked in zip(recon["cash_paid_for_income_taxes"],
                                              recon["non_gaap_tax_provision"])]
    commitments = staging["purchase_commitments_usd_m"]
    next_two = [None if first is None or second is None else first + second
                for first, second in zip(commitments["due_within_one_year"],
                                         commitments["due_in_year_two"])]
    liabilities = [notes.get(end, {}).get("contract_liabilities_current_usd_m") for end in ends[-2:]]
    return {
        "ai_revenue": Reading(
            "AI 半导体收入", "usd_m", None if ai_now is None else ai_now * 1000,
            "业绩 8-K 新闻稿的 CEO 引语（精度 US$0.1B）",
            [compact_period(period) for period in ai["periods"]],
            [None if value is None else round(value * 1000, 6) for value in ai["actual_usd_bn"]]),
        "ai_next_guide": Reading(
            "下季 AI 收入指引", "usd_m", ai["next_quarter_guide_usd_bn"] * 1000,
            "本季业绩 8-K 新闻稿的 CEO 引语"),
        "semi_gross_margin": Reading(
            "半导体分部毛利率", "pct", semi_gm[-1],
            "10-Q / 10-K 分部附注的分部收入与分部成本（ASU 2023-07）",
            long_labels[first_gm:], rounded(semi_gm[first_gm:])),
        "software_revenue": Reading(
            "基础设施软件收入", "usd_m", seg["infrastructure_software_revenue"][-1],
            "业绩 8-K 分部收入表", long_labels, seg["infrastructure_software_revenue"]),
        "buyback": Reading(
            "季度回购", "usd_m", capital["share_repurchases"][-1], "现金流量表融资活动",
            long_labels, capital["share_repurchases"]),
        "cash": Reading(
            "期末现金", "usd_m", capital["cash_and_equivalents"][-1], "资产负债表",
            long_labels, capital["cash_and_equivalents"]),
        "backstop_max": Reading(
            "backstop 合计最大敞口", "usd_m", notes.get(ends[-1], {}).get("backstop_max_usd_m"),
            "10-Q 或有负债附注（全部 AI racks 部署之后的最大敞口，未折现）"),
        "ng_opex": Reading(
            "non-GAAP 营业费用", "usd_m", recon["non_gaap_operating_expenses"][-1],
            "各季业绩 8-K 对账表「Total operating expenses on non-GAAP basis」",
            long_labels, recon["non_gaap_operating_expenses"]),
        "cash_tax_ratio_ng": Reading(
            "现金纳税 ÷ non-GAAP 所得税", "pct", cash_tax_ratio[-1],
            "各季业绩 8-K 现金流量表的补充披露与对账表的税项段（自算）",
            long_labels, rounded(cash_tax_ratio)),
        "commitments_next_two": Reading(
            "采购承诺（下一与再下一财年两行合计）", "usd_m", next_two[-1],
            "10-Q / 10-K 承诺附注（XBRL 第一、第二个财年两行）", long_labels, next_two),
        "commitments_second_fy": Reading(
            "采购承诺（再下一财年一行）", "usd_m", commitments["due_in_year_two"][-1],
            "10-Q 承诺附注"),
        "contract_liabilities_qoq": Reading(
            "流动合同负债环比", "usd_m",
            None if None in liabilities else liabilities[1] - liabilities[0],
            "10-Q「其他流动负债」附注的合同负债，本季减上季"),
    }


def threshold_value(entry: dict, readers: dict[str, Reading],
                    release: str) -> tuple[float | None, str]:
    """(reading, where it comes from) for one threshold entry, or a named error.

    A known metric with no reading this quarter returns ``None``: the 10-Q that
    carries it can land a week after the release, and a threshold waiting on a
    filing is pending, not an error. An unknown metric key is an error. A
    reading only the call gives is written into the entry, so its source must
    name this quarter's call: a block carried from last quarter's `next_kpi`
    keeps last quarter's call reading until the roll re-reads it.
    """
    if "reads" in entry:
        if entry["reads"] not in readers:
            raise ValueError(f"threshold {entry.get('id')!r} reads {entry['reads']!r}, which "
                             "build/avgo.py `readings` does not know")
        reader = readers[entry["reads"]]
        return reader.current, reader.source
    if "value" not in entry or not entry.get("value_source"):
        raise ValueError(f"threshold {entry.get('id')!r} has neither `reads` nor a sourced `value`")
    if not entry["value_source"].startswith(release):
        raise ValueError(f"threshold {entry.get('id')!r} is read off a call, but its `value_source` "
                         f"does not start with this quarter's release date {release}: re-read it "
                         "from this quarter's call with the roll")
    return entry["value"], entry["value_source"]


def evaluate(entries: list[dict], readers: dict[str, Reading],
             release: str) -> tuple[list[dict], list[dict]]:
    """Each threshold with its reading, whether it fired, and its verdict.

    A gate (加仓 / 跟踪 / 上调 lines) fires when reached; a floor (减仓 /
    警示 lines) fires when breached. `direction` names the favourable side so
    the headroom bar reads positive when the reading is on it; an entry whose
    direction contradicts its own comparison stops the build instead of
    drawing a bar on the wrong side of zero. Returns ``(read, pending)``:
    entries whose metric has no reading yet are set aside, named, not dropped.
    """
    out, pending = [], []
    for entry in entries:
        value, source = threshold_value(entry, readers, release)
        if entry.get("kind") not in ("gate", "floor") or entry.get("op") not in COMPARE:
            raise ValueError(f"threshold {entry.get('id')!r}: kind must be gate or floor and op one of "
                             f"{sorted(COMPARE)}")
        if value is None:
            pending.append({**entry, "source": source})
            continue
        fired = COMPARE[entry["op"]](value, entry["threshold"])
        favourable = fired if entry["kind"] == "gate" else not fired
        room = headroom(entry["direction"], entry["threshold"], value)
        if (favourable and room < 0) or (not favourable and room > 0):
            raise ValueError(f"threshold {entry['id']!r}: direction {entry['direction']!r} puts the "
                             f"{'favourable' if favourable else 'unfavourable'} reading on the other side")
        verdict = ("达到" if fired else "未达") if entry["kind"] == "gate" else ("击穿" if fired else "守住")
        out.append({**entry, "reading": value, "source": source, "fired": fired,
                    "favourable": favourable, "verdict": verdict})
    return out, pending


def pending_words(pending: list[dict], form: str) -> str:
    """The thresholds still waiting on a filing, named rather than dropped."""
    if not pending:
        return ""
    return (f"另有{cn_count(len(pending))}条的读数要等本季的 {form}（"
            + "、".join(entry["metric"] for entry in pending) + "），申报后再算。")


def pending_lead(pending: list[dict], form: str) -> str:
    """A title's clause for thresholds counted but not yet measurable."""
    return f"{len(pending)} 条的读数要等本季 {form}；已有读数的 " if pending else ""


def base_name(metric: str) -> str:
    """``'季度回购（加仓线）'`` → ``'季度回购'``."""
    return metric.split("（", 1)[0]


def track_next(staging: dict, readers: dict[str, Reading]) -> tuple[list[dict], dict | None, dict]:
    """Section three: this report's section-8 thresholds against this quarter's readings.

    Rendered from the stamped `next_kpi` block with the same fields a settlement
    uses, so next quarter the block moves into `prior_kpi_settlement` unchanged.
    The bars compare this quarter's reading with next quarter's line: they say
    how far away the line is, not whether it was met.
    """
    period = staging["periods"][-1]
    form = filed_form(staging["fiscal_labels"][-1])
    kpi = stamped_block(staging, "next_kpi", period)
    if kpi is None:
        return [], None, {"count": 0, "pending": 0, "unquantified": [], "rows": 0}
    tracked, waiting = evaluate(kpi["quantified"], readers, staging["release_dates"][-1])
    total = len(tracked) + len(waiting)
    gates = [entry for entry in tracked if entry["kind"] == "gate"]
    floors = [entry for entry in tracked if entry["kind"] == "floor"]
    breached = [entry for entry in floors if entry["fired"]]
    missed = [entry for entry in gates if not entry["fired"]]
    unquantified = kpi.get("unquantified", [])
    call_sources = list(dict.fromkeys(entry["source"] for entry in tracked if "reads" not in entry))
    headroom_chart = headroom_exhibit(
        f"下季 {total} 条阈值：" + pending_lead(waiting, form)
        + f"{len(floors)} 条警戒线按本季读数"
        + ("全部守住" if not breached else f"已有 {len(breached)} 条越线")
        + f"；{len(gates)} 条上行线已达到 {len(gates) - len(missed)} 条"
        + (spaced("，没到的是", joined([spaced(base_name(entry["metric"]), "的" + entry["line"])
                                       for entry in missed])) if missed else ""),
        tracked, "reading",
        note=("余量拿本季读数对下季的线，只说明离线还有多远，不是结算；下一季用那一季的读数结算。"
              "阈值逐字取自本季本地分析稿第 8.2 节，一行里的每个数值阈值拆成一条：上行线（上调、加仓、跟踪一类）"
              "达到才触发，警戒线（警示、减仓一类）越线才触发。正值 = 落在有利一侧。"
              + (f"标「电话会」的读数只在业绩电话会上出现过（{'；'.join(call_sources)}）。" if call_sources else "")
              + pending_words(waiting, form)
              + (f"另有{cn_count(len(unquantified))}条没有数可画：" + "；".join(
                  f"{item['metric']}——{item['reason']}" for item in unquantified) + "。"
                 if unquantified else "")),
        src_extra=(f"阈值：{kpi['set_in']} 那份本地分析稿第 8.2 节，不是公司指引；"
                   "当前值：本季业绩 8-K、10-Q 与电话会，逐条出处见核对抽屉。"),
    )
    headroom_chart["positive_label"] = "有利一侧（上行线已达到 / 警戒线未越线）"
    headroom_chart["negative_label"] = "不利一侧（上行线未达到 / 警戒线已越线）"
    charts = [headroom_chart]
    grouped: dict[str, list[dict]] = {}
    for entry in tracked:
        if "reads" in entry and readers[entry["reads"]].xlabels:
            grouped.setdefault(entry["reads"], []).append(entry)
    for key, entries in grouped.items():
        reader = readers[key]
        charts.append(threshold_lines(
            reader,
            [(f"下季{entry['line']} {exact_number(entry['unit'], entry['threshold'])}",
              entry["threshold"]) for entry in entries],
            title=(f"{reader.label}：下季阈值 "
                   + " / ".join(f"{entry['op']} {exact_number(entry['unit'], entry['threshold'])}"
                                for entry in entries)
                   + f"，当前 {exact_number(reader.unit, reader.current)}"),
            note="；".join(f"{entry['line']}：{entry['rule']}" for entry in entries) + "。",
            src_extra=f"阈值：本季本地分析稿第 8.2 节，不是公司指引；实际值：{reader.source}。",
        ))
    table = {
        "title": f"下季 {total} 条阈值（原始单位）与没有数可画的{cn_count(len(unquantified))}条",
        "headers": ["行", "指标", "线", "阈值", "本季读数", "读数出处", "余量 D", "动作"],
        "rows": [[entry["row"], entry["metric"], entry["line"],
                  f"{entry['op']} {exact_number(entry['unit'], entry['threshold'])}",
                  exact_number(entry["unit"], entry["reading"]), entry["source"],
                  f"{headroom(entry['direction'], entry['threshold'], entry['reading']):+.1f}%",
                  entry["action"]] for entry in tracked]
                + [[entry["row"], entry["metric"], entry["line"],
                    f"{entry['op']} {exact_number(entry['unit'], entry['threshold'])}",
                    "待申报", entry["source"], "—", entry["action"]] for entry in waiting]
                + [[item["row"], item["metric"], "—", "—", "—", item["reason"], "—", "—"]
                   for item in unquantified],
    }
    rows = {entry["row"].split("(")[0] for entry in tracked + waiting}
    rows |= {item["row"] for item in unquantified if item["row"].startswith("K")}
    return charts, table, {"count": total, "pending": len(waiting), "unquantified": unquantified,
                           "set_in": kpi["set_in"], "rows": len(rows)}


def threshold_lines(reader: Reading, lines: list[tuple[str, float]], *, title: str,
                    note: str, src_extra: str) -> dict:
    """One metric's series against every threshold that reads it."""
    fmt = "f0c" if reader.unit == "usd_m" else "pct1"
    chart = threshold_exhibit(
        title, reader.xlabels, reader.values, lines[0][1], fmt=fmt,
        ylab="US$M" if reader.unit == "usd_m" else "%", actual_name=reader.label,
        threshold_name=lines[0][0], note=note, src_extra=src_extra)
    for (name, value), color in zip(lines[1:], ("GOLD", "GRAY", "MBLUE")):
        chart["series"].append({"name": name, "values": [value] * len(reader.xlabels),
                                "color": color})
    return chart


def settle_prior(staging: dict, readers: dict[str, Reading],
                 story_values: dict[str, str]) -> tuple[list[dict], list[dict], dict]:
    """Section one's lead: last quarter's follow-ups and section-8 thresholds, settled.

    Returns ``(charts, tables, facts)``. Everything is rendered from the two
    stamped blocks and the reading registry: the follow-up labels, how a
    question was split, each threshold's line, side and comparison are data.
    The first-report quarter has nothing before it and says so; any later
    quarter without both blocks stops the build.
    """
    period = staging["periods"][-1]
    closure = stamped_block(staging, "followup_closure", period)
    prior = stamped_block(staging, "prior_kpi_settlement", period)
    if period == FIRST_REPORT_PERIOD:
        if closure is not None or prior is not None:
            raise ValueError(f"no local AVGO report precedes {FIRST_REPORT_PERIOD}: there is "
                             "nothing for `followup_closure` / `prior_kpi_settlement` to settle")
        return [], [], {"first": True}
    if closure is None or prior is None:
        raise ValueError(f"the report before {period} left follow-ups and section-8 thresholds: "
                         f"stamp `followup_closure` and `prior_kpi_settlement` for {period}")

    form = filed_form(staging["fiscal_labels"][-1])
    values = dict(story_values)
    settled, waiting = evaluate(prior["quantified"], readers, staging["release_dates"][-1])
    for entry in settled:
        entry["actual"] = entry["reading"]
        values[f"prior:{entry['id']}"] = text_number(entry["unit"], entry["reading"])

    # (a) the follow-up questions, judged part by part the way the report split them
    labels = closure["labels"]
    parts = [part for item in closure["items"] for part in item["parts"]]
    unknown = sorted({part["verdict"] for part in parts} - set(labels))
    if unknown:
        raise ValueError(f"followup_closure verdicts {unknown} are not among its labels {labels}")
    counts = [sum(1 for part in parts if part["verdict"] == label) for label in labels]
    split = len(parts) != len(closure["items"])
    unit = "项" if split else "条"
    closure_chart = {
        "kind": "bars_labeled",
        "title": (f"上季 {len(closure['items'])} 条待验证问题"
                  + (f"（按报告的分项是 {len(parts)} 项判定）" if split else "") + "："
                  + "、".join(f"{count} {unit}{label}" for label, count in zip(labels, counts) if count)),
        "xlabels": labels,
        "values": counts,
        "legend": "判定项数" if split else "问题条数",
        "fmt": "f0", "yfmt": "f0", "label_fmt": "f0", "ylab": unit,
        "note": (fill_story(closure["diagnosis"], values) + "。"
                 + (fill_story(closure["after_filing"], values) if closure.get("after_filing") else "")
                 + "逐题的问题、判定与读数见核对抽屉。"),
        "src_extra": ("问题：上季本地分析稿文末的 Follow-up Questions（中文转述）；判定：本季本地分析稿第 0 节"
                      "「验证结果」一栏，只照录、不改判。"),
    }
    closure_table = {
        "title": f"上季 {len(closure['items'])} 条待验证问题：本季报告第 0 节的逐项判定",
        "headers": ["#", "上季问题", "判定（按报告的分项）", "本季读数"],
        "rows": [[str(item["n"]), fill_story(item["question"], values),
                  "；".join(f"{part['part']}：{part['verdict']}" for part in item["parts"]),
                  fill_story(item["reading"], values)] for item in closure["items"]],
    }

    # (b) every numeric threshold of the previous report's section 8
    gates = [entry for entry in settled if entry["kind"] == "gate"]
    floors = [entry for entry in settled if entry["kind"] == "floor"]
    call_sources = list(dict.fromkeys(entry["source"] for entry in settled if "reads" not in entry))
    # What cannot be settled is said from the settlement's side. A block moved
    # over from last quarter's `next_kpi` still carries that section's
    # `unquantified` rows, whose reasons were written about the quarter ahead
    # (「下一次业绩发布才有这个数」); printed here they would be false.
    if "unquantified" in prior:
        raise ValueError("series block `prior_kpi_settlement` still carries `unquantified` from last "
                         "quarter's `next_kpi`: rewrite those rows as `unsettled`, each with why it "
                         "cannot be settled this quarter")
    unsettled = prior.get("unsettled", [])
    total = len(settled) + len(waiting)
    headroom_chart = headroom_exhibit(
        f"上季 {total} 条量化阈值：" + pending_lead(waiting, form)
        + f"{len(gates)} 条上行线达到 "
        f"{sum(entry['fired'] for entry in gates)} 条，{len(floors)} 条警戒线击穿 "
        f"{sum(entry['fired'] for entry in floors)} 条",
        settled, "actual",
        note=("阈值逐字取自上季本地分析稿第 8 节，一行里的每个数值阈值拆成一条；上行线（加仓、跟踪一类）"
              "达到才触发，警戒线（减仓、警示一类）击穿才触发。正值 = 落在有利一侧。"
              + (f"标「电话会」的读数只在业绩电话会上出现过、不在任何申报里（{'；'.join(call_sources)}）。"
                 if call_sources else "")
              + prior.get("report_verdicts", "")
              + pending_words(waiting, form)
              + (f"另有{cn_count(len(unsettled))}条结算不了：" + "；".join(
                  f"{item['metric']}——{item['reason']}" for item in unsettled) + "。" if unsettled else "")),
        src_extra=(f"阈值：{prior['set_in']} 那份本地分析稿第 8 节；读数：本季业绩 8-K、10-Q 与电话会，"
                   "逐条出处见核对抽屉。"),
    )
    headroom_chart["positive_label"] = "有利一侧（上行线达到 / 警戒线守住）"
    headroom_chart["negative_label"] = "不利一侧（上行线未达 / 警戒线击穿）"
    charts = [closure_chart, headroom_chart]
    grouped: dict[str, list[dict]] = {}
    for entry in settled:
        if "reads" in entry and readers[entry["reads"]].xlabels:
            grouped.setdefault(entry["reads"], []).append(entry)
    for key, entries in grouped.items():
        reader = readers[key]
        charts.append(threshold_lines(
            reader,
            [(f"上季{entry['line']} {exact_number(entry['unit'], entry['threshold'])}",
              entry["threshold"]) for entry in entries],
            title=(f"{reader.label} {exact_number(reader.unit, reader.current)}："
                   + "，".join(f"{entry['verdict']}上季{entry['line']} "
                              f"{exact_number(entry['unit'], entry['threshold'])}" for entry in entries)),
            note="；".join(f"{entry['line']}的原文条件：{entry['rule']}" for entry in entries) + "。",
            src_extra=f"阈值：上季本地分析稿第 8 节；实际值：{reader.source}。",
        ))
    prior_table = {
        "title": f"上季 {total} 条量化阈值的结算（原始单位）",
        "headers": ["行", "指标", "线", "阈值", "本季读数", "读数出处", "余量 D", "判定"],
        "rows": [[entry["row"], entry["metric"], entry["line"],
                  f"{entry['op']} {exact_number(entry['unit'], entry['threshold'])}",
                  exact_number(entry["unit"], entry["actual"]), entry["source"],
                  f"{headroom(entry['direction'], entry['threshold'], entry['actual']):+.1f}%",
                  entry["verdict"]] for entry in settled]
                + [[entry["row"], entry["metric"], entry["line"],
                    f"{entry['op']} {exact_number(entry['unit'], entry['threshold'])}",
                    "待申报", entry["source"], "—", "待申报"] for entry in waiting]
                + [[item["row"], item["metric"], "—", "—", "—", item["reason"], "—", "结算不了"]
                   for item in unsettled],
    }
    return charts, [closure_table, prior_table], {
        "first": False, "questions": len(closure["items"]), "thresholds": total,
        "pending": len(waiting), "set_in": prior["set_in"]}


def current_guidance(staging: dict) -> dict:
    """The outlook the page's own release gave, or a stamp error.

    The block names the release it came from, which is the page's quarter's
    release date when it is current; last quarter's outlook under this quarter's
    label is the stale-prose failure `stamped_block` guards everywhere else.
    """
    releases = staging["release_dates"]
    guidance = staging["guidance"]["next_quarter"]
    if guidance["released"] != releases[-1]:
        raise ValueError(f"series block `guidance.next_quarter` is stamped with the "
                         f"{guidance['released']} release, but the series ends on the "
                         f"{releases[-1]} one: update it with the roll")
    if "formal_qualifier" not in guidance:
        raise ValueError("series block `guidance.next_quarter` has no `formal_qualifier`: record "
                         "the word the Business Outlook block puts before its guides "
                         "(\"approximately\"), or null if it prints none")
    ai = staging["ai_semiconductor_disclosures"]
    if ai["next_quarter_guided_in_release"] != releases[-1]:
        raise ValueError(f"series block `ai_semiconductor_disclosures` next-quarter guide is "
                         f"stamped with the {ai['next_quarter_guided_in_release']} release, "
                         f"but the series ends on the {releases[-1]} one: update it with the roll")
    return guidance


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    fiscal = staging["fiscal_labels"]
    ends = staging["period_ends"]
    releases = staging["release_dates"]
    last = len(periods) - 1
    latest = latest_block(staging, period=periods[-1], period_end=ends[-1],
                          release_date=releases[-1])
    financials = staging["financials_usd_m"]
    segments = staging["segments_usd_m"]
    cash = staging["cash_flow_usd_m"]
    capital = staging["capital_allocation_usd_m"]
    working = staging["working_capital_usd_m"]
    commitments = staging["purchase_commitments_usd_m"]
    guidance = current_guidance(staging)
    # Next quarter's guides that management gave only on the call (company
    # words, never filed figures); absent in a quarter without such a block.
    call = guidance.get("by_line_call")
    ai = staging["ai_semiconductor_disclosures"]
    record = staging["quarterly_guidance_history"]
    ngm_guide = staging["non_gaap_operating_margin_guidance"]
    stop = staging.get("adjusted_ebitda_disclosure_stop")
    story = stamped_block(staging, "capital_return_story", periods[-1])
    release_source = next((item for item in staging["sources"]
                           if item["label"].startswith(f"{fiscal[-1]} 业绩新闻稿")), None)
    if release_source is None:
        raise ValueError(f"series `sources` has no entry for the {fiscal[-1]} release: "
                         "add it with the roll")
    # The note below states how many guide/actual pairs exist and how they
    # compare. Both moved when the series was extended back to Q1 2024, and the
    # comparison was wrong even before that: Q1 2025 guided "over $4.4 billion"
    # and reported 4.4, which meets the floor rather than beating it.
    ai_pairs = [(g, a) for g, a in zip(ai["guided_usd_bn"], ai["actual_usd_bn"])
                if g is not None and a is not None]

    revenue = financials["revenue"]
    gaap_oi = financials["gaap_operating_income"]
    ng_oi = financials["non_gaap_operating_income"]
    ebitda = financials["adjusted_ebitda"]
    semi_rev = segments["semiconductor_revenue"]
    isg_rev = segments["infrastructure_software_revenue"]
    ipl_rev = segments["ip_licensing_revenue"]
    semi_oi = segments["semiconductor_operating_income"]
    isg_oi = segments["infrastructure_software_operating_income"]
    ipl_oi = segments["ip_licensing_operating_income"]
    ocf = cash["operating_cash_flow"]
    capex = cash["capital_expenditures"]
    rnd = cash["research_and_development"]
    buyback = capital["share_repurchases"]
    dividends = capital["common_dividends"]
    cash_balance = capital["cash_and_equivalents"]
    debt = capital["total_debt"]

    # Segment operating profit comes from the 10-Q segment note, which lands days
    # after the earnings 8-K. Sentences about the split anchor here, not on [-1].
    seg_last = max(i for i, v in enumerate(semi_oi) if v is not None)
    notes_pending = seg_last < last
    form_now = filed_form(fiscal[-1])
    seg_rows = [i for i in range(len(periods))
                if semi_oi[i] is not None and isg_oi[i] is not None]
    identity_holds = all(
        abs(semi_oi[i] + isg_oi[i] + (ipl_oi[i] or 0.0) - ng_oi[i]) <= 0.5 for i in seg_rows)
    # How many days after its release last year's same quarter reached EDGAR.
    reports = {row["period_end"]: row
               for row in staging.get("periodic_reports_filed", {}).get("reports", [])}
    year_ago = last - 4
    lag_text = ""
    if year_ago >= 0 and ends[year_ago] in reports:
        lag = days_between(releases[year_ago], reports[ends[year_ago]]["filed"])
        lag_text = f"（去年同季是发布后第 {lag} 天）"

    gaap_margin = ratio(gaap_oi, revenue)
    ng_margin = ratio(ng_oi, revenue)
    ebitda_margin = ratio(ebitda, revenue)
    fcf = [o - c for o, c in zip(ocf, capex)]
    fcf_margin = ratio(fcf, revenue)
    ocf_margin = ratio(ocf, revenue)
    capex_intensity = ratio(capex, revenue)
    rnd_intensity = ratio(rnd, revenue)
    semi_share = ratio(semi_rev, revenue)
    semi_margin = ratio(semi_oi, semi_rev)
    isg_margin = ratio(isg_oi, isg_rev)
    net_debt = [d - c for d, c in zip(debt, cash_balance)]
    yoy = [None if index < 4 else pct_change(revenue[index], revenue[index - 4])
           for index in range(len(revenue))]

    tail = slice(len(periods) - WINDOW, len(periods))
    labels = [compact_period(period) for period in periods[tail]]
    long_labels = [compact_period(period) for period in periods]
    vmware = periods.index(VMWARE_FIRST_PERIOD)

    source = (
        f'Source: <a href="{release_source["url"]}" rel="noopener">Broadcom {fiscal[-1]} '
        f'业绩新闻稿（8-K EX-99.1）</a>与截至 {ends[seg_last]} 的 {filed_form(fiscal[seg_last])}'
        + (f'（本季 {form_now} 尚未申报）。' if notes_pending else '。')
    )

    # ── section one ──────────────────────────────────────────────────────────
    # (a)+(b): what last quarter's report left, settled from the two stamped
    # blocks. Every number the blocks' sentences name is computed here.
    readers = readings(staging)
    notes_by_end = staging.get("ten_q_notes", {}).get("by_period_end", {})
    recon = staging["release_reconciliation_usd_m"]
    ai_at = ai["periods"].index(periods[-1]) if periods[-1] in ai["periods"] else None
    # Only readings that exist this quarter become placeholders: a block that
    # names one still waiting on the 10-Q stops the build in `fill_story`
    # instead of printing a stale or empty number.
    story_values = {
        "ai_next": text_number("usd_m", readers["ai_next_guide"].current),
        "buyback_now": text_number("usd_m", buyback[-1]),
        "buyback_prior": text_number("usd_m", buyback[-2]),
    }
    if readers["ai_revenue"].current is not None:
        story_values["ai_now"] = text_number("usd_m", readers["ai_revenue"].current)
    if readers["semi_gross_margin"].current is not None:
        story_values["semi_gm"] = f"{readers['semi_gross_margin'].current:.2f}%"
    if recon["non_gaap_gross_margin"][-1] is not None:
        story_values["ng_gm"] = f"{recon['non_gaap_gross_margin'][-1] / revenue[-1] * 100:.2f}%"
    if commitments["total"][-1] is not None:
        story_values["commit_now"] = text_number("usd_m", commitments["total"][-1])
    if commitments["total"][-2] is not None:
        story_values["commit_prior"] = text_number("usd_m", commitments["total"][-2])
    for name, end in (("backstop_now", ends[-1]), ("backstop_prior", ends[-2])):
        if notes_by_end.get(end, {}).get("backstop_max_usd_m") is not None:
            story_values[name] = text_number("usd_m", notes_by_end[end]["backstop_max_usd_m"])
    if ends[-1] in reports:
        story_values["tenq_filed"] = reports[ends[-1]]["filed"]
    prior_charts, prior_tables, prior_facts = settle_prior(staging, readers, story_values)

    at = record["periods"].index(periods[-1])
    # The band this quarter's beat is measured against is recomputed, so the
    # sentence cannot quietly become false the next time a quarter lands outside
    # the old range.
    deviations = revenue_deviation(record)
    dev_band = [value for _, value in deviations]
    others = [value for index, value in deviations if index != at]
    never_below = all(value >= 0 for value in dev_band)
    finished_count = len(dev_band)
    median_days, quarter_days = release_timing(record)

    # The second guided leg follows the measure the company itself moved to.
    # Broadcom stopped printing Adjusted EBITDA with the 2026-09-02 release, so
    # the guide it had given for that quarter can never be settled (see
    # `adjusted_ebitda_disclosure_stop`); the non-GAAP operating margin guide is
    # the one that did settle. Before that release the leg was EBITDA margin.
    second = None
    if ends[-1] in ngm_guide["period_ends"]:
        k = ngm_guide["period_ends"].index(ends[-1])
        if ngm_guide["actual_pct"][k] is not None:
            second = ("non-GAAP 营业利润率", ngm_guide["guide_pct"][k], ngm_guide["actual_pct"][k])
    if (second is None and record["guide_ebitda_margin_pct"][at] is not None
            and record["actual_ebitda_margin_pct"][at] is not None):
        second = ("Adjusted EBITDA 利润率", record["guide_ebitda_margin_pct"][at],
                  record["actual_ebitda_margin_pct"][at])
    revenue_beat = pct_change(revenue[-1], record["guide_revenue_usd_m"][at])
    # Only what the company guided is settled here. Three quarter-on-quarter
    # bars used to share this axis (segment revenues, free-cash-flow margin);
    # they settle nothing, and each of them is drawn where it belongs.
    delivery = [("收入", revenue_beat)]
    if second is not None:
        delivery.append((second[0], second[2] - second[1]))
    guided = len(delivery)
    all_cleared = all(value > 0 for _, value in delivery[:guided])
    small = revenue_beat < 2 and (second is None or second[2] - second[1] < 1)
    if all_cleared:
        verdict = (f"本季{cn_count(guided)}条指引都过了" if guided > 1 else "本季收入指引过了")
        verdict += ("，但都只多出一点点" if guided > 1 else "，但只多出一点点") if small else ""
    else:
        verdict = "本季" + "、".join(
            f"{name}{'过了' if value > 0 else '没过'}指引" for name, value in delivery[:guided])
    beat_words = "、".join(
        f"{name} {signed(value, 2, '%' if name == '收入' else 'pp')}"
        for name, value in delivery[:guided])
    if 0 < revenue_beat and others and min(others) <= revenue_beat <= max(others):
        beat_note = (f"收入超出指引 {revenue_beat:+.2f}%——这个幅度落在 {len(dev_band)} 季 "
                     f"{min(dev_band):+.2f}% 到 {max(dev_band):+.2f}% 的常态带里，"
                     "属于「照例过线」而不是意外。")
    elif revenue_beat > 0:
        beat_note = (f"收入超出指引 {revenue_beat:+.2f}%——落在此前 {len(others)} 季 "
                     f"{min(others):+.2f}% 到 {max(others):+.2f}% 的常态带之外。")
    else:
        beat_note = (f"收入较指引 {revenue_beat:+.2f}%——此前 {len(others)} 季的偏离都在 "
                     f"{min(others):+.2f}% 到 {max(others):+.2f}% 之间。")
    switched = (stop is not None and stop["first_missing_period"] == periods[-1]
                and second is not None and second[0] == "non-GAAP 营业利润率"
                and record["guide_ebitda_margin_pct"][at] is not None)
    delivery_chart = {
        "kind": "diverging_bars",
        "title": verdict + "：" + beat_words,
        "xlabels": [metric for metric, _ in delivery],
        "values": [round(value, 2) for _, value in delivery],
        "legend": "本季表现",
        "positive_label": "优于指引",
        "negative_label": "逊于指引",
        "fmt": "f1", "yfmt": "f1", "label_fmt": "f1",
        "ylab": "% 或 pp", "zero_line": True,
        "note": (
            (f"{cn_count(guided)}条都是" if guided > 1 else "这一条是")
            + "与公司上季在新闻稿里给这一季的正式指引比较（"
            + "、".join([f"收入指引 US${record['guide_revenue_usd_m'][at]:,.0f}M"]
                       + ([f"{second[0]} {second[1]:.0f}%"] if second else []))
            + "）；收入是百分比、利润率是百分点，放在同一根轴上只是为了一次看完。"
            + beat_note
            + ("<b>第二条腿这一季换了指标</b>：上一份新闻稿同时给了 Adjusted EBITDA 与 "
               "non-GAAP 营业利润率两条指引，本季的新闻稿里 Adjusted EBITDA 连同实际值一起消失了，"
               "那条指引因此无法结算——不是没达标，是用来结算它的数不再印了。" if switched else "")
        ),
        "src_extra": SOURCE_8K,
    }

    # The same guidance, split the way the company gave it on the call: only
    # the total and the AI figure reach the 8-K, the other lines exist only as
    # what management said, so the block that carries them says so. The split
    # is an identity -- the legs add to the total miss or beat exactly. The
    # non-AI guide is therefore the semiconductor guide less the AI guide; when
    # the figure management said aloud differs (it did for FY2026 Q4: 26.1 −
    # 21.7 = 4.4 against a spoken 4.3), the note names both. A semiconductor
    # and software guide that do not add to the guided total stop the build.
    by_line = stamped_block(staging, "guidance_by_line", periods[-1])
    legs_chart = None
    legs_summary = None
    if by_line is not None and ai_at is not None and ai["guided_usd_bn"][ai_at] is not None:
        ai_guide = ai["guided_usd_bn"][ai_at] * 1000
        ai_actual = ai["actual_usd_bn"][ai_at] * 1000
        semi_guide = by_line["semiconductor_usd_m"]
        if abs(semi_guide + by_line["infrastructure_software_usd_m"]
               - record["guide_revenue_usd_m"][at]) > 0.5:
            raise ValueError("series block `guidance_by_line` does not add up to the guided total")
        non_ai_guide = semi_guide - ai_guide
        spoken = by_line.get("non_ai_semiconductor_usd_m")
        spoken_differs = spoken is not None and abs(spoken - non_ai_guide) > 0.5
        legs = [("AI 半导体", ai_actual - ai_guide),
                ("非 AI 半导体", semi_rev[-1] - ai_actual - non_ai_guide),
                ("基础设施软件", isg_rev[-1] - by_line["infrastructure_software_usd_m"])]
        total_gap = revenue[-1] - record["guide_revenue_usd_m"][at]
        up = [(name, value) for name, value in legs if value > 0]
        down = [(name, value) for name, value in legs if value < 0]
        legs_summary = (up, down, total_gap)
        legs_chart = {
            "kind": "diverging_bars",
            "title": (
                f"收入比指引{'多' if total_gap >= 0 else '少'} US${abs(total_gap):,.0f}M，按业务线拆开："
                + "、".join(f"{name}{'多出' if value > 0 else '少了'} US${abs(value):,.0f}M"
                           for name, value in up)
                + ("，" if up and down else "")
                + (f"{joined([name for name, _ in down])}合计少了 "
                   f"US${abs(sum(value for _, value in down)):,.0f}M" if len(down) > 1 else
                   "".join(f"{name}少了 US${abs(value):,.0f}M" for name, value in down))
            ),
            "xlabels": [name for name, _ in legs] + ["合计"],
            "values": [round(value, 1) for _, value in legs] + [round(total_gap, 1)],
            "legend": "实际 − 上季指引",
            "positive_label": "高于指引",
            "negative_label": "低于指引",
            "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
            "ylab": "US$M", "zero_line": True,
            "note": (
                f"分业务的指引出自 {by_line['given_in']}：半导体 US${semi_guide:,.0f}M（其中 AI "
                f"US${ai_guide:,.0f}M，非 AI 取两者之差 US${non_ai_guide:,.0f}M）、软件 "
                f"US${by_line['infrastructure_software_usd_m']:,.0f}M；只有总收入与 AI 写进了 8-K 新闻稿，"
                "其余是电话会上的公司口径。"
                + (f"电话会上口头说的非 AI 是 US${spoken:,.0f}M，与半导体减 AI 差 US${abs(spoken - non_ai_guide):,.0f}M，"
                   "本页按相减值算，三条腿才能加回总指引。" if spoken_differs else "")
                + "三条腿相加恰好等于收入对总指引的偏离，没有残差。"
                f"非 AI 的实际值 = 半导体分部收入 US${semi_rev[-1]:,.0f}M 减去 AI 引语 US${ai_actual:,.0f}M，"
                "而 AI 引语只精确到 US$0.1B，所以非 AI 那条腿带 ±US$50M 的舍入。"
                + ("<b>这一季的超额只落在 AI 一格</b>，另外两格都在指引之下。"
                   if len(up) == 1 and up[0][0] == "AI 半导体" and len(down) == 2 else "")
            ),
            "src_extra": ("实际值：本季业绩 8-K 的分部收入表与 CEO 引语；指引：上季 8-K（总收入、AI）"
                          "与上季业绩电话会（半导体、非 AI、软件）。三条腿均为自算。"),
        }

    delivery_charts, delivery_tables = guidance_delivery_charts(staging)
    settled_charts = (prior_charts + [delivery_chart]
                      + ([legs_chart] if legs_chart else []) + delivery_charts)

    # ── section two ──────────────────────────────────────────────────────────
    semi_yoy = pct_change(semi_rev[-1], semi_rev[-5])
    isg_yoy = pct_change(isg_rev[-1], isg_rev[-5])
    if semi_yoy > 0 and isg_yoy > 0:
        fast, slow = max(semi_yoy, isg_yoy), min(semi_yoy, isg_yoy)
        leader = "半导体" if semi_yoy >= isg_yoy else "软件"
        trailer = "软件" if semi_yoy >= isg_yoy else "半导体"
        gap_words = ("同一家公司里两条增速差着一个数量级" if fast >= 10 * slow
                     else f"同一家公司里{leader}的增速是{trailer}的 {fast / slow:.1f} 倍")
    else:
        gap_words = "同一家公司里两条线一涨一跌" if semi_yoy * isg_yoy < 0 else "两条线同比都在收缩"
    revenue_chart = {
        "ref": "EX_REVENUE",
        "kind": "gs_bar",
        "title": (
            f"收入 US${revenue[-1]:,.0f}M、同比 {signed(yoy[-1])}，"
            f"半导体占比{moved(semi_share[-1], semi_share[-2])} {semi_share[-1]:.0f}%"
        ),
        "xlabels": labels,
        "values": revenue[tail],
        "legend": "季度收入",
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M", "ylab2": "同比增速",
        "yoy": {"name": "收入 YoY (RHS)", "values": rounded(yoy[tail]), "color": "GREEN", "yfmt": "pct0"},
        "note": (
            f"环比 {signed(pct_change(revenue[-1], revenue[-2]), 1)}。"
            f"半导体分部收入同比 {signed(semi_yoy)}，"
            f"基础设施软件同比 {signed(isg_yoy)}——"
            f"{gap_words}，这正是下一张图要拆的东西。"
        ),
        "src_extra": "收入与分部收入取自各季业绩 8-K；与 XBRL companyfacts 逐季一致。",
    }

    after_vmware = [semi_share[i] for i in range(vmware, len(periods)) if semi_share[i] is not None]
    window_share = [value for value in semi_share[tail] if value is not None]
    mix_chart = {
        "ref": "EX_MIX",
        "kind": "grouped_bars",
        "title": (
            f"两个引擎：半导体 US${semi_rev[-1]:,.0f}M、软件 US${isg_rev[-1]:,.0f}M，"
            f"半导体占比从 {semi_share[-WINDOW]:.0f}% "
            f"{moved(semi_share[-1], semi_share[-WINDOW], up='回到')} {semi_share[-1]:.0f}%"
        ),
        "xlabels": labels,
        "groups": [
            {"name": "半导体解决方案", "values": semi_rev[tail], "color": "NAVY"},
            {"name": "基础设施软件", "values": isg_rev[tail], "color": "BLUE"},
        ],
        "bar_labels": False,
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c", "ylab": "US$M",
        "note": (
            f"VMware 并入后软件一度把半导体的占比压到{cn_count(math.ceil(min(after_vmware) / 10))}成以下；"
            + ("AI 放量把它推了回去，" if semi_share[-1] > min(after_vmware) else "")
            + f"本季 {semi_share[-1]:.1f}%，"
            + (f"是{cn_count(WINDOW)}季里最高的一季。" if semi_share[-1] == max(window_share)
               else f"{cn_count(WINDOW)}季里最高是 {max(window_share):.1f}%。")
            + "两条线的利润结构完全不同，见 Exhibit {EX_SEG_MARGIN}。"
        ),
        "src_extra": "分部收入为公司申报的两个报告分部，取自各季业绩 8-K 与 10-Q 分部附注（两处一致）。",
    }

    ai_labels = [compact_period(period) for period in ai["periods"]]
    quote = guidance.get("ai_semiconductor_revenue_quote")
    formal = ([guidance["revenue_usd_bn"]]
              + [value for value in (guidance["non_gaap_operating_margin_pct"],
                                     guidance["adjusted_ebitda_margin_pct"]) if value is not None])
    unqualified = quote is not None and "approximately" not in quote
    floors = [i for i, floor in enumerate(ai["actual_is_floor"]) if floor]
    ai_chart = {
        "ref": "EX_AI",
        "kind": "grouped_bars",
        "title": (
            f"AI 半导体收入：公司口头指引与随后报出的实际值，"
            f"下季的口头目标是 US${ai['next_quarter_guide_usd_bn']:.1f}B"
        ),
        "xlabels": ai_labels,
        "groups": [
            {"name": "上一季给出的口头指引", "values": ai["guided_usd_bn"], "color": "GRAY"},
            {"name": "随后报出的实际值", "values": ai["actual_usd_bn"], "color": "NAVY"},
        ],
        "bar_labels": True,
        "fmt": "usd1", "yfmt": "usd1", "label_fmt": "usd1", "ylab": "US$B",
        "note": (
            "<b>这张图的口径与第一节那几张不同，不要放在一起读。</b>"
            "AI 半导体收入<b>不是</b>公司的申报分部，这些数字出自业绩新闻稿里的 CEO 引语，"
            f"精度只有 US$0.1B；下季的 US${ai['next_quarter_guide_usd_bn']:.1f}B 同样出自引语，"
            "不在正式的 Business Outlook 区块内"
            + (("，而且原文<b>不带</b> approximately"
                + (f"——同一份新闻稿里，{cn_count(len(formal))}条正式指引都带"
                   if guidance["formal_qualifier"] == "approximately" else ""))
               if unqualified else "")
            + "。"
            + "".join(f"{ai['periods'][i]} 一季公司的原话是「over ${ai['actual_usd_bn'][i]:.1f} billion」，"
                      "是下限不是点值；" for i in floors)
            + "Q3 2025 一季新闻稿只给了同比增速、没有给水平值，因此留空——"
            "这个洞是披露本身的洞，不是取数失败。"
            f"<b>序列的起点是 {ai['periods'][0]}</b>：2024-06-12 那份发布的 CEO 引语"
            "「Revenue from our AI products was a record $3.1 billion during the quarter」"
            "是公司第一次给出季度级的 AI 收入金额。"
            "紧接着的两季（Q2 2024、Q3 2024）新闻稿<b>只给全年数</b>"
            "（指引 US$12B、实际 US$12.2B），没有季度水平值，"
            "所以那两格与 Q3 2025 一样是披露的洞，只是原因不同。"
            f"就已有的 {len(ai_pairs)} 对而言，"
            + ("实际值每次都<b>高于</b>口头指引"
               if all(a > g + 1e-9 for g, a in ai_pairs)
               else f"实际值 {sum(1 for g, a in ai_pairs if a > g + 1e-9)} 次高于口头指引、"
                    f"{sum(1 for g, a in ai_pairs if abs(a - g) <= 1e-9)} 次与之相等"
                    "（相等那次的指引本就是「over」的下限措辞）")
            + (("，一次都没有低于" + ("，与正式指引的形态一致。" if never_below else "。"))
               if all(a >= g - 1e-9 for g, a in ai_pairs) else
               f"，{sum(1 for g, a in ai_pairs if a < g - 1e-9)} 次低于。")
        ),
        "src_extra": (
            "取自各季业绩 8-K EX-99.1 新闻稿的 CEO 引语。"
            "公司不按 AI / 非 AI 拆分申报收入，故无法与分部附注交叉验证。"
        ),
    }

    # Report insight 1: the record margin was carried by software. The two
    # segments' filed operating incomes sum to the company's non-GAAP operating
    # income exactly, so the quarter-on-quarter move in the guided margin splits
    # with no estimate into a mix leg and one leg per segment margin
    # (sequential substitution: mix first, then each segment's own margin).
    now_i, prev_i = seg_last, seg_last - 1

    def seg_split(i: int) -> tuple[float, float, float, float]:
        total_rev = semi_rev[i] + isg_rev[i]
        return (semi_rev[i] / total_rev, semi_oi[i] / semi_rev[i] * 100,
                isg_oi[i] / isg_rev[i] * 100, (semi_oi[i] + isg_oi[i]) / total_rev * 100)

    w0, semi_m0, soft_m0, om0 = seg_split(prev_i)
    w1, semi_m1, soft_m1, om1 = seg_split(now_i)
    mix_leg = (w1 - w0) * (semi_m0 - soft_m0)
    semi_leg = w1 * (semi_m1 - semi_m0)
    soft_leg = (1 - w1) * (soft_m1 - soft_m0)
    if abs(mix_leg + semi_leg + soft_leg - (om1 - om0)) > 1e-9:
        raise ValueError("the operating-margin bridge does not close")
    # `ng_margin` is rounded to six places for the payload, so compare with a
    # tolerance that covers the rounding and nothing more.
    om_record = om1 >= max(value for value in ng_margin if value is not None) - 1e-5
    without_software = om0 + mix_leg + semi_leg
    carried = soft_leg > 0 and mix_leg + semi_leg < 0
    isg_cost = segments["infrastructure_software_cost_of_revenue"]
    soft_opex = [None if isg_cost[i] is None else isg_rev[i] - isg_cost[i] - isg_oi[i]
                 for i in (prev_i, now_i)]
    soft_gm = [None if isg_cost[i] is None else (isg_rev[i] - isg_cost[i]) / isg_rev[i] * 100
               for i in (prev_i, now_i)]
    # Until this quarter's 10-Q / 10-K lands the split is the latest filed
    # quarter's, and every sentence says which quarter that is.
    bridge_quarter = "本季" if now_i == last else f"{periods[now_i]} "
    upfront_next = now_i == last and staging["upfront_license_revenue_usd_m"][last] is not None
    bridge_chart = {
        "ref": "EX_OM_BRIDGE",
        "kind": "diverging_bars",
        "title": spaced(
            "" if now_i == last else f"本季的分部拆分要等 {form_now}；最新一期 {periods[now_i]} 的",
            f"non-GAAP 营业利润率 {om1:.1f}%" + ("、创本页记录" if om_record else "")
            + f"，环比 {signed(om1 - om0, 2, 'pp')}"
            + (f"——软件分部利润率（{soft_m0:.1f}%→{soft_m1:.1f}%）贡献了 {signed(soft_leg, 2, 'pp')}，"
               f"半导体那一侧合计 {signed(mix_leg + semi_leg, 2, 'pp')}" if carried else
               f"：结构 {signed(mix_leg, 2, 'pp')}、半导体利润率 {signed(semi_leg, 2, 'pp')}、"
               f"软件利润率 {signed(soft_leg, 2, 'pp')}")
        ),
        "xlabels": [f"结构：半导体占比 {w0 * 100:.1f}%→{w1 * 100:.1f}%",
                    f"半导体分部利润率 {semi_m0:.1f}%→{semi_m1:.1f}%",
                    f"软件分部利润率 {soft_m0:.1f}%→{soft_m1:.1f}%", "合计"],
        "values": [round(mix_leg, 4), round(semi_leg, 4), round(soft_leg, 4), round(om1 - om0, 4)],
        "legend": "对 non-GAAP 营业利润率环比变化的贡献",
        "positive_label": "抬高营业利润率",
        "negative_label": "压低营业利润率",
        "fmt": "pp1", "yfmt": "pp1", "label_fmt": "pp1",
        "ylab": "pp", "zero_line": True,
        "note": (
            (f"<b>这是恒等式，不是估计</b>：在分部附注给出分部营业利润的全部 {len(seg_rows)} 个季度里，"
             "两个（FY2019 之前是三个）分部的申报营业利润之和<b>逐季精确等于</b>公司当季的 non-GAAP 营业利润，"
             "所以公司指引的那条营业利润率可以毫无估计地拆到两个引擎上；三条腿按「先结构、再各分部利润率」"
             "的顺序替代，相加恰好等于环比变化。" if identity_holds else
             "分部营业利润之和并不逐季等于公司的 non-GAAP 营业利润，这张拆分只是读数对照。")
            + (f"<b>没有软件分部利润率的抬升，{bridge_quarter}营业利润率是 {without_software:.2f}%，"
               f"环比 {signed(without_software - om0, 2, 'pp')}</b>，而不是{'创记录' if om_record else '上升'}；"
               f"半导体分部利润率 {semi_m0:.2f}%→{semi_m1:.2f}%，占比又从 {w0 * 100:.1f}% 升到 {w1 * 100:.1f}%，"
               "两件事都在往下拉。" if carried else "")
            + (f"软件那一侧的抬升来自费用与毛利率：软件分部营业费用（分部收入减成本减营业利润）"
               f"US${soft_opex[0]:,.0f}M→US${soft_opex[1]:,.0f}M，分部毛利率 {soft_gm[0]:.2f}%→{soft_gm[1]:.2f}%。"
               if None not in soft_opex else "")
            + f"{periods[now_i]} 软件用 {isg_rev[now_i] / (semi_rev[now_i] + isg_rev[now_i]) * 100:.0f}% 的收入"
            f"贡献了 {isg_oi[now_i] / (semi_oi[now_i] + isg_oi[now_i]) * 100:.0f}% 的分部营业利润"
            + ("；这一季的软件收入里有多少是一次性确认的，见下一张。" if upfront_next else "。")
        ),
        "src_extra": "分部收入、分部成本与分部营业利润逐季读自 10-Q / 10-K 的分部附注；三条腿与软件营业费用为自算。",
    }

    # Report insight 1, second half: whether the software jump is a pulse. The
    # 10-Qs disclose the licence revenue recognised upfront, which is the part
    # of software revenue that does not recur on a schedule.
    upfront = staging["upfront_license_revenue_usd_m"]
    up_rows = [i for i, value in enumerate(upfront) if value is not None]
    rest = [None if upfront[i] is None else isg_rev[i] - upfront[i] for i in range(len(periods))]
    up_share = [None if upfront[i] is None else upfront[i] / isg_rev[i] * 100 for i in range(len(periods))]
    up_yoy = rest_yoy = None
    if last - 4 in up_rows and last in up_rows:
        up_yoy = pct_change(upfront[last], upfront[last - 4])
        rest_yoy = pct_change(rest[last], rest[last - 4])
    story_block = stamped_block(staging, "quarter_story", periods[-1])
    upfront_chart = None
    if last in up_rows:
        upfront_chart = {
            "ref": "EX_UPFRONT",
            "kind": "stacked_dual",
            "title": (
                f"软件收入 US${isg_rev[-1]:,.0f}M 里 US${upfront[-1]:,.0f}M 是交付即确认的 upfront license"
                + (f"：剔除它，同比 {signed(rest_yoy)}，不是 {signed(isg_yoy)}" if rest_yoy is not None else "")
            ),
            "xlabels": [long_labels[i] for i in up_rows],
            "stacks": [
                {"name": "其余软件收入 D", "color": "NAVY", "values": [rest[i] for i in up_rows]},
                {"name": "upfront license 收入", "color": "GOLD", "values": [upfront[i] for i in up_rows]},
            ],
            "line": {"name": "upfront license 占软件收入 (RHS)", "color": "RED",
                     "values": rounded([up_share[i] for i in up_rows]), "yfmt": "pct1", "ymax": 100},
            "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
            "ylab": "US$M", "ylab2": "占软件收入",
            "note": (
                "没有「无理由解约」条款的软件合同，其授权部分在交付时一次性确认，公司叫它 upfront license revenue，"
                "从 FY2025 10-K 起单独披露。"
                + (f"本季 US${upfront[-1]:,.0f}M，上季 US${upfront[-2]:,.0f}M" if last - 1 in up_rows else "")
                + (f"，去年同季 US${upfront[-5]:,.0f}M（{signed(up_yoy)}）；按期确认的其余部分同比只有 "
                   f"{signed(rest_yoy)}。软件收入同比多出的 US${isg_rev[-1] - isg_rev[-5]:,.0f}M 里，"
                   f"US${upfront[-1] - upfront[-5]:,.0f}M 来自 upfront license。" if up_yoy is not None else "。")
                + (fill_story(story_block["upfront_reading"],
                              {"now": f"US${upfront[-1]:,.0f}M", "prior": f"US${upfront[-2]:,.0f}M"})
                   if story_block and story_block.get("upfront_reading") and last - 1 in up_rows else "")
            ),
            "src_extra": ("upfront license 取自 10-Q 收入附注（FY2025 各季为新口径下的重分类比较数，FY2025 Q4 为 10-K "
                          "全年减前三季）；其余软件收入 = 软件分部收入减 upfront license，为自算。"),
        }

    # Section one of the report: the free-cash-flow rate rests partly on tax
    # that was booked but not yet paid. Both provisions are shown because both
    # are reasonable baselines and they differ.
    recon_all = staging["release_reconciliation_usd_m"]
    cash_tax = recon_all["cash_paid_for_income_taxes"]
    gaap_tax = recon_all["gaap_tax_provision"]
    ng_tax = recon_all["non_gaap_tax_provision"]

    def taxed(provision: list[float | None]) -> list[float | None]:
        return [None if p is None or c is None or not r else (f - (p - c)) / r * 100
                for f, p, c, r in zip(fcf, provision, cash_tax, revenue)]

    fcf_gaap_taxed = taxed(gaap_tax)
    fcf_ng_taxed = taxed(ng_tax)
    fiscal_year = fiscal[-1].split()[0]
    ytd = [i for i, label in enumerate(fiscal) if label.split()[0] == fiscal_year]
    ytd_gap = sum(ng_tax[i] - cash_tax[i] for i in ytd)
    ytd_fcf = sum(fcf[i] for i in ytd)
    low, high = sorted((fcf_gaap_taxed[-1], fcf_ng_taxed[-1]))
    fcf_tax_chart = {
        "ref": "EX_FCF_TAX",
        "kind": "lines",
        "title": (
            f"自由现金流率 {fcf_margin[-1]:.1f}%，按当季计提补足没付的税只有 {low:.1f}%–{high:.1f}%："
            f"本季现金纳税 US${cash_tax[-1]:,.0f}M，所得税计提 US${gaap_tax[-1]:,.0f}M（GAAP）/ "
            f"US${ng_tax[-1]:,.0f}M（non-GAAP）"
            if cash_tax[-1] < min(gaap_tax[-1], ng_tax[-1]) else
            f"自由现金流率 {fcf_margin[-1]:.1f}%：本季现金纳税 US${cash_tax[-1]:,.0f}M，不低于所得税计提"
        ),
        "xlabels": long_labels,
        "series": [
            {"name": "自由现金流 ÷ 收入（公布口径）", "values": rounded(fcf_margin), "color": "NAVY"},
            {"name": "补足到 GAAP 所得税计提 D", "values": rounded(fcf_gaap_taxed), "color": "BLUE"},
            {"name": "补足到 non-GAAP 所得税计提 D", "values": rounded(fcf_ng_taxed), "color": "GOLD"},
        ],
        "fmt": "pct0", "yfmt": "pct0", "label_fmt": "pct1",
        "end_label": True, "ylab": "占收入 %",
        "note": (
            "三条线的差就是「计提了、当季还没付」的税：公布口径的自由现金流只扣了现金纳税，"
            "另外两条把当季的所得税计提补足（两种计提都说得通：non-GAAP 的计提是 EPS 用的那一个，GAAP 的是报表上的那一个）。"
            f"本季三者是 {fcf_margin[-1]:.2f}% / {fcf_gaap_taxed[-1]:.2f}% / {fcf_ng_taxed[-1]:.2f}%，"
            f"差 {fcf_margin[-1] - fcf_gaap_taxed[-1]:.2f}pp 到 {fcf_margin[-1] - fcf_ng_taxed[-1]:.2f}pp。"
            f"{fiscal_year} 到本季为止，non-GAAP 计提比现金纳税多 US${ytd_gap:,.0f}M，"
            f"是同期自由现金流 US${ytd_fcf:,.0f}M 的 {ytd_gap / ytd_fcf * 100:.1f}%。"
            "GAAP 计提在不少季度是负的（税收利益），所以浅蓝线常在深蓝线之上——两种补法的方向不一定相同。"
            "这张图只说明本季的公布口径里含有时点红利，不说明它会不会回补；回补的信号见第三板块的现金纳税比率。"
            "2016–2017 年没有可接的 non-GAAP 对账口径，两条补足线从 2018 起。"
        ),
        "src_extra": ("自由现金流 = 经营现金流 − 资本开支；现金纳税取自各季业绩 8-K 现金流量表的补充披露，"
                      "两种所得税计提取自同一份新闻稿的对账表。补足线为自算。"),
    }

    wedge = [None if n is None or g is None else n - g for n, g in zip(ng_margin, gaap_margin)]
    wedge_after = max(value for value in wedge[vmware:] if value is not None)
    wedge_peak = max(value for value in wedge if value is not None)
    wedge_chart = {
        "ref": "EX_WEDGE",
        "kind": "lines",
        "title": (
            f"GAAP 与 non-GAAP 营业利润率的缺口：本季 "
            f"{ng_margin[-1] - gaap_margin[-1]:.1f}pp，收购摊销与股权激励是主要内容"
        ),
        "xlabels": long_labels,
        "series": [
            {"name": "non-GAAP 营业利润率", "values": rounded(ng_margin), "color": "NAVY"},
            {"name": "GAAP 营业利润率", "values": rounded(gaap_margin), "color": "BLUE"},
            {"name": "Adjusted EBITDA 利润率", "values": rounded(ebitda_margin), "color": "GREEN"},
        ],
        "fmt": "pct0", "yfmt": "pct0", "label_fmt": "pct1",
        "end_label": True, "ylab": "占收入 %",
        "note": (
            "三条线画在一起是为了说明公司指引的是哪一条："
            "Adjusted EBITDA 利润率（绿）和 non-GAAP 营业利润率（深蓝）都是公司自定义口径，"
            "而它<b>从不指引</b> GAAP 利润率（浅蓝）。"
            f"两条口径之间的缺口在 VMware 并表后一度扩大到 {wedge_after:.1f}pp"
            + (f"（全窗口最大是 {periods[wedge.index(wedge_peak)]} 的 {wedge_peak:.1f}pp）"
               if wedge_peak > wedge_after else "")
            + f"，本季 {ng_margin[-1] - gaap_margin[-1]:.1f}pp。"
            "长期序列一律用 GAAP，因为 GAAP 的定义在整个窗口内没有变过。"
        ),
        "src_extra": (
            "GAAP 营业利润取自合并损益表；non-GAAP 营业利润与 Adjusted EBITDA "
            "取自同一份新闻稿的对账表。"
        ),
    }

    # The commitments table lives only in the 10-Q/10-K, so the newest quarter is
    # blank until that filing lands. Every sentence below anchors on the reading
    # that jumped and on the last quarter that has a reading, never on `[-1]`.
    total = commitments["total"]
    commit_filled = [i for i, v in enumerate(total) if v is not None]
    commit_last = commit_filled[-1]
    jump = max(commit_filled[1:],
               key=lambda i: total[i] / max(total[k] for k in commit_filled if k < i))
    before = [total[i] for i in commit_filled if i < jump]
    after_jump = [i for i in commit_filled if i > jump]
    commit_pending = total[-1] is None

    def quarter_word(index: int) -> str:
        return "本季" if index == last else ("上季" if index == last - 1 else "")

    if commit_pending:
        where = quarter_word(commit_last) or f"{periods[commit_last]} "
        commit_title = (f"无条件采购承诺停在{where}的 US${total[commit_last]:,.0f}M："
                        f"本季 {form_now} 尚未申报，这条线没有新读数")
    elif jump == last:
        commit_title = (f"无条件采购承诺一季之内从 US${total[commit_filled[-2]]:,.0f}M 跳到 "
                        f"US${total[last]:,.0f}M")
    else:
        commit_title = (f"无条件采购承诺 US${total[last]:,.0f}M：{periods[jump]} 那一跳之后"
                        f"{'继续上升' if total[last] > total[jump] else '有所回落'}")
    when = quarter_word(jump)

    # The two split columns are the XBRL first- and second-anniversary rows,
    # which in a 10-Q quarter are the next two fiscal years after the current
    # one's remainder -- not "within a year" and "the year after", as this note
    # used to say (see `purchase_commitments_note`).
    def row_years(index: int) -> tuple[str, str]:
        year = int(fiscal[index].split()[0][2:])
        return f"FY{year + 1}", f"FY{year + 2}"

    jump_first, jump_second = row_years(jump)
    last_first, last_second = row_years(commit_last)
    two_rows = [None if first is None or second is None else first + second
                for first, second in zip(commitments["due_within_one_year"], commitments["due_in_year_two"])]
    now_notes = notes_by_end.get(ends[commit_last], {})
    prior_notes = notes_by_end.get(ends[commit_last - 1], {})
    # The quarter before the last reading is 「上季」 only when that reading is this quarter's.
    before_last = (quarter_word(commit_last - 1) or periods[commit_last - 1]) + " "
    commit_chart = {
        "ref": "EX_COMMIT",
        "kind": "gs_bar",
        "title": commit_title,
        "xlabels": long_labels,
        "values": rounded(total),
        "legend": "无条件采购承诺（期末余额）",
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c", "ylab": "US$M",
        "note": (
            f"这条线有读数的 {len(commit_filled)} 个季度里，前 {len(before)} 个一直在 "
            f"US${min(before):,.0f}M–US${max(before):,.0f}M 之间，"
            + (f"{when}（{periods[jump]}）" if when else f"{periods[jump]} ")
            + f"一次性跳到 US${total[jump]:,.0f}M——"
            f"其中 {jump_first} 一行 US${commitments['due_within_one_year'][jump]:,.0f}M、"
            f"{jump_second} 一行 US${commitments['due_in_year_two'][jump]:,.0f}M。"
            "那一跳把「产能锁到 2028」从电话会上的说法变成了附注里的合同金额，"
            "它同时是两件事——基线情形下是收入的前瞻指标，"
            "需求不及预期时则是 take-or-pay 的刚性成本。"
            + (f"此后最新一期（{periods[commit_last]}）为 US${total[commit_last]:,.0f}M，"
               f"{last_first} 与 {last_second} 两行合计 US${two_rows[commit_last]:,.0f}M"
               f"（{before_last}US${two_rows[commit_last - 1]:,.0f}M）"
               + ("——本季本地分析稿把这两行当作「secured the supply」唯一的申报凭证，"
                  f"它们这一季{'续升' if two_rows[commit_last] > two_rows[commit_last - 1] else '没有续升'}；"
                  "这一读数离下季阈值有多远见第三板块。" if commit_last == last else "。")
               if after_jump and two_rows[commit_last - 1] is not None else "")
            + (f"资产一侧的对照是剩余履约义务：US${now_notes['rpo_usd_bn']:.1f}B"
               f"（{before_last}US${prior_notes['rpo_usd_bn']:.1f}B），公司预计其中约 "
               f"{now_notes['rpo_next_12_months_pct']:.0f}% 在 12 个月内确认。"
               if now_notes.get("rpo_usd_bn") and prior_notes.get("rpo_usd_bn") else "")
            + (f"<b>本季（{periods[-1]}）这条线是空的</b>：这张表只在 10-Q / 10-K 里，"
               f"而本季 {form_now} 截至本页构建时尚未申报{lag_text}。"
               "空格是披露时点的问题，不是承诺消失了。" if commit_pending else "")
            + f"注意纵轴是线性的，所以前 {len(before)} 季在图上几乎贴着零，那不是没有数据。"
        ),
        "src_extra": "取自各季 10-Q / 10-K 承诺与或有事项附注的 XBRL 标签，逐季申报值。",
    }

    # The report's reading of working capital: in days of sales and of cost the
    # two lines this chart used to call 「变重」 both got lighter this quarter;
    # what grew was other current assets. The levels did rise year on year --
    # that was true and is kept in the note -- but relative to the quarter's
    # sales and cost, which is what a working-capital question asks, they fell.
    days = [None] + [(datetime.date.fromisoformat(ends[i]) - datetime.date.fromisoformat(ends[i - 1])).days
                     for i in range(1, len(ends))]
    ng_cost = [None if gm is None else r - gm
               for r, gm in zip(revenue, staging["release_reconciliation_usd_m"]["non_gaap_gross_margin"])]
    receivable_days = [None if d is None else ar / r * d
                       for ar, r, d in zip(working["accounts_receivable"], revenue, days)]
    inventory_days = [None if d is None or not c else inv / c * d
                      for inv, c, d in zip(working["inventory"], ng_cost, days)]
    working_now = working["inventory"][-1] + working["accounts_receivable"][-1]
    working_year_ago = working["inventory"][-5] + working["accounts_receivable"][-5]
    lighter = receivable_days[-1] < receivable_days[-2] and inventory_days[-1] < inventory_days[-2]
    oca_now = notes_by_end.get(ends[-1], {})
    oca_prior = notes_by_end.get(ends[-2], {})
    oca_words = ""
    if oca_now.get("other_current_assets_usd_m") and oca_prior.get("other_current_assets_usd_m"):
        oca_words = (
            f"其他流动资产 US${oca_prior['other_current_assets_usd_m']:,.0f}M→US${oca_now['other_current_assets_usd_m']:,.0f}M"
            f"（{'+' if oca_now['other_current_assets_usd_m'] >= oca_prior['other_current_assets_usd_m'] else '−'}"
            f"US${abs(oca_now['other_current_assets_usd_m'] - oca_prior['other_current_assets_usd_m']):,.0f}M），"
            f"其中合同资产 US${oca_prior['contract_assets_current_usd_m']:,.0f}M→"
            f"US${oca_now['contract_assets_current_usd_m']:,.0f}M、预付费用 US${oca_prior['prepaid_expenses_usd_m']:,.0f}M→"
            f"US${oca_now['prepaid_expenses_usd_m']:,.0f}M（10-Q 附注）。")
    working_chart = {
        "ref": "EX_WORKING",
        "kind": "lines",
        "title": (
            f"应收天数 {receivable_days[-2]:.1f}→{receivable_days[-1]:.1f}、"
            f"存货天数 {inventory_days[-2]:.1f}→{inventory_days[-1]:.1f}"
            + ("：相对本季的收入与成本，营运资本在变轻" if lighter else "")
            + ("，涨的是其他流动资产" if oca_words and oca_now["other_current_assets_usd_m"]
               > oca_prior["other_current_assets_usd_m"] else "")
        ),
        "xlabels": long_labels,
        "series": [
            {"name": "应收天数 D（期末应收 ÷ 当季收入 × 当季天数）", "values": rounded(receivable_days),
             "color": "NAVY"},
            {"name": "存货天数 D（期末存货 ÷ 当季 non-GAAP 营业成本 × 当季天数）", "values": rounded(inventory_days),
             "color": "BLUE"},
        ],
        "fmt": "f0", "yfmt": "f0", "label_fmt": "f1",
        "end_label": True, "ylab": "天",
        "note": (
            f"金额本身同比是涨的：存货 US${working['inventory'][-1]:,.0f}M、应收 US${working['accounts_receivable'][-1]:,.0f}M，"
            f"两项同比合计{'多' if working_now > working_year_ago else '少'} US${abs(working_now - working_year_ago):,.0f}M；"
            f"但本季收入环比 {signed(pct_change(revenue[-1], revenue[-2]))}，应收只涨 "
            f"{signed(pct_change(working['accounts_receivable'][-1], working['accounts_receivable'][-2]))}、"
            f"存货只涨 {signed(pct_change(working['inventory'][-1], working['inventory'][-2]))}，"
            "折成天数两条都在下降，所以「库存与应收在膨胀」不是这一季的事实。"
            + oca_words
            + "存货天数的分母用 non-GAAP 营业成本（收入减对账表的 non-GAAP 毛利），2018 年以前没有这个口径，所以那条线从 2018 起；"
            "公司自己在电话会上说的「库存天数」以半导体分部成本作分母，与这里不是同一个数。"
        ),
        "src_extra": ("存货与应收取自各季 10-Q / 10-K 资产负债表；收入取自业绩 8-K，non-GAAP 营业成本 = 收入减对账表的 "
                      "non-GAAP 毛利；天数为两个季末之间的日历天数。两条均为自算。"),
    }

    # ── section three ────────────────────────────────────────────────────────
    # This report's section-8 lines, rendered from `next_kpi` with the same
    # fields section one settles, so next quarter the block moves there as is.
    ngm_order = (ngm_guide["periods"].index(guidance["period"]) + 1
                 if guidance["period"] in ngm_guide["periods"] else len(ngm_guide["periods"]) + 1)
    next_charts, next_table, next_facts = track_next(staging, readers)
    zero_streak = 0
    for value in reversed(buyback):
        if value != 0:
            break
        zero_streak += 1
    backstop_points = [notes_by_end[end]["backstop_max_usd_m"] for end in ends
                       if notes_by_end.get(end, {}).get("backstop_max_usd_m") is not None]
    # The one K6 condition with a zero threshold has no headroom to draw; its
    # reading goes into the section's own text instead of being dropped.
    liabilities_words = ""
    cl_now = notes_by_end.get(ends[-1], {}).get("contract_liabilities_current_usd_m")
    cl_prior = notes_by_end.get(ends[-2], {}).get("contract_liabilities_current_usd_m")
    if cl_now is not None and cl_prior is not None:
        liabilities_words = (
            f"K6 的「递延收入不降」没有余量可算，读数是流动合同负债 US${cl_prior:,.0f}M→US${cl_now:,.0f}M"
            f"（{'+' if cl_now >= cl_prior else '−'}US${abs(cl_now - cl_prior):,.0f}M）"
            + ("：降了，结构性一档的这一条没有满足" if cl_now < cl_prior else "：没有降")
            + "。")

    # ── section four ─────────────────────────────────────────────────────────
    both = [i for i in range(len(periods)) if semi_margin[i] is not None and isg_margin[i] is not None]
    software_always_higher = all(isg_margin[i] > semi_margin[i] for i in both)
    before_vmware = isg_margin[vmware - 1]
    trough = min(isg_margin[i] for i in both if i >= vmware)
    trough_at = next(i for i in both if i >= vmware and isg_margin[i] == trough)
    best_after = max(isg_margin[i] for i in both if i >= vmware)
    if trough < before_vmware < isg_margin[seg_last]:
        seg_tail = "软件的利润率被 VMware 拉低后已涨回并超过并入前"
    elif software_always_higher:
        seg_tail = f"软件在有分部数据的 {len(both)} 季里季季高于半导体"
    else:
        seg_tail = "两条线在窗口内有过交叉"
    ipl_quarters = sum(1 for i in both if ipl_rev[i] is not None)
    semi_recent = [semi_margin[i] for i in both][-WINDOW:]
    cost_points = sum(1 for v in segments["semiconductor_cost_of_revenue"] if v is not None)
    first_cost = periods[next(i for i, v in enumerate(segments["semiconductor_cost_of_revenue"])
                              if v is not None)]
    seg_margin_chart = {
        "ref": "EX_SEG_MARGIN",
        "kind": "lines",
        "title": (
            f"两个引擎的分部营业利润率（最新一期 {periods[seg_last]}）：软件 "
            f"{isg_margin[seg_last]:.0f}%、半导体 {semi_margin[seg_last]:.0f}%，" + seg_tail
        ),
        "xlabels": long_labels,
        "series": [
            {"name": "半导体分部", "values": rounded(semi_margin), "color": "NAVY"},
            {"name": "基础设施软件分部", "values": rounded(isg_margin), "color": "BLUE"},
        ],
        "fmt": "pct0", "yfmt": "pct0", "label_fmt": "pct1",
        "end_label": True, "ylab": "分部营业利润率",
        "note": (
            "两条线讲的是这家公司为什么长成现在这样：软件分部的利润率在 VMware 并入的"
            f"{'那一季' if trough_at == vmware else f' {periods[trough_at]} '}从 {before_vmware:.0f}% "
            f"掉到 {trough:.0f}%，此后一路抬到 {best_after:.0f}% 上下，"
            "靠的是把收购来的产品并进现有渠道而几乎不增加成本；"
            f"半导体分部则在 AI 放量下保持在{cn_count(round(statistics.median(semi_recent) / 10))}成上下。"
            + (f"最左边的{cn_count(ipl_quarters)}季只有半导体与软件两条、没有第三条，"
               "是因为当时还有一个很小的 IP licensing 分部，其收入与利润已并入核对表。"
               if ipl_quarters else "")
            + f"分部<b>毛利率</b>不画进这张 {len(periods)} 季的图：分部成本是 ASU 2023-07 之后才有的披露，"
            f"季度数从 {first_cost} 起，只有{cn_count(cost_points)}季。"
        ),
        "src_extra": "分部收入与分部营业利润逐季取自 10-Q / 10-K 分部附注。",
    }

    clouds = hyperscaler_capex_share(periods[-1])
    cloud_words = ""
    if clouds and int(min(clouds[1]) // 10) >= 1:
        cloud_words = (f"表里{cn_count(len(clouds[1]))}家云厂的现金资本开支占收入普遍在"
                       f"{cn_count(int(min(clouds[1]) // 10))}成以上，Broadcom 是 "
                       f"{capex_intensity[-1]:.1f}%——"
                       "同一条 AI 产业链上，上游花的是别人的资本开支，自己几乎不花。")
    intensity_chart = {
        "ref": "EX_INTENSITY",
        "kind": "lines",
        "title": (
            f"资本强度：资本开支只占收入 {capex_intensity[-1]:.1f}%，"
            f"研发占 {rnd_intensity[-1]:.1f}%"
            + ("——钱花在人身上，不花在厂房上" if rnd_intensity[-1] > capex_intensity[-1] else "")
        ),
        "xlabels": long_labels,
        "series": [
            {"name": "研发费用 / 收入", "values": rounded(rnd_intensity), "color": "NAVY"},
            {"name": "资本开支 / 收入", "values": rounded(capex_intensity), "color": "RED"},
        ],
        "fmt": "pct0", "yfmt": "pct0", "label_fmt": "pct1",
        "end_label": True, "ylab": "占收入 %",
        "note": (
            "这张图是本页与页尾那张 AI capex 循环表的接口。"
            + cloud_words
            + f"研发强度从窗口初的 {rnd_intensity[0]:.0f}% "
            f"{moved(rnd_intensity[-1], rnd_intensity[0])} {rnd_intensity[-1]:.0f}%，"
            + ("分母涨得比分子快，不是研发投入在收缩（绝对额同期从 "
               f"US${rnd[0]:,.0f}M 涨到 US${rnd[-1]:,.0f}M）。"
               if rnd_intensity[-1] < rnd_intensity[0] and rnd[-1] > rnd[0] else "")
            # The claim this note used to end on -- that the real capacity cost
            # sits in working capital -- is not this quarter's fact (see the
            # working-capital chart); what moved is capital expenditure itself.
            + (f"资本开支本身这一季从 US${capex[-2]:,.0f}M 涨到 US${capex[-1]:,.0f}M"
               f"（{capex[-1] / capex[-2]:.1f} 倍）"
               + (f"，公司在电话会上给下一季的是 US${call['capital_expenditures_usd_bn']:.1f}B（公司口径）"
                  if call and call.get("capital_expenditures_usd_bn") else "")
               + "——占收入的比例仍低，但这条线的方向已经变了。"
               if capex[-2] and capex[-1] >= 1.5 * capex[-2] else "")
        ),
        "src_extra": "资本开支与研发费用逐季取自现金流量表与损益表（财年第四季为年度数减前三季）。",
    }

    fcf_top = fcf[-1] == max(fcf)
    margin_top = fcf_margin[-1] == max(value for value in fcf_margin if value is not None)
    if fcf_top and margin_top:
        conversion_title = (f"自由现金流 US${fcf[-1]:,.0f}M、占收入 {fcf_margin[-1]:.0f}%，"
                            f"两项都是本页 {len(periods)} 季记录中最高")
    elif fcf_top:
        conversion_title = (f"自由现金流 US${fcf[-1]:,.0f}M，为本页 {len(periods)} 季记录中最高；"
                            f"占收入 {fcf_margin[-1]:.0f}% 则不是")
    else:
        conversion_title = f"自由现金流 US${fcf[-1]:,.0f}M、占收入 {fcf_margin[-1]:.0f}%"
    fcf_rise = fcf_margin[-1] - fcf_margin[0]
    capex_saving = capex_intensity[0] - capex_intensity[-1]
    if fcf_rise > 0 and capex_saving < 0.15 * fcf_rise:
        source_words = ("抬升几乎全部来自利润率而不是资本开支的节省——后者从 "
                        f"{capex_intensity[0]:.1f}% 降到 {capex_intensity[-1]:.1f}%，"
                        f"只贡献了其中 {max(capex_saving, 0):.1f} 个百分点。")
    elif fcf_rise > 0:
        source_words = (f"其中资本开支占收入从 {capex_intensity[0]:.1f}% 降到 "
                        f"{capex_intensity[-1]:.1f}%，贡献了 {capex_saving:.1f} 个百分点，"
                        f"经营现金流利润率贡献了其余的 {ocf_margin[-1] - ocf_margin[0]:.1f} 个。")
    else:
        source_words = ""
    conversion_chart = {
        "ref": "EX_FCF",
        "kind": "gs_bar",
        "title": conversion_title,
        "xlabels": long_labels,
        "values": rounded(fcf),
        "legend": "自由现金流 D",
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M", "ylab2": "占收入",
        "yoy": {"name": "FCF 利润率 (RHS)", "values": rounded(fcf_margin), "color": "GREEN", "yfmt": "pct0"},
        "note": (
            "自由现金流在这里是<b>自算值</b>：经营现金流减去资本开支，"
            "与公司在新闻稿里印出来的同名数字定义一致，逐季核对相符。"
            f"占收入的比重从窗口初的 {fcf_margin[0]:.0f}% "
            f"{moved(fcf_margin[-1], fcf_margin[0], up='抬到')} {fcf_margin[-1]:.0f}%，"
            + source_words
        ),
        "src_extra": "经营现金流与资本开支取自现金流量表；两项均与新闻稿披露的当季数一致。",
    }

    peak = max(value for value in net_debt if value is not None)
    peak_at = net_debt.index(peak)
    delevered = net_debt[-1] < peak and peak_at >= vmware
    cash_up = cash_balance[-1] - cash_balance[-2]
    debt_down = debt[-2] - debt[-1]
    net_down = net_debt[-2] - net_debt[-1]
    buyback_cut = buyback[-1] < buyback[-2]
    unexplained = story is not None and not story["buyback_change_explained"]
    debt_story = ""
    if net_down > 0 and cash_up > 0 and debt_down > 0:
        # `cn_fraction` names the nearest unit fraction, so above one half it
        # would call nine tenths 「一半」.
        share = cash_up / net_down
        debt_story = (f"本季的去杠杆有{cn_fraction(share) if share < 0.6 else '大部分'}不是还债换来的，而是现金堆积"
                      + (f"——回购从上季的 US${buyback[-2]:,.0f}M 砍到 US${buyback[-1]:,.0f}M"
                         + ("，公司没有解释原因。" if unexplained else "。")
                         if buyback_cut else "。"))
    debt_chart = {
        "ref": "EX_DEBT",
        "kind": "lines",
        "title": (
            ("VMware 之后的去杠杆：" if delevered else "")
            + f"总债务 US${debt[-1]:,.0f}M、净债务 US${net_debt[-1]:,.0f}M"
            + (f"，净债务较峰值下降 US${peak - net_debt[-1]:,.0f}M" if delevered else "")
        ),
        "xlabels": long_labels,
        "series": [
            {"name": "总债务（长期＋一年内到期）", "values": rounded(debt), "color": "NAVY"},
            {"name": "净债务 D（总债务 − 现金）", "values": rounded(net_debt), "color": "RED"},
            {"name": "现金及等价物", "values": rounded(cash_balance), "color": "GREEN"},
        ],
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "end_label": True, "ylab": "US$M",
        "note": (
            "两级台阶都看得见：2019 年的 CA / Symantec，以及 "
            f"{ends[vmware][:4]} 年初 VMware 把总债务一次抬到 US${debt[vmware]:,.0f}M。"
            + (f"此后净债务从峰值 US${peak:,.0f}M 降到 US${net_debt[-1]:,.0f}M。" if delevered else "")
            + debt_story
        ),
        "src_extra": (
            "总债务为资产负债表长期债务与一年内到期部分之和。"
            "公司在 FY2023–FY2025 期间改用了含融资租赁的标签、FY2026 又改回，"
            "两套标签在重叠期取值一致，本页按同一口径接续。"
        ),
    }

    # Report insight 2: the buyback went to zero in the quarter debt repayment
    # jumped, and nothing in the release says why. Where this quarter's free
    # cash flow went is read off the cash-flow statement, one line per use.
    repaid = staging["release_reconciliation_usd_m"]["debt_repayments"]
    returned = (buyback[-1] + dividends[-1]) / fcf[-1] * 100
    window_dividends = dividends[tail]
    flat = (max(window_dividends) - min(window_dividends)) / max(window_dividends) <= 0.25
    uses = [("偿债", repaid[-1]), ("分红", dividends[-1]), ("回购", buyback[-1])]
    payout_chart = {
        "ref": "EX_PAYOUT",
        "kind": "grouped_bars",
        "title": (
            f"本季自由现金流 US${fcf[-1]:,.0f}M 的去向："
            + "、".join(f"{name} US${value:,.0f}M（{value / fcf[-1] * 100:.0f}%）"
                       for name, value in uses if value)
            + ("，回购为零" if buyback[-1] == 0 else "")
            + (f"，现金多出 US${cash_up:,.0f}M" if cash_up > 0 else "")
        ),
        "xlabels": labels,
        "groups": [
            {"name": "自由现金流 D", "values": rounded(fcf[tail]), "color": "GREEN"},
            {"name": "偿还债务", "values": repaid[tail], "color": "GRAY"},
            {"name": "普通股分红", "values": capital["common_dividends"][tail], "color": "BLUE"},
            {"name": "回购", "values": capital["share_repurchases"][tail], "color": "NAVY"},
        ],
        "bar_labels": False,
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c", "ylab": "US$M",
        "note": (
            f"偿债从上季的 US${repaid[-2]:,.0f}M {moved(repaid[-1], repaid[-2], up='跳到')} "
            f"US${repaid[-1]:,.0f}M，回购从 US${buyback[-2]:,.0f}M "
            f"{'掉到' if buyback_cut else '变成'} US${buyback[-1]:,.0f}M，"
            + (f"分红{cn_count(WINDOW)}季几乎是平的；" if flat else
               f"分红{cn_count(WINDOW)}季从 US${window_dividends[0]:,.0f}M "
               f"{moved(window_dividends[-1], window_dividends[0], up='涨到')} US${window_dividends[-1]:,.0f}M；")
            + f"回购加分红合计{'只' if returned < 50 else ''}占自由现金流 {returned:.0f}%。"
            + (f"期末现金多出 US${cash_up:,.0f}M——钱没有还给股东，一部分还了债，一部分留在了资产负债表上。"
               if buyback_cut and cash_up > 0 else "")
            + ("本页不推测原因——新闻稿对回购归零一字未提，这里只把几条线并排放着。" if unexplained
               else "这里只把几条线并排放着。")
        ),
        "src_extra": ("回购、分红与偿债取自各季业绩 8-K 现金流量表融资活动（偿债为「Payments on debt obligations」，"
                      "早年叫「Repayment of debt」）；自由现金流为经营现金流减资本开支。"),
    }

    # Numbered once every chart exists, in render order. The four sections are
    # the site's fixed layout: what last quarter left, settled; this quarter's
    # conclusions; what to track next; the long-run series. A chart belongs to
    # the section its content answers, not to where it happens to be computed:
    # the GAAP / non-GAAP wedge is a 42-quarter structural line with no
    # this-quarter conclusion, so it sits with the routine series, and the
    # payout chart reads this quarter's capital allocation, so it sits with the
    # quarter's highlights. Section two runs in the order of the report's own
    # conclusions: revenue and its mix, the AI line, the record margin and what
    # carried it, how much of software was booked upfront, the tax inside the
    # free-cash-flow rate, where that cash went, the commitments the 10-Q
    # settles, and working capital.
    highlight_charts = ([revenue_chart, mix_chart, ai_chart, bridge_chart]
                        + ([upfront_chart] if upfront_chart else [])
                        + [fcf_tax_chart, payout_chart, commit_chart, working_chart])
    routine_charts = [seg_margin_chart, wedge_chart, intensity_chart, conversion_chart, debt_chart]
    settled_ex = number_exhibits(settled_charts, start=2)
    highlight_ex = number_exhibits(highlight_charts, start=settled_ex[-1]["n"] + 1)
    next_ex = number_exhibits(next_charts, start=highlight_ex[-1]["n"] + 1)
    routine_ex = number_exhibits(routine_charts, start=(next_ex or highlight_ex)[-1]["n"] + 1)

    all_ex = settled_ex + highlight_ex + next_ex + routine_ex
    resolve_exhibit_refs(all_ex)

    # ── audit tables ─────────────────────────────────────────────────────────
    def fmt_row(values, spec="{:,.0f}"):
        return ["—" if v is None else spec.format(v) for v in values]

    tables = []
    for table in prior_tables + delivery_tables:
        tables.append({"n": len(tables) + 1, **table})
    gap_table_n = tables[-1]["n"]
    tables.append({
        "n": len(tables) + 1,
        "title": f"{cn_count(WINDOW)}季度收入、利润率与现金流（US$M，利润率为自算）",
        "headers": ["项目"] + [f"{p}（{f}）" for p, f in zip(periods[tail], fiscal[tail])],
        "rows": [
            ["收入"] + fmt_row(revenue[tail]),
            ["GAAP 营业利润"] + fmt_row(gaap_oi[tail]),
            ["non-GAAP 营业利润"] + fmt_row(ng_oi[tail]),
            ["Adjusted EBITDA"] + fmt_row(ebitda[tail]),
            ["GAAP 营业利润率 D"] + fmt_row(gaap_margin[tail], "{:.2f}%"),
            ["non-GAAP 营业利润率 D"] + fmt_row(ng_margin[tail], "{:.2f}%"),
            ["Adjusted EBITDA 利润率 D"] + fmt_row(ebitda_margin[tail], "{:.2f}%"),
            ["经营现金流"] + fmt_row(ocf[tail]),
            ["资本开支"] + fmt_row(capex[tail]),
            ["自由现金流 D"] + fmt_row(fcf[tail]),
        ],
    })
    tables.append({
        "n": len(tables) + 1,
        "title": f"{cn_count(WINDOW)}季度分部收入与分部营业利润（US$M）",
        "headers": ["项目"] + [f"{p}（{f}）" for p, f in zip(periods[tail], fiscal[tail])],
        "rows": [
            ["半导体解决方案 收入"] + fmt_row(semi_rev[tail]),
            ["基础设施软件 收入"] + fmt_row(isg_rev[tail]),
            ["半导体 分部营业利润"] + fmt_row(semi_oi[tail]),
            ["基础设施软件 分部营业利润"] + fmt_row(isg_oi[tail]),
            ["两分部合计营业利润 D"] + fmt_row(
                [None if a is None or b is None else a + b for a, b in zip(semi_oi[tail], isg_oi[tail])]),
            ["公司 non-GAAP 营业利润（对照）"] + fmt_row(ng_oi[tail]),
            ["半导体 分部营业利润率 D"] + fmt_row(semi_margin[tail], "{:.1f}%"),
            ["基础设施软件 分部营业利润率 D"] + fmt_row(isg_margin[tail], "{:.1f}%"),
        ],
    })
    tables.append({
        "n": len(tables) + 1,
        "title": f"{cn_count(WINDOW)}季度资本配置、营运资本与采购承诺（US$M）",
        "headers": ["项目"] + [f"{p}（{f}）" for p, f in zip(periods[tail], fiscal[tail])],
        "rows": [
            ["回购"] + fmt_row(capital["share_repurchases"][tail]),
            ["普通股分红"] + fmt_row(capital["common_dividends"][tail]),
            ["现金及等价物"] + fmt_row(capital["cash_and_equivalents"][tail]),
            ["总债务"] + fmt_row(capital["total_debt"][tail]),
            ["净债务 D"] + fmt_row(net_debt[tail]),
            ["存货"] + fmt_row(working["inventory"][tail]),
            ["应收账款"] + fmt_row(working["accounts_receivable"][tail]),
            ["无条件采购承诺"] + fmt_row(commitments["total"][tail]),
            ["其中下一财年一行"] + fmt_row(commitments["due_within_one_year"][tail]),
            ["其中再下一财年一行"] + fmt_row(commitments["due_in_year_two"][tail]),
            ["偿还债务"] + fmt_row(repaid[tail]),
        ],
    })
    tables.append({
        "n": len(tables) + 1,
        "title": f"{cn_count(WINDOW)}季度自由现金流与所得税：现金纳税与两种计提（US$M，比率为自算）",
        "headers": ["项目"] + [f"{p}（{f}）" for p, f in zip(periods[tail], fiscal[tail])],
        "rows": [
            ["自由现金流 D"] + fmt_row(fcf[tail]),
            ["现金纳税"] + fmt_row(cash_tax[tail]),
            ["GAAP 所得税计提"] + fmt_row(gaap_tax[tail]),
            ["non-GAAP 所得税计提"] + fmt_row(ng_tax[tail]),
            ["自由现金流 ÷ 收入 D"] + fmt_row(fcf_margin[tail], "{:.2f}%"),
            ["补足到 GAAP 计提 D"] + fmt_row(fcf_gaap_taxed[tail], "{:.2f}%"),
            ["补足到 non-GAAP 计提 D"] + fmt_row(fcf_ng_taxed[tail], "{:.2f}%"),
            ["现金纳税 ÷ non-GAAP 计提 D"] + fmt_row(readers["cash_tax_ratio_ng"].values[tail], "{:.1f}%"),
            ["non-GAAP 营业费用"] + fmt_row(
                staging["release_reconciliation_usd_m"]["non_gaap_operating_expenses"][tail]),
        ],
    })
    if up_rows:
        tables.append({
            "n": len(tables) + 1,
            "title": "软件收入里的 upfront license（US$M，其余部分与占比为自算）",
            "headers": ["本站季度", "公司财季", "软件分部收入", "upfront license", "其余软件收入 D",
                        "upfront 占软件收入 D"],
            "rows": [[periods[i], fiscal[i], f"{isg_rev[i]:,.0f}", f"{upfront[i]:,.0f}",
                      f"{rest[i]:,.0f}", f"{up_share[i]:.1f}%"] for i in up_rows],
        })
    tables.append({
        "n": len(tables) + 1,
        "title": "AI 半导体收入的口头指引与实际值（US$B，出自新闻稿 CEO 引语，非申报分部）",
        "headers": ["本站季度", "上一季给出的口头指引", "随后报出的实际值", "指引所在新闻稿"],
        "rows": [
            [period,
             "—" if g is None else f"{g:.1f}",
             "—" if a is None else (f"≥{a:.1f}" if floor else f"{a:.1f}"),
             rel or "—"]
            for period, g, a, floor, rel in zip(
                ai["periods"], ai["guided_usd_bn"], ai["actual_usd_bn"],
                ai["actual_is_floor"], ai["guided_in_release"])
        ] + [[ai["next_quarter_period"], f"{ai['next_quarter_guide_usd_bn']:.1f}", "待披露",
              ai["next_quarter_guided_in_release"]]],
    })
    if next_table is not None:
        tables.append({"n": len(tables) + 1, **next_table})
    tables.append(ai_capex_cycle_table(len(tables) + 1))

    point_count = sum(1 for form, actual in zip(record["revenue_form"], record["actual_revenue_usd_m"])
                      if form == "point" and actual is not None)
    range_count = sum(1 for form in record["revenue_form"] if form == "range")
    range_inside = all(lo <= actual <= hi for form, lo, hi, actual in zip(
        record["revenue_form"], record["guide_revenue_lo_usd_m"], record["guide_revenue_hi_usd_m"],
        record["actual_revenue_usd_m"]) if form == "range" and actual is not None)
    point_above = all(actual > mid for form, mid, actual in zip(
        record["revenue_form"], record["guide_revenue_usd_m"], record["actual_revenue_usd_m"])
        if form == "point" and actual is not None)
    margin_pairs = [(g, a) for g, a in zip(record["guide_ebitda_margin_pct"],
                                           record["actual_ebitda_margin_pct"])
                    if g is not None and a is not None]
    margin_count = len(margin_pairs)
    margin_above = all(a > g for g, a in margin_pairs)
    phases = outlook_phases(record, staging["annual_only_guidance"])
    unguided = unguided_quarters(staging)
    releases_examined = len(record["periods"]) + len(staging["annual_only_guidance"])
    formal_names = (["收入"]
                    + (["non-GAAP 营业利润率"] if guidance["non_gaap_operating_margin_pct"] is not None else [])
                    + (["Adjusted EBITDA 利润率"] if guidance["adjusted_ebitda_margin_pct"] is not None else []))
    record_years = year_of(record["periods"][max(i for i, v in enumerate(record["actual_revenue_usd_m"])
                                                 if v is not None)]) - year_of(record["periods"][0])
    # Two paths to a fiscal fourth quarter -- the release, and the year less its
    # first three quarters -- meet wherever a whole fiscal year sits in the window.
    fin_years = staging["filed_fiscal_years"]
    by_end = dict(zip(ends, range(len(ends))))
    reconciled = 0
    for year_end, filed_revenue in zip(fin_years["fiscal_year_ends"], fin_years["revenue_usd_m"]):
        quarters = [by_end[end] for end in ends if end <= year_end][-4:]
        if len(quarters) < 4 or int(year_end[:4]) - int(ends[quarters[0]][:4]) > 1:
            continue
        if any(semi_rev[i] is None or isg_rev[i] is None for i in quarters):
            continue
        if abs(sum(revenue[i] for i in quarters) - filed_revenue) <= 1.0 and all(
                abs(semi_rev[i] + isg_rev[i] + (ipl_rev[i] or 0.0) - revenue[i]) <= 1.0
                for i in quarters):
            reconciled += 1

    # ── the takeaways ────────────────────────────────────────────────────────
    if stop is None:
        seal = "。"
    elif stop["first_missing_period"] == periods[-1]:
        seal = f"——而这条记录到 {periods[-1]} 为止<b>封存</b>了：公司本季起不再披露该指标。"
    else:
        seal = (f"——而这条记录到 {stop['first_missing_period']} 为止<b>封存</b>了："
                f"公司自那一季起不再披露该指标。")
    record_article = (
        '<article><span>记录</span><b>指引的形式变了，答案也跟着变</b>'
        + (f'<p>给区间的 {range_count} 季，实际值季季落在<b>区间之内</b>；' if range_inside
           else f'<p>给区间的 {range_count} 季，实际值并非季季落在区间之内；')
        + (f'改给单点后的 {point_count} 季，季季落在<b>点之上</b>。' if point_above
           else f'改给单点后的 {point_count} 季，并非季季落在点之上。')
        + (f'Adjusted EBITDA 利润率 {margin_count} 季全部高于指引' if margin_above
           else f'Adjusted EBITDA 利润率 {margin_count} 季并非全部高于指引')
        + seal + '</p></article>'
    )
    # The quarter's lines follow the report's conclusions, each one only when
    # the data says it: the beat sat in one line, the record margin needed the
    # software leg, the cash rate carried booked-but-unpaid tax, and the
    # commitments the 10-Q settles.
    articles = [record_article]
    bridge_is_this_quarter = now_i == last
    if legs_summary:
        up_legs, down_legs, gap = legs_summary
        articles.append(
            '<article><span>分歧</span><b>'
            + ("超额只落在 AI 一格" if [name for name, _ in up_legs] == ["AI 半导体"] and down_legs
               else "三条业务线相对指引有正有负" if up_legs and down_legs else "三条业务线同向偏离指引")
            + f'</b><p>收入比指引{"多" if gap >= 0 else "少"} US${abs(gap):,.0f}M：'
            + "、".join(f"{name}多出 US${value:,.0f}M" for name, value in up_legs)
            + ("，" if up_legs and down_legs else "")
            + "、".join(f"{name}少了 US${abs(value):,.0f}M" for name, value in down_legs)
            + '。分业务的指引只在电话会上说过，按公司口径记。</p></article>')
    if carried and bridge_is_this_quarter:
        articles.append(
            '<article><span>利润</span><b>'
            + ("创纪录的" if om_record else "") + '营业利润率靠软件撑住</b>'
            f'<p>non-GAAP 营业利润率 {om1:.1f}%，环比 {signed(om1 - om0, 2, "pp")}；'
            f'软件分部利润率 {soft_m0:.1f}%→{soft_m1:.1f}% 贡献 {signed(soft_leg, 2, "pp")}，'
            f'半导体占比上升与半导体利润率合计 {signed(mix_leg + semi_leg, 2, "pp")}。'
            + (f'而软件收入里 US${upfront[-1]:,.0f}M 是交付即确认的 upfront license。' if upfront[-1] else '')
            + '</p></article>')
    if cash_tax[-1] < min(gaap_tax[-1], ng_tax[-1]):
        articles.append(
            f'<article><span>现金</span><b>{fcf_margin[-1]:.0f}% 的自由现金流率里有时点红利</b>'
            f'<p>本季现金纳税 US${cash_tax[-1]:,.0f}M，所得税计提 US${gaap_tax[-1]:,.0f}M（GAAP）/ '
            f'US${ng_tax[-1]:,.0f}M（non-GAAP）；按计提补足，自由现金流率是 {low:.1f}%–{high:.1f}%。</p></article>')
    if not commit_pending and after_jump and two_rows[commit_last - 1] is not None:
        grew = two_rows[commit_last] > two_rows[commit_last - 1]
        articles.append(
            '<article><span>承诺</span><b>'
            + ("采购承诺继续上升" if grew else "采购承诺没有续升") + '</b>'
            f'<p>{periods[jump]} 一季之内从 US${total[max(i for i in commit_filled if i < jump)]:,.0f}M '
            f'跳到 US${total[jump]:,.0f}M；'
            f'本季 {form_now} 里 {last_first} 与 {last_second} 两行合计 US${two_rows[commit_last]:,.0f}M'
            f'（上季 US${two_rows[commit_last - 1]:,.0f}M）。</p></article>')

    subtractions = []
    if stop is not None and stop["first_missing_period"] == periods[-1]:
        subtractions.append("公司停止披露 Adjusted EBITDA，上季为它给出的指引因此永远无法结算")
    if buyback_cut:
        subtractions.append(f"回购从 US${buyback[-2]:,.0f}M 降到 US${buyback[-1]:,.0f}M"
                            + ("，公司没有解释" if unexplained else ""))
    if all_cleared and never_below:
        record_words = (
            f"{cn_count(guided)}条正式指引照例都过了：{finished_count} 个已完结季里实际收入一次都没有低于指引，"
            f"偏离始终挤在 {min(dev_band):+.2f}% 到 {max(dev_band):+.2f}% 这条窄带里，"
        )
    else:
        record_words = (
            f"{verdict[2:]}；{finished_count} 个已完结季里实际收入有 "
            f"{sum(1 for value in dev_band if value < 0)} 季低于指引的点或中值，"
            f"偏离在 {min(dev_band):+.2f}% 到 {max(dev_band):+.2f}% 之间，"
        )
    # The headline follows the report's reading of the quarter, one clause per
    # conclusion and each only when the data carries it.
    headline_parts = [f"收入 US${revenue[-1]:,.0f}M、同比 {signed(yoy[-1])}"]
    if legs_summary:
        up_legs, down_legs, gap = legs_summary
        if gap > 0 and [name for name, _ in up_legs] == ["AI 半导体"] and len(down_legs) == 2:
            headline_parts.append(
                f"比指引多 US${gap:,.0f}M，超额全在 AI（+US${up_legs[0][1]:,.0f}M），"
                f"非 AI 与软件合计少 US${abs(sum(value for _, value in down_legs)):,.0f}M")
        else:
            headline_parts.append(f"比指引{'多' if gap >= 0 else '少'} US${abs(gap):,.0f}M")
    # The margin is this quarter's from the release; what carried it needs the
    # segment note, so that clause waits for this quarter's 10-Q / 10-K.
    headline_parts.append(
        f"non-GAAP 营业利润率 {ng_margin[-1]:.1f}%"
        + ("，创本页记录" if ng_margin[-1] >= max(v for v in ng_margin if v is not None) else "")
        + ("，但没有软件分部利润率的抬升就是环比下降"
           if now_i == last and carried and without_software < om0 else ""))
    if cash_tax[-1] < min(gaap_tax[-1], ng_tax[-1]):
        headline_parts.append(
            f"自由现金流率 {fcf_margin[-1]:.1f}%，其中 {fcf_margin[-1] - high:.1f}–{fcf_margin[-1] - low:.1f}pp "
            "是计提了、当季还没付的税")

    # Guidance rows follow the outlook the release actually printed.
    about = "约" if guidance["formal_qualifier"] == "approximately" else ""
    guidance_rows = [["收入", f"{about} US${guidance['revenue_usd_bn']:.1f}B".strip(),
                      "单点" if guidance["revenue_form"] == "point" else "区间",
                      "Business Outlook 区块"]]
    if guidance["non_gaap_operating_margin_pct"] is not None:
        guidance_rows.append([
            "non-GAAP 营业利润率",
            f"{about}为收入的 {guidance['non_gaap_operating_margin_pct']:.0f}%", "单点",
            f"Business Outlook 区块（第{cn_ordinal(ngm_order)}次给这一条）"])
    if guidance["adjusted_ebitda_margin_pct"] is not None:
        guidance_rows.append([
            "Adjusted EBITDA 利润率",
            f"{about}为收入的 {guidance['adjusted_ebitda_margin_pct']:.0f}%", "单点",
            "Business Outlook 区块"])
    elif stop is not None and stop["release"] == guidance["released"]:
        guidance_rows.append([
            "Adjusted EBITDA 利润率", "未给", "—",
            f"上一份给过约 {record['guide_ebitda_margin_pct'][at]:.0f}%；"
            "本份新闻稿里这个指标连同实际值一起消失"])
    guidance_rows.append([
        "AI 半导体收入",
        f"US${guidance['ai_semiconductor_revenue_usd_bn']:.1f}B", "单点",
        "CEO 引语，不在 Business Outlook 区块内" + ("，且不带 approximately" if unqualified else "")])
    # What management added on the call and the release left out: kept as the
    # company's own words, never as a filed figure (the owner's rule for
    # call-only guidance), and the one inconsistency in them is named.
    if call:
        where = f"只在电话会上说过：{call['given_in']}"
        guidance_rows += [
            ["半导体收入", f"约 US${call['semiconductor_usd_bn']:.1f}B", "单点", where],
            ["非 AI 半导体收入", f"约 US${call['non_ai_semiconductor_usd_bn']:.1f}B", "单点",
             where + (f"；半导体减 AI 是 US${call['semiconductor_usd_bn'] - guidance['ai_semiconductor_revenue_usd_bn']:.1f}B，"
                      "与口头数不一致" if abs(call['semiconductor_usd_bn'] - guidance['ai_semiconductor_revenue_usd_bn']
                                          - call['non_ai_semiconductor_usd_bn']) > 0.05 else "")],
            ["基础设施软件收入", f"约 US${call['infrastructure_software_usd_bn']:.1f}B", "单点",
             where + (f"；低于本季实际的 US${isg_rev[-1]:,.0f}M"
                      if call["infrastructure_software_usd_bn"] * 1000 < isg_rev[-1] else "")],
            ["non-GAAP 毛利率", f"约 {call['gross_margin_pct']:.0f}%", "单点", where],
            ["资本开支", f"US${call['capital_expenditures_usd_bn']:.1f}B", "单点",
             where + f"；本季实际 US${capex[-1]:,.0f}M"],
        ]

    return {
        "schema_version": "quarterly-dashboard/avgo-v1",
        "page": {"slug": "avgo", "language": "zh-CN"},
        "company": {
            "ticker": "AVGO",
            "name": "Broadcom",
            "group": "semiconductor_ai",
            "accounting_standard": "US GAAP",
        },
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · AVGO",
        "title": f"Broadcom (AVGO)：{periods[-1]} 季报仪表盘",
        "subtitle": (
            f"截至 {ends[-1]} · 发布 {releases[-1]} · US GAAP · "
            f"{AUDIT_WORDS[latest['audit_status']]} · "
            f"11 月制财年，本站按自然年季度标注：本页 {periods[-1]} 即公司所称 {fiscal[-1]}"
        ),
        "headline": (
            # `headline` is written with `node.textContent`, so a tag here reaches
            # the reader as the literal characters `<b>`. Emphasis belongs in
            # `brief` or an exhibit's `note`, which are raw innerHTML.
            "；".join(headline_parts) + "。"
            + record_words
            + f"而指引是在被指引季度已经过了中位 {median_days:.0f} 天时才发布的。"
            + (f"本季{cn_count(len(subtractions))}处减法值得单独记：" + "；".join(subtractions) + "。"
               if subtractions else "")
        ),
        "brief": (
            f'<h4>本季{cn_count(len(articles))}条主线</h4><div class="takeaway-grid">'
            + "".join(articles)
            + '</div>'
        ),
        "source": source,
        "source_url": release_source["url"],
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": {
            "title": f"下季（本站 {guidance['period']}，公司 {guidance['fiscal_label']}）指引",
            "headers": ["指标", "指引", "形式", "出处"],
            "rows": guidance_rows,
            "note": (guidance["note"] + f" 该季于 {guidance['period_end']} 结束，预计 {guidance['expected_release']}发布。"
                     + (" 表里标「只在电话会上说过」的几行是管理层在电话会上补充的口径，新闻稿里没有，"
                        "照公司的说法列出、不当作申报数。" if call else "")),
        },
        "sections": [
            {
                "id": "settled",
                "title": "一、上季跟踪指标兑现了吗",
                "description": (
                    (f"本站对 Broadcom 的第一份季报分析是 {periods[-1]}，没有上季留下的跟踪指标可结算；"
                     "本节结算的是公司上季给出、本季到期的指引。"
                     if prior_facts["first"] else
                     f"先结算上季（本页 {periods[-2]}，公司 {fiscal[-2]}）那份本地分析稿留下的 "
                     f"{prior_facts['questions']} 条待验证问题与第 8 节的 "
                     f"{prior_facts['thresholds']} 条量化阈值"
                     + (f"（其中 {prior_facts['pending']} 条要等本季的 {form_now}）" if prior_facts["pending"] else "")
                     + "，再看公司自己的指引。")
                    + "Broadcom 每季在业绩新闻稿的 "
                    f"Business Outlook 区块给出下一季的{joined(formal_names)}，"
                    f"所以「有没有做到」在这里有{cn_count(record_years)}年的答案——"
                    "而这段记录里真正会变的，是公司愿意公布哪一种形式的指引。"
                ),
                "exhibits": settled_ex,
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": (
                    "按本季本地分析稿的结论排：收入与两个引擎、AI 那一条线、营业利润率的变化由什么构成、"
                    + ("软件收入里有多少是一次性确认的、" if upfront_chart else "")
                    + "自由现金流率里的时点红利、这笔现金去了哪里、"
                    f"{form_now} 里的采购承诺，以及营运资本。"
                    + (story_block["not_drawn"] if story_block and story_block.get("not_drawn") else "")
                ),
                "exhibits": highlight_ex,
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": (
                    (f"本季本地分析稿第 8.2 节的 {next_facts['rows']} 行观察指标，拆成 "
                     f"{next_facts['count']} 条数值阈值，逐条拿本季读数对下季的线，统一用「距阈值余量」口径；"
                     + (f"backstop、采购承诺、分部毛利率与合同负债四项读自 {reports[ends[-1]]['filed']} "
                        f"申报的 {form_now}。" if ends[-1] in reports else "")
                     + (f"其中 {next_facts['pending']} 条的本季读数只在 {form_now} 里，申报之前不画余量。"
                        if next_facts["pending"] else "")
                     + ((f"K4 的警示条件要求回购连续为零：本季为零，上季是 US${buyback[-2]:,.0f}M。"
                         if zero_streak == 1 else
                         f"K4 的警示条件要求回购连续为零：已连续{cn_count(zero_streak)}季为零。")
                        if zero_streak else "")
                     + liabilities_words
                     + (f"另有{cn_count(len(next_facts['unquantified']))}条没有数可画，原因写在总览图注与核对抽屉里。"
                        if next_facts["unquantified"] else ""))
                    if next_facts["count"] else "本季没有设定下季阈值。"
                ),
                "exhibits": next_ex,
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": (
                    "AVGO 专属的常规序列：两个引擎的分部利润率、GAAP 与自定义口径之间的缺口、"
                    "fab-lite 的资本强度、现金转化，以及 VMware 之后的去杠杆路径。"
                ),
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            (f"本页所有季度按自然年标注。Broadcom 财年 11 月初结束，故本页的 {periods[-1]} "
             f"是截至 {ends[-1]} 的季度，公司自己称之为 {fiscal[-1]}；"
             "映射规则为公司 FY 的 Q1→上一自然年 Q4、Q2→Q1、Q3→Q2、Q4→Q3，"
             "与本站 Synopsys 页（10 月制财年）用的是同一条规则。"
             "不统一成一种约定，跨公司的资本开支对照表就会把不同的三个月放在一起比较。"),
            (f"第一节的指引兑现组图（Exhibit {delivery_charts[0]['n']}–{delivery_charts[-1]['n']}）"
             "用的是同一批业绩 8-K 的 EX-99.1「Business Outlook」区块。"
             f"公司在这 {releases_examined} 份新闻稿里换过{cn_count(len(phases) - 1)}次指引形式："
             f"{phase_words(phases, record)}。"
             f"因此已完结的季度收入指引共 {finished_count} 条，"
             f"其中 {range_count} 条是区间、{point_count} 条是单点。"),
            (f"窗口内有 {sum(len(quarters) for _, quarters in unguided)} 个已申报季度从未被单独指引过"
             f"（{unguided_words(unguided)}），它们在偏离图上是空档而不是零。"
             f"这些只按财年给出的指引单列在核对抽屉的第 {gap_table_n} 张表里。"),
            (f"指引发布时点：公司在上一季业绩发布时才给出这一季的指引，"
             f"而那场发布落在被指引季度开始之后，中位数为 {quarter_days:.0f} 天里的第 {median_days:.0f} 天。"
             + ("所以「从未低于指引」不是一句纯粹的事前预测记录；" if never_below
                else "所以这份兑现记录不是纯粹的事前预测记录；")
             + "这条提醒印在每一张指引图上，而不是只放在这里。"),
            ("Adjusted EBITDA 与 non-GAAP 营业利润都是公司自定义口径（在 GAAP 基础上加回"
             "收购无形资产摊销、股权激励、重组与收购相关费用等）。"
             "每一对「指引 vs 实际」都在当时适用的同一套口径内部比较；"
             "长期水平序列一律用 GAAP，因为 GAAP 的定义在整个窗口内没有变过。"),
            *([("分部营业利润之和等于 non-GAAP 营业利润，这是本页几张分部图的前提，"
                f"并非假设：在分部附注给出分部营业利润的全部 {len(seg_rows)} 个季度里逐季精确相等"
                "（FY2019 及以前需把已停止披露的第三个分部 IP licensing 一并计入）。"
                "这条恒等式已写成测试。")] if identity_holds else []),
            ("财年第四季在 XBRL 里没有单独的季度事实，本页的第四季值取自该季业绩新闻稿；"
             f"分部数据的第四季则为该财年数减去前三季。两条路径在 {reconciled} 个完整财年上互相验证一致。"),
            ("AI 半导体收入不是公司的申报分部。本页相关数字出自各季业绩新闻稿的 CEO 引语，"
             "精度为 US$0.1B，其中一季公司只给了同比增速、没有给水平值（图上留空），"
             + "".join(f"另一季的措辞是「over ${ai['actual_usd_bn'][i]:.1f} billion」（下限而非点值）"
                       for i in floors[:1])
             + "。"
             f"这条口径与 Business Outlook 区块里的{cn_count(len(formal_names))}条正式指引不同级，"
             "本页分开画、不合并统计。"),
            (f"分部毛利率只从 {first_cost} 起有季度数（{cn_count(cost_points)}季）。公司在 FY2025 10-K 里"
             "第一次按 ASU 2023-07 披露分部成本，只有全年数；季度数从 FY2026 的 10-Q 开始，比较列带出上年同季，"
             "FY2025 第四季为 10-K 全年减前三季，四季相加与全年逐分相符。更早的季度公司没有披露，本页留空。"),
            ("自由现金流为自算值：经营现金流减去资本开支，与公司在新闻稿里印出的同名数字定义一致，"
             "逐季核对相符。"),
            "本页只发布公司披露值、可复算的简单派生值，以及明确标注的市场预期；D 标记代表 Derived / 自算。",
            "市场预期一律标注为「市场预期」并给出取数时点，不写卖方机构名，也不发布评级、目标价或估值。",
            *([f"Exhibit {settled_ex[1]['n']} 与 Exhibit {next_ex[0]['n']} 的阈值分别取自上季与本季本地分析稿的"
               "第 8 节，不是公司指引；前一张结算上季的线，后一张量本季读数离下季的线还有多远。"]
              if not prior_facts["first"] and next_ex else []),
            ("本页已知未接入：客户租赁 backstop 的当前敞口与会计处理（10-Q 只给全部 AI racks 部署之后的最大敞口"
             + (f"，{cn_count(len(backstop_points))}份 10-Q 都是约 {text_number('usd_m', backstop_points[-1])}"
                if backstop_points and len(set(backstop_points)) == 1 else "")
             + "，公允价值写的是 not material，构不成敞口路径）；AI 收入里 XPU 与网络芯片的拆分（只在电话会上以占比给出）；"
             "单一客户的收入占比与最大客户的份额（公司从不点名客户、也不披露单客户占比，"
             "第三方估计不在本页可发布范围内）；地区收入拆分（口径逐年变动，未按同一口径接续）；"
             "以及 FY2018 及以前的半导体/软件两分部拆分（当时的报告分部是按产品线划分的四个，不可接续）。"),
            "业绩电话会文字稿仅链接官方 IR 与 SEC 托管版本，公开仓不复制原件或逐字内容。",
        ],
        "footer": "AVGO quarterly results · 数据来自 Broadcom 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "avgo.js"), payload, "avgo")
    shell_dir = ROOT / "avgo"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("AVGO", "avgo"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(
        f"AVGO page: {charts} charts in {len(payload['sections'])} sections "
        f"+ {len(payload['tables'])} audit tables"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
