#!/usr/bin/env python3
"""Build the GOOGL quarterly-results page.

The page is meant to be scanned, not read: it replaces the slide deck that used
to accompany the local earnings note, so almost everything is a chart with one
or two sentences under it.  Charts are ordered the way the note is used --

    1. 上季兑现   did last quarter's tracked lines hold?
    2. 本季重点   what actually moved this quarter
    3. 下季跟踪   what to watch next
    4. 长期常规   the routine multi-quarter series for this specific company

-- and the tables that back them stay collapsed in the audit drawer.

Published numbers are company-reported or transparent arithmetic.  Market
expectations are labelled as such, with no broker attribution.  Ratings, target
prices and valuation stay off the page.

Rolling the page to a new quarter edits `series/googl.json` and nothing else.
Every figure, period label, count and record claim on the page is computed from
the series here; a sentence that says "the only time", "a new high" or "has
never been crossed" is printed only while the series makes it true, and a
different, true sentence is printed otherwise.  What belongs to one quarter
only -- the thresholds and their settlement, the market expectation, the
quarter's snapshot inputs, the call's reading of backlog -- lives in blocks
stamped with that quarter (`board.stamped_block`): a block stamped with another
quarter stops the build, a missing one leaves its part of the page out.

Fixed history stays in the code because a roll cannot change it: the 2018Q4
line-disclosure floor and the 2022Q1 cost-allocation recast are read from the
series' own first quarters, but the 2023 caption change of the depreciation
line, the 2023 start of the AI build-out used to split the capital-intensity
record, the FY2019 first RPO disclosure, the Q1 2026 TPU inclusion in backlog
and the US$1M Q4 2025 revenue difference are facts about filings already made.
"""

from __future__ import annotations

import datetime
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
    stamped_block,
    unit_text,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "googl.json"
DATA_DIR = ROOT / "data"

AUDIT_WORDS = {"unaudited": "未审计", "audited": "已审计"}

# The AI build-out that the capital-intensity chart splits its record at. It is
# a fact about the past, not a parameter of the quarter.
BUILD_OUT_FROM = "2023Q1"

# A stretch of consecutive year-on-year accelerations counts as an episode on
# the revenue chart once it is this long; one- and two-quarter wiggles do not.
ACCELERATION_EPISODE = 3

# The first quarter the owner's local analysis covered (the vault's
# `2026-03-05 GOOGL Q4 2025 vs Q3 2025 Analysis.md`). Every later quarter has a
# previous analysis whose follow-up list and section 8 section one settles.
FIRST_REPORT_PERIOD = "Q4 2025"

# The four sections every company page carries, in order (owner, 2026-09-23;
# TSM is the reference page).
SECTIONS = (
    ("settled", "一、上季跟踪指标兑现了吗"),
    ("quarter_highlights", "二、本季重点"),
    ("next_quarter", "三、下季要跟踪什么"),
    ("routine", "四、长期常规跟踪"),
)


def parse_number(value: str) -> float | None:
    """Parse the compact financial-number strings used by the GOOGL source table."""
    text = re.sub(r"<[^>]+>", "", value).strip()
    if not text or re.fullmatch(r"—+|-+|NM|N/?A|不适用|未披露|n\.m\.", text, re.I):
        return None
    if re.search(r"\d\s*[-–—~]\s*\d", text):
        return None
    text = re.sub(r"\[[^]]*\]", "", text)
    negative = bool(
        re.search(r"\(\s*[$€£¥]?[\d,.]+\s*[A-Za-z]{0,3}\s*\)", text)
        or re.search(r"(?:^|[^A-Za-z0-9_])-\s*[$€£¥]?\s*\d", text)
    )
    match = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", text)
    if not match:
        return None
    parsed = float(match.group(0).replace(",", ""))
    return -abs(parsed) if negative else parsed


def number(value: str | None) -> float | None:
    return parse_number(value or "")


def change(current: float | None, base: float | None, digits: int = 1) -> str:
    if current is None or base in (None, 0):
        return "—"
    return f"{(current / base - 1) * 100:+.{digits}f}%"


def source_note(detail: str) -> str:
    return f"{detail}；历史期同口径。自算项目均可在表格视图核对。"


def cross_capex_table(n: int) -> dict:
    """Return the shared AI-capex cross reference used by every company page."""
    return ai_capex_cycle_table(n)


WINDOW = 8


def yoy(values: list[float | None]) -> list[float | None]:
    """Year-over-year in percent, None until a year-ago quarter exists.

    A hole in the input has to become a hole in the output, not an exception and
    not a skipped quarter: several of the long series here start mid-record
    (quarterly depreciation only exists from 2023Q1), and the year-on-year line
    for those has to be missing exactly where its own base is missing.
    """
    out: list[float | None] = [None] * 4
    for index in range(4, len(values)):
        current, base = values[index], values[index - 4]
        out.append(None if current is None or base is None or base == 0
                   else (current / base - 1) * 100)
    return out


def trailing(values: list[float | None]) -> list[float | None]:
    """Rolling four-quarter sum, None until four complete quarters exist."""
    out: list[float | None] = [None] * 3
    for index in range(3, len(values)):
        window = values[index - 3:index + 1]
        out.append(None if any(value is None for value in window) else sum(window))
    return out


def shown(values: list) -> list:
    return values[-WINDOW:]


def quarter_label(quarter: str) -> str:
    """``'2016Q1'`` → ``'Q1'16'``, matching the eight-quarter labels."""
    year, number = quarter.split("Q")
    return f"Q{number}'{year[-2:]}"


def quarter_key(period: str) -> str:
    """``'Q2 2026'`` → ``'2026Q2'``, the key the long records use."""
    quarter, year = period.split()
    return f"{year}{quarter}"


def next_period(period: str) -> str:
    """``'Q2 2026'`` → ``'Q3 2026'``; ``'Q4 2026'`` → ``'Q1 2027'``."""
    quarter, year = period.split()
    number = int(quarter[1])
    return f"Q1 {int(year) + 1}" if number == 4 else f"Q{number + 1} {year}"


def leading_gap(values: list[float | None]) -> int:
    """Index of the first reported value; ``len(values)`` when there is none."""
    return next((i for i, value in enumerate(values) if value is not None), len(values))


def spaced(name: str) -> str:
    """A Latin name inside Chinese prose gets a space in front: 「落后于 APAC」, 「落后于其他美洲」."""
    return f" {name}" if name[:1].isascii() else name


def money_bn(value: float) -> str:
    """US$M → ``'-$5.9B'``, the sign ahead of the currency as the headline writes it."""
    return f"{'-' if value < 0 else ''}${abs(value) / 1000:.1f}B"


def money_m(value: float) -> str:
    return f"{'-' if value < 0 else ''}${abs(value):,.0f}M"


def rising_streak(values: list[float | None], digits: int) -> int:
    """How many consecutive quarters, ending with the last, rose at printed precision.

    Two quarters that print the same number did not rise: Cloud's operating
    margin printed 9.40% in both 2023Q4 and 2024Q1, and a streak that counted a
    0.001pp step would claim a rise no reader can see on the page.
    """
    streak = 0
    for index in range(len(values) - 1, 0, -1):
        current, previous = values[index], values[index - 1]
        if current is None or previous is None or round(current, digits) <= round(previous, digits):
            break
        streak += 1
    return streak


def runs(values: list[float | None], test) -> list[tuple[int, int]]:
    """Maximal stretches (first, last index) where ``test(value)`` holds."""
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


def span_text(quarters: list[str], first: int, last: int) -> str:
    return quarters[first] if first == last else f"{quarters[first]}–{quarters[last]}"


def ranges_text(quarters: list[str], indices: list[int]) -> str:
    """``[27, 32, 33, 34]`` → ``'2022Q4、2024Q1–2024Q3'``: consecutive quarters collapse."""
    groups: list[list[int]] = []
    for index in indices:
        if groups and index == groups[-1][-1] + 1:
            groups[-1].append(index)
        else:
            groups.append([index])
    return "、".join(span_text(quarters, group[0], group[-1]) for group in groups)


# One x label per year: forty-two quarterly labels at 90 degrees turn the axis
# into a hairbrush, and this axis is only ever navigated by year.
LONG_STEP = 4


# ── Thresholds ───────────────────────────────────────────────────────────────
# A threshold in the series names the record it is read against (`reads`),
# never its reading: this quarter's value is the end of that record at build
# time, so a roll cannot leave last quarter's number under this quarter's line
# and the previous quarter's `next_kpi` becomes this quarter's settlement
# unchanged (TSM is the reference). The local analysis often writes two or three
# lines into one row ("<+55% 警示；<+45% 减仓"); each is its own entry with its
# own `tier`, so every line is settled and drawn, not only the first one.

TIER_COLORS = ("RED", "GOLD", "GRAY")


def unsafe(entry: dict, value: float) -> bool:
    """On the wrong side of the entry's line -- a line at zero included, which
    `board.headroom` cannot express as a percentage."""
    if entry["direction"] == "up":
        return value < entry["threshold"]
    return value > entry["threshold"]


def unsafe_run(entry: dict, values: list) -> int:
    """How many readings in a row, ending with this quarter's, sit on the wrong side."""
    run = 0
    for value in reversed(values):
        if value is None or not unsafe(entry, value):
            break
        run += 1
    return run


def line_state(entry: dict, values: list) -> str:
    """「守住」, 「击穿」, or 「越线」 when the row asks for consecutive quarters and
    this is not yet enough of them to trigger."""
    run = unsafe_run(entry, values)
    if run == 0:
        return "守住"
    return "击穿" if run >= entry.get("consecutive", 1) else "越线"


def by_reads(entries: list[dict]) -> list[list[dict]]:
    """The tiers of one record together, in the order the analysis wrote them."""
    groups: dict[str, list[dict]] = {}
    for entry in entries:
        groups.setdefault(entry["reads"], []).append(entry)
    return list(groups.values())


def is_band(group: list[dict]) -> bool:
    """Two lines on one record facing each other: 「<$42,000M 或 >$55,000M 均需重估」."""
    return len(group) == 2 and {entry["direction"] for entry in group} == {"up", "down"}


def tier_label(entry: dict) -> str:
    return f"{entry['metric']}（{entry['tier']}）"


def tier_line(entry: dict) -> str:
    """``'警示线 55.0%'``; a tier ending in a Latin letter or digit keeps a space: ``'需解释 Wiz 线 30.0%'``."""
    tier = entry["tier"]
    return f"{tier}{' ' if tier[-1:].isascii() else ''}线 {unit_text(entry['unit'], entry['threshold'])}"


def tier_chart(title: str, xlabels: list[str], values: list, group: list[dict], spec: dict, *,
               line_word: str, note: str, src_extra: str) -> dict:
    """One record against every line the analysis drew on it, each line its own series."""
    series = [{"name": spec["name"], "values": values, "color": "NAVY"}]
    for color, entry in zip(TIER_COLORS, group):
        side = "上方" if entry["direction"] == "up" else "下方"
        series.append({"name": f"{line_word}{spaced(tier_line(entry))}（安全侧在{side}）",
                       "values": [entry["threshold"]] * len(xlabels), "color": color})
    chart = {"kind": "lines", "title": title, "xlabels": xlabels, "series": series,
             "fmt": spec["fmt"], "yfmt": spec["fmt"], "label_fmt": spec["fmt"], "end_label": True,
             "ylab": spec["ylab"], "note": note, "src_extra": src_extra}
    if len(xlabels) > 16:
        chart["xstep"] = LONG_STEP
    return chart


def record_words(group: list[dict], values: list, per: str) -> str:
    """How often this record has sat on the wrong side of each line, on its own full window."""
    reported = [value for value in values if value is not None]
    parts = []
    for entry in group:
        line = tier_line(entry)
        crossed = sum(1 for value in reported if unsafe(entry, value))
        recent = sum(1 for value in reported[-WINDOW:] if unsafe(entry, value))
        parts.append(f"{line} 的不安全一侧有 {crossed} 个（最近八季 {recent} 个）" if crossed
                     else f"{line} 一次都没越过")
    return f"这条线自己的记录有 {len(reported)} 个{per}：" + "；".join(parts) + "。"


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    q = staging["quarterly"]
    cloud = q["cloud"]
    fcf = q["operating_cash_flow"][-1] - q["capital_expenditures"][-1]
    return [f"Revenue ${q['revenue_total'][-1] / 1000:.1f}B",
            f"Cloud {(cloud[-1] / cloud[-5] - 1) * 100:+.1f}%",
            f"FCF {'-' if fcf < 0 else ''}${abs(fcf) / 1000:.1f}B"]


def source_for(staging: dict, label: str) -> dict:
    """The series' `sources` entry for one label, or a roll error naming it."""
    item = next((entry for entry in staging["sources"] if entry["label"] == label), None)
    if item is None:
        raise ValueError(f"series `sources` has no {label!r}: add this quarter's release "
                         "and call webcast with the roll")
    return item


# ── the snapshot table ───────────────────────────────────────────────────────

