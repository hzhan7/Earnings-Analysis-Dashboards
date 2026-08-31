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
that actually settles it.  Thirty-one vintages across FY2019-FY2026 come out of
the releases themselves.

That record answers a question the quarterly pages cannot ask, and the answer is
two-sided in a way that only shows up because the metrics sit in the same table:

* **adjusted diluted EPS has never landed below its own final range** -- 5 of 7
  finished years above the top, 2 inside, none below;
* **GAAP diluted EPS landed below in 3 of the same 7 years.**

Same release, same table, same twelve-month horizon.  The number that never
misses is the one the company defines itself.

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
    delivery_band,
    headroom,
    headroom_exhibit,
    midpoint_deviation,
    number_exhibits,
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

TIMING_WARNING = (
    "<b>先读这一句，再读柱子。</b>这不是一份事前预测的记录。"
    "每个财年的四档指引分别发布在该年的 2 月、4-5 月、7-8 月与 10-11 月 —— "
    "也就是说，「初次」那一档发布时全年还剩十一个月，而「Q3 修订」那一档发布时"
    "全年已经过去约四分之三，公司手里已经有三个季度的实际数。"
    "越靠右的那一档越不是预测、越接近一次预告，"
    "所以「末次指引从没被跌破」这句话的分量远小于它的字面。"
    "真正带信息的是最左边那一档，见 Exhibit {EX_CONVERGE}。"
)

MOBILITY_BREAK = (
    "<b>最右边那一档是口径重设，不是下调。</b>"
    "公司于 2026-07-01 完成 Mobility 分拆（Mobility Global，NYSE: MBGL），"
    "并在 2026-07-28 的业绩新闻稿里把 FY2026 全年指引整体挪到不含 Mobility 的口径上，"
    "同一份新闻稿写明「Current adjusted financial guidance is not directly comparable "
    "to prior guidance」。本页保留这根落差很大的柱子并在此说明，而不是把它悄悄改掉。"
)


# ── section one: the full-year guidance record ───────────────────────────────
def guidance_charts(staging: dict) -> tuple[list[dict], dict]:
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

    adjusted_band = band(
        "EX_ADJ_BAND", "调整后摊薄 EPS",
        "guide_adjusted_eps_lo", "guide_adjusted_eps_hi", "actual_adjusted_eps",
        fmt="usd2", ylab="US$/股", unit="US$",
        extra_note=(
            f"<b>每个财年占据连续的几格</b>：年初首次指引、Q1、Q2、Q3 修订，"
            f"实际值只落在该年<b>末次</b>那一格上，因为那才是结算这一年的那一档。"
            f"{adj_above + adj_inside + adj_below} 个已完结财年里"
            f"{adj_above} 年高于末次区间上限、{adj_inside} 年落在区间内，"
            f"<b>一年都没有跌破过下限</b>。"
            + TIMING_WARNING
            + MOBILITY_BREAK
        ),
    )
    adjusted_dev = deviation(
        "EX_ADJ_DEV", "调整后摊薄 EPS",
        "guide_adjusted_eps_lo", "guide_adjusted_eps_hi", "actual_adjusted_eps",
        mode="pct",
        extra_note=(
            "柱子全部为正，而且长度在收敛 —— "
            "越晚发布的那一档指引离最终结果越近，这正是它应该有的样子。"
            f"把它和 GAAP 那张（Exhibit {{EX_GAAP_DEV}}）并排看："
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
            "<b>那条从不失手的曲线，是公司自己定义的那一条。</b>"
            "另有几格是空的：FY2021 前三档与 FY2023 首档、FY2026 前两档，"
            "公司当时只给调整后口径、不给 GAAP 口径，原因见「口径与方法说明」。"
        ),
    )
    gaap_dev = deviation(
        "EX_GAAP_DEV", "GAAP 摊薄 EPS",
        "guide_gaap_eps_lo", "guide_gaap_eps_hi", "actual_gaap_eps",
        mode="pct",
        extra_note=(
            "与调整后那张（Exhibit {EX_ADJ_DEV}）不是同一个形状："
            "这里有明显的负柱，而且最深的一根出现在 FY2023 —— "
            "那一年 Engineering Solutions 于 5 月出售并计入处置损失，"
            "而它从未被列作终止经营，所以损失直接落在 GAAP 每股收益里。"
        ),
    )

    # ── the chart the band cannot draw: how early was the year knowable ──────
    converge = convergence_chart(record)

    revenue_band = band(
        "EX_REVG_BAND", "GAAP 收入增速",
        "guide_revenue_growth_lo_pct", "guide_revenue_growth_hi_pct",
        "actual_revenue_growth_pct",
        fmt="pct1", ylab="全年收入同比", unit="%",
        extra_note=(
            "<b>这条指引只有四年，因为再往前公司根本不给数字。</b>"
            "FY2019–FY2022 的展望段落里，收入增速是「mid single-digits」这类文字，"
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
            "样本只有三年，不足以谈规律，放在这里是为了让读者看到"
            "同一张展望表上不同指标的可得年份差得很远。"
        ),
    )

    fcf_band = band(
        "EX_FCF_BAND", "调整后自由现金流",
        "guide_adjusted_fcf_lo_usd_m", "guide_adjusted_fcf_hi_usd_m",
        "actual_adjusted_fcf_usd_m",
        fmt="f0c", ylab="US$M", unit="US$M", use_break=False,
        extra_note=(
            "<b>这是记录里唯一一条经常做不到的指引。</b>"
            "三个已完结财年里两年跌破下限：FY2023 指引 US$4,200–4,300M、实际 US$4,057M；"
            "FY2025 指引 US$5,600–5,800M、实际 US$5,481M。"
            "唯一超额的 FY2024 是一次大幅超额。"
            "把它和上面两张 EPS 图并排看："
            "同一家公司，<b>每股收益的指引几乎不失手，现金的指引经常失手</b>。"
            "另外这条线在 FY2026 直接消失了 —— 2026 年的三档展望里，"
            "初次与 Q1 只写「grow mid-single digits」这类文字，Q2 连这句也没有，"
            "所以本图右端不是空白待填，而是公司停止给这个数字。"
        ),
    )
    fcf_dev = deviation(
        "EX_FCF_DEV", "调整后自由现金流",
        "guide_adjusted_fcf_lo_usd_m", "guide_adjusted_fcf_hi_usd_m",
        "actual_adjusted_fcf_usd_m", mode="pct",
        extra_note=(
            "FY2024 那一档的指引是单点值（「approximately $5.2 billion」）而不是区间，"
            "所以它的中值就是那个点本身。"
        ),
    )

    charts = [adjusted_band, adjusted_dev, gaap_band, gaap_dev, converge,
              revenue_band, revenue_dev, fcf_band, fcf_dev]
    stats = {
        "adjusted": (adj_above, adj_inside, adj_below),
        "gaap": (gaap_above, gaap_inside, gaap_below),
    }
    return charts, stats


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
    for year in years:
        actual = settled[year]
        for slot in slots:
            value = None
            for index, (fy, sl) in enumerate(zip(record["fiscal_years"],
                                                 record["vintage_slots"])):
                if fy == year and sl == slot:
                    low = record["guide_adjusted_eps_lo"][index]
                    high = record["guide_adjusted_eps_hi"][index]
                    if low is not None:
                        value = (actual / ((low + high) / 2) - 1) * 100
                    break
            out[slot].append(value)
    return out


