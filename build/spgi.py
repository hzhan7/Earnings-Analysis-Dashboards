#!/usr/bin/env python3
"""Build the SPGI (S&P Global) quarterly-results page.

Same four-part, chart-led shape as the other company pages (上季兑现 → 本季重点
→ 下季跟踪 → 长期常规).  S&P Global runs on a calendar fiscal year, so every
quarter label here is the calendar quarter it covers and no mapping is needed.

What makes this page different is the shape of the guidance record.

**S&P Global has never published a quarterly outlook.**  What it files, in the
EX-99.1 of every quarterly earnings 8-K, is a **full-year** outlook that it then
revises once a quarter.  So the object the Amazon, Cadence, NVIDIA, Synopsys,
TSMC and Meta pages are built on -- a next-quarter range and the quarter that
settles it -- does not exist anywhere in this filing history.  Inventing one
would mean transcribing call material that cannot be checked against a second
source, which is the failure this repo exists to avoid.

The honest isomorph is built instead: for each fiscal year the successive
vintages (opening guidance → Q1 → Q2 → Q3 revision) are drawn as one continuous
band, and the year's reported result lands on the **final** vintage, the cell
that actually settles it.  Every vintage from FY2016 on comes out of the
releases themselves.

That record answers a question the quarterly pages cannot ask, and the answer is
two-sided in a way that only shows up because the metrics sit in the same table:
adjusted diluted EPS has not landed below its own final range, while GAAP diluted
EPS on the same table has, repeatedly.  Every count in those sentences is
recounted from the series on each build -- they were typed as "5 of 7" and "3 of
7", and stayed typed after the record was extended back to FY2016.

The page is rolled by editing ``series/spgi.json`` alone.  What only one quarter
has -- last quarter's thresholds settled, next quarter's thresholds, the
quarter's pro forma figures and its story (this quarter: the Mobility spin) --
sits in blocks stamped with the quarter (``board.stamped_block``); ``_checks``
is a separate reading of the quarter's release that the tests hold the page to
and this builder never reads.

Two structural breaks are marked rather than smoothed.  The IHS Markit merger
closed 2022-02-28, so FY2022 is a stub year and the level is not readable across
it.  And Mobility was spun off on **2026-07-01** -- one day after the quarter
this page reports -- so the Q2 2026 release rebased the FY2026 outlook onto a
basis that excludes it, dropping adjusted EPS from US$19.40-19.65 to
US$17.50-17.75 while saying in as many words that the two are "not directly
comparable".  The reported statements on this page still include Mobility,
because every filed statement to date does.

Published numbers are company-reported or transparent arithmetic.  Market
expectations are labelled as such, with no broker attribution.
"""

from __future__ import annotations

import json
import re
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
    number_exhibits,
    stamped_block,
    threshold_exhibit,
    threshold_table,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "spgi.json"
DATA_DIR = ROOT / "data"

# One tick per year keeps the 38- and 42-quarter axes readable.
LONG_STEP = 4


def compact_period(period: str) -> str:
    """``'Q2 2026'`` → ``'Q2'26'``."""
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


def fiscal_of(vintage_label: str) -> str:
    """``'FY24 Q3'`` → ``'FY24'`` -- the deviation chart counts years, not vintages."""
    return vintage_label.split()[0].rstrip("*†")


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def rounded(values: list[float | None], digits: int = 6) -> list[float | None]:
    return [None if value is None else round(value, digits) for value in values]


def operating_margin_ex_credits(long_history: dict) -> list[float]:
    """Operating margin before the two credits SPGI adds below the expense line.

    Its income statement reads `revenue - total expenses + gain on dispositions
    + equity income = operating profit`, so subtracting the filed expense line
    from the filed revenue line leaves operating profit before both credits --
    two filed legs and no estimate. Doing it the other way round, by taking the
    disposition gain back off the operating profit, would put a hole in every
    fiscal fourth quarter: the filer never tags that line for Q4.
    """
    return [
        (revenue - expenses) / revenue * 100
        for revenue, expenses in zip(long_history["revenue_usd_m"],
                                     long_history["total_expenses_usd_m"])
    ]


def quarter_words(label: str) -> str:
    """``'Q2 2026'`` → ``'2026 年第二季度'``."""
    quarter, year = display_period(label).split()
    return f"{year} 年第{cn_ordinal(int(quarter[1]))}季度"


def release_source(staging: dict) -> dict:
    """This quarter's own release in `sources`, found by its label."""
    label = f"S&P Global {quarter_words(staging['periods'][-1])}业绩新闻稿"
    found = next((item for item in staging["sources"] if item["label"].startswith(label)), None)
    if found is None:
        raise ValueError(f"series `sources` has no entry for the {label}: add this "
                         "quarter's release with the roll")
    return found


def periodic_report_words(staging: dict) -> str:
    """「与截至 … 的 10-Q」 when `sources` carries the quarter's own 10-Q / 10-K."""
    end = staging["period_ends"][-1]
    year = display_period(staging["periods"][-1]).split()[1]
    for form, label in (("10-Q", f"截至 {end} 的 10-Q"), ("10-K", f"FY{year} 10-K")):
        if any(item["label"].startswith(label) for item in staging["sources"]):
            return f"与截至 {end} 的 {form}"
    return ""


def free_cash_flow(staging: dict) -> list[float]:
    capital = staging["capital_allocation_usd_m"]
    return [o - c for o, c in zip(capital["operating_cash_flow"], capital["capex"])]


def gross_revenue_by_type(types: dict) -> list[float]:
    return [sum(types[key][i] for key in
                ("subscription", "non_subscription_transaction", "non_transaction",
                 "asset_linked_fees", "sales_usage_royalties", "recurring_variable"))
            for i in range(len(types["quarters"]))]


def period_order(label: str) -> tuple[int, int]:
    """``'Q2 2026'`` → ``(2026, 2)``."""
    quarter, year = display_period(label).split()
    return int(year), int(quarter[1])


def shift_quarter(label: str, step: int) -> str:
    """``'Q2 2026'``, 1 → ``'Q3 2026'``; ``'Q4 2026'``, 1 → ``'Q1 2027'``."""
    year, quarter = period_order(label)
    index = year * 4 + quarter - 1 + step
    return f"Q{index % 4 + 1} {index // 4}"


def ytd_words(label: str) -> str:
    """How far into its year a quarter is, the way the prose names it."""
    return {1: "第一季度", 2: "上半年", 3: "前三季度", 4: "全年"}[period_order(label)[1]]


def ytd_sum(quarters: list[str], values: list[float | None], label: str) -> float | None:
    """The year-to-date sum through ``label``'s quarter; None while a quarter is missing."""
    year, quarter = period_order(label)
    cells = [f"Q{n} {year}" for n in range(1, quarter + 1)]
    if not all(cell in quarters and values[quarters.index(cell)] is not None for cell in cells):
        return None
    return sum(values[quarters.index(cell)] for cell in cells)


def ratings_total(staging: dict) -> list[float]:
    """Ratings revenue, as its two filed legs add up."""
    split = staging["ratings_revenue_split_usd_m"]
    return [t + n for t, n in zip(split["transaction"], split["non_transaction"])]


def quarter_block(staging: dict, key: str, reads: str) -> dict:
    """A stamped block a tracked reading cannot do without."""
    block = stamped_block(staging, key, staging["periods"][-1])
    if block is None:
        raise ValueError(f"tracked reading {reads!r} needs the series block `{key}` stamped for "
                         f"{staging['periods'][-1]}: add it with the roll")
    return block


def kpi_reading(staging: dict, reads: str) -> float:
    """A tracked threshold's current value, read from the series it names.

    The two reports word their thresholds their own way; each entry says which of
    these readings settles it, so carrying a threshold from section three into
    next quarter's section one is a series edit, not a builder edit.
    """
    period = staging["periods"][-1]
    if reads == "ytd_buyback":
        capital = staging["capital_allocation_usd_m"]
        value = ytd_sum(capital["quarters"], capital["buyback"], period)
        if value is None:
            raise ValueError(f"the buyback series has no complete year to date through {period}")
        return value
    if reads == "ratings_yoy":
        total = ratings_total(staging)
        return pct_change(total[-1], total[-5])
    if reads == "mi_yoy":
        mi = staging["segments_usd_m"]["revenue"]["market_intelligence"]
        return pct_change(mi[-1], mi[-5])
    if reads == "energy_organic_cc":
        return pct_change(*quarter_block(staging, "quarter_figures", reads)["energy_organic_cc_revenue_usd_m"])
    if reads == "ytd_adjusted_fcf_growth":
        return pct_change(*quarter_block(staging, "ytd_vs_guidance", reads)["adjusted_free_cash_flow_usd_m"])
    raise ValueError(f"tracked reading {reads!r} is not one this page can read: add it to kpi_reading")


def with_current(staging: dict, block: dict | None, key: str) -> list[dict]:
    """The block's thresholds with their current value read from the series.

    The value is never typed into the block: the old one carried 7.62, 43.44,
    49.15 rounded by hand, and the headroom computed from the rounded figure
    printed a 49.1% beside a chart that said 49.2%.
    """
    if not block:
        return []
    return [{**entry, key: kpi_reading(staging, entry["reads"])} for entry in block["quantified"]]


def plain_text(html: str) -> str:
    """Strip inline markup for the slots the renderer escapes rather than parses.

    `assets/page.js` writes exhibit notes with `innerHTML`, but `title`,
    `subtitle`, `headline` and `tracker` go through `textContent` and both the
    section descriptions and the 口径与方法说明 list go through `esc()`. A `<b>`
    that reads as emphasis on a chart caption reaches the reader as the literal
    characters `<b>` in those five places, so the same sentence is written once
    with markup and stripped here.
    """
    return re.sub(r"<[^>]+>", "", html)


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


SOURCE_8K = (
    "全年指引的每一档 vintage 逐字取自当季业绩 8-K 的 EX-99.1 展望表；"
    "实际值取自该财年第四季度业绩 8-K 的 EX-99.1，与 10-K 交叉核对过。"
)

# The timing caveat this page needs is *stronger* than the quarterly pages', and
# it is the first thing a reader has to know about the record. Cadence's outlook
# lands a few weeks into the quarter it guides; S&P Global's third revision lands
# in late October, with roughly ten of twelve months already banked.
TIMING = "该财年<b>进行途中</b>"

def vintage_months(record: dict) -> str:
    """「2-3 月、4-5 月、7-8 月与 10-11 月」: when each vintage slot was actually filed.

    Typed as 「2 月、4-5 月…」, which the FY2022 opening range -- given at the
    2022-03-01 investor day -- already contradicted.
    """
    months: dict[str, set[int]] = {}
    for slot, filed in zip(record["vintage_slots"], record["filed"]):
        months.setdefault(slot, set()).add(int(filed[5:7]))
    words = [f"{min(m)}-{max(m)} 月" if min(m) != max(m) else f"{min(m)} 月"
             for m in (months[slot] for slot in ("initial", "q1", "q2", "q3"))]
    return "、".join(words[:-1]) + "与 " + words[-1]


def timing_warning(record: dict) -> str:
    return (
        "<b>先读这一句，再读柱子。</b>这不是一份事前预测的记录。"
        f"每个财年的四档指引分别发布在该年的 {vintage_months(record)} —— "
        "也就是说，「初次」那一档发布时全年还剩十一个月，而「Q3 修订」那一档发布时"
        "全年已经过去约四分之三，公司手里已经有三个季度的实际数。"
        "越靠右的那一档越不是预测、越接近一次预告，"
        "所以「末次指引从没被跌破」这句话的分量远小于它的字面。"
        "真正带信息的是最左边那一档，见 Exhibit {EX_CONVERGE}。"
    )

MOBILITY_BREAK = (
    "<b>{where}是口径重设，不是下调。</b>"
    "公司于 2026-07-01 完成 Mobility 分拆（Mobility Global，NYSE: MBGL），"
    "并在 2026-07-28 的业绩新闻稿里把 FY2026 全年指引整体挪到不含 Mobility 的口径上，"
    "同一份新闻稿写明「Current adjusted financial guidance is not directly comparable "
    "to prior guidance」。本页保留这根落差很大的柱子并在此说明，而不是把它悄悄改掉。"
)


# ── section one: the full-year guidance record ───────────────────────────────
def minus(value: float, digits: int = 1) -> str:
    """``-7.74`` → ``'−7.7%'`` with the typographic minus the prose uses; a value
    that rounds to nothing prints as ``'0.0%'`` rather than ``'−0.0%'``."""
    if round(value, digits) == 0:
        return f"{0:.{digits}f}%"
    return f"{value:+.{digits}f}%".replace("-", "−")


def final_rows(record: dict, lo_key: str, hi_key: str, actual_key: str) -> list[tuple]:
    """(fiscal year, low, high, actual) for every settled cell of one metric."""
    return [(record["fiscal_years"][i], record[lo_key][i], record[hi_key][i], value)
            for i, value in enumerate(record[actual_key])
            if value is not None and record[lo_key][i] is not None]


def final_deviations(record: dict, lo_key: str, hi_key: str, actual_key: str) -> list[tuple]:
    """(``'FY17'``, % from the final midpoint) -- the labels the deviation chart prints."""
    return [(f"FY{str(year)[2:]}", pct_change(actual, (low + high) / 2))
            for year, low, high, actual in final_rows(record, lo_key, hi_key, actual_key)]


def year_span(years: list[int]) -> str:
    """``[2018, 2019, 2020, 2023]`` → ``'FY2018–FY2020、FY2023'``."""
    runs = [[years[0]]]
    for year in years[1:]:
        if year == runs[-1][-1] + 1:
            runs[-1].append(year)
        else:
            runs.append([year])
    return "、".join(f"FY{run[0]}" if len(run) == 1 else f"FY{run[0]}–FY{run[-1]}" for run in runs)


def unsettled_fcf_words(record: dict) -> str:
    """Finished years whose cash guidance never reached the vintage that settles them.

    FY2018-FY2020 put free cash flow in the opening release only; the Q1-Q3
    releases of those years do not restate it. The band settles a year on its
    last vintage and draws a result only where a range stands, so those years
    carry guidance and no diamond -- which reads as "not reported yet" unless
    the chart says why. Said only while some year is in that state.
    """
    finished = {year for year, value in zip(record["fiscal_years"], record["actual_adjusted_eps"])
                if value is not None}
    years, opening_only = [], True
    for year in sorted(finished):
        cells = [(slot, low) for fy, slot, low in zip(record["fiscal_years"], record["vintage_slots"],
                                                       record["guide_adjusted_fcf_lo_usd_m"])
                 if fy == year]
        guided = [slot for slot, low in cells if low is not None]
        if not guided or cells[-1][1] is not None:
            continue
        years.append(year)
        opening_only = opening_only and guided == ["initial"]
    if not years:
        return ""
    these = "这一年" if len(years) == 1 else "这几年"
    if opening_only:
        return (f"{year_span(years)} 的现金指引只在年初那一档给过，其后几次修订的新闻稿都没有再提，"
                f"没有末次那一格可结算，所以图上{these}只有年初一格、没有菱形。")
    return f"{year_span(years)} 的末次修订没有现金指引，无从结算，所以图上{these}没有菱形。"


def empty_gaap_words(record: dict) -> str:
    """「FY2016 四档、FY2021 前三档、…」: the vintages that carry an adjusted range and no GAAP one."""
    by_year = {}
    for year, adjusted, gaap in zip(record["fiscal_years"], record["guide_adjusted_eps_lo"],
                                    record["guide_gaap_eps_lo"]):
        slots = by_year.setdefault(year, [])
        slots.append(adjusted is not None and gaap is None)
    words = []
    for year, slots in by_year.items():
        empty = sum(slots)
        if not empty:
            continue
        if empty == len(slots):
            words.append(f"FY{year} {cn_count(empty)}档" if empty > 1 else f"FY{year} 那一档")
        elif all(slots[:empty]):
            words.append(f"FY{year} " + ("首档" if empty == 1 else f"前{cn_count(empty)}档"))
        else:
            words.append(f"FY{year} 有{cn_count(empty)}档")
    return "、".join(words)


