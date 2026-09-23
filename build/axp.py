"""American Express quarterly dashboard.

**This is the first page on this site whose guidance record cannot be settled.**
American Express publishes a full-year outlook in the EX-99.1 of its earnings
8-Ks -- EPS every year, revenue growth from FY2018 -- and the honest answer to
"did it clear it" is *for about half of those years there is no answer*: the
company moved the basis of its own promise, printed two ranges in the same year,
withdrew one outlook and did not publish one at all for a whole year.

What is left after the unsettleable years are removed is a two-sided finding
that only exists because both metrics sit in the same sentence of the same
release: full-year EPS has not landed below its range in any settleable year,
full-year revenue growth has -- once, in FY2023, where the company's own
FX-adjusted figure met the floor exactly and its reported figure did not. Every
count, year and direction in those sentences is recomputed from
``series/axp.json`` on each build; none is typed here.

Section two is why. The distance from one quarter's pretax income to the same
quarter a year before splits exactly two ways -- an operating leg and a
provision leg, both filed, no estimate anywhere.

The page is rolled by editing ``series/axp.json`` alone. Which years settle, the
verdicts and where each actual lands on the vintage axis are derived from the
guidance record; the only stored judgements are the years the page declines to
settle (``unsettleable``), each with its reason. What only one quarter has --
the settlement of last quarter's thresholds, next quarter's thresholds and the
quarter's own sentences -- sits in blocks stamped with the quarter
(``board.stamped_block``); ``_checks`` is a separate reading of the quarter's
release that the tests hold the page to and this builder never reads.

Published numbers are company-reported or transparent arithmetic. No rating, no
target price, no valuation. Market expectations are not published on this page:
no dated, checkable public source for one was available.
"""

from __future__ import annotations

import json
import math
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
    fill_story,
    headroom_exhibit,
    latest_block,
    midpoint_deviation,
    minus_sign,
    number_exhibits,
    stamped_block,
    threshold_exhibit,
    threshold_table,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402

STAGING_PATH = ROOT / "series" / "axp.json"
DATA_DIR = ROOT / "data"

# One tick per year keeps a forty-two-quarter axis readable.
LONG_STEP = 4


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100.0


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def money(value: float) -> str:
    """A signed dollar change: ``+US$521M`` / ``−US$80M``."""
    return f"{'−' if value < 0 else '+'}US${abs(value):,.0f}M"


def rounded(values, digits: int = 6):
    return [None if v is None else round(v, digits) for v in values]


def plain_text(html: str) -> str:
    """Strip markup for the fields the renderer writes with ``textContent``.

    ``section.description`` and every string in ``notes`` reach the page through
    ``esc()`` or ``textContent``, so a ``<b>`` in them is published as the four
    literal characters. Emphasis belongs in an exhibit note, which is rendered.
    """
    return re.sub(r"<[^>]+>", "", html)


def fiscal_of(vintage_label: str) -> str:
    """``'FY23 Q2'`` -> ``'FY23'`` -- the deviation charts count years."""
    return vintage_label.split()[0]


def joined(items: list[str]) -> str:
    """「A」 / 「A 与 B」 / 「A、B 与 C」."""
    return items[0] if len(items) == 1 else "、".join(items[:-1]) + " 与 " + items[-1]


def quarter_words(label: str) -> str:
    """``'Q2 2026'`` -> ``'2026 年第二季度'``, the way the source labels name a quarter."""
    quarter, year = label.split()
    return f"{year} 年第{cn_ordinal(int(quarter[1]))}季度"


def compact_period(period: str) -> str:
    """``'2022Q4'`` -> ``"Q4'22"``."""
    return f"{period[4:]}'{period[2:4]}"


def resolve_exhibit_refs(exhibits: list[dict]) -> list[dict]:
    """Replace ``{EX_NAME}`` placeholders with numbers assigned at render time."""
    numbers = {ex["ref"]: ex["n"] for ex in exhibits if "ref" in ex}
    for exhibit in exhibits:
        for field in ("note", "src_extra", "title"):
            text = exhibit.get(field)
            if not text:
                continue
            for ref, number in numbers.items():
                text = text.replace("{" + ref + "}", str(number))
            exhibit[field] = text
    return exhibits


def release_source(staging: dict) -> dict:
    """This quarter's own release in `sources`, found by its label."""
    label = f"American Express {quarter_words(staging['period_labels'][-1])}业绩新闻稿"
    found = next((item for item in staging["sources"] if item["label"].startswith(label)), None)
    if found is None:
        raise ValueError(f"series `sources` has no entry for the {label}: add this "
                         "quarter's release with the roll")
    return found


def statistical_tables_words(staging: dict, release: dict) -> str:
    """「与同一份 8-K 的 EX-99.2 统计表」 when `sources` carries that exhibit.

    The exhibit's label does not name a quarter, so it counts as this quarter's
    only when it sits in the same EDGAR filing folder as the release itself.
    """
    folder = release["url"].rsplit("/", 1)[0]
    for item in staging["sources"]:
        if "EX-99.2" in item["label"] and item["url"].rsplit("/", 1)[0] == folder:
            return "与同一份 8-K 的 EX-99.2 统计表"
    return ""


def release_of(staging: dict, index: int) -> str:
    """Release date of the quarter at ``index`` of the quarterly axis.

    The guidance record carries one vintage per quarterly release, in order, and
    its first vintage is the release of the quarter *before* the axis starts --
    so the quarter at ``index`` was released on ``filed[index + 1]``.
    """
    g = staging["annual_guidance_history"]
    first = staging["periods"][0]
    year, quarter = int(first[:4]), int(first[5])
    opening = (year - 1, 4) if quarter == 1 else (year, quarter - 1)
    if (g["fiscal_years"][0] - 1, 4) != opening or g["vintage_slots"][0] != "初":
        raise ValueError("the guidance record no longer opens one release before the quarterly axis")
    return g["filed"][index + 1]


# ── the annual guidance record, counted once for every sentence that uses it ──
METRIC_KEYS = {
    "eps": ("guide_eps_lo_usd", "guide_eps_hi_usd", "guide_eps_form"),
    "revenue": ("guide_revenue_growth_lo_pct", "guide_revenue_growth_hi_pct",
                "guide_revenue_form"),
}
# Qualifiers on a vintage that change what the printed number means. The others
# in `BASIS_ZH` describe how a figure was printed (only the high end, subject to
# contingencies) or that none was (withdrawn, never issued, reaffirmed in words).
BASIS_CHANGES = ("adj_ex_restructuring", "adjusted_no_gaap", "adjusted_dual",
                 "fx_adjusted_revenue", "includes_accertify_gain")
BASIS_ZH = {
    "adj_ex_restructuring": "调整后，剔除重组费用",
    "adjusted_no_gaap": "调整后，公司写明无 GAAP 对照",
    "adjusted_dual": "同时印 GAAP 与调整后两条",
    "ex_contingencies": "「subject to contingencies」",
    "high_end_only": "只重申「区间上沿」，不是整条区间",
    "fx_adjusted_revenue": "收入指引为汇率调整口径",
    "includes_accertify_gain": "含 Accertify 出售收益",
    "withdrawn": "已撤回",
    "never_issued": "从未给出",
    "reaffirmed_no_number": "口头重申，未印数字",
}
FORM_ZH = {"range": "区间", "point": "单点", "floor": "只有下限", None: "—"}
VERDICT_ZH = {"inside": "落在区间内", "above": "高于上限", "below": "跌破下限",
              "inside_on_bound": "正好落在下限上（区间内）",
              "equals_point": "与指引的单点相同"}
# The reasons a year cannot be settled, and how each place on the page says it.
# The two judged kinds carry their own per-year sentences in the series file;
# the rest are read off the record.
REASON_BRIEF = {"two_ranges": "同年印了两条区间", "basis": "口径对不上", "withdrawn": "被撤回",
                "never": "从未给出", "not_guided": "从未给出", "open": "尚未结束"}


def band_words(lo: float, hi: float, metric: str) -> str:
    """How the ledger and the reasons print one vintage's range."""
    if metric == "eps":
        return f"${lo:.2f}" if lo == hi else f"${lo:.2f}–${hi:.2f}"
    return f"{lo:.0f}%" if lo == hi else f"{lo:.0f}%–{hi:.0f}%"


def verdict_of(lo: float, hi: float, value: float, exact: float | None) -> str:
    """Where the delivered figure landed on the vintage that settles the year.

    ``inside_on_bound`` is the case the notes single out: the company's own
    whole-point figure sits on the floor only because it was rounded there
    (FY2019 delivered 7.98% against a floor of 8%).
    """
    if lo == hi:
        return "equals_point" if value == lo else ("above" if value > hi else "below")
    if value > hi:
        return "above"
    if value < lo:
        return "below"
    if value == lo and exact is not None and exact < lo:
        return "inside_on_bound"
    return "inside"


def record_facts(staging: dict) -> dict:
    """Which years settle, against which vintage, and what they say -- per metric."""
    g = staging["annual_guidance_history"]
    n = len(g["vintages"])
    years = sorted(set(g["fiscal_years"]))
    actuals = g["actual_by_year"]
    basis = g["guide_eps_basis"]
    judged = g["unsettleable"]
    unknown = {code for code in basis if code is not None} - set(BASIS_ZH)
    if unknown:
        raise ValueError(f"guidance basis codes with no wording: {sorted(unknown)}")
    facts = {"years": years, "n": n, "metrics": {}}
    for metric, (lo_k, hi_k, form_k) in METRIC_KEYS.items():
        settle, verdicts, reasons, actual = {}, {}, {}, [None] * n
        for year in years:
            idx = [i for i in range(n) if g["fiscal_years"][i] == year]
            numeric = [i for i in idx if g[lo_k][i] is not None]
            banded = [i for i in numeric if g[form_k][i] != "floor"]
            codes = {basis[i] for i in idx}
            if str(year) in judged[metric]:
                reasons[year] = dict(judged[metric][str(year)])
            elif "withdrawn" in codes:
                first = numeric[0]
                qualifier = "（汇率调整口径）" if (metric == "revenue"
                                              and basis[first] == "fx_adjusted_revenue") else ""
                reasons[year] = {
                    "kind": "withdrawn",
                    "ledger": (f"年初给过 {band_words(g[lo_k][first], g[hi_k][first], metric)}"
                               f"{qualifier}，{g['withdrawal']['announced']} 的另一份 8-K 撤回")}
            elif codes == {"never_issued"}:
                reasons[year] = {"kind": "never", "ledger": (
                    "全年从未给过 EPS 指引" if metric == "eps" else "全年从未给过收入指引")}
            elif not numeric:
                reasons[year] = {"kind": "not_guided", "ledger": "公司当年不指引收入"}
            elif str(year) not in actuals:
                reasons[year] = {"kind": "open", "ledger": "本年度尚未结束"}
            elif not banded:
                raise ValueError(f"FY{year} {metric} guidance is only ever a floor: decide in "
                                 "`unsettleable` whether and how it settles")
            else:
                i = banded[-1]
                block = actuals[str(year)]
                if metric == "eps":
                    value, exact = block["eps"], None
                else:
                    value, exact = float(block["growth_reported_pct"]), block["growth_exact_pct"]
                settle[year] = i
                verdicts[year] = verdict_of(g[lo_k][i], g[hi_k][i], value, exact)
                actual[i] = value
        facts["metrics"][metric] = {
            "settle": settle, "verdicts": verdicts, "reasons": reasons, "actual": actual,
            "below": [y for y, v in verdicts.items() if v == "below"],
            "above": [y for y, v in verdicts.items() if v == "above"],
        }
    blank = [i for i in range(n)
             if g["guide_eps_lo_usd"][i] is None and g["guide_revenue_growth_lo_pct"][i] is None]
    runs, run = [], []
    for i in blank:
        if run and i != run[-1] + 1:
            runs.append(run)
            run = []
        run.append(i)
    if run:
        runs.append(run)
    facts["blank"] = blank
    facts["longest_blank"] = max(runs, key=len) if runs else []
    facts["open"] = [y for y in years if str(y) not in actuals]
    return facts


def midpoint_split(g: dict, metric: dict, keys: tuple) -> dict:
    """Settled years above, on and below the midpoint of their settling vintage."""
    lo_k, hi_k, _ = keys
    out = {"above": [], "equal": [], "below": [], "outside": []}
    for year, i in sorted(metric["settle"].items()):
        mid = (g[lo_k][i] + g[hi_k][i]) / 2
        value = metric["actual"][i]
        out["above" if value > mid else "below" if value < mid else "equal"].append(year)
        if value < g[lo_k][i] or value > g[hi_k][i]:
            out["outside"].append(year)
    return out


def direction(split: dict) -> int:
    return (len(split["above"]) > len(split["below"])) - (len(split["above"]) < len(split["below"]))


def reason_groups(facts: dict, metric: str) -> list[tuple[str, list[int]]]:
    """(kind, years) in order of each kind's first year."""
    groups: dict[str, list[int]] = {}
    for year, reason in sorted(facts["metrics"][metric]["reasons"].items()):
        groups.setdefault(reason["kind"], []).append(year)
    return sorted(groups.items(), key=lambda item: item[1][0])


