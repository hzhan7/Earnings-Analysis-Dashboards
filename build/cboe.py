"""Cboe Global Markets quarterly dashboard.

Cboe prints market share and revenue per contract for the same business, in the
same table, in every quarterly release. Share is the number that gets quoted;
**ADV x RPC is the money**. This page exists because over the published record
the two do not agree: across the quarters in which Cboe has published a
multi-listed options market share alongside the ADV and RPC that multiply into
daily revenue, the two move in OPPOSITE directions in most quarter-on-quarter
steps, and over that window share fell while daily revenue more than tripled.
A threshold set on share alone is not a weak risk control; on this record it is
slightly worse than a coin flip. The same shape runs in the cash equities
business, on and off exchange.

What this page will NOT settle, and why it is worth saying twice: the guidance a
reader most wants scored is organic net revenue growth, and it cannot be scored
in either era. From 2022 to 2024 the company guided it as a number, but no
full-year organic actual was found in the releases and annual report read for
it. From 2025 the guidance stops being a number at all. This site does not
convert a phrase into endpoints, so the record simply stops. The two full-year
numbers that CAN be settled through the latest finished year are adjusted
operating expenses and the adjusted effective tax rate.

**Rolling a quarter edits `series/cboe.json` and nothing else** (CLAUDE.md §9).
Every figure, period and count in the prose is computed from the series, and a
sentence that states a record, an "only", an "always", a "never", a direction or
a ranking is printed only while the series still says so. What belongs to one
quarter -- the thresholds the last local note set and this quarter settles
(`settled_kpi`), the next ones (`next_kpi`), and what the release said beside
its numbers (`quarter_context`: the Australia sale inside the reaffirmed expense
guidance, the local note's own correction) -- carries a ``period`` stamp and is
read through `board.stamped_block`. `_checks` is a separate reading of the
quarter's release that the tests hold the page to; this builder never reads it.

Fixed history stays in code: the Bats close (2017-02-28) and the 2017 guidance
basis change (US$214-218M stand-alone, US$415-423M combined, US$386.6M as the
as-reported combined actual), the Cboe Digital years of the sixth segment row,
the label changes of the tax-rate guidance, and the four February releases and
the FY2025 10-K read for an organic full-year actual.

Published numbers are company-reported or transparent arithmetic. No market
expectation, valuation or rating appears here.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import (  # noqa: E402
    ai_capex_cycle_table,
    cn_count,
    cn_fraction,
    cn_ordinal,
    delivery_band,
    display_period,
    fill_story,
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

STAGING_PATH = ROOT / "series" / "cboe.json"
DATA_DIR = ROOT / "data"

# One tick a year keeps the long axes readable.
LONG_STEP = 4

AUDIT_WORDS = {"unaudited": "未审计", "audited": "已审计"}

# The same release printed a second FY2017 figure, as-reported combined (Bats
# from 2017-02-28), against which the combined-basis guidance would read as a
# huge beat. Fixed history.
FY2017_AS_REPORTED = 386.6
# Where the page looked for a full-year organic net revenue growth actual and
# found none: the four February releases and the FY2025 annual report.
ORGANIC_SEARCHED = "2023、2024、2025、2026 四份 2 月新闻稿与 FY2025 的 10-K"


def plain_text(html: str) -> str:
    """Strip tags for the slots `assets/page.js` renders through `esc()`.

    Section descriptions and the 口径与方法说明 list are escaped by the shared
    renderer, so a `<b>` written into either reaches the reader as four literal
    characters. Exhibit notes are raw innerHTML and keep their markup.
    """
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html)).strip()


def compact(period: str) -> str:
    """``2026Q2`` -> ``26Q2``."""
    return period[2:]


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100.0


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def rounded(values: list, digits: int = 6) -> list:
    return [None if v is None else round(v, digits) for v in values]


def axis(labels: list, step: int = LONG_STEP) -> list:
    """Blank every label but each ``step``-th and the last."""
    keep = set(range(len(labels) - 1, -1, -step))
    return [label if index in keep else "" for index, label in enumerate(labels)]


def quarter_words(period: str) -> str:
    """``'Q2 2026'`` → ``'2026 年第二季度'``, the way the source labels name a quarter."""
    quarter, year = period.split()
    return f"{year} 年第{cn_ordinal(int(quarter[1]))}季度"


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


def falls(values: list) -> tuple[int, int]:
    """Quarter-on-quarter falls, and how many changes there were."""
    known = [v for v in values if v is not None]
    return sum(1 for a, b in zip(known, known[1:]) if b < a), len(known) - 1


def usd_zero(value: float) -> str:
    """A fee that is exactly zero reads as US$0M, as the release prints it."""
    return "US$0M" if value == 0 else f"US${value:,.1f}M"


# ── the page's central statistic ────────────────────────────────────────────
def direction_steps(share: list, money: list) -> dict:
    """Count quarter-on-quarter steps where share and money disagree.

    Returns the tallies plus the per-step verdicts, so the chart note and the
    audit table are computed once from one function rather than twice from two.
    A step in which either series is flat is counted in neither tally: "did not
    move" is not a direction, and rounding a printed 23.5% makes ties real.
    """
    same = opposite = 0
    verdicts = [None]
    for index in range(1, len(share)):
        # A step needs both legs. The share line starts thirteen quarters into
        # this record, so those steps have no verdict rather than a zero one.
        if (share[index] is None or share[index - 1] is None
                or money[index] is None or money[index - 1] is None):
            verdicts.append(None)
            continue
        ds = share[index] - share[index - 1]
        dm = money[index] - money[index - 1]
        if ds == 0 or dm == 0:
            verdicts.append(None)
            continue
        if (ds > 0) == (dm > 0):
            same += 1
            verdicts.append("同向")
        else:
            opposite += 1
            verdicts.append("反向")
    return {"same": same, "opposite": opposite,
            "steps": same + opposite, "verdicts": verdicts}


def finished_years(item: dict) -> list[int]:
    return [year for year in item["years"]
            if item["by_year"][str(year)]["actual"] is not None
            and item["by_year"][str(year)]["guided"]]


def vintages(item: dict, year: int) -> tuple[list, list]:
    guided = item["by_year"][str(year)]["guided"]
    return guided[0], guided[-1]


def tally(item: dict, which: int, years: list[int]) -> dict[str, int]:
    counts = {"inside": 0, "above": 0, "below": 0}
    for year in years:
        low, high, _ = vintages(item, year)[which]
        actual = item["by_year"][str(year)]["actual"]
        counts["inside" if low <= actual <= high
               else ("above" if actual > high else "below")] += 1
    return counts


GUIDE_NAMES = {"adjusted_operating_expenses": "调整后营业费用",
               "adjusted_effective_tax_rate": "调整后有效税率",
               "capex": "资本开支", "depreciation_and_amortization": "折旧摊销"}


def guidance_census(staging: dict) -> dict:
    """How many guided lines there are, and which of them settle to the latest finished year.

    The section used to say "only two of the six lines are numbers with a
    printed full-year actual"; the series itself carries D&A actuals for
    FY2013-FY2016 and a capex actual for FY2013, so the count is taken from the
    file: a line settles if its actuals run to the latest finished year.
    """
    guide = staging["annual_guidance_history"]
    lines = {key: finished_years(item) for key, item in guide.items()}
    latest = max(max(years) for years in lines.values() if years)
    settled = [key for key, years in lines.items() if years and max(years) == latest]
    partial = {key: max(years) for key, years in lines.items()
               if years and max(years) < latest}
    growth_lines = len({key for row in staging["revenue_growth_guidance"]["by_year"].values()
                        for key in row})
    return {"total": len(guide) + growth_lines, "settled": settled, "partial": partial,
            "latest": latest}


# ── section one (c): the company's own guidance, and what cannot be settled ──
def settled_exhibits(staging: dict) -> tuple[list[dict], dict]:
    """The company's own full-year guidance record -- section one's part (c),
    after what the previous local analysis left open."""
    guide = staging["annual_guidance_history"]
    opex = guide["adjusted_operating_expenses"]
    tax = guide["adjusted_effective_tax_rate"]
    census = guidance_census(staging)

    opex_years = finished_years(opex)
    opex_labels = [f"FY{y}" for y in opex_years]
    opex_last = [vintages(opex, y)[1] for y in opex_years]
    opex_actual = [opex["by_year"][str(y)]["actual"] for y in opex_years]
    opex_tally = tally(opex, 1, opex_years)
    break_index = opex_years.index(2017)
    over = [y for y in opex_years if opex["by_year"][str(y)]["actual"] > vintages(opex, y)[1][1]]
    below = [y for y in opex_years if opex["by_year"][str(y)]["actual"] < vintages(opex, y)[1][0]]
    # How many of the undershoots the company had already told anyone about.
    # The warning sits in a release that gave no range (FY2016's October one),
    # so it is found in the text record, not in the vintages.
    flagged = [y for y in below
               if any(word in opex["by_year"][str(y)]["texts"][-1].lower()
                      for word in ("below", "lower end", "low end"))]

    tax_years = finished_years(tax)
    others = [key for key in census["settled"] if key != "adjusted_operating_expenses"]
    settle_words = (
        f"这是本页{cn_count(len(census['settled']))}条能一直结清到 FY{census['latest']} 的记录之一"
        + (f"（另一条是下一张的{GUIDE_NAMES[others[0]]}）" if len(others) == 1 else "")
        + "，也是最长的一条。"
        if len(census["settled"]) > 1 else
        f"这是本页唯一一条能一直结清到 FY{census['latest']} 的记录。")

    if len(over) == 1:
        over_year = over[0]
        low17, high17, _ = vintages(opex, over_year)[1]
        over_by = opex["by_year"][str(over_year)]["actual"] - high17
        sided = (f"<b>这条记录几乎是单边的</b>：{opex_tally['below']} 次低于下限，"
                 f"而唯一一次超出上限是 FY{over_year}，只超了 US${over_by:.1f}M —— "
                 f"在一条 US${low17:,.0f}–{high17:,.0f}M 的带子上，那等于压着线。")
    elif not over:
        sided = (f"<b>这条记录是单边的</b>：{opex_tally['below']} 次低于下限，没有一次超出上限。")
    else:
        sided = (f"{opex_tally['below']} 次低于下限、{len(over)} 次超出上限"
                 f"（{'、'.join(f'FY{y}' for y in over)}）。")

    flag_words = ""
    if flagged:
        year = flagged[0]
        block = opex["by_year"][str(year)]
        month = int(block["releases"][len(block["texts"]) - 1][5:7])
        low, high, _ = block["guided"][-1]
        flag_words = (
            (f"{opex_tally['below']} 次低于下限里只有 FY{year} 一次是<b>提前说过的</b>："
             if len(flagged) == 1 else
             f"{opex_tally['below']} 次低于下限里 FY{year} 是<b>提前说过的</b>：")
            + f"该年 {month} 月那期新闻稿写的是「预计略低于 US${low:.1f}–{high:.1f}M 的指引区间」，")
        rest = [y for y in below if y not in flagged]
        # "The rest all fell below a range the company had just reaffirmed" was
        # the original sentence; only FY2013's last range was a reaffirmation --
        # FY2019 and FY2023 fell below a range just cut, FY2021 below one just raised.
        kinds: dict[str, list[int]] = {"重申过": [], "刚下调过": [], "刚上调过": []}
        months = set()
        for y in rest:
            guided = opex["by_year"][str(y)]["guided"]
            months.add(int(guided[-1][2][5:7]))
            last, before = guided[-1][:2], guided[-2][:2] if len(guided) > 1 else None
            kind = ("重申过" if last == before else
                    ("刚下调过" if before and last[0] < before[0] else "刚上调过"))
            kinds[kind].append(y)
        if rest and len(kinds["重申过"]) == len(rest):
            flag_words += ("其余各次都是在 "
                           + "或 ".join(f"{m} 月" for m in sorted(months))
                           + "刚重申过区间之后落在区间下方。")
        elif rest:
            parts = [f"{'、'.join(f'FY{y}' for y in years)} 是{kind}的区间"
                     for kind, years in kinds.items() if years]
            flag_words += ("其余" + cn_count(len(rest)) + "次都是在当年 "
                           + "或 ".join(f"{m} 月" for m in sorted(months))
                           + "最后一次给出区间之后落到它下方：" + "，".join(parts) + "。")
        else:
            flag_words = flag_words.rstrip("，") + "。"

    first17, last17 = vintages(opex, 2017)
    combined17 = next(g for g in opex["by_year"]["2017"]["guided"] if g[0] > 300)
    charts = [delivery_band(
        "EX_OPEX", "全年调整后营业费用", opex_labels,
        [g[0] for g in opex_last], [g[1] for g in opex_last], opex_actual,
        fmt="f0c", ylab="US$M", unit="US$M",
        venue="业绩新闻稿", timing="该年<b>当年内最后一次</b>", period_word="年",
        break_at=break_index,
        break_label="Bats 交割（2017-02-28）：口径换过一次",
        extra_note=(
            f"<b>{len(opex_years)} 个已完结年度里，落在区间内 {opex_tally['inside']} 次、"
            f"跌破下限 {opex_tally['below']} 次、超出上限 {opex_tally['above']} 次。</b>"
            + settle_words
            + sided
            + flag_words
            + f"竖线那一年不要连着读：2017 年 2 月那版指引是 US${first17[0]:,.0f}–{first17[1]:,.0f}M，"
            "写明「不含拟收购的 Bats」；同年 5 月那版跳到 "
            f"US${combined17[0]:,.0f}–{combined17[1]:,.0f}M，已含 Bats。"
            "两版之间隔着一次收购，不是一次费用暴涨。"
            f"FY2017 的实际值取<b>合并口径</b>的 US${opex['by_year']['2017']['actual']:.1f}M，"
            "因为它要对照的指引就是按合并口径给的；"
            f"同一份新闻稿里另有一个「如实合并」口径的 US${FY2017_AS_REPORTED:.1f}M（Bats 自 2 月 28 日起并表），"
            f"拿它去对 US${last17[0]:,.0f}–{last17[1]:,.0f}M 的指引会凭空造出一次巨大的超预期。"),
        src_extra=("指引与实际均取自各期业绩 8-K EX-99.1；"
                   "2013–2016 年公司称其为「core operating expenses」，"
                   "2017 年 5 月起改称「adjusted operating expenses」。"),
    )]

    tax_labels = [f"FY{y}" for y in tax_years]
    tax_last = [vintages(tax, y)[1] for y in tax_years]
    tax_actual = [tax["by_year"][str(y)]["actual"] for y in tax_years]
    tax_tally = tally(tax, 1, tax_years)
    charts.append(delivery_band(
        "EX_TAX", "全年调整后有效税率", tax_labels,
        [g[0] for g in tax_last], [g[1] for g in tax_last], tax_actual,
        fmt="pct1", ylab="%", unit="%",
        venue="业绩新闻稿", timing="该年<b>当年内最后一次</b>", period_word="年",
        extra_note=(
            f"第二条能结清的记录：{len(tax_years)} 个已完结年度里区间内 "
            f"{tax_tally['inside']} 次、低于下限 {tax_tally['below']} 次、"
            f"高于上限 {tax_tally['above']} 次。"
            "这一条的标签在 2013–2017 年间来回改过 —— 同一个区间，"
            "2 月那期叫「consolidated effective tax rate」，年中几期叫「adjusted」，"
            "2018 年起统一成「effective tax rate on adjusted earnings」。"
            "本页按内容归到一条线上，因为三个名字指的是同一个数。"),
        src_extra=("各期业绩 8-K EX-99.1。2017 年 8 月与 11 月那两期在同一句话里"
                   "先给 GAAP 区间、再给调整后合并区间，本页取<b>后者</b>；"
                   "取第一个出现的区间会拿到 GAAP 的数，那是另一个指标。"),
    ))

    growth = staging["revenue_growth_guidance"]["by_year"]
    numeric_years = sorted(y for y, row in growth.items()
                           if any(v["low"] is not None for v in row.get("total", [])))
    word_years = sorted(y for y, row in growth.items()
                        if row.get("total") and all(v["low"] is None for v in row["total"]))
    last_words = growth[word_years[-1]]["total"][-1]["text"]
    latest_total = growth[word_years[-1]]["total"]
    raises = sum(1 for vintage in latest_total[1:] if "up from" in vintage["text"])
    phrases = [re.search(r"['‘]([^'’]+)['’]", vintage["text"]) for vintage in latest_total]
    ladder = ""
    if raises and all(phrases):
        # 「从 mid single-digit 连升三档」: the year's three vintages are two raises.
        ladder = (f" —— {word_years[-1]} 年这一版已经从「{phrases[0].group(1)}」"
                  + (f"连升{cn_count(raises)}次到「{phrases[-1].group(1)}」，每一次都是一句话"
                     if raises > 1 else
                     f"上调到「{phrases[-1].group(1)}」，两版都是一句话"))
    charts.append({
        "ref": "EX_GROWTH",
        "kind": "grouped_bars",
        "title": ("最想结清的那条指引结不了：有机净收入增速 "
                  f"{numeric_years[0]}–{numeric_years[-1]} 是数字，"
                  f"{word_years[0]} 起变成一句话"),
        "xlabels": [f"FY{y}" for y in numeric_years],
        "groups": [
            {"name": "当年第一次指引下限", "color": "BLUE",
             "values": [growth[y]["total"][0]["low"] for y in numeric_years]},
            {"name": "当年最后一次指引下限", "color": "NAVY",
             "values": [next(v["low"] for v in reversed(growth[y]["total"])
                             if v["low"] is not None) for y in numeric_years]},
            {"name": "当年最后一次指引上限", "color": "GOLD",
             "values": [next(v["high"] for v in reversed(growth[y]["total"])
                             if v["high"] is not None) for y in numeric_years]},
        ],
        "bar_labels": True,
        "fmt": "pct0", "label_fmt": "pct0",
        "ylab": "%（有机净收入增速指引）",
        "note": (
            "<b>这张图上没有实际值，而且两个时代各有各的原因。</b>"
            f"{numeric_years[0]}–{numeric_years[-1]} {cn_count(len(numeric_years))}年公司给的是数字区间"
            "（「in the range of 5 to 7 percentage points」），"
            "但它指引的是<b>有机</b>增速，而它的全年实际值本页没有找到 —— "
            f"翻遍 {ORGANIC_SEARCHED} 都没有这个数，"
            "所以没有可以对照的对象。"
            f"{word_years[0]} 年起连数字都没有了：最新一版的原话是"
            f"「{last_words}」。"
            "<b>本站不把一句话换算成区间端点</b>（见口径说明），"
            "所以这条线在这里就断了。"
            "顺带一提，指引变成文字的那一年，正是增速从个位数切到两位数的那一年"
            + ladder + "。"),
        "src_extra": ("各期业绩 8-K EX-99.1 的全年指引段；"
                      "柱子只画公司给出数字区间的年份，文字口径的年份不换算、不上图。"),
    })

    return charts, {"opex": opex_tally, "tax": tax_tally,
                    "opex_years": opex_years, "tax_years": tax_years,
                    "numeric_years": numeric_years, "word_years": word_years,
                    "census": census}


# ── section one (a)(b): what the previous local analysis left open ───────────
#
# From the second local analysis on, section one opens with what the previous
# one asked -- its Follow-up Questions, judged in this quarter's section 0
# (`followup_closure`) -- and set: its section 8 thresholds, settled against
# this quarter's readings (`prior_kpi_settlement`). A threshold names the series
# it is read from (`reads`) and never carries a reading of its own: the reading
# is taken here from the series, so a roll moves last quarter's
# `next_kpi.quantified` into `prior_kpi_settlement` as it stood and edits
# nothing else. The first analysis (`analysis_record.first_period`) has neither
# block and says so.

# The first full quarter of the combined company: Bats is consolidated from
# 2017-02-28, so 2017Q1 carries one month of it beside three-month quarters.
NET_REVENUE_FROM = "2017Q2"


def quarter_order(label: str) -> tuple[int, int]:
    """``'Q3 2026'`` / ``'2026Q3'`` → ``(2026, 3)``, so two quarter labels compare."""
    quarter, year = display_period(label).split()
    return int(year), int(quarter[1])


def next_period(label: str) -> str:
    """``'Q4 2026'`` → ``'Q1 2027'``."""
    year, quarter = quarter_order(label)
    return f"Q1 {year + 1}" if quarter == 4 else f"Q{quarter + 1} {year}"


def kpi_history(staging: dict, reads: str) -> tuple[list[str], list, dict]:
    """One threshold metric's own record, ending at this quarter's reading.

    Returns (period keys, values, spec). Every metric a local analysis has set a
    threshold on is read from the series here and only here. Growth conditions
    ("环比为负") are carried as ratios against 1.00, because their threshold is
    zero growth and a percentage headroom against zero is undefined.
    """
    kpi, kpil, long = staging["kpi"], staging["kpi_long"], staging["long"]
    nr = staging["net_revenue_window"]
    start = nr["quarters"].index(NET_REVENUE_FROM)
    nr_quarters, net = nr["quarters"][start:], nr["net_revenue"][start:]
    if reads == "net_revenue":
        return nr_quarters, net, {"name": "季度净收入", "fmt": "f0c", "ylab": "US$M"}
    if reads == "net_revenue_yoy":
        return (nr_quarters[4:], [pct_change(net[i], net[i - 4]) for i in range(4, len(net))],
                {"name": "净收入同比增速", "fmt": "pct1", "ylab": "同比 %"})
    if reads == "ml_share":
        first = next(i for i, v in enumerate(kpi["multi_listed_share_pct"]) if v is not None)
        return (kpi["quarters"][first:], kpi["multi_listed_share_pct"][first:],
                {"name": "Multi-listed 期权市占", "fmt": "pct1", "ylab": "%"})
    if reads == "ml_daily_revenue_qoq":
        money = [adv * rpc / 1000 for adv, rpc in
                 zip(kpi["multi_listed_adv_k"], kpi["multi_listed_rpc_usd"])]
        return (kpi["quarters"][1:], [money[i] / money[i - 1] for i in range(1, len(money))],
                {"name": "Multi-listed 日均收入 本季 ÷ 上季", "fmt": "f2", "ylab": "本季 ÷ 上季",
                 "growth": "环比"})
    if reads == "adj_opex":
        return (long["quarters"], long["adj_opex"],
                {"name": "调整后营业费用（季）", "fmt": "f0c", "ylab": "US$M"})
    if reads == "index_adv_qoq":
        adv = kpil["index_options_adv_k"]
        return (kpil["quarters"][1:], [adv[i] / adv[i - 1] for i in range(1, len(adv))],
                {"name": "指数期权 ADV 本季 ÷ 上季", "fmt": "f2", "ylab": "本季 ÷ 上季",
                 "growth": "环比"})
    if reads == "fy_adj_opex":
        # A full-year line: the year's reading exists once its four quarters are in
        # (the printed full-year actual when the series carries it, else their sum);
        # before that the year-to-date spend is context, not a reading.
        guide = staging["annual_guidance_history"]["adjusted_operating_expenses"]
        year = quarter_order(staging["periods"][-1])[0]
        years = [y for y in guide["years"] if y <= year]
        spent = [v for q, v in zip(long["quarters"], long["adj_opex"]) if q.startswith(str(year))]
        values = [guide["by_year"][str(y)]["actual"] for y in years]
        if values[-1] is None and len(spent) == 4:
            values[-1] = sum(spent)
        return ([f"FY{y}" for y in years], values,
                {"name": "全年调整后营业费用", "fmt": "f0c", "ylab": "US$M", "annual": True,
                 "ytd": sum(spent), "ytd_quarters": len(spent),
                 "break_at": years.index(2017) if 2017 in years else None,
                 "break_label": "Bats 交割（2017-02-28）：口径换过一次"})
    raise ValueError(f"a threshold entry reads {reads!r}, which build/cboe.py does not know")


def history_labels(keys: list[str], spec: dict) -> list[str]:
    return list(keys) if spec.get("annual") else axis([compact(q) for q in keys])


def reading(staging: dict, entry: dict):
    """This quarter's reading of a threshold's metric (None for a full-year line
    whose year is not over)."""
    return kpi_history(staging, entry["reads"])[1][-1]


def value_text(entry: dict, value: float, spec: dict) -> str:
    text = unit_text(entry["unit"], value)
    if entry["unit"] == "times":
        text += f"（即{spec['growth']} {minus_sign(signed((value - 1) * 100))}）"
    return text


def pending_text(entry: dict, spec: dict) -> str:
    """What a full-year line shows before its year is over: the spend so far, at
    the release's own precision (`usd_m` would round US$417.6M to $418M)."""
    spent = (f"US${spec['ytd']:,.1f}M" if entry["unit"] == "usd_m"
             else unit_text(entry["unit"], spec["ytd"]))
    return f"年初至今 {spent}（{cn_count(spec['ytd_quarters'])}季）"


