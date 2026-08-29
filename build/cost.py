#!/usr/bin/env python3
"""Build the Costco quarterly-results page.

Same four-part, chart-led shape as the other company pages (上季兑现 → 本季重点
→ 下季跟踪 → 长期常规).  Costco's fiscal year ends on the Sunday nearest 31
August, so every label here is a calendar quarter: the twelve weeks ended
2026-05-10 are the company's FY2026 Q3 and this page's ``Q2 2026``.

**Costco does file numeric guidance -- it is just never about profit.**  Across
twelve consecutive earnings 8-Ks the words `outlook`, `guidance` and `we expect`
appear only inside the forward-looking-statements legend: no revenue range, no
EPS range, no margin, no comparable-sales forecast.  What every 10-K does carry,
in the paragraph headed `Capital Expenditure Plans`, is next year's capital
expenditure as a dollar range and a warehouse opening plan phrased as a ceiling
-- and the same paragraph is rewritten in every 10-Q, so each year has an
opening vintage and up to three revisions.  Since 2024-05-30 the EX-99.2
supplemental deck adds a fiscal-year-end warehouse count, revised quarterly.

That record has a shape none of the others on this site do.  Against the plan as
first published the outcomes land above the range and below it in equal numbers.
Every other guidance record here behaves like a floor; a capital plan is not a
promise to anyone, so nothing pushes it toward a number that will be cleared.
Balanced is not the same as uninformative: the misses are not spread evenly in
time, and the quarterly revision narrows the mean absolute error by less than
half -- against the seven-fold funnels the annual-guidance pages show.

Two disclosure facts shape the rest of the page.

The first is a **resolution gap**.  Costco publishes comparable sales twice: to
one decimal in the earnings press release, and rounded to whole percentages in
the 10-Q.  The local note's central claim -- that the ex-gasoline, ex-currency
comp is a flat line at about 6.5% -- is only visible at press-release
resolution.  In the filings the same three quarters read 6%, 7%, 7%, which looks
like acceleration.  This page plots the release series and says so.

The second is that **the headline is inflated at both ends, and both inflations
come back out of filed numbers**.  Reported comp is +9.8% against an adjusted
+6.6%, and EPS is +15.2% against operating income +11.3%; the comp gap is
gasoline and currency, and the EPS wedge factors exactly into a below-the-line
leg and a tax leg.  Neither correction needs an estimate.  What the full record
adds to the local note is the sign: over 27 quarters that comp gap has been
*negative* in 15, so gasoline and currency have suppressed the headline more
often than they have flattered it.

Costco is also the only company here that publishes a sales figure between
earnings dates -- a comparable-sales reading for every four- or five-week retail
month.  Only some of those reach EDGAR: about forty 8-Ks carry a retail month,
overwhelmingly February, bundled into the second-quarter earnings release.  That
makes a sparse annual point, not a monthly series, and the site's cadence is
quarterly either way, so none of it is carried.  The same bundling is a parser
trap the page had to handle: every Q2 release prints *two* comparable-sales
tables with identical row labels, one for the thirteen-week quarter and one for
the February retail month.

Published numbers are company-reported or transparent arithmetic.  No market
expectation is published: the consensus basis for this quarter is not consistent
across sources, and inventing a comparison point is worse than omitting one.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import (  # noqa: E402
    ai_capex_cycle_table,
    headroom_exhibit,
    number_exhibits,
    threshold_exhibit,
    threshold_table,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "cost.json"
DATA_DIR = ROOT / "data"

# A 27-quarter axis needs thinned tick labels or the quarter names collide.
LONG_STEP = 3


def compact_period(period: str) -> str:
    """``'Q2 2026'`` → ``'Q2'26'``."""
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def rounded(values, digits: int = 6):
    return [None if v is None else round(v, digits) for v in values]


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


SOURCE_PR = (
    "同店销售取自各季业绩 8-K 的 EX-99.1 新闻稿开头那张表，公司在那里给到<b>一位小数</b>；"
    "同一组数字在 10-Q 的 MD&A 里被四舍五入到整数百分点。"
)

RESOLUTION_NOTE = (
    "<b>这条序列只有在新闻稿的精度上才存在。</b>同样这三个季度，10-Q 印出来的调整后合并 comp "
    "是 6%、7%、7%，读起来像在加速；新闻稿的一位小数是 6.4%、6.7%、6.6%，是一条平线。"
    "本页一律取新闻稿那一版，并在核对表里同时列出 10-Q 的整数版，"
    "好让读者看见这个差别是精度而不是数据。"
)

# ── section one: the two records Costco actually files ──────────────────────
CAPEX_TIMING = "该财年<b>开始后约五周</b>"

CAPEX_SOURCE = (
    "指引取自各年 10-K 的 Liquidity and Capital Resources 里那段 Capital Expenditure Plans，"
    "句式历年一致：「In 2025, we spent $5,498 on capital expenditures, and it is our current "
    "intention to spend $6,000 to $6,500 during fiscal 2026.」"
    "实际值取自被指引那一年自己那份 10-K 现金流量表的 Additions to property and equipment。"
)

WINDOW_NOTE = (
    "<b>这张图的窗口比记录短，理由是刻度而不是取数。</b>完整记录从 FY1995 起 —— "
    "EDGAR 上最早那份 10-K 就带着这段话 —— 但那一年的计划是 US$550–700M，"
    "而 FY2026 的是 US$6,000–6,500M；一条线性纵轴放不下三十年而不把早年的色块压成一根发丝。"
    "<b>整段记录由下一张无量纲的偏离图承载</b>，那是本站 NVIDIA 页处理同一个问题的办法。"
    "另外，FY2007 之前公司把计划拆成美加与国际两笔分别给出，本页取两笔之和（D）。"
)

CAPEX_LAG_NOTE = (
    "<b>先读这两句，再读命中率。</b>其一，10-K 申报时，它所指引的那个财年<b>已经开始了</b> —— "
    "Costco 的财年在 9 月初开始，而年报在 10 月甚至更晚才申报。近十四年是第 37 到 53 天，"
    "更早的年份更晚：FY2007 之前的年报要到被指引财年的第 67 到 87 天才出来，"
    "因为那时还没有大型加速申报人的 60 天期限。整段记录的区间是第 37 到 87 天。"
    "其二，它<b>不是只发一次</b>：每一季的 10-Q 都会把同一段重写一遍，"
    "所以每个财年都有一版年初计划和最多三次修订（本页只回溯到 FY2013）。"
    "本节把「年初那一版」与「当年最后一版」分开结清，因为两者的答案不一样。"
)


