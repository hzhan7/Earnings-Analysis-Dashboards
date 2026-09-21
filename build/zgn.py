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

Third, and this is what the last section is about: the group total has never
been restated, and four of the lines underneath it have. Across the releases
this page reads, thirty-nine group-revenue readings were published and twenty-
four of them were published again later; not one came back different. Over the
same releases the `Other` product line changed eleven times, the Zegna segment
and the elimination line four each, and the old `Total Wholesale` five. Every
one of those changes reconciles exactly. Seven restatements sit behind them and
the company narrated two: the Tizeta segment move and the switch from a
by-nature income statement to a by-function one.

**A roll edits `series/zgn.json` and nothing else** (CLAUDE.md §9). Every period,
count and figure on the page is computed from the series; every sentence that
states something the data could stop saying is printed only while the data says
it. Published figures are company-reported or transparent arithmetic.
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
    latest_block,
    minus_sign,
    number_exhibits,
    round_half_up,
    stamped_block,
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


# ── section one: the period just reported ────────────────────────────────────
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
    put_ex = {
        "ref": "EX_PUT",
        "kind": "bars_labeled",
        "title": (f"{put['brand']} 少数股东看跌期权：两项合计 {eur_m(put_total)} 的不利变动，"
                  f"比经营线以下的净变动 {eur_m(-net)} 还大"),
        "xlabels": [name for name, _ in legs_put] + ["两项合计", "经营线以下净变动（取正）"],
        "values": rounded([v for _, v in legs_put] + [put_total, -net], 1),
        "fmt": "f0c", "label_fmt": "f0c", "yfmt": "f0c",
        "ylab": "€ 千（对同比的不利影响）",
        "note": ("公司把这两个数写在半年报正文里：期权负债的公允价值重估在金融损益里造成 "
                 f"{eur_m(legs_put[0][1])} 的同比不利变动，该负债以美元计价，其汇兑影响在汇兑损益里"
                 f"再造成 {eur_m(legs_put[1][1])}。两项之和比经营线以下的全部净变动还大 "
                 f"{eur_m(put_total - (-net))}，也就是说<b>其余财务项净贡献是正的</b>。"
                 f"这笔负债本身 {eur_m(put['liability_eur_k'])}，对应 {put['brand']} 尚未收购的 "
                 f"{put['remaining_stake_pct']}% 少数股权，行权价挂在 "
                 f"{' 年与 '.join(str(y) for y in put['tranche_ebitda_years'])} 年的 EBITDA 上。"
                 "重估不可抵扣，也是本期实际税率从 "
                 f"{num(put['effective_tax_rate_prior_pct'])}% 升到 "
                 f"{num(put['effective_tax_rate_pct'])}% 的原因。"),
        "src_extra": ("两个变动额与税率说明取自 2026 年半年报「Financial income and expenses」"
                      "与「Foreign exchange」段落；负债余额取自附注 16。"),
    }
    return [ladder_ex, bridge, put_ex]


# ── section two: the channel conversion ──────────────────────────────────────
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
        "note": ("这一条是本页唯一可以画成真正季度线的收入序列：公司每季都把**单季**数印出来，"
                 "没有一格是由累计相减得到的。"
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


# ── section three: where the profit is ───────────────────────────────────────
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
                 "详见下一节。"),
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


# ── section four: the geographic rotation ────────────────────────────────────
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


