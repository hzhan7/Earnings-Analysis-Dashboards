#!/usr/bin/env python3
"""Build the META quarterly-results page.

Same four-part, chart-led shape as the other company pages (上季兑现 → 本季重点
→ 下季跟踪 → 长期常规).  The routine series are the ones that decide this
company right now: not "is the ad engine working" -- it is -- but whether the
incremental revenue the ad engine produces still turns into incremental
operating profit while the capital base doubles.

That is why the page leads on a series no filing publishes directly: the
year-over-year incremental operating margin, ΔOI / ΔRevenue.  A level margin
falling from 41% to 31% and a company whose extra dollar of revenue carries a
negative extra dollar of profit look identical on a margin chart and are two
completely different investment problems.

Published numbers are company-reported or transparent arithmetic.  Market
expectations are labelled as such, with no broker attribution.

Rolling the page to a new quarter edits `series/meta.json` and nothing else.
Every figure, period label, count and record claim is computed here from the
series; a sentence such as "the lower bound has never been tested", "the only
time" or "for the first time" is printed only while the series makes it true.
What belongs to one quarter -- the previous analysis's follow-up questions and
section-8 lines, this analysis's section-8 lines, the market's expectation, the
call's outlook wording, the 10-Q's off-balance-sheet facts and the rows of the
quality table the series does not carry -- lives in blocks stamped with that
quarter and is read through `board.stamped_block`: a block stamped with another
quarter stops the build. The three settlement blocks are required every quarter;
a missing optional one leaves its part of the page out. The one-off items the
analysis adds back are a record keyed by quarter, because a quarter-on-quarter
reading needs last quarter's too. Threshold lines never carry a typed reading:
each names a `measure` computed here from the series, so a roll moves `next_kpi`
into `prior_kpi_settlement` as it stands. The three guidance records (quarterly
revenue, annual expenses, annual capex) are read from `quarterly_guidance_history`
alone; the page no longer keeps its own copies.
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
    fill_story,
    headroom,
    headroom_exhibit,
    latest_block,
    number_exhibits,
    stamped_block,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "meta.json"
DATA_DIR = ROOT / "data"

AUDIT_WORDS = {"unaudited": "未审计", "audited": "已审计"}

# The source carries twelve quarters so every displayed quarter has a year-ago
# base; the page shows the last eight.
WINDOW = 8

# The year the capital build-out left its old range; the capital-intensity note
# measures "the previous high" on the record before it. A fact about the past.
BUILD_OUT_FROM = "2023Q1"


def compact_period(period: str) -> str:
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


def shown(values: list) -> list:
    return values[-WINDOW:]


def quarter_label(quarter: str) -> str:
    """``'2016Q1'`` → ``'Q1'16'``, matching the eight-quarter labels."""
    year, number = quarter.split("Q")
    return f"Q{number}'{year[-2:]}"


def quarter_key(period: str) -> str:
    """``'Q2 2026'`` → ``'2026Q2'``."""
    quarter, year = period.split()
    return f"{year}{quarter}"


def period_of(key: str) -> str:
    """``'2026Q2'`` → ``'Q2 2026'``."""
    return f"{key[4:]} {key[:4]}"


def next_key(key: str) -> str:
    year, quarter = int(key[:4]), int(key[-1])
    return f"{year + (quarter == 4)}Q{1 if quarter == 4 else quarter + 1}"


def call_of(filed: str) -> str:
    """The quarter whose results a release on ``filed`` reported: the last quarter
    that ended before it. Meta reports a month after each quarter closes."""
    day = datetime.date.fromisoformat(filed)
    quarter = (day.month - 1) // 3          # quarters fully ended this year
    year = day.year if quarter else day.year - 1
    return f"Q{quarter or 4} {year}"


def leading_gap(values: list[float | None]) -> int:
    """Index of the first reported value; ``len(values)`` when there is none."""
    return next((i for i, value in enumerate(values) if value is not None), len(values))


def runs(values: list, test) -> list[tuple[int, int]]:
    """Maximal stretches (first, last index) where ``test(value)`` holds; None breaks a run."""
    found, start = [], None
    for index, value in enumerate(values):
        hit = value is not None and test(value)
        if hit and start is None:
            start = index
        if not hit and start is not None:
            found.append((start, index - 1))
            start = None
    if start is not None:
        found.append((start, len(values) - 1))
    return found


def runs_over_holes(values: list, test) -> list[tuple[int, int]]:
    """Like `runs`, but a hole (None) neither breaks nor extends a run: a missing
    fourth-quarter reading between two price-led quarters is not a regime change."""
    known = [(index, value) for index, value in enumerate(values) if value is not None]
    found, start, last = [], None, None
    for index, value in known:
        if test(value):
            if start is None:
                start = index
            last = index
        elif start is not None:
            found.append((start, last))
            start = None
    if start is not None:
        found.append((start, last))
    return found


def spaced(word: str) -> str:
    """「隐含 H2 还要」 but 「隐含余下三季还要」: only Latin tokens get spaces around them."""
    return f" {word} " if word[:1].isascii() else word


def span_text(quarters: list[str], first: int, last: int) -> str:
    return quarters[first] if first == last else f"{quarters[first]}–{quarters[last]}"


# One x label per year: forty-two quarterly labels at 90 degrees turn the axis
# into a hairbrush, and this axis is only ever navigated by year.
LONG_STEP = 4


def guidance_band(quarters: list[str], low: list[float], high: list[float],
                  actual: list[float | None]) -> dict:
    """Meta's own revenue range against what it then reported, quarter by quarter.

    Deliberately local rather than shared with the TSMC page.  TSMC guides three
    numbers and needs a generalised helper; META guides exactly one, and the
    shared version is being rewritten in another session as this is written, so
    depending on its signature would make this page break on someone else's
    unrelated edit.
    """
    finished = [index for index, value in enumerate(actual) if value is not None]
    above = [i for i in finished if actual[i] > high[i]]
    below = [i for i in finished if actual[i] < low[i]]
    inside = len(finished) - len(above) - len(below)
    pending = [quarters[i] for i, value in enumerate(actual) if value is None]
    return {
        "ref": "meta_revenue_band",
        "kind": "range_band",
        "title": (
            f"收入指引兑现：{len(finished)} 个已完结季里 {len(above)} 季超出上限、"
            f"{inside} 季落在区间内，"
            + ("没有一季跌破下限" if not below else f"{len(below)} 季跌破下限")
        ),
        "xlabels": [quarter_label(quarter) for quarter in quarters],
        "xrot": 90,
        "lo": list(low),
        "hi": list(high),
        "actual": list(actual),
        "actual_color": "NAVY",
        "names": {
            "range": "公司收入指引区间",
            "actual": "实际收入",
            "lo": "指引下限（US$B）",
            "hi": "指引上限（US$B）",
        },
        "fmt": "f1",
        "label_fmt": "f1",
        "ylab": "US$B",
        "note": (
            "色块是该季<b>开始前</b>公司在上一季财报里给出的收入区间，菱形是随后报出来的实际值。"
            + (f"<b>下限从未被测试过</b>：{len(finished)} 季里一次都没有跌破，"
               "所以这条区间的下沿不是预测的一端，是公司愿意公开承诺的地板。"
               if not below else
               f"<b>下限被跌破过 {len(below)} 次</b>（"
               + "、".join(quarter_label(quarters[i]) for i in below) + "）。")
            + (f"最后一格 {quarter_label(pending[-1])} 只有指引色块，实际值待披露。"
               if pending else "")
            + "纵轴不自 0 起，但没有任何点被截掉。"
        ),
        "src_extra": (
            "指引区间逐季读自各季财报 8-K 的 EX-99.1 新闻稿「Outlook」段落；"
            "实际收入取同批申报的 XBRL 收入事实。"
        ),
    }


def guidance_deviation(quarters: list[str], low: list[float], high: list[float],
                       actual: list[float | None]) -> dict:
    """How far past the guided midpoint each quarter landed.

    The band chart saturates once a metric has cleared the same bound many times
    running -- it then says the same thing every quarter.  This asks the question
    that still has an answer: by how much, and is that widening or narrowing.
    """
    finished = [index for index, value in enumerate(actual) if value is not None]
    midpoints = [(low[i] + high[i]) / 2 for i in finished]
    deviation = [
        round((actual[i] / mid - 1) * 100, 6) for i, mid in zip(finished, midpoints)
    ]
    above = sum(1 for value in deviation if value > 0)
    biggest = max(deviation, key=abs)
    recent = deviation[-4:]
    recent_mean = sum(recent) / len(recent)
    # The comparison year is the last calendar year the record has in full.
    by_year: dict[str, list[float]] = {}
    for i, value in zip(finished, deviation):
        by_year.setdefault(quarters[i][:4], []).append(value)
    full_years = [year for year, values in by_year.items() if len(values) == 4]
    last_year = max(full_years) if full_years else None
    year_mean = (sum(by_year[last_year]) / 4) if last_year else None
    if year_mean is None:
        trend = ""
    elif recent_mean < year_mean:
        trend = (f"<b>这张图比上面那张多说的一句是「超额在收窄」</b>：最近四季平均 "
                 f"{recent_mean:+.1f}%，低于 {last_year} 全年的水平 —— "
                 "区间照样年年清得掉，但清出来的余量不如从前厚。")
    else:
        trend = (f"最近四季平均 {recent_mean:+.1f}%，不低于 {last_year} 全年的 {year_mean:+.1f}%。")
    return {
        "ref": "meta_revenue_midpoint",
        "kind": "grouped_bars",
        "title": (
            f"收入相对指引中值的偏离：{len(deviation)} 季里 {above} 季为正，"
            f"平均绝对偏离 {sum(abs(v) for v in deviation) / len(deviation):.1f}%"
        ),
        "xlabels": [quarter_label(quarters[i]) for i in finished],
        "xrot": 90,
        "groups": [{
            "name": "实际收入 vs 指引中值",
            "color": "BLUE",
            "values": deviation,
        }],
        "bar_labels": True,
        "fmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "% vs 指引中值",
        "note": (
            "正值 = 高于指引区间的中值；长期为正说明公司指引偏保守，不是一连串意外。"
            f"窗口内最大的一次是 {quarter_label(quarters[finished[deviation.index(biggest)]])} "
            f"的 {biggest:+.1f}%。"
            + trend
        ),
        "src_extra": "指引中值为区间上下限的算术平均（自算）；两条腿均为公司申报值。",
    }


def yoy(values: list[float]) -> list[float | None]:
    return [None] * 4 + [
        (values[index] / values[index - 4] - 1) * 100 for index in range(4, len(values))
    ]


def trailing(values: list[float]) -> list[float | None]:
    return [None] * 3 + [sum(values[index - 3:index + 1]) for index in range(3, len(values))]


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    q = staging["quarterly_usd_m"]
    ads = [total - reality - other for total, reality, other in
           zip(q["revenue_total"], q["reality_labs_revenue"], q["foa_other_revenue"])]
    fcf = (q["operating_cash_flow"][-1] - q["purchases_of_property_and_equipment"][-1]
           - q["finance_lease_principal"][-1])
    return [f"Revenue ${q['revenue_total'][-1] / 1000:.1f}B",
            f"Ads {(ads[-1] / ads[-5] - 1) * 100:+.1f}%",
            f"FCF {'-' if fcf < 0 else ''}${abs(fcf) / 1000:.1f}B"]


def guided_calls(records: list[dict], year: str) -> list[dict]:
    """Every call that guided ``year``, in filing order."""
    return sorted((call for call in records if call["year"] == year), key=lambda call: call["filed"])


def range_text(low: float, high: float) -> str:
    """``130.0, 145.0`` → ``'130–145'``; a fractional bound keeps its decimal."""
    def one(value):
        return f"{value:g}"
    return f"{one(low)}–{one(high)}"


