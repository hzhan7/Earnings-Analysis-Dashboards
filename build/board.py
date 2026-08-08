"""Shared pieces for the chart-led company pages.

The page exists to be scanned, not read, so anything that would otherwise be a
wall of thresholds is turned into one chart: `headroom_exhibit` normalises a
mixed-unit KPI list into a single "distance from the threshold" number, so a
reader sees which lines are breached without parsing units.

`ai_capex_cycle_table` is the one cross-company object both pages publish.
"""

from __future__ import annotations


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
}


def unit_text(unit: str, value: float) -> str:
    return UNIT_FORMATS[unit](value)


def headroom_exhibit(
    n: int,
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
        "n": n,
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


def ai_capex_cycle_table(n: int, googl_capex: dict, tsm_series: dict) -> dict:
    """Return the shared upstream-capex / downstream-shipment cross reference.

    ``googl_capex`` maps a quarter label to ``(capex_usd_m, capex_intensity)``.
    The two sides keep their own currencies and must not be added together.
    """
    rows = []
    for index, period in enumerate(tsm_series["periods"]):
        capex = googl_capex.get(period)
        revenue = tsm_series["financials"]["revenue_usd_bn"][index]
        rows.append([
            period,
            f"${capex[0]:,.0f}M" if capex else "—",
            capex[1] if capex else "—",
            f"US${revenue:.2f}B",
            f"{tsm_series['financials']['revenue_yoy_pct'][index]:.1f}%",
            f"NT${tsm_series['cash_flow_ntd_bn']['capital_expenditures'][index]:,.2f}B",
        ])
    return {
        "n": n,
        "title": "AI capex 循环：上游投入承诺与下游出货（跨页对照）",
        "headers": [
            "期间",
            "GOOGL CapEx",
            "GOOGL CapEx/收入",
            "TSM 收入",
            "TSM 收入 YoY",
            "TSM CapEx",
        ],
        "rows": rows,
    }
