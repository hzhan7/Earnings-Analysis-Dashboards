#!/usr/bin/env python3
"""Compagnie Financière Richemont (CFR) quarterly dashboard.

Richemont is a Geneva-listed issuer reporting under IFRS in euros, with a
fiscal year that ends on 31 March. It is not an SEC reporting issuer -- EDGAR
holds Form D notices, REGDEX filings, one Schedule 13D and a Form 4/A under its
name and no financial statement of any kind -- so the results and sales
announcements it has published on richemont.com since September 2015 are the
whole source (`documents` in the series). The first forty-five were each
transcribed twice, blind, by separate readers; the two transcriptions agreed on
6,496 cells and disagreed on four, all on a cash line this page does not use.

**Three facts about how this company discloses decide what the page can be.**

The first is two clocks. Sales are published every quarter, split five ways by
region, three ways by channel and three (for four years, four) ways by business
area, each with a constant-exchange-rate growth rate beside it. Profit is
published only for the half-year to 30 September and the full year to 31 March.
There is no quarterly gross margin, no quarterly segment result, no quarterly
cash flow. The half-years are not calendar halves: the first half runs April to
September and the second October to March, so every profit chart here is on its
own axis, labelled by the month the half ends.

The second is that the quarterly record has holes, and they are of two kinds.
Until the 2019 annual general meeting the company reported its first months not
as a quarter but as five months, April to August, and as growth rates only. The
first and second fiscal quarters of FY17 and FY18 -- calendar 2016Q2, 2016Q3,
2017Q2 and 2017Q3 -- therefore cannot be separated by anybody: only their sum
exists, inside the half-year. Five further quarters were never printed as
quarters but can be derived, either as the full year less the nine months to
December or as the half-year less the first quarter. Everything else was
printed; from November 2021 each interim and annual announcement carries an
appendix that reprints every quarter, and that appendix reached back two years,
so some quarters from 2019-2021 were printed as quarters for the first time up
to 780 days after they ended.

The third is that the subtraction is only as good as the basis of its two legs.
Richemont consolidated YOOX NET-A-PORTER from May 2018 and moved it to
discontinued operations in November 2022, re-presenting one year of
comparatives. A reader who took the July 2022 first-quarter release and
subtracted it from the November 2022 half-year got a July-September 2022 that is
€610M short and an online retail channel with negative sales. The company
printed the right figure in the same November release. This page takes every
quarter from the latest document that prints it, holds every quarter the company
eventually printed against the subtraction available the day before, and names
the one quarter where the two disagree and why.

Published figures are company-reported or transparent arithmetic. The company
issues no sales or growth guidance; the only numbers it has given about its own
future results are listed in the audit drawer with what followed.

The page is in the site's four parts. One settles what the owner's previous
note left: its follow-up questions as this quarter's note judged them, its
quantified thresholds measured with this quarter's printed figures, and then
the two margin ranges the CFO stated on results calls (checked against the
company's own transcripts). Two is the quarter, which is sales only. Three is
this quarter's note's thresholds for the next one. Four is the long record,
including every half-year profit chart: a sales-only quarter has no profit to
highlight. Thresholds are local research settings, not guidance.

Rolling the page is a data edit (CLAUDE.md §9). Every quarter appends one
column; the interim and the annual results announcement add a half-year as well
(a fiscal year whose annual has not yet come has only its first half, and its
`half_sources` entry has no year document). Every period label, count and figure
in the prose is computed from the series. What belongs to one release sits in
blocks stamped with the period they describe and read through
`board.stamped_block`: the note's follow-up closure and settlement of the
previous note's thresholds (each also naming the quarter it was set in), the
note's thresholds for the next quarter, the company's own streak claim, the
quarter-end net cash and the quarter's story (stamped with the quarter), and the
half's story (stamped with the half). A threshold block names what it measures
and never types the current value. A block stamped for another period stops the
build; an absent optional one takes its sentences with it. Statements about the corpus -- how many documents were
read twice, how many the restatement and guidance censuses covered -- print
their own scope. What stays in this file is fixed history no roll moves: the two
YNAP breaks, the four quarters nobody can separate, the 2018 watch buy-back,
the 2020Q2 regional collapse, the FY22 restatement and the CFO's two ranges.
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import (  # noqa: E402
    ai_capex_cycle_table,
    cn_count,
    cn_ordinal,
    display_period,
    headroom,
    headroom_exhibit,
    latest_block,
    minus_sign,
    number_exhibits,
    stamped_block,
    threshold_exhibit,
    threshold_table,
    unit_text,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402

STAGING_PATH = ROOT / "series" / "cfr.json"
DATA_DIR = ROOT / "data"

# One tick per year on the forty-two-quarter axes. The renderer's own font
# shrinking floors out around thirty labels.
LONG_STEP = 4

REGIONS = ["europe", "asia_pacific", "americas", "japan", "middle_east_africa"]
REGION_NAMES = {"europe": "欧洲", "asia_pacific": "亚太", "americas": "美洲", "japan": "日本",
                "middle_east_africa": "中东与非洲"}
REGION_COLORS = {"europe": "NAVY", "asia_pacific": "RED", "americas": "GOLD", "japan": "GREEN",
                 "middle_east_africa": "GRAY"}
CHANNELS = ["retail", "online_retail", "wholesale"]
CHANNEL_NAMES = {"retail": "零售", "online_retail": "线上零售", "wholesale": "批发与特许权收入"}
AREAS = ["jewellery_maisons", "specialist_watchmakers", "online_distributors", "other"]
AREA_NAMES = {"jewellery_maisons": "珠宝", "specialist_watchmakers": "腕表",
              "online_distributors": "线上分销（YNAP 等）", "other": "其他（时装与配饰等）"}
AREA_COLORS = {"jewellery_maisons": "NAVY", "specialist_watchmakers": "GOLD",
               "online_distributors": "GRAY", "other": "MBLUE"}

# The two basis breaks every group-level quarterly line crosses.
YNAP_IN = "2018Q2"       # consolidated from 1 May 2018
YNAP_OUT = "2021Q2"      # first quarter printed on the continuing-operations basis
HALF_YNAP_IN = "FY19H1"
HALF_YNAP_OUT = "FY22H1"
# A quarter that waited longer than this to be printed as a quarter is "late".
ON_TIME_DAYS = 60
# The announcement that first prints each fiscal quarter: (name before 与, suffix).
RELEASE_KIND = {1: ("第一季度", "销售公告"), 2: ("中期", "业绩公告"),
                3: ("第三季度", "销售公告"), 4: ("全年", "业绩公告")}
# The measures a threshold block may name by `id`: the company's own printed
# constant-rate growth for one line of the sales table, read for the page's quarter.
CER_LINES = {
    "cer_total": "total", "cer_jewellery": "jewellery_maisons", "cer_watchmakers": "specialist_watchmakers",
    "cer_other": "other", "cer_retail": "retail", "cer_online": "online_retail", "cer_wholesale": "wholesale",
    "cer_europe": "europe", "cer_asia_pacific": "asia_pacific", "cer_americas": "americas", "cer_japan": "japan",
    "cer_middle_east_africa": "middle_east_africa",
}
LINE_NAMES = {"total": "集团", "jewellery_maisons": "珠宝", "specialist_watchmakers": "腕表", "other": "其他",
              **REGION_NAMES, **CHANNEL_NAMES}
# A constant-rate line runs to +276% (the Americas, 2021Q2) and -65% (wholesale,
# 2020Q2); a threshold a few points either side of zero is unreadable on that
# axis, so threshold charts cap it here and mark the capped points with their values.
RATE_CAP = 60


def pct(current: float, base: float) -> float:
    return (current / base - 1) * 100.0


def signed(value: float, digits: int = 0, suffix: str = "%") -> str:
    text = f"{value:+.{digits}f}"
    return text.replace("-", "−") + suffix


def eur(value: float) -> str:
    return f"{'−' if value < 0 else ''}€{abs(value):,.0f}M"


def rounded(values, digits: int = 6):
    return [None if v is None else round(v, digits) for v in values]


def share(part, whole):
    return None if part is None or whole in (None, 0) else part / whole * 100.0


def half_end(label: str) -> str:
    """`FY26H1` -> `2025-09`, `FY26H2` -> `2026-03`: the month the half ends."""
    fy = 2000 + int(label[2:4])
    return f"{fy - 1}-09" if label.endswith("H1") else f"{fy}-03"


def half_end_date(label: str) -> str:
    """`FY26H2` -> `2026-03-31`, `FY27H1` -> `2026-09-30`."""
    return half_end(label) + ("-30" if label.endswith("H1") else "-31")


def half_name(label: str) -> str:
    return f"FY{label[2:4]} {'上' if label.endswith('H1') else '下'}半年"


def compact(quarter: str) -> str:
    return quarter


def fiscal_parts(fiscal: str) -> tuple[str, int]:
    """`FY27Q1` -> `('FY27', 1)`."""
    return fiscal[:4], int(fiscal[-1])


def release_name(fiscal: str) -> str:
    """`FY27Q1` -> `FY27 第一季度销售公告`: the announcement that first prints the quarter."""
    fy, number = fiscal_parts(fiscal)
    head, tail = RELEASE_KIND[number]
    return f"{fy} {head}{tail}"


def quarter_months(quarter: str) -> tuple[int, int]:
    """`2026Q2` -> `(4, 6)`."""
    number = int(quarter[-1])
    return 3 * number - 2, 3 * number


def month_of(date: str) -> str:
    """`2026-11-13` -> `11 月`."""
    return f"{int(date[5:7])} 月"


def fill(text: str, values: dict) -> str:
    """Fill a story's `{placeholders}` from the series; an unknown one stops the build."""
    try:
        return text.format_map(values)
    except KeyError as missing:
        raise ValueError(f"a story in the series names {missing}, which this page does not fill") from None


def trailing_run(values: list, test) -> int:
    n = 0
    for v in reversed(values):
        if v is None or not test(v):
            break
        n += 1
    return n


def statement(s: dict, key: str) -> dict:
    return next(x for x in s["statements"] if x["key"] == key)


# ── views: everything the page computes, in one place ───────────────────────
def quarter_view(s: dict) -> dict:
    q = s["quarters"]
    fq = s["fiscal_quarters"]
    e = s["quarterly_eur_m"]
    cer = s["quarterly_cer_pct"]
    act = s["quarterly_actual_pct"]
    basis = s["quarter_basis"]
    last = len(q) - 1
    year_ago = last - 4

    printed = [i for i, b in enumerate(basis) if b == "printed"]
    derived = [i for i, b in enumerate(basis) if b == "derived"]
    missing = [i for i, b in enumerate(basis) if b == "missing"]

    # Jewellery double-digit streak, counted back from the latest quarter on the
    # company's own printed constant-currency rates.
    streak = trailing_run(cer["jewellery_maisons"], lambda v: v >= 10)
    streak_values = cer["jewellery_maisons"][last - streak + 1:] if streak else []
    watch_in_streak = cer["specialist_watchmakers"][last - streak + 1:] if streak else []

    lags = [None if qq not in s["first_printed"] else s["first_printed"][qq]["lag_days"] for qq in q]
    recent = []
    for i in range(last, -1, -1):
        if lags[i] is None or lags[i] > ON_TIME_DAYS:
            break
        recent.append(i)
    late = [lags[i] for i in printed if lags[i] is not None and lags[i] > ON_TIME_DAYS]
    late_quarters = [q[i] for i in printed if lags[i] is not None and lags[i] > ON_TIME_DAYS]

    checks = s["derived_checks"]
    differ = [c for c in checks if c["derived"] != c["printed"]]
    check_quarters = sorted({c["quarter"] for c in checks})
    trap = next(d for d in s["first_print_derivations"] if d["derived_total"] != d["printed_total"])

    fx_gap = [None if c is None or a is None else c - a for c, a in zip(cer["total"], act["total"])]
    fx_both = [v for v in fx_gap if v is not None]

    increment = {k: e[k][last] - e[k][year_ago] for k in REGIONS + ["total"]}
    dtc = [None if e["retail"][i] is None else (e["retail"][i] + (e["online_retail"][i] or 0)) / e["total"][i] * 100
           for i in range(len(q))]

    # the quarters the business-area growth lines cannot draw, and why
    gaps = [i for i, v in enumerate(cer["jewellery_maisons"]) if v is None]
    return {
        "last": last, "year_ago": year_ago,
        "printed": printed, "derived": derived, "missing": missing,
        "streak": streak, "streak_values": streak_values, "watch_in_streak": watch_in_streak,
        "lags": lags, "recent_on_time": recent, "late_lags": late, "late_quarters": late_quarters,
        "checks": checks, "differ": differ, "check_quarters": check_quarters, "trap": trap,
        "fx_gap": fx_gap, "fx_both": fx_both,
        "increment": increment, "dtc": dtc,
        "jewellery_share": [share(a, b) for a, b in zip(e["jewellery_maisons"], e["total"])],
        "watch_share": [share(a, b) for a, b in zip(e["specialist_watchmakers"], e["total"])],
        "region_share": {k: [share(a, b) for a, b in zip(e[k], e["total"])] for k in REGIONS},
        "jewellery_two_year": ((1 + cer["jewellery_maisons"][year_ago] / 100) *
                               (1 + cer["jewellery_maisons"][last] / 100)) ** 0.5 * 100 - 100,
        "gaps": gaps,
        "gaps_q24": [i for i in gaps if fiscal_parts(fq[i])[1] in (2, 4) and q[i] < YNAP_OUT],
        "fiscal": fq[last], "fiscal_ago": fq[year_ago],
    }


