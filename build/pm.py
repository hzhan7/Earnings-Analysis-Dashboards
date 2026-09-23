"""Philip Morris International quarterly dashboard.

PMI is the first company on this site that guides **the same earnings number at
two horizons and on two definitions**, and the four records that fall out of
that disagree with each other. Every quarterly earnings 8-K since the 2008
spin-off carries a full-year EPS forecast, revised each quarter -- seventy-one
vintages across eighteen years when this page was built at Q2 2026, the longest
guidance record here by a wide margin. From the 2020 second quarter it also
carries a *next-quarter* forecast, and in 2022-2023 the guided quarterly metric
moved from reported diluted EPS to adjusted diluted EPS.

Read on the reported basis, the record is two-sided: the year landed below its
own final range in five of sixteen years, above in seven and inside in four (at
Q2 2026). Read on the adjusted basis -- same company, same release, same
horizon -- the next-quarter number has cleared the top of its range in every
finished quarter.

The reason is written into the guidance itself rather than inferred. From the
April 2009 release through the February 2022 release, every full-year forecast
carried the same clause: it excludes future acquisitions, asset impairment and
exit-cost charges, and any unusual events (the four releases before April 2009
name acquisitions at most). So the number labelled GAAP was never a
forecast of GAAP -- it was a GAAP number conditional on nothing unusual
happening. FY2024 is the clean case: reported EPS came in at US$4.52 against a
final guidance of US$6.20-6.26, entirely because of a US$1.49 non-cash
impairment of the deconsolidated Canadian affiliate recognised after the
guidance was published. The adjusted line for the same year cleared its range.

Rolling the page is a data edit (CLAUDE.md §9). Every count, period label, date,
tally and comparison below is computed from ``series/pm.json``; the sentences
that claim something about the whole record ("the only", "every", "all above",
"usually", "often") print only while the record says so. What one release says
sits in blocks stamped with the quarter and read through ``board.stamped_block``:
``next_kpi`` (thresholds and what is not tracked), ``quarter_printed`` (organic
growth rates the release printed), ``guidance_other`` (the non-EPS forecast rows)
and ``quarter_story`` (the company's explanations). The ZYN and revenue-bridge
blocks must end on the page's quarter. What stays here is fixed history: the
2008 pro forma forecast, the 2020 withdrawal, the 2021Q2 Saudi customs charge,
the FY2022 pro forma rows, the excise-label trap, the ASU 2017-07 hole.

Published numbers are company-reported or transparent arithmetic. No rating, no
target price and no broker-attributed estimate appears here.
"""

from __future__ import annotations

import collections
import datetime
import json
import statistics
import sys
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
    minus_sign,
    number_exhibits,
    stamped_block,
    threshold_exhibit,
    threshold_table,
    unit_text,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "pm.json"
DATA_DIR = ROOT / "data"

# One tick per year keeps the long quarterly axes readable.
LONG_STEP = 4

SEG_KEYS = ("international_smoke_free", "international_combustibles", "us")
SEG_NAMES = {"international_smoke_free": "国际无烟", "international_combustibles": "国际组合烟草",
             "us": "美国"}
SEG_COLORS = {"international_smoke_free": "NAVY", "international_combustibles": "BLUE",
              "us": "GOLD"}
CN_Q = {1: "一", 2: "二", 3: "三", 4: "四"}
EN_Q = {1: "First", 2: "Second", 3: "Third", 4: "Fourth"}
BRIDGE_PARTS = {"price": "价格", "volume_mix_other": "量与结构", "acq_div": "收购与处置", "currency": "汇率"}
AUDIT_WORDS = {"unaudited": "未审计", "audited": "已审计"}

# FY2019 and the FY2020 opening were published as a floor with no upper bound
# ("forecast to be at least $4.73"), so those years have no band to clear and
# sit outside the band chart rather than being drawn as a zero-width range.
FLOOR_YEARS = (2019,)

# PMI's three reportable segments start with the 2026 first quarter; the 2025
# quarters on this page are the prior-year columns of the 2026 releases.
NEW_SEGMENTS_FROM = "2026Q1"

# Fixed history, printed only while the record still says what they describe.
# The four releases before the exclusion clause, read 2026-09-19: 2008-04-23 and
# 2008-07-23 exclude future acquisitions "and a number of other factors",
# 2009-02-04 excludes acquisitions only, 2008-10-22 states no exclusion.
PRE_CLAUSE = ("2008-04-23", "2008-07-23", "2008-10-22", "2009-02-04")
Q2_2021_STORY = ("那一季沙特海关评估与退出成本压低了 GAAP 每股收益，而当季<b>调整后</b>每股收益是 "
                 "US$1.57，仍在指引区间之上")


def rounded(values, digits: int = 6):
    return [None if v is None else round(v, digits) for v in values]


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100.0


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def mid(low: float, high: float) -> float:
    return (low + high) / 2


def yq(label: str) -> tuple[int, int]:
    """``'2026Q2'`` or ``'Q2 2026'`` → ``(2026, 2)``."""
    text = label.strip()
    if text.startswith("Q"):
        number, year = text.split()
        return int(year), int(number[1])
    return int(text[:4]), int(text[-1])


def cn_quarter(label: str, word: str = "季度") -> str:
    year, number = yq(label)
    return f"{year} 年第{CN_Q[number]}{word}"


def display(label: str) -> str:
    year, number = yq(label)
    return f"Q{number} {year}"


def resolve_exhibit_refs(exhibits: list[dict]) -> list[dict]:
    """Replace ``{EX_NAME}`` placeholders with the numbers assigned at render.

    Exhibits are numbered in render order by ``board.number_exhibits``, so a
    caption cannot name its neighbour until after numbering.
    """
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


def verdict_of(actual: float | None, low: float, high: float) -> str | None:
    if actual is None:
        return None
    if actual > high:
        return "above"
    if actual < low:
        return "below"
    return "inside"


def tally(rows: list[tuple[float | None, float, float]]) -> tuple[int, int, int, int]:
    """(finished, above, inside, below) for a list of (actual, low, high)."""
    verdicts = [verdict_of(a, lo, hi) for a, lo, hi in rows]
    done = [v for v in verdicts if v]
    return (len(done), done.count("above"), done.count("inside"), done.count("below"))


def page_period(staging: dict) -> str:
    return staging["period_labels"][-1]


# ── the quarter's blocks ─────────────────────────────────────────────────────
def block(staging: dict, key: str) -> dict:
    return stamped_block(staging, key, page_period(staging)) or {}


def ending_on_page_quarter(staging: dict, key: str, periods: list[str]) -> None:
    """A per-quarter block whose last column is another quarter is last quarter's story."""
    if yq(periods[-1]) != yq(staging["periods"][-1]):
        raise ValueError(f"series block `{key}` ends at {periods[-1]!r}, but the series ends at "
                         f"{staging['periods'][-1]!r}: it is stamped for another quarter -- add the quarter")


def next_quarter_guidance(staging: dict) -> dict | None:
    """The one quarterly forecast not yet settled: the quarter after the page's."""
    rows = [r for r in staging["quarterly_guidance"] if r["actual_eps"] is None]
    late = [r["guided_period"] for r in rows if yq(r["guided_period"]) <= yq(staging["periods"][-1])]
    if late:
        raise ValueError(f"quarterly_guidance {late} has no actual although the series "
                         f"reaches {staging['periods'][-1]}")
    return rows[-1] if rows else None


def previous_quarter(label: str) -> str:
    """``'Q2 2026'`` → ``'Q1 2026'``; a first quarter's predecessor is last year's fourth."""
    year, number = yq(label)
    year, number = (year - 1, 4) if number == 1 else (year, number - 1)
    return f"Q{number} {year}"


def released_vintages(staging: dict) -> tuple[dict, dict, dict | None]:
    """The annual record this quarter's release updated, its newest vintage and the
    one before (a fourth-quarter release opens the next year, so it has no earlier one)."""
    released = staging["latest"]["release_date"]
    record = next((r for r in staging["annual_guidance"]["records"]
                   if r["vintages"] and r["vintages"][-1]["release_date"] == released), None)
    if record is None:
        raise ValueError(f"annual_guidance has no vintage released {released}: add this release's "
                         "full-year forecast")
    vintages = record["vintages"]
    return record, vintages[-1], (vintages[-2] if len(vintages) > 1 else None)


def page_quarter_offtake(staging: dict) -> tuple[float | None, str | None]:
    """This quarter's U.S. ZYN offtake reading: a figure, or only the company's words.

    Read through `zyn_view`, which refuses a block that ends on another quarter or
    whose figures and words do not pair up quarter by quarter.
    """
    zyn = zyn_view(staging)["zyn"]
    return zyn["offtake_yoy_pct"][-1], zyn["offtake_words"][-1]


def printed_rate(staging: dict, key: str) -> float:
    printed = block(staging, "quarter_printed")
    if key not in printed:
        raise ValueError(f"series `quarter_printed` has no {key!r} for {page_period(staging)}")
    return printed[key]


# What a settled threshold is measured against this quarter. A figure the
# release did not print reads as None, and the entry then has to say in words
# what the release's words settle it as.
READINGS = {
    "organic_growth": lambda s: printed_rate(s, "organic_revenue_growth_pct"),
    "organic_oi_growth": lambda s: printed_rate(s, "organic_operating_income_growth_pct"),
    "combustible_pricing": lambda s: printed_rate(s, "combustible_pricing_pct"),
    "zyn_offtake": lambda s: page_quarter_offtake(s)[0],
}


def money(value: float) -> str:
    return f"{'−' if value < 0 else ''}US${abs(value):.2f}"


def unit_words(unit: str, value: float) -> str:
    """A value in prose: money as ``US$`` the way this page's sentences write it, a
    multiple with ``×``; everything else as the shared table formatter prints it."""
    if unit == "usd_m":
        return f"{'−' if value < 0 else ''}US${abs(value):,.0f}M"
    if unit == "usd_eps":
        return f"{'−' if value < 0 else ''}US${abs(value):.2f}"
    if unit == "times":
        return f"{value:.2f}×"
    return unit_text(unit, value)


def threshold_words(entry: dict) -> str:
    """``≥15.0%``: the side of the line that is safe, in the entry's own unit."""
    return f"{'≥' if entry['direction'] == 'up' else '≤'}{unit_words(entry['unit'], entry['threshold'])}"


def base_name(metric: str) -> str:
    """「集团有机收入增速（加仓线）」→「集团有机收入增速」: the metric without its role."""
    return metric.split("（")[0]


def settlement_values(staging: dict) -> tuple[dict[str, str], dict[str, bool]]:
    """What a stamped settlement sentence may name, and the facts it may assume.

    The evidence behind last quarter's questions is one quarter's prose and lives
    in the series; a number the series already carries is named here instead of
    typed into it, and a claim the sentence makes about those numbers is a fact
    the sentence has to declare (`requires`) so a roll that breaks it stops.
    """
    values: dict[str, str] = {}
    facts: dict[str, bool] = {}
    offtake, words = page_quarter_offtake(staging)
    facts["zyn_words_only"] = offtake is None and bool(words)
    if words:
        values["zyn_words"] = words
    _, now, before = released_vintages(staging)
    if before is not None and before.get("adj_low") is not None and now.get("adj_low") is not None:
        values["xfx_band"] = f"US${now['xfx_low']:.2f}–{now['xfx_high']:.2f}"
        values["adj_before"] = f"US${before['adj_low']:.2f}–{before['adj_high']:.2f}"
        values["adj_now"] = f"US${now['adj_low']:.2f}–{now['adj_high']:.2f}"
        values["fx_before"] = money(before["currency_eps"])
        values["fx_now"] = money(now["currency_eps"])
        moved = mid(now["adj_low"], now["adj_high"]) - mid(before["adj_low"], before["adj_high"])
        facts["fy_change_all_currency"] = (
            (now["xfx_low"], now["xfx_high"]) == (before["xfx_low"], before["xfx_high"])
            and abs(moved - (now["currency_eps"] - before["currency_eps"])) < 0.005)
    return values, facts


# ── section one (a): the questions last quarter's note left open ───────────


def followup_exhibit(staging: dict) -> dict | None:
    """Last quarter's follow-up questions as this quarter's note closed them.

    The verdicts are the note's own words; the chart only counts them by the
    label each carries, so the count is computed and cannot disagree with the
    list printed under it. A quarter without the block has nothing to close.
    """
    period = page_period(staging)
    closure = stamped_block(staging, "followup_closure", period)
    if closure is None:
        return None
    if yq(closure["set_in"]) != yq(previous_quarter(period)):
        raise ValueError(f"series block `followup_closure` closes questions set in {closure['set_in']!r}, "
                         f"but the quarter before {period!r} is {previous_quarter(period)!r}")
    labels, items = closure["labels"], closure["items"]
    stray = sorted({item["label"] for item in items} - set(labels))
    if stray:
        raise ValueError(f"followup_closure items carry labels {stray} that `labels` does not list")
    values, facts = settlement_values(staging)
    for item in items:
        for fact in item.get("requires", []):
            if not facts.get(fact):
                raise ValueError(f"followup_closure item {item['question']!r} assumes {fact!r}, which the "
                                 "series no longer supports: rewrite its evidence")
    counted = [(label, sum(1 for item in items if item["label"] == label)) for label in labels]
    # a label nobody carries this quarter would be an empty column under its name
    counted = [(label, count) for label, count in counted if count]
    lines = "".join(f"<br>{number}. {item['question']} —— <b>{item['verdict']}</b>："
                    f"{fill_story(item['evidence'], values)}。"
                    for number, item in enumerate(items, 1))
    return {
        "ref": "EX_CLOSURE",
        "kind": "bars_labeled",
        "title": f"上季 {len(items)} 条待验证问题：" + "、".join(f"{count} 条{label}" for label, count in counted),
        "xlabels": [label for label, _ in counted],
        "values": [count for _, count in counted],
        "legend": "问题条数",
        "fmt": "f0", "yfmt": "f0", "label_fmt": "f0",
        "ylab": "条",
        "note": ("判定逐字取自本季本地分析稿第 0 节「上季遗留问题回答」，柱只把它们按判定归类计数。"
                 "证据只引新闻稿与 10-Q 印出的数；只在电话会上出现的数不引用。" + lines),
        "src_extra": (f"问题清单来自上季（{closure['set_in']}）本地分析稿的下季度跟踪问题；"
                      "验证依据本季业绩 8-K EX-99.1、10-Q 与业绩电话会。"),
    }


# ── section one (b): the thresholds last quarter's note set ────────────────