def convergence_chart(record: dict) -> dict:
    """One bar per vintage slot per year: the funnel closing on the answer."""
    dev = vintage_deviations(record)
    opening = [value for value in dev["initial"] if value is not None]
    final = [value for value in dev["q3"] if value is not None]
    beaten = sum(1 for value in opening if value > 0)
    missed = [dev["years"][index] for index, value in enumerate(dev["initial"])
              if value is not None and value < 0]
    open_abs = statistics.fmean(abs(value) for value in opening)
    final_abs = statistics.fmean(abs(value) for value in final)
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
            f"{len(opening)} 年里有 {beaten} 年最终结果高于它，"
            + (f"唯一低于开局指引的是 {missed[0]}，而那一年正是公司自己在年中"
               "<b>撤回</b>全年指引的那一年 —— 2022 年 6 月 1 日，理由写的是"
               "「Extraordinarily Weak Market Conditions for its Ratings Business」，"
               "八月初随第二季度业绩重新发布。那一年 Ratings 的交易性收入"
               "跌到整段记录的最低点，见 Exhibit {EX_L_RATINGS}。"
               if missed else "")
            + "<b>FY22 那一年的开局指引是唯一一档没有进入 8-K 的</b>："
            "它出自 2022-03-01 的投资者日，本页之所以能引用，"
            "是因为公司在 2022-05-03 那份 8-K 里逐字复述了它；图上以 * 标出。"
        ),
        "src_extra": SOURCE_8K + "偏离为自算值，四档指引原值见核对表。",
    }


# ── section one: settling the thresholds the previous note set ───────────────
def settlement_charts(staging: dict) -> list[dict]:
    settlement = staging["prior_kpi_settlement"]
    entries = settlement["quantified"]
    bar = headroom_exhibit(
        "上季设定的阈值，本季逐条结算：距阈值余量",
        entries, "actual",
        note=(
            "正值＝仍在安全侧，负值＝已越过阈值。"
            "把百分比、美元与十亿美元的发行量放在同一根轴上，"
            "靠的是统一换算成「距阈值的百分比余量」，原单位见核对表。"
            "<b>本季六条全部为正。</b>"
            "其中「Ratings 非交易性收入同比」「单季自由现金流」「计费发行量」三条"
            "不在本节重复画自己的走势图 —— 它们各自的历史图在第三节向前指，"
            "同一条线画两遍只会占位置。"
            "另有一条<b>无法结算</b>而不是被跌破：" + plain_text(settlement["retired"][0])
        ),
        src_extra="阈值为上一份笔记的研究设定，不是公司指引；实际值为本季申报值与自算值。",
    )
    bar["ref"] = "EX_SETTLE_BAR"

    split = staging["ratings_revenue_split_usd_m"]
    window = 13
    labels = [compact_period(q) for q in split["quarters"][-window:]]
    transaction = split["transaction"]
    yoy = [pct_change(transaction[i], transaction[i - 4])
           for i in range(len(transaction) - window, len(transaction))]
    trans_chart = threshold_exhibit(
        "Ratings 交易性收入同比 vs 阈值 15%",
        labels, rounded(yoy), 15.0,
        fmt="pct1", ylab="同比增速",
        actual_name="Ratings 交易性收入同比", threshold_name="阈值 15%",
        note=(
            "交易性收入按公开发债与银团贷款的<b>每笔评级</b>收费，是这家公司里"
            "唯一一条真正随发行窗口开合而摆动的线。"
            f"本季 {yoy[-1]:+.1f}%，是窗口内第 "
            f"{sorted(yoy, reverse=True).index(yoy[-1]) + 1} 高。"
            "它与非交易性那条年金线的对比见 Exhibit {EX_Q_RATINGS}。"
        ),
        src_extra="各季 10-Q / 10-K 收入附注与业绩 8-K EX-99.1 的 Revenue by Type 表。",
    )
    trans_chart["ref"] = "EX_SET_TRANS"

    long_history = staging["long_history"]
    quarters = long_history["quarters"]
    margin_window = 13
    ex_credits = operating_margin_ex_credits(long_history)
    margin_chart = threshold_exhibit(
        "营业利润率（剔除处置损益与联营收益 D）vs 阈值 41%",
        [compact_period(q) for q in quarters[-margin_window:]],
        rounded(ex_credits[-margin_window:]), 41.0,
        fmt="pct1", ylab="营业利润率",
        actual_name="（收入 − 费用）/ 收入 D", threshold_name="阈值 41%",
        note=(
            "<b>分子是两条申报行相减：收入减总费用。</b>"
            "公司的损益表结构是「收入 − 费用 + 处置损益 + 联营收益 = 营业利润」，"
            "所以这个差额恰好是加上那两项<b>之前</b>的经营利润，不含任何估计。"
            "不剔除的话这条线会被几次剥离顶出一个与经营无关的尖峰 —— "
            "最极端的一次是 2022Q1 的 79.2%，那一季装着 US$1,344M 的处置收益，"
            "剔除后只有 22.8%。整段对照见 Exhibit {EX_L_MARGIN}。"
            "<b>之所以用「收入 − 费用」而不是「营业利润 − 处置收益」</b>："
            "公司在每个会计第四季度都不单独申报处置收益这一行，"
            "用后者会在每年第四季度留下一个洞，而前者两条腿每季都有。"
        ),
        src_extra="各季 10-Q / 10-K 合并损益表的收入行与总费用行。",
    )
    margin_chart["ref"] = "EX_SET_MARGIN"

    types = staging["revenue_by_type_usd_m"]
    gross = [
        sum(types[key][i] for key in
            ("subscription", "non_subscription_transaction", "non_transaction",
             "asset_linked_fees", "sales_usage_royalties", "recurring_variable"))
        for i in range(len(types["quarters"]))
    ]
    share = [types["subscription"][i] / gross[i] * 100 for i in range(len(gross))]
    sub_chart = threshold_exhibit(
        "订阅型收入占毛收入比重 vs 阈值 47%",
        [compact_period(q) for q in types["quarters"]],
        rounded(share), 47.0,
        fmt="pct1", ylab="占毛收入比",
        actual_name="Subscription 占毛收入比", threshold_name="阈值 47%",
        note=(
            "公司把收入拆成六种申报类型，订阅是其中最大的一条，也是最不随发行周期摆动的一条。"
            f"这条线从 {share[0]:.1f}% 走到 {share[-1]:.1f}%，"
            "但它上升不全是订阅变强 —— 2022 年 IHS Markit 并表带进来的大多是订阅型收入。"
            "六条线各自的走向见 Exhibit {EX_L_TYPE}。"
        ),
        src_extra="各季 10-Q / 10-K 收入分解附注的六条收入类型行。",
    )
    sub_chart["ref"] = "EX_SET_SUB"

    return [bar, trans_chart, margin_chart, sub_chart]


