"""Ermenegildo Zegna N.V. quarterly dashboard.

Zegna is a Dutch-incorporated Italian luxury group listed on the NYSE since
2021-12-17, reporting under IFRS in euro on a calendar fiscal year. It is a
foreign private issuer: the annual report is a 20-F and everything in between
is furnished on 6-K, so unlike the European filers elsewhere on this site its
entire record is on EDGAR. Twenty-seven earnings releases carry this page.

**Three structural facts shape every chart here.**

First, the cadence is unusual for a European luxury house: revenue is published
as a *discrete quarter* four times a year, with brand, channel, geography and
segment splits for that quarter alone, while a complete income statement
appears only twice. So the revenue axis is genuinely quarterly -- nothing on it
is a subtraction -- and the profit axis is genuinely half-yearly. The page never
mixes the two.

Second, the quarterly record starts at 2021Q1 and cannot start earlier. The
company published no quarterly figure before it listed, and each 2021 quarter
reaches this page as the prior-year column of a 2022 release. The F-4, the F-1
and the FY2021 20-F were read for this: they discuss quarters in prose and table
none.

Third, and this is what the audit drawer's census and restatement tables
record: the group total has never been restated, and four of the lines
underneath it have. Across the releases
this page reads, thirty-nine group-revenue readings were published and twenty-
four of them were published again later; not one came back different. Over the
same releases the `Other` product line changed eleven times, the Zegna segment
and the elimination line four each, and the old `Total Wholesale` five. Every
one of those changes reconciles exactly. Seven restatements sit behind them and
the company narrated two: the Tizeta segment move and the switch from a
by-nature income statement to a by-function one.

**The page is laid out in the site's four parts** -- what last quarter's local
analysis left to settle, this half's findings, what the current analysis asks
the next disclosures to settle, and the long-run record. The questions and
thresholds are the local analyses' (`followup_closure`, `prior_kpi_settlement`,
`next_kpi`, each stamped with the half it belongs to); every value they are
settled against is the company's own, read from the series or typed into the
stamped block with the filing it came from.

**A roll edits `series/zgn.json` and nothing else** (CLAUDE.md §9). Every period,
count and figure on the page is computed from the series; every sentence that
states something the data could stop saying is printed only while the data says
it. Published figures are company-reported or transparent arithmetic.
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
    cn_ordinal,
    display_period,
    headroom,
    headroom_exhibit,
    latest_block,
    minus_sign,
    number_exhibits,
    round_half_up,
    stamped_block,
    unit_text,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402

STAGING_PATH = ROOT / "series" / "zgn.json"
DATA_DIR = ROOT / "data"

SOURCE_RELEASES = ("每一格都取自公司自己的 6-K 新闻稿与半年报原件；"
                   "公司是美国证券法下的外国私人发行人，年度报告为 20-F，"
                   "期间披露一律以 6-K 报送，因此全部原件都在 EDGAR 上。")


# ── small helpers ────────────────────────────────────────────────────────────
def pct(current: float, base: float) -> float:
    return (current / base - 1) * 100.0


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return minus_sign(f"{value:+.{digits}f}{suffix}")


def num(value: float, digits: int = 1) -> str:
    return minus_sign(f"{value:.{digits}f}")


def rounded(values, digits: int = 6):
    return [None if v is None else round(v, digits) for v in values]


def eur_m(value: float, digits: int = 1) -> str:
    """Euro thousands as the millions the company's own prose uses.

    The sign goes outside the currency symbol -- "−€28.7M", not "€-28.7M" --
    which is the convention `board.UNIT_FORMATS` uses for every other currency
    on this site.
    """
    return f"{'−' if value < 0 else ''}€{abs(value) / 1000:,.{digits}f}M"


def cagr(start: float, end: float, years: float) -> float:
    return ((end / start) ** (1 / years) - 1) * 100.0


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
    """``2026H1`` -> ``2026 年上半年``."""
    return f"{label[:4]} 年{'上' if label.endswith('H1') else '下'}半年"


def quarter_cn(label: str) -> str:
    """``2026Q2`` -> ``2026 年第二季度``."""
    return f"{label[:4]} 年第{cn_ordinal(int(label[5]))}季度"


# ── what 「本期」 means on this page ──────────────────────────────────────────
def period_view(s: dict) -> dict:
    """The page reports the latest half, because that is the latest profit.

    The revenue series runs one or two quarters ahead of the income statement
    whenever a quarterly revenue release has landed and the half-year results
    have not. The page's period is the half: a profit figure is what the reader
    came for, and a quarter with revenue but no profit would put two different
    period labels on one page.
    """
    h = s["half"]
    q = s["quarterly"]
    half = next(p for p in reversed(h["periods"]) if h["profit"][h["periods"].index(p)] is not None)
    i = h["periods"].index(half)
    year = int(half[:4])
    prior = h["periods"].index(f"{year - 1}{half[4:]}")
    quarters = [p for p in q["periods"] if p[:4] == half[:4] and
                (int(p[5]) <= 2 if half.endswith("H1") else int(p[5]) >= 3)]
    return {
        "half": half, "year": year, "i": i, "prior": prior,
        "is_h1": half.endswith("H1"),
        "word": "上半年" if half.endswith("H1") else "下半年",
        "quarters": quarters,
        "latest_quarter": q["periods"][-1],
        "revenue": h["revenue"][i],
        "revenue_prior": h["revenue"][prior],
    }


def dtc_share(s: dict, i: int) -> float:
    ch = s["quarterly"]["channel"]
    return ch["dtc"][i] / (ch["dtc"][i] + ch["wholesale_branded"][i]) * 100.0


def half_sum(s: dict, path: list[str], half: str) -> float:
    """Sum a quarterly line over the two quarters of `half`."""
    q = s["quarterly"]
    node = q
    for key in path:
        node = node[key]
    wanted = (1, 2) if half.endswith("H1") else (3, 4)
    return sum(node[q["periods"].index(f"{half[:4]}Q{n}")] for n in wanted)


# ── section two (本季重点): the half just reported ──────────────────────────
def period_charts(s: dict, view: dict, put: dict | None) -> list[dict]:
    h = s["half"]
    i, j = view["i"], view["prior"]
    g = lambda key: h[key][i]
    p = lambda key: h[key][j]

    ladder = [("收入", pct(g("revenue"), p("revenue"))),
              ("毛利", pct(g("gross_profit"), p("gross_profit"))),
              ("经营利润", pct(g("operating_profit"), p("operating_profit"))),
              ("Adjusted EBIT", pct(g("adjusted_ebit"), p("adjusted_ebit"))),
              ("期间利润", pct(g("profit"), p("profit")))]
    above = [v for name, v in ladder[:-1]]
    profit_growth = ladder[-1][1]
    split = all(v > 0 for v in above) and profit_growth < 0
    ladder_ex = {
        "ref": "EX_LADDER",
        # Not `bars_labeled`: that kind pins `y0 = 0` (assets/charts.js:876), so a
        # negative bar is drawn from the zero line downwards, off the bottom of
        # the card, with no NaN and no error. The whole point of this chart is
        # that the last bar is negative. `grouped_bars` floors at
        # `min(0, mn * 1.15)` and labels its bars.
        "kind": "grouped_bars",
        "title": ((f"{half_cn(view['half'])}：经营线上的{cn_count(len(above))}个口径全部为正，"
                   f"期间利润 {signed(profit_growth)}")
                  if split else
                  f"{half_cn(view['half'])}从收入到利润的{cn_count(len(ladder))}个同比增速"),
        "xlabels": [name for name, _ in ladder],
        "groups": [{"name": f"{half_cn(view['half'])}同比", "color": "NAVY",
                    "values": rounded([v for _, v in ladder], 1)}],
        "bar_labels": True,
        "fmt": "pct1", "label_fmt": "pct1", "yfmt": "pct1",
        "ylab": "同比 %",
        "note": ("五根柱子不是一条桥，是损益表五个高度上各自的同比增速，放在一起看落差在哪一段发生。"
                 + (f"收入到 Adjusted EBIT 这一段全部为正，最高的一档是经营利润 "
                    f"{signed(ladder[2][1])}；<b>方向在经营利润之下才反过来</b>。"
                    if split else "")
                 + "增速之间不做加减，因为分母不同。"),
        "src_extra": SOURCE_RELEASES,
    }

    legs = [("金融收入", g("financial_income") - p("financial_income")),
            ("金融费用", g("financial_expenses") - p("financial_expenses")),
            ("汇兑损益", g("fx") - p("fx")),
            ("权益法结果", g("equity_result") - p("equity_result"))]
    net = sum(v for _, v in legs)
    op_delta = g("operating_profit") - p("operating_profit")
    pbt_delta = g("pbt") - p("pbt")
    assert abs(op_delta + net - pbt_delta) < 0.5, "financial bridge does not close"
    bridge = {
        "ref": "EX_FINBRIDGE",
        "kind": "bridge_bar",
        "title": (f"经营利润同比多了 {eur_m(op_delta)}，税前利润却少了 {eur_m(-pbt_delta)}："
                  f"经营线以下净变动 {eur_m(net)}"),
        "xlabels": [name for name, _ in legs] + ["经营线以下合计"],
        "stacks": [{"name": "较上年同期的变动（€ 千）", "color": "NAVY",
                    "values": rounded([v for _, v in legs] + [None])}],
        "net": {"name": "经营利润到税前利润之间的净变动", "values": [None] * len(legs) + [round(net, 6)]},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "€ 千（半年同比变动）",
        "note": ("四条腿按损益表逐行相减，四者之和恰好等于经营利润变动与税前利润变动之差 —— "
                 "这是恒等式，不是近似。"
                 "本页把它单独画出来，是因为本期收入、毛利、经营利润、Adjusted EBIT 四个口径同时改善，"
                 "而利润下降，落差整段发生在这里。"),
        "src_extra": "取自半年度业绩新闻稿与半年报的合并损益表。",
    }

    if put is None:
        return [ladder_ex, bridge]
    legs_put = [("公允价值重估（计入金融损益）", put["fair_value_swing_eur_k"]),
                ("汇兑（计入汇兑损益）", put["fx_swing_eur_k"])]
    put_total = sum(v for _, v in legs_put)
    # The fair-value figure is the swing on *all* non-controlling-interest put
    # options; the company names the brand that drives it and prints that brand's
    # own two halves in the same sentence. The FX figure is that brand's alone.
    own = put["fair_value_brand_eur_k"]
    own_swing = own["prior"] - own["current"]
    put_ex = {
        "ref": "EX_PUT",
        "kind": "bars_labeled",
        "title": (f"少数股东看跌期权（以 {put['brand']} 为主）：两项合计 {eur_m(put_total)} 的不利变动，"
                  f"比经营线以下的净变动 {eur_m(-net)} 还大"),
        "xlabels": [name for name, _ in legs_put] + ["两项合计", "经营线以下净变动（取正）"],
        "values": rounded([v for _, v in legs_put] + [put_total, -net], 1),
        "fmt": "f0c", "label_fmt": "f0c", "yfmt": "f0c",
        "ylab": "€ 千（对同比的不利影响）",
        "note": ("公司把这两个数写在半年报正文里：少数股东看跌期权负债的公允价值重估在金融损益里造成 "
                 f"{eur_m(legs_put[0][1])} 的同比不利变动 —— 这是全部少数股东期权的合计，公司写明主要来自 "
                 f"{put['brand']}：它一家本期{'亏' if own['current'] < 0 else '赚'} {eur_m(abs(own['current']))}、"
                 f"上年同期{'赚' if own['prior'] > 0 else '亏'} {eur_m(abs(own['prior']))}，差 {eur_m(own_swing)}。"
                 f"{put['brand']} 那笔负债以美元计价，其汇兑影响在汇兑损益里"
                 f"再造成 {eur_m(legs_put[1][1])}。两项之和比经营线以下的全部净变动还大 "
                 f"{eur_m(put_total - (-net))}，也就是说<b>其余财务项净贡献是正的</b>。"
                 f"这笔负债本身 {eur_m(put['liability_eur_k'])}，对应 {put['brand']} 尚未收购的 "
                 f"{put['remaining_stake_pct']}% 少数股权，行权价挂在 "
                 f"{' 年与 '.join(str(y) for y in put['tranche_ebitda_years'])} 年的 EBITDA 上。"
                 "重估不可抵扣，也是本期实际税率从 "
                 f"{num(put['effective_tax_rate_prior_pct'])}% 升到 "
                 f"{num(put['effective_tax_rate_pct'])}% 的原因。"),
        # The provenance is the stamped block's own: which document, which
        # paragraph and which note are facts about this half's filing.
        "src_extra": put["source"],
    }
    return [ladder_ex, bridge, put_ex]


# ── section four (长期常规): the channel conversion ─────────────────────────
def channel_charts(s: dict, view: dict) -> list[dict]:
    q = s["quarterly"]
    P, ch = q["periods"], q["channel"]
    share = [dtc_share(s, i) for i in range(len(P))]
    peak = max(range(len(P)), key=lambda i: ch["wholesale_branded"][i])

    mix = {
        "ref": "EX_MIX",
        "kind": "stacked_dual",
        "title": (f"DTC 占品牌收入从 {num(share[0])}% 走到 {num(share[-1])}%，"
                  f"批发品牌收入同期从峰值 {eur_m(ch['wholesale_branded'][peak])}"
                  f"（{P[peak]}）降到 {eur_m(ch['wholesale_branded'][-1])}"),
        "xlabels": list(P),
        "stacks": [
            {"name": "DTC（三个品牌直营）", "color": "NAVY", "values": rounded(ch["dtc"])},
            {"name": "批发品牌", "color": "GOLD", "values": rounded(ch["wholesale_branded"])},
        ],
        "line": {"name": "DTC 占品牌收入（右轴）", "color": "RED",
                 "values": rounded(share, 1), "ymax": 100},
        "fmt": "f0c", "label_fmt": "f0c",
        "ylab": "€ 千（单季）",
        "ylab2": "DTC 占比 %",
        "note": ("柱是每个季度的两个渠道绝对额，右轴红线是 DTC 占品牌收入的比例 —— "
                 "分母只含三个品牌，不含面料与其他，这是公司自己的口径，"
                 f"本期公司把它印成 {round_half_up(share[-1], 0)}%。"
                 f"批发品牌收入较 {P[peak]} 的峰值下降 "
                 f"{num(abs(pct(ch['wholesale_branded'][-1], ch['wholesale_branded'][peak])))}%，"
                 "公司把这写成主动选择（「retail-first」）而不是需求问题。"
                 "右轴显式设了 100% 的上界，且写在 line 里 —— 这一图型的右轴默认封顶在 60，"
                 "写在 exhibit 顶层不生效，占比线会被画到画布外而图例照常显示。"),
        "src_extra": SOURCE_RELEASES,
    }

    yoy = [None if i < 4 else round(pct(q["revenue_eur_k"][i], q["revenue_eur_k"][i - 4]), 1)
           for i in range(len(P))]
    flat_from = None
    for i in range(len(P) - 1, 3, -1):
        if abs(yoy[i]) > 10:
            flat_from = i + 1
            break
    revenue = {
        "ref": "EX_REV",
        "kind": "gs_bar",
        "title": (f"集团单季收入，{cn_count(len(P))}个季度没有一格是相减出来的："
                  f"本季 {eur_m(q['revenue_eur_k'][-1])}，同比 {signed(yoy[-1])}"),
        "xlabels": list(P),
        "values": rounded(q["revenue_eur_k"]),
        "yoy": {"name": "同比（右轴）", "color": "GOLD", "values": yoy},
        "fmt": "f0c", "label_fmt": "f0c", "yfmt": "f0c",
        "ylab": "€ 千（单季）",
        "ylab2": "同比 %",
        "note": ("这条线没有一格是由累计相减得到的：公司每季都把<b>单季</b>收入印出来，"
                 "连同品牌、渠道、地区与分部的单季拆分。"
                 + (f"自 {P[flat_from]} 起，{cn_count(len(P) - flat_from)}个季度的同比全部落在 ±10% 以内。"
                    if flat_from is not None and len(P) - flat_from >= 4 else "")
                 + "前四季没有同比，因为本页的季度记录从 "
                 + f"{P[0]} 开始 —— 公司上市前没有公布过任何季度数。"),
        "src_extra": SOURCE_RELEASES,
    }

    st = s["stores"]
    doors = {
        "ref": "EX_DOORS",
        "kind": "bar_line_dual",
        "title": (f"直营门店从 {st['dtc']['Group'][0]} 家增到 {st['dtc']['Group'][-1]} 家，"
                  f"批发门店从 {st['wholesale_doors']['Group'][0]} 家减到 "
                  f"{st['wholesale_doors']['Group'][-1]} 家"),
        "xlabels": list(st["dates"]),
        "bar": {"name": "直营门店（DOS）", "color": "NAVY", "values": st["dtc"]["Group"]},
        "line": {"name": "批发门店（右轴）", "color": "RED", "values": st["wholesale_doors"]["Group"],
                 "yfmt": "f0"},
        "fmt": "f0", "label_fmt": "f0", "yfmt": "f0",
        "ylab": "家（直营）",
        "ylab2": "家（批发）",
        "xrot": 90,
        "note": ("渠道改造在门店口径上的同一件事：直营门店净增 "
                 f"{st['dtc']['Group'][-1] - st['dtc']['Group'][0]} 家，"
                 f"批发门店净减 {st['wholesale_doors']['Group'][0] - st['wholesale_doors']['Group'][-1]} 家。"
                 "两条线都只读每份发布里当期那一栏 —— 比较栏在 TOM FORD FASHION 并表之前少一列，"
                 "按等分去读会静默错位。"),
        "src_extra": "各期末门店数取自当期营收或业绩新闻稿的门店表，Group 一列已逐期核对等于三个品牌之和。",
    }
    return [mix, revenue, doors]


# ── section four (长期常规): where the profit is ────────────────────────────
def brand_charts(s: dict, view: dict) -> list[dict]:
    se = s["segment_adjusted_ebit"]
    keep = [i for i, t in enumerate(se["total"]) if t is not None]
    labels = [se["periods"][i] for i in keep]
    take = lambda key: [se[key][i] for i in keep]

    losers = [name for name, key in (("Thom Browne", "thom_browne"), ("TOM FORD FASHION", "tff"))
              if se[key][-1] is not None and se[key][-1] < 0]
    grid = {
        "ref": "EX_SEGEBIT",
        "kind": "grouped_bars",
        "title": (f"三个品牌的 Adjusted EBIT：本期 Zegna {eur_m(se['zegna'][-1])}，"
                  + (f"另外{cn_count(len(losers))}个为负" if losers else "另外两个为正")),
        "xlabels": labels,
        "groups": [
            {"name": "Zegna 分部", "color": "NAVY", "values": rounded(take("zegna"))},
            {"name": "Thom Browne 分部", "color": "BLUE", "values": rounded(take("thom_browne"))},
            {"name": "TOM FORD FASHION 分部", "color": "GOLD", "values": rounded(take("tff"))},
            {"name": "集团费用（Corporate）", "color": "RED", "values": rounded(take("corporate"))},
        ],
        "bar_labels": False,
        "fmt": "f0c", "label_fmt": "f0c",
        "ylab": "€ 千",
        "xrot": 45,
        "note": ("半年与全年交替排列，因为公司只在这两个频率上给分部利润。"
                 f"{'、'.join(losers)} 本期为负，"
                 "而 Corporate 是一条一直为负的集团费用线。"
                 "<b>2022 年上半年之前没有 Corporate 这一行</b>："
                 "集团费用当时整体计在 Zegna 分部里，FY2022 业绩发布才把它拆出来并重述了上半年 —— "
                 "详见核对抽屉里的重述表。"),
        "src_extra": "各期分部 Adjusted EBIT 取自当期业绩新闻稿的分部表；每期五项之和已核对等于集团合计。",
    }

    ratio = [se["zegna"][i] / se["total"][i] * 100 for i in keep]
    over = [(labels[k], ratio[k]) for k in range(len(keep)) if ratio[k] > 100]
    run = 0
    for k in range(len(ratio) - 1, -1, -1):
        if ratio[k] > 100:
            run += 1
        else:
            break
    share = {
        "ref": "EX_SEGSHARE",
        "kind": "lines",
        "title": (f"Zegna 一个分部的 Adjusted EBIT 相当于集团的 {num(ratio[-1])}%"
                  + (f"，已连续{cn_count(run)}期高于 100%" if run >= 2 else "")),
        "xlabels": labels,
        "series": [
            {"name": "Zegna 分部占集团 Adjusted EBIT", "values": rounded(ratio, 1), "color": "NAVY"},
            {"name": "100%（其余三项合计为零的水平）", "values": [100.0] * len(keep), "color": "RED"},
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1",
        "end_label": True,
        "ylab": "占集团 Adjusted EBIT %",
        "xrot": 45,
        "note": ("高于 100% 意味着另外两个品牌加上集团费用合计为负 —— "
                 "集团的全部利润来自一个分部，另外三项在往回吃。"
                 + (f"这条线{cn_count(len(over))}次高于 100%，最早一次是 {over[0][0]}。"
                    if over else "这条线还没有越过 100%。")
                 + "红线不是目标，只是「其余三项合计为零」这个水平。"),
        "src_extra": "由上一张图的同一组数字相除得到（D）。",
    }

    st, q = s["stores"], s["quarterly"]
    years = [y for y in range(2022, view["year"] + 1)
             if f"{y}-12-31" in st["dates"] and f"{y}Q4" in q["periods"]]
    tb_rev = [sum(q["channel"]["dtc_thom_browne"][q["periods"].index(f"{y}Q{n}")]
                  for n in (1, 2, 3, 4)) for y in years]
    tb_doors = [st["dtc"]["Thom Browne"][st["dates"].index(f"{y}-12-31")] for y in years]
    per_door = [r / d for r, d in zip(tb_rev, tb_doors)]
    tb = {
        "ref": "EX_TB",
        "kind": "bar_line_dual",
        "title": (f"Thom Browne 直营门店 {tb_doors[0]} → {tb_doors[-1]} 家，"
                  f"单店直营收入 {eur_m(per_door[0])} → {eur_m(per_door[-1])}"),
        "xlabels": [f"FY{y}" for y in years],
        "bar": {"name": "直营门店数（年末）", "color": "NAVY", "values": tb_doors},
        "line": {"name": "单店直营收入（右轴，€ 千）", "color": "RED",
                 "values": rounded(per_door, 1), "yfmt": "f0c"},
        "fmt": "f0", "label_fmt": "f0", "yfmt": "f0",
        "ylab": "家",
        "ylab2": "€ 千 / 店",
        "note": (f"门店数增长 {num(pct(tb_doors[-1], tb_doors[0]))}%，"
                 f"直营收入增长 {num(pct(tb_rev[-1], tb_rev[0]))}%，"
                 f"两者之差落在单店上：{num(pct(per_door[-1], per_door[0]))}%。"
                 "分母用年末门店数，不是平均门店数 —— 在扩张期这会让单店数偏低，"
                 "所以这张图只适合看方向，不适合和别家的单店收入直接比。"),
        "src_extra": "直营收入按该年四个季度的 Thom Browne DTC 相加（D）；门店数取自各年末门店表。",
    }
    return [grid, share, tb]


# ── section four (长期常规): the geographic rotation ────────────────────────
def geography_charts(s: dict, view: dict) -> list[dict]:
    q = s["quarterly"]
    P, geo = q["periods"], q["geography"]
    names = [("EMEA", "emea", "NAVY"), ("美洲", "americas", "BLUE"),
             ("大中华区", "greater_china", "RED"), ("亚太其余", "rest_of_apac", "GOLD")]
    first = {zh: geo[key][0] for zh, key, _ in names}
    last = {zh: geo[key][-1] for zh, key, _ in names}
    grew = max(names, key=lambda n: last[n[0]] - first[n[0]])[0]
    fell = min(names, key=lambda n: last[n[0]] - first[n[0]])[0]

    regions = {
        "ref": "EX_GEO",
        "kind": "lines_endlabels",
        "title": (f"{cn_count(len(names))}个区域{cn_count(len(P))}季："
                  f"{grew}增加 {eur_m(last[grew] - first[grew])}，"
                  f"{fell}{'减少' if last[fell] < first[fell] else '增加'} "
                  f"{eur_m(abs(last[fell] - first[fell]))}"),
        "xlabels": list(P),
        "series": [{"name": zh, "color": color, "values": rounded(geo[key])}
                   for zh, key, color in names],
        "end_label": True,
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "€ 千（单季）",
        "xrot": 90,
        "note": ("公司在 "
                 + s["quarterly"]["geography"]["basis_change_release"]
                 + " 的发布里换过一次区域口径：此前是 EMEA / 北美 / 拉美 / 亚太（亚太下挂大中华与日本），"
                 "此后是 EMEA / 美洲 / 大中华区 / 亚太其余。<b>文字里没有任何说明</b>，"
                 "唯一的证据是算术：美洲 = 北美 + 拉美，亚太其余 = 亚太 − 大中华区。"
                 "两套口径同时印出过的期间有"
                 + cn_count(s["quarterly"]["geography"]["periods_on_both_bases"])
                 + "个，两条恒等式在每一个上都逐欧元相等，本图因此把换口径之前的季度按新口径还原。"),
        "src_extra": "换口径之前的四个区域为本页由公司自己印出的两行相加／相减还原（D）。",
    }

    am, gc = geo["americas"], geo["greater_china"]
    run = 0
    for i in range(len(P) - 1, -1, -1):
        if am[i] > gc[i]:
            run += 1
        else:
            break
    earlier = [P[i] for i in range(len(P) - run) if am[i] > gc[i]]
    cross = {
        "ref": "EX_CROSS",
        "kind": "lines",
        # The lead clause is conditional, so the invariant phrase comes first:
        # `tests/test_chart_window.py` keys an exemption on a title fragment, and
        # a key that only matches one branch goes unused the quarter the other
        # branch renders.
        "title": ("美洲与大中华区："
                  + (f"美洲已连续{cn_count(run)}个季度更大，" if run >= 2 else "")
                  + f"本季 {eur_m(am[-1])} 对 {eur_m(gc[-1])}"),
        "xlabels": list(P),
        "series": [
            {"name": "美洲", "color": "BLUE", "values": rounded(am)},
            {"name": "大中华区", "color": "RED", "values": rounded(gc)},
        ],
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "end_label": True,
        "ylab": "€ 千（单季）",
        "xrot": 90,
        "note": (f"起点上大中华区是美洲的 {num(gc[0] / am[0], 1)} 倍，"
                 + (f"本季反过来是 {num(am[-1] / gc[-1], 2)} 倍。" if am[-1] > gc[-1]
                    else f"本季仍是 {num(gc[-1] / am[-1], 2)} 倍。")
                 + (f"这条交叉在当前这一段之前还出现过{cn_count(len(earlier))}次"
                    f"（{'、'.join(earlier)}），随后又被反超，所以「反超」这件事在本页的记录里"
                    "不是一次性的。" if earlier else "")
                 + "两条都是单季绝对额，没有做汇率调整 —— 公司按季给恒定汇率增速，但不给恒定汇率的绝对额。"),
        "src_extra": "同上图，换口径之前的季度按同样的算术还原（D）。",
    }
    return [regions, cross]


# ── the audit drawer: what was republished, and what changed ────────────────
# What each restatement was, in the page's words. Fixed history: a roll never
# rewrites a past restatement, it can only add one, and an unnamed one stops
# the build rather than printing a key.
RESTATEMENT_WORDS = {
    "geography_taxonomy": "地区口径换表",
    "other_line_absorbs_agnona": "「其他」并入 Agnona",
    "other_line_absorbs_third_party_brands": "「其他」并入第三方品牌",
    "pelletteria_tizeta_moves_to_the_tom_ford_fashion_segment": "Pelletteria Tizeta 调入 TOM FORD FASHION 分部",
    "corporate_costs_leave_the_zegna_segment": "集团费用移出 Zegna 分部",
    "fy2021_wholesale_and_other": "FY2021 批发与「其他」之间重分类",
    "income_statement_moves_from_by_nature_to_by_function": "损益表由按性质改为按功能列报",
}
CENSUS_KIND_WORDS = {"segment": "分部", "brand": "品牌", "channel": "渠道", "geo": "地区"}


def census_table(s: dict, n: int) -> dict:
    """Every period more than one release printed, counted per line."""
    rows = s["republication_census"]["rows"]
    changed = [r for r in rows if r["periods_changed"] > 0]
    total = next(r for r in rows if r["row"] == "total" and r["kind"] == "segment")
    return {
        "n": n,
        "title": (f"重复公布普查：集团合计收入被再印 {total['periods_republished']} 次、"
                  f"改过 {total['periods_changed']} 次；它下面{cn_count(len(rows) - 1)}条线里"
                  f"有{cn_count(len(changed))}条改过"),
        "headers": ["行", "口径", "被印过的期间数", "其中后来又被印过", "再印时数字变了", "变了的期间"],
        "rows": [[r["label"], CENSUS_KIND_WORDS[r["kind"]], str(r["periods_published"]),
                  str(r["periods_republished"]), str(r["periods_changed"]),
                  "、".join(r["changed"]) if r["changed"] else "—"]
                 for r in rows],
    }


def restatement_detail(s: dict, r: dict) -> str:
    """The arithmetic that exposes one restatement, from the block's own figures."""
    what = r["what"]
    if what == "geography_taxonomy":
        return ("美洲 = 北美 + 拉美，亚太其余 = 亚太 − 大中华区"
                + ("，逐欧元相等" if r["identity_holds_exactly"] else "，但有差额"))
    if what == "other_line_absorbs_agnona":
        return "、".join(f"{p} €{v} 千" for p, v in r["size_eur_k"].items()) + " 并入「其他」"
    if what == "other_line_absorbs_third_party_brands":
        tpb = s["quarterly"]["brand"]["fold_overlap"]["third_party_brands"]
        same = all(a + b == c for a, b, c in zip(tpb["other_as_first_printed"],
                                                 tpb["third_party_brands"],
                                                 tpb["other_as_refolded"]))
        return "旧「其他」加第三方品牌" + ("逐期等于新「其他」" if same else "与新「其他」有差额")
    if what == "pelletteria_tizeta_moves_to_the_tom_ford_fashion_segment":
        return (minus_sign("、".join(f"{p} {eur_m(v)}" for p, v in r["revenue_changes_eur_k"].items()))
                + " 移出 Zegna 分部收入" + ("，集团合计不变" if r["group_total_unchanged"] else ""))
    if what == "corporate_costs_leave_the_zegna_segment":
        a = r["adjusted_ebit_eur_k"]
        return "；".join(
            f"{p} Zegna 分部 {eur_m(a[f'{p}_as_first_published'])} → {eur_m(a[f'{p}_as_restated'])}，"
            f"差额 {eur_m(-a[f'{p}_corporate_line'])} 即新设的 Corporate 行"
            for p in ("2022H1", "FY2021", "FY2020"))
    if what == "fy2021_wholesale_and_other":
        return f"{eur_m(r['size_eur_k'])}（{r['cause']}）由批发移到「其他」，集团合计不变"
    if what == "income_statement_moves_from_by_nature_to_by_function":
        return ("重述 " + "、".join(r["periods_restated"])
                + ("；两种列报下经营利润、税前利润、税与利润相同" if r["totals_unchanged"] else ""))
    raise ValueError(f"restatement `{what}` has no arithmetic on this page")


