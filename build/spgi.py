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


def kpi_reading(staging: dict, reads: str) -> float:
    """A threshold's current value, read from the series it names.

    The block used to carry the value typed and rounded -- 7.62, 43.44, 49.15 --
    and the headroom was then computed from the rounded figure, which moved two
    bars by a tenth and printed a 49.1% beside a chart that says 49.2%.
    """
    if reads.startswith("yoy:"):
        block, key = reads[4:].split(".")
        values = staging[block][key]
        return pct_change(values[-1], values[-5])
    split = staging["ratings_revenue_split_usd_m"]
    capital = staging["capital_allocation_usd_m"]
    types = staging["revenue_by_type_usd_m"]
    if reads == "margin_ex_credits":
        return operating_margin_ex_credits(staging["long_history"])[-1]
    if reads == "subscription_share":
        return types["subscription"][-1] / gross_revenue_by_type(types)[-1] * 100
    if reads == "free_cash_flow":
        return free_cash_flow(staging)[-1]
    if reads == "transaction_share":
        return split["transaction"][-1] / (split["transaction"][-1] + split["non_transaction"][-1]) * 100
    if reads == "payout_to_fcf":
        return (capital["buyback"][-1] + capital["dividends"][-1]) / free_cash_flow(staging)[-1] * 100
    if reads == "guidance_adjusted_eps_mid":
        record = staging["annual_guidance_history"]
        return (record["guide_adjusted_eps_lo"][-1] + record["guide_adjusted_eps_hi"][-1]) / 2
    block, key = reads.split(".")
    return staging[block][key][-1]


def with_current(staging: dict, block: dict | None, key: str) -> list[dict]:
    """The block's thresholds with their current value read from the series."""
    if not block:
        return []
    return [{**entry, key: kpi_reading(staging, entry["reads"])} for entry in block["quantified"]]


def short_name(metric: str) -> str:
    """「单季自由现金流 D」 → 「单季自由现金流」, 「营业利润率（…）」 → 「营业利润率」."""
    return metric.split("（")[0].removesuffix(" D").strip()


