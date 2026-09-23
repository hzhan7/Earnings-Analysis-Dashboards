#!/usr/bin/env python3
"""Build the AMD quarterly-results page.

Same four-part, chart-led shape as the other semiconductor pages (上季兑现 →
本季重点 → 下季跟踪 → 长期常规). AMD reports calendar quarters (the fiscal year
ends on the last Saturday of December), so the page's quarter labels are the
company's own.

Three things about AMD's record shape the page.

First, the guidance record reaches back to 2016 but changes form twice. Through
the Q4 2017 outlook the release guided revenue as a sequential percentage plus or
minus three points, and the gross-margin figure sat in the CFO commentary filed
beside it (EX-99.2); from the Q1 2018 outlook on, revenue is a dollar amount plus
or minus a band and non-GAAP gross margin is in the release itself. Both are
filed documents, so all forty-three guided quarters are scored, each against the
basis it was guided on: the 2016-2017 ranges are computed from the prior
quarter's revenue as that release printed it, and each guided quarter is scored
against its own first print.

Second, 2016 and 2017 exist on two revenue bases. AMD adopted ASC 606 with full
retrospective restatement in 2018; the four 2017 quarters were restated, 2016 was
restated only as a year. Level series use the newest print (2016 on ASC 605,
2017 onward on ASC 606); growth rates are computed on one basis at a time.

Third, the segment structure changed in 2022 (Data Center / Client / Gaming /
Embedded, recast from Q2 2021) and again in 2025 (Client and Gaming became one
reportable segment, revenue still split). Before Q2 2021 there is no data-center
line at all -- servers sat with game-console chips in "Enterprise, Embedded and
Semi-Custom" -- so the four-segment charts start there, and the old two-segment
record is drawn separately.

A roll edits ``series/amd.json`` and nothing else (CLAUDE.md §9). Every number
the prose prints is computed here from the series; what only one quarter has --
last quarter's open questions, the balance-sheet exposure read from one 10-Q,
the call's guidance items -- lives in period-stamped blocks read through
`board.stamped_block`.
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
    delivery_band,
    fill_story,
    latest_block,
    midpoint_deviation,
    minus_sign,
    number_exhibits,
    stamped_block,
    threshold_exhibit,
    threshold_table,
    unit_text,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "amd.json"
DATA_DIR = ROOT / "data"

AUDIT_WORDS = {"unaudited": "未审计", "audited": "已审计"}
DAYS_PER_QUARTER = 91


# ── small helpers ────────────────────────────────────────────────────────────
def compact(period: str) -> str:
    """``'Q1 2026'`` → ``"Q1'26"``."""
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return minus_sign(f"{value:+.{digits}f}{suffix}")


def pct(current: float, base: float) -> float:
    return (current / base - 1) * 100.0


def num(value: float, digits: int = 1) -> str:
    return minus_sign(f"{value:.{digits}f}")


def usd_m(value: float) -> str:
    return f"{'−' if value < 0 else ''}US${abs(value):,.0f}M"


def usd_b(value_m: float, digits: int = 1) -> str:
    return f"{'−' if value_m < 0 else ''}US${abs(value_m) / 1000:,.{digits}f}B"


def rounded(values, digits: int = 6):
    return [None if v is None else round(v, digits) + 0.0 for v in values]


def ratio(numerators, denominators, scale: float = 100.0):
    return [None if n is None or d in (None, 0) else n / d * scale
            for n, d in zip(numerators, denominators)]


def half_label(year: int, half: int) -> str:
    return f"{year} {'上' if half == 1 else '下'}半年"


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
            left = re.search(r"\{EX_[A-Z_]+\}", text)
            if left:
                raise ValueError(f"{left.group(0)} in {key!r} of {exhibit['title'][:30]!r} names a chart "
                                 "that is not on the page")
            exhibit[key] = text
    return exhibits


def revenue_yoy(staging: dict) -> list[float | None]:
    """Year-over-year growth, each on one revenue basis.

    2016 is compared with 2015 as printed (ASC 605 both sides). 2017 is compared
    on ASC 605 both sides too -- the basis the company printed that year; the
    series keeps the 2017 first prints for exactly this. From 2018 each quarter
    is compared with the restated (ASC 606) year-ago quarter, as the company
    printed it.
    """
    fin = staging["financials"]
    periods = staging["periods"]
    revenue = fin["revenue_usd_m"]
    old = staging["asc605_2017"]
    old_2017 = dict(zip(old["quarters"], old["revenue_usd_m"]))
    prior_2015 = fin["revenue_prior_year_2015_usd_m"]
    out = []
    for i, period in enumerate(periods):
        year = int(period[-4:])
        if year == 2016:
            out.append(pct(revenue[i], prior_2015[i]))
        elif year == 2017:
            out.append(pct(old_2017[period], revenue[i - 4]))
        else:
            out.append(pct(revenue[i], revenue[i - 4]))
    return out


def payable_days(staging: dict) -> list[float]:
    payables = staging["balance_sheet_usd_m"]["payables_incl_related"]
    cost = staging["financials"]["cost_of_sales_usd_m"]
    return [p / c * DAYS_PER_QUARTER for p, c in zip(payables, cost)]


def inventory_days(staging: dict) -> list[float]:
    inventory = staging["balance_sheet_usd_m"]["inventory"]
    cost = staging["financials"]["cost_of_sales_usd_m"]
    return [v / c * DAYS_PER_QUARTER for v, c in zip(inventory, cost)]


def guidance_record(staging: dict) -> dict:
    """The guided quarters, each scored against the actual it was guided on."""
    record = staging["guidance_history"]
    quarters = record["quarters"]
    like = record.get("like_for_like_actuals", {})
    actual_rev, actual_gm, actual_opex = [], [], []
    for i, quarter in enumerate(quarters):
        revenue = record["actual_revenue_usd_m"][i]
        gross = record["actual_non_gaap_gross_profit_usd_m"][i]
        opex = record["actual_non_gaap_opex_usd_m"][i]
        if quarter in like:
            revenue = like[quarter]["revenue_usd_m"]
            gross = like[quarter]["non_gaap_gross_profit_usd_m"]
            opex = gross - like[quarter]["non_gaap_operating_income_usd_m"]
        actual_rev.append(revenue)
        # Scored at the two decimals the page prints: Q2 2020 is 44.00% against
        # a 44% guide, and a sixth decimal must not turn that into a miss.
        actual_gm.append(None if revenue is None else round(gross / revenue * 100, 2))
        actual_opex.append(opex)
    return {
        "quarters": quarters,
        "low": record["revenue_low_usd_m"],
        "mid": record["revenue_mid_usd_m"],
        "high": record["revenue_high_usd_m"],
        "gm": record["non_gaap_gm_guide_pct"],
        "actual_revenue": actual_rev,
        "actual_gm": actual_gm,
        "opex": record["non_gaap_opex_guide_usd_m"],
        "actual_opex": actual_opex,
    }


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    fin = staging["financials"]
    seg = staging["segments"]
    dc = seg["data_center_usd_m"]
    gm = fin["non_gaap_gross_profit_usd_m"][-1] / fin["revenue_usd_m"][-1] * 100
    return [f"Revenue ${fin['revenue_usd_m'][-1] / 1000:.1f}B",
            f"Data Center {pct(dc[-1], dc[-5]):+.0f}%",
            f"Gross margin {gm:.1f}%"]


# ── section one: last quarter's questions and the guidance record ────────────
def followup_chart(block: dict | None, prior_label: str, values: dict[str, str]) -> dict | None:
    if block is None:
        return None
    labels, counts = block["labels"], block["counts"]
    total = sum(counts)
    if total != block["total"] or len(block["items"]) != total:
        raise ValueError("followup_closure: counts, total and items disagree")
    for label, count in zip(labels, counts):
        if sum(1 for item in block["items"] if item["verdict"] == label) != count:
            raise ValueError(f"followup_closure: {label} count does not match its items")
    verdict = "、".join(f"{c} 条{l}" for l, c in zip(labels, counts) if c)
    lines = "".join(f"<br>{i + 1}. {item['question']} —— <b>{item['verdict']}</b>：{fill_story(item['evidence'], values)}"
                    for i, item in enumerate(block["items"]))
    return {
        "kind": "bars_labeled",
        "title": f"上季 {total} 条待验证问题：{verdict}",
        "xlabels": labels,
        "values": counts,
        "legend": "问题条数",
        "fmt": "f0",
        "yfmt": "f0",
        "label_fmt": "f0",
        "ylab": "条",
        "note": fill_story(block["note"], values) + lines,
        "src_extra": (f"问题清单来自 {prior_label} 本地分析稿的 follow-up；"
                      "验证结果依据本季业绩 8-K、10-Q 与业绩电话会。"),
    }


def guidance_lag_days(staging: dict) -> tuple[int, int]:
    """Days between the start of a guided quarter and the release that guided it.

    AMD reports a quarter three to six weeks after it ends, and the outlook for
    the next quarter goes out in the same release -- so every guide on this page
    was published after the quarter it guides had already begun.
    """
    import datetime
    record = staging["guidance_history"]
    ends = dict(zip(staging["periods"], staging["period_ends"]))
    lags = []
    for i, quarter in enumerate(record["quarters"][1:], start=1):
        previous = record["quarters"][i - 1]
        if previous not in ends:
            continue
        start = datetime.date.fromisoformat(ends[previous]) + datetime.timedelta(days=1)
        lags.append((datetime.date.fromisoformat(record["release_dates"][i]) - start).days)
    return min(lags), max(lags)


def guidance_charts(staging: dict) -> tuple[list[dict], dict, dict]:
    rec = guidance_record(staging)
    record = staging["guidance_history"]
    lag_lo, lag_hi = guidance_lag_days(staging)
    timing = f"被指引季度开始 {lag_lo}–{lag_hi} 天后"
    quarters = rec["quarters"]
    labels = [compact(q) for q in quarters]
    low_b = [v / 1000 for v in rec["low"]]
    high_b = [v / 1000 for v in rec["high"]]
    actual_b = [None if v is None else v / 1000 for v in rec["actual_revenue"]]
    finished = [i for i, v in enumerate(rec["actual_revenue"]) if v is not None]
    below = [i for i in finished if rec["actual_revenue"][i] < rec["low"][i]]
    above = [i for i in finished if rec["actual_revenue"][i] > rec["high"][i]]
    forms = record["form"]
    first_usd = forms.index("usd")
    notes_by_q = record["annotations"]

    last = finished[-1]
    last_word = ("超出上限" if last in above else "跌破下限" if last in below else "落在区间内")
    band_note = (
        f"{labels[0]}–{labels[first_usd - 1]} 的指引是「环比 ±{record['sequential_band_pct'][0]} 个百分点」，"
        "本页用该份新闻稿自己印出的上季收入换算成美元区间（D）；"
        f"自 {labels[first_usd]} 起公司直接给美元区间。"
        + f"本季 {labels[last]} 实际 {usd_m(rec['actual_revenue'][last])}，{last_word}"
        + (f"（上限 {usd_m(rec['high'][last])}）" if last in above else "") + "。"
        + "".join(f"{labels[quarters.index(q)]}：{text}" for q, text in record["revenue_annotations"].items()
                  if q in quarters and quarters.index(q) in finished)
    )
    rev_band = delivery_band(
        "EX_REV_BAND", "收入", labels, rounded(low_b), rounded(high_b), rounded(actual_b),
        fmt="usd1", ylab="US$B", unit="US$B", venue="业绩发布", timing=timing,
        src_extra=("2018 年起的区间来自各季业绩 8-K EX-99.1 的 Current Outlook 段；2016–2017 年的环比指引同段可见，"
                   "毛利率与费用指引在同日提交的 CFO commentary（EX-99.2）。实际值取被指引季度自己那份新闻稿的首次印出值。"),
        extra_note=band_note, xstep=4,
    )
    rev_dev = midpoint_deviation(
        "EX_REV_DEV", "收入", labels, rec["low"], rec["high"], rec["actual_revenue"],
        mode="pct", window=len(finished), label=None, bar_labels=False, xstep=4,
        src_extra="偏离 = 实际收入 ÷ 指引区间中值 − 1（D）。",
        extra_note="",
    )
    # GM guidance: a point figure, "approximately X%".
    gm_actual = rec["actual_gm"]
    gm_dev = [None if gm_actual[i] is None else gm_actual[i] - rec["gm"][i] for i in range(len(quarters))]
    near = sum(1 for i in finished if abs(gm_dev[i]) < 0.5)
    biggest_up = max(finished, key=lambda i: gm_dev[i])
    biggest_down = min(finished, key=lambda i: gm_dev[i])
    wording = record["gm_wording"]
    plain = [i for i, w in enumerate(wording) if w == "gross margin"]
    if plain:
        fin = staging["financials"]
        by_period = {p: (g, n, r) for p, g, n, r in zip(staging["periods"], fin["gaap_gross_profit_usd_m"],
                                                           fin["non_gaap_gross_profit_usd_m"], fin["revenue_usd_m"])}
        gm_gaps = {i: (by_period[quarters[i]][1] - by_period[quarters[i]][0]) / by_period[quarters[i]][2] * 100
                for i in plain}
        plain_gap_at = max(gm_gaps, key=lambda i: abs(gm_gaps[i]))
        plain_gap = gm_gaps[plain_gap_at]
        plain_rest = max((abs(v) for i, v in gm_gaps.items() if i != plain_gap_at), default=0.0)
    gm_note = (
        "实际值 = 该季新闻稿印出的 non-GAAP 毛利美元数 ÷ 收入（D，两位小数）；公司自己的标题只印到整数百分比。"
        f"{cn_count(len(finished))}季里 {near} 季与指引相差不到 0.5pp。"
        + (f"{labels[plain[0]]}–{labels[plain[-1]]} 的 CFO commentary 写的是「Gross margin」未注明口径，本页按 non-GAAP 比较"
           f"（那几季 GAAP 与 non-GAAP 毛利率的差距最大是 {labels[plain_gap_at]} 的 {plain_gap:.1f}pp"
           + (f"，{notes_by_q[quarters[plain_gap_at]]}" if quarters[plain_gap_at] in notes_by_q else "")
           + (f"，其余不超过 {plain_rest:.1f}pp）。" if len(plain) > 1 else "）。") if plain else "")
        + f"最大的正偏离是 {labels[biggest_up]} 的 {signed(gm_dev[biggest_up], 2, 'pp')}"
        + (f"：{notes_by_q[quarters[biggest_up]]}" if quarters[biggest_up] in notes_by_q else "。")
        + f"最大的负偏离是 {labels[biggest_down]} 的 {signed(gm_dev[biggest_down], 2, 'pp')}"
        + (f"：{notes_by_q[quarters[biggest_down]]}" if quarters[biggest_down] in notes_by_q else "。")
    )
    gm_band = delivery_band(
        "EX_GM_BAND", "non-GAAP 毛利率", labels, rec["gm"], rec["gm"], rounded(gm_actual),
        fmt="pct1", ylab="毛利率", unit="%", venue="业绩发布", point=True, timing=timing,
        src_extra="指引为各季业绩 8-K 的 Current Outlook 段（2018 年一季度及以前为同日 CFO commentary 的 Outlook 段）。",
        extra_note=gm_note, xstep=4,
    )
    gm_dev_chart = midpoint_deviation(
        "EX_GM_DEV", "non-GAAP 毛利率", labels, rec["gm"], rec["gm"], rounded(gm_actual),
        mode="pp", window=len(finished), bar_labels=False, xstep=4,
        src_extra="偏离 = 实际 non-GAAP 毛利率 − 指引值（D）。",
        extra_note="",
    )
    opex_guide = rec["opex"]
    opex_actual = rec["actual_opex"]
    scored = [i for i in finished if opex_guide[i] is not None]
    over = [i for i in scored if opex_actual[i] > opex_guide[i]]
    same = [i for i in scored if opex_actual[i] == opex_guide[i]]
    streak = 0
    for i in reversed(scored):
        if opex_actual[i] <= opex_guide[i]:
            break
        streak += 1
    gaps = [labels[i] for i in finished if opex_guide[i] is None]
    docs = record["opex_guide_document"]
    first_slides = next(i for i, d in enumerate(docs) if d and d.startswith("业绩幻灯片"))
    opex_note = (
        "费用指引不在新闻稿正文里：2016 年一季度到 2018 年一季度写在同日提交的 CFO commentary，"
        f"{labels[first_slides]} 起写在业绩幻灯片（两者都是业绩 8-K 的 EX-99.2）"
        + (f"；{gaps[0]}–{gaps[-1]} 这 {len(gaps)} 季的业绩 8-K 只有新闻稿一个附件，没有载有费用指引的附件，本图留空。"
           if gaps else "。")
        + (f"<b>最近 {streak} 季连续高于自己的指引</b>"
           + (f"（{labels[scored[-streak]]}–{labels[scored[-1]]}）" if streak > 1 else "") + "。"
           if streak else f"最近一季 {labels[scored[-1]]} 没有超出指引。")
        + "实际值取被指引季度自己那份新闻稿的首次印出值，与指引同一口径；"
        "2025 年的新闻稿曾把 2024 年各季的 non-GAAP 营业费用下调重印，若按重印值计分，2024 年的结论会不同 —— 本页按当时的口径计分。"
    )
    opex_band = delivery_band(
        "EX_OPEX_BAND", "non-GAAP 营业费用", labels,
        rounded([None if v is None else v / 1000 for v in opex_guide]),
        rounded([None if v is None else v / 1000 for v in opex_guide]),
        rounded([None if v is None else v / 1000 for v in opex_actual]),
        fmt="usd2", ylab="US$B", unit="US$B", venue="业绩发布", point=True, timing=timing,
        src_extra="指引见 CFO commentary 与业绩幻灯片（业绩 8-K EX-99.2）的 Outlook 页；实际值为被指引季度新闻稿的 non-GAAP 营业费用首次印出值。",
        extra_note=opex_note, xstep=4,
    )
    opex_dev = midpoint_deviation(
        "EX_OPEX_DEV", "non-GAAP 营业费用", labels, opex_guide, opex_guide, opex_actual,
        mode="pct", window=len(scored), bar_labels=False, xstep=4,
        src_extra="偏离 = 实际 non-GAAP 营业费用 ÷ 指引值 − 1（D）；正值 = 花得比指引多。",
        extra_note="",
        lead="正值 = 实际费用高于公司自己的指引，也就是花得比说的多；<b>方向与收入那张相反</b>。",
    )
    table_rows = []
    for i, quarter in enumerate(quarters):
        form = ("环比 " + signed(record["sequential_pct"][i], 0) + f" ±{record['sequential_band_pct'][i]}pp"
                if forms[i] == "sequential_pct" else
                f"US${rec['mid'][i] / 1000:g}B ± US${(rec['high'][i] - rec['mid'][i]):.0f}M")
        actual = rec["actual_revenue"][i]
        table_rows.append([
            quarter,
            form,
            f"{usd_m(rec['low'][i])} – {usd_m(rec['high'][i])}" + (" D" if forms[i] == "sequential_pct" else ""),
            "—" if actual is None else usd_m(actual),
            "—" if actual is None else ("高于上限" if actual > rec["high"][i] else
                                        "低于下限" if actual < rec["low"][i] else "区间内"),
            f"约 {rec['gm'][i]:g}%",
            "—" if gm_actual[i] is None else f"{gm_actual[i]:.2f}% D",
            "—" if gm_actual[i] is None else signed(gm_dev[i], 2, "pp") + " D",
            "—" if opex_guide[i] is None else f"约 {usd_m(opex_guide[i])}",
            "—" if opex_actual[i] is None or opex_guide[i] is None else usd_m(opex_actual[i]),
        ])
    table = {
        "title": f"指引兑现全表（{len(quarters)} 季，含尚未完结的一季）",
        "headers": ["被指引季度", "收入指引原文形式", "收入区间", "实际收入", "位置",
                    "non-GAAP 毛利率指引", "实际 non-GAAP 毛利率", "偏离", "non-GAAP 营业费用指引", "实际 non-GAAP 营业费用"],
        "rows": table_rows,
    }
    facts = {
        "finished": len(finished), "above": len(above), "below": len(below),
        "inside": len(finished) - len(above) - len(below),
        "gm_above": sum(1 for i in finished if gm_dev[i] > 0),
        "gm_below": sum(1 for i in finished if gm_dev[i] < 0),
        "last_rev_dev": pct(rec["actual_revenue"][last], rec["mid"][last]),
        "last_gm_dev": gm_dev[last],
        "next_mid": rec["mid"][-1], "next_band": rec["high"][-1] - rec["mid"][-1],
        "next_gm": rec["gm"][-1],
        "opex_scored": len(scored), "opex_over": len(over), "opex_same": len(same), "opex_streak": streak,
        "opex_last_dev": pct(opex_actual[last], opex_guide[last]),
        "next_opex": opex_guide[-1],
    }
    return [rev_band, rev_dev, gm_band, gm_dev_chart, opex_band, opex_dev], table, facts


# ── section two ──────────────────────────────────────────────────────────────
def revenue_chart(staging: dict, labels: list[str], yoy: list[float]) -> dict:
    revenue = staging["financials"]["revenue_usd_m"]
    now, prev_yoy = yoy[-1], yoy[-2]
    higher = [i for i in range(len(yoy) - 1) if yoy[i] >= now]
    since = (f"同比增速是 {labels[higher[-1]]}（{signed(yoy[higher[-1]])}）之后最高" if higher
             else f"同比增速是 {len(labels)} 季最高")
    title = (f"收入 {usd_b(revenue[-1])}、同比 {signed(now)}，"
             + (since if now > prev_yoy else f"同比增速较上季的 {prev_yoy:.1f}% 回落"))
    peak = max(range(len(yoy)), key=lambda i: yoy[i])
    return {
        "kind": "gs_bar",
        "title": title,
        "xlabels": labels,
        "xstep": 4,
        "values": rounded([v / 1000 for v in revenue]),
        "legend": "季度收入",
        "fmt": "usd1",
        "yfmt": "usd1",
        "label_fmt": "usd1",
        "ylab": "US$B",
        "ylab2": "同比增速",
        "yoy": {"name": "收入 YoY (RHS) D", "values": rounded(yoy), "color": "GREEN", "yfmt": "pct0"},
        "note": (f"环比 {signed(pct(revenue[-1], revenue[-2]))}。{len(labels)} 季里同比最高的是 {labels[peak]} 的 "
                 f"{yoy[peak]:.1f}%。<b>2016 年四季是 ASC 605 口径</b>（公司 2018 年全面追溯采用 ASC 606 时只按年重述 2016，"
                 "没有季度数）；2017 年起的柱是 ASC 606 口径。增速逐年按同一口径算：2016、2017 两年用 ASC 605 两端，"
                 "2018 年起用重述后的上年同季 —— 都是公司当年自己印出的比较口径。"),
        "src_extra": "各季业绩 8-K EX-99.1 合并损益表的三个月列，同一季被 2–3 份新闻稿重复印出，取最新一次；增速为自算 D。",
    }


def segment_charts(staging: dict) -> list[dict]:
    seg = staging["segments"]
    quarters = seg["quarters"]
    labels = [compact(q) for q in quarters]
    fin = staging["financials"]
    offset = staging["periods"].index(quarters[0])
    revenue = fin["revenue_usd_m"][offset:]
    dc, client, gaming, emb = (seg["data_center_usd_m"], seg["client_usd_m"],
                               seg["gaming_usd_m"], seg["embedded_usd_m"])
    for i, q in enumerate(quarters):
        if dc[i] + client[i] + gaming[i] + emb[i] != revenue[i]:
            raise ValueError(f"segments do not sum to revenue in {q}")
    share = [d / r * 100 for d, r in zip(dc, revenue)]
    dc_yoy = pct(dc[-1], dc[-5])
    peak_share = max(range(len(share)), key=lambda i: share[i])
    stack = {
        "kind": "stacked_dual",
        "title": (f"数据中心 {usd_b(dc[-1], 2)}、同比 {signed(dc_yoy, 0)}，占收入 {share[-1]:.1f}%"
                  + ("，是四分部口径以来最高" if peak_share == len(share) - 1 else "")),
        "xlabels": labels,
        "xrot": 90,
        "stacks": [
            {"name": "数据中心", "color": "NAVY", "values": rounded([v / 1000 for v in dc])},
            {"name": "客户端", "color": "MBLUE", "values": rounded([v / 1000 for v in client])},
            {"name": "游戏", "color": "BLUE", "values": rounded([v / 1000 for v in gaming])},
            {"name": "嵌入式", "color": "GOLD", "values": rounded([v / 1000 for v in emb])},
        ],
        "line": {"name": "数据中心占收入 (RHS) D", "color": "GREEN", "values": rounded(share),
                 "yfmt": "pct0", "ymax": 100},
        "fmt": "usd1",
        "yfmt": "usd1",
        "label_fmt": "usd1",
        "ylab": "US$B",
        "ylab2": "%",
        "note": (f"<b>四段之和逐季等于合并损益表的收入，差额为零。</b>这张图从 {labels[0]} 开始是披露边界，不是取数边界："
                 "四分部口径自 2022 年二季度起启用、只回溯到上年同季；在那之前服务器 CPU 与游戏机芯片同在「企业、嵌入式与半定制」一个分部里，"
                 f"没有可以单独读出的数据中心收入（旧口径见 Exhibit {{EX_LEGACY}}）。游戏本季 {usd_m(gaming[-1])}、同比 "
                 f"{signed(pct(gaming[-1], gaming[-5]), 0)}，客户端 {usd_m(client[-1])}、同比 {signed(pct(client[-1], client[-5]), 0)}；"
                 "公司自 2025 年一季度起把客户端与游戏并成一个报告分部，收入仍分开印。"),
        "src_extra": "各季业绩 8-K EX-99.1 的分部与分解收入表；占比为自算 D。",
    }
    dc_oi, cg_oi, emb_oi = seg["data_center_oi_usd_m"], seg["client_gaming_oi_usd_m"], seg["embedded_oi_usd_m"]
    dc_m = [o / r * 100 for o, r in zip(dc_oi, dc)]
    cg_m = [o / (c + g) * 100 for o, c, g in zip(cg_oi, client, gaming)]
    emb_m = [o / r * 100 for o, r in zip(emb_oi, emb)]
    worst = min(range(len(dc_m)), key=lambda i: dc_m[i])
    episodes = seg.get("episodes", {})
    margins = {
        "kind": "lines",
        "title": (f"分部营业利润率：数据中心 {dc_m[-1]:.1f}%，客户端与游戏 {cg_m[-1]:.1f}%"
                  f"（同比 {signed(cg_m[-1] - cg_m[-5], 1, 'pp')}），嵌入式 {emb_m[-1]:.1f}%"),
        "xlabels": labels,
        "xrot": 90,
        "series": [
            {"name": "数据中心", "values": rounded(dc_m), "color": "NAVY"},
            {"name": "客户端与游戏", "values": rounded(cg_m), "color": "MBLUE"},
            {"name": "嵌入式", "values": rounded(emb_m), "color": "GOLD"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "分部营业利润率",
        "note": (f"数据中心最低的一格是 {labels[worst]} 的 {num(dc_m[worst])}%"
                 + (f"：{episodes[quarters[worst]]}" if quarters[worst] in episodes else "。")
                 + ("分部营业利润不含股权激励、无形资产摊销与并购相关费用，公司把它们放在「All Other」："
                    f"这 {len(quarters)} 季里 All Other 每一季都是负数，所以三个分部的利润加起来每季都高于公司的 GAAP 营业利润。"
                    if all(v < 0 for v in seg["all_other_oi_usd_m"]) else
                    "分部营业利润不含股权激励、无形资产摊销与并购相关费用，公司把它们放在「All Other」。")
                 + "客户端与游戏的利润在 2025 年以前按两个分部印，本页相加成一条。"),
        "src_extra": "各季业绩 8-K EX-99.1 的分部营业利润；利润率为自算 D。",
    }
    return [stack, margins]


def eps_chart(block: dict | None) -> dict | None:
    if block is None:
        return None
    quarters = block["quarters"]
    gaap, non_gaap = block["gaap_eps_usd"], block["non_gaap_eps_usd"]
    gains = block["long_term_investment_gains_usd_m"]
    gaap_qoq = pct(gaap[0], gaap[1])
    ng_qoq = pct(non_gaap[0], non_gaap[1])
    return {
        "kind": "grouped_bars",
        "title": (f"GAAP 每股收益环比 {signed(gaap_qoq)}、non-GAAP {signed(ng_qoq)}"
                  + (f"：GAAP 里有 {usd_m(gains[0])} 长期投资净收益，non-GAAP 不含" if gains[0] else "")),
        "xlabels": [compact(q) for q in reversed(quarters)],
        "groups": [
            {"name": "GAAP 摊薄每股收益", "color": "NAVY", "values": list(reversed(gaap))},
            {"name": "non-GAAP 摊薄每股收益", "color": "GOLD", "values": list(reversed(non_gaap))},
        ],
        "bar_labels": True,
        "fmt": "usd2",
        "yfmt": "usd2",
        "label_fmt": "usd2",
        "ylab": "US$/股",
        "note": (f"GAAP 净利 {usd_m(block['gaap_net_income_usd_m'][0])} 里有 {usd_m(gains[0])} 的长期投资净收益"
                 f"（每股 US${block['long_term_investment_gains_per_share_usd'][0]:.2f}），上季这一项只有 {usd_m(gains[1])}；"
                 "non-GAAP 把它剔除。" + block.get("reading", "")),
        "src_extra": "三季同取本季业绩 8-K EX-99.1 的 GAAP/non-GAAP 对账表；环比为自算 D。",
    }


def cash_quality_chart(staging: dict, dpo_chart: bool) -> dict:
    wc = staging["working_capital_cash_flow_usd_m"]
    quarters = wc["quarters"][-8:]
    offset = staging["periods"].index(quarters[0])
    ocf = staging["cash_flow_usd_m"]["operating"][offset:]
    ap = wc["accounts_payable_change"][-8:]
    ex_ap = [o - a for o, a in zip(ocf, ap)]
    rising = ap[-1] > 0
    if rising:
        title = (f"经营现金流 {usd_m(ocf[-1])}，其中 {usd_m(ap[-1])} 来自应付账款增加；"
                 f"扣掉这一项是 {usd_m(ex_ap[-1])} D")
        lead = (f"应付账款的增加相当于本季经营现金流的 {ap[-1] / ocf[-1] * 100:.0f}%。"
                "它说的是<b>这一季的经营现金流里有一块来自付款节奏</b>：下季若应付天数回落，这一块会反向流出")
    else:
        title = (f"经营现金流 {usd_m(ocf[-1])}，应付账款减少占用了 {usd_m(-ap[-1])}；"
                 f"不计这一项是 {usd_m(ex_ap[-1])} D")
        lead = "本季应付账款是减少的，付款节奏在拖累而不是撑高经营现金流"
    return {
        "kind": "grouped_bars",
        "title": title,
        "xlabels": [compact(q) for q in quarters],
        "groups": [
            {"name": "经营现金流（持续经营）", "color": "NAVY", "values": ocf},
            {"name": "其中：应付账款变动", "color": "GOLD", "values": ap},
            {"name": "不计应付账款变动 D", "color": "MBLUE", "values": ex_ap},
        ],
        "bar_labels": False,
        "fmt": "usd0",
        "yfmt": "usd0",
        "label_fmt": "usd0",
        "ylab": "US$M",
        "note": (lead + ("（应付天数的完整历史见 Exhibit {EX_DPO}）。" if dpo_chart else "。")
                 + f"图里 {len(quarters)} 季有 {sum(1 for v in ap if v < 0)} 季应付账款是减少的。"),
        "src_extra": ("经营现金流与应付账款变动取各季业绩 8-K EX-99.1 的三个月现金流量表，同一季被两份新闻稿印出时取较新一次"
                      "（2024 年各季在 2025 年新闻稿里按新列报方式重印过）；差额为自算 D。"),
    }


def capex_chart(staging: dict, labels: list[str], exposure_chart_present: bool) -> dict:
    capex = staging["cash_flow_usd_m"]["capex"]
    revenue = staging["financials"]["revenue_usd_m"]
    intensity = [c / r * 100 for c, r in zip(capex, revenue)]
    record_level = max(capex[:-1]) < capex[-1]
    record_share = max(intensity[:-1]) < intensity[-1]
    both = record_level and record_share
    prior_peak = max(range(len(intensity) - 1), key=lambda i: intensity[i])
    band = sum(1 for v in intensity if 1 <= v <= 4)
    return {
        "kind": "bar_line_dual",
        "title": (f"资本开支 {usd_m(capex[-1])}（环比 {signed(pct(capex[-1], capex[-2]), 0)}）、占收入 {intensity[-1]:.1f}%"
                  + (f"，两项都是 {len(labels)} 季最高" if both else
                     f"，金额是 {len(labels)} 季最高" if record_level else
                     f"，占比是 {len(labels)} 季最高" if record_share else "")),
        "xlabels": labels,
        "xstep": 4,
        "bar": {"name": "资本开支", "values": capex, "color": "NAVY"},
        "line": {"name": "资本开支 / 收入 (RHS) D", "values": rounded(intensity), "color": "GOLD", "yfmt": "pct1"},
        "fmt": "usd0",
        "yfmt": "usd0",
        "label_fmt": "usd0",
        "ylab": "US$M",
        "ylab2": "占收入比",
        "note": (f"AMD 是无晶圆厂公司，{len(labels)} 季里有 {band} 季资本开支占收入在 1%–4% 之间。"
                 + (f"此前的最高点是 {labels[prior_peak]} 的 {intensity[prior_peak]:.1f}%。" if record_share else
                    f"这条线的最高点是 {labels[prior_peak]} 的 {intensity[prior_peak]:.1f}%。")
                 + "这只是现金流量表上的「购置物业与设备」，不含尚未上表的采购承诺、租约与担保"
                 + ("（见 Exhibit {EX_EXPOSURE}）。" if exposure_chart_present else "。")),
        "src_extra": "各季业绩 8-K EX-99.1 自由现金流对账表的「Purchases of property and equipment」；占比为自算 D。",
    }


def exposure_chart(block: dict | None) -> tuple[dict | None, dict | None]:
    if block is None:
        return None, None
    items = block["items"]
    quarters = block["quarters"]
    labels = [item["label"] for item in items]
    groups = [{"name": compact(q) + " 期末", "color": color,
               "values": [None if item["values"][k] is None else item["values"][k] / 1000 for item in items]}
              for k, (q, color) in enumerate(zip(quarters, ("MBLUE", "NAVY")))]
    total = items[0]["values"]
    later = items[1]["values"]
    chart = {
        "ref": "EX_EXPOSURE",
        "kind": "grouped_bars",
        "title": (f"无条件采购承诺一季 {signed(pct(total[1], total[0]), 0)} 到 {usd_b(total[1])}，"
                  f"其中 {items[1]['short']}那一段 {signed(pct(later[1], later[0]), 0)}"),
        "xlabels": labels,
        "groups": groups,
        "bar_labels": True,
        "fmt": "usd1",
        "yfmt": "usd1",
        "label_fmt": "usd1",
        "ylab": "US$B",
        "note": block["note"],
        "src_extra": block["source"],
    }
    rows = [[item["label"]] + (item["values_text"] if "values_text" in item
                               else ["—" if v is None else usd_m(v) for v in item["values"]])
            + [item.get("where", "")] for item in items]
    rows += [[row["label"], "—", row["value"], row["where"]] for row in block["table_extra"]]
    table = {
        "title": f"表外与或有敞口：{quarters[0]} 与 {quarters[1]} 两份 10-Q 并列",
        "headers": ["项目", f"{quarters[0]} 期末", f"{quarters[1]} 期末", "出处"],
        "rows": rows,
    }
    return chart, table


# ── section three ────────────────────────────────────────────────────────────
def data_center_half_chart(staging: dict, claim: dict | None) -> tuple[dict | None, dict | None]:
    """What a filed "Data Center accelerates in the second half" takes, in dollars.

    Only drawn while the series carries a period-stamped ``dc_acceleration_claim``
    -- the sentence, where it was filed, and the half it is about. The floor is the
    prior-year half grown at the rate of the half the company has just finished:
    anything above it is faster growth, which is all "accelerate" can mean against
    a year-over-year base. Everything else comes from filed segment revenue.
    """
    if claim is None:
        return None, None
    seg = staging["segments"]
    quarters = seg["quarters"]
    dc = dict(zip(quarters, seg["data_center_usd_m"]))
    year, half_no = claim["year"], claim["half"]
    base_half = 1 if half_no == 2 else 2
    base_year = year if half_no == 2 else year - 1

    def half(y: int, h: int) -> int:
        qs = [f"Q{n} {y}" for n in ((1, 2) if h == 1 else (3, 4))]
        return sum(dc[q] for q in qs)

    done_now, done_prev = half(base_year, base_half), half(base_year - 1, base_half)
    target_prev = half(year - 1, half_no)
    growth = pct(done_now, done_prev)
    floor = target_prev * (1 + growth / 100)
    labels = [half_label(base_year - 1, base_half), half_label(year - 1, half_no),
              half_label(base_year, base_half), half_label(year, half_no) + "门槛 D"]
    values = [done_prev / 1000, target_prev / 1000, done_now / 1000, floor / 1000]
    last = quarters[-1]
    chart = {
        "kind": "bars_labeled",
        "title": (f"公司说 {half_label(year, half_no)}数据中心会「加速」：同比要高过 {signed(growth)}，"
                  f"至少 {usd_b(floor, 2)} D"),
        "xlabels": labels,
        "values": rounded(values),
        "legend": "数据中心分部收入（半年合计）",
        "fmt": "usd1",
        "yfmt": "usd1",
        "label_fmt": "usd2",
        "ylab": "US$B",
        "note": (f"{claim['said']}把它翻成算术：{half_label(base_year, base_half)}数据中心 {usd_m(done_now)}，"
                 f"对 {half_label(base_year - 1, base_half)}的 {usd_m(done_prev)} 同比 {signed(growth)}；"
                 f"{half_label(year - 1, half_no)}基数 {usd_m(target_prev)}，所以 {half_label(year, half_no)}要超过 "
                 f"{usd_m(floor)} 才算加速，相当于平均每季 {usd_m(floor / 2)}，比 {compact(last)} 的 {usd_m(dc[last])} 高 "
                 f"{pct(floor / 2, dc[last]):.0f}%。<b>这条门槛完全来自公司自己印出的分部收入</b>，不依赖任何分部以下的拆分假设。"),
        "src_extra": f"各季业绩 8-K EX-99.1 的分部收入；「加速」一语见{claim['where']}；门槛为自算 D。",
    }
    return chart, {"floor": floor, "growth": growth}


def threshold_charts(staging: dict, labels: list[str], block: dict | None,
                     gm_series: list[float], dpo: list[float]) -> tuple[list[dict], list[dict]]:
    if block is None:
        return [], []
    entries = []
    charts = []
    for spec in block["quantified"]:
        metric = spec["id"]
        if metric == "non_gaap_gm":
            series, name, fmt = gm_series, "non-GAAP 毛利率", "pct1"
        elif metric == "dpo":
            series, name, fmt = dpo, "应付天数", "f1"
        else:
            raise ValueError(f"next_kpi: unknown metric {metric!r}")
        current = series[-1]
        entries.append({"metric": spec["metric"], "direction": spec["direction"],
                        "threshold": spec["threshold"], "unit": spec["unit"], "current": current})
        if metric == "non_gaap_gm":
            window = series[-8:]
            # At the precision the chart prints: 53.99% reads 54.0% on the page and
            # sits on the line, so it is not counted as a breach.
            under = [labels[len(series) - 8 + i] for i, v in enumerate(window)
                     if round(v, 1) < spec["threshold"]]
            title = (f"non-GAAP 毛利率对 {spec['threshold']:.1f}% 警戒线：本季 {current:.1f}%，"
                     f"下季公司指引约 {staging['guidance_history']['non_gaap_gm_guide_pct'][-1]:g}%")
            note = (f"最近八季里这条线被跌破 {len(under)} 次（{'、'.join(under)}）"
                    if under else "最近八季没有一季跌破这条线") + "。" + spec["why"]
        else:
            jumps = [dpo[i] - dpo[i - 1] for i in range(1, len(dpo))]
            jump_record = max(jumps[:-1]) < jumps[-1]
            peak = max(range(len(dpo)), key=lambda i: dpo[i])
            rank = 1 + sum(1 for v in dpo[:-1] if v > current)
            if peak == len(dpo) - 1:
                level = "，水平本身也是纪录"
            elif jump_record:
                level = f"，但水平不是纪录（{labels[peak]} {dpo[peak]:.1f} 天）"
            else:
                level = f"，水平排第 {rank}（最高是 {labels[peak]} 的 {dpo[peak]:.1f} 天）"
            title = (f"应付天数 {current:.1f} 天对 {spec['threshold']:.0f} 天警戒线："
                     + f"单季 {signed(jumps[-1], 1, ' 天')}"
                     + (f"是 {len(dpo)} 季最大跳升" if jump_record else "")
                     + level)
            ordered = sorted(range(len(jumps)), key=lambda i: jumps[i])
            second = ordered[-2] + 1
            early = [v for v, label in zip(dpo, labels) if int("20" + label[-2:]) <= 2019]
            inside_early = min(early) <= current <= max(early)
            note = (f"应付天数 = （应付账款 + 应付关联方款项）÷ 当季销货成本（不含无形资产摊销）× {DAYS_PER_QUARTER}（D）。"
                    f"本季水平在 {len(dpo)} 季里排第 {rank}"
                    + (f"：2016–2019 年 AMD 的应付天数在 {min(early):.0f}–{max(early):.0f} 天之间，"
                       f"本季的水平落在那个区间里" if inside_early else "")
                    + "。"
                    + (f"<b>罕见的是速度</b>：单季 {signed(jumps[-1], 1, ' 天')}是 {len(dpo)} 季最大，上一次接近的是 "
                       f"{labels[second]} 的 {signed(dpo[second] - dpo[second - 1], 1, ' 天')}。" if jump_record else "")
                    + spec["why"])
        charts.append(threshold_exhibit(
            title, labels, rounded(series), spec["threshold"], fmt=fmt,
            ylab=spec["ylab"], actual_name=name, threshold_name=f"阈值 {unit_text(spec['unit'], spec['threshold'])}",
            note=note, src_extra=spec["source"], xstep=4,
        ))
        if metric == "dpo":
            charts[-1]["ref"] = "EX_DPO"
    return charts, entries


def commitments_chart(staging: dict) -> dict | None:
    block = staging.get("purchase_commitments_usd_m")
    if block is None:
        return None
    quarters, total = block["quarters"], block["total"]
    if quarters[-1] != staging["periods"][-1] or total[-1] is None:
        raise ValueError("purchase_commitments_usd_m must end, with a value, at the series' last quarter")
    labels = [compact(q) for q in quarters]
    known = [i for i, v in enumerate(total) if v is not None]
    trough = min(known, key=lambda i: total[i])
    before = [i for i in known if i < trough]
    peak = max(before, key=lambda i: total[i]) if before else trough
    record = total[-1] > max(total[i] for i in known[:-1])

    def compared(back: int) -> str:
        """The quarter ``back`` places earlier, or the nearest earlier one that is comparable."""
        target = len(total) - 1 - back
        usable = [i for i in known if i <= target]
        if not usable:
            return ""
        i = usable[-1]
        return (f"{labels[i]} 的 {usd_b(total[i])}" if i == target
                else f"{labels[target]} 不可比，取更早的 {labels[i]} {usd_b(total[i])}")

    breaks = "".join(f"{compact(q)} {text}；" for q, text in block["breaks"].items())
    holes = "".join(f"{compact(q)} 留空：{text}" for q, text in block["not_comparable"].items())
    return {
        "kind": "lines",
        "title": (f"无条件采购承诺 {usd_b(total[-1])}"
                  + ("，是这条序列的新高" if record else "")
                  + (f"：上一轮高点是 {labels[peak]} 的 {usd_b(total[peak])}，低点是 {labels[trough]} 的 {usd_b(total[trough])}"
                     if peak != trough else "")),
        "xlabels": labels,
        "xrot": 90,
        "series": [{"name": "无条件采购承诺合计", "values": rounded([None if v is None else v / 1000 for v in total]),
                    "color": "NAVY"}],
        "fmt": "usd1",
        "yfmt": "usd1",
        "label_fmt": "usd1",
        "end_label": True,
        "ylab": "US$B",
        "note": (f"上季：{compared(1)}；一年前：{compared(4)}。"
                 f"口径变化：{breaks}{holes}{block['floor_note']}"),
        "src_extra": block["source"],
    }


# ── section four ─────────────────────────────────────────────────────────────
def margin_chart(staging: dict, labels: list[str], gm: list[float]) -> dict:
    fin = staging["financials"]
    revenue = fin["revenue_usd_m"]
    op = [o / r * 100 for o, r in zip(fin["non_gaap_operating_income_usd_m"], revenue)]
    gaap_op = [o / r * 100 for o, r in zip(fin["gaap_operating_income_usd_m"], revenue)]
    top = max(range(len(op)), key=lambda i: op[i])
    return {
        "kind": "lines",
        "title": (f"{len(labels)} 季 non-GAAP 毛利率由 {num(gm[0])}% 到 {num(gm[-1])}%、"
                  f"营业利润率由 {num(op[0])}% 到 {num(op[-1])}%"),
        "xlabels": labels,
        "xstep": 4,
        "series": [
            {"name": "non-GAAP 毛利率", "values": rounded(gm), "color": "NAVY"},
            {"name": "non-GAAP 营业利润率", "values": rounded(op), "color": "MBLUE"},
            {"name": "GAAP 营业利润率", "values": rounded(gaap_op), "color": "GRAY"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "利润率",
        "note": (f"{len(labels)} 季里 non-GAAP 营业利润率的最高点是 {labels[top]} 的 {op[top]:.1f}%"
                 + ("，就是本季。" if top == len(op) - 1 else "，不是本季。")
                 + "GAAP 与 non-GAAP 营业利润率的缺口自 2022 年起明显变宽：收购 Xilinx 之后每季要摊销数亿美元的无形资产，"
                 "这一项只在 GAAP 里。"),
        "src_extra": "各季业绩 8-K EX-99.1 合并损益表与 GAAP/non-GAAP 对账表；利润率为自算 D。",
    }


def legacy_segment_chart(staging: dict) -> dict:
    seg = staging["segments_legacy"]
    quarters = seg["quarters"]
    labels = [compact(q) for q in quarters]
    cg, eesc = seg["computing_graphics_revenue_usd_m"], seg["eesc_revenue_usd_m"]
    share = [c / (c + e) * 100 for c, e in zip(cg, eesc)]
    return {
        "ref": "EX_LEGACY",
        "kind": "stacked_dual",
        "title": (f"旧的两分部口径（{labels[0]}–{labels[-1]}）：计算与图形由 {usd_b(cg[0], 2)} 到 {usd_b(cg[-1], 2)}，"
                  f"企业、嵌入式与半定制由 {usd_b(eesc[0], 2)} 到 {usd_b(eesc[-1], 2)}"),
        "xlabels": labels,
        "xrot": 90,
        "stacks": [
            {"name": "计算与图形", "color": "MBLUE", "values": rounded([v / 1000 for v in cg])},
            {"name": "企业、嵌入式与半定制", "color": "NAVY", "values": rounded([v / 1000 for v in eesc])},
        ],
        "line": {"name": "计算与图形占比 (RHS) D", "color": "GOLD", "values": rounded(share), "yfmt": "pct0", "ymax": 100},
        "fmt": "usd1",
        "yfmt": "usd1",
        "label_fmt": "usd1",
        "ylab": "US$B",
        "ylab2": "%",
        "note": ("2022 年一季度以前 AMD 只报两个分部：客户端 CPU 与显卡在「计算与图形」，服务器 CPU、嵌入式与游戏机半定制芯片"
                 "同在「企业、嵌入式与半定制」。所以这一段没有数据中心收入可读 —— 游戏机换代的起伏与服务器的增长混在同一根柱里。"
                 "2017 年四季为 ASC 606 重述口径，2016 年为 ASC 605。"),
        "src_extra": "各季业绩 8-K EX-99.1 的分部表（旧口径），同一季被多份新闻稿印出时取最新一次；占比为自算 D。",
    }


def fcf_chart(staging: dict, labels: list[str]) -> dict:
    fcf = staging["cash_flow_usd_m"]["free_cash_flow"]
    revenue = staging["financials"]["revenue_usd_m"]
    margin = [f / r * 100 for f, r in zip(fcf, revenue)]
    negative = sum(1 for v in fcf if v < 0)
    years_negative = [int("20" + label[-2:]) for v, label in zip(fcf, labels) if v < 0]
    return {
        "kind": "bar_line_dual",
        "title": (f"自由现金流 {len(labels)} 季：本季 {usd_m(fcf[-1])}、占收入 {margin[-1]:.1f}%，"
                  f"上季是 {margin[-2]:.1f}%"),
        "xlabels": labels,
        "xstep": 4,
        "bar": {"name": "自由现金流", "values": fcf, "color": "NAVY"},
        "line": {"name": "自由现金流 / 收入 (RHS) D", "values": rounded(margin), "color": "GOLD", "yfmt": "pct0"},
        "fmt": "usd0",
        "yfmt": "usd0",
        "label_fmt": "usd0",
        "ylab": "US$M",
        "ylab2": "占收入比",
        "note": ((f"{len(labels)} 季里有 {negative} 季自由现金流为负，都在 "
                  f"{min(years_negative)}–{max(years_negative)} 年之间。" if negative else
                  f"{len(labels)} 季里没有一季自由现金流为负。")
                 + f"自由现金流 = 经营现金流（2025 年起为持续经营部分）− 购置物业与设备，本页 {len(labels)} 季每一季的新闻稿都印了这张对账表。"
                 "2019 年的新闻稿按调整后的列报重印过 2017 年四季度与 2018 年各季的经营现金流，本页取重印值；"
                 "2017 年前三季没有被重印，仍是原口径，所以 2017 年四季相加既不等于当年 10-K 的原值、也不等于重述值。"),
        "src_extra": "各季业绩 8-K EX-99.1 的自由现金流对账表；占比为自算 D。",
    }


def opex_chart(staging: dict, labels: list[str]) -> dict:
    fin = staging["financials"]
    intensity = [o / r * 100 for o, r in zip(fin["non_gaap_opex_usd_m"], fin["revenue_usd_m"])]
    low = min(range(len(intensity)), key=lambda i: intensity[i])
    return {
        "kind": "gs_line",
        "title": f"non-GAAP 营业费用占收入 {len(labels)} 季由 {intensity[0]:.1f}% 到 {intensity[-1]:.1f}%",
        "xlabels": labels,
        "xstep": 4,
        "values": rounded(intensity),
        "legend": "non-GAAP 营业费用 / 收入",
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "占收入比",
        "note": (f"最低的一格是 {labels[low]} 的 {intensity[low]:.1f}%。本季费用 {usd_m(fin['non_gaap_opex_usd_m'][-1])}、"
                 f"同比 {signed(pct(fin['non_gaap_opex_usd_m'][-1], fin['non_gaap_opex_usd_m'][-5]))}，"
                 f"收入同比 {signed(pct(fin['revenue_usd_m'][-1], fin['revenue_usd_m'][-5]))}。"
                 "费用相对公司自己指引的记录见 Exhibit {EX_OPEX_BAND}。"),
        "src_extra": "各季业绩 8-K EX-99.1（2016 年四季度一格取同日 CFO commentary EX-99.2）的 non-GAAP 营业费用；占比为自算 D。",
    }


def share_chart(staging: dict, labels: list[str], warrants: dict | None) -> dict:
    shares = staging["financials"]["diluted_shares_m"]
    steps = [shares[i] - shares[i - 1] for i in range(1, len(shares))]
    big = max(range(len(steps)), key=lambda i: steps[i]) + 1
    note = (f"GAAP 摊薄加权股数。{len(labels)} 季里单季最大的一级台阶是 {labels[big - 1]} 到 {labels[big]} 的 "
            f"+{steps[big - 1]:,}M 股"
            + (f"：{staging['share_count_episodes'][staging['periods'][big]]}" if staging["periods"][big]
               in staging.get("share_count_episodes", {}) else "")
            + "。")
    if warrants is not None:
        note += warrants["share_note"]
    return {
        "kind": "lines",
        "title": (f"摊薄股数 {len(labels)} 季由 {shares[0]:,}M 到 {shares[-1]:,}M"
                  + (f"；另有 {warrants['shares_m']:,}M 股认股权证未归属、不在其中" if warrants else "")),
        "xlabels": labels,
        "xstep": 4,
        "series": [{"name": "摊薄加权股数（百万股）", "values": shares, "color": "NAVY"}],
        "fmt": "f0",
        "yfmt": "f0",
        "label_fmt": "f0",
        "end_label": True,
        "ylab": "百万股",
        "note": note,
        "src_extra": "各季业绩 8-K EX-99.1 合并损益表的「Shares used in per share calculation – Diluted」。",
    }


def inventory_chart(staging: dict, labels: list[str], dio: list[float]) -> dict:
    inventory = staging["balance_sheet_usd_m"]["inventory"]
    peak = max(range(len(dio)), key=lambda i: dio[i])
    return {
        "kind": "bar_line_dual",
        "title": f"存货 {usd_b(inventory[-1])}、存货天数 {dio[-1]:.0f} 天：{len(labels)} 季里最高是 {labels[peak]} 的 {dio[peak]:.0f} 天",
        "xlabels": labels,
        "xstep": 4,
        "bar": {"name": "存货", "values": rounded([v / 1000 for v in inventory]), "color": "NAVY"},
        "line": {"name": "存货天数 (RHS) D", "values": rounded(dio), "color": "GOLD", "yfmt": "f0"},
        "fmt": "usd1",
        "yfmt": "usd1",
        "label_fmt": "usd1",
        "ylab": "US$B",
        "ylab2": "天",
        "note": (f"存货天数 = 期末存货 ÷ 当季销货成本（不含无形资产摊销）× {DAYS_PER_QUARTER}（D）。"
                 "2018 年采用 ASC 606 后，部分半定制产品在出货前就确认收入、从存货转出，所以 2017 年前后的水平不完全可比。"),
        "src_extra": "各季业绩 8-K EX-99.1 资产负债表的存货与合并损益表的销货成本。",
    }


# ── tables ───────────────────────────────────────────────────────────────────
def core_table(staging: dict, gm: list[float], yoy: list[float]) -> dict:
    fin = staging["financials"]
    cash = staging["cash_flow_usd_m"]
    periods = staging["periods"]
    rows = []
    for i in range(len(periods) - 8, len(periods)):
        rows.append([
            periods[i],
            usd_m(fin["revenue_usd_m"][i]),
            signed(yoy[i]) + " D",
            f"{gm[i]:.2f}% D",
            usd_m(fin["non_gaap_opex_usd_m"][i]),
            usd_m(fin["non_gaap_operating_income_usd_m"][i]),
            f"${fin['non_gaap_eps_usd'][i]:.2f}",
            f"${fin['gaap_eps_diluted_usd'][i]:.2f}",
            usd_m(cash["free_cash_flow"][i]),
        ])
    return {
        "title": "八季核心（公司印出值；D 为自算）",
        "headers": ["季度", "收入", "同比", "non-GAAP 毛利率", "non-GAAP 营业费用", "non-GAAP 营业利润",
                    "non-GAAP EPS", "GAAP EPS", "自由现金流"],
        "rows": rows,
    }


def segment_table(staging: dict) -> dict:
    seg = staging["segments"]
    rows = []
    for i in range(len(seg["quarters"]) - 8, len(seg["quarters"])):
        rows.append([
            seg["quarters"][i],
            usd_m(seg["data_center_usd_m"][i]), usd_m(seg["data_center_oi_usd_m"][i]),
            usd_m(seg["client_usd_m"][i]), usd_m(seg["gaming_usd_m"][i]), usd_m(seg["client_gaming_oi_usd_m"][i]),
            usd_m(seg["embedded_usd_m"][i]), usd_m(seg["embedded_oi_usd_m"][i]),
            usd_m(seg["all_other_oi_usd_m"][i]),
        ])
    return {
        "title": "分部八季（收入与分部营业利润）",
        "headers": ["季度", "数据中心", "数据中心利润", "客户端", "游戏", "客户端与游戏利润", "嵌入式", "嵌入式利润",
                    "All Other"],
        "rows": rows,
    }


def guidance_box(block: dict | None, staging: dict) -> dict | None:
    if block is None:
        return None
    nq = block["next_quarter"]
    revenue = staging["financials"]["revenue_usd_m"]
    gm_now = staging["financials"]["non_gaap_gross_profit_usd_m"][-1] / revenue[-1] * 100
    rows = [
        ["收入", f"US${nq['revenue_usd_m'] / 1000:g}B ± US${nq['revenue_band_usd_m']}M",
         signed(pct(nq["revenue_usd_m"], revenue[-1])) + " D",
         signed(pct(nq["revenue_usd_m"], revenue[-4])) + " D", "新闻稿"],
        ["non-GAAP 毛利率", f"约 {nq['non_gaap_gm_pct']:g}%",
         signed(nq["non_gaap_gm_pct"] - gm_now, 2, "pp") + " D", "—", "新闻稿"],
    ]
    for item in block["slides_only"]["items"]:
        rows.append([item["metric"], item["value"], "—", "—", "业绩幻灯片"])
    return {
        "title": f"下季指引（{nq['period']}）",
        "headers": ["指标", "公司指引", "隐含环比", "隐含同比", "出处"],
        "rows": rows,
        "note": block["slides_only"]["note"],
    }


# ── the page ─────────────────────────────────────────────────────────────────
def story_values(staging: dict, gfacts: dict, half_facts: dict | None, exposure: dict | None,
                 yoy: list[float], gm: list[float], dpo: list[float], labels: list[str]) -> dict[str, str]:
    """Every number a period-stamped sentence may name, computed from the series."""
    fin = staging["financials"]
    revenue = fin["revenue_usd_m"]
    cash = staging["cash_flow_usd_m"]
    seg = staging["segments"]
    dc = seg["data_center_usd_m"]
    offset = staging["periods"].index(seg["quarters"][0])
    capex = cash["capex"]
    capex_record = max(capex[:-1]) < capex[-1]
    jumps = [dpo[i] - dpo[i - 1] for i in range(1, len(dpo))]
    jump_record = max(jumps[:-1]) < jumps[-1]
    peak = max(range(len(dpo)), key=lambda i: dpo[i])
    wc = staging["working_capital_cash_flow_usd_m"]
    if wc["quarters"][-1] != staging["periods"][-1]:
        raise ValueError("working_capital_cash_flow_usd_m must end at the series' last quarter")
    opex = fin["non_gaap_opex_usd_m"]
    guided_opex = gfacts["next_opex"]
    record = staging["guidance_history"]
    next_q = record["quarters"][-1]
    year_ago = f"{next_q[:2]} {int(next_q[-4:]) - 1}"
    year_ago_opex = record["actual_non_gaap_opex_usd_m"][record["quarters"].index(year_ago)]
    values = {
        "revenue": usd_b(revenue[-1]),
        "revenue_yoy": signed(yoy[-1]),
        "dc": usd_b(dc[-1]),
        "dc_yoy": signed(pct(dc[-1], dc[-5]), 0),
        "dc_share": f"{dc[-1] / revenue[offset + len(dc) - 1] * 100:.1f}%",
        "gm": f"{gm[-1]:.1f}%",
        "ocf": usd_m(cash["operating"][-1]),
        "ap_change": usd_m(wc["accounts_payable_change"][-1]),
        "ap_direction": "增加" if wc["accounts_payable_change"][-1] > 0 else "减少",
        "fcf": usd_m(cash["free_cash_flow"][-1]),
        "fcf_qoq": signed(pct(cash["free_cash_flow"][-1], cash["free_cash_flow"][-2]), 0),
        "dpo_prev": f"{dpo[-2]:.0f}",
        "dpo": f"{dpo[-1]:.0f}",
        "dpo_jump": signed(jumps[-1], 1, " 天"),
        "dpo_jump_rank": f"，是 {len(dpo)} 季最大的单季跳升" if jump_record else "",
        "dpo_level": (f"水平本身也是 {len(dpo)} 季最高" if peak == len(dpo) - 1
                      else (f"但 {len(dpo)} 季里水平不是最高" if jump_record else f"{len(dpo)} 季里水平不是最高")
                      + f"（{labels[peak]} {dpo[peak]:.0f} 天）"),
        "capex_phrase": (f"资本开支 {usd_m(capex[-1])}" + (f"、为 {len(capex)} 季最高" if capex_record else "")),
        "rev_above": str(gfacts["above"]),
        "rev_finished": str(gfacts["finished"]),
        "next_mid": usd_b(gfacts["next_mid"]),
        "next_gm": f"{gfacts['next_gm']:g}%",
        "opex_streak": cn_count(gfacts["opex_streak"]),
        "opex_over": str(gfacts["opex_over"]),
        "opex_scored": str(gfacts["opex_scored"]),
        "opex_yoy": signed(pct(opex[-1], opex[-5])),
        "opex_guide_yoy": signed(pct(guided_opex, year_ago_opex)),
        "next_opex": usd_b(guided_opex, 2),
    }
    # Only when the half-year chart exists: an empty string would print a sentence
    # with a hole in it, while a missing key makes `fill_story` stop the build.
    if half_facts:
        values["dc_floor"] = usd_b(half_facts["floor"], 2)
        values["dc_half_growth"] = signed(half_facts["growth"])
    if exposure is not None:
        total, later = exposure["items"][0]["values"], exposure["items"][1]["values"]
        values.update({
            "commit_prev": usd_b(total[0]), "commit_now": usd_b(total[1]),
            "commit_later_prev": usd_b(later[0]), "commit_later_now": usd_b(later[1]),
            "later_label": exposure["items"][1]["short"],
            "exposure_tail": exposure["brief_tail"],
        })
    return values


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    period, prior = periods[-1], periods[-2]
    latest = latest_block(staging, period=period, period_end=staging["period_ends"][-1],
                          release_date=staging["release_dates"][-1])
    if staging["guidance_history"]["quarters"][-2] != period:
        raise ValueError("guidance_history must end one quarter past the series")
    labels = [compact(p) for p in periods]
    fin = staging["financials"]
    revenue = fin["revenue_usd_m"]
    gm = [g / r * 100 for g, r in zip(fin["non_gaap_gross_profit_usd_m"], revenue)]
    yoy = revenue_yoy(staging)
    dpo = payable_days(staging)
    dio = inventory_days(staging)

    if str(staging["release_accessions"][-1]).replace("-", "") not in staging["latest"]["source_url"]:
        raise ValueError("latest.source_url is not the latest quarter's release (release_accessions[-1])")
    followups = stamped_block(staging, "followup_closure", period)
    eps_block = stamped_block(staging, "eps_reconciliation", period)
    exposure = stamped_block(staging, "balance_sheet_exposure", period)
    next_kpi = stamped_block(staging, "next_kpi", period)
    guidance = stamped_block(staging, "guidance", period)
    story = stamped_block(staging, "quarter_story", period)
    warrants = stamped_block(staging, "warrants", period)
    claim = stamped_block(staging, "dc_acceleration_claim", period)
    commitments_block = staging.get("purchase_commitments_usd_m")
    if exposure is not None and commitments_block is not None:
        history = dict(zip(commitments_block["quarters"], commitments_block["total"]))
        if [history.get(q) for q in exposure["quarters"]] != exposure["items"][0]["values"]:
            raise ValueError("balance_sheet_exposure totals disagree with purchase_commitments_usd_m")

    guide_ex, guide_table, gfacts = guidance_charts(staging)
    half_chart, half_facts = data_center_half_chart(staging, claim)
    values = story_values(staging, gfacts, half_facts, exposure, yoy, gm, dpo, labels)

    # section one
    settled_ex = []
    closure = followup_chart(followups, prior, values)
    if closure:
        settled_ex.append(closure)
    settled_ex += guide_ex

    # section two
    highlight_ex = [revenue_chart(staging, labels, yoy)]
    highlight_ex += segment_charts(staging)
    eps = eps_chart(eps_block)
    if eps:
        highlight_ex.append(eps)
    exp_chart, exp_table = exposure_chart(exposure)
    threshold_ex, kpi_entries = threshold_charts(staging, labels, next_kpi, gm, dpo)
    has_dpo = any(ex.get("ref") == "EX_DPO" for ex in threshold_ex)
    highlight_ex.append(cash_quality_chart(staging, has_dpo))
    highlight_ex.append(capex_chart(staging, labels, exp_chart is not None))
    if exp_chart:
        highlight_ex.append(exp_chart)

    # section three
    next_ex = []
    next_ex += threshold_ex
    if half_chart:
        next_ex.append(half_chart)
    commitments = commitments_chart(staging)
    if commitments:
        next_ex.append(commitments)

    # section four
    routine_ex = [
        margin_chart(staging, labels, gm),
        legacy_segment_chart(staging),
        fcf_chart(staging, labels),
        opex_chart(staging, labels),
        share_chart(staging, labels, warrants),
        inventory_chart(staging, labels, dio),
    ]

    everything = settled_ex + highlight_ex + next_ex + routine_ex
    number_exhibits(everything, start=2)
    resolve_exhibit_refs(everything)
    for exhibit in everything:
        exhibit.pop("ref", None)

    # tables
    tables = []
    n = everything[-1]["n"] + 1
    if guidance is not None:
        nq = guidance["next_quarter"]
        rec = guidance_record(staging)
        tables.append({
            "title": f"{period} 兑现与 {nq['period']} 指引",
            "headers": ["指标", f"{period} 原指引", f"{period} 实际", "位置", f"{nq['period']} 指引"],
            "rows": [
                ["收入", f"{usd_m(rec['low'][-2])} – {usd_m(rec['high'][-2])}", usd_m(revenue[-1]),
                 f"高于中值 {gfacts['last_rev_dev']:.1f}% D" if gfacts["last_rev_dev"] > 0
                 else f"低于中值 {abs(gfacts['last_rev_dev']):.1f}% D",
                 f"US${nq['revenue_usd_m'] / 1000:g}B ± US${nq['revenue_band_usd_m']}M"],
                ["non-GAAP 毛利率", f"约 {rec['gm'][-2]:g}%", f"{gm[-1]:.2f}% D",
                 signed(gfacts["last_gm_dev"], 2, "pp") + " D", f"约 {nq['non_gaap_gm_pct']:g}%"],
            ],
        })
    tables.append(guide_table)
    tables.append(core_table(staging, gm, yoy))
    tables.append(segment_table(staging))
    if exp_table:
        tables.append(exp_table)
    if next_kpi is not None:
        kpi_table = threshold_table(0, "下季阈值与当前值（原单位）", kpi_entries, "current", "当前值")
        kpi_table.pop("n")
        for item in next_kpi["table_only"]:
            kpi_table["rows"].append([item["metric"], item["direction"], item["threshold"], item["current"], "不作图：" + item["why"]])
        tables.append(kpi_table)
    for table in tables:
        table["n"] = n
        n += 1
    tables.append(ai_capex_cycle_table(n))

    # headline and brief
    if story is None:
        raise ValueError("series/amd.json needs a quarter_story block for the headline")
    headline = fill_story(story["headline"], values)
    brief = fill_story(story["brief"], values)

    notes = [
        "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
        "AMD 的财年在 12 月最后一个星期六结束，季度即自然年季度（2016 年与 2022 年的第四季各为 14 周）。",
        ("季度数值逐季读自 SEC EDGAR 上 AMD（CIK 2488）的业绩 8-K EX-99.1 新闻稿。每份新闻稿并排印出本季、上季与去年同季，"
         "所以除最新一季外每个季度都被两到三份文件各读了一遍；读数不一致处以最新一份为准。"
         "GAAP 损益、资产负债表与现金流各行另与 10-Q/10-K 的 XBRL 数据逐格核对过；non-GAAP 各行与分部只在新闻稿里有。"),
        ("2018 年 AMD 以全面追溯法采用 ASC 606：2017 年四季的收入、毛利与利润在 2018 年的新闻稿里被重述，"
         "2016 年只按全年重述（收入 +US$47M）。本页的水平序列 2016 年为 ASC 605、2017 年起为 ASC 606；"
         "指引记录则按每季当时的口径计分（指引与首次印出的实际值同一口径）。"),
        ("资产负债表有两处列报变更：截至 2023-12-30 的约 US$1.1B 未开票应收款在 2024 年 10-K 里由应收账款改列预付及其他流动资产；"
         "应付关联方款项自 2025 年起并入应付账款。本页的应付天数因此用「应付账款 + 应付关联方款项」这一在全窗口内一致的口径，"
         "并且不画应收天数。"),
        "Exhibit 编号在渲染时分配；阈值是本地研究设定，不是公司指引，也不构成评级或投资建议。",
    ]
    if guidance is not None:
        notes.append(guidance["slides_only"]["page_note"])
    if exposure is not None:
        notes.append(exposure["page_note"])
    notes.append("本页只发布公司披露值与可复算的简单派生值；D 标记代表 Derived / 自算。")
    notes.append("业绩电话会文字稿仅链接官方 IR 与 SEC 托管版本，公开仓不复制原件或逐字内容。")

    source_url = staging["latest"]["source_url"]
    return {
        "schema_version": "quarterly-dashboard/amd-v1",
        "page": {"slug": "amd", "language": "zh-CN"},
        "company": {
            "ticker": "AMD",
            "name": "Advanced Micro Devices",
            "group": "semiconductor_ai",
            "accounting_standard": "US GAAP",
        },
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · AMD",
        "title": f"Advanced Micro Devices (AMD)：{period} 季报仪表盘",
        "subtitle": (f"截至 {staging['period_ends'][-1]} · 发布 {latest['release_date']} · US GAAP · "
                     f"{AUDIT_WORDS[latest['audit_status']]} · 自然年季度"),
        "headline": headline,
        "brief": brief,
        "source": (f'Source: <a href="{source_url}" rel="noopener">AMD {period} 业绩新闻稿（8-K EX-99.1）</a>'
                   "、同季 10-Q 与历季业绩 8-K。"),
        "source_url": source_url,
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": guidance_box(guidance, staging),
        "sections": [
            {
                "id": "settled",
                "title": "一、上季跟踪指标兑现了吗",
                "description": (
                    "先看上季留的问题闭环了几条，再看公司对自己指引的兑现记录。AMD 每季在业绩 8-K 里给下一季的"
                    "收入区间与 non-GAAP 毛利率（新闻稿），以及 non-GAAP 营业费用（CFO commentary 或业绩幻灯片），"
                    f"这份记录从 2016 年连到本季：{cn_count(gfacts['finished'])}个已完结季里收入 {gfacts['above']} 季超出上限、"
                    f"{gfacts['inside']} 季落在区间内、{gfacts['below']} 季跌破下限；有费用指引的 {gfacts['opex_scored']} 季里 "
                    f"{gfacts['opex_over']} 季花得比指引多。"
                ),
                "exhibits": settled_ex,
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": ("收入与数据中心的增速、分部利润率"
                                + ("、GAAP 与 non-GAAP 在净利处的分叉" if eps else "")
                                + "，以及现金流里的付款节奏、资本开支"
                                + ("和没有上表的承诺" if exp_chart else "") + "。"),
                "exhibits": highlight_ex,
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": ("；".join(
                    ([f"{cn_count(len(threshold_ex))}条能从 AMD 自己的申报文件算出水平的阈值，各自画在十年的历史上"]
                     if threshold_ex else [])
                    + (["公司在申报文件里写下的「加速」翻成算术是多少"] if half_chart else [])
                    + (["10-Q 里的无条件采购承诺走到了哪里"] if commitments else []))
                    + "。" + ("不能作图的阈值列在核对抽屉里并说明原因。" if next_kpi is not None else "")),
                "exhibits": next_ex,
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": (f"AMD 专属的常规序列：{labels[0]} 起 {len(labels)} 季的利润率、旧分部口径、自由现金流、"
                                "费用强度、股数与存货。这一节给上面三节一个纵深 —— 本季的每一个数都要放在一条走过亏损年代的序列上读。"),
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": notes,
        "footer": "AMD quarterly results · 数据来自 AMD 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "amd.js"), payload, "amd")
    shell_dir = ROOT / "amd"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("AMD", "amd"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"AMD page: {charts} charts in {len(payload['sections'])} sections "
          f"+ {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