def breach_run(values: list, entry: dict) -> int:
    """How many readings in a row, up to this one, sit on the wrong side of the line."""
    count = 0
    for value in reversed(values):
        if value is None or headroom(entry["direction"], entry["threshold"], value) >= 0:
            break
        count += 1
    return count


def verdicts_for(staging: dict, entries: list[dict], value_key: str) -> dict[str, dict]:
    """Per threshold: did the reading cross the line, and did the analysis's own
    trigger fire -- a consecutive line needs the run of crossed readings."""
    out = {}
    for entry in entries:
        values = kpi_history(staging, entry["reads"])[1]
        crossed = headroom(entry["direction"], entry["threshold"], entry[value_key]) < 0
        run, need = breach_run(values, entry), entry.get("consecutive", 1)
        out[entry["id"]] = {"crossed": crossed, "run": run, "need": need,
                            "triggered": crossed and run >= need}
    return out


def settlement_blocks(staging: dict, period: str) -> tuple[bool, dict | None, dict | None]:
    """Whether this quarter's local analysis is the first, and what the previous one left.

    The first CBOE analysis (`analysis_record.first_period`) has no previous one,
    so its section one settles only the company's guidance and says why. Any
    later quarter has a previous analysis by construction: a roll that leaves
    both blocks out would publish a section one that silently skipped it, so
    that stops the build.
    """
    record = staging.get("analysis_record")
    first = record is not None and display_period(record["first_period"]) == display_period(period)
    closure = stamped_block(staging, "followup_closure", period)
    prior = stamped_block(staging, "prior_kpi_settlement", period)
    present = [key for key, block in (("followup_closure", closure), ("prior_kpi_settlement", prior))
               if block is not None]
    if first and present:
        raise ValueError(f"{period} is the first CBOE analysis, so there is nothing for "
                         f"{', '.join(present)} to settle")
    if not first and not present:
        raise ValueError(f"{period} is not the first CBOE analysis: section one must settle the "
                         "previous one -- add `followup_closure` (its section 0) and "
                         "`prior_kpi_settlement` (its section 8 thresholds) to the series")
    set_in = {block["set_in"] for block in (closure, prior) if block is not None}
    if len(set_in) > 1:
        raise ValueError(f"`followup_closure` and `prior_kpi_settlement` name different analyses: "
                         f"{sorted(set_in)}")
    if set_in and quarter_order(next(iter(set_in))) >= quarter_order(period):
        raise ValueError(f"the settlement blocks say they were set in {next(iter(set_in))!r}, "
                         f"which is not before {period!r}")
    return first, closure, prior


