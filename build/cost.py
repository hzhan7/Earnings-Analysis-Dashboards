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
first published the recent outcomes land above the range and below it about equally.
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

The second is that **the headline can be inflated at both ends, and both
inflations come back out of filed numbers**: the comp gap between reported and
adjusted is gasoline and currency, and the EPS wedge over operating income
factors exactly into a below-the-line leg and a tax leg.  Neither correction
needs an estimate.  What the full record adds is the sign: over the whole comp
record that gap has been *negative* more often than positive, so gasoline and
currency have suppressed the headline more often than they have flattered it.

Every count, quarter, date and threshold in the prose is computed from
`series/cost.json`; what belongs to one quarter (the local note's claims and
thresholds, the follow-up questions) lives in blocks stamped with that quarter
(`board.stamped_block`), and the notes carry placeholders the builder fills.

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
    cn_count,
    cn_ordinal,
    display_period,
    fill_story,
    headroom,
    headroom_exhibit,
    hyperscaler_capex_share,
    latest_block,
    minus_sign,
    number_exhibits,
    stamped_block,
    threshold_table,
    unit_text,
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


AUDIT_WORDS = {"unaudited": "未审计", "audited": "已审计"}

# The 60-day 10-K deadline for large accelerated filers first applied to
# Costco's FY2007 report; plans guided for FY2007 and earlier came out later.
PRE_DEADLINE_LAST_GUIDED_YEAR = 2007

_EN_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen "
            "fourteen fifteen sixteen seventeen eighteen nineteen").split()
_EN_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def english_number(value: int) -> str:
    """``9`` → ``'nine'``, ``36`` → ``'thirty-six'``: how the 10-Q spells basis points."""
    if value < 20:
        return _EN_ONES[value]
    tens, ones = divmod(value, 10)
    return _EN_TENS[tens] + (f"-{_EN_ONES[ones]}" if ones else "")


def fiscal_year_of(period: str) -> int:
    """Costco's fiscal year for a site quarter: the year ends near 31 August, so a
    calendar fourth quarter already belongs to the next fiscal year."""
    quarter, year = period.split()
    return int(year) + (1 if quarter == "Q4" else 0)


def fiscal_label_of(period: str) -> str:
    quarter, year = period.split()
    return f"FY{fiscal_year_of(period)} Q{int(quarter[1]) % 4 + 1}"


def moved(new: float, old: float, up: str = "升到", down: str = "降到") -> str:
    return up if new > old else (down if new < old else "持平在")


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

def recent_precisions(staging: dict) -> tuple[list[float], list[float]]:
    """The last three quarters' adjusted comp at release and at 10-Q precision.

    A fiscal fourth quarter has no 10-Q and so no whole-number reading; the three
    are the last three that have both, not simply the last three.
    """
    comp = staging["comparable_sales_pct"]
    both = [i for i, value in enumerate(comp["filed_integer_adjusted_total_pct"]) if value is not None][-3:]
    return ([comp["adjusted_total_pct"][i] for i in both],
            [comp["filed_integer_adjusted_total_pct"][i] for i in both])


def precision_contrast(release: list[float], filed: list[float]) -> tuple[str, str]:
    """How each precision reads: the whole-number one can look like a trend that
    the decimal one does not have. Computed, so a quarter that really moves stops
    being called flat."""
    flat = max(release) - min(release) <= 0.5
    rising = filed[-1] > filed[0] and all(b >= a for a, b in zip(filed, filed[1:]))
    falling = filed[-1] < filed[0] and all(b <= a for a, b in zip(filed, filed[1:]))
    filed_reads = "读起来像在加速" if rising else ("读起来像在减速" if falling else "读起来没有方向")
    release_reads = "是一条平线" if flat else f"从 {release[0]:.1f}% 走到 {release[-1]:.1f}%"
    return filed_reads, release_reads


def resolution_note(staging: dict) -> str:
    release, filed = recent_precisions(staging)
    filed_reads, release_reads = precision_contrast(release, filed)
    return (
        f"<b>这条序列只有在新闻稿的精度上才存在。</b>同样这{cn_count(len(release))}个季度，"
        "10-Q 印出来的调整后合并 comp "
        f"是 {'、'.join(f'{v:.0f}%' for v in filed)}，{filed_reads}；"
        f"新闻稿的一位小数是 {'、'.join(f'{v:.1f}%' for v in release)}，{release_reads}。"
        "本页一律取新闻稿那一版，并在核对表里同时列出 10-Q 的整数版，"
        "好让读者看见这个差别是精度而不是数据。"
    )


def resolution_recent(staging: dict) -> str:
    release, filed = recent_precisions(staging)
    filed_reads, release_reads = precision_contrast(release, filed)
    return (f"最近{cn_count(len(release))}个季度的调整后合并 comp 在新闻稿是 "
            f"{'、'.join(f'{v:.1f}%' for v in release)}，在 10-Q 是 "
            f"{'、'.join(f'{v:.0f}%' for v in filed)} —— 前者{release_reads}，后者{filed_reads}。")

# ── thresholds: what a local analysis set, read back from the series ────────
#
# Both threshold blocks (`prior_kpi_settlement`, `next_kpi`) carry only what the
# analysis wrote -- metric, direction, threshold, the sentence it came from --
# plus a `reads` key naming the series its reading comes from. No reading is
# typed: this quarter's value is taken from the series here. So a roll moves
# last quarter's `next_kpi.quantified` into `prior_kpi_settlement` as it stood,
# writes the new analysis into `next_kpi`, and no code changes (CLAUDE.md §9).

def quarter_order(label: str) -> tuple[int, int]:
    """``'Q2 2026'`` / ``"Q2'26"`` / ``'2026Q2'`` → ``(2026, 2)``."""
    quarter, year = display_period(label).split()
    return int(year), int(quarter[1])


def quarters_between(first: str, last: str) -> list[str]:
    """The quarters strictly after ``first`` up to and including ``last``."""
    year, quarter = quarter_order(first)
    out = []
    while (year, quarter) < quarter_order(last):
        quarter += 1
        if quarter == 5:
            year, quarter = year + 1, 1
        out.append(f"Q{quarter} {year}")
    return out


# The series every threshold may read, one entry per `reads` value. A threshold
# naming anything else stops the build rather than publishing a line with no
# history behind it.
KPI_READS = ("adjusted_comp", "digital_comp", "renewal_us", "renewal_ww",
             "renewal_us_change_bp", "renewal_ww_change_bp", "executive_share",
             "executive_yoy", "core_on_core", "us_traffic")


def kpi_history(staging: dict, reads: str) -> tuple[list[str], list[float | None], dict]:
    """(xlabels, values, spec) of one tracked metric, ending at this quarter."""
    hist = staging["comp_history_pct"]
    mem = staging["membership"]
    deck = staging["supplement"]
    core = staging["core_on_core"]
    start = mem["renewal_decimal_from_index"]
    hist_labels = [compact_period(period) for period in hist["periods"]]
    mem_labels = [compact_period(period) for period in mem["periods"]]
    deck_labels = [compact_period(period) for period in deck["periods"]]
    us, world = mem["renewal_rate_us_canada_pct"], mem["renewal_rate_worldwide_pct"]
    executive, paid = deck["executive_members_mm"], deck["paid_members_mm"]
    digital, names = hist["digital_reported_pct"], hist["digital_metric_name"]

    def change_bp(values: list[float]) -> list[int]:
        # A change needs two one-decimal readings, so it starts one quarter after
        # the first of them: across the whole-number era it would be a staircase.
        return [round((values[i] - values[i - 1]) * 100) for i in range(start + 1, len(values))]

    if reads == "adjusted_comp":
        return hist_labels, hist["adjusted_total_pct"], {
            "name": "调整后合并 comp（剔除汽油与汇率）", "short": "调整后合并 comp", "fmt": "pct1", "ylab": "%"}
    if reads == "digital_comp":
        return hist_labels, [v if n == "Digitally-Enabled" else None for v, n in zip(digital, names)], {
            "name": "数字化同店销售（digitally-enabled）", "short": "数字化同店销售", "fmt": "pct1", "ylab": "%",
            "context": [{"name": "电商同店销售（e-commerce，此前的窄口径）", "color": "GRAY",
                         "values": [v if n == "E-commerce" else None for v, n in zip(digital, names)]}]}
    if reads == "renewal_us":
        return mem_labels[start:], us[start:], {
            "name": "美加续费率", "short": "美加", "fmt": "pct1", "ylab": "%"}
    if reads == "renewal_ww":
        return mem_labels[start:], world[start:], {
            "name": "全球续费率", "short": "全球", "fmt": "pct1", "ylab": "%"}
    if reads == "renewal_us_change_bp":
        return mem_labels[start + 1:], change_bp(us), {
            "name": "美加续费率季度变化", "short": "美加", "fmt": "f0", "ylab": "基点"}
    if reads == "renewal_ww_change_bp":
        return mem_labels[start + 1:], change_bp(world), {
            "name": "全球续费率季度变化", "short": "全球", "fmt": "f0", "ylab": "基点"}
    if reads == "executive_share":
        return deck_labels, [e / p * 100 for e, p in zip(executive, paid)], {
            "name": "Executive 占付费会员 D", "short": "Executive 占付费会员", "fmt": "pct1", "ylab": "%"}
    if reads == "executive_yoy":
        # Year-on-year needs the deck's fifth quarter, so the line starts there.
        return deck_labels[4:], [(executive[i] / executive[i - 4] - 1) * 100
                                 for i in range(4, len(executive))], {
            "name": "Executive 会员同比 D", "short": "Executive 会员同比", "fmt": "pct1", "ylab": "%"}
    if reads == "core_on_core":
        return [compact_period(period) for period in core["periods"]], core["change_bps"], {
            "name": "核心商品毛利率同比变动", "short": "核心商品毛利率同比", "fmt": "f0", "ylab": "基点",
            "markers": True}
    if reads == "us_traffic":
        return deck_labels, deck["comp_traffic_us_pct"], {
            "name": "美国同店客流", "short": "美国同店客流", "fmt": "pct1", "ylab": "%"}
    raise ValueError(f"a threshold reads {reads!r}, which build/cost.py does not know")


def kpi_reading(staging: dict, entry: dict) -> float:
    """This quarter's reading of one threshold, from the series and nothing else."""
    xlabels, values, _ = kpi_history(staging, entry["reads"])
    this = compact_period(staging["periods"][-1])
    if xlabels[-1] != this or values[-1] is None:
        raise ValueError(f"threshold {entry['id']!r} reads {entry['reads']!r}, "
                         f"which has no {this} reading yet")
    return values[-1]


def kpi_text(entry: dict, value: float) -> str:
    """A threshold or a reading in its own unit, with a typographic minus."""
    if entry["unit"] == "pct" and entry.get("signed"):
        return minus_sign(f"{value:+.1f}%")
    if entry["unit"] == "bps" and value == 0:
        return "0bp"
    return minus_sign(unit_text(entry["unit"], value))


def crossed(entry: dict, value: float) -> bool:
    """On the wrong side of the line; a line the analysis wrote as「≤ X」breaks at X."""
    margin = headroom(entry["direction"], entry["threshold"], value)
    return margin < 0 or (margin == 0 and bool(entry.get("breach_on_equal")))


def second_line_hit(entry: dict, value: float) -> bool | None:
    """Whether the analysis's second, harsher line (减仓 / 警示 / 跟踪) was hit."""
    line = entry.get("downside")
    if not line:
        return None
    if entry["direction"] == "up":
        return value < line["value"] or (value == line["value"] and bool(line.get("inclusive")))
    return value > line["value"] or (value == line["value"] and bool(line.get("inclusive")))


def breach_run(staging: dict, entry: dict) -> int:
    """How many readings in a row, up to this one, sit on the wrong side of the line."""
    run = 0
    for value in reversed(kpi_history(staging, entry["reads"])[1]):
        if value is None or not crossed(entry, value):
            break
        run += 1
    return run