# ── section two: what moved this quarter ─────────────────────────────────────
def quarter_segments(staging: dict) -> dict:
    segments = staging["segments_usd_m"]
    names = [("ratings", "Ratings"), ("indices", "Indices"),
             ("energy", "Energy"), ("market_intelligence", "Market Intelligence"),
             ("mobility", "Mobility")]
    latest = len(segments["quarters"]) - 1
    revenue = [segments["revenue"][key][latest] for key, _ in names]
    prior = [segments["revenue"][key][latest - 4] for key, _ in names]
    growth = [pct_change(now, was) for now, was in zip(revenue, prior)]
    return {
        "ref": "EX_Q_SEG",
        "kind": "grouped_bars",
        "title": (
            f"本季五个分部的收入同比：Indices {growth[1]:+.0f}%、Ratings {growth[0]:+.0f}% 领先，"
            f"Energy {growth[2]:+.0f}% 落后"
        ),
        "xlabels": [label for _, label in names],
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
            "五条分部收入加上分部间抵销恒等于申报的合并收入，本页 34 个季度逐季核对过，"
            "最大残差 US$1M（出现在按「全年减九个月」推出来的第四季度上）。"
            "<b>Mobility 这一根是最后一次出现在这张图上</b>："
            "公司于 2026-07-01 完成分拆，自 2026 年第三季度起它将按终止经营列报，"
            "并重述<b>所有</b>期间；截至本页取数时点，没有任何一份已申报报表是重述后的。"
            "分部口径用的是含分部间收入的申报列（8-K Exhibit 4 各期一致的那一列），"
            "不是 2025 年起新增的「对外部客户」列，两者本季相差 US$45M。"
        ),
        "src_extra": "各季 10-Q / 10-K 分部附注与业绩 8-K EX-99.1 Exhibit 4。",
    }


def quarter_ratings(staging: dict) -> dict:
    split = staging["ratings_revenue_split_usd_m"]
    window = 21
    labels = [compact_period(q) for q in split["quarters"][-window:]]
    transaction = split["transaction"][-window:]
    non_transaction = split["non_transaction"][-window:]
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
            "本季交易性 US$746M 是本记录内的最高值，"
            "而它在 2022Q3 曾经只有 US$244M。整段周期见 Exhibit {EX_L_RATINGS}。"
        ),
        "src_extra": "各季 10-Q / 10-K 收入附注与业绩 8-K EX-99.1 Revenue by Type 表。",
    }


def quarter_margin_bases(staging: dict) -> dict:
    """Three margins for one quarter, because the release prints two of them."""
    long_history = staging["long_history"]
    index = len(long_history["quarters"]) - 1
    revenue = long_history["revenue_usd_m"][index]
    operating = long_history["operating_income_usd_m"][index]
    gain = long_history["gain_on_dispositions_usd_m"][index]
    gaap = operating / revenue * 100
    ex_gain = operating_margin_ex_credits(long_history)[index]
    proforma_revenue, proforma_operating = 3678.0, 1757.0
    proforma = proforma_operating / proforma_revenue * 100
    adjusted_operating = 1998.0
    adjusted = adjusted_operating / proforma_revenue * 100
    return {
        "ref": "EX_Q_MARGIN",
        "kind": "bars_labeled",
        "title": (
            f"同一个季度的四个营业利润率口径：申报 {gaap:.1f}%、"
            f"剔除处置损益与联营收益 {ex_gain:.1f}%、公司口径 pro forma {proforma:.1f}%、"
            f"公司口径 adjusted {adjusted:.1f}%"
        ),
        "xlabels": ["申报 GAAP", "剔除处置损益与联营收益 D", "pro forma（不含 Mobility）",
                    "adjusted（不含 Mobility）"],
        "values": rounded([gaap, ex_gain, proforma, adjusted]),
        "legend": "本季营业利润率",
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "营业利润率",
        "note": (
            "<b>公司新闻稿的头条margin是第三根，不是第一根。</b>"
            "新闻稿里那句「operating profit margin increased 410 basis points to 47.8%」"
            f"说的是 pro forma 口径 —— 分母是剔除 Mobility 后的 US${proforma_revenue:,.0f}M，"
            f"而不是申报的 US${revenue:,.0f}M。按申报口径算是 {gaap:.1f}%。"
            "第二根是本页自算的口径：申报收入减去申报的总费用，"
            f"本季处置收益只有 US${gain:,.0f}M，所以第一、二根几乎一样高；"
            "在 2022 年那几季它们相差几十个百分点。"
            "四根都是可复算的，差别全在分子分母各取哪一列，本页把四列都画出来而不是挑一列。"
        ),
        "src_extra": (
            "申报口径取自截至 2026-06-30 的 10-Q 合并损益表；"
            "pro forma 与 adjusted 口径取自同日业绩 8-K EX-99.1 的 Exhibit 5 与 Exhibit 6。"
        ),
    }


def quarter_mobility(staging: dict) -> dict:
    """The guidance rebase, drawn as the two bases it actually spans."""
    record = staging["annual_guidance_history"]
    prior_mid = (record["guide_adjusted_eps_lo"][-2]
                 + record["guide_adjusted_eps_hi"][-2]) / 2
    new_mid = (record["guide_adjusted_eps_lo"][-1]
               + record["guide_adjusted_eps_hi"][-1]) / 2
    addback = record["mobility_addback_adjusted_eps_usd"]
    base_2025 = 17.83
    proforma_2025 = record["fy2025_proforma_adjusted_eps_usd"]
    old_growth = pct_change(prior_mid, base_2025)
    new_growth = pct_change(new_mid, proforma_2025)
    return {
        "ref": "EX_Q_MOBILITY",
        "kind": "grouped_bars",
        "title": (
            f"FY2026 指引中值掉了 US${prior_mid - new_mid:.2f}（{signed(pct_change(new_mid, prior_mid))}），"
            f"但同口径的增速从 {old_growth:+.1f}% 变成 {new_growth:+.1f}%"
        ),
        "xlabels": ["FY2025 基数", "FY2026 指引中值"],
        "groups": [
            {"name": "含 Mobility（Q1 及以前的口径）", "color": "GOLD",
             "values": rounded([base_2025, prior_mid])},
            {"name": "不含 Mobility（Q2 起的口径）", "color": "NAVY",
             "values": rounded([proforma_2025, new_mid])},
        ],
        "bar_labels": True,
        "fmt": "usd2",
        "label_fmt": "usd2",
        "ylab": "调整后摊薄 EPS（US$）",
        "note": (
            "<b>指引数字掉了，被指引的公司也变小了，两件事要一起看。</b>"
            "左边一组是基数：FY2025 实际调整后 EPS 为 US$17.83，"
            f"公司在 2026-07-06 单独发布的新闻稿里给出重述后的 FY2025 pro forma 基数 "
            f"US${proforma_2025:.2f}，两者相差 US${addback:.2f}，就是 Mobility 那一块。"
            "右边一组是指引中值。"
            f"拿金色比金色是 {old_growth:+.1f}%，拿深蓝比深蓝是 {new_growth:+.1f}% —— "
            "<b>按同口径看，这次修订是上调而不是下调。</b>"
            "斜着比（用新指引对旧基数）得到的那个「−9.7%」不对应任何真实的经营变化。"
            "公司自己在新闻稿里写的是「not directly comparable to prior guidance」。"
            "本页不发布任何自算的桥：公司没有披露 FY2026 口径差的逐项拆分，"
            f"US${addback:.2f} 是它对 <b>FY2025</b> 给出的加回额，不是对 FY2026 的。"
        ),
        "src_extra": (
            "指引区间取自 2026-04-28 与 2026-07-28 两份业绩 8-K 的 EX-99.1；"
            "FY2025 pro forma 基数取自 2026-07-06 的 8-K。"
        ),
    }