def half_view(s: dict) -> dict:
    halves = s["halves"]
    h = s["half_eur_m"]
    seg = s["half_segment_result_eur_m"]
    segs = s["half_segment_sales_eur_m"]
    gross = [share(g, v) for g, v in zip(h["gross_profit"], h["sales"])]
    operating = [share(o, v) for o, v in zip(h["operating_profit"], h["sales"])]
    margin = {k: [share(r, v) for r, v in zip(seg[k], segs[k])] for k in AREAS}
    jewel_of_op = [share(j, o) for j, o in zip(seg["jewellery_maisons"], h["operating_profit"])]

    def after_statement(date: str) -> list[int]:
        # a half counts once it ENDED after the statement was made
        return [i for i, lab in enumerate(halves)
                if datetime.date.fromisoformat(half_end(lab) + "-01") > datetime.date.fromisoformat(date)]

    jr = statement(s, "jewellery_margin_range")
    jewel_after = after_statement(jr["earlier"]["said_on"])
    jm = [share(r, v) for r, v in zip(seg["jewellery_maisons"], segs["jewellery_maisons"])]
    below_after = [i for i in jewel_after if jm[i] < jr["low"]]
    jewel_first_break = bool(below_after) and below_after[0] == len(halves) - 1
    watch_after = after_statement(statement(s, "watchmakers_margin_midterm")["said_on"])
    last = len(halves) - 1

    def last_lower(series: list[float], i: int) -> int | None:
        for k in range(i - 1, -1, -1):
            if series[k] is not None and series[k] < series[i]:
                return k
        return None

    cont = halves.index(HALF_YNAP_OUT)
    over = [i for i, v in enumerate(jewel_of_op) if v is not None and v > 100]
    trailing = trailing_run(jewel_of_op, lambda v: v > 100)
    balance = s["balance"]
    # fiscal years with both halves: is the second half's jewellery margin the lower one?
    years = [(i, i + 1) for i in range(len(halves) - 1)
             if halves[i].endswith("H1") and halves[i + 1] == halves[i][:4] + "H2"]
    h2_lower = sum(1 for a, b in years if jm[b] < jm[a])
    return {
        "halves": halves, "labels": [half_end(x) for x in halves], "last": last,
        "gross": gross, "operating": operating, "margin": margin, "jewel_of_op": jewel_of_op,
        "jewel_after": jewel_after, "watch_after": watch_after, "jewel_first_break": jewel_first_break,
        "jewel_lowest_since": last_lower(margin["jewellery_maisons"], last),
        "gross_continuing_min": min(gross[cont:]), "continuing_halves": len(halves) - cont,
        "over": over, "trailing_over": trailing,
        "inventory_above_cash": sum(1 for b in balance if b["inventories"] > b["net_cash_position"]),
        "balance": balance,
        "derived_last": s["half_basis"][last] == "derived",
        "full_years": len(years), "h2_lower": h2_lower,
    }


def band_state(value: float, low: float, high: float) -> str:
    return "below" if value < low else "above" if value > high else "inside"


# ── what a threshold measures ────────────────────────────────────────────────
def previous_quarter(quarter: str) -> str:
    """`2026Q2` -> `2026Q1`, `2026Q1` -> `2025Q4`."""
    year, number = int(quarter[:4]), int(quarter[5])
    return f"{year - 1}Q4" if number == 1 else f"{year}Q{number - 1}"


def next_quarter(quarter: str) -> str:
    """`2026Q2` -> `2026Q3`, `2026Q4` -> `2027Q1`."""
    year, number = int(quarter[:4]), int(quarter[5])
    return f"{year + 1}Q1" if number == 4 else f"{year}Q{number + 1}"


def two_year_rates(values: list) -> list:
    """Each quarter's two-year stacked constant-rate growth, annualised: the square
    root of (1 + the rate a year earlier) x (1 + this quarter's rate), less one. Only
    where the company printed both rates; a rate is never derived."""
    return [None if i < 4 or values[i] is None or values[i - 4] is None
            else ((1 + values[i - 4] / 100) * (1 + values[i] / 100)) ** 0.5 * 100 - 100
            for i in range(len(values))]


def measure(s: dict, qv: dict, hv: dict, key: str) -> dict:
    """What a threshold key measures: its value now, the record a threshold chart
    draws it against, and how the value was read. Current values are computed here
    and never typed into a threshold block -- a typed value is free to disagree with
    the series it claims to come from."""
    q, last = s["quarters"], qv["last"]
    cer = s["quarterly_cer_pct"]
    quarter_breaks = {"breaks": [q.index(YNAP_IN), q.index(YNAP_OUT)], "break_label": ["YNAP 并表", "持续经营口径"]}
    if key in CER_LINES:
        line = CER_LINES[key]
        values = cer[line]
        if values[last] is None:
            raise ValueError(f"threshold `{key}` reads {line!r} for {q[last]}, which the company did not print")
        return {"now": values[last], "xlabels": list(q), "values": rounded(values), "fmt": "pct0",
                "ylab": "恒定汇率增速 %", "name": f"{LINE_NAMES[line]}恒定汇率增速（公司印出）",
                "how": f"{LINE_NAMES[line]}取本季恒定汇率增速", "line_name": LINE_NAMES[line],
                "unit_word": "季度", "gappy": True, "rate": True, **quarter_breaks,
                "src": "实际值是公司各季公告与业绩公告附录印出的恒定汇率增速。"}
    if key == "jewellery_two_year":
        values = two_year_rates(cer["jewellery_maisons"])
        if values[last] is None:
            raise ValueError("threshold `jewellery_two_year` needs the jewellery rate for this quarter and a year earlier")
        return {"now": round(values[last], 1), "xlabels": list(q), "values": rounded(values, 2), "fmt": "pct1",
                "ylab": "两年叠加年化 %", "name": "珠宝两年恒定汇率叠加年化 D",
                "how": (f"珠宝两年年化取上年同季与本季两个增速连乘开方"
                        f"（{signed(cer['jewellery_maisons'][qv['year_ago']])} 与 {signed(cer['jewellery_maisons'][last])}，"
                        f"{values[last]:.1f}% D）"),
                "unit_word": "季度", "gappy": True, "rate": True, **quarter_breaks,
                "src": "两年年化由公司印出的上年同季与本季两个恒定汇率增速连乘开方得到（D），两个都印出的季度才有。"}
    if key == "half_gross_margin":
        halves, gross, h = hv["halves"], hv["gross"], s["half_eur_m"]
        years = [(i, i + 1) for i in range(len(halves) - 1)
                 if halves[i].endswith("H1") and halves[i + 1] == halves[i][:4] + "H2"]
        first_higher = sum(1 for a, b in years if gross[a] > gross[b])
        last_h1 = max(i for i, label in enumerate(halves) if label.endswith("H1"))
        fy = halves[last_h1][:4]
        coming = f"FY{int(fy[2:]) + 1:02d}H1" if halves[-1].endswith("H2") else fy + "H2"
        context = (f"下一个读数是 {half_name(coming)}。同一财年里上半年的毛利率通常更高：{len(years)} 个完整财年里 "
                   f"{first_higher} 个上半年高于下半年；最近一个上半年（{half_name(halves[last_h1])}）是 "
                   f"{gross[last_h1]:.1f}%")
        if last_h1 + 1 < len(halves) and halves[last_h1 + 1] == fy + "H2":
            year = (h["gross_profit"][last_h1] + h["gross_profit"][last_h1 + 1]) / \
                   (h["sales"][last_h1] + h["sales"][last_h1 + 1]) * 100
            context += f"，{fy} 全年 {year:.1f}%"
        return {"now": round(gross[hv["last"]], 1), "xlabels": hv["labels"], "values": rounded(gross, 2),
                "fmt": "pct1", "ylab": "半年毛利率 %", "name": "集团半年毛利率",
                "how": f"半年毛利率取 {half_name(halves[hv['last']])}{'（D）' if hv['derived_last'] else ''}",
                "unit_word": "半年", "gappy": False, "rate": False, "context": context + "。",
                "breaks": [halves.index(HALF_YNAP_IN), halves.index(HALF_YNAP_OUT)],
                "break_label": ["YNAP 并表", "持续经营口径"],
                "src": "毛利除以销售，取自中期与全年业绩公告的合并损益表；下半年由全年减上半年得到（D）。"}
    if key == "net_cash":
        now = net_cash_now(s)
        if now is None:
            raise ValueError("series block `next_kpi` measures the quarter-end net cash, but the quarter "
                             "does not end a half and `net_cash_quarter_end` is not stamped for it")
        balance = s["balance"]
        labels = [b["date"][:7] for b in balance]
        values = [b["net_cash_position"] / 1000 for b in balance]
        extra = now["date"] != balance[-1]["date"]
        if extra:
            labels.append(now["date"][:7])
            values.append(now["eur_bn"])
        return {"now": now["eur_bn"], "xlabels": labels, "values": rounded(values, 3), "fmt": "f1",
                "ylab": "€B", "name": "净现金" + ("（最后一格是季度公告值，其余是半年末）" if extra else "（半年末）"),
                "how": f"净现金取 {now['date']} 的{now['kind']}", "unit_word": "时点", "gappy": False,
                "rate": False, "date": now["date"], "kind": now["kind"], "quarter_point": extra,
                "src": ("半年末净现金取自中期与全年业绩公告的「net cash position」"
                        + ("；最后一格是季度公告正文给的季末数，只印到 €0.1B。" if extra else "。"))}
    raise ValueError(f"a threshold block names {key!r}, which this page does not know how to measure")


def reading_value(unit: str, value: float) -> str:
    """A growth rate reads `+24%`, the way the company prints it; anything else in its unit."""
    if unit == "pct" and float(value).is_integer():
        return signed(value)
    return unit_text(unit, value)


def threshold_chart(entry: dict, m: dict, value_key: str, title: str, threshold_label: str, reading: str) -> dict:
    """One tracked measure over its own record, against its threshold line."""
    side = "上方" if entry["direction"] == "up" else "下方"
    values = m["values"]
    printed = [i for i, v in enumerate(values) if v is not None]
    unsafe = [i for i in printed
              if (values[i] < entry["threshold"] if entry["direction"] == "up" else values[i] > entry["threshold"])]
    record = f"这条线有数的 {len(printed)} 个{m['unit_word']}里，{len(unsafe)} 个落在阈值的不安全一侧"
    breaks = m.get("breaks")
    if breaks and unsafe:
        inside = [i for i in unsafe if breaks[0] <= i < breaks[1]]
        if inside and len(inside) == len(unsafe):
            record += "，全部在两道断点之间含 YNAP 的那一段"
        elif inside:
            record += f"，其中 {len(inside)} 个在两道断点之间含 YNAP 的那一段"
    chart = threshold_exhibit(
        title, m["xlabels"], values, entry["threshold"],
        fmt=m["fmt"], ylab=m["ylab"], actual_name=m["name"],
        threshold_name=f"{threshold_label}（安全侧在{side}）",
        note=(f"阈值 {minus_sign(unit_text(entry['unit'], entry['threshold']))}，"
              f"当前 {minus_sign(unit_text(entry['unit'], entry[value_key]))}，"
              f"余量 {headroom(entry['direction'], entry['threshold'], entry[value_key]):+.1f}%。"
              + reading + record + "。"
              + ("线上的缺口是公司没有把增速印成单独季度的季度，不画。" if m["gappy"] else "")),
        src_extra="阈值取自所有者的季报笔记（本地研究），不是公司指引。" + m["src"],
        xstep=LONG_STEP if len(m["xlabels"]) > 30 else None,
    )
    chart["xrot"] = 90
    if m["gappy"]:
        # Before 2021Q2 most printed rates stand alone between gaps, and a line
        # with no neighbour on either side draws nothing without a marker.
        chart["markers"] = True
    if breaks:
        chart["break_at"] = list(breaks)
        chart["break_label"] = list(m["break_label"])
    beyond = [(label, v) for label, v in zip(m["xlabels"], values) if v is not None and abs(v) > RATE_CAP]
    high = any(v > 0 for _, v in beyond)
    low = any(v < 0 for _, v in beyond)
    if m["rate"] and beyond:
        if high:
            chart["ycap"] = RATE_CAP
        if low:
            chart["yfloor"] = -RATE_CAP
        chart["cap_note"] = ((f"纵轴截在 ±{RATE_CAP}%：" if high and low else
                              f"纵轴上界截在 +{RATE_CAP}%：" if high else f"纵轴下界截在 −{RATE_CAP}%：")
                             + "、".join(label for label, _ in beyond) + " 以空心圈标出真值")
    return chart


# ── section one (a)(b): what the previous note left to settle ──────────────
def settlement_block(s: dict, key: str) -> dict | None:
    """A block that settles what the previous note set: stamped with this quarter, and
    naming the quarter it was set in, which has to be the quarter before."""
    quarter = s["quarters"][-1]
    block = stamped_block(s, key, display_period(quarter))
    if block is not None and display_period(block["set_in"]) != display_period(previous_quarter(quarter)):
        raise ValueError(f"series block `{key}` settles what was set in {block['set_in']!r}, but the quarter "
                         f"before {display_period(quarter)} is {display_period(previous_quarter(quarter))}")
    return block