def html_text(text: str) -> str:
    """Prose that goes into an exhibit note (rendered as HTML): escape what the
    report wrote literally -- its comparators -- so a `<` is never read as markup."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── thresholds: the two reports' section 8, line by line ─────────────────────
# A report writes each line as the condition that fires it -- 「≥ +8% = 加仓」,
# 「< 37% = 警示」 -- so an entry carries that comparator as written (`fires`) and
# whether firing is good news or a warning (`kind`: target / warn). Which side
# of the line is favourable follows from the two, and it is the comparator, not
# the sign of a headroom, that decides a reading landing exactly on an inclusive
# line. Readings are never typed into the series: an entry names a `measure`
# and the reading is computed here from the series, so next quarter's list can
# be moved into `prior_kpi_settlement` as it stands and settled with no code
# change.
OPERATORS = {"≥": lambda value, line: value >= line, ">": lambda value, line: value > line,
             "≤": lambda value, line: value <= line, "<": lambda value, line: value < line}

# page name, short name for a bar label, unit, how a reading prints, and the
# chart spec when the measure is a quarterly series (`point` ones are not).
MEASURES = {
    "price_per_ad_yoy": {"name": "平均每条广告价格同比", "short": "单价同比", "unit": "pct",
                         "reading": "{:+.0f}%", "fmt": "pct0", "ylab": "同比增速"},
    "ad_impressions_yoy": {"name": "广告曝光同比", "short": "曝光同比", "unit": "pct",
                           "reading": "{:+.0f}%", "fmt": "pct0", "ylab": "同比增速"},
    "reality_labs_revenue": {"name": "Reality Labs 单季收入", "short": "RL 收入", "unit": "usd_m",
                             "reading": "${:,.0f}M", "fmt": "f0c", "ylab": "$M"},
    "reality_labs_revenue_yoy": {"name": "Reality Labs 收入同比", "short": "RL 收入同比", "unit": "pct",
                                 "reading": "{:+.1f}%", "chart": False},
    "foa_other_revenue": {"name": "FoA Other 单季收入", "short": "FoA Other 收入", "unit": "usd_m",
                          "reading": "${:,.0f}M", "fmt": "f0c", "ylab": "$M"},
    "foa_other_revenue_yoy": {"name": "FoA Other 收入同比", "short": "FoA Other 同比", "unit": "pct",
                              "reading": "{:+.1f}%", "fmt": "pct1", "ylab": "同比增速"},
    "operating_margin_adjusted": {"name": "经营利润率（调整后）", "short": "经营利润率",
                                  "unit": "pct", "reading": "{:.2f}%", "fmt": "pct1", "ylab": "经营利润率"},
    "operating_margin_adjusted_qoq_pp": {"name": "经营利润率环比变动（调整后）", "short": "利润率环比",
                                         "unit": "pp", "reading": "{:+.2f}pp", "chart": False},
    "incremental_margin_qoq_adjusted": {"name": "调整后环比增量经营利润率", "short": "环比增量利润率",
                                        "unit": "pct", "reading": "{:+.1f}%", "fmt": "pct1",
                                        "ylab": "ΔOI / ΔRevenue"},
    "operating_income": {"name": "单季经营利润（GAAP）", "short": "单季经营利润", "unit": "usd_m",
                         "reading": "${:,.0f}M", "fmt": "f0c", "ylab": "$M"},
    "capex_guide_mid": {"name": "CapEx 指引中点", "short": "CapEx 指引中点", "unit": "usd_bn",
                        "reading": "US${:g}B", "point": True},
    "capex_guide_first_mid": {"name": "首次 CapEx 指引中点", "short": "首次 CapEx 指引", "unit": "usd_bn",
                              "reading": "US${:g}B", "point": True},
    "fy_capex": {"name": "CapEx（全年；年内取最新指引中点）", "short": "CapEx", "unit": "usd_bn",
                 "reading": "US${:g}B", "point": True},
    "fy_operating_income": {"name": "经营利润（全年）", "short": "经营利润", "unit": "usd_m",
                            "reading": "${:,.0f}M", "point": True},
    "cumulative_rvg": {"name": "累计残值担保敞口", "short": "累计残值担保", "unit": "usd_bn",
                       "reading": "约 US${:g}B", "point": True},
}

LINE_WORDS = {"加仓线": "加仓", "减仓线": "减仓", "警示线": "警示", "跟踪线": "跟踪"}


def quarter_order(label: str) -> tuple[int, int]:
    """``'Q3 2026'`` → ``(2026, 3)``, so two quarter labels can be compared."""
    quarter, year = label.split()
    return int(year), int(quarter[1])


def threshold_direction(entry: dict) -> str:
    rising = entry["fires"] in ("≥", ">")
    return "up" if rising == (entry["kind"] == "target") else "down"


def measure_name(entry: dict, short: bool = False) -> str:
    spec = MEASURES[entry["measure"]]
    name = spec["short" if short else "name"]
    return f"FY{entry['year']} {name}" if entry.get("year") else name


def reading_words(entry: dict, value: float) -> str:
    """A reading the way the page prints it; money keeps its sign outside the symbol."""
    fmt = MEASURES[entry["measure"]]["reading"]
    if "$" in fmt:
        text = fmt.format(abs(value))
        return "−" + text if value < 0 else text
    return fmt.format(value).replace("-", "−")


def threshold_words(entry: dict) -> str:
    value, unit = entry["threshold"], entry["unit"]
    text = {"pct": f"{value:g}%", "pp": f"{value:g}pp", "usd_m": f"${value:,.0f}M",
            "usd_bn": f"${value:g}B"}[unit]
    return text.replace("-", "−")


def line_label(entry: dict) -> str:
    """The bar label: which reading, the report's comparator and line, and what firing means."""
    return f"{measure_name(entry, short=True)} {entry['fires']}{threshold_words(entry)} {LINE_WORDS.get(entry['line'], entry['line'])}"


def one_off_record(staging: dict) -> dict[str, list[dict]]:
    """Per quarter, the charges the report adds back to operating income."""
    return (staging.get("operating_income_one_offs") or {}).get("by_period", {})


def measure_series(staging: dict) -> dict[str, list[float | None]]:
    """Every quarterly reading a threshold can be settled on, aligned with `long_history.quarters`."""
    long = staging["long_history"]
    quarters = long["quarters"]
    revenue, operating = long["revenue_usd_m"], long["operating_income_usd_m"]
    record = one_off_record(staging)
    adjusted = [income + sum(item["usd_m"] for item in record.get(period_of(quarter), []))
                for quarter, income in zip(quarters, operating)]

    def year_on_year(values: list) -> list[float | None]:
        return [None] * 4 + [None if now is None or not before else (now / before - 1) * 100
                             for before, now in zip(values, values[4:])]

    margin = [income / sales * 100 for income, sales in zip(adjusted, revenue)]
    return {
        "price_per_ad_yoy": [None if v is None else float(v) for v in long["price_per_ad_yoy_pct"]],
        "ad_impressions_yoy": [None if v is None else float(v) for v in long["ad_impressions_yoy_pct"]],
        "reality_labs_revenue": list(long["reality_labs_revenue_usd_m"]),
        "reality_labs_revenue_yoy": year_on_year(long["reality_labs_revenue_usd_m"]),
        "foa_other_revenue": list(long["foa_other_revenue_usd_m"]),
        "foa_other_revenue_yoy": year_on_year(long["foa_other_revenue_usd_m"]),
        "operating_margin_adjusted": margin,
        "operating_margin_adjusted_qoq_pp": [None] + [now - before for before, now in zip(margin, margin[1:])],
        # A quarter whose revenue fell has no incremental margin: ΔOI / ΔRevenue
        # with a negative denominator reads as a margin and is not one.
        "incremental_margin_qoq_adjusted": [None] + [
            None if sales_now - sales_before <= 0 else (now - before) / (sales_now - sales_before) * 100
            for before, now, sales_before, sales_now in zip(adjusted, adjusted[1:], revenue, revenue[1:])],
        "operating_income": [float(v) for v in operating],
    }


def point_reading(staging: dict, entry: dict, period: str) -> float | None:
    """A reading that is not a quarterly series, as of the page's quarter."""
    name, year = entry["measure"], entry.get("year")
    released = staging["latest"]["release_date"]
    calls = [call for call in guided_calls(staging["quarterly_guidance_history"]["capex_guidance_calls"], year or "")
             if call["filed"] <= released]
    if name == "capex_guide_mid":
        return (calls[-1]["low"] + calls[-1]["high"]) / 2 if calls else None
    if name == "capex_guide_first_mid":
        return (calls[0]["low"] + calls[0]["high"]) / 2 if calls else None
    annual = staging["annual_actuals_usd_m"].get(year) if year else None
    if name == "fy_capex":
        # The year's filed total once the 10-K is in; until then the latest guided midpoint.
        if annual:
            return (annual["purchases_of_property_and_equipment"] + annual["finance_lease_principal"]) / 1000
        return (calls[-1]["low"] + calls[-1]["high"]) / 2 if calls else None
    if name == "fy_operating_income":
        return float(annual["operating_income"]) if annual else None
    if name == "cumulative_rvg":
        block = stamped_block(staging, "off_balance_sheet", period)
        if block is None:
            raise ValueError("a threshold measures `cumulative_rvg`: stamp the quarter's `off_balance_sheet` "
                             "block with the residual value guarantees its 10-Q discloses")
        return float(sum(item["usd_bn"] for item in block["residual_value_guarantees"]))
    raise ValueError(f"this page does not know how to measure {name!r}")


def evaluate(staging: dict, block: dict, value_key: str, period: str) -> list[dict]:
    """A threshold block's lines, each read now and settled by its own comparator.

    `consecutive: n` fires only if the last n readings all fire. A line with no
    reading has to say why (`unread`) or when it settles (`settles`) -- a line
    that silently drops out is the failure this section exists to prevent.
    """
    series = measure_series(staging)
    entries = []
    for entry in block["quantified"]:
        name = entry["measure"]
        if name not in MEASURES:
            raise ValueError(f"threshold {entry['id']!r} measures {name!r}, which build/meta.py does not know")
        if entry["fires"] not in OPERATORS or entry["kind"] not in ("warn", "target"):
            raise ValueError(f"threshold {entry['id']!r}: fires must be one of {''.join(OPERATORS)} "
                             "and kind warn or target")
        need = entry.get("consecutive", 1)
        values = series.get(name)
        if values is None:
            if need > 1:
                raise ValueError(f"threshold {entry['id']!r}: a point reading cannot be consecutive")
            value, run = point_reading(staging, entry, period), None
        else:
            value, run = values[-1], values[-need:]
        item = {**entry, "direction": threshold_direction(entry), value_key: value}
        if value is None:
            if not (entry.get("unread") or entry.get("settles")):
                raise ValueError(f"threshold {entry['id']!r} has no reading for {period}: say why in "
                                 "`unread`, or when it settles in `settles`")
            if entry.get("settles") and quarter_order(entry["settles"]) <= quarter_order(period):
                raise ValueError(f"threshold {entry['id']!r} settles in {entry['settles']}, and {period} has no "
                                 f"reading for it: add the figure it settles on (for a full year, the year's "
                                 f"10-K line in `annual_actuals_usd_m`)")
            entries.append({**item, "fired": None, "favourable": None, "run": []})
            continue
        run = run if run is not None else [value]
        fire = OPERATORS[entry["fires"]]
        fired = all(v is not None and fire(round(v, 6), entry["threshold"]) for v in run)
        streak = 0
        for v in reversed(values if values is not None else [value]):
            if v is None or not fire(round(v, 6), entry["threshold"]):
                break
            streak += 1
        entries.append({**item, "fired": fired, "run": run, "streak": streak,
                        "favourable": fired if entry["kind"] == "target" else not fired})
    return entries


def on_bars(entry: dict, value_key: str) -> bool:
    """A line whose bar means its verdict: read now, a single reading, a line away from zero
    (a percentage distance from zero does not exist)."""
    return entry[value_key] is not None and entry["threshold"] != 0 and entry.get("consecutive", 1) == 1


def settle_words(entry: dict, lead: str = "上季") -> str:
    """How one line settled: 「守住上季警示线 3%」「未达到上季加仓线 39%」."""
    line = f"{lead}{entry['line']} {entry['fires']}{threshold_words(entry)}"
    on_line = round(entry["actual"], 6) == entry["threshold"]
    if entry["kind"] == "warn":
        return ("压线触发" if on_line and entry["fired"] else "击穿" if entry["fired"] else "守住") + line
    return ("压线达到" if on_line and entry["fired"] else "达到" if entry["fired"] else "未达到") + line


def run_words(entry: dict, value_key: str) -> str:
    """A consecutive line in words: the readings it needs and where the run stands."""
    need = entry["consecutive"]
    readings = " 与 ".join("—" if v is None else reading_words(entry, v) for v in entry["run"])
    verdict = ("触发" if entry["fired"] else "未触发") if value_key == "actual" else (
        "已满足" if entry["fired"] else f"本季是连续第{cn_ordinal(entry['streak'])}季" if entry["streak"] else "本季不在线上")
    return (f"「{measure_name(entry)} {entry['fires']}{threshold_words(entry)}」要连续{cn_count(need)}季才算"
            f"（{LINE_WORDS.get(entry['line'], entry['line'])}）：最近{cn_count(need)}季 {readings}，{verdict}")


def plot_spec(staging: dict, measure: str) -> tuple[list[dict], str]:
    """What a threshold chart draws under its lines, on the full record, and where it comes from.

    Every threshold chart runs the whole record from the first quarter of
    `long_history`, holes where the measure did not exist yet: which charts a
    quarter's thresholds call for changes with each roll, and a fixed axis keeps
    that from changing what the rest of the site's census counts.
    """
    long = staging["long_history"]
    quarters = long["quarters"]
    record = one_off_record(staging)
    series = measure_series(staging)
    revenue, operating = long["revenue_usd_m"], long["operating_income_usd_m"]
    adjusted_at = [bool(record.get(period_of(quarter))) for quarter in quarters]

    def rounded(values: list) -> list:
        return [None if v is None else round(v, 2) for v in values]

    def tail(values: list, marks: list[bool]) -> list:
        """The adjusted line only where it differs, plus the point before it so it joins."""
        keep = [marks[i] or (i + 1 < len(marks) and marks[i + 1]) for i in range(len(marks))]
        return rounded([v if k else None for v, k in zip(values, keep)])

    if measure == "operating_margin_adjusted":
        gaap = [income / sales * 100 for income, sales in zip(operating, revenue)]
        lines = [{"name": "经营利润率（GAAP）", "values": rounded(gaap), "color": "NAVY"}]
        if any(adjusted_at):
            lines.append({"name": "调整后（加回一次性项）D", "values": tail(series[measure], adjusted_at),
                          "color": "GOLD"})
        return lines, "经营利润与收入逐季来自各期 10-Q / 10-K 与当季新闻稿；利润率为自算，调整后加回项见核对表。"
    if measure == "incremental_margin_qoq_adjusted":
        gaap = [None] + [None if s1 - s0 <= 0 else (o1 - o0) / (s1 - s0) * 100
                         for o0, o1, s0, s1 in zip(operating, operating[1:], revenue, revenue[1:])]
        marks = [adjusted_at[i] or (i > 0 and adjusted_at[i - 1]) for i in range(len(quarters))]
        lines = [{"name": "环比增量经营利润率（GAAP）D", "values": rounded(gaap), "color": "NAVY"}]
        if any(marks):
            lines.append({"name": "调整后 D", "values": tail(series[measure], marks), "color": "GOLD"})
        return lines, ("环比增量经营利润率 = 经营利润环比变动 ÷ 收入环比变动（自算）；收入环比下降的季度"
                       "（多数第一季）没有增量利润率可言，图上留空。")
    names = {
        "price_per_ad_yoy": ("平均每条广告价格同比", "公司披露的同比百分比，逐季读自 10-Q MD&A 与业绩新闻稿；"
                             "2016–2020 年的第四季公司只给全年变动，留空。"),
        "ad_impressions_yoy": ("广告曝光同比", "公司披露的同比百分比，逐季读自 10-Q MD&A 与业绩新闻稿；"
                               "2016–2020 年的第四季公司只给全年变动，留空。"),
        "reality_labs_revenue": ("Reality Labs 收入", "分部收入逐季来自 10-Q / 10-K 与 Q4 新闻稿；"
                                 f"{long['segment_first_reported']} 起才按分部披露，之前留空。"),
        "foa_other_revenue": ("FoA Other 收入", "分部收入逐季来自 10-Q / 10-K 与 Q4 新闻稿；"
                              f"{long['segment_first_reported']} 起才按分部披露，之前留空。"),
        "foa_other_revenue_yoy": ("FoA Other 收入同比 D", "分部收入逐季来自 10-Q / 10-K 与 Q4 新闻稿，同比为自算；"
                                  f"分部自 {long['segment_first_reported']} 起披露，同比要再晚四季。"),
        "operating_income": ("单季经营利润（GAAP）", "经营利润逐季来自各期 10-Q / 10-K 与当季新闻稿。"),
    }
    name, source = names[measure]
    return [{"name": name, "values": rounded(series[measure]), "color": "NAVY"}], source