def restatement_table(s: dict, n: int) -> dict:
    """The restatements behind the census, each with the arithmetic that exposes it."""
    rs = s["restatements"]
    unnamed = [r["what"] for r in rs if r["what"] not in RESTATEMENT_WORDS]
    if unnamed:
        raise ValueError(f"restatements {unnamed} have no wording on this page: add them to RESTATEMENT_WORDS")
    explained = [r for r in rs if r.get("footnoted_by_the_company")]

    def both(r: dict) -> str:
        for key in ("periods_on_both_bases", "periods_checked_on_both_bases"):
            if key in r:
                return str(r[key])
        return "—"

    return {
        "n": n,
        "title": (f"{cn_count(len(rs))}处重述：只有{cn_count(len(explained))}处被公司说明过，"
                  "其余都只能靠算术认出来"),
        "headers": ["重述", "新口径首次出现", "公司是否说明", "两套口径都印过的期间数", "算术"],
        "rows": [[RESTATEMENT_WORDS[r["what"]], r["first_on_new_basis"],
                  "是（脚注）" if r.get("footnoted_by_the_company") else "否",
                  both(r), restatement_detail(s, r)]
                 for r in rs],
    }


# ── section one (a): the questions last quarter's analysis left open ────────
def check_set_in(block: dict, name: str, view: dict) -> None:
    """A block settling last quarter's analysis must name a quarter of this half.

    The page is half-yearly and the analyses are quarterly: the one before this
    half's results is the revenue release of the half's other quarter. A block
    naming anything else is another half's.
    """
    if block["set_in"] not in view["quarters"] or block["set_in"] == view["latest_quarter"]:
        raise ValueError(f"series block `{name}` settles an analysis set in {block['set_in']!r}, "
                         f"which is not this half's earlier quarter: update it with the roll")


