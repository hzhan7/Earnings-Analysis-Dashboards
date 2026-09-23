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
import math
import re
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


def trim(value: float, digits: int = 1) -> str:
    """``3.693`` → ``'3.7'``, ``50.0`` → ``'50'``."""
    text = f"{value:.{digits}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def usd(value: float, digits: int = 2) -> str:
    """``-1.91`` → ``'−US$1.91'``: the sign sits outside the currency."""
    return f"{'−' if value < 0 else ''}US${abs(value):.{digits}f}"


def fiscal_name(label: str) -> str:
    """``'FQ3-26'`` → ``'FY2026 Q3'``, the way the company names the quarter."""
    quarter, year = label[2], label[-2:]
    return f"FY20{year} Q{quarter}"


def fiscal_year_end(year: int) -> str:
    """Micron's year ends on the Thursday nearest 31 August (filer record 09-03).

    Computed from that rule rather than typed: FY2026 ends 2026-09-03, FY2027
    on 2027-09-02, and a page rolled into a new fiscal year has to say so
    without anyone remembering to.
    """
    import datetime
    anchor = datetime.date(year, 8, 31)
    offset = (3 - anchor.weekday()) % 7          # Thursday is weekday 3
    if offset > 3:
        offset -= 7
    return (anchor + datetime.timedelta(days=offset)).isoformat()


# Micron states price and volume moves only in bucketed words. The page never
# turns a bucket into a number; it only quotes the bucket and its direction.
_WORDED_MOVE = re.compile(r"(?:an?\s+)?(?P<bucket>\S.*?range)\s+(?P<verb>increase|decrease)", re.I)
_BIT_WORDS = {"low-single-digit": "低个位数", "mid-single-digit": "中个位数",
              "high-single-digit": "高个位数"}
_LEVEL = {"low": 1, "mid": 2, "high": 3}


def worded_move(text: str | None) -> tuple[str, str] | None:
    """「a low-60% range increase in …」→ ``('low-60% range', '上升')``."""
    match = _WORDED_MOVE.search(text or "")
    if not match:
        return None
    return match.group("bucket"), "上升" if match.group("verb").lower() == "increase" else "下降"


def bucket_rank(bucket: str) -> tuple[int, int]:
    """Order ``low-60% range`` below ``mid-80% range``: by the number, then the word."""
    level = _LEVEL.get(bucket.split("-", 1)[0], 0)
    number = re.search(r"(\d+)%", bucket)
    return (int(number.group(1)) if number else 0, level)


SOURCE_8K = (
    "指引区间来自各季业绩 8-K 的 EX-99.1 新闻稿里那张 Business Outlook 表 —— "
    "公司在同一张表里用同一种句式给出下一季的收入、毛利率、营业费用与摊薄每股收益，"
    "GAAP 与 non-GAAP 两栏并列；实际值来自随后一季 8-K 的合并损益表与 GAAP/non-GAAP 对账表。"
)

# The guided record's lag is measured in days into a 13-week quarter.
QUARTER_DAYS = 91


def lag_facts(record: dict) -> tuple[int, int, int]:
    lags = record["publication_lag_days"]
    return min(lags), max(lags), statistics.median_low(lags)


def timing(record: dict) -> str:
    """Micron reports about four weeks after its quarter ends and guides the
    quarter that has already started, so this record is not an ex-ante one.
    Named on every chart in the group, the way TJX's is."""
    low, high, _ = lag_facts(record)
    return f"该季<b>开始后 {low}–{high} 天</b>"


def lag_note(record: dict) -> str:
    low, high, middle = lag_facts(record)
    return (
        "<b>先读这一句，再读命中率。</b>Micron 的下一季指引是随上一季业绩一起发布的，"
        "而它在季末约四周后发业绩，所以这张 Outlook 表落在<b>它所指引的那个季度之内</b>："
        f"本记录里最早的一次是第 {low} 天、最晚的一次是第 {high} 天、中位数第 {middle} 天，"
        f"即公司给出区间时该季通常已经过去{cn_fraction(low / QUARTER_DAYS)}"
        f"到{cn_fraction(high / QUARTER_DAYS)}。"
        "这不是一份事前预测。"
    )


def cn_more_than(value: float) -> str:
    """``117.2`` → 「一百多」, ``25.7`` → 「二十多」: the round figure a sentence rests on."""
    if value >= 100:
        return f"{cn_count(int(value // 100))}百多"
    if value >= 10:
        return f"{cn_count(int(value // 10) * 10)}多"
    return f"{cn_count(int(value))}个多"


def partial_fiscal_year(staging: dict) -> dict | None:
    """The fiscal year the latest quarter sits in, while the 10-K record lacks it.

    The fifteen-year chart only draws years a 10-K has printed, so the quarters
    of the running year are summed here for the one sentence that says what
    the chart leaves out.
    """
    labels = staging["fiscal_labels"]
    year = 2000 + int(labels[-1][-2:])
    if any(row["fiscal_year"] == year for row in staging["annual_cycle"]):
        return None
    fin = staging["financials"]
    inside = [i for i, label in enumerate(labels) if 2000 + int(label[-2:]) == year]
    revenue = sum(fin["revenue_usd_m"][i] for i in inside)
    gross = sum(fin["gross_margin_usd_m"][i] for i in inside)
    return {"fiscal_year": year, "quarters": len(inside), "revenue_usd_m": revenue,
            "gross_margin_pct": gross / revenue * 100}


def yi(value_usd_m: float) -> str:
    """US$ millions in 亿: ``5000`` → ``'50'``, ``422`` → ``'4.22'``, ``100000`` → ``'1,000'``."""
    value = value_usd_m / 100
    return f"{value:,.0f}" if value == int(value) else trim(value, 2)


def joined(names: list[str]) -> str:
    """「毛利率与营业费用」「收入、毛利率与每股收益」."""
    return names[0] if len(names) == 1 else "、".join(names[:-1]) + "与" + names[-1]


def half_and_half(above: int, total: int) -> bool:
    """Whether "above the band" and "not above it" split roughly evenly."""
    return abs(above - (total - above)) <= max(1, round(total * 0.1))


def shift_quarter(period: str, step: int) -> str:
    """``'Q2 2026'`` moved by ``step`` calendar quarters: ``+1`` → ``'Q3 2026'``."""
    quarter, year = period.split()
    index = int(year) * 4 + int(quarter[1]) - 1 + step
    return f"Q{index % 4 + 1} {index // 4}"


def usd_band(value_usd_m: float) -> str:
    """A guidance half-width the way the release prints it: ``750`` → ``'US$750M'``,
    ``1000`` → ``'US$1.0B'``."""
    return f"US${value_usd_m:,.0f}M" if value_usd_m < 1000 else f"US${value_usd_m / 1000:.1f}B"


# ── section one, first half: what last quarter left for this one ───────────
# The owner's local analysis of each quarter ends with follow-up questions and
# a table of observation metrics with thresholds. The next quarter's analysis
# closes the questions (its section 0); the thresholds are settled here against
# this quarter's filed numbers. What was asked and where the line was drawn are
# facts about that analysis, so they live in two period-stamped series blocks;
# every reading the settlement names is computed from the arrays below, so a
# sentence in a block and a number on a chart cannot drift apart.
CLOSURE_ORDER = ("已验证", "部分验证", "被证伪", "仍未披露")


def settlement_blocks(staging: dict) -> tuple[dict | None, dict | None]:
    """This quarter's follow-up closure and last quarter's thresholds, or None.

    Both describe one quarter and are stamped with it (``board.stamped_block``);
    both close what was set one quarter earlier, so ``set_in`` has to be the
    page's previous quarter -- a block carried over from an older roll would
    otherwise settle another quarter's list under this quarter's label.
    """
    periods = staging["periods"]
    blocks = []
    for key in ("followup_closure", "prior_kpi_settlement"):
        block = stamped_block(staging, key, periods[-1])
        if block is not None and block["set_in"] != periods[-2]:
            raise ValueError(f"series block `{key}` settles what was set in {block['set_in']!r}, "
                             f"but the quarter before {periods[-1]!r} is {periods[-2]!r}")
        blocks.append(block)
    return blocks[0], blocks[1]


def settlement_values(staging: dict, prior: dict | None) -> dict[str, str]:
    """Every figure the one-quarter settlement sentences cite, from the arrays."""
    periods = staging["periods"]
    fin = staging["financials"]
    record = staging["quarterly_guidance_history"]
    outlook = staging["next_quarter_guidance"]
    units = staging["business_units"]
    following = shift_quarter(periods[-1], 1)
    if record["quarters"][-1] != following or outlook["period_label"] != following:
        raise ValueError(f"the guidance record ends at {record['quarters'][-1]!r} and the outlook "
                         f"is for {outlook['period_label']!r}, but the quarter after "
                         f"{periods[-1]!r} is {following!r}: add this release's outlook with the roll")
    if units["quarters"][-1] != periods[-1]:
        raise ValueError(f"business units end at {units['quarters'][-1]!r}, not {periods[-1]!r}")
    this = record["quarters"].index(periods[-1])
    guide_rev = record["guide_non_gaap_revenue_usd_m"][this]

    def margin_guide(index: int) -> str:
        """One quarter's non-GAAP margin guide as the release printed it."""
        guided = record["guide_non_gaap_gross_margin_pct"][index]
        if record["guide_non_gaap_gross_margin_pct_is_point"][index]:
            return f"约 {guided:.0f}%"
        return f"{guided:.1f}% ± {record['guide_non_gaap_gross_margin_pct_band'][index]:.1f}%"

    values = {
        "revenue": f"US${fin['revenue_usd_m'][-1] / 1000:.2f}B",
        "margin": f"{fin['non_gaap_gross_margin_pct'][-1]:.1f}%",
        "prior_guide_revenue": (
            f"约 US${guide_rev / 1000:.1f}B" if record["guide_non_gaap_revenue_usd_m_is_point"][this]
            else f"US${guide_rev / 1000:.1f}B ± "
                 f"{usd_band(record['guide_non_gaap_revenue_usd_m_band'][this])}"),
        "prior_guide_margin": margin_guide(this),
        "next_guide": (f"US${outlook['revenue_usd_m'] / 1000:.1f}B ± "
                       f"{usd_band(outlook['revenue_band_usd_m'])}"),
        "next_guide_qoq": f"{pct_change(outlook['revenue_usd_m'], fin['revenue_usd_m'][-1]):+.1f}%",
        "cmbu_margin": f"{units['CMBU_gross_margin_pct'][-1]:.0f}%",
        "cdbu_margin": f"{units['CDBU_gross_margin_pct'][-1]:.0f}%",
        "cmbu_vs_cdbu": ("低于" if units["CMBU_gross_margin_pct"][-1] < units["CDBU_gross_margin_pct"][-1]
                         else "高于" if units["CMBU_gross_margin_pct"][-1] > units["CDBU_gross_margin_pct"][-1]
                         else "等于"),
        "release": outlook["published_on"],
        "prior_period": periods[-2],
        "next_guide_margin": margin_guide(len(record["quarters"]) - 1),
    }
    agreements = stamped_block(staging, "supply_agreements", periods[-1])
    for item in (agreements or {}).get("items", []):
        if item["metric"].startswith("剩余履约义务"):
            values["rpo_company"] = f"US${item['company_usd_m'] / 1000:,.0f}B"
    spoken = stamped_block(staging, "spoken_outlook", periods[-1])
    if spoken:
        values["sca_signed"] = str(spoken["supply_agreements_signed"])
        values["capex_year"] = f"FY{spoken['capex_fiscal_year']}"
        values["capex_words"] = spoken["capex_words"]
    asp = worded_move(staging["technology"]["dram_asp_text"][-1])
    if asp:
        values["dram_asp_words"] = f"{asp[0]} {'increase' if asp[1] == '上升' else 'decrease'}"
    # Figures the analysis itself states (last quarter's "当前 1 份") and no
    # array carries: named by the series block, so the builder knows no names.
    for name, text in (prior or {}).get("story_values", {}).items():
        if name in values:
            raise ValueError(f"story value {{{name}}} is computed from the series; do not type it")
        values[name] = str(text)
    return values


def prior_actual(staging: dict, entry: dict) -> float:
    """This quarter's reading of one of last quarter's quantified thresholds.

    Keyed by id and never typed into the series: a hand-keyed reading is where
    the other pages' settlement blocks went wrong (a rate keyed as 43.4 against
    a computed 43.3 moved the printed headroom).
    """
    if "actual" in entry or "current" in entry:
        raise ValueError(f"threshold `{entry['id']}` is read from the series; remove its typed value")
    fin = staging["financials"]
    known = {
        "revenue": lambda: fin["revenue_usd_m"][-1] / 1000,
        "gross_margin": lambda: fin["non_gaap_gross_margin_pct"][-1],
        # The guided midpoint for the quarter after this one, from the outlook
        # this quarter's release printed.
        "next_guide": lambda: staging["next_quarter_guidance"]["revenue_usd_m"] / 1000,
        # Mapped now because this quarter's section three sets a DSO line, so
        # next quarter settles it -- a roll then edits the series only.
        "dso": lambda: staging["balance_sheet"]["dso_days"][-1],
    }
    if entry["id"] not in known:
        raise ValueError(f"threshold `{entry['id']}` has no series on this page: map it in "
                         "build/mu.py `prior_actual`")
    return known[entry["id"]]()