def prior_settlement(staging: dict) -> tuple[list[dict], list[dict], dict | None]:
    """Last quarter's quantified thresholds against this quarter's filed figures.

    Returns the charts, the entries settled with a figure (for the audit table)
    and the block. A threshold whose figure the release did not print is
    settled from the release's own words, stated in the block, and is drawn
    only where it has a series to draw; one that cannot be settled this
    quarter at all is named with the reason.
    """
    period = page_period(staging)
    kpi = stamped_block(staging, "prior_kpi_settlement", period)
    if kpi is None:
        return [], [], None
    if yq(kpi["set_in"]) != yq(previous_quarter(period)):
        raise ValueError(f"series block `prior_kpi_settlement` settles thresholds set in {kpi['set_in']!r}, "
                         f"but the quarter before {period!r} is {previous_quarter(period)!r}")
    numeric, worded = [], []
    for entry in kpi["quantified"]:
        if entry["measure"] not in READINGS:
            raise ValueError(f"prior_kpi_settlement entry {entry['metric']!r}: this page does not know how "
                             f"to measure {entry['measure']!r}")
        value = READINGS[entry["measure"]](staging)
        if value is None:
            words = page_quarter_offtake(staging)[1] if entry["measure"] == "zyn_offtake" else None
            if not words or entry.get("words_verdict") not in ("未达", "已达"):
                raise ValueError(f"prior_kpi_settlement entry {entry['metric']!r}: this quarter has no figure; "
                                 "settle it from the release's words as `words_verdict` (未达 / 已达)")
            worded.append({**entry, "words": words})
        elif "words_verdict" in entry:
            raise ValueError(f"prior_kpi_settlement entry {entry['metric']!r} has a figure this quarter "
                             f"({value}): remove its `words_verdict`")
        else:
            numeric.append({**entry, "actual": value})
    unsettleable = kpi.get("unsettleable", [])
    qualitative = kpi.get("qualitative", [])
    held = [e for e in numeric if headroom(e["direction"], e["threshold"], e["actual"]) >= 0]
    missed = [e for e in numeric if headroom(e["direction"], e["threshold"], e["actual"]) < 0]
    parts = []
    if held:
        parts.append(f"{len(held)} 条守住")
    if missed:
        parts.append(f"{len(missed)} 条没有守住（" + "、".join(e["metric"] for e in missed) + "）")
    parts += [f"{base_name(e['metric'])} {threshold_words(e)} {e['words_verdict']}" for e in worded]
    if unsettleable:
        parts.append(f"{len(unsettleable)} 条本季无法结算")
    note = ("正值 = 本季实际仍在上季阈值的安全侧。阈值逐字取自上季本地分析稿的「关键观察指标」，不是公司指引；"
            "同一个指标上季设了加仓线与警示线两条的，分开结算。"
            f"柱只画能用本季数字结算的{cn_count(len(numeric))}条。")
    for e in worded:
        note += (f"<b>{base_name(e['metric'])}那条画不成柱</b>：本季公司只说「{e['words']}」，没有给百分比，"
                 f"本页按这句话把 {threshold_words(e)} 记为「{e['words_verdict']}」，不把措辞折算成数字。")
    if unsettleable:
        note += (f"本季无法结算的{cn_count(len(unsettleable))}条：" + "；".join(
            f"{x['metric']} —— {x['why']}" for x in unsettleable) + "。")
    if qualitative:
        note += (f"另有{cn_count(len(qualitative))}行不是数字阈值：" + "；".join(
            f"{x['name']} —— {x['result']}" for x in qualitative) + "。")
    readings: dict[str, tuple[str, float, str]] = {}
    for e in numeric:
        readings.setdefault(e["measure"], (base_name(e["metric"]), e["actual"], e["unit"]))
    overview = headroom_exhibit(
        f"上季 {len(kpi['quantified']) + len(unsettleable)} 条量化阈值：" + "，".join(parts),
        numeric, "actual", note,
        ("实际值取自本季业绩 8-K EX-99.1："
         + "、".join(f"{name} {unit_text(unit, value)}" for name, value, unit in readings.values())
         + ("；美国 ZYN 零售出货只有新闻稿 U.S. 段的一句措辞" if worded else "") + "。"))
    overview["ref"] = "EX_PRIOR"
    charts = [overview]
    zyn = staging["zyn"]
    for e in worded:
        if e["measure"] != "zyn_offtake":
            continue
        known = [(v, label) for v, label in zip(zyn["offtake_yoy_pct"], zyn["period_labels"]) if v is not None]
        last_value, last_label = known[-1]
        side = "之下" if last_value < e["threshold"] else "之上"
        when = ("上季设这条线时，最近一格读数是" if yq(last_label) == yq(previous_quarter(period))
                else "最近一个有数字的读数是")
        chart = threshold_exhibit(
            f"{base_name(e['metric'])}：{e['words_verdict']}上季阈值 {unit_text(e['unit'], e['threshold'])}，"
            "本季只有措辞",
            zyn["period_labels"], rounded(zyn["offtake_yoy_pct"]), e["threshold"],
            fmt="pct1", ylab="同比 %", actual_name="美国 ZYN 零售出货同比（Nielsen）",
            threshold_name="上季阈值（安全侧在上方）",
            note=(f"{when} {last_label} 的 {last_value:.0f}%，已在 "
                  f"{unit_text(e['unit'], e['threshold'])} {side}；本季公司只说「{e['words']}」，"
                  "线停在有数字的最后一格，本页不把措辞折算成一个点。"),
            src_extra="各季业绩 8-K EX-99.1 正文；Nielsen 为公司引用的第三方零售监测口径；阈值取自上季本地分析稿。")
        chart["annot"] = f"{zyn['period_labels'][-1]}：公司口径为「{e['words']}」，无数字"
        charts.append(chart)
    return charts, numeric, kpi


def settled_description(closure: dict | None, prior: dict | None) -> str:
    """Section one's description names what it settles this quarter (plain text: it is escaped)."""
    parts = []
    if closure is not None:
        parts.append(f"上季本地分析稿留下的 {sum(closure['values'])} 条待验证问题，判定逐字取自本季分析稿第 0 节")
    if prior is not None:
        count = len(prior["quantified"]) + len(prior.get("unsettleable", []))
        parts.append(f"上季「关键观察指标」里的 {count} 条量化阈值，用本季申报值结算")
    lead = ("先结算上季留下、本季到期的东西：" + "；".join(parts) + "。" if parts
            else "本季没有上季分析稿留下的问题与阈值可结算。")
    return (lead + "再结清公司自己给的指引：PMI 把同一个盈利数字指引两次 —— 一次是全年，一次是下一个季度 —— "
            "而且中途把被指引的口径从 GAAP 换成了公司自定义的调整后口径，四条记录因此互相矛盾，"
            "这里把它们并排结清，并说明矛盾来自哪里。")


# ── section one (c): the guidance record ────────────────────────────────────


def annual_records(staging: dict):
    """Split the annual record into the years a range was actually published."""
    banded, floors = [], []
    for record in staging["annual_guidance"]["records"]:
        last = record.get("last_guided")
        if not last:
            continue
        if last["form"] == "floor" or record["year"] in FLOOR_YEARS:
            floors.append(record)
        else:
            banded.append(record)
    return banded, floors


def clause_sentence(staging: dict) -> tuple[str, str]:
    """The exclusion clause, counted release by release from the stored census."""
    census = staging["annual_guidance"]["exclusion_clause_census"]
    releases, without = census["releases"], census["without_clause"]
    unknown = sorted(set(without) - set(releases))
    if unknown:
        raise ValueError(f"exclusion_clause_census lists {unknown} outside its own releases")
    first_with = min(r for r in releases if r not in without)
    # A release that withdrew the full-year forecast still carries the clause, on
    # the forecasts it gave instead; it is counted, and said.
    withdrawn = sorted(d for r in staging["annual_guidance"]["records"] for d in r["withdrawn"]
                       if d in releases and d not in without)
    span = (f"{int(releases[0][:4])} 年 {int(releases[0][5:7])} 月到 "
            f"{int(releases[-1][:4])} 年 {int(releases[-1][5:7])} 月的 {len(releases)} 份新闻稿里")
    counted = f"有 {len(releases) - len(without)} 份写明该预测不含未来并购、资产减值与退出成本、以及任何异常事件"
    if without and all(r < first_with for r in without):
        detail = f"（{int(first_with[:4])} 年 {int(first_with[5:7])} 月起每一份都有"
        if withdrawn:
            detail += (f"，其中 {'、'.join(withdrawn)} {'那份' if len(withdrawn) == 1 else '那几份'}"
                       "撤回了全年预测，这句话跟着它改给的季度预测")
        detail += f"；此前的 {len(without)} 份 —— {'、'.join(without)} —— "
        detail += ("点名排除的最多只有并购）" if tuple(without) == PRE_CLAUSE else "没有这句话）")
    else:
        detail = f"（例外是 {'、'.join(without)}）" if without else ""
    return span, counted + detail


def annual_reported_band(staging: dict) -> dict:
    banded, floors = annual_records(staging)
    labels = [f"FY{r['year']}" for r in banded]
    low = [r["last_guided"]["low"] for r in banded]
    high = [r["last_guided"]["high"] for r in banded]
    actual = [r["actual_reported_eps"] for r in banded]
    years = [r["year"] for r in banded]
    # The axis jumps across the floor years; the marker says so rather than
    # letting the gap read as a missing year.
    floor_years = [r["year"] for r in floors]
    after = [y for y in years if floor_years and y > floor_years[-1]]
    before = [y for y in years if floor_years and y < floor_years[0]]
    break_at = years.index(after[0]) if after else None
    months = collections.Counter(int(r["last_guided"]["release_date"][5:7]) for r in banded
                                 if r["actual_reported_eps"] is not None)
    usual, count = months.most_common(1)[0]
    timing = (f"画的是<b>当年最后一次</b>指引，通常发布于 {usual} 月，此时全年已过去四分之三。"
              if count * 2 > sum(months.values()) and usual == 10 else "画的是<b>当年最后一次</b>指引。")
    span, counted = clause_sentence(staging)
    return delivery_band(
        "EX_FY_BAND", "全年报告口径摊薄每股收益", labels, low, high, actual,
        fmt="usd2", ylab="US$/股", unit="US$/股",
        venue="业绩新闻稿", period_word="年",
        timing="该年<b>当年内</b>",
        scope="（当年最后一次指引）",
        break_at=break_at,
        break_label="、".join(f"{y} 年" for y in floor_years) + "只给下限，不在本图",
        extra_note=(
            timing
            + (f"横轴从 FY{before[-1]} 跳到 FY{after[0]}，是因为 "
               + "、".join("FY%d" % y for y in floor_years) + " "
               "的指引是「至少 US$X」这样只有下限的形式，没有上限可以穿出，画成零宽区间会造出"
               "一个公司没说过的上界；这些年份的记录见核对抽屉。" if before and after else "")
            + "<b>更要紧的是这条指引长期带着一句排除条款</b>："
            + span + counted + "。"
            "所以这个挂着 GAAP 名字的数并不是对 GAAP 的预测，"
            f"而是「不出异常事件时的 GAAP」。同一记录换成公司自定义的调整后口径见 Exhibit {{EX_ADJ_BAND}}。"),
        src_extra=("指引取自各年最后一份季度业绩 8-K EX-99.1 的全年预测段；"
                   "实际值取自 XBRL companyfacts 的年度 EarningsPerShareDiluted。"),
    )


def annual_deviation(staging: dict) -> dict:
    """How far the year landed from its opening range and from its final one."""
    banded, _ = annual_records(staging)
    rows = [r for r in banded if r["actual_reported_eps"] is not None
            and r["first_guided"] and r["first_guided"].get("high")]
    labels = [f"FY{r['year']}" for r in rows]
    first = [pct_change(r["actual_reported_eps"],
                        mid(r["first_guided"]["low"], r["first_guided"]["high"])) for r in rows]
    last = [pct_change(r["actual_reported_eps"],
                       mid(r["last_guided"]["low"], r["last_guided"]["high"])) for r in rows]
    mean_first = statistics.fmean(abs(v) for v in first)
    mean_last = statistics.fmean(abs(v) for v in last)
    worst = max(first, key=abs)
    return {
        "ref": "EX_FY_DEV",
        "kind": "grouped_bars",
        "title": (f"同一年、两次指引：对年初那次平均绝对偏离 {mean_first:.1f}%，"
                  f"对年末那次 {mean_last:.1f}%"),
        "xlabels": labels,
        "xrot": 90,
        "groups": [
            {"name": "实际 vs 年初第一次指引中值", "color": "GOLD", "values": rounded(first, 2)},
            {"name": "实际 vs 当年最后一次指引中值", "color": "NAVY", "values": rounded(last, 2)},
        ],
        "bar_labels": False,
        "fmt": "pct1", "label_fmt": "pct1",
        "ylab": "% vs 指引中值",
        "note": (
            "两根柱的<b>差</b>就是一年里修订做的功。年初那次给的是十二个月的预测，"
            "年末那次发布时全年已经过去四分之三，所以后者更接近零是记账而不是预测能力 —— "
            "本站在 S&P Global 与穆迪两页上遇到过同样的形状。"
            f"窗口内对年初指引偏得最远的一年是 {labels[first.index(worst)]}，{worst:+.1f}%。"
            "注意这里两条腿都是<b>报告口径</b>：偏离里既有经营，也有汇率、税项与减值。"),
        "src_extra": "偏离 = 实际 ÷ 指引中值 − 1；两个中值分别取该年第一次与最后一次指引区间的中点。",
    }


def adjusted_rows(staging: dict) -> list[tuple[int, float, float, float | None]]:
    hist = staging["annual_guidance"]
    actuals = hist["annual_adjusted_eps_actual"]
    rows = []
    for record in hist["records"]:
        vintages = [v for v in record["vintages"] if v.get("adj_low") is not None]
        if not vintages:
            continue
        last = vintages[-1]
        rows.append((record["year"], last["adj_low"], last["adj_high"], actuals.get(str(record["year"]))))
    return rows


def annual_adjusted_band(staging: dict) -> dict:
    """The same years on the company's own adjusted definition."""
    rows = adjusted_rows(staging)
    labels = [f"FY{y}" for y, _, _, _ in rows]
    banded, _ = annual_records(staging)
    reported = tally([(r["actual_reported_eps"], r["last_guided"]["low"], r["last_guided"]["high"])
                      for r in banded])
    return delivery_band(
        "EX_ADJ_BAND", "全年调整后摊薄每股收益", labels,
        [lo for _, lo, _, _ in rows], [hi for _, _, hi, _ in rows],
        [a for _, _, _, a in rows],
        fmt="usd2", ylab="US$/股", unit="US$/股",
        venue="业绩新闻稿", period_word="年",
        timing="该年<b>当年内</b>",
        scope="（当年最后一次指引）",
        extra_note=(
            "<b>这张图和上面那张是同一家公司、同一批年份、同一份新闻稿里的同一张表</b>，"
            "唯一的差别是把公司自己点名并逐项计价的调整加回去。"
            f"报告口径那条自 {banded[0]['year']} 年起有 {reported[0]} 个完整年度，调整后这条自 {rows[0][0]} "
            "年公司开始在预测表里"
            "并列两行才有，所以窗口短得多 —— 这是披露的限制，不是本页的取舍。"),
        src_extra=("指引取自各年最后一份业绩 8-K EX-99.1 全年预测表的 Adjusted Diluted EPS 行；"
                   "实际值取自次年第四季新闻稿标题与预测表的上年对照列，两处逐年一致。"),
    )


def quarter_timing(staging: dict) -> tuple[int, int]:
    starts = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
    days = []
    for row in staging["quarterly_guidance"]:
        year, number = yq(row["guided_period"])
        start = datetime.date(year, *starts[number])
        days.append((datetime.date.fromisoformat(row["release_date"]) - start).days)
    return min(days), max(days)