def story_values(staging: dict) -> dict[str, str]:
    """The numbers a one-quarter sentence in the series may name, computed here.

    A stamped block's prose names a series number by placeholder
    (``{adj_opex}``) rather than typing it, so the two cannot disagree.
    """
    fin, kpi = staging["financials"], staging["kpi"]
    div = divergence_long(staging)
    money = div["daily_revenue_usd_m"]
    return {
        "net_revenue": f"US${fin['net_revenue'][-1]:,.1f}M",
        "net_revenue_yoy": signed(pct_change(fin["net_revenue"][-1], fin["net_revenue"][-5])),
        "adj_opex": f"US${fin['adj_opex'][-1]:.1f}M",
        "ml_share": f"{kpi['multi_listed_share_pct'][-1]:.1f}%",
        "ml_money": f"US${money[-1]:.3f}M/日",
        "ml_money_qoq": minus_sign(signed(pct_change(money[-1], money[-2]))),
    }


def closure_counts(closure: dict) -> list[int]:
    """The count per verdict, counted from the block's own items."""
    labels, items = closure["labels"], closure["items"]
    unknown = sorted({item["verdict"] for item in items} - set(labels))
    if unknown:
        raise ValueError(f"`followup_closure` items carry verdicts that are not labels: {unknown}")
    return [sum(1 for item in items if item["verdict"] == label) for label in labels]


def closure_exhibit(closure: dict, values: dict[str, str]) -> dict:
    counts = closure_counts(closure)
    total = sum(counts)
    items = closure["items"]
    numbered = list(enumerate(items, 1))
    detail = "；".join(
        f"{label}的{cn_count(count)}条是"
        + "、".join(f"第 {i} 条「{item['short']}」" for i, item in numbered if item["verdict"] == label)
        for label, count in zip(closure["labels"][1:], counts[1:]) if count)
    corrections = "".join(f"第 {i} 条：{fill_story(item['filing_note'], values)}"
                          for i, item in numbered if item.get("filing_note"))
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
                 "本季那一份在第 0 节逐条判定。"
                 + (f"第 0 节只有逐条判定、没有统计行，这里的计数按判定原文归类：{closure['rule']}"
                    if closure.get("rule") else "")
                 + (detail + "。" if detail else "")
                 + (f"<b>判定照录报告，理由按申报核过：</b>{corrections}" if corrections else "")),
        "src_extra": (f"问题清单来自上季（{closure['set_in']}）本地分析稿的 Follow-up Questions；"
                      "判定照录本季本地分析稿第 0 节，本页不改判；申报核对取自本季与上季的 10-Q、"
                      "业绩新闻稿，逐条见核对抽屉。"),
    }


