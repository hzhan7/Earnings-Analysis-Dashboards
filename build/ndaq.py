"""Nasdaq, Inc. quarterly dashboard.

Nasdaq guides **two numbers and no others**: full-year non-GAAP operating expense
and the full-year non-GAAP effective tax rate. It has never published revenue
guidance, EPS guidance or margin guidance, and it says so in a footnote to the
guidance section of every release. So the object this page's first section
settles is not a forecast of the business -- it is the company's own budget.

That changes what a hit rate means. Against the year's LAST range the expense
record has been one-sided (inside or above, never below) and the tax-rate
record one-sided the other way (inside or below, never above); against the
year's FIRST (January) range the expense record is two-sided. Most of what
looks like discipline in the October record is the ten months already banked
when it is published. Three of the "above" verdicts (FY2020, FY2022, FY2023)
and two of the "below vs January" ones (FY2018, FY2019) have an explanation the
page carries rather than smooths.

**Rolling a quarter edits `series/ndaq.json` and nothing else** (CLAUDE.md §9).
Every figure, period and count in the prose is computed from the series, and a
sentence that states a record, a "first", an "only", an "always" or a direction
is printed only while the series still says so. What belongs to one quarter --
the thresholds (`next_kpi`), what the release itself printed beside the numbers
(`quarter_context`: the adjusted Index growth and the one-off behind it, the
printed ARR growth rates, the trailing-twelve-month AUM split, the note on the
release's own format) and the year-ago column the release reprinted
(`year_ago_reprinted`) -- carries a ``period`` stamp and is read through
`board.stamped_block`. Year-on-year rates divide by the year-ago figure the
company reprinted in this quarter's release, not by the one it first printed:
Solovis was moved out of Capital Access into Other in October 2025 and the
Market Services gross and rebate lines were regrossed, so the first print sits
on a different basis. `_checks` is a separate reading of the quarter's release
that the tests hold the page to; this builder never reads it.

Fixed history that does not move with a roll stays in code: the Adenza close
(2023-11-01), the 2021-01-12 8-K, the FY2018 / FY2019 divestitures behind the
January misses, FY2017's ASC 606 restatement (1,280 → 1,271), the 2022 split,
the 2017 ASC 606 step in net revenue, and the segment and ARR splice traps.

Published numbers are company-reported or transparent arithmetic. No market
expectation is published on this page: no dated, checkable public source for one
was available, and inventing one is worse than omitting the comparison.
"""

from __future__ import annotations

import datetime
import json
import math
import statistics
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
    fill_story,
    headroom,
    headroom_exhibit,
    latest_block,
    number_exhibits,
    stamped_block,
    threshold_exhibit,
    threshold_table,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "ndaq.json"
DATA_DIR = ROOT / "data"

# One tick per year keeps the long axes readable.
LONG_STEP = 4

AUDIT_WORDS = {"unaudited": "未审计", "audited": "已审计"}

# The "above the final range" verdicts that have a story, in the order the page
# tells them. Each is fixed history; a year is only told while the data still
# puts it above its final range.
ABOVE_EXPLAINED = (2022, 2023, 2020)
# The January misses that were divestitures, not thrift (fixed history).
BELOW_FIRST_EXPLAINED = (2018, 2019)
# FY2017's actual as first reported and after the ASC 606 restatement.
FY2017_RESTATED = 1271
# The 2021-01-12 8-K: FY2020 expenses would clear the prior range by about $45M.
FY2020_PREANNOUNCED_OVER = 45
FY2020_PREANNOUNCED_ON = "2021-01-12"
# The years whose 10-K tax rate was recomputed from the releases' pre-tax income
# and tax adjustments (all within 0.04pp). A year outside this list was not.
TAX_RECOMPUTED_YEARS = tuple(range(2019, 2026))
# Adenza closed on 2023-11-01; the FinTech sub-lines step there.
ADENZA_QUARTER = "2023Q4"
# The quarter the site's first NDAQ analysis covers (the 2026-07-23 release; the
# owner's vault holds no earlier NDAQ report, and that report's section 0 says so).
# Fixed history: only this quarter may say there is nothing from last quarter to
# settle. Every later quarter settles what the report before it set.
FIRST_REPORT_PERIOD = "Q2 2026"


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100.0


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def rounded(values, digits: int = 6):
    return [None if v is None else round(v, digits) for v in values]


def mid(low: float, high: float) -> float:
    return (low + high) / 2


def quarter_words(period: str) -> str:
    """``'Q2 2026'`` → ``'2026 年第二季度'``, the way the source labels name a quarter."""
    quarter, year = period.split()
    return f"{year} 年第{cn_ordinal(int(quarter[1]))}季度"


def next_period(period: str) -> str:
    quarter, year = period.split()
    number = int(quarter[1])
    return f"Q1 {int(year) + 1}" if number == 4 else f"Q{number + 1} {year}"


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


def finished_years(item: dict) -> list[int]:
    return [year for year in item["years"] if item["by_year"][str(year)]["actual"] is not None]


def open_years(item: dict) -> list[int]:
    return [year for year in item["years"] if item["by_year"][str(year)]["actual"] is None]


def vintages(item: dict, year: int) -> tuple[list, list]:
    block = item["by_year"][str(year)]
    guided = [g for g in block["guided"] if g]
    return guided[0], guided[-1]


def verdict_of(low: float, high: float, actual: float) -> str:
    return "inside" if low <= actual <= high else ("above" if actual > high else "below")


def tally(item: dict, which: int, overrides: dict | None = None) -> dict[str, int]:
    counts = {"inside": 0, "above": 0, "below": 0}
    for year in finished_years(item):
        low, high, _ = vintages(item, year)[which]
        actual = (overrides or {}).get(year, item["by_year"][str(year)]["actual"])
        counts[verdict_of(low, high, actual)] += 1
    return counts


def years_where(item: dict, which: int, verdict: str) -> list[int]:
    return [year for year in finished_years(item)
            if verdict_of(*vintages(item, year)[which][:2],
                          item["by_year"][str(year)]["actual"]) == verdict]


def fy_list(years: list[int]) -> str:
    return "、".join(f"FY{year}" for year in years)


def times_word(ratio: float) -> str:
    """How many times larger, in the strict sense of 「涨了 N 倍」 (ratio − 1)."""
    increase = ratio - 1
    whole = round(increase)
    if increase < 1:
        return f"{cn_count(round(increase * 10))}成"
    if abs(increase - whole) < 0.01:
        return f"{cn_count(whole)}倍"
    return f"近{cn_count(whole)}倍" if increase < whole else f"{cn_count(whole)}倍多"


def zero_run_before_last(values: list[float]) -> int:
    """How many quarters immediately before the last one were exactly zero."""
    run = 0
    for value in reversed(values[:-1]):
        if value != 0:
            break
        run += 1
    return run


def release_source(staging: dict) -> dict:
    label = f"Nasdaq {quarter_words(staging['period_labels'][-1])}业绩新闻稿"
    found = next((item for item in staging["sources"] if item["label"].startswith(label)), None)
    if found is None:
        raise ValueError(f"series `sources` has no entry for the {label}: add this "
                         "quarter's release with the roll")
    return found


class YearAgo:
    """The year-ago figure a year-on-year rate divides by.

    It is the one the company reprinted in this quarter's release when the
    series file carries that column (`year_ago_reprinted`), and the one it first
    printed otherwise. The two differ when the company reclassifies: the Q2
    2026 release reprints Q2 2025 Capital Access at 520 against a first print
    of 527 (Solovis moved to Other), and Market Services gross at 1,101 against
    1,090 (rebates regrossed by the same 11).
    """

    def __init__(self, reprinted: dict | None):
        self.values = (reprinted or {}).get("usd_m", {})

    def of(self, key: str, series: list[float]) -> float:
        return self.values.get(key, series[-5])

    def growth(self, key: str, series: list[float]) -> float:
        return pct_change(series[-1], self.of(key, series))


def annual_deviation(ref: str, metric: str, years: list[str], first: list[tuple],
                     last: list[tuple], actual: list[float], *, unit: str,
                     src_extra: str, extra_note: str = "") -> dict:
    """Distance from each of the two guided midpoints, for an ANNUAL record.

    ``board.midpoint_deviation`` hard-codes 「季」 into every sentence it builds,
    so an annual series renders as "11 季里 8 季为正". This is its annual twin and
    it draws both vintages side by side, because the whole finding is that the
    two answers differ: the January range is a forecast and the October one is
    largely bookkeeping on a year three-quarters banked.
    """
    dev_first = [(a / mid(lo, hi) - 1) * 100 for (lo, hi, _), a in zip(first, actual)]
    dev_last = [(a / mid(lo, hi) - 1) * 100 for (lo, hi, _), a in zip(last, actual)]
    mean_first = statistics.fmean(abs(v) for v in dev_first)
    mean_last = statistics.fmean(abs(v) for v in dev_last)
    biggest = max(dev_first, key=abs)
    # "The October range always lands closer" was written as a rule; FY2022 and
    # FY2023 are the two years it is not true, so the sentence counts instead.
    exceptions = [years[i] for i, (f, l) in enumerate(zip(dev_first, dev_last)) if abs(l) >= abs(f)]
    if not exceptions:
        closer = "深蓝是年末那次，年末那次总是更贴近实际，因为它发布时全年已过去约十个月。"
    else:
        closer = (f"深蓝是年末那次，{cn_count(len(years))}年里有{cn_count(len(years) - len(exceptions))}年"
                  f"是年末那次更贴近实际（{'、'.join(exceptions)} 相反），"
                  "因为它发布时全年已过去约十个月。")
    return {
        "ref": ref,
        "kind": "grouped_bars",
        "title": (f"{metric}相对指引中值的偏离：对年初那次平均绝对偏离 {mean_first:.2f}%，"
                  f"对年末那次 {mean_last:.2f}%"),
        "xlabels": list(years),
        "groups": [
            {"name": "vs 年初第一次指引中值", "color": "GOLD", "values": rounded(dev_first)},
            {"name": "vs 当年最后一次指引中值", "color": "NAVY", "values": rounded(dev_last)},
        ],
        "bar_labels": True,
        "fmt": "pct1",
        "label_fmt": "pct1",
        "ylab": f"% vs 指引中值（{unit}）",
        "note": ("正值 = 实际值高于指引区间的中值。"
                 "<b>两组柱子的高度差就是这一年里指引被修订的幅度</b>：金色是年初那次、"
                 + closer
                 + f"金色柱里最大的一次是 {years[dev_first.index(biggest)]} 的 {biggest:+.2f}%。"
                 + extra_note),
        "src_extra": src_extra,
    }