def snapshot_cells(kind: str, values: list, *, prior: float | None = None) -> list[str]:
    """Three period cells and the QoQ / YoY cells for one snapshot row.

    ``values`` is (a year ago, last quarter, this quarter). The change columns
    are computed from those three, never typed: the typed versions of this table
    had put a quarter-on-quarter change in the year-on-year column and carried a
    year-on-year figure from the wrong base.
    """
    def fmt(value):
        if value is None:
            return "—"
        if kind == "margin":
            return f"{value:.2f}%"
        if kind == "growth_pct":
            return f"{value:+d}%"
        if kind == "eps":
            return f"${value:.2f}"
        if kind == "eps_less":
            return f"~${value:.2f}"
        if kind == "count":
            return f"{value:,}"
        if kind == "backlog":
            return f"${value * 1000:,.0f}M"
        return money_m(value)

    def moved(current, base):
        if current is None or base is None:
            return "—"
        if kind == "no_change":
            return "—"
        if kind == "margin":
            return f"{current - base:+.2f}pp"
        if kind == "growth_pct":
            return f"{current - base:+d}pp"
        if kind in ("loss", "difference"):
            delta = current - base
            text = f"{'-' if delta < 0 else '+'}${abs(delta):,.0f}M"
            if kind == "loss" and current < 0 and base < 0:
                text += "（亏损收窄）" if delta > 0 else "（亏损扩大）"
            return text
        if kind == "free_cash_flow":
            if current < 0 <= base:
                return "转负"
            if base < 0 <= current:
                return "转正"
        if kind == "buyback":
            if base == 0:
                return "—"
            if current == 0:
                return "-100%"
        return change(current, base)

    year_ago, previous, current = values
    return [fmt(year_ago), fmt(previous), fmt(current),
            moved(current, previous), moved(current, year_ago)]