def threshold_line_charts(staging: dict, block: dict, entries: list[dict], value_key: str) -> list[dict]:
    """One chart per measure that has a record: the reading's whole history under every line
    the report drew on it."""
    lead = "上季" if value_key == "actual" else "下季"
    rows = {row["row"]: row for row in block.get("rows", [])}
    long_labels = [quarter_label(quarter) for quarter in staging["long_history"]["quarters"]]
    charts = []
    order: list[str] = []
    for entry in entries:
        if entry[value_key] is not None and MEASURES[entry["measure"]].get("chart", True) \
                and not MEASURES[entry["measure"]].get("point") and entry["measure"] not in order:
            order.append(entry["measure"])
    for measure in order:
        group = [entry for entry in entries if entry["measure"] == measure and entry[value_key] is not None]
        spec = MEASURES[measure]
        now = reading_words(group[0], group[0][value_key])
        lines, source = plot_spec(staging, measure)
        thresholds = [{"name": f"{lead}{entry['line']} {entry['fires']}{threshold_words(entry)}",
                       "values": [entry["threshold"]] * len(long_labels),
                       "color": "RED" if entry["kind"] == "warn" else "GREEN"} for entry in group]
        if value_key == "actual":
            title = f"{measure_name(group[0])} {now}：" + "，".join(settle_words(entry) for entry in group)
        else:
            title = (f"{measure_name(group[0])}：下季阈值 "
                     + " / ".join(f"{entry['fires']}{threshold_words(entry)}（{entry['line']}）" for entry in group)
                     + f"，当前 {now}")
        seen_rows = sorted({entry["row"] for entry in group}, key=str)
        note = "".join(f"{'上季' if value_key == 'actual' else '本季'}分析第 8 节第 {row} 行原文：{html_text(rows[row]['text'])}。"
                       for row in seen_rows if row in rows)
        for entry in group:
            room = ("" if entry["threshold"] == 0 else
                    f"（余量 {headroom(entry['direction'], entry['threshold'], entry[value_key]) + 0.0:+.1f}%）")
            if entry.get("consecutive", 1) > 1:
                note += html_text(run_words(entry, value_key)) + "。"
            elif value_key == "actual":
                note += f"{html_text(settle_words(entry))}{room}。"
            else:
                note += (f"{entry['line']} {html_text(entry['fires'] + threshold_words(entry))}：当前"
                         f"{'在有利一侧' if entry['favourable'] else '在不利一侧'}{room}。")
            if entry.get("reads_as"):
                note += html_text(entry["reads_as"]) + "。"
            if entry.get("also"):
                note += (f"这一档还要「{html_text(entry['also']['text'])}」"
                         + (f"：{html_text(entry['also']['reading'])}" if entry["also"].get("reading") else "")
                         + "。")
        if value_key == "actual":
            note += "".join(f"本季分析对这一行的读法：{html_text(rows[row]['report_reading'])}；处理：{html_text(rows[row]['handling'])}。"
                            for row in seen_rows if rows.get(row, {}).get("report_reading"))
        chart = {
            "kind": "lines",
            "title": title,
            "xlabels": long_labels,
            "xstep": LONG_STEP,
            "series": lines + thresholds,
            "fmt": spec["fmt"],
            "yfmt": spec["fmt"],
            "label_fmt": spec["fmt"],
            "end_label": True,
            "ylab": spec["ylab"],
            "note": note,
            "src_extra": source + ("阈值为上季本地研究设定，不是公司指引。" if value_key == "actual"
                                   else "阈值为本季本地研究设定，不是公司指引。"),
        }
        charts.append(chart)
    return charts


def rule_sentences(block: dict, entries: list[dict], value_key: str, values: dict,
                   progress: dict | None = None) -> str:
    """What the bars cannot show: joint halves, runs, zero lines, lines with no reading,
    word-only legs and conditions with no series at all."""
    words = []
    by_id = {entry["id"]: entry for entry in entries}
    seen: set[str] = set()
    for entry in entries:
        partner = by_id.get(entry.get("joint", ""))
        if partner is None or entry["id"] in seen or entry[value_key] is None or partner[value_key] is None:
            continue
        seen |= {entry["id"], partner["id"]}
        legs = [entry, partner]
        reached = [leg for leg in legs if leg["fired"]]
        state = ("两腿都已到" if len(reached) == 2 else "两腿都没到" if not reached
                 else f"只有「{measure_name(reached[0], short=True)}」一腿到了")
        words.append(f"「{line_label(entry)}」与「{line_label(partner)}」要同时成立才算"
                     f"{LINE_WORDS.get(entry['line'], entry['line'])}：{'本季' if value_key == 'actual' else '当前'} "
                     f"{reading_words(entry, entry[value_key])} / {reading_words(partner, partner[value_key])}，{state}。")
    for entry in entries:
        if entry.get("also"):
            words.append(f"{line_label(entry)}这一档还要「{entry['also']['text']}」"
                         + (f"：{fill_story(entry['also']['reading'], values)}" if entry["also"].get("reading")
                            else "，要等披露")
                         + "。")
    for entry in entries:
        if entry[value_key] is not None and entry.get("consecutive", 1) > 1:
            words.append(run_words(entry, value_key) + "。")
        elif entry[value_key] is not None and entry["threshold"] == 0:
            verdict = ("触发" if entry["fired"] else "未触发") if value_key == "actual" else (
                "当前在有利一侧" if entry["favourable"] else "当前在不利一侧")
            words.append(f"{line_label(entry)}的阈值是 0，没有百分比余量、不进柱图：本季 "
                         f"{reading_words(entry, entry[value_key])}，{verdict}。")
    for entry in entries:
        if entry[value_key] is not None:
            continue
        pending = f"它结算的是 {entry.get('settles')} 才有的数"
        done = (progress or {}).get(f"{entry['measure']}:{entry.get('year')}")
        if done and entry.get("settles"):
            so_far, value = done
            need = entry["threshold"] - value
            pending += (f"；{so_far}已实现 {reading_words(entry, value)}，剩下的季度至少要 "
                        f"{reading_words(entry, need)} 才{'不低于' if entry['kind'] == 'warn' else '达到'}"
                        f" {threshold_words(entry)}")
        words.append(f"「{measure_name(entry)} {entry['fires']}{threshold_words(entry)}」"
                     f"（{LINE_WORDS.get(entry['line'], entry['line'])}）本季没有读数："
                     + (fill_story(entry["unread"], values) if entry.get("unread") else pending)
                     + "。")
    for leg in block.get("text_legs", []):
        words.append(f"第 {leg['row']} 行还有一条只能按文字结算的条件「{leg['text']}」"
                     + (f"：{fill_story(leg['reading'], values)}" if leg.get("reading") else "")
                     + "。")
    for item in block.get("gated", []):
        words.append(f"{item['row']}的「{item['text']}」没有序列、不进柱图：{fill_story(item['why'], values)}。")
    return html_text("".join(words))


def next_overview(block: dict, entries: list[dict], values: dict, progress: dict, period: str) -> dict:
    """Section three: this report's section-8 lines, measured from where the quarter left off."""
    bars = [entry for entry in entries if on_bars(entry, "current")]
    good = [entry for entry in bars if entry["favourable"]]
    bad = [entry for entry in bars if not entry["favourable"]]
    title = f"下季 {len(bars)} 条阈值：当前 {len(good)} 条在有利一侧、{len(bad)} 条在不利一侧"
    if bad and len(bad) <= 3:
        title += "（" + "、".join(f"{measure_name(entry, short=True)} {entry['fires']}{threshold_words(entry)}"
                                  for entry in bad) + "）"
    on_line = [entry for entry in bars if round(entry["current"], 6) == entry["threshold"]]
    yearly = [entry for entry in entries if entry.get("year") and entry["measure"] != "capex_guide_first_mid"]
    exhibit = headroom_exhibit(
        title,
        [{**entry, "metric": line_label(entry)} for entry in bars],
        "current",
        html_text(
            "正值 = 当前读数落在这条线的有利一侧（警示线未触发、目标线已到），负值 = 不利一侧；当前值是本季的读数，"
            f"这些线结算的是 {block['for_period']} 的读数"
            + (f"（带年份的{cn_count(len(yearly))}条结算的是全年数）" if yearly else "") + "。"
            + (f"{cn_count(len(on_line))}条正好压在线上（余量 0）："
               + "、".join(line_label(entry) for entry in on_line)
               + " —— 这几条线就是报告按本季读数设的。" if on_line else ""))
        + rule_sentences(block, entries, "current", values, progress),
        src_extra=(f"阈值与比较符逐字取自本季（{period}）本地分析第 8 节「本季 5 条指标」与立场撤销条件，是研究设定，"
                   "不是公司指引；当前值由本页从序列现算（新闻稿、10-Q、10-K）。逐行原文、触发动作与撤销条件见核对抽屉。"),
    )
    # a line the reading sits exactly on prints 0.0, not -0.0
    exhibit["values"] = [value + 0.0 for value in exhibit["values"]]
    exhibit["positive_label"] = "落在有利一侧"
    exhibit["negative_label"] = "落在不利一侧"
    return exhibit


def next_row_table(block: dict) -> dict:
    """This report's section-8 rows as written, their actions, and the revocation conditions."""
    rows = [[f"第 {row['row']} 行", row["metric"], row["text"], row["action"]] for row in block["rows"]]
    rows += [[f"撤销条件{item['n']}", item["text"], "—", "撤回「经营无恙、资本待验证」的中性判断并转为负面重估"]
             for item in block.get("revocation", [])]
    return {"n": 0, "title": f"本季（{block['period']}）第 8 节原文、触发动作与立场撤销条件",
            "headers": ["行", "指标", "原文", "触发动作"], "rows": rows}


def prior_overview(block: dict, entries: list[dict], values: dict, basis_words: str) -> dict:
    """(b) Last quarter's section 8, every line with a single reading on one headroom axis."""
    bars = [entry for entry in entries if on_bars(entry, "actual")]
    warn = [entry for entry in bars if entry["kind"] == "warn"]
    target = [entry for entry in bars if entry["kind"] == "target"]
    broken = [entry for entry in warn if entry["fired"]]
    reached = [entry for entry in target if entry["fired"]]
    parts = []
    if warn:
        parts.append(f"{len(warn)} 条警示线"
                     + (f"击穿 {len(broken)} 条（" + "、".join(f"{measure_name(entry, short=True)} "
                                                              f"{entry['fires']}{threshold_words(entry)}"
                                                              for entry in broken) + "）"
                        if broken else "全部守住"))
    if target:
        parts.append(f"{len(target)} 条目标线" + (f"达到 {len(reached)} 条" if reached else "一条都未达到"))
    exhibit = headroom_exhibit(
        f"上季 {len(bars)} 条量化阈值：" + "，".join(parts),
        [{**entry, "metric": line_label(entry)} for entry in bars],
        "actual",
        ("正值 = 落在这条线的有利一侧（警示线守住、目标线达到），负值 = 不利一侧（警示线击穿、目标线未达到）；"
         "恰好压在线上的一格余量为 0，算不算触发由原文的比较符决定。"
         + rule_sentences(block, entries, "actual", values) + html_text(basis_words)),
        src_extra=(f"阈值与比较符逐字取自上季（{block['set_in']}）本地分析第 8 节「关键观察指标」，是研究设定，"
                   "不是公司指引；实际值由本页从序列现算（新闻稿、10-Q、10-K）。每行原文与本季分析的读法、处理见核对抽屉。"),
    )
    # a line the reading sits exactly on prints 0.0, not -0.0
    exhibit["values"] = [value + 0.0 for value in exhibit["values"]]
    exhibit["positive_label"] = "落在有利一侧"
    exhibit["negative_label"] = "落在不利一侧"
    return exhibit


def settlement_table(title: str, entries: list[dict], value_key: str, value_head: str, values: dict) -> dict:
    """Every line of a section-8 block in its own units, with the comparator the report wrote."""
    rows = []
    for entry in entries:
        value = entry[value_key]
        if value is None:
            verdict = ("读不到：" + fill_story(entry["unread"], values) if entry.get("unread")
                       else f"待 {entry['settles']} 结算")
        elif entry.get("consecutive", 1) > 1:
            verdict = run_words(entry, value_key)
        elif value_key == "actual":
            verdict = settle_words(entry)
        else:
            verdict = "当前在有利一侧" if entry["favourable"] else "当前在不利一侧"
        rows.append([
            f"第 {entry['row']} 行",
            f"{measure_name(entry)}（{entry['line']}）",
            f"{entry['fires']}{threshold_words(entry)}",
            "—" if value is None else reading_words(entry, value),
            "—" if value is None or entry["threshold"] == 0
            else f"{headroom(entry['direction'], entry['threshold'], value) + 0.0:+.1f}%",
            verdict,
        ])
    return {"n": 0, "title": title,
            "headers": ["行", "这条线", "比较符与阈值", value_head, "余量 D", "判定"], "rows": rows}


def prior_row_table(block: dict) -> dict:
    """The previous report's rows as written, and how this quarter's report read and handled them."""
    return {
        "n": 0,
        "title": f"上季（{block['set_in']}）第 8 节原文，与本季分析「先校准上季指标」的读法和处理",
        "headers": ["行", "指标", "原文", "触发动作", "本季分析的读法", "处理"],
        "rows": [[f"第 {row['row']} 行", row["metric"], row["text"], row["action"],
                  row.get("report_reading", "—"), row.get("handling", "—")] for row in block["rows"]],
    }


