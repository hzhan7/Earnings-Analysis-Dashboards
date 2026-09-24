#!/usr/bin/env python3
"""Build the SCHW quarterly-results page.

Same four-part, chart-led shape as the other company pages (上季兑现 → 本季重点
→ 下季跟踪 → 长期常规).  Schwab runs on the calendar year, so no quarter here
needs relabelling.

**Rolling a quarter edits `series/schw.json` and nothing else** (CLAUDE.md §9).
Every period, date, count and figure printed here is computed from the series.
A sentence that states a record, a window low, "all five" or "the only one" is
printed only while the series still says so, and gives way to a sentence that
is true when it stops. What belongs to one quarter only carries a ``period``
stamp and is read through `board.stamped_block` -- the settlement of what the
previous quarter's analysis left (`followup_closure`, its scorecard
`tracked_metric_verdicts`, and `prior_kpi_settlement`, the previous analysis's
monitoring lines), the next thresholds (`next_kpi`), the call's scenario
figures (`guidance.scenario`) and the release's one-quarter disclosures
(`latest_disclosures`). A block stamped for another quarter stops the build.
The follow-up closure, the previous analysis's lines and the next thresholds
are required -- every quarter from Q2 2026 on has an analysis before it and
one of its own, and a roll that forgot them would otherwise publish an empty
first or third section -- the other blocks leave their part of the page out
when absent. Where a one-quarter sentence has to restate a
number, the series writes a placeholder and the builder fills it; a threshold
block never stores a reading, it names the record the reading comes from
(`reads`). `_checks` is a separate reading of the quarter's release and of the
two analyses that the tests hold the page to; this builder never reads it.

Three things about this company break the template the other pages share, and
each one is answered on the page rather than smoothed over:

**No guidance-delivery record.**  TSMC, NVIDIA, Meta, Amazon, Cadence and
Synopsys all print a numeric range in a filing, which is what makes their
first section a multi-quarter record.  Schwab does not.  Its scenario guidance
is given on the Business Update calls (Winter / Investor Day / Summer / Fall)
and in 2026 it dropped the EPS point guidance entirely in favour of a
revenue / NIM / expense combination.  That is the Microsoft and Alphabet
situation -- a sourcing limit, not an editorial choice -- so this page carries
only the figures the company stated numerically on the current call, and
says in its notes why there is no record chart.

**The routine long series are a broker's, not a hyperscaler's.**  Capital
intensity and the depreciation wave mean nothing here.  What carries this
company is the split between rate-driven and fee-driven revenue, the operating
leverage between the two, and the volume/price relationship inside trading.

**The tracking framework is monthly and this page's axes are quarterly.**
Schwab publishes a monthly activity report, and both analyses' watch lists are
built on it.  Every quarterly release also prints that report's last thirteen
months, so a monthly line is settled from the release at the quarterly roll --
the page never moves between earnings dates -- and its reading enters the
threshold overview and the audit table; no chart runs on a monthly axis.

Published numbers are company-reported or transparent arithmetic.  No rating,
no target price, no valuation, no broker-attributed estimate.
"""

from __future__ import annotations

import calendar
import json
import operator
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import (  # noqa: E402
    ai_capex_cycle_table,
    cn_count,
    cn_ordinal,
    display_period,
    fill_story,
    headroom,
    headroom_exhibit,
    latest_block,
    number_exhibits,
    stamped_block,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "schw.json"
DATA_DIR = ROOT / "data"

# One tick per year keeps a thirty-eight-quarter axis readable.
LONG_STEP = 4

AUDIT_WORDS = {"unaudited": "未审计", "audited": "已审计"}
MONTHS = {"Q1": "一月至三月", "Q2": "四月至六月", "Q3": "七月至九月", "Q4": "十月至十二月"}

# Schwab's stated long-term operating objective for the adjusted Tier 1
# leverage ratio (the release's non-GAAP section says it manages capital to
# it). A company policy rather than a quarter's figure; it lives here, and the
# headline compares the quarter with its midpoint.
TIER1_TARGET = (6.75, 7.0)

# Fixed history: the quarter TD Ameritrade closed (2020-10-06), which is when
# bank deposit account fees start and the share count steps up.
TDA_CLOSE = "2020Q4"

FIVE_LINES = (
    ("净利息收入", "net_interest_revenue_usd_m", "净利息收入"),
    ("资产管理与行政管理费", "amaf_usd_m", "资产管理费"),
    ("交易收入", "trading_usd_m", "交易"),
    ("银行存款账户费", "bda_usd_m", "银行存款账户费"),
    ("其他", "other_usd_m", "其他"),
)

MONTH_WORDS = ("一月", "二月", "三月", "四月", "五月", "六月",
               "七月", "八月", "九月", "十月", "十一月", "十二月")

# The comparison each analysis wrote beside a line, as the event it watches for.
OPS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}
TRIGGER_WORDS = {"<": "低于", "<=": "不高于", ">": "高于", ">=": "不低于"}


def _cjk(char: str) -> bool:
    return "一" <= char <= "鿿"


def cn_join(left: str, right: str) -> str:
    """Join two phrases with the space this site's prose puts between Latin and Chinese."""
    if left and right and ((left[-1].isascii() and (left[-1].isalnum() or left[-1] in "%$") and _cjk(right[0]))
                           or (_cjk(left[-1]) and right[0].isascii() and right[0].isalnum())):
        return f"{left} {right}"
    return left + right


def filled(text: str, values: dict[str, str]) -> str:
    """`board.fill_story`, plus a refusal to publish a placeholder it could not see.

    `fill_story` only recognises lower-case letters and underscores, so a name
    with a digit in it (``{t1l_now}``) passes through as literal braces; the
    first draft of this page's closure table shipped one.
    """
    out = fill_story(text, values)
    stray = re.findall(r"\{[^{}]*\}", out)
    if stray:
        raise ValueError(f"unfilled placeholders {stray} in {text[:60]!r}")
    return out


def compact(period: str) -> str:
    """``2026Q2`` -> ``26Q2``."""
    return period[2:]


def company_period(period: str) -> str:
    """``2026Q2`` -> ``2Q26``, the way Schwab's own releases name a quarter."""
    return f"{period[-1]}Q{period[2:4]}"


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100.0


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def rounded(values: list, digits: int = 4) -> list:
    return [None if v is None else round(v, digits) for v in values]


def tenths_word(share: float) -> str:
    """``0.715`` -> ``'七成'``: a share of a whole, floored to tenths, in words."""
    return f"{cn_ordinal(int(share * 10))}成"


def tail(periods: list, *series: list) -> tuple:
    """Return the longest tail over which every series is populated.

    Schwab's operating metrics come from the earnings press releases, and the
    older releases carry fewer of them, so each chart's window is decided by
    the metric it draws rather than by the page.  Cutting to the longest
    complete tail keeps a chart from opening with a run of holes that look like
    the company stopped disclosing something mid-series.
    """
    start = 0
    for index in range(len(periods)):
        if all(s[index] is not None for s in series):
            start = index
            break
    else:
        return [], *([] for _ in series)
    for index in range(start, len(periods)):
        if any(s[index] is None for s in series):
            start = index + 1
    return periods[start:], *[s[start:] for s in series]


def axis(labels: list, step: int = LONG_STEP) -> list:
    """Blank every label but each ``step``-th and the last, keeping the axis legible."""
    keep = set(range(len(labels) - 1, -1, -step))
    return [label if index in keep else "" for index, label in enumerate(labels)]


def yoy(values: list) -> list:
    """Year-over-year percent change, ``None`` for the first four quarters."""
    out = []
    for index, value in enumerate(values):
        base = values[index - 4] if index >= 4 else None
        out.append(None if base in (None, 0) or value is None
                   else round(pct_change(value, base), 4))
    return out


def money_bn(value: float) -> str:
    """US$ billions with the sign outside the symbol: ``-135`` -> ``'−US$135B'``."""
    return f"{'−' if value < 0 else ''}US${abs(value):,.0f}B"


def is_top(values: list) -> bool:
    """The last value is the highest the series has printed."""
    return values[-1] >= max(v for v in values if v is not None)


def is_bottom(values: list) -> bool:
    return values[-1] <= min(v for v in values if v is not None)


def high_words(values: list, window: str) -> str:
    """「是…最高值」 only above every earlier value; a printed value that ties one is said as a tie."""
    earlier = [v for v in values[:-1] if v is not None]
    if not earlier or values[-1] > max(earlier):
        return f"是{window}里的最高值"
    if values[-1] == max(earlier):
        return f"追平{window}里的最高值"
    return ""


def first_filled(periods: list, values: list, offset: int = 0) -> str:
    """The period ``offset`` quarters after the first reading of a record."""
    first = next(i for i, value in enumerate(values) if value is not None)
    return periods[first + offset]


def nim_basis_words(staging: dict) -> str:
    """Which 2025 margins are the company's recast and which are still first prints.

    From 4Q25 Schwab took the long/short balances out of interest-earning
    assets and recast 2025; a recast value reaches this page only through a later
    release's year-ago column, so for a while the record mixes the two. The
    series says which is which (`nim_recast`), and the sentence is built from it,
    so the roll that replaces a first print also changes what this note says.
    """
    recast = staging.get("nim_recast")
    if not recast:
        return ""
    ops = staging["operating"]
    parts = []
    for quarter, rec in sorted(recast["quarters"].items()):
        used = ops["nim_pct"][ops["periods"].index(quarter)]
        if rec.get("recast") is not None:
            if used != rec["recast"]:
                raise ValueError(f"nim_pct for {quarter} is {used}, not the recast {rec['recast']} `nim_recast` names")
            parts.append(f"{quarter} {cn_join('用', rec['source'])}重印的 {rec['recast']:.2f}%（首印 {rec['first_print']:.2f}%）")
        else:
            if used != rec["first_print"]:
                raise ValueError(f"nim_pct for {quarter} is {used}, not the first print {rec['first_print']}")
            parts.append(f"{quarter} 仍是首印 {rec['first_print']:.2f}%（{rec['source']}说新口径下该季高 "
                         f"{rec['delta_pp']:.2f}pp，重印值要等下一份同比栏）")
    return recast["intro"] + "；".join(parts) + "。"


def filing_words(period: str, period_end: str) -> str:
    """This quarter's periodic filing: a 10-Q, or the 10-K for a fourth quarter."""
    if period.endswith("Q4"):
        return f"{period[:4]} 年 10-K"
    return f"截至 {period_end} 的 10-Q"


# ── months ───────────────────────────────────────────────────────────────────
# Schwab's monthly activity report is reprinted, thirteen months at a time, at
# the back of every quarterly release. The series keeps those months as one
# rolling block (`monthly`), appended three months per roll, so a monthly line
# is settled from the quarterly release and nothing on this page moves between
# earnings dates.

def quarter_months(period: str) -> list[str]:
    """``2026Q2`` -> ``['2026-04', '2026-05', '2026-06']``."""
    year, quarter = int(period[:4]), int(period[-1])
    return [f"{year}-{month:02d}" for month in range(3 * quarter - 2, 3 * quarter + 1)]


def month_word(month: str) -> str:
    """``2026-04`` -> ``四月``."""
    return MONTH_WORDS[int(month[5:]) - 1]


def shift_month(month: str, step: int) -> str:
    index = int(month[:4]) * 12 + int(month[5:]) - 1 + step
    return f"{index // 12}-{index % 12 + 1:02d}"


def quarter_end_month(period: str) -> str:
    return quarter_months(period)[-1]


class Monthly:
    """The months of the rolling block, read for one quarter.

    A quarter whose three months are not in the block stops the build: the roll
    appends them from the release's own monthly table, and a page that settled a
    monthly line on last quarter's months would be settling the wrong quarter.
    """

    def __init__(self, staging: dict, period: str) -> None:
        self.block = staging["monthly"]
        self.index = {month: i for i, month in enumerate(self.block["months"])}
        self.quarter = quarter_months(period)
        missing = [month for month in self.quarter if month not in self.index]
        if missing:
            raise ValueError(f"series block `monthly` has no {missing}: append the quarter's three "
                             "months from its release's Monthly Activity Report with the roll")

    def value(self, key: str, month: str) -> float:
        if month not in self.index or self.block[key][self.index[month]] is None:
            raise ValueError(f"series block `monthly` has no {key} for {month}")
        return self.block[key][self.index[month]]

    def before(self, key: str) -> list[tuple[str, float]]:
        """Every month before this quarter, with its value."""
        first = self.quarter[0]
        return [(month, self.block[key][i]) for month, i in self.index.items()
                if month < first and self.block[key][i] is not None]


# ── threshold lines ──────────────────────────────────────────────────────────
# Both threshold blocks -- `prior_kpi_settlement` (the previous analysis's lines,
# settled in section one) and `next_kpi` (this analysis's section 15.1 lines,
# watched in section three) -- carry the analysis's lines as data: the row of
# its table a line comes from, its colour (`tier`: warn / red / green, or
# `watch` for a table that wrote no trigger), the comparison the analysis wrote
# (`op`, `threshold` or a `baseline` it named in words), the quarter it settles
# in (`settles`) and the record it is read against (`reads`). No reading is
# typed into a block: every one is computed here from the series, so a roll
# moves this quarter's `next_kpi` into next quarter's `prior_kpi_settlement` as
# it stands and the page settles it without a code change.

