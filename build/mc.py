#!/usr/bin/env python3
"""LVMH Moët Hennessy Louis Vuitton quarterly dashboard.

LVMH publishes revenue four times a year and profit twice. The first and third
quarter releases are revenue announcements: divisional euro amounts and organic
growth rates, and not one line of profit. The income statement, divisional
operating profit, the currency and perimeter effects on profit, the cash flow
statement, the balance sheet, the store count and earnings per share exist only
at the half-year and the full year.

So in the quarters this page covers, **no quarter has a profit number of its
own**. That is not a gap in the sourcing; it is the disclosure. The page
therefore runs two independent x axes -- revenue by quarter, profit by half --
and interpolates nothing. Every half-year chart says "半年" in its own axis
label, because a reader who mistakes a half for a quarter here halves every
margin denominator on the page.

The company issues no numeric guidance at all. Its only forward statements are
sentences on a call, so section one scores sentences: the ones made on the
previous call, settled by this quarter's release.

**A roll edits `series/mc.json` and nothing else.** Every period label, count
and figure on the page is computed from the series; every sentence that says
something true of the data (「第一次」「每一次都」「连续下降」) is printed only
while the data says it, and falls back to a plain statement otherwise. What
belongs to one quarter or one half -- the call record, the next thresholds,
quotes and attributions -- lives in period-stamped blocks of the series
(`call_record`, `forward_statements`, `next_kpi`, `quarter_story` on the
quarter; `half_story` on the latest half). A block stamped for another period
stops the build; a missing block drops the charts and sentences that need it.
A number the series arrays already carry is never typed into a story sentence:
the sentence names it (``{now:wines_spirits}``) and `board.fill_story` puts the
computed value in.

Fixed history stays in the code because a roll does not change it: the two
consolidations the long record straddles (Christian Dior Couture in 2017,
Tiffany in January 2021), the nine full-year releases the 2016-2025 record was
stitched from, and LVMH's SEC filing history.

Published numbers are company-reported or transparent arithmetic. Where the
company printed a figure the page also computes -- a divisional margin to one
decimal -- the text prints the company's; thresholds are local research
settings, not company guidance.
"""

from __future__ import annotations

import json
import sys
from math import gcd
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
    latest_block,
    minus_sign,
    number_exhibits,
    stamped_block,
    threshold_exhibit,
    unit_text,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "mc.json"
DATA_DIR = ROOT / "data"

DIVS = ["wines_spirits", "fashion_leather", "perfumes_cosmetics",
        "watches_jewelry", "selective_retailing"]
DIV_NAMES = {"wines_spirits": "葡萄酒与烈酒", "fashion_leather": "时装与皮具",
             "perfumes_cosmetics": "香水与化妆品", "watches_jewelry": "手表与珠宝",
             "selective_retailing": "精品零售"}
DIV_COLORS = {"wines_spirits": "GOLD", "fashion_leather": "NAVY",
              "perfumes_cosmetics": "GREEN", "watches_jewelry": "BLUE",
              "selective_retailing": "MBLUE", "other": "GRAY"}
STORE_KEYS = ("france", "europe_ex_fr", "united_states", "japan", "asia_ex_japan",
              "other_markets", "total")
STORE_NAMES = {"france": "法国", "europe_ex_fr": "欧洲（除法国）", "united_states": "美国",
               "japan": "日本", "asia_ex_japan": "亚洲（除日本）",
               "other_markets": "其他市场（含中东）"}
REGION_NAMES = {"united_states": "美国", "asia_ex_japan": "亚洲（除日本）",
                "japan": "日本", "europe": "欧洲"}

# What the series' `latest.audit_status` means on the subtitle.
AUDIT_WORDS = {
    "limited_review_pending": "有限审阅报告尚未出具",
    "limited_review": "经有限审阅",
    "unaudited": "未经审阅",
    "audited": "经审计",
}

SOURCE_QUARTER = ("分部季度收入与有机增速逐季取自公司自己的季度收入公告与半年度／全年业绩新闻稿附录"
                  "「Revenue by business group and by quarter」，以及全年业绩演示材料附录的"
                  "「Quarterly revenue by business group – Organic change」。")
SOURCE_HALF = ("半年度数字取自当期半年度业绩新闻稿与半年度财务报告；H2 各行由「全年减上半年」得出并标 D，"
               "全年数取自 Financial Documents。公司不按季披露任何利润行。")


# ── period arithmetic ────────────────────────────────────────────────────────
def compact_quarter(period: str) -> str:
    """`2026Q2` -> `Q2'26`, the axis label the rest of the site uses."""
    return f"{period[4:]}'{period[2:4]}"


def quarter_parts(period: str) -> tuple[int, int]:
    """`2026Q2` -> (2026, 2)."""
    return int(period[:4]), int(period[5])


def quarter_before(period: str, back: int = 1) -> str:
    year, number = quarter_parts(period)
    index = year * 4 + number - 1 - back
    return f"{index // 4}Q{index % 4 + 1}"


def half_of_quarter(period: str) -> str:
    """`2026Q2` -> `H1 2026`: the half whose release carries this quarter."""
    year, number = quarter_parts(period)
    return f"H{1 if number <= 2 else 2} {year}"


def half_parts(half: str) -> tuple[int, int]:
    """`H2 2024` -> (2, 2024)."""
    return int(half[1]), int(half.split()[1])


def half_cn(half: str) -> str:
    """`H2 2024` -> `2024 年下半年`."""
    number, year = half_parts(half)
    return f"{year} 年{'上' if number == 1 else '下'}半年"


def closes_half(period: str, half: str) -> bool:
    """True when this quarter is the last quarter of `half` (Q2 closes H1, Q4 closes H2)."""
    year, number = quarter_parts(period)
    return number in (2, 4) and half == f"H{number // 2} {year}"


def month_cn(date: str) -> str:
    """`2026-04-13` -> `四月`."""
    return f"{cn_ordinal(int(date[5:7]))}月"


# ── number formatting ────────────────────────────────────────────────────────
def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100.0


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def rounded(values, digits: int = 6):
    return [None if v is None else round(v, digits) for v in values]


def cn_share(share: float) -> str:
    """The nearest simple fraction in words: 0.667 -> 「三分之二」, 0.5 -> 「一半」."""
    candidates = [(n, d) for d in range(2, 6) for n in range(1, d) if gcd(n, d) == 1]
    n, d = min(candidates, key=lambda nd: abs(share - nd[0] / nd[1]))
    return "一半" if (n, d) == (1, 2) else f"{cn_ordinal(d)}分之{cn_ordinal(n)}"


def unit_value(value: float, unit: str) -> str:
    """A call statement's number in the unit it was said in: −80bp, −1pp, +3%."""
    suffix = {"bps": "bp", "pp": "pp", "pct": "%"}[unit]
    return minus_sign(f"{value:+.0f}{suffix}")


def spaced(left: str, right: str) -> str:
    """Join two fragments with the space this site puts between CJK and Latin or digits."""
    if not left or not right:
        return left + right
    if left[-1] in "（）「」：，、—" or right[0] in "（）「」：，。、—":
        return left + right
    return left + (" " if left[-1].isascii() != right[0].isascii() else "") + right


def stores_text(value: float) -> str:
    return f"{value:,.0f} 家"


def kpi_unit_text(unit: str, value: float) -> str:
    """Store counts are counts: the shared `million` format printed 1,832 stores as `1832M`."""
    return stores_text(value) if unit == "stores" else unit_text(unit, value)


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


# ── what the page computes ───────────────────────────────────────────────────
def derived(staging: dict) -> dict:
    """Everything the page computes, in one place, from the staged series."""
    long_q = staging["long_quarters"]
    rev = staging["quarterly_revenue_eur_m"]
    window = staging["quarters"]
    start = long_q.index(window[0])

    # Reported year-on-year needs the same quarter one year back, which is why
    # the staged revenue table runs four quarters longer than the window.
    reported_yoy = [pct_change(rev["total"][i], rev["total"][i - 4])
                    for i in range(start, len(long_q))]
    div_reported_yoy = {
        d: [pct_change(rev[d][i], rev[d][i - 4]) for i in range(start, len(long_q))]
        for d in DIVS
    }

    org_q = staging["organic_quarters"]
    org_start = org_q.index(window[0])
    organic = {k: v[org_start:] for k, v in staging["organic_growth_pct"].items()}

    # The gap between the two growth rates is the currency-plus-perimeter drag.
    # LVMH publishes the split only at the half-year, so the quarterly figure is
    # a residual and is labelled as one everywhere it appears.
    gap = [organic["total"][i] - reported_yoy[i] for i in range(len(window))]

    # "Other activities and eliminations" is taken as the residual against the
    # published group total so the stack closes; the company's own printed
    # figure differs by at most EUR 1M and is carried in the audit table.
    other = [rev["total"][i] - sum(rev[d][i] for d in DIVS)
             for i in range(len(long_q))]

    flg_share = [rev["fashion_leather"][i] / rev["total"][i] * 100
                 for i in range(start, len(long_q))]

    halves = staging["halves"]
    hrev = staging["half_revenue_eur_m"]
    hpro = staging["half_pro_eur_m"]
    half_margin = [hpro["total"][i] / hrev["total"][i] * 100 for i in range(len(halves))]
    div_half_margin = {d: [hpro[d][i] / hrev[d][i] * 100 for i in range(len(halves))]
                       for d in DIVS}

    # The seasonal shape the semi-annual disclosure is the only way to see: every
    # complete year on the page, H1 against H2.
    pairs = []
    for i in range(0, len(halves) - 1):
        if halves[i].startswith("H1") and halves[i + 1] == f"H2 {halves[i].split()[1]}":
            pairs.append({
                "year": halves[i].split()[1],
                "h1": i, "h2": i + 1,
                "rev_h1": hrev["total"][i], "rev_h2": hrev["total"][i + 1],
                "margin_h1": half_margin[i], "margin_h2": half_margin[i + 1],
            })
    h2_bigger = sum(1 for p in pairs if p["rev_h2"] > p["rev_h1"])
    h2_thinner = sum(1 for p in pairs if p["margin_h2"] < p["margin_h1"])

    cash = staging["half_cash_eur_m"]
    capex_intensity = [cash["capex"][i] / _half_revenue(staging, staging["cash_halves"][i]) * 100
                       for i in range(len(staging["cash_halves"]))]

    return {
        "reported_yoy": reported_yoy,
        "div_reported_yoy": div_reported_yoy,
        "organic": organic,
        "gap": gap,
        "other": other,
        "flg_share": flg_share,
        "half_margin": half_margin,
        "div_half_margin": div_half_margin,
        "half_pairs": pairs,
        "h2_bigger": h2_bigger,
        "h2_thinner": h2_thinner,
        "capex_intensity": capex_intensity,
    }


def _half_revenue(staging: dict, half: str) -> float:
    return staging["half_revenue_eur_m"]["total"][staging["halves"].index(half)]


def year_ago_half(halves: list[str], half: str) -> int | None:
    """Index of the same half one year earlier, or None if the series does not reach it."""
    number, year = half_parts(half)
    label = f"H{number} {year - 1}"
    return halves.index(label) if label in halves else None


def full_year_margin(staging: dict, year: int) -> float | None:
    """A complete year's operating margin from its two halves, or None."""
    halves = staging["halves"]
    first, second = f"H1 {year}", f"H2 {year}"
    if first not in halves or second not in halves:
        return None
    hrev = staging["half_revenue_eur_m"]["total"]
    hpro = staging["half_pro_eur_m"]["total"]
    i, j = halves.index(first), halves.index(second)
    return (hpro[i] + hpro[j]) / (hrev[i] + hrev[j]) * 100


def printed_margin(staging: dict, half: str, key: str) -> float | None:
    """The margin the company printed for this half and division, if it printed one."""
    return staging["half_margin_company_printed_pct"].get(half, {}).get(key)


def shown_margin(staging: dict, der: dict, index: int, key: str) -> float:
    """The margin the text quotes: the company's printed figure where there is one.

    The page recomputes every divisional margin as profit over revenue so the
    seven halves are on one basis, and the charts draw those. But where the
    company printed a figure and the recomputation rounds differently (Perfumes
    & Cosmetics H1 2026: 417 / 3,914 = 10.65%, printed 10.6%), a sentence that
    quotes the margin quotes the company's.
    """
    half = staging["halves"][index]
    printed = printed_margin(staging, half, key)
    if printed is not None:
        return printed
    return der["half_margin"][index] if key == "total" else der["div_half_margin"][key][index]