def reason_text(reason: dict, field: str, g: dict, year: int) -> str:
    """A judged reason's own sentence, with the record's numbers filled in."""
    lo_k, hi_k, form_k = METRIC_KEYS["eps"]
    idx = [i for i in range(len(g["vintages"])) if g["fiscal_years"][i] == year
           and g[lo_k][i] is not None and g[form_k][i] != "floor"]
    values = {}
    if idx:
        values["band"] = band_words(g[lo_k][idx[-1]], g[hi_k][idx[-1]], "eps")
    block = g["actual_by_year"].get(str(year))
    if block:
        values["actual"] = f"${block['eps']:.2f}"
    return fill_story(reason[field], values)


def eps_band_reasons(facts: dict, g: dict) -> str:
    """「FY2016、FY2019 同一年印了…；FY2017 …；FY2020 撤回；…」 for the EPS band note."""
    parts = []
    for kind, years in reason_groups(facts, "eps"):
        reasons = facts["metrics"]["eps"]["reasons"]
        if kind == "two_ranges":
            parts.append("、".join(f"FY{y}" for y in years) + " 同一年印了 GAAP 与调整后两条区间")
        elif kind == "basis":
            parts += [f"FY{y} " + reason_text(reasons[y], "band", g, y) for y in years]
        else:
            word = {"withdrawn": "撤回", "never": "从头到尾没给过", "open": "还没结束"}[kind]
            parts += [f"FY{y} {word}" for y in years]
    return "；".join(parts)


def eps_note_reasons(facts: dict, g: dict) -> str:
    """The notes' grouping of the same reasons: 「…（FY2016、FY2019）；…」."""
    parts = []
    reasons = facts["metrics"]["eps"]["reasons"]
    for kind, years in reason_groups(facts, "eps"):
        listed = "、".join(f"FY{y}" for y in years)
        if kind == "two_ranges":
            parts.append(f"同一年印了 GAAP 与调整后两条区间（{listed}）")
        elif kind == "basis":
            parts.append("指引与实际不在同一口径上（"
                         + "，".join(reason_text(reasons[y], "note", g, y) for y in years) + "）")
        else:
            word = {"withdrawn": "被撤回", "never": "从头到尾没有给过", "open": "本年度尚未结束"}[kind]
            parts.append(f"{word}（{listed}）")
    return "；".join(parts)


def year_list(years: list[int]) -> str:
    """「FY2018、FY2019、FY2022–FY2025」: three or more consecutive years collapse into a span."""
    spans, run = [], []
    for year in sorted(years):
        if run and year != run[-1] + 1:
            spans.append(run)
            run = []
        run.append(year)
    if run:
        spans.append(run)
    return "、".join(f"FY{s[0]}–FY{s[-1]}" if len(s) >= 3 else "、".join(f"FY{y}" for y in s)
                    for s in spans)


SOURCE_8K = (
    "全年指引的每一档 vintage 逐字取自当季业绩 8-K 的 EX-99.1；"
    "全年实际值取自次年 1 月发布中公司自己印的 FY 列，并与 SEC XBRL companyfacts 独立核对过。"
)

TIMING = "该财年<b>进行途中</b>"


def timing_warning(g: dict) -> str:
    """When in the year each vintage went out, read off the filing dates."""
    slots = list(dict.fromkeys(g["vintage_slots"]))
    months = []
    for slot in slots:
        seen = {g["filed"][i][5:7] for i in range(len(g["filed"])) if g["vintage_slots"][i] == slot}
        if len(seen) != 1:
            raise ValueError(f"vintage slot {slot} was filed in more than one month: {sorted(seen)}")
        months.append(int(seen.pop()))
    firsts = [g["filed"][i] for i in range(len(g["filed"])) if g["vintage_slots"][i] == slots[0]]
    # Days into the year when the opening vintage went out, at the latest.
    left = 12 - max(int(date[5:7]) - 1 + int(date[8:10]) / 31 for date in firsts)
    lasts = [g["filed"][i] for i in range(len(g["filed"])) if g["vintage_slots"][i] == slots[-1]]
    gone = min(int(date[5:7]) - 1 + int(date[8:10]) / 31 for date in lasts) / 12
    return (
        "<b>先读这一句，再读色块。</b>这不是一份事前预测的记录。"
        f"每个财年的{cn_count(len(slots))}档指引分别随该年 "
        + "、".join(f"{m} 月" for m in months)
        + f"的业绩发布出去 —— 年初那一档发布时全年还剩{cn_count(math.floor(left))}个多月，"
        f"{months[-1]} 月那一档发布时全年已经过去"
        + ("四分之三" if 0.7 <= gone < 0.85 else f"{gone * 100:.0f}%")
        + "。越靠右的那一档越不是预测。"
    )


def unsettled_warning(g: dict, facts: dict, ledger_ref: str) -> str:
    """The longest blank run, and what caused it, read off the record."""
    run = facts["longest_blank"]
    years = sorted({g["fiscal_years"][i] for i in run})
    causes = []
    for year in years:
        codes = {g["guide_eps_basis"][i] for i in run if g["fiscal_years"][i] == year}
        if "withdrawn" in codes:
            causes.append(f"{year} 年的指引在 {g['withdrawal']['announced']} 由另一份 8-K 撤回")
        elif codes == {"never_issued"}:
            causes.append(f"{year} 年则从头到尾没有给过")
    return (
        "<b>空档不是「公司没发业绩」，是「这一年结不了账」。</b>"
        f"{cn_count(len(facts['years']))}个财年里只有一部分能被诚实地结清，其余各有各的原因，"
        f"整理在 Exhibit {ledger_ref} 那张表里。"
        + (f"最长的一段空白是 {g['filed'][run[0]]} 到 {g['filed'][run[-1]]} 连续 {len(run)} 份业绩发布"
           + (" —— " + "，".join(causes) + "。" if causes else "。")
           if run else ""))