TIER_WORDS = {"warn": "警示线", "red": "红色线", "green": "正面信号线", "watch": "追踪线"}
TIER_SHORT = {"warn": "橙色警示", "red": "红色", "green": "绿色", "watch": "追踪"}
TIER_COLOR = {"warn": "ORANGE", "red": "RED", "green": "GREEN", "watch": "GREY"}
RISK = ("warn", "red")
# The report's own words for the tax month of a quarter (「4 月税季」).
TAX_MONTHS = ("04",)


def month_days(month: str) -> int:
    return calendar.monthrange(int(month[:4]), int(month[5:]))[1]


def annualized_growth(monthly: "Monthly", month: str) -> float:
    """A month's core net new assets as an annualized organic growth rate, %.

    Schwab's formula, reproduced from the four rates it printed (June 2026 5.8%,
    1Q26 5.4%, 1Q25 5.5%, full-year 2024 4.3%): the period's core net new assets
    over the client assets it opened with, scaled by 365 over the days in the
    period. Scaling by twelve over the closing assets matches two of the four
    and misses 2024 by 0.7pp.
    """
    return (monthly.value("core_net_new_assets_usd_bn", month)
            / monthly.value("beginning_client_assets_usd_bn", month) * 365 / month_days(month) * 100)


def year_ago_quarter(period: str) -> str:
    return f"{int(period[:4]) - 1}{period[4:]}"


def period_order(label: str) -> tuple[int, int]:
    """``'Q3 2026'`` / ``'2026Q3'`` -> ``(2026, 3)``."""
    quarter, year = display_period(label).split()
    return int(year), int(quarter[1])


def short_period(label: str) -> str:
    """``'Q4 2026'`` -> ``'4Q26'``, the way Schwab names a quarter."""
    year, quarter = period_order(label)
    return f"{quarter}Q{str(year)[2:]}"


def quarterly_history(staging: dict, reads: str) -> tuple[list[str], list[float | None]]:
    """The quarter-by-quarter record a quarterly line is read against (labels are ``2016Q1``)."""
    ops, fin = staging["operating"], staging["financials"]
    periods = staging["periods"]
    if reads == "nim":
        return periods, ops["nim_pct"]
    if reads == "rpt":
        return periods, ops["revenue_per_trade_usd"]
    if reads == "adj_t1l":
        return periods, ops["adjusted_tier1_leverage_pct"]
    if reads == "repurchases":
        return periods, ops["repurchases_usd_bn"]
    if reads in ("swa_flow_yoy", "mi_flow_yoy"):
        key = {"swa_flow_yoy": "swa_net_flow_yoy_pct", "mi_flow_yoy": "mi_net_flow_yoy_pct"}[reads]
        return periods, ops[key]
    if reads == "revenue_yoy":
        earlier = dict(zip(staging["revenue_2015_usd_m"]["quarters"], staging["revenue_2015_usd_m"]["usd_m"]))
        revenue = dict(zip(periods, fin["revenue_usd_m"]))
        values = []
        for period in periods:
            base = revenue.get(year_ago_quarter(period), earlier.get(year_ago_quarter(period)))
            values.append(None if base is None else round(pct_change(revenue[period], base), 4))
        return periods, values
    if reads == "adj_expense_yoy":
        return periods, yoy(fin["adjusted_total_expenses_usd_m"])
    if reads == "dats_qoq":
        dats = ops["dats_thousands"]
        return periods, [None] + [round(pct_change(b, a), 4) for a, b in zip(dats, dats[1:])]
    if reads in ("pal_yoy", "pal_qoq"):
        block = staging["pledged_asset_lines"]
        pal = dict(zip(block["quarters"], block["usd_bn"]))
        missing = [p for p in periods if p not in pal]
        if missing:
            raise ValueError(f"series block `pledged_asset_lines` has no {missing}: append the quarter "
                             "from its 10-Q / 10-K loan note with the roll")
        lag = 4 if reads == "pal_yoy" else 1
        order = block["quarters"]
        values = []
        for period in periods:
            i = order.index(period)
            values.append(None if i < lag else round(pct_change(pal[period], pal[order[i - lag]]), 4))
        return periods, values
    if reads == "margin_ex_ls_qoq":
        margin, ls = ops["margin_loans_usd_bn"], ops["long_short_margin_loans_usd_bn"]
        values = [None]
        for i in range(1, len(periods)):
            if ls[i] is None or ls[i - 1] is None:
                values.append(None)
            else:
                values.append(round(pct_change(margin[i] - ls[i], margin[i - 1] - ls[i - 1]), 4))
        return periods, values
    raise ValueError(f"a line reads {reads!r}, which build/schw.py does not know")


# How each record is named, printed and charted. `chart` is False where the
# record has too few points or runs on months, and `why` says so on the page.
READS = {
    "nim": {"name": "NIM", "fmt": "pct2", "ylab": "%", "text": lambda v: f"{v:.2f}%",
            "line": lambda t: f"{t:.2f}%"},
    "revenue_yoy": {"name": "净收入同比", "fmt": "pct1", "ylab": "% YoY", "text": lambda v: f"{v:+.1f}%",
                    "line": lambda t: f"{t:g}%"},
    "adj_expense_yoy": {"name": "调整后费用同比", "fmt": "pct1", "ylab": "% YoY", "text": lambda v: f"{v:+.1f}%",
                        "line": lambda t: f"{t:g}%", "printed": "adjusted_total_expenses_printed_yoy_pct"},
    "rpt": {"name": "每笔交易收入 RPT", "fmt": "usd2", "ylab": "US$/笔", "text": lambda v: f"${v:.2f}",
            "line": lambda t: f"${t:.2f}"},
    "dats_qoq": {"name": "DATs 环比", "text": lambda v: f"{v:+.0f}%", "line": lambda t: f"{t:g}%",
                 "chart": False},
    "pal_yoy": {"name": "PAL 余额同比", "fmt": "pct1", "ylab": "% YoY", "text": lambda v: f"{v:+.1f}%",
                "line": lambda t: f"+{t:g}%", "printed": "pledged_asset_line_yoy_pct"},
    "pal_qoq": {"name": "PAL 余额环比", "fmt": "pct1", "ylab": "% QoQ", "text": lambda v: f"{v:+.1f}%",
                "line": lambda t: f"{t:g}%"},
    "margin_ex_ls_qoq": {"name": "剔除 long/short 的保证金余额环比", "text": lambda v: f"{v:+.1f}%",
                         "line": lambda t: f"{t:g}%", "chart": False,
                         "why": "季末的 long/short 拆分公司自 4Q25 起才印，环比只有两个读数"},
    "swa_flow_yoy": {"name": "SWA 净流入同比", "text": lambda v: f"{v:+.0f}%", "line": lambda t: f"+{t:g}%",
                     "chart": False, "why": "公司只在新闻稿要点里用一句话印增速、不印金额，SWA 这一句本季第一次出现"},
    "mi_flow_yoy": {"name": "Managed Investing 净流入同比", "text": lambda v: f"{v:+.0f}%",
                    "line": lambda t: f"+{t:g}%", "chart": False,
                    "why": "公司只在新闻稿要点里用一句话印增速、不印金额（1Q25 起每季一句）"},
    "repurchases": {"name": "回购支出", "fmt": "f1", "ylab": "US$B", "text": lambda v: f"US${v:.1f}B",
                    "line": lambda t: f"US${t:g}B/季",
                    # the analysis wrote no basis; the release prints the other one
                    "basis": lambda d: (f"新闻稿要点按成交口径印本季回购约 US${d['buyback_usd_m'] / 1000:.1f}B；"
                                        "本页的线按现金流量表口径结算，两者差结算时点。"
                                        if d.get("buyback_usd_m") is not None else "")},
    "adj_t1l": {"name": "调整后 Tier 1 杠杆率", "fmt": "pct1", "ylab": "%", "text": lambda v: f"{v:.1f}%",
                "line": lambda t: f"{t:g}%"},
    "core_nna_annualized": {"name": "单月 core NNA 年化增速", "line": lambda t: f"{t:g}%", "chart": False,
                            "monthly": True},
    "core_nna_non_tax_month": {"name": "非税季单月 core NNA", "line": lambda t: f"US${t:g}B", "chart": False,
                               "monthly": True},
    "dats_month_low": {"name": "单月 DATs", "line": lambda t: f"{t / 1000:g}M", "chart": False, "monthly": True},
    "new_accounts_month_low": {"name": "单月新开经纪账户", "line": lambda t: f"{t:g} 千", "chart": False,
                               "monthly": True},
    "core_nna_month": {"name": "core 净新增资产", "chart": False, "monthly": True},
    "margin_month_end": {"name": "季末保证金余额", "chart": False, "monthly": True},
}
OP_SIGNS = {"<": "<", "<=": "≤", ">": ">", ">=": "≥"}


def line_label(line: dict) -> str:
    """The short axis label of a line: 「单月 DATs <9.5M」, 「单月 core NNA 年化增速 <4%（连续两月）」."""
    spec = READS[line["reads"]]
    label = f"{spec['name']} {OP_SIGNS[line['op']]}{spec['line'](line['threshold'])}"
    if line.get("window", 1) > 1:
        label += f"（连续{cn_count(line['window'])}月）"
    if line.get("consecutive", 1) > 1:
        label += f"（连续{cn_count(line['consecutive'])}季）"
    return label


MONTHLY_WHY = "阈值是单月口径，读数取自本季新闻稿印的月度活动表，本页不画月度走势"


def read_line(staging: dict, line: dict) -> dict:
    """This quarter's reading of one line, and the line it is read against.

    Returns ``value``, ``threshold`` (the line's number, or the reference it
    named in words, looked up here), the printed ``text``, a short ``label``
    and a sentence ``subject``. Quarterly records also return their ``history``.
    """
    period = staging["periods"][-1]
    reads = line["reads"]
    spec = READS.get(reads)
    if spec is None:
        raise ValueError(f"line {line.get('id')!r} reads {reads!r}, which build/schw.py does not know")
    if reads in ("core_nna_month", "margin_month_end") or (reads == "dats_month_low" and line.get("tier") == "watch"):
        got = watch_reading(staging, period, line)
        return {**got, "history": None}
    monthly_reads = ("core_nna_annualized", "core_nna_non_tax_month", "dats_month_low", "new_accounts_month_low")
    if reads in monthly_reads:
        monthly = Monthly(staging, period)
        window = line.get("window", 1)
        if reads == "core_nna_annualized":
            # 「连续 N 个月」: the run has to end inside this quarter, so a window may
            # start in the quarter before; the reading is the window that came
            # closest -- the better month of the worst window.
            windows = [[shift_month(end, -k) for k in range(window - 1, -1, -1)] for end in monthly.quarter]
            rates = {m: annualized_growth(monthly, m) for w in windows for m in w}
            worst = min(windows, key=lambda w: max(rates[m] for m in w))
            value = max(rates[m] for m in worst)
            where = "、".join(month_word(m) for m in worst)
            text = (f"{value:.2f}%（{where}）" if window == 1 else
                    f"{value:.2f}%（最接近的连续{cn_count(window)}个月是{where}，其中较高的一个月）")
            return {"value": value, "threshold": line["threshold"], "text": text,
                    "label": line_label(line),
                    "history": None}
        if reads == "core_nna_non_tax_month":
            months = [m for m in monthly.quarter if m[5:] not in TAX_MONTHS]
            month = min(months, key=lambda m: monthly.value("core_net_new_assets_usd_bn", m))
            value = monthly.value("core_net_new_assets_usd_bn", month)
            return {"value": value, "threshold": line["threshold"], "text": f"US${value:,.1f}B（{month_word(month)}）",
                    "label": line_label(line), "history": None}
        key = {"dats_month_low": "dats_thousands", "new_accounts_month_low": "new_brokerage_accounts_thousands"}[reads]
        month = min(monthly.quarter, key=lambda m: monthly.value(key, m))
        value = monthly.value(key, month)
        text = (f"{value / 1000:.2f}M（{month_word(month)}，季内最弱）" if key == "dats_thousands"
                else f"{value:,.0f} 千（{month_word(month)}，季内最弱）")
        return {"value": value, "threshold": line["threshold"], "text": text, "label": line_label(line),
                "history": None}
    labels, values = quarterly_history(staging, reads)
    value = values[-1]
    if value is None:
        raise ValueError(f"line {line.get('id')!r}: {reads} has no reading for {period}")
    return {"value": value, "threshold": line["threshold"], "text": spec["text"](value),
            "label": line_label(line) if "op" in line and "line" in spec else spec["name"],
            "history": (labels, values)}


def line_direction(line: dict) -> str:
    """The favourable side of a line: a warning fires when the reading crosses it,
    a green line is met when the reading reaches it."""
    if line["tier"] not in TIER_WORDS:
        raise ValueError(f"line {line.get('id')!r} has no tier the page knows: {line['tier']!r}")
    if line["op"] not in OPS:
        raise ValueError(f"line {line.get('id')!r} has no comparison the page knows: {line['op']!r}")
    up = (line["tier"] == "green") == (line["op"] in (">", ">="))
    return "up" if up else "down"


