#!/usr/bin/env python3
"""Build the IBKR (Interactive Brokers Group) quarterly-results page.

Same four-part, chart-led shape as the other company pages (上季兑现 → 本季重点
→ 下季跟踪 → 长期常规).  Interactive Brokers' fiscal year is the calendar year,
so no quarter on this page needs remapping: the page's ``Q2 2026`` is the
quarter the company calls 2Q2026.

**Rolling a quarter edits `series/ibkr.json` and nothing else** (CLAUDE.md §9).
Every period, date, count and figure printed here is computed from the series;
every sentence that states a record, a streak or an "all of them" is printed
only while the series still says so, and switches to a sentence that is true
when it stops. What belongs to one quarter only -- the previous note's
follow-up questions as this quarter's note closes them (`followup_closure`),
the previous note's section-8 thresholds settled against this quarter
(`prior_kpi_settlement`), and this quarter's note's section-8 thresholds
(`next_kpi`) -- carries a ``period`` stamp and is read through
`board.stamped_block`: a block stamped for another quarter stops the build, an
absent block leaves its charts out. `_checks` in the series is a separate
reading of the quarter's release that the tests hold the page to; this builder
never reads it.

Section one settles what the previous note left and nothing else: (a) its
follow-up questions, counted by the verdicts this quarter's note gives them in
its section 0; (b) the thresholds in its section 8 that a filed figure can
settle, each against the same series its history chart draws. The company's own
charts that used to stand in for a settlement (its consecutive-quarter table and
the net-interest-margin record) are long records, not settlements, and live in
section four.

Three things make this page different from the ones built before it.

**No guidance record, and it is a sourcing limit rather than an editorial
choice.**  IBKR has never put a numeric quarterly outlook in a filing -- no
revenue range, no EPS range, no margin range, in any earnings 8-K in the
archive -- so part (c) of section one, a company guidance record, has nothing
to draw. Transcribing forward-looking remarks off a webcast that cannot be
checked against a second source is the failure this repo exists to avoid. (The
page used to name other pages that lack a guidance record too; by the time it
was re-read one of them had gained one, so it no longer speaks for them.)

**Coverage began with `meta.coverage_start`** -- the quarter of the first
analysis note on this company in the owner's vault (Q4 2025, 2026-03-05). On
that quarter there is no previous note to settle and section one says so. The
page once stamped its own first quarter here and printed "first coverage" on a
quarter that already had two notes behind it.

**The operating metrics are not XBRL facts.**  Accounts, customer equity, DARTs,
margin loans, credits and the net-interest-margin table are read out of the
filings' text -- the EX-99.1 of each quarterly earnings 8-K, and for the net
interest margin table's earliest quarters (the releases only print it from
3Q2017) the same table in a 10-Q's MD&A or a later release's prior-year column.
The income statement is the other way round: every quarter but the fiscal
fourth is the 10-Q's own three-month column, and the fourth is the 10-K year
minus the Q3 10-Q's nine months.

Two structural breaks are marked rather than smoothed:

* The company **renamed its per-order commission metric** at 1Q2020, from
  "Commission per DART" to "Commission per Cleared Commissionable Order".  The
  two never appear in the same release, so there is no overlap quarter to splice
  on and that series starts at 1Q2020 rather than being carried back.
* The **4-for-1 stock split** declared 2025-04-15 restated only those quarters
  that later served as a comparative, so the per-share figures in companyfacts
  are a mix of two bases.  This page therefore plots **net income available for
  common stockholders in dollars**, which is additive and split-invariant, and
  publishes no multi-quarter EPS line at all.

Published numbers are company-reported or transparent arithmetic.  No ratings,
no target prices, no broker-attributed estimates.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import (  # noqa: E402
    ai_capex_cycle_table,
    cn_count,
    cn_ordinal,
    fill_story,
    headroom,
    headroom_exhibit,
    latest_block,
    number_exhibits,
    round_half_up,
    stamped_block,
    threshold_exhibit,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "ibkr.json"
DATA_DIR = ROOT / "data"

# The recent window every 本季重点 chart uses, and the long window for 长期常规.
# The highlight charts used to show the last eight quarters. Every series they
# draw now runs the whole record, and eight quarters cannot tell a level from a
# cycle for a business whose revenue is half net interest -- so RECENT is the
# whole window, and the two lines that genuinely start later carry their own
# holes rather than shortening everybody else's axis.
RECENT = 42
LONG_STEP = 4

AUDIT_WORDS = {"unaudited": "未审计", "audited": "已审计"}

# Fixed history the prose names, not data a roll changes: the zero-rate years
# the revenue-mix note calls 零利率, and the retail wave the commission note
# ties its 2021 trough to. The builder only uses those words when the stretch
# it computed from the series actually falls in these years.
ZERO_RATE_YEARS = ("2020", "2021")
RETAIL_WAVE_YEAR = "2021"
# The pretax-margin level management counts its streak against ("margins above
# 70%"), and the one the note disputes that count at. Framing, not data.
MARGIN_FLOOR = 70

NO_GUIDANCE_NOTE = (
    "<b>IBKR 从不在申报文件里给季度数字指引</b>，所以本节没有公司指引的兑现记录。"
    "这是取数限制而不是编辑取舍：翻遍档案里的历次业绩 8-K，公司没有给过下一季的收入区间、"
    "EPS 区间或利润率区间中的任何一个。"
)


def compact_period(period: str) -> str:
    """``'Q2 2026'`` → ``'Q2'26'``."""
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


def company_period(period: str) -> str:
    """``'Q2 2026'`` → ``'2Q2026'``, the way IBKR's own releases name a quarter."""
    quarter, year = period.split()
    return f"{quarter[1]}Q{year}"


def key_period(period: str) -> str:
    """``'Q1 2020'`` → ``'2020Q1'``, the form the notes use."""
    quarter, year = period.split()
    return f"{year}{quarter}"


def previous_period(period: str) -> str:
    quarter, year = period.split()
    number = int(quarter[1])
    return f"Q4 {int(year) - 1}" if number == 1 else f"Q{number - 1} {year}"


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def rounded(values: list[float | None], digits: int = 6) -> list[float | None]:
    return [None if value is None else round(value, digits) for value in values]


def ratio(numerator: list[float | None], denominator: list[float | None]
          ) -> list[float | None]:
    return [None if None in (a, b) or b == 0 else a / b * 100
            for a, b in zip(numerator, denominator)]


def yoy(values: list[float | None]) -> list[float | None]:
    """Year-over-year percent, ``None`` for the first four quarters."""
    return [None if index < 4 or None in (values[index], values[index - 4])
            or values[index - 4] == 0
            else pct_change(values[index], values[index - 4])
            for index in range(len(values))]


def qoq(values: list[float | None]) -> list[float | None]:
    return [None if index < 1 or None in (values[index], values[index - 1])
            or values[index - 1] == 0
            else pct_change(values[index], values[index - 1])
            for index in range(len(values))]


def accounts_millions(thousands: float) -> str:
    """Accounts in millions, rounded the way the filer rounds them.

    IBKR prints 5,185 thousand accounts as "5.19 million"; binary float
    formatting prints 5.18 (see `board.round_half_up`). Every accounts figure on
    this page goes through here, so the page never prints a number the company
    did not.
    """
    return round_half_up(thousands / 1000, 2)


def tenths_word(value: float) -> str:
    """``34.1`` → ``'三成'``: the floor of a percentage in tenths, in words."""
    return f"{cn_ordinal(int(value // 10))}成"


def share_words(share: float) -> str:
    """The nearest simple fraction of a whole, in words: 0.767 → 「四分之三」."""
    best = min(((numerator, denominator) for denominator in range(2, 6)
                for numerator in range(1, denominator)),
               key=lambda pair: abs(share - pair[0] / pair[1]))
    if best == (1, 2):
        return "一半"
    return f"{cn_ordinal(best[1])}分之{cn_ordinal(best[0])}"


def runs(flags: list[bool]) -> list[tuple[int, int, bool]]:
    """Maximal stretches of equal flags as ``(start, stop, flag)``, stop exclusive."""
    stretches = []
    start = 0
    for index in range(1, len(flags) + 1):
        if index == len(flags) or flags[index] != flags[start]:
            stretches.append((start, index, flags[start]))
            start = index
    return stretches


def trailing_streak(values: list[float | None], test) -> int:
    streak = 0
    for value in reversed([value for value in values if value is not None]):
        if not test(value):
            break
        streak += 1
    return streak


def plain_text(html: str) -> str:
    """Strip inline markup for the two slots the renderer escapes rather than parses.

    `assets/page.js` writes exhibit notes with `innerHTML` but runs section
    descriptions and the 口径与方法说明 list through `esc()`, so a `<b>` that
    reads as emphasis on a chart caption reaches the reader as the literal
    characters `<b>` in those two places.
    """
    return re.sub(r"<[^>]+>", "", html)


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


RELEASE_SOURCE = "各季业绩 8-K 的 EX-99.1「Operating Data」与「Net Interest Margin」两表。"
# The release only prints the net-interest-margin table from 3Q2017. The
# earlier quarters on these charts were read from the same table in a 10-Q's
# MD&A (1Q2016's 44,572 / 1.14% is in the 1Q2017 10-Q, not in any release) or
# from a later release's prior-year column, and the caption says so.
NIM_SOURCE = ("各季业绩 8-K 的 EX-99.1「Net Interest Margin」表；该表 3Q2017 起才进新闻稿，"
              "更早的季度读自 10-Q 管理层讨论里的同一张表或一年后新闻稿的去年同期列。")
INCOME_SOURCE = ("各季 10-Q 合并损益表；会计第四季为 10-K 全年数减去第三季 10-Q 的九个月栏，"
                 "两端都是申报值。")


def is_first_coverage(staging: dict) -> bool:
    return staging["periods"][-1] == staging["meta"]["coverage_start"]


# ── thresholds: one registry for both ends of the loop ─────────────────────

KPI_TEXT = {
    "k_accounts": lambda value: f"{value:,.0f}K",
    "pct2": lambda value: f"{value:.2f}%",
    "pct": lambda value: f"{value:.1f}%",
    "usd_eps": lambda value: f"US${value:.2f}",
    "usd_bn": lambda value: f"US${value:,.1f}B",
    "usd_m": lambda value: f"US${value:,.0f}M",
}


def kpi_text(unit: str, value: float) -> str:
    """A threshold or a reading in its own unit, the way this page prints it.

    `board.unit_text` prints every percentage to one decimal, so a 1.80%
    net-interest-margin line and a 1.93% quarter would read "1.8%" and "1.9%";
    it also has no unit for a count of accounts. This page's thresholds print
    through here instead.
    """
    return KPI_TEXT[unit](value)


def net_adds(accounts: list[float | None]) -> list[float | None]:
    """Quarter-end accounts minus the quarter before: the quarter's net adds (D)."""
    return [None] + [None if None in (a, b) else b - a for a, b in zip(accounts, accounts[1:])]


def first_reported(values: list[float | None]) -> int:
    return next(index for index, value in enumerate(values) if value is not None)


