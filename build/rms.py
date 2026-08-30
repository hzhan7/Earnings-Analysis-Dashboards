"""Hermès International quarterly dashboard.

Hermès is the first company on this site that runs on **two clocks**. Revenue is
published every quarter, split seven ways by métier and six ways by region, with
the company's own constant-currency rate printed beside each cell. Everything
else -- the income statement, the cash flow statement, the balance sheet, the
segment note -- is published **twice a year**. There is no such thing as a
second-quarter margin, a second-quarter EPS or a second-quarter free cash flow
for this company; the half-year report's comparative balance sheet is not even
the prior June, it is the prior December.

So this page does not put profit on a quarterly axis. The revenue exhibits run
on eight quarters and the profit exhibits run on their own half-year axis, and
every profit chart says 「半年」 in its title and its axis label, because the two
clocks sit on one page and a reader scrolling past cannot otherwise tell which
one a chart is on.

**And the guidance record has a shape no other page here carries.** Ferrari's
outlook sheds its upper bound as the year becomes knowable; Hermès never had a
bound to shed. Its entire Outlook section, in all fifteen releases held here
spanning 2021Q1 to 2026H1, is one sentence:

    In the medium-term, despite the economic, geopolitical and monetary
    uncertainties around the world, the group confirms an ambitious goal for
    revenue growth at constant exchange rates.

Word for word, five and a half years, zero numbers. No revenue range, no margin,
no EPS, no currency quantification, and 「medium-term」 rather than a year. There
is nothing to settle, so this page does not report a hit rate: it would be a
column of dashes. What it settles instead is the one pair of numbers the company
does publish every quarter -- the published growth rate and the constant-currency
one -- and the wedge between them, which over these eight quarters went from
+1.3pp to −7.0pp and in 2026Q1 left the two with opposite signs.

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
    headroom as headroom_value,
    headroom_exhibit,
    number_exhibits,
    threshold_exhibit,
    threshold_table,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "rms.json"
DATA_DIR = ROOT / "data"

SECTOR_ORDER = ["leather_goods_saddlery", "ready_to_wear_accessories", "silk_textiles",
                "other_hermes_sectors", "perfume_beauty", "watches", "other_products"]
REGION_ORDER = ["france", "europe_ex_france", "japan", "asia_pacific_ex_japan",
                "americas", "other_middle_east"]
SERIES_COLORS = ["NAVY", "MBLUE", "BLUE", "GOLD", "RED", "GREEN", "GRAY"]

SOURCE_QUARTER = ("各季数值逐字取自公司当期公告自己印出的单季表："
                  "第一、三季度取季度收入公告，第二季度取半年度业绩新闻稿，"
                  "第四季度取全年业绩新闻稿。固定汇率增速一律取该表印出的那一列。")
SOURCE_HALF = ("上半年数值取半年度财务报告与半年度业绩新闻稿；"
               "下半年为公司申报的全年减去公司申报的上半年（D），公司本身不单独披露下半年。")


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def rounded(values, digits: int = 6):
    """Round for the payload so a rebuild is idempotent, keeping ``None`` holes.

    Six places, never the display precision. The renderer rounds again when it
    formats, so a value stored at the precision it is printed at can move a
    digit on that second pass: this page published 香水与美妆's share of the
    quarter's constant-currency increment as −4.3% when the figure is −4.3527%,
    because the builder had already flattened it to −4.35 and `pct1` then took
    it down rather than up.
    """
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


def cc_increments(block: dict, order: list[str], index: int) -> tuple[dict, float]:
    """Each line's euro contribution to the group's constant-currency growth.

    A constant-currency rate is a percentage of that line's own prior-year base,
    so the rates cannot be averaged or compared for size directly -- Silk grew
    12.2% on €192M and Leather Goods 10.2% on €1,765M. Weighting each rate by
    the prior-year column the company prints beside it turns seven percentages
    into seven euro amounts that add up, which is the only form in which
    「哪个板块在推动集团」 has an answer.
    """
    increments = {key: block[key]["prior_year_eur_m"][index] * block[key]["cc_pct"][index] / 100
                  for key in order}
    return increments, sum(increments.values())


# ── section one: what the company actually publishes ─────────────────────────
def outlook_charts(staging: dict) -> list[dict]:
    periods = staging["periods"]
    group = staging["group_revenue"]
    published = group["published_pct"]
    cc = group["cc_pct"]
    wedge = [p - c for p, c in zip(published, cc)]
    worst = wedge.index(min(wedge))

    two_rates = {
        "ref": "EX_RATES",
        "kind": "lines",
        "title": (f"公司每季给出的两个增速：published {signed(published[-1])} 对固定汇率 "
                  f"{signed(cc[-1])}；{periods[worst]} 是两者差得最远的一季"
                  f"（{signed(published[worst])} 对 {signed(cc[worst])}）"),
        "xlabels": list(periods),
        "series": [
            {"name": "published（按当期汇率）", "values": rounded(published), "color": "RED"},
            {"name": "固定汇率（cc）", "values": rounded(cc), "color": "NAVY"},
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
        "ylab": "同比 %",
        "note": ("<b>这两条线是这家公司每季度唯一给出的可结算数字，而它们不是同一件事。</b>"
                 "published 是读者在标题里看到的那个数，固定汇率是公司自己按上期平均汇率重算的那个数。"
                 f"八个季度里两条线一路分开：{periods[2]} 时 published 还比固定汇率高 "
                 f"{signed(wedge[2], 1, 'pp')}，到 {periods[worst]} 已经低了 "
                 f"{abs(wedge[worst]):.1f}pp。"
                 "红线在 2026 年第一季<b>转负</b>，而同一季蓝线是 +5.6% —— "
                 "同一家公司、同一个季度，一个口径说收入在萎缩，另一个说它增长了近 6%。"
                 "纵轴不自 0 起，但没有任何点被截掉。"),
        "src_extra": SOURCE_QUARTER,
    }

    wedge_chart = {
        "ref": "EX_WEDGE",
        "kind": "diverging_bars",
        "title": (f"汇率把标题增速抬高或压低了多少：八季从 {signed(wedge[2], 1, 'pp')} 走到 "
                  f"{signed(wedge[worst], 1, 'pp')}，本季收窄到 {signed(wedge[-1], 1, 'pp')}"),
        "xlabels": list(periods),
        "values": rounded(wedge),
        "legend": "published 减固定汇率",
        "positive_label": "汇率抬高了标题增速",
        "negative_label": "汇率压低了标题增速",
        "fmt": "pp1", "yfmt": "pp1", "label_fmt": "pp1",
        "ylab": "pp",
        "zero_line": True,
        "note": ("这张图只是把 Exhibit {EX_RATES} 的两条线相减，但它回答的问题不同："
                 "<b>不是「增长了多少」，而是「你读到的那个数有多少不是经营」</b>。"
                 "2025 年第一季汇率还在帮忙（+1.3pp），此后连续四个季度转为拖累并逐季加深，"
                 f"到 {periods[worst]} 达到 {abs(wedge[worst]):.1f}pp。"
                 "本季收窄到 1.9pp 不是汇率转向，是<b>上年同期的基数已经被压低了</b> —— "
                 "去年第二季那一格自己就带着 −3.4pp 的拖累。"
                 "所以用「上半年汇率拖累 4.5pp」外推下半年会系统性高估逆风。"),
        "src_extra": SOURCE_QUARTER,
    }

    flips = [(period, block["label"], block["published_pct"][i], block["cc_pct"][i])
             for block in staging["by_region"].values()
             for i, period in enumerate(periods)
             if block["published_pct"][i] * block["cc_pct"][i] < 0]
    latest = len(periods) - 1
    regions = {
        "ref": "EX_REGION_RATES",
        "kind": "grouped_bars",
        "title": (f"本季六个地区的两个口径：日本 published {signed(staging['by_region']['japan']['published_pct'][latest])}"
                  f"、固定汇率 {signed(staging['by_region']['japan']['cc_pct'][latest])}，"
                  f"一个口径说它在萎缩，另一个说它是全集团最快"),
        "xlabels": [staging["by_region"][key]["label"] for key in REGION_ORDER],
        "xrot": 45,
        "groups": [
            {"name": "published（按当期汇率）", "color": "RED",
             "values": [staging["by_region"][key]["published_pct"][latest] for key in REGION_ORDER]},
            {"name": "固定汇率（cc）", "color": "NAVY",
             "values": [staging["by_region"][key]["cc_pct"][latest] for key in REGION_ORDER]},
        ],
        "bar_labels": True,
        "fmt": "pct1", "label_fmt": "pct1",
        "ylab": "同比 %",
        "note": ("法国两根柱一样高 —— 本币计价，没有汇率可换算；日本两根柱差 12.5pp，"
                 "是全表最大的一格。"
                 f"把窗口拉到八个季度、六个地区共 {len(periods) * len(REGION_ORDER)} 格，"
                 f"其中 <b>{len(flips)} 格的两个口径符号相反</b>："
                 + "、".join(f"{p} 的{label}（{signed(a)} 对 {signed(b)}）"
                             for p, label, a, b in flips) +
                 "。这四格全部落在日本与亚太（除日本），也就是本页最需要判断需求方向的两个地区 —— "
                 "读错口径不是读小了一点，是把方向读反。"),
        "src_extra": SOURCE_QUARTER,
    }
    return [two_rates, wedge_chart, regions]


# ── section two: the quarter, which exists only at the revenue line ──────────
def quarter_charts(staging: dict) -> list[dict]:
    periods = staging["periods"]
    latest = len(periods) - 1
    sectors = staging["by_sector"]
    regions = staging["by_region"]
    group = staging["group_revenue"]

    deltas = {key: sectors[key]["cc_pct"][latest] - sectors[key]["cc_pct"][latest - 1]
              for key in SECTOR_ORDER}
    accelerating = [k for k in SECTOR_ORDER if deltas[k] > 0]
    biggest_drop = min(SECTOR_ORDER, key=lambda k: deltas[k])
    # How much of the acceleration is the base rather than the quarter: a line
    # whose previous reading was the low of the whole window has an easier
    # comparison than one that accelerated from mid-range. Counted rather than
    # asserted -- the sentence that used to say "three of the four" was typed by
    # hand and was wrong by one.
    off_the_low = [k for k in accelerating
                   if sectors[k]["cc_pct"][latest - 1] == min(sectors[k]["cc_pct"])]
    sector_pace = {
        "ref": "EX_SECTOR_PACE",
        "kind": "grouped_bars",
        "title": (f"七个板块的环比加减速（固定汇率）：{len(accelerating)} 个在加速，"
                  f"而减速最深的{sectors[biggest_drop]['label']}掉了 "
                  f"{abs(deltas[biggest_drop]):.1f}pp"),
        "xlabels": [sectors[key]["label"] for key in SECTOR_ORDER],
        "xrot": 45,
        "groups": [
            {"name": f"{periods[latest - 1]} 固定汇率", "color": "BLUE",
             "values": [sectors[key]["cc_pct"][latest - 1] for key in SECTOR_ORDER]},
            {"name": f"{periods[latest]} 固定汇率", "color": "NAVY",
             "values": [sectors[key]["cc_pct"][latest] for key in SECTOR_ORDER]},
        ],
        "bar_labels": True,
        "fmt": "pct1", "label_fmt": "pct1",
        "ylab": "同比 %（固定汇率）",
        "note": ("<b>四个板块同时加速，这是本季管理层叙述的支点，也是最容易被过度解读的一格。</b>"
                 "皮具从 +9.4% 到 +10.2%，成衣从 +0.4% 到 +3.6%，丝绸从 +7.8% 到 +12.2%，"
                 "钟表从 −3.7% 到 +4.4%。但这四条里有 "
                 f"{len(off_the_low)} 条（{'、'.join(sectors[k]['label'] for k in off_the_low)}）"
                 "的上季读数正好是本窗口的低点，"
                 "即加速有一部分来自比较基数 —— 公司自己在电话会上用的措辞是"
                 "「有时候是去年太差，才让今年的百分比好看，但销量本身并没有那么好」。"
                 f"另一侧同样要写出来：{sectors[biggest_drop]['label']}是七个板块里唯一负增长的一个，"
                 "环比掉了 9.7pp，而公司在新闻稿与电话会里都没有解释原因。"),
        "src_extra": SOURCE_QUARTER,
    }

    increments, total = cc_increments(sectors, SECTOR_ORDER, latest)
    lead = max(SECTOR_ORDER, key=lambda k: increments[k])
    share = {key: increments[key] / total * 100 for key in SECTOR_ORDER}
    weight = {key: sectors[key]["revenue_eur_m"][latest] / group["revenue_eur_m"][latest] * 100
              for key in SECTOR_ORDER}
    sector_mix = {
        "ref": "EX_SECTOR_MIX",
        "kind": "grouped_bars",
        "title": (f"占收入与占增量不是一回事：{sectors[lead]['label']}占本季收入 "
                  f"{weight[lead]:.1f}%，却贡献了固定汇率增量的 {share[lead]:.1f}%"),
        "xlabels": [sectors[key]["label"] for key in SECTOR_ORDER],
        "xrot": 45,
        "groups": [
            {"name": "占本季收入", "color": "BLUE",
             "values": rounded([weight[key] for key in SECTOR_ORDER])},
            {"name": "占本季固定汇率增量", "color": "NAVY",
             "values": rounded([share[key] for key in SECTOR_ORDER])},
        ],
        "bar_labels": True,
        "fmt": "pct1", "label_fmt": "pct1",
        "ylab": "占比 %",
        "note": ("<b>这张图是本页对「增长有多集中」的全部证据，也是本站少见的一种自算：</b>"
                 "把每个板块公司印出的固定汇率增速乘以它自己印出的上年同期收入，"
                 f"得到 {len(SECTOR_ORDER)} 个可相加的欧元增量，合计 €{total:.0f}M；"
                 f"用集团口径复核是 €{group['prior_year_eur_m'][latest] * group['cc_pct'][latest] / 100:.0f}M，"
                 "两者相差不到 1%，差额是各行四舍五入。"
                 "不能直接比增速大小 —— 丝绸 +12.2% 比皮具 +10.2% 高，但它的基数只有皮具的九分之一。"
                 "<b>皮具一个板块顶掉了近七成的增量，而香水是负贡献</b>；"
                 "换句话说集团的增长现在压在一条腿上，这条腿每一次小幅不及预期都会被放大。"),
        "src_extra": SOURCE_QUARTER + "（增量权重为本页自算 D）",
    }

    r_inc, r_total = cc_increments(regions, REGION_ORDER, latest)
    r_share = {key: r_inc[key] / r_total * 100 for key in REGION_ORDER}
    r_weight = {key: regions[key]["revenue_eur_m"][latest] / group["revenue_eur_m"][latest] * 100
                for key in REGION_ORDER}
    engine = max(REGION_ORDER, key=lambda k: r_inc[k])
    biggest = max(REGION_ORDER, key=lambda k: r_weight[k])
    region_mix = {
        "ref": "EX_REGION_MIX",
        "kind": "grouped_bars",
        "title": (f"同一张图换成地区：{regions[engine]['label']}占收入 {r_weight[engine]:.1f}%、"
                  f"贡献增量 {r_share[engine]:.1f}%，而最大的{regions[biggest]['label']}"
                  f"占收入 {r_weight[biggest]:.1f}%、只贡献 {r_share[biggest]:.1f}%"),
        "xlabels": [regions[key]["label"] for key in REGION_ORDER],
        "xrot": 45,
        "groups": [
            {"name": "占本季收入", "color": "BLUE",
             "values": rounded([r_weight[key] for key in REGION_ORDER])},
            {"name": "占本季固定汇率增量", "color": "NAVY",
             "values": rounded([r_share[key] for key in REGION_ORDER])},
        ],
        "bar_labels": True,
        "fmt": "pct1", "label_fmt": "pct1",
        "ylab": "占比 %",
        "note": ("<b>两根柱的高低关系整个反了过来，这就是本季最值得记住的一格。</b>"
                 "亚太（除日本）是集团最大的一块收入，也是上半年分部经常性经营利润里最大的一块，"
                 "但它贡献的增量还不到美洲的一半；美洲用五分之一的收入顶起了四成的增量。"
                 "按上半年累计口径算，这个数是 45.3% —— <b>抽掉美洲，集团上半年的固定汇率增速"
                 "会从 +6.1% 掉到 +3.3%</b>（本页自算 D：把美洲的增量从合计里剔除后除以上年同期收入）。"
                 "而美洲自己已经从上季的 +17.2% 减速到 +13.7%，是六个地区里减速最快的一个。"
                 "集团的单点依赖没有消失，只是换了个地方。"),
        "src_extra": SOURCE_QUARTER + "（增量权重为本页自算 D）",
    }

    peak = periods.index("Q4 2024")
    double_digit = [k for k in SECTOR_ORDER if sectors[k]["cc_pct"][peak] >= 10.0]
    watches = sectors["watches"]["cc_pct"]
    watch_positive = sum(1 for v in watches[-4:] if v > 0)
    sector_trend = {
        "ref": "EX_SECTOR_TREND",
        "kind": "lines",
        "title": "八季七个板块的固定汇率增速：唯一没有回到正区间的是香水与美妆",
        "xlabels": list(periods),
        "series": [
            {"name": sectors[key]["label"], "values": rounded(sectors[key]["cc_pct"]),
             "color": SERIES_COLORS[i]}
            for i, key in enumerate(SECTOR_ORDER)
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
        "ylab": "同比 %（固定汇率）",
        "note": (f"{periods[peak]} 那一格是本窗口的顶：七条线里有 {len(double_digit)} 条在两位数以上"
                 f"（最低的两条是{sectors['silk_textiles']['label']} "
                 f"{sectors['silk_textiles']['cc_pct'][peak]:.1f}% 与"
                 f"{sectors['watches']['label']} {sectors['watches']['cc_pct'][peak]:.1f}%），"
                 "此后一起下台阶 —— "
                 "所以本季的「四个板块同时加速」要放在这个背景里读：<b>是从低位反弹，不是回到原来的斜率</b>。"
                 "钟表那条线的形状最值得单独看：窗口前段是连续的两位数负增长，"
                 f"最近四季里有 {watch_positive} 季为正但仍在正负之间来回，"
                 "而它只有集团收入的 3.3%，对集团的贡献停在 2.2%。"
                 "香水与美妆是唯一一条本季仍在零以下并且还在下探的线。"
                 "纵轴不自 0 起，但没有任何点被截掉。"),
        "src_extra": SOURCE_QUARTER,
    }
    return [sector_pace, sector_mix, region_mix, sector_trend]


# ── section three: the other clock ───────────────────────────────────────────
def half_year_charts(staging: dict) -> list[dict]:
    halves = {h["label"]: h for h in staging["half_years"]}
    years = ["2023", "2024", "2025", "2026"]
    first = [halves[f"H1 {y}"]["roi_margin_pct"] for y in years]
    second = [halves[f"H2 {y}"]["roi_margin_pct"] if f"H2 {y}" in halves else None for y in years]
    gaps = [f - s for f, s in zip(first, second) if s is not None]

    seasonality = {
        "ref": "EX_HALF_MARGIN",
        "kind": "lines",
        "title": (f"经常性经营利润率<b>按半年</b>：上半年在三个完整年度里每一次都高于下半年，"
                  f"落差从 {gaps[0]:.2f}pp 收窄到 {gaps[-1]:.2f}pp"),
        "xlabels": years,
        "series": [
            {"name": "上半年（公司披露）", "values": rounded(first), "color": "NAVY"},
            {"name": "下半年（全年减上半年 D）", "values": rounded(second), "color": "GOLD"},
        ],
        "fmt": "pct2", "yfmt": "pct1", "label_fmt": "pct2", "end_label": True,
        "ylab": "半年经常性经营利润率 %",
        "note": ("<b>横轴是年份，每个点是一个半年，不是一个季度 —— 这家公司不存在季度利润率。</b>"
                 f"上半年 {first[-1]:.2f}% 被广泛引用为「这家公司的利润率」，"
                 "但它是季节性偏强的那一半：三个完整年度里上半年每次都高于下半年，"
                 f"落差依次是 {gaps[0]:.2f}pp、{gaps[1]:.2f}pp、{gaps[2]:.2f}pp。"
                 "把这条落差套到本年：若重复 2025 年的 0.72pp，全年落在 40.7% 附近；"
                 "若重复三年平均的 2.45pp，全年落在 39.8% 附近。"
                 "<b>这个区间不是预测，是把已发生的季节性原样搬过来的算术</b>，"
                 "它的作用是说明「上半年 41.0%」本身不构成全年 41% 的证据。"
                 "下半年为公司申报全年减公司申报上半年，公司不单独披露下半年。"
                 "纵轴不自 0 起，但没有任何点被截掉。"),
        "src_extra": SOURCE_HALF,
    }

    income = staging["h1_income"]
    lines = {key: (cur, prior) for key, _, cur, prior in income["lines"]}
    detail = {key: (cur, prior) for key, _, cur, prior in income["other_detail"]}
    rev_now, rev_before = lines["revenue"]

    def share_delta(now: float, before: float) -> float:
        """One line's contribution in percentage points of revenue."""
        return now / rev_now * 100 - before / rev_before * 100

    # Every expense line is stored with the sign the income statement prints it
    # with, so a single subtraction gives the contribution in the right
    # direction -- a cost that grew faster than revenue comes out negative.
    gross = share_delta(*lines["gross_margin"])
    sga = share_delta(*lines["sga"])
    da = share_delta(*detail["da"])
    impair = share_delta(*detail["impairment"])
    free_share = share_delta(*detail["free_share_plans"])
    start = lines["recurring_operating_income"][1] / rev_before * 100
    end = lines["recurring_operating_income"][0] / rev_now * 100
    residual = (end - start) - (gross + sga + da + impair + free_share)
    legs = [gross, sga, da, impair, free_share, residual]
    bridge = {
        "ref": "EX_MARGIN_BRIDGE",
        "kind": "bridge_bar",
        "title": (f"上半年经常性经营利润率 {start:.2f}% → {end:.2f}%：净降 "
                  f"{signed(end - start, 2, 'pp')}，其中减值一项就是 {signed(impair, 2, 'pp')}"),
        "xlabels": ["毛利率", "销售及管理费用", "折旧与摊销", "减值损失",
                    "免费股计划费用", "计提准备、其他与舍入", "合计变动"],
        "xrot": 45,
        "stacks": [{
            "name": "对上半年利润率的影响",
            "color": "NAVY",
            "values": rounded(legs) + [None],
        }],
        "net": {
            "name": "上半年利润率净变动",
            "values": [None] * len(legs) + [round(end - start, 6)],
        },
        "fmt": "pp1", "yfmt": "pp1", "label_fmt": "pp1",
        "ylab": "对利润率的影响 pp",
        "note": ("<b>「汇率压毛利」这条最常见的叙述在这家公司身上不成立。</b>"
                 "上半年销货成本的绝对额与去年同期<b>一分未涨</b>（€2,356M 对 €2,356M），"
                 f"毛利率反而扩张 {signed(gross, 2, 'pp')}。"
                 f"<b>头两根柱几乎正好抵消</b>：毛利率 {signed(gross, 2, 'pp')} 对销售及管理费用 "
                 f"{signed(sga, 2, 'pp')}，净额只有 {signed(gross + sga, 2, 'pp')}。"
                 "所以这 0.36pp 的净降幅实际上整个落在「其他收支」这一行里，"
                 f"而那一行里最大的一项既不是广告也不是折旧，是<b>减值损失</b>："
                 f"从 €70M 涨到 €98M，单项 {signed(impair, 2, 'pp')}，"
                 f"占 {abs(end - start):.2f}pp 净降幅的 "
                 f"{abs(impair / (end - start)) * 100:.0f}%。"
                 "半年度财务报告附注 6.2.2 对这笔减值的用途写的是「生产线上的个别资产与"
                 "被认为盈利能力不足的门店」—— 在一份通篇讲需求强劲的报告里，"
                 "这是管理层自己确认的一条反向证据。"
                 f"反方向的一项也要写出来：免费股计划费用从 €111M 降到 €89M，贡献 "
                 f"{signed(free_share, 2, 'pp')}，而该费用与公司股价挂钩，同期期间平均股价下跌 26.2%。"
                 "最后一格是把计提准备净变动、其他收支净额与合并报表的印刷舍入并在一起，"
                 "让六项相加恰好等于净变动。"),
        "src_extra": "2026 半年度财务报告 §3.1 合并损益表与附注 4.4；各项占收入比重为本页自算 D。",
    }

    segments = staging["h1_segments"]
    operating = [s for s in segments if s["key"] != "unallocated"]
    unallocated = next(s for s in segments if s["key"] == "unallocated")
    six_now = sum(s["roi_2026"] for s in operating)
    six_before = sum(s["roi_2025"] for s in operating)
    total_now = lines["recurring_operating_income"][0]
    total_before = lines["recurring_operating_income"][1]
    segment_roi = {
        "ref": "EX_SEGMENT_ROI",
        "kind": "grouped_bars",
        "title": (f"<b>半年</b>分部经常性经营利润：六个经营地区合计 €{six_before:,}M → €{six_now:,}M"
                  f"（{signed((six_now / six_before - 1) * 100)}），"
                  f"集团之所以是 {signed((total_now / total_before - 1) * 100)}，"
                  f"全靠未分配一栏摆动 €{unallocated['roi_2026'] - unallocated['roi_2025']:+,}M"),
        "xlabels": [s["label"] for s in operating],
        "xrot": 45,
        "groups": [
            {"name": "上半年 2025", "color": "BLUE", "values": [s["roi_2025"] for s in operating]},
            {"name": "上半年 2026", "color": "NAVY", "values": [s["roi_2026"] for s in operating]},
        ],
        "bar_labels": True,
        "fmt": "f0c", "label_fmt": "f0c",
        "ylab": "€M（半年）",
        "note": ("<b>这张表在公司自己的文件里是附注 3，很少被引用，而它推翻了「利润小幅增长」这句概括。</b>"
                 f"六个经营地区加起来是 €{six_before:,}M → €{six_now:,}M，也就是 −€{six_before - six_now}M；"
                 f"集团口径的 +€{total_now - total_before}M 完全来自未分配一栏从 "
                 f"−€{abs(unallocated['roi_2025'])}M 翻正到 +€{unallocated['roi_2026']}M。"
                 "公司对未分配栏的定义是「免费股分配计划费用、未分配的中央成本与内部计费」，"
                 "而同期免费股计划费用降了 €22M。"
                 "<b>未分配那一栏没有画在图上</b>：一根 €25M 的柱子挨着一根 €1,653M 的柱子"
                 "既读不出高低、又会把自己的数值标签压到地区名上，它的两个数在标题里、"
                 "在这段话里、也在核对抽屉的分部表里。"
                 "<b>所以「上半年利润还在增长」这句话，要成立必须把一个与本期经营无关的科目算进去。</b>"
                 "另外附注 3 自己写明：上半年的分部利润率<b>不含内部转移定价调整</b>，"
                 "这些调整对合并利润中性、将发生在下半年，且主要影响法国与亚太（除日本）——"
                 "所以这两个地区的半年利润率不可外推全年，而表内所有半年对半年的同比变动是同口径的。"),
        "src_extra": "2026 半年度财务报告附注 3（分部信息），上半年口径。",
    }

    margin_delta = [s["roi_2026"] / s["revenue_2026"] * 100 - s["roi_2025"] / s["revenue_2025"] * 100
                    for s in operating]
    big = next(i for i, s in enumerate(operating) if s["key"] == "asia_pacific_ex_japan")
    amer = next(i for i, s in enumerate(operating) if s["key"] == "americas")
    segment_margin = {
        "ref": "EX_SEGMENT_MARGIN",
        "kind": "diverging_bars",
        "title": (f"<b>半年</b>分部利润率变动：{operating[big]['label']}掉了 "
                  f"{abs(margin_delta[big]):.2f}pp，而它占集团分部利润的 "
                  f"{operating[big]['roi_2026'] / total_now * 100:.1f}%"),
        "xlabels": [s["label"] for s in operating],
        "xrot": 45,
        "values": rounded(margin_delta),
        "legend": "上半年利润率同比变动",
        "positive_label": "利润率扩张",
        "negative_label": "利润率收缩",
        "fmt": "pp1", "yfmt": "pp1", "label_fmt": "pp1",
        "ylab": "pp（半年对半年）",
        "zero_line": True,
        "note": ("六个地区里只有两个扩张。<b>唯一量与利润率同时改善的是美洲</b>"
                 f"（利润 {signed((operating[amer]['roi_2026'] / operating[amer]['roi_2025'] - 1) * 100)}、"
                 f"利润率 {signed(margin_delta[amer], 2, 'pp')}），"
                 "而日本利润率的 +1.48pp 是在收入按当期汇率<b>下降</b> 2.1% 的情况下取得的 —— "
                 "日元贬值同时压低了它的欧元收入与欧元成本。"
                 f"最该盯的是{operating[big]['label']}：它一个地区占了集团分部利润的 "
                 f"{operating[big]['roi_2026'] / total_now * 100:.1f}%，"
                 "利润率和利润额同时下滑，是集团利润率的第一决定变量。"
                 "中东那条最长的负柱只有 €330M 的收入基数，对集团的绝对影响远小于它的柱长。"
                 "利润率为本页按分部收入与分部利润自算 D；公司自己只印到整数百分比（47%、48%），"
                 "两位小数的变动量按未取整的原值计算。"),
        "src_extra": "2026 半年度财务报告附注 3；利润率与变动量为本页自算 D。",
    }

    invest_first = [halves[f"H1 {y}"]["operating_investments_eur_m"] for y in years]
    invest_second = [halves[f"H2 {y}"]["operating_investments_eur_m"] if f"H2 {y}" in halves
                     else None for y in years]
    fy_target = 1000
    implied = fy_target - invest_first[-1]
    invest_second[-1] = implied
    fy_2025 = staging["full_years"]["2025"]["operating_investments_eur_m"]
    capex = {
        "ref": "EX_CAPEX",
        "kind": "grouped_bars",
        "title": (f"<b>半年</b>经营性投资：管理层口头说下半年会加速，而全年目标 €{fy_target:,}M 比 2025 年"
                  f"实际的 €{fy_2025:,}M 少 {abs((fy_target / fy_2025 - 1) * 100):.1f}%"),
        "xlabels": years,
        "groups": [
            {"name": "上半年（公司披露）", "color": "NAVY", "values": invest_first},
            {"name": "下半年（2023–2025 为全年减上半年 D，2026 为按全年目标反推）",
             "color": "GOLD", "values": invest_second},
        ],
        "bar_labels": True,
        "fmt": "f0c", "label_fmt": "f0c",
        "ylab": "€M（半年）",
        "annot": f"2026 下半年 €{implied:,}M 为按全年目标 €{fy_target:,}M 反推的隐含值",
        "note": ("<b>下半年投资爬坡是这家公司每年都有的季节性，问题在于今年的爬坡比往年弱。</b>"
                 f"2025 年下半年花了 €{invest_second[2]:,}M，是上半年的 "
                 f"{invest_second[2] / invest_first[2]:.2f} 倍；"
                 f"2026 年按全年目标反推的下半年是 €{implied:,}M，只有上半年的 "
                 f"{implied / invest_first[-1]:.2f} 倍，同比 "
                 f"{signed((implied / invest_second[2] - 1) * 100)}。"
                 "<b>所以资本开支在下半年是自由现金流的顺风，不是逆风</b> —— "
                 "这一点与本季普遍的读法相反，而它可以直接从新闻稿关键数据表核出来："
                 f"Operating investments 那一行同时印着上半年 €{invest_first[-1]}M、"
                 f"2025 全年 €{fy_2025:,}M 与上年同期 €{invest_first[2]}M，三列同口径。"
                 "值得追问的是反方向的问题：口头的「加速投资」与账上的同比下降约 14% 之间，"
                 "公司没有给出拆分，两种解释（上年含一次性项目 / 投资节奏确在收敛）都无法裁定。"),
        "src_extra": SOURCE_HALF + "；全年目标 €1,000m 出自业绩电话会，不是新闻稿里的书面指引。",
    }
    return [seasonality, bridge, segment_roi, segment_margin, capex]