def line_hit(staging: dict, line: dict, got: dict) -> bool:
    """Whether the event the analysis wrote for this line happened.

    A line that asks for several quarters in a row (`consecutive`) needs that
    many readings, all on the far side; one whose other half (`and`) did not
    happen did not happen.
    """
    hit = OPS[line["op"]](got["value"], got["threshold"])
    need = line.get("consecutive", 1)
    if hit and need > 1:
        history = got.get("history")
        recent = [v for v in (history[1] if history else [])][-need:]
        hit = len(recent) == need and all(v is not None and OPS[line["op"]](v, got["threshold"]) for v in recent)
    for leg in line.get("and", []):
        leg_got = read_line(staging, {**leg, "tier": line["tier"]})
        hit = hit and OPS[leg["op"]](leg_got["value"], leg["threshold"])
    return hit


def line_state(staging: dict, line: dict, got: dict, era: str) -> str:
    hit = line_hit(staging, line, got)
    if line["tier"] == "green":
        return ("已达到" if hit else "还没到") if era == "next" else ("达到" if hit else "没到")
    if line["tier"] == "watch":
        return "发生" if hit else "没有发生"
    return ("已越线" if hit else "在安全侧") if era == "next" else ("越线" if hit else "守住")


def line_text(line: dict) -> str:
    """The comparison as the page prints it: 「低于 3.05%」「连续两个月低于 4%」「且 DATs 同步环比回落」."""
    spec = READS[line["reads"]]
    text = f"{TRIGGER_WORDS[line['op']]} {spec['line'](line['threshold'])}"
    if line.get("window", 1) > 1:
        text = f"连续{cn_count(line['window'])}个月{text}"
    if line.get("consecutive", 1) > 1:
        text = f"连续{cn_count(line['consecutive'])}季{text}"
    for leg in line.get("and", []):
        text += cn_join("，且", leg["words"])
    return text


def headroom_or_gap(line: dict, got: dict) -> str:
    """Distance to the line: percent where the line is not zero, points where it is."""
    if line["threshold"] == 0:
        return f"{got['value'] - got['threshold']:+.1f}pp"
    return f"{headroom(line_direction(line), got['threshold'], got['value']):+.1f}%"


def reading_charts(staging: dict, readings: list, era: str, set_in: str, later: list | None = None) -> list:
    """One chart per quarterly record, every due line of this era drawn on it.

    ``era`` is ``next`` (the lines are watched: the title names them and where
    the reading stands now) or ``prior`` (the lines are settled). A line due in
    a later quarter is named under its record's chart, not drawn.
    """
    groups: dict[str, list] = {}
    for line, got in readings:
        if READS[line["reads"]].get("chart", True) and got["history"]:
            groups.setdefault(line["reads"], []).append((line, got))
    charts = []
    for reads, group in groups.items():
        spec = READS[reads]
        labels, values = tail(*group[0][1]["history"])
        now = group[0][1]["text"]
        if era == "next":
            title = (f"{spec['name']}：下季" + "、".join(f"{TIER_WORDS[line['tier']]} {spec['line'](line['threshold'])}"
                                                    for line, _ in group) + f"，当前 {now}")
        else:
            title = (f"{spec['name']} {now}：" + "、".join(
                f"{line_state(staging, line, got, 'prior')}上季{TIER_WORDS[line['tier']]} {spec['line'](line['threshold'])}"
                for line, got in group))
        series = [{"name": spec["name"], "values": rounded(values), "color": "NAVY"}]
        for line, _ in group:
            series.append({"name": f"{'下季' if era == 'next' else '上季'}{TIER_WORDS[line['tier']]}：{line_text(line)}",
                           "values": [line["threshold"]] * len(labels), "color": TIER_COLOR[line["tier"]]})
        filled_values = [v for v in values if v is not None]
        crossed = [(line, sum(1 for v in filled_values if OPS[line["op"]](v, line["threshold"]))) for line, _ in group]
        pending = [line for line in (later or []) if line["reads"] == reads]
        disclosures = staging.get("latest_disclosures") or {}
        printed = disclosures.get(spec.get("printed", ""))
        note = (
            (cn_join("本季", spec["name"]) + f"按公司印的两个数自算为 {now}，新闻稿按整数印「{printed:+.0f}%」。"
             if printed is not None else "")
            + spec.get("basis", lambda d: "")(disclosures)
            + "".join(f"{TIER_WORDS[line['tier']]}「{line_text(line)}」：余量 {headroom_or_gap(line, got)}"
                      + (f"，{line_state(staging, line, got, era)}" if era == "prior" else "")
                      + "。" for line, got in group)
            + "".join(f"同一行的{TIER_WORDS[line['tier']]}「{line_text(line)}」要到 {short_period(line['settles'])} 才结算，"
                      "这里不画。" for line in pending)
            + f"图上{cn_count(len(filled_values))}个季度里，"
            + "、".join(cn_join(f"{TRIGGER_WORDS[line['op']]} {spec['line'](line['threshold'])}", f"的有{cn_count(count)}季")
                       for line, count in crossed) + "。"
        )
        charts.append({
            "kind": "lines",
            "title": title,
            "xlabels": axis([compact(p) for p in labels]),
            "series": series,
            "fmt": spec["fmt"],
            "yfmt": spec["fmt"],
            "label_fmt": spec["fmt"],
            "end_label": True,
            "ylab": spec["ylab"],
            "note": note,
            "src_extra": (f"线取自{'本季' if era == 'next' else '上季'}（{set_in}）本地分析的关键观察指标，不是公司指引；"
                          + READ_SOURCES.get(reads, "读数取自各季业绩新闻稿与 10-Q / 10-K。")),
        })
    return charts


READ_SOURCES = {
    "nim": "NIM 逐季取自各季新闻稿的 Net Interest Revenue 表（公司印到两位小数）。",
    "revenue_yoy": "净收入取自各期 10-Q / 10-K 利润表（第四季度为全年减前三季），同比为自算（D）。",
    "adj_expense_yoy": "调整后总费用取自各季新闻稿的非 GAAP 调节表（三个月栏），同比为自算（D）。",
    "rpt": "每笔交易收入取自各季新闻稿 Financial and Operating Highlights 表。",
    "pal_yoy": "PAL 余额取自各期 10-Q / 10-K 贷款附注，同比为自算（D）。",
    "pal_qoq": "PAL 余额取自各期 10-Q / 10-K 贷款附注，环比为自算（D）。",
    "repurchases": "回购支出取自各期 10-Q / 10-K 现金流量表，按年初至今逐季相减（D）；新闻稿按成交口径印整数十亿，差结算时点。",
    "adj_t1l": "调整后 Tier 1 杠杆率取自各季新闻稿的非 GAAP 表（公司 2024 年起按季印）。",
}


def lines_table(staging: dict, block: dict, readings: list, era: str, later: frozenset = frozenset()) -> dict:
    """The drawer's view of a threshold block: every row of the analysis's table, line by line.

    ``later`` holds the ids `split_by_date` put off to a later quarter, so the
    drawer and the overview cannot disagree on which lines were settled.
    """
    rows = []
    page = display_period(staging["periods"][-1])
    by_row = {}
    for line, got in readings:
        by_row.setdefault(line["row"], []).append((line, got))
    story = {"sweep_ex_ls": sweep_ex_ls_text(staging)}
    for row in block["rows"]:
        subject = row.get("subject", row.get("text"))
        if row["row"] not in by_row:
            rows.append([str(row["row"]), subject, row.get("text", ""), row.get("action", "—"), "—", "—", "—",
                         ("不结算：" + filled(row["why"], story)) if "why" in row else "—"])
            continue
        for line, got in by_row[row["row"]]:
            settles = line.get("settles", page)
            if era == "prior":
                status = (f"未到期（{short_period(settles)} 结算）" if line["id"] in later
                          else line_state(staging, line, got, "prior"))
            else:
                status = f"{short_period(settles)} 结算；当前{line_state(staging, line, got, 'next')}"
            rows.append([str(row["row"]), subject, row.get("text", ""), TIER_SHORT[line["tier"]], line_text(line),
                         got["text"], headroom_or_gap(line, got), status])
    return {
        "title": (f"{'下季' if era == 'next' else '上季'}{block['table_name']}逐行（{block['set_in']} 本地分析{block['section']}）："
                  "原文、本页的线与读数"),
        "headers": ["行", "指标", "原文阈值", "档", "本页的线", "本季读数" if era == "prior" else "当前值",
                    "余量 D", "结算" if era == "prior" else "现状"],
        "rows": rows,
    }


def sweep_ex_ls_text(staging: dict) -> str:
    """The one underlying-cash figure the release gives: quarter-end sweep less the short credits."""
    disclosures = staging.get("latest_disclosures") or {}
    if disclosures.get("transactional_sweep_cash_usd_bn") is None or disclosures.get("short_credits_usd_bn") is None:
        return "当季没有印"
    net = disclosures["transactional_sweep_cash_usd_bn"] - disclosures["short_credits_usd_bn"]
    return (f"{month_word(quarter_end_month(staging['periods'][-1]))}末 US${disclosures['transactional_sweep_cash_usd_bn']:,.1f}B"
            f" − US${disclosures['short_credits_usd_bn']:,.1f}B = US${net:,.1f}B")


# ── section one ──────────────────────────────────────────────────────────────

def watch_reading(staging: dict, period: str, line: dict) -> dict:
    """This quarter's reading of one line the previous analysis was watching.

    The line names the record it is read against (``reads``) and either a
    number (``threshold``) or the reference the analysis wrote in words
    (``baseline``: 「vs 去年同月」, 「是否继续创新高」), which is looked up here.
    Nothing is typed into the block, so a roll that moves last quarter's lines
    in as they stood settles them against the new quarter's figures.
    """
    monthly = Monthly(staging, period)
    reads = line["reads"]
    # A reference written in words is read one way per record; a line that
    # names another reference stops the build rather than being compared
    # against the one this function happens to know.
    known = {"core_nna_month": "year_ago_month", "margin_month_end": "prior_high"}
    if line.get("baseline") != known.get(reads):
        raise ValueError(f"line {line['id']} reads {reads!r} against baseline {line.get('baseline')!r}; "
                         f"build/schw.py reads it against {known.get(reads)!r}")
    if reads == "core_nna_month":
        month = monthly.quarter[line["month"] - 1]
        year_ago = shift_month(month, -12)
        value = monthly.value("core_net_new_assets_usd_bn", month)
        base = monthly.value("core_net_new_assets_usd_bn", year_ago)
        return {"subject": f"{month_word(month)} core 净新增资产", "label": f"{month_word(month)} core NNA",
                "month": month, "value": value, "threshold": base,
                "value_text": f"US${value:,.1f}B", "threshold_text": f"去年{month_word(year_ago)} US${base:,.1f}B"}
    if reads == "dats_month_low":
        month = min(monthly.quarter, key=lambda m: monthly.value("dats_thousands", m))
        value = monthly.value("dats_thousands", month)
        return {"subject": "季内最弱一个月的 DATs", "label": "DATs 最弱月", "month": month,
                "value": value, "threshold": line["threshold"],
                "value_text": f"{value / 1000:.2f}M（{month_word(month)}）",
                "threshold_text": f"约 {line['threshold'] / 1000:.1f}M"}
    if reads == "margin_month_end":
        month = monthly.quarter[-1]
        value = monthly.value("margin_balances_usd_bn", month)
        # The previous high is read off every month-end the releases printed
        # before this quarter and every quarter-end in the client-assets record,
        # which is the same balance ("Margin loans outstanding").
        ops = staging["operating"]
        end = ops["periods"].index(period)
        earlier = dict(monthly.before("margin_balances_usd_bn"))
        for quarter, balance in zip(ops["periods"][:end], ops["margin_loans_usd_bn"][:end]):
            if balance is not None:
                earlier.setdefault(quarter_end_month(quarter), balance)
        where = max(sorted(earlier), key=lambda m: earlier[m])
        within = " / ".join(f"{monthly.value('margin_balances_usd_bn', m):,.1f}" for m in monthly.quarter)
        return {"subject": "季末保证金余额", "label": "季末保证金余额", "month": month,
                "value": value, "threshold": earlier[where],
                "value_text": f"US${value:,.1f}B（季内三个月末依次 {within}）",
                "threshold_text": f"此前最高 US${earlier[where]:,.1f}B（{where[:4]} 年{month_word(where)}末）"}
    raise ValueError(f"a line reads {reads!r}, which build/schw.py does not know")


def row_reading(staging: dict, period: str, row: dict) -> str:
    """One sentence of this quarter's figures for a row the analysis gave no number."""
    monthly = Monthly(staging, period)
    reads = row["reads"]
    if reads == "sweep_month_path":
        start = shift_month(monthly.quarter[0], -1)
        path = [(m, monthly.value("transactional_sweep_cash_usd_bn", m)) for m in [start] + monthly.quarter]
        lower = sum(1 for _, v in path[1:] if v < path[0][1])
        return ("月末余额依次是" + " → ".join(f"{month_word(m)} {v:,.1f}" for m, v in path) + "（US$B），"
                + ("季内没有一个月末低于上季末" if not lower else f"季内有{cn_count(lower)}个月末低于上季末"))
    if reads == "client_cash_path":
        start = shift_month(monthly.quarter[0], -1)
        year_ago = shift_month(monthly.quarter[-1], -12)
        path = " → ".join(f"{month_word(m)} {monthly.value('client_cash_pct', m):.1f}%"
                          for m in [start] + monthly.quarter)
        return (f"{path}（去年{month_word(year_ago)} "
                f"{monthly.value('client_cash_pct', year_ago):.1f}%）")
    raise ValueError(f"a row reads {reads!r}, which build/schw.py does not know")