def kpi_registry(staging: dict) -> dict:
    """Every series a section-8 threshold -- this quarter's or the last one's -- reads.

    An entry names its series by `reads`; this is where that becomes values, a
    unit, a format and the sentences about the series that do not change with
    the quarter. A threshold on a series that is not here stops the build: it
    has no history to draw, and inventing one is not a roll. `history: False`
    marks a series with too few filed cells to draw -- it settles on the
    headroom chart only, and the note says why.
    """
    periods = staging["periods"]
    financials = staging["financials_usd_m"]
    operating = staging["operating"]
    nim = staging["nim"]
    adds = net_adds(operating["accounts_thousands"])
    commission = operating["commission_per_order_usd"]
    margin_loans = operating["customer_margin_loans_usd_bn"]
    credits = operating["customer_credits_usd_bn"]
    credits_to_equity = ratio(credits, operating["customer_equity_usd_bn"])
    bad_debt = financials["customer_bad_debt"]
    lending = nim["securities_lending_all_in_usd_m"]
    nim_pct = nim["nim_pct"]

    def adds_note() -> str:
        return (f"本季净增 {adds[-1]:,.0f}K，是季末账户数之差（D）。阈值原文按月度写、笔记自己换算成季度；"
                "本页只有各季末的账户数，画的是季度净增，季内某一个月跌破在这张图上看不到。")

    def margin_loan_note() -> str:
        start = first_reported(margin_loans)
        if start == 0:
            span = ("这条线跑满全窗口：公司在 2019 年及之前的新闻稿里把这个余额叫 customer debits，"
                    "1Q2020 起改叫 Customer margin loans，口径没有变。")
        else:
            span = f"这条线从 {key_period(periods[start])} 起算：公司在此之前不在新闻稿里按季给这个余额。"
        return (f"本季 US${margin_loans[-1]:,.1f}B，同比 {signed(pct_change(margin_loans[-1], margin_loans[-5]))}。"
                "阈值原文按月度读数写，本页只有季末余额（即当季最后一个月的读数），季中某月越线在这张图上看不到。"
                "保证金贷款是净利息收入里收益率最高的一块资产，所以它比客户权益更直接地决定下一季的净利息收入。"
                + span)

    def nim_note() -> str:
        return (f"本季 {nim_pct[-1]:.2f}%，环比 {nim_pct[-1] - nim_pct[-2]:+.2f}pp、"
                f"同比 {nim_pct[-1] - nim_pct[-5]:+.2f}pp。净息差是公司在新闻稿净息差表里印的数，不是本页自算。")

    story = stamped_block(staging, "quarter_story", periods[-1]) or {}

    def commission_note() -> str:
        return (f"本季 US${commission[-1]:.2f}。"
                f"这条线在 {operating['commission_metric_from']} 之前是空的，"
                "因为公司当时公布的是另一个口径的指标（Commission per DART），详见 Exhibit {EX_COMMISSION}。"
                + (story["commission_reading"] + "。" if story.get("commission_reading") else ""))

    def bad_debt_note() -> str:
        return (f"本季 US${bad_debt[-1]:,.0f}M。坏账是客户亏损超过其在 IBKR 的资产、公司追不回的净额，"
                "取自各季 10-Q 损益表（会计第四季为全年减九个月）。")

    def credits_note() -> str:
        start = first_reported(credits)
        return (f"本季 US${credits[-1]:,.1f}B，环比 {signed(pct_change(credits[-1], credits[-2]))}、"
                f"同比 {signed(pct_change(credits[-1], credits[-5]))}。"
                f"这条线从 {key_period(periods[start])} 起算：公司在此之前不在业绩新闻稿里按季给这个期末余额。")

    def cushion_note() -> str:
        start = first_reported(credits_to_equity)
        return (f"本季 {credits_to_equity[-1]:.1f}%：客户贷方余额 ÷ 客户权益，两个分量都是公司披露值（D）。"
                f"这条线从 {key_period(periods[start])} 起算，因为贷方余额从那一季起才按季披露。"
                "比率越低，客户账上的现金垫越薄、仓位越满。")

    return {
        "net_adds": {"values": adds, "fmt": "f0c", "ylab": "千户", "noun": "季度净增账户",
                     "unit": "k_accounts", "note": adds_note, "src_extra": RELEASE_SOURCE},
        "margin_loans": {"values": margin_loans, "fmt": "f0c", "ylab": "US$B",
                         "noun": "客户保证金贷款（季末）", "unit": "usd_bn",
                         "note": margin_loan_note, "src_extra": RELEASE_SOURCE},
        "nim": {"values": nim_pct, "fmt": "pct2", "ylab": "年化", "noun": "净息差 NIM",
                "unit": "pct2", "note": nim_note, "src_extra": NIM_SOURCE},
        "commission_per_order": {"values": commission, "fmt": "usd2", "ylab": "US$ / 笔",
                                 "noun": "每笔已清算订单佣金", "unit": "usd_eps",
                                 "note": commission_note,
                                 "src_extra": RELEASE_SOURCE + (story.get("commission_source", "")
                                                                if story.get("commission_reading") else "")},
        "bad_debt": {"values": bad_debt, "fmt": "f0c", "ylab": "US$M", "noun": "客户坏账",
                     "unit": "usd_m", "note": bad_debt_note, "src_extra": INCOME_SOURCE},
        "customer_credits": {"values": credits, "fmt": "f0c", "ylab": "US$B", "noun": "客户贷方余额",
                             "unit": "usd_bn", "note": credits_note, "src_extra": RELEASE_SOURCE},
        "credits_to_equity": {"values": credits_to_equity, "fmt": "pct1", "ylab": "占客户权益",
                              "noun": "客户贷方余额 / 客户权益", "unit": "pct",
                              "note": cushion_note, "src_extra": RELEASE_SOURCE},
        "securities_lending_all_in": {"values": lending, "noun": "全口径证券借贷净利息",
                                      "unit": "usd_m", "history": False},
    }


def read_entries(staging: dict, block: dict, key: str) -> list[dict]:
    """The block's thresholds, each with its reading off the series it names.

    The reading is the last cell of the same series the history chart draws,
    so the headroom bar and the line cannot disagree about where the quarter
    landed.
    """
    registry = kpi_registry(staging)
    entries = []
    for entry in block["quantified"]:
        if entry["reads"] not in registry:
            raise ValueError(f"threshold {entry['metric']!r} reads {entry['reads']!r}, "
                             "which build/ibkr.py has no series for: map it in kpi_registry")
        if key in entry:
            raise ValueError(f"threshold {entry['metric']!r} carries a typed {key!r}; "
                             "it is read off the series")
        value = registry[entry["reads"]]["values"][-1]
        if value is None:
            raise ValueError(f"threshold {entry['metric']!r}: the series it reads has no value this quarter")
        entries.append({**entry, key: value})
    return entries


def line_label(entry: dict) -> str:
    """``'客户坏账 · 单季线'`` → ``'单季线'``: the part that tells two lines on one series apart."""
    return entry["metric"].split(" · ")[-1]


def multi_threshold_exhibit(title: str, staging: dict, spec: dict, entries: list[dict], *,
                            threshold_label: str, note: str) -> dict:
    """One series against every threshold set on it, each as its own flat line.

    `board.threshold_exhibit` draws one threshold; a metric the note bounds from
    both sides (or with a warning line under a confirmation line) needs each of
    them on the same axis, or the reader sees half of what was set.
    """
    labels = [compact_period(period) for period in staging["periods"]]
    first, *rest = entries

    def name(entry: dict) -> str:
        if len(entries) == 1:
            return f"{threshold_label} {kpi_text(entry['unit'], entry['threshold'])}"
        return f"{threshold_label}：{line_label(entry)} {kpi_text(entry['unit'], entry['threshold'])}"

    chart = threshold_exhibit(
        title, labels, rounded(spec["values"]), first["threshold"],
        fmt=spec["fmt"], xstep=LONG_STEP, ylab=spec["ylab"], actual_name=spec["noun"],
        threshold_name=name(first), note=note, src_extra=spec["src_extra"],
    )
    for entry, color in zip(rest, ("GOLD", "GRAY", "MBLUE")):
        chart["series"].append({"name": name(entry), "values": [entry["threshold"]] * len(labels),
                                "color": color})
    return chart


def threshold_history(staging: dict, entries: list[dict], value_key: str) -> str:
    """How often the drawn window sat on the wrong side of each line, and when last.

    A threshold means little without the record under it: the net-interest-margin
    Bear line sits above every quarter of the zero-rate years, the single-quarter
    bad-debt line was crossed once. Counted here, never typed.
    """
    registry = kpi_registry(staging)
    periods = staging["periods"]
    parts = []
    for entry in entries:
        values = registry[entry["reads"]]["values"]
        earlier = [index for index, value in enumerate(values[:-1]) if value is not None]
        wrong = [index for index in earlier
                 if headroom(entry["direction"], entry["threshold"], values[index]) < 0]
        text = kpi_text(entry["unit"], entry["threshold"])
        side = "低于" if entry["direction"] == "up" else "高于"
        if not wrong:
            parts.append(f"此前没有一季{side} {text}")
        elif len(wrong) == len(earlier):
            parts.append(f"此前{cn_count(len(wrong))}季全部{side} {text}，本季是第一次到了安全侧")
        elif len(wrong) == 1:
            index = wrong[0]
            parts.append(f"此前{side} {text} 的只有 {key_period(periods[index])}"
                         f"（{kpi_text(entry['unit'], values[index])}）")
        else:
            parts.append(f"此前有{cn_count(len(wrong))}季{side} {text}，最近一次是 "
                         f"{key_period(periods[wrong[-1]])}")
    return "；".join(parts) + "。"


def consecutive_words(staging: dict, entries: list[dict]) -> str:
    """For a line that counts only after N quarters in a row: where this quarter stands."""
    registry = kpi_registry(staging)
    parts = []
    for entry in entries:
        rule = entry.get("consecutive")
        if not rule:
            continue
        values = registry[entry["reads"]]["values"]
        run = 0
        for value in reversed(values):
            if value is None or value < entry["threshold"]:
                break
            run += 1
        text = kpi_text(entry["unit"], entry["threshold"])
        standing = ("本季不在线上。" if not run else "本季是第一季。" if run == 1
                    else f"到本季已连续{cn_count(run)}季。")
        parts.append(f"{line_label(entry)}要连续{cn_count(rule['quarters'])}季 ≥ {text} 才{rule['verb']}："
                     + standing)
    return "".join(parts)


def kpi_table(n: int, title: str, entries: list[dict], value_key: str, value_head: str) -> dict:
    """The audit table behind a headroom chart, in each threshold's own unit."""
    return {
        "n": n,
        "title": title,
        "headers": ["笔记第 8 节", "指标", "方向", "阈值", value_head, "余量 D"],
        "rows": [[f"第 {entry['row']} 行", entry["metric"],
                  "高于阈值为安全" if entry["direction"] == "up" else "低于阈值为安全",
                  kpi_text(entry["unit"], entry["threshold"]),
                  kpi_text(entry["unit"], entry[value_key]),
                  f"{headroom(entry['direction'], entry['threshold'], entry[value_key]) + 0.0:+.1f}%"]
                 for entry in entries],
    }


def zero_safe(chart: dict) -> dict:
    """A bar exactly on its line is 0.0, not −0.0: the renderer prints the sign."""
    chart["values"] = [0.0 if value == 0 else value for value in chart["values"]]
    return chart


# ── section one ─────────────────────────────────────────────────────────────

def closure_values(staging: dict) -> dict[str, str]:
    """Numbers a `followup_closure` / `prior_kpi_settlement` sentence may name.

    The sentences belong to one quarter and live in the series; the figures in
    them are the arrays' and are filled here, so the two cannot disagree.
    """
    operating = staging["operating"]
    accounts = operating["accounts_thousands"]
    equity = operating["customer_equity_usd_bn"]
    credits = operating["customer_credits_usd_bn"]
    return {
        "net_adds": f"{accounts[-1] - accounts[-2]:,.0f}K",
        "equity_qoq": signed(pct_change(equity[-1], equity[-2])),
        "accounts_yoy": signed(pct_change(accounts[-1], accounts[-5])),
        "credits_now": f"US${credits[-1]:,.1f}B",
        "credits_prev": f"US${credits[-2]:,.1f}B",
    }


def closure_exhibit(staging: dict, closure: dict) -> dict:
    """(a) The previous note's follow-up questions, as this quarter's note closes them.

    The counts are the verdicts of the note's section 0, counted here from the
    per-question verdicts rather than typed, so the title cannot drift from the
    list it summarises.
    """
    labels = closure["labels"]
    items = closure["items"]
    unknown = sorted({item["verdict"] for item in items} - set(labels))
    if unknown:
        raise ValueError(f"series block `followup_closure` has verdicts {unknown} "
                         f"that are not among its labels {labels}")
    counts = [sum(1 for item in items if item["verdict"] == label) for label in labels]
    values = closure_values(staging)
    groups = []
    for label, count in zip(labels, counts):
        if count:
            texts = [fill_story(item["text"], values) for item in items if item["verdict"] == label]
            groups.append(f"{label}的{cn_count(count)}条：" + "；".join(texts) + "。")
    return {
        "kind": "bars_labeled",
        "title": (f"上季 {len(items)} 条待验证问题：" + "、".join(
            f"{count} 条{label}" for label, count in zip(labels, counts) if count)),
        "xlabels": list(labels),
        "values": counts,
        "legend": "问题条数",
        "fmt": "f0",
        "yfmt": "f0",
        "label_fmt": "f0",
        "ylab": "条",
        "note": "".join(groups),
        "src_extra": ("问题清单是上季（" + closure["set_in"] + "）分析笔记文末的 Follow-up，"
                      "判定取自本季分析笔记第 0 节；数字一律按本季新闻稿与申报现算。"),
    }


