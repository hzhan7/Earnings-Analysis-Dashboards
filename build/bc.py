"""Brunello Cucinelli S.p.A. half-year dashboard.

Brunello Cucinelli is an Italian issuer listed on Euronext Milan, reporting
under IFRS in euro on a calendar fiscal year. It is not an SEC registrant: the
only EDGAR entity in its name holds seven filings, all of them F-6 and 424B3
depositary paperwork for an unsponsored ADR filed by a custodian bank under the
Rule 12g3-2(b) exemption, and none of them carries a financial statement. So
neither the rendered-statement R-files nor companyfacts reaches this company --
the annual reports, the half-year reports and the quarterly revenue releases
are the entire source.

**Two structural facts shape every chart here, and they are the page.**

First, everything the issuer prints is a *to-date* figure. It publishes revenue
four times a year -- Q1, H1, nine months, full year -- and a complete income
statement only twice, at H1 and at the full year. It has never printed a second,
third or fourth quarter, nor a second half, as a discrete period. So one quarter
in four and one half in two are company-printed; the rest are obtained here by
subtracting one cumulative disclosure from the next. That is transparent
arithmetic, but it is not disclosure, and the page marks which is which
everywhere it matters. The subtraction is checkable in one place and one only:
the issuer quotes a standalone third quarter in prose without tabling it, and
those quotes match the subtraction.

Second, and this is what the back half of the first section is about: the
company guides revenue growth every year in the same words -- "around 10%" --
and for years it never said which currency basis it meant. The census of
quantified forward statements in its results calls (`guidance_basis_census`)
finds none that states an exchange-rate basis before December 2025. The basis
is not a footnote: in a year whose guidance range is one point wide, reported
and constant-rate growth can land on opposite sides of it.

The page is in the site's four parts, with the TSM page's titles word for word:
一 settles what the owner's previous analysis left (its follow-ups, closed as
the current analysis' section 0 records; its section 8 thresholds, settled on
this half's filings) and then the company's own guidance record; 二 draws the
current analysis' conclusions that the filings can carry; 三 tracks the current
analysis' section 8 thresholds; 四 is the long record. The owner writes an
analysis every quarter while this page moves every half, so what a half settles
was set by the analysis of the quarter before its last one.

**A roll edits `series/bc.json` and nothing else** (CLAUDE.md §9). The page's
period is the latest half: an H1 page reads the half against the year's
guidance, an H2 page reads the full year. Every period, count and figure is
computed from the series, and every sentence that states something the data
could stop saying (「连续四年」「三年停在」「全部达成」「同时高于」「没有一笔转回」)
is printed only while the data says it. What belongs to one half sits in blocks
stamped with that half: the closure and the settlement (`followup_closure`,
`prior_kpi_settlement`, with the allowance table in `doubtful_receivables`),
the half's printed figures the arrays do not carry (`half_detail`), the next
thresholds (`next_kpi`) and the conclusions the page cannot draw (`half_story`);
the company's targets for a year sit in `company_targets` and are published only
in that year. The analyses' own counts and thresholds are recorded again in
`_checks["note"]`, which the tests read and the builder never does. Fixed
history stays in code: the 2025 regional re-presentation, the 2025 provision for
a North American wholesale customer, the withdrawn lease-adjusted EBITDA, the
Russia audit matter, the end of the 2016-2023 margin climb, the lockdown and
rebound halves, and the 30% wholesale target the company once wrote down.

Published figures are company-reported or transparent arithmetic. Thresholds in
sections one and three are the owner's local research settings, not company
guidance.
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
    latest_block,
    number_exhibits,
    stamped_block,
    threshold_exhibit,
    threshold_table,
    unit_text,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402

STAGING_PATH = ROOT / "series" / "bc.json"
DATA_DIR = ROOT / "data"

SOURCE_RELEASES = ("各期数字逐一取自公司自己的年度财务报告、半年度财务报告与季度营收公告；"
                   "公司不是美国申报人，本站其他页依赖的 10-Q/10-K 渲染报表对它不存在。")

# Fixed history. The margin climb that began in 2016 ended with 2023H1; from the
# next half the series moves sideways. That is a reading of the record up to
# the date it was written, not something a roll changes.
FLAT_FROM = "2023H2"

# Fixed history. The first half of 2020 is the lockdown half (EBIT went negative)
# and the first half of 2021 is the rebound from it; their year-on-year margin
# changes are thirty-odd percentage points either way. Plotted, they flatten the
# other nine halves into one line at zero, so the margin-change chart names them
# in its note and prints them in the audit table instead of drawing them.
PANDEMIC_HALVES = ("2020H1", "2021H1")


def pct(current: float, base: float) -> float:
    return (current / base - 1) * 100.0


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def rounded(values, digits: int = 6):
    return [None if v is None else round(v, digits) for v in values]


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


def half_cn(label: str) -> str:
    """``2026H1`` / ``H1 2026`` -> ``2026 年上半年``."""
    text = label.replace(" ", "")
    year, half = (text[:4], text[4:]) if text[0].isdigit() else (text[2:], text[:2])
    return f"{year} 年{'上' if half == 'H1' else '下'}半年"


def pp(value: float) -> str:
    """A guidance bound as the company writes it: 10.0 -> ``10``, 10.5 -> ``10.5``."""
    return f"{value:g}"


def period_view(s: dict) -> dict:
    """What 「本期」 means on this page: the latest half, or the full year it closes.

    An H1 page compares the half with the same half a year earlier (two indices
    back on the half axis) and the H1-only blocks. An H2 page is a full-year
    page: the growth rates and the income-statement comparisons come from the
    annual record, because the company prints the year, never the second half.
    """
    h = s["half"]
    half = h["periods"][-1]
    year = int(half[:4])
    is_h1 = half.endswith("H1")
    if is_h1:
        now, prior = h["periods"].index(half), h["periods"].index(f"{year - 1}H1")
        gr = s["growth_h1_pct"]
        g = gr["years"].index(year)
        return {
            "half": half, "year": year, "is_h1": True,
            "word": "上半年", "span": "半年", "same": "同一个半年里",
            "revenue": h["revenue_eur_k"][now], "cfx": gr["cfx"][g], "reported": gr["reported"][g],
            "ebit_growth": pct(h["ebit_eur_k"][now], h["ebit_eur_k"][prior]),
            "net_growth": pct(h["net_profit_eur_k"][now], h["net_profit_eur_k"][prior]),
            "margin": h["ebit_eur_k"][now] / h["revenue_eur_k"][now] * 100,
        }
    a = s["annual"]
    j = a["years"].index(year)
    return {
        "half": half, "year": year, "is_h1": False,
        "word": "全年", "span": "一年", "same": "同一年里",
        "revenue": a["revenue_eur_k"][j], "cfx": a["revenue_yoy_cfx_pct"][j],
        "reported": a["revenue_yoy_reported_pct"][j],
        "ebit_growth": pct(a["ebit_eur_k"][j], a["ebit_eur_k"][j - 1]),
        "net_growth": pct(a["net_profit_eur_k"][j], a["net_profit_eur_k"][j - 1]),
        "margin": a["ebit_eur_k"][j] / a["revenue_eur_k"][j] * 100,
    }


def guidance_for(s: dict, year: int) -> dict | None:
    g = s["annual_revenue_guidance"]
    if year not in g["target_years"]:
        return None
    i = g["target_years"].index(year)
    return {"low": g["final_low"][i], "high": g["final_high"][i], "basis": g["final_basis"][i],
            "cfx_low": g["cfx_leg_low"][i], "cfx_high": g["cfx_leg_high"][i]}


def legs(guide: dict) -> tuple[tuple[float, float], tuple[float, float]]:
    """The range each basis is settled on: (constant-rate, reported).

    A year guided on two legs at once (December 2025: about +10% reported and
    +11% to +12% at constant rates) settles each actual on its own leg. A year
    guided on one basis is read against that one range on both bases -- which
    is exactly the reading the page warns about, and says so.
    """
    final = (guide["low"], guide["high"])
    if guide["basis"] == "reported" and guide["cfx_low"] is not None:
        return (guide["cfx_low"], guide["cfx_high"]), final
    return final, final


def targets_for(s: dict, year: int) -> dict | None:
    """The company's targets for `year`, published only in the year they describe."""
    targets = s.get("company_targets")
    return targets if targets and targets["year"] == year else None


def relation(value: float, low: float, high: float) -> str:
    if low == high:
        if value > high:
            return f"高于全年指引 {pp(high)}%"
        return f"低于全年指引 {pp(low)}%" if value < low else f"等于全年指引 {pp(low)}%"
    if value > high:
        return f"高于全年指引上限 {pp(high)}%"
    if value < low:
        return f"低于下限 {pp(low)}%"
    return f"落在全年指引 {pp(low)}%–{pp(high)}% 之内"


# ── section one (a)(b): what the last analysis left to settle ────────────────
def quarter_before(half: str) -> str:
    """``2026H1`` -> ``Q1 2026``: the quarter before the last one a half closes.

    The owner's analyses are written every quarter while this page moves every
    half, so what a half settles was set by the analysis of the quarter just
    before its last one: the first-quarter revenue update for an H1 page, the
    nine-month update for a full-year page.
    """
    return f"Q{1 if half.endswith('H1') else 3} {half[:4]}"


def quarter_words(label: str) -> str:
    """``Q1 2026`` -> ``2026 年第一季度``."""
    quarter, year = label.split()
    return f"{year} 年第{cn_ordinal(int(quarter[1]))}季度"


def eur_k(value: float) -> str:
    return f"€{value:,.0f} 千"


def spaced(head: str, tail: str) -> str:
    """Join Chinese prose to a phrase, with the space the site puts before a leading number."""
    return head + (" " if tail[:1].isascii() and tail[:1].isalnum() else "") + tail


def h1_margin_changes(s: dict) -> list[dict]:
    """First-half EBIT margin against the same half a year earlier, on one basis.

    The half series keeps every half as it was first printed, so three first
    halves would otherwise be compared across a change the company itself
    bridged in the same table: 2016 has no 2015 in the series, IFRS 15 restated
    the 2017 comparative that the 2018 report printed, and IFRS 16 arrived in
    2019 without restating 2018 -- that year the report printed the current half
    both ways. `h1_like_for_like` records the column the company printed.
    """
    h = s["half"]
    like = {(r["half"], r["side"]): r for r in s["h1_like_for_like"]["records"]}
    rows = []
    for i, period in enumerate(h["periods"]):
        if not period.endswith("H1"):
            continue
        current = like.get((period, "current"))
        rev, ebit = ((current["revenue_eur_k"], current["ebit_eur_k"]) if current
                     else (h["revenue_eur_k"][i], h["ebit_eur_k"][i]))
        prior = like.get((period, "prior"))
        base = f"{int(period[:4]) - 1}H1"
        if prior is not None:
            prior_rev, prior_ebit = prior["revenue_eur_k"], prior["ebit_eur_k"]
        elif base in h["periods"]:
            j = h["periods"].index(base)
            prior_rev, prior_ebit = h["revenue_eur_k"][j], h["ebit_eur_k"][j]
        else:
            raise ValueError(f"{period}: no same-half base in the series or in `h1_like_for_like`")
        margin, prior_margin = ebit / rev * 100, prior_ebit / prior_rev * 100
        rows.append({"half": period, "margin": margin, "prior_margin": prior_margin,
                     "bp": (margin - prior_margin) * 100,
                     "basis": (current or prior or {}).get("why", "")})
    return rows


def allowance_release(dr: dict) -> float:
    """The release the allowance table shows, in EUR thousand, after checking it closes.

    The table's lines have to take the opening balance to the closing one. A
    release is a line of its own (`releases_eur_k`, negative); if the lines the
    series carries do not close, a movement is missing and the page would be
    about to say "nothing was released" about a table it did not read whole.
    """
    moved = (dr["opening_eur_k"] + dr["allocations_eur_k"] + dr["uses_eur_k"]
             + dr["reclassifications_eur_k"] + dr["exchange_eur_k"] + dr.get("releases_eur_k", 0))
    if moved != dr["closing_eur_k"]:
        raise ValueError(f"`doubtful_receivables` does not close: {moved} against {dr['closing_eur_k']}")
    return -dr.get("releases_eur_k", 0)


