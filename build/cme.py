"""CME Group Inc. quarterly dashboard.

Three things about this filer decide what the page can be.

**The number the market models is not in any filing.** Every quarter the sell
side builds CME's cost line off a full-year "adjusted operating expense
excluding license fees" figure. That number is said out loud on the earnings
call and appears in **no** SEC filing -- the page names the filings it searched
for it (`quarter_context`). What *is* in a filing, once a year, is a single
sentence in the 10-K's liquidity section: "In 2026, we expect capital
expenditures to total approximately $85.0 million." (The next sentence states a
regular-dividend target as a share of the prior year's "cash earnings", a
company-defined measure this page has not reconciled, so it is named in section
one but not settled.) So the first section settles capital expenditure, and the
record it settles is lopsided in the
opposite direction from what a cost guidance usually shows: most finished years
came in **below** the guidance, and the overshoots cluster in the NEX
integration and data-centre build years.

**Its revenue does not follow its volume one-for-one, and that is measurable
rather than asserted.** CME's fee schedule steps down as a client's monthly
volume rises, so a quiet quarter pushes contracts back into higher tiers and the
average rate per contract goes *up*. The page publishes the regression slope of
revenue on contracts over every quarterly change in the window, and how often
rate and volume moved against each other; a high-volume quarter does not carry
a low-volume quarter's rate.

**Its second income stream is a spread, not a rate bet.** CME reinvests cash
performance bonds and hands most of the interest back to clearing firms; what it
keeps is disclosed in the 10-Q as two prose figures, and dividing the difference
by the average collateral balance gives a retained spread that has stayed in a
narrow band of basis points while the gross yield on the same balance moved by
hundreds. The balance is a period-end number and the page says so.

**The four sections follow the site's shape, and the local analysis decides
what goes in them.** Section one settles what the previous local analysis left
open; the first CME analysis covers Q2 2026 (`analysis_record`) and left
nothing, so that quarter's section one says so and settles only the company's
own guidance. From the next quarter on it opens with the follow-up tally
(`followup_closure`) and the previous thresholds (`prior_kpi_settlement` --
last quarter's `next_kpi` list moved as it stood, settled against this
quarter's readings), and a later quarter with neither block stops the build.
`tests/test_cme_dashboard.py` rolls the series forward three quarters in
memory to prove none of that needs a code change. Section two draws that quarter's analysis's conclusions that a filing
can show and names the ones it cannot (`quarter_context.undrawn`). Section three
is the analysis's section 8, threshold by threshold (`next_kpi`), with every
current value computed here from the series. Section four is the long record.

**Rolling a quarter edits `series/cme.json` and nothing else** (CLAUDE.md §9).
Every figure, period and count in the prose is computed from the series, and a
sentence that states a record, a "first", an "only", an "always" or a ranking
is printed only while the series still says so. What belongs to one quarter --
the thresholds (`next_kpi`) and the call-only expense guidance with the list of
filings searched for it (`quarter_context`) -- carries a ``period`` stamp and is
read through `board.stamped_block`. `_checks` is a separate reading of the
quarter's release, and `_checks["note"]` of the quarter's local analysis, that
the tests hold the page to; this builder never reads either.

Published numbers are company-reported or transparent arithmetic. No market
expectation, rating, target price or valuation is published, and neither is the
call-only expense guidance -- see the note on what this page refuses to carry.
"""

from __future__ import annotations

import json
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
    headroom,
    headroom_exhibit,
    latest_block,
    minus_sign,
    number_exhibits,
    stamped_block,
    threshold_exhibit,
    threshold_table,
    unit_text,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "cme.json"
DATA_DIR = ROOT / "data"

# One tick per year keeps the fifty-four-quarter axes readable.
LONG_STEP = 4

AUDIT_WORDS = {"unaudited": "未审计", "audited": "已审计"}

CLASSES = [
    ("rates", "利率", "NAVY"),
    ("equity", "股指", "MBLUE"),
    ("fx", "外汇", "BLUE"),
    ("energy", "能源", "GREEN"),
    ("ags", "农产品", "GOLD"),
    ("metals", "金属", "GRAY"),
]

# Fixed history the prose names. The capex overshoot run the page explains by
# the NEX integration and the data-centre build, and the preferred-share
# conversion that makes one quarter's diluted share count not comparable with
# the next (the release's own footnote). The builder uses these words only when
# the series puts the event where it says.
NEX_BUILD_YEARS = ("2018", "2019", "2020")
PREFERRED_CONVERSION = ("2026-03-05", "Q1 2026")
# The first two collateral quarters are the zero-rate years; the band the page
# describes is everything after them.
ZERO_RATE_COLLATERAL_QUARTERS = 2


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100.0


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def rounded(values, digits: int = 6):
    return [None if v is None else round(v, digits) for v in values]


def mid(low: float, high: float) -> float:
    return (low + high) / 2


def usd_m(value: float, digits: int = 1) -> str:
    """US$M with the minus outside the currency symbol, as `board` formats it."""
    return f"{'−' if value < 0 else ''}US${abs(value):,.{digits}f}M"


def signed_usd(value: float, digits: int = 1) -> str:
    """A change in US$M that always carries its sign: +US$40.0M / −US$35.5M."""
    return f"{'−' if value < 0 else '+'}US${abs(value):,.{digits}f}M"