def build_payload(staging: dict) -> dict:
    q = staging["quarterly"]
    periods = q["periods"]
    period = periods[-1]
    quarter_word = period.split()[0]
    latest = latest_block(staging, period=period)
    source_for(staging, f"{period} SEC Exhibit 99.1")
    source_for(staging, f"{period} Alphabet earnings call webcast")

    closure = stamped_block(staging, "followup_closure", period)
    prior_kpi = stamped_block(staging, "prior_kpi_settlement", period)
    next_kpi = stamped_block(staging, "next_kpi", period)
    snapshot = stamped_block(staging, "snapshot", period)
    # The page has four sections every quarter. Section one settles what the
    # previous local analysis left and section three carries this analysis's
    # section 8; the site has analysed Alphabet since FIRST_REPORT_PERIOD, so
    # every quarter the page can be rolled to has both, and a roll that forgot
    # one would otherwise publish a page with a section quietly missing. The
    # snapshot is the quarter's reading of the release beside the series, and
    # several of those thresholds are read off it.
    for key, block in (("followup_closure", closure), ("prior_kpi_settlement", prior_kpi),
                       ("next_kpi", next_kpi), ("snapshot", snapshot)):
        if block is None:
            raise ValueError(f"series block `{key}` is required every quarter: the local analysis "
                             f"has covered Alphabet since {FIRST_REPORT_PERIOD}, so {period} has "
                             "a previous analysis to settle and a section 8 to track")
    for key, block in (("followup_closure", closure), ("prior_kpi_settlement", prior_kpi)):
        if block["set_in"] != periods[-2]:
            raise ValueError(f"series block `{key}` settles what {block['set_in']!r} left, but the "
                             f"quarter before {period} is {periods[-2]!r}")
    if next_kpi["for_period"] != next_period(period):
        raise ValueError(f"series block `next_kpi` tracks {next_kpi['for_period']!r}, but the quarter "
                         f"after {period} is {next_period(period)!r}")
    consensus = stamped_block(staging, "market_expectation", period)
    story = stamped_block(staging, "quarter_story", period) or {}
    errata = stamped_block(staging, "local_note_errata", period)

    revenue_values = shown(q["revenue_total"])
    revenue_yoy = shown(yoy(q["revenue_total"]))
    capex_values = shown(q["capital_expenditures"])
    dep_values = shown(q["depreciation"])
    dep_yoy = shown(yoy(q["depreciation"]))

    # ── The routine charts run on the ten-year record, not the eight ─────────
    # Eight quarters cannot tell a trend from a wobble, and for capital
    # intensity eight quarters is barely one build cycle.  Everything below is
    # a filed number or the difference of two filed numbers; the quarterly
    # cash-flow lines exist only year-to-date in a 10-Q, so every quarter after
    # the first is one year-to-date figure minus the previous one.  See
    # long_history.provenance.
    long = staging["long_history"]
    quarters = long["quarters"]
    if quarters[-1] != quarter_key(period):
        raise ValueError(f"long_history ends at {quarters[-1]} but the page is {period}")
    long_labels = [quarter_label(quarter) for quarter in quarters]
    long_revenue = long["revenue_usd_m"]
    long_capex = long["capital_expenditures_usd_m"]
    years = len(quarters) // 4
    # Four 2015 quarters exist only as the denominator for 2016's year-on-year
    # line; without them that line starts a year into a ten-year chart.
    base_2015 = staging["prior_year_base_2015"]["revenue_usd_m"]
    long_revenue_yoy = yoy(base_2015 + long_revenue)[len(base_2015):]
    long_intensity = [
        capex / total * 100 for capex, total in zip(long_capex, long_revenue)
    ]
    # y/y needs four quarters of run-up, so these two start a year in rather
    # than drawing four empty slots on the left.
    long_geography = long["geography_usd_m"]
    yoy_from = leading_gap(long_revenue_yoy)
    long_geography_yoy = {
        region: yoy(values)[yoy_from:]
        for region, values in long_geography.items()
    }

    # ── The 2016-onward record for the metrics that have one ────────────────
    # Three different floors, and each one is a disclosure floor rather than a
    # choice, so they are kept apart instead of being padded to a common start:
    #   * revenue / capex / operating cash flow / geography -- the long record
    #   * the revenue lines (Search, YouTube, Cloud ...) -- from 2018Q4, because
    #     Alphabet did not publish this breakdown before the 2018Q4 release
    #   * Cloud operating margin -- from 2022Q1, because the current cost
    #     allocation was only recast back to 2022Q1
    lines = staging["revenue_lines_usd_m"]
    line_quarters = lines["quarters"]
    line_labels = [quarter_label(quarter) for quarter in line_quarters]
    long_cloud = lines["google_cloud"]
    long_cloud_yoy = yoy(long_cloud)
    long_search_yoy = yoy(lines["search_and_other"])
    long_youtube_yoy = yoy(lines["youtube_ads"])
    long_network_yoy = yoy(lines["google_network"])

    seg = staging["segment_operating_income_usd_m"]
    balance = staging["balance_sheet_usd_m"]
    for name, keys in (("revenue_lines_usd_m", line_quarters), ("segment_operating_income_usd_m", seg["quarters"]),
                       ("balance_sheet_usd_m", balance["quarters"])):
        if keys[-1] != quarter_key(period):
            raise ValueError(f"series block `{name}` ends at {keys[-1]} but the page is {period}")
    seg_at = {quarter: index for index, quarter in enumerate(seg["quarters"])}
    long_cloud_opm = [
        None if quarter not in seg_at
        else seg["oi_google_cloud"][seg_at[quarter]] / long_cloud[index] * 100
        for index, quarter in enumerate(line_quarters)
    ]
    cloud_yoy_now = long_cloud_yoy[-1]
    cloud_opm_now = long_cloud_opm[-1]
    search_yoy_now = long_search_yoy[-1]
    search_step = long_search_yoy[-1] - long_search_yoy[-2]

    long_ocf = long["operating_cash_flow_usd_m"]
    long_fcf = [operating - capex
                for operating, capex in zip(long_ocf, long_capex)]
    long_ttm_fcf = trailing(long_fcf)
    negative_fcf = sum(1 for value in long_fcf if value < 0)
    long_dep = long["depreciation_usd_m"]
    long_dep_yoy = yoy(long_dep)

    captions = staging["depreciation_two_captions"]
    def on_long_axis(block: dict) -> list[float | None]:
        at = dict(zip(block["quarters"], block["values"]))
        return [at.get(quarter) for quarter in quarters]
    dep_prior_caption = on_long_axis(captions["prior_caption"])
    dep_current_caption = on_long_axis(captions["current_caption"])
    dep_prior_yoy = yoy(dep_prior_caption)
    dep_current_yoy = yoy(dep_current_caption)

    ttm_fcf_cur = long_ttm_fcf[-1]

    capex_guide = staging["capex_guidance_history"]
    backlog = staging["backlog"]
    backlog_levels = backlog["level_usd_bn"]
    backlog_quarters = backlog["quarters"]
    backlog_labels = [quarter_label(quarter) for quarter in backlog_quarters]
    backlog_qoq = [None] + [
        (current / previous - 1) * 100
        for previous, current in zip(backlog_levels, backlog_levels[1:])
    ]
    backlog_net_add = [None] + [
        current - previous
        for previous, current in zip(backlog_levels, backlog_levels[1:])
    ]
    if backlog_quarters[-1] != quarter_key(period):
        raise ValueError(f"backlog ends at {backlog_quarters[-1]} but the page is {period}")

    # Every quarter-keyed series the snapshot table can name, so a row reads the
    # same number the charts draw instead of carrying its own copy.
    by_quarter: dict[str, dict[str, float | None]] = {}
    def keyed(name: str, keys: list[str], values: list) -> None:
        by_quarter[name] = dict(zip(keys, values))
    keyed("revenue", quarters, long_revenue)
    for name in ("google_services", "search_and_other", "youtube_ads", "google_network",
                 "google_subscriptions_platforms_devices", "google_cloud", "other_bets"):
        keyed(name, line_quarters, lines[name])
    keyed("operating_income", seg["quarters"], seg["oi_total"])
    keyed("other_bets_operating_income", seg["quarters"], seg["oi_other_bets"])
    keyed("alphabet_level", seg["quarters"], seg["oi_reconciling"])
    revenue_at = dict(zip(quarters, long_revenue))
    line_at = {name: dict(zip(line_quarters, lines[name]))
               for name in ("google_services", "google_cloud")}
    keyed("operating_margin", seg["quarters"],
          [oi / revenue_at[k] * 100 for k, oi in zip(seg["quarters"], seg["oi_total"])])
    keyed("services_margin", seg["quarters"],
          [oi / line_at["google_services"][k] * 100
           for k, oi in zip(seg["quarters"], seg["oi_google_services"])])
    keyed("cloud_margin", seg["quarters"],
          [oi / line_at["google_cloud"][k] * 100
           for k, oi in zip(seg["quarters"], seg["oi_google_cloud"])])
    keyed("operating_cash_flow", quarters, long_ocf)
    keyed("capital_expenditures", quarters, long_capex)
    keyed("free_cash_flow", quarters, long_fcf)
    keyed("ttm_free_cash_flow", quarters, long_ttm_fcf)
    keyed("depreciation", quarters, long_dep)
    keyed("repurchases_of_stock", [quarter_key(p) for p in periods], q["repurchases_of_stock"])
    keyed("cloud_backlog", backlog_quarters,
          [None if quarter < backlog["basis_change_at"] else level
           for quarter, level in zip(backlog_quarters, backlog_levels)])
    keyed("cash_and_marketable_securities", balance["quarters"], balance["cash_and_marketable_securities"])
    keyed("long_term_debt", balance["quarters"], balance["long_term_debt"])

    column_periods = [periods[-5], periods[-2], periods[-1]]
    column_keys = [quarter_key(p) for p in column_periods]
    snapshot_rows = []
    snapshot_values: dict[str, list] = {}
    if snapshot is not None:
        rows_by_key = {}
        for row in snapshot["rows"]:
            kind = row.get("kind", "usd_m")
            if "from" in row:
                values = [by_quarter[row["from"]].get(key) for key in column_keys]
            elif kind == "eps_less":
                base = rows_by_key["gaap_diluted_eps"]
                values = [None if eps is None else round(eps - less, 2)
                          for eps, less in zip(base, row["less_per_share"])]
            else:
                values = row["values"]
            if "key" in row:
                rows_by_key[row["key"]] = values
            snapshot_values[row.get("key", row["label"])] = values
            snapshot_rows.append([row["label"]] + snapshot_cells(kind, values) + [row["source"]])

    # ── thresholds: the record behind every `reads` ─────────────────────────
    dep_first = long["depreciation_first_reported"]
    dep_yoy_first = quarters[leading_gap(long_dep_yoy)]
    line_floor = f"记录始于 {line_quarters[0]} —— Alphabet 那一季才第一次按这套分类披露收入。"
    opm_floor = (f"记录始于 {seg['quarters'][0]} —— 现行分部成本分摊只追溯到这一季，更早的旧口径本站不接。")
    rpo_floor = (f"记录始于 {backlog_quarters[0]} —— 剩余履约义务首次出现在 FY{backlog_quarters[0][:4]} 10-K；"
                 f"{backlog['basis_change_at']} 那一格跨了口径（改为 Cloud 单列、并纳入一年以内的合同），"
                 "细节见第二板块的 backlog 图。")
    window_floor = f"记录始于 {quarters[0]}，与本站其余页面同一窗口。"
    dep_floor = (f"记录始于 {dep_first} —— 在此之前 Alphabet 的现金流量表没有单列可比的季度折旧，"
                 f"同比因此从 {dep_yoy_first} 起。")

    def snapshot_now(key: str) -> float:
        values = snapshot_values.get(key)
        if values is None or values[-1] is None:
            raise ValueError(f"a threshold reads snapshot row {key!r} for {period}, but the stamped "
                             "`snapshot` block has no such row or its current column is empty")
        return values[-1]

    def tax_rate_ex_gains() -> float:
        taxed = snapshot_now("income_tax") - snapshot_now("equity_gain_tax_effect")
        return taxed / (snapshot_now("pretax_income") - snapshot_now("equity_securities_gain")) * 100

    lines_source = "逐季来自各期 10-Q / 10-K 的收入分类表（第四季为全年减前三季），同比为自算（D）。"
    records = {
        "cloud_yoy": lambda: (line_labels, long_cloud_yoy, {
            "fmt": "pct1", "ylab": "同比增速", "name": "Cloud 收入 YoY D", "per": "季度",
            "floor": line_floor, "source": "Cloud 收入" + lines_source}),
        "cloud_opm": lambda: (line_labels, long_cloud_opm, {
            "fmt": "pct1", "ylab": "利润率", "name": "Cloud 经营利润率 D", "per": "季度",
            "floor": opm_floor, "source": "Cloud 经营利润来自各期分部表，除以 Cloud 收入为自算（D）。"}),
        "search_yoy": lambda: (line_labels, long_search_yoy, {
            "fmt": "pct1", "ylab": "同比增速", "name": "Search & other YoY D", "per": "季度",
            "floor": line_floor, "source": "Search & other 收入" + lines_source}),
        "network_yoy": lambda: (line_labels, long_network_yoy, {
            "fmt": "pct1", "ylab": "同比增速", "name": "Network 收入 YoY D", "per": "季度",
            "floor": line_floor, "source": "Google Network 收入" + lines_source}),
        "backlog_qoq": lambda: (backlog_labels, backlog_qoq, {
            "fmt": "pct1", "ylab": "环比", "name": "backlog 环比 D", "per": "季度",
            "floor": rpo_floor, "source": "backlog 为各期 10-Q / 10-K 的剩余履约义务，环比为自算（D）。"}),
        "backlog_net_add": lambda: (backlog_labels, backlog_net_add, {
            "fmt": "usd0", "ylab": "$B", "name": "backlog 单季净增 D", "per": "季度",
            "floor": rpo_floor, "source": "backlog 为各期 10-Q / 10-K 的剩余履约义务，单季净增为相邻两季相减（D）。"}),
        "capex_quarter": lambda: (long_labels, long_capex, {
            "fmt": "f0c", "ylab": "$M", "name": "单季 CapEx", "per": "季度",
            "floor": window_floor,
            "source": "资本开支逐季来自各期现金流量表（10-Q 只按年初至今披露，逐季由相邻两个年初至今值相减）。"}),
        "ttm_fcf": lambda: (long_labels, long_ttm_fcf, {
            "fmt": "f0c", "ylab": "$M", "name": "TTM 自由现金流 D", "per": "季度",
            "floor": window_floor,
            "source": "自由现金流 = 经营现金流 − 购买物业及设备，逐季相减后滚动四季（D）；本季值与新闻稿对账表的 TTM 一致。"}),
        "dep_yoy": lambda: (long_labels, long_dep_yoy, {
            "fmt": "pct1", "ylab": "同比增速", "name": "折旧 YoY D", "per": "季度",
            "floor": dep_floor, "source": "季度折旧来自各期现金流量表，第四季按全年减前三季倒推；同比为自算（D）。"}),
        "net_cash": lambda: ([period], [balance["cash_and_marketable_securities"][-1] - balance["long_term_debt"][-1]], {
            "chart": False, "fmt": "f0c", "name": "净现金 D",
            "source": "现金、现金等价物与有价证券减长期债务，两行都取自季末资产负债表（D）。"}),
        "atm_sold": lambda: ([period], [snapshot_now("atm_sold")], {
            "chart": False, "fmt": "f0c", "name": "ATM 本季发行额",
            "why": "ATM 计划 2026-06-01 才签订，没有历史可画"}),
        "tax_rate_ex_gains": lambda: ([period], [tax_rate_ex_gains()], {
            "chart": False, "fmt": "pct1", "name": "剔权益收益的有效税率 D",
            "why": "它要用新闻稿脚注里权益证券收益带来的所得税，公司只在收益大的季度才印，没有连续的季度记录可画"}),
    }

    def record(reads: str) -> tuple:
        if reads not in records:
            raise ValueError(f"a threshold entry reads {reads!r}, which build/googl.py does not know")
        return records[reads]()

    def html_text(text: str) -> str:
        """Verbatim analysis text inside a note, which the page renders as HTML."""
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    buyback = q["repurchases_of_stock"]
    debt = balance["long_term_debt"]
    zero_buybacks = 0
    for value in reversed(buyback):
        if value != 0:
            break
        zero_buybacks += 1
    other_bets = seg["oi_other_bets"]

    def losses(before: float, after: float) -> str:
        """Other Bets' operating loss from one quarter to the next, the verb read off the numbers."""
        verb = "收窄" if abs(after) < abs(before) else "扩大" if abs(after) > abs(before) else "持平"
        return f"由 {money_m(abs(before))} {verb}到 {money_m(abs(after))}"

    story_values = {
        "cloud_opm_now": f"{cloud_opm_now:.2f}%",
        # 「创新高」 only while the record makes it true, on the record's own window.
        "cloud_opm_record": (f"，是现行分摊口径{cn_count(sum(1 for v in long_cloud_opm if v is not None))}季里最高的一季"
                             if cloud_opm_now >= max(v for v in long_cloud_opm if v is not None) else ""),
        "backlog_now": f"${backlog_levels[-1]:.1f}B",
        "backlog_add_now": f"${backlog_net_add[-1]:.1f}B",
        "capex_now": money_m(long_capex[-1]),
        "buyback_now": money_m(buyback[-1]),
        "search_prev": f"{long_search_yoy[-2]:+.1f}%",
        "search_now": f"{long_search_yoy[-1]:+.1f}%",
        "other_bets_move": losses(other_bets[-2], other_bets[-1]),
    }

    def condition(item: dict) -> tuple[str, str]:
        """(reading, verdict) of a row that is a condition rather than one number. Rows the
        series can judge are judged here; the rest carry the analysis's own verdict."""
        reads = item.get("reads")
        if reads == "buyback_debt":
            reading = (f"本季回购 {money_m(buyback[-1])}；长期债务 {money_m(debt[-2])} → {money_m(debt[-1])}")
            return reading, ("触发" if buyback[-1] == 0 and debt[-1] > debt[-2] else "未触发")
        if reads == "buyback_streak":
            reading = (f"本季回购 {money_m(buyback[-1])}"
                       + (f"，已连续{cn_count(zero_buybacks)}季为零" if zero_buybacks else ""))
            return reading, ("触发" if zero_buybacks >= 3 else
                             f"还差{cn_count(3 - zero_buybacks)}季" if zero_buybacks else "未触发")
        if reads == "eps_ex_gains_qoq":
            eps = snapshot_values.get("eps_ex_equity_gains")
            if eps is None or None in eps[1:]:
                raise ValueError("the EPS condition reads the snapshot's `eps_ex_equity_gains` row")
            step = round(eps[-1] - eps[-2], 2)
            reading = (f"剔权益收益 EPS 本季 ${eps[-1]:.2f}、上季 ${eps[-2]:.2f}，环比 "
                       f"{'+' if step >= 0 else '−'}${abs(step):.2f}")
            # The snapshot carries this quarter and the one before, so one step is all
            # the page can see; a second flat step would be on last quarter's page.
            return reading, ("未触发" if step > 0 else "本季环比不增长，是否已连续两季要对照上一季的页面")
        if reads == "cloud_opm_two_down":
            steps = [round(b, 2) - round(a, 2) for a, b in zip(long_cloud_opm[-3:-1], long_cloud_opm[-2:])]
            falling = 0
            for step in reversed(steps):
                if step >= 0:
                    break
                falling += 1
            slowing = round(long_cloud_yoy[-1], 1) < round(long_cloud_yoy[-2], 1)
            reading = (f"Cloud 利润率本季环比 {steps[-1]:+.2f}pp，收入同比由 {long_cloud_yoy[-2]:.1f}% "
                       f"{'放缓' if slowing else '加快'}到 {long_cloud_yoy[-1]:.1f}%")
            return reading, ("触发" if falling >= 2 and slowing else "未触发")
        if reads is not None:
            raise ValueError(f"a condition row reads {reads!r}, which build/googl.py does not know")
        return fill_story(item["reading"], story_values), item["verdict"]

    source = (
        'Source: <a href="https://abc.xyz/investor/" rel="noopener">Alphabet Investor Relations</a>'
        f'（{period} earnings release / call；历史季度 release 经 SEC EDGAR 回源）。'
    )

    # ── section one: what last quarter's analysis left, settled ─────────────
    # (a) the follow-up questions, as this quarter's analysis judged them
    labels = closure["labels"]
    items = closure["items"]
    unlabelled = sorted({item["verdict"] for item in items} - set(labels))
    if unlabelled:
        raise ValueError(f"series block `followup_closure` judges {unlabelled} outside its labels {labels}")
    closure_counts = [sum(1 for item in items if item["verdict"] == label) for label in labels]
    judged = [(label, count) for label, count in zip(labels, closure_counts) if count]
    scorecard = closure.get("scorecard")
    closure_chart = {
        "kind": "bars_labeled",
        # Every category the analysis used, in its order, so the counts in the
        # title add up to the total in front of them.
        "title": f"上季 {len(items)} 条待验证问题：" + "、".join(f"{count} 条{label}" for label, count in judged),
        "xlabels": labels,
        "values": closure_counts,
        "legend": "问题条数",
        "fmt": "f0",
        "yfmt": "f0",
        "label_fmt": "f0",
        "ylab": "条",
        "note": (
            "；".join(f"{label}的{cn_count(count)}条：" + "、".join(
                f"#{item['n']} {item['topic']}（{html_text(fill_story(item['answer'], story_values))}）"
                for item in items if item["verdict"] == label) for label, count in judged) + "。"
            + html_text(closure["rule"])
            + (f"第 0 节另有上季 {scorecard['total']} 条关键判断的记分卡：方向对 {scorecard['direction_right']} 条，"
               f"错 {len(scorecard['direction_wrong'])} 条（" + "、".join(f"「{name}」" for name in scorecard["direction_wrong"])
               + "）。" if scorecard else "")
        ),
        "src_extra": (f"问题清单来自上季（{closure['set_in']}）本地分析文末的 Follow-up Questions；判定取自本季本地分析"
                      f"第 0 节，各条的数逐条对过 {period} 新闻稿与 10-Q。"),
    }

    # (b) the previous analysis's section 8, every line against this quarter
    prior_rows = {row["row"]: row for row in prior_kpi["rows"]}
    prior_lines = prior_kpi["quantified"]
    prior_retired = prior_kpi.get("retired", [])
    prior_conditions = prior_kpi.get("conditions", [])
    covered = ({entry["row"] for entry in prior_lines + prior_retired}
               | {item["row"] for item in prior_conditions})
    if covered != set(prior_rows):
        raise ValueError(f"`prior_kpi_settlement` rows {sorted(prior_rows)} are not all settled: "
                         f"entries cover {sorted(covered)}")
    prior_read = {entry["id"]: record(entry["reads"]) for entry in prior_lines + prior_retired}

    def prior_now(entry: dict) -> float:
        value = prior_read[entry["id"]][1][-1]
        if value is None:
            raise ValueError(f"threshold {entry['id']!r} reads {entry['reads']!r}, which has no {period} value")
        return value

    prior_state = {entry["id"]: line_state(entry, prior_read[entry["id"]][1]) for entry in prior_lines}
    priced = [entry for entry in prior_lines if entry["threshold"] != 0]
    at_zero = [entry for entry in prior_lines if entry["threshold"] == 0]
    broken = [entry for entry in priced if prior_state[entry["id"]] == "击穿"]
    crossing = [entry for entry in priced if prior_state[entry["id"]] == "越线"]
    operating_held = all(prior_state[entry["id"]] == "守住" for entry in priced if entry["kind"] == "operating")
    if not broken and not crossing:
        tally = "全部守住"
    elif broken and not crossing and operating_held and all(entry["kind"] == "cash" for entry in broken):
        tally = "经营类全部守住，击穿的是现金类的" + "、".join(
            f"{spaced(entry['metric'])}{tier_line(entry)}" for entry in broken)
    else:
        tally = (f"{len(priced) - len(broken) - len(crossing)} 条守住、{len(broken)} 条击穿"
                 + (f"、{len(crossing)} 条越线但还不满该行要求的连续季数" if crossing else ""))
    condition_results = [(item, *condition(item)) for item in prior_conditions]
    prior_overview = headroom_exhibit(
        f"上季 {len(priced)} 条量化阈值：{tally}",
        [{**entry, "metric": tier_label(entry), "actual": prior_now(entry)} for entry in priced],
        "actual",
        (
            "正值 = 本季实际落在上季阈值的安全侧，负值 = 已越过。阈值逐字取自上季本地分析第 8 节，"
            "一行写了几档就拆成几条。"
            + ("阈值为零的" + "、".join(spaced(tier_label(entry)) for entry in at_zero)
               + "没有百分比余量，只画在它自己的图上：" + "；".join(
                   f"本季 {unit_text(entry['unit'], prior_now(entry))}，{prior_state[entry['id']]}"
                   for entry in at_zero) + "。" if at_zero else "")
            + "".join(f"{entry['metric']}{tier_line(entry)}：本季 {unit_text(entry['unit'], prior_now(entry))}，"
                      f"没有触发；但{html_text(entry['why'])}，所以不进本图。" for entry in prior_retired)
            + (f"另有{cn_count(len(condition_results))}行写不成一个数：" + "；".join(
                f"第 {item['row']} 行{spaced(item['short'])}（「{html_text(prior_rows[item['row']]['threshold_text'])}」）"
                f"——{html_text(reading)}，判定：{verdict}" for item, reading, verdict in condition_results) + "。"
               if condition_results else "")
            + "逐条的走势见下面各图。"
        ),
        src_extra=(f"阈值逐字取自上季（{prior_kpi['set_in']}）本地分析第 8 节，不是公司指引；实际值为 {period} 申报值"
                   "或据其计算的自算值（D）。"),
    )

    def settled_title(group: list[dict], values: list) -> str:
        unit, actual = group[0]["unit"], values[-1]
        head = f"{group[0]['metric']} {unit_text(unit, actual)}："
        if is_band(group):
            low = next(entry for entry in group if entry["direction"] == "up")
            high = next(entry for entry in group if entry["direction"] == "down")
            band = f"{unit_text(unit, low['threshold'])}–{unit_text(unit, high['threshold'])}"
            if unsafe(low, actual):
                return head + f"跌破上季区间 {band} 的下沿"
            if unsafe(high, actual):
                return head + f"高于上季区间 {band} 的上沿"
            return head + f"落在上季区间 {band} 之内"
        parts: list[tuple[str, list[str]]] = []
        for entry in group:
            state = line_state(entry, values)
            if parts and parts[-1][0] == state:
                parts[-1][1].append(tier_line(entry))
            else:
                parts.append((state, [tier_line(entry)]))
        need = max(entry.get("consecutive", 1) for entry in group)
        words = {"守住": "守住上季", "击穿": "击穿上季", "越线": "越过上季"}
        return head + "，".join(words[state] + "、".join(lines)
                                + (f"（还不满连续{cn_count(need)}季）" if state == "越线" else "")
                                for state, lines in parts)

    def row_words(row: dict, which: str) -> str:
        return (f"{which}本地分析第 8 节第 {row['row']} 行原文：{html_text(row['name'])}"
                f"「{html_text(row['threshold_text'])}」，触发动作「{html_text(row['action'])}」。")

    def margin_words(group: list[dict], value: float) -> str:
        priced_lines = [entry for entry in group if entry["threshold"] != 0]
        return ("距" + "、".join(f"{tier_line(entry)} 余量 "
                                f"{headroom(entry['direction'], entry['threshold'], value):+.1f}%"
                                for entry in priced_lines) + "。" if priced_lines else "")

    def consecutive_words(group: list[dict]) -> str:
        need = max(entry.get("consecutive", 1) for entry in group)
        return f"这一行要连续{cn_count(need)}季越线才算触发。" if need > 1 else ""

    prior_charts = []
    for group in by_reads(prior_lines):
        xlabels, values, spec = prior_read[group[0]["id"]]
        if spec.get("chart") is False:
            continue
        actual = values[-1]
        previous = next((value for value in reversed(values[:-1]) if value is not None), None)
        prior_charts.append(tier_chart(
            settled_title(group, values), xlabels, values, group, spec,
            line_word="上季",
            note=(row_words(prior_rows[group[0]["row"]], "上季")
                  + f"本季 {unit_text(group[0]['unit'], actual)}"
                  + (f"（上季 {unit_text(group[0]['unit'], previous)}）" if previous is not None else "") + "；"
                  + margin_words(group, actual)
                  + consecutive_words(group)
                  + record_words(group, values, spec["per"])
                  + spec["floor"]),
            src_extra=spec["source"] + f"阈值为上季（{prior_kpi['set_in']}）本地研究设定，不是公司指引。",
        ))

    # (c) the company's own guidance: Alphabet guides no quarterly figure, and
    # its one numeric guide -- the year's capital expenditure -- settles only at
    # the year end, so it is drawn in section two as a revision record.
    settled_charts = [closure_chart, prior_overview] + prior_charts

    # ── section two: the quarter ────────────────────────────────────────────
    # One chart per conclusion of this quarter's analysis (sections 1, 3 and 7)
    # that filed numbers can draw, in the analysis's order: what drove the
    # quarter, then the arithmetic under the headline, then cash and capital.
    highlights: list[dict] = []
    topics: list[str] = []

    # Cloud: growth and margin together.
    joint = 0
    for index in range(len(line_quarters) - 1, 0, -1):
        a, b = long_cloud_opm[index], long_cloud_opm[index - 1]
        if a is None or b is None:
            break
        if round(long_cloud_yoy[index], 1) > round(long_cloud_yoy[index - 1], 1) and round(a, 2) > round(b, 2):
            joint += 1
        else:
            break
    if joint >= 2:
        together = f"两条线近{cn_count(joint)}季同向上行，是最难被叙事伪造的组合；"
    elif joint == 1:
        together = "两条线本季同向上行；"
    else:
        together = "两条线本季没有同向上行；"
    eight_back = long_cloud_opm[-1 - WINDOW] if len(long_cloud_opm) > WINDOW else None
    opm_record = [value for value in long_cloud_opm if value is not None]
    cloud_accel = rising_streak(long_cloud_yoy, 1)
    opm_streak = rising_streak(long_cloud_opm, 2)
    cloud_pace = (f"增速连续{cn_count(cloud_accel)}季加快" if cloud_accel >= 2 else
                  "增速本季加快" if cloud_accel == 1 else "增速本季没有加快")
    opm_pace = (f"利润率连续{cn_count(opm_streak)}季上升" if opm_streak >= 2 else
                "利润率本季上升" if opm_streak == 1 else "利润率本季没有上升")
    highlights.append({
        # Growth and margin are the two curves that decide this segment; the
        # revenue level is a scale fact and belongs in the note, not the axis.
        "kind": "lines",
        "title": (f"Cloud 增速本季 {cloud_yoy_now:.1f}%、利润率 {cloud_opm_now:.2f}%："
                  f"{cloud_pace}，{opm_pace}"),
        "xlabels": line_labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": "Cloud 收入 YoY", "values": long_cloud_yoy, "color": "NAVY"},
            {"name": "Cloud 经营利润率", "values": long_cloud_opm, "color": "GOLD"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "zero_base": True,
        "end_label": True,
        "ylab": "同比增速 / 利润率",
        "note": (
            together
            + f"本季收入 ${long_cloud[-1]:,.0f}M"
            + (f"，利润率较八季前 {cloud_opm_now - eight_back:+.2f}pp。" if eight_back is not None else "。")
            + "<b>两条线在这张图上起点不同，那不是缺数据，是两个不同的披露底。</b>"
            f"收入线从 {line_quarters[0]} 起（Alphabet 那一季才第一次按这套分类披露收入）；"
            f"利润率线从 {seg['quarters'][0]} 起（2023 年改了分部成本分摊，公司只把 2022 四个季度"
            "追溯了一遍）。更早还有一段旧分摊口径的 Cloud 利润率，本站不接 —— "
            "把两段拼起来会在 2022 年初造出一个纯由分摊改动产生的台阶。"
            f"利润率线自己的窗口里，最低一格是 {min(opm_record):.1f}%，最高是 {max(opm_record):.1f}%。"
        ),
        "src_extra": source_note("Cloud 收入与经营利润来自公司分部表；同比与 OPM 为自算"),
    })
    topics.append("Cloud 的增速与利润率")

    # Search and YouTube.
    def below_zero(values: list[float | None], name: str) -> str:
        found = runs(values, lambda value: value < 0)
        if not found:
            return f"{name}没有跌破过零"
        parts = []
        for first, last in found:
            low = min(range(first, last + 1), key=lambda i: values[i])
            if first == last:
                parts.append(f"{line_quarters[first]}（{values[first]:.1f}%）")
            else:
                parts.append(f"{span_text(line_quarters, first, last)}（最低 "
                             f"{line_quarters[low]} 的 {values[low]:.1f}%）")
        return f"{name}{cn_count(len(found))}次，" + "与 ".join(parts)
    search_dips = runs(long_search_yoy, lambda value: value < 0)
    recent_dip = any(value is not None and value < 0
                     for value in long_search_yoy[-WINDOW:] + long_youtube_yoy[-WINDOW:])
    search_yoy_values = [value for value in long_search_yoy if value is not None]
    # At the one decimal the page prints, so a step that rounds to zero is 「持平」.
    search_pace = ("放缓" if round(search_step, 1) < 0 else "加快" if round(search_step, 1) > 0 else "持平")
    search_move = ("与上季持平" if search_pace == "持平" else f"比上季{search_pace} {abs(search_step):.1f}pp")
    youtube_now = long_youtube_yoy[-1]
    youtube_driver = story.get("youtube_driver")
    both_dipped = [name for name, values in (("Search", long_search_yoy), ("YouTube", long_youtube_yoy))
                   if runs(values, lambda value: value < 0)]
    highlights.append({
        "kind": "lines",
        "title": (
            f"Search 增速本季 {search_yoy_now:.1f}%，{search_move}；"
            f"{cn_count(len(line_quarters) // 4)}年里它"
            + (f"跌破过零{cn_count(len(search_dips))}次，最低 {min(search_yoy_values):.1f}%"
               if search_dips else f"没有跌破过零，最低 {min(search_yoy_values):.1f}%")
        ),
        "xlabels": line_labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": "Search & other YoY", "values": long_search_yoy, "color": "NAVY"},
            {"name": "YouTube ads YoY", "values": long_youtube_yoy, "color": "MBLUE"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "zero_base": True,
        "end_label": True,
        "ylab": "同比增速",
        "note": (
            (f"Search 同比由 {long_search_yoy[-2]:.1f}% {search_pace}到 {search_yoy_now:.1f}%"
             if search_pace != "持平" else f"Search 同比与上季同为 {search_yoy_now:.1f}%")
            + (f"；{html_text(story['search_outlook'])}。" if story.get("search_outlook") else "。")
            + f"YouTube {youtube_now:+.1f}%"
            + (f" {youtube_driver}。" if youtube_driver else "。")
            + ("<b>八季的窗口里这两条线只是高低起伏，" if not recent_dip else "<b>")
            + (f"拉到 {line_quarters[0]} 之后两条都跌破过零</b>：" if len(both_dipped) == 2 else
               f"拉到 {line_quarters[0]} 之后只有 {both_dipped[0]} 跌破过零</b>："
               if both_dipped else f"拉到 {line_quarters[0]} 之后两条都没有跌破过零</b>。")
            + (below_zero(long_search_yoy, "Search ") + "；" + below_zero(long_youtube_yoy, "YouTube ") + "。"
               if both_dipped else "")
            + f"起点 {line_quarters[0]} 是披露底：更早的季度公司没有按这套"
            "分类披露过收入。"
        ),
        "src_extra": source_note("分项收入来自公司季度 release，同比为自算；展望与世界杯是电话会口径"),
    })
    topics.append(f"Search {search_pace}")

    # Google Services' margin: the step into this quarter, against the same step
    # in every earlier year of the current allocation.
    seg_quarters = seg["quarters"]
    seg_labels = [quarter_label(quarter) for quarter in seg_quarters]
    services_margin = [oi / line_at["google_services"][quarter] * 100
                       for quarter, oi in zip(seg_quarters, seg["oi_google_services"])]
    total_margin = [oi / revenue_at[quarter] * 100 for quarter, oi in zip(seg_quarters, seg["oi_total"])]
    step_into = [(seg_quarters[i][:4], round(services_margin[i], 2) - round(services_margin[i - 1], 2))
                 for i in range(1, len(seg_quarters)) if seg_quarters[i][4:] == seg_quarters[-1][4:]]
    services_step = step_into[-1][1]
    earlier_steps = step_into[:-1]
    fell = [year for year, step in earlier_steps if step < 0]
    rose = [year for year, step in earlier_steps if step > 0]
    services_yoy = round(services_margin[-1], 2) - round(services_margin[-5], 2)
    step_name = f"{quarter_label(seg_quarters[-2])[:2]}→{quarter_label(seg_quarters[-1])[:2]}"
    if not earlier_steps:
        seasonal = ""
    elif fell and not rose:
        seasonal = f"；同一步（{step_name}）此前{cn_count(len(earlier_steps))}年都是回落"
    elif not fell:
        seasonal = f"；同一步（{step_name}）此前{cn_count(len(earlier_steps))}年没有一年回落"
    else:
        seasonal = (f"；同一步（{step_name}）此前{cn_count(len(earlier_steps))}年里"
                    f"{cn_count(len(fell))}年回落、{cn_count(len(rose))}年上升")
    reading = story.get("services_reading")
    highlights.append({
        "kind": "lines",
        "title": (f"Services 经营利润率本季 {services_margin[-1]:.2f}%：环比 {services_step:+.2f}pp、"
                  f"同比 {services_yoy:+.2f}pp" + seasonal),
        "xlabels": seg_labels,
        "series": [
            {"name": "Google Services 经营利润率 D", "values": services_margin, "color": "NAVY"},
            {"name": "Alphabet 经营利润率 D", "values": total_margin, "color": "GRAY"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "经营利润率",
        "note": (
            (html_text(reading) + "。" if reading else "")
            # Weighed against the record only where the analysis made the seasonal claim.
            + (f"<b>现行分摊口径的记录只在一部分年份支持「季节性」这个读法</b>：同一步回落的是 "
               + "、".join(fell) + "，上升的是 " + "、".join(rose) + "。" if reading and fell and rose else "")
            + f"同比看本季 {services_yoy:+.2f}pp；Alphabet 整体经营利润率本季 {total_margin[-1]:.2f}%。"
            f"记录始于 {seg_quarters[0]} —— 现行分部成本分摊只追溯到这一季。"
        ),
        "src_extra": source_note("分部经营利润与分部收入来自各期分部表，利润率为自算"),
    })
    topics.append("Services 利润率的环比"
                  + ("回落" if round(services_step, 2) < 0 else "上升" if round(services_step, 2) > 0 else "持平"))

    # Backlog.
    level_now, add_now, add_before = backlog_levels[-1], backlog_net_add[-1], backlog_net_add[-2]
    backlog_record = level_now >= max(backlog_levels)
    add_fell = add_now < add_before
    peak_at = max(range(len(backlog_levels)), key=lambda i: backlog_levels[i])
    level_words = (f"backlog 创 ${level_now:.0f}B 新高" if backlog_record else
                   f"backlog ${level_now:.0f}B，低于 {backlog_quarters[peak_at]} 的 "
                   f"${backlog_levels[peak_at]:.0f}B")
    def bn0(value: float) -> str:
        """``-124.2`` → ``'-$124B'``: the sign in front of the currency, as the headline writes it."""
        return f"{'-' if value < 0 else ''}${abs(value):.0f}B"
    add_words = (f"单季净增从 {bn0(add_before)} {'降' if add_fell else '升'}到 {bn0(add_now)}")
    opposite = (level_now > backlog_levels[-2]) and add_fell
    backlog_story = story.get("backlog_reading")
    change_at = backlog["basis_change_at"]
    basis_words = ""
    if change_at in backlog_quarters[1:] and backlog.get("total_usd_bn", {}).get(change_at) is not None:
        at = backlog_quarters.index(change_at)
        total_then = backlog["total_usd_bn"][change_at]
        short_term = backlog.get("short_term_usd_bn") if backlog.get("short_term_included_at") == change_at else None
        basis_words = (f"{change_at} 那一格跨了口径：公司从那一季起单列 Cloud 的部分（公司总额 ${total_then:.1f}B、"
                       f"其中 Cloud ${backlog_levels[at]:.1f}B）"
                       + (f"，并把一年以内的合同也算进来（当季约 ${short_term:.1f}B）；按旧口径同口径（公司总额、"
                          f"扣掉一年以内合同）那一季的净增约 ${total_then - short_term - backlog_levels[at - 1]:.1f}B"
                          if short_term is not None else "")
                       + "。")
    highlights.append({
        "kind": "bar_line",
        "title": level_words + ("，但" if opposite else "，") + add_words,
        "xlabels": backlog_labels,
        "bar": {
            "name": "backlog 余额",
            "color": "NAVY",
            "values": backlog_levels,
            "yfmt": "usd0",
        },
        "line": {
            "name": "单季净增 (RHS)",
            "color": "RED",
            "values": backlog_net_add,
            "yfmt": "usd0",
        },
        "fmt": "usd0",
        "yfmt": "usd0",
        "label_fmt": "usd0",
        "ylab": "$B",
        "ylab2": "单季净增 $B",
        "note": (
            ("余额与净增方向相反：" if opposite else "")
            + (backlog_story.format(prev_q=periods[-2].split()[0], cur_q=quarter_word,
                                    prev_add=f"${add_before:.0f}B", add=f"${add_now:.0f}B")
               if backlog_story else f"单季净增 {bn0(add_now)}。")
            + basis_words
        ),
        "src_extra": (
            "backlog 为合同剩余履约义务，来自各期 10-Q / 10-K"
            + (f"；{period} 尚无 10-Q，采用当季电话会口径。"
               if backlog_quarters[-1] in backlog.get("from_call", []) else "。")
            + "公司未披露取消额与客户集中度，Q1 2026 起纳入 TPU hardware agreements。口径细节见核对表。"
        ),
    })
    fall = (1 - add_now / add_before) * 100 if add_before > 0 and add_fell else None
    topics.append("backlog 净增" + ("骤降" if fall is not None and fall >= 50 else "回落" if add_fell else "回升"))

    # Earnings per share with and without the equity-securities gain.
    eps_values = snapshot_values.get("gaap_diluted_eps")
    ex_values = snapshot_values.get("eps_ex_equity_gains")
    revenue_now = long_revenue[-1]
    if eps_values and ex_values and consensus is not None:
        eps_now, ex_now = eps_values[-1], ex_values[-1]
        gain_now = round(eps_now - ex_now, 2)
        expected_eps = consensus["operating_eps_mid"]
        eps_gap = (ex_now / expected_eps - 1) * 100
        side = ("略低于" if -3 < eps_gap < 0 else "低于" if eps_gap < 0 else
                "略高于" if 0 < eps_gap < 3 else "高于" if eps_gap > 0 else "等于")
        revenue_gap = (revenue_now / consensus["revenue_usd_m"] - 1) * 100
        highlights.append({
            "kind": "bars_labeled",
            "title": (f"${eps_now:.2f} 的 GAAP EPS 里 ${gain_now:.2f} 来自权益证券收益，"
                      f"剔除后 ${ex_now:.2f}、{side}市场预期"),
            "xlabels": ["GAAP 摊薄 EPS", "其中：权益证券收益", "剔除后（简单自算）", "市场预期"],
            "values": [eps_now, gain_now, ex_now, expected_eps],
            "legend": "每股收益",
            "fmt": "usd2",
            "yfmt": "usd2",
            "label_fmt": "usd2",
            "ylab": "美元 / 股",
            "note": (
                f"公司披露权益证券收益贡献 EPS ${gain_now:.2f}；剔除后 ${ex_now:.2f}，较市场预期 "
                f"${expected_eps:.2f} {'低' if eps_gap < 0 else '高'} {abs(eps_gap):.1f}%。"
                f"同期收入{'高' if revenue_gap >= 0 else '低'}于市场预期 {abs(revenue_gap):.1f}%。"
            ),
            "src_extra": (
                f"GAAP EPS 与权益收益的每股贡献来自 {quarter_word} release 脚注；${ex_now:.2f} 是 "
                f"${eps_now:.2f} − ${gain_now:.2f} 的算术拆分，"
                "不是公司定义的 non-GAAP。市场预期为财报前一致预期区间 "
                f"${consensus['operating_eps_low']:.2f}–${consensus['operating_eps_high']:.2f} 的中值，不具名。"
            ),
        })
        topics.append("GAAP EPS 里的权益证券收益与对市场预期")

    # Free cash flow, quarter by quarter.
    fcf_now, fcf_before = long_fcf[-1], long_fcf[-2]
    ocf_delta = long_ocf[-1] - long_ocf[-5]
    capex_delta = long_capex[-1] - long_capex[-5]
    count_words = cn_count(len(long_fcf))
    if fcf_now < 0:
        head = (f"单季自由现金流转负至 {money_bn(fcf_now)} —— " if fcf_before >= 0 else
                f"单季自由现金流 {money_bn(fcf_now)}，仍为负 —— ")
        head += (f"{count_words}季里唯一的一次" if negative_fcf == 1
                 else f"{count_words}季里的第 {negative_fcf} 次")
    else:
        head = (f"单季自由现金流 {money_bn(fcf_now)} —— {count_words}季里"
                + (f"为负的有 {negative_fcf} 季" if negative_fcf else "没有一季为负"))
    earlier_negative = [quarters[index] for index, value in enumerate(long_fcf[:-1]) if value < 0]
    fcf_story = story.get("fcf_context", "")
    highlights.append({
        "kind": "diverging_bars",
        "title": head,
        "xlabels": long_labels,
        "xstep": LONG_STEP,
        "values": [round(value, 1) for value in long_fcf],
        "legend": "自由现金流",
        "positive_label": "正自由现金流",
        "negative_label": "负自由现金流",
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "$M",
        "zero_line": True,
        "note": (
            f"经营现金流同比{'增' if ocf_delta >= 0 else '减'} ${abs(ocf_delta) / 1000:.1f}B，"
            + (f"被同比增 ${capex_delta / 1000:.1f}B 的 CapEx 完全吞没"
               if capex_delta > ocf_delta > 0 else
               f"CapEx 同比{'增' if capex_delta >= 0 else '减'} ${abs(capex_delta) / 1000:.1f}B")
            + (f"；{fcf_story}" if fcf_story else "。")
            + ((f"<b>把窗口从八季拉到{count_words}季，「首次转负」这句话仍然成立</b> —— "
                f"{quarters[0][:4]} 年以来这条线只有本季一次落到零以下，"
                f"此前最低的一格是 ${min(long_fcf[:-1]) / 1000:,.1f}B。")
               if fcf_now < 0 and negative_fcf == 1 else
               ("<b>八季的窗口里「首次转负」是错的说法</b> —— 更早的负值出现在 "
                + "、".join(long_labels[i] for i, value in enumerate(long_fcf)
                           if value < 0 and i != len(long_fcf) - 1) + "。")
               if fcf_now < 0 else
               (f"{quarters[0][:4]} 年以来这条线落到零以下的季度：" + "、".join(earlier_negative) + "。"
                if earlier_negative else ""))
        ),
        "src_extra": source_note("FCF = 经营现金流 − 购买物业及设备"),
    })
    topics.append("单季自由现金流" + ("转负" if fcf_now < 0 <= fcf_before else ""))

    # Where the quarter's cash came from and went: the capital-allocation bridge.
    capital = stamped_block(staging, "capital_allocation", period)
    buyback_now = buyback[-1]
    equity_raised = debt_raised = 0.0
    if capital is not None:
        flows = (capital["sources"] + [{"label": "资本开支", "value": -long_capex[-1]}] + capital["uses"]
                 + [{"label": "回购", "value": -buyback_now}])
        equity_raised = sum(item["value"] for item in capital["sources"] if item["kind"] == "equity")
        debt_raised = sum(item["value"] for item in capital["sources"] if item["kind"] == "debt")
        raised = sum(item["value"] for item in capital["sources"])
        spent_out = -sum(item["value"] for item in flows if item["value"] < 0)
        atm_now = snapshot_values.get("atm_sold", [None])[-1]
        highlights.append({
            "kind": "diverging_bars",
            "title": (f"本季回购 {money_m(buyback_now)}，" if buyback_now == 0 else f"本季回购 {money_bn(buyback_now)}，")
                     + (f"发行普通股与强制可转优先股融资 {money_bn(equity_raised)}、" if equity_raised else "")
                     + f"净发债 {money_bn(debt_raised)}",
            "xlabels": [item["label"] for item in flows],
            "values": [round(item["value"], 1) for item in flows],
            "legend": "本季现金流（流入为正）",
            "positive_label": "融资流入",
            "negative_label": "资本开支、投资与股东回报流出",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "zero_line": True,
            "note": (
                f"{cn_count(len(capital['sources']))}项融资合计 {money_bn(raised)}；资本开支、"
                + "、".join(item["label"] for item in capital["uses"])
                + f"用掉 {money_bn(spent_out)}"
                + (f"，回购为零" if buyback_now == 0 else "")
                + "。"
                + (html_text(capital["first_time"]) + "。" if capital.get("first_time") else "")
                + (f"CFO 在电话会上说「{html_text(capital['equity_markets_quote'])}」（ATM 计划除外）。"
                   if capital.get("equity_markets_quote") else "")
                + (f"上限 ${capital['atm_capacity_usd_bn']:.1f}B 的 ATM 计划本季发行 {money_m(atm_now)}。"
                   if capital.get("atm_capacity_usd_bn") and atm_now is not None else "")
            ),
            "src_extra": (f"{quarter_word} release 现金流量表单季列；资本开支与回购与本页其余图同一序列。"
                          "电话会引语为公司口径。"),
        })
        raised_by = [words for words, amount in (("发股", equity_raised), ("发债", debt_raised)) if amount > 0]
        topics.append(("回购归零" if buyback_now == 0 else "回购继续")
                      + (f"而{'与'.join(raised_by)}" if raised_by else ""))

    # This year's capex guidance, call by call.
    guided_year = capex_guide["fiscal_years"][-1]
    guided = [index for index, year in enumerate(capex_guide["fiscal_years"]) if year == guided_year]
    lows = [capex_guide["low_usd_bn"][index] for index in guided]
    highs = [capex_guide["high_usd_bn"][index] for index in guided]
    mids = [(low + high) / 2 for low, high in zip(lows, highs)]
    raises = sum(1 for a, b in zip(mids, mids[1:]) if b > a)
    cuts = sum(1 for a, b in zip(mids, mids[1:]) if b < a)
    first_call = datetime.date.fromisoformat(capex_guide["dates"][guided[0]])
    last_call = datetime.date.fromisoformat(capex_guide["dates"][guided[-1]])
    days = (last_call - first_call).days
    within = "半年内" if days <= 184 else ("一年内" if days <= 366 else "")
    if len(guided) == 1:
        guide_title = f"FY{guided_year} CapEx 首次指引 ${lows[0]}–{highs[0]}B"
        guide_move = f"首次给出 ${lows[0]}–{highs[0]}B"
    elif cuts == 0 and raises == len(guided) - 1:
        guide_title = (f"FY{guided_year} CapEx 指引{within}{cn_count(raises)}次上调，"
                       f"中点从 ${mids[0]:.0f}B 抬到 ${mids[-1]:.0f}B")
        guide_move = f"{within}{cn_count(raises)}次上调至 ${lows[-1]}–{highs[-1]}B"
    else:
        guide_title = (f"FY{guided_year} CapEx 指引{within}改过{cn_count(len(guided) - 1)}次"
                       f"（{cn_count(raises)}次上调、{cn_count(cuts)}次下调），"
                       f"中点从 ${mids[0]:.0f}B 到 ${mids[-1]:.0f}B")
        guide_move = f"{within}改过{cn_count(len(guided) - 1)}次、现为 ${lows[-1]}–{highs[-1]}B"
    in_year = [index for index, quarter in enumerate(quarters) if quarter.startswith(str(guided_year))]
    spent = sum(long_capex[index] for index in in_year) / 1000
    done = {1: "Q1", 2: "H1", 3: "前三季"}.get(len(in_year))
    rest = {1: "余下三季", 2: "H2", 3: "Q4"}.get(len(in_year))
    if done:
        spend_words = (f"；{done} 已花 ${spent:.1f}B，隐含{spaced(rest)}{' ' if rest.isascii() else ''}需再花 "
                       f"${lows[-1] - spent:.0f}–{highs[-1] - spent:.0f}B。")
    elif len(in_year) == 4:
        spend_words = (f"；全年实际 ${spent:.1f}B，"
                       + ("落在区间内" if lows[-1] <= spent <= highs[-1] else
                          "高于上限" if spent > highs[-1] else "低于下限") + "。")
    else:
        spend_words = "。"
    highlights.append({
        "kind": "bars_labeled",
        "title": guide_title,
        "xlabels": [capex_guide["calls"][index] for index in guided],
        "values": mids,
        "legend": f"FY{guided_year} CapEx 指引中点",
        "fmt": "usd0",
        "yfmt": "usd0",
        "label_fmt": "usd0",
        "ylab": "$B",
        "note": (
            "区间依次为 " + "、".join(f"${low}–{high}B" for low, high in zip(lows, highs))
            + spend_words
        ),
        "src_extra": source_note(
            f"{cn_count(len(guided))}次指引区间来自对应季度电话会；中点"
            + (f"与{spaced(rest)}{' ' if rest.isascii() else ''}隐含额" if done else "") + "为自算"),
    })
    topics.append(f"FY{guided_year} 资本开支指引")

    # ── section three: this analysis's section 8 ────────────────────────────
    next_rows = {row["row"]: row for row in next_kpi["rows"]}
    next_lines = next_kpi["quantified"]
    next_conditions = next_kpi.get("conditions", [])
    gated = next_kpi.get("disclosure_gated", [])
    covered = ({entry["row"] for entry in next_lines} | {item["row"] for item in next_conditions}
               | {item["row"] for item in gated})
    if covered != set(next_rows):
        raise ValueError(f"`next_kpi` rows {sorted(next_rows)} are not all tracked: entries cover {sorted(covered)}")
    for entry in next_lines:
        if "current" in entry or "actual" in entry:
            raise ValueError(f"`next_kpi` entry {entry['id']!r} carries a typed reading; it is read from the "
                             "series (`reads`)")
    next_read = {entry["id"]: record(entry["reads"]) for entry in next_lines}

    def next_now(entry: dict) -> float:
        value = next_read[entry["id"]][1][-1]
        if value is None:
            raise ValueError(f"threshold {entry['id']!r} reads {entry['reads']!r}, which has no {period} value")
        return value

    next_priced = [entry for entry in next_lines if entry["threshold"] != 0]
    next_zero = [entry for entry in next_lines if entry["threshold"] == 0]
    below = [entry for entry in next_priced if unsafe(entry, next_now(entry))]
    safe = len(next_priced) - len(below)
    if not below:
        state = "当前值全部在安全侧"
    elif len(below) == 1:
        state = f"{safe} 条当前值在安全侧，{tier_label(below[0])}是唯一在另一侧的一条"
    else:
        state = f"{safe} 条当前值在安全侧，{len(below)} 条在另一侧"
    uncharted = [entry for entry in next_lines if next_read[entry["id"]][2].get("chart") is False]
    next_condition_results = [(item, *condition(item)) for item in next_conditions]

    def ahead_words(entry: dict) -> str:
        """Why a line the current reading sits beyond is not yet a breach."""
        now_value = next_now(entry)
        if entry["reads"] == "capex_quarter":
            return (f"{tier_label(entry)}挂在 {next_kpi['for_period']} 的 CapEx 上，本页只有 {period} 的读数 "
                    f"{unit_text(entry['unit'], now_value)}：下季要比本季多花 "
                    f"{(entry['threshold'] / now_value - 1) * 100:.1f}% 才落在安全侧。")
        return (f"{tier_label(entry)}当前 {unit_text(entry['unit'], now_value)}，离安全侧还差 "
                f"{abs(headroom(entry['direction'], entry['threshold'], now_value)):.1f}%。")

    next_overview = headroom_exhibit(
        f"下季 {len(next_priced)} 条量化阈值：{state}",
        [{**entry, "metric": tier_label(entry), "current": next_now(entry)} for entry in next_priced],
        "current",
        (
            "口径与第一板块的余量图相同：正值 = 当前值在下季阈值的安全侧。阈值逐字取自本季本地分析第 8 节，"
            "一行写了几档就拆成几条；当前值是 " + period + " 的读数。"
            + "".join(ahead_words(entry) for entry in below)
            + ("阈值为零的" + "、".join(spaced(tier_label(entry)) for entry in next_zero) + "没有百分比余量，只画在它自己的图上："
               + "；".join(f"当前 {unit_text(entry['unit'], next_now(entry))}" for entry in next_zero)
               + "。" if next_zero else "")
            + ("".join(f"{tier_label(entry)}只进本图：当前 {unit_text(entry['unit'], next_now(entry))}，"
                       f"{next_read[entry['id']][2]['why']}。" for entry in uncharted))
        ),
        src_extra=(f"阈值为本季（{period}）本地研究设定，不是公司指引；当前值为 {period} 申报值或据其计算的自算值（D）。"
                   "写不成数的条件与要等披露的行见本板块说明与核对表。"),
    )

    next_charts = [next_overview]
    for group in by_reads(next_lines):
        xlabels, values, spec = next_read[group[0]["id"]]
        if spec.get("chart") is False:
            continue
        now_value, unit = values[-1], group[0]["unit"]
        next_charts.append(tier_chart(
            f"{group[0]['metric']}：下季阈值 "
            + " / ".join(f"{unit_text(unit, entry['threshold'])}（{entry['tier']}）" for entry in group)
            + f"，当前 {unit_text(unit, now_value)}",
            xlabels, values, group, spec,
            line_word="下季",
            note=(row_words(next_rows[group[0]["row"]], "本季")
                  + f"当前 {unit_text(unit, now_value)}；"
                  + margin_words(group, now_value)
                  + consecutive_words(group)
                  + record_words(group, values, spec["per"])
                  + spec["floor"]),
            src_extra=spec["source"] + f"阈值为本季（{period}）本地研究设定，不是公司指引。",
        ))

    # ── section four: the routine record ────────────────────────────────────
    revenue_yoy_values = [value for value in long_revenue_yoy if value is not None]
    accel = rising_streak(long_revenue_yoy, 6)
    episodes = [(first, last) for first, last in
                runs([None] + [long_revenue_yoy[i] - long_revenue_yoy[i - 1]
                               for i in range(1, len(long_revenue_yoy))],
                     lambda step: step > 0)
                if last - first + 1 >= ACCELERATION_EPISODE]
    current_episode = episodes[-1] if episodes and episodes[-1][1] == len(quarters) - 1 else None
    earlier = [episode for episode in episodes if episode is not current_episode]
    full_years = {}
    for quarter, value in zip(quarters, long_revenue):
        full_years.setdefault(quarter[:4], []).append(value)
    last_full_year = max(year for year, values in full_years.items() if len(values) == 4)
    annual_revenue = sum(full_years[last_full_year])
    beat = (revenue_now / consensus["revenue_usd_m"] - 1) * 100 if consensus else None
    if accel >= 2:
        accel_title = f"总收入同比连续 {accel} 季加速至 {revenue_yoy[-1]:.1f}%"
        accel_words = f"连续 {accel} 季加速"
    elif accel == 1:
        accel_title = f"总收入同比本季加速至 {revenue_yoy[-1]:.1f}%"
        accel_words = "本季加速"
    else:
        accel_title = f"总收入同比本季放缓至 {revenue_yoy[-1]:.1f}%"
        accel_words = "本季放缓"
    if current_episode:
        length = current_episode[1] - current_episode[0] + 1
        episode_words = (
            f"<b>八季的窗口里这只是一条上行线，{cn_count(years)}年的窗口里它是第"
            f"{cn_ordinal(len(earlier) + 1)}段连续{cn_count(ACCELERATION_EPISODE)}季以上的加速</b>"
            + (f" —— 此前{cn_count(len(earlier))}段是 "
               + "、".join(span_text(quarters, first, last) for first, last in earlier)
               + "，分别持续" + "、".join(cn_count(last - first + 1) for first, last in earlier)
               + "季后回落"
               + (f"，本轮的{cn_count(length)}季是其中最长的"
                  if length > max(last - first + 1 for first, last in earlier) else "")
               + f"；这一次与前{cn_count(len(earlier))}段的区别要靠资本强度那张图判断，不是靠这一张。"
               if earlier else "。")
        )
    else:
        episode_words = (f"<b>{cn_count(years)}年的窗口里连续{cn_count(ACCELERATION_EPISODE)}季以上的加速"
                         f"有{cn_count(len(earlier))}段</b>"
                         + ("（" + "、".join(span_text(quarters, first, last) for first, last in earlier)
                            + "），本季不在其中。" if earlier else "。"))

    build_start = quarters.index(BUILD_OUT_FROM)
    before_build = long_intensity[:build_start]
    since_build = long_intensity[build_start:]
    flat_or_down = sum(1 for a, b in zip(since_build, since_build[1:]) if round(b, 1) <= round(a, 1))
    intensity_top = long_intensity[-1] >= max(long_intensity)
    guide_mid_now = mids[-1]
    trailing_revenue = sum(long_revenue[-4:])

    dep_streak = 0
    for index in range(len(quarters) - 1, -1, -1):
        dy, ry_ = long_dep_yoy[index], long_revenue_yoy[index]
        # compared at the one decimal the page prints, so a float's last bit
        # cannot make an equal pair read as "higher"
        if dy is None or ry_ is None or round(dy, 1) <= round(ry_, 1):
            break
        dep_streak += 1
    overlap = sorted(set(captions["prior_caption"]["quarters"]) & set(captions["current_caption"]["quarters"]))
    old_at = dict(zip(captions["prior_caption"]["quarters"], captions["prior_caption"]["values"]))
    new_at = dict(zip(captions["current_caption"]["quarters"], captions["current_caption"]["values"]))
    overlap_year = overlap[0][:4]
    overlap_words = (f"{overlap_year} 年前{cn_count(len(overlap))}季"
                     if all(k[:4] == overlap_year for k in overlap)
                     and [k[4:] for k in overlap] == [f"Q{i}" for i in range(1, len(overlap) + 1)]
                     else "、".join(overlap))

    us, others = "美国", ("EMEA", "APAC", "其他美洲")
    geo_axis = quarters[yoy_from:]
    geo_valid = [i for i in range(len(geo_axis))
                 if all(long_geography_yoy[r][i] is not None for r in (us,) + others)]
    geo_quarters = [geo_axis[i] for i in geo_valid]
    leads = [long_geography_yoy[us][i] - max(long_geography_yoy[r][i] for r in others)
             for i in geo_valid]
    fastest = max(others, key=lambda r: long_geography_yoy[r][-1])
    us_share = long_geography[us][-1] / revenue_now * 100
    us_accel = rising_streak(long_geography_yoy[us], 1)
    ahead = [i for i, lead in enumerate(leads[:-1]) if lead > 0]

    routine = [
        {
            "kind": "lines",
            "title": (
                f"{accel_title}，"
                f"{cn_count(years)}年区间 {min(revenue_yoy_values):.0f}–{max(revenue_yoy_values):.0f}%"
            ),
            "xlabels": long_labels[leading_gap(long_revenue_yoy):],
            "xstep": LONG_STEP,
            "series": [
                {"name": "总收入同比", "values": long_revenue_yoy[leading_gap(long_revenue_yoy):],
                 "color": "NAVY"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "end_label": True,
            "ylab": "同比增速",
            "note": (
                f"在约 ${round(annual_revenue / 10000) * 100:,} 亿的年收入体量上{accel_words}"
                + (f"，本季收入较市场预期{'高' if beat >= 0 else '低'} "
                   f"{change(revenue_now, consensus['revenue_usd_m']) if beat >= 0 else f'{abs(beat):.1f}%'}。"
                   if consensus else "。")
                + episode_words
            ),
            "src_extra": source_note(
                "收入逐季来自各期 10-Q / 10-K（第四季为全年 − 前三季），同比为自算"),
        },
        {
            "kind": "lines",
            "title": (
                f"资本强度{cn_count(years)}年从 {long_intensity[0]:.1f}% "
                f"{'升' if long_intensity[-1] > long_intensity[0] else '降'}到 {long_intensity[-1]:.1f}%"
                + ("，且尚未见顶" if intensity_top else "")
            ),
            "xlabels": long_labels,
            "xstep": LONG_STEP,
            "series": [
                {"name": "CapEx / 收入 D", "values": long_intensity, "color": "NAVY"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "zero_base": True,
            "end_label": True,
            "ylab": "占收入比",
            "note": (
                f"FY{guided_year} 指引中点 ${guide_mid_now:.0f}B 约为过去四季收入"
                f"（${trailing_revenue / 1000:.1f}B）的 {guide_mid_now * 1000 / trailing_revenue * 100:.0f}%；"
                "这条线比利润表更早反映建设周期。"
                f"<b>{cn_count(years)}年里这条线只有两个台阶</b>：{quarters[0][:4]}–"
                f"{int(BUILD_OUT_FROM[:4]) - 1} 年长期在 "
                f"{min(before_build):.0f}–{max(before_build):.0f}% 之间来回，"
                f"{BUILD_OUT_FROM[:4]} 年起"
                + ("单向上行" if flat_or_down == 0 else
                   f"上行（{cn_count(len(since_build) - 1)}次环比里{cn_count(flat_or_down)}次没有上升）")
                + f"到今天的 {long_intensity[-1]:.1f}%"
                + (f"，当前值是{cn_count(years)}年区间的顶点而非区间内的一次波动。" if intensity_top else "。")
            ),
            "src_extra": source_note(
                "CapEx / 收入为自算；资本开支逐季来自各期现金流量表"
                "（10-Q 只按年初至今披露，逐季由相邻两个年初至今值相减）"),
        },
        {
            "kind": "lines",
            "title": (
                f"折旧同比 {dep_yoy[-1]:+.1f}%，"
                + (f"快于收入的 {revenue_yoy[-1]:+.1f}%；" if round(dep_yoy[-1], 1) > round(revenue_yoy[-1], 1) else
                   f"慢于收入的 {revenue_yoy[-1]:+.1f}%；" if round(dep_yoy[-1], 1) < round(revenue_yoy[-1], 1) else
                   f"与收入的 {revenue_yoy[-1]:+.1f}% 持平；")
                + f"{cn_count(years)}年里这条线换过一次科目，所以画成两条"
            ),
            "xlabels": long_labels,
            "xstep": LONG_STEP,
            "series": [
                {"name": captions["prior_caption"]["label"] + " YoY",
                 "values": [None if v is None else round(v, 1) for v in dep_prior_yoy],
                 "color": "GRAY"},
                {"name": captions["current_caption"]["label"] + " YoY",
                 "values": [None if v is None else round(v, 1) for v in dep_current_yoy],
                 "color": "RED"},
                {"name": "总收入 YoY",
                 "values": [None if v is None else round(v, 1) for v in long_revenue_yoy],
                 "color": "NAVY"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "end_label": True,
            "ylab": "同比增速",
            "note": (
                ("折旧同比已连续多季高于收入同比；" if dep_streak >= 2 else
                 "折旧同比本季高于收入同比；" if dep_streak == 1 else "折旧同比本季不高于收入同比；")
                + f"当季 CapEx 是折旧的 {capex_values[-1] / dep_values[-1]:.1f} 倍"
                + ("，意味着这条线的上行才刚开始。" if capex_values[-1] > dep_values[-1] else "。")
                + "<b>这张图上有两条折旧线，不是一条线断了。</b>"
                "现金流量表上这个科目 2023 年之前叫「折旧与减值」、之后叫「折旧」，"
                f"两个口径在 {overlap_words}重叠，值是 "
                + "/".join(f"{old_at[k]:,.0f}" for k in overlap) + " 对 "
                + "/".join(f"{new_at[k]:,.0f}" for k in overlap) + " —— "
                "差的那一截是办公场地减值。把它们接成一条，会把 2023 年的一次性减值"
                "画成折旧的跳升，所以本站画两条、让重叠段自己说话。"
            ),
            "src_extra": source_note("季度折旧来自各期 10-Q / 10-K 现金流量表，第四季按全年减前三季倒推"),
        },
        {
            "kind": "lines",
            "title": (
                f"美国收入同比 {long_geography_yoy[us][-1]:+.0f}%，"
                + (("与其余地区的差距在" + ("拉大" if leads[-1] > leads[-2] else "收窄"))
                   if round(leads[-1], 1) > 0 else f"与{spaced(fastest)}持平" if round(leads[-1], 1) == 0
                   else f"慢于{spaced(fastest)}")
            ),
            "xlabels": long_labels[yoy_from:],
            "xstep": LONG_STEP,
            "series": [
                {"name": "美国", "values": long_geography_yoy["美国"], "color": "NAVY"},
                {"name": "EMEA", "values": long_geography_yoy["EMEA"], "color": "MBLUE"},
                {"name": "APAC", "values": long_geography_yoy["APAC"], "color": "GOLD"},
                {"name": "其他美洲", "values": long_geography_yoy["其他美洲"], "color": "GRAY"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "zero_base": True,
            "end_label": True,
            "ylab": "同比增速",
            "note": (
                (f"美国同比已连续{cn_count(us_accel)}季加速，" if us_accel >= 2 else "")
                + (f"本季比其余三个地区里最快的{spaced(fastest)}（{long_geography_yoy[fastest][-1]:+.1f}%）"
                   f"高 {leads[-1]:.1f}pp，" if round(leads[-1], 1) > 0 else
                   f"本季与{spaced(fastest)}（{long_geography_yoy[fastest][-1]:+.1f}%）持平，"
                   if round(leads[-1], 1) == 0 else
                   f"本季落后于{spaced(fastest)}（{long_geography_yoy[fastest][-1]:+.1f}%），")
                + f"占总收入 {us_share:.1f}%；"
                "地域集中度与 AI 基础设施客户的集中度是同一件事的两个视角。"
                + ((f"<b>拉到{cn_count(years)}年才看得出这次领先没有先例</b>：{geo_quarters[0][:4]} 年有同比以来，"
                    f"美国跑赢其余全部三个地区的季度此前有 {len(ahead)} 个（"
                    + ranges_text(geo_quarters, ahead) + "），"
                    f"领先最多的一次是 {geo_quarters[max(ahead, key=lambda i: leads[i])]} 的 "
                    f"{max(leads[i] for i in ahead):.1f}pp。")
                   if leads[-1] > 0 and leads[-1] >= max(leads) and ahead else "")
            ),
            "src_extra": source_note(
                "分地域收入逐季来自各期 10-Q / 10-K 的 srt:StatementGeographicalAxis 维度事实"
                "（第四季按全年减前三季倒推）；同比为自算"),
        },
    ]

    exhibits = number_exhibits(settled_charts + highlights + next_charts + routine)
    next_table_number = len(exhibits) + 2

    def line_cells(entry: dict, value: float) -> list[str]:
        return [f"{entry['tier']}：{'≥' if entry['direction'] == 'up' else '≤'} "
                f"{unit_text(entry['unit'], entry['threshold'])} 为安全侧",
                unit_text(entry["unit"], value),
                (f"{headroom(entry['direction'], entry['threshold'], value):+.1f}%"
                 if entry["threshold"] != 0 else "—（阈值为零）")]

    def row_table(title: str, rows: dict, lines: list[dict], read: dict, extra: dict, head: str,
                  result) -> dict:
        """Every row of one analysis's section 8: its words, the lines split out of it, their
        reading and what became of it -- the conditions and gated rows included."""
        body = []
        for number, row in rows.items():
            original = [str(number), row["name"], row["threshold_text"]]
            for entry in [entry for entry in lines if entry["row"] == number]:
                value = read[entry["id"]][1][-1]
                body.append(original + line_cells(entry, value) + [result(entry)])
            for cells in extra.get(number, []):
                body.append(original + cells)
        return {"n": 0, "title": title,
                "headers": ["行", "指标（原文）", "阈值（原文）", "拆出的线", head, "余量 D", "结果"],
                "rows": body}

    prior_extra: dict[int, list[list[str]]] = {}
    for entry in prior_retired:
        prior_extra.setdefault(entry["row"], []).append(
            line_cells(entry, prior_now(entry)) + [f"未触发；已退役：{entry['why']}"])
    for item, reading, verdict in condition_results:
        prior_extra.setdefault(item["row"], []).append(["条件", reading, "—", verdict])
    next_extra: dict[int, list[list[str]]] = {}
    for item, reading, verdict in next_condition_results:
        next_extra.setdefault(item["row"], []).append(["条件", reading, "—", f"当前：{verdict}"])
    for item in gated:
        next_extra.setdefault(item["row"], []).append(["待披露", "—", "—", item["why"]])

    tables = [
        row_table(f"上季（{prior_kpi['set_in']}）本地分析第 8 节 {len(prior_rows)} 行与本季结算",
                  prior_rows, prior_lines, prior_read, prior_extra, f"{period} 读数",
                  lambda entry: prior_state[entry["id"]]),
        row_table(f"本季（{period}）本地分析第 8 节 {len(next_rows)} 行：下季阈值与当前值",
                  next_rows, next_lines, next_read, next_extra, "当前值",
                  lambda entry: "当前在另一侧" if unsafe(entry, next_now(entry)) else "当前在安全侧"),
    ]
    tables.append({
        "n": 0,
        "title": f"{cn_count(len(periods))}季度基础数据（前四季只用于计算同比）",
        "headers": ["季度", "总收入", "Search & other", "YouTube ads", "Cloud",
                    "折旧", "经营现金流", "CapEx", "自由现金流 D", "美国", "EMEA", "APAC", "其他美洲"],
        "rows": [
            [
                p,
                f"${q['revenue_total'][i]:,.0f}M",
                f"${q['search_and_other'][i]:,.0f}M",
                f"${q['youtube_ads'][i]:,.0f}M",
                f"${q['cloud'][i]:,.0f}M",
                f"${q['depreciation'][i]:,.0f}M",
                f"${q['operating_cash_flow'][i]:,.0f}M",
                f"${q['capital_expenditures'][i]:,.0f}M",
                (lambda v: f"-${abs(v):,.0f}M" if v < 0 else f"${v:,.0f}M")(
                    q["operating_cash_flow"][i] - q["capital_expenditures"][i]
                ),
                f"${q['geography_usd_m']['美国'][i]:,.0f}M",
                f"${q['geography_usd_m']['EMEA'][i]:,.0f}M",
                f"${q['geography_usd_m']['APAC'][i]:,.0f}M",
                f"${q['geography_usd_m']['其他美洲'][i]:,.0f}M",
            ]
            for i, p in enumerate(periods)
        ],
    })
    if snapshot is not None:
        tables.append({
            "n": 0,
            "title": f"关键指标一览（{column_periods[2]} vs {column_periods[1]} vs {column_periods[0]}）",
            "headers": ["指标", column_periods[0], column_periods[1], column_periods[2],
                        "QoQ", "YoY", "来源"],
            "rows": snapshot_rows,
        })
    tables.append(cross_capex_table(0))
    for offset, table in enumerate(tables):
        table["n"] = next_table_number + offset

    # ── the lines the page leads with ───────────────────────────────────────
    revenue_record = revenue_now >= max(long_revenue)
    operating_record = seg["oi_total"][-1] >= max(seg["oi_total"])
    cloud_margin_record = cloud_opm_now >= max(opm_record)
    cloud_revenue_record = long_cloud[-1] >= max(long_cloud)
    buyback = q["repurchases_of_stock"]
    zero_run = 0
    for value in reversed(buyback):
        if value != 0:
            break
        zero_run += 1
    pressures = []
    if fcf_now < 0:
        pressures.append(f"单季自由现金流{'转负' if fcf_before >= 0 else '仍为负'} {money_bn(fcf_now)}")
    if zero_run >= 2:
        pressures.append(f"回购连续{cn_count(zero_run)}季归零")
    elif zero_run == 1:
        pressures.append("回购归零")
    if equity_raised > 0:
        pressures.append(f"发行普通股与强制可转优先股 {money_bn(equity_raised)}")
    if len(guided) > 1 and raises:
        pressures.append(f"FY{guided_year} CapEx 指引{guide_move}")
    reaction = (f"财报当日股价 {consensus['post_earnings_price_change_pct']:+.1f}%"
                if consensus and "post_earnings_price_change_pct" in consensus else "")
    sold_off = bool(consensus) and consensus.get("post_earnings_price_change_pct", 0) < 0
    headline = (
        ("经营端交出史上最强一季——" if revenue_record and operating_record else "经营端：")
        + f"收入 {revenue_yoy[-1]:+.1f}%、Cloud {cloud_yoy_now:+.1f}%"
        + (f" 且利润率创 {cloud_opm_now:.2f}% 新高；" if cloud_margin_record else
           f"、利润率 {cloud_opm_now:.2f}%；")
        + (("但市场交易的是另一件事：" if sold_off else "另一面：") + "、".join(pressures)
           + (f"，{reaction}。" if reaction else "。")
           if pressures else (f"{reaction}。" if reaction else ""))
    )

    opm_streak = rising_streak(long_cloud_opm, 2)
    drop = (1 - add_now / add_before) * 100 if add_before else None
    cards = []
    cards.append(
        '<article><span>' + ("亮点" if cloud_revenue_record and cloud_margin_record else "观察") + '</span>'
        + ("<b>Cloud 收入与利润率同步创新高</b>" if cloud_revenue_record and cloud_margin_record
           else "<b>Cloud 收入与利润率</b>")
        + f"<p>${long_cloud[-1] / 1000:.1f}B、同比 {cloud_yoy_now:+.1f}%；OPM {cloud_opm_now:.2f}%，"
        + (f"连续{cn_count(opm_streak)}季上行。" if opm_streak >= 2 else
           "本季上行。" if opm_streak == 1 else "本季没有上行。")
        + "</p></article>")
    # Cash and capital: the other half of the quarter's contradiction.
    if fcf_now < 0 or buyback[-1] == 0 or equity_raised > 0:
        funded = [words for words, amount in (("发股", equity_raised), ("发债", debt_raised)) if amount > 0]
        cards.append(
            "<article><span>存疑</span><b>"
            + ("单季自由现金流为负，" if fcf_now < 0 else "")
            + ("回购归零" if buyback[-1] == 0 else "回购继续")
            + ((f"，靠{'与'.join(funded)}补上" if fcf_now < 0 else f"，同时{'与'.join(funded)}") if funded else "")
            + "</b><p>"
            + f"FCF {money_bn(fcf_now)}；回购 {money_m(buyback[-1])}"
            + (f"；发行普通股与强制可转优先股 {money_bn(equity_raised)}" if equity_raised > 0 else "")
            + (f"、净发债 {money_bn(debt_raised)}" if debt_raised > 0 else "")
            + "。</p></article>")
    if backlog_record and add_fell and drop is not None:
        backlog_tag, backlog_head = "存疑", f"backlog 新高，净增却降 {drop:.0f}%"
    elif backlog_record:
        backlog_tag, backlog_head = "亮点", "backlog 新高，净增也在扩大"
    else:
        backlog_tag, backlog_head = "观察", "backlog 未创新高"
    cards.append(
        f"<article><span>{backlog_tag}</span><b>{backlog_head}</b>"
        + f"<p>${level_now:.0f}B；净增 ${add_before:.0f}B → ${add_now:.0f}B。"
        + story.get("backlog_brief", "") + "</p></article>")
    cards.append(
        f"<article><span>{'亮点' if search_pace == '加快' else '观察'}</span>"
        + (f"<b>Search {search_pace} {abs(search_step):.1f}pp</b>" if search_pace != "持平"
           else "<b>Search 增速与上季持平</b>")
        + f"<p>{search_yoy_now:+.1f}%，上季 {long_search_yoy[-2]:+.1f}%。"
        + story.get("search_brief", "") + "</p></article>")
    brief = (f'<h4>本季{cn_count(len(cards))}条主线</h4><div class="takeaway-grid">'
             + "".join(cards) + '</div>')

    ttm_note = "TTM 自由现金流按各季经营现金流减资本开支滚动四季自算。"
    if errata is not None:
        claimed = errata["ttm_fcf_recorded_for"]
        actual = errata["recorded_value_is_for"]
        at = {quarter_key(p) if " " in p else p: v for p, v in zip(quarters, long_ttm_fcf)}
        recorded = at[quarter_key(actual)]
        true_value = at[quarter_key(claimed)]
        ttm_note += (f"本地分析稿曾记 {claimed} 的 TTM 为 ${recorded:,.0f}M、同比 "
                     f"{change(ttm_fcf_cur, recorded)}；按 10-Q 逐季倒推，${recorded:,.0f}M 实为 {actual} 的 TTM，"
                     f"{claimed} 应为 ${true_value:,.0f}M，同比 {change(ttm_fcf_cur, true_value)}。本页采用后者。")

    parts = ["上季兑现", "本季重点", "下季跟踪", "长期常规"]
    notes = [
        f"本页按「{' → '.join(parts)}」{cn_count(len(parts))}段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
    ]
    # The two overview charts' own numbers, read after numbering: section one
    # now opens with the follow-up chart, so its first exhibit is not the one
    # carrying thresholds.
    notes.append(f"Exhibit {prior_overview['n']} 与 Exhibit {next_overview['n']} 的阈值（及两图其后逐条的线）是本地"
                 "研究设定，前者取自上季、后者取自本季本地分析第 8 节，不是公司指引，也不构成评级或投资建议；"
                 "「距阈值余量」统一为正值代表安全侧。")
    notes += [
        "本页只发布公司披露值、可复算的简单派生值，以及明确标注的市场预期；D 标记代表 Derived / 自算。",
        "市场预期一律标注为「市场预期」并给出取数时点，不写卖方机构名，也不发布评级、目标价或估值。",
    ]
    if eps_values and ex_values:
        notes.append(f"${ex_values[-1]:.2f} 仅做 ${eps_values[-1]:.2f} − ${round(eps_values[-1] - ex_values[-1], 2):.2f} 的算术拆分，不命名为经营 EPS，也不等同公司定义的 non-GAAP 指标。")
    notes += [
        ttm_note,
        "Cloud backlog 来自各期 10-Q / 10-K 的剩余履约义务附注"
        + (f"（{period} 为电话会口径）" if backlog_quarters[-1] in backlog.get("from_call", []) else "")
        + "；公司未披露取消额、外汇调整或客户集中度。",
        "Q4 2025 总收入采用当季 earnings release 的 $113,828M；与最新 10-K 倒挤值存在 $1M 差异。",
        f"同比曲线都用各自的完整季度记录计算（总收入同比另借 {int(quarters[0][:4]) - 1} 年四季作分母，"
        f"所以从 {quarters[0]} 起就有值）；核对表另列最近{cn_count(len(periods))}季的逐季原值。",
        f"季度值来自各期 10-Q 与 10-K；无 10-Q 的第四季度按「全年 − 前三季」倒推，{period} 采用当季 earnings release。",
        "本页已知未接入：收入成本 / R&D / S&M / G&A 四条费用线、有效税率的长序列、稀释股数、paid clicks 与 CPC，以及电话会口径的 Gemini、订阅、Waymo 等运营 KPI。",
    ]

    if len(guided) > 1:
        move = ("上调" if mids[-1] > mids[-2] else "下调" if mids[-1] < mids[-2] else "维持")
        guide_words = (f"{capex_guide['calls'][guided[-1]]}把 FY{guided_year} 的区间从 ${lows[-2]}–{highs[-2]}B "
                       f"{move}到 ${lows[-1]}–{highs[-1]}B（见第二板块）")
    else:
        guide_words = f"FY{guided_year} 的区间是 ${lows[-1]}–{highs[-1]}B（见第二板块）"
    descriptions = {
        "settled": (
            f"先结算上季（{prior_kpi['set_in']}）本地分析留下的：文末 {len(items)} 条待验证问题，按本季分析第 0 节的"
            f"判定计数；第 8 节「关键观察指标」{len(prior_rows)} 行，写成数的拆成 {len(prior_lines)} 条线"
            f"（一行写了几档就拆几条）逐条对本季申报读数，{len(priced)} 条有百分比余量、进总览，有长序列的逐条画出"
            + (f"；{len(prior_retired)} 条已被本季分析判定失效退役，照样结算，只是不进总览" if prior_retired else "")
            + (f"；写不成一个数的 {len(prior_conditions)} 行按条件判定" if prior_conditions else "")
            + "。Alphabet 不发季度财务指引；它唯一给数的指引是全年资本开支——" + guide_words
            + "，要到年末才能结算，所以本节没有公司指引兑现图。"
        ),
        "quarter_highlights": (
            f"本季（{period}）本地分析第 1、3、7 节里能用申报数画的结论，一图一个：" + "、".join(topics) + "。"
            "美国收入领先其余三个地区（分析 3.3 节）画在第四板块的地域图里。"
            + (fill_story(story["undrawn"], {"tax_rate_now": f"{tax_rate_ex_gains():.1f}%"})
               if story.get("undrawn") else "")
        ),
        "next_quarter": (
            f"本季（{period}）本地分析第 8 节「关键观察指标」{len(next_rows)} 行，看 {next_kpi['for_period']}："
            f"写成数的拆成 {len(next_lines)} 条线，{len(next_priced)} 条有百分比余量、进总览（当前值离阈值多远），"
            "有长序列的逐条画出"
            + ("；按序列判定的条件 " + str(len(next_condition_results)) + " 行——" + "；".join(
                f"第 {item['row']} 行{spaced(item['short'])}：{reading}，当前{verdict}"
                for item, reading, verdict in next_condition_results) if next_condition_results else "")
            + ("；要等之后的披露才能结算的 " + str(len(gated)) + " 行——" + "；".join(
                f"第 {item['row']} 行{spaced(item['short'])}：{item['why']}" for item in gated) if gated else "")
            + "。"
        ),
        "routine": "GOOGL 专属的常规序列：总量增长、资本强度、折旧与现金转换、地域结构。",
    }
    counts = [len(settled_charts), len(highlights), len(next_charts), len(routine)]
    sections, start = [], 0
    for (section_id, title), count in zip(SECTIONS, counts):
        sections.append({"id": section_id, "title": title, "description": descriptions[section_id],
                         "exhibits": exhibits[start:start + count]})
        start += count

    return {
        "schema_version": "quarterly-dashboard/googl-v3",
        "page": {"slug": "googl", "language": "zh-CN"},
        "company": {
            "ticker": "GOOGL",
            "name": "Alphabet",
            "group": "internet",
            "accounting_standard": "US GAAP",
        },
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · GOOGL",
        "title": f"Alphabet (GOOGL)：{period} 季报仪表盘",
        "subtitle": (f"截至 {latest['period_end']} · 发布 {latest['release_date']} · US GAAP · "
                     f"{AUDIT_WORDS[latest['audit_status']]} · 金额单位为 $M，另有注明除外"),
        "headline": headline,
        "brief": brief,
        "source": source,
        "source_url": "https://abc.xyz/investor/",
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": sections,
        "tables": tables,
        "notes": notes,
        "footer": (
            "GOOGL quarterly results · 数据来自 Alphabet 公开披露与本地已核对分析稿 · "
            "仅供研究，不构成投资建议"
        ),
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "googl.js"), payload, "googl")
    shell_dir = ROOT / "googl"
    shell_dir.mkdir(exist_ok=True)
    # Rendered here, not at import: the shell stamps the payload's content
    # hash into its <script src>, so it has to be built after write_dash.
    (shell_dir / "index.html").write_text(
        render_shell("GOOGL", "googl"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"GOOGL page: {charts} charts in {len(payload['sections'])} sections + "
          f"{len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