def capex_charts(staging: dict) -> tuple[list[dict], dict]:
    """The capital-expenditure plan against what was actually spent.

    This is the only numeric multi-year delivery record Costco files, and its
    shape is unlike any other on this site: against the plan as first published
    the outcomes land above and below in equal numbers.  A capital plan is not a
    promise to the market -- underspending it is not a miss and overspending it
    is not a beat -- so there is no reason for it to behave like the floors the
    other pages' guidance records turn out to be.

    The plan is restated in every 10-Q, so each year has an opening vintage and
    up to three revisions.  Both ends are settled here, because the revision
    narrows the error by less than half, which is a far weaker funnel than the
    annual-guidance pages show.
    """
    record = staging["capex_guidance"]
    years = record["guided_fiscal_years"]
    labels = [f"FY{year}" for year in years]
    low, high = record["guided_low_usd_m"], record["guided_high_usd_m"]
    actual = record["actual_capex_usd_m"]

    full_record = staging["capex_record_full"]
    full_settled = [i for i, v in enumerate(full_record["deviation_vs_opening_pct"])
                    if v is not None]

    finished = [i for i, (a, lo) in enumerate(zip(actual, low))
                if a is not None and lo is not None]
    above = [i for i in finished if actual[i] > high[i]]
    below = [i for i in finished if actual[i] < low[i]]
    inside = len(finished) - len(above) - len(below)

    # The symmetry is a property of the OPENING vintage AND of the recent
    # window. Scored against each year's final 10-Q, or across the whole
    # thirty-year record, the same series leans one way -- so every tally the
    # page states is computed here and all of them go on the charts. Publishing
    # only the one that survives is choosing the condition that makes the
    # finding.
    def tally(verdicts):
        counts = {"ABOVE": 0, "BELOW": 0, "INSIDE": 0}
        for verdict in verdicts:
            if verdict in counts:
                counts[verdict] += 1
        counts["total"] = sum(counts[k] for k in ("ABOVE", "BELOW", "INSIDE"))
        return counts

    final = tally([verdict for verdict, a in zip(record["verdict_vs_final"], actual)
                   if a is not None])
    final_above, final_below = final["ABOVE"], final["BELOW"]
    final_inside, final_total = final["INSIDE"], final["total"]

    whole = {"ABOVE": 0, "BELOW": 0, "INSIDE": 0}
    for index in full_settled:
        verdict = full_record["verdict_vs_opening"][index]
        if verdict in whole:
            whole[verdict] += 1
    full_tally_text = (f"{len(full_settled)} 个已完结年度是 {whole['BELOW']} 年低于区间、"
                       f"{whole['INSIDE']} 年落在区间内、{whole['ABOVE']} 年高于区间")

    # "approximately $X to $Y" is not a hard bound, and two of the overshoots
    # sit inside what the word plausibly covers. Counting them as breaches
    # without saying so would read the wording more strictly than it is written.
    hedged = sum(1 for lo in low if lo is not None)
    hedged_approx = sum(1 for text in record["figure_as_printed"]
                        if text and "approximately" in text.lower())
    soft = [i for i in above if actual[i] / high[i] - 1 < 0.05]
    soft_above = len(soft)
    soft_above_labels = [labels[i] for i in soft]

    # The regime shift is real but it is not a clean flip: the earliest settled
    # year is itself an overshoot, so "underspent every year, then overspent
    # every year" is false in both halves.
    FLIP_YEAR = 2021
    early = tally([record["verdict_vs_opening"][i] for i in finished
                   if years[i] < FLIP_YEAR])
    late = tally([record["verdict_vs_opening"][i] for i in finished
                  if years[i] >= FLIP_YEAR])
    early_above_labels = [labels[i] for i in finished
                          if years[i] < FLIP_YEAR
                          and record["verdict_vs_opening"][i] == "ABOVE"]
    qualitative = [labels[i] for i, flag in enumerate(record["is_qualitative"]) if flag]
    pending = [labels[i] for i, a in enumerate(actual) if a is None]

    band = {
        "ref": "EX_CAPEX_BAND",
        "kind": "range_band",
        "title": (f"资本开支计划与实际（年初那一版）：{len(finished)} 个已完结年度里 "
                  f"{len(above)} 年高于上限、{inside} 年落在区间内、{len(below)} 年低于下限"),
        "xlabels": labels,
        "xrot": 90,
        "lo": low,
        "hi": high,
        "actual": actual,
        "actual_color": "NAVY",
        "names": {"range": "10-K 里的资本开支计划区间", "actual": "实际资本开支",
                  "lo": "计划下限（US$M）", "hi": "计划上限（US$M）"},
        "fmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$M",
        "note": (f"色块是{CAPEX_TIMING}公司在 10-K 里给出的下一财年资本开支区间，"
                 "菱形是那一年实际花掉的钱。"
                 "<b>本站其他每一份指引记录都是单边的</b> —— 要么几乎从不跌破下限，"
                 f"要么几乎每期穿出上限；这一段 {len(finished)} 年里 {len(below)} 年低于下限、"
                 f"{len(above)} 年高于上限，两边一样多。"
                 "<b>但这只是最近这一段。</b>把窗口拉到 FY1995 起的完整记录，"
                 f"{full_tally_text}，对称就没有了 —— 见 Exhibit {{EX_CAPEX_DEV}}。"
                 "原因是结构性的，而且这<b>不是一次同类比较</b>：别的页记录的是收入、利润或每股收益，"
                 "那是对市场的预测；这一份记录的是支出，是公司给自己排的预算。"
                 "少花不算失信、多花也不算超预期，所以没有把它设在容易达成位置的动机 —— "
                 "分布对称的原因在这里，不在预测能力上。"
                 f"<b>而且这句话连在这一段里也只对年初那一版成立</b>：换成当年最后一版 10-Q，"
                 f"{final_total} 个已结清年度是 {final_above} 年高于上限、{final_inside} 年落在区间内、"
                 f"{final_below} 年低于下限。"
                 "<b>一句话经不起换窗口，也经不起换 vintage，那它就不是一个发现。</b>"
                 "本页把两个都画出来，让读者自己看这句话在哪些条件下成立。"
                 f"另一层软化在措辞里：{hedged} 个数字区间里有 {hedged_approx} 个印的是"
                 "「approximately $X to $Y」，"
                 f"而 {len(above)} 次高于上限里有 {soft_above} 次只超出上限不到 5%（"
                 + "、".join(soft_above_labels) + "），落在这个词本身能覆盖的范围内。"
                 + (f"{'、'.join(qualitative)} 那一格没有色块 —— 那一年公司只说了要花"
                    "「a similar amount」，是一句话不是一个区间，本页不把词换算成数；"
                    "那年实际花的钱比上一年多 16.7%。" if qualitative else "")
                 + (f"最后一格 {pending[-1]} 只有区间，实际值待披露。" if pending else "")
                 + WINDOW_NOTE
                 + CAPEX_LAG_NOTE
                 + "纵轴不自 0 起，但没有任何点被截掉。"),
        "src_extra": CAPEX_SOURCE,
    }
    if pending:
        band["annot"] = f"{pending[-1]}：仅计划，实际值待披露"

    # ── the deviation chart carries the WHOLE record, not the band's window ──
    full = staging["capex_record_full"]
    full_labels = [f"FY{year}" for year in full["guided_fiscal_years"]]
    dev_open = full["deviation_vs_opening_pct"]
    dev_final = full["deviation_vs_final_pct"]
    settled = [i for i, v in enumerate(dev_open) if v is not None]
    full_tally = tally([full["verdict_vs_opening"][i] for i in settled])

    # The two halves are the two harvests, FY1995-2012 and FY2013-2026 -- not
    # the FLIP_YEAR split, which is about the recent window's own internal
    # shift and would put 26 years on one side of this comparison and 4 on the
    # other.
    SPLIT_YEAR = 2013
    early = tally([full["verdict_vs_opening"][i] for i in settled
                   if full["guided_fiscal_years"][i] < SPLIT_YEAR])
    late = tally([full["verdict_vs_opening"][i] for i in settled
                  if full["guided_fiscal_years"][i] >= SPLIT_YEAR])

    # A point guidance has no width, so a year guided as a point cannot land
    # "inside" one; those years are excluded from the hit rate rather than
    # counted as misses -- the distinction the NVIDIA page draws for its opex
    # line. Counting them as misses is what makes the two eras look identical.
    def inside_rate(lo_year, hi_year):
        years = [i for i in settled
                 if full["guidance_shape"][i] == "range"
                 and lo_year <= full["guided_fiscal_years"][i] <= hi_year]
        hits = sum(1 for i in years if full["verdict_vs_opening"][i] == "INSIDE")
        return hits, len(years), hits / len(years) * 100

    early_hits, early_ranged, early_rate = inside_rate(0, SPLIT_YEAR - 1)
    late_hits, late_ranged, late_rate = inside_rate(SPLIT_YEAR, 9999)

    # Both averages must be taken over the SAME years, or the comparison is the
    # full record's spread against the recent window's.
    both = [i for i in settled if dev_final[i] is not None]
    open_abs_both = [abs(dev_open[i]) for i in both]
    final_abs_both = [abs(dev_final[i]) for i in both]
    open_abs_all = [abs(dev_open[i]) for i in settled]

    # The direction runs in blocks rather than year to year, so the blocks are
    # measured rather than described from memory.
    def longest_run(predicate):
        best, current = [], []
        for i in settled:
            if predicate(full["verdict_vs_opening"][i]):
                current.append(full["guided_fiscal_years"][i])
            else:
                best, current = (current if len(current) > len(best) else best), []
        return current if len(current) > len(best) else best

    run_above = longest_run(lambda v: v == "ABOVE")
    run_none = longest_run(lambda v: v != "ABOVE")
    biggest = max((dev_open[i] for i in settled), key=abs)
    points = [full_labels[i] for i in settled if full["guidance_shape"][i] == "point"]

    dev = {
        "ref": "EX_CAPEX_DEV",
        "kind": "grouped_bars",
        "title": (f"实际资本开支相对计划中值的偏离，{len(settled)} 个已完结年度："
                  f"{full_tally['BELOW']} 年低于区间、{full_tally['INSIDE']} 年落在区间内、"
                  f"{full_tally['ABOVE']} 年高于区间"),
        "xlabels": full_labels,
        "xrot": 90,
        "groups": [
            {"name": "对 10-K 年初计划中值", "color": "GOLD", "values": dev_open},
            {"name": "对当年最后一次 10-Q 计划中值", "color": "NAVY", "values": dev_final},
        ],
        "bar_labels": False,
        "fmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "% vs 计划中值",
        "note": ("正值 = 花得比计划中值多。"
                 "<b>把上一张图的十二年放回三十年里，那份对称就不见了：</b>"
                 f"整段记录是 {full_tally['BELOW']} 年低于区间对 {full_tally['ABOVE']} 年高于区间；"
                 f"FY{SPLIT_YEAR} 之前的 {early['total']} 年是 {early['BELOW']} 比 {early['ABOVE']}，"
                 f"之后的 {late['total']} 年才是 {late['BELOW']} 比 {late['ABOVE']} 的对半。"
                 "所以「两边一样多」是最近这一段窗口的性质，不是这家公司的性质 —— "
                 "本页上一张图因此把窗口写进了标题。"
                 "<b>相对稳的是另一个数：区间被打中的频率。</b>"
                 f"在以区间形式给出的年度里，前一段 {early_ranged} 年中了 {early_hits} 次"
                 f"（{early_rate:.0f}%），后一段 {late_ranged} 年中了 {late_hits} 次"
                 f"（{late_rate:.0f}%）—— 两段都在五分之一到六分之一之间。"
                 "变的主要是错的方向，不是错的频率。"
                 f"（{'、'.join(points)} 公司给的是单点而不是区间，没有宽度可落，"
                 "只可能高于或低于，不计入这个频率；把它们算成「没中」正是让两段看起来一模一样的做法。）"
                 "<b>而方向是成段走的，不是逐年抖动：</b>"
                 f"FY{run_above[0]} 到 FY{run_above[-1]} 连续 {len(run_above)} 年高于区间，"
                 f"FY{run_none[0]} 到 FY{run_none[-1]} 的 {len(run_none)} 年里一次都没有高过。"
                 "<b>第二根柱只有近十二年有：</b>10-Q 里的季度修订本页只回溯到 "
                 f"FY{full['final_vintage_from_fiscal_year']}，更早的年度没有采集，"
                 "所以左边那一段只有年初计划这一条腿。"
                 f"在两条腿都有的那 {len(both)} 年里，修订把平均绝对偏离从 "
                 f"{sum(open_abs_both) / len(open_abs_both):.1f}% 收到 "
                 f"{sum(final_abs_both) / len(final_abs_both):.1f}%，只压掉不到一半 —— "
                 "本站另外两页按年指引的公司（穆迪、标普全球）同一口径下能压到五分之一甚至七分之一。"
                 f"（整段三十年对年初计划的平均绝对偏离是 "
                 f"{sum(open_abs_all) / len(open_abs_all):.1f}%，与上面那个数不是同一批年份，不要并排比。）"
                 f"整段记录里偏离最大的一次是 "
                 f"{full_labels[dev_open.index(biggest)]} 的 {biggest:+.1f}%。"
                 + CAPEX_LAG_NOTE),
        "src_extra": (CAPEX_SOURCE
                      + "FY1995 至 FY2012 取自同一段落更早的版本，"
                      "标题在那些年份是 Expansion Plans 或没有小标题；"
                      "FY2007 之前的计划为美加与国际两笔之和（D）。"
                      "当年最后一版取自该财年第三季 10-Q；"
                      "偏离 = 实际值 ÷ 计划区间中点 − 1，为本页自算（D）。"),
    }

    rows = []
    for i, label in enumerate(labels):
        if record["is_qualitative"][i]:
            guided = "「a similar amount」（无数字）"
        elif low[i] is None:
            guided = "—"
        else:
            guided = f"${low[i]:,.0f}–{high[i]:,.0f}M"
        final_low = record["final_10q_low_usd_m"][i]
        final_high = record["final_10q_high_usd_m"][i]
        if final_low is None:
            final = "—"
        elif final_low == final_high:
            final = f"${final_low:,.0f}M（单点）"
        else:
            final = f"${final_low:,.0f}–{final_high:,.0f}M"
        rows.append([label, record["guidance_filed_on"][i],
                     f"{record['lag_days_into_guided_year'][i]} 天"
                     if record["lag_days_into_guided_year"][i] is not None else "—",
                     guided, final,
                     f"${actual[i]:,.0f}M" if actual[i] is not None else "待披露",
                     record["verdict_vs_opening"][i] or "—",
                     record["verdict_vs_final"][i] or "—"])
    table = {
        "title": "资本开支：年初计划、当年最后一版计划、实际支出与两次判定",
        "headers": ["被指引的财年", "年初计划公布日", "公布时该财年已过", "年初计划区间",
                    "当年最后一版", "实际资本开支", "对年初版", "对最后一版"],
        "rows": rows,
    }
    return [band, dev], table


