"""Ferrari N.V. quarterly dashboard.

Ferrari is the first company on this site that files no 10-Q, no 10-K and no
8-K. It is a Dutch-incorporated foreign private issuer reporting under IFRS in
euro, so its annual filing is a 20-F and every quarterly figure it has ever
published sits in the EX-99.1 of a results 6-K. The rendered-statement R-files
the rest of this site leans on cover 10-Q and 10-K schedules, and Ferrari has
neither, so the releases themselves are the whole source.

**And the guidance record it files has a shape no other page here carries.**
The other guidance pages settle a range: did the reported number land inside
it. Ferrari's full-year outlook is mostly not a range at all -- it is a
one-sided inequality or an "about". When this page was built on the Q2 2026
release, 31 vintages and five guided metrics gave 155 readings: 69 floors, 31
points, 6 ceilings and only 49 two-sided ranges. The opening, Q1 and Q2
vintages carried 15 to 17 ranges each; the Q3 vintage -- the one that settles
the year, published in early November with about ten of twelve months banked
-- carried one range out of 35.

So the guidance sheds its upper bound exactly as the year becomes knowable,
which is the opposite of a forecast narrowing onto an answer. That is why this
page does not report a hit rate as its headline: against a floor, "never
missed" is close to a tautology, and it is the *distance above* the floor and
the *path the floor took* that still carry information.

Rolling the page is a data edit (CLAUDE.md §9). Every count, period label, date,
record and comparison in the prose below is computed from ``series/race.json``,
and the sentences that make a claim about the whole record ("every quarter",
"the only", "a new high", "usually") are printed only while the record says so.
Margins quoted in prose are the ones the company printed (the charts plot the
page's own ratio of two printed figures, marked D). What belongs to one release
sits in blocks stamped with the quarter and read through ``board.stamped_block``:
``next_kpi`` (the thresholds, their rationale and what the page does not track),
``quarter_story`` (the full-year D&A figure management gave and the quarter's
explanations) and ``printed_yoy_pct`` (the growth rates the release printed). A
block stamped for another quarter stops the build; an absent optional one takes
its sentences with it. Where the company reprinted a quarter the series holds
the reprint and ``reprints`` records the first print. What stays in this file is
fixed history no roll moves: the FY2020 guidance cut, the seven-week 2020
shutdown, the Engines reclassification, the region renamings, and the capex
reconstruction for 2016-2018.

Published numbers are company-reported or transparent arithmetic. Thresholds in
section three are local research settings, not company guidance.
"""

from __future__ import annotations

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
    headroom,
    headroom_exhibit,
    latest_block,
    number_exhibits,
    round_half_up,
    stamped_block,
    threshold_exhibit,
    threshold_table,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "race.json"
DATA_DIR = ROOT / "data"

# One tick per year keeps the long axes readable.
LONG_STEP = 4

METRIC_NAMES = {
    "revenue": "净收入",
    "adj_ebitda": "调整后 EBITDA",
    "adj_ebit": "调整后 EBIT",
    "adj_eps": "调整后摊薄 EPS",
    "ifcf": "工业自由现金流",
}
FORM_NAMES = {"range": "两端区间", "floor": "只给下限", "point": "单点约数", "ceiling": "只给上限"}
FORM_SHORT = {"point": "单点", "floor": "下限", "ceiling": "上限", "range": "区间"}
FORM_WORDS = {"range": "区间", "floor": "「至少」", "point": "「约」", "ceiling": "「不超过」"}
SLOT_NAMES = {"initial": "年初首次", "q1": "Q1 修订", "q2": "Q2 修订", "q3": "Q3 修订"}
SLOTS = ["initial", "q1", "q2", "q3"]
FORM_GROUPS = [("利润三项（EBITDA、EBIT、EPS）", ["adj_ebitda", "adj_ebit", "adj_eps"]),
               ("收入", ["revenue"]),
               ("工业自由现金流", ["ifcf"])]
CN_Q = {1: "一", 2: "二", 3: "三", 4: "四"}
REGIONS = [("shipments_emea", "EMEA", "NAVY"),
           ("shipments_americas", "美洲", "BLUE"),
           ("shipments_china_hk_taiwan", "中国大陆、香港与台湾", "GOLD"),
           ("shipments_rest_of_apac", "亚太其余", "RED")]
LEGS = [("cars_and_spare_parts_eur_m", "Cars and spare parts", "NAVY"),
        ("sponsorship_commercial_brand_eur_m", "Sponsorship, commercial and brand", "BLUE"),
        ("other_revenues_eur_m", "Other", "GOLD")]
# The quarters-add-to-the-year check: series key, full-year key, the name prose uses.
SUM_KEYS = [("net_revenues_eur_m", "净收入"), ("shipments_units", "出货"), ("ebitda_eur_m", "EBITDA"),
            ("ebit_eur_m", "EBIT"), ("da_eur_m", "D&A"), ("net_profit_eur_m", "净利润"),
            ("industrial_fcf_eur_m", "工业自由现金流")]
AUDIT_WORDS = {"unaudited": "未审计", "audited": "已审计"}

# Fixed history: the one guidance cut in the record, in the company's own words
# (FY2019 results, 2020-02-04: "Net revenues: > Euro 4.1 billion"; Q1 2020
# results, 2020-05-04: "REVISED GUIDANCE 2020 ... 3.4-3.6"). Printed only while
# the record still says FY2020's first revision is its only cut.
FY2020_CUT = "那一年公司在 5 月把全年收入指引从「> €4.1B」下调到「€3.4–3.6B」"


# ── small helpers ────────────────────────────────────────────────────────────
def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100.0


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def rounded(values, digits: int = 6):
    return [None if v is None else round(v, digits) for v in values]


def qparts(label: str) -> tuple[int, int]:
    """``'Q2 2026'`` → ``(2026, 2)``."""
    number, year = label.split()
    return int(year), int(number[1])


def compact(label: str) -> str:
    """``'Q2 2026'`` → ``'2026Q2'``, the form prose uses."""
    year, number = qparts(label)
    return f"{year}Q{number}"


def cn_quarter(label: str, word: str = "季") -> str:
    """``'Q1 2016'`` → ``'2016 年第一季'``."""
    year, number = qparts(label)
    return f"{year} 年第{CN_Q[number]}{word}"


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


def decimals(value: float) -> int:
    text = f"{value:.10f}".rstrip("0")
    return len(text.split(".")[1]) if "." in text else 0


def verdict(low: float, high: float, form: str, actual: float) -> str:
    """How a year landed, with a tolerance equal to the PRINTED precision.

    `~1.27` is stated to EUR 0.01B and therefore carries +/- EUR 5M. FY2019
    adjusted EBITDA came in at EUR 1.269B -- three million euro under a figure
    the company printed to two decimals. Scoring that as a miss would apply a
    threshold finer than the disclosure it is measured against, which is the
    same reason the Mastercard page retired a currency-neutral threshold.
    """
    tolerance = 0.5 * 10 ** -decimals(high)
    if form == "range":
        if actual > high + tolerance:
            return "above"
        if actual < low - tolerance:
            return "below"
        return "inside"
    if form == "ceiling":
        return "within" if actual <= high + tolerance else "exceeded"
    if abs(actual - high) <= tolerance:
        return "met"
    return "above" if actual > high else "below"


def official_margin(long: dict, kind: str, index: int) -> float:
    """The margin the company printed for a quarter, where it printed one on the
    page's basis; the page's own ratio of the two printed figures otherwise.

    Three quarters (2016Q2, 2016Q4, 2018Q2) were printed only on an adjusted
    basis that differs from reported; prose about the reported line uses the
    ratio there."""
    printed = long[f"{kind}_margin_printed_pct"][index]
    same_basis = (long["margin_printed_basis"][index] == "reported"
                  or long[f"adj_{kind}_eur_m"][index] == long[f"{kind}_eur_m"][index])
    if printed is not None and same_basis:
        return printed
    return long[f"{kind}_margin_pct"][index]


def official_rate(computed: float, printed: int | None) -> str:
    """A year-on-year rate as prose prints it: the page's own figure to a tenth,
    unless the company printed a whole-percent rate it does not round to -- then
    the company's."""
    if printed is None or int(round_half_up(computed, 0)) == printed:
        return signed(computed)
    return f"{printed:+d}%"


def month_span(dates: list[str]) -> str:
    months = sorted({int(d[5:7]) for d in dates})
    if len(months) > 1 and months == list(range(months[0], months[-1] + 1)):
        return f"{months[0]}–{months[-1]} 月"
    return "、".join(str(m) for m in months) + " 月"


def months_by_year(dates: list[str]) -> str:
    """``['2019-01-31', '2019-05-07', '2025-02-04']`` → ``'2019 年 1、5 月与 2025 年 2 月'``."""
    years: dict[str, list[int]] = {}
    for d in sorted(dates):
        years.setdefault(d[:4], []).append(int(d[5:7]))
    parts = [f"{y} 年 " + "、".join(str(m) for m in ms) + " 月" for y, ms in years.items()]
    return parts[0] if len(parts) == 1 else "、".join(parts[:-1]) + "与 " + parts[-1]


def span_words(n_quarters: int) -> str:
    """``42`` → ``'十年半'``: the length of the long record in years."""
    years, rest = divmod(n_quarters, 4)
    return cn_count(years) + "年" + {0: "", 1: "多", 2: "半", 3: "多"}[rest]


def lowest_since(values: list[float], labels: list[str], min_run: int = 4) -> str | None:
    """「是 X 以来最低」 for the latest value, when it is below at least the
    `min_run` values before it; the whole window when nothing earlier is lower."""
    current = values[-1]
    for j in range(len(values) - 2, -1, -1):
        if values[j] <= current:
            run = len(values) - 2 - j
            return f"是 {compact(labels[j])} 以来最低" if run >= min_run else None
    return f"是这 {len(values)} 季里最低"


def ytd_indices(quarters: list[str]) -> list[int]:
    year = qparts(quarters[-1])[0]
    return [i for i, q in enumerate(quarters) if qparts(q)[0] == year]


YTD_WORDS = {1: "一季度", 2: "上半年", 3: "前三季"}
REST_WORDS = {1: "后三季", 2: "下半年", 3: "第四季"}
REST_SHORT = {1: "Q2–Q4 季均", 2: "H2 季均", 3: "Q4"}


# ── what the series knows about itself ───────────────────────────────────────
def form_counts(record: dict) -> dict:
    counts = {slot: {form: 0 for form in FORM_NAMES} for slot in SLOTS}
    for index, slot in enumerate(record["vintage_slots"]):
        for metric in METRIC_NAMES:
            form = record["items"][metric]["form"][index]
            if form:
                counts[slot][form] += 1
    return counts


def settled_years(record: dict) -> list[int]:
    return sorted({fy for fy, actual in zip(record["fiscal_years"],
                                            record["items"]["adj_eps"]["actual"])
                   if actual is not None})


def slot_months(record: dict) -> str:
    spans = []
    for slot in SLOTS:
        dates = [d for d, s in zip(record["release_dates"], record["vintage_slots"]) if s == slot]
        spans.append(month_span(dates))
    return "、".join(spans[:-1]) + "与 " + spans[-1]


def months_gone(record: dict) -> str:
    """How much of the year is over when the settling (Q3) vintage comes out."""
    dates = [d for d, s in zip(record["release_dates"], record["vintage_slots"]) if s == "q3"]
    months = statistics.fmean(int(d[5:7]) - 1 + int(d[8:10]) / 30 for d in dates)
    return f"约{cn_count(round(months))}个月"