def guidance_section(staging: dict) -> tuple[list[dict], list[dict]]:
    """The annual guidance record: expense and tax rate, two vintages each."""
    hist = staging["annual_guidance_history"]
    charts: list[dict] = []
    tables: list[dict] = []

    opex = hist["operating_expense"]
    years = finished_years(opex)
    labels = [f"FY{y}" for y in years]
    first = [vintages(opex, y)[0] for y in years]
    last = [vintages(opex, y)[1] for y in years]
    actual = [opex["by_year"][str(y)]["actual"] for y in years]
    t_last, t_first = tally(opex, 1), tally(opex, 0)
    by_year = dict(zip(years, zip(first, last, actual)))

    if t_last["below"] == 0:
        last_lead = (f"<b>{len(years)} 个完整年度里没有一年低于下限</b> —— 落在区间内 "
                     f"{t_last['inside']} 次、高于上限 {t_last['above']} 次、低于下限 "
                     f"{t_last['below']} 次。费用指引的下限从来没有约束过这家公司："
                     "它要么花在区间内，要么花得更多，但从未比自己说的少花。")
    else:
        last_lead = (f"{len(years)} 个完整年度里落在区间内 {t_last['inside']} 次、高于上限 "
                     f"{t_last['above']} 次、低于下限 {t_last['below']} 次"
                     f"（{fy_list(years_where(opex, 1, 'below'))}）。")
    above_last = years_where(opex, 1, "above")
    stories = []
    for year in ABOVE_EXPLAINED:
        if year not in above_last:
            continue
        (_f, (low, high, date), value) = by_year[year]
        if year == 2022:
            stories.append(f"FY2022 只超出上限 US${value - high:,.0f}M"
                           + ("，落在百万美元级四舍五入之内" if value - high <= 1 else ""))
        elif year == 2023:
            stories.append(f"FY2023 的最后一次指引发布于 {date}，而 Adenza 收购在两周后的 11 月 1 日才交割，"
                           f"实际值含两个月 Adenza 费用，超出的 US${value - high:,.0f}M 与之量级相当")
        elif year == 2020:
            gap = (datetime.date.fromisoformat(FY2020_PREANNOUNCED_ON)
                   - datetime.date(year, 12, 31)).days
            stories.append(f"FY2020 的超支由公司在 {FY2020_PREANNOUNCED_ON} 一份单独的 8-K 里提前披露，"
                           f"而那已是被指引年度结束后第 {gap} 天")
    told = ""
    if stories:
        told = (f"{cn_count(len(above_last))}次「高于上限」里有{cn_count(len(stories))}次另有说法："
                + "；".join(stories) + "。")
    charts.append(delivery_band(
        "EX_OPEX_LAST", "全年非 GAAP 营业费用", labels,
        [g[0] for g in last], [g[1] for g in last], actual,
        fmt="f0c", ylab="US$M", unit="US$M",
        venue="业绩新闻稿", timing="该年<b>当年内最后一次</b>", period_word="年",
        extra_note=(
            last_lead
            + "这条记录的分量要打折：这里画的是<b>当年最后一次</b>指引，通常发布于 10 月下旬，"
            "此时全年已过去约十个月，更接近记账而不是预测；"
            + ("同一指标对<b>年初第一次</b>指引的结果完全不同，见 Exhibit {EX_OPEX_FIRST}。"
               if t_first != t_last else
               "同一指标对<b>年初第一次</b>指引的结果见 Exhibit {EX_OPEX_FIRST}。")
            + told),
        src_extra=("指引取自各年业绩 8-K EX-99.1 的费用指引段落；"
                   "实际值取自次年 Q4 业绩新闻稿非 GAAP 营业费用调节表的 Year Ended 列。"),
    ))

    two_sided = t_first["above"] > 0 and t_first["below"] > 0
    below_first = years_where(opex, 0, "below")
    shrinks = [year for year in BELOW_FIRST_EXPLAINED if year in below_first]
    shrink_words = ""
    if shrinks:
        parts = []
        if 2018 in shrinks:
            guided_2018 = [g for g in opex["by_year"]["2018"]["guided"] if g]
            cut = guided_2018[0][0] - guided_2018[1][0]
            parts.append("FY2018 的年初指引明确包含整年约 US$170M 的 Public Relations Solutions 与 "
                         f"Digital Media Services 费用，该业务当年 4 月出售，指引随即下调 US${cut:,.0f}M")
        if 2019 in shrinks:
            parts.append("FY2019 的年初指引下调则是因为 BWise 出售")
        shrink_words = (f"{cn_count(len(below_first))}次「低于下限」里有{cn_count(len(shrinks))}次"
                        "不是省钱而是缩表：" + "；".join(parts) + "。把它们读成「指引保守」是错的。")
    pairs = [y for y in years if len([g for g in opex["by_year"][str(y)]["guided"] if g]) == 2]
    pair_words = ""
    if pairs == [2015, 2016]:
        # Both years' guidance went out in January and April only: the July and
        # October releases carried none. The two copies of this sentence used to
        # disagree (「第二、三季度」 here, 「第三、四季度」 in the notes); the
        # release dates in the series decide it.
        pair_words = ("FY2015 与 FY2016 每年只有两次指引（公司在这两年的第三、四季度没有发布费用指引），"
                      "所以这两年的「第一次」与「最后一次」相隔只有一个季度。")
    charts.append(delivery_band(
        "EX_OPEX_FIRST", "全年非 GAAP 营业费用（对年初第一次指引）", labels,
        [g[0] for g in first], [g[1] for g in first], actual,
        fmt="f0c", ylab="US$M", unit="US$M",
        venue="业绩新闻稿", timing="该年<b>年初第一次</b>", period_word="年",
        extra_note=(
            (f"<b>换成年初那次指引，同样 {len(years)} 年就成了双向的</b>：区间内 "
             if two_sided else f"换成年初那次指引，同样 {len(years)} 年：区间内 ")
            + f"{t_first['inside']} 次、高于上限 {t_first['above']} 次、低于下限 "
            f"{t_first['below']} 次。这才是十二个月视角下的记录。"
            + shrink_words + pair_words),
        src_extra=("年初第一次指引取自各年 1 月的业绩 8-K EX-99.1；"
                   "FY2015 与 FY2016 的最后一次分别为当年 4 月发布。"),
    ))
    width_first = statistics.fmean(g[1] - g[0] for g in first)
    width_last = statistics.fmean(g[1] - g[0] for g in last)
    dev_first = statistics.fmean(abs(a / mid(g[0], g[1]) - 1) for g, a in zip(first, actual))
    dev_last = statistics.fmean(abs(a / mid(g[0], g[1]) - 1) for g, a in zip(last, actual))
    charts.append(annual_deviation(
        "EX_OPEX_DEV", "全年非 GAAP 营业费用", labels, first, last, actual,
        unit="US$M",
        src_extra="偏离 = 实际值 ÷ 指引中值 − 1；两组柱分别取该年第一次与最后一次指引区间的中点。",
        extra_note=(
            "同一段记录还可以从区间宽度上读："
            f"年初那次的平均宽度是 US${width_first:.0f}M，"
            f"年末那次是 US${width_last:.0f}M。"
            + ("指引在一年里既向实际值靠拢，也把自己收窄，两件事一起发生。"
               if width_last < width_first and dev_last < dev_first else "")),
    ))

    tax = hist["tax_rate"]
    tax_years = finished_years(tax)
    tax_labels = [f"FY{y}" for y in tax_years]
    tax_first = [vintages(tax, y)[0] for y in tax_years]
    tax_last = [vintages(tax, y)[1] for y in tax_years]
    tax_actual = [tax["by_year"][str(y)]["actual"] for y in tax_years]
    tt = tally(tax, 1)
    floor_groups: list[tuple[list[int], float, float]] = []
    for year, (lo, _hi, _d), value in zip(tax_years, tax_last, tax_actual):
        if abs(value - lo) < 0.05:
            if floor_groups and floor_groups[-1][1] == value:
                floor_groups[-1][0].append(year)
            else:
                floor_groups.append(([year], value, lo))
    on_floor = sum(len(group[0]) for group in floor_groups)
    tax_low_sided = tt["above"] == 0 and tt["below"] > 0
    opex_high_sided = t_last["below"] == 0 and t_last["above"] > 0
    if tax_low_sided and opex_high_sided:
        tax_lead = "<b>这是另一条单边记录，而且方向相反</b>："
    elif tax_low_sided or (tt["below"] == 0 and tt["above"] > 0):
        tax_lead = "<b>这是一条单边记录</b>："
    else:
        tax_lead = ""
    floor_words = ""
    if floor_groups:
        spelled = []
        for number, (group, value, lo) in enumerate(floor_groups):
            spelled.append(f"{fy_list(group)} 报 {value:.1f}%，"
                           + ("指引下限" if number == 0 else "下限") + f"就是 {lo:.1f}%")
        floor_words = (f"而且 {on_floor} 次「区间内」其实正落在区间的<b>下沿</b>上（"
                       + "；".join(spelled) + "），所以说「落在区间内」比说「贴着下限」要宽容得多。")
    first_tax_year = tax["years"][0]
    first_tax_block = tax["by_year"][str(first_tax_year)]
    first_tax_releases = len([g for g in first_tax_block["guided"] if g])
    charts.append(delivery_band(
        "EX_TAX", "全年非 GAAP 有效税率", tax_labels,
        [g[0] for g in tax_last], [g[1] for g in tax_last], tax_actual,
        fmt="pct1", ylab="%", unit="%",
        venue="业绩新闻稿", timing="该年<b>当年内最后一次</b>", period_word="年",
        extra_note=(
            tax_lead
            + f"{len(tax_years)} 个完整年度里区间内 "
            f"{tt['inside']} 次、低于下限 {tt['below']} 次、"
            f"高于上限 {tt['above']} 次。"
            + ("税率从未高于公司自己说的上限。" if tt["above"] == 0 else "")
            + floor_words
            + "税率指引自 2018 年 1 月那期新闻稿才开始发布，"
            f"FY{first_tax_year} 全年只发布过{cn_count(first_tax_releases)}次、"
            f"且当年没有可用的实际值（公司披露非 GAAP 有效税率是从 FY{tax_years[0]} 起），"
            f"因此本图从 FY{tax_years[0]} 起算。"),
        src_extra=("指引取自各年业绩 8-K EX-99.1；实际值为公司在 10-K 「NON-GAAP FINANCIAL MEASURES」"
                   "一节印出的 Non-GAAP effective tax rate，业绩新闻稿从不印这个数。"),
    ))

    tables.append({
        "title": "全年非 GAAP 营业费用：年初指引、年末指引与实际（US$M）",
        "headers": ["年度", "指引次数", "年初第一次", "当年最后一次", "全年实际",
                    "对年初", "对最后一次"],
        "rows": [[f"FY{y}", str(len([g for g in opex['by_year'][str(y)]['guided'] if g])),
                  f"${f[0]:,.0f}–{f[1]:,.0f}",
                  f"${l[0]:,.0f}–{l[1]:,.0f}",
                  f"${a:,.0f}",
                  verdict(f[0], f[1], a), verdict(l[0], l[1], a)]
                 for y, f, l, a in zip(years, first, last, actual)]
        + [[f"FY{year}", str(len(guided)),
            f"${guided[0][0]:,.0f}–{guided[0][1]:,.0f}",
            f"${guided[-1][0]:,.0f}–{guided[-1][1]:,.0f}",
            "未完结", "—", "—"]
           for year in open_years(opex)
           for guided in [[g for g in opex["by_year"][str(year)]["guided"] if g]]],
    })
    tables.append({
        "title": "全年非 GAAP 有效税率：指引与实际（%）",
        "headers": ["年度", "年初第一次", "当年最后一次", "全年实际", "对最后一次"],
        "rows": [[f"FY{y}", f"{f[0]:.1f}–{f[1]:.1f}%", f"{l[0]:.1f}–{l[1]:.1f}%",
                  f"{a:.1f}%", verdict(l[0], l[1], a)]
                 for y, f, l, a in zip(tax_years, tax_first, tax_last, tax_actual)],
    })
    return charts, tables