def closure_chart(closure: dict, view: dict) -> dict:
    check_set_in(closure, "followup_closure", view)
    items, buckets = closure["items"], closure["buckets"]
    stray = [it["n"] for it in items if it["bucket"] not in buckets]
    if stray:
        raise ValueError(f"follow-up items {stray} sit in no declared bucket")
    counts = [sum(1 for it in items if it["bucket"] == b) for b in buckets]
    falsified = [it for it in items if "被证伪" in it["verdict"]]
    calls: dict[str, list[int]] = {}
    for it in items:
        calls.setdefault(it["call"], []).append(it["n"])
    return {
        "ref": "EX_CLOSURE",
        "kind": "bars_labeled",
        "title": (f"上季 {len(items)} 条待验证问题：" + "、".join(
            f"{count} 条{label}" for label, count in zip(buckets, counts) if count)),
        "xlabels": list(buckets),
        "values": counts,
        "legend": "问题条数",
        "fmt": "f0", "yfmt": "f0", "label_fmt": "f0",
        "ylab": "条",
        "note": ((f"判定里带「被证伪」的是第 {'、'.join(str(it['n']) for it in falsified)} 条："
                  + "；".join(f"第 {it['n']} 条，{it['reading']}" for it in falsified) + "。"
                  if falsified else "")
                 + "按本季分析稿的框架复盘，"
                 + "，".join(f"{cn_count(len(ns))}条{call}（第 {'、'.join(str(n) for n in ns)} 条）"
                            for call, ns in calls.items())
                 + "。"),
        "src_extra": (f"问题清单来自 {closure['set_in_report']}；判定依据 {closure['closed_in_report']}，"
                      "逐条回到营收与业绩新闻稿、半年报和两场电话会核实。"),
    }