def guidance_cuts(record: dict) -> list[int]:
    """Vintages that lowered some metric's lower bound against the one before."""
    cuts = []
    for index in range(1, len(record["vintages"])):
        if record["fiscal_years"][index] != record["fiscal_years"][index - 1]:
            continue
        for item in record["items"].values():
            low, before = item["lo"][index], item["lo"][index - 1]
            if low is not None and before is not None and low < before:
                cuts.append(index)
                break
    return cuts


def layout_sentence(record: dict, lead: str) -> str:
    """How the outlook table is laid out, vintage by vintage, from `layout`."""
    layouts, dates = record["layout"], record["release_dates"]
    by = {kind: [d for d, k in zip(dates, layouts) if k == kind] for kind in set(layouts)}
    unknown = set(by) - {"last", "before_growth", "first", "text"}
    if unknown:
        raise ValueError(f"annual_guidance_history.layout has unknown kinds {sorted(unknown)}")
    pieces = [f"{len(layouts)} 档里 {len(by.get('last', []))} 档的指引列排在最右"]
    if by.get("before_growth"):
        growth = by["before_growth"]
        pieces.append(f"{len(growth)} 档（{months_by_year(growth)}）右边另有一列增速")
    if by.get("first"):
        first = by["first"]
        tail = all(k == "first" for d, k in zip(dates, layouts) if d >= min(first))
        if tail:
            pieces.append(f"{first[0][:4]} 年 {int(first[0][5:7])} 月起改排最左")
        else:
            pieces.append(f"{len(first)} 档（{months_by_year(first)}）排在最左")
    if by.get("text"):
        text = by["text"]
        pieces.append(f"{months_by_year(text)}那{'一' if len(text) == 1 else cn_count(len(text))}档"
                      "只有逐条文字、没有表")
    return lead + "，".join(pieces) + "。"


def guidance_source(record: dict) -> str:
    return ("全年指引的每一档逐字取自当季业绩 6-K 的 EX-99.1 展望部分；"
            + layout_sentence(record, "那张表的列序并不固定：")
            + "本页按表头逐期判断，不按列序取值。")


def adjustment_facts(long: dict) -> dict:
    """Where adjusted and reported differ: quarters for EBITDA/EBIT, years for EPS."""
    diffs = []
    for i, q in enumerate(long["quarters"]):
        gap = long["adj_ebit_eur_m"][i] - long["ebit_eur_m"][i]
        gap_da = long["adj_ebitda_eur_m"][i] - long["ebitda_eur_m"][i]
        if gap or gap_da:
            diffs.append((q, gap))
    eps, eps_years = [], []
    for year, row in long["full_year_actuals"].items():
        adjusted, reported = row.get("adj_diluted_eps_eur"), row.get("diluted_eps_eur")
        if adjusted is None or reported is None:
            continue
        eps_years.append(int(year))
        if adjusted != reported:
            eps.append((int(year), adjusted, reported))
    return {"quarters": diffs, "eps": eps, "eps_years": eps_years}


def adjustment_sentences(long: dict) -> tuple[str, str]:
    """What the margin chart and the method note say about adjusted versus reported."""
    facts = adjustment_facts(long)
    first_year = qparts(long["quarters"][0])[0]
    early = [(q, g) for q, g in facts["quarters"] if qparts(q)[0] == first_year]
    later = [(q, g) for q, g in facts["quarters"] if qparts(q)[0] != first_year]

    def direction(items):
        signs = {g > 0 for _, g in items}
        return "高于" if signs == {True} else "低于" if signs == {False} else "不同于"

    chart = ""
    if early:
        chart += (f"{first_year} 年有非经常调整项（" + " 与 ".join(f"Q{qparts(q)[1]}" for q, _ in early)
                  + f" {cn_count(len(early))}季 adjusted {direction(early)} reported），")
    if later:
        chart += ("此后 adjusted 与 reported 不同的只有 "
                  + "、".join(f"{compact(q)}（adjusted {'高' if g > 0 else '低'} €{abs(g):,.0f}M）"
                              for q, g in later)
                  + "，所以整段用报告口径既连续又与公司口径基本一致；")
    else:
        chart += ("此后 adjusted 与 reported 逐季相同，" if early else "adjusted 与 reported 逐季相同，") \
            + "所以整段用报告口径既连续又与公司口径一致；"

    def quarter_list(items):
        years: dict[int, list[int]] = {}
        for q, _ in items:
            years.setdefault(qparts(q)[0], []).append(qparts(q)[1])
        return "与 ".join(f"{y} 年第" + "、".join(CN_Q[k] for k in ks) + "季" for y, ks in years.items())

    note = "公司指引的是调整后口径，本页结算也用调整后口径。"
    if facts["quarters"]:
        note += f"EBITDA 与 EBIT 的 adjusted 与 reported 只在 {quarter_list(facts['quarters'])}不同"
        parts = []
        if early:
            parts.append(f"{first_year} 年{'两' if len(early) == 2 else cn_count(len(early))}季 adjusted "
                         f"{direction(early)} reported")
        for q, g in later:
            parts.append(f"{cn_quarter(q)} adjusted {'高' if g > 0 else '低'} €{abs(g):,.0f}M")
        note += "（" + "，".join(parts) + "）"
    else:
        note += "EBITDA 与 EBIT 的 adjusted 与 reported 逐季相同"
    years = facts["eps_years"]
    if years:
        span = f"{min(years)}–{max(years)} 年" if len(years) > 1 else f"{years[0]} 年"
        if facts["eps"]:
            note += (f"；{span}的全年摊薄 EPS 两者不同的是 "
                     + "与 ".join(f"{y} 年（调整后 €{a:.2f}、报告口径 €{r:.2f}）" for y, a, r in facts["eps"]))
        else:
            note += f"；{span}的全年摊薄 EPS 两者逐年相同"
    note += "。长序列的利润率一律用报告口径，指引结算一律用调整口径，两者不混。"
    return chart, note


def quarter_sum_census(long: dict, reprints: list[dict]) -> dict:
    """Every complete year's four quarters against the full year the company printed.

    A year that does not add up stops the build -- unless a reprint recorded in
    the series explains it: the company re-presented one quarter and the offset
    belongs to quarters it has not reprinted yet."""
    quarters = long["quarters"]
    checked, exact, explained = 0, 0, []
    years = []
    for year, filed in long["full_year_actuals"].items():
        idx = [quarters.index(f"Q{n} {year}") for n in range(1, 5) if f"Q{n} {year}" in quarters]
        if len(idx) != 4:
            continue
        years.append(int(year))
        for key, name in SUM_KEYS:
            total = sum(long[key][i] for i in idx)
            checked += 1
            if abs(total - filed[key]) <= 1.5:
                exact += 1
                continue
            pending = [r for r in reprints if r["key"] == key and r.get("offset_pending")
                       and qparts(r["quarter"])[0] == int(year)]
            shift = sum(r["first_print"] - r["reprint"] for r in pending)
            if pending and abs(total + shift - filed[key]) <= 1.5:
                explained.append({"year": int(year), "key": key, "name": name,
                                  "gap": filed[key] - total, "reprints": pending})
                continue
            raise ValueError(f"FY{year} {key}: the quarters add to {total:g}, the company printed "
                             f"{filed[key]:g} -- a column read as the wrong period?")
    return {"years": years, "checked": checked, "exact": exact, "explained": explained}


def margin_census(long: dict) -> dict:
    """The page's ratio against the margin the company printed, on the printed basis."""
    worst, beyond = None, []
    count = 0
    for i, q in enumerate(long["quarters"]):
        revenue = long["net_revenues_eur_m"][i]
        adjusted = long["margin_printed_basis"][i] == "adjusted"
        printed_any = False
        for kind, label in (("ebit", "EBIT"), ("ebitda", "EBITDA")):
            printed = long[f"{kind}_margin_printed_pct"][i]
            if printed is None:
                continue
            printed_any = True
            numerator = long[f"adj_{kind}_eur_m" if adjusted else f"{kind}_eur_m"][i]
            own = numerator / revenue * 100
            gap = abs(printed - own)
            # rounding alone: the printed margin to a tenth, both printed figures to EUR 1M
            allowance = 0.05 + (50 + 0.5 * own) / revenue
            if gap > allowance + 1e-9:
                beyond.append(q)
            if worst is None or gap > worst["gap"]:
                worst = {"quarter": q, "label": label, "gap": gap, "printed": printed, "own": own,
                         "numerator": numerator, "revenue": revenue}
        count += printed_any
    return {"quarters": count, "worst": worst, "beyond": list(dict.fromkeys(beyond))}


# ── section one: the full-year guidance record ───────────────────────────────
def form_chart(record: dict, source: str) -> dict:
    """How often each vintage slot published a two-sided range at all."""
    counts = form_counts(record)
    totals = {slot: sum(counts[slot].values()) for slot in SLOTS}
    ranges = {slot: counts[slot]["range"] for slot in SLOTS}
    all_forms = {form: sum(counts[slot][form] for slot in SLOTS) for form in FORM_NAMES}
    readings = sum(all_forms.values())
    early = [ranges[s] for s in ("initial", "q1", "q2")]
    early_text = f"{min(early)}–{max(early)}" if min(early) != max(early) else f"{min(early)}"
    groups = []
    for name, metrics in FORM_GROUPS:
        tally: dict[str, int] = {}
        for metric in metrics:
            for form in record["items"][metric]["form"]:
                if form:
                    tally[form] = tally.get(form, 0) + 1
        ordered = sorted(tally.items(), key=lambda kv: (-kv[1], list(FORM_NAMES).index(kv[0])))
        groups.append(f"{name}{'' if name.endswith('）') else ' '}{sum(tally.values())} 个读数里 "
                      + "、".join(f"{n} 个{FORM_WORDS[f]}" for f, n in ordered))
    mostly_not = all_forms["range"] * 2 < readings
    shed = ranges["q3"] < min(early)
    note = ("<b>这是本页的核心发现，也是本站其他指引页问不出来的问题。</b>"
            "别的公司给的是区间，可以问「实际值有没有落在区间里」；"
            + ("法拉利给的大多不是区间，而是单边不等式 —— " if mostly_not else "法拉利给的不全是区间 —— ")
            + "；".join(groups) + "。"
            f"{cn_count(len(METRIC_NAMES))}个指标、{len(record['vintages'])} 档 vintage 共 {readings} 个读数里，"
            f"只有 {all_forms['range']} 个是两端都有的区间。"
            "更关键的是它们<b>什么时候</b>是区间："
            f"年初、Q1、Q2 三档各有 {early_text} 个区间，而到了 Q3 那一档 —— 也就是结算这一年的那一档，"
            f"发布时全年已过去{months_gone(record)} —— {totals['q3']} 个读数里"
            + (f"只剩 {ranges['q3']} 个还是区间。" if shed else f"有 {ranges['q3']} 个是区间。")
            + ("<b>不确定性最小的时候，指引反而卸掉了上界。</b>"
               "这跟「预测随时间收敛到答案」正好相反，也是本页不把命中率当结论的原因："
               if shed else "本页不把命中率当结论的原因在于：")
            + "对着一个下限说「从没跌破」，接近同义反复。")
    return {
        "ref": "EX_FORM",
        "kind": "grouped_bars",
        "title": (f"指引的<b>形状</b>按发布档次分布：年初那一档 {totals['initial']} 个读数里 "
                  f"{ranges['initial']} 个是两端区间，"
                  f"结算这一年的 Q3 那一档 {totals['q3']} 个读数里只有 "
                  f"{ranges['q3']} 个"),
        "xlabels": [SLOT_NAMES[slot] for slot in SLOTS],
        "groups": [
            {"name": FORM_NAMES["range"], "color": "NAVY",
             "values": [counts[s]["range"] for s in SLOTS]},
            {"name": FORM_NAMES["floor"], "color": "BLUE",
             "values": [counts[s]["floor"] for s in SLOTS]},
            {"name": FORM_NAMES["point"], "color": "GOLD",
             "values": [counts[s]["point"] for s in SLOTS]},
            {"name": FORM_NAMES["ceiling"], "color": "RED",
             "values": [counts[s]["ceiling"] for s in SLOTS]},
        ],
        "bar_labels": True,
        "fmt": "f0", "label_fmt": "f0",
        "ylab": "读数个数",
        "note": note,
        "src_extra": source,
    }