# ── section one: the annual guidance record ──────────────────────────────────
def guidance_charts(staging: dict, facts: dict) -> tuple[list[dict], list[dict]]:
    g = staging["annual_guidance_history"]
    labels = g["vintages"]
    years = g["actual_by_year"]
    eps, rev = facts["metrics"]["eps"], facts["metrics"]["revenue"]
    unsettled = unsettled_warning(g, facts, "{EX_LEDGER}")
    warning = timing_warning(g)
    eps_split = midpoint_split(g, eps, METRIC_KEYS["eps"])
    rev_split = midpoint_split(g, rev, METRIC_KEYS["revenue"])

    # The diamond is the company's OWN whole-percentage-point growth rate, not
    # the two-decimal number the filed dollars divide to. The guidance is
    # written in whole points and never in anything finer, so settling it
    # against a figure with two more digits invents a precision the promise
    # never had. The exact quotients are in the audit table instead.
    floors_skipped = [y for y, i in sorted(eps["settle"].items())
                      if any(g["fiscal_years"][j] == y and g["guide_eps_form"][j] == "floor"
                             for j in range(i + 1, facts["n"]))]
    eps_band = delivery_band(
        "EX_EPS_BAND", "全年摊薄 EPS", labels,
        g["guide_eps_lo_usd"], g["guide_eps_hi_usd"], eps["actual"],
        fmt="usd2", ylab="US$/股", unit="US$", venue="业绩发布",
        timing=TIMING, period_word="年", src_extra=SOURCE_8K,
        extra_note=(
            "<b>每个财年占据连续的几格</b> —— 年初首次、Q1、Q2、Q3 修订 —— "
            "而菱形只落在<b>结算这一年的那一格</b>上，也就是该年最后一次印出"
            + ("区间" if floors_skipped else "数字") + "的那一档"
            + ("（" + "、".join(
                f"FY{y} 最后一档只写了「"
                + next(f"${g['guide_eps_lo_usd'][j]:.2f} 以上" for j in range(facts["n"])
                       if g["fiscal_years"][j] == y and g["guide_eps_form"][j] == "floor")
                + "」，没有上沿，结算用它前一档" for y in floors_skipped) + "）"
               if floors_skipped else "")
            + "。"
            f"能被结清的只有 {len(eps['settle'])} 个财年，"
            f"其余{cn_count(len(eps['reasons']))}年<b>不是没兑现，是没法判定</b>："
            + eps_band_reasons(facts, g) + "。"
            + unsettled + warning),
    )

    below_words = ("一次都没有跌破下限" if not eps["below"]
                   else f"{cn_count(len(eps['below']))}次跌破下限")
    n_eps = cn_count(len(eps["settle"]))
    if not eps_split["below"] and not eps_split["equal"]:
        dev_words = f"{n_eps}年全部在中值之上"
    else:
        dev_words = (f"{n_eps}年里{cn_count(len(eps_split['above']))}年在中值之上、"
                     f"{cn_count(len(eps_split['below']))}年（"
                     + "、".join(f"FY{y}" for y in eps_split["below"]) + "）在中值之下"
                     + ("但仍落在区间内" if not set(eps_split["below"]) & set(eps_split["outside"])
                        else ""))
    eps_dev = midpoint_deviation(
        "EX_EPS_DEV", "全年摊薄 EPS", labels,
        g["guide_eps_lo_usd"], g["guide_eps_hi_usd"], eps["actual"],
        mode="pct", window=len(eps["settle"]), label=fiscal_of, period_word="年",
        src_extra=SOURCE_8K + "偏离为实际值相对该年<b>结算那一档</b>指引中值的自算值。",
        extra_note=(
            "<b>这张图和上一张回答的不是同一个问题。</b>上一张问「有没有掉出区间」，"
            f"答案是{n_eps}年里{below_words}；这一张问「离中值多远」，"
            f"答案是{dev_words}。"
            "把这一条和 Exhibit {EX_REV_DEV} 并排读才是本节的重点：两条指引写在"
            "同一句话、同一份新闻稿、同一个十二个月的视野里，"
            + ("答案却是两个方向。" if direction(eps_split) * direction(rev_split) < 0
               else "答案是同一个方向。")),
    )

    below_note = ""
    if rev["below"]:
        described = []
        for year in rev["below"]:
            i = rev["settle"][year]
            block = years[str(year)]
            lo = g["guide_revenue_growth_lo_pct"][i]
            quote = (f"「up {block['growth_reported_pct']} percent"
                     + (f"（{block['growth_fx_pct']} percent FX-adjusted）」"
                        if block["growth_fx_pct"] not in (None, block["growth_reported_pct"]) else "」"))
            fx = block["growth_fx_pct"]
            fx_words = ""
            if fx is not None and fx != block["growth_reported_pct"]:
                fx_words = ("—— 同一年、同一句话，汇率调整口径"
                            + ("正好踩在下限上" if fx == lo else
                               "落在区间内" if fx > lo else "也在下限之下")
                            + "，报告口径没有。"
                            + ("读哪一个口径决定这一年算不算失手。" if fx >= lo else ""))
            point = lo == g["guide_revenue_growth_hi_pct"][i]
            described.append(
                f"FY{year}</b>：指引{'是单点 ' if point else ' '}"
                f"{band_words(lo, g['guide_revenue_growth_hi_pct'][i], 'revenue')}，"
                f"公司自己报的是{quote}" + (fx_words or "。"))
        if len(described) == 1:
            below_note = "<b>唯一一次真正跌破下限是 " + described[0]
        else:
            below_note = (f"<b>真正跌破下限（或低于单点）的有{cn_count(len(described))}年。</b>"
                          + "".join("<b>" + d for d in described))
    points = [i for i in range(facts["n"]) if g["guide_revenue_form"][i] == "point"]
    quotes = g["point_quotes"]
    missing = [labels[i] for i in points if labels[i] not in quotes]
    if missing:
        raise ValueError(f"point revenue vintages without the company's words: {missing}")
    point_note = ""
    if points:
        point_note = (
            f"另有{cn_count(len(points))}档指引<b>没有宽度</b>："
            + "，".join(f"FY{g['fiscal_years'][i]} 的 {int(g['filed'][i][5:7])} 月那一档是"
                       f"「{quotes[labels[i]]}」" for i in points)
            + ("，都是单点" if len(points) > 1 else "，是单点") + "，画在图上没有高度。")
    rev_band = delivery_band(
        "EX_REV_BAND", "全年收入增速", labels,
        g["guide_revenue_growth_lo_pct"], g["guide_revenue_growth_hi_pct"],
        rev["actual"], fmt="pct0", ylab="同比 %", unit="%", venue="业绩发布",
        timing=TIMING, period_word="年", src_extra=SOURCE_8K,
        extra_note=(
            "<b>色块与菱形都是整数个百分点，因为公司只用这个精度说话。</b>"
            "指引写成「9% 到 10%」，实际值也写成「up 9 percent」——"
            "把申报的美元金额除出两位小数再去判定，是给这份承诺发明一个它从来没有过的精度。"
            "两位小数的商在核对抽屉里。"
            + below_note + point_note + unsettled),
    )

    eps_parts = []
    if not eps_split["below"] and not eps_split["equal"]:
        eps_words = f"{n_eps}年全部高于中值"
    else:
        eps_words = (f"{n_eps}年里只有{cn_count(len(eps_split['below']))}年低于中值"
                     + ("且仍在区间内" if not set(eps_split["below"]) & set(eps_split["outside"]) else ""))
    b, e, a = (len(rev_split[k]) for k in ("below", "equal", "above"))
    if b:
        eps_parts.append(f"{cn_count(b)}年低于中值")
    if e:
        eps_parts.append(f"{cn_count(e)}年正好等于中值")
    if a:
        eps_parts.append(("只有" if a < b else "") + f"{cn_count(a)}年高于中值")
    rev_words = f"{cn_count(len(rev['settle']))}年里" + "、".join(eps_parts)
    if rev["below"]:
        rev_words += (f"，而且其中{cn_count(len(rev['below']))}年（"
                      + "、".join(f"FY{y}" for y in rev["below"]) + "）直接掉出了区间")
    rev_dev = midpoint_deviation(
        "EX_REV_DEV", "全年收入增速", labels,
        g["guide_revenue_growth_lo_pct"], g["guide_revenue_growth_hi_pct"],
        rev["actual"], mode="pp", window=len(rev["settle"]), label=fiscal_of, period_word="年",
        src_extra=SOURCE_8K + "偏离取算术差（百分点），不是比值。",
        extra_note=(
            "<b>与 Exhibit {EX_EPS_DEV} 对照着看。</b>"
            f"EPS 那条{eps_words}；这一条{rev_words}。"
            "收入增速是这两条指引里公司<b>自己控制不了</b>的那一条"
            + ("，也是唯一一条被跌破过的。" if rev["below"] and not eps["below"] else "。")),
    )

    # opening vintage against the one that settles the year: the same question
    # MSCI's page asks, and here it has the opposite answer for the two metrics.
    lo_k, hi_k, _ = METRIC_KEYS["revenue"]
    mid = lambda i: (g[lo_k][i] + g[hi_k][i]) / 2  # noqa: E731
    open_years, open_dev, final_dev, rows = [], [], [], []
    for year in sorted(rev["settle"]):
        idx = [i for i in range(facts["n"]) if g["fiscal_years"][i] == year and g[lo_k][i] is not None]
        first, last = idx[0], rev["settle"][year]
        actual = rev["actual"][last]
        open_years.append(f"FY{str(year)[2:]}")
        open_dev.append(round(actual - mid(first), 4))
        final_dev.append(round(actual - mid(last), 4))
        rows.append((year, idx, first, last, actual))
    revision_words = []
    swing = max(rows, key=lambda r: abs((r[4] - mid(r[2])) - (r[4] - mid(r[3]))))
    year, idx, first, last, actual = swing
    bands = [(g[lo_k][i], g[hi_k][i]) for i in idx]
    changes = [i for i, prev in zip(idx[1:], idx) if (g[lo_k][i], g[hi_k][i]) != (g[lo_k][prev], g[hi_k][prev])]
    if len(set(bands)) == 2 and changes and g["guide_revenue_form"][first] == "range":
        lo, hi = g[lo_k][last], g[hi_k][last]
        dev0 = actual - mid(first)
        landed = ("正好落在上限" if actual == hi else "正好落在下限" if actual == lo
                  else "落在区间内" if lo < actual < hi else "落在区间外")
        revision_words.append(
            f"FY{year} 年初指引 {band_words(g[lo_k][first], g[hi_k][first], 'revenue')}、"
            f"{int(g['filed'][changes[0]][5:7])} 月调到 {band_words(g[lo_k][changes[0]], g[hi_k][changes[0]], 'revenue')}，"
            f"实际 {actual:.0f}% —— 对年初那一档{'高出' if dev0 > 0 else '低了'} {abs(dev0):.0f}pp，"
            f"对修订后那一档{landed}。"
            + (f"修订把一次大幅{'低估' if dev0 > 0 else '高估'}变成一次精准命中，"
               "这是修订的功劳，不是预测的功劳。" if abs(dev0) >= 3 and lo <= actual <= hi else ""))
    both = [r for r in rows if r[4] - mid(r[2]) < 0 and r[4] - mid(r[3]) < 0]
    if both:
        unrevised = [r for r in both
                     if len({(g[lo_k][i], g[hi_k][i]) for i in r[1]}) == 1]
        revised = [r for r in both if r not in unrevised]
        words = "反过来，" + joined([f"FY{r[0]}" for r in both]) + f" {cn_count(len(both))}年<b>对两档都是负的</b>："
        if unrevised:
            words += ((f"这{cn_count(len(both))}年" if not revised else
                       joined([f"FY{r[0]}" for r in unrevised]) + " ")
                      + "全年都没有修订过区间，年初那一档就是结算那一档"
                      + ("。" if not revised else "；"))
        if revised:
            words += ((joined([f"FY{r[0]}" for r in revised]) + " " if unrevised else "")
                      + "修订也没能把它救回来。")
        revision_words.append(words)
    late = [r for r in rows if g["vintage_slots"][r[2]] != g["vintage_slots"][0]]
    for year, idx, first, last, actual in late:
        revision_words.append(
            f"FY{year} 年初那一档没有收入指引，这一年左边那根柱子对的是 "
            f"{int(g['filed'][first][5:7])} 月那一档"
            + (f"（只有下限 {g[lo_k][first]:.0f}%）" if g["guide_revenue_form"][first] == "floor" else "")
            + "。")
    revision = {
        "ref": "EX_REVISION",
        "kind": "grouped_bars",
        "title": (f"收入增速：对年初那一档与对结算那一档的偏离，"
                  f"{cn_count(len(rev['settle']))}个已完结财年"),
        "xlabels": open_years,
        "groups": [
            {"name": "对年初第一档指引", "color": "GOLD", "values": open_dev},
            {"name": "对结算那一档指引", "color": "NAVY", "values": final_dev},
        ],
        "bar_labels": True,
        "fmt": "pp1", "label_fmt": "pp1", "ylab": "pp vs 指引中值",
        "note": "两根柱子之间的距离就是<b>这一年被修订了多少</b>。" + "".join(revision_words),
        "src_extra": SOURCE_8K,
    }

    ledger = {
        "title": f"{cn_count(len(facts['years']))}个财年逐年：指引、实际值，以及不能结清的年份为什么不能",
        "headers": ["财年", "收入增速指引（结算那一档）", "公司自报增速", "收入判定",
                    "EPS 指引（结算那一档）", "GAAP 摊薄 EPS", "EPS 判定"],
        "rows": [],
    }
    for year in facts["years"]:
        block = years.get(str(year))

        def band_text(metric: str) -> str:
            m = facts["metrics"][metric]
            if year in m["settle"]:
                i = m["settle"][year]
                lo_key, hi_key, _ = METRIC_KEYS[metric]
                lo, hi = g[lo_key][i], g[hi_key][i]
                if metric == "eps":
                    return band_words(lo, hi, "eps")
                return (f"{lo:.0f}" if lo == hi else f"{lo:.0f}–{hi:.0f}") + "%"
            return reason_text(m["reasons"][year], "ledger", g, year)

        ledger["rows"].append([
            f"FY{year}",
            band_text("revenue"),
            f"{block['growth_reported_pct']}%" if block and block["growth_reported_pct"] is not None else "—",
            VERDICT_ZH[rev["verdicts"][year]] if year in rev["verdicts"] else "无法判定",
            band_text("eps"),
            f"${block['eps']:.2f}" if block else "—",
            VERDICT_ZH[eps["verdicts"][year]] if year in eps["verdicts"] else "无法判定",
        ])

    vintage_table = {
        "title": (f"全年指引的全部 {len(labels)} 档 vintage"
                  f"（FY{facts['years'][0]}–FY{facts['years'][-1]}）"),
        "headers": ["vintage", "财年", "发布日", "收入增速指引", "形式",
                    "EPS 指引", "EPS 口径限定"],
        "rows": [],
    }
    for i, label in enumerate(labels):
        lo, hi = g["guide_revenue_growth_lo_pct"][i], g["guide_revenue_growth_hi_pct"][i]
        elo, ehi = g["guide_eps_lo_usd"][i], g["guide_eps_hi_usd"][i]
        vintage_table["rows"].append([
            label, f"FY{g['fiscal_years'][i]}", g["filed"][i],
            "—" if lo is None else (f"{lo:.0f}%" if lo == hi else f"{lo:.0f}%–{hi:.0f}%"),
            FORM_ZH[g["guide_revenue_form"][i]],
            "—" if elo is None else (f"${elo:.2f} 以上" if g["guide_eps_form"][i] == "floor"
                                     else f"${elo:.2f}–${ehi:.2f}"),
            BASIS_ZH.get(g["guide_eps_basis"][i], "—"),
        ])

    return [eps_band, eps_dev, rev_band, rev_dev, revision], [ledger, vintage_table]


# There is no recast window any more, and there did not need to be one.
#
# American Express adopted ASC 606 on 2018-01-01 and recast 2017 by quarter in
# its own statistical tables. This file used to cut every income-statement
# series to start at 2017Q1 on the reasoning that 2016 was never republished on
# the new basis -- "each release prints only five quarters side by side, so the
# last one carrying Q4 2016 predates the change." That is a true statement about
# the *earnings releases* and a false statement about the company. On 2018-03-09
# AmEx furnished a separate Item 7.01 Form 8-K whose Exhibit 99.1, "Eight
# Quarter Trend Q1 2016 through Q4 2017", prints As Reported, Adjustments and As
# Recast side by side for all eight quarters. `series/axp.json` now carries the
# 2016 quarters from that document, so the whole income statement is one basis
# for all 42 quarters and nothing needs cutting.
#
# The inference that failed is worth naming, because it looks like evidence: a
# pattern in one document series ("releases print five quarters") was treated as
# an exhaustive search over everything the company files.


# ── the readings a threshold is settled against ──────────────────────────────
def vce_ratio(staging: dict) -> list[float | None]:
    fin = staging["financials"]
    return [None if bd is None else (rw + sv + bd) / rev * 100
            for rw, sv, bd, rev in zip(fin["rewards_usd_m"], fin["card_member_services_usd_m"],
                                       fin["business_development_usd_m"], fin["revenue_usd_m"])]


def jaws_series(staging: dict) -> list[float | None]:
    fin = staging["financials"]
    rev, exp = fin["revenue_usd_m"], fin["total_expenses_usd_m"]
    return [None] * 4 + [pct_change(rev[i], rev[i - 4]) - pct_change(exp[i], exp[i - 4])
                         for i in range(4, len(rev))]


def kpi_reading(staging: dict, reads: str) -> float:
    """The quarter's value of one tracked metric, read from the series.

    A current value typed into the threshold block is a second copy of a number
    the arrays already hold, free to disagree with it -- and rounding it before
    it is compared moves the last printed digit.
    """
    if reads == "vce_ratio":
        return vce_ratio(staging)[-1]
    if reads == "jaws":
        return jaws_series(staging)[-1]
    if reads.startswith("yoy:"):
        block, key = reads[4:].split(".")
        values = staging[block][key]
        return pct_change(values[-1], values[-5])
    block, key = reads.split(".")
    return staging[block][key][-1]


def kpi_entries(block: dict, value_key: str, staging: dict) -> list[dict]:
    """The block's thresholds with their value filled in: read, or as the filer printed it."""
    out = []
    for entry in block["quantified"]:
        if "reads" in entry:
            out.append({**entry, value_key: kpi_reading(staging, entry["reads"])})
        elif value_key in entry:
            out.append(dict(entry))
        else:
            raise ValueError(f"threshold {entry['metric']!r} has neither `reads` nor a printed {value_key}")
    return out


CREDIT_READS = ("credit_metrics.past_due_30_pct", "credit_metrics.net_write_off_rate_principal_pct")