def closure_chart(s: dict) -> dict | None:
    """Last note's follow-up questions and how this quarter's note judged each one."""
    block = settlement_block(s, "followup_closure")
    if block is None:
        return None
    labels, items = block["labels"], block["items"]
    stray = sorted({i["verdict"] for i in items} - set(labels))
    if stray:
        raise ValueError(f"series block `followup_closure` has verdicts {stray} outside its labels {labels}")
    counts = [sum(1 for i in items if i["verdict"] == label) for label in labels]
    shown = [(label, count) for label, count in zip(labels, counts) if count]
    structural = [i["topic"] for i in items if i.get("structural")]
    values = {**story_values(s), "structural_count": cn_count(len(structural)),
              "structural_topics": "、".join(structural)}
    return {
        "ref": "EX_CLOSURE",
        "kind": "bars_labeled",
        "title": f"上季 {len(items)} 条待验证问题：" + "、".join(f"{count} 条{label}" for label, count in shown),
        "xlabels": [label for label, _ in shown],
        "values": [count for _, count in shown],
        "legend": "问题条数",
        "fmt": "f0", "yfmt": "f0", "label_fmt": "f0",
        "ylab": "条",
        "note": fill(block["note"], values),
        "src_extra": ("问题清单来自上季笔记末尾的 Follow-up Questions，判定来自本季笔记第 0 节；"
                      "逐条判定的原话见核对抽屉。文中的增速是公司本季公告印出的数。"),
    }


def settlement_words(s: dict, pending: list[dict]) -> str:
    """`2026-11-13 的中期业绩与 2027 年 5 月的全年业绩`, from the pending items' own dates."""
    nxt = next_results(s)[0]
    words = []
    for item in pending:
        date, kind = item["settles"], item["settles_with"]
        if kind == "中期业绩" and date != nxt["date"]:
            raise ValueError(f"a pending threshold settles with the interim results on {date!r}, but "
                             f"latest.next_release is {nxt['date']!r}: update it with the roll")
        text = (f"{date} 的{kind}" if len(date) == 10 else f"{date[:4]} 年 {int(date[5:7])} 月的{kind}")
        if text not in words:
            words.append(text)
    return "与 ".join(words)


def prior_settlement(s: dict, qv: dict, hv: dict) -> tuple[list[dict], dict | None, list[dict]]:
    """The previous note's quantified thresholds, settled with this quarter's figures."""
    block = settlement_block(s, "prior_kpi_settlement")
    if block is None:
        return [], None, []
    entries = []
    for entry in block["quantified"]:
        if "actual" in entry:
            raise ValueError(f"threshold `{entry['id']}` is computed from the series; remove its typed value")
        entries.append({**entry, "actual": measure(s, qv, hv, entry["id"])["now"]})
    held = [e["id"] for e in entries if headroom(e["direction"], e["threshold"], e["actual"]) >= 0]
    breached = [e["id"] for e in entries if e["id"] not in held]
    for key, computed in (("held", held), ("breached", breached)):
        if sorted(block[key]) != sorted(computed):
            raise ValueError(f"series block `prior_kpi_settlement` says {key} = {block[key]}, the data says "
                             f"{computed}: rewrite it for this quarter")
    pending = block.get("pending", [])
    total = len(entries) + len(pending)
    title = (f"上季 {total} 条量化阈值：本季能结算的 {len(entries)} 条"
             + ("都守住" if not breached else f"里 {len(breached)} 条被击穿")
             + (f"，另 {len(pending)} 条要等 {settlement_words(s, pending)}" if pending else ""))
    readings = "；".join(f"{e['metric']}本季 {reading_value(e['unit'], e['actual'])}，"
                         f"本季笔记判定「{e['note_verdict']}」" for e in entries)
    headroom_chart = headroom_exhibit(
        title, entries, "actual",
        note=("正值 = 仍在安全侧。" + readings + "。"
              + (f"还没到期的{cn_count(len(pending))}条：" + "".join(f"「{p['metric']}」" for p in pending)
                 + "，规则、结算日与本季笔记的处置见核对抽屉。" if pending else "")),
        src_extra=(f"阈值与规则取自上季笔记（{block['set_on']}）第 8 节，判定与处置取自本季笔记第 8 节的校准表；"
                   "实际值是公司本季公告印出的恒定汇率增速。阈值是本地研究设定，不是公司指引。"),
    )
    headroom_chart["ref"] = "EX_PRIOR_HEADROOM"
    charts = [headroom_chart]
    for entry in entries:
        m = measure(s, qv, hv, entry["id"])
        held_it = headroom(entry["direction"], entry["threshold"], entry["actual"]) >= 0
        chart = threshold_chart(
            entry, m, "actual",
            f"{entry['metric']}：{'守住' if held_it else '已击穿'}上季阈值 "
            f"{minus_sign(unit_text(entry['unit'], entry['threshold']))}",
            "上季阈值",
            f"上季笔记的规则是「{entry['rule']}」，本季笔记判定「{entry['note_verdict']}」，处置：{entry['disposal']}。")
        chart["ref"] = f"EX_PRIOR_{entry['id'].upper()}"
        charts.append(chart)
    return charts, block, entries


# ── section one (c): the numbers the company did give ───────────────────────
def said_section(s: dict, hv: dict) -> list[dict]:
    labels = hv["labels"]
    n = len(labels)
    d = " D" if hv["derived_last"] else ""

    jm = hv["margin"]["jewellery_maisons"]
    jr = statement(s, "jewellery_margin_range")
    after = hv["jewel_after"]
    inside = sum(1 for i in after if jr["low"] <= jm[i] <= jr["high"])
    below = [i for i in after if jm[i] < jr["low"]]
    above = [i for i in after if jm[i] > jr["high"]]
    last = hv["last"]
    low_since = hv["jewel_lowest_since"]
    first_below = below[0] if below else None
    quote = "it's not a guidance, it's an indication of the range in which we are comfortable, 30% to 35%"
    if quote not in jr["quote"]:
        raise ValueError("the jewellery note quotes words the statement record does not carry")
    if low_since is None:
        lowest = f"是图上 {n} 个半年里最低"
    elif low_since < last - 1:
        lowest = f"{half_name(hv['halves'][low_since])}以来最低"
    else:
        lowest = ""
    lead = (f"{half_name(hv['halves'][last])} {jm[last]:.1f}%{d}"
            + ("，是这句话之后第一次跌破下沿" if first_below == last else "")
            + (("、" if first_below == last else "，") + lowest if lowest else ""))
    systematic = hv["full_years"] and hv["h2_lower"] * 2 > hv["full_years"]
    jewel = {
        "ref": "EX_JEWEL_BAND",
        "kind": "lines",
        "title": (f"珠宝半年经营利润率：CFO 说「舒适区间」是 {jr['low']:.0f}–{jr['high']:.0f}%，"
                  f"那之后的 {len(after)} 个半年里 {inside} 个在区间内；{lead}"),
        "xlabels": labels,
        "xrot": 90,
        "series": [
            {"name": "珠宝分部半年经营利润率", "values": rounded(jm, 2), "color": "NAVY"},
            {"name": f"区间下沿 {jr['low']:.0f}%", "values": [jr["low"]] * n, "color": "RED"},
            {"name": f"区间上沿 {jr['high']:.0f}%", "values": [jr["high"]] * n, "color": "GRAY"},
        ],
        "fmt": "pct1", "yfmt": "pct0", "label_fmt": "pct1",
        "end_label": True,
        "ylab": "半年经营利润率 %",
        "note": (
            "<b>这不是指引，CFO 自己这么说；但它和下一张图的腕表区间一样，能用半年数据结算。</b>"
            f"{jr['earlier']['said_on']} 的中期业绩电话会上，分析师引用「30% 到 35%」问能否上调，"
            "CFO 答仍对这个区间感到舒适；"
            f"{jr['said_on']} 的电话会上 CFO 原话：「{quote}」。"
            f"图上 {n} 个点，每个标签是该半年的最后一个月：9 月是 4–9 月的上半年，3 月是 10–3 月的下半年。"
            "下半年由全年减上半年得到（D）。"
            f"那句话之后 {len(after)} 个半年：{inside} 个在区间内，{len(above)} 个高于上沿，"
            f"{len(below)} 个低于下沿。"
            + ("<b>下半年系统性低于上半年</b>，所以要拿下半年和下半年比。" if systematic else "")),
        "src_extra": (
            "分部经营利润与分部销售取自各期中期与全年业绩公告的分部表；H2 = 全年 − 上半年，"
            "两者取同一代口径的文件（逐年所用文件见核对抽屉）。珠宝分部的经营利润在窗口内的每一次重述里"
            "都没有变过，所以这条线不跨口径。区间原话取自 FY23 与 FY24 中期业绩电话会记录。"),
    }

    wm = hv["margin"]["specialist_watchmakers"]
    wr = statement(s, "watchmakers_margin_midterm")
    wafter = hv["watch_after"]
    winside = [i for i in wafter if wr["low"] <= wm[i] <= wr["high"]]
    wbelow = [i for i in wafter if wm[i] < wr["low"]]
    said_idx = max(i for i in range(n) if i not in wafter)
    story = half_story(s)
    watch = {
        "ref": "EX_WATCH_BAND",
        "kind": "lines",
        "title": (f"腕表半年经营利润率：CFO 说中期有潜力到 {wr['low']:.0f}–{wr['high']:.0f}%，"
                  f"说的时候上一个半年是 {wm[said_idx]:.1f}%；此后 {len(wafter)} 个半年只有 "
                  f"{len(winside)} 个落在区间里，{half_name(hv['halves'][last])} {wm[last]:.1f}%{d}"),
        "xlabels": labels,
        "xrot": 90,
        "series": [
            {"name": "腕表分部半年经营利润率", "values": rounded(wm, 2), "color": "GOLD"},
            {"name": f"中期区间下沿 {wr['low']:.0f}%", "values": [wr["low"]] * n, "color": "RED"},
            {"name": f"中期区间上沿 {wr['high']:.0f}%", "values": [wr["high"]] * n, "color": "GRAY"},
        ],
        "fmt": "pct1", "yfmt": "pct0", "label_fmt": "pct1",
        "end_label": True,
        "ylab": "半年经营利润率 %",
        "note": (
            f"{wr['said_on']} 的中期业绩电话会上，分析师问「mid to high-teen」是否仍是腕表分部的长期利润率潜力，"
            f"CFO 原话：「{wr['quote']}」。"
            f"说这句话之后的 {len(wafter)} 个半年，{len(winside)} 个在区间内、{len(wbelow)} 个低于下沿。"
            + (story_text(s, story, "watchmakers") if story else "")),
        "src_extra": (
            "同上一张图的分部表与取数规则。FY19 的腕表经营利润在 FY20 年报里被重述过 €3M"
            "（收购相关摊销移出分部），本页的 FY19 两个半年用 FY19 自己的文件，不跨口径。"),
    }
    return [jewel, watch]


# ── the stories: blocks stamped with the period they describe ────────────────
def next_results(s: dict) -> tuple[dict, str]:
    """`latest.next_release` is the next announcement that carries profit.

    Profit comes only with the interim and the annual results, so the page's
    「下一次利润数据」 and the thresholds that wait for it point there; a
    first- or third-quarter sales update in that slot would send the reader to a
    document with no profit in it.
    """
    nxt = s["latest"]["next_release"]
    label = nxt["label"].lower()
    if "interim" in label:
        return nxt, "中期业绩"
    if "annual" in label:
        return nxt, "全年业绩"
    raise ValueError(f"latest.next_release is {nxt['label']!r}: it names the next results announcement "
                     "(interim or annual), because profit is published only there")


def story_values(s: dict) -> dict:
    """What a story's `{placeholders}` may name: dates from the series, and the quarter's
    printed constant-rate growth for each line (`{cer_jewellery}` -> `+24%`)."""
    bm = s["baume_mercier"]
    nxt = next_results(s)[0]["date"]
    cer = s["quarterly_cer_pct"]
    values = {"next_date": nxt, "next_month": month_of(nxt), "announced": bm["announced"],
              "held_for_sale_at": bm["held_for_sale_at"], "write_down_eur_m": bm["write_down_eur_m"]}
    if bm.get("completed_on"):
        values["bm_completed"] = bm["completed_on"]
    for key, line in CER_LINES.items():
        if cer[line][-1] is not None:
            values[key] = signed(cer[line][-1])
    return values


def story_text(s: dict, story: dict, key: str) -> str:
    return fill(story[key], story_values(s)) if story.get(key) else ""


def quarter_story(s: dict) -> dict | None:
    return stamped_block(s, "quarter_story", display_period(s["quarters"][-1]))


def half_story(s: dict) -> dict | None:
    return stamped_block(s, "half_story", s["halves"][-1])


def company_claim(s: dict, key: str) -> dict | None:
    block = stamped_block(s, "company_claims", display_period(s["quarters"][-1]))
    if block is None:
        return None
    return next((c for c in block["items"] if c["key"] == key), None)


def quarter_net_cash(s: dict) -> dict | None:
    block = stamped_block(s, "net_cash_quarter_end", display_period(s["quarters"][-1]))
    if block is not None and block["date"] != s["latest"]["period_end"]:
        raise ValueError(f"series block `net_cash_quarter_end` is dated {block['date']!r}, "
                         f"but the quarter ends {s['latest']['period_end']!r}")
    return block


