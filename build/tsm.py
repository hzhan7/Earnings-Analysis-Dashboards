#!/usr/bin/env python3
"""Build the TSMC quarterly-results page.

Same four-part, chart-led shape as the GOOGL page (上季兑现 → 本季重点 →
下季跟踪 → 长期常规), but the routine series are the ones that actually decide
this company: volume vs price, node and platform mix, guidance delivery and
capital intensity.

The public payload contains only TSMC-reported figures, clearly labelled market
expectations, and arithmetic reproducible from the audit tables.

Rolling a quarter is a data edit (see CLAUDE.md §9): every period label, count
and figure in the prose below is computed from ``series/tsm.json``. What
belongs to one quarter only -- the snapshot columns, the latest declared
dividend, this call's guidance and full-year outlook, the market expectation, a
one-off in net income, the follow-up closure, the thresholds, the call's own
readings -- sits in blocks
stamped with that quarter and read through ``board.stamped_block``; a block
stamped with another quarter stops the build, an absent one leaves its part of
the page out. Every "all / never / first / only" sentence is printed only while
the data still says so.
"""

from __future__ import annotations

import json
import math
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import (  # noqa: E402
    ai_capex_cycle_table,
    cn_count,
    delivery_band,
    fill_story,
    headroom,
    headroom_exhibit,
    latest_block,
    midpoint_deviation,
    number_exhibits,
    stamped_block,
    threshold_exhibit,
    threshold_table,
    unit_text,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "tsm.json"

# One x label per year. Forty-two quarterly labels at 90 degrees turn every axis
# on this page into a hairbrush, and the reader navigates all of them by year.
LONG_STEP = 4
DATA_DIR = ROOT / "data"

# The quarter operating margin started clearing its upper bound as a habit. It
# is the page's reading of a pricing-power regime, not a figure that moves with
# a roll; the counts measured from it are recomputed every build.
REGIME_START = "2023Q1"

# The quarter from which TSMC's own "advanced technologies" aggregate and this
# page's summed 2/3/5/7nm line share one definition (its last redefinition).
ADVANCED_BASIS_FROM = "2021Q1"

# The two stretches the inventory-days sentence compares: before the 2021 build
# cycle and from it on. Fixed analytic windows, not quantities a roll changes.
INVENTORY_EARLY = ("2016Q1", "2019Q4")
INVENTORY_LATE_FROM = "2021Q1"


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100


def compact_period(period: str) -> str:
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


def iso_period(period: str) -> str:
    """``'Q2 2026'`` → ``'2026Q2'``, the spelling the long record uses."""
    quarter, year = period.split()
    return f"{year}{quarter}"


def deck_short(period: str) -> str:
    """``'Q2 2026'`` → ``'2Q26'``, the way TSMC names its own reports."""
    quarter, year = period.split()
    return f"{quarter[1]}Q{year[-2:]}"


def per_share_text(value: float) -> str:
    """``7.0`` → ``'7.0'``, ``7.25`` → ``'7.25'``: a per-share amount the way
    TSMC's board resolutions print it (one decimal unless it needs two)."""
    text = f"{value:.2f}"
    return text[:-1] if text.endswith("0") else text


def declared_dividend_annual(dividend: dict) -> float:
    """Annualised dividend in NT$B: the latest declared quarterly amount per
    share × 4 × shares outstanding (thousands), not the cash paid this quarter,
    which is the dividend declared two quarters earlier."""
    return dividend["per_share_ntd"] * 4 * dividend["shares_outstanding_thousands"] / 1e6


def quarter_word(period: str) -> str:
    """``'Q3 2026'`` → ``'Q3'``."""
    return period.split()[0]


def shift_period(period: str, step: int) -> str:
    """``shift_period('Q4 2026', 1)`` → ``'Q1 2027'``."""
    quarter, year = period.split()
    index = int(year) * 4 + int(quarter[1]) - 1 + step
    return f"Q{index % 4 + 1} {index // 4}"


MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def month_label(month: str) -> str:
    """``'2026-06'`` → ``'Jun-26'``."""
    year, number = month.split("-")
    return f"{MONTH_ABBR[int(number) - 1]}-{year[-2:]}"


def quarter_end_month(quarter: str) -> str:
    """``'2026Q2'`` → ``'2026-06'``."""
    year, number = quarter.split("Q")
    return f"{year}-{int(number) * 3:02d}"


def quarter_label(quarter: str) -> str:
    """``'2016Q1'`` → ``'Q1'16'``, matching `compact_period`'s output."""
    year, number = quarter.split("Q")
    return f"Q{number}'{year[-2:]}"


def leading_gap(values: list[float | None]) -> int:
    """Index of the first reported value; ``len(values)`` when there is none."""
    return next((i for i, value in enumerate(values) if value is not None), len(values))


def rounded(values: list[float | None], digits: int = 6) -> list[float | None]:
    """Round for the payload so a rebuild is idempotent, keeping ``None`` holes."""
    return [None if value is None else round(value, digits) for value in values]


def spaced(word: str) -> str:
    """A word that opens with Latin letters or digits gets a space after Chinese
    text (「归因于 N2 爬坡备货」); a Chinese one does not."""
    return f" {word}" if word[:1].isascii() and word[:1].isalnum() else word


def joined(names: list[str]) -> str:
    """「毛利率与营业利润率」「A、B 与 HPC mix」: the last 「与」 is spaced the way
    the page spaces Chinese against Latin text."""
    if len(names) == 1:
        return names[0]
    head = "、".join(names[:-1])
    last = names[-1]
    left = " " if head[-1:].isascii() and head[-1:].isalnum() else ""
    right = " " if last[:1].isascii() and last[:1].isalnum() else ""
    return f"{head}{left}与{right}{last}"


def usd_range(values: list[float]) -> str:
    """``[60, 64]`` → ``'US$60–64B'``; a single-figure outlook reads ``'US$56B'``."""
    low, high = values
    return f"US${low}B" if low == high else f"US${low}–{high}B"


def trim(value: float) -> str:
    """``66.0`` → ``'66'``, ``66.5`` → ``'66.5'``: a midpoint at the precision it has."""
    return f"{value:.1f}".rstrip("0").rstrip(".")


def cn_share(share: float) -> str:
    """The nearest simple fraction, in words: 0.66 → 「三分之二」, 0.52 → 「一半」."""
    choices = [(1 / 10, "十分之一"), (1 / 5, "五分之一"), (1 / 4, "四分之一"), (1 / 3, "三分之一"),
               (1 / 2, "一半"), (2 / 3, "三分之二"), (3 / 4, "四分之三")]
    return min(choices, key=lambda choice: abs(share - choice[0]))[1]


def cn_fraction_above(value: float) -> str:
    """A share of revenue as the simple fraction it clears: 0.684 → 「三分之二以上」."""
    for share, words in ((3 / 4, "四分之三"), (2 / 3, "三分之二"), (1 / 2, "一半"),
                         (1 / 3, "三分之一"), (1 / 4, "四分之一")):
        if value >= share:
            return f"{words}以上"
    return f"{value * 100:.0f}%"


def resolve_exhibit_refs(exhibits: list[dict]) -> list[dict]:
    """Substitute ``{ref}`` placeholders with the numbers `number_exhibits` assigned.

    Cross-references written as literal numbers break the moment a chart is
    inserted, and the page already refuses to hand-number the exhibits
    themselves; captions that point at them must follow the same rule.
    """
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


def html_text(text: str) -> str:
    """Report wording for a raw-innerHTML slot (an exhibit note or source).

    The local analyses write their thresholds with bare operators (「< 63% =
    Q1 是周期高点」). In markup a bare ``<`` is the start of a tag to every
    tag-stripping reader, including this repo's own scans, so it is escaped
    here; the escaped slots (titles, descriptions) take the text as it is."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── Threshold records ─────────────────────────────────────────────────────────
# A threshold in the series names the record it is read against (`reads`),
# never the reading itself: this quarter's value is taken off the end of that
# record at build time, so a roll cannot leave last quarter's number under this
# quarter's line, and an entry that names a record this builder does not know
# stops the build instead of silently dropping its chart.

def half_year_capex(long: dict) -> tuple[list[str], list[float]]:
    """First-half capital expenditure, US$B: TSMC's own dollar figures for Q1 and
    Q2 added, one point per year whose two quarters are both in the record."""
    by_quarter = dict(zip(long["quarters"], long["capital_intensity"]["capex_usd_bn"]))
    labels, values = [], []
    for year in sorted({quarter[:4] for quarter in long["quarters"]}):
        first, second = by_quarter.get(f"{year}Q1"), by_quarter.get(f"{year}Q2")
        if first is None or second is None:
            continue
        labels.append(f"1H{year[-2:]}")
        values.append(round(first + second, 6))
    return labels, values


def kpi_history(staging: dict, reads: str) -> tuple[list[str], list[float | None], dict]:
    """(x labels, values, chart spec) of the record a threshold entry reads.

    Node rows are summed the way the process-mix chart sums them: a node with no
    row in the company's table counts as nothing, and a quarter in which none of
    the summed rows existed stays empty rather than reading as 0%."""
    long = staging["long_history"]
    labels = [quarter_label(quarter) for quarter in long["quarters"]]
    tech = long["technology_mix_pct"]

    def summed(*nodes: str) -> list[float | None]:
        return [None if all(tech[node][i] is None for node in nodes)
                else sum(tech[node][i] or 0 for node in nodes) for i in range(len(labels))]

    born = long["node_first_reported"]

    def first_halves() -> tuple[list[str], list[float], dict]:
        halves, sums = half_year_capex(long)
        return halves, sums, {
            "fmt": "usd1", "ylab": "US$B", "name": "上半年 CapEx 累计 D", "per": "个上半年",
            # The reading is a half-year, so it is named, not called 「本季」.
            "now": halves[-1],
            "source": ("美元 CapEx 逐季读自各季 quarterly management report「V. Capital Expenditures」"
                       "的美元表，上半年累计为 Q1 与 Q2 相加（D）；")}

    histories = {
        "gross_margin": lambda: (labels, long["financials"]["gross_margin_pct"], {
            "fmt": "pct1", "ylab": "毛利率", "name": "毛利率", "per": "季",
            "source": "毛利率逐季读自各季 6-K 的合并损益表，公司印到一位小数；"}),
        "h1_capex_usd": first_halves,
        "n3_n5_share": lambda: (labels, summed("3nm", "5nm"), {
            "fmt": "pct0", "ylab": "晶圆收入占比", "name": "3nm + 5nm D", "per": "季",
            "source": ("制程占比逐季读自各季 earnings release 与 management report 的 Wafer Revenue by "
                       f"Technology，3nm + 5nm 为两行相加（D）；5nm 那一行 {born['5nm']} 才出现在公司表上"
                       f"（3nm 是 {born['3nm']}），之前留空；")}),
    }
    if reads not in histories:
        raise ValueError(f"a threshold entry reads {reads!r}, which build/tsm.py does not know")
    return histories[reads]()


def settle_verdict(entry: dict, values: list[float | None]) -> str:
    """How this quarter's reading stands against a line set last quarter.

    「守住」 and 「击穿」 describe a line the metric was on the safe side of when it
    was set; a line set above where the metric stood is a target, and it is
    「达到」 or 「仍未达到」 -- calling that 「击穿」 would say a floor broke that
    the metric had never stood on."""
    readings = [value for value in values if value is not None]
    safe_now = headroom(entry["direction"], entry["threshold"], readings[-1]) >= 0
    safe_before = len(readings) > 1 and headroom(entry["direction"], entry["threshold"], readings[-2]) >= 0
    if safe_now:
        return "守住" if safe_before else "达到"
    return "击穿" if safe_before else "仍未达到"


def safe_run(entry: dict, values: list[float | None]) -> int:
    """How many readings in a row, up to this one, sit on the safe side of the line."""
    run = 0
    for value in reversed(values):
        if value is None or headroom(entry["direction"], entry["threshold"], value) < 0:
            break
        run += 1
    return run


def delivery_words(actual: float, low: float, high: float, unit: str = "pp") -> str:
    """Where a reported figure landed against its own guided range, at the
    precision the company prints (a figure on the bound is inside it)."""
    if actual > high:
        return f"高于上端 {actual - high:.1f}{unit} D"
    if actual < low:
        return f"低于下端 {low - actual:.1f}{unit} D"
    return "区间上端" if actual == high else "区间内"


def expectation_chart(staging: dict, consensus: dict, snapshot: dict,
                      bridge: dict | None) -> dict:
    """Reported beat versus core beat, against the same market expectation.

    The page's other guidance charts ask whether the quarter cleared the
    company's own bar. This asks whether it cleared the market's -- and when
    the quarter carries a one-off, it is the one place where the answer changes
    depending on which profit line you use. Both are plotted so the reader sees
    the gap rather than being told about it; a quarter without a one-off plots
    the reported lines only.
    """
    financials = staging["financials"]
    reported_net = snapshot["net_income_ntd_bn"][0]
    reported_eps = financials["eps_ntd"][-1]
    rows = [
        ("营收（US$）", pct_change(financials["revenue_usd_bn"][-1], consensus["revenue_usd_bn"])),
        ("营收（NT$）", pct_change(snapshot["revenue_ntd_bn"][0], consensus["revenue_ntd_bn"])),
        ("毛利率（pp）", financials["gross_margin_pct"][-1] - consensus["gross_margin_pct"]),
        ("报告净利", pct_change(reported_net, consensus["net_income_ntd_bn"])),
        ("报告 EPS", pct_change(reported_eps, consensus["eps_ntd"])),
    ]
    headline = pct_change(reported_eps, consensus["eps_ntd"])
    title = f"对市场预期：报告 EPS {'beat' if headline >= 0 else 'miss'} {headline:+.1f}%"
    note = "毛利率一项是百分点，其余是百分比，两类单位并列只用于比较方向与相对幅度。"
    src_core = ""
    if bridge is not None:
        values = bridge["values_ntd_bn"]
        core_net = values[2]
        # Core EPS is not disclosed: the one-off is a pre-tax non-operating gain,
        # so scaling reported EPS by the core/reported profit ratio is the only
        # arithmetic available and it is marked D like every other derived figure.
        core_eps = reported_eps * core_net / values[0]
        core_net_beat = pct_change(core_net, consensus["net_income_ntd_bn"])
        core = pct_change(core_eps, consensus["eps_ntd"])
        rows += [("核心净利 D", core_net_beat), ("核心 EPS D", core)]
        share = values[1] / (values[0] - consensus["net_income_ntd_bn"])
        title += f"，剔除一次性后{'只有' if abs(core) < abs(headline) / 2 else ''} {core:+.1f}%"
        clean = [label for label, value in rows[:3] if value > 0]
        note = (
            f"{bridge['one_off_description']} NT${values[1]:.2f}B 解释了净利超预期金额的"
            + ("绝大部分" if share >= 0.75 else "大部分" if share >= 0.5 else "一部分")
            + f"：剔除后核心净利较预期只有 {core_net_beat:+.1f}%。"
            + ("<b>干净的超预期在营收与毛利率，不在利润</b>。"
               if len(clean) == 3 and abs(core_net_beat) < 5 else "")
            + note
        )
        src_core = (f"核心净利 = 报告净利减一次性税前收益，未做税务调整；"
                    "核心 EPS 按核心 / 报告净利之比折算报告 EPS，均为自算，不是公司定义的调整后指标。")
    return {
        "ref": "EX_EXPECTATION",
        "kind": "diverging_bars",
        "title": title,
        "xlabels": [label for label, _ in rows],
        "values": [round(value, 2) for _, value in rows],
        "legend": "较市场预期",
        "positive_label": "高于市场预期",
        "negative_label": "低于市场预期",
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "% 或 pp",
        "zero_line": True,
        "note": note,
        "src_extra": (
            f"实际值来自 {staging['latest']['period']} earnings release / management report；"
            f"市场预期为财报前一致预期（{consensus['as_of']}），不具名。"
            + src_core
        ),
    }


def guidance_delivery_charts(staging: dict, guidance: dict | None) -> tuple[list[dict], dict]:
    """The full guided record for all three guided metrics, and what the beats are made of.

    TSMC guides three numbers every quarter -- revenue, gross margin, operating
    margin -- plus the exchange rate it assumed when setting them. The record
    runs back to 2016Q1, and its length is the point: read over the recent
    stretch only, operating margin had cleared its upper bound almost every
    quarter and neither revenue nor gross margin had broken the floor. Over the
    full record none of those statements survives. A hit rate counted inside
    one favourable window is not a hit rate.

    One basis break travels with the revenue series and is disclosed rather
    than smoothed: through 2017Q2 TSMC guided revenue in **NT dollars**, and
    from 2017Q3 in US dollars. The six NT$ quarters are shown in dollars by
    dividing the company's own guided range by the exchange-rate assumption
    printed in the same sentence -- a mechanical conversion, not two currencies
    spliced onto one axis. The decomposition below is unaffected: for those six
    quarters its operating leg is simply the beat against the NT$ range the
    company actually published.

    The beat decomposition is an identity rather than an estimate. Revenue is
    guided in US dollars at an FX assumption stated on the call and reported at
    the rate the quarter realised, so:

        (1 + dollar beat) = (1 + NT$ operating beat) x (assumption / realised)

    Every term is a company-reported quarterly number, so the split needs no
    monthly series and no market rate.
    """
    guide = staging["quarterly_guidance_history"]
    quarters = guide["quarters"]
    low = guide["guide_low_usd_bn"]
    high = guide["guide_high_usd_bn"]
    midpoint = {
        quarter: (lo + hi) / 2 for quarter, lo, hi in zip(quarters, low, high)
    }
    guide_fx = dict(zip(quarters, guide["guide_fx_ntd_per_usd"]))
    actual_fx = dict(zip(quarters, guide["actual_fx_ntd_per_usd"]))
    actual = dict(zip(quarters, guide["actual_revenue_usd_bn"]))

    finished = [quarter for quarter in quarters if actual[quarter] is not None]
    beats = {quarter: (actual[quarter] / midpoint[quarter] - 1) * 100 for quarter in finished}
    # The dollar band is the one chart here that cannot carry the whole record:
    # the guided number grows several-fold over it, and a band of about one per
    # cent at the left edge of a linear dollar axis is a few pixels tall. The
    # scale-free deviation chart beside it carries all of it.
    BAND_WINDOW = 16

    SOURCE_6K = (
        "指引区间与假设汇率来自各季法说会当场发布的 6-K；"
        "实际值来自随后一季 6-K 所载合并损益表。"
    )
    first_half_width = (high[0] - low[0]) / 2 / ((high[0] + low[0]) / 2) * 100
    band_slice = slice(len(quarters) - BAND_WINDOW, len(quarters))
    revenue_band = delivery_band(
        "EX_RANGE", "收入", quarters[band_slice], low[band_slice], high[band_slice],
        [actual[q] for q in quarters][band_slice],
        fmt="usd1", ylab="US$B", unit="US$B", src_extra=SOURCE_6K,
        scope=f"（本图仅近 {BAND_WINDOW} 季）",
        extra_note=(
            f"<b>这张只画最近 {BAND_WINDOW} 季，不是数据缺失</b>：本页的指引记录一路回到 "
            f"{quarters[0]}，而指引的收入从 US${low[0]:.1f}B 长到 US${high[-1]:.1f}B，"
            f"{cn_count(int(high[-1] / low[0]))}倍的量级差放在一根线性美元轴上，"
            f"早年那条 ±{first_half_width:.1f}% 宽的带子会被压成几个像素。"
            f"完整 {len(finished)} 季的同一问题改用与量级无关的口径回答，见 Exhibit {{EX_MIDPOINT}}。"
            "指引与实际都是公司自己给的美元数，而美元数是新台币结果除以当季实际汇率的产物，"
            "所以每一格里都含一条汇率腿 —— 拆开见 Exhibit {EX_LEGS}。"
        ),
    )

    gm_low, gm_high = guide["gross_margin_guide_low_pct"], guide["gross_margin_guide_high_pct"]
    gm_actual = guide["gross_margin_actual_pct"]
    gm_widths = {round(hi - lo, 6) for lo, hi in zip(gm_low, gm_high)}
    gm_below = [quarters[i] for i, value in enumerate(gm_actual)
                if value is not None and value < gm_low[i]]
    gm_below_years = sorted({quarter[:4] for quarter in gm_below})
    this_gm, next_gm_mid = gm_actual[-2], (gm_low[-1] + gm_high[-1]) / 2
    dilution = (guidance or {}).get("n2_gross_margin_dilution_pp")
    margin_band = delivery_band(
        "EX_GM", "毛利率", quarters, gm_low, gm_high, gm_actual,
        fmt="pct1", ylab="毛利率", unit="%", xstep=LONG_STEP,
        src_extra=SOURCE_6K + "实际毛利率 = 该季 6-K 合并损益表的毛利 ÷ 净销售额 D。",
        extra_note=(
            (f"区间宽度一律 {gm_widths.pop():g}pp，{len(quarters)} 季无一例外，公司从不给单点。"
             if len(gm_widths) == 1 else "")
            + (f"<b>但「从不跌破」是短窗口的错觉</b>：把记录拉到 {quarters[0]}，跌破下限的季度出现过"
               f"{cn_count(len(gm_below))}次，全部在 {gm_below_years[0]} 年到 {gm_below_years[-1]} 年"
               "那段产能与汇率同时逆风的时期。"
               if gm_below and not any(q in gm_below for q in finished[-8:]) else "")
            + f"本季 {this_gm:.1f}% "
            + (f"超出上限 {this_gm - gm_high[-2]:.1f}pp" if this_gm > gm_high[-2] else
               "落在区间内" if this_gm >= gm_low[-2] else f"跌破下限 {gm_low[-2] - this_gm:.1f}pp")
            + f"，而下季指引中值 {next_gm_mid:.1f}%"
            + (f"，管理层同时把 {guidance['n2_gross_margin_dilution_half']} 的 N2 稀释量化为 "
               f"{dilution[0]}–{dilution[1]}pp" if dilution else "")
            + (" —— 这条线的方向已经确定向下。" if next_gm_mid < this_gm else "。")
        ),
    )

    om_low, om_high = guide["operating_margin_guide_low_pct"], guide["operating_margin_guide_high_pct"]
    om_actual = guide["operating_margin_actual_pct"]
    om_done = [i for i, value in enumerate(om_actual) if value is not None]
    om_above = [i for i in om_done if om_actual[i] > om_high[i]]
    om_below = [i for i in om_done if om_actual[i] < om_low[i]]
    om_inside = len(om_done) - len(om_above) - len(om_below)
    regime = [i for i in om_done if quarters[i] >= REGIME_START]
    regime_above = [i for i in regime if om_actual[i] > om_high[i]]
    regime_on_bound = [i for i in regime if om_actual[i] == om_high[i]]
    regime_year = REGIME_START[:4]
    regime_reading = (
        f"按 {regime_year} 年起的那 {len(regime)} 季读，营业利润率"
        + ("<b>每一季都从上限穿出去</b>" if len(regime_above) == len(regime) else
           f"<b>{len(regime_above)} 季从上限穿出去、其余 {len(regime_on_bound)} 季恰好落在上限上</b>"
           if len(regime_above) + len(regime_on_bound) == len(regime) else
           f"有 {len(regime_above)} 季从上限穿出去")
    )
    floor_since_regime = not any(om_actual[i] < om_low[i] for i in regime)
    operating_band = delivery_band(
        "EX_OM", "营业利润率", quarters, om_low, om_high, om_actual,
        fmt="pct1", ylab="营业利润率", unit="%", xstep=LONG_STEP,
        src_extra=SOURCE_6K + "实际营业利润率 = 该季 6-K 合并损益表的营业利益 ÷ 净销售额 D。",
        extra_note=(
            f"<b>这张图是本次把窗口从 14 季拉到 {len(om_done)} 季后改动最大的一张。</b>"
            + regime_reading
            + ("，于是它看起来像一条底线而不是预测，「有没有超」这个问题根本不用问。"
               if floor_since_regime else "。")
            + f"整段记录不是这样：落在区间内的季度有 {om_inside} 个，跌破下限的有 {len(om_below)} 个。"
            + (f"<b>「指引是底线」是 {regime_year} 年以后才成立的性质，不是这家公司的固有属性</b> —— "
               "而那正好是它的定价权发生变化的同一段时间。"
               if floor_since_regime and om_below else "")
        ),
    )

    # ── Distance from the guided midpoint, one chart per guided metric ────────
    midpoint_chart = midpoint_deviation(
        "EX_MIDPOINT", "收入", quarters, low, high, guide["actual_revenue_usd_bn"],
        mode="pct", window=len(finished), xstep=LONG_STEP,
        label=lambda quarter: month_label(quarter_end_month(quarter)),
        axis_note="x 轴标的是该季最后一个月。",
        src_extra=SOURCE_6K + "偏离为实际收入除以指引中值的自算值。",
        extra_note=(
            "<b>柱高不是纯经营偏离</b> —— 指引按业绩会写明的<b>假设</b>汇率给出，"
            "实际收入按当季实际汇率折算，每根柱里都含一条汇率腿，拆开见 Exhibit {EX_LEGS}。"
        ),
    )
    # The two margins share the revenue guidance's FX assumption -- it is one
    # column in the same 6-K -- so their gaps carry an FX component too. The
    # direction is stated, not the size: TSMC publishes no sensitivity in these
    # filings and this page does not invent one.
    FX_SHARED = (
        "毛利率指引与收入指引写在同一份 6-K 里、共用同一个假设汇率，"
        "所以这条偏离同样含汇率成分（新台币比假设弱时对利润率是顺风）；"
        "哪几季顺风、哪几季逆风见 Exhibit {EX_LEGS} 的金色腿。"
        "本页不给汇率对利润率的敏感度系数 —— 这批 6-K 没有披露，不自行编造。"
    )
    gm_midpoint_chart = midpoint_deviation(
        "EX_GM_MIDPOINT", "毛利率", quarters, gm_low, gm_high, gm_actual,
        mode="pp", window=len(finished),
        xstep=LONG_STEP,
        label=lambda quarter: month_label(quarter_end_month(quarter)),
        axis_note="x 轴标的是该季最后一个月。",
        src_extra=(SOURCE_6K + "实际毛利率 = 该季 6-K 合并损益表的毛利 ÷ 净销售额 D；"
                   "偏离为实际值减指引中值的自算值。"),
        extra_note=FX_SHARED,
    )
    om_deviation = [om_actual[i] - (om_low[i] + om_high[i]) / 2 for i in om_done]
    om_positive = sum(1 for value in om_deviation if value > 0)
    regime_positive = all(om_actual[i] > (om_low[i] + om_high[i]) / 2 for i in regime)
    om_midpoint_chart = midpoint_deviation(
        "EX_OM_MIDPOINT", "营业利润率", quarters, om_low, om_high, om_actual,
        mode="pp", window=len(finished),
        xstep=LONG_STEP,
        label=lambda quarter: month_label(quarter_end_month(quarter)),
        axis_note="x 轴标的是该季最后一个月。",
        src_extra=(SOURCE_6K + "实际营业利润率 = 该季 6-K 合并损益表的营业利益 ÷ 净销售额 D；"
                   "偏离为实际值减指引中值的自算值。"),
        extra_note=(
            ("这一条的柱<b>全部为正</b>，与 Exhibit {EX_OM} 的「没有一季落回区间内」是同一件事的"
             "两种说法 —— 区间图已经饱和（每季都超上限，看不出多少），要读幅度只能看这张。"
             if om_positive == len(om_deviation) and om_inside == 0 and not om_below else
             f"这一条的柱 {len(om_deviation)} 根里 {om_positive} 根为正"
             + (f"；{regime_year} 年起的 {len(regime)} 根<b>全部为正</b>，与 Exhibit {{EX_OM}} 里那段"
                f"「{len(regime_above)} 季穿出上限、{len(regime_on_bound)} 季恰好落在上限」是同一件事的两种说法"
                " —— 那一段的区间图已经饱和，要读幅度只能看这张。"
                if regime_positive and regime else "。"))
            + FX_SHARED.replace("毛利率指引", "营业利润率指引")
        ),
    )

    # ── What the beat is made of ──────────────────────────────────────────────
    window = finished
    operating_leg = [
        (actual[quarter] * actual_fx[quarter] / (midpoint[quarter] * guide_fx[quarter]) - 1) * 100
        for quarter in window
    ]
    fx_leg = [(guide_fx[quarter] / actual_fx[quarter] - 1) * 100 for quarter in window]
    opposed = [
        quarter for quarter, one, two in zip(window, operating_leg, fx_leg) if one * two < 0
    ]
    flipped = [
        quarter for quarter, one in zip(window, operating_leg) if one * beats[quarter] < 0
    ]
    fx_dominant = [
        quarter for quarter, one, two in zip(window, operating_leg, fx_leg) if abs(two) > abs(one)
    ]
    headwind = sum(1 for value in fx_leg if value < 0)
    legs_chart = {
        "ref": "EX_LEGS",
        "kind": "grouped_bars",
        "title": (
            f"把收入超额拆成两条腿：{len(window)} 季里 {len(opposed)} 季方向相反，"
            + (
                f"{'、'.join(flipped)} 一季美元 beat 而新台币 miss"
                if len(flipped) == 1
                else f"{len(flipped)} 季两个口径给出相反结论"
            )
        ),
        "xlabels": [month_label(quarter_end_month(quarter)) for quarter in window],
        "xrot": 90,
        # 42 quarterly labels at 90 degrees turn the axis into a hairbrush; the
        # reader navigates this axis by year, so one label per year.
        "xstep": 4,
        "groups": [
            {"name": "新台币经营超额", "color": "NAVY", "values": rounded(operating_leg)},
            {"name": "汇率腿（假设 vs 实际）", "color": "GOLD", "values": rounded(fx_leg)},
        ],
        # 84 bars in one card cannot carry 84 labels without overlapping; the
        # numbers live one click away in this card's own table view.
        "bar_labels": False,
        "fmt": "pp1",
        "label_fmt": "pp1",
        "ylab": "pp",
        "note": (
            "这是 Exhibit {EX_MIDPOINT} 那根柱的拆解，不是新数据：公司在业绩会上同时给出收入区间和"
            "<b>假设汇率</b>，季报又按当季<b>实际汇率</b>折出美元收入，所以美元偏离恰好等于"
            "两项<b>相乘</b>（不是相加）—— 深蓝是新台币经营超额，金色是假设汇率相对实际汇率的差。"
            f"{len(window)} 季里 {len(opposed)} 季两条腿方向相反，但只有 {len(fx_dominant)} 季"
            "汇率腿盖过经营腿"
            + (
                f"（{flipped[0]}：美元口径 {beats[flipped[0]]:+.1f}%、新台币经营 "
                f"{operating_leg[window.index(flipped[0])]:+.2f}pp，整个超额来自假设 "
                f"{guide_fx[flipped[0]]:.1f} 而实际 {actual_fx[flipped[0]]:.3f}）"
                if flipped
                else ""
            )
            + f"；全记录里有 {headwind} 季汇率是<b>逆风</b>，美元口径反而低估了经营超额。"
        ),
        "src_extra": SOURCE_6K + "两条腿均为自算，原值见核对表。",
    }

    # 按指标分组（用户 2026-08 定）：一个指标的「区间 → 偏离」连着读完再换下一个，
    # 收入那条后面直接跟它专属的汇率拆解。跨指标的对照靠图注点名，不靠版面相邻 ——
    # 营业利润率那两张的图注各自写明了与另外两条指引的差别。
    charts = [
        revenue_band, midpoint_chart, legs_chart,
        margin_band, gm_midpoint_chart,
        operating_band, om_midpoint_chart,
    ]

    table = {
        "title": f"指引兑现全表（{len(quarters)} 季）：三项指引区间、汇率假设与超额分解",
        "headers": ["期间", "收入指引", "实际收入", "较中值",
                    "毛利率指引", "实际毛利率", "营业利润率指引", "实际营业利润率",
                    "假设汇率", "实际汇率", "经营超额 D", "汇率腿 D"],
        "rows": [],
    }
    for index, quarter in enumerate(quarters):
        reported = actual[quarter]
        realised = actual_fx[quarter]
        gm = gm_actual[index]
        om = om_actual[index]
        derived = reported is not None and realised is not None
        table["rows"].append([
            quarter,
            f"US${low[index]:.1f}–{high[index]:.1f}B",
            f"US${reported:.2f}B" if reported is not None else "—",
            f"{beats[quarter]:+.2f}% D" if reported is not None else "—",
            f"{gm_low[index]:.1f}–{gm_high[index]:.1f}%",
            f"{gm:.2f}% D" if gm is not None else "—",
            f"{om_low[index]:.1f}–{om_high[index]:.1f}%",
            f"{om:.2f}% D" if om is not None else "—",
            f"{guide_fx[quarter]:.1f}",
            f"{realised:.3f}" if realised is not None else "—",
            f"{(reported * realised / (midpoint[quarter] * guide_fx[quarter]) - 1) * 100:+.2f}pp D"
            if derived else "—",
            f"{(guide_fx[quarter] / realised - 1) * 100:+.2f}pp D" if derived else "—",
        ])

    return charts, table


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    fin = staging["financials"]
    return [f"Revenue ${fin['revenue_usd_bn'][-1]:.1f}B",
            f"HPC {staging['platform_mix_pct']['hpc'][-1]:.0f}%",
            f"Gross margin {fin['gross_margin_pct'][-1]:.1f}%"]


def check_stamps(staging: dict) -> dict:
    """Read every one-quarter block, refusing any that belongs to another quarter.

    Returns the blocks this quarter has; an absent one is None and the page
    leaves its part out.
    """
    period = staging["periods"][-1]
    blocks = {key: stamped_block(staging, key, period) for key in (
        "current_snapshot", "declared_dividend", "guidance", "market_expectation",
        "net_income_bridge", "capex_guidance_history", "guidance_delivery", "followup_closure",
        "prior_kpi_settlement", "next_kpi", "quarter_story")}
    if blocks["current_snapshot"] is None or blocks["next_kpi"] is None:
        raise ValueError("series blocks `current_snapshot` and `next_kpi` are required every quarter")
    following = shift_period(period, 1)
    guide = staging["quarterly_guidance_history"]
    if guide["quarters"][-1] != iso_period(following):
        raise ValueError(f"series block `quarterly_guidance_history` is stamped "
                         f"{guide['quarters'][-1]!r}, but the quarter after {period!r} is "
                         f"{iso_period(following)!r}: add this call's guidance with the roll")
    if staging["long_history"]["quarters"][-1] != iso_period(period):
        raise ValueError(f"series block `long_history` is stamped "
                         f"{staging['long_history']['quarters'][-1]!r}, but the series ends at "
                         f"{period!r}: extend it with the roll")
    if blocks["guidance"] and blocks["guidance"]["next_guide"]["quarter"] != following:
        raise ValueError(f"series block `guidance.next_guide` is stamped "
                         f"{blocks['guidance']['next_guide']['quarter']!r}, but the next quarter is "
                         f"{following!r}: update it or remove it")
    if blocks["next_kpi"]["for_period"] != following:
        raise ValueError(f"series block `next_kpi` is stamped for {blocks['next_kpi']['for_period']!r}, "
                         f"but the next quarter is {following!r}: update it with the roll")
    closure = blocks["followup_closure"]
    if closure and closure["set_in"] != shift_period(period, -1):
        raise ValueError(f"series block `followup_closure` closes questions stamped "
                         f"{closure['set_in']!r}, but last quarter was {shift_period(period, -1)!r}")
    if closure:
        for label, count in zip(closure["labels"], closure["counts"]):
            if len(closure["topics"].get(label, [])) != count:
                raise ValueError(f"series block `followup_closure` counts {count} {label!r} "
                                 f"but names {len(closure['topics'].get(label, []))}")
    prior = blocks["prior_kpi_settlement"]
    if prior and prior["set_in"] != shift_period(period, -1):
        raise ValueError(f"series block `prior_kpi_settlement` closes thresholds set in "
                         f"{prior['set_in']!r}, but last quarter was {shift_period(period, -1)!r}")
    hub = f"TSMC {period} quarterly"
    if not any(item["label"].startswith(hub) for item in staging["sources"]):
        raise ValueError(f"series `sources` has no entry labelled {hub + ' results'!r}: add this "
                         "quarter's results hub with the roll")
    return blocks


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    period = periods[-1]
    following = shift_period(period, 1)
    latest = latest_block(staging, period=period)
    blocks = check_stamps(staging)
    financials = staging["financials"]
    snapshot = blocks["current_snapshot"]
    guidance = blocks["guidance"]
    consensus = blocks["market_expectation"]
    net_income_bridge = blocks["net_income_bridge"]
    capex_guide = blocks["capex_guidance_history"]
    delivery = blocks["guidance_delivery"]
    closure = blocks["followup_closure"]
    next_kpi = blocks["next_kpi"]
    story = blocks["quarter_story"] or {}
    hub = next(item for item in staging["sources"]
               if item["label"].startswith(f"TSMC {period} quarterly"))

    source = (
        f'Source: <a href="{hub["url"]}" '
        f'rel="noopener">TSMC Investor Relations</a>（{deck_short(period)} earnings release、'
        'management report 与 earnings conference）。'
    )

    revenue_ntd_yoy = pct_change(snapshot["revenue_ntd_bn"][0], snapshot["revenue_ntd_bn"][2])
    capex_ntd_yoy = pct_change(
        snapshot["capital_expenditures_ntd_bn"][0], snapshot["capital_expenditures_ntd_bn"][2]
    )

    # ── The routine charts run on the ten-year record, not the eight ──────────
    # Eight quarters cannot show whether a mix shift is a trend or a wobble, and
    # for capital intensity eight quarters is barely one build cycle. Everything
    # below is company-reported per quarter; see long_history.provenance for the
    # three disciplines that keep it honest (no platform back-cast before 2018,
    # no derived days, no quoting of TSMC's own "advanced" aggregate).
    long = staging["long_history"]
    long_quarters = long["quarters"]
    long_labels = [quarter_label(quarter) for quarter in long_quarters]
    long_tech = long["technology_mix_pct"]
    long_platform = long["platform_mix_pct"]
    long_working = long["working_capital_days"]
    long_capex = long["capital_intensity"]
    long_intensity = [
        capex / revenue * 100
        for capex, revenue in zip(long_capex["capex_usd_bn"], long_capex["revenue_usd_bn"])
    ]
    decade = cn_count(int(long_quarters[-1][:4]) - int(long_quarters[0][:4]))
    # Platform gets its own shorter axis rather than eight blank quarters on the
    # left: TSMC did not report HPC before 2019Q1 and only ever restated 2018.
    platform_from = leading_gap(long_platform["hpc"])
    platform_labels = long_labels[platform_from:]
    node_birth = long["node_first_reported"]
    # The first quarter each node printed a non-zero share, read off the series
    # itself: a stored date can outlive the data it describes (rolled back a
    # quarter, the page would name a first 2nm quarter that has not happened).
    node_first_real = {
        node: next((quarter for quarter, value in zip(long_quarters, long_tech[node]) if value), None)
        for node in node_birth
    }
    # Everything the eight-quarter window used to carry, on the ten-year one.
    # The first four year-on-year cells are None rather than zero: the year
    # before the record is not in it, so the growth rate for its first four
    # quarters has no denominator and inventing one would put a fabricated
    # point at the left edge of every growth chart on the page.
    long_fin = long["financials"]
    long_cash = long["cash_flow_ntd_bn"]
    long_revenue = long_fin["revenue_usd_bn"]
    long_shipments = long_fin["wafer_shipments_kpcs_12in_equiv"]
    long_asp = [
        revenue * 1_000_000 / units
        for revenue, units in zip(long_revenue, long_shipments)
    ]

    def year_on_year(values: list[float]) -> list[float | None]:
        return [None if index < 4 else (values[index] / values[index - 4] - 1) * 100
                for index in range(len(values))]

    long_revenue_yoy = year_on_year(long_revenue)
    long_capex_usd_yoy = year_on_year(long_capex["capex_usd_bn"])
    no_base_year = int(long_quarters[0][:4]) - 1

    reported_fx = guidance["reported"]["usd_ntd"] if guidance else financials_fx(staging)
    kpi_by_metric = {entry["metric"]: entry for entry in next_kpi["quantified"]}

    # CapEx is reported in NT$ but tracked against a US$ line, so the threshold
    # is converted at the quarter's own realised rate and marked as derived.
    capex_threshold_ntd = round(kpi_by_metric["单季 CapEx"]["threshold"] * reported_fx, 1)
    # Each threshold now runs on the longest window its own series has, not on
    # a shared eight. Two of the five are shorter than the rest and it is the
    # disclosure that limits them, not this page: TSMC first reported the
    # platform split in 2019Q1 -- 2018 exists only as that year's restated
    # prior-year columns -- and first broke 2nm out of "advanced" in 2025Q2.
    # Trimming to the first reported quarter is why they start where they do --
    # a run of leading blanks would read as a series that fell to zero.
    two_nm_from = leading_gap(long_tech["2nm"])
    tracked = {
        "毛利率": (long_labels, long_fin["gross_margin_pct"], "pct1", "毛利率", "毛利率", None),
        "库存天数": (long_labels, long_working["inventory_days"], "f0", "天", "库存天数", None),
        "HPC 占比（集中度）": (
            platform_labels, long_platform["hpc"][platform_from:],
            "pct0", "净收入占比", "HPC 占比", None,
        ),
        "2nm 占晶圆收入": (
            long_labels[two_nm_from:], long_tech["2nm"][two_nm_from:],
            "pct0", "晶圆收入占比", "2nm 占比", None,
        ),
        "单季 CapEx": (
            long_labels, long_cash["capital_expenditures"], "f0c", "NT$B",
            "单季 CapEx", capex_threshold_ntd,
        ),
    }

    def tracking_charts(entries, value_key, threshold_label, headline) -> list[dict]:
        charts = []
        for entry in entries:
            metric = entry["metric"]
            if metric not in tracked:
                continue
            xlabels, values, fmt, ylab, actual_name, override = tracked[metric]
            side = "上方" if entry["direction"] == "up" else "下方"
            threshold = entry["threshold"] if override is None else override
            converted = (
                ""
                if override is None
                else f"（US${entry['threshold']:.0f}B 按本季实际汇率 {reported_fx} 折为 NT${override:,.1f}B D）"
            )
            charts.append(threshold_exhibit(
                headline(entry),
                xlabels,
                values,
                threshold,
                # One label per year once a series is long enough to need it;
                # the short ones keep every label.
                xstep=LONG_STEP if len(xlabels) > 16 else None,
                fmt=fmt,
                ylab=ylab,
                actual_name=actual_name,
                threshold_name=f"{threshold_label}（安全侧在{side}）",
                note=(
                    f"阈值 {unit_text(entry['unit'], entry['threshold'])}{converted}，"
                    f"当前 {unit_text(entry['unit'], entry[value_key])}，"
                    f"余量 {headroom(entry['direction'], entry['threshold'], entry[value_key]):+.1f}%。"
                ),
                src_extra=(
                    "实际值来自各季 earnings release / management report；"
                    "阈值为本地研究设定，不是公司指引。"
                ),
            ))
        return charts

    # ── Section one: the follow-up closure and this quarter against its guide ─
    guide_history = staging["quarterly_guidance_history"]
    this_guide = guide_history["quarters"].index(iso_period(period))
    rev_low = guide_history["guide_low_usd_bn"][this_guide]
    rev_high = guide_history["guide_high_usd_bn"][this_guide]
    revenue_now = financials["revenue_usd_bn"][-1]
    gm_now, om_now = financials["gross_margin_pct"][-1], financials["operating_margin_pct"][-1]
    gm_band = (guide_history["gross_margin_guide_low_pct"][this_guide],
               guide_history["gross_margin_guide_high_pct"][this_guide])
    om_band = (guide_history["operating_margin_guide_low_pct"][this_guide],
               guide_history["operating_margin_guide_high_pct"][this_guide])
    above_high = [name for name, value, band in (("毛利率", gm_now, gm_band), ("营业利润率", om_now, om_band))
                  if value > band[1]]
    revenue_position = ("超出指引上限" if revenue_now > rev_high else
                        "落指引上端" if revenue_now == rev_high else
                        "落在指引区间内" if revenue_now >= rev_low else "低于指引下限")

    closure_charts = []
    if closure is not None:
        total = sum(closure["counts"])
        falsified = closure.get("falsified")
        judged = [(label, count) for label, count in zip(closure["labels"], closure["counts"]) if count]

        def category_words(label: str, count: int) -> str:
            if label == "被证伪" and count == 1 and falsified and falsified["metric"] == "库存天数":
                return (f"被证伪的是{falsified['metric']}——上季判断会回落到 "
                        f"{falsified['expected_low_days']}–{falsified['expected_high_days']} 天，"
                        f"实际升到 {long_working['inventory_days'][-1]} 天")
            names = spaced(joined(closure["topics"][label]))
            return f"{label}的是{names}" if count == 1 else f"{label}的{cn_count(count)}条是{names}"

        closure_charts.append({
            "kind": "bars_labeled",
            # Every category the analysis used, in its order: a title that lists
            # three of four leaves the reader adding 3 + 1 + 4 and getting 8 of 12.
            "title": f"上季 {total} 条待验证问题：" + "、".join(f"{count} 条{label}" for label, count in judged),
            "xlabels": closure["labels"],
            "values": closure["counts"],
            "legend": "问题条数",
            "fmt": "f0",
            "yfmt": "f0",
            "label_fmt": "f0",
            "ylab": "条",
            "note": "；".join(category_words(label, count) for label, count in judged) + "。",
            "src_extra": (f"问题清单来自上季本地分析稿的 follow-up；验证结果依据 {deck_short(period)} "
                          "earnings conference 与 management report。"),
        })
    delivery_lead = []
    if delivery is not None:
        items = delivery["items"]
        fx_item = next(item for item in items if "汇率" in item["metric"])
        others_better = all(item["value"] > 0 for item in items if item is not fx_item)
        fx_headwind = fx_item["value"] < 0
        delivery_lead.append({
            "kind": "diverging_bars",
            "title": (f"{quarter_word(period)} 全线优于自身指引中值，只有汇率是逆风"
                      if others_better and fx_headwind else
                      f"{quarter_word(period)} 相对自身指引中值"),
            "xlabels": [item["metric"] for item in items],
            "values": [item["value"] for item in items],
            "legend": "优于指引中值的幅度",
            "positive_label": "优于指引",
            "negative_label": "逊于指引",
            "fmt": "f1",
            "yfmt": "f1",
            "label_fmt": "f1",
            "ylab": "% 或 pp",
            "zero_line": True,
            "note": (
                (f"{joined(above_high)}都超出指引区间上限" if len(above_high) == 2 else
                 f"{above_high[0]}超出指引区间上限" if above_high else "毛利率与营业利润率都没有超出指引区间上限")
                + ("，且是在新台币较汇率假设"
                   + ("小幅" if abs(fx_item["value"]) < 1 else "")
                   + "升值的逆风下做到的。" if fx_headwind and above_high else "。")
            ),
            "src_extra": (
                "收入与汇率为百分比，毛利率 / 营业利润率 / 税率为百分点，两类单位并列于同一轴上，"
                "只用于比较方向与相对幅度；原值见核对表。"
                + ("税率一项对照的是上季法说会上 CFO 口头给的本季税率，6-K 新闻稿不载这个数。"
                   if any("税率" in item["metric"] for item in items) else "")
            ),
        })

    # ── Section two ───────────────────────────────────────────────────────────
    next_guide = guidance["next_guide"] if guidance else None
    this_qoq = pct_change(long_revenue[-1], long_revenue[-2])
    finished_yoy = [value for value in long_revenue_yoy if value is not None]
    zero_crossings = sum(1 for a, b in zip(finished_yoy, finished_yoy[1:]) if (a < 0) != (b < 0))
    recent_rising = all(value > 0 for value in long_revenue_yoy[-8:] if value is not None)
    yoy_low = min(finished_yoy)
    yoy_high = max(finished_yoy)
    revenue_note = (
        f"本季环比 {signed(this_qoq)}、同比 {signed(long_revenue_yoy[-1])}"
        + (f"，较市场预期 US${consensus['revenue_usd_bn']:.2f}B "
           f"{'高' if long_revenue[-1] >= consensus['revenue_usd_bn'] else '低'} "
           f"{abs(pct_change(long_revenue[-1], consensus['revenue_usd_bn'])):.1f}%" if consensus else "")
    )
    if next_guide:
        next_mid = sum(next_guide["revenue_usd_bn"]) / 2
        next_growth = pct_change(next_mid, revenue_now)
        revenue_note += (f"；{quarter_word(following)} 指引中值 US${next_mid:.1f}B，环比 {signed(next_growth)}"
                         + ("，不减速" if next_growth >= this_qoq else "") + "。")
    else:
        revenue_note += "。"
    revenue_note += (
        f"<b>{decade}年的窗口里这条同比线穿越过零轴{cn_count(zero_crossings)}次</b>："
        f"最低 {yoy_low:.0f}%"
        f"（{long_labels[long_revenue_yoy.index(yoy_low)]}），"
        f"最高 {yoy_high:.0f}%"
        f"（{long_labels[long_revenue_yoy.index(yoy_high)]}）。"
        + (f"{cn_count(len(periods))}季的窗口只能看到最近这一段单边上行。" if recent_rising else "")
        + f"前四格没有同比线：{no_base_year} 年不在本记录内，没有分母。"
    )
    shipment_qoq = pct_change(long_shipments[-1], long_shipments[-2])
    asp_qoq = pct_change(long_asp[-1], long_asp[-2])
    two_nm_now = long_tech["2nm"][-1]
    three_nm_move = long_tech["3nm"][-1] - long_tech["3nm"][-2]
    hpc_move = long_platform["hpc"][-1] - long_platform["hpc"][-2]
    mix_drivers = []
    if two_nm_now and node_first_real["2nm"] == iso_period(period):
        mix_drivers.append(f"2nm 首季贡献 {two_nm_now}%")
    if three_nm_move > 0:
        mix_drivers.append(f"3nm 占比 {three_nm_move:+}pp")
    if hpc_move > 0:
        mix_drivers.append("HPC mix")
    asp_ratio = long_asp[-1] / long_asp[0]
    shipment_ratio = long_shipments[-1] / long_shipments[0]
    revenue_ratio = long_revenue[-1] / long_revenue[0]
    price_share = math.log(1 + asp_qoq / 100) / math.log(1 + this_qoq / 100) if this_qoq > 0 else 0

    margin_trough = min(range(len(long_quarters)), key=lambda i: long_fin["gross_margin_pct"][i])
    before_trough = range(max(0, margin_trough - 4), margin_trough)
    margin_peak = (max(before_trough, key=lambda i: long_fin["gross_margin_pct"][i])
                   if margin_trough else None)
    gm_levels = long_fin["gross_margin_pct"]
    next_gm_mid = sum(next_guide["gross_margin_pct"]) / 2 if next_guide else None
    dilution = (guidance or {}).get("n2_gross_margin_dilution_pp")
    overseas_late = (guidance or {}).get("overseas_fab_gross_margin_dilution_latter_pp")

    capex_chart = None
    capex_raised = False
    if capex_guide is not None:
        mids = [(low + high) / 2 for low, high in zip(capex_guide["low_usd_bn"], capex_guide["high_usd_bn"])]
        raises = sum(1 for a, b in zip(mids, mids[1:]) if b > a)
        capex_raised = mids[-1] > mids[0]
        first_call, last_call = (date.fromisoformat(capex_guide["dates"][0]),
                                 date.fromisoformat(capex_guide["dates"][-1]))
        months = (last_call.year - first_call.year) * 12 + last_call.month - first_call.month
        fiscal = capex_guide["fiscal_year"]
        capex_chart = {
            "kind": "bars_labeled",
            "title": (
                f"FY{fiscal} CapEx 预算"
                + (("半年内" if months <= 6 else f"{cn_count(months)}个月内")
                   + f"{cn_count(raises)}次上调" if raises else "维持")
                + f"，中点从 US${mids[0]:.0f}B {'抬到' if mids[-1] > mids[0] else '到'} US${mids[-1]:.0f}B"
            ),
            "xlabels": capex_guide["calls"],
            "values": mids,
            "legend": f"FY{fiscal} CapEx 指引中点",
            "fmt": "usd0",
            "yfmt": "usd0",
            "label_fmt": "usd0",
            "ylab": "US$B",
            "note": (
                f"新台币口径下本季 CapEx 同比 {signed(capex_ntd_yoy)}、收入同比 {signed(revenue_ntd_yoy)}；"
                "两条增速的美元口径长序列对照见 Exhibit {EX_CROSSOVER}。"
            ),
            "src_extra": (
                f"{cn_count(len(mids))}次口径依次为 "
                + "、".join(f"{date.fromisoformat(day).month} 月 {words}"
                           for day, words in zip(capex_guide["dates"], capex_guide["wording"]))
                + "；同比增速为新台币口径自算，避免与全年美元预算混用。"
            ),
        }

    bridge_chart = None
    if net_income_bridge is not None and consensus is not None:
        values = net_income_bridge["values_ntd_bn"]
        core_beat = pct_change(values[2], consensus["net_income_ntd_bn"])
        headline_beat = pct_change(values[0], consensus["net_income_ntd_bn"])
        share = values[1] / (values[0] - consensus["net_income_ntd_bn"])
        bridge_chart = {
            "kind": "bars_labeled",
            "title": (f"净利{'大幅' if headline_beat >= 5 else ''}超预期，但剔除 "
                      f"{net_income_bridge['one_off_short']} 一次性后核心 beat "
                      f"{'只有 ' if abs(core_beat) < abs(headline_beat) / 2 else ''}{core_beat:+.1f}%"),
            "xlabels": net_income_bridge["labels"],
            "values": values,
            "legend": "净利润",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "NT$B",
            "note": (
                f"报告净利较市场预期高 {headline_beat:+.1f}%，但{net_income_bridge['one_off_description']} "
                f"NT${values[1]:.2f}B 解释了其中"
                + ("绝大部分" if share >= 0.75 else "大部分" if share >= 0.5 else "一部分")
                + "；真正干净的超预期在收入与毛利率。"
                "本图是净利的金额桥，各项相对市场预期的百分比见 Exhibit {EX_EXPECTATION}。"
            ),
            "src_extra": (
                f"报告净利与 {net_income_bridge['one_off_short']} 相关收益来自 {deck_short(period)} "
                "management report；核心净利为两者相减的自算值（未做税务调整），"
                "市场预期为财报前一致预期，不具名。"
            ),
        }

    free_cash = long_cash["free_cash_flow"]
    negative_fcf = [value for value in free_cash if value < 0]
    dividend = blocks["declared_dividend"]
    this_year = [value for quarter, value in zip(long_quarters, free_cash)
                 if quarter[:4] == long_quarters[-1][:4]]
    if dividend:
        dividends_annual = declared_dividend_annual(dividend)
        coverage = sum(this_year) / len(this_year) * 4 / dividends_annual
    cash_chart = {
        "kind": "grouped_bars",
        "title": (
            f"CapEx 环比 "
            f"{signed(pct_change(long_cash['capital_expenditures'][-1], long_cash['capital_expenditures'][-2]))}，"
            f"自由现金流 "
            f"{signed(pct_change(free_cash[-1], free_cash[-2]))}"
        ),
        "xlabels": long_labels,
        "xstep": LONG_STEP,
        "groups": [
            {"name": "经营现金流", "values": long_cash["operating_cash_flow"], "color": "BLUE"},
            {"name": "资本开支", "values": long_cash["capital_expenditures"], "color": "NAVY"},
            {"name": "自由现金流 D", "values": free_cash, "color": "MBLUE"},
        ],
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "NT$B",
        "bar_labels": False,
        "note": (
            "资本强度见 Exhibit {EX_INTENSITY}"
            + (f"；按已宣告的每股 NT${per_share_text(dividend['per_share_ntd'])} 季度股利年化，"
               f"股息约 NT${dividends_annual:.0f}B，本年自由现金流仍可覆盖约{cn_count(round(coverage))}倍"
               + ("，现金流压缩暂未威胁股东回报。" if coverage >= 1 and free_cash[-1] < free_cash[-2] else "。")
               if dividend else "。")
            + f"<b>{decade}年里自由现金流为负的季度有 {len(negative_fcf)} 个</b>"
            + (f"（最低 {min(free_cash):,.0f} NT$B，{long_labels[free_cash.index(min(free_cash))]}）—— "
               "在一家把资本开支按付款节奏落账的公司里，单季自由现金流转负是扩产的常态而不是警讯"
               if negative_fcf else "")
            + (f"，{cn_count(len(periods))}季的窗口里一次都看不到。"
               if negative_fcf and min(free_cash[-len(periods):]) >= 0 else "。")
        ),
        "src_extra": (
            "季度新台币现金流口径；FCF = 经营现金流 − 现金支付资本开支，按 TSMC 定义复算。"
            + (f"股息年化 = 每股 NT${per_share_text(dividend['per_share_ntd'])} × 4 × "
               f"{dividend['shares_outstanding_thousands']:,} 千股：每股股利为 {dividend['board_date']} "
               f"董事会决议的 {deck_short(dividend['dividend_quarter'])} 现金股利，股数为 "
               f"{dividend['shares_as_of']} 合并财报的已发行股数（均见 6-K）。"
               if dividend else "")
        ),
    }

    entries = next_kpi["quantified"]
    breached = [entry for entry in entries
                if headroom(entry["direction"], entry["threshold"], entry["current"]) < 0]
    ramp = kpi_by_metric.get(next_kpi.get("ramp_metric"))
    watch = kpi_by_metric.get(next_kpi.get("watch_metric"))
    only_ramp = len(breached) == 1 and ramp is not None and breached[0] is ramp
    gated = next_kpi["disclosure_gated"]
    headroom_chart = headroom_exhibit(
        f"下季 {len(entries)} 条量化阈值："
        + (f"{ramp.get('short', ramp['metric'])}是唯一需要"
           f"{'大幅' if headroom(ramp['direction'], ramp['threshold'], ramp['current']) <= -20 else ''}"
           f"{'上行' if ramp['direction'] == 'up' else '回落'}才能达标的一条"
           if only_ramp else f"{len(breached)} 条已越过"),
        entries,
        "current",
        (
            "正值 = 仍在安全侧。"
            + (f"{ramp.get('short', ramp['metric']).split(' ')[0]} 当前 {ramp['current']:g}%，"
               f"而 {quarter_word(following)} 的「{next_kpi['ramp_quote']}」需要至少 {ramp['threshold']:g}%，"
               "是唯一明显在阈值之下的指标"
               if only_ramp and next_kpi.get("ramp_quote") else "")
            + (f"；{watch['metric']}离 {watch['threshold']:g} 天的警戒只剩 "
               f"{headroom(watch['direction'], watch['threshold'], watch['current']):.1f}%。"
               if watch and watch["unit"] == "days"
               and headroom(watch["direction"], watch["threshold"], watch["current"]) > 0 else "。")
        ),
        src_extra=(
            f"阈值为本地研究设定，不是公司指引；当前值为 {period} 实际。"
            + (f"另有 {len(gated)} 条需等披露才能判定（{'、'.join(item['short'] for item in gated)}）。"
               if gated else "")
        ),
    )

    advanced = long_tech["advanced_7nm_and_below"]
    advanced_from = long_quarters.index(ADVANCED_BASIS_FROM)
    advanced_agrees = snapshot["advanced_mix_pct"][0] == advanced[-1]
    two_nm_first = node_first_real["2nm"] == iso_period(period)
    tech_chart = {
        "kind": "lines",
        "title": (
            f"{decade}年制程迁移：7nm 及以下从 {advanced[0]}% 升到 "
            f"{advanced[-1]}%，2nm "
            + (f"本季首次单列为 {long_tech['2nm'][-1]}%" if two_nm_first else
               f"本季 {long_tech['2nm'][-1]}%")
        ),
        "xlabels": long_labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": "2nm", "values": long_tech["2nm"], "color": "GOLD"},
            {"name": "3nm", "values": long_tech["3nm"], "color": "NAVY"},
            {"name": "5nm", "values": long_tech["5nm"], "color": "MBLUE"},
            {"name": "7nm", "values": long_tech["7nm"], "color": "GRAY"},
            {"name": "7nm 及以下 D", "values": advanced, "color": "GREEN"},
        ],
        "fmt": "pct0",
        "yfmt": "pct0",
        "label_fmt": "pct0",
        "zero_base": True,
        "end_label": True,
        "ylab": "晶圆收入占比",
        "note": (
            "<b>每条线从该节点第一次出现在公司表里的那一季起画，之前是空的 —— 那不是缺数据，"
            "是当时表上根本没有这一行</b>（起始季 / 首次非零季）："
            + "、".join(
                f"{node} {quarter_label(node_birth[node])} / "
                f"{quarter_label(node_first_real[node]) if node_first_real[node] else '—'}"
                for node in node_birth
            )
            + "。两个日期不同，是因为新节点常先以公司自己印的 0% 出现在后续报告的"
            "比较列里，几个季度后才真正放量。之后某季若该行没印出来，表示舍入到 0.5% 以下，"
            "按 0 计（依据是该季印出来的各行仍合计 100%）。"
            "<b>绿线「7nm 及以下」是本页自己把印出来的 2/3/5/7nm 四行相加</b>，"
            "不是公司披露的 advanced technologies 口径 —— 那个口径 2019Q1 从「28nm 及以下」"
            "改成「16nm 及以下」、2021Q1 再改成「7nm 及以下」，且从未重述，直接连起来会在"
            "这两处砸出纯定义性的假悬崖（2021Q1 报出来是 62%→49%，同口径其实是微升）。"
            + (f"自算值与公司口径在 {ADVANCED_BASIS_FROM} 起的 {len(long_quarters) - advanced_from} 个季度逐季相等。"
               if advanced_agrees else
               f"本季自算值 {advanced[-1]}% 与公司口径 {snapshot['advanced_mix_pct'][0]}% 不等。")
        ),
        "src_extra": (
            f"制程组合分母为 total wafer revenue，口径{decade}年未变；逐季读自各季 "
            "quarterly management report 的 Wafer Revenue by Technology 表。"
        ),
    }

    hpc_line = kpi_by_metric.get("HPC 占比（集中度）")
    platform_chart = {
        "kind": "lines",
        "title": (
            f"HPC 从 {long_platform['hpc'][platform_from]}% 升到 "
            f"{long_platform['hpc'][-1]}%，智能手机从 "
            f"{long_platform['smartphone'][platform_from]}% 降到 "
            f"{long_platform['smartphone'][-1]}%"
        ),
        "xlabels": platform_labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": "HPC", "values": long_platform["hpc"][platform_from:], "color": "NAVY"},
            {"name": "Smartphone",
             "values": long_platform["smartphone"][platform_from:], "color": "MBLUE"},
        ],
        "fmt": "pct0",
        "yfmt": "pct0",
        "label_fmt": "pct0",
        "zero_base": True,
        "end_label": True,
        "ylab": "净收入占比",
        "note": (
            f"<b>这条线只能回到 {long_quarters[platform_from]}，不能到 {long_quarters[0][:4]}，"
            "原因是口径断层不是数据缺失</b>："
            "台积电 2019Q1 才把收入拆分从「按应用」（Communication / Computer / Consumer / "
            "Industrial-Standard）改成「按平台」，<b>在那之前根本没有 HPC 这个类别</b>。"
            "2018 那四季用的是公司自己在 2019 各季报告的去年同期列里给出的重述值，属公司报告值；"
            "2016–2017 公司只发过年度平台数、季度值从未发布。两套类别是交叉分类而非重切"
            "（公司给的映射是「Computer >95% 归 HPC」「Communication 约 2/3 是 Smartphone」"
            "这类 30–60% 的定性区间），拿它换算就是估算，本页不做。"
            + (f"集中度是这条曲线的另一面，HPC 站上 {hpc_line['threshold']:g}% 即触发本页的集中度跟踪线。"
               if hpc_line else "")
        ),
        "src_extra": (
            "平台组合分母为 net revenue，逐季读自各季 quarterly management report 的 "
            "Net Revenue by Platform 表；本页仅接入 HPC 与 Smartphone 两类，"
            "IoT / 汽车 / DCE 尚未接入。"
        ),
    }

    inventory = long_working["inventory_days"]
    receivable = long_working["receivable_days"]
    early = [value for quarter, value in zip(long_quarters, inventory)
             if INVENTORY_EARLY[0] <= quarter <= INVENTORY_EARLY[1]]
    late = [value for quarter, value in zip(long_quarters, inventory) if quarter >= INVENTORY_LATE_FROM]
    first_year_receivable = [value for quarter, value in zip(long_quarters, receivable)
                             if quarter[:4] == long_quarters[0][:4]]
    working_chart = {
        "kind": "lines",
        "title": (
            f"库存天数{decade}年区间 {min(inventory)}–"
            f"{max(inventory)} 天，本季 "
            f"{inventory[-1]} 天；"
            + (f"应收天数一路降到 {receivable[-1]} 天" if receivable[-1] == min(receivable) else
               f"应收天数从 {receivable[0]} 天降到 {receivable[-1]} 天")
        ),
        "xlabels": long_labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": "库存天数", "values": inventory, "color": "NAVY"},
            {"name": "应收天数", "values": receivable, "color": "MBLUE"},
        ],
        "fmt": "f0",
        "yfmt": "f0",
        "label_fmt": "f0",
        "end_label": True,
        "ylab": "天",
        "note": (
            (f"本季公司归因于{spaced(story['inventory_attribution'])}；{story['inventory_test']}。"
             if story.get("inventory_attribution") else "")
            + f"拉长看，库存天数在 {INVENTORY_EARLY[0][:4]}–{INVENTORY_EARLY[1][:4]} 年在 "
            f"{min(early)}–{max(early)} 天之间，{INVENTORY_LATE_FROM[:4]} 年后"
            f"{'抬到' if sorted(late)[len(late) // 2] > sorted(early)[len(early) // 2] else '在'} "
            f"{min(late)}–{max(late)} 天，"
            f"当前 {inventory[-1]} 天"
            + ("仍在这个区间内而非异常值；" if min(late) <= inventory[-1] <= max(late) else "已在这个区间之外；")
            + ("应收天数则整体下行，" if receivable[-1] < min(first_year_receivable) else "应收天数")
            + f"从 {long_quarters[0][:4]} 年的 {min(first_year_receivable)}–{max(first_year_receivable)} 天"
            f"{'降到' if receivable[-1] < min(first_year_receivable) else '到'}本季的 {receivable[-1]} 天。"
            "<b>两条都是公司印在报告里的原值，本页不自己推导</b> —— 实测任何"
            f"「余额 ÷ 日均」的公式都复现不出这 {len(long_quarters)} 个季度（最好的一版只精确命中一成），"
            "公司也未公开其天数惯例。"
        ),
        "src_extra": (
            "应收与库存天数逐季读自各季 quarterly management report 的 "
            "「III - 2. Receivable/Inventory Days」表原值。"
        ),
    }

    highlight = [
        {
            "kind": "gs_bar",
            "title": (
                f"收入 US${long_revenue[-1]:.2f}B {revenue_position}，"
                f"{decade}年里长到 {long_revenue[-1] / long_revenue[0]:.1f} 倍"
            ),
            "xlabels": long_labels,
            "xstep": LONG_STEP,
            "values": long_revenue,
            "legend": "季度收入",
            "fmt": "usd1",
            "yfmt": "usd1",
            "label_fmt": "usd1",
            "ylab": "US$B",
            "ylab2": "同比增速",
            "yoy": {
                "name": "收入 YoY (RHS) D",
                "values": rounded(long_revenue_yoy),
                "color": "GREEN",
                "yfmt": "pct0",
            },
            "note": revenue_note,
            "src_extra": (
                "美元收入逐季读自各季 earnings release 与法说会简报；同比为自算 D；"
                "市场预期为财报前一致预期，不具名。"
            ),
        },
        {
            "kind": "gs_bar",
            "title": (
                f"本季环比里{'大部分' if price_share > 0.5 else '小部分'}来自价与结构："
                f"出货 {signed(shipment_qoq)}，隐含 ASP {signed(asp_qoq)}"
            ),
            "xlabels": long_labels,
            "xstep": LONG_STEP,
            "values": long_shipments,
            "legend": "晶圆出货（12 吋等值）",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "千片",
            "ylab2": "隐含 ASP（美元 / 片）",
            "yoy": {
                "name": "隐含 ASP（美元/片，RHS） D",
                "values": rounded(long_asp),
                "color": "GOLD",
                "yfmt": "f0c",
            },
            "note": (
                f"隐含 ASP = 季度美元收入 / 晶圆出货，本季 ${long_asp[-1]:,.0f}/片"
                + (f"；抬价的是{spaced(joined(mix_drivers))}，不是单纯提价。" if asp_qoq > 0 and mix_drivers else "。")
                + f"<b>{decade}年的窗口说明这不是一次提价而是一条结构线</b>：ASP 从 "
                f"${long_asp[0]:,.0f} 升到 ${long_asp[-1]:,.0f}（{asp_ratio:.1f} 倍），"
                f"而同期出货只从 {long_shipments[0]:,} 增到 {long_shipments[-1]:,} 千片"
                f"（{shipment_ratio:.1f} 倍）—— "
                f"收入的 {revenue_ratio:.1f} 倍增长里，量只解释了其中一小部分。"
            ),
            "src_extra": (
                "出货量与美元收入来自各季 earnings release / management report；隐含 ASP 为两者相除的自算值，"
                "不是公司披露的定价指标，也不区分制程与封装口径。"
            ),
        },
        {
            "kind": "lines",
            "title": (
                f"毛利率 {gm_levels[-1]:.1f}% "
                + ("超指引上限" if gm_levels[-1] > gm_band[1] else "落在指引区间内"
                   if gm_levels[-1] >= gm_band[0] else "低于指引下限")
                + (f"，但 {quarter_word(following)} 指引中值已降到 {trim(next_gm_mid)}%"
                   if next_gm_mid is not None and next_gm_mid < gm_levels[-1] else
                   f"，{quarter_word(following)} 指引中值 {trim(next_gm_mid)}%" if next_gm_mid is not None else "")
            ),
            "ref": "EX_MARGIN_LEVEL",
            "xstep": LONG_STEP,
            "xlabels": long_labels,
            "series": [
                {"name": "毛利率", "values": gm_levels, "color": "NAVY"},
                {"name": "营业利润率", "values": long_fin["operating_margin_pct"], "color": "MBLUE"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "end_label": True,
            "ylab": "利润率",
            "note": (
                (f"管理层{'首次' if story.get('n2_dilution_first_quantified') else ''}量化 "
                 f"{guidance['n2_gross_margin_dilution_half']} 的 N2 稀释 {dilution[0]}–{dilution[1]}pp"
                 + (f"，叠加海外厂后期 {overseas_late[0]}–{overseas_late[1]}pp" if overseas_late else "")
                 + "；" if dilution else "")
                + (f"{quarter_word(following)} 指引中值 {next_gm_mid:.1f}%，较本季 "
                   f"{next_gm_mid - gm_levels[-1]:+.1f}pp。" if next_gm_mid is not None else "")
                + f"<b>但「本周期顶点」要放在{decade}年里看才有意义</b>："
                f"这条线的{decade}年区间是 {min(gm_levels):.1f}%"
                f"（{long_labels[margin_trough]}）到 "
                f"{max(gm_levels):.1f}%"
                f"（{long_labels[gm_levels.index(max(gm_levels))]}），"
                + (f"而 {long_quarters[margin_peak][:4]}–{long_quarters[margin_trough][:4]} 那一段曾从 "
                   f"{gm_levels[margin_peak]:.1f}%（{long_labels[margin_peak]}）降到 "
                   f"{gm_levels[margin_trough]:.1f}%（{long_labels[margin_trough]}） —— "
                   "这家公司的毛利率不是单调抬升的，它有过一段完整的下行。"
                   if margin_peak is not None and gm_levels[margin_peak] > gm_levels[margin_trough] else "")
                + "本图画的是水平，逐季指引区间与兑现记录见 Exhibit {EX_GM}。"
            ),
            "src_extra": ("利润率与指引来自 TSMC earnings release"
                          + ("；稀释幅度为管理层在电话会上的量化口径。" if dilution else "。")),
        },
    ]
    # Section two follows the quarter's analysis in its own order: growth
    # (revenue, volume against price), profit quality (the margin, the market's
    # bar and the one-off inside net income), then capital intensity (the
    # budget, the cash). The market's bar is a reading of this quarter, not
    # something last quarter left to settle, so it sits here and not in section one.
    if consensus:
        highlight.append(expectation_chart(staging, consensus, snapshot, net_income_bridge))
    if bridge_chart:
        highlight.append(bridge_chart)
    if capex_chart:
        highlight.append(capex_chart)
    highlight.append(cash_chart)

    # The check tables run on the same window as the charts they back. An
    # eight-row table under a forty-two-point chart is not a check.
    financial_table = []
    mix_table = []
    cash_table = []
    for index, quarter in enumerate(long_quarters):
        label = quarter_label(quarter)
        yoy = long_revenue_yoy[index]
        financial_table.append([
            label,
            f"US${long_revenue[index]:.2f}B",
            f"{yoy:.1f}% D" if yoy is not None else "—",
            f"{long_fin['gross_margin_pct'][index]:.1f}%",
            f"{long_fin['operating_margin_pct'][index]:.1f}%",
            f"NT${long_fin['eps_ntd'][index]:.2f}",
            f"{long_shipments[index] / 1000:.3f}M",
            f"${long_asp[index]:,.0f} D",
        ])
        # "—" is not a formatting nicety: a node with no row in the company's
        # table is a different fact from a reported 0%, and printing "0%" for it
        # is the thing the mix_notes used to have to apologise for.
        def mix_cell(values: list[float | None], at: int = index) -> str:
            value = values[at]
            return "—" if value is None else f"{value:.0f}%"

        mix_table.append([
            label,
            mix_cell(long_tech["2nm"]),
            mix_cell(long_tech["3nm"]),
            mix_cell(long_tech["5nm"]),
            mix_cell(long_tech["7nm"]),
            mix_cell(long_tech["advanced_7nm_and_below"]),
            mix_cell(long_platform["hpc"]),
            mix_cell(long_platform["smartphone"]),
        ])
        cash_table.append([
            label,
            f"NT${long_cash['operating_cash_flow'][index]:,.2f}B",
            f"NT${long_cash['capital_expenditures'][index]:,.2f}B",
            f"NT${long_cash['free_cash_flow'][index]:,.2f}B D",
            f"{long_working['receivable_days'][index]}天",
            f"{long_working['inventory_days'][index]}天",
        ])

    guide_rows = guidance_rows(guidance, financials, period) if guidance else []

    falsified = (closure or {}).get("falsified")
    inventory_expectation = None
    if falsified and falsified["metric"] == "库存天数":
        expected_low, expected_high = falsified["expected_low_days"], falsified["expected_high_days"]
        above_expected = sum(1 for value in inventory if value > expected_high)
        labels_count = dict(zip(closure["labels"], closure["counts"]))
        watch_line = kpi_by_metric.get("库存天数")
        inventory_expectation = threshold_exhibit(
            f"上季判断库存回落到 {expected_low}–{expected_high} 天，实际升到 {inventory[-1]} 天（被证伪）",
            long_labels,
            inventory,
            float(expected_high),
            xstep=LONG_STEP,
            fmt="f0",
            ylab="天",
            actual_name="库存天数",
            threshold_name=f"上季预期上沿 {expected_high} 天",
            note=(
                (f"管理层归因于{spaced(story['inventory_attribution'])}；" if story.get("inventory_attribution") else "")
                + (f"这是上季 {sum(closure['counts'])} 条判断里唯一被明确证伪的一条"
                   if labels_count["被证伪"] == 1 else
                   f"这是上季 {sum(closure['counts'])} 条判断里被明确证伪的{cn_count(labels_count['被证伪'])}条之一")
                + (f"，也是本季分析把下季警戒线定在 {watch_line['threshold']:g} 天的由来。" if watch_line else "。")
                + f"<b>但 {expected_high} 天这条线放在{decade}年里并不高</b>：{decade}年区间 "
                f"{min(inventory)}–{max(inventory)} 天，"
                f"高于 {expected_high} 天的季度有 {above_expected} 个，"
                f"上季那个「回落到 {expected_low}–{expected_high} 天」的预期本身就是拿最近几年的水平当常态。"
                if above_expected * 4 >= len(inventory) else
                (f"管理层归因于{spaced(story['inventory_attribution'])}；" if story.get("inventory_attribution") else "")
                + f"{decade}年区间 {min(inventory)}–{max(inventory)} 天，高于 {expected_high} 天的季度有 "
                f"{above_expected} 个。"
            ),
            src_extra=(f"库存天数逐季读自各季 management report；{expected_low}–{expected_high} 天"
                       "为上季本地分析稿的预期区间。"),
        )

    intensity_low = min(long_intensity)
    intensity_low_at = long_labels[long_intensity.index(intensity_low)]
    intensity_high = max(long_intensity)
    intensity_high_index = long_intensity.index(intensity_high)
    intensity_high_at = long_labels[intensity_high_index]
    intensity_move = long_intensity[-1] - long_intensity[-2]
    capex_intensity_chart = {
        "ref": "EX_INTENSITY",
        "kind": "gs_line",
        "title": (
            f"资本强度{decade}年从 {long_intensity[0]:.1f}% "
            f"{'升到' if long_intensity[-1] >= long_intensity[0] else '降到'} {long_intensity[-1]:.1f}%，"
            f"期间峰值 {intensity_high:.1f}%（{intensity_high_at}）"
        ),
        "xlabels": long_labels,
        "xstep": LONG_STEP,
        "values": [round(value, 6) for value in long_intensity],
        "legend": "CapEx / 收入（美元口径）",
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "占收入比",
        "note": (
            f"本季 {long_intensity[-1]:.1f}%，较上季 {long_intensity[-2]:.1f}% "
            + ("跳升" if intensity_move >= 3 else "上升" if intensity_move > 0 else "回落")
            + "。"
            f"{decade}年区间 {intensity_low:.1f}%（{intensity_low_at}）到 "
            f"{intensity_high:.1f}%（{intensity_high_at}）"
            + (f"—— <b>本季并不是历史高位</b>，{long_quarters[intensity_high_index][:4]} 年那轮扩产把单季资本支出"
               f"打到收入的{cn_fraction_above(intensity_high / 100)}"
               + (f"，{cn_count(len(periods))}季的窗口看不到这件事" if intensity_high_index < len(long_quarters) - len(periods) else "")
               + "。" if intensity_high > long_intensity[-1] else "—— 本季就是历史高位。")
            + "单季比值天然比年度口径抖，因为 CapEx 按付款节奏落账、收入按季确认，"
            "看趋势要顺着几个季度读，不要盯单点。"
            "这条线与 GOOGL 页同口径，可直接对照上下游的资本强度。"
        ),
        "src_extra": (
            "美元 CapEx 逐季读自各季 quarterly management report 的「V. Capital Expenditures」"
            "美元表（1Q16 的单位是 US$ millions，其余季为 billions），美元收入来自各季 "
            "earnings release 原句；比值为自算，两侧同币种，不与新台币现金流口径混用。"
        ),
    }

    with_yoy = [i for i in range(len(long_quarters))
                if long_capex_usd_yoy[i] is not None and long_revenue_yoy[i] is not None]
    capex_ahead = [i for i in with_yoy if long_capex_usd_yoy[i] > long_revenue_yoy[i]]
    crossings = [i for i in with_yoy[1:]
                 if long_capex_usd_yoy[i] > long_revenue_yoy[i]
                 and long_capex_usd_yoy[i - 1] <= long_revenue_yoy[i - 1]]
    crossed_now = bool(crossings) and crossings[-1] == len(long_quarters) - 1
    growth_crossover_chart = {
        "ref": "EX_CROSSOVER",
        "kind": "lines",
        "title": (
            f"CapEx 增速 {long_capex_usd_yoy[-1]:+.0f}% "
            + ("反超" if long_capex_usd_yoy[-1] > long_revenue_yoy[-1] else "低于")
            + f"收入增速 {long_revenue_yoy[-1]:+.0f}%"
        ),
        "xlabels": long_labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": "收入 YoY", "values": rounded(long_revenue_yoy), "color": "NAVY"},
            {"name": "CapEx YoY", "values": rounded(long_capex_usd_yoy), "color": "RED"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "同比增速",
        "note": (
            (f"上季管理层称「{story['prior_call_quote']}」；"
             + (f"本季两条线交叉，{story['crossover_reading']}。" if crossed_now else "")
             if story.get("prior_call_quote") else
             ("本季两条线交叉。" if crossed_now else ""))
            + f"<b>{decade}年的窗口说明交叉本身不稀奇</b>："
            f"{len(with_yoy)} 个有同比的季度里 CapEx 增速高于收入增速的有 {len(capex_ahead)} 个，"
            f"从下方穿上来的有 {len(crossings)} 次（"
            + "、".join(long_labels[i] if i != len(long_quarters) - 1 else "本季" for i in crossings)
            + "），交叉当季的收入同比依次为 "
            + "、".join(f"{long_revenue_yoy[i]:+.1f}%" for i in crossings)
            + "。"
            f"两条都是美元口径，不含汇率错配。前四格没有同比：{no_base_year} 年不在本记录内。"
        ),
        "src_extra": (
            "收入与美元 CapEx 逐季读自各季 earnings release 与 quarterly management report；"
            "两条同比均为自算 D。"
        ),
    }

    # ── Section one (b): last quarter's section 8, settled ────────────────────
    # The thresholds are the previous analysis's own, moved as they stood; the
    # readings are this quarter's, taken off the end of each record. A line set
    # where the metric already stood on the safe side is 「守住 / 击穿」; one set
    # above it is a target, 「达到 / 仍未达到」 (see `settle_verdict`).
    prior = blocks["prior_kpi_settlement"]
    prior_charts: list[dict] = []
    prior_rows = 0
    # Placeholders in the series' threshold prose: `board.fill_story` only knows
    # lower-case letters and underscores, so a name with a digit would pass
    # through as literal braces -- hence `two_nm_now`, not `n2_now`.
    story_values = {
        "two_nm_now": f"{long_tech['2nm'][-1]:g}%",
        "hpc_now": f"{long_platform['hpc'][-1]:g}%",
    }
    if prior is not None:
        readings = []
        for entry in prior["quantified"]:
            xlabels, values, spec = kpi_history(staging, entry["reads"])
            readings.append(({**entry, "actual": values[-1]}, xlabels, values, spec))
        prior_entries = [entry for entry, _, _, _ in readings]
        prior_rows = len({entry["row"] for entry in prior_entries}
                         | {item["row"] for item in prior.get("not_carried", [])})

        def is_safe(entry: dict) -> bool:
            return headroom(entry["direction"], entry["threshold"], entry["actual"]) >= 0

        safe = [entry for entry in prior_entries if is_safe(entry)]
        short = [(entry, values) for entry, _, values, _ in readings if not is_safe(entry)]
        if not short:
            tally = "全部在安全侧"
        elif not safe:
            tally = "全部不在安全侧"
        elif len(short) == 1:
            entry, values = short[0]
            tally = (f"：{len(safe)} 条在安全侧，{entry['metric']} {unit_text(entry['unit'], entry['actual'])} "
                     f"{settle_verdict(entry, values)} {unit_text(entry['unit'], entry['threshold'])}")
        else:
            tally = f"：{len(safe)} 条在安全侧、{len(short)} 条不在"
        not_carried = prior.get("not_carried", [])
        prior_charts.append(headroom_exhibit(
            f"上季 {len(prior_entries)} 条量化阈值" + tally,
            prior_entries,
            "actual",
            (
                "正值 = 本季实际落在上季阈值的安全侧。"
                + "".join(f"{entry['metric']}：{spec.get('now', '本季')} {unit_text(entry['unit'], entry['actual'])}，"
                          f"上季阈值 {unit_text(entry['unit'], entry['threshold'])}"
                          f"（{'以上' if entry['direction'] == 'up' else '以下'}为安全侧）。"
                          for entry, _, _, spec in readings)
                + (f"上季第 8 节另有{cn_count(len(not_carried))}行本季读不到："
                   + "；".join(f"{item['short']}（{html_text(item['text'])}）——"
                              f"{html_text(fill_story(item['why'], story_values))}" for item in not_carried)
                   + "。" if not_carried else "")
            ),
            src_extra=(f"阈值逐字取自上季（{prior['set_in']}）本地分析第 8 节，不是公司指引；"
                       "实际值为本季申报值或据其相加的自算值（D）。"),
        ))
        for entry, xlabels, values, spec in readings:
            unit, actual, threshold = entry["unit"], entry["actual"], entry["threshold"]
            side = "上方" if entry["direction"] == "up" else "下方"
            reported = [value for value in values if value is not None]
            earlier = reported[:-1]
            previous = next(((label, value) for label, value in zip(reversed(xlabels[:-1]), reversed(values[:-1]))
                             if value is not None), None)
            need = entry.get("consecutive", 1)
            run = safe_run(entry, values)
            best = (max if entry["direction"] == "up" else min)(reported)
            extreme = "最高" if entry["direction"] == "up" else "最低"
            record = ""
            if earlier and actual == best and best not in earlier:
                record = f"，是图上{cn_count(len(reported))}{spec['per']}里{extreme}的一个"
                if headroom(entry["direction"], threshold, actual) >= 0 and all(
                        headroom(entry["direction"], threshold, value) < 0 for value in earlier):
                    record += f"、第一次越过 {unit_text(unit, threshold)}"
            warn = entry.get("warn")
            prior_charts.append(threshold_exhibit(
                (f"{entry['metric']} {unit_text(unit, actual)}：{settle_verdict(entry, values)}"
                 f"上季阈值 {unit_text(unit, threshold)}"),
                xlabels,
                values,
                threshold,
                xstep=LONG_STEP if len(xlabels) > 16 else None,
                fmt=spec["fmt"],
                ylab=spec["ylab"],
                actual_name=spec["name"],
                threshold_name=f"上季阈值（安全侧在{side}）",
                note=(
                    f"上季分析第 8 节原文：{html_text(entry['basis'])}。"
                    f"{spec.get('now', '本季')} {unit_text(unit, actual)}"
                    + (f"（{previous[0]} 为 {unit_text(unit, previous[1])}）" if previous else "")
                    + f"，余量 {headroom(entry['direction'], threshold, actual):+.1f}%"
                    + record
                    + (f"；连续在安全侧的已有{cn_count(run)}{spec['per']}，上季要的是连续{cn_count(need)}{spec['per']}，"
                       + ("已经满足" if run >= need else f"还差{cn_count(need - run)}{spec['per']}")
                       if need > 1 else "")
                    + "。"
                    + (f"同一行的另一条线「{'低于' if entry['direction'] == 'up' else '高于'} "
                       f"{unit_text(unit, warn['threshold'])} = {html_text(warn['words'])}」"
                       + ("没有触及。" if headroom(entry["direction"], warn["threshold"], actual) >= 0 else "已经触及。")
                       if warn else "")
                    + (html_text(fill_story(entry["rest"], story_values)) if entry.get("rest") else "")
                ),
                src_extra=spec["source"] + "阈值为上季本地研究设定，不是公司指引。",
            ))

    # Section one settles what last quarter left, in the order it was left: the
    # follow-up list and the one falsified call that has a long series behind
    # it, then the previous analysis's section-8 thresholds, then this quarter
    # against the company's own guide and the three guided metrics over the full
    # guided record.
    delivery_charts, delivery_table = guidance_delivery_charts(staging, guidance)
    settled_charts = (
        closure_charts
        + ([inventory_expectation] if inventory_expectation else [])
        + prior_charts
        + delivery_lead
        + delivery_charts
    )
    highlights = highlight + [growth_crossover_chart]
    next_charts = [headroom_chart] + tracking_charts(
        next_kpi["quantified"],
        "current",
        "下季阈值",
        lambda entry: (
            f"{entry['metric']}：下季阈值 {unit_text(entry['unit'], entry['threshold'])}，"
            f"当前 {unit_text(entry['unit'], entry['current'])}"
        ),
    )
    routine = [tech_chart, platform_chart, working_chart, capex_intensity_chart]

    exhibits = resolve_exhibit_refs(
        number_exhibits(settled_charts + highlights + next_charts + routine)
    )
    # Slice by cumulative length rather than by hand-written indices: the
    # sections are the same list, cut in order, so inserting a chart into one of
    # them cannot silently move a chart into its neighbour.
    grouped = []
    cursor = 0
    for group in (settled_charts, highlights, next_charts, routine):
        grouped.append(exhibits[cursor:cursor + len(group)])
        cursor += len(group)
    settled_ex, highlight_ex, next_ex, routine_ex = grouped
    next_table_number = len(exhibits) + 2

    tables = []
    if guide_rows:
        tables.append({
            # Reference detail, not a lead module: the decision-relevant parts of
            # guidance are already in the settled and highlight sections.
            "title": f"{quarter_word(period)} 兑现、{quarter_word(following)} 指引与全年 outlook",
            "headers": ["指标", f"{quarter_word(period)} 原指引", f"{quarter_word(period)} 实际", "兑现",
                        f"{quarter_word(following)} / FY{str(guidance['fiscal_year'])[-2:]} 新口径",
                        "变化 / 备注"],
            "rows": guide_rows,
        })
    tables += [
        threshold_table(
            0,
            "下季阈值与当前值（原单位）",
            next_kpi["quantified"],
            "current",
            "当前值",
        ),
        {
            "title": f"{len(long_quarters)} 季度财务、出货与隐含 ASP（{long_quarters[0]} 起）",
            "headers": ["期间", "收入", "收入 YoY", "毛利率", "营业利润率", "稀释 EPS", "晶圆出货", "隐含 ASP"],
            "rows": financial_table,
        },
        {
            "title": f"{len(long_quarters)} 季度制程与平台收入组合（{long_quarters[0]} 起）",
            "headers": ["期间", "2nm", "3nm", "5nm", "7nm", "≤7nm", "HPC", "Smartphone"],
            "rows": mix_table,
        },
        {
            "title": f"{len(long_quarters)} 季度现金流与营运资金（新台币，{long_quarters[0]} 起）",
            "headers": ["期间", "经营现金流", "资本开支", "自由现金流", "应收天数", "库存天数"],
            "rows": cash_table,
        },
        # The eight-quarter guidance table used to sit here. It is gone: the
        # full guided record below carries the same five columns and four more,
        # so keeping both would mean two tables that must agree and one of them
        # silently shorter.
        delivery_table,
        ai_capex_cycle_table(0),
    ]
    numbered = []
    for offset, table in enumerate(tables):
        table.pop("n", None)
        number = next_table_number + offset
        # The guided-record table has always carried its number last; the
        # others first. Key order is part of the published bytes.
        numbered.append({**table, "n": number} if table is delivery_table else {"n": number, **table})
    tables = numbered

    # ── Headline and brief ────────────────────────────────────────────────────
    headline = ""
    if guidance:
        growth_raised = guidance["fy_revenue_growth_change_cn"] == "上调"
        all_stronger = (revenue_now >= rev_high and gm_now > gm_band[1] and growth_raised)
        headline = (
            ("基本面全线更强——" if all_stronger else "")
            + f"收入{revenue_position}、毛利率 {gm_now:.1f}% "
            + ("超上限" if gm_now > gm_band[1] else "落在区间内" if gm_now >= gm_band[0] else "低于下限")
            + f"、全年增速指引由{spaced(guidance['fy_revenue_growth_prior_short_cn'])}"
            + (" " if guidance["fy_revenue_growth_prior_short_cn"][-1:].isascii() else "")
            + f"{guidance['fy_revenue_growth_change_cn']}到{guidance['fy_revenue_growth_cn']}"
        )
        capex_ahead_now = capex_ntd_yoy > revenue_ntd_yoy
        capex_range = guidance["fy_capex_usd_bn"]
        headline += (
            ("；但" if all_stronger and capex_ahead_now else "；")
            + (f"股价当日 {consensus['post_earnings_price_change_pct']}%，" if consensus else "")
            + (f"市场卖的是{story['market_sold']}：" if story.get("market_sold") else "")
            + f"全年 CapEx {'上调至' if sum(capex_range) > sum(guidance['fy_capex_prior_usd_bn']) else '为'} "
            f"{usd_range(capex_range)}，新台币口径 CapEx 同比 {signed(capex_ntd_yoy)} "
            + ("已快于" if capex_ahead_now else "仍慢于")
            + f"收入的 {signed(revenue_ntd_yoy)}。"
        )
    articles = []
    delivered = (["收入"] if revenue_now > rev_high else []) + above_high
    if delivered:
        articles.append(
            '<article><span>亮点</span>'
            f'<b>{joined(delivered)}{"双" if len(delivered) == 2 else "三项全" if len(delivered) == 3 else ""}超指引上限</b>'
            f'<p>US${revenue_now:.2f}B {"落区间上端" if revenue_now == rev_high else revenue_position}；'
            f'GM {gm_now:.1f}%、OM {om_now:.1f}%'
            + ("，均超上限" if len(above_high) == 2 else "")
            + '。</p></article>')
    if this_qoq > 0 and asp_qoq > 0:
        articles.append(
            '<article><span>结构</span>'
            f'<b>增长约{cn_share(price_share)}来自价与 mix</b>'
            f'<p>出货环比 {signed(shipment_qoq)}，隐含 ASP {signed(asp_qoq)}'
            + (f'；2nm 首季即贡献 {two_nm_now}%' if two_nm_first else "")
            + '。</p></article>')
    if net_income_bridge is not None and consensus is not None:
        values = net_income_bridge["values_ntd_bn"]
        core_beat = pct_change(values[2], consensus["net_income_ntd_bn"])
        articles.append(
            '<article><span>存疑</span>'
            f'<b>净利{"大 " if pct_change(values[0], consensus["net_income_ntd_bn"]) >= 5 else ""}beat 含一次性</b>'
            f'<p>{net_income_bridge["one_off_short"]} 税前收益 NT${values[1]:.2f}B；'
            f'核心净利较预期仅 {core_beat:+.1f}%。</p></article>')

    guided = guide_history["quarters"]
    finished_count = sum(1 for value in guide_history["actual_revenue_usd_bn"] if value is not None)
    recent = [i for i, value in enumerate(guide_history["actual_revenue_usd_bn"])
              if value is not None][-len(periods):]

    def broken(low_key: str, actual_key: str, indices) -> bool:
        return any(guide_history[actual_key][i] < guide_history[low_key][i] for i in indices)

    finished_indices = [i for i, value in enumerate(guide_history["actual_revenue_usd_bn"]) if value is not None]
    triples = (("guide_low_usd_bn", "actual_revenue_usd_bn"),
               ("gross_margin_guide_low_pct", "gross_margin_actual_pct"),
               ("operating_margin_guide_low_pct", "operating_margin_actual_pct"))
    recent_clean = not any(broken(low, act, recent) for low, act in triples)
    all_broken = all(broken(low, act, finished_indices) for low, act in triples)

    prior_overview = next((ex for ex in settled_ex
                           if ex["kind"] == "diverging_bars" and ex["title"].startswith("上季 ")), None)
    notes = [
        "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
        (f"Exhibit {prior_overview['n']} 与 Exhibit {next_ex[0]['n']} 的阈值（及两图其后逐条的线）是本地研究设定，"
         "前者取自上季、后者取自本季本地分析第 8 节，"
         if prior_overview else f"Exhibit {next_ex[0]['n']} 与其后各图的阈值是本地研究设定，")
        + "不是公司指引，也不构成评级或投资建议；「距阈值余量」统一为正值代表安全侧。",
    ]
    bands = [ex for ex in settled_ex if ex["kind"] == "range_band"]
    margins_match = all(
        abs(a - b) < 0.05
        for key, published in (("gross_margin_actual_pct", "gross_margin_pct"),
                               ("operating_margin_actual_pct", "operating_margin_pct"))
        for a, b in zip([guide_history[key][i] for i in recent], financials[published]))
    notes.append(
        f"第一节的指引兑现三张图（Exhibit {'／'.join(str(ex['n']) for ex in bands)}）用的是同一批 6-K：每份法说会 6-K 同时给出下一季的收入区间、毛利率区间、营业利润率区间与假设汇率，实际值取自随后一季 6-K 的合并损益表；毛利率与营业利润率由毛利、营业利益分别除以净销售额得出"
        + (f"，与本页 financials 的{cn_count(len(periods))}季逐季对到小数点后一位。" if margins_match else "。")
        + "指引区间与实际值一律按公司发布的一位小数比较：区间本身只印到 0.1pp，用比它更细的精度裁定越界，等于让第二次取整决定结论 —— 本页上一版正是这样把 2024Q1 与 2025Q1 两季判成了「超出上限」，而按公司自己的口径它们恰好落在上限上。")
    if net_income_bridge is not None and consensus is not None:
        expectation_n = next(ex["n"] for ex in highlight_ex if ex["title"].startswith("对市场预期"))
        notes.append(
            f"Exhibit {expectation_n} 的「核心」口径是报告净利减 {net_income_bridge['one_off_short']} "
            "税前一次性收益的算术差，未做税务调整；核心 EPS 按核心 / 报告净利之比折算报告 EPS。"
            "两者都不是公司定义的调整后指标，只用于回答「这个季度是不是真的超预期」。")
    notes += [
        "本页不接入月度营收公告，全页维持季度更新节奏。",
        "本页只发布公司披露值、可复算的简单派生值，以及明确标注的市场预期；D 标记代表 Derived / 自算。",
        "市场预期一律标注为「市场预期」并给出取数时点，不写卖方机构名，也不发布评级、目标价或估值。",
        "隐含 ASP 为季度美元收入除以晶圆出货，仅用于量价拆分，不等同任何制程或封装的实际定价。",
    ]
    if net_income_bridge is not None:
        notes.append(
            f"核心净利为报告净利减 {net_income_bridge['one_off_short']} 相关税前收益的算术差，"
            "未做税务调整，也不是公司定义的调整后利润。")
    notes += [
        "自由现金流按 TSMC 口径，以经营现金流减季度现金支付资本开支复算；不是利润表 non-GAAP 指标。",
        "收入趋势采用美元口径，现金流采用新台币口径；季度现金支付 CapEx 不与全年美元 CapEx 预算相加。",
        "制程占比的分母为晶圆收入，平台占比的分母为净收入；两组 mix 不可直接相加。",
        "本页已知未接入：ROE、折旧、R&D / SG&A 费用线、IoT / 汽车 / DCE 平台占比、地区与客户类型组合，以及税率的指引兑现历史（尚未录入；收入、毛利率与营业利润率三项的逐季指引区间已全部录入，见第一节）。",
        "电话会文字稿仅链接 TSMC 官方 IR 托管版本，公开仓不复制原件或逐字内容。",
    ]

    audit_words = {"unaudited": "未审计", "audited": "已审计"}[latest["audit_status"]]
    return {
        "schema_version": "quarterly-dashboard/tsm-v3",
        "page": {"slug": "tsm", "language": "zh-CN"},
        "company": {
            "ticker": "TSM",
            "name": "TSMC",
            "group": "semiconductor_ai",
            "accounting_standard": "TIFRS",
        },
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · TSM",
        "title": f"TSMC (TSM)：{period} 季报仪表盘",
        "subtitle": (f"截至 {latest['period_end']} · 发布 {latest['release_date']} · TIFRS · {audit_words} · "
                     "收入为美元，现金流为新台币，另有注明除外"),
        "headline": headline,
        "brief": (
            f'<h4>本季{cn_count(len(articles))}条主线</h4><div class="takeaway-grid">'
            + "".join(articles)
            + '</div>'
        ),
        "source": source,
        "source_url": hub["url"],
        "source_links": staging["sources"] + (blocks["declared_dividend"] or {}).get("links", []),
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {
                "id": "settled",
                "title": "一、上季跟踪指标兑现了吗",
                "description": (
                    ("先结算上季留下的东西：" if closure is not None or prior is not None else "")
                    + (f"{sum(closure['counts'])} 条待验证问题闭环了几条"
                       + ("（被证伪的那条连同它的长序列一起画出）" if inventory_expectation else "")
                       if closure is not None else "")
                    + ("；" if closure is not None and prior is not None else "")
                    + (f"上季分析第 8 节「关键观察指标」{prior_rows} 行里，申报读得到的 "
                       f"{len(prior['quantified'])} 条量化阈值逐条对本季实际值（一张总览、每条一张长序列）"
                       + (f"，另 {len(prior['not_carried'])} 行本季读不到："
                          + "；".join(f"{item['short']}——{fill_story(item['why'], story_values)}"
                                     for item in prior["not_carried"])
                          if prior.get("not_carried") else "")
                       if prior is not None else "")
                    + ("。然后看" if closure is not None or prior is not None else "先看")
                    + "这一季对公司自己的指引兑现到什么程度。"
                    "公司每季指引三个数——收入、毛利率、营业利润率——三张图各给一条完整记录，"
                    "收入那条后面紧跟超额里经营与汇率两条腿的拆分。"
                    f"这条记录是 {guided[0]} 起的 {finished_count} 个已完结季，不是最近{cn_count(len(periods))}季"
                    + ("：只看最近那一段，三条指引都像「从不被打破的底线」；整段记录里三条各自都被打破过。"
                       if recent_clean and all_broken else "。")
                ),
                "exhibits": settled_ex,
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": (
                    "收入与指引、量价拆分、"
                    + ("毛利率拐点" if next_gm_mid is not None and next_gm_mid < gm_levels[-1] else "毛利率")
                    + ("，对市场预期" if consensus is not None else "")
                    + ("与净利里的一次性成分" if bridge_chart and consensus is not None else
                       "，净利里的一次性成分" if bridge_chart else "")
                    + (("，资本开支上调" if capex_raised else "，资本开支") if capex_chart else "")
                    + "与现金流。"
                ),
                "exhibits": highlight_ex,
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": "当前值离下季阈值还有多远，统一用「距阈值余量」口径。",
                "exhibits": next_ex,
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": "TSM 专属的常规序列：制程世代迁移、平台结构、营运资金与资本强度。",
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": notes,
        "footer": "TSM quarterly results · 数据来自 TSMC 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def financials_fx(staging: dict) -> float:
    """The quarter's realised USD/NTD when no guidance block is stamped for it."""
    return staging["long_history"]["financials"]["usd_ntd_actual"][-1]


def guidance_rows(guidance: dict, financials: dict, period: str) -> list[list[str]]:
    """This call's guidance table, row by row from the stamped block."""
    reported, prior, upcoming = guidance["reported"], guidance["prior_guide"], guidance["next_guide"]
    fiscal = guidance["fiscal_year"]
    next_mid = sum(upcoming["revenue_usd_bn"]) / 2
    rows = [[
        "收入（美元）",
        f"US${prior['revenue_usd_bn'][0]:.1f}–{prior['revenue_usd_bn'][1]:.1f}B",
        f"US${reported['revenue_usd_bn']:.2f}B",
        delivery_words(reported["revenue_usd_bn"], *prior["revenue_usd_bn"], unit="B"),
        f"US${upcoming['revenue_usd_bn'][0]:.1f}–{upcoming['revenue_usd_bn'][1]:.1f}B",
        f"中值 US${next_mid:.1f}B；环比 {signed(pct_change(next_mid, reported['revenue_usd_bn']))} D",
    ]]
    for name, key in (("毛利率", "gross_margin_pct"), ("营业利润率", "operating_margin_pct")):
        rows.append([
            name,
            f"{prior[key][0]:.1f}–{prior[key][1]:.1f}%",
            f"{reported[key]:.1f}%",
            delivery_words(reported[key], *prior[key]),
            f"{upcoming[key][0]:.1f}–{upcoming[key][1]:.1f}%",
            f"中值环比 {sum(upcoming[key]) / 2 - reported[key]:+.1f}pp D",
        ])
    against_assumption = pct_change(reported["usd_ntd"], prior["usd_ntd"])
    next_against = pct_change(upcoming["usd_ntd"], reported["usd_ntd"])
    rows.append([
        "USD / NTD",
        f"{prior['usd_ntd']}",
        f"{reported['usd_ntd']:.2f}",
        f"较假设{'低' if against_assumption < 0 else '高'} {abs(against_assumption):.1f}% D",
        f"{upcoming['usd_ntd']:.1f}",
        f"较 {quarter_word(period)} 实际{'高' if next_against > 0 else '低'} {abs(next_against):.1f}% D",
    ])
    capex, capex_prior = guidance["fy_capex_usd_bn"], guidance["fy_capex_prior_usd_bn"]
    capex_move = sum(capex) / 2 - sum(capex_prior) / 2
    rows += [
        [f"FY{fiscal} 美元收入增速", guidance["fy_revenue_growth_prior_cn"], "—",
         guidance["fy_revenue_growth_change_cn"], guidance["fy_revenue_growth_cn"], "公司年度 outlook"],
        [f"FY{fiscal} CapEx",
         f"{usd_range(capex_prior)}；{guidance['fy_capex_prior_positioning_cn']}", "—",
         "上调" if capex_move > 0 else "下调" if capex_move < 0 else "重申",
         usd_range(capex),
         f"中值较先前高端锚点 {'+' if sum(capex) / 2 >= capex_prior[1] else '−'}"
         f"US${abs(sum(capex) / 2 - capex_prior[1]):.0f}B D"],
    ]
    # The two dilution lines exist only in quarters whose call quantified them.
    n2 = guidance.get("n2_gross_margin_dilution_pp")
    if n2:
        rows.append([f"{guidance['n2_gross_margin_dilution_half']} N2 毛利率稀释", "—", "—", "—",
                     f"{n2[0]}–{n2[1]}pp", "管理层量化"])
    early = guidance.get("overseas_fab_gross_margin_dilution_early_pp")
    late = guidance.get("overseas_fab_gross_margin_dilution_latter_pp")
    if early and late:
        rows.append(["海外厂毛利率稀释", "—", "—", "—",
                     f"初期 {early[0]}–{early[1]}pp", f"后期扩大至 {late[0]}–{late[1]}pp"])
    floor = guidance["long_term_gross_margin_floor_pct"]
    gm_now = financials["gross_margin_pct"][-1]
    rows.append([
        "长期 through-cycle 毛利率",
        f"{floor}% 及以上",
        f"{gm_now:.1f}%",
        f"{'高出' if gm_now >= floor else '低于'} {abs(gm_now - floor):.1f}pp D",
        f"{floor}% 及以上",
        guidance["long_term_gross_margin_change_cn"],
    ])
    return rows


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "tsm.js"), payload, "tsm")
    shell_dir = ROOT / "tsm"
    shell_dir.mkdir(exist_ok=True)
    # Rendered here, not at import: the shell stamps the payload's content
    # hash into its <script src>, so it has to be built after write_dash.
    (shell_dir / "index.html").write_text(
        render_shell("TSM", "tsm"), encoding="utf-8")
    # Counted, not typed: this line claimed "13 charts in 4 sections" while the
    # page had grown to 21.
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(
        f"TSM page: {charts} charts in {len(payload['sections'])} sections "
        f"+ {len(payload['tables'])} audit tables"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