def settled_entries(s: dict, prior: dict, detail: dict, dr: dict, margins: list[dict]) -> list[dict]:
    """Last analysis' quantified thresholds with this half's actual beside each.

    Thresholds and directions are the analysis' own; every actual is read from
    the series or a block stamped for this half, never typed into the entry.
    """
    actual = {
        "retail_cfx": lambda: detail["retail_cfx_pct"],
        "ebit_margin_yoy": lambda: margins[-1]["bp"],
        "receivables": lambda: detail["trade_receivables_eur_k"][0] / 1000,
        "allowance_release": lambda: allowance_release(dr) / 1000,
        "allowance_charge": lambda: dr["allocations_eur_k"] / 1000,
    }
    base = {"receivables": lambda: detail["trade_receivables_eur_k"][1] / 1000}
    entries = []
    for entry in prior["quantified"]:
        if entry["id"] not in actual:
            raise ValueError(f"prior threshold `{entry['id']}` has no way to read its actual")
        threshold = (base[entry["id"]]() if entry.get("threshold_from") == "same_date_last_year"
                     else entry["threshold"])
        entries.append({**entry, "threshold": threshold, "actual": actual[entry["id"]]()})
    return entries


def settled_charts(s: dict, view: dict, closure: dict | None, prior: dict | None,
                   detail: dict | None, dr: dict | None) -> tuple[list[dict], list[dict]]:
    """(a) the follow-up closure, (b) the threshold settlement; and the entries (b) settled."""
    charts, entries = [], []
    margins = h1_margin_changes(s)
    if closure is not None:
        if closure["set_in"] != quarter_before(view["half"]):
            raise ValueError(f"series block `followup_closure` closes questions set in {closure['set_in']!r}, "
                             f"but the analysis before this half is {quarter_before(view['half'])!r}")
        items = closure["items"]
        labels = list(dict.fromkeys(item["verdict"] for item in items))
        counts = [sum(1 for item in items if item["verdict"] == label) for label in labels]
        stores = s["store_network"]
        if stores["periods"][-1] != s["latest"]["period_end"]:
            raise ValueError("series block `store_network` does not end on this half's period end")
        target = targets_for(s, view["year"])
        if target is None:
            raise ValueError("the closure note names the year's capex target: `company_targets` is missing")
        released = allowance_release(dr)
        by_verdict = dict(zip(labels, counts))
        values = {
            "partial_count": cn_count(by_verdict.get("部分闭环", 0)),
            "complete_count": cn_count(by_verdict.get("完整闭环", 0)),
            "adverse_count": cn_count(sum(1 for item in items if item.get("adverse"))),
            "retail_cfx": f"{detail['retail_cfx_pct']:+.1f}%",
            "retail_last_quarter_cfx": f"{detail['retail_q2_cfx_pct']:+.1f}%",
            "dos_open": str(stores["dos"][0]), "dos_close": str(stores["dos"][-1]),
            "ebit_bp": f"{margins[-1]['bp']:+.0f}bp",
            "capex_pct": f"{detail['investments_eur_m'][0] * 1000 / view['revenue'] * 100:.1f}%",
            "capex_relation": ("高于" if detail["investments_eur_m"][0] * 1000 / view["revenue"] * 100
                               > target["capex_pct_of_revenue"] else "没有超过"),
            "capex_target": target["capex_words"],
            # The sentence the analysis got wrong last quarter is the one the
            # table settles, so its verb is read off the table, not typed.
            "release_words": "没有一笔转回" if released == 0 else f"转回了 {eur_k(released)}",
            "allowance_uses": eur_k(-dr["uses_eur_k"]),
            "allowance_open": eur_k(dr["opening_eur_k"]), "allowance_close": eur_k(dr["closing_eur_k"]),
        }
        charts.append({
            "ref": "EX_CLOSURE",
            "kind": "bars_labeled",
            "title": (f"上季 {len(items)} 条待验证问题："
                      + "、".join(f"{count} 条{label}" for label, count in zip(labels, counts))),
            "xlabels": labels,
            "values": counts,
            "legend": "问题条数",
            "fmt": "f0", "yfmt": "f0", "label_fmt": "f0",
            "ylab": "条",
            "note": fill_story(closure["note"], values),
            "src_extra": ("问题清单与每条的判定取自本季分析稿第 0 节（逐条核验上一份分析稿留下的问题）；"
                          "数字取自本期新闻稿与半年报。"),
        })
    if prior is not None:
        if prior["set_in"] != quarter_before(view["half"]):
            raise ValueError(f"series block `prior_kpi_settlement` settles thresholds set in {prior['set_in']!r}, "
                             f"but the analysis before this half is {quarter_before(view['half'])!r}")
        entries = settled_entries(s, prior, detail, dr, margins)
        held = [e for e in entries if headroom(e["direction"], e["threshold"], e["actual"]) >= 0]
        broken = [e for e in entries if headroom(e["direction"], e["threshold"], e["actual"]) < 0]
        charts.append({**headroom_exhibit(
            f"上季 {len(entries)} 条量化阈值：{len(held)} 条守住、{len(broken)} 条被击穿",
            entries, "actual",
            ("正值 = 仍在安全侧。守住的是" + "、".join(e["metric"] for e in held)
             + ("；被击穿的是" + "、".join(e["metric"] for e in broken) if broken else "")
             + "。每条的阈值与上季写下的触发动作列在核对抽屉里。"),
            "阈值为上一份分析稿的本地研究设定，不是公司指引；实际值为本期新闻稿与半年报的披露值或据其自算（D）。",
        ), "ref": "EX_PRIOR"})
        for entry in entries:
            if not entry.get("chart"):
                continue
            if entry["id"] != "ebit_margin_yoy":
                raise ValueError(f"prior threshold `{entry['id']}` asks for a chart this page does not draw")
            shown = [None if r["half"] in PANDEMIC_HALVES else round(r["bp"], 1) for r in margins]
            skipped = [r for r in margins if r["half"] in PANDEMIC_HALVES]
            below = [r["half"] for r in margins[:-1]
                     if r["half"] not in PANDEMIC_HALVES and r["bp"] < entry["threshold"]]
            verdict = "守住" if headroom(entry["direction"], entry["threshold"], entry["actual"]) >= 0 else "击穿"
            charts.append({**threshold_exhibit(
                (f"{entry['metric']} {entry['actual']:+.0f}bp：{verdict}上季阈值 "
                 f"{unit_text(entry['unit'], entry['threshold'])}"),
                [r["half"] for r in margins], shown, entry["threshold"],
                fmt="f0", ylab="较上年同期 bp", actual_name="上半年 EBIT 利润率同比",
                threshold_name="上季阈值（安全侧在上方）",
                note=(f"阈值 {unit_text(entry['unit'], entry['threshold'])}，本期 "
                      f"{margins[-1]['prior_margin']:.2f}% → {margins[-1]['margin']:.2f}%，"
                      f"余量 {headroom(entry['direction'], entry['threshold'], entry['actual']):+.1f}%。"
                      f"此前图上画出的{cn_count(len(margins) - 1 - len(skipped))}个上半年里有"
                      f"{cn_count(len(below))}个低于这条线（{'、'.join(below)}）。"
                      + "、".join(f"{r['half']} 的 {r['bp']:+,.0f}bp" for r in skipped)
                      + " 是停摆与反弹，不画在图上 —— 画上去其余各格都会被压成零线上的一条线；"
                      "逐格数值（含这两格）见核对抽屉。每格按公司当年并排印出的同一口径比较："
                      + "；".join(f"{r['half']}：{r['basis']}" for r in margins if r["basis"]) + "。"),
                src_extra=("利润率为 EBIT（Operating income）除以收入，公司印出值计算（D）；"
                           "阈值为上一份分析稿的本地研究设定，不是公司指引。"),
            ), "ref": "EX_PRIOR_MARGIN"})
    return charts, entries