def kpi_groups(entries: list[dict]) -> list[list[dict]]:
    """Entries drawn on one chart: those sharing a `chart` key, else one per `reads`."""
    groups: dict[str, list[dict]] = {}
    for entry in entries:
        if entry["reads"] not in KPI_READS:
            raise ValueError(f"threshold {entry['id']!r} reads {entry['reads']!r}, "
                             "which build/cost.py does not know")
        groups.setdefault(entry.get("chart", entry["reads"]), []).append(entry)
    return list(groups.values())


def kpi_chart(staging: dict, group: list[dict], *, word: str, title: str, ref: str,
              note: str, src_extra: str) -> dict:
    """One tracked metric (or a pair drawn together) against its threshold lines."""
    xlabels = None
    series = []
    fmt = ylab = None
    markers = False
    colours = iter(("NAVY", "MBLUE", "BLUE"))
    for reads in dict.fromkeys(entry["reads"] for entry in group):
        labels, values, spec = kpi_history(staging, reads)
        if xlabels is None:
            xlabels, fmt, ylab = labels, spec["fmt"], spec["ylab"]
        elif labels != xlabels:
            raise ValueError(f"chart {ref}: {reads!r} is not on the same axis as the rest of its group")
        markers = markers or bool(spec.get("markers"))
        series.append({"name": spec["name"], "values": rounded(values), "color": next(colours)})
        for context in spec.get("context", []):
            series.append({"name": context["name"], "values": rounded(context["values"]),
                           "color": context["color"]})
    drawn = set()
    # The harsher lines are drawn only when the chart has a single threshold:
    # two thresholds with two harsher lines each is four flat lines, and the
    # reader can no longer tell which pair belongs together. The sentences under
    # the chart still name every one of them.
    single = len({entry["threshold"] for entry in group}) == 1
    for entry in group:
        side = "上方" if entry["direction"] == "up" else "下方"
        if entry["threshold"] not in drawn:
            drawn.add(entry["threshold"])
            series.append({"name": f"{word} {kpi_text(entry, entry['threshold'])}（安全侧在{side}）",
                           "values": [entry["threshold"]] * len(xlabels), "color": "RED"})
        for key in ("downside", "upside"):
            line = entry.get(key)
            if single and line and line["value"] not in drawn:
                drawn.add(line["value"])
                series.append({"name": f"{line['name']} {kpi_text(entry, line['value'])}",
                               "values": [line["value"]] * len(xlabels), "color": "GOLD"})
    chart = {
        "ref": ref,
        "kind": "lines",
        "title": title,
        "xlabels": xlabels,
        "series": series,
        "fmt": fmt, "yfmt": fmt, "label_fmt": fmt, "end_label": True,
        "ylab": ylab,
        "note": note,
        "src_extra": src_extra,
    }
    if markers:
        chart["markers"] = True
    if len(xlabels) > 16:
        chart["xstep"] = LONG_STEP
    return chart


def kpi_series_note(staging: dict, reads: str, local_note: dict | None) -> str:
    """What a reader needs to know about the series under a threshold line."""
    hist = staging["comp_history_pct"]
    mem = staging["membership"]
    start = mem["renewal_decimal_from_index"]
    if reads == "adjusted_comp":
        adjusted_filed = [v for v in hist["adjusted_total_pct"] if v is not None]
        asc606 = sum(1 for v in hist["adjusted_total_pct"] if v is None)
        recent_mean = sum(hist["adjusted_total_pct"][-4:]) / 4
        claim = local_note.get("structural_comp_claim_pct") if local_note else None
        return ("<b>这条线的窗口是选出来的，理由要说清楚：</b>公司从 FY2013 起就在披露"
                "剔除汽油的口径，但 FY2019 那四个季度的「Adjusted」还额外剔除了 ASC 606 收入准则变更，"
                f"是同一个标签下的另一个口径；本图因此把那{cn_count(asc606)}季留空，"
                "其余每一季都是同一个「剔除汽油价格与汇率」的定义。"
                f"窗口内区间 {min(adjusted_filed):.1f}% 到 {max(adjusted_filed):.1f}%，"
                + (f"所以「结构性 {claim:.1f}%」这句话描述的是最近四个季度，不是这家公司的常态。"
                   if claim is not None and abs(recent_mean - claim) <= 0.3 and claim < max(adjusted_filed)
                   else "")
                + resolution_note(staging))
    if reads in ("renewal_us", "renewal_ww", "renewal_us_change_bp", "renewal_ww_change_bp"):
        return ("<b>这条线为什么不从更早画起：</b>"
                f"Costco 在 {fiscal_label_of(mem['periods'][start])} 之前把续费率四舍五入到"
                "整数百分点（91%、92%、93%），之后才给到一位小数。"
                "把两段接在一起会把四舍五入画成一段台阶式的「趋势」，"
                + ("所以季度变化从有两个一位小数读数的那一季起算。" if reads.endswith("_bp") else
                   "所以本图从有小数的那一季起画。")
                + "续费率是滚动口径：公司写明它统计的是报告日前第 7 到第 18 个月到期的会员。")
    if reads in ("executive_share", "executive_yoy"):
        return ("<b>公司从不印这两个比率</b>，但它印它们的组成部分 —— Executive 会员数与付费会员数"
                "并排放在同一张表里，所以占比与同比都是申报值相除（D）。" + deck_source(staging))
    if reads == "digital_comp":
        brk = hist["digital_break_index"]
        first = next(i for i, name in enumerate(hist["digital_metric_name"]) if name is not None)
        return ("<b>深蓝与灰色是两个口径，不接成一条线：</b>"
                f"公司自 {hist['fiscal_labels'][brk]} 起把 e-commerce comp 换成更宽的 digitally-enabled comp"
                "（10-Q 写明新口径包括经数字设备发起、由仓库或配送中心履约的销售与 Costco Travel），"
                "新闻稿没有重述历史。阈值设在新口径上，灰线只作背景。"
                f"电商 comp 最早印在 {hist['fiscal_labels'][first]} 的新闻稿里，更早的季度没有这一行。")
    if reads == "core_on_core":
        return core_on_core_note(staging)
    if reads == "us_traffic":
        deck = staging["supplement"]
        return ("补充材料的 Segment Reporting 页按美国、加拿大、其他国际给同店客流与客单，"
                f"本季美国 {deck['comp_traffic_us_pct'][-1]:+.1f}%、全公司 {deck['comp_traffic_pct'][-1]:+.1f}%。"
                "汽油站的客流不计入这个数（公司在 FY2026 Q3 电话会上说明），所以它是仓内的购物频次。"
                + deck_source(staging))
    raise ValueError(reads)


def kpi_source(staging: dict, reads: str) -> str:
    return {
        "adjusted_comp": SOURCE_PR,
        "digital_comp": "业绩 8-K EX-99.1 新闻稿开头的同店销售表（Digitally-Enabled 一行，此前为 E-commerce 一行）。",
        "renewal_us": "各季 10-Q 与各年 10-K 的 MD&A 正文句子；公司披露值。",
        "renewal_ww": "各季 10-Q 与各年 10-K 的 MD&A 正文句子；公司披露值。",
        "renewal_us_change_bp": "各季 10-Q 与各年 10-K 的 MD&A 正文句子；季度变化为相邻两季相减（D）。",
        "renewal_ww_change_bp": "各季 10-Q 与各年 10-K 的 MD&A 正文句子；季度变化为相邻两季相减（D）。",
        "executive_share": deck_source(staging),
        "executive_yoy": deck_source(staging),
        "core_on_core": ("各季 10-Q 的 MD&A 正文句子；数值为公司披露的基点变动，"
                         "自 FY2024 Q3 起同一个数字也出现在业绩 8-K 的 EX-99.2 里，两者逐季一致。"),
        "us_traffic": "业绩 8-K EX-99.2 补充材料 Segment Reporting 页的 Traffic 一行（US 列）。",
    }[reads]


def core_on_core_note(staging: dict) -> str:
    """The core-merchandise margin line: where it comes from and what its holes are."""
    core = staging["core_on_core"]
    deck = staging["supplement"]
    core_bps = core["change_bps"]
    # A fiscal fourth quarter has no 10-Q sentence, but the supplemental deck
    # prints one from FY2024 Q3 on, so some of the annual holes are filled and
    # some are not. Count both rather than describing the axis from memory.
    q4_slots = sum(1 for period in core["periods"] if period.startswith("Q3 "))
    deck_filled = sum(1 for period, source in zip(core["periods"], core["value_source"])
                      if period.startswith("Q3 ") and source)
    filed_core = [v for v in core_bps if v is not None]
    negative_core = sum(1 for v in filed_core if v < 0)
    # The 10-Q sentence the reading comes from, rebuilt from the last quarter
    # that has one: the company writes the same sentence every quarter.
    tenq = [i for i, source in enumerate(core["value_source"]) if source == "10-Q/10-K MD&A prose"]
    quoted = core_bps[tenq[-1]]
    quote = ("「The gross margin in core merchandise categories, when expressed as a "
             "percentage of core merchandise sales (rather than total net sales), "
             f"{'decreased' if quoted < 0 else 'increased'} {english_number(abs(quoted))} "
             f"basis point{'' if abs(quoted) == 1 else 's'}.」")
    deck_core = dict(zip(deck["periods"], deck["core_on_core_bps"]))
    overlap = [period for period, source in zip(core["periods"], core["value_source"])
               if source == "10-Q/10-K MD&A prose" and period in deck_core]
    overlap_equal = all(deck_core[period] == core_bps[core["periods"].index(period)] for period in overlap)
    return ("<b>这就是管理层在电话会上说的「core on core」，只不过是申报版本。</b>"
            "10-Q 的 MD&A 每季用同一句话给它："
            + quote +
            "它把仓内附属与其他业务的销售占比变化和它们自己的毛利率都排除掉，"
            "所以它是这家公司剔除汽油之后最干净的一条商品毛利率读数。"
            f"{len(filed_core)} 个有披露的季度里 {negative_core} 季为负。"
            "<b>点与点之间的空格是会计 Q4</b>：它没有 10-Q，而 10-K 讲的是整个财年，"
            "从不单说第四季度；本页不用「全年减去 36 周」去补那一格，"
            "因为那样得到的是自算值而不是披露值。"
            f"<b>但最后 {deck_filled} 个会计 Q4 是有值的</b> —— 自 FY2024 Q3 起的 "
            "EX-99.2 补充材料按季给这个数，第四季度也给，所以窗口里 "
            f"{q4_slots} 个会计 Q4 有 {deck_filled} 个由它填上、其余 "
            f"{q4_slots - deck_filled} 个仍是空的。"
            f"这{cn_count(deck_filled)}格的来源比其余的弱，值得说明：补充材料只印「Core on Core Sales」这一行，"
            "既不定义它，也不说它属于毛利率还是 SG&A 那张桥；而 10-Q 的那句话自带定义。"
            + (f"两者在{cn_count(len(overlap))}个重叠季度里逐季相同，"
               f"这是本页愿意用它补那{cn_count(deck_filled)}格的理由。"
               if overlap_equal else
               f"两者在{cn_count(len(overlap))}个重叠季度里并不逐季相同，本页仍只在 10-Q 缺席时用它。"))


def kpi_line_words(staging: dict, entry: dict, value: float, *, word: str) -> str:
    """One threshold's sentence: the line, this quarter's reading, and the harsher line."""
    up = entry["direction"] == "up"
    margin = headroom(entry["direction"], entry["threshold"], value)
    breach = crossed(entry, value)
    text = (f"{word}「{entry['metric']}」{'不低于' if up else '不高于'} {kpi_text(entry, entry['threshold'])}"
            f"{'（等于即越线）' if entry.get('breach_on_equal') else ''}；"
            f"本季 {kpi_text(entry, value)}，{'越线' if breach else '守住'}（余量 {minus_sign(f'{margin:+.1f}')}%）")
    need = entry.get("consecutive", 1)
    if need > 1:
        run = breach_run(staging, entry)
        text += (f"；报告要的是连续{cn_count(need)}季越线才算触发，"
                 + (f"本季已是连续第{cn_ordinal(run)}季，触发" if run >= need else
                    f"本季是连续第{cn_ordinal(run)}季，还不够" if run else "本季没有越线"))
    line = entry.get("downside")
    if line:
        hit = second_line_hit(entry, value)
        text += (f"；更严的那条是 {kpi_text(entry, line['value'])}（{line['name']}），本季"
                 + ("已经碰到" if hit else "没有碰到"))
    if entry.get("remark"):
        text += "；" + entry["remark"]
    extra = entry.get("upside")
    if extra:
        text += (f"；另一侧的 {kpi_text(entry, extra['value'])} 是报告写的{extra['name']}线，本季"
                 + ("已经回到它上面" if (value >= extra["value"] if up else value <= extra["value"])
                    else "还没有回到它上面"))
    return text + "。"