def guidance_band(ref: str, record: dict, metric: str, *, fmt: str, ylab: str,
                  unit: str, source: str, extra_note: str = "") -> dict:
    """One guided metric's own vintages against the year that settled them."""
    item = record["items"][metric]
    labels = record["vintages"]
    tally: dict[str, int] = {}
    for low, high, form, actual in zip(item["lo"], item["hi"], item["form"], item["actual"]):
        if actual is None or low is None:
            continue
        result = verdict(low, high, form, actual)
        tally[result] = tally.get(result, 0) + 1
    finished = sum(tally.values())
    words = {"above": "高于所给的数", "below": "低于所给的数", "inside": "落在区间内",
             "met": "与所给的数持平（在印刷精度内）", "within": "守住了上限",
             "exceeded": "越过了上限"}
    verdict_text = "、".join(f"{count} 年{words[key]}" for key, count in
                            sorted(tally.items(), key=lambda kv: -kv[1]))
    forms_used = [FORM_NAMES[f] for f in dict.fromkeys(f for f in item["form"] if f)]
    return {
        "ref": ref,
        "kind": "range_band",
        "title": f"{METRIC_NAMES[metric]}：{finished} 个已完结年度里，{verdict_text}",
        "xlabels": list(labels),
        "xrot": 90,
        "lo": list(item["lo"]),
        "hi": list(item["hi"]),
        "actual": list(item["actual"]),
        "actual_color": "NAVY",
        "names": {
            "range": f"公司{METRIC_NAMES[metric]}全年指引",
            "actual": f"全年实际{METRIC_NAMES[metric]}",
            "lo": f"指引下缘（{unit}）",
            "hi": f"指引上缘（{unit}）",
        },
        "fmt": fmt, "label_fmt": fmt, "ylab": ylab,
        "note": ("<b>每个财年占据连续的四格</b>：年初首次指引，然后 Q1、Q2、Q3 三次修订；"
                 "菱形只落在该年<b>最后</b>那一格上，因为那才是结算这一年的那一档。"
                 f"这条指引在窗口内用过的形状有：{'、'.join(forms_used)}。"
                 "<b>只给下限或只给单点时，色块没有宽度</b> —— 画成有宽度的区间等于替公司发明一个上界，"
                 f"所以那些格子是一条细线（见 Exhibit {{EX_FORM}}）。"
                 + extra_note
                 + f"<b>时点必须说清楚</b>：四档分别发布于当年的 {slot_months(record)}，"
                 f"最后一档发出时全年已经过去{months_gone(record)}，所以「结清」这个词在这里比在季度指引页上弱得多。"
                 "纵轴不自 0 起，但没有任何点被截掉。"),
        "src_extra": source,
    }


def ebitda_extra(record: dict) -> str:
    """Adjusted EBITDA opened as a range and closed as something else -- while it does."""
    item = record["items"]["adj_ebitda"]
    years = sorted(set(record["fiscal_years"]))
    per_year = {y: [i for i, fy in enumerate(record["fiscal_years"]) if fy == y] for y in years}
    opened = [y for y in years if item["form"][per_year[y][0]] == "range"]
    finished = set(settled_years(record))
    if not opened or opened != list(range(opened[0], opened[-1] + 1)) or not set(opened) <= finished:
        return ""
    closing = [item["form"][per_year[y][-1]] for y in opened]
    if "range" in closing:
        return ""
    switched_at_q3 = all(
        all(item["form"][i] == "range" for i in per_year[y][:-1]) and record["vintage_slots"][per_year[y][-1]] == "q3"
        for y in opened)
    closed = [FORM_SHORT[f] for f in ("point", "floor", "ceiling") if f in closing]
    text = (f"这条指引在 FY{opened[0]}–FY{opened[-1]} 的年初都是两端区间，"
            f"而这{cn_count(len(opened))}年<b>没有一年是以区间收尾的</b>"
            + (f" —— 全部在 Q3 那一档变成{'或'.join(closed)}" if switched_at_q3 else "")
            + "；")
    later = [y for y in years if y > opened[-1]]
    if later and all(item["form"][per_year[y][0]] != "range" for y in later):
        text += f"FY{opened[-1] + 1} 起连年初那一档也不再给区间。"
    else:
        text = text[:-1] + "。"
    return text


def eps_extra(record: dict, long: dict) -> str:
    base = "公司指引的是<b>调整后</b>摊薄 EPS，所以这里的实际值也取调整后口径。"
    rows = long["full_year_actuals"]
    years = settled_years(record)
    differ = [y for y in years if rows[str(y)].get("diluted_eps_eur") is not None
              and rows[str(y)]["diluted_eps_eur"] != rows[str(y)]["adj_diluted_eps_eur"]]
    if not differ:
        return base + "窗口内每一个已完结年度两者都相同。"
    if len(differ) * 2 >= len(years):
        return base + f"两者不同的年份有 {'、'.join(f'FY{y}' for y in differ)}。"
    y = differ[0]
    reported, adjusted = rows[str(y)]["diluted_eps_eur"], rows[str(y)]["adj_diluted_eps_eur"]
    text = (base + f"两者在多数年份相同，但 FY{y} 不同：报告口径 €{reported:.2f}、调整后 €{adjusted:.2f}，"
            f"拿报告值去结算一个按调整口径给出的指引，会凭空造出一次 {abs(reported / adjusted - 1) * 100:.0f}% 的"
            f"{'超预期' if reported > adjusted else '落空'}。")
    if len(differ) > 1:
        text += f"另有 {'、'.join(f'FY{z}' for z in differ[1:])} 两者也不同。"
    return text


def final_vintage_deviation(record: dict, metric: str) -> list[float]:
    item = record["items"][metric]
    out = []
    for index, actual in enumerate(item["actual"]):
        if actual is None or item["lo"][index] is None:
            continue
        out.append((actual / ((item["lo"][index] + item["hi"][index]) / 2) - 1) * 100)
    return out


def ifcf_extra(record: dict) -> str:
    spread = {m: statistics.fmean(abs(v) for v in final_vintage_deviation(record, m))
              for m in METRIC_NAMES}
    ifcf = final_vintage_deviation(record, "ifcf")
    loosest = max(spread, key=spread.get) == "ifcf"
    double = sum(1 for v in ifcf if abs(v) >= 10)
    return ((f"这条是{cn_count(len(METRIC_NAMES))}条里最松的一条：" if loosest else "")
            + f"见 Exhibit {{EX_CONVERGE}} 的口径，工业自由现金流即便到了 Q3 那一档，"
            f"离最终结果平均仍差 {spread['ifcf']:.1f}%，{cn_count(len(ifcf))}年里有"
            f"{cn_count(double) if double else '没有一'}年差到两位数。")


def convergence_chart(record: dict, source: str) -> dict:
    """Deviation of each finished year from EVERY one of its four vintages."""
    years = settled_years(record)
    settled = {}
    for index, actual in enumerate(record["items"]["adj_eps"]["actual"]):
        if actual is not None:
            settled[record["fiscal_years"][index]] = actual
    series = {slot: [] for slot in SLOTS}
    for year in years:
        actual = settled[year]
        for slot in SLOTS:
            value = None
            for index, (fy, sl) in enumerate(zip(record["fiscal_years"],
                                                 record["vintage_slots"])):
                if fy == year and sl == slot:
                    low = record["items"]["adj_eps"]["lo"][index]
                    high = record["items"]["adj_eps"]["hi"][index]
                    if low is not None:
                        value = (actual / ((low + high) / 2) - 1) * 100
                    break
            series[slot].append(value)
    opening = [v for v in series["initial"] if v is not None]
    final = [v for v in series["q3"] if v is not None]
    open_abs = statistics.fmean(abs(v) for v in opening)
    final_abs = statistics.fmean(abs(v) for v in final)
    beaten = sum(1 for v in opening if v > 0)
    missed = [years[i] for i, v in enumerate(series["initial"]) if v is not None and v < 0]
    cuts = guidance_cuts(record)
    story = ""
    if missed:
        revenue = record["items"]["revenue"]
        only_cut = (len(cuts) == 1 and record["fiscal_years"][cuts[0]] == 2020 == missed[0]
                    and record["vintage_slots"][cuts[0]] == "q1"
                    and record["release_dates"][cuts[0]][5:7] == "05"
                    and revenue["form"][cuts[0] - 1] == "floor" and revenue["hi"][cuts[0] - 1] == 4.1
                    and (revenue["lo"][cuts[0]], revenue["hi"][cuts[0]]) == (3.4, 3.6))
        if len(missed) == 1:
            story = f"唯一低于年初指引的是 FY{missed[0]}"
            story += (f" —— {FY2020_CUT}，是这段记录里唯一一次下修。" if only_cut else "。")
        else:
            story = f"低于年初指引的有 {'、'.join(f'FY{y}' for y in missed)}。"
    return {
        "ref": "EX_CONVERGE",
        "kind": "grouped_bars",
        "title": (f"调整后摊薄 EPS 相对<b>每一档</b>指引中值的偏离："
                  f"年初那一档 {len(opening)} 年里 {beaten} 年偏正，"
                  f"平均绝对偏离从 {open_abs:.1f}% 收敛到 {final_abs:.1f}%"),
        "xlabels": [f"FY{year}" for year in years],
        "groups": [
            {"name": "vs 年初首次指引", "color": "NAVY", "values": rounded(series["initial"])},
            {"name": "vs Q1 修订", "color": "BLUE", "values": rounded(series["q1"])},
            {"name": "vs Q2 修订", "color": "GOLD", "values": rounded(series["q2"])},
            {"name": "vs Q3 修订", "color": "RED", "values": rounded(series["q3"])},
        ],
        "bar_labels": False,
        "fmt": "pct1", "label_fmt": "pct1",
        "ylab": "% vs 该档指引中值",
        "note": ("<b>这张图问的是区间图问不了的那个问题：这一年在年初就知道了多少。</b>"
                 "每年四根柱子，是最终实际值相对该年四档指引中值的偏离；"
                 "柱子从左到右变矮，就是这一年的不确定性被逐季消掉的过程。"
                 f"平均绝对偏离从 {open_abs:.1f}% 收到 {final_abs:.1f}%，约 "
                 f"{open_abs / final_abs:.1f} 倍。"
                 f"年初那一档 {len(opening)} 年里有 {beaten} 年被最终结果超过，"
                 + story
                 + "把它和上面几张区间图并排看：区间图说的是「有没有兑现」，"
                   "这张说的是「兑现得多容易」。"),
        "src_extra": source + "偏离为实际值 ÷ 该档指引中值 − 1，本页自算（D）。",
    }