def quarter_band(staging: dict) -> dict:
    rows = staging["quarterly_guidance"]
    labels = [r["period_label"] for r in rows]
    low = [r["low"] for r in rows]
    high = [r["high"] for r in rows]
    actual = [r["actual_eps"] for r in rows]
    first_adjusted = next(i for i, r in enumerate(rows) if r["basis"] != "reported")
    fastest, slowest = quarter_timing(staging)
    guided = {r["guided_period"] for r in rows}
    fourths = sorted(p for p in guided if yq(p)[1] == 4)
    points = [r for r in rows if r["point"]]
    pro_forma = [r for r in rows if r["basis"] == "pro_forma_adjusted"]
    q4_note = ""
    if len(fourths) == 1:
        exception = next(r for r in rows if r["guided_period"] == fourths[0])
        last_year = yq(rows[-1]["guided_period"])[0]
        silent = [y for y in range(yq(fourths[0])[0] + 1, last_year) if f"{y}Q4" not in guided]
        if silent:
            q4_note = (f"<b>横轴上没有 {silent[0]} 到 {silent[-1]} 的任何第四季，这不是缺数据</b>："
                       "PMI 只指引第一、二、三季，从不指引第四季 —— 唯一的例外是 "
                       f"{cn_quarter(fourths[0], '季')}"
                       + (f"，那一次还是个单点（「约 US${exception['low']:.2f}」）而不是区间。"
                          if exception["point"] else "。"))
    exceptions = []
    if pro_forma:
        years = sorted({yq(r["guided_period"])[0] for r in pro_forma})
        numbers = "、".join(CN_Q[yq(r["guided_period"])[1]] for r in pro_forma)
        if len(years) == 1:
            exceptions.append(f"{years[0]} 年第{numbers}季那{cn_count(len(pro_forma))}格还是剔除俄罗斯与乌克兰的 "
                              "pro forma 口径")
    # 2023Q1 was guided on reported EPS again, between the pro forma quarters and
    # the switch to adjusted, so the right-hand segment is not all adjusted.
    back = [r for r in rows[first_adjusted:] if r["basis"] == "reported"]
    if back:
        exceptions.append("、".join(cn_quarter(r["guided_period"], "季") for r in back)
                          + f"那{cn_count(len(back))}格又回到报告口径")
    pro_forma_note = "，".join(exceptions) + " —— " if exceptions else ""
    band = delivery_band(
        "EX_Q_BAND", "下季每股收益", labels, low, high, actual,
        fmt="usd2", ylab="US$/股", unit="US$/股",
        venue="业绩新闻稿",
        timing=f"该季<b>开始后 {fastest}–{slowest} 天</b>",
        break_at=first_adjusted,
        break_label="指引口径改为调整后",
        extra_note=(
            q4_note
            + f"窗口内被指引的 {len(rows)} 个季度里有 {len(points)} 个是单点，图上因此有"
            + f"{cn_count(len(points))}格没有宽度。左段的指引口径是<b>报告</b>每股收益，右段是<b>调整后</b>每股收益，"
            + pro_forma_note
            + "实际值一律按各自当期的口径取，不跨口径比较。"),
        src_extra=("指引取自各季业绩 8-K EX-99.1 全年预测假设段的最后一条；实际值中报告口径"
                   "取自 companyfacts，调整后与 pro forma 口径取自随后那份新闻稿的标题与"
                   "EPS 调节表。"),
    )
    return band


def quarter_deviation(staging: dict) -> dict:
    rows = [r for r in staging["quarterly_guidance"] if r["actual_eps"] is not None]
    labels = [r["period_label"] for r in rows]

    def leg(reported: bool):
        return rounded([
            pct_change(r["actual_eps"], mid(r["low"], r["high"]))
            if ((r["basis"] == "reported") == reported) else None
            for r in rows], 2)

    rep, adj = leg(True), leg(False)
    rep_vals = [v for v in rep if v is not None]
    adj_vals = [v for v in adj if v is not None]
    rep_rows = [r for r in rows if r["basis"] == "reported"]
    adj_rows = [r for r in rows if r["basis"] != "reported"]
    misses = [r for r in rep_rows if r["actual_eps"] < r["low"]]
    note = "同一家公司、同一段时间、同一份新闻稿里的同一句话，换个口径就换个分布。"
    note += f"报告口径那 {len(rep_rows)} 个季度里" + ("有正有负，" if min(rep_vals) < 0 < max(rep_vals) else "")
    if len(misses) == 1 and misses[0]["guided_period"] == "2021Q2":
        note += f"唯一一次跌破下限是 {cn_quarter('2021Q2', '季')} —— {Q2_2021_STORY}。"
    elif misses:
        note += "跌破下限的有 " + "、".join(r["period_label"] for r in misses) + "。"
    else:
        note += "没有一次跌破下限。"
    n, above, inside, below = tally([(r["actual_eps"], r["low"], r["high"]) for r in adj_rows])
    if above == n:
        note += f"调整后口径那 {n} 个季度<b>没有一次落在区间之内</b>，全部高于上限。"
    else:
        note += f"调整后口径那 {n} 个季度里 {above} 季高于上限、{inside} 季落在区间内、{below} 季跌破下限。"
    return {
        "ref": "EX_Q_DEV",
        "kind": "grouped_bars",
        "title": (f"下季指引的偏离，按口径分开：报告口径 {len(rep_vals)} 季平均 "
                  f"{statistics.fmean(rep_vals):+.1f}%，调整后口径 {len(adj_vals)} 季平均 "
                  f"{statistics.fmean(adj_vals):+.1f}%"),
        "xlabels": labels,
        "xrot": 90,
        "groups": [
            {"name": "报告口径季度", "color": "GOLD", "values": rep},
            {"name": "调整后口径季度", "color": "NAVY", "values": adj},
        ],
        "bar_labels": False,
        "fmt": "pct1", "label_fmt": "pct1",
        "ylab": "% vs 指引中值",
        "note": note,
        "src_extra": "偏离 = 实际 ÷ 指引中值 − 1；单点指引的中值即该点。",
    }


def currency_moves(staging: dict) -> list[tuple[int, float, float, list[dict]]]:
    rows = []
    for record in staging["annual_guidance"]["records"]:
        vs = [v for v in record["vintages"]
              if v.get("adj_low") is not None and v.get("xfx_low") is not None]
        if len(vs) < 2:
            continue
        # FY2022's two rows sat on different bases -- the dollar band was the
        # group and the ex-currency band the pro forma (ex Russia and Ukraine)
        # -- so subtracting one from the other would compare two companies.
        if record["year"] == 2022:
            continue
        rows.append((
            record["year"],
            mid(vs[-1]["adj_low"], vs[-1]["adj_high"]) - mid(vs[0]["adj_low"], vs[0]["adj_high"]),
            mid(vs[-1]["xfx_low"], vs[-1]["xfx_high"]) - mid(vs[0]["xfx_low"], vs[0]["xfx_high"]),
            vs,
        ))
    return rows


def currency_path(staging: dict) -> dict:
    """How far the dollar guidance moved in a year against the ex-currency one."""
    rows = currency_moves(staging)
    labels = [f"FY{y}" for y, _, _, _ in rows]
    opposite = [(y, d, x) for y, d, x, _ in rows if d * x < 0]
    same = [y for y, d, x, _ in rows if d * x > 0]
    listed = "、".join(f"FY{y}（美元口径 {minus_sign(f'{d:+.2f}')}、剔除汇率 {minus_sign(f'{x:+.2f}')}）"
                       for y, d, x in opposite)
    note = ("两条腿都是公司自己在同一张预测表里印出来的行：Adjusted Diluted EPS 与 "
            "Adjusted Diluted EPS, excluding currency，中间隔着一行 Less Currency。")
    mostly_opposite = len(opposite) * 2 > len(rows)
    if mostly_opposite:
        note += (f"<b>它们经常朝相反方向走</b>：{cn_count(len(rows))}年里有{cn_count(len(opposite))}年方向相反 —— "
                 f"{listed}。")
    elif opposite:
        note += (f"<b>它们走得常常不一样</b>：{cn_count(len(rows))}年里方向相反的只有 {listed}"
                 + ("，更常见的是同向而幅度不同 —— " if len(same) * 2 > len(rows) else "。"))
    else:
        note += "<b>它们的方向一致，幅度不同</b>："
    example = next(((d, x) for y, d, x, _ in rows if y == 2024), None)
    if example and example[1] > example[0] > 0 and not mostly_opposite:
        note += (f"FY2024 剔除汇率的指引一年抬了 US${example[1]:.2f}，美元口径只抬了 "
                 f"US${example[0]:.2f}，差额被汇率吃掉；")
    year, dollar, _, vintages = rows[-1]
    bands = {(v["xfx_low"], v["xfx_high"]) for v in vintages}
    open_year = not any(r["year"] == year and r["actual_reported_eps"] is not None
                        for r in staging["annual_guidance"]["records"])
    if open_year and len(bands) == 1:
        low, high = next(iter(bands))
        note += (f"FY{year} 到目前为止剔除汇率的区间{cn_count(len(vintages))}次发布<b>逐字未动</b>"
                 f"（US${low:.2f}–{high:.2f}），而美元口径的中值{'降' if dollar < 0 else '升'}了 "
                 f"US${abs(dollar):.2f}。")
    note += ("这解释了 PMI 新闻稿标题里反复出现的那句「仅因汇率调整全年预测」—— "
             "它不是修辞，是这张表里可以逐分核对的算术。"
             "FY2022 不在图上：那三期的美元行是集团口径而剔除汇率行是剔除俄乌的 pro forma 口径，"
             "相减等于把两家公司相减。")
    return {
        "ref": "EX_FX",
        "kind": "grouped_bars",
        "title": ("年内指引移动了多少：美元口径与剔除汇率口径，"
                  f"{labels[0]}–{labels[-1]} 共 {len(labels)} 年"
                  "（FY2022 两行口径不可比，不在图上）"),
        "xlabels": labels,
        "groups": [
            {"name": "调整后 EPS 指引中值移动（美元口径）", "color": "BLUE",
             "values": rounded([d for _, d, _, _ in rows], 3)},
            {"name": "同一指引剔除汇率后的移动", "color": "NAVY",
             "values": rounded([x for _, _, x, _ in rows], 3)},
        ],
        "bar_labels": True,
        "fmt": "usd2", "label_fmt": "usd2",
        "ylab": "US$/股（年末指引中值 − 年初指引中值）",
        "note": note,
        "src_extra": "各年第一次与最后一次业绩 8-K EX-99.1 全年预测表的两行中值之差。",
    }


# ── section two: what moved this quarter ───────────────────────────────────


def bridge_blocks(staging: dict) -> tuple[dict, dict | None, str]:
    bridge = staging["revenue_bridge"]
    periods = bridge["periods"]
    ending_on_page_quarter(staging, "revenue_bridge", periods)
    previous = bridge[periods[-2]] if len(periods) > 1 else None
    return bridge[periods[-1]], previous, periods[-1]


def segment_shape(name: str, parts: dict, index: int, first: bool = False) -> str:
    """What one segment's revenue change was made of, in the company's own bridge."""
    moves = {key: parts[key][index] for key in ("price", "volume_mix_other", "currency")}
    total = parts["end"][index] - parts["base"][index]
    positive = sorted(((v, k) for k, v in moves.items() if v > 0), reverse=True)
    negative = [k for k in ("price", "volume_mix_other") if moves[k] < 0]
    if total > 0 and positive:
        value, key = positive[0]
        text = (f"{name}{'的增量' if first else ''}{'几乎全部' if value >= 0.9 * total else '主要'}"
                f"来自{BRIDGE_PARTS[key]}")
        if len(negative) == 2:
            text += "而价格和量与结构都是负的"
        elif negative:
            text += f"而{BRIDGE_PARTS[negative[0]]}是负的"
        return text
    lifted = [k for k, v in moves.items() if v > 0]
    text = f"{name}净减少 US${abs(total):,.0f}M"
    if negative:
        text += "：" + "、".join(f"{BRIDGE_PARTS[k]}是负的（−US${abs(moves[k]):,.0f}M）" for k in negative)
    if lifted:
        text += (f"，{'和'.join(BRIDGE_PARTS[k] for k in lifted)}只托回 "
                 f"US${sum(moves[k] for k in lifted):,.0f}M")
    return text


def money_m(value: float) -> str:
    """``-346`` → ``−US$346M``; ``140`` → ``+US$140M``."""
    return f"{'−' if value < 0 else '+'}US${abs(value):,.0f}M"


def printed_split(quarter: dict) -> tuple[float, float] | None:
    """The group column of a bridge that printed Volume/Mix and Other as two lines.

    The first 2026 release printed them apart and the second as one line, so the
    two quarters compare only on the sum; the parts are kept to say so.
    """
    split = quarter.get("printed_split")
    if split is None:
        return None
    for i in range(len(quarter["volume_mix_other"])):
        if split["volume_mix"][i] + split["other"][i] != quarter["volume_mix_other"][i]:
            raise ValueError("revenue_bridge printed_split does not add up to volume_mix_other")
    return split["volume_mix"][0], split["other"][0]


def organic_rate(quarter: dict) -> float:
    """The group's organic growth from its own bridge: price plus volume/mix/other over the base,
    i.e. the change excluding currency and acquisitions -- the definition the release uses."""
    return (quarter["price"][0] + quarter["volume_mix_other"][0]) / quarter["base"][0] * 100


def highlights_description(staging: dict) -> str:
    """Section two's description (plain text: it is escaped)."""
    seg = staging["segments"]
    us = seg["adjusted_gross_margin_pct"]["us"]
    ago = year_ago_index(seg["periods"], len(seg["periods"]) - 1)
    parts = ["增量的来源（价格、量与结构、汇率各贡献多少）", "三个报告分部的分化",
             f"美国分部调整后毛利率同比 {minus_sign(signed(us[-1] - us[ago], 1, 'pp'))}",
             "美国 ZYN 零售出货" + ("从有百分比到只剩措辞" if zyn_view(staging)["words_only"] else "的增速")]
    return ("按本季本地分析稿第 1 节与第 7 节的结论排：" + "、".join(parts) + "。"
            "分析稿里的估值读数（当前年市盈率与情景回报）本页不画 —— 本站不发布估值与评级；"
            "国际无烟毛利增速领先收入的那道剪刀差、有机经营利润增速与杠杆率放在第三节的阈值里。")