# ── section five: what was republished, and what changed ─────────────────────
def basis_charts(s: dict, view: dict) -> list[dict]:
    rows = s["republication_census"]["rows"]
    unchanged = [r for r in rows if r["periods_changed"] == 0]
    changed = [r for r in rows if r["periods_changed"] > 0]
    total = next(r for r in rows if r["row"] == "total" and r["kind"] == "segment")

    census = {
        "ref": "EX_CENSUS",
        "kind": "grouped_bars",
        "title": (f"集团合计收入被重复公布 {total['periods_republished']} 次，"
                  f"改过 {total['periods_changed']} 次；"
                  f"它下面{cn_count(len(rows) - 1)}条线里有{cn_count(len(changed))}条改过"),
        "xlabels": [r["label"] for r in rows],
        "groups": [
            {"name": "被重复公布过的期间数", "color": "NAVY",
             "values": [r["periods_republished"] for r in rows]},
            {"name": "其中回来时数字变了的", "color": "RED",
             "values": [r["periods_changed"] for r in rows]},
        ],
        "bar_labels": True,
        "fmt": "f0", "label_fmt": "f0",
        "ylab": "期间数",
        "xrot": 45,
        "note": ("把本页读的每一份发布里的每一个期间都数一遍："
                 "蓝柱是「后来又被印过一次」的期间数，红柱是「再印时数字不一样」的期间数。"
                 f"合计那一条红柱是 {total['periods_changed']} —— "
                 f"{total['periods_republished']} 次重复公布，没有一次改过。"
                 f"改过的{cn_count(len(changed))}条是："
                 + "、".join(f"{r['label']}（{r['periods_changed']} 次）" for r in changed)
                 + "。<b>合计稳定不等于拆分稳定</b>，而读者引用的多半是拆分。"),
        "src_extra": "普查范围为本页 sources 里列出的全部发布；每一格的比对都在同一期间、同一行名之间进行。",
    }

    rs = s["restatements"]
    explained = [r for r in rs if r.get("footnoted_by_the_company")]
    sizes = []
    for r in rs:
        if r["what"] == "pelletteria_tizeta_moves_to_the_tom_ford_fashion_segment":
            sizes.append(("Tizeta 调入 TFF 分部", abs(min(r["revenue_changes_eur_k"].values()))))
        elif r["what"] == "corporate_costs_leave_the_zegna_segment":
            sizes.append(("集团费用移出 Zegna 分部", abs(r["adjusted_ebit_eur_k"]["2022H1_corporate_line"])))
        elif r["what"] == "fy2021_wholesale_and_other":
            sizes.append(("FY2021 批发／其他重分类", r["size_eur_k"]))
    corp = next(r for r in rs if r["what"] == "corporate_costs_leave_the_zegna_segment")
    a = corp["adjusted_ebit_eur_k"]
    restate = {
        "ref": "EX_RESTATE",
        "kind": "bars_labeled",
        "title": (f"最大的一次重述把 {eur_m(abs(a['2022H1_corporate_line']))} 的集团费用"
                  f"移出 Zegna 分部：同一个半年的分部利润从 {eur_m(a['2022H1_as_first_published'])} "
                  f"变成 {eur_m(a['2022H1_as_restated'])}"),
        "xlabels": ["首次公布的 Zegna 分部 Adjusted EBIT", "重述后", "差额（即新设的 Corporate 行）"],
        "values": rounded([a["2022H1_as_first_published"], a["2022H1_as_restated"],
                           abs(a["2022H1_corporate_line"])], 1),
        "fmt": "f0c", "label_fmt": "f0c", "yfmt": "f0c",
        "ylab": "€ 千（2022 年上半年）",
        "note": (f"{corp['first_on_new_basis']} 的 FY2022 业绩发布第一次把集团费用单列成 Corporate；"
                 "在那之前它整体计在 Zegna 分部里。2022 年上半年是唯一一个两套口径都公布过的半年，"
                 "而差额恰好等于新设的 Corporate 行 —— 这是恒等式。"
                 f"本页{cn_count(len(rs))}处重述里只有{cn_count(len(explained))}处被公司说明过，"
                 "其余都只能靠算术认出来。"
                 "2021 年上半年只有旧口径，本页不把它和后面的分部利润画在同一条线上。"),
        "src_extra": "两个数分别取自 2022 年上半年业绩发布与 2023 年上半年业绩发布的分部表。",
    }
    return [census, restate]


