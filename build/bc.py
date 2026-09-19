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

Second, and this is what the first section is about: the company guides revenue
growth every year in the same words -- "around 10%" -- and for years it never
said which currency basis it meant. The census of quantified forward statements
in its results calls (`guidance_basis_census`) finds none that states an
exchange-rate basis before December 2025. The basis is not a footnote: in a year
whose guidance range is one point wide, reported and constant-rate growth can
land on opposite sides of it.

**A roll edits `series/bc.json` and nothing else** (CLAUDE.md §9). The page's
period is the latest half: an H1 page reads the half against the year's
guidance, an H2 page reads the full year. Every period, count and figure is
computed from the series, and every sentence that states something the data
could stop saying (「连续四年」「三年停在」「全部达成」「同时高于」) is printed
only while the data says it. What belongs to one half -- the next thresholds and
why three of them broke, the reading of the channel jump, the list of items the
last call refused to quantify -- sits in blocks stamped with that half
(`next_kpi`, `half_story`); the company's targets for a year sit in
`company_targets` and are published only in that year. Fixed history stays in
code: the 2025 regional re-presentation, the 2025 provision for a North American
wholesale customer, the withdrawn lease-adjusted EBITDA, the Russia audit matter,
the end of the 2016-2023 margin climb, and the 30% wholesale target the company
once wrote down.

Published figures are company-reported or transparent arithmetic. Thresholds in
the tracking section are local research settings, not company guidance.
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
    headroom,
    headroom_exhibit,
    latest_block,
    number_exhibits,
    stamped_block,
    threshold_table,
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