def closure_table(closure: dict, n: int) -> dict:
    return {
        "n": n,
        "title": "上季待验证问题与本季判定（问题摘自上季分析稿，判定原文取自本季分析稿第 0 节）",
        "headers": ["#", "上季问题", "判定", "本季读数"],
        "rows": [[str(it["n"]), it["question"], it["verdict"], it["reading"]] for it in closure["items"]],
    }


# ── section one (b): the thresholds last quarter's analysis set ─────────────
def quarterly_yoy(values: list) -> list:
    return [None if k < 4 or values[k] is None or not values[k - 4] else pct(values[k], values[k - 4])
            for k in range(len(values))]


def prior_series(s: dict) -> dict:
    """Every threshold the series can measure, on its own axis."""
    q = s["quarterly"]
    P, ch, st = q["periods"], q["channel"], s["stores"]
    z = lambda v: 0.0 if v is None else v
    branded = [z(ch["dtc"][k]) + z(ch["wholesale_branded"][k]) for k in range(len(P))]
    like = [z(ch["dtc_zegna"][k]) + z(ch["dtc_thom_browne"][k])
            + z(ch["ws_zegna"][k]) + z(ch["ws_thom_browne"][k]) for k in range(len(P))]

    def per_store(k: int):
        end = q["period_ends"][k]
        if end not in st["dates"]:
            return None
        doors = st["dtc"]["ZEGNA"][st["dates"].index(end)]
        return ch["dtc_zegna"][k] / doors if doors else None

    stores = [per_store(k) for k in range(len(P))]
    h, pre = s["half"], s["pre_listing_half"]
    firsts = [(pre["period"], pre["adjusted_ebit"] / pre["revenue"] * 100)] + [
        (p, e / r * 100) for p, r, e in zip(h["periods"], h["revenue"], h["adjusted_ebit"])
        if p.endswith("H1") and None not in (r, e)]
    return {
        "h1_margin": ([p for p, _ in firsts], [v for _, v in firsts]),
        "tb_wholesale": (list(P), quarterly_yoy(ch["ws_thom_browne"])),
        "branded_net": (list(P), [None if k < 4 else (branded[k] - branded[k - 4]) / 1000
                                  for k in range(len(P))]),
        "branded_net_like": (list(P), [None if k < 4 else (like[k] - like[k - 4]) / 1000
                                       for k in range(len(P))]),
        "zegna_per_store": (list(P), [None if k < 4 or None in (stores[k], stores[k - 4])
                                      else pct(stores[k], stores[k - 4]) for k in range(len(P))]),
    }


def prior_entries(s: dict, view: dict, block: dict) -> list[dict]:
    """Each threshold with the reading it is settled on, computed wherever the series can."""
    check_set_in(block, "prior_kpi_settlement", view)
    series = prior_series(s)
    out = []
    for e in block["quantified"]:
        wanted = view["latest_quarter"] if QUARTER_LABEL.match(e["reading"]) else view["half"]
        if e["reading"] != wanted:
            raise ValueError(f"series block `prior_kpi_settlement` reads `{e['id']}` at {e['reading']!r}, "
                             f"but this page's latest reading is {wanted!r}: update it with the roll")
        if e["id"] in series:
            if "actual" in e or "previous" in e:
                raise ValueError(f"`prior_kpi_settlement.{e['id']}` is computed from the series; "
                                 "remove its typed value")
            labels, values = series[e["id"]]
            k = labels.index(e["reading"])
            entry = {**e, "actual": values[k]}
            if e.get("upper_quarters", 1) == 2:
                entry["previous"] = values[k - 1]
            out.append(entry)
        else:
            if "actual" not in e:
                raise ValueError(f"`prior_kpi_settlement.{e['id']}` has no reading and no way to compute one")
            out.append(dict(e))
    return out


def upper_met(e: dict) -> bool | None:
    """Whether the add-side condition of a threshold held; None if it has none."""
    if "upper" not in e:
        return None
    readings = [e["actual"]] + ([e["previous"]] if e.get("upper_quarters", 1) == 2 else [])
    beyond = (lambda v: v > e["upper"]) if e.get("upper_strict") else (lambda v: v >= e["upper"])
    return all(beyond(v) for v in readings) and e.get("plan_raised", True)


def prior_value(e: dict, value: float, *, sign: bool = False) -> str:
    """A threshold or reading in its own unit; `sign` marks a reading, and only a
    change or a growth rate carries one -- a margin of 7.5% is not "+7.5%"."""
    if e["unit"] == "eur_m":
        return eur_m(value * 1000)
    if e["unit"] == "pp":
        return minus_sign(f"{value:+.1f}pp")
    rate = "同比" in e["metric"] or "增速" in e["metric"]
    return signed(value) if sign and rate else minus_sign(f"{value:.1f}%")


PRIOR_CAP = 200