# ── section one (c): the guidance and the basis it was never given on ─────────
def guidance_charts(s: dict, view: dict) -> list[dict]:
    g = s["annual_revenue_guidance"]
    cen = s["guidance_basis_census"]
    by = s["guidance_basis_by_year"]
    st = g["strict_judgeability"]

    complete = [i for i, y in enumerate(g["target_years"])
                if g["actual_reported_pct"][i] is not None and g["actual_cfx_pct"][i] is not None]
    labels = [f"FY{g['target_years'][i]}" for i in complete]
    mid = [(g["final_low"][i] + g["final_high"][i]) / 2 for i in complete]
    rep = [g["actual_reported_pct"][i] for i in complete]
    cfx = [g["actual_cfx_pct"][i] for i in complete]
    current = guidance_for(s, view["year"])
    progress = view["is_h1"] and current is not None
    if progress:
        labels.append(view["half"])
        mid.append((current["low"] + current["high"]) / 2)
        rep.append(view["reported"])
        cfx.append(view["cfx"])
    gap = round(cfx[-1] - rep[-1], 1)
    guide = current or guidance_for(s, int(labels[-1][-4:])) if labels else None
    width = guide["high"] - guide["low"]
    straddle = guide["low"] > rep[-1] and cfx[-1] > guide["high"]
    closed = complete[:-1] if not progress else complete
    all_above = all(r > m and c > m for r, c, m in zip(rep[:len(closed)], cfx[:len(closed)], mid))

    note = ""
    if straddle and all_above:
        note += (f"{cn_count(len(closed))}个完整年度里两条实际线都稳稳高于指引，口径选哪个都不影响结论 —— "
                 f"所以这个问题在那{cn_count(len(closed))}年里是不用回答的。<b>到本期它变成了唯一要回答的问题</b>：")
    if straddle:
        note += (f"恒定汇率 {cfx[-1]:.1f}% 高于指引上限 {pp(guide['high'])}%，"
                 f"报告口径 {rep[-1]:.1f}% 低于指引下限 {pp(guide['low'])}%。")
        if guide["basis"] == "cfx":
            note += (f"{view['year']} 年的指引写明了是恒定汇率，所以正确的读法是前者；"
                     f"但把同一个「{pp(guide['low'])}%」按报告口径去读，会把一个跑在目标之上的"
                     f"{view['span']}读成跑输。")
    else:
        note += (f"本期恒定汇率 {cfx[-1]:.1f}%、报告口径 {rep[-1]:.1f}%，"
                 f"两个口径相差 {gap:.1f}pp，没有分落在指引区间的两侧。")
    if progress:
        note += "最后一格是上半年进度，不是全年结果。"

    straddle_chart = {
        "ref": "EX_STRADDLE",
        "kind": "lines",
        "title": (f"同一条指引，两个实际：本期两个口径相差 {gap:.1f}pp，"
                  + (f"而指引区间只有 {pp(width)}pp 宽" if width > 0 else "而指引是一个单点")),
        "xlabels": labels,
        "series": [
            {"name": "公司全年指引（区间中值）", "values": rounded(mid), "color": "RED"},
            {"name": "报告口径实际增长", "values": rounded(rep), "color": "NAVY"},
            {"name": "恒定汇率实际增长", "values": rounded(cfx), "color": "BLUE"},
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1",
        "end_label": True,
        "ylab": "同比 %",
        "note": note,
        "src_extra": SOURCE_RELEASES,
    }

    first = cen["first_stated_date"]
    basis = {
        "ref": "EX_BASIS",
        "kind": "grouped_bars",
        "title": (f"{cen['quantified_rows']} 条量化指引里 {cen['fx_basis_unstated']} 条没写汇率口径，"
                  f"写了的 {cen['fx_basis_stated']} 条全部在 {first} 之后"),
        "xlabels": [str(y) for y in by["years"]],
        "groups": [
            {"name": "未写明汇率口径", "color": "RED", "values": by["basis_unstated"]},
            {"name": "写明汇率口径", "color": "NAVY", "values": by["basis_stated"]},
        ],
        "bar_labels": True,
        "fmt": "f0", "label_fmt": "f0",
        "ylab": "条",
        "note": (f"按会议年份统计{cn_count(cen['calls_covered'])}场业绩会里的每一条量化前瞻表述。"
                 f"口径这一栏在 {first[:4]} 年 {int(first[5:7])} 月之前是空的 —— 不是偶尔漏写，是一条都没有。"
                 "同一批文件在报<b>结果</b>时几乎每次都同时给两个口径，"
                 "只有在给<b>目标</b>时把口径省掉。"
                 + ("另外两项口径的情况更彻底：租赁准则口径与并购口径在这 "
                    f"{cen['quantified_rows']} 条里<b>一次都没有</b>被说明过。"
                    if cen["lease_basis_stated"] == 0 and cen["perimeter_basis_stated"] == 0 else "")),
        "src_extra": "统计口径为业绩电话会中带数字的前瞻表述；订货会反馈等定性表述不计入。",
    }

    done, scoreable = st["completed_quantified_targets"], st["scoreable_once_an_unstated_basis_is_treated_as_unjudgeable"]
    all_met = st["met"] == done
    met_words = "全部达成" if all_met else "里达成 " + str(st["met"]) + " 条"
    judge = {
        "ref": "EX_JUDGE",
        "kind": "bars_labeled",
        "title": (f"{done} 条已完结目标{met_words}，"
                  f"但只有 {scoreable} 条说清了自己该用哪个口径结算"),
        "xlabels": ["已完结的量化目标", "其中达成", "其中说明了汇率口径"],
        "values": [done, st["met"], scoreable],
        "fmt": "f0", "label_fmt": "f0", "yfmt": "f0",
        "ylab": "条",
        "note": (("「从没错过」这句话本身是成立的，公司确实条条兑现。" if all_met else
                  f"已完结的 {done} 条里有 {st['missed']} 条没有达成。")
                 + "但一条没写口径的目标，严格说不是「达成了」，而是「无法判定」—— "
                 f"按这个标准，{done} 条里只有 {scoreable} 条可以打分。"
                 "把两种口径都算上去凑出一个高达成率，等于让公司在事后挑一个对自己有利的基准。"
                 "本页两个数都给，并写明哪个是哪个。"),
        "src_extra": "覆盖公司在书面申报中给出的全部已完结量化目标，不只营收增长一项。",
    }
    return [straddle_chart, basis, judge]


# ── section two: the period just reported ────────────────────────────────────
def pretax(s: dict, view: dict, detail: dict | None) -> tuple[float, float] | None:
    """(this period's profit before tax, the same period a year earlier), EUR thousand.

    The full year has it in the annual record; a first half has it only in the
    stamped block for that half, because the half series does not carry it.
    """
    if not view["is_h1"]:
        a = s["annual"]
        j = a["years"].index(view["year"])
        return a["pbt_eur_k"][j], a["pbt_eur_k"][j - 1]
    if detail is not None and "pbt_eur_k" in detail:
        return tuple(detail["pbt_eur_k"])
    return None


def ebit_pair(s: dict, view: dict) -> tuple[float, float]:
    """(this period's EBIT, the same period a year earlier), EUR thousand."""
    if not view["is_h1"]:
        a = s["annual"]
        j = a["years"].index(view["year"])
        return a["ebit_eur_k"][j], a["ebit_eur_k"][j - 1]
    h = s["half"]
    return (h["ebit_eur_k"][h["periods"].index(view["half"])],
            h["ebit_eur_k"][h["periods"].index(f"{view['year'] - 1}H1")])


def ladder_chart(s: dict, view: dict, detail: dict | None) -> dict:
    """Revenue to net profit as separate growth rates, with the pre-tax step when it is printed."""
    rev_g_cfx, rev_g_rep = view["cfx"], view["reported"]
    ebit_g, net_g = view["ebit_growth"], view["net_growth"]
    fx = rev_g_cfx - rev_g_rep
    pbt = pretax(s, view, detail)
    pbt_g = pct(*pbt) if pbt else None
    labels = ["收入（恒定汇率）", "收入（报告口径）", "EBIT"] + (["税前利润"] if pbt else []) + ["净利润"]
    values = [rev_g_cfx, rev_g_rep, ebit_g] + ([pbt_g] if pbt else []) + [net_g]
    bars = cn_count(len(values))
    below = ebit_g - net_g
    financial = ebit_g - pbt_g if pbt else None
    if pbt and net_g < ebit_g and financial >= 0.75 * below:
        title = (f"EBIT 增 {signed(ebit_g)}、税前只增 {signed(pbt_g)}：经营线以下 {below:.1f}pp 的落差，"
                 f"{financial:.1f}pp 落在财务收支这一行")
    elif rev_g_cfx > net_g and 0 < fx < rev_g_cfx - net_g:
        title = (f"从收入到净利，{bars}个增速一路掉了 {rev_g_cfx - net_g:.1f}pp，"
                 f"而其中只有 {fx:.1f}pp 发生在经营层面之上")
    else:
        title = (f"从收入到净利的{bars}个增速：恒定汇率收入 {signed(rev_g_cfx)}、报告口径 {signed(rev_g_rep)}、"
                 f"EBIT {signed(ebit_g)}、净利 {signed(net_g)}")
    note = f"{bars}根柱子不是一条桥，是{bars}个各自独立的同比增速，放在一起看落差在哪一段发生。"
    note += f"汇率吃掉 {fx:.1f}pp；" if fx > 0 else f"汇率贡献了 {-fx:.1f}pp；"
    if ebit_g > rev_g_rep:
        note += f"经营杠杆把它加回来 {ebit_g - rev_g_rep:.1f}pp，所以 EBIT 增速反而高于报告口径收入；"
    else:
        note += f"EBIT 增速比报告口径收入低 {rev_g_rep - ebit_g:.1f}pp；"
    if net_g < ebit_g:
        note += f"真正的断层在 EBIT 之下 —— 净利只增 {net_g:.1f}%，落差 {below:.1f}pp"
        if pbt:
            ebit_now, ebit_before = ebit_pair(s, view)
            note += (f" 里 {financial:.1f}pp 在 EBIT 与税前之间：净财务费用 {eur_k(ebit_now - pbt[0])}，上年同期 "
                     f"{eur_k(ebit_before - pbt[1])}"
                     + (f"，其中汇兑收益从 €{detail['fx_gains_eur_m'][1]:.1f}M 降到 €{detail['fx_gains_eur_m'][0]:.1f}M"
                        if view["is_h1"] and detail and "fx_gains_eur_m" in detail else "")
                     + f"；税只占 {pbt_g - net_g:.1f}pp，与经营无关。")
        else:
            note += "全部来自财务损益与税，与经营无关。"
    else:
        note += f"净利增速 {net_g:.1f}%，不低于 EBIT。"
    note += "增速之间不做加减，因为分母不同。"
    return {
        "ref": "EX_LADDER",
        "kind": "bars_labeled",
        "title": title,
        "xlabels": labels,
        "values": [round(v, 1) for v in values],
        "fmt": "pct1", "label_fmt": "pct1", "yfmt": "pct1",
        "ylab": "同比 %",
        "note": note,
        "src_extra": ("收入两个口径、EBIT、税前利润与期间利润均由公司印出；净财务费用为 EBIT 减税前利润（D）；"
                      "汇兑收益取自新闻稿正文。"),
    }


def implied_second_half(s: dict, view: dict) -> dict | None:
    """What the year's constant-rate guidance leaves for the second half.

    The target is a full-year rate at last year's exchange rates. Last year's
    revenue times the target, less this first half at last year's rates (the
    printed rate times last year's first half), is what the second half has to
    deliver; over last year's second half that is the implied rate. The same
    arithmetic on last year gives the second half it was compared against. Each
    half is at its own prior-year rates and the company prints no second half,
    so every derived bar here is an approximation and says so.
    """
    guide = guidance_for(s, view["year"])
    if not view["is_h1"] or guide is None or guide["basis"] != "cfx":
        return None
    a, h, gr = s["annual"], s["half"], s["growth_h1_pct"]
    y = view["year"]

    def revenue(label: str) -> float:
        return h["revenue_eur_k"][h["periods"].index(label)]

    fy_before = a["revenue_eur_k"][a["years"].index(y - 1)]
    at_old_rates = revenue(f"{y - 1}H1") * (1 + view["cfx"] / 100)
    bounds = sorted({guide["low"], guide["high"]})
    implied = [((fy_before * (1 + g / 100) - at_old_rates) / revenue(f"{y - 1}H2") - 1) * 100 for g in bounds]
    h1_before = gr["cfx"][gr["years"].index(y - 1)]
    fy_before_cfx = a["revenue_yoy_cfx_pct"][a["years"].index(y - 1)]
    h2_before = ((a["revenue_eur_k"][a["years"].index(y - 2)] * (1 + fy_before_cfx / 100)
                  - revenue(f"{y - 2}H1") * (1 + h1_before / 100)) / revenue(f"{y - 2}H2") - 1) * 100
    ends = ["下限", "上限"] if len(bounds) == 2 else ["单点"]
    labels = ([f"{y - 1} 年上半年", f"{y - 1} 年下半年 D", f"{y} 年上半年"]
              + [f"{y} 年下半年 · 指引{end}隐含 D" for end in ends])
    slow = view["cfx"] - max(implied)
    band = (f"{min(implied):.1f}%–{max(implied):.1f}%" if len(implied) == 2 else f"{implied[0]:.1f}%")
    target = (f"+{pp(bounds[0])}%–{pp(bounds[-1])}%" if len(bounds) == 2 else f"+{pp(bounds[0])}%")
    title = (f"全年指引 {target}（恒定汇率）隐含下半年只增 {band}，比上半年的 {view['cfx']:.1f}% 慢 "
             + (f"{view['cfx'] - max(implied):.1f}–{view['cfx'] - min(implied):.1f}pp" if len(implied) == 2
                else f"{slow:.1f}pp")
             if slow > 0 else f"全年指引 {target}（恒定汇率）隐含下半年 {band}，上半年是 {view['cfx']:.1f}%")
    tougher = h2_before - h1_before
    note = (f"全年目标 = {y - 1} 年收入 × (1 + 指引)，恒定汇率即按上年汇率；减去上半年按上年汇率的收入"
            f"（{eur_k(at_old_rates)}，即上年同期收入乘公司印出的 {signed(view['cfx'])}），余下的就是下半年要做到的；"
            f"除以 {y - 1} 年下半年收入得到隐含增速。")
    if tougher > 0:
        note += (f"同样的算法放在上年：{y - 1} 年下半年是 {signed(h2_before)}，比当年上半年的 {signed(h1_before)} "
                 f"高 {tougher:.1f}pp —— 下半年的比较基数确实更高"
                 + ("，但高出的幅度远小于隐含的放缓。" if slow > 2 * tougher else "。"))
    note += "两个半年各按自己上年同期的汇率折算，公司又不印下半年，所以标 D 的几格都是自算的近似值。"
    return {
        "ref": "EX_H2",
        "kind": "bars_labeled",
        "title": title,
        "xlabels": labels,
        "values": [round(v, 1) for v in [h1_before, h2_before, view["cfx"]] + implied],
        "fmt": "pct1", "label_fmt": "pct1", "yfmt": "pct1",
        "ylab": "恒定汇率同比 %",
        "note": note,
        "src_extra": ("上半年与全年的恒定汇率增速、全年收入、上半年收入与全年指引由公司印出；"
                      "下半年收入为全年减上半年，标 D 的增速为本页自算。"),
    }


def region_contribution(s: dict, view: dict, detail: dict | None) -> dict | None:
    """Each region's constant-rate growth times its weight a year earlier."""
    geo = s["geography_h1_eur_k"]
    if not view["is_h1"] or detail is None or "region_cfx_pct" not in detail or geo["years"][-1] != view["year"]:
        return None
    rows = {"欧洲": ("europe_total", "europe"), "美洲": ("americas", "americas"), "亚洲": ("asia", "asia")}
    before = {name: geo[key][-2] for name, (key, _) in rows.items()}
    total_before = sum(before.values())
    growth = {name: detail["region_cfx_pct"][key] for name, (_, key) in rows.items()}
    share = {name: before[name] / total_before * 100 for name in rows}
    contrib = {name: growth[name] * share[name] / 100 for name in rows}
    order = sorted(contrib, key=contrib.get, reverse=True)
    total = sum(contrib.values())
    top = order[0]
    agree = abs(total - view["cfx"]) <= 0.15
    return {
        "ref": "EX_CONTRIB",
        "kind": "bars_labeled",
        "title": (f"本期恒定汇率增长 {view['cfx']:.1f}% 里，{top}一家贡献 {contrib[top]:.1f} 个百分点"
                  f"（{contrib[top] / total * 100:.1f}%）"),
        "xlabels": order,
        "values": [round(contrib[name], 2) for name in order],
        "fmt": "pp1", "label_fmt": "pp1", "yfmt": "pp1",
        "ylab": "对集团恒定汇率增速的贡献",
        "note": ("三个区域的恒定汇率增速由公司印出（"
                 + "、".join(f"{name} {signed(growth[name])}" for name in order)
                 + "），乘以各自在上年同期收入里的占比（"
                 + "、".join(f"{share[name]:.1f}%" for name in order)
                 + f"）就是对集团增速的贡献（D）。三者相加 {total:.1f}pp，"
                 + (f"与公司印出的集团 {signed(view['cfx'])} 一致。" if agree
                    else f"与公司印出的集团 {signed(view['cfx'])} 相差 {total - view['cfx']:+.1f}pp。")
                 + f"{top}的增速是集团的 {growth[top] / view['cfx']:.1f} 倍，是本期增长最集中的一块。"),
        "src_extra": "区域收入与区域恒定汇率增速取自本期新闻稿的区域表与正文；贡献为本页自算（D）。",
    }


def working_capital_chart(s: dict, view: dict, detail: dict | None) -> dict | None:
    """Working capital over rolling revenue: the company's measure and the trade core of it."""
    if not view["is_h1"] or detail is None or "inventories_eur_k" not in detail:
        return None
    h = s["half"]
    i = h["periods"].index(view["half"])
    rolling = (h["revenue_eur_k"][i] + h["revenue_eur_k"][i - 1],
               h["revenue_eur_k"][i - 2] + h["revenue_eur_k"][i - 3])
    inv, rec, pay = detail["inventories_eur_k"], detail["trade_receivables_eur_k"], detail["trade_payables_eur_k"]
    nwc = [v * 1000 for v in detail["net_working_capital_eur_m"]]
    trade = [inv[k] + rec[k] - pay[k] for k in (0, 1)]
    other = [nwc[k] - trade[k] for k in (0, 1)]

    def ratio(pair: list[float], k: int) -> float:
        return pair[k] / rolling[k] * 100

    def move(pair: list[float]) -> float:
        return ratio(pair, 0) - ratio(pair, 1)

    parts = [("贸易营运资本（存货 + 应收 − 应付）", move(trade)), ("其中：存货", move(inv)),
             ("其中：应收账款", move(rec)), ("其中：应付账款（减少即占用增加）", -move(pay)),
             ("其他流动项目净额", move(other)), ("公司口径的营运资本", move(nwc))]
    trade_move, pay_move, company_move = parts[0][1], parts[3][1], parts[5][1]
    biggest = max(parts[1:4], key=lambda p: abs(p[1]))
    if company_move < 0 < trade_move:
        title = (f"公司口径的营运资本占滚动收入降了 {-company_move:.1f}pp，存货加应收减应付却升了 {trade_move:.1f}pp"
                 + (f"，其中 {pay_move:.1f}pp 来自应付账款下降" if biggest is parts[3] else ""))
    else:
        title = f"营运资本占滚动收入：贸易口径 {trade_move:+.1f}pp，公司口径 {company_move:+.1f}pp"
    # Mixed signs, so grouped bars (whose axis reaches below zero) rather than
    # labelled bars, which start every axis at zero; and one neutral colour,
    # because a rise here is the worse direction and red/navy would say the opposite.
    return {
        "ref": "EX_NWC",
        "kind": "grouped_bars",
        "title": title,
        "xlabels": [label for label, _ in parts],
        "groups": [{"name": "占滚动 12 个月收入，较上年同期（pp）", "color": "NAVY",
                    "values": [round(v, 2) for _, v in parts]}],
        "bar_labels": True,
        "fmt": "pp1", "label_fmt": "pp1", "yfmt": "pp1",
        "ylab": "占滚动 12 个月收入，较上年同期",
        "note": (f"滚动收入是最近两个半年之和（{eur_k(rolling[0])}，上年同期 {eur_k(rolling[1])}）。"
                 f"公司口径的营运资本（€{detail['net_working_capital_eur_m'][0]:.1f}M，占 {ratio(nwc, 0):.1f}%，"
                 f"上年同期 {ratio(nwc, 1):.1f}%）包含「其他流动资产 / 负债净额」，新闻稿脚注说这一项的变化"
                 "主要来自汇率对冲衍生品的公允价值；拿掉它，存货加应收减应付占滚动收入从 "
                 f"{ratio(trade, 1):.1f}% 升到 {ratio(trade, 0):.1f}%。"
                 f"三项里存货 {parts[1][1]:+.1f}pp、应收 {parts[2][1]:+.1f}pp，应付账款从 {eur_k(pay[1])} "
                 f"{'降到' if pay[0] < pay[1] else '升到'} {eur_k(pay[0])}"
                 + ("而收入在涨，贡献了升幅里最大的一块" if biggest is parts[3] else "")
                 + " —— 新闻稿的说法是维持一贯的供应商付款惯例。"),
        "src_extra": ("存货、应收、应付取自本期新闻稿合并资产负债表（本期末与上年同期末两列），公司口径营运资本取自新闻稿正文；"
                      "占比与变化为本页自算（D）。"),
    }


def quarter_charts(s: dict, view: dict, detail: dict | None) -> tuple[list[dict], dict]:
    """This period's charts, and the multi-year regional chart that goes to the long record."""
    ch = s["channel_h1_eur_k"]
    geo = s["geography_h1_eur_k"]
    this_half = view["is_h1"] and ch["years"][-1] == view["year"]
    period_word = "本期" if this_half else f"{ch['years'][-1]} 年上半年"
    ladder = ladder_chart(s, view, detail)

    d_ret = ch["retail"][-1] - ch["retail"][-2]
    d_who = ch["wholesale"][-1] - ch["wholesale"][-2]
    d_tot = d_ret + d_who
    grew = 0
    for i in range(len(ch["years"]) - 2, 0, -1):
        if ch["wholesale"][i] > ch["wholesale"][i - 1]:
            grew += 1
        else:
            break
    share_now = ch["wholesale"][-1] / (ch["retail"][-1] + ch["wholesale"][-1]) * 100
    share_before = ch["wholesale"][-2] / (ch["retail"][-2] + ch["wholesale"][-2]) * 100
    stalled = abs(d_who) / ch["wholesale"][-2] < 0.01
    bridge_note = (f"批发渠道的绝对额从 €{ch['wholesale'][-2]:,.0f} 千走到 "
                   f"€{ch['wholesale'][-1]:,.0f} 千，一年{'只' if stalled else ''}"
                   f"{'多' if d_who >= 0 else '少'}了 €{abs(d_who):,.0f} 千"
                   + (f"（公司印出的恒定汇率增速 {signed(detail['wholesale_cfx_pct'])}，零售 "
                      f"{signed(detail['retail_cfx_pct'])}）"
                      if this_half and detail is not None and "wholesale_cfx_pct" in detail else "")
                   + "。")
    if grew >= 2:
        bridge_note += f"在此之前它连续{cn_count(grew)}年每年都增长。"
    bridge_note += f"公司把批发占比降到 30% 写成过目标，{period_word}是 {share_now:.1f}%"
    if share_before - share_now >= 0.5 and d_who >= 0:
        bridge_note += " —— 占比确实在降，但降的原因是分母在跑，不是分子在缩。"
    else:
        bridge_note += "。"
    bridge = {
        "ref": "EX_BRIDGE",
        "kind": "bridge_bar",
        "title": (f"{'半年' if this_half else period_word} €{d_tot:,.0f} 千的收入增量里，零售贡献 "
                  f"{d_ret / d_tot * 100:.1f}%"
                  + ("，批发几乎原地不动" if abs(d_who) / d_tot < 0.05 else "")),
        "xlabels": ["零售渠道", "批发渠道", "合计增量"],
        "stacks": [{"name": "较上年同期的增量", "color": "NAVY",
                    "values": [d_ret, d_who, None]}],
        "net": {"name": "半年收入增量合计", "values": [None, None, d_tot]},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "€ 千",
        "note": bridge_note,
        "src_extra": "渠道口径为公司自己的两分法：零售（直营门店与自营电商）与批发。",
    }

    share = [round(r / (r + w) * 100, 1) for r, w in zip(ch["retail"], ch["wholesale"])]
    run = [len(share) - 2]
    while run[0] > 0 and max(share[run[0] - 1:run[-1] + 1]) - min(share[run[0] - 1:run[-1] + 1]) <= 0.5:
        run.insert(0, run[0] - 1)
    band = share[run[0]:run[-1] + 1]
    plateau = len(run) >= 2 and not (min(band) <= share[-1] <= max(band))
    if plateau:
        mix_title = (f"零售占比连续{cn_count(len(run))}年停在 {min(band):.1f}%–{max(band):.1f}%，"
                     f"{period_word}一步走到 {share[-1]:.1f}%")
        mix_note = (f"{ch['years'][run[0]]} 到 {ch['years'][run[-1]]} {cn_count(len(run))}年占比停在 "
                    f"{min(band):.1f}%–{max(band):.1f}%，看起来结构已经稳定。")
    else:
        mix_title = f"零售占比从 {share[0]:.1f}% 走到 {share[-1]:.1f}%"
        mix_note = ""
    if this_half and len(ch["years"]) >= 3:
        # Which leg moved the share. The page used to say the jump was "not
        # retail suddenly accelerating" -- retail's own growth rose by four
        # points while wholesale's fell by nine, so both moved; the split is
        # measured here rather than asserted.
        exact = [r / (r + w) * 100 for r, w in zip(ch["retail"], ch["wholesale"])]
        grow = {leg: (ch[leg][-1] / ch[leg][-2] - 1, ch[leg][-2] / ch[leg][-3] - 1) for leg in ("retail", "wholesale")}
        kept_pace = ch["retail"][-1] / (ch["retail"][-1] + ch["wholesale"][-2] * (1 + grow["wholesale"][1])) * 100
        jump, from_stall = exact[-1] - exact[-2], exact[-1] - kept_pace
        if jump > 0 and grow["wholesale"][0] < grow["wholesale"][1]:
            mix_note += (f"{period_word}的 {jump:.1f}pp 两条腿都在动：零售报告口径增速由上年同期的 "
                         f"{grow['retail'][1] * 100:+.1f}% {'提到' if grow['retail'][0] > grow['retail'][1] else '变为'} "
                         f"{grow['retail'][0] * 100:+.1f}%，批发由 {grow['wholesale'][1] * 100:+.1f}% 掉到 "
                         f"{grow['wholesale'][0] * 100:+.1f}%。假如批发维持上年同期的增速，占比只会到 {kept_pace:.1f}% —— "
                         f"跳升里 {from_stall:.1f}pp 来自批发放慢，{jump - from_stall:.1f}pp 来自零售跑得比批发的原速更快。")
    mix = {
        "ref": "EX_MIX",
        "kind": "stacked_dual",
        "title": mix_title,
        "xlabels": [f"{y}H1" for y in ch["years"]],
        "stacks": [
            {"name": "零售渠道", "color": "NAVY", "values": ch["retail"]},
            {"name": "批发渠道", "color": "GOLD", "values": ch["wholesale"]},
        ],
        "line": {"name": "零售占比（右轴）", "color": "RED", "values": share, "ymax": 100},
        "fmt": "f0c", "label_fmt": "f0c",
        "ylab": "€ 千",
        "ylab2": "零售占比 %",
        "note": ("柱是每年上半年的两个渠道绝对额，右轴红线是零售占比。" + mix_note
                 + "右轴显式设了 100% 的上界 —— 这一图型的右轴默认封顶在 60，"
                 "占比线超过就会被画到画布外而图例照常显示。"),
        "src_extra": (f"各年上半年数取自当期半年度报告的渠道表；{ch['years'][-1]} 年取自半年业绩新闻稿。"),
    }

    names = ("欧洲", "美洲", "亚洲")
    rows = (geo["europe_total"], geo["americas"], geo["asia"])
    totals = [sum(col[i] for col in rows) for i in range(len(geo["years"]))]
    first = {n: col[0] / totals[0] * 100 for n, col in zip(names, rows)}
    last = {n: col[-1] / totals[-1] * 100 for n, col in zip(names, rows)}
    was_biggest = max(first, key=first.get)
    now_biggest = max(last, key=last.get)
    printed_h1 = s["cumulative_revenue_eur_k"]
    exact = all(totals[i] == printed_h1["h1"][printed_h1["years"].index(y)]
                for i, y in enumerate(geo["years"]))
    italy = geo["italy_row_when_separate"]
    last_split = max(i for i, v in enumerate(italy) if v is not None)
    n_years = cn_count(len(geo["years"]))
    region = {
        "ref": "EX_REGION",
        "kind": "grouped_bars",
        "title": (f"{cn_count(len(names))}个区域{n_years}年："
                  + (f"最大的一块从{was_biggest}换成{now_biggest}，"
                     f"{was_biggest}让出 {first[was_biggest] - last[was_biggest]:.1f} 个百分点"
                     if was_biggest != now_biggest else
                     f"最大的一块一直是{now_biggest}，占比 {first[now_biggest]:.1f}% → {last[now_biggest]:.1f}%")),
        "xlabels": [f"{y}H1" for y in geo["years"]],
        "groups": [
            {"name": "欧洲（含意大利）", "color": "NAVY", "values": geo["europe_total"]},
            {"name": "美洲", "color": "BLUE", "values": geo["americas"]},
            {"name": "亚洲", "color": "GOLD", "values": geo["asia"]},
        ],
        "bar_labels": False,
        "fmt": "f0c", "label_fmt": "f0c",
        "ylab": "€ 千",
        "note": ("公司到 2024 年上半年为止分四行披露：欧洲（不含意大利）、意大利、美洲、亚洲；"
                 "2025 年上半年起改成三行，意大利并进欧洲，上年同期也一并改按新口径重列。"
                 "<b>这次改动在文字里没有任何说明</b>，唯一的证据是算术："
                 f"{geo['europe_total'][last_split] - italy[last_split]:,} + {italy[last_split]:,} = "
                 f"{geo['europe_total'][last_split]:,}。本图{n_years}年一律用「含意大利的欧洲」，"
                 f"早年由两行相加还原，{n_years}年各自相加都"
                 + ("精确等于公司印出的总额。" if exact else "与公司印出的总额核对过，差额见核对抽屉。")),
        "src_extra": "口径还原为本页自算（D）；相加校验见核对抽屉。",
    }
    # The analysis' conclusions for this half, in its own order: the profit gap
    # below EBIT, the slowdown the raised guidance implies, where the growth
    # came from (region, then channel), and the one balance-sheet line that got worse.
    charts = [ladder, implied_second_half(s, view), region_contribution(s, view, detail),
              bridge, mix, working_capital_chart(s, view, detail)]
    return [chart for chart in charts if chart is not None], region


def ifrs16_facts(s: dict) -> dict:
    """The lease-adjusted EBITDA line: its two margins and when each step of its withdrawal came."""
    dec = s["ifrs16_disclosure_decay"]
    h = s["half"]
    periods = dec["periods"]
    idx = [h["periods"].index(p.split()[1] + p.split()[0]) for p in periods]
    post = [round(h["ebitda_eur_k"][i] / h["revenue_eur_k"][i] * 100, 1) for i in idx]
    ex = [None if h["ebitda_ex_ifrs16_eur_k"][i] is None
          else round(h["ebitda_ex_ifrs16_eur_k"][i] / h["revenue_eur_k"][i] * 100, 1)
          for i in idx]
    shown = [k for k, v in enumerate(ex) if v is not None]
    silent = next((k for k, count in enumerate(dec["ebitda_token_count"]) if count == 0), None)
    return {
        "periods": periods, "post": post, "ex": ex, "shown": shown,
        "with_bridge": [k for k, v in enumerate(dec["bridge_printed"]) if v][-1],
        "no_bridge": next(k for k, (both, bridge) in enumerate(zip(dec["both_bases_printed"], dec["bridge_printed"]))
                          if both and not bridge),
        "dropped": next(k for k, both in enumerate(dec["both_bases_printed"]) if not both),
        "silent": silent,
        "gap_first": post[shown[0]] - ex[shown[0]],
        "gap_last": post[shown[-1]] - ex[shown[-1]],
        "published_years": sum(1 for v in dec["both_bases_printed"] if v),
    }


def year_of(label: str) -> str:
    """``H1 2024`` -> ``2024``."""
    return label[-4:]


# ── section three: what to track next ────────────────────────────────────────
def next_entries(s: dict, view: dict, kpi: dict, detail: dict | None) -> list[dict]:
    """This analysis' §8 thresholds with the current reading beside each.

    Thresholds and directions are the analysis' own. The current readings are
    read from the series or this half's stamped block -- never typed into the
    entry, which is where the old block went wrong once a threshold was moved.
    """
    need_detail = {"americas_cfx", "europe_cfx", "retail_cfx", "related_party_ai"}
    current = {
        "group_cfx": lambda: view["cfx"],
        "americas_cfx": lambda: detail["region_cfx_pct"]["americas"],
        "europe_cfx": lambda: detail["region_cfx_pct"]["europe"],
        "retail_cfx": lambda: detail["retail_q2_cfx_pct"],
        "core_net_debt": lambda: s["net_debt_h1_eur_k"]["pre_ifrs16"][-1] / 1000,
        # basis points of the half's revenue, so 0.5% of revenue reads as 50bp
        "related_party_ai": lambda: detail["related_party_ai_services_eur_k"] / view["revenue"] * 10000,
    }
    entries = []
    for entry in kpi["quantified"]:
        if entry["id"] not in current:
            raise ValueError(f"next threshold `{entry['id']}` has no way to read its current value")
        if entry["id"] in need_detail and detail is None:
            raise ValueError(f"next threshold `{entry['id']}` reads this half's `half_detail`, which is missing")
        if "current" in entry:
            raise ValueError(f"next threshold `{entry['id']}` is computed from the series; remove its typed value")
        entries.append({**entry, "current": current[entry["id"]]()})
    return entries


def next_quarter_charts(s: dict, view: dict, kpi: dict | None, entries: list[dict],
                        debt: dict) -> list[dict]:
    """§8's thresholds: the headroom overview, then a line for each that has a record behind it."""
    charts = []
    if kpi is not None:
        breached = [e for e in entries if headroom(e["direction"], e["threshold"], e["current"]) < 0]
        story = fill_story(kpi["breach_story"], {"dividends": f"€{kpi['dividends_eur_m']:.1f}M"}) \
            if breached and kpi.get("breach_story") else ""
        charts.append({**headroom_exhibit(
            (f"下季 {len(entries)} 条阈值：{len(entries) - len(breached)} 条在安全侧"
             + (f"，越线的是" + "、".join(e["metric"] for e in breached) if breached else "，没有一条越线")),
            entries, "current",
            ("正值 = 仍在安全侧。阈值取自本季分析稿第 8 节，每条的另一条线与触发动作列在核对抽屉里。"
             "当前值的口径各不相同：集团与区域是上半年累计的恒定汇率增速，零售是第二季度单季"
             "（两者都由公司印出），净负债是 6 月 30 日的时点值，付给 Solomei AI 的费用是上半年服务成本占上半年收入。"
             + story),
            "阈值为本季分析的本地研究设定，不是公司指引；当前值为本期新闻稿与半年报的披露值或据其自算（D）。",
        ), "ref": "EX_NEXT"})
    by_id = {e["id"]: e for e in entries}
    group = by_id.get("group_cfx")
    if group is not None and group.get("chart"):
        gr = s["growth_h1_pct"]
        labels = [f"{y}H1" for y in gr["years"]]
        shown = [(y, v) for y, v in zip(gr["years"], gr["cfx"])]
        earlier = [(y, v) for y, v in shown[:-1] if v is not None]
        under = [f"{y}H1" for y, v in earlier if v < group["threshold"]]
        blank = [y for y, v in shown if v is None]
        charts.append({**threshold_exhibit(
            (f"{group['metric']}：下季阈值 {unit_text(group['unit'], group['threshold'])}，"
             f"当前 {unit_text(group['unit'], group['current'])}"),
            labels, gr["cfx"], group["threshold"],
            fmt="pct1", ylab="恒定汇率同比 %", actual_name="上半年集团恒定汇率增速（公司印出）",
            threshold_name="下季阈值（安全侧在上方）",
            note=(spaced("阈值管的是", group["settles"])
                  + f"：低于 {unit_text(group['unit'], group['threshold'])} 是减仓线，"
                  "另一条上调线与它的附加条件列在核对抽屉里。图上是公司每年印出的上半年累计增速，"
                  f"余量 {headroom(group['direction'], group['threshold'], group['current']):+.1f}%。"
                  f"此前印出的{cn_count(len(earlier))}个上半年里有{cn_count(len(under))}个低于这条线"
                  + (f"（{'、'.join(under)}）" if under else "")
                  + "。"
                  + "".join(f"{y} 年上半年公司只印了对 {y - 2} 年的恒定汇率增速，没有对 {y - 1} 年的，所以那一格空着。"
                            for y in blank)),
            src_extra=("各年上半年的恒定汇率增速取自当年半年度报告；"
                       "阈值为本季分析的本地研究设定，不是公司指引。"),
        ), "ref": "EX_NEXT_GROUP"})
    net_debt = by_id.get("core_net_debt")
    if net_debt is not None and net_debt.get("chart"):
        # The record chart becomes the threshold chart: its own headline moves
        # into the note, so the three-year run and the company's target stay.
        line = net_debt["threshold"] * 1000
        debt["series"].append({"name": "下季阈值（安全侧在下方）", "values": [line] * len(debt["xlabels"]),
                               "color": "RED"})
        debt["note"] = (spaced("阈值管的是", net_debt["settles"])
                        + f"：高于 {unit_text(net_debt['unit'], net_debt['threshold'])} "
                        "为警示，落在公司目标区间为节奏问题（见核对抽屉）；图上是每年 6 月 30 日的时点值，"
                        f"余量 {headroom(net_debt['direction'], net_debt['threshold'], net_debt['current']):+.1f}%。"
                        f"{debt['title']}。" + debt["note"])
        debt["title"] = (f"{net_debt['metric']}：下季阈值 {unit_text(net_debt['unit'], net_debt['threshold'])}，"
                         f"当前 €{net_debt['current']:.1f}M")
    charts.append(debt)
    return charts


def ifrs16_chart(s: dict) -> dict:
    """The withdrawn lease-adjusted EBITDA: a disclosure record, so a long-run chart."""
    f = ifrs16_facts(s)
    periods, post, ex, shown = f["periods"], f["post"], f["ex"], f["shown"]
    no_bridge, dropped, silent = f["no_bridge"], f["dropped"], f["silent"]
    gap_first, gap_last = f["gap_first"], f["gap_last"]
    ifrs = {
        "ref": "EX_IFRS16",
        "kind": "lines",
        "title": f"能把租赁会计和经营利润分开的那条线，公司发布了{cn_count(len(shown))}年然后停了",
        "xlabels": periods,
        "series": [
            {"name": "EBITDA 利润率（含租赁准则影响）", "values": post, "color": "NAVY"},
            {"name": "EBITDA 利润率（剔除租赁准则）", "values": ex, "color": "RED"},
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1",
        "end_label": True,
        "ylab": "占收入 %",
        "note": (f"红线在 {half_cn(periods[shown[-1]])}之后就没有了 —— 不是数值变差，是公司不再披露："
                 f"两个口径连同调节表一起给到 {half_cn(periods[f['with_bridge']])}，"
                 f"{half_cn(periods[no_bridge])}去掉调节表，"
                 f"{half_cn(periods[dropped])}把「剔除租赁准则的 EBITDA」整个从其替代业绩指标里撤下"
                 + (f"，{periods[silent][-4:]} 年的半年新闻稿连 EBITDA 本身都不再出现。" if silent is not None else "。")
                 + ("<b>值得说清的是红线消失前的走向</b>："
                    f"两条线的差距从 {gap_first:.1f}pp 收窄到 {gap_last:.1f}pp，"
                    "也就是说被披露的那几年里，租赁对利润率的抬升作用是在<b>减弱</b>的。"
                    if gap_last < gap_first else
                    f"红线消失前两条线的差距从 {gap_first:.1f}pp 变为 {gap_last:.1f}pp。")
                 + f"撤下披露发生在 {periods[no_bridge][-4:]} 年，早于外界就这个口径提出质疑的时间。"
                 f"本页不替公司补算 {periods[shown[-1] + 1][-4:]} 年之后的红线：还原它需要剔除租赁后的折旧，"
                 "而那个数同样不再披露。"),
        "src_extra": "两个口径的数值与调节表均为公司印出；停止披露的时点以各期报告的替代业绩指标章节为准。",
    }
    return ifrs


# ── section four: the long record ────────────────────────────────────────────
def long_charts(s: dict, view: dict) -> list[dict]:
    q = s["quarterly"]
    labels, vals, basis = q["periods"], q["revenue_eur_k"], q["basis"]
    yoy = [None if i < 4 else round(pct(vals[i], vals[i - 4]), 1) for i in range(len(vals))]
    printed = sum(1 for b in basis if b == "printed")
    quoted = q["narrative_q3_crosscheck_eur_m"]
    rough = set(q.get("narrative_q3_approximate", []))
    quoted_text = "、".join(f"{p[:4]} 年{'约 ' + format(v, '.0f') if p in rough else ' ' + format(v, '.1f')}"
                           for p, v in quoted.items())

    quarters = {
        "ref": "EX_Q",
        "kind": "gs_bar",
        "title": (f"{len(labels)} 个季度里只有 {printed} 个是公司印出来的，"
                  f"其余 {len(labels) - printed} 个由相邻两次累计披露相减得到"),
        "xlabels": labels,
        "values": vals,
        "yoy": {"name": "同比（右轴）", "color": "GOLD", "values": yoy},
        "fmt": "f0c", "label_fmt": "f0c",
        "ylab": "€ 千",
        "ylab2": "同比 %",
        "note": ("公司每年只把第一季度当作一个季度来公布；半年、九个月、全年都是累计数。"
                 "所以第二、三、四季度在任何一份文件里都不存在，本图由 H1−Q1、9M−H1、FY−9M 得到。"
                 "<b>这个减法只有一处可以外部验证</b>："
                 f"公司在正文里口头提过{cn_count(len(quoted))}次单季第三季度的规模，"
                 f"而相减的结果与那{cn_count(len(quoted))}次逐一对上（{quoted_text}，"
                 "单位百万欧元）。四个季度相加等于全年这件事<b>不构成验证</b> —— "
                 "第四季度本来就是用全年减出来的。"
                 "同比线从第五格起才有值，因为需要上年同季。"),
        "src_extra": SOURCE_RELEASES,
    }

    h = s["half"]
    # Two lists on purpose. The payload keeps a rounded value so a rebuild is
    # idempotent; the prose formats the exact one. Rounding to 2dp and then
    # printing at 1dp double-rounds: 2023H2 is 16.7449%, which becomes 16.75 and
    # then prints as 16.8, a figure no arithmetic on this page produces.
    margin_exact = [e / r * 100 for e, r in zip(h["ebit_eur_k"], h["revenue_eur_k"])]
    margin = [round(v, 2) for v in margin_exact]
    target = targets_for(s, view["year"])
    # Every count and list below is derived. On a half-year axis "a year ago" is
    # two indices back, not four, and a hand-typed run of values silently drops
    # one: the first draft of this note listed five halves for a six-half span
    # and skipped 2025H1 altogether.
    flat_from = h["periods"].index(FLAT_FROM)
    flat = margin_exact[flat_from:]
    flat_text = "、".join(f"{v:.1f}" for v in flat)
    peak_i = margin_exact.index(max(margin_exact))
    climb_to = max(margin_exact[:flat_from])
    series = [{"name": "EBIT 利润率（半年）", "values": margin, "color": "NAVY"}]
    # IFRS 16 arrived on 1 January 2019 without restating earlier years: rent
    # became depreciation plus interest, and interest sits below EBIT, so the
    # line steps up there for accounting reasons. The one half printed both ways
    # measures the step.
    lease_step = ""
    both_ways = next((r for r in s["h1_like_for_like"]["records"]
                      if r["side"] == "current" and "IFRS 16" in r["why"]), None)
    if both_ways is not None and both_ways["half"] in h["periods"]:
        k = h["periods"].index(both_ways["half"])
        ex_lease = both_ways["ebit_eur_k"] / both_ways["revenue_eur_k"] * 100
        lease_step = (f"<b>这条线在 {both_ways['half'][:4]} 年有一个会计台阶</b>：IFRS 16 从那年起执行、不重述此前各期，"
                      "租金改记为使用权折旧与利息，而利息在 EBIT 之下，EBIT 因此抬高 —— "
                      f"{both_ways['half']} 公司并排印出的两个口径是 {ex_lease:.1f}%（剔除 IFRS 16）与 "
                      f"{margin_exact[k]:.1f}%（按新准则），差 {margin_exact[k] - ex_lease:.1f}pp。"
                      f"所以 {h['periods'][0]} 起的爬升里有一段是口径，不全是经营改善。")
    target_words = ""
    if target is not None:
        series.append({"name": f"公司 {target['year']} 年指引：{target['ebit_margin_words']}",
                       "values": [target["ebit_margin_pct"]] * len(h["periods"]), "color": "RED"})
        if min(flat) <= target["ebit_margin_pct"] <= max(flat):
            target_words = (f"所以公司把 {target['year']} 年的目标定在「{target['ebit_margin_words']}」，"
                            "要求的不是继续扩张，是守住这条线。")
    ebit = {
        "ref": "EX_MARGIN",
        "kind": "lines",
        "title": (f"EBIT 利润率按半年：{margin_exact[0]:.1f}% 起步爬到 {climb_to:.1f}%，"
                  f"随后 {len(flat)} 个半年在 {min(flat):.1f}%–{max(flat):.1f}% 之间来回"),
        "xlabels": h["periods"],
        "series": series,
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1",
        "end_label": True,
        "ylab": "占收入 %",
        "note": ("这是本站第一条以<b>半年</b>为时间轴的连续序列，因为这家公司的完整损益一年只有两次。"
                 "奇数格（H1）是公司印出的，偶数格（H2）由全年减上半年得到，公司从不单独公布下半年。"
                 f"{h['periods'][flat_from]} 到 {h['periods'][-1]} 共 {len(flat)} 个半年，"
                 f"依次是 {flat_text} —— 在 {min(flat):.1f}% 到 {max(flat):.1f}% 之间来回。"
                 f"最高的一格是 {h['periods'][peak_i]} 的 {margin_exact[peak_i]:.1f}%。"
                 + target_words
                 + lease_step
                 + "<b>2025 年下半年那一格里含一笔北美批发客户破产的拨备</b>，"
                 "公司在全年口径上另给了一个剔除该笔的「正常化」EBIT，本图一律用报告口径。"),
        "src_extra": "半年值为公司印出；下半年值为全年减上半年（D）。",
    }

    a = s["annual"]
    # Only the years whose reported growth the company itself printed. FY2020 is
    # absent: it is the COVID year, revenue fell about a tenth, and this pass did
    # not recover the company's own printed figure for it. Deriving one from the
    # two revenue lines would be easy and would also quietly turn an "as printed"
    # column into a mixed one, so the year is dropped from the chart instead and
    # named in the note.
    pairs = [(y, v) for y, v in zip(a["years"][1:], a["revenue_yoy_reported_pct"][1:])
             if v is not None]
    yrs = [y for y, _ in pairs]
    rep = [v for _, v in pairs]
    missing = [y for y, v in zip(a["years"][1:], a["revenue_yoy_reported_pct"][1:])
               if v is None]
    # The years the company ran far past its own figure: every reported growth
    # rate of twenty per cent or more, which is 2021-2023 in this record.
    fast = [y for y, v in pairs if v >= 20]
    later = [(y, v) for y, v in pairs if fast and y > fast[-1]]
    widest = max(v - 10 for y, v in pairs if y in fast) if fast else None
    conv_note = ""
    if fast and fast == list(range(fast[0], fast[-1] + 1)) and later:
        conv_note = (f"{fast[0]} 到 {fast[-1]} 年公司远远跑赢自己给的数，"
                     f"指引在那{cn_count(len(fast))}年更像是一条地板。"
                     f"{later[0][0]} 年起实际增速落到 " + "、".join(f"{v:.1f}%" for _, v in later) + "，"
                     f"和「约 10%」之间的距离从{cn_count(int(widest // 10) * 10)}多个百分点收到"
                     + ("一个百分点以内" if abs(later[-1][1] - 10) < 1 else f"{abs(later[-1][1] - 10):.1f} 个百分点")
                     + " —— <b>同一句话的性质因此变了</b>：它从一条容易越过的地板，"
                     "变成一条贴着实际走的线。这也是口径问题在今年才开始要紧的原因。")
    cfx_years = [y for y, v in zip(a["years"], a["revenue_yoy_cfx_pct"]) if v is not None]
    cfx_runs = []
    for y in cfx_years:
        if cfx_runs and y == cfx_runs[-1][-1] + 1:
            cfx_runs[-1].append(y)
        else:
            cfx_runs.append([y])
    runs_text = "、".join(f"{r[0]}–{r[-1]}" if len(r) > 1 else str(r[0]) for r in cfx_runs)
    gaps = [y for y in range(cfx_years[0], cfx_years[-1] + 1) if y not in cfx_years] if cfx_years else []
    conv = {
        "ref": "EX_CONV",
        "kind": "bars_labeled",
        # The title used to read 「{len(yrs)} 年从 30.9% 收敛到 10.1%」: the count
        # was the number of bars, while the fall it named runs from the peak year.
        "title": (f"年度营收增速从 FY{yrs[rep.index(max(rep))]} 的 {max(rep):.1f}% 收敛到 "
                  f"FY{yrs[-1]} 的 {rep[-1]:.1f}%，而指引一直是同一句「约 10%」"),
        "xlabels": [f"FY{y}" for y in yrs],
        "values": rounded(rep),
        "fmt": "pct1", "label_fmt": "pct1", "yfmt": "pct1",
        "ylab": "报告口径同比 %",
        "note": conv_note,
        "src_extra": (f"报告口径同比；恒定汇率口径公司在 {runs_text} 年给出"
                      + (f"，{'、'.join(str(y) for y in gaps)} 年没有" if gaps else "") + "。"
                      + (f"**FY{missing[0]} 不在这张图上**：那是疫情年，收入下滑约一成，本轮没有取回公司自己印出的增速数字；"
                         "两条收入相减很容易得到一个数，但那会把「公司印出值」这一栏悄悄变成混合栏。" if missing else "")),
    }

    nd = s["net_debt_h1_eur_k"]
    trough = nd["pre_ifrs16"].index(min(nd["pre_ifrs16"]))
    span = nd["years"][-1] - nd["years"][trough]
    now_year = nd["years"][-1]
    this_half = view["is_h1"] and now_year == view["year"]
    ratio = nd["post_ifrs16"][-1] / nd["pre_ifrs16"][-1]
    year_end = s["net_debt_year_end_eur_k"].get(str(now_year - 1))
    debt_note = ("公司主推的是这条不含租赁负债的「核心」口径，本图照此。"
                 f"含租赁负债的口径在同一时点是 €{nd['post_ifrs16'][-1]:,.0f} 千，"
                 f"量级差{cn_count(int(ratio))}倍以上，两者不可混用。")
    if this_half and year_end is not None and nd["pre_ifrs16"][-1] > year_end and nd["pre_ifrs16"][-1] > nd["pre_ifrs16"][-2]:
        debt_note += (f"本期 €{nd['pre_ifrs16'][-1]:,.0f} 千同时高于上年末的 €{year_end:,.0f} 千"
                      f"与上年同期的 €{nd['pre_ifrs16'][-2]:,.0f} 千；")
    target = targets_for(s, view["year"])
    guide = guidance_for(s, view["year"])
    if this_half and target is not None and guide is not None:
        revenue_last_year = a["revenue_eur_k"][a["years"].index(view["year"] - 1)]
        level = round(revenue_last_year * (1 + guide["low"] / 100) * target["net_debt_pct_of_revenue_low"] / 100, -4)
        if level < nd["pre_ifrs16"][-1]:
            debt_note += (f"按公司自己的年末目标（收入的 {pp(target['net_debt_pct_of_revenue_low'])}–"
                          f"{pp(target['net_debt_pct_of_revenue_high'])}%）与它给的全年增速，"
                          f"下半年需要回落到 €{level:,.0f} 千一线。")
    derived_years = nd.get("post_ifrs16_derived_years", [])
    debt = {
        "ref": "EX_DEBT",
        "kind": "lines",
        "title": (f"核心净金融负债 {span} 年从 €{nd['pre_ifrs16'][trough] / 1000:.1f} 百万"
                  f"走到 €{nd['pre_ifrs16'][-1] / 1000:.1f} 百万"
                  + (f"，而公司给的年末目标是收入的 {pp(target['net_debt_pct_of_revenue_low'])}–"
                     f"{pp(target['net_debt_pct_of_revenue_high'])}%" if target is not None else "")),
        "xlabels": [f"{y}H1" for y in nd["years"]],
        "series": [
            {"name": "核心净金融负债（不含租赁负债）", "values": nd["pre_ifrs16"], "color": "NAVY"},
        ],
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "end_label": True,
        "ylab": "€ 千",
        "note": debt_note,
        "src_extra": ("两个口径均由公司印出"
                      + (f"；{'、'.join(str(y) for y in derived_years)} 年含租赁口径为本页自算（D）。"
                         if derived_years else "。")),
    }
    return [quarters, ebit, conv, debt]


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    view = period_view(staging)
    return [f"Revenues €{view['revenue'] / 1000:.1f}M",
            f"恒定汇率 {view['cfx']:+.1f}%",
            f"EBIT 利润率 {view['margin']:.1f}%"]


def build_payload(staging: dict) -> dict:
    s = staging
    view = period_view(s)
    half = view["half"]
    period = display_period(half)
    latest = latest_block(staging, period=period)
    kpi = stamped_block(s, "next_kpi", period)
    story = stamped_block(s, "half_story", period)
    release = f"{view['year']} 年{'上半年' if view['is_h1'] else '全年'}业绩"
    if not any(source["label"].startswith(release) for source in s["sources"]):
        raise ValueError(f"series `sources` has no entry for the {release} release: add it with the roll")

    closure = stamped_block(s, "followup_closure", period)
    prior = stamped_block(s, "prior_kpi_settlement", period)
    detail = stamped_block(s, "half_detail", period)
    dr = stamped_block(s, "doubtful_receivables", period)
    if (closure or prior) and (detail is None or dr is None):
        raise ValueError("settling last analysis' questions needs this half's `half_detail` and "
                         "`doubtful_receivables` blocks")
    settled_lead, prior_entries = settled_charts(s, view, closure, prior, detail, dr)
    settled = settled_lead + guidance_charts(s, view)
    highlights, region = quarter_charts(s, view, detail)
    quarters, margin, conv, debt = long_charts(s, view)
    # The core net debt chart is the line the tracking section settles at the
    # year end, so it sits there, carrying the threshold, rather than in the long record.
    next_list = next_entries(s, view, kpi, detail) if kpi is not None else []
    nxt = next_quarter_charts(s, view, kpi, next_list, debt)
    # The long record: revenue and its growth, how the mix of regions moved,
    # margin and the lease line that was withdrawn beside it.
    routine = [quarters, conv, region, margin, ifrs16_chart(s)]

    exhibits = number_exhibits(settled + highlights + nxt + routine)
    resolve_exhibit_refs(exhibits)
    a, b, c = len(settled), len(highlights), len(nxt)
    settled_ex, highlight_ex = exhibits[:a], exhibits[a:a + b]
    next_ex, routine_ex = exhibits[a + b:a + b + c], exhibits[a + b + c:]

    h = s["half"]
    q = s["quarterly"]
    ch = s["channel_h1_eur_k"]
    geo = s["geography_h1_eur_k"]
    gr = s["growth_h1_pct"]
    first_table = exhibits[-1]["n"] + 1

    tables = [{
        "n": first_table,
        "title": "半年合并损益与利润率（公司披露值，H2 为全年减上半年）",
        "headers": ["期间", "来源", "收入", "EBITDA", "EBITDA（剔除租赁准则）",
                    "EBIT", "EBIT 利润率 D", "期间利润"],
        "rows": [[h["periods"][i],
                  "公司印出" if h["printed"][i] else "全年减上半年 D",
                  f"€{h['revenue_eur_k'][i]:,.0f}千",
                  f"€{h['ebitda_eur_k'][i]:,.0f}千",
                  "—" if h["ebitda_ex_ifrs16_eur_k"][i] is None
                  else f"€{h['ebitda_ex_ifrs16_eur_k'][i]:,.0f}千",
                  f"€{h['ebit_eur_k'][i]:,.0f}千",
                  f"{h['ebit_eur_k'][i] / h['revenue_eur_k'][i] * 100:.2f}%",
                  f"€{h['net_profit_eur_k'][i]:,.0f}千"]
                 for i in range(len(h["periods"]))],
    }, {
        "n": first_table + 1,
        "title": "季度收入与它的来源（公司只印第一季度）",
        "headers": ["期间", "收入", "来源", "同比 D"],
        "rows": [[q["periods"][i], f"€{q['revenue_eur_k'][i]:,.0f}千",
                  "公司印出" if q["basis"][i] == "printed" else "由累计披露相减 D",
                  "—" if i < 4 else f"{pct(q['revenue_eur_k'][i], q['revenue_eur_k'][i - 4]):+.1f}%"]
                 for i in range(len(q["periods"]))],
    }, {
        "n": first_table + 2,
        "title": "上半年的渠道、区域与两个口径的增速",
        "headers": ["期间", "零售", "批发", "零售占比 D", "欧洲（含意大利）", "美洲", "亚洲",
                    "报告口径同比", "恒定汇率同比"],
        "rows": [[f"{y}H1", f"€{ch['retail'][i]:,.0f}千", f"€{ch['wholesale'][i]:,.0f}千",
                  f"{ch['retail'][i] / (ch['retail'][i] + ch['wholesale'][i]) * 100:.1f}%",
                  f"€{geo['europe_total'][i]:,.0f}千", f"€{geo['americas'][i]:,.0f}千",
                  f"€{geo['asia'][i]:,.0f}千",
                  "—" if y not in gr["years"] else f"{gr['reported'][gr['years'].index(y)]:+.1f}%",
                  "—" if y not in gr["years"] or gr["cfx"][gr["years"].index(y)] is None
                  else f"{gr['cfx'][gr['years'].index(y)]:+.1f}%"]
                 for i, y in enumerate(ch["years"])],
    }]
    if prior_entries:
        tables.append({
            "n": first_table + len(tables),
            "title": "上半年 EBIT 利润率同比（按公司当年并排印出的同一口径）",
            "headers": ["期间", "本期利润率 D", "上年同期利润率 D", "同比 D", "口径说明"],
            "rows": [[r["half"], f"{r['margin']:.2f}%", f"{r['prior_margin']:.2f}%", f"{r['bp']:+,.0f}bp",
                      r["basis"] or "与本页半年序列相同"]
                     for r in h1_margin_changes(s)],
        })
        settle = threshold_table(first_table + len(tables), "上季量化阈值与本期实际（原始单位）",
                                 prior_entries, "actual", "本期实际")
        settle["headers"].append("上季写下的阈值与动作")
        for row, entry in zip(settle["rows"], prior_entries):
            row.append(entry["rule"])
        tables.append(settle)
    if next_list:
        ahead = threshold_table(first_table + len(tables), "下季阈值与当前值（原始单位）",
                                next_list, "current", "当前值")
        ahead["headers"] += ["结算时点", "本季分析写下的阈值与动作"]
        for row, entry in zip(ahead["rows"], next_list):
            row += [entry["settles"], entry["rule"]]
        tables.append(ahead)
    tables.append(ai_capex_cycle_table(first_table + len(tables)))

    d_ret = ch["retail"][-1] - ch["retail"][-2]
    d_who = ch["wholesale"][-1] - ch["wholesale"][-2]
    d_tot = d_ret + d_who
    this_half = view["is_h1"] and ch["years"][-1] == view["year"]
    grew = 0
    for i in range(len(ch["years"]) - 2, 0, -1):
        if ch["wholesale"][i] > ch["wholesale"][i - 1]:
            grew += 1
        else:
            break
    stalled = 0 <= d_who / ch["wholesale"][-2] < 0.01
    cen = s["guidance_basis_census"]
    st = s["annual_revenue_guidance"]["strict_judgeability"]
    guide = guidance_for(s, view["year"])
    ebit_g, net_g = view["ebit_growth"], view["net_growth"]
    first = cen["first_stated_date"]
    census_years = s["guidance_basis_by_year"]["years"]
    blank_years = int(first[:4]) - census_years[0] + 1

    headline = (f"{view['word']}收入 €{view['revenue']:,.0f} 千，恒定汇率 "
                f"{signed(view['cfx'])}、报告口径 {signed(view['reported'])}")
    if guide is not None:
        (cfx_low, cfx_high), (rep_low, rep_high) = legs(guide)
        cfx_rel, rep_rel = relation(view["cfx"], cfx_low, cfx_high), relation(view["reported"], rep_low, rep_high)
        headline += f" —— 前者{cfx_rel}，后者{rep_rel}"
    headline += (f"，而公司在 {first[:4]} 年 {int(first[5:7])} 月之前给过的 {cen['fx_basis_unstated']} 条量化指引"
                 "没有一条写明该用哪个口径；"
                 f"{view['same']} EBIT 增 {signed(ebit_g)} 而净利"
                 + (f"只增 {signed(net_g)}，落差全在经营线以下" if net_g < ebit_g else f"增 {signed(net_g)}"))
    if this_half:
        headline += f"；收入增量的 {d_ret / d_tot * 100:.1f}% 来自零售"
        if stalled and grew >= 2:
            headline += f"，批发在连续增长{cn_count(grew)}年之后停住"
    headline += "。"

    cards = [
        '<article><span>记录</span><b>口径这一栏空了'
        f'{cn_count(blank_years)}年，今年开始决定答案</b>'
        f'<p>{cn_count(cen["calls_covered"])}场业绩会里 {cen["quantified_rows"]} 条量化指引，'
        f'{cen["fx_basis_unstated"]} 条没写汇率口径；写了的全在 {first} 之后。'
        f'{st["completed_quantified_targets"]} 条已完结目标'
        + ("条条达成" if st["met"] == st["completed_quantified_targets"] else f"达成 {st['met']} 条")
        + f'，但只有 {st["scoreable_once_an_unstated_basis_is_treated_as_unjudgeable"]} 条'
        '说清了该用哪个口径结算。</p></article>',
    ]
    pbt = pretax(s, view, detail)
    if net_g < ebit_g:
        cards.append(
            '<article><span>本期</span><b>断层在 EBIT 以下，不在收入</b>'
            f'<p>恒定汇率收入 {signed(view["cfx"])}、EBIT {signed(ebit_g)}，'
            f'经营层面没有问题；净利润只增 {signed(net_g)}，'
            + (f'{ebit_g - net_g:.1f}pp 的落差里 {ebit_g - pct(*pbt):.1f}pp 在财务收支这一行，税只占 '
               f'{pct(*pbt) - net_g:.1f}pp。</p></article>' if pbt else
               f'{ebit_g - net_g:.1f}pp 的落差来自财务损益与税。</p></article>'))
    if this_half and stalled and grew >= 2:
        cards.append(
            '<article><span>结构</span><b>批发停住，增长只剩一条腿</b>'
            f'<p>半年收入增量 €{d_tot:,.0f} 千里零售占 {d_ret / d_tot * 100:.1f}%；'
            f'批发绝对额一年只多了 €{d_who:,.0f} 千，'
            f'而它此前连续{cn_count(grew)}年增长。</p></article>')

    # The four parts and their titles are the site's format (the TSM page), word
    # for word, on a half-year page as on a quarterly one: 「下季」 here is the
    # next disclosure the tracked lines settle on, not a quarter of this issuer's.
    guidance_words = (f"公司每年用同一句话给指引：营收增长「约 10%」。{'最后' if settled_lead else ''}"
                      f"{cn_count(len(settled) - len(settled_lead))}张图先看这句话在报告口径与恒定汇率下"
                      "会得到相反的结论，再看口径这一栏在申报里是什么时候才开始被填上的。")
    if closure is not None or prior is not None:
        before = quarter_words(quarter_before(half))
        settled_words = f"上一份季报分析写于 {before}营收公告之后。"
        if closure is not None:
            settled_words += f"它留下的{cn_count(len(closure['items']))}条待验证问题，按本季分析的逐条核验结算；"
        if prior is not None:
            gone = prior.get("unsettled", [])
            settled_words += (f"它第 8 节的观察指标里能量化的{cn_count(len(prior_entries))}条阈值，用本期申报逐条结算"
                              + ("；另有" + "、".join(u["topic"] for u in gone)
                                 + f"这{cn_count(len(gone))}项结算不了 —— "
                                 + "；".join(u["why"] for u in gone) if gone else "")
                              + "。")
        settled_words += guidance_words
    else:
        settled_words = (f"本站对该公司没有上一份季报分析留下的跟踪指标可结算；本节结算的是公司自己给出、"
                         "本期到期的指引。" + guidance_words)
    sections = [
        {"id": "settled", "short": "上季兑现", "title": "上季跟踪指标兑现了吗",
         "description": settled_words,
         "exhibits": settled_ex},
        {"id": "quarter_highlights", "short": "本季重点", "title": "本季重点",
         "description": (("按本季分析的结论排：利润在哪一段掉下来、上调后的全年指引留给下半年多少、增长来自哪里、"
                          "资产负债表哪一项变差。" if detail is not None else
                          "增速在哪一段掉下来、收入增量由谁贡献、渠道结构走到了哪里。")
                         + (f"本季分析另有{cn_count(len(story['undrawn']))}条结论不在图上："
                            + "；".join(f"{u['topic']} —— {u['why']}" for u in story["undrawn"]) + "。"
                            if story and story.get("undrawn") else "")),
         "exhibits": highlight_ex},
    ]
    if kpi is not None:
        breached = sum(1 for e in next_list if headroom(e["direction"], e["threshold"], e["current"]) < 0)
        gated = kpi.get("gated", [])
        next_words = (f"本季分析第 8 节里能量化的{cn_count(len(next_list))}条阈值，统一换算成距阈值的余量，"
                      f"当前{cn_count(breached)}条越线；有长序列的逐条画线。"
                      + (spaced("另有", "、".join(g["topic"] for g in gated))
                         + f"这{cn_count(len(gated))}项不是一个能画线的数："
                         + "；".join(g["why"] for g in gated) + "。" if gated else ""))
    else:
        next_words = "核心净负债的走势与公司给的年末目标。"
    sections.append({"id": "next_quarter", "short": "下季跟踪", "title": "下季要跟踪什么",
                     "description": next_words, "exhibits": next_ex})
    sections.append({"id": "routine", "short": "长期常规", "title": "长期常规跟踪",
                     "description": ("季度收入的来源构成与增速收敛、区域结构"
                                     f"{cn_count(len(geo['years']))}年里的变化、半年利润率的长期路径，"
                                     "以及公司发布"
                                     f"{cn_count(sum(1 for v in s['ifrs16_disclosure_decay']['both_bases_printed'] if v))}"
                                     "年后停掉的那条剔除租赁准则的利润率。"),
                     "exhibits": routine_ex})
    for index, section in enumerate(sections, start=1):
        section["title"] = f"{cn_ordinal(index)}、{section['title']}"
    order = " → ".join(section.pop("short") for section in sections)
    tracking = next(i for i, section in enumerate(sections, start=1) if section["id"] == "next_quarter")

    printed_q = sum(1 for basis in q["basis"] if basis == "printed")
    printed_h = sum(h["printed"])
    quoted = q["narrative_q3_crosscheck_eur_m"]
    rough = set(q.get("narrative_q3_approximate", []))
    quoted_text = "、".join(f"{p[:4]} 年{'约 ' + format(v, '.0f') if p in rough else ' ' + format(v, '.1f')}"
                           for p, v in quoted.items())
    a = s["annual"]
    record = [(f"FY{y}", r, c) for y, r, c in zip(a["years"], a["revenue_yoy_reported_pct"], a["revenue_yoy_cfx_pct"])
              if r is not None and c is not None]
    # a first half with no constant-rate figure on the same-half basis (2021) is not a pair
    record += [(f"{y}H1", r, c) for y, r, c in zip(gr["years"], gr["reported"], gr["cfx"]) if c is not None]
    spreads = [abs(r - c) for _, r, c in record]
    g_hist = s["annual_revenue_guidance"]
    dual = [i for i, low in enumerate(g_hist["cfx_leg_low"]) if low is not None and g_hist["final_basis"][i] == "reported"]
    nd = s["net_debt_h1_eur_k"]
    fy_norm = [(y, n, e, r) for y, n, e, r in zip(a["years"], a["ebit_normalised_eur_k"], a["ebit_eur_k"], a["revenue_eur_k"])
               if n is not None and y == 2025]
    fx = ifrs16_facts(s)
    debt_label = half_cn(str(nd["years"][-1]) + "H1")
    debt_times = cn_count(int(nd["post_ifrs16"][-1] / nd["pre_ifrs16"][-1]))
    notes = [
        f"本页按「{order}」{cn_count(len(sections))}段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
        "公司在 Euronext Milan 上市，按 IFRS 以欧元列报，财年即自然年。它不是美国证券法下的申报人：EDGAR 上以其名义存在的唯一实体只有七份文件，全部是存托银行为一只无保荐 ADR 提交的 F-6 与 424B3，依据 Rule 12g3-2(b) 豁免，不含任何财务报表。本站其他公司页依赖的 10-Q/10-K 渲染报表对本公司不存在，本页全部数据来自公司自己的年度财务报告、半年度财务报告与季度营收公告。",
        "披露节奏是本页所有图表形状的来源：收入一年公布四次（第一季度、半年、九个月、全年），完整损益表一年只有两次（半年与全年）。公司从未把第二、第三、第四季度或下半年作为独立期间公布过，它印出来的每一个数都是「截至某日累计」。"
        f"因此本页 {len(q['periods'])} 个季度里只有 {printed_q} 个是公司印出的，{len(h['periods'])} 个半年里只有 {printed_h} 个是公司印出的，其余由相邻两次累计披露相减得到，图与表中逐格标明。",
        f"相减这件事只有一处可以外部验证：公司在正文叙述里{cn_count(len(quoted))}次提到过单季第三季度的规模，而 9M 减 H1 的结果与这{cn_count(len(quoted))}次逐一吻合（{quoted_text}，单位百万欧元）。「四个季度相加等于全年」不构成验证，因为第四季度本来就是用全年减九个月得到的 —— 一个从被检查对象推导出自己期望值的检查不可能失败，本页不把它算作证据。",
        f"指引口径是本页第一节{'后半部分' if settled_lead else ''}的主题。{cn_count(cen['calls_covered'])}场业绩会里共 {cen['quantified_rows']} 条带数字的前瞻表述，其中 {cen['fx_basis_unstated']} 条没有说明汇率口径；说明了的 {cen['fx_basis_stated']} 条全部发布于 {first[:4]} 年 {int(first[5:7])} 月 {int(first[8:10])} 日或之后。"
        + (f"租赁准则口径与并购口径在这 {cen['quantified_rows']} 条里一次都没有被说明过。"
           if cen["lease_basis_stated"] == 0 and cen["perimeter_basis_stated"] == 0 else "")
        + "同一批文件在公布结果时几乎每次都同时给出报告口径与恒定汇率两个数，只在给出目标时把口径省略。",
        f"口径的取舍不是措辞问题：报告口径与恒定汇率的差在本记录里介于 {min(spreads):.1f}pp 与 {max(spreads):.1f}pp 之间，本期为 {abs(view['cfx'] - view['reported']):.1f}pp"
        + (f"，而 {view['year']} 年的指引区间只有 {pp(guide['high'] - guide['low'])}pp 宽" if guide and guide["high"] > guide["low"] else "")
        + "。一条指引必须用它自己的口径结算"
        + ("".join(f" —— 把 {g_hist['target_years'][i]} 年 12 月给出的恒定汇率区间（+{pp(g_hist['cfx_leg_low'][i])}% 至 +{pp(g_hist['cfx_leg_high'][i])}%）"
                   f"拿去和报告口径实际（+{g_hist['actual_reported_pct'][i]:.1f}%）相比，会得到一次并不存在的未达标；"
                   f"那次修订同时给了报告口径「约 {pp(g_hist['final_low'][i])}%」这一条腿，两条腿各自都兑现了。"
                   for i in dual if g_hist["actual_reported_pct"][i] is not None) or "。"),
        f"公司已完结的量化目标共 {st['completed_quantified_targets']} 条，"
        + ("全部达成。" if st["met"] == st["completed_quantified_targets"] else f"达成 {st['met']} 条。")
        + f"但其中只有 {st['scoreable_once_an_unstated_basis_is_treated_as_unjudgeable']} 条说明了自己的汇率口径，其余 "
        f"{st['completed_quantified_targets'] - st['scoreable_once_an_unstated_basis_is_treated_as_unjudgeable']} 条严格说无法判定 —— 本页两个数都给出，并写明哪个是哪个。"
        + ("「从没错过」这句话成立，但它衡量的是指引的保守程度，不是预测的准确程度。" if st["missed"] == 0 else ""),
        "区域披露口径在 2025 年上半年变过一次：此前分四行（欧洲不含意大利、意大利、美洲、亚洲），此后分三行，意大利并入欧洲，上年同期一并重列。这次改动在文字里没有任何说明，"
        + (lambda i: f"唯一的证据是算术恒等式 {geo['europe_total'][i] - geo['italy_row_when_separate'][i]:,} + {geo['italy_row_when_separate'][i]:,} = {geo['europe_total'][i]:,}。")(
            max(i for i, v in enumerate(geo["italy_row_when_separate"]) if v is not None))
        + f"本页{cn_count(len(geo['years']))}年一律采用含意大利的欧洲口径，早年由两行相加还原，{cn_count(len(geo['years']))}年各自相加都精确等于公司印出的总额。",
        "「剔除租赁准则影响的 EBITDA」是公司自己的替代业绩指标，"
        f"发布于 {year_of(fx['periods'][fx['shown'][0]])} 至 {year_of(fx['periods'][fx['shown'][-1]])} 年上半年："
        f"{year_of(fx['periods'][0])} 至 {year_of(fx['periods'][fx['with_bridge']])} 年上半年同时给出两个口径与调节表，"
        f"{year_of(fx['periods'][fx['no_bridge']])} 年上半年去掉调节表，"
        f"{year_of(fx['periods'][fx['dropped']])} 年上半年将该指标整个撤下"
        + (f"，{year_of(fx['periods'][fx['silent']])} 年的半年新闻稿不再出现 EBITDA 本身。" if fx["silent"] is not None else "。")
        + (f"被披露的那几年里两个口径的差距是收窄的（{fx['gap_first']:.1f}pp 到 {fx['gap_last']:.1f}pp），"
           if fx["gap_last"] < fx["gap_first"] else
           f"被披露的那几年里两个口径的差距从 {fx['gap_first']:.1f}pp 变为 {fx['gap_last']:.1f}pp，")
        + f"撤下发生在 {year_of(fx['periods'][fx['no_bridge']])} 年。本页不向后补算这条线，因为还原它需要剔除租赁后的折旧，而该数同样不再披露。",
        "公司不发布任何期间的完整毛利表：其损益表按费用性质列示，没有销货成本，也没有毛利这一行。它另给一个自定义的「first margin」，且从不在同一期间同时印出该指标的绝对值与百分比，两者之中总有一个是算出来的。本页因此不发布毛利率序列。",
        f"净金融负债有两个口径：公司主推不含租赁负债的「核心」口径，{debt_label}为 €{nd['pre_ifrs16'][-1]:,.0f} 千；含租赁负债的口径在同一时点为 €{nd['post_ifrs16'][-1]:,.0f} 千。"
        f"量级相差{debt_times}倍以上，任何跨页或跨期比较都必须先说明用的是哪一个。",
    ]
    for year, normalised, ebit_value, revenue in fy_norm:
        j = a["years"].index(year)
        prior_margin = a["ebit_eur_k"][j - 1] / a["revenue_eur_k"][j - 1] * 100
        notes.append(
            f"{year} 年下半年的 EBIT 里含一笔北美批发客户破产相关的拨备，公司在全年口径上另给了一个剔除该笔的「正常化」EBIT"
            f"（€{normalised:,.0f} 千，占收入 {normalised / revenue * 100:.1f}%），而报告口径为 €{ebit_value:,.0f} 千、"
            f"占收入 {ebit_value / revenue * 100:.1f}%，比上一年的 {prior_margin:.1f}% 是"
            + ("下降的" if ebit_value / revenue * 100 < prior_margin else "上升的")
            + "。本页所有利润率一律用报告口径，正常化值只在本说明中出现，因为把一年的正常化值和另一年的报告值放在同一条线上会让方向反过来。")
    notes += [
        "公司在 2025 年年度报告中把一家做空机构就其俄罗斯业务提出的指控列为关键审计事项，审计师据此对相关批发交易执行了程序并出具了无保留意见，未确认相关或有负债。本页记录这一披露事实本身，不对指控作判断，也不发布任何第三方的结论。",
        "本页不发布市场一致预期、评级、目标价与估值。"
        + "；".join(([f"第{cn_ordinal(tracking)}节的{cn_count(len(next_list))}条阈值是本地研究设定，不是公司指引，"
                      "数值与方向取自本站对本期的季报分析第 8 节"] if next_list else [])
                    + ([f"第一节结算的{cn_count(len(prior_entries))}条阈值同样是本地研究设定，不是公司指引，"
                        "取自上一份季报分析"] if prior_entries else []))
        + ("。" if next_list or prior_entries else ""),
        "本页只发布公司披露值与可复算的简单派生值；D 标记代表 Derived / 自算。",
        "本页已知未接入：" + (kpi["unconnected"] + "以及 " if kpi is not None else "")
        + f"{half_cn(half)}之后的任何数据。",
        "业绩电话会内容仅用于定位公司已在申报文件中量化的项目与统计指引口径的披露与否，公开仓不复制原件或逐字内容。",
        "核对抽屉最后那张「AI capex 循环」是全站共用的跨页对照块，在每一页都逐字节相同，不是对本公司的判断。它追的是四家云厂现金资本开支到 NVDA 数据中心收入再到 TSM 晶圆这条链，本公司不在这条链的任何一环上；它在折叠的抽屉里，不参与本页的论证。",
    ]

    return {
        "schema_version": "quarterly-dashboard/bc-v1",
        "page": {"slug": "bc", "language": "zh-CN"},
        "company": {"ticker": "BC", "name": "Brunello Cucinelli S.p.A.",
                    "group": "luxury_brands", "accounting_standard": "IFRS"},
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · BC",
        "title": f"Brunello Cucinelli S.p.A. (BC)：{view['year']} 年{view['word']}业绩仪表盘",
        "subtitle": (f"截至 {latest['period_end']} · 发布 {latest['release_date']} · IFRS · 欧元列示 · 自然年财年 · "
                     "季度只发营收、完整损益一年两次 · 数据来自公司年报、半年报与季度营收公告"),
        "headline": headline,
        "brief": (f'<h4>本期{cn_count(len(cards))}条主线</h4><div class="takeaway-grid">'
                  + "".join(cards) + '</div>'),
        "source": ('Source: <a href="https://investor.brunellocucinelli.com/en/services/'
                   'archive/investor/press-releases" rel="noopener">'
                   'Brunello Cucinelli 投资者关系 · 新闻稿与业绩公告归档</a>。'
                   '公司在 Euronext Milan 上市，不是美国申报人，'
                   'EDGAR 上仅有存托银行为无保荐 ADR 提交的 F-6/424B3 文件，不含任何财务报表。'),
        "source_url": ("https://investor.brunellocucinelli.com/en/services/archive/"
                       "investor/press-releases"),
        "source_links": s["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": sections,
        "tables": tables,
        "notes": notes,
        "footer": "Brunello Cucinelli half-year results · 数据来自公司公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "bc.js"), payload, "bc")
    shell_dir = ROOT / "bc"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("BC", "bc"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"BC page: {charts} charts in {len(payload['sections'])} sections "
          f"+ {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