# What a line settled by the company's words can come to. "已越线" is the only
# one that counts as crossed in a title; "无法判定" is for words that bound a
# figure on the wrong side (a "higher than X" can prove a ceiling crossed, never
# that it held).
WORDED_VERDICTS = ("已越线", "未触发", "守住", "无法判定")


def worded_settlements(prior: dict) -> list[tuple[dict, dict]]:
    """Last quarter's lines that only the company's words settle, as recorded.

    Each entry carries its own `settled_by_wording` block -- the verdict, the
    company's words and where they were said -- in the period-stamped series
    block. The builder reads it and decides nothing, so a roll that brings a
    new kind of worded line edits the series file only. (It used to keep a
    table keyed by metric that decided two of them in code.)
    """
    settled = []
    for entry in prior.get("by_words", []):
        record = entry.get("settled_by_wording") or {}
        missing = [key for key in ("verdict", "quote", "source") if not record.get(key)]
        if missing:
            raise ValueError(f"worded threshold `{entry['id']}`: settled_by_wording lacks {missing}")
        if record["verdict"] not in WORDED_VERDICTS:
            raise ValueError(f"worded threshold `{entry['id']}`: verdict {record['verdict']!r} "
                             f"is not one of {WORDED_VERDICTS}")
        settled.append((entry, record))
    return settled