def years_of(quarters: int) -> str:
    """Whole years in a quarter count, in words: 42 → 「十」."""
    return cn_count(quarters // 4)


def quarter_words(period: str) -> str:
    """``'Q2 2026'`` → ``'2026 年第二季度'``, the way the source labels name a quarter."""
    quarter, year = period.split()
    return f"{year} 年第{cn_ordinal(int(quarter[1]))}季度"


def next_period(period: str) -> str:
    quarter, year = period.split()
    number = int(quarter[1])
    return f"Q1 {int(year) + 1}" if number == 4 else f"Q{number + 1} {year}"


def joined(words: list[str]) -> str:
    """``['A', 'B', 'C']`` → 「A、B与C」."""
    return words[0] if len(words) == 1 else "、".join(words[:-1]) + "与" + words[-1]


def runs(flags: list[bool]) -> list[tuple[int, int]]:
    """Maximal stretches of True as ``(start, stop)``, stop exclusive."""
    stretches, start = [], None
    for index, flag in enumerate(flags + [False]):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            stretches.append((start, index))
            start = None
    return stretches


def resolve_exhibit_refs(exhibits: list[dict]) -> list[dict]:
    """Replace ``{EX_NAME}`` placeholders with the numbers assigned at render."""
    numbers = {ex["ref"]: ex["n"] for ex in exhibits if "ref" in ex}
    for exhibit in exhibits:
        for key in ("note", "src_extra", "title"):
            text = exhibit.get(key)
            if not text:
                continue
            for ref, number in numbers.items():
                text = text.replace("{" + ref + "}", str(number))
            exhibit[key] = text
    return exhibits


def slope_and_r2(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Least-squares slope of y on x, and the R-squared, both from the series.

    Published rather than described: the whole argument about the fee schedule
    is a claim about a slope, and a page that only asserts "revenue is less
    volatile than volume" cannot be checked against the data it ships.
    """
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    return sxy / sxx, sxy ** 2 / (sxx * syy)


def qoq(values: list[float]) -> list[float]:
    return [(values[i] / values[i - 1] - 1) * 100 for i in range(1, len(values))]


def finished_capex_years(capex: dict) -> list[str]:
    return [y for y in capex["years"] if capex["by_year"][y]["actual"] is not None]


def capex_tally(capex: dict) -> dict[str, int]:
    counts = {"inside": 0, "above": 0, "below": 0}
    for year in finished_capex_years(capex):
        block = capex["by_year"][year]
        actual = block["actual"]
        counts["inside" if block["low"] <= actual <= block["high"]
               else ("above" if actual > block["high"] else "below")] += 1
    return counts


def over_midpoint_years(capex: dict) -> list[str]:
    return [y for y in finished_capex_years(capex)
            if capex["by_year"][y]["actual"] > mid(capex["by_year"][y]["low"],
                                                   capex["by_year"][y]["high"])]


def consecutive_years(years: list[str]) -> list[list[str]]:
    """Group sorted year labels into runs of consecutive years."""
    groups: list[list[str]] = []
    for year in years:
        if groups and int(year) == int(groups[-1][-1]) + 1:
            groups[-1].append(year)
        else:
            groups.append([year])
    return groups


# ── section one: the only guidance that lives in a filing ────────────────────

def capex_section(staging: dict) -> tuple[list[dict], list[dict]]:
    capex = staging["capex_guidance"]
    years = capex["years"]
    low = [capex["by_year"][y]["low"] for y in years]
    high = [capex["by_year"][y]["high"] for y in years]
    actual = [capex["by_year"][y]["actual"] for y in years]
    labels = [f"FY{y}" for y in years]
    ranges = [y for y in years if capex["by_year"][y]["form"] == "range"]
    tally = capex_tally(capex)
    finished = finished_capex_years(capex)
    inside = [y for y in finished
              if capex["by_year"][y]["low"] <= capex["by_year"][y]["actual"] <= capex["by_year"][y]["high"]]
    latest_guided = years[-1]
    inside_words = "；".join(
        "FY{0}，实际 US${1:.1f}M 落在 {2:g}–{3:g} 之间".format(
            y, capex["by_year"][y]["actual"], capex["by_year"][y]["low"], capex["by_year"][y]["high"])
        for y in inside)

    band = delivery_band(
        "EX_CAPEX", "全年资本开支", labels, low, high, actual,
        fmt="f0c", ylab="US$M", unit="US$M",
        venue="10-K",
        timing="该年<b>开始后两个月内</b>",
        period_word="年",
        extra_note=(
            f"<b>{len(years) - len(ranges)} 个年度的指引是一个单点（「approximately $X million」），"
            f"只有 {'、'.join('FY' + y for y in ranges)} 这 {len(ranges)} 年给的是区间</b>，"
            "所以图上多数色块没有宽度 —— 这不是渲染问题，是公司的指引本来就没有宽度。"
            f"因此「落在区间内」这一档在 {len(finished)} 个已完结年度里只可能属于那{cn_count(len(ranges))}年，"
            f"实际也只发生过 {tally['inside']} 次"
            + (f"（{inside_words}）" if inside else "")
            + "。"),
        src_extra=("指引句逐年读自各年 10-K 的流动性与资本资源一节（例如 "
                   f"FY{latest_guided}：「{capex['by_year'][latest_guided]['sentence']}.」）；"
                   "实际值取各年 10-K 现金流量表的 Purchases of property 一行，"
                   "每个年度都在 2–3 份 10-K 的三年比较列里出现过，逐份核对无差异。"),
    )

    deviation = [(a / mid(lo, hi) - 1) * 100
                 for lo, hi, a in zip(low, high, actual) if a is not None]
    dev_labels = [f"FY{y}" for y in finished]
    over = [d for d in deviation if d > 0]
    mean_abs = statistics.fmean(abs(d) for d in deviation)
    biggest = max(deviation, key=abs)
    over_years = over_midpoint_years(capex)
    under = len(finished) - len(over_years)
    # The first version said the guidance was "always" off in one direction and
    # the brief that it was "always" too high; four of the sixteen finished
    # years came in above it. The counts are now the claim.
    groups = consecutive_years(over_years)
    described = []
    for group in groups:
        if len(group) > 1:
            text = "连续的 " + "、".join(f"FY{y}" for y in group)
            if tuple(group) == NEX_BUILD_YEARS:
                text += " —— 那三年正是 NEX 并购整合与自建数据中心同时在跑的三年 ——"
            described.append(text)
        else:
            described.append(f"FY{group[0]}")
    over_words = (f"{cn_count(len(finished))}个年度里只有{cn_count(len(over_years))}年高于指引中值："
                  + " 以及 ".join(described)
                  + f"；其余{cn_count(under)}年全部低于指引中值。") if over_years else (
                  f"{cn_count(len(finished))}个年度全部低于指引中值。")
    last_finished = finished[-1]
    last_year_income = sum(
        value for quarter, value in zip(staging["long"]["quarters"], staging["long"]["operating_income"])
        if quarter.startswith(last_finished))
    capex_share = capex["by_year"][last_finished]["actual"] / last_year_income * 100
    dev = {
        "ref": "EX_CAPEX_DEV",
        "kind": "grouped_bars",
        "title": (f"资本开支实际值相对指引中值的偏离：{len(deviation)} 年里 {len(over)} 年为正，"
                  f"平均绝对偏离 {mean_abs:.1f}%"),
        "xlabels": dev_labels,
        "xrot": 90,
        "groups": [{"name": "实际资本开支 vs 指引中值", "color": "BLUE",
                    "values": rounded(deviation)}],
        "bar_labels": True,
        "fmt": "pct0",
        "label_fmt": "pct0",
        "ylab": "% vs 指引中值",
        "note": (
            "<b>这张图说明的不是「指引准不准」，而是它"
            + (f"{cn_count(len(finished))}年里有{cn_count(under)}年往同一个方向不准。</b>"
               if under * 2 > len(finished) else "往哪个方向不准。</b>")
            + f"平均绝对偏离 {mean_abs:.1f}%，窗口内最大的一次是 "
            f"{dev_labels[deviation.index(biggest)]} 的 {biggest:+.0f}%。"
            + over_words
            + ("<b>一个长期往下偏的资本开支指引，对现金流模型的含义是上偏而不是中性</b>"
               if under * 2 > len(finished) else "<b>这条指引的偏差没有一个稳定的方向</b>")
            + " —— 但它的绝对量级很小，"
            f"FY{last_finished} 的 US${capex['by_year'][last_finished]['actual']:.1f}M 只相当于当年营业利润的"
            + ("个位数百分比" if capex_share < 10 else f" {capex_share:.0f}%")
            + "，所以它值得看的地方在于口径本身，而不在于它对自由现金流的影响。"),
        "src_extra": "同 Exhibit {EX_CAPEX}；中值对单点指引即该点本身。",
    }

    table = {
        "n": 0,
        "title": "全年资本开支：10-K 指引 vs 现金流量表实际值（US$M）",
        "headers": ["年度", "指引形式", "指引", "实际", "相对中值 D", "判定 D", "指引出处"],
        "rows": [[
            f"FY{y}",
            "单点" if capex["by_year"][y]["form"] == "point" else "区间",
            (f"${capex['by_year'][y]['low']:,.1f}"
             if capex["by_year"][y]["form"] == "point"
             else f"${capex['by_year'][y]['low']:,.1f}–${capex['by_year'][y]['high']:,.1f}"),
            (f"${capex['by_year'][y]['actual']:,.1f}"
             if capex["by_year"][y]["actual"] is not None else "待披露"),
            (f"{(capex['by_year'][y]['actual'] / mid(capex['by_year'][y]['low'], capex['by_year'][y]['high']) - 1) * 100:+.1f}%"
             if capex["by_year"][y]["actual"] is not None else "—"),
            ("—" if capex["by_year"][y]["actual"] is None else
             ("区间内" if capex["by_year"][y]["low"] <= capex["by_year"][y]["actual"] <= capex["by_year"][y]["high"]
              else ("高于上限" if capex["by_year"][y]["actual"] > capex["by_year"][y]["high"] else "低于下限"))),
            f"{capex['by_year'][y]['source_filed']} 的 10-K",
        ] for y in years],
    }
    return [band, dev], [table]


# ── section two: this quarter ────────────────────────────────────────────────

def revenue_legs(fin: dict) -> list[tuple[str, float, float]]:
    """(name, year-on-year change in US$M, year-on-year %) for the three revenue lines."""
    return [(name, fin[key][-1] - fin[key][-5], pct_change(fin[key][-1], fin[key][-5]))
            for name, key in (("清算与交易费", "clearing_fees"), ("行情数据", "market_data"),
                              ("其他收入", "other_revenue"))]


def quarter_section(staging: dict, context: dict | None) -> list[dict]:
    fin = staging["financials"]
    lng = staging["long"]
    labels = staging["period_labels"]
    window = cn_count(len(labels))

    # The `long` block runs from 2013Q1; this site's window starts 2016Q1, which
    # is index 12. Four of this section's charts read from here rather than from
    # the short `financials` block -- the same disclosure, forty-two quarters of
    # it, already in the file.
    LONG_FROM = lng["quarters"].index("2016Q1")
    long_labels = lng["period_labels"][LONG_FROM:]
    long_years = years_of(len(long_labels))

    def span(name: str) -> list:
        return lng[name][LONG_FROM:]

    share = [100 * c / r for c, r in zip(span("clearing_fees"), span("total_revenues"))]
    legs = revenue_legs(fin)
    total_change = fin["total_revenues"][-1] - fin["total_revenues"][-5]
    clearing_change = fin["clearing_fees"][-1] - fin["clearing_fees"][-5]
    market_change = fin["market_data"][-1] - fin["market_data"][-5]
    growers = [name for name, change, _ in legs if change > 0]
    total_yoy = pct_change(fin["total_revenues"][-1], fin["total_revenues"][-5])
    small = 0 < total_yoy < 5
    if total_change > 0 and len(growers) == 1:
        source_words = f"而这{'一点点' if small else ''}增长全部来自{growers[0]}那条腿"
    elif total_change > 0:
        source_words = f"而这{'一点点' if small else ''}增长来自{joined(growers)}"
    else:
        source_words = "三条腿合计没有增长"
    # The clearing line's year-on-year turns inside the short window. The first
    # version called this quarter's the first; Q3 2025 had already been -5.3%.
    short_yoy = [pct_change(fin["clearing_fees"][i], fin["clearing_fees"][i - 4])
                 for i in range(4, len(labels))]
    short_neg = [labels[4 + i] for i, value in enumerate(short_yoy) if value < 0]
    clearing_yoy = short_yoy[-1]
    if clearing_yoy < 0 and short_neg == [labels[-1]]:
        turn_words = f"是<b>{window}季窗口内</b>第一次同比转负"
        long_lead = "<b>把窗口拉到十年，「第一次」这个说法就要收回</b>"
    elif clearing_yoy < 0:
        before = short_neg[-2]
        turn_words = (f"是<b>{window}季窗口内</b>第{cn_ordinal(len(short_neg))}次同比转负"
                      f"（上一次是 {before}，{pct_change(fin['clearing_fees'][labels.index(before)], fin['clearing_fees'][labels.index(before) - 4]):+.1f}%）")
        long_lead = f"<b>把窗口拉到{long_years}年，同比转负并不稀奇</b>"
    else:
        turn_words = ""
        long_lead = f"<b>把窗口拉到{long_years}年看</b>"
    clearing = span("clearing_fees")
    negative = [i for i in range(4, len(clearing)) if clearing[i] < clearing[i - 4]]
    negative_runs = runs([i in negative for i in range(len(clearing))])
    longest = max(negative_runs, key=lambda span_: (span_[1] - span_[0], span_[0]))
    lower = sum(1 for value in share if value < share[-1])
    peak_at = share.index(max(share))
    rises = sum(1 for i in range(peak_at + 1, len(share)) if share[i] > share[i - 1])
    if lower * 6 <= len(share):
        share_words = (f"真正少见的不是同比转负 —— 是金色那条占比线降到 {share[-1]:.1f}%："
                       f"{len(share)} 季里只有{cn_count(lower)}季比它低。")
    else:
        share_words = f"金色那条占比线本季是 {share[-1]:.1f}%。"
    mix = {
        "ref": "EX_MIX",
        "kind": "stacked_dual",
        # The title used to lead with the ten-year range of the clearing share;
        # the quarter's conclusion -- the local analysis's core contradiction --
        # sat in the note. It leads now, and only while the legs still say it.
        "title": (
            (f"总收入同比 {minus_sign(signed(total_yoy))}、清算与交易费同比 "
             f"{minus_sign(signed(clearing_yoy))}：行情数据一条线多出 {signed_usd(market_change)}，"
             f"比全公司的 {signed_usd(total_change)} 还多"
             if market_change >= total_change > 0 > clearing_change else
             f"总收入同比 {minus_sign(signed(total_yoy))}、清算与交易费同比 {minus_sign(signed(clearing_yoy))}："
             f"清算与交易费 US${fin['clearing_fees'][-1]:,.1f}M，占总收入 {share[-1]:.1f}%")),
        "xlabels": long_labels,
        "xstep": LONG_STEP,
        "stacks": [
            {"name": "清算与交易费", "color": "NAVY", "values": rounded(span("clearing_fees"))},
            {"name": "行情数据与信息服务", "color": "MBLUE", "values": rounded(span("market_data"))},
            {"name": "其他收入", "color": "BLUE", "values": rounded(span("other_revenue"))},
        ],
        # `stacked_dual` scales its right axis to `ticks(0, ymax || 60, 6)`,
        # not to the data. This share sits around 80%, so without a ymax the
        # line is drawn above the top of the canvas and vanishes silently.
        "line": {"name": "清算与交易费占比 (RHS)", "color": "GOLD",
                 "values": rounded(share), "yfmt": "pct1", "ymax": 100},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M", "ylab2": "%",
        "note": (
            f"<b>本季总收入同比{'只' if 0 < total_yoy < 5 else ''}增长 {signed(total_yoy)}，"
            f"{source_words}。</b>"
            f"清算与交易费同比 {signed(pct_change(fin['clearing_fees'][-1], fin['clearing_fees'][-5]))}"
            + (f"，{turn_words}" if turn_words else "")
            + "；行情数据同比 "
            f"{signed(pct_change(fin['market_data'][-1], fin['market_data'][-5]))}；"
            f"其他收入同比 {signed(pct_change(fin['other_revenue'][-1], fin['other_revenue'][-5]))}。"
            f"逐条相加：US${fin['market_data'][-1] - fin['market_data'][-5]:+,.1f}M 加上 "
            f"US${fin['other_revenue'][-1] - fin['other_revenue'][-5]:+,.1f}M，"
            + (f"再减去 US${abs(fin['clearing_fees'][-1] - fin['clearing_fees'][-5]):,.1f}M，"
               if fin["clearing_fees"][-1] < fin["clearing_fees"][-5] else
               f"再加上 US${fin['clearing_fees'][-1] - fin['clearing_fees'][-5]:,.1f}M，")
            + f"得到 US${total_change:+,.1f}M。"
            f"{long_lead}：这 {len(long_labels)} 季里清算与交易费"
            f"同比为负的季度共 {len(negative)} 个，"
            f"最长的一轮是 {long_labels[longest[0]]}–{long_labels[longest[1] - 1]} "
            f"连续{cn_count(longest[1] - longest[0])}季。"
            + share_words
            + f"{long_years}年高点是 {long_labels[peak_at]} 的 {max(share):.1f}%，此后总体下行"
            f"（{len(share) - 1 - peak_at} 次环比里 {rises} 次回升）—— "
            "行情数据那条腿一直在把它往下压。"),
        "src_extra": (f"{len(long_labels)} 季逐季读自各季业绩新闻稿（8-K EX-99.1）的合并损益表，均为公司披露值；"
                      "占比为三条腿相除的自算值 D。"),
    }

    # The volume/price bridge, built from the company's own ADV, trading days
    # and RPC rather than from the reported fee line -- the two differ by the
    # cash and FX businesses, which have no published volume at all.
    prev_contracts = lng["contracts_m"][-2]
    contracts = lng["contracts_m"][-1]
    prev_rpc, this_rpc = lng["rpc"][-2], lng["rpc"][-1]
    volume_effect = (contracts - prev_contracts) * prev_rpc
    rate_effect = (this_rpc - prev_rpc) * contracts
    prev_fees, fees = lng["fo_clearing_fees"][-2], lng["fo_clearing_fees"][-1]
    tiering = volume_effect < 0 < rate_effect
    bridge = {
        "ref": "EX_BRIDGE",
        "kind": "bridge_bar",
        "title": (f"期货与期权清算费环比 {usd_m(fees - prev_fees)}："
                  + (f"量减 {usd_m(abs(volume_effect))}，费率回升补回 {usd_m(rate_effect)}"
                     if tiering else
                     f"量效应 {usd_m(volume_effect)}，费率效应 {usd_m(rate_effect)}")),
        "xlabels": [f"{labels[-2]} 期货与期权清算费", "成交合约数变动", "平均每手费率变动",
                    f"{labels[-1]} 期货与期权清算费"],
        "stacks": [{"name": "环比拆解", "color": "NAVY",
                    "values": rounded([prev_fees, volume_effect, rate_effect, None])}],
        "net": {"name": f"{labels[-1]} 清算费（净额）",
                "values": rounded([None, None, None, fees])},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M",
        "note": (
            (f"<b>合约数环比 {qoq(lng['contracts_m'])[-1]:+.1f}%，但这条费用线只跌了 "
             f"{qoq(lng['fo_clearing_fees'])[-1]:+.1f}% —— 差额就是分级费率。</b>"
             if tiering else
             f"<b>合约数环比 {qoq(lng['contracts_m'])[-1]:+.1f}%，这条费用线环比 "
             f"{qoq(lng['fo_clearing_fees'])[-1]:+.1f}%。</b>")
            + f"{labels[-2]} 成交 {prev_contracts:,.1f} 百万张、每手 ${prev_rpc:.3f}；"
            f"{labels[-1]} 成交 {contracts:,.1f} 百万张、每手 ${this_rpc:.3f}。"
            "量效应按上季费率计价，费率效应按本季成交量计价，两者相加与直接相减完全吻合。"
            + ("<b>费率不是被提上去的</b>：客户当月累计成交量越大、落进的费率档越低，"
               "所以量一少，同一批客户自动退回较高的档位。" if tiering else "")
            + f"Exhibit {{EX_ADV_LONG}} 把这条机制放在{cn_count(len(lng['quarters']))}个季度上，"
            "Exhibit {EX_CLASS_RPC} 说明它在六个品种里同时发生。"),
        "src_extra": ("ADV、交易日与 RPC 均为业绩新闻稿披露值；"
                      "期货与期权清算费 = ADV × 交易日 × RPC，是公司口径的乘积 D，"
                      "与合并损益表的清算与交易费一行相差的部分见 Exhibit {EX_RESIDUAL}。"),
    }

    adv_qoq = [pct_change(lng[f"adv_{k}"][-1], lng[f"adv_{k}"][-2]) for k, _, _ in CLASSES]
    rpc_qoq = [pct_change(lng[f"rpc_{k}"][-1], lng[f"rpc_{k}"][-2]) for k, _, _ in CLASSES]
    opposite = sum(1 for a, r in zip(adv_qoq, rpc_qoq) if a * r < 0)
    worst = adv_qoq.index(min(adv_qoq))
    worst_name = CLASSES[worst][1]
    mixed_rate = weighted_rpc(lng)
    # Not all six moved against their rates, as the first title said: this
    # quarter agricultural ADV rose and so did its rate.
    if opposite == len(CLASSES):
        class_head = "六个品种的量与价同时反向"
    else:
        class_head = f"六个品种里{cn_count(opposite)}个量价反向"
    class_rpc = {
        "ref": "EX_CLASS_RPC",
        "kind": "grouped_bars",
        "title": (f"{class_head}：ADV 环比 {sum(1 for v in adv_qoq if v < 0)} 跌 "
                  f"{sum(1 for v in adv_qoq if v >= 0)} 涨，每手费率环比 "
                  f"{sum(1 for v in rpc_qoq if v > 0)} 个上升"),
        "xlabels": [name for _, name, _ in CLASSES],
        "groups": [
            {"name": "ADV 环比", "color": "NAVY", "values": rounded(adv_qoq)},
            {"name": "每手费率 RPC 环比", "color": "GOLD", "values": rounded(rpc_qoq)},
        ],
        "bar_labels": True,
        "fmt": "pct1", "label_fmt": "pct1",
        "ylab": "环比 %",
        "note": (
            ("<b>六个品种的费率没有一个下降，而这六个品种的成交量方向并不一致 —— "
             "只有一个与量相关的机制能同时解释六条。</b>"
             if all(v > 0 for v in rpc_qoq) and any(v < 0 for v in adv_qoq) and any(v >= 0 for v in adv_qoq)
             else "")
            + f"{'跌得最狠' if adv_qoq[worst] < 0 else '涨得最少'}的{worst_name} ADV 环比 "
            f"{adv_qoq[worst]:+.1f}%，它的每手费率"
            + ("反而升了" if rpc_qoq[worst] > 0 > adv_qoq[worst] else "环比")
            + f" {rpc_qoq[worst]:+.1f}%"
            + ("，是六个里最大的一格。" if rpc_qoq[worst] == max(rpc_qoq) and rpc_qoq[worst] > 0 else "。")
            + "把上季各品种的费率固定住、只换成本季的成交结构，混合费率是 "
            f"${mixed_rate:.4f}，"
            + (f"比上季实际的 ${lng['rpc'][-2]:.3f} 还要低 —— "
               f"也就是说<b>结构效应是负的（{(mixed_rate - lng['rpc'][-2]) * 1000:+.1f} 厘），"
               f"整个 ${lng['rpc'][-1] - lng['rpc'][-2]:+.3f} 的回升都来自品种内部</b>，"
               "而不是成交向高费率品种迁移。"
               if mixed_rate < lng["rpc"][-2] < lng["rpc"][-1] else
               f"比上季实际的 ${lng['rpc'][-2]:.3f} 低 —— 结构效应 "
               f"{(mixed_rate - lng['rpc'][-2]) * 1000:+.1f} 厘，其余 "
               f"{(lng['rpc'][-1] - mixed_rate) * 1000:+.1f} 厘来自品种内部。"
               if mixed_rate < lng["rpc"][-2] else
               f"比上季实际的 ${lng['rpc'][-2]:.3f} 高 {(mixed_rate - lng['rpc'][-2]) * 1000:+.1f} 厘 —— "
               "成交结构本身也推高了混合费率。")),
        "src_extra": "各季业绩新闻稿的分品种 ADV 与 RPC 五季表；结构分解为固定上季费率的加权重算 D。",
    }

    adj = fin["adj_margin_pct"]
    expense_move = pct_change(fin["adj_total_expenses"][-1], fin["adj_total_expenses"][-2])
    if adj[-2] == max(adj) and adj[-1] < adj[-2] and abs(expense_move) < 3:
        margin_lead = (f"<b>上季的 {adj[-2]:.1f}% 是这{window}个季度里最高的一格，本季回落 "
                       f"{adj[-1] - adj[-2]:.1f} 个百分点，而费用几乎没动。</b>")
    else:
        margin_lead = (f"<b>本季调整后营业利润率 {adj[-1]:.1f}%，环比 "
                       f"{adj[-1] - adj[-2]:+.1f} 个百分点。</b>")
    margin = {
        "ref": "EX_MARGIN",
        "kind": "lines",
        "title": (f"两条营业利润率：调整后 {fin['adj_margin_pct'][-1]:.1f}%（只有 "
                  f"{len(fin['adj_margin_pct'])} 季），"
                  f"GAAP {fin['gaap_margin_pct'][-1]:.1f}%（{len(long_labels)} 季）"),
        "xlabels": long_labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": "调整后营业利润率",
             "values": ([None] * (len(long_labels) - len(fin["adj_margin_pct"]))
                        + rounded(fin["adj_margin_pct"])),
             "color": "NAVY"},
            {"name": "GAAP 营业利润率", "values": rounded(span("gaap_margin_pct")),
             "color": "BLUE"},
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
        "ylab": "%",
        "note": (
            margin_lead
            + f"调整后费用环比 {signed(expense_move)}，"
            f"收入环比 {signed(pct_change(fin['total_revenues'][-1], fin['total_revenues'][-2]))}"
            + (" —— 利润率的落差几乎全部来自分母。" if abs(expense_move) < 3 and adj[-1] < adj[-2] else "。")
            + "两条线之间的缺口是并购无形资产摊销、"
            "重组与遣散、递延薪酬与诉讼等调整项，"
            f"本季 {fin['adj_margin_pct'][-1] - fin['gaap_margin_pct'][-1]:.1f} 个百分点。"
            "<b>两条线长度不同，那不是没做完，是披露本身的形状。</b>"
            f"GAAP 那条回到 {long_labels[0].split()[1]}{long_labels[0].split()[0]}；"
            f"调整后那条只有{cn_count(len(adj))}季，因为在 2025 年 10 月之前 CME 的"
            "业绩发布里根本没有量化过「调整后营业利润」—— 那个词只出现在标题和 CEO 引语里，"
            "一个数都没有，直到 SEC 的问询函要求「要么量化、要么别用」。"
            "所以更早的调整后利润率不是本站没取，是它不存在。"
            f"GAAP 那条自己的窗口区间是 {min(span('gaap_margin_pct')):.1f}–"
            f"{max(span('gaap_margin_pct')):.1f}%，本季 {fin['gaap_margin_pct'][-1]:.1f}%。"),
        "src_extra": ("调整后营业利润取自各季业绩新闻稿的 Reconciliation of Adjusted Operating "
                      "Income 表；两个利润率均为该口径营业利润 ÷ 总收入 D，与公司披露的分子一致。"),
    }

    searched = context["searched"] if context else None
    opex = {
        "ref": "EX_OPEX",
        "kind": "bar_line_dual",
        "title": (f"调整后营业费用（除许可费）US${fin['adj_opex_ex_license'][-1]:,.1f}M，"
                  f"许可费 US${fin['licensing_expense'][-1]:,.1f}M 单独一条"),
        "xlabels": labels,
        "bar": {"name": "调整后营业费用（除许可费）", "color": "NAVY",
                "values": rounded(fin["adj_opex_ex_license"])},
        "line": {"name": "许可与其他费用协议 (RHS)", "color": "GOLD",
                 "values": rounded(fin["licensing_expense"]), "yfmt": "f0c"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M", "ylab2": "US$M",
        "note": (
            "<b>这条线是市场唯一拿来给 CME 建成本模型的口径，而公司从不把它写进任何申报文件。</b>"
            "本页能画出它，是因为它等于业绩新闻稿里的调整后费用合计减去合并损益表里的"
            "「许可与其他费用协议」一行，两个数都是披露值；但公司对它的<b>全年指引</b>只在"
            "业绩电话会上给"
            + (f"，{searched}逐字搜过，一次都没有出现。" if searched else "。")
            + "<b>所以第一节结清的公司指引是资本开支，不是它的全年指引。</b>"
            "把许可费单画一条是因为它跟着股指成交量走而不是跟着成本走："
            f"本季许可费同比 "
            f"{signed(pct_change(fin['licensing_expense'][-1], fin['licensing_expense'][-5]))}，"
            f"同期股指 ADV 同比 {signed(pct_change(lng['adv_equity'][-1], lng['adv_equity'][-5]))}。"),
        "src_extra": ("调整后费用合计取自 Reconciliation of Adjusted Operating Income 表"
                      "（公司自 2025 年第三季度业绩新闻稿起才印这张表，因此本页的调整后费用"
                      f"序列正好只有{cn_count(len(fin['adj_total_expenses']))}个季度）；"
                      "许可费取自合并损益表。差额为 D。"),
    }

    md_long = span("market_data")
    md_yoy = [pct_change(value, lng["market_data"][LONG_FROM + index - 4])
              for index, value in enumerate(md_long)]
    md_records = sum(1 for index, value in enumerate(md_long)
                     if value == max(md_long[:index + 1]))
    md_carries = md_long[-1] - md_long[-5] >= total_change > 0
    short_records = all(md_long[-len(labels) + i] == max(md_long[:len(md_long) - len(labels) + i + 1])
                        for i in range(len(labels)))
    # By full year the line was flat in 2016-2017 and grew fastest in 2018,
    # 2019 and 2025 -- the first version said it was flat until 2020 and only
    # accelerated after 2021.
    by_year: dict[str, list[float]] = {}
    for quarter, value in zip(lng["quarters"], lng["market_data"]):
        by_year.setdefault(quarter[:4], []).append(value)
    annual = {year: sum(values) for year, values in by_year.items()
              if len(values) == 4 and year >= long_labels[0].split()[1]}
    growth = {year: (annual[year] / annual[prior] - 1) * 100
              for prior, year in zip(sorted(annual), sorted(annual)[1:])}
    first_year = long_labels[0].split()[1]
    first_growth = ((annual[first_year] / sum(by_year[str(int(first_year) - 1)]) - 1) * 100
                    if len(by_year.get(str(int(first_year) - 1), [])) == 4 else None)
    if first_growth is not None:
        growth = {first_year: first_growth, **growth}
    flat = [year for year, value in growth.items() if abs(value) < 5]
    fastest = sorted(sorted(growth, key=growth.get, reverse=True)[:3])
    flat_span = (f"{flat[0]}–{flat[-1]}" if len(flat) > 1 and int(flat[-1]) - int(flat[0]) == len(flat) - 1
                 else "、".join(flat))
    history_words = (
        f"按完整年度算，{flat_span} 年这条线基本是平的"
        f"（{'、'.join(signed(growth[y]) for y in flat)}），涨得最快的是 "
        f"{'、'.join(fastest)} 年（{'、'.join(signed(growth[y]) for y in fastest)}）。"
        if flat else
        f"按完整年度算，涨得最快的是 {'、'.join(fastest)} 年"
        f"（{'、'.join(signed(growth[y]) for y in fastest)}）。")
    market_data = {
        "ref": "EX_MKTDATA",
        "kind": "bar_line_dual",
        "title": (f"行情数据与信息服务 US${md_long[-1]:,.1f}M，同比 {signed(md_yoy[-1])}，"
                  f"{len(long_labels)} 季里 {md_records} 季创下当时的新高"),
        "xlabels": long_labels,
        "xstep": LONG_STEP,
        "bar": {"name": "行情数据与信息服务收入", "color": "MBLUE",
                "values": rounded(md_long)},
        "line": {"name": "同比 (RHS)", "color": "RED", "values": rounded(md_yoy), "yfmt": "pct1"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M", "ylab2": "同比 %",
        "note": (
            ("<b>这条线现在扛着 CME 全部的同比增长，而它的加速与成交量无关。</b>" if md_carries else "")
            + (f"<b>{'但' if md_carries else ''}「一路创纪录」是{window}季窗口才成立的说法</b>："
               if short_records else "")
            + f"{len(long_labels)} 季里同比为负的有 "
            f"{sum(1 for value in md_yoy if value < 0)} 季，最低 {min(md_yoy):+.1f}%"
            f"（{long_labels[md_yoy.index(min(md_yoy))]}）—— "
            + history_words
            + f"近{window}季同比从 {md_yoy[-len(labels)]:+.1f}% 走到 {md_yoy[-1]:+.1f}%，"
            f"环比 {signed(pct_change(fin['market_data'][-1], fin['market_data'][-2]))}。"
            "<b>本页不拆分这条线的价与量</b>：公司既不披露提价幅度，也不披露订阅数的绝对值，"
            "电话会上给过的「专业订阅数环比」与「同比」是两个不同口径的数，"
            "把它们当同一个序列相减会造出一个不存在的量增长。"
            "能从申报文件里读到的只有这条收入线本身，以及它在总收入里的占比 —— "
            f"本季 {100 * md_long[-1] / span('total_revenues')[-1]:.1f}%，"
            f"{long_years}年前是 {100 * md_long[0] / span('total_revenues')[0]:.1f}%。"),
        "src_extra": (f"{len(long_labels)} 季逐季读自合并损益表的行情数据与信息服务一行；"
                      "同比与占比由本页对同一序列相除 D。"),
    }

    gaps = [a - g for a, g in zip(span("adj_diluted_eps"), span("diluted_eps"))]
    low_at, high_at = gaps.index(min(gaps)), gaps.index(max(gaps))
    outlier = lng["effective_tax_outlier"]["quarter"]
    low_label, high_label = long_labels[low_at], long_labels[high_at]
    low_words = (f"（{low_label.split()[1]}{low_label.split()[0]}，那一格 GAAP 被税改的一次性重估抬到"
                 "调整后之上，见 Exhibit {EX_TAX}）"
                 if lng["quarters"][LONG_FROM + low_at] == outlier
                 else f"（{low_label.split()[1]}{low_label.split()[0]}）")
    tax = fin["effective_tax_pct"]
    shares = fin["diluted_shares_k"]
    eps = {
        "ref": "EX_EPS",
        "kind": "lines",
        "title": (f"{len(long_labels)} 季两条摊薄每股收益：调整后 ${span('adj_diluted_eps')[-1]:.2f}，"
                  f"GAAP ${span('diluted_eps')[-1]:.2f}"),
        "xlabels": long_labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": "调整后摊薄 EPS", "values": rounded(span("adj_diluted_eps")), "color": "NAVY"},
            {"name": "GAAP 摊薄 EPS", "values": rounded(span("diluted_eps")), "color": "BLUE"},
        ],
        "fmt": "usd2", "yfmt": "usd2", "label_fmt": "usd2", "end_label": True,
        "ylab": "US$/股",
        "note": (
            f"<b>本季 GAAP 与调整后的缺口{'收窄到' if gaps[-1] < gaps[-2] else '为'} "
            f"${gaps[-1]:.2f}</b> —— 而 {len(long_labels)} 季里最窄的是 "
            f"${min(gaps):.2f}{low_words}，"
            f"最宽 ${max(gaps):.2f}（{high_label.split()[1]}{high_label.split()[0]}）。"
            f"GAAP 有效税率 {tax[-1]:.2f}%，比上季的 {tax[-2]:.2f}% "
            + (f"低 {(tax[-2] - tax[-1]) * 100:.0f} 个基点，GAAP 那条线因此被抬高；"
               "而公司的调整口径把当季的离散税项整笔剔除，"
               "所以调整后那条线没有被同一件事抬到。"
               if tax[-1] < tax[-2] else
               f"高 {(tax[-1] - tax[-2]) * 100:.0f} 个基点。")
            + f"摊薄股数从上季的 {shares[-2]:,.0f} 千股{'降到' if shares[-1] < shares[-2] else '变为'} "
            f"{shares[-1]:,.0f} 千股"
            + (f"，上季含 {PREFERRED_CONVERSION[0]} 优先股转普通股的加权影响，两季分母口径不同。"
               if labels[-2] == PREFERRED_CONVERSION[1] else
               f"，本季含 {PREFERRED_CONVERSION[0]} 优先股转普通股的加权影响，两季分母口径不同。"
               if labels[-1] == PREFERRED_CONVERSION[1] else "。")),
        "src_extra": ("GAAP 每股收益与摊薄股数取自合并损益表，调整后每股收益取自各季业绩新闻稿的 "
                      f"Reconciliation of Adjusted Net Income 表（{len(long_labels)} 季，"
                      f"{long_labels[0].split()[1]}{long_labels[0].split()[0]} 起）；"
                      "有效税率为所得税费用 ÷ 税前利润 D。"),
    }
    return [mix, bridge, class_rpc, margin, opex, market_data, eps, collateral_exhibit(staging)]


def collateral_exhibit(staging: dict) -> dict:
    """The collateral line this quarter, beside the gross income it is mistaken for.

    The local analysis's third insight is a claim about this quarter: gross
    investment income fell year on year while what CME keeps rose. So the chart
    leads with that reading, and the band of retained basis points since the
    zero-rate quarters is the evidence under it. The collateral series skips
    quarters (fourth quarters come only as full-year prose), so the year-ago
    cell is found by its label, never by stepping back four places.
    """
    coll, lng = staging["collateral"], staging["long"]
    post = coll["retained_bp"][ZERO_RATE_COLLATERAL_QUARTERS:]
    post_gross = coll["gross_bp"][ZERO_RATE_COLLATERAL_QUARTERS:]
    post_from = coll["period_labels"][ZERO_RATE_COLLATERAL_QUARTERS]
    this = coll["quarters"][-1]
    year_ago = f"{int(this[:4]) - 1}{this[4:]}"
    income = lng["investment_income"]
    income_change, income_yoy = income[-1] - income[-5], pct_change(income[-1], income[-5])
    net_yoy = lead = None
    if year_ago in coll["quarters"]:
        prior = coll["quarters"].index(year_ago)
        net_yoy = pct_change(coll["net"][-1], coll["net"][prior])
        net_change = coll["net"][-1] - coll["net"][prior]
        earned_change = coll["earnings"][-1] - coll["earnings"][prior]
        paid_change = coll["distribution"][-1] - coll["distribution"][prior]
        if income_change < 0 < net_change and paid_change < earned_change < 0:
            lead = (f"<b>投资收益同比少了 US${abs(income_change):,.1f}M，CME 自己留下的这一块反而多了 "
                    f"US${net_change:,.1f}M</b> —— 抵押品再投资收益同比少了 US${abs(earned_change):,.1f}M，"
                    f"付给清算会员的利息分配少得更多（US${abs(paid_change):,.1f}M）。")
    return {
        "ref": "EX_SPREAD",
        "kind": "bar_line_dual",
        "title": (f"抵押品净利差 US${coll['net'][-1]:,.1f}M"
                  + (f"、同比 {minus_sign(signed(net_yoy))}" if net_yoy is not None else "")
                  + (f"，同期投资收益同比 {minus_sign(signed(income_yoy))}" if lead else "")
                  + f"：留存约 {coll['retained_bp'][-1]:.0f} 个基点"),
        "xlabels": coll["period_labels"],
        "bar": {"name": "抵押品再投资收益 − 利息分配支出（US$M）", "color": "NAVY",
                "values": rounded(coll["net"])},
        "line": {"name": "折合留存利差 (RHS)", "color": "GOLD",
                 "values": rounded(coll["retained_bp"]), "yfmt": "f0"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M", "ylab2": "基点",
        "note": (
            (lead or "")
            + "<b>这条收入被普遍当成利率敞口，但它是一个基点数，不是一个利率。</b>"
            # "Since 2022" used to open this sentence; Q1 2022 is in 2022 and
            # retained 6 basis points. The band starts with Q3 2022.
            f"{len(post)} 个 {post_from} 以来的季度里，留存利差落在 "
            f"{min(post):.0f} 到 {max(post):.0f} 个基点之间，"
            f"而同一笔余额上的毛收益率从 {min(post_gross):.0f} 个基点走到 "
            f"{max(post_gross):.0f} 个基点又回到 {coll['gross_bp'][-1]:.0f}。"
            f"最左边两格是零利率年代：{coll['period_labels'][0]} 的留存利差只有 "
            f"{coll['retained_bp'][0]:.0f} 个基点，净额 US${coll['net'][0]:.1f}M。"
            "<b>所以常规降息压缩的是分子和分母，留存的基点数基本不动；"
            "真正的风险是利率低到这个基点数没地方赚 —— 那种情形图上左端已经出现过一次。</b>"
            "反过来说，留存额随余额复利增长，而余额跟着未平仓合约走。"
            "长期的投资收益与利息分配两条原始线见 Exhibit {EX_INVEST}。"),
        "src_extra": (
            "再投资收益与利息分配支出是 10-Q 与 10-K 正文里逐季用文字给出的两个数（附注四与 "
            "MD&A，两处口径一致，本页交叉核对过）；余额取合并资产负债表的 Performance bonds "
            "and guaranty fund contributions 一行、按本季末与上季末取平均 D；"
            "投资收益取自合并损益表。"
            "<b>那是期末数不是日均数</b>：公司唯一一次公开的日均现金抵押品余额比本页这个"
            "两点平均低约 8%，因此本页的基点数相应偏低约 8%，趋势不受影响。"),
    }


def weighted_rpc(lng: dict) -> float:
    """This quarter's volume mix priced at last quarter's per-class rates."""
    total = sum(lng[f"adv_{k}"][-1] for k, _, _ in CLASSES)
    return sum(lng[f"adv_{k}"][-1] * lng[f"rpc_{k}"][-2] for k, _, _ in CLASSES) / total


# ── section three: what the next release settles ─────────────────────────────
#
# Every threshold here is the local analysis's own: its section 8, keyed into
# the `next_kpi` block with the clause it came from as `basis`. Every current
# value is read from the series at build time rather than stored beside the
# threshold, so a roll cannot leave last quarter's reading under this quarter's
# line. The two growth lines ("no year-on-year decline", "no sequential
# decline") are carried as ratios against 1.00 -- their threshold is zero growth,
# and a percentage headroom against zero is undefined.

KPI_FROM = "2016Q1"

# One chart per metric; a metric with two thresholds (ADV) draws both lines.
KPI_REFS = {
    "adj_margin": "EX_MARGIN_LINE",
    "adv": "EX_ADV_LINE",
    "rpc": "EX_RPC_LINE",
    "adj_opex": "EX_OPEX_LINE",
    "rates_adv_yoy": "EX_RATES_LINE",
    "market_data_qoq": "EX_MKTDATA_QOQ_LINE",
    # Due only in the quarter its `settles` names (Q1 2027 for the Q2 2026
    # analysis); until then it sits in the threshold table, not on a chart.
    "market_data_yoy": "EX_MKTDATA_YOY_LINE",
}


def kpi_history(staging: dict, reads: str) -> tuple[list[str], list[float], dict]:
    """One threshold metric's own history, ending at this quarter's reading."""
    fin, lng = staging["financials"], staging["long"]
    start = lng["quarters"].index(KPI_FROM)
    long_labels = lng["period_labels"][start:]

    def ratio(values: list[float], lag: int) -> list[float]:
        return [values[i] / values[i - lag] for i in range(start, len(values))]

    market_data = lng["market_data"]
    histories = {
        "adj_margin": (staging["period_labels"], fin["adj_margin_pct"],
                       {"fmt": "pct1", "ylab": "%", "name": "调整后营业利润率"}),
        "adj_opex": (staging["period_labels"], fin["adj_opex_ex_license"],
                     {"fmt": "f0c", "ylab": "US$M", "name": "调整后营业费用（除许可费）"}),
        "adv": (long_labels, lng["adv_k"][start:],
                {"fmt": "f0c", "ylab": "千手/日", "name": "季度 ADV"}),
        "rpc": (long_labels, lng["rpc"][start:],
                {"fmt": "usd3", "ylab": "US$/手", "name": "平均每手费率 RPC"}),
        "rates_adv_yoy": (long_labels, ratio(lng["adv_rates"], 4),
                          {"fmt": "f2", "ylab": "本季 ÷ 去年同季", "name": "利率类 ADV 本季 ÷ 去年同季",
                           "growth": "同比"}),
        "market_data_qoq": (long_labels, ratio(market_data, 1),
                            {"fmt": "f2", "ylab": "本季 ÷ 上季", "name": "行情数据收入本季 ÷ 上季",
                             "growth": "环比"}),
        "market_data_yoy": (long_labels,
                            [pct_change(market_data[i], market_data[i - 4])
                             for i in range(start, len(market_data))],
                            {"fmt": "pct1", "ylab": "同比 %", "name": "行情数据收入同比"}),
    }
    if reads not in histories:
        raise ValueError(f"a `next_kpi` entry reads {reads!r}, which build/cme.py does not know")
    return histories[reads]


def next_split(kpi: dict, period: str) -> tuple[list[dict], list[dict]]:
    """(upcoming, later): the lines the next release settles, and those that settle after it.

    A line with no `settles` is due next quarter; one whose `settles` names the
    next quarter is due then too, so a roll does not have to delete the key when
    the date arrives. One whose date has passed was carried forward by mistake.
    """
    following = next_period(period)
    upcoming, later = [], []
    for entry in kpi["quantified"]:
        settles = entry.get("settles")
        if settles and quarter_order(settles) < quarter_order(following):
            raise ValueError(f"next-quarter threshold {entry['id']!r} settles in {settles}, "
                             "which has passed: the roll should have dropped it")
        (later if settles and quarter_order(settles) > quarter_order(following) else upcoming).append(entry)
    return upcoming, later


def kpi_entries(staging: dict, kpi: dict) -> list[dict]:
    """The block's entries, each with this quarter's reading attached as ``current``."""
    return [{**entry, "current": kpi_history(staging, entry["reads"])[1][-1]}
            for entry in kpi["quantified"]]


def short_name(entry: dict) -> str:
    return entry.get("short", entry["metric"])


def kpi_label(entry: dict) -> str:
    """How an entry is named in the threshold table: one that is not settled by
    the next release says when it is."""
    return entry["metric"] + (f"（{entry['settles']} 结算）" if entry.get("settles") else "")


def basis_text(entry: dict, by_id: dict) -> str:
    """Which clause of the local analysis a threshold comes from, and its condition."""
    extra = []
    if entry.get("joint"):
        extra.append(f"与{short_name(by_id[entry['joint']])} 同时")
    if entry.get("consecutive", 1) > 1:
        extra.append(f"连续{cn_count(entry['consecutive'])}季")
    if entry.get("settles"):
        extra.append(f"{entry['settles']} 结算")
    return entry["basis"] + (f"（{'，'.join(extra)}）" if extra else "")


def breach_run(values: list[float], entry: dict) -> int:
    """How many quarters in a row, up to this one, sit on the wrong side of the line."""
    count = 0
    for value in reversed(values):
        if headroom(entry["direction"], entry["threshold"], value) >= 0:
            break
        count += 1
    return count


def current_text(entry: dict, spec: dict) -> str:
    text = unit_text(entry["unit"], entry["current"])
    if entry["unit"] == "times":
        text += f"（即{spec['growth']} {minus_sign(signed((entry['current'] - 1) * 100))}）"
    return text


def next_section(staging: dict, kpi: dict, context: dict | None) -> list[dict]:
    period = staging["period_labels"][-1]
    window = cn_count(len(staging["period_labels"]))
    entries = kpi_entries(staging, kpi)
    by_id = {entry["id"]: entry for entry in entries}
    upcoming_ids = {entry["id"] for entry in next_split(kpi, period)[0]}
    upcoming = [entry for entry in entries if entry["id"] in upcoming_ids]
    later = [entry for entry in entries if entry["id"] not in upcoming_ids]
    margin = {entry["id"]: headroom(entry["direction"], entry["threshold"], entry["current"])
              for entry in entries}
    breached = [entry for entry in upcoming if margin[entry["id"]] < 0]
    safe = [entry for entry in upcoming if margin[entry["id"]] >= 0]
    closest = min(safe, key=lambda entry: margin[entry["id"]]) if safe else None
    from_statement = sum(1 for entry in upcoming if entry.get("from") == "statement")
    from_table = sum(1 for entry in upcoming if entry.get("from") == "adv_table")
    joint = [entry for entry in upcoming if entry.get("joint")]
    searched = context["searched"] if context else "申报文件"

    def breach_words(entry: dict) -> str:
        values = kpi_history(staging, entry["reads"])[1]
        spec = kpi_history(staging, entry["reads"])[2]
        run, need = breach_run(values, entry), entry.get("consecutive", 1)
        return (f"{short_name(entry)}本季 {current_text(entry, spec)}，已经越线"
                + (f"；本地研究的这条线要的是连续{cn_count(need)}季，这是第{cn_ordinal(run)}格"
                   if run < need else ""))

    not_carried = kpi.get("not_carried", [])
    excluded = kpi.get("excluded", [])
    bar = headroom_exhibit(
        f"下季 {len(upcoming)} 条阈值："
        + (f"{'、'.join(short_name(entry) for entry in breached)}已越线" if breached else "没有一条越线")
        + (f"，离线最近的是{short_name(closest)}（{margin[closest['id']]:+.1f}%）" if closest else ""),
        upcoming, "current",
        note=(
            f"<b>{cn_count(len(upcoming))}条线的单位互不相同，所以画的是「距阈值还有百分之几」而不是原值</b>；"
            "原始单位见核对抽屉里的阈值表。正值在安全侧，负值已经越线"
            + ("：" + "；".join(breach_words(entry) for entry in breached) + "。" if breached else "，本季没有一条越线。")
            + (f"{'、'.join(dict.fromkeys(short_name(entry) for entry in joint))} 的"
               f"{cn_count(len(joint))}条线要和{short_name(by_id[joint[0]['joint']])} 同时失守才算数 —— "
               "量少了而费率守住，按分级费率的机制正是常态。" if joint else "")
            + (f"{cn_count(len(upcoming))}条全部可以在下一份业绩新闻稿里直接读到，不需要任何未披露的数据："
               f"{cn_count(from_statement)}条来自合并损益表与调整对账表，"
               f"{cn_count(from_table)}条来自同一份文件里的 ADV/RPC 五季表。"
               if from_statement + from_table == len(upcoming) else "")
            + f"<b>阈值全部取自本地研究（{period} 那一份季报分析的关键观察指标），不是公司指引</b>，"
            "每条出自哪一句列在阈值表的最后一栏。"
            + "".join(f"另有一条要到 {entry['settles']} 才结算：{short_name(entry)}不低于 "
                      f"{unit_text(entry['unit'], entry['threshold'])}（当前 {unit_text(entry['unit'], entry['current'])}），"
                      "只列在阈值表里，不进这张图。" for entry in later)
            + (f"关键观察指标里还有{cn_count(len(not_carried))}条本页读不到："
               + "".join(f"（{i}）{item['text']}" for i, item in enumerate(not_carried, 1))
               if not_carried else "")
            + (f"另有{cn_count(len(excluded))}类数据本页<b>不接入</b>，原因各不相同："
               + "".join(f"（{i}）{text.format(searched=searched)}" for i, text in enumerate(excluded, 1))
               if excluded else "")),
        src_extra=(f"阈值取自本地研究（{period} 季报分析），不是公司指引；当前值全部取自 {quarter_words(period)}"
                   "业绩新闻稿（合并损益表、调整对账表与 ADV/RPC 五季表），同比与环比倍数为本页相除 D。"),
    )
    bar["ref"] = "EX_HEADROOM"
    charts = [bar]

    groups: dict[str, list[dict]] = {}
    for entry in upcoming:
        groups.setdefault(entry["reads"], []).append(entry)
    for reads, group in groups.items():
        xlabels, values, spec = kpi_history(staging, reads)
        if reads not in KPI_REFS:
            raise ValueError(f"no threshold chart is defined for `next_kpi` metric {reads!r}")
        name = spec["name"] if len(group) > 1 else group[0]["metric"]
        head = group[0]
        chart = threshold_exhibit(
            f"{name}：下季阈值 {'与 '.join(unit_text(e['unit'], e['threshold']) for e in group)}，"
            f"当前 {unit_text(head['unit'], head['current'])}",
            xlabels, rounded(values), head["threshold"],
            xstep=LONG_STEP if len(xlabels) > 16 else None,
            fmt=spec["fmt"], ylab=spec["ylab"],
            actual_name=spec["name"],
            threshold_name=threshold_line_name(head, len(group)),
            note=threshold_note(staging, reads, group, xlabels, values, by_id, window),
            src_extra=threshold_source(reads, period),
        )
        for extra in group[1:]:
            chart["series"].append({"name": threshold_line_name(extra, len(group)),
                                    "values": [extra["threshold"]] * len(xlabels), "color": "GOLD"})
        chart["ref"] = KPI_REFS[reads]
        charts.append(chart)
    return charts


def threshold_line_name(entry: dict, siblings: int, label: str = "下季阈值") -> str:
    side = "上方" if entry["direction"] == "up" else "下方"
    label = (entry["metric"].split("（", 1)[1].rstrip("）")
             if siblings > 1 and "（" in entry["metric"] else label)
    return f"{label} {unit_text(entry['unit'], entry['threshold'])}（安全侧在{side}）"


def threshold_source(reads: str, period: str) -> str:
    where = {
        "adj_margin": "调整后营业利润 ÷ 总收入 D，分子取自各季业绩新闻稿的调整对账表",
        "adj_opex": "调整后费用合计（调整对账表）减去合并损益表的许可与其他费用协议一行 D",
        "adv": "各季业绩新闻稿五季表的 ADV 合计行",
        "rpc": "各季业绩新闻稿五季表的 Average RPC 一行",
        "rates_adv_yoy": "各季业绩新闻稿五季表的利率类 ADV，本季 ÷ 去年同季 D",
        "market_data_qoq": "合并损益表的行情数据与信息服务一行，本季 ÷ 上季 D",
        "market_data_yoy": "合并损益表的行情数据与信息服务一行，本季对去年同季的增速 D",
    }[reads]
    return f"{where}；阈值取自本地研究（{period} 季报分析），不是公司的任何披露。"


def threshold_note(staging: dict, reads: str, group: list[dict], xlabels: list[str],
                   values: list[float], by_id: dict, window: str) -> str:
    """What one threshold chart says, computed from its own history."""
    head = group[0]
    threshold = head["threshold"]
    lng = staging["long"]
    labels = staging["period_labels"]

    if reads == "adj_margin":
        below = [(xlabels[i], value) for i, value in enumerate(values) if value < threshold]
        # The first version said the threshold sat "a little below the window's
        # lowest cell", so that breaking it would be new. The window's lowest is
        # Q4 2024's 65.9% and Q4 2025 was 67.0%: it had been broken twice.
        if below:
            where = (f"窗口里有{cn_count(len(below))}季低于它（"
                     + "、".join(f"{label} 的 {value:.1f}%" for label, value in below)
                     + f"），所以「跌破」在这{window}个季度里发生过，不是新事。")
        else:
            where = f"它低于窗口内最低的一格，因此「跌破」意味着这{window}个季度里没有出现过的事。"
        return (
            "<b>余量条回答「哪条线破了」，这张回答「它是怎么走到这里的」。</b>"
            f"{window}个季度里最高的一格是 {xlabels[values.index(max(values))]} 的 "
            f"{max(values):.1f}%，最低是 {xlabels[values.index(min(values))]} 的 "
            f"{min(values):.1f}%，本季 {values[-1]:.1f}%。"
            f"阈值 {threshold:.1f}% 取自本地研究的{head['basis']}，不是公司的任何披露：" + where
            + f"<b>这张图停在{window}季，是被披露挡住的</b>：CME 直到 2025-10-22 的"
            "第三季业绩新闻稿才第一次印出「Reconciliation of Adjusted Operating Income」表，"
            "而那张表只带一列去年同期，所以调整后营业利润最早只到 2024Q3。"
            "（那张表的出现本身有出处：SEC 在 2025-09-12 的问询函里要求公司要么量化这个指标"
            "并附对账、要么不再使用这个词。）"
            f"分母那条总收入本页有 {len(lng['quarters']) - lng['quarters'].index(KPI_FROM)} 季，"
            "但两条腿必须同窗。"
            "<b>不能拿一直都有的调整后净利润对账表反推</b> —— 公司自己的脚注写明两张表口径不同"
            "（净利润那张不含递延薪酬、摊销含权益法部分），在两表并存的 2026Q2 实测差 "
            "US$9.1M，折合利润率约 0.5 个百分点。")

    if reads == "adv":
        partner = by_id[head["joint"]]
        top = max(entry["threshold"] for entry in group)
        bottom = min(entry["threshold"] for entry in group)
        clear_top = sum(1 for value in values if value >= top)
        clear_bottom = [xlabels[i] for i, value in enumerate(values) if value >= bottom]
        return (
            f"<b>两条线都要和{short_name(partner)} 跌破 {unit_text(partner['unit'], partner['threshold'])} "
            "同时发生才算数</b>："
            + "，".join(f"{unit_text(entry['unit'], entry['threshold'])}那条是本地研究的{entry['basis']}"
                       for entry in group)
            + "。量少了而费率守住，按分级费率的机制正是常态，见 Exhibit {EX_ADV_LONG}。"
            f"<b>这两条线划在{years_of(len(values))}年的高位上</b>：{len(values)} 季里 ADV 不低于 "
            f"{unit_text(head['unit'], top)}的只有{cn_count(clear_top)}季、不低于 "
            f"{unit_text(head['unit'], bottom)}的只有{cn_count(len(clear_bottom))}季，"
            f"最早的一季是 {clear_bottom[0]}。"
            + (f"去年同一季 {xlabels[-4]} 只有 {unit_text(head['unit'], values[-4])}，比两条线都低。"
               if values[-4] < bottom else ""))

    if reads == "rpc":
        below = [i for i, value in enumerate(values) if value < threshold]
        recent_below = [xlabels[i] for i in below if i >= len(values) - len(labels)]
        below_runs = runs([value < threshold for value in values])
        longest = max(below_runs, key=lambda span_: (span_[1] - span_[0], span_[0])) if below_runs else None
        adv = lng["adv_k"]
        mechanical = values[-1] > values[-2] and adv[-1] < adv[-2]
        upside = head.get("upside")
        # The first version called $0.670 "a little below the lowest cell of the
        # eight-quarter window"; Q3 2024 ($0.666) and Q1 2026 ($0.652) are both in
        # that window and both under it. And the long stretch under it is
        # 2021-2023, not "2019-2021".
        return (
            "<b>这条线要和成交量一起读，单独看会给出相反的结论。</b>"
            f"本季 ${values[-1]:.3f}，比上季{'高' if values[-1] >= values[-2] else '低'} "
            f"${abs(values[-1] - values[-2]):.3f}"
            + ("，但 Exhibit {EX_ADV_LONG} 说明这个回升是成交量下滑的机械结果。" if mechanical else "。")
            + f"<b>把窗口拉到 {len(values)} 季看这条阈值线</b>："
            f"{xlabels[0].split()[1]}{xlabels[0].split()[0]} 起有 {len(below)} 个季度落在它下面"
            + (f"，其中{cn_count(len(recent_below))}季就在最近{window}季里（{'、'.join(recent_below)}）"
               if recent_below else "")
            + f" —— 费率从 {xlabels[0]} 的 ${values[0]:.3f} 一路下行到"
            f"{years_of(len(values))}年低点 ${min(values):.3f}（{xlabels[values.index(min(values))]}）"
            "才回升到今天。"
            + (f"跌破它不是「没出现过的事」，是回到 {xlabels[longest[0]].split()[1]}–"
               f"{xlabels[longest[1] - 1].split()[1]} 年的常态。" if longest else "")
            + f"阈值 {unit_text(head['unit'], threshold)} 取自本地研究的{head['basis']}。"
            + (f"<b>所以真正有信息量的组合是「量回来了而费率没掉」</b>：若下季 ADV 回到 "
               f"{unit_text('contracts_k', upside['adv'])}以上而费率仍不低于 "
               f"{unit_text('usd_rpc', upside['rpc'])}，才说明存在与成交量无关的费率改善"
               f"（本地研究的{upside['basis']}）；若量价同时落到阈值以下，则说明连分级费率的缓冲也没兜住。"
               if upside else ""))

    if reads == "adj_opex":
        upside = head.get("upside")
        top_two = sorted(range(len(values)), key=lambda i: values[i], reverse=True)[:2]
        peak = top_two[0]
        return (
            f"<b>本地研究的警戒线是 {unit_text(head['unit'], threshold)}：下季超过它，就算费用指引失控</b>"
            + ((f"；反方向还有一条 {unit_text(head['unit'], upside['below'])} —— 低于它说明全年指引留有余量"
                + (f"，本季 {unit_text(head['unit'], values[-1])} 已经在它下面" if values[-1] < upside['below'] else ""))
               if upside else "")
            + f"。{window}个季度里最高的一格是 {xlabels[peak]} 的 US${values[peak]:,.1f}M"
            + (f"，离警戒线只差 US${threshold - values[peak]:,.1f}M" if 0 < threshold - values[peak] < 10 else "")
            + ("；最高的两格都是第四季度（" + "、".join(f"{xlabels[i]} 的 US${values[i]:,.1f}M" for i in top_two) + "）"
               if all(xlabels[i].startswith("Q4") for i in top_two) else "")
            + f"，下季的去年同季 {xlabels[-4]} 是 US${values[-4]:,.1f}M。"
            f"<b>这条线只有{window}季</b>：调整后费用合计是从 2025 年第三季度那期业绩新闻稿起才印的"
            "（见 Exhibit {EX_OPEX}）。本地研究定这条线时参照的是电话会全年费用指引隐含的下半年节奏；"
            "本页照录阈值，不接入那条指引本身。")

    if reads in ("rates_adv_yoy", "market_data_qoq"):
        spec = kpi_history(staging, reads)[2]
        need = head.get("consecutive", 1)
        run = breach_run(values, head)
        negative = [i for i, value in enumerate(values) if value < threshold]
        streaks = [(a, b) for a, b in runs([value < threshold for value in values]) if b - a >= need]
        if reads == "rates_adv_yoy":
            base = (f"下季只要利率 ADV 低于去年同季（{lng['period_labels'][-4]}）的 "
                    f"{unit_text('contracts_k', lng['adv_rates'][-4])}")
            tail = ("利率是 FMX 正在挑战的那条产品线（见 Exhibit {EX_CLASS_ADV}）；"
                    "FMX 自己的成交量本页不发布。")
        else:
            base = (f"下季只要行情数据收入低于本季的 US${lng['market_data'][-1]:,.1f}M")
            tail = head.get("caveat", "")
        rule = f"本地研究这条线（{head['basis']}）要的是连续{cn_count(need)}季"
        return (
            f"<b>本季 {values[-1]:.2f}x，即{spec['growth']} {minus_sign(signed((values[-1] - 1) * 100))}"
            + (f"：{rule}，这是第{cn_ordinal(run)}格</b>" if 0 < run < need else
               f"：{rule}，已经触发</b>" if run >= need else
               f"，在线的安全一侧；{rule}</b>")
            + (f"。{base}，就是连续第{cn_ordinal(run + 1)}季" if run else f"。{base}，才是第一格")
            + ("，这条线就触发了。" if run + 1 >= need else "。")
            + f"{len(values)} 季里{spec['growth']}为负的有 {len(negative)} 季，"
            + (f"连续{cn_count(need)}季以上的有{cn_count(len(streaks))}段："
               + "、".join(f"{xlabels[a]}–{xlabels[b - 1]}（{cn_count(b - a)}季）" for a, b in streaks) + "。"
               if streaks else f"从来没有连续{cn_count(need)}季过。")
            + tail)

    if reads == "market_data_yoy":
        side = [value for value in values if headroom(head["direction"], threshold, value) < 0]
        return (f"<b>本季同比 {minus_sign(signed(values[-1]))}，本地研究这条线（{head['basis']}）是 "
                f"{unit_text(head['unit'], threshold)}</b>"
                + (f"，它在 {head['settles']} 结算" if head.get("settles") else "")
                + f"。{len(values)} 季里同比落在这条线{'下方' if head['direction'] == 'up' else '上方'}"
                f"的有 {len(side)} 季。")

    raise ValueError(f"no threshold note is written for `next_kpi` metric {reads!r}")


# ── section four: the long series ────────────────────────────────────────────

def routine_section(staging: dict) -> list[dict]:
    lng = staging["long"]
    coll = staging["collateral"]
    labels = lng["period_labels"]
    n = len(labels)
    fin = staging["financials"]

    adv_long = {
        "ref": "EX_ADV_LONG",
        "kind": "bar_line_dual",
        "title": (f"{n} 季量与价：ADV {lng['adv_k'][-1] / 1000:.1f}M 手/日，"
                  f"平均每手费率 ${lng['rpc'][-1]:.3f}"),
        "xlabels": labels,
        "bar": {"name": "季度 ADV（千手/日）", "color": "BLUE", "values": rounded(lng["adv_k"])},
        "line": {"name": "平均每手费率 RPC", "color": "NAVY", "values": rounded(lng["rpc"]),
                 "yfmt": "usd3"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "千手/日", "ylab2": "US$/手", "xstep": LONG_STEP,
        "note": (
            f"<b>{cn_count(n)}个季度里，成交量与每手费率有 {opposite_moves(lng)} 个季度朝相反方向走。</b>"
            f"把两者的环比变动回归，斜率是 {rpc_slope(lng):.2f}（费率环比 % 对成交量环比 %），"
            f"R² {rpc_r2(lng):.2f}。这不是定价能力，是分级费率的算术："
            "客户当月累计成交量越大，边际合约落进的档位费率越低，所以量涨价跌、量跌价涨。"
            f"窗口内 ADV 最低的一季是 {labels[lng['adv_k'].index(min(lng['adv_k']))]}"
            f"（{min(lng['adv_k']) / 1000:.1f}M 手/日），"
            f"最高的是 {labels[lng['adv_k'].index(max(lng['adv_k']))]}"
            f"（{max(lng['adv_k']) / 1000:.1f}M 手/日）。"),
        "src_extra": ("每季 ADV 与 RPC 取自当季业绩新闻稿的五季表；"
                      "同一个季度在其后四份新闻稿里重复出现，逐份核对无差异。"),
    }

    contracts_qoq = qoq(lng["contracts_m"])
    revenue_qoq = qoq(lng["total_revenues"])
    fee_qoq = qoq(lng["clearing_fees"])
    beta_rev, r2_rev = slope_and_r2(contracts_qoq, revenue_qoq)
    beta_fee, r2_fee = slope_and_r2(contracts_qoq, fee_qoq)
    on_line = on_the_slope(lng)
    beta = {
        "ref": "EX_BETA",
        "kind": "lines",
        "title": (f"{len(contracts_qoq)} 次环比变动：成交量动 1%，总收入只动 "
                  f"{beta_rev:.2f}%（R² {r2_rev:.2f}）"),
        "xlabels": labels[1:],
        "series": [
            {"name": "成交合约数环比", "values": rounded(contracts_qoq), "color": "GRAY"},
            {"name": "清算与交易费环比", "values": rounded(fee_qoq), "color": "BLUE"},
            {"name": "总收入环比", "values": rounded(revenue_qoq), "color": "NAVY"},
        ],
        "fmt": "pct0", "yfmt": "pct0", "label_fmt": "pct0",
        "ylab": "环比 %", "xstep": LONG_STEP, "zero_line": True,
        "note": (
            "<b>三条线的形状一样，振幅一层比一层小 —— 这就是这家公司最被低估的属性。</b>"
            f"把成交合约数的环比变动作自变量：清算与交易费的斜率是 {beta_fee:.2f}"
            f"（R² {r2_fee:.2f}），总收入的斜率是 {beta_rev:.2f}（R² {r2_rev:.2f}）。"
            f"本季自己的读数是成交量 {contracts_qoq[-1]:+.1f}%、清算费 {fee_qoq[-1]:+.1f}%、"
            f"总收入 {revenue_qoq[-1]:+.1f}%，"
            + ("落在这条长期关系上而不是外面。" if on_line else "偏离了这条长期关系。")
            + "<b>它是对称的，这一点比抗跌更重要</b>：同一个系数意味着量能回升时收入也只跟"
            + ("一半多一点" if 0.5 < beta_rev < 0.7 else f"{beta_rev:.2f} 倍")
            + f"，所以用本季 ${lng['rpc'][-1]:.3f} 的费率去乘一个高成交量假设，"
            "会同时高估价和量。"),
        "src_extra": ("成交合约数 = ADV × 交易日（两者均为公司披露值）D；收入取自合并损益表。"
                      "斜率与 R² 为对本页所载序列的最小二乘回归 D，可用图下数据复算。"),
    }

    split = lng["quarters"].index("2018Q4")
    residual = {
        "ref": "EX_RESIDUAL",
        "kind": "lines",
        "title": (f"清算与交易费拆成两块：期货与期权 US${lng['fo_clearing_fees'][-1]:,.0f}M，"
                  f"其余 US${lng['other_clearing_fees'][-1]:,.0f}M"),
        "xlabels": labels,
        "series": [
            {"name": "清算与交易费（报表值）", "values": rounded(lng["clearing_fees"]), "color": "NAVY"},
            {"name": "期货与期权：ADV × 交易日 × RPC", "values": rounded(lng["fo_clearing_fees"]),
             "color": "BLUE"},
            {"name": "其余（现券、外汇等）", "values": rounded(lng["other_clearing_fees"]),
             "color": "GOLD"},
        ],
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c", "end_label": True,
        "ylab": "US$M", "xstep": LONG_STEP,
        "break_at": split,
        "break_label": "NEX（BrokerTec 与 EBS）并表（2018Q4）",
        "note": (
            "<b>公司披露的 ADV 与 RPC 只覆盖期货与期权，而报表的清算与交易费还包含 BrokerTec "
            "的现券与 EBS 的外汇 —— 这张图把那块差额单独画出来，因为本页所有量价分析都不覆盖它。</b>"
            f"差额本季 US${lng['other_clearing_fees'][-1]:,.1f}M，占清算与交易费 "
            f"{100 * lng['other_clearing_fees'][-1] / lng['clearing_fees'][-1]:.1f}%。"
            "<b>这条差额线自己就是这套推算是否成立的证据</b>：它在 2018 年第三季度之前的"
            f"{cn_count(split)}个季度里从没超过 US${max(lng['other_clearing_fees'][:split]):,.0f}M，"
            "而 2018 年 11 月 NEX 并表的那一个季度直接跳到 "
            f"US${lng['other_clearing_fees'][split]:,.0f}M，"
            + ("此后再没回去过" if min(lng["other_clearing_fees"][split:]) > max(lng["other_clearing_fees"][:split])
               else "此后回落过")
            + " —— 台阶落在收购当季，而不是落在任何一次费率或口径变动上。"
            "<b>这块的内部量价结构完全不可见</b>：公司不公布现券与外汇的成交量或费率，"
            "所以本页不对它做任何拆解，只标出它有多大。"),
        "src_extra": ("报表值取自合并损益表；期货与期权部分为公司披露的 ADV × 交易日 × RPC D；"
                      "差额为两者相减 D。"),
    }

    income = lng["investment_income"]
    peak = max(income)
    invest = {
        "ref": "EX_INVEST",
        "kind": "lines",
        # The title used to read "from near zero to US$1,430M and back down":
        # US$1,430M is this quarter, after the fall; the peak was US$1,777M.
        "title": (f"{n} 季投资收益与利息分配支出：从近乎为零到 US${peak:,.0f}M"
                  + (f" 再回落到 US${income[-1]:,.0f}M" if income[-1] < peak else "")),
        "xlabels": labels,
        "series": [
            {"name": "投资收益", "values": rounded(lng["investment_income"]), "color": "NAVY"},
            {"name": "其他非经营收支（主要是付给清算会员的利息分配）",
             "values": rounded(lng["other_nonop"]), "color": "BLUE"},
        ],
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c", "end_label": True,
        "ylab": "US$M", "xstep": LONG_STEP, "zero_line": True,
        "note": (
            "<b>两条线几乎是镜像，而这正是它们容易被读错的原因。</b>"
            f"投资收益从 {labels[0]} 的 US${lng['investment_income'][0]:,.1f}M 涨到本季的 "
            f"US${lng['investment_income'][-1]:,.0f}M，看起来是一条巨大的利率敞口；"
            "但同期公司付给清算会员的利息分配几乎等额地跟着涨。"
            "<b>本页不把这两条相减当成利差</b>：其他非经营收支里还有非抵押品的项目，"
            "2021 年那一格是正的，因为里面装着一笔与利率无关的一次性收益。"
            "真正只属于抵押品的那一段公司在 10-Q 里单独用文字给出，见 Exhibit {EX_SPREAD}。"),
        "src_extra": "两条均为合并损益表的原始行，未做任何合并或净额处理。",
    }

    md_share = [100 * m / r for m, r in zip(lng["market_data"], lng["total_revenues"])]
    md_multiple = lng["market_data"][-1] / lng["market_data"][0]
    cf_multiple = lng["clearing_fees"][-1] / lng["clearing_fees"][0]
    carried = [lng["quarters"][i] for i in range(4, n)
               if lng["market_data"][i] - lng["market_data"][i - 4]
               >= lng["total_revenues"][i] - lng["total_revenues"][i - 4] > 0]
    stalled = [name for name, change, _ in revenue_legs(fin) if name != "行情数据" and change <= 0]
    if carried and carried[-1] == lng["quarters"][-1]:
        if len(carried) == 1:
            carry_words = "<b>本季是这条线第一次单独扛起全公司的同比增长</b>，"
        else:
            carry_words = (f"<b>本季是这条线第{cn_ordinal(len(carried))}次单独扛起全公司的同比增长"
                           f"（上一次是 {carried[-2]}）</b>，")
        carry_words += ("不是因为它突然加速，而是因为"
                        + ("、".join(stalled) + "同比转负" if stalled else "另外两条腿停了")
                        + "。")
    else:
        carry_words = ""
    md_long = {
        "ref": "EX_MKTDATA_LONG",
        "kind": "bar_line_dual",
        "title": (f"{n} 季行情数据收入：US${lng['market_data'][0]:,.0f}M → "
                  f"US${lng['market_data'][-1]:,.0f}M，占总收入 {md_share[-1]:.1f}%"),
        "xlabels": labels,
        "bar": {"name": "行情数据与信息服务收入", "color": "MBLUE",
                "values": rounded(lng["market_data"])},
        "line": {"name": "占总收入 (RHS)", "color": "NAVY", "values": rounded(md_share),
                 "yfmt": "pct1"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M", "ylab2": "%", "xstep": LONG_STEP,
        "note": (
            # The first version said the share "barely moved because clearing
            # fees grew just as much"; they grew 2.3x to market data's 2.9x.
            f"<b>这条线在{cn_count(n // 4)}年{'半' if n % 4 == 2 else ''}里涨到期初的 {md_multiple:.1f} 倍，"
            f"而它在总收入里的占比只从 {md_share[0]:.1f}% 走到 {md_share[-1]:.1f}% —— "
            f"因为清算费同期也涨到了期初的 {cf_multiple:.1f} 倍。</b>"
            f"窗口内的低点是 {labels[md_share.index(min(md_share))]} 的 {min(md_share):.1f}%。"
            + carry_words),
        "src_extra": "合并损益表的行情数据与信息服务一行与总收入一行；占比为两者相除 D。",
    }

    # The 2017 tax act remeasured deferred tax liabilities in one quarter and
    # produced an effective rate of -411%. Drawn on one axis with the rest, that
    # single point compresses the other fifty-three into the top 5% of the
    # canvas -- a chart that passes every gate and shows nothing. The window
    # therefore starts where the statutory rate does: 35% federal before 2018,
    # 21% after, which is two regimes rather than one series anyway.
    tax_start = lng["quarters"].index("2016Q1")
    tax_labels = labels[tax_start:]
    outlier = lng["effective_tax_outlier"]
    outlier_at = lng["quarters"].index(outlier["quarter"]) - tax_start
    tax_values = [
        None if index == outlier_at else value
        for index, value in enumerate(lng["effective_tax_pct"][tax_start:])
    ]
    reform_at = lng["quarters"].index("2018Q1") - tax_start
    before = [v for i, v in enumerate(tax_values) if v is not None and i < reform_at]
    after = [v for i, v in enumerate(tax_values) if v is not None and i >= reform_at]
    low_after = next(i for i, v in enumerate(tax_values) if v == min(after))
    tax = {
        "ref": "EX_TAX",
        "kind": "lines",
        "title": (f"{len(tax_labels)} 季 GAAP 有效税率：税改前均值 "
                  f"{sum(before) / len(before):.1f}%，税改后 {sum(after) / len(after):.1f}%，"
                  f"本季 {tax_values[-1]:.1f}%"),
        "xlabels": tax_labels,
        "series": [
            {"name": "GAAP 有效税率", "values": rounded(tax_values), "color": "NAVY"},
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
        "ylab": "%", "xstep": LONG_STEP,
        "note": (
            "<b>线上那个缺口是 2017 年第四季度，它是有意留空的。</b>"
            f"美国税改当季一次性重估递延所得税负债，使所得税变成大额净收益，"
            f"有效税率算出来是 {outlier['value']:.1f}% —— 那不是一个税率，"
            f"画进同一条线会把其余{cn_count(len(tax_labels) - 1)}格压进画布顶端百分之五。本页留空，不截轴、不平滑。"
            "<b>缺口两侧是两套制度</b>：联邦法定税率 2018 年 1 月从 35% 降到 21%，"
            f"图上表现为税改前 {len(before)} 季均值 {sum(before) / len(before):.1f}% "
            f"与之后 {len(after)} 季的 {sum(after) / len(after):.1f}%，"
            f"差 {sum(before) / len(before) - sum(after) / len(after):.1f}pp。"
            "<b>这张图上一版从 2018Q1 起，正是为了避开那个缺口</b> —— "
            "代价是把这一整级台阶也一起切掉了；本站的窗口现在自 2016Q1 起，"
            "所以改成留一个看得见的洞，而不是一个看不见的起点。"
            f"税改后最低的一季是 {tax_labels[low_after]} 的 {min(after):.1f}%，"
            f"最高 {max(after):.1f}%；本季 {tax_values[-1]:.1f}%，比上季"
            + (f"低 {(tax_values[-2] - tax_values[-1]) * 100:.0f} 个基点。"
               if tax_values[-1] < tax_values[-2] else
               f"高 {(tax_values[-1] - tax_values[-2]) * 100:.0f} 个基点。")
            + "公司的调整口径把当季的离散税项整笔剔除，所以它只影响 GAAP 这一条线，"
            "不影响 Exhibit {EX_EPS} 里的调整后每股收益。"),
        "src_extra": ("所得税费用 ÷ 税前利润，两者均取自合并损益表 D。"
                      "2013Q1–2015Q4 的读数仍在原始序列里，只是不画在这张图上。"),
    }
    class_yoy = {name: pct_change(lng[f"adv_{key}"][-1], lng[f"adv_{key}"][-5])
                 for key, name, _ in CLASSES}
    top_riser = max(class_yoy, key=class_yoy.get)
    class_adv = {
        "ref": "EX_CLASS_ADV",
        "kind": "lines",
        "title": f"{n} 季六个品种的 ADV：利率一条腿占 {100 * lng['adv_rates'][-1] / lng['adv_k'][-1]:.0f}%",
        "xlabels": labels,
        "series": [
            {"name": name, "values": rounded(lng[f"adv_{key}"]), "color": color}
            for key, name, color in CLASSES
        ],
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "千手/日", "xstep": LONG_STEP,
        "note": (
            # It used to say rates was the "only" product line named as under
            # challenge; the quarter's call spent most of its time on perpetual
            # futures, which are pitched against equity-index and crypto futures.
            "<b>利率是这家公司的主干，也是 FMX 正面挑战的那条产品线。</b>"
            f"本季利率 ADV {lng['adv_rates'][-1]:,.0f} 千手、同比 "
            f"{signed(pct_change(lng['adv_rates'][-1], lng['adv_rates'][-5]))}；"
            # "The largest move of the six" was equity's +12.7%; energy's -13.5%
            # is larger. The sentence now names the largest *rise*, and says so.
            + (f"{top_riser}同比 {signed(class_yoy[top_riser])}，是本季六个品种里同比涨得最多的一条。"
               if class_yoy[top_riser] > 0 else
               "六个品种同比全部下降。" if class_yoy[top_riser] < 0 else "六个品种同比没有一个上涨。")
            + f"窗口内利率 ADV 的最高一季是 {labels[lng['adv_rates'].index(max(lng['adv_rates']))]} 的 "
            f"{max(lng['adv_rates']):,.0f} 千手。"
            "<b>本页不发布任何竞争对手的成交量</b>：那些数字来自对手方的季报与新闻稿，"
            "口径与这张图的合约张数不可比，混在一起画会造出一个两边都不成立的份额。"),
        "src_extra": "各季业绩新闻稿的分品种 ADV 五季表；均为公司披露值。",
    }
    return [adv_long, beta, residual, invest, md_long, class_adv, tax]


def on_the_slope(lng: dict) -> bool:
    """Whether this quarter's revenue move sits within two standard deviations
    of the long-run revenue-on-contracts line (the brief and Exhibit EX_BETA
    both say so, and both must stop saying it the quarter it stops being true)."""
    contracts_qoq, revenue_qoq = qoq(lng["contracts_m"]), qoq(lng["total_revenues"])
    beta, _ = slope_and_r2(contracts_qoq, revenue_qoq)
    intercept = statistics.fmean(revenue_qoq) - beta * statistics.fmean(contracts_qoq)
    residuals = [y - (intercept + beta * x) for x, y in zip(contracts_qoq, revenue_qoq)]
    return abs(residuals[-1]) <= 2 * statistics.pstdev(residuals)


def opposite_moves(lng: dict) -> int:
    a, r = qoq(lng["adv_k"]), qoq(lng["rpc"])
    return sum(1 for x, y in zip(a, r) if x * y < 0)


def rpc_slope(lng: dict) -> float:
    return slope_and_r2(qoq(lng["adv_k"]), qoq(lng["rpc"]))[0]


def rpc_r2(lng: dict) -> float:
    return slope_and_r2(qoq(lng["adv_k"]), qoq(lng["rpc"]))[1]


# ── payload ──────────────────────────────────────────────────────────────────

def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    fin = staging["financials"]
    fees = fin["clearing_fees"]
    return [f"Revenue ${fin['total_revenues'][-1] / 1000:.2f}B",
            minus_sign(f"清算费同比 {(fees[-1] / fees[-5] - 1) * 100:+.1f}%"),
            f"调整后 OpM {fin['adj_margin_pct'][-1]:.1f}%"]


def release_source(staging: dict) -> dict:
    label = f"CME Group {quarter_words(staging['period_labels'][-1])}业绩新闻稿"
    found = next((item for item in staging["sources"] if item["label"].startswith(label)), None)
    if found is None:
        raise ValueError(f"series `sources` has no entry for the {label}: add this "
                         "quarter's release with the roll")
    return found


def quarter_order(label: str) -> tuple[int, int]:
    """``'Q3 2026'`` / ``'2026Q3'`` → ``(2026, 3)``, so two quarter labels can be compared."""
    quarter, year = display_period(label).split()
    return int(year), int(quarter[1])


def settlement_blocks(staging: dict, period: str) -> tuple[bool, dict | None, dict | None]:
    """Whether this is the first local analysis, and what the previous one left open.

    Section one is 「上季跟踪指标兑现了吗」: it settles the previous analysis's
    follow-up questions (`followup_closure`) and thresholds
    (`prior_kpi_settlement`), then the company's own guidance. The first CME
    analysis covers Q2 2026 and says it has no previous one, so that quarter
    settles only the guidance -- and says why. Any later quarter has a previous
    analysis by construction, so a roll that leaves both blocks out would publish
    a section one that silently skipped it; that stops the build instead.
    """
    record = staging.get("analysis_record")
    first = record is not None and display_period(record["first_period"]) == display_period(period)
    closure = stamped_block(staging, "followup_closure", period)
    prior = stamped_block(staging, "prior_kpi_settlement", period)
    present = [key for key, block in (("followup_closure", closure), ("prior_kpi_settlement", prior))
               if block is not None]
    if first and present:
        raise ValueError(f"{period} is the first CME analysis, so there is nothing for "
                         f"{', '.join(present)} to settle")
    if not first and not present:
        raise ValueError(f"{period} is not the first CME analysis: section one must settle the "
                         "previous one -- add `followup_closure` (its section 0) and "
                         "`prior_kpi_settlement` (its section 8 thresholds) to the series")
    set_in = {block["set_in"] for block in (closure, prior) if block is not None}
    if len(set_in) > 1:
        raise ValueError(f"`followup_closure` and `prior_kpi_settlement` name different analyses: {sorted(set_in)}")
    if set_in and quarter_order(next(iter(set_in))) >= quarter_order(period):
        raise ValueError(f"the settlement blocks say they were set in {next(iter(set_in))!r}, "
                         f"which is not before {period!r}")
    return first, closure, prior


# ── section one (a)(b): what the previous local analysis left open ───────────
#
# From the second analysis on, section one opens with what the previous one
# asked and set. `prior_kpi_settlement.quantified` is the previous quarter's
# `next_kpi.quantified`, moved as it stood -- same ids, `reads`, directions and
# qualifiers -- so a roll copies it rather than re-keys it, and every reading it
# is settled against is taken here from the series.

def closure_counts(closure: dict) -> list[int]:
    """The count per verdict, from the block's own items when it lists them."""
    labels = closure["labels"]
    items = closure.get("items")
    if items is None:
        if len(closure["counts"]) != len(labels):
            raise ValueError("`followup_closure` has a count for every label or it is not a tally")
        return list(closure["counts"])
    unknown = sorted({item["verdict"] for item in items} - set(labels))
    if unknown:
        raise ValueError(f"`followup_closure` items carry verdicts that are not labels: {unknown}")
    counted = [sum(1 for item in items if item["verdict"] == label) for label in labels]
    if "counts" in closure and list(closure["counts"]) != counted:
        raise ValueError(f"`followup_closure.counts` {closure['counts']} disagrees with its own items {counted}")
    return counted


def closure_exhibit(closure: dict) -> dict:
    counts = closure_counts(closure)
    total = sum(counts)
    items = closure.get("items") or []
    groups = [(label, [item for item in items if item["verdict"] == label])
              for label in closure["labels"][1:]]
    detail = "；".join(f"{label}的{cn_count(len(group))}条是"
                      + "、".join(f"「{item.get('short', item['question'])}」" for item in group)
                      for label, group in groups if group)
    return {
        "ref": "EX_CLOSURE",
        "kind": "bars_labeled",
        "title": (f"上季 {total} 条待验证问题："
                  + "、".join(f"{count} 条{label}" for label, count in zip(closure["labels"], counts))),
        "xlabels": list(closure["labels"]),
        "values": counts,
        "legend": "问题条数",
        "fmt": "f0", "yfmt": "f0", "label_fmt": "f0",
        "ylab": "条",
        "note": (f"上季（{closure['set_in']}）那一份本地分析在文末留下 {total} 条待验证问题，"
                 "本季那一份在第 0 节逐条判定。" + (detail + "。" if detail else "")),
        "src_extra": (f"问题清单来自上季（{closure['set_in']}）本地分析稿的 Follow-up Questions；"
                      "判定照录本季本地分析稿第 0 节，本页不改判"
                      + ("，逐条见核对抽屉。" if items else "。")),
    }


def closure_table(closure: dict) -> dict | None:
    items = closure.get("items")
    if not items:
        return None
    return {
        "n": 0,
        "title": f"上季（{closure['set_in']}）留下的待验证问题：本季逐条判定",
        "headers": ["#", "问题", "判定", "依据"],
        "rows": [[str(i), item["question"], item["verdict"], item.get("evidence", "—")]
                 for i, item in enumerate(items, 1)],
    }


def settlement_entries(staging: dict, prior: dict, period: str) -> tuple[list[dict], list[dict]]:
    """(due, later): the previous analysis's thresholds with this quarter's reading as ``actual``."""
    due, later = [], []
    for entry in prior["quantified"]:
        settles = entry.get("settles")
        if settles and quarter_order(settles) < quarter_order(period):
            raise ValueError(f"prior threshold {entry['id']!r} was due in {settles}, before {period}: "
                             "it should have been settled then, or dropped")
        target = later if settles and quarter_order(settles) > quarter_order(period) else due
        target.append({**entry, "actual": kpi_history(staging, entry["reads"])[1][-1]})
    return due, later


def settlement_verdicts(staging: dict, due: list[dict], every: list[dict]) -> dict[str, dict]:
    """Per threshold: did the reading cross the line, and did the analysis's own
    trigger fire -- which for a joint line needs its partner to cross too, and
    for a consecutive line needs the run of crossed quarters to be long enough."""
    by_id = {entry["id"]: entry for entry in every}
    verdicts = {}
    for entry in due:
        values = kpi_history(staging, entry["reads"])[1]
        crossed = headroom(entry["direction"], entry["threshold"], entry["actual"]) < 0
        if entry.get("joint") and entry["joint"] not in by_id:
            raise ValueError(f"prior threshold {entry['id']!r} is joint with {entry['joint']!r}, "
                             "which the block does not carry")
        partners = ([by_id[entry["joint"]]] if entry.get("joint") else
                    [other for other in every if other.get("joint") == entry["id"]])
        partners_crossed = [other for other in partners
                            if headroom(other["direction"], other["threshold"],
                                        kpi_history(staging, other["reads"])[1][-1]) < 0]
        run, need = breach_run(values, entry), entry.get("consecutive", 1)
        verdicts[entry["id"]] = {
            "crossed": crossed, "run": run, "need": need,
            "partners": partners, "partners_crossed": partners_crossed,
            "triggered": crossed and run >= need and (not partners or bool(partners_crossed)),
        }
    return verdicts


def value_text(entry: dict, value: float, spec: dict) -> str:
    text = unit_text(entry["unit"], value)
    if entry["unit"] == "times":
        text += f"（即{spec['growth']} {minus_sign(signed((value - 1) * 100))}）"
    return text


def settlement_line_note(staging: dict, entry: dict, verdict: dict, by_id: dict) -> str:
    xlabels, values, spec = kpi_history(staging, entry["reads"])
    up = entry["direction"] == "up"
    words = (f"{basis_text(entry, by_id)}：{'不低于' if up else '不高于'} "
             f"{unit_text(entry['unit'], entry['threshold'])}；本季 {value_text(entry, entry['actual'], spec)}，"
             f"{'越线' if verdict['crossed'] else '守住'}（余量 "
             f"{headroom(entry['direction'], entry['threshold'], entry['actual']):+.1f}%）")
    if verdict["crossed"] and verdict["partners"]:
        names = "、".join(dict.fromkeys(short_name(other) for other in verdict["partners"]))
        words += (f"。这条要和{names} 同时失守才算触发："
                  + (f"{names} 本季也越线，所以触发" if verdict["partners_crossed"] else
                     f"{names} 本季守住了，所以没有触发"))
    if verdict["need"] > 1:
        words += (f"。这条要连续{cn_count(verdict['need'])}季越线才算触发："
                  + (f"本季已是连续第{cn_ordinal(verdict['run'])}季，触发" if verdict["run"] >= verdict["need"] else
                     f"本季是连续第{cn_ordinal(verdict['run'])}季，还不够" if verdict["run"] else
                     "本季没有越线，连续计数归零"))
    upside = entry.get("upside") or {}
    if "below" in upside:
        words += (f"。反方向那条 {unit_text(entry['unit'], upside['below'])}（{upside['basis']}：低于它说明留有余量），"
                  f"本季{'在它下面' if entry['actual'] < upside['below'] else '没有到它下面'}")
    if "adv" in upside and "rpc" in upside:
        adv, rpc = staging["long"]["adv_k"][-1], staging["long"]["rpc"][-1]
        hit = adv >= upside["adv"] and rpc >= upside["rpc"]
        words += (f"。上行那一组（{upside['basis']}：ADV 不低于 {unit_text('contracts_k', upside['adv'])}"
                  f"而 RPC 不低于 {unit_text('usd_rpc', upside['rpc'])}）本季"
                  f"{'成立' if hit else '不成立'}：ADV {unit_text('contracts_k', adv)}、RPC {unit_text('usd_rpc', rpc)}")
    side = [value for value in values if headroom(entry["direction"], entry["threshold"], value) < 0]
    return words + f"。{len(values)} 季里落在这条线{'下方' if up else '上方'}的有 {len(side)} 季。"


def settlement_section(staging: dict, period: str, closure: dict | None,
                       prior: dict | None) -> tuple[list[dict], list[dict], dict]:
    """Section one's (a) and (b): the charts, the drawer tables, and the counts the prose names."""
    charts, tables, counts = [], [], {}
    if closure is not None:
        charts.append(closure_exhibit(closure))
        table = closure_table(closure)
        if table:
            tables.append(table)
        counts["questions"] = sum(closure_counts(closure))
    if prior is None:
        return charts, tables, counts

    set_in = prior["set_in"]
    due, later = settlement_entries(staging, prior, period)
    every = due + later
    by_id = {entry["id"]: entry for entry in every}
    verdicts = settlement_verdicts(staging, due, every)
    crossed = [entry for entry in due if verdicts[entry["id"]]["crossed"]]
    triggered = [entry for entry in due if verdicts[entry["id"]]["triggered"]]
    counts["thresholds"] = len(due)
    not_carried = prior.get("not_carried", [])
    overview = headroom_exhibit(
        # Most of CME's lines fire only jointly or after a run, so whenever a line
        # is crossed the title also says how many actually fired.
        f"上季 {len(due)} 条量化阈值：{len(due) - len(crossed)} 条守住、{len(crossed)} 条越线"
        + ("" if not crossed else
           "，按触发条件一条都没有触发" if not triggered else
           f"，按触发条件触发 {len(triggered)} 条"),
        due, "actual",
        note=(
            f"正值 = 仍在安全侧。阈值是上季（{set_in}）那一份本地分析在关键观察指标里设的，"
            f"本季读数取自 {quarter_words(period)}业绩新闻稿。"
            + ("越线的是 —— " + "；".join(
                f"{entry['metric']}：本季 {value_text(entry, entry['actual'], kpi_history(staging, entry['reads'])[2])}，"
                f"{'触发' if verdicts[entry['id']]['triggered'] else '未触发'}" for entry in crossed) + "。"
               if crossed else "")
            + ("有的线要与另一条同时失守、或者连续几季越线才算触发，逐条判定写在各自的历史图下。"
               if len(triggered) != len(crossed) else "")
            + "".join(f"另有一条要到 {entry['settles']} 才结算：{short_name(entry)}（当前 "
                      f"{unit_text(entry['unit'], entry['actual'])}），不进这张图。" for entry in later)
            + (f"上季还有{cn_count(len(not_carried))}条本页读不到（"
               + "、".join(item["short"] for item in not_carried) + "），本页照旧不结算。"
               if not_carried else "")),
        src_extra=(f"阈值取自上季本地研究（{set_in} 季报分析），不是公司指引；本季读数全部取自 "
                   f"{quarter_words(period)}业绩新闻稿，同比与环比倍数为本页相除 D。"),
    )
    overview["ref"] = "EX_PRIOR_HEADROOM"
    charts.append(overview)

    groups: dict[str, list[dict]] = {}
    for entry in due:
        groups.setdefault(entry["reads"], []).append(entry)
    for reads, group in groups.items():
        xlabels, values, spec = kpi_history(staging, reads)
        marks = ["击穿" if verdicts[entry["id"]]["crossed"] else "守住" for entry in group]
        if len(set(marks)) == 1:
            head = f"{marks[0]}上季阈值 " + "与 ".join(unit_text(e["unit"], e["threshold"]) for e in group)
        else:
            head = "；".join(f"{mark}上季阈值 {unit_text(e['unit'], e['threshold'])}"
                            for mark, e in zip(marks, group))
        chart = threshold_exhibit(
            f"{spec['name'] if len(group) > 1 else group[0]['metric']}：{head}",
            xlabels, rounded(values), group[0]["threshold"],
            xstep=LONG_STEP if len(xlabels) > 16 else None,
            fmt=spec["fmt"], ylab=spec["ylab"], actual_name=spec["name"],
            threshold_name=threshold_line_name(group[0], len(group), "上季阈值"),
            note="".join(settlement_line_note(staging, entry, verdicts[entry["id"]], by_id) for entry in group),
            src_extra=threshold_source(reads, set_in),
        )
        for extra in group[1:]:
            chart["series"].append({"name": threshold_line_name(extra, len(group), "上季阈值"),
                                    "values": [extra["threshold"]] * len(xlabels), "color": "GOLD"})
        chart["ref"] = f"EX_PRIOR_{reads.upper()}"
        charts.append(chart)

    table = threshold_table(0, f"上季（{set_in}）阈值与本季读数（原始单位）",
                            [{**entry, "metric": kpi_label(entry)} for entry in every],
                            "actual", "本季读数")
    table["headers"] += ["出处（上季本地研究）", "判定"]
    for row, entry in zip(table["rows"], every):
        verdict = verdicts.get(entry["id"])
        row += [basis_text(entry, by_id),
                "未到期" if verdict is None else
                ("触发" if verdict["triggered"] else "越线未触发" if verdict["crossed"] else "守住")]
    tables.append(table)
    return charts, tables, counts


def build_payload(staging: dict) -> dict:
    fin = staging["financials"]
    lng = staging["long"]
    coll = staging["collateral"]
    capex = staging["capex_guidance"]
    labels = staging["period_labels"]
    period = labels[-1]
    latest = latest_block(staging, period=period, period_end=staging["period_ends"][-1])
    kpi = stamped_block(staging, "next_kpi", period)
    context = stamped_block(staging, "quarter_context", period)
    release = release_source(staging)
    first_analysis, closure, prior = settlement_blocks(staging, period)

    story, story_tables, settled_counts = settlement_section(staging, period, closure, prior)
    capex_charts, capex_tables = capex_section(staging)
    settled = story + capex_charts
    settled_tables = story_tables + capex_tables
    highlights = quarter_section(staging, context)
    next_block = next_section(staging, kpi, context) if kpi else []
    routine = routine_section(staging)

    exhibits = number_exhibits(settled + highlights + next_block + routine)
    resolve_exhibit_refs(exhibits)
    n1, n2, n3 = len(settled), len(highlights), len(next_block)
    settled_ex = exhibits[:n1]
    highlight_ex = exhibits[n1:n1 + n2]
    next_ex = exhibits[n1 + n2:n1 + n2 + n3]
    routine_ex = exhibits[n1 + n2 + n3:]

    tally = capex_tally(capex)
    finished = finished_capex_years(capex)
    contracts_qoq = qoq(lng["contracts_m"])
    beta_rev, r2_rev = slope_and_r2(contracts_qoq, qoq(lng["total_revenues"]))
    post_zirp = coll["retained_bp"][ZERO_RATE_COLLATERAL_QUARTERS:]
    window = cn_count(len(labels))
    n = len(lng["quarters"])

    first_table = exhibits[-1]["n"] + 1
    tables = [{**t, "n": first_table + i} for i, t in enumerate(settled_tables)]
    tables.append({
        "n": first_table + len(settled_tables),
        "title": f"近{window}季合并损益与非 GAAP 对账（公司披露值，US$M）",
        "headers": ["期间", "清算与交易费", "行情数据", "其他收入", "总收入",
                    "营业费用", "经营利润", "GAAP 利润率", "调整后费用",
                    "调整后费用（除许可费）", "调整后经营利润", "调整后利润率",
                    "GAAP 摊薄 EPS", "调整后摊薄 EPS"],
        "rows": [[labels[i],
                  f"${fin['clearing_fees'][i]:,.1f}",
                  f"${fin['market_data'][i]:,.1f}",
                  f"${fin['other_revenue'][i]:,.1f}",
                  f"${fin['total_revenues'][i]:,.1f}",
                  f"${fin['total_expenses'][i]:,.1f}",
                  f"${fin['operating_income'][i]:,.1f}",
                  f"{fin['gaap_margin_pct'][i]:.1f}%",
                  f"${fin['adj_total_expenses'][i]:,.1f}",
                  f"${fin['adj_opex_ex_license'][i]:,.1f} D",
                  f"${fin['adj_operating_income'][i]:,.1f}",
                  f"{fin['adj_margin_pct'][i]:.1f}% D",
                  f"${fin['diluted_eps'][i]:.2f}",
                  f"${fin['adj_diluted_eps'][i]:.2f}"]
                 for i in range(len(labels))],
    })
    tail = len(labels)
    tables.append({
        "n": first_table + len(settled_tables) + 1,
        "title": f"近{window}季量价与清算费拆分（ADV 与 RPC 为公司披露值）",
        "headers": ["期间", "ADV（千手/日）", "交易日", "平均每手费率",
                    "成交合约数（百万张）D", "期货与期权清算费 D",
                    "报表清算与交易费", "其余（现券、外汇等）D"],
        "rows": [[labels[i],
                  f"{lng['adv_k'][-tail + i]:,.0f}",
                  f"{lng['trading_days'][-tail + i]:d}",
                  f"${lng['rpc'][-tail + i]:.3f}",
                  f"{lng['contracts_m'][-tail + i]:,.1f}",
                  f"${lng['fo_clearing_fees'][-tail + i]:,.1f}",
                  f"${lng['clearing_fees'][-tail + i]:,.1f}",
                  f"${lng['other_clearing_fees'][-tail + i]:,.1f}"]
                 for i in range(len(labels))],
    })
    tables.append({
        "n": first_table + len(settled_tables) + 2,
        "title": "抵押品再投资：申报文件逐季给出的两个数与由它们得到的利差（US$M）",
        "headers": ["期间", "再投资收益", "利息分配支出", "净额 D",
                    "净额占再投资收益 D", "期末与上季末平均余额 D",
                    "毛收益率（年化）D", "留存利差（年化）D"],
        "rows": [[coll["period_labels"][i],
                  f"${coll['earnings'][i]:,.1f}",
                  f"${coll['distribution'][i]:,.1f}",
                  f"${coll['net'][i]:,.1f}",
                  f"{coll['retained_pct_of_gross'][i]:.2f}%",
                  (f"${coll['avg_balance_usd_m'][i] / 1000:,.1f}B"
                   if coll["avg_balance_usd_m"][i] is not None else "—"),
                  (f"{coll['gross_bp'][i]:.0f}bp" if coll["gross_bp"][i] is not None else "—"),
                  (f"{coll['retained_bp'][i]:.1f}bp" if coll["retained_bp"][i] is not None else "—")]
                 for i in range(len(coll["quarters"]))],
    })
    if kpi:
        entries = kpi_entries(staging, kpi)
        by_id = {entry["id"]: entry for entry in entries}
        table = threshold_table(tables[-1]["n"] + 1, "下季阈值与当前值（原始单位）",
                                [{**entry, "metric": kpi_label(entry)} for entry in entries],
                                "current", "当前值")
        table["headers"].append("出处（本地研究）")
        for row, entry in zip(table["rows"], entries):
            row.append(basis_text(entry, by_id))
        tables.append(table)
    tables.append(ai_capex_cycle_table(tables[-1]["n"] + 1))

    # ── the sentences the page leads with ───────────────────────────────────
    legs = revenue_legs(fin)
    total_change = fin["total_revenues"][-1] - fin["total_revenues"][-5]
    growers = [(name, pct) for name, change, pct in legs if change > 0]
    short_yoy = [pct_change(fin["clearing_fees"][i], fin["clearing_fees"][i - 4])
                 for i in range(4, len(labels))]
    short_neg = sum(1 for value in short_yoy if value < 0)
    clearing_yoy = short_yoy[-1]
    if clearing_yoy < 0:
        turn = ("、是本窗口内第一次转负" if short_neg == 1
                else f"、是{window}季窗口内第{cn_ordinal(short_neg)}次转负")
    else:
        turn = ""
    if total_change > 0 and len(growers) == 1:
        growth_words = f"全部同比增量来自{growers[0][0]}一条线（同比 {signed(growers[0][1])}）"
    elif total_change > 0:
        growth_words = "同比增量来自" + joined([f"{name}（同比 {signed(pct)}）" for name, pct in growers])
    else:
        growth_words = "三条收入线合计同比没有增长"
    headline = (
        f"总收入 US${fin['total_revenues'][-1]:,.1f}M、同比 "
        f"{signed(pct_change(fin['total_revenues'][-1], fin['total_revenues'][-5]))}，"
        f"清算与交易费同比 "
        f"{signed(pct_change(fin['clearing_fees'][-1], fin['clearing_fees'][-5]))}"
        f"{turn}，{growth_words}；"
        f"成交合约数环比 {contracts_qoq[-1]:.1f}% 而总收入"
        + (f"只跌 {abs(qoq(lng['total_revenues'])[-1]):.1f}%，"
           if contracts_qoq[-1] < 0 and 0 > qoq(lng["total_revenues"])[-1] > contracts_qoq[-1]
           else f"环比 {qoq(lng['total_revenues'])[-1]:+.1f}%，")
        + f"这是{cn_count(len(contracts_qoq))}次环比变动测出来的同一条斜率（{beta_rev:.2f}）。"
    )

    # The first thread used to be the ten-year capital-expenditure record. That
    # record is section one's (c), not a thread of this quarter, and the local
    # analysis's core contradiction -- the clearing line shrinking year on year
    # while market data carries all the growth -- was only in the headline.
    changes = {name: change for name, change, _ in legs}
    rates = {name: pct for name, _, pct in legs}
    clearing, market, other = "清算与交易费", "行情数据", "其他收入"
    carried = changes[market] >= total_change > 0 > changes[clearing]
    slope_words = str(round(beta_rev, 2))
    brief = (
        '<h4>本季三条主线</h4><div class="takeaway-grid">'
        '<article><span>增长</span><b>'
        + ("清算与交易费同比转负，行情数据一条线扛下全部增量" if carried else
           f"总收入同比 {minus_sign(signed(pct_change(fin['total_revenues'][-1], fin['total_revenues'][-5])))}")
        + '</b>'
        f'<p>总收入 US${fin["total_revenues"][-1]:,.1f}M、同比 '
        f'{minus_sign(signed(pct_change(fin["total_revenues"][-1], fin["total_revenues"][-5])))}（{signed_usd(total_change)}）：'
        + "，".join(f"{name} {signed_usd(changes[name])}（同比 {minus_sign(signed(rates[name]))}）"
                   for name in (clearing, market, other))
        + ("。行情数据一条线的增量就比全公司多。" if carried else "。")
        + '</p></article>'
        # The title used to say 零点六六 while the body printed the computed
        # 0.65: the slope moved when the series was extended and the words did not.
        '<article><span>机制</span><b>量动一个点，收入只动'
        f'{"零点" + "".join("零一二三四五六七八九"[int(d)] for d in slope_words.split(".")[1]) if beta_rev < 1 else slope_words}'
        '个点</b>'
        f'<p>{cn_count(len(contracts_qoq))}次环比变动里，总收入对成交合约数的斜率是 {beta_rev:.2f}（R² {r2_rev:.2f}），'
        f'清算与交易费是 {slope_and_r2(contracts_qoq, qoq(lng["clearing_fees"]))[0]:.2f}；'
        f'成交量与每手费率有 {opposite_moves(lng)}/{len(contracts_qoq)} 个季度反向。'
        f'本季成交量 {contracts_qoq[-1]:+.1f}%、收入 {qoq(lng["total_revenues"])[-1]:+.1f}%，'
        + ('落在这条长期关系上。' if on_the_slope(lng) else '偏离了这条长期关系。')
        + '</p></article>'
        '<article><span>口径</span><b>抵押品那条线是基点，不是利率</b>'
        f'<p>{coll["period_labels"][ZERO_RATE_COLLATERAL_QUARTERS]} 以来 {len(post_zirp)} 个季度的留存利差落在 '
        f'{min(post_zirp):.0f}–{max(post_zirp):.0f} 个基点之间，而同一笔余额上的毛收益率从 '
        f'{min(coll["gross_bp"][ZERO_RATE_COLLATERAL_QUARTERS:]):.0f} 走到 '
        f'{max(coll["gross_bp"][ZERO_RATE_COLLATERAL_QUARTERS:]):.0f} 个基点。'
        f'零利率的 {coll["period_labels"][0]} 那一格只有 {coll["retained_bp"][0]:.0f} 个基点。</p></article>'
        '</div>')

    year = int(period.split()[1])
    fourth = period.startswith("Q4")
    filings = (f"与截至 {year}-12-31 的 10-K" if fourth else
               f"与截至 {latest['period_end']} 的 10-Q、截至 {year - 1}-12-31 的 10-K")
    searched = context["searched"] if context else None
    guidance = context.get("call_expense_guidance") if context else None
    forms = [capex["by_year"][y]["form"] for y in capex["years"]]
    form_changes = sum(1 for a, b in zip(forms, forms[1:]) if a != b)
    ranges = [y for y in capex["years"] if capex["by_year"][y]["form"] == "range"]
    inside = [y for y in finished
              if capex["by_year"][y]["low"] <= capex["by_year"][y]["actual"] <= capex["by_year"][y]["high"]]
    collateral_count = len(coll["quarters"])
    long_from = lng["quarters"].index("2016Q1")

    # The company's guidance is annual, so "given last quarter, due this
    # quarter" does not describe it; what section one settles for CME is every
    # guided year that has ended.
    pending_years = [y for y in capex["years"] if capex["by_year"][y]["actual"] is None]
    settled_from = (closure or prior or {}).get("set_in")
    settled_parts = [f"{settled_counts['questions']} 条待验证问题的判定" if "questions" in settled_counts else "",
                     f"{settled_counts['thresholds']} 条量化阈值的本季读数" if "thresholds" in settled_counts else ""]
    settled_description = (
        (f"本站对该公司的第一份季报分析是 {period}，没有上季留下的跟踪指标可结算；"
         "本节结算的是公司自己给出、已经到期的指引。" if first_analysis else
         f"先结清上季（{settled_from} 那一份季报分析）留下的 "
         + "与 ".join(part for part in settled_parts if part)
         + "，再结算公司自己给出、已经到期的指引。")
        + "CME 在申报文件里不指引收入、每股收益、利润率，也不指引费用；10-K 流动性一节里有一句全年资本开支的预期，"
        f"{cn_count(len(capex['years']))}年没有断过。它按年到期，所以这里结算的是"
        f"{cn_count(len(finished))}个已完结年度"
        + (f"，FY{pending_years[-1]} 那一格要等该年的 10-K" if pending_years else "")
        # Fixed history, read in the FY2025 10-K: the sentence after the capex
        # guidance states the regular-dividend target. The page once called the
        # capex sentence the filings' only guidance; it is not their only target.
        + "。FY2025 的 10-K 在同一段里还写了一个常规股息的派息目标（按上年「现金收益」的比例给出），"
        "本节没有结算它：「现金收益」是公司自定义的口径，本页没有逐年核对过它的定义与数值。"
        "市场用来给它建成本模型的那个全年调整后营业费用指引只出现在业绩电话会上"
        + (f"，本页逐份检索过 {searched}，一次都没有找到，因此不接入。" if searched else "，因此不接入。")
    )

    undrawn = context.get("undrawn", []) if context else []

    if kpi:
        upcoming, later = next_split(kpi, period)
        shared = {}
        for entry in upcoming:
            shared.setdefault(entry["reads"], []).append(entry)
        shared = [group for group in shared.values() if len(group) > 1]
        not_carried = kpi.get("not_carried", [])
        next_description = (
            f"本地研究（{period} 那一份季报分析的关键观察指标）给下季留了{cn_count(len(upcoming))}条阈值，"
            "全部能在下一份业绩新闻稿里直接读到：先用「距阈值余量」口径放在一张图上，"
            f"再把它们画回各自的历史，共{cn_count(len(next_block) - 1)}张"
            + "".join(f"（{short_name(group[0])} 的{cn_count(len(group))}条线画在同一张上）" for group in shared)
            + "。"
            + "".join(f"另有一条要到 {entry['settles']} 才结算（{short_name(entry)}），只列在核对抽屉的阈值表里。"
                      for entry in later)
            + (f"下一份新闻稿里读不到的{cn_count(len(not_carried))}条（"
               + "、".join(item["short"] for item in not_carried)
               + "）和本页一向不接入的几类数据，写在余量图的图注里。" if not_carried else ""))
    else:
        next_description = "本季没有设定下季阈值，本节没有图。"

    notes = [
        "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
        "CME 财年即自然年，本页季度标注与公司自己的口径一致，无需换算。",
        ("第一节结清的公司指引是资本开支，不是费用。市场给 CME 建成本模型用的是「全年调整后营业费用（除许可费）」"
         + (f"，{guidance['fiscal_year']} 年的口径是约 {guidance['adj_opex_ex_license_usd_m'] / 100:.2f} 亿美元；"
            "这个数只在业绩电话会上出现。" if guidance else "，这个数只在业绩电话会上出现。")
         + (f"本页逐字检索过 {searched}，其中没有任何一处给出全年费用指引，8-K 正文同样没有。"
            if searched else "")
         + "本站只发布有申报出处的指引，所以第一节结清的是每年 10-K 里那句「In 20XX, we expect capital expenditures to total approximately $X million」。这不是说费用指引不重要，而是说它不满足本站对可核对来源的要求。"),
        (f"资本开支指引的形式在窗口内换过{cn_count(form_changes)}次：{'、'.join('FY' + y for y in ranges)} 给的是区间，"
         f"其余{cn_count(len(capex['years']) - len(ranges))}个年度给的是一个单点。"
         f"因此「落在区间内」这一档在图上只对那{cn_count(len(ranges))}年有意义，"
         f"{cn_count(len(finished))}个已完结年度里只发生过{cn_count(len(inside))}次"
         + (f"（{'、'.join('FY' + y for y in inside)}）" if inside else "")
         + "。单点指引在图上没有宽度，这是公司的指引本来就没有宽度，不是渲染缺陷。"),
        ("资本开支的实际值取各年 10-K 现金流量表的 Purchases of property 一行。每个年度都在两到三份 10-K 的三年比较列里重复出现过，逐份核对没有任何一年被重述。"
         f"指引与实际因此跨{cn_count(len(capex['years']))}年在同一个口径上。"),
        "分品种的 ADV 与 RPC 只覆盖期货与期权，公司在五季表的脚注里写明这一点。报表的清算与交易费还包含 BrokerTec 的现券与 EBS 的外汇业务，公司不披露这两块的成交量或费率。本页把差额单独画成一条线并标出它的大小，但不对它做任何量价拆解。",
        ("本页的品种标签在窗口内改过名：2018 年第四季度以前公司写的是 Interest rate、Equity、Agricultural commodity、Metal 的单数形式，2013 年上半年股指那一行叫 Equities。数值没有变，只有标签变了；本页逐份按标签的历史拼写取值，"
         f"因此六个品种的序列在{cn_count(n)}个季度上连续。"
         "若只按现在的复数拼写取值，会有二十一个季度的品种行取不到，而合计行仍然取得到 —— 那种缺失在图上看不出来。"),
        "成交场所的拆分（CME Globex、公开喊价、私下议价）本页不接入。公司在 2013 年第三季度换过一次场所口径，此前用的是 Exchange-traded 与 CME ClearPort 两分法；同一个 2013 年第一季度按不同新闻稿读出的私下议价成交量是 275 千手或 691 千手。本页其余每一条序列在所有出现过它的新闻稿里都完全一致，只有这一条不是，所以不发布。",
        (f"调整后的费用、经营利润与利润率只有{cn_count(len(fin['adj_total_expenses']))}个季度，"
         "因为公司是从 2025 年第三季度那期业绩新闻稿起才开始印 Reconciliation of Adjusted Operating Income 这张表的。此前各期只印调整后净利润与调整后每股收益的对账。调整后每股收益本身还有一段 2014 年第四季度至 2018 年第三季度的更早记录，但公司在 2016 年改过调整项的定义并重述了 2015 年第四季度与 2016 年第一季度（例如 2015 年第四季度的调整后每股收益由 0.92 美元改为 0.97 美元），跨越这次改动的比较不同基准，因此本页不把两段接起来。"),
        "「调整后营业费用（除许可费）」是调整后费用合计减去合并损益表里「许可与其他费用协议」一行，两个数都是公司披露值，相减是本页做的。用这个口径是因为公司自己的全年指引就是按它给的；把许可费单画一条，是因为它随股指成交量变动而不是随成本决策变动。",
        ("抵押品再投资收益与利息分配支出这两个数不在业绩新闻稿里，只在 10-Q 与 10-K 的正文中以文字给出，且同一份文件里出现两次、写法不同：附注四写成「本季与年初至今」两个数并列，MD&A 写成「本季与去年同期」两个数并列。两处口径一致，本页交叉核对过每一个季度。取值一律按名词认期间，不按位置；同一句话里第二个数在附注四里是年初至今、在 MD&A 里是去年同期，按位置取会把两者互换。"
         f"这项披露自 2021 年第三季度起才有，更早的季度没有，因此该序列只有{cn_count(collateral_count)}个季度而不是{cn_count(n)}个。"),
        "留存利差的分母是合并资产负债表上 Performance bonds and guaranty fund contributions 一行，按本季末与上季末取平均。这是期末数不是日均数：公司唯一一次公开过的日均现金抵押品余额约为 1,490 亿美元，本页同期的两点平均是 1,623 亿美元，高约 8%，因此本页算出的基点数相应偏低约 8%。趋势与区间不受影响，绝对水平要按这个偏差读。",
        "投资收益与其他非经营收支这两条线本页不相减。其他非经营收支里除了付给清算会员的利息分配还有别的项目，2021 年该行是正数，里面装着一笔与利率无关的一次性收益；相减会得到一条把它算进利差的曲线。只属于抵押品的那一段用上一条注释里的文字披露单独画。",
        ("收入对成交量的斜率与决定系数是本页对所载序列做的最小二乘回归，自变量是成交合约数的环比变动，"
         f"样本是窗口内{cn_count(len(contracts_qoq))}次环比。"
         "成交合约数由公司披露的 ADV 与交易日相乘得到。斜率可以用核对抽屉里的量价表复算。本页不把它当作预测模型，它只说明历史上量与收入的振幅关系，任何一个季度都可能偏离。"),
        # The first version said the page kept this cell on the chart; the
        # chart leaves it empty and says so, as its own note explains.
        (f"有效税率序列里 {lng['effective_tax_outlier']['quarter'][:4]} 年第四季度那一格是美国税改一次性重估递延所得税负债的结果，与经营无关。"
         "本页在图上把这一格留空、在图注里写明原因，而不是把它画进去或平滑掉 —— 画进去会把其余"
         f"{cn_count(n - long_from - 1)}格压进画布顶端，平滑则会让那条线看起来像一条平稳的税率而它不是。"),
        "本页不发布市场一致预期、评级、目标价与估值，也不发布任何竞争对手的成交量或市占率。竞品的量取自对手方自己的季报，合约口径与本页的合约张数不可比。",
        "本页只发布公司披露值、可复算的简单派生值；D 标记代表 Derived / 自算。",
        "核对抽屉最后那张「AI capex 循环」是全站共用的跨页对照块，在每一页都逐字节相同，不是对 CME 的判断。它追的是四家云厂现金资本开支到 NVDA 数据中心收入再到 TSM 晶圆这条链，CME 不在这条链的任何一环上。把它放在这里是为了让读者在任意一页都能查到同一份上下游对照。它在折叠的抽屉里，不参与本页的论证。",
        ("本页已知未接入：全年调整后营业费用指引（电话会口径，无申报出处）、日均保证金效率（只以「超过」的形式出现，无逐季序列与定义）、未平仓合约的绝对值（申报文件只有同比百分比）、事件合约与预测市场的成交与收入（两季口径基数不同，不能连成序列）、成交场所拆分、非美成交量占比（同样只在电话会与新闻稿正文里以单点形式出现），"
         f"以及 {quarter_words(next_period(period))}之后的任何数据"
         + (f"（本页数据截至 {context['filings_through']} 的申报）" if context else "")
         + "。"),
        "业绩电话会文字稿仅链接官方 IR 与 SEC 托管版本，公开仓不复制原件或逐字内容。",
    ]

    return {
        "schema_version": "quarterly-dashboard/cme-v1",
        "page": {"slug": "cme", "language": "zh-CN"},
        "company": {
            "ticker": "CME",
            "name": "CME Group Inc.",
            "group": "exchanges",
            "accounting_standard": "US GAAP",
        },
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · CME",
        "title": f"CME Group Inc. (CME)：{period} 季报仪表盘",
        "subtitle": (f"截至 {latest['period_end']} · 发布 {latest['release_date']} · US GAAP · "
                     f"{AUDIT_WORDS[latest['audit_status']]} · "
                     "自然年财年，季度标注与财年一致"),
        "headline": headline,
        "brief": brief,
        "source": (f'Source: <a href="{release["url"]}" rel="noopener">'
                   f'CME Group {quarter_words(period)}业绩新闻稿（8-K EX-99.1）</a>'
                   f'{filings}。'),
        "source_url": release["url"],
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {"id": "settled", "title": "一、上季跟踪指标兑现了吗",
             "description": settled_description,
             "exhibits": settled_ex},
            {"id": "quarter_highlights", "title": "二、本季重点",
             "description": (
                 "本地研究对这一季的核心结论，能用申报数画的逐条画出：先把三条收入线分开，"
                 "再把清算费的环比变动拆成量与价两块、看六个品种的量价方向，"
                 "然后是利润率、费用、行情数据与每股收益，最后是抵押品净利差。"
                 + (f"另有{cn_count(len(undrawn))}条画不了：" + "；".join(undrawn) + "。"
                    if undrawn else "")),
             "exhibits": highlight_ex},
            {"id": "next_quarter", "title": "三、下季要跟踪什么",
             "description": next_description,
             "exhibits": next_ex},
            {"id": "routine", "title": "四、长期常规跟踪",
             "description": (f"{cn_count(n)}个季度的量与价、收入对成交量的斜率、清算费里看不见的那一块、"
                             "投资收益与利息分配的镜像，以及行情数据、六个品种的成交量与有效税率。"),
             "exhibits": routine_ex},
        ],
        "tables": tables,
        "notes": notes,
        "footer": "CME quarterly results · 数据来自 CME Group 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "cme.js"), payload, "cme")
    shell_dir = ROOT / "cme"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("CME", "cme"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"CME page: {charts} charts in {len(payload['sections'])} sections "
          f"+ {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