def guidance_charts(staging: dict, fcf_story: str | None = None) -> tuple[list[dict], dict]:
    """The full-year outlook's in-year revision path, per guided metric.

    ``delivery_band`` takes vintage labels on the x axis and the year's reported
    result on the vintage that settles it, so a fiscal year occupies as many
    cells as it had revisions and exactly one of them carries a diamond. Both it
    and ``midpoint_deviation`` are told the unit is a year rather than a quarter;
    without that the titles would count seven fiscal years as seven quarters.
    """
    record = staging["annual_guidance_history"]
    labels = record["vintages"]
    break_at = record["basis_break_at"]

    def band(ref, metric, lo_key, hi_key, actual_key, *, fmt, ylab, unit,
             extra_note, use_break=True):
        return delivery_band(
            ref, metric, labels,
            record[lo_key], record[hi_key], record[actual_key],
            fmt=fmt, ylab=ylab, unit=unit, venue="业绩发布",
            timing=TIMING, period_word="年",
            break_at=break_at if use_break else None,
            break_label=record["basis_break_label"],
            src_extra=SOURCE_8K, extra_note=extra_note,
        )

    def deviation(ref, metric, lo_key, hi_key, actual_key, *, mode, extra_note):
        finished = sum(1 for v in record[actual_key] if v is not None)
        return midpoint_deviation(
            ref, metric, labels,
            record[lo_key], record[hi_key], record[actual_key],
            mode=mode, window=finished, label=fiscal_of, period_word="年",
            src_extra=SOURCE_8K + "偏离为实际值相对该年<b>末次</b>指引中值的自算值。",
            extra_note=extra_note,
        )

    adj_lo = record["guide_adjusted_eps_lo"]
    adj_hi = record["guide_adjusted_eps_hi"]
    adj_actual = record["actual_adjusted_eps"]
    gaap_actual = record["actual_gaap_eps"]

    def tally(lo, hi, actual):
        above = inside = below = 0
        for low, high, value in zip(lo, hi, actual):
            if value is None or low is None:
                continue
            if value > high:
                above += 1
            elif value < low:
                below += 1
            else:
                inside += 1
        return above, inside, below

    adj_above, adj_inside, adj_below = tally(adj_lo, adj_hi, adj_actual)
    gaap_above, gaap_inside, gaap_below = tally(
        record["guide_gaap_eps_lo"], record["guide_gaap_eps_hi"], gaap_actual)
    labels_all = record["vintages"]
    rebase = ""
    if break_at is not None:
        where = ("最右边那一档" if break_at == len(labels_all) - 1
                 else f"{labels_all[break_at]} 那一档")
        rebase = MOBILITY_BREAK.format(where=where)

    adjusted_band = band(
        "EX_ADJ_BAND", "调整后摊薄 EPS",
        "guide_adjusted_eps_lo", "guide_adjusted_eps_hi", "actual_adjusted_eps",
        fmt="usd2", ylab="US$/股", unit="US$",
        extra_note=(
            f"<b>每个财年占据连续的几格</b>：年初首次指引、Q1、Q2、Q3 修订，"
            f"实际值只落在该年<b>末次</b>那一格上，因为那才是结算这一年的那一档。"
            f"{adj_above + adj_inside + adj_below} 个已完结财年里"
            f"{adj_above} 年高于末次区间上限、{adj_inside} 年落在区间内，"
            + ("<b>一年都没有跌破过下限</b>。" if not adj_below else
               f"<b>{adj_below} 年跌破下限</b>。")
            + timing_warning(record)
            + rebase
        ),
    )
    adj_devs = final_deviations(record, "guide_adjusted_eps_lo", "guide_adjusted_eps_hi",
                                "actual_adjusted_eps")
    adj_negative = [(year, value) for year, value in adj_devs if value <= 0]
    lengths = [abs(value) for _, value in adj_devs]
    adjusted_dev = deviation(
        "EX_ADJ_DEV", "调整后摊薄 EPS",
        "guide_adjusted_eps_lo", "guide_adjusted_eps_hi", "actual_adjusted_eps",
        mode="pct",
        extra_note=(
            ("柱子全部为正" if not adj_negative else
             f"{cn_count(len(adj_devs))}根柱子里{cn_count(len(adj_devs) - len(adj_negative))}根为正"
             f"（{'、'.join(f'{year} 为 {minus(value)}' for year, value in adj_negative)}）")
            + ("，而且长度在逐年收敛。" if all(b <= a for a, b in zip(lengths, lengths[1:])) else
               "，长度也没有随年份收敛。")
            + "把它和 GAAP 那张（Exhibit {EX_GAAP_DEV}）并排看："
            "同一张表上的两个数字，一个常年为正、一个正负都有。"
        ),
    )

    gaap_band = band(
        "EX_GAAP_BAND", "GAAP 摊薄 EPS",
        "guide_gaap_eps_lo", "guide_gaap_eps_hi", "actual_gaap_eps",
        fmt="usd2", ylab="US$/股", unit="US$",
        extra_note=(
            f"<b>这张图是本页存在的理由，要和上面那张并排读。</b>"
            f"同一份新闻稿、同一张展望表、同一个财年，"
            f"调整后 EPS {adj_below} 次跌破下限，GAAP EPS 却"
            f"<b>{gaap_below} 次跌破下限</b>（{gaap_above} 年高于上限、"
            f"{gaap_inside} 年落在区间内）。"
            "两者之差全部落在调整线以下：并购无形资产摊销、处置损益与减值 —— "
            "也就是公司自己选择剔除掉的那些项。"
            + ("<b>那条从不失手的曲线，是公司自己定义的那一条。</b>" if not adj_below else "")
            + f"另有几格是空的：{empty_gaap_words(record)}，"
            "公司当时只给调整后口径、不给 GAAP 口径（FY2016 的原因见「口径与方法说明」）。"
        ),
    )
    gaap_devs = final_deviations(record, "guide_gaap_eps_lo", "guide_gaap_eps_hi", "actual_gaap_eps")
    # The note used to say the deepest bar was FY2023's; extended back to FY2016
    # the deepest is FY2017's, which the helper's own caption already names.
    gaap_negative = sorted((row for row in gaap_devs if row[1] < 0), key=lambda row: row[1])
    rank = next((i for i, (year, _) in enumerate(gaap_negative) if year == "FY23"), None)
    engineering = ("那一年 Engineering Solutions 于 5 月出售并计入处置损失，"
                   "而它从未被列作终止经营，所以损失直接落在 GAAP 每股收益里。")
    if not gaap_negative:
        shape = "这里没有负柱。"
    elif rank == 0:
        shape = "这里有明显的负柱，而且最深的一根出现在 FY2023 —— " + engineering
    elif rank == 1:
        shape = (f"这里有明显的负柱，FY2023 那一根（{minus(gaap_negative[1][1])}）"
                 f"仅次于 FY20{gaap_negative[0][0][2:]} —— " + engineering)
    else:
        shape = "这里有明显的负柱。"
    gaap_dev = deviation(
        "EX_GAAP_DEV", "GAAP 摊薄 EPS",
        "guide_gaap_eps_lo", "guide_gaap_eps_hi", "actual_gaap_eps",
        mode="pct",
        extra_note="与调整后那张（Exhibit {EX_ADJ_DEV}）不是同一个形状：" + shape,
    )

    # ── the chart the band cannot draw: how early was the year knowable ──────
    converge = convergence_chart(staging)
    revenue_years = sorted({year for year, low in zip(record["fiscal_years"],
                                                      record["guide_revenue_growth_lo_pct"])
                            if low is not None})

    revenue_band = band(
        "EX_REVG_BAND", "GAAP 收入增速",
        "guide_revenue_growth_lo_pct", "guide_revenue_growth_hi_pct",
        "actual_revenue_growth_pct",
        fmt="pct1", ylab="全年收入同比", unit="%",
        extra_note=(
            f"<b>这条指引只有{cn_count(len(revenue_years))}年，因为再往前公司根本不给数字。</b>"
            f"FY{record['fiscal_years'][0]}–FY{revenue_years[0] - 1} 的展望段落里，"
            "收入增速是「mid single-digits」这类文字，"
            "不是可结算的区间；数字化的收入增速指引最早出现在 2023 年第一季度那份新闻稿里。"
            "实际值是本页按申报的全年收入自算的同比（D），"
            "公司自己在新闻稿里只印到整数百分点。"
        ),
    )
    revenue_dev = deviation(
        "EX_REVG_DEV", "GAAP 收入增速",
        "guide_revenue_growth_lo_pct", "guide_revenue_growth_hi_pct",
        "actual_revenue_growth_pct", mode="pp",
        extra_note=(
            f"样本只有{cn_count(sum(1 for v in record['actual_revenue_growth_pct'] if v is not None))}年，"
            "不足以谈规律，放在这里是为了让读者看到"
            "同一张展望表上不同指标的可得年份差得很远。"
        ),
    )

    fcf_rows = final_rows(record, "guide_adjusted_fcf_lo_usd_m", "guide_adjusted_fcf_hi_usd_m",
                          "actual_adjusted_fcf_usd_m")
    fcf_below = [row for row in fcf_rows if row[3] < row[1]]
    fcf_above = [row for row in fcf_rows if row[3] > row[2]]

    def often_missed(counts):
        return 2 * counts[2] >= sum(counts) > 0

    others = {
        "调整后 EPS": (adj_above, adj_inside, adj_below),
        "GAAP EPS": (gaap_above, gaap_inside, gaap_below),
        "收入增速": tally(record["guide_revenue_growth_lo_pct"], record["guide_revenue_growth_hi_pct"],
                      record["actual_revenue_growth_pct"]),
    }
    often = often_missed((len(fcf_above), len(fcf_rows) - len(fcf_above) - len(fcf_below), len(fcf_below)))
    also_often = [name for name, counts in others.items() if often_missed(counts)]

    def fcf_range(row):
        return (f"US${row[1]:,.0f}M" if row[1] == row[2] else f"US${row[1]:,.0f}–{row[2]:,.0f}M")

    fcf_band = band(
        "EX_FCF_BAND", "调整后自由现金流",
        "guide_adjusted_fcf_lo_usd_m", "guide_adjusted_fcf_hi_usd_m",
        "actual_adjusted_fcf_usd_m",
        fmt="f0c", ylab="US$M", unit="US$M", use_break=False,
        extra_note=(
            ((f"<b>这是记录里除 {'、'.join(also_often)} 之外唯一一条经常做不到的指引。</b>" if also_often
              else "<b>这是记录里唯一一条经常做不到的指引。</b>") if often else "")
            + f"{cn_count(len(fcf_rows))}个已完结财年里{cn_count(len(fcf_below))}年跌破下限"
            + ("：" + "；".join(f"FY{row[0]} 指引 {fcf_range(row)}、实际 US${row[3]:,.0f}M" for row in fcf_below)
               if fcf_below else "")
            + "。"
            + ((f"唯一超额的 FY{fcf_above[0][0]} 是一次"
                + ("大幅超额。" if pct_change(fcf_above[0][3], fcf_above[0][2]) > 5 else "超额。"))
               if len(fcf_above) == 1 else "")
            + unsettled_fcf_words(record)
            + ("把它和上面两张 EPS 图并排看："
               "同一家公司，<b>调整后每股收益的指引几乎不失手，现金的指引经常失手</b>。"
               if often and adj_below <= 1 else "")
            + (fcf_story or "")
        ),
    )
    if record["guide_adjusted_fcf_lo_usd_m"][-1] is None and "annot" in fcf_band:
        # `delivery_band` closes on "the last cell has only its band, the result
        # is pending" -- true of a metric still being guided, false of this one
        # once the company stops giving it, and it would contradict the story
        # sentence just before it.
        pending = f"最后一格 {labels[-1]} 只有指引色块，实际值待披露。"
        if pending not in fcf_band["note"]:
            raise ValueError("delivery_band's pending sentence changed; update the FCF band")
        fcf_band["note"] = fcf_band["note"].replace(pending, "")
        del fcf_band["annot"]
    points = [row for row in fcf_rows if row[1] == row[2]]
    fcf_dev = deviation(
        "EX_FCF_DEV", "调整后自由现金流",
        "guide_adjusted_fcf_lo_usd_m", "guide_adjusted_fcf_hi_usd_m",
        "actual_adjusted_fcf_usd_m", mode="pct",
        extra_note=(
            "、".join(f"FY{row[0]}" for row in points)
            + (" 那一档的指引是单点值" if len(points) == 1 else " 的末次指引都是单点值")
            + "（" + "".join(f"「approximately ${row[1] / 1000:g} billion」" for row in points)
            + "）而不是区间，所以" + ("它的" if len(points) == 1 else "") + "中值就是那个点本身。"
            if points else "每一年的末次指引都是区间，中值取区间中点。"
        ),
    )

    charts = [adjusted_band, adjusted_dev, gaap_band, gaap_dev, converge,
              revenue_band, revenue_dev, fcf_band, fcf_dev]
    stats = {
        "adjusted": (adj_above, adj_inside, adj_below),
        "gaap": (gaap_above, gaap_inside, gaap_below),
    }
    return charts, stats


def rebased_vintages(record: dict) -> set[int]:
    """The rebased year's vintages published before the rebase.

    They guide the company as it was before the spin, and the year's reported
    result will describe it after, so comparing the two would score a change of
    perimeter as a forecast miss. Nothing settles until that year closes; this
    keeps the first roll that settles it from printing FY2026 as a broken
    opening guidance.
    """
    at = record["basis_break_at"]
    if at is None:
        return set()
    return {i for i in range(at) if record["fiscal_years"][i] == record["fiscal_years"][at]}


def vintage_deviations(record: dict) -> dict[str, list[float]]:
    """Deviation of each finished year's actual from *every* one of its vintages.

    The band settles a year against its final revision, which is the least
    demanding comparison in the record -- that vintage is published with about
    ten of twelve months already banked. This is the comparison that still has
    an answer: how far the *opening* guidance sat from the year that arrived.
    """
    slots = ("initial", "q1", "q2", "q3")
    years = sorted({fy for fy, actual in
                    zip(record["fiscal_years"], record["actual_adjusted_eps"])
                    if actual is not None} |
                   {record["fiscal_years"][index]
                    for index, value in enumerate(record["actual_adjusted_eps"])
                    if value is not None})
    settled = {}
    for index, value in enumerate(record["actual_adjusted_eps"]):
        if value is not None:
            settled[record["fiscal_years"][index]] = value
    out = {slot: [] for slot in slots}
    out["years"] = [f"FY{year}" for year in years]
    other_basis = rebased_vintages(record)
    for year in years:
        actual = settled[year]
        for slot in slots:
            value = None
            for index, (fy, sl) in enumerate(zip(record["fiscal_years"],
                                                 record["vintage_slots"])):
                if fy == year and sl == slot:
                    low = record["guide_adjusted_eps_lo"][index]
                    high = record["guide_adjusted_eps_hi"][index]
                    if low is not None and index not in other_basis:
                        value = (actual / ((low + high) / 2) - 1) * 100
                    break
            out[slot].append(value)
    return out


def opening_misses(staging: dict, dev: dict) -> str:
    """The years that settled below their opening midpoint, and what each one was.

    This used to print the first such year as "the only one below the opening
    guidance, the year the company withdrew its guidance" -- which, once the
    record reached back to FY2016, named FY2018 (0.3% under the midpoint and
    still inside the range) instead of FY2022.
    """
    record = staging["annual_guidance_history"]
    opening_low = {f"FY{year}": low for year, slot, low in
                   zip(record["fiscal_years"], record["vintage_slots"], record["guide_adjusted_eps_lo"])
                   if slot == "initial"}
    settled = {f"FY{year}": value for year, value in
               zip(record["fiscal_years"], record["actual_adjusted_eps"]) if value is not None}
    below = [(dev["years"][i], value) for i, value in enumerate(dev["initial"])
             if value is not None and value < 0]
    if not below:
        return ""
    parts = [f"{year} 差 {minus(value)}，"
             + ("跌破了开局区间" if settled[year] < opening_low[year] else "仍在开局区间之内")
             for year, value in below]
    words = (f"唯一低于开局指引中值的是 {below[0][0]}，{parts[0].removeprefix(below[0][0] + ' ')}。"
             if len(below) == 1 else
             f"低于开局指引中值的{cn_count(len(below))}年里，" + "；".join(parts) + "。")
    withdrawn = f"FY{record['suspension']['announced'][:4]}"
    if withdrawn in [year for year, _ in below] and settled[withdrawn] < opening_low[withdrawn]:
        split = staging["ratings_revenue_split_usd_m"]
        peak, trough, fall = deepest_fall(split["transaction"])
        words += (f"{withdrawn} 正是公司自己在年中<b>撤回</b>全年指引的那一年 —— "
                  "2022 年 6 月 1 日，理由写的是"
                  "「Extraordinarily Weak Market Conditions for its Ratings Business」，"
                  "八月初随第二季度业绩重新发布。那一年 Ratings 的交易性收入跌到 "
                  f"{year_quarter(split['quarters'][trough])} 的 US${split['transaction'][trough]:,.0f}M，"
                  f"比 {year_quarter(split['quarters'][peak])} 的高点低 {fall * 100:.0f}%，"
                  "见 Exhibit {EX_L_RATINGS}。")
    return words


def rebased_words(record: dict) -> str:
    """Says which vintages this chart leaves out, once the rebased year has settled."""
    skipped = sorted(rebased_vintages(record))
    at = record["basis_break_at"]
    if not skipped or record["actual_adjusted_eps"][max(i for i, y in enumerate(record["fiscal_years"])
                                                        if y == record["fiscal_years"][at])] is None:
        return ""
    return (f"FY{record['fiscal_years'][at]} 在 {record['filed'][at]} 换了口径，"
            f"此前的{cn_count(len(skipped))}档（{'、'.join(record['vintages'][i] for i in skipped)}）"
            "与该年实际值不同基，不参与这张图的比较。")


def convergence_chart(staging: dict) -> dict:
    """One bar per vintage slot per year: the funnel closing on the answer."""
    record = staging["annual_guidance_history"]
    dev = vintage_deviations(record)
    opening = [value for value in dev["initial"] if value is not None]
    final = [value for value in dev["q3"] if value is not None]
    beaten = sum(1 for value in opening if value > 0)
    open_abs = statistics.fmean(abs(value) for value in opening)
    final_abs = statistics.fmean(abs(value) for value in final)
    outside = [(label, filed) for label, filed, in_8k in
               zip(record["vintages"], record["filed"], record["filed_in_8k"]) if not in_8k]
    return {
        "ref": "EX_CONVERGE",
        "kind": "grouped_bars",
        "title": (
            f"实际结果相对每一档指引中值的偏离：开局那一档 {len(opening)} 年里 "
            f"{beaten} 年偏正，平均绝对偏离从 {open_abs:.1f}% 收敛到 {final_abs:.1f}%"
        ),
        "xlabels": dev["years"],
        "groups": [
            {"name": "vs 年初首次指引", "color": "NAVY", "values": rounded(dev["initial"])},
            {"name": "vs Q1 修订", "color": "BLUE", "values": rounded(dev["q1"])},
            {"name": "vs Q2 修订", "color": "GOLD", "values": rounded(dev["q2"])},
            {"name": "vs Q3 修订", "color": "GREEN", "values": rounded(dev["q3"])},
        ],
        "bar_labels": False,
        "fmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "% vs 该档指引中值",
        "note": (
            "<b>这张图问的是区间图问不了的那个问题：这一年在年初就知道了多少。</b>"
            "每一年有四根柱子，分别是最终实际值相对该年四档指引中值的偏离；"
            "四根柱子从左到右变矮，就是那一年的不确定性被逐季消掉的过程。"
            f"平均绝对偏离从开局的 {open_abs:.1f}% 收敛到末次的 {final_abs:.1f}%，"
            f"差不多是 {open_abs / final_abs:.1f} 倍。"
            "<b>方向也很整齐</b>：开局那一档"
            f"{len(opening)} 年里有 {beaten} 年最终结果高于它。"
            + opening_misses(staging, dev)
            + rebased_words(record)
            + (f"<b>{outside[0][0].split()[0]} 那一年的开局指引是唯一一档没有进入 8-K 的</b>："
               f"它出自 {outside[0][1]} 的投资者日，本页之所以能引用，"
               f"是因为公司在 {record['filed'][record['filed'].index(outside[0][1]) + 1]} 那份 8-K 里逐字复述了它；"
               "图上以 * 标出。" if len(outside) == 1 else "")
        ),
        "src_extra": SOURCE_8K + "偏离为自算值，四档指引原值见核对表。",
    }


def year_quarter(label: str) -> str:
    """``'Q3 2022'`` → ``'2022Q3'``, the way the prose names a quarter."""
    quarter, year = display_period(label).split()
    return f"{year}{quarter}"