def guidance_charts(staging: dict) -> tuple[list[dict], list[dict]]:
    record = staging["annual_guidance_history"]
    long = staging["long_history"]
    source = guidance_source(record)
    charts = [
        form_chart(record, source),
        guidance_band("EX_EBITDA", record, "adj_ebitda", fmt="f2", ylab="€B", unit="€B",
                      source=source, extra_note=ebitda_extra(record)),
        guidance_band("EX_EPS", record, "adj_eps", fmt="f2", ylab="€/股", unit="€",
                      source=source, extra_note=eps_extra(record, long)),
        guidance_band("EX_IFCF", record, "ifcf", fmt="f2", ylab="€B", unit="€B",
                      source=source, extra_note=ifcf_extra(record)),
        convergence_chart(record, source),
    ]
    labels = record["vintages"]
    rows = []
    for index, label in enumerate(labels):
        cells = [label, record["release_dates"][index]]
        for metric in ["revenue", "adj_ebitda", "adj_ebit", "adj_eps", "ifcf"]:
            item = record["items"][metric]
            low, high, form = item["lo"][index], item["hi"][index], item["form"][index]
            if low is None:
                cells.append("—")
            elif form == "range":
                cells.append(f"{low:g}–{high:g}")
            else:
                mark = {"floor": "≥", "ceiling": "≤", "point": "~"}[form]
                cells.append(f"{mark}{high:g}")
        actual = record["items"]["adj_eps"]["actual"][index]
        cells.append("本档结算" if actual is not None else "")
        rows.append(cells)
    tables = [{
        "title": f"全年指引的 {len(labels)} 档 vintage 原值（€B，EPS 为 €/股）",
        "headers": ["vintage", "发布日", "净收入", "调整后 EBITDA", "调整后 EBIT",
                    "调整后摊薄 EPS", "工业自由现金流", "结算档"],
        "rows": rows,
    }]
    return charts, tables


# ── the quarter's blocks ─────────────────────────────────────────────────────
def quarter_story(staging: dict) -> dict:
    return stamped_block(staging, "quarter_story", staging["periods"][-1]) or {}


def printed_yoy(staging: dict) -> dict:
    return stamped_block(staging, "printed_yoy_pct", staging["periods"][-1]) or {}


def da_guidance(staging: dict) -> dict | None:
    """The full-year D&A figure management gave, turned into the quarterly level the
    rest of the year needs. None when this quarter has no such figure."""
    said = quarter_story(staging).get("da_guidance")
    if said is None:
        return None
    long = staging["long_history"]
    idx = ytd_indices(long["quarters"])
    done = len(idx)
    if done >= 4:
        raise ValueError("quarter_story.da_guidance is stamped on a fourth quarter: "
                         "there is no rest of the year to derive a level for")
    ytd = sum(long["da_eur_m"][i] for i in idx)
    need = said["full_year_floor_eur_m"] - ytd
    return {**said, "done": done, "ytd": ytd, "need": need, "per_quarter": need / (4 - done)}


def kpi_entries(staging: dict) -> tuple[dict, list[dict]]:
    """The stamped threshold block, with each entry's current value measured from the series."""
    block = stamped_block(staging, "next_kpi", staging["periods"][-1])
    if block is None:
        raise ValueError("series `next_kpi` is missing: every quarter carries its thresholds")
    long = staging["long_history"]
    record = staging["annual_guidance_history"]
    americas = long["shipments_americas"]
    idx = ytd_indices(long["quarters"])
    year = qparts(long["quarters"][-1])[0]

    def ifcf_vs_floor() -> float:
        vintages = [i for i, fy in enumerate(record["fiscal_years"]) if fy == year]
        if not vintages:
            raise ValueError(f"annual_guidance_history has no vintage for FY{year}")
        floor = record["items"]["ifcf"]["lo"][vintages[-1]]
        return sum(long["industrial_fcf_eur_m"][i] for i in idx) / (floor * 1000) * 100

    measures = {
        "ebit_margin": lambda: official_margin(long, "ebit", -1),
        "da": lambda: long["da_eur_m"][-1],
        "americas_yoy": lambda: pct_change(americas[-1], americas[-5]),
        "ifcf_ytd_vs_floor": ifcf_vs_floor,
    }
    entries = []
    for entry in block["quantified"]:
        if entry["measure"] not in measures:
            raise ValueError(f"next_kpi entry {entry['metric']!r}: this page does not know how to "
                             f"measure {entry['measure']!r}")
        entries.append({**entry, "current": measures[entry["measure"]]()})
    guide = da_guidance(staging)
    for entry in entries:
        if entry["measure"] == "da" and guide is not None and entry["threshold"] != guide["per_quarter"]:
            raise ValueError(f"next_kpi D&A threshold {entry['threshold']:g} is not the level management's "
                             f"full-year figure implies ({guide['per_quarter']:g})")
    return block, entries


def excluded_text(block: dict) -> str:
    items = block.get("not_tracked", [])
    text = ""
    if items:
        text = (f"另有{cn_count(len(items))}条本地跟踪指标本页不接入："
                + "，以及".join(f"{x['name']}（{x['why']}）" for x in items) + "。")
    return text + block.get("also", "")


# ── section two: what moved this quarter ─────────────────────────────────────
def quarter_charts(staging: dict) -> list[dict]:
    long = staging["long_history"]
    # Everything this section draws is already in `long_history` -- the
    # eight-quarter `financials` block is the same disclosure, cut short.
    labels = long["quarters"]
    da = long["da_eur_m"]
    guide = da_guidance(staging)
    low = lowest_since(da, labels)
    title = f"季度 D&A：本季 €{da[-1]:,.0f}M" + (f" {low}" if low else "")
    series = [{"name": "季度 D&A", "values": rounded(da), "color": "NAVY"}]
    if guide is None:
        note = ("红线只在公司给了全年 D&A 的量化口径时才画 —— 公司不给季度指引，"
                "这一季本页没有录入这样的口径，所以图上只有季度实际值。")
        src = "D&A 为各季业绩新闻稿 EBITDA 还原表的披露值。"
    else:
        done, per_quarter = guide["done"], guide["per_quarter"]
        title += f"，而全年指引隐含的{REST_WORDS[done]}{'季均' if done < 3 else ''}是 €{per_quarter:,.0f}M"
        series.append({"name": f"全年指引隐含的 {REST_SHORT[done]}", "values": [per_quarter] * len(labels),
                       "color": "RED"})
        similar = next((j for j in range(len(da) - 2, -1, -1)
                        if abs(da[j] - per_quarter) <= 0.02 * per_quarter), None)
        note = ("红线不是公司给的季度指引 —— 公司不给季度指引。它是两个披露值相减："
                f"管理层在{guide['said_on']}上{'首次' if guide.get('first_time') else ''}"
                f"把全年 D&A 量化为「超过 €{guide['full_year_floor_eur_m']:,.0f}M」，"
                f"减去{YTD_WORDS[done]}实际的 €{guide['ytd']:,.0f}M，{REST_WORDS[done]}就得 > "
                f"€{guide['need']:,.0f}M" + (f"，季均 ≥ €{per_quarter:,.0f}M。" if done < 3 else "。"))
        if similar is not None:
            back = len(da) - 1 - similar
            note += (f"这个数并不陌生：{cn_quarter(labels[similar])}的实际 D&A 就是 €{da[similar]:,.0f}M。"
                     f"换句话说{REST_WORDS[done]}的「台阶」只是回到{cn_count(back)}个季度前出现过的水平"
                     + ("，而本季的低点才是这条序列里的异常。" if low else "。"))
        src = ("D&A 为各季业绩新闻稿 EBITDA 还原表的披露值；"
               f"隐含季均由公司全年口径与{YTD_WORDS[done]}实际相减得到，本页自算（D）。")
    return [{
        "ref": "EX_DA",
        "kind": "lines",
        "title": title,
        "xlabels": labels,
        "series": series,
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c", "end_label": True,
        "ylab": "€M",
        "note": note,
        "src_extra": src,
    }]


# ── section three: what to watch next ────────────────────────────────────────
def next_quarter_charts(staging: dict, block: dict, entries: list[dict]) -> list[dict]:
    long = staging["long_history"]
    quarters = long["quarters"]
    guide = da_guidance(staging)
    by_measure = {e["measure"]: e for e in entries}
    da_entry = by_measure.get("da")
    note = ("正值表示仍在安全侧。阈值为本地研究设定，<b>不是公司指引</b> —— "
            "法拉利只给全年指引，从不给季度指引。")
    if (da_entry is not None and guide is not None
            and headroom(da_entry["direction"], da_entry["threshold"], da_entry["current"]) < 0):
        note += ("<b>D&A 那根柱子为负是设计使然，不是已经出事</b>："
                 f"它的阈值是全年指引隐含的{REST_WORDS[guide['done']]}季均，本季读数低于它正是本页要说的那件事。")
    exhibits = [headroom_exhibit(
        f"下季 {len(entries)} 条阈值：当前值离阈值的余量",
        entries, "current",
        note + excluded_text(block),
        f"当前值为 {compact(quarters[-1])} 披露值或其自算比值；阈值为本地研究设定。")]

    first_label = compact(quarters[0])
    previous = None
    for entry in entries:
        measure, threshold = entry["measure"], entry["threshold"]
        if measure == "ebit_margin":
            exhibits.append(ebit_threshold_chart(staging, entry))
        elif measure == "da":
            da = long["da_eur_m"]
            implied = guide is not None
            note = ("这条与上一条必须配对读：单看利润率会被折旧节奏骗，"
                    "单看 D&A 又不构成投资判断。" if previous == "ebit_margin" else "")
            note += ("红线是公司全年口径减去" + YTD_WORDS[guide["done"]] + "实际得到的隐含季均，"
                     "不是公司给的季度指引。" if implied else "红线是本地研究设定的阈值，不是公司给的季度指引。")
            note += (f"{len(quarters)} 季的窗口说明这条线的量级本身是新的：{first_label} 的季度 D&A 是 "
                     f"€{da[0]:,.0f}M，{cn_count(len(quarters) // 4)}年里翻了 "
                     f"{da[-1] / da[0]:.1f} 倍，"
                     "而资本化研发正是它的来源（见资本开支那一张）。")
            exhibits.append(threshold_exhibit(
                f"单季 D&A：当前 €{entry['current']:,.0f}M，阈值 €{threshold:,.0f}M",
                quarters, rounded(da), threshold,
                xstep=LONG_STEP, fmt="f0c", ylab="€M",
                actual_name="季度 D&A",
                threshold_name=(f"全年指引隐含的 {REST_SHORT[guide['done']]}" if implied else "本地阈值"),
                note=note,
                src_extra=("D&A 为披露值；隐含季均为本页自算（D）。" if implied
                           else "D&A 为披露值；阈值为本地研究设定。")))
        elif measure == "americas_yoy":
            americas = long["shipments_americas"]
            yoy = [None if index < 4 else pct_change(americas[index], americas[index - 4])
                   for index in range(len(americas))]
            # The series starts where a year-on-year first has a denominator: the
            # first four quarters of the record have nothing to divide by.
            first_yoy = 4
            story = quarter_story(staging).get("americas", "")
            threshold_text = f"{'−' if threshold < 0 else ''}{abs(threshold):.1f}%"
            exhibits.append(threshold_exhibit(
                f"美洲出货同比：当前 {yoy[-1]:.1f}%，阈值 {threshold_text}",
                quarters[first_yoy:], rounded(yoy[first_yoy:]), threshold,
                xstep=LONG_STEP, fmt="pct1", ylab="同比 %",
                actual_name="美洲出货同比", threshold_name="本地阈值",
                note=story + "序列从有同比可算的那一季起画。",
                src_extra="出货为披露值，同比为本页自算（D）；阈值为本地研究设定。"))
        previous = measure
    return exhibits