def settlement_exhibits(staging: dict, settlement: dict) -> list[dict]:
    """(b) The previous note's section-8 thresholds against this quarter's figures.

    Only rows a filed figure can settle go on the headroom chart; every other
    row of that section is named in the note with the reason it is not there,
    so a row that could not be settled is never silently dropped.
    """
    registry = kpi_registry(staging)
    entries = read_entries(staging, settlement, "actual")
    held = [entry for entry in entries
            if headroom(entry["direction"], entry["threshold"], entry["actual"]) >= 0]
    values = closure_values(staging)
    eps = settlement["eps_leg"]["adjusted_diluted_eps_usd"]
    eps_growth = pct_change(eps["this_quarter"], eps["year_ago"])
    eps_words = (
        f"第 {settlement['eps_leg']['row']} 行「{settlement['eps_leg']['words']}」的 Q2 那一腿"
        + ("成立" if eps_growth > 0 else "没有成立")
        + f"：调整后摊薄 EPS ${eps['this_quarter']:.2f}，去年同季 ${eps['year_ago']:.2f}，"
        f"同比 {signed(eps_growth)}。它的阈值落在零上，「距阈值 %」没有定义，所以不进这张图。"
    )
    rows_in_chart = sorted({entry["row"] for entry in entries})
    note = (
        "正值 = 仍在安全侧。"
        f"上季笔记第 8 节共 {settlement['rows']} 行，能用本季申报数结算的是第 "
        + "、".join(str(row) for row in rows_in_chart)
        + f" 行的这{cn_count(len(entries))}条线。"
        + eps_words
        + "其余各行——"
        + "；".join(f"第 {item['row']} 行：{fill_story(item['text'], values)}"
                   for item in settlement["not_settled"])
        + "。"
    )
    if len(held) == len(entries):
        verdict = f"{cn_count(len(entries))}条都守住" if len(entries) > 1 else "守住"
    else:
        verdict = f"{len(held)} 条守住、{len(entries) - len(held)} 条被击穿"
    charts = [zero_safe({
        **headroom_exhibit(
            f"上季 {len(entries)} 条量化阈值：{verdict}",
            entries, "actual", note=note,
            src_extra=("阈值逐字取自上季（" + settlement["set_in"] + "）分析笔记第 8 节，不是公司指引；"
                       "实际值取自本页各条序列的最后一格。"),
        ),
        "ref": "EX_PRIOR",
    })]
    slip = settlement.get("report_slip")
    for reads in dict.fromkeys(entry["reads"] for entry in entries):
        spec = registry[reads]
        group = [entry for entry in entries if entry["reads"] == reads]
        lines = "、".join(f"{line_label(entry)} {kpi_text(entry['unit'], entry['threshold'])}"
                         for entry in group)
        kept = all(headroom(e["direction"], e["threshold"], e["actual"]) >= 0 for e in group)
        broke = all(headroom(e["direction"], e["threshold"], e["actual"]) < 0 for e in group)
        word = "守住" if kept else "击穿" if broke else "守住一部分"
        chart = multi_threshold_exhibit(
            f"{spec['noun']} {kpi_text(group[0]['unit'], group[0]['actual'])}："
            f"{word}上季阈值（{lines}）",
            staging, spec, group, threshold_label="上季阈值",
            note=(spec["note"]()
                  + "上季笔记的条件：" + "；".join(
                      fill_story(entry["words"], {"threshold": kpi_text(entry["unit"], entry["threshold"])})
                      for entry in group) + "。"),
        )
        if slip and reads == "customer_credits":
            payables = slip["payables_to_customers_usd_m"]
            prev_period, now_period = staging["periods"][-2], staging["periods"][-1]
            chart["src_extra"] += fill_story(slip["text"], {
                **values,
                "payables_prev": f"US${payables[prev_period] / 1000:,.1f}B",
                "payables_now": f"US${payables[now_period] / 1000:,.1f}B",
            }) + "。"
        charts.append(chart)
    return charts


# ── section four: the company's own records ────────────────────────────────