# ── section two: what moved this quarter ────────────────────────────────────
def quarter_charts(staging: dict, next_entries: list[dict]) -> list[dict]:
    fin = staging["financials"]
    labels = staging["period_labels"]
    periods = staging["periods"]
    revenue = fin["revenue_usd_m"]
    expenses = fin["total_expenses_usd_m"]
    provisions = fin["provisions_usd_m"]
    pretax = fin["pretax_income_usd_m"]
    ppop = fin["ppop_usd_m"]

    # Guiding nothing and reporting both legs still implies an identity: the
    # year-over-year change in pretax income is the change in pre-provision
    # profit plus the change in the provision line, and `ppop - provisions =
    # pretax` closes in every quarter, so the split carries no estimate.
    start = 4
    dev_labels = labels[start:]
    ppop_leg = [ppop[i] - ppop[i - 4] for i in range(start, len(revenue))]
    prov_leg = [-(provisions[i] - provisions[i - 4]) for i in range(start, len(revenue))]
    latest_total = pretax[-1] - pretax[-5]
    closes = all(abs(ppop[i] - provisions[i] - pretax[i]) < 1e-6
                 and abs(revenue[i] - expenses[i] - ppop[i]) < 1e-6 for i in range(len(revenue)))
    credit_lines = sum(1 for entry in next_entries if entry.get("reads") in CREDIT_READS)
    share = prov_leg[-1] / latest_total * 100 if latest_total > 0 else None
    decomposition = {
        "ref": "EX_PTI",
        "kind": "grouped_bars",
        "title": (f"税前利润同比增量拆成两条腿：本季 {money(latest_total)} 里，"
                  f"拨备行贡献 {money(prov_leg[-1])}"),
        "xlabels": dev_labels,
        "xrot": 90,
        "xstep": LONG_STEP,
        "groups": [
            {"name": "经营腿（拨备前利润的同比变化）", "color": "NAVY", "values": rounded(ppop_leg)},
            {"name": "拨备腿（拨备下降为正）", "color": "GOLD", "values": rounded(prov_leg)},
        ],
        "bar_labels": False,
        "fmt": "f0c", "label_fmt": "f0c", "ylab": "US$M（同比增量）",
        "note": (
            "<b>这是一个恒等式，不是估计。</b>拨备前利润 = 收入 − 总费用，"
            "而拨备前利润 − 拨备 = 税前利润 —— 三条都是申报值，"
            + (f"这个等式在全部 {len(labels)} 个季度里逐季精确成立，所以两条腿相加正好等于税前利润的同比增量。"
               if closes else "")
            + f"本季两条腿是 {money(ppop_leg[-1])} 与 {money(prov_leg[-1])}"
            + (f"，拨备腿占 {share:.0f}%。" if share is not None and 0 < share <= 100 else "。")
            + "<b>拨备腿为正的意思是当季拨备比去年同期少</b>，它可以是信用真的变好，"
            "也可以是准备金释放 —— 图上分不出来"
            + (f"，第三节的{cn_count(credit_lines)}条信用阈值才分得出来。" if credit_lines else "。")
            + "2021 年那几根特别高的拨备腿是疫情期计提的准备金在回冲，"
            "它们同时也说明这条腿有物理边界：放完了就没有了。"),
        "src_extra": "各季业绩 8-K EX-99.2 的合并损益表；两条腿均为本页自算（D），加总等于申报的税前增量。",
    }

    ratio = vce_ratio(staging)
    vce_idx = [i for i, v in enumerate(ratio) if v is not None]
    vce_labels = [labels[i] for i in vce_idx]
    vce_values = [ratio[i] for i in vce_idx]
    jaws = jaws_series(staging)
    vce_now = fin["rewards_usd_m"][-1] + fin["card_member_services_usd_m"][-1] + fin["business_development_usd_m"][-1]
    vce_then = fin["rewards_usd_m"][-5] + fin["card_member_services_usd_m"][-5] + fin["business_development_usd_m"][-5]
    rev_growth = pct_change(revenue[-1], revenue[-5])
    vce_growth = pct_change(vce_now, vce_then)
    rest_growth = pct_change(expenses[-1] - vce_now, expenses[-5] - vce_then)
    top = sorted(vce_values, reverse=True)[:3]
    tail_words = ""
    if len(vce_values) >= 4:
        a, b = vce_values[-4], vce_values[-1]
        tail_words = f"最近三季从 {a:.1f}% {'抬到' if b > a else '回落到'} {b:.1f}%"
        if sorted(vce_values[-3:], reverse=True) == top:
            tail_words += "，这三季是这条线上最高的三格"
        tail_words += "；"
    if jaws[-1] < 0 and vce_growth > rev_growth > rest_growth:
        source_words = "这条线是本季负 jaws 的来源"
    elif jaws[-1] < 0:
        source_words = "本季负 jaws 不只来自这条线"
    else:
        source_words = "本季 jaws 为正"
    watched = any(entry.get("reads") == "vce_ratio" for entry in next_entries)
    vce_chart = {
        "ref": "EX_VCE",
        "kind": "lines",
        "title": (f"VCE 占收入比（公司自己的定义）：本季 {vce_values[-1]:.1f}%，"
                  f"{len(vce_values)} 季区间 {min(vce_values):.1f}–{max(vce_values):.1f}%"),
        "xlabels": vce_labels,
        "series": [{"name": "VCE ÷ 收入", "values": rounded(vce_values), "color": "NAVY"}],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
        "ylab": "%",
        "note": (
            "VCE（variable customer engagement）是公司在业绩表附录里自己定义的口径："
            "Card Member rewards + business development + Card Member services 三条费用相加。"
            f"<b>这条线只有 {len(vce_values)} 个季度，不是选出来的窗口，是这个数存在的全部长度</b> —— "
            "business development 在 2022 年 4 月那份发布里才第一次从 Marketing 里拆出来，"
            "公司只把 2021 年四个季度按新口径重述了一遍，再往前没有。"
            + tail_words + source_words
            + ("，也是第三节里那条阈值盯的东西。" if watched else "。")),
        "src_extra": "各季业绩 8-K EX-99.2 的合并损益表三条费用行相加，除以同季收入；比值为本页自算（D）。",
    }

    values = jaws[start:]
    runs, run = [], []
    for i, value in enumerate(values):
        if value > 0:
            run.append(i)
        elif run:
            runs.append(run)
            run = []
    if run:
        runs.append(run)
    longest = max((len(r) for r in runs), default=0)
    best = [r for r in runs if len(r) == longest]
    streak = 1
    while streak < len(values) and (values[-1 - streak] > 0) == (values[-1] > 0):
        streak += 1
    sign = "正" if values[-1] > 0 else "负"
    if streak == 1:
        now_words = f"本季转{sign}（{values[-1]:+.1f}pp），上一季是 {values[-2]:+.1f}pp。"
    else:
        now_words = f"已连续 {streak} 季为{sign}，本季 {values[-1]:+.1f}pp。"
    run_words = (
        f"连续为正最长的一段是 {longest} 个季度"
        + (f"，出现过{cn_count(len(best))}次：" if len(best) > 1 else "：")
        + "与 ".join(f"{periods[start + r[0]]}–{periods[start + r[-1]]}"
                     f"（最高 {max(values[i] for i in r):+.1f}pp）" for r in best)
        + "；") if best else "这条线从来没有为正过；"
    # Which expense lines outgrew revenue in each of the last four quarters: the
    # page says VCE is the only one, so it has to be the only one in the data.
    lines = {"VCE": [None if fin["business_development_usd_m"][i] is None else
                     fin["rewards_usd_m"][i] + fin["card_member_services_usd_m"][i]
                     + fin["business_development_usd_m"][i] for i in range(len(revenue))]}
    marketing = [fin["marketing_usd_m"][i] if fin["marketing_usd_m"][i] is not None
                 else fin["marketing_and_business_development_usd_m"][i] for i in range(len(revenue))]
    lines["市场营销"] = marketing
    for key, name in (("salaries_usd_m", "薪酬"), ("professional_services_usd_m", "专业服务"),
                      ("other_net_usd_m", "其他")):
        lines[name] = fin[key]
    # Data processing and equipment is the one expense line the file does not
    # carry; it is what total expenses leave after every line it does.
    lines["数据处理与设备"] = [
        None if lines["VCE"][i] is None else
        expenses[i] - lines["VCE"][i] - marketing[i] - fin["salaries_usd_m"][i]
        - fin["professional_services_usd_m"][i] - fin["other_net_usd_m"][i]
        for i in range(len(revenue))]
    faster = [name for name, series in lines.items()
              if all(series[i] is not None and series[i - 4] is not None
                     and pct_change(series[i], series[i - 4]) > pct_change(revenue[i], revenue[i - 4])
                     for i in range(len(revenue) - 4, len(revenue)))]
    jaws_chart = {
        "ref": "EX_JAWS",
        "kind": "diverging_bars",
        "title": f"jaws（收入增速 − 费用增速）：本季 {values[-1]:+.1f}pp",
        "xlabels": dev_labels,
        "xrot": 90,
        "xstep": LONG_STEP,
        "values": rounded(values),
        "legend": "收入增速 − 总费用增速",
        "positive_label": "收入跑赢费用",
        "negative_label": "费用跑赢收入",
        "fmt": "pp1", "yfmt": "pp1", "label_fmt": "pp1",
        "ylab": "pp", "zero_line": True,
        "note": (
            "正值表示收入的同比增速快于总费用的同比增速。"
            + run_words + now_words
            + ("<b>它和 Exhibit {EX_VCE} 是同一件事的两个看法</b>：费用里唯一持续超速的部分是 VCE，"
               "而 VCE 是随消费与权益使用量走的可变成本，不是一次性投入。"
               if faster == ["VCE"] else "")),
        "src_extra": "收入与总费用均为申报值，两个增速之差为本页自算（D）。",
    }
    return [decomposition, vce_chart, jaws_chart]


# ── section four: the long structural series ─────────────────────────────────
def structure_charts(staging: dict) -> list[dict]:
    """The four revenue legs over the record and the four segments' margins.

    Neither carries a finding about the quarter: one is a 42-quarter structure,
    the other a 26-quarter margin record. They sit with the routine series.
    """
    fin = staging["financials"]
    labels = staging["period_labels"]
    revenue = fin["revenue_usd_m"]
    discount = fin["discount_revenue_usd_m"]
    card_fees = fin["net_card_fees_usd_m"]
    other = fin["other_non_interest_revenue_usd_m"]
    nii = fin["net_interest_income_usd_m"]
    legs = {"商户折扣收入": discount, "净卡费": card_fees, "其他非利息收入": other, "净利息收入": nii}
    total_multiple = revenue[-1] / revenue[0]
    faster_legs = [name for name, leg in legs.items() if leg[-1] / leg[0] > total_multiple]
    legs_close = all(abs(discount[i] + card_fees[i] + other[i] + nii[i] - revenue[i]) < 1e-6
                     for i in range(len(revenue)))
    break_at = staging["periods"].index("2021Q1")
    mix = {
        "ref": "EX_MIX",
        "kind": "grouped_bars",
        "title": (f"四条收入腿：净卡费占收入 "
                  f"{card_fees[-1] / revenue[-1] * 100:.1f}%，"
                  f"{len(labels) - 1} 季前是 {card_fees[0] / revenue[0] * 100:.1f}%"),
        "xlabels": labels,
        "xrot": 90,
        "xstep": LONG_STEP,
        "groups": [
            {"name": "商户折扣收入", "color": "NAVY", "values": rounded(discount)},
            {"name": "净卡费", "color": "GOLD", "values": rounded(card_fees)},
            {"name": "其他非利息收入", "color": "BLUE", "values": rounded(other)},
            {"name": "净利息收入", "color": "RED", "values": rounded(nii)},
        ],
        "bar_labels": False,
        "fmt": "f0c", "label_fmt": "f0c", "ylab": "US$M",
        "break_at": break_at,
        "break_label": "processed revenue 移出折扣收入",
        "note": (
            (f"四条腿相加正好等于「收入（扣除利息支出后）」，全部 {len(labels)} 个季度逐季精确成立。"
             if legs_close else "")
            + f"{len(labels)} 个季度里折扣收入长到 {discount[-1] / discount[0]:.2f} 倍、"
            f"净卡费长到 {card_fees[-1] / card_fees[0]:.2f} 倍、"
            + ("" if "净利息收入" not in faster_legs else f"净利息收入长到 {nii[-1] / nii[0]:.2f} 倍、")
            + f"总收入长到 {total_multiple:.2f} 倍 —— "
            + ("<b>卡费是唯一一条跑赢总收入的腿，商户那条跑输</b>。" if faster_legs == ["净卡费"] else
               "<b>跑赢总收入的是" + "与".join(faster_legs) + "，商户那条跑输</b>。"
               if "商户折扣收入" not in faster_legs else "")
            + "断点标记处（2021 年第一季度）公司把 processed revenue 从折扣收入里挪进了"
            "「其他非利息收入」，并只重述了 2021 年四个季度。"
            "<b>合计不受影响，所以任何总额层面的核对都发现不了这次挪动</b>，"
            "断点因此必须画在图上而不是靠等式发现。"
            "「其他非利息收入」这条腿是用合计减去前两条得到的，"
            "而不是取那一行印出来的数 —— 那一行本身在窗口内被改过两次名、并过一次。"),
        "src_extra": "各季业绩 8-K EX-99.2 合并损益表；「其他非利息收入」为非利息收入合计减折扣收入与净卡费（D）。",
    }

    seg = staging["segments_usd_m"]
    seg_labels = staging["segment_period_labels"]
    seg_periods = staging["segment_periods"]
    margins = {tag: [None if p is None or r in (None, 0) else p / r * 100
                     for p, r in zip(block["pretax_usd_m"], block["revenue_usd_m"])]
               for tag, block in seg.items()}
    gmns = margins["GMNS"]
    others = [margins[tag][-1] for tag in ("USCS", "CS", "ICS")]
    recast = seg_periods.index("2022Q3")
    ics = margins["ICS"]
    spike = ("2026Q1" in seg_periods and 0 < seg_periods.index("2026Q1") < len(ics) - 1
             and ics[seg_periods.index("2026Q1")] - max(ics[seg_periods.index("2026Q1") - 1],
                                                        ics[seg_periods.index("2026Q1") + 1]) > 5)
    seg_chart = {
        "ref": "EX_SEG",
        "kind": "lines",
        "title": (f"四个分部的税前利润率：GMNS 本季 {gmns[-1]:.1f}%、{len(gmns)} 季里 "
                  f"{sum(1 for v in gmns if v > 50)} 季在 50% 以上，"
                  f"其余三个本季 {min(others):.1f}–{max(others):.1f}%"),
        "xlabels": seg_labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": block["name_zh"], "color": color, "values": rounded(margins[tag])}
            for (tag, block), color in zip(
                [(t, seg[t]) for t in ("USCS", "CS", "ICS", "GMNS")],
                ["NAVY", "BLUE", "GOLD", "RED"])
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
        "ylab": "分部税前利润率 %",
        "note": (
            f"<b>这张图只有 {len(seg_labels)} 个季度，而且不能往前接。</b>现在这四个分部是 2022 年 10 月那份"
            f"业绩发布第一次启用的，同一份发布用一张附表把 2020 年第一季度以后的{cn_count(recast)}个季度"
            "按新口径重算了一遍，本图的窗口就是那张附表能覆盖到的长度。"
            "再往前是 Global Consumer Services Group 那一套三分部结构，"
            "公司没有为它提供过按新口径的重算，两套结构的同名分部不是同一个东西。"
            + ("ICS 在 2026 年第一季度那个尖峰不是国际业务变好："
               "当季 10-Q 写的是该分部记了 Swisscard 原持股的重估收益，以及一笔国际非所得税"
               "准备金的释放（a release of a reserve associated with international non-income tax），"
               "两者都没有单独披露金额，所以本页不做还原，只在这里说明它是什么。" if spike else "")),
        "src_extra": "各季业绩 8-K EX-99.2 的四张分部页；利润率 = 分部税前利润 ÷ 分部收入（D）。",
    }
    return [mix, seg_chart]


