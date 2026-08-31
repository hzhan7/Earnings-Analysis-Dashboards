"""Cboe Global Markets quarterly dashboard.

Cboe prints market share and revenue per contract for the same business, in the
same table, in every quarterly release. Share is the number that gets quoted;
**ADV x RPC is the money**. This page exists because over the published record
the two do not agree.

Across the 29 quarters in which Cboe has published a multi-listed options market
share alongside the ADV and RPC that multiply into daily revenue, the two move in
OPPOSITE directions in 17 of the 28 quarter-on-quarter steps. Share fell from
30.8% to 23.5% over that window -- down 7.3 points -- while daily revenue went
from US$0.309M to US$1.002M, up 224%. A threshold set on share alone is not a
weak risk control; on this record it is slightly worse than a coin flip.

That is not a claim about one quarter. The local note that feeds this page set
exactly such a threshold last quarter ("multi-listed share must hold 22%"), and
this quarter it read 23.5% and cleared -- while daily revenue fell 10.2%. The
note caught that and retired the threshold. The record here says the problem was
never specific to this quarter.

The same shape runs in the cash equities business, twice and in opposite
directions: off-exchange share climbed while net capture fell, and on-exchange
share more than halved -- 21.3% to 9.4% across 42 quarters -- while net capture
ended exactly where it began.

What this page will NOT settle, and why it is worth saying twice: the guidance a
reader most wants scored is organic net revenue growth, and it cannot be scored
in either era. From 2022 to 2024 the company guided it as a number, but "organic"
has no published full-year actual to score against. From 2025 the guidance stops
being a number at all -- "mid single digit", then "'mid to high teens'". This
site does not convert a phrase into endpoints, so the record simply stops. The
two full-year numbers that CAN be settled are adjusted operating expenses (13
finished years) and the adjusted effective tax rate (10).

Published numbers are company-reported or transparent arithmetic. No market
expectation, valuation or rating appears here.
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
    delivery_band,
    headroom,
    headroom_exhibit,
    number_exhibits,
    threshold_exhibit,
    threshold_table,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402

STAGING_PATH = ROOT / "series" / "cboe.json"
DATA_DIR = ROOT / "data"

# One tick a year keeps the long axes readable.
LONG_STEP = 4


def plain_text(html: str) -> str:
    """Strip tags for the slots `assets/page.js` renders through `esc()`.

    Section descriptions and the 口径与方法说明 list are escaped by the shared
    renderer, so a `<b>` written into either reaches the reader as four literal
    characters. Exhibit notes are raw innerHTML and keep their markup.
    """
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html)).strip()


def compact(period: str) -> str:
    """``2026Q2`` -> ``26Q2``."""
    return period[2:]


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100.0


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def rounded(values: list, digits: int = 6) -> list:
    return [None if v is None else round(v, digits) for v in values]


def axis(labels: list, step: int = LONG_STEP) -> list:
    """Blank every label but each ``step``-th and the last."""
    keep = set(range(len(labels) - 1, -1, -step))
    return [label if index in keep else "" for index, label in enumerate(labels)]


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


# ── the page's central statistic ────────────────────────────────────────────
def direction_steps(share: list, money: list) -> dict:
    """Count quarter-on-quarter steps where share and money disagree.

    Returns the tallies plus the per-step verdicts, so the chart note and the
    audit table are computed once from one function rather than twice from two.
    A step in which either series is flat is counted in neither tally: "did not
    move" is not a direction, and rounding a printed 23.5% makes ties real.
    """
    same = opposite = 0
    verdicts = [None]
    for index in range(1, len(share)):
        # A step needs both legs. The share line starts thirteen quarters into
        # this record, so those steps have no verdict rather than a zero one.
        if (share[index] is None or share[index - 1] is None
                or money[index] is None or money[index - 1] is None):
            verdicts.append(None)
            continue
        ds = share[index] - share[index - 1]
        dm = money[index] - money[index - 1]
        if ds == 0 or dm == 0:
            verdicts.append(None)
            continue
        if (ds > 0) == (dm > 0):
            same += 1
            verdicts.append("同向")
        else:
            opposite += 1
            verdicts.append("反向")
    return {"same": same, "opposite": opposite,
            "steps": same + opposite, "verdicts": verdicts}


def finished_years(item: dict) -> list[int]:
    return [year for year in item["years"]
            if item["by_year"][str(year)]["actual"] is not None
            and item["by_year"][str(year)]["guided"]]


def vintages(item: dict, year: int) -> tuple[list, list]:
    guided = item["by_year"][str(year)]["guided"]
    return guided[0], guided[-1]


def tally(item: dict, which: int, years: list[int]) -> dict[str, int]:
    counts = {"inside": 0, "above": 0, "below": 0}
    for year in years:
        low, high, _ = vintages(item, year)[which]
        actual = item["by_year"][str(year)]["actual"]
        counts["inside" if low <= actual <= high
               else ("above" if actual > high else "below")] += 1
    return counts


# ── section one: what can be settled, and what cannot ───────────────────────
def settled_exhibits(staging: dict) -> tuple[list[dict], list[dict], dict]:
    guide = staging["annual_guidance_history"]
    opex = guide["adjusted_operating_expenses"]
    tax = guide["adjusted_effective_tax_rate"]

    opex_years = finished_years(opex)
    opex_labels = [f"FY{y}" for y in opex_years]
    opex_last = [vintages(opex, y)[1] for y in opex_years]
    opex_actual = [opex["by_year"][str(y)]["actual"] for y in opex_years]
    opex_tally = tally(opex, 1, opex_years)
    break_index = opex_years.index(2017)
    # How far the one overshoot actually cleared the band, and how many of the
    # undershoots the company had already told anyone about. Both are computed
    # rather than typed, so a restated figure moves the sentence with it.
    over_year = next(y for y in opex_years
                     if opex["by_year"][str(y)]["actual"] > vintages(opex, y)[1][1])
    over_by = (opex["by_year"][str(over_year)]["actual"] - vintages(opex, over_year)[1][1])
    flagged = [y for y in opex_years
               if opex["by_year"][str(y)]["actual"] < vintages(opex, y)[1][0]
               and any(word in opex["by_year"][str(y)]["texts"][-1].lower()
                       for word in ("below", "lower end", "low end"))]

    charts = [delivery_band(
        "EX_OPEX", "全年调整后营业费用", opex_labels,
        [g[0] for g in opex_last], [g[1] for g in opex_last], opex_actual,
        fmt="f0c", ylab="US$M", unit="US$M",
        venue="业绩新闻稿", timing="该年<b>当年内最后一次</b>", period_word="年",
        break_at=break_index,
        break_label="Bats 交割（2017-02-28）：口径换过一次",
        extra_note=(
            f"<b>{len(opex_years)} 个已完结年度里，落在区间内 {opex_tally['inside']} 次、"
            f"跌破下限 {opex_tally['below']} 次、超出上限 {opex_tally['above']} 次。</b>"
            "这是本页唯一一条既有数字指引、又有公司自己印出来的全年实际值的记录，"
            "所以它是唯一能真正结清的一条。"
            f"<b>这条记录几乎是单边的</b>：{opex_tally['below']} 次低于下限，"
            f"而唯一一次超出上限是 FY{over_year}，只超了 US${over_by:.1f}M —— "
            "在一条 US$413–415M 的带子上，那等于压着线。"
            f"{opex_tally['below']} 次低于下限里只有 FY{flagged[0]} 一次是<b>提前说过的</b>："
            "该年 10 月那期新闻稿写的是「预计略低于 US$211.0–215.0M 的指引区间」，"
            "其余各次都是在 10 月或 11 月刚重申过区间之后落在区间下方。"
            "竖线那一年不要连着读：2017 年 2 月那版指引是 US$214–218M，"
            "写明「不含拟收购的 Bats」；同年 5 月那版跳到 US$415–423M，已含 Bats。"
            "两版之间隔着一次收购，不是一次费用暴涨。"
            "FY2017 的实际值取<b>合并口径</b>的 US$415.3M，"
            "因为它要对照的指引就是按合并口径给的；"
            "同一份新闻稿里另有一个「如实合并」口径的 US$386.6M（Bats 自 2 月 28 日起并表），"
            "拿它去对 US$413–415M 的指引会凭空造出一次巨大的超预期。"),
        src_extra=("指引与实际均取自各期业绩 8-K EX-99.1；"
                   "2013–2016 年公司称其为「core operating expenses」，"
                   "2017 年 5 月起改称「adjusted operating expenses」。"),
    )]

    tax_years = finished_years(tax)
    tax_labels = [f"FY{y}" for y in tax_years]
    tax_last = [vintages(tax, y)[1] for y in tax_years]
    tax_actual = [tax["by_year"][str(y)]["actual"] for y in tax_years]
    tax_tally = tally(tax, 1, tax_years)
    charts.append(delivery_band(
        "EX_TAX", "全年调整后有效税率", tax_labels,
        [g[0] for g in tax_last], [g[1] for g in tax_last], tax_actual,
        fmt="pct1", ylab="%", unit="%",
        venue="业绩新闻稿", timing="该年<b>当年内最后一次</b>", period_word="年",
        extra_note=(
            f"第二条能结清的记录：{len(tax_years)} 个已完结年度里区间内 "
            f"{tax_tally['inside']} 次、低于下限 {tax_tally['below']} 次、"
            f"高于上限 {tax_tally['above']} 次。"
            "这一条的标签在 2013–2017 年间来回改过 —— 同一个区间，"
            "2 月那期叫「consolidated effective tax rate」，年中几期叫「adjusted」，"
            "2018 年起统一成「effective tax rate on adjusted earnings」。"
            "本页按内容归到一条线上，因为三个名字指的是同一个数。"),
        src_extra=("各期业绩 8-K EX-99.1。2017 年 8 月与 11 月那两期在同一句话里"
                   "先给 GAAP 区间、再给调整后合并区间，本页取<b>后者</b>；"
                   "取第一个出现的区间会拿到 GAAP 的数，那是另一个指标。"),
    ))

    growth = staging["revenue_growth_guidance"]["by_year"]
    numeric_years = sorted(y for y, row in growth.items()
                           if any(v["low"] is not None for v in row.get("total", [])))
    word_years = sorted(y for y, row in growth.items()
                        if row.get("total") and all(v["low"] is None for v in row["total"]))
    last_words = growth[word_years[-1]]["total"][-1]["text"]
    charts.append({
        "ref": "EX_GROWTH",
        "kind": "grouped_bars",
        "title": ("最想结清的那条指引结不了：有机净收入增速 "
                  f"{numeric_years[0]}–{numeric_years[-1]} 是数字，"
                  f"{word_years[0]} 起变成一句话"),
        "xlabels": [f"FY{y}" for y in numeric_years],
        "groups": [
            {"name": "当年第一次指引下限", "color": "BLUE",
             "values": [growth[y]["total"][0]["low"] for y in numeric_years]},
            {"name": "当年最后一次指引下限", "color": "NAVY",
             "values": [next(v["low"] for v in reversed(growth[y]["total"])
                             if v["low"] is not None) for y in numeric_years]},
            {"name": "当年最后一次指引上限", "color": "GOLD",
             "values": [next(v["high"] for v in reversed(growth[y]["total"])
                             if v["high"] is not None) for y in numeric_years]},
        ],
        "bar_labels": True,
        "fmt": "pct0", "label_fmt": "pct0",
        "ylab": "%（有机净收入增速指引）",
        "note": (
            "<b>这张图上没有实际值，而且两个时代各有各的原因。</b>"
            f"{numeric_years[0]}–{numeric_years[-1]} 三年公司给的是数字区间"
            "（「in the range of 5 to 7 percentage points」），"
            "但它指引的是<b>有机</b>增速，而公司从不公布有机增速的全年实际值 —— "
            "翻遍 2023、2024、2025、2026 四份 2 月新闻稿都没有这个数，"
            "所以没有可以对照的对象。"
            f"{word_years[0]} 年起连数字都没有了：最新一版的原话是"
            f"「{last_words}」。"
            "<b>本站不把一句话换算成区间端点</b>（见口径说明），"
            "所以这条线在这里就断了。"
            "顺带一提，指引变成文字的那一年，正是增速从个位数切到两位数的那一年 —— "
            "2026 年这一版已经从「mid single-digit」连升三档到「mid to high teens」，"
            "每一档都是一句话。"),
        "src_extra": ("各期业绩 8-K EX-99.1 的全年指引段；"
                      "柱子只画公司给出数字区间的年份，文字口径的年份不换算、不上图。"),
    })

    settled = staging["settled_kpi"]
    entries = settled["quantified"]
    cleared = sum(1 for e in entries
                  if headroom(e["direction"], e["threshold"], e["actual"]) >= 0)
    charts.append(headroom_exhibit(
        f"上季那份分析立的阈值里，能用申报值结清的 {len(entries)} 条："
        f"{cleared} 条守住、{len(entries) - cleared} 条越过",
        entries, "actual",
        (settled["note"] + "百分比与美元被归一化成「距阈值的余量」才能放在一根轴上；"
         "原始单位见核对抽屉。" + settled["excluded"]),
        "阈值为本地研究设定，不是公司指引；实际值取自 2026-07-31 业绩 8-K EX-99.1。",
    ))

    div = divergence_long(staging)
    share_threshold = next(e["threshold"] for e in entries
                           if e["metric"].startswith("Multi-listed"))
    charts.append(threshold_exhibit(
        f"其中最关键的一条：Multi-listed 期权市占 "
        f"{staging['divergence']['share_pct'][-1]:.1f}%，"
        f"从未跌破上季那条 {share_threshold:.0f}% 的线",
        axis([compact(q) for q in staging["divergence"]["quarters"]]),
        rounded(staging["divergence"]["share_pct"]),
        share_threshold,
        fmt="pct1", ylab="%",
        actual_name="Multi-listed 期权市占", threshold_name=f"上季阈值 {share_threshold:.0f}%",
        note=("这条线本季读 23.5%，比上季的 22.3% 还高了 1.2 个百分点，阈值没有触发。"
              "<b>但它守住的这一季，这门生意的日均收入环比少了 10.2%。</b>"
              "为什么一条没破的线仍然给错了信号，是下一节整节要回答的问题 —— "
              "见 Exhibit {EX_DIVERGE}。"),
        src_extra="各期业绩 8-K EX-99.1 的经营指标表；市占率为公司披露值。",
    ))
    return charts, [], {"opex": opex_tally, "tax": tax_tally,
                        "opex_years": opex_years, "tax_years": tax_years,
                        "numeric_years": numeric_years, "word_years": word_years}


def divergence_long(staging: dict) -> dict:
    """The multi-listed record over the whole KPI window, not the last 29.

    `divergence` in the series file is exactly the tail of `kpi` plus one
    derived column (daily revenue = ADV x RPC). Nothing about the earlier
    quarters is missing or on another basis -- they are in `kpi` already -- so
    the charts that carry this page's central argument run the full record and
    the shorter block stays as the cross-check.
    """
    kpi = staging["kpi"]
    built = {
        "quarters": kpi["quarters"],
        "period_labels": kpi["period_labels"],
        "share_pct": kpi["multi_listed_share_pct"],
        "adv_k": kpi["multi_listed_adv_k"],
        "rpc_usd": kpi["multi_listed_rpc_usd"],
    }
    built["daily_revenue_usd_m"] = [
        adv * 1000 * rpc / 1e6
        for adv, rpc in zip(built["adv_k"], built["rpc_usd"])
    ]
    # The stored block has to agree with the rebuilt one everywhere they meet,
    # or one of the two is wrong and the argument rests on the wrong half.
    stored = staging["divergence"]
    at = {quarter: index for index, quarter in enumerate(built["quarters"])}
    for index, quarter in enumerate(stored["quarters"]):
        position = at[quarter]
        for key in ("share_pct", "adv_k", "rpc_usd", "daily_revenue_usd_m"):
            assert abs(stored[key][index] - built[key][position]) < 2e-3, (quarter, key)
    return built


# ── section two: share against the money ────────────────────────────────────
def highlight_exhibits(staging: dict) -> tuple[list[dict], dict]:
    div = divergence_long(staging)
    steps = direction_steps(div["share_pct"], div["daily_revenue_usd_m"])
    labels = axis([compact(q) for q in div["quarters"]])
    # The share line starts at 2019Q2 -- Cboe did not print a multi-listed share
    # separately before then -- while ADV and RPC, and so the money, run the
    # whole window. One axis, two starts, both stated on the chart.
    share_from = next(index for index, value in enumerate(div["share_pct"])
                      if value is not None)

    charts = [{
        "ref": "EX_DIVERGE",
        "kind": "bar_line_dual",
        "title": (f"Multi-listed 期权：{len(div['quarters'])} 个季度、"
                  f"{steps['steps']} 次环比里，市占与日均收入有 "
                  f"{steps['opposite']} 次走反方向"),
        "xlabels": labels,
        "bar": {"name": "日均收入 = ADV × RPC（US$M/日）",
                "values": rounded(div["daily_revenue_usd_m"]), "color": "BLUE"},
        "line": {"name": "Multi-listed 市占（RHS）", "color": "ORANGE",
                 "values": rounded(div["share_pct"]), "yfmt": "pct1"},
        "fmt": "f2", "yfmt": "f2", "label_fmt": "f2",
        "ylab": "US$M/日", "rhs_label": "%",
        "note": (
            "<b>这是本页的核心。</b>两条线来自公司同一张表的同一列季度："
            "橙线是被引用最多的市占率，柱子是 ADV 乘 RPC —— 这门生意每天真正收到的钱。"
            f"市占那条线自己的窗口（{div['period_labels'][share_from]} 起）两端："
            f"从 {div['share_pct'][share_from]:.1f}% 落到 "
            f"{div['share_pct'][-1]:.1f}%"
            f"（{signed(div['share_pct'][-1] - div['share_pct'][share_from], 1, 'pp')}），"
            f"同期日均收入从 US${div['daily_revenue_usd_m'][share_from]:.3f}M 升到 "
            f"US${div['daily_revenue_usd_m'][-1]:.3f}M"
            f"（{signed(pct_change(div['daily_revenue_usd_m'][-1], div['daily_revenue_usd_m'][share_from]), 0)}）。"
            "<b>柱子比线长十三格，那不是缺数据。</b>"
            "ADV 与 RPC 两条公司都从 2016Q1 起按季披露，所以钱这一侧回得到 2016；"
            "而「multi-listed 市占」这个单独的百分比要到 2019Q2 才第一次印出来。"
            f"把柱子自己的全窗口两端也放在这里：US${div['daily_revenue_usd_m'][0]:.3f}M → "
            f"US${div['daily_revenue_usd_m'][-1]:.3f}M"
            f"（{signed(pct_change(div['daily_revenue_usd_m'][-1], div['daily_revenue_usd_m'][0]), 0)}）。"
            f"<b>七年里份额掉了近四分之一，钱多了两倍出头。</b>"
            f"逐季看，{steps['steps']} 次环比里 {steps['opposite']} 次两者方向相反、"
            f"{steps['same']} 次同向 —— 抛硬币大约是一半一半，"
            "所以「份额」这个变量对「钱」几乎不含信息，甚至略微反着来。"
            "本季正是反向的又一次：份额 +1.2pp，日均收入 −10.2%。"
            "上一节 Exhibit {EX_SHARE} 那条没有触发的阈值，就设在橙线上。"),
        "src_extra": ("ADV、RPC 与市占率三者都取自各期业绩 8-K EX-99.1 的经营指标表；"
                      "日均收入 = ADV（千手）× RPC（US$/手）÷ 1000，为透明自算（D）。"
                      "窗口起点是公司开始披露 multi-listed 市占率的那一季。"),
    }, {
        "ref": "EX_RPC",
        "kind": "lines",
        "title": ("两类期权的每合约收入差着一个数量级，而且走向相反："
                  f"指数期权 ${staging['kpi']['index_options_rpc_usd'][-1]:.3f}、"
                  f"multi-listed ${staging['kpi']['multi_listed_rpc_usd'][-1]:.3f}"),
        "xlabels": axis([compact(q) for q in staging["kpi"]["quarters"]]),
        "series": [
            {"name": "指数期权 RPC", "values": rounded(staging["kpi"]["index_options_rpc_usd"]),
             "color": "NAVY"},
            {"name": "Multi-listed 期权 RPC",
             "values": rounded(staging["kpi"]["multi_listed_rpc_usd"]), "color": "RED"},
        ],
        "fmt": "usd3", "yfmt": "usd3", "label_fmt": "usd3",
        "end_label": True,
        "ylab": "US$/合约",
        "note": (
            "<b>这是上一张图为什么会发生的机制。</b>Cboe 的期权业务其实是两门生意："
            "指数期权是它独家挂牌的自有产品，"
            f"RPC 从 ${staging['kpi']['index_options_rpc_usd'][0]:.3f} 一路走到 "
            f"${staging['kpi']['index_options_rpc_usd'][-1]:.3f}，几乎只往上；"
            "multi-listed 是十几家交易所挂同一批合约、靠返点抢单流的同质化市场，"
            f"RPC 在 ${min(v for v in staging['kpi']['multi_listed_rpc_usd'] if v):.3f}–"
            f"${max(v for v in staging['kpi']['multi_listed_rpc_usd'] if v):.3f} 之间来回，"
            "本季环比 −20.0%。"
            "<b>在后一门生意里，量和价是可以互换的</b> —— 多给返点就能买到份额，"
            "份额涨和单价跌是同一个动作的两面。"
            "所以只盯量、或只盯价、或只盯份额的阈值都会失效，"
            "唯一不会失效的是两者的乘积。"),
        "src_extra": "各期业绩 8-K EX-99.1 的经营指标表；两条都是公司披露值。",
    }]

    off = staging["offexchange"]
    off_steps = direction_steps(off["share_pct"], off["daily_revenue_usd_k"])
    charts.append({
        "ref": "EX_OFF",
        "kind": "bar_line_dual",
        "title": (f"同一形状在股票撮合里重演：场外大宗 {len(off['quarters'])} 季、"
                  f"{off_steps['steps']} 次环比里 {off_steps['opposite']} 次反向"),
        "xlabels": axis([compact(q) for q in off["quarters"]]),
        "bar": {"name": "日均收入 = ADV × net capture（US$千/日）",
                "values": rounded(off["daily_revenue_usd_k"]), "color": "BLUE"},
        "line": {"name": "场外大宗市占（RHS）", "color": "ORANGE",
                 "values": rounded(off["share_pct"]), "yfmt": "pct1"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$千/日", "rhs_label": "%",
        "note": (
            "把同样的算术搬到另一门生意上，形状没变："
            f"份额从 {off['share_pct'][0]:.1f}% 走到 {off['share_pct'][-1]:.1f}%，"
            f"日均收入从 US${off['daily_revenue_usd_k'][0]:,.0f} 走到 "
            f"US${off['daily_revenue_usd_k'][-1]:,.0f}。"
            f"{off_steps['steps']} 次环比里 {off_steps['opposite']} 次反向 —— "
            "比 multi-listed 那张更接近一半一半，但结论一样："
            "份额单独看不构成信号。"
            "本季这条尤其扎眼：份额同比 +3.9pp 是全公司最漂亮的一条，"
            "而每百股 net capture 同比 −29.3%。"),
        "src_extra": ("ADV（百万股）与 net capture（US$/百股）取自各期 EX-99.1 经营指标表；"
                      "日均收入 = ADV × 10⁶ ÷ 100 × net capture ÷ 1000，为透明自算（D）。"),
    })

    cashm = staging["cash_markets"]
    charts.append({
        "ref": "EX_ONEX",
        "kind": "bar_line_dual",
        "title": (f"交易所内侧则是反过来的：美股市占从 {cashm['us_share_pct'][0]:.1f}% "
                  f"腰斩到 {cashm['us_share_pct'][-1]:.1f}%，每百股 net capture 回到原点"),
        "xlabels": axis([compact(q) for q in cashm["quarters"]]),
        "bar": {"name": "美股交易所市占", "values": rounded(cashm["us_share_pct"]),
                "color": "BLUE"},
        "line": {"name": "每百股 net capture（US$，RHS）", "color": "ORANGE",
                 "values": rounded(cashm["us_net_capture_per_100"]), "yfmt": "usd3"},
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1",
        "ylab": "%", "rhs_label": "US$/百股",
        "note": (
            f"{len(cashm['quarters'])} 个季度，份额掉了 "
            f"{cashm['us_share_pct'][-1] - cashm['us_share_pct'][0]:.1f} 个百分点，"
            f"而 net capture 从 ${cashm['us_net_capture_per_100'][0]:.3f} 到 "
            f"${cashm['us_net_capture_per_100'][-1]:.3f} —— 首尾同一个数。"
            "<b>这条线的分母是全美股票成交量，包含场外</b>，"
            "所以它下滑的另一半正是上一张图里那门场外生意在长大："
            "同一家公司在交易所里让出份额、在场外买进份额，"
            "两边的价格走向也正好相反。公司没有在任何一期新闻稿里定义过这个分母，"
            "本页据行业口径与序列本身没有断点这一点来读它。"),
        "src_extra": "各期业绩 8-K EX-99.1 经营指标表；两条都是公司披露值。",
    })

    seg = staging["segments"]
    # This used to draw the last 20 of the 37 reconciled quarters this file
    # already holds. The excuse on record said the five-segment structure "begins
    # 2021Q3; the earlier structure had different segments" -- but the series
    # itself runs to 2017Q2 with no break, so the axis was short by a hardcoded
    # number, not by anything about the filings.
    tail = len(seg["quarters"])
    seg_labels = [compact(q) for q in seg["quarters"][-tail:]]
    charts.append({
        "ref": "EX_SEG",
        "kind": "grouped_bars",
        "title": (f"五个分部的净收入，加上一条读者容易漏掉的第六行："
                  f"Options US${seg['options'][-1]:,.1f}M 占 "
                  f"{seg['options'][-1] / seg['total'][-1] * 100:.1f}%"),
        "xlabels": axis(seg_labels, 2),
        "groups": [
            {"name": "Options", "color": "NAVY", "values": rounded(seg["options"][-tail:])},
            {"name": "North American Equities", "color": "BLUE",
             "values": rounded(seg["north_american_equities"][-tail:])},
            {"name": "Europe and Asia Pacific", "color": "GOLD",
             "values": rounded(seg["europe_and_apac"][-tail:])},
            {"name": "Futures", "color": "GREEN", "values": rounded(seg["futures"][-tail:])},
            {"name": "Global FX", "color": "ORANGE", "values": rounded(seg["global_fx"][-tail:])},
            {"name": "Corporate / Digital", "color": "RED",
             "values": rounded(seg["corporate_digital"][-tail:])},
        ],
        "fmt": "f0c", "label_fmt": "f0c", "ylab": "US$M",
        "note": (
            "<b>第六根柱子是负的，而且大多数读者不会去找它。</b>"
            "分部表里那一行在两个时代是两样东西：2017–2022 年叫 Corporate，"
            "小额为正或为零；2022Q4–2024Q4 叫 Digital，"
            "是 2022 年 5 月收购、随后关掉的 Cboe Digital，"
            "净收入<b>为负</b>（表本身是扣掉收入成本之后的口径），最深一季 −US$1.7M；"
            "2025Q1 起这一行消失。"
            "只取前五行会在 37 个季度里的 25 个对不上公司自己印的合计，"
            "而差额还会中途换号 —— 六行相加则 37 季全部对平，"
            "这也是本页把它画出来而不是抹掉的原因。"
            "窗口只画最近 20 季；2017Q1 不画，因为 Bats 自 2017-02-28 才并表，"
            "那一季的三个分部是一个月对着别人的三个月。"),
        "src_extra": ("各期业绩 8-K EX-99.1 的分部表，逐季取自同一份新闻稿；"
                      "六行相加与公司印出的合计在 37 个季度里全部一致（容差 0.05）。"),
    })

    nr = staging["net_revenue_window"]
    pass_through = [round(r / t * 100, 6) if t else None
                    for r, t in zip(nr["regulatory_fees_cost"], nr["total_revenues"])]
    charts.append({
        "ref": "EX_WEDGE",
        "kind": "stacked_dual",
        "title": (f"毛收入与净收入之间那道楔子：本季总收入 US${nr['total_revenues'][-1]:,.1f}M，"
                  f"留下的净收入 US${nr['net_revenue'][-1]:,.1f}M"),
        "xlabels": axis([compact(q) for q in nr["quarters"]]),
        "stacks": [
            {"name": "流动性返点", "color": "BLUE", "values": rounded(nr["liquidity_payments"])},
            {"name": "Section 31 等监管规费（代收代付）", "color": "GOLD",
             "values": rounded(nr["regulatory_fees_cost"])},
            {"name": "路由清算与版税等", "color": "ORANGE",
             "values": rounded([a + b for a, b in zip(nr["routing_and_clearing"],
                                                      nr["royalty_and_other_cost"])])},
            {"name": "净收入（公司自己的头条口径）", "color": "NAVY",
             "values": rounded(nr["net_revenue"])},
        ],
        "line": {"name": "监管规费占总收入 (RHS)", "color": "RED",
                 "values": rounded(pass_through), "yfmt": "pct1", "ymax": 30},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M", "ylab2": "规费占比",
        "note": (
            "<b>「总收入」这条线一半以上不属于公司。</b>四段自下而上是付给流动性提供方的返点、"
            "代 SEC 收取再上缴的监管规费、路由清算与指数版税，"
            "以及公司真正留下的净收入 —— 也是它自己每期头条用的口径。"
            f"规费那一段在本窗口里从 US${min(nr['regulatory_fees_cost']):,.1f}M 到 "
            f"US${max(nr['regulatory_fees_cost']):,.1f}M 之间开关式跳动："
            "<b>本季 US$153.9M，上一季是 US$0M</b>，费率由 SEC 定、不由公司定。"
            "它同时进收入和进成本，所以对净收入几乎没有影响 —— "
            "本季收入端 US$"
            f"{nr['regulatory_fees_revenue'][-1]:,.1f}M、成本端 US${nr['regulatory_fees_cost'][-1]:,.1f}M。"
            "<b>只把成本端剥掉、不同时剥收入端，会把一个中性项读成一次巨大的收入注水</b> —— "
            "喂给本页的那份本地分析上季正是这么错的，本季自己更正了过来。"),
        "src_extra": ("各期业绩 8-K EX-99.1 的合并损益表；四段相加等于总收入，"
                      "38 个季度逐季核对无差。红线为自算（D）。"),
    })
    return charts, {"steps": steps, "off_steps": off_steps}


# ── section three: the same question pointed forward ────────────────────────
def next_exhibits(staging: dict) -> list[dict]:
    kpi = staging["next_kpi"]
    entries = kpi["quantified"]
    safe = sum(1 for e in entries
               if headroom(e["direction"], e["threshold"], e["current"]) >= 0)
    charts = [headroom_exhibit(
        f"下季 {len(entries)} 条阈值：当前值离阈值的余量，{safe} 条仍在安全侧",
        entries, "current",
        ("正值表示仍在安全侧。阈值为本地研究设定，<b>不是公司指引</b>。"
         "<b>其中第一条是本页这次唯一改动过的一条</b> —— 上季那份分析把它写在市占率上，"
         "本页按 Exhibit {EX_DIVERGE} 的记录改写在日均收入上。" + kpi["excluded"]),
        "当前值为 2026Q2 披露值或本页自算；阈值为本地研究设定。",
    )]

    div = divergence_long(staging)
    money_threshold = next(e["threshold"] for e in entries
                           if e["metric"].startswith("Multi-listed 日均收入"))
    charts.append(threshold_exhibit(
        f"改写后的第一条：Multi-listed 日均收入 US${div['daily_revenue_usd_m'][-1]:.3f}M/日",
        axis([compact(q) for q in div["quarters"]]),
        rounded(div["daily_revenue_usd_m"]),
        money_threshold,
        fmt="f2", ylab="US$M/日",
        actual_name="日均收入（ADV × RPC）", threshold_name=f"阈值 US${money_threshold:.2f}M/日",
        note=("和上一节 Exhibit {EX_SHARE} 画的是同一门生意的同一批季度，"
              "只是纵轴换成了钱。"
              "<b>两张图给出的信号在本季是相反的</b>：那张的线没有触发，这张环比 −10.2%。"
              "阈值取上一季的水平 —— 连续两季低于它，才说明这不是一次波动。"),
        src_extra="ADV 与 RPC 为公司披露值，乘积为自算（D）。",
    ))

    long = staging["long"]
    opex_threshold = next(e["threshold"] for e in entries
                          if e["metric"].startswith("调整后营业费用"))
    charts.append(threshold_exhibit(
        f"季度调整后营业费用：本季 US${long['adj_opex'][-1]:.1f}M，"
        f"已越过上季设下的 US$215M",
        axis([compact(q) for q in long["quarters"]]),
        rounded(long["adj_opex"]),
        opex_threshold,
        fmt="f0c", ylab="US$M",
        actual_name="调整后营业费用（季）", threshold_name=f"阈值 US${opex_threshold:.0f}M",
        note=("上季那条线设在 US$215M，本季实际 US$216.7M，是三条能结清的阈值里唯一越过的一条。"
              "全年指引 US$838–853M 表面上「重申」，但公司在同一场电话会里说明其中含"
              "澳洲出售带来的 US$11M 减项 —— <b>同口径其实是上调</b>。"
              "上半年已经花掉 US$"
              f"{long['adj_opex'][-2] + long['adj_opex'][-1]:.1f}M，"
              "按指引上限倒推，下半年只剩约每季 US$214M 的额度，低于本季的实际值。"
              f"<b>这条线自己的记录有 {len(long['quarters'])} 个季度</b>，"
              f"从 {long['period_labels'][0]} 的 US${long['adj_opex'][0]:.1f}M 起 —— "
              f"整段窗口里落在 US${opex_threshold:.0f}M 之上的有 "
              f"{sum(1 for v in long['adj_opex'] if v > opex_threshold)} 季，"
              "阈值守的是「下一季会不会继续超」，不是「历史上从未超过」。"),
        src_extra="各期业绩 8-K EX-99.1 的非 GAAP 调节表；指引取自同一份新闻稿的全年指引段。",
    ))
    return charts


# ── section four: the routine long series ───────────────────────────────────
def routine_exhibits(staging: dict) -> list[dict]:
    long = staging["long"]
    kpil = staging["kpi_long"]
    cats = staging["categories"]
    cap = staging["capital"]

    charts = [{
        "ref": "EX_MARGIN",
        "kind": "lines",
        "title": (f"{len(long['quarters'])} 个季度的调整后营业利润率："
                  f"从 {long['adj_op_margin_pct'][0]:.1f}% 到 "
                  f"{long['adj_op_margin_pct'][-1]:.1f}%"),
        "xlabels": axis([compact(q) for q in long["quarters"]]),
        "series": [
            {"name": "调整后营业利润率", "values": rounded(long["adj_op_margin_pct"]),
             "color": "NAVY"},
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1",
        "ylab": "%",
        "note": (
            "本季 70.4%，环比降 2.0 个百分点，而降的这一段全部来自费用端 —— "
            "净收入环比几乎没动（+0.4%），调整后费用环比 +7.9%。"
            f"窗口内的高点是 {max(long['adj_op_margin_pct']):.1f}%，"
            f"低点 {min(long['adj_op_margin_pct']):.1f}%。"
            "<b>这条线的分母在 2017 年 2 月之后才是「净收入」口径</b>，"
            "之前 CBOE Holdings 的收入里没有那么大的过路项；"
            "利润率在 2017 年前后的台阶主要是这次口径变化与 Bats 并表，不是经营效率的跳变。"),
        "src_extra": "各期业绩 8-K EX-99.1 的非 GAAP 调节表；利润率为公司披露值。",
    }, {
        "ref": "EX_INDEX",
        "kind": "bar_line_dual",
        "title": (f"独家产品那门生意：指数期权 ADV 从 {kpil['index_options_adv_k'][0]:,.0f} 千手"
                  f"到 {kpil['index_options_adv_k'][-1]:,.0f} 千手，RPC 同期只往上"),
        "xlabels": axis([compact(q) for q in kpil["quarters"]]),
        "bar": {"name": "指数期权 ADV（千手）",
                "values": rounded(kpil["index_options_adv_k"]), "color": "BLUE"},
        "line": {"name": "指数期权 RPC（US$，RHS）", "color": "ORANGE",
                 "values": rounded(kpil["index_options_rpc_usd"]), "yfmt": "usd3"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "千手/日", "rhs_label": "US$/合约",
        "note": (
            f"{len(kpil['quarters'])} 个季度 —— 本页最长的一条线，"
            "因为 Bats 没有指数期权也没有期货，这两行在收购前后指的是同一件事，"
            "2016 年四个重叠季度里新旧两张表印的数字完全相同。"
            "<b>量涨了五倍，价没有被摊薄</b>："
            f"ADV {kpil['index_options_adv_k'][-1] / kpil['index_options_adv_k'][0]:.1f} 倍，"
            f"RPC 从 ${kpil['index_options_rpc_usd'][0]:.3f} 到 "
            f"${kpil['index_options_rpc_usd'][-1]:.3f}。"
            "这正是它与 multi-listed 那门生意的分野（Exhibit {EX_RPC}）："
            "独家挂牌的产品不需要用返点买单流，所以份额这个概念在这里根本不存在 —— "
            "公司也从不为指数期权披露市占率。"),
        "src_extra": "各期业绩 8-K EX-99.1 的经营指标表；两条都是公司披露值。",
    }, {
        "ref": "EX_CATS",
        "kind": "grouped_bars",
        "title": (f"公司自己的第二套口径：Derivatives US${cats['derivatives'][-1]:,.1f}M、"
                  f"Cash and Spot US${cats['cash_and_spot'][-1]:,.1f}M、"
                  f"Data Vantage US${cats['data_vantage'][-1]:,.1f}M"),
        "xlabels": axis([compact(q) for q in cats["quarters"]], 2),
        "groups": [
            {"name": "Derivatives", "color": "NAVY", "values": rounded(cats["derivatives"])},
            {"name": "Cash and Spot Markets", "color": "BLUE",
             "values": rounded(cats["cash_and_spot"])},
            {"name": "Data Vantage", "color": "GOLD", "values": rounded(cats["data_vantage"])},
        ],
        "bar_labels": False,
        "fmt": "f0c", "label_fmt": "f0c", "ylab": "US$M",
        "note": (
            "公司并行发布两套口径：上一节那张按<b>分部</b>（Options / 北美股票 / 欧洲亚太 / "
            "期货 / 外汇），这张按<b>业务类别</b>。两套不可混用，但都加总到同一个净收入 —— "
            f"本季三类相加 US${cats['derivatives'][-1] + cats['cash_and_spot'][-1] + cats['data_vantage'][-1]:,.1f}M。"
            f"Data Vantage 这条从 US${cats['data_vantage'][0]:,.1f}M 走到 "
            f"US${cats['data_vantage'][-1]:,.1f}M，"
            f"占净收入的比重从 {cats['data_vantage'][0] / (cats['derivatives'][0] + cats['cash_and_spot'][0] + cats['data_vantage'][0]) * 100:.1f}% "
            f"到 {cats['data_vantage'][-1] / (cats['derivatives'][-1] + cats['cash_and_spot'][-1] + cats['data_vantage'][-1]) * 100:.1f}%，"
            "<b>这几年几乎没动</b> —— 它跟着成交量一起长，而不是独立于成交量在长。"),
        "src_extra": "各期业绩 8-K EX-99.1 的业务类别表；起点是公司开始印这张表的那一季。",
    }]

    price = cap["buyback_avg_price_usd"]
    charts.append({
        "ref": "EX_CAP",
        "kind": "bar_line_dual",
        "title": (f"回购与股息：本季回购 US${cap['buyback_usd_m'][-1]:.1f}M、"
                  f"股息 US${cap['dividends_paid_usd_m'][-1]:.1f}M，"
                  f"回购均价 US${price[-1]:,.2f}"),
        "xlabels": axis([compact(q) for q in cap["quarters"]]),
        "bar": {"name": "当季回购金额（US$M）",
                "values": rounded(cap["buyback_usd_m"]), "color": "BLUE"},
        "line": {"name": "回购均价（US$/股，RHS）", "color": "ORANGE",
                 "values": rounded(price), "yfmt": "f0c"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M", "rhs_label": "US$/股",
        "note": (
            "柱子有几季是空的，那几季公司没有回购，不是数据缺失。"
            "<b>橙线只画公司自己印出均价的那些季度</b> —— 其余季度留空而不是用金额除以股数补上，"
            "把一个自算值混进一条公司披露值的线里，读者无法分辨哪个是哪个。"
            f"本季回购 US${cap['buyback_usd_m'][-1]:.1f}M，环比 "
            f"{signed(pct_change(cap['buyback_usd_m'][-1], cap['buyback_usd_m'][-2]), 1)}，"
            f"均价从 US${price[-2]:,.2f} 降到 US${price[-1]:,.2f}。"
            f"资产负债表这一侧：调整后现金 US${cap['adjusted_cash_usd_m'][-1]:,.1f}M、"
            f"总债务 US${cap['total_debt_usd_m'][-1]:,.1f}M。"),
        "src_extra": "各期业绩 8-K EX-99.1 的资本管理段；均价为公司披露值，缺则留空。",
    })
    return charts


def build_payload(staging: dict) -> dict:
    settled_ex, _, stats = settled_exhibits(staging)
    highlight_ex, counts = highlight_exhibits(staging)
    next_ex = next_exhibits(staging)
    routine_ex = routine_exhibits(staging)

    all_ex = number_exhibits(settled_ex + highlight_ex + next_ex + routine_ex, start=1)
    # `threshold_exhibit` and `headroom_exhibit` return dicts without a `ref`,
    # so the two that other captions point at get theirs assigned here rather
    # than by editing board.py, which four other pages share.
    settled_ex[-1]["ref"] = "EX_SHARE"
    resolve_exhibit_refs(all_ex)
    a, b, c = len(settled_ex), len(highlight_ex), len(next_ex)
    settled_ex, highlight_ex = all_ex[:a], all_ex[a:a + b]
    next_ex, routine_ex = all_ex[a + b:a + b + c], all_ex[a + b + c:]

    fin = staging["financials"]
    periods = staging["periods"]
    div = divergence_long(staging)
    first_share = next(index for index, value in enumerate(div["share_pct"])
                       if value is not None)
    seg = staging["segments"]
    guide = staging["annual_guidance_history"]
    steps = counts["steps"]
    first_table = len(all_ex) + 1

    def verdict(low, high, actual):
        return "区间内" if low <= actual <= high else ("高于上限" if actual > high else "低于下限")

    opex = guide["adjusted_operating_expenses"]
    opex_rows = []
    for year in opex["years"]:
        block = opex["by_year"][str(year)]
        if not block["guided"]:
            continue
        first, last = block["guided"][0], block["guided"][-1]
        actual = block["actual"]
        opex_rows.append([
            f"FY{year}", str(len(block["guided"])),
            f"${first[0]:,.0f}–{first[1]:,.0f}", f"${last[0]:,.0f}–{last[1]:,.0f}",
            "未完结" if actual is None else f"${actual:,.1f}",
            "—" if actual is None else verdict(last[0], last[1], actual),
        ])

    tax = guide["adjusted_effective_tax_rate"]
    tax_rows = []
    for year in tax["years"]:
        block = tax["by_year"][str(year)]
        if not block["guided"]:
            continue
        first, last = block["guided"][0], block["guided"][-1]
        actual = block["actual"]
        tax_rows.append([
            f"FY{year}", f"{first[0]:.1f}–{first[1]:.1f}%", f"{last[0]:.1f}–{last[1]:.1f}%",
            "未完结" if actual is None else f"{actual:.1f}%",
            "—" if actual is None else verdict(last[0], last[1], actual),
        ])

    growth = staging["revenue_growth_guidance"]["by_year"]
    growth_rows = []
    for year in sorted(growth):
        for vintage in growth[year].get("total", []):
            span = ("—" if vintage["low"] is None
                    else f"{vintage['low']:.0f}–{vintage['high']:.0f}%")
            growth_rows.append([
                f"FY{year}", vintage["release"], span,
                "数字区间" if vintage["low"] is not None else "文字口径",
                re.sub(r"\s+", " ", vintage["text"]).replace("•", "").strip()[:150],
            ])

    div_rows = []
    for index, quarter in enumerate(div["quarters"]):
        verdict_step = steps["verdicts"][index]
        div_rows.append([
            f"Q{quarter[5]} {quarter[:4]}",
            f"{div['adv_k'][index]:,.0f}",
            f"${div['rpc_usd'][index]:.3f}",
            ("—" if div["share_pct"][index] is None
             else f"{div['share_pct'][index]:.1f}%"),
            f"${div['daily_revenue_usd_m'][index]:.3f}M",
            verdict_step or "—",
        ])

    seg_rows = [[f"Q{q[5]} {q[:4]}",
                 f"{seg['options'][i]:,.1f}",
                 f"{seg['north_american_equities'][i]:,.1f}",
                 f"{seg['europe_and_apac'][i]:,.1f}",
                 f"{seg['futures'][i]:,.1f}",
                 f"{seg['global_fx'][i]:,.1f}",
                 f"{seg['corporate_digital'][i]:,.1f}",
                 f"{seg['total'][i]:,.1f}"]
                for i, q in enumerate(seg["quarters"])]

    tables = [
        {"n": first_table,
         "title": "全年调整后营业费用：年初指引、当年最后一次指引与实际（US$M）",
         "headers": ["年度", "指引次数", "年初第一次", "当年最后一次", "全年实际", "对最后一次"],
         "rows": opex_rows},
        {"n": first_table + 1,
         "title": "全年调整后有效税率：指引与实际（%）",
         "headers": ["年度", "年初第一次", "当年最后一次", "全年实际", "对最后一次"],
         "rows": tax_rows},
        {"n": first_table + 2,
         "title": "有机净收入增速指引的每一版：数字区间与文字口径",
         "headers": ["年度", "发布日", "区间", "形式", "原文"],
         "rows": growth_rows},
        {"n": first_table + 3,
         "title": "Multi-listed 期权：ADV、RPC、市占与日均收入，逐季方向对照",
         "headers": ["季度", "ADV（千手）", "RPC", "市占", "日均收入 D", "与市占同向？"],
         "rows": div_rows},
        {"n": first_table + 4,
         "title": "分部净收入六行与公司印出的合计（US$M）",
         "headers": ["季度", "Options", "North American Equities", "Europe and Asia Pacific",
                     "Futures", "Global FX", "Corporate / Digital", "合计"],
         "rows": seg_rows},
        threshold_table(first_table + 5, "上季阈值与本季实际值（原始单位）",
                        staging["settled_kpi"]["quantified"], "actual", "本季实际值"),
        threshold_table(first_table + 6, "下季阈值与当前值（原始单位）",
                        staging["next_kpi"]["quantified"], "current", "当前值"),
        ai_capex_cycle_table(first_table + 7),
    ]

    latest_release = staging["release_dates"][-1]
    return {
        "schema_version": "quarterly-dashboard/cboe-v1",
        "page": {"slug": "cboe", "language": "zh-CN"},
        "company": {
            "ticker": "CBOE",
            "name": "Cboe Global Markets, Inc.",
            "group": "exchanges",
            "accounting_standard": "US GAAP",
        },
        "latest": {
            "disclosed_period_label": "Q2 2026",
            "full_financial_period_label": "Q2 2026",
            "period_end": staging["period_ends"][-1],
            "release_date": latest_release,
            "analysis_date": "2026-08-29",
            "audit_status": "unaudited",
            "status": "history_ready",
        },
        "tracker": "Watchlist Quarterly Tracker · CBOE",
        "title": "Cboe Global Markets, Inc. (CBOE)：Q2 2026 季报仪表盘",
        "subtitle": (
            f"截至 {staging['period_ends'][-1]} · 发布 {latest_release} · US GAAP · 未审计 · "
            "自然年财年，季度标注无需换算"
        ),
        "headline": plain_text(
            f"净收入 US${fin['net_revenue'][-1]:,.1f}M、同比 "
            f"{signed(pct_change(fin['net_revenue'][-1], fin['net_revenue'][-5]))}，"
            f"调整后营业利润率 {fin['adj_op_margin_pct'][-1]:.1f}%。"
            "但本页的对象不是这个季度 —— Cboe 每季在同一张表里印出市占率和每合约收入，"
            "而两者相乘才是这门生意每天挣到的钱。"
            f"在公司同时披露这三个数的 "
            f"{sum(1 for value in div['share_pct'] if value is not None)} 个季度里，"
            f"市占与日均收入的 {steps['steps']} 次环比有 {steps['opposite']} 次方向相反；"
            f"那段窗口里市占掉了 "
            f"{abs(div['share_pct'][-1] - div['share_pct'][first_share]):.1f} 个百分点，"
            f"日均收入却涨了 "
            f"{pct_change(div['daily_revenue_usd_m'][-1], div['daily_revenue_usd_m'][first_share]):.0f}%。"
            "上一季那份分析把阈值设在市占率上，本季它没有触发，而同一门生意的日均收入环比少了 10.2%。"
        ),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>记录</span><b>份额与钱，七年里有六成的季度走反方向</b>'
            f'<p>{steps["steps"]} 次环比里 {steps["opposite"]} 次相反、{steps["same"]} 次同向。'
            f'市占 {div["share_pct"][first_share]:.1f}% → {div["share_pct"][-1]:.1f}%，'
            f'日均收入 US${div["daily_revenue_usd_m"][0]:.3f}M → '
            f'US${div["daily_revenue_usd_m"][-1]:.3f}M。</p></article>'
            '<article><span>结不清</span><b>最想结清的那条指引，两个时代各有各的原因</b>'
            f'<p>{stats["numeric_years"][0]}–{stats["numeric_years"][-1]} 有数字但指引的是'
            '「有机」增速，公司从不公布它的全年实际；'
            f'{stats["word_years"][0]} 起指引变成一句话。能结清的只有费用与税率两条。</p></article>'
            '<article><span>本季</span><b>过路项开关式跳动，只剥一边就会读错</b>'
            f'<p>监管规费成本本季 US${staging["net_revenue_window"]["regulatory_fees_cost"][-1]:,.1f}M、'
            '上一季 US$0M。它同时进收入与成本，对净收入近乎中性。</p></article>'
            '</div>'
        ),
        "source": (
            'Source: <a href="https://www.sec.gov/Archives/edgar/data/1374310/'
            '000162828026051217/cboe-20260731xex991.htm" rel="noopener">Cboe Q2 2026 '
            '业绩新闻稿（8-K EX-99.1）</a>与截至 2026-06-30 的 10-Q。'
        ),
        "source_url": (
            "https://www.sec.gov/Archives/edgar/data/1374310/"
            "000162828026051217/cboe-20260731xex991.htm"
        ),
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {"id": "settled", "title": "一、上季兑现了吗",
             "description": plain_text(
                 "这一节先说清楚哪些东西能结清、哪些不能，再结清能结的。"
                 "Cboe 每期业绩新闻稿都给一份全年指引并在当年逐季修订，"
                 "但六条指引里只有两条既是数字、又有公司自己印出来的全年实际值可以对照。"
                 "读者最想看的那条 —— 收入增速 —— 恰好两样都不占全。"
                 "第二样是上一份本地分析立的阈值，其中能用申报值结清的三条。"),
             "exhibits": settled_ex},
            {"id": "quarter_highlights", "title": "二、本季重点",
             "description": plain_text(
                 "本页的核心在这一节：市占率和每合约收入印在同一张表里，"
                 "而它们相乘才是这门生意每天挣到的钱。"
                 "三门生意、三条不同的窗口，形状是同一个。"
                 "最后两张是读这张表之前必须先看懂的两件事："
                 "分部表里那条负的第六行，以及毛收入与净收入之间那道过路项的楔子。"),
             "exhibits": highlight_ex},
            {"id": "next_quarter", "title": "三、下季要跟踪什么",
             "description": plain_text(
                 "同样的问题指向下一季。上季那份分析的第一条阈值设在市占率上，"
                 "本页按第二节的记录把它改写在日均收入上 —— "
                 "这是本页对那份分析唯一改动过的一条，理由全部在 Exhibit 里。"),
             "exhibits": next_ex},
            {"id": "routine", "title": "四、长期常规",
             "description": plain_text(
                 "CBOE 专属的常规序列：十四年的调整后营业利润率、"
                 "本页最长的一条线（指数期权的量与价，五十九个季度）、"
                 "公司自己的第二套收入口径，以及回购与它实际付出的价格。"),
             "exhibits": routine_ex},
        ],
        "tables": tables,
        "notes": [plain_text(p) for p in [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，"
            "每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "Cboe 为自然年财年（12 月 31 日结束），本页季度标注与公司口径一致，无需换算。",
            "本页最需要说明的一条：公司在每份业绩新闻稿的经营指标表里，"
            "把市占率、平均日成交量与每合约收入并排印出，而三者之中只有后两者的乘积是收入。"
            "把阈值设在市占率上，在 multi-listed 期权这类同质化市场里会失效，"
            "因为那里量和价可以互换 —— 多给返点就能买到份额。"
            "本页第二节用公司自己的披露值把这件事画出来，第三节据此改写了跟踪指标。",
            "日均收入是本页最重要的自算值：multi-listed 为 ADV（千手）乘 RPC（US$/手）再除以一千，"
            "得到 US$M/日；场外大宗为 ADV（百万股）乘每百股 net capture 再换算，得到 US$千/日。"
            "两个乘数都是公司披露值，乘法本身没有任何假设，标 D。",
            "经营指标表每份新闻稿印五个季度，相邻两份重叠四季。本页把它们拼成长序列，"
            "并用重叠季逐项交叉核对；重叠处出现分歧的，一律采用较晚那份的印刷值，"
            "分歧本身记录在下面的来源说明里。",
            "全年调整后营业费用的记录跨着一次收购：2017 年 2 月那版指引是 CBOE Holdings 单体口径、"
            "写明不含拟收购的 Bats，同年 5 月起改为含 Bats 的合并口径。"
            "本页在图上画了断点，并且 FY2017 的实际值取合并口径的 US$415.3M —— "
            "同一份新闻稿里另有一个 US$386.6M 的如实合并数，"
            "拿它去对合并口径的指引会凭空造出一次巨大的超预期。",
            "有机净收入增速的指引不进任何一张兑现图。2022–2024 年公司给的是数字区间，"
            "但它指引的是「有机」增速，而公司从不公布有机增速的全年实际值，没有可对照的对象；"
            "2025 年起指引本身变成文字（「mid single digit」「mid to high teens」），"
            "本站不把文字换算成区间端点。两个时代的原因不同，结果一样：结不清。",
            "分部表有第六行，而且在两个时代是两样东西：2017–2022 年是 Corporate，"
            "2022Q4–2024Q4 是 Digital（2022 年 5 月收购、随后关掉的 Cboe Digital，净收入为负），"
            "2025Q1 起消失。只取前五行会在 37 个季度里的 25 个对不上公司印出的合计，"
            "而差额还会中途换号；六行相加则 37 季全部对平。",
            "分部序列从 2017Q2 起画，不回补 2017Q1：Bats 自 2017-02-28 才并表，"
            "那一季的北美股票、欧洲与外汇三个分部是一个月，与前后各季的三个月不可比。"
            "2013–2016 年公司只报单一业务，没有分部表，因此这段窗口在本页根本不存在。",
            "指数期权与期货的量价序列回溯到 2011Q4，比其余经营指标长十七个季度："
            "Bats 既没有指数期权也没有期货，这两行在收购前后指的是同一件事，"
            "并且在 2016 年的四个重叠季度里，新旧两张表印出的 ADV 与 RPC 完全相同。"
            "其余各行不这样回补，因为收购前的口径是 CBOE 单体，与合并口径不是一个数。",
            "监管规费（Section 31 等）是代收代付：公司向会员收取再上缴 SEC，"
            "同一笔金额同时计入收入与收入成本，对净收入近乎中性。"
            "本季成本端 US$153.9M、上一季 US$0M，费率由 SEC 决定。"
            "只把成本端剥掉而不同时剥掉收入端，会把一个中性项误读成一次巨大的收入注水。",
            "回购均价只画公司自己印出这个数的季度，其余留空。"
            "用当季回购金额除以股数可以补出一个数，但那是自算值，"
            "混进一条公司披露值的线里读者无法分辨；本页宁可留空。",
            "本页不发布评级、目标价、估值与任何券商共识，也不发布公司未在申报文件中给出的数字。"
            "上一季那份本地分析里引用的若干口径 —— 例如 SPX 期权的日均成交量 —— "
            "只出现在电话会里、不在业绩新闻稿的经营指标表内，因此不进本页的任何序列。",
        ]],
        "footer": "Quarterly Results · 公司披露值与透明自算 · 仅供研究",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "cboe.js"), payload, "cboe")
    shell_dir = ROOT / "cboe"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("CBOE", "cboe"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(
        f"CBOE page: {charts} charts in {len(payload['sections'])} sections "
        f"+ {len(payload['tables'])} audit tables"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