def verdict(low, high, actual):
    return {"inside": "区间内", "above": "高于上限", "below": "低于下限"}[verdict_of(low, high, actual)]


def spent_in_year(staging: dict, year: int) -> tuple[float, int]:
    """Non-GAAP operating expense already spent in ``year``, US$M, and over how many quarters."""
    spent = [v for p, v in zip(staging["periods"], staging["financials"]["nongaap_opex"])
             if p.startswith(str(year))]
    return sum(spent), len(spent)


_SPENT_WORDS = {1: ("第一季度", "后三季"), 2: ("上半年", "下半年"), 3: ("前三季", "第四季度")}


def open_year_chart(staging: dict, opex: dict, finished: list[int]) -> dict:
    """The year still running: each release's range, and what is left of it.

    It sits in the quarter's section, not in the settled one: a year that has not
    ended settles nothing, and what the latest release did to the range -- raise
    it, cut it, leave it -- is news about this quarter. So the title leads with
    that last move, read off the vintages, and names the release that made it.
    """
    open_year = max(opex["years"])
    guided = [g for g in opex["by_year"][str(open_year)]["guided"] if g]
    moves = [(g[2], mid(g[0], g[1])) for g in guided]
    count = cn_count(len(moves))
    widths = [g[1] - g[0] for g in guided]
    rising = all(b[1] > a[1] for a, b in zip(moves, moves[1:]))
    falling = all(b[1] < a[1] for a, b in zip(moves, moves[1:]))

    if len(moves) == 1:
        title = (f"FY{open_year} 费用指引的{count}次发布：年初区间 US${guided[0][0]:,.0f}–{guided[0][1]:,.0f}M，"
                 f"中值 US${moves[0][1]:,.0f}M")
    else:
        step = moves[-1][1] - moves[-2][1]
        who = ("本季" if moves[-1][0] == staging["latest"]["release_date"]
               else f"{moves[-1][0]} 那次")
        if step > 0:
            change = (f"{who}把中值从 US${moves[-2][1]:,.0f}M 抬到 US${moves[-1][1]:,.0f}M"
                      f"（+US${step:,.0f}M）")
        elif step < 0:
            change = (f"{who}把中值从 US${moves[-2][1]:,.0f}M 降到 US${moves[-1][1]:,.0f}M"
                      f"（−US${-step:,.0f}M）")
        else:
            change = f"{who}维持中值 US${moves[-1][1]:,.0f}M"
        title = (f"FY{open_year} 费用指引的{count}次发布：{change}，"
                 f"年初那次的中值是 US${moves[0][1]:,.0f}M")

    only_open = len(open_years(opex)) == 1
    lead = f"FY{open_year} 是唯一还没结清的年度" if only_open else f"FY{open_year} 还没结清"
    if len(moves) == 1:
        lead += "，目前只有年初这一次发布。"
    elif rising:
        lead += f"，{count}次发布都在往上走。"
    elif falling:
        lead += f"，{count}次发布都在往下走。"
    else:
        lead += f"，{count}次发布的中值有升有降。"
    note = f"<b>{lead}</b>"

    if len(moves) > 1:
        up_and_narrow = moves[-1][1] > moves[0][1] and widths[-1] < widths[0]
        width_verb = "收到" if widths[-1] < widths[0] else ("放宽到" if widths[-1] > widths[0] else "保持在")
        note += (f"区间宽度同时从 US${widths[0]:,.0f}M {width_verb} US${widths[-1]:,.0f}M")
        if up_and_narrow:
            # "The same shape as every one of the previous eleven years" was
            # written as a rule; the midpoint fell across the year in six of them.
            same = [year for year in finished
                    if mid(*vintages(opex, year)[1][:2]) > mid(*vintages(opex, year)[0][:2])
                    and (vintages(opex, year)[1][1] - vintages(opex, year)[1][0])
                    < (vintages(opex, year)[0][1] - vintages(opex, year)[0][0])]
            if len(same) == len(finished):
                note += (f" —— 抬中值与收区间同时发生，和前{cn_count(len(finished))}年每一年的形状一样。")
            else:
                note += (f" —— 抬中值与收区间同时发生；前{cn_count(len(finished))}个完整年度里，"
                         f"同样既抬中值又收区间的只有 {fy_list(same)} {cn_count(len(same))}年。")
        else:
            note += "。"

    spent, quarters = spent_in_year(staging, open_year)
    if quarters in _SPENT_WORDS:
        done_words, left_words = _SPENT_WORDS[quarters]
        left = guided[-1][1] - spent
        note += (f"{done_words}已发生的非 GAAP 营业费用是 US${spent:,.0f}M，"
                 f"按最新指引上限倒推，{left_words}还剩 US${left:,.0f}M 的额度"
                 + (f"，折合每季 US${left / (4 - quarters):,.1f}M。" if 4 - quarters > 1 else "。"))
    note += (f"这一年怎么结清，要等 {open_year + 1} 年 1 月那期新闻稿，届时会并入 "
             "Exhibit {EX_OPEX_LAST}。")
    return {
        "ref": "EX_FY26",
        "kind": "grouped_bars",
        "title": title,
        "xlabels": [date for date, _ in moves],
        "groups": [
            {"name": "指引区间下限", "color": "BLUE", "values": [g[0] for g in guided]},
            {"name": "指引区间中值", "color": "NAVY", "values": [round(m, 1) for _, m in moves]},
            {"name": "指引区间上限", "color": "GOLD", "values": [g[1] for g in guided]},
        ],
        "bar_labels": True,
        "fmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M",
        "note": note,
        "src_extra": (f"{count}次发布：{'、'.join(date for date, _ in moves)} 的业绩 8-K EX-99.1；"
                      "中值为本页自算（D）。"),
    }


def _on_segment_window(staging: dict, key: str) -> list[float]:
    """A `long` series cut to the segment window, so one chart has one basis."""
    lng = staging["long"]
    index = {q: i for i, q in enumerate(lng["quarters"])}
    return [abs(lng[key][index[q]]) for q in staging["segments"]["quarters"]]


def _seg_rebates(staging: dict) -> list[float]:
    return _on_segment_window(staging, "rebates")


def _seg_bcef(staging: dict) -> list[float]:
    return _on_segment_window(staging, "bcef")


def _aum_on_segment_window(staging: dict) -> list[float]:
    aum = staging["etp_aum"]
    index = {q: i for i, q in enumerate(aum["quarters"])}
    return [aum["period_end_usd_b"][index[q]] for q in staging["segments"]["quarters"]]


def _retained_capture(staging: dict) -> list[float]:
    """Rebates as a share of gross trading revenue with the SEC fee taken out.

    The headline pass-through ratio moves whenever the Section 31 rate moves,
    which is a regulator's decision and not a fact about the business. Netting
    the fee out of both legs leaves the part volume and pricing actually drive.
    """
    seg = staging["segments"]
    rebates, bcef = _seg_rebates(staging), _seg_bcef(staging)
    return [100.0 * r / (g - b) for r, b, g in zip(rebates, bcef, seg["ms_gross"])]


def aum_first_trillion(staging: dict) -> bool:
    """Did the period-end AUM cross US$1,000B for the first time this quarter?"""
    values = staging["etp_aum"]["period_end_usd_b"]
    return values[-1] >= 1000 and all(v < 1000 for v in values[:-1])


def s31_story(staging: dict) -> dict:
    """The fee's own record: now, before, and the run of zero quarters between."""
    s31 = staging["section_31"]
    fees = s31["fees_usd_m"]
    run = zero_run_before_last(fees)
    return {"now": fees[-1], "prior": fees[-2], "run": run,
            "run_from": s31["quarters"][-1 - run] if run else None,
            "run_to": s31["quarters"][-2] if run else None}


