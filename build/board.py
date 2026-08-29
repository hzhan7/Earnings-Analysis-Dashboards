"""Shared pieces for the chart-led company pages.

The page exists to be scanned, not read, so anything that would otherwise be a
wall of thresholds is turned into one chart: `headroom_exhibit` normalises a
mixed-unit KPI list into a single "distance from the threshold" number, so a
reader sees which lines are breached without parsing units.

`ai_capex_cycle_table` is the one cross-company object both pages publish.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Callable


def headroom(direction: str, threshold: float, actual: float) -> float:
    """Return distance from a threshold in percent, signed so positive is safe.

    Metrics arrive in percent, US$M, days and FX rates, and a page that shows
    eight of them side by side has to put them on one axis or it is a table
    again.  ``direction`` says which side of the threshold is safe, so a
    "must stay above" and a "must stay below" line read the same way.
    """
    if direction not in ("up", "down"):
        raise ValueError(f"unknown threshold direction: {direction}")
    if threshold == 0:
        raise ValueError("threshold of zero has no percentage headroom")
    sign = 1.0 if direction == "up" else -1.0
    return sign * (actual - threshold) / abs(threshold) * 100.0


# Money keeps its sign outside the currency symbol: a threshold of minus ten
# billion reads as "−US$10.0B", not "US$-10.0B". Amazon is the first company
# here whose free-cash-flow threshold is negative, and the naive format put the
# minus where a reader parses it as part of the unit.
UNIT_FORMATS = {
    "pct": lambda value: f"{value:.1f}%",
    "pp": lambda value: f"{value:+.1f}pp",
    "usd_m": lambda value: f"{'−' if value < 0 else ''}${abs(value):,.0f}M",
    "usd_bn": lambda value: f"{'−' if value < 0 else ''}US${abs(value):.1f}B",
    "days": lambda value: f"{value:.0f}天",
    "fx": lambda value: f"{value:.2f}",
    "million": lambda value: f"{value:.0f}M",
    # Cadence settles two thresholds that are neither money nor a rate: a
    # coverage ratio (backlog over trailing revenue) and a book-to-bill, both of
    # which read as "times".  Per-share amounts get their own key so a US$8.10
    # EPS threshold is not printed as though it were eight million dollars.
    "times": lambda value: f"{value:.2f}x",
    "usd_eps": lambda value: f"{'−' if value < 0 else ''}${abs(value):.2f}",
    # Ferrari is the first filer here that reports in a currency other than the
    # US dollar, so its thresholds cannot borrow `usd_m` -- printing a euro
    # figure with a dollar sign is a unit error a reader cannot see through.
    "eur_m": lambda value: f"{'−' if value < 0 else ''}€{abs(value):,.0f}M",
    "eur_bn": lambda value: f"{'−' if value < 0 else ''}€{abs(value):.2f}B",
    "eur_eps": lambda value: f"{'−' if value < 0 else ''}€{abs(value):.2f}",
    # Costco is the first page whose threshold sits on a *change* the company
    # states in basis points rather than on a level. Storing it in percentage
    # points would print both the threshold (−0.10pp) and the current value
    # (−0.09pp) as "-0.1pp", so the audit table could not tell them apart.
    "bps": lambda value: f"{value:+.0f}bp",
    # CME is the first page whose thresholds are a contract volume and a
    # per-contract rate. Average daily volume is quoted in thousands of
    # contracts and the interesting moves are a few hundred wide, so `million`
    # rounds 29,843 and 28,000 to the same "30M"; the rate carries three
    # decimals, and `usd_eps` prints $0.678 and $0.670 as $0.68 and $0.67 --
    # in both cases the audit table would show a threshold and a current value
    # that look identical while the headroom bar beside it shows a gap.
    "contracts_k": lambda value: f"{value:,.0f} 千手",
    "usd_rpc": lambda value: f"${value:.3f}",
}


def unit_text(unit: str, value: float) -> str:
    return UNIT_FORMATS[unit](value)


def headroom_exhibit(
    title: str,
    entries: list[dict],
    value_key: str,
    note: str,
    src_extra: str,
) -> dict:
    """Build the diverging-bar exhibit that carries a KPI list.

    ``entries`` are dicts with metric / direction / threshold / unit and either
    an ``actual`` or a ``current`` value, named by ``value_key``.
    """
    labels = []
    values = []
    for entry in entries:
        actual = entry[value_key]
        labels.append(entry["metric"])
        values.append(round(headroom(entry["direction"], entry["threshold"], actual), 1))
    return {
        "kind": "diverging_bars",
        "title": title,
        "xlabels": labels,
        "values": values,
        "legend": "距阈值的余量",
        "positive_label": "仍在安全侧",
        "negative_label": "已越过阈值",
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "距阈值 %",
        "zero_line": True,
        "note": note,
        "src_extra": src_extra,
    }


def threshold_exhibit(
    title: str,
    xlabels: list[str],
    values: list[float | None],
    threshold: float,
    *,
    fmt: str,
    ylab: str,
    actual_name: str,
    threshold_name: str,
    note: str,
    src_extra: str,
) -> dict:
    """Plot one tracked metric against its own threshold line.

    The headroom bar answers "which lines broke"; this answers "how did it get
    there", which is the part a single normalised bar throws away.  Drawing the
    threshold as a flat series keeps the judgement on the chart instead of in
    the caption.
    """
    return {
        "kind": "lines",
        "title": title,
        "xlabels": xlabels,
        "series": [
            {"name": actual_name, "values": values, "color": "NAVY"},
            {"name": threshold_name, "values": [threshold] * len(xlabels), "color": "RED"},
        ],
        "fmt": fmt,
        "yfmt": fmt,
        "label_fmt": fmt,
        "end_label": True,
        "ylab": ylab,
        "note": note,
        "src_extra": src_extra,
    }


def _rounded(values: list[float | None], digits: int = 6) -> list[float | None]:
    """Round for the payload so a rebuild is idempotent, keeping ``None`` holes."""
    return [None if value is None else round(value, digits) for value in values]


def delivery_band(ref: str, metric: str, xlabels: list[str], low: list[float],
                  high: list[float], actual: list[float | None], *, fmt: str, ylab: str,
                  unit: str, src_extra: str, extra_note: str = "",
                  venue: str = "法说会", scope: str = "", point: bool = False,
                  break_at: int | None = None, break_label: str = "",
                  timing: str = "该季<b>开始前</b>", period_word: str = "季") -> dict:
    """One guided metric's own range against what was reported, quarter by quarter.

    Both companies that use this guide several numbers every quarter with the
    same sentence structure, and the interesting part is that the hit rates
    differ sharply *between* the metrics -- so it is one chart per metric, each
    on its own axis, rather than one chart with everything normalised onto a
    shared one. Percent and percentage points do not belong together.

    ``timing`` says when the guidance was published relative to the quarter it
    guides. The default reads "before the quarter began", which is how the first
    pages here described it; Cadence overrides it, because its outlook goes out
    with the *previous* quarter's results and so lands weeks into the quarter
    being guided -- past the halfway mark for a first quarter. A record of never
    missing means something weaker when part of the quarter is already banked,
    so the chart has to say which one it is.
    """
    finished = [index for index, value in enumerate(actual) if value is not None]
    above = [index for index in finished if actual[index] > high[index]]
    below = [index for index in finished if actual[index] < low[index]]
    inside = len(finished) - len(above) - len(below)
    pending = [xlabels[index] for index, value in enumerate(actual) if value is None]
    if point:
        # A point guidance has no bound to clear, so "cleared the upper bound"
        # would be a category error: `lo == hi` and every quarter is trivially
        # outside. The band still draws -- the renderer floors its height at
        # 0.9px -- which is the honest picture of a guidance with no width.
        verdict = (f"{len(finished)} 个已完结{period_word}里 {len(above)} {period_word}高于指引、"
                   f"{len(below)} {period_word}低于指引")
        if inside:
            verdict += f"、{inside} {period_word}与指引完全相同"
    elif below and above:
        verdict = (f"{len(finished)} 个已完结{period_word}里 {len(above)} {period_word}超出上限、"
                   f"{inside} {period_word}落在区间内、{len(below)} {period_word}跌破下限")
    elif below:
        verdict = (f"{len(finished)} 个已完结{period_word}里 {inside} {period_word}落在区间内、"
                   f"{len(below)} {period_word}跌破下限，没有一{period_word}超出上限")
    elif inside == 0:
        verdict = f"{len(finished)} 个已完结{period_word}全部超出指引上限，一次例外都没有"
    else:
        verdict = (f"{len(finished)} 个已完结{period_word}里 {len(above)} {period_word}超出上限、"
                   f"{inside} {period_word}落在区间内，没有一{period_word}跌破下限")
    band = {
        "ref": ref,
        "kind": "range_band",
        # ``scope`` names the drawn window when it is deliberately shorter than
        # the record the page holds, so a reader scanning titles cannot mistake
        # "7 finished quarters" for the length of the history.
        "title": f"{metric}{scope}：{verdict}",
        "xlabels": list(xlabels),
        "xrot": 90,
        "lo": list(low),
        "hi": list(high),
        "actual": list(actual),
        "actual_color": "NAVY",
        "names": {
            "range": f"公司{metric}指引" + ("（单点）" if point else "区间"),
            "actual": f"实际{metric}",
            "lo": f"指引{'值' if point else '下限'}（{unit}）",
            "hi": f"指引{'值' if point else '上限'}（{unit}）",
        },
        "fmt": fmt,
        "label_fmt": fmt,
        "ylab": ylab,
        "note": (
            (f"细横线是{timing}公司在上一场{venue}给出的{metric}指引，"
             "公司给的是单点数而不是区间，所以它在图上没有宽度；"
             "菱形是随后报出来的实际值。"
             if point else
             f"色块是{timing}公司在上一场{venue}给出的{metric}区间，菱形是随后报出来的实际值。")
            + extra_note
            + (f"最后一格 {pending[-1]} 只有指引{'' if point else '色块'}，实际值待披露。"
               if pending else "")
            + "纵轴不自 0 起，但没有任何点被截掉。"
        ),
        "src_extra": src_extra,
    }
    if pending:
        band["annot"] = f"{pending[-1]}：仅指引，实际值待披露"
    # Structural break (规矩 6): the series is not comparable across this index,
    # so the chart says so rather than drawing one continuous line over a
    # definition change.
    if break_at is not None:
        band["break_at"] = break_at
        band["break_label"] = break_label
    return band


def midpoint_deviation(ref: str, metric: str, xlabels: list[str], low: list[float],
                       high: list[float], actual: list[float | None], *, mode: str,
                       src_extra: str, extra_note: str = "", window: int = 14,
                       label: Callable[[str], str] | None = None,
                       bar_labels: bool = True, axis_note: str = "",
                       period_word: str = "季") -> dict:
    """How far past the guided midpoint the quarter landed, for one guided metric.

    The band charts answer "did it clear the range at all", which saturates once
    a metric has cleared the same bound many times running: the band then says
    the same thing every quarter. This asks the question that still has an
    answer -- by how much, and is that widening or narrowing.

    Two modes because the units genuinely differ. A level guided in dollars has
    an honest relative distance (%). A ratio's distance is the arithmetic gap
    (pp): dividing a percentage by a percentage would print a number nobody
    quotes and that no company reports.

    ``period_word`` names the unit each bar stands for, matching the parameter
    of the same name on `delivery_band`. It is a quarter on every page whose
    guidance is quarterly; S&P Global guides only the full year, so its bars are
    fiscal years and a hardcoded 「季」 would have counted seven years as seven
    quarters in the chart's own title.
    """
    if mode not in ("pct", "pp"):
        raise ValueError(f"unknown mode {mode!r}")
    finished = [
        index for index, value in enumerate(actual) if value is not None
    ][-window:]
    midpoints = [(low[index] + high[index]) / 2 for index in finished]
    deviation = [
        (actual[index] / mid - 1) * 100 if mode == "pct" else actual[index] - mid
        for index, mid in zip(finished, midpoints)
    ]
    unit = "%" if mode == "pct" else "pp"
    above = sum(1 for value in deviation if value > 0)
    mean_absolute = statistics.fmean(abs(value) for value in deviation)
    biggest = max(deviation, key=abs)
    render = label or (lambda text: text)
    return {
        "ref": ref,
        "kind": "grouped_bars",
        "title": (
            f"{metric}相对指引中值的偏离：{len(deviation)} {period_word}里 {above} "
            f"{period_word}为正，平均绝对偏离 {mean_absolute:.1f}{unit}"
        ),
        "xlabels": [render(xlabels[index]) for index in finished],
        "xrot": 90,
        "groups": [{
            "name": f"实际{metric} vs 指引中值",
            "color": "BLUE",
            "values": _rounded(deviation),
        }],
        "bar_labels": bar_labels,
        "fmt": "pct1" if mode == "pct" else "pp1",
        "label_fmt": "pct1" if mode == "pct" else "pp1",
        "ylab": f"{unit} vs 指引中值",
        "note": (
            f"正值 = 高于指引区间的中值；长期为正说明公司指引偏保守，不是一连串意外。"
            + axis_note
            + f"窗口内最大的一次是 {render(xlabels[finished[deviation.index(biggest)]])} "
            f"的 {biggest:+.1f}{unit}。"
            + (
                "本图单位是<b>百分点</b>，与收入那张的<b>百分比</b>不可直接比大小 —— "
                "率的偏离取算术差，除一次只会得到一个没人引用的数。"
                if mode == "pp" else ""
            )
            + extra_note
        ),
        "src_extra": src_extra,
    }


def number_exhibits(exhibits: list[dict], start: int = 2) -> list[dict]:
    """Assign exhibit numbers in render order.

    Hand-numbering breaks the moment a chart is inserted, and a page whose
    Exhibit 7 is captioned "see Exhibit 6" is worse than no caption.
    """
    for offset, exhibit in enumerate(exhibits):
        exhibit["n"] = start + offset
    return exhibits


def threshold_table(n: int, title: str, entries: list[dict], value_key: str,
                    value_head: str) -> dict:
    """Return the audit table behind a headroom exhibit, in original units."""
    rows = []
    for entry in entries:
        rows.append([
            entry["metric"],
            "高于阈值为安全" if entry["direction"] == "up" else "低于阈值为安全",
            unit_text(entry["unit"], entry["threshold"]),
            unit_text(entry["unit"], entry[value_key]),
            f"{headroom(entry['direction'], entry['threshold'], entry[value_key]):+.1f}%",
        ])
    return {
        "n": n,
        "title": title,
        "headers": ["指标", "方向", "阈值", value_head, "余量 D"],
        "rows": rows,
    }


SERIES_DIR = Path(__file__).resolve().parents[1] / "series"

# One accessor per company: (series file, period list, cash-capex list).  Only
# cash purchases of property and equipment are collected, because that is the
# one capex definition every filer here reports identically -- META's headline
# number adds finance-lease principal, MSFT's adds finance-lease additions, and
# AMZN's own free-cash-flow definition nets off proceeds from equipment sales
# and incentives, so the company-defined totals are not addable across pages.
#
# AMZN joined this table when its page was built. Leaving the largest capex
# spender of the four out of a table whose whole point is the size of the wave
# would have understated every row by roughly a third.
_CASH_CAPEX_SOURCES = [
    ("amzn", "AMZN", lambda d: (d["periods"], d["quarterly_usd_m"]["purchases_of_property_and_equipment"])),
    ("googl", "GOOGL", lambda d: (d["quarterly"]["periods"], d["quarterly"]["capital_expenditures"])),
    ("meta", "META", lambda d: (d["periods"], d["quarterly_usd_m"]["purchases_of_property_and_equipment"])),
    ("msft", "MSFT", lambda d: (d["periods"], d["quarterly_usd_m"]["cash_paid_for_property_and_equipment"])),
]


def _load(slug: str) -> dict:
    return json.loads((SERIES_DIR / f"{slug}.json").read_text(encoding="utf-8"))


def ai_capex_cycle_table(n: int) -> dict:
    """Return the upstream-capex / downstream-shipment cross reference.

    Published byte-identically on every company page: four hyperscalers'
    quarterly cash capex, the accelerator revenue it lands in, and the foundry
    quarter that has to build it. Each page can answer "did my company spend
    more"; only this table answers "did the spending turn into shipments".

    NVIDIA sits between the two ends rather than at one of them, so it gets the
    Data Center line specifically -- Edge Computing is not what a hyperscaler's
    capex buys. Its quarters end about four weeks after the calendar ones the
    rest of the table uses (late April against 31 March), which the column
    header states, because a reader comparing a row across cannot see it
    otherwise. The offset is left in rather than interpolated away: shifting a
    reported quarter onto someone else's calendar would invent a number.
    """
    tsm = _load("tsm")
    periods = tsm["periods"]
    by_company = []
    for slug, _label, accessor in _CASH_CAPEX_SOURCES:
        company_periods, capex = accessor(_load(slug))
        by_company.append(dict(zip(company_periods, capex)))
    nvda = _load("nvda")
    data_center = dict(zip(nvda["periods"], nvda["market_platform_usd_m"]["data_center"]))

    rows = []
    for index, period in enumerate(periods):
        values = [company.get(period) for company in by_company]
        total = sum(value for value in values if value is not None)
        revenue = tsm["financials"]["revenue_usd_bn"][index]
        accelerator = data_center.get(period)
        rows.append(
            [period]
            + [f"${value:,.0f}M" if value is not None else "—" for value in values]
            + [
                f"${total:,.0f}M D",
                f"US${accelerator / 1000:.2f}B" if accelerator is not None else "—",
                f"US${revenue:.2f}B",
                f"{tsm['financials']['revenue_yoy_pct'][index]:.1f}%",
            ]
        )
    return {
        "n": n,
        "title": "AI capex 循环：四家云厂现金 CapEx → NVDA 数据中心 → TSM 晶圆（跨页对照）",
        "headers": [
            "期间",
            "AMZN 现金 CapEx",
            "GOOGL 现金 CapEx",
            "META 现金 CapEx",
            "MSFT 现金 CapEx",
            "四家合计 D",
            "NVDA DC 收入（季末晚约 1 个月）",
            "TSM 收入",
            "TSM 收入 YoY",
        ],
        "rows": rows,
    }