def half_components(staging: dict) -> dict | None:
    """The company's organic / perimeter / currency / reported split for the latest half."""
    return staging["half_growth_components_pct"].get(staging["halves"][-1])


def story_values(staging: dict, der: dict, call: dict | None) -> dict[str, str]:
    """The computed numbers a story sentence may name (see `board.fill_story`)."""
    org = der["organic"]
    values: dict[str, str] = {}
    for key in DIVS + ["total"]:
        values[f"now:{key}"] = signed(org[key][-1], 0)
        values[f"prior:{key}"] = signed(org[key][-2], 0)
        values[f"level:{key}"] = f"{abs(org[key][-1]):.0f}%"
    components = half_components(staging)
    if components is not None:
        values["half_organic"] = signed(components["organic"], 0)
    for item in (call or {}).get("items", []):
        said, outcome = item.get("quantified"), item.get("outcome_value")
        if said is not None:
            values[f"said:{item['key']}"] = unit_value(said, item["quantified_unit"])
        if outcome is not None:
            values[f"outcome:{item['key']}"] = unit_value(outcome, item["outcome_unit"])
        if said is not None and outcome is not None and item["quantified_unit"] == item["outcome_unit"]:
            values[f"gap:{item['key']}"] = f"{abs(outcome - said):.0f}"
    return values


def kpi_entries(staging: dict, der: dict, kpi: dict) -> list[dict]:
    """The next thresholds with their current values read from the series.

    Each entry names the series value it tracks (``reads``); the value on the
    chart and in the table is that value, so a roll cannot leave last quarter's
    reading beside this quarter's threshold.
    """
    def current(reads: str) -> float:
        kind, _, key = reads.partition(".")
        if kind == "organic":
            return der["organic"][key][-1]
        if kind == "half_margin":
            return der["half_margin"][-1] if key == "total" else der["div_half_margin"][key][-1]
        if kind == "gap":
            return der["gap"][-1]
        if kind == "stores":
            return staging["stores"][key][-1]
        raise KeyError(f"next_kpi entry reads an unknown series: {reads}")
    return [{**entry, "current": current(entry["reads"])} for entry in kpi["entries"]]


# ── section one: the record of what was said ─────────────────────────────────
def said_charts(staging: dict, der: dict, call: dict, values: dict) -> list[dict]:
    """The previous call's statements, settled by this quarter's release."""
    org = der["organic"]
    quarters = staging["quarters"]
    items = {item["key"]: item for item in call["items"]}
    lead = call["lead"]
    source_call = (f"原话逐字取自公司业绩电话会记录（{call['made_on']} 与 {call['settled_by']}），"
                   f"结算值取自 {call['settled_source']}。")

    plotted = [items[key] for key in call["score_order"]]
    checkable = [item["key"] for item in call["items"]
                 if item.get("quantified") is not None and item["verdict"] != "unverifiable"]
    if sorted(call["score_order"]) != sorted(checkable):
        raise ValueError("call_record.score_order must list exactly the quantified, checkable statements")
    unplotted = [item for item in call["items"]
                 if item.get("quantified") is not None and item["verdict"] == "unverifiable"]
    met = [item for item in plotted if item["verdict"] in ("met", "beat")]
    caveat = [item for item in plotted if item["verdict"] == "caveat_held"]
    missed = [item for item in plotted if item["verdict"] == "missed"]

    def in_pp(value: float, unit: str) -> float:
        return value / 100 if unit == "bps" else value

    def actual(item: dict) -> float:
        """What the release printed; a statement about a series value reads the series."""
        kind, _, key = item.get("reads", "").partition(".")
        if kind == "organic":
            return org[key][-1]
        return in_pp(item["outcome_value"], item["outcome_unit"])

    verdicts = [f"{cn_count(len(met))}条兑现"] if met else []
    if caveat:
        verdicts.append(f"{cn_count(len(caveat))}条靠它自己预留的余地兑现")
    if missed:
        verdicts.append(f"{cn_count(len(missed))}条未兑现")

    note = f"{cn_count(len(plotted))}条里{cn_count(len(met))}条落地：" if met else ""
    note += "，".join(fill_story(item["score_note"], values) for item in met) + ("。" if met else "")
    position = len(met)
    for item in caveat:
        position += 1
        note += f"<b>第{cn_ordinal(position)}条要单独读。</b>" + fill_story(item["score_note"], values)
    for item in missed:
        position += 1
        note += f"<b>第{cn_ordinal(position)}条没有兑现。</b>" + fill_story(item["score_note"], values)
    for item in unplotted:
        position += 1
        note += f"第{cn_ordinal(position)}条（{item['score_topic']}）" + fill_story(item["score_note"], values)

    return [
        {
            "ref": "EX_SAID",
            "kind": "grouped_bars",
            "title": fill_story(lead["title"], values),
            "xlabels": [DIV_NAMES[d] for d in DIVS] + ["集团合计"],
            "groups": [
                {"name": f"{display_period(quarters[-2])} 有机增速", "color": "BLUE",
                 "values": rounded([org[d][-2] for d in DIVS] + [org["total"][-2]])},
                {"name": f"{display_period(quarters[-1])} 有机增速", "color": "NAVY",
                 "values": rounded([org[d][-1] for d in DIVS] + [org["total"][-1]])},
            ],
            "bar_labels": True,
            "fmt": "pct0", "label_fmt": "pct0", "yfmt": "pct0",
            "ylab": "有机增速",
            "note": ("<b>LVMH 不发布任何数字指引。</b>它对未来的全部陈述都是电话会上的句子，"
                     "所以这一节能核的只有句子。" + fill_story(lead["note"], values)
                     + f"完整{cn_count(len(call['items']))}条记录见核对表 {{TBL_SAID}}。"),
            "src_extra": source_call,
        },
        {
            "ref": "EX_SCORE",
            "kind": "grouped_bars",
            "title": f"{cn_count(len(plotted))}条能落到数字上的陈述：" + "，".join(verdicts),
            "xlabels": [item["chart_label"] for item in plotted],
            "xrot": 0,
            "groups": [
                {"name": "上季电话会所述", "color": "GOLD",
                 "values": rounded([in_pp(item["quantified"], item["quantified_unit"])
                                    for item in plotted])},
                {"name": "本季实际", "color": "NAVY",
                 "values": rounded([actual(item) for item in plotted])},
            ],
            "bar_labels": True,
            "fmt": "pp1", "label_fmt": "pp1", "yfmt": "pp1",
            "ylab": "百分点",
            "note": note,
            "src_extra": source_call,
        },
    ]