def closure_exhibit(closure: dict, values: dict) -> tuple[dict, dict]:
    """(a) Last quarter's follow-up questions as this quarter's section 0 judged them,
    and the table that lists them one by one."""
    labels, items = closure["labels"], closure["items"]
    unknown = sorted({item["verdict"] for item in items} - set(labels))
    if unknown:
        raise ValueError(f"`followup_closure` items carry verdicts that are not labels: {unknown}")
    for item in items:
        if not item["wording"].startswith(item["verdict"]):
            raise ValueError(f"`followup_closure` item {item['n']}: verdict {item['verdict']!r} is not how "
                             f"the report's wording {item['wording']!r} begins")
    counts = [sum(1 for item in items if item["verdict"] == label) for label in labels]
    groups = [(label, [item for item in items if item["verdict"] == label]) for label in labels]
    detail = "；".join(f"{label}的{cn_count(len(group))}条是" + "、".join(f"「{item['short']}」" for item in group)
                      for label, group in groups if group)
    chart = {
        "kind": "bars_labeled",
        "title": (f"上季 {len(items)} 条待验证问题："
                  + "、".join(f"{count} 条{label}" for label, count in zip(labels, counts))),
        "xlabels": list(labels),
        "values": counts,
        "legend": "问题条数",
        "fmt": "f0",
        "yfmt": "f0",
        "label_fmt": "f0",
        "ylab": "条",
        "note": (f"上季（{closure['set_in']}）的本地分析在文末留下 {len(items)} 条待验证问题，本季那一份在第 0 节"
                 f"逐条判定。{html_text(closure['rule'])}{detail}。"
                 + "".join(f"被证伪的「{item['short']}」：{html_text(fill_story(item['evidence'], values))}。"
                           for item in items if item["verdict"] == "被证伪")),
        "src_extra": (f"问题清单来自上季（{closure['set_in']}）本地分析稿的 Follow-up Questions；判定照录本季本地分析稿"
                      "第 0 节。证据里的数由本页从本季新闻稿与 10-Q 现算，电话会的说法注明为电话会。逐条见核对抽屉。"),
    }
    table = {
        "n": 0,
        "title": f"上季（{closure['set_in']}）留下的 {len(items)} 条待验证问题：本季第 0 节逐条判定",
        "headers": ["#", "问题（上季原文）", "判定（本季第 0 节原文）", "归类", "本季证据"],
        "rows": [[str(item["n"]), item["question"], item["wording"], item["verdict"],
                  fill_story(item["evidence"], values)] for item in items],
    }
    return chart, table


def regional_chart(geography: dict, quarter_revenue: float, period: str) -> dict:
    """The quarter's revenue growth by region, as the 10-Q prints it, read against where the
    10-Q says the impressions grew.

    A one-quarter reading, so it sits with the quarter's other findings rather
    than among the long series.
    """
    growth = geography["user_geography_yoy_pct"]
    order = sorted(range(len(growth)), key=lambda i: -growth[i])
    regions = geography["regions"]
    share = geography["customer_address_current"][0] / quarter_revenue * 100
    address_growth = pct_change(geography["customer_address_current"][0],
                                geography["customer_address_prior_year"][0])
    led = geography.get("impressions_led_by")
    if led in regions:
        rank = order.index(regions.index(led)) + 1
        at = growth[regions.index(led)]
        title = (f"10-Q：曝光增长尤其在{led}，而{led}收入同比只有 {at:g}%，四个区域里最低"
                 if rank == len(regions) else
                 f"10-Q：曝光增长尤其在{led}，{led}收入同比 {at:g}%，四个区域里排第{cn_ordinal(rank)}")
        filing = (f"10-Q 写明本季曝光在所有地区都增长、尤其在{led}，而平均单价的涨幅被「在变现率较低的地区与产品"
                  "（如 Reels）投放的更多曝光」部分抵消 —— 与本季分析洞察 2 说的量价两难是同一个机制：量靠低变现的"
                  "地区与版面撑，价就被稀释。")
    else:
        title = (f"本季四大区域收入同比：{regions[order[0]]}最快，"
                 f"{regions[order[-2]]}与{regions[order[-1]]}落在后两位")
        filing = ""
    return {
        "kind": "bars_labeled",
        "title": title,
        "xlabels": regions,
        "values": growth,
        "legend": "收入同比",
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "同比增速",
        "note": (
            filing
            + f"{regions[0]}同比 {growth[0]:g}%（公司按用户所在地印的口径）；按收入分解附注的客户所在地口径，"
            f"它占本季收入 {share:.1f}%、同比 {address_growth:.1f}% —— 两个口径不同，本图画前者。"
        ),
        "src_extra": (
            f"区域同比取 {period} 10-Q MD&A「revenue by user geography」一段公司印出的整数百分比；"
            "收入分解附注按客户所在地分区，那张表算出的同比是 "
            + "、".join(f"{pct_change(c, p):.1f}%" for c, p in
                       zip(geography["customer_address_current"], geography["customer_address_prior_year"]))
            + "，口径不同、不混用。公司未按区域披露利润，本页不做区域盈利推断。"
            + (f"曝光与单价一句出自 {geography['filing_words_source']}：{html_text(geography['filing_words'])}。"
               if geography.get("filing_words") else "")
        ),
    }


def expectation_chart(consensus: dict, actual: dict, one_offs: list[dict], period: str) -> dict:
    """The quarter against the market's expectation going in: where it beat and where it missed.

    `actual` carries this quarter's revenue, diluted EPS and DAP and the midpoint of
    the next quarter's revenue guide, all from the release.
    """
    rows = [("收入", pct_change(actual["revenue_usd_m"], consensus["revenue_usd_m"])),
            ("摊薄 EPS", pct_change(actual["diluted_eps_usd"], consensus["diluted_eps_usd"])),
            ("Family DAP", pct_change(actual["dap_bn"], consensus["family_daily_active_people_bn"]))]
    if actual.get("next_guide_mid_usd_m") and consensus.get("q3_revenue_usd_m"):
        rows.append(("下季收入指引中点", pct_change(actual["next_guide_mid_usd_m"], consensus["q3_revenue_usd_m"])))
    revenue_gap, eps_gap = rows[0][1], rows[1][1]
    low, high = consensus.get("diluted_eps_usd_range", (None, None))
    note = (f"市场预期是财报前的一致预期（{consensus['as_of']}），不具名。"
            f"收入 ${actual['revenue_usd_m']:,}M 对预期 ${consensus['revenue_usd_m']:,.0f}M；"
            f"摊薄 EPS ${actual['diluted_eps_usd']:.2f} 对预期 ${consensus['diluted_eps_usd']:.2f}"
            + (f"（各来源的 EPS 预期在 ${low:.2f}–${high:.2f} 之间，按两端算是 "
               f"{pct_change(actual['diluted_eps_usd'], low):+.1f}% 到 {pct_change(actual['diluted_eps_usd'], high):+.1f}%）"
               if low and high else "")
            + "。"
            + (f"本季经营利润里有{cn_count(len(one_offs))}笔一次性项（"
               + "、".join(f"{item['name']} ${item['usd_m']:,}M" for item in one_offs)
               + "，税前），公司没有给剔除后的每股收益。" if one_offs else "")
            + (f"下季收入指引中点 ${actual['next_guide_mid_usd_m']:,.0f}M 对财报前的下季预期 "
               f"${consensus['q3_revenue_usd_m']:,.0f}M。" if len(rows) > 3 else ""))
    return {
        "kind": "diverging_bars",
        "title": (f"对市场预期：收入{'高' if revenue_gap >= 0 else '低'} {abs(revenue_gap):.1f}%，"
                  f"摊薄 EPS {'高' if eps_gap >= 0 else '低'} {abs(eps_gap):.1f}%"),
        "xlabels": [label for label, _ in rows],
        "values": [round(value, 2) for _, value in rows],
        "legend": "较市场预期",
        "positive_label": "高于市场预期",
        "negative_label": "低于市场预期",
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "% 较市场预期",
        "zero_line": True,
        "note": note,
        "src_extra": f"实际值来自 {period} 业绩新闻稿（EX-99.1）；{consensus['label']}。",
    }