def counted(items: list[dict], labels: list[str], what: str) -> list[int]:
    """Counts per label, from the items -- never typed -- and no item outside the labels."""
    stray = sorted({item["verdict"] for item in items} - set(labels))
    if stray:
        raise ValueError(f"{what} carries verdicts {stray} that have no bar")
    return [sum(1 for item in items if item["verdict"] == label) for label in labels]


def numbers_word(ns: list[int]) -> str:
    """``[7, 8, 9, 10]`` -> ``第 7–10 条``-style run, ``[2, 3, 6]`` -> ``第 2、3、6``."""
    if len(ns) > 2 and ns == list(range(ns[0], ns[-1] + 1)):
        return f"第 {ns[0]}–{ns[-1]}"
    return "第 " + "、".join(str(n) for n in ns)


def story_values(staging: dict, blocks: dict, scenario: dict | None) -> dict[str, str]:
    """The numbers the one-quarter sentences restate, computed from the series."""
    ops, fin = staging["operating"], staging["financials"]
    period = staging["periods"][-1]
    monthly = Monthly(staging, period)
    nim, dats, rpt = ops["nim_pct"], ops["dats_thousands"], ops["revenue_per_trade_usd"]
    tier1 = ops["adjusted_tier1_leverage_pct"]
    investor = ops["net_new_assets_investor_services_usd_bn"]
    start = shift_month(monthly.quarter[0], -1)
    values = {
        "sweep_path": " → ".join(
            f"{month_word(m)} {monthly.value('transactional_sweep_cash_usd_bn', m):,.1f}"
            for m in [start] + monthly.quarter) + "（US$B）",
        "nim_now": f"{nim[-1]:.2f}%",
        "nim_qoq": f"{(nim[-1] - nim[-2]) * 100:+.0f}bp",
        "dats_now": f"{dats[-1] / 1000:.2f}M",
        "dats_qoq": signed(pct_change(dats[-1], dats[-2]), 0),
        "rpt_now": f"${rpt[-1]:.2f}",
        "tier_now": f"{tier1[-1]:.1f}%",
        "is_qoq": signed(pct_change(investor[-1], investor[-2]), 0),
    }
    nim_range = next((item for item in (scenario or {}).get("items", []) if item["metric"] == "全年 NIM"), None)
    if nim_range:
        values["nim_range"] = f"{nim_range['low']:.2f}%–{nim_range['high']:.2f}%"
    disclosures = blocks["disclosures"]
    if disclosures:
        values["buyback_now"] = f"US${disclosures['buyback_usd_m'] / 1000:.1f}B"
        if disclosures.get("prior_quarter_buyback_usd_m"):
            values["buyback_before"] = f"US${disclosures['prior_quarter_buyback_usd_m'] / 1000:.1f}B"
        for key, word in (("preferred_redeemed_usd_bn", "pref_redeemed"), ("preferred_issued_usd_bn", "pref_issued")):
            if disclosures.get(key) is not None:
                values[word] = f"US${disclosures[key]:.1f}B"
    return values


def settled_exhibits(staging: dict, blocks: dict, story: dict, when: dict) -> tuple[list, list]:
    """Section one: what the previous quarter's analysis left, settled.

    (a) the follow-up questions as this quarter's analysis judged them in its
    section 0, with its scorecard of last quarter's judgements beside them, and
    (b) the previous analysis's own watch lines, read against this quarter's
    figures. Returns the charts and their audit tables.
    """
    period = staging["periods"][-1]
    closure, verdicts, prior = blocks["closure"], blocks["verdicts"], blocks["prior"]
    charts, tables = [], []

    labels = closure["labels"]
    counts = counted(closure["items"], labels, "followup_closure")
    groups = "；".join(f"{label}：{numbers_word([i['n'] for i in closure['items'] if i['verdict'] == label])} 问"
                      for label, count in zip(labels, counts) if count)
    charts.append({
        "kind": "bars_labeled",
        "title": (f"上季 {len(closure['items'])} 条待验证问题："
                  + "、".join(f"{count} 条{label}" for label, count in zip(labels, counts))),
        "xlabels": labels,
        "values": counts,
        "legend": "问题条数",
        "fmt": "f0",
        "yfmt": "f0",
        "label_fmt": "f0",
        "ylab": "条",
        "note": f"{groups}。{closure['rule']}每一问的原文、判定与本季读数见核对抽屉。",
        "src_extra": (f"问题清单来自上季（{closure['set_in']}）本地分析的下季度关注清单；判定取自本季本地分析第〇节，"
                      f"读数取自 {when['release']} 业绩新闻稿与当季电话会。"),
    })
    tables.append({
        "title": f"上季 {len(closure['items'])} 条待验证问题：本季分析第〇节的判定与本季读数",
        "headers": ["问", "上季留下的问题", "本季判定", "本季读数与依据"],
        "rows": [[str(item["n"]), item["topic"], item["verdict"], filled(item["answer"], story)]
                 for item in closure["items"]],
    })

    if verdicts:
        v_labels = verdicts["labels"]
        v_counts = counted(verdicts["items"], v_labels, "tracked_metric_verdicts")
        quiet = [item["n"] for item in verdicts["items"] if not item["topic"]]
        charts.append({
            "kind": "bars_labeled",
            "title": (f"上季 {len(verdicts['items'])} 条判断："
                      + "、".join(f"{count} 条{label}" for label, count in zip(v_labels, v_counts))),
            "xlabels": v_labels,
            "values": v_counts,
            "legend": "判断条数",
            "fmt": "f0",
            "yfmt": "f0",
            "label_fmt": "f0",
            "ylab": "条",
            "note": (filled(verdicts["summary"], story)
                     + "归类按本季分析「上季判断记分卡」的打分列：✅ 记验证、❌ 记证伪、⏳ 记尚未到期，"
                     "原文打「❌幅度/✅方向」的单列为方向对但幅度错。"
                     + (f"{numbers_word(quiet)} 条是{verdicts['unrestated']}，本页只计入判定、不转述内容（见口径说明）。"
                        if quiet else "")),
            "src_extra": f"判断来自上季（{verdicts['set_in']}）本地分析，不是公司指引；判定取自本季本地分析。",
        })
        tables.append({
            "title": f"上季 {len(verdicts['items'])} 条判断：本季分析记分卡的判定",
            "headers": ["条", "上季判断", "本季判定"],
            "rows": [[str(item["n"]), item["topic"] or "（本页不转述）", item["verdict"]]
                     for item in verdicts["items"]],
        })

    watched = [line for line in prior["lines"] if line.get("tier") == "watch"]
    ruled = [line for line in prior["lines"] if line.get("tier") != "watch"]
    if watched:
        watch_charts, watch_table = watch_settlement(staging, prior, watched)
        charts += watch_charts
        tables.append(watch_table)
    if ruled:
        rule_charts, rule_table = rule_settlement(staging, prior, ruled)
        charts += rule_charts
        tables.append(rule_table)
    return charts, tables


def watch_settlement(staging: dict, prior: dict, lines: list[dict]) -> tuple[list, dict]:
    """A monitoring table that named what to watch but wrote no trigger.

    The chart is neutral -- its sign only says which side of the line the
    reading fell on -- because the analysis did not say which side was bad.
    """
    period = staging["periods"][-1]
    readings = [(line, read_line(staging, line)) for line in lines]
    for line, _ in readings:
        line_direction({**line, "tier": "warn"})     # validates the comparison
    happened = {line["id"]: OPS[line["op"]](got["value"], got["threshold"]) for line, got in readings}

    # One clause per row of the table; a row settled month by month says its
    # months once when they all came out the same way.
    clauses = []
    for row in prior["rows"]:
        group = [(line, got) for line, got in readings if line["row"] == row["row"]]
        if not group:
            continue
        states = {happened[line["id"]] for line, _ in group}
        if len(group) > 1 and len(states) == 1 and all(got.get("month") for _, got in group):
            state = states.pop()
            months = "、".join(month_word(got["month"]) for _, got in group)
            subject = group[0][1]["subject"].split(" ", 1)[1]
            clauses.append(f"{months}的 {subject}都{'' if state else '没有'}{group[0][0]['event']}")
        else:
            clauses.extend(cn_join(got["subject"], ("" if happened[line["id"]] else "没有") + line["event"])
                           for line, got in group)
    no_line = [row for row in prior["rows"] if not any(line["row"] == row["row"] for line in prior["lines"])]
    chart = {
        "kind": "diverging_bars",
        "title": f"上季{prior['table_name']}的 {len(readings)} 条线：" + "，".join(clauses),
        "xlabels": [got["label"] for _, got in readings],
        "values": [round((got["value"] - got["threshold"]) / abs(got["threshold"]) * 100, 1)
                   for _, got in readings],
        "legend": "距上季所盯那条线",
        "positive_label": "高于那条线",
        "negative_label": "低于那条线",
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "距该线 %",
        "zero_line": True,
        "note": (
            prior["section_note"]
            + "所以图上的正负只表示本季读数落在那条线的哪一侧，不表示好坏。"
            + "".join(f"{got['subject']} {got['value_text']}，对照{got['threshold_text']}。" for _, got in readings)
            + "".join(f"第 {row['row']} 行「{row['text']}」{row['why']}，本季{row_reading(staging, period, row)}。"
                      for row in no_line)
        ),
        "src_extra": (f"线取自上季（{prior['set_in']}）本地分析{prior['section']}，不是公司指引；"
                      f"读数取自本季业绩新闻稿的月度活动表与客户资产表。"),
    }
    rows = []
    for row in prior["rows"]:
        group = [(line, got) for line, got in readings if line["row"] == row["row"]]
        if not group:
            rows.append([str(row["row"]), row["text"], "—", row_reading(staging, period, row), "—",
                         f"未量化：{row['why']}"])
            continue
        for line, got in group:
            rows.append([str(row["row"]), row["text"], f"{TRIGGER_WORDS[line['op']]}{got['threshold_text']}",
                         got["value_text"],
                         f"{(got['value'] - got['threshold']) / abs(got['threshold']) * 100:+.1f}%",
                         ("" if happened[line["id"]] else "没有") + line["event"]])
    table = {
        "title": f"上季{prior['table_name']}逐行（{prior['set_in']} 本地分析{prior['section']}）：原文、本季读数、所盯的事发生了吗",
        "headers": ["行", "原文", "所盯的事（本页的线）", "本季读数", "距该线 D", "结果"],
        "rows": rows,
    }
    return [chart], table


def split_by_date(staging: dict, lines: list[dict], due_at: str, block: str) -> tuple[list, list]:
    """(lines due at `due_at`, lines due later); a line whose date has passed stops the build."""
    due, later = [], []
    for line in lines:
        settles = line.get("settles", due_at)
        if period_order(settles) < period_order(due_at):
            raise ValueError(f"series block `{block}`: line {line['id']!r} settled in {settles}, which has "
                             f"passed: the roll should have dropped it")
        (due if period_order(settles) == period_order(due_at) else later).append(line)
    return due, later


def lines_note(staging: dict, block: dict, readings: list, later: list, era: str) -> str:
    """The overview's note: which lines are past their line, the green lines, and what is not on the chart."""
    risk = [(line, got) for line, got in readings if line["tier"] in RISK]
    green = [(line, got) for line, got in readings if line["tier"] == "green"]
    hit = [(line, got) for line, got in risk if line_hit(staging, line, got)]
    reached = [(line, got) for line, got in green if line_hit(staging, line, got)]
    unplotted = {}
    for line, _ in readings:
        spec = READS[line["reads"]]
        if spec.get("chart", True) is False and spec.get("why"):
            unplotted.setdefault(spec["name"], [spec["why"], 0])[1] += 1
    monthly = [line for line, _ in readings if READS[line["reads"]].get("monthly")]
    no_line = [row for row in block["rows"] if not any(line["row"] == row["row"] for line in block["lines"])]
    now = "当前" if era == "next" else "本季"
    parts = [("正值表示当前读数仍在该线安全的一侧，负值表示已经越过。" if era == "next"
              else "正值 = 本季读数落在上季那条警示线的安全一侧，负值 = 越线。")]
    if hit:
        parts.append(cn_join("当前已越线的是" if era == "next" else "越线的是",
                             "、".join(f"{got['label']}（{now} {got['text']}）" for _, got in hit)) + "。")
    if green:
        parts.append(f"另有{cn_count(len(green))}条正面信号线（"
                     + "；".join(f"{got['label']}，{now} {got['text']}" for _, got in green)
                     + f"），{now}{cn_count(len(reached))}条{'已达到' if era == 'next' else '达到'}。")
    for line, got in risk:
        if line["threshold"] == 0:
            parts.append(cn_join(got["label"], f"那条的阈值是 0，没有百分比余量，不进这张图（{now} {got['text']}）。"))
    for line in later:
        parts.append(f"「{cn_join(READS[line['reads']]['name'], line_text(line))}」要到 "
                     f"{short_period(line['settles'])} 才结算。")
    if monthly:
        names = "、".join(dict.fromkeys(READS[line["reads"]]["name"] for line in monthly))
        parts.append(f"单月口径的{cn_count(len(monthly))}条（{names}）按季内最弱的一个月读，{MONTHLY_WHY}。")
    for name, (why, count) in unplotted.items():
        parts.append(cn_join(name, f"（{cn_count(count)}条线）只进总览：{why}。"))
    if no_line:
        parts.append("、".join(f"第 {row['row']} 行（{row.get('subject', row.get('text'))}）" for row in no_line)
                     + ("没有可结算的申报读数，原因见核对抽屉。" if era == "next" else "本季读不到，原因见核对抽屉。"))
    return "".join(parts)