def deepest_fall(values: list[float]) -> tuple[int, int, float]:
    """(peak index, trough index, fall) of the deepest peak-to-trough fall.

    The drawdown has to be measured from a peak that *precedes* its trough: the
    all-time high is the current quarter, and "fell from Q2'26 to Q3'22" would
    read backwards in time. Taking the all-time low and looking left for a peak
    worked only while the record began in 2017 -- extended back to 2016 the
    lowest quarter is the *first* one, and there is nothing to its left. The
    brief made the same mistake the other way round and printed that first
    quarter's US$225M as the 2022 trough.
    """
    peak_index = trough_index = running_peak = 0
    deepest = -1.0
    for index, value in enumerate(values):
        if value > values[running_peak]:
            running_peak = index
        fall = 1 - value / values[running_peak]
        if fall > deepest:
            deepest, peak_index, trough_index = fall, running_peak, index
    return peak_index, trough_index, deepest


# "Collapse" is a word the page uses for the transaction leg's 2020-2022 fall;
# the non-transaction leg is said never to have collapsed only while its own
# deepest fall stays under a fifth.
COLLAPSE = 0.2


def ratings_cycle(staging: dict) -> dict:
    """The facts the three notes about the Ratings cycle share."""
    split = staging["ratings_revenue_split_usd_m"]
    transaction, non_transaction = split["transaction"], split["non_transaction"]
    peak, trough, fall = deepest_fall(transaction)
    last = len(transaction) - 1
    return {
        "quarters": split["quarters"],
        "peak": peak, "trough": trough, "fall": fall,
        "at_high": transaction[-1] == max(transaction),
        "years_since_trough": (last - trough) / 4,
        "held_up": deepest_fall(non_transaction)[2] < COLLAPSE,
    }


def years_words(years: float) -> str:
    """``3.75`` → ``'三年多'``, ``4.0`` → ``'四年'``."""
    whole = int(years)
    return f"{cn_count(whole)}年" + ("多" if years > whole else "")


def q1_low_years(quarters: list[str], values: list[float]) -> tuple[list[int], list[int]]:
    """The complete calendar years, and those whose first quarter is the lowest of four."""
    years = sorted({int(label.split()[1]) for label in quarters})
    full = [year for year in years if all(f"Q{n} {year}" in quarters for n in (1, 2, 3, 4))]
    low = [year for year in full
           if values[quarters.index(f"Q1 {year}")]
           == min(values[quarters.index(f"Q{n} {year}")] for n in (1, 2, 3, 4))]
    return full, low


def issuance_downturn(total: list[float]) -> bool:
    """Whether the billed-issuance record holds anything a reader would call a downturn:
    a year-on-year fall deeper than a tenth, or two falling quarters in a row."""
    yoy = [pct_change(total[i], total[i - 4]) for i in range(4, len(total))]
    return (any(value < -10 for value in yoy)
            or any(a < 0 and b < 0 for a, b in zip(yoy, yoy[1:])))


# ── what the two reports left: settled in section one, set in section three ──
# The first S&P Global analysis on this site covers Q1 2026; its section 0 says in
# as many words that there was no earlier report. From the quarter after it, every
# page has a report before it whose follow-up list and section-8 thresholds come
# due, and a page that quietly dropped them would be the stale-prose failure in a
# new place -- so the build stops until the blocks are stamped for the quarter.
FIRST_REPORT_PERIOD = "Q1 2026"


def subscription_share(types: dict) -> list[float]:
    gross = gross_revenue_by_type(types)
    return [types["subscription"][i] / gross[i] * 100 for i in range(len(gross))]


def threshold_words(entry: dict) -> str:
    """A threshold the way its chart title prints it: 「+3%」「−5%」「+4.5%」「US$1,500M」."""
    if entry["unit"] == "usd_m":
        return f"US${entry['threshold']:,.0f}M"
    return f"{entry['threshold']:+g}%".replace("-", "−")


def reading_words(entry: dict, value: float) -> str:
    """A current reading in its threshold's unit: 「+16.6%」「−7.8%」「US$1,500M」."""
    if entry["unit"] == "usd_m":
        return f"US${value:,.0f}M"
    return minus(value)


def grouped_by_reading(entries: list[dict]) -> list[tuple[str, list[dict]]]:
    """Entries grouped by the reading they settle on, in first-appearance order."""
    groups: dict[str, list[dict]] = {}
    for entry in entries:
        groups.setdefault(entry["reads"], []).append(entry)
    return list(groups.items())


def track_title(name: str, entries: list[dict], key: str, mode: str) -> str:
    """「…：守住 / 击穿上季阈值 X」 for section one, 「…：下季阈值 A，当前 B」 for three."""
    now = entries[0][key]
    if mode == "prior":
        parts = []
        for entry in entries:
            mark = headroom(entry["direction"], entry["threshold"], entry[key])
            if round(mark, 1) == 0:
                parts.append(f"恰好踩在上季阈值 {threshold_words(entry)} 上")
            else:
                parts.append(f"{'守住' if mark > 0 else '击穿'}上季阈值 {threshold_words(entry)}")
        return f"{name} {reading_words(entries[0], now)}：" + "，".join(parts)
    return (f"{name}：下季阈值 {' / '.join(threshold_words(entry) for entry in entries)}，"
            f"当前 {reading_words(entries[0], now)}")


def threshold_series(entries: list[dict], length: int, lead: str) -> list[dict]:
    colors = ("RED", "GOLD", "GREEN")
    return [{"name": f"{lead}阈值 {threshold_words(entry)}", "values": [entry["threshold"]] * length,
             "color": colors[i % len(colors)]} for i, entry in enumerate(entries)]


def below_words(values: list[float | None], labels: list[str], entry: dict) -> str:
    """「38 个有读数的季度里 8 个低于 −5%（…）」 -- the line's own history, counted."""
    seen = [(label, value) for label, value in zip(labels, values) if value is not None]
    below = [label for label, value in seen if value < entry["threshold"]]
    if not below:
        return f"{len(seen)} 个有读数的季度里没有一个低于 {threshold_words(entry)}"
    return (f"{len(seen)} 个有读数的季度里 {len(below)} 个低于 {threshold_words(entry)}"
            f"（{'、'.join(year_quarter(label) for label in below)}）")


def ytd_buyback_chart(staging: dict, entries: list[dict], key: str, mode: str) -> dict:
    """Year-to-date buybacks for every year the record holds, against the lines set on them."""
    capital = staging["capital_allocation_usd_m"]
    quarters = capital["quarters"]
    period = staging["periods"][-1]
    quarter = period_order(period)[1]
    years = sorted({period_order(label)[0] for label in quarters})
    values = [ytd_sum(quarters, capital["buyback"], f"Q{quarter} {year}") for year in years]
    words = ytd_words(period)
    known = [(year, value) for year, value in zip(years, values) if value is not None]
    peak_year, peak = max(known, key=lambda row: row[1])
    zero = [year for year, value in known if value == 0]
    top = max(entry["threshold"] for entry in entries)
    cap = top * 2 if peak > top * 3 else None
    chart = {
        "ref": "EX_TRACK_BUYBACK",
        "kind": "lines",
        "title": track_title(f"{words}累计回购", entries, key, mode),
        "xlabels": [str(year) for year in years],
        "series": [{"name": f"{words}累计回购", "values": rounded(values), "color": "NAVY"}]
                  + threshold_series(entries, len(years), "上季" if mode == "prior" else "下季"),
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c", "end_label": True, "ylab": "US$M",
        "note": (
            f"每一年{words}的回购合计，{len(known)} 年都画出来，看本季这一格在自己的历史里算多还是少。"
            f"最多的一年是 {peak_year} 年（US${peak:,.0f}M）"
            + (f"，图上截在 US${cap:,.0f}M 画、真值标在点旁" if cap else "")
            + "，来历见 Exhibit {EX_L_CAPITAL}。"
            + (f"{'、'.join(str(year) for year in zero)} 年{words}没有回购。" if zero else "")
            + (f"上季阈值是对 {period_order(period)[0]} 年{words}合计设的，本季到期结算。" if mode == "prior" else "")
        ),
        "src_extra": "各季 10-Q / 10-K 合并现金流量表「Repurchase of treasury shares」；季度值为相邻两次年初至今申报值之差。",
    }
    if cap:
        chart["ycap"] = cap
    return chart


def ratings_yoy_chart(staging: dict, entries: list[dict], key: str, mode: str) -> dict:
    """Ratings revenue growth over the whole record, against the report's two lines."""
    quarters = staging["ratings_revenue_split_usd_m"]["quarters"]
    total = ratings_total(staging)
    yoy = [None] * 4 + [pct_change(total[i], total[i - 4]) for i in range(4, len(total))]
    period = staging["periods"][-1]
    following = shift_quarter(period, 1)
    base_label = shift_quarter(following, -4)
    counts = "；".join(below_words(yoy, quarters, entry) for entry in entries)
    base = total[quarters.index(base_label)] if base_label in quarters else None
    return {
        "ref": "EX_TRACK_RATINGS",
        "kind": "lines",
        "title": track_title("Ratings 收入同比", entries, key, mode),
        "xlabels": [compact_period(label) for label in quarters],
        "xstep": LONG_STEP,
        "series": [{"name": "Ratings 收入同比", "values": rounded(yoy), "color": "NAVY"}]
                  + threshold_series(entries, len(quarters), "上季" if mode == "prior" else "下季"),
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True, "ylab": "同比增速",
        "note": (
            "Ratings 收入是交易性与非交易性两条申报腿之和（Exhibit {EX_L_RATINGS}）。"
            + counts + "。"
            + (f"下一季的比较基数是 {year_quarter(base_label)} 的 US${base:,.0f}M，"
               f"比本季的比较基数（{year_quarter(quarters[-5])} 的 US${total[-5]:,.0f}M）"
               f"{'高' if base > total[-5] else '低'} {abs(pct_change(base, total[-5])):.1f}% —— "
               "本季的同比与下季阈值之间隔着这一层基数。"
               if mode == "next" and base is not None else "")
        ),
        "src_extra": "各季 10-Q / 10-K 收入附注与业绩 8-K EX-99.1 的 Revenue by Type 表。",
    }


def mi_yoy_chart(staging: dict, entries: list[dict], key: str, mode: str) -> dict:
    """Market Intelligence revenue growth, on the segment's filed (10-Q) basis."""
    segments = staging["segments_usd_m"]
    quarters = segments["quarters"]
    mi = segments["revenue"]["market_intelligence"]
    yoy = [None] * 4 + [pct_change(mi[i], mi[i - 4]) if mi[i] and mi[i - 4] else None
                        for i in range(4, len(mi))]
    top = max(entry["threshold"] for entry in entries)
    cap = top * 4
    over = [(label, value) for label, value in zip(quarters, yoy) if value is not None and value > cap]
    merger = staging["long_history"]["quarters"][staging["long_history"]["structural_break_at"][-1]]
    merger_window = {shift_quarter(merger, step) for step in range(5)}
    figures = stamped_block(staging, "quarter_figures", staging["periods"][-1]) or {}
    recast = figures.get("mi_recast_revenue_usd_m")
    chart = {
        "ref": "EX_TRACK_MI",
        "kind": "lines",
        "title": track_title("Market Intelligence 收入同比", entries, key, mode),
        "xlabels": [compact_period(label) for label in quarters],
        "xstep": LONG_STEP,
        "series": [{"name": "Market Intelligence 收入同比", "values": rounded(yoy), "color": "NAVY"}]
                  + threshold_series(entries, len(quarters), "上季" if mode == "prior" else "下季"),
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True, "ylab": "同比增速",
        "note": (
            "分部收入取 10-Q 分部附注的申报列（含分部间收入）。"
            + "；".join(below_words(yoy, quarters, entry) for entry in entries) + "。"
            + (f"{year_quarter(over[0][0])}–{year_quarter(over[-1][0])} 的同比被抬到 "
               f"{min(v for _, v in over):.0f}%–{max(v for _, v in over):.0f}%，图上截在 {cap:g}% 画"
               + ("：那是 IHS Markit 并表（2022-02-28 交割）带来的跳升，不是增长" if all(
                   label in merger_window for label, _ in over) else "")
               + "。" if over else "")
            + (f"新闻稿 Exhibit 6 的重述口径（451 Research 与 Maritime & Trade 从 MI 划入 Energy）"
               f"本季同比为 {reading_words(entries[0], pct_change(*recast))}。" if recast else "")
        ),
        "src_extra": "各季 10-Q / 10-K 分部附注；第四季度为全年减九个月。",
    }
    if over:
        chart["ycap"] = cap
    return chart


TRACK_CHARTS = {
    "ytd_buyback": ytd_buyback_chart,
    "ratings_yoy": ratings_yoy_chart,
    "mi_yoy": mi_yoy_chart,
}

# Readings with no chart of their own, and why -- stated under the overview bar
# rather than left for the reader to wonder about.
UNCHARTED = {
    "energy_organic_cc": ("Energy 有机恒定汇率增速只有本季与去年同季两个重述口径读数（新闻稿 Exhibit 8），"
                          "申报的 Energy 分部长序列是另一个口径（重述前、含汇率与并购），没有同口径的走势可画"),
    "ytd_adjusted_fcf_growth": ("调整后自由现金流的当前值是公司年初至今的读数，阈值结算的是全年；"
                                "逐年的全年实际值画在 Exhibit {EX_FCF_BAND}"),
}


def track_charts(staging: dict, entries: list[dict], key: str, mode: str) -> list[dict]:
    return [TRACK_CHARTS[reads](staging, group, key, mode)
            for reads, group in grouped_by_reading(entries) if reads in TRACK_CHARTS]


def closure_counts(closure: dict) -> list[int]:
    labels = closure["labels"]
    unknown = sorted({item["verdict"] for item in closure["items"]} - set(labels))
    if unknown:
        raise ValueError(f"followup_closure verdicts {unknown} are not among its labels {labels}")
    return [sum(1 for item in closure["items"] if item["verdict"] == label) for label in labels]


def closure_chart(closure: dict) -> dict:
    """(a) Last report's follow-up questions, as this quarter's report judged them."""
    labels, items = closure["labels"], closure["items"]
    counts = closure_counts(closure)
    lead = closure.get("lead")
    lead_words = ""
    if lead:
        got = counts[labels.index(lead["label"])]
        lead_words = (f"第 0 节导语「{lead['words']}」与逐条判定一致。" if got == lead["count"] else
                      f"第 0 节导语写的是「{lead['words']}」，逐条判定里是{cn_count(got)}条，本页按逐条判定计。")
    groups = "；".join(
        f"{label}{cn_count(count)}条：" + "、".join(item["short"] for item in items if item["verdict"] == label)
        for label, count in zip(labels, counts) if count)
    return {
        "ref": "EX_CLOSURE",
        "kind": "bars_labeled",
        "title": (f"上季 {len(items)} 条待验证问题："
                  + "、".join(f"{count} 条{label}" for label, count in zip(labels, counts))),
        "xlabels": labels,
        "values": counts,
        "legend": "问题条数",
        "fmt": "f0", "yfmt": "f0", "label_fmt": "f0", "ylab": "条",
        "note": closure["rule"] + groups + "。" + lead_words + "逐条的问题、原文判定与可核的读数见核对表。",
        "src_extra": (f"问题清单来自上季（{display_period(closure['set_in'])}）本地季报分析稿的 Follow-up；"
                      "判定取自本季分析稿第 0 节；只在电话会上出现的数按公司口径转述，不当作申报数。"),
    }


def row_words(row: dict, values: dict[str, str]) -> str:
    return f"第{cn_ordinal(row['row'])}条「{row['metric']}」{row['status']}：{fill_story(row['note'], values)}"


def prior_overview(prior: dict, entries: list[dict], values: dict[str, str]) -> dict:
    """(b) The rows of last report's section 8, the due ones on one headroom axis."""
    rows = prior["rows"]
    marks = [headroom(entry["direction"], entry["threshold"], entry["actual"]) for entry in entries]
    held = sum(1 for mark in marks if mark >= 0)
    flat = [entry for entry, mark in zip(entries, marks) if round(mark, 1) == 0]
    verdict = (f"{held} 道全部守住" if held == len(entries) else
               f"{held} 道守住、{len(entries) - held} 道击穿")
    bar = headroom_exhibit(
        f"上季 {len(rows)} 条观察指标，本季到期 {len(entries)} 道量化阈值：{verdict}",
        entries, "actual",
        note=("正值＝守住上季报告第 8 节的阈值，负值＝击穿。"
              + "".join(f"「{entry['metric']}」的余量恰好为 0，所以这一格没有柱子，不是缺数。" for entry in flat)
              + "".join(row_words(row, values) for row in rows)),
        src_extra=(f"阈值数值与方向逐字取自上季（{display_period(prior['set_in'])}）本地季报分析稿第 8 节，"
                   "是研究设定，不是公司指引，触发动作不发布；实际值为本季申报值与自算值。"),
    )
    bar["ref"] = "EX_PRIOR_BAR"
    if flat:
        bar["annot"] = "；".join(f"{entry['metric']}余量 0" for entry in flat)
    return bar


def next_overview(next_kpi: dict, entries: list[dict], following: str) -> dict:
    """Section three: this report's section-8 lines, measured from where the quarter left off."""
    rows = next_kpi["rows"]
    marks = [headroom(entry["direction"], entry["threshold"], entry["current"]) for entry in entries]
    safe = sum(1 for mark in marks if mark >= 0)
    quantified_rows = sorted({entry["row"] for entry in entries})
    high = [(entry, mark) for entry, mark in zip(entries, marks) if mark > 150]
    low = [(entry, mark) for entry, mark in zip(entries, marks) if mark < -150]
    where = []
    for reads, group in grouped_by_reading(entries):
        if reads in UNCHARTED:
            where.append(UNCHARTED[reads])
    partial = [row for row in rows if row["row"] in quantified_rows and row.get("why")]
    bar = headroom_exhibit(
        (f"下季 {len(entries)} 道量化阈值（第 8 节 {len(rows)} 条里的 {len(quantified_rows)} 条）："
         f"当前 {safe} 道在安全侧、{len(entries) - safe} 道已在线外"),
        entries, "current",
        note=("正值＝当前读数在阈值的安全侧，负值＝已在线外。"
              f"当前值是本季的读数，这些阈值结算的是 {display_period(following)} 的读数"
              + ("（全年调整后自由现金流那一条结算的是全年）"
                 if any(entry["reads"] == "ytd_adjusted_fcf_growth" for entry in entries) else "")
              + "。"
              + (f"{'、'.join(entry['metric'] for entry, _ in high)}的余量"
                 f"（{'、'.join(f'{mark:+.0f}%' for _, mark in high)}）远超其余几道，截在 +100% 画、真值标在柱旁。"
                 if high else "")
              + (f"{'、'.join(entry['metric'] for entry, _ in low)}的余量截在 −100% 画。" if low else "")
              + "".join(f"{text}。" for text in where)
              + "".join(f"「{row['metric']}」只接一半：{row['why']}。" for row in partial)
              + ("另外几条不接入的原因见本节说明与核对表。"
                 if len(quantified_rows) < len(rows) else "")),
        src_extra=("阈值数值与方向逐字取自本季本地季报分析稿第 8 节，是研究设定，不是公司指引，触发动作不发布；"
                   "当前值为本季申报值与自算值。"),
    )
    bar["ref"] = "EX_NEXT_BAR"
    if high:
        bar["ycap"] = 100
    if low:
        bar["yfloor"] = -100
    return bar