def quarter_section(staging: dict, year_ago: YearAgo, context: dict | None) -> list[dict]:
    """What moved this quarter, and the pass-through the gross line hides."""
    s31 = staging["section_31"]
    seg = staging["segments"]
    arr = staging["arr"]
    aum = staging["etp_aum"]
    fees = s31["fees_usd_m"]
    residual = s31["residual_usd_m"]
    story = s31_story(staging)

    share = [100.0 * f / b if b else None
             for f, b in zip(s31["fees_usd_m"], s31["bcef_usd_m"])]
    if share[-1] is not None and share[-1] >= 90:
        s31_lead = "<b>这条支出行几乎全部不是纳斯达克的成本，而是它替 SEC 收的一笔税。</b>"
    elif fees[-1] == 0:
        s31_lead = "<b>本季这条支出行只剩真实的经纪与清算成本：替 SEC 收的那笔规费是零。</b>"
    else:
        s31_lead = (f"<b>这条支出行本季有 {share[-1]:.0f}% 不是纳斯达克的成本，"
                    "而是它替 SEC 收的一笔税。</b>")
    low, high = min(fees), max(fees)
    span = (f"从 US${low:,.0f}M 走到 US${high:,.0f}M" if fees.index(low) < fees.index(high)
            else f"在 US${low:,.0f}M 与 US${high:,.0f}M 之间")
    if story["run"] and story["now"] > 0:
        back = (f"：{story['run_from']} 至 {story['run_to']} 连续{cn_count(story['run'])}个季度为零，"
                if story["run"] > 1 else f"：{story['run_to']} 为零，")
        back += f"本季又回到 US${story['now']:,.0f}M。"
    else:
        back = f"，本季 US${story['now']:,.0f}M。"

    n_seg = len(seg["quarters"])

    legs = [year_ago.growth(key, seg[key]) for key in ("cap", "fin", "ms_net")]
    adenza = seg["quarters"].index(ADENZA_QUARTER)
    reg_jump = (seg["fin_reg"][adenza - 1], seg["fin_reg"][adenza])
    cmt_jump = (seg["fin_cmt"][adenza - 1], seg["fin_cmt"][adenza])
    index_growth = year_ago.growth("cap_index", seg["cap_index"])

    first_trillion = aum_first_trillion(staging)
    adjusted = (context or {}).get("index_adjusted")
    index_note = ""
    if adjusted:
        index_note = (f"<b>标题里那个 {signed(index_growth)} 是报告口径，公司自己给的调整后口径是 "
                      f"+{adjusted['adjusted_yoy_pct']:.0f}%</b> —— "
                      f"差额是本季 Index 业务{adjusted['cause']}（US${adjusted['one_time_usd_m']:,.0f}M），"
                      "公司在新闻稿脚注里把它从调整后同比中剔除，金额印在同一份新闻稿的"
                      "「Reconciliation of Organic and Adjusted Impacts」表里。"
                      "两个数都印在这里，因为只引报告值会高估这条腿的斜率。")
    aum_window = _aum_on_segment_window(staging)

    cap_yoy, fin_yoy = arr["cap_yoy_pct"][-1], arr["fin_yoy_pct"][-1]
    faster, slower = max(fin_yoy, cap_yoy), min(fin_yoy, cap_yoy)
    ratio = faster / slower if slower > 0 else math.inf
    if 1.5 <= ratio < 2.5:
        gap_words = "<b>两条腿的增速差了一倍</b>"
    elif ratio >= 2.5:
        names = ("Financial Technology", "Capital Access") if fin_yoy > cap_yoy else (
            "Capital Access", "Financial Technology")
        gap_words = f"<b>{names[0]}的增速是{names[1]}的 {ratio:.1f} 倍</b>"
    else:
        gap_words = f"<b>两条腿的增速差了 {faster - slower:.1f} 个百分点</b>"
    printed_as = arr["arr_cap"][-5]
    restated_as = arr["cap_prior_year_same_release"][-1]
    printed = (context or {}).get("arr_printed") or {}
    arr_basis = ""
    if printed_as != restated_as:
        arr_basis = ("公司在 2025 年 10 月卖掉 Solovis 并把它从 Capital Access 移入 Other、重述了可比期，"
                     f"所以 {arr['quarters'][-5]} 的 Capital Access ARR 有两个值 —— 当期印的 "
                     f"US${printed_as:,.0f}M 与重述后的 US${restated_as:,.0f}M。拿本季除以当期那个会得出 "
                     f"{signed(pct_change(arr['arr_cap'][-1], printed_as))}，而同口径是 {signed(cap_yoy)}"
                     + (f"，也正是公司自己在这份新闻稿里写的 {printed['cap_pct']:.0f}%。"
                        if "cap_pct" in printed else "。"))

    charts = [{
        "ref": "EX_S31",
        "kind": "stacked_dual",
        "title": (f"「经纪、清算与交易所费用」拆开看：本季 SEC Section 31 规费 "
                  f"US${fees[-1]:,.0f}M，上一季是 US${fees[-2]:,.0f}M"),
        "xlabels": s31["period_labels"],
        "stacks": [
            {"name": "SEC Section 31 规费（代收代付）", "color": "NAVY",
             "values": rounded(s31["fees_usd_m"]), "label": True, "label_color": "WHITE"},
            {"name": "其余经纪与清算费用", "color": "GOLD",
             "values": rounded(s31["residual_usd_m"])},
        ],
        "line": {"name": "Section 31 占该行的比重 (RHS)", "color": "RED",
                 "values": rounded(share), "yfmt": "pct1", "ymax": 100},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M", "ylab2": "Section 31 占比",
        "note": (
            s31_lead
            + "10-Q 的原话是：Section 31 规费同时计入收入与交易性支出，"
            "「由于计入收入的金额等于计入 Section 31 规费的金额，对我们的净收入没有影响」。"
            # The count here said 18 after the fee record was reached back to
            # 2016Q1 (42 quarters); the range beside it was already over all 42.
            f"把它剥掉之后剩下的真实经纪与清算费用，{len(residual)} 个季度里始终在 US$"
            f"{min(residual):.0f}M–US${max(residual):.0f}M 之间，"
            "几乎是一条直线。"
            f"而规费本身在同一窗口里{span}" + back + "费率由 SEC 定，不由公司定。"),
        "src_extra": ("Section 31 规费逐季数值取自各期 10-Q / 10-K 的 MD&A 表格"
                      "（U.S. Equity Derivative Trading 与 Cash Equity Trading 两块相加）；"
                      "该行总额取自各季业绩 8-K EX-99.1 的合并损益表；"
                      "其余经纪与清算费用为两者之差（D）。各年第四季由 10-K 全年数减前三季得到。"),
    }, {
        "ref": "EX_SEG",
        "kind": "grouped_bars",
        "title": (f"三个分部的净收入：Capital Access US${seg['cap'][-1]:,.0f}M、"
                  f"Financial Technology US${seg['fin'][-1]:,.0f}M、"
                  f"Market Services 净 US${seg['ms_net'][-1]:,.0f}M"),
        "xlabels": seg["period_labels"],
        "groups": [
            {"name": "Capital Access Platforms", "color": "NAVY", "values": rounded(seg["cap"])},
            {"name": "Financial Technology", "color": "BLUE", "values": rounded(seg["fin"])},
            {"name": "Market Services（净）", "color": "GOLD", "values": rounded(seg["ms_net"])},
            {"name": "Other", "color": "RED", "values": rounded(seg["other"])},
        ],
        "fmt": "f0c", "label_fmt": "f0c", "ylab": "US$M",
        "note": (
            f"四条相加等于合并净收入，{n_seg} 个季度逐季核对无差。"
            f"<b>窗口从 {seg['quarters'][0]} 起，不向前回补</b>：这套三分部结构是 2023 年那次重组的产物，"
            "在此之前公司先后用过 Market Services / Listing Services / Information Services / "
            "Technology Solutions、Market Services / Corporate Services / Information Services / "
            "Market Technology、以及 Market Platforms / Capital Access Platforms / "
            "Anti-Financial Crime 三套完全不同的分部口径，各季的分部数不可直接相接。"
            f"本季三条腿同比分别为 {signed(legs[0])}、{signed(legs[1])}、{signed(legs[2])}。"),
        "src_extra": ("各季业绩 8-K EX-99.1 的 Revenue Detail 表。"
                      "每个季度的四条腿取自<b>同一份</b>新闻稿：分季取各自最早出现的那份，"
                      "会把重组前后的两套口径拼在一起，加总比净收入少 US$9M。"),
    }, {
        "ref": "EX_FINSUB",
        "kind": "grouped_bars",
        "title": (f"Financial Technology 的三条子线：Capital Markets Tech "
                  f"US${seg['fin_cmt'][-1]:,.0f}M、Regulatory Tech US${seg['fin_reg'][-1]:,.0f}M、"
                  f"Financial Crime Management US${seg['fin_fcmt'][-1]:,.0f}M"),
        "xlabels": seg["period_labels"],
        "groups": [
            {"name": "Capital Markets Technology", "color": "NAVY", "values": rounded(seg["fin_cmt"])},
            {"name": "Regulatory Technology", "color": "BLUE", "values": rounded(seg["fin_reg"])},
            {"name": "Financial Crime Management Technology", "color": "GOLD",
             "values": rounded(seg["fin_fcmt"])},
        ],
        "fmt": "f0c", "label_fmt": "f0c", "ylab": "US$M",
        "break_at": adenza,
        "break_label": "Adenza 交割（2023-11-01）",
        "note": (
            "<b>2023Q4 那道竖线是收购，不是增长。</b>Adenza 于 2023-11-01 交割，"
            "AxiomSL 并入 Regulatory Technology、Calypso 并入 Capital Markets Technology，"
            f"两条线因此分别从 US${reg_jump[0]:,.0f}M、US${cmt_jump[0]:,.0f}M 一步跳到 "
            f"US${reg_jump[1]:,.0f}M、US${cmt_jump[1]:,.0f}M；"
            "该季只含两个月的被收购业务，下一季才是完整季度。"
            "跨这道线比较同比增速没有意义，本页也不这样比。"
            f"2024Q1 之后三条线都是内生的：本季分别同比 "
            f"{signed(year_ago.growth('fin_cmt', seg['fin_cmt']))}、"
            f"{signed(year_ago.growth('fin_reg', seg['fin_reg']))}、"
            f"{signed(year_ago.growth('fin_fcmt', seg['fin_fcmt']))}。"),
        "src_extra": ("各季 EX-99.1 的 Revenue Detail 表。"
                      "Financial Crime Management Technology 是 2024 年 4 月那期新闻稿才从 "
                      "Regulatory Technology 里单列出来的，并回溯重述了 2023 各季；"
                      "2022Q4 没有这条子线，图上留空不补。"),
    }, {
        "ref": "EX_INDEX",
        "kind": "bar_line",
        "title": (f"Index：挂钩纳斯达克指数的 ETP AUM 期末 US${aum['period_end_usd_b'][-1]:,.0f}B"
                  + (" 首次站上一万亿，" if first_trillion else "，")
                  + f"Index 收入同比 {signed(index_growth)}"),
        "xlabels": seg["period_labels"],
        "bar": {"name": "期末 ETP AUM", "values": rounded(aum_window),
                "color": "BLUE"},
        "line": {"name": "Index 分部收入（US$M，RHS）", "color": "RED", "yfmt": "f0c",
                 "values": rounded(seg["cap_index"])},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$B", "ylab2": "Index 收入 US$M",
        "note": (
            index_note
            + "<b>本页不把这两条线相除。</b>Index 分部收入除了挂钩 AUM 的 ETP 授权费，"
            "还包含指数期权与期货的授权收入，"
            "所以「收入 ÷ AUM」不是费率，印成基点会让读者以为那是一个可比的过路费。"
            "公司也从不披露这个费率。两条线各自看，差距的方向才是信息："
            f"窗口内 AUM 涨到期初的 {aum_window[-1] / aum_window[0]:.1f} 倍，"
            f"Index 收入涨到期初的 {seg['cap_index'][-1] / seg['cap_index'][0]:.1f} 倍。"
            f"本图只画现行分部口径下的 {n_seg} 个季度；AUM 自己的 {len(aum['quarters'])} 季长序列见 "
            "Exhibit {EX_AUMLONG}。"),
        "src_extra": ("AUM 取自各季 EX-99.1 的 Key Drivers 表，Index 收入取自同一份新闻稿的 "
                      "Revenue Detail 表。窗口与分部图一致，因为 Index 这条收入线在 2018 年"
                      "第二季度的 Information Services 拆分中被重新划过一次，"
                      "更早的读数与现行口径不可直接相接。"),
    }, {
        "ref": "EX_ARR",
        "kind": "grouped_bars",
        "title": (f"ARR 两条腿：Financial Technology US${arr['arr_fin'][-1]:,.0f}M、同比 "
                  f"{signed(fin_yoy)}；"
                  f"Capital Access US${arr['arr_cap'][-1]:,.0f}M、同比 "
                  f"{signed(cap_yoy)}"),
        "xlabels": arr["period_labels"],
        "groups": [
            {"name": "Financial Technology ARR", "color": "NAVY", "values": rounded(arr["arr_fin"])},
            {"name": "Capital Access Platforms ARR", "color": "BLUE", "values": rounded(arr["arr_cap"])},
        ],
        "fmt": "f0c", "label_fmt": "f0c", "ylab": "US$M",
        "break_at": arr["quarters"].index(ADENZA_QUARTER),
        "break_label": "Adenza 交割（2023-11-01）",
        "note": (
            f"两条相加是公司口径的总 ARR，本季 US${arr['arr_fin'][-1] + arr['arr_cap'][-1]:,.0f}M。"
            + gap_words + "，而订阅这件事对二者的含义并不相同："
            "Capital Access 那条主要是上市公司年费与数据订阅，随上市公司家数走；"
            "Financial Technology 那条是软件合同，随签约与交叉销售走。"
            "<b>标题里的同比取自同一份新闻稿里并排印出的两列，而不是本图两根柱子相除</b>"
            + ("：" + arr_basis if arr_basis else "。")
            + "ARR 是合同的年化值而不是收入，公司自己也说它「不是预测」，"
            "与已确认收入之间没有恒等式，本页不把两者相除。"),
        "src_extra": ("各季 EX-99.1 的 Key Drivers 表；柱子为各季首次披露值，"
                      "同比为同一份新闻稿内当期与去年同期两列之比（D）。"
                      "2023 各季的 ARR 在当期新闻稿里按当时的分部口径印出，2024 年的新闻稿按现行口径重述过；"
                      "本页每季取<b>同一份</b>新闻稿里两条腿同时存在的那一版，"
                      "分季取最早出现的那版会把 Capital Access 的 ARR 画出一个 2.4 倍的假跳升。"),
    }]
    return charts


