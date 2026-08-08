"""Shared building blocks for the two-layer company page.

Layer 1 (``panel``) is the stable quarterly operating panel: fixed fields, same
rows every quarter, so eight-quarter trends stay comparable.  Layer 2 (``board``)
is the tracking board: a small set of metrics carrying an explicit threshold and
a trigger action, refreshed as the thesis moves.

Thresholds are local research settings, not company guidance.  Every current
value on the board must be reproducible from the published series or from an
arithmetic derivation shown in the same row.
"""

from __future__ import annotations


STATUS_LABELS = {
    "ok": "正常",
    "watch": "接近阈值",
    "hit": "已触发",
    "pending": "待验证",
    "na": "待接入",
}

BOARD_HEADS = ["当前值", "阈值", "触发动作", "状态"]


def board_row(metric: str, current: str, threshold: str, action: str, status: str) -> dict:
    """Return one tracking-board row.

    ``status`` drives only the colour chip; the threshold text next to it is the
    actual rule, so a reader can disagree with the light and still audit the
    number.
    """
    if status not in STATUS_LABELS:
        raise ValueError(f"unknown board status: {status}")
    return {
        "label": metric,
        "cells": [
            {"v": current, "cls": "cur", "status": "reported"},
            {"v": threshold, "cls": "thr", "status": "reported"},
            {"v": action, "cls": "act", "status": "reported"},
            {"v": STATUS_LABELS[status], "cls": f"st st-{status}", "status": "reported"},
        ],
    }


def board_block(rows: list[dict], note: str) -> dict:
    return {
        "id": "tracking",
        "title": "跟踪盘：本季重点指标的阈值与触发动作",
        "frequency": "quarterly",
        "heads": BOARD_HEADS,
        "sep": 3,
        "rows": rows,
        "note": note,
    }


def panel_row(label: str, values: list[str], derived: bool | list[bool] = False) -> dict:
    """Return one operating-panel row.

    ``derived`` may be a single flag for the whole row or a per-cell list, so a
    row can mix reported values with a self-computed ratio column.
    """
    flags = derived if isinstance(derived, list) else [derived] * len(values)
    if len(flags) != len(values):
        raise ValueError("derived flags must match the value count")
    return {
        "label": label,
        "cells": [
            {
                "v": value if value not in (None, "") else "—",
                "cls": "cur" if index == 0 else "",
                "status": "derived" if flag and value not in (None, "", "—") else "reported",
            }
            for index, (value, flag) in enumerate(zip(values, flags))
        ],
    }


def panel_group(
    group_id: str,
    title: str,
    heads: list[str],
    rows: list[dict],
    note: str,
    open_by_default: bool = False,
    sep: int | None = None,
) -> dict:
    group = {
        "id": group_id,
        "title": title,
        "heads": heads,
        "rows": rows,
        "note": note,
        "open": open_by_default,
    }
    if sep is not None:
        group["sep"] = sep
    return group


def ai_capex_cycle_table(n: int, googl_capex: dict, tsm_series: dict) -> dict:
    """Return the shared upstream-capex / downstream-shipment cross reference.

    ``googl_capex`` maps a quarter label to ``(capex_usd_m, capex_intensity)``.
    Only quarters present on both sides are shown; the two columns keep their own
    currencies and must not be added together.
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
