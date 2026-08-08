"""Shared pieces for the chart-led company pages.

The page exists to be scanned, not read, so anything that would otherwise be a
wall of thresholds is turned into one chart: `headroom_exhibit` normalises a
mixed-unit KPI list into a single "distance from the threshold" number, so a
reader sees which lines are breached without parsing units.

`ai_capex_cycle_table` is the one cross-company object both pages publish.
"""

from __future__ import annotations

import json
from pathlib import Path


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


UNIT_FORMATS = {
    "pct": lambda value: f"{value:.1f}%",
    "pp": lambda value: f"{value:+.1f}pp",
    "usd_m": lambda value: f"${value:,.0f}M",
    "usd_bn": lambda value: f"US${value:.1f}B",
    "days": lambda value: f"{value:.0f}天",
    "fx": lambda value: f"{value:.2f}",
    "million": lambda value: f"{value:.0f}M",
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
# one capex definition all four filers report identically -- META's headline
# number adds finance-lease principal and MSFT's adds finance-lease additions,
# so the company-defined totals are not addable across pages.
_CASH_CAPEX_SOURCES = [
    ("googl", "GOOGL", lambda d: (d["quarterly"]["periods"], d["quarterly"]["capital_expenditures"])),
    ("meta", "META", lambda d: (d["periods"], d["quarterly_usd_m"]["purchases_of_property_and_equipment"])),
    ("msft", "MSFT", lambda d: (d["periods"], d["quarterly_usd_m"]["cash_paid_for_property_and_equipment"])),
]


def _load(slug: str) -> dict:
    return json.loads((SERIES_DIR / f"{slug}.json").read_text(encoding="utf-8"))


def ai_capex_cycle_table(n: int) -> dict:
    """Return the upstream-capex / downstream-shipment cross reference.

    Published byte-identically on every company page: three hyperscalers'
    quarterly cash capex against the foundry quarter that has to build it.
    Each page can answer "did my company spend more"; only this table answers
    "did the spending turn into shipments".
    """
    tsm = _load("tsm")
    periods = tsm["periods"]
    by_company = []
    for slug, _label, accessor in _CASH_CAPEX_SOURCES:
        company_periods, capex = accessor(_load(slug))
        by_company.append(dict(zip(company_periods, capex)))

    rows = []
    for index, period in enumerate(periods):
        values = [company.get(period) for company in by_company]
        total = sum(value for value in values if value is not None)
        revenue = tsm["financials"]["revenue_usd_bn"][index]
        rows.append(
            [period]
            + [f"${value:,.0f}M" if value is not None else "—" for value in values]
            + [
                f"${total:,.0f}M D",
                f"US${revenue:.2f}B",
                f"{tsm['financials']['revenue_yoy_pct'][index]:.1f}%",
            ]
        )
    return {
        "n": n,
        "title": "AI capex 循环：上游投入承诺与下游出货（跨页对照）",
        "headers": [
            "期间",
            "GOOGL 现金 CapEx",
            "META 现金 CapEx",
            "MSFT 现金 CapEx",
            "三家合计 D",
            "TSM 收入",
            "TSM 收入 YoY",
        ],
        "rows": rows,
    }
