#!/usr/bin/env python3
"""LVMH Moët Hennessy Louis Vuitton quarterly dashboard.

LVMH publishes revenue four times a year and profit twice. The first and third
quarter releases are revenue announcements: divisional euro amounts and organic
growth rates, and not one line of profit. The income statement, divisional
operating profit, the currency and perimeter effects on profit, the cash flow
statement, the balance sheet, the store count and earnings per share exist only
at the half-year and the full year.

So in the eight quarters this page covers, **no quarter has a profit number of
its own**. That is not a gap in the sourcing; it is the disclosure. The page
therefore runs two independent x axes -- revenue by quarter, profit by half --
and interpolates nothing. Every half-year chart says "半年" in its own axis
label, because a reader who mistakes a half for a quarter here halves every
margin denominator on the page.

**And the half is where this particular half-year lived.** By April the market
had already seen the revenue half of H1 2026: Q1 organic +1%. What arrived only
on July 27 was the margin -- 22.5% at group level, and Fashion & Leather Goods
at 34.1%, a 60bp decline the company says is more than entirely currency. On
+2% organic growth. At the Q1 call the CFO had said the group needed "3% to 4%
organic growth in order to stabilize margin", adding "we could maybe do it with
a bit less"; it was the caveat that held, and at the Q2 call the same 3-4%
reappeared attached to a different claim -- no longer the level that stabilizes
margin, but the level at which operating leverage begins.

The company issues no numeric guidance at all. Its only forward statements are
sentences on a call, so section one scores sentences: six of them, made on
2026-04-13 and settled on 2026-07-27. The one stated most firmly in the negative
-- that Wines & Spirits' first-quarter strength was a Chinese New Year shipment
phasing that "will not be repeating" in Q2 -- is the one that was wrong: Q2
organic growth was +5%, identical to Q1, and the company then attributed the
half to volume rather than to phasing.

Published numbers are company-reported or transparent arithmetic. Thresholds in
section four are local research settings, not company guidance.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import (  # noqa: E402
    ai_capex_cycle_table,
    headroom_exhibit,
    number_exhibits,
    threshold_exhibit,
    threshold_table,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "mc.json"
DATA_DIR = ROOT / "data"

DIVS = ["wines_spirits", "fashion_leather", "perfumes_cosmetics",
        "watches_jewelry", "selective_retailing"]
DIV_COLORS = {"wines_spirits": "GOLD", "fashion_leather": "NAVY",
              "perfumes_cosmetics": "GREEN", "watches_jewelry": "BLUE",
              "selective_retailing": "MBLUE", "other": "GRAY"}

SOURCE_QUARTER = ("分部季度收入与有机增速逐季取自公司自己的季度收入公告与半年度／全年业绩新闻稿附录"
                  "「Revenue by business group and by quarter」，以及全年业绩演示材料附录的"
                  "「Quarterly revenue by business group – Organic change」。")
SOURCE_HALF = ("半年度数字取自当期半年度业绩新闻稿与半年度财务报告；H2 各行由「全年减上半年」得出并标 D，"
               "全年数取自 Financial Documents。公司不按季披露任何利润行。")
SOURCE_CALL = ("原话逐字取自公司业绩电话会记录（2026-04-13 与 2026-07-27），"
               "结算值取自 H1 2026 业绩新闻稿与半年度财务报告。")


def compact_quarter(period: str) -> str:
    """`2026Q2` -> `Q2'26`, the axis label the rest of the site uses."""
    return f"{period[4:]}'{period[2:4]}"


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100.0


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

    # The seasonal shape the semi-annual disclosure is the only way to see: in
    # every complete year on this page the second half carries more revenue and
    # a lower margin than the first.
    pairs = []
    for i in range(0, len(halves) - 1, 2):
        if halves[i].startswith("H1") and halves[i + 1].startswith("H2"):
            pairs.append({
                "year": halves[i].split()[1],
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


# ── section one: the record of what was said ─────────────────────────────────
def said_charts(staging: dict, der: dict, labels: list[str]) -> list[dict]:
    record = staging["call_record"]
    items = {item["key"]: item for item in record["items"]}
    org = der["organic"]

    ws_q1, ws_q2 = org["wines_spirits"][-2], org["wines_spirits"][-1]
    flg_q2 = org["fashion_leather"][-1]

    quarter_pairs = {
        "xlabels": ["葡萄酒与烈酒", "时装与皮具", "香水与化妆品", "手表与珠宝", "精品零售", "集团合计"],
        "q1": [org[d][-2] for d in DIVS] + [org["total"][-2]],
        "q2": [org[d][-1] for d in DIVS] + [org["total"][-1]],
    }

    said_vs_actual = [
        ("中东冲突对集团有机增速<br>（本季，pp）", -1.0, -1.0),
        ("上半年汇率对经营利润率<br>（pp）", -0.8, -0.7),
        ("时装与皮具本季有机增速<br>（公司锚点「flattish」，%）", 0.0, flg_q2),
        ("稳住利润率所需的有机增速<br>对本半年实际有机增速（%）", 3.0, 2.0),
    ]

    return [
        {
            "ref": "EX_SAID",
            "kind": "grouped_bars",
            "title": (f"公司唯一明确说「不会重复」的分部，本季又是 {signed(ws_q2, 0)} —— "
                      f"和上季一模一样"),
            "xlabels": quarter_pairs["xlabels"],
            "groups": [
                {"name": "Q1 2026 有机增速", "color": "BLUE", "values": rounded(quarter_pairs["q1"])},
                {"name": "Q2 2026 有机增速", "color": "NAVY", "values": rounded(quarter_pairs["q2"])},
            ],
            "bar_labels": True,
            "fmt": "pct0", "label_fmt": "pct0", "yfmt": "pct0",
            "ylab": "有机增速",
            "note": ("<b>LVMH 不发布任何数字指引。</b>它对未来的全部陈述都是电话会上的句子，"
                     "所以这一节能核的只有句子。上季电话会上，管理层对葡萄酒与烈酒说得最硬："
                     f"Q1 的 {signed(ws_q1, 0)} 里有中国春节从一月挪到二月的发货相位利好，"
                     "「Q2 will not be repeating Q1 overall given this impact」。"
                     f"本季该分部有机增速 {signed(ws_q2, 0)}，与上季<b>完全相同</b>，"
                     "而公司在本季电话会上把上半年的增长归因于「predominantly volume growth」—— "
                     "不是相位。同一场电话会里被追问最多的时装与皮具，反而落在管理层暗示区间的上沿："
                     f"公司当时给的唯一锚点是「三月剔除冲突本应大致持平」，本季实际 {signed(flg_q2, 0)}。"
                     f"完整六条记录见核对表 {{TBL_SAID}}。"),
            "src_extra": SOURCE_CALL,
        },
        {
            "ref": "EX_SCORE",
            "kind": "grouped_bars",
            "title": "四条能落到数字上的陈述：三条兑现，一条靠它自己预留的余地兑现",
            "xlabels": [label for label, _, _ in said_vs_actual],
            "xrot": 0,
            "groups": [
                {"name": "上季电话会所述", "color": "GOLD",
                 "values": rounded([said for _, said, _ in said_vs_actual])},
                {"name": "本季实际", "color": "NAVY",
                 "values": rounded([actual for _, _, actual in said_vs_actual])},
            ],
            "bar_labels": True,
            "fmt": "pp1", "label_fmt": "pp1", "yfmt": "pp1",
            "ylab": "百分点",
            "note": ("四条里三条落地：中东拖累与上季所述同为 −1pp（持续时间更长，季末「much more muted」），"
                     "汇率对上半年利润率的拖累实际约 −70bp、比所述的 −80bp 好 10 个基点，"
                     "时装与皮具从「大致持平」的锚点走到 " + signed(flg_q2, 0) + "。"
                     "<b>第四条要单独读。</b>上季管理层说「需要 3–4% 的有机增长才能稳住利润率」，"
                     "紧接着补了一句「we could maybe do it with a bit less」。"
                     "本半年有机增长 +2%，利润率稳住了 —— <b>兑现的是那句补充，不是那条线</b>。"
                     "而本季电话会上同一个 3–4% 换了说法：不再是「稳住利润率」的门槛，"
                     "而是「开始获得经营杠杆」的门槛，并被明确声明「it doesn't make it a rule」。"
                     "第五条（DFS 对精品零售的分季度并表影响）公司只在集团口径上给了数，"
                     "分部的分季度并表影响它从不披露，本页记为无法在原口径上核。"),
            "src_extra": SOURCE_CALL,
        },
    ]


# ── section two: the quarter ─────────────────────────────────────────────────
def quarter_charts(staging: dict, der: dict, labels: list[str]) -> list[dict]:
    rev = staging["quarterly_revenue_eur_m"]
    long_q = staging["long_quarters"]
    start = long_q.index(staging["quarters"][0])
    window_rev = {k: v[start:] for k, v in rev.items()}
    org = der["organic"]

    rep_q1, rep_q2 = der["reported_yoy"][-2], der["reported_yoy"][-1]
    gap_q1, gap_q2 = der["gap"][-2], der["gap"][-1]
    org_step = org["total"][-1] - org["total"][-2]
    rep_step = rep_q2 - rep_q1
    gap_step = gap_q1 - gap_q2
    # The perimeter leg is the only piece of the gap the company splits out by
    # quarter (group level, second quarter); the currency leg is the remainder.
    perimeter_step = -1.0
    currency_step = gap_step - perimeter_step

    hpro = staging["half_pro_eur_m"]
    halves = staging["halves"]
    i_now, i_prior = halves.index("H1 2026"), halves.index("H1 2025")
    legs = [(d, hpro[d][i_now] - hpro[d][i_prior]) for d in DIVS]
    other_leg = (hpro["total"][i_now] - hpro["total"][i_prior]
                 - sum(delta for _, delta in legs))

    return [
        {
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
            "yoy": {"name": "报告口径同比 (RHS)", "values": rounded(der["reported_yoy"]),
                    "color": "RED", "yfmt": "pct0"},
            "note": ("<b>报告口径的收入八季里第一次不再下滑</b>：本季 " + signed(rep_q2) +
                     "，上季 " + signed(rep_q1) + "。"
                     "但同期有机增速只从 " + signed(org["total"][-2], 0) + " 走到 " +
                     signed(org["total"][-1], 0) + "。两条线之间的差是汇率加并表，"
                     f"它从上季的 {gap_q1:.2f}pp 收窄到本季的 {gap_q2:.2f}pp —— "
                     "见下一张。"),
            "src_extra": SOURCE_QUARTER,
        },
        {
            "ref": "EX_BRIDGE_REV",
            "kind": "bridge_bar",
            "title": (f"报告口径同比改善了 {rep_step:.2f}pp，其中 {gap_step:.2f}pp 不是需求"),
            "xlabels": ["Q1 2026 报告同比", "有机增速变动", "并表影响变动", "汇率影响变动 D",
                        "Q2 2026 报告同比"],
            "stacks": [{"name": "环比拆解（pp）", "color": "NAVY",
                        "values": rounded([rep_q1, org_step, perimeter_step, currency_step, None])}],
            "net": {"name": "Q2 2026 报告口径同比", "values": [None, None, None, None, round(rep_q2, 6)]},
            "fmt": "pp1", "yfmt": "pp1", "label_fmt": "pp1",
            "ylab": "百分点",
            "note": ("<b>本季报表上最大的一笔改善来自汇率，不是来自需求。</b>"
                     f"报告口径同比从 {signed(rep_q1)} 走到 {signed(rep_q2)}，改善 {rep_step:.2f}pp；"
                     f"其中有机增速只贡献 {org_step:+.2f}pp，剩下的 {gap_step:.2f}pp 来自"
                     f"汇率与并表这条线 —— 占改善幅度的 {gap_step / rep_step * 100:.0f}%。"
                     "并表那一腿取公司在本季电话会上给的集团口径 −1pp（DFS 大中华处置），"
                     "汇率腿是残值，标 D：<b>公司按季只给有机增速，不给分季度的汇率与并表拆分</b>，"
                     "半年度口径它给的是「有机 +2%、并表 −1%、汇率 −5%」，"
                     "而这三个取整后的数相加是 −4%，公司自己印的报告口径合计是 −3% —— "
                     "本页因此不把公司印的三个整数当成一个能闭合的等式来用。"),
            "src_extra": SOURCE_QUARTER + " 集团口径的并表影响取自 2026-07-27 电话会。",
        },
        {
            "ref": "EX_GAPS",
            "kind": "grouped_bars",
            "title": "八季里报告口径与有机口径的两条增速：差额就是汇率加并表",
            "xlabels": labels,
            "groups": [
                {"name": "报告口径同比", "color": "RED", "values": rounded(der["reported_yoy"])},
                {"name": "有机增速", "color": "NAVY", "values": rounded(org["total"])},
            ],
            "bar_labels": True,
            "fmt": "pct1", "label_fmt": "pct0", "yfmt": "pct0",
            "ylab": "同比",
            "note": ("两条线之差在 2025Q1 还是负的（汇率是顺风），此后一路扩大到 2026Q1 的 "
                     f"{der['gap'][-2]:.2f}pp，本季骤缩到 {der['gap'][-1]:.2f}pp。"
                     "<b>这条差额过去六个季度的振幅比有机增速本身还大</b>："
                     f"有机增速八季在 {min(org['total']):.0f}% 到 {max(org['total']):.0f}% 之间，"
                     f"差额在 {min(der['gap']):.1f}pp 到 {max(der['gap']):.1f}pp 之间。"
                     "读这家公司的报表增速，先看这条差额。"),
            "src_extra": SOURCE_QUARTER,
        },
        {
            "ref": "EX_MIX",
            "kind": "stacked_dual",
            "title": (f"分部收入结构：时装与皮具占 {der['flg_share'][-1]:.1f}%，"
                      f"八季前是 {der['flg_share'][0]:.1f}%"),
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
                     "values": rounded(der["flg_share"]), "yfmt": "pct1", "ymax": 100},
            "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
            "ylab": "€M", "ylab2": "时装与皮具占比",
            "note": ("时装与皮具仍是集团近一半的收入，但它的占比八季里降了 "
                     f"{der['flg_share'][0] - der['flg_share'][-1]:.1f}pp，"
                     "而手表与珠宝从 " +
                     f"{window_rev['watches_jewelry'][0] / window_rev['total'][0] * 100:.1f}% 升到 "
                     f"{window_rev['watches_jewelry'][-1] / window_rev['total'][-1] * 100:.1f}%。"
                     "「其他与抵销」一行按「集团合计减五个分部」取残值以让堆叠闭合，"
                     "与公司自己印的那个数在八季里有两季差 €1M，逐季列在核对表里。"),
            "src_extra": SOURCE_QUARTER,
        },
        {
            "ref": "EX_DIVORG",
            "kind": "lines_endlabels",
            "title": "五个分部的有机增速：本季分化到 12 个百分点宽",
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
            "note": ("<b>时装与皮具本季 " + signed(org["fashion_leather"][-1], 0) +
                     "，是 2024Q3 以来七个非正季度之后的第一个正数。</b>"
                     "同一节里手表与珠宝 " + signed(org["watches_jewelry"][-1], 0) +
                     "、香水与化妆品 " + signed(org["perfumes_cosmetics"][-1], 0) +
                     "，两端相差 " +
                     f"{max(org[d][-1] for d in DIVS) - min(org[d][-1] for d in DIVS):.0f} 个百分点。"
                     "公司在电话会上说手表与珠宝的加速来自 Tiffany 与 Bvlgari 双双 mid-teens 增长，"
                     "而香水与化妆品的平淡是主动选择的结果：「we have made a choice … "
                     "to be very selective in distribution」。"),
            "src_extra": SOURCE_QUARTER,
        },
        {
            "ref": "EX_BRIDGE_PRO",
            "kind": "bridge_bar",
            "title": (f"半年经营利润 €{hpro['total'][i_prior]:,.0f}M → €{hpro['total'][i_now]:,.0f}M："
                      f"时装与皮具一个分部就拿走 €{-legs[1][1]:,.0f}M"),
            "xlabels": ["H1 2025 经营利润"] + [
                {"wines_spirits": "葡萄酒与烈酒", "fashion_leather": "时装与皮具",
                 "perfumes_cosmetics": "香水与化妆品", "watches_jewelry": "手表与珠宝",
                 "selective_retailing": "精品零售"}[d] for d, _ in legs
            ] + ["其他、抵销与舍入 D", "H1 2026 经营利润"],
            "stacks": [{"name": "分部贡献（€M）", "color": "NAVY",
                        "values": rounded([hpro["total"][i_prior]]
                                          + [delta for _, delta in legs]
                                          + [other_leg, None], 0)}],
            "net": {"name": "H1 2026 经营利润（净额）",
                    "values": [None] * 7 + [round(float(hpro["total"][i_now]), 6)]},
            "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
            "ylab": "€M（半年）",
            "note": ("<b>这是半年图，不是季度图 —— 公司不按季披露分部利润。</b>"
                     f"集团经营利润同比 −€{hpro['total'][i_prior] - hpro['total'][i_now]:,.0f}M，"
                     f"其中时装与皮具一个分部 −€{-legs[1][1]:,.0f}M，"
                     "而公司称该分部的下滑「entirely driven by currencies」、恒定汇率下利润率还略有改善。"
                     f"另外四个分部合计 {sum(d for k, d in legs if k != 'fashion_leather'):+,.0f}，"
                     "其中手表与珠宝与葡萄酒与烈酒各贡献了正的双位数百万欧元。"
                     "末腿含公司印的集团合计与五个分部相加之间 €1M 的取整差（分部相加为 "
                     f"€{sum(staging['half_pro_eur_m'][d][i_now] for d in DIVS) + staging['half_pro_eur_m']['other'][i_now]:,.0f}M，"
                     f"公司印的是 €{staging['half_pro_published_total_eur_m']['H1 2026']:,.0f}M）。"),
            "src_extra": SOURCE_HALF,
        },
    ]


# ── section three: what only the half-year shows ─────────────────────────────
def half_charts(staging: dict, der: dict) -> list[dict]:
    halves = staging["halves"]
    hrev = staging["half_revenue_eur_m"]
    hpro = staging["half_pro_eur_m"]
    cash_halves = staging["cash_halves"]
    cash = staging["half_cash_eur_m"]
    pairs = der["half_pairs"]
    stores = staging["stores"]
    store_labels = [d[:7].replace("-", " 年 ") + " 月" for d in staging["store_dates"]]

    # Year on year, so the same span the sentence claims: the series is
    # semi-annual, which puts twelve months ago at index -3, not at index 0.
    year_ago = -3
    # -1 is this half, -3 is the same half a year ago.
    improved = sum(1 for d in DIVS
                   if der["div_half_margin"][d][-1] > der["div_half_margin"][d][-3])

    asia_drop = stores["asia_ex_japan"][year_ago] - stores["asia_ex_japan"][-1]
    total_drop = stores["total"][year_ago] - stores["total"][-1]

    return [
        {
            "ref": "EX_SEASON",
            "kind": "bar_line_dual",
            "title": (f"三个完整年度里，下半年每一次都是收入更高、利润率更低 "
                      f"（{der['h2_bigger']}/{len(pairs)} 与 {der['h2_thinner']}/{len(pairs)}）"),
            "xlabels": halves,
            "bar": {"name": "半年收入", "values": rounded(hrev["total"], 0), "color": "NAVY"},
            "line": {"name": "半年经营利润率 (RHS)", "values": rounded(der["half_margin"]),
                     "color": "RED", "yfmt": "pct1"},
            "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
            "ylab": "€M（半年）", "ylab2": "半年经营利润率",
            "note": ("<b>本页最该被记住的一张，也是只有半年度披露才画得出来的一张。</b>"
                     + "；".join(f"{p['year']} 年下半年收入比上半年多 "
                                 f"€{p['rev_h2'] - p['rev_h1']:,.0f}M，利润率低 "
                                 f"{p['margin_h1'] - p['margin_h2']:.2f}pp"
                                 for p in pairs)
                     + "。三年三次，方向没有例外：<b>季节性更大的那半年，利润率反而更薄</b>。"
                     f"所以本半年的 {der['half_margin'][-1]:.2f}% 不是全年运行率 —— "
                     f"上一整年的全年数是 "
                     f"{(hpro['total'][-2] + hpro['total'][-3]) / (hrev['total'][-2] + hrev['total'][-3]) * 100:.1f}%，"
                     "而那一年的上半年是 "
                     f"{der['half_margin'][-3]:.2f}%。把上半年利润率年化，这家公司三年会错三次。"),
            "src_extra": SOURCE_HALF,
        },
        {
            "ref": "EX_DIVMARGIN",
            "kind": "grouped_bars",
            "title": (f"分部半年经营利润率：本半年五个分部里 {improved} 个同比走高，"
                      f"{len(DIVS) - improved} 个走低"),
            "xlabels": halves[-4:],
            "groups": [
                {"name": "时装与皮具", "color": "NAVY",
                 "values": rounded(der["div_half_margin"]["fashion_leather"][-4:])},
                {"name": "葡萄酒与烈酒", "color": "GOLD",
                 "values": rounded(der["div_half_margin"]["wines_spirits"][-4:])},
                {"name": "手表与珠宝", "color": "BLUE",
                 "values": rounded(der["div_half_margin"]["watches_jewelry"][-4:])},
                {"name": "精品零售", "color": "MBLUE",
                 "values": rounded(der["div_half_margin"]["selective_retailing"][-4:])},
                {"name": "香水与化妆品", "color": "GREEN",
                 "values": rounded(der["div_half_margin"]["perfumes_cosmetics"][-4:])},
            ],
            "bar_labels": True,
            "fmt": "pct1", "label_fmt": "pct0", "yfmt": "pct0",
            "ylab": "半年经营利润率",
            "note": ("这四个半年正好覆盖本页的八个季度 —— <b>同样的时间，只有四个利润读数</b>。"
                     f"时装与皮具 {der['div_half_margin']['fashion_leather'][-1]:.1f}%（同比 "
                     f"{der['div_half_margin']['fashion_leather'][-1] - der['div_half_margin']['fashion_leather'][-3]:+.1f}pp），"
                     f"葡萄酒与烈酒 {der['div_half_margin']['wines_spirits'][-1]:.1f}%（"
                     f"{der['div_half_margin']['wines_spirits'][-1] - der['div_half_margin']['wines_spirits'][-3]:+.1f}pp）"
                     "是本半年最大的一笔改善。"
                     "各分部利润率同时呈现下半年更薄的同一节奏，香水与化妆品尤其极端："
                     f"H2 2025 只有 {der['div_half_margin']['perfumes_cosmetics'][-2]:.1f}%，"
                     f"H1 2026 是 {der['div_half_margin']['perfumes_cosmetics'][-1]:.1f}%。"
                     "本页图上的利润率按「分部经营利润 ÷ 分部收入」重算，"
                     "与公司自己印的百分数最大差 0.05pp，两套数并列在核对表里。"),
            "src_extra": SOURCE_HALF,
        },
        {
            "ref": "EX_CASH",
            "kind": "bar_line_dual",
            "title": (f"半年经营自由现金流 €{cash['ofcf'][-1]:,.0f}M，"
                      f"而净金融负债在每年 6 月都比前一个 12 月高"),
            "xlabels": cash_halves,
            "bar": {"name": "半年经营自由现金流", "values": rounded(cash["ofcf"], 0), "color": "NAVY"},
            "line": {"name": "期末净金融负债 (RHS)", "color": "RED",
                     "values": rounded(staging["net_financial_debt_eur_m"], 0), "yfmt": "f0c"},
            "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
            "ylab": "€M（半年）", "ylab2": "期末净金融负债",
            "note": ("现金流的季节性和利润率正好相反：<b>下半年的自由现金流大约是上半年的两倍</b>"
                     f"（H2 2025 €{cash['ofcf'][3]:,.0f}M 对 H1 2025 €{cash['ofcf'][2]:,.0f}M；"
                     f"H2 2024 €{cash['ofcf'][1]:,.0f}M 对 H1 2024 €{cash['ofcf'][0]:,.0f}M）。"
                     "净负债因此每年 6 月抬头、12 月回落，两个观测年都是这个形状 —— "
                     "主股息在上半年支付，营运资金也在上半年占用。"
                     f"本期末净负债 €{staging['net_financial_debt_eur_m'][-1]:,.0f}M，"
                     f"较去年同期少 €{staging['net_financial_debt_eur_m'][2] - staging['net_financial_debt_eur_m'][-1]:,.0f}M，"
                     f"净负债对权益 {staging['net_financial_debt_eur_m'][-1] / staging['equity_eur_m'][-1] * 100:.1f}%。"),
            "src_extra": SOURCE_HALF,
        },
        {
            "ref": "EX_STORES",
            "kind": "lines_endlabels",
            "title": (f"门店网络：亚洲（除日本）一年少了 {asia_drop} 家，同期集团总数只少了 {total_drop} 家"),
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
            "note": ("<b>店数只在半年度和全年披露，一年只有两个读数。</b>"
                     f"亚洲（除日本）从 {stores['asia_ex_japan'][year_ago]:,} 家降到 "
                     f"{stores['asia_ex_japan'][-1]:,} 家"
                     f"（{-asia_drop / stores['asia_ex_japan'][year_ago] * 100:.1f}%），"
                     "其中包含 DFS 大中华业务的处置，所以这不是一次纯粹的自主收缩；"
                     "公司未披露处置本身带走了多少家店，本页也不估算。"
                     f"同期美国 {stores['united_states'][year_ago]:,} → "
                     f"{stores['united_states'][-1]:,} 家、其他市场（含中东）"
                     f"{stores['other_markets'][year_ago]:,} → {stores['other_markets'][-1]:,} 家，"
                     "两个区域都在开店。而亚洲（除日本）本半年的有机收入增速是 "
                     f"{staging['region_organic_pct']['asia_ex_japan'][-1]:+d}%（本季）—— "
                     "<b>收入在涨，店在减</b>。"),
            "src_extra": SOURCE_HALF,
        },
        {
            "ref": "EX_REGION",
            "kind": "grouped_bars",
            "title": "分地区有机增速：公司只把两年的 Q1 与 Q2 排在一张表里",
            "xlabels": [compact_quarter(q) for q in staging["region_quarters"]],
            "groups": [
                {"name": "美国", "color": "NAVY",
                 "values": rounded(staging["region_organic_pct"]["united_states"])},
                {"name": "亚洲（除日本）", "color": "BLUE",
                 "values": rounded(staging["region_organic_pct"]["asia_ex_japan"])},
                {"name": "日本", "color": "GOLD",
                 "values": rounded(staging["region_organic_pct"]["japan"])},
                {"name": "欧洲", "color": "GREEN",
                 "values": rounded(staging["region_organic_pct"]["europe"])},
            ],
            "bar_labels": True,
            "fmt": "pct0", "label_fmt": "pct0", "yfmt": "pct0",
            "ylab": "有机增速",
            "note": ("这张图只有四根 x 轴，不是八根：<b>公司在半年报的附录里只表格化两年的 Q1 与 Q2</b>，"
                     "第三、四季度的分地区有机增速只出现在全年演示材料的柱状图里、没有对应的数字表，"
                     "本页因此不予收录，而不是从图上目测。"
                     f"本季日本 {staging['region_organic_pct']['japan'][-1]:+d}% 是四个区域里最高的，"
                     f"去年同期是 {staging['region_organic_pct']['japan'][1]:+d}% —— "
                     "公司解释为亚洲客群把消费从亚洲搬到了日本与欧洲，"
                     "这同时解释了亚洲（除日本）从上季的 "
                     f"{staging['region_organic_pct']['asia_ex_japan'][-2]:+d}% 回落到 "
                     f"{staging['region_organic_pct']['asia_ex_japan'][-1]:+d}%。"),
            "src_extra": ("分地区有机增速取自 H1 2026 业绩演示材料附录"
                          "「Quarterly organic revenue change by region」。"),
        },
    ]


# ── section four: the routine series and the local thresholds ────────────────
def routine_charts(staging: dict, der: dict, labels: list[str]) -> list[dict]:
    cash_halves = staging["cash_halves"]
    cash = staging["half_cash_eur_m"]
    halves = staging["halves"]
    rev = staging["quarterly_revenue_eur_m"]
    long_q = staging["long_quarters"]
    split = staging["quarterly_wines_split_eur_m"]
    first = next(i for i, v in enumerate(split["champagne_wines"]) if v is not None)
    split_labels = [compact_quarter(q) for q in long_q[first:]]
    entries = staging["next_kpi"]["entries"]

    return [
        headroom_exhibit(
            "下季跟踪阈值：七条线里六条仍在安全侧",
            entries, "current",
            ("阈值是本地研究设定，不是公司指引 —— <b>LVMH 不提供任何数字指引</b>，"
             "所以这一节没有可以照抄的公司口径。正值代表仍在安全侧。"
             "集团季度有机增速恰好压在 3% 的线上，而这 3% 里有 1pp 被中东抵掉："
             "公司称剔除中东本季是 +4%。原始单位的阈值与当前值见核对表。"),
            "阈值与理由见核对表；当前值取自本页已列示的公司披露值与透明自算。",
        ),
        threshold_exhibit(
            "半年集团经营利润率对 FY2025 全年水平（22.0%）",
            halves, rounded(der["half_margin"]), 22.0,
            fmt="pct1", ylab="半年经营利润率",
            actual_name="半年经营利润率 D", threshold_name="FY2025 全年 22.0%",
            note=("七个半年里，本半年是 2024 年下半年以来第一次同时做到"
                  "「高于上年同期的下半年」与「高于上一整年」。"
                  "但注意这条阈值线本身的性质：<b>上半年高于全年是这家公司的常态</b>"
                  "（见 {EX_SEASON}），所以站在这条线之上不是新信息，"
                  "跌破它才是。"),
            src_extra=SOURCE_HALF,
        ),
        {
            "ref": "EX_CAPEX",
            "kind": "bar_line_dual",
            "title": (f"半年经营性投资 €{cash['capex'][-1]:,.0f}M，占半年收入 "
                      f"{der['capex_intensity'][-1]:.1f}%"),
            "xlabels": cash_halves,
            "bar": {"name": "半年经营性投资", "values": rounded(cash["capex"], 0), "color": "NAVY"},
            "line": {"name": "占半年收入 (RHS)", "values": rounded(der["capex_intensity"]),
                     "color": "RED", "yfmt": "pct1"},
            "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
            "ylab": "€M（半年）", "ylab2": "占半年收入",
            "note": ("资本强度五个半年连续下降："
                     f"从 {der['capex_intensity'][0]:.1f}% 降到 {der['capex_intensity'][-1]:.1f}%，"
                     f"绝对额从 €{cash['capex'][0]:,.0f}M 降到 €{cash['capex'][-1]:,.0f}M。"
                     "公司在电话会上没有把这解释成收缩，而是解释成纪律；"
                     "但它和门店数同期净减少是同一个方向的两个读数，"
                     "而管理层同时表示 Tiffany 的门店翻新节奏不变（「10% or more per year」）。"
                     "经营性投资是公司自己的口径，含门店、生产与物业，不等于会计上的购置固定资产。"),
            "src_extra": SOURCE_HALF,
        },
        {
            "ref": "EX_WS_SPLIT",
            "kind": "lines_endlabels",
            "title": "葡萄酒与烈酒的两条腿：香槟与葡萄酒在恢复，干邑与烈酒还没有",
            "xlabels": split_labels,
            "series": [
                {"name": "香槟与葡萄酒", "values": rounded(split["champagne_wines"][first:], 0),
                 "color": "GOLD"},
                {"name": "干邑与烈酒", "values": rounded(split["cognac_spirits"][first:], 0),
                 "color": "NAVY"},
            ],
            "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
            "end_label": True,
            "ylab": "€M",
            "note": ("公司只在这一个分部之下再拆两行，且只从 2024 年起提供。"
                     "本半年香槟与葡萄酒有机 +7%、干邑与烈酒有机 +3%（公司口径），"
                     "而干邑与烈酒的绝对额十个季度里仍未回到 2024Q1 的 "
                     f"€{split['cognac_spirits'][first]:,.0f}M。"
                     "公司称美国干邑需求仍软、出货仍为负，是中国的 VSOP 与 X.O 把它拉回增长，"
                     "并强调「it's not sell-in … the stocks are much healthier than they used to be」。"
                     "这条线是本页判断上季那句「Q2 不会重复 Q1」为什么落空的主要证据。"),
            "src_extra": SOURCE_QUARTER,
        },
    ]



# ── the long record ─────────────────────────────────────────────────────────
def long_charts(staging: dict) -> list[dict]:
    """The 42-quarter revenue record, added once the series reached 2016Q1.

    LVMH stopped filing with the SEC in 2004, and this page was built on the
    eight quarters its own releases carry as a current window. But the company
    reprints all four quarters of the current AND prior year in every full-year
    press-release appendix, so nine of those releases stitch into a continuous,
    self-overlapping 2016-2025 series -- a research-effort floor, not a
    disclosure one. The eight-quarter section above is untouched; its prose is
    written about eight quarters and stays that way.
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