def rule_settlement(staging: dict, prior: dict, lines: list[dict]) -> tuple[list, dict]:
    """The previous analysis's warning and green lines, settled on this quarter's figures."""
    page = display_period(staging["periods"][-1])
    due, later = split_by_date(staging, lines, page, "prior_kpi_settlement")
    readings = [(line, read_line(staging, line)) for line in due]
    for line, _ in readings:
        line_direction(line)
    risk = [(line, got) for line, got in readings if line["tier"] in RISK]
    broken = [(line, got) for line, got in risk if line_hit(staging, line, got)]
    entries = [{"metric": got["label"], "direction": line_direction(line), "threshold": line["threshold"],
                "actual": got["value"]} for line, got in risk if line["threshold"] != 0]
    charts = [headroom_exhibit(
        f"上季 {len(risk)} 条警示线：{len(risk) - len(broken)} 条守住、{len(broken)} 条越线",
        entries, "actual", lines_note(staging, prior, readings, later, "prior"),
        f"线逐字取自上季（{prior['set_in']}）本地分析{prior['section']}，不是公司指引；读数取自本季申报与新闻稿。",
    )]
    charts += reading_charts(staging, readings, "prior", prior["set_in"], later)
    table = lines_table(staging, prior, readings + [(line, read_line(staging, line)) for line in later], "prior",
                        frozenset(line["id"] for line in later))
    return charts, table


def next_exhibits(staging: dict, kpi: dict) -> tuple[list, dict, str]:
    """Section three: this analysis's own lines, and where each reading stands now."""
    due, later = split_by_date(staging, kpi["lines"], kpi["for_period"], "next_kpi")
    readings = [(line, read_line(staging, line)) for line in due]
    for line, _ in readings:
        line_direction(line)
    risk = [(line, got) for line, got in readings if line["tier"] in RISK]
    beyond = [(line, got) for line, got in risk if line_hit(staging, line, got)]
    entries = [{"metric": got["label"], "direction": line_direction(line), "threshold": line["threshold"],
                "current": got["value"]} for line, got in risk if line["threshold"] != 0]
    no_line = [row for row in kpi["rows"] if not any(line["row"] == row["row"] for line in kpi["lines"])]
    overview = headroom_exhibit(
        f"下季 {len(risk)} 条警示线：当前 {len(risk) - len(beyond)} 条在安全侧、{len(beyond)} 条已越线",
        entries, "current", lines_note(staging, kpi, readings, later, "next"),
        f"线逐字取自本季（{kpi['set_in']}）本地分析{kpi['section']}，不是公司指引；当前值取自本季申报与新闻稿。",
    )
    charts = [overview] + reading_charts(staging, readings, "next", kpi["set_in"], later)
    table = lines_table(staging, kpi, readings + [(line, read_line(staging, line)) for line in later], "next",
                        frozenset(line["id"] for line in later))
    green = sum(1 for line in due if line["tier"] == "green")
    description = (
        f"本季分析{kpi['section']}的{cn_count(len(kpi['rows']))}行拆成{cn_count(len(kpi['lines']))}条线："
        f"下季结算的{cn_count(len(risk))}条警示线与{cn_count(green)}条正面信号线"
        + (f"，另有{cn_count(len(later))}条要到 {'、'.join(dict.fromkeys(short_period(l['settles']) for l in later))} "
           "才结算" if later else "")
        + f"；{cn_count(len(no_line))}行没有可结算的申报读数，原因写在核对抽屉。"
        "单月口径的线读本季新闻稿印的月度活动表，只进总览与核对表，不画月度走势。"
    )
    return charts, table, description


def highlight_exhibits(staging: dict, fin: dict, periods: list, ops: dict,
                       blocks: dict) -> dict:
    """The income-statement charts, by name.

    Section two takes the ones that state this quarter's reading; the two
    long-run structure charts (`mix`, `share`) go to section four, where a
    ten-year range is the point rather than a quarter's conclusion.
    """
    labels = [compact(p) for p in periods]
    revenue = fin["revenue_usd_m"]
    nii = fin["net_interest_revenue_usd_m"]
    amaf = fin["amaf_usd_m"]
    trading = fin["trading_usd_m"]
    bda = fin["bda_usd_m"]
    other = fin["other_usd_m"]
    expenses = fin["total_expenses_usd_m"]
    pretax = fin["pretax_usd_m"]
    growth_of = {name: pct_change(fin[key][-1], fin[key][-5]) for name, key, _ in FIVE_LINES}
    short = {name: word for name, _, word in FIVE_LINES}
    by_growth = sorted(growth_of, key=growth_of.get, reverse=True)
    level_now = {name: fin[key][-1] for name, key, _ in FIVE_LINES}
    level_before = {name: fin[key][-2] for name, key, _ in FIVE_LINES}
    largest = max(level_now, key=level_now.get)

    # The five revenue lines only coexist from 2020Q4, when bank deposit account
    # fees arrived with the TD Ameritrade acquisition (closed 2020-10-06).
    mix_periods, mix_nii, mix_amaf, mix_trading, mix_bda, mix_other = tail(
        periods, nii, amaf, trading, bda, other)
    # The first version of this title said the fastest-growing line was
    # trading; on the release's own table bank deposit account fees (+35%) and
    # "other" (+32%) both grew faster than trading (+28%). The ranking is now
    # read off the series.
    still = "仍是" if max(level_before, key=level_before.get) == largest else "是"
    fastest = by_growth[0]
    mix_title = (f"五条收入线（{compact(mix_periods[0])}–{compact(mix_periods[-1])}）："
                 f"{largest}{still}最大一条，"
                 + (f"但本季同比增速最快的是{short[fastest]}" if fastest != largest
                    else "也是本季同比增速最快的一条"))
    mix = {
        "kind": "lines_endlabels",
        "title": mix_title,
        "xlabels": axis([compact(p) for p in mix_periods]),
        "series": [
            {"name": "净利息收入", "values": rounded(mix_nii), "color": "NAVY"},
            {"name": "资产管理与行政管理费", "values": rounded(mix_amaf), "color": "BLUE"},
            {"name": "交易收入", "values": rounded(mix_trading), "color": "TEAL"},
            {"name": "银行存款账户费", "values": rounded(mix_bda), "color": "ORANGE"},
            {"name": "其他", "values": rounded(mix_other), "color": "GREY"},
        ],
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$M",
        "note": (
            f"窗口从 {mix_periods[0]} 起，因为银行存款账户费这条线是随 TD Ameritrade 收购"
            "（2020-10-06 完成）才出现的，再往前公司的利润表上没有它，补零会造出一条"
            "并不存在的历史。五条线相加恒等于净收入，本页的对账测试就钉这条恒等式。"
        ),
        "src_extra": "各期 10-Q / 10-K 合并利润表；第四季度为全年数减去同年三个季度。",
    }

    latest_mix = [(name, fin[key]) for name, key, _ in FIVE_LINES]
    positive = sum(1 for name in growth_of if growth_of[name] > 0)
    trading_record = is_top(trading)
    rpt = ops["revenue_per_trade_usd"]
    dats_all = ops["dats_thousands"]
    volume_note = ""
    if pct_change(rpt[-1], rpt[-5]) < 0 < pct_change(dats_all[-1], dats_all[-5]):
        volume_note = (
            "值得注意的是交易这条是<b>量</b>驱动而不是价驱动："
            + ("交易收入创纪录的同时" if trading_record
               else f"交易收入同比 {signed(growth_of['交易收入'], 0)} 的同时")
            + "每笔交易收入同比是负的，这是下一张图要解决的矛盾。"
        )
    growth = {
        "kind": "grouped_bars",
        "title": (f"本季五条收入线的同比增速：{short[by_growth[0]]} "
                  f"{signed(growth_of[by_growth[0]], 0)}、{short[by_growth[1]]} "
                  f"{signed(growth_of[by_growth[1]], 0)} 领先"),
        "xlabels": [name for name, _ in latest_mix] + ["净收入合计"],
        "groups": [{
            "name": "同比增速",
            "color": "BLUE",
            "values": rounded([pct_change(s[-1], s[-5]) for _, s in latest_mix]
                              + [pct_change(revenue[-1], revenue[-5])]),
        }],
        "bar_labels": True,
        "fmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "% YoY",
        "zero_line": True,
        "note": (
            ("五条线全部同比为正是这一季最直白的事实。" if positive == 5
             else f"五条线里{cn_count(positive)}条同比为正。")
            + volume_note
        ),
        "src_extra": f"同比基数为 {periods[-5]} 的同一条线。",
    }

    nii_share = [round(n / r * 100, 4) for n, r in zip(nii, revenue)]
    fees = [a + t + (b or 0) + o for a, t, b, o in zip(amaf, trading, bda, other)]
    by_year = {}
    for period, value in zip(periods, fees):
        by_year.setdefault(period[:4], []).append(value)
    annual = [sum(v) for _, v in sorted(by_year.items()) if len(v) == 4]
    fell = sum(1 for a, b in zip(annual, annual[1:]) if b < a)
    # The first version said fee revenue rose "almost monotonically" over the
    # window, which is what licensed "the swing is all the rate leg". Summed by
    # full year it fell in four of nine year-on-year steps, so the note now
    # says that instead.
    if fell:
        fee_words = (f"同一段时间里公司的费类收入并不单调：按完整年度算，"
                     f"{cn_count(len(annual) - 1)}次同比里有{cn_count(fell)}次下降。")
    else:
        fee_words = "同一段时间里公司的费类收入按完整年度逐年上升 —— 摆动来自利率腿。"
    share = {
        "kind": "lines",
        "title": (
            f"净利息收入占净收入的比重（{compact(periods[0])}–{compact(periods[-1])}）："
            f"{min(nii_share):.1f}% 到 {max(nii_share):.1f}% 之间来回摆"
        ),
        "xlabels": axis(labels),
        "series": [{"name": "净利息收入占比", "values": nii_share, "color": "NAVY"}],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "%",
        "note": (
            "这是本页最能说明「Schwab 是什么公司」的一条线：它既不是纯券商也不是纯银行，"
            f"而是一台利率敞口随周期开合的机器。{cn_count(len(periods) // 4)}年里"
            "这个比重的高点与低点相差超过 "
            f"{int(max(nii_share) - min(nii_share))} 个百分点；"
            + fee_words
        ),
        "src_extra": "分子分母同为公司披露的合并利润表数字，比值为自算（D）。",
    }

    rev_yoy, exp_yoy = yoy(revenue), yoy(expenses)
    lev_periods, lev_rev, lev_exp = tail(periods, rev_yoy, exp_yoy)
    window = 20
    lev_periods, lev_rev, lev_exp = lev_periods[-window:], lev_rev[-window:], lev_exp[-window:]
    compensation = fin["compensation_usd_m"]
    comp_added = compensation[-1] - compensation[-5]
    rest_added = (expenses[-1] - compensation[-1]) - (expenses[-5] - compensation[-5])
    comp_step = compensation[-1] - compensation[-2]
    rest_step = (expenses[-1] - compensation[-1]) - (expenses[-2] - compensation[-2])
    adjusted = fin["adjusted_total_expenses_usd_m"]
    # The first version said the biggest riser inside expenses was variable,
    # volume-linked cost "rather than people"; the release's own table has
    # compensation and benefits up US$254M of the US$355M. The second version
    # then called compensation "not variable cost" and concluded costs would not
    # fall with volume -- the analysis says part of compensation is incentive pay
    # tied to revenue, and that the quarter's sequential increase sat entirely
    # outside compensation. The note now states the two splits and leaves the
    # judgement to the threshold the analysis actually set.
    if comp_added > rest_added > 0:
        cost_words = (f"费用同比 {signed(exp_yoy[-1], 0)} 里涨得最多的是薪酬福利"
                      f"（+US${comp_added:,.0f}M，占费用增量的{tenths_word(comp_added / (comp_added + rest_added))}）；")
    else:
        cost_words = (f"费用同比 {signed(exp_yoy[-1], 0)}：薪酬福利 +US${comp_added:,.0f}M、"
                      f"其余各项合计 +US${rest_added:,.0f}M；")
    cost_words += (f"环比看，薪酬福利 {'+' if comp_step >= 0 else '−'}US${abs(comp_step):,.0f}M、"
                   f"薪酬以外的各项合计 {'+' if rest_step >= 0 else '−'}US${abs(rest_step):,.0f}M。")
    if adjusted[-1] is not None and adjusted[-5] is not None:
        cost_words += (f"按公司的调整后口径（剔除收购无形资产摊销与整合费用）费用同比 "
                       f"{signed(pct_change(adjusted[-1], adjusted[-5]))}。")
    expense_line = next((line for line in (blocks["next"] or {}).get("lines", [])
                         if line["reads"] == "adj_expense_yoy"), None)
    leverage = {
        "kind": "grouped_bars",
        "title": (
            f"经营杠杆：本季收入同比 {rev_yoy[-1]:.1f}%、费用同比 {exp_yoy[-1]:.1f}%，"
            f"差 {rev_yoy[-1] - exp_yoy[-1]:.0f} 个百分点"
        ),
        "xlabels": [compact(p) for p in lev_periods],
        "xrot": 90,
        "groups": [
            {"name": "净收入同比", "color": "NAVY", "values": rounded(lev_rev)},
            {"name": "费用同比", "color": "ORANGE", "values": rounded(lev_exp)},
        ],
        "bar_labels": False,
        "fmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "% YoY",
        "zero_line": True,
        "note": (
            "两根柱子的差就是经营杠杆。要注意的是它在这一季的成色："
            + cost_words
            + (f"本季分析担心的是量回落而费用不跟着回落，第三节的「调整后费用同比{line_text(expense_line)}」"
               "警示线盯的就是这件事。" if expense_line else "")
        ),
        "src_extra": "均为公司披露的合并利润表数字；同比为自算（D）。",
    }

    # The company prints the margin every quarter, so the chart draws the printed
    # figure; the ratio of the two statement lines is the check on it.
    margin = [p / r * 100 for p, r in zip(pretax, revenue)]
    disclosed = ops["pretax_margin_pct_disclosed"]
    printed_margin = [disclosed[ops["periods"].index(p)] for p in periods]
    agree = sum(1 for m, d in zip(margin, printed_margin) if d is not None and round(m, 1) == d)
    compared = sum(1 for d in printed_margin if d is not None)
    top = high_words(printed_margin, "这段窗口")
    margin_chart = {
        "kind": "lines",
        "title": (
            f"税前利润率（{compact(periods[0])}–{compact(periods[-1])}）：本季 {printed_margin[-1]:.1f}%"
            + (f"，{top}" if top else "")
        ),
        "xlabels": axis(labels),
        "series": [{"name": "税前利润率", "values": printed_margin, "color": "NAVY"}],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "%",
        "note": (
            "画的是新闻稿逐季印的「Pre-tax profit margin」。用利润表的税前利润 ÷ 净收入自算，"
            + (f"{cn_count(compared)}个季度逐季四舍五入后都等于印出值"
               if agree == compared else f"{cn_count(compared)}个季度里有{cn_count(compared - agree)}季与印出值差一位舍入以上")
            + f"（本季 {margin[-1]:.2f}%）。这条对账同时验证了本页各年第四季度的推导 —— 那几个季度公司不出 10-Q，"
            "利润率却印在新闻稿里，两边对得上才说明「全年减九个月」这一步没错。"
        ),
        "src_extra": "利润率为各季新闻稿印出值；分子分母为公司披露的利润表数字，自算比值逐季核对。",
    }

    op_periods = ops["periods"]
    vp_periods, dats, rpt_tail = tail(op_periods, ops["dats_thousands"], ops["revenue_per_trade_usd"])
    dats_words = f"日均交易量 {dats[-1] / 1000:.2f}M" + (" 创纪录" if is_top(dats) else "")
    rpt_words = (f"每笔交易收入 ${rpt_tail[-1]:.2f}"
                 + (" 是窗口内最低" if is_bottom(rpt_tail) else ""))
    if trading_record:
        record_words = "交易收入仍然创了纪录。"
    else:
        peak = max(trading)
        record_words = (f"交易收入 US${trading[-1]:,.0f}M，离 {periods[trading.index(peak)]} 的纪录 "
                        f"US${peak:,.0f}M 只差 US${peak - trading[-1]:,.0f}M。")
    verdicts = blocks["verdicts"]
    volume_price = {
        "kind": "bar_line_dual",
        "title": (
            f"量与价反向（{compact(vp_periods[0])}–{compact(vp_periods[-1])}）："
            f"{dats_words}，{rpt_words}"
        ),
        "xlabels": axis([compact(p) for p in vp_periods]),
        "bar": {"name": "日均交易量 DATs（千笔）", "values": rounded(dats), "color": "BLUE"},
        "line": {"name": "每笔交易收入 RPT", "values": rounded(rpt_tail), "color": "ORANGE",
                 "yfmt": "usd2"},
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "千笔/日",
        "ylab2": "US$/笔",
        "note": (
            "这是 SCHW 收入函数里最容易读错的一处。把 RPT 当独立变量看，会得出"
            "「定价在恶化」的结论；但把两条放在一起看，量的斜率明显盖过价 —— "
            f"本季 DATs 同比 {pct_change(dats[-1], dats[-5]):+.0f}%、RPT 同比 "
            f"{pct_change(rpt_tail[-1], rpt_tail[-5]):+.0f}%，"
            + record_words
            + (verdicts.get("rpt_note", "") if verdicts else "")
        ),
        "src_extra": "两条都取自各季业绩新闻稿的 Financial and Operating Highlights 表。",
    }

    return {"mix": mix, "growth": growth, "share": share, "leverage": leverage,
            "margin": margin_chart, "volume_price": volume_price}