# ── section one: the guidance and the basis it was never given on ────────────
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
def quarter_charts(s: dict, view: dict, story: dict | None) -> list[dict]:
    ch = s["channel_h1_eur_k"]
    geo = s["geography_h1_eur_k"]
    this_half = view["is_h1"] and ch["years"][-1] == view["year"]
    period_word = "本期" if this_half else f"{ch['years'][-1]} 年上半年"

    rev_g_cfx, rev_g_rep = view["cfx"], view["reported"]
    ebit_g, net_g = view["ebit_growth"], view["net_growth"]
    fx = rev_g_cfx - rev_g_rep
    if rev_g_cfx > net_g and 0 < fx < rev_g_cfx - net_g:
        ladder_title = (f"从收入到净利，四个增速一路掉了 {rev_g_cfx - net_g:.1f}pp，"
                        f"而其中只有 {fx:.1f}pp 发生在经营层面之上")
    else:
        ladder_title = (f"从收入到净利的四个增速：恒定汇率收入 {signed(rev_g_cfx)}、报告口径 {signed(rev_g_rep)}、"
                        f"EBIT {signed(ebit_g)}、净利 {signed(net_g)}")
    ladder_note = "四根柱子不是一条桥，是四个各自独立的同比增速，放在一起看落差在哪一段发生。"
    if fx > 0:
        ladder_note += f"汇率吃掉 {fx:.1f}pp；"
    else:
        ladder_note += f"汇率贡献了 {-fx:.1f}pp；"
    if ebit_g > rev_g_rep:
        ladder_note += (f"经营杠杆把它加回来 {ebit_g - rev_g_rep:.1f}pp，所以 EBIT 增速反而高于报告口径收入；")
    else:
        ladder_note += f"EBIT 增速比报告口径收入低 {rev_g_rep - ebit_g:.1f}pp；"
    if net_g < ebit_g:
        ladder_note += (f"真正的断层在 EBIT 之下 —— 净利只增 {net_g:.1f}%，"
                        f"落差 {ebit_g - net_g:.1f}pp 全部来自财务损益与税，与经营无关。")
    else:
        ladder_note += f"净利增速 {net_g:.1f}%，不低于 EBIT。"
    ladder_note += "增速之间不做加减，因为分母不同。"
    ladder = {
        "ref": "EX_LADDER",
        "kind": "bars_labeled",
        "title": ladder_title,
        "xlabels": ["收入（恒定汇率）", "收入（报告口径）", "EBIT", "净利润"],
        "values": [round(rev_g_cfx, 1), round(rev_g_rep, 1), round(ebit_g, 1), round(net_g, 1)],
        "fmt": "pct1", "label_fmt": "pct1", "yfmt": "pct1",
        "ylab": "同比 %",
        "note": ladder_note,
        "src_extra": "收入两个口径与 EBIT 由公司印出；净利润为公司印出的期间利润。",
    }

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
                   f"{'多' if d_who >= 0 else '少'}了 €{abs(d_who):,.0f} 千。")
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
                    f"{min(band):.1f}%–{max(band):.1f}%，看起来结构已经稳定"
                    + (f"；{story['mix_story']}" if story and this_half else "。"))
    else:
        mix_title = f"零售占比从 {share[0]:.1f}% 走到 {share[-1]:.1f}%"
        mix_note = ""
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
    return [ladder, bridge, mix, region]


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
def next_quarter_charts(s: dict, view: dict, kpi: dict | None) -> list[dict]:
    charts = []
    ahead = "下半年" if view["is_h1"] else "明年上半年"
    if kpi is not None:
        entries = kpi["quantified"]
        # listed in the order the page has always named them: margin, capex, debt
        company = [e for e in reversed(entries) if e["source"] == "company"]
        breached = [e for e in entries if headroom(e["direction"], e["threshold"], e["current"]) < 0]
        slow = [e for e in entries if e["cadence"] == "half"]
        charts.append(headroom_exhibit(
            f"{ahead}{cn_count(len(entries))}条阈值与当前值：距阈值的余量",
            entries, "current",
            (f"{cn_count(len(entries))}条统一换算成「距阈值的余量」，正值表示还在安全侧。"
             f"其中{cn_count(len(company))}条的阈值取自公司自己给出的年度目标（"
             + "、".join(e["target_words"] for e in company) + "），"
             f"{cn_count(len(entries) - len(company))}条是本页自设的观察线。"
             + (f"<b>当前有{cn_count(len(breached))}条已经越线</b>：{kpi['breach_note']}" if breached else
                "<b>当前没有一条越线。</b>")
             + (f"注意其中{cn_count(len(slow))}条一年只更新两次 —— 完整损益与资产负债表只在半年和全年出现。"
                if slow else "")),
            "阈值为本地研究设定，不是公司指引；当前值为公司披露值或本页自算（D）。",
        ))

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
    charts.append(ifrs)
    return charts


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
        "title": (f"年度营收增速 {len(yrs)} 年从 {max(rep):.1f}% 收敛到 {rep[-1]:.1f}%，"
                  "而指引一直是同一句「约 10%」"),
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

    settled = guidance_charts(s, view)
    highlights = quarter_charts(s, view, story)
    nxt = next_quarter_charts(s, view, kpi)
    routine = long_charts(s, view)

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
                  "—" if y not in gr["years"] else f"{gr['cfx'][gr['years'].index(y)]:+.1f}%"]
                 for i, y in enumerate(ch["years"])],
    }]
    ahead = "下半年" if view["is_h1"] else "明年上半年"
    if kpi is not None:
        tables.append(threshold_table(first_table + len(tables), f"{ahead}阈值与当前值（原始单位）",
                                      kpi["quantified"], "current", "当前值"))
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
    if net_g < ebit_g:
        cards.append(
            '<article><span>本期</span><b>断层在 EBIT 以下，不在收入</b>'
            f'<p>恒定汇率收入 {signed(view["cfx"])}、EBIT {signed(ebit_g)}，'
            f'经营层面没有问题；净利润只增 {signed(net_g)}，'
            f'{ebit_g - net_g:.1f}pp 的落差来自财务损益与税。</p></article>')
    if this_half and stalled and grew >= 2:
        cards.append(
            '<article><span>结构</span><b>批发停住，增长只剩一条腿</b>'
            f'<p>半年收入增量 €{d_tot:,.0f} 千里零售占 {d_ret / d_tot * 100:.1f}%；'
            f'批发绝对额一年只多了 €{d_who:,.0f} 千，'
            f'而它此前连续{cn_count(grew)}年增长。</p></article>')

    sections = [
        {"id": "settled", "short": "指引与口径", "title": "公司的指引，和它没说的口径",
         "description": ("公司每年用同一句话给指引：营收增长「约 10%」。"
                         "这一节先看这句话在报告口径与恒定汇率下会得到相反的结论，"
                         "再看口径这一栏在申报里是什么时候才开始被填上的。"),
         "exhibits": settled_ex},
        {"id": "quarter_highlights", "short": "本期重点", "title": "本期重点",
         "description": "增速在哪一段掉下来、收入增量由谁贡献、渠道与区域结构走到了哪里。",
         "exhibits": highlight_ex},
    ]
    if kpi is not None:
        breached = sum(1 for e in kpi["quantified"] if headroom(e["direction"], e["threshold"], e["current"]) < 0)
        next_words = (f"{cn_count(len(kpi['quantified']))}条阈值统一用「距阈值余量」口径，"
                      f"其中{cn_count(breached)}条当前已越线；另有一条公司发布"
                      f"{cn_count(sum(1 for v in s['ifrs16_disclosure_decay']['both_bases_printed'] if v))}"
                      "年后停掉的口径，单独列出。")
    else:
        next_words = (f"一条公司发布{cn_count(sum(1 for v in s['ifrs16_disclosure_decay']['both_bases_printed'] if v))}"
                      "年后停掉的口径。")
    sections.append({"id": "next_quarter", "short": f"{ahead}跟踪", "title": f"{ahead}要跟踪什么",
                     "description": next_words, "exhibits": next_ex})
    sections.append({"id": "routine", "short": "长期常规", "title": "长期常规跟踪",
                     "description": "季度收入的来源构成、半年利润率的长期路径、增速收敛与净负债。",
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
    record += [(f"{y}H1", r, c) for y, r, c in zip(gr["years"], gr["reported"], gr["cfx"])]
    spreads = [abs(r - c) for _, r, c in record]
    g_hist = s["annual_revenue_guidance"]
    dual = [i for i, low in enumerate(g_hist["cfx_leg_low"]) if low is not None and g_hist["final_basis"][i] == "reported"]
    nd = s["net_debt_h1_eur_k"]
    fy_norm = [(y, n, e, r) for y, n, e, r in zip(a["years"], a["ebit_normalised_eur_k"], a["ebit_eur_k"], a["revenue_eur_k"])
               if n is not None and y == 2025]
    company = [e for e in kpi["quantified"] if e["source"] == "company"] if kpi is not None else []
    fx = ifrs16_facts(s)
    debt_label = half_cn(str(nd["years"][-1]) + "H1")
    debt_times = cn_count(int(nd["post_ifrs16"][-1] / nd["pre_ifrs16"][-1]))
    notes = [
        f"本页按「{order}」{cn_count(len(sections))}段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
        "公司在 Euronext Milan 上市，按 IFRS 以欧元列报，财年即自然年。它不是美国证券法下的申报人：EDGAR 上以其名义存在的唯一实体只有七份文件，全部是存托银行为一只无保荐 ADR 提交的 F-6 与 424B3，依据 Rule 12g3-2(b) 豁免，不含任何财务报表。本站其他公司页依赖的 10-Q/10-K 渲染报表对本公司不存在，本页全部数据来自公司自己的年度财务报告、半年度财务报告与季度营收公告。",
        "披露节奏是本页所有图表形状的来源：收入一年公布四次（第一季度、半年、九个月、全年），完整损益表一年只有两次（半年与全年）。公司从未把第二、第三、第四季度或下半年作为独立期间公布过，它印出来的每一个数都是「截至某日累计」。"
        f"因此本页 {len(q['periods'])} 个季度里只有 {printed_q} 个是公司印出的，{len(h['periods'])} 个半年里只有 {printed_h} 个是公司印出的，其余由相邻两次累计披露相减得到，图与表中逐格标明。",
        f"相减这件事只有一处可以外部验证：公司在正文叙述里{cn_count(len(quoted))}次提到过单季第三季度的规模，而 9M 减 H1 的结果与这{cn_count(len(quoted))}次逐一吻合（{quoted_text}，单位百万欧元）。「四个季度相加等于全年」不构成验证，因为第四季度本来就是用全年减九个月得到的 —— 一个从被检查对象推导出自己期望值的检查不可能失败，本页不把它算作证据。",
        f"指引口径是本页第一节的主题。{cn_count(cen['calls_covered'])}场业绩会里共 {cen['quantified_rows']} 条带数字的前瞻表述，其中 {cen['fx_basis_unstated']} 条没有说明汇率口径；说明了的 {cen['fx_basis_stated']} 条全部发布于 {first[:4]} 年 {int(first[5:7])} 月 {int(first[8:10])} 日或之后。"
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
        + (f"第{cn_ordinal(tracking)}节的{cn_count(len(kpi['quantified']))}条阈值是本地研究设定，不是公司指引；"
           f"其中{cn_count(len(company))}条的数值取自公司自己给出的年度目标，"
           f"{cn_count(len(kpi['quantified']) - len(company))}条为本页自设的观察线。" if kpi is not None else ""),
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