# ── section three: the thresholds pointed forward ────────────────────────────
def credit_values(staging: dict) -> dict:
    """The numbers the credit notes in the series file name, read off the arrays."""
    credit = staging["credit_metrics"]
    loans = credit["loans_basis"]
    periods = staging["periods"]
    overlap = credit["basis_overlap_quarters"]
    first_dpd = next(i for i, v in enumerate(credit["past_due_30_pct"]) if v is not None)
    covered = [i for i, v in enumerate(loans["past_due_30_pct"]) if v is not None]
    reads = loans["readings_per_quarter"]
    five = [i for i in covered if reads[i] == 5]
    early = [i for i in covered if i < five[0]]
    late = [i for i in covered if i > five[-1]]
    if any(reads[i] != reads[early[0]] for i in early) if early else False:
        raise ValueError("the early loans-basis quarters no longer share one reading count")
    return {
        "overlap": f"{overlap[0]}–{overlap[-1]}",
        "overlap_n": cn_count(len(overlap)),
        "gap_first": periods[0],
        "gap_last": periods[first_dpd - 1],
        "covered_first": periods[covered[0]],
        "covered_last": periods[covered[-1]],
        "covered_n": str(len(covered)),
        "five_first": periods[five[0]],
        "five_last": periods[five[-1]],
        "five_n": str(len(five)),
        "early_n": cn_count(len(early)),
        "early_reads": str(reads[early[0]]) if early else "",
        "late_min": str(min(reads[i] for i in late)) if late else "",
    }


def next_quarter_charts(staging: dict, entries: list[dict], block: dict | None) -> list[dict]:
    if not entries:
        return []
    fin = staging["financials"]
    credit = staging["credit_metrics"]
    loans = credit["loans_basis"]
    labels = staging["period_labels"]
    values = credit_values(staging)
    excluded = [fill_story(item, block_values(staging, block)) for item in block.get("excluded", [])]

    exhibits = [headroom_exhibit(
        f"下季 {len(entries)} 条阈值：当前值离阈值的余量",
        entries, "current",
        ("正值表示仍在安全侧。阈值为本地研究设定，<b>不是公司指引</b> —— "
         "公司的指引是全年的、只覆盖收入增速与 EPS 两个数，见第一节。"
         + (f"另有{cn_count(len(excluded))}条本页<b>不接入</b>。" + "".join(excluded) if excluded else "")),
        f"当前值为 {staging['periods'][-1]} 的申报值或由申报值直接相除；阈值为本地研究设定。")]
    exhibits[0]["ref"] = "EX_NEXT_HEADROOM"

    long_billed = staging["operating_metrics"]["billed_business_usd_bn"]
    billed_yoy_idx = [i for i in range(4, len(long_billed))
                      if long_billed[i] is not None and long_billed[i - 4] is not None]
    ratio = vce_ratio(staging)
    vce_idx = [i for i, v in enumerate(ratio) if v is not None]
    jaws = jaws_series(staging)
    credit_note = " ".join(fill_story(text, values) for text in (
        credit["basis_note"], credit["gap_note"], loans["note"], loans["covid_note"]))
    series_for = {
        # Billed business reaches 2016Q3 and no further, and that IS a disclosure
        # limit rather than a code path: the proprietary (ex-GNS) total was first
        # printed as its own consolidated dollar line in the Q3 2017 release,
        # whose trailing window reaches back five quarters to 2016Q3.
        "financials.net_card_fees_usd_m": (
            labels, fin["net_card_fees_usd_m"], "f0c", "US$M",
            "净卡费是 ASC 606 重述<b>没有动过</b>的几条之一 —— "
            "2018 年 4 月那份重述表把 2017Q1 的商户折扣收入从 4,519 改成 "
            "5,387，却把净卡费原样重印。这条线从 2016Q1 起，与本页其余损益表各行一样："
            "那些被重述动过的行，2016 四季取自 2018-03-09 那份 8-K 的 As Recast 栏。"),
        "yoy:operating_metrics.billed_business_usd_bn": (
            [labels[i] for i in billed_yoy_idx],
            [pct_change(long_billed[i], long_billed[i - 4]) for i in billed_yoy_idx],
            "pct1", "%",
            "由两个印出来的美元金额相除得到，因此可以被结清；"
            "本季那份分析的阈值原本写在公司只披露到整数的汇率调整口径上，见 Exhibit {EX_NEXT_HEADROOM} 的说明。"
            f"消费额本身是 ASC 606 重述没有动过的几条之一，但它只回到 "
            f"{labels[next(i for i, v in enumerate(long_billed) if v is not None)]}，"
            f"所以这条同比线自 {labels[billed_yoy_idx[0]]} 起 —— 同比要往回够四个季度。"
            "<b>再往前不是被截掉的，是公司没按这个口径印过</b>："
            "本页这条是<b>自营</b>（剔除 GNS）消费额，而 AmEx 直到 2017 年第三季那份发布"
            "才第一次把它作为一条合并口径的美元行印出来，那份发布的对照窗口只回溯五个季度、"
            "到 2016Q3 为止。更早的两季只能用「合并总额减去分部表里的 GNS」减出来，"
            "而公司自己从没做过这个减法。"),
        # Two bases, two lines, never joined -- see `gap_note` and `overlap_note`.
        "credit_metrics.past_due_30_pct": (
            labels, credit["past_due_30_pct"], "pct1", "%",
            credit_note + " " + fill_story(loans["overlap_note"], values)),
        "credit_metrics.net_write_off_rate_principal_pct": (
            labels, credit["net_write_off_rate_principal_pct"], "pct1", "%",
            " ".join(fill_story(text, values) for text in (
                credit["basis_note"], credit["gap_note"], loans["note"], loans["overlap_note"]))),
        "vce_ratio": ([labels[i] for i in vce_idx], [ratio[i] for i in vce_idx], "pct1", "%",
                      f"序列只有 {len(vce_idx)} 季，因为 business development 到 2022 年才从 Marketing 里拆出来。"),
        "jaws": (labels[4:], jaws[4:], "pp1", "pp", None),
        "operating_metrics.cet1_ratio_pct": (
            labels, staging["operating_metrics"]["cet1_ratio_pct"], "pct1", "%",
            "公司按季披露的巴塞尔 III 普通股一级资本比率，非自算，"
            "资本比率与收入确认口径无关，所以它同样回到 2016Q1。"
            "<b>但 2016 那四格的两条取数路径没有重叠</b>："
            "前三季来自业绩发布的统计表，第四季来自 FY2016 10-K，没有一格被第二份文件核对过。"),
    }
    # The two credit charts carry a second, older basis as its own grey line.
    # It is *not* a backfill of the tracked series: the company only began
    # publishing the combined loans-and-receivables basis with the 2023Q1
    # release, and over the sixteen quarters both are printed they agree in
    # exactly one.  Drawing them as two lines is the same refusal EX_RATE makes
    # for the printed and the derived discount rate.
    loans_line_for = {
        "credit_metrics.past_due_30_pct": loans["past_due_30_pct"],
        "credit_metrics.net_write_off_rate_principal_pct": loans["net_write_off_rate_principal_pct"],
    }
    annual = credit["annual_past_due_30_pct"]["values"]
    periods = staging["periods"]
    first_dpd = periods[next(i for i, v in enumerate(credit["past_due_30_pct"]) if v is not None)]
    reached_back = (first_dpd < credit["combined_basis_first_quarter"]
                    and first_dpd.endswith("Q4") and first_dpd[:4] in annual)
    for entry in entries:
        reads = entry.get("reads")
        if reads not in series_for:
            continue
        xlab, series, fmt, unit, extra = series_for[reads]
        if reads == "jaws":
            extra = ("阈值为负数：本地设定的是「收敛到 "
                     + minus_sign(f"{entry['threshold']:.0f}") + "pp 以内」，不是「转正」。"
                     if entry["threshold"] < 0 else "")
        if unit == "US$M":
            shown = f"当前 US${entry['current']:,.0f}M，阈值 US${entry['threshold']:,.0f}M"
        else:
            shown = f"当前 {entry['current']:,.2f}{unit}，阈值 {entry['threshold']:,.2f}{unit}"
        exhibit = threshold_exhibit(
            f"{entry['metric']}：{shown}",
            xlab, rounded(series), entry["threshold"],
            fmt=fmt, ylab=unit,
            actual_name=entry["metric"], threshold_name="本地阈值",
            note=("红线是本地研究设定的阈值，既不是公司指引，也不是公司披露的目标。"
                  "深蓝那条序列从这个数在申报文件里存在的那一季开始画，不向前回补。" + extra),
            src_extra="各季业绩 8-K EX-99.2；阈值为本地研究设定。")
        if reads in loans_line_for:
            exhibit["series"].append({
                "name": loans["label"] + "，对照",
                "values": rounded(loans_line_for[reads]),
                "color": "GRAY",
            })
            exhibit["src_extra"] = (
                "两条线都读自各季业绩 8-K 的 EX-99.2："
                "深蓝取合并口径那一段，灰线取 Worldwide Card Member loans 那一段。"
                + (f"{first_dpd} 那一格深蓝取自 FY2023 的 10-K 三年对照表（同一口径的年末时点值）。"
                   if reads == "credit_metrics.past_due_30_pct" and reached_back else "")
                + "阈值为本地研究设定。")
        exhibit["xstep"] = LONG_STEP
        exhibits.append(exhibit)
    return exhibits


def block_values(staging: dict, block: dict | None) -> dict:
    """Numbers a stamped block's sentences name, filled from the block and the series."""
    period = staging["period_labels"][-1]
    values = {"quarter": quarter_words(period)}
    if block:
        for entry in block.get("quantified", []):
            alias = READ_ALIASES.get(entry.get("reads"))
            if alias:
                values[f"{alias}_threshold"] = f"{entry['threshold']:g}"
        for key, value in block.get("figures", {}).items():
            values[key] = f"{value:g}"
    return values


# Names a stamped block's sentence may use for a threshold it quotes.
READ_ALIASES = {"yoy:operating_metrics.billed_business_usd_bn": "billed"}


# ── section four: the long routine series ────────────────────────────────────
def share_words(share: float) -> str:
    """How the share chart says one revenue share in words, when it can."""
    if share >= 60:
        return "六成以上"
    if 50 < share < 55:
        return "略高于一半"
    near = min(range(2, 11), key=lambda d: abs(share / 100 - 1 / d))
    if abs(share / 100 * near - 1) < 0.05:
        return f"接近{cn_fraction(1 / near)}"
    return f"约 {share:.0f}%"


