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
when it stops. What belongs to one quarter only -- the thresholds section three
sets (`next_kpi`) and, from the page's second quarter on, the settlement of the
previous quarter's thresholds (`prior_kpi`) -- carries a ``period`` stamp and is
read through `board.stamped_block`: a block stamped for another quarter stops
the build, an absent block leaves its charts out. `_checks` in the series is a
separate reading of the quarter's release that the tests hold the page to; this
builder never reads it.

Three things make this page different from the ones built before it.

**No guidance record, and it is a sourcing limit rather than an editorial
choice.**  IBKR has never put a numeric quarterly outlook in a filing -- no
revenue range, no EPS range, no margin range, in any earnings 8-K in the
archive.  The object the Amazon, Cadence, Synopsys, NVIDIA, TSMC and Meta pages
are built on simply does not exist here, the same way it does not exist for
Microsoft, Alphabet and Visa.  Transcribing forward-looking remarks off a
webcast that cannot be checked against a second source is the failure this repo
exists to avoid, so section one carries what the company *does* publish about
its own prior quarter instead.

**Coverage began with `meta.coverage_start`** -- the quarter of the first
analysis note on this company in the owner's vault (Q4 2025, 2026-03-05). On
that quarter there are no thresholds set by a previous note to settle and
section one says so; from then on the loop closes through `prior_kpi`. The page
once stamped its own first quarter here and printed "first coverage" on a
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
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import (  # noqa: E402
    ai_capex_cycle_table,
    cn_count,
    cn_ordinal,
    headroom_exhibit,
    latest_block,
    number_exhibits,
    round_half_up,
    stamped_block,
    threshold_exhibit,
    threshold_table,
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

NO_GUIDANCE_NOTE = (
    "<b>IBKR 从不在申报文件里给季度数字指引</b>，所以本页没有逐季的指引兑现记录。"
    "这是取数限制而不是编辑取舍：翻遍档案里的历次业绩 8-K，公司没有给过下一季的收入区间、"
    "EPS 区间或利润率区间中的任何一个。微软、Alphabet 与 Visa 三页出于同样的理由也没有这类记录。"
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


# ── section one ─────────────────────────────────────────────────────────────

def consecutive_record(staging: dict, thresholds_set: bool) -> dict:
    """The company's own sequential comparison, carried across the whole record.

    IBKR prints a "Consecutive Quarters" table in every release -- this quarter
    against the one before it -- so the sequential move is the company's own
    published object rather than something this page invents. One quarter of it
    says nothing; the full run says whether a negative quarter is normal.
    """
    periods = staging["periods"]
    operating = staging["operating"]
    accounts = qoq(operating["accounts_thousands"])
    equity = qoq(operating["customer_equity_usd_bn"])
    darts = qoq(operating["darts_thousands"])
    finished = [value for value in accounts if value is not None]
    negative_equity = sum(1 for value in equity[1:] if value is not None and value < 0)
    negative_accounts = sum(1 for value in finished if value < 0)
    if is_first_coverage(staging):
        opening = ("<b>本页首次覆盖，第一节没有本站上季阈值可结算</b>"
                   + (" —— 阈值从第三节开始设，闭环从下一季起。" if thresholds_set else "。")
                   + "能结算的是公司自己每季都印的那张环比表：本图把它拉成完整记录。")
    else:
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


def prior_settlement(staging: dict, prior: dict, registry: dict) -> dict:
    """The previous note's thresholds against this quarter's actuals.

    The actual is read off the same series the threshold chart draws, so the
    settlement bar and the history line cannot disagree about where the quarter
    landed.
    """
    entries = []
    for entry in prior["quantified"]:
        if entry["metric"] not in registry:
            raise ValueError(f"prior_kpi metric {entry['metric']!r} has no series on this "
                             "page: map it in build/ibkr.py threshold_registry")
        entries.append({**entry, "actual": registry[entry["metric"]]["values"][-1]})
    return {
        "ref": "EX_PRIOR",
        **headroom_exhibit(
            f"上季 {len(entries)} 条阈值：本季实际离阈值的余量",
            entries, "actual",
            note=("正值表示仍在安全侧。阈值是<b>本站的研究设定</b>，不是公司指引 —— "
                  "IBKR 不发布季度指引，本页也不会替它编一个。" + prior.get("excluded", "")),
            src_extra="本季实际值取自本页各条序列的最后一格；阈值为本站研究设定。",
        ),
    }


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


def nim_and_yields(staging: dict) -> dict:
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
                   "但方向是一致的，四条线没有一条在往上走。")
    else:
        rising = [name for (key, name), fell in zip(YIELD_LINES, down) if not fell]
        if not nim_down(staging):
            rising.append("净息差")
        reading = f"四条线同比并不同向：{'、'.join(rising)}没有下行。"
    return {
        "ref": "EX_NIM",
        "kind": "lines",
        "title": (
            f"净息差 {nim['nim_pct'][-1]:.2f}%，同比 "
            f"{nim['nim_pct'][-1] - nim['nim_pct'][-5]:+.2f}pp{title_tail}"
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
            f"这条费用率的{years}年{direction}见 Exhibit {{EX_LEVERAGE}}。"
        ),
        "src_extra": INCOME_SOURCE,
    }


# ── section three ───────────────────────────────────────────────────────────

def threshold_registry(staging: dict) -> dict:
    """Every metric a threshold can be set on, with the series its chart draws.

    `next_kpi` and `prior_kpi` name metrics by their label; this is where a
    label becomes a series, a format and the sentences that do not change with
    the quarter. A threshold on a metric that is not here stops the build --
    it has no history to draw, and inventing one is not a roll.
    """
    periods = staging["periods"]
    financials = staging["financials_usd_m"]
    operating = staging["operating"]
    nim = staging["nim"]
    accounts = operating["accounts_thousands"]
    account_growth = qoq(accounts)
    commission = operating["commission_per_order_usd"]
    margin_loans = operating["customer_margin_loans_usd_bn"]
    expense_ratio = ratio(financials["total_non_interest_expenses"],
                          financials["total_net_revenues"])
    nci_share = ratio(financials["net_income_noncontrolling"], financials["net_income"])

    def distance(entry: dict, value: float, digits: int, threshold_digits: int,
                 noun: str = " ") -> str:
        """「距 X 还有 Ypp」 while on the safe side, 「已越过」 once it is not."""
        threshold = entry["threshold"]
        gap = value - threshold if entry["direction"] == "up" else threshold - value
        if gap >= 0:
            return f"距 {threshold:.{threshold_digits}f}%{noun}还有 {gap:.{digits}f}pp"
        return f"已越过 {threshold:.{threshold_digits}f}% 的阈值 {-gap:.{digits}f}pp"

    def nim_note(entry: dict) -> str:
        value = nim["nim_pct"][-1]
        return f"本季 {value:.2f}%，{distance(entry, value, 2, 2)}。" + entry_note(entry)

    def growth_note(entry: dict) -> str:
        value = account_growth[-1]
        recent = [v for v in account_growth[-8:] if v is not None]
        threshold = entry["threshold"]
        if threshold < min(recent):
            where = (f"低于过去两年每一季的环比（{cn_count(len(recent))}季里最低 "
                     f"{min(recent):.2f}%、中位数 {statistics.median(recent):.2f}%）")
        elif threshold > max(recent):
            where = (f"高于过去两年每一季的环比（{cn_count(len(recent))}季里最高 "
                     f"{max(recent):.2f}%）")
        else:
            where = (f"落在过去两年的区间之内（{cn_count(len(recent))}季 {min(recent):.2f}%–"
                     f"{max(recent):.2f}%，中位数 {statistics.median(recent):.2f}%）")
        return (f"本季 {value:.2f}%。阈值 {threshold:+.1f}% {where}，"
                + entry_note(entry)
                + "<b>这里用环比而不是同比</b>：账户数是存量，同比会把四个季度前的一次性事件"
                "在图上拖四个季度。")

    def commission_note(entry: dict) -> str:
        return (f"本季 US${commission[-1]:.2f}。"
                f"这条线在 {operating['commission_metric_from']} 之前是空的，"
                "因为公司当时公布的是另一个口径的指标（Commission per DART），"
                "详见 Exhibit {EX_COMMISSION}。"
                f"阈值设在 ${entry['threshold']:.2f}：" + entry_note(entry))

    def expense_note(entry: dict) -> str:
        value = expense_ratio[-1]
        return (f"本季 {value:.2f}%，{distance(entry, value, 2, 1, noun=' 的阈值')}。"
                + entry_note(entry))

    def nci_note(entry: dict) -> str:
        value = nci_share[-1]
        rises = [index for index in range(1, len(nci_share)) if nci_share[index] > nci_share[index - 1]]
        if rises:
            path = (f"这条线长期下行但并不单调，最近一次环比回升在 {periods[rises[-1]]}；"
                    if nci_share[-1] < nci_share[0] else
                    f"这条线最近一次环比回升在 {periods[rises[-1]]}；")
        else:
            path = "这条线在窗口内逐季下行；"
        threshold = entry["threshold"]
        if entry["direction"] == "down" and threshold > value:
            where = "略上方" if threshold - value <= 1 else "上方"
            placed = f"阈值 {threshold:.1f}% 设在本季{where}："
        else:
            placed = f"阈值 {threshold:.1f}%，本季已越过："
        return (f"本季 {value:.2f}%。" + path + placed + entry_note(entry)
                + "长期走向见 Exhibit {EX_UPC_LONG}。")

    def margin_loan_note(entry: dict) -> str:
        start = next(index for index, value in enumerate(margin_loans) if value is not None)
        if start == 0:
            span = ("这条线跑满全窗口：公司在 2019 年及之前的新闻稿里把这个余额叫 customer debits，"
                    "1Q2020 起改叫 Customer margin loans，口径没有变。")
        else:
            span = (f"这条线从 {key_period(periods[start])} 起算：公司在此之前不在新闻稿里按季给这个余额。")
        return (f"本季 US${margin_loans[-1]:,.1f}B，"
                f"同比 {signed(pct_change(margin_loans[-1], margin_loans[-5]))}。"
                + entry_note(entry)
                + "保证金贷款是净利息收入里收益率最高的一块资产，"
                "所以它比客户权益更直接地决定下一季的净利息收入。"
                + span)

    return {
        "净息差 NIM": {
            "values": nim["nim_pct"], "fmt": "pct2", "ylab": "年化",
            "actual_name": "实际 NIM", "threshold_text": lambda t: f"{t:.2f}%",
            "note": nim_note, "src_extra": NIM_SOURCE,
        },
        "账户数环比增速": {
            "values": account_growth, "fmt": "pct1", "ylab": "环比增速",
            "actual_name": "账户数 环比", "threshold_text": lambda t: f"{t:+.1f}%",
            "note": growth_note, "src_extra": RELEASE_SOURCE,
        },
        "每笔已清算订单佣金": {
            "values": commission, "fmt": "usd2", "ylab": "US$ / 笔",
            "actual_name": "每笔佣金", "threshold_text": lambda t: f"${t:.2f}",
            "note": commission_note, "src_extra": RELEASE_SOURCE,
        },
        "非息费用 / 总净收入": {
            "values": expense_ratio, "fmt": "pct1", "ylab": "占总净收入",
            "actual_name": "非息费用率 D", "threshold_text": lambda t: f"{t:.1f}%",
            "note": expense_note, "src_extra": INCOME_SOURCE,
        },
        "少数股东占净利润比": {
            "values": nci_share, "fmt": "pct1", "ylab": "占合并净利润",
            "actual_name": "少数股东占比 D", "threshold_text": lambda t: f"{t:.1f}%",
            "note": nci_note, "src_extra": INCOME_SOURCE,
        },
        "客户保证金贷款": {
            "values": margin_loans, "fmt": "f0c", "ylab": "US$B",
            "actual_name": "客户保证金贷款", "threshold_text": lambda t: f"US${t:.0f}B",
            "note": margin_loan_note, "src_extra": RELEASE_SOURCE,
        },
    }


def entry_note(entry: dict) -> str:
    """The note's own words for one threshold, with its threshold filled in.

    The reasoning behind a threshold belongs to the quarter that set it, so it
    lives in the stamped `next_kpi` block; where it restates the threshold it
    writes ``{threshold:...}`` and the number is filled from the entry, so the
    sentence cannot drift from the line drawn beside it.
    """
    return entry.get("note", "").format(threshold=entry["threshold"])


UNIT_WORDS = (("pct", "百分比"), ("usd_bn", "美元金额"), ("usd_m", "美元金额"),
              ("usd_eps", "每笔单价"))


def threshold_section(staging: dict, kpi: dict, registry: dict) -> list[dict]:
    quantified = kpi["quantified"]
    periods = staging["periods"]
    long_labels = [compact_period(period) for period in periods]
    words = []
    for unit, word in UNIT_WORDS:
        if any(entry["unit"] == unit for entry in quantified) and word not in words:
            words.append(word)
    units = ("、".join(words[:-1]) + "与" + words[-1]) if len(words) > 1 else words[0]
    filing = "10-K" if periods[-1].startswith("Q4") else "10-Q"
    charts = [headroom_exhibit(
        f"下季 {len(quantified)} 条阈值与当前值的距离（正数 = 仍在安全侧）",
        quantified, "current",
        note=(
            "所有阈值都是<b>本站的研究设定</b>，不是公司指引，也不是评级 —— "
            "IBKR 不发布季度指引，本页也不会替它编一个。"
            f"把{units}归一到「距阈值余量」这一个口径，"
            "是为了让一张图同时回答「哪几条已经越线」。"
            + ("<b>本页首次覆盖，这是第一组阈值</b>，下一季第一节才会有本站自己的闭环。"
               if is_first_coverage(staging) else "")
            + kpi.get("excluded", "").format(count=cn_count(len(quantified)))
        ),
        src_extra=f"当前值全部取自本季 {filing} 与业绩 8-K 的申报值。",
    )]
    for position, entry in enumerate(quantified):
        if entry["metric"] not in registry:
            raise ValueError(f"next_kpi metric {entry['metric']!r} has no series on this "
                             "page: map it in build/ibkr.py threshold_registry")
        spec = registry[entry["metric"]]
        safe = "越高越安全" if entry["direction"] == "up" else "越低越安全"
        charts.append(threshold_exhibit(
            f"{entry['metric']}：{safe}",
            long_labels, rounded(spec["values"]), entry["threshold"],
            fmt=spec["fmt"], xstep=LONG_STEP, ylab=spec["ylab"],
            actual_name=spec["actual_name"],
            threshold_name=f"阈值 {spec['threshold_text'](entry['threshold'])}",
            note=(("上一张图说哪条线越了，这张说它是怎么走到那里的。" if position == 0 else "")
                  + spec["note"](entry)),
            src_extra=spec["src_extra"],
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
    prior = stamped_block(staging, "prior_kpi", period)
    kpi = stamped_block(staging, "next_kpi", period)
    first_coverage = is_first_coverage(staging)
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
    registry = threshold_registry(staging)

    settled_ex = ([prior_settlement(staging, prior, registry)] if prior else [])
    settled_ex += [consecutive_record(staging, kpi is not None), nim_record(staging)]

    highlight_ex = [
        revenue_quarter(staging),
        revenue_mix_quarter(staging),
        nim_and_yields(staging),
        customer_scale(staging),
        upc_wedge(staging),
        pretax_margin_quarter(staging),
    ]

    quantified = kpi["quantified"] if kpi else []
    next_ex = threshold_section(staging, kpi, registry) if kpi else []

    # The other-income chart states a range over the whole record and no
    # reading of this quarter, so it is routine tracking, not a highlight.
    routine_ex = [
        revenue_mix_long(staging),
        other_income_swing(staging),
        nim_long(staging),
        scale_long(staging),
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
         f"${financials['pretax_income'][index]:,.0f}M",
         f"${net_income[index]:,.0f}M",
         f"${nci[index]:,.0f}M",
         f"${common[index]:,.0f}M D",
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
         f"${net_interest[index]:,.0f}M D"]
        for index in range(len(periods))
    ]

    tables = ([threshold_table(first_table, "下季阈值与当前值（原单位）",
                               quantified, "current", "当前值")] if kpi else [])
    table_n = first_table + len(tables)
    tables += [
        {
            "n": table_n,
            "title": f"{len(periods)} 季损益表（每季注明取自申报三个月栏还是全年减九个月）",
            "headers": ["期间", "总净收入", "佣金", "其他费用与服务 D", "其他收入 D",
                        "净利息收入 D", "非息费用", "税前利润", "净利润",
                        "归属少数股东", "归属普通股东 D", "取数方式"],
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
                        "保证金贷款收益率", "客户贷方付息率", "GAAP 净利息收入 D"],
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
        + ('四条利率线没有一条在往上走。' if four_down else
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
    if first_coverage:
        settled_lead = ("本页首次覆盖，没有上一份笔记留下的阈值可结算"
                        + ("，本站自己的闭环从下一季开始。" if kpi else "。"))
        settled_tail = "这一节因此改为结算公司自己每季都印的那两个对照对象："
    elif prior:
        settled_lead = (f"本节先结算上一份笔记留下的{cn_count(len(prior['quantified']))}条阈值。")
        settled_tail = "这一节另外结算公司自己每季都印的那两个对照对象："
    else:
        settled_lead = ""
        settled_tail = "这一节结算公司自己每季都印的那两个对照对象："
    tracked = [
        entry["metric"] for entry in quantified
    ]
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
        threshold_note = (f"第一节结算上一份笔记留下的{cn_count(len(prior['quantified']))}条，"
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
                + settled_tail
                + "「Consecutive Quarters」环比表，以及净息差表 —— "
                "两者都拉成完整记录，因为一个季度的环比说明不了任何事。"
            ),
            "exhibits": settled_ex,
        },
        {
            "id": "quarter_highlights",
            "title": "二、本季重点",
            "description": plain_text(
                ("创纪录的总净收入" if record else "本季的总净收入")
                + "、它的三条腿、"
                "决定其中最大一条腿价格的四条利率线、"
                "客户端的规模、Up-C 结构切走的那一块，以及税前利润率。"
            ),
            "exhibits": highlight_ex,
        },
    ]
    # A quarter whose note set no thresholds keeps the section and says so,
    # rather than renumbering the page: the notes describe four parts.
    sections.append({
        "id": "next_quarter",
        "title": "三、下季要跟踪什么",
        "description": plain_text(
            (f"{cn_count(len(tracked))}条阈值，全部是本站研究设定而非公司指引；"
             "每条都先在归一化的余量图上出现一次，再各给一张自己的历史图。"
             + ("不接入的几条写在阈值图的说明里，不给近似值。" if kpi.get("excluded") else ""))
            if kpi else "本季笔记没有设定下季阈值，本节没有图。"
        ),
        "exhibits": next_ex,
    })
    sections.append({
        "id": "routine",
        "title": "四、长期常规跟踪",
        "description": plain_text(
            f"IBKR 专属的常规序列，窗口{cn_count(len(periods))}季而不是八季，"
            "因为其中几条要走完一整轮利率周期才显形："
            "收入结构的迁移、「其他收入」里的货币头寸摆动、净息差与生息资产、账户与户均权益、"
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
            "EPS 区间或利润率区间。微软、Alphabet 与 Visa 三页出于同样的理由也没有这类记录；"
            "亚马逊、Cadence、新思、NVIDIA、台积电与 Meta 六页有，是因为那六家把区间写进了申报文件。"
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
            "阈值是<b>本站的研究设定</b>，不是公司指引，也不是评级。" + threshold_note,
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