def settled_lead(staging: dict, values: dict[str, str]) -> tuple[list[dict], list[dict], str]:
    """Section one's opening: what last quarter's report left, settled -- or why nothing is."""
    period = staging["periods"][-1]
    closure = stamped_block(staging, "followup_closure", period)
    prior = stamped_block(staging, "prior_kpi_settlement", period)
    if period_order(period) <= period_order(FIRST_REPORT_PERIOD):
        if closure or prior:
            raise ValueError(f"no S&P Global report precedes {FIRST_REPORT_PERIOD}: there is nothing "
                             "for `followup_closure` / `prior_kpi_settlement` to settle")
        return [], [], (f"本站对 S&P Global 的第一份季报分析是 {display_period(FIRST_REPORT_PERIOD)}，"
                        "没有上季留下的跟踪指标可结算（那份分析的第 0 节也写明没有上季问题可回看）；"
                        "本节结算的是公司自己给出的指引 —— ")
    if closure is None or prior is None:
        raise ValueError(f"the report before {period} left follow-up questions and section-8 thresholds: "
                         f"stamp `followup_closure` and `prior_kpi_settlement` for {period}")
    entries = with_current(staging, prior, "actual")
    charts = [closure_chart(closure)]
    if entries:
        charts.append(prior_overview(prior, entries, values))
        charts += track_charts(staging, entries, "actual", "prior")
    tables = [
        {"title": f"上季 {len(closure['items'])} 条待验证问题：本季分析稿第 0 节的逐条判定",
         "headers": ["#", "上季问题", "原文判定", "本页归类", "申报与公司口径的读数"],
         "rows": [[str(item["n"]), item["topic"], item["wording"], item["verdict"],
                   fill_story(item["reading"], values)] for item in closure["items"]]},
        {"title": f"上季分析稿第 8 节 {len(prior['rows'])} 条观察指标的本季结算",
         "headers": ["行", "指标", "阈值原文（触发动作不发布）", "本季状态", "说明"],
         "rows": [[str(row["row"]), row["metric"], row["condition"], row["status"],
                   fill_story(row["note"], values)] for row in prior["rows"]]},
    ]
    if entries:
        tables.append(threshold_table(0, "上季阈值与本季实际（原单位）", entries, "actual", "本季实际"))
    words = (f"先结清上一份报告留下的两样东西：本季分析稿第 0 节核验的上季 {len(closure['items'])} 条待验证问题，"
             f"和上季分析稿第 8 节的 {len(prior['rows'])} 条观察指标（本季到期的 {len(entries)} 道量化阈值画成余量图，"
             "其余逐条写明何时结算、为何不结算）；然后是公司自己的指引 —— ")
    return charts, tables, words


def next_section(staging: dict, following: str) -> tuple[list[dict], list[dict], str]:
    """Section three from this report's section 8, or a stop if the block is missing."""
    period = staging["periods"][-1]
    next_kpi = stamped_block(staging, "next_kpi", period)
    if next_kpi is None:
        raise ValueError(f"every S&P Global report has a section 8: stamp `next_kpi` for {period}")
    if next_kpi["for_period"] != following:
        raise ValueError(f"series block `next_kpi` is stamped for {next_kpi['for_period']!r}, "
                         f"but the quarter after {period} is {following!r}")
    entries = with_current(staging, next_kpi, "current")
    quantified_rows = {entry["row"] for entry in entries}
    left_out = [row for row in next_kpi["rows"] if row["row"] not in quantified_rows]
    charts = []
    if entries:
        charts.append(next_overview(next_kpi, entries, following))
        charts += track_charts(staging, entries, "current", "next")

    def current_words(row: dict) -> str:
        found = [entry for entry in entries if entry["row"] == row["row"]]
        if not found:
            return row.get("why", "")
        return reading_words(found[0], found[0]["current"]) + (f"；{row['why']}" if row.get("why") else "")

    tables = [
        {"title": f"本季分析稿第 8 节 {len(next_kpi['rows'])} 条观察指标：本页接入与不接入",
         "headers": ["行", "指标", "阈值原文（触发动作不发布）", "本页处理", "当前读数 / 不接入的原因"],
         "rows": [[str(row["row"]), row["metric"], row["condition"], row["status"], current_words(row)]
                  for row in next_kpi["rows"]]},
    ]
    if entries:
        tables.append(threshold_table(0, "下季阈值与当前值（原单位）", entries, "current", "当前值"))
    words = (f"本季分析稿第 8 节 {len(next_kpi['rows'])} 条观察指标。可量化的 {len(quantified_rows)} 条"
             "先看当前读数离阈值还有多远（统一用「距阈值余量」口径），有走势可画的再逐条画出来"
             + (f"；另外 {len(left_out)} 条不接入 —— "
                + "；".join(f"{row['metric']}：{row['why']}" for row in left_out) if left_out else "")
             + "。")
    return charts, tables, words


# ── section two: what moved this quarter ─────────────────────────────────────
SEGMENTS = [("ratings", "Ratings"), ("indices", "Indices"), ("energy", "Energy"),
            ("market_intelligence", "Market Intelligence"), ("mobility", "Mobility")]


def segment_identity(staging: dict) -> dict:
    """Segment revenue, corporate revenue and the elimination against consolidated revenue.

    The note used to say "five segments plus the elimination equal consolidated
    revenue in all 34 quarters". Five do not: Engineering Solutions (2022Q1 to
    2023Q2, up to US$100M a quarter) and a corporate revenue line in 2018 are
    needed as well, and only with both does the largest residual come to US$1M.
    """
    segments = staging["segments_usd_m"]
    long_history = staging["long_history"]
    consolidated = dict(zip(long_history["quarters"], long_history["revenue_usd_m"]))
    residuals = []
    for i, label in enumerate(segments["quarters"]):
        total = (sum(values[i] or 0 for values in segments["revenue"].values())
                 + (segments["corporate_revenue"][i] or 0)
                 + segments["intersegment_elimination"][i])
        residuals.append((abs(total - consolidated[label]), label))
    worst = max(residual for residual, _ in residuals)
    extra = [key for key, _ in SEGMENTS]
    others = sorted({key for key, values in segments["revenue"].items()
                     if key not in extra and any(values)})
    return {
        "checked": len(residuals),
        "worst": worst,
        "worst_derived": all(label in segments["derived_quarters"]
                             for residual, label in residuals if residual == worst),
        "others": others,
        "corporate": [label for label, value in zip(segments["quarters"], segments["corporate_revenue"])
                      if value],
    }


def identity_words(check: dict, segments: dict) -> str:
    """「各分部收入（含 … ）加上分部间抵销等于申报的合并收入，本页 34 个季度逐季核对过，最大残差 US$1M（…）」"""
    names = {"engineering_solutions": "Engineering Solutions"}
    inside = []
    for key in check["others"]:
        present = [label for label, value in zip(segments["quarters"], segments["revenue"][key]) if value]
        inside.append(f"只在 {year_quarter(present[0])} 至 {year_quarter(present[-1])} 出现的 "
                      f"{names.get(key, key)}")
    if check["corporate"]:
        years = sorted({label.split()[1] for label in check["corporate"]})
        inside.append(f"{'、'.join(years)} 年{cn_count(len(check['corporate']))}季的公司层收入")
    joined = inside[0] if inside else ""
    for part in inside[1:]:
        joined += ("，以及 " if part[0].isdigit() else "，以及") + part
    return (("各分部收入（含" + joined + "）" if inside else "各分部收入")
            + f"加上分部间抵销等于申报的合并收入，本页 {check['checked']} 个季度逐季核对过，"
            + (f"最大残差 US${check['worst']:,.0f}M"
               + ("（出现在按「全年减九个月」推出来的第四季度上）" if check["worst_derived"] else "")
               if check["worst"] else "逐季无差"))


def quarter_segments(staging: dict, story: dict | None, figures: dict | None = None) -> dict:
    segments = staging["segments_usd_m"]
    latest = len(segments["quarters"]) - 1
    present = [(key, label) for key, label in SEGMENTS
               if segments["revenue"][key][latest] is not None
               and segments["revenue"][key][latest - 4] is not None]
    revenue = [segments["revenue"][key][latest] for key, _ in present]
    prior = [segments["revenue"][key][latest - 4] for key, _ in present]
    growth = {label: pct_change(now, was)
              for (_, label), now, was in zip(present, revenue, prior)}
    ranked = sorted(growth, key=growth.get, reverse=True)
    intersegment = -segments["intersegment_elimination"][latest]
    # The same quarter on the release's recast basis, which moves 451 Research and
    # Maritime & Trade from Market Intelligence into Energy -- the basis the report
    # reads the segments on, and the one the filed series takes from 2026Q3.
    recast = ""
    if figures and figures.get("energy_recast_revenue_usd_m") and figures.get("mi_recast_revenue_usd_m"):
        energy = pct_change(*figures["energy_recast_revenue_usd_m"])
        mi = pct_change(*figures["mi_recast_revenue_usd_m"])
        recast_growth = {label: value for label, value in growth.items() if label != "Mobility"}
        recast_growth.update({"Energy": energy, "Market Intelligence": mi})
        recast_rank = sorted(recast_growth, key=recast_growth.get, reverse=True)
        same = recast_rank[:2] == ranked[:2] and recast_rank[-1] == ranked[-1]
        recast = ("按新闻稿 Exhibit 6 的重述口径（451 Research 与 Maritime & Trade 从 Market Intelligence "
                  f"划入 Energy，且不含 Mobility），Energy 本季同比 {minus(energy)}、Market Intelligence {minus(mi)}，"
                  "本季分析稿读的是这个口径；"
                  + ("标题里领先与落后的分部不变。" if same else "按这个口径，标题里领先与落后的分部会变。"))
    return {
        "ref": "EX_Q_SEG",
        "kind": "grouped_bars",
        "title": (
            f"本季{cn_count(len(present))}个分部的收入同比：{ranked[0]} {growth[ranked[0]]:+.0f}%、"
            f"{ranked[1]} {growth[ranked[1]]:+.0f}% 领先，"
            f"{ranked[-1]} {growth[ranked[-1]]:+.0f}% 落后"
        ),
        "xlabels": [label for _, label in present],
        "groups": [
            {"name": f"{segments['quarters'][latest - 4]} 收入", "color": "GOLD",
             "values": rounded(prior)},
            {"name": f"{segments['quarters'][latest]} 收入", "color": "NAVY",
             "values": rounded(revenue)},
        ],
        "bar_labels": True,
        "fmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$M",
        "note": (
            identity_words(segment_identity(staging), segments) + "。"
            + (story["segment_note"] if story and story.get("segment_note") else "")
            + recast
            + "分部口径用的是含分部间收入的申报列（8-K Exhibit 4 各期一致的那一列），"
            f"不是 2025 年起新增的「对外部客户」列，两者本季相差 US${intersegment:,.0f}M。"
        ),
        "src_extra": "各季 10-Q / 10-K 分部附注与业绩 8-K EX-99.1 Exhibit 4。",
    }


def quarter_ratings(staging: dict) -> dict:
    split = staging["ratings_revenue_split_usd_m"]
    cycle = ratings_cycle(staging)
    window = 21
    labels = [compact_period(q) for q in split["quarters"][-window:]]
    transaction = split["transaction"][-window:]
    non_transaction = split["non_transaction"][-window:]
    trough = cycle["trough"]
    high = split["transaction"].index(max(split["transaction"]))
    return {
        "ref": "EX_Q_RATINGS",
        "kind": "lines",
        "title": (
            f"Ratings 的两条腿：交易性 US${transaction[-1]:,.0f}M（同比 "
            f"{signed(pct_change(split['transaction'][-1], split['transaction'][-5]), 0)}），"
            f"非交易性 US${non_transaction[-1]:,.0f}M（"
            f"{signed(pct_change(split['non_transaction'][-1], split['non_transaction'][-5]), 0)}）"
        ),
        "xlabels": labels,
        "xrot": 90,
        "series": [
            {"name": "交易性（按每笔发行评级收费）", "values": rounded(transaction),
             "color": "NAVY"},
            {"name": "非交易性（存续监控、年费、实体评级）",
             "values": rounded(non_transaction), "color": "GOLD"},
        ],
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "end_label": True,
        "ylab": "US$M",
        "note": (
            "<b>这是理解这家公司周期性的那张图。</b>"
            "两条线加起来恒等于申报的 Ratings 分部收入，都是收入附注里的申报值。"
            "深蓝那条按公开发债与银团贷款的每一笔评级收费，随发行窗口开合摆动；"
            "金色那条是存续期监控与年费，是一条年金。"
            + (f"本季交易性 US${transaction[-1]:,.0f}M 是本记录内的最高值，" if cycle["at_high"] else
               f"本季交易性 US${transaction[-1]:,.0f}M，本记录内的最高值是 "
               f"{year_quarter(split['quarters'][high])} 的 US${split['transaction'][high]:,.0f}M，")
            + f"而它在 {year_quarter(split['quarters'][trough])} 曾经只有 "
            f"US${split['transaction'][trough]:,.0f}M。整段周期见 Exhibit {{EX_L_RATINGS}}。"
        ),
        "src_extra": "各季 10-Q / 10-K 收入附注与业绩 8-K EX-99.1 Revenue by Type 表。",
    }


def quarter_margin_bases(staging: dict, figures: dict | None, story: dict | None) -> dict:
    """The quarter's operating margin on every basis the filings print it.

    The reported and the ex-credits bars come from the statements. The company's
    pro forma and adjusted bars exist only in a quarter whose release prints
    them, and that quarter's figures sit in the stamped `quarter_figures` block.
    """
    long_history = staging["long_history"]
    index = len(long_history["quarters"]) - 1
    revenue = long_history["revenue_usd_m"][index]
    operating = long_history["operating_income_usd_m"][index]
    gain = long_history["gain_on_dispositions_usd_m"][index] or 0
    gaap = operating / revenue * 100
    ex_gain = operating_margin_ex_credits(long_history)[index]
    labels = ["申报 GAAP", "剔除处置损益与联营收益 D"]
    values = [gaap, ex_gain]
    title_parts = [f"申报 {gaap:.1f}%", f"剔除处置损益与联营收益 {ex_gain:.1f}%"]
    headline = ""
    denominator = revenue
    if figures and figures.get("pro_forma_revenue_usd_m"):
        basis = figures["basis"]
        denominator = figures["pro_forma_revenue_usd_m"]
        proforma = figures["pro_forma_operating_profit_usd_m"] / denominator * 100
        labels.append(f"pro forma（{basis}）")
        values.append(proforma)
        title_parts.append(f"公司口径 pro forma {proforma:.1f}%")
        if story and story.get("margin_note"):
            headline = fill_story(story["margin_note"], {
                "nth": cn_ordinal(len(values)),
                "pro_forma_revenue": f"{denominator:,.0f}",
                "revenue": f"{revenue:,.0f}",
                "gaap_margin": f"{gaap:.1f}",
            })
    if figures and figures.get("adjusted_operating_profit_usd_m"):
        adjusted = figures["adjusted_operating_profit_usd_m"] / denominator * 100
        labels.append(f"adjusted（{figures['basis']}）" if figures.get("basis") else "adjusted")
        values.append(adjusted)
        title_parts.append(f"公司口径 adjusted {adjusted:.1f}%")
    close = abs(gaap - ex_gain) < 1
    long_history_gap = [(o - (r - e)) / r * 100 for o, r, e, label in
                        zip(long_history["operating_income_usd_m"], long_history["revenue_usd_m"],
                            long_history["total_expenses_usd_m"], long_history["quarters"])
                        if label.endswith("2022")]
    report = periodic_report_words(staging)
    return {
        "ref": "EX_Q_MARGIN",
        "kind": "bars_labeled",
        "title": f"同一个季度的{cn_count(len(values))}个营业利润率口径：" + "、".join(title_parts),
        "xlabels": labels,
        "values": rounded(values),
        "legend": "本季营业利润率",
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "营业利润率",
        "note": (
            headline
            + "第二根是本页自算的口径：申报收入减去申报的总费用，"
            + (f"本季处置收益只有 US${gain:,.0f}M，所以第一、二根几乎一样高；" if close else
               f"本季处置收益 US${gain:,.0f}M，第一根比第二根高 {gaap - ex_gain:.1f} 个百分点；")
            + ("在 2022 年那几季它们相差几十个百分点。" if max(long_history_gap) >= 20 else "")
            + f"{cn_count(len(values))}根都是可复算的，差别全在分子分母各取哪一列，"
            f"本页把{cn_count(len(values))}列都画出来而不是挑一列。"
        ),
        "src_extra": (
            (f"申报口径取自{report.removeprefix('与')} 合并损益表；" if report
             else "申报口径取自本季业绩 8-K EX-99.1 的合并损益表；")
            + (figures.get("src_extra", "") if figures else "")
        ),
    }