def kpi_count_words(entry: dict, values: list[float | None], spec: dict) -> str:
    """How often the metric's own record sat on the wrong side of this line."""
    readings = [value for value in values if value is not None]
    below = sum(1 for value in readings if crossed(entry, value))
    name = spec["short"] + (" " if spec["short"][-1].isascii() else "")
    return (f"{name}一共 {len(readings)} 个读数，落在这条线"
            f"{'下方' if entry['direction'] == 'up' else '上方'}的有 {below} 个。")


def closure_counts(closure: dict) -> list[int]:
    """The count per verdict, from the block's own items; a verdict that is not a label stops the build."""
    labels = closure["labels"]
    unknown = sorted({item["verdict"] for item in closure["items"]} - set(labels))
    if unknown:
        raise ValueError(f"`followup_closure` items carry verdicts that are not labels: {unknown}")
    return [sum(1 for item in closure["items"] if item["verdict"] == label) for label in labels]


def closure_exhibit(closure: dict, values: dict) -> dict:
    """Section one (a): the previous analysis's follow-up questions, judged in this one's section 0."""
    counts = closure_counts(closure)
    items = closure["items"]
    groups = [(label, [i for i, item in enumerate(items, 1) if item["verdict"] == label])
              for label in closure["labels"]]
    return {
        "ref": "EX_CLOSURE",
        "kind": "bars_labeled",
        "title": (f"上季 {len(items)} 条待验证问题："
                  + "、".join(f"{count} 条{label}" for label, count in zip(closure["labels"], counts))),
        "xlabels": list(closure["labels"]),
        "values": counts,
        "legend": "问题条数",
        "fmt": "f0", "yfmt": "f0", "label_fmt": "f0",
        "ylab": "条",
        "note": ("<b>归类规则：</b>" + fill_story(closure["rule"], values)
                 + "逐条是 —— "
                 + "；".join(f"{label}：" + "、".join(f"#{i}「{items[i - 1]['short']}」" for i in numbers)
                            for label, numbers in groups if numbers)
                 + "。" + fill_story(closure.get("reading", ""), values)),
        "src_extra": (f"问题清单来自上一份报告（{closure['set_in_file']}）文末的 Follow-up Questions；"
                      f"判定照录本季报告（{closure['closed_in']}）第 0 节，本页不改判；"
                      "每条判定所对应的申报读数列在核对抽屉。"),
    }


def story_values(staging: dict) -> dict[str, str]:
    """Numbers a one-quarter sentence may name, computed so the sentence cannot drift.

    The follow-up items and the thresholds' readings are written into the
    series file because they belong to one quarter; any figure they mention
    that the series also carries is a placeholder filled from here
    (`board.fill_story`), and a name missing from here stops the build.
    """
    mem = staging["membership"]
    deck = staging["supplement"]
    hist = staging["comp_history_pct"]
    est = staging["warehouse_estimate"]
    ann = staging["annual"]
    us, world = mem["renewal_rate_us_canada_pct"], mem["renewal_rate_worldwide_pct"]
    executive, paid = deck["executive_members_mm"], deck["paid_members_mm"]
    adjusted = hist["adjusted_total_pct"]
    bridge = staging["eps_growth_bridge_pct"]
    start = mem["renewal_decimal_from_index"]

    def pct(value: float) -> str:
        return minus_sign(f"{value:+.1f}%")

    def change(values: list[float]) -> str:
        if len(values) < start + 2:
            return "—"
        moved_by = round((values[-1] - values[-2]) * 100)
        return "0bp" if moved_by == 0 else minus_sign(f"{moved_by:+d}bp")

    return {
        "renewal_us": f"{us[-1]:.1f}%", "renewal_us_prev": f"{us[-2]:.1f}%",
        "renewal_ww": f"{world[-1]:.1f}%", "renewal_ww_prev": f"{world[-2]:.1f}%",
        "renewal_us_change": change(us), "renewal_ww_change": change(world),
        "eps_wedge": pct(bridge["below_the_line_leg_pct"][-1] + bridge["tax_leg_pct"][-1]),
        "executive_mm": f"{executive[-1]:.1f}MM", "paid_mm": f"{paid[-1]:.1f}MM",
        "executive_share": f"{executive[-1] / paid[-1] * 100:.1f}%",
        "executive_share_prev": f"{executive[-2] / paid[-2] * 100:.1f}%",
        "executive_yoy": pct((executive[-1] / executive[-5] - 1) * 100),
        "paid_yoy": pct((paid[-1] / paid[-5] - 1) * 100),
        "digital": pct(hist["digital_reported_pct"][-1]),
        "digital_prev": pct(hist["digital_reported_pct"][-2]),
        "adjusted_comp": pct(adjusted[-1]), "adjusted_comp_prev": pct(adjusted[-2]),
        "traffic": pct(deck["comp_traffic_pct"][-1]), "traffic_prev": pct(deck["comp_traffic_pct"][-2]),
        "us_traffic": pct(deck["comp_traffic_us_pct"][-1]),
        "us_traffic_prev": pct(deck["comp_traffic_us_pct"][-2]),
        "adjusted_ticket": pct(deck["adjusted_comp_ticket_pct"][-1]),
        "fy_end_estimate": f"{est['fy_end_estimate'][-1]:,}",
        "fy_end_estimate_prev": f"{est['fy_end_estimate'][-2]:,}",
        "fy_start_warehouses": f"{ann['warehouses_at_year_end'][-1]:,}",
        "net_new": f"{est['fy_end_estimate'][-1] - ann['warehouses_at_year_end'][-1]}",
        "net_new_prev": f"{est['fy_end_estimate'][-2] - ann['warehouses_at_year_end'][-1]}",
        "warehouses": f"{mem['warehouses_at_period_end'][-1]:,}",
        "fee_growth": pct(deck["membership_income_growth_pct"][-1]),
        "fee_growth_ex_fx": pct(deck["membership_income_growth_ex_fx_pct"][-1]),
        "fee_growth_prev": pct(deck["membership_income_growth_pct"][-2]),
        "fee_growth_ex_fx_prev": pct(deck["membership_income_growth_ex_fx_pct"][-2]),
    }


def settlement_blocks(staging: dict, period: str) -> tuple[bool, dict | None, dict | None]:
    """Whether this is the first local analysis, and what the previous one left open.

    Section one settles the previous analysis's follow-up questions
    (`followup_closure`) and thresholds (`prior_kpi_settlement`) before the
    company's own guidance. The first Costco analysis in the vault is the one
    `analysis_record.first_period` names; any later quarter has a previous
    analysis by construction, so a roll that leaves both blocks out would
    publish a section one that silently skipped it -- that stops the build.
    """
    record = staging.get("analysis_record") or {}
    first = display_period(record.get("first_period", "")) == display_period(period)
    closure = stamped_block(staging, "followup_closure", period)
    prior = stamped_block(staging, "prior_kpi_settlement", period)
    present = [key for key, block in (("followup_closure", closure), ("prior_kpi_settlement", prior))
               if block is not None]
    if first and present:
        raise ValueError(f"{period} is the first Costco analysis, so there is nothing for "
                         f"{', '.join(present)} to settle")
    if not first and not present:
        raise ValueError(f"{period} is not the first Costco analysis: section one must settle the "
                         "previous one -- add `followup_closure` (its section 0) and "
                         "`prior_kpi_settlement` (the previous section 8 thresholds) to the series")
    set_in = {block["set_in"] for block in (closure, prior) if block is not None}
    if len(set_in) > 1:
        raise ValueError(f"`followup_closure` and `prior_kpi_settlement` name different analyses: {sorted(set_in)}")
    if set_in and quarter_order(next(iter(set_in))) >= quarter_order(period):
        raise ValueError(f"the settlement blocks say they were set in {next(iter(set_in))!r}, "
                         f"which is not before {period!r}")
    return first, closure, prior


def group_title(staging: dict, group: list[dict], value_key: str, *, settle: bool) -> str:
    """「X：本季 A，守住上季阈值 B」 for a settlement, 「X：下季阈值 B，当前 A」 for a next line."""
    reads = list(dict.fromkeys(entry["reads"] for entry in group))
    specs = {r: kpi_history(staging, r)[2] for r in reads}
    family = group[0].get("family") or group[0]["metric"]
    by_reads = {r: next(entry for entry in group if entry["reads"] == r) for r in reads}
    if len(reads) > 1:
        now = "、".join(f"{specs[r]['short']} {kpi_text(by_reads[r], by_reads[r][value_key])}" for r in reads)
        lines = "、".join(dict.fromkeys(
            f"{specs[entry['reads']]['short']} {kpi_text(entry, entry['threshold'])}" for entry in group))
        if len({entry["threshold"] for entry in group}) == 1:
            lines = kpi_text(group[0], group[0]["threshold"])
    else:
        now = kpi_text(group[0], group[0][value_key])
        lines = " 与 ".join(dict.fromkeys(kpi_text(entry, entry["threshold"]) for entry in group))
    if not settle:
        return f"{family}：下季阈值 {lines}，当前 {now}"
    marks = ["击穿" if crossed(entry, entry[value_key]) else "守住" for entry in group]
    if len(set(marks)) == 1:
        head = f"{marks[0]}上季阈值 {lines}"
    else:
        head = "；".join(f"{entry['metric']}{mark}上季阈值 {kpi_text(entry, entry['threshold'])}"
                        for entry, mark in zip(group, marks))
    return f"{family}：本季 {now}，{head}"