def off_balance_chart(leases: dict, off_balance: dict | None, period: str) -> dict:
    """What does not go through the capex line: lease obligations signed but not yet commenced,
    quarter by quarter since the disclosure began, with the ventures' guarantees in the note."""
    quarters, total = leases["quarters"], leases["total_usd_bn"]
    if quarter_key(period) != quarters[-1]:
        raise ValueError(f"`leases_not_yet_commenced` ends at {quarters[-1]} but the page is {period}: "
                         "append the quarter's 10-Q figure with the roll")
    year_end_at = max(i for i, quarter in enumerate(quarters[:-1]) if quarter.endswith("Q4"))
    year_end = total[year_end_at]
    ratio = total[-1] / year_end
    first_at = {basis: leases["basis"].index(basis) for basis in dict.fromkeys(leases["basis"])}
    ventures = ""
    if off_balance is not None:
        guarantees = off_balance["residual_value_guarantees"]
        ventures = (
            f"不进资本开支线的还有不并表合资的残值担保（RVG）："
            + "；".join(f"{item['name']}（{item['basis']}；{item['measure_words']}约 US${item['usd_bn']:g}B）"
                       for item in guarantees)
            + f"。路易斯安那合资的最大损失敞口 {quarter_label(quarters[-1])} 为 US${off_balance['louisiana_max_exposure_usd_bn']:.2f}B"
            f"（上年末 US${off_balance['louisiana_max_exposure_year_end_usd_bn']:.2f}B），含股权账面值、租约承诺、后续出资与 RVG 门槛。"
            f"季末之后又签了约 US${off_balance['leases_signed_after_quarter_usd_bn']:g}B"
            f"（{off_balance['leases_signed_after_quarter_words']}），不在这条线里。")
    return {
        "kind": "lines",
        "title": (f"已签约未起租的租赁义务 US${total[-1]:.2f}B：比上年末多 US${total[-1] - year_end:.2f}B，"
                  f"是上年末的 {ratio:.1f} 倍"),
        "xlabels": [quarter_label(quarter) for quarter in quarters],
        "xstep": LONG_STEP,
        "series": [{"name": "未起租的租赁义务（季末）", "values": total, "color": "NAVY"}],
        "fmt": "f1",
        "yfmt": "f1",
        "label_fmt": "f1",
        "end_label": True,
        "ylab": "US$B",
        "note": (
            "季末已经签约、还没起租的经营与融资租赁义务。起租后才进资产负债表：融资租赁的本金偿付从那时起计入"
            "公司口径的资本开支，经营租赁的租金不计入。本季分析洞察 3 以 El Paso 合资说明「资本开支指引已不是资本强度的"
            "完整度量」；申报里同类义务在它之前就有，而且在上升 —— "
            f"这条线 {quarter_label(quarters[year_end_at])} 是 US${year_end:.2f}B，{quarter_label(quarters[-1])} 是 "
            f"US${total[-1]:.2f}B。{ventures}"
            f"<b>这张图只能回到 {quarter_label(quarters[0])}</b>：新租赁准则 2019 年起才要求披露这个数，此前的年报没有。"
        ),
        "src_extra": (
            "逐季取自 10-Q / 10-K 租赁附注（2025 年起在 Commitments and Contingencies）那一句；"
            f"{quarter_label(quarters[first_at['分列相加']])} 起公司分列经营与融资两个数（本页相加），"
            + (f"{quarter_label(quarters[first_at['只写经营租赁']])}–{quarter_label(quarters[first_at['合计'] - 1])} "
               "只写了经营租赁，" if "只写经营租赁" in first_at else "")
            + (f"{quarter_label(quarters[first_at['合计']])} 起写合计。" if "合计" in first_at else "")
            + "逐季的申报编号见 series 的 leases_not_yet_commenced.sources。"
        ),
    }


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    period = periods[-1]
    prev_period, year_ago = periods[-2], periods[-5]
    key = quarter_key(period)
    latest = latest_block(staging, period=period)
    if not any(item["label"] == f"{period} 业绩发布 8-K" for item in staging["sources"]):
        raise ValueError(f"series `sources` has no {period} 业绩发布 8-K: add the quarter's "
                         "release with the roll")

    labels = [compact_period(p) for p in shown(periods)]
    q = staging["quarterly_usd_m"]
    ads = staging["advertising_metrics"]
    closure = stamped_block(staging, "followup_closure", period)
    prior_kpi = stamped_block(staging, "prior_kpi_settlement", period)
    next_kpi = stamped_block(staging, "next_kpi", period)
    # Every quarter now has a local analysis before it and one of its own, so
    # section one always settles the previous one and section three always
    # places this one: a roll that leaves a block out stops here rather than
    # publishing a page that silently skipped a section.
    missing = [name for name, block in (("followup_closure", closure), ("prior_kpi_settlement", prior_kpi),
                                        ("next_kpi", next_kpi)) if block is None]
    if missing:
        raise ValueError(f"series blocks {missing} are required every quarter: section one settles the "
                         "previous analysis (its section 0 and section 8), section three places this one's section 8")
    for name, block in (("followup_closure", closure), ("prior_kpi_settlement", prior_kpi)):
        if block["set_in"] != prev_period:
            raise ValueError(f"series block `{name}` settles what {block['set_in']!r} left, but the quarter "
                             f"before {period} is {prev_period!r}")
    if next_kpi["for_period"] != period_of(next_key(key)):
        raise ValueError(f"series block `next_kpi` is set for {next_kpi['for_period']!r}, but the quarter "
                         f"after {period} is {period_of(next_key(key))!r}")
    consensus = stamped_block(staging, "market_expectation", period)
    off_balance = stamped_block(staging, "off_balance_sheet", period)
    outlook = stamped_block(staging, "outlook", period)
    snapshot = stamped_block(staging, "quarter_snapshot", period)
    geography = stamped_block(staging, "quarter_geography", period)
    expense = stamped_block(staging, "quarter_expense_lines_usd_m", period)
    if snapshot is not None and snapshot["columns"] != [period, prev_period, year_ago]:
        raise ValueError(f"series block `quarter_snapshot` columns {snapshot['columns']} are not "
                         f"{[period, prev_period, year_ago]}: re-key them with the roll")
    history = staging["quarterly_guidance_history"]

    revenue = q["revenue_total"]
    operating_income = q["operating_income"]

    # Advertising is not tagged separately in the cash-flow-level series; it is
    # the reported total less the two disclosed non-advertising lines, so the
    # three revenue lines always add back to the reported total exactly.
    advertising = [
        total - reality - other
        for total, reality, other in zip(
            revenue, q["reality_labs_revenue"], q["foa_other_revenue"]
        )
    ]

    # META's own free-cash-flow definition nets finance-lease principal, and the
    # headline capex number adds it too, so both derived lines use the same base.
    capex_total = [
        purchases + lease
        for purchases, lease in zip(
            q["purchases_of_property_and_equipment"], q["finance_lease_principal"]
        )
    ]
    free_cash_flow = [
        operating - capex
        for operating, capex in zip(q["operating_cash_flow"], capex_total)
    ]

    one_offs = one_off_record(staging).get(period, [])
    one_off_total = sum(item["usd_m"] for item in one_offs)
    one_off_words = "与 ".join(f"${item['usd_m']:,}M {item['name']}" for item in one_offs)
    one_off_words_named_first = " 与".join(f"{item['name']} ${item['usd_m']:,}M" for item in one_offs)
    adjusted_operating_income = operating_income[-1] + one_off_total

    # ΔOI / ΔRevenue on a year-over-year base. Quarter-over-quarter would be
    # cleaner arithmetic but META's Q4 is seasonally large enough to flip the
    # sign twice a year, which would make the series unreadable.
    adjusted_incremental_margin = (
        (adjusted_operating_income - operating_income[-5])
        / (revenue[-1] - revenue[-5]) * 100
    )

    volume_price_product = [
        ((1 + impressions / 100) * (1 + price / 100) - 1) * 100
        for impressions, price in zip(
            ads["ad_impressions_yoy_pct"], ads["price_per_ad_yoy_pct"]
        )
    ]

    # ── The routine charts run on the ten-year record, not the eight ─────────
    # Everything below is a filed number or the difference of two filed numbers.
    # The cash-flow lines exist only year-to-date in a 10-Q, so each quarter
    # after the first is one year-to-date figure minus the previous one; see
    # long_history.provenance.
    long = staging["long_history"]
    quarters = long["quarters"]
    if quarters[-1] != key:
        raise ValueError(f"long_history ends at {quarters[-1]} but the page is {period}")
    long_labels = [quarter_label(quarter) for quarter in quarters]
    years = len(quarters) // 4
    long_revenue = long["revenue_usd_m"]
    long_depreciation = long["depreciation_and_amortization_usd_m"]
    long_revenue_yoy = yoy(long_revenue)
    long_depreciation_yoy = yoy(long_depreciation)
    yoy_from = leading_gap(long_revenue_yoy)

    # META's own free-cash-flow definition nets finance-lease principal, which
    # is on every cash-flow statement in the record (under its pre-ASC 842 name
    # before 2019) -- see long_history.finance_lease_note.
    long_lease = long["finance_lease_principal_usd_m"]
    long_fcf = [
        None if lease is None else operating - purchases - lease
        for operating, purchases, lease in zip(
            long["operating_cash_flow_usd_m"],
            long["capital_expenditures_usd_m"],
            long_lease,
        )
    ]
    long_ttm_fcf = [
        None if any(value is None for value in long_fcf[index - 3:index + 1])
        else sum(long_fcf[index - 3:index + 1])
        for index in range(len(long_fcf))
    ]
    long_ttm_fcf[:3] = [None] * 3
    ttm_from = leading_gap(long_ttm_fcf)

    # The two segment lines only exist from the quarter META first reported
    # segments; before that the categories did not exist, so the chart carries
    # its own shorter axis rather than twenty blank quarters on the left.
    long_reality = long["reality_labs_revenue_usd_m"]
    long_foa_other = long["foa_other_revenue_usd_m"]
    segment_from = leading_gap(long_reality)

    # The advertising engine, on the ten-year window. The two rate lines have
    # holes -- one per fourth quarter from 2016 through 2020 -- because the 10-K
    # states only the full-year change and the 8-K did not carry the quarterly
    # bullet until 2021Q4. Holes, not interpolation: a line drawn through them
    # would invent readings the company never gave.
    long_advertising = long["advertising_revenue_usd_m"]
    long_advertising_yoy = yoy(long_advertising)
    long_impressions = long["ad_impressions_yoy_pct"]
    long_price = long["price_per_ad_yoy_pct"]
    ad_rate_holes = [
        long_labels[index] for index, value in enumerate(long_impressions) if value is None
    ]

    # Capex on the company's own definition -- purchases of property and
    # equipment plus finance-lease principal -- which is why it needed the lease
    # line backfilled before this chart could run the whole record.
    long_capex = [
        purchases + lease
        for purchases, lease in zip(long["capital_expenditures_usd_m"], long_lease)
    ]
    long_capex_intensity = [
        capex / revenue * 100 for capex, revenue in zip(long_capex, long_revenue)
    ]

    revenue_shown = shown(revenue)
    revenue_yoy = shown(yoy(revenue))
    advertising_yoy = shown(yoy(advertising))
    foa_other_shown = shown(q["foa_other_revenue"])
    foa_other_yoy = shown(yoy(q["foa_other_revenue"]))
    reality_labs_shown = shown(q["reality_labs_revenue"])
    capex_shown = shown(capex_total)
    capex_intensity = [
        capex / total * 100 for capex, total in zip(capex_shown, revenue_shown)
    ]
    fcf_shown = shown(free_cash_flow)
    ttm_fcf = shown(trailing(free_cash_flow))
    depreciation_shown = shown(q["depreciation_and_amortization"])
    depreciation_yoy = shown(yoy(q["depreciation_and_amortization"]))

    # The three guidance records, read from the filed history alone.
    guided_year = key[:4]
    capex_calls = guided_calls(history["capex_guidance_calls"], guided_year)
    expense_calls = guided_calls(history["expense_guidance_calls"], guided_year)
    capex_guide_mid = [(call["low"] + call["high"]) / 2 for call in capex_calls]
    coming = next_key(key)
    q3_low = history["guide_low_usd_bn"][history["quarters"].index(coming)] \
        if coming in history["quarters"] else None
    q3_high = history["guide_high_usd_bn"][history["quarters"].index(coming)] \
        if coming in history["quarters"] else None
    q3_midpoint = (q3_low + q3_high) / 2 * 1000 if q3_low is not None else None
    q3_yoy = pct_change(q3_midpoint, revenue[-4]) if q3_midpoint else None
    annual = staging["annual_actuals_usd_m"]
    base_year = str(int(guided_year) - 1)
    base = annual.get(base_year)
    in_year = [i for i, p in enumerate(periods) if p.endswith(guided_year)]
    year_to_date_capex = sum(capex_total[i] for i in in_year)
    year_to_date_oi = sum(operating_income[i] for i in in_year)
    elapsed = len(in_year)
    so_far = {1: "Q1", 2: "H1", 3: "前三季"}.get(elapsed, f"前{elapsed}季")
    so_far_words = {1: "一季度", 2: "上半年", 3: "前三季"}.get(elapsed, f"前{elapsed}季")
    rest = {1: "余下三季", 2: "H2", 3: "Q4"}.get(elapsed, "")
    line_words = {1: "四分之一线", 2: "半程线", 3: "四分之三线"}.get(elapsed, "全年线")
    pace_line = base["operating_income"] * elapsed / 4 if base else None
    price_low, price_high = (consensus or {}).get("post_earnings_price_change_range_pct", (None, None))

    source = (
        'Source: <a href="https://investor.atmeta.com/" rel="noopener">Meta Investor Relations</a>'
        f'（{period} earnings release 与电话会；历史季度经 SEC EDGAR 的 10-Q / 10-K 回源）。'
    )

    def source_note(detail: str) -> str:
        return f"{detail}；历史期同口径。自算项目均可在核对表中复核。"

    # Numbers the quarter's story blocks name ({capex_now}, {positions} ...):
    # computed here from the arrays, never typed into the series beside them.
    advertising_yoy_all = yoy(advertising)
    story = {
        "price_now": f"{long_price[-1]:+.0f}%", "price_before": f"{long_price[-2]:+.0f}%",
        "impressions_now": f"{long_impressions[-1]:+.0f}%",
        "impressions_before": f"{long_impressions[-2]:+.0f}%",
        "ads_now": f"{advertising_yoy_all[-1]:+.1f}%", "ads_before": f"{advertising_yoy_all[-2]:+.1f}%",
    }
    def bounds_move(before_call: dict, now_call: dict) -> str:
        words = []
        for bound, name in (("low", "下限"), ("high", "上限")):
            change = now_call[bound] - before_call[bound]
            words.append(f"{name}不变" if change == 0 else
                         f"{name}{'抬高' if change > 0 else '下调'} US${abs(change):g}B")
        return "、".join(words)

    if len(capex_calls) >= 2:
        before_call, now_call = capex_calls[-2], capex_calls[-1]
        story.update({
            "capex_before": f"US${range_text(before_call['low'], before_call['high'])}B",
            "capex_now": f"US${range_text(now_call['low'], now_call['high'])}B",
            "capex_bounds_move": bounds_move(before_call, now_call),
            "capex_mid_before": f"US${(before_call['low'] + before_call['high']) / 2:g}B",
            "capex_mid_now": f"US${(now_call['low'] + now_call['high']) / 2:g}B",
            "capex_range_held": ("维持" if (now_call["low"], now_call["high"])
                                 == (before_call["low"], before_call["high"]) else "没有维持"),
        })
    if len(expense_calls) >= 2:
        before_call, now_call = expense_calls[-2], expense_calls[-1]
        story.update({
            "expense_before": f"US${range_text(before_call['low'], before_call['high'])}B",
            "expense_now": f"US${range_text(now_call['low'], now_call['high'])}B",
            "expense_bounds_move": bounds_move(before_call, now_call),
        })
    if snapshot and snapshot.get("workforce_reduction_positions"):
        story["positions"] = f"{snapshot['workforce_reduction_positions']:,}"
    for item in one_offs:
        if item.get("key"):
            story[item["key"]] = f"${item['usd_m']:,}M"
    if off_balance is not None:
        for item in off_balance["residual_value_guarantees"]:
            story[item["key"]] = f"约 US${item['usd_bn']:g}B"
    # How far into the year a full-year line already is, for the lines that
    # settle only when the year closes.
    progress = ({f"fy_operating_income:{guided_year}": (so_far_words, float(year_to_date_oi))}
                if 0 < elapsed < 4 else {})

    # ── section one ──────────────────────────────────────────────────────────
    # What last quarter left, in the order it was left: (a) the follow-up
    # questions, (b) the previous analysis's section-8 lines -- overview, then
    # each reading against its own record -- and (c) only then the company's
    # own guidance record.
    settled_charts: list[dict] = []
    closure_table = None
    if closure is not None:
        closure_chart, closure_table = closure_exhibit(closure, story)
        settled_charts.append(closure_chart)
    prior_entries: list[dict] = []
    if prior_kpi is not None:
        prior_entries = evaluate(staging, prior_kpi, "actual", period)
        basis_words = ""
        margin_lines = [entry for entry in prior_entries
                        if entry["measure"] == "operating_margin_adjusted" and entry["actual"] is not None]
        if margin_lines and one_offs:
            gaap_margin = operating_income[-1] / revenue[-1] * 100
            same = all(OPERATORS[entry["fires"]](round(gaap_margin, 6), entry["threshold"]) == entry["fired"]
                       for entry in margin_lines)
            basis_words = (f"原文没有写经营利润率用哪个口径，两个都算：按调整后（加回本季{one_off_words_named_first}）"
                           f"结算为 {margin_lines[0]['actual']:.2f}%，GAAP 口径 {gaap_margin:.2f}%，"
                           + ("两个口径在这几条线上的判定相同。" if same else "两个口径的判定不同，以核对表为准。"))
        settled_charts.append(prior_overview(prior_kpi, prior_entries, story, basis_words))
        settled_charts += threshold_line_charts(staging, prior_kpi, prior_entries, "actual")
    # META is the only US filer on this site that puts its quarterly guidance in
    # a filing, so it is the only one that can carry TSMC's guidance record.
    # Microsoft's own release says guidance is given on the webcast instead, and
    # Alphabet gives no quarterly number at all -- both are stated on their pages
    # rather than silently left out.
    settled_charts += [
        guidance_band(history["quarters"], history["guide_low_usd_bn"],
                      history["guide_high_usd_bn"], history["actual_revenue_usd_bn"]),
        guidance_deviation(history["quarters"], history["guide_low_usd_bn"],
                           history["guide_high_usd_bn"], history["actual_revenue_usd_bn"]),
    ]

    # ── section two ──────────────────────────────────────────────────────────
    revenue_step = long_revenue_yoy[-1] - long_revenue_yoy[-2]
    impressions_now, impressions_before = long_impressions[-1], long_impressions[-2]
    price_now, price_before = long_price[-1], long_price[-2]
    volume_led_slowdown = (advertising_yoy[-1] < advertising_yoy[-2]
                           and impressions_now < impressions_before and price_now >= price_before)
    negative_price = sum(1 for v in long_price if v is not None and v < 0)
    price_dips = runs_over_holes(long_price, lambda value: value < 0)
    leader = []
    for impressions, price in zip(long_impressions, long_price):
        if impressions is None or price is None or impressions == price:
            leader.append(None)
        else:
            leader.append("价" if price > impressions else "量")
    known = [(i, side) for i, side in enumerate(leader) if side]
    switches = sum(1 for (_, a), (_, b) in zip(known, known[1:]) if a != b)
    price_led = runs_over_holes(leader, lambda side: side == "价")
    dap = ads["family_daily_active_people_bn"]
    dap_growth = pct_change(dap[-1], dap[-5])
    bridge_gap = abs(volume_price_product[-1] - advertising_yoy[-1])
    closes_twice = all(abs(volume_price_product[i] - yoy(advertising)[i]) < 1.0 for i in (-1, -2))

    fcf_now, fcf_before = long_fcf[-1], long_fcf[-2]
    reported_fcf = [v for v in long_fcf if v is not None]
    fcf_high, fcf_low = max(reported_fcf), min(reported_fcf)
    trough = 0 <= fcf_now <= max(v for v in long_fcf if v is not None) * 0.1
    low_while_growing = [i for i in range(len(long_fcf) - 1)
                         if long_fcf[i] is not None and long_fcf[i] <= fcf_now
                         and long_revenue_yoy[i] is not None and long_revenue_yoy[i] >= 10]
    buybacks = q["stock_repurchases"]
    zero_run = 0
    for value in reversed(buybacks):
        if value != 0:
            break
        zero_run += 1
    ocf_step = pct_change(q["operating_cash_flow"][-1], q["operating_cash_flow"][-2])

    build_start = quarters.index(BUILD_OUT_FROM)
    earlier_peak_at = max(range(build_start), key=lambda i: long_capex_intensity[i])
    first_above = next((i for i in range(build_start, len(quarters))
                        if long_capex_intensity[i] > long_capex_intensity[earlier_peak_at]), None)
    intensity_ratio = long_capex_intensity[-1] / long_capex_intensity[0]

    highlights = [
        {
            "kind": "gs_bar",
            "title": (
                f"收入 ${long_revenue[-1]:,.0f}M、同比 {long_revenue_yoy[-1]:.1f}%，"
                f"较上季{'减速' if revenue_step < 0 else '加速'} {abs(revenue_step):.1f}pp"
            ),
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
                "name": "同比增速 (RHS) D",
                "values": long_revenue_yoy,
                "color": "GREEN",
                "yfmt": "pct1",
            },
            "note": (
                (f"较市场预期 ${consensus['revenue_usd_m']:,.0f}M "
                 f"{'高' if revenue_shown[-1] >= consensus['revenue_usd_m'] else '低'} "
                 f"{abs(pct_change(revenue_shown[-1], consensus['revenue_usd_m'])):.1f}%；"
                 if consensus else "")
                + (f"{period_of(coming)[:2]} 指引中点 ${q3_midpoint:,.0f}M，隐含同比 {signed(q3_yoy)}，"
                   + (f"再减速约 {revenue_yoy[-1] - q3_yoy:.0f}pp。" if q3_yoy < revenue_yoy[-1]
                      else f"较本季加速约 {q3_yoy - revenue_yoy[-1]:.0f}pp。")
                   if q3_midpoint else "")
            ),
            "src_extra": source_note("收入来自各期 10-Q / 10-K 与当季 release，同比为自算"),
        },
    ]
    if consensus is not None and snapshot is not None:
        highlights.append(expectation_chart(consensus, {
            "revenue_usd_m": revenue[-1],
            "diluted_eps_usd": snapshot["diluted_eps_usd"][0],
            "dap_bn": ads["family_daily_active_people_bn"][-1],
            "next_guide_mid_usd_m": q3_midpoint,
        }, one_offs, period))
    highlights += [
        {
            "kind": "lines",
            "title": (
                ("广告减速全部来自量：" if volume_led_slowdown else f"广告同比 {advertising_yoy[-1]:.1f}%：")
                + f"曝光同比 {impressions_now:.0f}%，"
                f"单价 {price_now:.0f}%，而{cn_count(years)}年里价这条线有 "
                f"{negative_price} 个季度是负的"
            ),
            "xlabels": long_labels,
            "xstep": LONG_STEP,
            "series": [
                {"name": "广告收入 YoY D", "values": long_advertising_yoy, "color": "NAVY"},
                {"name": "广告曝光 YoY", "values": long_impressions, "color": "MBLUE"},
                {"name": "平均每条广告价格 YoY", "values": long_price, "color": "GOLD"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "zero_base": True,
            "end_label": True,
            "ylab": "同比增速",
            "note": (
                (f"量价相乘可以闭合：" if bridge_gap < 1.0 else "量价相乘与实际差 "
                 f"{bridge_gap:.1f}pp：")
                + f"{(1 + ads['ad_impressions_yoy_pct'][-1] / 100):.2f} × "
                f"{(1 + ads['price_per_ad_yoy_pct'][-1] / 100):.2f} − 1 = "
                f"{volume_price_product[-1]:.1f}%，对上实际的 {advertising_yoy[-1]:.1f}%。"
                f"同期 Family DAP 仅 {dap[-1]:.2f}B、同比 {dap_growth:.0f}%，"
                f"曝光与用户之间约 {impressions_now - dap_growth:.0f}pp 的缺口来自广告负载与人均时长。"
                f"<b>{cn_count(years)}年的窗口里「量价谁在拉动」的答案换过{cn_count(switches)}次</b>："
                "价格跑赢曝光的只有 "
                + "、".join(span_text(quarters, a, b) for a, b in price_led)
                + f" {cn_count(len(price_led))}段，其余季度量不慢于价；"
                f"金色那条价格线有 {negative_price} 个季度为负"
                f"（最低 {min(v for v in long_price if v is not None):.0f}%），集中在 "
                + "、".join(span_text(quarters, a, b) for a, b in price_dips)
                + "。"
                f"<b>价与量两条线上有{cn_count(len(ad_rate_holes))}个缺口</b>（{'、'.join(ad_rate_holes)}）："
                f"那{cn_count(len(ad_rate_holes))}年公司只在 10-K 里给全年变动，第四季的季度值不存在于任何申报，"
                "本页留空而不是插值。"
            ),
            "src_extra": (
                "曝光与单价同比为公司披露的百分比；广告收入 = 总收入 − Reality Labs − FoA Other，"
                "同比为自算。量价乘积与实际增速的差异来自公司披露值的整数舍入。"
            ),
        },
    ]
    if geography is not None:
        highlights.append(regional_chart(geography, revenue_shown[-1], period))
    if one_offs:
        highlights.append({
            "kind": "bars_labeled",
            "title": (
                f"剔除 ${one_off_total:,}M 一次性项后，经营利润仍较上季"
                + (f"少 ${operating_income[-2] - adjusted_operating_income:,.0f}M"
                   if adjusted_operating_income < operating_income[-2] else
                   f"多 ${adjusted_operating_income - operating_income[-2]:,.0f}M")
            ),
            "xlabels": [f"{prev_period} 经营利润", f"{period} GAAP", f"{period} 调整后 D"],
            "values": [operating_income[-2], operating_income[-1], adjusted_operating_income],
            "legend": "经营利润",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "note": (
                f"加回{one_off_words_named_first} 得到 "
                f"${adjusted_operating_income:,}M；"
                f"同期收入环比 {signed(pct_change(revenue[-1], revenue[-2]))}，"
                + ("所以环比的经营杠杆是负的，与一次性项无关。"
                   if revenue[-1] > revenue[-2] and adjusted_operating_income < operating_income[-2] else
                   "剔除一次性项后环比经营杠杆不为负。")
            ),
            "src_extra": (
                f"GAAP 经营利润来自 {period} 10-Q；{cn_count(len(one_offs))}笔加回项的金额来自当季 release 与分部附注，"
                "调整后经营利润为两者相加的自算值，不是公司定义的 non-GAAP 指标。"
            ),
        })
    collapsed = 0 <= fcf_now < fcf_before * 0.5
    if not trough:
        trough_words = "。"
    elif long_revenue_yoy[-1] < 10:
        trough_words = "，本季收入增速也不在两位数。"
    elif not low_while_growing:
        trough_words = "，但它是唯一一次在收入仍在两位数增长时掉到这个水平。"
    else:
        trough_words = ("，收入仍在两位数增长时掉到这个水平，此前还有 "
                        + "、".join(f"{long_labels[i]}（${long_fcf[i]:,.0f}M，收入同比 "
                                   f"{long_revenue_yoy[i]:+.1f}%）" for i in low_while_growing) + "。")
    negative_fcf = sum(1 for v in long_fcf if v is not None and v < 0)
    fcf_title = (f"单季自由现金流塌到 ${fcf_now:,.0f}M，环比 {pct_change(fcf_now, fcf_before):.1f}% —— "
                 if collapsed else
                 f"单季自由现金流 ${fcf_now:,.0f}M，环比 {pct_change(fcf_now, fcf_before):.1f}% —— ")
    highlights += [
        {
            "kind": "diverging_bars",
            "title": (
                fcf_title
                + (f"{len(long_fcf)} 季里为负的有 {negative_fcf} 季" if negative_fcf
                   else f"{len(long_fcf)} 季里没有一季为负")
            ),
            "xlabels": long_labels,
            "xstep": LONG_STEP,
            "values": long_fcf,
            "legend": "自由现金流",
            "positive_label": "正自由现金流",
            "negative_label": "负自由现金流",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "zero_line": True,
            "note": (
                f"经营现金流 ${q['operating_cash_flow'][-1]:,.0f}M "
                + ("基本持平，" if abs(ocf_step) < 2 else f"环比 {signed(ocf_step)}，")
                + (f"资本开支却从 ${capex_shown[-2]:,.0f}M 跳到 ${capex_shown[-1]:,.0f}M；"
                   if capex_shown[-1] > capex_shown[-2] else
                   f"资本开支从 ${capex_shown[-2]:,.0f}M 降到 ${capex_shown[-1]:,.0f}M；")
                + (f"同季净发债 ${snapshot['net_debt_issuance_usd_m']:,}M、"
                   if snapshot and snapshot.get("net_debt_issuance_usd_m") else "")
                + (f"回购连续第{cn_ordinal(zero_run)}季为 $0。"
                   if zero_run >= 2 else "本季回购为 $0。" if zero_run == 1 else
                   f"本季回购 ${buybacks[-1]:,.0f}M。")
                + f"<b>{cn_count(years)}年的窗口给这一格一个参照</b>：{len(long_fcf)} 季里自由现金流的最高是 "
                f"${fcf_high:,.0f}M（{long_labels[long_fcf.index(fcf_high)]}），"
                f"最低 ${fcf_low:,.0f}M（{long_labels[long_fcf.index(fcf_low)]}）—— "
                + ("本季不是这条线最差的一格" if fcf_now > fcf_low else "本季是这条线最差的一格")
                + trough_words
            ),
            "src_extra": source_note(
                "FCF 按公司口径 = 经营现金流 − 购买物业及设备 − 融资租赁本金偿付"
            ),
        },
        {
            "kind": "gs_bar",
            "title": (
                f"资本开支 ${long_capex[-1]:,.0f}M、占收入 {long_capex_intensity[-1]:.1f}%，"
                f"{cn_count(years)}年前是 {long_capex_intensity[0]:.1f}%"
            ),
            "xlabels": long_labels,
            "xstep": LONG_STEP,
            "values": long_capex,
            "legend": "单季资本开支（含融资租赁）",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "ylab2": "占收入比",
            "yoy": {
                "name": "CapEx / 收入 (RHS) D",
                "values": long_capex_intensity,
                "color": "GOLD",
                "yfmt": "pct1",
            },
            "note": (
                f"<b>右轴那条占收入比是这张图的主角</b>：{cn_count(years)}年区间 "
                f"{min(long_capex_intensity):.1f}%–{max(long_capex_intensity):.1f}%，"
                f"{quarters[0]} 是 {long_capex_intensity[0]:.1f}%，本季 {long_capex_intensity[-1]:.1f}% —— "
                + ("资本强度翻了不止一倍" if intensity_ratio >= 2 else
                   f"资本强度是那时的 {intensity_ratio:.1f} 倍")
                + (f"，而越过 {quarters[earlier_peak_at]} 的前高 "
                   f"{long_capex_intensity[earlier_peak_at]:.1f}% 是 {quarters[first_above]} 以后才发生的。"
                   if first_above is not None else "。")
                + (f"{so_far} 已实现 ${year_to_date_capex:,}M，全年指引下限 "
                   f"US${capex_calls[-1]['low']:g}B 隐含{spaced(rest)}还要再做 "
                   f"${capex_calls[-1]['low'] * 1000 - year_to_date_capex:,.0f}M，"
                   + ("即单季规模较本季再上一个台阶。"
                      if (capex_calls[-1]['low'] * 1000 - year_to_date_capex) / (4 - elapsed) > capex_total[-1]
                      else "单季规模不必再高于本季。")
                   if capex_calls and 0 < elapsed < 4 else "")
            ),
            "src_extra": (
                "资本开支为购买物业及设备加融资租赁本金，与公司指引口径一致；占收入比为自算。"
                "经营租赁的租金与不并表合资的建设支出不进这条线，所以它是资本强度的下界而非全貌"
                "（已签约未起租的租赁义务见本板块最后一张图）。"
            ),
        },
    ]
    capex_raises = sum(1 for a, b in zip(capex_guide_mid, capex_guide_mid[1:]) if b > a)
    if capex_calls:
        raises = sum(1 for a, b in zip(capex_guide_mid, capex_guide_mid[1:]) if b > a)
        cuts = sum(1 for a, b in zip(capex_guide_mid, capex_guide_mid[1:]) if b < a)
        span_days = (datetime.date.fromisoformat(capex_calls[-1]["filed"])
                     - datetime.date.fromisoformat(capex_calls[0]["filed"])).days
        within = "半年内" if span_days <= 184 else ("一年内" if span_days <= 366 else "")
        if len(capex_calls) == 1:
            capex_title = f"FY{guided_year} CapEx 首次指引 US${range_text(capex_calls[0]['low'], capex_calls[0]['high'])}B"
        elif cuts == 0 and raises == len(capex_calls) - 1:
            capex_title = (f"FY{guided_year} CapEx 指引{within}{cn_count(raises)}次上调，"
                           f"中点从 US${capex_guide_mid[0]:.0f}B 抬到 US${capex_guide_mid[-1]:.1f}B")
        else:
            capex_title = (f"FY{guided_year} CapEx 指引{within}改过{cn_count(len(capex_calls) - 1)}次"
                           f"（{cn_count(raises)}次上调、{cn_count(cuts)}次下调），"
                           f"中点从 US${capex_guide_mid[0]:.0f}B 到 US${capex_guide_mid[-1]:.1f}B")
        last, before = capex_calls[-1], capex_calls[-2] if len(capex_calls) > 1 else None
        narrowed_up = (before is not None and last["low"] > before["low"] and last["high"] == before["high"])
        prior_actual = (base["purchases_of_property_and_equipment"] + base["finance_lease_principal"]
                        if base else None)
        highlights.append({
            "kind": "bars_labeled",
            "title": capex_title,
            "xlabels": [f"{call_of(call['filed'])} call" for call in capex_calls],
            "values": capex_guide_mid,
            "legend": f"FY{guided_year} CapEx 指引中点",
            "fmt": "usd1",
            "yfmt": "usd1",
            "label_fmt": "usd1",
            "ylab": "US$B",
            "note": (
                "区间依次为 " + "、".join(f"US${range_text(call['low'], call['high'])}B" for call in capex_calls)
                + "。"
                + ("最新一次是区间收窄，但收窄的方式是抬高下限——中点仍在上移。" if narrowed_up else "")
            ),
            "src_extra": (
                f"{cn_count(len(capex_calls))}次区间逐字取自对应季度业绩 8-K EX-99.1 的 CFO Outlook Commentary；中点为自算。"
                + (f"FY{base_year} 实际（同口径，含融资租赁本金）${prior_actual:,}M，最新中点比它高 "
                   f"{pct_change(capex_guide_mid[-1] * 1000, prior_actual):.1f}%。" if prior_actual else "")
            ),
        })
    leases_chart = None
    if staging.get("leases_not_yet_commenced"):
        leases_chart = off_balance_chart(staging["leases_not_yet_commenced"], off_balance, period)
        highlights.append(leases_chart)

    # ── section three ────────────────────────────────────────────────────────
    # This quarter's section 8, tier by tier, placed against where the quarter
    # left each reading. Same format as last quarter's block, so the roll moves
    # it into `prior_kpi_settlement` as it stands.
    next_entries = evaluate(staging, next_kpi, "current", period)
    next_charts = ([next_overview(next_kpi, next_entries, story, progress, period)]
                   + threshold_line_charts(staging, next_kpi, next_entries, "current"))

    # ── section four ─────────────────────────────────────────────────────────
    ahead = runs([None if a is None or b is None else a - b
                  for a, b in zip(long_depreciation_yoy, long_revenue_yoy)], lambda gap: gap > 0)
    current_run = ahead[-1] if ahead and ahead[-1][1] == len(quarters) - 1 else None
    earlier_runs = [run for run in ahead if run is not current_run]
    multiple_now = capex_shown[-1] / depreciation_shown[-1]
    multiple_before = capex_shown[-2] / depreciation_shown[-2]
    peak_ttm = max(v for v in long_ttm_fcf if v is not None)
    turned_last_quarter = (long_ttm_fcf[-1] < long_ttm_fcf[-2] and long_ttm_fcf[-2] > long_ttm_fcf[-3])
    rl_yoy = yoy(q["reality_labs_revenue"])
    long_reality_yoy = [None] * 4 + [
        None if long_reality[i] is None or not long_reality[i - 4] else pct_change(long_reality[i], long_reality[i - 4])
        for i in range(4, len(long_reality))]
    rl_step = ("首次转正" if rl_yoy[-1] > 0 and all(v is None or v <= 0 for v in long_reality_yoy[:-1])
               else "转正" if rl_yoy[-1] > 0 and rl_yoy[-2] <= 0
               else "为正" if rl_yoy[-1] > 0
               else "转负" if rl_yoy[-2] > 0 else "仍为负")
    foa_first_billion = foa_other_shown[-1] >= 1000 > max(v for v in long_foa_other[:-1] if v is not None)
    # Both non-advertising lines add revenue that does not depend on ad load; how
    # the year-on-year increment splits between them is computed, not asserted.
    foa_increment = foa_other_shown[-1] - foa_other_shown[-5]
    rl_increment = reality_labs_shown[-1] - reality_labs_shown[-5]
    routine = [
        {
            "kind": "lines",
            "title": (
                f"折旧摊销同比 {depreciation_yoy[-1]:+.1f}%，"
                f"{'快' if depreciation_yoy[-1] > revenue_yoy[-1] else '慢'}于收入的 {revenue_yoy[-1]:+.1f}%"
            ),
            "xlabels": long_labels[yoy_from:],
            "xstep": LONG_STEP,
            "series": [
                {"name": "折旧摊销同比", "values": long_depreciation_yoy[yoy_from:],
                 "color": "RED"},
                {"name": "收入同比", "values": long_revenue_yoy[yoy_from:], "color": "NAVY"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "end_label": True,
            "ylab": "同比增速",
            "note": (
                f"本季资本开支是折旧摊销的 {multiple_now:.1f} 倍，"
                "意味着这条线的上行才刚开始；折旧曲线与收入曲线的交叉点，是这轮资本周期的定价问题。"
                f"<b>把两条同比放在一张图上，{cn_count(years)}年里折旧跑赢收入的有{cn_count(len(ahead))}段</b> —— "
                + "、".join(span_text(quarters, a, b) for a, b in ahead)
                + (f"；上一段持续了{cn_count(earlier_runs[-1][1] - earlier_runs[-1][0] + 1)}季"
                   if earlier_runs else "")
                + ("，而这一次资本开支与折旧的倍数还在扩大。" if current_run and multiple_now > multiple_before
                   else "。")
            ),
            "src_extra": source_note(
                "折旧摊销逐季来自各期现金流量表（只按年初至今披露，逐季由相邻两个年初至今值"
                "相减，第四季为全年 − 前三季）；同比为自算"),
        },
        {
            "kind": "lines",
            "title": (
                f"TTM 自由现金流由 ${peak_ttm:,.0f}M 回落到 ${ttm_fcf[-1]:,.0f}M"
                if ttm_fcf[-1] < peak_ttm else f"TTM 自由现金流创新高：${ttm_fcf[-1]:,.0f}M"
            ),
            "xlabels": long_labels[ttm_from:],
            "xstep": LONG_STEP,
            "series": [
                {"name": "TTM 自由现金流", "values": long_ttm_fcf[ttm_from:], "color": "NAVY"},
            ],
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "end_label": True,
            "ylab": "$M",
            "note": (
                f"滚动四季口径把单季税款与季节性摊平；同比 "
                f"{pct_change(ttm_fcf[-1], ttm_fcf[-5]):+.1f}%"
                + ("，拐点出现在上一季。" if turned_last_quarter else "。")
                + f"<b>这条线从 {long_labels[ttm_from]} 起</b>：滚动四季要先攒满四个季度。"
                f"{long['finance_lease_note']}"
            ),
            "src_extra": source_note("按各季经营现金流减资本开支（含融资租赁本金）滚动四季求和（自算）"),
        },
        {
            "kind": "lines",
            "title": (
                "两条非广告收入线分道扬镳："
                + (f"FoA Other 首破 $10 亿" if foa_first_billion else f"FoA Other ${foa_other_shown[-1]:,.0f}M")
                + f"，Reality Labs 仍在 ${reality_labs_shown[-1]:,.0f}M"
            ),
            "xlabels": long_labels[segment_from:],
            "xstep": LONG_STEP,
            "series": [
                {"name": "FoA Other", "values": long_foa_other[segment_from:], "color": "NAVY"},
                {"name": "Reality Labs", "values": long_reality[segment_from:],
                 "color": "MBLUE"},
            ],
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "zero_base": True,
            "end_label": True,
            "ylab": "$M",
            "note": (
                f"FoA Other 同比 {foa_other_yoy[-1]:+.1f}%、年化约 "
                f"${foa_other_shown[-1] * 4 / 1000:.1f}B"
                + (f"：两条非广告收入线的同比增量 ${foa_increment + rl_increment:,.0f}M 里，"
                   f"{foa_increment / (foa_increment + rl_increment) * 100:.0f}% 来自它；"
                   if foa_increment > 0 and rl_increment > 0 else
                   "：两条非广告收入线的同比增量全部来自它；" if foa_increment > 0 >= rl_increment else "；")
                + f"Reality Labs 收入同比 {pct_change(reality_labs_shown[-1], reality_labs_shown[-5]):+.1f}% {rl_step}"
                + (f"，但本季经营亏损仍有 ${abs(snapshot['reality_labs_operating_loss_usd_m'][0]):,}M。"
                   if snapshot else "。")
                + f"<b>这张图只能回到 {long_labels[segment_from]}，不能到 {quarters[0][:4]}</b>：{long['segment_note']}"
            ),
            "src_extra": (
                "两条分项收入逐季来自各期 10-Q / 10-K 收入分解附注的分部维度事实；"
                "第四季取公司 Q4 新闻稿印出来的三个月列，而不是「全年 − 前三季」的相减值 —— "
                "相减的两条腿各自已四舍五入到百万，2024Q4 因此会算出 519 与 522 两个版本，"
                "公司自己印的是 519。Reality Labs 的 Q4 有硬件季节性，不宜按环比读。"
            ),
        },
    ]

    exhibits = number_exhibits(settled_charts + highlights + next_charts + routine)
    first_table = len(exhibits) + 2

    quarterly_rows = []
    for index, p in enumerate(periods):
        quarterly_rows.append([
            p,
            f"${revenue[index]:,.0f}M",
            f"${advertising[index]:,.0f}M D",
            f"${q['foa_other_revenue'][index]:,.0f}M",
            f"${q['reality_labs_revenue'][index]:,.0f}M",
            f"${operating_income[index]:,.0f}M",
            f"${q['operating_cash_flow'][index]:,.0f}M",
            f"${capex_total[index]:,.0f}M D",
            (lambda value: f"-${abs(value):,.0f}M" if value < 0 else f"${value:,.0f}M")(
                free_cash_flow[index]
            ),
            f"${q['depreciation_and_amortization'][index]:,.0f}M",
            f"${q['share_based_compensation'][index]:,.0f}M",
            f"${q['stock_repurchases'][index]:,.0f}M",
        ])

    ad_rows = []
    for index, p in enumerate(periods):
        ad_rows.append([
            p,
            f"{ads['ad_impressions_yoy_pct'][index]:+.0f}%",
            f"{ads['price_per_ad_yoy_pct'][index]:+.0f}%",
            f"{volume_price_product[index]:+.1f}% D",
            "—" if index < 4 else f"{yoy(advertising)[index]:+.1f}% D",
            f"{ads['family_daily_active_people_bn'][index]:.2f}B",
        ])

    def three(values: list, money: bool = True) -> list[str]:
        """This quarter, last quarter, a year ago → the table's three period cells and two changes."""
        cur, prev, prior = values
        cell = (lambda v: "—" if v is None else f"${v:,}M") if money else (lambda v: "—" if v is None else v)
        return [cell(prior), cell(prev), cell(cur),
                "—" if prev is None else f"{pct_change(cur, prev):+.1f}%",
                "—" if prior is None else f"{pct_change(cur, prior):+.1f}%"]

    def loss_words(cur: float, base_value: float) -> str:
        return "亏损扩大" if cur < base_value else "亏损收窄"

    series_three = lambda values: [values[-1], values[-2], values[-5]]  # noqa: E731
    quality_rows = []
    if snapshot is not None:
        rl_loss = snapshot["reality_labs_operating_loss_usd_m"]
        eps = snapshot["diluted_eps_usd"]
        unpaid = snapshot["unpaid_capex_in_payables_usd_m"]
        restricted = snapshot["restricted_cash_in_other_assets_usd_m"]
        heads = snapshot["headcount"]
        quality_rows = [
            ["总收入"] + three(series_three(revenue)),
            ["广告收入"] + three(series_three(advertising)),
            ["Family of Apps 经营利润"] + three(snapshot["family_of_apps_operating_income_usd_m"]),
            ["Reality Labs 经营亏损", f"-${abs(rl_loss[2]):,}M", f"-${abs(rl_loss[1]):,}M",
             f"-${abs(rl_loss[0]):,}M", loss_words(rl_loss[0], rl_loss[1]), loss_words(rl_loss[0], rl_loss[2])],
            ["经营利润（GAAP）"] + three(series_three(operating_income)),
            ["经营利润（调整后 D）", "—", "—",
             f"${adjusted_operating_income:,}M", "—",
             f"{pct_change(adjusted_operating_income, operating_income[-5]):+.1f}%"],
            ["稀释 EPS", f"${eps[2]:.2f}", f"${eps[1]:.2f}", f"${eps[0]:.2f}",
             f"{pct_change(eps[0], eps[1]):+.1f}%", f"{pct_change(eps[0], eps[2]):+.1f}%"],
            ["经营现金流"] + three(series_three(q["operating_cash_flow"])),
            ["资本开支（含融资租赁）"] + three(series_three(capex_total)),
            ["自由现金流 D"] + three(series_three(free_cash_flow)),
            ["计入应付的未付资本开支"] + three(unpaid),
            ["其他资产项下的受限现金", f"${restricted[2]:,}M", "—", f"${restricted[0]:,}M", "—",
             (f"含 ${off_balance['restricted_escrow_usd_bn']:.2f}B 多年期基础设施采购协议的托管资金，"
              f"预计 {off_balance['restricted_escrow_release']} 释放（10-Q）"
              if off_balance else f"{pct_change(restricted[0], restricted[2]):+.1f}%")],
            ["员工数", f"{heads[2]:,}", f"{heads[1]:,}", f"{heads[0]:,}",
             f"{pct_change(heads[0], heads[1]):+.1f}%", f"{pct_change(heads[0], heads[2]):+.1f}%"],
        ]
        if one_offs:
            if len(one_offs) != 2:
                pass
        else:
            quality_rows = [row for row in quality_rows if not row[0].startswith("经营利润（调整后")]

    expense_rows = []
    if expense is not None:
        expense_rows = [
            [
                name,
                f"${prior:,}M",
                f"${current:,}M",
                f"{pct_change(current, prior):+.1f}%",
                f"{current / revenue_shown[-1] * 100:.2f}%",
            ]
            for name, current, prior in zip(expense["lines"], expense["current"], expense["prior_year"])
        ]
        expense_rows.append([
            "合计",
            f"${sum(expense['prior_year']):,}M",
            f"${sum(expense['current']):,}M",
            f"{pct_change(sum(expense['current']), sum(expense['prior_year'])):+.1f}%",
            f"{sum(expense['current']) / revenue_shown[-1] * 100:.2f}%",
        ])

    guidance_rows = []
    if q3_midpoint:
        guidance_rows.append(
            [f"{period_of(coming)} 收入", "—", "—", f"US${q3_low:.0f}–{q3_high:.0f}B",
             f"中点 ${q3_midpoint:,.0f}M，隐含同比 {signed(q3_yoy)} D"])
    if len(expense_calls) >= 2:
        before_exp, now_exp = expense_calls[-2], expense_calls[-1]
        move = []
        if now_exp["low"] != before_exp["low"]:
            move.append(f"下限{'抬高' if now_exp['low'] > before_exp['low'] else '下调'} "
                        f"${abs(now_exp['low'] - before_exp['low']):g}B")
        if now_exp["high"] != before_exp["high"]:
            move.append(f"上限{'抬高' if now_exp['high'] > before_exp['high'] else '下调'} "
                        f"${abs(now_exp['high'] - before_exp['high']):g}B")
        guidance_rows.append(
            [f"FY{guided_year} 总费用", f"US${range_text(before_exp['low'], before_exp['high'])}B", "—",
             f"US${range_text(now_exp['low'], now_exp['high'])}B",
             ("、".join(move) + (" " + outlook["expense_change_reason"]
                                 if outlook and outlook.get("expense_change_reason") else "")) if move else "不变"])
    if len(capex_calls) >= 2:
        guidance_rows.append(
            [f"FY{guided_year} CapEx", f"US${range_text(capex_calls[-2]['low'], capex_calls[-2]['high'])}B",
             f"{so_far} 已实现 ${year_to_date_capex:,}M",
             f"US${range_text(capex_calls[-1]['low'], capex_calls[-1]['high'])}B",
             f"中点由 US${capex_guide_mid[-2]:.0f}B {'抬到' if capex_guide_mid[-1] > capex_guide_mid[-2] else '改为'} "
             f"US${capex_guide_mid[-1]:.1f}B D"])
    if outlook is not None:
        if base:
            guidance_rows.append(
                [f"FY{guided_year} 经营利润", outlook["operating_income_commitment_prior"],
                 f"{so_far} ${year_to_date_oi:,}M", outlook["operating_income_commitment"],
                 f"FY{base_year} 为 ${base['operating_income']:,}M；{line_words} ${pace_line:,.0f}M D"])
        tax_move = ((outlook["tax_rate_pct"][0] + outlook["tax_rate_pct"][1])
                    - (outlook["tax_rate_prior_pct"][0] + outlook["tax_rate_prior_pct"][1])) / 2
        guidance_rows.append(
            ["余下各季有效税率",
             f"{outlook['tax_rate_prior_pct'][0]}–{outlook['tax_rate_prior_pct'][1]}%", "—",
             f"{outlook['tax_rate_pct'][0]}–{outlook['tax_rate_pct'][1]}%",
             "持平" if tax_move == 0 else f"区间中值{'上调' if tax_move > 0 else '下调'} {abs(tax_move):g}pp D"])
        guidance_rows.append(
            [f"FY{int(guided_year) + 1} CapEx", outlook["fy2027_capex_prior"], "—",
             outlook["fy2027_capex"], outlook["fy2027_capex_remark"]])

    tables = []
    if closure_table is not None:
        tables.append(closure_table)
    if prior_kpi is not None:
        tables.append(settlement_table(f"上季（{prior_kpi['set_in']}）第 8 节逐档结算（原单位）", prior_entries,
                                       "actual", f"{period} 实际", story))
        tables.append(prior_row_table(prior_kpi))
    tables.append(settlement_table(f"下季阈值与当前值（原单位，结算 {next_kpi['for_period']}）", next_entries,
                                   "current", "当前值", story))
    tables.append(next_row_table(next_kpi))
    if guidance_rows:
        tables.append({
            "n": 0,
            "title": f"{period[:2]} 兑现、{period_of(coming)[:2]} 指引与全年 outlook",
            "headers": ["指标", "上季口径", "本季已实现", "本季新口径", "变化 / 备注"],
            "rows": guidance_rows,
        })
    if quality_rows:
        tables.append({
            "n": 0,
            "title": f"当季经营质量与可比性（{year_ago} / {prev_period} / {period}）",
            "headers": ["指标", year_ago, prev_period, period, "QoQ", "YoY"],
            "rows": quality_rows,
        })
    tables += [
        {
            "n": 0,
            "title": f"{cn_count(len(periods))}季度基础数据（前四季只用于计算同比）",
            "headers": ["期间", "总收入", "广告收入", "FoA Other", "Reality Labs", "经营利润",
                        "经营现金流", "资本开支", "自由现金流 D", "折旧摊销", "股权激励", "回购"],
            "rows": quarterly_rows,
        },
        {
            "n": 0,
            "title": f"{cn_count(len(periods))}季度广告量价与用户",
            "headers": ["期间", "曝光 YoY", "单价 YoY", "量价乘积 D", "广告收入 YoY D", "Family DAP"],
            "rows": ad_rows,
        },
    ]
    if expense_rows:
        tables.append({
            "n": 0,
            "title": f"本季{cn_count(len(expense['lines']))}条费用线（{period} vs {year_ago}）",
            "headers": ["费用线", year_ago, period, "YoY", "占本季收入 D"],
            "rows": expense_rows,
        })
    tables.append(ai_capex_cycle_table(0))
    for offset, table in enumerate(tables):
        table["n"] = first_table + offset

    # ── the lines the page leads with ───────────────────────────────────────
    adjusted_margin = adjusted_operating_income / revenue[-1] * 100
    headline = (
        ("广告引擎本身没坏——" if closes_twice else "")
        + f"收入 ${revenue_shown[-1]:,}M、同比 {revenue_yoy[-1]:.1f}%"
        + ("，量价桥两季都能闭合；" if closes_twice else "；")
        + (("但多做的收入不再产生利润：" if adjusted_operating_income < operating_income[-2] and revenue[-1] > revenue[-2] else "")
           + (f"剔除 ${one_off_total:,}M 一次性项后经营利润仍环比 "
              f"{pct_change(adjusted_operating_income, operating_income[-2]):.1f}%，" if one_offs else
              f"经营利润环比 {pct_change(operating_income[-1], operating_income[-2]):.1f}%，"))
        + f"同比增量经营利润率{'只有' if adjusted_incremental_margin < adjusted_margin else '为'} "
        f"{adjusted_incremental_margin:.1f}%，"
        + (f"单季自由现金流塌到 ${fcf_shown[-1]:,}M。" if collapsed
           else f"单季自由现金流 ${fcf_shown[-1]:,}M。")
        + (f"财报后股价下跌约 {abs(price_high):.0f}%–{abs(price_low):.0f}%。"
           if price_high is not None and price_high < 0 else "")
    )
    price_streak = 1
    for index in range(len(long_price) - 1, 0, -1):
        if long_price[index - 1] is None or long_price[index - 1] != long_price[-1]:
            break
        price_streak += 1
    qoq_incremental = measure_series(staging)["incremental_margin_qoq_adjusted"][-1]
    adjusted_change = adjusted_operating_income - (
        operating_income[-2] + sum(item["usd_m"] for item in one_off_record(staging).get(prev_period, [])))
    brief = (
        '<h4>本季三条主线</h4><div class="takeaway-grid">'
        '<article><span>亮点</span><b>广告绝对竞争力没有裂缝</b>'
        f'<p>广告收入同比 {advertising_yoy[-1]:.1f}%，'
        + (f'单价连续{cn_count(price_streak)}季 {price_now:+.0f}%；' if price_streak >= 2
           else f'单价 {price_now:+.0f}%；')
        + (f'FoA Other 首破 $10 亿、同比 {foa_other_yoy[-1]:.0f}%。' if foa_first_billion
           else f'FoA Other ${foa_other_shown[-1]:,.0f}M、同比 {foa_other_yoy[-1]:.0f}%。')
        + '</p></article>'
        + ('<article><span>结构</span><b>减速全部来自量</b>' if volume_led_slowdown
           else '<article><span>结构</span><b>量与价</b>')
        + f'<p>曝光同比 {impressions_before:.0f}% → {impressions_now:.0f}%，'
        f'价格贡献 {price_now - price_before:.0f}pp；曝光与 DAP 之间约 {impressions_now - dap_growth:.0f}pp 靠广告负载。</p></article>'
        + ('<article><span>存疑</span><b>增量资本没有产出增量利润</b>'
           if adjusted_incremental_margin < adjusted_margin / 2 else
           '<article><span>观察</span><b>增量利润率与资本强度</b>')
        + '<p>'
        + (f'环比多做 ${revenue[-1] - revenue[-2]:,}M 收入，调整后经营利润'
           f'{"少" if adjusted_change < 0 else "多"} ${abs(adjusted_change):,}M'
           f'（环比增量经营利润率 {qoq_incremental:+.1f}%）；'.replace("-", "−")
           if qoq_incremental is not None else "")
        + f'同比增量经营利润率 {adjusted_incremental_margin:.1f}%，'
        f'资本开支占收入 {capex_intensity[-1]:.1f}%。</p></article>'
        '</div>'
    )

    parts = ["上季兑现", "本季重点", "下季跟踪", "长期常规"]
    notes = [
        f"本页按「{' → '.join(parts)}」{cn_count(len(parts))}段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
    ]
    settled_bar = next(ex for ex in settled_charts if ex["kind"] == "diverging_bars")
    notes.append(f"Exhibit {settled_bar['n']} 与 Exhibit {next_charts[0]['n']} 的阈值是本地研究设定，"
                 "不是公司指引，也不构成评级或投资建议；「距阈值余量」统一为正值代表落在有利一侧"
                 "（警示线未触发、目标线已到）。")
    notes += [
        "本页只发布公司披露值、可复算的简单派生值，以及明确标注的市场预期；D 标记代表 Derived / 自算。",
        "市场预期一律标注为「市场预期」并给出取数时点，不写卖方机构名，也不发布评级、目标价或估值。",
    ]
    if one_offs:
        notes.append(f"调整后经营利润 = GAAP 经营利润加回本季{one_off_words_named_first}，是算术加总，"
                     "不是公司定义的 non-GAAP 指标；10-Q 只说遣散费分摊在两个分部、没有给分部金额，"
                     "因此分部层面的调整后利润率无法拆分。")
    notes += [
        "增量经营利润率 = 经营利润的变动 ÷ 收入的变动。长期序列用同比口径，因为第四季的季节性足以让环比口径"
        "每年两次翻转符号；下季阈值按本季分析原文用环比口径，收入环比下降的季度没有环比增量利润率，图上留空。",
        "广告收入 = 总收入 − Reality Labs − FoA Other，三条线始终加回报告总额；"
        "量价乘积为公司披露的曝光与单价同比相乘，与实际广告收入增速的差异来自整数舍入。",
        "自由现金流按公司口径 = 经营现金流 − 购买物业及设备 − 融资租赁本金偿付；资本开支同口径含融资租赁。",
        "公司口径的资本开支（及其指引）含融资租赁本金，但不含经营租赁的租金与不并表合资的建设支出；"
        "本页因此把资本强度曲线标注为下界而非全貌，已签约未起租的租赁义务单独成图。",
    ]
    if price_high is not None:
        notes.append(f"财报后股价反应各公开来源报价不一致（约 {abs(price_high):.0f}%–{abs(price_low):.0f}%），本页只发布区间，不取单一数值。")
    notes += [
        "季度值来自各期 10-Q 与 10-K；无 10-Q 的第四季度按「全年 − 前三季」倒推，"
        "个别科目因公司按百万美元四舍五入，倒推值与逐季披露值存在 $1M 级差异。",
        "本页已知未接入：分部季度经营利润的完整历史、区域收入的多季序列、按分部拆分的一次性项、"
        "以及电话会口径的 Meta AI、business agents、AI 眼镜等运营 KPI（公司仅给相对数）。",
    ]

    next_bars = [entry for entry in next_entries if on_bars(entry, "current")]
    sections = [{
        "id": "settled",
        "title": "一、上季跟踪指标兑现了吗",
        "description": (
            "先结算上季留下的东西，再看本季数据——否则页面只会不断累积判断，从不闭环。顺序是："
            f"上季（{closure['set_in']}）分析留下的 {len(closure['items'])} 条待验证问题，照本季分析第 0 节的判定；"
            f"上季第 8 节 {len(prior_kpi['rows'])} 行阈值逐档拆成 {len(prior_entries)} 条线，读数由本页从申报现算；"
            "最后是公司自己在每季新闻稿里给的下季收入区间与随后的实际值。"),
        "exhibits": exhibits[: len(settled_charts)],
    }, {
        "id": "quarter_highlights",
        "title": "二、本季重点",
        "description": ("本季分析的核心结论里能用申报数画的，一图一个结论：收入"
                        + ("与对市场预期" if consensus is not None and snapshot is not None else "")
                        + "、广告的量价拆分"
                        + ("与各区域的收入增速" if geography is not None else "")
                        + ("、一次性项之后的经营利润" if one_offs else "")
                        + "、现金流与资本开支"
                        + (f"、资本开支指引的{cn_count(capex_raises)}次上调" if capex_raises else "")
                        + ("与不进资本开支线的租赁和合资承诺" if leases_chart is not None else "")
                        + "。报告核心矛盾里全年增量经营利润率的区间依赖报告自设的第四季收入假设（公司不给第四季指引），"
                          "本页不画；第三板块按上半年实际与全年承诺的差距跟踪同一件事。"),
        "exhibits": exhibits[len(settled_charts): len(settled_charts) + len(highlights)],
    }, {
        "id": "next_quarter",
        "title": "三、下季要跟踪什么",
        "description": (f"本季（{period}）分析第 8 节 {len(next_kpi['rows'])} 行与立场撤销条件，逐档拆成 "
                        f"{len(next_entries)} 条线：{len(next_bars)} 条有当前读数，进总览柱图并按读数逐张画出历史；"
                        "其余的（要连续两季的、阈值为 0 的、要等全年或下一次披露的）写在总览图注与核对表。"),
        "exhibits": exhibits[
            len(settled_charts) + len(highlights):
            len(settled_charts) + len(highlights) + len(next_charts)
        ],
    }]
    sections.append({
        "id": "routine",
        "title": "四、长期常规跟踪",
        "description": "META 专属的常规序列：折旧曲线、现金转换与非广告收入线。",
        "exhibits": exhibits[-len(routine):],
    })

    return {
        "schema_version": "quarterly-dashboard/meta-v1",
        "page": {"slug": "meta", "language": "zh-CN"},
        "company": {
            "ticker": "META",
            "name": "Meta Platforms",
            "group": "internet",
            "accounting_standard": "US GAAP",
        },
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · META",
        "title": f"Meta Platforms (META)：{period} 季报仪表盘",
        "subtitle": (f"截至 {latest['period_end']} · 发布 {latest['release_date']} · US GAAP · "
                     f"{AUDIT_WORDS[latest['audit_status']]} · 金额单位为 $M，另有注明除外"),
        "headline": headline,
        "brief": brief,
        "source": source,
        "source_url": "https://investor.atmeta.com/",
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": sections,
        "tables": tables,
        "notes": notes,
        "footer": (
            "META quarterly results · 数据来自 Meta Platforms 公开披露与透明自算 · "
            "仅供研究，不构成投资建议"
        ),
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "meta.js"), payload, "meta")
    shell_dir = ROOT / "meta"
    shell_dir.mkdir(exist_ok=True)
    # Rendered here, not at import: the shell stamps the payload's content
    # hash into its <script src>, so it has to be built after write_dash.
    (shell_dir / "index.html").write_text(
        render_shell("META", "meta"), encoding="utf-8")
    exhibits = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"META page: {exhibits} charts in {len(payload['sections'])} sections + "
          f"{len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