def warehouse_plan_chart(staging: dict) -> dict:
    """The opening plan against what opened -- one quantity, four wordings.

    This is the least tidy of the three records in this section and the page
    keeps the untidiness on the chart rather than resolving it.  The number
    itself is comparable throughout -- total warehouses planned to open against
    total opened -- but the *qualifier* moved four times (a range, then "up to",
    then "approximately", then "approximately up to", then "up to" again), and
    the relocation clause flipped between naming relocations as a subset of the
    plan and as an addition to it.  Where they are an addition the comparable
    plan is N + M, which is how the series is built.

    The two earliest guided years are left out entirely: their plan is a range
    rather than a number, and the fiscal 2012 opening figure is stated once as
    net-new and once as gross-new, so neither leg is on one basis.
    """
    plan = staging["warehouse_plan"]
    labels = [f"FY{year}" for year in plan["guided_fiscal_years"]]
    planned = plan["planned_total"]
    opened = plan["actual_total_openings"]
    finished = [i for i, value in enumerate(opened) if value is not None]
    under = [i for i in finished if opened[i] < planned[i]]
    over = [i for i in finished if opened[i] > planned[i]]
    shortfall = [planned[i] - opened[i] for i in under]
    return {
        "ref": "EX_WH_PLAN",
        "kind": "grouped_bars",
        "title": (f"计划开店数与实际开店数：{len(finished)} 个已完结年度里 {len(under)} 年没开满、"
                  f"{len(over)} 年超过，平均少开 {sum(shortfall) / len(shortfall):.1f} 家"),
        "xlabels": labels,
        "xrot": 90,
        "groups": [
            {"name": "10-K 里的开店计划（含搬迁）", "color": "GOLD", "values": planned},
            {"name": "实际开店数（含搬迁）", "color": "NAVY", "values": opened},
        ],
        "bar_labels": True,
        "fmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "家",
        "note": ("<b>与上面那份资本开支计划对照着看：钱的计划两边一样会错，店的计划几乎年年开不满。</b>"
                 f"{len(finished)} 个已完结年度里 {len(under)} 年低于计划，"
                 f"最大一次少开 {max(shortfall)} 家。"
                 "<b>但这条记录比它看上去的松，原因写在这里而不是藏起来：</b>"
                 "同一句话的限定词换过四次 —— 早年是区间（「27 到 30 家」），"
                 "后来是「up to N」，中间三年是「approximately N」，再后来是"
                 "「approximately up to N」，近年又回到「up to N」。"
                 "所以这张图比的是「计划的家数」与「实际的家数」这一个量，"
                 "不是「有没有守住一个承诺」—— 一个点估计开不满和一个上限没顶到，不是同一件事。"
                 "<b>搬迁那一项的口径也翻过面：</b>FY2016 到 FY2019 的计划把搬迁写成计划之外的"
                 "另一句（「and relocate up to M warehouses」），其余年份写成"
                 "「including M relocations」即计划之内。"
                 "本图在前一种年份把计划记为 N + M，好让两根柱子量的是同一件事。"
                 "<b>更早的年度完全不接入，而理由比「口径变了」更硬：那个被承诺的量公司从没申报过。</b>"
                 "FY2009 之前的十五份 10-K 把计划限定在<b>美国与加拿大</b>，国际开店写在后面另一句里、"
                 "不在这个数里；而公司申报的实际开店数是全球口径，区域拆分只按<b>净</b>增给。"
                 "所以「美加的毛新开」这个量在任何一年都没有被申报过 —— "
                 "拿全球数去对美加计划，会把其中六年的判定翻面，还有两年（FY2000、FY2001）"
                 "连方向都定不了。本页因此把那十五年整段留在外面，而不是画一条看起来连续的线。"
                 "FY2013 与 FY2014 另有原因：那两年的计划是区间而不是一个数，"
                 "而且 FY2012 的开店数在两份 10-K 里一次记作净新增、一次记作新开，两条腿都不在一个口径上。"
                 + CAPEX_LAG_NOTE),
        "src_extra": ("与资本开支计划取自各年 10-K 的同一段；"
                      "实际开店数取自被指引那一年自己那份 10-K 的同一句话，"
                      "计划口径统一为「含搬迁的开店总数」，为本页自算（D）。"),
    }


DECK_SOURCE = (
    "取自各季业绩 8-K 的 EX-99.2「Supplemental Information」补充材料。"
    "这份材料自 2024-05-30（FY2024 Q3 业绩）起随每份业绩 8-K 一并 furnish，共 9 期，"
    "在此之前这些数字只在电话会上口头给出，因此本页的这条序列从那一季开始，不向前回补。"
)


