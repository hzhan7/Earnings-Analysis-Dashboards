#!/usr/bin/env python3
"""Build the CDNS quarterly-results page.

Same four-part, chart-led shape as the other company pages (上季兑现 → 本季重点
→ 下季跟踪 → 长期常规).  Cadence's fiscal quarters have ended on the calendar
quarter since 2023 and within a few days of it before that, so every label on
this page is already a calendar quarter and needs no restatement.

What makes this page different from its neighbours is the length of the guided
record.  Cadence files a CFO Commentary as EX-99.02 of every quarterly earnings
8-K, and that document states the next quarter's revenue, GAAP and non-GAAP
operating margin and GAAP and non-GAAP EPS.  The record reaches back to 2016Q1,
which turns "did the quarter clear the company's own bar" from an anecdote into a
distribution -- and every sentence that describes the distribution ("never once
below the floor", "the only two misses were against a point guidance") is
recounted from the record on every build, so it stops being printed the quarter
it stops being true.

Rolling a quarter edits `series/cdns.json` and nothing else.  The arrays get a
cell; the blocks that describe one quarter -- the follow-up closure, the prior
and next thresholds, the guidance, the market expectation, the half-year balance
sheet and cash bridge, and `quarter_story` (the page's reading of the quarter:
call quotes, attributions, the headline's verdict) -- carry the quarter they were
written for and are read through `board.stamped_block`, so last quarter's story
cannot be published under this quarter's label.  A story sentence names the
numbers it uses as placeholders (`board.fill_story`) and lists the facts it
rests on under `requires`; the builder recomputes each fact and refuses to build
when the data no longer says what the sentence says.

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
    cn_ordinal,
    delivery_band,
    display_period,
    fill_story,
    headroom,
    headroom_exhibit,
    latest_block,
    midpoint_deviation,
    minus_sign,
    number_exhibits,
    stamped_block,
    unit_text,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "cdns.json"
DATA_DIR = ROOT / "data"

WINDOW = 8
# Forty-odd quarterly labels at ninety degrees is already a dense axis; one
# tick per year is the only way the long routine charts stay navigable.
LONG_STEP = 4
# The guidance bands are drawn on the most recent quarters only: a ±$5M band on
# a US$450M quarter and the same band on a US$1,600M one are the same proportion
# and a very different number of pixels. The deviation charts carry the record.
BAND_QUARTERS = 20
# The era the EPS beat is compared against when the page says the cushion is
# thinning. Fixed history, not a window: it is the five years in which the
# record's beats were widest.
EPS_BEAT_ERA = (2018, 2022)
# ASC 606 replaced ASC 605 for the quarter beginning 2018-01-01 and Cadence did
# not restate the earlier years. Fixed history.
ASC_606_FIRST = "2018Q1"
# A backlog figure is published to US$0.1B, so each one carries ±US$0.05B.
BACKLOG_HALF_STEP_BN = 0.05

AUDIT_WORDS = {"unaudited": "未经审计", "audited": "已审计"}
YTD_WORDS = {1: "一季度", 2: "上半年", 3: "前三季度", 4: "全年"}
REST_WORDS = {1: "后三季", 2: "下半年", 3: "第四季"}


def compact_period(period: str) -> str:
    """``'Q2 2026'`` → ``'Q2'26'``."""
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


def quarter_label(quarter: str) -> str:
    """``'2018Q1'`` → ``'Q1'18'``, matching `compact_period`'s output."""
    year, number = quarter.split("Q")
    return f"Q{number}'{year[-2:]}"


def record_key(period: str) -> str:
    """``'Q2 2026'`` → ``'2026Q2'``, the spelling of the guided record."""
    quarter, year = period.split()
    return f"{year}{quarter}"


def period_of(quarter: str) -> str:
    """``'2026Q2'`` → ``'Q2 2026'``."""
    year, number = quarter.split("Q")
    return f"Q{number} {year}"


def shown(values: list) -> list:
    return values[-WINDOW:]


def yoy(values: list[float | None]) -> list[float | None]:
    out: list[float | None] = [None] * 4
    for index in range(4, len(values)):
        current, base = values[index], values[index - 4]
        out.append(None if current is None or not base else (current / base - 1) * 100)
    return out


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def leading_gap(values: list[float | None]) -> int:
    """Index of the first reported value; ``len(values)`` when there is none."""
    return next((i for i, value in enumerate(values) if value is not None), len(values))


def mid(value) -> float:
    """A guided figure is a range ``[lo, hi]`` or a single approximate number."""
    return sum(value) / 2 if isinstance(value, list) else value


def money_range(value, digits: int = 0) -> str:
    """``[1875, 1975]`` → ``'$1,875–1,975M'``; ``2000`` → ``'约 $2,000M'``."""
    if isinstance(value, list):
        return f"${value[0]:,.{digits}f}–{value[1]:,.{digits}f}M"
    return f"约 ${value:,.{digits}f}M"


def spaced(value) -> str:
    """A guided cash figure inside a sentence: ``' $1,875–1,975M'`` or ``'约 $2,000M'``.

    The leading space sits before a bare dollar range and not before 「约」, so
    「由 $1,875–1,975M 上修到约 $2,000M」 and 「由约 $2,000M 下修到 $1,875–1,975M」 both read.
    """
    return (" " if isinstance(value, list) else "") + money_range(value)