def quarter_issuance(staging: dict) -> dict:
    issuance = staging["billed_issuance_usd_bn"]
    labels = [compact_period(q) for q in issuance["quarters"]]
    total = issuance["total"]
    yoy = [None] * 4 + [pct_change(total[i], total[i - 4])
                        for i in range(4, len(total))]
    return {
        "ref": "EX_Q_ISSUANCE",
        "kind": "gs_bar",
        "title": (
            f"计费发行量 US${total[-1]:,.0f}B，同比 "
            f"{signed(pct_change(total[-1], total[-5]), 0)}；本记录从 2023 年才开始"
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
            "本页能往回补到 2023 年第一季度，靠的是 2024 年各季 10-Q 里的上年同期栏。"
            "<b>也就是说，这条线从 2022 年那次发行冰点之后才开始</b> —— "
            "它整段都在复苏区间里，看不到一次下行周期，"
            "拿它来论证「Ratings 有周期性」是不成立的，"
            f"能论证的是 Exhibit {{EX_L_RATINGS}} 那条 35 季的收入线。"
            "三个第四季度（2023、2024、2025）是「全年减九个月」推出来的，"
            "其余十一季是申报的单季值。"
            "公司只按评级类别（投资级 / 高收益 / 其他）拆分，从不按地区给金额。"
        ),
        "src_extra": "各季 10-Q / 10-K 的 MD&A「Billed Issuance Volumes」表。",
    }


def quarter_capital(staging: dict) -> dict:
    capital = staging["capital_allocation_usd_m"]
    window = 13
    labels = [compact_period(q) for q in capital["quarters"][-window:]]
    fcf = [o - c for o, c in zip(capital["operating_cash_flow"], capital["capex"])]
    payout = [b + d for b, d in zip(capital["buyback"], capital["dividends"])]
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
            "季节性很强：第一季度的经营现金流常年是全年最低的一档，"
            "所以单季的比值不宜单独解读，值得看的是连续几季都在上面的那些窗口。"
            "<b>本页的自由现金流是自算口径（D）</b>：经营现金流减资本开支。"
            "公司自己的定义还要再减去付给非控股股东的分派，"
            f"因此公司口径每年都比本页低，差额恰好等于那笔分派（FY2025 为 US$321M）。"
            "指引里用的又是第三个口径「调整后自由现金流」，"
            f"见 Exhibit {{EX_FCF_BAND}}。三个口径都在核对表里列出。"
        ),
        "src_extra": "各季 10-Q / 10-K 合并现金流量表；季度值为相邻两次年初至今申报值之差。",
    }


# ── section three: the thresholds pointed forward ────────────────────────────
def next_quarter_charts(staging: dict) -> list[dict]:
    entries = staging["next_kpi"]["quantified"]
    bar = headroom_exhibit(
        "下季阈值与当前值：距阈值余量",
        entries, "current",
        note=(
            "同一套归一化口径：正值＝当前值仍在安全侧。"
            "阈值是本站的研究设定，不是公司指引，也不是评级。"
            "把七条不同单位的线放在一根轴上是为了先看「哪条最接近临界」。"
            "下面画出其中四条的走势；另外三条 —— 「Ratings 交易性收入同比」"
            "「营业利润率」「订阅型收入占毛收入比重」—— 的历史图在第一节，"
            "本站每条跟踪指标只画一遍，不在两节之间重复。"
        ),
        src_extra="阈值为研究设定；当前值为截至 2026-06-30 的申报值与自算值。",
    )
    bar["ref"] = "EX_NEXT_BAR"

    split = staging["ratings_revenue_split_usd_m"]
    window = 21
    share = [t / (t + n) * 100
             for t, n in zip(split["transaction"], split["non_transaction"])]
    share_chart = threshold_exhibit(
        "交易性收入占 Ratings 比重 vs 阈值 58%",
        [compact_period(q) for q in split["quarters"][-window:]],
        rounded(share[-window:]), 58.0,
        fmt="pct1", ylab="占 Ratings 收入比",
        actual_name="交易性占比", threshold_name="阈值 58%（越高越依赖发行窗口）",
        note=(
            "<b>这条阈值的方向是「越低越安全」</b>，与本节其他几条相反："
            "占比越高，说明这家公司的收入越依赖一个它不控制的变量 —— 债券发行窗口。"
            f"本季 {share[-1]:.1f}%，离 58% 还有余量；"
            f"这个比率在本记录里最高到过 {max(share):.1f}%，最低到过 {min(share):.1f}%。"
        ),
        src_extra="各季 10-Q / 10-K 收入附注的交易性 / 非交易性两行。",
    )
    share_chart["ref"] = "EX_N_SHARE"

    capital = staging["capital_allocation_usd_m"]
    window = 17
    fcf = [o - c for o, c in zip(capital["operating_cash_flow"], capital["capex"])]
    fcf_chart = threshold_exhibit(
        "单季自由现金流 D vs 阈值 US$1,100M",
        [compact_period(q) for q in capital["quarters"][-window:]],
        rounded(fcf[-window:]), 1100.0,
        fmt="f0c", ylab="US$M",
        actual_name="自由现金流 D", threshold_name="阈值 US$1,100M",
        note=(
            "季节性明显：每年第一季度都是四季里最低的一档，"
            "所以这条阈值只在非第一季度有判别力，第一季度的穿越不作为信号。"
            "口径是经营现金流减资本开支，两端都是申报值。"
        ),
        src_extra="各季 10-Q / 10-K 合并现金流量表。",
    )
    fcf_chart["ref"] = "EX_N_FCF"

    payout = [(b + d) / f * 100 for b, d, f in
              zip(capital["buyback"], capital["dividends"], fcf)]
    payout_chart = threshold_exhibit(
        "单季股东回报 / 自由现金流 D vs 阈值 130%",
        [compact_period(q) for q in capital["quarters"][-window:]],
        rounded(payout[-window:]), 130.0,
        fmt="pct1", ylab="回报 / 自由现金流",
        actual_name="（回购 + 分红）/ 自由现金流 D", threshold_name="阈值 130%",
        note=(
            "单季穿越并不稀奇 —— 回购按授权与 ASR 的节奏走，现金流按季节走。"
            "值得看的是连续几季都在上面的窗口。"
            "公司自己给的是「把约 85% 的调整后自由现金流返还给股东」这类年度目标，"
            "口径与本图的自算分母不同，本页不把两者混为一谈。"
        ),
        src_extra="各季 10-Q / 10-K 合并现金流量表。",
    )
    payout_chart["ref"] = "EX_N_PAYOUT"

    issuance = staging["billed_issuance_usd_bn"]
    issuance_chart = threshold_exhibit(
        "计费发行量 vs 阈值 US$1,050B",
        [compact_period(q) for q in issuance["quarters"]],
        rounded(issuance["total"]), 1050.0,
        fmt="f0c", ylab="US$B",
        actual_name="计费发行量", threshold_name="阈值 US$1,050B",
        note=(
            "这是公司自己按季披露的 Ratings 前瞻量指标，"
            "但窗口只有 14 季且不含一次下行周期，理由见 Exhibit {EX_Q_ISSUANCE}。"
            "把它放在这里是因为它是唯一一条<b>先于收入</b>动的申报量指标。"
        ),
        src_extra="各季 10-Q / 10-K 的 MD&A「Billed Issuance Volumes」表。",
    )
    issuance_chart["ref"] = "EX_N_ISSUANCE"

    return [bar, share_chart, fcf_chart, payout_chart, issuance_chart]