def quarter_mobility(staging: dict) -> dict | None:
    """The guidance rebase, drawn as the two bases it spans -- in the quarter it happened.

    Drawn only when the rebased vintage was published with this quarter's
    release: a quarter later it is part of the record, and the band in section
    one keeps showing it.
    """
    record = staging["annual_guidance_history"]
    at = record["basis_break_at"]
    if at is None or record["filed"][at] != staging["latest"]["release_date"]:
        return None
    before = at - 1
    prior_mid = (record["guide_adjusted_eps_lo"][before] + record["guide_adjusted_eps_hi"][before]) / 2
    new_mid = (record["guide_adjusted_eps_lo"][at] + record["guide_adjusted_eps_hi"][at]) / 2
    year = record["fiscal_years"][at]
    actuals = staging["annual_actuals"]
    base = actuals["adjusted_eps"][actuals["fiscal_years"].index(year - 1)]
    proforma_base = record["proforma_base_adjusted_eps_usd"]
    addback = base - proforma_base
    old_growth = pct_change(prior_mid, base)
    new_growth = pct_change(new_mid, proforma_base)
    old_slot = record["vintage_slots"][before].upper()
    new_slot = record["vintage_slots"][at].upper()
    return {
        "ref": "EX_Q_MOBILITY",
        "kind": "grouped_bars",
        "title": (
            f"FY{year} 指引中值掉了 US${prior_mid - new_mid:.2f}（{signed(pct_change(new_mid, prior_mid))}），"
            f"但同口径的增速从 {old_growth:+.1f}% 变成 {new_growth:+.1f}%"
        ),
        "xlabels": [f"FY{year - 1} 基数", f"FY{year} 指引中值"],
        "groups": [
            {"name": f"含 Mobility（{old_slot} 及以前的口径）", "color": "GOLD",
             "values": rounded([base, prior_mid])},
            {"name": f"不含 Mobility（{new_slot} 起的口径）", "color": "NAVY",
             "values": rounded([proforma_base, new_mid])},
        ],
        "bar_labels": True,
        "fmt": "usd2",
        "label_fmt": "usd2",
        "ylab": "调整后摊薄 EPS（US$）",
        "note": (
            "<b>指引数字掉了，被指引的公司也变小了，两件事要一起看。</b>"
            f"左边一组是基数：FY{year - 1} 实际调整后 EPS 为 US${base:.2f}，"
            f"公司在 {record['proforma_base_filed']} 单独发布的新闻稿里给出重述后的 FY{year - 1} pro forma 基数 "
            f"US${proforma_base:.2f}，两者相差 US${addback:.2f}，就是 Mobility 那一块。"
            "右边一组是指引中值。"
            f"拿金色比金色是 {old_growth:+.1f}%，拿深蓝比深蓝是 {new_growth:+.1f}% —— "
            + ("<b>按同口径看，这次修订是上调而不是下调。</b>" if new_growth > old_growth else
               "<b>按同口径看，这次修订也是下调。</b>")
            + f"拿右边一组里深蓝的新指引直接比金色的旧指引，得到的那个「{minus(pct_change(new_mid, prior_mid))}」"
            "跨了两个口径，不对应任何真实的经营变化。"
            "公司自己在新闻稿里写的是「not directly comparable to prior guidance」。"
            f"本页不发布任何自算的桥：公司没有披露 FY{year} 口径差的逐项拆分，"
            f"US${addback:.2f} 是它对 <b>FY{year - 1}</b> 给出的加回额，不是对 FY{year} 的。"
        ),
        "src_extra": (
            f"指引区间取自 {record['filed'][before]} 与 {record['filed'][at]} 两份业绩 8-K 的 EX-99.1；"
            f"FY{year - 1} pro forma 基数取自 {record['proforma_base_filed']} 的 {record['proforma_base_form']}。"
        ),
    }


def quarter_issuance(staging: dict) -> dict:
    issuance = staging["billed_issuance_usd_bn"]
    labels = [compact_period(q) for q in issuance["quarters"]]
    total = issuance["total"]
    yoy = [None] * 4 + [pct_change(total[i], total[i - 4])
                        for i in range(4, len(total))]
    derived = issuance["derived_quarters"]
    if all(label.startswith("Q4") for label in derived):
        derived_words = (f"{cn_count(len(derived))}个第四季度（"
                         f"{'、'.join(label.split()[1] for label in derived)}）")
    else:
        derived_words = "、".join(year_quarter(label) for label in derived)
    first_year = issuance["quarters"][0].split()[1]
    return {
        "ref": "EX_Q_ISSUANCE",
        "kind": "gs_bar",
        "title": (
            f"计费发行量 US${total[-1]:,.0f}B，同比 "
            f"{signed(pct_change(total[-1], total[-5]), 0)}；本记录从 {first_year} 年才开始"
        ),
        "xlabels": labels,
        "xrot": 90,
        "values": rounded(total),
        "legend": "计费发行量",
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$B",
        "ylab2": "同比增速",
        "yoy": {"name": "同比增速 (RHS)", "values": rounded(yoy),
                "color": "GREEN", "yfmt": "pct1"},
        "note": (
            "<b>这张图的窗口本身就是它最大的局限，所以写在图上而不是脚注里。</b>"
            "「计费发行量」这个指标 2024 年第一季度才第一次进入申报文件，"
            f"本页能往回补到 {quarter_words(issuance['quarters'][0])}，靠的是 2024 年各季 10-Q 里的上年同期栏。"
            "<b>也就是说，这条线从 2022 年那次发行冰点之后才开始</b> —— "
            + ("它整段都在复苏区间里，看不到一次下行周期，" if not issuance_downturn(total) else "")
            + "拿它来论证「Ratings 有周期性」是不成立的，"
            f"能论证的是 Exhibit {{EX_L_RATINGS}} 那条 "
            f"{len(staging['ratings_revenue_split_usd_m']['quarters'])} 季的收入线。"
            + (f"{derived_words}是「全年减九个月」推出来的，"
               f"其余{cn_count(len(total) - len(derived))}季是申报的单季值。" if derived else "")
            + "公司只按评级类别（投资级 / 高收益 / 其他）拆分，从不按地区给金额。"
        ),
        "src_extra": "各季 10-Q / 10-K 的 MD&A「Billed Issuance Volumes」表。",
    }


REST_WORDS = {1: "后三个季度", 2: "下半年", 3: "第四季度"}


def usd_words(value: float) -> str:
    """``-119`` → ``'−US$119M'``, ``137`` → ``'+US$137M'``: a signed cash-flow line."""
    return f"{'−' if value < 0 else '+'}US${abs(value):,.0f}M"


def rest_of_year(staging: dict) -> dict | None:
    """Full-year guidance less the year to date: what the rest of the year is left to do.

    The report's central section is this subtraction. Every input is a figure
    the company printed -- the full-year outlook (this quarter's release), the
    year to date (the same release's Exhibits 5 and 6) and the base year the
    outlook is projected against (the July 6 8-K/A) -- so the page can do it
    and say so. Nothing is left to do once a fourth quarter closes the year.
    """
    period = staging["periods"][-1]
    year, quarter = period_order(period)
    ytd = stamped_block(staging, "ytd_vs_guidance", period)
    if ytd is None or quarter == 4:
        return None
    record = staging["annual_guidance_history"]
    if record["fiscal_years"][-1] != year:
        raise ValueError(f"the last guidance vintage guides FY{record['fiscal_years'][-1]}, "
                         f"not the year {period} belongs to")
    base = ytd["base_year"]
    rev_now, rev_then = ytd["revenue_usd_m"]
    rest_base_revenue = base["revenue_usd_m"] - rev_then
    growth = (record["guide_revenue_growth_lo_pct"][-1], record["guide_revenue_growth_hi_pct"][-1])
    full = [base["revenue_usd_m"] * (1 + g / 100) for g in (*growth, sum(growth) / 2)]
    revenue = [pct_change(value - rev_now, rest_base_revenue) for value in full]
    eps_now, eps_then = ytd["adjusted_diluted_eps_usd"]
    eps_guide = (record["guide_adjusted_eps_lo"][-1], record["guide_adjusted_eps_hi"][-1])
    rest_base_eps = base["adjusted_diluted_eps_usd"] - eps_then
    eps_rest = [value - eps_now for value in (*eps_guide, sum(eps_guide) / 2)]
    eps = [pct_change(value, rest_base_eps) for value in eps_rest]
    # The margin the company guides "excluding OSTTRA" takes the adjusted equity
    # income out of profit; the arithmetic runs at both guidance midpoints.
    expansion = ytd["guidance"]["adjusted_margin_expansion_ex_osttra_bp"]
    base_profit = base["adjusted_operating_profit_usd_m"] - base["adjusted_equity_income_usd_m"]
    full_margin = base_profit / base["revenue_usd_m"] * 100 + sum(expansion) / 200
    ytd_profit = [ytd["adjusted_operating_profit_usd_m"][i] - ytd["adjusted_equity_income_usd_m"][i]
                  for i in (0, 1)]
    rest_margin = (full_margin / 100 * full[2] - ytd_profit[0]) / (full[2] - rev_now) * 100
    rest_margin_then = (base_profit - ytd_profit[1]) / rest_base_revenue * 100
    return {
        "ytd": ytd_words(period), "rest": REST_WORDS[quarter], "base_year": base["fiscal_year"],
        "growth": growth, "eps_guide": eps_guide,
        "revenue_ytd": pct_change(rev_now, rev_then), "revenue_rest": revenue,
        "eps_ytd": pct_change(eps_now, eps_then), "eps_rest": eps, "eps_rest_usd": eps_rest,
        "eps_now": eps_now, "eps_then": eps_then, "eps_base": base["adjusted_diluted_eps_usd"],
        "rest_base_eps": rest_base_eps,
        "expansion": expansion,
        "margin_ytd": margin_change_bp(ytd, True) / 100,
        "margin_rest": rest_margin - rest_margin_then,
        "tax_ytd": ytd["adjusted_effective_tax_pct"][0],
        "tax_guide": (record["guide_adjusted_tax_lo_pct"][-1], record["guide_adjusted_tax_hi_pct"][-1]),
    }


def quarter_rest_of_year(facts: dict | None, story: dict | None) -> dict | None:
    if facts is None:
        return None
    ytd, rest = facts["ytd"], facts["rest"]
    lo, hi, mid = facts["revenue_rest"]
    eps_lo, eps_hi, eps_mid = facts["eps_rest"]
    usd_lo, usd_hi, _ = facts["eps_rest_usd"]
    return {
        "ref": "EX_Q_REST",
        "kind": "grouped_bars",
        "title": (f"全年指引减去{ytd}：{rest}收入只需 {minus(mid)}、调整后 EPS 只需 {minus(eps_mid)}，"
                  f"{ytd}是 {minus(facts['revenue_ytd'])}、{minus(facts['eps_ytd'])}"),
        "xlabels": ["收入同比", "调整后 EPS 同比"],
        "groups": [
            {"name": f"{ytd}实际", "color": "NAVY",
             "values": rounded([facts["revenue_ytd"], facts["eps_ytd"]])},
            {"name": f"{rest}隐含（全年指引中值）", "color": "GOLD", "values": rounded([mid, eps_mid])},
        ],
        "bar_labels": True,
        "fmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "同比增速",
        "note": (
            "<b>本季分析稿认为这是全文最重要的一节，而它全是减法，输入都是公司自己印的数。</b>"
            f"全年 = FY{facts['base_year']} 不含 Mobility 的 pro forma 基数乘以本季新闻稿的全年指引；"
            f"{rest} = 全年减去{ytd}实际。"
            f"收入：全年指引 {facts['growth'][0]:g}%–{facts['growth'][1]:g}%，对应{rest}同比 "
            f"{minus(lo)} 至 {minus(hi)}（柱子取中值）。"
            f"调整后 EPS：全年 US${facts['eps_guide'][0]:.2f}–{facts['eps_guide'][1]:.2f} 减去{ytd}的 "
            f"US${facts['eps_now']:.2f}，{rest}是 US${usd_lo:.2f}–{usd_hi:.2f}，对去年同期的 "
            f"US${facts['rest_base_eps']:.2f}（全年 US${facts['eps_base']:.2f} 减{ytd} US${facts['eps_then']:.2f}）"
            f"为 {minus(eps_lo)} 至 {minus(eps_hi)}；每股收益按期相减只是近似，因为股数在变。"
            f"利润率：全年调整后营业利润率扩张指引（剔除 OSTTRA）{facts['expansion'][0]}–{facts['expansion'][1]}bp，"
            f"按它与收入指引的中值算，{rest}调整后营业利润率（剔除 OSTTRA）同比 "
            f"{signed(facts['margin_rest'], 1, 'pp').replace('-', '−')}，"
            f"而{ytd}是 {signed(facts['margin_ytd'], 1, 'pp').replace('-', '−')}。"
            f"税率：{ytd}调整后有效税率 {facts['tax_ytd']:.1f}%，全年指引 "
            f"{facts['tax_guide'][0]:g}%–{facts['tax_guide'][1]:g}%。"
            + (story["rest_of_year_reading"] if story and story.get("rest_of_year_reading") else "")
        ),
        "src_extra": ("全年指引取自本季业绩 8-K EX-99.1 展望表；年初至今取自同一份新闻稿 Exhibit 5、6；"
                      f"FY{facts['base_year']} 基数取自 2026-07-06 8-K/A EX-99.1。{rest}的数为自算（D）。"),
    }


def highlight_words(highlights: list[tuple[str, dict]], rest: dict | None, margin_chart: dict,
                    story: dict | None, cash_story: dict | None) -> str:
    """Section two's description: the charts it actually carries, in its order."""
    topics = {
        "rest": (f"全年指引减去{rest['ytd']}之后{rest['rest']}隐含的增速（分析稿认为全文最重要的一节）"
                 if rest else ""),
        "segments": "分部收入的分化",
        "ratings": "Ratings 那条随发行窗口摆动的交易腿",
        "margin": f"同一个季度被印成{cn_count(len(margin_chart['values']))}个数的营业利润率",
        "rebase": (story["section2_tail"] if story and story.get("section2_tail") else "全年指引的口径重设"),
        "issuance": "计费发行量",
        "unearned": (cash_story or {}).get("topic", "递延收入现金流"),
        "capital": "自由现金流与股东回报",
    }
    return ("本季分析稿的结论按它的顺序画在这里：" + "、".join(topics[key] for key, _ in highlights) + "。"
            + (story.get("section2_unchartable", "") if story else ""))


def quarter_unearned(staging: dict, story: dict | None) -> dict | None:
    """The cash line the report reads as the price of longer renewals, on its own record.

    Drawn in a quarter whose report makes it a finding (a stamped `cash_story`);
    the series itself runs every quarter back to 2016.
    """
    if not story:
        return None
    capital = staging["capital_allocation_usd_m"]
    quarters = capital["quarters"]
    period = staging["periods"][-1]
    year_now, quarter = period_order(period)
    years = sorted({period_order(label)[0] for label in quarters})
    values = [ytd_sum(quarters, capital["unearned_revenue"], f"Q{quarter} {year}") for year in years]
    known = [(year, value) for year, value in zip(years, values) if value is not None]
    now, prior = values[-1], values[-2]
    swing = now - prior
    swings = [(years[i], values[i] - values[i - 1]) for i in range(1, len(years))
              if values[i] is not None and values[i - 1] is not None]
    deepest_year = min(swings, key=lambda row: row[1])[0]
    low_year, low = min(known, key=lambda row: row[1])
    high_year, high = max(known, key=lambda row: row[1])
    words = ytd_words(period)
    ytd = stamped_block(staging, "ytd_vs_guidance", period)
    first = known[0][0]
    title = (f"{words}递延收入现金流 {usd_words(now)}，比去年同期{'少' if swing < 0 else '多'} "
             f"US${abs(swing):,.0f}M"
             + (f"，是 {first} 年以来最大的同比回落" if swing < 0 and deepest_year == year_now else "")
             + ("，但去年同期那一格是记录最高" if prior == high and swing < 0 else ""))
    return {
        "ref": "EX_Q_UNEARNED",
        "kind": "grouped_bars",
        "title": title,
        "xlabels": [str(year) for year in years],
        "groups": [{"name": f"{words}递延收入现金流变动", "color": "NAVY", "values": rounded(values)}],
        "bar_labels": True,
        "fmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$M",
        "note": (
            "现金流量表「Unearned revenue」这一行记预收款的净变化（已剔除并购与处置）："
            "负值表示本期确认掉的预收收入多于新收进来的预收现金。"
            f"每一年取{words}合计，{len(known)} 年都画出来。"
            + (f"最低的一年是 {low_year} 年（{usd_words(low)}）"
               + ("，本季仍在它之上" if now > low else "，本季就是最低")
               + f"；最高的一年是 {high_year} 年（{usd_words(high)}）。")
            + fill_story(story["call"], {}) + "。"
            + fill_story(story["reading"], {}) + "。"
            + (f"同期公司口径的调整后自由现金流{words}同比 "
               f"{minus(pct_change(*ytd['adjusted_free_cash_flow_usd_m']))}（新闻稿 Exhibit 8），"
               f"pro forma 调整后归母净利润同比 {minus(pct_change(*ytd['adjusted_net_income_usd_m']))}"
               "（Exhibit 6）；两个增速不是同一口径 —— " + ytd["basis"] + "。"
               if ytd and ytd.get("adjusted_net_income_usd_m") else "")
            + "2022 年起的各格含 IHS Markit，量级与此前不完全可比；2023 年那一格取的是公司次年改列后的数。"
        ),
        "src_extra": "各季 10-Q / 10-K 合并现金流量表「Unearned revenue」；季度值为相邻两次年初至今申报值之差。",
    }


def nci_distribution_words(staging: dict) -> str:
    """「（FY2025 为 US$321M）」 from the latest year the series carries."""
    actuals = staging["annual_actuals"]
    known = [(year, value) for year, value in
             zip(actuals["fiscal_years"], actuals["nci_distributions_usd_m"]) if value is not None]
    if not known:
        return ""
    year, value = known[-1]
    return f"（FY{year} 为 US${value:,.0f}M）"


def quarter_capital(staging: dict, story: dict | None) -> dict:
    capital = staging["capital_allocation_usd_m"]
    window = 13
    labels = [compact_period(q) for q in capital["quarters"][-window:]]
    fcf = free_cash_flow(staging)
    payout = [b + d for b, d in zip(capital["buyback"], capital["dividends"])]
    record = staging["annual_guidance_history"]
    period = staging["periods"][-1]
    bought = ytd_sum(capital["quarters"], capital["buyback"], period)
    target = ""
    if story and story.get("payout_target"):
        target = (fill_story(story["payout_target"], {"release": record["filed"][-1],
                                                      "prior_release": record["filed"][-2]})
                  + f"{ytd_words(period)}已回购 US${bought:,.0f}M。")
    full, low = q1_low_years(capital["quarters"], capital["operating_cash_flow"])
    if len(low) == len(full):
        season = "第一季度的经营现金流每年都是全年最低的一档"
    else:
        season = (f"{cn_count(len(full))}个完整年份里有{cn_count(len(low))}年，"
                  "第一季度的经营现金流是全年最低的一档"
                  f"（例外是 {'、'.join(str(y) for y in full if y not in low)} 年）")
    return {
        "ref": "EX_Q_CAPITAL",
        "kind": "lines",
        "title": (
            f"本季自由现金流 US${fcf[-1]:,.0f}M、股东回报 US${payout[-1]:,.0f}M，"
            f"回报占自由现金流 {payout[-1] / fcf[-1] * 100:.0f}%"
        ),
        "xlabels": labels,
        "xrot": 90,
        "series": [
            {"name": "自由现金流 D（经营现金流 − 资本开支）",
             "values": rounded(fcf[-window:]), "color": "NAVY"},
            {"name": "回购 + 分红", "values": rounded(payout[-window:]), "color": "RED"},
        ],
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "end_label": True,
        "ylab": "US$M",
        "note": (
            f"季节性很强：{season}，"
            "所以单季的比值不宜单独解读，值得看的是连续几季都在上面的那些窗口。"
            + target
            + "<b>本页的自由现金流是自算口径（D）</b>：经营现金流减资本开支。"
            "公司自己的定义还要再减去付给非控股股东的分派，"
            f"因此公司口径每年都比本页低，差额恰好等于那笔分派{nci_distribution_words(staging)}。"
            "指引里用的又是第三个口径「调整后自由现金流」，"
            "见 Exhibit {EX_FCF_BAND}。"
            "本页口径逐季列在核对表里，调整后口径的指引区间列在全年指引那张核对表里；"
            "公司自己的口径本页没有进表。"
        ),
        "src_extra": "各季 10-Q / 10-K 合并现金流量表；季度值为相邻两次年初至今申报值之差。",
    }