def net_cash_now(s: dict) -> dict | None:
    """The net cash at the page's quarter end: the trading update's own figure when the
    quarter's block gives one, the half-year balance sheet when the quarter ends a half."""
    block = quarter_net_cash(s)
    if block is not None:
        return {"eur_bn": block["eur_bn"], "date": block["date"], "kind": "季度公告值"}
    balance = s["balance"][-1]
    if balance["date"] == s["latest"]["period_end"]:
        return {"eur_bn": balance["net_cash_position"] / 1000, "date": balance["date"], "kind": "半年末值"}
    return None


def latest_document(s: dict) -> dict:
    """The announcement that first printed the page's quarter, and its entry in `sources`."""
    first = s["first_printed"].get(s["quarters"][-1])
    if first is None:
        raise ValueError(f"series `first_printed` has no entry for {s['quarters'][-1]!r}")
    doc = next(d for d in s["documents"] if d["doc_id"] == first["doc"])
    source = next((x for x in s["sources"] if x["url"] == doc["url"]), None)
    if source is None:
        raise ValueError(f"series `sources` has no entry for {doc['doc_id']!r}: add this quarter's announcement")
    return {**doc, "label": source["label"]}


# ── section two: the quarter ─────────────────────────────────────────────────
def quarter_section(s: dict, qv: dict) -> list[dict]:
    q = s["quarters"]
    e = s["quarterly_eur_m"]
    cer = s["quarterly_cer_pct"]
    act = s["quarterly_actual_pct"]
    last, ya = qv["last"], qv["year_ago"]
    n = len(q)
    breaks = [q.index(YNAP_IN), q.index(YNAP_OUT)]
    story = quarter_story(s)
    fy_now, number = fiscal_parts(qv["fiscal"])
    fy_ago, _ = fiscal_parts(qv["fiscal_ago"])
    head, tail = RELEASE_KIND[number]

    sales = {
        "ref": "EX_SALES",
        "kind": "gs_bar",
        "title": (f"集团销售：本季 {eur(e['total'][last])}，恒定汇率 {signed(cer['total'][last])}、"
                  f"实际汇率 {signed(act['total'][last])}；{n} 季里 {len(qv['printed'])} 季是公司印出的，"
                  f"{len(qv['derived'])} 季本页减出，{len(qv['missing'])} 季拆不出来"),
        "xlabels": list(q),
        "xrot": 90,
        "xstep": LONG_STEP,
        "values": rounded(e["total"]),
        "legend": "季度销售",
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "€M",
        "ylab2": "恒定汇率增速",
        "yoy": {"name": "恒定汇率增速，公司印出 (RHS)", "values": rounded(cer["total"]),
                "color": "GREEN", "yfmt": "pct0"},
        "bar_marks": qv["derived"],
        "mark_note": "本页减出（D）",
        "break_at": breaks,
        "break_label": ["YNAP 并表", "YNAP 改列终止经营"],
        "note": (
            "<b>柱子之间有两道口径断点。</b>2018 年 5 月起 YOOX NET-A-PORTER 并表，"
            f"2021Q2 起是持续经营口径（公司在 2022 年 11 月改列并重述了一年）。"
            f"<b>{cn_count(len(qv['missing']))}个空格不是缺数据，是公司从来没印过：</b>"
            f"{', '.join(q[i] for i in qv['missing'])}"
            "（FY17 与 FY18 的第一、二财季）：那几年公司在 9 月股东大会只报 4–8 月「前五个月」的增速，"
            "只有那五个月和整个上半年，拆不回两个季度。"
            f"斜纹的 {len(qv['derived'])} 根柱子是本页减出来的：全年减前九个月、或上半年减第一季。"
            "绿线是公司自己印出的恒定汇率增速，只在公司把它印成单独季度的那一季才有 —— "
            "增速不能相减，所以减出来的季度没有增速。"
            f"FY22 的四个季度绿线取的是当年公告（含 YNAP）的增速，柱子取的是一年后重述的持续经营额。"),
        "src_extra": (
            "每个季度的金额取自印出该季度的最后一份公告（逐季来历见核对抽屉）；"
            "增速取自该季度所属财年的公告。每一列都用三条恒等式核过：五个地区、三个渠道、"
            "业务板块加抵销各自加总等于合计。"),
    }

    region_now = {
        "ref": "EX_REGION_NOW",
        "kind": "grouped_bars",
        "title": None,  # filled below
        "xlabels": [REGION_NAMES[k] for k in REGIONS] + ["集团"],
        "groups": [
            {"name": f"本季 {q[last]}", "color": "NAVY",
             "values": [cer[k][last] for k in REGIONS + ["total"]]},
            {"name": f"上年同季 {q[ya]}", "color": "GRAY",
             "values": [cer[k][ya] for k in REGIONS + ["total"]]},
        ],
        "fmt": "pct0", "yfmt": "pct0", "label_fmt": "pct0",
        "ylab": "恒定汇率增速 %",
    }
    swings = {k: cer[k][last] - cer[k][ya] for k in REGIONS}
    up = max(REGIONS, key=lambda k: swings[k])
    down = min(REGIONS, key=lambda k: swings[k])
    region_now["title"] = (
        f"本季各地区恒定汇率增速：{REGION_NAMES[up]} {signed(cer[up][last])}（上年同季 {signed(cer[up][ya])}），"
        f"{REGION_NAMES[down]} {signed(cer[down][last])}（上年同季 {signed(cer[down][ya])}）")
    # the region whose two growth rates differ most is the one to read with the currency
    fx_region = max(REGIONS, key=lambda k: abs(cer[k][last] - act[k][last]))
    fx_gap = cer[fx_region][last] - act[fx_region][last]
    fx_text = ""
    if abs(fx_gap) >= 5:
        why = (f"差额是日元对欧元{'贬值' if fx_gap > 0 else '升值'}" if fx_region == "japan"
               else f"差额是汇率{'拖累' if fx_gap > 0 else '助推'}")
        fx_text = (f"<b>{REGION_NAMES[fx_region]}那一格要和实际汇率一起读：</b>恒定汇率 "
                   f"{signed(cer[fx_region][last])}，实际汇率 {signed(act[fx_region][last])}，{why}。")
    story_note = ""
    if story:
        explained = story.get("region_explanation")
        if explained:
            r = explained["region"]
            story_note += (f"{REGION_NAMES[r]}从上年同季的 {signed(cer[r][ya])} "
                           f"{'掉到' if cer[r][last] < cer[r][ya] else '升到'} {signed(cer[r][last])}，"
                           f"{explained['text']}。")
        story_note += story_text(s, story, "china")
    region_now["note"] = fx_text + story_note
    region_now["src_extra"] = f"{release_name(qv['fiscal'])}与 {release_name(qv['fiscal_ago'])}的销售表。"

    # ── business areas
    streak = qv["streak"]
    claim = company_claim(s, "jewellery_streak")
    if streak >= 2:
        area_title = (f"三块业务的恒定汇率增速：珠宝连续 {streak} 个季度两位数"
                      f"（{signed(qv['streak_values'][0])} → {signed(qv['streak_values'][-1])}），"
                      f"腕表同样这 {streak} 个季度里 {sum(1 for v in qv['watch_in_streak'] if v < 0)} 个为负")
    else:
        area_title = (f"三块业务的恒定汇率增速：珠宝本季 {signed(cer['jewellery_maisons'][last])}，"
                      f"腕表 {signed(cer['specialist_watchmakers'][last])}")
    claim_text = ""
    if claim is not None:
        holds = claim["count"] == streak
        claim_text = (f"<b>「第{cn_ordinal(claim['count'])}个连续双位数季度」是公司在本季公告里的原话，"
                      f"本页逐季核过：{'成立' if holds else f'不成立，本页逐季数到 {streak} 个'}。</b>")
    sequence = ""
    if streak:
        before = cer["jewellery_maisons"][last - streak] if last - streak >= 0 else None
        sequence = (f"序列是 {'、'.join(signed(v) for v in qv['streak_values'])}"
                    + (f"，再往前一季是 {signed(before)}。" if before is not None else "，再往前一季没有印出增速。"))
    q24 = qv["gaps_q24"]
    later = [i for i in qv["gaps"] if s["quarter_basis"][i] == "printed"]
    derived_gaps = [i for i in qv["gaps"] if s["quarter_basis"][i] == "derived"]
    missing_gaps = [i for i in qv["gaps"] if s["quarter_basis"][i] == "missing"]
    q1_gaps = [i for i in qv["gaps"] if i not in q24]
    text_rates = [x for x in s["text_quarter_rates"]
                  if x["line"] == "total" and x["quarter"] in q and q.index(x["quarter"]) in qv["gaps"]]
    area = {
        "ref": "EX_AREA_CER",
        "kind": "lines",
        "title": area_title,
        "xlabels": list(q),
        "xrot": 90,
        "xstep": LONG_STEP,
        "series": [
            {"name": "珠宝", "values": rounded(cer["jewellery_maisons"]), "color": "NAVY"},
            {"name": "腕表", "values": rounded(cer["specialist_watchmakers"]), "color": "GOLD"},
            {"name": "其他（时装与配饰等）", "values": rounded(cer["other"]), "color": "MBLUE"},
        ],
        "fmt": "pct0", "yfmt": "pct0", "label_fmt": "pct0",
        "end_label": True,
        "markers": True,
        "ycap": 60,
        "yfloor": -60,
        "cap_note": "纵轴截在 ±60%：2020Q2 的疫情下跌与 2021Q2 的反弹以空心圈标出真值",
        "ylab": "恒定汇率增速 %",
        "break_at": breaks,
        "break_label": ["YNAP 并表", "持续经营口径"],
        "note": (
            claim_text + sequence
            + f"线上的缺口是公司没有在销售表里按单独季度印过增速的季度：{YNAP_OUT} 之前的第二、四财季"
            + ("，以及「前五个月」那几年的第一财季" if q1_gaps else "")
            + f"。它们在表里最多只有金额（{len(qv['gaps'])} 个缺口里 {len(later)} 个"
            + ("在季末一年多以后才第一次被印成单独季度" if later and min(qv["lags"][i] for i in later) > 365
               else "后来才被印成单独季度")
            + f"，{len(derived_gaps)} 个只能减出，{len(missing_gaps)} 个连金额也拆不出来"
            + (f"；其中 {len(text_rates)} 个季度公司在正文里给过集团合计的单季增速："
               + "、".join(f"{x['quarter']} {signed(x['cer_pct'])}" for x in text_rates) if text_rates else "")
            + "），恒定汇率增速不能由上半年减第一季算出来，本页不补。"),
        "src_extra": "各季度公告与业绩公告附录里的季度表，均为公司印出的恒定汇率增速。",
    }

    inc = qv["increment"]
    ranked = sorted(REGIONS, key=lambda k: inc[k], reverse=True)
    first, second, least = ranked[0], ranked[1], ranked[-1]
    same_doc = (s["quarter_sources"][q[ya]].get("value_doc") == s["quarter_sources"][q[last]].get("value_doc"))
    increment = {
        "ref": "EX_INCREMENT",
        "kind": "bars_labeled",
        "title": (f"本季比上年同季{'多卖' if inc['total'] >= 0 else '少卖'} {eur(abs(inc['total']))}："
                  f"{REGION_NAMES[first]} {eur(inc[first])}、{REGION_NAMES[second]} {eur(inc[second])}，"
                  f"{REGION_NAMES[least]}{'只有 ' if inc[least] >= 0 else ' '}{eur(inc[least])}"),
        "xlabels": [REGION_NAMES[k] for k in REGIONS] + ["集团合计"],
        "values": [inc[k] for k in REGIONS + ["total"]],
        "legend": "欧元增量（实际汇率）",
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "€M",
        "note": (
            "增量按实际汇率算，所以包含汇率"
            + (f"：{REGION_NAMES[fx_region]}那一根比恒定汇率口径{'小' if fx_gap > 0 else '大'}得多。"
               if abs(fx_gap) >= 5 else "。")
            + (f"两个季度的金额取自同一份公告的本期列与上年同期列（{s['latest']['release_date']}），不跨口径。"
               if same_doc else "两个季度的金额各自取自印出它的最后一份公告（见核对抽屉）。")),
        "src_extra": f"{release_name(qv['fiscal'])}销售表，本期减上年同期。",
    }
    if min(increment["values"]) < 0:
        # `bars_labeled` draws from a zero floor, so a region that sold less than a
        # year earlier would be painted below the plot; the grouped form carries
        # negatives and the same per-bar labels.
        values = increment.pop("values")
        increment.update(kind="grouped_bars", bar_labels=True,
                         groups=[{"name": increment.pop("legend"), "color": "NAVY", "values": values}])

    channel = {
        "ref": "EX_CHANNEL_NOW",
        "kind": "grouped_bars",
        "title": (f"渠道：零售 {signed(cer['retail'][last])}、线上 {signed(cer['online_retail'][last])}、"
                  f"批发与特许权收入 {signed(cer['wholesale'][last])}；零售与批发差 "
                  f"{cer['retail'][last] - cer['wholesale'][last]:.0f}pp，上年同季差 "
                  f"{cer['retail'][ya] - cer['wholesale'][ya]:.0f}pp"),
        "xlabels": [CHANNEL_NAMES[k] for k in CHANNELS],
        "groups": [
            {"name": f"本季 {q[last]}", "color": "NAVY", "values": [cer[k][last] for k in CHANNELS]},
            {"name": f"上年同季 {q[ya]}", "color": "GRAY", "values": [cer[k][ya] for k in CHANNELS]},
        ],
        "fmt": "pct0", "yfmt": "pct0", "label_fmt": "pct0",
        "ylab": "恒定汇率增速 %",
        "note": (
            f"零售与线上零售合计占本季销售 {qv['dtc'][last]:.1f}%。"
            "批发这一行包含特许权收入：FY19 年报到 FY20 年报之间公司把特许权收入单列过一行，"
            "本页把它并回批发，让这一行在窗口里只有一个定义。"),
        "src_extra": f"{fy_now} {head}与 {fy_ago} {head}{tail}的渠道表。",
    }
    return [sales, two_year_chart(s, qv), area, area_increment_chart(s, qv), region_now, increment, channel]