def reads_as(value: float) -> str:
    """How to read a rate good to about ±10pp: ``43.3`` → 「40% 出头」, ``18.7`` → 「近 20%」."""
    tens = int(value // 10) * 10
    return f"{tens}% 出头" if value - tens < 5 else f"近 {tens + 10}%"


def years_words(quarters: int) -> str:
    """``42`` → 「十年半」, ``40`` → 「十年」, ``43`` → 「十年多」, ``8`` → 「两年」."""
    whole, rest = divmod(quarters, 4)
    if rest == 0:
        return f"{cn_count(whole)}年"
    return f"{cn_count(whole)}年半" if rest == 2 else f"{cn_count(whole)}年多"


def times_words(ratio: float) -> str:
    """``3.54`` → 「三倍多」, ``2.14`` → 「两倍」, ``2.8`` → 「近三倍」."""
    whole = int(ratio)
    rest = ratio - whole
    if rest >= 0.75:
        return f"近{cn_count(whole + 1)}倍"
    return f"{cn_count(whole)}倍" + ("多" if rest >= 0.25 else "")


def verb_to(previous: float, current: float, digits: int = 1) -> str:
    """「升到」「降到」「持平于」 by the printed precision, not by the float."""
    before, after = round(previous, digits), round(current, digits)
    return "升到" if after > before else "降到" if after < before else "持平于"


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
    """A story sentence states what the quarter looked like; the data must agree.

    `requires` lists the facts the block's sentences rest on (the backlog grew,
    the quarter landed inside its guided range, China is below its peak...).
    Each is recomputed here, and a block whose premise the data no longer
    supports stops the build instead of printing a sentence that has become
    false -- the page says it only while the data says it.
    """
    if not story:
        return
    for name in story.get("requires", []):
        if name not in facts:
            raise KeyError(f"series block `{block}` requires unknown fact {name!r}")
        if not facts[name]:
            raise ValueError(f"series block `{block}` rests on {name!r}, which the data no "
                             "longer supports: rewrite the block for this quarter")


# ── threshold lines ─────────────────────────────────────────────────────────
# A line is one comparison a local analysis wrote down: last quarter's are
# settled in section one, this quarter's are watched in section three, and a
# roll moves the second list into the first unchanged. `kind` says what
# crossing it means -- a hurdle is something the analysis hoped to see
# (达到 / 没到), a guard something it warned about (守住 / 越线) -- and
# `trigger` is the comparison exactly as the analysis printed it, so a line
# written "≥ 15%" is tripped by 15% and one written "> 15%" is not. The value
# each line is read against is computed here from the series (`reads`), never
# typed into the block.
TRIGGERS = {
    "<": lambda value, line: value < line,
    "≤": lambda value, line: value <= line,
    ">": lambda value, line: value > line,
    "≥": lambda value, line: value >= line,
}
KIND_WORDS = {"hurdle": "达标线", "guard": "警示线"}
GOOD_WORDS = {"hurdle": "达到", "guard": "守住"}
BAD_WORDS = {"hurdle": "没到", "guard": "越线"}
UNDECIDED = "无法判定"
NOT_YET = "未到期"
SETTLED = ("达到", "没到", "守住", "越线")


def line_direction(entry: dict) -> str:
    """The side of the line `headroom` counts as positive: where a hurdle is met
    and where a guard is not tripped."""
    upward = entry["trigger"] in (">", "≥")
    if entry["kind"] == "hurdle":
        return "up" if upward else "down"
    return "down" if upward else "up"


def line_verdict(entry: dict, reading: dict) -> str:
    """达到 / 没到 / 守住 / 越线, or why the line cannot be read yet.

    A reading published only to US$0.1B carries a band; a line inside the band
    is 无法判定 rather than a coin toss read off the midpoint. A reading that
    does not exist yet (next year's guidance, before it is given) is 未到期.
    """
    if reading.get("value") is None:
        return NOT_YET
    hit = TRIGGERS[entry["trigger"]]
    low, high = reading.get("range") or (reading["value"], reading["value"])
    at_low, at_high = hit(low, entry["threshold"]), hit(high, entry["threshold"])
    if at_low != at_high:
        return UNDECIDED
    return (GOOD_WORDS if at_low == (entry["kind"] == "hurdle") else BAD_WORDS)[entry["kind"]]


def line_amount(unit: str, value: float, digits: int | None = None) -> str:
    """A threshold as the analysis wrote it: ``$8.2B``, ``1.10x``, ``44.0%``, ``13%``."""
    if unit == "pct":
        places = 1 if digits is None else digits
        return f"{value:.{places}f}%"
    if unit == "usd_bn_change":
        return "0" if value == 0 else f"{'+' if value > 0 else '−'}US${abs(value):.1f}B"
    if unit == "usd_m":
        return f"${value:,.0f}M"
    return unit_text(unit, value)


def line_label(entry: dict) -> str:
    """「单季回购金额 < $200M（连续两季）」: the line as a condition, for the headroom axis."""
    run = entry.get("consecutive", 1)
    return (f"{entry['metric']} {entry['trigger']} "
            f"{line_amount(entry['unit'], entry['threshold'], entry.get('digits'))}"
            + (f"（连续{cn_count(run)}季）" if run > 1 else ""))


def rounded_list(values: list[float | None], digits: int = 6) -> list[float | None]:
    return [None if value is None else round(value, digits) for value in values]


def threshold_reading(staging: dict, guidance: dict | None, reads: str) -> dict:
    """What a threshold line is read against, computed from the series.

    Returns the current value (``value``), how to print a value (``show``),
    and either a history to draw (``labels`` / ``values``) or ``why`` the
    reading has no chart. ``history`` is the quarterly record a
    "N quarters running" line is judged on; ``range`` is the band a reading
    derived from two rounded figures carries.
    """
    long = staging["long_history"]
    labels = [quarter_label(quarter) for quarter in long["quarters"]]
    revenue = long["revenue_usd_m"]
    backlog = long["backlog_usd_bn"]
    q = staging["quarterly_usd_m"]
    window = [compact_period(period) for period in shown(staging["periods"])]

    def trimmed(values: list[float | None]) -> tuple[list[str], list[float | None]]:
        start = leading_gap(values)
        return labels[start:], values[start:]

    if reads == "backlog":
        axis, values = trimmed(backlog)
        # The last hole in the record: before it only year-end figures exist.
        steady = max(i for i, value in enumerate(backlog) if value is None) + 1
        return {
            "value": backlog[-1], "show": lambda v: f"US${v:.1f}B", "history": backlog,
            "name": "季末 backlog", "labels": axis, "values": values, "fmt": "usd1", "ylab": "US$B",
            "note": (f"backlog 自 {labels[steady]} 起逐季披露，更早只有年末值；"
                     "精度到 US$0.1B，所以水平值可判，两季相减的净增要带上 ±US$0.1B。"),
            "src": "各季 CFO Commentary 的 Backlog 表（公司披露值）。",
        }
    if reads == "backlog_qoq":
        change = [None if i == 0 or backlog[i] is None or backlog[i - 1] is None
                  else round(backlog[i] - backlog[i - 1], 1) for i in range(len(backlog))]
        return {
            "value": change[-1], "show": lambda v: line_amount("usd_bn_change", v), "history": change,
            "why": ("没有单独画图：book-to-bill 等于 1 加上环比变化除以当季收入，季末 backlog 持平或下降"
                    "就是 book-to-bill ≤ 1.00x，画在 book-to-bill 那张图的 1.00x 线上。"),
        }
    if reads == "book_to_bill":
        # The change is taken at the precision the company prints (US$0.1B):
        # 8.1 − 8.0 in binary floating point is 0.0999…, which would put the
        # bottom of the band a hair under 1.00x and fail a line it clears.
        ratio = [None if i == 0 or backlog[i] is None or backlog[i - 1] is None
                 else (revenue[i] + round(backlog[i] - backlog[i - 1], 1) * 1000) / revenue[i]
                 for i in range(len(backlog))]
        axis, values = trimmed(ratio)
        swing = 2 * BACKLOG_HALF_STEP_BN * 1000
        net = round(backlog[-1] - backlog[-2], 1) * 1000
        low = (revenue[-1] + net - swing) / revenue[-1]
        high = (revenue[-1] + net + swing) / revenue[-1]
        return {
            "value": ratio[-1], "range": (low, high), "show": lambda v: f"{v:.2f}x", "history": ratio,
            "name": "单季 book-to-bill", "series_name": "单季 book-to-bill D",
            "labels": axis, "values": rounded_list(values),
            "fmt": "f2", "ylab": "倍",
            "note": (f"book-to-bill = （当季收入 + 季末 backlog 环比变化）÷ 当季收入，自算。"
                     f"backlog 只印到 US$0.1B，两季相减带 ±US${swing / 1000:.1f}B，所以本季 {ratio[-1]:.2f}x "
                     f"的真实值落在 {low:.2f}x–{high:.2f}x 之间：落在这个区间里的线判不了，区间整体在线的"
                     "一侧才算数。"),
            "src": "收入取各期 10-Q / 10-K，backlog 取各季 CFO Commentary；比率为本页自算（D）。",
        }
    if reads in ("buyback", "ocf"):
        key = "stock_repurchases" if reads == "buyback" else "operating_cash_flow"
        return {
            "value": q[key][-1], "show": lambda v: f"${v:,.0f}M", "history": q[key],
            "name": "单季回购金额" if reads == "buyback" else "单季经营现金流",
            "labels": window, "values": shown(q[key]), "fmt": "f0c", "ylab": "$M",
            "note": "",
            "src": ("回购金额取各季 CFO Commentary 的 Share Repurchase 表；" if reads == "buyback" else
                    "经营现金流取各期现金流量表（10-Q 只按年初至今披露，逐季由相邻两个年初至今值相减）；")
                   + f"本页的季度序列从 {staging['periods'][0]} 起，图上画最近{cn_count(WINDOW)}季。",
        }
    if reads == "eps_guide":
        full = (guidance or {}).get("full_year", {})
        now = round(mid(full["current"]["non_gaap_eps"]), 2) if full else None
        before = full.get("previous") if full else None
        return {
            "value": now, "show": lambda v: f"${v:.2f}",
            "why": ("没有时间序列可画：它比的是全年指引的两档中值"
                    + (f"（上季 ${mid(before['non_gaap_eps']):.2f} → 本季 ${now:.2f}）" if before and now else "")
                    + "，两档都列在核对抽屉的「下季与全年指引」表里。"),
        }
    if reads == "china_share":
        share = long["china_share_pct"]
        axis, values = trimmed(share)
        filed = q["china_revenue"][-1] / q["revenue_total"][-1] * 100
        return {
            "value": staging["quarterly_pct"]["geo_china"][-1], "show": lambda v: f"{v:.0f}%",
            "history": share, "name": "中国收入占比", "labels": axis, "values": values,
            "fmt": "pct0", "ylab": "占总收入",
            "basis": "公司在 CFO Commentary 印的整数占比",
            "alt": {"value": filed, "show": lambda v: f"{v:.1f}%", "basis": "申报金额（10-Q 分部附注）算出的占比"},
            "note": f"这条线是 CFO Commentary 印的<b>整数</b>占比，{axis[0]} 起才单列中国。",
            "src": "各季 CFO Commentary 的 Revenue Mix by Geography 表（整数百分比）。",
        }
    if reads == "margin":
        margin = long["non_gaap_operating_margin_pct"]
        break_at = long["quarters"].index(ASC_606_FIRST)
        return {
            "value": staging["quarterly_pct"]["non_gaap_operating_margin"][-1], "show": lambda v: f"{v:.1f}%",
            "history": margin, "name": "单季非 GAAP 营业利润率", "labels": labels, "values": margin,
            "fmt": "pct1", "ylab": "非 GAAP 营业利润率",
            "break_at": break_at, "break_label": "ASC 606",
            # Fixed history: 2018Q1 was printed under both standards (2018-04-23 CFO Commentary).
            "note": (f"{labels[break_at]} 起为 ASC 606，之前为 ASC 605 且公司没有重述——2018Q1 两套准则都印过："
                     "ASC 606 下 27.8%、ASC 605 下 29.5%，所以断点左侧那一段不能和右侧直接比高低。"),
            "src": "各季 CFO Commentary 的五季对照表（公司披露的非 GAAP 营业利润率）。",
        }
    if reads == "coverage":
        ratio = [None if i < 3 or backlog[i] is None else backlog[i] * 1000 / sum(revenue[i - 3:i + 1])
                 for i in range(len(backlog))]
        axis, values = trimmed(ratio)
        return {
            "value": ratio[-1], "show": lambda v: f"{v:.2f}x", "history": ratio, "seasonal": True,
            "name": "backlog / 过去四季收入", "series_name": "backlog / 过去四季收入 D",
            "labels": axis, "values": rounded_list(values), "fmt": "f2", "ylab": "倍",
            "note": coverage_pattern(long, ratio),
            "src": "backlog 取各季 CFO Commentary，收入取各期 10-Q / 10-K；比率为本页自算（D）。",
        }
    if reads == "ip_yoy":
        shares = staging["category_long_pct"]
        if [display_period(quarter) for quarter in shares["quarters"]] != [display_period(quarter)
                                                                           for quarter in long["quarters"]]:
            raise ValueError("`category_long_pct.quarters` must be `long_history.quarters`")
        ip = [None if share is None else share / 100 * total
              for share, total in zip(shares["category_semiconductor_ip"], revenue)]
        growth = [None if i < 4 or ip[i] is None or not ip[i - 4] else (ip[i] / ip[i - 4] - 1) * 100
                  for i in range(len(ip))]
        now, then = shares["category_semiconductor_ip"][-1], shares["category_semiconductor_ip"][-5]
        # Two whole-number shares, each good to ±0.5pp, bound the rate.
        low = ((now - 0.5) * revenue[-1]) / ((then + 0.5) * revenue[-5]) * 100 - 100
        high = ((now + 0.5) * revenue[-1]) / ((then - 0.5) * revenue[-5]) * 100 - 100
        company = stamped_block(staging["operating_kpi"], "category_growth_company_pct",
                                staging["periods"][-1])
        alt = None
        if company is not None and company.get("semiconductor_ip_yoy") is not None:
            point = company["semiconductor_ip_yoy"]
            alt = {"value": point, "show": lambda v: f"{v:+.0f}%", "basis": "公司在新闻稿里给的 IP 增速"}
        elif company is not None and company.get("semiconductor_ip_yoy_floor") is not None:
            floor = company["semiconductor_ip_yoy_floor"]
            alt = {"value": floor, "range": (floor, float("inf")), "show": lambda v: f"超过 {v:.0f}%",
                   "basis": "公司在新闻稿里给的 IP 增速"}
        break_at = long["quarters"].index(ASC_606_FIRST)
        return {
            "value": growth[-1], "range": (low, high), "show": lambda v: f"{v:+.0f}%", "history": growth,
            "name": "Semiconductor IP 同比", "series_name": "Semiconductor IP 同比（整数占比反推）D",
            "labels": labels, "values": rounded_list(growth), "fmt": "pct0", "ylab": "同比增速",
            "break_at": break_at, "break_label": "ASC 606",
            "basis": "整数占比乘总收入反推", "alt": alt,
            "note": (f"公司只印产品线的整数占比，本页用占比 × 当季收入反推 IP 收入再算同比；两个整数各带 ±0.5pp，"
                     f"复合到增速上本季是 {low:+.0f}% 到 {high:+.0f}%。{labels[break_at]} 起为 ASC 606，"
                     "那一年四季的同比拿 606 口径比 605 口径，跨着准则。"),
            "src": "各季 CFO Commentary 的 Revenue Mix by Product Group 表（整数百分比）× 各期 10-Q / 10-K 总收入；自算（D）。",
        }
    if reads == "fy_next_margin_guide":
        year = int(staging["periods"][-1].split()[1])
        full = (guidance or {}).get("full_year")
        if full and full["fiscal_year"] == year + 1:
            return {"value": mid(full["current"]["non_gaap_operating_margin_pct"]), "show": lambda v: f"{v:.2f}%",
                    "why": "没有时间序列可画：它读的是公司给出的下一财年初始指引。"}
        return {"value": None, "show": lambda v: f"{v:.2f}%",
                "why": f"它读的是 {year + 1} 财年的初始指引，公司要到 {year + 1} 年 2 月随第四季财报才给。"}
    if reads == "revenue":
        return {"value": q["revenue_total"][-1], "show": lambda v: f"${v:,.1f}M",
                "why": "没有单独画图：收入画在第二节的收入图与第一节的指引兑现图里。"}
    raise KeyError(f"threshold reads {reads!r} has no reading defined in build/cdns.py")


def first_half_backlog(long: dict) -> dict[str, list[tuple[int, float]]]:
    """Each year's first-half change in the backlog itself (prior year-end → Q2), by sign.

    Management says backlog is "normally" drawn down in the first half; the
    record, read here, is what the page prints instead.
    """
    quarters, backlog = long["quarters"], long["backlog_usd_bn"]
    halves: dict[str, list[tuple[int, float]]] = {"grew": [], "flat": [], "fell": []}
    for year in sorted({int(quarter[:4]) for quarter in quarters}):
        start, end = f"{year - 1}Q4", f"{year}Q2"
        if start not in quarters or end not in quarters:
            continue
        i, j = quarters.index(start), quarters.index(end)
        if backlog[i] is None or backlog[j] is None:
            continue
        change = round(backlog[j] - backlog[i], 1)
        halves["grew" if change > 0 else "fell" if change < 0 else "flat"].append((year, change))
    return halves


def coverage_pattern(long: dict, ratio: list[float | None]) -> str:
    """What the coverage multiple does over a first half, counted from the record.

    The page used to say the multiple falls every first half because backlog
    is drawn down every first half. The second half of that is false: the
    backlog itself grew over the first half in some years and was flat in
    others. What the record does support is the multiple's own pattern, so
    that is what is counted and printed.
    """
    quarters = long["quarters"]
    fell, rose = [], []
    for year in sorted({int(quarter[:4]) for quarter in quarters}):
        start, end = f"{year - 1}Q4", f"{year}Q2"
        if start not in quarters or end not in quarters:
            continue
        i, j = quarters.index(start), quarters.index(end)
        if ratio[i] is None or ratio[j] is None:
            continue
        (fell if ratio[j] < ratio[i] else rose).append(year)
    halves = first_half_backlog(long)
    level = {sign: [year for year, _ in pairs] for sign, pairs in halves.items()}
    span = sorted(fell + rose)
    if not span:
        return ""
    held_up = [year for year in fell if year not in level["fell"]]
    return (f"覆盖倍数有上半年走低的季节性：{span[0]}–{span[-1]} 年的"
            f"{cn_count(len(span))}个上半年里有{cn_count(len(fell))}个走低"
            + (f"（例外 {'、'.join(str(y) for y in rose)}）" if rose else "")
            + "，所以这条线要和去年同季比，不能拿环比读。但这是比率的季节性，不是 backlog 本身每年上半年都在消耗："
            f"同样这{cn_count(len(span))}年，上半年 backlog 绝对额增加的有{cn_count(len(level['grew']))}年"
            + (f"（{'、'.join(str(y) for y in level['grew'])}）" if level["grew"] else "")
            + f"、持平{cn_count(len(level['flat']))}年、减少{cn_count(len(level['fell']))}年"
            + (f"；比率走低的{cn_count(len(fell))}年里有{cn_count(len(held_up))}年 backlog 并没有减少，"
               "走低来自分母（过去四季收入）在长。" if held_up else "。"))


def period_order(label: str) -> tuple[int, int]:
    quarter, year = display_period(label).split()
    return int(year), int(quarter[1])


def read_line(staging: dict, guidance: dict | None, entry: dict) -> dict:
    """The reading one line is judged on.

    A line that must hold for N quarters running is judged on the quarter of
    those N that is furthest from tripping it. A line written about one named
    quarter (``period``) -- a quarter's revenue against that quarter's guided
    floor -- has no reading until that quarter is the page's: the revenue of
    the quarter before it would only show a growing line as already crossed.
    """
    page = staging["periods"][-1]
    if entry.get("period") and period_order(entry["period"]) != period_order(page):
        if period_order(entry["period"]) < period_order(page):
            raise ValueError(f"threshold {entry.get('id')!r} reads {entry['period']}, but the page is on "
                             f"{page}: settle it on its own quarter's page or drop it")
        return {"value": None, "why": f"这条线读的是 {entry['period']} 的数，要等 {entry['period']} 发布。"}
    reading = threshold_reading(staging, guidance, entry["reads"])
    run = entry.get("consecutive", 1)
    if run > 1 and reading.get("value") is not None:
        recent = reading["history"][-run:]
        binding = max(recent) if entry["trigger"] in ("<", "≤") else min(recent)
        reading = {**reading, "value": binding, "range": None,
                   "text": f"近{cn_count(run)}季 " + "、".join(reading["show"](v) for v in recent)}
    if reading.get("value") is not None and "text" not in reading:
        reading["text"] = reading["show"](reading["value"])
    return reading


def kind_words(lines: list[dict]) -> str:
    """「达标线三条达到一条、警示线四条都守住」, counted from the verdicts."""
    parts = []
    for kind in ("hurdle", "guard"):
        group = [line for line in lines if line["kind"] == kind]
        if not group:
            continue
        good = sum(1 for line in group if line["verdict"] == GOOD_WORDS[kind])
        if len(group) == 1:
            parts.append(f"{KIND_WORDS[kind]}一条{group[0]['verdict']}")
        elif good == len(group):
            parts.append(f"{KIND_WORDS[kind]}{cn_count(len(group))}条都{GOOD_WORDS[kind]}")
        elif good == 0:
            parts.append(f"{KIND_WORDS[kind]}{cn_count(len(group))}条都{BAD_WORDS[kind]}")
        else:
            parts.append(f"{KIND_WORDS[kind]}{cn_count(len(group))}条{GOOD_WORDS[kind]}{cn_count(good)}条")
    return "、".join(parts)


def basis_words(line: dict) -> str:
    """When a reading has a second basis, what the line says on it.

    The analyses rarely name the basis they mean: China's share is printed as a
    whole number in the CFO Commentary and implied in dollars by the 10-Q, and
    the IP rate is either the page's reconstruction or the company's own
    wording. The line is judged on the analysis' basis and the other is always
    shown, so a line the two bases disagree on is never settled in silence.
    """
    reading = line["reading"]
    alt = reading.get("alt")
    if not alt or line["verdict"] not in SETTLED:
        return ""
    other = line_verdict(line, alt)
    text = alt["show"](alt["value"])
    if other == line["verdict"]:
        return f"「{line_label(line)}」换成{alt['basis']}（{text}）判定相同。"
    return (f"「{line_label(line)}」换成{alt['basis']}（{text}）会判为{other}；报告与本页用的是"
            f"{reading['basis']}（{reading['show'](reading['value'])}），判为{line['verdict']}。")


def open_line_words(line: dict) -> str:
    """Why a line has no verdict: its reading's band straddles it, or the reading is not out yet."""
    reading = line["reading"]
    if line["verdict"] == UNDECIDED:
        low, high = reading["range"]
        return (f"「{line_label(line)}」{line['verdict']}：本季读数的精度区间 {reading['show'](low)}–"
                f"{reading['show'](high)} 横跨这条线。")
    return f"「{line_label(line)}」{line['verdict']}：{reading.get('why', '读数尚未披露。')}"


def margin_text(value: float) -> str:
    """A headroom as the table prints it; a zero is 「+0.0%」, never 「-0.0%」."""
    return f"{round(value, 1) + 0.0:+.1f}%"


def row_text(line: dict) -> str:
    """Where in the analysis a line was written: its section-8 row, or where else."""
    if line.get("row_label"):
        return line["row_label"]
    return f"第 8 节第{cn_ordinal(line['row'])}行" if line.get("row") else "第 1 节假设表"


def line_name(line: dict) -> str:
    """「达标线 US$8.2B」「警示线 $200M（连续两季）」."""
    run = line.get("consecutive", 1)
    return (f"{KIND_WORDS[line['kind']]} {line_amount(line['unit'], line['threshold'], line.get('digits'))}"
            + (f"（连续{cn_count(run)}季）" if run > 1 else ""))


def line_words(line: dict, era: str) -> str:
    """「没到上季达标线 US$8.2B」, or 「上季达标线 1.10x 无法判定」 when it cannot be read."""
    if line["verdict"] in SETTLED:
        return f"{line['verdict']}{era}{line_name(line)}"
    return f"{era}{line_name(line)} {line['verdict']}"


def line_charts(staging: dict, guidance: dict | None, lines: list[dict],
                era: str, upcoming: str | None = None) -> tuple[list[dict], list[str]]:
    """One chart per reading, every threshold line on that reading drawn across its history.

    ``era`` is 「上季」 (section one: each line is settled against this quarter)
    or 「下季」 (section three: each line is watched against the current value).
    A reading with no history to draw returns the sentence saying why, so no
    line is ever left out of the page without a word. For a seasonal reading
    watched into ``upcoming``, the note counts how often that same quarter has
    already sat on the wrong side of each line -- a line an ordinary seasonal
    dip can trip is still drawn where the analysis put it, and says so.
    """
    analysis = "上季" if era == "上季" else "本季"
    charts, undrawn = [], []
    for reads in dict.fromkeys(line["reads"] for line in lines):
        group = [line for line in lines if line["reads"] == reads]
        reading = threshold_reading(staging, guidance, reads)
        if "labels" not in reading:
            # A reading that does not exist yet is explained where its line is
            # listed as waiting; one that exists but has no history says why here.
            if reading.get("value") is not None:
                undrawn.append("".join(f"「{line_label(line)}」" for line in group) + reading["why"])
            continue
        axis = reading["labels"]
        now = reading["show"](reading["value"])
        series = [{"name": reading.get("series_name", reading["name"]), "values": reading["values"],
                   "color": "NAVY"}]
        by_level: dict[float, list[dict]] = {}
        for line in group:
            by_level.setdefault(line["threshold"], []).append(line)
        for (level, same), color in zip(by_level.items(), ("RED", "GOLD", "GRAY")):
            series.append({
                "name": "、".join(f"{era}{KIND_WORDS[line['kind']]}（{line['trigger']} "
                                 f"{line_amount(line['unit'], level, line.get('digits'))}"
                                 + (f"，连续{cn_count(line['consecutive'])}季" if line.get("consecutive", 1) > 1
                                    else "") + "）" for line in same),
                "values": [level] * len(axis),
                "color": color,
            })
        seasonal = ""
        if era == "下季" and reading.get("seasonal") and upcoming:
            quarter = display_period(upcoming).split()[0]
            same = [(label, value) for label, value in zip(axis, reading["values"])
                    if label.startswith(quarter + "'") and value is not None]
            for line in group:
                hits = [label for label, value in same if TRIGGERS[line["trigger"]](value, line["threshold"])]
                seasonal += (f"图上 {len(same)} 个{quarter}里有 {len(hits)} 个已经在 "
                             f"{line['trigger']} {line_amount(line['unit'], line['threshold'], line.get('digits'))} 那一侧"
                             + (f"（{'、'.join(hits)}）——正常的季节性回落本身就可能触发这条线，"
                                "本页照报告的阈值画，不换成更容易过的数。" if hits else "。"))
        if era == "上季":
            title = f"{reading['name']}：本季 {now}，" + "、".join(line_words(line, era) for line in group)
        else:
            title = (f"{reading['name']}：下季" + "、".join(
                f"{KIND_WORDS[line['kind']]} {line['trigger']} "
                f"{line_amount(line['unit'], line['threshold'], line.get('digits'))}" for line in group)
                + f"，当前 {now}")
        chart = {
            "ref": f"EX_{'PRIOR' if era == '上季' else 'NEXT'}_{reads.upper()}",
            "kind": "lines",
            "title": title,
            "xlabels": axis,
            "series": series,
            "fmt": reading["fmt"],
            "yfmt": reading["fmt"],
            "label_fmt": reading["fmt"],
            "end_label": True,
            "ylab": reading["ylab"],
            "note": (("红线与金线" if len(by_level) > 1 else "红线") + f"是阈值，逐字取自{analysis}本站季报分析"
                     + ("第 8 节" if all(line.get("row") for line in group) else "第 8 节或第 1 节的假设表")
                     + "，不是公司指引。" + reading["note"] + seasonal
                     + "".join(basis_words(line) for line in group)),
            "src_extra": reading["src"] + f"阈值取自{analysis}本站季报分析。",
        }
        if len(axis) > 12:
            chart["xstep"] = LONG_STEP
        if reading.get("break_at") is not None:
            chart["break_at"] = reading["break_at"]
            chart["break_label"] = reading["break_label"]
        charts.append(chart)
    return charts, undrawn


SOURCE_8K = (
    "指引区间来自各季业绩 8-K 的 EX-99.02 CFO Commentary 里「Q&lt;n&gt; &lt;year&gt; Outlook」段落；"
    "实际收入来自各期 10-Q / 10-K，实际非 GAAP 营业利润率与非 GAAP EPS 来自其后各期 "
    "CFO Commentary 的五季对照表。"
)

GUIDED_WHEN = "该季<b>刚开始不久时</b>"

# Cadence publishes each quarter's outlook alongside the *previous* quarter's
# results, and that release lands inside the quarter being guided -- about four
# weeks in for Q2/Q3/Q4, and past the halfway point for Q1, whose guidance waits
# for the mid-February annual release.  Every page module that draws this record
# has to say so, because "did it clear its own bar" means something weaker when
# a third to a half of the quarter is already in the books. The 2021Q1 example
# is fixed history (the release of 2021-02-22).
TIMING_CAVEAT = (
    "<b>口径提示：这不是事前预测。</b>Cadence 与上一季财报同时给出本季指引，"
    "发布日已经落在被指引季度<b>之内</b>——第二、三、四季通常已过约 4 周，"
    "第一季因四季报在 2 月中下旬发布，往往已过半个季度（例：2021Q1 的指引发布于 2021-02-22，"
    "该季 91 天已过 50 天）。核对表里的「指引发布日」一列可逐季复核。"
)


def record_facts(record: dict) -> dict:
    """What the guided record says, recounted: the counts every sentence about it uses."""
    quarters = record["quarters"]
    finished = [i for i, value in enumerate(record["revenue_actual_usd_m"]) if value is not None]

    def tally(low_key: str, high_key: str, actual_key: str) -> dict:
        low, high, actual = record[low_key], record[high_key], record[actual_key]
        rows = [i for i in finished if actual[i] is not None]
        return {
            "rows": rows,
            "above": [i for i in rows if actual[i] > high[i]],
            "below": [i for i in rows if actual[i] < low[i]],
            "below_mid": [i for i in rows if actual[i] < (low[i] + high[i]) / 2],
        }

    return {
        "quarters": quarters,
        "finished": finished,
        "revenue": tally("revenue_guide_low_usd_m", "revenue_guide_high_usd_m", "revenue_actual_usd_m"),
        "margin": tally("non_gaap_operating_margin_guide_low_pct",
                        "non_gaap_operating_margin_guide_high_pct",
                        "non_gaap_operating_margin_actual_pct"),
        "eps": tally("non_gaap_eps_guide_low", "non_gaap_eps_guide_high", "non_gaap_eps_actual"),
    }


def guidance_delivery_charts(staging: dict, story: dict | None) -> list[dict]:
    """The full guided record for the three metrics Cadence files a range for.

    Cadence guides revenue, non-GAAP operating margin and non-GAAP EPS every
    quarter in the same filed document, so each gets the same pair -- the range
    against the reported result, then the distance from the guided midpoint --
    grouped so one metric is read through before the next begins.

    The three answers are not the same answer, and every sentence below that
    says which is which is recounted from the record: revenue and EPS have (so
    far) never landed under the floor; the margin has, and so far only against
    a guidance that was a single number rather than a range.
    """
    record = staging["quarterly_guidance_history"]
    facts = record_facts(record)
    quarters = record["quarters"]
    labels = [quarter_label(quarter) for quarter in quarters]

    revenue_lo = record["revenue_guide_low_usd_m"]
    revenue_hi = record["revenue_guide_high_usd_m"]
    revenue_actual = record["revenue_actual_usd_m"]
    margin_lo = record["non_gaap_operating_margin_guide_low_pct"]
    margin_hi = record["non_gaap_operating_margin_guide_high_pct"]
    margin_actual = record["non_gaap_operating_margin_actual_pct"]
    margin_form = record["non_gaap_operating_margin_guide_form"]
    eps_lo = record["non_gaap_eps_guide_low"]
    eps_hi = record["non_gaap_eps_guide_high"]
    eps_actual = record["non_gaap_eps_actual"]

    finished = facts["finished"]
    point_quarters = sum(1 for form in margin_form if form == "point")
    # ASC 606 replaced ASC 605 for the quarter beginning 2018-01-01 and Cadence
    # did not restate the earlier years, so the level charts carry a break there.
    break_at = quarters.index(ASC_606_FIRST)

    # A ±$15M band on a $450M quarter and the same band on a $1,600M quarter are
    # the same *proportion* and a very different number of pixels, so the band
    # chart draws the recent window and the deviation chart carries the record.
    band_window = slice(max(0, len(quarters) - BAND_QUARTERS), len(quarters))
    band_labels = labels[band_window]
    drawn = len(band_labels)
    scope = f"（本图仅近 {drawn} 季）"
    band_break = max(0, break_at - band_window.start) if break_at >= band_window.start else None
    first_actual, last_actual = revenue_actual[finished[0]], revenue_actual[finished[-1]]
    first_half_band = (revenue_hi[0] - revenue_lo[0]) / 2

    revenue_band = delivery_band(
        "EX_REV_RANGE", "收入", band_labels, revenue_lo[band_window], revenue_hi[band_window],
        revenue_actual[band_window],
        fmt="f0c", ylab="$M", unit="$M", venue="财报的 CFO Commentary", timing=GUIDED_WHEN,
        scope=scope,
        src_extra=SOURCE_8K + TIMING_CAVEAT,
        extra_note=(
            f"<b>这张只画最近 {drawn} 季，不是数据缺失</b>：本页的指引记录一路回到 {quarters[0]}，"
            f"而收入在这段时间从 US${first_actual / 1000:.2f}B 长到 US${last_actual / 1000:.2f}B，"
            f"早年的指引区间只有 ±${first_half_band:.0f}M，"
            "放在同一根线性美元轴上会被压成一两个像素。"
            f"完整 {len(quarters)} 季的同一问题改用与量级无关的口径回答，见 Exhibit {{EX_REV_DEV}}。"
        ),
        break_at=band_break,
        break_label="ASC 606",
    )

    revenue = facts["revenue"]
    n_finished = len(finished)
    if not revenue["below"] and not revenue["below_mid"]:
        record_words = (
            f"<b>这是全页最该先读的一张</b>：{n_finished} 个已完结季里，实际收入"
            "<b>一次都没有跌破过指引下限，也一次都没有低于指引中值</b>——"
            f"不是很少，是零次，跨越{years_words(n_finished)}、两任产品周期、一次会计准则切换和一次出口管制冲击。"
        )
    elif not revenue["below"]:
        record_words = (
            f"<b>这是全页最该先读的一张</b>：{n_finished} 个已完结季里，实际收入"
            f"<b>一次都没有跌破过指引下限</b>，低于指引中值的有 {len(revenue['below_mid'])} 季"
            f"（{'、'.join(labels[i] for i in revenue['below_mid'])}）。"
        )
    else:
        record_words = (
            f"<b>这是全页最该先读的一张</b>：{n_finished} 个已完结季里，实际收入有 "
            f"{len(revenue['below'])} 季跌破指引下限（{'、'.join(labels[i] for i in revenue['below'])}）。"
        )
    revenue_dev = midpoint_deviation(
        "EX_REV_DEV", "收入", quarters, revenue_lo, revenue_hi, revenue_actual,
        mode="pct", window=n_finished, label=quarter_label, bar_labels=False,
        src_extra=SOURCE_8K + "偏离为实际收入除以指引中值的自算值。" + TIMING_CAVEAT,
        extra_note=(
            record_words
            + f"柱高在这里可比，因为口径是百分比，不受收入量级{times_words(last_actual / first_actual)}变化的影响。"
            f"{ASC_606_FIRST} 起收入确认改用 ASC 606：每一对「指引 vs 实际」都落在同一套准则内，"
            f"所以偏离序列不受影响，只有上一张的水平值跨 {ASC_606_FIRST} 不可直接连读。"
        ),
    )
    margin_band = delivery_band(
        "EX_MARGIN_RANGE", "非 GAAP 营业利润率", band_labels,
        margin_lo[band_window], margin_hi[band_window], margin_actual[band_window],
        fmt="pct1", ylab="非 GAAP 营业利润率", unit="%", venue="财报的 CFO Commentary", timing=GUIDED_WHEN,
        scope=scope,
        src_extra=SOURCE_8K + (
            "公司在部分季度给的是单点数（原文写作 ~30% 或 approximately 30%）而不是区间，"
            "那些季的色块没有宽度；写作「29% to 30%」的季度是区间，不是单点。"
        ) + TIMING_CAVEAT,
        extra_note=(
            f"整段 {len(quarters)} 季记录里有 {point_quarters} 季公司给的是<b>一个点</b>而不是区间"
            "（新闻稿原文写作 ~30% 这种形式），那些季在图上没有宽度可言——"
            "这不是渲染问题，是指引本身没有宽度。"
            f"同样只画最近 {drawn} 季，完整记录见 Exhibit {{EX_MARGIN_DEV}}。"
        ),
        break_at=band_break,
        break_label="ASC 606",
    )

    # Below the guided midpoint -- the bars under zero on the deviation chart.
    negative = [i for i in finished
                if margin_actual[i] - (margin_lo[i] + margin_hi[i]) / 2 < 0]
    gaps = [abs(margin_actual[i] - (margin_lo[i] + margin_hi[i]) / 2) for i in negative]
    all_point = all(margin_form[i] == "point" for i in negative)
    if not negative:
        negative_words = "没有一季低于指引中值。"
    else:
        count = len(negative)
        lead = ("唯一一次为负的季度" if count == 1 else
                "唯二两次为负的季度都" if count == 2 else f"{count} 次为负的季度都")
        where = "发生在<b>单点指引</b>上" if all_point else (
            "发生在 " + "、".join(labels[i] for i in negative) + " 这几季")
        sizes = " 与 ".join(f"{gap:.1f}pp" for gap in gaps)
        negative_words = (
            f"{lead}{where}，而且差距{'分别' if count > 1 else ''}只有 {sizes}"
            + ("——在一个没有宽度的指引面前，这两次与其说是「跌破」，不如说是四舍五入。"
               if all_point and count == 2 and max(gaps) < 0.5 else
               "——在一个没有宽度的指引面前，与其说是「跌破」，不如说是四舍五入。"
               if all_point and max(gaps) < 0.5 else "。")
        )
    margin_dev = midpoint_deviation(
        "EX_MARGIN_DEV", "非 GAAP 营业利润率", quarters, margin_lo, margin_hi, margin_actual,
        mode="pp", window=n_finished, label=quarter_label, bar_labels=False,
        src_extra=SOURCE_8K + "偏离为实际利润率减指引中值的算术差。" + TIMING_CAVEAT,
        extra_note=negative_words,
    )

    # The EPS range's width, by era: where it started and where it has sat since.
    half = [round((hi - lo) / 2, 3) for lo, hi in zip(eps_lo, eps_hi)]
    two_sided = all(hi > lo for lo, hi in zip(eps_lo, eps_hi))
    head = 0
    while head + 1 < len(half) and half[head + 1] == half[0]:
        head += 1
    tail = len(half) - 1
    while tail > 0 and half[tail - 1] == half[-1]:
        tail -= 1
    width_words = (
        f"区间半宽从 {labels[0]}–{labels[head]} 的 ±${half[0]:.2f} 放宽到 {labels[tail]} 起的 ±${half[-1]:.2f}"
        if half[-1] > half[0] else
        f"区间半宽从 {labels[0]}–{labels[head]} 的 ±${half[0]:.2f} 收窄到 {labels[tail]} 起的 ±${half[-1]:.2f}"
        if half[-1] < half[0] else f"区间半宽一直是 ±${half[0]:.2f}"
    )
    eps_band = delivery_band(
        "EX_EPS_RANGE", "非 GAAP EPS", band_labels, eps_lo[band_window], eps_hi[band_window],
        eps_actual[band_window],
        fmt="usd2", ylab="US$/股", unit="US$", venue="财报的 CFO Commentary", timing=GUIDED_WHEN,
        scope=scope,
        src_extra=SOURCE_8K + TIMING_CAVEAT,
        extra_note=(
            (f"EPS 的指引区间始终是双边的，{len(quarters)} 季无一例外，" if two_sided else
             f"EPS 的指引在 {len(quarters)} 季里有 {sum(1 for lo, hi in zip(eps_lo, eps_hi) if hi <= lo)} 季是单点，")
            + width_words + "。"
            f"完整记录见 Exhibit {{EX_EPS_DEV}}。"
        ),
        break_at=band_break,
        break_label="ASC 606",
    )

    eps = facts["eps"]
    deviation = {i: (eps_actual[i] / ((eps_lo[i] + eps_hi[i]) / 2) - 1) * 100 for i in finished}
    era = [i for i in finished if EPS_BEAT_ERA[0] <= int(quarters[i][:4]) <= EPS_BEAT_ERA[1]]
    recent = finished[-WINDOW:]
    era_mean = statistics.fmean(deviation[i] for i in era)
    recent_mean = statistics.fmean(deviation[i] for i in recent)
    era_wide = sum(1 for i in era if deviation[i] >= 5)
    thinning = recent_mean < era_mean and not eps["below"]
    reading = (story or {}).get("eps_reading")
    eps_tail = (("<b>指引仍是底线，只是留出的余量在变薄</b>" if thinning else "")
                + (("，" if thinning else "") + reading if reading else ("。" if thinning else "")))
    floor_words = ("与收入同样从未跌破下限" if not eps["below"] and not revenue["below"] else
                   "从未跌破下限" if not eps["below"] else
                   f"有 {len(eps['below'])} 季跌破下限")
    eps_dev = midpoint_deviation(
        "EX_EPS_DEV", "非 GAAP EPS", quarters, eps_lo, eps_hi, eps_actual,
        mode="pct", window=n_finished, label=quarter_label, bar_labels=False,
        src_extra=SOURCE_8K + "偏离为实际非 GAAP EPS 除以指引中值的自算值。" + TIMING_CAVEAT,
        extra_note=(
            f"{floor_words}，但超出的幅度"
            + ("在收窄" if recent_mean < era_mean else "没有收窄")
            + f"：{EPS_BEAT_ERA[0]}–{EPS_BEAT_ERA[1]} 年 {len(era)} 季里 {era_wide} 季在 +5% 以上、"
            f"平均 {era_mean:+.1f}%，近{cn_count(len(recent))}季平均 {recent_mean:+.1f}%。"
            + eps_tail
        ),
    )
    return [revenue_band, revenue_dev, margin_band, margin_dev, eps_band, eps_dev]


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    return [f"Revenue ${staging['quarterly_usd_m']['revenue_total'][-1] / 1000:.2f}B",
            f"Backlog ${staging['quarterly_other']['backlog_usd_bn'][-1]:.1f}B",
            f"Non-GAAP OpM {staging['quarterly_pct']['non_gaap_operating_margin'][-1]:.1f}%"]


def release_source(staging: dict, period: str) -> dict:
    """The quarter's own earnings 8-K, which the page must cite."""
    found = next((item for item in staging["sources"]
                  if item["label"].startswith(f"{period} 业绩发布 8-K")), None)
    if found is None:
        raise ValueError(f"series `sources` has no entry for the {period} earnings 8-K: add it with the roll")
    return found


def guided_plan(staging: dict, guidance: dict | None, periods: list[str],
                revenue: list[float], ng_oi: list[float]) -> dict | None:
    """The arithmetic the outlook implies, from filed numbers only.

    The full-year non-GAAP operating income at the guidance midpoint, less what
    the year's reported quarters earned, less what the next quarter is guided to
    earn, is what the company has implicitly guided the rest of the year to.
    Which quarters that rest is depends on the quarter the page is on: after a
    first quarter it is Q3–Q4, after a second it is Q4, after a third nothing is
    left, and after a fourth the outlook is for the next year and the rest is
    Q2–Q4 of it. Every input is a company figure; nothing is an estimate.
    """
    if guidance is None:
        return None
    nq = guidance["next_quarter"]
    full = guidance["full_year"]
    cur, prev = full["current"], full.get("previous")
    fy_year = full["fiscal_year"]
    nq_period = nq["period"]
    nq_number, nq_year = int(nq_period[1]), int(nq_period.split()[1])
    done = [i for i, p in enumerate(periods) if p.endswith(f" {fy_year}")]
    ytd_revenue = sum(revenue[i] for i in done)
    ytd_oi = sum(ng_oi[i] for i in done)
    fy_revenue = mid(cur["revenue_usd_m"])
    fy_oi = cur["non_gaap_operating_income_midpoint_usd_m"]
    nq_revenue = mid(nq["revenue_usd_m"])
    nq_margin = mid(nq["non_gaap_operating_margin_pct"])
    nq_oi = nq_revenue * nq_margin / 100
    remaining = list(range(nq_number + 1, 5)) if nq_year == fy_year else []
    plan = {
        "fiscal_year": fy_year, "current": cur, "previous": prev, "next": nq,
        "next_period": nq_period, "next_label": compact_period(nq_period),
        "done": done, "ytd_revenue": ytd_revenue, "ytd_oi": ytd_oi,
        "ytd_margin": ytd_oi / ytd_revenue * 100 if done else None,
        "fy_revenue": fy_revenue, "fy_oi": fy_oi,
        "nq_revenue": nq_revenue, "nq_margin": nq_margin, "nq_oi": nq_oi,
        "rest_revenue": fy_revenue - ytd_revenue, "rest_oi": fy_oi - ytd_oi,
    }
    plan["rest_margin"] = plan["rest_oi"] / plan["rest_revenue"] * 100
    if done:
        plan["giveback"] = plan["rest_revenue"] * plan["ytd_margin"] / 100 - plan["rest_oi"]
    if remaining:
        word = f"Q{remaining[0]}" if len(remaining) == 1 else f"Q{remaining[0]}–Q{remaining[-1]}"
        plan["remainder_word"] = word
        plan["remainder_period"] = f"{word} {fy_year}"
        plan["remainder_label"] = f"{word}'{str(fy_year)[-2:]}E"
        plan["remainder_revenue"] = fy_revenue - ytd_revenue - nq_revenue
        plan["remainder_oi"] = fy_oi - ytd_oi - nq_oi
        plan["remainder_margin"] = plan["remainder_oi"] / plan["remainder_revenue"] * 100
    year_ago = f"Q{nq_number} {nq_year - 1}"
    if year_ago in periods:
        plan["nq_yoy"] = pct_change(nq_revenue, revenue[periods.index(year_ago)])
    plan["nq_qoq"] = pct_change(nq_revenue, revenue[-1])
    if prev is not None:
        plan["raise_revenue"] = fy_revenue - mid(prev["revenue_usd_m"])
        plan["raise_oi"] = fy_oi - prev["non_gaap_operating_income_midpoint_usd_m"]
        plan["incremental_margin"] = plan["raise_oi"] / plan["raise_revenue"] * 100
        exact = (fy_revenue * mid(cur["non_gaap_operating_margin_pct"]) / 100
                 - mid(prev["revenue_usd_m"]) * mid(prev["non_gaap_operating_margin_pct"]) / 100)
        plan["incremental_margin_exact"] = exact / plan["raise_revenue"] * 100
        # The printed operating income is revenue midpoint × margin midpoint,
        # rounded to the million, in every outlook on file; say so only while true.
        plan["rounding_explains"] = all(
            abs(block["non_gaap_operating_income_midpoint_usd_m"]
                - mid(block["revenue_usd_m"]) * mid(block["non_gaap_operating_margin_pct"]) / 100) <= 0.5
            for block in (cur, prev))
    return plan


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    period = periods[-1]
    year, quarter_number = int(period.split()[1]), int(period[1])
    labels = [compact_period(p) for p in shown(periods)]
    q = staging["quarterly_usd_m"]
    qp = staging["quarterly_pct"]
    qo = staging["quarterly_other"]
    fy = staging["fiscal_year"]
    record = staging["quarterly_guidance_history"]
    latest = latest_block(staging, period=period, full_label=f"{period}（自然年季度）")
    release = release_source(staging, period)
    ir = next(item for item in staging["sources"] if item["label"] == "Cadence Investor Relations")

    closure = stamped_block(staging, "followup_closure", period)
    prior_kpi = stamped_block(staging, "prior_kpi_settlement", period)
    next_kpi = stamped_block(staging, "next_kpi", period)
    guidance = stamped_block(staging, "guidance", period)
    consensus = stamped_block(staging, "market_expectation", period)
    story = stamped_block(staging, "quarter_story", period)
    balance = stamped_block(staging, "balance_sheet_usd_m", period)
    bridge = stamped_block(staging, "ytd_cash_bridge_usd_m", period)
    company_growth = stamped_block(staging["operating_kpi"], "category_growth_company_pct", period)
    story_or = story or {}

    revenue = q["revenue_total"]
    revenue_shown = shown(revenue)
    revenue_yoy = shown(yoy(revenue))
    services = shown(q["revenue_services"])
    recon = staging["non_gaap_reconciliation_usd_m"]
    if recon["periods"] != periods:
        raise ValueError("`non_gaap_reconciliation_usd_m.periods` must be the page's periods")
    # Non-GAAP operating income to the thousand: GAAP operating income plus the
    # operating add-backs of each release's reconciliation. Summing the CFO
    # Commentary's rounded "non-GAAP costs" instead is off by up to a million a
    # quarter -- enough to move the implied fourth quarter by five basis points.
    ng_oi = [oi + add for oi, add in zip(q["operating_income"], recon["operating_addbacks"])]

    non_gaap_margin = shown(qp["non_gaap_operating_margin"])
    gaap_margin = shown(qp["gaap_operating_margin"])
    gaap_gross = shown(qp["gaap_gross_margin"])
    non_gaap_gross = shown(qp["non_gaap_gross_margin"])
    amortisation_drag = [
        gross_non_gaap - gross_gaap
        for gross_non_gaap, gross_gaap in zip(non_gaap_gross, gaap_gross)
    ]

    operating_cash_flow = shown(q["operating_cash_flow"])
    capex = shown(q["capital_expenditures"])
    free_cash_flow = [flow - spend for flow, spend in zip(operating_cash_flow, capex)]
    buybacks = shown(q["stock_repurchases"])
    buyback_shares = shown(qo["buyback_shares_m"])
    diluted_shares = shown(qo["diluted_shares_m"])
    research_yoy = shown(yoy(q["research_and_development"]))
    marketing_yoy = shown(yoy(q["marketing_and_sales"]))
    admin_yoy = shown(yoy(q["general_and_administrative"]))
    sbc = shown(q["stock_based_compensation"])
    sbc_ratio = [value / total * 100 for value, total in zip(sbc, revenue_shown)]

    backlog_all = qo["backlog_usd_bn"]
    backlog = shown(backlog_all)
    # Coverage, not level: the backlog is a record in dollars and shrinking in
    # months, and only the ratio shows the second thing. Computed over every
    # quarter held, so the drawn ones can be compared against the same quarter
    # a year and two years earlier -- the multiple is drawn down every first
    # half and a sequential read misleads.
    coverage_all = [
        None if index < 3 or backlog_all[index] is None
        else backlog_all[index] * 1000 / sum(revenue[index - 3: index + 1])
        for index in range(len(revenue))
    ]
    coverage = coverage_all[-WINDOW:]
    # Book-to-bill: one quarter's revenue plus the quarter's change in backlog,
    # over that revenue. Both legs are disclosed; the backlog is only published
    # to US$0.1B, so the change carries ±US$0.1B and the ratio a range.
    net_add = (backlog_all[-1] - backlog_all[-2]) * 1000
    book_to_bill = (revenue[-1] + net_add) / revenue[-1]
    swing = 2 * BACKLOG_HALF_STEP_BN * 1000
    btb_low = (revenue[-1] + net_add - swing) / revenue[-1]
    btb_high = (revenue[-1] + net_add + swing) / revenue[-1]
    btb_range = f"{btb_low:.2f}x–{btb_high:.2f}x"
    year_end = f"Q4 {year - 1}"
    ytd_backlog_add = ((backlog_all[-1] - backlog_all[periods.index(year_end)]) * 1000
                       if year_end in periods and quarter_number < 4 else None)
    backlog_record = backlog_all[-1] == max(v for v in backlog_all if v is not None) and \
        backlog_all[-1] > max(v for v in backlog_all[:-1] if v is not None)

    ytd_word = YTD_WORDS[quarter_number]
    ytd = [i for i, p in enumerate(periods) if p.endswith(f" {year}")]
    ytd_ocf = sum(q["operating_cash_flow"][i] for i in ytd)

    # ── product category and geography are published as integer percentages ──
    # of total revenue and nothing else, so every dollar figure below is that
    # percentage times the reported total, and carries the rounding with it.
    def mix_series(key: str, window: int) -> tuple[list[str], list[float | None]]:
        share = qp[key]
        start = leading_gap(share)
        picked = list(range(max(start, len(share) - window), len(share)))
        return (
            [compact_period(periods[index]) for index in picked],
            [share[index] / 100 * revenue[index] for index in picked],
        )

    category_labels, core_eda = mix_series("category_core_eda", WINDOW + 2)
    _, semiconductor_ip = mix_series("category_semiconductor_ip", WINDOW + 2)
    _, system_design = mix_series("category_system_design_analysis", WINDOW + 2)

    def mix_yoy(key: str, bump_now: float = 0.0, bump_then: float = 0.0) -> float:
        return pct_change((qp[key][-1] + bump_now) / 100 * revenue[-1],
                          (qp[key][-5] + bump_then) / 100 * revenue[-5])

    derived_growth = {
        "category_core_eda": mix_yoy("category_core_eda"),
        "category_semiconductor_ip": mix_yoy("category_semiconductor_ip"),
        "category_system_design_analysis": mix_yoy("category_system_design_analysis"),
    }
    ip_yoy = derived_growth["category_semiconductor_ip"]
    core_eda_yoy = derived_growth["category_core_eda"]
    system_design_yoy = derived_growth["category_system_design_analysis"]
    fastest = max(derived_growth, key=derived_growth.get)
    # Two integer shares, each good to ±0.5pp, bound the derived growth rate.
    ip_low = mix_yoy("category_semiconductor_ip", -0.5, +0.5)
    ip_high = mix_yoy("category_semiconductor_ip", +0.5, -0.5)

    # This quarter's own guided range, read from the record rather than retyped.
    record_index = record["quarters"].index(record_key(period))
    quarter_guide_low = record["revenue_guide_low_usd_m"][record_index]
    quarter_guide_high = record["revenue_guide_high_usd_m"][record_index]
    quarter_guide_mid = (quarter_guide_low + quarter_guide_high) / 2
    versus_mid = pct_change(revenue[-1], quarter_guide_mid)
    inside_guide = quarter_guide_low <= revenue[-1] <= quarter_guide_high
    facts_record = record_facts(record)

    long = staging["long_history"]
    long_labels = [quarter_label(quarter) for quarter in long["quarters"]]
    long_revenue = long["revenue_usd_m"]
    long_revenue_yoy = yoy(long_revenue)
    long_research = long["research_and_development_usd_m"]
    long_research_ratio = [
        None if value is None else value / total * 100
        for value, total in zip(long_research, long_revenue)
    ]
    long_opex_ratio = [
        (rnd + sell + admin) / total * 100
        for rnd, sell, admin, total in zip(
            long_research, long["marketing_and_sales_usd_m"],
            long["general_and_administrative_usd_m"], long_revenue)
    ]
    reported_yoy = [(index, value) for index, value in enumerate(long_revenue_yoy) if value is not None]
    max_index, max_yoy = max(reported_yoy, key=lambda pair: pair[1])
    peak_quarter = quarter_label(long["quarters"][max_index])
    after_peak = [pair for pair in reported_yoy if pair[0] > max_index]
    negative_yoy = [(index, value) for index, value in reported_yoy if value < 0]
    asc_605 = sum(1 for standard in long["accounting_standard"] if standard == "ASC 605")
    # China is disclosed in dollars in the segment note, so the line is filed
    # rather than derived; the integer share reaches further back but is only
    # ever used as a share.
    china_from = leading_gap(q["china_revenue"])
    china_labels = [compact_period(p) for p in periods[china_from:]]
    china_revenue = q["china_revenue"][china_from:]
    china_share_exact = [
        None if value is None else value / total * 100
        for value, total in zip(china_revenue, revenue[china_from:])
    ]
    china_yoy = yoy(q["china_revenue"])[china_from:]
    china_peak = max(v for v in china_revenue if v is not None)
    china_peak_index = china_from + q["china_revenue"][china_from:].index(china_peak)
    china_peak_quarter = record_key(periods[china_peak_index])
    china_is_peak = china_peak_index == len(periods) - 1
    china_share_yoy_by_share = pct_change(qp["geo_china"][-1] / 100 * revenue[-1],
                                          qp["geo_china"][-5] / 100 * revenue[-5])
    recent_shares = [q["china_revenue"][i] / revenue[i] * 100 for i in range(len(periods) - WINDOW, len(periods))]
    china_rank = sorted(recent_shares, reverse=True).index(recent_shares[-1]) + 1

    plan = guided_plan(staging, guidance, periods, revenue, ng_oi)

    # The quarter in the drawn window whose margin sits closest to the implied
    # remainder -- recomputed, because "the same as the crisis quarter" was a
    # sentence about one number that moves.
    peer = None
    if plan and "remainder_margin" in plan:
        window_margins = list(zip(periods[-WINDOW:], non_gaap_margin))
        best = min(abs(value - plan["remainder_margin"]) for _, value in window_margins)
        peer_period, peer_margin = [pair for pair in window_margins
                                    if abs(pair[1] - plan["remainder_margin"]) == best][-1]
        gap = plan["remainder_margin"] - peer_margin
        if round(plan["remainder_margin"], 1) == round(peer_margin, 1) or abs(gap) < 0.5:
            story_peer = story_or.get("implied_peer") or {}
            peer = {
                "period": peer_period, "key": record_key(peer_period), "margin": peer_margin,
                "gap": gap, "label": story_peer.get("label", "") if story_peer.get("quarter") == peer_period else "",
                "why": story_peer.get("why") if story_peer.get("quarter") == peer_period else None,
                "china_share": qp["geo_china"][periods.index(peer_period)],
            }

    def peer_clause(labelled: bool = False, with_value: bool = False) -> str:
        """「与危机季 2025Q2 持平」 when the printed figures agree, the gap otherwise."""
        if peer is None:
            return ""
        head = (f"与{peer['label']} {peer['key']}" if labelled and peer["label"]
                else f"与 {peer['key']}")
        if round(plan["remainder_margin"], 1) == round(peer["margin"], 1):
            return head + (f" 的 {peer['margin']:.1f}%" if with_value else "") + " 持平"
        return head + f" 的 {peer['margin']:.1f}% 只差 {abs(peer['gap']):.1f}pp"

    # ── what the story blocks may assume, recomputed ─────────────────────────
    facts = {
        "ytd_backlog_grew": ytd_backlog_add is not None and ytd_backlog_add > 0,
        "revenue_inside_guide": inside_guide,
        "china_below_peak": not china_is_peak,
        "china_peak_is_next_base": bool(plan) and china_peak_quarter == record_key(
            f"Q{plan['next_period'][1]} {int(plan['next_period'].split()[1]) - 1}"),
        "ip_fastest": fastest == "category_semiconductor_ip",
        "gaap_gross_down": gaap_gross[-1] < gaap_gross[-2],
        "non_gaap_gross_up": non_gaap_gross[-1] > non_gaap_gross[-2],
        "full_year_raised": bool(plan) and plan.get("raise_revenue", 0) > 0,
        "implied_below_ytd": bool(plan) and "remainder_margin" in plan and plan["ytd_margin"] is not None
        and plan["remainder_margin"] < plan["ytd_margin"],
    }
    require(story, facts, "quarter_story")

    # ── the numbers a story sentence may name ────────────────────────────────
    values = {
        "ytd_word": ytd_word,
        "backlog": f"US${backlog_all[-1]:.1f}B",
        "backlog_record": " 创纪录" if backlog_record else "",
        "ytd_backlog_add": "—" if ytd_backlog_add is None else f"${ytd_backlog_add:,.0f}M",
        "backlog_net_add": f"${net_add:,.0f}M",
        "book_to_bill_range": btb_range,
        "ocf": f"${operating_cash_flow[-1]:,.0f}M",
        "ocf_yoy": f"{pct_change(operating_cash_flow[-1], operating_cash_flow[-5]):+.0f}%",
        "buyback": f"${buybacks[-1]:,.0f}M",
        "china_year_ago": f"${q['china_revenue'][-5]:,.0f}M",
        "china_peak_quarter": china_peak_quarter,
        "china_share_exact": f"{china_share_exact[-1]:.1f}%",
        "china_revenue": f"${china_revenue[-1]:,.0f}M",
        "china_share_rank": (f"创{years_words(WINDOW)}新高" if china_rank == 1 else
                             f"为{years_words(WINDOW)}来第{cn_ordinal(china_rank)}高"),
        "china_vs_peak": (f"仍低于 {china_peak_quarter} 的 ${china_peak:,.0f}M" if not china_is_peak
                          else "为全序列最高"),
    }
    hexagon = staging["operating_kpi"].get("hexagon")
    if hexagon:
        values["hexagon_revenue"] = f"${hexagon['revenue_contribution_usd_m']:,.0f}M"
        values["hexagon_eps"] = f"−${abs(hexagon['eps_dilution_usd']):.2f}"
        low, high = hexagon["operating_margin_range_pct"]
        values["hexagon_margin"] = f"{low:.0f}–{high:.0f}%"
    if balance is not None:
        taxes = balance.get("other_long_term_liabilities_components", {}).get("deferred_income_taxes")
        if taxes:
            values["dtl_start"], values["dtl_end"] = (f"${value:,.1f}M" for value in taxes)
    acquisition = staging.get("acquisition_dne")
    if acquisition:
        values["dne_shares"] = f"{acquisition['shares_issued_m']:.1f}M"
        values["dne_stock_value"] = f"${acquisition['stock_fair_value_usd_m']:,.1f}M"
        values["dne_ltl"] = f"${acquisition['long_term_liabilities_assumed_usd_m']:,.1f}M"
    # The years before this one in which the backlog itself grew over the first
    # half: the claim that it is "normally drawn down" is management's.
    earlier = [f"{when} 年 +US${change:.1f}B"
               for when, change in first_half_backlog(staging["long_history"])["grew"] if when != year]
    # Placeholder names are letters and underscores only: `fill_story` passes
    # a name with a digit in it through as literal braces.
    values["half_growth_years"] = "、".join(earlier) or "申报记录里没有别的年份"
    if plan:
        values["fy_prior_label"] = fy["labels"][-1]
        values["share_guide_increase"] = (
            f"{mid(plan['current']['diluted_shares_m']) - fy['diluted_shares_m'][-1]:.1f}M 股")
        values["next_buyback"] = f"${plan['next']['buyback_usd_m']:,.0f}M"
        values["buyback_policy"] = plan["current"].get("buyback_policy", "")
        values["fy_label"] = f"{plan['fiscal_year']}E"
        values["fy_margin_mid"] = f"{mid(plan['current']['non_gaap_operating_margin_pct']):.2f}%"
        if "raise_revenue" in plan:
            values["raise_revenue"] = f"${plan['raise_revenue']:,.0f}M"
            values["raise_operating_income"] = f"${plan['raise_oi']:,.0f}M"
        if "remainder_margin" in plan:
            values["remainder"] = plan["remainder_word"]
            values["implied_margin"] = f"{plan['remainder_margin']:.2f}%"
            if plan["ytd_margin"] is not None:
                values["implied_vs_ytd"] = f"{plan['ytd_margin'] - plan['remainder_margin']:.1f}pp"
    if peer is not None:
        values["peer_china_share"] = f"{peer['china_share']:.0f}%"

    # Last quarter's lines, each read against this quarter's series; this
    # quarter's, against the same series as it stands now. A typed value in
    # either block would be a second copy free to disagree with the series.
    lines_by_era = {}
    for era, block in (("prior", prior_kpi), ("next", next_kpi)):
        lines_by_era[era] = []
        for entry in (block or {}).get("quantified", []):
            if "current" in entry or "actual" in entry:
                raise ValueError(f"threshold {entry.get('id')!r} carries a typed value: every reading is "
                                 "computed from the series")
            reading = read_line(staging, guidance, entry)
            lines_by_era[era].append({**entry, "reading": reading, "verdict": line_verdict(entry, reading)})
    prior_lines, next_lines = lines_by_era["prior"], lines_by_era["next"]
    for line in prior_lines:
        values[f"prior_threshold:{line['id']}"] = line_amount(line["unit"], line["threshold"], line.get("digits"))
        values[f"prior_actual:{line['id']}"] = line["reading"].get("text", "—")
    # The figures the follow-up evidence quotes, read from the series.
    values["china_share_int"] = f"{qp['geo_china'][-1]:.0f}%"
    values["china_yoy_filed"] = f"{china_yoy[-1]:+.1f}%"
    research = q["research_and_development"]
    values["rnd"] = f"${research[-1]:,.1f}M"
    values["rnd_yoy"] = f"{pct_change(research[-1], research[-5]):+.1f}%"
    values["rnd_ratio"] = f"{research[-1] / revenue[-1] * 100:.1f}%"
    values["rnd_ratio_prior"] = f"{research[-2] / revenue[-2] * 100:.1f}%"
    if plan:
        values["fy_ocf"] = spaced(plan["current"]["operating_cash_flow_usd_m"])
        if plan["previous"] is not None and "operating_cash_flow_usd_m" in plan["previous"]:
            values["prev_fy_ocf"] = money_range(plan["previous"]["operating_cash_flow_usd_m"])

    def told(key: str, default: str = "") -> str:
        text = story_or.get(key)
        return fill_story(text, values) if text else default

    source = (
        f'Source: <a href="{ir["url"]}" '
        f'rel="noopener">Cadence Investor Relations</a>（{period} 业绩 8-K 的新闻稿与 CFO Commentary；'
        '历史季度经 SEC EDGAR 的 10-Q / 10-K 与历次 8-K 回源）。'
    )

    def source_note(detail: str) -> str:
        return f"{detail}；历史期同口径。自算项目均可在核对表中复核。"

    company_words = None
    if company_growth is not None:
        company_words = (f"Core EDA +{company_growth['core_eda_yoy']:.0f}%、"
                         f"IP「超过 {company_growth['semiconductor_ip_yoy_floor']:.0f}%」、"
                         f"SD&A +{company_growth['system_design_analysis_yoy']:.0f}%")
    MIX_PROVENANCE = (
        "公司只披露产品线与地域的<b>收入占比整数百分位</b>，不披露分部金额，"
        "因此本图金额均为占比 × 当季总收入的自算值，"
        f"含 ±${revenue[-1] * 0.005:.0f}M 量级的四舍五入误差"
        + (f"；公司自己给的同比口径（{company_words}）与占比法互有出入，两者都列在核对表里。"
           if company_words else "。")
    )

    # ── section one: settle what was set last quarter ───────────────────────
    # Last quarter's book-to-bill hurdle, when the ratio's own rounding band
    # straddles it: the sentences that explain the band name it.
    btb_undecided = next((line for line in prior_lines
                          if line["reads"] == "book_to_bill" and line["verdict"] == UNDECIDED), None)

    settled_charts = []
    closure_table = None
    if closure is not None:
        items = closure["items"]
        verdicts = closure["labels"]
        counts = [sum(1 for item in items if item["verdict"] == label) for label in verdicts]
        stray = sorted({item["verdict"] for item in items} - set(verdicts))
        if stray or 0 in counts:
            raise ValueError(f"series block `followup_closure`: verdicts {stray} have no label, or a "
                             "label counts no question -- the labels are the verdicts the analysis used")
        settled_charts.append({
            "kind": "bars_labeled",
            "title": f"上季 {len(items)} 条待验证问题：" + "、".join(
                f"{count} 条{label}" for label, count in zip(verdicts, counts)),
            "xlabels": verdicts,
            "values": counts,
            "legend": "问题条数",
            "fmt": "f0",
            "yfmt": "f0",
            "label_fmt": "f0",
            "ylab": "条",
            "note": ((fill_story(closure["falsified_item"], values) + "。" if closure.get("falsified_item") else "")
                     + closure["rule"] + closure.get("calibration", "")),
            "src_extra": (
                f"问题原文：上季（{closure['set_in']}）本站季报分析文末的 Follow-up；判定照录本季分析第 0 节"
                "「验证结果」栏，逐条的原文判定、本页归类与证据见核对抽屉。" + closure.get("checked", "")
            ),
        })
        closure_table = {
            "n": 0,
            "title": f"上季 {len(items)} 条待验证问题与本季判定",
            "headers": ["#", "上季问题", "本季分析第 0 节的判定（原文）", "本页归类", "本季证据"],
            "rows": [[str(i), item["question"], item["verdict_text"], item["verdict"],
                      fill_story(item["evidence"], values)] for i, item in enumerate(items, 1)],
        }

    prior_table = None
    if prior_kpi is not None:
        section_rows = prior_kpi["rows"]
        unsettled = prior_kpi.get("unsettled", [])
        accounted = ({line["row"] for line in prior_lines if line.get("row")}
                     | {item["row"] for item in unsettled})
        if accounted != set(range(1, section_rows + 1)):
            raise ValueError(f"series block `prior_kpi_settlement`: section-8 rows {sorted(accounted)} of "
                             f"{section_rows} are accounted for -- every row is either settled or explained")
        judged = [line for line in prior_lines if line["verdict"] in SETTLED]
        bars = [line for line in judged if line["threshold"] != 0]
        charts, undrawn = line_charts(staging, guidance, prior_lines, "上季")
        from_table = [line for line in prior_lines if not line.get("row")]
        origin_words = (
            f"阈值与方向逐字取自上季（{prior_kpi['set_in']}）本站季报分析第 8 节的{cn_count(section_rows)}行"
            + (f"；另有{cn_count(len(from_table))}条（" + "、".join(line_label(line) for line in from_table)
               + "）写在同一份分析第 1 节 Bull / Base / Bear 三档假设的「验证指标」列，本季分析第 8 节"
               "「上季 KPI 校准」把它们与第 8 节一并结算，本页照收并在核对表里标明出处" if from_table else "")
            + "。"
        )
        zero_words = "".join(
            f"「{line_label(line)}」的阈值是 0，没有百分比余量可算，不进这张图：本季 "
            f"{line['reading']['text']}，{line['verdict']}。"
            for line in judged if line["threshold"] == 0)
        open_words = "".join(open_line_words(line) for line in prior_lines if line["verdict"] not in SETTLED)
        row_words = "".join(
            f"第 8 节第{cn_ordinal(item['row'])}行（{item['text']}）<b>无法结算</b>：{item['why']}。"
            for item in sorted(unsettled, key=lambda item: item["row"]))
        overview = headroom_exhibit(
            f"上季 {len(bars)} 条量化阈值：" + kind_words(bars),
            [{"metric": line_label(line), "direction": line_direction(line),
              "threshold": line["threshold"], "actual": line["reading"]["value"]} for line in bars],
            "actual",
            ("正值 = 守住或达到，负值 = 越线或没到。" + origin_words + zero_words + open_words + row_words
             + (f"有序列可画的{cn_count(len(charts))}个读数各画一张图（Exhibit "
                + "、".join("{" + chart["ref"] + "}" for chart in charts) + "）。" if charts else "")
             + "".join(undrawn)),
            src_extra=(f"实际值为 {period} 的申报值或据申报自算（D）；逐条的出处、读数与本季分析的处置见核对抽屉。"),
        )
        # round() keeps the sign of zero, and −0.0 prints as "-0.0%" on the bar.
        overview["values"] = [value + 0.0 for value in overview["values"]]
        overview["positive_label"] = "守住 / 达到"
        overview["negative_label"] = "越线 / 没到"
        settled_charts += [overview] + charts
        prior_rows = []
        for line in prior_lines:
            reading = line["reading"]
            band = reading.get("range")
            prior_rows.append([
                row_text(line),
                line_label(line),
                reading.get("text", "—") + (f"（区间 {reading['show'](band[0])}–{reading['show'](band[1])}）"
                                            if band else ""),
                (margin_text(headroom(line_direction(line), line['threshold'], reading['value']))
                 if line["verdict"] in SETTLED and line["threshold"] != 0 else "—"),
                line["verdict"],
                line.get("disposition", "—"),
            ])
        prior_rows += [[f"第 8 节第{cn_ordinal(item['row'])}行", item["text"], "—", "—", "无法结算", item["why"]]
                       for item in sorted(unsettled, key=lambda item: item["row"])]
        prior_table = {
            "n": 0,
            "title": "上季阈值与本季读数（原单位）",
            "headers": ["出处", "阈值", "本季读数", "余量 D", "结果", "本季分析的处置 / 无法结算的原因"],
            "rows": prior_rows,
        }
    settled_charts += guidance_delivery_charts(staging, story)

    # ── section two: what actually moved ────────────────────────────────────
    services_yoy = pct_change(services[-1], shown(q["revenue_services"])[-5])
    position = ("，但落在指引区间之内而不是之上" if inside_guide else
                "，高于指引上限" if revenue[-1] > quarter_guide_high else "，低于指引下限")
    if round(versus_mid, 1) == 0:
        versus_words = "与中值持平"
    elif versus_mid > 0:
        versus_words = ("仅高出中值 " if inside_guide else "高出中值 ") + signed(versus_mid)
    else:
        versus_words = "低于中值 " + signed(versus_mid)
    next_words = ""
    if plan:
        qoq = plan["nq_qoq"]
        next_words = (
            f"下季指引中值 ${plan['nq_revenue']:,.0f}M "
            + (f"隐含同比 {signed(plan['nq_yoy'])}、" if "nq_yoy" in plan else "")
            + f"环比{'仅' if 'nq_yoy' in plan and abs(qoq) < abs(plan['nq_yoy']) / 4 else ''} {signed(qoq)}。"
        )
    # The acquisition is inside the reported growth; the 10-Q's pro forma
    # revenue (as if D&E had been owned in both periods) is the one filed
    # figure that takes it out of the comparison. No organic rate is filed.
    pro_forma = stamped_block(staging, "pro_forma_revenue_usd_m", period)
    pro_forma_words = ""
    if pro_forma is not None:
        if abs(pro_forma["three_months"][0] - revenue[-1]) > 0.001:
            raise ValueError("`pro_forma_revenue_usd_m` must open with this quarter's reported revenue")
        quarter_word, year_word = display_period(period).split()
        if pro_forma["labels"] != [f"{quarter_word} {year_word}", f"{quarter_word} {int(year_word) - 1}"]:
            raise ValueError("`pro_forma_revenue_usd_m.labels` must be this quarter and the same quarter a year earlier")
        pro_forma_words = (
            f"同比 {revenue_yoy[-1]:.1f}% 里含 Hexagon D&E 的并表：10-Q 附注 2 的备考收入（假设 D&E 两期都已并入）"
            f"同比是 {signed(pct_change(*pro_forma['three_months']))}，公司没有单独披露剔除并购的有机增速。")
    highlights = [
        {
            "kind": "gs_bar",
            "title": f"收入 ${revenue_shown[-1]:,.0f}M、同比 {revenue_yoy[-1]:.1f}%" + position,
            "xlabels": long_labels,
            "xstep": LONG_STEP,
            "values": long_revenue,
            "legend": "总收入",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "ylab2": "同比增速",
            "yoy": {
                "name": "同比增速 (RHS)",
                "values": long_revenue_yoy,
                "color": "GREEN",
                "yfmt": "pct1",
            },
            "note": (
                # The size of the ASC 605/606 step is fixed history: 2018Q1 was
                # printed under both standards (2018-04-23 CFO Commentary).
                "<b>这条柱子跨着一道准则的坎。</b>Cadence 2018 财年首日以 modified "
                "retrospective 采用 ASC 606，2017 及以前不重述 —— 2018Q1 在两套准则下都被"
                "披露过，所以坎有多高是量得出来的：收入 525.5（605）对 517.3（606）。"
                "同比线在 2018 那四季因此跨基数，读它要连着这句话一起读。"
                f"本季指引区间 ${quarter_guide_low:,.0f}–{quarter_guide_high:,.0f}M，"
                f"实际 ${revenue_shown[-1]:,.0f}M，{versus_words}（区间与实际见 Exhibit {{EX_REV_RANGE}}）；"
                + next_words
                + pro_forma_words
                + f"服务收入同比 {signed(services_yoy)}"
                + (f"，{story_or['services']}。" if story_or.get("services") else "。")
            ),
            "src_extra": source_note(
                "收入来自各期 10-Q / 10-K 与本季新闻稿损益表；同比与环比为自算"),
        },
    ]

    company_gap = None
    if company_growth is not None:
        gaps = {"Core EDA": abs(core_eda_yoy - company_growth["core_eda_yoy"]),
                "SD&A": abs(system_design_yoy - company_growth["system_design_analysis_yoy"])}
        widest = max(gaps, key=gaps.get)
        company_gap = f"——与公司口径的差在 {widest} 上最大（{gaps[widest]:.0f}pp），因此本页两套数都列，不在两者间取舍。"
    growth_now = ([company_growth["semiconductor_ip_yoy_floor"], company_growth["core_eda_yoy"],
                   company_growth["system_design_analysis_yoy"]] if company_growth is not None
                  else list(derived_growth.values()))
    diverge = "的分化" if max(growth_now) - min(growth_now) >= 5 else ""
    highlights.append({
        "kind": "lines",
        "title": (
            f"三条产品线{diverge}：公司口径 Semiconductor IP"
            f"「超过 {company_growth['semiconductor_ip_yoy_floor']:.0f}%」、"
            f"Core EDA +{company_growth['core_eda_yoy']:.0f}%、"
            f"SD&A +{company_growth['system_design_analysis_yoy']:.0f}%"
            if company_growth is not None else
            f"三条产品线{diverge}（按整数占比自算）：Semiconductor IP {ip_yoy:+.0f}%、"
            f"Core EDA {core_eda_yoy:+.0f}%、SD&A {system_design_yoy:+.0f}%"
        ),
        "xlabels": category_labels,
        "series": [
            {"name": "Core EDA D", "values": core_eda, "color": "NAVY"},
            {"name": "System Design & Analysis D", "values": system_design, "color": "MBLUE"},
            {"name": "Semiconductor IP D", "values": semiconductor_ip, "color": "GOLD"},
        ],
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "zero_base": True,
        "end_label": True,
        "ylab": "$M",
        "note": (
            f"按整数占比反推，同期 IP {ip_yoy:+.0f}%、Core EDA {core_eda_yoy:+.0f}%、"
            f"SD&A {system_design_yoy:+.0f}%"
            + (company_gap or "。")
            + told("mix")
        ),
        "src_extra": MIX_PROVENANCE,
    })

    # The analysis' headline evidence is a gap between two companies' IP growth.
    # Synopsys's side is its filed segment revenue; the quarter the analysis
    # used and the quarter the site's calendar pairs with Cadence's are both
    # drawn, because the second was filed after the analysis was written and
    # narrows the gap.
    peers = stamped_block(staging, "peer_ip_growth", period)
    if peers is not None:
        months = {1: "1–3 月", 2: "4–6 月", 3: "7–9 月", 4: "10–12 月"}[quarter_number]
        rows = [(f"Cadence IP（{months}，占比法 D）", ip_yoy)] + [
            (f"{peers['peer']} Design IP（{row['months']}）", pct_change(*row["design_ip_usd_m"]))
            for row in peers["quarters"]]
        compared = [row for row in peers["quarters"] if row.get("analysis_compared")]
        later = [row for row in peers["quarters"] if not row.get("analysis_compared")]
        floor = company_growth["semiconductor_ip_yoy_floor"] if company_growth is not None else None
        peer_words = "、".join(minus_sign(f"{pct_change(*row['design_ip_usd_m']):+.1f}%") + f"（{row['months']}）"
                               for row in peers["quarters"])
        highlights.append({
            "kind": "diverging_bars",
            "title": ((f"IP 同比：Cadence「超过 {floor:.0f}%」" if floor is not None else f"IP 同比：Cadence {ip_yoy:+.0f}%")
                      + f"，{peers['peer']} Design IP 同期 {peer_words}"),
            "xlabels": [label for label, _ in rows],
            "values": [round(value, 1) for _, value in rows],
            "legend": "同比增速",
            "positive_label": "同比增长",
            "negative_label": "同比下降",
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "ylab": "同比 %",
            "zero_line": True,
            "note": (
                "本站季报分析拿来说「份额转移」的是 Cadence 与 "
                + "、".join(f"{peers['peer']} {row['months']}（{row['period_end']} 止）" for row in compared)
                + "的对照，差约 " + "、".join(f"{ip_yoy - pct_change(*row['design_ip_usd_m']):.0f}pp" for row in compared)
                + "——那是分析写成时对方最新的一季。两家财季错开："
                + "；".join(f"{row['months']}那一季 {row['filed_on']} 才申报，与 Cadence {months}重叠更多，"
                           f"Design IP 同比 {pct_change(*row['design_ip_usd_m']):+.1f}%，差距收窄到约 "
                           f"{ip_yoy - pct_change(*row['design_ip_usd_m']):.0f}pp" for row in later)
                + "。Cadence 这一根是整数占比反推，精度约 ±"
                f"{(ip_high - ip_low) / 2:.0f}pp" + (f"，公司自己的说法是「超过 {floor:.0f}%」" if floor is not None else "")
                + f"；{peers['peer']} 的 Design Automation 自 2025 年 7 月起含 Ansys，与 Core EDA 不可比，这里不画。"
            ),
            "src_extra": ("Cadence：CFO Commentary 的产品线整数占比 × 10-Q 总收入，自算（D）；"
                          + "；".join(f"{peers['peer']} {row['months']}：{row['source']}" for row in peers["quarters"])
                          + "；同比为自算。"),
        })

    china_values = {
        "china_yoy_by_share": f"{china_share_yoy_by_share:+.0f}%",
        "china_yoy_filed": f"{china_yoy[-1]:+.1f}%",
    }
    highlights.append({
        "kind": "gs_bar",
        "title": (
            f"中国收入 ${china_revenue[-1]:,.0f}M、同比 {china_yoy[-1]:+.1f}%——"
            + (f"仍低于 {china_peak_quarter} 的 ${china_peak:,.0f}M" if not china_is_peak
               else f"{len(china_revenue)} 季里最高")
        ),
        "xlabels": china_labels,
        "values": china_revenue,
        "legend": "中国收入（申报值）",
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "$M",
        "ylab2": "占总收入",
        "yoy": {
            "name": "占总收入 (RHS) D",
            "values": china_share_exact,
            "color": "RED",
            "yfmt": "pct1",
        },
        "note": told("china", (
            f"去年同期 ${q['china_revenue'][-5]:,.0f}M，本季"
            + (f"仍低于 {china_peak_quarter} 的 ${china_peak:,.0f}M。" if not china_is_peak
               else "为全序列最高。")
        )),
        "src_extra": fill_story(staging["china_provenance"], china_values),
    })

    gross_gap_verb = ("张到" if round(amortisation_drag[-1], 1) > round(amortisation_drag[-5], 1) else
                      "收窄到" if round(amortisation_drag[-1], 1) < round(amortisation_drag[-5], 1) else "持平于")
    gross_yoy = non_gaap_gross[-1] - non_gaap_gross[-5]
    gaap_turns = verb_to(gaap_gross[-2], gaap_gross[-1])
    non_gaap_turns = verb_to(non_gaap_gross[-2], non_gaap_gross[-1])
    highlights.append({
        "kind": "lines",
        "title": (
            f"GAAP 毛利率{gaap_turns} {gaap_gross[-1]:.1f}%，非 GAAP 毛利率"
            f"{'反而' if gaap_turns != non_gaap_turns else ''}{non_gaap_turns} {non_gaap_gross[-1]:.1f}%"
        ),
        "xlabels": labels,
        "series": [
            {"name": "非 GAAP 毛利率", "values": non_gaap_gross, "color": "NAVY"},
            {"name": "GAAP 毛利率", "values": gaap_gross, "color": "MBLUE"},
            {"name": "两者之差（主要是无形资产摊销）D", "values": amortisation_drag, "color": "RED"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "毛利率",
        "note": (
            f"两条线的缺口从 {amortisation_drag[-5]:.1f}pp {gross_gap_verb} {amortisation_drag[-1]:.1f}pp"
            + (f"，{told('gross_margin_cause')}" if story_or.get("gross_margin_cause") else "。")
            + (f"<b>只看 GAAP 会得出「产品结构恶化」的结论，而底层毛利率同比是 {gross_yoy:+.1f}pp</b>"
               if gaap_gross[-1] < gaap_gross[-5] and gross_yoy > 0 else
               f"底层毛利率同比 {gross_yoy:+.1f}pp")
            + (told("gross_margin_tail") if story_or.get("gross_margin_tail") else "。")
        ),
        "src_extra": (
            "GAAP 与非 GAAP 毛利率均为公司在各季 CFO Commentary 披露值；"
            "两者之差为自算，其构成以无形资产摊销为主，另含少量股权激励与并购整合费用。"
        ),
    })

    margin = facts_record["margin"]
    if plan and "remainder_margin" in plan:
        remainder = plan["remainder_margin"]
        rest_word = REST_WORDS.get(quarter_number, "全年") if plan["done"] else "全年"
        next_quarter_word = plan["next_period"].split()[0]
        giveback_words = ""
        if plan["ytd_margin"] is not None:
            giveback_words = (
                f"若{rest_word}只是维持{ytd_word}的 {plan['ytd_margin']:.2f}%，将"
                f"{'多出' if plan['giveback'] >= 0 else '少'} ${abs(plan['giveback']):,.0f}M 经营利润"
                + (f"；{told('giveback')}" if story_or.get("giveback") else "。")
            )
        highlights.append({
            "kind": "lines",
            "title": (
                f"本季非 GAAP 营业利润率 {non_gaap_margin[-1]:.1f}%，"
                f"而全年指引隐含的 {plan['remainder_word']} "
                f"{'只有' if remainder < non_gaap_margin[-1] else '为'} {remainder:.2f}%"
            ),
            "xlabels": labels + [f"{plan['next_label']}E", plan["remainder_label"]],
            "series": [
                {
                    "name": "非 GAAP 营业利润率",
                    "values": non_gaap_margin + [None, None],
                    "color": "NAVY",
                },
                {
                    "name": "下季指引中值 / 全年指引隐含 D",
                    "values": [None] * (WINDOW - 1) + [non_gaap_margin[-1], plan["nq_margin"], remainder],
                    "color": "GOLD",
                },
                {
                    "name": "GAAP 营业利润率",
                    "values": gaap_margin + [None, None],
                    "color": "GRAY",
                },
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "end_label": True,
            "ylab": "营业利润率",
            "note": (
                f"算式全部是申报值：全年非 GAAP 营业利润中值 ${plan['fy_oi']:,.0f}M "
                + (f"− {ytd_word}实际 ${plan['ytd_oi']:,.0f}M = {rest_word} ${plan['rest_oi']:,.0f}M"
                   f"（{plan['rest_margin']:.2f}%），" if plan["done"] else "，")
                + f"再减去 {next_quarter_word} 指引中值隐含的 ${plan['nq_oi']:,.0f}M，"
                f"剩下的 {plan['remainder_word']} 就是 {remainder:.2f}%。"
                + (f"<b>这个数{peer_clause()}</b>"
                   + (f"——{fill_story(peer['why'], values)}。" if peer["why"] else "。")
                   if peer is not None else "")
                + giveback_words
            ),
            "src_extra": (
                f"实际值为公司披露的季度非 GAAP 营业利润率；{plan['next_label']}E 为公司指引区间中值，"
                f"{plan['remainder_label']} 为全年指引中值扣除{ytd_word + '实际与 ' if plan['done'] else ''}"
                f"{next_quarter_word} 指引后的隐含值（自算 D，无估计成分）。"
                "口径提示：这条线与 Exhibit {EX_MARGIN_DEV} 的偏离序列同源，"
                f"该序列显示公司在 {len(margin['rows'])} 个已完结季里有 {len(margin['above'])} 季高于自己的指引上限。"
            ),
        })

    cash_note = f"{ytd_word}经营现金流 ${ytd_ocf:,.1f}M，"
    if plan:
        cur, prev = plan["current"], plan["previous"]
        if prev is not None and "operating_cash_flow_usd_m" in prev:
            moved = mid(cur["operating_cash_flow_usd_m"]) - mid(prev["operating_cash_flow_usd_m"])
            cash_note += (f"全年指引由{spaced(prev['operating_cash_flow_usd_m'])} "
                          f"{'上修到' if moved > 0 else '下修到' if moved < 0 else '维持在'}"
                          f"{spaced(cur['operating_cash_flow_usd_m'])}。")
        else:
            cash_note += f"全年经营现金流指引 {money_range(cur['operating_cash_flow_usd_m'])}。"
        prior_year = fy["labels"][-1]
        prior_capex = fy["capital_expenditures_usd_m"][-1]
        capex_guide = mid(cur["capital_expenditures_usd_m"])
        capex_change = pct_change(capex_guide, prior_capex)
        cash_note += (
            f"资本开支同比 {signed(pct_change(capex[-1], capex[-5]))}，"
            + (f"全年口径约 ${capex_guide:,.0f}M" if not isinstance(cur["capital_expenditures_usd_m"], list)
               else f"全年口径 {money_range(cur['capital_expenditures_usd_m'])}")
            + f"，较 {prior_year} 年的 ${prior_capex:,.0f}M {'增' if capex_change >= 0 else '减'} "
            f"{abs(capex_change):.0f}%"
            + (f"——{told('capex')}" if story_or.get("capex") else "。")
        )
    else:
        cash_note += f"资本开支同比 {signed(pct_change(capex[-1], capex[-5]))}。"
    highlights.append({
        "kind": "grouped_bars",
        "title": (
            f"经营现金流 ${operating_cash_flow[-1]:,.0f}M、同比 "
            f"{signed(pct_change(operating_cash_flow[-1], operating_cash_flow[-5]))}"
            + (f"，{story_or['cash_verdict']}" if story_or.get("cash_verdict") else "")
        ),
        "xlabels": labels,
        "groups": [
            {"name": "经营现金流", "values": operating_cash_flow, "color": "NAVY"},
            {"name": "自由现金流 D", "values": free_cash_flow, "color": "BLUE"},
            {"name": "资本开支", "values": capex, "color": "GRAY"},
        ],
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "bar_labels": False,
        "ylab": "$M",
        "note": cash_note,
        "src_extra": source_note(
            "经营现金流与资本开支逐季来自各期现金流量表（10-Q 只按年初至今披露，"
            "逐季由相邻两个年初至今值相减，财政第四季为全年 − 前三季）；自由现金流为两者之差"),
    })

    def moved_twice(values_list: list[float]) -> str:
        a, b, c = (round(v, 2) for v in values_list[-3:])
        return "连续两季走低" if a > b > c else "连续两季走高" if a < b < c else ""

    cov_now, cov_year_ago = round(coverage[-1], 2), round(coverage_all[-5], 2)
    trend = moved_twice(coverage)
    versus_year = ("高于" if cov_now > cov_year_ago else "低于" if cov_now < cov_year_ago else "持平于")
    # The analysis reads the multiple sequentially (two quarters down); the
    # record says the multiple falls in most first halves, so the same-quarter
    # comparison is printed beside it rather than instead of it.
    against = (trend == "连续两季走低" and versus_year == "高于") or (trend == "连续两季走高" and versus_year == "低于")
    seasonal_words = threshold_reading(staging, guidance, "coverage")["note"]
    highlights.append({
        "kind": "gs_bar",
        "title": (
            f"backlog {'创纪录的 ' if backlog_record else ''}US${backlog[-1]:.1f}B，"
            f"覆盖倍数{trend + '到 ' if trend else ' '}{coverage[-1]:.2f}x，"
            f"{'但' if against else ''}{versus_year}去年同期的 {coverage_all[-5]:.2f}x"
        ),
        "xlabels": labels,
        "values": backlog,
        "legend": "季末 backlog",
        "fmt": "usd1",
        "yfmt": "usd1",
        "label_fmt": "usd1",
        "ylab": "US$B",
        "ylab2": "覆盖倍数",
        "yoy": {
            "name": "backlog / 过去四季收入 (RHS) D",
            "values": coverage,
            "color": "RED",
            "yfmt": "f2",
        },
        "note": (
            f"绝对额{'是历史最高' if backlog_record else '不是历史最高'}，覆盖倍数 {coverage[-3]:.2f}x → {coverage[-2]:.2f}x → "
            f"{coverage[-1]:.2f}x {trend}".rstrip() + "。"
            + (f"<b>环比走低本身说明不了什么</b>——{seasonal_words}" if seasonal_words else "")
            + f"同一季度的对照：本季 {coverage[-1]:.2f}x，去年同期 {coverage_all[-5]:.2f}x"
            + (f"，前年同期 {coverage_all[-9]:.2f}x。" if len(coverage_all) >= 9 and coverage_all[-9] is not None
               else "。")
            + told("backlog_news")
            + f"本季隐含 book-to-bill 的中枢读数是 "
            f"{book_to_bill:.2f}x，但 backlog 只披露到 US$0.1B，两季相减后的区间是 "
            f"{btb_range}——这个比率因此只能当方向看，不能当阈值判"
            + (f"，上季 {btb_undecided['reading']['show'](btb_undecided['threshold'])} 那条达标线因此判为无法判定。"
               if btb_undecided else "。")
        ),
        "src_extra": (
            "backlog 为公司在各季 CFO Commentary 披露值，精度到 US$0.1B，"
            "2020Q1 起逐季给出、此前只在年末给出；"
            "覆盖倍数与 book-to-bill 为自算，后者受 backlog 只到 US$0.1B 的精度限制。"
        ),
    })

    fixed_run = 1
    while (fixed_run < len(buybacks)
           and round(buybacks[-1 - fixed_run]) == round(buybacks[-fixed_run])):
        fixed_run += 1
    shares_note = ""
    if plan:
        shares_mid = mid(plan["current"]["diluted_shares_m"])
        prior_shares = fy["diluted_shares_m"][-1]
        low_shares, high_shares = plan["current"]["diluted_shares_m"]
        shares_note = (f"全年摊薄股数指引 {low_shares:.1f}–{high_shares:.1f}M，"
                       f"{'高于' if shares_mid > prior_shares else '低于'} {fy['labels'][-1]} 年的 {prior_shares:.1f}M。")
    sbc_flat = round(sbc_ratio[-1], 1) == round(sbc_ratio[-5], 1)
    highlights.append({
        "kind": "gs_bar",
        "title": (
            f"单季回购 ${buybacks[-1]:,.0f}M，摊薄股数"
            + ("却升到" if diluted_shares[-1] > diluted_shares[-2] else "降到")
            + f" {diluted_shares[-1]:.1f}M"
        ),
        "xlabels": labels,
        "values": buybacks,
        "legend": "单季回购金额",
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "$M",
        "ylab2": "摊薄股数",
        "yoy": {
            "name": "摊薄股数 (RHS)",
            "values": diluted_shares,
            "color": "RED",
            "yfmt": "f1",
        },
        "note": (
            f"本季回购均价 ${buybacks[-1] / buyback_shares[-1]:.0f}/股，"
            f"上季 ${buybacks[-2] / buyback_shares[-2]:.0f}、去年同期 "
            f"${buybacks[-5] / buyback_shares[-5]:.0f}——"
            + ("金额固定、对价格不敏感，股价越高买到的股数越少。" if fixed_run >= 2 else
               "股价越高，同样的金额买到的股数越少。")
            + shares_note
            + told("buyback")
            + f"本季股权激励占收入 {sbc_ratio[-1]:.1f}%，"
            + ("与去年同期持平。" if sbc_flat else f"去年同期 {sbc_ratio[-5]:.1f}%。")
        ),
        "src_extra": (
            "回购金额与股数、摊薄股数均为公司披露值；回购均价为两者相除的自算值。"
            + told("share_note")
        ),
    })

    # ── section three: the same discipline pointed forward ──────────────────
    next_charts = []
    next_table = followup_table = None
    next_section_words = ""
    if next_kpi is not None:
        if period_order(next_kpi["for_period"]) <= period_order(period):
            raise ValueError(f"series block `next_kpi` is written for {next_kpi['for_period']}, "
                             f"which is not after {period}")
        section_rows = next_kpi["rows"]
        not_drawn = next_kpi.get("not_drawn", [])
        accounted = {line["row"] for line in next_lines} | {item["row"] for item in not_drawn}
        if accounted != set(range(1, section_rows + 1)):
            raise ValueError(f"series block `next_kpi`: section-8 rows {sorted(accounted)} of {section_rows} "
                             "are accounted for -- every row is either a line or explained")
        live = [line for line in next_lines if line["verdict"] in SETTLED]
        bars = [line for line in live if line["threshold"] != 0]
        waiting = [line for line in next_lines if line["verdict"] not in SETTLED]
        charts, undrawn = line_charts(staging, guidance, next_lines, "下季", upcoming=next_kpi["for_period"])
        tripped = [line for line in bars if line["verdict"] == BAD_WORDS["guard"]]
        overview = headroom_exhibit(
            f"下季 {len(bars)} 条量化阈值：按本季读数，" + kind_words(bars)
            + (f"，{'、'.join(line_label(line) for line in tripped)} 已经触发" if tripped else ""),
            [{"metric": line_label(line), "direction": line_direction(line),
              "threshold": line["threshold"], "actual": line["reading"]["value"]} for line in bars],
            "actual",
            ("正值 = 按本季读数已在安全一侧或已经达到，负值 = 已越线或还没达到；下季结算时读的是下季的实际值。"
             f"阈值与方向逐字取自本季（{period}）本站季报分析第 8 节。" + next_kpi.get("rows_note", "")
             + "".join(open_line_words(line) for line in waiting)
             + "".join(f"第 8 节第{cn_ordinal(item['row'])}行（{item['text']}）不在总览里：{item['why']}。"
                       for item in not_drawn)
             + (f"有序列可画的{cn_count(len(charts))}个读数各画一张图（Exhibit "
                + "、".join("{" + chart["ref"] + "}" for chart in charts) + "）。" if charts else "")
             + "".join(undrawn)),
            src_extra=(f"当前值为 {period} 的申报值或据申报自算（D），只用来量现在离线多远；"
                       "每条线的出处与报告写的含义见核对抽屉。"),
        )
        overview["values"] = [value + 0.0 for value in overview["values"]]
        overview["positive_label"] = "安全 / 已达到"
        overview["negative_label"] = "越线 / 未达到"
        next_charts = [overview] + charts
        next_section_words = (
            f"本季报告第 8 节的阈值逐条拆成 {len(next_lines)} 条线：{len(bars)} 条有本季读数，总览量它们离线多远，"
            f"每个读数再画一张历史图"
            + (f"；{'、'.join(line_label(line) for line in waiting if line['verdict'] == UNDECIDED)} "
               "落在本季读数的精度区间里，按现在的读数判不了"
               if any(line["verdict"] == UNDECIDED for line in waiting) else "")
            + (f"；{'、'.join(line_label(line) for line in waiting if line['verdict'] == NOT_YET)} 现在还没有读数"
               if any(line["verdict"] == NOT_YET for line in waiting) else "")
            + (f"；另有{cn_count(len(not_drawn))}项不成线" if not_drawn else "")
            + "，都列在核对抽屉。"
            + (f"文末 {len(next_kpi['followups'])} 条追问留到下季第 0 节逐条结算，也列在核对抽屉。"
               if next_kpi.get("followups") else "")
        )
        next_table = {
            "n": 0,
            "title": "下季阈值与本季读数（原单位）",
            "headers": ["出处", "阈值", "本季读数", "余量 D", "按本季读数", "报告写的含义"],
            "rows": [[row_text(line), line_label(line),
                      line["reading"].get("text", "—")
                      + (f"（区间 {line['reading']['show'](line['reading']['range'][0])}–"
                         f"{line['reading']['show'](line['reading']['range'][1])}）"
                         if line["reading"].get("range") else ""),
                      (margin_text(headroom(line_direction(line), line['threshold'], line['reading']['value']))
                       if line["verdict"] in SETTLED and line["threshold"] != 0 else "—"),
                      line["verdict"], line.get("meaning", "—")] for line in next_lines]
            + [[f"第 8 节第{cn_ordinal(item['row'])}行", item["text"], "—", "—", "不成线", item["why"]]
               for item in not_drawn],
        }
        if next_kpi.get("followups"):
            # A question the filings have already answered says so, with the
            # figures read from the series; the rest wait for next quarter.
            answered = next_kpi.get("answered", {})
            if set(answered) - {str(i) for i in range(1, len(next_kpi["followups"]) + 1)}:
                raise ValueError("`next_kpi.answered` names a follow-up that does not exist")
            followup_table = {
                "n": 0,
                "title": f"本季分析文末 {len(next_kpi['followups'])} 条追问（下季第 0 节逐条结算）",
                "headers": ["#", "追问", "申报里已有的答案"],
                "rows": [[str(i), text, fill_story(answered[str(i)], values) if str(i) in answered else "—"]
                         for i, text in enumerate(next_kpi["followups"], 1)],
            }

    # ── section four: the routine series chosen for this company ────────────
    guided_year = None
    if plan and str(plan["fiscal_year"] - 1) == fy["labels"][-1]:
        guided_year = plan["current"]
    fy_labels = fy["labels"] + ([f"{plan['fiscal_year']}E"] if guided_year else [])
    fy_gaap_margin = fy["gaap_operating_margin_pct"] + (
        [mid(guided_year["gaap_operating_margin_pct"])] if guided_year else [])
    fy_non_gaap_margin = fy["non_gaap_operating_margin_pct"] + (
        [mid(guided_year["non_gaap_operating_margin_pct"])] if guided_year else [])
    fy_sbc = fy["stock_based_compensation_pct_of_revenue"] + (
        [guided_year["stock_based_compensation_pct_of_revenue"]] if guided_year else [])
    fy_ex_sbc = fy["non_gaap_operating_margin_ex_sbc_pct"] + (
        [guided_year["non_gaap_operating_margin_ex_sbc_pct"]] if guided_year else [])
    fy_backlog = fy["year_end_backlog_usd_bn"]
    fy_revenue = fy["revenue_usd_m"]
    fy_coverage = [
        None if level is None else level * 1000 / total
        for level, total in zip(fy_backlog, fy_revenue)
    ]
    actual_years = len(fy["labels"])
    ten = cn_count(actual_years)
    e_label = fy_labels[-1] if guided_year else None
    last_year = fy["labels"][-1]

    def climbs(values_list: list[float]) -> int:
        """Consecutive year-on-year rises ending at the last value."""
        run = 0
        while run + 1 < len(values_list) and values_list[-1 - run] > values_list[-2 - run]:
            run += 1
        return run

    ngm_actual = fy["non_gaap_operating_margin_pct"]
    ngm_rises = climbs(ngm_actual)
    ngm_ever_fell = any(b < a for a, b in zip(ngm_actual, ngm_actual[1:]))
    gaap_actual = fy["gaap_operating_margin_pct"]
    gaap_peak = max(gaap_actual)
    gaap_peak_year = fy["labels"][gaap_actual.index(gaap_peak)]
    gaap_falls = 0
    while (gaap_falls + 1 < len(gaap_actual)
           and gaap_actual[-1 - gaap_falls] < gaap_actual[-2 - gaap_falls]):
        gaap_falls += 1
    gap_by_year = [n - g for n, g in zip(ngm_actual, gaap_actual)]
    widening = climbs(gap_by_year)
    steps = [gap_by_year[-1 - k] - gap_by_year[-2 - k] for k in range(widening)][::-1]
    accelerating = widening >= 2 and all(b > a for a, b in zip(steps, steps[1:]))

    margin_title = f"利润率{ten}年：非 GAAP 从 {fy_non_gaap_margin[0]:.0f}% 升到 {ngm_actual[-1]:.1f}%"
    margin_note = (f"非 GAAP 口径连续{cn_count(ngm_rises)}年上行" if ngm_rises else "非 GAAP 口径上一年没有上行")
    if guided_year:
        e_ngm = fy_non_gaap_margin[-1]
        falls = e_ngm < ngm_actual[-1]
        margin_title += (f"，{e_label} 却是{ten}年里第一次同比下降" if falls and not ngm_ever_fell else
                         f"，{e_label} 同比下降" if falls else f"，{e_label} 继续上行")
        margin_note += (
            f"，{e_label} 中值 {e_ngm:.2f}% 是这条线"
            + (f"<b>{ten}年里第一次同比走低</b>" if falls and not ngm_ever_fell else
               "同比走低" if falls else "继续走高")
            + f"（{last_year} 年为 {ngm_actual[-1]:.1f}%）。"
        )
    else:
        margin_note += "。"
    e_gaap = fy_gaap_margin[-1] if guided_year else None
    margin_note += (
        f"GAAP 口径在 {gaap_peak_year} 年见顶 {gaap_peak:.1f}% 后回落了{cn_count(gaap_falls)}年"
        if gaap_falls and gaap_peak_year != last_year else
        f"GAAP 口径 {last_year} 年为 {gaap_actual[-1]:.1f}%"
    )
    if guided_year:
        margin_note += (f"（{e_label} 中值 {e_gaap:.2f}%，比 {last_year} 年"
                        f"{'高' if e_gaap > gaap_actual[-1] else '低'} {abs(e_gaap - gaap_actual[-1]):.2f}pp）")
    if widening:
        # Widening since the first year of the run; accelerating from the year
        # whose step first exceeds the one before it.
        run_years = fy["labels"][-widening:]
        margin_note += (f"，两条线的缺口自 {run_years[1] if accelerating else run_years[0]} 年起"
                        f"{'加速' if accelerating else ''}张开——那是并购摊销与整合费用累积的结果。")
    else:
        margin_note += "。"
    margin_note += told("margin_promise")

    ex_sbc_actual = fy["non_gaap_operating_margin_ex_sbc_pct"]
    ex_sbc_ever_fell = any(b < a for a, b in zip(ex_sbc_actual, ex_sbc_actual[1:]))
    sbc_actual_path = fy_sbc
    sbc_dips = [fy_labels[i] for i in range(1, len(sbc_actual_path)) if sbc_actual_path[i] < sbc_actual_path[i - 1]]
    sbc_title = (f"扣掉股权激励之后：SBC 占收入{ten}年从 {fy_sbc[0]:.0f}% "
                 f"{'升到' if fy_sbc[-1] > fy_sbc[0] else '降到'} {fy_sbc[-1]:.1f}%")
    sbc_note = ""
    if guided_year:
        ex_now, ex_before = fy_ex_sbc[-1], ex_sbc_actual[-1]
        apparent = fy_non_gaap_margin[-1] - ngm_actual[-1]
        real = ex_now - ex_before
        sbc_title += (f"，调整后利润率 {e_label} 反而回落到 {ex_now:.2f}%" if real < 0
                      else f"，调整后利润率 {e_label} 为 {ex_now:.2f}%")
        if real < 0 and apparent < 0:
            sbc_note = (
                ("<b>这是这条线" + ten + "年里第一次倒退，" if not ex_sbc_ever_fell else "<b>这一年调整后利润率倒退，")
                + f"而且倒退幅度是表观的{times_words(real / apparent) if real / apparent >= 1 else '不到一倍'}</b>："
                f"表观非 GAAP 利润率 {e_label} 较 {last_year} 年降 {abs(apparent):.2f}pp，"
                f"而把股权激励还原成成本后降 {abs(real):.2f}pp。"
            )
        else:
            sbc_note = (f"表观非 GAAP 利润率 {e_label} 较 {last_year} 年 {apparent:+.2f}pp，"
                        f"把股权激励还原成成本后 {real:+.2f}pp。")
    sbc_note += (
        f"两条线的缺口就是 SBC，它{ten}年间从 {fy_sbc[0]:.0f}% "
        + ("一路" if not sbc_dips else "")
        + f"走到 {fy_sbc[-1]:.0f}%"
        + (f"，中间在 {sbc_dips[0]}" + (f"–{sbc_dips[-1]}" if len(sbc_dips) > 1 else "") + " 年回落过。"
           if sbc_dips else "。")
        + "这一行与上一行都是公司自己在 CFO Commentary 里并列披露的，不是本页的再加工。"
    )

    cat_long = staging["category_long_pct"]
    cat_labels = [compact_period(q_) for q_ in cat_long["quarters"]]
    long_span = years_words(len(long_labels))
    negative_words = (
        f"窗口里唯一一个负增长季是 {quarter_label(long['quarters'][negative_yoy[0][0]])}（{negative_yoy[0][1]:.1f}%）。"
        if len(negative_yoy) == 1 else
        "窗口里没有负增长季。" if not negative_yoy else
        f"窗口里有 {len(negative_yoy)} 个负增长季："
        + "、".join(f"{quarter_label(long['quarters'][i])}（{v:.1f}%）" for i, v in negative_yoy) + "。"
    )
    trough_words = ""
    if after_peak:
        trough_index, min_recent_yoy = min(after_peak, key=lambda pair: pair[1])
        trough_words = f"，到 {quarter_label(long['quarters'][trough_index])} 掉到 {min_recent_yoy:.1f}%"
    fy_cov_peak = max(v for v in fy_coverage if v is not None)
    fy_cov_peak_year = fy["labels"][fy_coverage.index(fy_cov_peak)]
    flat_years = 1
    while (flat_years < len(fy_coverage)
           and round(fy_coverage[-1 - flat_years], 2) == round(fy_coverage[-1], 2)):
        flat_years += 1
    early = next((i for i, v in enumerate(fy_coverage)
                  if v is not None and round(v, 2) > round(fy_coverage[-1], 2)), None)
    backlog_rising = all(b > a for a, b in zip(fy_backlog, fy_backlog[1:]))
    flat_names = "、".join(fy["labels"][-flat_years:])
    routine = [
        {
            "ref": "EX_CAT_LONG",
            "kind": "lines",
            "title": (f"{len(cat_labels)} 季三条产品线占收入的比重："
                      f"Semiconductor IP 从 {cat_long['category_semiconductor_ip'][0]:.0f}% 走到 "
                      f"{cat_long['category_semiconductor_ip'][-1]:.0f}%，"
                      f"Core EDA 从 {cat_long['category_core_eda'][0]:.0f}% "
                      f"{'降到' if cat_long['category_core_eda'][-1] < cat_long['category_core_eda'][0] else '升到'} "
                      f"{cat_long['category_core_eda'][-1]:.0f}%"),
            "xlabels": cat_labels,
            "xstep": 4,
            "series": [
                {"name": "Core EDA D", "values": cat_long["category_core_eda"], "color": "NAVY"},
                {"name": "System Design & Analysis", "color": "MBLUE",
                 "values": cat_long["category_system_design_analysis"]},
                {"name": "Semiconductor IP", "color": "GOLD",
                 "values": cat_long["category_semiconductor_ip"]},
            ],
            "fmt": "pct0", "yfmt": "pct0", "label_fmt": "pct0",
            "ylab": "占收入", "end_label": True,
            "note": (
                # Fixed history: the five-way table ran 2016Q1–2024Q2, the
                # "Core EDA" row first printed in 2024Q3, the five rows last
                # printed in 2024Q3 (the 2024Q4 release carries three).
                "<b>这个三分法本身是 2024–2025 年合并出来的，不是一路不变的口径。</b>"
                "Cadence 从 2016Q1 到 2024Q2 一直印<b>五分法</b>"
                "（Functional Verification、Digital IC Design and Signoff、Custom IC Design、"
                "System Interconnect / Design and Analysis、IP）；"
                "第一次印出「Core EDA」这一行是 2024Q3，第一次不再给五行明细是 2024Q4。"
                "所以 2016Q1–2023Q2 的 Core EDA 是前三行相加得到的 <b>D</b>，"
                "与本页 2023Q3 起既有值的算法相同 —— 那几季本来也是相加出来的，"
                "不是公司印出的单一数字。"
                "<b>支持这样接的证据</b>：公司自己第一次印出的 Core EDA 合计（2024Q3）"
                "与该算法数值精确相符。"
                "三条相加每季为 100%，这是公司按整数印出来的占比，所以这张图不受"
                "收入水平口径变化影响。"
            ),
            "src_extra": "各季业绩 8-K EX-99.2 CFO Commentary 的 Revenue Mix by Product Group 表。",
        },
        {
            "kind": "gs_bar",
            "title": (
                f"收入 {len(long_labels)} 个季度（前 {asc_605} 季为 ASC 605）：从 ${long_revenue[0]:,.0f}M 到 "
                f"${long_revenue[-1]:,.0f}M，本季同比 {long_revenue_yoy[-1]:.1f}%"
            ),
            "xlabels": long_labels,
            "xstep": LONG_STEP,
            "values": long_revenue,
            "legend": "季度总收入",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "ylab2": "同比增速",
            "yoy": {
                "name": "同比增速 (RHS) D",
                "values": long_revenue_yoy,
                "color": "GREEN",
                "yfmt": "pct0",
            },
            "note": (
                f"<b>八季的窗口会把当前这段读成一条直线，{long_span}的窗口说的是一段过山车</b>："
                f"同比增速在 {peak_quarter} 见顶 {max_yoy:.1f}%"
                + trough_words
                + f"，本季回到 {long_revenue_yoy[-1]:.1f}%。"
                + negative_words
                + long["provenance"]
            ),
            "src_extra": source_note("季度收入来自各期 10-Q / 10-K；同比为自算"),
        },
        {
            "kind": "lines",
            "title": margin_title,
            "xlabels": fy_labels,
            "series": [
                {"name": "非 GAAP 营业利润率", "values": fy_non_gaap_margin, "color": "NAVY"},
                {"name": "GAAP 营业利润率", "values": fy_gaap_margin, "color": "MBLUE"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "end_label": True,
            "ylab": "营业利润率",
            "note": margin_note,
            "src_extra": (
                f"{fy['labels'][0]}–{last_year} 为公司在历年 CFO Commentary 的五年财务指标表中披露的年度值"
                "（2016–2020 的 GAAP 口径由当年 10-K 的营业利润 ÷ 收入自算，公司当年未在该表列示）"
                + (f"；{e_label} 为本季全年指引区间的中值。" if guided_year else "。")
            ),
        },
        {
            "kind": "lines",
            "title": sbc_title,
            "xlabels": fy_labels,
            "series": [
                {"name": "非 GAAP 营业利润率", "values": fy_non_gaap_margin, "color": "GRAY"},
                {"name": "SBC 调整后非 GAAP 营业利润率", "values": fy_ex_sbc, "color": "NAVY"},
                {"name": "股权激励占收入", "values": fy_sbc, "color": "RED"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "zero_base": True,
            "end_label": True,
            "ylab": "占收入比",
            "note": sbc_note,
            "src_extra": (
                "三行均取自历年 CFO Commentary 的「Profitability Trends」表（公司披露值）"
                + (f"；{e_label} 为公司给出的全年指引中值。" if guided_year else "。")
            ),
        },
        {
            "kind": "gs_bar",
            "title": (
                f"研发绝对额{long_span} {long_research[-1] / long_research[0]:.1f} 倍，"
                f"占收入比却从 {long_research_ratio[0]:.1f}% 降到 {long_research_ratio[-1]:.1f}%"
            ),
            "xlabels": long_labels,
            "xstep": LONG_STEP,
            "values": long_research,
            "legend": "季度研发费用",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "ylab2": "占收入比",
            "yoy": {
                "name": "研发 / 收入 (RHS) D",
                "values": long_research_ratio,
                "color": "RED",
                "yfmt": "pct0",
            },
            "note": (
                f"<b>十年利润率扩张的来源就在这条线上</b>：研发、营销与管理三项合计占收入"
                f"由 {long_opex_ratio[0]:.1f}% 降到 {long_opex_ratio[-1]:.1f}%，"
                f"同期非 GAAP 营业利润率从 {ngm_actual[0]:.0f}% 走到 {ngm_actual[-1]:.1f}%——不是提价，是费用被收入摊薄。"
                f"这条线季节性明显（第四季收入高、比率低），窗口内最低到过 "
                f"{min(v for v in long_research_ratio if v is not None):.1f}%。"
                f"本季研发同比 {research_yoy[-1]:.1f}%，"
                + told("rnd")
                + f"营销费用同比 {marketing_yoy[-1]:.1f}%、管理费用同比 {admin_yoy[-1]:.1f}%"
                + (f"，后者是三条费用线里最快的一条。"
                   if admin_yoy[-1] > max(research_yoy[-1], marketing_yoy[-1]) else "。")
            ),
            "src_extra": source_note(
                "研发费用逐季来自各期 10-Q / 10-K，财政第四季为全年 − 前三季；占收入比为自算"),
        },
        {
            "kind": "gs_bar",
            "title": (
                f"年末 backlog {ten}年从 US${fy_backlog[0]:.1f}B 到 US${fy_backlog[-1]:.1f}B，"
                f"覆盖倍数在 {fy_cov_peak_year} 年见顶 {fy_cov_peak:.2f}x "
                + (f"后连续{cn_count(flat_years)}年停在 {fy_coverage[-1]:.2f}x" if flat_years >= 2
                   else f"后回到 {fy_coverage[-1]:.2f}x")
            ),
            "xlabels": fy["labels"],
            "values": fy_backlog,
            "legend": "年末 backlog",
            "fmt": "usd1",
            "yfmt": "usd1",
            "label_fmt": "usd1",
            "ylab": "US$B",
            "ylab2": "覆盖倍数",
            "yoy": {
                "name": "backlog / 当年收入 (RHS) D",
                "values": fy_coverage,
                "color": "RED",
                "yfmt": "f2",
            },
            "note": (
                f"<b>{ten}年窗口才说得清「创纪录 backlog」到底意味着什么</b>："
                + ("绝对额年年新高，" if backlog_rising else "")
                + "而以当年收入衡量的覆盖倍数"
                + (f"在 {fy['labels'][early]} 年就到过 {fy_coverage[early]:.2f}x、" if early is not None
                   and fy["labels"][early] != fy_cov_peak_year else "")
                + f"{fy_cov_peak_year} 年见顶 {fy_cov_peak:.2f}x，"
                + (f"随后 {flat_names} {cn_count(flat_years)}年<b>一模一样地停在 {fy_coverage[-1]:.2f}x</b>。"
                   "订单存量与收入是同步长大的，没有跑赢——所以「record backlog」的 de-risk 含义"
                   "比标题读起来小，可见度既没有变长，也没有变短。"
                   if flat_years >= 2 else f"{last_year} 年为 {fy_coverage[-1]:.2f}x。")
            ),
            "src_extra": (
                "backlog 为公司在历年 CFO Commentary 的 Backlog 表中披露的年末值，精度到 US$0.1B；"
                "覆盖倍数为其除以同年收入的自算值。"
            ),
        },
    ]

    exhibits = resolve_exhibit_refs(
        number_exhibits(settled_charts + highlights + next_charts + routine)
    )
    grouped = []
    cursor = 0
    for group in (settled_charts, highlights, next_charts, routine):
        grouped.append(exhibits[cursor:cursor + len(group)])
        cursor += len(group)
    settled_ex, highlight_ex, next_ex, routine_ex = grouped
    first_table = len(exhibits) + 2

    # ── audit tables ────────────────────────────────────────────────────────
    delivery_rows = []
    for index, quarter in enumerate(record["quarters"]):
        def verdict(actual, low, high):
            if actual is None:
                return "待披露"
            if actual > high:
                return "高于上限"
            if actual < low:
                return "低于下限"
            return "区间内"
        actual_revenue = record["revenue_actual_usd_m"][index]
        actual_margin = record["non_gaap_operating_margin_actual_pct"][index]
        actual_eps = record["non_gaap_eps_actual"][index]
        low, high = record["revenue_guide_low_usd_m"][index], record["revenue_guide_high_usd_m"][index]
        m_low = record["non_gaap_operating_margin_guide_low_pct"][index]
        m_high = record["non_gaap_operating_margin_guide_high_pct"][index]
        e_low, e_high = record["non_gaap_eps_guide_low"][index], record["non_gaap_eps_guide_high"][index]
        delivery_rows.append([
            quarter_label(quarter),
            record["guided_on"][index],
            f"${low:,.0f}–{high:,.0f}M",
            "—" if actual_revenue is None else f"${actual_revenue:,.1f}M",
            verdict(actual_revenue, low, high),
            (f"{m_low:.2f}%" if record["non_gaap_operating_margin_guide_form"][index] == "point"
             else f"{m_low:.2f}–{m_high:.2f}%"),
            "—" if actual_margin is None else f"{actual_margin:.1f}%",
            verdict(actual_margin, m_low, m_high),
            f"${e_low:.2f}–{e_high:.2f}",
            "—" if actual_eps is None else f"${actual_eps:.2f}",
            verdict(actual_eps, e_low, e_high),
        ])

    quarterly_rows = []
    for index, period_label in enumerate(periods):
        def cell(name, fmt="${:,.1f}M"):
            value = q[name][index]
            return "—" if value is None else fmt.format(value)
        quarterly_rows.append([
            period_label,
            cell("revenue_total"),
            cell("revenue_product_and_maintenance"),
            cell("revenue_services"),
            cell("operating_income"),
            cell("research_and_development"),
            cell("marketing_and_sales"),
            cell("general_and_administrative"),
            cell("stock_based_compensation"),
            cell("operating_cash_flow"),
            cell("capital_expenditures"),
            f"${q['operating_cash_flow'][index] - q['capital_expenditures'][index]:,.1f}M D",
            cell("stock_repurchases"),
            "—" if qo["diluted_shares_m"][index] is None else f"{qo['diluted_shares_m'][index]:.3f}M",
        ])

    mix_rows = []
    for index, period_label in enumerate(periods[-WINDOW:], start=len(periods) - WINDOW):
        def share(name):
            value = qp[name][index]
            return "—" if value is None else f"{value:.0f}%"

        def amount(name):
            value = qp[name][index]
            return "—" if value is None else f"${value / 100 * revenue[index]:,.0f}M D"
        mix_rows.append([
            period_label,
            share("category_core_eda"), amount("category_core_eda"),
            share("category_semiconductor_ip"), amount("category_semiconductor_ip"),
            share("category_system_design_analysis"), amount("category_system_design_analysis"),
            share("geo_americas"), share("geo_china"),
            "—" if q["china_revenue"][index] is None else f"${q['china_revenue'][index]:,.1f}M",
            share("geo_other_asia"), share("geo_emea"), share("geo_japan"),
            "—" if qp["recurring_revenue"][index] is None else f"{qp['recurring_revenue'][index]:.0f}%",
        ])

    annual_rows = []
    for index, fiscal in enumerate(fy["labels"]):
        def fy_cell(name, fmt="{:,.0f}"):
            value = fy[name][index]
            return "—" if value is None else fmt.format(value)
        annual_rows.append([
            fiscal,
            f"${fy['revenue_usd_m'][index]:,.0f}M",
            fy_cell("gaap_operating_margin_pct", "{:.1f}%"),
            fy_cell("non_gaap_operating_margin_pct", "{:.1f}%"),
            fy_cell("stock_based_compensation_pct_of_revenue", "{:.1f}%"),
            fy_cell("non_gaap_operating_margin_ex_sbc_pct", "{:.1f}%"),
            fy_cell("non_gaap_eps", "${:.2f}"),
            fy_cell("diluted_shares_m", "{:.1f}M"),
            fy_cell("operating_cash_flow_usd_m", "${:,.1f}M"),
            fy_cell("capital_expenditures_usd_m", "${:,.1f}M"),
            fy_cell("stock_repurchases_usd_m", "${:,.1f}M"),
            fy_cell("year_end_backlog_usd_bn", "US${:.1f}B"),
        ])
    if guided_year:
        guided = guided_year
        annual_rows.append([
            f"{e_label}（指引）",
            f"${guided['revenue_usd_m'][0]:,.0f}–{guided['revenue_usd_m'][1]:,.0f}M",
            f"{guided['gaap_operating_margin_pct'][0]:.2f}–{guided['gaap_operating_margin_pct'][1]:.2f}%",
            f"{guided['non_gaap_operating_margin_pct'][0]:.2f}–{guided['non_gaap_operating_margin_pct'][1]:.2f}%",
            f"{guided['stock_based_compensation_pct_of_revenue']:.1f}%",
            f"{guided['non_gaap_operating_margin_ex_sbc_pct']:.2f}%",
            f"${guided['non_gaap_eps'][0]:.2f}–{guided['non_gaap_eps'][1]:.2f}",
            f"{guided['diluted_shares_m'][0]:.1f}–{guided['diluted_shares_m'][1]:.1f}M",
            money_range(guided["operating_cash_flow_usd_m"]),
            money_range(guided["capital_expenditures_usd_m"]),
            guided["buyback_policy"].replace("全年", "").replace("用于回购", "")
            if guided.get("buyback_policy") else "—",
            "—",
        ])

    guidance_rows = []
    if plan:
        nq = plan["next"]
        cur, prev = plan["current"], plan["previous"]
        next_q = plan["next_period"].split()[0]
        run = 1
        amounts = [round(v) for v in q["stock_repurchases"]] + [round(nq["buyback_usd_m"])]
        while run + 1 < len(amounts) and amounts[-1 - run] == amounts[-2 - run]:
            run += 1
        flat_words = (f"连续第{cn_ordinal(run)}季持平" if amounts[-1] == amounts[-2] else
                      "较本季" + ("增加" if amounts[-1] > amounts[-2] else "减少"))
        guidance_rows = [
            ["下季收入", f"${revenue[-1]:,.1f}M（本季实际）",
             f"${nq['revenue_usd_m'][0]:,.0f}–{nq['revenue_usd_m'][1]:,.0f}M",
             "中值隐含" + (f"同比 {signed(plan['nq_yoy'])}、" if "nq_yoy" in plan else "")
             + f"环比 {signed(plan['nq_qoq'])} D"],
            ["下季非 GAAP 营业利润率", f"{non_gaap_margin[-1]:.1f}%（本季实际）",
             f"{nq['non_gaap_operating_margin_pct'][0]:.1f}–{nq['non_gaap_operating_margin_pct'][1]:.1f}%",
             f"中值较本季实际 {plan['nq_margin'] - non_gaap_margin[-1]:+.1f}pp D"],
            ["下季非 GAAP EPS", f"${qo['non_gaap_eps'][-1]:.2f}（本季实际）",
             f"${nq['non_gaap_eps'][0]:.2f}–{nq['non_gaap_eps'][1]:.2f}",
             f"中值环比 {pct_change(mid(nq['non_gaap_eps']), qo['non_gaap_eps'][-1]):+.1f}% D"],
            ["下季回购", f"${buybacks[-1]:,.0f}M（本季实际）", f"约 ${nq['buyback_usd_m']:,.0f}M", flat_words],
        ]
        cur_margin_mid = mid(cur["non_gaap_operating_margin_pct"])
        prior_margin = fy["non_gaap_operating_margin_pct"][-1]
        prev_margin_mid = mid(prev["non_gaap_operating_margin_pct"]) if prev is not None else None
        margin_vs_prior = (("仍低于" if prev_margin_mid is not None and prev_margin_mid < prior_margin else "低于")
                           if cur_margin_mid < prior_margin else
                           ("仍高于" if prev_margin_mid is not None and prev_margin_mid > prior_margin else "高于")
                           if cur_margin_mid > prior_margin else "持平于")
        if prev is not None:
            raise_words = (f"上修 ${plan['raise_revenue']:,.0f}M D" if plan["raise_revenue"] > 0 else
                           f"下修 ${abs(plan['raise_revenue']):,.0f}M D" if plan["raise_revenue"] < 0 else "维持")
            if guidance.get("revenue_raise_note"):
                raise_words += "，" + guidance["revenue_raise_note"]
            margin_move = (cur_margin_mid - mid(prev["non_gaap_operating_margin_pct"])) * 100
            eps_move = mid(cur["non_gaap_eps"]) - mid(prev["non_gaap_eps"])
            ocf_move = mid(cur["operating_cash_flow_usd_m"]) - mid(prev["operating_cash_flow_usd_m"])
            backlog_share = (cur["revenue_from_beginning_backlog_pct"], prev["revenue_from_beginning_backlog_pct"])
            guidance_rows += [
                ["全年收入", f"${prev['revenue_usd_m'][0]:,.0f}–{prev['revenue_usd_m'][1]:,.0f}M",
                 f"${cur['revenue_usd_m'][0]:,.0f}–{cur['revenue_usd_m'][1]:,.0f}M", raise_words],
                ["全年非 GAAP 营业利润率",
                 f"{prev['non_gaap_operating_margin_pct'][0]:.2f}–{prev['non_gaap_operating_margin_pct'][1]:.2f}%",
                 f"{cur['non_gaap_operating_margin_pct'][0]:.2f}–{cur['non_gaap_operating_margin_pct'][1]:.2f}%",
                 f"中值{'上修' if margin_move > 0 else '下修' if margin_move < 0 else '维持'}"
                 + (f" {abs(margin_move):.0f}bp" if margin_move else "")
                 + f"，{margin_vs_prior} {last_year} 年的 {prior_margin:.1f}%"],
                ["全年非 GAAP EPS", f"${prev['non_gaap_eps'][0]:.2f}–{prev['non_gaap_eps'][1]:.2f}",
                 f"${cur['non_gaap_eps'][0]:.2f}–{cur['non_gaap_eps'][1]:.2f}",
                 f"中值{'上修' if eps_move > 0 else '下修'} ${abs(eps_move):.2f}；增量经营利润率 "
                 f"{plan['incremental_margin']:.1f}% D"
                 f"（用公司印出的经营利润 ${plan['fy_oi']:,.0f}M 与 "
                 f"${prev['non_gaap_operating_income_midpoint_usd_m']:,.0f}M 相减）；"
                 f"改用指引区间中值直接相乘为 {plan['incremental_margin_exact']:.1f}%，"
                 + ("差异来自公司对经营利润的四舍五入" if plan["rounding_explains"] else
                    "差异大于四舍五入所能解释的幅度")],
                ["全年经营现金流", money_range(prev["operating_cash_flow_usd_m"]),
                 money_range(cur["operating_cash_flow_usd_m"]),
                 f"{'上修' if ocf_move > 0 else '下修'}约 ${abs(ocf_move):,.0f}M"],
                ["全年收入中来自期初 backlog 的比例",
                 f"约 {backlog_share[1]}%",
                 f"约 {backlog_share[0]}%",
                 "只披露到整数位；方向是"
                 + ("新签订单的贡献在上升" if backlog_share[0] < backlog_share[1] else
                    "期初 backlog 的贡献在上升" if backlog_share[0] > backlog_share[1] else "两者持平")
                 + "，比例本身不稳健"],
            ]
        else:
            guidance_rows += [
                ["全年收入", "—", f"${cur['revenue_usd_m'][0]:,.0f}–{cur['revenue_usd_m'][1]:,.0f}M",
                 "本季首次给出"],
                ["全年非 GAAP 营业利润率", "—",
                 f"{cur['non_gaap_operating_margin_pct'][0]:.2f}–{cur['non_gaap_operating_margin_pct'][1]:.2f}%",
                 f"中值{margin_vs_prior} {last_year} 年的 {prior_margin:.1f}%"],
                ["全年非 GAAP EPS", "—", f"${cur['non_gaap_eps'][0]:.2f}–{cur['non_gaap_eps'][1]:.2f}", "—"],
                ["全年经营现金流", "—", money_range(cur["operating_cash_flow_usd_m"]), "—"],
            ]
        if "remainder_margin" in plan:
            guidance_rows.append([
                f"{plan['remainder_period']} 隐含非 GAAP 营业利润率", "—", f"{plan['remainder_margin']:.2f}% D",
                f"由全年中值 ${plan['fy_oi']:,.0f}M"
                + (f" − {ytd_word}实际" if plan["done"] else "")
                + f" − {next_q} 指引中值倒推"
                + (f"；{peer_clause(with_value=True)}" if peer is not None else ""),
            ])
        if guidance.get("export_control_assumption"):
            guidance_rows.append(["全年指引的政策前提", "—", "出口管制维持现状",
                                  guidance["export_control_assumption"]])

    tables = [table for table in (closure_table, prior_table, next_table, followup_table) if table is not None]
    tables.append({
        "n": 0,
        "title": f"指引兑现记录：{len(record['quarters'])} 个季度的三项指引与实际（原单位）",
        "headers": ["季度", "指引发布日", "收入指引", "实际收入", "结果",
                    "非 GAAP 营业利润率指引", "实际", "结果",
                    "非 GAAP EPS 指引", "实际", "结果"],
        "rows": delivery_rows,
    })
    if guidance_rows:
        tables.append({
            "n": 0,
            "title": "下季与全年指引",
            "headers": ["指标", "上季 / 本季实际", "新口径", "变化 / 备注"],
            "rows": guidance_rows,
        })
    tables += [
        {
            "n": 0,
            "title": f"{cn_count(len(periods))}季度基础数据（前四季只用于计算同比）",
            "headers": ["期间", "总收入", "产品与维护", "服务", "GAAP 经营利润", "研发", "营销",
                        "管理", "股权激励", "经营现金流", "资本开支", "自由现金流 D", "回购", "摊薄股数"],
            "rows": quarterly_rows,
        },
        {
            "n": 0,
            "title": f"{cn_count(WINDOW)}季度产品线与地域占比（公司只披露整数百分位，金额为自算）",
            "headers": ["期间", "Core EDA", "金额 D", "IP", "金额 D", "SD&A", "金额 D",
                        "美洲", "中国占比", "中国收入（申报值）", "其他亚洲", "EMEA", "日本", "经常性收入"],
            "rows": mix_rows,
        },
        {
            "n": 0,
            "title": f"{ten}年年度记录" + (f"与 {plan['fiscal_year']} 全年指引" if guided_year else ""),
            "headers": ["年度", "收入", "GAAP 营业利润率", "非 GAAP 营业利润率", "SBC 占收入",
                        "SBC 调整后非 GAAP 营业利润率", "非 GAAP EPS", "摊薄股数",
                        "经营现金流", "资本开支", "回购", "年末 backlog"],
            "rows": annual_rows,
        },
    ]
    if balance is not None:
        start_label, end_label = balance["labels"]
        balance_rows = []
        for name, chinese in [
            ("cash_and_equivalents", "现金及等价物"),
            ("receivables_net", "应收账款净额"),
            ("inventories", "存货"),
            ("goodwill", "商誉"),
            ("acquired_intangibles_net", "无形资产净额"),
            ("deferred_revenue_current", "当期递延收入"),
            ("deferred_revenue_long_term", "长期递延收入"),
            ("long_term_debt", "长期借款（账面）"),
            ("other_long_term_liabilities", "其他长期负债"),
            ("stockholders_equity", "股东权益"),
            ("total_assets", "资产总额"),
        ]:
            start, end = balance[name]
            balance_rows.append([
                chinese, f"${start:,.1f}M", f"${end:,.1f}M",
                f"${end - start:+,.1f}M", f"{pct_change(end, start):+.1f}% D",
            ])
            # The 10-Q's balance-sheet note breaks this line down; the parts
            # must add back to the line or the breakdown is from another date.
            parts = balance.get(f"{name}_components") if name == "other_long_term_liabilities" else None
            if parts:
                for side in (0, 1):
                    if abs(sum(values[side] for values in parts.values()) - balance[name][side]) > 0.002:
                        raise ValueError(f"`balance_sheet_usd_m.{name}_components` does not add up to the line")
                for part, words in (("deferred_income_taxes", "其中：递延所得税负债"),
                                    ("operating_lease_liabilities", "其中：经营租赁负债"),
                                    ("other_accrued_liabilities", "其中：其他应计负债")):
                    part_start, part_end = parts[part]
                    balance_rows.append([
                        words, f"${part_start:,.1f}M", f"${part_end:,.1f}M",
                        f"${part_end - part_start:+,.1f}M", f"{pct_change(part_end, part_start):+.1f}% D",
                    ])
        tables.append({
            "n": 0,
            "title": f"资产负债表变动（{start_label} → {end_label}）",
            "headers": ["项目", start_label, end_label, "变动", "变动率"],
            "rows": balance_rows,
        })
    if bridge is not None:
        tables.append({
            "n": 0,
            "title": f"{ytd_word}现金桥（逐项取自现金流量表）",
            "headers": ["项目", "金额"],
            "rows": [
                [name, f"${value:+,.1f}M" if index not in (0, len(bridge["labels"]) - 1)
                 else f"${value:,.1f}M"]
                for index, (name, value) in enumerate(zip(bridge["labels"], bridge["values"]))
            ],
        })
    tables.append(ai_capex_cycle_table(0))
    for offset, table in enumerate(tables):
        table["n"] = first_table + offset

    # ── headline, brief, notes ──────────────────────────────────────────────
    headline = ""
    if story_or.get("headline_lead"):
        headline += story_or["headline_lead"] + "："
    headline += (
        f"收入 ${revenue[-1]:,.1f}M "
        + ("落在指引区间之内" if inside_guide else
           "高于指引上限" if revenue[-1] > quarter_guide_high else "低于指引下限")
        + ("、与中值持平" if round(versus_mid, 1) == 0 else
           f"、只比中值高 {versus_mid:.1f}%" if inside_guide and versus_mid > 0 else
           f"、比中值{'高' if versus_mid > 0 else '低'} {abs(versus_mid):.1f}%")
    )
    if story_or.get("headline_backlog"):
        headline += "，" + told("headline_backlog") + "。"
    elif ytd_backlog_add is not None:
        headline += (f"，{ytd_word} backlog {'净增' if ytd_backlog_add >= 0 else '净减'} "
                     f"${abs(ytd_backlog_add):,.0f}M 到 US${backlog_all[-1]:.1f}B。")
    else:
        headline += f"，backlog US${backlog_all[-1]:.1f}B。"
    if plan and "raise_revenue" in plan and "remainder_margin" in plan:
        headline += (
            (story_or["headline_cost"] + "：" if story_or.get("headline_cost") else "")
            + f"全年收入{'上修' if plan['raise_revenue'] > 0 else '下修'} ${abs(plan['raise_revenue']):,.0f}M "
            f"{'只换来' if 0 < plan['raise_oi'] < plan['raise_revenue'] else '对应'} ${plan['raise_oi']:,.0f}M 经营利润，"
            f"倒推出的 {plan['remainder_word']} 非 GAAP 营业利润率 {plan['remainder_margin']:.2f}%"
            + (f" {peer_clause(labelled=True)}" if peer is not None else "")
            + "。"
        )
    if consensus is not None and consensus.get("post_earnings_price_change_pct") is not None:
        headline += f"财报当日盘后 {signed(consensus['post_earnings_price_change_pct'], 0)}。"

    cards = []
    for card in story_or.get("cards", []):
        cards.append(f'<article><span>{card["tag"]}</span><b>{fill_story(card["title"], values)}</b>'
                     f'<p>{fill_story(card["body"], values)}</p></article>')
    if not cards:
        cards = [
            '<article><span>订单</span><b>backlog 与覆盖倍数</b>'
            f'<p>backlog US${backlog_all[-1]:.1f}B{values["backlog_record"]}，覆盖倍数 {coverage[-1]:.2f}x；'
            f'经营现金流 {values["ocf"]}、同比 {values["ocf_yoy"]}。</p></article>',
            '<article><span>利润率</span><b>本季非 GAAP 营业利润率</b>'
            f'<p>{non_gaap_margin[-1]:.1f}%，去年同期 {non_gaap_margin[-5]:.1f}%。</p></article>',
            '<article><span>中国</span><b>中国收入占比</b>'
            f'<p>占比 {values["china_share_exact"]}、金额 {values["china_revenue"]}，{values["china_vs_peak"]}。</p></article>',
        ]
    brief = (f'<h4>本季{cn_count(len(cards))}条主线</h4><div class="takeaway-grid">'
             + "".join(cards) + '</div>')

    notes = [
        "本页统一用自然年季度标注。Cadence 自 2023 财年起各季结束于自然季末，"
        "2022 及以前为 52/53 周制、季末落在自然季末前后数日；本页按公司自己的财季归入相应自然年季度，"
        "不做任何日历调整。",
        "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，"
        "每张图下一到两句解释；支撑表格收在核对抽屉里。",
    ]
    # Both numbers are the thresholds charts' own, read after numbering: the
    # first used to be typed as 2, which is the follow-up chart.
    threshold_charts = [ex["n"] for ex in settled_ex + next_ex if ex["kind"] == "diverging_bars"]
    if threshold_charts:
        notes.append(
            " 与 ".join(f"Exhibit {n}" for n in threshold_charts) + " 的阈值取自本站自己的季报分析"
            "（上季与本季两份，出处逐条列在核对表），不是公司指引，也不构成评级或投资建议；"
            "「距阈值余量」统一为正值代表守住或达到。")
    pending = len(record["quarters"]) - len(facts_record["finished"])
    notes += [
        "本页只发布公司披露值、可复算的简单派生值，以及明确标注的市场预期；D 标记代表 Derived / 自算。",
        "指引兑现记录取自各季业绩 8-K 的 EX-99.02 CFO Commentary，"
        f"覆盖 {record['quarters'][0]} 起共 {len(record['quarters'])} 个季度"
        + (f"，其中最后一季只有指引、实际值待披露。" if pending == 1 else
           f"，其中最后 {pending} 季只有指引、实际值待披露。" if pending else "。")
        + "该指引与上一季财报同时发布，发布日已落在被指引季度之内——"
        "第二、三、四季通常已过约 4 周，第一季往往已过半个季度，因此它不是事前预测；"
        "核对表的「指引发布日」一列可逐季复核。"
        "非 GAAP 营业利润率的指引在部分季度是单点数（原文写作 ~30% 或 approximately 30%）而不是区间，"
        "写作「29% to 30%」的则是区间；核对表按公司原样列示，单点季在图上因此没有宽度。",
        f"{ASC_606_FIRST} 起收入确认采用 ASC 606，2017 及以前按 ASC 605 报告且公司未重述，"
        f"两段水平值不可直接连读；本页的长期序列自 {long['quarters'][0]} 起、前 {asc_605} 季为 ASC 605，"
        f"图注标出这道坎，指引兑现的水平图在 {ASC_606_FIRST} 打断点，而偏离序列不受影响——每一对指引与实际都落在同一套准则内。",
        "产品线（Core EDA / Semiconductor IP / System Design and Analysis）只披露"
        "收入占比的整数百分位，公司不披露该口径的分部金额。本页相关金额均为占比 × 当季总收入的自算值，"
        f"含 ±${revenue[-1] * 0.005:.0f}M 量级的四舍五入误差；两个整数占比相除得到的同比增速误差可达 "
        f"±{(ip_high - ip_low) / 2:.0f}pp，"
        f"因此 IP 的「{ip_yoy:+.0f}%」只应读作「{reads_as(ip_yoy)}」。"
        + (f"公司自己给出的分部同比（{company_words}）与占比法反推的结果互有出入，"
           "两者都列在核对表里，本页不在两者间取舍。" if company_words else ""),
        "地域是例外：中国收入有申报金额，不需要用占比反推。"
        "10-Q / 10-K 的分部附注按地域披露收入金额（千美元），本页中国那张图用的就是这个金额；"
        "季度值自 2023Q1 起可得，财政第四季为全年 − 前三季。"
        f"用整数占比反推会系统性偏离——按占比法本季中国同比为 {china_values['china_yoy_by_share']}，"
        f"按申报金额为 {china_yoy[-1]:+.1f}%。CFO Commentary 的整数占比可回溯到 2018Q1，本页只把它当占比用。",
    ]
    if plan and "remainder_margin" in plan:
        notes.append(
            f"{plan['remainder_period']} 隐含非 GAAP 营业利润率为算术倒推：全年指引中值的非 GAAP 营业利润 "
            + (f"− {ytd_word}实际 " if plan["done"] else "")
            + f"− {plan['next_period'].split()[0]} 指引中值隐含值，除以同法倒推的 {plan['remainder_word']} 收入。"
            f"{'四' if plan['done'] else '三'}个输入全部是公司披露值，"
            f"没有估计成分；但它是指引隐含值而非公司给出的 {plan['remainder_word']} 指引，"
            f"公司并未单独给 {plan['remainder_word']} 数字。"
        )
    btb_lines = [line for line in prior_lines if line["reads"] == "book_to_bill"]
    notes.append(
        "backlog 覆盖倍数为自算（季末 backlog ÷ 过去四季收入）。backlog 只披露到 US$0.1B，"
        "水平值与覆盖倍数受此限制但仍可判；两季相减得到的 book-to-bill 只能按区间判——"
        f"本季 ${net_add:,.0f}M 的净增带 ±${swing:,.0f}M 的四舍五入区间，比率落在 {btb_range}"
        + ("：" + "；".join(
            f"上季{line_name(line)} 落在区间里，判为无法判定，而不是没到" if line["verdict"] == UNDECIDED
            else f"上季{line_name(line)} 在整个区间之外，判为{line['verdict']}" for line in btb_lines) + "。"
           if btb_lines else "，只能当方向看。")
        + seasonal_words
    )
    if balance is not None and balance.get("other_long_term_liabilities_components"):
        parts = balance["other_long_term_liabilities_components"]
        start, end = balance["other_long_term_liabilities"]
        # The quarter-end in between (the earlier 10-Q's same note) says when
        # the change happened; its parts must add back to its own total.
        interim = balance.get("other_long_term_liabilities_interim")
        timing = ""
        if interim:
            if not balance["labels"][0] < interim["date"] < balance["labels"][1]:
                raise ValueError("`balance_sheet_usd_m.other_long_term_liabilities_interim` is not between the two columns")
            month = int(interim["date"][5:7])
            timing = (f"，其中 {'+' if interim['value'] >= start else '−'}${abs(interim['value'] - start):,.1f}M "
                      f"发生在 {interim['date'][:4]}Q{(month - 1) // 3 + 1}")
            if all(part in interim for part in parts):
                if abs(sum(interim[part] for part in parts) - interim["value"]) > 0.002:
                    raise ValueError("`balance_sheet_usd_m.other_long_term_liabilities_interim` does not add up")
                timing += f"（{interim['date']} 的递延所得税负债已是 ${interim['deferred_income_taxes']:,.1f}M）"
        notes.append(
            f"其他长期负债在 {balance['labels'][0]} 到 {balance['labels'][1]} 之间"
            f"{'增加' if end >= start else '减少'} ${abs(end - start):,.1f}M{timing}；"
            "10-Q 附注 13 把它拆开了："
            + "、".join(f"{words} {'+' if pair[1] >= pair[0] else '−'}${abs(pair[1] - pair[0]):,.1f}M"
                       for part, words in (("deferred_income_taxes", "递延所得税负债"),
                                           ("operating_lease_liabilities", "经营租赁负债"),
                                           ("other_accrued_liabilities", "其他应计负债"))
                       for pair in [parts[part]])
            + (f"；附注 2 的 Hexagon D&E 购买价分摊里承接的长期负债是 {values['dne_ltl']}" if "dne_ltl" in values else "")
            + "。明细列在核对抽屉的资产负债表里。")
    market_note = "市场预期一律标注为「市场预期」并给出取数时点，不写卖方机构名，也不发布评级、目标价或估值。"
    if consensus is not None and consensus.get("source_conflict_note"):
        market_values = {
            "expected_revenue": f"${consensus['revenue_usd_m'] / 1000:.2f}B",
            "expected_revenue_alt": f"${consensus['revenue_usd_m_alt'] / 1000:.2f}B",
            "expected_eps_beat": f"{pct_change(qo['non_gaap_eps'][-1], consensus['non_gaap_eps']):+.1f}%",
        }
        market_note += f"{consensus['as_of']} 财报前，" + fill_story(consensus["source_conflict_note"], market_values) + "。"
    notes.append(market_note)
    if story_or.get("not_tracked"):
        notes.append(told("not_tracked"))

    return {
        "schema_version": "quarterly-dashboard/cdns-v1",
        "page": {"slug": "cdns", "language": "zh-CN"},
        "company": {
            "ticker": "CDNS",
            "name": "Cadence Design Systems",
            "group": "semiconductor_ai",
            "accounting_standard": "US GAAP",
        },
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · CDNS",
        "title": f"Cadence Design Systems (CDNS)：{period} 季报仪表盘",
        "subtitle": (
            f"截至 {latest['period_end']} · 发布 {latest['release_date']} · US GAAP · "
            f"{AUDIT_WORDS[latest['audit_status']]} · 金额单位为 $M，另有注明除外"
        ),
        "headline": headline,
        "brief": brief,
        "source": source,
        "source_url": ir["url"],
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {
                "id": "settled",
                "title": "一、上季跟踪指标兑现了吗",
                "description": (
                    ("先结算上季留下的问题与阈值，再把同一个问题问给公司自己："
                     if closure is not None or prior_kpi is not None else
                     "本季没有可结算的上季问题与阈值，只把同一个问题问给公司自己：")
                    + f"{len(record['quarters'])} 个季度的指引与实际摆在一起，"
                    "本季这份成绩单才有参照系。"
                ),
                "exhibits": settled_ex,
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": (
                    "收入与产品线结构、"
                    + (f"与 {peers['peer']} 的 IP 增速对照、" if peers is not None else "")
                    + ("中国这条没人问的线、" if story is not None else "中国收入、")
                    + "GAAP 与非 GAAP 毛利率的背离、"
                    + ("全年指引倒推出来的 " + plan["remainder_word"] + " 利润率，"
                       if plan and "remainder_margin" in plan else "")
                    + "以及订单存量与资本分配。"
                    + told("undrawn")
                ),
                "exhibits": highlight_ex,
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": (next_section_words if next_kpi is not None else "本季没有设定下季阈值。"),
                "exhibits": next_ex,
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": (
                    f"CDNS 专属的常规序列：{long['quarters'][0]} 以来的收入曲线、{ten}年利润率、"
                    "把股权激励还原成成本之后的利润率、研发强度，以及订单存量的覆盖倍数。"
                ),
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": notes,
        "footer": (
            "CDNS quarterly results · 数据来自 Cadence 公开披露与透明自算 · "
            "仅供研究，不构成投资建议"
        ),
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "cdns.js"), payload, "cdns")
    shell_dir = ROOT / "cdns"
    shell_dir.mkdir(exist_ok=True)
    # Rendered here, not at import: the shell stamps the payload's content
    # hash into its <script src>, so it has to be built after write_dash.
    (shell_dir / "index.html").write_text(
        render_shell("CDNS", "cdns"), encoding="utf-8")
    exhibits = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"CDNS page: {exhibits} charts in 4 sections + {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