def settlement_section(staging: dict, period: str, closure: dict | None, prior: dict | None,
                       local_note: dict | None, values: dict) -> tuple[list[dict], list[dict]]:
    """Section one's (a) and (b): the charts and the drawer tables that back them."""
    charts, tables = [], []
    if closure is not None:
        charts.append(closure_exhibit(closure, values))
        items = closure["items"]
        tables.append({
            "title": f"上季 {len(items)} 条待验证问题：本季报告第 0 节的判定与申报读数",
            "headers": ["#", "上季问题", "本季报告判定（原文）", "申报文件里的读数"],
            "rows": [[str(i), item["question"], item["verdict"], fill_story(item["evidence"], values)]
                     for i, item in enumerate(items, 1)],
        })
    if prior is None:
        return charts, tables

    due = [{**entry, "actual": kpi_reading(staging, entry)} for entry in prior["quantified"]]
    broken = [entry for entry in due if crossed(entry, entry["actual"])]
    harsher = [entry for entry in due if second_line_hit(entry, entry["actual"])]
    between = quarters_between(prior["set_in"], period)
    earlier = between[:-1]
    not_charted = prior.get("not_charted", [])
    overview = headroom_exhibit(
        ((f"上季 {len(due)} 条量化阈值全部守住" if not broken else
          f"上季 {len(due)} 条量化阈值：{len(due) - len(broken)} 条守住、{len(broken)} 条击穿")
         + (f"，{len(harsher)} 条碰到了更严的那条线" if harsher else "")),
        due, "actual",
        ("正值 = 仍在安全侧。阈值逐字取自上一份报告（" + prior["set_in_file"] + "）第 8 节，不是公司指引"
         + (f"；原文写的是「{prior['due_text']}」，即本站 {' 与 '.join(between)}"
            if prior.get("due_text") else "")
         + "，本节按本季读数结清"
         + (f"，逐条的历史图里同时画着 {'、'.join(earlier)} 那一季" if earlier else "")
         + "。"
         + ("越线的是 —— " + "；".join(f"{entry['metric']}：本季 {kpi_text(entry, entry['actual'])}"
                                     for entry in broken) + "。" if broken else "")
         + (f"另有{cn_count(len(not_charted))}条上季阈值不进这张图："
            + "；".join(f"{item['metric']} —— {item['verdict']}" for item in not_charted)
            + "。读数与理由见核对抽屉里的上季阈值表。" if not_charted else "")),
        ("阈值取自上一份报告（" + prior["set_in_file"] + "）第 8 节；本季读数全部由申报值得出，"
         "比率与变化为本页相除或相减（D）。"),
    )
    overview["ref"] = "EX_PRIOR_HEADROOM"
    charts.append(overview)
    for group in kpi_groups(due):
        reads = list(dict.fromkeys(entry["reads"] for entry in group))
        history = []
        for entry in group:
            xlabels, series_values, spec = kpi_history(staging, entry["reads"])
            earlier_words = [f"{label} {kpi_text(entry, value)}（{'越线' if crossed(entry, value) else '守住'}）"
                             for label, value in zip(xlabels, series_values)
                             if value is not None and display_period(label) in earlier]
            history.append(
                kpi_line_words(staging, entry, entry["actual"], word="上季阈值")
                + (f"中间没有单独报告的 {'、'.join(earlier_words)}。" if earlier_words else "")
                + kpi_count_words(entry, series_values, spec))
        # A caveat is the previous analysis's own description of the history it
        # set the line against; the readings it describes are printed beside it,
        # from the series, so the sentence carries no number of its own.
        caveat = ""
        for entry in group:
            if not entry.get("caveat"):
                continue
            xlabels, series_values, _ = kpi_history(staging, entry["reads"])
            set_label = compact_period(prior["set_in"])
            at = xlabels.index(set_label) if set_label in xlabels else None
            context = [f"{xlabels[i]} {kpi_text(entry, series_values[i])}"
                       for i in ((at - 1, at) if at else ()) if series_values[i] is not None]
            caveat = (("上一份报告写成时最近两季的读数：" + "、".join(context) + "。" if context else "")
                      + fill_story(entry["caveat"], values))
            break
        charts.append(kpi_chart(
            staging, group, word="上季阈值",
            title=group_title(staging, group, "actual", settle=True),
            ref=f"EX_PRIOR_{group[0].get('chart', group[0]['reads']).upper()}",
            note="".join(history) + caveat + kpi_series_note(staging, reads[0], local_note),
            src_extra=(kpi_source(staging, reads[0])
                       + "阈值取自上一份报告（" + prior["set_in_file"] + "）第 8 节，不是公司的任何披露。"),
        ))

    table = threshold_table(0, f"上季阈值与本季读数（原始单位；阈值来自 {prior['set_in_file']} 第 8 节）",
                            due, "actual", "本季读数")
    table["headers"] += ["判定", "上一份报告原文"]
    for row, entry in zip(table["rows"], due):
        row[2], row[3] = kpi_text(entry, entry["threshold"]), kpi_text(entry, entry["actual"])
        hit = second_line_hit(entry, entry["actual"])
        row += [("击穿" if crossed(entry, entry["actual"]) else "守住")
                + ("，碰到更严的那条线" if hit else ""), entry["quote"]]
    for item in not_charted:
        table["rows"].append([item["metric"], "—", item["threshold_text"],
                              fill_story(item["reading"], values), "—", item["verdict"], item["quote"]])
    tables.append(table)
    return charts, tables


def next_section(staging: dict, kpi: dict, local_note: dict | None,
                 values: dict) -> tuple[list[dict], dict]:
    """Section three: this analysis's section 8, the overview and one history per metric."""
    period = staging["periods"][-1]
    entries = [{**entry, "current": kpi_reading(staging, entry)} for entry in kpi["quantified"]]
    margin = {entry["id"]: headroom(entry["direction"], entry["threshold"], entry["current"])
              for entry in entries}
    broken = [entry for entry in entries if crossed(entry, entry["current"])]
    on_line = [entry for entry in entries if margin[entry["id"]] == 0 and entry not in broken]
    safe = [entry for entry in entries if margin[entry["id"]] > 0]
    closest = min(safe, key=lambda entry: margin[entry["id"]]) if safe else None
    closest_words = (f"，其余离线最近的是{closest['metric']}"
                     f"（{minus_sign(format(margin[closest['id']], '+.1f'))}%）" if closest else "")
    runs = "".join(f"{entry['metric']}要连续{cn_count(entry['consecutive'])}季越线才算触发。"
                   for entry in entries if entry.get("consecutive", 1) > 1)
    not_charted = kpi.get("not_charted", [])
    overview = headroom_exhibit(
        (f"下季 {len(entries)} 条阈值："
         + (f"{'、'.join(entry['metric'] for entry in broken)}已越线" if broken else "没有一条越线")
         + (f"，{'、'.join(entry['metric'] for entry in on_line)}正压在线上" if on_line else "")
         + closest_words),
        entries, "current",
        ("正值 = 仍在安全侧，零 = 正压在线上。阈值逐字取自本季报告（" + kpi["set_in_file"]
         + "）第 8 节，不是公司指引；每条出自哪一句列在核对抽屉的下季阈值表。"
         + runs
         + (f"关键观察指标里还有{cn_count(len(not_charted))}条不画阈值线："
            + "；".join(f"{item['metric']} —— {fill_story(item['why'], values)}" for item in not_charted)
            + "。" if not_charted else "")),
        (f"当前值全部为 {period} 的申报值或由申报值相除（D）；阈值取自本季报告第 8 节。"),
    )
    overview["ref"] = "EX_NEXT_HEADROOM"
    charts = [overview]
    for group in kpi_groups(entries):
        reads = list(dict.fromkeys(entry["reads"] for entry in group))
        words = []
        for entry in group:
            _, series_values, spec = kpi_history(staging, entry["reads"])
            words.append(kpi_line_words(staging, entry, entry["current"], word="下季阈值")
                         + kpi_count_words(entry, series_values, spec))
        charts.append(kpi_chart(
            staging, group, word="下季阈值",
            title=group_title(staging, group, "current", settle=False),
            ref=f"EX_NEXT_{group[0].get('chart', group[0]['reads']).upper()}",
            note="".join(words) + kpi_series_note(staging, reads[0], local_note),
            src_extra=(kpi_source(staging, reads[0])
                       + "阈值取自本季报告（" + kpi["set_in_file"] + "）第 8 节，不是公司的任何披露。"),
        ))
    table = threshold_table(0, f"下季阈值（原始单位；阈值来自 {kpi['set_in_file']} 第 8 节）",
                            entries, "current", "当前值")
    table["headers"] += ["本季报告原文"]
    for row, entry in zip(table["rows"], entries):
        row[2], row[3] = kpi_text(entry, entry["threshold"]), kpi_text(entry, entry["current"])
        row.append(entry["quote"])
    for item in not_charted:
        table["rows"].append([item["metric"], "—", item["threshold_text"],
                              fill_story(item["reading"], values), "—", item["quote"]])
    return charts, table


OWN_GUIDANCE = ("Costco 自己在申报文件里给的数字只有三份，都关于资本而不关于利润：10-K 每年给一次"
                "下一财年的资本开支区间与开店计划，自 2024 年 5 月起每季的 EX-99.2 还给一次财年末仓库数的估计；"
                "它从不指引收入、利润或每股收益 —— 翻遍近十二份业绩 8-K，outlook 与 guidance 这两个词"
                "只出现在前瞻性陈述的免责声明里。这三份记录放在本节最后。")


def settled_description(staging: dict, first: bool, closure: dict | None, prior: dict | None,
                        numbers: dict[str, int]) -> str:
    """Section one's lead: which analysis is being settled, and how it maps onto this page's quarters."""
    period = staging["periods"][-1]
    if first:
        return (f"本站对该公司的第一份季报分析是 {period}，没有上季留下的跟踪指标可结算；"
                "本节结算的是公司上季给出、本季到期的指引。" + OWN_GUIDANCE)
    block = closure or prior
    set_in = block["set_in"]
    released = dict(zip(staging["periods"], staging["release_dates"]))
    skipped = quarters_between(set_in, period)[:-1]
    text = (f"先结清上一份报告留下的东西，再结清公司自己的指引。上一份报告的文件名是「{block['set_in_file']}」，"
            f"正文分析的是 {fiscal_label_of(set_in)}（本站 {set_in}"
            + (f"，{released[set_in]} 发布" if set_in in released else "") + "）")
    if skipped:
        text += ("；" + "、".join(f"{quarter}（{fiscal_label_of(quarter)}）" for quarter in skipped)
                 + "没有单独写报告，所以本季报告一次性结清它留下的东西")
    text += "。"
    if closure is not None:
        text += (f"它文末的 {len(closure['items'])} 条待验证问题由本季报告第 0 节逐条判定"
                 f"（Exhibit {numbers['EX_CLOSURE']}，判定照录原文）；")
    if prior is not None:
        quarters = quarters_between(set_in, period)
        text += (f"它第 8 节的量化阈值（Exhibit {numbers['EX_PRIOR_HEADROOM']} 起）"
                 + (f"原文写的是「{prior['due_text']}」，即本站 {' 与 '.join(quarters)}，" if prior.get("due_text") else "")
                 + f"本节按本季读数结清" + (f"，历史图里同时画着 {'、'.join(skipped)} 那一季" if skipped else "")
                 + "。")
    return text + OWN_GUIDANCE


def next_description(kpi: dict, next_ex: list[dict], values: dict) -> str:
    """Section three's lead: the analysis's section 8, what is drawn and what is only named."""
    quantified = kpi["quantified"]
    not_charted = kpi.get("not_charted", [])
    return (f"本季报告（{kpi['set_in_file']}）第 8 节「关键观察指标」里能按申报数跟踪的 {len(quantified)} 条阈值："
            "先看当前值离每条线还有多远（统一用「距阈值余量」口径），再逐条看它的历史；阈值与原文见核对抽屉。"
            + (f"另有{cn_count(len(not_charted))}条不画阈值线：" + "；".join(
                f"{item['metric']} —— {fill_story(item['why'], values)}" for item in not_charted) + "。"
               if not_charted else ""))


# ── section one: the two records Costco actually files ──────────────────────
def latest_numeric_plan(record: dict) -> int:
    """Index of the newest guided year the 10-K gave a dollar range for."""
    return max(i for i, low in enumerate(record["guided_low_usd_m"]) if low is not None)


def capex_timing(staging: dict) -> str:
    lag = staging["capex_guidance"]["lag_days_into_guided_year"][-1]
    return f"该财年<b>开始后约{cn_count(round(lag / 7))}周</b>"


def capex_source(staging: dict) -> str:
    record = staging["capex_guidance"]
    at = latest_numeric_plan(record)
    year = record["guided_fiscal_years"][at]
    spent = record["actual_capex_usd_m"][record["guided_fiscal_years"].index(year - 1)]
    return (
        "指引取自各年 10-K 的 Liquidity and Capital Resources 里那段 Capital Expenditure Plans，"
        f"句式历年一致：「In {year - 1}, we spent ${spent:,.0f} on capital expenditures, and it is our current "
        f"intention to spend {record['figure_as_printed'][at]} during fiscal {year}.」"
        "实际值取自被指引那一年自己那份 10-K 现金流量表的 Additions to property and equipment。"
    )