def prior_charts(s: dict, view: dict, block: dict) -> tuple[list[dict], list[dict]]:
    entries = prior_entries(s, view, block)
    plotted = [e for e in entries if e["threshold"] != 0]
    unplotted = [e for e in entries if e["threshold"] == 0]
    held = [e for e in plotted if headroom(e["direction"], e["threshold"], e["actual"]) >= 0]
    upper = [e for e in entries if upper_met(e)]
    nearest = min(plotted, key=lambda e: headroom(e["direction"], e["threshold"], e["actual"]))
    half_way = [e for e in entries if upper_met(e) is False and "plan_raised" in e
                and all(v >= e["upper"] for v in (e["actual"], e["previous"]))]
    fx = next((e for e in entries if e["id"] == "fx_drag"), None)
    overview = headroom_exhibit(
        (f"上季 {len(entries)} 条量化阈值："
         + (f"能算余量的 {len(plotted)} 条" if unplotted else "")
         + ("都守住" if len(held) == len(plotted) else f"守住 {len(held)} 条、击穿 {len(plotted) - len(held)} 条")
         + (f"，{len(upper)} 条连加仓线也过了" if upper else "")),
        plotted, "actual",
        ("正值 = 仍在安全侧；线是上季分析稿里触发减仓或警示的那一条。"
         + f"离线最近的是「{nearest['metric']}」：{prior_value(nearest, nearest['actual'], sign=True)} 对 "
         f"{prior_value(nearest, nearest['threshold'])}。"
         + (f"连加仓线也过了的是{'、'.join('「' + e['metric'] + '」' for e in upper)}。" if upper else "")
         + "".join(f"「{e['metric']}」的数字那一半过了线（上一季 {signed(e['previous'])}、本季 {signed(e['actual'])}），"
                   "管理层没有上调规划，加仓条件只成立一半。" for e in half_way)
         + "".join(f"「{e['metric']}」的警戒线是「转负」，零阈值算不出百分比余量，不进这张图，结算在核对抽屉的表里。"
                   for e in unplotted)
         + (f"「{fx['metric']}」那条原文写在 EUR/USD 季均上（{fx['as_written']}）；季均不是申报数，"
            "按上季稿写明的等价后果结算。" if fx else "")),
        src_extra=("阈值原文取自上季本地分析稿第 8 节，不是公司指引；实际值为本季披露值或据其自算，"
                   "逐条出处见核对抽屉。"),
    )
    overview["ref"] = "EX_PRIOR"
    # One bar a hundred times its threshold flattens every other bar to a
    # sliver; the renderer caps it and prints the true value on the bar.
    if max(overview["values"]) > PRIOR_CAP:
        overview["ycap"] = PRIOR_CAP
        overview["note"] += f"超过 {PRIOR_CAP}% 的柱截在 {PRIOR_CAP}%，真值标在柱上。"
    charts = [overview]

    series = prior_series(s)
    h = s["half"]
    margin_of = {p: e / r for p, r, e in zip(h["periods"], h["revenue"], h["adjusted_ebit"])
                 if None not in (r, e)}
    halves = [(y, margin_of[f"{y}H1"], margin_of[f"{y}H2"])
              for y in sorted({int(p[:4]) for p in h["periods"]})
              if f"{y}H1" in margin_of and f"{y}H2" in margin_of]
    first_higher = [str(y) for y, a, b in halves if a > b]
    second_higher = [str(y) for y, a, b in halves if b > a]
    q_prev = view["quarters"][0] if view["quarters"][0] != view["latest_quarter"] else None
    by_id = {e["id"]: e for e in entries}

    def line(e: dict, *, fmt: str, ylab: str, note: str, src: str, extra=None, rotate: bool = False) -> dict:
        labels, values = series[e["id"]]
        start = next(k for k, v in enumerate(values) if v is not None)
        labels, values = labels[start:], values[start:]
        ok = headroom(e["direction"], e["threshold"], e["actual"]) >= 0
        side = "上方" if e["direction"] == "up" else "下方"
        lines = [{"name": e["metric"], "color": "NAVY", "values": rounded(values, 2)},
                 {"name": f"上季阈值（安全侧在{side}）", "color": "RED",
                  "values": [e["threshold"]] * len(labels)}]
        if "upper" in e:
            lines.append({"name": "上季的加仓线", "color": "GOLD", "values": [e["upper"]] * len(labels)})
        if extra:
            name, color, more = extra
            lines.insert(1, {"name": name, "color": color, "values": rounded(more[start:], 2)})
        word = "本期" if e["reading"] == view["half"] else "本季"
        chart = {
            "ref": f"EX_PRIOR_{e['id'].upper()}",
            "kind": "lines",
            "title": (f"{e['metric']}：{'守住' if ok else '已击穿'}上季阈值 {prior_value(e, e['threshold'])}，"
                      f"{word} {prior_value(e, e['actual'], sign=True)}"),
            "xlabels": labels,
            "series": lines,
            "fmt": fmt, "yfmt": fmt, "label_fmt": fmt,
            "end_label": True,
            "ylab": ylab,
            "note": f"上季稿的触发条件：{e['trigger']}。" + note,
            "src_extra": src,
        }
        if rotate:
            chart["xrot"] = 90
        return chart

    if "h1_margin" in by_id:
        e = by_id["h1_margin"]
        pre = s["pre_listing_half"]
        charts.append(line(
            e, fmt="pct1", ylab="上半年 Adjusted EBIT ÷ 收入 %",
            note=(("只画上半年，因为这条阈值是上半年对上半年：半年利润率并不是每年都下半年高 —— "
                   f"{'、'.join(first_higher)} 年是上半年高，{'、'.join(second_higher)} 年是下半年高。"
                   if first_higher and second_higher else "只画上半年，因为这条阈值是上半年对上半年。")
                  + f"{pre['period']} 取自 F-1，那是任何申报里印出的第一个半年。"),
            src="上半年收入与 Adjusted EBIT 取自各期半年度业绩新闻稿与 F-1（D）。"))
    if "tb_wholesale" in by_id:
        e = by_id["tb_wholesale"]
        labels, values = series["tb_wholesale"]
        before = (f"上一季 {signed(values[labels.index(q_prev)])}，" if q_prev else "")
        charts.append(line(
            e, fmt="pct1", ylab="同比 %",
            note=(f"{before}本季 {signed(e['actual'])}。这是报告口径（含汇率），由本页单季批发收入现算；"
                  "上季稿用的也是这个口径的算术。"),
            src="Thom Browne 品牌批发收入取自各季营收与业绩新闻稿的渠道表（D）。", rotate=True))
    if "branded_net" in by_id:
        e = by_id["branded_net"]
        like_labels, like = series["branded_net_like"]
        tff_from = s["quarterly"]["brand"]["tff_floor"]
        charts.append(line(
            e, fmt="f1", ylab="€M（同比变动）",
            extra=("不含 TOM FORD FASHION（同口径对照）", "GRAY", like),
            note=(f"DTC 的同比增量减去批发的同比减量，等于三个品牌合计收入的同比变动（报告口径）。"
                  + (f"上一季 {eur_m(e['previous'] * 1000)}、本季 {eur_m(e['actual'] * 1000)}。" if "previous" in e else "")
                  + f"TOM FORD FASHION 从 {tff_from} 起并表，并表后一年里的同比变动含并购带来的增量，"
                  "灰线剔除它，只看 ZEGNA 与 Thom Browne。"),
            src="DTC 与批发品牌收入取自各季营收与业绩新闻稿的渠道表；同比变动为本页自算（D）。", rotate=True))
    if "zegna_per_store" in by_id:
        e = by_id["zegna_per_store"]
        labels, values = series["zegna_per_store"]
        first = next(labels[k] for k, v in enumerate(values) if v is not None)
        st = s["stores"]
        ends = s["quarterly"]["period_ends"]
        k = s["quarterly"]["periods"].index(e["reading"])
        doors_now = st["dtc"]["ZEGNA"][st["dates"].index(ends[k])]
        doors_then = st["dtc"]["ZEGNA"][st["dates"].index(ends[k - 4])]
        before = (f"上一季 {signed(values[labels.index(q_prev)])}，" if q_prev else "")
        charts.append(line(
            e, fmt="pct1", ylab="同比 %",
            note=("单店收入 = 当季 ZEGNA 品牌 DTC 收入 ÷ 季末 ZEGNA 直营门店数（上季稿的口径）。"
                  f"{before}本季 {signed(e['actual'])}，同期门店 {doors_then} → {doors_now} 家。"
                  f"季末门店数从 2022-03-31 起按季印出，此前只有年末数，所以同比从 {first} 起。"),
            src="ZEGNA 品牌 DTC 收入与季末直营门店数取自各季营收与业绩新闻稿（D）。", rotate=True))
    return charts, entries


def prior_table(block: dict, entries: list[dict], n: int) -> dict:
    rows = []
    for e in entries:
        met = upper_met(e)
        rows.append([
            e["metric"], e["trigger"],
            prior_value(e, e["threshold"]),
            prior_value(e, e["actual"], sign=True)
            + (f"（上一季 {prior_value(e, e['previous'], sign=True)}）" if "previous" in e else ""),
            (minus_sign(f"{headroom(e['direction'], e['threshold'], e['actual']):+.1f}%")
             if e["threshold"] != 0 else ("未转负" if e["actual"] >= 0 else "已转负")),
            "—" if met is None else ("过了" if met else "没过"),
            e.get("source", "本页序列现算（D）"),
        ])
    by_id = {e["id"]: e for e in entries}
    for w in block.get("stance_withdrawal", []):
        if "unsettled" in w:
            verdict = "无法结算：" + w["unsettled"]
        else:
            legs = [by_id[i] for i in w["legs"]]
            broken = [headroom(e["direction"], e["threshold"], e["actual"]) < 0 for e in legs]
            if "group_organic" in w:
                broken.append(w["group_organic"] < w["group_organic_below"])
            verdict = "触发" if all(broken) else "未触发"
            if "group_organic" in w:
                verdict += f"（集团二季度有机 {w['group_organic']:.1f}%；{w['source']}）"
        rows.append([f"立场撤销条件 {w['n']}", w["text"], "—", "—", "—", "—", verdict])
    return {
        "n": n,
        "title": "上季量化阈值的结算（阈值原文取自上季分析稿第 8 节）",
        "headers": ["指标", "上季触发条件", "警戒线", "本期读数", "余量 D", "加仓线", "出处 / 结算"],
        "rows": rows,
    }


# ── section one (c): the company's own medium-term targets ───────────────────
def _span(values: list[float]) -> str:
    """``[2200, 2400]`` (€M) -> ``€2.2–2.4B``; ``[250, 300]`` -> ``€250–300M``."""
    low, high = values
    if low >= 1000:
        return f"€{low / 1000:.1f}–{high / 1000:.1f}B"
    return f"€{low:,.0f}–{high:,.0f}M"


ACTUAL_COLORS = ["NAVY", "BLUE", "GRAY", "GREEN"]


