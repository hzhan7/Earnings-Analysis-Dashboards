#!/usr/bin/env python3
"""Build the NIKE quarterly-results page.

Same four-part, chart-led shape as the other company pages (上季兑现 → 本季重点
→ 下季跟踪 → 长期常规).  NIKE's fiscal year ends 31 May, so every label here is
the calendar quarter the fiscal one mostly covers: the three months ended
2026-05-31 are the company's FY2026 Q4 and this page's ``Q2 2026``.

**NIKE files no quarterly outlook, and that is a sourcing fact rather than an
editorial choice.**  Forty earnings releases from FY2017 Q1 to FY2026 Q4 were
read end to end and not one carries an operating outlook; the releases say in as
many words that "Revised guidance will be provided on the conference call".  So
the object the Cadence / Synopsys / TSMC / NVIDIA / Meta / Amazon / Broadcom /
S&P Global / Moody's / MSCI / TJX pages are built on does not exist here.

What NIKE filed instead is longer-dated and, unusually, now finished.  Three
times it wrote a set of multi-year financial goals into the MD&A of its 10-K --
through fiscal 2020, through fiscal 2023, and through fiscal 2025 -- and each
window has closed, so the filed record settles all fourteen of them.  The last
vintage, set in July 2021, missed on all six.  Two of its targets asked for
numbers NIKE has not printed once in the thirteen filed years: a gross margin in
the high 40s against a record high of 46.2%, and an EBIT margin in the high
teens against a record high of 15.5%.  The FY2022 10-K still refers to "our
long-term financial goals" without restating one, and the four 10-Ks since
contain no financial goal at all -- while the ROIC and EBIT-margin calculations
those goals were struck on are still published every year.  What disappeared is
the target, not the measurement.  A new set is due at the investor day announced
for 2026-11-16/17.

The mechanism behind the misses is visible in the same filings, which is why the
long section is built around it: NIKE Direct went from 20.3% of NIKE Brand
revenue in fiscal 2014 to 43.7% in fiscal 2023, and consolidated gross margin
never made a new high after fiscal 2016.  The channel mix moved as promised; the
margin it was supposed to buy did not arrive, and the selling-and-administrative
ratio rose 3.2 points instead.

Published numbers are company-reported or transparent arithmetic.  The one block
that is not from a filing is the outlook table, and it is labelled as such.
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


STAGING_PATH = ROOT / "series" / "nke.json"
DATA_DIR = ROOT / "data"


def compact_period(period: str) -> str:
    """``'Q2 2026'`` → ``'Q2'26'``."""
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


def fy_label(year: int) -> str:
    return f"FY{year}"


def fiscal_to_calendar(fiscal: str) -> str:
    """``'FY2018Q3'`` → ``'Q1 2018'``.

    NIKE's year ends 31 May, so its Q1 and Q2 fall in the previous calendar year
    and its Q3 and Q4 in the same one. This is the same mapping the series file
    applies to the quarterly arrays; it is repeated here only because the
    2017-2018 guidance record carries fiscal labels of its own.
    """
    year, quarter = int(fiscal[2:6]), int(fiscal[7])
    return f"Q{quarter + 2} {year - 1}" if quarter <= 2 else f"Q{quarter - 2} {year}"


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    """``+3.0%`` / ``−17.0%``, with a typographic minus.

    Python's ``+`` flag emits an ASCII hyphen, and this page's prose uses U+2212
    throughout -- so a title built with the flag and a sentence built by hand
    print two different characters for the same sign, side by side.
    """
    return f"{value:+.{digits}f}{suffix}".replace("-", "−")


def rounded(values: list[float | None], digits: int = 6) -> list[float | None]:
    return [None if value is None else round(value, digits) for value in values]


def resolve_exhibit_refs(exhibits: list[dict]) -> list[dict]:
    """Substitute ``{ref}`` placeholders with the numbers `number_exhibits` assigned."""
    numbers = {exhibit["ref"]: exhibit["n"] for exhibit in exhibits if exhibit.get("ref")}
    for exhibit in exhibits:
        exhibit.pop("ref", None)
        for field in ("title", "note", "src_extra", "annot"):
            text = exhibit.get(field)
            if not isinstance(text, str):
                continue
            for key, number in numbers.items():
                text = text.replace("{" + key + "}", str(number))
            exhibit[field] = text
    return exhibits


SOURCE_10K = (
    "多年财务目标逐字读自各年 10-K 的 MD&A：FY2016/FY2017 两份写「截至 FY2020」那一轮，"
    "FY2018/FY2019/FY2020 三份写「截至 FY2023」那一轮，FY2021 一份写「截至 FY2025」那一轮；"
    "交付值取自各年 10-K 的 RESULTS OF OPERATIONS 表与 Use of Non-GAAP 一节的 "
    "EBIT Margin / ROIC 计算表。"
)

WORDS_NOTE = (
    "<b>先读这一句，再读命中与否。</b>NIKE 的目标是用词写的，不是端点："
    "high single-digit、mid-teens、high 40s、high teens、low thirties。"
    "图上的区间是本页对这些词的读法（7–9%、14–16%、47–49%、17–19%、30–33%），"
    "写在这里是因为它是本页的口径而不是公司的算术。"
    "凡是结论会随读法翻转的那一条，本页标为「取决于读法」而不是替读者选一边。"
)

CALL_NOTE = (
    "本页没有「指引兑现」记录组图，这是取数限制而不是编辑取舍："
    "本站清点了 FY2017 Q1 到 FY2026 Q4 的 40 份业绩新闻稿，"
    "<b>没有一份带经营指引</b>，公司自己在稿子里写着 "
    "Revised guidance will be provided on the conference call。"
)


# ── section one: last quarter's thresholds, then NIKE's own filed goals ──────
def prior_threshold_charts(staging: dict) -> list[dict]:
    growth = staging["growth_pct"]
    periods = [compact_period(period) for period in staging["periods"]]
    settled = staging["prior_kpi_settlement"]
    china = [float(value) for value in growth["greater_china_currency_neutral"]]
    america = [float(value) for value in growth["north_america_currency_neutral"]]
    return [
        headroom_exhibit(
            "上季四道门槛：两道加仓门没够着，两道减仓门没碰到 —— 一个动作都没触发",
            settled, "actual",
            note=(
                "<b>这张图上的负值不是「越线」，是「没够着」。</b>"
                "上季设的每条指标都写成一道加仓门加一道减仓门，中间留空，"
                "所以每个指标画两根柱：对着加仓门是「还差多少」，对着减仓门是「还剩多少余量」。"
                "本季两个能算的指标都落在自己的两道门之间 —— "
                "北美固定汇率 +3%，够不着 +5% 的加仓门、也远在 +1% 之上；"
                "大中华区 −17%，够不着 −15% 的加仓门、也没跌破 −25%。"
                "<b>五条指标里另外三条本季根本无法结清，原因写在下面的核对表里：</b>"
                "一条要的是按地域拆的毛利率，NIKE 任何一份申报文件都不披露；"
                "两条的测量窗口整个落在 FY2027。"
                "一份四条阈值全落在中间、三条无法测量的框架，本季度对仓位没有说任何话。"
            ),
            src_extra="阈值为上季本地研究设定，不是公司指引；当前值取自本季业绩 8-K 的 DIVISIONAL REVENUES 表。",
        ),
        threshold_exhibit(
            f"大中华区收入同比（固定汇率）八季：本季 {signed(china[-1], 0)}，好于公司自己的 −20% 指引，"
            "但仍在加仓门之外",
            periods, china, -15.0,
            fmt="pct0", ylab="%", actual_name="大中华区收入同比（固定汇率）",
            threshold_name="上季加仓门槛 −15%",
            note=(
                "红线是上季设的加仓门。本季 −17%：<b>比公司三个月前给的 −20% 指引好 3 个百分点，"
                "却仍在门槛之外</b> —— 好于公司自己的预期与好到能改变仓位，是两件事。"
                "报表口径是 −12%，两者差 5 个百分点全是汇率；阈值当初是按固定汇率设的，图上画的也是它。"
                "这条线八季里有七季为负，最深的一季是 −20%。"
            ),
            src_extra="各季业绩 8-K 的 DIVISIONAL REVENUES 表，公司同时印出报表与固定汇率两个增速。",
        ),
        threshold_exhibit(
            f"北美收入同比（固定汇率）八季：本季 {signed(america[-1], 0)}，连续第四季为正",
            periods, america, 5.0,
            fmt="pct0", ylab="%", actual_name="北美收入同比（固定汇率）",
            threshold_name="上季加仓门槛 +5%",
            note=(
                "北美从 FY2025 那四季的 −11%/−8%/−4%/−11% 转正，已连续四季为正，"
                "但本季 +3% 离 +5% 的加仓门还有距离，也没接近 +1% 的观察门。"
                "<b>这一季的北美利润要单独读：</b>分部 EBIT 报表值 2,000（同比 +91%），"
                "里面装着 965 的 IEEPA 关税退款；剔除后 1,035，同比 −1%，"
                "这个口径是公司自己在新闻稿脚注里给的。"
            ),
            src_extra="各季业绩 8-K 的 DIVISIONAL REVENUES 与 EARNINGS BEFORE INTEREST AND TAXES 两张表。",
        ),
    ]