def revenue_bridge(staging: dict) -> dict:
    latest, previous, label = bridge_blocks(staging)
    year, number = yq(label)
    columns = ["PMI 合计", "国际无烟", "国际组合烟草", "美国"]
    walks = [abs(latest["base"][i] + latest["price"][i] + latest["volume_mix_other"][i]
                 + latest["acq_div"][i] + latest["currency"][i] - latest["end"][i]) for i in range(4)]
    total = latest["end"][0] - latest["base"][0]
    note = ("这是公司自己印的分解，四段相加等于本季与去年同期的差额，误差不超过四舍五入的 US$1M。"
            if max(walks) <= 1.0 else
            f"这是公司自己印的分解，四段相加与本季和去年同期的差额最多差 US${max(walks):,.0f}M。")
    shapes = [segment_shape(n, latest, i, first=(i == 1))
              for i, n in ((1, "国际无烟"), (2, "国际组合烟草"), (3, "美国"))]
    note += "<b>三个分部的形状完全不同</b>：" + "，".join(shapes) + "。"
    if latest["price"][0] + latest["currency"][0] >= 0.8 * total > 0:
        note += "把集团那一列单独读，会把「涨价 + 汇率」读成「增长」。"
    if previous is not None:
        before, now = previous["volume_mix_other"][0], latest["volume_mix_other"][0]
        turn = "本季转正" if before < 0 < now else "本季转负" if before > 0 > now else "本季仍然同号"
        split = printed_split(previous)
        where = (f"那张表把量与结构（{money_m(split[0])}）和其他（{money_m(split[1])}）分两行印，合起来对集团是 "
                 if split else "同一张表里量与结构对集团是 ")
        note += f"上一季（{display(staging['revenue_bridge']['periods'][-2])}）{where}{money_m(before)}，{turn}。"
        was, is_now = organic_rate(previous), organic_rate(latest)
        note += ("按同一张表算，集团有机增速（剔除汇率与收购处置）"
                 + (f"从上一季的 {was:.1f}% {'升到' if is_now > was else '降到'}本季的 {is_now:.1f}%。"
                    if f"{was:.1f}" != f"{is_now:.1f}" else f"上一季与本季都是 {is_now:.1f}%。"))
    return {
        "ref": "EX_BRIDGE",
        "kind": "grouped_bars",
        "title": (f"本季净收入增量 US${total:,.0f}M 的来源："
                  f"价格 US${latest['price'][0]:,.0f}M、汇率 US${latest['currency'][0]:,.0f}M、"
                  f"量与结构 US${latest['volume_mix_other'][0]:,.0f}M"),
        "xlabels": columns,
        "groups": [
            {"name": "价格", "color": "NAVY", "values": rounded(latest["price"])},
            {"name": "量、结构与其他", "color": "BLUE", "values": rounded(latest["volume_mix_other"])},
            {"name": "收购与处置", "color": "GRAY", "values": rounded(latest["acq_div"])},
            {"name": "汇率", "color": "GOLD", "values": rounded(latest["currency"])},
        ],
        "bar_labels": True,
        "fmt": "f0c", "label_fmt": "f0c",
        "ylab": f"US$M（vs {display(f'{year - 1}Q{number}')}）",
        "note": note,
        "src_extra": (f"{cn_quarter(label)}业绩 8-K EX-99.1「{EN_Q[number]}-Quarter {year} Operating Review」"
                      "净收入表。"),
    }


def quarter_years(labels: list[str]) -> str:
    """``'2026'`` or ``'2025–2026'``: whose quarterly releases a series was read from
    (a release is named for its quarter, so Q4 2026's February 8-K is a 2026 one)."""
    years = sorted({yq(p)[0] for p in labels})
    return f"{years[0]}" if len(years) == 1 else f"{years[0]}–{years[-1]}"


def segment_releases(staging: dict) -> str:
    """The releases the segment table was read from: each new-basis quarter's own
    release, which also printed the year-ago column. ``'2026 年第一、二季度业绩 8-K
    EX-99.1 的经营回顾表与同期 10-Q 分部附注'``."""
    own = [p for p in staging["segments"]["periods"] if yq(p) >= yq(NEW_SEGMENTS_FROM)]
    years = sorted({yq(p)[0] for p in own})
    if len(years) == 1:
        span = f"{years[0]} 年第" + "、".join(CN_Q[yq(p)[1]] for p in own) + "季度"
    else:
        span = f"{cn_quarter(own[0])}至{cn_quarter(own[-1])}各季"
    report = "10-Q / 10-K" if any(yq(p)[1] == 4 for p in own) else "10-Q"
    return f"{span}业绩 8-K EX-99.1 的经营回顾表与同期 {report} 分部附注"


def recast_block(staging: dict) -> dict | None:
    """The filing that reprinted earlier quarters on the current segments, with the
    segment quarters this page took from it (``taken``)."""
    recast = staging["segments"].get("recast_filing")
    if not recast:
        return None
    first, last = yq(recast["first"]), yq(recast["last"])
    taken = [p for p in staging["segments"]["periods"] if first <= yq(p) <= last]
    return {**recast, "taken": taken}


def recast_source(staging: dict, tables: str) -> str:
    """``'2023–2025 年各季取自 2026-03-13 按新分部重印的 8-K（…）；'`` -- empty when none was taken."""
    recast = recast_block(staging)
    if recast is None or not recast["taken"]:
        return ""
    return (f"{quarter_years(recast['taken'])} 年各季取自 {recast['date']} 按新分部重印的 8-K"
            f"（{recast['accession']}，{tables}，未经审计补充信息）；")


def year_ago_index(labels: list[str], index: int) -> int | None:
    year, number = yq(labels[index])
    target = (year - 1, number)
    return next((i for i, label in enumerate(labels) if yq(label) == target), None)


def segment_revenue(staging: dict) -> dict:
    seg = staging["segments"]
    ending_on_page_quarter(staging, "segments", seg["periods"])
    rev = seg["net_revenues_usd_m"]
    ago = year_ago_index(seg["periods"], len(seg["periods"]) - 1)
    largest = max(SEG_KEYS, key=lambda k: rev[k][-1])
    falling = [k for k in SEG_KEYS if ago is not None and rev[k][-1] < rev[k][ago]]
    title = (f"三个报告分部的净收入：{SEG_NAMES[largest]}仍是最大一块（本季 "
             f"US${rev[largest][-1]:,.0f}M）")
    if len(falling) == 1:
        title += f"，{SEG_NAMES[falling[0]]}是唯一同比下降的（US${rev[falling[0]][-1]:,.0f}M）"
    elif falling:
        title += "，同比下降的有" + "、".join(SEG_NAMES[k] for k in falling)
    long = staging["long"]
    total = dict(zip(long["periods"], long["net_revenues_usd_m"]))
    gaps = [abs(sum(rev[k][i] for k in SEG_KEYS) - total[p]) for i, p in enumerate(seg["periods"])]
    recast = recast_block(staging)
    n = len(seg["periods"])
    return {
        "ref": "EX_SEG_REV",
        "kind": "grouped_bars",
        "title": title,
        "xlabels": seg["period_labels"],
        "groups": [{"name": SEG_NAMES[k], "color": SEG_COLORS[k], "values": rounded(rev[k])}
                   for k in SEG_KEYS],
        # a label on every bar reads at a few quarters, not at three bars times a dozen
        "bar_labels": n <= 8,
        "fmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M",
        "note": (
            f"现行三个分部自 {cn_quarter(NEW_SEGMENTS_FROM)}起启用，"
            + (f"{cn_quarter(recast['taken'][0])}至 {cn_quarter(recast['taken'][-1])}取自公司 {recast['date']} "
               "按新分部的未经审计重印，" if recast and recast["taken"] else "")
            + "本页不把这条线往前接到它取代的四个地理分部上 —— 那会是把两套口径画成一条。"
            + (f"三个分部相加等于合并净收入，{cn_count(n)}个季度逐季核对无差。" if max(gaps) < 0.5 else
               f"三个分部相加与合并净收入在{cn_count(n)}个季度里最多差 US${max(gaps):,.0f}M。")),
        "src_extra": (recast_source(staging, recast["tables"]["net_revenues"] if recast else "")
                      + f"{segment_releases(staging)}。"),
    }


def segment_margin(staging: dict) -> dict:
    seg = staging["segments"]
    gm = seg["adjusted_gross_margin_pct"]
    labels = seg["period_labels"]
    last = len(labels) - 1
    ago = year_ago_index(seg["periods"], last)
    us_gap = gm["us"][-1] - gm["us"][ago]
    pairs = [(i, year_ago_index(seg["periods"], i)) for i in range(len(labels))]
    pairs = [(i, j) for i, j in pairs if j is not None]
    rising = {k: gm[k][-1] > gm[k][ago] for k in ("pmi",) + SEG_KEYS}
    story = block(staging, "quarter_story")
    # The run of same-direction year-on-year moves that ends at the page's quarter:
    # the whole record would be a dozen clauses, and the run is the part in play.
    moves = [(i, gm["us"][i] - gm["us"][j]) for i, j in pairs]
    run = [moves[-1]]
    for i, move in reversed(moves[:-1]):
        if (move > 0) - (move < 0) != (run[0][1] > 0) - (run[0][1] < 0):
            break
        run.insert(0, (i, move))
    history = "，".join(
        f"{labels[i]} 同比 " + (signed(move, 1, 'pp') if i == last else minus_sign(signed(move, 1, 'pp')))
        for i, move in run)
    direction = "下降" if run[-1][1] < 0 else "上升" if run[-1][1] > 0 else "持平"
    history = (f"已连续{cn_count(len(run))}个季度同比{direction}：{history}" if len(run) > 1
               else history)
    if rising["pmi"] and rising["international_smoke_free"] and rising["international_combustibles"] \
            and not rising["us"]:
        tension = ("<b>这是本季真正的张力，也是集团数字看不出来的那一层。</b>"
                   "集团调整后毛利率同比还在抬，国际无烟与国际组合烟草两条都在抬，"
                   f"只有美国一条在塌，{history}。"
                   + story.get("us_gross_margin_reason", "")
                   + "所以「毛利率在改善」和「美国单位经济性在恶化」这两句话同时为真，"
                   "而后者是估值的边际变量。")
    else:
        tension = f"美国分部调整后毛利率{history}。" + story.get("us_gross_margin_reason", "")
    recast = recast_block(staging)
    return {
        "ref": "EX_SEG_GM",
        "kind": "lines",
        "title": (f"分部调整后毛利率：国际无烟 {gm['international_smoke_free'][-1]:.1f}%，"
                  f"美国 {gm['us'][-1]:.1f}%，同比 {us_gap:+.1f}pp"),
        "xlabels": labels,
        "series": (
            [{"name": "PMI 合计", "values": rounded(gm["pmi"]), "color": "GRAY"}]
            + [{"name": SEG_NAMES[k], "values": rounded(gm[k]), "color": SEG_COLORS[k]}
               for k in SEG_KEYS]),
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
        "ylab": "调整后毛利率 %",
        "note": tension,
        "src_extra": (recast_source(staging, recast["tables"]["adjusted_gross_margin"] if recast else "")
                      + f"{segment_releases(staging).split('业绩 8-K')[0]}业绩 8-K EX-99.1 经营回顾的毛利表。"),
    }


def zyn_view(staging: dict) -> dict:
    zyn = staging["zyn"]
    ending_on_page_quarter(staging, "zyn", zyn["periods"])
    values, words = zyn["offtake_yoy_pct"], zyn["offtake_words"]
    if not len(values) == len(words) == len(zyn["shipment_words"]) == len(zyn["periods"]):
        raise ValueError("series `zyn`: offtake_yoy_pct, offtake_words and shipment_words need one entry per quarter")
    for value, word, label in zip(values, words, zyn["period_labels"]):
        if value is None and not word:
            raise ValueError(f"series `zyn` {label}: no offtake figure and no offtake words")
    known = [(v, label) for v, label in zip(values, zyn["period_labels"]) if v is not None]
    return {"zyn": zyn, "values": values, "known": known, "words_only": values[-1] is None,
            "words": words[-1]}


def zyn_offtake(staging: dict) -> dict:
    view = zyn_view(staging)
    zyn, values, known = view["zyn"], view["values"], view["known"]
    peak = max(v for v, _ in known)
    latest = known[-1][0]
    title = "美国 ZYN 零售出货同比（公司引用的 Nielsen 口径）："
    title += (f"从 {peak:.0f}% 降到 {latest:.0f}%" if latest < peak else f"本季 {latest:.0f}%")
    if view["words_only"]:
        title += "，最后一格公司只给了措辞"
    chart = {
        "ref": "EX_ZYN",
        "kind": "bars_labeled",
        "title": title,
        "xlabels": zyn["period_labels"],
        "values": rounded(values),
        "fmt": "pct1", "label_fmt": "pct1",
        "ylab": "同比 %",
        "note": (
            ("<b>最后一格是空的，不是零。</b>公司在本季新闻稿里把美国 ZYN 的零售出货描述为"
             f"「{view['words']}」，没有给百分比，所以这里留空而不是填 0 —— "
             "填 0 会把一句措辞变成一个可以进模型的数。" if view["words_only"] else "")
            + "出货量（发给渠道）与零售出货（卖给消费者）在这段时间里差得很远，"
            "因为渠道库存先补后去。公司披露的出货口径依次是："
            + "；".join(f"{label} {words}"
                          for label, words in zip(zyn["period_labels"],
                                                  zyn["shipment_words"])) + "。"
            "两条口径里，判断需求要看后者。"),
        "src_extra": "各季业绩 8-K EX-99.1 正文；Nielsen 为公司引用的第三方零售监测口径。",
    }
    if view["words_only"]:
        chart["annot"] = f"{zyn['period_labels'][-1]}：公司口径为「{view['words']}」，无数字"
    return chart


# ── section three: the thresholds this quarter's note set for the next ─────


# Roles the note gives a line; a warning-type line is drawn red, the others gold.
WARNING_ROLES = ("警示线", "受损线", "转弱线", "重新评估线", "年末线")


def role_of(metric: str) -> str:
    """「美国分部调整后毛利率（改善线）」→「改善线」."""
    return metric.split("（")[1].rstrip("）") if "（" in metric else ""


def segment_margin_now(staging: dict, key: str) -> float:
    seg = staging["segments"]
    ending_on_page_quarter(staging, "segments", seg["periods"])
    return seg["adjusted_gross_margin_pct"][key][-1]


def leverage_now(staging: dict) -> float:
    lev = staging["leverage"]
    ending_on_page_quarter(staging, "leverage", lev["periods"])
    return lev["net_debt_to_adjusted_ebitda"][-1]


READINGS.update({
    "zyn_share": lambda s: printed_rate(s, "zyn_retail_value_share_pct"),
    "segment_gm_us": lambda s: segment_margin_now(s, "us"),
    "segment_gm_isf": lambda s: segment_margin_now(s, "international_smoke_free"),
    "isf_organic_growth": lambda s: printed_rate(s, "isf_organic_revenue_growth_pct"),
    # both rates are printed to one decimal, so their difference is exact at one
    "isf_gp_lead": lambda s: round(printed_rate(s, "isf_organic_gross_profit_growth_pct")
                                   - printed_rate(s, "isf_organic_revenue_growth_pct"), 1),
    "leverage": leverage_now,
})

# Where each current reading was printed, for the overview's source line.
READING_SOURCES = {
    "segment_gm_us": "分部毛利率取自业绩 8-K EX-99.1 的毛利表",
    "segment_gm_isf": "分部毛利率取自业绩 8-K EX-99.1 的毛利表",
    "leverage": "杠杆率取自业绩 8-K EX-99.2 的杠杆率明细表",
}
PRINTED_KEYS = {
    "zyn_share": "zyn_retail_value_share_pct",
    "isf_organic_growth": "isf_organic_revenue_growth_pct",
    "isf_gp_lead": "isf_organic_gross_profit_growth_pct",
    "organic_oi_growth": "organic_operating_income_growth_pct",
}
AWAITING = ("next_quarter_eps", "h2_ocf")