# ── section four: the long filed record ──────────────────────────────────────
def long_ratings(staging: dict) -> dict:
    split = staging["ratings_revenue_split_usd_m"]
    labels = [compact_period(q) for q in split["quarters"]]
    transaction = split["transaction"]
    non_transaction = split["non_transaction"]
    # The drawdown has to be measured from a peak that *precedes* its trough:
    # the all-time high is the current quarter, and "fell from Q2'26 to Q3'22"
    # would read backwards in time. Taking the all-time low and looking left for
    # a peak worked only while the record began in 2017 -- extended back to 2016
    # the lowest quarter is the *first* one, and there is nothing to its left.
    # So take the deepest peak-to-trough fall anywhere in the series, which is
    # the quantity the sentence was always describing and is defined for any
    # window.
    peak_index = trough_index = 0
    running_peak, deepest = 0, -1.0
    for index, value in enumerate(transaction):
        if value > transaction[running_peak]:
            running_peak = index
        fall = 1 - value / transaction[running_peak]
        if fall > deepest:
            deepest, peak_index, trough_index = fall, running_peak, index
    trough = transaction[trough_index]
    peak = transaction[peak_index]
    return {
        "ref": "EX_L_RATINGS",
        "kind": "lines",
        "title": (
            f"{len(labels)} 季 Ratings 两条腿：交易性在 {labels[peak_index]} 见顶 "
            f"US${peak:,.0f}M，{labels[trough_index]} 只剩 US${trough:,.0f}M"
            f"（−{(1 - trough / peak) * 100:.0f}%），如今回到 US${transaction[-1]:,.0f}M 的新高；"
            f"非交易性同期没有塌陷过"
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
            "然后用了三年多回到今天的新高。"
            "金色那条是存续期监控与年费，同一段时间里"
            f"从 US${non_transaction[0]:,.0f}M 走到 US${non_transaction[-1]:,.0f}M，"
            "整段没有出现过深蓝那样的塌陷。"
            "<b>把这张图和第一节的指引记录并排看</b>："
            "七年里唯一一次开局指引没被超过的财年是 2022 年，"
            "而 2022 年正是深蓝这条线塌到谷底的那一年 —— "
            "公司当年 6 月撤回全年指引时给出的理由，"
            "写的就是「Ratings 业务面临极弱的市场环境」。"
            "两条线相加恒等于申报的 Ratings 分部收入。"
        ),
        "src_extra": "各季 10-Q / 10-K 收入附注与业绩 8-K EX-99.1 Revenue by Type 表。",
    }


def long_margin(staging: dict) -> dict:
    long_history = staging["long_history"]
    labels = [compact_period(q) for q in long_history["quarters"]]
    revenue = long_history["revenue_usd_m"]
    operating = long_history["operating_income_usd_m"]
    gaap = [o / r * 100 for o, r in zip(operating, revenue)]
    ex_gain = operating_margin_ex_credits(long_history)
    peak = max(gaap)
    peak_index = gaap.index(peak)
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
            "里面装着 US$1,344M 的剥离收益 —— 那是为通过反垄断审查而卖掉的业务，"
            f"剔掉之后是 {ex_gain[peak_index]:.1f}%。"
            "<b>断点标在 2022Q1</b>：IHS Markit 于 2022-02-28 交割，"
            "此后并购无形资产摊销进入费用，深蓝这条线从五十几个百分点被压到二十几，"
            "再用四年爬回今天的水平。断点两侧不是同一家公司，不要当成一条连续的经营曲线读。"
            "<b>左端第一道断点是列报口径，不是经营变化。</b>"
            "公司按 ASU 2017-07 把非服务性养老金成本挪到营业利润之下，"
            "并在 2018 年第一季度起的三份季报里重述了 2017 年前三季 —— "
            "本页 2017 年之后用的正是那批重述值。2016 的四个季度从未被任何申报按新口径重述过"
            "（该重述只以上年同期对比列出现，采用时对比窗口已够不到 2016），"
            "所以它们只能是原始申报口径。落差经逐季核对为每季 9.0，"
            "对营业利润率的影响 0.6–1.8pp —— 本页此前因此把序列截在 2017Q1，"
            "现在改为画出来并标注：断点的大小是量出来的，不再只是一个理由。"
        ),
        "src_extra": "各季 10-Q / 10-K 合并损益表的营业利润行与处置收益行。",
    }