def filed_target_charts(staging: dict) -> tuple[list[dict], dict]:
    """The three vintages of multi-year goals NIKE wrote into its own 10-K.

    This is the closest thing NIKE has to the guidance-delivery record the other
    pages carry, and it differs in the two ways that make it worth building: the
    horizon is years rather than a quarter, and it is *finished* -- every window
    has closed, so the filed record settles each goal rather than leaving the
    last one pending.
    """
    targets = staging["filed_targets"]
    history = staging["long_history"]
    years = history["fiscal_years"]
    labels = [fy_label(year) for year in years]
    latest = next(v for v in targets["vintages"] if v["key"] == "fy2025")

    # Every goal on one axis: distance from the near bound of its own target, in
    # percent of that bound. Six goals in four different units (a growth rate, a
    # margin level, a return, a capex ratio) do not otherwise share a chart.
    entries = [
        {"metric": goal["metric"], "direction": "up", "threshold": goal["lo"],
         "unit": "pct", "actual": goal["delivered"]}
        for goal in latest["goals"]
    ]
    record = targets["record_levels"]

    gross_margin = history["gross_margin_pct"]
    ebit_margin = history["ebit_margin_pct"]
    roic_years = [year for year, value in zip(years, history["roic_pct"]) if value is not None]
    roic = [value for value in history["roic_pct"] if value is not None]

    charts = [
        headroom_exhibit(
            "公司自己写进 10-K 的最后一轮目标：六条，六条都没做到",
            entries, "actual",
            note=(
                "<b>这是 NIKE 在申报文件里给过的最后一组数字承诺。</b>"
                "FY2021 的 10-K（2021-07-20 报出）写下六条「截至 FY2025」的目标，"
                "四年窗口已经走完，六条全部落在目标之外 —— 图上六根柱没有一根为正。"
                "六条里五条是差得不够，只有资本开支那条反过来：公司说要花到收入的 3%，"
                f"FY2022–FY2025 四年平均只花了 {latest['goals'][-1]['delivered']:.2f}%。"
                + WORDS_NOTE
            ),
            src_extra=SOURCE_10K,
        ),
        threshold_exhibit(
            f"十三年毛利率：FY2025 目标要求 high 40s，而这条线的最高点是 FY{record['max_gross_margin_fiscal_year']} 的 "
            f"{record['max_gross_margin_pct']:.1f}%",
            labels, rounded(gross_margin), 47.0,
            fmt="pct1", ylab="%", actual_name="毛利率（报表口径）",
            threshold_name="FY2025 目标下限 47%（high 40s）",
            note=(
                "<b>红线一次都没有被碰到过。</b>公司在 FY2021 的 10-K 里写下"
                "「Gross margin rate in the high 40s by fiscal 2025」，"
                f"而十三年里这条线的最高点是 FY{record['max_gross_margin_fiscal_year']} 的 "
                f"{record['max_gross_margin_pct']:.1f}%，比目标下限还低 "
                f"{47.0 - record['max_gross_margin_pct']:.1f} 个百分点。"
                f"FY2025 实际报出 {gross_margin[-2]:.1f}%。"
                f"<b>FY2026 的 {gross_margin[-1]:.1f}% 比 FY2025 高，但那是报表口径：</b>"
                "里面含 986 的 IEEPA 关税退款，剔除后是 40.8%，反而是十三年最低。"
                "把「high 40s」读成 47% 还是 49%，不改变这张图的结论。"
            ),
            src_extra="各年 10-K 的 RESULTS OF OPERATIONS 表；毛利率为公司印出的值。",
        ),
        threshold_exhibit(
            f"十三年 EBIT 利润率：FY2025 目标要求 high teens，最高点是 FY{record['max_ebit_margin_fiscal_year']} 的 "
            f"{record['max_ebit_margin_pct']:.1f}%",
            labels, rounded(ebit_margin), 17.0,
            fmt="pct1", ylab="%", actual_name="EBIT 利润率",
            threshold_name="FY2025 目标下限 17%（high teens）",
            note=(
                "和上一张同一种情形，而且差得更远："
                "「EBIT Margin in the high teens by fiscal 2025」对上 FY2025 实际的 "
                f"{ebit_margin[-2]:.1f}%，差 {17.0 - ebit_margin[-2]:.1f} 个百分点；"
                f"十三年最高的一年是 FY{record['max_ebit_margin_fiscal_year']} 的 "
                f"{record['max_ebit_margin_pct']:.1f}%，也够不着。"
                "<b>EBIT 是公司自己定义的口径</b>（净利润加回净利息与所得税），"
                "公司只在 FY2022 起的 10-K 里印出这条比率；本图把它按同一条定义"
                "往前算到 FY2014，在五个有披露的年份里逐年复现公司印出的值，误差不超过 0.05 个百分点。"
            ),
            src_extra="FY2022 起为公司印出的 EBIT Margin；更早年份按同一定义自算（税前利润加净利息费用，除以收入）。",
        ),
        threshold_exhibit(
            f"投入资本回报率：两轮目标都设在 low 30s，FY2023 做到了 {roic[3]:.1f}%，FY2025 只有 {roic[-2]:.1f}%",
            [fy_label(year) for year in roic_years], rounded(roic), 30.0,
            fmt="pct1", ylab="%", actual_name="ROIC（公司披露）",
            threshold_name="两轮目标共同的下限 30%（low thirties）",
            note=(
                "<b>十四条目标里唯一达成的一条，和落空最惨的一条，是同一条指标。</b>"
                f"「截至 FY2023」那一轮要求 low thirties，FY2023 报出 {roic[3]:.1f}%，达成；"
                f"「截至 FY2025」那一轮要求 exceeding low 30% range，FY2025 报出 {roic[-2]:.1f}%，落空。"
                f"值得注意的是后一条目标写下时（FY2021 的 10-K），公司当年的 ROIC 是 {roic[1]:.1f}% —— "
                "<b>目标设在了当时水平的一半以下</b>，四年后仍然没做到。"
                f"FY2021 那个高点本身有分母的成分：投入资本从 FY2021 的 12.2B 长到 FY2026 的 16.4B。"
                "公司至今每年照常披露 ROIC 的完整计算表 —— 停掉的是目标，不是度量。"
            ),
            src_extra="各年 10-K 的 Use of Non-GAAP 一节，ROIC 为公司印出的值。",
        ),
    ]

    # The coda: the one stretch in which NIKE did file a next-quarter band.
    record = staging["filed_quarterly_guidance_2017_2018"]
    short = {"毛利率同比变化": "毛利率", "有效税率": "税率", "其他收支净额（含利息）": "其他收支"}
    charts.append({
        "kind": "diverging_bars",
        "title": (
            f"NIKE 唯一一段申报过的下季指引：{record['scoreable_bands']} 条区间里 "
            f"{record['landed_inside']} 条落在区间内，"
            f"{record['broke_low']} 条跌破下限、{record['broke_high']} 条穿出上限"
        ),
        "xlabels": [f"{compact_period(fiscal_to_calendar(item['period']))} {short[item['metric']]}"
                    for item in record["items"]],
        "values": [item["half_widths_from_midpoint"] for item in record["items"]],
        "legend": "距区间中值的偏离（以区间半宽为单位）",
        "positive_label": "高于中值",
        "negative_label": "低于中值",
        "fmt": "f1",
        "yfmt": "f1",
        "label_fmt": "f1",
        "ylab": "区间半宽",
        "zero_line": True,
        "note": (
            "<b>纵轴的一个单位就是区间的半宽，所以 ±1 之外就是区间之外。</b>"
            f"{record['scoreable_bands']} 条里有 {record['broke_low'] + record['broke_high']} 条在区间之外，"
            "<b>而且是两个方向都有</b> —— 这在本站是独一份。"
            "其他十一家公司的申报指引记录几乎清一色朝一个方向偏（多数是把指引当地板），"
            "NIKE 这段记录看起来像一份真的预测：会低估也会高估，最大的两次一个是 −5.2、一个是 +3.8。"
            "落在区间内的两条里，还有一条（Q3'17 的毛利率）正好压在下限上。"
            f"<b>这段记录只有八个季度，而且早已终止。</b>NIKE 只在 {record['window']} "
            "把电话会讲稿作为业绩 8-K 的另一份附件报出，2018-07-03 之后不再附；"
            "此后四个季度的业绩 8-K 只带一份新闻稿附件，长度不到讲稿的三分之一。"
            f"这八份里的下一季指引共 {sum(record['next_quarter_item_forms'].values())} 条，"
            f"只有 {record['next_quarter_item_forms']['range']} 条是带端点的区间，"
            f"{record['next_quarter_item_forms']['verbal']} 条是词、"
            f"{record['next_quarter_item_forms']['point']} 条是单点，本图只画那 "
            f"{record['next_quarter_item_forms']['range']} 条。"
            f"指引仍是随上一季业绩发布的，落在被指引那个季度的第 "
            f"{record['publication_lag_days']['min']}–{record['publication_lag_days']['max']} 天。"
        ),
        "src_extra": (
            "八份业绩 8-K 的电话会讲稿附件（Item 2.02），实际值取自随后一季 8-K 的 EX-99.1 合并损益表；"
            "偏离为实际值减区间中值再除以区间半宽的自算值。"
        ),
    })

    rows = []
    for vintage in targets["vintages"]:
        for goal in vintage["goals"]:
            unit = "%" if goal["unit"] == "pct" else "pp"
            band = (f"{goal['lo']:.1f}{unit}" if goal["lo"] == goal["hi"]
                    else f"{goal['lo']:.1f}–{goal['hi']:.1f}{unit}")
            alt = goal.get("alt_base_delivered")
            delivered = f"{goal['delivered']:.2f}{unit}"
            if alt is not None:
                delivered += f"（改用前一年为基年则 {alt:.2f}{unit}）"
            rows.append([
                vintage["label"], vintage["set_on"], goal["metric"], goal["words"],
                band, delivered,
                {"miss": "未达成", "hit": "达成", "boundary": "压在边界上",
                 "base_dependent": "取决于基年"}[goal["verdict"]],
            ])
        for item in vintage["not_settleable"]:
            rows.append([vintage["label"], vintage["set_on"], item["metric"], item["words"],
                         "—", "—", "无法结清：" + item["reason"]])
    table = {
        "title": "NIKE 写进 10-K 的三轮多年财务目标，及其结清情况",
        "headers": ["目标窗口", "写下的日期", "指标", "公司原文", "本页读作", "实际交付", "判定"],
        "rows": rows,
    }
    return charts, table