TWO_YEAR_LINES = ["total", "jewellery_maisons", "specialist_watchmakers", "other"]


def base_effect(s: dict, qv: dict) -> dict:
    """The quarter's rate against the rate it was measured on, for the group and the
    three business areas; and, for the group, the rate the next quarter would need to
    keep the two-year stack where it is, given the base the next quarter is measured on."""
    cer = s["quarterly_cer_pct"]
    last, ya = qv["last"], qv["year_ago"]
    two = {k: two_year_rates(cer[k])[last] for k in TWO_YEAR_LINES}
    missing = [k for k, v in two.items() if v is None]
    if missing:
        raise ValueError(f"the two-year view needs this quarter's and the year-ago rate for {missing}")
    stack = (1 + cer["total"][ya] / 100) * (1 + cer["total"][last] / 100)
    bases = [cer["total"][ya + k] for k in (1, 2, 3)]
    keep = None if bases[0] is None else stack / (1 + bases[0] / 100) * 100 - 100
    return {"two": two, "stack": stack * 100 - 100, "bases": bases, "keep": keep,
            "now": cer["total"][last], "ago": cer["total"][ya]}


def two_year_chart(s: dict, qv: dict) -> dict:
    """The quarter's rate against the rate it was measured on: the base effect.

    Every growth rate here is the company's own; the two-year figure multiplies the
    year-ago rate by this quarter's and takes the square root. Each rate was struck at
    its own base-year average exchange rates, so the product is an approximation.
    """
    cer = s["quarterly_cer_pct"]
    last, ya = qv["last"], qv["year_ago"]
    be = base_effect(s, qv)
    two = be["two"]
    names = [LINE_NAMES[k] for k in TWO_YEAR_LINES]
    ahead = ""
    if None not in be["bases"]:
        ahead = (f"接下来三个季度的上年同季分别是 {'、'.join(signed(v) for v in be['bases'])}：下一季要约 "
                 f"{signed(be['keep'], 1)}（D）才能让两年叠加保持不变。")
    stack = 1 + be["stack"] / 100
    return {
        "ref": "EX_TWO_YEAR",
        "kind": "grouped_bars",
        "title": (f"本季集团恒定汇率 {signed(cer['total'][last])} 是踩在上年同季 {signed(cer['total'][ya])} 上的："
                  f"两年叠加年化 {signed(two['total'], 1)}；珠宝 {signed(two['jewellery_maisons'], 1)}、"
                  f"腕表 {signed(two['specialist_watchmakers'], 1)}"),
        "xlabels": names,
        "groups": [
            {"name": f"上年同季 {s['quarters'][ya]}", "color": "GRAY", "values": [cer[k][ya] for k in TWO_YEAR_LINES]},
            {"name": f"本季 {s['quarters'][last]}", "color": "NAVY", "values": [cer[k][last] for k in TWO_YEAR_LINES]},
            {"name": "两年叠加年化 D", "color": "GOLD", "values": [round(two[k], 2) for k in TWO_YEAR_LINES]},
        ],
        "fmt": "pct1", "yfmt": "pct0", "label_fmt": "pct1",
        "bar_labels": True,
        "ylab": "恒定汇率增速 %",
        "note": (
            f"两年叠加 = (1 + 上年同季增速) × (1 + 本季增速) − 1，集团是 {signed(stack * 100 - 100, 1)}；"
            "年化取它的平方根。两个增速各自用上一个完整财年的平均汇率折算，基准汇率在两年之间换过一次，"
            "所以叠加只是近似。" + ahead),
        "src_extra": "各季度公告与业绩公告附录里公司印出的恒定汇率增速；叠加与年化为本页自算（D）。",
    }


def area_increment_chart(s: dict, qv: dict) -> dict:
    """Where the quarter's extra euros came from, by business area."""
    e = s["quarterly_eur_m"]
    last, ya = qv["last"], qv["year_ago"]
    areas = [k for k in AREAS if e[k][last] is not None and e[k][ya] is not None]
    inc = {k: e[k][last] - e[k][ya] for k in areas + ["total"]}
    residual = inc["total"] - sum(inc[k] for k in areas)
    lead = max(areas, key=lambda k: inc[k])
    rest = [k for k in areas if k != lead]
    if inc["total"] > 0:
        title = (f"本季比上年同季多卖的 {eur(inc['total'])} 里，{LINE_NAMES[lead]}占 {eur(inc[lead])}"
                 f"（{inc[lead] / inc['total'] * 100:.1f}%）；"
                 + "、".join(f"{LINE_NAMES[k]} {eur(inc[k])}" for k in rest))
    else:
        title = (f"本季比上年同季{'少卖' if inc['total'] < 0 else '持平，变化'} {eur(abs(inc['total']))}："
                 + "、".join(f"{LINE_NAMES[k]} {eur(inc[k])}" for k in areas))
    chart = {
        "ref": "EX_AREA_INCREMENT",
        "kind": "bars_labeled",
        "title": title,
        "xlabels": [LINE_NAMES[k] for k in areas] + ["集团合计"],
        "values": [inc[k] for k in areas + ["total"]],
        "legend": "欧元增量（实际汇率）",
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "€M",
        "note": ("增量按实际汇率算，含汇率。"
                 + (f"{cn_count(len(areas))}块业务的增量加起来等于集团合计。" if residual == 0 else
                    f"{cn_count(len(areas))}块业务之外还有 {eur(residual)} 是板块之间的抵销。")),
        "src_extra": f"{release_name(qv['fiscal'])}的业务板块表，本期减上年同期。",
    }
    if min(chart["values"]) < 0:
        values = chart.pop("values")
        chart.update(kind="grouped_bars", bar_labels=True,
                     groups=[{"name": chart.pop("legend"), "color": "NAVY", "values": values}])
    return chart


def fx_chart(s: dict, qv: dict) -> dict:
    """Constant-rate minus actual-rate growth over the whole record: a routine series.

    The quarter's own currency story is the region whose two rates differ most,
    told under the regional chart in section two; this chart is the long record.
    """
    q = s["quarters"]
    gap_now = qv["fx_gap"][qv["last"]]
    return {
        "ref": "EX_FX_GAP",
        "kind": "diverging_bars",
        "title": (f"恒定汇率减实际汇率：两个增速都被印出的 {len(qv['fx_both'])} 个季度里，"
                  f"{sum(1 for v in qv['fx_both'] if v > 0)} 个是汇率拖累；"
                  + (f"本季恒定汇率比实际汇率{'高' if gap_now > 0 else '低'} {abs(gap_now):.0f}pp"
                     if gap_now else "本季两者相同")),
        "xlabels": list(q),
        "xrot": 90,
        "xstep": LONG_STEP,
        "values": rounded(qv["fx_gap"]),
        "legend": "恒定汇率增速 − 实际汇率增速",
        "positive_label": "汇率拖累（恒定汇率高于实际）",
        "negative_label": "汇率助推",
        "fmt": "pp0", "yfmt": "pp0", "label_fmt": "pp0",
        "ylab": "pp",
        "zero_line": True,
        "note": (
            "两个增速都是公司印出的整数百分比，差额因此也是整数 —— 1pp 以内的差不要读。"
            "恒定汇率增速用上一个完整财年的平均汇率同时折算本期与比较期，所以基准汇率每年换一次。"),
        "src_extra": "各季度公告与业绩公告附录里公司印出的两个增速。",
    }