def long_revenue(staging: dict) -> dict:
    long_history = staging["long_history"]
    labels = [compact_period(q) for q in long_history["quarters"]]
    revenue = long_history["revenue_usd_m"]
    yoy = [None] * 4 + [pct_change(revenue[i], revenue[i - 4])
                        for i in range(4, len(revenue))]
    return {
        "ref": "EX_L_REV",
        "kind": "gs_bar",
        "title": (
            f"{len(labels)} 季收入从 US${revenue[0]:,.0f}M 到 US${revenue[-1]:,.0f}M，"
            f"其中 2022 年那一跳是并表不是增长"
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
            "<b>右轴那根 2022 年的尖峰要按口径读，不要按经营读。</b>"
            "IHS Markit 于 2022-02-28 完成合并，因此 2022 年只装进约十个月的被并购方收入，"
            "而 2021 年一个月都没有：申报口径的全年收入从 US$8,297M 跳到 US$11,181M（+34.8%），"
            "但 10-K 自己给的备考口径（假设合并发生在 2021 年初）是从 US$12,382M "
            "降到 US$11,842M，也就是 −4.4% —— <b>同一年，两个方向相反的符号。</b>"
            "断点因此标在 2022Q1，本图不把它画成一条连续的增长曲线。"
            "另一件将要发生的事已经确定但还没进任何一张申报报表："
            "Mobility 于 2026-07-01 分拆，公司称自 2026 年第三季度起按终止经营"
            "重述<b>所有</b>期间，届时这条线的整段都会向下移约一成。"
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
    ratings_share = series[0]["values"]
    return {
        "ref": "EX_L_SEG",
        "kind": "lines",
        "title": (
            f"五个分部各自占分部收入合计的比重：Ratings 从 {ratings_share[0]:.0f}% "
            f"被稀释到 {min(v for v in ratings_share if v is not None):.0f}%，"
            f"如今回到 {ratings_share[-1]:.0f}%"
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
            "分母是五个分部收入之和（不含分部间抵销），所以五条线恒等于 100%。"
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


def long_revenue_types(staging: dict) -> dict:
    types = staging["revenue_by_type_usd_m"]
    labels = [compact_period(q) for q in types["quarters"]]
    names = [("subscription", "Subscription", "NAVY"),
             ("non_subscription_transaction", "Non-subscription / Transaction", "RED"),
             ("non_transaction", "Non-transaction", "GOLD"),
             ("asset_linked_fees", "Asset-linked fees", "GREEN"),
             ("sales_usage_royalties", "Sales usage-based royalties", "BLUE"),
             ("recurring_variable", "Recurring variable", "MBLUE")]
    gross = [sum(types[key][i] for key, _, _ in names) for i in range(len(labels))]
    series = [
        {"name": label, "color": color,
         "values": rounded([types[key][i] / gross[i] * 100 for i in range(len(labels))])}
        for key, label, color in names
    ]
    transaction = series[1]["values"]
    return {
        "ref": "EX_L_TYPE",
        "kind": "lines",
        "title": (
            f"六条申报收入类型各自占毛收入的比重：交易性从 {min(transaction):.1f}% "
            f"回到 {transaction[-1]:.1f}%，订阅稳定在五成上下"
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
            "六条相加减去分部间抵销恒等于申报的合并收入，本页 18 个季度逐季核对过。"
            "窗口从 2022Q1 开始，因为再往前是并购之前的分部结构，"
            "同名的类型装的不是同一批业务，拼接会得到一条假的结构迁移曲线。"
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
            f"{len(labels)} 季涨了 {aum[-1] / aum[0]:.1f} 倍"
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
            "<b>它是本页唯一一条不由公司经营决定的量</b> —— "
            "它跟的是市场点位与资金流向，公司能决定的只是费率与指数授权本身。"
            "<b>只画期末值，不画季度平均值</b>：10-K 给的是全年平均而不是第四季度平均，"
            "所以平均值那条线每年第四季度都有一个洞，本页不用推算去填它。"
            "2022 年公司同时披露过含与不含 IHS Markit 指数资产的两个口径，"
            "本页统一用不含的那个。"
        ),
        "src_extra": "各季 10-Q / 10-K 的 MD&A Indices 分部段落。",
    }


def long_capital(staging: dict) -> dict:
    capital = staging["capital_allocation_usd_m"]
    labels = [compact_period(q) for q in capital["quarters"]]
    fcf = [o - c for o, c in zip(capital["operating_cash_flow"], capital["capex"])]
    buyback = capital["buyback"]
    dividends = capital["dividends"]
    payout = [b + d for b, d in zip(buyback, dividends)]
    peak_index = buyback.index(max(buyback))
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
            "<b>2022 年第一季度那根尖峰是一次性的，而且日期很说明问题。</b>"
            "公司在 2021 年全年回购金额<b>恰好为零</b>（合并待批期间停止回购），"
            f"然后在 IHS Markit 交割的次日（2022-03-01）启动 US$7.0B 的加速回购，"
            f"当季回购 US${max(buyback):,.0f}M，而同季自由现金流只有 "
            f"US${fcf[peak_index]:,.0f}M。"
            "整个 2022 年回购 US$12,004M，约为当年经营现金流的 4.6 倍，"
            "钱来自 2021 年攒下的现金与剥离所得，"
            "账上现金也因此从 2021 年末的 US$6,497M 降到 2022 年末的 US$1,286M。"
            "分红那条腿则平稳得多，逐季缓慢抬升。"
            "现金流量表在 10-Q 里只有年初至今栏，除第一季外每季均为相邻两次申报值之差；"
            "四个季度相加与申报全年逐年相等，残差为零。"
        ),
        "src_extra": "各季 10-Q / 10-K 合并现金流量表。",
    }


def build_payload(staging: dict) -> dict:
    financials = staging["financials"]
    periods = staging["periods"]
    revenue = financials["revenue_usd_m"]
    operating = financials["operating_income_usd_m"]
    gain = financials["gain_on_dispositions_usd_m"]
    eps = financials["diluted_eps_usd"]
    record = staging["annual_guidance_history"]
    split = staging["ratings_revenue_split_usd_m"]

    guidance_ex, stats = guidance_charts(staging)
    settled_ex = settlement_charts(staging) + guidance_ex
    highlight_ex = [
        quarter_segments(staging),
        quarter_ratings(staging),
        quarter_margin_bases(staging),
        quarter_mobility(staging),
        quarter_issuance(staging),
        quarter_capital(staging),
    ]
    next_ex = next_quarter_charts(staging)
    routine_ex = [
        long_ratings(staging),
        long_margin(staging),
        long_revenue(staging),
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

    split_rows = [
        [split["quarters"][i],
         f"${split['transaction'][i]:,.0f}M",
         f"${split['non_transaction'][i]:,.0f}M",
         f"${split['transaction'][i] + split['non_transaction'][i]:,.0f}M",
         f"{split['transaction'][i] / (split['transaction'][i] + split['non_transaction'][i]) * 100:.1f}%"]
        for i in range(len(split["quarters"]) - 21, len(split["quarters"]))
    ]

    segments = staging["segments_usd_m"]
    segment_rows = [
        [segments["quarters"][i]]
        + [f"${segments['revenue'][key][i]:,.0f}M"
           if segments["revenue"][key][i] is not None else "—"
           for key in ("ratings", "indices", "energy", "market_intelligence", "mobility")]
        + [f"${segments['intersegment_elimination'][i]:,.0f}M",
           "全年减九个月 D" if segments["quarters"][i] in segments["derived_quarters"]
           else "10-Q 申报三个月栏"]
        for i in range(len(segments["quarters"]) - 13, len(segments["quarters"]))
    ]

    capital = staging["capital_allocation_usd_m"]
    capital_rows = [
        [capital["quarters"][i],
         f"${capital['operating_cash_flow'][i]:,.0f}M",
         f"${capital['capex'][i]:,.0f}M",
         f"${capital['operating_cash_flow'][i] - capital['capex'][i]:,.0f}M",
         f"${capital['buyback'][i]:,.0f}M",
         f"${capital['dividends'][i]:,.0f}M"]
        for i in range(len(capital["quarters"]) - 13, len(capital["quarters"]))
    ]

    tables = [
        {
            "n": first_table,
            "title": "全年指引的全部 31 档 vintage 与被它们指引的那一年（FY2019–FY2026）",
            "headers": ["vintage", "财年", "发布日", "载体", "调整后 EPS 指引",
                        "GAAP EPS 指引", "收入增速指引", "调整后 FCF 指引",
                        "该年实际调整后 EPS", "该年实际 GAAP EPS"],
            "rows": guidance_rows,
        },
        threshold_table(first_table + 1, "上季阈值与本季实际（原单位）",
                        staging["prior_kpi_settlement"]["quantified"], "actual", "本季实际"),
        threshold_table(first_table + 2, "下季阈值与当前值（原单位）",
                        staging["next_kpi"]["quantified"], "current", "当前值"),
        {
            "n": first_table + 3,
            "title": "近十二季损益表与两个营业利润率口径",
            "headers": ["期间", "收入", "收入 YoY", "营业利润", "营业利润率 D",
                        "其中处置收益", "（收入−费用）/ 收入 D", "净利润",
                        "摊薄 EPS", "摊薄股数（百万）"],
            "rows": quarterly_rows,
        },
        {
            "n": first_table + 4,
            "title": "近二十一季 Ratings 的交易性与非交易性收入",
            "headers": ["期间", "交易性", "非交易性", "分部收入合计", "交易性占比 D"],
            "rows": split_rows,
        },
        {
            "n": first_table + 5,
            "title": "近十三季分部收入（含分部间收入的申报列）",
            "headers": ["期间", "Ratings", "Indices", "Energy", "Market Intelligence",
                        "Mobility", "分部间抵销", "取数方式"],
            "rows": segment_rows,
        },
        {
            "n": first_table + 6,
            "title": "近十三季现金流与股东回报",
            "headers": ["期间", "经营现金流", "资本开支", "自由现金流 D", "回购", "分红"],
            "rows": capital_rows,
        },
        ai_capex_cycle_table(first_table + 7),
    ]

    adj_above, adj_inside, adj_below = stats["adjusted"]
    gaap_above, gaap_inside, gaap_below = stats["gaap"]
    finished_years = adj_above + adj_inside + adj_below
    prior_mid = (record["guide_adjusted_eps_lo"][-2]
                 + record["guide_adjusted_eps_hi"][-2]) / 2
    new_mid = (record["guide_adjusted_eps_lo"][-1]
               + record["guide_adjusted_eps_hi"][-1]) / 2

    return {
        "schema_version": "quarterly-dashboard/spgi-v1",
        "page": {"slug": "spgi", "language": "zh-CN"},
        "company": {
            "ticker": "SPGI",
            "name": "S&P Global",
            "group": "financial_data_indices",
            "accounting_standard": "US GAAP",
        },
        "latest": {
            "disclosed_period_label": "Q2 2026",
            "full_financial_period_label": "Q2 2026",
            "period_end": "2026-06-30",
            "release_date": "2026-07-28",
            "analysis_date": "2026-08-29",
            "audit_status": "unaudited",
            "status": "history_ready",
        },
        "tracker": "Watchlist Quarterly Tracker · SPGI",
        "title": "S&P Global (SPGI)：Q2 2026 季报仪表盘",
        "subtitle": (
            "截至 2026-06-30 · 发布 2026-07-28 · US GAAP · 未审计 · "
            "自然年财年，季度标注与本站其余各页一致"
        ),
        "headline": plain_text(
            f"公司不给季度指引，只给全年指引并逐季修订；本页把 FY2019–FY2026 的 "
            f"{len(record['vintages'])} 档 vintage 排成一条修订路径。"
            f"记录是两面的：{finished_years} 个已完结财年里，调整后摊薄 EPS "
            f"一次都没有跌破过自己的末次指引下限，"
            f"同一张展望表上的 GAAP 摊薄 EPS 却跌破了 {gaap_below} 次。"
            f"本季那根看起来像 −US${prior_mid - new_mid:.2f} 的指引下调也不是下调 —— "
            f"Mobility 于 2026-07-01 分拆，指引换了口径，按同口径看是上调。"
        ),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>记录</span><b>不失手的是公司自己定义的那条</b>'
            f'<p>{finished_years} 个已完结财年，调整后 EPS 相对末次指引 '
            f'{adj_above} 年超出上限、{adj_inside} 年落在区间内、{adj_below} 年跌破；'
            f'GAAP EPS 在同样七年里跌破 {gaap_below} 次。差额全在并购摊销与处置损益上。</p></article>'
            '<article><span>本季</span><b>指引掉了 $1.90，公司也小了一块</b>'
            f'<p>Mobility 于 2026-07-01 分拆，FY2026 调整后 EPS 指引从 '
            f'${prior_mid:.3f} 中值挪到 ${new_mid:.3f}。'
            '公司同时给了重述后的 FY2025 基数，按同口径算这次是上调。</p></article>'
            '<article><span>周期</span><b>Ratings 的交易腿又回到高点</b>'
            f'<p>交易性收入 US${split["transaction"][-1]:,.0f}M 创记录内新高，'
            f'而它在 2022Q3 只有 US${min(split["transaction"]):,.0f}M；'
            '非交易性那条年金腿同期从未塌陷。</p></article>'
            '</div>'
        ),
        "source": (
            'Source: <a href="https://www.sec.gov/Archives/edgar/data/64040/'
            '000006404026000040/spgi2q2026-earningsrelease.htm" rel="noopener">S&P Global '
            '2026 年第二季度业绩新闻稿（8-K EX-99.1）</a>与截至 2026-06-30 的 10-Q。'
        ),
        "source_url": (
            "https://www.sec.gov/Archives/edgar/data/64040/"
            "000006404026000040/spgi2q2026-earningsrelease.htm"
        ),
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {
                "id": "settled",
                "title": "一、上季兑现了吗",
                "description": plain_text(
                    "先结清上一份笔记留下的阈值，再看新数字。"
                    "这一节的后半段是本页与本站其他几页最不一样的地方："
                    "S&P Global 从不发布季度指引，它发布的是全年指引并逐季修订，"
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
                    "同一个季度被印成四个数的营业利润率，"
                    "以及一次被普遍读成下调、其实是换口径的指引修订。"
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
        "notes": [plain_text(_p) for _p in [
            "长序列左端有一道<b>养老金列报口径</b>断点：2016 四季为原始申报口径，2017 起为公司按 ASU 2017-07 重述后的口径，逐季差 9.0（营业利润低 9.0、总费用高 9.0）。收入不受该重述影响，两段可直接相接；营业利润与利润率两段之间的落差属于列报差异，不是经营变化，图上已标出断点。",
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "S&P Global 采用自然年财年，本页所有季度标注即该季度本身，无需财年映射。",
            "<b>公司从不在申报文件里发布季度指引，因此本页没有逐季的指引兑现记录。</b>"
            "这是取数限制而不是编辑取舍 —— 它在每季业绩 8-K 的 EX-99.1 里给的是<b>全年</b>展望，"
            "并在其后每个季度修订一次。本页因此建的是同构的记录："
            "把每个财年的历次 vintage（年初首次 → Q1 → Q2 → Q3 修订）排成一条连续的区间带，"
            "把该财年最终报出来的实际值落在<b>末次</b>那一格上。"
            "微软、Alphabet、Mastercard、Visa 与盈透证券五页出于各自的理由也没有季度记录。",
            "<b>这份记录的时效性必须先读。</b>四档 vintage 分别发布在该财年的 2 月、4-5 月、7-8 月与 10-11 月，"
            "末次那一档发布时该财年已经过去约四分之三，公司手里已有三个季度的实际数。"
            "因此「末次指引从没被跌破」这句话的分量远小于字面，"
            "真正带信息的是开局那一档 —— 本页专门画了一张按 vintage 位次看偏离收敛的图。",
            "记录是两面的，而这正是把两个指标画在一起才看得见的事："
            "七个已完结财年里，调整后摊薄 EPS 五年高于末次区间上限、两年落在区间内、"
            "<b>一年都没有跌破过</b>；同一张展望表上的 GAAP 摊薄 EPS 却<b>跌破了三次</b>。"
            "两者之差全部落在调整线以下 —— 并购无形资产摊销、处置损益与减值，"
            "也就是公司自己选择剔除的那些项。不发布任何关于这个差异是否合理的判断。",
            "<b>FY2026 的指引在本季换了口径，本页保留落差并标注，不做平滑。</b>"
            "公司于 2026-07-01 完成 Mobility 分拆（Mobility Global，NYSE: MBGL，1 股换 1 股）。"
            "2026-07-28 那份新闻稿把 FY2026 调整后 EPS 指引从 US$19.40–19.65 挪到 US$17.50–17.75，"
            "并写明「Current adjusted financial guidance is not directly comparable to prior guidance」。"
            "公司同时在 2026-07-06 单独发布了重述后的 FY2025 基数，"
            "两者相差 US$1.98/股。<b>本页不发布任何自算的 FY2026 口径桥</b>："
            "那 US$1.98 是公司对 FY2025 给出的加回额，不是对 FY2026 的，"
            "把它当成 FY2026 的差额去搭桥是发布方的发明，不是公司的披露。",
            "<b>Mobility 在本页的所有报表数字里仍然是继续经营的一个分部。</b>"
            "分拆于 2026-07-01 生效，比本页报告的季末晚一天，"
            "因此截至 2026-06-30 的 10-Q 里没有终止经营行、没有持有待售的 Mobility 资产，"
            "分部附注里它是完整的五个分部之一（本季收入 US$468M）。"
            "公司在同一份 10-Q 里说明，自 2026 年第三季度起将把 Mobility 按终止经营重述<b>所有</b>期间。"
            "本页实测核对过：2025Q2 的合并收入在 2025 年的 10-Q 与 2026 年的 10-Q 里都是 US$3,755M，"
            "分毫未动 —— 也就是说重述尚未发生在任何一份已申报的报表里。"
            "等第三季度 10-Q 落地，本页的长序列需要整体重建。",
            "长序列在 2022Q1 打了结构断点：IHS Markit 于 2022-02-28 完成合并，"
            "所以 2022 年只装进约十个月的被并购方收入而 2021 年一个月都没有。"
            "申报口径全年收入从 US$8,297M 跳到 US$11,181M（+34.8%），"
            "而 10-K 自己给的备考口径（假设合并发生在 2021 年初）是从 US$12,382M 降到 US$11,842M，"
            "即 −4.4%。同一年两个方向相反的符号，因此这条线不画成连续的增长曲线。",
            "营业利润率的长序列起点定在 2017Q1 而不是更早："
            "公司按 ASU 2017-07 重述了 FY2016 的全年营业利润，却从未重述 2016 年的各个季度，"
            "那四个季度在任何申报文件里都只有旧口径的版本，本页因此不往前补。"
            "收入、净利润、每股收益与现金流各行本身从 2016Q1 起就是干净的。",
            "<b>营业利润率一律同时给出剔除处置收益的口径。</b>"
            "公司的损益表结构是「收入 − 费用 + 处置损益 + 联营收益 = 营业利润」，"
            "处置损益是一张申报的行而不是估计值，"
            "但它足以把 2022Q1 的营业利润率顶到 79.2%（当季处置收益 US$1,344M，剔除后 22.9%）。"
            "本页把两条线并排画出来，而不是挑一条画、在脚注里说明另一条。",
            "分部口径统一用<b>含分部间收入</b>的申报列，也就是业绩 8-K Exhibit 4 各期一致的那一列。"
            "自 2025 年第一季度起（ASU 2023-07），10-Q 的分部附注同时印出「对外部客户」与「分部间」两列，"
            "两种口径本季相差 US$45M；混用会在 2025 年初制造一个并不存在的台阶。"
            "分部收入加分部间抵销恒等于申报合并收入，34 季逐季核对，最大残差 US$1M（出现在推算的第四季度上）。",
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
            "公司自己的定义还要再减去付给非控股股东的分派（FY2025 为 US$321M），"
            "而全年指引里用的是第三个口径「调整后自由现金流」，还会加回并购费用、遣散与处置税负等项。"
            "三个口径都在核对表里列出，本页不把它们混为一谈。",
            "现金流量表在 10-Q 里只有年初至今栏，因此除第一季外每季均为相邻两次申报值之差；"
            "四个季度相加与申报全年逐年相等，十个财年、六条现金流线全部残差为零。"
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
            "<b>Mobility 剥离后的重述历史</b>（尚无任何一份已申报报表是重述后的）；"
            "<b>分部营业利润率的长序列</b>（分部营业利润含处置损益，"
            "Market Intelligence 在 2022Q1 因此出现 205% 的分部利润率）；"
            "<b>按地区拆分的发行量金额</b>（公司只按评级类别给金额；2024 年之前那张按地区的表"
            "是口径不同的「市场发行量」，且只给同比百分比）；"
            "<b>交易所衍生品成交量与共同基金 AUM</b>（只在投资者关系网站按月披露，未进入申报文件）；"
            "<b>季度平均 ETF 资产规模</b>（10-K 给的是全年平均，第四季度是空档，本页不推算）；"
            "以及任何来自业绩电话会而无法与第二个来源核对的前瞻数字。",
            "业绩电话会文字稿仅链接官方 IR 与 SEC 托管版本，公开仓不复制原件或逐字内容。",
        ]],
        "footer": "SPGI quarterly results · 数据来自 S&P Global 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


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
