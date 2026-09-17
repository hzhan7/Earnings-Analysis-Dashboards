#!/usr/bin/env python3
"""Kering quarterly dashboard.

Kering publishes revenue four times a year and profit twice. The first and third
quarter releases are revenue announcements; the income statement, the Houses'
recurring operating income, the cash flow and the balance sheet exist only at the
half-year and the full year. So this page runs two independent x axes -- revenue by
quarter, profit by half -- and never puts a profit figure on a quarterly axis.

Kering is not an SEC filer: EDGAR holds only ADR depositary paperwork (F-6EF,
424B3) under CIK 1445465. Every number comes from kering.com downloads, read
twice by transcribers blind to each other, every disagreement
settled against the page. `series/ker.json` is built from those ledgers and records
the document behind every cell.

**The disclosure changed shape four times in the window, and each change is a
place where a long line can lie without any sum failing:**

- Q1 2018: PUMA, Volcom, Stella McCartney (and later Christopher Kane) moved to
  discontinued operations. Group revenue and "Other Houses" before 2018 exist on
  two perimeters; this page uses the one the FY2018 release uses, which the June
  2018 "KPIs restated IFRS 5" file prints back to 2016Q1.
- 2019: IFRS 16. Kering printed 2018 on both bases; the half-year profit lines
  switch basis at 2018 and say so on the axis.
- Q1 2022: "Corporate and other" became "Kering Eyewear and Corporate" plus an
  eliminations line, and 2021 Other Houses was re-presented about €4-6M higher per
  quarter with no stated reason. The page keeps each quarter's first publication.
- FY2025 / Q1 2026: Kering Beauté to IFRS 5, then a new segment grid (Fashion &
  Leather Goods, Jewelry, Eyewear, Corporate & Other). Saint Laurent, Bottega
  Veneta and Other Houses stop being disclosed after 2025Q4.

Gucci and Bottega Veneta revenue are lines no re-presentation ever touched: every
reprint of every quarter, in every document read, equals its first publication.
Saint Laurent has one exception (2021Q3, 652.9 first published, 652 in the 2022
re-presentation), carried in the notes.

Published numbers are company-reported or transparent arithmetic (marked D).
Thresholds in the last section are local research settings, not company guidance.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import (  # noqa: E402
    ai_capex_cycle_table,
    headroom,
    headroom_exhibit,
    number_exhibits,
    threshold_exhibit,
    threshold_table,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "ker.json"
DATA_DIR = ROOT / "data"

HOUSE_ZH = {"gucci": "Gucci", "saint_laurent": "Saint Laurent", "bottega_veneta": "Bottega Veneta",
            "other_houses": "其他品牌"}
LONG_STEP = 4

SOURCE_Q = ("季度收入与可比增速逐季取自当季首次公布它的那份公告：第一、三季度取季度收入公告，"
            "第二季度取半年度业绩新闻稿附表，第四季度取全年业绩新闻稿附表。")
SOURCE_H = ("半年数取自半年度业绩新闻稿与半年度财务报告；H2 各行为「全年减上半年」并标 D。"
            "公司不按季披露任何利润行。")
SOURCE_G = "指引原话逐字取自当期公告与演示材料；结算值取自其后的半年度与全年业绩新闻稿。"


# ── helpers ──────────────────────────────────────────────────────────────────
def compact_quarter(period: str) -> str:
    """`2026Q2` -> `Q2'26`."""
    return f"{period[4:]}'{period[2:4]}"


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def rounded(values, digits: int = 6):
    return [None if v is None else round(v, digits) for v in values]


def ratio(num, den):
    return None if num is None or not den else num / den * 100.0


def resolve_exhibit_refs(exhibits: list[dict]) -> list[dict]:
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


def trailing_streak(values: list, predicate) -> int:
    n = 0
    for v in reversed(values):
        if v is None or not predicate(v):
            break
        n += 1
    return n


def doc_label(doc: str) -> str:
    """A reader-facing name for a normalised corpus file name."""
    d = doc.replace("KER_", "")
    kinds = {
        "revenue_release": "收入公告", "revenue_presentation": "收入演示材料",
        "results_release": "业绩新闻稿", "presentation": "业绩演示材料",
        "financial_report": "半年度财务报告", "financial_document": "年度 Financial Document",
        "universal_registration_document": "Universal Registration Document",
        "reference_document": "Document de référence",
        "ifrs5_restated_kpis": "按 IFRS 5 重述的关键指标（2018-06）",
        "proforma_quarterly_sales": "2017 年备考季度收入（2018-04）",
        "proforma_revenue_release": "2017 年备考收入公告（2018-04）",
        "ifrs16_restated": "按 IFRS 16 重述的 2018 年数据",
        "dos_count_quarterly_restatement": "新门店计数口径下的 2018 年季度重述",
        "ifrs5_beaute_restatement_release": "剔除 Kering Beauté 的 IFRS 5 重述公告（2025-12-11）",
        "segment_reporting_restatement_release": "新分部口径重述公告（2026-03-16）",
        "covid_initial_estimate_release": "新冠影响初步估计公告（2020-03-20）",
        "preliminary_information_release": "一季度初步信息公告（2024-03-19）",
        "Capital_Markets_Day": "资本市场日演示材料（2026-04-16）",
    }
    for key, zh in kinds.items():
        if d.endswith(key):
            period = d[: -len(key)].strip("_").replace("_", " ")
            return f"Kering {period} {zh}".replace("  ", " ")
    return f"Kering {d}"


# ── derivations ──────────────────────────────────────────────────────────────
def derived(st: dict) -> dict:
    q = st["long_quarters"]
    rev = st["quarterly_revenue_eur_m"]
    comp = st["quarterly_comparable_pct"]
    halves = st["halves"]
    hg = st["half_group"]
    hh = st["half_house"]

    group_margin = [ratio(r, v) for r, v in zip(hg["recurring_operating_income"]["values"], hg["revenue"]["values"])]
    gross_rate = [ratio(g, v) for g, v in zip(hg["gross_margin"]["values"], hg["revenue"]["values"])]
    house_margin = {h: [ratio(r, v) for r, v in zip(hh[h]["roi_eur_m"], hh[h]["revenue_eur_m"])]
                    + [None] * (len(halves) - len(hh[h]["roi_eur_m"]))
                    for h in ("gucci", "saint_laurent", "bottega_veneta")}

    houses_sum = [None if rev["other_houses"][i] is None else
                  sum(rev[h][i] for h in ("gucci", "saint_laurent", "bottega_veneta", "other_houses"))
                  for i in range(len(q))]
    gucci_share = [None if s is None else rev["gucci"][i] / s * 100 for i, s in enumerate(houses_sum)]

    gucci_neg_streak = trailing_streak(comp["gucci"], lambda v: v < 0)
    group_c = comp["group_first_published"]
    last_positive_before = next(i for i in range(len(q) - 2, -1, -1) if group_c[i] > 0)

    # H1 2026 margin bridge, in percentage points of revenue
    is_ = st["h1_income_statement"]
    a, b = is_["H1 2025 restated"], is_["H1 2026"]
    rate = lambda row, k: row[k] / row["revenue"] * 100
    bridge = {
        "gross": rate(b, "gross_margin") - rate(a, "gross_margin"),
        "personnel": rate(b, "personnel_expenses") - rate(a, "personnel_expenses"),
        "other": rate(b, "other_recurring_operating_income_expenses") - rate(a, "other_recurring_operating_income_expenses"),
        "from": rate(a, "recurring_operating_income"),
        "to": rate(b, "recurring_operating_income"),
    }

    # guidance settlement (published basis; see the footnote note)
    idx = {h: i for i, h in enumerate(halves)}
    roi = hg["recurring_operating_income"]["values"]
    h1_23, h2_23 = roi[idx["H1 2023"]], roi[idx["H2 2023"]]
    h1_24, h2_24 = roi[idx["H1 2024"]], roi[idx["H2 2024"]]
    fy_23, fy_24 = h1_23 + h2_23, h1_24 + h2_24
    settle = {
        "h1": (h1_24 / h1_23 - 1) * 100, "h2": (h2_24 / h2_23 - 1) * 100,
        "fy": (fy_24 / fy_23 - 1) * 100, "fy_implied": (2500 / fy_23 - 1) * 100,
        "fy_eur": fy_24, "fy_23": fy_23, "h1_23": h1_23, "h2_23": h2_23, "h1_24": h1_24, "h2_24": h2_24,
    }

    ann = st["annual_house"]
    ann_margin = {h: [r / v * 100 for r, v in zip(ann[h]["roi_eur_m"], ann[h]["revenue_eur_m"])] for h in ann}

    fy25_margin = (hg["recurring_operating_income"]["values"][idx["H1 2025"]]
                   + hg["recurring_operating_income"]["values"][idx["H2 2025"]]) / (
        hg["revenue"]["values"][idx["H1 2025"]] + hg["revenue"]["values"][idx["H2 2025"]]) * 100

    cmd_line = 2 * fy25_margin
    above = [halves[i] for i, m in enumerate(group_margin) if m is not None and m > cmd_line]

    return {
        "halves_above_cmd": len(above), "last_above_cmd": above[-1] if above else "—",
        "group_margin": group_margin, "gross_rate": gross_rate, "house_margin": house_margin,
        "houses_sum": houses_sum, "gucci_share": gucci_share,
        "gucci_neg_streak": gucci_neg_streak, "last_positive_before": last_positive_before,
        "bridge": bridge, "settle": settle, "ann_margin": ann_margin, "fy25_margin": fy25_margin,
        "cmd_margin_line": 2 * fy25_margin,
    }


# ── section one: the numbers Kering did give ─────────────────────────────────
def settled_charts(st: dict, der: dict) -> list[dict]:
    s = der["settle"]
    g = st["guidance_record"]
    ann = st["annual_house"]
    years = ann["gucci"]["years"]
    g_rev, g_m = ann["gucci"]["revenue_eur_m"], der["ann_margin"]["gucci"]
    y_rev, y_m = ann["saint_laurent"]["revenue_eur_m"], der["ann_margin"]["saint_laurent"]

    g_rev_hit = [years[i] for i, v in enumerate(g_rev) if v >= 10000]
    g_m_hit = [years[i] for i, v in enumerate(g_m) if v >= 40]
    g_both = [years[i] for i in range(len(years)) if g_rev[i] >= 10000 and g_m[i] >= 40]
    t = st["targets_2022"]
    ey = t["eyewear_fy2025"]
    ey_m = ey["roi_eur_m"] / ey["revenue_eur_m"] * 100
    i22 = years.index("FY2022")
    t_items = [("Gucci 收入", g_rev[i22] / 15000 * 100, g_rev[-1] / 15000 * 100),
               ("SL 收入", y_rev[i22] / 5000 * 100, y_rev[-1] / 5000 * 100),
               ("SL 利润率", y_m[i22] / 33 * 100, y_m[-1] / 33 * 100),
               ("眼镜收入", None, ey["revenue_eur_m"] / 2000 * 100),
               ("眼镜利润率", None, ey_m / 15 * 100)]
    t22 = [a for _, a, _ in t_items]
    t25 = [b for _, _, b in t_items]
    y2_first = next(i for i, v in enumerate(y_rev) if v >= 2000)
    y3_first = next(i for i, v in enumerate(y_rev) if v >= 3000)

    return [
        {
            "ref": "EX_G2024",
            "kind": "grouped_bars",
            "title": (f"2024 年三次利润指引：上半年落在区间里，下半年的「约 −30%」"
                      f"实际是 {s['h2']:.1f}%"),
            "xlabels": ["2024 上半年", "2024 下半年", "2024 全年"],
            "xrot": 0,
            # Plotted as the size of the decline: an all-negative grouped_bars
            # puts its axis top at max x 1.22, still below zero, and every bar
            # is drawn from zero straight off the canvas.
            "groups": [
                {"name": "公司所述降幅（区间取中点；全年为 €2.5B 折算 D）", "color": "GOLD",
                 "values": rounded([42.5, 30.0, -s["fy_implied"]])},
                {"name": "实际降幅（报告口径 D）", "color": "NAVY",
                 "values": rounded([-s["h1"], -s["h2"], -s["fy"]])},
            ],
            "bar_labels": True,
            "fmt": "pct1", "label_fmt": "pct1", "yfmt": "pct0",
            "ylab": "经常性营业利润同比降幅",
            "note": ("<b>2024 年 Kering 三次在新闻稿里给出经常性营业利润的数字。</b>"
                     f"{g['roi_2024'][0]['release_date']} 的一季度收入公告说上半年经常性营业利润将「a decline of 40 to 45%」，"
                     f"实际 €{s['h1_24']:,.0f}M 对 €{s['h1_23']:,.0f}M，{s['h1']:.1f}%，落在区间里。"
                     "7 月的半年报接着说下半年「could be down by approximately 30%」；"
                     f"实际下半年是 €{s['h2_24']:,.0f}M D 对 €{s['h2_23']:,.0f}M D，{s['h2']:.1f}% —— "
                     "差了二十多个百分点。10 月的三季度收入公告把它换成了全年「approximately €2.5 billion」，"
                     f"实际 €{s['fy_eur']:,.0f}M，这一次兑现。"
                     "两句下半年与全年指引都带脚注「Based on the scope of consolidation and exchange rates」"
                     "（当时的合并范围与汇率）；公司从未按那个口径公布实际值，本页用报告口径结算，"
                     "而同期三季度收入公告给的汇率影响只有约 −1%，解释不了这个差。"),
            "src_extra": SOURCE_G,
        },
        {
            "ref": "EX_GUCCI_TARGET",
            "kind": "bar_line_dual",
            "title": (f"Gucci 的中期目标「收入 €10B / 利润率 40%+」：收入在 {g_rev_hit[0]} 达到、"
                      f"利润率在 {g_m_hit[0]} 达到，{'从未同一年' if not g_both else '同年达到'}"),
            "xlabels": years,
            "bar": {"name": "Gucci 全年收入", "values": rounded(g_rev, 1), "color": "NAVY"},
            "line": {"name": "Gucci 全年经常性营业利润率 D (RHS)", "values": rounded(g_m), "color": "RED",
                     "yfmt": "pct0"},
            "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
            "ylab": "€M（全年）", "ylab2": "经常性营业利润率",
            "note": ("<b>这是 2019-02-12 全年业绩演示材料上给 Gucci 的中期目标：「REVENUE €10BN / "
                     "EBIT MARGIN 40%+ MEDIUM TERM」。</b>"
                     f"利润率在 {g_m_hit[0]} 做到 {g_m[years.index(g_m_hit[0])]:.1f}%，那一年收入 "
                     f"€{g_rev[years.index(g_m_hit[0])]:,.0f}M；收入在 {g_rev_hit[0]} 做到 "
                     f"€{g_rev[years.index(g_rev_hit[0])]:,.0f}M，那一年利润率 "
                     f"{g_m[years.index(g_rev_hit[0])]:.1f}%。之后两条线一起往下走，"
                     f"{years[-1]} 收入 €{g_rev[-1]:,.0f}M、利润率 {g_m[-1]:.1f}%。"
                     "利润率按公司印出的品牌经常性营业利润 ÷ 品牌收入重算；2018 年及以前为 IAS 17 口径，"
                     "2019 年起为 IFRS 16 口径，按当年公布值、不做回溯。"),
            "src_extra": "目标取自 FY2018 业绩演示材料第 22 页；实际值取自各年全年业绩新闻稿。",
        },
        {
            "ref": "EX_YSL_TARGET",
            "kind": "bar_line_dual",
            "title": (f"Saint Laurent 的两级目标都兑现：€2B 在 {years[y2_first]}、€3B 在 {years[y3_first]}，"
                      "利润率当年都在目标之上"),
            "xlabels": years,
            "bar": {"name": "Saint Laurent 全年收入", "values": rounded(y_rev, 1), "color": "NAVY"},
            "line": {"name": "Saint Laurent 全年经常性营业利润率 D (RHS)", "values": rounded(y_m),
                     "color": "RED", "yfmt": "pct0"},
            "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
            "ylab": "€M（全年）", "ylab2": "经常性营业利润率",
            "note": ("同一份演示材料写的是「IN LINE WITH MT/LT AMBITIONS PRESENTED IN 2017 REVENUE €2BN THEN €3BN / "
                     "EBIT MARGIN 25%, THEN 27%」。"
                     f"{years[y2_first]} 收入 €{y_rev[y2_first]:,.0f}M、利润率 {y_m[y2_first]:.1f}%；"
                     f"{years[y3_first]} 收入 €{y_rev[y3_first]:,.0f}M、利润率 {y_m[y3_first]:.1f}%。"
                     "<b>同一份材料上两个品牌、两种结局</b>：Saint Laurent 在收入跨过每一级目标的那一年，"
                     "利润率都已在对应目标之上；Gucci 的两条是在不同年份分别碰到线（见上一张）。"
                     f"{years[-1]} Saint Laurent 收入 €{y_rev[-1]:,.0f}M，已回到 €3B 之下。"),
            "src_extra": "目标取自 FY2018 业绩演示材料第 23 页；实际值取自各年全年业绩新闻稿。",
        },
        {
            "ref": "EX_TARGETS_2022",
            "kind": "grouped_bars",
            "title": (f"FY2022 年报里的中期目标：Gucci €15B 在 FY2025 只完成 {t25[0]:.0f}%，"
                      f"比 FY2022 的 {t22[0]:.0f}% 更远"),
            "xlabels": [lab for lab, _, _ in t_items],
            "groups": [
                {"name": "FY2022", "color": "GOLD", "values": rounded(t22)},
                {"name": "FY2025", "color": "NAVY", "values": rounded(t25)},
            ],
            "bar_labels": True,
            "fmt": "pct0", "label_fmt": "pct0", "yfmt": "pct0",
            "ylab": "实际 ÷ 目标 D",
            "note": ("<b>FY2022 Universal Registration Document 把三个业务的中期目标写成了新的数字</b>"
                     "（Saint Laurent 与眼镜两处都注明是 2022 年更新）：Gucci「medium-term sales target of €15 billion」；Saint Laurent「revenue (now €5 billion) "
                     "and recurring operating margin (now 33%)」；Kering Eyewear「€2 billion in revenue and operating margin of over "
                     "15%」。图上每根柱是「实际 ÷ 目标」：Gucci 收入对 €15B，SL（Saint Laurent）收入对 €5B、利润率对 33%，"
                     "眼镜收入对 €2B、利润率对 15%。"
                     f"Gucci 从 FY2022 的 €{g_rev[years.index('FY2022')]:,.0f}M 走到 FY2025 的 €{g_rev[-1]:,.0f}M；"
                     f"Saint Laurent 利润率从 {y_m[years.index('FY2022')]:.1f}% 降到 {y_m[-1]:.1f}%。"
                     f"图上五项里只有眼镜的利润率站在目标上：FY2025 为 {ey_m:.1f}%。"
                     "眼镜 FY2022 的收入公司只在正文里写了「€1.1 billion」、利润没有单列，所以那两根柱留空；"
                     "Gucci 目标里的利润率只写了「historical recurring operating margin」，没有数字，不画。"),
            "src_extra": "目标取自 FY2022 Universal Registration Document 第 47、49、59 页；实际值取自 FY2022 与 FY2025 全年业绩新闻稿。",
        },
    ]


# ── section two: the quarter ─────────────────────────────────────────────────
def quarter_charts(st: dict, der: dict) -> list[dict]:
    q = st["long_quarters"]
    labels = [compact_quarter(p) for p in q]
    rev = st["quarterly_revenue_eur_m"]
    comp = st["quarterly_comparable_pct"]
    grid = st["new_grid"]
    gq = grid["quarters"]
    gr, gc = grid["revenue_eur_m"], grid["comparable_pct"]
    i26, i25 = gq.index("2026Q2"), gq.index("2025Q2")
    legs = [("时装与皮具", "fashion_leather_goods"), ("珠宝", "jewelry"), ("眼镜", "eyewear"),
            ("集团其他", "corporate_and_other"), ("内部抵销", "eliminations")]
    deltas = [(zh, gr[k][i26] - gr[k][i25]) for zh, k in legs]
    net = gr["total"][i26] - gr["total"][i25]
    jewelry_eyewear = sum(d for zh, d in deltas if zh in ("珠宝", "眼镜"))
    group_c = comp["group_first_published"]
    lp = der["last_positive_before"]
    break_2018 = q.index("2018Q1")
    jewelry_double_from = next(i for i, v in enumerate(gc["jewelry"]) if v is not None and v >= 10
                               and all(x >= 10 for x in gc["jewelry"][i:]))

    return [
        {
            "ref": "EX_GROUP_COMP",
            "kind": "lines",
            "title": (f"集团可比增速本季 {signed(group_c[-1], 0)}：{compact_quarter(q[lp])} 之后第一次为正"),
            "xlabels": labels,
            "series": [{"name": "集团季度可比增速（当季首次公布）", "values": rounded(group_c), "color": "NAVY"}],
            "fmt": "pct0", "yfmt": "pct0", "label_fmt": "pct0",
            "ylab": "可比增速", "zero_line": True, "end_label": True, "xstep": LONG_STEP,
            "break_at": break_2018, "break_label": "此前含 Puma",
            "note": (f"<b>{compact_quarter(q[lp])} 的 {signed(group_c[lp], 0)} 之后，集团可比增速"
                     f"经历了 {len(q) - 2 - lp} 个非正季度</b>（最后一季 {compact_quarter(q[-2])} 为 "
                     f"{group_c[-2]:+.0f}%）".replace("+0%", "0%") + f"，本季回到 {signed(group_c[-1], 0)}。"
                     "可比增速按定义剔除汇率与合并范围变化，所以这条线能跨越 2018 年 Puma 分拆、"
                     "2023 年 Creed 并表与 2025 年 Kering Beauté 出售连续读；"
                     "但 2018 年以前的读数本身包含 Puma 等运动与生活方式业务，红色虚线标出这一处。"
                     f"2020 年二季度的 {signed(min(group_c), 0)} 是门店关闭，2021 年二季度的 "
                     f"{signed(max(group_c), 0)} 是对着那个低基数。"),
            "src_extra": SOURCE_Q,
        },
        {
            "ref": "EX_Q2_BRIDGE",
            "kind": "bridge_bar",
            "title": (f"本季报告口径收入多了 €{net:,.0f}M：珠宝与眼镜合计 +€{jewelry_eyewear:,.0f}M，"
                      f"时装与皮具 {'−' if deltas[0][1] < 0 else '+'}€{abs(deltas[0][1]):,.0f}M"),
            "xlabels": [zh for zh, _ in deltas] + ["Q2 收入同比变动"],
            "stacks": [{"name": "各分部同比变动（€M）", "color": "NAVY",
                        "values": rounded([d for _, d in deltas] + [None], 1)}],
            "net": {"name": "集团 Q2 2026 对 Q2 2025 重述（€M）", "values": [None] * len(deltas) + [round(net, 6)]},
            "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
            "ylab": "€M（季度）",
            "note": ("<b>报告口径收入回到增长，不是 Gucci 带回来的。</b>"
                     f"Q2 2026 集团 €{gr['total'][i26]:,}M 对 Q2 2025（剔除 Kering Beauté 的重述值）"
                     f"€{gr['total'][i25]:,}M，多 €{net:,.0f}M；其中珠宝 {deltas[1][1]:+,.0f}、眼镜 {deltas[2][1]:+,.0f}，"
                     f"时装与皮具 {deltas[0][1]:+,.0f}（其中 Gucci {gr['gucci'][i26] - gr['gucci'][i25]:+,.0f}）。"
                     "分部口径是 2026 年一季度起的新口径，2025 年各季由公司在 2026-03-16 的公告中重述，"
                     "所以这张桥只能对着重述值画，没有更早的同口径对照。"),
            "src_extra": "Q2 2026 与重述后的 Q2 2025 取自 2026 上半年业绩新闻稿附表。",
        },
        {
            "ref": "EX_GRID",
            "kind": "grouped_bars",
            "title": ("新分部口径下的可比增速：Gucci 六季全负，珠宝从 "
                      f"{compact_quarter(gq[jewelry_double_from])} 起两位数"),
            "xlabels": [compact_quarter(p) for p in gq],
            "groups": [
                {"name": "Gucci", "color": "NAVY", "values": rounded(gc["gucci"])},
                {"name": "时装与皮具（含 Gucci）", "color": "MBLUE", "values": rounded(gc["fashion_leather_goods"])},
                {"name": "珠宝", "color": "GOLD", "values": rounded(gc["jewelry"])},
                {"name": "眼镜", "color": "GREEN", "values": rounded(gc["eyewear"])},
            ],
            "bar_labels": True,
            "fmt": "pct0", "label_fmt": "pct0", "yfmt": "pct0",
            "ylab": "可比增速",
            "note": ("<b>这张图只有六个季度，因为这套分部只存在六个季度。</b>"
                     "Kering 在 2026-03-16 宣布新分部（时装与皮具、珠宝、眼镜、集团其他），"
                     "只把 2025 年四个季度按新口径重述；珠宝此前包含在「其他品牌」里，没有按季单列的收入。"
                     f"Gucci 从 {signed(gc['gucci'][0], 0)} 收窄到 {signed(gc['gucci'][-1], 0)}，"
                     f"珠宝本季 {signed(gc['jewelry'][-1], 0)}、眼镜 {signed(gc['eyewear'][-1], 0)}。"
                     "Saint Laurent 与 Bottega Veneta 自 2026 年起不再单独披露收入。"),
            "src_extra": "2025 年四个季度取自新分部口径重述公告（2026-03-16）；2026 年取自当季公告。",
        },
        {
            "ref": "EX_GUCCI_Q",
            "kind": "gs_bar",
            "title": (f"Gucci 本季收入 €{rev['gucci'][-1]:,.0f}M，可比增速连续 "
                      f"{der['gucci_neg_streak']} 个季度为负（本季 {signed(comp['gucci'][-1], 0)}）"),
            "xlabels": labels,
            "values": rounded(rev["gucci"], 1),
            "legend": "Gucci 季度收入",
            "yoy": {"name": "可比增速 (RHS)", "values": rounded(comp["gucci"]), "yfmt": "pct0"},
            "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
            "ylab": "€M", "ylab2": "可比增速", "xstep": LONG_STEP,
            "note": (f"<b>峰值是 {compact_quarter(q[rev['gucci'].index(max(rev['gucci']))])} 的 "
                     f"€{max(rev['gucci']):,.0f}M，本季只有它的 {rev['gucci'][-1] / max(rev['gucci']) * 100:.0f}%。</b>"
                     f"可比增速在 2017 年最高到 {signed(max(comp['gucci'][4:8]), 1)}，"
                     f"自 {compact_quarter(q[len(q) - der['gucci_neg_streak']])} 起每一季为负，"
                     f"本季从上季的 {signed(comp['gucci'][-2], 0)} 收窄到 {signed(comp['gucci'][-1], 0)}。"
                     "Gucci 与 Bottega Veneta 的季度收入在本页读过的全部文件里，每一次被后续公告重印都与首次公布相同；"
                     "Saint Laurent 只有 2021 年三季度一处（652.9 与 652）。"),
            "src_extra": SOURCE_Q,
        },
    ]


# ── section three: what only the half-year shows ─────────────────────────────
def half_charts(st: dict, der: dict) -> list[dict]:
    halves = st["halves"]
    hg = st["half_group"]
    gm = der["group_margin"]
    hm = der["house_margin"]
    idx = {h: i for i, h in enumerate(halves)}
    g_peak = max(range(len(halves)), key=lambda i: hm["gucci"][i] or -1)
    grp_peak = max(range(len(halves)), key=lambda i: gm[i] or -1)
    b = der["bridge"]
    gross = der["gross_rate"]
    cont_from = idx["H1 2017"]
    gross_cont = [(gross[i], halves[i]) for i in range(cont_from, len(halves)) if gross[i] is not None]
    lowest = min(gross_cont)
    dates = st["balance_dates"]
    nd = st["net_debt_eur_m"]
    i_low = nd.index(min(nd))
    i_high = nd.index(max(nd))
    breaks = [idx["H1 2017"], idx["H1 2018"], idx["H1 2025"]]

    return [
        {
            "ref": "EX_HOUSE_MARGIN",
            "kind": "lines",
            "title": (f"半年经常性营业利润率：Gucci 从 {hm['gucci'][g_peak]:.1f}%（{halves[g_peak]}）"
                      f"降到 {hm['gucci'][-1]:.1f}%"),
            "xlabels": halves,
            "series": [
                {"name": "Gucci", "values": rounded(hm["gucci"]), "color": "NAVY"},
                {"name": "Saint Laurent", "values": rounded(hm["saint_laurent"]), "color": "GOLD"},
                {"name": "Bottega Veneta", "values": rounded(hm["bottega_veneta"]), "color": "GREEN"},
            ],
            "fmt": "pct1", "yfmt": "pct0", "label_fmt": "pct1",
            "ylab": "半年经常性营业利润率 D", "end_label": True, "xstep": 2,
            "break_at": idx["H1 2018"], "break_label": "2018 起为 IFRS 16 口径",
            "note": ("<b>这是半年图，不是季度图 —— 公司不按季披露品牌利润。</b>"
                     f"Gucci 在 {halves[g_peak]} 做到 {hm['gucci'][g_peak]:.1f}%，比同期 Saint Laurent 高 "
                     f"{hm['gucci'][g_peak] - hm['saint_laurent'][g_peak]:.1f}pp；"
                     f"到 H2 2025 Gucci {hm['gucci'][idx['H2 2025']]:.1f}%，已低于 Saint Laurent 的 "
                     f"{hm['saint_laurent'][idx['H2 2025']]:.1f}%。"
                     "Saint Laurent 与 Bottega Veneta 自 2026 年起不再披露，线停在 H2 2025。"
                     "利润率 = 品牌经常性营业利润 ÷ 品牌收入（两季相加），H2 为「全年减上半年」，标 D；"
                     "2018 年两个半年用公司按 IFRS 16 重述的数，与 2019 年起口径一致。"),
            "src_extra": SOURCE_H,
        },
        {
            "ref": "EX_GROUP_MARGIN",
            "kind": "bar_line_dual",
            "title": (f"集团半年经常性营业利润 €{hg['recurring_operating_income']['values'][-1]:,.0f}M、"
                      f"利润率 {gm[-1]:.1f}%，峰值是 {halves[grp_peak]} 的 {gm[grp_peak]:.1f}%"),
            "xlabels": halves,
            "bar": {"name": "半年经常性营业利润", "values": rounded(hg["recurring_operating_income"]["values"], 1),
                    "color": "NAVY"},
            "line": {"name": "半年经常性营业利润率 D (RHS)", "values": rounded(gm), "color": "RED", "yfmt": "pct0"},
            "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
            "ylab": "€M（半年）", "ylab2": "半年利润率", "xstep": 2,
            "break_at": breaks,
            "break_label": ["剔除 Puma", "IFRS 16", "剔除 Kering Beauté"],
            "note": ("<b>这条线上有三处口径切换，每一处都用虚线标出，没有一处被接平。</b>"
                     "2016 年为当时公布的集团口径（含 Puma 等运动与生活方式业务）；2017 年用公司 2018 年按 IFRS 5 "
                     "重述的持续经营口径；2018 年用按 IFRS 16 重述的数；2025 年起剔除 Kering Beauté。"
                     "2024 年下半年无法按剔除 Beauté 的口径算，因为公司没有重述 2024 年上半年的利润。"
                     f"本半年 {gm[-1]:.1f}% 对 H1 2025 重述值 {gm[idx['H1 2025']]:.1f}%；"
                     f"H2 2025 是 {gm[idx['H2 2025']]:.1f}%，也是这 {len(halves)} 个半年里最低的。"),
            "src_extra": SOURCE_H,
        },
        {
            "ref": "EX_H1_BRIDGE",
            "kind": "bridge_bar",
            "title": (f"上半年利润率 {b['to'] - b['from']:+.2f}pp：毛利率 {b['gross']:+.2f}pp，"
                      "被两项费用率抵掉还有余"),
            "xlabels": ["毛利率变动", "人员费用率变动", "其他经常性费用率变动", "经常性营业利润率变动"],
            "stacks": [{"name": "占收入比例的变动（pp）", "color": "NAVY",
                        "values": rounded([b["gross"], b["personnel"], b["other"], None])}],
            "net": {"name": "H1 2026 对 H1 2025 重述（pp）", "values": [None, None, None, round(b["to"] - b["from"], 6)]},
            "fmt": "pp1", "yfmt": "pp1", "label_fmt": "pp1",
            "ylab": "百分点（半年）",
            "note": ("<b>利润率的改善全部来自费用，毛利率在往下走。</b>"
                     f"经常性营业利润率从 {b['from']:.2f}% 到 {b['to']:.2f}%。"
                     "三条腿按损益表逐行算：毛利、人员费用、其他经常性经营收支各自除以收入，"
                     "三项之差相加恰好等于利润率之差 —— 这是恒等式，不是近似。"
                     "对照是公司在 2026 上半年新闻稿里印出的、剔除 Kering Beauté 的 H1 2025 重述损益表。"),
            "src_extra": "两期损益表均取自 2026 上半年业绩新闻稿。",
        },
        {
            "ref": "EX_GROSS",
            "kind": "lines",
            "title": (f"半年毛利率 {gross[-1]:.1f}%：持续经营口径（H1 2017 起）"
                      f"{'以来最低' if lowest[1] == halves[-1] else '低点是 ' + lowest[1]}"),
            "xlabels": halves,
            "series": [{"name": "半年毛利率 D", "values": rounded(gross), "color": "NAVY"}],
            "fmt": "pct1", "yfmt": "pct0", "label_fmt": "pct1",
            "ylab": "半年毛利率", "end_label": True, "xstep": 2,
            "break_at": [idx["H1 2017"], idx["H1 2025"]],
            "break_label": ["剔除 Puma", "剔除 Kering Beauté"],
            "note": (f"2016 年两个半年含 Puma，毛利率只有 {gross[0]:.1f}% 与 {gross[1]:.1f}%，"
                     "与之后不可比，所以用虚线隔开。"
                     f"持续经营口径下毛利率在 {max(gross_cont)[1]} 最高、为 {max(gross_cont)[0]:.1f}%，"
                     f"本半年 {gross[-1]:.1f}%。"
                     "毛利率不受 IFRS 16 影响（租赁费用在毛利以下），所以 2018 年直接用公布值。"
                     "H2 为「全年毛利 − 上半年毛利」÷「全年收入 − 上半年收入」，标 D。"),
            "src_extra": SOURCE_H,
        },
        {
            "ref": "EX_NET_DEBT",
            "kind": "bars_labeled",
            "title": (f"净负债 €{nd[-1]:,.0f}M：{dates[i_low][:7]} 的 €{nd[i_low]:,.0f}M 涨到 "
                      f"{dates[i_high][:7]} 的 €{nd[i_high]:,.0f}M 再降回来"),
            "xlabels": dates,
            "values": rounded(nd, 1),
            "label_fmt": "f0c", "fmt": "f0c", "yfmt": "f0c",
            "ylab": "€M（期末）", "xstep": 2,
            "note": ("<b>净负债按公司定义不含租赁负债，整条序列口径没有变过。</b>"
                     f"从 {dates[i_low]} 的 €{nd[i_low]:,.0f}M 涨到 {dates[i_high]} 的 €{nd[i_high]:,.0f}M，"
                     "期间有 2023 年 Creed 收购与 Valentino 30% 股权、2024 年的房地产购置。"
                     f"本期末 €{nd[-1]:,.0f}M，比 2025 年末少 €{nd[-2] - nd[-1]:,.0f}M；"
                     "公司在半年报里写明现金中包含 2026-03-31 完成出售 Kering Beauté 收到的 €4.0 billion。"
                     "所以这一段下降主要是卖资产，不是经营现金流。"),
            "src_extra": "期末净负债取自各期半年度财务报告与全年业绩新闻稿的净负债表（精确值）。",
        },
    ]


# ── section four: the long record ────────────────────────────────────────────
def long_charts(st: dict, der: dict) -> list[dict]:
    q = st["long_quarters"]
    end = q.index("2025Q4") + 1
    labels = [compact_quarter(p) for p in q[:end]]
    rev = st["quarterly_revenue_eur_m"]
    comp = st["quarterly_comparable_pct"]
    share = der["gucci_share"][:end]
    peak = max(range(end), key=lambda i: share[i])
    break_2022 = q.index("2022Q1")
    ysl_first_over_gucci = next((i for i in range(len(q)) if comp["saint_laurent"][i] is not None
                                 and comp["gucci"][i] is not None and i >= q.index("2023Q1")
                                 and all(comp["saint_laurent"][j] > comp["gucci"][j]
                                         for j in range(i, end))), None)

    return [
        {
            "ref": "EX_HOUSES",
            "kind": "stacked_dual",
            "title": (f"四条品牌线的季度收入：Gucci 占比从 {labels[peak]} 的 {share[peak]:.1f}% "
                      f"降到 {labels[-1]} 的 {share[-1]:.1f}%"),
            "xlabels": labels,
            "stacks": [
                {"name": "Gucci", "color": "NAVY", "values": rounded(rev["gucci"][:end], 1)},
                {"name": "Saint Laurent", "color": "GOLD", "values": rounded(rev["saint_laurent"][:end], 1)},
                {"name": "Bottega Veneta", "color": "GREEN", "values": rounded(rev["bottega_veneta"][:end], 1)},
                {"name": "其他品牌", "color": "GRAY", "values": rounded(rev["other_houses"][:end], 1)},
            ],
            "line": {"name": "Gucci 占四条品牌线合计 D (RHS)", "color": "RED", "values": rounded(share),
                     "yfmt": "pct1", "ymax": 100},
            "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
            "ylab": "€M", "ylab2": "Gucci 占比", "xstep": LONG_STEP,
            "break_at": break_2022, "break_label": "其他品牌 2022 年起列报方式变更",
            "note": ("<b>这张图停在 2025 年四季度：2026 年起 Saint Laurent、Bottega Veneta 与「其他品牌」不再单独披露。</b>"
                     "「其他品牌」在 2018 年一季度以前用公司 2018 年 6 月按 IFRS 5 重述的口径"
                     "（剔除 Stella McCartney 与 Christopher Kane），与之后连续；"
                     "2022 年一季度起公司把 2021 年「其他品牌」每季上调约 €4–6M 重新列报、未说明原因，"
                     "本页保留每季首次公布值，并在那一处画虚线。"
                     "占比的分母是四条品牌线之和，不是集团收入 —— 集团收入里还有眼镜、集团其他与内部抵销，"
                     "而且口径换过三次。"),
            "src_extra": SOURCE_Q + " 2016–2017 年「其他品牌」取自按 IFRS 5 重述的关键指标（2018-06）。",
        },
        {
            "ref": "EX_HOUSE_COMP",
            "kind": "lines",
            "title": ("三个品牌的季度可比增速：Saint Laurent 从 "
                      f"{compact_quarter(q[ysl_first_over_gucci]) if ysl_first_over_gucci is not None else '—'}"
                      " 起每一季都跑赢 Gucci"),
            "xlabels": [compact_quarter(p) for p in q],
            "series": [
                {"name": "Gucci", "values": rounded(comp["gucci"]), "color": "NAVY"},
                {"name": "Saint Laurent", "values": rounded(comp["saint_laurent"]), "color": "GOLD"},
                {"name": "Bottega Veneta", "values": rounded(comp["bottega_veneta"]), "color": "GREEN"},
            ],
            "fmt": "pct0", "yfmt": "pct0", "label_fmt": "pct0",
            "ylab": "可比增速", "zero_line": True, "end_label": True, "xstep": LONG_STEP,
            "note": ("可比增速是公司口径，剔除汇率与合并范围变化，是三条品牌线里最能连续读的一种量。"
                     f"Gucci 2017 年四个季度在 {min(comp['gucci'][4:8]):+.1f}% 到 {max(comp['gucci'][4:8]):+.1f}% 之间；"
                     f"Bottega Veneta 反过来，2016 年四季全负、近年多为正。"
                     "Saint Laurent 与 Bottega Veneta 的线停在 2025 年四季度，因为 2026 年起不再单独披露。"
                     "2020 年二季度与 2021 年二季度的两个极值是门店关闭与低基数，三个品牌同时出现。"),
            "src_extra": SOURCE_Q,
        },
    ]


# ── section five: next-quarter tracking ──────────────────────────────────────
def routine_charts(st: dict, der: dict) -> list[dict]:
    entries = st["next_kpi"]["entries"]
    breached = [e["metric"] for e in entries if headroom(e["direction"], e["threshold"], e["current"]) < 0]
    return [
        headroom_exhibit(
            f"下季跟踪阈值：{len(entries)} 条里 {len(entries) - len(breached)} 条在安全侧",
            entries, "current",
            ("阈值是本地研究设定，不是公司指引。正值代表仍在安全侧。"
             "<b>2026 上半年新闻稿的展望段落里没有数字</b>，只写「its objective remains to return to growth "
             "and improve profitability」；资本市场日给的是中期目标（利润率为 FY2025 的两倍以上），"
             "见下一张。原始单位的阈值与当前值见核对表。"),
            "阈值与理由见核对表；当前值取自本页已列示的公司披露值与透明自算。",
        ),
        threshold_exhibit(
            f"半年利润率对资本市场日的中期目标：FY2025 的两倍是 {der['cmd_margin_line']:.1f}%",
            st["halves"], rounded(der["group_margin"]), round(der["cmd_margin_line"], 2),
            fmt="pct1", ylab="半年经常性营业利润率 D",
            actual_name="半年经常性营业利润率 D",
            threshold_name=f"FY2025 利润率 × 2（{der['cmd_margin_line']:.1f}%）",
            note=("2026-04-16 资本市场日第 121 页：「More than double FY 2025 recurring operating margin percentage」，"
                  "期限写的是「MID-TERM」，没有年份。"
                  f"FY2025 全年利润率 {der['fy25_margin']:.1f}%（剔除 Kering Beauté），两倍是 "
                  f"{der['cmd_margin_line']:.1f}%；本半年 {der['group_margin'][-1]:.1f}%，差 "
                  f"{der['cmd_margin_line'] - der['group_margin'][-1]:.1f}pp。"
                  f"{len(st['halves'])} 个半年里有 {der['halves_above_cmd']} 个高于这条线，最近一次是 "
                  f"{der['last_above_cmd']} —— 目标不是没到过的水平，而是回到过去的水平。"
                  "口径切换见 Exhibit {EX_GROUP_MARGIN}。"),
            src_extra=SOURCE_H + " 目标取自 2026 资本市场日演示材料。",
            xstep=2,
        ),
    ]


def build_payload(st: dict) -> dict:
    der = derived(st)
    said_ex = settled_charts(st, der)
    quarter_ex = quarter_charts(st, der)
    half_ex = half_charts(st, der)
    long_ex = long_charts(st, der)
    routine_ex = routine_charts(st, der)
    exhibits = number_exhibits(said_ex + quarter_ex + half_ex + long_ex + routine_ex)
    resolve_exhibit_refs(exhibits)

    q = st["long_quarters"]
    rev = st["quarterly_revenue_eur_m"]
    comp = st["quarterly_comparable_pct"]
    halves = st["halves"]
    hg = st["half_group"]
    hh = st["half_house"]
    grid = st["new_grid"]

    fmt = lambda v, d=1: "—" if v is None else f"{v:,.{d}f}"
    pct = lambda v: "—" if v is None else f"{v:+g}%"
    q_rows = [[p] + [fmt(rev[h][i]) for h in ("gucci", "saint_laurent", "bottega_veneta", "other_houses")]
              + [pct(comp[h][i]) for h in ("gucci", "saint_laurent", "bottega_veneta", "other_houses")]
              + [fmt(rev["group_first_published"][i]), pct(comp["group_first_published"][i])]
              for i, p in enumerate(q)]
    perim_rows = ([[x["period"], fmt(x["first_published"]), fmt(x["ifrs5_june_2018"]), fmt(x["proforma_april_2018"]),
                    "本页采用 IFRS 5（2018-06）口径"] for x in st["other_houses_perimeter_2016_2018"]]
                  + [[x["period"], fmt(x["first_published"]), "—", "—",
                      f"2022 年重列为 {fmt(x['represented_2022'])}；本页保留首次公布值"]
                     for x in st["other_houses_representation_2021"]])
    grid_lines = [("时装与皮具", "fashion_leather_goods"), ("其中 Gucci", "gucci"), ("珠宝", "jewelry"),
                  ("眼镜", "eyewear"), ("集团其他", "corporate_and_other"), ("内部抵销", "eliminations"),
                  ("集团合计", "total")]
    grid_rows = [[compact_quarter(p)] + [f"{grid['revenue_eur_m'][k][i]:,}" for _, k in grid_lines]
                 + [pct(grid["comparable_pct"][k][i]) for _, k in grid_lines[:4]] + [pct(grid["comparable_pct"]["total"][i])]
                 for i, p in enumerate(grid["quarters"])]
    basis_zh = {"published_incl_sport_lifestyle": "公布值（含运动与生活方式）",
                "continuing_restated_ifrs5": "IFRS 5 重述的持续经营口径",
                "ifrs16_restated": "IFRS 16 重述", "published": "公布值",
                "published_incl_beaute": "公布值（含 Kering Beauté）",
                "restated_ex_beaute": "重述（剔除 Kering Beauté）", "published_new_grid": "公布值（新分部口径）"}
    half_rows = [[h, "公司印出" if hg["revenue"]["flag"][i] == "printed" else "全年减上半年 D",
                  basis_zh[hg["revenue"]["basis"][i]],
                  fmt(hg["revenue"]["values"][i]), fmt(hg["gross_margin"]["values"][i]),
                  fmt(hg["recurring_operating_income"]["values"][i]),
                  fmt(der["gross_rate"][i], 2) + "%", fmt(der["group_margin"][i], 2) + "%"]
                 for i, h in enumerate(halves)]
    house_rows = []
    for i, h in enumerate(halves):
        row = [h]
        for k in ("gucci", "saint_laurent", "bottega_veneta"):
            r = hh[k]["roi_eur_m"][i] if i < len(hh[k]["roi_eur_m"]) else None
            m = der["house_margin"][k][i]
            row += [fmt(r), "—" if m is None else f"{m:.2f}%"]
        house_rows.append(row)
    nd_rows = [[d, f"{v:,.1f}", doc_label(s)] for d, v, s in zip(st["balance_dates"], st["net_debt_eur_m"],
                                                                 st["net_debt_src"])]
    g = st["guidance_record"]
    s = der["settle"]
    guide_rows = [
        ["2024 上半年经常性营业利润", g["roi_2024"][0]["release_date"], g["roi_2024"][0]["quote"],
         "−40% 至 −45%", f"{s['h1']:.1f}%", "兑现"],
        ["2024 下半年经常性营业利润", g["roi_2024"][1]["release_date"], g["roi_2024"][1]["quote"],
         "约 −30%", f"{s['h2']:.1f}%", "未兑现"],
        ["2024 全年经常性营业利润", g["roi_2024"][2]["release_date"], g["roi_2024"][2]["quote"],
         "约 €2,500M", f"€{s['fy_eur']:,.0f}M", "兑现"],
        ["Gucci 中期", g["medium_term_2019"][0]["release_date"], g["medium_term_2019"][0]["quote"],
         "收入 €10B / 利润率 40%+", "分别在不同年份达到，从未同年", "未同时兑现"],
        ["Saint Laurent 中长期", g["medium_term_2019"][1]["release_date"], g["medium_term_2019"][1]["quote"],
         "€2B 与 25%，再 €3B 与 27%", "两级都与利润率同年达到", "兑现"],
    ] + [["集团中期（资本市场日）", "2026-04-16", c["quote"], "—", "尚未到期", "待结算"] for c in g["cmd_2026"]]

    entries = st["next_kpi"]["entries"]
    kpi = threshold_table(0, "下季跟踪阈值与当前值（原始单位）", entries, "current", "当前值")
    kpi["headers"] = kpi["headers"] + ["为什么是这条线"]
    kpi["rows"] = [row + [e["why"]] for row, e in zip(kpi["rows"], entries)]

    first_table = exhibits[-1]["n"] + 1
    tables = [
        {"title": "四十二季品牌线收入（€M）与可比增速（当季首次公布）",
         "headers": ["季度", "Gucci", "Saint Laurent", "Bottega Veneta", "其他品牌",
                     "Gucci 可比", "SL 可比", "BV 可比", "其他品牌可比", "集团收入（首次公布）", "集团可比"],
         "rows": q_rows},
        {"title": "「其他品牌」的三种口径：2016–2018 年的合并范围，与 2021 年的重新列报",
         "headers": ["季度", "首次公布", "IFRS 5 重述（2018-06）", "备考（2018-04）", "本页取法"],
         "rows": perim_rows},
        {"title": "新分部口径的六个季度（€M 与可比增速）",
         "headers": ["季度"] + [zh for zh, _ in grid_lines] + ["时装与皮具可比", "Gucci 可比", "珠宝可比", "眼镜可比", "集团可比"],
         "rows": grid_rows},
        {"title": "二十一个半年的集团收入、毛利与经常性营业利润（€M）；H2 为全年减上半年",
         "headers": ["半年", "来源", "口径", "收入", "毛利", "经常性营业利润", "毛利率 D", "利润率 D"],
         "rows": half_rows},
        {"title": "品牌半年经常性营业利润（€M）与利润率（本页重算）",
         "headers": ["半年", "Gucci 利润", "Gucci 利润率 D", "SL 利润", "SL 利润率 D", "BV 利润", "BV 利润率 D"],
         "rows": house_rows},
        {"title": "期末净负债（€M，不含租赁负债）与取值文件",
         "headers": ["日期", "净负债", "取自"], "rows": nd_rows},
        {"title": "公司给过的数字目标与结算（原话逐字）",
         "headers": ["主题", "发布日期", "原话", "所述", "实际", "判词"], "rows": guide_rows},
        kpi,
        ai_capex_cycle_table(0),
    ]
    for offset, table in enumerate(tables):
        table["n"] = first_table + offset
        # keep key order n, title, headers, rows
    tables = [{"n": t["n"], "title": t["title"], "headers": t["headers"], "rows": t["rows"]} for t in tables]

    gm = der["group_margin"]
    b = der["bridge"]
    return {
        "schema_version": "quarterly-dashboard/ker-v1",
        "page": {"slug": "ker", "language": "zh-CN"},
        "company": {"ticker": "KER.PA", "name": "Kering SA", "group": "luxury_brands",
                    "accounting_standard": "IFRS"},
        "latest": {
            "disclosed_period_label": "Q2 2026",
            "full_financial_period_label": "H1 2026",
            "period_end": "2026-06-30",
            "release_date": "2026-07-28",
            "analysis_date": "2026-09-17",
            "audit_status": "limited_review",
            "status": "history_ready",
        },
        "tracker": "Watchlist Quarterly Tracker · KER.PA",
        "title": "Kering（KER.PA）：Q2 2026 / H1 2026 季报仪表盘",
        "subtitle": ("截至 2026-06-30 · 发布 2026-07-28 · IFRS 合并 · 全部以欧元列示 · "
                     "收入按季披露，利润只有半年度 · 2026 年起采用新分部口径"),
        "headline": (f"本季集团可比增速 {signed(comp['group_first_published'][-1], 0)}，"
                     f"Gucci {signed(comp['gucci'][-1], 0)}、连续 {der['gucci_neg_streak']} 个季度为负；"
                     f"上半年利润率 {gm[-1]:.1f}%，比重述后的上年同期高 {b['to'] - b['from']:.2f}pp，"
                     f"但毛利率低了 {-b['gross']:.2f}pp —— 改善来自费用率，不是来自毛利；"
                     f"净负债降到 €{st['net_debt_eur_m'][-1]:,.0f}M，降幅里有 €4.0B 是出售 Kering Beauté 的现金。"),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>收入</span><b>集团转正了，Gucci 还没有</b>'
            f'<p>Q2 报告口径多出 €{grid["revenue_eur_m"]["total"][-1] - grid["revenue_eur_m"]["total"][1]:,}M：'
            f'珠宝与眼镜合计 +€{(grid["revenue_eur_m"]["jewelry"][-1] - grid["revenue_eur_m"]["jewelry"][1]) + (grid["revenue_eur_m"]["eyewear"][-1] - grid["revenue_eur_m"]["eyewear"][1]):,}M，'
            f'时装与皮具 −€{grid["revenue_eur_m"]["fashion_leather_goods"][1] - grid["revenue_eur_m"]["fashion_leather_goods"][-1]:,}M。</p></article>'
            '<article><span>利润</span><b>利润率改善来自费用，毛利率在下降</b>'
            f'<p>毛利率 {b["gross"]:+.2f}pp，人员与其他费用率合计 {b["personnel"] + b["other"]:+.2f}pp。</p></article>'
            '<article><span>兑现</span><b>说得最具体的一次没兑现</b>'
            f'<p>2024 年下半年指引约 −30%，实际 {der["settle"]["h2"]:.1f}%；'
            'Gucci 的 €10B 与 40% 从未同年到达，2022 年再提的 €15B 更远。</p></article>'
            '</div>'
        ),
        "source": ('Source: <a href="https://www.kering.com/en/finance/publications/" rel="noopener">Kering Finance '
                   'Publications</a>（季度收入公告、半年度与全年业绩新闻稿、半年度财务报告、Financial Document、'
                   '演示材料与重述公告）。Kering 不是 SEC 报告发行人，本页没有任何 EDGAR 来源。'),
        "source_url": "https://www.kering.com/en/finance/publications/",
        "source_links": [{"label": doc_label(x["doc"]), "url": x["url"]} for x in st["sources"]],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {"id": "settled",
             "title": "一、公司给过的数字，结算了没有",
             "description": ("Kering 给过的数字目标散在新闻稿、演示材料与年度文件里。这一节只结算能在原口径上核的："
                             "2024 年三次利润指引、2019 年与 2022 年的品牌中期目标；其余目标逐条列在核对表里，"
                             "2026 年资本市场日的中期目标尚未到期，放在最后一节跟踪。"),
             "exhibits": said_ex},
            {"id": "quarter_highlights",
             "title": "二、本季重点：集团回到增长，增长来自哪里",
             "description": "季度口径只有收入。这一节看集团可比增速、分部贡献与 Gucci 本身。",
             "exhibits": quarter_ex},
            {"id": "half_year",
             "title": "三、只有半年度披露才看得见的：利润、毛利与负债",
             "description": "本节所有利润图的 x 轴都是半年，不是季度；净负债是期末时点。",
             "exhibits": half_ex},
            {"id": "long_record",
             "title": "四、四十二季的品牌记录",
             "description": "季度收入与可比增速回到 2016 年一季度；品牌线停在 2025 年四季度，因为之后不再披露。",
             "exhibits": long_ex},
            {"id": "routine",
             "title": "五、下季跟踪",
             "description": "阈值为本地研究设定，不是公司指引；再加资本市场日中期利润率目标的距离。",
             "exhibits": routine_ex},
        ],
        "tables": tables,
        "notes": [
            "本页按「给过的数字 → 本季 → 半年度独有 → 长期记录 → 下季跟踪」五段排列，支撑表格收在核对抽屉里。",
            "Kering 一年发四次收入、只发两次利润。第一与第三季度只发收入公告；损益表、品牌经常性营业利润、现金流与资产负债表只在半年度与全年披露。所以收入用季度轴、利润用半年轴，两条轴各自独立，本页不做任何按季摊平。",
            "Kering 不是 SEC 报告发行人：EDGAR 上 CIK 1445465 名下只有 ADR 存托登记文件（F-6EF、424B3），没有任何财务报表。本页全部数据取自 kering.com 发布的文件。",
            "本页用到的每一份文件都由两个互不知情的转录者各读一遍，逐格比对，所有不一致的格子回到原页裁定；再按期间把同一季度在不同文件里的全部读数排在一起，凡是与首次公布不同的，都能对上一次有记录的口径变更。",
            "季度收入与可比增速一律取当季首次公布它的那份公告：第二季度取半年度业绩新闻稿附表，第四季度取全年业绩新闻稿附表。",
            "口径变更一：2018 年一季度起 Puma、Volcom、Stella McCartney（后来加上 Christopher Kane）转入终止经营。本页「其他品牌」在 2018 年以前采用公司 2018 年 6 月按 IFRS 5 重述的关键指标，与 2018 年全年新闻稿的比较数一致；2018 年 4 月的备考文件口径略不同（仍含 Christopher Kane），两套数并列在核对表里。",
            "口径变更二：2019 年起适用 IFRS 16。公司把 2018 年按 IFRS 16 重述过，本页半年利润图 2018 年起用 IFRS 16 口径；2016–2017 年为 IAS 17 口径，图上画了虚线。毛利率不受 IFRS 16 影响，2018 年直接用公布值。",
            "口径变更三：2022 年一季度起「集团其他」改为「Kering Eyewear 与集团」并单列内部抵销，同时 2021 年「其他品牌」每季被重新列报高出约 €4–6M，公司没有说明原因。本页保留 2021 年各季首次公布值，重列值并列在核对表第二张。",
            "口径变更四：2025 年全年起 Kering Beauté 转入终止经营，2024 年与 2025 年前三季收入重述；2026 年一季度起采用新分部（时装与皮具、珠宝、眼镜、集团其他），公司只把 2025 年按新分部重述。2024 年上半年利润没有剔除 Beauté 的重述，所以 2024 年两个半年保持含 Beauté 的公布值。",
            "Saint Laurent 2021 年三季度收入首次公布为 652.9 百万欧元，在 2022 年的重新列报表里印作 652；文件没有说明这是凑整还是重述。本页保留首次公布值。在本页读过的全部文件里，这是三条品牌线唯一一处与首次公布不同的重印。",
            "H2 各行由「全年减上半年」得出并标 D；半年品牌收入取当季首次公布的两个季度相加，与公司印出的半年表逐一核对过。",
            "2024 年下半年与全年利润指引都附脚注「Based on the scope of consolidation and exchange rates」（当时的合并范围与汇率）；公司从未按该口径公布实际值，本页用报告口径结算，并在图注里写明。",
            "净负债按公司定义不含租赁负债，整条序列口径一致；公告正文只印到 0.1 十亿欧元，本页取半年度财务报告与全年新闻稿净负债表里的精确值。",
            "第五节的阈值是本地研究设定，不是公司指引，也不构成评级或投资建议；「距阈值余量」统一为正值代表安全侧。",
            "本页只发布公司披露值与可复算的简单派生值；D 标记代表 Derived / 自算。电话会记录仅作背景，不作为本页任何数字的来源。",
            "本页已知未接入：品牌的分地区收入（公司只给零散的文字增速）、按季的零售与批发拆分、门店数（两份文件对同一时点的门店数不一致，见各年财务文件）、2026 年起 Saint Laurent 与 Bottega Veneta 的任何数字（公司不再披露）。",
        ],
        "footer": "Kering quarterly results · 数据来自公司公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "ker.js"), payload, "ker")
    shell_dir = ROOT / "ker"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("KER.PA", "ker"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"Kering page: {charts} charts in {len(payload['sections'])} sections "
          f"+ {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