def target_charts(s: dict, view: dict) -> list[dict]:
    mt = s["medium_term_targets"]
    new = mt["targets_2027"]
    a = s["annual"]
    fy = lambda key, year: a[key][a["years"].index(year)]
    base = mt["base_year"]
    # The release that replaced the December 2023 set reported this year, so it
    # is the only year that set was ever live for.
    lived = new["results_year_of_the_release"]
    span = lived - base
    rev_old = cagr(fy("revenue", base), fy("revenue", lived), span)
    ebit_old = cagr(fy("adjusted_ebit", base), fy("adjusted_ebit", lived), span)
    rev_target = next(t for t in mt["targets"] if t["metric"] == "group_revenue_cagr_pct")["floor"]
    ebit_target = next(t for t in mt["targets"]
                       if t["metric"] == "group_adjusted_ebit_cagr_pct")["around"]
    old = {
        "ref": "EX_TARGET_OLD",
        "kind": "grouped_bars",
        "title": (f"{mt['set_on']} 定下的中期目标只走完 FY{lived} 一年：收入 {signed(rev_old)} "
                  f"对「10% 以上」，Adjusted EBIT {signed(ebit_old)} 对「约 20%」，"
                  f"随后在 {new['set_on']} 被换掉"),
        "xlabels": ["集团收入", "集团 Adjusted EBIT"],
        "groups": [
            {"name": f"{mt['set_on']} 给出的年复合目标", "color": "RED",
             "values": [rev_target, ebit_target]},
            {"name": f"FY{base} → FY{lived} 实际（按公布的 FY{base} 为基数）",
             "color": "NAVY", "values": rounded([rev_old, ebit_old], 1)},
        ],
        "bar_labels": True,
        "fmt": "pct1", "label_fmt": "pct1",
        "ylab": "年复合增速 %",
        "note": ("目标是公司在第二次资本市场日给出的，带基年、带口径脚注。"
                 f"<b>但基年本身没有被公布过</b>：脚注写的是「starting from FY{base} "
                 "pro-rated on a 12 month basis」，即把 TOM FORD FASHION 视作全年并表之后的 "
                 f"FY{base}，而公司从未印出那个数。本图用公布的 FY{base} 作基数。"
                 "对收入而言这个替代基数只会偏低（并表前那几个月的收入不可能为负），"
                 "所以图上的收入增速是<b>上界</b>，真实差距只会更大；"
                 "对 Adjusted EBIT 则无法判断方向，因为并表前那几个月的利润可正可负。"
                 f"<b>这组目标已经不是公司的现行目标</b>：{new['set_on']} 的 FY{lived} 业绩新闻稿以"
                 "「To reflect the current business environment」为由，把中期目标换成了 "
                 f"{new['year']} 年的绝对区间（下一张图），所以它在任上只报过 FY{lived} 这一年。"),
        "src_extra": ("目标原文取自 2023-12-05 资本市场日新闻稿；替换它的原文取自 "
                      f"{new['set_on']} 的 FY{lived} 业绩新闻稿「Mid-term targets」段；"
                      "实际值按本页年度序列现算（D）。"),
    }

    last = max(y for y in a["years"] if fy("revenue", y) is not None
               and fy("adjusted_ebit", y) is not None)
    left = new["year"] - last
    if left <= 0:
        raise ValueError(f"the {new['year']} targets are settled by FY{last}: "
                         "replace this chart with their settlement")
    need = [(cagr(fy("revenue", last), bound_rev * 1000, left),
             cagr(fy("adjusted_ebit", last), bound_ebit * 1000, left))
            for bound_rev, bound_ebit in zip(new["revenue_eur_m"], new["adjusted_ebit_eur_m"])]
    first_live = int(new["set_on"][:4])
    live_years = list(range(first_live, last + 1))
    groups = [{"name": f"FY{y} 实际同比", "color": ACTUAL_COLORS[k % len(ACTUAL_COLORS)],
               "values": rounded([pct(fy("revenue", y), fy("revenue", y - 1)),
                                  pct(fy("adjusted_ebit", y), fy("adjusted_ebit", y - 1))], 1)}
              for k, y in enumerate(live_years)]
    h = s["half"]
    i, j = view["i"], view["prior"]
    half_growth = (pct(h["revenue"][i], h["revenue"][j]),
                   pct(h["adjusted_ebit"][i], h["adjusted_ebit"][j]))
    half_after = int(view["half"][:4]) > last
    if half_after:
        groups.append({"name": f"{half_cn(view['half'])}同比", "color": "MBLUE",
                       "values": rounded(list(half_growth), 1)})
    groups += [
        {"name": f"FY{last} → {new['year']} 到区间下沿所需年复合 D", "color": "GOLD",
         "values": rounded(list(need[0]), 1)},
        {"name": "到区间上沿所需年复合 D", "color": "RED", "values": rounded(list(need[1]), 1)},
    ]
    first_year_fell = (first_live in live_years
                       and fy("revenue", first_live) < fy("revenue", first_live - 1)
                       and fy("adjusted_ebit", first_live) < fy("adjusted_ebit", first_live - 1))
    fell = groups[0]["values"] if first_year_fell else None
    faster = [name for name, got, wanted in (("收入", half_growth[0], need[0][0]),
                                               ("Adjusted EBIT", half_growth[1], need[0][1]))
              if got >= wanted]
    pace = ("两条都快于下沿所需的年增速" if len(faster) == 2 else
            f"{faster[0]}快于下沿所需，另一条慢于所需" if faster else
            "两条都慢于下沿所需的年增速")
    reaffirmed = mt["reaffirmed_in"]
    current = {
        "ref": "EX_TARGET_2027",
        "kind": "grouped_bars",
        "title": (f"{new['year']} 年目标（{new['set_on']} 更新）：收入 {_span(new['revenue_eur_m'])}、"
                  f"Adjusted EBIT {_span(new['adjusted_ebit_eur_m'])} —— 从 FY{last} 出发，"
                  f"下沿要求收入年增 {num(need[0][0])}%、Adjusted EBIT 年增 {num(need[0][1])}%"),
        "xlabels": ["集团收入", "集团 Adjusted EBIT"],
        "groups": groups,
        "bar_labels": True,
        "fmt": "pct1", "label_fmt": "pct1",
        "ylab": "增速 %",
        "note": (f"原文：「{new['wording']}」。"
                 + (f"目标定下之后的第一个完整年度 FY{first_live}，收入与 Adjusted EBIT 都比上一年少"
                    f"（{signed(fell[0])}、{signed(fell[1])}）。" if fell else "")
                 + (f"{half_cn(view['half'])}收入同比 {signed(half_growth[0])}、Adjusted EBIT "
                    f"{signed(half_growth[1])}，{pace}（半年同比与年复合不是同一个量，只看方向）。"
                    if half_after else "")
                 + f"公司在 {'、'.join(reaffirmed)} {cn_count(len(reaffirmed))}份业绩新闻稿里写过"
                 f"仍以「2027 年目标」为准，{cn_count(len(reaffirmed))}次都没有重述数字。"),
        "src_extra": (f"目标原文取自 {new['set_on']} 的 FY{lived} 业绩新闻稿；所需年复合 = "
                      f"（区间端点 ÷ FY{last} 实际）开 {left} 次方 − 1（D）。"),
    }
    return [old, current]


# ── section three: what the current analysis asks the next disclosures ──────
QUARTER_LABEL = re.compile(r"^\d{4}Q[1-4]$")


def next_entries(s: dict, view: dict, nk: dict) -> list[dict]:
    """The quantified thresholds, each with the reading it is judged on.

    A reading that is arithmetic on other figures is computed here and must not
    also be typed into the block; one that is a printed figure (an organic rate,
    a headroom from a note) is typed with its filing. The gap line is written on
    the company's two printed rates, so it is their difference -- the reported
    rate the series would give (10.29% for Q2 2026) is not the one the company
    printed (10.3%), and the owner's rule is the printed one. Either way the
    reading has to be this page's own latest period, or the block is last half's.
    """
    q = s["quarterly"]

    def reported_growth(label: str) -> float:
        k = q["periods"].index(label)
        return pct(q["revenue_eur_k"][k], q["revenue_eur_k"][k - 4])

    computed = {"fx_gap": lambda e: e["reported"] - e["organic"]}
    out = []
    for e in nk["quantified"]:
        wanted = view["latest_quarter"] if QUARTER_LABEL.match(e["reading"]) else s["latest"]["period_end"]
        if e["reading"] != wanted:
            raise ValueError(f"series block `next_kpi` reads `{e['id']}` at {e['reading']!r}, "
                             f"but this page's latest reading is {wanted!r}: update it with the roll")
        if "reported" in e and round(reported_growth(e["reading"]), 1) != e["reported"]:
            raise ValueError(f"`next_kpi.{e['id']}` says the company printed {e['reported']}% for "
                             f"{e['reading']}, but the series gives {reported_growth(e['reading']):.2f}%")
        if e["id"] in computed:
            if "current" in e:
                raise ValueError(f"`next_kpi.{e['id']}` is computed from its printed legs; "
                                 "remove its typed value")
            out.append({**e, "current": computed[e["id"]](e)})
        else:
            if "current" not in e:
                raise ValueError(f"`next_kpi.{e['id']}` has no reading and no way to compute one")
            out.append(dict(e))
    return out


def second_halves(s: dict, before: int) -> tuple[list[str], list[float]]:
    """Every second half on record before `before`: FY minus H1 (D).

    The earliest first half any filing prints is the F-1's, so the record
    starts there, a year before this series' own half axis does.
    """
    h, a = s["half"], s["annual"]
    pre = s["pre_listing_half"]
    first = {pre["period"]: pre["adjusted_ebit"]}
    first.update({p: v for p, v in zip(h["periods"], h["adjusted_ebit"])
                  if p.endswith("H1") and v is not None})
    labels, values = [], []
    for year in range(int(pre["period"][:4]), before):
        full = a["adjusted_ebit"][a["years"].index(year)] if year in a["years"] else None
        if full is None or f"{year}H1" not in first:
            continue
        labels.append(f"{year}H2")
        values.append(full - first[f"{year}H1"])
    return labels, values


def next_charts(s: dict, view: dict, nk: dict) -> tuple[list[dict], list[dict]]:
    entries = next_entries(s, view, nk)
    fy = nk.get("full_year")
    safe = [e for e in entries if headroom(e["direction"], e["threshold"], e["current"]) >= 0]
    count = len(entries) + (1 if fy else 0)
    gap = next((e for e in entries if e["id"] == "fx_gap"), None)
    tb = next((e for e in entries if e["id"] == "tb_headroom"), None)
    overview = headroom_exhibit(
        (f"下季 {count} 条阈值：有当前读数的 {len(entries)} 条"
         + ("都在安全侧" if len(safe) == len(entries) else f"里 {len(entries) - len(safe)} 条已越线")
         + (f"；{fy['metric']} 那条要等 {fy['settles_with']}" if fy else "")),
        entries, "current",
        ("正值 = 仍在安全侧。"
         + (f"「{gap['metric']}」是合取条件：差超过 {minus_sign(unit_text(gap['unit'], gap['threshold']))} "
            f"且有机增速不高于 {gap['organic_ceiling']:.0f}% 才算触发，本季有机 {gap['organic']:.1f}%。"
            if gap else "")
         + (f"减值余量 {unit_text(tb['unit'], tb['current'])} 对应商誉 {eur_m(tb['goodwill_eur_k'])} "
            f"加无限期品牌 {eur_m(tb['brand_eur_k'])}；公司自己的敏感性表里 WACC 上调 100bp，"
            f"余量就变成 {unit_text(tb['unit'], tb['headroom_if_wacc_plus_100bp_eur_m'])}。"
            if tb else "")),
        src_extra=("阈值为本地研究设定（本季分析稿第 8 节），不是公司指引。有机增速是公司印出的数，"
                   "本站没有接入按季的有机增速序列，所以这几条只有总览、没有历史线；"
                   "各条的出处列在核对抽屉的阈值表里。"),
    )
    overview["ref"] = "EX_NEXT"
    charts = [overview]
    if fy:
        h = s["half"]
        year = fy["year"]
        if f"{year}H1" not in h["periods"] or f"{year}H2" in h["periods"]:
            raise ValueError(f"series block `next_kpi.full_year` is for FY{year}, but the half record "
                             f"ends at {h['periods'][-1]}: update it with the roll")
        first = h["adjusted_ebit"][h["periods"].index(f"{year}H1")]
        need_bear = fy["bear_below_eur_m"] * 1000 - first
        need_bull = fy["bull_from_eur_m"] * 1000 - first
        labels, values = second_halves(s, year)
        best = max(range(len(values)), key=lambda k: values[k])
        from_f1 = labels[0][:4] == s["pre_listing_half"]["period"][:4]
        charts.append({
            "ref": "EX_NEXT_FY",
            "kind": "lines",
            "title": (f"{fy['metric']}：下季阈值 {eur_m(fy['bear_below_eur_m'] * 1000, 0)}，"
                      f"当前上半年 {eur_m(first)} —— 下半年要做到 {eur_m(need_bear)}"
                      + ("，比此前任何一个下半年都高" if need_bear > values[best] else "")),
            "xlabels": labels,
            "series": [
                {"name": "下半年 Adjusted EBIT（全年 − 上半年 D）", "color": "NAVY",
                 "values": rounded(values)},
                {"name": f"全年 {eur_m(fy['bear_below_eur_m'] * 1000, 0)} 所需的下半年（安全侧在上方）",
                 "color": "RED", "values": [round(need_bear, 6)] * len(labels)},
                {"name": f"全年 {eur_m(fy['bull_from_eur_m'] * 1000, 0)} 所需的下半年", "color": "GOLD",
                 "values": [round(need_bull, 6)] * len(labels)},
            ],
            "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
            "end_label": True,
            "ylab": "€ 千（下半年）",
            "note": (f"阈值是全年的：{fy['trigger']}。上半年已经报出 {eur_m(first)}，两条线就是"
                     "全年阈值减去上半年之后、下半年必须做到的数。"
                     f"此前最高的下半年是 {labels[best]} 的 {eur_m(values[best])}。"
                     "下半年由全年减上半年得到（D）"
                     + (f"；{labels[0]} 用到的上半年取自 F-1，那是任何申报里印出的第一个半年" if from_f1 else "")
                     + "。"),
            "src_extra": ("阈值为本地研究设定（本季分析稿第 8 节），不是公司指引；"
                          "全年与上半年 Adjusted EBIT 取自各期业绩新闻稿与 F-1。"),
        })
    return charts, entries