def build_payload(staging: dict) -> dict:
    fin = staging["financials"]
    comp = staging["comparable_sales_pct"]
    hist = staging["comp_history_pct"]
    bridge = staging["eps_growth_bridge_pct"]
    seg = staging["segments_usd_m"]
    cats = staging["merchandise_categories"]
    mem = staging["membership"]
    bal = staging["balance_sheet_usd_m"]
    ann = staging["annual"]
    deck = staging["supplement"]
    core = staging["core_on_core"]

    labels = [compact_period(period) for period in staging["periods"]]
    hist_labels = [compact_period(period) for period in hist["periods"]]
    mem_labels = [compact_period(period) for period in mem["periods"]]
    deck_labels = [compact_period(period) for period in deck["periods"]]
    weeks = staging["weeks"]
    long_weeks = [staging["weeks_by_period"][period] for period in hist["periods"]]

    # Two hazards that have to travel with every level and every year-over-year
    # figure on this page, so they are computed once from the series rather than
    # typed as prose.
    long_quarters = [index for index, w in enumerate(weeks) if w > 12]
    mismatch = [index for index, period in enumerate(staging["periods"])
                if staging["yoy_week_mismatch"][index]]

    revenue = fin["total_revenue_usd_m"]
    net_sales = fin["net_sales_usd_m"]
    fees = fin["membership_fees_usd_m"]
    operating = fin["operating_income_usd_m"]

    capex_ex, capex_table = capex_charts(staging)
    settled_ex = list(capex_ex) + [warehouse_plan_chart(staging)]

    # ── the local thresholds carried into this quarter ──────────────────────
    prior = staging["prior_kpi"]["quantified"]
    settled_ex.append(headroom_exhibit(
        f"上季 {len(prior)} 条可结清阈值：本季实际离阈值的余量",
        prior, "actual",
        ("正值表示仍在安全侧。阈值为本地研究设定，<b>不是公司指引</b> —— "
         "Costco 唯一的数字指引是上面两张图里的资本开支与开店计划，从不指引收入或利润。"
         + staging["prior_kpi"]["excluded"]),
        "本季实际值全部取自申报文件；阈值为本地研究设定。"))

    settled_ex.append(threshold_exhibit(
        f"剔除汽油与汇率后的合并同店销售：{len(hist['periods'])} 季记录，"
        f"本季 {hist['adjusted_total_pct'][-1]:+.1f}%",
        hist_labels, rounded(hist["adjusted_total_pct"]), 6.0,
        fmt="pct1", ylab="%", actual_name="调整后合并 comp（剔除汽油与汇率）",
        threshold_name="上季阈值 +6.0%",
        note=("红线是本地研究设定的阈值，不是公司指引。"
              "<b>这条线的窗口是选出来的，理由要说清楚：</b>公司从 FY2013 起就在披露"
              "剔除汽油的口径，但 FY2019 那四个季度的「Adjusted」还额外剔除了 ASC 606 收入准则变更，"
              "是同一个标签下的另一个口径；本图因此从 FY2020 Q1 起画，"
              "此后每一季都是同一个「剔除汽油价格与汇率」的定义。"
              f"窗口内区间 {min(hist['adjusted_total_pct']):.1f}% 到 "
              f"{max(hist['adjusted_total_pct']):.1f}%，"
              "所以「结构性 6.5%」这句话描述的是最近四个季度，不是这家公司的常态。"
              + RESOLUTION_NOTE),
        src_extra=SOURCE_PR))
    settled_ex[-1]["xstep"] = LONG_STEP
    settled_ex[-1]["ref"] = "EX_ADJCOMP"

    renewal_start = mem["renewal_decimal_from_index"]
    settled_ex.append({
        "ref": "EX_RENEWAL",
        "kind": "lines",
        "title": (f"会员续费率：美加 {mem['renewal_rate_us_canada_pct'][-1]:.1f}%、"
                  f"全球 {mem['renewal_rate_worldwide_pct'][-1]:.1f}%"),
        "xlabels": mem_labels[renewal_start:],
        "series": [
            {"name": "美加续费率", "color": "NAVY",
             "values": rounded(mem["renewal_rate_us_canada_pct"][renewal_start:])},
            {"name": "全球续费率", "color": "BLUE",
             "values": rounded(mem["renewal_rate_worldwide_pct"][renewal_start:])},
            {"name": "上季阈值 92.1%（美加）", "color": "RED",
             "values": [92.1] * len(mem_labels[renewal_start:])},
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
        "ylab": "%",
        "note": ("<b>这张图为什么不从更早画起：</b>Costco 在 FY2023 Q2 之前把续费率四舍五入到"
                 "整数百分点（91%、92%、93%），之后才给到一位小数。"
                 "把两段接在一起会把四舍五入画成一段台阶式的「趋势」，"
                 "所以本图从有小数的那一季起画。"
                 "上季设下的阈值是「企稳或回升」，本页把它写成一条水平线 —— "
                 f"美加从上一季的 {mem['renewal_rate_us_canada_pct'][-2]:.1f}% 回到 "
                 f"{mem['renewal_rate_us_canada_pct'][-1]:.1f}%，阈值兑现；"
                 "但把窗口拉开看，两条线都还在自己 FY2025 高点之下。"),
        "src_extra": "各季 10-Q 与各年 10-K 的 MD&A 正文句子；公司披露值。",
    })

    # Both legs are already in millions, so the ratio is a plain division; the
    # company prints the two counts side by side and never the ratio itself.
    exec_share = [round(e / p * 100, 6) if None not in (e, p) else None
                  for e, p in zip(deck["executive_members_mm"], deck["paid_members_mm"])]
    settled_ex.append({
        "ref": "EX_EXEC",
        "kind": "bar_line_dual",
        "title": (f"Executive 会员 {deck['executive_members_mm'][-1]:.1f}MM，"
                  f"占付费会员 {exec_share[-1]:.1f}% D，销售渗透率 "
                  f"{deck['executive_sales_penetration_pct'][-1]:.1f}%"),
        "xlabels": deck_labels,
        "bar": {"name": "Executive 会员数（百万）", "color": "NAVY",
                "values": rounded(deck["executive_members_mm"])},
        "line": {"name": "Executive 销售渗透率", "color": "RED", "yfmt": "pct1",
                 "values": rounded(deck["executive_sales_penetration_pct"])},
        "fmt": "f1", "yfmt": "f1", "label_fmt": "f1",
        "ylab": "百万人", "ylab2": "销售渗透率 %",
        "note": ("上季阈值写的是「Executive 占付费会员 ≥47%」。"
                 "<b>公司从不印这个比率</b>，但它印这个比率的两个组成部分 —— "
                 "Executive 会员数与付费会员数并排放在同一张表里，所以这里的占比是两个申报值相除（D）。"
                 f"本季 {exec_share[-1]:.1f}%，阈值兑现。"
                 "红线是另一个数，别看混：<b>销售渗透率是 Executive 会员贡献的销售额占比，"
                 "不是人数占比</b>，公司直接披露它，本季 "
                 f"{deck['executive_sales_penetration_pct'][-1]:.1f}%。"
                 + DECK_SOURCE),
        "src_extra": DECK_SOURCE,
    })

    # ── section two: what actually moved this quarter ───────────────────────
    gap = hist["gap_pp"]
    negative_gaps = sum(1 for v in gap if v < 0)
    highlight_ex = [
        {
            "ref": "EX_COMPBOTH",
            "kind": "lines",
            "title": (f"报告 comp 与剔除汽油、汇率后的 comp：本季 "
                      f"{hist['reported_total_pct'][-1]:+.1f}% 对 "
                      f"{hist['adjusted_total_pct'][-1]:+.1f}%"),
            "xlabels": hist_labels,
            "series": [
                {"name": "报告合并 comp", "color": "GOLD",
                 "values": rounded(hist["reported_total_pct"])},
                {"name": "剔除汽油与汇率后", "color": "NAVY",
                 "values": rounded(hist["adjusted_total_pct"])},
            ],
            "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
            "ylab": "%", "xstep": LONG_STEP,
            "note": ("两条线都是公司披露值，差别只在剔不剔汽油价格与汇率。"
                     "<b>本季金色那条比深蓝那条高 "
                     f"{gap[-1]:.1f} 个百分点，是这 {len(gap)} 季里第 "
                     f"{sorted(gap, reverse=True).index(gap[-1]) + 1} 大的一次。</b>"
                     "读 headline 的人看到的是金色，读这家公司的人要看深蓝。"
                     "两条线在 2021–2022 年那段一起冲到两位数，是疫情后的低基数加油价，"
                     "不是需求。"
                     + RESOLUTION_NOTE),
            "src_extra": SOURCE_PR,
        },
        {
            "ref": "EX_GAP",
            "kind": "diverging_bars",
            "title": (f"汽油与汇率把 headline 抬高（或压低）了多少："
                      f"{len(gap)} 季里 {negative_gaps} 季是压低"),
            "xlabels": hist_labels,
            "values": rounded(gap),
            "legend": "报告 comp − 调整后 comp",
            "positive_label": "抬高 headline",
            "negative_label": "压低 headline",
            "fmt": "pp1", "yfmt": "pp1", "label_fmt": "pp1",
            "ylab": "百分点", "zero_line": True, "xstep": LONG_STEP,
            "note": ("<b>这张图是本页最想让人看见的一张。</b>本地笔记把本季 "
                     f"{gap[-1]:.1f} 个百分点的汽油顺风当成一次性的加成来提示风险，"
                     f"而完整记录说的是更强的一句话：这个缺口在 {len(gap)} 个季度里有 "
                     f"{negative_gaps} 季是<b>负的</b> —— "
                     "汽油与汇率压低 headline 的次数比抬高的次数还多，"
                     f"最深一次是 {hist_labels[gap.index(min(gap))]} 的 {min(gap):.1f} 个百分点。"
                     f"符号是在四个季度前才翻过来的：{hist_labels[-4]} 还是 {gap[-4]:+.1f}，"
                     f"接着 {gap[-3]:+.1f}、{gap[-2]:+.1f}、{gap[-1]:+.1f}。"
                     "<b>公司只披露汽油与汇率合在一起的影响，从不拆开</b>，"
                     "所以本页画的是合并缺口，不发布「汽油贡献 X 个百分点、汇率 Y 个百分点」"
                     "这样的拆分 —— 那个拆分只在电话会上出现过，没有可核对的申报来源。"),
            "src_extra": SOURCE_PR + "缺口为两条披露值相减，本页自算（D）。",
        },
        {
            "ref": "EX_CATS",
            "kind": "grouped_bars",
            "title": (f"四条商品线对净销售额增速的贡献：本季合计 "
                      f"{cats['net_sales_yoy_pct'][-1]:+.1f}%，其中加油站所在那条占 "
                      f"{cats['growth_contribution_pp']['warehouse_ancillary_and_other_usd_m'][-1]:.1f} 个百分点"),
            "xlabels": labels,
            "groups": [
                {"name": "食品与日用", "color": "NAVY",
                 "values": rounded(cats["growth_contribution_pp"]["foods_and_sundries_usd_m"])},
                {"name": "非食品", "color": "BLUE",
                 "values": rounded(cats["growth_contribution_pp"]["non_foods_usd_m"])},
                {"name": "生鲜", "color": "GOLD",
                 "values": rounded(cats["growth_contribution_pp"]["fresh_foods_usd_m"])},
                {"name": "仓内附属与其他（含加油站）", "color": "RED",
                 "values": rounded(
                     cats["growth_contribution_pp"]["warehouse_ancillary_and_other_usd_m"])},
            ],
            "bar_labels": True,
            "fmt": "pp1", "label_fmt": "pp1", "ylab": "百分点",
            "annot": f"{labels[mismatch[0]]}：16 周对上年 17 周" if mismatch else "",
            "note": ("四根柱相加等于当季净销售额的同比增速，是恒等式不是估计。"
                     "<b>红色那条是加油站、药房、食品部、眼镜与轮胎安装所在的「仓内附属与其他」</b>，"
                     f"本季它一条就贡献了 "
                     f"{cats['growth_contribution_pp']['warehouse_ancillary_and_other_usd_m'][-1]:.1f} "
                     f"个百分点，接近全部增量的一半，而它只占上年净销售额的 "
                     f"{cats['ancillary_share_of_base_pct'][-1]:.1f}%。"
                     "这是「汽油推高了 headline」这句话在申报文件里的样子 —— "
                     "公司不拆汽油单独的销售额，但它拆到了这条线。"
                     + (f"<b>{labels[mismatch[0]]} 那一格要打折：</b>它是 16 周的会计 Q4 "
                        "对上年 17 周的会计 Q4（FY2023 是 53 周财年），"
                        "同比因此被少算了大约一周，四根柱一起被压低。" if mismatch else "")),
            "src_extra": ("各季 10-Q 与 10-K 收入分解附注的四个商品类别；"
                          "贡献 = 该类别同比增量 ÷ 上年同期净销售额，本页自算（D）。"),
        },
        {
            "ref": "EX_EPSBRIDGE",
            "kind": "grouped_bars",
            "title": (f"每股收益增速拆成四条腿：本季 "
                      f"{bridge['reported_eps_yoy_pct'][-1]:+.1f}% 里营业利润只占 "
                      f"{bridge['operating_leg_pct'][-1]:+.1f}%"),
            "xlabels": [compact_period(period) for period in bridge["periods"]],
            "groups": [
                {"name": "营业利润腿", "color": "NAVY",
                 "values": rounded(bridge["operating_leg_pct"])},
                {"name": "营业外腿（利息与其他）", "color": "GOLD",
                 "values": rounded(bridge["below_the_line_leg_pct"])},
                {"name": "税率腿", "color": "RED",
                 "values": rounded(bridge["tax_leg_pct"])},
                {"name": "股数腿", "color": "GRAY",
                 "values": rounded(bridge["share_count_leg_pct"])},
            ],
            "bar_labels": True,
            "fmt": "pct1", "label_fmt": "pct1", "ylab": "%",
            "note": ("<b>这是恒等式，不是估计。</b>每股收益 = （营业利润 + 营业外净额）×（1 − 税率）"
                     "÷ 摊薄股数，所以同比增速精确地分解成四个相乘的因子；"
                     f"本季四条腿相乘得 {bridge['product_pct'][-1]:+.2f}%，"
                     "与用申报的净利润和摊薄股数算出的每股收益同比完全相同；"
                     f"而新闻稿印到分的 ${fin['diluted_eps_usd'][-1]:.2f} 对 "
                     f"${fin['diluted_eps_usd'][-5]:.2f} 得到 "
                     f"{pct_change(fin['diluted_eps_usd'][-1], fin['diluted_eps_usd'][-5]):+.2f}% —— "
                     "两者相差的那一点就是那两个分位的四舍五入。"
                     f"<b>本季的读法：{bridge['reported_eps_yoy_pct'][-1]:+.1f}% 里有 "
                     f"{bridge['below_the_line_leg_pct'][-1] + bridge['tax_leg_pct'][-1]:+.1f}% "
                     "来自经营之外</b> —— 利息收入（现金及短期投资 US$"
                     f"{bal['cash_and_short_term_investments_usd_m'][-1] / 1000:.1f}B）与更低的税率。"
                     "记录起点是这里而不是更早：FY2023 之前公司报表里还有少数股东权益一行，"
                     "分解需要第五条腿，两段不是同一个口径。"),
            "src_extra": ("各季业绩 8-K EX-99.1 合并损益表的营业利润、税前利润、所得税与摊薄股数；"
                          "四条腿为本页自算（D）。"),
        },
        {
            "ref": "EX_TRAFFIC",
            "kind": "lines",
            "title": (f"客流与客单：本季客流 {deck['comp_traffic_pct'][-1]:+.1f}%、"
                      f"剔除汽油与汇率后的客单 {deck['adjusted_comp_ticket_pct'][-1]:+.1f}%"),
            "xlabels": deck_labels,
            "series": [
                {"name": "同店客流（购物频次）", "color": "NAVY",
                 "values": rounded(deck["comp_traffic_pct"])},
                {"name": "同店客单（报告）", "color": "GOLD",
                 "values": rounded(deck["comp_ticket_pct"])},
                {"name": "同店客单（剔除汽油与汇率）", "color": "BLUE",
                 "values": rounded(deck["adjusted_comp_ticket_pct"])},
            ],
            "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
            "ylab": "%",
            "note": ("客流与客单是 comp 的两个乘数，公司把它们拆开给出。"
                     f"<b>本季的张力在这里：客流从 {deck['comp_traffic_pct'][-2]:+.1f}% 降到 "
                     f"{deck['comp_traffic_pct'][-1]:+.1f}%，缺口由客单补上。</b>"
                     "金色与蓝色两条客单线之间的距离就是汽油与汇率 —— 本季 "
                     f"{deck['comp_ticket_pct'][-1] - deck['adjusted_comp_ticket_pct'][-1]:.1f} "
                     "个百分点，几乎全部的客单加速都在这个缺口里。"
                     + DECK_SOURCE),
            "src_extra": DECK_SOURCE,
        },
        {
            "ref": "EX_MARGINS",
            "kind": "lines",
            "title": (f"毛利率 {fin['gross_margin_pct'][-1]:.2f}%、SG&A 率 "
                      f"{fin['sga_pct_of_net_sales'][-1]:.2f}%、营业利润率 "
                      f"{fin['operating_margin_pct'][-1]:.2f}%"),
            "xlabels": labels,
            "series": [
                {"name": "毛利率（占净销售额）", "color": "NAVY",
                 "values": rounded(fin["gross_margin_pct"])},
                {"name": "SG&A 率（占净销售额）", "color": "BLUE",
                 "values": rounded(fin["sga_pct_of_net_sales"])},
                {"name": "营业利润率（占总收入）", "color": "GOLD",
                 "values": rounded(fin["operating_margin_pct"])},
            ],
            "fmt": "pct2", "yfmt": "pct2", "label_fmt": "pct2", "end_label": True,
            "ylab": "%",
            "note": ("三条线都是从申报的美元数直接相除得来的，与公司 MD&A 印出的百分比逐季一致。"
                     "<b>比率不受周数影响</b>，所以这张图上 16 周的会计 Q4 与 12 周的其他季度可以直接比 —— "
                     "同一页上的金额柱状图不行，那里 16 周的柱子会打斜纹。"
                     "毛利率与 SG&A 率同向移动是这家公司的常态：汽油销售额同时进两个比率的分母，"
                     "油价一涨两个比率一起被稀释，所以本季毛利率 −21bp 与 SG&A 率 −20bp "
                     "几乎抵消，营业利润率只动了 "
                     f"{fin['operating_margin_pct'][-1] - fin['operating_margin_pct'][-5]:+.2f} 个百分点。"),
            "src_extra": "各季业绩 8-K EX-99.1 合并损益表；三个比率为本页自算（D）。",
        },
        {
            "ref": "EX_SEGMARGIN",
            "kind": "lines",
            "title": (f"三个地区分部的营业利润率：美国 "
                      f"{seg['united_states']['operating_margin_pct'][-1]:.2f}%、加拿大 "
                      f"{seg['canada']['operating_margin_pct'][-1]:.2f}%、其他国际 "
                      f"{seg['other_international']['operating_margin_pct'][-1]:.2f}%"),
            "xlabels": labels,
            "series": [
                {"name": "美国", "color": "NAVY",
                 "values": rounded(seg["united_states"]["operating_margin_pct"])},
                {"name": "加拿大", "color": "BLUE",
                 "values": rounded(seg["canada"]["operating_margin_pct"])},
                {"name": "其他国际", "color": "GOLD",
                 "values": rounded(seg["other_international"]["operating_margin_pct"])},
            ],
            "fmt": "pct2", "yfmt": "pct2", "label_fmt": "pct2", "end_label": True,
            "ylab": "%",
            "note": ("<b>加拿大的分部利润率长期高于美国</b>，而它只占本季总收入的 "
                     f"{seg['canada']['revenue_usd_m'][-1] / revenue[-1] * 100:.1f}%。"
                     "三个分部的收入相加等于合并总收入、营业利润相加等于合并营业利润，"
                     "八个季度逐季核对差额为零。"
                     f"<b>{'、'.join(labels[i] for i in long_quarters)} 两格是自算值（D）：</b>"
                     "会计 Q4 没有 10-Q，分部数只能用全年减去 36 周累计。"
                     "同一个减法在合并层面得到的净销售额与营业利润，与 Q4 业绩稿印出的 16 周数逐项相同，"
                     "这是本页愿意用它做分部的理由。"),
            "src_extra": ("各季 10-Q 与 10-K 分部附注；分部利润率为分部营业利润除以分部总收入，"
                          "本页自算（D）。"),
        },
    ]

    # ── section three: what to watch next ───────────────────────────────────
    next_kpi = staging["next_kpi"]["quantified"]
    core_labels = [compact_period(period) for period in core["periods"]]
    core_bps = core["change_bps"]
    # A fiscal fourth quarter has no 10-Q sentence, but the supplemental deck
    # prints one from FY2024 Q3 on, so some of the annual holes are filled and
    # some are not. Count both rather than describing the axis from memory.
    q4_slots = sum(1 for period in core["periods"] if period.startswith("Q3 "))
    deck_filled = sum(1 for period, source in zip(core["periods"], core["value_source"])
                      if period.startswith("Q3 ") and source)
    filed_core = [v for v in core_bps if v is not None]
    negative_core = sum(1 for v in filed_core if v < 0)
    est = staging["warehouse_estimate"]
    # One line per settled fiscal year, taking that year's LAST vintage: the
    # earlier ones were off by a warehouse or two and the point is that the
    # final revision lands exactly.
    final_estimate = {}
    for year, estimate, actual in zip(est["target_fiscal_year"], est["fy_end_estimate"],
                                      est["actual_fy_end"]):
        if actual is not None:
            final_estimate[year] = (estimate, actual)
    settled_estimates = [f"FY{year} 最后估 {estimate} 家、实际 {actual} 家"
                         for year, (estimate, actual) in sorted(final_estimate.items())]
    special = staging["special_dividends"]
    special_index = [bal["periods"].index(period) for period in special["paid_in_periods"]
                     if period in bal["periods"]]
    cash = bal["cash_and_short_term_investments_usd_m"]

    next_ex = [
        headroom_exhibit(
            f"下季 {len(next_kpi)} 条阈值：当前值离阈值的余量",
            next_kpi, "current",
            ("正值表示仍在安全侧。阈值为本地研究设定，<b>不是公司指引</b>。"
             + staging["next_kpi"]["excluded"]),
            "当前值为 2026Q2 申报值或其自算比率；阈值为本地研究设定。"),
        {
            "ref": "EX_CORECORE",
            "kind": "diverging_bars",
            "title": (f"核心商品在核心商品销售额上的毛利率变动：本季 {core_bps[-1]:+.0f}bp，"
                      f"{len(filed_core)} 个有披露的季度里 {negative_core} 季为负"),
            "xlabels": core_labels,
            "values": core_bps,
            "legend": "同比变动（基点）",
            "positive_label": "改善",
            "negative_label": "恶化",
            "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
            "ylab": "基点", "zero_line": True, "xstep": LONG_STEP,
            "note": ("<b>这就是管理层在电话会上说的「core on core」，只不过是申报版本。</b>"
                     "10-Q 的 MD&A 每季用同一句话给它："
                     "「The gross margin in core merchandise categories, when expressed as a "
                     "percentage of core merchandise sales (rather than total net sales), "
                     "decreased nine basis points.」"
                     "它把仓内附属与其他业务的销售占比变化和它们自己的毛利率都排除掉，"
                     "所以它是这家公司剔除汽油之后最干净的一条商品毛利率读数。"
                     "<b>轴上的空格是会计 Q4</b>：它没有 10-Q，而 10-K 讲的是整个财年，"
                     "从不单说第四季度；本页不用「全年减去 36 周」去补那一格，"
                     "因为那样得到的是自算值而不是披露值。"
                     f"<b>但最后 {deck_filled} 个会计 Q4 是有值的</b> —— 自 FY2024 Q3 起的 "
                     "EX-99.2 补充材料按季给这个数，第四季度也给，所以窗口里 "
                     f"{q4_slots} 个会计 Q4 有 {deck_filled} 个由它填上、其余 "
                     f"{q4_slots - deck_filled} 个仍是空的。"
                     "这两格的来源比其余的弱，值得说明：补充材料只印「Core on Core Sales」这一行，"
                     "既不定义它，也不说它属于毛利率还是 SG&A 那张桥；而 10-Q 的那句话自带定义。"
                     "两者在九个重叠季度里逐季相同，这是本页愿意用它补那两格的理由。"
                     "上季阈值是「回正或 ≥0」，本季 "
                     f"{core_bps[-1]:+.0f}bp，未兑现；"
                     "下季阈值是「不要连续两季 ≤−10bp」。"),
            "src_extra": ("各季 10-Q 的 MD&A 正文句子；数值为公司披露的基点变动，"
                          "自 FY2024 Q3 起同一个数字也出现在业绩 8-K 的 EX-99.2 里，两者逐季一致。"),
        },
        {
            "ref": "EX_WH_EST",
            "kind": "grouped_bars",
            "title": (f"公司自己估的财年末仓库数：两个已完结财年都精确落在最后一次估计上，"
                      f"本季估 FY{est['target_fiscal_year'][-1]} 年末 "
                      f"{est['fy_end_estimate'][-1]} 家"),
            "xlabels": [f"{compact_period(period)}→FY{str(year)[-2:]}"
                        for period, year in zip(est["periods"], est["target_fiscal_year"])],
            "xrot": 90,
            "groups": [
                {"name": "该期估计的财年末仓库数", "color": "BLUE",
                 "values": est["fy_end_estimate"]},
                {"name": "该财年实际末仓库数", "color": "NAVY",
                 "values": est["actual_fy_end"]},
            ],
            "bar_labels": True,
            "fmt": "f0c", "label_fmt": "f0c", "ylab": "家",
            "note": ("<b>这是 Costco 唯一一份按季修订的数字指引，而它指的是店的数量、不是钱。</b>"
                     "自 2024-05-30 起，每份业绩 8-K 的 EX-99.2 都印一张仓库扩张表："
                     "上一财年末的家数、本财年已开的每一季、剩余年度的估计，以及财年末的估计合计。"
                     "横轴标注的是「哪一期估计 → 估的是哪个财年」，"
                     "所以同一个财年会被连着估好几次，可以看见它怎么收敛。"
                     "会计第四季那两份材料的估计列指向的是<b>下一个</b>财年，"
                     "当年年末那一格在那里已经是实际数 —— 横轴的标注按每份材料自己写的目标财年，"
                     "不按它发布的季度。"
                     "<b>把这张图和第一节那两张放在一起，就是这家公司预测能力的两面：</b>"
                     "已完结的两个财年里，仓库数的<b>最后一次</b>估计与实际一个不差（"
                     + "；".join(settled_estimates)
                     + "），而同期的资本开支计划每年都差 5% 到 15%。"
                     "店的数量是它自己排的工期，花掉的钱不是。"
                     + DECK_SOURCE),
            "src_extra": DECK_SOURCE + "实际财年末家数取自各年 10-K。",
        },
        {
            "ref": "EX_CASH",
            "kind": "bars_labeled",
            "title": (f"现金及短期投资：本季末 US${cash[-1] / 1000:.1f}B，"
                      f"已高于上一次宣布特别股息时的 US${special['cash_before_last_special_usd_m'] / 1000:.1f}B"),
            "xlabels": [compact_period(period) for period in bal["periods"]],
            "values": rounded(cash),
            "fmt": "f0c", "label_fmt": "f0c", "ylab": "US$M", "xstep": LONG_STEP,
            "bar_marks": special_index,
            "mark_note": "该季支付了特别股息",
            "note": ("斜纹柱是支付了特别股息的季度。"
                     "Costco 一共派过五次特别股息 —— "
                     + "、".join(f"{d['fiscal_year']} 年每股 US${d['per_share']:.0f}"
                                 for d in special["all"])
                     + " —— 平均间隔约三年，最近一次是 2024 年 1 月的每股 US$15、"
                     f"合计 US${special['last_total_usd_m']:,.0f}M。"
                     "<b>阈值不是「现金越多越好」而是相反：</b>"
                     "上一次宣布特别股息的前一个季度末，现金及短期投资是 US$"
                     f"{special['cash_before_last_special_usd_m'] / 1000:.1f}B；"
                     f"本季已经是 US${cash[-1] / 1000:.1f}B，也就是说按上一次的标准，"
                     "现金已经攒过了那条线。这不是预测公司会宣布什么，"
                     "只是把「闲置现金」这个判断放到它自己的历史刻度上。"
                     "本页不发布特别股息的时点预期。"),
            "src_extra": ("各季业绩 8-K EX-99.1 的合并资产负债表（现金及等价物加短期投资）；"
                          "特别股息的宣告日、每股金额与合计支付额取自各次宣告的 8-K 与当年 10-K。"),
        },
    ]

    # ── section four: the long routine ─────────────────────────────────────
    fy_labels = ann["fiscal_years"]
    merch_leg = ann["merchandising_leg_pct_of_net_sales"]
    memb_leg = ann["membership_leg_pct_of_net_sales"]
    share = ann["membership_fee_share_of_operating_income_pct"]
    fee_per_member = mem["annualised_fee_per_paid_member_usd"]
    routine_ex = [
        {
            "ref": "EX_TWOLEGS",
            "kind": "grouped_bars",
            "title": (f"营业利润率的两条腿：会员费从 {memb_leg[0]:.2f} 个百分点降到 "
                      f"{memb_leg[-1]:.2f}，商品从 {merch_leg[0]:.2f} 升到 {merch_leg[-1]:.2f}"),
            "xlabels": fy_labels,
            "groups": [
                {"name": "商品腿（毛利率 − SG&A 率 − 开办费率）", "color": "NAVY",
                 "values": rounded(merch_leg)},
                {"name": "会员费腿（会员费 ÷ 净销售额）", "color": "GOLD",
                 "values": rounded(memb_leg)},
            ],
            "bar_labels": True,
            "fmt": "pct2", "label_fmt": "pct2", "ylab": "占净销售额 %",
            "note": ("<b>这张图是这家公司最常被引用的那句话的申报版本。</b>"
                     "「Costco 靠会员费赚钱、商品基本按成本卖」——"
                     "这句话在 FY2013 是对的：营业利润率 "
                     f"{ann['operating_margin_on_net_sales_pct'][0]:.2f}% 里，"
                     f"会员费贡献 {memb_leg[0]:.2f} 个百分点，商品只贡献 {merch_leg[0]:.2f}。"
                     f"到 FY2025 变成 {memb_leg[-1]:.2f} 对 {merch_leg[-1]:.2f}，"
                     f"两条腿只差 {memb_leg[-1] - merch_leg[-1]:.2f} 个百分点，"
                     "十三年来第一次快要交叉。"
                     "换成占营业利润的比重说同一件事："
                     f"会员费从 {share[0]:.1f}% 降到 {share[-1]:.1f}%。"
                     "<b>这是恒等式：</b>商品腿 + 会员费腿 = 营业利润 ÷ 净销售额，"
                     "十三个年度逐年核对差额为零。"
                     "会员费在这段时间涨过两次价（2017 年 6 月、2024 年 9 月），"
                     "占比仍然在降 —— 不是会员费不行了，是商品那条腿长得更快。"),
            "src_extra": ("各年 10-K 合并损益表；两条腿均为申报值相除，本页自算（D）。"),
        },
        {
            "ref": "EX_LONGMARGIN",
            "kind": "lines",
            "title": (f"十三年毛利率与 SG&A 率：毛利率 {ann['gross_margin_pct'][0]:.2f}% → "
                      f"{ann['gross_margin_pct'][-1]:.2f}%，SG&A 率 "
                      f"{ann['sga_pct_of_net_sales'][0]:.2f}% → {ann['sga_pct_of_net_sales'][-1]:.2f}%"),
            "xlabels": fy_labels,
            "series": [
                {"name": "毛利率（占净销售额）", "color": "NAVY",
                 "values": rounded(ann["gross_margin_pct"])},
                {"name": "SG&A 率（占净销售额）", "color": "BLUE",
                 "values": rounded(ann["sga_pct_of_net_sales"])},
                {"name": "营业利润率（占净销售额）", "color": "GOLD",
                 "values": rounded(ann["operating_margin_on_net_sales_pct"])},
            ],
            "fmt": "pct2", "yfmt": "pct2", "label_fmt": "pct2", "end_label": True,
            "ylab": "%",
            "note": ("上一张图问「利润从哪来」，这一张问「商品那条腿是怎么长出来的」。"
                     "答案是两头都出了力，但不是同时："
                     f"毛利率十三年只动了 {ann['gross_margin_pct'][-1] - ann['gross_margin_pct'][0]:+.2f} "
                     f"个百分点，SG&A 率动了 "
                     f"{ann['sga_pct_of_net_sales'][-1] - ann['sga_pct_of_net_sales'][0]:+.2f}。"
                     "<b>FY2022 那一格是油价，不是经营</b>：那一年毛利率与 SG&A 率一起掉到窗口最低，"
                     "因为汽油销售额把两个比率的分母同时撑大了，营业利润率反而是当时的高点。"
                     "这也是为什么本页在第三节要单独画一条剔除仓内附属业务的核心商品毛利率。"
                     "FY2017 与 FY2023 是 53 周财年，多一周的销售额被摊进全年比率里，影响在小数点后两位。"),
            "src_extra": "各年 10-K 合并损益表；三个比率均为本页自算（D），与 MD&A 印出的百分比一致。",
        },
        {
            "ref": "EX_FEEPM",
            "kind": "lines",
            "title": (f"每位付费会员的年化会员费：US${fee_per_member[0]:.2f} → "
                      f"US${fee_per_member[-1]:.2f}"),
            "xlabels": mem_labels,
            "series": [{"name": "年化会员费 ÷ 付费会员数 D", "color": "NAVY",
                        "values": fee_per_member}],
            "fmt": "f2", "yfmt": "f2", "label_fmt": "f2", "end_label": True,
            "ylab": "US$/年", "xstep": LONG_STEP,
            "break_at": mem["fee_increase_index"],
            "break_label": "2024-09-01 会员费上调",
            "note": ("会员费收入按季确认、按周折算成一年，再除以期末付费会员数 —— "
                     "两个都是申报值，比率是本页自算（D）。"
                     "<b>先看断点左边：五年多几乎是一条平线</b>，说明在没有涨价的年份里，"
                     "会员结构变化对每位会员实际交的钱影响很小。"
                     "断点右边是 2024 年 9 月那次涨价（美加 Gold Star US$60 → US$65、"
                     "Executive US$120 → US$130）："
                     f"这条线从 US${fee_per_member[mem['fee_increase_index'] - 1]:.2f} 一路走到 "
                     f"US${fee_per_member[-1]:.2f}，连涨七个季度还没走完。"
                     "这正是会员费递延确认的样子 —— 涨价按会员各自的续费日分批进入收入，"
                     "要两年左右才吃满，所以它是一条<b>还没结束的</b>顺风。"
                     "按周折算是必须的：会计 Q4 长 16 周，不折算的话每年第三季会凭空高出三分之一。"),
            "src_extra": ("会员费收入取自各季业绩 8-K EX-99.1 合并损益表的 12 周／16 周栏；"
                          "付费会员数取自各季 10-Q 与各年 10-K 的 MD&A。"),
        },
        {
            "ref": "EX_WH_LONG",
            "kind": "bar_line_dual",
            "title": (f"十三年仓库数与单仓销售额：{ann['warehouses_at_year_end'][0]:,} 家 → "
                      f"{ann['warehouses_at_year_end'][-1]:,} 家，单仓 US${ann['sales_per_warehouse_usd_m'][0]:.0f}M → "
                      f"US${ann['sales_per_warehouse_usd_m'][-1]:.0f}M"),
            "xlabels": fy_labels,
            "bar": {"name": "财年末仓库数", "color": "BLUE",
                    "values": ann["warehouses_at_year_end"]},
            "line": {"name": "单仓年销售额（US$M）D", "color": "NAVY", "yfmt": "f0c",
                     "values": ann["sales_per_warehouse_usd_m"]},
            "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
            "ylab": "家", "ylab2": "单仓年销售额 US$M",
            "note": ("十三年门店数增加 "
                     f"{ann['warehouses_at_year_end'][-1] - ann['warehouses_at_year_end'][0]:,} 家、"
                     f"年化 "
                     f"{((ann['warehouses_at_year_end'][-1] / ann['warehouses_at_year_end'][0]) ** (1 / (len(fy_labels) - 1)) - 1) * 100:.1f}%，"
                     "而单仓销售额同期增加 "
                     f"{(ann['sales_per_warehouse_usd_m'][-1] / ann['sales_per_warehouse_usd_m'][0] - 1) * 100:.0f}%。"
                     "<b>两个乘数里，长得快的是后者。</b>这也是为什么开店计划开不满对这家公司的"
                     "影响，比对一家靠铺店增长的零售商要小。"
                     "单仓销售额是净销售额除以财年末仓库数，没有对开店时点做加权，"
                     "所以在开店多的年份会被略微低估；这是一个刻意保留的粗口径，"
                     "公司不披露可用来加权的月度开店时点。"),
            "src_extra": "各年 10-K；单仓销售额为净销售额 ÷ 财年末仓库数，本页自算（D）。",
        },
        {
            "ref": "EX_CAPITAL",
            "kind": "grouped_bars",
            "title": (f"十三年经营现金流、资本开支与股东回报：FY2025 分别为 US$"
                      f"{ann['operating_cash_flow_usd_m'][-1] / 1000:.1f}B、US$"
                      f"{ann['capex_usd_m'][-1] / 1000:.1f}B 与 US$"
                      f"{(ann['buybacks_usd_m'][-1] + ann['dividends_paid_usd_m'][-1]) / 1000:.1f}B"),
            "xlabels": fy_labels,
            "groups": [
                {"name": "经营现金流", "color": "NAVY",
                 "values": ann["operating_cash_flow_usd_m"]},
                {"name": "资本开支", "color": "BLUE",
                 "values": ann["capex_usd_m"]},
                {"name": "回购 + 分红（含特别股息）", "color": "GOLD",
                 "values": [b + d for b, d in zip(ann["buybacks_usd_m"],
                                                  ann["dividends_paid_usd_m"])]},
            ],
            "fmt": "f0c", "label_fmt": "f0c", "bar_labels": False, "ylab": "US$M",
            "note": ("金色柱的高低几乎全由特别股息决定："
                     + "、".join(f"FY{d['fiscal_year']}" for d in special["all"]
                                 if f"FY{d['fiscal_year']}" in fy_labels)
                     + " 那几年凸出来的部分就是它，其余年份基本是常规分红加防稀释回购。"
                     "<b>Costco 的回购小得不像一家这个规模的公司</b>："
                     f"十三年累计回购 US${sum(ann['buybacks_usd_m']) / 1000:.1f}B，"
                     f"只有同期经营现金流 US${sum(ann['operating_cash_flow_usd_m']) / 1000:.0f}B 的 "
                     f"{sum(ann['buybacks_usd_m']) / sum(ann['operating_cash_flow_usd_m']) * 100:.1f}%。"
                     "这家公司把超额现金攒起来、隔几年一次性派掉，而不是逐年买回股票 —— "
                     "所以现金余额本身就是资本配置的跟踪指标，见第三节那张图。"
                     "资本开支占总收入的比重十三年从 "
                     f"{ann['capex_intensity_pct'][0]:.2f}% 到 {ann['capex_intensity_pct'][-1]:.2f}%，"
                     "始终在 2% 附近 —— 一家把钱主要花在盖仓库上的零售商，资本强度比本站任何一家云厂都低一个数量级。"),
            "src_extra": "各年 10-K 现金流量表，申报值；分红含特别股息。",
        },
    ]

    number_exhibits(settled_ex, start=1)
    number_exhibits(highlight_ex, start=settled_ex[-1]["n"] + 1)
    number_exhibits(next_ex, start=highlight_ex[-1]["n"] + 1)
    number_exhibits(routine_ex, start=next_ex[-1]["n"] + 1)
    resolve_exhibit_refs(settled_ex + highlight_ex + next_ex + routine_ex)

    first_table = routine_ex[-1]["n"] + 1
    core_rows = []
    for index, period in enumerate(staging["periods"]):
        core_rows.append([
            period,
            staging["fiscal_labels"][index],
            staging["period_ends"][index],
            f"{weeks[index]} 周",
            f"${net_sales[index]:,.0f}M",
            f"${fees[index]:,.0f}M",
            f"${revenue[index]:,.0f}M",
            (f"{fin['total_revenue_yoy_pct'][index]:+.1f}%"
             if fin["total_revenue_yoy_pct"][index] is not None else "—"),
            f"{comp['reported_total_pct'][index]:+.1f}%",
            f"{comp['adjusted_total_pct'][index]:+.1f}%",
            f"{fin['gross_margin_pct'][index]:.2f}%",
            f"{fin['sga_pct_of_net_sales'][index]:.2f}%",
            f"${operating[index]:,.0f}M",
            f"${fin['diluted_eps_usd'][index]:.2f}",
            f"{mem['warehouses_at_period_end'][mem['periods'].index(period)]:,}",
        ])
    comp_rows = []
    for index, period in enumerate(hist["periods"]):
        comp_rows.append([
            period,
            hist["fiscal_labels"][index],
            f"{long_weeks[index]} 周",
            f"{hist['reported_total_pct'][index]:+.1f}%",
            f"{hist['adjusted_total_pct'][index]:+.1f}%",
            f"{hist['gap_pp'][index]:+.1f}pp",
            (f"{hist['digital_reported_pct'][index]:+.1f}%"
             if hist["digital_reported_pct"][index] is not None else "—"),
            hist["digital_metric_name"][index] or "—",
        ])
    annual_rows = []
    for index, year in enumerate(fy_labels):
        annual_rows.append([
            year,
            ann["year_ends"][index],
            f"{ann['weeks'][index]} 周",
            f"${ann['total_revenue_usd_m'][index]:,.0f}M",
            f"${ann['membership_fees_usd_m'][index]:,.0f}M",
            f"${ann['operating_income_usd_m'][index]:,.0f}M",
            f"{share[index]:.1f}%",
            f"{merch_leg[index]:.2f}%",
            f"{memb_leg[index]:.2f}%",
            f"${ann['capex_usd_m'][index]:,.0f}M",
            f"${ann['operating_cash_flow_usd_m'][index]:,.0f}M",
            f"{ann['warehouses_at_year_end'][index]:,}",
            (f"${ann['special_dividend_per_share_usd'][index]:.2f}"
             if ann["special_dividend_per_share_usd"][index] else "—"),
        ])
    boundary_rows = [[item["metric"], item["verdict"], item["where"], item["window"]]
                     for item in staging["disclosure_boundary"]]
    plan = staging["warehouse_plan"]
    plan_rows = []
    for index, year in enumerate(plan["guided_fiscal_years"]):
        opened = plan["actual_total_openings"][index]
        planned = plan["planned_total"][index]
        plan_rows.append([
            f"FY{year}",
            plan["planned_qualifier"][index],
            f"{plan['planned_as_stated'][index]} 家",
            ("另计" if plan["relocations_are_additional"][index] else "含在计划内")
            + (f" {plan['planned_relocations'][index]} 家"
               if plan["planned_relocations"][index] is not None else ""),
            f"{planned} 家",
            f"{opened} 家" if opened is not None else "待披露",
            ("待披露" if opened is None else
             "少开" if opened < planned else
             "超过" if opened > planned else "正好"),
        ])
    closure_rows = [[item["question"], item["evidence"], item["verdict"]]
                    for item in staging["followup_closure"]]

    tables = [
        {**capex_table, "n": first_table},
        threshold_table(first_table + 1, "上季阈值核对（原始单位）", prior, "actual", "本季实际"),
        threshold_table(first_table + 2, "下季阈值（原始单位）", next_kpi, "current", "当前值"),
        {
            "n": first_table + 3,
            "title": "上季七条待验证问题的结清情况",
            "headers": ["上季问题", "本季申报证据", "判定"],
            "rows": closure_rows,
        },
        {
            "n": first_table + 4,
            "title": "八季核心（自然年季度标注；公司财季与周数见第二、四列）",
            "headers": ["自然年季度", "公司财季", "季末", "周数", "净销售额", "会员费",
                        "总收入", "总收入同比", "报告 comp", "调整后 comp",
                        "毛利率", "SG&A 率", "营业利润", "摊薄 EPS", "季末仓库数"],
            "rows": core_rows,
        },
        {
            "n": first_table + 5,
            "title": "同店销售完整记录（新闻稿一位小数版；10-Q 的整数版见说明）",
            "headers": ["自然年季度", "公司财季", "周数", "报告 comp", "调整后 comp",
                        "缺口 D", "数字化 comp", "数字化口径"],
            "rows": comp_rows,
        },
        {
            "n": first_table + 6,
            "title": "十三年年度记录（各年取该年 10-K 印出的数）",
            "headers": ["财年", "财年末", "周数", "总收入", "会员费", "营业利润",
                        "会员费占营业利润 D", "商品腿 D", "会员费腿 D",
                        "资本开支", "经营现金流", "财年末仓库数", "特别股息／股"],
            "rows": annual_rows,
        },
        {
            "n": first_table + 7,
            "title": "开店计划的限定词变迁与逐年结清",
            "headers": ["被指引的财年", "计划原文的限定词", "计划家数", "搬迁口径",
                        "计划合计 D", "实际开店数", "判定"],
            "rows": plan_rows,
        },
        {
            "n": first_table + 8,
            "title": "口径边界：哪些指标进了申报文件，哪些只在电话会上",
            "headers": ["指标", "是否进入申报文件", "在哪份文件里", "可用窗口"],
            "rows": boundary_rows,
        },
        ai_capex_cycle_table(first_table + 9),
    ]

    latest_gap = hist["gap_pp"][-1]
    reported = hist["reported_total_pct"]
    higher = [i for i, value in enumerate(reported[:-1]) if value > reported[-1]]
    quarters_since_higher = len(reported) - 1 - max(higher) if higher else len(reported)
    return {
        "schema_version": "quarterly-dashboard/cost-v1",
        "page": {"slug": "cost", "language": "zh-CN"},
        "company": {
            "ticker": "COST",
            "name": "Costco Wholesale Corporation",
            "group": "consumer_retail",
            "accounting_standard": "US GAAP",
        },
        "latest": {
            "disclosed_period_label": staging["latest"]["period"],
            "full_financial_period_label": staging["latest"]["period"],
            "period_end": staging["latest"]["period_end"],
            "release_date": staging["latest"]["release_date"],
            "analysis_date": "2026-08-29",
            "audit_status": "unaudited",
            "status": "history_ready",
        },
        "tracker": "Watchlist Quarterly Tracker · COST",
        "title": "Costco Wholesale Corporation (COST)：Q2 2026 季报仪表盘",
        "subtitle": (
            f"十二周截至 {staging['latest']['period_end']} · 发布 "
            f"{staging['latest']['release_date']} · US GAAP · 未审计 · "
            "财年末为最接近 8 月 31 日的星期日，本站按自然年季度标注：本页 Q2 2026 即公司所称 FY2026 Q3"
        ),
        "headline": (
            f"总收入 US${revenue[-1]:,.0f}M、同比 {signed(fin['total_revenue_yoy_pct'][-1])}，"
            f"报告 comp {signed(hist['reported_total_pct'][-1])} 是 {quarters_since_higher} "
            f"个季度以来最高；但公司自己披露的剔除汽油与汇率后的 comp 是 "
            f"{signed(hist['adjusted_total_pct'][-1])}，两者 {latest_gap:.1f} 个百分点的缺口"
            f"在这 {len(gap)} 季里有 {negative_gaps} 季是负的，四个季度前还是 {gap[-4]:+.1f}；"
            f"同一季每股收益 {signed(bridge['reported_eps_yoy_pct'][-1])} 对营业利润 "
            f"{signed(fin['operating_income_yoy_pct'][-1])}。两端的加成都能用申报值原样剥掉。"
        ),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>记录</span><b>公司只指引要花多少钱，不指引要赚多少</b>'
            f'<p>10-K 每年给一次下一财年的资本开支区间。'
            f'已完结的 {len([i for i, a in enumerate(staging["capex_guidance"]["actual_capex_usd_m"]) if a is not None and staging["capex_guidance"]["guided_low_usd_m"][i] is not None])} 年里'
            '低于下限与高于上限的次数几乎相同 —— 全站唯一一份两边都会错的指引记录。</p></article>'
            '<article><span>裂口</span><b>headline 两端都被垫高了</b>'
            f'<p>报告 comp 比调整后高 {latest_gap:.1f} 个百分点；'
            f'每股收益增速里有 {bridge["below_the_line_leg_pct"][-1] + bridge["tax_leg_pct"][-1]:+.1f}% '
            '来自利息收入与税率。两者都是申报值可复算的。</p></article>'
            '<article><span>长期</span><b>「靠会员费赚钱」这句话在变弱</b>'
            f'<p>会员费占营业利润从 {share[0]:.1f}% 降到 {share[-1]:.1f}%；'
            f'商品腿与会员费腿只差 {memb_leg[-1] - merch_leg[-1]:.2f} 个百分点，十三年来最近。</p></article>'
            '</div>'
        ),
        "source": (
            'Source: <a href="https://www.sec.gov/Archives/edgar/data/909832/'
            '000090983226000046/costex9918-k52826.htm" rel="noopener">Costco FY2026 Q3 '
            '业绩新闻稿（8-K EX-99.1）</a>、同一份 8-K 的 EX-99.2 补充材料，'
            '与截至 2026-05-10 的 10-Q。'
        ),
        "source_url": (
            "https://www.sec.gov/Archives/edgar/data/909832/"
            "000090983226000046/costex9918-k52826.htm"
        ),
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {
                "id": "settled",
                "title": "一、上季兑现与公司自己的指引记录",
                "description": (
                    "Costco 从不指引收入、利润或每股收益 —— 翻遍近十二份业绩 8-K，"
                    "outlook 与 guidance 这两个词只出现在前瞻性陈述的免责声明里。"
                    "但它确实在申报文件里给数字：10-K 每年给一次下一财年的资本开支区间与开店计划上限，"
                    "而自 2024 年 5 月起每季的 EX-99.2 还给一次财年末仓库数的估计。"
                    "所以这一节先结清公司自己那份「只关于资本」的指引，再结清上一份笔记留下的阈值。"
                ),
                "exhibits": settled_ex,
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": (
                    "headline 的两端各被垫高了一次，而两次垫高都能用申报值原样剥掉："
                    "comp 那端是汽油与汇率，每股收益那端是利息收入与税率。"
                    "剥完之后剩下的是客流在走软、客单在补位，以及四条商品线里"
                    "加油站所在的那一条贡献了接近一半的销售增量。"
                ),
                "exhibits": highlight_ex,
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": (
                    "当前值离下季阈值还有多远，统一用「距阈值余量」口径；"
                    "不接入的几条也写在这里。"
                ),
                "exhibits": next_ex,
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": (
                    "Costco 专属的常规序列：营业利润率的两条腿如何在十三年里换位、"
                    "毛利率与 SG&A 率各走了多远、一次涨价要花多久才吃满，"
                    "以及一家资本强度只有 2% 的零售商怎么处理它攒下来的现金。"
                ),
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": staging["notes"],
        "footer": "Costco quarterly results · 数据来自 Costco 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "cost.js"), payload, "cost")
    shell_dir = ROOT / "cost"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("COST", "cost"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(
        f"COST page: {charts} charts in {len(payload['sections'])} sections "
        f"+ {len(payload['tables'])} audit tables"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