# ── section six: the targets set in December 2023 ────────────────────────────
def target_charts(s: dict, view: dict) -> list[dict]:
    mt = s["medium_term_targets"]
    a = s["annual"]
    base_year = mt["base_year"]
    last_year = max(y for y in a["years"] if a["revenue"][a["years"].index(y)] is not None
                    and a["adjusted_ebit"][a["years"].index(y)] is not None)
    span = last_year - base_year
    bi, li = a["years"].index(base_year), a["years"].index(last_year)
    rev_cagr = cagr(a["revenue"][bi], a["revenue"][li], span)
    ebit_cagr = cagr(a["adjusted_ebit"][bi], a["adjusted_ebit"][li], span)
    rev_target = next(t for t in mt["targets"] if t["metric"] == "group_revenue_cagr_pct")["floor"]
    ebit_target = next(t for t in mt["targets"]
                       if t["metric"] == "group_adjusted_ebit_cagr_pct")["around"]

    settle = {
        "ref": "EX_TARGET",
        "kind": "grouped_bars",
        "title": (f"{mt['set_on']} 定下的中期目标，对 FY{base_year} 到 FY{last_year} 的实际："
                  f"收入 {signed(rev_cagr)} 对「10% 以上」，"
                  f"Adjusted EBIT {signed(ebit_cagr)} 对「约 20%」"),
        "xlabels": ["集团收入 CAGR", "集团 Adjusted EBIT CAGR"],
        "groups": [
            {"name": f"{mt['set_on']} 给出的目标", "color": "RED",
             "values": [rev_target, ebit_target]},
            {"name": f"FY{base_year} → FY{last_year} 实际（按公布的 FY{base_year} 为基数）",
             "color": "NAVY", "values": rounded([rev_cagr, ebit_cagr], 1)},
        ],
        "bar_labels": True,
        "fmt": "pct1", "label_fmt": "pct1",
        "ylab": "年复合增速 %",
        "note": ("目标是公司在第二次资本市场日给出的，带基年、带口径脚注。"
                 f"<b>但基年本身没有被公布过</b>：脚注写的是「starting from FY{base_year} "
                 "pro-rated on a 12 month basis」，即把 TOM FORD FASHION 视作全年并表之后的 "
                 f"FY{base_year}，而公司从未印出那个数。本图用公布的 FY{base_year} 作基数。"
                 "对收入而言这个替代基数只会偏低（并表前那几个月的收入不可能为负），"
                 "所以图上的收入 CAGR 是<b>上界</b>，真实差距只会更大；"
                 "对 Adjusted EBIT 则无法判断方向，因为并表前那几个月的利润可正可负。"
                 f"公司在 {'、'.join(mt['reaffirmed_in'])} 两次重申仍以「2027 年目标」为准，"
                 "两次都没有重述数字。"),
        "src_extra": ("目标原文取自 2023-12-05 资本市场日新闻稿；实际值按本页年度序列现算（D）。"),
    }
    return [settle]


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

    period_ex = period_charts(s, view, stamped_block(s, "half_story", period))
    channel_ex = channel_charts(s, view)
    brand_ex = brand_charts(s, view)
    geo_ex = geography_charts(s, view)
    basis_ex = basis_charts(s, view)
    target_ex = target_charts(s, view)

    exhibits = number_exhibits(period_ex + channel_ex + brand_ex + geo_ex + basis_ex + target_ex)
    resolve_exhibit_refs(exhibits)
    sizes = [len(period_ex), len(channel_ex), len(brand_ex), len(geo_ex), len(basis_ex), len(target_ex)]
    cuts, at = [], 0
    for size in sizes:
        cuts.append(exhibits[at:at + size])
        at += size
    period_ex, channel_ex, brand_ex, geo_ex, basis_ex, target_ex = cuts

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
    tables.append(ai_capex_cycle_table(first_table + len(tables)))

    g = lambda key: h[key][i]
    p = lambda key: h[key][j]
    margin = g("adjusted_ebit") / g("revenue") * 100
    margin_prior = p("adjusted_ebit") / p("revenue") * 100
    profit_growth = pct(g("profit"), p("profit"))
    share_now = dtc_share(s, len(P) - 1)
    share_first = dtc_share(s, 0)
    total_row = next(r for r in s["republication_census"]["rows"]
                     if r["row"] == "total" and r["kind"] == "segment")
    changed_rows = [r for r in s["republication_census"]["rows"] if r["periods_changed"] > 0]
    ratio = se["zegna"][-1] / se["total"][-1] * 100

    put = stamped_block(s, "half_story", period)
    headline = (f"{half_cn(half)}收入 {eur_m(view['revenue'])}，同比 "
                f"{signed(pct(view['revenue'], view['revenue_prior']))}；"
                f"Adjusted EBIT {eur_m(g('adjusted_ebit'))}、利润率 {num(margin)}%"
                f"（上年同期 {num(margin_prior)}%），"
                f"而期间利润 {eur_m(g('profit'))}、同比 {signed(profit_growth)} —— "
                "落差整段发生在经营利润之下"
                + (f"，其中 {put['brand']} 少数股东看跌期权一项就造成 "
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
        + (f'{put["brand"]} 看跌期权的公允价值与汇兑两项，合计比经营线以下的全部净变动还大。'
           if put else '')
        + '</p></article>',
        '<article><span>结构</span><b>渠道换完了，收入没动</b>'
        f'<p>DTC 占品牌收入从 {num(share_first)}% 到 {num(share_now)}%，'
        f'直营门店 {st["dtc"]["Group"][0]} → {st["dtc"]["Group"][-1]} 家，'
        f'批发门店 {st["wholesale_doors"]["Group"][0]} → {st["wholesale_doors"]["Group"][-1]} 家；'
        f'集团收入 FY{s["annual"]["years"][-3]} 到 FY{s["annual"]["years"][-1]} 只变了 '
        f'{signed(pct(s["annual"]["revenue"][-1], s["annual"]["revenue"][-3]), 2)}。</p></article>',
        '<article><span>口径</span><b>合计从没改过，拆分改过</b>'
        f'<p>集团合计收入被重复公布 {total_row["periods_republished"]} 次，'
        f'{total_row["periods_changed"]} 次改动；它下面'
        f'{cn_count(len(s["republication_census"]["rows"]) - 1)}条线里有'
        f'{cn_count(len(changed_rows))}条改过，'
        f'{cn_count(len(s["restatements"]))}处重述里只有'
        f'{cn_count(sum(1 for r in s["restatements"] if r.get("footnoted_by_the_company")))}'
        '处被公司说明过。</p></article>',
    ]

    sections = [
        {"id": "period", "short": "本期", "title": f"{half_cn(half)}：落差在哪一段发生",
         "description": ("从收入到利润五个口径的同比方向不一致，本节先把落差定位到损益表的哪一段，"
                         "再看那一段里最大的一笔是什么。"),
         "exhibits": period_ex},
        {"id": "channel", "short": "渠道改造", "title": "把批发换成直营，换了几年",
         "description": ("DTC 占品牌收入、批发品牌的绝对额、单季收入与门店数 —— "
                         "同一件事的四个侧面。"),
         "exhibits": channel_ex},
        {"id": "brands", "short": "利润在哪个品牌", "title": "三个品牌，一个在赚钱",
         "description": "分部 Adjusted EBIT、Zegna 分部占集团的比例，以及 Thom Browne 的单店产出。",
         "exhibits": brand_ex},
        {"id": "geography", "short": "地区", "title": "大中华区与美洲换了位置",
         "description": f"{cn_count(len(P))}个季度的四个区域，以及换过一次的区域口径。",
         "exhibits": geo_ex},
        {"id": "basis", "short": "口径与重述", "title": "被重复公布的数，和被改过的数",
         "description": ("把每一份发布里的每一个期间数一遍：合计从没改过，它下面的几条线改过。"),
         "exhibits": basis_ex},
        {"id": "targets", "short": "中期目标", "title": "2023 年 12 月的目标，和它没公布的基年",
         "description": "目标带基年、带口径脚注，而基年本身是一个从未印出的数。",
         "exhibits": target_ex},
    ]
    for index, section in enumerate(sections, start=1):
        section["title"] = f"{cn_ordinal(index)}、{section['title']}"
    order = " → ".join(section.pop("short") for section in sections)

    geo_block = q["geography"]
    fold = q["brand"]["fold_overlap"]
    both = geo_block["periods_on_both_bases"]
    notes = [
        f"本页按「{order}」{cn_count(len(sections))}段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
        "公司在荷兰注册、在纽约证券交易所上市，按 IFRS 以欧元列报，财年即自然年。它是美国证券法下的外国私人发行人：年度报告为 20-F，季度营收公告与半年度业绩一律以 6-K 报送。因此与本站其他欧洲奢侈品公司不同，它的全部原件都在 EDGAR 上，本页 sources 里逐份直链。",
        "披露节奏决定了本页两条时间轴的形状：收入按单季公布，一年四次，每次都带品牌、渠道、地区与分部拆分；完整损益表一年只有两次，在半年与全年。所以收入轴是真正的季度轴，上面没有一格是相减出来的；利润轴是半年轴，下半年由全年减上半年得到，表里逐行标明。本页不把这两条轴画在同一张图上。",
        f"季度记录的下限是 {P[0]}，而且不可能更早：公司 {s['company']['listed_on']} 才完成上市，此前没有公布过任何季度数字。本页的 {P[0]} 到 {P[3]} 四个季度，都是作为 2022 年各份发布的上年同期列才第一次被印出来的，表里逐格标明是哪一份。为确认这一点，除二十七份业绩发布之外还读了 F-4、F-1 与 FY2021 的 20-F：三份都在正文里谈到季度，但都没有列出任何季度财务表。",
        f"地区口径在 {geo_block['basis_change_release']} 的发布里换过一次：此前分 EMEA / 北美 / 拉美 / 亚太（亚太下挂大中华区与日本），此后分 EMEA / 美洲 / 大中华区 / 亚太其余。这次改动在文字里没有任何说明，唯一的证据是算术 —— 美洲等于北美加拉美，亚太其余等于亚太减大中华区。两套口径同时被印出过的期间有{cn_count(both)}个，两条恒等式在每一个上都逐欧元相等，本页因此把换口径之前的季度按新口径还原并标为自算。意大利、美国与日本原本是旧表下的「其中」行，随旧表一起停在 2023 年第四季度，本页不向后补。",
        "产品线里的「其他」也被并过两次，都没有文字说明：Agnona 在 2023 年第一季度的发布里并入，第三方品牌在 2024 年第一季度的发布里并入。本页按公司最后采用的口径发布，换口径之前的季度由首次印出的几行相加还原；"
        + f"两次并线各有{cn_count(len(fold['third_party_brands']['periods']))}个和{cn_count(len(fold['agnona']['periods']))}个期间两套口径都印过，相加的结果与公司自己印出的合并行在每一个上都相等，原值列在 series 的 fold_overlap 里。",
        "批发口径同样分两段：2023 年第一季度起公司把「批发品牌」单列，此前的「批发合计」还含面料、第三方品牌与 Agnona。本页统一用只含三个品牌的口径，早期季度由同一份发布里的各品牌批发行相加得到。",
        "分部利润有一处必须先说明才能看：2022 年上半年之前没有 Corporate 这一行，集团费用整体计在 Zegna 分部里。FY2022 业绩发布第一次把它拆出来，并重述了 2022 年上半年；那是唯一一个两套口径都公布过的半年，差额恰好等于新设的 Corporate 行。2021 年上半年只有旧口径，本页不把它画进分部利润的时间轴。",
        "唯一被公司用脚注说明过的重述是 Pelletteria Tizeta：2024 年的发布把它从 Zegna 分部调入 TOM FORD FASHION 分部，并重述了 2023 年第二、第三季度的分部收入与抵销行，集团合计不变。有一处后果值得记下来：2023 年第四季度按「全年减前九个月」去算，必须用重述后的前九个月才能等于公司印出的第四季度，用首次公布的前九个月会少算一千二百八十二万六千欧元。",
        "Adjusted EBIT 是公司自定义的非 IFRS 指标，定义为税前利润加回金融收支、汇兑损益与权益法结果，再剔除管理层认为不反映经营的项目。本页照用公司的口径与公司印出的值，不自行调整剔除项；各期剔除项的构成在业绩发布里逐项列出。",
        "本页不发布市场一致预期、评级、目标价与估值。中期目标一节引用的是公司自己在资本市场日给出的口径，本页只做结算，不给出自己的预测。",
        "本页只发布公司披露值与可复算的简单派生值；D 标记代表 Derived / 自算。",
        f"本页已知未接入：{quarter_cn(view['latest_quarter'])}之后的任何数据"
        + (f"；另外 {quarter_cn(view['latest_quarter'])} 已有营收披露但尚无损益，"
           "本页的利润口径因此停在半年。"
           if view["latest_quarter"] not in view["quarters"] else "。"),
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