def kpi_entry(kpi: dict, metric: str) -> dict | None:
    return next((entry for entry in kpi["quantified"] if entry["metric"] == metric), None)


def next_section(staging: dict, kpi: dict, context: dict | None) -> list[dict]:
    lng = staging["long"]
    fin = staging["financials"]
    story = s31_story(staging)
    excluded = fill_story(kpi.get("excluded", ""), {
        "fee_now": f"US${story['now']:,.0f}M",
        "fee_prior": f"US${story['prior']:,.0f}M",
    })
    exhibits = [headroom_exhibit(
        f"下季 {len(kpi['quantified'])} 条阈值：当前值离阈值的余量",
        kpi["quantified"], "current",
        ("正值表示仍在安全侧。阈值为本地研究设定，<b>不是公司指引</b> —— "
         "纳斯达克只指引全年非 GAAP 营业费用与非 GAAP 有效税率两个数，"
         "从不指引收入、每股收益或利润率，见第一节。"
         + excluded),
        f"当前值为 {staging['periods'][-1]} 披露值或本页自算；阈值为本地研究设定。")]

    margin = kpi_entry(kpi, "非 GAAP 经营利润率")
    if margin:
        values = lng["nongaap_margin_pct"]
        falls = sum(1 for a, b in zip(values, values[1:]) if b < a)
        direction = "向上" if values[-1] > values[0] else "向下"
        # "Almost monotone" was the original word; 17 of the 45 quarter-on-quarter
        # changes are falls, so the page counts them instead.
        shape = (f"几乎单调{direction}" if falls <= (len(values) - 1) // 10
                 else f"总体{direction}（{len(values) - 1} 次环比里 {falls} 次回落）")
        exhibits.append(threshold_exhibit(
            "非 GAAP 经营利润率：当前 "
            f"{fin['nongaap_margin_pct'][-1]:.1f}%，阈值 {margin['threshold']:.1f}%",
            lng["period_labels"], rounded(values), margin["threshold"],
            fmt="pct1", ylab="%",
            actual_name="非 GAAP 经营利润率", threshold_name="本地阈值",
            note=("红线是本地研究设定的阈值，不是公司指引 —— 公司从不指引利润率。"
                  f"{len(values)} 个季度里这条线从 {values[0]:.1f}% 走到 "
                  f"{values[-1]:.1f}%，{shape}；"
                  "分母是净收入（已扣除交易性支出），所以上一节那笔 SEC 规费的开关不影响它。"),
            src_extra="各季业绩 8-K EX-99.1 的非 GAAP 经营利润调节表；分母为净收入。"))
        exhibits[-1]["xstep"] = LONG_STEP

    aum = staging["etp_aum"]
    aum_entry = kpi_entry(kpi, "期末 ETP AUM")
    if aum_entry:
        ttm = (context or {}).get("aum_ttm_usd_b")
        if ttm:
            bigger = "净增值大于净流入" if ttm["net_appreciation"] > ttm["net_inflows"] else "净流入大于净增值"
            market = ("它同时是市场涨跌的读数而不只是经营的读数："
                      f"公司自己披露的滚动十二个月数据里，增量中{bigger}。")
        else:
            market = "它同时是市场涨跌的读数而不只是经营的读数。"
        exhibits.append(threshold_exhibit(
            f"期末 ETP AUM：当前 US${aum['period_end_usd_b'][-1]:,.0f}B，"
            f"阈值 US${aum_entry['threshold']:,.0f}B",
            aum["period_labels"], rounded(aum["period_end_usd_b"]), aum_entry["threshold"],
            fmt="f0c", ylab="US$B",
            actual_name="期末 ETP AUM", threshold_name="本地阈值",
            note=("红线是本地研究设定的阈值，不是公司指引 —— 公司从不指引 AUM。"
                  + ("本季是这条序列首次站上一万亿美元，" if aum_first_trillion(staging) else "")
                  + aum_entry.get("why", "")
                  + market),
            src_extra="各季业绩 8-K EX-99.1 的 Key Drivers 表；公司披露值。"))
        exhibits[-1]["xstep"] = LONG_STEP
    return exhibits


def gross_to_net_chart(staging: dict) -> dict:
    """Where the Market Services gross line goes: a structural chart, not a quarter's news.

    It used to sit in the quarter's section, but what it argues -- that only about
    a quarter of the exchange's gross revenue stays with the company, and that the
    rebate share net of the SEC fee is the real volume-and-price signal -- is the
    same argument every quarter. So it belongs with the long-run series.
    """
    seg = staging["segments"]
    lng = staging["long"]
    capture = _retained_capture(staging)
    peak = capture.index(max(capture))
    capture_words = (f"{len(capture)} 个季度里它从 {capture[0]:.1f}% 走到 "
                     f"{max(capture):.1f}% 的高点，本季 {capture[-1]:.1f}%。"
                     if peak != len(capture) - 1 else
                     f"{len(capture)} 个季度里它从 {capture[0]:.1f}% 走到本季 {capture[-1]:.1f}% 的高点。")
    basis = staging["ms_reclassification"]
    old_basis = lng["ms_net"][lng["quarters"].index(basis["quarter"])]
    n_seg = len(seg["quarters"])
    return {
        "ref": "EX_GROSSNET",
        "kind": "stacked_dual",
        "title": (f"Market Services 毛收入的去向：本季毛 US${seg['ms_gross'][-1]:,.0f}M，"
                  f"留在公司的净收入 US${seg['ms_net'][-1]:,.0f}M（{100 * seg['ms_net'][-1] / seg['ms_gross'][-1]:.1f}%）"),
        "xlabels": seg["period_labels"],
        "stacks": [
            {"name": "交易返点（付给流动性提供方）", "color": "BLUE",
             "values": rounded(_seg_rebates(staging))},
            {"name": "经纪、清算与交易所费用（近全部为 SEC 规费）", "color": "GOLD",
             "values": rounded(_seg_bcef(staging))},
            {"name": "Market Services 净收入", "color": "NAVY",
             "values": rounded(seg["ms_net"])},
        ],
        "line": {"name": "返点 ÷（毛收入 − 规费）(RHS)", "color": "RED",
                 "yfmt": "pct1", "ymax": 100,
                 "values": rounded(capture)},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M", "ylab2": "返点占比",
        "note": (
            f"<b>交易所毛收入线里，只有约{cn_fraction(seg['ms_net'][-1] / seg['ms_gross'][-1])}留在公司。</b>"
            "三段自下而上是付给做市商与流动性提供方的返点、Exhibit {EX_S31} 拆出来的那笔 SEC 规费，"
            "以及公司真正留下的净收入。"
            f"<b>窗口只画 {seg['quarters'][0]} 之后的 {n_seg} 个季度，是因为再往前不是同一个口径</b>："
            "2022 年那次重组把不产生交易性支出的 Trade Management Services 移出了 Market Services，"
            f"分母因此变窄 —— 同一个 {basis['quarter']}，旧口径净收入 US${old_basis:,.0f}M、"
            f"新口径 US${basis['new_usd_m']:,.0f}M，"
            "拿旧口径的比例和新口径连成一条线，会把一次重分类读成过路成本的上升。"
            "红线是剥掉规费之后的返点占比，规费的开关动不了它："
            + capture_words + "这条线才是量与价的真实变化。"),
        "src_extra": ("毛收入、返点与经纪清算费均取自各季 EX-99.1 合并损益表与 Revenue Detail 表；"
                      f"三段相加等于毛收入，{n_seg} 个季度逐季核对无差。红线为本页自算（D）。"),
    }