def kpi_entries(staging: dict) -> tuple[dict, list[dict], list[dict]]:
    """This quarter's note's thresholds for the next quarter.

    Returns the block, the entries with a current figure (the headroom bars),
    and the entries whose current reading is only the company's words.
    """
    kpi = stamped_block(staging, "next_kpi", page_period(staging))
    if kpi is None:
        raise ValueError("series `next_kpi` is missing: every quarter carries its thresholds")
    entries, worded = [], []
    for entry in kpi["quantified"]:
        if entry["measure"] not in READINGS:
            raise ValueError(f"next_kpi entry {entry['metric']!r}: this page does not know how to "
                             f"measure {entry['measure']!r}")
        value = READINGS[entry["measure"]](staging)
        if value is None:
            words = page_quarter_offtake(staging)[1] if entry["measure"] == "zyn_offtake" else None
            if not words:
                raise ValueError(f"next_kpi entry {entry['metric']!r} has neither a figure nor words this quarter")
            worded.append({**entry, "words": words})
        else:
            entries.append({**entry, "current": value})
    for entry in kpi.get("awaiting", []):
        if entry["measure"] not in AWAITING:
            raise ValueError(f"next_kpi awaiting entry {entry['metric']!r}: this page does not know how to "
                             f"measure {entry['measure']!r}")
    return kpi, entries, worded


def h2_ocf(staging: dict) -> tuple[list[int], list[float], dict | None]:
    """Second-half operating cash flow by year (full year − first half, both filed), and
    the second half this year's forecast implies once the first half is filed."""
    half = staging["half_year_cash"]
    annual = dict(zip(staging["annual"]["years"], staging["annual"]["operating_cash_flow_usd_m"]))
    first = dict(zip(half["years"], half["h1_operating_cash_flow_usd_m"]))
    years = [y for y in half["years"] if y in annual]
    implied = None
    other = block(staging, "guidance_other")
    open_year = half["years"][-1]
    if open_year not in annual and "operating_cash_flow_usd_m" in other:
        guide = other["operating_cash_flow_usd_m"]
        implied = {"year": open_year, "guide": guide, "first_half": first[open_year],
                   "second_half": guide - first[open_year]}
    return years, [annual[y] - first[y] for y in years], implied


def awaiting_text(staging: dict, entry: dict) -> str:
    """Why a threshold has no reading yet, with what the company already said about it."""
    head = f"{entry['metric']} {threshold_words(entry)} —— "
    if entry["measure"] == "next_quarter_eps":
        upcoming = next_quarter_guidance(staging)
        if upcoming is None:
            return head + "要等下一份新闻稿；公司没有给这一季的指引"
        low, high = upcoming["low"], upcoming["high"]
        edge = ("，这条线正是指引上沿" if abs(entry["threshold"] - high) < 0.005 else
                "，这条线正是指引下沿" if abs(entry["threshold"] - low) < 0.005 else "")
        return (head + f"要等 {cn_quarter(upcoming['guided_period'])}的新闻稿；公司自己的指引是 "
                f"US${low:.2f}–{high:.2f}（画在第一节的 Exhibit {{EX_Q_BAND}} 上）{edge}")
    _, _, implied = h2_ocf(staging)
    text = head + "按全年结算，要等年报"
    if implied is not None:
        gap = pct_change(implied["second_half"], entry["threshold"])
        text += (f"；公司全年约 US${implied['guide']:,.0f}M 的指引减去上半年 US${implied['first_half']:,.0f}M，"
                 f"隐含下半年 US${implied['second_half']:,.0f}M（D），{'高于' if gap >= 0 else '低于'}这条线 "
                 f"{abs(gap):.1f}%（见下图）")
    return text


def not_tracked_text(kpi: dict) -> str:
    items = kpi.get("not_tracked", [])
    if not items:
        return ""
    return (f"另有{cn_count(len(items))}条本页<b>不接入</b>："
            + "".join(f"（{i}）<b>{x['name']}</b> —— {x['why']}" for i, x in enumerate(items, 1)))


def threshold_series(entries: list[dict], length: int) -> list[dict]:
    """One flat line per threshold on a metric, warning-type lines in red."""
    return [{"name": f"{role_of(e['metric']) or '阈值'}（{threshold_words(e)}）",
             "values": [e["threshold"]] * length,
             "color": "RED" if role_of(e["metric"]) in WARNING_ROLES else "GOLD"}
            for e in entries]


def standing(entries: list[dict]) -> str:
    """「离改善线 67.0% 还差 1.6pp、在警示线 63.0% 之上 2.4pp」 in the metric's own unit."""
    parts = []
    for e in entries:
        gap = e["current"] - e["threshold"]
        safe = headroom(e["direction"], e["threshold"], e["current"]) >= 0
        unit = "pp" if e["unit"] == "pct" else ""
        size = f"{abs(gap):.1f}{unit}" if unit else unit_text(e["unit"], abs(gap))
        where = ("之上" if e["direction"] == "up" else "之下") if safe else ""
        parts.append(f"在{role_of(e['metric'])} {unit_text(e['unit'], e['threshold'])} {where} {size}" if safe
                     else f"离{role_of(e['metric'])} {unit_text(e['unit'], e['threshold'])} 还差 {size}")
    return "、".join(parts)


def segment_line(staging: dict, entries: list[dict]) -> dict:
    key = {"segment_gm_us": "us", "segment_gm_isf": "international_smoke_free"}[entries[0]["measure"]]
    seg = staging["segments"]
    values = seg["adjusted_gross_margin_pct"][key]
    kept = [k for k, v in enumerate(values) if v is not None]
    values = [values[k] for k in kept]
    xlab = [seg["period_labels"][k] for k in kept]
    periods = [seg["periods"][k] for k in kept]
    recast = recast_block(staging)
    from_recast = [p for p in periods if recast and p in recast["taken"]]
    own = [p for p in periods if yq(p) >= yq(NEW_SEGMENTS_FROM)]
    window = (f"序列从现行分部口径印出的最早一季（{xlab[0]}）起画，"
              f"{quarter_years(from_recast)} 年取自 {recast['date']} 按新分部的未经审计重印。"
              if from_recast else
              f"这条线只有{cn_count(len(values))}个季度：本页只接了新闻稿印出的季度与它们的上年对照列。")
    name = base_name(entries[0]["metric"])
    current = entries[0]["current"]
    chart = threshold_exhibit(
        f"{name}：下季阈值 " + " 与 ".join(unit_text(e["unit"], e["threshold"]) for e in entries)
        + f"，当前 {unit_text(entries[0]['unit'], current)}",
        xlab, rounded(values), entries[0]["threshold"],
        fmt="pct1", ylab="调整后毛利率 %", actual_name=name, threshold_name="阈值",
        note=("阈值取自本季本地分析稿第 8 节，不是公司指引。"
              + f"{cn_quarter(page_period(staging))} {unit_text(entries[0]['unit'], current)}，"
              + standing(entries) + "。" + window),
        src_extra=((recast_source(staging, recast["tables"]["adjusted_gross_margin"]) if from_recast else "")
                   + f"{quarter_years(own)} 年各季业绩 8-K EX-99.1；阈值取自本季本地分析稿第 8 节。"))
    chart["series"] = chart["series"][:1] + threshold_series(entries, len(xlab))
    return chart


def zyn_offtake_line(staging: dict, entries: list[dict]) -> dict:
    entry = entries[0]
    zyn = staging["zyn"]
    value, words = page_quarter_offtake(staging)
    known = [(v, label) for v, label in zip(zyn["offtake_yoy_pct"], zyn["period_labels"]) if v is not None]
    chart = threshold_exhibit(
        f"{base_name(entry['metric'])}：下季阈值 {unit_text(entry['unit'], entry['threshold'])}，"
        + (f"当前 {unit_text(entry['unit'], value)}" if value is not None else "当前只有措辞"),
        zyn["period_labels"], rounded(zyn["offtake_yoy_pct"]), entry["threshold"],
        fmt="pct1", ylab="同比 %", actual_name="美国 ZYN 零售出货同比（Nielsen）",
        threshold_name=f"{role_of(entry['metric'])}（{threshold_words(entry)}）",
        note=("阈值取自本季本地分析稿第 8 节第 1 行，不是公司指引；那一行的修复条件是零售出货与零售价值份额同时过线，"
              "份额两条在总览里。"
              + (f"<b>最后一格没有点</b>：本季公司只说「{words}」，没有给百分比，线停在有数字的最后一格"
                 f"（{known[-1][1]} 的 {known[-1][0]:.0f}%），总览因此不为这一条画柱，而不是把措辞折算成一个数。"
                 if value is None else "")),
        src_extra="各季业绩 8-K EX-99.1 正文；Nielsen 为公司引用的第三方零售监测口径；阈值取自本季本地分析稿第 8 节。")
    if value is None:
        chart["annot"] = f"{zyn['period_labels'][-1]}：公司口径为「{words}」，无数字"
    return chart


def leverage_line(staging: dict, entries: list[dict]) -> dict:
    entry = entries[0]
    lev = staging["leverage"]
    ending_on_page_quarter(staging, "leverage", lev["periods"])
    values, labels, debt = lev["net_debt_to_adjusted_ebitda"], lev["period_labels"], lev["net_debt_usd_m"]
    ebitda = lev["adjusted_ebitda_ttm_usd_m"]
    jumps = [values[i] - values[i - 1] for i in range(1, len(values))]
    big = jumps.index(max(jumps)) + 1
    peak = values.index(max(values))
    other = block(staging, "guidance_other")
    note = ("每一格是当季业绩新闻稿杠杆率明细表印出的比率（净债务 ÷ 滚动十二个月调整后 EBITDA），按当时的定义，"
            "未经事后重述；表里的净债务与调整后 EBITDA 相除，逐季都等于印出的比率。"
            f"最大的一跳在 {labels[big]}：{values[big - 1]:.2f}× → {values[big]:.2f}×，净债务从 "
            f"US${debt[big - 1]:,.0f}M 升到 US${debt[big]:,.0f}M"
            # fixed history, read in the 2022 fourth-quarter release (0001413329-23-000020)
            + ("，那一季 PMI 于 2022 年 11 月 11 日取得 Swedish Match 的控股权" if lev["periods"][big] == "2022Q4"
               else "")
            + f"；最高是 {labels[peak]} 的 {values[peak]:.2f}×。"
            + f"阈值取自本季本地分析稿第 8 节第 5 行，按年末结算：{staging['period_ends'][-1]} 的读数 "
            f"{values[-1]:.2f}×（净债务 US${debt[-1]:,.0f}M ÷ 调整后 EBITDA US${ebitda[-1]:,.0f}M），"
            + ("离 " if values[-1] > entry["threshold"] else "已在 ")
            + f"{unit_words(entry['unit'], entry['threshold'])}"
            + (f" 还差 {values[-1] - entry['threshold']:.2f}×" if values[-1] > entry["threshold"] else " 之下")
            + (f"；公司指引假设写的目标是年底接近 {other['net_debt_to_ebitda_target']:.1f}×"
               if "net_debt_to_ebitda_target" in other else "") + "。")
    return threshold_exhibit(
        f"净债务 / 调整后 EBITDA：下季阈值 {unit_words(entry['unit'], entry['threshold'])}（年末），"
        f"当前 {unit_words(entry['unit'], values[-1])}",
        labels, rounded(values), entry["threshold"],
        fmt="f2", ylab="倍", actual_name="净债务 / 调整后 EBITDA",
        threshold_name=f"{role_of(entry['metric'])}（{threshold_words(entry)}）",
        note=note,
        src_extra=("各季业绩 8-K 的杠杆率明细表（2016–2022 年在 EX-99.1，2023 年起在 EX-99.2）；"
                   "阈值取自本季本地分析稿第 8 节。"),
        xstep=LONG_STEP)


def h2_ocf_line(staging: dict, entry: dict) -> dict:
    years, second, implied = h2_ocf(staging)
    threshold = entry["threshold"]
    reached = [y for y, v in zip(years, second) if v >= threshold]
    record = (f"{cn_count(len(years))}年里只有 {reached[0]} 年达到" if len(reached) == 1 else
              f"{cn_count(len(years))}年里没有一年达到" if not reached else
              f"{cn_count(len(years))}年里有{cn_count(len(reached))}年达到")
    title = (f"下半年经营现金流：下季阈值 {unit_words(entry['unit'], threshold)}（年末结算），"
             + (f"今年指引隐含 US${implied['second_half']:,.0f}M（D）；" if implied is not None else "")
             + f"过去{record}")
    note = ("下半年 = 全年（10-K）− 上半年（第二季 10-Q），两条腿都是申报值。阈值取自本季本地分析稿第 8 节第 5 行，"
            "按全年结算。")
    if implied is not None:
        note += (f"公司 {implied['year']} 年全年经营现金流指引约 US${implied['guide']:,.0f}M，减去上半年 "
                 f"US${implied['first_half']:,.0f}M，隐含下半年 US${implied['second_half']:,.0f}M（D）。")
    note += (f"上半年与下半年的分配每年不同，所以同一个全年数可以对应很不一样的下半年：最近一年 {years[-1]} 的"
             f"下半年是 US${second[-1]:,.0f}M。")
    return threshold_exhibit(
        title, [f"H2 {y}" for y in years], rounded(second), threshold,
        fmt="f0c", ylab="US$M", actual_name="下半年经营现金流",
        threshold_name=f"{role_of(entry['metric'])}（{threshold_words(entry)}）",
        note=note,
        src_extra="各年 Form 10-K 与第二季 Form 10-Q 的现金流量表（XBRL companyfacts）；阈值取自本季本地分析稿第 8 节。")


LINES = {
    "zyn_offtake": zyn_offtake_line,
    "segment_gm_us": segment_line,
    "segment_gm_isf": segment_line,
    "leverage": leverage_line,
}