# ── section four: the long filed record ──────────────────────────────────────
# What the disposition gain in a given quarter actually was. The amount is read
# from the series; only the name of the sale has to be written down. Keyed by
# quarter because the *largest* gain moves when the window moves -- it used to be
# 2022Q1 and extending back to 2016 made it 2016Q3, at which point a sentence
# that derived its quarter and percentage but hard-coded "US$1,344M, the business
# sold to clear antitrust review" attributed an IHS-Markit-era divestiture to
# 2016. A quarter with no entry gets no clause rather than the wrong one.
DISPOSAL_EVENTS = {
    "Q3 2016": "出售 J.D. Power（2016-09 完成，税前 US$722M / 税后 US$521M）",
    "Q1 2022": "为通过反垄断审查而在 IHS Markit 合并前后卖掉的业务",
}


def disposition_spike(long_history: dict) -> dict:
    """The largest reported operating margin in the record, and what caused it.

    Three separate notes describe this spike. All three used to hard-code
    2022Q1 / 79.2% / US$1,344M, which was right for a record starting in 2017
    and wrong the moment it reached 2016: J.D. Power's sale put a bigger one in
    2016Q3. One derivation, so the three cannot drift apart from each other or
    from the data.
    """
    reported = [o / r * 100 for o, r in zip(long_history["operating_income_usd_m"],
                                            long_history["revenue_usd_m"])]
    index = reported.index(max(reported))
    return {
        "index": index,
        "quarter": long_history["quarters"][index],
        "label": compact_period(long_history["quarters"][index]),
        "reported": reported[index],
        "ex_credits": operating_margin_ex_credits(long_history)[index],
        "gain": long_history["gain_on_dispositions_usd_m"][index] or 0,
    }


def opening_breaks(record: dict) -> tuple[int, list[int]]:
    """How many settled years had an opening range, and which settled below it."""
    settled = {record["fiscal_years"][i]: v
               for i, v in enumerate(record["actual_adjusted_eps"]) if v is not None}
    years, broken = 0, []
    other_basis = rebased_vintages(record)
    for i, slot in enumerate(record["vintage_slots"]):
        year = record["fiscal_years"][i]
        if (slot != "initial" or year not in settled or record["guide_adjusted_eps_lo"][i] is None
                or i in other_basis):
            continue
        years += 1
        if settled[year] < record["guide_adjusted_eps_lo"][i]:
            broken.append(year)
    return years, broken


def long_ratings(staging: dict) -> dict:
    split = staging["ratings_revenue_split_usd_m"]
    record = staging["annual_guidance_history"]
    opening_years, broken = opening_breaks(record)
    cycle = ratings_cycle(staging)
    labels = [compact_period(q) for q in split["quarters"]]
    transaction = split["transaction"]
    non_transaction = split["non_transaction"]
    peak_index, trough_index = cycle["peak"], cycle["trough"]
    trough = transaction[trough_index]
    peak = transaction[peak_index]
    trough_year = int(split["quarters"][trough_index].split()[1])
    withdrawn = record["suspension"]["announced"]
    if len(broken) == 1:
        guidance_words = (f"{opening_years} 年里唯一一次开局指引被<b>跌破</b>的财年是 {broken[0]} 年")
        if broken[0] == trough_year:
            guidance_words += (f"，而 {broken[0]} 年正是深蓝这条线塌到谷底的那一年"
                               + (f" —— 公司当年 {int(withdrawn[5:7])} 月撤回全年指引时给出的理由，"
                                  "写的就是「Ratings 业务面临极弱的市场环境」。"
                                  if int(withdrawn[:4]) == broken[0] else "。"))
        else:
            guidance_words += "。"
    elif broken:
        guidance_words = (f"{opening_years} 年里开局指引被<b>跌破</b>过 {len(broken)} 次："
                          f"{'、'.join(str(y) for y in broken)} 年。")
    else:
        guidance_words = f"{opening_years} 年里开局指引一次都没有被<b>跌破</b>过。"
    return {
        "ref": "EX_L_RATINGS",
        "kind": "lines",
        "title": (
            f"{len(labels)} 季 Ratings 两条腿：交易性在 {labels[peak_index]} 见顶 "
            f"US${peak:,.0f}M，{labels[trough_index]} 只剩 US${trough:,.0f}M"
            f"（−{(1 - trough / peak) * 100:.0f}%），"
            + (f"如今回到 US${transaction[-1]:,.0f}M 的新高；" if cycle["at_high"] else
               f"如今是 US${transaction[-1]:,.0f}M；")
            + ("非交易性同期没有塌陷过" if cycle["held_up"] else "非交易性同期也塌陷过")
        ),
        "xlabels": labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": "交易性（按每笔发行评级收费）", "values": rounded(transaction),
             "color": "NAVY"},
            {"name": "非交易性（存续监控、年费、实体评级）",
             "values": rounded(non_transaction), "color": "GOLD"},
        ],
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "end_label": True,
        "ylab": "US$M",
        "note": (
            "<b>本页最重要的一条长序列，也是八个季度的窗口完全看不出来的那种。</b>"
            "深蓝那条按每一笔公开发债与银团贷款的评级收费："
            f"它在 {labels[peak_index]} 见顶 US${peak:,.0f}M，"
            f"到 {labels[trough_index]} 只剩 US${trough:,.0f}M，"
            + (f"然后用了{years_words(cycle['years_since_trough'])}回到今天的新高。" if cycle["at_high"] else
               f"{years_words(cycle['years_since_trough'])}后的今天是 US${transaction[-1]:,.0f}M。")
            + "金色那条是存续期监控与年费，同一段时间里"
            f"从 US${non_transaction[0]:,.0f}M 走到 US${non_transaction[-1]:,.0f}M，"
            + ("整段没有出现过深蓝那样的塌陷。" if cycle["held_up"] else "")
            + "<b>把这张图和第一节的指引记录并排看</b>："
            + guidance_words
            + "两条线相加恒等于申报的 Ratings 分部收入。"
        ),
        "src_extra": "各季 10-Q / 10-K 收入附注与业绩 8-K EX-99.1 Revenue by Type 表。",
    }


def tens_words(value: float) -> str:
    """``54.8`` → ``'五十几'``, ``22.8`` → ``'二十几'``."""
    return f"{_TENS[int(value // 10)]}十几"


_TENS = "零一二三四五六七八九"


def merger_margin_words(long_history: dict) -> str:
    """「从五十几个百分点被压到二十几，再用四年爬回今天的水平」, read off the series."""
    ex_credits = operating_margin_ex_credits(long_history)
    at = long_history["structural_break_at"][-1]
    before = max(ex_credits[at - 4:at])
    trough = min(ex_credits[at:])
    trough_at = at + ex_credits[at:].index(trough)
    climb = (len(ex_credits) - 1 - trough_at) / 4
    return (f"深蓝这条线从{tens_words(before)}个百分点被压到{tens_words(trough)}，"
            f"再用{cn_count(int(climb))}年爬回今天的水平")