def next_table(s: dict, nk: dict, entries: list[dict], n: int) -> dict:
    rows = [[e["metric"], e["trigger"], minus_sign(unit_text(e["unit"], e["threshold"])),
             minus_sign(unit_text(e["unit"], e["current"])),
             minus_sign(f"{headroom(e['direction'], e['threshold'], e['current']):+.1f}%"),
             e["reading"], e["source"]]
            for e in entries]
    fy = nk.get("full_year")
    if fy:
        h = s["half"]
        first = h["adjusted_ebit"][h["periods"].index(f"{fy['year']}H1")]
        rows.append([fy["metric"], fy["trigger"],
                     f"{eur_m(fy['bear_below_eur_m'] * 1000, 0)} / {eur_m(fy['bull_from_eur_m'] * 1000, 0)}",
                     f"上半年 {eur_m(first)}", "—", fy["settles_with"],
                     "全年减上半年（D），见第三节的下半年那张图"])
    return {
        "n": n,
        "title": "下季阈值与当前读数（阈值原文取自本季分析稿第 8 节）",
        "headers": ["指标", "触发条件", "阈值", "当前", "余量 D", "读数期间", "当前值出处"],
        "rows": rows,
    }


# ── the page ─────────────────────────────────────────────────────────────────
def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    view = period_view(staging)
    h = staging["half"]
    i = view["i"]
    margin = h["adjusted_ebit"][i] / h["revenue"][i] * 100
    last = len(staging["quarterly"]["periods"]) - 1
    return [f"Revenues {eur_m(view['revenue'])}",
            f"Adjusted EBIT 利润率 {num(margin)}%",
            f"DTC 占品牌收入 {num(dtc_share(staging, last))}%"]