def routine_charts(staging: dict) -> list[dict]:
    fin = staging["financials"]
    labels = staging["period_labels"]
    periods = staging["periods"]
    revenue = fin["revenue_usd_m"]
    card_fees = fin["net_card_fees_usd_m"]
    discount = fin["discount_revenue_usd_m"]

    # All three of these -- net card fees, average fee per card, proprietary
    # cards in force -- run the whole record. Cards in force is the exception:
    # the consolidated proprietary/GNS split was not printed before the Q3 2017
    # supplement, so its first two points are holes, and every multiple the
    # note multiplies together is taken over the span where all three exist.
    fee_per_card = staging["operating_metrics"]["average_fee_per_card_usd"]
    cards = staging["operating_metrics"]["proprietary_cards_in_force_m"]
    cards_from = next(i for i, v in enumerate(cards) if v is not None)
    fee_m = card_fees[-1] / card_fees[cards_from]
    fpc_m = fee_per_card[-1] / fee_per_card[cards_from]
    cards_m = cards[-1] / cards[cards_from]
    product = fpc_m * cards_m
    recent = fee_per_card[-8:]
    price_chart = {
        "ref": "EX_PRICE",
        "kind": "bar_line_dual",
        "title": (f"净卡费与每卡年费：卡费 US${card_fees[-1]:,.0f}M，"
                  f"每卡年费 US${fee_per_card[-1]:.0f}"),
        "xlabels": labels,
        "xrot": 90,
        "xstep": LONG_STEP,
        "bar": {"name": "净卡费（季度额）", "values": rounded(card_fees), "color": "NAVY"},
        "line": {"name": "每卡年费（年化，US$）", "values": rounded(fee_per_card),
                 "color": "RED", "yfmt": "f0"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c", "ylab": "US$M",
        "ylab2": "US$/卡·年",
        "note": (
            "<b>这是本页最需要长窗口才看得见的一张。</b>"
            f"{len(labels)} 个季度里净卡费从 US${card_fees[0]:,.0f}M 长到 "
            f"US${card_fees[-1]:,.0f}M"
            f"（{card_fees[-1] / card_fees[0]:.2f} 倍），"
            f"每卡年费从 US${fee_per_card[0]:.0f} 涨到 US${fee_per_card[-1]:.0f}"
            f"（{fee_per_card[-1] / fee_per_card[0]:.2f} 倍），"
            f"而自营卡量只从 {cards[cards_from]:.1f}M"
            f"（{labels[cards_from]}）长到 {cards[-1]:.1f}M"
            f"（{cards_m:.2f} 倍）。"
            + (f"同从 {labels[cards_from]} 算起，每卡年费涨到 {fpc_m:.2f} 倍、卡量 {cards_m:.2f} 倍，"
               f"两者相乘 {product:.2f}，约等于同期卡费的 {fee_m:.2f} 倍"
               + (" —— <b>卡费的增长里，涨价那一半比发卡那一半更大</b>。" if fpc_m > cards_m else "。")
               if abs(product / fee_m - 1) < 0.05 else "")
            + "每卡年费是公司自己印出来的数，不是本页除出来的；"
            "它的定义（自营净卡费年化 ÷ 平均自营总卡量）写在业绩表附录里。"
            + ("八个季度看这条线只是一条缓慢上行的直线，"
               f"看不出它已经涨到原来的 {fee_per_card[-1] / fee_per_card[0]:.2f} 倍。"
               if all(b >= a for a, b in zip(recent, recent[1:])) else "")),
        "src_extra": "各季业绩 8-K EX-99.2：净卡费取合并损益表，每卡年费与卡量取 Selected Card Related Statistical Information。",
    }

    # The company's own printed average discount rate is a ratio the company
    # computes on its own basis, not a revenue line, and the values it printed
    # run 2.44% (2016Q4) into 2.43% (2017Q1) with no step. The *derived* line
    # starts at 2021Q1, and that one is a basis limit -- see the note.
    printed = staging["operating_metrics"]["company_average_discount_rate_pct"]
    billed = staging["operating_metrics"]["billed_business_usd_bn"]
    derived_idx = [i for i, p in enumerate(periods) if p >= "2021Q1"]
    derived_rate = [None] * len(labels)
    for i in derived_idx:
        derived_rate[i] = discount[i] / (billed[i] * 1000) * 100
    overlap = [i for i in derived_idx if printed[i] is not None]
    gap = [(derived_rate[i] - printed[i]) * 100 for i in overlap]
    printed_idx = [i for i, v in enumerate(printed) if v is not None]
    last_printed = printed_idx[-1]
    released = release_of(staging, last_printed)
    first_revenue = next(i for i, v in enumerate(revenue) if v is not None)
    one_sided = all(v < 0 for v in gap) or all(v > 0 for v in gap)
    rate_chart = {
        "ref": "EX_RATE",
        "kind": "lines",
        "title": (f"商户那一侧的价格：公司自己印的平均折扣率停在 {periods[last_printed]}，"
                  "自算那条不是它的延续"),
        "xlabels": labels,
        "xrot": 90,
        "xstep": LONG_STEP,
        "series": [
            {"name": "公司披露的平均折扣率", "values": rounded(printed), "color": "NAVY"},
            {"name": "折扣收入 ÷ 消费额（本页自算，非同一口径）",
             "values": rounded(derived_rate), "color": "GOLD"},
        ],
        "fmt": "pct2", "yfmt": "pct2", "label_fmt": "pct2", "end_label": True,
        "ylab": "%",
        "note": (
            "<b>两条线不是同一个数，本页不把它们接成一条。</b>"
            f"公司在每份业绩表里印了 {len(printed_idx)} 个季度的"
            f"「Average discount rate」，最后一次出现在 {released[:4]} 年 {int(released[5:7])} 月发布的 "
            f"{compact_period(periods[last_printed])} 那一格，"
            "之后这一行从统计表里消失，再也没有回来。它的脚注把分母定义为"
            "<b>自营与网络伙伴合计</b>的消费额、并扣掉第三方收单机构留存的部分，"
            "所以它不是「折扣收入 ÷ 消费额」。"
            + (f"在两条线重叠的 {len(overlap)} 个季度里，自算那条稳定地比公司印的"
               f"{'低' if max(gap) < 0 else '高'} {min(abs(v) for v in gap):.1f} 到 "
               f"{max(abs(v) for v in gap):.1f} 个基点 —— "
               "<b>这是一个口径造成的水平差，不是噪声</b>，所以把公司那条的末端接到自算那条上，"
               f"会在 {periods[last_printed]} 与 {periods[last_printed + 1]} 之间画出一个纯属口径的台阶。"
               if one_sided and overlap else "")
            + "自算那条也只从 2021Q1 起：2021 年之前折扣收入里还含着 processed revenue，"
            "而分母在 2020 年就已经改成只算自营，"
            "<b>拿旧口径的分子除新口径的分母，会读出一次并不存在的提价</b>。"
            + (f"<b>公司那条和本页收入侧的长序列一样从 {labels[printed_idx[0]]} 起。</b>"
               if printed_idx[0] == first_revenue else
               f"<b>公司那条从 {labels[printed_idx[0]]} 起。</b>")
            + "平均折扣率是公司按自己的口径算出来的一个比率，不是收入确认口径下的一行金额，"
            "它印出来的值在 2016Q4 的 2.44% 与 2017Q1 的 2.43% 之间没有台阶。"
            "此前它停在 2017Q1，是因为跟着收入那几条一起被截，不是因为公司没披露过。"),
        "src_extra": "平均折扣率为公司披露值；自算折扣率 = 折扣收入 ÷ 消费额（D），分母以十亿计需换算。",
    }

    # Net income and diluted EPS sit below the ASC 606 gross-up, so the chart
    # and the diluted share count in its note both read the whole record: the
    # note divides the fall in share count against the ratio of the two
    # multiples, and taking them over different spans compares two spans in one
    # sentence (that is how a 7.7pp span mismatch once read as preferred
    # dividends).
    net_income = fin["net_income_usd_m"]
    eps = fin["diluted_eps_usd"]
    shares = fin["diluted_shares_m"]
    ni_index = [v / net_income[0] * 100 for v in net_income]
    eps_index = [v / eps[0] * 100 for v in eps]
    eps_m, ni_m = eps[-1] / eps[0], net_income[-1] / net_income[0]
    not_operating = (eps_m - ni_m) / (eps_m - 1) if eps_m > 1 else None
    tax_quarter = periods.index("2017Q4")
    buyback_chart = {
        "ref": "EX_BUYBACK",
        "kind": "lines",
        "title": (f"净利润与每股收益的分岔：{len(labels)} 季里净利润长到 "
                  f"{ni_m:.2f} 倍，摊薄 EPS 长到 {eps_m:.2f} 倍"),
        "xlabels": labels,
        "xrot": 90,
        "xstep": LONG_STEP,
        "series": [
            {"name": f"净利润（{labels[0]} = 100）", "values": rounded(ni_index), "color": "NAVY"},
            {"name": f"摊薄 EPS（{labels[0]} = 100）", "values": rounded(eps_index), "color": "GOLD"},
        ],
        "fmt": "f0", "yfmt": "f0", "label_fmt": "f0", "end_label": True,
        "ylab": f"指数（{labels[0]} = 100）",
        "note": (
            "<b>两条线之间的缺口几乎全是回购。</b>同期摊薄股数从 "
            f"{shares[0]:,.0f}M 降到 {shares[-1]:,.0f}M"
            f"（{pct_change(shares[-1], shares[0]):+.1f}%），"
            f"倒数是 {shares[0] / shares[-1]:.3f} 倍，"
            f"而两条线的倍数之比是 {eps_m / ni_m:.3f} 倍 —— "
            "剩下的一点点差额是优先股股息与参与型股权激励分走的部分，不是别的。"
            + ("<b>这条缺口是每股收益增长里不来自经营的那一半的量度</b>"
               if not_operating is not None and 0.4 <= not_operating <= 0.6 else
               "<b>这条缺口是每股收益增长里不来自经营的那一部分的量度</b>")
            + "，而它依赖资本比率还有多少余量，见第三节的 CET1 那张图。"
            + ("2017Q4 净利润为负是当年的税改一次性费用，两条线在那一格同时下穿。"
               if net_income[tax_quarter] < 0 and eps[tax_quarter] < 0 else "")),
        "src_extra": "净利润、摊薄 EPS 与摊薄股数均取自各季业绩 8-K EX-99.2 的合并损益表；指数化为本页自算（D）。",
    }

    fee_share = [card_fees[i] / revenue[i] * 100 for i in range(len(revenue))]
    discount_share = [discount[i] / revenue[i] * 100 for i in range(len(revenue))]
    spike = max(range(len(fee_share)), key=fee_share.__getitem__)
    share_chart = {
        "ref": "EX_SHARE",
        "kind": "lines",
        "title": (f"两条腿占收入的比重：净卡费 {fee_share[0]:.1f}% → {fee_share[-1]:.1f}%，"
                  f"商户折扣收入 {discount_share[0]:.1f}% → {discount_share[-1]:.1f}%"),
        "xlabels": labels,
        "xrot": 90,
        "xstep": LONG_STEP,
        "series": [
            {"name": "净卡费 ÷ 收入", "values": rounded(fee_share), "color": "GOLD"},
            {"name": "商户折扣收入 ÷ 收入", "values": rounded(discount_share), "color": "NAVY"},
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
        "ylab": "占收入 %",
        "note": (
            ("<b>同一家公司的两个价格，方向相反。</b>"
             if (fee_share[-1] - fee_share[0]) * (discount_share[-1] - discount_share[0]) < 0 else "")
            + "向持卡人收的年费从占收入"
            + ("不到九分之一" if fee_share[0] < 100 / 9 else share_words(fee_share[0]))
            + ("涨到" if fee_share[-1] > fee_share[0] else "降到") + share_words(fee_share[-1])
            + "；向商户收的折扣收入从占收入" + share_words(discount_share[0])
            + ("降到" if discount_share[-1] < discount_share[0] else "涨到") + share_words(discount_share[-1])
            + "。"
            + ("2020 年那个尖峰是疫情：消费塌了而年费是合同性的，所以分母掉得比分子快，"
               "它是分母事件不是提价事件。" if periods[spike].startswith("2020") else "")
            + "折扣收入那条在 2021Q1 有一次口径下移（processed revenue 移出），见 Exhibit {EX_MIX} 的断点。"),
        "src_extra": "两条比值均由同一份合并损益表的申报值相除得到（D）。",
    }
    return [price_chart, share_chart, rate_chart, buyback_chart]


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    fin = staging["financials"]
    fees = fin["net_card_fees_usd_m"]
    vce = (fin["rewards_usd_m"][-1] + fin["card_member_services_usd_m"][-1]
           + fin["business_development_usd_m"][-1])
    return [f"Revenue ${fin['revenue_usd_m'][-1] / 1000:.1f}B",
            f"净卡费 {(fees[-1] / fees[-5] - 1) * 100:+.1f}%",
            f"VCE 占收入 {vce / fin['revenue_usd_m'][-1] * 100:.1f}%"]


def settled_words(block: dict) -> str:
    """How last quarter's thresholds were settled, counted from the block."""
    quantified = block["quantified"]
    unsettled = block.get("unsettled", [])
    items = {entry["note_item"] for entry in quantified} | {entry["note_item"] for entry in unsettled}
    settled_items = {entry["note_item"] for entry in quantified}
    unjudgeable = [entry for entry in unsettled if entry["kind"] == "unjudgeable"]
    declined = [entry for entry in unsettled if entry["kind"] == "declined"]
    words = (f"上季那份分析一共立了{cn_count(len(items))}条阈值，本页结清了其中"
             f"{cn_count(len(settled_items))}条"
             + (f"（拆成{cn_count(len(quantified))}根阈值线）" if len(quantified) != len(settled_items) else ""))
    if unjudgeable:
        openers = ["一条", "另一条"] if len(unjudgeable) == 2 else [
            f"第{cn_ordinal(i + 1)}条" for i in range(len(unjudgeable))]
        words += (f"，另外{cn_count(len(unjudgeable))}条<b>无法判定</b>"
                  + ("，原因不同：" if len(unjudgeable) > 1 else "：")
                  + "；".join(opener + entry["text"] for opener, entry in zip(openers, unjudgeable)))
    words += "。"
    for entry in declined:
        words += ("剩下一条" if len(declined) == 1 else "另有一条") + entry["text"]
    return words


def build_payload(staging: dict) -> dict:
    fin = staging["financials"]
    labels = staging["period_labels"]
    period = labels[-1]
    latest = latest_block(staging, period=period, period_end=staging["period_ends"][-1])
    release = release_source(staging)
    settled_block = stamped_block(staging, "settled_kpi", period)
    next_block = stamped_block(staging, "next_kpi", period)
    story = stamped_block(staging, "quarter_story", period)
    g = staging["annual_guidance_history"]
    facts = record_facts(staging)
    eps_v, rev_v = facts["metrics"]["eps"], facts["metrics"]["revenue"]

    revenue = fin["revenue_usd_m"]
    expenses = fin["total_expenses_usd_m"]
    provisions = fin["provisions_usd_m"]
    pretax = fin["pretax_income_usd_m"]
    ppop = fin["ppop_usd_m"]
    card_fees = fin["net_card_fees_usd_m"]
    eps = fin["diluted_eps_usd"]

    rev_yoy = pct_change(revenue[-1], revenue[-5])
    eps_yoy = pct_change(eps[-1], eps[-5])
    jaws = rev_yoy - pct_change(expenses[-1], expenses[-5])
    d_pretax = pretax[-1] - pretax[-5]
    d_prov = -(provisions[-1] - provisions[-5])
    d_ppop = ppop[-1] - ppop[-5]
    vce = (fin["rewards_usd_m"][-1] + fin["card_member_services_usd_m"][-1]
           + fin["business_development_usd_m"][-1])
    vce_ratio_now = vce / revenue[-1] * 100
    fee_share = card_fees[-1] / revenue[-1] * 100

    next_entries = kpi_entries(next_block, "current", staging) if next_block else []
    settled_entries = kpi_entries(settled_block, "actual", staging) if settled_block else []

    guidance, settled_tables = guidance_charts(staging, facts)
    settled = []
    if settled_entries:
        settled.append(headroom_exhibit(
            f"上季那份分析立的阈值里，能结清的 {len(settled_entries)} 条",
            settled_entries, "actual",
            ("正值表示仍在安全侧。这些是本地研究设定的阈值，不是公司指引。"
             + settled_words(settled_block)
             + fill_story(settled_block.get("breach_story", ""), block_values(staging, settled_block))),
            f"实际值为 {staging['periods'][-1]} 的申报值；阈值为上季本地研究设定。"))
    settled += guidance

    highlights = quarter_charts(staging, next_entries)
    next_charts = next_quarter_charts(staging, next_entries, next_block)
    price, share, rate, buyback = routine_charts(staging)
    mix, seg = structure_charts(staging)
    routine = [price, mix, share, rate, seg, buyback]

    exhibits = number_exhibits(settled + highlights + next_charts + routine)
    resolve_exhibit_refs(exhibits)
    n1, n2, n3 = len(settled), len(highlights), len(next_charts)
    settled_ex = exhibits[:n1]
    highlight_ex = exhibits[n1:n1 + n2]
    next_ex = exhibits[n1 + n2:n1 + n2 + n3]
    routine_ex = exhibits[n1 + n2 + n3:]

    first_table = exhibits[-1]["n"] + 1
    tables = [{**t, "n": first_table + i} for i, t in enumerate(settled_tables)]
    n = first_table + len(settled_tables)
    tables.append({
        "n": n,
        "title": "近八季合并损益与收入结构（公司披露值，D 为自算）",
        "headers": ["期间", "收入", "商户折扣收入", "净卡费", "其他非利息收入 D", "净利息收入",
                    "拨备", "总费用", "拨备前利润 D", "税前利润", "摊薄 EPS"],
        "rows": [[labels[i], f"${revenue[i]:,.0f}M", f"${fin['discount_revenue_usd_m'][i]:,.0f}M",
                  f"${card_fees[i]:,.0f}M", f"${fin['other_non_interest_revenue_usd_m'][i]:,.0f}M",
                  f"${fin['net_interest_income_usd_m'][i]:,.0f}M", f"${provisions[i]:,.0f}M",
                  f"${expenses[i]:,.0f}M", f"${ppop[i]:,.0f}M", f"${pretax[i]:,.0f}M",
                  f"${eps[i]:.2f}"]
                 for i in range(len(labels) - 8, len(labels))],
    })
    n += 1
    lo_k, hi_k, _ = METRIC_KEYS["revenue"]
    tables.append({
        "n": n,
        "title": "全年收入增速：公司自报的整数与申报金额除出来的两位小数",
        "headers": ["财年", "指引（结算那一档）", "公司自报（报告口径）", "公司自报（汇率调整）",
                    "申报金额相除 D", "全年收入"],
        "rows": [[f"FY{year}",
                  (band_words(g[lo_k][rev_v["settle"][int(year)]], g[hi_k][rev_v["settle"][int(year)]],
                              "revenue") if int(year) in rev_v["settle"] else "—"),
                  f"{block['growth_reported_pct']}%" if block["growth_reported_pct"] is not None else "—",
                  f"{block['growth_fx_pct']}%" if block["growth_fx_pct"] is not None else "—",
                  f"{block['growth_exact_pct']:+.2f}%" if block["growth_exact_pct"] is not None else "—",
                  f"${block['revenue_usd_m']:,.0f}M"]
                 for year, block in sorted(g["actual_by_year"].items())],
    })
    if next_entries:
        n += 1
        tables.append(threshold_table(n, "下季阈值与当前值（原始单位）", next_entries, "current", "当前值"))
    if settled_entries:
        n += 1
        tables.append(threshold_table(n, "上季阈值与本季实际值（原始单位）",
                                      settled_entries, "actual", "本季实际值"))
    n += 1
    tables.append(ai_capex_cycle_table(n))

    # The ledger is a TABLE, not an exhibit, so it is numbered after the charts
    # and its placeholder cannot be resolved in the exhibit pass above.
    for exhibit in exhibits:
        for field in ("note", "src_extra", "title"):
            if exhibit.get(field):
                exhibit[field] = exhibit[field].replace("{EX_LEDGER}", str(first_table))

    years_n = cn_count(len(facts["years"]))
    unsettled_years = {y for m in facts["metrics"].values() for y in m["reasons"]}
    kinds = []
    for kind in ("two_ranges", "basis", "withdrawn", "never", "not_guided", "open"):
        word = REASON_BRIEF[kind]
        if any(r["kind"] == kind for m in facts["metrics"].values() for r in m["reasons"].values()) \
                and word not in kinds:
            kinds.append(word)
    # Share of year-metric pairs the record cannot settle: EPS and revenue are
    # two promises a year, and each is settled (or not) on its own.
    unsettled_share = ((len(eps_v["reasons"]) + len(rev_v["reasons"]))
                       / (2 * len(facts["years"])))
    fraction = ("一半" if abs(unsettled_share - 0.5) <= 0.05 else
                "过半" if unsettled_share > 0.5 else "不到一半的")
    two_sided = (not eps_v["below"]) and bool(rev_v["below"])
    blank_n = len(facts["blank"])
    first_revenue_year = min(g["fiscal_years"][i] for i in range(facts["n"])
                             if g["guide_revenue_growth_lo_pct"][i] is not None)
    basis_changes = len({code for code in g["guide_eps_basis"] if code in BASIS_CHANGES})
    withdrawn_n = len([y for y, r in eps_v["reasons"].items() if r["kind"] == "withdrawn"])
    never_n = len([y for y, r in eps_v["reasons"].items() if r["kind"] == "never"])

    audit_words = {"unaudited": "未审计", "audited": "已审计"}[latest["audit_status"]]
    printed = staging["operating_metrics"]["company_average_discount_rate_pct"]
    last_printed = max(i for i, v in enumerate(printed) if v is not None)
    stopped_year = staging["periods"][last_printed + 1][:4]
    prov_share = d_prov / d_pretax if d_pretax > 0 else None
    if prov_share is not None and 0 < prov_share < 1:
        prov_title = f"税前增量的{cn_count(round(prov_share * 10))}成来自拨备行"
    elif prov_share is not None and prov_share >= 1:
        prov_title = "税前增量全部来自拨备行"
    elif prov_share is not None:
        prov_title = "税前增量全部来自经营"
    else:
        prov_title = "税前利润同比没有增长"
    if d_pretax > 0 and d_prov > d_ppop:
        headline_tail = (f"；但税前利润 {signed(pct_change(pretax[-1], pretax[-5]))} 的增量里，"
                         f"US${d_prov:,.0f}M 来自拨备行、US${d_ppop:,.0f}M 来自经营 —— "
                         f"拨备前利润只增长 {signed(pct_change(ppop[-1], ppop[-5]))}，jaws {jaws:+.1f}pp。")
    else:
        headline_tail = (f"；税前利润 {signed(pct_change(pretax[-1], pretax[-5]))}，"
                         f"其中经营腿 {money(d_ppop)}、拨备腿 {money(d_prov)}，"
                         f"拨备前利润 {signed(pct_change(ppop[-1], ppop[-5]))}，jaws {jaws:+.1f}pp。")
    total_kpis = len({e["note_item"] for e in settled_block["quantified"]}
                     | {e["note_item"] for e in settled_block.get("unsettled", [])}) if settled_block else 0
    reason_note = eps_note_reasons(facts, g)
    qualified = [y for y, i in sorted(eps_v["settle"].items())
                 if any(g["fiscal_years"][j] == y and g["guide_eps_basis"][j] == "includes_accertify_gain"
                        for j in range(facts["n"]))]
    qualified_month = next((int(g["filed"][j][5:7]) for j in range(facts["n"])
                            if qualified and g["fiscal_years"][j] == qualified[0]
                            and g["guide_eps_basis"][j] == "includes_accertify_gain"), None)
    highlights_n = len(highlight_ex)
    story_values = block_values(staging, story)
    not_wired = [fill_story(text, story_values) for text in (story or {}).get("not_wired", [])]
    release_date = latest["release_date"]
    divergent_fx = [y for y in rev_v["below"]
                    if g["actual_by_year"][str(y)]["growth_fx_pct"] not in
                    (None, g["actual_by_year"][str(y)]["growth_reported_pct"])]

    notes = [
        "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
        "美国运通财年即自然年，本页季度标注与公司自己的口径一致，无需换算。",
        f"本页整张损益表现在是一个口径的 {len(labels)} 季。公司自 2018-01-01 起适用 ASC 606 并在自家统计表里重述了 2017 年 —— 2018 年 1 月发布中 Q1 2017 的折扣收入是 4,519，2018 年 4 月发布中同一季是 5,387，Card Member rewards 同步等额调高，收入合计从 7,889 变成 8,709。此前本页把 2016 那四季留在旧口径上，理由写的是「公司从未按季重发 2016，因为每份发布只并排印五个季度、最后一份带 Q4 2016 的发布早于该变更」—— 这句话对业绩发布成立，对公司不成立：2018-03-09 那份 Item 7.01 的 8-K，Exhibit 99.1「Eight Quarter Trend Q1 2016 through Q4 2017」把 As Reported、Adjustments、As Recast 三栏并排印了八个季度。2016 四季现在取自该文件的 As Recast 栏。该文件通篇标着 (Preliminary) 且从未被最终版取代，而这份不确定性是可以量的，因为同一份文件也覆盖 2017：对着本页早已采用的四个 2017 季度，它在收入上差 1 百万美元、在拨备上差一个方向相反的 1 百万美元（四季里的三季），在总费用、税前利润、净利润上一分不差。同样的差一位也出现在它的 As Reported 栏，所以那是初步数据的噪声，不是重述本身带来的。注意重述并非在两侧完全抵消：2016 四季的净利润被移动了 +13、−30、0、−16。",
        "第一节结清的是年度指引而不是季度指引：公司的展望几乎只给全年，本站其他几页第一节结清的是季度收入区间，本页不是，差别源于公司披露口径而非编辑选择。"
        "季度区间本页至少见过两次，都不进年度记录：2019-10-18 的业绩发布给了 2019 年第四季度收入增速 8%–10%，"
        "2020-03-17 那份 Item 7.01 的 8-K 给了 2020 年第一季度汇率调整口径收入增速 2%–4% 与剔除准备金计提的调整后 EPS $1.90–$2.10。",
        f"{years_n}个财年里，全年 EPS 指引只有{cn_count(len(eps_v['settle']))}年（{year_list(list(eps_v['settle']))}）、"
        f"全年收入增速指引只有{cn_count(len(rev_v['settle']))}年（{year_list(list(rev_v['settle']))}）"
        "可以被诚实结清，逐年理由列在核对抽屉的第一张表里。"
        f"EPS 不能结清的{cn_count(len(eps_v['reasons']))}年各有原因：" + reason_note + "。"
        + (f"另有{cn_count(len(qualified))}年是结清了但带限定：FY{qualified[0]} 的指引在 "
           f"{qualified_month} 月被整体上调以容纳一笔出售收益，"
           "上调后的区间与原区间不是同一个东西，这一点写在该年的那几格上。" if len(qualified) == 1 else ""),
        "2020 年全年指引的撤回不在业绩 8-K 里。公司在 2020-03-17 单独报了一份 Item 7.01 的 8-K 说明无法预测第一季度以后的业绩，随后三份业绩新闻稿的前瞻性声明段里「2020 年展望」这个对象整段消失。只读业绩 8-K 会把它读成「没给过指引」，而不是「给过又撤回」。",
        "收入增速的指引与实际值在图上都用整数个百分点，因为公司只用这个精度说话：指引写成「9% 到 10%」，实际值写成「up 9 percent」。用申报金额除出两位小数再判定，会给这份承诺发明一个它从未有过的精度 —— FY2019 的 7.98% 是这样落在 8% 的下限上的，FY2024 的 8.98% 是这样落在 9% 那个单点上的。两位小数的商列在核对抽屉里。",
    ]
    if len(rev_v["below"]) == 1 and divergent_fx:
        year = rev_v["below"][0]
        i = rev_v["settle"][year]
        block = g["actual_by_year"][str(year)]
        fx_lo = block["growth_fx_pct"] == g[lo_k][i]
        notes.append(
            f"FY{year} 是窗口内唯一一次收入增速真正跌破下限，而它同时是一次口径事件："
            f"指引 {band_words(g[lo_k][i], g[hi_k][i], 'revenue')}，公司自己报的是"
            f"「up {block['growth_reported_pct']} percent（{block['growth_fx_pct']} percent FX-adjusted）」。"
            + ("汇率调整口径正好踩在下限上，报告口径没有。" if fx_lo else "")
            + "本页按报告口径判定并在图上写明两者都存在。")
    ratio = vce_ratio(staging)
    vce_n = sum(1 for v in ratio if v is not None)
    printed_idx = [i for i, v in enumerate(printed) if v is not None]
    overlap = [i for i in printed_idx if staging["periods"][i] >= "2021Q1"]
    billed = staging["operating_metrics"]["billed_business_usd_bn"]
    discount = fin["discount_revenue_usd_m"]
    gaps = [(discount[i] / (billed[i] * 1000) * 100 - printed[i]) * 100 for i in overlap]
    notes += [
        f"VCE（可变客户参与成本）用公司自己的定义 —— Card Member rewards + business development + Card Member services —— 序列只有 {vce_n} 个季度，因为 business development 到 2022 年 4 月那份发布才第一次从 Marketing 里拆出来，公司只把 2021 年四个季度按新口径重述过。这不是选出来的窗口，是这个数存在的全部长度。",
        f"分部序列只有 {len(staging['segment_periods'])} 个季度，且不能往前接。现在这四个分部是 2022 年 10 月那份业绩发布启用的，同一份发布用一张附表把 2020 年第一季度以后的{cn_count(staging['segment_periods'].index('2022Q3'))}个季度按新口径重算了一遍，本页的分部窗口就是那张附表的长度。再往前是另一套三分部结构，公司没有为它提供过按新口径的重算。",
        "商户折扣收入在 2021 年第一季度有一次口径变化：processed revenue 被移出这一行、并进其他非利息收入，公司只重述了 2021 年四个季度。收入合计不受影响，因此任何总额层面的核对都发现不了这次挪动，图上因此打了断点。同样的原因，「其他非利息收入」这条腿是用非利息收入合计减去折扣收入与净卡费得到的，而不是取那一行印出来的数 —— 那一行在窗口内被改过两次名并被并过一次。",
        "公司披露的「平均折扣率」与本页自算的「折扣收入 ÷ 消费额」不是同一个数，本页把它们画成两条线而不是一条。公司的口径把分母定义为自营与网络伙伴合计的消费额并扣掉第三方收单机构留存的部分；"
        + (f"在两条线重叠的{cn_count(len(overlap))}个季度里，自算那条稳定地比公司印的"
           f"{'低' if max(gaps) < 0 else '高'} {min(abs(v) for v in gaps):.1f} 到 {max(abs(v) for v in gaps):.1f} 个基点 —— 是口径造成的水平差，不是噪声。"
           if gaps and (all(v < 0 for v in gaps) or all(v > 0 for v in gaps)) else "")
        + f"公司自 {release_of(staging, last_printed)[:4]} 年 {int(release_of(staging, last_printed)[5:7])} 月发布的 {quarter_label(staging['periods'][last_printed])} 之后不再披露这一行，本页也不为它编一个延续。",
        "自算的折扣率只从 2021 年第一季度起。2020 年那四个季度的分子还含着 processed revenue，而分母在 2021 年 4 月那份发布里已经被改成只算自营消费额，拿旧口径的分子除新口径的分母会读出一次并不存在的提价 —— 没有任何一条恒等式能发现这个错误。",
        "信用指标的两段序列是接起来的，接线的依据写在图上：公司在 2026 年第一季度把 Card Member loans 与 receivables 合并列示为 Card balances，同一份发布把前四个季度按新口径重述了一遍，而这四个季度两种口径印出来的数字完全相同 —— 公司自己的附注也写明「无计量影响」。没有这段重叠就不会接。",
        "本页不发布市场一致预期，也不发布评级、目标价与估值。站点规则允许发布带日期、不署机构名的「市场预期」对照点，但不允许凭印象填一个数，而本季没有可核对的公开来源。",
        "本页只发布公司披露值与可复算的简单派生值；D 标记代表 Derived / 自算，不代表公司定义的非 GAAP 指标。",
        "本页已知未接入：季度层面的分红与回购金额（现金流量表按年初至今披露，业绩表只印回购股数不印金额）；汇率调整口径的消费与收入增速序列（公司只披露到整数个百分点）；"
        + "".join(text + "；" for text in not_wired)
        + f"以及 {int(release_date[:4])} 年 {int(release_date[5:7])} 月 {int(release_date[8:10])} 日之后的任何数据。",
        "核对抽屉最后那张「AI capex 循环」是全站共用的跨页对照块，在每一页都逐字节相同，不是对美国运通的判断。它追的是四家云厂现金资本开支 → NVDA 数据中心收入 → TSM 晶圆这条链，美国运通不在这条链的任何一环上。把它放在这里是为了让读者在任意一页都能查到同一份上下游对照；它在折叠的抽屉里，不参与本页的论证。",
        "业绩电话会内容不进本页。公司在电话会上给过若干前瞻数字（例如全年 VCE 占收入比、市场营销费用的增长口径），但业绩 8-K 里没有它们，无法与第二个来源核对，本站不转录只在网络广播里出现过的数字。",
    ]

    return {
        "schema_version": "quarterly-dashboard/axp-v1",
        "page": {"slug": "axp", "language": "zh-CN"},
        "company": {
            "ticker": "AXP",
            "name": "American Express Company",
            "group": "payment_networks",
            "accounting_standard": "US GAAP",
        },
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · AXP",
        "title": f"American Express (AXP)：{period} 季报仪表盘",
        "subtitle": (f"截至 {latest['period_end']} · 发布 {latest['release_date']} · US GAAP · {audit_words} · "
                     "自然年财年，季度标注与公司口径一致"),
        "headline": (
            f"收入 US${revenue[-1]:,.0f}M、同比 {signed(rev_yoy)}，摊薄 EPS ${eps[-1]:.2f}、"
            f"同比 {signed(eps_yoy)}" + headline_tail),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            f'<article><span>记录</span><b>公司自己的指引，{fraction}年份结不了账</b>'
            f'<p>{years_n}个财年、{facts["n"]} 档全年指引里，EPS 只有 {len(eps_v["settle"])} 年、收入只有 '
            f'{len(rev_v["settle"])} 年能被诚实结清；其余各年或' + "、或".join(kinds) + '。'
            + (f'能结清的部分是两面的：EPS {len(eps_v["below"])} 次跌破下限，收入 {len(rev_v["below"])} 次。'
               if two_sided else
               f'能结清的部分里 EPS {len(eps_v["below"])} 次跌破下限，收入 {len(rev_v["below"])} 次。')
            + '</p></article>'
            f'<article><span>成色</span><b>{prov_title}</b>'
            f'<p>税前同比 {money(d_pretax)} = 经营腿 {money(d_ppop)} + 拨备腿 '
            f'{money(d_prov)}，是申报值构成的恒等式。VCE 占收入 {vce_ratio_now:.1f}%，'
            f'jaws {jaws:+.1f}pp。</p></article>'
            '<article><span>结构</span><b>持卡人的价格在涨，商户的在降</b>'
            f'<p>{len(labels)} 季里净卡费长到 {card_fees[-1] / card_fees[0]:.2f} 倍、占收入从 '
            f'{card_fees[0] / revenue[0] * 100:.1f}% 到 {fee_share:.1f}%；'
            f'商户折扣收入只长到 {fin["discount_revenue_usd_m"][-1] / fin["discount_revenue_usd_m"][0]:.2f} 倍，'
            f'而公司自 {stopped_year} 年起不再披露平均折扣率。</p></article>'
            '</div>'),
        "source": (f'Source: <a href="{release["url"]}" rel="noopener">'
                   f'American Express {quarter_words(period)}业绩新闻稿（8-K EX-99.1）</a>'
                   f'{statistical_tables_words(staging, release)}。'),
        "source_url": release["url"],
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {"id": "settled", "title": "一、上季跟踪指标兑现了吗",
             "description": plain_text(
                 (f"这一节先结清上季那份本地分析立的{cn_count(total_kpis)}条阈值，再结清公司自己的全年指引，"
                  "而后者在本站是头一回结不出一个数。" if settled_block else
                  "这一节结清的是公司自己的全年指引，而它在本站是头一回结不出一个数。")
                 + "美国运通的全年展望写在业绩 8-K 的 EX-99.1 里 —— 摊薄 EPS，"
                 f"FY{first_revenue_year} 起再加收入增速 —— 年初给一次、当年后三期各更新一次，"
                 f"{years_n}个财年一共 {facts['n']} 档，其中 {blank_n} 档一个数都没印。"
                 f"但这份记录不能当成一条连续的序列读：口径改过{cn_count(basis_changes)}次、"
                 f"撤回过{cn_count(withdrawn_n)}次、还有{cn_count(never_n)}整年从头到尾没给。"
                 "所以先说清哪些年份能结清、哪些不能，再结清能结的。"),
             "exhibits": settled_ex},
            {"id": "quarter_highlights", "title": "二、本季重点",
             "description": plain_text(
                 "本季的核心张力是「利润从哪来」：税前利润同比增量拆成经营与拨备两条腿，"
                 "这是一个由申报值构成的恒等式，不含任何估计。"
                 f"其余{cn_count(highlights_n - 1)}张分别是压住经营腿的那条费用（VCE）与"
                 + ("它造成的负 jaws。" if jaws < 0 else "jaws 的走向。")),
             "exhibits": highlight_ex},
            {"id": "next_quarter", "title": "三、下季要跟踪什么",
             "description": plain_text(
                 ("当前值离下季阈值还有多远，统一用「距阈值余量」口径"
                  + (f"；不接入的{cn_count(len(next_block.get('excluded', [])))}条与它们各自的理由也写在这一节。"
                     if next_block.get("excluded") else "。")
                  if next_entries else "本季没有新立的下季阈值，本节没有图。")),
             "exhibits": next_ex},
            {"id": "routine", "title": "四、长期常规跟踪",
             "description": plain_text(
                 "美国运通专属的常规序列：卡费这台涨价机器的量价两条腿、四条收入腿的长期结构、"
                 "持卡人与商户两侧价格的反向移动、公司自己停掉的那条折扣率、四个分部的税前利润率，"
                 "以及净利润与每股收益之间那道回购缺口。"),
             "exhibits": routine_ex},
        ],
        "tables": tables,
        "notes": notes,
        "footer": "American Express quarterly results · 数据来自 AXP 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def quarter_label(period: str) -> str:
    """``'2022Q4'`` -> ``'Q4 2022'``."""
    return f"{period[4:]} {period[:4]}"


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "axp.js"), payload, "axp")
    shell_dir = ROOT / "axp"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("AXP", "axp"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"AXP page: {charts} charts in {len(payload['sections'])} sections "
          f"+ {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