def window_note(staging: dict) -> str:
    full = staging["capex_record_full"]
    record = staging["capex_guidance"]
    at = latest_numeric_plan(record)
    span = len(full["guided_fiscal_years"])
    return (
        "<b>这张图的窗口比记录短，理由是刻度而不是取数。</b>"
        f"完整记录从 FY{full['guided_fiscal_years'][0]} 起 —— "
        "EDGAR 上最早那份 10-K 就带着这段话 —— 但那一年的计划是 "
        f"US${full['guided_low_usd_m'][0]:,.0f}–{full['guided_high_usd_m'][0]:,.0f}M，"
        f"而 FY{record['guided_fiscal_years'][at]} 的是 "
        f"US${record['guided_low_usd_m'][at]:,.0f}–{record['guided_high_usd_m'][at]:,.0f}M；"
        f"一条线性纵轴放不下{cn_count(round(span, -1))}年而不把早年的色块压成一根发丝。"
        "<b>整段记录由下一张无量纲的偏离图承载</b>，那是本站 NVIDIA 页处理同一个问题的办法。"
        "另外，FY2007 之前公司把计划拆成美加与国际两笔分别给出，本页取两笔之和（D）。"
    )


def capex_lag_note(staging: dict) -> str:
    recent = staging["capex_guidance"]["lag_days_into_guided_year"]
    full = staging["capex_record_full"]
    early = [lag for year, lag in zip(full["guided_fiscal_years"], full["lag_days_into_guided_year"])
             if year <= PRE_DEADLINE_LAST_GUIDED_YEAR]
    every = full["lag_days_into_guided_year"]
    return (
        "<b>先读这两句，再读命中率。</b>其一，10-K 申报时，它所指引的那个财年<b>已经开始了</b> —— "
        "Costco 的财年在 9 月初开始，而年报在 10 月甚至更晚才申报。"
        f"近{cn_count(len(recent))}年是第 {min(recent)} 到 {max(recent)} 天，"
        f"更早的年份更晚：FY{PRE_DEADLINE_LAST_GUIDED_YEAR} 之前的年报要到被指引财年的第 "
        f"{min(early)} 到 {max(early)} 天才出来，"
        "因为那时还没有大型加速申报人的 60 天期限。"
        f"整段记录的区间是第 {min(every)} 到 {max(every)} 天。"
        "其二，它<b>不是只发一次</b>：每一季的 10-Q 都会把同一段重写一遍，"
        "所以每个财年都有一版年初计划和最多三次修订"
        f"（本页只回溯到 FY{full['final_vintage_from_fiscal_year']}）。"
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
    # What the qualitative year actually spent, against the year before it.
    qualitative_growth = [
        (labels[i], (actual[i] / actual[i - 1] - 1) * 100)
        for i, flag in enumerate(record["is_qualitative"])
        if flag and i > 0 and actual[i] is not None and actual[i - 1]]
    pending = [labels[i] for i, a in enumerate(actual) if a is None]
    timing = capex_timing(staging)
    lag_note = capex_lag_note(staging)

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
        "note": (f"色块是{timing}公司在 10-K 里给出的下一财年资本开支区间，"
                 "菱形是那一年实际花掉的钱。"
                 "<b>本站其他每一份指引记录都是单边的</b> —— 要么几乎从不跌破下限，"
                 f"要么几乎每期穿出上限；这一段 {len(finished)} 年里 {len(below)} 年低于下限、"
                 f"{len(above)} 年高于上限，"
                 + ("两边一样多。" if len(below) == len(above) else
                    ("两边差不多。" if abs(len(below) - len(above)) <= 1 else
                     f"{'低于' if len(below) > len(above) else '高于'}的一侧更多。"))
                 +
                 "<b>但这只是最近这一段。</b>"
                 f"把窗口拉到 FY{full_record['guided_fiscal_years'][0]} 起的完整记录，"
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
                    "「a similar amount」，是一句话不是一个区间，本页不把词换算成数"
                    + "".join(f"；那年实际花的钱比上一年{'多' if growth >= 0 else '少'} "
                              f"{abs(growth):.1f}%" for _, growth in qualitative_growth)
                    + "。" if qualitative else "")
                 + (f"最后一格 {pending[-1]} 只有区间，实际值待披露。" if pending else "")
                 + window_note(staging)
                 + lag_note
                 + "纵轴不自 0 起，但没有任何点被截掉。"),
        "src_extra": capex_source(staging),
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
    open_mean = sum(open_abs_both) / len(open_abs_both)
    final_mean = sum(final_abs_both) / len(final_abs_both)
    # "Both halves hit between a fifth and a sixth" is a claim about two rates;
    # it is printed only while the rates say it.
    rate_band = (100 / 6 - 1e-9 <= min(early_rate, late_rate)
                 and max(early_rate, late_rate) <= 20 + 1e-9)

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
                 f"<b>把上一张图的{cn_count(len(finished))}年放回{cn_count(len(settled))}年里，"
                 "那份对称就不见了：</b>"
                 f"整段记录是 {full_tally['BELOW']} 年低于区间对 {full_tally['ABOVE']} 年高于区间；"
                 f"FY{SPLIT_YEAR} 之前的 {early['total']} 年是 {early['BELOW']} 比 {early['ABOVE']}，"
                 f"之后的 {late['total']} 年才是 {late['BELOW']} 比 {late['ABOVE']} 的对半。"
                 "所以「两边一样多」是最近这一段窗口的性质，不是这家公司的性质 —— "
                 "本页上一张图因此把窗口写进了标题。"
                 "<b>相对稳的是另一个数：区间被打中的频率。</b>"
                 f"在以区间形式给出的年度里，前一段 {early_ranged} 年中了 {early_hits} 次"
                 f"（{early_rate:.0f}%），后一段 {late_ranged} 年中了 {late_hits} 次"
                 f"（{late_rate:.0f}%）"
                 + ("—— 两段都在五分之一到六分之一之间。变的主要是错的方向，不是错的频率。"
                    if rate_band else "。")
                 +
                 f"（{'、'.join(points)} 公司给的是单点而不是区间，没有宽度可落，"
                 "只可能高于或低于，不计入这个频率；把它们算成「没中」正是让两段看起来一模一样的做法。）"
                 "<b>而方向是成段走的，不是逐年抖动：</b>"
                 f"FY{run_above[0]} 到 FY{run_above[-1]} 连续 {len(run_above)} 年高于区间，"
                 f"FY{run_none[0]} 到 FY{run_none[-1]} 的 {len(run_none)} 年里一次都没有高过。"
                 f"<b>第二根柱只有近{cn_count(len(both))}年有：</b>10-Q 里的季度修订本页只回溯到 "
                 f"FY{full['final_vintage_from_fiscal_year']}，更早的年度没有采集，"
                 "所以左边那一段只有年初计划这一条腿。"
                 f"在两条腿都有的那 {len(both)} 年里，修订把平均绝对偏离从 "
                 f"{open_mean:.1f}% 收到 "
                 f"{final_mean:.1f}%，"
                 + ("只压掉不到一半 —— " if final_mean > open_mean / 2 else "压掉了一半以上 —— ")
                 + "本站另外两页按年指引的公司（穆迪、标普全球）同一口径下能压到五分之一甚至七分之一。"
                 f"（整段三十年对年初计划的平均绝对偏离是 "
                 f"{sum(open_abs_all) / len(open_abs_all):.1f}%，与上面那个数不是同一批年份，不要并排比。）"
                 f"整段记录里偏离最大的一次是 "
                 f"{full_labels[dev_open.index(biggest)]} 的 {biggest:+.1f}%。"
                 + lag_note),
        "src_extra": (capex_source(staging)
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
    # The wording of the plan, run by run; the range era before the first year
    # on this chart is one more form, so the count of changes is the number of runs.
    runs: list[list] = []
    for qualifier in plan["planned_qualifier"]:
        if runs and runs[-1][0] == qualifier:
            runs[-1][1] += 1
        else:
            runs.append([qualifier, 1])
    if [q for q, _ in runs] == ["up to", "approximately", "approximately up to", "up to"]:
        wording = ("同一句话的限定词换过" + cn_count(len(runs)) + "次 —— 早年是区间（「27 到 30 家」），"
                   "后来是「up to N」，中间" + cn_count(runs[1][1]) + "年是「approximately N」，再后来是"
                   "「approximately up to N」，近年又回到「up to N」。")
    else:
        wording = ("同一句话的限定词换过" + cn_count(len(runs)) + "次 —— 早年是区间（「27 到 30 家」），此后依次是"
                   + "、".join(f"「{q} N」（{cn_count(n)}年）" for q, n in runs) + "。")
    additional = [year for year, flag in zip(plan["guided_fiscal_years"], plan["relocations_are_additional"])
                  if flag]
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
                 + wording +
                 "所以这张图比的是「计划的家数」与「实际的家数」这一个量，"
                 "不是「有没有守住一个承诺」—— 一个点估计开不满和一个上限没顶到，不是同一件事。"
                 "<b>搬迁那一项的口径也翻过面：</b>"
                 f"FY{additional[0]} 到 FY{additional[-1]} 的计划把搬迁写成计划之外的"
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
                 + capex_lag_note(staging)),
        "src_extra": ("与资本开支计划取自各年 10-K 的同一段；"
                      "实际开店数取自被指引那一年自己那份 10-K 的同一句话，"
                      "计划口径统一为「含搬迁的开店总数」，为本页自算（D）。"),
    }