def routine_section(staging: dict) -> list[dict]:
    lng = staging["long"]
    aum = staging["etp_aum"]
    n = len(lng["quarters"])
    gap = [None if None in (a, b) else a - b
           for a, b in zip(lng["nongaap_margin_pct"], lng["gaap_margin_pct"])]
    share_first = 100 * lng["ms_net"][0] / lng["net_revenue"][0]
    share_now = 100 * lng["ms_net"][-1] / lng["net_revenue"][-1]
    basis = staging["ms_reclassification"]
    at = lng["quarters"].index(basis["quarter"])
    old_basis = lng["ms_net"][at]
    reclass_pp = 100 * (old_basis - basis["new_usd_m"]) / lng["net_revenue"][at]
    total_pp = share_first - share_now
    rest_pp = total_pp - reclass_pp
    average = aum["average_usd_b"]
    average_from = next(i for i, v in enumerate(average) if v is not None)
    ends = aum["period_end_usd_b"]
    both_high = average[-1] == max(v for v in average if v is not None) and ends[-1] == max(ends)
    if both_high:
        high_words = "两者都是有披露以来的最高。"
    elif ends[-1] == max(ends):
        high_words = "期末值是有披露以来的最高。"
    elif average[-1] == max(v for v in average if v is not None):
        high_words = "平均值是有披露以来的最高。"
    else:
        high_words = ""
    return [{
        "ref": "EX_MARGIN",
        "kind": "lines",
        "title": (f"{n} 季经营利润率：非 GAAP {lng['nongaap_margin_pct'][-1]:.1f}%、"
                  f"GAAP {lng['gaap_margin_pct'][-1]:.1f}%"),
        "xlabels": lng["period_labels"],
        "series": [
            {"name": "非 GAAP 经营利润率", "values": rounded(lng["nongaap_margin_pct"]), "color": "NAVY"},
            {"name": "GAAP 经营利润率", "values": rounded(lng["gaap_margin_pct"]), "color": "BLUE"},
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
        "ylab": "%", "xstep": LONG_STEP,
        "note": (
            "两条线的<b>缺口</b>就是被调整掉的成本 —— 主要是收购无形资产摊销，"
            f"其次是重组与并购费用。缺口在 {n} 个季度里从 {gap[0]:.1f}pp 走到 {gap[-1]:.1f}pp，"
            "2023Q4 Adenza 交割后明显走阔，因为摊销基数一次性变大。"
            "两条线的分母都是净收入。第一节结清的费用指引只针对非 GAAP 口径，"
            "公司在每份新闻稿里都写明不提供 GAAP 费用指引。"),
        "src_extra": "各季业绩 8-K EX-99.1；GAAP 利润率为经营利润 ÷ 净收入（D），与公司披露值一致。",
    }, {
        "ref": "EX_MIX",
        "kind": "lines",
        "title": (f"{n} 季净收入与 Market Services 净收入：后者占比 {share_now:.1f}%"),
        "xlabels": lng["period_labels"],
        "series": [
            {"name": "合并净收入", "values": rounded(lng["net_revenue"]), "color": "NAVY"},
            {"name": "Market Services 净收入", "values": rounded(lng["ms_net"]), "color": "BLUE"},
        ],
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c", "end_label": True,
        "ylab": "US$M", "xstep": LONG_STEP,
        "break_at": lng["quarters"].index("2022Q4"),
        "break_label": "Market Services 口径变窄（2022Q4）",
        "note": (
            f"<b>这张图是这家公司{cn_count(n // 4)}年里最大的一次自我改写，但其中有一步不是业务变化。</b>"
            f"{lng['quarters'][0]} 交易业务占净收入 {share_first:.1f}%，本季 {share_now:.1f}%。"
            # The reclassification used to be measured as 305 against 245, but
            # 245 is 2022Q4 on the new basis; the same 2022Q3 reprinted on the new
            # basis (Q3 2023 release, Trading Services revenues, net) is 239.
            f"这{cn_count(round(total_pp))}个百分点里，约 {reclass_pp:.1f}pp 出现在 2022Q4 那一格："
            "重组把 Trade Management Services 移出了 Market Services，"
            f"同一个季度（{basis['quarter']}）的口径落差是 US${old_basis:,.0f}M 对 "
            f"US${basis['new_usd_m']:,.0f}M，分母（合并净收入）不变。"
            f"<b>剩下的约{cn_count(round(rest_pp))}个百分点才是业务本身的变化</b> —— "
            f"合并净收入涨了{times_word(lng['net_revenue'][-1] / lng['net_revenue'][0])}，"
            f"交易那条腿只涨了{times_word(lng['ms_net'][-1] / lng['ms_net'][0])}，"
            "差额来自上市与数据、指数，"
            "以及 2021 年之后靠 Verafin 与 Adenza 买进来的软件业务。"
            "合并净收入那条线不受这次重分类影响，跨全窗口连续。"),
        "src_extra": ("各季业绩 8-K EX-99.1 的合并损益表与 Revenue Detail 表，均为公司披露值。"
                      "口径落差由同一季度在重组前后两份新闻稿里的两个读数直接得到，非估算。"),
    }, {
        "ref": "EX_AUMLONG",
        "kind": "lines",
        "title": (f"{len(aum['quarters'])} 季挂钩纳斯达克指数的 ETP AUM：US${ends[0]:,.0f}B → "
                  f"US${ends[-1]:,.0f}B"),
        "xlabels": aum["period_labels"],
        "series": [
            {"name": "期末 ETP AUM", "values": rounded(ends), "color": "NAVY"},
            {"name": "当季平均 ETP AUM", "values": rounded(average), "color": "BLUE"},
        ],
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c", "end_label": True,
        "ylab": "US$B", "xstep": LONG_STEP,
        "note": (
            "期末值受季末一天的市场影响，平均值不受 —— 两条线拉开的地方就是季内的波动。"
            f"<b>平均值序列自 {aum['quarters'][average_from]} 才有披露，之前只有期末值，"
            "图上因此从那里开始，不向前回补。</b>"
            f"本季平均 US${average[-1]:,.0f}B、期末 "
            f"US${ends[-1]:,.0f}B" + ("，" + high_words if high_words else "。")),
        "src_extra": "各季业绩 8-K EX-99.1 的 Key Drivers 表；均为公司披露值。",
    }]


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    fin = staging["financials"]
    return [f"Net revenue ${fin['net_revenue'][-1] / 1000:.2f}B",
            f"ETP AUM ${staging['etp_aum']['period_end_usd_b'][-1]:,.0f}B",
            f"Non-GAAP OpM {fin['nongaap_margin_pct'][-1]:.1f}%"]


def settlement_lead(staging: dict, period: str) -> tuple[list[dict], str]:
    """Section one's opening: what last quarter's report left, settled -- or why nothing is.

    The first NDAQ analysis on this site covers `FIRST_REPORT_PERIOD`, so that
    quarter has no follow-up list and no thresholds to settle, and the section
    says so instead of inventing either. From the next quarter on, the report
    before it did set thresholds (its section 8), and a page that quietly
    dropped them would be the stale-prose failure in a new place: the build
    stops until `prior_kpi_settlement` is stamped for the quarter.
    """
    closure = stamped_block(staging, "followup_closure", period)
    prior = stamped_block(staging, "prior_kpi_settlement", period)
    if period == FIRST_REPORT_PERIOD:
        if closure or prior:
            raise ValueError(f"no NDAQ report precedes {FIRST_REPORT_PERIOD}: there is nothing "
                             "for `followup_closure` / `prior_kpi_settlement` to settle")
        return [], (f"本站对纳斯达克的第一份季报分析是 {FIRST_REPORT_PERIOD}，"
                    "没有上季留下的跟踪指标可结算（那份分析的第 0 节也写明没有上季问题可回看）；"
                    "本节结算的是公司自己给出的指引。")
    if prior is None:
        raise ValueError(f"the report before {period} set thresholds in its section 8: stamp "
                         f"`prior_kpi_settlement` (and `followup_closure`) for {period}")
    charts: list[dict] = []
    if closure:
        counts = dict(zip(closure["labels"], closure["counts"]))
        charts.append({
            "kind": "bars_labeled",
            "title": (f"上季 {sum(closure['counts'])} 条待验证问题："
                      + "、".join(f"{count} 条{label}" for label, count in counts.items())),
            "xlabels": closure["labels"], "values": closure["counts"],
            "legend": "问题条数", "fmt": "f0", "yfmt": "f0", "label_fmt": "f0", "ylab": "条",
            "note": closure.get("note", "逐条判定见上季报告的 Follow-up Questions 与本季报告第 0 节。"),
            "src_extra": f"问题清单来自 {closure.get('set_in', '上季')} 的本地分析稿；判定依据本季新闻稿与 10-Q。",
        })
    entries = prior["quantified"]
    held = sum(1 for e in entries if headroom(e["direction"], e["threshold"], e["actual"]) >= 0)
    charts.append(headroom_exhibit(
        f"上季 {len(entries)} 条量化阈值：{held} 条守住、{len(entries) - held} 条击穿",
        entries, "actual",
        "正值 = 守住上季报告第 8 节设的阈值，负值 = 击穿。阈值逐字取自上季报告，实际值取自本季申报。",
        f"阈值：{prior.get('set_in', '上季')} 的本地分析稿第 8 节；实际值：{period} 申报。"))
    return charts, "先结算上季报告留下的问题与阈值，再看公司自己给出的指引。"


def accelerating(now: float, before: float) -> bool:
    return now > before


PACE_WORDS = {"加速": "在加速", "放缓": "放缓", "持平": "增速持平"}


def pace(now: float, before: float) -> str:
    """Faster, slower or level, at the one decimal the page prints."""
    now, before = round(now, 1), round(before, 1)
    return "加速" if now > before else ("放缓" if now < before else "持平")


def build_payload(staging: dict) -> dict:
    fin = staging["financials"]
    seg = staging["segments"]
    arr = staging["arr"]
    aum = staging["etp_aum"]
    labels = staging["period_labels"]
    period = labels[-1]
    hist = staging["annual_guidance_history"]
    latest = latest_block(staging, period=period, period_end=staging["period_ends"][-1])
    kpi = stamped_block(staging, "next_kpi", period)
    context = stamped_block(staging, "quarter_context", period)
    year_ago = YearAgo(stamped_block(staging, "year_ago_reprinted", period))
    release = release_source(staging)

    lead, settled_opening = settlement_lead(staging, period)
    guidance_charts, settled_tables = guidance_section(staging)
    settled = lead + guidance_charts
    opex_record = hist["operating_expense"]
    highlights = quarter_section(staging, year_ago, context) + [
        open_year_chart(staging, opex_record, finished_years(opex_record))]
    next_block = next_section(staging, kpi, context) if kpi else []
    routine = routine_section(staging)
    routine.insert(2, gross_to_net_chart(staging))

    exhibits = number_exhibits(settled + highlights + next_block + routine)
    resolve_exhibit_refs(exhibits)
    n1, n2, n3 = len(settled), len(highlights), len(next_block)
    settled_ex = exhibits[:n1]
    highlight_ex = exhibits[n1:n1 + n2]
    next_ex = exhibits[n1 + n2:n1 + n2 + n3]
    routine_ex = exhibits[n1 + n2 + n3:]
    open_year_n = next(ex["n"] for ex in highlight_ex if ex.get("ref") == "EX_FY26")

    first_table = exhibits[-1]["n"] + 1
    tables = [{**t, "n": first_table + i} for i, t in enumerate(settled_tables)]
    tables.append({
        "n": first_table + len(settled_tables),
        "title": f"近{cn_count(len(labels))}季合并损益与交易性支出（公司披露值，US$M）",
        "headers": ["期间", "总收入", "交易返点", "经纪清算与交易所费用", "净收入",
                    "营业费用", "经营利润", "GAAP 利润率", "非 GAAP 营业费用",
                    "非 GAAP 利润率", "GAAP 摊薄 EPS", "非 GAAP 摊薄 EPS"],
        "rows": [[labels[i],
                  f"${fin['total_revenues'][i]:,.0f}",
                  f"−${abs(fin['rebates'][i]):,.0f}",
                  f"−${abs(fin['bcef'][i]):,.0f}",
                  f"${fin['net_revenue'][i]:,.0f}",
                  f"${fin['opex'][i]:,.0f}",
                  f"${fin['op_income'][i]:,.0f}",
                  f"{fin['gaap_margin_pct'][i]:.1f}%",
                  f"${fin['nongaap_opex'][i]:,.0f}",
                  f"{fin['nongaap_margin_pct'][i]:.1f}%",
                  f"${fin['diluted_eps'][i]:.2f}",
                  f"${fin['nongaap_eps'][i]:.2f}"]
                 for i in range(len(labels))],
    })
    tables.append({
        "n": tables[-1]["n"] + 1,
        "title": "Section 31 规费与它所在的支出行（US$M）",
        "headers": ["期间", "SEC Section 31 规费", "经纪清算与交易所费用合计",
                    "其余经纪与清算费用 D", "Section 31 占该行 D"],
        "rows": [[staging["section_31"]["period_labels"][i],
                  f"${staging['section_31']['fees_usd_m'][i]:,.0f}",
                  f"${staging['section_31']['bcef_usd_m'][i]:,.0f}",
                  f"${staging['section_31']['residual_usd_m'][i]:,.1f}",
                  f"{100 * staging['section_31']['fees_usd_m'][i] / staging['section_31']['bcef_usd_m'][i]:.1f}%"]
                 for i in range(len(staging["section_31"]["quarters"]))],
    })
    if kpi:
        tables.append(threshold_table(tables[-1]["n"] + 1,
                                      "下季阈值与当前值（原始单位）",
                                      kpi["quantified"], "current", "当前值"))
    tables.append(ai_capex_cycle_table(tables[-1]["n"] + 1))

    opex = hist["operating_expense"]
    tax = hist["tax_rate"]
    t_last = tally(opex, 1)
    t_first = tally(opex, 0)
    tax_last = tally(tax, 1)
    n_years = len(finished_years(opex))
    n_tax = len(finished_years(tax))
    opex_never_below = t_last["below"] == 0
    tax_never_above = tax_last["above"] == 0

    net_growth = year_ago.growth("net_revenue", fin["net_revenue"])
    index_growth = year_ago.growth("cap_index", seg["cap_index"])
    index_before = pct_change(seg["cap_index"][-2], seg["cap_index"][-6])
    fin_growth = year_ago.growth("fin", seg["fin"])
    fin_before = pct_change(seg["fin"][-2], seg["fin"][-6])
    fin_arr_now, fin_arr_before = arr["fin_yoy_pct"][-1], arr["fin_yoy_pct"][-2]
    first_trillion = aum_first_trillion(staging)
    story = s31_story(staging)

    record = ("公司唯一给的两条指引都只关于自己的成本 —— "
              f"{n_years} 个完整年度里全年非 GAAP 营业费用"
              + ("没有一年低于指引下限" if opex_never_below else f"有 {t_last['below']} 年低于指引下限")
              + f"，{n_tax} 个年度里非 GAAP 有效税率"
              + ("没有一年高于指引上限。" if tax_never_above else f"有 {tax_last['above']} 年高于指引上限。"))
    headline = (
        f"净收入 US${fin['net_revenue'][-1]:,.0f}M、同比 {signed(net_growth)}，"
        f"Index 收入同比 {signed(index_growth)}、"
        + (f"挂钩指数的 ETP AUM 首次突破一万亿美元（期末 US${aum['period_end_usd_b'][-1]:,.0f}B）；"
           if first_trillion else
           f"挂钩指数的 ETP AUM 期末 US${aum['period_end_usd_b'][-1]:,.0f}B；")
        + record)

    # Which legs sped up. "Index 与 FinTech 是加速的两条腿" was written when both
    # did; in Q2 2026 Financial Technology's revenue growth slowed from +19.7% to
    # +16.2% and its ARR growth from +17.6% to +15.7%.
    arr_legs = [("Index", pace(index_growth, index_before)),
                ("FinTech", pace(fin_arr_now, fin_arr_before))]
    fast = [name for name, state in arr_legs if state == "加速"]
    if len(fast) == 2:
        legs_title = "Index 与 FinTech 是加速的两条腿"
    elif all(state == "放缓" for _, state in arr_legs):
        legs_title = "Index 与 FinTech 都在放缓"
    else:
        legs_title = "，".join(f"{name} {PACE_WORDS[state]}" for name, state in arr_legs)
    fin_arr_words = (f'Financial Technology ARR US${arr["arr_fin"][-1]:,.0f}M、同比 {signed(fin_arr_now)}'
                     + ("" if accelerating(fin_arr_now, fin_arr_before)
                        else f'（上季 {signed(fin_arr_before)}）'))
    cap_arr_words = (f'而 Capital Access ARR 只有 {signed(arr["cap_yoy_pct"][-1])}'
                     if arr["cap_yoy_pct"][-1] < fin_arr_now else
                     f'Capital Access ARR {signed(arr["cap_yoy_pct"][-1])}')
    index_words = (f'Index 收入 US${seg["cap_index"][-1]:,.0f}M、同比 {signed(index_growth)}'
                   + ("" if accelerating(index_growth, index_before) else f"（上季 {signed(index_before)}）"))

    articles = [
        '<article><span>记录</span><b>'
        + ("只指引成本，而且是单边的" if opex_never_below and tax_never_above else "只指引成本")
        + '</b>'
        f'<p>{n_years} 年里全年非 GAAP 营业费用对当年最后一次指引 {t_last["inside"]} 次落在区间内、'
        f'{t_last["above"]} 次高于上限、{t_last["below"]} 次低于下限；换成年初那次是 '
        f'{t_first["inside"]}/{t_first["above"]}/{t_first["below"]}。'
        f'税率 {n_tax} 年里 {tax_last["above"]} 次高于上限。</p></article>',
        f'<article><span>亮点</span><b>{legs_title}</b>'
        f'<p>{index_words}；{fin_arr_words}，{cap_arr_words}。</p></article>',
    ]
    gross_growth = year_ago.growth("ms_gross", seg["ms_gross"])
    net_ms_growth = year_ago.growth("ms_net", seg["ms_net"])
    fee_before = dict(zip(staging["section_31"]["quarters"],
                          staging["section_31"]["fees_usd_m"])).get(staging["periods"][-5])
    if story["now"] > 0 and fee_before is not None:
        gross_ago = year_ago.of("ms_gross", seg["ms_gross"])
        ex_fee = pct_change(seg["ms_gross"][-1] - story["now"], gross_ago - fee_before)
        gap = gross_growth - net_ms_growth
        explained = (gap - (ex_fee - net_ms_growth)) / gap if gap else 0
        if story["run"] > 1:
            before_words = f"前{cn_count(story['run'])}个季度是 US$0M"
        elif story["run"] == 1:
            before_words = "上一季是 US$0M"
        else:
            before_words = f"上一季是 US${story['prior']:,.0f}M"
        articles.append(
            '<article><span>口径</span><b>毛收入里有一笔 SEC 规费</b>'
            f'<p>本季 Section 31 规费 US${story["now"]:,.0f}M，{before_words}。'
            f'它同时进收入与支出，对净收入没有影响；'
            f'毛收入同比 {signed(gross_growth)} 与净收入同比 {signed(net_ms_growth)} 的差距'
            + ("几乎全在这里。" if explained >= 0.85 else
               f"只有一部分在这里：剥掉规费后毛收入同比 {signed(ex_fee)}。")
            + '</p></article>')

    if len(fast) == 2 and accelerating(fin_growth, fin_before):
        highlight_words = "Index 与 Financial Technology 是本季加速的来源。"
    else:
        moves = [("Index", index_before, index_growth), ("Financial Technology", fin_before, fin_growth)]
        up = [f"{name}（收入同比从 {signed(a)} 到 {signed(b)}）" for name, a, b in moves if b > a]
        down = [f"{name}（从 {signed(a)} 到 {signed(b)}）" for name, a, b in moves if b <= a]
        highlight_words = ((f"本季加速的是 {'、'.join(up)}" if up else "本季没有一条腿在加速")
                           + (f"，放缓的是 {'、'.join(down)}。" if down else "。"))

    aum_years = (len(aum["quarters"]) - 1) // 4
    aum_times = round(aum["period_end_usd_b"][-1] / aum["period_end_usd_b"][0])
    ms_share = 100 * staging["long"]["ms_net"][-1] / staging["long"]["net_revenue"][-1]
    notes = notes_for(staging, latest, context)

    return {
        "schema_version": "quarterly-dashboard/ndaq-v1",
        "page": {"slug": "ndaq", "language": "zh-CN"},
        "company": {
            "ticker": "NDAQ",
            "name": "Nasdaq, Inc.",
            "group": "financial_data_indices",
            "accounting_standard": "US GAAP",
        },
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · NDAQ",
        "title": f"Nasdaq, Inc. (NDAQ)：{period} 季报仪表盘",
        "subtitle": (f"截至 {latest['period_end']} · 发布 {latest['release_date']} · US GAAP · "
                     f"{AUDIT_WORDS[latest['audit_status']]} · "
                     "自然年财年，季度标注与财年一致"),
        "headline": headline,
        "brief": (
            f'<h4>本季{cn_count(len(articles))}条主线</h4><div class="takeaway-grid">'
            + "".join(articles)
            + '</div>'),
        "source": (f'Source: <a href="{release["url"]}" rel="noopener">{release["label"]}</a>'
                   f"与截至 {latest['period_end']} 的 {'10-K' if period.startswith('Q4') else '10-Q'}。"),
        "source_url": release["url"],
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {"id": "settled", "title": "一、上季跟踪指标兑现了吗",
             "description": (settled_opening
                             + "纳斯达克只指引两个数：全年非 GAAP 营业费用与全年非 GAAP 有效税率，"
                             "两者都是年度的，都在每季业绩新闻稿里更新一次；"
                             "它从不指引收入、每股收益或利润率，也从不提供任何 GAAP 口径的指引。"
                             f"所以能结清的只有已经过完的年度（FY{finished_years(opex_record)[0]} 至 "
                             f"FY{finished_years(opex_record)[-1]}），结清的是公司自己的预算，不是它对业务的预测；"
                             f"FY{max(opex_record['years'])} 还没过完，它这一年的几次发布是本季的事，"
                             f"放在第二节（Exhibit {open_year_n}）。"
                             "「年初那次」与「当年最后一次」分开算，因为两者的答案不一样。"),
             "exhibits": settled_ex},
            {"id": "quarter_highlights", "title": "二、本季重点",
             "description": ("先把毛收入里那笔代收代付的 SEC 规费剥掉，再看三个分部与两条 ARR，"
                             "最后是本季对全年费用指引的更新；"
                             + highlight_words),
             "exhibits": highlight_ex},
            {"id": "next_quarter", "title": "三、下季要跟踪什么",
             "description": "当前值离下季阈值还有多远，统一用「距阈值余量」口径；不接入的几条也写在这里。",
             "exhibits": next_ex},
            {"id": "routine", "title": "四、长期常规跟踪",
             "description": (f"纳斯达克专属的常规序列：{len(staging['long']['quarters'])} 季两条利润率"
                             "与它们的调整缺口、"
                             f"交易业务在净收入里退到{cn_count(math.ceil(ms_share / 10))}成以下的过程、"
                             "Market Services 毛收入里真正留在公司的那一截，"
                             f"以及指数资产{cn_count(aum_years)}年{cn_count(aum_times)}倍的曲线。"),
             "exhibits": routine_ex},
        ],
        "tables": tables,
        "notes": notes,
        "footer": "NDAQ quarterly results · 数据来自 Nasdaq 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def notes_for(staging: dict, latest: dict, context: dict | None) -> list[str]:
    hist = staging["annual_guidance_history"]
    opex, tax = hist["operating_expense"], hist["tax_rate"]
    years = finished_years(opex)
    releases = [g for block in opex["by_year"].values() for g in block["guided"] if g]
    first_release = min(g[2] for g in releases)
    tax_years = finished_years(tax)
    arr = staging["arr"]
    s31 = staging["section_31"]
    residual = s31["residual_usd_m"]
    labels = staging["period_labels"]
    period = labels[-1]
    printed = (context or {}).get("arr_printed") or {}

    restated = tally(opex, 1, overrides={2017: FY2017_RESTATED})
    fy2017_last = vintages(opex, 2017)[1]
    fy2017_first_verdict = verdict(fy2017_last[0], fy2017_last[1], opex["by_year"]["2017"]["actual"])
    fy2017_restated_verdict = verdict(fy2017_last[0], fy2017_last[1], FY2017_RESTATED)
    fy2020_high = vintages(opex, 2020)[1][1]
    fy2020_actual = opex["by_year"]["2020"]["actual"]
    implied = fy2020_high + FY2020_PREANNOUNCED_OVER

    if tuple(tax_years) == TAX_RECOMPUTED_YEARS:
        recompute = ("用新闻稿里的税前利润与税项调整独立复算的结果与之逐年相差不超过 0.04 个百分点。")
    else:
        recompute = (f"FY{TAX_RECOMPUTED_YEARS[0]} 至 FY{TAX_RECOMPUTED_YEARS[-1]} 用新闻稿里的税前利润与"
                     "税项调整独立复算过，结果与之逐年相差不超过 0.04 个百分点；更晚的年度尚未复算。")

    arr_note = ("ARR 的同比一律取自同一份新闻稿里并排印出的两列，不由本页的柱子相除。")
    if arr["arr_cap"][-5] != arr["cap_prior_year_same_release"][-1]:
        arr_note += ("2025 年 10 月出售 Solovis 后公司把它从 Capital Access Platforms 移入 Other 并重述了可比期，"
                     f"因此 {arr['quarters'][-5]} 的 Capital Access ARR 有两个值（当期 {arr['arr_cap'][-5]:,.0f}、"
                     f"重述后 {arr['cap_prior_year_same_release'][-1]:,.0f}）；跨基准相除会把该分部的同比从 "
                     + (f"{printed['cap_pct']:.0f}%" if "cap_pct" in printed
                        else f"{arr['cap_yoy_pct'][-1]:.1f}%")
                     + f" 读成 {pct_change(arr['arr_cap'][-1], arr['arr_cap'][-5]):.1f}%。")
    if "total_reported_pct" in printed and "total_organic_pct" in printed:
        arr_note += (f"公司在本季新闻稿里同时给出总 ARR 的两个增速，报告口径 {printed['total_reported_pct']:.0f}%、"
                     f"有机口径 {printed['total_organic_pct']:.0f}%，差别正是这次剥离："
                     "前者拿本季比去年当期印出的数，后者两端都在剥离后的口径上。本页图表标注有机口径可比的同一份读数。")

    unconnected = ("本页已知未接入：公司在投资者日发布的中期分部有机增长目标（不在任何申报文件里）、"
                   + ((context or {}).get("cross_sell_note", "") + "、" if (context or {}).get("cross_sell_note") else "")
                   + "各交易所的市占率与行业成交量序列（同一标签在一份新闻稿里出现两次、分别属于期权与现货两块，"
                   "按出现次序取值会静默取错，故不接入）、现金流与资本回报的逐季序列（业绩新闻稿不含现金流量表），"
                   # This said 「2026 年第三季度之后」 while the page's data ends at the
                   # second quarter: the unconnected data starts after this quarter.
                   f"以及 {quarter_words(period)}之后的任何数据（本页数据截至 {latest['release_date']} 的申报）。")

    notes = [
        "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
        "纳斯达克财年即自然年，本页季度标注与公司自己的口径一致，无需换算。",
        "第一节结清的是年度指引而不是季度指引，而且只覆盖成本与税率：公司在每季业绩新闻稿里给出并更新一次全年非 GAAP 营业费用指引与全年非 GAAP 有效税率指引，从不指引收入、每股收益或利润率。每份新闻稿都用同一句脚注说明不提供 GAAP 口径的费用与税率指引，理由是外汇变动与非经常项目难以量化。本站其他公司页第一节结清的多是季度收入区间，本页不是，差别源于公司披露口径而非编辑选择。",
        (f"费用指引记录自 {first_release[:4]} 年 {int(first_release[5:7])} 月那期新闻稿起算，"
         f"共 {len(releases)} 次发布、覆盖 FY{opex['years'][0]} 至 FY{opex['years'][-1]} "
         f"{cn_count(len(opex['years']))}个年度，其中{cn_count(len(years))}个已完结。"
         "2015 与 2016 两年公司只在第一、二季度发布过费用指引，第三、四季度没有发布，因此这两年的「当年最后一次」是 4 月而不是 10 月；已逐份读过这四期新闻稿确认不是漏读。记录不向 2014 年之前延伸，是因为非 GAAP 营业费用的定义在 2015 年 4 月那期发生过变化（收购无形资产摊销自那时起才被列为非 GAAP 调整项），跨越该点的比较不同基准。"),
        (f"税率指引自 2018 年 1 月那期新闻稿起才有，FY2018 全年只发布过一次且当年无可用实际值，"
         f"因此税率图从 FY{tax_years[0]} 起算，共{cn_count(len(tax_years))}个完整年度。"
         "全年实际的非 GAAP 有效税率业绩新闻稿从不印，取自各年 10-K 的非 GAAP 财务指标一节；"
         + recompute),
        (f"另有一次费用指引更新不在季度新闻稿里：{FY2020_PREANNOUNCED_ON} 的一份 8-K 在披露 12 月成交量的同时，"
         f"说明 2020 年非 GAAP 营业费用将「超出此前指引区间上限约 "
         f"{FY2020_PREANNOUNCED_OVER * 100:,.0f} 万美元」。该文件发布于被指引年度结束后第 "
         f"{(datetime.date.fromisoformat(FY2020_PREANNOUNCED_ON) - datetime.date(2020, 12, 31)).days} 天，"
         "且没有给出新的区间，因此不计入本页的指引 vintage；但它是理解 FY2020 那次超支的必要背景，"
         f"实际值 US${fy2020_actual:,.0f}M 与它隐含的约 US${implied:,.0f}M 相差 "
         f"US${abs(implied - fy2020_actual):,.0f}M。"),
        (f"FY2017 的全年实际值有两个版本：首次披露为 US${opex['by_year']['2017']['actual']:,.0f}M，"
         f"2018 年采用 ASC 606 全面追溯法后重述为 US${FY2017_RESTATED:,.0f}M。"
         "本页取首次披露值，因为 FY2017 的指引本身写在 ASC 606 之前的基准上，两者相比才是同口径；"
         f"若改用重述值，该年对最后一次指引的判定会由「{fy2017_first_verdict}」变为「{fy2017_restated_verdict}」，"
         f"{cn_count(len(years))}年的记录随之变为 {restated['inside']} 内 / {restated['above']} 上 / "
         f"{restated['below']} 下。这是窗口内唯一一个实际值被重述过的年度。"),
        "分部收入、ARR 与分部子线的每一个季度都取自同一份新闻稿。公司在 2023 与 2024 年两次重述过分部与子线口径，逐条按「该指标最早出现的那份新闻稿」取值会把重述前后的两套基准拼在一起：分部加总会比净收入少 US$9M，Capital Access 的 ARR 会画出一个 2.4 倍的假跳升。两处都已按同一份文件取值消除。",
        # "18 个季度全部落在 US$4M 至 US$8M 之间" was the record before the fee
        # was reached back to 2016Q1; it is now read off the record.
        ("Section 31 规费的逐季数值不在业绩新闻稿里，也没有 XBRL 标记、不在 R-file 中，只存在于 10-Q 与 10-K 的 MD&A 正文表格；"
         "本页逐份解析主文档取得，各年第四季由 10-K 的全年数减去前三季得到。"
         "与合并损益表里「经纪、清算与交易所费用」一行相减后的余额，"
         f"{len(residual)} 个季度全部落在 US${min(residual):.0f}M 至 US${max(residual):.0f}M 之间，"
         "这一稳定性是该拆分成立的证据。"),
        arr_note,
        "本页不发布 Index 分部收入除以 ETP AUM 得到的「基点费率」：Index 收入还包含指数期权与期货的授权收入，两者相除得到的不是过路费率，公司自己也从不披露这个数。同理不把 ARR 与已确认收入相除 —— ARR 是合同的年化值，公司明确说明它不是预测，与收入之间没有恒等式。",
        ("每股收益序列跨越 2022 年 8 月的三比一拆股。"
         + (f"本页近{cn_count(len(labels))}季表格全部位于拆股之后，不受影响；"
            if staging["periods"][0] >= "2022Q3" else
            f"本页近{cn_count(len(labels))}季表格有几季在拆股之前，每股收益按公司重述后的口径列示；")
         + "长期序列不画每股收益，因此没有需要拼接的地方。"),
        # 「本页唯一一条可以从 2015 年直接画到 2026 年的序列」: the margin and AUM
        # charts on this page run the same span without a break.
        (f"合并净收入可以从 {staging['long']['quarters'][0][:4]} 年直接画到 {staging['long']['quarters'][-1][:4]} 年："
         f"{len(staging['long']['quarters'])} 个季度里公司始终把它定义为总收入减去交易返点与经纪清算费用这两项、且只有这两项，"
         "跨越四次分部重组数值都能对上。它在窗口内有一处未经说明的口径变动：2018 年 4 月采用 ASC 606 时公司重述了 2017 各季，"
         "全年由 US$2,428M 降为 US$2,411M，逐季幅度 US$2M 至 US$6M（不到 1%），新闻稿的收入表对此没有任何注释。"
         "本页长期序列取各季首次披露值，因此 2017 与 2018 之间存在这一处小台阶，图上未画断点标记，因为它小于线宽；在此写明。"),
    ]
    release_note = (context or {}).get("release_note")
    if release_note:
        fin = staging["financials"]
        quarter_in_year = int(period.split()[0][1])
        notes.append(fill_story(release_note, {
            "release_date": latest["release_date"],
            "bcef_now": f"US${fin['bcef'][-1]:,.0f}M",
            "bcef_ytd": f"US${sum(fin['bcef'][-quarter_in_year:]):,.0f}M",
            "bcef_prior": f"US${fin['bcef'][-2]:,.0f}M",
            "prior_quarter": quarter_words(labels[-2]),
        }))
    notes += [
        "本页不发布市场一致预期：没有可核对的、带日期的公开来源，站点规则允许发布带日期的「市场预期」对照点，但不允许凭印象填一个数。本页同样不发布评级、目标价与估值。",
        "本页只发布公司披露值、可复算的简单派生值；D 标记代表 Derived / 自算。",
        "核对抽屉最后那张「AI capex 循环」是全站共用的跨页对照块，在每一页都逐字节相同，不是对 NDAQ 的判断。它追的是四家云厂现金资本开支 → NVDA 数据中心收入 → TSM 晶圆这条链，纳斯达克不在这条链的任何一环上。把它放在这里是为了让读者在任意一页都能查到同一份上下游对照。它在折叠的抽屉里，不参与本页的论证。",
        unconnected,
        "业绩电话会文字稿仅链接官方 IR 与 SEC 托管版本，公开仓不复制原件或逐字内容。",
    ]
    return notes


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "ndaq.js"), payload, "ndaq")
    shell_dir = ROOT / "ndaq"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("NDAQ", "ndaq"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"NDAQ page: {charts} charts in {len(payload['sections'])} sections "
          f"+ {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