# ── section two: what actually moved ────────────────────────────────────────
def quarter_highlight_charts(staging: dict) -> list[dict]:
    fin = staging["financials"]
    seg = staging["segments_usd_m"]
    margins = staging["segment_margins_pct"]
    growth = staging["growth_pct"]
    one_off = staging["one_off_usd_m"]
    severance = staging["severance"]
    balance = staging["balance_sheet_usd_m"]
    long_q = staging["long_quarters"]
    periods = [compact_period(period) for period in staging["periods"]]

    reported = fin["gross_margin_pct"][-1]
    ex_refund = fin["gross_margin_ex_tariff_refund_pct"][-1]
    refund_pp = reported - ex_refund
    severance_pp = one_off["severance_q4_cost_of_sales"] / fin["revenue_usd_m"][-1] * 100
    year_ago = fin["gross_margin_pct"][-5]

    china_revenue = long_q["greater_china_revenue"]
    china_margin = long_q["greater_china_ebit_margin_pct"]
    long_labels = [compact_period(period) for period in long_q["periods"]]

    refund_receivable = one_off["ieepa_receivable_at_period_end"]
    receivable = balance["accounts_receivable_net"]

    return [
        {
            "kind": "bridge_bar",
            "title": (
                f"本季毛利率 {reported:.2f}% 拆到底：{refund_pp:.2f} 个百分点是一次性关税退款，"
                f"{severance_pp:.2f} 个百分点是埋在销货成本里的遣散费用"
            ),
            "xlabels": ["报表毛利率", "IEEPA 关税退款", "销货成本内的遣散费用", "两项都剔除后"],
            "stacks": [{"name": "毛利率构成", "color": "NAVY",
                        "values": [reported, -refund_pp, severance_pp, None]}],
            "net": {"name": "两项都剔除后的毛利率",
                    "values": [None, None, None, round(ex_refund + severance_pp, 4)]},
            "fmt": "pct2",
            "yfmt": "pct2",
            "label_fmt": "pct2",
            "ylab": "%",
            "note": (
                f"<b>报表毛利率同比 +8.9 个百分点，剔除退款后是 −0.1 个百分点。</b>"
                f"去年同期 {year_ago:.2f}%。986 的 IEEPA 退款是公司在最高法院 2026-02-20 裁定后"
                "把回收认定为 probable 才计入的，全额冲减销货成本，其中北美 965、Converse 21。"
                f"<b>第三根柱是本页对本地笔记的一处更正：</b>Q4 新增的遣散费用是 "
                f"{one_off['severance_q4_total']:.0f}，不是把 10-Q 印的「三个月 230」当成年初至今"
                f"推出来的约 170 —— 申报的九个月数是 {severance['fy2026_nine_months_total_usd_m']:.0f}、"
                f"全年 {severance['total_usd_m'][-1]:.0f}，差出来就是 {one_off['severance_q4_total']:.0f}。"
                f"其中落在销货成本的是 {one_off['severance_q4_cost_of_sales']:.0f}，"
                f"落在经营费用的是 {one_off['severance_q4_operating_overhead']:.0f}（一笔冲回）。"
                "所以两项都剔除后的毛利率是 41.12%，比去年同期高 0.85 个百分点 —— "
                "而不是笔记里的 1.4 个百分点。"
            ),
            "src_extra": (
                "退款金额与科目见 FY2026 10-K 的 OTHER MATTERS 与附注一；"
                "遣散费用见 10-K 附注十八与 FY2026 Q3 的 10-Q 附注十三，季度值为两者之差。"
            ),
        },
        {
            "kind": "grouped_bars",
            "title": (
                "五个分部的本季增速：报表与固定汇率的差，在大中华区是 5 个百分点，"
                "在 EMEA 也是 5 个"
            ),
            "xlabels": ["北美", "EMEA", "大中华区", "APLA", "Converse"],
            "groups": [
                {"name": "报表口径同比", "color": "BLUE",
                 "values": [float(growth[f"{key}_reported"][-1]) for key in
                            ("north_america", "emea", "greater_china", "apla", "converse")]},
                {"name": "固定汇率同比", "color": "NAVY",
                 "values": [float(growth[f"{key}_currency_neutral"][-1]) for key in
                            ("north_america", "emea", "greater_china", "apla", "converse")]},
            ],
            "fmt": "pct0",
            "yfmt": "pct0",
            "label_fmt": "pct0",
            "ylab": "%",
            "note": (
                "<b>本季汇率是顺风，而且不是均匀的。</b>合并口径报表 −1%、固定汇率 −4%；"
                "分到地域上，北美两个口径相同，EMEA 是 −1% 对 −6%，大中华区是 −12% 对 −17%。"
                "上季设的阈值按固定汇率写，本页也按固定汇率结清 —— "
                "用报表口径去对一条按固定汇率设的门槛，等于让汇率替公司过线。"
            ),
            "src_extra": "各季业绩 8-K 的 DIVISIONAL REVENUES 表，两个增速都是公司印出的整数百分比。",
        },
        {
            "kind": "lines",
            "title": (
                f"四个地域的 EBIT 利润率 {len(long_labels)} 季："
                f"北美本季 {margins['north_america_ebit_margin_pct'][-1]:.1f}% "
                "里有 20 个百分点是关税退款"
            ),
            "xlabels": long_labels,
            "xstep": 4,
            "series": [
                {"name": "北美", "values": rounded(long_q["north_america_ebit_margin_pct"]),
                 "color": "NAVY"},
                {"name": "EMEA", "values": rounded(long_q["emea_ebit_margin_pct"]),
                 "color": "BLUE"},
                {"name": "大中华区", "values": rounded(long_q["greater_china_ebit_margin_pct"]),
                 "color": "GOLD"},
                {"name": "APLA", "values": rounded(long_q["apla_ebit_margin_pct"]),
                 "color": "GREEN"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "end_label": True,
            "ylab": "%",
            "note": (
                "<b>北美最后那一跳是会计，不是经营。</b>965 的退款全部记在北美，"
                f"占它本季收入的 {965 / seg['north_america_revenue'][-1] * 100:.1f} 个百分点；"
                f"剔除后北美 EBIT 是 1,035、利润率 {1035 / seg['north_america_revenue'][-1] * 100:.1f}%，"
                "同比 −1%。"
                "<b>另外三条线才是这一季的实际形状：</b>EMEA 从 25.1% 掉到 14.6%，"
                "大中华区在 13.4% 与 28.9% 之间来回，APLA 一直是四个里最稳的一条。"
                "分部利润率的分子是公司披露的 EBIT，分母是同一张表上的分部收入，两条腿都是申报值。"
                f"<b>八季的窗口把这四条线画成一组平行的波动，{len(long_labels)} 季不是。</b>"
                f"大中华区在这段记录里从 {long_q['greater_china_ebit_margin_pct'][0]:.1f}% 起步、"
                f"最高到 {max(long_q['greater_china_ebit_margin_pct']):.1f}%、"
                f"最低 {min(long_q['greater_china_ebit_margin_pct']):.1f}%，"
                "而 EMEA 与 APLA 的区间要窄得多 —— 四条线的排序换过多次，"
                "近八季的那个排序不是常态。"
            ),
            "src_extra": "各季业绩 8-K 的 EARNINGS BEFORE INTEREST AND TAXES 表与 DIVISIONAL REVENUES 表。",
        },
        {
            "kind": "bar_line",
            "title": (
                f"大中华区四十个季度：收入从 {max(china_revenue):,.0f} 的高点回到 {china_revenue[-1]:,.0f}，"
                f"而利润率还在 {china_margin[-1]:.1f}%"
            ),
            "xlabels": long_labels,
            "bar": {"name": "大中华区收入", "color": "BLUE", "values": china_revenue},
            "line": {"name": "大中华区 EBIT 利润率", "color": "RED", "values": rounded(china_margin)},
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "US$M / %",
            "note": (
                "八个季度看不出这条线在说什么，四十个可以。"
                f"收入的高点是 {long_labels[china_revenue.index(max(china_revenue))]} 的 "
                f"{max(china_revenue):,.0f}，本季 {china_revenue[-1]:,.0f}，"
                f"退回到 {round(pct_change(china_revenue[-1], max(china_revenue)))}%。"
                "<b>但利润率没有跟着走完同样的路：</b>这条红线在 2020 年的疫情季触到过 "
                f"{min(v for v in china_margin if v is not None):.1f}%，此后大部分时间在 20% 上下，"
                f"本季 {china_margin[-1]:.1f}% —— 高于 EMEA、低于 APLA。"
                "管理层这一季的说法是 profitability will bottom before sales；"
                "这张图给的是它的起点，不是它的验证。"
            ),
            "src_extra": "四十个季度的分部收入与 EBIT 均为申报值；FY2017 四季用的是 FY2018 各季申报文件里的重述比较列。",
        },
        {
            "kind": "bar_line",
            "title": (
                f"应收账款八季：本季 {receivable[-1]:,.0f}，同比 "
                f"{signed(pct_change(receivable[-1], receivable[-5]))}，其中 {refund_receivable:,.0f} 是关税退款应收"
            ),
            "xlabels": periods,
            "bar": {"name": "应收账款净额", "color": "NAVY", "values": receivable},
            "line": {"name": "剔除关税退款应收后的应收账款 D", "color": "RED",
                     "values": [None] * 7 + [receivable[-1] - refund_receivable]},
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "US$M",
            "note": (
                f"应收同比 {signed(pct_change(receivable[-1], receivable[-5]))}，"
                f"剔除 {refund_receivable:,.0f} 的退款应收后是 "
                f"{signed(pct_change(receivable[-1] - refund_receivable, receivable[-5]))} —— "
                "仍然偏高，与批发占比回升是一致的。"
                "<b>上季笔记把这笔应收列为最大的未完成项（金额、时点与减值风险都不确定），"
                "而 10-K 在九天后就把它结清了：</b>公司写明年末已收现 302、余额 684，"
                "且「Subsequent to May 31, 2026, we received substantially all of the remaining "
                "IEEPA tariff receivable」，全文没有任何减值准备。"
                "笔记自算的 686 与申报的 684 差 2，这里用申报值。"
            ),
            "src_extra": "应收账款为各季资产负债表申报值；退款应收金额与收现表述见 FY2026 10-K 的 OTHER MATTERS。",
        },
        {
            "kind": "grouped_bars",
            "title": (
                f"三年遣散与重组费用按科目：FY2026 共 {severance['total_usd_m'][-1]:.0f}，"
                f"其中销货成本 {severance['cost_of_sales_usd_m'][-1]:.0f}"
            ),
            "xlabels": [fy_label(year) for year in severance["fiscal_years"]],
            "groups": [
                {"name": "计入经营费用", "color": "NAVY", "values": severance["operating_overhead_usd_m"]},
                {"name": "计入销货成本", "color": "GOLD", "values": severance["cost_of_sales_usd_m"]},
            ],
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "US$M",
            "note": (
                "<b>科目分布是这张图的重点，不是总额。</b>"
                "FY2024 那一轮 443 里只有 64 落在销货成本，FY2026 这一轮 385 里落了 154 —— "
                "同样叫「重组」，一轮压的是费用率，一轮压的是毛利率。"
                f"FY2025 公司写明没有新的费用发生，只付了 {severance['cash_paid_usd_m'][1]:.0f} 的现金。"
                f"截至本季末仍有 {severance['remaining_accrual_usd_m']:.0f} 挂在应计负债里。"
                "<b>公司只按季度与年初至今披露，不按科目拆到季，</b>"
                "所以本页不画按季的遣散费用曲线，只在毛利率桥上用两个申报数的差给出 Q4 那一格。"
            ),
            "src_extra": "FY2026 10-K 附注十八与 FY2024 10-K 的重组附注，均为申报值。",
        },
    ]


# ── section three: the thresholds pointed forward ───────────────────────────
def next_quarter_charts(staging: dict) -> list[dict]:
    fin = staging["financials"]
    growth = staging["growth_pct"]
    history = staging["long_history"]
    next_kpi = staging["next_kpi"]
    periods = [compact_period(period) for period in staging["periods"]]

    ex_refund = fin["gross_margin_ex_tariff_refund_pct"]
    yoy = [None if index < 4 else round(ex_refund[index] - ex_refund[index - 4], 4)
           for index in range(len(ex_refund))]
    ebit_margin = history["ebit_margin_pct"]
    labels = [fy_label(year) for year in history["fiscal_years"]]
    ex_refund_fy26 = round((history["ebit_usd_m"][-1] - 986) / history["revenue_usd_m"][-1] * 100, 4)

    return [
        headroom_exhibit(
            "下季四条门槛：三条仍有余量，一条离得最远的是那个双位数利润率目标",
            next_kpi, "current",
            note=(
                "正值是当前值离门槛还剩的余量，负值是还差多少。"
                "<b>最右那根柱是这一页真正的距离感：</b>管理层重申要回到双位数的 EBIT 利润率，"
                f"而 FY2026 剔除关税退款后的实际值是 {ex_refund_fy26:.2f}% —— "
                f"差 {10 - ex_refund_fy26:.1f} 个百分点，而且这条比率上一次到过双位数是 FY2024。"
                "两条本季无法量化的指标没有画进来，写在核对表里："
                "Sportswear 与 Jordan 的降幅公司从不披露收入，只在电话会上用 double digits 这样的词描述；"
                "经营费用增速的阈值是「不高于 0%」，零阈值没有百分比余量可算。"
            ),
            src_extra="阈值为本地研究设定，不是公司指引；当前值取自本季申报文件与自算。",
        ),
        threshold_exhibit(
            f"毛利率同比（剔除关税退款）八季：本季 {signed(yoy[-1], 2, ' 个百分点')}，离 +50bp 的加仓门还差一截",
            periods, yoy, 0.5,
            fmt="pp1", ylab="pp", actual_name="毛利率同比（剔除关税退款）D",
            threshold_name="下季加仓门槛 +50bp",
            note=(
                "<b>这条线是下一季最先见分晓的一条。</b>管理层把毛利率转正的时点从 FY2027 Q2 "
                "提前到 FY2027 Q1，说会「slightly positive」；加仓门设在 +50bp。"
                f"本季 {signed(yoy[-1], 2, ' 个百分点')}已经比公司自己给的 −25 到 −75bp 好，"
                "但仍是负的，而且这四季一路从 −4.1 个百分点收窄上来，还没有穿过零。"
                "剔除的只有 IEEPA 退款；埋在销货成本里的遣散费用没有剔，剔了本季会再高 0.95 个百分点。"
            ),
            src_extra="毛利率为收入减销货成本的自算值；关税退款金额为公司披露值，只发生在最后一季。",
        ),
        threshold_exhibit(
            f"十三年 EBIT 利润率对双位数目标：FY2026 报表 {ebit_margin[-1]:.1f}%，剔除退款 {ex_refund_fy26:.1f}%",
            labels, rounded(ebit_margin), 10.0,
            fmt="pct1", ylab="%", actual_name="EBIT 利润率（报表口径）",
            threshold_name="管理层重申的双位数目标 10%",
            note=(
                "把同一条线换一条红线再看一次：上一节那张画的是公司写进 10-K 的 17%，这张画的是"
                "管理层如今口头重申的双位数。"
                f"十三年里有十年在红线之上，最近两年在下面 —— FY2025 {ebit_margin[-2]:.1f}%、"
                f"FY2026 报表 {ebit_margin[-1]:.1f}%，而 FY2026 剔除 986 的退款后只有 {ex_refund_fy26:.1f}%。"
                "<b>公司要跨的不是一个百分点的坎，是四个。</b>"
                "这条目标目前只存在于电话会，没有进任何一份申报文件；"
                "按公司公告，2026-11-16/17 的投资者日会给出更新后的长期财务目标。"
            ),
            src_extra="EBIT 利润率的口径与上一节同一条；剔除退款的 FY2026 值为自算。",
        ),
    ]


# ── section four: the long routine series ───────────────────────────────────
def routine_charts(staging: dict) -> list[dict]:
    history = staging["long_history"]
    cash = staging["cash_history"]
    channel_q = staging["channel_quarters"]
    buyback = staging["buyback_programme"]
    years = history["fiscal_years"]
    labels = [fy_label(year) for year in years]
    cash_labels = [fy_label(year) for year in cash["fiscal_years"]]

    direct_share = history["nike_direct_share_pct"]
    gross_margin = history["gross_margin_pct"]
    peak_index = direct_share.index(max(direct_share))
    gm_peak_index = gross_margin.index(max(gross_margin))

    quarterly_share = channel_q["nike_direct_share_pct"]
    quarterly_labels = [compact_period(period) for period in channel_q["periods"]]

    repurchase = cash["share_repurchases_usd_m"]
    dividends = cash["dividends_paid_usd_m"]
    operating = cash["operating_cash_flow_usd_m"]
    capex = cash["capital_expenditures_usd_m"]

    price_years = sorted(buyback["annual_shares_m"])
    prices = [round(buyback["annual_cost_usd_m"][year] / buyback["annual_shares_m"][year], 2)
              for year in price_years]

    return [
        {
            "kind": "bar_line",
            "title": (
                f"十三年直营占比与毛利率：直营从 {direct_share[0]:.1f}% 升到 "
                f"{max(direct_share):.1f}% 再退到 {direct_share[-1]:.1f}%，"
                f"而毛利率此后再没有超过 FY{years[gm_peak_index]}"
            ),
            "xlabels": labels,
            "bar": {"name": "NIKE Direct 占 NIKE Brand 收入 D", "color": "BLUE",
                    "values": rounded(direct_share)},
            "line": {"name": "毛利率（报表口径）", "color": "RED", "values": rounded(gross_margin)},
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "ylab": "%",
            "note": (
                "<b>这是本页最长的一条记录，也是上一节那些目标为什么落空的机制。</b>"
                "转向直营的整个理由是它毛利更高，而把两条线画在一起，"
                f"十三年里直营占比涨了 {max(direct_share) - direct_share[0]:.1f} 个百分点"
                f"（FY{years[0]} 的 {direct_share[0]:.1f}% → FY{years[peak_index]} 的 {max(direct_share):.1f}%），"
                f"毛利率的最高点却停在 FY{years[gm_peak_index]} 的 {max(gross_margin):.1f}%，"
                f"那一年直营才 {direct_share[gm_peak_index]:.1f}%。"
                "<b>占比最高的 FY2023，毛利率是 43.5%，比 FY2016 低 2.7 个百分点。</b>"
                "两条腿都是申报值：占比的分子分母都在 10-K 的 Supplemental NIKE Brand Revenues Details 表里，"
                "毛利率在同一份文件的 RESULTS OF OPERATIONS 表里，占比是一次除法。"
                "口径连续性：FY2017 及更早这条线叫 Sales Direct to Consumer，"
                "FY2018 起改名 Sales through NIKE Direct，FY2018 的 10-K 用新名字重印了前两年且数值相同，"
                "所以是改名不是换口径。"
            ),
            "src_extra": "各年 10-K 的 Supplemental NIKE Brand Revenues Details 与 RESULTS OF OPERATIONS 两张 MD&A 正文表。",
        },
        {
            "kind": "grouped_bars",
            "title": (
                f"十三年两个渠道的绝对额：批发本财年 {history['wholesale_usd_m'][-1]:,.0f}，"
                f"直营 {history['nike_direct_usd_m'][-1]:,.0f}，两年前是 27,758 对 21,519"
            ),
            "xlabels": labels,
            "groups": [
                {"name": "批发", "color": "NAVY", "values": history["wholesale_usd_m"]},
                {"name": "NIKE Direct", "color": "BLUE", "values": history["nike_direct_usd_m"]},
            ],
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "bar_labels": False,
            "ylab": "US$M",
            "note": (
                "上一张画的是比例，这张画的是钱，两张一起才看得出本财年的形状："
                f"NIKE Brand 收入同比 +1%，而批发 {signed(pct_change(history['wholesale_usd_m'][-1], history['wholesale_usd_m'][-2]))}、"
                f"直营 {signed(pct_change(history['nike_direct_usd_m'][-1], history['nike_direct_usd_m'][-2]))} —— "
                "<b>全年那点增长完全来自公司过去七年一直在压缩的那个渠道。</b>"
                "公司自己在 FY2026 的毛利率归因里写了同一件事："
                "仓储与物流成本下降使毛利率提高约 20 个基点，primarily due to channel mix。"
                "直营的绝对额已连续两年下降，回到 FY2021 与 FY2022 之间的水平。"
            ),
            "src_extra": "各年 10-K 的 Supplemental NIKE Brand Revenues Details 表，申报值。",
        },
        {
            "kind": "lines",
            "title": (
                f"三十二个季度的直营占比：从 {quarterly_share[0]:.1f}% 到 "
                f"{max(quarterly_share):.1f}% 再到本季 {quarterly_share[-1]:.1f}%"
            ),
            "xlabels": quarterly_labels,
            "series": [{"name": "NIKE Direct 占 NIKE Brand 收入 D",
                        "values": rounded(quarterly_share), "color": "NAVY"}],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "end_label": True,
            "ylab": "%",
            "note": (
                "年度那张图看不出季节性，这张看得出：直营占比在每年的假日季最高、在批发发货季最低，"
                "所以季度线要和四个季度前比而不是和上一季比。"
                f"本季 {quarterly_share[-1]:.1f}%，四个季度前 {quarterly_share[-5]:.1f}%。"
                "<b>这条记录只能从 FY2019 起画：</b>渠道拆分是 ASC 606 的收入分解附注，"
                "NIKE 在 FY2019（2018 年 6 月起的财年）才开始按这个准则披露，往前没有可比的数。"
                "每年的会计季 Q4 是全年数减九个月数的差分值（渠道拆分只在收入附注里，业绩新闻稿不印），"
                "两条腿都是申报值。"
            ),
            "src_extra": "各季 10-Q 与各年 10-K 的 REVENUES 附注（收入分解表）。",
        },
        {
            "kind": "lines",
            "title": (
                f"十三年两条费用率：需求创造费用 {history['demand_creation_pct_of_revenue'][-1]:.1f}%、"
                f"经营费用 {history['operating_overhead_pct_of_revenue'][-1]:.1f}%，"
                f"合计 {history['sga_pct_of_revenue'][-1]:.1f}% 是十三年最高"
            ),
            "xlabels": labels,
            "series": [
                {"name": "经营费用率", "values": rounded(history["operating_overhead_pct_of_revenue"]), "color": "NAVY"},
                {"name": "需求创造费用率（营销）", "values": rounded(history["demand_creation_pct_of_revenue"]), "color": "GOLD"},
                {"name": "两项合计", "values": rounded(history["sga_pct_of_revenue"]), "color": "RED"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "end_label": True,
            "ylab": "%",
            "note": (
                "<b>直营那条曲线的账，是在这张图上付的。</b>"
                "「截至 FY2023」那一轮目标里有一条是 slight selling and administrative expense leverage —— "
                f"要费用率往下走。实际从 FY2018 的 {history['sga_pct_of_revenue'][4]:.1f}% 走到 FY2023 的 "
                f"{history['sga_pct_of_revenue'][9]:.1f}%，再到本财年的 {history['sga_pct_of_revenue'][-1]:.1f}%。"
                "拆开看，动的主要是经营费用那条：直营要开店、要仓配、要技术投入，"
                "这些都不进销货成本，进的是这里。"
                "需求创造费用（品牌与体育营销）反而是这十三年里最稳的一条，"
                f"在 {min(history['demand_creation_pct_of_revenue']):.1f}% 到 "
                f"{max(history['demand_creation_pct_of_revenue']):.1f}% 之间。"
                "FY2020 与 FY2021 的两个尖是疫情：一年是收入塌了分母，一年是营销停了分子。"
            ),
            "src_extra": "各年 10-K 的 TOTAL SELLING AND ADMINISTRATIVE EXPENSE 表；两条费用率为自算。",
        },
        {
            "kind": "grouped_bars",
            "title": (
                f"十年经营现金流、资本开支与股东回报：本财年分别为 "
                f"{operating[-1] / 1000:.1f}B、{capex[-1] / 1000:.1f}B 与 "
                f"{(repurchase[-1] + dividends[-1]) / 1000:.1f}B"
            ),
            "xlabels": cash_labels,
            "groups": [
                {"name": "经营现金流", "color": "NAVY", "values": operating},
                {"name": "资本开支", "color": "BLUE", "values": capex},
                {"name": "回购 + 分红", "color": "GOLD",
                 "values": [b + d for b, d in zip(repurchase, dividends)]},
            ],
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "bar_labels": False,
            "ylab": "US$M",
            "note": (
                f"经营现金流本财年 {operating[-1]:,.0f}，是这十年里除疫情年之外最低的一年，"
                f"比上年少 {operating[-2] - operating[-1]:,.0f}；10-K 把主因写成应收增加，"
                "而应收增加的第一项就是那笔关税退款应收。"
                f"<b>第三根柱的构成整个变了：</b>本财年回购加分红 {repurchase[-1] + dividends[-1]:,.0f} 里，"
                f"分红占 {dividends[-1] / (repurchase[-1] + dividends[-1]) * 100:.0f}%；"
                f"FY2023 那一年这个比例是 {dividends[6] / (repurchase[6] + dividends[6]) * 100:.0f}%。"
                "分红这条线十年没有断过，且逐年上升；回购是被关掉的那一个。"
                "FY2017 的经营现金流按该年 10-K 原始申报值记录；"
                "FY2018 采用 ASU 2016-09 后把它追溯重述为 3,846，差额是科目间的重分类，不是净现金变化。"
            ),
            "src_extra": "各年 10-K 的合并现金流量表，申报值。",
        },
        {
            "kind": "bar_line",
            "title": (
                f"十年回购与资本强度：回购从 FY2023 的 {repurchase[6] / 1000:.1f}B 掉到本财年的 "
                f"{repurchase[-1]:,.0f}M，资本开支占收入从 3% 以上掉到 {cash['capex_pct_of_revenue'][-1]:.2f}%"
            ),
            "xlabels": cash_labels,
            "bar": {"name": "回购（现金流量表口径）", "color": "GOLD", "values": repurchase},
            "line": {"name": "资本开支 / 收入 D", "color": "RED",
                     "values": rounded(cash["capex_pct_of_revenue"])},
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "US$M / %",
            "note": (
                f"<b>两条线一起塌，而其中一条是公司自己写过目标的那条。</b>"
                "FY2021 与 FY2022 的 10-K 都写着 In future periods, we expect to make annual capital "
                "expenditures of approximately 3% of annual revenues —— "
                f"而这句话第一次出现的那一年，这条比率刚从 {cash['capex_pct_of_revenue'][3]:.2f}% 掉到 "
                f"{cash['capex_pct_of_revenue'][4]:.2f}%，此后再没回去过，本财年 "
                f"{cash['capex_pct_of_revenue'][-1]:.2f}%。这句话在 FY2023 的 10-K 里消失。"
                f"回购这一侧：FY2026 的现金流量表口径是 {repurchase[-1]:,.0f}，"
                f"比 FY2025 少 {(1 - repurchase[-1] / repurchase[-2]) * 100:.0f}%。"
                "<b>同一年的回购金额公司印了三个数</b>：现金流量表 146（当期付现，含结算上年的交易）、"
                "股东权益表与新闻稿 123、10-K 的 MD&A 122.4；本图取现金流量表口径，"
                "因为其余九年也取自同一张表。"
            ),
            "src_extra": "各年 10-K 的合并现金流量表；资本开支占收入为自算。",
        },
        {
            "kind": "bars_labeled",
            "title": (
                f"回购的成交均价：FY2023 每股 {prices[0]:.2f}，本财年 {prices[-1]:.2f}，"
                f"而整个计划的累计均价是 {buyback['cumulative_average_price_usd']:.2f}"
            ),
            "xlabels": [fy_label(int(year)) for year in price_years],
            "values": prices,
            "fmt": "usd2",
            "yfmt": "usd2",
            "label_fmt": "usd2",
            "ylab": "US$ / 股",
            "note": (
                "<b>把花掉的钱除以买回的股数，是这一页少有的两条腿都申报、结论却只能靠除法看见的数。</b>"
                f"2022 年 6 月批准的 180 亿美元四年计划，到本财年末累计买了 "
                f"{buyback['cumulative_shares_m']:.1f} 百万股、花掉约 "
                f"{buyback['cumulative_cost_usd_bn']:.1f}B，均价 "
                f"{buyback['cumulative_average_price_usd']:.2f}；"
                f"而本财年只买了 {buyback['fy2026_shares_m']:.1f} 百万股，均价 "
                f"{buyback['fy2026_average_price_usd']:.2f}。"
                "<b>买得最多的几年是价格最高的几年，价格最低的这一年几乎没买。</b>"
                f"计划还剩约 {buyback['remaining_usd_bn']:.1f}B 未动用，"
                "而董事会在 2026 年 6 月重新批准它继续执行、不设固定到期日、也不增加授权额度 —— "
                "四年期这个约束被去掉了。"
                "只有四年有股数披露，更早的年份公司没在 MD&A 里印出股数，本图不往前补。"
            ),
            "src_extra": "各年 10-K 的 MD&A 与 Item 5，股数、金额与累计均价均为公司披露值。",
        },
    ]


def build_payload(staging: dict) -> dict:
    fin = staging["financials"]
    seg = staging["segments_usd_m"]
    growth = staging["growth_pct"]
    channels = staging["channels_usd_m"]
    products = staging["product_lines_usd_m"]
    balance = staging["balance_sheet_usd_m"]
    history = staging["long_history"]
    cash = staging["cash_history"]
    targets = staging["filed_targets"]
    periods = staging["periods"]

    reported_gm = fin["gross_margin_pct"][-1]
    ex_refund_gm = fin["gross_margin_ex_tariff_refund_pct"][-1]
    record = targets["record_levels"]
    latest_vintage = next(v for v in targets["vintages"] if v["key"] == "fy2025")
    missed = sum(1 for goal in latest_vintage["goals"] if goal["verdict"] == "miss")
    all_goals = [goal for vintage in targets["vintages"] for goal in vintage["goals"]]
    hits = sum(1 for goal in all_goals if goal["verdict"] == "hit")

    settled_ex = prior_threshold_charts(staging)
    target_charts, target_table = filed_target_charts(staging)
    settled_ex.extend(target_charts)
    highlight_ex = quarter_highlight_charts(staging)
    next_ex = next_quarter_charts(staging)
    routine_ex = routine_charts(staging)

    number_exhibits(settled_ex, start=1)
    number_exhibits(highlight_ex, start=settled_ex[-1]["n"] + 1)
    number_exhibits(next_ex, start=highlight_ex[-1]["n"] + 1)
    number_exhibits(routine_ex, start=next_ex[-1]["n"] + 1)
    for group in (settled_ex, highlight_ex, next_ex, routine_ex):
        resolve_exhibit_refs(group)

    first_table = routine_ex[-1]["n"] + 1
    core_rows = []
    for index, period in enumerate(periods):
        core_rows.append([
            period,
            staging["fiscal_labels"][index],
            staging["period_ends"][index],
            f"${fin['revenue_usd_m'][index]:,.0f}M",
            f"{growth['total_nike_inc_reported'][index]:+.0f}%",
            f"{growth['total_nike_inc_currency_neutral'][index]:+.0f}%",
            f"{fin['gross_margin_pct'][index]:.2f}%",
            f"{fin['demand_creation_pct_of_revenue'][index]:.2f}%",
            f"{fin['operating_overhead_pct_of_revenue'][index]:.2f}%",
            f"{fin['pretax_margin_pct'][index]:.2f}%",
            f"${fin['diluted_eps_usd'][index]:.2f}",
            f"{fin['diluted_shares_m'][index]:,.1f}M",
        ])
    segment_rows = []
    for index, period in enumerate(periods):
        segment_rows.append([
            period,
            f"${seg['north_america_revenue'][index]:,.0f}M / ${seg['north_america_ebit'][index]:,.0f}M",
            f"${seg['emea_revenue'][index]:,.0f}M / ${seg['emea_ebit'][index]:,.0f}M",
            f"${seg['greater_china_revenue'][index]:,.0f}M / ${seg['greater_china_ebit'][index]:,.0f}M",
            f"${seg['apla_revenue'][index]:,.0f}M / ${seg['apla_ebit'][index]:,.0f}M",
            f"${seg['converse_revenue'][index]:,.0f}M / ${seg['converse_ebit'][index]:,.0f}M",
            f"${seg['global_brand_divisions_ebit'][index]:,.0f}M",
            f"${seg['total_nike_inc_ebit'][index]:,.0f}M",
        ])
    channel_rows = []
    for index, period in enumerate(periods):
        channel_rows.append([
            period,
            f"${channels['nike_brand_wholesale'][index]:,.0f}M",
            f"${channels['nike_brand_direct'][index]:,.0f}M",
            f"{channels['nike_direct_share_pct'][index]:.1f}%",
            f"${products['footwear'][index]:,.0f}M",
            f"${products['apparel'][index]:,.0f}M",
            f"${products['equipment'][index]:,.0f}M",
            f"${balance['inventories'][index]:,.0f}M",
            f"${balance['accounts_receivable_net'][index]:,.0f}M",
            "全年减九个月 D" if channels["derived_from_annual_minus_nine_months"][index] else "申报值",
        ])
    long_rows = []
    for index, year in enumerate(history["fiscal_years"]):
        long_rows.append([
            fy_label(year),
            f"${history['revenue_usd_m'][index]:,.0f}M",
            f"{history['gross_margin_pct'][index]:.1f}%",
            f"{history['sga_pct_of_revenue'][index]:.1f}%",
            f"{history['ebit_margin_pct'][index]:.2f}%",
            (f"{history['ebit_margin_disclosed_pct'][index]:.1f}%"
             if history["ebit_margin_disclosed_pct"][index] is not None else "未披露"),
            (f"{history['roic_pct'][index]:.1f}%" if history["roic_pct"][index] is not None else "未披露"),
            f"${history['diluted_eps_usd'][index]:.2f}",
            f"${history['wholesale_usd_m'][index]:,.0f}M",
            f"${history['nike_direct_usd_m'][index]:,.0f}M",
            f"{history['nike_direct_share_pct'][index]:.1f}%",
        ])
    cash_rows = []
    for index, year in enumerate(cash["fiscal_years"]):
        cash_rows.append([
            fy_label(year),
            f"${cash['operating_cash_flow_usd_m'][index]:,.0f}M",
            f"${cash['capital_expenditures_usd_m'][index]:,.0f}M",
            f"{cash['capex_pct_of_revenue'][index]:.2f}%",
            f"${cash['share_repurchases_usd_m'][index]:,.0f}M",
            f"${cash['dividends_paid_usd_m'][index]:,.0f}M",
            f"${cash['depreciation_usd_m'][index]:,.0f}M",
        ])
    closure_rows = [[item["question"], item["evidence"], item["verdict"]]
                    for item in staging["followup_closure"]]
    unsettleable_rows = [[item["metric"], item["reason"]]
                         for item in staging["prior_kpi_unsettleable"]]
    unsettleable_rows += [[item["metric"], item["reason"]]
                          for item in staging["next_kpi_not_plotted"]]

    tables = [
        threshold_table(first_table, "上季门槛核对（原始单位）", staging["prior_kpi_settlement"],
                        "actual", "本季实际"),
        threshold_table(first_table + 1, "下季门槛（原始单位）", staging["next_kpi"],
                        "current", "当前值"),
        {
            "n": first_table + 2,
            "title": "本季无法结清的门槛，及其原因",
            "headers": ["门槛", "为什么本季无法结清"],
            "rows": unsettleable_rows,
        },
        {
            "n": first_table + 3,
            "title": "上季八条待验证问题的结清情况",
            "headers": ["上季问题", "本季申报文件里的证据", "判定"],
            "rows": closure_rows,
        },
        {**target_table, "n": first_table + 4},
        {
            "n": first_table + 5,
            "title": "八季核心（自然年季度标注；公司财季见第二列）",
            "headers": ["自然年季度", "公司财季", "季末", "收入", "同比", "同比（固定汇率）",
                        "毛利率", "需求创造费用率", "经营费用率", "税前利润率", "摊薄 EPS", "摊薄股数"],
            "rows": core_rows,
        },
        {
            "n": first_table + 6,
            "title": "八季分部（收入 / EBIT，均为申报值）",
            "headers": ["自然年季度", "北美", "EMEA", "大中华区", "APLA", "Converse",
                        "Global Brand Divisions EBIT", "NIKE, Inc. EBIT"],
            "rows": segment_rows,
        },
        {
            "n": first_table + 7,
            "title": "八季渠道与品类（NIKE Brand 口径）",
            "headers": ["自然年季度", "批发", "NIKE Direct", "直营占比", "鞋", "服装", "器材",
                        "存货", "应收账款", "渠道拆分来源"],
            "rows": channel_rows,
        },
        {
            "n": first_table + 8,
            "title": "十三年年度记录（各年取该年 10-K 印出的数）",
            "headers": ["财年", "收入", "毛利率", "销售与管理费用率", "EBIT 利润率 D",
                        "EBIT 利润率（公司披露）", "ROIC（公司披露）", "摊薄 EPS",
                        "批发", "NIKE Direct", "直营占比 D"],
            "rows": long_rows,
        },
        {
            "n": first_table + 9,
            "title": "十年现金流与资本配置（各年 10-K 现金流量表）",
            "headers": ["财年", "经营现金流", "资本开支", "资本开支占收入 D", "回购", "分红", "折旧"],
            "rows": cash_rows,
        },
        # The one object published byte-identically on every page. NIKE is not on
        # the chain it draws and is not a column in it -- neither are Cadence,
        # Synopsys, TSMC, NVIDIA, Visa, Mastercard or TJX, which carry it on the
        # same terms. It lives in the collapsed audit drawer rather than the chart
        # flow, so it does not spend this page's "every chart must earn its place"
        # budget; the notes say what it is.
        ai_capex_cycle_table(first_table + 10),
    ]

    return {
        "schema_version": "quarterly-dashboard/nke-v1",
        "page": {"slug": "nke", "language": "zh-CN"},
        "company": {
            "ticker": "NKE",
            "name": "NIKE, Inc.",
            "group": "consumer_retail",
            "accounting_standard": "US GAAP",
        },
        "latest": {
            "disclosed_period_label": "Q2 2026",
            "full_financial_period_label": "Q2 2026",
            "period_end": "2026-05-31",
            "release_date": "2026-06-30",
            "analysis_date": "2026-08-29",
            "audit_status": "audited",
            "status": "history_ready",
        },
        "tracker": "Watchlist Quarterly Tracker · NKE",
        "title": "NIKE, Inc. (NKE)：Q2 2026 季报仪表盘",
        "subtitle": (
            "三个月截至 2026-05-31 · 发布 2026-06-30 · US GAAP · 已审计（FY2026 10-K） · "
            "5 月制财年，本站按自然年季度标注：本页 Q2 2026 即公司所称 FY2026 Q4"
        ),
        "headline": (
            f"报表毛利率 {reported_gm:.1f}% 里有 {reported_gm - ex_refund_gm:.1f} 个百分点是一次性关税退款，"
            f"剔除后 {ex_refund_gm:.1f}%、同比 −0.1 个百分点；"
            f"而把镜头拉到十三年，公司自己写进 10-K 的最后一轮多年目标（截至 FY2025）"
            f"{len(latest_vintage['goals'])} 条全部未达成 —— 其中毛利率与 EBIT 利润率两条要求的水平，"
            f"NIKE 在这十三年里一次都没印出来过。"
        ),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>记录</span><b>公司自己的目标，三轮十四条，达成一条</b>'
            f'<p>NIKE 在 10-K 里给过三轮多年财务目标，窗口都已走完：合计 {len(all_goals)} 条，'
            f'达成 {hits} 条。最后一轮（FY2021 写下、截至 FY2025）{missed} 条全落空，'
            f'其中 high 40s 的毛利率与 high teens 的 EBIT 利润率，高于十三年记录里的任何一年。</p></article>'
            '<article><span>断口</span><b>此后四份 10-K 一条目标也没有</b>'
            '<p>FY2022 的 10-K 还提「long-term financial goals」但不再复述数字，'
            'FY2023 起连这个词都不出现；而 EBIT 利润率与 ROIC 的计算表照旧逐年披露。'
            '消失的是目标，不是度量。新的一轮定在 2026-11-16/17 的投资者日。</p></article>'
            '<article><span>机制</span><b>渠道换了，毛利率没来</b>'
            '<p>NIKE Direct 从 FY2014 的 20.3% 升到 FY2023 的 43.7%，'
            '而毛利率的最高点停在 FY2016 的 46.2%；同期销售与管理费用率从 31.5% 升到 34.7%。'
            '本财年 NIKE Brand 那 +1% 的增长，全部来自被压缩了七年的批发渠道。</p></article>'
            '</div>'
        ),
        "source": (
            'Source: <a href="https://www.sec.gov/Archives/edgar/data/320187/'
            '000032018726000076/q4fy26exhibit991er.htm" rel="noopener">NIKE FY2026 Q4 '
            '业绩新闻稿（8-K EX-99.1）</a>与截至 2026-05-31 的 10-K。'
        ),
        "source_url": (
            "https://www.sec.gov/Archives/edgar/data/320187/"
            "000032018726000076/q4fy26exhibit991er.htm"
        ),
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": staging["guidance"],
        "sections": [
            {
                "id": "settled",
                "title": "一、上季兑现与公司自己写进申报文件的目标",
                "description": (
                    "先结清上季设下的门槛，再看新数字。NIKE 不在任何申报文件里给季度指引，"
                    "本站清点的 40 份业绩新闻稿没有一份带经营指引；"
                    "它写进申报文件的是三轮多年财务目标，窗口都已走完，因此可以逐条结清。"
                ),
                "exhibits": settled_ex,
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": (
                    "一次性关税退款把毛利率、北美分部利润与每股收益同时推歪了多少，"
                    "汇率在各地域之间的不均匀顺风，大中华区四十个季度的完整弧线，"
                    "以及上季笔记留下的两个数字被申报文件更正到哪里。"
                ),
                "exhibits": highlight_ex,
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": "当前值离下季门槛还有多远，统一用「距阈值余量」口径；两条不接入的也写在这里。",
                "exhibits": next_ex,
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": (
                    "NIKE 专属的常规序列：十三年直营占比与毛利率这一对、两个渠道的绝对额、"
                    "三十二个季度的直营占比、两条费用率、十年现金流与资本配置，"
                    "以及回购的成交均价。"
                ),
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "本页所有季度按自然年标注。NIKE 财年在 5 月 31 日结束，故本页的 Q2 2026 是三个月截至 2026-05-31 的季度，公司自己称之为 FY2026 Q4；映射规则为公司 FY(N) 的 Q1、Q2 分别是本页的 Q3、Q4 (N−1)，Q3、Q4 分别是本页的 Q1、Q2 (N)。不统一成一种约定，跨公司对照就会把不同的三个月放在一起比较。",
            "本页没有「季度指引兑现」记录组图，这是取数限制而不是编辑取舍。本站逐份读了 FY2017 Q1 至 FY2026 Q4 的 40 份业绩 8-K 的 EX-99.1，没有一份带经营指引：只有三份带任何指向未来期间的数字，分别是期货订单余额、回购计划的启动时点与一次重组费用预估。公司在新闻稿里自己写着 Revised guidance will be provided on the conference call。另有一段窗口：FY2017 Q1 至 FY2018 Q4 的八份业绩 8-K 曾把电话会讲稿一并附上，其中带完整数字指引，2018-07-03 之后不再附。",
            "第一节的目标记录来自各年 10-K 的 MD&A。三轮目标分别写在 FY2016/FY2017（截至 FY2020）、FY2018/FY2019/FY2020（截至 FY2023）与 FY2021（截至 FY2025）的 10-K 里。FY2022 的 10-K 仍提及 long-term financial goals 但不再复述任何一条数字，FY2023 至 FY2026 的四份 10-K 里 financial goal 与 long-term financial 两个词组出现次数均为 0，而 EBIT Margin 与 ROIC 的定义与计算表仍逐年披露。",
            "NIKE 的目标是用词写的而不是端点：high single-digit、low double-digit、mid-teens、mid to high teens、high 40s、high teens、high-twenties to low-thirties、low-thirties。本页把它们分别读作 7–9%、10–12%、14–16%、14–19%、47–49%、17–19%、27–33%、30–33%，这是本页的口径而不是公司的算术，已写在图上。凡是结论会随读法翻转的一条，本页标为「取决于读法」而不是替读者选一边；FY2025 那一轮的六条差距都在 4 到 11 个百分点之间，读法不影响结论。",
            "「on average, per year, through fiscal N」没有指明基年。本页以目标写下那一年的财年为基年，另把改用前一年为基年的结果并列在核对表里。这一条不是形式：截至 FY2023 那一轮的每股收益，按 FY2018 为基年是年均 +22.5%（达成），按 FY2017 为基年是 +4.3%（未达成），差别全部来自 FY2018 那一年 55.3% 的有效税率——《减税与就业法案》的一次性影响。收入那一条同样压在边界上（7.07% 对 7.05% 对 6.88%），本页记为「压在边界上」而不是判定达成。",
            "EBIT 与 EBIT 利润率是公司自定义的非 GAAP 口径：净利润加回净利息费用（收入）与所得税费用，再除以收入。公司只在 FY2022 起的 10-K 里印出这条比率。本页按同一条定义把它算到 FY2014，在五个有披露的年份里逐年复现公司印出的值，最大差 0.05 个百分点。ROIC 一律取公司印出的值，不自算。",
            "会计季 Q4 没有 10-Q。其损益取自 Q4 业绩 8-K 印出的 THREE MONTHS ENDED 一栏，是申报的季度值而不是财年数减九个月数的差分值；分部收入与 EBIT 同样取自该新闻稿。渠道拆分是唯一的例外：它只存在于 10-K 与 10-Q 的收入分解附注里，新闻稿不印，所以每年会计季 Q4 的渠道数是全年减九个月的差分值，已在核对表里逐季标注。",
            "四十个季度的每一季都通过了四条恒等式：收入减销货成本等于毛利、需求创造费用加经营费用等于销售与管理费用、毛利减费用减利息减其他等于税前利润、分部 EBIT 之和减净利息费用等于税前利润。四个季度之和与各年 10-K 印出的年度数在十个财年逐行相等。两条完全独立的取数路线（R-file 与业绩新闻稿 vs XBRL companyfacts）在 40 个季度、16 个字段上逐格比对，无一处不一致。",
            "地域分部在 FY2018 从六个改成四个（北美、西欧、中东欧、大中华区、日本、新兴市场 → 北美、EMEA、大中华区、APLA）。FY2017 的四个季度用的是公司在 FY2018 各季申报文件里印出的重述比较列，不是本页拼出来的；重述后的四季之和与 FY2018 的 10-K 印出的 FY2017 年度列逐项相等。原始六地域口径的数值不在本页发布。",
            "渠道拆分只能从 FY2019 起画。NIKE 在 FY2019 财年（2018 年 6 月起）采用 ASC 606，收入分解附注从那时开始存在，往前没有可比的数，本页不往前补。年度口径可以更早：MD&A 的 Supplemental NIKE Brand Revenues Details 表从 FY2014 起就在，只是 FY2017 及更早把这条线叫 Sales Direct to Consumer，FY2018 起改名 Sales through NIKE Direct，FY2018 的 10-K 用新名字重印前两年且数值相同，所以是改名不是换口径。",
            "IEEPA 关税退款 986 全额冲减销货成本，其中北美 965、Converse 21，是公司在最高法院 2026-02-20 裁定后把回收认定为 probable 才计入的。截至 2026-05-31 已收现 302、应收余额 684；10-K 写明年末之后已收到其中绝大部分，且未计提任何减值准备。本地笔记自算的应收 686 与申报的 684 差 2，本页用申报值。",
            "FY2026 的遣散费用全年 385，其中经营费用 231、销货成本 154，现金支出 142，期末仍有 243 挂在应计负债里。会计季 Q4 的那一格是全年数减九个月数：总额 81、销货成本 104、经营费用 −23。10-Q 印出的是「三个月 230、九个月 304」，把前者当成年初至今会把 Q4 算成约 170，本地笔记正是这样算的，本页按申报值更正。",
            "本页不发布剔除遣散费用后的「underlying 毛利率」年度序列。公司只在有费用的年份披露科目拆分，不按季拆，也从不给 underlying 口径；只有本季那一格能由两个申报数相减得出，画在毛利率桥上。同理，Sportswear、Jordan Streetwear 与 Football 的收入或增速不发布——NIKE 不按这些口径披露任何金额，管理层只在电话会上用 declined double digits 这样的词描述，把词换算成数需要自选一个比例，那是假设不是算术。",
            "同一年的回购金额公司印了三个数：现金流量表 146（当期实际付现，含结算上一年度的交易）、股东权益表与业绩新闻稿 123、10-K 的 MD&A 122.4（180 万股，均价 67.63 美元）。图上一律用现金流量表口径，因为十年序列的其余各年也取自同一张表；成交均价那张图用的是 MD&A 的金额与股数。",
            "FY2017 的经营现金流按该年 10-K 原始申报的 3,640 记录。FY2018 采用 ASU 2016-09 后把它追溯重述为 3,846，差额 206 是超额税务利益在经营与筹资之间的重分类，不是净现金变化；本页十年序列一律取各年 10-K 原始申报值。",
            "「公司展望」那张表是本页唯一不来自申报文件的数据块，来自 2026-06-30 的电话会，已在表下注明。它既无法用第二份文件交叉核对，也不会在下一季被自动结清，本页因此不为它建任何命中率记录。",
            "核对抽屉最后那张「AI capex 循环」是全站逐字节一致的跨页对照块，不是对 NIKE 的判断：它把四家云厂的现金资本开支、NVDA 的数据中心收入与 TSM 的晶圆季度串成一条链，而 NIKE 不在这条链的任何一环上。本站有若干页同样只是承载它而不出现在它的列里（Cadence、Synopsys、TSMC、NVIDIA、Visa、Mastercard、TJX 都是如此，且有测试专门钉住这一点）。它放在折叠抽屉里而不是图表区，所以不占本页「每张图都要自证」的额度。",
            "本页只发布公司披露值、可复算的简单派生值，以及明确标注来源与时点的公司口头展望；D 标记代表 Derived / 自算。",
            "本页不发布评级、目标价、估值倍数与任何卖方或第三方估计。上季笔记里的卖方目标价与其汇总值、市盈率倍数、正常化每股收益乘以倍数得到的重估区间、第三方跑鞋份额估算与第三方商场同店销售追踪，一律不接入。市场预期同样不接入：本季的营收与每股收益市场预期在笔记里带机构来源，本站只发布不带机构名且注明取数时点的市场预期，而这两个数不满足该条件。",
            "本页已知未接入：按地域拆的毛利率与库存金额（公司均不披露）、Sportswear/Jordan/Football 的收入与增速（无披露）、自由现金流（公司从不定义也不披露，这也是「截至 FY2020」那一轮里唯一无法结清的一条目标）、NIKE Brand 批发等价收入的季度值（只在会计季 Q4 的新闻稿里按十二个月印出，且 FY2026 起停印）、门店数（公司自 FY2024 起不再在 10-K 里印出零售店数量表）。",
            "业绩电话会文字稿仅链接官方 IR 与 SEC 托管版本，公开仓不复制原件或逐字内容。",
        ],
        "footer": "NIKE quarterly results · 数据来自 NIKE, Inc. 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "nke.js"), payload, "nke")
    shell_dir = ROOT / "nke"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("NKE", "nke"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(
        f"NKE page: {charts} charts in {len(payload['sections'])} sections "
        f"+ {len(payload['tables'])} audit tables"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