def ebit_threshold_chart(staging: dict, entry: dict) -> dict:
    long = staging["long_history"]
    quarters = long["quarters"]
    threshold = entry["threshold"]
    margins = [official_margin(long, "ebit", i) for i in range(len(quarters))]
    below = [i for i, m in enumerate(margins) if m < threshold]
    note = entry.get("why", "")
    # What the full-year guidance leaves for the rest of the year.
    record = staging["annual_guidance_history"]
    idx = ytd_indices(quarters)
    year = qparts(quarters[-1])[0]
    vintages = [i for i, fy in enumerate(record["fiscal_years"]) if fy == year]
    if vintages and len(idx) < 4:
        v = vintages[-1]
        ebit_floor = record["items"]["adj_ebit"]["lo"][v]
        revenue_guide = record["items"]["revenue"]["hi"][v]
        if ebit_floor is not None and revenue_guide is not None:
            rest = ((ebit_floor * 1000 - sum(long["adj_ebit_eur_m"][i] for i in idx))
                    / (revenue_guide * 1000 - sum(long["net_revenues_eur_m"][i] for i in idx)) * 100)
            note += f"公司全年指引隐含的{REST_WORDS[len(idx)]}利润率是 {rest:.1f}%，"
            note += ("比这条红线高一档，两者的差就是本页留给「成本节奏」与「结构退潮」之间的判别区间。"
                     if rest > threshold else "已经不高于这条红线。")
    note += (f"<b>放在 {len(quarters)} 季里看，这条红线的位置才说得清</b>："
             f"{compact(quarters[0])} 的 EBIT 利润率是 {margins[0]:.1f}%，")
    above = [i for i, m in enumerate(margins) if m >= threshold]
    if not below:
        note += f"这 {len(quarters)} 季里没有一季低于它。"
    elif not above:
        note += f"这 {len(quarters)} 季里没有一季够到它。"
    else:
        first_above = above[0]
        relapses = [i for i in below if i > first_above]
        note += f"这条线直到 {compact(quarters[first_above])} 才第一次被越过，"
        if relapses:
            last = relapses[-1]
            note += (f"此后还有 {len(relapses)} 个季度跌回它下面，最近一次是 {compact(quarters[last])}"
                     f"（{margins[last]:.1f}%）；{len(quarters)} 季里共有 {len(below)} 个季度低于它。"
                     f"换句话说跌破 {threshold:g}% 不是回到未知领域，{qparts(quarters[last])[0]} 年还发生过。")
        else:
            note += f"此后再没有跌回它下面；{len(quarters)} 季里共有 {len(below)} 个季度低于它。"
    return threshold_exhibit(
        f"EBIT 利润率：当前 {entry['current']:.1f}%，阈值 {threshold:.1f}%",
        quarters, rounded(long["ebit_margin_pct"]), threshold,
        xstep=LONG_STEP, fmt="pct1", ylab="%",
        actual_name="EBIT 利润率", threshold_name="本地阈值",
        note=note,
        src_extra="EBIT 与净收入为披露值，利润率为本页自算（D）；当前值与正文里的利润率取公司印出的数；"
                  "阈值为本地研究设定。")


# ── section four: the long routine series ────────────────────────────────────
def margin_view(long: dict) -> dict:
    n = len(long["quarters"])
    ebit = [official_margin(long, "ebit", i) for i in range(n)]
    ebitda = [official_margin(long, "ebitda", i) for i in range(n)]
    return {"ebit": ebit, "ebitda": ebitda,
            "ebit_change": ebit[-1] - ebit[-2], "ebitda_change": ebitda[-1] - ebitda[-2],
            "record": ebit[-1] > max(ebit[:-1]),
            "diverge": ebit[-1] - ebit[-2] > 0 > ebitda[-1] - ebitda[-2]}


def engines_break(staging: dict) -> dict | None:
    """Where the Engines line stops, and the year the company folded it into Other.

    The fold happened in the 2024 releases, which restated 2023 alongside; the
    series holds the restated 2023, so the gap opens a year before the fold.
    ``reprints`` records which releases restated which quarters."""
    engines = staging["long_history"]["engines_eur_m"]
    quarters = staging["long_history"]["quarters"]
    at = next((i for i, value in enumerate(engines)
               if value is None and i > 0 and engines[i - 1] is not None), None)
    if at is None:
        return None
    restated = [r for r in staging.get("reprints", [])
                if r["key"] == "engines_eur_m" and r["reprint"] is None]
    gap_year = qparts(quarters[at])[0]
    merged = min((qparts(r["reprinted_in"])[0] for r in restated), default=gap_year)
    return {"at": at, "year": gap_year, "merged": merged, "quarter": quarters[at]}


def reprint_words(staging: dict, keys: tuple[str, ...]) -> list[dict]:
    """Reprinted quarters for these series, grouped by the year they belong to:
    ``{"year", "where", "first", "reprint", "rows"}`` -- ``where`` the years of the
    releases that reprinted them. The one still waiting for its offset is left
    to the year-sum census, which explains it."""
    rows = [r for r in staging.get("reprints", []) if r["key"] in keys and not r.get("offset_pending")
            and r["reprint"] is not None]
    groups = {}
    for r in rows:
        groups.setdefault(qparts(r["quarter"])[0], []).append(r)
    return [{"year": year, "rows": rs,
             "where": sorted({qparts(r["reprinted_in"])[0] for r in rs}),
             "first": sum(r["first_print"] for r in rs), "reprint": sum(r["reprint"] for r in rs)}
            for year, rs in sorted(groups.items())]