def build_payload(staging: dict) -> dict:
    s = staging
    view = period_view(s)
    half = view["half"]
    period = display_period(half)
    latest = latest_block(s, period=period, period_end=s["latest"]["period_end"],
                          release_date=s["latest"]["release_date"])
    release = f"{view['year']} 年{view['word']}业绩"
    if not any(source["label"].startswith(release) for source in s["sources"]):
        raise ValueError(f"series `sources` has no entry for the {release} release: add it with the roll")
    put = stamped_block(s, "half_story", period)
    nk = stamped_block(s, "next_kpi", period)
    if nk is None:
        raise ValueError("series block `next_kpi` is required every half: the page's third part "
                         "is the current analysis's thresholds")
    # Last quarter's analysis is optional: a half with no earlier analysis has
    # nothing of it to settle, and the section says so instead.
    closure = stamped_block(s, "followup_closure", period)
    prior = stamped_block(s, "prior_kpi_settlement", period)

    # The four parts, in the order the site reads them. Each list holds the
    # exhibit dicts themselves, so numbering them below numbers them here too.
    prior_ex, prior_list = prior_charts(s, view, prior) if prior else ([], [])
    settled_ex = ([closure_chart(closure, view)] if closure else []) + prior_ex + target_charts(s, view)
    highlight_ex = period_charts(s, view, put)
    next_ex, next_list = next_charts(s, view, nk)
    routine_ex = channel_charts(s, view) + brand_charts(s, view) + geography_charts(s, view)
    exhibits = number_exhibits(settled_ex + highlight_ex + next_ex + routine_ex)
    resolve_exhibit_refs(exhibits)

    h, q, se, st = s["half"], s["quarterly"], s["segment_adjusted_ebit"], s["stores"]
    i, j = view["i"], view["prior"]
    P = q["periods"]
    first_table = exhibits[-1]["n"] + 1

    tables = [{
        "n": first_table,
        "title": "半年合并损益（公司披露值，下半年为全年减上半年 D）",
        "headers": ["期间", "来源", "收入", "毛利", "经营利润", "Adjusted EBIT",
                    "Adjusted EBIT 利润率 D", "期间利润"],
        "rows": [[h["periods"][k],
                  "公司印出" if h["printed"][k] else "全年减上半年 D",
                  eur_m(h["revenue"][k]) if h["revenue"][k] is not None else "—",
                  eur_m(h["gross_profit"][k]) if h["gross_profit"][k] is not None else "—",
                  eur_m(h["operating_profit"][k]) if h["operating_profit"][k] is not None else "—",
                  eur_m(h["adjusted_ebit"][k]) if h["adjusted_ebit"][k] is not None else "—",
                  f"{num(h['adjusted_ebit'][k] / h['revenue'][k] * 100, 2)}%"
                  if None not in (h["adjusted_ebit"][k], h["revenue"][k]) else "—",
                  eur_m(h["profit"][k]) if h["profit"][k] is not None else "—"]
                 for k in range(len(h["periods"]))],
    }, {
        "n": first_table + 1,
        "title": "单季收入、渠道与地区（每一格都是公司印出的单季数）",
        "headers": ["期间", "首次印出它的发布", "收入", "DTC", "批发品牌",
                    "DTC 占品牌收入 D", "EMEA", "美洲", "大中华区", "亚太其余", "同比 D"],
        "rows": [[P[k], q["first_printed_by"][k],
                  eur_m(q["revenue_eur_k"][k]),
                  eur_m(q["channel"]["dtc"][k]), eur_m(q["channel"]["wholesale_branded"][k]),
                  f"{num(dtc_share(s, k))}%",
                  eur_m(q["geography"]["emea"][k]), eur_m(q["geography"]["americas"][k]),
                  eur_m(q["geography"]["greater_china"][k]), eur_m(q["geography"]["rest_of_apac"][k]),
                  "—" if k < 4 else signed(pct(q["revenue_eur_k"][k], q["revenue_eur_k"][k - 4]))]
                 for k in range(len(P))],
    }, {
        "n": first_table + 2,
        "title": "分部 Adjusted EBIT 与集团费用（公司披露值）",
        "headers": ["期间", "Zegna", "Thom Browne", "TOM FORD FASHION", "Corporate",
                    "分部间抵销", "集团合计"],
        "rows": [[se["periods"][k]]
                 + [eur_m(se[key][k]) if se[key][k] is not None else "—"
                    for key in ("zegna", "thom_browne", "tff", "corporate", "eliminations", "total")]
                 for k in range(len(se["periods"]))],
    }, {
        "n": first_table + 3,
        "title": "门店数与净财务状况（各期末）",
        "headers": ["日期", "ZEGNA 直营", "Thom Browne 直营", "TOM FORD FASHION 直营",
                    "集团直营", "集团批发门店", "净负债／（净现金）"],
        "rows": [[d,
                  *[str(st["dtc"][b][k]) if st["dtc"][b][k] is not None else "—"
                    for b in ("ZEGNA", "Thom Browne", "TOM FORD FASHION", "Group")],
                  str(st["wholesale_doors"]["Group"][k]),
                  (eur_m(s["net_financial_position"]["net_debt_eur_k"][
                      s["net_financial_position"]["dates"].index(d)])
                   if d in s["net_financial_position"]["dates"] else "—")]
                 for k, d in enumerate(st["dates"])],
    }]
    tables.append(census_table(s, first_table + len(tables)))
    tables.append(restatement_table(s, first_table + len(tables)))
    if closure:
        tables.append(closure_table(closure, first_table + len(tables)))
    if prior:
        tables.append(prior_table(prior, prior_list, first_table + len(tables)))
    tables.append(next_table(s, nk, next_list, first_table + len(tables)))
    tables.append(ai_capex_cycle_table(first_table + len(tables)))

    g = lambda key: h[key][i]
    p = lambda key: h[key][j]
    margin = g("adjusted_ebit") / g("revenue") * 100
    margin_prior = p("adjusted_ebit") / p("revenue") * 100
    profit_growth = pct(g("profit"), p("profit"))
    share_now = dtc_share(s, len(P) - 1)
    share_first = dtc_share(s, 0)
    rows = s["republication_census"]["rows"]
    total_row = next(r for r in rows if r["row"] == "total" and r["kind"] == "segment")
    changed_rows = [r for r in rows if r["periods_changed"] > 0]
    ratio = se["zegna"][-1] / se["total"][-1] * 100

    headline = (f"{half_cn(half)}收入 {eur_m(view['revenue'])}，同比 "
                f"{signed(pct(view['revenue'], view['revenue_prior']))}；"
                f"Adjusted EBIT {eur_m(g('adjusted_ebit'))}、利润率 {num(margin)}%"
                f"（上年同期 {num(margin_prior)}%），"
                f"而期间利润 {eur_m(g('profit'))}、同比 {signed(profit_growth)} —— "
                "落差整段发生在经营利润之下"
                + (f"，其中少数股东看跌期权（以 {put['brand']} 为主）的重估与汇兑两项就造成 "
                   f"{eur_m(put['fair_value_swing_eur_k'] + put['fx_swing_eur_k'])} 的不利同比变动"
                   if put else "")
                + "。"
                f"同期 DTC 占品牌收入升到 {num(share_now)}%，"
                f"Zegna 一个分部的 Adjusted EBIT 相当于集团的 {num(ratio)}%。")

    cards = [
        '<article><span>本期</span><b>经营线全好，利润掉了四成</b>'
        f'<p>收入 {signed(pct(view["revenue"], view["revenue_prior"]))}、'
        f'毛利 {signed(pct(g("gross_profit"), p("gross_profit")))}、'
        f'经营利润 {signed(pct(g("operating_profit"), p("operating_profit")))}、'
        f'Adjusted EBIT {signed(pct(g("adjusted_ebit"), p("adjusted_ebit")))}，'
        f'期间利润 {signed(profit_growth)}。'
        + (f'少数股东看跌期权（以 {put["brand"]} 为主）的公允价值与汇兑两项，'
           '合计比经营线以下的全部净变动还大。'
           if put else '')
        + '</p></article>',
        '<article><span>结构</span><b>渠道换完了，收入没动</b>'
        f'<p>DTC 占品牌收入从 {num(share_first)}% 到 {num(share_now)}%，'
        f'直营门店 {st["dtc"]["Group"][0]} → {st["dtc"]["Group"][-1]} 家，'
        f'批发门店 {st["wholesale_doors"]["Group"][0]} → {st["wholesale_doors"]["Group"][-1]} 家；'
        f'集团收入 FY{s["annual"]["years"][-3]} 到 FY{s["annual"]["years"][-1]} 只变了 '
        f'{signed(pct(s["annual"]["revenue"][-1], s["annual"]["revenue"][-3]), 2)}。</p></article>',
        '<article><span>口径</span><b>'
        + ('合计从没改过，拆分改过' if total_row["periods_changed"] == 0 else '合计也改过')
        + '</b>'
        f'<p>集团合计收入被重复公布 {total_row["periods_republished"]} 次，'
        f'{total_row["periods_changed"]} 次改动；它下面'
        f'{cn_count(len(rows) - 1)}条线里有'
        f'{cn_count(len(changed_rows))}条改过，'
        f'{cn_count(len(s["restatements"]))}处重述里只有'
        f'{cn_count(sum(1 for r in s["restatements"] if r.get("footnoted_by_the_company")))}'
        '处被公司说明过。</p></article>',
    ]

    mt = s["medium_term_targets"]
    fy = nk.get("full_year")
    sections = [
        {"id": "settled", "title": "一、上季跟踪指标兑现了吗",
         "description": (
             (f"先结算上季分析稿（{(closure or prior)['set_in']} 营收那份）留下的东西："
              + "、".join(part for part in (
                  f"{len(closure['items'])} 条待验证问题" if closure else "",
                  f"{len(prior['quantified'])} 条量化阈值" if prior else "") if part)
              + "，都在本期到期；"
              if closure or prior else
              "本期之前没有可结算的本地分析稿，本节只结算公司自己给出的目标；")
             + f"再看公司自己的中期目标兑现到哪一步 —— {mt['set_on']} 的年复合目标只走完一年，"
             f"就在 {mt['targets_2027']['set_on']} 被换成 {mt['targets_2027']['year']} 年的绝对区间。"),
         "exhibits": settled_ex},
        {"id": "quarter_highlights", "title": "二、本季重点",
         "description": (f"{half_cn(half)}从收入到利润五个口径的同比方向不一致：先把落差定位到损益表的"
                         "哪一段，再看那一段里最大的一笔是什么。"),
         "exhibits": highlight_ex},
        {"id": "next_quarter", "title": "三、下季要跟踪什么",
         "description": (f"本季分析稿第 8 节留给下一次披露的 {len(next_list) + (1 if fy else 0)} 条阈值："
                         f"有当前读数的 {len(next_list)} 条统一用「距阈值余量」表示"
                         + (f"；{fy['metric']} 要等全年业绩才能结算，单独画出下半年必须做到的数"
                            if fy else "")
                         + "。"),
         "exhibits": next_ex},
        {"id": "routine", "title": "四、长期常规跟踪",
         "description": (f"Zegna 专属的长期序列：{P[0]} 起的单季收入、渠道结构与门店，"
                         "分部利润与 Thom Browne 的单店产出，以及换过一次口径的地区收入。"),
         "exhibits": routine_ex},
    ]

    geo_block = q["geography"]
    fold = q["brand"]["fold_overlap"]
    both = geo_block["periods_on_both_bases"]
    releases = [x for x in s["sources"] if re.search(r"(营收|业绩)新闻稿", x["label"])]
    pre = s["pre_listing_half"]
    headrooms = {ex.get("ref"): ex["n"] for ex in exhibits if ex["kind"] == "diverging_bars"}
    notes = [
        "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
    ]
    if "EX_PRIOR" in headrooms:
        notes.append(
            f"Exhibit {headrooms['EX_PRIOR']} 与 Exhibit {headrooms['EX_NEXT']} 的阈值是本地研究设定"
            "（上季与本季的两份分析稿），不是公司指引，也不构成评级或投资建议；「距阈值余量」统一为正值代表安全侧，"
            "实际值与当前读数一律取公司披露值或据其自算。")
    notes += [
        "公司在荷兰注册、在纽约证券交易所上市，按 IFRS 以欧元列报，财年即自然年。它是美国证券法下的外国私人发行人：年度报告为 20-F，季度营收公告与半年度业绩一律以 6-K 报送。因此与本站其他欧洲奢侈品公司不同，它的全部原件都在 EDGAR 上，本页 sources 里逐份直链。",
        "披露节奏决定了本页两条时间轴的形状：收入按单季公布，一年四次，每次都带品牌、渠道、地区与分部拆分；完整损益表一年只有两次，在半年与全年。所以收入轴是真正的季度轴，上面没有一格是相减出来的；利润轴是半年轴，下半年由全年减上半年得到，表里逐行标明。本页不把这两条轴画在同一张图上。",
        f"季度记录的下限是 {P[0]}，而且不可能更早：公司 {s['company']['listed_on']} 才完成上市，此前没有公布过任何季度数字。本页的 {P[0]} 到 {P[3]} 四个季度，都是作为 2022 年各份发布的上年同期列才第一次被印出来的，表里逐格标明是哪一份。为确认这一点，除{cn_count(len(releases))}份业绩与营收新闻稿之外还读了 F-4、F-1 与 FY2021 的 20-F：三份都在正文里谈到季度，但都没有列出任何季度财务表。",
        f"半年的下限比季度早一年：F-1 印出了 {half_cn(pre['period'])}的收入、期间利润与 Adjusted EBIT，这是任何申报里的第一个半年数（F-4 里没有任何半年表）。本页的半年表从 {h['periods'][0]} 起；只有第三节那张下半年的图用到了这个更早的半年，以便从 {pre['period'][:4]} 年下半年算起（全年减上半年 D）。",
        f"地区口径在 {geo_block['basis_change_release']} 的发布里换过一次：此前分 EMEA / 北美 / 拉美 / 亚太（亚太下挂大中华区与日本），此后分 EMEA / 美洲 / 大中华区 / 亚太其余。这次改动在文字里没有任何说明，唯一的证据是算术 —— 美洲等于北美加拉美，亚太其余等于亚太减大中华区。两套口径同时被印出过的期间有{cn_count(both)}个，两条恒等式在每一个上都逐欧元相等，本页因此把换口径之前的季度按新口径还原并标为自算。意大利、美国与日本原本是旧表下的「其中」行，随旧表一起停在 2023 年第四季度，本页不向后补。",
        "产品线里的「其他」也被并过两次，都没有文字说明：Agnona 在 2023 年第一季度的发布里并入，第三方品牌在 2024 年第一季度的发布里并入。本页按公司最后采用的口径发布，换口径之前的季度由首次印出的几行相加还原；"
        + f"两次并线各有{cn_count(len(fold['third_party_brands']['periods']))}个和{cn_count(len(fold['agnona']['periods']))}个期间两套口径都印过，相加的结果与公司自己印出的合并行在每一个上都相等，原值列在 series 的 fold_overlap 里。",
        "批发口径同样分两段：2023 年第一季度起公司把「批发品牌」单列，此前的「批发合计」还含面料、第三方品牌与 Agnona。本页统一用只含三个品牌的口径，早期季度由同一份发布里的各品牌批发行相加得到。",
        "分部利润有一处必须先说明才能看：2022 年上半年之前没有 Corporate 这一行，集团费用整体计在 Zegna 分部里。FY2022 业绩发布第一次把它拆出来，并重述了 2022 年上半年；那是唯一一个两套口径都公布过的半年，差额恰好等于新设的 Corporate 行。2021 年上半年只有旧口径，本页不把它画进分部利润的时间轴。",
        "唯一被公司用脚注说明过的重述是 Pelletteria Tizeta：2024 年的发布把它从 Zegna 分部调入 TOM FORD FASHION 分部，并重述了 2023 年第二、第三季度的分部收入与抵销行，集团合计不变。有一处后果值得记下来：2023 年第四季度按「全年减前九个月」去算，必须用重述后的前九个月才能等于公司印出的第四季度，用首次公布的前九个月会少算一千二百八十二万六千欧元。",
        "Adjusted EBIT 是公司自定义的非 IFRS 指标，定义为税前利润加回金融收支、汇兑损益与权益法结果，再剔除管理层认为不反映经营的项目。本页照用公司的口径与公司印出的值，不自行调整剔除项；各期剔除项的构成在业绩发布里逐项列出。",
        (f"本页不发布市场一致预期、评级、目标价与估值。第一节结算的中期目标是公司自己给出的：{mt['set_on']} "
         f"资本市场日的年复合目标，以及 {mt['targets_2027']['set_on']} 的 FY"
         f"{mt['targets_2027']['results_year_of_the_release']} 业绩新闻稿换上的 {mt['targets_2027']['year']} 年区间；"
         "第三节的阈值是本地研究设定（本季分析稿），不是公司指引。本页只做结算，不给出自己的预测。"),
        "本页只发布公司披露值与可复算的简单派生值；D 标记代表 Derived / 自算。",
        f"本页已知未接入：{quarter_cn(view['latest_quarter'])}之后的任何数据"
        + (f"；另外 {quarter_cn(view['latest_quarter'])} 已有营收披露但尚无损益，"
           "本页的利润口径因此停在半年"
           if view["latest_quarter"] not in view["quarters"] else "")
        + "；按季的有机增速（公司每季都印，本站没有接入序列，第三节的有机增速阈值因此只有当前读数、没有历史线）。",
        "核对抽屉最后那张「AI capex 循环」是全站共用的跨页对照块，在每一页都逐字节相同，不是对本公司的判断。它追的是四家云厂现金资本开支到 NVDA 数据中心收入再到 TSM 晶圆这条链，本公司不在这条链的任何一环上；它在折叠的抽屉里，不参与本页的论证。",
    ]

    return {
        "schema_version": "quarterly-dashboard/zgn-v1",
        "page": {"slug": "zgn", "language": "zh-CN"},
        "company": {"ticker": "ZGN", "name": "Ermenegildo Zegna N.V.",
                    "group": "luxury_brands", "accounting_standard": "IFRS"},
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · ZGN",
        "title": f"Ermenegildo Zegna N.V. (ZGN)：{view['year']} 年{view['word']}业绩仪表盘",
        "subtitle": (f"截至 {latest['period_end']} · 发布 {latest['release_date']} · IFRS · 欧元列示 · "
                     "自然年财年 · 收入按单季公布、完整损益一年两次 · "
                     "数据来自公司 6-K 新闻稿、半年报与 20-F"),
        "headline": headline,
        "brief": (f'<h4>本期{cn_count(len(cards))}条主线</h4><div class="takeaway-grid">'
                  + "".join(cards) + '</div>'),
        "source": ('Source: <a href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany'
                   '&CIK=0001877787&type=6-K&dateb=&owner=include&count=40" rel="noopener">'
                   'Ermenegildo Zegna N.V. 在 SEC EDGAR 的申报（CIK 1877787）</a>。'
                   '公司为外国私人发行人，年度报告为 20-F，期间披露以 6-K 报送。'),
        "source_url": ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
                       "&CIK=0001877787&type=6-K&dateb=&owner=include&count=40"),
        "source_links": s["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": sections,
        "tables": tables,
        "notes": notes,
        "footer": ("Ermenegildo Zegna quarterly results · 数据来自公司公开披露与透明自算 · "
                   "仅供研究，不构成投资建议"),
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "zgn.js"), payload, "zgn")
    shell_dir = ROOT / "zgn"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("ZGN", "zgn"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"ZGN page: {charts} charts in {len(payload['sections'])} sections "
          f"+ {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