def routine_exhibits(staging: dict, fin: dict, periods: list, ops: dict,
                     blocks: dict) -> dict:
    """The balance-sheet and client series, by name.

    The lending and net-new-asset charts each state this quarter's reading of a
    conclusion the quarter's analysis leads with (lending carries the margin
    expansion; Advisor Services carries the flows), so section two takes them;
    client assets and the share count stay in section four as long-run series.
    """
    op_periods = ops["periods"]
    labels = [compact(p) for p in periods]
    disclosures = blocks["disclosures"]
    verdicts = blocks["verdicts"]

    ca_periods, total_ca, is_ca, as_ca = tail(
        op_periods, ops["client_assets_usd_bn"],
        ops["client_assets_investor_services_usd_bn"],
        ops["client_assets_advisor_services_usd_bn"])
    added = total_ca[-1] - total_ca[-2]
    market = ops["net_market_gains_usd_bn"][-1]
    if added > 0 and market > added / 2:
        earned = (
            "这条线增长的大部分不是公司挣来的：本季客户总资产环比增加约 "
            f"US${added:,.0f}B，其中净市场损益一项就是 US${market:,.0f}B。"
        )
    else:
        earned = (f"本季客户总资产环比变动约 {money_bn(added)}，其中净市场损益 "
                  f"{money_bn(market)}。")
    assets = {
        "kind": "lines_endlabels",
        "title": (
            f"客户总资产（{compact(ca_periods[0])}–{compact(ca_periods[-1])}）："
            f"US${total_ca[-1] / 1000:.2f}T，同比 {pct_change(total_ca[-1], total_ca[-5]):+.0f}%"
        ),
        "xlabels": axis([compact(p) for p in ca_periods]),
        "series": [
            {"name": "客户总资产", "values": rounded(total_ca), "color": "NAVY"},
            {"name": "Investor Services", "values": rounded(is_ca), "color": "BLUE"},
            {"name": "Advisor Services", "values": rounded(as_ca), "color": "TEAL"},
        ],
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$B",
        "note": (
            earned
            + "把资产规模当经营成绩读是这条线最容易犯的错，第二节的净新增资产图才是公司自己带进来的量。"
            "<b>两条业务线在 2023Q3/2023Q4 之间换过一次口径</b>：公司 2024 年第四季把 "
            "Retirement Business Services 从 Advisor Services 划到 Investor Services，"
            "只把重述发布到 2023-12-31 为止，更早的季度没有重述值。"
            "总额那条线不受影响，划转只在两条业务线之间搬。"
        ),
        "src_extra": ("各季业绩新闻稿的客户资产表；两条业务线相加恒等于总额 —— "
                      "而这条恒等式对上面那次划转按构造无分辨力。"),
    }

    # The window starts after the TD Ameritrade quarter: that quarter's net new
    # assets include the TD Ameritrade client base arriving at once, which is an
    # acquisition, not asset gathering, and would flatten every other bar.
    close_ops = op_periods.index(TDA_CLOSE)
    nna_start = close_ops + 1
    nna_periods = op_periods[nna_start:]
    nna_is = ops["net_new_assets_investor_services_usd_bn"][nna_start:]
    nna_as = ops["net_new_assets_advisor_services_usd_bn"][nna_start:]
    nna_total = ops["net_new_assets_usd_bn"][nna_start:]
    arrived = ops["net_new_assets_usd_bn"][close_ops]
    channel_words = ""
    if verdicts and verdicts.get("channel_note") and nna_is[-1] < nna_as[-1]:
        channel_words = verdicts["channel_note"].format(
            is_qoq=f"{pct_change(nna_is[-1], nna_is[-2]):+.0f}%")
    flows = {
        "kind": "grouped_bars",
        "title": (
            f"季度净新增资产按渠道（{compact(nna_periods[0])}–{compact(nna_periods[-1])}）："
            f"本季 US${nna_total[-1]:,.1f}B，Advisor Services 扛了 "
            f"{nna_as[-1] / nna_total[-1] * 100:.0f}%"
        ),
        "xlabels": [compact(p) for p in nna_periods],
        "xrot": 90,
        "groups": [
            {"name": "Investor Services", "color": "NAVY", "values": rounded(nna_is)},
            {"name": "Advisor Services", "color": "TEAL", "values": rounded(nna_as)},
        ],
        "bar_labels": False,
        "fmt": "f1",
        "label_fmt": "f1",
        "ylab": "US$B",
        "note": (
            f"窗口从 {nna_periods[0]} 起：{TDA_CLOSE} 的净新增资产里含 TD Ameritrade 客户群一次性并入的 "
            f"US${arrived:,.1f}B，那是收购不是获客，画进来会把其余每一根柱子压平。"
            + channel_words
            + "<b>两条渠道线在 2023Q3/2023Q4 之间换过一次口径。</b>"
            "公司 2024 年第四季把 Retirement Business Services 从 Advisor Services "
            "划到 Investor Services，并追溯重述 —— 但只重述到 2023-12-31 为止，"
            "那是 4Q24 与 1Q25 两份发布回溯到的最远处。本页 2023Q4 起用重述后的口径，"
            "更早的季度只有重述前的口径，公司没有发布过更早的重述值。"
            "<b>合计不受影响</b>：这次划转只在两条渠道之间搬余额，两条相加逐季恒等于"
            "公司披露的合计 —— 这也正是本页把重述前后接在一起画了很久而没有任何"
            "求和断言变红的原因。"
        ),
        "src_extra": ("各季业绩新闻稿；两条渠道相加恒等于公司披露的净新增资产合计 —— "
                      "而这条恒等式对上面那次口径划转按构造无分辨力，因为划转只在两条之间搬。"),
    }

    shares = fin["diluted_shares_m"]
    # The acquisition step is the quarter-on-quarter jump in the quarter TD
    # Ameritrade closed, not the spread of the series -- those differ, and only
    # the first one is the thing the sentence claims to measure.
    close_index = periods.index(TDA_CLOSE)
    issued = shares[close_index] - shares[close_index - 1]
    bought_back = max(shares) - shares[-1]
    after = shares[close_index:]
    peak_at = close_index + after.index(max(after))
    # It did not fall every quarter after the deal, as the first version said:
    # it kept rising into 2022 before the buybacks turned it.
    if all(b <= a for a, b in zip(after, after[1:])):
        path = "此后逐季回落。"
    else:
        path = (f"此后先升到 {periods[peak_at]} 的 {shares[peak_at]:,.0f}M，"
                f"再回落到本季的 {shares[-1]:,.0f}M。")
    buyback_words = ""
    if disclosures:
        now = disclosures["buyback_usd_m"]
        before = disclosures.get("prior_quarter_buyback_usd_m")
        pace = ""
        if before:
            pace = ("，节奏较上季明显收窄" if now <= before * 0.6
                    else "，节奏较上季收窄" if now < before else "，节奏较上季加快")
        buyback_words = (
            f"本季回购 {disclosures['buyback_shares_m']:.1f}M 股、约 US${now / 1000:.1f}B"
            + pace + "（第二节的回购图画的是逐季的回购支出）。"
        )
    share_chart = {
        "kind": "lines",
        "title": (
            f"摊薄股数（{compact(periods[0])}–{compact(periods[-1])}）："
            f"收购当季一次多出 {issued:.0f}M 股，自此后的高点回购了 {bought_back:.0f}M 股"
        ),
        "xlabels": axis(labels),
        "series": [{"name": "摊薄股数", "values": rounded(shares, 1), "color": "NAVY"}],
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "end_label": True,
        "ylab": "百万股",
        "note": (
            f"这条线是本页唯一一条把「收购的代价」画出来的序列：{TDA_CLOSE} 一次性从约 "
            f"{shares[close_index - 1]:,.0f}M 跳到 {shares[close_index]:,.0f}M，"
            + path
            + buyback_words
        ),
        "src_extra": "各期 10-Q / 10-K 的加权平均摊薄股数；第四季度由全年与九个月推出（D）。",
    }

    pal_block = staging["pledged_asset_lines"]
    pal_by_quarter = dict(zip(pal_block["quarters"], pal_block["usd_bn"]))
    pal_series = [pal_by_quarter.get(p) for p in op_periods]
    lb_periods, margin_loans, bank_loans, pal = tail(
        op_periods, ops["margin_loans_usd_bn"], ops["bank_loans_usd_bn"], pal_series)
    all_high = is_top(margin_loans) and is_top(bank_loans) and is_top(pal)
    pal_share = pal[-1] / bank_loans[-1] * 100
    pal_share_before = pal[-5] / bank_loans[-5] * 100
    # The release's footnote splits the long/short strategy into margin loans
    # (inside the margin balance) and short credits (inside client cash). The
    # first version put the short credits inside the margin balance.
    long_short = ops["long_short_margin_loans_usd_bn"][-1]
    lending = {
        "kind": "lines_endlabels",
        "title": (
            f"放贷（{compact(lb_periods[0])}–{compact(lb_periods[-1])}）：银行贷款 US${bank_loans[-1]:,.1f}B、"
            f"同比 {signed(pct_change(bank_loans[-1], bank_loans[-5]), 0)}，其中 PAL US${pal[-1]:,.1f}B、"
            f"同比 {signed(pct_change(pal[-1], pal[-5]), 0)}；保证金贷款"
            + ("（含 long/short 策略部分）" if long_short is not None else " ")
            + f"US${margin_loans[-1]:,.1f}B" + ("，三条同创新高" if all_high else "")
        ),
        "xlabels": axis([compact(p) for p in lb_periods]),
        "series": [
            {"name": "保证金贷款余额", "values": rounded(margin_loans), "color": "ORANGE"},
            {"name": "银行贷款余额", "values": rounded(bank_loans), "color": "NAVY"},
            {"name": "其中 PAL 余额", "values": rounded(pal), "color": "TEAL"},
        ],
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$B",
        "note": (
            "三条线一起看才对：银行贷款是公司主动配置资本的结果"
            + (f"，{disclosures['nim_attribution']}" if disclosures and disclosures.get("nim_attribution") else "")
            + f"，其中以客户证券作抵押的 PAL 占银行贷款净额的 {pal_share:.0f}%（一年前 {pal_share_before:.0f}%）"
            "；保证金贷款则是客户风险偏好的读数，它和交易量、以及市场回撤时的去杠杆压力绑在一起。"
            + (f"本季保证金贷款余额 US${margin_loans[-1]:,.1f}B 里含 long/short 策略相关的保证金贷款，"
               f"公司在脚注里把{month_word(quarter_end_month(periods[-1]))}末这部分单独列为 US${long_short:,.1f}B"
               + (f"（对应的空头贷记 US${disclosures['short_credits_usd_bn']:,.1f}B 计在交易性 sweep 现金里）"
                  if disclosures and disclosures.get("short_credits_usd_bn") is not None else "")
               + " —— 总额不能直接当作客户杠杆读。" if long_short is not None else "")
        ),
        "src_extra": ("保证金与银行贷款取自各季业绩新闻稿（保证金贷款为客户资产表中的抵减项，此处取绝对值）；"
                      "PAL 余额取自各期 10-Q / 10-K 的贷款附注（毛额，拨备为零）。"),
    }

    repurchases = ops["repurchases_usd_bn"]
    tier1 = ops["adjusted_tier1_leverage_pct"]
    none_since = next((i for i in range(len(repurchases) - 1, -1, -1) if repurchases[i] == 0), None)
    capital = {
        "kind": "grouped_bars",
        "title": (f"回购支出（{compact(op_periods[0])}–{compact(op_periods[-1])}）：本季 US${repurchases[-1]:.1f}B，"
                  f"上季 US${repurchases[-2]:.1f}B"
                  + ("，是上季的一半不到" if repurchases[-1] < repurchases[-2] / 2 else "")),
        "xlabels": axis([compact(p) for p in op_periods]),
        "groups": [{"name": "回购支出（现金流量表）", "color": "NAVY", "values": rounded(repurchases, 3)}],
        "bar_labels": False,
        "fmt": "f1",
        "label_fmt": "f1",
        "ylab": "US$B",
        "zero_line": True,
        "note": (
            f"本季调整后 Tier 1 杠杆率 {tier1[-1]:.1f}%，公司自述的长期运营目标区间是 "
            f"{TIER1_TARGET[0]:g}%–{TIER1_TARGET[1]:g}%。"
            + (f"新闻稿要点按成交口径印本季回购 {disclosures['buyback_shares_m']:.1f}M 股、约 US${disclosures['buyback_usd_m'] / 1000:.1f}B"
               + (f"，上季约 US${disclosures['prior_quarter_buyback_usd_m'] / 1000:.1f}B"
                  if disclosures.get("prior_quarter_buyback_usd_m") else "")
               + "，与现金流量表差结算时点。" if disclosures else "")
            + (disclosures["buyback_note"] if disclosures and disclosures.get("buyback_note") else "")
            + (f"窗口里上一次回购为零是 {op_periods[none_since]}。" if none_since is not None else "")
        ),
        "src_extra": "各期 10-Q / 10-K 现金流量表「Repurchases of common stock」，按年初至今逐季相减（D）。",
    }

    return {"assets": assets, "flows": flows, "shares": share_chart, "lending": lending, "capital": capital}


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    op = staging["operating"]
    return [f"Revenue ${staging['financials']['revenue_usd_m'][-1] / 1000:.2f}B",
            f"NIM {op['nim_pct'][-1]:.2f}%",
            f"DATs {op['dats_thousands'][-1] / 1000:.1f}M"]