def build_payload(staging: dict) -> dict:
    labels = [compact_quarter(q) for q in staging["quarters"]]
    der = derived(staging)
    long_ex = long_charts(staging)
    rev = staging["quarterly_revenue_eur_m"]
    long_q = staging["long_quarters"]
    start = long_q.index(staging["quarters"][0])
    halves = staging["halves"]
    hrev = staging["half_revenue_eur_m"]
    hpro = staging["half_pro_eur_m"]
    cash = staging["half_cash_eur_m"]
    org = der["organic"]

    said_ex = said_charts(staging, der, labels)
    quarter_ex = quarter_charts(staging, der, labels)
    half_ex = half_charts(staging, der)
    routine_ex = routine_charts(staging, der, labels)
    exhibits = number_exhibits(said_ex + quarter_ex + half_ex + long_ex + routine_ex)

    # ── audit tables ─────────────────────────────────────────────────────────
    rev_rows = [
        [staging["quarters"][i]]
        + [f"{rev[d][start + i]:,}" for d in DIVS]
        + [f"{der['other'][start + i]:,}",
           f"{staging['quarterly_revenue_other_published_eur_m'][start + i]:,}",
           f"{der['other'][start + i] - staging['quarterly_revenue_other_published_eur_m'][start + i]:+,}",
           f"{rev['total'][start + i]:,}"]
        for i in range(len(staging["quarters"]))
    ]
    growth_rows = [
        [staging["quarters"][i]]
        + [f"{org[d][i]:+d}%" for d in DIVS]
        + [f"{org['total'][i]:+d}%", f"{der['reported_yoy'][i]:+.2f}%", f"{der['gap'][i]:+.2f}pp"]
        for i in range(len(staging["quarters"]))
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
        [staging["store_dates"][i]]
        + [f"{staging['stores'][k][i]:,}" for k in
           ("france", "europe_ex_fr", "united_states", "japan", "asia_ex_japan",
            "other_markets", "total")]
        for i in range(len(staging["store_dates"]))
    ]
    VERDICTS = {"met": "兑现", "beat": "兑现且好于所述", "missed": "未兑现",
                "caveat_held": "兑现在它自己预留的余地里", "unverifiable": "无法在原口径上核"}
    said_rows = [
        [item["topic"], item["said"], item["said_zh"], item["outcome_zh"], VERDICTS[item["verdict"]]]
        for item in staging["call_record"]["items"]
    ]
    forward_rows = [[item["topic"], item["said"], item["quantified"]]
                    for item in staging["forward_statements"]["items"]]

    entries = staging["next_kpi"]["entries"]
    kpi = threshold_table(9, "下季跟踪阈值与当前值（原始单位）", entries, "current", "本季值")
    kpi["headers"] = kpi["headers"] + ["为什么是这条线"]
    kpi["rows"] = [row + [entry["why"]] for row, entry in zip(kpi["rows"], entries)]

    div_headers = ["葡萄酒与烈酒", "时装与皮具", "香水与化妆品", "手表与珠宝", "精品零售"]
    tables = [
        {"n": 1, "title": "八季分部收入（€M）与「其他与抵销」两种取法的差",
         "headers": ["期间"] + div_headers
                    + ["其他与抵销 D", "公司印的其他与抵销", "差 D", "集团合计"],
         "rows": rev_rows},
        {"n": 2, "title": "八季有机增速（公司披露）与报告口径同比（本页自算）",
         "headers": ["期间"] + div_headers + ["集团有机", "集团报告口径 D", "两者之差 D"],
         "rows": growth_rows},
        {"n": 3, "title": "七个半年的分部经营利润（€M）；H2 各行为「全年减上半年」",
         "headers": ["半年"] + div_headers
                    + ["其他与抵销", "集团合计", "经营利润率 D", "公司印的利润率"],
         "rows": pro_rows},
        {"n": 4, "title": "七个半年的分部经营利润率（本页按分部利润 ÷ 分部收入重算）",
         "headers": ["半年"] + div_headers,
         "rows": margin_rows},
        {"n": 5, "title": "五个半年的现金流、资本强度与期末资产负债（€M）",
         "headers": ["半年", "经营现金流", "经营性投资", "租赁负债偿还", "经营自由现金流",
                     "投资占收入 D", "期末净金融负债", "期末权益"],
         "rows": cash_rows},
        {"n": 6, "title": "四个时点的门店数（只在半年度与全年披露）",
         "headers": ["日期", "法国", "欧洲（除法国）", "美国", "日本", "亚洲（除日本）",
                     "其他市场", "合计"],
         "rows": store_rows},
        {"n": 7, "title": "上季电话会的六条前瞻陈述，逐条结算",
         "headers": ["主题", "原话（英文照抄）", "中文转述", "本季实际", "判词"],
         "rows": said_rows},
        {"n": 8, "title": "本季电话会给出的全部前瞻（原话）",
         "headers": ["主题", "原话（英文照抄）", "可数字化的部分"],
         "rows": forward_rows},
        kpi,
        ai_capex_cycle_table(10),
    ]
    resolve_exhibit_refs(exhibits)
    for table in tables:
        table["title"] = table["title"].replace("{TBL_SAID}", "7")
    for exhibit in exhibits:
        for key in ("note", "src_extra", "title"):
            if exhibit.get(key):
                exhibit[key] = exhibit[key].replace("{TBL_SAID}", "7")

    i_now, i_prior = halves.index("H1 2026"), halves.index("H1 2025")
    rep_step = der["reported_yoy"][-1] - der["reported_yoy"][-2]
    gap_step = der["gap"][-2] - der["gap"][-1]

    return {
        "schema_version": "quarterly-dashboard/mc-v1",
        "page": {"slug": "mc", "language": "zh-CN"},
        "company": {
            "ticker": "MC.PA",
            "name": "LVMH Moët Hennessy Louis Vuitton SE",
            "group": "luxury_brands",
            "accounting_standard": "IFRS",
        },
        "latest": {
            "disclosed_period_label": "Q2 2026",
            "full_financial_period_label": "H1 2026",
            "period_end": "2026-06-30",
            "release_date": "2026-07-27",
            "analysis_date": "2026-08-30",
            "audit_status": "limited_review_pending",
            "status": "history_ready",
        },
        "tracker": "Watchlist Quarterly Tracker · MC.PA",
        "title": "LVMH（MC.PA）：Q2 2026 / H1 2026 季报仪表盘",
        "subtitle": (
            "截至 2026-06-30 · 发布 2026-07-27 · IFRS 合并 · 有限审阅报告尚未出具 · "
            "全部以欧元列示 · 收入按季披露，利润只有半年度"
        ),
        "headline": (
            f"半年收入 €{hrev['total'][i_now] / 1000:.1f}B（报告口径 "
            f"{pct_change(hrev['total'][i_now], hrev['total'][i_prior]):+.0f}%、有机 +2%），"
            f"经营利润 €{hpro['total'][i_now]:,}M、利润率 {der['half_margin'][i_now]:.2f}%；"
            f"本季报告口径同比 {signed(der['reported_yoy'][-1])}，比上季改善 {rep_step:.2f}pp，"
            f"其中 {gap_step / rep_step * 100:.0f}% 来自汇率与并表而不是需求 —— "
            f"而这一半年最重要的数字（利润率）在四月那次收入公告里根本不存在。"
        ),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>结构</span><b>一年发四次收入，只发两次利润</b>'
            f'<p>八个季度里没有一个季度有属于它自己的分部利润数。本页收入按季、'
            f'利润按半年，两条 x 轴各自独立。</p></article>'
            '<article><span>算术</span><b>报表上的好转有三分之二不是需求</b>'
            f'<p>报告口径同比改善 {rep_step:.2f}pp，有机增速只贡献 '
            f'{org["total"][-1] - org["total"][-2]:+.0f}pp，其余来自汇率与并表。</p></article>'
            '<article><span>兑现</span><b>说得最硬的那一条错了</b>'
            '<p>上季管理层说葡萄酒与烈酒的 Q1 相位利好「不会重复」；本季该分部又是 +5%，'
            '且公司自己把它归因于销量。</p></article>'
            '</div>'
        ),
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
        "sections": [
            {
                "id": "settled",
                "title": "一、公司给的是句子，不是数字 —— 上季那些话结算了没有",
                "description": (
                    "LVMH 不发布收入、利润或利润率的任何数字指引，所以这一节不是常规的指引兑现，"
                    "而是对电话会陈述的逐条结算：六条前瞻陈述，2026-04-13 说出，2026-07-27 结清。"
                ),
                "exhibits": said_ex,
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点：报表上的好转，有多少来自需求",
                "description": (
                    "季度口径能看的只有收入。这一节拆报告增速与有机增速之间那条差，"
                    "看分部结构与分化，最后用半年图给出唯一存在的利润拆解。"
                ),
                "exhibits": quarter_ex,
            },
            {
                "id": "half_year",
                "title": "三、只有半年度披露才看得见的",
                "description": (
                    "利润率、现金流、净负债与门店数一年只有两个读数。"
                    "本节所有图的 x 轴都是半年，不是季度。"
                ),
                "exhibits": half_ex,
            },
            {
                "id": "long_record",
                "title": "四、四十二季的长期记录",
                "description": (
                    "季度收入与有机增速回到 2016Q1。LVMH 不向 SEC 申报，但它每年的全年"
                    "新闻稿附表里同时重印当年与上年全部四个季度 —— 九份发布就拼出完整序列，"
                    "且相邻两份互相重叠、可逐格核对。这一节只画能连续读的三张。"
                ),
                "exhibits": long_ex,
            },
            {
                "id": "routine",
                "title": "四、下季跟踪与长期常规",
                "description": (
                    "阈值为本地研究设定，不是公司指引；再加资本强度与葡萄酒与烈酒的两条腿。"
                ),
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": [
            "本页按「上季兑现 → 本季重点 → 半年度独有 → 下季跟踪与常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "LVMH 一年发四次收入、只发两次利润。第一与第三季度只发收入公告，正文里没有任何利润行；损益表、分部经营利润、汇率与并表对利润的影响、现金流量表、资产负债表、分地区收入与门店数只在半年度和全年披露。本页八个季度里没有任何一个季度有属于它自己的分部利润数，所以收入按季度轴、利润按半年轴，两条轴各自独立，本页不做任何按季摊平或插值。",
            "LVMH 已不是 SEC 报告发行人。CIK 0000824046 名下只有两份 20-F（2002-07-01 报 FY2001、2003-06-30 报 FY2002，另有一份 20-F/A）与七份 6-K（2002-02-12 至 2004-03-17）；2004-03-08 报 Form 15-15D 中止申报义务，2009-07-31 报 Form 15F-15D 终止注册。此后该 CIK 下只剩 ADR 存托登记用的 F-6EF / F-6 POS（最新一份 2022-01-24）与两份 SC 13D。本页因此没有任何 EDGAR 来源，全部数据取自公司自己发布的文件。",
            "全页以欧元列示，不折算美元。公司本身不发布美元财务数字，折算会在页面上制造一个任何披露里都不存在的数；而本半年欧元对美元、日元与韩元的升值正是本页要读的那条汇率腿，折算会把它抹掉。",
            "H2 各行由「全年减上半年」得出并标 D。这与公司自己在全年演示材料附录里印的 H2 行偶有 ±1 百万欧元的差，因为公司按未取整数字计算；本页统一用「全年减上半年」，不混用两种口径。",
            "季度的「其他业务与抵销」按「公司印的集团合计减五个分部」取残值，以让堆叠图闭合到公司印的合计。它与公司自己印的那一行在八个季度里有两季差 1 百万欧元，两个数并列在核对表第 1 张里。",
            "H1 2026 五个分部的经营利润加上「其他与抵销」是 8,690 百万欧元，而公司印的集团合计是 8,691，本页在利润桥的末腿里显式带上这 1 百万欧元的取整差，不把它藏进任何一个分部。",
            "分部经营利润率按「分部经营利润 ÷ 分部收入」重算，与公司自己印的百分数最大差 0.05 个百分点（香水与化妆品：本页 10.65%，公司印 10.6%）。两套数并列在核对表第 3、第 4 张里，本页图上用重算值，因为只有它在七个半年上口径一致。",
            "季度的汇率与并表拆分公司不披露：它按季只给有机增速，报告口径同比是本页自算，两者之差因此是一个残值，标 D。半年度口径公司给的是「有机 +2%、并表 −1%、汇率 −5%」，而这三个取整后的整数相加是 −4%，公司自己印的报告口径合计是 −3%；本页因此不把这三个整数当成一个能闭合的等式来用，也不据此反推任何一条腿。",
            "分部有机增速里，公司在部分季度印的是「−0%」与「+0%」而不是「0%」，本页在序列里一律记为 0，原样印法保留在核对表里。",
            "分地区有机增速只收录四个季度。公司在半年报附录里只把两年的 Q1 与 Q2 排成表格，第三、四季度的分地区数字只出现在全年演示材料的柱状图上、没有对应的数字表，本页不从图上目测取数。",
            "门店数的口径是期末自营门店数（含电商），公司口径。亚洲（除日本）一年净减 159 家里包含 DFS 大中华业务的处置，公司未披露处置本身带走了多少家店，本页也不估算。",
            "第四节的阈值是本地研究设定，不是公司指引，也不构成评级或投资建议；「距阈值余量」统一为正值代表安全侧。",
            "本页只发布公司披露值与可复算的简单派生值；D 标记代表 Derived / 自算。市面上流传的单品牌收入（Louis Vuitton、Christian Dior、Tiffany 的绝对额）均为卖方估计，公司从不披露，本页不予采用。",
            "本页已知未接入：任何单一品牌的收入或利润（公司只披露五个分部）、分部的分季度利润、分季度的汇率与并表拆分、分部的分地区拆分、价格与销量的分解（公司只在电话会上给过定性数字）、以及 2023 年之前的历史。",
            "电话会记录仅作引用来源，公开仓不复制原件或逐字全文；页面内引用的英文原话为逐字短句引用。",
        ],
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