# ── section four: what the next release can and cannot settle ────────────────
def next_quarter_charts(staging: dict) -> list[dict]:
    periods = staging["periods"]
    kpi = staging["next_kpi"]
    # Every count and every name below is read out of the threshold list rather
    # than typed beside it. A tally printed in a title has nothing checking it,
    # which is how this page shipped four wrong ones in its first draft.
    entries = kpi["quantified"]
    breached = [e for e in entries
                if headroom_value(e["direction"], e["threshold"], e["current"]) < 0]
    later = kpi["full_year_only"]
    headroom = headroom_exhibit(
        f"下季 {len(entries)} 条阈值的余量：本季已有 {len(breached)} 条落在阈值的另一侧",
        entries, "current",
        note=(f"{len(entries)} 条全部是收入类，因为 <b>{kpi['settles_on']} 的第三季度公告只有收入</b> —— "
              "没有损益表、没有现金流量表、没有资产负债表，所以任何「第三季度利润率」都不存在。"
              f"利润与投资类的 {len(later)} 条要等 2027 年 2 月的全年业绩，列在核对抽屉里。"
              "阈值方向统一为「正值 = 仍在安全侧」，各条的原始单位见核对表。"
              f"越过阈值的是{'、'.join(e['metric'] for e in breached)}，"
              f"共 {len(breached)} 条，彼此不重叠。"),
        src_extra="阈值为本页本地研究设定，不是公司指引；公司不发布任何数字化指引。",
    )

    apac = staging["by_region"]["asia_pacific_ex_japan"]
    apac_line = threshold_exhibit(
        f"亚太（除日本）固定汇率增速与 5% 阈值：八季里 {sum(1 for v in apac['cc_pct'] if v >= 5.0)} 季在阈值之上",
        list(periods), rounded(apac["cc_pct"]), 5.0,
        fmt="pct1", ylab="同比 %（固定汇率）",
        actual_name="亚太（除日本）固定汇率增速", threshold_name="本页阈值 5.0%",
        note=("这条线为什么值得单独画：该地区占上半年集团收入 43.3%、"
              "占分部经常性经营利润 49.3%，是集团利润率的第一决定变量，"
              f"而它在这 {len(periods)} 个季度里有 "
              f"{sum(1 for v in apac['cc_pct'] if v < 5.0)} 季低于 5%。"
              "阈值取 5% 的理由是可审计的：分析师在电话会上按亚太约 5% 的提价幅度提问，"
              "管理层没有否认这个量级，所以固定汇率增速回到 5% 以上"
              "大致对应销量不再下滑 —— 这是<b>推断</b>，公司从不披露量价拆分，也从不单独披露大中华区增速。"
              "纵轴不自 0 起，但没有任何点被截掉。"),
        src_extra=SOURCE_QUARTER,
    )

    leather = staging["by_sector"]["leather_goods_saddlery"]
    leather_line = threshold_exhibit(
        f"皮具与马具固定汇率增速与 9% 阈值：八季里 {sum(1 for v in leather['cc_pct'] if v >= 9.0)} 季在阈值之上",
        list(periods), rounded(leather["cc_pct"]), 9.0,
        fmt="pct1", ylab="同比 %（固定汇率）",
        actual_name="皮具与马具固定汇率增速", threshold_name="本页阈值 9.0%",
        note=("<b>这条线和上一条是集团的两条承重柱，而它们指向相反。</b>"
              "皮具本季 +10.2%，兑现了上一季管理层在电话会上给出的「皮具增速会逐月回升」这句"
              "可证伪的承诺；但它同时贡献了近七成的集团增量，"
              "所以它自己的增速已经接近等同于集团增速，单看这条线的信息量在下降 —— "
              "这也是 Exhibit {EX_SECTOR_MIX} 那条集中度腿必须和它一起看的原因。"
              "另外公司在本季明确否认了外部普遍使用的「6% 量 + 中个位数价」这套拆解，"
              "理由是量的本质是工时而不同产品的工时价值不同，"
              "而公司又不提供替代口径 —— 量价拆分与皮具占比都被拒答。"
              "纵轴不自 0 起，但没有任何点被截掉。"),
        src_extra=SOURCE_QUARTER,
    )
    return [headroom, apac_line, leather_line]


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    latest = len(periods) - 1
    group = staging["group_revenue"]
    halves = {h["label"]: h for h in staging["half_years"]}
    sectors = staging["by_sector"]
    regions = staging["by_region"]
    income = staging["h1_income"]
    lines = {key: (cur, prior) for key, _, cur, prior in income["lines"]}

    outlook = outlook_charts(staging)
    quarter = quarter_charts(staging)
    half_year = half_year_charts(staging)
    next_block = next_quarter_charts(staging)

    exhibits = number_exhibits(outlook + quarter + half_year + next_block)
    resolve_exhibit_refs(exhibits)
    n_out, n_qtr, n_half = len(outlook), len(quarter), len(half_year)
    outlook_ex = exhibits[:n_out]
    quarter_ex = exhibits[n_out:n_out + n_qtr]
    half_ex = exhibits[n_out + n_qtr:n_out + n_qtr + n_half]
    next_ex = exhibits[n_out + n_qtr + n_half:]

    increments, total_inc = cc_increments(sectors, SECTOR_ORDER, latest)
    leather_share = increments["leather_goods_saddlery"] / total_inc * 100
    r_inc, r_total = cc_increments(regions, REGION_ORDER, latest)
    americas_share = r_inc["americas"] / r_total * 100
    wedge = [p - c for p, c in zip(group["published_pct"], group["cc_pct"])]

    first_table = exhibits[-1]["n"] + 1
    tables = [
        {
            "n": first_table,
            "title": "近八季分板块收入与两个增速口径（公司披露值）",
            "headers": ["期间", "集团收入", "集团 published", "集团固定汇率"]
                       + [sectors[key]["label"] for key in SECTOR_ORDER],
            "rows": [[periods[i], f"€{group['revenue_eur_m'][i]:,}M",
                      f"{group['published_pct'][i]:.1f}%", f"{group['cc_pct'][i]:.1f}%"]
                     + [f"€{sectors[key]['revenue_eur_m'][i]:,}M / {sectors[key]['cc_pct'][i]:.1f}%"
                        for key in SECTOR_ORDER]
                     for i in range(len(periods))],
        },
        {
            "n": first_table + 1,
            "title": "近八季分地区收入与两个增速口径（公司披露值）",
            "headers": ["期间"] + [f"{regions[key]['label']}（收入 / published / 固定汇率）"
                                   for key in REGION_ORDER],
            "rows": [[periods[i]]
                     + [f"€{regions[key]['revenue_eur_m'][i]:,}M / "
                        f"{regions[key]['published_pct'][i]:.1f}% / "
                        f"{regions[key]['cc_pct'][i]:.1f}%"
                        for key in REGION_ORDER]
                     for i in range(len(periods))],
        },
        {
            "n": first_table + 2,
            "title": "半年度损益、现金流与投资（下半年为全年减上半年 D）",
            "headers": ["半年", "口径", "收入", "经常性经营利润", "经常性经营利润率 D",
                        "归母净利润", "经营现金流", "经营性投资", "调整后自由现金流"],
            "rows": [[h["label"], "公司披露" if not h["derived"] else "全年减上半年 D",
                      f"€{h['revenue_eur_m']:,}M",
                      f"€{h['recurring_operating_income_eur_m']:,}M",
                      f"{h['roi_margin_pct']:.2f}%",
                      f"€{h['net_profit_group_eur_m']:,}M",
                      f"€{h['operating_cash_flows_eur_m']:,}M",
                      f"€{h['operating_investments_eur_m']:,}M",
                      f"€{h['adjusted_fcf_eur_m']:,}M"]
                     for h in staging["half_years"]],
        },
        {
            "n": first_table + 3,
            "title": "上半年合并损益表与其他收支明细（公司披露值）",
            "headers": ["科目", "上半年 2026", "上半年 2025", "变动", "占收入变动 D"],
            "rows": [[label, f"€{cur:,}M", f"€{prior:,}M", f"€{cur - prior:+,}M",
                      f"{cur / lines['revenue'][0] * 100 - prior / lines['revenue'][1] * 100:+.3f}pp"]
                     for _, label, cur, prior in income["lines"]]
                    + [[f"其中：{label}", f"€{cur:,}M", f"€{prior:,}M", f"€{cur - prior:+,}M",
                        f"{cur / lines['revenue'][0] * 100 - prior / lines['revenue'][1] * 100:+.3f}pp"]
                       for _, label, cur, prior in income["other_detail"]]
                    + [["稀释每股收益", f"€{income['eps_diluted_eur'][0]:.2f}",
                        f"€{income['eps_diluted_eur'][1]:.2f}",
                        f"€{income['eps_diluted_eur'][0] - income['eps_diluted_eur'][1]:+.2f}",
                        f"{(income['eps_diluted_eur'][0] / income['eps_diluted_eur'][1] - 1) * 100:+.2f}%"]],
        },
        {
            "n": first_table + 4,
            "title": "分地区经常性经营利润与投资（附注 3，上半年口径）",
            "headers": ["地区", "利润 2026", "利润 2025", "同比", "利润率 2026 D",
                        "利润率 2025 D", "利润率变动 D", "投资 2026", "投资 2025"],
            "rows": [[s["label"], f"€{s['roi_2026']:,}M", f"€{s['roi_2025']:,}M",
                      f"{(s['roi_2026'] / s['roi_2025'] - 1) * 100:+.1f}%"
                      if s["roi_2025"] > 0 else "—",
                      f"{s['roi_2026'] / s['revenue_2026'] * 100:.2f}%" if s["revenue_2026"] else "—",
                      f"{s['roi_2025'] / s['revenue_2025'] * 100:.2f}%" if s["revenue_2025"] else "—",
                      f"{s['roi_2026'] / s['revenue_2026'] * 100 - s['roi_2025'] / s['revenue_2025'] * 100:+.2f}pp"
                      if s["revenue_2026"] and s["revenue_2025"] else "—",
                      f"€{s['capex_2026']:,}M", f"€{s['capex_2025']:,}M"]
                     for s in staging["h1_segments"]],
        },
        {
            "n": first_table + 5,
            "title": "官方展望的原文与它出现过的每一份公告",
            "headers": ["发布日期", "公告", "展望段的数字个数", "展望段原文"],
            "rows": [[r["date"], r["label"], "0", staging["outlook"]["sentence"]]
                     for r in staging["outlook"]["releases"]],
        },
        {
            "n": first_table + 6,
            "title": f"电话会上给出的 {len(staging['quasi_guidance'])} 条数字化「准指引」（不是新闻稿里的书面指引）",
            "headers": ["项目", "数值", "对下半年的方向", "何时可结算", "限定"],
            "rows": [[q["item"], q["value"], q["direction"], q["settles"], q["note"]]
                     for q in staging["quasi_guidance"]],
        },
        threshold_table(first_table + 7, "下季阈值与当前值（原始单位）",
                        staging["next_kpi"]["quantified"], "current", "当前值"),
        {
            "n": first_table + 8,
            "title": f"只有全年业绩才能结算的 {len(staging['next_kpi']['full_year_only'])} 条（2027-02-11）",
            "headers": ["指标", "当前值", "阈值", "为什么"],
            "rows": [[k["metric"], k["current"], k["threshold"], k["why"]]
                     for k in staging["next_kpi"]["full_year_only"]],
        },
        ai_capex_cycle_table(first_table + 9),
    ]

    h1_2026 = halves["H1 2026"]
    h1_2025 = halves["H1 2025"]
    operating = [s for s in staging["h1_segments"] if s["key"] != "unallocated"]
    six_now = sum(s["roi_2026"] for s in operating)
    six_before = sum(s["roi_2025"] for s in operating)
    apac = next(s for s in operating if s["key"] == "asia_pacific_ex_japan")

    return {
        "schema_version": "quarterly-dashboard/rms-v1",
        "page": {"slug": "rms", "language": "zh-CN"},
        "company": {
            "ticker": "RMS",
            "name": "Hermès International",
            "group": "luxury_brands",
            "accounting_standard": "IFRS",
        },
        "latest": {
            "disclosed_period_label": "Q2 2026",
            "full_financial_period_label": "H1 2026",
            "period_end": "2026-06-30",
            "release_date": "2026-07-29",
            "analysis_date": "2026-08-30",
            "audit_status": "limited_review",
            "status": "history_ready",
        },
        "tracker": "Watchlist Quarterly Tracker · RMS",
        "title": "Hermès International (RMS)：Q2 2026 收入与 H1 2026 利润仪表盘",
        "subtitle": ("收入截至 2026-06-30 单季 · 利润仅上半年累计 · 发布 2026-07-29 · "
                     "IFRS · 欧元列示 · 半年度报告经有限审阅 · 自然年财年 · "
                     "数据来自公司季度收入公告与半年度业绩新闻稿及财务报告"),
        "headline": (
            f"第二季度收入 €{group['revenue_eur_m'][latest]:,}M，"
            f"published {signed(group['published_pct'][latest])} 而固定汇率 "
            f"{signed(group['cc_pct'][latest])}；"
            f"皮具占本季收入 "
            f"{sectors['leather_goods_saddlery']['revenue_eur_m'][latest] / group['revenue_eur_m'][latest] * 100:.1f}%"
            f"、却贡献了固定汇率增量的 {leather_share:.1f}%，"
            f"美洲用 {regions['americas']['revenue_eur_m'][latest] / group['revenue_eur_m'][latest] * 100:.1f}% 的收入"
            f"贡献了 {americas_share:.1f}%；"
            f"而利润只有上半年口径 —— 经常性经营利润率 {h1_2026['roi_margin_pct']:.2f}%，"
            f"六个经营地区的利润合计 {signed((six_now / six_before - 1) * 100)}，"
            f"集团口径的 {signed((h1_2026['recurring_operating_income_eur_m'] / h1_2025['recurring_operating_income_eur_m'] - 1) * 100)} "
            f"全部来自未分配一栏。"),
        "brief": (
            '<h4>本期三条主线</h4><div class="takeaway-grid">'
            '<article><span>口径</span><b>这家公司有两个时钟</b>'
            '<p>收入按季披露，利润只按半年披露。不存在第二季度的利润率、每股收益或自由现金流；'
            '半年报的资产负债表比较期还是上年 12 月而不是上年 6 月。'
            '本页的利润图全部走半年轴，标题里都写着「半年」。</p></article>'
            '<article><span>记录</span><b>展望五年半没换过一个字，也没有一个数</b>'
            f'<p>手上 {len(staging["outlook"]["releases"])} 份公告的 Outlook 段逐字相同，'
            '数字个数为 0：没有收入区间、没有利润率、没有每股收益，'
            '连时间边界都是「中期」而不是某一年。能结算的只有它每季给的两个增速口径。</p></article>'
            '<article><span>本季</span><b>标题增速与经营增速差 1.9pp，上季差 7.0pp</b>'
            f'<p>published 从 {signed(group["published_pct"][latest - 1])} 跳到 '
            f'{signed(group["published_pct"][latest])}，抬升 '
            f'{group["published_pct"][latest] - group["published_pct"][latest - 1]:.1f}pp；'
            f'固定汇率只从 {signed(group["cc_pct"][latest - 1])} 到 {signed(group["cc_pct"][latest])}，'
            f'抬升 {group["cc_pct"][latest] - group["cc_pct"][latest - 1]:.1f}pp。'
            '真实加速是 1.1pp，不是 6.2pp。</p></article>'
            '</div>'),
        "source": ('Source: <a href="https://finance.hermes.com/en/publications/" rel="noopener">'
                   'Hermès Finance — 财务出版物</a>（各期季度收入公告、半年度与全年业绩新闻稿）。'
                   '爱马仕不是美国证券交易委员会的申报人：它自 2008 年起依 Rule 12g3-2(b) 豁免登记，'
                   '从未提交过 20-F 或 6-K。'),
        "source_url": "https://finance.hermes.com/en/publications/",
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {"id": "outlook", "title": "一、公司到底给了什么可以被结算的东西",
             "description": ("答案是：书面展望里什么都没有。手上 15 份公告的 Outlook 段是同一句话、"
                             "零个数字。所以这一节结算的是公司每季确实给出的另一样东西 —— "
                             "published 与固定汇率两个增速，以及它们之间那道逐季张开的口子。"),
             "exhibits": outlook_ex},
            {"id": "quarter_highlights", "title": "二、本季重点：收入是唯一有季度口径的一层",
             "description": ("七个板块与六个地区的加减速、增长的集中度，以及八个季度的板块走势。"
                             "本节所有内容都在收入线上，因为这家公司的季度披露到收入为止。"),
             "exhibits": quarter_ex},
            {"id": "half_year_profit", "title": "三、利润的另一个时钟：半年",
             "description": ("利润率的季节性、上半年利润率变动的逐项拆解、分地区利润与投资节奏。"
                             "本节每张图的横轴都是半年或年度，没有一张是季度 —— "
                             "把其中任何一个数称作「第二季度」都是错的。"),
             "exhibits": half_ex},
            {"id": "next_quarter", "title": "四、下季要跟踪什么",
             "description": (f"{len(staging['next_kpi']['quantified'])} 条可在 "
                             f"{staging['next_kpi']['settles_on']} 第三季度收入公告上结算的阈值，"
                             "统一用「距阈值余量」口径；利润与投资类的 "
                             f"{len(staging['next_kpi']['full_year_only'])} 条要等 2027-02-11 的全年业绩，"
                             "收在核对抽屉里。"),
             "exhibits": next_ex},
        ],
        "tables": tables,
        "notes": [
            "本页按「公司给了什么 → 本季重点 → 半年利润 → 下季跟踪」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "爱马仕不是美国证券交易委员会的申报人。CIK 0001436949 名下只有四类文件：2008-02-25 的一份 12G3-2B（依 Rule 12g3-2(b) 豁免登记）、同日的两份 ARS 与一份 SUPPL，以及 2008、2013、2017、2019 年的四份 F-6EF（存托凭证登记）—— 没有 20-F、没有 6-K、没有 F-1，也没有任何一张财务报表。因此本站其他公司页所依赖的 10-Q/10-K 渲染报表（R-files）与 companyfacts 对它都不存在。本页全部数据来自公司自己在法国发布的季度收入公告、半年度业绩新闻稿与半年度财务报告。",
            "**这家公司有两个披露时钟，本页不把它们混在一根轴上。** 收入按季度披露，分七个 métier、六个地区，每一格都带公司自己算的固定汇率增速；损益表、现金流量表、资产负债表与分部附注一年只出两次。所以本页不存在任何形式的「第二季度利润率」「第二季度每股收益」「第二季度自由现金流」—— 利润类的每一张图都走半年轴，标题与轴标里都写着「半年」。",
            "固定汇率增速一律取公司自己在该期表格里印出的那一列，绝不由「半年减第一季」反推。反推值含各行四舍五入，与官方值最大相差 0.3pp（例如成衣的 +0.4% 会被反推成 +0.5%、钟表的 −3.7% 会被反推成 −3.4%），而这类差异恰好落在判断加减速的量级上。",
            "季度数值取自四种不同的公告：第一、三季度取季度收入公告，第二季度取半年度业绩新闻稿的「2nd quarter」子表，第四季度取全年业绩新闻稿的「4th quarter」子表。四种公告的表格结构一致，都同时印出当期、上年同期、published 与固定汇率四列。",
            "已做的对账：八个季度里,七个板块相加与六个地区相加都等于公司印出的集团合计（最大差 1，为各行四舍五入）；2025 年四个季度相加等于公司申报的全年 €16,002M；2026 年第一、二季度相加等于公司印出的上半年累计各行；三个财年的上下半年相加都等于公司申报的全年。",
            "下半年的利润、现金流与投资是公司申报的全年减去公司申报的上半年（D）。公司本身从不单独披露下半年，所以这几格是本页可复算的派生值而不是披露值；上半年那几格全部是披露值。",
            "上半年经常性经营利润率的逐项拆解按各科目占收入的比重相减得到，是本页自算（D）。合并损益表印到百万欧元，所以毛利减销管费用再减其他收支与印出的经常性经营利润之间存在 €1M 的印刷差；拆解图最后一格把计提准备、其他收支净额与这笔舍入并在一起，使六项相加恰好等于净变动。",
            "分部利润率（附注 3）公司只印到整数百分比。本页图上的两位小数变动量是按分部利润除以分部收入的未取整原值计算的（D），与公司印出的整数不矛盾但比它精细。附注 3 同时写明：上半年的分部利润率不含内部转移定价调整，这些调整对合并经营利润中性、将发生在下半年，且主要影响法国与亚太（除日本）——所以这两个地区的半年利润率不可外推全年，而表内所有半年对半年的同比变动是同口径的。",
            "「固定汇率增量贡献」是本页自算（D）：把每一行公司印出的固定汇率增速乘以它自己印出的上年同期收入，得到可相加的欧元增量。这一步是必要的 —— 固定汇率增速是各行相对自己基数的百分比，直接比较大小会把一个 €192M 的板块和一个 €1,765M 的板块放在同一把尺上。用集团口径复核，两种算法相差不到 1%。",
            "公司的官方展望自 2021 年第一季以来逐字未变，且不含任何数字。本页因此不设「指引兑现」一节，也不报命中率 —— 对着一句没有数字的话报命中率，得到的只会是一列破折号。电话会上出现过六条数字化的说法，它们收在核对抽屉的单独一张表里，并逐条标注了限定：其中两条的发言人在纪要中标为未具名高管，两条是被分析师问出来的而非主动披露。",
            "本页不发布市场一致预期、评级、目标价与估值。第四节的阈值是本地研究设定，不是公司指引；每条阈值都写明了它当初想检验的机制，以便下一季判断它是被触发还是被证明设计失效。",
            "上半年利润率与全年利润率的关系是季节性的，不是趋势性的。三个完整年度里上半年每一次都高于下半年，落差依次为 3.83pp、2.79pp、0.72pp。本页给出的全年区间是把这条已发生的落差原样搬到本年的算术，不是预测。",
            "本页只发布公司披露值与可复算的简单派生值；D 标记代表 Derived / 自算。",
            "核对抽屉最后那张「AI capex 循环」是全站共用的跨页对照块，在每一页都逐字节相同，不是对爱马仕的判断。它追的是四家云厂现金资本开支 → NVDA 数据中心收入 → TSM 晶圆这条链，爱马仕不在这条链的任何一环上。把它放在这里是为了让读者在任意一页都能查到同一份上下游对照；它在折叠的抽屉里，不参与本页的论证。",
            "本页已知未接入：大中华区的量化增速（公司从不单独披露，只在定性口径里出现）、皮具的量价拆分与经典款占比（公司在本季明确拒答）、零售与批发的拆分（上一季在电话会上给过一次，本季收回，只答方向）、门店数与单店效率、减值损失的地区与资产归属（两份文件均未披露）、以及 2026 年第三季度之后的任何数据（本页数据截至 2026-07-29 的披露）。",
            "上半年有效税率 35.37% 因法国大企业特别税须按 IAS 34 在中期一次性全额确认而虚高；公司在半年度财务报告附注 1.2 给出的含特别税全年估计税率是 33%、剔除后是 28%。本页不据此调整任何披露值，只在此说明为什么半年税率不能年化。",
            "业绩电话会内容仅用于定位公司已在公告中量化的项目，或用于标注公司口头给出、书面未给的说法；公开仓不复制原件或逐字内容。",
        ],
        "footer": "Hermès International quarterly and half-year results · 数据来自公司公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "rms.js"), payload, "rms")
    shell_dir = ROOT / "rms"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("RMS", "rms"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"RMS page: {charts} charts in {len(payload['sections'])} sections "
          f"+ {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