def consecutive_record(staging: dict) -> dict:
    """The company's own sequential comparison, carried across the whole record.

    IBKR prints a "Consecutive Quarters" table in every release -- this quarter
    against the one before it -- so the sequential move is the company's own
    published object rather than something this page invents. One quarter of it
    says nothing; the full run says whether a negative quarter is normal. It
    used to open section one as a stand-in for a settlement; it is a record.
    """
    periods = staging["periods"]
    operating = staging["operating"]
    accounts = qoq(operating["accounts_thousands"])
    equity = qoq(operating["customer_equity_usd_bn"])
    darts = qoq(operating["darts_thousands"])
    finished = [value for value in accounts if value is not None]
    negative_equity = sum(1 for value in equity[1:] if value is not None and value < 0)
    negative_accounts = sum(1 for value in finished if value < 0)
    opening = "公司自己每季都印一张环比表：本图把它拉成完整记录。"
    # "Almost never" is a claim about the count, so the count decides the words.
    if negative_accounts == 0:
        accounts_words = f"账户数从未环比下滑（{len(finished)} 季里没有一季为负）"
    elif negative_accounts * 10 <= len(finished):
        accounts_words = (f"账户数几乎从不环比下滑（{len(finished)} 季里仅 "
                          f"{negative_accounts} 季为负）")
    else:
        accounts_words = f"账户数 {len(finished)} 季里有 {negative_accounts} 季环比下滑"
    equity_words = ("客户权益却有" if negative_equity > negative_accounts else "客户权益有")
    return {
        "ref": "EX_QOQ",
        "kind": "lines",
        "title": (
            f"公司自印的环比表拉成 {len(finished)} 季记录："
            f"账户数 {len(finished)} 季里 {len(finished) - negative_accounts} 季环比为正，"
            f"客户权益 {negative_equity} 季为负"
        ),
        "xlabels": [compact_period(period) for period in periods],
        "xstep": LONG_STEP,
        "xrot": 90,
        "series": [
            {"name": "账户数 环比", "values": rounded(accounts), "color": "NAVY"},
            {"name": "客户权益 环比", "values": rounded(equity), "color": "BLUE"},
            {"name": "DARTs 环比", "values": rounded(darts), "color": "GOLD"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "环比增速",
        "zero_line": True,
        "note": (
            opening
            + f"{accounts_words}，{equity_words} {negative_equity} 季为负 —— 这是两条性质不同的线，"
            "前者是揽客，后者同时含市值波动。把客户权益的环比读成揽客成果，"
            "会在下跌季里把一次行情记成经营失利，在上涨季里反过来记成揽客成功。"
        ),
        "src_extra": RELEASE_SOURCE,
    }


def nim_record(staging: dict) -> dict:
    """Net interest margin against the same quarter a year earlier."""
    periods = staging["periods"]
    nim = staging["nim"]["nim_pct"]
    delta = [None if index < 4 or None in (nim[index], nim[index - 4])
             else nim[index] - nim[index - 4]
             for index in range(len(nim))]
    finished = [value for value in delta if value is not None]
    negative = sum(1 for value in finished if value < 0)
    streak = trailing_streak(finished, lambda value: value < 0)
    if streak >= 2:
        streak_title = f"最近连续 {streak} 季低于一年前"
        streak_note = (f"最近这 {streak} 季连续为负，正是本页头条要讲的事：规模在涨，价在跌。"
                       if volume_up_price_down(staging) else f"最近这 {streak} 季连续为负。")
    elif streak == 1:
        streak_title = "最近一季低于一年前"
        streak_note = "最近一季为负。"
    else:
        streak_title = "最近一季不低于一年前"
        streak_note = "最近一季不为负。"
    return {
        "ref": "EX_NIM_YOY",
        "kind": "grouped_bars",
        "title": f"净息差相对一年前：{len(finished)} 季里 {negative} 季为负，{streak_title}",
        "xlabels": [compact_period(period) for period in periods],
        "xstep": LONG_STEP,
        "xrot": 90,
        "groups": [{"name": "NIM 同比变化", "color": "BLUE", "values": rounded(delta)}],
        "bar_labels": False,
        "fmt": "pp1",
        "label_fmt": "pp1",
        "ylab": "pp vs 一年前",
        "note": (
            "净息差是公司自己在每份业绩新闻稿的「Net Interest Margin」表里印的数，不是本页自算。"
            "把它对一年前作差，是为了避开季节性：客户余额和交易量都有季度节奏，"
            "而利率周期没有。"
            "<b>本图单位是百分点</b>，与规模那几张的百分比不可直接比大小 —— "
            "率的变化取算术差，除一次只会得到一个没人引用的数。"
            + streak_note
        ),
        "src_extra": NIM_SOURCE,
    }


def scale_yoy(staging: dict) -> list[float]:
    """Accounts, customer equity and DARTs against a year earlier, in that order."""
    operating = staging["operating"]
    return [pct_change(operating[key][-1], operating[key][-5])
            for key in ("accounts_thousands", "customer_equity_usd_bn", "darts_thousands")]


YIELD_LINES = (
    ("yield_margin_loans_pct", "保证金贷款"),
    ("yield_segregated_pct", "隔离资金"),
    ("yield_credits_pct", "客户贷方付息"),
)


def yields_down(staging: dict) -> list[bool]:
    """Whether each of the three printed yields is below its year-ago value."""
    nim = staging["nim"]
    return [nim[key][-1] < nim[key][-5] for key, _ in YIELD_LINES]


def nim_down(staging: dict) -> bool:
    nim = staging["nim"]["nim_pct"]
    return nim[-1] < nim[-5]


def volume_up_price_down(staging: dict) -> bool:
    """The page's thesis, as a condition: every scale line up, the margin down."""
    return min(scale_yoy(staging)) > 0 and nim_down(staging)


def is_record(values: list[float | None]) -> bool:
    return values[-1] == max(value for value in values if value is not None)


# ── section two ─────────────────────────────────────────────────────────────

def revenue_quarter(staging: dict) -> dict:
    periods = staging["periods"][-RECENT:]
    financials = staging["financials_usd_m"]
    revenue = financials["total_net_revenues"]
    if is_record(revenue):
        record_words = "本季创纪录，但增长的构成才是问题所在："
    else:
        peak = max(revenue)
        record_words = (f"本季低于 {staging['periods'][revenue.index(peak)]} 的 "
                        f"US${peak:,.0f}M 纪录；增长的构成见这里：")
    return {
        "ref": "EX_REV",
        "kind": "gs_bar",
        "title": (
            f"总净收入 US${revenue[-1]:,.0f}M、同比 "
            f"{signed(pct_change(revenue[-1], revenue[-5]))}"
        ),
        "xlabels": [compact_period(period) for period in periods],
        "xstep": LONG_STEP,
        "values": rounded(revenue[-RECENT:]),
        "legend": "总净收入",
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$M",
        "ylab2": "同比增速",
        "yoy": {
            "name": "总净收入 YoY (RHS)",
            "values": rounded(yoy(revenue)[-RECENT:]),
            "color": "GREEN",
            "yfmt": "pct1",
        },
        "note": (
            "总净收入 = 佣金 + 其他费用与服务 + 其他收入 + 净利息收入，公司损益表的小计行。"
            + record_words
            + "见 Exhibit {EX_MIX} 的结构与 Exhibit {EX_NIM} 的价格。"
            "注意这条线自带噪音 —— 其中「其他收入」含公司的货币多元化头寸损益，"
            "见 Exhibit {EX_OTHER}。"
        ),
        "src_extra": INCOME_SOURCE,
    }


def revenue_mix_quarter(staging: dict) -> dict:
    periods = staging["periods"][-RECENT:]
    financials = staging["financials_usd_m"]
    revenue = financials["total_net_revenues"]
    net_interest = financials["net_interest_income"]
    share = ratio(net_interest, revenue)
    if share[-1] > 50:
        lead = "<b>这家券商一半以上的收入不来自交易佣金，而来自客户余额的利差。</b>"
    else:
        lead = f"<b>本季净利息只占这家券商总净收入的 {share[-1]:.1f}%，没有过半。</b>"
    return {
        "ref": "EX_MIX",
        "kind": "stacked_dual",
        "title": (
            f"收入三条腿：净利息 US${net_interest[-1]:,.0f}M，占总净收入 {share[-1]:.1f}%"
        ),
        "xlabels": [compact_period(period) for period in periods],
        "xstep": LONG_STEP,
        "stacks": [
            {"name": "净利息收入", "color": "NAVY",
             "values": rounded(net_interest[-RECENT:])},
            {"name": "佣金", "color": "BLUE",
             "values": rounded(financials["commissions"][-RECENT:])},
            {"name": "其他费用与服务 + 其他收入", "color": "GOLD",
             "values": rounded([
                 None if None in (fee, other) else fee + other
                 for fee, other in zip(financials["other_fees_and_services"][-RECENT:],
                                       financials["other_income"][-RECENT:])])},
        ],
        # `stacked_dual` hard-codes its right axis to 0-60 unless `ymax` is
        # given *inside* `line` -- put it at the exhibit's top level and it is
        # silently ignored. On eight quarters this share never reached 60; on
        # the whole record it does, and the line was drawn off the canvas.
        "line": {"name": "净利息占比 (RHS)", "color": "RED",
                 "values": rounded(share[-RECENT:]), "yfmt": "pct1",
                 "ymax": 100},
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$M",
        "ylab2": "净利息占比",
        "note": (
            lead
            + f"本季净利息 US${net_interest[-1]:,.0f}M 对佣金 "
            f"US${financials['commissions'][-1]:,.0f}M，前者是后者的 "
            f"{net_interest[-1] / financials['commissions'][-1]:.2f} 倍。"
            "这也是为什么本页把净息差放在与交易量同等的位置："
            "对 IBKR 来说，利率是收入的价格，不是背景。"
            "这个占比的长期迁移见 Exhibit {EX_MIX_LONG}。"
        ),
        "src_extra": INCOME_SOURCE,
    }


def nim_and_yields(staging: dict, story: dict) -> dict:
    periods = staging["periods"][-RECENT:]
    nim = staging["nim"]
    down = yields_down(staging)
    if all(down):
        title_tail = "；三条年化收益率同比全线下行"
    else:
        title_tail = f"；三条年化收益率同比{cn_count(sum(down))}条下行"
    comparisons = "，".join(
        f"{name} {nim[key][-5]:.2f}% → {nim[key][-1]:.2f}%"
        for key, name in (("yield_margin_loans_pct", "保证金贷款"),
                          ("yield_segregated_pct", "隔离资金"),
                          ("yield_credits_pct", "客户贷方付息")))
    if all(down) and nim_down(staging):
        reading = ("付息率同时下降，说明利差的压缩比资产端收益率的降幅要小 —— "
                   "但方向是一致的，四条线同比没有一条在往上走。")
    else:
        rising = [name for (key, name), fell in zip(YIELD_LINES, down) if not fell]
        if not nim_down(staging):
            rising.append("净息差")
        reading = f"四条线同比并不同向：{'、'.join(rising)}没有下行。"
    # The note's reading of the quarter is sequential: the margin ticked up
    # while every component yield stood still. Both halves are read off the
    # table here, including when the last rise before this one was.
    nim_pct = nim["nim_pct"]
    step = nim_pct[-1] - nim_pct[-2]
    flat = max(abs(nim[key][-1] - nim[key][-2]) for key, _ in YIELD_LINES)
    if step > 0:
        rises = [index for index in range(1, len(nim_pct) - 1) if nim_pct[index] > nim_pct[index - 1]]
        sequential = (f"环比 {step:+.2f}pp，是 {key_period(staging['periods'][rises[-1]])} 之后的第一次回升"
                      if rises else f"环比 {step:+.2f}pp")
        if flat * 2 < step:
            sequential += (f"，而三条分部收益率环比变动都不超过 {flat:.2f}pp —— "
                           "这一季的回升不是利率给的")
        sequential += ("；" + story["nim_reading"] if story.get("nim_reading") else "") + "。"
    elif step < 0:
        falls = 0
        for index in range(len(nim_pct) - 1, 0, -1):
            if nim_pct[index] >= nim_pct[index - 1]:
                break
            falls += 1
        sequential = f"环比 {step:+.2f}pp，已连续{cn_count(falls)}季环比下行。"
    else:
        sequential = "环比持平。"
    return {
        "ref": "EX_NIM",
        "kind": "lines",
        "title": (
            f"净息差 {nim_pct[-1]:.2f}%，同比 "
            f"{nim_pct[-1] - nim_pct[-5]:+.2f}pp、环比 {step:+.2f}pp{title_tail}"
        ),
        "xlabels": [compact_period(period) for period in periods],
        "xstep": LONG_STEP,
        "series": [
            {"name": "保证金贷款收益率", "values": rounded(nim["yield_margin_loans_pct"][-RECENT:]),
             "color": "NAVY"},
            {"name": "隔离资金收益率", "values": rounded(nim["yield_segregated_pct"][-RECENT:]),
             "color": "BLUE"},
            {"name": "客户贷方余额付息率", "values": rounded(nim["yield_credits_pct"][-RECENT:]),
             "color": "GOLD"},
            {"name": "净息差 NIM", "values": rounded(nim["nim_pct"][-RECENT:]),
             "color": "RED"},
        ],
        "fmt": "pct2",
        "yfmt": "pct2",
        "label_fmt": "pct2",
        "end_label": True,
        "ylab": "年化",
        "note": (
            "<b>本页的核心矛盾在这张图上。</b>四条线全部是公司自己在净息差表里印的年化数字，"
            "不是本页自算。同比看："
            f"{comparisons}。"
            + reading
            + "净息差" + sequential
            + "纵轴不自 0 起，但没有任何点被截掉。"
        ),
        "src_extra": NIM_SOURCE,
    }


def customer_scale(staging: dict) -> dict:
    periods = staging["periods"][-RECENT:]
    operating = staging["operating"]
    accounts = operating["accounts_thousands"]
    equity = operating["customer_equity_usd_bn"]
    equity_yoy = pct_change(equity[-1], equity[-5])
    accounts_yoy = pct_change(accounts[-1], accounts[-5])
    floor = min(equity_yoy, accounts_yoy)
    if floor >= 10:
        why = (f"是因为它们本季给出的答案一致：规模两端都在以{tenths_word(floor)}以上的速度扩张。")
    else:
        why = (f"是为了并排看规模的两端：本季客户权益同比 {signed(equity_yoy)}，"
               f"账户数同比 {signed(accounts_yoy)}。")
    return {
        "ref": "EX_SCALE",
        "kind": "gs_bar",
        "title": (
            f"客户权益 US${equity[-1]:,.1f}B、同比 {signed(equity_yoy)}；"
            f"账户数 {accounts_millions(accounts[-1])} 百万、同比 "
            f"{signed(accounts_yoy)}"
        ),
        "xlabels": [compact_period(period) for period in periods],
        "xstep": LONG_STEP,
        "values": rounded(equity[-RECENT:]),
        "legend": "客户权益",
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$B",
        "ylab2": "账户数同比",
        "yoy": {
            "name": "账户数 YoY (RHS)",
            "values": rounded(yoy(accounts)[-RECENT:]),
            "color": "GREEN",
            "yfmt": "pct1",
        },
        "note": (
            "柱是客户权益（US$B），右轴线是<b>账户数</b>的同比 —— 两个不同的量放在一张图上，"
            + why
            + "<b>但客户权益不是净流入。</b>公司披露的是期末权益，其变动同时包含客户净入金与市值波动，"
            "申报文件里没有把两者分开，所以本页不发布任何「净流入」口径的数字，"
            "也不用权益的环比变动去近似它。"
        ),
        "src_extra": RELEASE_SOURCE,
    }


def upc_wedge(staging: dict) -> dict:
    periods = staging["periods"][-RECENT:]
    financials = staging["financials_usd_m"]
    net_income = financials["net_income"]
    nci = financials["net_income_noncontrolling"]
    common = financials["net_income_common"]
    share = ratio(nci, net_income)
    multiple = net_income[-1] / common[-1] if common[-1] > 0 else None
    if multiple is not None and multiple >= 1.5:
        gap = f"是两个相差{cn_count(round(multiple))}倍的数，"
    else:
        gap = "是两个不同的数，"
    return {
        "ref": "EX_UPC",
        "kind": "stacked_dual",
        "title": (
            f"净利润 US${net_income[-1]:,.0f}M 里，归上市公司普通股东的只有 "
            f"US${common[-1]:,.0f}M（{100 - share[-1]:.1f}%）"
        ),
        "xlabels": [compact_period(period) for period in periods],
        "xstep": LONG_STEP,
        "stacks": [
            {"name": "归属少数股东（IBG Holdings）", "color": "GOLD",
             "values": rounded(nci[-RECENT:])},
            {"name": "归属普通股东", "color": "NAVY",
             "values": rounded(common[-RECENT:])},
        ],
        # `stacked_dual` scales its right axis to `ticks(0, ymax || 60, 6)` and
        # not to the data, so this share -- which has run above 77% -- was being
        # drawn above the top of the canvas and dropped by the browser without
        # a word, while the legend still named it. Caught by the off-canvas
        # check added to `tests/render_check.js`.
        #
        # Then the window moved and 100 stopped being enough either: Q4'17 is
        # 101.2%, because the parent's own result was negative that quarter and
        # the minority interest exceeded the whole. It was still drawn -- inside
        # the canvas, so the off-canvas check stayed quiet -- but above the
        # topmost gridline with no tick to read it against. A declared ceiling is
        # a constant fitted to whatever window was drawn when it was written, and
        # this one had been fitted to eight quarters. The renderer now takes
        # max(declared, peak) so the axis cannot under-scale again; 100 stays
        # declared because the round number is what tells the reader this is a
        # share of a whole, and this chart is what exercises that lift.
        "line": {"name": "少数股东占比 (RHS)", "color": "RED",
                 "values": rounded(share[-RECENT:]), "yfmt": "pct1", "ymax": 100},
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$M",
        "ylab2": "少数股东占比",
        "note": (
            "<b>这是本站其他任何一页都没有的一条线。</b>"
            "IBKR 是 Up-C 结构：上市主体 Interactive Brokers Group, Inc. 只持有经营实体 "
            "IBG LLC 的少数权益，其余由 IBG Holdings LLC 持有，"
            "因此合并报表上的净利润绝大部分被记为「归属少数股东」。"
            f"本季 US${net_income[-1]:,.0f}M 的净利润里，US${nci[-1]:,.0f}M "
            f"（{share[-1]:.1f}%）不归上市公司股东。"
            "读这家公司的利润表时，「净利润」和「普通股东能分到的利润」"
            + gap
            + "这个比例的长期走向见 Exhibit {EX_UPC_LONG}。"
        ),
        "src_extra": INCOME_SOURCE,
    }


def other_income_swing(staging: dict) -> dict:
    periods = staging["periods"]
    other = staging["financials_usd_m"]["other_income"]
    window = other
    biggest = max((value for value in window if value is not None), key=abs)
    reported = [value for value in window if value is not None]
    leading_holes = next(index for index, value in enumerate(window) if value is not None)
    holes = (
        f"<b>左边{cn_count(leading_holes)}格是空的：这一行按 ASC 606 的口径定义，"
        "而公司 2018-01-01 才采用该准则、"
        "且用 modified retrospective，2016–2017 的申报里没有那张分解表。</b>"
        if leading_holes else ""
    )
    return {
        "ref": "EX_OTHER",
        "kind": "grouped_bars",
        "title": (
            f"「其他收入」的摆动：{len(reported)} 季在 US${min(reported):,.0f}M 与 "
            f"US${max(reported):,.0f}M 之间"
        ),
        "xlabels": [compact_period(period) for period in periods],
        "xstep": LONG_STEP,
        "xrot": 90,
        "groups": [{"name": "其他收入", "color": "BLUE", "values": rounded(window)}],
        "bar_labels": True,
        "fmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$M",
        "note": (
            "这一行里装着公司的<b>货币多元化策略</b>：IBKR 把自身净值锚定在一篮子十种货币"
            "（公司称之为 GLOBAL）上，该头寸的损益一部分进「其他收入」、一部分进其他综合收益。"
            + holes
            + "所以总净收入这条线自带一块与经营无关的波动 —— "
            f"窗口内最大的一次是 US${biggest:,.0f}M。"
            "<b>本页不把它剔除后另画一条「调整后收入」线</b>："
            "公司在新闻稿里确实同时给出 adjusted 口径，但每季剔除哪几项由公司当季决定，"
            "把若干季的 adjusted 数连成一条线会把口径变化画成经营变化。"
        ),
        "src_extra": INCOME_SOURCE,
    }


def pretax_margin_quarter(staging: dict) -> dict:
    periods = staging["periods"][-RECENT:]
    financials = staging["financials_usd_m"]
    margin = ratio(financials["pretax_income"], financials["total_net_revenues"])
    expense = ratio(financials["total_non_interest_expenses"],
                    financials["total_net_revenues"])
    years = cn_count(len(staging["periods"]) // 4)
    direction = "下行" if expense[-1] < expense[0] else "走向"
    # "Above 70% for N quarters running" is management's framing and the note
    # disputed its count off the releases. Counted here off the filed 10-Q
    # figures -- and where a release printed a margin its own 10-Q later
    # overrode, the note says which and why.
    streak = 0
    for value in reversed(margin):
        if value is None or value <= MARGIN_FLOOR:
            break
        streak += 1
    if streak >= 2 and streak < len(margin):
        below = len(margin) - streak - 1
        restated = {item["period"]: item for item in staging.get("release_restated_in_10q", [])}
        run = (f"按 10-Q 申报口径，税前利润率已连续{cn_count(streak)}季高于 {MARGIN_FLOOR}%；"
               f"上一次不到 {MARGIN_FLOOR}% 是 {key_period(staging['periods'][below])} 的 {margin[below]:.1f}%")
        if staging["periods"][below] in restated:
            item = restated[staging["periods"][below]]
            run += (f"（那一季业绩新闻稿印的是 {item['release_pretax_margin_printed_pct']}%：新闻稿发出之后"
                    f"公司达成和解，10-Q 给那一季补记了 US${item['added_g_and_a_usd_m']:,.0f}M 一般及行政费用，"
                    "本页以 10-Q 为准）")
        run += "。"
    else:
        run = ""
    return {
        "ref": "EX_MARGIN",
        "kind": "lines",
        "title": (
            f"税前利润率 {margin[-1]:.1f}%，同比 {margin[-1] - margin[-5]:+.1f}pp；"
            f"非息费用率 {expense[-1]:.1f}%"
        ),
        "xlabels": [compact_period(period) for period in periods],
        "xstep": LONG_STEP,
        "series": [
            {"name": "税前利润率", "values": rounded(margin[-RECENT:]), "color": "NAVY"},
            {"name": "非息费用 / 总净收入", "values": rounded(expense[-RECENT:]),
             "color": "GOLD"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "占总净收入",
        "note": (
            "两条线相加恒等于 100%：税前利润率 = 1 − 非息费用率，这是损益表的恒等式，"
            "不是巧合，也不需要任何估计 —— 券商的损益表在总净收入之下只有一个费用小计。"
            "所以这张图真正要看的是费用率那条："
            f"本季 {expense[-1]:.1f}%，"
            f"公司把每一美元收入里的 {margin[-1]:.0f} 美分留在了税前利润里。"
            + run
            + f"这条费用率的{years}年{direction}见 Exhibit {{EX_LEVERAGE}}。"
        ),
        "src_extra": INCOME_SOURCE,
    }


def net_adds_quarter(staging: dict) -> dict:
    """The note's one growth engine that is not market beta: accounts added in the quarter."""
    periods = staging["periods"]
    accounts = staging["operating"]["accounts_thousands"]
    adds = net_adds(accounts)
    finished = [value for value in adds if value is not None]
    now = adds[-1]
    if now == max(finished) and finished.count(now) == 1:
        standing = f"{len(finished)} 季里最高"
    else:
        peak = max(finished)
        standing = f"低于 {key_period(periods[adds.index(peak)])} 的 {peak:,.0f}K"
    rising = 0
    for index in range(len(adds) - 1, 1, -1):
        if adds[index - 1] is None or adds[index] <= adds[index - 1]:
            break
        rising += 1
    return {
        "ref": "EX_ADDS",
        "kind": "grouped_bars",
        "title": (f"本季净增账户 {now:,.0f}K，{standing}"
                  + (f"；净增已连续{cn_count(rising)}季走高" if rising >= 2 else "")),
        "xlabels": [compact_period(period) for period in periods],
        "xstep": LONG_STEP,
        "xrot": 90,
        "groups": [{"name": "季度净增账户 D", "color": "NAVY", "values": rounded(adds)}],
        "bar_labels": False,
        "fmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "千户",
        "note": (
            f"账户数 {accounts_millions(accounts[-1])} 百万，环比 "
            f"{signed(pct_change(accounts[-1], accounts[-2]))}、同比 "
            f"{signed(pct_change(accounts[-1], accounts[-5]))}。"
            "净增是相邻两季末账户数之差（D）；公司每月另发的逐月净增不在季度申报里，本页不画。"
            "账户数不含市值波动，所以这条线是客户端唯一不随行情涨跌的量 —— "
            "客户权益那张图（Exhibit {EX_SCALE}）里混着市场的贡献。"
        ),
        "src_extra": RELEASE_SOURCE,
    }


def cushion_quarter(staging: dict, story: dict) -> dict:
    """How full the clients' accounts are: cash cushion against equity, and leverage against it."""
    periods = staging["periods"]
    operating = staging["operating"]
    equity = operating["customer_equity_usd_bn"]
    cash = ratio(operating["customer_credits_usd_bn"], equity)
    leverage = ratio(operating["customer_margin_loans_usd_bn"], equity)
    start = first_reported(cash)
    shown = [value for value in cash if value is not None]
    if cash[-1] == min(shown) and shown.count(cash[-1]) == 1:
        cash_words = f"{key_period(periods[start])} 有这个口径以来最低"
    else:
        low = min(shown)
        cash_words = f"高于 {key_period(periods[cash.index(low)])} 的 {low:.1f}%"
    higher = [index for index in range(len(leverage) - 1) if leverage[index] > leverage[-1]]
    if not higher:
        leverage_words = f"{len(periods)} 季里最高"
    elif higher[-1] < len(leverage) - 2:
        leverage_words = f"{key_period(periods[higher[-1]])} 之后最高"
    else:
        leverage_words = ""
    peak = max(leverage)
    peak_at = leverage.index(peak)
    share = leverage[-1] / peak
    return {
        "ref": "EX_CUSHION",
        "kind": "lines",
        "title": (f"客户贷方余额 / 客户权益 {cash[-1]:.1f}%，{cash_words}；"
                  f"保证金贷款 / 客户权益 {leverage[-1]:.1f}%"
                  + (f"，{leverage_words}" if leverage_words else "")),
        "xlabels": [compact_period(period) for period in periods],
        "xstep": LONG_STEP,
        "xrot": 90,
        "series": [
            {"name": "客户贷方余额 / 客户权益 D", "values": rounded(cash), "color": "NAVY"},
            {"name": "客户保证金贷款 / 客户权益 D", "values": rounded(leverage), "color": "GOLD"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "占客户权益",
        "note": (
            "两条比率都是本页自算（D），分子分母都是公司披露的季末值。"
            "贷方余额占权益越低，客户账上的现金垫越薄；保证金贷款占权益越高，杠杆越高。"
            + (story["cushion_reading"] + "。" if story.get("cushion_reading") else "")
            + f"放到整个窗口看，杠杆那条线并不高：峰值是 {key_period(periods[peak_at])} 的 {peak:.1f}%，"
            + (f"今天的 {leverage[-1]:.1f}% 不到它的一半。" if share < 0.5 else
               f"今天的 {leverage[-1]:.1f}% 是它的 {share:.0%}。")
            + f"贷方余额那条线从 {key_period(periods[start])} 起算，因为这个期末余额从那一季起才按季披露。"
            "纵轴不自 0 起，但没有任何点被截掉。"
        ),
        "src_extra": RELEASE_SOURCE,
    }


def bad_debt_quarter(staging: dict, story: dict) -> dict:
    """The note's 'new crack': customer bad debt, with the 10-Q's own explanation when it has one."""
    periods = staging["periods"]
    financials = staging["financials_usd_m"]
    bad = financials["customer_bad_debt"]
    loans = staging["operating"]["customer_margin_loans_usd_bn"]
    now = bad[-1]
    higher = [index for index in range(len(bad) - 1) if bad[index] > now]
    if not higher:
        standing = f"{len(bad)} 季里最高"
    elif higher[-1] < len(bad) - 2:
        standing = f"{key_period(periods[higher[-1]])} 之后最高"
    else:
        standing = f"低于上季的 US${bad[-2]:,.0f}M"
    cause = story.get("bad_debt_cause")
    values = {"bad_debt_yoy": f"US${now - bad[-5]:,.0f}M"}
    return {
        "ref": "EX_BAD_DEBT",
        "kind": "grouped_bars",
        "title": f"客户坏账 US${now:,.0f}M，{standing}",
        "xlabels": [compact_period(period) for period in periods],
        "xstep": LONG_STEP,
        "xrot": 90,
        "groups": [{"name": "客户坏账", "color": "BLUE", "values": rounded(bad)}],
        "bar_labels": False,
        "fmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$M",
        "note": (
            "坏账是客户亏损超过其在 IBKR 的资产、公司追不回的部分（净额，负值是追回多于新增）。"
            + (f"窗口里比本季高的只有 "
               + "、".join(f"{key_period(periods[index])}（US${bad[index]:,.0f}M）" for index in higher)
               + "。" if higher else "")
            + f"本季绝对额只占总净收入的 {now / financials['total_net_revenues'][-1]:.1%}；"
            f"同一季客户保证金贷款环比 {signed(pct_change(loans[-1], loans[-2]))}、"
            f"同比 {signed(pct_change(loans[-1], loans[-5]))}。"
            + (fill_story(cause, values) + "。" if cause else "")
        ),
        "src_extra": INCOME_SOURCE + (story.get("source", "") if cause else ""),
    }


def comprehensive_quarter(staging: dict) -> dict:
    """The note's third optic: the currency basket's other half lands outside net income."""
    periods = staging["periods"]
    financials = staging["financials_usd_m"]
    common = financials["net_income_common"]
    comprehensive = financials["comprehensive_income_common"]
    common_yoy = pct_change(common[-1], common[-5])
    comprehensive_yoy = pct_change(comprehensive[-1], comprehensive[-5])
    quarter = int(periods[-1][1])
    ytd_word = {1: "一季度", 2: "上半年", 3: "前三季", 4: "全年"}[quarter]
    ytd_now = sum(comprehensive[-quarter:])
    ytd_then = sum(comprehensive[-quarter - 4:-4])
    ytd_common_now = sum(common[-quarter:])
    ytd_common_then = sum(common[-quarter - 4:-4])
    opposite = (common_yoy > 0) != (comprehensive_yoy > 0)
    return {
        "ref": "EX_COMPREHENSIVE",
        "kind": "lines",
        "title": (f"归属普通股东：净利润 US${common[-1]:,.0f}M、同比 {signed(common_yoy)}；"
                  f"综合收益 US${comprehensive[-1]:,.0f}M、同比 {signed(comprehensive_yoy)}"),
        "xlabels": [compact_period(period) for period in periods],
        "xstep": LONG_STEP,
        "xrot": 90,
        "series": [
            {"name": "归属普通股东的净利润", "values": rounded(common), "color": "NAVY"},
            {"name": "归属普通股东的综合收益", "values": rounded(comprehensive), "color": "GOLD"},
        ],
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "end_label": True,
        "ylab": "US$M",
        "note": (
            "综合收益 = 净利润 + 其他综合收益。IBKR 把自身净值锚在一篮子十种货币（GLOBAL）上，"
            "这个头寸的损益一部分进「其他收入」、一部分进其他综合收益 —— 公司的 adjusted 口径剔掉前者，"
            "后者本来就不进每股收益，于是头条利润看不见它。"
            + (f"本季两条线同比方向相反：" if opposite else "本季两条线同比：")
            + f"净利润 {signed(common_yoy)}，综合收益 {signed(comprehensive_yoy)}。"
            f"{ytd_word}归属普通股东的综合收益 US${ytd_now:,.0f}M，去年同期 US${ytd_then:,.0f}M"
            f"（净利润 US${ytd_common_now:,.0f}M 对 US${ytd_common_then:,.0f}M）。"
            "两条线都取自各季 10-Q 的合并综合收益表，会计第四季为全年减九个月。"
        ),
        "src_extra": INCOME_SOURCE,
    }


# ── section three ───────────────────────────────────────────────────────────

def threshold_section(staging: dict, kpi: dict) -> list[dict]:
    """This quarter's note, section 8: the headroom overview, then one history per series.

    Thresholds are the note's, verbatim, and so are their directions; the
    readings are the series'. A series bounded twice (both sides, or a warning
    line under a confirmation line) gets one chart with both lines on it.
    """
    registry = kpi_registry(staging)
    entries = read_entries(staging, kpi, "current")
    values = {entry["metric"]: headroom(entry["direction"], entry["threshold"], entry["current"])
              for entry in entries}
    safe = [e for e in entries if values[e["metric"]] > 0]
    on_line = [e for e in entries if values[e["metric"]] == 0]
    crossed = [e for e in entries if values[e["metric"]] < 0]
    title = f"下季 {len(entries)} 条阈值：{len(safe)} 条在安全侧"
    if on_line:
        title += f"、{len(on_line)} 条踩在线上"
    if crossed:
        title += f"、{len(crossed)} 条已越过"
    no_history = [e for e in entries if registry[e["reads"]].get("history") is False]
    lending = staging["nim"]["securities_lending_all_in_usd_m"]
    note = (
        "正值 = 仍在安全侧。阈值与方向逐字取自本季分析笔记第 8 节，不是公司指引，也不是评级；"
        "当前值取自本页各条序列的最后一格。"
        + "".join(f"「{e['metric']}」的余量是零：本季 {kpi_text(e['unit'], e['current'])} 正好踩在"
                  f"「{fill_story(e['words'], {'threshold': kpi_text(e['unit'], e['threshold'])})}」的线上。"
                  for e in on_line)
        + "".join(f"「{e['metric']}」只有本季新闻稿净息差表脚注里的数（本季 "
                  f"{kpi_text(e['unit'], e['current'])}，去年同季 "
                  f"{kpi_text(e['unit'], lending[-5])}），1Q2026 的新闻稿还没有这个脚注，"
                  "所以它只进这张图、不画历史线。"
                  for e in no_history if e["reads"] == "securities_lending_all_in" and lending[-5] is not None)
    )
    charts = [zero_safe(headroom_exhibit(
        title, entries, "current", note=note,
        src_extra=f"阈值取自本季（{staging['periods'][-1]}）分析笔记第 8 节；当前值全部是本季申报值或据其自算。",
    ))]
    for position, reads in enumerate(dict.fromkeys(e["reads"] for e in entries)):
        spec = registry[reads]
        if spec.get("history") is False:
            continue
        group = [e for e in entries if e["reads"] == reads]
        lines = " / ".join(kpi_text(e["unit"], e["threshold"])
                           + (f"（{line_label(e)}）" if len(group) > 1 else "") for e in group)
        charts.append(multi_threshold_exhibit(
            f"{spec['noun']}：下季阈值 {lines}，当前 {kpi_text(group[0]['unit'], group[0]['current'])}",
            staging, spec, group, threshold_label="下季阈值",
            note=(("上一张图说哪条线离得近，这张说它是怎么走到那里的。" if position == 0 else "")
                  + spec["note"]()
                  + "笔记的条件：" + "；".join(
                      fill_story(e["words"], {"threshold": kpi_text(e["unit"], e["threshold"])})
                      for e in group) + "。"
                  + consecutive_words(staging, group)
                  + threshold_history(staging, group, "current")),
        ))
    return charts


# ── section four ────────────────────────────────────────────────────────────

def revenue_mix_long(staging: dict) -> dict:
    periods = staging["periods"]
    financials = staging["financials_usd_m"]
    revenue = financials["total_net_revenues"]
    net_interest_share = ratio(financials["net_interest_income"], revenue)
    commission_share = ratio(financials["commissions"], revenue)
    # The crossings are the whole point of the long window, so they are read off
    # the series rather than typed. The first version of this note said the two
    # lines crossed twice and put the start of the zero-rate stretch at the
    # window's left edge: true of the thirty-quarter window it was written on,
    # false once the window reached back to 2016, where commissions led for
    # most of 2016-2017 as well.
    stretches = runs([commission_share[index] > net_interest_share[index]
                      for index in range(len(periods))])
    crossings = len(stretches) - 1
    led = [(start, stop) for start, stop, flag in stretches if flag]
    if led:
        start, stop = max(led, key=lambda span: (span[1] - span[0], span[0]))
        closed = stop < len(periods)
        if periods[start][-4:] in ZERO_RATE_YEARS and closed:
            longest = (f"最长的一段是 {periods[start]} 零利率把净利息压到佣金之下，"
                       f"直到 {periods[stop]} 加息把它重新推回第一大收入来源，"
                       f"中间整整 {stop - start} 个季度里佣金才是这家公司最大的一条收入线。")
        elif closed:
            longest = (f"最长的一段是 {periods[start]} 起净利息落到佣金之下，"
                       f"直到 {periods[stop]} 才重新成为第一大收入来源，"
                       f"中间 {stop - start} 个季度里佣金是这家公司最大的一条收入线。")
        else:
            longest = (f"最长的一段是 {periods[start]} 起净利息落到佣金之下，至今 "
                       f"{stop - start} 个季度仍未回到第一大收入来源。")
    else:
        longest = "窗口内净利息一直高于佣金。"
    crossed = (f"两条线在窗口内交叉过<b>{cn_count(crossings)}次</b>，" if crossings
               else "两条线在窗口内没有交叉过，")
    return {
        "ref": "EX_MIX_LONG",
        "kind": "lines",
        "title": (
            f"利率周期改写了收入结构：净利息占比 {net_interest_share[0]:.1f}% → "
            f"{net_interest_share[-1]:.1f}%，佣金占比 {commission_share[0]:.1f}% → "
            f"{commission_share[-1]:.1f}%"
        ),
        "xlabels": [compact_period(period) for period in periods],
        "xstep": LONG_STEP,
        "xrot": 90,
        "series": [
            {"name": "净利息占比", "values": rounded(net_interest_share), "color": "NAVY"},
            {"name": "佣金占比", "values": rounded(commission_share), "color": "BLUE"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "占总净收入",
        "note": (
            f"{len(periods)} 个季度覆盖了完整的一轮利率周期：2020–2021 的零利率、"
            "2022–2023 的加息、以及 2024 年之后的降息。"
            + crossed + longest
            + "<b>八个季度看不出这件事</b>：它需要一整轮周期才能显形，"
            f"而这正是本页把常规序列拉到{cn_count(len(periods))}季而不是八季的原因。"
        ),
        "src_extra": INCOME_SOURCE,
    }


def nim_long(staging: dict) -> dict:
    periods = staging["periods"]
    nim = staging["nim"]
    values = [value for value in nim["nim_pct"] if value is not None]
    trough = min(values)
    peak = max(values)
    assets = nim["avg_earning_assets_usd_m"]
    negative = [period for period, value in zip(periods, nim["yield_segregated_pct"])
                if value is not None and value < 0]
    negative_words = (
        "在零利率那几个季度，隔离资金的年化收益率是<b>负的</b> —— "
        "公司为持有客户的隔离现金而付费，这不是取数错误，是当时的市场利率。"
        if negative else "")
    trough_at = nim["nim_pct"].index(trough)
    peak_at = nim["nim_pct"].index(peak)
    if trough_at < peak_at < len(periods) - 1 and nim["nim_pct"][-1] < peak:
        path = f"净息差从 {trough:.2f}% 的谷底走到 {peak:.2f}% 的峰值再回落到今天，"
    else:
        path = f"净息差在窗口内的谷底是 {trough:.2f}%、峰值是 {peak:.2f}%，"
    growth = assets[-1] / assets[0]
    if is_record(staging["financials_usd_m"]["total_net_revenues"]) and nim_down(staging):
        reading = ("把这两件事放在同一张图上，就能看出为什么本季收入创纪录与净息差下行"
                   "并不矛盾。")
    else:
        reading = "把这两件事放在同一张图上，就能看出收入与净息差为什么不必同向。"
    return {
        "ref": "EX_NIM_LONG",
        "kind": "lines",
        "title": (
            f"净息差走完一轮周期：谷底 {trough:.2f}%、峰值 {peak:.2f}%、本季 "
            f"{nim['nim_pct'][-1]:.2f}%；平均生息资产同期 "
            f"{assets[0] / 1000:.0f} → "
            f"{assets[-1] / 1000:.0f} 十亿美元"
        ),
        "xlabels": [compact_period(period) for period in periods],
        "xstep": LONG_STEP,
        "xrot": 90,
        "series": [
            {"name": "净息差 NIM", "values": rounded(nim["nim_pct"]), "color": "RED"},
            {"name": "隔离资金收益率", "values": rounded(nim["yield_segregated_pct"]),
             "color": "BLUE"},
            {"name": "保证金贷款收益率", "values": rounded(nim["yield_margin_loans_pct"]),
             "color": "NAVY"},
        ],
        "fmt": "pct2",
        "yfmt": "pct2",
        "label_fmt": "pct2",
        "end_label": True,
        "ylab": "年化",
        "note": (
            negative_words
            + path
            + f"而同期平均生息资产涨到了期初的 {growth:.1f} 倍：规模的扩张一直在，价格没有。"
            + reading
            + "纵轴不自 0 起，但没有任何点被截掉。"
        ),
        "src_extra": NIM_SOURCE,
    }


def scale_long(staging: dict) -> dict:
    periods = staging["periods"]
    operating = staging["operating"]
    accounts = operating["accounts_thousands"]
    equity = operating["customer_equity_usd_bn"]
    per_account = [None if None in (e, a) or a == 0 else e * 1e6 / a
                   for e, a in zip(equity, accounts)]
    peak_at = per_account.index(max(per_account))
    trough_at = per_account.index(min(per_account))
    if peak_at < trough_at:
        diluted = (
            f"它确实被稀释过 —— 从 {periods[peak_at]} 的峰值 "
            f"US${max(per_account):,.0f} 一路跌到 "
            f"{periods[trough_at]} 的 US${min(per_account):,.0f}，"
            "熊市与一波小额新户同时压着它。"
        )
    else:
        diluted = (f"窗口内它的低点是 {periods[trough_at]} 的 US${min(per_account):,.0f}，"
                   f"高点是 {periods[peak_at]} 的 US${max(per_account):,.0f}。")
    recovery = ""
    if trough_at < len(periods) - 1 and per_account[-1] > min(per_account):
        doubled = accounts[-1] >= 2 * accounts[trough_at]
        recovery = (
            f"但此后它<b>回升了 {per_account[-1] / min(per_account) - 1:.1%}</b>，"
            + ("而同期账户数还在继续翻倍 —— "
               f"也就是说 {periods[trough_at][-4:]} 年之后新增的账户不再明显拖低平均值。"
               if doubled else
               f"同期账户数涨了 {accounts[-1] / accounts[trough_at] - 1:.0%}。")
        )
    if per_account[-1] < per_account[0]:
        against_start = (f"注意本季 US${per_account[-1]:,.0f} 仍比窗口起点低 "
                         f"{1 - per_account[-1] / per_account[0]:.0%}"
                         + ("，稀释发生过，只是已经停下来了。" if recovery else "。"))
    else:
        against_start = (f"本季 US${per_account[-1]:,.0f} 已不低于窗口起点的 "
                         f"US${per_account[0]:,.0f}。")
    return {
        "ref": "EX_SCALE_LONG",
        "kind": "lines",
        "title": (
            f"账户数 {accounts_millions(accounts[0])} → {accounts_millions(accounts[-1])} 百万，"
            f"户均权益 US${per_account[0]:,.0f} → US${per_account[-1]:,.0f}"
        ),
        "xlabels": [compact_period(period) for period in periods],
        "xstep": LONG_STEP,
        "xrot": 90,
        "series": [
            {"name": "户均客户权益（US$）D", "values": rounded(per_account),
             "color": "NAVY"},
        ],
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "end_label": True,
        "ylab": "US$ / 账户",
        "note": (
            "户均权益是本页自算（D）：客户权益 ÷ 账户数，两个分量都是公司披露值。"
            "<b>这条线是判断增长质量的那一条</b>：如果新账户显著小于存量账户，"
            "它会被稀释下去，账户数的高增速就不会等比例地变成收入。"
            + diluted + recovery + against_start
        ),
        "src_extra": RELEASE_SOURCE,
    }


def upc_long(staging: dict) -> dict:
    periods = staging["periods"]
    financials = staging["financials_usd_m"]
    share = ratio(financials["net_income_noncontrolling"], financials["net_income"])
    fell = share[0] - share[-1]
    changes = len(share) - 1
    rises = sum(1 for index in range(1, len(share)) if share[index] > share[index - 1])
    # The first version said this line only ever falls. Over the forty-two
    # quarters it rose quarter on quarter eighteen times -- Q4'17 is 101.2%,
    # the quarter the parent's own result was negative -- so the shape is a
    # trend with noise, and the note now counts the noise instead of denying it.
    if rises == 0:
        shape = "这条线单向下行，"
    elif fell > 0:
        shape = f"这条线总体下行（{changes} 次环比里有 {rises} 次回升，并不单调），"
    else:
        shape = f"这条线在窗口内没有下行（{changes} 次环比里 {rises} 次回升），"
    return {
        "ref": "EX_UPC_LONG",
        "kind": "lines",
        "title": (
            f"少数股东占净利润的比例：{share[0]:.1f}% → {share[-1]:.1f}%，"
            + (f"{len(periods)} 季共下降 {fell:.1f}pp" if fell > 0
               else f"{len(periods)} 季共上升 {-fell:.1f}pp")
        ),
        "xlabels": [compact_period(period) for period in periods],
        "xstep": LONG_STEP,
        "xrot": 90,
        "series": [
            {"name": "归属少数股东占比 D", "values": rounded(share), "color": "GOLD"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "占合并净利润",
        "note": (
            "比例是本页自算（D）：归属少数股东的净利润 ÷ 合并净利润，两个分量都是申报值。"
            + (shape
               + "是因为上市主体逐年从 IBG Holdings 手中收购 IBG LLC 的权益单位，"
               "上市公司股东对同一份利润的 claim 因此缓慢扩大。"
               f"但 {len(periods)} 季只走了 {fell:.1f}pp，"
               f"今天仍有 {share[-1]:.1f}% 的合并利润不归上市公司股东 —— "
               "按这个斜率，这不是一个几年内会消失的楔子。"
               if fell > 0 else
               shape + f"今天仍有 {share[-1]:.1f}% 的合并利润不归上市公司股东。")
            + "纵轴不自 0 起，但没有任何点被截掉。"
        ),
        "src_extra": INCOME_SOURCE,
    }


def operating_leverage_long(staging: dict) -> dict:
    periods = staging["periods"]
    financials = staging["financials_usd_m"]
    expense = ratio(financials["total_non_interest_expenses"],
                    financials["total_net_revenues"])
    compensation = ratio(financials["employee_compensation"],
                         financials["total_net_revenues"])
    net_interest_share = ratio(financials["net_interest_income"],
                               financials["total_net_revenues"])
    if expense[-1] < expense[0] and compensation[-1] < compensation[0]:
        moved = (f"费用率从 {expense[0]:.1f}% 降到 {expense[-1]:.1f}%，"
                 f"薪酬率从 {compensation[0]:.1f}% 降到 {compensation[-1]:.1f}% —— "
                 "在一家几乎全自动化的券商里，收入随利率与客户余额放大，人力不随之放大。")
    else:
        moved = (f"费用率从 {expense[0]:.1f}% 到 {expense[-1]:.1f}%，"
                 f"薪酬率从 {compensation[0]:.1f}% 到 {compensation[-1]:.1f}%。")
    if net_interest_share[-1] > 50:
        caution = ("<b>但要小心把这读成纯粹的效率提升</b>：分母里有一半以上是净利息收入，"
                   "而净利息收入的高低主要由利率决定。")
    else:
        caution = ("<b>但要小心把这读成纯粹的效率提升</b>：分母里有 "
                   f"{net_interest_share[-1]:.1f}% 是净利息收入，而净利息收入的高低主要由利率决定。")
    return {
        "ref": "EX_LEVERAGE",
        "kind": "lines",
        "title": (
            f"经营杠杆：非息费用率 {expense[0]:.1f}% → {expense[-1]:.1f}%，"
            f"薪酬率 {compensation[0]:.1f}% → {compensation[-1]:.1f}%"
        ),
        "xlabels": [compact_period(period) for period in periods],
        "xstep": LONG_STEP,
        "xrot": 90,
        "series": [
            {"name": "非息费用 / 总净收入 D", "values": rounded(expense), "color": "NAVY"},
            {"name": "员工薪酬 / 总净收入 D", "values": rounded(compensation),
             "color": "BLUE"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "占总净收入",
        "note": (
            "两条比率都是本页自算（D），分子分母都是申报值。"
            + moved
            + caution
            + "利率下行时，同一批人和同一套系统会让"
            "这条线自己回升，那不是费用失控。"
        ),
        "src_extra": INCOME_SOURCE,
    }


def commission_long(staging: dict) -> dict:
    periods = staging["periods"]
    operating = staging["operating"]
    commission = operating["commission_per_order_usd"]
    start = next(index for index, value in enumerate(commission) if value is not None)
    values = [value for value in commission if value is not None]
    labels = periods[start:]
    trough_at = values.index(min(values))
    rebound = max(values[trough_at:])
    rebound_at = values.index(rebound, trough_at)
    if values[-1] < values[0]:
        shape = "<b>口径之内它并不平稳，也没有趋势性上行。</b>"
    else:
        shape = "<b>口径之内它并不平稳。</b>"
    if labels[trough_at][-4:] == RETAIL_WAVE_YEAR:
        dip = f"{RETAIL_WAVE_YEAR} 年散户潮里被小额订单摊薄到 US${min(values):.2f} 的谷底，"
    else:
        dip = f"{labels[trough_at][-4:]} 年跌到 US${min(values):.2f} 的谷底，"
    if 0 < trough_at < rebound_at < len(values) - 1 and values[-1] < rebound:
        path = (f"US${values[0]:.2f} 起步，" + dip
                + f"随后回到 US${rebound:.2f}，此后一路走低到今天的 US${values[-1]:.2f}。")
    else:
        path = (f"US${values[0]:.2f} 起步，" + dip + f"今天是 US${values[-1]:.2f}。")
    return {
        "ref": "EX_COMMISSION",
        "kind": "lines",
        "title": (
            f"每笔已清算订单佣金：{len(values)} 季从 US${values[0]:.2f} 到 "
            f"US${values[-1]:.2f}，峰值 US${max(values):.2f}"
        ),
        "xlabels": [compact_period(period) for period in periods],
        "xstep": LONG_STEP,
        "xrot": 90,
        "series": [
            {"name": "每笔已清算订单佣金", "values": rounded(commission), "color": "NAVY"},
        ],
        "fmt": "usd2",
        "yfmt": "usd2",
        "label_fmt": "usd2",
        "end_label": True,
        "ylab": "US$ / 笔",
        "note": (
            f"<b>这条线从 {periods[start]} 起算，不是本页少取了数。</b>"
            "公司在此之前公布的是「Commission per DART」，从这一季起改为"
            "「Commission per Cleared Commissionable Order」，两个口径从未在同一份新闻稿里"
            "并列出现过，因此没有可供拼接的重叠季 —— 强行接成一条线就是无中生有。"
            + shape
            + path
            + "<b>要小心把这条线读成公司的定价。</b>它是<b>实现</b>的单均佣金，"
            "同时受费率表与订单结构影响 —— 一批小额订单和一次降价在这张图上长得一模一样，"
            "申报文件不拆开这两者，所以本页只说它的走向，不说公司调没调价。"
            "能说的是结果：佣金收入的增长来自笔数，而单均收费同期是逆风。"
        ),
        "src_extra": RELEASE_SOURCE,
    }


# ── payload ─────────────────────────────────────────────────────────────────

def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    # The filer's own text rounds 5,185 thousand accounts to "5.19 million";
    # binary float formatting would print 5.18. See `round_half_up`.
    return [f"Revenue ${staging['financials_usd_m']['total_net_revenues'][-1] / 1000:.2f}B",
            f"NIM {staging['nim']['nim_pct'][-1]:.2f}%",
            f"账户 {round_half_up(staging['operating']['accounts_thousands'][-1] / 1000, 2)}M"]


def release_source(staging: dict) -> dict:
    """This quarter's earnings release in the series' source list."""
    label = f"IBKR {company_period(staging['periods'][-1])} 业绩新闻稿"
    found = next((item for item in staging["sources"] if item["label"].startswith(label)), None)
    if found is None:
        raise ValueError(f"series `sources` has no entry for the {label}: add this "
                         "quarter's release with the roll")
    return found


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    period = periods[-1]
    labels = [compact_period(period) for period in periods]
    financials = staging["financials_usd_m"]
    operating = staging["operating"]
    nim = staging["nim"]

    latest = latest_block(staging, period=period,
                          release_date=staging["release_dates"][period])
    closure = stamped_block(staging, "followup_closure", period)
    prior = stamped_block(staging, "prior_kpi_settlement", period)
    kpi = stamped_block(staging, "next_kpi", period)
    first_coverage = is_first_coverage(staging)
    if first_coverage and (closure or prior):
        raise ValueError(f"series says {period} is the first quarter covered "
                         "(meta.coverage_start), yet carries a block settling a previous note")
    for block in (closure, prior):
        if block and block["set_in"] != previous_period(period):
            raise ValueError(f"a section-one block settles the note of {block['set_in']!r}, "
                             f"but the quarter before {period!r} is {previous_period(period)!r}")
    release = release_source(staging)
    fourth = period.startswith("Q4")
    filing = (f"{period[-4:]} 年度 10-K" if fourth else f"截至 {latest['period_end']} 的 10-Q")

    revenue = financials["total_net_revenues"]
    net_interest = financials["net_interest_income"]
    net_income = financials["net_income"]
    nci = financials["net_income_noncontrolling"]
    common = financials["net_income_common"]
    nci_share = ratio(nci, net_income)
    accounts = operating["accounts_thousands"]
    equity = operating["customer_equity_usd_bn"]
    darts = operating["darts_thousands"]
    scale = scale_yoy(staging)
    down = yields_down(staging)
    record = is_record(revenue)
    thesis = volume_up_price_down(staging)
    story = stamped_block(staging, "quarter_story", period) or {}

    # Section one settles the previous note and nothing else: (a) its follow-up
    # questions, (b) its section-8 thresholds. (c), a company guidance record,
    # does not exist for this filer and the description says so.
    settled_ex = ([closure_exhibit(staging, closure)] if closure else [])
    settled_ex += (settlement_exhibits(staging, prior) if prior else [])

    # Section two: the note's own conclusions about this quarter that a filed
    # series can draw -- the record revenue and its legs, the price of the
    # biggest leg, the client base (and the record net adds), how full the
    # clients' accounts are, the bad-debt jump, the margin, and the two
    # profit lines the Up-C structure and the currency basket split.
    highlight_ex = [
        revenue_quarter(staging),
        revenue_mix_quarter(staging),
        nim_and_yields(staging, story),
        customer_scale(staging),
        net_adds_quarter(staging),
        cushion_quarter(staging, story),
        bad_debt_quarter(staging, story),
        pretax_margin_quarter(staging),
        upc_wedge(staging),
        comprehensive_quarter(staging),
    ]

    quantified = read_entries(staging, kpi, "current") if kpi else []
    next_ex = threshold_section(staging, kpi) if kpi else []

    # The other-income chart states a range over the whole record and no
    # reading of this quarter, so it is routine tracking, not a highlight.
    # So do the company's own consecutive-quarter table and the net interest
    # margin against a year earlier: records of the whole window, which used to
    # open section one in place of a settlement.
    routine_ex = [
        revenue_mix_long(staging),
        other_income_swing(staging),
        nim_long(staging),
        nim_record(staging),
        scale_long(staging),
        consecutive_record(staging),
        upc_long(staging),
        operating_leverage_long(staging),
        commission_long(staging),
    ]

    exhibits = number_exhibits(settled_ex + highlight_ex + next_ex + routine_ex, start=2)
    resolve_exhibit_refs(exhibits)
    first_table = exhibits[-1]["n"] + 1

    # ── audit tables ────────────────────────────────────────────────────────
    income_rows = [
        [periods[index],
         f"${revenue[index]:,.0f}M",
         f"${financials['commissions'][index]:,.0f}M",
         (f"${financials['other_fees_and_services'][index]:,.0f}M D"
          if financials["other_fees_and_services"][index] is not None else "—"),
         (f"${financials['other_income'][index]:,.0f}M D"
          if financials["other_income"][index] is not None else "—"),
         f"${net_interest[index]:,.0f}M D",
         f"${financials['total_non_interest_expenses'][index]:,.0f}M",
         f"${financials['customer_bad_debt'][index]:,.0f}M",
         f"${financials['pretax_income'][index]:,.0f}M",
         f"${net_income[index]:,.0f}M",
         f"${nci[index]:,.0f}M",
         f"${common[index]:,.0f}M D",
         f"${financials['comprehensive_income_common'][index]:,.0f}M",
         "10-K 全年减九个月 D" if staging["basis"][index] == "fy_minus_9m"
         else "10-Q 申报三个月栏"]
        for index in range(len(periods))
    ]

    operating_rows = [
        [periods[index],
         f"{accounts[index]:,.0f}K",
         f"${equity[index]:,.1f}B",
         f"{darts[index]:,.0f}K",
         f"${operating['commission_per_order_usd'][index]:.2f}"
         if operating["commission_per_order_usd"][index] is not None else "—",
         f"${operating['customer_credits_usd_bn'][index]:,.1f}B"
         if operating["customer_credits_usd_bn"][index] is not None else "—",
         f"${operating['customer_margin_loans_usd_bn'][index]:,.1f}B"
         if operating["customer_margin_loans_usd_bn"][index] is not None else "—",
         staging["release_dates"].get(periods[index]) or "—"]
        for index in range(len(periods))
    ]

    nim_rows = [
        [periods[index],
         f"${nim['avg_earning_assets_usd_m'][index]:,.0f}M",
         f"{nim['nim_pct'][index]:.2f}%",
         f"{nim['yield_segregated_pct'][index]:.2f}%",
         f"{nim['yield_margin_loans_pct'][index]:.2f}%",
         (f"{nim['yield_credits_pct'][index]:.2f}%"
          if nim["yield_credits_pct"][index] is not None else "—"),
         f"${net_interest[index]:,.0f}M D",
         (f"${nim['securities_lending_all_in_usd_m'][index]:,.0f}M"
          if nim["securities_lending_all_in_usd_m"][index] is not None else "—")]
        for index in range(len(periods))
    ]

    tables = ([kpi_table(first_table, "上季阈值与本季实际（原单位）",
                         read_entries(staging, prior, "actual"), "actual", "本季实际")]
              if prior else [])
    tables += ([kpi_table(first_table + len(tables), "下季阈值与当前值（原单位）",
                          quantified, "current", "当前值")] if kpi else [])
    table_n = first_table + len(tables)
    tables += [
        {
            "n": table_n,
            "title": f"{len(periods)} 季损益表（每季注明取自申报三个月栏还是全年减九个月）",
            "headers": ["期间", "总净收入", "佣金", "其他费用与服务 D", "其他收入 D",
                        "净利息收入 D", "非息费用", "其中客户坏账", "税前利润", "净利润",
                        "归属少数股东", "归属普通股东 D", "归属普通股东的综合收益", "取数方式"],
            "rows": income_rows,
        },
        {
            "n": table_n + 1,
            "title": f"{len(periods)} 季运营指标（含各季业绩新闻稿的申报日期）",
            "headers": ["期间", "账户数", "客户权益", "总 DARTs", "每笔订单佣金",
                        "客户贷方余额", "客户保证金贷款", "新闻稿申报日"],
            "rows": operating_rows,
        },
        {
            "n": table_n + 2,
            "title": f"{len(periods)} 季净息差表（公司披露值，非本页自算）",
            "headers": ["期间", "平均生息资产", "净息差 NIM", "隔离资金收益率",
                        "保证金贷款收益率", "客户贷方付息率", "GAAP 净利息收入 D",
                        "证券借贷全口径净利息（表下脚注）"],
            "rows": nim_rows,
        },
        ai_capex_cycle_table(table_n + 3),
    ]

    # ── the sentences the page leads with ───────────────────────────────────
    floor = min(scale)
    if floor >= 30:
        opener = "客户端每一项都在爆发 —— "
    else:
        opener = "客户端三项 —— "
    if nim_down(staging):
        price = (f"但净息差从 {nim['nim_pct'][-5]:.2f}% 压到 {nim['nim_pct'][-1]:.2f}%，"
                 + ("公司自己披露的三条年化收益率同比无一例外全线下行。" if all(down) else
                    f"公司自己披露的三条年化收益率同比{cn_count(sum(down))}条下行。"))
    else:
        price = (f"净息差从 {nim['nim_pct'][-5]:.2f}% 到 {nim['nim_pct'][-1]:.2f}%，"
                 "同比没有下行。")
    if record and thesis:
        record_words = f"总净收入 US${revenue[-1]:,.0f}M 的纪录是量堆出来的，不是价。"
    elif record:
        record_words = f"总净收入 US${revenue[-1]:,.0f}M 创纪录。"
    else:
        record_words = (f"总净收入 US${revenue[-1]:,.0f}M，低于 "
                        f"{periods[revenue.index(max(revenue))]} 的纪录。")
    headline = (
        opener
        + f"账户数 {accounts_millions(accounts[-1])} 百万、同比 {signed(scale[0])}，"
        f"客户权益 US${equity[-1]:,.1f}B、同比 {signed(scale[1])}，"
        f"DARTs 同比 {signed(scale[2])} —— "
        + price
        + record_words
        + f"而这 US${net_income[-1]:,.0f}M 净利润里，只有 US${common[-1]:,.0f}M"
        f"（{100 - nci_share[-1]:.1f}%）归上市公司普通股东。"
    )

    nim_delta = nim["nim_pct"][-1] - nim["nim_pct"][-5]
    if floor >= 10:
        scale_words = f"账户数、客户权益、DARTs 三项同比都在{tenths_word(floor)}以上，"
    else:
        scale_words = ("账户数、客户权益、DARTs 三项同比 "
                       f"{signed(scale[0])}、{signed(scale[1])}、{signed(scale[2])}，")
    four_down = all(down) and nim_down(staging)
    rising = sum(1 for fell in down if not fell) + (0 if nim_down(staging) else 1)
    brief_one = (
        '<article><span>矛盾</span>'
        + ('<b>量在涨，价在跌</b>' if thesis else '<b>量与价</b>')
        + f'<p>{scale_words}'
        + (f'净息差却同比 {nim_delta:+.2f}pp。' if thesis else f'净息差同比 {nim_delta:+.2f}pp。')
        + f'保证金贷款收益率 {nim["yield_margin_loans_pct"][-5]:.2f}% → '
        f'{nim["yield_margin_loans_pct"][-1]:.2f}%，'
        + ('四条利率线同比没有一条在往上走。' if four_down else
           f'四条利率线里{cn_count(rising)}条没有下行。')
        + '</p></article>'
    )
    nii_share_now = net_interest[-1] / revenue[-1] * 100
    brief_two = (
        '<article><span>结构</span>'
        + ('<b>一半以上的收入不是佣金</b>' if nii_share_now > 50 else '<b>净利息与佣金</b>')
        + f'<p>净利息收入 US${net_interest[-1]:,.0f}M，占总净收入 '
        f'{nii_share_now:.1f}%，是佣金的 '
        f'{net_interest[-1] / financials["commissions"][-1]:.2f} 倍。'
        f'{len(periods)} 季里这个占比从 '
        f'{net_interest[0] / revenue[0] * 100:.1f}% 走到今天，走完了一整轮利率周期。</p></article>'
    )
    wedge_fell = nci_share[0] - nci_share[-1]
    brief_three = (
        '<article><span>结构</span>'
        f'<b>净利润有{share_words(nci_share[-1] / 100)}不归你</b>'
        f'<p>Up-C 结构下，合并净利润的 {nci_share[-1]:.1f}% 归 IBG Holdings。'
        + (f'这个比例 {len(periods)} 季只降了 {wedge_fell:.1f}pp，' if wedge_fell > 0 else
           f'这个比例 {len(periods)} 季没有下降，')
        + '读这家公司的利润表必须先把这个楔子扣掉。</p></article>'
    )

    # ── section descriptions and notes ──────────────────────────────────────
    # What section one settles is read off the blocks it draws, so a quarter
    # whose previous note left nothing says so instead of borrowing a chart.
    settled_parts = []
    if closure:
        settled_parts.append(f"（a）上一份笔记（{closure['set_in']}）留下的"
                             f"{cn_count(len(closure['items']))}条待验证问题，"
                             "按本季笔记第 0 节的判定计数；")
    if prior:
        settled_parts.append(f"（b）上一份笔记第 8 节的{cn_count(prior['rows'])}行关键观察指标，"
                             f"其中能用本季申报数结算的{cn_count(len(prior['quantified']))}条阈值"
                             "先上余量图、再画进它们所在序列的历史线，其余各行在图注里写明为什么结算不了；")
    if settled_parts:
        settled_lead = "本节结算上一季留下、本季到期的东西：" + "".join(settled_parts)
        settled_lead += "（c）"
    elif first_coverage:
        settled_lead = (f"本站对 IBKR 的第一份季报分析是 {periods[-1]}，"
                        "没有上季留下的跟踪指标可结算；")
    else:
        settled_lead = "上一份笔记没有留下可结算的问题或阈值；"
    # Section three names every row of the note's section 8: the ones drawn,
    # and the ones not, each with its reason.
    if kpi:
        registry = kpi_registry(staging)
        drawn_rows = sorted({entry["row"] for entry in quantified})
        single_cell = [entry["metric"] for entry in quantified
                       if registry[entry["reads"]].get("history") is False]
        next_words = (
            f"本季分析笔记第 8 节共 {kpi['rows']} 行关键观察指标。能用申报数结算的是第 "
            + "、".join(str(row) for row in drawn_rows)
            + f" 行，共{cn_count(len(quantified))}个阈值：先上余量图，再按序列各画一张历史线，"
            "两条线落在同一序列上的画进同一张图；阈值与方向逐字取自笔记，不是公司指引。"
            + ("其中" + "、".join(single_cell) + "只有本季一格，只进余量图。" if single_cell else "")
            + "不接入的：" + "；".join(f"第 {item['row']} 行，{item['text']}" for item in kpi["not_tracked"])
            + "。"
        )
    else:
        next_words = "本季笔记没有设定下季阈值，本节没有图。"
    unplotted = story.get("unplotted", [])
    derived_both = sum(1 for fee, other in zip(financials["other_fees_and_services"],
                                               financials["other_income"])
                       if fee is not None and other is not None)
    first_dated = next(index for index, label in enumerate(periods)
                       if staging["release_dates"].get(label))
    dated_words = ("每一季" if first_dated == 0
                   else f" {key_period(periods[first_dated])} 起每一季")
    commission_from = operating["commission_metric_from"]
    credits_from = periods[next(index for index, value
                                in enumerate(operating["customer_credits_usd_bn"])
                                if value is not None)]
    loans_from = next(index for index, value
                      in enumerate(operating["customer_margin_loans_usd_bn"])
                      if value is not None)
    if credits_from == commission_from:
        credits_words = (f"客户贷方余额同样自 {key_period(credits_from)} 起算，"
                         "因为公司在此之前不在业绩新闻稿里按季给这个期末余额；")
    else:
        credits_words = (f"客户贷方余额自 {key_period(credits_from)} 起算，"
                         "因为公司在此之前不在业绩新闻稿里按季给这个期末余额；")
    if loans_from == 0:
        loans_words = ("客户保证金贷款跑满全窗口：公司在 2019 年及之前的新闻稿里把它叫 "
                       "customer debits，1Q2020 起改名，口径没有变。")
    else:
        loans_words = (f"客户保证金贷款自 {key_period(periods[loans_from])} 起算，"
                       "因为公司在此之前不在业绩新闻稿里按季给这个期末余额。")
    if first_coverage and quantified:
        threshold_note = (f"本页首次覆盖，第三节的{cn_count(len(quantified))}条是第一组阈值，"
                          "第一节的闭环从下一季开始。")
    elif prior and quantified:
        threshold_note = (f"第一节结算上一份笔记第 8 节里能用申报数结算的"
                          f"{cn_count(len(prior['quantified']))}条，"
                          f"第三节的{cn_count(len(quantified))}条留到下一季结算。")
    elif quantified:
        threshold_note = f"第三节的{cn_count(len(quantified))}条留到下一季结算。"
    else:
        threshold_note = ""

    sections = [
        {
            "id": "settled",
            "title": "一、上季跟踪指标兑现了吗",
            "description": plain_text(
                settled_lead
                + NO_GUIDANCE_NOTE
                + "公司自己每季都印的环比表与净息差表是长期记录，不是结算，放在第四节。"
            ),
            "exhibits": settled_ex,
        },
        {
            "id": "quarter_highlights",
            "title": "二、本季重点",
            "description": plain_text(
                "本季分析笔记第 1、2、3、7 节的结论里，能用申报数画出来的一图一条："
                + ("创纪录的总净收入" if record else "本季的总净收入")
                + "、它的三条腿、决定其中最大一条腿价格的四条利率线、客户端的规模与本季净增账户、"
                "客户账上的现金垫与杠杆、客户坏账、税前利润率，以及 Up-C 结构与货币篮子"
                "分别从普通股东那里切走、挪走的两块。"
                + (f"笔记里另有{cn_count(len(unplotted))}条结论画不出来，不给近似值："
                   + "；".join(unplotted) + "。" if unplotted else "")
            ),
            "exhibits": highlight_ex,
        },
    ]
    # A quarter whose note set no thresholds keeps the section and says so,
    # rather than renumbering the page: the notes describe four parts.
    sections.append({
        "id": "next_quarter",
        "title": "三、下季要跟踪什么",
        "description": plain_text(next_words),
        "exhibits": next_ex,
    })
    sections.append({
        "id": "routine",
        "title": "四、长期常规跟踪",
        "description": plain_text(
            f"IBKR 专属的常规序列，窗口{cn_count(len(periods))}季而不是八季，"
            "因为其中几条要走完一整轮利率周期才显形："
            "收入结构的迁移、「其他收入」里的货币头寸摆动、净息差与生息资产、"
            "净息差相对一年前的逐季变化、账户与户均权益、公司自印环比表的完整记录、"
            "Up-C 楔子、经营杠杆，以及每笔订单的佣金单价。"
        ),
        "exhibits": routine_ex,
    })

    return {
        "schema_version": "quarterly-dashboard/ibkr-v1",
        "page": {"slug": "ibkr", "language": "zh-CN"},
        "company": {
            "ticker": "IBKR",
            "name": "Interactive Brokers Group",
            "group": "brokerage_wealth",
            "accounting_standard": "US GAAP",
        },
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · IBKR",
        "title": f"Interactive Brokers (IBKR)：{period} 季报仪表盘",
        "subtitle": (
            f"截至 {latest['period_end']} · 发布 {latest['release_date']} · US GAAP · "
            f"{AUDIT_WORDS[latest['audit_status']]} · "
            "财年即自然年，本页季度标注无需映射"
        ),
        "headline": headline,
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            + brief_one + brief_two + brief_three
            + '</div>'
        ),
        "source": (
            f'Source: <a href="{release["url"]}" rel="noopener">IBKR {company_period(period)} '
            f'业绩新闻稿（8-K EX-99.1）</a>与{filing}。'
        ),
        "source_url": release["url"],
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": sections,
        "tables": tables,
        "notes": [plain_text(_p) for _p in [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，"
            "每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "IBKR 的财年即自然年，因此本页的季度标注不需要任何映射："
            f"本页的 {period} 就是公司所称的 {company_period(period)}，"
            f"即截至 {latest['period_end']} 的三个月。"
            "本站的微软、新思与 Visa 三页需要映射，本页不需要。",
            "<b>IBKR 从不在申报文件里给季度数字指引，因此本页没有逐季的指引兑现记录。</b>"
            "这是取数限制而不是编辑取舍：档案里的历次业绩 8-K 都没有给过下一季的收入区间、"
            "EPS 区间或利润率区间。"
            "把电话会上的前瞻措辞翻译成数字再画成兑现图，正是本仓库要避免的失败。",
            "损益表口径：会计 Q1–Q3 直接取自各季 10-Q 自己印的三个月栏，无需差分；"
            "会计 Q4 没有 10-Q，其各行为 10-K 全年数减去第三季 10-Q 的九个月栏，"
            "两端都是申报值，核对表逐行标注取数方式。",
            "「其他费用与服务」与「其他收入」两行标 D，是因为它们由申报值相减得到："
            "其他费用与服务 = 来自客户合同的收入 − 佣金；"
            "其他收入 = 总净收入 − 佣金 − 其他费用与服务 − 净利息收入。"
            f"两条恒等式在两行都有值的全部{cn_count(derived_both)}季逐季成立，"
            "且与公司新闻稿印出来的对应行完全相等。",
            "运营指标与净息差表<b>不是 XBRL 事实</b>，companyfacts 接口里没有，"
            f"因此本页的运营指标逐份读自 {key_period(periods[0])} 以来连续"
            f"{cn_count(len(periods))}份业绩新闻稿；"
            "净息差表 3Q2017 起才进新闻稿，更早的季度读自 10-Q 管理层讨论里的同一张表"
            "或一年后新闻稿的去年同期列。"
            f"核对表给出{dated_words}新闻稿的申报日期。",
            f"<b>每笔订单佣金这条线从 {key_period(commission_from)} 起算，不是缺数。</b>"
            f"公司在 {key_period(previous_period(commission_from))} 及之前公布的指标叫「Commission per DART」，"
            f"自 {key_period(commission_from)} 起改为「Commission per Cleared Commissionable Order」，"
            "两个口径从未在同一份新闻稿里并列出现，没有可供拼接的重叠季。"
            + credits_words + loans_words,
            "<b>本页不发布任何跨季度的每股收益序列。</b>"
            "公司于 2025-04-15 宣布 4 拆 1，而申报数据里只有那些后来充当比较期的季度被重述，"
            "因此 EPS 在公开接口上是拆股前后两种口径混在一起的序列，连成一条线会画出一个断崖。"
            "本页改用<b>归属普通股东的净利润（美元）</b>，它可加、且不受拆股影响。",
            "<b>Up-C 结构必须先扣掉再读利润表。</b>上市主体 Interactive Brokers Group, Inc. "
            "只持有经营实体 IBG LLC 的少数权益，其余由 IBG Holdings LLC 持有，"
            "所以合并净利润的大部分被记为「归属少数股东」。"
            "本页把这个比例作为一条常规序列逐季画出，"
            "并在所有涉及利润的图上区分「净利润」与「归属普通股东的净利润」。",
            "<b>客户权益不等于净流入。</b>公司披露的是期末客户权益，"
            "其变动同时包含客户净入金与市值波动，申报文件里没有把两者分开，"
            "因此本页不发布任何「净流入」口径的数字，也不用权益的环比变动去近似它。",
            "净息差、三条年化收益率与平均生息资产均为公司在净息差表里的<b>披露值</b>，"
            "非本页自算。需要注意公司在该表中的「净利息收入」口径略大于损益表上的 GAAP 净利息收入："
            "它把记在「其他费用与服务」和「其他收入」里、性质与利息相同的部分并了进来，"
            "公司在表下的脚注里逐季给出这两笔金额。本页的图与表分别标注了各自用的是哪一个口径。",
            "阈值逐字取自所有者的季报分析笔记第 8 节（关键观察指标），不是公司指引，也不是评级。"
            + threshold_note,
            "本页只发布公司披露值、可复算的简单派生值；D 标记代表 Derived / 自算。"
            "不发布评级、目标价、估值与卖方共识。",
            "本页已知未接入：公司对下一季的任何数字（公司不给）、"
            "分产品与分地区的佣金金额拆分（公司只按地区披露来自客户合同的收入总额，"
            "不把佣金按股票 / 期权 / 期货拆成金额）、客户资产净流入、"
            "公司口径 adjusted 收入与 adjusted EPS 的逐季序列（每季剔除项由公司当季决定）、"
            "以及任何来自业绩电话会而无法与第二个来源核对的前瞻数字。",
            "业绩电话会文字稿仅链接官方 IR 与 SEC 托管版本，公开仓不复制原件或逐字内容。",
        ]],
        "footer": ("IBKR quarterly results · 数据来自 Interactive Brokers 公开披露与透明自算 · "
                   "仅供研究，不构成投资建议"),
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "ibkr.js"), payload, "ibkr")
    shell_dir = ROOT / "ibkr"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("IBKR", "ibkr"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(
        f"IBKR page: {charts} charts in {len(payload['sections'])} sections "
        f"+ {len(payload['tables'])} audit tables"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