def next_section(staging: dict, kpi: dict, entries: list[dict], worded: list[dict]) -> list[dict]:
    awaiting = kpi.get("awaiting", [])
    unmeasurable = kpi.get("unmeasurable", [])
    total = len(kpi["quantified"]) + len(awaiting) + len(unmeasurable)
    short = [e for e in entries if headroom(e["direction"], e["threshold"], e["current"]) < 0]
    title = (f"下季 {total} 条阈值：有当前值的 {len(entries)} 条里 {len(entries) - len(short)} 条在安全侧"
             + (f"，{'、'.join(e['metric'] for e in short)}尚未达到" if short else ""))
    note = ("正值表示仍在安全侧。阈值逐字取自本季本地分析稿第 8 节「关键观察指标」，不是公司指引；"
            "同一个指标设了两条线的分开画。")
    if kpi.get("joint"):
        note += "分析稿里用「且 / 或」连起来的条件，这里拆成单条画，读的时候要合起来看：" + "；".join(kpi["joint"]) + "。"
    for e in worded:
        note += (f"<b>{e['metric']} {threshold_words(e)} 画不成柱</b>：本季公司只说「{e['words']}」，没有给百分比，"
                 "走势见下面那张线图。")
    for e in short:
        if e["measure"] == "leverage":
            note += (f"{e['metric']}按年末结算，柱子用的是 {staging['period_ends'][-1]} 的读数，"
                     "负值表示还没降到线下，不是已经越线。")
    # The organic operating-income lines are read on the quarter; the year to
    # date the same release prints can sit on the other side of them.
    oi_lines = [e for e in entries if e["measure"] == "organic_oi_growth"]
    ytd = block(staging, "quarter_printed").get("ytd_organic_operating_income_growth_pct")
    if oi_lines and ytd is not None and yq(page_period(staging))[1] > 1:
        under = [e for e in oi_lines if headroom(e["direction"], e["threshold"], ytd) < 0]
        note += (f"集团有机经营利润增速的柱用的是本季单季的 {oi_lines[0]['current']:.1f}%；同一份新闻稿印的年初至今累计是 "
                 f"{ytd:.1f}%，" + ("在两条线之上。" if not under else
                                   "低于" + "、".join(f"{role_of(e['metric'])} {unit_words(e['unit'], e['threshold'])}"
                                                      for e in under) + "。"))
    if awaiting:
        note += (f"要等下一份新闻稿或年报才有读数的{cn_count(len(awaiting))}条：" + "；".join(
            awaiting_text(staging, e) for e in awaiting) + "。")
    if unmeasurable:
        note += (f"量不出来的{cn_count(len(unmeasurable))}条：" + "；".join(
            f"{e['metric']} —— {e['why']}" for e in unmeasurable) + "。")
    printed = block(staging, "quarter_printed").get("sources", {})
    sources = []
    for e in entries:
        text = READING_SOURCES.get(e["measure"])
        if text is None and e["measure"] in PRINTED_KEYS and PRINTED_KEYS[e["measure"]] in printed:
            text = f"{base_name(e['metric'])}取自{printed[PRINTED_KEYS[e['measure']]]}"
        if text and text not in sources:
            sources.append(text)
    overview = headroom_exhibit(
        title, entries, "current", note + not_tracked_text(kpi),
        f"当前值为 {cn_quarter(page_period(staging))}披露值：" + "；".join(sources)
        + "。阈值取自本季本地分析稿第 8 节。")
    overview["ref"] = "EX_NEXT"
    charts = [overview]
    by_measure: dict[str, list[dict]] = {}
    for e in entries + worded:
        by_measure.setdefault(e["measure"], []).append(e)
    drawn = []
    for e in kpi["quantified"]:
        if e["measure"] in LINES and e["measure"] not in drawn:
            drawn.append(e["measure"])
            same = sorted(by_measure[e["measure"]], key=lambda x: -x["threshold"])
            charts.append(LINES[e["measure"]](staging, same))
    for e in awaiting:
        if e["measure"] == "h2_ocf":
            charts.append(h2_ocf_line(staging, e))
    return charts


def next_description(kpi: dict, entries: list[dict], charts: list[dict]) -> str:
    """Section three's description (plain text: it is escaped)."""
    awaiting = kpi.get("awaiting", [])
    unmeasurable = kpi.get("unmeasurable", [])
    total = len(kpi["quantified"]) + len(awaiting) + len(unmeasurable)
    rest = total - len(entries)
    return (f"阈值逐字取自本季本地分析稿第 8 节「关键观察指标」，共 {total} 条。总览画有当前值的 {len(entries)} 条"
            f"（统一用「距阈值余量」口径），其后 {len(charts) - 1} 张线图画有时间序列的那几条；其余 {rest} 条只有措辞、"
            "要等下一份申报或量不出来，逐条写在总览图注里"
            + (f"，不接入的{cn_count(len(kpi['not_tracked']))}条也写在那里" if kpi.get("not_tracked") else "")
            + "。")


# ── section four: the long routine series ──────────────────────────────────


def smoke_free_transition(staging: dict) -> dict:
    annual = staging["annual"]
    years = annual["years"]
    share = annual["smoke_free_share_pct"]
    gaps = [(y, c + s - r) for y, c, s, r in zip(years, annual["combustible_usd_m"],
                                                  annual["smoke_free_usd_m"], annual["net_revenues_usd_m"])]
    off = [(y, g) for y, g in gaps if g]
    if not off:
        sums = "两段相加等于合并净收入，逐年核对无差。"
    elif all(abs(g) <= 1 for _, g in off):
        sums = (f"两段相加等于合并净收入，{cn_count(len(years))}年里只有 "
                + "、".join(f"{y} 年" for y, _ in off) + "差 US$1M，是各自四舍五入的结果。")
    else:
        sums = f"两段相加与合并净收入最多差 US${max(abs(g) for _, g in off):,.0f}M。"
    combustible = annual["combustible_usd_m"]
    flat = abs(combustible[-1] / combustible[0] - 1) < 0.10
    return {
        "ref": "EX_SF",
        "kind": "stacked_dual",
        "title": (f"无烟产品净收入占比：{years[0]} 年 {share[0]:.1f}% → "
                  f"{years[-1]} 年 {share[-1]:.1f}%"),
        "xlabels": [f"FY{y}" for y in years],
        "stacks": [
            {"name": "组合烟草产品", "color": "GRAY", "values": rounded(annual["combustible_usd_m"])},
            {"name": "无烟产品", "color": "NAVY", "values": rounded(annual["smoke_free_usd_m"])},
        ],
        # `stacked_dual` is the one chart kind whose right axis does not read
        # the data: it draws `ticks(0, ex.line.ymax || 60, 6)`. This share is at
        # 41.5% and climbing about 4pp a year, so the undeclared default was
        # roughly four years from silently mis-scaling it. Declared, not left to
        # the default -- and note it belongs inside `line`, not at the top level,
        # where it is accepted and ignored.
        "line": {"name": "无烟产品占净收入 (RHS)", "color": "RED",
                 "values": rounded(share), "yfmt": "pct1", "ymax": 60},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M", "ylab2": "无烟占比",
        "note": (
            "<b>这条线是申报里的美元，不是新闻稿里的百分比。</b>PMI 在 10-K 的分部附注里"
            "按产品类别披露净收入的美元金额，本图逐年读的是那张表；" + sums
            + "两个口径细节写在这里而不是抹掉：该行的名称从「reduced-risk products」改成"
            "「smoke-free products」，而 2020 与 2021 两年在 FY2022 的 10-K 里被重述过"
            "（Wellness and Healthcare 并入无烟口径），本图取较新的申报值。"
            + (f"组合烟草的绝对金额{cn_count(len(years))}年几乎没动，" if flat else "")
            + f"无烟从 US${annual['smoke_free_usd_m'][0]:,.0f}M 长到 "
            f"US${annual['smoke_free_usd_m'][-1]:,.0f}M"
            + (" —— 转型是加出来的，不是替换出来的。" if flat else "。")),
        "src_extra": "各年 Form 10-K 的 Segment Reporting 附注「Net revenues by product category」。",
    }


def seasonality(staging: dict) -> str:
    long = staging["long"]
    by = dict(zip(long["periods"], long["net_revenues_usd_m"]))
    years = [y for y in staging["annual"]["years"] if all(f"{y}Q{q}" in by for q in (1, 2, 3, 4))]
    lowest = collections.Counter()
    top = collections.Counter()
    for y in years:
        values = [by[f"{y}Q{q}"] for q in (1, 2, 3, 4)]
        lowest[values.index(min(values)) + 1] += 1
        top[tuple(sorted(sorted(range(4), key=lambda i: -values[i])[:2]))] += 1
    low_q, low_n = lowest.most_common(1)[0]
    pair, pair_n = top.most_common(1)[0]
    exceptions = [y for y in years
                  if [by[f"{y}Q{q}"] for q in (1, 2, 3, 4)].index(min(by[f"{y}Q{q}"] for q in (1, 2, 3, 4))) + 1 != low_q]
    text = f"季节性明显：{cn_count(len(years))}年里有{cn_count(low_n)}年第{CN_Q[low_q]}季是低点"
    if exceptions:
        text += "（" + "、".join(f"{y} 年" for y in exceptions) + "例外）"
    text += (f"，最高的两季{cn_count(pair_n)}年是第{CN_Q[pair[0] + 1]}、{CN_Q[pair[1] + 1]}季。")
    return text


def gross_profit_basis(staging: dict) -> str:
    """Which years' gross profit is on the basis PMI adopted in 2026, and from which filing."""
    recast = staging["segments"].get("recast_filing")
    if not recast:
        return f"{yq(NEW_SEGMENTS_FROM)[0]} 年起的毛利在公司 2026 年启用的新口径上"
    first, last = yq(recast["first"])[0], yq(recast["last"])[0]
    return (f"{first}–{last} 年的毛利取公司 {recast['date']} 按 2026 年新口径重印的各季数，"
            f"{first - 1} 年及以前仍是原口径")


YEAR_SUM_KEYS = {"net_revenues_usd_m": "净收入", "gross_profit_usd_m": "毛利", "operating_income_usd_m": "经营利润"}


def year_sum_sentence(staging: dict) -> str:
    """The years whose four quarters were checked against a printed full year,
    and the ones that did not tie, named rather than smoothed."""
    long = staging["long"]
    filed = long.get("filed_year_totals")
    if not filed:
        return ""
    by = {key: dict(zip(long["periods"], long[key])) for key in YEAR_SUM_KEYS}
    tied, off = [], []
    for year, row in sorted(filed["years"].items()):
        quarters = [f"{year}Q{q}" for q in (1, 2, 3, 4)]
        if not all(q in by["net_revenues_usd_m"] for q in quarters):
            continue
        ok = all(abs(sum(by[key][q] for q in quarters) - total) < 0.5 for key, total in row.items())
        (tied if ok else off).append(int(year))
    recast = staging["segments"].get("recast_filing")
    where = f" {recast['date']} 那份重印 8-K " if recast else "申报"
    items = "、".join(YEAR_SUM_KEYS.values())
    text = ""
    if tied:
        span = (f"{tied[0]}–{tied[-1]} 年" if len(tied) > 1 and tied == list(range(tied[0], tied[-1] + 1))
                else "、".join(f"{y} 年" for y in tied))
        text += f"{span}的{items}四季相加逐项与{where}印出的全年核对无差；"
    if off:
        text += "、".join(f"{y} 年" for y in off) + f"的四季相加与{where}印出的全年有出入；"
    return text + f"{gross_profit_basis(staging)}。"


def segment_basis_sentence(staging: dict) -> str:
    seg = staging["segments"]
    recast = recast_block(staging)
    own = [p for p in seg["periods"] if yq(p) >= yq(NEW_SEGMENTS_FROM)]
    text = (f"分部序列自 {cn_quarter(seg['periods'][0])}起：公司自 {cn_quarter(NEW_SEGMENTS_FROM)}起把四个地理分部"
            "改为国际无烟、国际组合烟草与美国三个报告分部")
    if recast and recast["taken"]:
        text += (f"，{recast['date']} 的 8-K（{recast['accession']}，{recast['exhibits']}）以未经审计补充信息的形式"
                 f"按新分部重印了 {quarter_years([recast['first'], recast['last']])} 各季；本页"
                 f" {quarter_years(recast['taken'])} 年取自那份重印，{quarter_years(own)} 年取自各季新闻稿")
    return text + "。本页不把这条线接到它取代的四个地理分部上。"