# ── section two: the quarter ─────────────────────────────────────────────────
def quarter_charts(staging: dict, der: dict, labels: list[str],
                   story: dict | None, hstory: dict | None) -> list[dict]:
    rev = staging["quarterly_revenue_eur_m"]
    long_q = staging["long_quarters"]
    quarters = staging["quarters"]
    n = len(quarters)
    start = long_q.index(quarters[0])
    window_rev = {k: v[start:] for k, v in rev.items()}
    org = der["organic"]
    rep, gap = der["reported_yoy"], der["gap"]
    now_label, prior_label = display_period(quarters[-1]), display_period(quarters[-2])

    rep_q1, rep_q2 = rep[-2], rep[-1]
    gap_q1, gap_q2 = gap[-2], gap[-1]
    org_step = org["total"][-1] - org["total"][-2]
    rep_step = rep_q2 - rep_q1
    gap_step = gap_q1 - gap_q2
    perimeter = (story or {}).get("perimeter")

    # ── the quarterly revenue bar ──
    if rep_q2 >= 0 and all(v < 0 for v in rep[:-1]):
        rev_lead = f"<b>报告口径的收入{cn_count(n)}季里第一次不再下滑</b>："
    elif rep_q2 >= 0:
        rev_lead = "<b>报告口径的收入本季不再下滑</b>："
    else:
        rev_lead = "<b>报告口径的收入本季仍在下滑</b>："
    if org["total"][-1] == org["total"][-2]:
        organic_move = f"同期有机增速持平在 {signed(org['total'][-1], 0)}。"
    else:
        organic_move = (("但同期有机增速只从 " if org_step < rep_step else "同期有机增速从 ")
                        + signed(org["total"][-2], 0) + " 走到 " + signed(org["total"][-1], 0) + "。")
    if gap_q2 < gap_q1:
        gap_move = f"它从上季的 {gap_q1:.2f}pp 收窄到本季的 {gap_q2:.2f}pp"
    else:
        gap_move = f"它从上季的 {gap_q1:.2f}pp 变为本季的 {gap_q2:.2f}pp"
    rev_chart = {
        "ref": "EX_REV",
        "kind": "gs_bar",
        "title": (f"集团季度收入 €{window_rev['total'][-1]:,.0f}M，"
                  f"报告口径同比 {signed(rep_q2)}，有机 {signed(org['total'][-1], 0)}"),
        "xlabels": labels,
        "values": rounded(window_rev["total"], 0),
        "legend": "季度收入",
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "€M",
        "ylab2": "报告口径同比",
        "yoy": {"name": "报告口径同比 (RHS)", "values": rounded(rep),
                "color": "RED", "yfmt": "pct0"},
        "note": (rev_lead + "本季 " + signed(rep_q2) + "，上季 " + signed(rep_q1) + "。"
                 + organic_move + "两条线之间的差是汇率加并表，"
                 + gap_move + " —— 见下一张。"),
        "src_extra": SOURCE_QUARTER,
    }

    # ── the revenue bridge: why the reported rate moved ──
    # The perimeter leg is the only piece of the gap the company quantifies by
    # quarter (at group level, on the call); the currency leg is the remainder.
    # Without that figure the bridge shows the gap as one leg.
    if rep_step > 0:
        headline_move = f"报告口径同比改善了 {rep_step:.2f}pp"
    else:
        headline_move = f"报告口径同比变动 {rep_step:+.2f}pp"
    if rep_step > 0 and gap_step > 0:
        bridge_title = f"{headline_move}，其中 {gap_step:.2f}pp 不是需求"
    else:
        bridge_title = f"{headline_move}：有机 {org_step:+.2f}pp，汇率与并表 {gap_step:+.2f}pp"
    if perimeter is not None:
        perimeter_step = perimeter["quarter_pp"] - perimeter["prior_quarter_pp"]
        currency_step = gap_step - perimeter_step
        bridge_labels = [f"{prior_label} 报告同比", "有机增速变动", "并表影响变动", "汇率影响变动 D",
                         f"{now_label} 报告同比"]
        bridge_values = [rep_q1, org_step, perimeter_step, currency_step, None]
        biggest_is_currency = currency_step > max(org_step, perimeter_step)
    else:
        bridge_labels = [f"{prior_label} 报告同比", "有机增速变动", "汇率与并表变动 D",
                         f"{now_label} 报告同比"]
        bridge_values = [rep_q1, org_step, gap_step, None]
        biggest_is_currency = False
    bridge_note = ""
    if rep_step > 0 and biggest_is_currency:
        bridge_note += "<b>本季报表上最大的一笔改善来自汇率，不是来自需求。</b>"
    bridge_note += f"报告口径同比从 {signed(rep_q1)} 走到 {signed(rep_q2)}，"
    if rep_step > 0 and 0 < gap_step < rep_step and org_step < gap_step:
        bridge_note += (f"改善 {rep_step:.2f}pp；其中有机增速只贡献 {org_step:+.2f}pp，"
                        f"剩下的 {gap_step:.2f}pp 来自汇率与并表这条线 —— "
                        f"占改善幅度的 {gap_step / rep_step * 100:.0f}%。")
    else:
        bridge_note += (f"变动 {rep_step:+.2f}pp；有机增速贡献 {org_step:+.2f}pp，"
                        f"汇率与并表这条线贡献 {gap_step:+.2f}pp。")
    if perimeter is not None:
        bridge_note += (f"并表那一腿取公司在本季电话会上给的集团口径 "
                        f"{unit_value(perimeter['quarter_pp'], 'pp')}（{perimeter['reason']}）"
                        + (f"，上季为 {unit_value(perimeter['prior_quarter_pp'], 'pp')}"
                           if perimeter["prior_quarter_pp"] else "")
                        + "，汇率腿是残值，标 D：")
    else:
        bridge_note += "汇率与并表只能合成一条残值腿，标 D："
    bridge_note += "<b>公司按季只给有机增速，不给分季度的汇率与并表拆分</b>"
    components = half_components(staging)
    if components is not None and closes_half(quarters[-1], staging["halves"][-1]):
        legs = components["organic"] + components["perimeter"] + components["currency"]
        bridge_note += ("，半年度口径它给的是「有机 " + signed(components["organic"], 0)
                        + "、并表 " + unit_value(components["perimeter"], "pct")
                        + "、汇率 " + unit_value(components["currency"], "pct") + "」")
        if legs != components["reported"]:
            bridge_note += (f"，而这三个取整后的数相加是 {unit_value(legs, 'pct')}，"
                            f"公司自己印的报告口径合计是 {unit_value(components['reported'], 'pct')} —— "
                            "本页因此不把公司印的三个整数当成一个能闭合的等式来用。")
        else:
            bridge_note += "，这一次三个取整后的数恰好相加闭合到公司印的报告口径合计。"
    else:
        bridge_note += "。"
    bridge = {
        "ref": "EX_BRIDGE_REV",
        "kind": "bridge_bar",
        "title": bridge_title,
        "xlabels": bridge_labels,
        "stacks": [{"name": "环比拆解（pp）", "color": "NAVY", "values": rounded(bridge_values)}],
        "net": {"name": f"{now_label} 报告口径同比",
                "values": [None] * (len(bridge_labels) - 1) + [round(rep_q2, 6)]},
        "fmt": "pp1", "yfmt": "pp1", "label_fmt": "pp1",
        "ylab": "百分点",
        "note": bridge_note,
        "src_extra": SOURCE_QUARTER + (f" 集团口径的并表影响取自 {perimeter['said_on']} 电话会。"
                                       if perimeter is not None else ""),
    }

    # ── the two growth rates side by side ──
    negative = [i for i, v in enumerate(gap) if v < 0]
    turn = negative[0] if len(negative) == 1 else None
    pattern = (turn is not None and turn < n - 2
               and all(gap[i + 1] > gap[i] for i in range(turn, n - 2))
               and gap[-1] < gap[-2])
    if pattern:
        gap_story = (f"两条线之差在 {quarters[turn]} 还是负的（汇率是顺风），此后一路扩大到 "
                     f"{quarters[-2]} 的 {gap[-2]:.2f}pp，本季骤缩到 {gap[-1]:.2f}pp。")
        span_from = turn
    else:
        low, high = gap.index(min(gap)), gap.index(max(gap))
        gap_story = (f"两条线之差{cn_count(n)}季里最低是 {quarters[low]} 的 {gap[low]:.2f}pp，"
                     f"最高是 {quarters[high]} 的 {gap[high]:.2f}pp，本季 {gap[-1]:.2f}pp。")
        span_from = 0
    wider = (max(gap[span_from:]) - min(gap[span_from:]) > max(org["total"][span_from:]) - min(org["total"][span_from:])
             and max(gap) - min(gap) > max(org["total"]) - min(org["total"]))
    span_words = "过去" + cn_count(n - span_from) + "个季度" if span_from else cn_count(n) + "季"
    gaps_chart = {
        "ref": "EX_GAPS",
        "kind": "grouped_bars",
        "title": f"{cn_count(n)}季里报告口径与有机口径的两条增速：差额就是汇率加并表",
        "xlabels": labels,
        "groups": [
            {"name": "报告口径同比", "color": "RED", "values": rounded(rep)},
            {"name": "有机增速", "color": "NAVY", "values": rounded(org["total"])},
        ],
        "bar_labels": True,
        "fmt": "pct1", "label_fmt": "pct0", "yfmt": "pct0",
        "ylab": "同比",
        "note": (gap_story
                 + (f"<b>这条差额{span_words}的振幅比有机增速本身还大</b>：" if wider else
                    f"这条差额{span_words}的振幅没有有机增速本身大：")
                 + f"有机增速{cn_count(n)}季在 {min(org['total']):.0f}% 到 {max(org['total']):.0f}% 之间，"
                 f"差额在 {min(gap):.1f}pp 到 {max(gap):.1f}pp 之间。"
                 "读这家公司的报表增速，先看这条差额。"),
        "src_extra": SOURCE_QUARTER,
    }

    # ── divisional mix ──
    printed_other = staging["quarterly_revenue_other_published_eur_m"]
    residual_gaps = [abs(der["other"][start + i] - printed_other[start + i]) for i in range(n)]
    off = [g for g in residual_gaps if g]
    other_words = (f"与公司自己印的那个数在{cn_count(n)}季里有{cn_count(len(off))}季差 €{max(off):,.0f}M，逐季列在核对表里。"
                   if off else f"与公司自己印的那个数在{cn_count(n)}季里逐季一致，列在核对表里。")
    flg = der["flg_share"]
    wj_first = window_rev["watches_jewelry"][0] / window_rev["total"][0] * 100
    wj_last = window_rev["watches_jewelry"][-1] / window_rev["total"][-1] * 100
    flg_lead = "时装与皮具仍是集团近一半的收入" if 40 <= flg[-1] < 50 else f"时装与皮具占集团收入 {flg[-1]:.1f}%"
    mix = {
        "ref": "EX_MIX",
        "kind": "stacked_dual",
        # The first bar of an n-quarter window is n - 1 quarters before the last.
        "title": (f"分部收入结构：时装与皮具占 {flg[-1]:.1f}%，"
                  f"{cn_count(n - 1)}季前是 {flg[0]:.1f}%"),
        "xlabels": labels,
        "stacks": [
            {"name": "时装与皮具", "color": "NAVY",
             "values": rounded(window_rev["fashion_leather"], 0)},
            {"name": "精品零售", "color": "MBLUE",
             "values": rounded(window_rev["selective_retailing"], 0)},
            {"name": "手表与珠宝", "color": "BLUE",
             "values": rounded(window_rev["watches_jewelry"], 0)},
            {"name": "香水与化妆品", "color": "GREEN",
             "values": rounded(window_rev["perfumes_cosmetics"], 0)},
            {"name": "葡萄酒与烈酒", "color": "GOLD",
             "values": rounded(window_rev["wines_spirits"], 0)},
            {"name": "其他与抵销 D", "color": "GRAY",
             "values": rounded(der["other"][start:], 0)},
        ],
        "line": {"name": "时装与皮具占收入 (RHS)", "color": "RED",
                 "values": rounded(flg), "yfmt": "pct1", "ymax": 100},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "€M", "ylab2": "时装与皮具占比",
        "note": (flg_lead + ("，但它的占比" if flg[-1] < flg[0] else "，它的占比") + cn_count(n) + "季里"
                 + ("降了 " if flg[-1] < flg[0] else "升了 ")
                 + f"{abs(flg[0] - flg[-1]):.1f}pp，"
                 + (f"而手表与珠宝从 {wj_first:.1f}% " + ("升到 " if wj_last > wj_first else "降到 ")
                    + f"{wj_last:.1f}%。" if f"{wj_first:.1f}" != f"{wj_last:.1f}" else
                    f"而手表与珠宝持平在 {wj_last:.1f}%。")
                 + "「其他与抵销」一行按「集团合计减五个分部」取残值以让堆叠闭合，" + other_words),
        "src_extra": SOURCE_QUARTER,
    }

    # ── divisional organic growth ──
    now = {d: org[d][-1] for d in DIVS}
    top, bottom = max(DIVS, key=now.get), min(DIVS, key=now.get)
    spread = now[top] - now[bottom]
    long_org = staging["organic_growth_pct"]

    def run_before_last(key: str) -> int:
        """How many quarters before the latest were non-positive, counted back without a break."""
        values = long_org[key]
        count = 0
        for value in reversed(values[:-1]):
            if value > 0:
                break
            count += 1
        return count

    turned = [(run_before_last(d), d) for d in DIVS if now[d] > 0 and run_before_last(d) >= 2]
    lead_sentence = ""
    if turned:
        run, key = max(turned)
        began = staging["organic_quarters"][-1 - run]
        lead_sentence = (f"<b>{DIV_NAMES[key]}本季 {signed(now[key], 0)}，是 {began} 以来"
                         f"{cn_count(run)}个非正季度之后的第一个正数。</b>")
    divorg = {
        "ref": "EX_DIVORG",
        "kind": "lines_endlabels",
        "title": f"{cn_count(len(DIVS))}个分部的有机增速：本季分化到 {spread:.0f} 个百分点宽",
        "xlabels": labels,
        "series": [
            {"name": "手表与珠宝", "values": rounded(org["watches_jewelry"]), "color": "BLUE"},
            {"name": "精品零售", "values": rounded(org["selective_retailing"]), "color": "MBLUE"},
            {"name": "葡萄酒与烈酒", "values": rounded(org["wines_spirits"]), "color": "GOLD"},
            {"name": "时装与皮具", "values": rounded(org["fashion_leather"]), "color": "NAVY"},
            {"name": "香水与化妆品", "values": rounded(org["perfumes_cosmetics"]), "color": "GREEN"},
        ],
        "fmt": "pct0", "yfmt": "pct0", "label_fmt": "pct0",
        "end_label": True,
        "ylab": "有机增速",
        "note": (lead_sentence
                 + f"同一节里{DIV_NAMES[top]} {signed(now[top], 0)}、{DIV_NAMES[bottom]} {signed(now[bottom], 0)}，"
                 f"两端相差 {spread:.0f} 个百分点。"
                 + (story["divorg_note"] if story else "")),
        "src_extra": SOURCE_QUARTER,
    }

    # ── the one profit decomposition that exists: half on half ──
    hpro = staging["half_pro_eur_m"]
    halves = staging["halves"]
    i_now = len(halves) - 1
    i_prior = year_ago_half(halves, halves[-1])
    legs = [(d, hpro[d][i_now] - hpro[d][i_prior]) for d in DIVS]
    other_leg = (hpro["total"][i_now] - hpro["total"][i_prior]
                 - sum(delta for _, delta in legs))
    change = hpro["total"][i_now] - hpro["total"][i_prior]
    worst_key, worst = min(legs, key=lambda kv: kv[1])
    others = [(d, delta) for d, delta in legs if d != worst_key]
    best = max(delta for _, delta in others)
    main = [d for d, delta in sorted(others, key=lambda kv: -kv[1])
            if delta > 0 and delta >= best / 2]
    main_words = ("，其中" + "与".join(DIV_NAMES[d] for d in main) + "各贡献了正的双位数百万欧元"
                  if main and all(10 <= dict(others)[d] < 100 for d in main) else "")
    parts_sum = sum(hpro[d][i_now] for d in DIVS) + hpro["other"][i_now]
    published = staging["half_pro_published_total_eur_m"].get(halves[-1])
    rounding = ""
    if published is not None and published != parts_sum:
        rounding = (f"末腿含公司印的集团合计与五个分部相加之间 €{abs(published - parts_sum):,.0f}M 的取整差"
                    f"（分部相加为 €{parts_sum:,.0f}M，公司印的是 €{published:,.0f}M）。")
    if worst < 0:
        pro_title = (f"半年经营利润 €{hpro['total'][i_prior]:,.0f}M → €{hpro['total'][i_now]:,.0f}M："
                     f"{DIV_NAMES[worst_key]}一个分部就拿走 €{-worst:,.0f}M")
    else:
        pro_title = f"半年经营利润 €{hpro['total'][i_prior]:,.0f}M → €{hpro['total'][i_now]:,.0f}M"
    bridge_pro = {
        "ref": "EX_BRIDGE_PRO",
        "kind": "bridge_bar",
        "title": pro_title,
        "xlabels": [f"{halves[i_prior]} 经营利润"] + [DIV_NAMES[d] for d, _ in legs]
                   + ["其他、抵销与舍入 D", f"{halves[i_now]} 经营利润"],
        "stacks": [{"name": "分部贡献（€M）", "color": "NAVY",
                    "values": rounded([hpro["total"][i_prior]]
                                      + [delta for _, delta in legs]
                                      + [other_leg, None], 0)}],
        "net": {"name": f"{halves[i_now]} 经营利润（净额）",
                "values": [None] * (len(legs) + 2) + [round(float(hpro["total"][i_now]), 6)]},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "€M（半年）",
        "note": ("<b>这是半年图，不是季度图 —— 公司不按季披露分部利润。</b>"
                 f"集团经营利润同比 {'−' if change < 0 else '+'}€{abs(change):,.0f}M，"
                 + (f"其中{DIV_NAMES[worst_key]}一个分部 −€{-worst:,.0f}M，" if worst < 0 else "")
                 + ((hstory or {}).get("profit_note", "") if worst < 0 else "")
                 + f"另外{cn_count(len(others))}个分部合计 {sum(d for _, d in others):+,.0f}"
                 + main_words + "。" + rounding),
        "src_extra": SOURCE_HALF,
    }
    return [rev_chart, bridge, gaps_chart, mix, divorg, bridge_pro]