def release_source(staging: dict) -> dict:
    label = f"Schwab {company_period(staging['periods'][-1])} 业绩新闻稿"
    found = next((item for item in staging["sources"] if item["label"].startswith(label)), None)
    if found is None:
        raise ValueError(f"series `sources` has no entry for the {label}: add this "
                         "quarter's release with the roll")
    return found


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    period = display_period(periods[-1])
    fin = staging["financials"]
    ops = staging["operating"]
    guidance = staging["guidance"]

    latest = latest_block(staging, period=period, period_end=staging["period_ends"][-1])
    blocks = {
        "closure": stamped_block(staging, "followup_closure", period),
        "verdicts": stamped_block(staging, "tracked_metric_verdicts", period),
        "prior": stamped_block(staging, "prior_kpi_settlement", period),
        "next": stamped_block(staging, "next_kpi", period),
        "disclosures": stamped_block(staging, "latest_disclosures", period),
    }
    for key, name in (("closure", "followup_closure"), ("prior", "prior_kpi_settlement"), ("next", "next_kpi")):
        if blocks[key] is None:
            raise ValueError(f"series block `{name}` is required for {period}: every quarter's analysis "
                             "settles the one before it and sets the lines for the next")
    for key, name in (("closure", "followup_closure"), ("verdicts", "tracked_metric_verdicts"),
                      ("prior", "prior_kpi_settlement")):
        if blocks[key] and display_period(blocks[key]["set_in"]) == period:
            raise ValueError(f"series block `{name}` settles what {blocks[key]['set_in']} set, "
                             "which is this quarter: it has to be the quarter before")
    if display_period(blocks["next"]["for_period"]) == period:
        raise ValueError("series block `next_kpi` is stamped for this quarter's own lines: "
                         "move it into `prior_kpi_settlement` and write the new analysis's lines")
    scenario = stamped_block(guidance, "scenario", period)
    disclosures = blocks["disclosures"]
    release = release_source(staging)
    when = {"release": latest["release_date"],
            "filing": filing_words(periods[-1], latest["period_end"])}
    story = story_values(staging, blocks, scenario)

    revenue = fin["revenue_usd_m"]
    pretax = fin["pretax_usd_m"]
    nii = fin["net_interest_revenue_usd_m"]
    trading = fin["trading_usd_m"]
    nim = [v for v in ops["nim_pct"] if v is not None]
    rpt = ops["revenue_per_trade_usd"]
    dats = ops["dats_thousands"]

    settled_charts, settled_tables = settled_exhibits(staging, blocks, story, when)
    next_charts, next_table, next_description = next_exhibits(staging, blocks["next"])
    tables = [{"n": index + 1, **table} for index, table in enumerate(settled_tables + [next_table])]
    tables.append({
        "n": len(tables) + 1,
        "title": "五条收入线逐季原值（US$M）与净收入对账",
        "headers": ["期间", "净利息收入", "资产管理与行政管理费", "交易收入",
                    "银行存款账户费", "其他", "五条合计 D", "公司披露净收入", "差额 D"],
        "rows": [
            [compact(p),
             f"{fin['net_interest_revenue_usd_m'][i]:,.0f}",
             f"{fin['amaf_usd_m'][i]:,.0f}",
             f"{fin['trading_usd_m'][i]:,.0f}",
             f"{fin['bda_usd_m'][i]:,.0f}" if fin["bda_usd_m"][i] is not None else "—",
             f"{fin['other_usd_m'][i]:,.0f}",
             f"{(fin['net_interest_revenue_usd_m'][i] + fin['amaf_usd_m'][i] + fin['trading_usd_m'][i] + (fin['bda_usd_m'][i] or 0) + fin['other_usd_m'][i]):,.0f}",
             f"{revenue[i]:,.0f}",
             f"{(fin['net_interest_revenue_usd_m'][i] + fin['amaf_usd_m'][i] + fin['trading_usd_m'][i] + (fin['bda_usd_m'][i] or 0) + fin['other_usd_m'][i]) - revenue[i]:+,.0f}"]
            for i, p in enumerate(periods) if p >= "2024Q1"
        ],
    })
    fourth_table = len(tables) + 1
    tables.append({
        "n": fourth_table,
        "title": "各年第四季度的推导与全年对账（US$M）",
        "headers": ["年度", "公司披露全年净收入", "前三季合计 D", "推得第四季 D",
                    "该季公司披露税前利润率", "本页自算税前利润率 D"],
        "rows": [
            [year,
             f"{annual['revenue_usd_m']:,.0f}",
             f"{sum(revenue[periods.index(f'{year}Q{i}')] for i in (1, 2, 3)):,.0f}",
             f"{revenue[periods.index(f'{year}Q4')]:,.0f}",
             (f"{ops['pretax_margin_pct_disclosed'][ops['periods'].index(f'{year}Q4')]:.1f}%"
              if f"{year}Q4" in ops["periods"] else "—"),
             f"{pretax[periods.index(f'{year}Q4')] / revenue[periods.index(f'{year}Q4')] * 100:.1f}%"]
            for year, annual in sorted(staging["annual_filed_usd_m"].items())
            if f"{year}Q4" in periods
        ],
    })
    tables.append(ai_capex_cycle_table(len(tables) + 1))

    # ── the sentences the page leads with ───────────────────────────────────
    five_up = all(pct_change(fin[key][-1], fin[key][-5]) > 0 for _, key, _ in FIVE_LINES)
    # the printed margin, as the chart draws it
    margin = [ops["pretax_margin_pct_disclosed"][ops["periods"].index(p)] for p in periods]
    years = cn_count(len(periods) // 4)
    margin_top = high_words(margin, f"{years}年窗口")
    tier1 = ops["adjusted_tier1_leverage_pct"]
    midpoint = sum(TIER1_TARGET) / 2
    tier1_words = f"调整后 Tier 1 杠杆率停在 {tier1[-1]:.1f}%"
    if tier1[-1] < midpoint and any(v is not None and v >= midpoint for v in tier1[:-1]):
        tier1_words += " 没有回到目标区间中枢"
    closure = blocks["closure"]
    closure_counts = counted(closure["items"], closure["labels"], "followup_closure")
    settled_words = (f" —— 上季留下的{cn_count(len(closure['items']))}个问题里"
                     + "、".join(f"{cn_count(count)}个{label}"
                                for label, count in zip(closure["labels"], closure_counts) if count))
    headline = (
        f"净收入 US${revenue[-1]:,.0f}M、同比 {signed(pct_change(revenue[-1], revenue[-5]))}，"
        + ("五条收入线全部同比为正，" if five_up else "")
        + f"税前利润率 {margin[-1]:.1f}%"
        + (f" {margin_top}" if margin_top else "")
        + "；"
        + ("但同一季里每笔交易收入跌到 " if rpt[-1] < rpt[-2] else "同一季里每笔交易收入 ")
        + f"${rpt[-1]:.2f}、"
        + tier1_words
        + settled_words
        + "。"
    )

    trading_record = is_top(trading)
    if trading_record:
        brief_one_head = "交易创纪录" if is_top(dats) else "交易收入创纪录"
        trading_words = f"交易收入仍创纪录 US${trading[-1]:,.0f}M。"
    else:
        peak = max(trading)
        brief_one_head = "交易量创纪录" if is_top(dats) else "交易量与单价"
        trading_words = (f"交易收入 US${trading[-1]:,.0f}M，比 {periods[trading.index(peak)]} 的纪录 "
                         f"US${peak:,.0f}M 只少 US${peak - trading[-1]:,.0f}M。")
    brief_one_head += "，单笔收入创新低" if is_bottom(rpt) else ""
    # "Back above 3%" needs an earlier quarter above 3% to go back to, and the
    # window has none (its high before this quarter is 2.90%); whatever the
    # margin was before 2016 is outside what this page read, so the title says
    # only what the series shows.
    nim_floor = int(nim[-1])
    if nim[-1] >= nim_floor > nim[-2]:
        nim_head = (f"NIM 回到 {nim_floor}% 以上" if any(v >= nim_floor for v in nim[:-1])
                    else f"NIM 站上 {nim_floor}%")
    else:
        nim_head = f"NIM {nim[-1]:.2f}%"
    nim_range = next((item for item in (scenario or {}).get("items", [])
                      if item["metric"] == "全年 NIM"), None)
    brief = (
        '<h4>本季三条主线</h4><div class="takeaway-grid">'
        f'<article><span>量盖过价</span><b>{brief_one_head}</b>'
        f'<p>日均交易量 {dats[-1] / 1000:.2f}M、同比 '
        f'{signed(pct_change(dats[-1], dats[-5]), 0)}；'
        f'每笔交易收入 ${rpt[-1]:.2f}、同比 '
        f'{signed(pct_change(rpt[-1], rpt[-5]), 0)}。'
        f'{trading_words}</p></article>'
        f'<article><span>利率腿</span><b>{nim_head}</b>'
        f'<p>{nim[-1]:.2f}%，环比 {nim[-1] - nim[-2]:+.2f}pp；'
        f'净利息收入占净收入 {nii[-1] / revenue[-1] * 100:.1f}%。'
        + (f'公司给的全年区间是 {nim_range["low"]:.2f}%–{nim_range["high"]:.2f}%。'
           if nim_range else "")
        + '</p></article>'
        + ('<article><span>代价</span><b>表观 sweep 现金不能直接读</b>'
           f'<p>季末 US${disclosures["transactional_sweep_cash_usd_bn"]:,.1f}B、环比 '
           f'+US${disclosures["sweep_cash_qoq_change_usd_bn"]:,.1f}B，'
           f'但其中 long/short 策略的空头贷记就有 US${disclosures["short_credits_usd_bn"]:,.1f}B。</p></article>'
           if disclosures else "")
        + '</div>'
    )

    # ── section descriptions and notes ──────────────────────────────────────
    verdicts, kpi, prior = blocks["verdicts"], blocks["next"], blocks["prior"]
    settled_description = (
        f"先结清上季（{closure['set_in']}）本地分析留下的东西：本季分析第〇节闭环的"
        f"{cn_count(len(closure['items']))}个待验证问题"
        + (f"与上季判断记分卡的{cn_count(len(verdicts['items']))}条判断" if verdicts else "")
        + f"，以及上季分析{prior['section']}的{cn_count(len(prior['rows']))}行。"
        + prior["section_note"]
        + "公司自己的指引只在 Business Update 电话会上以情景形式给出，申报文件里没有可逐季核对的数字区间，"
        "所以这一节不画公司指引的兑现记录（原因见口径说明）。"
    )
    why = guidance["why_no_delivery_record"]
    why += (f"，因此本页只发布当季电话会上以数字形式给出的{cn_count(len(scenario['items']))}项。"
            if scenario else "。")
    quarter = periods[-1][-2:]
    monthly_words = ""
    if disclosures and disclosures.get("core_net_new_assets_usd_bn") is not None:
        this_quarter = Monthly(staging, periods[-1])
        months = [this_quarter.value("core_net_new_assets_usd_bn", m) for m in this_quarter.quarter]
        total = disclosures["core_net_new_assets_usd_bn"]
        if round(sum(months), 1) == round(total, 1):
            monthly_words = (
                f"月度表与季度数是同一套数：本季{MONTHS[quarter]}的月度 core 净新增资产 "
                + " + ".join(f"{m:g}" for m in months)
                + f" 恰好等于公司自己公布的季度 core 净新增资产 US${total:,.1f}B。"
            )
    # Which of last quarter's lines the release's monthly table settles: all of
    # them when last quarter kept a monthly tracking table, else its single-month lines.
    if any(line["tier"] == "watch" for line in prior["lines"]):
        settle_words = f"第一节结算上季分析的{prior['table_name']}，用的就是本季新闻稿印的{MONTHS[quarter]}。"
    else:
        prior_monthly = [line for line in prior["lines"] if READS[line["reads"]].get("monthly")]
        settle_words = (f"第一节里上季分析单月口径的{cn_count(len(prior_monthly))}条线，读的也是本季新闻稿印的{MONTHS[quarter]}。"
                        if prior_monthly else "")
    monthly_lines = [line for line in kpi["lines"] if READS[line["reads"]].get("monthly")]
    threshold_count = (f"第三节本季分析的{cn_count(len(kpi['lines']))}条线里，单月口径的{cn_count(len(monthly_lines))}条"
                       f"读本季新闻稿印的{MONTHS[quarter]}，按季内最弱的一个月结算。" if monthly_lines else "")
    last_month = quarter_end_month(periods[-1])
    growth_words = ""
    printed_rate = disclosures.get("core_nna_annualized_growth_pct") if disclosures else None
    if printed_rate is not None:
        rate = annualized_growth(Monthly(staging, periods[-1]), last_month)
        growth_words = (
            "单月 core 净新增资产的年化有机增速按公司自己的算法：当月 core 净新增资产 ÷ 月初客户资产 × 365 ÷ 当月天数；"
            f"本季{month_word(last_month)}这样算得 {rate:.2f}%，公司印 {printed_rate:g}%。"
        )
    identity_quarters = sum(1 for p in periods if p >= "2017Q1")
    provision = staging["financials_notes"]["loan_loss_provision_quarters"]
    if disclosures:
        sweep_note = (
            "交易性 sweep 现金的表观总额包含 long/short 策略相关的空头贷记"
            f"（本季{month_word(quarter_end_month(periods[-1]))} US${disclosures['short_credits_usd_bn']:,.1f}B），"
            "公司在新闻稿脚注里单独披露了这一拆分。"
            + disclosures["sweep_reading"].format(qoq=disclosures["sweep_cash_qoq_change_usd_bn"])
            + "，因此表观总额不能直接当作客户现金流向来读。"
        )
    else:
        sweep_note = None
    not_covered = ""
    if disclosures and disclosures.get("next_update_not_covered"):
        not_covered = (f"、以及 {disclosures['next_update_not_covered']} 的内容"
                       f"（本页数据截至 {disclosures['filings_through']} 的申报）")

    notes = [
        "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
        "Schwab 的会计年度与自然年一致，本页所有季度标注即公司自己的季度，无需换算。",
        why,
        "本页的图都用季度轴，不画月度走势。Schwab 每月中旬发布月度活动报告，其中的月度净新增资产、日均交易量、交易性 sweep 现金、新开经纪账户与保证金余额是两份研究记录里权重最高的跟踪项；"
        "每季业绩新闻稿又把最近十三个月的月度表整张印出来。本页只从新闻稿里的这张表取月度数字、用来结算阈值，所以页面只在财报发布时变化，不在两次财报之间更新。"
        f"{settle_words}{threshold_count}{growth_words}{monthly_words}",
        "各年第四季度公司不出 10-Q，其利润表各行均为 10-K 全年数减去同年三份 10-Q 的三个季度，四条腿都是申报值。这一步有独立的对账：新闻稿逐季印出「Pre-tax profit margin」，把推出来的第四季度税前利润与净收入相除，与公司印的数逐年一致"
        f"（核对抽屉里的第{cn_ordinal(fourth_table)}张表）。",
        "五条收入线（净利息收入、资产管理与行政管理费、交易收入、银行存款账户费、其他）相加恒等于公司披露的净收入合计，"
        f"本页对 2017Q1 起的全部 {identity_quarters} 个季度钉了这条恒等式；净收入减去总费用恒等于税前利润，同样逐季钉住。",
        "银行存款账户费这条线自 2020Q4 起才存在，它随 TD Ameritrade 收购（2020-10-06 完成）进入利润表，因此收入结构图的窗口从 2020Q4 开始而不是补零向前延伸。"
        f"本页的季度序列从 {periods[0]} 起；{provision[0]}–{provision[-1]} 的净收入里还含「贷款损失准备」一项"
        f"（2017 年起移到净收入之外），那{cn_count(len(provision))}季要把它加回五条线才等于净收入。",
        f"第二节的净新增资产图从 {op_periods_after(ops)} 起：{TDA_CLOSE} 那一季的净新增资产含 TD Ameritrade 客户群一次性并入的 "
        f"US${ops['net_new_assets_usd_bn'][ops['periods'].index(TDA_CLOSE)]:,.1f}B，那是收购而不是获客。",
        sweep_note,
        "调整后 Tier 1 杠杆率是公司自己定义的非 GAAP 指标（在 GAAP 口径上计入累计其他综合收益），公司同时披露 GAAP 口径与调节表；"
        f"本页用它是因为公司自述以该口径管理资本并设定 {TIER1_TARGET[0]:g}%–{TIER1_TARGET[1]:g}% 的长期运营目标。",
        "调整后总费用是公司的非 GAAP 口径（剔除收购无形资产摊销、收购整合与重组费用），各季新闻稿的调节表自 "
        f"{first_filled(staging['periods'], fin['adjusted_total_expenses_usd_m'], offset=4)} 那一份起才印（带着一年前的对比栏），"
        "所以第三节的调整后费用同比线从那里开始；更早的新闻稿本页逐份读到 4Q15，十八份里没有一份出现任何非 GAAP 指标。",
        "回购图用现金流量表的回购支出，按年初至今逐季相减；新闻稿要点按成交口径印到十亿，两者差结算时点。"
        "PAL 余额取自各期 10-Q / 10-K 的贷款附注（2015 年的 10-Q 叫 Personal loans secured by securities），同比从 2016Q1 起有读数。",
        f"NIM 取自各季新闻稿的 Net Interest Revenue 表。{nim_basis_words(staging)}",
        "「AI capex 循环」跨页对照表在本站每一页都以完全相同的内容发布，本页也保留。它不是 SCHW 的经营指标 —— 券商不在那条产业链上 —— 保留它是因为它是全站共享的产业参照，且收在核对抽屉里，不占用本页的图表流。",
        "本页只发布公司披露值与可复算的简单派生值；D 标记代表 Derived / 自算，不代表公司定义的非 GAAP 指标。",
        "本页不发布评级、目标价、估值倍数、情景 EPS 与任何券商归属的估计。本季分析师在电话会上问了什么，只在能说明「公司没有披露什么」时作为证据使用，不转述其结论。",
        "本页已知未接入：Crypto 与 Forge 的任何运营或收入数据（公司未披露）、AI 产品的客户端使用数据（公司未披露）、剔除 long/short 之后的底层 sweep 现金逐季序列（公司只在当季脚注给出季末那个月的拆分）"
        f"{not_covered}。",
        "业绩电话会与新闻稿仅链接 SEC 托管版本，公开仓不复制原件或逐字内容。",
    ]

    notes = [note for note in notes if note]

    income = highlight_exhibits(staging, fin, periods, ops, blocks)
    balance = routine_exhibits(staging, fin, periods, ops, blocks)
    # Section two runs in the order the quarter's analysis ranks its findings:
    # revenue growth, then the volume/price split the growth chart's note hands
    # on to (so it has to be the very next chart), margin, the lending that
    # carries the margin expansion, the buybacks it displaced, the flows, and
    # the cost side last.
    highlights = [income["growth"], income["volume_price"], income["margin"],
                  balance["lending"], balance["capital"], balance["flows"], income["leverage"]]
    routine = [balance["assets"], income["mix"], income["share"], balance["shares"]]

    settled_ex = number_exhibits(settled_charts, 2)
    highlight_ex = number_exhibits(highlights, settled_ex[-1]["n"] + 1)
    next_ex = number_exhibits(next_charts, highlight_ex[-1]["n"] + 1)
    routine_ex = number_exhibits(routine, next_ex[-1]["n"] + 1)


    call = f"（{scenario['call']}）" if scenario and scenario.get("call") else " "
    return {
        "schema_version": "quarterly-dashboard/schw-v1",
        "page": {"slug": "schw", "language": "zh-CN"},
        "company": {
            "ticker": "SCHW",
            "name": "Charles Schwab",
            "group": "brokerage_wealth",
            "accounting_standard": "US GAAP",
        },
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · SCHW",
        "title": f"Charles Schwab (SCHW)：{period} 季报仪表盘",
        "subtitle": (
            f"截至 {latest['period_end']} · 发布 {latest['release_date']}{call}· US GAAP · "
            f"{AUDIT_WORDS[latest['audit_status']]} · 自然年季度，无财年错位"
        ),
        "headline": headline,
        "brief": brief,
        "source": (
            f'Source: <a href="{release["url"]}" rel="noopener">Charles Schwab '
            f'{company_period(periods[-1])} 业绩新闻稿（8-K EX-99.1）</a>与{when["filing"]}。'
        ),
        "source_url": release["url"],
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {
                "id": "settled",
                "title": "一、上季跟踪指标兑现了吗",
                "description": settled_description,
                "exhibits": settled_ex,
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": (
                    "本季分析报告的核心结论，一图一条：五条收入线的同比增速、交易业务里量与价反向、"
                    "税前利润率、撑起 NIM 扩张的放贷、让位给放贷的回购、净新增资产由哪条渠道带进来，"
                    "以及收入与费用之间的经营杠杆。"
                    + "".join(f"{item}。" for item in (disclosures or {}).get("undrawn_conclusions", []))
                ),
                "exhibits": highlight_ex,
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": next_description,
                "exhibits": next_ex,
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": (
                    "SCHW 专属的常规序列：客户资产与它有多少是市场给的、五条收入线的长期结构、"
                    "利率腿占净收入的比重随周期开合，以及收购一次发出去又慢慢买回来的股数。"
                ),
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": notes,
        "footer": "SCHW quarterly results · 数据来自 Charles Schwab 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def op_periods_after(ops: dict) -> str:
    """The first quarter after the TD Ameritrade quarter, where the flows chart starts."""
    return ops["periods"][ops["periods"].index(TDA_CLOSE) + 1]


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "schw.js"), payload, "schw")
    shell_dir = ROOT / "schw"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("SCHW", "schw"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(
        f"SCHW page: {charts} charts in {len(payload['sections'])} sections "
        f"+ {len(payload['tables'])} audit tables"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