def long_charts(staging: dict) -> tuple[list[dict], list[dict]]:
    """The ten-year series, split into the four that belong beside the quarter
    and the two that are genuinely routine."""
    long = staging["long_history"]
    quarters = long["quarters"]
    n = len(quarters)
    n_cn = cn_count(n)
    ship = long["shipments_units"]
    per_unit = long["cars_revenue_per_unit_eur_k"]
    cars = long["cars_and_spare_parts_eur_m"]
    mv = margin_view(long)
    story = quarter_story(staging)
    printed = printed_yoy(staging)

    ship_x, pu_x, cars_x = ship[-1] / ship[0], per_unit[-1] / per_unit[0], cars[-1] / cars[0]
    share = math.log(pu_x) / math.log(cars_x)
    split = ("增长主要来自单台价值" if share >= 0.6 else "增长主要来自台数" if share <= 0.4
             else "台数与单台价值差不多各占一半")
    ship_yoy = [pct_change(ship[i], ship[i - 4]) for i in range(4, n)]
    pu_yoy = [pct_change(per_unit[i], per_unit[i - 4]) for i in range(4, n)]
    apart = [a * b < 0 for a, b in zip(ship_yoy, pu_yoy)]
    if apart[-1]:
        now = (f"<b>本季这两条{'仍在' if apart[-2] else ''}走反方向</b>：出货同比 "
               f"{signed(ship_yoy[-1])}，单台车与零件收入同比 {signed(pu_yoy[-1])} —— "
               f"这条记录里 {len(apart)} 个可算同比的季度有 {sum(apart)} 个是这样"
               + ("，是它的主旋律。" if sum(apart) * 2 > len(apart) else "，不到一半。"))
    else:
        now = (f"<b>本季这两条同向</b>：出货同比 {signed(ship_yoy[-1])}，单台车与零件收入同比 "
               f"{signed(pu_yoy[-1])}。")
    unit = {
        "ref": "EX_L_UNIT",
        "kind": "bar_line_dual",
        "title": (f"{n_cn}季的量与价：出货从 {ship[0]:,.0f} 台到 {ship[-1]:,.0f} 台，"
                  f"单台车与零件收入从 €{per_unit[0]:,.0f}千 到 €{per_unit[-1]:,.0f}千"),
        "xlabels": quarters,
        "bar": {"name": "出货（台）", "values": rounded(ship, 0), "color": "BLUE"},
        "line": {"name": "单台车与零件收入（€千）", "values": rounded(per_unit, 1),
                 "color": "RED", "yfmt": "f0c"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "台", "ylab2": "€千/台", "xstep": LONG_STEP,
        "note": ("<b>这张图是这家公司的整个股权故事，八个季度看不出来。</b>"
                 f"{span_words(n)}里出货涨到 {ship_x:.2f} 倍，"
                 f"每台车带来的车与零件收入涨到 {pu_x:.2f} 倍 —— "
                 f"两者相乘是车与零件收入的 {cars_x:.2f} 倍，{split}。"
                 "2020 年第二季那个坑是七周停产，不是需求。"
                 "单台收入不是 ASP：分子含零件与个性化，分母只含整车。"
                 + now),
        "src_extra": f"出货与 Cars and spare parts 收入取自 {n} 份季度业绩新闻稿；比值为本页自算（D）。",
    }

    fy = long["full_year_actuals"]
    gap = {y: fy[y]["da_eur_m"] / fy[y]["net_revenues_eur_m"] * 100 for y in fy}
    narrow, wide = min(gap, key=gap.get), max(gap, key=gap.get)
    last_year = max(gap)
    basis, _ = adjustment_sentences(long)
    if mv["diverge"]:
        tail = (f"<b>本季这两条背离本身就是答案</b>：EBIT 利润率环比 {signed(mv['ebit_change'], 1, 'pp')}"
                + (f"、创下这 {n} 季的纪录 {mv['ebit'][-1]:.1f}%" if mv["record"] else "")
                + f"，而 EBITDA 利润率却 {signed(mv['ebitda_change'], 1, 'pp')} —— "
                "两者之间只隔着折旧摊销一项，所以这次的"
                + ("纪录" if mv["record"] else "改善")
                + "发生在折旧线<b>以下</b>，不是折旧线以上的经营改善（见 Exhibit {EX_DA}）。")
    else:
        tail = (f"本季 EBIT 利润率环比 {signed(mv['ebit_change'], 1, 'pp')}、EBITDA 利润率环比 "
                f"{signed(mv['ebitda_change'], 1, 'pp')}（D&A 见 Exhibit {{EX_DA}}）。")
    margin = {
        "ref": "EX_L_MARGIN",
        "kind": "lines",
        "title": (f"{n_cn}季利润率：EBIT 从 {mv['ebit'][0]:.1f}% 到 {mv['ebit'][-1]:.1f}%，"
                  f"EBITDA 从 {mv['ebitda'][0]:.1f}% 到 {mv['ebitda'][-1]:.1f}%"),
        "xlabels": quarters,
        "series": [
            {"name": "EBIT 利润率", "values": rounded(long["ebit_margin_pct"]), "color": "NAVY"},
            {"name": "EBITDA 利润率", "values": rounded(long["ebitda_margin_pct"]), "color": "BLUE"},
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
        "ylab": "%", "xstep": LONG_STEP,
        "note": ("两条线之间的距离就是折旧摊销占收入的比重。"
                 f"按全年算，它在 {narrow} 年最窄（{gap[narrow]:.1f}%），在 {wide} 年最宽（{gap[wide]:.1f}%），"
                 f"{last_year} 年是 {gap[last_year]:.1f}%。"
                 "这两条画的是<b>报告口径</b>：" + basis
                 + "全年指引的结算另用调整口径，两者不混。"
                 + tail),
        "src_extra": "EBIT、EBITDA 与净收入为披露值，利润率为本页自算（D）；标题与正文里的利润率取公司印出的数。",
    }

    engines = long["engines_eur_m"]
    fold = engines_break(staging)
    break_at = fold["at"] if fold else None
    legs_sum = [sum(long[key][i] for key, _, _ in LEGS) + (engines[i] or 0) for i in range(n)]
    worst_leg_gap = max(abs(s - r) for s, r in zip(legs_sum, long["net_revenues_eur_m"]))
    break_year = fold["year"] if fold else None
    merged = fold["merged"] if fold else None
    # the one move between two legs the company made without a footnote
    shifts = [g for g in reprint_words(staging, ("cars_and_spare_parts_eur_m",))]
    shift_text = "".join(
        f"{g['year']} 年四季的 Cars and spare parts 与 Sponsorship, commercial and brand 取 "
        f"{'、'.join(map(str, g['where']))} 年各季新闻稿上年同期栏的重印值（两者之间 €{abs(g['reprint'] - g['first']):,.0f}M 的重分类）。"
        for g in shifts)
    mix_now = ""
    if printed:
        rates = {}
        for key, name, _ in LEGS:
            values = long[key]
            rates[key] = (name, official_rate(pct_change(values[-1], values[-5]), printed.get(key)),
                          printed.get(key, pct_change(values[-1], values[-5])))
        top = max(rates, key=lambda k: rates[k][2])
        unique = sum(1 for k in rates if rates[k][2] == rates[top][2]) == 1
        mix_now = (f"<b>本季 {rates[top][0]} 同比 {rates[top][1]}"
                   + ("，是三条腿里最快的一条" if unique else "") + "</b>")
        other = story.get("other_revenue")
        mix_now += (f"，{other['text']}" if other and other["leg"] == top else "。")
    mix = {
        "ref": "EX_L_MIX",
        "kind": "grouped_bars",
        "title": ((f"{n_cn}季收入结构：Engines 这一行在 {merged} 年被并进 Other"
                   + (f"，{break_year} 年取重述值" if merged != break_year else "")) if break_year
                  else f"{n_cn}季收入结构"),
        "xlabels": quarters,
        "groups": [
            {"name": "Cars and spare parts", "color": "NAVY",
             "values": rounded(long["cars_and_spare_parts_eur_m"], 0)},
            {"name": "Sponsorship, commercial and brand", "color": "BLUE",
             "values": rounded(long["sponsorship_commercial_brand_eur_m"], 0)},
            {"name": "Other", "color": "GOLD", "values": rounded(long["other_revenues_eur_m"], 0)},
            {"name": f"Engines（{break_year} 年起并入 Other）", "color": "RED", "values": rounded(engines, 0)},
        ],
        "bar_labels": False,
        "fmt": "f0c", "label_fmt": "f0c", "ylab": "€M", "xstep": LONG_STEP,
        "note": ("<b>Engines 那一行是断的，不是归零的。</b>"
                 f"公司自 {merged} 年起把向 Maserati 售发动机的"
                 f"剩余收入并入 Other，并在 {merged} 年各季新闻稿里重述了 {merged - 1} 年的可比数"
                 + (f"，本页取重述值，所以空档从 {compact(fold['quarter'])} 开始" if merged != break_year else "")
                 + "；空档不补零，因为补零会把一次列报变更画成一次业务消失。"
                 f"四条腿在 {break_year} 年之前相加等于合并净收入，之后前三条相加等于合并净收入，"
                 f"{n} 个季度逐季核对"
                 + ("无差。" if worst_leg_gap < 0.5 else f"最大差 €{worst_leg_gap:,.0f}M。")
                 + mix_now),
        "src_extra": (f"各季业绩新闻稿的 Total net revenues 表；并表说明见 {merged} 年各期新闻稿脚注。"
                      + shift_text),
    }
    if break_at is not None:
        mix["break_at"] = break_at
        mix["break_label"] = "Engines 并入 Other"

    china = long["shipments_china_hk_taiwan"]
    total = long["shipments_units"]
    smallest = sum(1 for i in range(n) if china[i] == min(long[key][i] for key, _, _ in REGIONS))
    always = smallest == n
    peak_index = china.index(max(china))
    share_now, share_first = china[-1] / total[-1] * 100, china[0] / total[0] * 100
    first_q = cn_quarter(quarters[0])
    units_word = "多" if china[-1] > china[0] else "少" if china[-1] < china[0] else "一样多"
    share_word = "降到" if share_now < share_first else "升到"
    if (china[-1] > china[0]) == (share_now < share_first):
        units_share = ("<b>要分清台数与占比</b>：以台数论，本季比 " + first_q + f"还{units_word}"
                       f"（{china[-1]:,.0f} 对 {china[0]:,.0f} 台）；以占比论则从 "
                       f"{share_first:.1f}% {share_word} {share_now:.1f}%。")
    else:
        units_share = (f"以台数论，本季比 {first_q}{units_word}（{china[-1]:,.0f} 对 {china[0]:,.0f} 台），"
                       f"占比也从 {share_first:.1f}% {share_word} {share_now:.1f}%。")
    peak = (f"真正的落差是相对自己的高点：{quarters[peak_index]} 的 {china[peak_index]:,.0f} 台"
            f"是这条线的峰值，本季只有它的 {china[-1] / china[peak_index] * 100:.0f}%。"
            if peak_index != n - 1 else "本季就是这条线的峰值。")
    yoy = {key: pct_change(long[key][-1], long[key][-5]) for key, _, _ in REGIONS}
    names = {key: name for key, name, _ in REGIONS}
    positive = [key for key in yoy if yoy[key] > 0]
    def listed(keys: list[str]) -> str:
        quoted = [f"「{names[k]}」" if "、" in names[k] else names[k] for k in keys]
        return quoted[0] if len(quoted) == 1 else "、".join(quoted[:-1]) + "与" + quoted[-1]

    region_now = (f"<b>本季</b>美洲 {long['shipments_americas'][-1]:,.0f} 台、同比 "
                  f"{signed(yoy['shipments_americas'])}")
    others = [k for k in positive if k != "shipments_americas"]
    if len(positive) == 1 and others:
        region_now += f"，{names[others[0]]} 同比 {signed(yoy[others[0]])}，是唯一同比正增长的地区。"
    elif positive == ["shipments_americas"]:
        region_now += "，是唯一同比正增长的地区。"
    elif not positive and all(v < 0 for v in yoy.values()):
        region_now += f"，{cn_count(len(REGIONS))}个地区全部同比下降。"
    elif not positive:
        region_now += "，没有一个地区同比增长。"
    elif "shipments_americas" in positive:
        region_now += f"，{listed(others)}也同比正增长。"
    else:
        region_now += f"，同比正增长的是{listed(others)}。"
    region_now += story.get("regions", "")
    region = {
        "ref": "EX_L_REGION",
        "kind": "lines",
        "title": (f"{n_cn}季分地区出货："
                  + (f"中国大陆、香港与台湾在 {n} 个季度里都是四个地区中最小的一个，" if always
                     else f"中国大陆、香港与台湾在 {n} 个季度里有 {smallest} 季是四个地区中最小的一个，")
                  + f"本季 {china[-1]:,.0f} 台、占 {share_now:.1f}%，"
                  f"而 {quarters[peak_index]} 曾是 {china[peak_index]:,.0f} 台、占 "
                  f"{china[peak_index] / total[peak_index] * 100:.1f}%"),
        "xlabels": quarters,
        "series": [{"name": name, "values": rounded(long[key], 0), "color": color}
                   for key, name, color in REGIONS],
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c", "end_label": True,
        "ylab": "台", "xstep": LONG_STEP,
        "note": (("四条线里最值得看的是最低那条。大中华区在这 " + str(n) + " 个季度里<b>每一季</b>都是四个地区中"
                  "最小的一个，这跟多数奢侈品公司的中国曲线是反的。") if always else
                 f"大中华区在这 {n} 个季度里有 {smallest} 季是四个地区中最小的一个。")
        + units_share + peak + region_now
        + ("地区名称在窗口内改过两次（Greater China → China, Hong Kong and Taiwan → "
           "Mainland China, Hong Kong and Taiwan），口径未变，本页按同一条线画。"),
        "src_extra": "各季业绩新闻稿的 Shipments 表。",
    }

    ifcf = long["industrial_fcf_eur_m"]
    nid = long["net_industrial_debt_eur_m"]
    years = sorted(fy)
    annual = [fy[y]["industrial_fcf_eur_m"] for y in years]
    falls = [years[i] for i in range(1, len(years)) if annual[i] < annual[i - 1]]
    cash_years = (f"全年工业自由现金流从 {years[0]} 年的 €{annual[0]:,.0f}M "
                  f"{'升到' if annual[-1] > annual[0] else '降到'} {years[-1]} 年的 €{annual[-1]:,.0f}M"
                  + ("，逐年抬高" if not falls else
                     f"，其间只有 {'、'.join(falls)} 年比上一年低" if len(falls) * 3 <= len(years) else
                     f"，其间 {len(falls)} 年比上一年低"))
    positive_nid = sum(1 for v in nid if v > 0)
    nid_text = ("而净工业头寸" + (f"在这 {n} 个季度里一直是净负债" if positive_nid == 0 else
                                 f"在这 {n} 个季度里只有{cn_count(positive_nid)}个季度是净现金"
                                 if positive_nid * 4 <= n else
                                 f"在这 {n} 个季度里有 {positive_nid} 个季度是净现金"))
    lowest = {}
    full = 0
    for y in years:
        idx = [quarters.index(f"Q{k} {y}") for k in range(1, 5) if f"Q{k} {y}" in quarters]
        if len(idx) == 4:
            full += 1
            values = [ifcf[i] for i in idx]
            lowest[values.index(min(values)) + 1] = lowest.get(values.index(min(values)) + 1, 0) + 1
    usual = max(lowest, key=lowest.get)
    season = (f"第{CN_Q[usual]}季通常最低" if lowest[usual] * 2 > full
              else "最低的一季并不固定")
    cash = {
        "ref": "EX_L_CASH",
        "kind": "bar_line_dual",
        "title": (f"{n_cn}季工业自由现金流与净工业头寸：本季 IFCF €{ifcf[-1]:,.0f}M，"
                  f"期末净工业{'负债' if nid[-1] < 0 else '现金'} €{abs(nid[-1]):,.0f}M"),
        "xlabels": quarters,
        "bar": {"name": "季度工业自由现金流", "values": rounded(ifcf, 0), "color": "BLUE"},
        "line": {"name": "期末净工业（负债）/现金", "values": rounded(nid, 0),
                 "color": "RED", "yfmt": "f0c"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "€M", "ylab2": "€M", "xstep": LONG_STEP,
        "note": ("净工业负债是负数表示净负债、正数表示净现金。"
                 "两条线放在一起才看得出这家公司的资本配置："
                 f"{cash_years}，{nid_text} —— "
                 "多出来的现金没有留在资产负债表上，也没有变成产能，而是以股息与回购发了出去。"
                 f"季度 IFCF 有强季节性（{season}），跨年比较要同季对同季。"),
        "src_extra": ("工业自由现金流与净工业（负债）/现金均为各季业绩新闻稿的披露值。"
                      + "".join(f"{g['year']} 年四季取 {'、'.join(map(str, g['where']))} 年各季新闻稿上年同期栏的重印值"
                                f"（四季合计 €{g['reprint']:,.0f}M，原印 €{g['first']:,.0f}M）。"
                                for g in reprint_words(staging, ("industrial_fcf_eur_m",)))),
    }

    capex = long["capex_eur_m"]
    first = next(index for index, value in enumerate(capex) if value is not None)
    reprinted = [r for r in staging.get("reprints", []) if r["key"] == "capex_eur_m"]
    capex_basis = ("资本开支不含 IFRS 16 使用权资产，这一口径自 FY2020 新闻稿起在 Capital expenditures "
                   "一行的脚注里写明。")
    if reprinted:
        year = qparts(reprinted[0]["quarter"])[0]
        where = sorted({qparts(r["reprinted_in"])[0] for r in reprinted})
        numbers = sorted(qparts(r["quarter"])[1] for r in reprinted)
        which = (f"前{cn_count(len(numbers))}季" if len(numbers) > 1 and numbers == list(range(1, len(numbers) + 1))
                 else "第" + "、".join(CN_Q[k] for k in numbers) + "季")
        capex_basis += (f"{year} 年{which}的首次印数不在这个口径上，"
                        f"本页用 {'、'.join(map(str, where))} 年各季新闻稿的重印值。")
    capex_chart = {
        "ref": "EX_L_CAPEX",
        "kind": "grouped_bars",
        "title": (f"资本开支与其中的资本化研发：本季 €{capex[-1]:,.0f}M，"
                  f"占收入 {capex[-1] / long['net_revenues_eur_m'][-1] * 100:.1f}%"),
        "xlabels": quarters[first:],
        "groups": [
            {"name": "资本开支", "color": "NAVY", "values": rounded(capex[first:], 0)},
            {"name": "其中：资本化研发", "color": "GOLD",
             "values": rounded(long["capitalised_development_eur_m"][first:], 0)},
        ],
        "bar_labels": False,
        "fmt": "f0c", "label_fmt": "f0c", "ylab": "€M", "xstep": LONG_STEP,
        "note": ("<b>这条序列此前从 2019Q1 起画，理由写的是「更早的季度这个数不存在」—— 那句话是错的。</b>"
                 "业绩新闻稿确实从 2019 年才开始印 Capex and R&D 表，但公司每季的中报 6-K 附件里"
                 "一直有资本开支与资本化研发的<b>累计</b>数，20-F 里有全年数 —— "
                 "2016Q1–2018Q4 由此逐季还原（Q1 取三个月栏，Q2/Q3 相减，Q4 用全年减前九个月）。"
                 "三个财年的四季之和与 20-F 印出的全年逐年相同；2018 四季另有一道完全独立的佐证 —— "
                 "2019 年各季新闻稿里印出的去年同期列与还原值逐格相同。"
                 "资本化研发是资本开支里最大的一块，也是几年后折旧线上那一步的来源，"
                 f"所以它和 Exhibit {{EX_DA}} 是同一件事的两端。"),
        "src_extra": ("2019Q1 起取自各季业绩新闻稿的 Capex and R&D 表；2016Q1–2018Q4 由各季中报 6-K "
                      "附件的累计栏与 20-F 全年数还原 D。" + capex_basis),
    }
    return [unit, margin, mix, region], [cash, capex_chart]


def engines_note(staging: dict) -> str:
    fold = engines_break(staging)
    if fold is None:
        return "Engines 收入一直单列，长序列没有断开。"
    return (f"Engines 收入自 {fold['merged']} 年起并入 Other，公司同时重述了 {fold['merged'] - 1} 年可比数"
            + ("，本页取重述值" if fold["merged"] != fold["year"] else "")
            + f"。长序列在 {compact(fold['quarter'])} 断开并加标记，不补零 —— 补零会把一次列报变更画成一次业务消失。")


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    long = staging["long_history"]
    return [f"Net revenues €{long['net_revenues_eur_m'][-1]:,.0f}M",
            f"EBIT margin {official_margin(long, 'ebit', -1):.1f}%",
            f"出货 {long['shipments_units'][-1]:,.0f} 台"]


def release_source(staging: dict) -> tuple[str, str]:
    """This quarter's release in `sources`: its link text and URL."""
    year, number = qparts(staging["periods"][-1])
    key = f"FY{year} 业绩新闻稿" if number == 4 else f"Q{number} {year} 业绩新闻稿"
    date = staging["release_dates"][-1]
    entry = next((s for s in staging["sources"] if key in s["label"] and date in s["label"]), None)
    if entry is None:
        raise ValueError(f"series `sources` has no {key!r} dated {date}: add this quarter's release")
    name = (f"Ferrari {year} 年第四季度及全年业绩新闻稿（6-K EX-99.1）" if number == 4
            else f"Ferrari {year} 年第{CN_Q[number]}季度业绩新闻稿（6-K EX-99.1）")
    return name, entry["url"]


def build_payload(staging: dict) -> dict:
    long = staging["long_history"]
    labels = staging["periods"]
    record = staging["annual_guidance_history"]
    quarters = long["quarters"]
    n = len(quarters)
    period = labels[-1]
    if quarters[-1] != period:
        raise ValueError(f"long_history ends at {quarters[-1]!r} but `periods` ends at {period!r}: "
                         "append the quarter to both")
    kpi_block, entries = kpi_entries(staging)

    settled, settled_tables = guidance_charts(staging)
    structural, routine = long_charts(staging)
    highlights = quarter_charts(staging) + structural
    next_block = next_quarter_charts(staging, kpi_block, entries)

    exhibits = number_exhibits(settled + highlights + next_block + routine)
    resolve_exhibit_refs(exhibits)
    n_settled, n_high, n_next = len(settled), len(highlights), len(next_block)
    settled_ex = exhibits[:n_settled]
    highlight_ex = exhibits[n_settled:n_settled + n_high]
    next_ex = exhibits[n_settled + n_high:n_settled + n_high + n_next]
    routine_ex = exhibits[n_settled + n_high + n_next:]

    first_table = exhibits[-1]["n"] + 1
    tables = [{**table, "n": first_table + index}
              for index, table in enumerate(settled_tables)]
    window = range(n - len(labels), n)
    tables.append({
        "n": first_table + len(settled_tables),
        "title": f"近{cn_count(len(labels))}季合并损益与经营指标（公司披露值，除标注外）",
        "headers": ["期间", "出货（台）", "净收入", "Cars and spare parts", "EBITDA",
                    "EBIT", "EBIT 利润率", "D&A", "净利润", "摊薄 EPS",
                    "资本开支", "工业自由现金流", "净工业（负债）/现金"],
        "rows": [[quarters[i], f"{long['shipments_units'][i]:,.0f}",
                  f"€{long['net_revenues_eur_m'][i]:,.0f}M",
                  f"€{long['cars_and_spare_parts_eur_m'][i]:,.0f}M",
                  f"€{long['ebitda_eur_m'][i]:,.0f}M",
                  f"€{long['ebit_eur_m'][i]:,.0f}M",
                  f"{official_margin(long, 'ebit', i):.1f}%",
                  f"€{long['da_eur_m'][i]:,.0f}M",
                  f"€{long['net_profit_eur_m'][i]:,.0f}M",
                  f"€{long['diluted_eps_eur'][i]:.2f}",
                  f"€{long['capex_eur_m'][i]:,.0f}M",
                  f"€{long['industrial_fcf_eur_m'][i]:,.0f}M",
                  f"€{long['net_industrial_debt_eur_m'][i]:,.0f}M"]
                 for i in window],
    })
    tables.append(threshold_table(first_table + len(settled_tables) + 1,
                                  "下季阈值与当前值（原始单位）", entries, "current", "当前值"))
    tables.append(ai_capex_cycle_table(first_table + len(settled_tables) + 2))

    revenue = long["net_revenues_eur_m"]
    da = long["da_eur_m"]
    ship = long["shipments_units"]
    per_unit = long["cars_revenue_per_unit_eur_k"]
    mv = margin_view(long)
    printed = printed_yoy(staging)
    guide = da_guidance(staging)
    low = lowest_since(da, quarters)
    counts = form_counts(record)
    ranges_q3, q3_total = counts["q3"]["range"], sum(counts["q3"].values())
    ranges_initial = counts["initial"]["range"]
    shed = ranges_q3 < min(counts[s]["range"] for s in ("initial", "q1", "q2"))
    all_ranges = sum(counts[s]["range"] for s in SLOTS)
    all_readings = sum(sum(counts[s].values()) for s in SLOTS)
    finished = len(settled_years(record))

    rev_yoy = official_rate(pct_change(revenue[-1], revenue[-5]), printed.get("net_revenues_eur_m"))
    da_now = f"本季 €{da[-1]:,.0f}M" + (f" {low}" if low else "")
    headline = (f"净收入 €{revenue[-1]:,.0f}M、同比 {rev_yoy}，"
                f"EBIT 利润率 {mv['ebit'][-1]:.1f}%" + (" 创窗口新高" if mv["record"] else ""))
    if mv["diverge"]:
        headline += (f"，但同一季 EBITDA 利润率 {signed(mv['ebitda_change'], 1, 'pp')}，"
                     f"两者之间只隔着 D&A —— {da_now}")
    else:
        headline += (f"、环比 {signed(mv['ebit_change'], 1, 'pp')}，EBITDA 利润率环比 "
                     f"{signed(mv['ebitda_change'], 1, 'pp')}；D&A {da_now}")
    if guide is not None:
        headline += (f"，而全年指引隐含的{REST_WORDS[guide['done']]}{'季均' if guide['done'] < 3 else ''}"
                     f"是 €{guide['per_quarter']:,.0f}M")
    headline += (f"；出货同比 {signed(pct_change(ship[-1], ship[-5]))} 而单台车与零件收入同比 "
                 f"{signed(pct_change(per_unit[-1], per_unit[-5]))}。")

    da_brief = f"本季 €{da[-1]:,.0f}M" + (f" 为 {low[2:]}" if low else "")
    if mv["record"] and mv["diverge"]:
        quarter_card = ("<b>纪录利润率发生在折旧线以下</b>"
                        f"<p>EBIT 利润率 {mv['ebit'][-1]:.1f}% 创新高，EBITDA 利润率却下滑；"
                        f"差额全部是 D&amp;A，{da_brief}。</p>")
    elif mv["diverge"]:
        quarter_card = ("<b>利润率的改善发生在折旧线以下</b>"
                        f"<p>EBIT 利润率 {mv['ebit'][-1]:.1f}%、环比 {signed(mv['ebit_change'], 1, 'pp')}，"
                        f"EBITDA 利润率却下滑；差额全部是 D&amp;A，{da_brief}。</p>")
    else:
        quarter_card = ("<b>利润率与折旧</b>"
                        f"<p>EBIT 利润率 {mv['ebit'][-1]:.1f}%、环比 {signed(mv['ebit_change'], 1, 'pp')}；"
                        f"EBITDA 利润率环比 {signed(mv['ebitda_change'], 1, 'pp')}；"
                        f"D&amp;A {da_brief}。</p>")
    ship_x = ship[-1] / ship[0]
    pu_x = per_unit[-1] / per_unit[0]

    yoy_regions = [pct_change(long[key][-1], long[key][-5]) for key, _, _ in REGIONS]
    ship_yoy = pct_change(ship[-1], ship[-5])
    pu_yoy = pct_change(per_unit[-1], per_unit[-5])
    topics = ["利润率与折旧" + ("的背离" if mv["diverge"] else ""),
              "量与价的长期走势" + ("与本季的反向" if ship_yoy * pu_yoy < 0 else ""),
              "收入结构的口径断点",
              "分地区出货" + ("的分化" if min(yoy_regions) < 0 < max(yoy_regions) else "")]
    all_long = all(len(ex.get("xlabels", [])) == n for ex in highlight_ex)
    guidance_word = "大多不是区间" if all_ranges * 2 < all_readings else "不全是区间"
    name, url = release_source(staging)
    audit = AUDIT_WORDS.get(staging["latest"]["audit_status"])
    if audit is None:
        raise ValueError(f"latest.audit_status {staging['latest']['audit_status']!r} is not one this page prints")
    census = quarter_sum_census(long, staging.get("reprints", []))
    census_text = (f"{len(census['years'])} 个财年 × {len(SUM_KEYS)} 个指标共 {census['checked']} 项")
    if not census["explained"]:
        census_text += "全部通过。"
    else:
        census_text += f"里 {census['exact']} 项逐项相等；"
        for item in census["explained"]:
            r = item["reprints"][0]
            census_text += (f"{item['year']} 年的{item['name']}四季相加比全年印数"
                            f"{'少' if item['gap'] > 0 else '多'} €{abs(item['gap']):,.0f}M："
                            f"公司在 {cn_quarter(r['reprinted_in'])}的新闻稿里把 {compact(r['quarter'])} 重列为 "
                            f"€{r['reprint']:,.0f}M（原印 €{r['first_print']:,.0f}M），{r['note']}。")
    margins = margin_census(long)
    worst = margins["worst"]
    margin_text = (f"自算的利润率与公司自己印出的利润率 {margins['quarters']} 个季度逐季比对"
                   "（公司只印调整后口径的季度按调整后自算），"
                   f"最大差 {worst['gap']:.2f}pp，在 {compact(worst['quarter'])} 的 {worst['label']} 利润率："
                   f"公司印 {worst['printed']:.1f}%，按同一份新闻稿的 €{worst['numerator']:,.0f}M ÷ "
                   f"€{worst['revenue']:,.0f}M 是 {worst['own']:.1f}%。"
                   + ("两者之差都在四舍五入能解释的范围内。" if not margins["beyond"] else
                      f"超出四舍五入所能解释的只有 {'、'.join(compact(q) for q in margins['beyond'])} "
                      + (f"{cn_count(len(margins['beyond']))}季。" if len(margins['beyond']) > 1 else "这一季。"))
                   + "正文与表格里的利润率一律用公司印的数，图上的利润率线是自算。")
    _, adjust_note = adjustment_sentences(long)

    return {
        "schema_version": "quarterly-dashboard/race-v1",
        "page": {"slug": "race", "language": "zh-CN"},
        "company": {
            "ticker": "RACE",
            "name": "Ferrari N.V.",
            "group": "luxury_brands",
            "accounting_standard": "IFRS",
        },
        "latest": latest_block(
            staging,
            period=staging["periods"][-1],
            period_end=staging["period_ends"][-1],
            release_date=staging["release_dates"][-1]),
        "tracker": "Watchlist Quarterly Tracker · RACE",
        "title": f"Ferrari N.V. (RACE)：{period} 季报仪表盘",
        "subtitle": (f"截至 {staging['period_ends'][-1]} · 发布 {staging['release_dates'][-1]} · IFRS · 欧元列示 · "
                     f"{audit} · 自然年财年，季度标注与财年一致 · 数据来自季度业绩 6-K 的 EX-99.1"),
        "headline": headline,
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>记录</span><b>'
            + ("指引在最确定的时候卸掉上界" if shed else "指引的形状随年份推进怎么变")
            + f'</b><p>{len(record["vintages"])} 档 vintage 里，年初那一档有 {ranges_initial} 个读数是两端区间；'
            f'结算全年的 Q3 那一档 {q3_total} 个读数里{"只剩" if shed else "有"} {ranges_q3} 个。'
            '对着下限说「从没跌破」接近同义反复，所以本页看的是超出多少。</p></article>'
            '<article><span>本季</span>' + quarter_card + '</article>'
            '<article><span>结构</span>'
            f'<b>{span_words(n)}里台数涨到 {ship_x:.1f} 倍，单台收入涨到 {pu_x:.1f} 倍</b>'
            f'<p>出货 {ship[0]:,.0f} → {ship[-1]:,.0f} 台，'
            f'单台车与零件收入 €{per_unit[0]:,.0f}千 → '
            f'€{per_unit[-1]:,.0f}千。</p></article>'
            '</div>'),
        "source": (f'Source: <a href="{url}" rel="noopener">{name}</a>。'
                   '法拉利为外国私人发行人，不报 10-Q/10-K/8-K，年度申报为 20-F。'),
        "source_url": url,
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {"id": "settled", "title": "一、公司自己的指引兑现了吗",
             "description": (f"法拉利只给全年指引，每季修订一次，而且给的{guidance_word}，"
                             "是「至少」「不超过」「约」这样的单边不等式。"
                             f"所以这一节先看指引的形状怎么随年份推进而变，再看{cn_count(finished)}个已完结年度落在哪里。"),
             "exhibits": settled_ex},
            {"id": "quarter_highlights", "title": "二、本季重点",
             "description": ("、".join(topics[:-1]) + "，以及" + topics[-1] + "。"
                             + (f"本节每一张都画在 {compact(quarters[0])} 起的 {n} 个季度上 —— " if all_long else "")
                             + "这四条序列此前在本页出现过两次：这里八季、第四节四十二季。"
                               "同一条线画两种长度不是两张图，短的那一版已经去掉。"),
             "exhibits": highlight_ex},
            {"id": "next_quarter", "title": "三、下季要跟踪什么",
             "description": (f"{cn_count(len(entries))}条可从申报复算的阈值，统一用「距阈值余量」口径；"
                             f"本页不接入的{cn_count(len(kpi_block.get('not_tracked', [])))}条写在这里。"),
             "exhibits": next_ex},
            {"id": "routine", "title": "四、长期常规跟踪",
             "description": f"{cn_count(n)}个季度的工业自由现金流、净工业头寸与资本开支。",
             "exhibits": routine_ex},
        ],
        "tables": tables,
        "notes": [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            f"法拉利是外国私人发行人（foreign private issuer），不提交 10-Q、10-K 或 8-K：年度申报是 20-F，季度业绩只以 6-K 的 EX-99.1 新闻稿提交。本站其他公司页所依赖的 10-Q/10-K 渲染报表（R-files）对本公司不存在，本页 {n} 个季度的数据以这 {n} 份新闻稿为主，另有三处补充：2016Q1–2018Q4 的资本开支与资本化研发来自各季中报 6-K 附件的累计栏与 20-F 全年数（新闻稿从 2019 年才开始印 Capex and R&D 表），Q4 2016 的摊薄加权股数来自 FY2017 新闻稿的上年对照栏，2016 四季的每股收益来自当年中报与年报里合并的「Basic and diluted」一行。",
            "报表采用 IFRS 并以欧元列示，是本站第一家两者皆非美国口径的公司。财年即自然年，季度标注与公司自己的口径一致，无需换算。",
            "2016 至 2018 年的第二、三季新闻稿把累计栏印在标签左侧、当季栏印在右侧，2019 年起两栏对调。按固定列序取值会把半年报与九个月的数字读成单季，而且四条恒等式全都照样成立（收入分项相加、地区相加、EBITDA 还原、EBIT 还原），因为各项是一起变成累计的。本页按每张表自己的期间表头判断，并以「四个季度相加等于公司印出的全年」作为最终检查：" + census_text,
            layout_sentence(record, "全年指引表的列序并不固定：")
            + "按固定列序取最右一列，在改排最左的各期会把上一年的实际值当成本年指引、在右边带增速列的各期会取到增速，本页按表头逐期判断。",
            adjust_note,
            "指引形状分为四类：两端区间、只给下限、只给上限、单点约数。只给下限或单点时图上的色块没有宽度，画成有宽度的区间等于替公司发明一个上界。判定「兑现」时对单点与下限留出等于印刷精度的容差：公司把 €1.27B 印到小数点后两位，FY2019 的 €1.269B 因此记为持平而不是跌破。",
            f"全年指引的四档分别发布于当年的 {slot_months(record)}，最后一档发出时全年已过去{months_gone(record)}。因此「结清」在本页比在季度指引页上弱得多，本页对每张区间图都写明了这一点，并另画一张相对每一档指引的偏离图。",
            engines_note(staging),
            f"资本开支与资本化研发的序列自 {compact(quarters[next(i for i, v in enumerate(long['capex_eur_m']) if v is not None)])} 起：业绩新闻稿从 2019 年第一季才开始印 Capex and R&D 表，更早的季度由各季中报 6-K 附件的累计栏与 20-F 全年数逐季还原（见资本开支那一张的图注）。",
            "单台车与零件收入为 Cars and spare parts 收入除以出货台数，是本页自算（D），不是 ASP：分子含零件与个性化收入，分母只含整车。公司已明确表示永不披露车型级的出货量与售价。",
            "地区披露的是出货台数而非收入，因此地域结构对收入与利润的影响无法从申报中拆出来，本页不做该拆分。",
            "本页不发布市场一致预期、评级、目标价与估值。第三节的阈值是本地研究设定，不是公司指引。",
            "本页只发布公司披露值与可复算的简单派生值；D 标记代表 Derived / 自算。" + margin_text,
            "核对抽屉最后那张「AI capex 循环」是全站共用的跨页对照块，在每一页都逐字节相同，不是对法拉利的判断。它追的是四家云厂现金资本开支 → NVDA 数据中心收入 → TSM 晶圆这条链，法拉利不在这条链的任何一环上。把它放在这里是为了让读者在任意一页都能查到同一份上下游对照；它在折叠的抽屉里，不参与本页的论证。",
            f"本页已知未接入：个性化收入占比（只在电话会上以定性口径出现，从未进入新闻稿或申报）、订单簿覆盖年限（新闻稿里只以 CEO 引语出现，没有可逐季比较的数字）、2027 年汇率对冲覆盖率（管理层仅称覆盖率低得多，未给数）、车型级出货与售价（公司明确永不披露）、恒定汇率口径的完整历史序列（公司只在近年新闻稿中逐期给出），以及 {cn_quarter(period, '季度')}之后的任何数据（本页数据截至 {staging['release_dates'][-1]} 的申报）。",
            "业绩电话会内容仅用于定位公司已在新闻稿中量化的项目，公开仓不复制原件或逐字内容。",
        ],
        "footer": "Ferrari quarterly results · 数据来自 Ferrari 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "race.js"), payload, "race")
    shell_dir = ROOT / "race"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("RACE", "race"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"RACE page: {charts} charts in {len(payload['sections'])} sections "
          f"+ {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