def deck_source(staging: dict) -> str:
    return (
        "取自各季业绩 8-K 的 EX-99.2「Supplemental Information」补充材料。"
        "这份材料自 2024-05-30（FY2024 Q3 业绩）起随每份业绩 8-K 一并 furnish，"
        f"共 {len(staging['supplement']['periods'])} 期，"
        "在此之前这些按季的数字没有进过申报文件（此前多半只在电话会上口头给出），"
        "因此本页的这条序列从那一季开始，不向前回补。"
    )


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    return [f"Revenue ${staging['financials']['total_revenue_usd_m'][-1] / 1000:.1f}B",
            f"调整后 comp {staging['comparable_sales_pct']['adjusted_total_pct'][-1]:+.1f}%",
            "会员费/营业利润 "
            f"{staging['annual']['membership_fee_share_of_operating_income_pct'][-1]:.0f}%"]


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    latest = latest_block(staging, period=periods[-1], period_end=staging["period_ends"][-1],
                          release_date=staging["release_dates"][-1])
    first_analysis, followup, prior_block = settlement_blocks(staging, periods[-1])
    next_block = stamped_block(staging, "next_kpi", periods[-1])
    if next_block is None:
        raise ValueError("series block `next_kpi` is required every quarter: section three is "
                         "this quarter's local analysis's section 8")
    local_note = stamped_block(staging, "local_note", periods[-1])
    values = story_values(staging)
    capex_full = staging["capex_record_full"]
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

    # Four quarters (FY2019, calendar Q4 2018 -- Q3 2019) have no adjusted comp
    # on this series' basis: Costco's printed "Adjusted" figure those quarters
    # also strips the ASC 606 transition, which every other quarter's does not.
    # The as-printed values are kept in the series file under
    # `asc606_era_as_disclosed`; they are not spliced in here, so any aggregate
    # over the adjusted line has to skip them rather than crash on them.
    adjusted_filed = [v for v in staging["comp_history_pct"]["adjusted_total_pct"]
                      if v is not None]
    asc606 = [period for period, value in zip(hist["periods"], hist["adjusted_total_pct"])
              if value is None]

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
    # Section one settles in the order the four-part format fixes: what the
    # previous local analysis left open first, then the company's own guidance
    # record -- the capital plan, the opening plan and the year-end store count.
    company_ex = list(capex_ex) + [warehouse_plan_chart(staging)]

    # ── section one (a)(b): what the previous local analysis left open ──────
    settled_ex, settlement_tables = settlement_section(staging, periods[-1], followup, prior_block,
                                                       local_note, values)
    deck_note = deck_source(staging)
    # Both legs are already in millions, so the ratio is a plain division; the
    # company prints the two counts side by side and never the ratio itself.
    exec_share = [round(e / p * 100, 6) if None not in (e, p) else None
                  for e, p in zip(deck["executive_members_mm"], deck["paid_members_mm"])]
    executive_ex = {
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
        "note": (f"{len(deck_labels)} 期里 Executive 会员从 {deck['executive_members_mm'][0]:.1f}MM "
                 f"到 {deck['executive_members_mm'][-1]:.1f}MM，占付费会员从 {exec_share[0]:.1f}% "
                 f"到 {exec_share[-1]:.1f}%（D）。"
                 "<b>公司从不印这个比率</b>，但它印这个比率的两个组成部分 —— "
                 "Executive 会员数与付费会员数并排放在同一张表里，所以这里的占比是两个申报值相除（D）。"
                 "红线是另一个数，别看混：<b>销售渗透率是 Executive 会员贡献的销售额占比，"
                 "不是人数占比</b>，公司直接披露它，本季 "
                 f"{deck['executive_sales_penetration_pct'][-1]:.1f}%。"
                 + deck_note),
        "src_extra": deck_note,
    }

    # ── section two: what actually moved this quarter ───────────────────────
    gap = hist["gap_pp"]
    # The gap is reported minus adjusted, so it is empty wherever the adjusted
    # figure is (the ASC 606 quarters above). Rank and count over what exists.
    gap_filed = [v for v in gap if v is not None]
    # When the sign last turned, read off the record rather than remembered.
    last_negative = max((i for i, v in enumerate(gap) if v is not None and v < 0), default=None)
    if last_negative == len(gap) - 4 and all(v >= 0 for v in gap[-3:]) and gap[-1] > 0:
        sign_story = (f"符号是在{cn_count(4)}个季度前才翻过来的：{hist_labels[-4]} 还是 {gap[-4]:+.1f}，"
                      f"接着 {gap[-3]:+.1f}、{gap[-2]:+.1f}、{gap[-1]:+.1f}。")
    elif last_negative == len(gap) - 1:
        sign_story = f"本季仍是负的：{gap[-1]:+.1f}。"
    elif last_negative is not None:
        sign_story = (f"最后一次为负是 {hist_labels[last_negative]} 的 {gap[last_negative]:+.1f}，"
                      f"此后 {len(gap) - 1 - last_negative} 季都不为负。")
    else:
        sign_story = ""
    ancillary = cats["growth_contribution_pp"]["warehouse_ancillary_and_other_usd_m"][-1]
    ancillary_share = ancillary / cats["net_sales_yoy_pct"][-1] if cats["net_sales_yoy_pct"][-1] > 0 else None
    if ancillary_share is not None and 0.4 <= ancillary_share < 0.5:
        ancillary_words = "接近全部增量的一半"
    elif ancillary_share is not None and 0.5 <= ancillary_share < 0.6:
        ancillary_words = "略超全部增量的一半"
    elif ancillary_share is not None:
        ancillary_words = f"占全部增量的 {ancillary_share * 100:.0f}%"
    else:
        ancillary_words = "而本季净销售额没有增长"
    comparative = None
    if mismatch:
        quarter, year = staging["periods"][mismatch[0]].split()
        comparative = f"{quarter} {int(year) - 1}"
    traffic, ticket, adjusted_ticket = (deck["comp_traffic_pct"], deck["comp_ticket_pct"],
                                        deck["adjusted_comp_ticket_pct"])
    ticket_gap = ticket[-1] - adjusted_ticket[-1]
    acceleration = ticket[-1] - ticket[-2]
    if acceleration > 0:
        in_gap = (acceleration - (adjusted_ticket[-1] - adjusted_ticket[-2])) / acceleration
        acceleration_words = ("，几乎全部的客单加速都在这个缺口里。" if in_gap >= 0.9 else
                              f"，客单加速的 {in_gap * 100:.0f}% 在这个缺口里。")
    else:
        acceleration_words = "。"
    # The margin bridge is the company's own: the MD&A prints the basis-point
    # changes, and where it rounds differently from the dollars the page uses
    # what the company printed.
    mdna = staging["mdna_margins_pct"]
    if staging["periods"][-1] in mdna["periods"]:
        m = mdna["periods"].index(staging["periods"][-1])
        gm_bps, sga_bps = mdna["gross_margin_change_bps"][m], mdna["sga_change_bps"][m]
    else:
        gm_bps = round((fin["gross_margin_pct"][-1] - fin["gross_margin_pct"][-5]) * 100)
        sga_bps = round((fin["sga_pct_of_net_sales"][-1] - fin["sga_pct_of_net_sales"][-5]) * 100)
    offsetting = gm_bps * sga_bps > 0 and abs(gm_bps - sga_bps) <= 5
    segments_close = all(
        seg["united_states"]["revenue_usd_m"][i] + seg["canada"]["revenue_usd_m"][i]
        + seg["other_international"]["revenue_usd_m"][i] == revenue[i]
        and seg["united_states"]["operating_income_usd_m"][i] + seg["canada"]["operating_income_usd_m"][i]
        + seg["other_international"]["operating_income_usd_m"][i] == operating[i]
        for i in range(len(staging["periods"])))
    canada_higher = all(c > u for c, u in zip(seg["canada"]["operating_margin_pct"],
                                               seg["united_states"]["operating_margin_pct"]))
    negative_gaps = sum(1 for v in gap_filed if v < 0)
    positive_gaps = sum(1 for v in gap_filed if v > 0)
    zero_gaps = sum(1 for v in gap_filed if v == 0)
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
                     f"{gap[-1]:.1f} 个百分点，是有该口径的 {len(gap_filed)} 季里第 "
                     f"{sorted(gap_filed, reverse=True).index(gap[-1]) + 1} 大的一次。</b>"
                     "读 headline 的人看到的是金色，读这家公司的人要看深蓝。"
                     "两条线在 2021–2022 年那段一起冲到两位数，是疫情后的低基数加油价，"
                     "不是需求。"
                     + resolution_note(staging)),
            "src_extra": SOURCE_PR,
        },
        {
            "ref": "EX_GAP",
            "kind": "diverging_bars",
            "title": (f"汽油与汇率把 headline 抬高（或压低）了多少："
                      f"{len(gap_filed)} 季里 {negative_gaps} 季是压低"),
            "xlabels": hist_labels,
            "values": rounded(gap),
            "legend": "报告 comp − 调整后 comp",
            "positive_label": "抬高 headline",
            "negative_label": "压低 headline",
            "fmt": "pp1", "yfmt": "pp1", "label_fmt": "pp1",
            "ylab": "百分点", "zero_line": True, "xstep": LONG_STEP,
            "note": ("<b>这张图是本页最想让人看见的一张。</b>"
                     + (f"本地笔记把本季 {gap[-1]:.1f} 个百分点的汽油顺风当成一次性的加成来提示风险，"
                        "而完整记录说的是更强的一句话："
                        if local_note and local_note.get("gas_tailwind_flagged") and gap[-1] > 0 else
                        f"本季这个缺口是 {gap[-1]:+.1f} 个百分点，而完整记录说的是一句更一般的话：")
                     + f"这个缺口在有该口径的 {len(gap_filed)} "
                     f"个季度里有 {negative_gaps} 季是<b>负的</b> —— "
                     + (f"压低的次数比抬高的次数多（{negative_gaps} 比 {positive_gaps}"
                        + (f"，另有 {zero_gaps} 季恰好为零" if zero_gaps else "")
                        + "）。"
                        if negative_gaps > positive_gaps else
                        f"压低 {negative_gaps} 季、抬高 {positive_gaps} 季"
                        + (f"、恰好为零 {zero_gaps} 季" if zero_gaps else "") + "，")
                     + (f"（横轴共 {len(gap)} 季，其中 {len(gap) - len(gap_filed)} 季"
                        "公司当年的「调整后」口径连同 ASC 606 一起剔除，与其余各季不可比，"
                        "本图留空、数字保留在核对表里。）"
                        if len(gap_filed) != len(gap) else "")
                     + f"最深一次是 {hist_labels[gap.index(min(gap_filed))]} 的 "
                     f"{min(gap_filed):.1f} 个百分点。"
                     + sign_story +
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
            "annot": (f"{labels[mismatch[0]]}：{weeks[mismatch[0]]} 周对上年 "
                      f"{staging['weeks_by_period'][comparative]} 周" if mismatch else ""),
            "note": ("四根柱相加等于当季净销售额的同比增速，是恒等式不是估计。"
                     "<b>红色那条是加油站、药房、食品部、眼镜与轮胎安装所在的「仓内附属与其他」</b>，"
                     f"本季它一条就贡献了 "
                     f"{cats['growth_contribution_pp']['warehouse_ancillary_and_other_usd_m'][-1]:.1f} "
                     f"个百分点，{ancillary_words}，而它只占上年净销售额的 "
                     f"{cats['ancillary_share_of_base_pct'][-1]:.1f}%。"
                     "这是「汽油推高了 headline」这句话在申报文件里的样子 —— "
                     "公司不拆汽油单独的销售额，但它拆到了这条线。"
                     + (f"<b>{labels[mismatch[0]]} 那一格要打折：</b>它是 {weeks[mismatch[0]]} 周的会计 Q4 "
                        f"对上年 {staging['weeks_by_period'][comparative]} 周的会计 Q4"
                        f"（FY{fiscal_year_of(comparative)} 是 53 周财年），"
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
                     + (f"<b>本季的张力在这里：客流从 {traffic[-2]:+.1f}% 降到 "
                        f"{traffic[-1]:+.1f}%，缺口由客单补上。</b>"
                        if traffic[-1] < traffic[-2] and ticket[-1] > ticket[-2] else
                        f"本季客流从 {traffic[-2]:+.1f}% 到 {traffic[-1]:+.1f}%、"
                        f"客单从 {ticket[-2]:+.1f}% 到 {ticket[-1]:+.1f}%。")
                     + "金色与蓝色两条客单线之间的距离就是汽油与汇率 —— 本季 "
                     f"{ticket_gap:.1f} 个百分点"
                     + acceleration_words
                     + deck_note),
            "src_extra": deck_note,
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
                     "油价一涨两个比率一起被稀释，"
                     + (f"所以本季毛利率 {minus_sign(f'{gm_bps:+d}')}bp 与 SG&A 率 "
                        f"{minus_sign(f'{sga_bps:+d}')}bp 几乎抵消，营业利润率只动了 "
                        if offsetting else
                        f"本季毛利率 {minus_sign(f'{gm_bps:+d}')}bp、SG&A 率 "
                        f"{minus_sign(f'{sga_bps:+d}')}bp，营业利润率动了 ")
                     + f"{fin['operating_margin_pct'][-1] - fin['operating_margin_pct'][-5]:+.2f} 个百分点。"),
            "src_extra": "各季业绩 8-K EX-99.1 合并损益表；三个比率为本页自算（D）。",
        },
    ]

    # Segment margins are a long-run structural read: the local analysis draws no
    # conclusion from them this quarter, so they sit in section four.
    segment_ex = {
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
        "note": (("<b>加拿大的分部利润率长期高于美国</b>，而它只占本季总收入的 "
                  if canada_higher else "加拿大只占本季总收入的 ")
                 + f"{seg['canada']['revenue_usd_m'][-1] / revenue[-1] * 100:.1f}%。"
                 + ("三个分部的收入相加等于合并总收入、营业利润相加等于合并营业利润，"
                    f"{cn_count(len(staging['periods']))}个季度逐季核对差额为零。"
                    if segments_close else "")
                 + f"<b>{'、'.join(labels[i] for i in long_quarters)} "
                 f"{cn_count(len(long_quarters))}格是自算值（D）：</b>"
                 "会计 Q4 没有 10-Q，分部数只能用全年减去 36 周累计。"
                 "同一个减法在合并层面得到的净销售额与营业利润，与 Q4 业绩稿印出的 16 周数逐项相同，"
                 "这是本页愿意用它做分部的理由。"),
        "src_extra": ("各季 10-Q 与 10-K 分部附注；分部利润率为分部营业利润除以分部总收入，"
                      "本页自算（D）。"),
    }

    # ── section three: what to watch next ───────────────────────────────────
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
    exact = sum(1 for estimate, actual in final_estimate.values() if estimate == actual)
    plan_misses = [capex_full["deviation_vs_final_pct"][capex_full["guided_fiscal_years"].index(year)]
                   for year in sorted(final_estimate)
                   if year in capex_full["guided_fiscal_years"]]
    plan_misses = [abs(value) for value in plan_misses if value is not None]
    special = staging["special_dividends"]
    special_index = [bal["periods"].index(period) for period in special["paid_in_periods"]
                     if period in bal["periods"]]
    cash = bal["cash_and_short_term_investments_usd_m"]
    special_years = [d["fiscal_year"] for d in special["all"]]
    special_gap = sum(b - a for a, b in zip(special_years, special_years[1:])) / (len(special_years) - 1)
    last_special = special["all"][-1]
    above_last = cash[-1] > special["cash_before_last_special_usd_m"]
    # The analysis's cash line is an event, not a number: it is named here and
    # tracked by this chart, and it never enters the headroom overview.
    watched = [item for item in next_block.get("not_charted", []) if item.get("tracked_by") == "EX_CASH"]
    cash_watch = "".join(
        f"本季报告第 8 节这一条的原文是「{item['quote']}」 —— 这是事件型触发，"
        "没有数值阈值，所以本图不画阈值线，也不进上面的余量图。"
        f"报告引用的现金是现金及等价物（本季末 US${bal['cash_and_equivalents_usd_m'][-1]:,.0f}M）；"
        f"本图再加上短期投资 US${bal['short_term_investments_usd_m'][-1]:,.0f}M，"
        "因为下面那个历史参照是同一口径。"
        for item in watched)
    cash_ex = {
        "ref": "EX_CASH",
        "kind": "bars_labeled",
        "title": (f"现金及短期投资：本季末 US${cash[-1] / 1000:.1f}B，"
                  f"{'已高于' if above_last else '仍低于'}上一次宣布特别股息时的 "
                  f"US${special['cash_before_last_special_usd_m'] / 1000:.1f}B"),
        "xlabels": [compact_period(period) for period in bal["periods"]],
        "values": rounded(cash),
        "fmt": "f0c", "label_fmt": "f0c", "ylab": "US$M", "xstep": LONG_STEP,
        "bar_marks": special_index,
        "mark_note": "该季支付了特别股息",
        "note": ("斜纹柱是支付了特别股息的季度。"
                 f"Costco 一共派过{cn_count(len(special['all']))}次特别股息 —— "
                 + "、".join(f"{d['fiscal_year']} 年每股 US${d['per_share']:.0f}"
                             for d in special["all"])
                 + f" —— 平均间隔约{cn_count(round(special_gap))}年，最近一次是 "
                 f"{last_special['paid'][:4]} 年 {int(last_special['paid'][5:7])} 月的每股 "
                 f"US${last_special['per_share']:.0f}、"
                 f"合计 US${special['last_total_usd_m']:,.0f}M。"
                 + cash_watch
                 + "<b>下面这个参照是本站自己放的历史刻度，不是报告的阈值：</b>"
                 "上一次宣布特别股息的前一个季度末，现金及短期投资是 US$"
                 f"{special['cash_before_last_special_usd_m'] / 1000:.1f}B；"
                 f"本季{'已经' if above_last else ''}是 US${cash[-1] / 1000:.1f}B，也就是说按上一次的标准，"
                 + ("现金已经攒过了那条线。" if above_last else "现金还没有攒过那条线。")
                 + "这不是预测公司会宣布什么，"
                 "只是把「闲置现金」这个判断放到它自己的历史刻度上。"
                 "本页不发布特别股息的时点预期。"),
        "src_extra": ("各季业绩 8-K EX-99.1 的合并资产负债表（现金及等价物加短期投资）；"
                      "特别股息的宣告日、每股金额与合计支付额取自各次宣告的 8-K 与当年 10-K。"),
    }
    next_ex, next_table = next_section(staging, next_block, local_note, values)
    next_ex.append(cash_ex)
    # The year-end store count is the company's own quarterly-revised guidance, so
    # it is settled in section one beside the capital and opening plans.
    company_ex.append({
        "ref": "EX_WH_EST",
        "kind": "grouped_bars",
        "title": (f"公司自己估的财年末仓库数：{cn_count(len(final_estimate))}个已完结财年"
                  + ("都精确落在最后一次估计上，" if exact == len(final_estimate)
                     else f"里 {exact} 个精确落在最后一次估计上，")
                  +
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
                 "<b>把这张图和本节前面的资本开支计划图放在一起，就是这家公司预测能力的两面：</b>"
                 f"已完结的{cn_count(len(final_estimate))}个财年里，仓库数的<b>最后一次</b>估计"
                 + ("与实际一个不差（" if exact == len(final_estimate) else "与实际的对照是（")
                 + "；".join(settled_estimates)
                 + "）"
                 + ("，而同期的资本开支计划每年都差 5% 到 15%。"
                    if plan_misses and all(5 <= value <= 15 for value in plan_misses) else
                    "。")
                 + "店的数量是它自己排的工期，花掉的钱不是。"
                 + deck_note),
        "src_extra": deck_note + "实际财年末家数取自各年 10-K。",
    })

    # ── section four: the long routine ─────────────────────────────────────
    fy_labels = ann["fiscal_years"]
    merch_leg = ann["merchandising_leg_pct_of_net_sales"]
    memb_leg = ann["membership_leg_pct_of_net_sales"]
    share = ann["membership_fee_share_of_operating_income_pct"]
    fee_per_member = mem["annualised_fee_per_paid_member_usd"]
    years_word = cn_count(len(fy_labels))
    legs_gap = [a - b for a, b in zip(memb_leg, merch_leg)]
    legs_closest = 0 < legs_gap[-1] == min(legs_gap)
    legs_close = all(abs(a + b - c) < 1e-3 for a, b, c in
                     zip(merch_leg, memb_leg, ann["operating_margin_on_net_sales_pct"]))
    low_year = fy_labels.index("FY2022") if "FY2022" in fy_labels else None
    oil_year = (low_year is not None
                and ann["gross_margin_pct"][low_year] == min(ann["gross_margin_pct"])
                and ann["sga_pct_of_net_sales"][low_year] == min(ann["sga_pct_of_net_sales"])
                and ann["operating_margin_on_net_sales_pct"][low_year]
                >= max(ann["operating_margin_on_net_sales_pct"][:low_year + 1]))
    long_years = [label for label, weeks_in_year in zip(fy_labels, ann["weeks"]) if weeks_in_year == 53]
    rises = 0
    for index in range(len(fee_per_member) - 1, mem["fee_increase_index"] - 1, -1):
        if fee_per_member[index] > fee_per_member[index - 1]:
            rises += 1
        else:
            break
    intensity = ann["capex_intensity_pct"]
    around = round(sum(intensity) / len(intensity))
    clouds = hyperscaler_capex_share(staging["periods"][-1])
    order_below = bool(clouds) and min(clouds[1]) >= 10 * intensity[-1]
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
                     f"这句话在 {fy_labels[0]} 是对的：营业利润率 "
                     f"{ann['operating_margin_on_net_sales_pct'][0]:.2f}% 里，"
                     f"会员费贡献 {memb_leg[0]:.2f} 个百分点，商品只贡献 {merch_leg[0]:.2f}。"
                     f"到 {fy_labels[-1]} 变成 {memb_leg[-1]:.2f} 对 {merch_leg[-1]:.2f}，"
                     f"两条腿只差 {memb_leg[-1] - merch_leg[-1]:.2f} 个百分点"
                     + (f"，{years_word}年来第一次快要交叉。" if legs_closest else "。")
                     +
                     "换成占营业利润的比重说同一件事："
                     f"会员费从 {share[0]:.1f}% 降到 {share[-1]:.1f}%。"
                     "<b>这是恒等式：</b>商品腿 + 会员费腿 = 营业利润 ÷ 净销售额"
                     + (f"，{years_word}个年度逐年核对差额为零。" if legs_close else "。")
                     +
                     "会员费在这段时间涨过两次价（2017 年 6 月、2024 年 9 月），"
                     "占比仍然在降 —— 不是会员费不行了，是商品那条腿长得更快。"),
            "src_extra": ("各年 10-K 合并损益表；两条腿均为申报值相除，本页自算（D）。"),
        },
        {
            "ref": "EX_LONGMARGIN",
            "kind": "lines",
            "title": (f"{years_word}年毛利率与 SG&A 率：毛利率 {ann['gross_margin_pct'][0]:.2f}% → "
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
                     f"毛利率{years_word}年只动了 {ann['gross_margin_pct'][-1] - ann['gross_margin_pct'][0]:+.2f} "
                     f"个百分点，SG&A 率动了 "
                     f"{ann['sga_pct_of_net_sales'][-1] - ann['sga_pct_of_net_sales'][0]:+.2f}。"
                     + ("<b>FY2022 那一格是油价，不是经营</b>：那一年毛利率与 SG&A 率一起掉到窗口最低，"
                        "因为汽油销售额把两个比率的分母同时撑大了，营业利润率反而是当时的高点。"
                        "这也是为什么本页在第三节要单独画一条剔除仓内附属业务的核心商品毛利率。"
                        if oil_year else "")
                     + (f"{' 与 '.join(long_years)} "
                        "是 53 周财年，多一周的销售额被摊进全年比率里，影响在小数点后两位。"
                        if long_years else "")),
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
                     f"US${fee_per_member[-1]:.2f}，"
                     + (f"连涨{cn_count(rises)}个季度还没走完。" if rises and fee_per_member[-1] > fee_per_member[-2]
                        else "涨势已经停下。")
                     +
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
            "note": (f"{years_word}年门店数增加 "
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
            "title": (f"{years_word}年经营现金流、资本开支与股东回报：{fy_labels[-1]} 分别为 US$"
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
                     f"{years_word}年累计回购 US${sum(ann['buybacks_usd_m']) / 1000:.1f}B，"
                     f"只有同期经营现金流 US${sum(ann['operating_cash_flow_usd_m']) / 1000:.0f}B 的 "
                     f"{sum(ann['buybacks_usd_m']) / sum(ann['operating_cash_flow_usd_m']) * 100:.1f}%。"
                     "这家公司把超额现金攒起来、隔几年一次性派掉，而不是逐年买回股票 —— "
                     "所以现金余额本身就是资本配置的跟踪指标，见第三节那张图。"
                     f"资本开支占总收入的比重{years_word}年从 "
                     f"{ann['capex_intensity_pct'][0]:.2f}% 到 {ann['capex_intensity_pct'][-1]:.2f}%，"
                     + (f"始终在 {around}% 附近 —— 一家把钱主要花在盖仓库上的零售商"
                        if all(abs(v - around) <= 0.5 for v in intensity) else
                        "—— 一家把钱主要花在盖仓库上的零售商")
                     + ("，资本强度比本站任何一家云厂都低一个数量级。" if order_below else "。")),
            "src_extra": "各年 10-K 现金流量表，申报值；分红含特别股息。",
        },
    ]

    settled_ex += company_ex
    routine_ex += [segment_ex, executive_ex]
    number_exhibits(settled_ex, start=1)
    number_exhibits(highlight_ex, start=settled_ex[-1]["n"] + 1)
    number_exhibits(next_ex, start=highlight_ex[-1]["n"] + 1)
    number_exhibits(routine_ex, start=next_ex[-1]["n"] + 1)
    # Read the numbers before the references are resolved (that drops `ref`).
    ref_numbers = {exhibit["ref"]: exhibit["n"]
                   for exhibit in settled_ex + highlight_ex + next_ex + routine_ex if exhibit.get("ref")}
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
    # The four ASC 606 quarters have no adjusted figure on this series' basis,
    # but the company did print one on a wider basis. Showing "—" there would
    # read as "not disclosed"; showing the number unmarked would read as though
    # it were comparable. So the table prints it with the basis attached.
    wider = staging["comp_history_pct"].get("asc606_era_as_disclosed", {})
    wider_total = dict(zip(wider.get("periods", []),
                           wider.get("as_disclosed_adjusted_total_pct", [])))

    def adjusted_cell(index, period):
        value = hist["adjusted_total_pct"][index]
        if value is not None:
            return f"{value:+.1f}%"
        if period in wider_total:
            return f"{wider_total[period]:+.1f}% *"
        return "—"

    comp_rows = []
    for index, period in enumerate(hist["periods"]):
        comp_rows.append([
            period,
            hist["fiscal_labels"][index],
            f"{long_weeks[index]} 周",
            f"{hist['reported_total_pct'][index]:+.1f}%",
            adjusted_cell(index, period),
            (f"{hist['gap_pp'][index]:+.1f}pp"
             if hist["gap_pp"][index] is not None else "—"),
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
    # The notes and the disclosure table are prose kept in the series file; their
    # counts are placeholders filled here, so a roll does not retype them.
    guide = staging["capex_guidance"]
    qualitative_at = next((i for i, flag in enumerate(guide["is_qualitative"]) if flag), None)
    capex_full_both = [i for i, (a, b) in enumerate(zip(capex_full["deviation_vs_opening_pct"],
                                                        capex_full["deviation_vs_final_pct"]))
                       if a is not None and b is not None]
    facts = {
        "fiscal_label": staging["fiscal_labels"][-1],
        "weeks": weeks[-1],
        "period_end": staging["period_ends"][-1],
        "period": staging["periods"][-1],
        "resolution_recent": resolution_recent(staging),
        "adjusted_quarters": len(adjusted_filed),
        "deck_quarters": len(deck["periods"]),
        "deck_first_fiscal": fiscal_label_of(deck["periods"][0]),
        "lag_min": min(guide["lag_days_into_guided_year"]),
        "lag_max": max(guide["lag_days_into_guided_year"]),
        "open_mean": sum(abs(capex_full["deviation_vs_opening_pct"][i]) for i in capex_full_both)
        / len(capex_full_both),
        "final_mean": sum(abs(capex_full["deviation_vs_final_pct"][i]) for i in capex_full_both)
        / len(capex_full_both),
        "band_first": guide["guided_fiscal_years"][0],
        "band_years": len(guide["guided_fiscal_years"]),
        "qualitative_year": guide["guided_fiscal_years"][qualitative_at] if qualitative_at is not None else "",
        "qualitative_prior": guide["guided_fiscal_years"][qualitative_at] - 1 if qualitative_at is not None else "",
        "qualitative_growth": ((guide["actual_capex_usd_m"][qualitative_at]
                                / guide["actual_capex_usd_m"][qualitative_at - 1] - 1) * 100
                               if qualitative_at else 0.0),
        "comp_first_fiscal": hist["fiscal_labels"][0],
        "comp_quarters": len(hist["periods"]),
        "asc606_quarters": len(asc606),
    }
    boundary_rows = [[item["metric"], item["verdict"], item["where"], item["window"].format_map(facts)]
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
    # The drawer follows the sections: what section one settles (the previous
    # analysis's questions and thresholds, then the company's own records), the
    # next quarter's lines, then the long tables.
    plan_table = {
        "title": "开店计划的限定词变迁与逐年结清",
        "headers": ["被指引的财年", "计划原文的限定词", "计划家数", "搬迁口径",
                    "计划合计 D", "实际开店数", "判定"],
        "rows": plan_rows,
    }
    ordered = settlement_tables + [capex_table, plan_table, next_table, {
        "title": f"{cn_count(len(staging['periods']))}季核心（自然年季度标注；公司财季与周数见第二、四列）",
        "headers": ["自然年季度", "公司财季", "季末", "周数", "净销售额", "会员费",
                    "总收入", "总收入同比", "报告 comp", "调整后 comp",
                    "毛利率", "SG&A 率", "营业利润", "摊薄 EPS", "季末仓库数"],
        "rows": core_rows,
    }, {
        "title": "同店销售完整记录（新闻稿一位小数版；10-Q 的整数版见说明）",
        "headers": ["自然年季度", "公司财季", "周数", "报告 comp", "调整后 comp",
                    "缺口 D", "数字化 comp", "数字化口径"],
        "rows": comp_rows,
    }, {
        "title": f"{years_word}年年度记录（各年取该年 10-K 印出的数）",
        "headers": ["财年", "财年末", "周数", "总收入", "会员费", "营业利润",
                    "会员费占营业利润 D", "商品腿 D", "会员费腿 D",
                    "资本开支", "经营现金流", "财年末仓库数", "特别股息／股"],
        "rows": annual_rows,
    }, {
        "title": "口径边界：哪些指标进了申报文件，哪些只在电话会上",
        "headers": ["指标", "是否进入申报文件", "在哪份文件里", "可用窗口"],
        "rows": boundary_rows,
    }]
    numbers = iter(range(first_table, first_table + 100))
    tables = [{"n": next(numbers), **{key: value for key, value in table.items() if key != "n"}}
              for table in ordered]
    tables.append(ai_capex_cycle_table(next(numbers)))

    latest_gap = hist["gap_pp"][-1]
    reported = hist["reported_total_pct"]
    higher = [i for i, value in enumerate(reported[:-1]) if value > reported[-1]]
    quarters_since_higher = len(reported) - 1 - max(higher) if higher else len(reported)
    eps_wedge = bridge["below_the_line_leg_pct"][-1] + bridge["tax_leg_pct"][-1]
    both_ends = latest_gap > 0 and bridge["reported_eps_yoy_pct"][-1] > fin["operating_income_yoy_pct"][-1]
    capex_rec = staging["capex_guidance"]
    capex_settled = [i for i, a in enumerate(capex_rec["actual_capex_usd_m"])
                     if a is not None and capex_rec["guided_low_usd_m"][i] is not None]
    capex_above = sum(1 for i in capex_settled if capex_rec["actual_capex_usd_m"][i] > capex_rec["guided_high_usd_m"][i])
    capex_below = sum(1 for i in capex_settled if capex_rec["actual_capex_usd_m"][i] < capex_rec["guided_low_usd_m"][i])
    fiscal = staging["fiscal_labels"]
    release = next(item for item in staging["sources"]
                   if item["label"].startswith(f"Costco {fiscal[-1]} 业绩新闻稿"))
    has_deck = any(item["label"].startswith(f"Costco {fiscal[-1]} 补充材料") for item in staging["sources"])
    has_10q = any(item["label"] == f"Costco 截至 {staging['period_ends'][-1]} 的 10-Q"
                  for item in staging["sources"])
    has_10k = fiscal[-1].endswith("Q4") and any(
        item["label"].startswith(f"Costco {fiscal[-1].split()[0]} 10-K") for item in staging["sources"])
    source_tail = (f"与截至 {staging['period_ends'][-1]} 的 10-Q。" if has_10q else
                   f"与 {fiscal[-1].split()[0]} 10-K。" if has_10k else
                   f"（本季 {'10-K' if fiscal[-1].endswith('Q4') else '10-Q'} 尚未申报）。")
    traffic_words = ("客流在走软" if traffic[-1] < traffic[-2] else
                     "客流在走强" if traffic[-1] > traffic[-2] else "客流持平")
    ticket_words = "客单在补位" if ticket[-1] > ticket[-2] else "客单在走弱"
    share_words = ("接近一半" if ancillary_share is not None and 0.4 <= ancillary_share < 0.5 else
                   "一半多" if ancillary_share is not None and 0.5 <= ancillary_share < 0.6 else
                   f"{ancillary_share * 100:.0f}%" if ancillary_share is not None else "没有")
    return {
        "schema_version": "quarterly-dashboard/cost-v1",
        "page": {"slug": "cost", "language": "zh-CN"},
        "company": {
            "ticker": "COST",
            "name": "Costco Wholesale Corporation",
            "group": "consumer_retail",
            "accounting_standard": "US GAAP",
        },
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · COST",
        "title": f"Costco Wholesale Corporation (COST)：{staging['periods'][-1]} 季报仪表盘",
        "subtitle": (
            f"{cn_count(weeks[-1])}周截至 {staging['period_ends'][-1]} · 发布 "
            f"{staging['release_dates'][-1]} · US GAAP · {AUDIT_WORDS[latest['audit_status']]} · "
            "财年末为最接近 8 月 31 日的星期日，本站按自然年季度标注："
            f"本页 {staging['periods'][-1]} 即公司所称 {fiscal[-1]}"
        ),
        "headline": (
            f"总收入 US${revenue[-1]:,.0f}M、同比 {signed(fin['total_revenue_yoy_pct'][-1])}，"
            f"报告 comp {signed(hist['reported_total_pct'][-1])} 是 {quarters_since_higher} "
            f"个季度以来最高；但公司自己披露的剔除汽油与汇率后的 comp 是 "
            f"{signed(hist['adjusted_total_pct'][-1])}，两者 {latest_gap:.1f} 个百分点的缺口"
            f"在这 {len(gap)} 季里有 {negative_gaps} 季是负的，{cn_count(4)}个季度前还是 {gap[-4]:+.1f}；"
            f"同一季每股收益 {signed(bridge['reported_eps_yoy_pct'][-1])} 对营业利润 "
            f"{signed(fin['operating_income_yoy_pct'][-1])}。"
            + ("两端的加成都能用申报值原样剥掉。" if both_ends else "")
        ),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>记录</span><b>公司只指引要花多少钱，不指引要赚多少</b>'
            f'<p>10-K 每年给一次下一财年的资本开支区间。'
            f'已完结的 {len(capex_settled)} 年里'
            + ('低于下限与高于上限的次数几乎相同 —— 全站唯一一份两边都会错的指引记录。</p></article>'
               if abs(capex_above - capex_below) <= 1 else
               f'低于下限 {capex_below} 次、高于上限 {capex_above} 次。</p></article>')
            + ('<article><span>裂口</span><b>headline 两端都被垫高了</b>'
               if latest_gap > 0 and eps_wedge > 0 else
               '<article><span>裂口</span><b>headline 与底层之间的两处差距</b>')
            + f'<p>报告 comp 比调整后{"高" if latest_gap >= 0 else "低"} {abs(latest_gap):.1f} 个百分点；'
            f'每股收益增速里有 {eps_wedge:+.1f}% '
            '来自利息收入与税率。两者都是申报值可复算的。</p></article>'
            '<article><span>长期</span><b>「靠会员费赚钱」这句话在变弱</b>'
            f'<p>会员费占营业利润从 {share[0]:.1f}% 降到 {share[-1]:.1f}%；'
            f'商品腿与会员费腿只差 {memb_leg[-1] - merch_leg[-1]:.2f} 个百分点'
            + (f'，{years_word}年来最近。</p></article>' if legs_closest else '。</p></article>')
            + '</div>'
        ),
        "source": (
            f'Source: <a href="{release["url"]}" rel="noopener">Costco {fiscal[-1]} '
            '业绩新闻稿（8-K EX-99.1）</a>'
            + ('、同一份 8-K 的 EX-99.2 补充材料，' if has_deck else '')
            + source_tail
        ),
        "source_url": release["url"],
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {
                "id": "settled",
                "title": "一、上季跟踪指标兑现了吗",
                "description": settled_description(staging, first_analysis, followup, prior_block, ref_numbers),
                "exhibits": settled_ex,
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": (
                    ("headline 的两端各被垫高了一次，而两次垫高都能用申报值原样剥掉："
                     if latest_gap > 0 and eps_wedge > 0 else
                     "headline 与底层之间的两处差距都能用申报值原样拆开：")
                    + "comp 那端是汽油与汇率，每股收益那端是利息收入与税率。"
                    f"剥完之后剩下的是{traffic_words}、{ticket_words}，以及四条商品线里"
                    f"加油站所在的那一条贡献了{share_words}的销售增量。"
                ),
                "exhibits": highlight_ex,
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": next_description(next_block, next_ex, values),
                "exhibits": next_ex,
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": (
                    f"Costco 专属的常规序列：营业利润率的两条腿如何在{years_word}年里换位、"
                    "毛利率与 SG&A 率各走了多远、一次涨价要花多久才吃满，"
                    f"一家资本强度只有 {round(intensity[-1])}% 的零售商怎么处理它攒下来的现金，"
                    "三个地区分部各自的利润率，以及 Executive 会员的人数与销售渗透率。"
                ),
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": [note.format_map(facts) for note in staging["notes"]],
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