def closure_table(closure: dict, values: dict[str, str]) -> dict:
    return {
        "n": 0,
        "title": f"上季（{closure['set_in']}）留下的待验证问题：本季报告第 0 节逐条判定与申报核对",
        "headers": ["#", "问题", "报告判定（原文）", "归类", "申报核对"],
        "rows": [[str(i), item["question"], item["report_verdict"], item["verdict"],
                  plain_text(fill_story(item["evidence"], values))]
                 for i, item in enumerate(closure["items"], 1)],
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
        target.append({**entry, "actual": reading(staging, entry)})
    missing = [entry["id"] for entry in due if entry["actual"] is None]
    if missing:
        raise ValueError(f"prior thresholds {missing} are due in {period} but the series has no "
                         "reading for them yet")
    return due, later


def threshold_lines(staging: dict, group: list[dict], label: str, verdicts: dict | None,
                    value_key: str, note: str, src_extra: str, ref: str) -> dict:
    """One chart per metric: its own record against every threshold set on it."""
    keys, values, spec = kpi_history(staging, group[0]["reads"])
    first = group[0]
    if verdicts is None:
        head = (f"{label} " + "、".join(unit_text(e["unit"], e["threshold"]) for e in group)
                + f"，当前 {value_text(first, first[value_key], spec)}")
    else:
        marks = ["击穿" if verdicts[e["id"]]["crossed"] else "守住" for e in group]
        head = ("；".join(f"{mark}{label} {unit_text(e['unit'], e['threshold'])}"
                         for mark, e in zip(marks, group)) if len(set(marks)) > 1 else
                f"{marks[0]}{label} " + "、".join(unit_text(e["unit"], e["threshold"]) for e in group))
    side = "高于" if first["direction"] == "up" else "低于"
    chart = threshold_exhibit(
        f"{first['metric'] if len(group) == 1 else spec['name']}：{head}",
        history_labels(keys, spec), rounded(values), first["threshold"],
        fmt=spec["fmt"], ylab=spec["ylab"], actual_name=spec["name"],
        threshold_name=f"{label} {unit_text(first['unit'], first['threshold'])}（{side}为安全）",
        note=note, src_extra=src_extra,
    )
    for extra in group[1:]:
        chart["series"].append({"name": f"{label} {unit_text(extra['unit'], extra['threshold'])}",
                                "values": [extra["threshold"]] * len(keys), "color": "GOLD"})
    for entry in group:
        upside = entry.get("upside") or {}
        if "above" in upside or "below" in upside:
            level = upside.get("above", upside.get("below"))
            chart["series"].append({"name": f"上行线 {unit_text(entry['unit'], level)}",
                                    "values": [level] * len(keys), "color": "GREEN"})
    if spec.get("break_at") is not None:
        chart["break_at"] = spec["break_at"]
        chart["break_label"] = spec["break_label"]
    chart["ref"] = ref
    return chart


def line_note(staging: dict, entry: dict, verdict: dict, value_key: str,
              values: dict[str, str]) -> str:
    """The sentence under a threshold line: the clause it comes from, this reading,
    the analysis's own trigger rule, and how often the record sat past the line."""
    keys, record, spec = kpi_history(staging, entry["reads"])
    up = entry["direction"] == "up"
    words = (f"{entry['basis']}：{'不低于' if up else '不高于'} "
             f"{unit_text(entry['unit'], entry['threshold'])}；本季 "
             f"{value_text(entry, entry[value_key], spec)}，"
             f"{'越线' if verdict['crossed'] else '仍在安全侧'}（余量 "
             f"{headroom(entry['direction'], entry['threshold'], entry[value_key]):+.1f}%）")
    if verdict["need"] > 1:
        words += (f"。这条要连续{cn_count(verdict['need'])}季越线才算触发："
                  + (f"本季已是连续第{cn_ordinal(verdict['run'])}季，触发" if verdict["run"] >= verdict["need"] else
                     f"本季是连续第{cn_ordinal(verdict['run'])}季，还差{cn_count(verdict['need'] - verdict['run'])}季"
                     if verdict["run"] else "本季没有越线，连续计数归零"))
    upside = entry.get("upside") or {}
    if "above" in upside:
        words += (f"。另一头的上行线 {unit_text(entry['unit'], upside['above'])}（{upside['basis']}），"
                  f"本季{'已经' if entry[value_key] > upside['above'] else '还没有'}越过")
    if "below" in upside:
        words += (f"。另一头的上行线 {unit_text(entry['unit'], upside['below'])}（{upside['basis']}），"
                  f"本季{'已经' if entry[value_key] < upside['below'] else '还没有'}落到它下面")
    unit_word = "年" if spec.get("annual") else "季"
    past = [v for v in record if v is not None
            and headroom(entry["direction"], entry["threshold"], v) < 0]
    words += (f"。{len([v for v in record if v is not None])} {unit_word}里落在这条线"
              f"{'下方' if up else '上方'}的有 {len(past)} {unit_word}。")
    if entry.get("caveat"):
        words += fill_story(entry["caveat"], values)
    return words


def settlement_extra(staging: dict, entry: dict) -> str:
    """What a settled line cannot say by itself: for the share line, what the money did."""
    if entry["reads"] != "ml_share":
        return ""
    money = divergence_long(staging)["daily_revenue_usd_m"]
    move = pct_change(money[-1], money[-2])
    if headroom(entry["direction"], entry["threshold"], entry["actual"]) >= 0 and move < 0:
        return (f"<b>但它守住的这一季，这门生意的日均收入环比少了 {abs(move):.1f}%。</b>"
                "为什么一条没破的线仍然给错了信号，是下一节要回答的问题 —— 见 Exhibit {EX_DIVERGE}。")
    return (f"同一季这门生意的日均收入环比 {minus_sign(signed(move))}。"
            "份额与钱为什么常常走反方向，见 Exhibit {EX_DIVERGE}。")


def settlement_section(staging: dict, period: str, closure: dict | None, prior: dict | None,
                       values: dict[str, str]) -> tuple[list[dict], list[dict], dict]:
    """Section one's (a) and (b): the charts, the drawer tables, and the counts the prose names."""
    charts, tables = [], []
    counts = {"questions": 0, "due": [], "later": [], "not_carried": [], "set_in": None}
    if closure is not None:
        charts.append(closure_exhibit(closure, values))
        tables.append(closure_table(closure, values))
        counts["questions"] = sum(closure_counts(closure))
        counts["set_in"] = closure["set_in"]
    if prior is None:
        return charts, tables, counts

    set_in = prior["set_in"]
    due, later = settlement_entries(staging, prior, period)
    not_carried = prior.get("not_carried", [])
    counts.update({"due": due, "later": later, "not_carried": not_carried, "set_in": set_in})
    verdicts = verdicts_for(staging, due, "actual")
    crossed = [e for e in due if verdicts[e["id"]]["crossed"]]
    triggered = [e for e in due if verdicts[e["id"]]["triggered"]]
    title = (f"上季 {len(due)} 条量化阈值："
             + (("全部守住" if len(due) > 1 else "守住") if not crossed else
                f"{len(due) - len(crossed)} 条守住、{len(crossed)} 条越线")
             + ("" if len(triggered) == len(crossed) else
                "，按触发条件一条都没有触发" if not triggered else
                f"，按触发条件触发 {len(triggered)} 条"))
    overview = headroom_exhibit(
        title, due, "actual",
        (f"正值 = 仍在安全侧。阈值是上季（{set_in}）那一份本地分析第 8 节「关键观察指标」设的，"
         f"本季读数取自 {quarter_words(period)}业绩新闻稿；逐条的来源与读法写在各自的历史图下。"
         + "".join(f"另有一条要到 {entry['settles']} 才结算：{entry['metric']}，"
                   f"{pending_text(entry, kpi_history(staging, entry['reads'])[2])}，不进这张图。"
                   for entry in later)
         + (f"上季第 8 节还有{cn_count(len(not_carried))}项本页不结算 —— "
            + "；".join(f"<b>{item['metric']}</b>（{item['basis']}：{item['rule']}）—— "
                       + fill_story(item["why"], values) for item in not_carried) + "。"
            if not_carried else "")
         + "百分比与美元被归一化成「距阈值的余量」才能放在一根轴上；原始单位见核对抽屉。"),
        (f"阈值取自上季本地研究（{set_in} 季报分析第 8 节），不是公司指引；本季读数取自 "
         f"{quarter_words(period)}业绩新闻稿，比值与同比为本页相除 D。"),
    )
    overview["ref"] = "EX_PRIOR_HEADROOM"
    charts.append(overview)

    groups: dict[str, list[dict]] = {}
    for entry in due:
        groups.setdefault(entry["reads"], []).append(entry)
    for reads, group in groups.items():
        note = "".join(line_note(staging, entry, verdicts[entry["id"]], "actual", values)
                       + settlement_extra(staging, entry) for entry in group)
        charts.append(threshold_lines(
            staging, group, "上季阈值", verdicts, "actual", note,
            f"阈值：上季本地研究（{set_in} 季报分析第 8 节）；读数：各期业绩 8-K EX-99.1，"
            "比值与同比为本页相除 D。",
            f"EX_PRIOR_{reads.upper()}"))

    rows = []
    for entry in due + later:
        spec = kpi_history(staging, entry["reads"])[2]
        verdict = verdicts.get(entry["id"])
        pending = verdict is None
        rows.append([
            entry["metric"],
            "高于阈值为安全" if entry["direction"] == "up" else "低于阈值为安全",
            unit_text(entry["unit"], entry["threshold"]),
            pending_text(entry, spec) if pending else value_text(entry, entry["actual"], spec),
            "—" if pending else
            f"{headroom(entry['direction'], entry['threshold'], entry['actual']):+.1f}%",
            plain_text(entry["basis"]),
            f"未到期（{entry['settles']} 结算）" if pending else
            ("触发" if verdict["triggered"] else "越线未触发" if verdict["crossed"] else "守住"),
        ])
    for item in not_carried:
        rows.append([item["metric"], "—", item["rule"], "—", "—", item["basis"],
                     "本页不结算：" + item["short_why"]])
    tables.append({
        "n": 0,
        "title": f"上季（{set_in}）第 8 节阈值与本季读数（原始单位）",
        "headers": ["指标", "方向", "阈值", "本季读数", "余量 D", "出处（上季本地研究）", "判定"],
        "rows": rows,
    })
    return charts, tables, counts


def divergence_long(staging: dict) -> dict:
    """The multi-listed record over the whole KPI window, not the last 29.

    `divergence` in the series file is exactly the tail of `kpi` plus one
    derived column (daily revenue = ADV x RPC). Nothing about the earlier
    quarters is missing or on another basis -- they are in `kpi` already -- so
    the charts that carry this page's central argument run the full record and
    the shorter block stays as the cross-check.
    """
    kpi = staging["kpi"]
    built = {
        "quarters": kpi["quarters"],
        "period_labels": kpi["period_labels"],
        "share_pct": kpi["multi_listed_share_pct"],
        "adv_k": kpi["multi_listed_adv_k"],
        "rpc_usd": kpi["multi_listed_rpc_usd"],
    }
    built["daily_revenue_usd_m"] = [
        adv * 1000 * rpc / 1e6
        for adv, rpc in zip(built["adv_k"], built["rpc_usd"])
    ]
    # The stored block has to agree with the rebuilt one everywhere they meet,
    # or one of the two is wrong and the argument rests on the wrong half.
    stored = staging["divergence"]
    at = {quarter: index for index, quarter in enumerate(built["quarters"])}
    for index, quarter in enumerate(stored["quarters"]):
        position = at[quarter]
        for key in ("share_pct", "adv_k", "rpc_usd", "daily_revenue_usd_m"):
            assert abs(stored[key][index] - built[key][position]) < 2e-3, (quarter, key)
    return built


def share_window(div: dict) -> int:
    """Where the share line starts: the first quarter Cboe printed it."""
    return next(index for index, value in enumerate(div["share_pct"]) if value is not None)


def multiple_words(ratio: float) -> str:
    """「多了两倍出头」 for a ratio of 3.24: the increase, not the multiple."""
    increase = ratio - 1
    whole = int(increase)
    if increase - whole < 0.5:
        return f"{cn_count(whole)}倍出头" if whole else f"{round(increase * 100)}%"
    return f"近{cn_count(whole + 1)}倍"


# ── section two: share against the money ────────────────────────────────────
def highlight_exhibits(staging: dict, context: dict | None,
                       prior_due: list[dict]) -> tuple[list[dict], dict]:
    div = divergence_long(staging)
    steps = direction_steps(div["share_pct"], div["daily_revenue_usd_m"])
    labels = axis([compact(q) for q in div["quarters"]])
    # The share line starts at 2019Q2 -- Cboe did not print a multi-listed share
    # separately before then -- while ADV and RPC, and so the money, run the
    # whole window. One axis, two starts, both stated on the chart.
    share_from = share_window(div)
    share, money = div["share_pct"], div["daily_revenue_usd_m"]
    years = round((len(div["quarters"]) - 1 - share_from) / 4)
    share_drop = 1 - share[-1] / share[share_from]
    unit = min(range(2, 11), key=lambda d: abs(abs(share_drop) - 1 / d))
    share_frac = cn_fraction(abs(share_drop))
    if abs(abs(share_drop) - 1 / unit) >= 0.01:
        share_frac = ("近" + share_frac) if abs(share_drop) < 1 / unit else (share_frac + "多")
    story = ""
    if share_drop > 0 and money[-1] > money[share_from]:
        story = (f"<b>{cn_count(years)}年里份额掉了{share_frac}，"
                 f"钱多了{multiple_words(money[-1] / money[share_from])}。</b>")
    coin = (" —— 抛硬币大约是一半一半，所以「份额」这个变量对「钱」几乎不含信息，甚至略微反着来。"
            if steps["opposite"] > steps["same"] else
            (" —— 正好一半一半。" if steps["opposite"] == steps["same"] else "。"))
    latest = steps["verdicts"][-1]
    share_move = share[-1] - share[-2]
    money_move = pct_change(money[-1], money[-2])
    now_words = ""
    if latest == "反向":
        now_words = (f"本季正是反向的又一次：份额 {signed(share_move, 1, 'pp')}，"
                     f"日均收入 {minus_sign(signed(money_move))}。")
    elif latest == "同向":
        now_words = (f"本季两者同向：份额 {signed(share_move, 1, 'pp')}，"
                     f"日均收入 {minus_sign(signed(money_move))}。")
    share_entry = next((e for e in prior_due if e["reads"] == "ml_share"), None)
    pointer = ""
    if share_entry:
        pointer = ("上一节 Exhibit {EX_PRIOR_ML_SHARE} 那条"
                   + ("没有触发的" if share[-1] >= share_entry["threshold"] else "已经触发的")
                   + "阈值，就设在橙线上。")

    charts = [{
        "ref": "EX_DIVERGE",
        "kind": "bar_line_dual",
        "title": (f"Multi-listed 期权：{len(div['quarters'])} 个季度、"
                  f"{steps['steps']} 次环比里，市占与日均收入有 "
                  f"{steps['opposite']} 次走反方向"),
        "xlabels": labels,
        "bar": {"name": "日均收入 = ADV × RPC（US$M/日）",
                "values": rounded(money), "color": "BLUE"},
        "line": {"name": "Multi-listed 市占（RHS）", "color": "ORANGE",
                 "values": rounded(share), "yfmt": "pct1"},
        "fmt": "f2", "yfmt": "f2", "label_fmt": "f2",
        "ylab": "US$M/日", "ylab2": "%",
        "note": (
            "<b>这是本页的核心。</b>两条线来自公司同一张表的同一列季度："
            "橙线是被引用最多的市占率，柱子是 ADV 乘 RPC —— 这门生意每天真正收到的钱。"
            f"市占那条线自己的窗口（{div['period_labels'][share_from]} 起）两端："
            f"从 {share[share_from]:.1f}% {'落到' if share[-1] < share[share_from] else '升到'} "
            f"{share[-1]:.1f}%"
            f"（{signed(share[-1] - share[share_from], 1, 'pp')}），"
            f"同期日均收入从 US${money[share_from]:.3f}M "
            f"{'升到' if money[-1] > money[share_from] else '落到'} "
            f"US${money[-1]:.3f}M"
            f"（{signed(pct_change(money[-1], money[share_from]), 0)}）。"
            f"<b>柱子比线长{cn_count(share_from)}格，那不是缺数据。</b>"
            f"ADV 与 RPC 两条公司都从 {div['quarters'][0]} 起按季披露，所以钱这一侧回得到 "
            f"{div['quarters'][0][:4]}；"
            f"而「multi-listed 市占」这个单独的百分比要到 {div['quarters'][share_from]} 才第一次印出来。"
            f"把柱子自己的全窗口两端也放在这里：US${money[0]:.3f}M → "
            f"US${money[-1]:.3f}M"
            f"（{signed(pct_change(money[-1], money[0]), 0)}）。"
            + story
            + f"逐季看，{steps['steps']} 次环比里 {steps['opposite']} 次两者方向相反、"
            f"{steps['same']} 次同向" + coin
            + now_words + pointer),
        "src_extra": ("ADV、RPC 与市占率三者都取自各期业绩 8-K EX-99.1 的经营指标表；"
                      "日均收入 = ADV（千手）× RPC（US$/手）÷ 1000，为透明自算（D）。"
                      "窗口起点是公司开始披露 multi-listed 市占率的那一季。"),
    }]

    kpi = staging["kpi"]
    index_rpc, multi_rpc = kpi["index_options_rpc_usd"], kpi["multi_listed_rpc_usd"]
    index_falls, index_steps = falls(index_rpc)
    opposite_ways = index_rpc[-1] > index_rpc[0] and multi_rpc[-1] < multi_rpc[0]
    magnitude = index_rpc[-1] / multi_rpc[-1]
    index_path = (f"RPC 从 ${index_rpc[0]:.3f} 一路走到 ${index_rpc[-1]:.3f}，几乎只往上；"
                  if index_falls <= index_steps // 10 else
                  f"RPC 从 ${index_rpc[0]:.3f} 走到 ${index_rpc[-1]:.3f}，"
                  f"总体向上（{index_steps} 次环比里 {index_falls} 次回落）；")
    charts.append({
        "ref": "EX_RPC",
        "kind": "lines",
        "title": (("两类期权的每合约收入差着一个数量级" if 10 <= magnitude < 100 else
                   f"两类期权的每合约收入差着 {magnitude:.0f} 倍")
                  + ("，而且走向相反：" if opposite_ways else "：")
                  + f"指数期权 ${index_rpc[-1]:.3f}、"
                  f"multi-listed ${multi_rpc[-1]:.3f}"),
        "xlabels": axis([compact(q) for q in kpi["quarters"]]),
        "series": [
            {"name": "指数期权 RPC", "values": rounded(index_rpc), "color": "NAVY"},
            {"name": "Multi-listed 期权 RPC", "values": rounded(multi_rpc), "color": "RED"},
        ],
        "fmt": "usd3", "yfmt": "usd3", "label_fmt": "usd3",
        "end_label": True,
        "ylab": "US$/合约",
        "note": (
            "<b>这是上一张图为什么会发生的机制。</b>Cboe 的期权业务其实是两门生意："
            "指数期权是它独家挂牌的自有产品，"
            + index_path
            + "multi-listed 是十几家交易所挂同一批合约、靠返点抢单流的同质化市场，"
            f"RPC 在 ${min(v for v in multi_rpc if v):.3f}–"
            f"${max(v for v in multi_rpc if v):.3f} 之间来回，"
            f"本季环比 {minus_sign(signed(pct_change(multi_rpc[-1], multi_rpc[-2])))}。"
            "<b>在后一门生意里，量和价是可以互换的</b> —— 多给返点就能买到份额，"
            "份额涨和单价跌是同一个动作的两面。"
            "所以只盯量、或只盯价、或只盯份额的阈值都会失效，"
            "唯一不会失效的是两者的乘积。"),
        "src_extra": "各期业绩 8-K EX-99.1 的经营指标表；两条都是公司披露值。",
    })

    off = staging["offexchange"]
    cashm = staging["cash_markets"]
    off_steps = direction_steps(off["share_pct"], off["daily_revenue_usd_k"])
    closer_to_half = (abs(off_steps["opposite"] / off_steps["steps"] - 0.5)
                      < abs(steps["opposite"] / steps["steps"] - 0.5))
    off_share_yoy = off["share_pct"][-1] - off["share_pct"][-5]
    off_capture_yoy = pct_change(off["net_capture_per_100"][-1], off["net_capture_per_100"][-5])
    share_yoys = {
        "multi": share[-1] - share[-5],
        "total_options": kpi["total_options_share_pct"][-1] - kpi["total_options_share_pct"][-5],
        "us": cashm["us_share_pct"][-1] - cashm["us_share_pct"][-5],
        "europe": cashm["european_share_pct"][-1] - cashm["european_share_pct"][-5],
        "off": off_share_yoy,
    }
    best = max(share_yoys, key=share_yoys.get) == "off"
    glare = ""
    if off_share_yoy > 0 and off_capture_yoy < 0:
        glare = ("本季这条尤其扎眼：份额同比 "
                 f"{signed(off_share_yoy, 1, 'pp')}"
                 + (" 是全公司最漂亮的一条" if best else "")
                 + f"，而每百股 net capture 同比 {minus_sign(signed(off_capture_yoy))}。")
    charts.append({
        "ref": "EX_OFF",
        "kind": "bar_line_dual",
        "title": (f"同一形状在股票撮合里重演：场外大宗 {len(off['quarters'])} 季、"
                  f"{off_steps['steps']} 次环比里 {off_steps['opposite']} 次反向"),
        "xlabels": axis([compact(q) for q in off["quarters"]]),
        "bar": {"name": "日均收入 = ADV × net capture（US$千/日）",
                "values": rounded(off["daily_revenue_usd_k"]), "color": "BLUE"},
        "line": {"name": "场外大宗市占（RHS）", "color": "ORANGE",
                 "values": rounded(off["share_pct"]), "yfmt": "pct1"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$千/日", "ylab2": "%",
        "note": (
            "把同样的算术搬到另一门生意上，形状没变："
            f"份额从 {off['share_pct'][0]:.1f}% 走到 {off['share_pct'][-1]:.1f}%，"
            f"日均收入从 US${off['daily_revenue_usd_k'][0]:,.0f} 走到 "
            f"US${off['daily_revenue_usd_k'][-1]:,.0f}。"
            f"{off_steps['steps']} 次环比里 {off_steps['opposite']} 次反向 —— "
            + ("比 multi-listed 那张更接近一半一半，但结论一样："
               if closer_to_half else "结论和 multi-listed 那张一样：")
            + "份额单独看不构成信号。"
            + glare),
        "src_extra": ("ADV（百万股）与 net capture（US$/百股）取自各期 EX-99.1 经营指标表；"
                      "日均收入 = ADV × 10⁶ ÷ 100 × net capture ÷ 1000，为透明自算（D）。"),
    })

    us_share, us_capture = cashm["us_share_pct"], cashm["us_net_capture_per_100"]
    halved = us_share[-1] <= us_share[0] / 2
    flat = us_capture[-1] == us_capture[0]
    charts.append({
        "ref": "EX_ONEX",
        "kind": "bar_line_dual",
        "title": (f"交易所内侧则是反过来的：美股市占从 {us_share[0]:.1f}% "
                  f"{'腰斩' if halved else '降'}到 {us_share[-1]:.1f}%，"
                  + ("每百股 net capture 回到原点" if flat else
                     f"每百股 net capture 从 ${us_capture[0]:.3f} 到 ${us_capture[-1]:.3f}")),
        "xlabels": axis([compact(q) for q in cashm["quarters"]]),
        "bar": {"name": "美股交易所市占", "values": rounded(us_share),
                "color": "BLUE"},
        "line": {"name": "每百股 net capture（US$，RHS）", "color": "ORANGE",
                 "values": rounded(us_capture), "yfmt": "usd3"},
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1",
        "ylab": "%", "ylab2": "US$/百股",
        "note": (
            # This printed 「份额掉了 -11.9 个百分点」: the sign of a fall was
            # formatted into a sentence that already says it fell.
            f"{len(cashm['quarters'])} 个季度，份额"
            + (f"掉了 {us_share[0] - us_share[-1]:.1f} 个百分点"
               if us_share[-1] < us_share[0] else
               f"涨了 {us_share[-1] - us_share[0]:.1f} 个百分点")
            + f"，而 net capture 从 ${us_capture[0]:.3f} 到 "
            f"${us_capture[-1]:.3f}"
            + (" —— 首尾同一个数。" if flat else "。")
            + "<b>这条线的分母是全美股票成交量，包含场外</b>，"
            "所以它下滑的另一半正是上一张图里那门场外生意在长大："
            "同一家公司在交易所里让出份额、在场外买进份额，"
            "两边的价格走向也正好相反。公司没有在任何一期新闻稿里定义过这个分母，"
            "本页据行业口径与序列本身没有断点这一点来读它。"),
        "src_extra": "各期业绩 8-K EX-99.1 经营指标表；两条都是公司披露值。",
    })

    nr = staging["net_revenue_window"]
    pass_through = [round(r / t * 100, 6) if t else None
                    for r, t in zip(nr["regulatory_fees_cost"], nr["total_revenues"])]
    not_ours = nr["cost_of_revenues"][-1] / nr["total_revenues"][-1] * 100
    fees = nr["regulatory_fees_cost"]
    wedge_story = (context or {}).get("wedge_story", "")
    charts.append({
        "ref": "EX_WEDGE",
        "kind": "stacked_dual",
        "title": (f"毛收入与净收入之间那道楔子：本季总收入 US${nr['total_revenues'][-1]:,.1f}M，"
                  f"留下的净收入 US${nr['net_revenue'][-1]:,.1f}M"),
        "xlabels": axis([compact(q) for q in nr["quarters"]]),
        "stacks": [
            {"name": "流动性返点", "color": "BLUE", "values": rounded(nr["liquidity_payments"])},
            {"name": "Section 31 等监管规费（代收代付）", "color": "GOLD",
             "values": rounded(nr["regulatory_fees_cost"])},
            {"name": "路由清算与版税等", "color": "ORANGE",
             "values": rounded([a + b for a, b in zip(nr["routing_and_clearing"],
                                                      nr["royalty_and_other_cost"])])},
            {"name": "净收入（公司自己的头条口径）", "color": "NAVY",
             "values": rounded(nr["net_revenue"])},
        ],
        "line": {"name": "监管规费占总收入 (RHS)", "color": "RED",
                 "values": rounded(pass_through), "yfmt": "pct1", "ymax": 30},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M", "ylab2": "规费占比",
        "note": (
            # 「一半以上不属于公司」: this quarter it is 49.3% -- net revenue is
            # just over half of the gross line.
            ("<b>「总收入」这条线一半以上不属于公司。</b>" if not_ours > 50 else
             f"<b>「总收入」这条线本季有 {not_ours:.1f}% 不属于公司。</b>")
            + "四段自下而上是付给流动性提供方的返点、"
            "代 SEC 收取再上缴的监管规费、路由清算与指数版税，"
            "以及公司真正留下的净收入 —— 也是它自己每期头条用的口径。"
            f"规费那一段在本窗口里从 US${min(fees):,.1f}M 到 "
            f"US${max(fees):,.1f}M 之间开关式跳动："
            f"<b>本季 {usd_zero(fees[-1])}，上一季是 {usd_zero(fees[-2])}</b>，费率由 SEC 定、不由公司定。"
            "它同时进收入和进成本，所以对净收入几乎没有影响 —— "
            "本季收入端 US$"
            f"{nr['regulatory_fees_revenue'][-1]:,.1f}M、成本端 {usd_zero(fees[-1])}。"
            "<b>只把成本端剥掉、不同时剥收入端，会把一个中性项读成一次巨大的收入注水</b>"
            + (" —— " + wedge_story if wedge_story else "。")),
        "src_extra": ("各期业绩 8-K EX-99.1 的合并损益表；四段相加等于总收入，"
                      f"{len(nr['quarters'])} 个季度逐季核对无差。红线为自算（D）。"),
    })
    return charts, {"steps": steps, "off_steps": off_steps}


# ── section three: the same question pointed forward ────────────────────────
def next_exhibits(staging: dict, kpi: dict, settled: dict | None, context: dict | None,
                  has_share: bool) -> list[dict]:
    entries = kpi["quantified"]
    safe = sum(1 for e in entries
               if headroom(e["direction"], e["threshold"], e["current"]) >= 0)
    charts = [headroom_exhibit(
        f"下季 {len(entries)} 条阈值：当前值离阈值的余量，{safe} 条仍在安全侧",
        entries, "current",
        ("正值表示仍在安全侧。阈值为本地研究设定，<b>不是公司指引</b>。"
         + kpi.get("lead", "") + kpi["excluded"]),
        f"当前值为 {staging['periods'][-1]} 披露值或本页自算；阈值为本地研究设定。",
    )]

    div = divergence_long(staging)
    money = div["daily_revenue_usd_m"]
    share = staging["divergence"]["share_pct"]
    money_entry = next((e for e in entries if e["metric"].startswith("Multi-listed 日均收入")), None)
    share_entry = next((e for e in (settled or {}).get("quantified", [])
                        if e["metric"].startswith("Multi-listed")), None)
    if money_entry:
        money_threshold = money_entry["threshold"]
        money_move = pct_change(money[-1], money[-2])
        share_from = share_window(div)
        note = ""
        if has_share:
            # 「同一批季度」: that chart starts where the share line does, this one
            # where ADV and RPC do -- thirteen quarters earlier.
            note += ("和上一节 Exhibit {EX_PRIOR_ML_SHARE} 画的是同一门生意，只是纵轴换成了钱，"
                     f"窗口也更长：那张从 {div['period_labels'][share_from]} 起（市占那一季才开始印），"
                     f"这张从 {div['period_labels'][0]} 起。")
            if share_entry and share[-1] >= share_entry["threshold"] and money_move < 0:
                note += ("<b>两张图给出的信号在本季是相反的</b>：那张的线没有触发，"
                         f"这张环比 {minus_sign(signed(money_move))}。")
        note += money_entry.get("why", "")
        charts.append(threshold_exhibit(
            f"改写后的第一条：Multi-listed 日均收入 US${money[-1]:.3f}M/日",
            axis([compact(q) for q in div["quarters"]]),
            rounded(money),
            money_threshold,
            fmt="f2", ylab="US$M/日",
            actual_name="日均收入（ADV × RPC）", threshold_name=f"阈值 US${money_threshold:.2f}M/日",
            note=note,
            src_extra="ADV 与 RPC 为公司披露值，乘积为自算（D）。",
        ))

    long = staging["long"]
    opex_entry = next((e for e in entries if e["metric"].startswith("调整后营业费用")), None)
    if opex_entry:
        opex_threshold = opex_entry["threshold"]
        now = long["adj_opex"][-1]
        last_quarter = next((e for e in (settled or {}).get("quantified", [])
                             if e["metric"].startswith("调整后营业费用")), None)
        if last_quarter:
            title = (f"季度调整后营业费用：本季 US${now:.1f}M，"
                     + (f"已越过上季设下的 US${last_quarter['threshold']:.0f}M"
                        if now > last_quarter["threshold"] else
                        f"仍在上季设下的 US${last_quarter['threshold']:.0f}M 之内"))
            breached = [e for e in settled["quantified"]
                        if headroom(e["direction"], e["threshold"], e["actual"]) < 0]
            note = (f"上季那条线设在 US${last_quarter['threshold']:.0f}M，本季实际 US${now:.1f}M"
                    + (f"，是{cn_count(len(settled['quantified']))}条能结清的阈值里唯一越过的一条。"
                       if breached == [last_quarter] else "。"))
        else:
            title = f"季度调整后营业费用：本季 US${now:.1f}M，阈值 US${opex_threshold:.0f}M"
            note = ""
        guide = staging["annual_guidance_history"]["adjusted_operating_expenses"]
        open_year = max(guide["years"])
        guided = guide["by_year"][str(open_year)]["guided"]
        low, high, _ = guided[-1]
        reaffirmed = len(guided) > 1 and guided[-1][:2] == guided[-2][:2]
        australia = (context or {}).get("opex_guidance_carve_out")
        if reaffirmed and australia:
            # This said the $11M came out on the call; it is in the release's own
            # guidance footnote.
            note += (f"全年指引 US${low:,.0f}–{high:,.0f}M 表面上「重申」，"
                     f"但公司在本季新闻稿的指引脚注里说明其中含{australia['what']}带来的 "
                     f"US${australia['usd_m']:,.0f}M 减项 —— <b>同口径其实是上调</b>。")
        else:
            note += f"全年指引 US${low:,.0f}–{high:,.0f}M。"
        spent = [v for q, v in zip(long["quarters"], long["adj_opex"]) if q.startswith(str(open_year))]
        words = {1: ("第一季度", "后三季"), 2: ("上半年", "下半年"), 3: ("前三季", "第四季度")}
        if len(spent) in words:
            done, left = words[len(spent)]
            remaining = 4 - len(spent)
            per_high = (high - sum(spent)) / remaining
            per_mid = ((low + high) / 2 - sum(spent)) / remaining
            # The page said 「按指引上限倒推，下半年只剩约每季 US$214M 的额度，
            # 低于本季的实际值」: 214 is the midpoint; the upper bound leaves 217.7,
            # above this quarter's 216.7.
            note += (f"{done}已经花掉 US${sum(spent):.1f}M，按指引上限倒推，"
                     f"{left}{'每季' if remaining > 1 else ''}还有约 US${per_high:.1f}M 的额度"
                     + (f"，只比本季实际高 US${per_high - now:.1f}M" if per_high >= now else
                        f"，低于本季的实际值")
                     + f"；按指引中值倒推则是 US${per_mid:.1f}M"
                     + ("，低于本季的实际值。" if per_mid < now else "。"))
        note += (f"<b>这条线自己的记录有 {len(long['quarters'])} 个季度</b>，"
                 f"从 {long['period_labels'][0]} 的 US${long['adj_opex'][0]:.1f}M 起 —— "
                 f"整段窗口里落在 US${opex_threshold:.0f}M 之上的有 "
                 f"{sum(1 for v in long['adj_opex'] if v > opex_threshold)} 季，"
                 "阈值守的是「下一季会不会继续超」，不是「历史上从未超过」。")
        charts.append(threshold_exhibit(
            title,
            axis([compact(q) for q in long["quarters"]]),
            rounded(long["adj_opex"]),
            opex_threshold,
            fmt="f0c", ylab="US$M",
            actual_name="调整后营业费用（季）", threshold_name=f"阈值 US${opex_threshold:.0f}M",
            note=note,
            src_extra="各期业绩 8-K EX-99.1 的非 GAAP 调节表；指引取自同一份新闻稿的全年指引段。",
        ))
    return charts


# ── section four: the routine long series ───────────────────────────────────
def segment_exhibit(staging: dict) -> dict:
    """The five named segments and the sixth row that makes them add up.

    A long structural series with no one-quarter conclusion of its own, so it
    sits in 「长期常规跟踪」; this quarter's segment moves are read in section two.
    """
    seg = staging["segments"]
    # This used to draw the last 20 of the 37 reconciled quarters this file
    # already holds. The excuse on record said the five-segment structure "begins
    # 2021Q3; the earlier structure had different segments" -- but the series
    # itself runs to 2017Q2 with no break, so the axis was short by a hardcoded
    # number, not by anything about the filings.
    tail = len(seg["quarters"])
    seg_labels = [compact(q) for q in seg["quarters"][-tail:]]
    five = [sum(seg[key][i] for key in ("options", "north_american_equities",
                                        "europe_and_apac", "futures", "global_fx"))
            for i in range(tail)]
    five_off = sum(1 for f, t in zip(five, seg["total"]) if abs(f - t) > 0.05)
    six_ok = sum(1 for i, (f, t) in enumerate(zip(five, seg["total"]))
                 if abs(f + seg["corporate_digital"][i] - t) <= 0.05)
    return {
        "ref": "EX_SEG",
        "kind": "grouped_bars",
        "title": (f"五个分部的净收入，加上一条读者容易漏掉的第六行："
                  f"Options US${seg['options'][-1]:,.1f}M 占 "
                  f"{seg['options'][-1] / seg['total'][-1] * 100:.1f}%"),
        "xlabels": axis(seg_labels, 2),
        "groups": [
            {"name": "Options", "color": "NAVY", "values": rounded(seg["options"][-tail:])},
            {"name": "North American Equities", "color": "BLUE",
             "values": rounded(seg["north_american_equities"][-tail:])},
            {"name": "Europe and Asia Pacific", "color": "GOLD",
             "values": rounded(seg["europe_and_apac"][-tail:])},
            {"name": "Futures", "color": "GREEN", "values": rounded(seg["futures"][-tail:])},
            {"name": "Global FX", "color": "ORANGE", "values": rounded(seg["global_fx"][-tail:])},
            {"name": "Corporate / Digital", "color": "RED",
             "values": rounded(seg["corporate_digital"][-tail:])},
        ],
        "fmt": "f0c", "label_fmt": "f0c", "ylab": "US$M",
        "note": (
            "<b>第六根柱子是负的，而且大多数读者不会去找它。</b>"
            "分部表里那一行在两个时代是两样东西：2017–2022 年叫 Corporate，"
            "小额为正或为零；2022Q4–2024Q4 叫 Digital，"
            "是 2022 年 5 月收购、随后关掉的 Cboe Digital，"
            "净收入<b>为负</b>（表本身是扣掉收入成本之后的口径），"
            f"最深一季 −US${abs(min(seg['corporate_digital'])):.1f}M；"
            "2025Q1 起这一行消失。"
            # "25 of 37" was the count on record; the five named rows miss the
            # printed total exactly where the sixth row is not zero, 16 quarters.
            f"只取前五行会在 {tail} 个季度里的 {five_off} 个对不上公司自己印的合计，"
            "而差额还会中途换号 —— "
            + (f"六行相加则 {tail} 季全部对平，" if six_ok == tail else
               f"六行相加则 {tail} 季里 {six_ok} 季对平，")
            + "这也是本页把它画出来而不是抹掉的原因。"
            # "窗口只画最近 20 季" stayed behind when the axis was widened to all 37.
            f"窗口从 {seg['quarters'][0]} 起画满 {tail} 季；"
            "2017Q1 不画，因为 Bats 自 2017-02-28 才并表，"
            "那一季的三个分部是一个月对着别人的三个月。"),
        "src_extra": ("各期业绩 8-K EX-99.1 的分部表，逐季取自同一份新闻稿；"
                      f"六行相加与公司印出的合计在 {tail} 个季度里"
                      + ("全部一致（容差 0.05）。" if six_ok == tail else
                         f"有 {six_ok} 季一致（容差 0.05）。")),
    }


def routine_exhibits(staging: dict) -> list[dict]:
    long = staging["long"]
    kpil = staging["kpi_long"]
    cats = staging["categories"]
    cap = staging["capital"]
    fin = staging["financials"]
    margin = long["adj_op_margin_pct"]
    margin_move = margin[-1] - margin[-2]
    net_move = pct_change(fin["net_revenue"][-1], fin["net_revenue"][-2])
    opex_move = pct_change(long["adj_opex"][-1], long["adj_opex"][-2])
    if margin_move < 0 and abs(net_move) < 1 and opex_move > 0:
        margin_words = (f"本季 {margin[-1]:.1f}%，环比降 {abs(margin_move):.1f} 个百分点，"
                        "而降的这一段全部来自费用端 —— "
                        f"净收入环比几乎没动（{signed(net_move)}），调整后费用环比 {signed(opex_move)}。")
    else:
        margin_words = (f"本季 {margin[-1]:.1f}%，环比{'降' if margin_move < 0 else '升'} "
                        f"{abs(margin_move):.1f} 个百分点；净收入环比 {minus_sign(signed(net_move))}，"
                        f"调整后费用环比 {minus_sign(signed(opex_move))}。")
    rpc = kpil["index_options_rpc_usd"]
    rpc_falls, rpc_steps = falls(rpc)
    adv_ratio = kpil["index_options_adv_k"][-1] / kpil["index_options_adv_k"][0]

    charts = [{
        "ref": "EX_MARGIN",
        "kind": "lines",
        "title": (f"{len(long['quarters'])} 个季度的调整后营业利润率："
                  f"从 {margin[0]:.1f}% 到 "
                  f"{margin[-1]:.1f}%"),
        "xlabels": axis([compact(q) for q in long["quarters"]]),
        "series": [
            {"name": "调整后营业利润率", "values": rounded(margin),
             "color": "NAVY"},
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1",
        "ylab": "%",
        "note": (
            margin_words
            + f"窗口内的高点是 {max(margin):.1f}%，"
            f"低点 {min(margin):.1f}%。"
            "<b>这条线的分母在 2017 年 2 月之后才是「净收入」口径</b>，"
            "之前 CBOE Holdings 的收入里没有那么大的过路项；"
            "利润率在 2017 年前后的台阶主要是这次口径变化与 Bats 并表，不是经营效率的跳变。"),
        "src_extra": "各期业绩 8-K EX-99.1 的非 GAAP 调节表；利润率为公司披露值。",
    }, {
        "ref": "EX_INDEX",
        "kind": "bar_line_dual",
        # 「RPC 同期只往上」: 19 of its 58 quarter-on-quarter changes are falls.
        "title": (f"独家产品那门生意：指数期权 ADV 从 {kpil['index_options_adv_k'][0]:,.0f} 千手"
                  f"到 {kpil['index_options_adv_k'][-1]:,.0f} 千手，RPC 同期"
                  + ("只往上" if rpc_falls == 0 else
                     ("总体向上" if rpc[-1] > rpc[0] else "没有跟着涨"))),
        "xlabels": axis([compact(q) for q in kpil["quarters"]]),
        "bar": {"name": "指数期权 ADV（千手）",
                "values": rounded(kpil["index_options_adv_k"]), "color": "BLUE"},
        "line": {"name": "指数期权 RPC（US$，RHS）", "color": "ORANGE",
                 "values": rounded(rpc), "yfmt": "usd3"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "千手/日", "ylab2": "US$/合约",
        "note": (
            f"{len(kpil['quarters'])} 个季度 —— 本页最长的一条线，"
            "因为 Bats 没有指数期权也没有期货，这两行在收购前后指的是同一件事，"
            "2016 年四个重叠季度里新旧两张表印的数字完全相同。"
            # 「量涨了五倍」 for a ratio of 5.2: the volume rose to five times, not by.
            + (f"<b>量涨到{cn_count(int(adv_ratio))}倍多，价没有被摊薄</b>："
               if rpc[-1] >= rpc[0] else f"<b>量涨到{cn_count(int(adv_ratio))}倍多，价被摊薄了</b>：")
            + f"ADV {adv_ratio:.1f} 倍，"
            f"RPC 从 ${rpc[0]:.3f} 到 "
            f"${rpc[-1]:.3f}"
            + (f"（{rpc_steps} 次环比里 {rpc_falls} 次回落）。" if rpc_falls else "。")
            + "这正是它与 multi-listed 那门生意的分野（Exhibit {EX_RPC}）："
            "独家挂牌的产品不需要用返点买单流，所以份额这个概念在这里根本不存在 —— "
            "公司也从不为指数期权披露市占率。"),
        "src_extra": "各期业绩 8-K EX-99.1 的经营指标表；两条都是公司披露值。",
    }, {
        "ref": "EX_CATS",
        "kind": "grouped_bars",
        "title": (f"公司自己的第二套口径：Derivatives US${cats['derivatives'][-1]:,.1f}M、"
                  f"Cash and Spot US${cats['cash_and_spot'][-1]:,.1f}M、"
                  f"Data Vantage US${cats['data_vantage'][-1]:,.1f}M"),
        "xlabels": axis([compact(q) for q in cats["quarters"]], 2),
        "groups": [
            {"name": "Derivatives", "color": "NAVY", "values": rounded(cats["derivatives"])},
            {"name": "Cash and Spot Markets", "color": "BLUE",
             "values": rounded(cats["cash_and_spot"])},
            {"name": "Data Vantage", "color": "GOLD", "values": rounded(cats["data_vantage"])},
        ],
        "bar_labels": False,
        "fmt": "f0c", "label_fmt": "f0c", "ylab": "US$M",
        "note": (
            "公司并行发布两套口径：上一张（Exhibit {EX_SEG}）按<b>分部</b>（Options / 北美股票 / 欧洲亚太 / "
            "期货 / 外汇），这张按<b>业务类别</b>。两套不可混用，但都加总到同一个净收入 —— "
            f"本季三类相加 US${cats['derivatives'][-1] + cats['cash_and_spot'][-1] + cats['data_vantage'][-1]:,.1f}M。"
            f"Data Vantage 这条从 US${cats['data_vantage'][0]:,.1f}M 走到 "
            f"US${cats['data_vantage'][-1]:,.1f}M，"
            f"占净收入的比重从 {cats['data_vantage'][0] / (cats['derivatives'][0] + cats['cash_and_spot'][0] + cats['data_vantage'][0]) * 100:.1f}% "
            f"到 {cats['data_vantage'][-1] / (cats['derivatives'][-1] + cats['cash_and_spot'][-1] + cats['data_vantage'][-1]) * 100:.1f}%，"
            "<b>这几年几乎没动</b> —— 它跟着成交量一起长，而不是独立于成交量在长。"),
        "src_extra": "各期业绩 8-K EX-99.1 的业务类别表；起点是公司开始印这张表的那一季。",
    }]

    price = cap["buyback_avg_price_usd"]
    price_words = ""
    if price[-1] is not None and price[-2] is not None:
        price_words = (f"均价从 US${price[-2]:,.2f} {'降到' if price[-1] < price[-2] else '升到'} "
                       f"US${price[-1]:,.2f}。")
    charts.append({
        "ref": "EX_CAP",
        "kind": "bar_line_dual",
        "title": (f"回购与股息：本季回购 US${cap['buyback_usd_m'][-1]:.1f}M、"
                  f"股息 US${cap['dividends_paid_usd_m'][-1]:.1f}M"
                  + (f"，回购均价 US${price[-1]:,.2f}" if price[-1] is not None else "")),
        "xlabels": axis([compact(q) for q in cap["quarters"]]),
        "bar": {"name": "当季回购金额（US$M）",
                "values": rounded(cap["buyback_usd_m"]), "color": "BLUE"},
        "line": {"name": "回购均价（US$/股，RHS）", "color": "ORANGE",
                 "values": rounded(price), "yfmt": "f0c"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M", "ylab2": "US$/股",
        "note": (
            "柱子有几季是空的，那几季公司没有回购，不是数据缺失。"
            "<b>橙线只画公司自己印出均价的那些季度</b> —— 其余季度留空而不是用金额除以股数补上，"
            "把一个自算值混进一条公司披露值的线里，读者无法分辨哪个是哪个。"
            f"本季回购 US${cap['buyback_usd_m'][-1]:.1f}M"
            + (f"，环比 {signed(pct_change(cap['buyback_usd_m'][-1], cap['buyback_usd_m'][-2]), 1)}，"
               if cap["buyback_usd_m"][-2] else "，")
            + price_words
            + f"资产负债表这一侧：调整后现金 US${cap['adjusted_cash_usd_m'][-1]:,.1f}M、"
            f"总债务 US${cap['total_debt_usd_m'][-1]:,.1f}M。"),
        "src_extra": "各期业绩 8-K EX-99.1 的资本管理段；均价为公司披露值，缺则留空。",
    })
    # The segment split sits beside the category split it is read against.
    charts.insert(2, segment_exhibit(staging))
    return charts


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    fin = staging["financials"]
    kpi = staging["kpi"]
    rpc = kpi["multi_listed_rpc_usd"][kpi["quarters"].index(staging["periods"][-1])]
    return [f"Net revenue ${fin['net_revenue'][-1]:.1f}M",
            f"Multi-listed RPC ${rpc:.3f}",
            f"调整后 OpM {fin['adj_op_margin_pct'][-1]:.1f}%"]


def release_source(staging: dict) -> dict:
    label = f"Cboe {quarter_words(staging['period_labels'][-1])}业绩新闻稿"
    found = next((item for item in staging["sources"] if item["label"].startswith(label)), None)
    if found is None:
        raise ValueError(f"series `sources` has no entry for the {label}: add this "
                         "quarter's release with the roll")
    return found


def build_payload(staging: dict) -> dict:
    period = staging["period_labels"][-1]
    latest = latest_block(
        staging,
        period=period,
        period_end=staging["period_ends"][-1],
        release_date=staging["release_dates"][-1])
    first_analysis, closure, prior = settlement_blocks(staging, period)
    kpi = stamped_block(staging, "next_kpi", period)
    context = stamped_block(staging, "quarter_context", period)
    release = release_source(staging)
    values = story_values(staging)

    # Section one: (a)(b) what the previous local analysis left, then (c) the
    # company's own guidance record.
    lead_ex, lead_tables, settle = settlement_section(staging, period, closure, prior, values)
    guide_ex, stats = settled_exhibits(staging)
    settled_ex = lead_ex + guide_ex
    prior_due = settle["due"]
    has_share = any(entry["reads"] == "ml_share" for entry in prior_due)
    highlight_ex, counts = highlight_exhibits(staging, context, prior_due)
    next_ex = (next_exhibits(staging, kpi, {"quantified": prior_due}, context, has_share)
               if kpi else [])
    routine_ex = routine_exhibits(staging)

    all_ex = number_exhibits(settled_ex + highlight_ex + next_ex + routine_ex, start=1)
    resolve_exhibit_refs(all_ex)
    a, b, c = len(settled_ex), len(highlight_ex), len(next_ex)
    settled_ex, highlight_ex = all_ex[:a], all_ex[a:a + b]
    next_ex, routine_ex = all_ex[a + b:a + b + c], all_ex[a + b + c:]

    fin = staging["financials"]
    div = divergence_long(staging)
    first_share = share_window(div)
    seg = staging["segments"]
    guide = staging["annual_guidance_history"]
    steps = counts["steps"]
    census = stats["census"]
    first_table = len(all_ex) + 1

    def verdict(low, high, actual):
        return "区间内" if low <= actual <= high else ("高于上限" if actual > high else "低于下限")

    opex = guide["adjusted_operating_expenses"]
    opex_rows = []
    for year in opex["years"]:
        block = opex["by_year"][str(year)]
        if not block["guided"]:
            continue
        first, last = block["guided"][0], block["guided"][-1]
        actual = block["actual"]
        opex_rows.append([
            f"FY{year}", str(len(block["guided"])),
            f"${first[0]:,.0f}–{first[1]:,.0f}", f"${last[0]:,.0f}–{last[1]:,.0f}",
            "未完结" if actual is None else f"${actual:,.1f}",
            "—" if actual is None else verdict(last[0], last[1], actual),
        ])

    tax = guide["adjusted_effective_tax_rate"]
    tax_rows = []
    for year in tax["years"]:
        block = tax["by_year"][str(year)]
        if not block["guided"]:
            continue
        first, last = block["guided"][0], block["guided"][-1]
        actual = block["actual"]
        tax_rows.append([
            f"FY{year}", f"{first[0]:.1f}–{first[1]:.1f}%", f"{last[0]:.1f}–{last[1]:.1f}%",
            "未完结" if actual is None else f"{actual:.1f}%",
            "—" if actual is None else verdict(last[0], last[1], actual),
        ])

    growth = staging["revenue_growth_guidance"]["by_year"]
    growth_rows = []
    for year in sorted(growth):
        for vintage in growth[year].get("total", []):
            span = ("—" if vintage["low"] is None
                    else f"{vintage['low']:.0f}–{vintage['high']:.0f}%")
            growth_rows.append([
                f"FY{year}", vintage["release"], span,
                "数字区间" if vintage["low"] is not None else "文字口径",
                re.sub(r"\s+", " ", vintage["text"]).replace("•", "").strip()[:150],
            ])

    div_rows = []
    for index, quarter in enumerate(div["quarters"]):
        verdict_step = steps["verdicts"][index]
        div_rows.append([
            f"Q{quarter[5]} {quarter[:4]}",
            f"{div['adv_k'][index]:,.0f}",
            f"${div['rpc_usd'][index]:.3f}",
            ("—" if div["share_pct"][index] is None
             else f"{div['share_pct'][index]:.1f}%"),
            f"${div['daily_revenue_usd_m'][index]:.3f}M",
            verdict_step or "—",
        ])

    seg_rows = [[f"Q{q[5]} {q[:4]}",
                 f"{seg['options'][i]:,.1f}",
                 f"{seg['north_american_equities'][i]:,.1f}",
                 f"{seg['europe_and_apac'][i]:,.1f}",
                 f"{seg['futures'][i]:,.1f}",
                 f"{seg['global_fx'][i]:,.1f}",
                 f"{seg['corporate_digital'][i]:,.1f}",
                 f"{seg['total'][i]:,.1f}"]
                for i, q in enumerate(seg["quarters"])]

    tables = [
        {"n": first_table,
         "title": "全年调整后营业费用：年初指引、当年最后一次指引与实际（US$M）",
         "headers": ["年度", "指引次数", "年初第一次", "当年最后一次", "全年实际", "对最后一次"],
         "rows": opex_rows},
        {"n": first_table + 1,
         "title": "全年调整后有效税率：指引与实际（%）",
         "headers": ["年度", "年初第一次", "当年最后一次", "全年实际", "对最后一次"],
         "rows": tax_rows},
        {"n": first_table + 2,
         "title": "有机净收入增速指引的每一版：数字区间与文字口径",
         "headers": ["年度", "发布日", "区间", "形式", "原文"],
         "rows": growth_rows},
        {"n": first_table + 3,
         "title": "Multi-listed 期权：ADV、RPC、市占与日均收入，逐季方向对照",
         "headers": ["季度", "ADV（千手）", "RPC", "市占", "日均收入 D", "与市占同向？"],
         "rows": div_rows},
        {"n": first_table + 4,
         "title": "分部净收入六行与公司印出的合计（US$M）",
         "headers": ["季度", "Options", "North American Equities", "Europe and Asia Pacific",
                     "Futures", "Global FX", "Corporate / Digital", "合计"],
         "rows": seg_rows},
    ]
    for table in lead_tables:
        tables.append({**table, "n": tables[-1]["n"] + 1})
    if kpi:
        tables.append(threshold_table(tables[-1]["n"] + 1, "下季阈值与当前值（原始单位）",
                                      kpi["quantified"], "current", "当前值"))
    tables.append(ai_capex_cycle_table(tables[-1]["n"] + 1))

    money = div["daily_revenue_usd_m"]
    share = div["share_pct"]
    money_move = pct_change(money[-1], money[-2])
    share_entry = next((e for e in prior_due if e["reads"] == "ml_share"), None)
    tail = ""
    if share_entry and share[-1] >= share_entry["threshold"] and money_move < 0:
        tail = ("上一季那份分析把阈值设在市占率上，本季它没有触发，"
                f"而同一门生意的日均收入环比少了 {abs(money_move):.1f}%。")
    elif share_entry:
        tail = ("上一季那份分析把阈值设在市占率上，本季它"
                + ("没有触发" if share[-1] >= share_entry["threshold"] else "触发了")
                + f"，同一门生意的日均收入环比 {minus_sign(signed(money_move))}。")
    years = round((len(div["quarters"]) - 1 - first_share) / 4)
    fees = staging["net_revenue_window"]["regulatory_fees_cost"]
    settled_n = cn_count(len(census["settled"]))
    partial = census["partial"]
    partial_words = "、".join(f"{GUIDE_NAMES[key]}的实际值只到 FY{year}"
                              for key, year in sorted(partial.items(), key=lambda kv: kv[1]))
    guidance_words = ("Cboe 每期业绩新闻稿都给一份全年指引并在当年逐季修订，"
                      f"但{cn_count(census['total'])}条指引里只有{settled_n}条既是数字、"
                      f"又有公司自己印出来的全年实际值一直对到 FY{census['latest']}"
                      + (f"（{partial_words}）" if partial_words else "")
                      + "。读者最想看的那条 —— 收入增速 —— 恰好两样都不占全。")
    if first_analysis:
        settled_words = (f"本站对该公司的第一份季报分析是 {period}，没有上季留下的跟踪指标可结算；"
                         "本节结算的是公司上季给出、本季到期的指引。" + guidance_words)
    else:
        unsettled = len(settle["later"]) + len(settle["not_carried"])
        parts = []
        if settle["questions"]:
            parts.append(f"第 0 节逐条判定的 {settle['questions']} 条待验证问题")
        if settle["due"]:
            parts.append(f"它第 8 节观察指标里本季到期、申报读得到的 {len(settle['due'])} 条量化阈值"
                         + (f"（第 8 节另有 {unsettled} 项本季不结，原因写在阈值总览的图注里）"
                            if unsettled else ""))
        settled_words = (f"先结清上季（{settle['set_in']} 那一份季报分析）留下的："
                         + "，以及".join(parts)
                         + "；再结算公司自己给出、已经到期的全年指引。" + guidance_words)
    tenths = cn_count(round(steps["opposite"] / steps["steps"] * 10))
    articles = [
        '<article><span>记录</span>'
        + (f'<b>份额与钱，{cn_count(years)}年里有{tenths}成的季度走反方向</b>'
           if steps["opposite"] > steps["same"] else
           f'<b>份额与钱，{cn_count(years)}年里走反方向的季度占{tenths}成</b>')
        + f'<p>{steps["steps"]} 次环比里 {steps["opposite"]} 次相反、{steps["same"]} 次同向。'
        f'市占 {share[first_share]:.1f}% → {share[-1]:.1f}%，'
        # The money's end point here used to be 2016Q1's, beside a share line
        # that starts in 2019Q2; both ends now come from the share window.
        f'日均收入 US${money[first_share]:.3f}M → '
        f'US${money[-1]:.3f}M。</p></article>',
        '<article><span>结不清</span><b>最想结清的那条指引，两个时代各有各的原因</b>'
        f'<p>{stats["numeric_years"][0]}–{stats["numeric_years"][-1]} 有数字但指引的是'
        '「有机」增速，本页查过的 2 月新闻稿与年报里都没有它的全年实际；'
        f'{stats["word_years"][0]} 起指引变成一句话。能结清的只有费用与税率{settled_n}条。</p></article>',
        '<article><span>本季</span><b>过路项开关式跳动，只剥一边就会读错</b>'
        f'<p>监管规费成本本季 {usd_zero(fees[-1])}、'
        f'上一季 {usd_zero(fees[-2])}。它同时进收入与成本，对净收入近乎中性。</p></article>',
    ]

    return {
        "schema_version": "quarterly-dashboard/cboe-v1",
        "page": {"slug": "cboe", "language": "zh-CN"},
        "company": {
            "ticker": "CBOE",
            "name": "Cboe Global Markets, Inc.",
            "group": "exchanges",
            "accounting_standard": "US GAAP",
        },
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · CBOE",
        "title": f"Cboe Global Markets, Inc. (CBOE)：{period} 季报仪表盘",
        "subtitle": (
            f"截至 {latest['period_end']} · 发布 {latest['release_date']} · US GAAP · "
            f"{AUDIT_WORDS[latest['audit_status']]} · "
            "自然年财年，季度标注无需换算"
        ),
        "headline": plain_text(
            f"净收入 US${fin['net_revenue'][-1]:,.1f}M、同比 "
            f"{signed(pct_change(fin['net_revenue'][-1], fin['net_revenue'][-5]))}，"
            f"调整后营业利润率 {fin['adj_op_margin_pct'][-1]:.1f}%。"
            "但本页的对象不是这个季度 —— Cboe 每季在同一张表里印出市占率和每合约收入，"
            "而两者相乘才是这门生意每天挣到的钱。"
            f"在公司同时披露这三个数的 "
            f"{sum(1 for value in share if value is not None)} 个季度里，"
            f"市占与日均收入的 {steps['steps']} 次环比有 {steps['opposite']} 次方向相反；"
            f"那段窗口里市占{'掉了' if share[-1] < share[first_share] else '涨了'} "
            f"{abs(share[-1] - share[first_share]):.1f} 个百分点，"
            f"日均收入{'却涨了' if money[-1] > money[first_share] else '跌了'} "
            f"{abs(pct_change(money[-1], money[first_share])):.0f}%。"
            + tail
        ),
        "brief": (
            f'<h4>本季{cn_count(len(articles))}条主线</h4><div class="takeaway-grid">'
            + "".join(articles)
            + '</div>'
        ),
        "source": (
            f'Source: <a href="{release["url"]}" rel="noopener">Cboe {period} '
            f'业绩新闻稿（8-K EX-99.1）</a>与截至 {latest["period_end"]} 的 '
            f'{"10-K" if period.startswith("Q4") else "10-Q"}。'
        ),
        "source_url": release["url"],
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {"id": "settled", "title": "一、上季跟踪指标兑现了吗",
             "description": plain_text(settled_words),
             "exhibits": settled_ex},
            {"id": "quarter_highlights", "title": "二、本季重点",
             "description": plain_text(
                 "本页的核心在这一节：市占率和每合约收入印在同一张表里，"
                 "而它们相乘才是这门生意每天挣到的钱。"
                 "三门生意、三条不同的窗口，形状是同一个。"
                 "最后一张是读这张表之前必须先看懂的一件事："
                 "毛收入与净收入之间那道过路项的楔子。"),
             "exhibits": highlight_ex},
            {"id": "next_quarter", "title": "三、下季要跟踪什么",
             "description": plain_text(
                 (kpi or {}).get("description",
                                 "当前值离下季阈值还有多远，统一用「距阈值余量」口径。")),
             "exhibits": next_ex},
            {"id": "routine", "title": "四、长期常规跟踪",
             "description": plain_text(
                 f"CBOE 专属的常规序列：{cn_count(round(len(staging['long']['quarters']) / 4))}年的调整后营业利润率、"
                 f"本页最长的一条线（指数期权的量与价，{cn_count(len(staging['kpi_long']['quarters']))}个季度）、"
                 "公司的两套收入口径（分部表连同那条负的第六行，以及业务类别），"
                 "以及回购与它实际付出的价格。"),
             "exhibits": routine_ex},
        ],
        "tables": tables,
        "notes": [plain_text(p) for p in notes_for(staging, context, census)],
        "footer": "Quarterly Results · 公司披露值与透明自算 · 仅供研究",
    }


def notes_for(staging: dict, context: dict | None, census: dict) -> list[str]:
    seg = staging["segments"]
    tail = len(seg["quarters"])
    five = [sum(seg[key][i] for key in ("options", "north_american_equities",
                                        "europe_and_apac", "futures", "global_fx"))
            for i in range(tail)]
    five_off = sum(1 for f, t in zip(five, seg["total"]) if abs(f - t) > 0.05)
    six_ok = sum(1 for i, (f, t) in enumerate(zip(five, seg["total"]))
                 if abs(f + seg["corporate_digital"][i] - t) <= 0.05)
    fees = staging["net_revenue_window"]["regulatory_fees_cost"]
    opex = staging["annual_guidance_history"]["adjusted_operating_expenses"]
    kpi, kpil = staging["kpi"], staging["kpi_long"]
    gap = kpil["quarters"].index(kpi["quarters"][0])
    return [
        "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，"
        "每张图下一到两句解释；支撑表格收在核对抽屉里。",
        "Cboe 为自然年财年（12 月 31 日结束），本页季度标注与公司口径一致，无需换算。",
        "本页最需要说明的一条：公司在每份业绩新闻稿的经营指标表里，"
        "把市占率、平均日成交量与每合约收入并排印出，而三者之中只有后两者的乘积是收入。"
        "把阈值设在市占率上，在 multi-listed 期权这类同质化市场里会失效，"
        "因为那里量和价可以互换 —— 多给返点就能买到份额。"
        "本页第二节用公司自己的披露值把这件事画出来，第三节据此改写了跟踪指标。",
        "日均收入是本页最重要的自算值：multi-listed 为 ADV（千手）乘 RPC（US$/手）再除以一千，"
        "得到 US$M/日；场外大宗为 ADV（百万股）乘每百股 net capture 再换算，得到 US$千/日。"
        "两个乘数都是公司披露值，乘法本身没有任何假设，标 D。",
        # 「分歧本身记录在下面的来源说明里」: no such record exists on the page
        # or in the series file, so the promise is dropped rather than kept.
        "经营指标表每份新闻稿印五个季度，相邻两份重叠四季。本页把它们拼成长序列，"
        "并用重叠季逐项交叉核对；重叠处出现分歧的，一律采用较晚那份的印刷值。",
        "全年调整后营业费用的记录跨着一次收购：2017 年 2 月那版指引是 CBOE Holdings 单体口径、"
        "写明不含拟收购的 Bats，同年 5 月起改为含 Bats 的合并口径。"
        f"本页在图上画了断点，并且 FY2017 的实际值取合并口径的 US${opex['by_year']['2017']['actual']:.1f}M —— "
        f"同一份新闻稿里另有一个 US${FY2017_AS_REPORTED:.1f}M 的如实合并数，"
        "拿它去对合并口径的指引会凭空造出一次巨大的超预期。",
        "有机净收入增速的指引不进任何一张兑现图。2022–2024 年公司给的是数字区间，"
        f"但它指引的是「有机」增速，而 {ORGANIC_SEARCHED} 都没有印出有机增速的全年实际值，没有可对照的对象；"
        "2025 年起指引本身变成文字（「mid single digit」「mid to high teens」），"
        "本站不把文字换算成区间端点。两个时代的原因不同，结果一样：结不清。",
        "分部表有第六行，而且在两个时代是两样东西：2017–2022 年是 Corporate，"
        "2022Q4–2024Q4 是 Digital（2022 年 5 月收购、随后关掉的 Cboe Digital，净收入为负），"
        f"2025Q1 起消失。只取前五行会在 {tail} 个季度里的 {five_off} 个对不上公司印出的合计，"
        "而差额还会中途换号；"
        + (f"六行相加则 {tail} 季全部对平。" if six_ok == tail else f"六行相加则 {tail} 季里 {six_ok} 季对平。"),
        "分部序列从 2017Q2 起画，不回补 2017Q1：Bats 自 2017-02-28 才并表，"
        "那一季的北美股票、欧洲与外汇三个分部是一个月，与前后各季的三个月不可比。"
        "2013–2016 年公司只报单一业务，没有分部表，因此这段窗口在本页根本不存在。",
        # 「指数期权与期货的量价序列」: the long record on this page is index
        # options only; futures is not a series here at all.
        f"指数期权的量价序列回溯到 {kpil['quarters'][0]}，比其余经营指标长{cn_count(gap)}个季度："
        "Bats 既没有指数期权也没有期货，这两行在收购前后指的是同一件事，"
        "并且在 2016 年的四个重叠季度里，新旧两张表印出的 ADV 与 RPC 完全相同。"
        "其余各行不这样回补，因为收购前的口径是 CBOE 单体，与合并口径不是一个数。",
        "监管规费（Section 31 等）是代收代付：公司向会员收取再上缴 SEC，"
        "同一笔金额同时计入收入与收入成本，对净收入近乎中性。"
        f"本季成本端 {usd_zero(fees[-1])}、上一季 {usd_zero(fees[-2])}，费率由 SEC 决定。"
        "只把成本端剥掉而不同时剥掉收入端，会把一个中性项误读成一次巨大的收入注水。",
        "回购均价只画公司自己印出这个数的季度，其余留空。"
        "用当季回购金额除以股数可以补出一个数，但那是自算值，"
        "混进一条公司披露值的线里读者无法分辨；本页宁可留空。",
        "本页不发布评级、目标价、估值与任何券商共识，也不发布公司未在申报文件中给出的数字。"
        + (context or {}).get("call_only_note", ""),
    ]


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "cboe.js"), payload, "cboe")
    shell_dir = ROOT / "cboe"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("CBOE", "cboe"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(
        f"CBOE page: {charts} charts in {len(payload['sections'])} sections "
        f"+ {len(payload['tables'])} audit tables"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