def quoted(names: list[str]) -> str:
    return "".join(f"「{name}」" for name in names)


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
            + ("把它和上面两张 EPS 图并排看："
               "同一家公司，<b>调整后每股收益的指引几乎不失手，现金的指引经常失手</b>。"
               if often and adj_below <= 1 else "")
            + (fcf_story or "")
        ),
    )
    points = [row for row in fcf_rows if row[1] == row[2]]
    fcf_dev = deviation(
        "EX_FCF_DEV", "调整后自由现金流",
        "guide_adjusted_fcf_lo_usd_m", "guide_adjusted_fcf_hi_usd_m",
        "actual_adjusted_fcf_usd_m", mode="pct",
        extra_note=(
            "、".join(f"FY{row[0]}" for row in points)
            + " 那一档的指引是单点值（「approximately "
            + "、".join(f"${row[1] / 1000:g} billion" for row in points)
            + "」）而不是区间，所以它的中值就是那个点本身。"
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
            f"实际结果相对<b>每一档</b>指引中值的偏离：开局那一档 {len(opening)} 年里 "
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


# ── the tracked readings: which chart draws which ────────────────────────────
TRANSACTION_YOY = "yoy:ratings_revenue_split_usd_m.transaction"
NON_TRANSACTION_YOY = "yoy:ratings_revenue_split_usd_m.non_transaction"

# Section one draws these three over time when last quarter's note settled them;
# section three draws every other tracked reading that has a chart below. A
# reading is drawn once on the page: the notes under the two headroom bars say
# where the rest went, and they are worked out from these two tables rather than
# listed by hand -- the hand-written list sent "Ratings non-transaction growth" to
# a section-three chart that never existed.
SECTION_ONE = (TRANSACTION_YOY, "margin_ex_credits", "subscription_share")
CHART_REF = {
    TRANSACTION_YOY: "EX_SET_TRANS",
    "margin_ex_credits": "EX_SET_MARGIN",
    "subscription_share": "EX_SET_SUB",
    "transaction_share": "EX_N_SHARE",
    "free_cash_flow": "EX_N_FCF",
    "payout_to_fcf": "EX_N_PAYOUT",
    "billed_issuance_usd_bn.total": "EX_N_ISSUANCE",
}
GUIDANCE_MID = "guidance_adjusted_eps_mid"
# Tracked readings with no trend chart of their own: what to say, and where the
# thing they read is drawn.
LEVELS_DRAWN_AT = {
    NON_TRANSACTION_YOY: ("本页没有单独的同比图，金额走势见", ("EX_Q_RATINGS", "EX_L_RATINGS")),
    GUIDANCE_MID: ("本页不另画它，指引区间见", ("EX_ADJ_BAND",)),
}


def percent_words(value: float) -> str:
    """``15.0`` → ``'15%'``, ``12.5`` → ``'12.5%'``: a threshold as the note set it."""
    return f"{value:g}%"


def threshold_words(entry: dict) -> str:
    """A threshold in the unit its chart title prints."""
    if entry["unit"] == "usd_m":
        return f"US${entry['threshold']:,.0f}M"
    if entry["unit"] == "usd_bn":
        return f"US${entry['threshold']:,.0f}B"
    return percent_words(entry["threshold"])


def exhibit_words(refs) -> str:
    """``('EX_A', 'EX_B')`` → ``'Exhibit {EX_A} 与 Exhibit {EX_B}'``."""
    names = [f"Exhibit {{{ref}}}" for ref in refs]
    return names[0] if len(names) == 1 else "、".join(names[:-1]) + " 与 " + names[-1]


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


# ── section one: settling the thresholds the previous note set ───────────────
def settlement_bar(entries: list[dict], drawn_first: list[str], drawn_next: list[str],
                   retired: list[str]) -> dict:
    marks = [headroom(entry["direction"], entry["threshold"], entry["actual"]) for entry in entries]
    safe = sum(1 for mark in marks if mark > 0)
    if safe == len(entries):
        verdict = f"<b>本季{cn_count(len(entries))}条全部为正。</b>"
    else:
        verdict = (f"<b>本季{cn_count(len(entries))}条里{cn_count(safe)}条为正、"
                   f"{cn_count(len(entries) - safe)}条已越过阈值。</b>")
    units = {entry["unit"] for entry in entries}
    axis = ("把百分比、美元与十亿美元的发行量放在同一根轴上，" if units == {"pct", "usd_m", "usd_bn"}
            else "把不同单位的指标放在同一根轴上，")
    elsewhere = [entry for entry in entries if entry["reads"] not in drawn_first]
    forward = [entry for entry in elsewhere if entry["reads"] in drawn_next]
    levels = [entry for entry in elsewhere
              if entry["reads"] not in drawn_next and entry["reads"] in LEVELS_DRAWN_AT]
    nowhere = [entry for entry in elsewhere if entry not in forward and entry not in levels]
    where = ""
    if forward:
        where += (f"其中{quoted([short_name(e['metric']) for e in forward])}"
                  f"{cn_count(len(forward))}条不在本节重复画自己的走势图 —— "
                  f"{'它们' if len(forward) > 1 else '它'}的历史图在第三节向前指"
                  f"（{exhibit_words(CHART_REF[e['reads']] for e in forward)}），"
                  "同一条线画两遍只会占位置。")
    for entry in levels:
        words, refs = LEVELS_DRAWN_AT[entry["reads"]]
        where += f"{quoted([short_name(entry['metric'])])}{words} {exhibit_words(refs)}。"
    if nowhere:
        where += f"{quoted([short_name(e['metric']) for e in nowhere])}本页不画走势，只在上图结算。"
    unsettled = ""
    if retired:
        unsettled = (f"另有{'一' if len(retired) == 1 else cn_count(len(retired))}条<b>无法结算</b>而不是被跌破："
                     + "".join(plain_text(text) for text in retired))
    bar = headroom_exhibit(
        "上季设定的阈值，本季逐条结算：距阈值余量",
        entries, "actual",
        note=(
            "正值＝仍在安全侧，负值＝已越过阈值。"
            + axis
            + "靠的是统一换算成「距阈值的百分比余量」，原单位见核对表。"
            + verdict + where + unsettled
        ),
        src_extra="阈值为上一份笔记的研究设定，不是公司指引；实际值为本季申报值与自算值。",
    )
    bar["ref"] = "EX_SETTLE_BAR"
    return bar


def transaction_growth_chart(staging: dict, entry: dict, entries: list[dict]) -> dict:
    split = staging["ratings_revenue_split_usd_m"]
    window = 13
    labels = [compact_period(q) for q in split["quarters"][-window:]]
    transaction = split["transaction"]
    yoy = [pct_change(transaction[i], transaction[i - 4])
           for i in range(len(transaction) - window, len(transaction))]
    threshold = percent_words(entry["threshold"])
    chart = threshold_exhibit(
        f"Ratings 交易性收入同比 vs 阈值 {threshold}",
        labels, rounded(yoy), entry["threshold"],
        fmt="pct1", ylab="同比增速",
        actual_name="Ratings 交易性收入同比", threshold_name=f"阈值 {threshold}",
        note=(
            "交易性收入按公开发债与银团贷款的<b>每笔评级</b>收费，是这家公司里"
            "唯一一条真正随发行窗口开合而摆动的线。"
            f"本季 {yoy[-1]:+.1f}%，是窗口内第 "
            f"{sorted(yoy, reverse=True).index(yoy[-1]) + 1} 高。"
            "它与非交易性那条年金线的对比见 Exhibit {EX_Q_RATINGS}。"
        ),
        src_extra="各季 10-Q / 10-K 收入附注与业绩 8-K EX-99.1 的 Revenue by Type 表。",
    )
    chart["ref"] = CHART_REF[TRANSACTION_YOY]
    return chart


def margin_threshold_chart(staging: dict, entry: dict, entries: list[dict]) -> dict:
    long_history = staging["long_history"]
    quarters = long_history["quarters"]
    window = 13
    ex_credits = operating_margin_ex_credits(long_history)
    spike = disposition_spike(long_history)
    threshold = percent_words(entry["threshold"])
    q4_blank = all(gain is None for label, gain in
                   zip(quarters, long_history["gain_on_dispositions_usd_m"]) if label.startswith("Q4"))
    chart = threshold_exhibit(
        f"营业利润率（剔除处置损益与联营收益 D）vs 阈值 {threshold}",
        [compact_period(q) for q in quarters[-window:]],
        rounded(ex_credits[-window:]), entry["threshold"],
        fmt="pct1", ylab="营业利润率",
        actual_name="（收入 − 费用）/ 收入 D", threshold_name=f"阈值 {threshold}",
        note=(
            "<b>分子是两条申报行相减：收入减总费用。</b>"
            "公司的损益表结构是「收入 − 费用 + 处置损益 + 联营收益 = 营业利润」，"
            "所以这个差额恰好是加上那两项<b>之前</b>的经营利润，不含任何估计。"
            "不剔除的话这条线会被几次剥离顶出一个与经营无关的尖峰 —— "
            f"最极端的一次是 {spike['label']} 的 {spike['reported']:.1f}%，"
            f"那一季装着 US${spike['gain']:,.0f}M 的处置收益，"
            f"剔除后只有 {spike['ex_credits']:.1f}%。整段对照见 Exhibit {{EX_L_MARGIN}}。"
            + ("<b>之所以用「收入 − 费用」而不是「营业利润 − 处置收益」</b>："
               "公司在每个会计第四季度都不单独申报处置收益这一行，"
               "用后者会在每年第四季度留下一个洞，而前者两条腿每季都有。" if q4_blank else "")
        ),
        src_extra="各季 10-Q / 10-K 合并损益表的收入行与总费用行。",
    )
    chart["ref"] = CHART_REF["margin_ex_credits"]
    return chart


def subscription_share(types: dict) -> list[float]:
    gross = gross_revenue_by_type(types)
    return [types["subscription"][i] / gross[i] * 100 for i in range(len(gross))]


def subscription_chart(staging: dict, entry: dict, entries: list[dict]) -> dict:
    types = staging["revenue_by_type_usd_m"]
    share = subscription_share(types)
    threshold = percent_words(entry["threshold"])
    chart = threshold_exhibit(
        f"订阅型收入占毛收入比重 vs 阈值 {threshold}",
        [compact_period(q) for q in types["quarters"]],
        rounded(share), entry["threshold"],
        fmt="pct1", ylab="占毛收入比",
        actual_name="Subscription 占毛收入比", threshold_name=f"阈值 {threshold}",
        note=(
            "公司把收入拆成六种申报类型，订阅是其中最大的一条，也是最不随发行周期摆动的一条。"
            f"这条线从 {share[0]:.1f}% 走到 {share[-1]:.1f}%，"
            + ("但它上升不全是订阅变强 —— 2022 年 IHS Markit 并表带进来的大多是订阅型收入。"
               if share[-1] > share[0] else "")
            + "六条线各自的走向见 Exhibit {EX_L_TYPE}。"
        ),
        src_extra="各季 10-Q / 10-K 收入分解附注的六条收入类型行。",
    )
    chart["ref"] = CHART_REF["subscription_share"]
    return chart


# ── section three's own charts ───────────────────────────────────────────────
def share_chart(staging: dict, entry: dict, entries: list[dict]) -> dict:
    split = staging["ratings_revenue_split_usd_m"]
    window = 21
    share = [t / (t + n) * 100 for t, n in zip(split["transaction"], split["non_transaction"])]
    threshold = percent_words(entry["threshold"])
    safe_side = {"down": "越低越安全", "up": "越高越安全"}[entry["direction"]]
    same = [e for e in entries if e["direction"] == entry["direction"] and e is not entry]
    against = ("与本节其他几条相反" if not same else
               f"与{quoted([short_name(e['metric']) for e in same])}相同、与其余几条相反")
    inside = share[-1] < entry["threshold"] if entry["direction"] == "down" else share[-1] > entry["threshold"]
    chart = threshold_exhibit(
        f"交易性收入占 Ratings 比重 vs 阈值 {threshold}",
        [compact_period(q) for q in split["quarters"][-window:]],
        rounded(share[-window:]), entry["threshold"],
        fmt="pct1", ylab="占 Ratings 收入比",
        actual_name="交易性占比", threshold_name=f"阈值 {threshold}（越高越依赖发行窗口）",
        note=(
            f"<b>这条阈值的方向是「{safe_side}」</b>，{against}："
            "占比越高，说明这家公司的收入越依赖一个它不控制的变量 —— 债券发行窗口。"
            f"本季 {share[-1]:.1f}%，"
            + (f"离 {threshold} 还有余量；" if inside else f"已越过 {threshold}；")
            + f"这个比率在本记录里最高到过 {max(share):.1f}%，最低到过 {min(share):.1f}%。"
        ),
        src_extra="各季 10-Q / 10-K 收入附注的交易性 / 非交易性两行。",
    )
    chart["ref"] = CHART_REF["transaction_share"]
    return chart


def fcf_threshold_chart(staging: dict, entry: dict, entries: list[dict]) -> dict:
    capital = staging["capital_allocation_usd_m"]
    window = 17
    fcf = free_cash_flow(staging)
    full, low = q1_low_years(capital["quarters"], fcf)
    if len(low) == len(full):
        season = "每年第一季度都是四季里最低的一档"
    else:
        season = (f"{cn_count(len(full))}个完整年份里有{cn_count(len(low))}年第一季度是四季里最低的一档"
                  f"（例外是 {'、'.join(str(y) for y in full if y not in low)} 年）")
    threshold = threshold_words(entry)
    chart = threshold_exhibit(
        f"单季自由现金流 D vs 阈值 {threshold}",
        [compact_period(q) for q in capital["quarters"][-window:]],
        rounded(fcf[-window:]), entry["threshold"],
        fmt="f0c", ylab="US$M",
        actual_name="自由现金流 D", threshold_name=f"阈值 {threshold}",
        note=(
            f"季节性明显：{season}，"
            "所以这条阈值只在非第一季度有判别力，第一季度的穿越不作为信号。"
            "口径是经营现金流减资本开支，两端都是申报值。"
        ),
        src_extra="各季 10-Q / 10-K 合并现金流量表。",
    )
    chart["ref"] = CHART_REF["free_cash_flow"]
    return chart


def payout_chart(staging: dict, entry: dict, entries: list[dict]) -> dict:
    story = stamped_block(staging, "quarter_story", staging["periods"][-1])
    record = staging["annual_guidance_history"]
    target = (fill_story(story["payout_target"], {"release": record["filed"][-1],
                                                  "prior_release": record["filed"][-2]})
              if story and story.get("payout_target") else "公司自己的回报目标按年给出，")
    capital = staging["capital_allocation_usd_m"]
    window = 17
    fcf = free_cash_flow(staging)
    payout = [(b + d) / f * 100 for b, d, f in zip(capital["buyback"], capital["dividends"], fcf)]
    threshold = percent_words(entry["threshold"])
    chart = threshold_exhibit(
        f"单季股东回报 / 自由现金流 D vs 阈值 {threshold}",
        [compact_period(q) for q in capital["quarters"][-window:]],
        rounded(payout[-window:]), entry["threshold"],
        fmt="pct1", ylab="回报 / 自由现金流",
        actual_name="（回购 + 分红）/ 自由现金流 D", threshold_name=f"阈值 {threshold}",
        note=(
            "单季穿越并不稀奇 —— 回购按授权与 ASR 的节奏走，现金流按季节走。"
            "值得看的是连续几季都在上面的窗口。"
            + target
            + "口径与本图的自算分母不同，本页不把两者混为一谈。"
        ),
        src_extra="各季 10-Q / 10-K 合并现金流量表。",
    )
    chart["ref"] = CHART_REF["payout_to_fcf"]
    return chart


def issuance_threshold_chart(staging: dict, entry: dict, entries: list[dict]) -> dict:
    issuance = staging["billed_issuance_usd_bn"]
    threshold = threshold_words(entry)
    chart = threshold_exhibit(
        f"计费发行量 vs 阈值 {threshold}",
        [compact_period(q) for q in issuance["quarters"]],
        rounded(issuance["total"]), entry["threshold"],
        fmt="f0c", ylab="US$B",
        actual_name="计费发行量", threshold_name=f"阈值 {threshold}",
        note=(
            "这是公司自己按季披露的 Ratings 前瞻量指标，"
            f"但窗口只有 {len(issuance['quarters'])} 季"
            + ("且不含一次下行周期" if not issuance_downturn(issuance["total"]) else "")
            + "，理由见 Exhibit {EX_Q_ISSUANCE}。"
            "把它放在这里是因为它是唯一一条<b>先于收入</b>动的申报量指标。"
        ),
        src_extra="各季 10-Q / 10-K 的 MD&A「Billed Issuance Volumes」表。",
    )
    chart["ref"] = CHART_REF["billed_issuance_usd_bn.total"]
    return chart


CHART_BUILDERS = {
    TRANSACTION_YOY: transaction_growth_chart,
    "margin_ex_credits": margin_threshold_chart,
    "subscription_share": subscription_chart,
    "transaction_share": share_chart,
    "free_cash_flow": fcf_threshold_chart,
    "payout_to_fcf": payout_chart,
    "billed_issuance_usd_bn.total": issuance_threshold_chart,
}


def next_bar(entries: list[dict], drawn_first: list[str], drawn_next: list[str],
             period_end: str) -> dict:
    here = [entry for entry in entries if entry["reads"] in drawn_next]
    before = [entry for entry in entries if entry["reads"] in drawn_first]
    other = [entry for entry in entries if entry not in here and entry not in before]
    note = ("同一套归一化口径：正值＝当前值仍在安全侧。"
            "阈值是本站的研究设定，不是公司指引，也不是评级。"
            f"把{cn_count(len(entries))}条不同单位的线放在一根轴上是为了先看「哪条最接近临界」。"
            f"下面画出其中{cn_count(len(here))}条的走势")
    if before:
        note += (f"；另外{cn_count(len(before))}条 —— "
                 f"{quoted([short_name(e['metric']) for e in before])}—— 的历史图在第一节，"
                 "本站每条跟踪指标只画一遍，不在两节之间重复。")
    else:
        note += "。"
    for entry in other:
        if entry["reads"] in LEVELS_DRAWN_AT:
            words, refs = LEVELS_DRAWN_AT[entry["reads"]]
            note += f"{quoted([short_name(entry['metric'])])}{words} {exhibit_words(refs)}。"
        else:
            note += f"{quoted([short_name(entry['metric'])])}本页不画走势。"
    bar = headroom_exhibit(
        "下季阈值与当前值：距阈值余量",
        entries, "current",
        note=note,
        src_extra=f"阈值为研究设定；当前值为截至 {period_end} 的申报值与自算值。",
    )
    bar["ref"] = "EX_NEXT_BAR"
    return bar


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


def quarter_segments(staging: dict, story: dict | None) -> dict:
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


def nci_distribution_words(staging: dict) -> str:
    """「（FY2025 为 US$321M）」 from the latest year the series carries."""
    actuals = staging["annual_actuals"]
    known = [(year, value) for year, value in
             zip(actuals["fiscal_years"], actuals["nci_distributions_usd_m"]) if value is not None]
    if not known:
        return ""
    year, value = known[-1]
    return f"（FY{year} 为 US${value:,.0f}M）"


def quarter_capital(staging: dict) -> dict:
    capital = staging["capital_allocation_usd_m"]
    window = 13
    labels = [compact_period(q) for q in capital["quarters"][-window:]]
    fcf = free_cash_flow(staging)
    payout = [b + d for b, d in zip(capital["buyback"], capital["dividends"])]
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
            "<b>本页的自由现金流是自算口径（D）</b>：经营现金流减资本开支。"
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


def story_values(staging: dict) -> dict[str, str]:
    """The numbers a story block may name, computed from the series."""
    record = staging["annual_guidance_history"]
    mobility = staging["segments_usd_m"]["revenue"].get("mobility", [None])[-1]
    values = {} if mobility is None else {"mobility": f"{mobility:,.0f}"}
    at = record["basis_break_at"]
    if at is not None:
        prior_mid = (record["guide_adjusted_eps_lo"][at - 1] + record["guide_adjusted_eps_hi"][at - 1]) / 2
        new_mid = (record["guide_adjusted_eps_lo"][at] + record["guide_adjusted_eps_hi"][at]) / 2
        values.update(drop=f"{prior_mid - new_mid:.2f}", prior_mid=f"{prior_mid:.3f}",
                      new_mid=f"{new_mid:.3f}")
    return values


def build_payload(staging: dict) -> dict:
    financials = staging["financials"]
    periods = staging["periods"]
    period = periods[-1]
    period_end = staging["period_ends"][-1]
    latest = latest_block(staging, period=period, period_end=period_end)
    release = release_source(staging)
    settlement = stamped_block(staging, "prior_kpi_settlement", period)
    next_kpi = stamped_block(staging, "next_kpi", period)
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

    settled_entries = with_current(staging, settlement, "actual")
    next_entries = with_current(staging, next_kpi, "current")
    drawn_first = [entry["reads"] for entry in settled_entries if entry["reads"] in SECTION_ONE]
    drawn_next = [entry["reads"] for entry in next_entries
                  if entry["reads"] in CHART_BUILDERS and entry["reads"] not in drawn_first]
    for entry in settled_entries + next_entries:
        if entry["reads"] not in CHART_BUILDERS and entry["reads"] not in LEVELS_DRAWN_AT:
            raise ValueError(f"tracked reading {entry['reads']!r} has no chart on this page: "
                             "map it in CHART_BUILDERS or LEVELS_DRAWN_AT")

    guidance_ex, stats = guidance_charts(
        staging, fcf_story=story.get("fcf_open_year") if story else None)
    settled_ex = []
    if settled_entries:
        settled_ex.append(settlement_bar(settled_entries, drawn_first, drawn_next,
                                         settlement.get("retired", [])))
        settled_ex += [CHART_BUILDERS[entry["reads"]](staging, entry, settled_entries)
                       for entry in settled_entries if entry["reads"] in drawn_first]
    settled_ex += guidance_ex
    margin_chart = quarter_margin_bases(staging, figures, story)
    highlight_ex = [
        quarter_segments(staging, story),
        quarter_ratings(staging),
        margin_chart,
        quarter_mobility(staging),
        quarter_issuance(staging),
        quarter_capital(staging),
    ]
    highlight_ex = [exhibit for exhibit in highlight_ex if exhibit]
    next_ex = []
    if next_entries:
        next_ex.append(next_bar(next_entries, drawn_first, drawn_next, period_end))
        next_ex += [CHART_BUILDERS[entry["reads"]](staging, entry, next_entries)
                    for entry in next_entries if entry["reads"] in drawn_next]
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
    if settled_entries:
        tables.append(threshold_table(0, "上季阈值与本季实际（原单位）",
                                      settled_entries, "actual", "本季实际"))
    if next_entries:
        tables.append(threshold_table(0, "下季阈值与当前值（原单位）",
                                      next_entries, "current", "当前值"))
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
    articles = [
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
        "本页只发布公司披露值、可复算的简单派生值，以及明确标注的市场预期；D 标记代表 Derived / 自算。",
        "市场预期一律标注为「市场预期」并给出取数时点，不写卖方机构名，也不发布评级、目标价或估值。",
        "本页已知未接入：<b>季度指引兑现记录</b>（公司只给全年指引，见上）；"
        # Until the series is rebuilt on the recast basis -- the roll that
        # drops Mobility from the segment arrays is the one that makes this false.
        + ("<b>Mobility 剥离后的重述历史</b>（尚无任何一份已申报报表是重述后的）；"
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
                "title": "一、上季兑现了吗",
                "description": plain_text(
                    ("先结清上一份笔记留下的阈值，再看新数字。"
                     "这一节的后半段是本页与本站其他几页最不一样的地方："
                     if settled_entries else
                     "上一份笔记没有留下可结算的阈值，这一节只有全年指引的记录，"
                     "也是本页与本站其他几页最不一样的地方：")
                    + "S&P Global 从不发布季度指引，它发布的是全年指引并逐季修订，"
                    "所以这里建的是同构而诚实的记录 —— 每个财年的历次修订排成一条路径，"
                    "该年的实际值落在末次那一档上。"
                ),
                "exhibits": settled_ex,
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": plain_text(
                    "分部收入的分化、Ratings 那条随发行窗口摆动的腿、"
                    f"同一个季度被印成{cn_count(len(margin_chart['values']))}个数的营业利润率"
                    + (f"，{story['section2_tail']}" if story and story.get("section2_tail") else "")
                    + "。"
                ),
                "exhibits": highlight_ex,
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": plain_text(
                    "当前值离下季阈值还有多远，统一用「距阈值余量」口径；"
                    "无法从申报文件复算的几条写在不接入清单里，不给近似值。"
                ),
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
CASH_FLOW_LINES = ("operating_cash_flow", "capex", "buyback", "dividends", "depreciation_amortization")


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