# ── section four: the half-years (profit comes only by the half) ─────────────
def half_section(s: dict, hv: dict) -> list[dict]:
    labels = hv["labels"]
    halves = hv["halves"]
    last = hv["last"]
    h = s["half_eur_m"]
    derived_idx = [i for i, b in enumerate(s["half_basis"]) if b == "derived"]
    breaks = [halves.index(HALF_YNAP_IN), halves.index(HALF_YNAP_OUT)]
    d = " D" if hv["derived_last"] else ""
    story = half_story(s)

    margins = {
        "ref": "EX_MARGINS",
        "kind": "lines",
        "title": (f"集团半年毛利率与经营利润率：{half_name(halves[last])} {hv['gross'][last]:.1f}%{d} 与 "
                  f"{hv['operating'][last]:.1f}%{d}；毛利率是持续经营口径 {hv['continuing_halves']} 个半年里"
                  + ("最低" if hv["gross"][last] == hv["gross_continuing_min"] else "不是最低")),
        "xlabels": labels,
        "xrot": 90,
        "series": [
            {"name": "毛利率", "values": rounded(hv["gross"], 2), "color": "NAVY"},
            {"name": "经营利润率", "values": rounded(hv["operating"], 2), "color": "GOLD"},
        ],
        "fmt": "pct1", "yfmt": "pct0", "label_fmt": "pct1",
        "end_label": True,
        "zero_base": True,
        "ylab": "占半年销售 %",
        "break_at": breaks,
        "break_label": ["YNAP 并表", "持续经营口径"],
        "note": (
            f"<b>两道断点之间的{cn_count(breaks[1] - breaks[0])}个半年含 YNAP</b>，那是一个低毛利、亏损的线上分销业务，"
            "所以 FY19–FY21 的利润率不能和两端直接比。FY22 两个半年用的是 FY23 公告重述后的持续经营口径。"
            "FY20 起采用 IFRS 16，比较期未重述。"
            + (story_text(s, story, "margins") if story else "")),
        "src_extra": "中期与全年业绩公告的合并损益表；H2 = 全年 − 上半年，逐年所用文件见核对抽屉。",
    }

    seg = s["half_segment_result_eur_m"]
    share_op = {
        "ref": "EX_JEWEL_OP",
        "kind": "bar_line_dual",
        "title": (f"{len(halves)} 个半年里 {len(hv['over'])} 个，珠宝一个分部的经营利润比集团经营利润还多；"
                  + (f"最近 {hv['trailing_over']} 个半年连续如此（{half_name(halves[last])} {hv['jewel_of_op'][last]:.0f}%）"
                     if hv["trailing_over"] >= 2 else
                     f"{half_name(halves[last])} 是 {hv['jewel_of_op'][last]:.0f}%")),
        "xlabels": labels,
        "xrot": 90,
        "bar": {"name": "集团半年经营利润", "values": rounded(h["operating_profit"]), "color": "NAVY"},
        "line": {"name": "珠宝分部经营利润 ÷ 集团经营利润 (RHS)", "values": rounded(hv["jewel_of_op"], 2),
                 "color": "RED", "yfmt": "pct0"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "€M",
        "ylab2": "珠宝 ÷ 集团 %",
        "bar_marks": derived_idx,
        "break_at": breaks,
        "break_label": ["YNAP 并表", "持续经营口径"],
        "note": (
            "超过 100% 的意思是：腕表、其他业务与总部费用合计在亏钱，珠宝的利润替它们补上了。"
            f"{half_name(halves[last])}，腕表分部经营利润 {eur(seg['specialist_watchmakers'][last])}{d}，"
            f"其他业务 {eur(seg['other'][last])}{d}，"
            f"未分配的总部费用 {eur(seg['unallocated_corporate_costs'][last])}{d}。"),
        "src_extra": "分部表与合并损益表；比值为本页自算（D）。",
    }

    bal = hv["balance"]
    net_cash = quarter_net_cash(s)
    quarter_cash = ""
    if net_cash is not None:
        quarter_cash = (f"季度公告另给过一个季末净现金：{net_cash['date']} 为 €{net_cash['eur_bn']:.1f}B"
                        + "".join(f"，其中包含{x['what']}的 €{x['eur_bn']:.1f}B" for x in net_cash.get("includes", []))
                        + "；" + net_cash.get("dividend_note", ""))
    cash = {
        "ref": "EX_CASH",
        "kind": "bar_line_dual",
        "title": (f"净现金 {eur(bal[-1]['net_cash_position'])}（{bal[-1]['date'][:7]}），库存 "
                  f"{eur(bal[-1]['inventories'])}；{len(bal)} 个半年末里库存有 {hv['inventory_above_cash']} 个高于净现金"),
        "xlabels": [b["date"][:7] for b in bal],
        "xrot": 90,
        "bar": {"name": "净现金（半年末）", "values": [b["net_cash_position"] for b in bal], "color": "NAVY"},
        "line": {"name": "库存 (RHS)", "values": [b["inventories"] for b in bal], "color": "GOLD", "yfmt": "f0c"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "净现金 €M",
        "ylab2": "库存 €M",
        "note": ("2018 年那一截净现金的下台阶是收购 YNAP 与 Watchfinder 的现金支出。" + quarter_cash),
        "src_extra": "中期与全年业绩公告的资产负债表与「net cash position」，均为当期首次印出值。",
    }
    return [margins, share_op, cash]


# ── section four: the long record ────────────────────────────────────────────
def long_section(s: dict, qv: dict) -> tuple[list[dict], list[dict]]:
    """The quarterly structure charts, and the disclosure-lag chart kept for the end of the part."""
    q = s["quarters"]
    e = s["quarterly_eur_m"]
    last = qv["last"]
    n = len(q)
    breaks = [q.index(YNAP_IN), q.index(YNAP_OUT)]
    first = next(i for i, v in enumerate(e["total"]) if v is not None)
    buyback = q.index("2018Q1")   # FY18 Q4, the quarter of the watch buy-backs

    js, ws = qv["jewellery_share"], qv["watch_share"]
    mix = {
        "ref": "EX_AREA_MIX",
        "kind": "lines",
        "title": (f"{n} 季里珠宝占销售从 {js[first]:.1f}%（{q[first]} D）到 {js[last]:.1f}%，"
                  f"腕表从 {ws[first]:.1f}% 到 {ws[last]:.1f}%"),
        "xlabels": list(q),
        "xrot": 90,
        "xstep": LONG_STEP,
        "series": [
            {"name": AREA_NAMES[k], "color": AREA_COLORS[k],
             "values": rounded([share(a, b) for a, b in zip(e[k], e["total"])], 2)} for k in AREAS
        ],
        "fmt": "pct1", "yfmt": "pct0", "label_fmt": "pct1",
        "end_label": True,
        "markers": True,
        "zero_base": True,
        "ylab": "占集团销售 %",
        "break_at": breaks,
        "break_label": ["YNAP 并表", "持续经营口径"],
        "note": (
            "<b>占比的分母是集团合计，它在两道断点处换过定义</b>：中间那一段含 YNAP，"
            "所以珠宝占比在 2018Q2 往下跳、在 2021Q2 往上跳，那两跳是口径，不是生意。"
            "「其他」从 2021Q2 起包含 Watchfinder（此前在线上分销里）。"
            "板块之间的抵销（最多几十个百万欧元）不单独画。"
            f"{q[buyback]} 腕表只有 {eur(e['specialist_watchmakers'][buyback])} D："
            "FY18 全年业绩公告说第四季度有集中的库存回购，腕表销售因回购减少 €203M。"),
        "src_extra": "各季度公告与业绩公告附录里的业务板块表；减出的季度标 D，见核对抽屉。",
    }

    rs = qv["region_share"]
    # YNAP's regional weight, read off the one full year printed on both bases
    fy22_cells = {(c["line"]): c for c in s["restatement_census"] if c["period"] == "FY22"}
    fy22 = {"orig": fy22_cells["asia_pacific"]["first"] / fy22_cells["total"]["first"] * 100,
            "rep": fy22_cells["asia_pacific"]["later"] / fy22_cells["total"]["later"] * 100}
    peak_ap = max((v, i) for i, v in enumerate(rs["asia_pacific"]) if v is not None)
    region = {
        "ref": "EX_REGION_MIX",
        "kind": "lines",
        "title": (f"{n} 季里亚太占销售从 {rs['asia_pacific'][first]:.1f}% 到 {rs['asia_pacific'][last]:.1f}%"
                  f"（峰值 {q[peak_ap[1]]} 的 {peak_ap[0]:.1f}%），美洲从 {rs['americas'][first]:.1f}% 到 "
                  f"{rs['americas'][last]:.1f}%"),
        "xlabels": list(q),
        "xrot": 90,
        "xstep": LONG_STEP,
        "series": [{"name": REGION_NAMES[k], "values": rounded(rs[k], 2), "color": REGION_COLORS[k]} for k in REGIONS],
        "fmt": "pct1", "yfmt": "pct0", "label_fmt": "pct1",
        "end_label": True,
        "zero_base": True,
        "ylab": "占集团销售 %",
        "break_at": breaks,
        "break_label": ["YNAP 并表", "持续经营口径"],
        "note": (
            (f"亚太的峰值 {q[peak_ap[1]]} 是疫情那一季：公告写欧洲 −59%、美洲 −61%，亚太 −29% 是最抗跌的，其中中国 +49%。"
             if q[peak_ap[1]] == "2020Q2" else "")
            + f"两道断点之间含 YNAP，它的销售偏欧美：FY22 全年按原口径亚太占 {fy22['orig']:.1f}%，"
            f"剔除 YNAP 重述后占 {fy22['rep']:.1f}%。"),
        "src_extra": "各季度公告与业绩公告附录里的地区表；占比为本页自算。",
    }

    dtc = {
        "ref": "EX_DTC",
        "kind": "lines",
        "title": (f"{n} 季里零售加线上零售占销售从 {qv['dtc'][first]:.1f}% 到 {qv['dtc'][last]:.1f}%"),
        "xlabels": list(q),
        "xrot": 90,
        "xstep": LONG_STEP,
        "series": [
            {"name": "零售 + 线上零售", "values": rounded(qv["dtc"], 2), "color": "NAVY"},
            {"name": "批发与特许权收入", "values": rounded([None if v is None else 100 - v for v in qv["dtc"]], 2),
             "color": "GOLD"},
        ],
        "fmt": "pct1", "yfmt": "pct0", "label_fmt": "pct1",
        "end_label": True,
        "zero_base": True,
        "ylab": "占集团销售 %",
        "break_at": breaks,
        "break_label": ["YNAP 并表", "持续经营口径"],
        "note": (
            "FY19 之前公司只分零售与批发两个渠道，线上门店算在零售里；"
            "FY19 起单列线上零售，而 FY19–FY21 的线上零售主要是 YNAP，所以中间那一段的直营占比偏高。"
            "持续经营口径下线上零售只剩各 Maison 自己的线上店与 Watchfinder。"),
        "src_extra": "渠道表；特许权收入单列的几期已并回批发。",
    }

    lags = qv["lags"]
    recent = qv["recent_on_time"]
    never = qv["derived"] + qv["missing"]
    first_2018q2 = s["first_printed"].get("2018Q2", {})
    lag = {
        "ref": "EX_LAG",
        "kind": "lines",
        "title": (f"{n} 季里 {len(qv['printed'])} 季被公司印成过单独的季度：最近 {len(recent)} 季都在 "
                  f"{max(lags[i] for i in recent)} 天内，最晚的一次等了 {max(qv['late_lags'])} 天，"
                  f"{len(never)} 季至今没有"),
        "xlabels": list(q),
        "xrot": 90,
        "xstep": LONG_STEP,
        "series": [{"name": "季末到该季度第一次被单独印出的天数", "values": lags, "color": "NAVY"}],
        "fmt": "f0", "yfmt": "f0", "label_fmt": "f0",
        "markers": True,
        "end_label": True,
        "zero_base": True,
        "ylab": "天",
        "note": (
            "<b>自 2021 年 11 月起，每份中期与全年业绩公告的附录都把当年每个季度重印一遍</b>，"
            "而且第一次这样做时回印了两年 —— 于是有几个季度是结束之后很久才第一次被印成单独的季度："
            f"{', '.join(f'{qq}（{lags[q.index(qq)]} 天）' for qq in qv['late_quarters'])}。"
            + ("其中 2018Q2 是 2019 年 7 月公司发出第一份第一季度公告时，作为上年比较列第一次出现的。"
               if "2018Q2" in qv["late_quarters"] and first_2018q2.get("column") == "comparative" else "")
            + f"线上的缺口是从来没被单独印过的 {len(never)} 个季度："
            f"其中 {len(qv['derived'])} 个本页减得出来，{len(qv['missing'])} 个谁也拆不出来。"),
        "src_extra": "每一格是季末日到最早印出该季度合计销售的那份公告发布日的日历天数；发布日取自各份公告首页。",
    }
    return [mix, region, dtc], [lag]


# ── section three: next quarter ──────────────────────────────────────────────
def next_kpi_block(s: dict) -> dict:
    """This quarter's note's section 8, for the quarter after the page's."""
    quarter = s["quarters"][-1]
    block = stamped_block(s, "next_kpi", display_period(quarter))
    if block is None:
        raise ValueError("series block `next_kpi` is missing: the tracking section has no thresholds")
    if display_period(block["for_period"]) != display_period(next_quarter(quarter)):
        raise ValueError(f"series block `next_kpi` is set for {block['for_period']!r}, but the quarter after "
                         f"{display_period(quarter)} is {display_period(next_quarter(quarter))}")
    return block


def how_read(measures: list[dict]) -> str:
    """How each current value was read, with the constant-rate lines said once."""
    lines = [m["line_name"] for m in measures if m.get("line_name")]
    parts = []
    if lines:
        parts.append(f"{'、'.join(lines)}的恒定汇率增速取本季")
    parts += [m["how"] for m in measures if not m.get("line_name")]
    return "；".join(parts)


def tracking_section(s: dict, qv: dict, hv: dict) -> tuple[list[dict], list[dict], dict]:
    """The note's thresholds for the next quarter: how far each current value sits from
    its line, then each measure over its own record against that line."""
    block = next_kpi_block(s)
    entries, measures = [], []
    for entry in block["quantified"]:
        if "current" in entry:
            raise ValueError(f"threshold `{entry['id']}` is computed from the series; remove its typed value")
        m = measure(s, qv, hv, entry["id"])
        entries.append({**entry, "current": m["now"]})
        measures.append(m)
    margins = [headroom(e["direction"], e["threshold"], e["current"]) for e in entries]
    breached = [e for e, margin in zip(entries, margins) if margin < 0]
    closest = min(range(len(entries)), key=lambda i: margins[i])
    nxt, kind = next_results(s)
    following = fiscal_parts(qv["fiscal"])[1] % 4 + 1
    if following in (2, 4):
        # The second and fourth fiscal quarters have no sales announcement of their
        # own: their sales are printed with the half's results.
        settles = (f"{cn_count(len(entries))}条都要等 {nxt['date']} 的{kind}结算：Richemont 第"
                   f"{cn_ordinal(following)}财季的销售不单独发公告，和{'上半年' if following == 2 else '全年'}"
                   f"利润一起印在{kind}里。")
    else:
        settles = f"销售类的阈值随下一份季度销售公告结算，利润与资产负债表类的要等 {nxt['date']} 的{kind}。"
    headroom_chart = headroom_exhibit(
        f"下季 {len(entries)} 条阈值："
        + (f"{len(breached)} 条已经越过" if breached else "都还在安全侧")
        + f"；离线最近的是{entries[closest]['metric']}，余量 {margins[closest]:.1f}%",
        entries, "current",
        note=("正值 = 仍在安全侧。各条的当前值：" + how_read(measures) + "。" + settles),
        src_extra=("阈值取自所有者的季报笔记第 8 节（本地研究），不是公司指引；每条取该条第一道警示或减仓线，"
                   "各档原话见核对抽屉。余量 = (当前值 − 阈值) / |阈值|。"),
    )
    headroom_chart["ref"] = "EX_HEADROOM"
    charts = [headroom_chart]
    for entry, m in zip(entries, measures):
        chart = threshold_chart(
            entry, m, "current",
            f"{entry['metric']}：下季阈值 {minus_sign(unit_text(entry['unit'], entry['threshold']))}，"
            f"当前 {minus_sign(unit_text(entry['unit'], entry['current']))}",
            "下季阈值",
            f"本季笔记第 8 节{entry['item']}的各档：{entry['levels']}。" + m.get("context", ""))
        chart["ref"] = f"EX_NEXT_{entry['id'].upper()}"
        charts.append(chart)
    return charts, entries, block


# ── audit drawer ─────────────────────────────────────────────────────────────
def audit_tables(s: dict, qv: dict, hv: dict, entries: list[dict], next_block: dict, settled: dict,
                 first: int) -> list[dict]:
    docs = {d["doc_id"]: d for d in s["documents"]}
    q = s["quarters"]
    e = s["quarterly_eur_m"]

    def ref(doc_id: str) -> str:
        d = docs[doc_id]
        return f"{d['release_date']} {d['kind'].replace('_', ' ')}"

    rows = []
    for i, quarter in enumerate(q):
        src = s["quarter_sources"][quarter]
        basis = s["quarter_basis"][i]
        if basis == "printed":
            how = "公司印出"
            where = ref(src["value_doc"])
            first_print = s["first_printed"][quarter]["published"]
        elif basis == "derived":
            how = f"本页减出 D（{src['method']}）"
            where = " − ".join(ref(d) for d in src["docs"])
            first_print = "从未单独印出"
        else:
            how = "拆不出来"
            where = "只有前五个月的增速与上半年合计"
            first_print = "—"
        cell = (lambda v: "—" if v is None else f"{v:,.0f}")
        rows.append([quarter, s["fiscal_quarters"][i], how, cell(e["total"][i]),
                     cell(e["jewellery_maisons"][i]), cell(e["specialist_watchmakers"][i]), first_print, where])
    ledger = {
        "n": first,
        "title": f"{len(q)} 个季度的销售与来历（€M）",
        "headers": ["季度", "公司财季", "来历", "集团", "珠宝", "腕表", "第一次单独印出", "取值文件"],
        "rows": rows,
    }

    by_quarter = {}
    for c in qv["checks"]:
        row = by_quarter.setdefault(c["quarter"], {"cells": 0, "differ": 0, "method": c["method"],
                                                  "derived": None, "printed": None,
                                                  "printed_doc": c["printed_doc"], "legs": c["derived_docs"]})
        row["cells"] += 1
        row["differ"] += c["derived"] != c["printed"]
        if c["line"] == "total":
            row["derived"], row["printed"] = c["derived"], c["printed"]
    check_rows = [[quarter, r["method"], f"{r['derived']:,.0f}", f"{r['printed']:,.0f}", str(r["cells"]), str(r["differ"]),
                   ref(r["printed_doc"]), "；".join(ref(d) for d in r["legs"])]
                  for quarter, r in sorted(by_quarter.items())]
    differ_quarters = sorted({c["quarter"] for c in qv["differ"]})
    checks = {
        "n": first + 1,
        "title": (f"公司后来印出的季度，与印出前一天就能做的减法逐格对照：{len(qv['checks'])} 格，"
                  f"{len(qv['differ'])} 格不同，"
                  + (f"全部在 {qv['trap']['quarter']}" if differ_quarters == [qv["trap"]["quarter"]]
                     else f"分布在 {'、'.join(differ_quarters)}")),
        "headers": ["季度", "减法", "减出的集团销售", "公司印出", "对照格数", "不同", "印出文件", "减法所用文件"],
        "rows": check_rows,
    }

    trap = qv["trap"]
    trap_rows = [[leg["period"], leg["column"], f"{leg['total']:,.0f}", leg["published"], leg["doc"]] for leg in trap["legs"]]
    trap_rows.append(["减出的合计", "", f"{trap['derived_total']:,.0f}", "", ""])
    trap_rows.append(["公司在同一份十一月公告里印出的", "", f"{trap['printed_total']:,.0f}", docs[trap["printed_doc"]]["release_date"], trap["printed_doc"]])
    trap_table = {
        "n": first + 2,
        "title": (f"{trap['quarter']} 用各自第一次印出的两个数相减会差 {eur(trap['printed_total'] - trap['derived_total'])}："
                  f"减数是 YNAP 改列之前的第一季"),
        "headers": ["期间", "列", "集团销售 €M", "发布日", "文件"],
        "rows": trap_rows,
    }

    census = {}
    for c in s["restatement_census"]:
        key = (c["period"], c["later_doc"])
        census.setdefault(key, []).append(c)
    census_rows = []
    for (period, later), cells in sorted(census.items(), key=lambda kv: (kv[0][0], docs[kv[0][1]]["release_date"])):
        total = next((c for c in cells if c["line"] == "total"), None)
        census_rows.append([period, docs[cells[0]["first_doc"]]["release_date"], docs[later]["release_date"],
                            str(len(cells)),
                            "—" if total is None else f"{total['first']:,.0f} → {total['later']:,.0f}"])
    scope = s["restatement_census_documents"]
    census_table = {
        "n": first + 3,
        "title": (f"销售表的重述普查：同一期间被不同公告印过 {s['restatement_paired_readings']:,} 对读数，"
                  + ("" if scope == len(s["documents"]) else f"（普查只读到第 {scope} 份公告）")
                  + f"{len(s['restatement_census'])} 对不同，来自两件事 —— FY19 起特许权收入并入销售并单列线上零售（重述 FY18），"
                  "与 YNAP 改列终止经营（重述 FY22）"),
        "headers": ["期间", "第一次印出", "后来印出", "不同的格数", "集团合计"],
        "rows": census_rows,
    }

    half_rows = [[fy, v["mode"].replace("next_year", "次年公告的比较列").replace("own_year", "当年公告"),
                  docs[v["year_doc"]]["release_date"] if v.get("year_doc") else "—（全年尚未公布）",
                  docs[v["h1_doc"]]["release_date"], v["why"]]
                 for fy, v in s["half_sources"].items()]
    half_table = {
        "n": first + 4,
        "title": f"{len(half_rows)} 个财年的半年数据各取自哪一对文件（H2 = 全年 − 上半年）",
        "headers": ["财年", "取法", "全年文件发布日", "上半年文件发布日", "原因"],
        "rows": half_rows,
    }

    warning = statement(s, "sep2016_profit_warning")
    h = s["half_eur_m"]
    i17, i16 = (s["halves"].index(x) for x in warning["settled_from"])
    warn_actual = pct(h["operating_profit"][i17], h["operating_profit"][i16])
    tariff = statement(s, "tariffs_fy26")
    said_rows = [
        [warning["said_on"], "FY17 上半年经营利润同比", f"约 {signed(warning['said_value'])}", f"{warn_actual:.1f}% D",
         f"业绩公告（{warning['settled_on']}）"],
        [tariff["said_on"], "FY26 新增美国关税", f"约 €{tariff['said_value']}M", f"约 €{tariff['settled_value']}M",
         "全年业绩电话会（公告本身不给金额）"],
    ]
    for y in statement(s, "tax_rate")["years"]:
        band = f"{y['low']:.1f}%" if y["low"] == y["high"] else f"{y['low']:.0f}–{y['high']:.0f}%"
        said_rows.append([y["said_on"], f"{y['fy']} 有效税率（持续经营）", band, f"{y['actual']:.1f}%", y["actual_on"]])
    jr, wr = statement(s, "jewellery_margin_range"), statement(s, "watchmakers_margin_midterm")
    d = " D" if hv["derived_last"] else ""
    said_rows.append([jr["said_on"], "珠宝经营利润率「舒适区间」", f"{jr['low']:.0f}–{jr['high']:.0f}%",
                      f"见第一节（最近 {hv['margin']['jewellery_maisons'][hv['last']]:.1f}%{d}）", "电话会"])
    said_rows.append([wr["said_on"], "腕表中期经营利润率潜力", f"{wr['low']:.0f}–{wr['high']:.0f}%",
                      f"见第一节（最近 {hv['margin']['specialist_watchmakers'][hv['last']]:.1f}%{d}）", "电话会"])
    said = {
        "n": first + 5,
        "title": "公司给过的关于自己未来结果的数字，与之后的结果",
        "headers": ["说的日期", "指标", "说的", "结果", "结果出处"],
        "rows": said_rows,
    }

    tables = [ledger, checks, trap_table, census_table, half_table]
    closure = settled["closure"]
    if closure is not None:
        tables.append({
            "n": first + len(tables),
            "title": (f"上季笔记留下的{cn_count(len(closure['items']))}条待验证问题，"
                      "与本季笔记第 0 节对每一条的判定"),
            "headers": ["#", "问题", "本季笔记的判定（原话）", "图上的归类"],
            "rows": [[str(i + 1), item["question"], item["note_verdict"], item["verdict"]]
                     for i, item in enumerate(closure["items"])],
        })
    prior = settled["prior"]
    if prior is not None:
        rows = [[e["metric"], e["rule"], s["latest"]["release_date"], reading_value(e["unit"], e["actual"]),
                 e["note_verdict"], e["disposal"]] for e in settled["prior_entries"]]
        rows += [[p["metric"], p["rule"], p["settles"], "—", p["note_verdict"], p["disposal"]]
                 for p in prior.get("pending", [])]
        tables.append({
            "n": first + len(tables),
            "title": (f"上季笔记（{prior['set_on']}）第 8 节的{cn_count(len(rows))}条量化阈值："
                      f"本季能结算 {len(settled['prior_entries'])} 条"),
            "headers": ["指标", "规则（上季笔记原话）", "结算", "本季值", "本季笔记的判定", "处置"],
            "rows": rows,
        })
    said["n"] = first + len(tables)
    tables.append(said)

    tables.append(threshold_table(first + len(tables),
                                  f"第三节{cn_count(len(entries))}条下季阈值的原始单位（本季笔记第 8 节）",
                                  entries, "current", "当前值"))
    level_rows = [[e["item"], e["metric"], e["levels"],
                   f"{'≥' if e['direction'] == 'up' else '≤'} {minus_sign(unit_text(e['unit'], e['threshold']))}"]
                  for e in entries]
    level_rows += [[u["item"], u["text"], "—", f"不画：{u['why']}"] for u in next_block.get("unquantified", [])]
    tables.append({
        "n": first + len(tables),
        "title": (f"本季笔记第 8 节的各档阈值与动作（原话）：本页画的是每条第一道警示或减仓线，"
                  f"另有{cn_count(len(next_block.get('unquantified', [])))}个半条没有数可画"),
        "headers": ["第 8 节", "指标", "各档阈值与动作", "本页画的线"],
        "rows": level_rows,
    })
    tables.append(ai_capex_cycle_table(first + len(tables)))
    return tables


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    sales = staging["half_segment_sales_eur_m"]["jewellery_maisons"][-1]
    result = staging["half_segment_result_eur_m"]["jewellery_maisons"][-1]
    return [f"Sales €{staging['quarterly_eur_m']['total'][-1]:,.0f}M",
            f"恒定汇率 {staging['quarterly_cer_pct']['total'][-1]:+.0f}%",
            f"珠宝 {staging['halves'][-1][-2:]} 利润率 {result / sales * 100:.1f}%"]


def build_payload(staging: dict) -> dict:
    s = staging
    qv = quarter_view(s)
    hv = half_view(s)
    q = s["quarters"]
    e = s["quarterly_eur_m"]
    cer = s["quarterly_cer_pct"]
    act = s["quarterly_actual_pct"]
    last = qv["last"]
    hl = hv["last"]
    halves = hv["halves"]
    period = display_period(q[-1])
    doc = latest_document(s)

    # The four parts, in the site's order: what last quarter left to settle, the
    # quarter, what to watch next, and the long record. Richemont's profit comes
    # only by the half, so the half-year charts are routine series here -- the
    # quarter itself carries sales and nothing else.
    closure_ex = closure_chart(s)
    prior_ex, prior_block, prior_entries = prior_settlement(s, qv, hv)
    settled = {"closure": settlement_block(s, "followup_closure"), "prior": prior_block,
               "prior_entries": prior_entries}
    settled_ex = ([closure_ex] if closure_ex else []) + prior_ex + said_section(s, hv)
    quarter_ex = quarter_section(s, qv)
    track_ex, entries, next_block = tracking_section(s, qv, hv)
    mix_ex, lag_ex = long_section(s, qv)
    routine_ex = mix_ex + half_section(s, hv) + [fx_chart(s, qv)] + lag_ex
    exhibits = number_exhibits(settled_ex + quarter_ex + track_ex + routine_ex, start=1)
    tables = audit_tables(s, qv, hv, entries, next_block, settled, len(exhibits) + 1)

    jm = hv["margin"]["jewellery_maisons"]
    wm = hv["margin"]["specialist_watchmakers"]
    latest = s["latest"]
    jewel_share = qv["jewellery_share"]
    first = next(i for i, v in enumerate(e["total"]) if v is not None)
    fy_now, number = fiscal_parts(qv["fiscal"])
    m1, m2 = quarter_months(q[-1])
    d = " D" if hv["derived_last"] else ""
    jr, wr = statement(s, "jewellery_margin_range"), statement(s, "watchmakers_margin_midterm")
    band = f"{jr['low']:.0f}–{jr['high']:.0f}%"
    state = band_state(jm[hl], jr["low"], jr["high"])
    claim = company_claim(s, "jewellery_streak")
    streak = qv["streak"]
    story = quarter_story(s)
    census = s["guidance_census"]
    transcription = s["transcription"]
    n_docs = len(s["documents"])

    # ── headline
    if streak and claim is not None and claim["count"] == streak:
        streak_text = f"公司说是连续第 {streak} 个两位数季度，本页逐季核过成立。"
    elif claim is not None:
        streak_text = f"公司说是连续第 {claim['count']} 个两位数季度，本页逐季数到 {streak} 个。"
    elif streak:
        streak_text = f"连续第 {streak} 个两位数季度（本页逐季数）。"
    else:
        streak_text = ""
    band_text = {
        "below": (f"CFO 口头给过的 {band} 舒适区间在这句话之后第一次被跌破；" if hv["jewel_first_break"]
                  else f"低于 CFO 口头给过的 {band} 舒适区间；"),
        "inside": f"落在 CFO 口头给过的 {band} 舒适区间里；",
        "above": f"高于 CFO 口头给过的 {band} 舒适区间；",
    }[state]
    be = base_effect(s, qv)
    ya = qv["year_ago"]
    inc_total = e["total"][last] - e["total"][ya]
    inc_jewel = e["jewellery_maisons"][last] - e["jewellery_maisons"][ya]
    gm_entry = next((x for x in entries if x["id"] == "half_gross_margin"), None)
    headline = (
        f"本季集团销售 {eur(e['total'][last])}，恒定汇率 {signed(cer['total'][last])}、实际汇率 "
        f"{signed(act['total'][last])}；上年同季恒定汇率{'只有' if be['ago'] < be['now'] else '是'} "
        f"{signed(be['ago'])}，两年叠加年化 {signed(be['two']['total'], 1)}。"
        f"珠宝 {eur(e['jewellery_maisons'][last])}、{signed(cer['jewellery_maisons'][last])}"
        + ("，" + streak_text if streak_text else "。")
        + (f"本季比上年同季多卖的 {eur(inc_total)} 里珠宝占 {inc_jewel / inc_total * 100:.0f}%。"
           if inc_total > 0 else "")
        + f"这一季没有利润数：刚结束的 {half_name(halves[hl])}珠宝经营利润率是 {jm[hl]:.1f}%"
        + ("（本页减出）" if hv["derived_last"] else "") + "，"
        + band_text
        + (f"同一个半年的集团毛利率 {gm_entry['current']:.1f}%，本季笔记给下一个半年设的阈值是 "
           f"{gm_entry['threshold']:g}%；" if gm_entry else "")
        + f"下一次利润数据在 {next_results(s)[0]['date']}。")

    # ── brief
    differ_quarters = sorted({c["quarter"] for c in qv["differ"]})
    structure = (
        '<article><span>结构</span>'
        f'<b>两个时钟，{cn_count(len(qv["missing"]))}个不存在的季度</b>'
        f'<p>销售按季、利润按半年，而半年是 4–9 月与 10–3 月。{len(q)} 个季度里公司印出 '
        f'{len(qv["printed"])} 个，本页减出 {len(qv["derived"])} 个，{len(qv["missing"])} 个谁也拆不出来'
        '（那几年 9 月只报前五个月）。公司后来印出的季度与本页的减法逐格对照 '
        f'{len(qv["checks"])} 格，{len(qv["differ"])} 格不同，'
        + (f'全部在 {qv["trap"]["quarter"]}：' if differ_quarters == [qv["trap"]["quarter"]]
           else f'分布在 {"、".join(differ_quarters)}；其中 {qv["trap"]["quarter"]}：')
        + f'减数用了 YNAP 改列之前的第一季，结果少 {eur(qv["trap"]["printed_total"] - qv["trap"]["derived_total"])}。</p></article>')
    cj = cer["jewellery_maisons"]
    accelerating = streak >= 2 and cj[last] > cj[last - 1]
    sales_word = ("销售在加速" if accelerating else "销售仍是两位数增长" if streak else "销售没有两位数增长")
    margin_word = {"below": "利润率没有跟上", "inside": "利润率在区间里", "above": "利润率在区间之上"}[state]
    margin_clause = {
        "below": f"但 {half_name(halves[hl])}利润率 {jm[hl]:.1f}%{d}，跌出 CFO 说的 {band}。",
        "inside": f"{half_name(halves[hl])}利润率 {jm[hl]:.1f}%{d}，在 CFO 说的 {band} 之内。",
        "above": f"{half_name(halves[hl])}利润率 {jm[hl]:.1f}%{d}，高于 CFO 说的 {band}。",
    }[state]
    trailing = hv["trailing_over"]
    growth_article = (
        f'<article><span>增长</span><b>{signed(be["now"])} 踩在 {signed(be["ago"])} 的基数上</b>'
        f'<p>本季集团恒定汇率 {signed(be["now"])}，上年同季 {signed(be["ago"])}：两年叠加年化 '
        f'{signed(be["two"]["total"], 1)}（D）。'
        + (f'接下来三个季度的上年同季是 {"、".join(signed(v) for v in be["bases"])}，下一季要约 '
           f'{signed(be["keep"], 1)} 才能让两年叠加不变。' if None not in be["bases"] else '')
        + '</p></article>')
    jewel_article = (
        f'<article><span>珠宝</span><b>{sales_word}，{margin_word}</b>'
        f'<p>珠宝本季 {signed(cer["jewellery_maisons"][last])}'
        + (f'，连续 {streak} 个季度两位数增长' if streak else '')
        + (f'，本季欧元增量的 {inc_jewel / inc_total * 100:.0f}% 来自珠宝' if inc_total > 0 else '')
        + f'；{len(q)} 季里占销售从 {jewel_share[first]:.1f}% 到 {jewel_share[last]:.1f}%。'
        + margin_clause
        + (f'<b>集团的利润越来越等于珠宝的利润</b>：最近 {trailing} 个半年珠宝分部利润都超过集团经营利润。'
           if trailing >= 2 else '')
        + '</p></article>')
    said_year, said_month = wr["said_on"][:4], int(wr["said_on"][5:7])
    watch_now, watch_ago = cer["specialist_watchmakers"][last], cer["specialist_watchmakers"][ya]
    watch_article = (
        f'<article><span>腕表</span><b>本季 {signed(watch_now)}，两年叠加年化 '
        f'{signed(be["two"]["specialist_watchmakers"], 1)}</b>'
        f'<p>本季腕表恒定汇率 {signed(watch_now)}，上年同季 {signed(watch_ago)}'
        + ("；" + story_text(s, story, "baume_mercier_brief") if story and story.get("baume_mercier_brief") else "。")
        + f'CFO {said_year} 年 {said_month} 月说腕表中期有潜力到 {wr["low"]:.0f}–{wr["high"]:.0f}%，'
        f'此后 {len(hv["watch_after"])} 个半年只有 '
        f'{sum(1 for i in hv["watch_after"] if wr["low"] <= wm[i] <= wr["high"])} 个落在区间里，'
        f'{half_name(halves[hl])} {wm[hl]:.1f}%{d}。'
        + '</p></article>')
    articles = [growth_article, jewel_article, watch_article, structure]
    brief = (f'<h4>本期{cn_count(len(articles))}条主线</h4><div class="takeaway-grid">'
             + "".join(articles) + '</div>')

    # ── notes
    if transcription["double_read_documents"] >= n_docs:
        read_twice = f"本页的季度销售逐格来自 {n_docs} 份公告，每份由两个互不通气的读者各转录一遍，"
    else:
        read_twice = (f"本页的季度销售逐格来自 {n_docs} 份公告，其中前 {transcription['double_read_documents']} 份"
                      "由两个互不通气的读者各转录一遍，")
    fallback = [fy for fy, v in s["half_sources"].items()
                if v["mode"] == "own_year" and fy != list(s["half_sources"])[-1]]
    notes = [
        "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，"
        "每张图下一到两句解释；支撑表格收在核对抽屉里。",
        "Richemont 的财年截至 3 月 31 日。本页按自然年季度标注：公司的第一财季（4–6 月）是本页的 Q2，"
        "第二财季（7–9 月）是 Q3，第三财季（10–12 月）是 Q4，第四财季（1–3 月）是下一年的 Q1。"
        f"所以本页的 {period} 是公司的 {fy_now} 第{cn_ordinal(number)}季。半年利润的横轴用半年的最后一个月标注。",
        "Richemont 不是美国证券交易委员会的报告发行人：EDGAR 上它名下只有 D 表格通知、REGDEX、"
        "一份 13D 与一份 4/A，没有任何财务报表。本页的数全部来自公司网站上的公告。",
        read_twice +
        "两份转录逐格比对后只在一条本页不用的现金行上有分歧。两份转录都漏掉了 FY22 的「前九个月」表，"
        "是用正则逐行扫描每份公告的合计行与板块行、对照转录结果时发现的，已补录并用三条加总恒等式核过。",
        f"{len(q)} 个季度里，{len(qv['printed'])} 个是公司印出的，{len(qv['derived'])} 个本页减出，"
        f"{len(qv['missing'])} 个拆不出来。每个季度的金额取自印出它的最后一份公告，"
        "也就是最新的口径；这让 FY22 的季度落在持续经营口径上、FY18 的季度落在特许权收入并入销售之后的口径上。"
        f"FY17 及更早的季度没有被重述过。",
        "恒定汇率增速是公司印出的整数百分比，本页从不相减或推算出某个季度的增速；"
        "两年叠加是把两个印出的增速连乘再开方，标 D。公司用上一个完整财年的平均汇率"
        "同时折算本期与比较期，基准汇率每年换一次，所以跨年比较增速时要知道分母换过汇率。",
        "半年利润数据逐年取自同一代口径的一对文件：优先用次年公告的比较列（最新口径），"
        "但如果次年只重述了全年、没有重述上半年，就退回当年自己的公告，避免 H2 = 全年 − 上半年跨口径。"
        f"{' 与 '.join(fallback)} 是这种情况。",
        "关税那一行的结果不在任何公告里：公告只说毛利率受到关税影响，金额是 CFO 在 2026 年 5 月电话会上说的。"
        "本页把它列出来，是因为公司在 2025 年 11 月的公告里给过一个估计值，这是少数能结算的数字之一。",
    ]
    if story and story.get("baume_mercier_note"):
        notes.append(story_text(s, story, "baume_mercier_note"))
    notes += [
        "本页不发布评级、目标价、估值与任何券商共识。第一、三节的阈值取自所有者的季报笔记（本地研究），不是公司指引。"
        f"在 {census['documents']} 份公告里，带数字的前瞻表述共 {census['forward_statements_with_a_number']} 处，"
        "没有一处是销售额或增速的数字。",
        "本页跨页对照表与其他公司页逐字相同，Richemont 本身不在那张表的任何一列里 —— "
        "带着这张表和成为表里的一列是两件事。",
    ]

    names = {x["id"]: x["metric"] for x in entries}
    revoked = [names[k] for k in next_block.get("revocation_ids", []) if k in names]
    unquantified = next_block.get("unquantified", [])
    track_description = (
        f"本季笔记第 8 节给下一季的{cn_count(len(entries))}条量化阈值：先看各条离线多远，再逐条画它自己的记录；"
        "每条画第一道警示或减仓线，当前值从序列现算，各档原话在核对抽屉。"
        + (f"第 8 节的{cn_count(len(revoked))}条立场撤销条件就画在其中" + "、".join(revoked)
           + f"这{cn_count(len(revoked))}条线上。" if revoked else "")
        + (f"没有数可画的{cn_count(len(unquantified))}个半条："
           + "；".join(f"{u['item']}——{u['text']}（{u['why']}）" for u in unquantified) + "。"
           if unquantified else ""))
    cash_now = quarter_net_cash(s)
    quarter_description = (
        f"{fy_now} 第{cn_ordinal(number)}季（{q[-1][:4]} 年 {m1}–{m2} 月）。{cn_count(len(quarter_ex))}张图："
        "集团销售与它的来历、上年同季的基数与两年叠加、三块业务的增速、增量按业务与按地区、"
        "各地区与各渠道和上年同季的对照。这一季只有销售，没有任何利润数。"
        + (story_text(s, story, "undrawn") if story else "")
        + (f"本季唯一的资产负债表数是季末净现金 €{cash_now['eur_bn']:.1f}B"
           + "".join(f"（含{x['what']} €{x['eur_bn']:.1f}B）" for x in cash_now.get("includes", []))
           + ("，画在第三节的净现金阈值图里。" if "net_cash" in names else "。")
           if cash_now else ""))
    closure, prior = settled["closure"], settled["prior"]
    settled_lead = []
    if closure is not None:
        settled_lead.append(f"上季笔记留下的{cn_count(len(closure['items']))}个问题闭环了几条")
    if prior is not None:
        settled_lead.append(f"它第 8 节的{cn_count(len(settled['prior_entries']) + len(prior.get('pending', [])))}条"
                            "量化阈值本季能结算几条")
    settled_description = (
        ("先看" + "、".join(settled_lead) + "，再结算公司自己说过的数。" if settled_lead else "")
        + f"Richemont 不给销售或增速指引：{census['documents']} 份公告里带数字的前瞻表述 "
        f"{census['forward_statements_with_a_number']} 处，没有一处是销售额或增速。"
        "CFO 在电话会上给过利润率区间，最后两张图各画其中一个能用半年数据结算的区间和它说出之后的每一个半年；"
        "税率、关税与 2016 年那次利润预警的结算放在核对抽屉。")
    return {
        "schema_version": "quarterly-dashboard/cfr-v1",
        "page": {"slug": "cfr", "language": "zh-CN"},
        "company": {
            "ticker": "CFR",
            "name": "Compagnie Financière Richemont SA",
            "group": "luxury_brands",
            "accounting_standard": "IFRS",
        },
        "latest": latest_block(
            s,
            period=period,
            full_label=f"H{halves[hl][-1]} FY{halves[hl][2:4]}"),
        "tracker": "Watchlist Quarterly Tracker · CFR",
        "title": (f"Richemont (CFR)：{period}（公司 {fy_now} 第{cn_ordinal(number)}季）销售与 "
                  f"{half_name(halves[hl])}利润仪表盘"),
        "subtitle": (
            f"销售截至 {latest['period_end']} · 发布 {latest['release_date']} · "
            f"利润截至 {half_end_date(halves[hl])} 半年 · "
            "IFRS · 欧元列示 · 3 月底制财年；本站按自然年季度标注"
            + (" · 季度公告未经审计" if latest["audit_status"] == "unaudited" else "")),
        "headline": headline,
        "brief": brief,
        "source": (
            'Source: <a href="' + doc["url"] + '" rel="noopener">'
            f'{doc["label"]}</a>与 2015 年 9 月以来的 {n_docs} 份销售与业绩公告；'
            "利润率区间与关税结果的原话取自公司业绩电话会记录。"),
        "source_url": "https://www.richemont.com/investors/results-reports-presentations/",
        "source_links": s["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {"id": "settled", "title": "一、上季跟踪指标兑现了吗",
             "description": settled_description,
             "exhibits": settled_ex},
            {"id": "quarter_highlights", "title": "二、本季重点",
             "description": quarter_description,
             "exhibits": quarter_ex},
            {"id": "next_quarter", "title": "三、下季要跟踪什么",
             "description": track_description,
             "exhibits": track_ex},
            {"id": "routine", "title": "四、长期常规跟踪",
             "description": (
                 f"{cn_count(len(routine_ex))}张图：业务、地区与渠道结构（{cn_count(len(q))}个季度），"
                 "半年利润率、珠宝对集团利润的占比、半年末净现金与库存，恒定汇率与实际汇率之差，"
                 "以及每个季度隔多久才第一次被印成单独的季度。季度图上的空格是公司从来没印过的季度，不是本页漏取；"
                 "半年图的横轴是半年的最后一个月，下半年由全年减上半年得到，全部标 D，"
                 "集团利润率跨过两道口径断点，珠宝与腕表的分部利润率不跨。"),
             "exhibits": routine_ex},
        ],
        "tables": tables,
        "notes": notes,
        "footer": "Richemont quarterly sales and half-year results · 数据来自公司公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "cfr.js"), payload, "cfr")
    shell_dir = ROOT / "cfr"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("CFR", "cfr"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"CFR page: {charts} charts in {len(payload['sections'])} sections "
          f"+ {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