def long_margin(staging: dict) -> dict:
    long_history = staging["long_history"]
    labels = [compact_period(q) for q in long_history["quarters"]]
    revenue = long_history["revenue_usd_m"]
    operating = long_history["operating_income_usd_m"]
    gaap = [o / r * 100 for o, r in zip(operating, revenue)]
    ex_gain = operating_margin_ex_credits(long_history)
    quarters = long_history["quarters"]
    peak = max(gaap)
    peak_index = gaap.index(peak)
    # The gain that produced the spike travels with the quarter, so it is read
    # rather than written down -- see DISPOSAL_EVENTS above for why.
    peak_gain = long_history["gain_on_dispositions_usd_m"][peak_index] or 0
    shift = long_history["pension_restatement_per_quarter_usd_m"]
    unrestated = [shift / r * 100 for r, label in zip(revenue, quarters)
                  if label.endswith(str(long_history["pension_unrestated_year"]))]
    merger = long_history["structural_break_at"][-1]
    return {
        "ref": "EX_L_MARGIN",
        "kind": "lines",
        "title": (
            f"{len(labels)} 季营业利润率：申报口径在 {labels[peak_index]} 冲到 {peak:.1f}%，"
            f"剔除处置损益与联营收益后同一季只有 {ex_gain[peak_index]:.1f}%"
        ),
        "xlabels": labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": "申报 GAAP 营业利润率", "values": rounded(gaap), "color": "GOLD"},
            {"name": "（收入 − 费用）/ 收入 D", "values": rounded(ex_gain), "color": "NAVY"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "营业利润率",
        "break_at": long_history["structural_break_at"],
        "break_label": long_history["structural_break_label"],
        "note": (
            "<b>两条线之间的距离，是公司加在费用行下面的两项：处置损益与联营收益。</b>"
            "深蓝那条是收入减总费用，两条腿每季都申报；"
            "金色那条是申报的营业利润，也就是把那两项加回之后的数。"
            f"最夸张的一季是 {labels[peak_index]}：申报营业利润率 {peak:.1f}%，"
            + (f"里面装着 US${peak_gain:,.0f}M 的处置收益"
               + (f" —— {DISPOSAL_EVENTS[quarters[peak_index]]}，"
                  if quarters[peak_index] in DISPOSAL_EVENTS else "，")
               if peak_gain else "")
            + f"剔掉之后是 {ex_gain[peak_index]:.1f}%。"
            f"<b>断点标在 {year_quarter(quarters[merger])}</b>：IHS Markit 于 2022-02-28 交割，"
            f"此后并购无形资产摊销进入费用，{merger_margin_words(long_history)}。"
            "断点两侧不是同一家公司，不要当成一条连续的经营曲线读。"
            "<b>左端第一道断点是列报口径，不是经营变化。</b>"
            "公司按 ASU 2017-07 把非服务性养老金成本挪到营业利润之下，"
            "并在 2018 年第一季度起的三份季报里重述了 2017 年前三季 —— "
            "本页 2017 年之后用的正是那批重述值。2016 的四个季度从未被任何申报按新口径重述过"
            "（<b>年度</b>数其实被重述过：FY2018 10-K 把 2016 全年营业利润从 3,369 改为 3,341；"
            "没有被重述的是<b>季度</b>拆分，而本页画的是季度线），"
            f"所以它们只能是原始申报口径。落差经逐季核对为每季 {shift:.1f}，"
            f"对营业利润率的影响 {min(unrestated):.1f}–{max(unrestated):.1f}pp —— "
            f"本页此前因此把序列截在 {year_quarter(quarters[long_history['structural_break_at'][0]])}，"
            "现在改为画出来并标注：断点的大小是量出来的，不再只是一个理由。"
        ),
        "src_extra": "各季 10-Q / 10-K 合并损益表的营业利润行与处置收益行。",
    }


def merger_jump(staging: dict) -> str:
    """「从 US$8,297M 跳到 US$11,181M（+34.8%）」 from the annual actuals."""
    actuals = staging["annual_actuals"]
    at = actuals["fiscal_years"].index(MERGER_YEAR)
    before, after = actuals["revenue_usd_m"][at - 1], actuals["revenue_usd_m"][at]
    return f"从 US${before:,.0f}M 跳到 US${after:,.0f}M（{pct_change(after, before):+.1f}%）"


# IHS Markit closed on 2022-02-28: the year whose reported revenue carries ten
# months of the acquiree and whose prior year carries none.
MERGER_YEAR = 2022


def long_revenue(staging: dict, story: dict | None) -> dict:
    long_history = staging["long_history"]
    labels = [compact_period(q) for q in long_history["quarters"]]
    revenue = long_history["revenue_usd_m"]
    yoy = [None] * 4 + [pct_change(revenue[i], revenue[i - 4])
                        for i in range(4, len(revenue))]
    merger = long_history["structural_break_at"][-1]
    return {
        "ref": "EX_L_REV",
        "kind": "gs_bar",
        "title": (
            f"{len(labels)} 季收入从 US${revenue[0]:,.0f}M 到 US${revenue[-1]:,.0f}M，"
            f"其中 {MERGER_YEAR} 年那一跳是并表不是增长"
        ),
        "xlabels": labels,
        "xstep": LONG_STEP,
        "values": rounded(revenue),
        "legend": "合并收入",
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$M",
        "ylab2": "同比增速",
        "yoy": {"name": "同比增速 (RHS)", "values": rounded(yoy),
                "color": "GREEN", "yfmt": "pct1"},
        "note": (
            f"<b>右轴那根 {MERGER_YEAR} 年的尖峰要按口径读，不要按经营读。</b>"
            f"IHS Markit 于 2022-02-28 完成合并，因此 {MERGER_YEAR} 年只装进约十个月的被并购方收入，"
            f"而 {MERGER_YEAR - 1} 年一个月都没有：申报口径的全年收入{merger_jump(staging)}，"
            "但 10-K 自己给的备考口径（假设合并发生在 2021 年初）是从 US$12,382M "
            "降到 US$11,842M，也就是 −4.4% —— <b>同一年，两个方向相反的符号。</b>"
            f"断点因此标在 {year_quarter(long_history['quarters'][merger])}，本图不把它画成一条连续的增长曲线。"
            + (story["revenue_restatement"] if story and story.get("revenue_restatement") else "")
        ),
        "src_extra": "各季 10-Q / 10-K 合并损益表；第四季度为全年减九个月。",
    }


def long_segment_mix(staging: dict) -> dict:
    segments = staging["segments_usd_m"]
    labels = [compact_period(q) for q in segments["quarters"]]
    names = [("ratings", "Ratings", "NAVY"), ("market_intelligence", "Market Intelligence", "BLUE"),
             ("energy", "Energy（原 Commodity Insights / Platts）", "GOLD"),
             ("indices", "Indices", "GREEN"), ("mobility", "Mobility", "RED")]
    totals = [
        sum((segments["revenue"][key][i] or 0) for key, _, _ in names)
        for i in range(len(labels))
    ]
    series = []
    for key, label, color in names:
        values = [
            None if segments["revenue"][key][i] is None
            else segments["revenue"][key][i] / totals[i] * 100
            for i in range(len(labels))
        ]
        series.append({"name": label, "values": rounded(values), "color": color})
    ratings_share = [v for v in series[0]["values"] if v is not None]
    low = min(ratings_share)
    diluted = low < ratings_share[0] and ratings_share[-1] > low
    return {
        "ref": "EX_L_SEG",
        "kind": "lines",
        "title": (
            f"{cn_count(len(names))}个分部各自占分部收入合计的比重：Ratings 从 {ratings_share[0]:.0f}% "
            + (f"被稀释到 {low:.0f}%，如今回到 {ratings_share[-1]:.0f}%" if diluted else
               f"走到 {ratings_share[-1]:.0f}%")
        ),
        "xlabels": labels,
        "xstep": LONG_STEP,
        "series": series,
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "占分部收入合计比",
        "break_at": labels.index("Q1'22"),
        "break_label": "IHS Markit 并表 + 分部重切",
        "note": (
            f"分母是{cn_count(len(names))}个分部收入之和（不含分部间抵销），"
            f"所以{cn_count(len(names))}条线恒等于 100%。"
            "<b>2022Q1 这个断点同时装着三件事</b>：IHS Markit 并表、"
            "Mobility 与 Engineering Solutions 两个新分部出现、"
            "以及 Market Intelligence 的 Commodities 业务转入当时的 Commodity Insights。"
            "分部名两次变更，只有一次是真的重切："
            "Platts 在 2022Q1 更名 Commodity Insights 并同时接收业务转入，"
            "而 Commodity Insights 在 FY2025 10-K 里改称 Energy 是<b>纯改名</b> —— "
            "同一年的数字在两个名字下逐一相等，而申报文件里没有任何一句说明它改过名。"
            "本页统一用最新名。"
            "Engineering Solutions 没有画进来："
            "它只在 2022Q1 至 2023Q2 存在，两端都是不满一个季度的残段，"
            "画成一条线会把两次交割日读成经营变化。"
        ),
        "src_extra": "各季 10-Q / 10-K 分部附注；第四季度为全年减九个月。",
    }


REVENUE_TYPES = [("subscription", "Subscription", "NAVY"),
                 ("non_subscription_transaction", "Non-subscription / Transaction", "RED"),
                 ("non_transaction", "Non-transaction", "GOLD"),
                 ("asset_linked_fees", "Asset-linked fees", "GREEN"),
                 ("sales_usage_royalties", "Sales usage-based royalties", "BLUE"),
                 ("recurring_variable", "Recurring variable", "MBLUE")]


def type_identity(staging: dict) -> tuple[int, float, bool]:
    """Six revenue types less the elimination against consolidated revenue, quarter by quarter."""
    types = staging["revenue_by_type_usd_m"]
    long_history = staging["long_history"]
    consolidated = dict(zip(long_history["quarters"], long_history["revenue_usd_m"]))
    derived = set(staging["segments_usd_m"]["derived_quarters"])
    gross = gross_revenue_by_type(types)
    residuals = [(abs(gross[i] - types["intersegment_elimination"][i] - consolidated[label]), label)
                 for i, label in enumerate(types["quarters"])]
    worst = max(residual for residual, _ in residuals)
    return (len(residuals), worst,
            all(label in derived for residual, label in residuals if residual == worst))


def long_revenue_types(staging: dict) -> dict:
    types = staging["revenue_by_type_usd_m"]
    labels = [compact_period(q) for q in types["quarters"]]
    gross = gross_revenue_by_type(types)
    series = [
        {"name": label, "color": color,
         "values": rounded([types[key][i] / gross[i] * 100 for i in range(len(labels))])}
        for key, label, color in REVENUE_TYPES
    ]
    transaction = series[1]["values"]
    subscription = series[0]["values"]
    checked, worst, worst_derived = type_identity(staging)
    return {
        "ref": "EX_L_TYPE",
        "kind": "lines",
        "title": (
            f"六条申报收入类型各自占毛收入的比重：交易性从 {min(transaction):.1f}% "
            f"回到 {transaction[-1]:.1f}%，订阅在 {min(subscription):.1f}%–{max(subscription):.1f}% 之间"
        ),
        "xlabels": labels,
        "xrot": 90,
        "series": series,
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "占毛收入比",
        "note": (
            "<b>这六条线是申报值，不是本页的分类。</b>"
            "公司在收入附注里就按这六种类型披露金额，"
            f"六条相加减去分部间抵销等于申报的合并收入，本页 {checked} 个季度逐季核对过"
            + (f"，最大残差 US${worst:,.0f}M"
               + ("（出现在按「全年减九个月」推出来的第四季度上）" if worst_derived else "")
               if worst else "")
            + "。"
            f"窗口从 {year_quarter(types['quarters'][0])} 开始，"
            "因为公司从那一季起（与 ASC 606 同时）才在收入附注里按类型拆分全公司收入，此前只有订阅 / 非订阅两分；"
            "2022Q1 起的结构变化有一部分是 IHS Markit 并表带来的，不是同一批业务的迁移。"
            "读法是：红色那条（交易性）是周期腿，深蓝（订阅）与绿色（资产挂钩费）是年金腿，"
            "而<b>年金腿里那条绿色的资产挂钩费其实也有自己的周期</b> —— "
            "它按 ETF 资产规模收费，跟的是市场点位而不是发行窗口。"
        ),
        "src_extra": "各季 10-Q / 10-K 收入分解附注的六条收入类型行。",
    }


def long_indices(staging: dict) -> dict:
    indices = staging["indices_kpi"]
    labels = [compact_period(q) for q in indices["etf_aum_quarters"]]
    aum = indices["etf_aum_ending_usd_tn"]
    return {
        "ref": "EX_L_AUM",
        "kind": "gs_line",
        "title": (
            f"跟踪 S&P 指数的 ETF 期末资产规模从 US${aum[0]:.2f}T 到 US${aum[-1]:.2f}T，"
            f"{len(labels)} 季涨到原来的 {aum[-1] / aum[0]:.1f} 倍"
        ),
        "xlabels": labels,
        "xstep": LONG_STEP,
        "values": rounded(aum),
        "legend": "期末 ETF AUM",
        "fmt": "usd2",
        "yfmt": "usd2",
        "label_fmt": "usd2",
        "ylab": "US$ 万亿",
        "note": (
            "Indices 分部的资产挂钩费按这个规模收费，所以这条线是那条收入线的量。"
            "<b>它和计费发行量（Exhibit {EX_Q_ISSUANCE}）是本页仅有的两条不由公司经营决定的量</b> —— "
            "它跟的是市场点位与资金流向，公司能决定的只是费率与指数授权本身。"
            "<b>只画期末值，不画季度平均值</b>：10-K 给的是全年平均而不是第四季度平均，"
            "所以平均值那条线每年第四季度都有一个洞，本页不用推算去填它。"
            "2022 年公司同时披露过含与不含 IHS Markit 指数资产的两个口径，"
            "本页统一用不含的那个。"
        ),
        "src_extra": "各季 10-Q / 10-K 的 MD&A Indices 分部段落。",
    }


def dividend_words(staging: dict) -> str:
    """「全年分红从 FY2016 的 US$380M 走到 FY2025 的 US$1,170M，只有 FY2024 比上一年少」"""
    capital = staging["capital_allocation_usd_m"]
    quarters, dividends = capital["quarters"], capital["dividends"]
    full, _ = q1_low_years(quarters, dividends)
    annual = [(year, sum(dividends[quarters.index(f"Q{n} {year}")] for n in (1, 2, 3, 4)))
              for year in full]
    fell = [year for (year, value), (_, prior) in zip(annual[1:], annual) if value < prior]
    return (f"全年分红从 FY{annual[0][0]} 的 US${annual[0][1]:,.0f}M 走到 "
            f"FY{annual[-1][0]} 的 US${annual[-1][1]:,.0f}M，"
            + ("逐年抬升" if not fell else
               f"只有 {'、'.join(f'FY{y}' for y in fell)} 比上一年少" if len(fell) < len(annual) / 2 else
               f"{'、'.join(f'FY{y}' for y in fell)} 都比上一年少")
            + "。")


def long_capital(staging: dict) -> dict:
    capital = staging["capital_allocation_usd_m"]
    quarters = capital["quarters"]
    labels = [compact_period(q) for q in quarters]
    fcf = free_cash_flow(staging)
    buyback = capital["buyback"]
    dividends = capital["dividends"]
    payout = [b + d for b, d in zip(buyback, dividends)]
    peak_index = buyback.index(max(buyback))
    peak_year = int(quarters[peak_index].split()[1])

    def year_total(values, year):
        return sum(values[quarters.index(f"Q{n} {year}")] for n in (1, 2, 3, 4))

    paused = year_total(buyback, peak_year - 1) == 0
    year_buyback = year_total(buyback, peak_year)
    year_ocf = year_total(capital["operating_cash_flow"], peak_year)
    return {
        "ref": "EX_L_CAPITAL",
        "kind": "lines",
        "title": (
            f"{len(labels)} 季自由现金流与股东回报："
            f"{labels[peak_index]} 单季回购 US${max(buyback):,.0f}M，"
            f"是同季自由现金流的 {max(buyback) / fcf[peak_index]:.1f} 倍"
        ),
        "xlabels": labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": "自由现金流 D（经营现金流 − 资本开支）", "values": rounded(fcf),
             "color": "NAVY"},
            {"name": "回购 + 分红", "values": rounded(payout), "color": "RED"},
        ],
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "end_label": True,
        "ylab": "US$M",
        "note": (
            f"<b>{peak_year} 年第{cn_ordinal(int(quarters[peak_index][1]))}季度那根尖峰是一次性的，而且日期很说明问题。</b>"
            + (f"公司在 {peak_year - 1} 年全年回购金额<b>恰好为零</b>（合并待批期间停止回购），" if paused else "")
            + "然后在 IHS Markit 交割的次日（2022-03-01）启动 US$7.0B 的加速回购，"
            f"当季回购 US${max(buyback):,.0f}M，而同季自由现金流只有 "
            f"US${fcf[peak_index]:,.0f}M。"
            f"整个 {peak_year} 年回购 US${year_buyback:,.0f}M，约为当年经营现金流的 "
            f"{year_buyback / year_ocf:.1f} 倍，"
            f"钱来自 {peak_year - 1} 年攒下的现金与剥离所得，"
            "账上现金也因此从 2021 年末的 US$6,497M 降到 2022 年末的 US$1,286M。"
            f"分红那条腿则平稳得多：{dividend_words(staging)}"
            "现金流量表在 10-Q 里只有年初至今栏，除第一季外每季均为相邻两次申报值之差；"
            "四个季度相加与申报全年逐年相等，残差为零。"
        ),
        "src_extra": "各季 10-Q / 10-K 合并现金流量表。",
    }


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series.

    The adjusted EPS is the company's headline one: pro forma where the series
    carries it (the quarter of the spin), else the quarter's own adjusted
    figure from its stamped block, else the reported diluted EPS -- a quarter
    whose release printed no pro forma table must not reach for last quarter's.
    """
    fin = staging["financials"]
    transaction = staging["ratings_revenue_split_usd_m"]["transaction"]
    eps = fin["pro_forma_adjusted_diluted_eps_usd"][-1]
    figures = stamped_block(staging, "quarter_figures", staging["periods"][-1])
    if eps is None and figures and figures.get("adjusted_diluted_eps_usd") is not None:
        eps = figures["adjusted_diluted_eps_usd"]
    return [f"Revenue ${fin['revenue_usd_m'][-1] / 1000:.2f}B",
            f"Ratings 交易性 {(transaction[-1] / transaction[-5] - 1) * 100:+.0f}%",
            f"调整后 EPS ${eps:.2f}" if eps is not None else f"摊薄 EPS ${fin['diluted_eps_usd'][-1]:.2f}"]


def margin_change_bp(ytd: dict, ex_equity: bool) -> float:
    """Year-to-date adjusted operating margin against the year before, in basis points.

    ``ex_equity`` takes the adjusted equity income out first -- that is the
    company's own definition of the margin "excluding OSTTRA".
    """
    margins = []
    for i in (0, 1):
        profit = ytd["adjusted_operating_profit_usd_m"][i]
        if ex_equity:
            profit -= ytd["adjusted_equity_income_usd_m"][i]
        margins.append(profit / ytd["revenue_usd_m"][i] * 100)
    return (margins[0] - margins[1]) * 100


def story_values(staging: dict) -> dict[str, str]:
    """The numbers a story or report block may name, computed from the series."""
    record = staging["annual_guidance_history"]
    period = staging["periods"][-1]
    mobility = staging["segments_usd_m"]["revenue"].get("mobility", [None])[-1]
    values = {} if mobility is None else {"mobility": f"{mobility:,.0f}"}
    at = record["basis_break_at"]
    if at is not None:
        prior_mid = (record["guide_adjusted_eps_lo"][at - 1] + record["guide_adjusted_eps_hi"][at - 1]) / 2
        new_mid = (record["guide_adjusted_eps_lo"][at] + record["guide_adjusted_eps_hi"][at]) / 2
        values.update(drop=f"{prior_mid - new_mid:.2f}", prior_mid=f"{prior_mid:.3f}",
                      new_mid=f"{new_mid:.3f}")
    capital = staging["capital_allocation_usd_m"]
    buyback_ytd = ytd_sum(capital["quarters"], capital["buyback"], period)
    issuance = staging["billed_issuance_usd_bn"]["total"]
    total = ratings_total(staging)
    values.update(
        following=display_period(shift_quarter(period, 1)),
        ytd_words=ytd_words(period),
        ratings_yoy=minus(pct_change(total[-1], total[-5])),
        buyback_q=f"US${capital['buyback'][-1]:,.0f}M",
        buyback_prev_q=f"US${capital['buyback'][-2]:,.0f}M",
        issuance_q=f"US${issuance[-1]:,.0f}B",
        issuance_yoy=signed(pct_change(issuance[-1], issuance[-5]), 0),
    )
    if buyback_ytd is not None:
        values["buyback_ytd"] = f"US${buyback_ytd:,.0f}M"
    figures = stamped_block(staging, "quarter_figures", period) or {}
    for key, name in (("energy_organic_cc_revenue_usd_m", "energy_organic_cc"),
                      ("mi_subscription_revenue_usd_m", "mi_subscription_yoy")):
        if figures.get(key):
            values[name] = minus(pct_change(*figures[key]))
    ytd = stamped_block(staging, "ytd_vs_guidance", period)
    if ytd:
        guide = ytd["guidance"]
        values.update(
            margin_guide="{}–{}bp".format(*guide["adjusted_margin_expansion_bp"]),
            margin_guide_ex="{}–{}bp".format(*guide["adjusted_margin_expansion_ex_osttra_bp"]),
            margin_ytd=f"{margin_change_bp(ytd, False):+.0f}bp",
            margin_ytd_ex=f"{margin_change_bp(ytd, True):+.0f}bp",
        )
    return values


def build_payload(staging: dict) -> dict:
    financials = staging["financials"]
    periods = staging["periods"]
    period = periods[-1]
    period_end = staging["period_ends"][-1]
    latest = latest_block(staging, period=period, period_end=period_end)
    release = release_source(staging)
    following = shift_quarter(period, 1)
    figures = stamped_block(staging, "quarter_figures", period)
    story = stamped_block(staging, "quarter_story", period)
    values = story_values(staging)

    revenue = financials["revenue_usd_m"]
    operating = financials["operating_income_usd_m"]
    gain = financials["gain_on_dispositions_usd_m"]
    eps = financials["diluted_eps_usd"]
    record = staging["annual_guidance_history"]
    split = staging["ratings_revenue_split_usd_m"]
    spike = disposition_spike(staging["long_history"])
    cycle = ratings_cycle(staging)

    lead_ex, lead_tables, settled_words = settled_lead(staging, values)
    guidance_ex, stats = guidance_charts(
        staging, fcf_story=story.get("fcf_open_year") if story else None)
    settled_ex = lead_ex + guidance_ex
    margin_chart = quarter_margin_bases(staging, figures, story)
    rest = rest_of_year(staging)
    cash_story = stamped_block(staging, "cash_story", period)
    # Section two runs in the report's order: its core arithmetic first, then the
    # segment and Ratings readings, the margin bases, the rebase, issuance, the
    # cash line it calls the first crack, and the capital charts.
    highlights = [
        ("rest", quarter_rest_of_year(rest, story)),
        ("segments", quarter_segments(staging, story, figures)),
        ("ratings", quarter_ratings(staging)),
        ("margin", margin_chart),
        ("rebase", quarter_mobility(staging)),
        ("issuance", quarter_issuance(staging)),
        ("unearned", quarter_unearned(staging, cash_story)),
        ("capital", quarter_capital(staging, story)),
    ]
    highlights = [(key, exhibit) for key, exhibit in highlights if exhibit]
    highlight_ex = [exhibit for _, exhibit in highlights]
    next_ex, next_tables, next_words = next_section(staging, following)
    routine_ex = [
        long_ratings(staging),
        long_margin(staging),
        long_revenue(staging, story),
        long_segment_mix(staging),
        long_revenue_types(staging),
        long_indices(staging),
        long_capital(staging),
    ]

    exhibits = number_exhibits(settled_ex + highlight_ex + next_ex + routine_ex, start=2)
    resolve_exhibit_refs(exhibits)
    first_table = exhibits[-1]["n"] + 1

    # ── audit tables ────────────────────────────────────────────────────────
    def fmt_band(low, high, digits=2, prefix="$"):
        if low is None:
            return "—"
        if low == high:
            return f"~{prefix}{low:,.{digits}f}"
        return f"{prefix}{low:,.{digits}f}–{high:,.{digits}f}"

    guidance_rows = [
        [record["vintages"][i], f"FY{record['fiscal_years'][i]}", record["filed"][i],
         "8-K EX-99.1" if record["filed_in_8k"][i] else "投资者日（由后续 8-K 复述）",
         fmt_band(record["guide_adjusted_eps_lo"][i], record["guide_adjusted_eps_hi"][i]),
         fmt_band(record["guide_gaap_eps_lo"][i], record["guide_gaap_eps_hi"][i]),
         fmt_band(record["guide_revenue_growth_lo_pct"][i],
                  record["guide_revenue_growth_hi_pct"][i], 1, "") + ("%" if
             record["guide_revenue_growth_lo_pct"][i] is not None else ""),
         fmt_band(record["guide_adjusted_fcf_lo_usd_m"][i],
                  record["guide_adjusted_fcf_hi_usd_m"][i], 0),
         f"${record['actual_adjusted_eps'][i]:,.2f}"
         if record["actual_adjusted_eps"][i] is not None else "—",
         f"${record['actual_gaap_eps'][i]:,.2f}"
         if record["actual_gaap_eps"][i] is not None else "—"]
        for i in range(len(record["vintages"]))
    ]

    quarterly_rows = [
        [periods[i],
         f"${revenue[i]:,.0f}M",
         f"{pct_change(revenue[i], revenue[i - 4]):+.1f}%" if i >= 4 else "—",
         f"${operating[i]:,.0f}M",
         f"{operating[i] / revenue[i] * 100:.1f}%",
         # Untagged in every fiscal fourth quarter; a dash rather than a zero.
         f"${gain[i]:,.0f}M" if gain[i] is not None else "—",
         f"{(revenue[i] - financials['total_expenses_usd_m'][i]) / revenue[i] * 100:.1f}%",
         f"${financials['net_income_usd_m'][i]:,.0f}M",
         f"${eps[i]:,.2f}",
         f"{financials['diluted_shares_m'][i]:,.1f}"]
        for i in range(len(periods))
    ]

    split_window = 21
    split_rows = [
        [split["quarters"][i],
         f"${split['transaction'][i]:,.0f}M",
         f"${split['non_transaction'][i]:,.0f}M",
         f"${split['transaction'][i] + split['non_transaction'][i]:,.0f}M",
         f"{split['transaction'][i] / (split['transaction'][i] + split['non_transaction'][i]) * 100:.1f}%"]
        for i in range(len(split["quarters"]) - split_window, len(split["quarters"]))
    ]

    segments = staging["segments_usd_m"]
    segment_window = 13
    segment_rows = [
        [segments["quarters"][i]]
        + [f"${segments['revenue'][key][i]:,.0f}M"
           if segments["revenue"][key][i] is not None else "—"
           for key in ("ratings", "indices", "energy", "market_intelligence", "mobility")]
        + [f"${segments['intersegment_elimination'][i]:,.0f}M",
           "全年减九个月 D" if segments["quarters"][i] in segments["derived_quarters"]
           else "10-Q 申报三个月栏"]
        for i in range(len(segments["quarters"]) - segment_window, len(segments["quarters"]))
    ]

    capital = staging["capital_allocation_usd_m"]
    capital_window = 13
    capital_rows = [
        [capital["quarters"][i],
         f"${capital['operating_cash_flow'][i]:,.0f}M",
         f"${capital['capex'][i]:,.0f}M",
         f"${capital['operating_cash_flow'][i] - capital['capex'][i]:,.0f}M",
         f"${capital['buyback'][i]:,.0f}M",
         f"${capital['dividends'][i]:,.0f}M"]
        for i in range(len(capital["quarters"]) - capital_window, len(capital["quarters"]))
    ]

    first_fy, last_fy = record["fiscal_years"][0], record["fiscal_years"][-1]
    tables = [
        {
            "title": (f"全年指引的全部 {len(record['vintages'])} 档 vintage 与被它们指引的那一年"
                      f"（FY{first_fy}–FY{last_fy}）"),
            "headers": ["vintage", "财年", "发布日", "载体", "调整后 EPS 指引",
                        "GAAP EPS 指引", "收入增速指引", "调整后 FCF 指引",
                        "该年实际调整后 EPS", "该年实际 GAAP EPS"],
            "rows": guidance_rows,
        },
    ]
    tables += lead_tables + next_tables
    tables += [
        {
            "title": f"近{cn_count(len(periods))}季损益表与两个营业利润率口径",
            "headers": ["期间", "收入", "收入 YoY", "营业利润", "营业利润率 D",
                        "其中处置收益", "（收入−费用）/ 收入 D", "净利润",
                        "摊薄 EPS", "摊薄股数（百万）"],
            "rows": quarterly_rows,
        },
        {
            "title": f"近{cn_count(split_window)}季 Ratings 的交易性与非交易性收入",
            "headers": ["期间", "交易性", "非交易性", "分部收入合计", "交易性占比 D"],
            "rows": split_rows,
        },
        {
            "title": f"近{cn_count(segment_window)}季分部收入（含分部间收入的申报列）",
            "headers": ["期间", "Ratings", "Indices", "Energy", "Market Intelligence",
                        "Mobility", "分部间抵销", "取数方式"],
            "rows": segment_rows,
        },
        {
            "title": f"近{cn_count(capital_window)}季现金流与股东回报",
            "headers": ["期间", "经营现金流", "资本开支", "自由现金流 D", "回购", "分红"],
            "rows": capital_rows,
        },
        ai_capex_cycle_table(0),
    ]
    for offset, table in enumerate(tables):
        table["n"] = first_table + offset
        tables[offset] = {"n": table.pop("n"), **table}

    adj_above, adj_inside, adj_below = stats["adjusted"]
    gaap_above, gaap_inside, gaap_below = stats["gaap"]
    finished_years = adj_above + adj_inside + adj_below
    # The two metrics no longer settle the same number of years: FY2016 has an
    # adjusted range and no GAAP one, because the company said it could not
    # reconcile the two without unreasonable effort. Counting them with one
    # number would put a year in the GAAP denominator that GAAP never guided.
    gaap_finished = gaap_above + gaap_inside + gaap_below
    audit_words = {"unaudited": "未审计", "audited": "已审计"}[latest["audit_status"]]
    transaction = split["transaction"]
    trough = cycle["trough"]
    articles = []
    if rest:
        # The report's central finding, stated as the subtraction it is.
        articles.append(
            f'<article><span>本季</span><b>{rest["rest"]}收入只需 {minus(rest["revenue_rest"][2])}、'
            f'调整后 EPS 只需 {minus(rest["eps_rest"][2])}</b>'
            f'<p>全年指引减去{rest["ytd"]}实际：{rest["ytd"]}收入 {minus(rest["revenue_ytd"])}、'
            f'调整后 EPS {minus(rest["eps_ytd"])}，指引中值隐含的{rest["rest"]}是 '
            f'{minus(rest["revenue_rest"][2])}、{minus(rest["eps_rest"][2])}。'
            + (story.get("rest_of_year_brief", "") if story else "")
            + '</p></article>')
    articles += [
        '<article><span>记录</span><b>不失手的是公司自己定义的那条</b>'
        f'<p>{finished_years} 个已完结财年，调整后 EPS 相对末次指引 '
        f'{adj_above} 年超出上限、{adj_inside} 年落在区间内、{adj_below} 年跌破；'
        f'GAAP EPS 在有 GAAP 指引的 {gaap_finished} 年里跌破 {gaap_below} 次。差额全在并购摊销与处置损益上。</p></article>'
        if not adj_below and gaap_below else
        '<article><span>记录</span><b>两条 EPS 指引的兑现记录</b>'
        f'<p>{finished_years} 个已完结财年，调整后 EPS 相对末次指引 '
        f'{adj_above} 年超出上限、{adj_inside} 年落在区间内、{adj_below} 年跌破；'
        f'GAAP EPS 在有 GAAP 指引的 {gaap_finished} 年里跌破 {gaap_below} 次。</p></article>',
    ]
    if story and story.get("brief_rebase"):
        articles.append(fill_story(story["brief_rebase"], values))
    articles.append(
        '<article><span>周期</span><b>'
        + ("Ratings 的交易腿又回到高点" if cycle["at_high"] else "Ratings 的交易腿")
        + '</b>'
        f'<p>交易性收入 US${transaction[-1]:,.0f}M'
        + (" 创记录内新高" if cycle["at_high"] else "")
        + f'，而它在 {year_quarter(split["quarters"][trough])} 只有 US${transaction[trough]:,.0f}M'
        + ('；非交易性那条年金腿同期从未塌陷。' if cycle["held_up"] else '。')
        + '</p></article>'
    )
    report = periodic_report_words(staging)
    identity = segment_identity(staging)
    mix = staging["segments_usd_m"]
    rebased = record["basis_break_at"]
    worst_margin = max(
        ((op / rev * 100, key, label) for key, series in mix["operating_profit"].items()
         for label, op, rev in zip(mix["quarters"], series, mix["revenue"][key])
         if op is not None and rev), default=None)
    segment_names = {"market_intelligence": "Market Intelligence", "ratings": "Ratings",
                     "energy": "Energy", "indices": "Indices", "mobility": "Mobility",
                     "engineering_solutions": "Engineering Solutions"}
    capital_years, _ = q1_low_years(capital["quarters"], capital["operating_cash_flow"])
    unrestated_start = year_quarter(staging["long_history"]["quarters"][0])

    notes = [
        "长序列左端有一道<b>养老金列报口径</b>断点："
        f"{staging['long_history']['pension_unrestated_year']} 四季为原始申报口径，"
        f"{staging['long_history']['pension_unrestated_year'] + 1} 起为公司按 ASU 2017-07 重述后的口径，"
        f"逐季差 {staging['long_history']['pension_restatement_per_quarter_usd_m']:.1f}"
        f"（营业利润低 {staging['long_history']['pension_restatement_per_quarter_usd_m']:.1f}、"
        f"总费用高 {staging['long_history']['pension_restatement_per_quarter_usd_m']:.1f}）。"
        "收入不受该重述影响，两段可直接相接；营业利润与利润率两段之间的落差属于列报差异，不是经营变化，图上已标出断点。",
        "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
        "S&P Global 采用自然年财年，本页所有季度标注即该季度本身，无需财年映射。",
        "<b>公司从不在申报文件里发布季度指引，因此本页没有逐季的指引兑现记录。</b>"
        "这是取数限制而不是编辑取舍 —— 它在每季业绩 8-K 的 EX-99.1 里给的是<b>全年</b>展望，"
        "并在其后每个季度修订一次。本页因此建的是同构的记录："
        "把每个财年的历次 vintage（年初首次 → Q1 → Q2 → Q3 修订）排成一条连续的区间带，"
        "把该财年最终报出来的实际值落在<b>末次</b>那一格上。"
        "微软、Alphabet、Mastercard、Visa 与盈透证券五页出于各自的理由也没有季度记录。",
        f"<b>这份记录的时效性必须先读。</b>四档 vintage 分别发布在该财年的 {vintage_months(record)}，"
        "末次那一档发布时该财年已经过去约四分之三，公司手里已有三个季度的实际数。"
        "因此「末次指引从没被跌破」这句话的分量远小于字面，"
        "真正带信息的是开局那一档 —— 本页专门画了一张按 vintage 位次看偏离收敛的图。",
        f"记录是两面的，而这正是把两个指标画在一起才看得见的事："
        f"{finished_years} 个已完结财年里，调整后摊薄 EPS {adj_above} 年高于末次区间上限、"
        f"{adj_inside} 年落在区间内、"
        + ("<b>一年都没有跌破过</b>；" if not adj_below else f"<b>{adj_below} 年跌破</b>；")
        + f"同一张展望表上的 GAAP 摊薄 EPS 在有指引的 {gaap_finished} 年里"
        f"<b>跌破了 {gaap_below} 次</b>（FY2016 公司明说无法把调整后指引对到 GAAP，故那一年没有 GAAP 区间）。"
        "两者之差全部落在调整线以下 —— 并购无形资产摊销、处置损益与减值，"
        "也就是公司自己选择剔除的那些项。不发布任何关于这个差异是否合理的判断。",
    ]
    if rebased is not None:
        year = record["fiscal_years"][rebased]
        when = ("在本季" if record["filed"][rebased] == latest["release_date"]
                else f"在 {record['filed'][rebased]} 那份新闻稿里")
        actuals = staging["annual_actuals"]
        base = actuals["adjusted_eps"][actuals["fiscal_years"].index(year - 1)]
        notes.append(
            f"<b>FY{year} 的指引{when}换了口径，本页保留落差并标注，不做平滑。</b>"
            "公司于 2026-07-01 完成 Mobility 分拆（Mobility Global，NYSE: MBGL，1 股换 1 股）。"
            f"{record['filed'][rebased]} 那份新闻稿把 FY{year} 调整后 EPS 指引从 "
            f"US${record['guide_adjusted_eps_lo'][rebased - 1]:.2f}–{record['guide_adjusted_eps_hi'][rebased - 1]:.2f} "
            f"挪到 US${record['guide_adjusted_eps_lo'][rebased]:.2f}–{record['guide_adjusted_eps_hi'][rebased]:.2f}，"
            "并写明「Current adjusted financial guidance is not directly comparable to prior guidance」。"
            f"公司同时在 {record['proforma_base_filed']} 单独发布了重述后的 FY{year - 1} 基数，"
            f"两者相差 US${base - record['proforma_base_adjusted_eps_usd']:.2f}/股。"
            f"<b>本页不发布任何自算的 FY{year} 口径桥</b>："
            f"那 US${base - record['proforma_base_adjusted_eps_usd']:.2f} 是公司对 FY{year - 1} 给出的加回额，"
            f"不是对 FY{year} 的，"
            f"把它当成 FY{year} 的差额去搭桥是发布方的发明，不是公司的披露。")
    if story and story.get("consolidated_note"):
        notes.append(fill_story(story["consolidated_note"], values))
    notes += [
        "长序列在 2022Q1 打了结构断点：IHS Markit 于 2022-02-28 完成合并，"
        "所以 2022 年只装进约十个月的被并购方收入而 2021 年一个月都没有。"
        f"申报口径全年收入{merger_jump(staging)}，"
        "而 10-K 自己给的备考口径（假设合并发生在 2021 年初）是从 US$12,382M 降到 US$11,842M，"
        "即 −4.4%。同一年两个方向相反的符号，因此这条线不画成连续的增长曲线。",
        f"营业利润率的长序列从 {unrestated_start} 画起，但 "
        f"{staging['long_history']['pension_unrestated_year']} 年四季与其后不是同一口径："
        "公司按 ASU 2017-07 重述了 FY2016 的全年营业利润，却从未重述 2016 年的各个季度，"
        "那四个季度在任何申报文件里都只有旧口径的版本。本页把它们画出来并在图上标断点，"
        "而不是截掉：重述的幅度是量得出来的，2018 年第一季度 10-Q 对 2017 年前三季逐季精确为 "
        f"{staging['long_history']['pension_restatement_per_quarter_usd_m']:.1f}。"
        "收入、净利润、每股收益与现金流各行本身从 2016Q1 起就是干净的，不受该重述影响。",
        "<b>营业利润率一律同时给出剔除处置收益的口径。</b>"
        "公司的损益表结构是「收入 − 费用 + 处置损益 + 联营收益 = 营业利润」，"
        "处置损益是一张申报的行而不是估计值，"
        f"但它足以把 {spike['label']} 的营业利润率顶到 {spike['reported']:.1f}%"
        f"（当季处置收益 US${spike['gain']:,.0f}M，剔除后 {spike['ex_credits']:.1f}%）。"
        "本页把两条线并排画出来，而不是挑一条画、在脚注里说明另一条。",
        "分部口径统一用<b>含分部间收入</b>的申报列，也就是业绩 8-K Exhibit 4 各期一致的那一列。"
        "自 2025 年第一季度起（ASU 2023-07），10-Q 的分部附注同时印出「对外部客户」与「分部间」两列，"
        f"两种口径本季相差 US${-mix['intersegment_elimination'][-1]:,.0f}M；混用会在 2025 年初制造一个并不存在的台阶。"
        + identity_words(identity, mix) + "。",
        "分部名两次变更，只有一次是真的重切。Platts 在 2022Q1 更名为 Commodity Insights，"
        "同时 Market Intelligence 的 Commodities 业务转入该分部，公司重述了 2021 各季（约每季 US$15M）；"
        "Commodity Insights 在 FY2025 10-K（2026-02-11 申报）里改称 Energy，"
        "这一次是<b>纯改名</b>，同一年的数字在两个名字下逐一相等 —— "
        "而申报文件里没有任何一句「原名」的说明，只能靠比对两份申报看出来。本页统一用最新名 Energy。",
        "Engineering Solutions 不单独画线：它只在 2022Q1 至 2023Q2 出现，"
        "两端都是不满一个完整季度的残段（2022-02-28 并入、2023-05-02 出售），"
        "而且从未被列作终止经营，所以它是留在合并数里的一截存量，"
        "画成一条线会把两次交割日读成经营变化。FY2023 的合并收入里含它 US$133M。",
        "自由现金流在本页是自算口径（D）：经营现金流减资本开支。"
        f"公司自己的定义还要再减去付给非控股股东的分派{nci_distribution_words(staging)}，"
        "而全年指引里用的是第三个口径「调整后自由现金流」，还会加回并购费用、遣散与处置税负等项。"
        "本页口径与调整后口径的指引区间在核对表里列出，公司自己的口径没有进表；本页不把它们混为一谈。",
        "现金流量表在 10-Q 里只有年初至今栏，因此除第一季外每季均为相邻两次申报值之差；"
        f"四个季度相加与申报全年逐年相等，{cn_count(len(capital_years))}个财年、"
        f"{cn_count(len(CASH_FLOW_LINES))}条现金流线全部残差为零。"
        "分部数与地区数的第四季度同样是全年减九个月（公司从不单独申报第四季分部列）。",
        "核对抽屉最后那张「AI capex 循环」是全站<b>共用</b>的跨页对照块，"
        "在每一页都逐字节相同，不是对 S&P Global 的判断。"
        "它追的是四家云厂的现金资本开支 → NVDA 数据中心 → TSM 晶圆这条链，"
        "S&P Global 不在这条链的任何一环上：它既不是其中的支出方，也不是供应方。"
        "把它放在这里是为了让读者在任意一页都能查到同一份上下游对照，"
        "而不是暗示评级与指数生意与这条链有关联。它在折叠的抽屉里，不参与本页的论证。",
        "本页只发布公司披露值与可复算的简单派生值（D 标记代表 Derived / 自算），"
        "不发布市场预期、卖方机构名、评级、目标价或估值。",
        "第一节的上季遗留问题与上季阈值、第三节的下季阈值，取自本站所有者的本地季报分析稿"
        "（本季那份的第 0 节，上季与本季两份的第 8 节）：问题与阈值的数值、方向照原文，是研究设定，不是公司指引，"
        "原文里的触发动作不发布；结算它们的读数一律取自申报文件，只在电话会上出现的数按公司口径转述、注明出处。",
        "本页已知未接入：<b>季度指引兑现记录</b>（公司只给全年指引，见上）；"
        # Until the series is rebuilt on the recast basis -- the roll that
        # drops Mobility from the segment arrays is the one that makes this false.
        + ("<b>Mobility 剥离后的重述历史</b>（2026-07-06 的 8-K/A 只给了 2025 年各季与 2026 年一季度"
           "不含 Mobility 的 pro forma 数，10-Q / 10-K 的历史报表还没有按终止经营重述）；"
           if mix["revenue"].get("mobility") and mix["revenue"]["mobility"][-1] is not None else "")
        + "<b>分部营业利润率的长序列</b>（分部营业利润含处置损益，"
        + (f"{segment_names[worst_margin[1]]} 在 {year_quarter(worst_margin[2])} 因此出现 "
           f"{worst_margin[0]:.0f}% 的分部利润率）；" if worst_margin and worst_margin[0] > 100 else "）；")
        + "<b>按地区拆分的发行量金额</b>（公司只按评级类别给金额；2024 年之前那张按地区的表"
        "是口径不同的「市场发行量」，且只给同比百分比）；"
        "<b>交易所衍生品成交量与共同基金 AUM</b>（只在投资者关系网站按月披露，未进入申报文件）；"
        "<b>季度平均 ETF 资产规模</b>（10-K 给的是全年平均，第四季度是空档，本页不推算）；"
        "以及任何来自业绩电话会而无法与第二个来源核对的前瞻数字。",
        "业绩电话会文字稿仅链接官方 IR 与 SEC 托管版本，公开仓不复制原件或逐字内容。",
    ]

    return {
        "schema_version": "quarterly-dashboard/spgi-v1",
        "page": {"slug": "spgi", "language": "zh-CN"},
        "company": {
            "ticker": "SPGI",
            "name": "S&P Global",
            "group": "financial_data_indices",
            "accounting_standard": "US GAAP",
        },
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · SPGI",
        "title": f"S&P Global (SPGI)：{display_period(period)} 季报仪表盘",
        "subtitle": (
            f"截至 {latest['period_end']} · 发布 {latest['release_date']} · US GAAP · {audit_words} · "
            "自然年财年，季度标注与本站其余各页一致"
        ),
        "headline": plain_text(
            f"公司不给季度指引，只给全年指引并逐季修订；本页把 FY{first_fy}–FY{last_fy} 的 "
            f"{len(record['vintages'])} 档 vintage 排成一条修订路径。"
            f"记录是两面的：{finished_years} 个已完结财年里，调整后摊薄 EPS "
            + ("一次都没有跌破过自己的末次指引下限，" if not adj_below else
               f"跌破过自己的末次指引下限 {adj_below} 次，")
            + f"同一张展望表上的 GAAP 摊薄 EPS 却跌破了 {gaap_below} 次。"
            + (fill_story(story["headline_rebase"], values) if story and story.get("headline_rebase") else "")
        ),
        "brief": (
            f'<h4>本季{cn_count(len(articles))}条主线</h4><div class="takeaway-grid">'
            + "".join(articles)
            + '</div>'
        ),
        "source": (
            f'Source: <a href="{release["url"]}" rel="noopener">{release["label"]}</a>{report}。'
        ),
        "source_url": release["url"],
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {
                "id": "settled",
                "title": "一、上季跟踪指标兑现了吗",
                "description": plain_text(
                    settled_words
                    + "S&P Global 从不发布季度指引，它发布的是全年指引并逐季修订，"
                    "所以这里建的是同构而诚实的记录：每个财年的历次修订排成一条路径，"
                    "该年的实际值落在末次那一档上。"
                ),
                "exhibits": settled_ex,
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": plain_text(highlight_words(highlights, rest, margin_chart, story,
                                                          cash_story)),
                "exhibits": highlight_ex,
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": plain_text(next_words),
                "exhibits": next_ex,
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": plain_text(
                    "SPGI 专属的常规序列：Ratings 的周期腿与年金腿、"
                    "被处置收益顶起来的利润率、被并购改写的收入与分部结构、"
                    "六条申报收入类型的迁移、指数资产规模，以及回购与自由现金流的关系。"
                ),
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": [plain_text(_p) for _p in notes],
        "footer": "SPGI quarterly results · 数据来自 S&P Global 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


# The cash-flow lines the series carries, each summed to its filed full year.
CASH_FLOW_LINES = ("operating_cash_flow", "capex", "buyback", "dividends", "depreciation_amortization",
                   "unearned_revenue")


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "spgi.js"), payload, "spgi")
    shell_dir = ROOT / "spgi"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("SPGI", "spgi"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(
        f"SPGI page: {charts} charts in {len(payload['sections'])} sections "
        f"+ {len(payload['tables'])} audit tables"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