def trailing_run(flags: list[bool]) -> int:
    """How many of the most recent readings are True, counting back from the end."""
    run = 0
    for flag in reversed(flags):
        if not flag:
            break
        run += 1
    return run


def is_a_recent_habit(flags: list[bool], least: int = 2) -> bool:
    """True when the trailing streak is long and what came before it was not.

    A claim that holds over the last few complete years and almost never before
    them is a regime, not a property of the business; the page says which.
    """
    run = trailing_run(flags)
    earlier = flags[:len(flags) - run]
    return run >= least and bool(earlier) and sum(earlier) * 3 <= len(earlier)


# ── section three: what only the half-year shows ─────────────────────────────
def half_charts(staging: dict, der: dict, hstory: dict | None) -> list[dict]:
    halves = staging["halves"]
    hrev = staging["half_revenue_eur_m"]
    cash_halves = staging["cash_halves"]
    cash = staging["half_cash_eur_m"]
    pairs = der["half_pairs"]
    stores = staging["stores"]
    store_dates = staging["store_dates"]
    store_labels = [d[:7].replace("-", " 年 ") + " 月" for d in store_dates]
    quarters = staging["quarters"]
    latest_half = halves[-1]
    i_now = len(halves) - 1
    i_prior = year_ago_half(halves, latest_half)

    # ── seasonality ──
    thin_flags = [p["margin_h2"] < p["margin_h1"] for p in pairs]
    rev_every = bool(pairs) and der["h2_bigger"] == len(pairs)
    every = rev_every and der["h2_thinner"] == len(pairs)
    # How far back the thinner-second-half streak runs, and how often it happened
    # before that streak began. Over three complete years the two halves of this
    # sentence were the same sentence; over ten they are not.
    run = trailing_run(thin_flags)
    earlier = thin_flags[:len(pairs) - run]
    n_years = cn_count(len(pairs))
    if every:
        season_title = (f"{n_years}个完整年度里，下半年每一次都是收入更高、利润率更低 "
                        f"（{der['h2_bigger']}/{len(pairs)} 与 {der['h2_thinner']}/{len(pairs)}）")
    elif rev_every:
        season_title = (f"{n_years}个完整年度里，下半年收入每一次都更高（{der['h2_bigger']}/{len(pairs)}），"
                        f"而利润率更低只有 {der['h2_thinner']} 次")
    else:
        season_title = (f"{n_years}个完整年度里，下半年收入更高的 {der['h2_bigger']} 次、"
                        f"利润率更低的 {der['h2_thinner']} 次")
    season_note = "<b>本页最该被记住的一张，也是只有半年度披露才画得出来的一张。</b>"
    if len(pairs) <= 4:
        season_note += "；".join(f"{p['year']} 年下半年收入比上半年"
                                f"{'多' if p['rev_h2'] >= p['rev_h1'] else '少'} "
                                f"€{abs(p['rev_h2'] - p['rev_h1']):,.0f}M，利润率"
                                f"{'低' if p['margin_h2'] < p['margin_h1'] else '高'} "
                                f"{abs(p['margin_h1'] - p['margin_h2']):.2f}pp"
                                for p in pairs) + "。"
    elif pairs:
        thin_gap = min((p for p, f in zip(pairs, thin_flags) if f),
                       key=lambda p: p["margin_h1"] - p["margin_h2"], default=None)
        rev_gaps = sorted(pairs, key=lambda p: p["rev_h2"] - p["rev_h1"])
        how_often = "每一次" if rev_every else f"{der['h2_bigger']} 次"
        season_note += (f"收入那一半是结构性的：{len(pairs)} 个完整年度里下半年{how_often}都更高，"
                        f"从 {rev_gaps[0]['year']} 年的 €{rev_gaps[0]['rev_h2'] - rev_gaps[0]['rev_h1']:,.0f}M "
                        f"到 {rev_gaps[-1]['year']} 年的 €{rev_gaps[-1]['rev_h2'] - rev_gaps[-1]['rev_h1']:,.0f}M。"
                        f"利润率那一半不是：更薄只有 {der['h2_thinner']}/{len(pairs)} 次"
                        + (f"，最小的一次是 {thin_gap['year']} 年的 "
                           f"{thin_gap['margin_h1'] - thin_gap['margin_h2']:.2f}pp" if thin_gap else "")
                        + "。")
    if every:
        season_note += (f"{n_years}年{n_years}次，方向没有例外："
                        "<b>季节性更大的那半年，利润率反而更薄</b>。")
    elif is_a_recent_habit(thin_flags):
        first = pairs[len(pairs) - run]
        season_note += (f"<b>「季节性更大的那半年利润率反而更薄」是最近{cn_count(run)}年才成立的</b>："
                        f"{first['year']}–{pairs[-1]['year']} 连续{cn_count(run)}次更薄，"
                        f"而在那之前的{cn_count(len(earlier))}年里只有 {sum(earlier)} 次。"
                        "把它当成这家公司的固有季节性，会把一段还不到一个周期长的历史读成结构。")
    widest = max(pairs, key=lambda p: abs(p["margin_h2"] - p["margin_h1"]), default=None)
    h1_margins = [p["margin_h1"] for p in pairs]
    if widest is not None and len(pairs) > 4:
        season_note += (f"差得最远的是 {widest['year']} 年，下半年"
                        f"{'高' if widest['margin_h2'] > widest['margin_h1'] else '低'} "
                        f"{abs(widest['margin_h2'] - widest['margin_h1']):.2f}pp"
                        + (f"——那一年的上半年利润率 {widest['margin_h1']:.2f}% 是"
                           f"{n_years}个上半年里最低的一个。"
                           if widest["margin_h1"] == min(h1_margins) else "。"))
    prior_year = half_parts(latest_half)[1] - 1
    prior_fy = full_year_margin(staging, prior_year)
    if every and latest_half.startswith("H1") and prior_fy is not None:
        prior_h1 = halves.index(f"H1 {prior_year}")
        season_note += (f"所以本半年的 {der['half_margin'][-1]:.2f}% 不是全年运行率 —— "
                        f"上一整年的全年数是 {prior_fy:.1f}%，而那一年的上半年是 "
                        f"{der['half_margin'][prior_h1]:.2f}%。"
                        f"把上半年利润率年化，这家公司{n_years}年会错{n_years}次。")
    season = {
        "ref": "EX_SEASON",
        "kind": "bar_line_dual",
        "title": season_title,
        "xlabels": halves,
        "bar": {"name": "半年收入", "values": rounded(hrev["total"], 0), "color": "NAVY"},
        "line": {"name": "半年经营利润率 (RHS)", "values": rounded(der["half_margin"]),
                 "color": "RED", "yfmt": "pct1"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "€M（半年）", "ylab2": "半年经营利润率",
        "note": season_note,
        "src_extra": SOURCE_HALF,
    }

    # ── divisional margins ──
    margins = der["div_half_margin"]
    improved = sum(1 for d in DIVS if margins[d][-1] > margins[d][i_prior])
    last4 = halves[-4:]
    covered = (len(last4) == 4
               and half_of_quarter(quarters[0]) == last4[0] and quarter_parts(quarters[0])[1] in (1, 3)
               and closes_half(quarters[-1], last4[-1]))

    def change(key: str) -> float:
        """This half on the year-ago half, from the company's printed margins when both exist."""
        now_p, then_p = (printed_margin(staging, latest_half, key),
                         printed_margin(staging, halves[i_prior], key))
        if now_p is not None and then_p is not None:
            return now_p - then_p
        return margins[key][-1] - margins[key][i_prior]

    revenue_now = {d: staging["half_revenue_eur_m"][d][-1] for d in DIVS}
    biggest = max(DIVS, key=revenue_now.get)
    best = max(DIVS, key=change)
    lead = (f"{DIV_NAMES[biggest]} {shown_margin(staging, der, i_now, biggest):.1f}%"
            f"（同比 {change(biggest):+.1f}pp），")
    if best != biggest:
        lead += (f"{DIV_NAMES[best]} {shown_margin(staging, der, i_now, best):.1f}%"
                 f"（{change(best):+.1f}pp）是本半年最大的一笔改善。")
    else:
        lead = lead.rstrip("，") + "是本半年最大的一笔改善。"
    # Which divisions carry the thinner second half in every complete year --
    # checked division by division rather than said of all five.
    thinner = [d for d in DIVS if pairs and all(margins[d][p["h2"]] < margins[d][p["h1"]] for p in pairs)]
    # Over three complete years the exceptions could be named one by one; over
    # ten there are too many to name, so each division carries its own count.
    # The count is bounded by the number of divisions, the naming was not.
    thin_count = {d: sum(1 for p in pairs if margins[d][p["h2"]] < margins[d][p["h1"]]) for d in DIVS}
    if len(thinner) == len(DIVS):
        rhythm = "各分部利润率同时呈现下半年更薄的同一节奏"
    elif pairs:
        order = sorted(DIVS, key=lambda d: (-thin_count[d], DIV_NAMES[d]))
        rhythm = (f"下半年更薄不是{cn_count(len(DIVS))}个分部共同的节奏 —— "
                  f"{cn_count(len(pairs))}个完整年度里更薄的次数逐个分部是："
                  + "、".join(f"{DIV_NAMES[d]} {thin_count[d]} 次" for d in order)
                  + ("，其中" + "、".join(DIV_NAMES[d] for d in thinner) + "每年都薄"
                     if thinner else "，没有一个分部每年都薄"))
    else:
        rhythm = ""
    extreme = ""
    if thinner and latest_half.startswith("H1") and len(halves) >= 2:
        key = max(thinner, key=lambda d: margins[d][-1] / margins[d][-2])
        extreme = (f"{'，' if rhythm else ''}{DIV_NAMES[key]}尤其极端：{halves[-2]} 只有 {margins[key][-2]:.1f}%，"
                   f"{latest_half} 是 {shown_margin(staging, der, i_now, key):.1f}%")
    diffs = [(abs((der["half_margin"][halves.index(h)] if k == "total"
                   else margins[k][halves.index(h)]) - v), h, k)
             for h, row in staging["half_margin_company_printed_pct"].items() for k, v in row.items()]
    div_margin = {
        "ref": "EX_DIVMARGIN",
        "kind": "grouped_bars",
        "title": (f"分部半年经营利润率：本半年{cn_count(len(DIVS))}个分部里 {improved} 个同比走高，"
                  f"{len(DIVS) - improved} 个走低"),
        "xlabels": halves[-4:],
        "groups": [
            {"name": "时装与皮具", "color": "NAVY",
             "values": rounded(margins["fashion_leather"][-4:])},
            {"name": "葡萄酒与烈酒", "color": "GOLD",
             "values": rounded(margins["wines_spirits"][-4:])},
            {"name": "手表与珠宝", "color": "BLUE",
             "values": rounded(margins["watches_jewelry"][-4:])},
            {"name": "精品零售", "color": "MBLUE",
             "values": rounded(margins["selective_retailing"][-4:])},
            {"name": "香水与化妆品", "color": "GREEN",
             "values": rounded(margins["perfumes_cosmetics"][-4:])},
        ],
        "bar_labels": True,
        "fmt": "pct1", "label_fmt": "pct0", "yfmt": "pct0",
        "ylab": "半年经营利润率",
        "note": ((f"这{cn_count(len(last4))}个半年正好覆盖本页的{cn_count(len(quarters))}个季度 —— "
                  f"<b>同样的时间，只有{cn_count(len(last4))}个利润读数</b>。" if covered else "")
                 + lead
                 + rhythm + extreme + ("。" if rhythm or extreme else "")
                 + "本页图上的利润率按「分部经营利润 ÷ 分部收入」重算，"
                 + (f"与公司自己印的百分数最大差 {max(diffs)[0]:.2f}pp，两套数并列在核对表里。"
                    if diffs else "公司本期没有印分部利润率。")),
        "src_extra": SOURCE_HALF,
    }

    # ── cash and net debt ──
    nfd = staging["net_financial_debt_eur_m"]
    dates = staging["balance_dates"]
    rises = [nfd[i] > nfd[i - 1] for i in range(1, len(dates))
             if dates[i].endswith("-06-30") and dates[i - 1].endswith("-12-31")]
    falls = [nfd[i] < nfd[i - 1] for i in range(1, len(dates))
             if dates[i].endswith("-12-31") and dates[i - 1].endswith("-06-30")]
    cash_pairs = [(cash_halves[i], cash_halves[i + 1], cash["ofcf"][i], cash["ofcf"][i + 1])
                  for i in range(len(cash_halves) - 1)
                  if cash_halves[i].startswith("H1") and cash_halves[i + 1] == f"H2 {cash_halves[i].split()[1]}"]
    ratios = [h2 / h1 for _, _, h1, h2 in cash_pairs]
    cash_note = ""
    if cash_pairs and all(r > 1 for r in ratios):
        times = round(sum(ratios) / len(ratios))
        cash_note += (f"现金流的季节性和利润率正好相反：<b>下半年的自由现金流大约是上半年的"
                      f"{cn_count(times)}倍</b>（"
                      + "；".join(f"{b} €{v2:,.0f}M 对 {a} €{v1:,.0f}M"
                                  for a, b, v1, v2 in reversed(cash_pairs)) + "）。")
    if rises and all(rises) and falls and all(falls):
        cash_note += ("净负债因此每年 6 月抬头、12 月回落，"
                      + (f"{cn_count(len(rises))}个观测年都是这个形状 —— " if len(rises) >= 2 else
                         "观测到的一年就是这个形状 —— ")
                      + "主股息在上半年支付，营运资金也在上半年占用。")
    year_ago = dates.index(f"{int(dates[-1][:4]) - 1}{dates[-1][4:]}") if \
        f"{int(dates[-1][:4]) - 1}{dates[-1][4:]}" in dates else None
    cash_note += f"本期末净负债 €{nfd[-1]:,.0f}M，"
    if year_ago is not None:
        cash_note += (f"较去年同期{'少' if nfd[-1] < nfd[year_ago] else '多'} "
                      f"€{abs(nfd[year_ago] - nfd[-1]):,.0f}M，")
    cash_note += f"净负债对权益 {nfd[-1] / staging['equity_eur_m'][-1] * 100:.1f}%。"
    june_higher = bool(rises) and all(rises)
    cash_chart = {
        "ref": "EX_CASH",
        "kind": "bar_line_dual",
        "title": (f"半年经营自由现金流 €{cash['ofcf'][-1]:,.0f}M，"
                  + ("而净金融负债在每年 6 月都比前一个 12 月高" if june_higher
                     else f"期末净金融负债 €{nfd[-1]:,.0f}M")),
        "xlabels": cash_halves,
        "bar": {"name": "半年经营自由现金流", "values": rounded(cash["ofcf"], 0), "color": "NAVY"},
        "line": {"name": "期末净金融负债 (RHS)", "color": "RED",
                 "values": rounded(nfd, 0), "yfmt": "f0c"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "€M（半年）", "ylab2": "期末净金融负债",
        "note": cash_note,
        "src_extra": SOURCE_HALF,
    }

    # ── stores ──
    ago = store_dates.index(f"{int(store_dates[-1][:4]) - 1}{store_dates[-1][4:]}")
    asia_drop = stores["asia_ex_japan"][ago] - stores["asia_ex_japan"][-1]
    total_drop = stores["total"][ago] - stores["total"][-1]
    openers = sorted((key for key in STORE_KEYS[:-1] if key != "asia_ex_japan"
                      and stores[key][-1] > stores[key][ago]),
                     key=lambda key: stores[key][ago] - stores[key][-1])[:2]
    openers = [key for key in STORE_KEYS if key in openers]
    region_q = staging["region_quarters"]
    asia_growth = staging["region_organic_pct"]["asia_ex_japan"][-1]
    when = "本季" if region_q[-1] == quarters[-1] else compact_quarter(region_q[-1])
    if asia_drop > 0:
        store_title = (f"门店网络：亚洲（除日本）一年少了 {asia_drop} 家，同期集团总数"
                       + (f"只少了 {total_drop} 家" if 0 < total_drop < asia_drop else
                          f"{'少了' if total_drop > 0 else '多了'} {abs(total_drop)} 家"))
    else:
        store_title = (f"门店网络：亚洲（除日本）一年{'多了' if asia_drop < 0 else '持平'}"
                       f"{f' {-asia_drop} 家' if asia_drop < 0 else ''}")
    store_note = ("<b>店数只在半年度和全年披露，一年只有两个读数。</b>"
                  f"亚洲（除日本）从 {stores['asia_ex_japan'][ago]:,} 家"
                  f"{'降' if asia_drop > 0 else '变'}到 {stores['asia_ex_japan'][-1]:,} 家"
                  f"（{-asia_drop / stores['asia_ex_japan'][ago] * 100:.1f}%），")
    if hstory and hstory.get("stores_reason") and asia_drop > 0:
        store_note += (spaced("其中包含", hstory['stores_reason']) + "，所以这不是一次纯粹的自主收缩；"
                       "公司未披露处置本身带走了多少家店，本页也不估算。")
    else:
        store_note = store_note.rstrip("，") + "。"
    if len(openers) == 2:
        store_note += ("同期" + "、".join(spaced(STORE_NAMES[k], f"{stores[k][ago]:,} → {stores[k][-1]:,} 家")
                                         for k in openers)
                       + f"，{cn_count(len(openers))}个区域都在开店。")
    if half_of_quarter(region_q[-1]) == latest_half:
        store_note += (f"而亚洲（除日本）本半年的有机收入增速是 {asia_growth:+d}%（{when}）"
                       + ("—— <b>收入在涨，店在减</b>。" if asia_growth > 0 and asia_drop > 0 else "。"))
    else:
        store_note += (f"亚洲（除日本）最近一个有分地区数的季度是 {compact_quarter(region_q[-1])}，"
                       f"有机收入增速 {asia_growth:+d}%。")
    stores_chart = {
        "ref": "EX_STORES",
        "kind": "lines_endlabels",
        "title": store_title,
        "xlabels": store_labels,
        "series": [
            {"name": "亚洲（除日本）", "values": rounded(stores["asia_ex_japan"], 0), "color": "NAVY"},
            {"name": "欧洲（除法国）", "values": rounded(stores["europe_ex_fr"], 0), "color": "MBLUE"},
            {"name": "美国", "values": rounded(stores["united_states"], 0), "color": "BLUE"},
            {"name": "其他市场", "values": rounded(stores["other_markets"], 0), "color": "GOLD"},
            {"name": "法国", "values": rounded(stores["france"], 0), "color": "GREEN"},
            {"name": "日本", "values": rounded(stores["japan"], 0), "color": "GREEN"},
        ],
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "end_label": True,
        "ylab": "门店数（期末）",
        "note": store_note,
        "src_extra": SOURCE_HALF,
    }

    # ── regions ──
    region = staging["region_organic_pct"]
    # 「两年的 Q1 与 Q2」 is the layout of the half-year appendix the table comes
    # from (this year and last), a fact about the document rather than a count
    # of this series -- it stays literal.
    leader = max(REGION_NAMES, key=lambda k: region[k][-1])
    year, number = quarter_parts(region_q[-1])
    ago_q = f"{year - 1}Q{number}"
    region_note = (f"这张图只有{cn_count(len(region_q))}根 x 轴，不是{cn_count(len(quarters))}根："
                   "<b>公司在半年报的附录里只表格化两年的 Q1 与 Q2</b>，"
                   "第三、四季度的分地区有机增速只出现在全年演示材料的柱状图里、没有对应的数字表，"
                   "本页因此不予收录，而不是从图上目测。"
                   + spaced(when, REGION_NAMES[leader])
                   + f" {region[leader][-1]:+d}% 是{cn_count(len(REGION_NAMES))}个区域里最高的")
    if ago_q in region_q:
        region_note += f"，去年同期是 {region[leader][region_q.index(ago_q)]:+d}%"
    asia = region["asia_ex_japan"]
    if len(region_q) < 2:
        previous = None
    elif region_q[-1] == quarters[-1] and region_q[-2] == quarter_before(region_q[-1]):
        previous = "上季"
    else:
        previous = f" {compact_quarter(region_q[-2])} "
    if previous and hstory and hstory.get("region_explanation") and asia[-1] < asia[-2]:
        region_note += (f" —— {hstory['region_explanation']}，这同时解释了亚洲（除日本）从{previous}的 "
                        f"{asia[-2]:+d}% 回落到 {asia[-1]:+d}%。")
    elif previous:
        region_note += (f"。亚洲（除日本）从{previous}的 {asia[-2]:+d}% "
                        f"{'回落' if asia[-1] < asia[-2] else '走'}到 {asia[-1]:+d}%。")
    else:
        region_note += "。"
    region_chart = {
        "ref": "EX_REGION",
        "kind": "grouped_bars",
        "title": "分地区有机增速：公司只把两年的 Q1 与 Q2 排在一张表里",
        "xlabels": [compact_quarter(q) for q in region_q],
        "groups": [
            {"name": "美国", "color": "NAVY",
             "values": rounded(region["united_states"])},
            {"name": "亚洲（除日本）", "color": "BLUE",
             "values": rounded(region["asia_ex_japan"])},
            {"name": "日本", "color": "GOLD",
             "values": rounded(region["japan"])},
            {"name": "欧洲", "color": "GREEN",
             "values": rounded(region["europe"])},
        ],
        "bar_labels": True,
        "fmt": "pct0", "label_fmt": "pct0", "yfmt": "pct0",
        "ylab": "有机增速",
        "note": region_note,
        "src_extra": (f"分地区有机增速取自 {half_of_quarter(region_q[-1])} 业绩演示材料附录"
                      "「Quarterly organic revenue change by region」。"),
    }
    return [season, div_margin, cash_chart, stores_chart, region_chart]


# ── the threshold section and the routine series ─────────────────────────────
def routine_charts(staging: dict, der: dict, labels: list[str], kpi: dict | None,
                   entries: list[dict], values: dict, call: dict | None,
                   hstory: dict | None) -> list[dict]:
    cash_halves = staging["cash_halves"]
    cash = staging["half_cash_eur_m"]
    halves = staging["halves"]
    long_q = staging["long_quarters"]
    split = staging["quarterly_wines_split_eur_m"]
    first = next(i for i, v in enumerate(split["champagne_wines"]) if v is not None)
    split_labels = [compact_quarter(q) for q in long_q[first:]]
    charts = []

    if kpi is not None:
        values_now = [headroom(e["direction"], e["threshold"], e["current"]) for e in entries]
        safe = sum(1 for v in values_now if round(v, 1) >= 0)
        charts.append(headroom_exhibit(
            f"下季跟踪阈值：{cn_count(len(entries))}条线里{cn_count(safe)}条仍在安全侧",
            entries, "current",
            ("阈值是本地研究设定，不是公司指引 —— <b>LVMH 不提供任何数字指引</b>，"
             "所以这一节没有可以照抄的公司口径。正值代表仍在安全侧。"
             + fill_story(kpi.get("headroom_note", ""), values)
             + "原始单位的阈值与当前值见核对表。"),
            "阈值与理由见核对表；当前值取自本页已列示的公司披露值与透明自算。",
        ))

    # The group margin against the last complete year's level. Two readings of
    # this half are made against it: above the previous year's second half, and
    # above that whole year. The sentence says since when both have held.
    fy_year = half_parts(halves[-1])[1] - 1
    fy = full_year_margin(staging, fy_year)
    margin = der["half_margin"]

    def above_prior_h2(i: int) -> bool | None:
        _, y = half_parts(halves[i])
        label = f"H2 {y - 1}"
        return margin[i] > margin[halves.index(label)] if label in halves else None

    def above_prior_year(i: int) -> bool | None:
        _, y = half_parts(halves[i])
        level = full_year_margin(staging, y - 1)
        return None if level is None else margin[i] > level

    now_a, now_b = above_prior_h2(len(halves) - 1), above_prior_year(len(halves) - 1)
    first_since = None
    if now_a and now_b:
        broke = [i for i in range(len(halves) - 1) if above_prior_h2(i) is False]
        if broke:
            since = broke[-1]
            if not any(above_prior_h2(i) and above_prior_year(i) for i in range(since, len(halves) - 1)):
                first_since = halves[since]
    if first_since:
        margin_note = (f"{cn_count(len(halves))}个半年里，本半年是 {half_cn(first_since)}以来第一次同时做到"
                       "「高于上年同期的下半年」与「高于上一整年」。")
    elif now_b is not None:
        margin_note = f"本半年{'高于' if now_b else '低于'}上一整年的 {fy:.1f}%。"
    else:
        margin_note = ""
    # Each first half against its OWN full year, not against one year's level:
    # over seven halves those were the same comparison, over twenty-one they
    # are not, and the sentence this guards is about the shape of the business.
    own = [(half_parts(h)[1], margin[i], full_year_margin(staging, half_parts(h)[1]))
           for i, h in enumerate(halves) if h.startswith("H1")]
    own = [(year, m, level) for year, m, level in own if level is not None]
    # Compared at the precision the page prints, so the count in the sentence is
    # the count a reader gets by looking at the chart.
    h1_above = [round(m, 1) > round(level, 1) for _, m, level in own]
    if h1_above and all(h1_above):
        margin_note += ("但注意这条阈值线本身的性质：<b>上半年高于全年是这家公司的常态</b>"
                        "（见 {EX_SEASON}），所以站在这条线之上不是新信息，跌破它才是。")
    elif is_a_recent_habit(h1_above):
        run = trailing_run(h1_above)
        early = h1_above[:len(h1_above) - run]
        thin_flags = [p["margin_h2"] < p["margin_h1"] for p in der["half_pairs"]]
        # `half_pairs` keys the year as a string and `half_parts` returns an int;
        # comparing them raw makes this condition unreachable rather than false.
        same = (trailing_run(thin_flags) == run and der["half_pairs"]
                and int(der["half_pairs"][-run]["year"]) == int(own[-run][0]))
        how_many = "一次都没有" if sum(early) == 0 else f"只有 {sum(early)} 次"
        margin_note += (f"但注意这条阈值线本身的性质：<b>上半年高于它自己那一整年，是 {own[-run][0]} 年以后才有的事</b> —— "
                        f"{own[-run][0]}–{own[-1][0]} 连续{cn_count(run)}年如此，"
                        f"而 {own[0][0]}–{own[len(early) - 1][0]} 的{cn_count(len(early))}年里{how_many}。"
                        + ("这不是另一个发现：全年利润率是两个半年按收入加权的平均，"
                           "所以「下半年更薄」与「上半年高于全年」在算术上是同一句话，"
                           "两边数出来的转折年份也确实相同。"
                           if same else "")
                        + "所以跌破这条线是信息，站在线上只说明这一年还在这段里。")
    if fy is not None:
        charts.append(threshold_exhibit(
            f"半年集团经营利润率对 FY{fy_year} 全年水平（{fy:.1f}%）",
            halves, rounded(margin), round(fy, 1),
            fmt="pct1", ylab="半年经营利润率",
            actual_name="半年经营利润率 D", threshold_name=f"FY{fy_year} 全年 {fy:.1f}%",
            note=margin_note,
            src_extra=SOURCE_HALF,
        ))

    intensity = der["capex_intensity"]
    falling = all(intensity[i + 1] < intensity[i] for i in range(len(intensity) - 1))
    capex_note = (f"资本强度{cn_count(len(cash_halves))}个半年"
                  + ("连续下降：" if falling else "的走势：")
                  + f"从 {intensity[0]:.1f}% {'降' if intensity[-1] < intensity[0] else '升'}到 {intensity[-1]:.1f}%，"
                  f"绝对额从 €{cash['capex'][0]:,.0f}M {'降' if cash['capex'][-1] < cash['capex'][0] else '升'}到 "
                  f"€{cash['capex'][-1]:,.0f}M。"
                  + ((hstory or {}).get("capex_note", "") if falling else "")
                  + "经营性投资是公司自己的口径，含门店、生产与物业，不等于会计上的购置固定资产。")
    charts.append({
        "ref": "EX_CAPEX",
        "kind": "bar_line_dual",
        "title": (f"半年经营性投资 €{cash['capex'][-1]:,.0f}M，占半年收入 "
                  f"{intensity[-1]:.1f}%"),
        "xlabels": cash_halves,
        "bar": {"name": "半年经营性投资", "values": rounded(cash["capex"], 0), "color": "NAVY"},
        "line": {"name": "占半年收入 (RHS)", "values": rounded(intensity),
                 "color": "RED", "yfmt": "pct1"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "€M（半年）", "ylab2": "占半年收入",
        "note": capex_note,
        "src_extra": SOURCE_HALF,
    })

    wines = (hstory or {}).get("wines_split")
    cognac = split["cognac_spirits"][first:]
    below_start = all(v < cognac[0] for v in cognac[1:])
    ws_note = f"公司只在这一个分部之下再拆两行，且只从 {long_q[first][:4]} 年起提供。"
    if wines:
        ws_note += (f"本半年香槟与葡萄酒有机 {signed(wines['organic_pct']['champagne_wines'], 0)}、"
                    f"干邑与烈酒有机 {signed(wines['organic_pct']['cognac_spirits'], 0)}（公司口径），"
                    + ("而" if below_start else ""))
    if below_start:
        ws_note += (f"干邑与烈酒的绝对额{cn_count(len(cognac))}个季度里仍未回到 {long_q[first]} 的 "
                    f"€{cognac[0]:,.0f}M。")
    elif wines:
        ws_note = ws_note.rstrip("，") + "。"
    if wines:
        ws_note += wines["note"]
    if call is not None and call["lead"].get("evidence_note"):
        ws_note += call["lead"]["evidence_note"]
    charts.append({
        "ref": "EX_WS_SPLIT",
        "kind": "lines_endlabels",
        "title": "葡萄酒与烈酒的两条腿" + (f"：{wines['title']}" if wines else ""),
        "xlabels": split_labels,
        "series": [
            {"name": "香槟与葡萄酒", "values": rounded(split["champagne_wines"][first:], 0),
             "color": "GOLD"},
            {"name": "干邑与烈酒", "values": rounded(cognac, 0),
             "color": "NAVY"},
        ],
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "end_label": True,
        "ylab": "€M",
        "note": ws_note,
        "src_extra": SOURCE_QUARTER,
    })
    return charts


# ── the long record ─────────────────────────────────────────────────────────
def long_charts(staging: dict) -> list[dict]:
    """The quarterly revenue record back to 2016Q1.

    LVMH stopped filing with the SEC in 2004, and this page was built on the
    eight quarters its own releases carry as a current window. But the company
    reprints all four quarters of the current AND prior year in every full-year
    press-release appendix, so nine of those releases stitch into a continuous,
    self-overlapping 2016-2025 series -- a research-effort floor, not a
    disclosure one. Later quarters come from each quarter's own release.
    """
    long_q = staging["long_quarters"]
    labels = [compact_quarter(q) for q in long_q]
    rev = staging["quarterly_revenue_eur_m"]
    org = staging["organic_growth_pct"]
    total = rev["total"]
    yoy = [None if i < 4 or not total[i - 4] else pct_change(total[i], total[i - 4])
           for i in range(len(total))]
    flg_share = [rev["fashion_leather"][i] / total[i] * 100 for i in range(len(total))]

    return [
        {
            "ref": "EX_L_REV",
            "kind": "gs_bar",
            "title": (f"{len(labels)} 季集团收入：从 €{total[0]:,.0f}M 到 €{total[-1]:,.0f}M，"
                      f"其中 2021 年那一跳里有 Tiffany"),
            "xlabels": labels,
            "values": rounded(total, 0),
            "legend": "季度收入",
            "yoy": {"name": "报告口径同比 (RHS)", "values": rounded(yoy), "yfmt": "pct0"},
            "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
            "ylab": "€M", "xstep": 4,
            "note": ("<b>这条线不是一家公司连续十年的经营曲线，中间有两次并表。</b>"
                     "Christian Dior Couture 于 2017 下半年并入时装与皮具；"
                     "Tiffany 于 2021 年 1 月并入手表与珠宝，公司自己的说法是"
                     "「+10% structural impact… linked entirely to the consolidation of "
                     "Tiffany &amp; Co.」。所以收入<b>水平</b>的两级台阶要按并购读，"
                     "而不是按需求读 —— 下一张的有机增速按定义剔除了结构性变化，"
                     "那条才是可以连续读的。"
                     "序列取自公司每年全年新闻稿的附表：每份都重印当年与上年全部四个季度，"
                     "相邻两份互相重叠，逐格交叉核对过。"),
            "src_extra": "各年全年业绩新闻稿附表（公司官网），2016–2025 共九份。",
        },
        {
            "ref": "EX_L_ORG",
            "kind": "lines",
            "title": (f"{len(labels)} 季五个分部的有机增速：并购不进这条线，"
                      f"所以它是唯一能跨 2017 与 2021 连续读的一条"),
            "xlabels": labels,
            "series": [
                {"name": "时装与皮具", "values": rounded(org["fashion_leather"]), "color": "NAVY"},
                {"name": "手表与珠宝", "values": rounded(org["watches_jewelry"]), "color": "BLUE"},
                {"name": "精品零售", "values": rounded(org["selective_retailing"]), "color": "MBLUE"},
                {"name": "香水与化妆品", "values": rounded(org["perfumes_cosmetics"]), "color": "GRAY"},
                {"name": "葡萄酒与烈酒", "values": rounded(org["wines_spirits"]), "color": "GOLD"},
            ],
            "fmt": "pct0", "yfmt": "pct0", "label_fmt": "pct0",
            "ylab": "有机增速", "zero_line": True, "end_label": True, "xstep": 4,
            "note": ("有机增速是公司自己的口径，剔除汇率与合并范围变化 —— "
                     "**这正是它能跨越 2017 年 Dior 与 2021 年 Tiffany 两次并表的原因**，"
                     "上一张的收入水平不能。2020 年那道深坑是门店关闭，不是份额流失："
                     "五条腿同时向下，精品零售（旅游零售为主）最深。"),
            "src_extra": "各年全年业绩新闻稿附表所载分部有机增速。",
        },
        {
            "ref": "EX_L_MIX",
            "kind": "stacked_dual",
            "title": (f"{len(labels)} 季分部结构：时装与皮具占比从 {flg_share[0]:.1f}% "
                      f"走到 {flg_share[-1]:.1f}%"),
            "xlabels": labels,
            "stacks": [
                {"name": "时装与皮具", "color": "NAVY",
                 "values": rounded(rev["fashion_leather"], 0)},
                {"name": "精品零售", "color": "MBLUE",
                 "values": rounded(rev["selective_retailing"], 0)},
                {"name": "手表与珠宝", "color": "BLUE",
                 "values": rounded(rev["watches_jewelry"], 0)},
                {"name": "香水与化妆品", "color": "GRAY",
                 "values": rounded(rev["perfumes_cosmetics"], 0)},
                {"name": "葡萄酒与烈酒", "color": "GOLD",
                 "values": rounded(rev["wines_spirits"], 0)},
            ],
            "line": {"name": "时装与皮具占比 (RHS)", "color": "RED",
                     "values": rounded(flg_share), "yfmt": "pct1", "ymax": 100},
            "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
            "ylab": "€M", "ylab2": "占比", "xstep": 4,
            "note": ("<b>占比的两次跳升要分开读。</b>时装与皮具的占比在 2017 下半年与 "
                     "2021 年初各抬一级，前者是 Dior 并入本分部，后者是 Tiffany 并入"
                     "手表与珠宝、把分母抬高。中间与之后的漂移才是经营。"
                     "各分部相加不等于集团收入：公司另有一条 Other &amp; eliminations，"
                     "本图不画，它在核对表里。"),
            "src_extra": "各年全年业绩新闻稿附表。",
        },
    ]


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    half = staging["halves"][-1]
    hrev, hpro = staging["half_revenue_eur_m"]["total"][-1], staging["half_pro_eur_m"]["total"][-1]
    margin = printed_margin(staging, half, "total")
    return [f"半年收入 €{hrev / 1000:.1f}B",
            f"半年经营利润率 {margin if margin is not None else hpro / hrev * 100:.1f}%",
            f"本季有机 {staging['organic_growth_pct']['total'][-1]:+.0f}%"]


def release_prefix(quarter: str) -> str:
    """The label a quarter's own release carries in `sources`: Q1/Q3 revenue, H1 or FY results."""
    year, number = quarter_parts(quarter)
    return {1: f"Q1 {year}", 2: f"H1 {year}", 3: f"Q3 {year}", 4: f"FY{year}"}[number]


def build_payload(staging: dict) -> dict:
    quarters = staging["quarters"]
    labels = [compact_quarter(q) for q in quarters]
    period = display_period(quarters[-1])
    half = staging["halves"][-1]
    der = derived(staging)
    rev = staging["quarterly_revenue_eur_m"]
    long_q = staging["long_quarters"]
    start = long_q.index(quarters[0])
    halves = staging["halves"]
    hrev = staging["half_revenue_eur_m"]
    hpro = staging["half_pro_eur_m"]
    cash = staging["half_cash_eur_m"]
    org = der["organic"]
    n = len(quarters)
    latest = latest_block(staging, period=period,
                          period_end=staging["quarter_period_ends"][-1], full_label=half)

    call = stamped_block(staging, "call_record", period)
    forward = stamped_block(staging, "forward_statements", period)
    kpi = stamped_block(staging, "next_kpi", period)
    story = stamped_block(staging, "quarter_story", period)
    hstory = stamped_block(staging, "half_story", half)
    prefix = release_prefix(quarters[-1])
    if not any(source["label"].startswith(f"{prefix} ") for source in staging["sources"]):
        raise ValueError(f"series `sources` has no entry for the {prefix} release: add it with the roll")

    values = story_values(staging, der, call)
    entries = kpi_entries(staging, der, kpi) if kpi is not None else []

    said_ex = said_charts(staging, der, call, values) if call is not None else []
    quarter_ex = quarter_charts(staging, der, labels, story, hstory)
    half_ex = half_charts(staging, der, hstory)
    long_ex = long_charts(staging)
    routine_ex = routine_charts(staging, der, labels, kpi, entries, values, call, hstory)
    exhibits = number_exhibits(said_ex + quarter_ex + half_ex + long_ex + routine_ex)

    # ── audit tables ─────────────────────────────────────────────────────────
    rev_rows = [
        [quarters[i]]
        + [f"{rev[d][start + i]:,}" for d in DIVS]
        + [f"{der['other'][start + i]:,}",
           f"{staging['quarterly_revenue_other_published_eur_m'][start + i]:,}",
           f"{der['other'][start + i] - staging['quarterly_revenue_other_published_eur_m'][start + i]:+,}",
           f"{rev['total'][start + i]:,}"]
        for i in range(n)
    ]
    growth_rows = [
        [quarters[i]]
        + [f"{org[d][i]:+d}%" for d in DIVS]
        + [f"{org['total'][i]:+d}%", f"{der['reported_yoy'][i]:+.2f}%", f"{der['gap'][i]:+.2f}pp"]
        for i in range(n)
    ]
    printed = staging["half_margin_company_printed_pct"]
    pro_rows = [
        [halves[i]]
        + [f"{hpro[d][i]:,}" for d in DIVS]
        + [f"{hpro['other'][i]:,}", f"{hpro['total'][i]:,}",
           f"{der['half_margin'][i]:.2f}%",
           printed.get(halves[i], {}).get("total") and f"{printed[halves[i]]['total']:.1f}%" or "—"]
        for i in range(len(halves))
    ]
    margin_rows = [
        [halves[i]] + [f"{der['div_half_margin'][d][i]:.2f}%" for d in DIVS]
        for i in range(len(halves))
    ]
    cash_rows = [
        [staging["cash_halves"][i], f"{cash['ocf'][i]:,}", f"{cash['capex'][i]:,}",
         f"{cash['lease_repaid'][i]:,}", f"{cash['ofcf'][i]:,}",
         f"{der['capex_intensity'][i]:.2f}%",
         f"{staging['net_financial_debt_eur_m'][i]:,}", f"{staging['equity_eur_m'][i]:,}"]
        for i in range(len(staging["cash_halves"]))
    ]
    store_rows = [
        [staging["store_dates"][i]] + [f"{staging['stores'][k][i]:,}" for k in STORE_KEYS]
        for i in range(len(staging["store_dates"]))
    ]
    VERDICTS = {"met": "兑现", "beat": "兑现且好于所述", "missed": "未兑现",
                "caveat_held": "兑现在它自己预留的余地里", "unverifiable": "无法在原口径上核"}

    div_headers = [DIV_NAMES[d] for d in DIVS]
    tables = [
        {"title": f"{cn_count(n)}季分部收入（€M）与「其他与抵销」两种取法的差",
         "headers": ["期间"] + div_headers
                    + ["其他与抵销 D", "公司印的其他与抵销", "差 D", "集团合计"],
         "rows": rev_rows},
        {"title": f"{cn_count(n)}季有机增速（公司披露）与报告口径同比（本页自算）",
         "headers": ["期间"] + div_headers + ["集团有机", "集团报告口径 D", "两者之差 D"],
         "rows": growth_rows},
        {"title": f"{cn_count(len(halves))}个半年的分部经营利润（€M）；H2 各行为「全年减上半年」",
         "headers": ["半年"] + div_headers
                    + ["其他与抵销", "集团合计", "经营利润率 D", "公司印的利润率"],
         "rows": pro_rows},
        {"title": f"{cn_count(len(halves))}个半年的分部经营利润率（本页按分部利润 ÷ 分部收入重算）",
         "headers": ["半年"] + div_headers,
         "rows": margin_rows},
        {"title": f"{cn_count(len(staging['cash_halves']))}个半年的现金流、资本强度与期末资产负债（€M）",
         "headers": ["半年", "经营现金流", "经营性投资", "租赁负债偿还", "经营自由现金流",
                     "投资占收入 D", "期末净金融负债", "期末权益"],
         "rows": cash_rows},
        {"title": f"{cn_count(len(staging['store_dates']))}个时点的门店数（只在半年度与全年披露）",
         "headers": ["日期", "法国", "欧洲（除法国）", "美国", "日本", "亚洲（除日本）",
                     "其他市场", "合计"],
         "rows": store_rows},
    ]
    if call is not None:
        tables.append({
            "ref": "TBL_SAID",
            "title": f"上季电话会的{cn_count(len(call['items']))}条前瞻陈述，逐条结算",
            "headers": ["主题", "原话（英文照抄）", "中文转述", "本季实际", "判词"],
            "rows": [[item["topic"], item["said"], item["said_zh"], item["outcome_zh"],
                      VERDICTS[item["verdict"]]] for item in call["items"]]})
    if forward is not None:
        tables.append({
            "title": "本季电话会给出的全部前瞻（原话）",
            "headers": ["主题", "原话（英文照抄）", "可数字化的部分"],
            "rows": [[item["topic"], item["said"], item["quantified"]] for item in forward["items"]]})
    if kpi is not None:
        tables.append({
            "title": "下季跟踪阈值与当前值（原始单位）",
            "headers": ["指标", "方向", "阈值", "本季值", "余量 D", "为什么是这条线"],
            "rows": [[e["metric"],
                      "高于阈值为安全" if e["direction"] == "up" else "低于阈值为安全",
                      kpi_unit_text(e["unit"], e["threshold"]),
                      kpi_unit_text(e["unit"], e["current"]),
                      f"{headroom(e['direction'], e['threshold'], e['current']):+.1f}%",
                      e["why"]] for e in entries]})
    for number, table in enumerate(tables, start=1):
        table["n"] = number
    table_no = {table.pop("ref"): table["n"] for table in tables if "ref" in table}
    tables.append(ai_capex_cycle_table(len(tables) + 1))
    tables = [{"n": t["n"], **{k: v for k, v in t.items() if k != "n"}} for t in tables]

    resolve_exhibit_refs(exhibits)
    for exhibit in exhibits:
        for key in ("note", "src_extra", "title"):
            if exhibit.get(key) and "{TBL_SAID}" in exhibit[key]:
                exhibit[key] = exhibit[key].replace("{TBL_SAID}", str(table_no["TBL_SAID"]))

    # ── the half and the quarter in two sentences ──
    i_now = len(halves) - 1
    i_prior = year_ago_half(halves, half)
    rep_step = der["reported_yoy"][-1] - der["reported_yoy"][-2]
    gap_step = der["gap"][-2] - der["gap"][-1]
    org_step = org["total"][-1] - org["total"][-2]
    share = gap_step / rep_step if rep_step else 0.0
    if rep_step > 0 and 0 < share < 1:
        step_words = (f"比上季改善 {rep_step:.2f}pp，其中 {share * 100:.0f}% 来自汇率与并表"
                      "而不是需求")
    elif rep_step > 0:
        step_words = f"比上季改善 {rep_step:.2f}pp"
    else:
        step_words = f"比上季{'持平' if rep_step == 0 else '回落'} {abs(rep_step):.2f}pp"
    components = half_components(staging)
    closing = closes_half(quarters[-1], half)
    if closing:
        first_quarter = quarter_before(quarters[-1])
        headline = (
            f"半年收入 €{hrev['total'][i_now] / 1000:.1f}B（报告口径 "
            f"{pct_change(hrev['total'][i_now], hrev['total'][i_prior]):+.0f}%、"
            f"有机 {components['organic']:+d}%），"
            f"经营利润 €{hpro['total'][i_now]:,}M、利润率 {der['half_margin'][i_now]:.2f}%；"
            f"本季报告口径同比 {signed(der['reported_yoy'][-1])}，{step_words} —— "
            f"而这一半年最重要的数字（利润率）在"
            f"{month_cn(staging['quarter_release_dates'][first_quarter])}那次收入公告里根本不存在。")
        title = f"LVMH（MC.PA）：{period} / {half} 季报仪表盘"
    else:
        next_half = half_of_quarter(quarters[-1])
        headline = (
            f"季度收入 €{rev['total'][-1]:,.0f}M，报告口径同比 {signed(der['reported_yoy'][-1])}、"
            f"有机 {signed(org['total'][-1], 0)}，{step_words} —— "
            f"本季公告只有收入，利润要等 {next_half} 的业绩；页面上的利润仍截至 {half}。")
        title = f"LVMH（MC.PA）：{period} 季报仪表盘（利润截至 {half}）"

    cards = [
        '<article><span>结构</span><b>一年发四次收入，只发两次利润</b>'
        f'<p>{cn_count(n)}个季度里没有一个季度有属于它自己的分部利润数。本页收入按季、'
        '利润按半年，两条 x 轴各自独立。</p></article>',
    ]
    if rep_step > 0 and 0 < share < 1:
        cards.append(
            f'<article><span>算术</span><b>报表上的好转有{cn_share(share)}不是需求</b>'
            f'<p>报告口径同比改善 {rep_step:.2f}pp，有机增速{"只" if share > 0.5 else ""}贡献 '
            f'{org_step:+.0f}pp，其余来自汇率与并表。</p></article>')
    if call is not None:
        cards.append(f'<article><span>兑现</span><b>{call["lead"]["brief_head"]}</b>'
                     f'<p>{fill_story(call["lead"]["brief"], values)}</p></article>')

    sections = []
    if said_ex:
        sections.append({
            "id": "settled",
            "short": "上季兑现",
            "title": "公司给的是句子，不是数字 —— 上季那些话结算了没有",
            "description": (
                "LVMH 不发布收入、利润或利润率的任何数字指引，所以这一节不是常规的指引兑现，"
                f"而是对电话会陈述的逐条结算：{cn_count(len(call['items']))}条前瞻陈述，"
                f"{call['made_on']} 说出，{call['settled_by']} 结清。"
            ),
            "exhibits": said_ex,
        })
    sections.append({
        "id": "quarter_highlights",
        "short": "本季重点",
        "title": "本季重点" + (f"：{story['section_theme']}" if story else ""),
        "description": (
            "季度口径能看的只有收入。这一节拆报告增速与有机增速之间那条差，"
            "看分部结构与分化，最后用半年图给出唯一存在的利润拆解。"
        ),
        "exhibits": quarter_ex,
    })
    sections.append({
        "id": "half_year",
        "short": "半年度独有",
        "title": "只有半年度披露才看得见的",
        "description": (
            "利润率、现金流、净负债与门店数一年只有两个读数。"
            "本节所有图的 x 轴都是半年，不是季度。"
        ),
        "exhibits": half_ex,
    })
    sections.append({
        "id": "long_record",
        "short": "长期记录",
        "title": f"{cn_count(len(long_q))}季的长期记录",
        "description": (
            f"季度收入与有机增速回到 {long_q[0]}。LVMH 不向 SEC 申报，但它每年的全年"
            "新闻稿附表里同时重印当年与上年全部四个季度 —— 九份发布就拼出完整序列，"
            f"且相邻两份互相重叠、可逐格核对。这一节只画能连续读的{cn_count(len(long_ex))}张。"
        ),
        "exhibits": long_ex,
    })
    sections.append({
        "id": "routine",
        "short": "下季跟踪与常规" if kpi is not None else "长期常规",
        "title": "下季跟踪与长期常规" if kpi is not None else "长期常规",
        "description": (
            ("阈值为本地研究设定，不是公司指引；再加资本强度与葡萄酒与烈酒的两条腿。"
             if kpi is not None else "半年利润率对上一整年的水平、资本强度与葡萄酒与烈酒的两条腿。")
        ),
        "exhibits": routine_ex,
    })
    for index, section in enumerate(sections, start=1):
        section["title"] = f"{cn_ordinal(index)}、{section['title']}"
    order = " → ".join(section.pop("short") for section in sections)
    threshold_section = next(i for i, s in enumerate(sections, start=1) if s["id"] == "routine")

    # ── notes ──
    residual_gaps = [abs(der["other"][start + i] - staging["quarterly_revenue_other_published_eur_m"][start + i])
                     for i in range(n)]
    off = [g for g in residual_gaps if g]
    parts_sum = sum(hpro[d][i_now] for d in DIVS) + hpro["other"][i_now]
    published = staging["half_pro_published_total_eur_m"].get(half)
    diffs = sorted(((abs((der["half_margin"][halves.index(h)] if k == "total"
                          else der["div_half_margin"][k][halves.index(h)]) - v), h, k, v)
                    for h, row in printed.items() for k, v in row.items()), reverse=True)
    stores = staging["stores"]
    ago = staging["store_dates"].index(
        f"{int(staging['store_dates'][-1][:4]) - 1}{staging['store_dates'][-1][4:]}")
    asia_drop = stores["asia_ex_japan"][ago] - stores["asia_ex_japan"][-1]
    region_q = staging["region_quarters"]
    table_titles = {t["title"]: t["n"] for t in tables}
    t_pro = next(n_ for title, n_ in table_titles.items() if "分部经营利润（€M）" in title)
    t_margin = next(n_ for title, n_ in table_titles.items() if "分部经营利润率" in title)
    t_rev = next(n_ for title, n_ in table_titles.items() if "分部收入（€M）" in title)
    notes = [
        f"本页按「{order}」{cn_count(len(sections))}段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
        f"LVMH 一年发四次收入、只发两次利润。第一与第三季度只发收入公告，正文里没有任何利润行；损益表、分部经营利润、汇率与并表对利润的影响、现金流量表、资产负债表、分地区收入与门店数只在半年度和全年披露。本页{cn_count(n)}个季度里没有任何一个季度有属于它自己的分部利润数，所以收入按季度轴、利润按半年轴，两条轴各自独立，本页不做任何按季摊平或插值。",
        "LVMH 已不是 SEC 报告发行人。CIK 0000824046 名下只有两份 20-F（2002-07-01 报 FY2001、2003-06-30 报 FY2002，另有一份 20-F/A）与七份 6-K（2002-02-12 至 2004-03-17）；2004-03-08 报 Form 15-15D 中止申报义务，2009-07-31 报 Form 15F-15D 终止注册。此后该 CIK 下只剩 ADR 存托登记用的 F-6EF / F-6 POS（最新一份 2022-01-24）与两份 SC 13D。本页因此没有任何 EDGAR 来源，全部数据取自公司自己发布的文件。",
        "全页以欧元列示，不折算美元。公司本身不发布美元财务数字，折算会在页面上制造一个任何披露里都不存在的数"
        + (f"；而{hstory['fx_clause']}正是本页要读的那条汇率腿，折算会把它抹掉。"
           if hstory and hstory.get("fx_clause") else "。"),
        "H2 各行由「全年减上半年」得出并标 D。这与公司自己在全年演示材料附录里印的 H2 行偶有 ±1 百万欧元的差，因为公司按未取整数字计算；本页统一用「全年减上半年」，不混用两种口径。",
        "季度的「其他业务与抵销」按「公司印的集团合计减五个分部」取残值，以让堆叠图闭合到公司印的合计。"
        + (f"它与公司自己印的那一行在{cn_count(n)}个季度里有{cn_count(len(off))}季差 {max(off):,.0f} 百万欧元，"
           f"两个数并列在核对表第 {t_rev} 张里。" if off else
           f"它与公司自己印的那一行在{cn_count(n)}个季度里逐季一致，两个数并列在核对表第 {t_rev} 张里。"),
    ]
    if published is not None and published != parts_sum:
        notes.append(f"{half} 五个分部的经营利润加上「其他与抵销」是 {parts_sum:,} 百万欧元，而公司印的集团合计是 {published:,}，"
                     f"本页在利润桥的末腿里显式带上这 {abs(published - parts_sum)} 百万欧元的取整差，不把它藏进任何一个分部。")
    if diffs:
        gap_pp, gap_half, gap_key, gap_printed = diffs[0]
        computed = (der["half_margin"][halves.index(gap_half)] if gap_key == "total"
                    else der["div_half_margin"][gap_key][halves.index(gap_half)])
        notes.append(
            f"分部经营利润率按「分部经营利润 ÷ 分部收入」重算，与公司自己印的百分数最大差 {gap_pp:.2f} 个百分点"
            f"（{DIV_NAMES.get(gap_key, '集团')}：本页 {computed:.2f}%，公司印 {gap_printed:.1f}%）。"
            f"两套数并列在核对表第 {t_pro}、第 {t_margin} 张里，"
            f"本页图上用重算值，因为只有它在{cn_count(len(halves))}个半年上口径一致；"
            "正文引用某一格利润率时，公司印过的就用公司印的数。")
    if components is not None and closing:
        legs = components["organic"] + components["perimeter"] + components["currency"]
        notes.append(
            "季度的汇率与并表拆分公司不披露：它按季只给有机增速，报告口径同比是本页自算，两者之差因此是一个残值，标 D。"
            "半年度口径公司给的是「有机 " + signed(components["organic"], 0) + "、并表 "
            + unit_value(components["perimeter"], "pct") + "、汇率 " + unit_value(components["currency"], "pct") + "」"
            + (f"，而这三个取整后的整数相加是 {unit_value(legs, 'pct')}，公司自己印的报告口径合计是 "
               f"{unit_value(components['reported'], 'pct')}；本页因此不把这三个整数当成一个能闭合的等式来用，也不据此反推任何一条腿。"
               if legs != components["reported"] else "，这一次恰好相加闭合；本页仍不据此反推季度的任何一条腿。"))
    else:
        notes.append("季度的汇率与并表拆分公司不披露：它按季只给有机增速，报告口径同比是本页自算，两者之差因此是一个残值，标 D。")
    notes += [
        "分部有机增速里，公司在部分季度印的是「−0%」与「+0%」而不是「0%」，本页在序列里一律记为 0，核对表统一印作「+0%」，不保留原样印法。",
        f"分地区有机增速只收录{cn_count(len(region_q))}个季度。公司在半年报附录里只把两年的 Q1 与 Q2 排成表格，第三、四季度的分地区数字只出现在全年演示材料的柱状图上、没有对应的数字表，本页不从图上目测取数。",
        "门店数的口径是期末自营门店数（含电商），公司口径。"
        + (f"亚洲（除日本）一年净减 {asia_drop} 家里" + spaced("包含", hstory['stores_reason'])
           + "，公司未披露处置本身带走了多少家店，本页也不估算。"
           if hstory and hstory.get("stores_reason") and asia_drop > 0 else ""),
    ]
    if kpi is not None:
        notes.append(f"第{cn_ordinal(threshold_section)}节的阈值是本地研究设定，不是公司指引，也不构成评级或投资建议；「距阈值余量」统一为正值代表安全侧。")
    notes += [
        "本页只发布公司披露值与可复算的简单派生值；D 标记代表 Derived / 自算。市面上流传的单品牌收入（Louis Vuitton、Christian Dior、Tiffany 的绝对额）均为卖方估计，公司从不披露，本页不予采用。",
        "本页已知未接入：任何单一品牌的收入或利润（公司只披露五个分部）、分部的分季度利润、分季度的汇率与并表拆分、分部的分地区拆分、价格与销量的分解（公司只在电话会上给过定性数字）、"
        f"以及 {half_parts(halves[0])[1]} 年之前的半年度利润、{staging['cash_halves'][0]} 之前的现金流与 "
        f"{staging['store_dates'][0][:7]} 之前的门店数（季度收入与有机增速已回补到 {long_q[0]}）。",
        "电话会记录仅作引用来源，公开仓不复制原件或逐字全文；页面内引用的英文原话为逐字短句引用。",
    ]

    return {
        "schema_version": "quarterly-dashboard/mc-v1",
        "page": {"slug": "mc", "language": "zh-CN"},
        "company": {
            "ticker": "MC.PA",
            "name": "LVMH Moët Hennessy Louis Vuitton SE",
            "group": "luxury_brands",
            "accounting_standard": "IFRS",
        },
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · MC.PA",
        "title": title,
        "subtitle": (
            f"截至 {latest['period_end']} · 发布 {latest['release_date']} · IFRS 合并 · "
            f"{AUDIT_WORDS[latest['audit_status']]} · "
            "全部以欧元列示 · 收入按季披露，利润只有半年度"
        ),
        "headline": headline,
        "brief": (f'<h4>本季{cn_count(len(cards))}条主线</h4><div class="takeaway-grid">'
                  + "".join(cards) + '</div>'),
        "source": (
            'Source: <a href="https://www.lvmh.com/en/investors/investors-and-analysts" '
            'rel="noopener">LVMH Investors &amp; Analysts</a>'
            '（季度收入公告、半年度与全年业绩新闻稿、半年度财务报告、Financial Documents '
            '与业绩演示材料）。LVMH 已不是 SEC 报告发行人，本页没有任何 EDGAR 来源。'
        ),
        "source_url": "https://www.lvmh.com/en/investors/investors-and-analysts",
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": sections,
        "tables": tables,
        "notes": notes,
        "footer": "LVMH quarterly results · 数据来自公司公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "mc.js"), payload, "mc")
    shell_dir = ROOT / "mc"
    shell_dir.mkdir(exist_ok=True)
    # Rendered here, not at import: the shell stamps the payload's content hash
    # into its <script src>, so it has to be built after write_dash.
    (shell_dir / "index.html").write_text(render_shell("MC.PA", "mc"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(
        f"LVMH page: {charts} charts in {len(payload['sections'])} sections "
        f"+ {len(payload['tables'])} audit tables"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