def settlement_charts(staging: dict, closure: dict | None, prior: dict | None,
                      values: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """(a) the follow-up closure and (b) last quarter's thresholds, settled.

    Returns the exhibits (closure bars, the headroom overview, then one
    threshold line per quantified metric that has a history on this page) and
    the two audit tables behind them.
    """
    periods = staging["periods"]
    labels = [compact_period(period) for period in periods]
    fin = staging["financials"]
    charts: list[dict] = []
    tables: list[dict] = []

    if closure is not None:
        verdicts = [item["verdict"] for item in closure["items"]]
        if closure["labels"] != list(CLOSURE_ORDER) or set(verdicts) - set(CLOSURE_ORDER):
            raise ValueError("followup_closure: labels must be " + "/".join(CLOSURE_ORDER)
                             + " and every verdict one of them")
        counts = [verdicts.count(label) for label in closure["labels"]]
        by_label = dict(zip(closure["labels"], counts))
        parts = [f"{count} 条{label}" for label, count in zip(closure["labels"], counts) if count]
        if not by_label["被证伪"]:
            parts.append("没有一条被证伪")
        story = {**values, "verified_n": cn_count(by_label["已验证"]),
                 "partial_n": cn_count(by_label["部分验证"])}
        charts.append({
            "kind": "bars_labeled",
            "title": f"上季 {len(verdicts)} 条待验证问题：" + "、".join(parts),
            "xlabels": closure["labels"],
            "values": counts,
            "legend": "问题条数",
            "fmt": "f0",
            "yfmt": "f0",
            "label_fmt": "f0",
            "ylab": "条",
            "note": fill_story(closure["note"], story),
            "src_extra": (
                f"问题清单来自上季（{periods[-2]}）本地分析稿的 follow-up，逐条判定取自本季本地分析稿"
                f"第 0 节；读数取自本季业绩新闻稿、10-Q 与 {values['release']} 业绩电话会书面发言稿。"
            ),
        })
        tables.append({
            "title": f"上季 {len(verdicts)} 条待验证问题：逐条闭环",
            "headers": ["#", "上季问题", "本季读数", "判定"],
            "rows": [[str(index), fill_story(item["question"], story),
                      fill_story(item["reading"], story), item["verdict"]]
                     for index, item in enumerate(closure["items"], 1)],
        })

    if prior is None:
        return charts, tables

    entries = [{**entry, "actual": prior_actual(staging, entry)} for entry in prior["quantified"]]
    story = dict(values)

    def filled(entry: dict, text: str) -> str:
        """A block sentence with its placeholders, the entry's own lines included.

        `settled_guide_margin` is the margin guide of the quarter a line
        settles: here, this quarter's (given last quarter). A rule copied over
        from last quarter's `next_kpi` therefore reads the same in both places.
        """
        names = {**story, "settled_guide_margin": story["prior_guide_margin"]}
        for key in ("threshold", "lower_threshold"):
            if key in entry:
                names[key] = unit_text(entry["unit"], entry[key])
        return fill_story(text, names)

    def rule_of(entry: dict) -> str:
        return filled(entry, entry["rule"])

    def crossed(entry: dict) -> bool:
        broken = headroom(entry["direction"], entry["threshold"], entry["actual"]) < 0
        # The guide line had a second trigger: a guided sequential decline.
        if entry["id"] == "next_guide":
            broken = broken or entry["actual"] * 1000 < fin["revenue_usd_m"][-1]
        return broken

    broken = [entry for entry in entries if crossed(entry)]
    worded = worded_settlements(prior)
    worded_crossed = [entry for entry, record in worded if record["verdict"] == "已越线"]
    total = len(entries) + len(worded) + len(prior.get("unsettled", []))

    def reading_of(entry: dict, record: dict) -> str:
        """The recorded reading, then the company's own words and where."""
        return ((filled(entry, record["reading"]) + "，" if record.get("reading") else "")
                + f"{record['source']}的原话是「{record['quote']}」")

    title = (f"上季 {len(entries)} 条量化阈值："
             + ("全部守住" if not broken else
                f"{len(entries) - len(broken)} 条守住、{len(broken)} 条被击穿")
             + "".join(f"；{entry['metric']}按公司措辞已越过 "
                       f"{unit_text(entry['unit'], entry['threshold'])} 线"
                       if "threshold" in entry else f"；{entry['metric']}按公司措辞已越线"
                       for entry in worded_crossed))
    aside = []
    for entry, record in worded:
        aside.append(f"<b>{entry['metric']}</b>（{rule_of(entry)}）：{reading_of(entry, record)}，"
                     f"<b>{record['verdict']}</b>"
                     + ("；" + filled(entry, entry["why_not_charted"])
                        if entry.get("why_not_charted") else "")
                     + "。")
    for entry in prior.get("unsettled", []):
        aside.append(f"<b>{entry['metric']}</b>（{rule_of(entry)}）："
                     + filled(entry, entry["reason"]) + "。")
    guide = next((entry for entry in entries if entry["id"] == "next_guide"), None)
    overview = headroom_exhibit(
        title,
        entries,
        "actual",
        (
            f"正值 = 仍在安全侧。上季本地分析稿第 8 节一共{cn_count(total)}条观察指标，"
            f"能用本季的公司数字结算成一个余量的是这{cn_count(len(entries))}条"
            + (f"；其中下季收入指引的中值 US${guide['actual']:.1f}B 相对本季收入环比 "
               f"{values['next_guide_qoq']}，阈值的另一半（「环比下降」）"
               + ("也没有触发" if guide["actual"] * 1000 >= fin["revenue_usd_m"][-1] else "已经触发")
               + "，它的逐季走势就是本节后面的收入指引记录（Exhibit {EX_REV_RANGE} 最右一格）"
               if guide else "")
            + "。" + (f"另外{cn_count(len(aside))}条不进这张图。" + "".join(aside) if aside else "")
        ),
        src_extra=("阈值、方向与触发动作逐字取自上季本地分析稿第 8 节，不是公司指引；"
                   "本季读数取自业绩新闻稿与 10-Q"
                   + (f"；按公司措辞结算的{cn_count(len(worded))}条，判定、原话与出处逐条写在图注里"
                      if worded else "")
                   + "。"),
    )
    overview["ref"] = "EX_PRIOR_HEADROOM"
    charts.append(overview)

    dso_start = continuous_tail(staging["balance_sheet"]["dso_days"])
    tracked = {
        "revenue": (labels, rounded([v / 1000 for v in fin["revenue_usd_m"]]), "usd1", "US$B",
                    "季度收入", values["prior_guide_revenue"]),
        "gross_margin": (labels, rounded(fin["non_gaap_gross_margin_pct"]), "pct1",
                         "non-GAAP 毛利率", "non-GAAP 毛利率", values["prior_guide_margin"]),
        # No guidance exists for receivables, so no guided figure is named.
        "dso": (labels[dso_start:], rounded(staging["balance_sheet"]["dso_days"][dso_start:]),
                "f1", "天", "DSO（自算）", None),
    }
    for entry in entries:
        if entry["id"] not in tracked:
            continue
        xlabels, series, fmt, ylab, actual_name, guided = tracked[entry["id"]]
        margin = headroom(entry["direction"], entry["threshold"], entry["actual"])
        safe = ((lambda v: v >= entry["threshold"]) if entry["direction"] == "up"
                else (lambda v: v <= entry["threshold"]))
        before = [v for v in series[:-1] if v is not None]
        unsafe_before = sum(1 for v in before if not safe(v))
        if unsafe_before == len(before) and safe(series[-1]):
            record = (f"这条线此前 {len(before)} 季全部落在阈值的不安全一侧，"
                      f"本季是 {len(series)} 季里第一次站到安全侧。")
        else:
            record = f"这条线此前 {len(before)} 季里有 {unsafe_before} 季落在阈值的不安全一侧。"
        side = "上方" if entry["direction"] == "up" else "下方"
        charts.append(threshold_exhibit(
            f"{entry['metric']}：{'守住' if not crossed(entry) else '已击穿'}上季阈值 "
            f"{unit_text(entry['unit'], entry['threshold'])}",
            xlabels,
            series,
            entry["threshold"],
            fmt=fmt,
            ylab=ylab,
            actual_name=actual_name,
            threshold_name=f"上季阈值 {unit_text(entry['unit'], entry['threshold'])}（安全侧在{side}）",
            note=(
                f"阈值 {unit_text(entry['unit'], entry['threshold'])}，本季 "
                f"{unit_text(entry['unit'], entry['actual'])}，余量 {margin:+.1f}%。"
                + (f"上季给这一季的指引：{guided}。" if guided else "") + record
                + f"上季的触发条件：{rule_of(entry)}。"
            ),
            src_extra=("实际值取自各季业绩 8-K EX-99.1；阈值取自上季本地分析稿第 8 节，不是公司指引。"),
        ))

    rows = []
    for entry in entries:
        rows.append([entry["metric"], rule_of(entry),
                     "高于阈值为安全" if entry["direction"] == "up" else "低于阈值为安全",
                     unit_text(entry["unit"], entry["actual"]),
                     f"{headroom(entry['direction'], entry['threshold'], entry['actual']):+.1f}%",
                     "已击穿" if crossed(entry) else "守住"])
    for entry, record in worded:
        rows.append([entry["metric"], rule_of(entry), "—", reading_of(entry, record), "—",
                     record["verdict"] + "（按公司措辞，不入余量图）"])
    for entry in prior.get("unsettled", []):
        rows.append([entry["metric"], rule_of(entry), "—", "—", "—", "无法用一手数据结算"])
    tables.append({
        "title": f"上季第 8 节{cn_count(total)}条观察指标：本季结算（原单位）",
        "headers": ["指标", "上季触发条件", "方向", "本季读数", "余量 D", "结算"],
        "rows": rows,
    })
    return charts, tables


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
    rev_below_labels = [compact_period(quarters[i]) for i in finished
                        if revenue_lo[i] is not None and revenue_actual[i] < revenue_lo[i]]
    rev_low_dev, rev_low_index = min((pct_change(revenue_actual[i], revenue_mid[i]), i)
                                     for i in finished)
    gm_n, gm_above, gm_inside, gm_below = tally(margin_lo, margin_hi, margin_actual)
    last_eight = finished[-8:]
    recent_above = sum(1 for i in last_eight if margin_actual[i] > margin_hi[i])
    recent_run = 0
    while (recent_run < len(finished)
           and margin_actual[finished[-1 - recent_run]] > margin_hi[finished[-1 - recent_run]]):
        recent_run += 1
    eps_n, eps_above, eps_inside, eps_below = tally(eps_lo, eps_hi, eps_actual)

    # the single worst quarter of the record, recounted rather than recalled
    gm_gaps = [(margin_actual[i] - margin_mid[i], i) for i in finished]
    worst_gap, worst_index = min(gm_gaps)
    best_gap, best_index = max(gm_gaps)
    # how far apart the worst miss and the best beat sit, in years
    swing_years = math.ceil(abs(best_index - worst_index) / 4)

    # The scale argument for drawing the dollar band short: the smallest
    # reported quarter against the largest guided one, and the band the early
    # record was published with.
    smallest = min(record["actual_revenue_usd_m"][i] for i in finished) / 1000
    largest = max(v for v in record["guide_non_gaap_revenue_usd_m"] if v is not None) / 1000
    scale = largest / smallest
    scale_words = ("十几倍" if 10 <= scale < 20 else
                   f"{cn_count(int(scale // 10) * 10)}多倍" if scale >= 20 else
                   f"{cn_count(int(scale))}倍多")
    early_band = record["guide_non_gaap_revenue_usd_m_band"][0]

    kpi = {entry["id"]: entry for entry in next_kpi_block(staging)["quantified"]}
    gm_line = kpi["gross_margin"]["threshold"]
    next_gm = staging["next_quarter_guidance"]["non_gaap_gross_margin_pct"]
    eps_done = [eps_actual[i] for i in finished if eps_actual[i] is not None]

    revenue_band_chart = delivery_band(
        "EX_REV_RANGE", "收入", labels[window], revenue_lo[window], revenue_hi[window],
        revenue_actual[window],
        fmt="usd1", ylab="US$B", unit="US$B", venue="业绩发布",
        scope=f"（本图仅近 {BAND_WINDOW} 季）",
        timing=timing(record),
        src_extra=SOURCE_8K,
        extra_note=(
            lag_note(record)
            + f"<b>这张只画最近 {BAND_WINDOW} 季，不是数据缺失</b>：本页的指引记录一路回到 "
            f"{quarters[0].split()[1]} 年，"
            f"而收入在这段时间从 US${trim(smallest)}B 长到 US${trim(largest)}B，"
            f"{scale_words}的量级差放在一根线性美元轴上，"
            f"早年那些 ±US${early_band:,.0f}M 的区间会被压成几个像素。"
            "完整 {full} 季的同一问题改用与量级无关的口径回答，见 Exhibit {EX_REV_DEV}。"
        ).replace("{full}", str(rev_n)),
    )
    revenue_dev_chart = midpoint_deviation(
        "EX_REV_DEV", "收入", quarters, revenue_lo, revenue_hi, revenue_actual,
        mode="pct", window=len(finished), label=compact_period, bar_labels=False,
        src_extra=SOURCE_8K + "偏离为实际收入除以指引中值的自算值。",
        # This note used to say the record was "the opposite of the other
        # multi-guide pages here" with "long tails on both sides". Neither held:
        # Intel's revenue record splits 13 above / 14 inside the same way, and
        # the downside tail is one quarter. So it states only this record.
        extra_note=(
            f"<b>这是这份指引记录里最该先读的一张。</b>{rev_n} 个已完结季里，"
            f"{rev_above} 季高于指引区间上限、{rev_inside} 季落在区间内、{rev_below} 季跌破下限 —— "
            + ("高于上限与没有高于上限的接近一半一半，收入指引不是一条每季都被越过的底线。"
               if half_and_half(rev_above, rev_n)
               else f"高于上限的占 {round(rev_above / rev_n * 100)}%。")
            + ((f"跌破下限的只有 {rev_below_labels[0]}（相对中值 {rev_low_dev:+.1f}%）。"
                if rev_below_labels == [compact_period(quarters[rev_low_index])] else
                f"跌破下限的是 {'、'.join(rev_below_labels)}；相对中值向下最深的一次是 "
                f"{compact_period(quarters[rev_low_index])} 的 {rev_low_dev:+.1f}%。")
               if rev_below_labels else "")
        ),
    )

    margin_band_chart = delivery_band(
        "EX_GM_RANGE", "non-GAAP 毛利率", labels, margin_lo, margin_hi, margin_actual,
        fmt="pct0", ylab="non-GAAP 毛利率", unit="%", venue="业绩发布",
        timing=timing(record),
        src_extra=(SOURCE_8K + "实际 non-GAAP 毛利率 = 对账表的 non-GAAP 毛利 ÷ 当季收入 D。"),
        extra_note=(
            "<b>这条线的形状就是本页存在的理由。</b>"
            f"{gm_n} 个已完结季里 {gm_above} 季穿出上限、{gm_inside} 季落在区间内、"
            f"{gm_below} 季跌破下限；"
            f"而跌破的幅度和穿出的幅度完全不是一个量级 —— 最差的一次是 "
            f"{compact_period(quarters[worst_index])}，公司指引 {margin_mid[worst_index]:.1f}%、"
            f"报出来 {margin_actual[worst_index]:.1f}%，差 {abs(worst_gap):.1f} 个百分点。"
            f"最好的一次是 {compact_period(quarters[best_index])} 的 {signed(best_gap, 1, 'pp')}。"
            f"<b>同一家公司、同一张 Outlook 表、同一种句式，{cn_count(swing_years)}年之内既能差"
            f"{cn_count(round(abs(worst_gap)))}个百分点，"
            f"也能好{cn_count(round(best_gap))}个百分点。</b>"
            # Counted rather than asserted: two of the last eight were not above.
            f"只看最近 8 季，{recent_above} 季穿出上限"
            + (f"、最近{cn_count(recent_run)}季连续穿出" if recent_run >= 2 else "")
            + ("，看到的会是一家不断超越自己指引的公司" if recent_above * 4 >= len(last_eight) * 3 else "")
            + "；这条完整的线说的是别的事。"
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
            f"一根柱子就把其余{cn_count(gm_n - 1)}根压平了。"
            # The 84% line is the local analysis's, not a figure this page
            # derived from the chart -- it used to say 「本页据此」.
            f"本季本地分析稿把下季 non-GAAP 毛利率的警戒线设在 {gm_line:.1f}%（公司指引约 {next_gm:.0f}%），"
            "见 Exhibit {EX_GM_THRESHOLD}。"
        ),
    )

    eps_band_chart = delivery_band(
        "EX_EPS_RANGE", "non-GAAP 每股收益", labels[window], eps_lo[window], eps_hi[window],
        eps_actual[window],
        fmt="usd2", ylab="US$/股", unit="US$", venue="业绩发布",
        scope=f"（本图仅近 {BAND_WINDOW} 季）",
        timing=timing(record),
        src_extra=SOURCE_8K,
        extra_note=(
            f"完整记录里 {eps_n} 季有 {eps_above} 季高于指引上限、{eps_inside} 季落在区间内、"
            f"{eps_below} 季跌破下限，是四个指引数字里最偏向一侧的一个；"
            f"它偏向哪一侧由哪条腿决定，见 Exhibit {{EX_LEGS}}。同样只画近 {BAND_WINDOW} 季：每股收益在整段记录里从 "
            f"{usd(min(eps_done))} 到 {usd(max(eps_done))}。"
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

    def leading_leg(index: int) -> str:
        sizes = {"revenue": abs(revenue_leg[index]), "margin": abs(margin_leg[index]),
                 "opex": abs(opex_leg[index])}
        return max(sizes, key=sizes.get)

    margin_led = sum(1 for index in range(len(total)) if leading_leg(index) == "margin")
    revenue_run = 0
    while revenue_run < len(total) and leading_leg(len(total) - 1 - revenue_run) == "revenue":
        revenue_run += 1

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
            # This used to say the margin leg "decides" every quarter and then
            # cite the biggest one -- whose +7.9B was +6.4B revenue leg. Both
            # halves are now counted.
            f"{len(total)} 季里有 {margin_led} 季是金色的毛利率腿最大"
            + (f"；但最近{cn_count(revenue_run)}季不是 —— 窗口内最大的一次 {leg_labels[biggest]} 的 "
               f"{total[biggest]:+.1f}B 里，收入腿 {revenue_leg[biggest]:+.1f}B、"
               f"毛利率腿 {margin_leg[biggest]:+.1f}B，这一轮超额主要是收入超出了指引。"
               if revenue_run and biggest >= len(total) - revenue_run else
               f"，窗口内最大的一次是 {leg_labels[biggest]} 的 {total[biggest]:+.1f}B，"
               f"其中毛利率腿 {margin_leg[biggest]:+.1f}B。")
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
        "同一个问题的百分点口径在 Exhibit {EX_GM_DEV} 上。"
        # It used to say the EPS miss or beat is "almost entirely" the margin
        # leg; the last two quarters are revenue-leg quarters, so it is counted.
        f"每股收益偏离由哪条腿决定：{len(total)} 季里 {margin_led} 季是毛利率腿最大"
        + (f"，最近{cn_count(revenue_run)}季是收入腿" if revenue_run else "")
        + "（见 Exhibit {EX_LEGS}）。"
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

    # The latest 10-Q's own bucketed words for price and volume, quoted.
    dram_asp = worded_move(tech["dram_asp_text"][-1])
    dram_bit = worded_move(tech["dram_bit_text"][-1])
    nand_asp = worded_move(tech["nand_asp_text"][-1])
    nand_bit = worded_move(tech["nand_bit_text"][-1])
    quoted = (f"「DRAM 平均售价{dram_asp[1]} {dram_asp[0]}、出货位元{dram_bit[1]} {dram_bit[0]}」"
              if dram_asp and dram_bit else "")

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
            f"{quoted}。"
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
    record_quarter = revenue[-1] == max(v for v in revenue if v is not None)
    share_word = "下滑" if dram_share[-1] < dram_share[-2] else "上升"
    if dram_asp and nand_asp and dram_bit and nand_bit and {dram_asp[1], nand_asp[1],
                                                            dram_bit[1], nand_bit[1]} == {"上升"}:
        bits = sorted({dram_bit[0].split(" ")[0], nand_bit[0].split(" ")[0]},
                      key=lambda word: _LEVEL.get(word.split("-", 1)[0], 0))
        bit_words = "到".join(_BIT_WORDS.get(word, word) for word in bits)
        price_words = (
            f"公司口径里 NAND 的售价涨幅（{nand_asp[0]}）"
            f"{'高于' if bucket_rank(nand_asp[0]) > bucket_rank(dram_asp[0]) else '不高于'} "
            f"DRAM（{dram_asp[0]}），而两者的出货位元都只是{bit_words}的增长。"
        )
    else:
        price_words = ""
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
        "ylab": "US$B", "ylab2": "%",
        "note": (
            "<b>三段之和逐季等于合并损益表的收入，差额为零</b> —— "
            "这三行是 10-Q 收入注释里印出来的美元数（Revenue by Technology），"
            "不是用百分比乘总额倒推的。"
            f"最近一季 NAND 收入环比 {signed(pct_change(nand[-1], nand[-2]), 0)}、"
            f"DRAM 环比 {signed(pct_change(dram[-1], dram[-2]), 0)}，"
            f"所以金色的 DRAM 占比线在{'收入创纪录的' if record_quarter else ''}同一季"
            f"<b>{share_word}</b>："
            f"{dram_share[-2]:.1f}% → {dram_share[-1]:.1f}%。"
            + price_words
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
            f"<b>这条序列只有{cn_count(len(units['quarters']))}个季度，而且不会更长。</b>"
            f"公司从 {units['first_printed_in']} 那份业绩稿起"
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

    cm, cd, mc = (units["CMBU_gross_margin_pct"], units["CDBU_gross_margin_pct"],
                  units["MCBU_gross_margin_pct"])
    led = 0
    while led < len(cm) and cm[led] >= max(cd[led], mc[led]):
        led += 1
    trailing = [cm[i] < min(cd[i], mc[i]) for i in range(led, len(cm))]
    if led == len(cm):
        lead_words = f"{cn_count(len(cm))}个季度里 CMBU 每一季都领先。"
    elif led == 0:
        lead_words = f"{cn_count(len(cm))}个季度里 CMBU 一季都没有领先过。"
    else:
        lead_words = (f"{cn_count(len(cm))}个季度里 CMBU 在前{cn_count(led)}季领先，"
                      + ("此后一路被另外两条超过。" if all(trailing) else "此后被反超。"))
    # The chart's claim is that the HBM-heavy unit is not the most profitable;
    # stated only while this quarter's three printed margins say so.
    below_both = cm[-1] < min(cd[-1], mc[-1])
    if below_both and cd[-1] == mc[-1]:
        peers = f"低于核心数据中心与移动客户端的 {cd[-1]:.0f}%"
    elif below_both:
        peers = f"低于核心数据中心的 {cd[-1]:.0f}% 与移动客户端的 {mc[-1]:.0f}%"
    else:
        peers = f"核心数据中心 {cd[-1]:.0f}%、移动客户端 {mc[-1]:.0f}%"
    unit_margin = {
        "ref": "EX_BU_GM",
        "kind": "lines_endlabels",
        "title": (
            f"业务单元毛利率：HBM 最重的云内存 {cm[-1]:.0f}%，{peers}"
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
            ("<b>这一张悄悄证伪了「HBM = 最高利润」的直觉。</b>"
               f"承载 HBM 与高性能云 DRAM 的 CMBU 毛利率 {cm[-1]:.0f}%，"
               f"低于不含 HBM 的核心数据中心 {cd[-1]:.0f}% "
               f"与移动客户端 {mc[-1]:.0f}%；"
               if below_both else
               f"承载 HBM 与高性能云 DRAM 的 CMBU 毛利率 {cm[-1]:.0f}%，"
               f"核心数据中心 {cd[-1]:.0f}%、移动客户端 {mc[-1]:.0f}%；")
            + lead_words +
            "如果 HBM 占比继续按公司说的向 DRAM 占比靠拢，"
            "这张图的读法是：那对合并毛利率是<b>稀释</b>而不是增厚。"
            "<b>这四条是公司自己印出来的百分比</b>（新闻稿里就是整数），不是本页用美元数除出来的；"
            "它们对应的是各单元的口径，与合并 GAAP 毛利率不完全同一定义。"
        ),
        "src_extra": "各季业绩 8-K EX-99.1 的 Quarterly Business Unit Financial Results 表。",
    }

    gaap_gm = fin["gaap_gross_margin_pct"]
    trough = gaap_gm.index(min(gaap_gm))
    loss_words = (f"（卖一美元的货亏{cn_count(round(abs(gaap_gm[trough]) / 10))}成）"
                  if gaap_gm[trough] < 0 else "")
    margins = {
        "ref": "EX_MARGINS",
        "kind": "lines_endlabels",
        # The title leads with this quarter's reading: a from-low-to-now range
        # is a long-run chart's title, and this one sits in section two.
        "title": (
            f"GAAP 毛利率 {gaap_gm[-1]:.1f}%、营业利润率 {fin['gaap_operating_margin_pct'][-1]:.1f}%"
            + ((f"：两条都是 {len(labels)} 个季度里最高的一季"
                if fin["gaap_operating_margin_pct"][-1] == max(fin["gaap_operating_margin_pct"])
                else f"：毛利率是 {len(labels)} 个季度里最高的一季")
               if gaap_gm[-1] == max(gaap_gm) else "")
            + f"，而 {labels[trough]} 的毛利率是 {gaap_gm[trough]:.1f}%"
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
            f"是 {min(fin['gaap_gross_margin_pct']):.1f}%{loss_words}，"
            f"到 {periods[-1]} 是 {fin['gaap_gross_margin_pct'][-1]:.1f}%；"
            f"{cn_count(len(gaap_gm) - 1 - trough)}个季度走完"
            f"{cn_more_than(gaap_gm[-1] - gaap_gm[trough])}个百分点。"
            "两条线之间的距离是营业费用占收入的比重，它在整段窗口里几乎没有变化 —— "
            "这家公司的利润率<b>不是</b>被费用管出来的。"
            "零线画出来是因为这条序列真的穿过它："
            f"窗口内有 {sum(1 for v in fin['gaap_operating_margin_pct'] if v < 0)} 个季度营业利润为负。"
        ),
        "src_extra": "毛利率与营业利润率 = 合并损益表的毛利、营业利润各自除以当季收入 D。",
    }

    # ── what next quarter's own guide says about the price move ─────────────
    # The analysis's reading of this quarter is that the second derivative of
    # price turned: the company said its next-quarter margin guide "reflects a
    # meaningful moderation in the rate of price increases". The filed and
    # guided numbers carry the same statement without any wording: the margin
    # step the guide implies against the steps the quarters actually took.
    outlook = staging["next_quarter_guidance"]
    spoken = stamped_block(staging, "spoken_outlook", periods[-1])
    ng_gm = fin["non_gaap_gross_margin_pct"]
    steps = [None] + [None if (a is None or b is None) else b - a for a, b in zip(ng_gm, ng_gm[1:])]
    guided_step = outlook["non_gaap_gross_margin_pct"] - ng_gm[-1]
    guided_revenue_qoq = pct_change(outlook["revenue_usd_m"], revenue[-1])
    stepped = [(value, index) for index, value in enumerate(steps) if value is not None]
    top_step, top_index = max(stepped)
    low_step, low_index = min(stepped)
    moderation_words = (spoken or {}).get("gross_margin_outlook_words")
    moderation = {
        "ref": "EX_GM_STEP",
        "kind": "diverging_bars",
        "title": (
            f"毛利率环比：本季 {steps[-1]:+.1f}pp，下季指引"
            + ("只" if guided_step < steps[-1] / 2 else "")
            + f"隐含 {guided_step:+.1f}pp"
        ),
        "xlabels": labels + [f"{compact_period(outlook['period_label'])} 指引"],
        "values": rounded(steps + [guided_step]),
        "bar_marks": [len(labels)],
        "mark_note": "下季指引隐含：公司给的下季 non-GAAP 毛利率指引减本季实际，不是实际值",
        "legend": "non-GAAP 毛利率环比变动",
        "positive_label": "环比上升",
        "negative_label": "环比下降",
        "fmt": "pp1", "yfmt": "pp1", "label_fmt": "pp1",
        "ylab": "百分点",
        "xrot": 90,
        "zero_line": True,
        "note": (
            "柱子是每季 non-GAAP 毛利率相对上一季的变动；<b>最右一根斜纹柱不是实际值</b>，是公司 "
            f"{outlook['published_on']} 给出的下季毛利率指引（约 {outlook['non_gaap_gross_margin_pct']:.0f}%）"
            f"减本季实际（{ng_gm[-1]:.1f}%）。"
            + (f"公司在书面发言稿里说，这个指引反映了「{moderation_words}」。" if moderation_words else "")
            + f"收入指引同样放缓：下季指引中值环比 {guided_revenue_qoq:+.1f}%，"
            f"本季实际环比 {fin['revenue_qoq_pct'][-1]:+.1f}%。"
            "本季本地分析稿把这读作涨价的二阶导第一次转弱：价格仍在涨，涨得慢了。"
            f"窗口内毛利率环比升得最多的一次是 {labels[top_index]} 的 {top_step:+.1f}pp，"
            f"跌得最深的一次是 {labels[low_index]} 的 {low_step:+.1f}pp。"
        ),
        "src_extra": ("实际值 = 各季对账表的 non-GAAP 毛利 ÷ 当季收入 D，环比变动为自算；"
                      "最右一根取自本季业绩新闻稿的 Business Outlook 表。"),
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
            + ("<b>没有回购的贡献，也没有一次性收益</b> —— " if round(share_leg, 2) == 0
               else "<b>没有一次性收益</b> —— ")
            + (f"「{'、'.join(dropped)}」这一项恰好为零（摊薄股数两季都是 "
               f"{this_shares:,.0f}M），所以横轴上没有它的位置；"
               if dropped == ["摊薄股数变动"] and this_shares == prior_shares else
               f"「{'、'.join(dropped)}」这一项四舍五入到分为零（摊薄股数 "
               f"{prior_shares:,.0f}M → {this_shares:,.0f}M），所以横轴上没有它的位置；"
               if dropped == ["摊薄股数变动"] else
               f"「{'、'.join(dropped)}」恰好为零，所以横轴上没有它的位置；"
               if dropped else "")
            + ("线下项那一格是负的（税随利润走）。" if below_leg < 0 else "线下项那一格是正的。")
            + "各项加上季末每股收益等于本季每股收益，"
            f"残差 US${residual:.4f}，只来自公司各自四舍五入到分与百万。"
        ),
        "src_extra": ("各项均取自业绩 8-K EX-99.1 的 GAAP/non-GAAP 对账表；"
                      "每股口径 = 各项美元数除以当季 non-GAAP 摊薄股数 D。"),
    }

    charts = [revenue_cogs, technology_chart, unit_revenue, unit_margin, margins, moderation, bridge]
    # The supply agreements and the balance sheet are this quarter's findings
    # (the report's synthesis puts both among the quarter's conclusions), not
    # thresholds anything is tracked against next quarter, so they sit here.
    agreements = stamped_block(staging, "supply_agreements", periods[-1])
    if agreements is not None:
        charts.append(supply_agreement_chart(
            staging, agreements, staging["next_quarter_guidance"]["published_on"]))
    charts.append(balance_sheet_chart(staging))
    return charts


# ── section three: what to watch next quarter ───────────────────────────────
def next_kpi_block(staging: dict) -> dict:
    """This quarter's analysis's section 8, stamped for the quarter it was set in.

    Required every quarter: section three is nothing but this block, and a block
    left over from an earlier roll would track last quarter's lines under this
    quarter's label.
    """
    periods = staging["periods"]
    block = stamped_block(staging, "next_kpi", periods[-1])
    if block is None:
        raise ValueError("series block `next_kpi` is required every quarter")
    if block["for_period"] != shift_quarter(periods[-1], 1):
        raise ValueError(f"series block `next_kpi` tracks {block['for_period']!r}, but the quarter "
                         f"after {periods[-1]!r} is {shift_quarter(periods[-1], 1)!r}")
    return block


def next_current(staging: dict, entry: dict) -> float:
    """Where a next-quarter line stands now, read from the arrays (never typed)."""
    if "current" in entry or "actual" in entry:
        raise ValueError(f"threshold `{entry['id']}` is read from the series; remove its typed value")
    known = {
        "gross_margin": lambda: staging["financials"]["non_gaap_gross_margin_pct"][-1],
        "dso": lambda: staging["balance_sheet"]["dso_days"][-1],
    }
    if entry["id"] not in known:
        raise ValueError(f"threshold `{entry['id']}` has no series on this page: map it in "
                         "build/mu.py `next_current`")
    return known[entry["id"]]()


def next_quarter_charts(staging: dict, kpi_block: dict,
                        values: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """The overview of next quarter's lines, then each line on its own history.

    Returns the exhibits and the entries with their computed current values
    (the audit table is built from the same list).
    """
    periods = staging["periods"]
    labels = [compact_period(period) for period in periods]
    fin = staging["financials"]
    bal = staging["balance_sheet"]
    entries = [{**entry, "current": next_current(staging, entry)} for entry in kpi_block["quantified"]]
    kpi = {entry["id"]: entry for entry in entries}

    def rule_of(entry: dict) -> str:
        # The quarter this line settles is the next one, so its margin guide.
        names = {**values, "threshold": unit_text(entry["unit"], entry["threshold"]),
                 "settled_guide_margin": values["next_guide_margin"]}
        return fill_story(entry["rule"], names)

    margins = {entry["id"]: headroom(entry["direction"], entry["threshold"], entry["current"])
               for entry in entries}
    broken = [entry for entry in entries if margins[entry["id"]] < 0]
    tightest = min(entries, key=lambda entry: margins[entry["id"]])
    total = len(entries) + len(kpi_block["excluded"])
    overview = headroom_exhibit(
        f"下季 {len(entries)} 条阈值："
        + ("都还在安全侧" if not broken else f"{len(broken)} 条已越线")
        + (f"，{tightest['metric']}离阈值只剩 {margins[tightest['id']]:.1f}%"
           if not broken and margins[tightest["id"]] < 5 else ""),
        entries,
        "current",
        (
            f"正值 = 仍在安全侧。本季本地分析稿第 8 节一共{cn_count(total)}条观察指标，"
            f"能从 Micron 自己的申报算出水平的是这{cn_count(len(entries))}条，下面各画一张历史线；"
            f"其余{cn_count(len(kpi_block['excluded']))}条（"
            + "、".join(item["metric"] for item in kpi_block["excluded"])
            + "）不作图，原因逐条列在核对抽屉「下季阈值」表里。"
        ),
        src_extra="阈值、方向与触发动作取自本季本地分析稿第 8 节，不是公司指引；当前值为本季申报数或据其自算。",
    )
    overview["ref"] = "EX_NEXT_HEADROOM"

    def title(entry: dict) -> str:
        return (f"{entry['metric']}：下季阈值 {unit_text(entry['unit'], entry['threshold'])}，"
                f"当前 {unit_text(entry['unit'], entry['current'])}")

    # How often the line was crossed, and where the plotted line sat below zero,
    # both recounted from the series the chart draws.
    gm = fin["non_gaap_gross_margin_pct"]
    gm_entry = kpi["gross_margin"]
    gm_line = gm_entry["threshold"]
    crossings = [(index, gm[index] > gm_line) for index in range(1, len(gm))
                 if gm[index] is not None and gm[index - 1] is not None
                 and (gm[index] - gm_line) * (gm[index - 1] - gm_line) < 0]
    if not crossings:
        crossed = "从未被跨越过"
    elif len(crossings) == 1:
        index, upward = crossings[0]
        crossed = f"只被跨越过一次（{labels[index]}，{'向上' if upward else '向下'}）"
    elif len({upward for _, upward in crossings}) == 2:
        crossed = f"被跨越过{cn_count(len(crossings))}次，方向相反"
    else:
        crossed = f"被跨越过{cn_count(len(crossings))}次，方向都是{'向上' if crossings[0][1] else '向下'}"
    below = [index for index, value in enumerate(gm) if value is not None and value < 0]
    below_years = sorted({periods[index].split()[1] for index in below})
    if not below:
        underwater = ""
    elif len(below_years) == 1 and len(below) == 4:
        underwater = f"深蓝线在 {below_years[0]} 年整整一年待在零以下，"
    elif len(below_years) == 1 and periods[below[0]].startswith("Q1") \
            and below == list(range(below[0], below[0] + len(below))):
        underwater = f"深蓝线在 {below_years[0]} 年前{cn_count(len(below))}季待在零以下，"
    else:
        underwater = f"深蓝线在 {labels[below[0]]} 到 {labels[below[-1]]} 之间有{cn_count(len(below))}季待在零以下，"

    margin_line = threshold_exhibit(
        title(gm_entry),
        labels,
        rounded(gm),
        gm_line,
        fmt="pct1",
        ylab="non-GAAP 毛利率",
        actual_name="实际 non-GAAP 毛利率",
        threshold_name=f"下季阈值 {unit_text(gm_entry['unit'], gm_line)}（安全侧在上方）",
        note=(
            f"<b>这条阈值在 {len(labels)} 个季度里{crossed}。</b>"
            f"{underwater}随后一路回到 {gm[-1]:.1f}%，离阈值只有 {gm[-1] - gm_line:.1f} 个百分点。"
            # The rationale is the analysis's own trigger, not one this page
            # wrote for it -- it used to say the line meant 「指引本身没兑现」.
            f"本季本地分析稿的触发条件：{rule_of(gm_entry)}。"
            "Exhibit {EX_GM_RANGE} 显示这家公司的毛利率指引真的会没兑现。"
        ),
        src_extra="实际值 = 对账表的 non-GAAP 毛利 ÷ 当季收入 D；阈值取自本季本地分析稿第 8 节，不是公司指引。",
    )
    margin_line["ref"] = "EX_GM_THRESHOLD"

    dso_entry = kpi["dso"]
    dso_start = continuous_tail(bal["dso_days"])
    dso_labels = labels[dso_start:]
    dso_days = bal["dso_days"][dso_start:]
    receivable_move = bal["receivables_usd_m"][-1] - bal["receivables_usd_m"][-2]
    dso_move = bal["dso_days"][-1] - bal["dso_days"][-2]
    # Receivables this quarter's revenue would need at last quarter's DSO: the
    # part of the increase above it is "collected slower", the part below it
    # is "sold more".
    at_prior_dso = bal["dso_days"][-2] / bal["days_in_quarter"][-1] * fin["revenue_usd_m"][-1]
    sold_more = at_prior_dso - bal["receivables_usd_m"][-2]
    collected_slower = bal["receivables_usd_m"][-1] - at_prior_dso
    # The second half of the analysis's trigger: receivables growing faster than
    # revenue, and for how many quarters in a row, ending with this one.
    def faster(index: int) -> bool:
        return (bal["receivables_usd_m"][index] / bal["receivables_usd_m"][index - 1]
                > fin["revenue_usd_m"][index] / fin["revenue_usd_m"][index - 1])
    faster_run = 0
    while faster_run < len(periods) - 1 and faster(len(periods) - 1 - faster_run):
        faster_run += 1
    recv_qoq = pct_change(bal["receivables_usd_m"][-1], bal["receivables_usd_m"][-2])
    rev_qoq = pct_change(fin["revenue_usd_m"][-1], fin["revenue_usd_m"][-2])
    # The quarter length is the difference of two filed period ends, and the
    # 53-week years put a 98-day quarter into a window that is otherwise 91.
    long_quarters = [dso_labels[i] for i, days in enumerate(bal["days_in_quarter"][dso_start:])
                     if days != 91]
    day_words = ("窗口内每一季都是 91 天" if not long_quarters else
                 f"窗口内除 {'、'.join(long_quarters)} 为 "
                 f"{bal['days_in_quarter'][dso_start + dso_labels.index(long_quarters[0])]} 天外都是 91 天")
    dso_line = threshold_exhibit(
        title(dso_entry),
        dso_labels,
        rounded(dso_days),
        dso_entry["threshold"],
        fmt="f1",
        ylab="天",
        actual_name="DSO（自算）",
        threshold_name=f"下季阈值 {unit_text(dso_entry['unit'], dso_entry['threshold'])}（安全侧在下方）",
        note=(
            (f"<b>本季应收账款环比增加 US${receivable_move / 1000:.1f}B，"
             "看上去像回款恶化，但周转天数说的是另一回事。</b>"
             if receivable_move > 0 else
             f"<b>本季应收账款环比减少 US${abs(receivable_move) / 1000:.1f}B。</b>")
            + f"DSO 从 {bal['dso_days'][-2]:.1f} 天走到 {bal['dso_days'][-1]:.1f} 天，"
            + (f"只多了 {dso_move:.1f} 天；" if dso_move >= 0 else f"少了 {abs(dso_move):.1f} 天；")
            + f"而本窗口的最高点是 {dso_labels[dso_days.index(max(dso_days))]} 的 "
            f"{max(dso_days):.1f} 天"
            + (" —— 也就是说，<b>应收占用相对收入的水平比两年前还低。</b>"
               if dso_days[-1] < dso_days[-9] else "。")
            + "换个说法：如果 DSO 完全不动地停在上季的水平，本季收入也需要 "
            f"US${at_prior_dso / 1000:.1f}B 的应收，实际是 US${bal['receivables_usd_m'][-1] / 1000:.1f}B。"
            + ("增量的绝大部分来自「卖得多」，不是「收得慢」。"
               if receivable_move > 0 and sold_more > collected_slower else "")
            + f"本季本地分析稿的触发条件：{rule_of(dso_entry)}。"
            + f"后半句的读数：本季应收环比 {recv_qoq:+.1f}%、收入环比 {rev_qoq:+.1f}%，"
            + (f"应收更快，连续{cn_count(faster_run)}季如此。" if faster_run else "应收没有更快。")
            + f"DSO = 期末应收 ÷ 当季收入 × 当季天数，{day_words}。"
        ),
        src_extra="应收账款取自各季业绩 8-K EX-99.1 的合并资产负债表；DSO 为自算 D；阈值取自本季本地分析稿第 8 节。",
    )
    dso_line["ref"] = "EX_DSO"

    return [overview, margin_line, dso_line], entries


def balance_sheet_chart(staging: dict) -> dict:
    """Net cash and total debt over the whole record.

    A section-two chart: its title is this quarter's reading (the debt paid
    down, the net cash left), which is one of the quarter's findings rather
    than a threshold anything is tracked against next quarter.
    """
    periods = staging["periods"]
    labels = [compact_period(period) for period in periods]
    fin = staging["financials"]
    bal = staging["balance_sheet"]

    interest = fin["interest_expense_usd_m"]
    if interest[-1] is None:
        interest_words = ""
    else:
        interest_words = ("本季合并损益表上的<b>利息支出是零</b>" if interest[-1] == 0
                          else f"本季合并损益表上的利息支出是 US${interest[-1]:,.0f}M")
        if interest[-2] is not None and interest[-5] is not None:
            interest_words += (f"（上一季 US${interest[-2]:,.0f}M，"
                               f"一年前 US${interest[-5]:,.0f}M）")
        interest_words += "。"
    net = bal["net_cash_usd_m"]
    debt = bal["total_debt_usd_m"]
    repaid = debt[-2] - debt[-1]
    net_words = (f"净现金 {'−' if net[-1] < 0 else ''}US${abs(net[-1]) / 1000:.1f}B"
                 + (f"，{len(labels)} 个季度里最高" if net[-1] == max(net) else ""))
    net_cash = {
        "ref": "EX_NETCASH",
        "kind": "bar_line_dual",
        # This quarter's reading first: the debt it paid down, then where that
        # left net cash.
        "title": (
            f"本季还债 US${repaid / 1000:.1f}B，总债务降到 US${debt[-1] / 1000:.1f}B；{net_words}"
            if repaid > 0 else
            f"{net_words}，总债务 US${debt[-1] / 1000:.1f}B"
        ),
        "xlabels": labels,
        "xrot": 90,
        "bar": {"name": "净现金（现金及投资 − 总债务）", "color": "NAVY",
                "values": rounded([v / 1000 for v in bal["net_cash_usd_m"]])},
        "line": {"name": "总债务 (RHS)", "color": "RED",
                 "values": rounded([v / 1000 for v in bal["total_debt_usd_m"]]),
                 "yfmt": "usd1"},
        "fmt": "usd1", "yfmt": "usd1", "label_fmt": "usd1",
        "ylab": "US$B", "ylab2": "US$B",
        "zero_line": True,
        "note": (
            "<b>这张图是上一轮周期留下的账单被还掉的过程。</b>"
            f"净现金在 {periods[net.index(min(net))]} 最低到 "
            f"−US${abs(min(net)) / 1000:.1f}B，"
            f"到本季是 {'+' if net[-1] >= 0 else '−'}US${abs(net[-1]) / 1000:.1f}B；"
            f"总债务从窗口内最高的 US${max(bal['total_debt_usd_m']) / 1000:.1f}B 降到 "
            f"US${bal['total_debt_usd_m'][-1] / 1000:.1f}B。"
            + interest_words
            + ("读这张图时值得记住 Exhibit {EX_CYCLE}："
               "上一轮下行里这家公司是靠借钱扛过去的，而现在它没有净债务了 —— "
               "这是下一次下行时和上一次不一样的地方，而且它已经<b>在报表上</b>，"
               "不需要相信任何协议条款。"
               if net[-1] > 0 else "")
        ),
        "src_extra": ("现金及投资 = 现金及等价物 + 短期投资 + 长期有价投资；"
                      "总债务 = 流动负债端债务 + 长期债务；两者相减为自算 D。"),
    }
    return net_cash


def supply_agreement_chart(staging: dict, agreements: dict, release: str) -> dict:
    """The supply agreements at quarter end beside the company's all-signed figures.

    Built only while the series carries a `supply_agreements` block stamped for
    the page's quarter (see `board.stamped_block`). The block was called
    `filed_vs_spoken` and the right-hand bars were labelled as spoken, non-filed
    figures; the deposit figure on that side is printed in the same 10-Q's
    liquidity section, so the split is quarter-end versus all-signed, and each
    right-hand bar names its own source.
    """
    items = agreements["items"]
    magnitude = round(max(math.log10(item["company_usd_m"] / item["quarter_end_usd_m"])
                          for item in items))
    fiscal_year_end_before = staging["annual_cycle"][-1]["fiscal_year_end_date"]
    # Micron's fiscal fourth quarter is filed in the 10-K, not a 10-Q.
    next_filing = ("10-K" if staging["next_quarter_guidance"]["fiscal_label"].startswith("FQ4")
                   else "10-Q")
    rpo, deposits = items
    sca = {
        "ref": "EX_SCA",
        "kind": "grouped_bars",
        "title": (
            f"长期供货协议：季末已入账的数，与含季后协议的公司口径差{cn_count(magnitude)}个数量级"
        ),
        "xlabels": [item["metric"] for item in items],
        "groups": [
            {"name": "季末已入账（10-Q 附注）", "color": "NAVY",
             "values": rounded([item["quarter_end_usd_m"] / 1000 for item in items])},
            {"name": "含季末后签署的协议（公司口径）", "color": "GOLD",
             "values": rounded([item["company_usd_m"] / 1000 for item in items])},
        ],
        "bar_labels": True,
        "fmt": "usd1",
        "label_fmt": "usd1",
        "ylab": "US$B",
        "note": (
            "<b>深蓝那两根几乎看不见，而这正是本图要说的事。</b>"
            f"截至 {staging['period_ends'][-1]} 的 10-Q 附注里，剩余履约义务约 "
            f"US${rpo['quarter_end_usd_m'] / 1000:.1f}B、合同负债（客户存款）"
            f"US${deposits['quarter_end_usd_m'] / 1000:.3f}B。"
            "含季末<b>之后</b>签署的协议，公司给的是：按合同最低价计的剩余期累计收入约 "
            f"US${rpo['company_usd_m'] / 1000:.0f}B（只在 {release} 的书面发言稿里给过），"
            f"预计收到的现金存款与相关承诺 US${deposits['company_usd_m'] / 1000:.0f}B"
            "（同一份 10-Q 的流动性一节与书面发言稿都写了）。"
            "<b>两边都不是错的，它们是不同的东西</b>："
            "附注只计入季末已签、且有固定价或价格带的协议，按<b>最低承诺量 × 最低合同价</b>计量，"
            "并排除原始期限一年以内的合同；公司口径含季末之后签署的协议，存款也要到下一季才陆续入表。"
            "公司自己在 10-Q 里写明附注口径「不代表这些合同下的未来收入」。"
            "<b>本页把两边都画出来，是因为一页只画其中一个都会误导</b> —— "
            "只画附注会漏掉已经发生的商业事实，只画公司口径会把还没进报表的东西当成已实现。"
            + (f"上一财年末（{fiscal_year_end_before}）公司称剩余履约义务 not material，"
               f"所以附注这一栏只有一个观测点，下一份申报（{next_filing}）才会给出第二个。"
               if agreements.get("first_filed_observation") else "")
        ),
        "src_extra": ("季末已入账一栏取自 " + rpo["quarter_end_source"] + "；公司口径逐项出处："
                      + "；".join(f"{item['metric']}取自{item['company_source']}" for item in items)
                      + "。"),
    }
    return sca



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
    n_years = cn_count(len(annual))
    latest_gm = fin["gaap_gross_margin_pct"][-1]
    above_record = latest_gm - margin[best]
    partial = partial_fiscal_year(staging)
    spoken = stamped_block(staging, "spoken_outlook", periods[-1])

    cycle = {
        "ref": "EX_CYCLE",
        "kind": "bar_line_dual",
        "title": (
            f"{n_years}个财年的营收与毛利率：最低 {margin[worst]:.1f}%（{years[worst]}），"
            f"最高 {margin[best]:.1f}%（{years[best]}）"
        ),
        "xlabels": years,
        "xrot": 90,
        "bar": {"name": "营收", "color": "NAVY", "values": rounded(revenue)},
        "line": {"name": "毛利率 (RHS)", "color": "GOLD",
                 "values": rounded(margin), "yfmt": "pct0"},
        "fmt": "usd1", "yfmt": "usd1", "label_fmt": "usd1",
        "ylab": "US$B", "ylab2": "毛利率",
        "zero_line": True,
        "note": (
            f"<b>本页所有判断都应该放在这张图上读。</b>{n_years}个财年里毛利率的完整区间是 "
            f"{margin[worst]:.1f}% 到 {margin[best]:.1f}%，"
            f"其中 {sum(1 for v in margin if v < 0)} 个财年为负、"
            f"{sum(1 for row in annual if row['operating_margin_pct'] < 0)} 个财年营业利润为负。"
            f"上一轮周期顶（{years[best]}）的毛利率是 {margin[best]:.1f}%，"
            f"而本页最新一季是 {latest_gm:.1f}%"
            + (" —— <b>比历史上任何一个完整财年都高出"
               f"{cn_more_than(above_record)}个百分点。</b>"
               "这既是「这次不一样」那套说法的全部依据，也是它最大的风险："
               "一个从未在这条序列上出现过的水平，没有历史可以告诉你它能待多久。"
               if above_record > 0 else "。")
            + (f"FY{partial['fiscal_year']} 只有前{cn_count(partial['quarters'])}季在表内"
               f"（营收 US${partial['revenue_usd_m'] / 1000:.1f}B、毛利率 {partial['gross_margin_pct']:.1f}%），"
               "本图不画未完结的财年。" if partial and partial["quarters"] < 4 else
               f"FY{partial['fiscal_year']} 四个季度都已报出，但本图的财年取 10-K 印出的数，"
               "等 10-K 申报后才画。" if partial else "")
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
        "ylab": "US$B", "ylab2": "资本强度",
        "note": (
            f"<b>红线才是这张图的主角。</b>{n_years}个财年里资本强度的区间是 "
            f"{min(intensity):.1f}%（{years[intensity.index(min(intensity))]}）到 "
            f"{max(intensity):.1f}%（{years[intensity.index(max(intensity))]}），"
            "而它的高点<b>全部落在营收的低点上</b> —— "
            f"{years[intensity.index(max(intensity))]} 那一年营收 US${revenue[intensity.index(max(intensity))]:.1f}B、"
            f"毛利率 {margin[intensity.index(max(intensity))]:.1f}%，"
            f"支出却是营收的{cn_fraction(max(intensity) / 100)}。"
            "这是内存行业最难的一件事：产能要在看不见需求的时候建。"
            + (f"管理层已经说 FY{spoken['capex_fiscal_year']} 的资本开支会「{spoken['capex_words']}」"
               f"（约 {spoken['capex_floor_usd_bn'] * 10:.0f} 亿美元以上），"
               f"而 {years[-1]} 是 US${capex[-1]:.1f}B —— "
               "<b>那个数只在电话会上给过，没有出现在任何申报文件里</b>，所以本图不画它；"
               if spoken else "")
            + f"等 FY{annual[-1]['fiscal_year'] + 1} 的 10-K 出来，"
            f"这条柱子才会有第{cn_ordinal(len(annual) + 1)}格。"
        ),
        "src_extra": "各财年现金流量表的「购建固定资产支出」；资本强度为自算 D。",
    }

    fcf = fin["adjusted_free_cash_flow_usd_m"]
    deepest = min(v for v in fcf if v is not None)
    # The empty cells of the net-capex row, named by year and quarter.
    empty = [periods[i] for i, v in enumerate(fin["capex_net_usd_m"]) if v is None]
    empty_years = sorted({period.split()[1] for period in empty})
    if empty and len(empty_years) == 1:
        empty_where = (f"{empty_years[0]} 年第"
                       + "、".join(cn_ordinal(int(period[1])) for period in empty) + "季")
    else:
        empty_where = "、".join(empty)
    # Net capex quarters read from a release body because the reconciliation
    # table the rest of the row comes from starts only with 2018Q1.
    recon_gap = sum(1 for period, value in zip(periods[:periods.index("Q1 2018")],
                                               fin["capex_net_usd_m"]) if value is not None)

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
            + (f"<b>红色那条有{cn_count(len(empty))}格是空的</b>（{empty_where}）：公司「扣除合作方出资后」"
               f"这个口径的措辞最早出现在 2016-10-04 那份发布里，更早{cn_count(len(empty))}份只印毛额，"
               f"10-Q 也只给毛额的年初至今数，所以那{cn_count(len(empty))}季没有可读的净值，"
               "本页不用毛额顶替 —— "
               "在此之前它们装的正是毛额，两个不同的计量摆在同一行上。"
               if empty else "")
            + "<b>另外，「等式逐季闭合」不是一次检验</b>：调整后自由现金流本页就是由"
            "另外两条相减得到的，所以它必然闭合，看不出资本开支那一行装的是哪个口径。"
            "<b>注意红色那条在整段窗口里几乎是平的</b>：资本开支并没有跟着现金流一起暴涨，"
            + (f"所以本季 US${fcf[-1] / 1000:.1f}B 的自由现金流几乎全部来自经营端。"
               if fcf[-1] is not None and fcf[-1] > 0 else "")
            + "这也是 Exhibit {EX_CAPEX} 那句话的季度版本 —— 支出的拐点还没到表里来。"
        ),
        "src_extra": ("2018 年第一季度起取自各季业绩 8-K EX-99.1 的非 GAAP 对账表；"
                      f"更早的{cn_count(recon_gap)}季该表尚不存在，"
                      "净资本开支取自同一份发布正文里公司自己写的那句「扣除合作方出资后……」（三位有效数字），"
                      "调整后自由现金流按同两条相减得到。"),
    }

    # Inventory days shares cost of goods sold's eighteen-quarter hole, so this
    # pair is drawn over the tail where both legs exist.
    dio_start = continuous_tail(bal["dio_days"])
    inv_labels = labels[dio_start:]
    inv_days = bal["dio_days"][dio_start:]
    inv_level = bal["inventories_usd_m"][dio_start:]
    inv_revenue = fin["revenue_usd_m"][dio_start:]
    # Official figures win on this site: the prepared remarks state this
    # quarter's days of inventory (120) and this page's arithmetic gives 122,
    # so the title prints the company's and the note keeps both.
    stated_days = (spoken or {}).get("days_of_inventory")
    stated_differs = stated_days is not None and round(inv_days[-1]) != stated_days
    inventory = {
        "ref": "EX_INVENTORY",
        "kind": "bar_line_dual",
        "title": (
            f"存货 US${inv_level[-1] / 1000:.1f}B、存货天数 "
            + (f"{stated_days} 天（公司口径）" if stated_days is not None else f"{inv_days[-1]:.0f} 天")
            + f"：{len(inv_labels)} 季里收入 "
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
        "ylab": "US$B", "ylab2": "天",
        "note": (
            # "Flat" is a claim about the last eight bars, so it is checked on
            # them: the highest within a quarter of the lowest.
            ("<b>存货这条柱子近两年是平的，而它本来最该动。</b>"
             if max(inv_level[-8:]) / min(inv_level[-8:]) - 1 <= 0.25 else "")
            + f"从 {periods[0]} 到 {periods[-1]}，收入涨了 "
            f"{pct_change(fin['revenue_usd_m'][-1], fin['revenue_usd_m'][0]):.0f}%（"
            f"{fin['revenue_usd_m'][-1] / fin['revenue_usd_m'][0]:.1f} 倍），"
            f"期末存货从 US${bal['inventories_usd_m'][0] / 1000:.1f}B 只走到 "
            f"US${bal['inventories_usd_m'][-1] / 1000:.1f}B。"
            f"存货天数的高点在 {inv_labels[inv_days.index(max(inv_days))]}，"
            f"{max(inv_days):.0f} 天 —— 那是上一轮下行最深的时候，"
            "货堆在仓库里而收入在掉；现在是 "
            f"{inv_days[-1]:.0f} 天"
            + (f"（本页自算；公司书面发言稿给的是 {stated_days} 天，公司没有公布算法）。"
               if stated_differs else "。")
            + "<b>存货天数用销货成本作分母</b>（期末存货 ÷ 当季销货成本 × 当季天数），"
            "所以它不受售价暴涨的影响，这一点在本页尤其要紧："
            "换成用收入作分母，同一组数字会显示存货天数「腰斩」，那只是价格的影子。"
        ),
        "src_extra": ("存货取自各季业绩 8-K EX-99.1 的合并资产负债表；图中存货天数线为自算 D"
                      + ("；标题的存货天数取自当季业绩电话会书面发言稿（公司口径）。"
                         if stated_days is not None else "。")),
    }

    return [cycle, capex_chart, cash_generation, inventory]


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    fin = staging["financials"]
    return [f"Revenue ${fin['revenue_usd_m'][-1] / 1000:.2f}B",
            f"non-GAAP GM {fin['non_gaap_gross_margin_pct'][-1]:.1f}%",
            f"销货成本环比 {fin['cost_of_goods_sold_qoq_pct'][-1]:+.1f}%"]


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    fin = staging["financials"]
    bal = staging["balance_sheet"]
    tech = staging["technology"]
    units = staging["business_units"]
    record = staging["quarterly_guidance_history"]
    outlook = staging["next_quarter_guidance"]
    annual = staging["annual_cycle"]

    closure, prior = settlement_blocks(staging)
    values = settlement_values(staging, prior)
    settlement_ex, settlement_tables = settlement_charts(staging, closure, prior, values)
    guided_ex, delivery_table, tallies = guidance_delivery_charts(staging)
    rev_n, rev_above, rev_inside, rev_below = tallies["revenue"]
    gm_n, gm_above, gm_inside, gm_below = tallies["gross_margin"]
    worst_gap = tallies["worst_gap"]
    # Section one settles in the order the format asks for: last quarter's
    # questions, last quarter's thresholds, then the company's own guidance.
    settled_ex = settlement_ex + guided_ex
    highlight_ex = quarter_charts(staging)
    kpi = next_kpi_block(staging)
    next_ex, next_entries = next_quarter_charts(staging, kpi, values)
    routine_ex = routine_charts(staging)

    groups = [settled_ex, highlight_ex, next_ex, routine_ex]
    exhibits = [exhibit for group in groups for exhibit in group]
    number_exhibits(exhibits)
    # `resolve_exhibit_refs` fills `{EX_…}` inside exhibits only; the same
    # references in table cells and section descriptions go through `refer`.
    exhibit_numbers = {exhibit["ref"]: exhibit["n"] for exhibit in exhibits if exhibit.get("ref")}

    def refer(text: str) -> str:
        for key, number in exhibit_numbers.items():
            text = text.replace("{" + key + "}", str(number))
        if "{EX_" in text:
            raise ValueError(f"unresolved exhibit reference in {text[:60]!r}")
        return text

    resolve_exhibit_refs(exhibits)
    # Sliced by cumulative length, the way the TSM builder does it, so adding a
    # chart to one section cannot move a chart into its neighbour.
    cut = []
    cursor = 0
    for group in groups:
        cut.append(exhibits[cursor:cursor + len(group)])
        cursor += len(group)
    settled_ex, highlight_ex, next_ex, routine_ex = cut

    first_table = exhibits[-1]["n"] + 1

    # The outlook being transcribed is the record's last row; its own flags say
    # which figures the company gave as a point ("Approximately") and which as
    # a range, so the table and its note follow the release instead of habit.
    point = {name: record[f"{key}_is_point"][-1] for name, key in (
        ("收入", "guide_non_gaap_revenue_usd_m"), ("毛利率", "guide_non_gaap_gross_margin_pct"),
        ("营业费用", "guide_non_gaap_opex_usd_m"), ("每股收益", "guide_non_gaap_eps_usd"))}
    band = {name: record[f"{key}_band"][-1] for name, key in (
        ("毛利率", "guide_non_gaap_gross_margin_pct"), ("营业费用", "guide_non_gaap_opex_usd_m"))}

    def guided(name: str, text: str, width: str) -> str:
        return f"约 {text}" if point[name] else f"{text} ± {width}"

    points = [name for name, flag in point.items() if flag]
    ranges = [name for name, flag in point.items() if not flag]
    shape_note = (
        (f"{joined(points)}是单点数（公司写的是 Approximately），不是区间；" if points else "")
        + (f"{joined(ranges)}是区间。" if ranges else "四项都是单点数。")
    )
    guidance = {
        "title": f"下季指引（{outlook['period_label']}，公司称 {outlook['fiscal_label']}）",
        "headers": ["指标", "GAAP 指引", "non-GAAP 指引", "隐含环比"],
        "rows": [
            ["收入",
             guided("收入", f"US${outlook['revenue_usd_m'] / 1000:.1f}B",
                    f"US${outlook['revenue_band_usd_m'] / 1000:.1f}B"),
             guided("收入", f"US${outlook['revenue_usd_m'] / 1000:.1f}B",
                    f"US${outlook['revenue_band_usd_m'] / 1000:.1f}B"),
             f"{pct_change(outlook['revenue_usd_m'], fin['revenue_usd_m'][-1]):+.1f}%"],
            ["毛利率",
             guided("毛利率", f"{outlook['gaap_gross_margin_pct']:.1f}%", f"{band['毛利率'] or 0:.1f}%"),
             guided("毛利率", f"{outlook['non_gaap_gross_margin_pct']:.1f}%", f"{band['毛利率'] or 0:.1f}%"),
             f"{outlook['non_gaap_gross_margin_pct'] - fin['non_gaap_gross_margin_pct'][-1]:+.1f}pp"],
            ["营业费用",
             guided("营业费用", f"US${outlook['gaap_opex_usd_m']:,.0f}M", f"US${band['营业费用'] or 0:,.0f}M"),
             guided("营业费用", f"US${outlook['non_gaap_opex_usd_m']:,.0f}M", f"US${band['营业费用'] or 0:,.0f}M"),
             f"{pct_change(outlook['non_gaap_opex_usd_m'], fin['non_gaap_operating_expenses_usd_m'][-1]):+.1f}%"],
            ["摊薄每股收益",
             guided("每股收益", f"US${outlook['gaap_eps_usd']:.2f}", f"US${outlook['eps_band_usd']:.2f}"),
             guided("每股收益", f"US${outlook['non_gaap_eps_usd']:.2f}", f"US${outlook['eps_band_usd']:.2f}"),
             f"{pct_change(outlook['non_gaap_eps_usd'], fin['non_gaap_diluted_eps_usd'][-1]):+.1f}%"],
        ],
        "note": (
            shape_note
            + f"本表按公司在 {outlook['published_on']} 业绩新闻稿里的 Business Outlook 原样转录，"
            f"隐含环比为自算。指引以约 {outlook['diluted_shares_m'] / 100:.1f} 亿股摊薄股数为基础。"
        ),
    }

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

    # Every one of the analysis's section-8 rows, with its own trigger; the ones
    # not drawn say why in the row itself. (The table used to print only the
    # metric name for those, beside 「原因见左」 -- the reason had been cut off
    # at the first bracket.)
    def kpi_rule(entry: dict) -> str:
        names = {**values, "settled_guide_margin": values["next_guide_margin"]}
        if "threshold" in entry:
            names["threshold"] = unit_text(entry["unit"], entry["threshold"])
        return refer(fill_story(entry["rule"], names))

    kpi_rows = []
    for item in next_entries:
        drawn = next(exhibit["n"] for exhibit in next_ex
                     if exhibit["title"].startswith(item["metric"] + "："))
        kpi_rows.append([
            item["metric"],
            kpi_rule(item),
            "高于阈值为安全" if item["direction"] == "up" else "低于阈值为安全",
            unit_text(item["unit"], item["current"]),
            f"{headroom(item['direction'], item['threshold'], item['current']):+.1f}%",
            f"作图（Exhibit {drawn}）",
        ])
    for item in kpi["excluded"]:
        kpi_rows.append([item["metric"], kpi_rule(item), "—", "—", "—",
                         "不作图：" + refer(fill_story(item["reason"], values))])

    agreements = stamped_block(staging, "supply_agreements", periods[-1])
    spoken = stamped_block(staging, "spoken_outlook", periods[-1])
    agreement_rows = []
    for item in (agreements or {}).get("items", []):
        agreement_rows.append([
            item["metric"],
            f"US${item['quarter_end_usd_m']:,.0f}M",
            item["quarter_end_source"],
            f"US${item['company_usd_m']:,.0f}M",
            item["company_source"] + "：" + item["company_basis"],
        ])

    tables = [
        *({"n": None, **table} for table in settlement_tables),
        {**delivery_table, "n": None},
        {
            "n": None,
            "title": "八季核心（自然年季度标注；公司财季见第二列）",
            "headers": ["自然年季度", "公司财季", "季末", "收入", "环比", "销货成本",
                        "GAAP 毛利率", "non-GAAP 毛利率", "GAAP 营业利润率",
                        "GAAP 每股收益", "non-GAAP 每股收益", "经营现金流",
                        "调整后自由现金流", "净现金"],
            "rows": core_rows,
        },
        {
            "n": None,
            "title": "八季按技术拆分，以及公司对价与量的原始措辞",
            "headers": ["自然年季度", "DRAM 收入", "DRAM 占比", "NAND 收入", "NAND 占比",
                        "其他", "DRAM 售价（公司原话）", "DRAM 出货位元（公司原话）",
                        "NAND 售价（公司原话）", "NAND 出货位元（公司原话）"],
            "rows": technology_rows,
        },
        {
            "n": None,
            "title": (f"业务单元{cn_count(len(units['quarters']))}季"
                      f"（公司自 {units['first_printed_in']} 业绩稿起披露的四单元口径）"),
            "headers": ["自然年季度", "公司财季",
                        "CMBU 收入", "CMBU 毛利率", "CMBU 营业利润率",
                        "CDBU 收入", "CDBU 毛利率", "CDBU 营业利润率",
                        "MCBU 收入", "MCBU 毛利率", "MCBU 营业利润率",
                        "AEBU 收入", "AEBU 毛利率", "AEBU 营业利润率"],
            "rows": unit_rows,
        },
        {
            "n": None,
            "title": f"{cn_count(len(annual))}财年记录（各年取该年 10-K 印出的数）",
            "headers": ["财年", "财年末", "周数", "营收", "毛利率", "营业利润率",
                        "摊薄每股收益", "经营现金流", "资本开支", "资本强度",
                        "期末存货", "总债务"],
            "rows": annual_rows,
        },
        {
            "n": None,
            "title": (f"下季阈值：本季本地分析稿第 8 节{cn_count(len(next_entries) + len(kpi['excluded']))}条，"
                      "哪些本页能作图，哪些不能"),
            "headers": ["指标", "阈值与触发动作", "方向", "当前值", "余量 D", "本页处理"],
            "rows": kpi_rows,
        },
    ]
    if agreement_rows:
        tables.append({
            "n": None,
            "title": "长期供货协议：季末已入账的数与公司口径逐项对照",
            "headers": ["项目", "季末已入账", "出处", "含季后协议的公司口径", "公司口径的出处与说明"],
            "rows": agreement_rows,
        })
    # The one object published byte-identically on every page. Micron is
    # neither a column in it nor on the chain it draws -- it sits upstream
    # of all four, which is exactly why it is not added: the table has to
    # stay identical on all twenty-six pages, and a column here would
    # rewrite it everywhere.
    tables.append(ai_capex_cycle_table(0))
    for offset, table in enumerate(tables):
        table["n"] = first_table + offset

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

    latest = latest_block(
        staging,
        period=periods[-1],
        period_end=staging["period_ends"][-1],
        release_date=outlook["published_on"])
    fiscal = fiscal_name(staging["fiscal_labels"][-1])
    fiscal_year = 2000 + int(staging["fiscal_labels"][-1][-2:])
    audit_words = {"unaudited": "未审计", "audited": "已审计"}[latest["audit_status"]]
    ng_gm = fin["non_gaap_gross_margin_pct"]
    ng_eps = fin["non_gaap_diluted_eps_usd"]
    gm_record = ng_gm[-1] == max(v for v in ng_gm if v is not None)
    eps_record = ng_eps[-1] == max(v for v in ng_eps if v is not None)
    finished_last = max(i for i, v in enumerate(record["actual_non_gaap_gross_margin_pct"])
                        if v is not None)
    years_since_worst = (finished_last - worst) // 4
    release_source = next(item for item in staging["sources"]
                          if item["label"].startswith(f"Micron {fiscal} 业绩新闻稿"))
    articles = [
        '<article><span>算术</span><b>涨的是价，不是量</b>'
        f'<p>一年之间收入 {signed(pct_change(revenue[-1], revenue[-5]), 0)}，'
        f'销货成本 {signed(pct_change(cogs[-1], cogs[-5]), 0)}；'
        f'最近一季收入环比 {signed(fin["revenue_qoq_pct"][-1], 0)}，'
        f'销货成本环比 {signed(fin["cost_of_goods_sold_qoq_pct"][-1], 0)}。'
        '两条都是同一张损益表上的申报值，'
        '公司对售价与出货位元只给文字口径，本页不把文字折成数字。</p></article>',
        '<article><span>记录</span><b>它的指引两个方向都破过</b>'
        f'<p>{gm_n} 个已完结季里，non-GAAP 毛利率指引 {gm_above} 季穿出上限、'
        f'{gm_inside} 季落在区间内、{gm_below} 季跌破下限，'
        f'最差的一次差 {abs(worst_gap):.0f} 个百分点。'
        f'同样 {rev_n} 季，收入指引 {rev_above} 季穿出上限、'
        f'{rev_inside} 季落在区间内、{rev_below} 季跌破下限 —— '
        + ('接近一半一半，不是底线。' if half_and_half(rev_above, rev_n)
           else f'高于上限的占 {round(rev_above / rev_n * 100)}%。')
        + '</p></article>',
    ]
    if agreements is not None:
        rpo, deposits = agreements["items"][0], agreements["items"][1]
        articles.append(
            '<article><span>口径</span>'
            f'<b>协议：季末入账 US${rpo["quarter_end_usd_m"] / 1000:.1f}B，'
            f'含季后协议 US${rpo["company_usd_m"] / 1000:.0f}B</b>'
            f'<p>10-Q 附注里季末已入账的剩余履约义务是 {yi(rpo["quarter_end_usd_m"])} 亿美元、'
            f'客户存款 {yi(deposits["quarter_end_usd_m"])} 亿美元；'
            f'含季末后签署的协议，公司给的是按最低价计约 {yi(rpo["company_usd_m"])} 亿美元的合同收入'
            f'（书面发言稿）与 {yi(deposits["company_usd_m"])} 亿美元的存款及相关承诺（10-Q 流动性一节）。'
            '两个口径都对，量的是不同的东西。</p></article>')
    inventory_quarters = len(periods) - continuous_tail(bal["dio_days"])
    annual_losses = sum(1 for index, row in enumerate(annual) if row["gross_margin_pct"] < 0
                        and (index == 0 or annual[index - 1]["gross_margin_pct"] >= 0))
    kpi_total = len(next_entries) + len(kpi["excluded"])
    point_run = 0
    while (point_run < len(record["quarters"])
           and record["guide_non_gaap_gross_margin_pct_is_point"][-1 - point_run]
           and record["guide_non_gaap_opex_usd_m_is_point"][-1 - point_run]):
        point_run += 1
    fcf_closed = sum(1 for value in fin["adjusted_free_cash_flow_usd_m"] if value is not None)
    dio_start = continuous_tail(bal["dio_days"])
    dio_long = [periods[i] for i in range(dio_start, len(periods)) if bal["days_in_quarter"][i] != 91]
    partial = partial_fiscal_year(staging)
    lag_low, lag_high, lag_middle = lag_facts(record)
    words_example = [move[0] for move in (worded_move(tech["dram_asp_text"][-1]),
                                         worded_move(tech["nand_bit_text"][-1])) if move]
    settle_parts = []
    if closure is not None:
        settle_parts.append(f"{cn_count(len(closure['items']))}条待验证问题闭环了几条")
    if prior is not None:
        settle_parts.append(f"第 8 节能量化的{cn_count(len(prior['quantified']))}条阈值守住了几条")
    settle_words = (
        f"先结算上季（{periods[-2]}）本地分析稿留下的东西：" + "、".join(settle_parts)
        + "；再看公司自己的指引记录。"
        if settle_parts else
        f"本站对该公司的第一份季报分析是 {periods[-1]}，没有上季留下的跟踪指标可结算；"
        "本节结算的是公司上季给出、本季到期的指引。")

    return {
        "schema_version": "quarterly-dashboard/mu-v1",
        "page": {"slug": "mu", "language": "zh-CN"},
        "company": {
            "ticker": "MU",
            "name": "Micron Technology, Inc.",
            "group": "semiconductor_ai",
            "accounting_standard": "US GAAP",
        },
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · MU",
        "title": f"Micron Technology (MU)：{periods[-1]} 季报仪表盘",
        "subtitle": (
            f"季度截至 {latest['period_end']} · 发布 {latest['release_date']} · US GAAP · {audit_words} · "
            "财年末为最接近 8 月 31 日的星期四（申报人记录 09-03，"
            f"FY{fiscal_year} 即 {fiscal_year_end(fiscal_year)}），"
            f"本站按自然年季度标注：本页 {periods[-1]} 即公司所称 {fiscal}"
        ),
        "headline": (
            f"收入 US${revenue[-1]:,.0f}M、环比 {signed(fin['revenue_qoq_pct'][-1])}，"
            f"non-GAAP 毛利率 {ng_gm[-1]:.1f}%{'（创纪录）' if gm_record and not eps_record else ''}、"
            f"每股收益 US${ng_eps[-1]:.2f}"
            + (" 双双创纪录；" if gm_record and eps_record else
               "（创纪录）；" if eps_record else "；")
            + "但同一张损益表上销货成本环比"
            f"{'只有' if fin['cost_of_goods_sold_qoq_pct'][-1] < fin['revenue_qoq_pct'][-1] else '是'} "
            f"{signed(fin['cost_of_goods_sold_qoq_pct'][-1])}，"
            f"而这家公司{cn_count(years_since_worst)}年前刚把自己 "
            f"{record['guide_non_gaap_gross_margin_pct'][worst]:.1f}% 的"
            f"毛利率指引报成 {record['actual_non_gaap_gross_margin_pct'][worst]:.1f}%。"
        ),
        "brief": (
            f'<h4>本季{cn_count(len(articles))}条主线</h4><div class="takeaway-grid">'
            + "".join(articles)
            + '</div>'
        ),
        "source": (
            f'Source: <a href="{release_source["url"]}" rel="noopener">Micron {fiscal} '
            f'业绩新闻稿（8-K EX-99.1）</a>与截至 {latest["period_end"]} 的 10-Q。'
        ),
        "source_url": release_source["url"],
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": guidance,
        "sections": [
            {
                "id": "settled",
                "title": "一、上季跟踪指标兑现了吗",
                "description": (
                    settle_words
                    + "公司每季在业绩新闻稿的 Business Outlook 表里给出下一季的收入、毛利率、"
                    "营业费用与每股收益，GAAP 与 non-GAAP 两栏并列，这份记录能一直回到 "
                    f"{record['quarters'][0].split()[1]} 年。"
                    # Stated from the record's own tallies. It used to call this
                    # 「本站唯一」 two-sided record, which stopped being true
                    # when Intel's page landed with a −20pp margin miss.
                    + (f"它两个方向都被打破过：non-GAAP 毛利率 {gm_n} 个已完结季里 {gm_above} 季穿出上限、"
                       f"{gm_below} 季跌破下限，最差一次差 {abs(worst_gap):.1f} 个百分点。"
                       if gm_above and gm_below else "")
                    + "这些区间是在被指引的那个季度开始之后才发布的，这一点写在每张图上。"
                ),
                "exhibits": settled_ex,
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": (
                    "收入与销货成本的分岔、按技术与按业务单元的两种拆法、"
                    f"{cn_count(len(periods))}个季度的利润率轨迹与下季指引隐含的毛利率环比、"
                    "每股收益从上季到本季的完整桥，"
                    + ("长期供货协议的两种口径，" if agreements is not None else "")
                    + ("以及本季还债之后的净现金。"
                       if bal["total_debt_usd_m"][-1] < bal["total_debt_usd_m"][-2]
                       else "以及净现金与总债务。")
                    + "公司对价格与出货量只给定性措辞，本页把原话放进核对表，不折算成数字；"
                    "电话会里只有措辞、没有申报数的本季结论（协议覆盖的份量、资本回报计划、"
                    "各业务单元出货位元的方向）不作图，列在本页 notes「已知未接入」一条。"
                ),
                "exhibits": highlight_ex,
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": refer(
                    f"本季本地分析稿第 8 节一共{cn_count(kpi_total)}条观察指标。"
                    f"能从 Micron 自己的申报文件算出水平的{cn_count(len(next_entries))}条："
                    "先看距阈值余量总览，再各画一张历史线。"
                    f"其余{cn_count(len(kpi['excluded']))}条（"
                    + "、".join(item["metric"] for item in kpi["excluded"])
                    + "）不作图 —— 要么是跨季条件、要么依赖公司从不给的数字、要么需要另外几家公司的申报值，"
                    "逐条原因在核对抽屉「下季阈值」表里；"
                    + ("长期供货协议与" if agreements is not None else "")
                    + "业务单元毛利率的本季读数在第二节（"
                    + ("Exhibit {EX_SCA}、" if agreements is not None else "")
                    + "Exhibit {EX_BU_GM}）。"
                ),
                "exhibits": next_ex,
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": (
                    f"{cn_count(len(annual))}个财年的营收与毛利率、资本开支与资本强度，"
                    f"以及{cn_count(len(periods))}个季度的现金三条与"
                    f"{cn_count(inventory_quarters)}个季度的存货。这一节存在的理由是给上面三节一个纵深："
                    f"本季的每一个纪录都要放在一条走过{cn_count(annual_losses)}次负毛利率的序列上读。"
                ),
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            f"本页所有季度按自然年标注。Micron 财年在最接近 8 月 31 日的那个星期四结束，故本页的 {periods[-1]} 是截至 {latest['period_end']} 的季度，公司自己称之为 {fiscal}；映射规则为公司 FY(N) 的 Q1 即本页的 Q4 (N−1)，FY(N) 的 Q2/Q3/Q4 即本页的 Q1/Q2/Q3 (N)。不统一成一种约定，跨公司对照就会把不同的三个月放在一起比较。",
            f"季度数值逐季读自 SEC EDGAR 上 Micron（CIK 723125）的 {staging['quarterly_releases_read']} 份季度业绩 8-K EX-99.1 新闻稿。每份新闻稿并排印出三个季度（本季、上季、去年同季）与三个资产负债表日期，所以除最新一季外的每个季度都被两到三份不同的文件各读了一遍；读数不一致的地方按最新一份为准并已逐条记录，本窗口内的分歧只出现在「其他经营（收益）费用」一行（各期在「重组与资产减值」和「其他经营」两行之间的归类不同）与 FY2021 年报对 FY2020 存货的重分类。",
            "因为上一条，本页不发布「其他经营（收益）费用」这一行本身，只发布它的合计值，且合计值取自恒等式：毛利 − 研发 − 销售管理及行政 − 营业利润。这个合计在每个季度、每份新闻稿里都精确闭合。",
            *([f"第一节开头的闭环与阈值结算来自本地分析稿："
               + (f"上季（{periods[-2]}）稿留下的{cn_count(len(closure['items']))}条待验证问题由本季稿第 0 节逐条核验，判定照录；"
                  if closure is not None else "")
               + (f"上季稿第 8 节的观察指标，阈值、方向与触发动作照录，本季读数由本页从业绩新闻稿、10-Q 与电话会现算；"
                  if prior is not None else "")
               + "「距阈值余量」统一以正值代表安全侧。这些阈值是本地研究设定，不是公司指引，也不构成评级或投资建议。"]
              if closure is not None or prior is not None else []),
            "第一节的指引兑现组图用的是同一批业绩 8-K：每份 EX-99.1 里那张 Business Outlook 表用同一种句式给出下一季的收入、毛利率、营业费用与每股收益；实际值取自随后一季 8-K 的合并损益表与 GAAP/non-GAAP 对账表。"
            + (f"毛利率与营业费用在最近{cn_count(point_run)}季改为单点数（Approximately），图上按零宽度的区间画，核对表里标注了哪几季是单点。" if point_run else ""),
            f"Micron 的下一季指引随上一季业绩一起发布，而它在季末约四周后发业绩，因此这张 Outlook 表落在它所指引的那个季度之内：本记录里最早第 {lag_low} 天、最晚第 {lag_high} 天、中位数第 {lag_middle} 天。这不是一份事前预测，命中率必须连同这句话一起读。",
            "本页不发布任何由公司定性措辞折算出来的数字。Micron 对售价与出货位元只给区间性措辞"
            + (f"（如{''.join(f'「{word}」' for word in words_example)}）" if words_example else "")
            + "，把这类措辞换算成一个百分比需要自选一个中点，那是假设不是算术。原话逐季收在核对抽屉的技术拆分表里；本页用来说明同一件事的，是收入与销货成本这两条申报值。",
            "按技术拆分的 DRAM / NAND / 其他三行取自各季 10-Q、10-K 收入注释里印出的美元数（Revenue by Technology），不是用百分比乘总额倒推的；三行之和逐季等于合并损益表的收入，差额为零。",
            f"业务单元序列只有{cn_count(len(units['quarters']))}个季度，因为公司从 {units['first_printed_in']} 那份业绩新闻稿起才在稿里印出这张四单元表（CMBU / CDBU / MCBU / AEBU），此前的业绩稿没有分部表，而更早的分部是 CNBU / MBU / SBU / EBU 四个不同口径。两套口径不可拼接，本页不往前补。各单元的毛利率与营业利润率是公司印出来的整数百分比，不是本页用美元数除出来的。",
            f"「调整后自由现金流」与「净资本开支」是公司自己的口径，不是本页的定义：净资本开支 = 购建固定资产支出 − 出售固定资产所得 − 收到的政府补助；调整后自由现金流 = 经营现金流 − 净资本开支。{cn_count(fcf_closed)}个季度逐季验算，全部闭合。",
            *(["长期供货协议一图把 10-Q 附注里季末已入账的数，与含季末之后签署协议的公司口径并列，并逐项标明出处："
               "剩余履约义务的公司口径（按合同最低价计的累计收入）只在业绩电话会书面发言稿里给过，"
               "存款与相关承诺那一项 10-Q 的流动性一节与书面发言稿都写了。附注口径只计入季末已签、有固定价或价格带的协议，"
               "按最低承诺量乘最低合同价计量，并排除原始期限一年以内的合同；公司在 10-Q 里明确写明该口径不代表这些合同下的未来收入。"
               "本页不发布这两者的差额，也不发布任何由此推出的收入覆盖率。"]
              if agreements is not None else []),
            # It used to say 「上一季本地分析稿」 set these seven: they are this
            # quarter's analysis's section 8. And it used to explain why there
            # was no headroom overview; there is one now, as on every page.
            f"第三节的阈值取自本季本地分析稿第 8 节：{cn_count(kpi_total)}条观察指标里有{cn_count(len(next_entries))}条能约化成一个可以从 Micron 自己的申报文件算出的水平（{'、'.join(item['metric'] for item in next_entries)}），本页先画距阈值余量总览，再各画一张历史线。其余{cn_count(len(kpi['excluded']))}条要么是跨季条件、要么依赖公司从不给的数字、要么需要另外几家公司的申报值，逐条列在核对抽屉「下季阈值」表里并写明原因，不作图也不折算。",
            "存货天数用销货成本作分母（期末存货 ÷ 当季销货成本 × 当季天数），不是用收入。在本页这一点尤其要紧：售价在窗口内涨了数倍，换成收入作分母会显示存货天数腰斩，那只是价格的影子而不是周转的改善。"
            + ("窗口内每个季度都是 91 天" if not dio_long else f"窗口内除 {'、'.join(dio_long)} 外每个季度都是 91 天")
            + "，取自申报的两个期末日期之差。"
            # The company states its own days of inventory in the prepared
            # remarks, and where it differs from this page's arithmetic the
            # published figure is the company's (site rule: official values win).
            + (f"公司在书面发言稿里给的本季存货天数是 {spoken['days_of_inventory']} 天，"
               f"本页按上式自算是 {bal['dio_days'][-1]:.0f} 天；公司没有公布它的算法，"
               "所以存货图的标题用公司的数，图里那条长线仍是本页自算、口径前后一致的序列。"
               if spoken and "days_of_inventory" in spoken
               and round(bal["dio_days"][-1]) != spoken["days_of_inventory"] else ""),
            f"{cn_count(len(annual))}财年记录中的每一年取自该财年自己的 10-K，不取自后来年报里的比较列。"
            + (f"FY{partial['fiscal_year']} 只有前{cn_count(partial['quarters'])}季在表内，本页不画未完结的财年，也不把{cn_count(partial['quarters'])}季年化。"
               if partial and partial["quarters"] < 4 else
               "本页不画未完结的财年。"),
            "核对抽屉最后那张「AI capex 循环」是全站逐字节一致的跨页对照块，不是对 Micron 的判断：它把四家云厂的现金资本开支、NVDA 的数据中心收入与 TSM 的晶圆季度串成一条链。Micron 在这条链的更上游 —— 它是内存供给方 —— 但本页刻意没有把它加成这张表的一列：那张表必须在每一页上逐字节相同，加一列等于改掉现存所有页面的同一张表。本站有若干页同样只是承载它而不出现在它的列里（Cadence、Synopsys、TSMC、NVIDIA 都是如此，且有测试专门钉住这一点）。",
            "本页只发布公司披露值、可复算的简单派生值，以及明确标注为管理层口径（非申报）的数字；D 标记代表 Derived / 自算。",
            "本页不发布评级、目标价、估值倍数或任何市场预期数字。",
            "本页已知未接入：HBM 单产品的收入与利润率（公司从未披露）、"
            + (f"Micron 在中国的收入敞口（连续{cn_count(spoken['china_exposure_unquantified_quarters'])}季被问到、"
               f"连续{cn_count(spoken['china_exposure_unquantified_quarters'])}季未量化）、"
               f"FY{spoken['capex_fiscal_year']} 的资本开支金额（只在电话会上给过区间性措辞，没有出现在任何申报文件里）、"
               if spoken else "")
            + "按地域的收入拆分（季报口径不披露）"
            + (f"、{cn_count(spoken['supply_agreements_signed'])}份长期供货协议的份数、客户构成与覆盖的 DRAM / NAND 份量"
               "（只在电话会上给过）、加大资本回报的计划（只有措辞），以及各业务单元出货位元的方向（只在电话会上给过）"
               if spoken else "")
            + "。",
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