def revenue_series(staging: dict) -> dict:
    long = staging["long"]
    rev = long["net_revenues_usd_m"]
    by = dict(zip(long["periods"], rev))
    annual = staging["annual"]
    sums_ok = all(abs(sum(by[f"{y}Q{q}"] for q in (1, 2, 3, 4)) - total) < 0.5
                  for y, total in zip(annual["years"], annual["net_revenues_usd_m"])
                  if all(f"{y}Q{q}" in by for q in (1, 2, 3, 4)))
    return {
        "ref": "EX_REV",
        "kind": "bar_line",
        "title": (f"{len(rev)} 个季度的净收入与毛利率：本季 US${rev[-1]:,.0f}M、"
                  f"毛利率 {long['gross_margin_pct'][-1]:.1f}%"),
        "xlabels": long["period_labels"],
        "bar": {"name": "净收入", "values": rounded(rev), "color": "BLUE"},
        "line": {"name": "毛利率", "values": rounded(long["gross_margin_pct"]), "color": "RED",
                 "yfmt": "pct1"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M", "xstep": LONG_STEP,
        "note": (
            "<b>本页此前写着「序列从 2017 年开始，因为 PMI 2016 年之前按含消费税的口径报收入"
            "（2015 年 US$73.9B），2016 年起才改成净收入口径（同年 US$26.7B）」—— 那句话是错的。</b>"
            "PMI 的口径从来没变过：损益表上一直同时有含消费税的一行和扣除后的一行。"
            "73.9B 是 2015 年的<b>含税</b>数，26.7B 是 2016 年的<b>扣税</b>数 —— "
            "拿两个不同年份的两个不同口径相比，于是看见了一条并不存在的断崖。"
            "2015 年扣税后的净收入是 US$26.8B（73,908 − 47,114），与 2016 年的 26,685 同一量级。"
            "真正的坑在标签上：2016/2017 的申报里，损益表上标着「Net revenues」的那一行是 "
            "us-gaap:SalesRevenueNet，它是<b>含</b>消费税的；扣除后的口径直到 2018 年的 10-Q "
            "才有自己的 XBRL 标签。本站按「含税收入 − 消费税」计算，得到的 FY2016 = 26,685 "
            "与 FY2018 10-K 逐字重印的 FY2016 净收入相同。"
            "第四季没有 10-Q，其收入与毛利为全年减去前九个月，两条腿都是申报值"
            f"（{gross_profit_basis(staging)}）；"
            + ("净收入四个季度相加等于全年，逐年核对无差。" if sums_ok else "净收入四个季度相加与全年有出入。")
            + seasonality(staging)),
        "src_extra": "XBRL companyfacts 的季度与年度收入、毛利；第四季为年度减前九个月。",
    }


def margin_series(staging: dict) -> dict:
    long = staging["long"]
    gm, om = long["gross_margin_pct"], long["operating_margin_pct"]
    # Which quarters those troughs are is derived, not remembered: a first draft
    # of this caption named 2024Q4 from recall and it is not in the bottom four.
    # The operating-margin line has holes at the front -- 2016's quarters are on
    # the pre-ASU-2017-07 basis and were never restated quarterly -- so the
    # ranking has to skip them rather than sort None against float.
    reported_om = [(value, label) for value, label
                   in zip(om, long["period_labels"]) if value is not None]
    deepest = sorted(reported_om)[:2]
    holes = len(om) - len(reported_om)
    om_from = long["period_labels"][holes]
    return {
        "ref": "EX_MARGIN",
        "kind": "lines",
        "title": (f"毛利率与经营利润率：本季 {gm[-1]:.1f}% 与 {om[-1]:.1f}%，"
                  f"窗口内毛利率区间 {min(gm):.1f}–{max(gm):.1f}%"),
        "xlabels": long["period_labels"],
        "series": [
            {"name": "毛利率", "values": rounded(gm), "color": "NAVY"},
            {"name": "经营利润率（报告口径）", "values": rounded(om), "color": "BLUE"},
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
        "ylab": "%", "xstep": LONG_STEP,
        "note": (
            "<b>两条线的缺口比任何一条自己的水平更有信息。</b>"
            + (f"毛利率的趋势向上 —— 窗口首季 {gm[0]:.1f}%、末季 {gm[-1]:.1f}%，是无烟产品占比上升的直接读数 —— "
               "但它不是单调的，季节性与地域结构每年都会把它拉回去。" if gm[-1] > gm[0] else
               f"毛利率窗口首季 {gm[0]:.1f}%、末季 {gm[-1]:.1f}%。")
            + "经营利润率则时不时被单季的减值、诉讼与重组砸出坑："
            f"窗口内最深的两个是 {deepest[0][1]} 的 {deepest[0][0]:.1f}% 与 "
            f"{deepest[1][1]} 的 {deepest[1][0]:.1f}%。"
            "这正是第一节里那条 GAAP 指引会踩空的地方：坑本身是真的，"
            "只是公司的全年预测从一开始就写明不含它们。"
            "经营利润率是报告口径，不是调整后口径。"
            f"<b>这条线的左端比毛利率短{cn_count(holes)}格，那是洞不是缺数据。</b>"
            f"它从 {om_from} 起画。2016 四个季度的营业利润都读到了"
            "（2,473 / 2,753 / 2,977 / 2,612，两条独立路径逐格相同，"
            "四季加总 10,815 与年报恒等），但它们在 ASU 2017-07 之前的口径上："
            "养老金的非服务成本当时还在营业利润里。PMI 2018 年初追溯采用该准则，"
            "2017 四季因此各被上调 16–22 US$M，而**公司从未按季重述过 2016** —— "
            "重述后的 2016 只有一个年度数。把未重述的四季接在重述后的 2017 前面，"
            "接缝上会出现一个纯由准则变更产生的台阶，所以这四格留空。"
            "毛利率不受影响：2018 年的业绩发布把 2017 四季的净收入与销货成本逐字重印，"
            "两者一个数都没动。"),
        "src_extra": "XBRL companyfacts 的季度收入、毛利与经营利润；第四季为年度减前九个月。",
    }


def hyperscaler_growth() -> tuple[int, float] | None:
    """The four clouds' combined cash capex across the cross-page table's rows."""
    table = ai_capex_cycle_table(0)
    totals = []
    for row in table["rows"]:
        if "—" in row[1:5]:
            continue
        totals.append(float(row[5].split("$", 1)[1].split("M", 1)[0].replace(",", "")))
    if len(totals) < 2:
        return None
    return len(totals), totals[-1] / totals[0]


def cash_series(staging: dict) -> dict:
    annual = staging["annual"]
    years = annual["years"]
    ocf = annual["operating_cash_flow_usd_m"]
    capex = annual["capex_usd_m"]
    intensity = [round(c / o * 100, 2) for c, o in zip(capex, ocf)]
    story = block(staging, "quarter_story")
    other = block(staging, "guidance_other")
    growth = hyperscaler_growth()
    note = "<b>把这一页放在本站其他公司旁边，这张图是最大的反差。</b>"
    if growth:
        note += (f"核对抽屉里那张跨页对照表追的是四家云厂的现金资本开支，"
                 f"{cn_count(growth[0])}个季度里它们合计增长到 {growth[1]:.1f} 倍；")
    note += (f"PMI {cn_count(len(years))}年里资本开支从没超过经营现金流的 {max(intensity):.1f}%，"
             f"本年是 {intensity[-1]:.1f}%。")
    if story.get("us_investment") and "capex_low_usd_m" in other:
        low, high = other["capex_low_usd_m"], other["capex_high_usd_m"]
        note += (f"{story['us_investment']}，而全年资本开支指引是 US${low / 100:.0f}–{high / 100:.0f} 亿、"
                 f"相对上年 US${capex[-1]:,.0f}M 是 {minus_sign(signed(pct_change(low, capex[-1])))} 到 "
                 f"{minus_sign(signed(pct_change(high, capex[-1])))} —— 也就是说这笔投入进的是销售与市场费用，"
                 "不是资产负债表。")
        half = staging["half_year_cash"]
        open_year = half["years"][-1]
        if open_year not in years and open_year - 1 in half["years"]:
            now_h1, then_h1 = half["h1_capex_usd_m"][-1], half["h1_capex_usd_m"][-2]
            note += (f"第二季 10-Q 印出的上半年资本开支是 US${now_h1:,.0f}M，上年同期 US${then_h1:,.0f}M"
                     + ("，到年中为止资本开支没有跟着「加大投入」上升。" if now_h1 <= then_h1 else
                        f"，多了 {pct_change(now_h1, then_h1):.1f}%，这条判断要看下半年。"))
        else:
            note += "这条判断下一季可以用同一张表证伪。"
    return {
        "ref": "EX_CASH",
        "kind": "bar_line_dual",
        "title": (f"经营现金流与资本开支：{years[-1]} 年 US${ocf[-1]:,.0f}M 对 "
                  f"US${capex[-1]:,.0f}M，资本开支只占 {intensity[-1]:.1f}%"),
        "xlabels": [f"FY{y}" for y in years],
        "bar": {"name": "经营现金流", "values": rounded(ocf), "color": "NAVY"},
        "line": {"name": "资本开支 ÷ 经营现金流 (RHS)", "values": rounded(intensity),
                 "color": "RED", "yfmt": "pct1"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M", "ylab2": "资本开支占经营现金流 %",
        "note": note,
        "src_extra": "XBRL companyfacts 的年度经营现金流与购置不动产、厂房及设备支出。",
    }


# ── payload ────────────────────────────────────────────────────────────────


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    fin = staging["financials"]
    return [f"Revenue ${fin['net_revenues_usd_m'][-1] / 1000:.2f}B",
            f"无烟收入占比 {staging['annual']['smoke_free_share_pct'][-1]:.1f}%",
            f"Adj EPS ${fin['adjusted_diluted_eps_usd'][-1]:.2f}"]


def release_source(staging: dict) -> tuple[str, str, str]:
    """This quarter's release and periodic report in `sources`: link text, URL, report words."""
    period = page_period(staging)
    year, number = yq(period)
    key = f"PMI {year} 年第{CN_Q[number]}季度" + ("及全年" if number == 4 else "") + "业绩新闻稿"
    entry = next((s for s in staging["sources"] if s["label"].startswith(key)), None)
    if entry is None:
        raise ValueError(f"series `sources` has no {key!r}: add this quarter's release")
    report = (f"与 {year} 年度 Form 10-K" if number == 4
              else f"与截至 {staging['period_ends'][-1]} 的 Form 10-Q")
    return f"{key}（8-K EX-99.1）", entry["url"], report


def guidance_table(staging: dict) -> dict:
    other = block(staging, "guidance_other")
    released = staging["latest"]["release_date"]
    record = next((r for r in staging["annual_guidance"]["records"]
                   if r["vintages"] and r["vintages"][-1]["release_date"] == released), None)
    if record is None:
        raise ValueError(f"annual_guidance has no vintage released {released}: add this release's "
                         "full-year forecast")
    now_v = record["vintages"][-1]
    before_v = record["vintages"][-2] if len(record["vintages"]) > 1 else None
    upcoming = next_quarter_guidance(staging)
    previous_q = next((r for r in staging["quarterly_guidance"]
                       if before_v and r["release_date"] == before_v["release_date"]), None)
    rows = []
    if upcoming is not None:
        year, number = yq(upcoming["guided_period"])
        fx = upcoming.get("currency_eps")
        rows.append([
            f"{year} 年第{CN_Q[number]}季度调整后摊薄 EPS", f"${upcoming['low']:.2f} – ${upcoming['high']:.2f}",
            (f"—（上一期只给第{CN_Q[yq(previous_q['guided_period'])[1]]}季 "
             f"${previous_q['low']:.2f} – ${previous_q['high']:.2f}）" if previous_q else "—"),
            "新季度对象" + (f"，含约 {abs(fx) * 100:.0f} 美分{'不利' if fx < 0 else '有利'}汇率" if fx else "")])

    def band(v, lo, hi):
        return f"${v[lo]:.2f} – ${v[hi]:.2f}"

    def change(key):
        if before_v is None:
            return "—"
        delta = mid(now_v[f"{key}low"], now_v[f"{key}high"]) - mid(before_v[f"{key}low"], before_v[f"{key}high"])
        if (now_v[f"{key}low"], now_v[f"{key}high"]) == (before_v[f"{key}low"], before_v[f"{key}high"]):
            return "逐字未变"
        return f"{'上调' if delta > 0 else '下调'} ${abs(delta):.2f}"

    y = record["year"]
    for label, key in ((f"{y} 全年报告口径摊薄 EPS", ""), (f"{y} 全年调整后摊薄 EPS", "adj_"),
                       (f"{y} 全年调整后摊薄 EPS（剔除汇率）", "xfx_")):
        rows.append([label, band(now_v, f"{key}low", f"{key}high"),
                     band(before_v, f"{key}low", f"{key}high") if before_v else "—", change(key)])
    rows.extend(other.get("rows", []))
    reported_move = change("")
    adjusted_move = change("adj_")
    unchanged = (before_v is not None
                 and all((v["xfx_low"], v["xfx_high"]) == (now_v["xfx_low"], now_v["xfx_high"])
                         for v in record["vintages"]))
    note = "公司在同一张预测表里并列报告口径与调整后口径，中间逐项列出调整。"
    if before_v is not None:
        note += (f"本期报告口径{reported_move}、调整后{adjusted_move}"
                 + (f"，而「剔除汇率的区间{cn_count(len(record['vintages']))}次发布逐字未变」"
                    f"（${now_v['xfx_low']:.2f}–{now_v['xfx_high']:.2f}）" if unchanged else "")
                 + (f"—— 公司自己的标题就写「{other['headline_quote']}」。" if other.get("headline_quote") else "。"))
    guided = {r["guided_period"] for r in staging["quarterly_guidance"]}
    fourths = sorted(p for p in guided if yq(p)[1] == 4)
    if upcoming is not None:
        note += f"下季指引只覆盖第{CN_Q[yq(upcoming['guided_period'])[1]]}季"
        if len(fourths) == 1 and yq(upcoming["guided_period"])[1] == 3:
            exception = next(r for r in staging["quarterly_guidance"] if r["guided_period"] == fourths[0])
            note += (f"：PMI 从不指引第四季，{cn_quarter(fourths[0], '季')}那次"
                     f"{'单点' if exception['point'] else '区间'}是唯一例外。")
        else:
            note += "。"
    title_date = now_v["release_date"]
    return {
        "title": f"公司指引（{title_date} 业绩新闻稿全年预测表与假设段，公司披露值）",
        "headers": ["指标", "本期指引",
                    f"上一期指引（{before_v['release_date']}）" if before_v else "上一期指引", "变动"],
        "rows": rows,
        "note": note,
    }


def build_payload(staging: dict) -> dict:
    fin = staging["financials"]
    labels = staging["period_labels"]
    long = staging["long"]
    seg = staging["segments"]
    period = page_period(staging)
    if yq(long["periods"][-1]) != yq(staging["periods"][-1]):
        raise ValueError(f"long ends at {long['periods'][-1]!r} but `periods` ends at "
                         f"{staging['periods'][-1]!r}: append the quarter to both")

    rev = fin["net_revenues_usd_m"]
    adj_eps = fin["adjusted_diluted_eps_usd"]
    rep_eps = fin["reported_diluted_eps_usd"]

    banded, floors = annual_records(staging)
    fy_rows = [(r["actual_reported_eps"], r["last_guided"]["low"], r["last_guided"]["high"])
               for r in banded]
    fy_n, fy_above, fy_inside, fy_below = tally(fy_rows)

    q_rows = staging["quarterly_guidance"]
    q_adj = [(r["actual_eps"], r["low"], r["high"]) for r in q_rows if r["basis"] != "reported"]
    qa_n, qa_above, qa_inside, qa_below = tally(q_adj)

    kpi, entries, worded = kpi_entries(staging)

    # Section one settles what last quarter left due, in the order the page's
    # format asks for: the note's open questions, its quantified thresholds,
    # then the company's own guidance record.
    closure_chart = followup_exhibit(staging)
    prior_charts, prior_entries, prior_block = prior_settlement(staging)
    settled = ([closure_chart] if closure_chart else []) + prior_charts + [
        annual_reported_band(staging),
        annual_deviation(staging),
        annual_adjusted_band(staging),
        currency_path(staging),
        quarter_band(staging),
        quarter_deviation(staging),
    ]
    highlights = [
        revenue_bridge(staging),
        segment_revenue(staging),
        segment_margin(staging),
        zyn_offtake(staging),
    ]
    next_block = next_section(staging, kpi, entries, worded)
    routine = [
        smoke_free_transition(staging),
        revenue_series(staging),
        margin_series(staging),
        cash_series(staging),
    ]

    exhibits = number_exhibits(settled + highlights + next_block + routine)
    resolve_exhibit_refs(exhibits)
    n_settled, n_high, n_next = len(settled), len(highlights), len(next_block)
    settled_ex = exhibits[:n_settled]
    highlight_ex = exhibits[n_settled:n_settled + n_high]
    next_ex = exhibits[n_settled + n_high:n_settled + n_high + n_next]
    routine_ex = exhibits[n_settled + n_high + n_next:]

    first_table = exhibits[-1]["n"] + 1
    tables = []

    def verdict_text(actual, low, high):
        v = verdict_of(actual, low, high)
        return {"above": "高于上限", "inside": "区间内", "below": "跌破下限", None: "待披露"}[v]

    if prior_entries:
        tables.append(threshold_table(0, "上季阈值与本季实际（原始单位）", prior_entries, "actual", "本季实际"))
    tables.append({
        "n": first_table,
        "title": "全年报告口径每股收益指引：年初、年末与实际（含只给下限的年份）",
        "headers": ["年度", "年初第一次指引", "当年最后一次指引", "全年实际", "对最后一次指引"],
        "rows": [[
            f"FY{r['year']}",
            (f"${r['first_guided']['low']:.2f}–{r['first_guided']['high']:.2f}"
             if r["first_guided"] and r["first_guided"].get("high")
             else (f"至少 ${r['first_guided']['low']:.2f}" if r["first_guided"] else "—")),
            (f"${r['last_guided']['low']:.2f}–{r['last_guided']['high']:.2f}"
             if r["last_guided"].get("high") else f"至少 ${r['last_guided']['low']:.2f}"),
            f"${r['actual_reported_eps']:.2f}" if r["actual_reported_eps"] is not None else "待披露",
            (verdict_text(r["actual_reported_eps"], r["last_guided"]["low"], r["last_guided"]["high"])
             if r["last_guided"].get("high") else
             ("高于下限" if r["actual_reported_eps"] is not None
              and r["actual_reported_eps"] >= r["last_guided"]["low"] else "跌破下限")),
        ] for r in sorted(banded + floors, key=lambda r: r["year"])],
    })
    adj_actual = staging["annual_guidance"]["annual_adjusted_eps_actual"]
    adj_rows = []
    for record in staging["annual_guidance"]["records"]:
        vs = [v for v in record["vintages"] if v.get("adj_low") is not None]
        if not vs:
            continue
        last, actual = vs[-1], adj_actual.get(str(record["year"]))
        adj_rows.append([
            f"FY{record['year']}",
            f"${vs[0]['adj_low']:.2f}–{vs[0]['adj_high']:.2f}",
            f"${last['adj_low']:.2f}–{last['adj_high']:.2f}",
            f"${actual:.2f}" if actual is not None else "待披露",
            verdict_text(actual, last["adj_low"], last["adj_high"]),
        ])
    tables.append({
        "n": first_table + 1,
        "title": "全年调整后每股收益指引：同一批年份、同一份新闻稿、另一个口径",
        # FY2020 has only one adjusted vintage (the October release), so the
        # first column is "the first release that carried this basis", not
        # "the February release" the reported-EPS table above it can promise.
        "headers": ["年度", "首次给出该口径的指引", "当年最后一次指引", "全年实际",
                    "对最后一次指引"],
        "rows": adj_rows,
    })
    tables.append({
        "n": first_table + 2,
        "title": "下季每股收益指引与随后实际（按各自当期口径）",
        "headers": ["被指引季度", "指引发布日", "口径", "指引", "实际", "结果"],
        "rows": [[
            r["period_label"], r["release_date"],
            {"reported": "报告", "adjusted": "调整后",
             "pro_forma_adjusted": "调整后（剔除俄乌）"}[r["basis"]],
            (f"${r['low']:.2f}（单点）" if r["point"] else f"${r['low']:.2f}–{r['high']:.2f}"),
            f"${r['actual_eps']:.2f}" if r["actual_eps"] is not None else "待披露",
            verdict_text(r["actual_eps"], r["low"], r["high"]),
        ] for r in q_rows],
    })
    tables.append({
        "n": first_table + 3,
        "title": f"近{cn_count(len(labels))}季合并损益与每股收益（公司披露值）",
        "headers": ["期间", "净收入", "毛利", "经营利润", "毛利率", "经营利润率",
                    "报告口径摊薄 EPS", "调整后摊薄 EPS"],
        "rows": [[
            labels[i], f"${rev[i]:,.0f}M", f"${fin['gross_profit_usd_m'][i]:,.0f}M",
            f"${fin['operating_income_usd_m'][i]:,.0f}M",
            f"{fin['gross_margin_pct'][i]:.1f}%", f"{fin['operating_margin_pct'][i]:.1f}%",
            f"${rep_eps[i]:.2f}", f"${adj_eps[i]:.2f}",
        ] for i in range(len(labels))],
    })
    tables.append(threshold_table(first_table + 4, "下季阈值与当前值（原始单位）",
                                  entries, "current", "当前值"))
    tables.append(ai_capex_cycle_table(first_table + 5))
    # numbered in the order they are listed, after the last exhibit, whichever
    # of the one-quarter tables this quarter carries
    for offset, table in enumerate(tables):
        table["n"] = first_table + offset

    # the quarter in one sentence
    seg_labels = seg["periods"]
    seg_gm = seg["adjusted_gross_margin_pct"]
    us_ago = year_ago_index(seg_labels, len(seg_labels) - 1)
    us_gm = seg_gm["us"]
    this_q = next((r for r in q_rows if yq(r["guided_period"]) == yq(staging["periods"][-1])), None)
    headline = f"净收入 US${rev[-1]:,.0f}M、同比 {signed(pct_change(rev[-1], rev[-5]))}，"
    if this_q is not None and this_q["basis"] == "adjusted":
        verdict = verdict_of(adj_eps[-1], this_q["low"], this_q["high"])
        headline += (f"调整后摊薄每股收益 US${adj_eps[-1]:.2f} "
                     + {"above": "高于", "below": "低于", "inside": "落在"}[verdict]
                     + f"公司自己给的 US${this_q['low']:.2f}–{this_q['high']:.2f}"
                     + ("之内" if verdict == "inside" else ""))
    else:
        headline += f"调整后摊薄每股收益 US${adj_eps[-1]:.2f}"
    rep_down = rep_eps[-1] < rep_eps[-5]
    one_off = block(staging, "quarter_story").get("gaap_one_off")
    headline += (f"；{'但' if rep_down else ''}报告口径每股收益 US${rep_eps[-1]:.2f} "
                 f"同比{'下降' if rep_down else '上升' if rep_eps[-1] > rep_eps[-5] else '持平'}"
                 + (f"（其中 {one_off['name']}拿走 US${one_off['eps_usd']:.2f}）" if one_off and rep_down else "")
                 + f"，美国分部调整后毛利率 {us_gm[-1]:.1f}%、同比 {us_gm[-1] - us_gm[us_ago]:+.1f}pp")
    if rep_down and this_q is not None and adj_eps[-1] > this_q["high"]:
        headline += " —— 同一份新闻稿里，公司定义的那个数在兑现，GAAP 那个数在被一次性项目拿走。"
    else:
        headline += "。"

    latest_bridge, previous_bridge, _ = bridge_blocks(staging)
    vmo_now = latest_bridge["volume_mix_other"][0]
    if previous_bridge is not None and previous_bridge["volume_mix_other"][0] < 0 < vmo_now:
        before = previous_bridge["volume_mix_other"][0]
        split = printed_split(previous_bridge)
        bridge_card = ('<article><span>亮点</span><b>增量从「价格＋汇率」变成「价格＋正的量与结构」</b>'
                       f'<p>本季净收入增量里价格 US${latest_bridge["price"][0]:,.0f}M、'
                       f'汇率 US${latest_bridge["currency"][0]:,.0f}M，量与结构 US${vmo_now:,.0f}M —— '
                       f'上一季这一项是 −US${abs(before):,.0f}M'
                       + (f'（那张表分两行印：量与结构 {money_m(split[0])}、其他 {money_m(split[1])}）'
                          if split else '') + '。</p></article>')
    else:
        bridge_card = ('<article><span>亮点</span><b>本季净收入增量的来源</b>'
                       f'<p>价格 US${latest_bridge["price"][0]:,.0f}M、汇率 US${latest_bridge["currency"][0]:,.0f}M、'
                       f'量与结构 US${vmo_now:,.0f}M。</p></article>')
    view = zyn_view(staging)
    peak_value, peak_label = max(view["known"])
    after_peak = [v for v, label in view["known"] if yq(label) > yq(peak_label)]
    zyn_words = ""
    if after_peak and all(a > b for a, b in zip([peak_value] + after_peak, after_peak)) and view["words_only"]:
        zyn_words = f"ZYN 零售出货从 {peak_value:.0f}% 一路降到公司只肯用措辞描述。"
    us_card = ('<article><span>代价</span><b>美国分部的单位经济性还在恶化</b>'
               if us_gm[-1] < us_gm[us_ago] else '<article><span>美国</span><b>美国分部的调整后毛利率</b>')
    us_card += (f'<p>调整后毛利率 {us_gm[-1]:.1f}%，同比 {us_gm[-1] - us_gm[us_ago]:+.1f}pp'
                + (f'；{zyn_words}' if zyn_words else '。') + '</p></article>')
    all_above = qa_above == qa_n and qa_n > 0
    brief = (
        '<h4>本季三条主线</h4><div class="takeaway-grid">'
        '<article><span>记录</span><b>同一年被指引两次，两条记录不一样</b>'
        f'<p>报告口径的全年指引，{fy_n} 个完整年度里 {fy_above} 年高于上限、{fy_inside} 年'
        f'落在区间内、{fy_below} 年跌破下限；换成公司自定义的调整后口径，下季指引 '
        + (f'{qa_n} 季<b>全部</b>高于上限。' if all_above
           else f'{qa_n} 季里 {qa_above} 季高于上限、{qa_inside} 季落在区间内、{qa_below} 季跌破下限。')
        + '</p></article>'
        + bridge_card + us_card + '</div>')

    name, url, report = release_source(staging)
    audit = AUDIT_WORDS.get(staging["latest"]["audit_status"])
    if audit is None:
        raise ValueError(f"latest.audit_status {staging['latest']['audit_status']!r} is not one this page prints")
    records = staging["annual_guidance"]["records"]
    withdrawn = [(r["year"], d) for r in records for d in r["withdrawn"]]
    published = sum(1 for r in records for v in r["vintages"] if v["release_date"] not in r["withdrawn"])
    span, counted = clause_sentence(staging)
    census = staging["annual_guidance"]["exclusion_clause_census"]
    first_q = q_rows[0]["guided_period"]
    reported_q = [r for r in q_rows if r["basis"] == "reported"]
    pro_forma = [r for r in q_rows if r["basis"] == "pro_forma_adjusted"]
    first_adj = next(r for r in q_rows if r["basis"] == "adjusted" and yq(r["guided_period"]) > yq(reported_q[-1]["guided_period"]))
    pf_years = sorted({yq(r["guided_period"])[0] for r in pro_forma})
    kpi_items = kpi.get("not_tracked", [])
    return {
        "schema_version": "quarterly-dashboard/pm-v1",
        "page": {"slug": "pm", "language": "zh-CN"},
        "company": {
            "ticker": "PM",
            "name": "Philip Morris International",
            "group": "consumer_staples",
            "accounting_standard": "US GAAP",
        },
        "latest": latest_block(
            staging,
            period=staging["period_labels"][-1],
            period_end=staging["period_ends"][-1]),
        "tracker": "Watchlist Quarterly Tracker · PM",
        "title": f"Philip Morris International (PM)：{period} 季报仪表盘",
        "subtitle": (f"截至 {staging['period_ends'][-1]} · 发布 {staging['latest']['release_date']} · US GAAP · "
                     f"{audit} · 自然年财年，季度标注与财年一致"),
        "headline": headline,
        "brief": brief,
        "source": (f'Source: <a href="{url}" rel="noopener">{name}</a>{report}。'),
        "source_url": url,
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": guidance_table(staging),
        "sections": [
            {"id": "settled", "title": "一、上季跟踪指标兑现了吗",
             "description": settled_description(closure_chart, prior_block),
             "exhibits": settled_ex},
            {"id": "quarter_highlights", "title": "二、本季重点",
             "description": highlights_description(staging),
             "exhibits": highlight_ex},
            {"id": "next_quarter", "title": "三、下季要跟踪什么",
             "description": next_description(kpi, entries, next_ex),
             "exhibits": next_ex},
            {"id": "routine", "title": "四、长期常规跟踪",
             "description": (f"PMI 专属的常规序列：{cn_count(len(staging['annual']['years']))}年无烟转型的美元金额、"
                             f"{len(long['periods'])} 个季度的收入与"
                             "两条利润率，以及一家现金强、资本轻的公司的现金结构。"),
             "exhibits": routine_ex},
        ],
        "tables": tables,
        "notes": [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "PMI 财年即自然年，本页季度标注与公司自己的口径一致，无需换算。",
            ("第一节先结算上季本地分析稿留下的待验证问题与量化阈值，再结清公司自己的指引："
             if closure_chart or prior_block else "第一节结清公司自己的指引：")
            + "全年与下一季两个层级、报告与调整后两种口径。"
            "全年指引自 2008 年分拆起在每一份季度业绩新闻稿里发布并逐季修订"
            + (f"（{'、'.join(d for _, d in withdrawn)} 那{cn_count(len(withdrawn))}份撤回除外）" if withdrawn else "")
            + f"，本页收录 {records[0]['year']}–{records[-1]['year']} 共 "
            f"{len(records)} 个年度、{published} 次发布；下季指引自 {cn_quarter(first_q)}"
            f"起发布，共 {len(q_rows)} 次。",
            "FY2008 不在记录内：公司 2008 年 3 月才分拆，当年的预测是按 pro forma「调整后」口径"
            "对 2007 年 pro forma 基数给出的（新闻稿原文如此），拿它对报告口径的实际值结清是口径错误"
            "而不是一次落空。",
            "FY2019 与 FY2020 年初的指引是「至少 US$X」这样「只有下限」的形式，没有上限可以穿出，"
            "所以不进区间图，只进核对表。2020 年 4 月 21 日公司因新冠「撤回」全年指引并改为按季度"
            "指引，同年 7 月恢复全年指引"
            + (" —— 这是记录里唯一一次撤回。" if len(withdrawn) == 1 else "。"),
            span + counted + "。"
            "2022 年第二季起公司改用「报告口径 + 逐项"
            "列名的调整 + 调整后口径」的预测表，排除项因此从一句概括变成了逐项计价。本页把两个时期"
            "画在同一张图上，但在图注里说明这条差别 —— 它正是报告口径那条记录会踩空的原因。",
            f"下季指引的口径在记录中期发生变化：{cn_quarter(first_q, '季')}至 {cn_quarter(reported_q[-1]['guided_period'], '季')}为「报告」每股收益，"
            f"{cn_quarter(first_adj['guided_period'], '季')}起为「调整后」每股收益，"
            + (f"{pf_years[0]} 年第" + "、".join(CN_Q[yq(r['guided_period'])[1]] for r in pro_forma)
               + f"季{cn_count(len(pro_forma))}格另为剔除俄罗斯与乌克兰的 pro forma 调整后口径。" if len(pf_years) == 1 else "")
            + "实际值一律按指引当期的同一口径取，不跨口径比较；图上有结构断点标记。",
            "第四季度没有 10-Q，所以本页季度序列里的第四季收入、毛利与经营利润为全年申报值减去前九个月"
            "申报值，两条腿都是申报数字；每股收益不可加总，第四季读自当期新闻稿的 EPS 调节表。"
            + year_sum_sentence(staging),
            f"长期季度序列自 {cn_quarter(long['periods'][0])}起：PMI 的损益表一直同时印含消费税与扣除消费税两行收入，"
            "本页取扣除后的净收入；2016/2017 申报里标着「Net revenues」的那一行其实含消费税，见收入那一张的图注。",
            segment_basis_sentence(staging),
            "无烟产品收入占比取自各年 10-K 分部附注里按产品类别的「美元」金额，不是新闻稿里的整数"
            "百分比。该行的名称在 2019 年前后从 reduced-risk products 改为 smoke-free products，"
            "2020 与 2021 两年在 FY2022 的 10-K 里被重述（Wellness and Healthcare 并入无烟口径），"
            "本页取较新的申报值。",
            "本页不发布市场一致预期：没有可核对的、带日期的公开来源。本页同样不发布评级、目标价与估值。",
            "本页只发布公司披露值、可复算的简单派生值；D 标记代表 Derived / 自算。",
            "核对抽屉最后那张「AI capex 循环」是全站共用的跨页对照块，在每一页都逐字节相同，不是对 PM 的判断。"
            "它追的是四家云厂现金资本开支 → NVDA 数据中心收入 → TSM 晶圆这条链，PMI 不在这条链的任何一环上。"
            "把它放在这里是为了让读者在任意一页都能查到同一份上下游对照。它在折叠的抽屉里，不参与本页的论证。",
            # what is not tracked is this quarter's list (`next_kpi`), not a remembered one
            "本页已知未接入：" + "".join(f"{x.get('note', x['name'])}" + ("，" if i == len(kpi_items) - 1 else "、")
                                       for i, x in enumerate(kpi_items))
            + f"以及 {int(staging['latest']['release_date'][:4])} 年 {int(staging['latest']['release_date'][5:7])} 月 "
            f"{int(staging['latest']['release_date'][8:10])} 日申报之后的任何数据。",
            "业绩电话会文字稿仅链接官方 IR 与 SEC 托管版本，公开仓不复制原件或逐字内容。",
        ],
        "footer": "PM quarterly results · 数据来自 PMI 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "pm.js"), payload, "pm")
    shell_dir = ROOT / "pm"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("PM", "pm"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"PM page: {charts} charts in {len(payload['sections'])} sections "
          f"+ {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
