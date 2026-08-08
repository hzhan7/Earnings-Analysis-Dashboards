#!/usr/bin/env python3
"""Build the META quarterly-results page.

Same four-part, chart-led shape as the other company pages (上季兑现 → 本季重点
→ 下季跟踪 → 长期常规).  The routine series are the ones that decide this
company right now: not "is the ad engine working" -- it is -- but whether the
incremental revenue the ad engine produces still turns into incremental
operating profit while the capital base doubles.

That is why the page leads on a series no filing publishes directly: the
year-over-year incremental operating margin, ΔOI / ΔRevenue.  A level margin
falling from 41% to 31% and a company whose extra dollar of revenue carries a
negative extra dollar of profit look identical on a margin chart and are two
completely different investment problems.

Published numbers are company-reported or transparent arithmetic.  Market
expectations are labelled as such, with no broker attribution.
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
    unit_text,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "meta.json"
DATA_DIR = ROOT / "data"
SHELL = render_shell("META", "meta")

# The source carries twelve quarters so every displayed quarter has a year-ago
# base; the page shows the last eight.
WINDOW = 8


def compact_period(period: str) -> str:
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


def shown(values: list) -> list:
    return values[-WINDOW:]


def yoy(values: list[float]) -> list[float | None]:
    return [None] * 4 + [
        (values[index] / values[index - 4] - 1) * 100 for index in range(4, len(values))
    ]


def trailing(values: list[float]) -> list[float | None]:
    return [None] * 3 + [sum(values[index - 3:index + 1]) for index in range(3, len(values))]


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    labels = [compact_period(period) for period in shown(periods)]
    q = staging["quarterly_usd_m"]
    ads = staging["advertising_metrics"]
    snapshot = staging["current_snapshot"]
    guidance = staging["guidance"]
    consensus = staging["market_expectation"]
    capex_guide = staging["capex_guidance_history"]
    bridge = staging["operating_income_bridge"]
    fy2025 = staging["fy2025_actuals_usd_m"]
    closure = staging["followup_closure"]
    prior_kpi = staging["prior_kpi_settlement"]
    next_kpi = staging["next_kpi"]

    revenue = q["revenue_total"]
    operating_income = q["operating_income"]

    # Advertising is not tagged separately in the cash-flow-level series; it is
    # the reported total less the two disclosed non-advertising lines, so the
    # three revenue lines always add back to the reported total exactly.
    advertising = [
        total - reality - other
        for total, reality, other in zip(
            revenue, q["reality_labs_revenue"], q["foa_other_revenue"]
        )
    ]

    # META's own free-cash-flow definition nets finance-lease principal, and the
    # headline capex number adds it too, so both derived lines use the same base.
    capex_total = [
        purchases + lease
        for purchases, lease in zip(
            q["purchases_of_property_and_equipment"], q["finance_lease_principal"]
        )
    ]
    free_cash_flow = [
        operating - capex
        for operating, capex in zip(q["operating_cash_flow"], capex_total)
    ]

    # ΔOI / ΔRevenue on a year-over-year base. Quarter-over-quarter would be
    # cleaner arithmetic but META's Q4 is seasonally large enough to flip the
    # sign twice a year, which would make the series unreadable.
    incremental_margin = [None] * 4 + [
        (operating_income[i] - operating_income[i - 4]) / (revenue[i] - revenue[i - 4]) * 100
        for i in range(4, len(revenue))
    ]
    adjusted_incremental_margin = (
        (snapshot["adjusted_operating_income_usd_m"] - operating_income[-5])
        / (revenue[-1] - revenue[-5]) * 100
    )

    volume_price_product = [
        ((1 + impressions / 100) * (1 + price / 100) - 1) * 100
        for impressions, price in zip(
            ads["ad_impressions_yoy_pct"], ads["price_per_ad_yoy_pct"]
        )
    ]

    revenue_shown = shown(revenue)
    revenue_yoy = shown(yoy(revenue))
    advertising_yoy = shown(yoy(advertising))
    foa_other_shown = shown(q["foa_other_revenue"])
    foa_other_yoy = shown(yoy(q["foa_other_revenue"]))
    reality_labs_shown = shown(q["reality_labs_revenue"])
    operating_income_shown = shown(operating_income)
    operating_margin = [
        income / total * 100 for income, total in zip(operating_income_shown, revenue_shown)
    ]
    capex_shown = shown(capex_total)
    capex_intensity = [
        capex / total * 100 for capex, total in zip(capex_shown, revenue_shown)
    ]
    fcf_shown = shown(free_cash_flow)
    ttm_fcf = shown(trailing(free_cash_flow))
    depreciation_shown = shown(q["depreciation_and_amortization"])
    depreciation_yoy = shown(yoy(q["depreciation_and_amortization"]))
    sbc_ratio = [
        sbc / total * 100 for sbc, total in zip(shown(q["share_based_compensation"]), revenue_shown)
    ]

    capex_guide_mid = [
        (low + high) / 2
        for low, high in zip(capex_guide["low_usd_bn"], capex_guide["high_usd_bn"])
    ]
    q3_midpoint = sum(guidance["q3_revenue_usd_m"]) / 2
    q3_yoy = pct_change(q3_midpoint, revenue[-4])
    fy2025_quarterly_average = fy2025["operating_income"] / 4
    half_year_line = fy2025["operating_income"] / 2
    half_year_actual = guidance["h1_2026_operating_income_usd_m"]
    price_low, price_high = consensus["post_earnings_price_change_range_pct"]

    source = (
        'Source: <a href="https://investor.atmeta.com/" rel="noopener">Meta Investor Relations</a>'
        '（Q2 2026 earnings release 与电话会；历史季度经 SEC EDGAR 的 10-Q / 10-K 回源）。'
    )

    def source_note(detail: str) -> str:
        return f"{detail}；历史期同口径。自算项目均可在核对表中复核。"

    # Two tracked metrics are settled on the adjusted basis while their history
    # only exists on the GAAP one, so those charts carry a second short line:
    # it coincides with the GAAP line through last quarter (which had no
    # comparable one-off items) and separates only where the add-backs land.
    # Without it the plotted last point and the stated "current" value disagree.
    def adjusted_tail(previous: float, current: float) -> dict:
        return {
            "name": "调整后（本季）D",
            "values": [None] * (WINDOW - 2) + [round(previous, 2), round(current, 2)],
            "color": "GOLD",
        }

    # One entry per tracked metric, so §1 and §3 can each draw the metric's own
    # history under its own threshold instead of only a normalised bar.
    tracked = {
        "经营利润率（调整后）": (
            operating_margin, "pct1", "经营利润率", "经营利润率（GAAP）",
            adjusted_tail(
                operating_margin[-2],
                snapshot["adjusted_operating_income_usd_m"] / revenue[-1] * 100,
            ),
        ),
        "平均每条广告价格 YoY": (
            shown(ads["price_per_ad_yoy_pct"]), "pct0", "同比", "平均每条广告价格 YoY", None,
        ),
        "同比增量经营利润率": (
            shown(incremental_margin), "pct1", "ΔOI / ΔRevenue", "同比增量经营利润率（GAAP）D",
            adjusted_tail(incremental_margin[-2], adjusted_incremental_margin),
        ),
        "广告量价乘积（隐含收入增速）": (
            shown(volume_price_product), "pct1", "隐含同比", "量价乘积 D", None,
        ),
        "FoA Other 单季收入": (foa_other_shown, "f0c", "$M", "FoA Other 收入", None),
        "单季经营利润 vs FY2025 季均线": (operating_income_shown, "f0c", "$M", "单季经营利润", None),
    }

    def tracking_charts(entries, value_key, threshold_label, headline) -> list[dict]:
        charts = []
        for entry in entries:
            metric = entry["metric"]
            if metric not in tracked:
                continue
            values, fmt, ylab, actual_name, adjusted = tracked[metric]
            side = "上方" if entry["direction"] == "up" else "下方"
            adjusted_note = (
                ""
                if adjusted is None
                else "金色线为剔除本季 $2,400M 法律计提与 $1,180M 遣散费后的同一指标，阈值按该口径结算。"
            )
            exhibit = threshold_exhibit(
                headline(entry),
                labels,
                values,
                entry["threshold"],
                fmt=fmt,
                ylab=ylab,
                actual_name=actual_name,
                threshold_name=f"{threshold_label}（安全侧在{side}）",
                note=(
                    f"阈值 {unit_text(entry['unit'], entry['threshold'])}，"
                    f"当前 {unit_text(entry['unit'], entry[value_key])}，"
                    f"余量 {headroom(entry['direction'], entry['threshold'], entry[value_key]):+.1f}%。"
                    f"{adjusted_note}"
                ),
                src_extra=(
                    "实际值来自各期 10-Q / 10-K 与当季 earnings release；"
                    "阈值为本地研究设定，不是公司指引。"
                ),
            )
            if adjusted is not None:
                exhibit["series"].insert(1, adjusted)
            charts.append(exhibit)
        return charts

    settled_charts = [
        {
            "kind": "bars_labeled",
            "title": "上季 6 条待验证问题：1 条已验证、1 条被证伪、3 条只做到部分验证",
            "xlabels": closure["labels"],
            "values": closure["counts"],
            "legend": "问题条数",
            "fmt": "f0",
            "yfmt": "f0",
            "label_fmt": "f0",
            "ylab": "条",
            "note": (
                "被证伪的是「裁员会带来费用指引下调」——裁员约 8,000 人、遣散费 $1,180M，"
                "全年费用指引反而把下限抬高了 $3B；三条部分验证全部因为公司换掉了原来的披露口径。"
            ),
            "src_extra": (
                "问题清单来自上季本地分析稿的 follow-up；验证结果依据本季 earnings release、"
                "电话会与 Q2 2026 10-Q。"
            ),
        },
        headroom_exhibit(
            "上季 5 条量化阈值：三条守住，被击穿的两条一条在利润率、一条在新硬件",
            prior_kpi["quantified"],
            "actual",
            (
                "正值 = 仍在安全侧。广告价格以 +50% 的余量「达标」，"
                "但同一季广告收入减速 5.4pp——这条阈值本身已被证明会给出方向相反的信号，本季退役。"
            ),
            src_extra=(
                "阈值为上季本地研究设定，不是公司指引；实际值为 Q2 2026 披露值。"
                "经营利润率一条按剔除 $2,400M 法律计提与 $1,180M 遣散费后的 36.77% 结算，"
                "GAAP 口径的 30.88% 击穿得更深。下面逐条给出可绘制指标自身的八季走势。"
            ),
        ),
    ]
    settled_charts += tracking_charts(
        [entry for entry in prior_kpi["quantified"]
         if entry["metric"] in ("经营利润率（调整后）", "平均每条广告价格 YoY")],
        "actual",
        "上季阈值",
        lambda entry: (
            f"{entry['metric']}："
            f"{'守住' if headroom(entry['direction'], entry['threshold'], entry['actual']) >= 0 else '已击穿'}"
            f"上季阈值 {unit_text(entry['unit'], entry['threshold'])}"
        ),
    )

    highlights = [
        {
            "kind": "gs_bar",
            "title": (
                f"收入 ${revenue_shown[-1]:,.0f}M、同比 {revenue_yoy[-1]:.1f}%，"
                f"较上季减速 {revenue_yoy[-1] - revenue_yoy[-2]:.1f}pp"
            ),
            "xlabels": labels,
            "values": revenue_shown,
            "legend": "总收入",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "ylab2": "同比增速",
            "yoy": {
                "name": "同比增速 (RHS)",
                "values": revenue_yoy,
                "color": "GREEN",
                "yfmt": "pct1",
            },
            "note": (
                f"较市场预期 ${consensus['revenue_usd_m']:,.0f}M 高 "
                f"{pct_change(revenue_shown[-1], consensus['revenue_usd_m']):.1f}%；"
                f"Q3 指引中点 ${q3_midpoint:,.0f}M，隐含同比 {signed(q3_yoy)}，再减速约 "
                f"{revenue_yoy[-1] - q3_yoy:.0f}pp。"
            ),
            "src_extra": source_note("收入来自各期 10-Q / 10-K 与当季 release，同比为自算"),
        },
        {
            "kind": "lines",
            "title": "广告减速全部来自量：曝光同比从 19% 降到 14%，单价两季都是 12%",
            "xlabels": labels,
            "series": [
                {"name": "广告收入 YoY D", "values": advertising_yoy, "color": "NAVY"},
                {"name": "广告曝光 YoY", "values": shown(ads["ad_impressions_yoy_pct"]), "color": "MBLUE"},
                {"name": "平均每条广告价格 YoY", "values": shown(ads["price_per_ad_yoy_pct"]), "color": "GOLD"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "zero_base": True,
            "end_label": True,
            "ylab": "同比增速",
            "note": (
                f"量价相乘可以闭合：{(1 + ads['ad_impressions_yoy_pct'][-1] / 100):.2f} × "
                f"{(1 + ads['price_per_ad_yoy_pct'][-1] / 100):.2f} − 1 = "
                f"{volume_price_product[-1]:.1f}%，对上实际的 {advertising_yoy[-1]:.1f}%。"
                f"同期 Family DAP 仅 {ads['family_daily_active_people_bn'][-1]:.2f}B、同比 "
                f"{pct_change(ads['family_daily_active_people_bn'][-1], ads['family_daily_active_people_bn'][-5]):.0f}%，"
                "曝光与用户之间约 11pp 的缺口来自广告负载与人均时长。"
            ),
            "src_extra": (
                "曝光与单价同比为公司披露的百分比；广告收入 = 总收入 − Reality Labs − FoA Other，"
                "同比为自算。量价乘积与实际增速的差异来自公司披露值的整数舍入。"
            ),
        },
        {
            "kind": "bars_labeled",
            "title": (
                f"剔除 $3,580M 一次性项后，经营利润仍较上季少 "
                f"${operating_income[-2] - snapshot['adjusted_operating_income_usd_m']:,.0f}M"
            ),
            "xlabels": bridge["labels"],
            "values": bridge["values_usd_m"],
            "legend": "经营利润",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "note": (
                f"加回法律计提 ${bridge['addbacks']['法律计提']:,}M 与遣散费 "
                f"${bridge['addbacks']['遣散费']:,}M 得到 "
                f"${snapshot['adjusted_operating_income_usd_m']:,}M；"
                f"同期收入环比 {signed(pct_change(revenue[-1], revenue[-2]))}，"
                "所以环比的经营杠杆是负的，与一次性项无关。"
            ),
            "src_extra": (
                "GAAP 经营利润来自 Q2 2026 10-Q；两笔加回项的金额来自当季 release 与分部附注，"
                "调整后经营利润为两者相加的自算值，不是公司定义的 non-GAAP 指标。"
            ),
        },
        {
            "kind": "diverging_bars",
            "title": (
                f"单季自由现金流塌到 ${fcf_shown[-1]:,.0f}M，环比 "
                f"{pct_change(fcf_shown[-1], fcf_shown[-2]):.1f}%"
            ),
            "xlabels": labels,
            "values": fcf_shown,
            "legend": "自由现金流",
            "positive_label": "正自由现金流",
            "negative_label": "负自由现金流",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "zero_line": True,
            "note": (
                f"经营现金流 ${q['operating_cash_flow'][-1]:,.0f}M 基本持平，"
                f"资本开支却从 ${capex_shown[-2]:,.0f}M 跳到 ${capex_shown[-1]:,.0f}M；"
                "同季净发债 $24,910M、回购连续第三季为 $0。"
            ),
            "src_extra": source_note(
                "FCF 按公司口径 = 经营现金流 − 购买物业及设备 − 融资租赁本金偿付"
            ),
        },
        {
            "kind": "gs_bar",
            "title": (
                f"资本开支 ${capex_shown[-1]:,.0f}M、占收入 {capex_intensity[-1]:.1f}%，"
                f"较上季的 {capex_intensity[-2]:.1f}% 跳升"
            ),
            "xlabels": labels,
            "values": capex_shown,
            "legend": "单季资本开支（含融资租赁）",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "ylab2": "占收入比",
            "yoy": {
                "name": "CapEx / 收入 (RHS) D",
                "values": capex_intensity,
                "color": "GOLD",
                "yfmt": "pct1",
            },
            "note": (
                f"H1 已实现 ${guidance['h1_2026_capex_usd_m']:,}M，全年指引下限 "
                f"US${guidance['fy2026_capex_usd_bn'][0]}B 隐含 H2 还要再做 "
                f"${guidance['fy2026_capex_usd_bn'][0] * 1000 - guidance['h1_2026_capex_usd_m']:,}M，"
                "即单季规模较本季再上一个台阶。"
            ),
            "src_extra": (
                "资本开支为购买物业及设备加融资租赁本金，与公司指引口径一致；占收入比为自算。"
                "指引不覆盖以合资与租赁结构取得的算力，因此这条线是资本强度的下界而非全貌。"
            ),
        },
        {
            "kind": "bars_labeled",
            "title": (
                f"FY2026 CapEx 指引半年内两次上调，中点从 US${capex_guide_mid[0]:.0f}B 抬到 "
                f"US${capex_guide_mid[-1]:.1f}B"
            ),
            "xlabels": capex_guide["calls"],
            "values": capex_guide_mid,
            "legend": "FY2026 CapEx 指引中点",
            "fmt": "usd1",
            "yfmt": "usd1",
            "label_fmt": "usd1",
            "ylab": "US$B",
            "note": (
                f"区间依次为 US${capex_guide['low_usd_bn'][0]}–{capex_guide['high_usd_bn'][0]}B、"
                f"US${capex_guide['low_usd_bn'][1]}–{capex_guide['high_usd_bn'][1]}B、"
                f"US${capex_guide['low_usd_bn'][2]}–{capex_guide['high_usd_bn'][2]}B。"
                "最新一次是区间收窄，但收窄的方式是抬高下限——中点仍在上移。"
            ),
            "src_extra": (
                "三次口径来自对应季度的 earnings call；中点为自算。"
                "较 FY2025 实际的 "
                f"${fy2025['purchases_of_property_and_equipment'] + fy2025['finance_lease_principal']:,}M "
                "为同一口径对照。"
            ),
        },
    ]

    next_charts = [
        headroom_exhibit(
            "下季 5 条量化阈值：两条已在阈值之下，且都直接指向「增量资本有没有产出增量利润」",
            next_kpi["quantified"],
            "current",
            (
                "正值 = 仍在安全侧。增量经营利润率与单季经营利润两条都在线下：本季 GAAP 经营利润 "
                f"${operating_income[-1]:,}M，低于 FY2025 经营利润的季均值 "
                f"${fy2025_quarterly_average:,.0f}M；上半年累计 ${half_year_actual:,}M，"
                f"只比全年承诺的半程线 ${half_year_line:,.0f}M 高 ${half_year_actual - half_year_line:,.0f}M。"
            ),
            src_extra=(
                "阈值为本地研究设定，不是公司指引；当前值为 Q2 2026 实际。"
                "增量经营利润率的当前值取剔除一次性项后的口径。"
                "另有 4 条需等披露才能判定（数据中心合资结构的合并判定与担保、FY2027 CapEx 首次指引、"
                "企业级业务的绝对收入、受限现金性质）。"
            ),
        ),
    ]
    next_charts += tracking_charts(
        next_kpi["quantified"],
        "current",
        "下季阈值",
        lambda entry: (
            f"{entry['metric']}：下季阈值 {unit_text(entry['unit'], entry['threshold'])}，"
            f"当前 {unit_text(entry['unit'], entry['current'])}"
        ),
    )

    geography = staging["quarter_geography_usd_m"]
    geography_yoy = [
        pct_change(current, prior)
        for current, prior in zip(geography["current"], geography["prior_year"])
    ]

    routine = [
        {
            "kind": "gs_bar",
            "title": (
                f"折旧摊销同比 {depreciation_yoy[-1]:+.1f}%，快于收入的 {revenue_yoy[-1]:+.1f}%"
            ),
            "xlabels": labels,
            "values": depreciation_shown,
            "legend": "季度折旧摊销",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "ylab2": "同比增速",
            "yoy": {
                "name": "折旧摊销 YoY (RHS)",
                "values": depreciation_yoy,
                "color": "RED",
                "yfmt": "pct1",
            },
            "note": (
                f"本季资本开支是折旧摊销的 {capex_shown[-1] / depreciation_shown[-1]:.1f} 倍，"
                "意味着这条线的上行才刚开始；折旧曲线与收入曲线的交叉点，是这轮资本周期的定价问题。"
            ),
            "src_extra": source_note("折旧摊销来自各期现金流量表；同比为自算"),
        },
        {
            "kind": "gs_line",
            "title": (
                f"TTM 自由现金流由 ${max(v for v in ttm_fcf if v is not None):,.0f}M 回落到 "
                f"${ttm_fcf[-1]:,.0f}M"
            ),
            "xlabels": labels,
            "values": ttm_fcf,
            "legend": "TTM 自由现金流",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "note": (
                f"滚动四季口径把单季税款与季节性摊平；同比 "
                f"{pct_change(ttm_fcf[-1], ttm_fcf[-5]):+.1f}%，拐点出现在上一季。"
            ),
            "src_extra": source_note("按各季经营现金流减资本开支（含融资租赁本金）滚动四季求和（自算）"),
        },
        {
            "kind": "lines",
            "title": (
                f"两条非广告收入线分道扬镳：FoA Other 首破 $10 亿，Reality Labs 仍在 "
                f"${reality_labs_shown[-1]:,.0f}M"
            ),
            "xlabels": labels,
            "series": [
                {"name": "FoA Other", "values": foa_other_shown, "color": "NAVY"},
                {"name": "Reality Labs", "values": reality_labs_shown, "color": "MBLUE"},
            ],
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "zero_base": True,
            "end_label": True,
            "ylab": "$M",
            "note": (
                f"FoA Other 同比 {foa_other_yoy[-1]:+.1f}%、年化约 "
                f"${foa_other_shown[-1] * 4 / 1000:.1f}B，是唯一不依赖广告负载的增量引擎；"
                f"Reality Labs 收入同比 {pct_change(reality_labs_shown[-1], reality_labs_shown[-5]):+.1f}% 首次转正，"
                f"但本季经营亏损仍有 ${abs(snapshot['reality_labs_operating_loss_usd_m'][0]):,}M。"
            ),
            "src_extra": (
                "两条分项收入来自各期 10-Q / 10-K 的收入分解附注；Reality Labs 的 Q4 有硬件季节性，"
                "不宜按环比读。"
            ),
        },
        {
            "kind": "bars_labeled",
            "title": "本季四大区域收入同比：其他地区最快，欧洲与亚太落在中段",
            "xlabels": geography["regions"],
            "values": geography_yoy,
            "legend": "收入同比",
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "ylab": "同比增速",
            "note": (
                f"美国与加拿大占本季收入 "
                f"{geography['current'][0] / revenue_shown[-1] * 100:.1f}%，同比 {geography_yoy[0]:.1f}%；"
                "管理层同时表示新增曝光更多来自「变现能力较低的版面与地区」，"
                "这正是价格被结构稀释的来源。"
            ),
            "src_extra": (
                "分区域收入来自 Q2 2026 10-Q 的收入分解附注（本季与去年同期两列）；同比为自算。"
                "公司未按区域披露利润，本页不做区域盈利推断。"
            ),
        },
    ]

    exhibits = number_exhibits(settled_charts + highlights + next_charts + routine)
    first_table = len(exhibits) + 2

    quarterly_rows = []
    for index, period in enumerate(periods):
        quarterly_rows.append([
            period,
            f"${revenue[index]:,.0f}M",
            f"${advertising[index]:,.0f}M D",
            f"${q['foa_other_revenue'][index]:,.0f}M",
            f"${q['reality_labs_revenue'][index]:,.0f}M",
            f"${operating_income[index]:,.0f}M",
            f"${q['operating_cash_flow'][index]:,.0f}M",
            f"${capex_total[index]:,.0f}M D",
            (lambda value: f"-${abs(value):,.0f}M" if value < 0 else f"${value:,.0f}M")(
                free_cash_flow[index]
            ),
            f"${q['depreciation_and_amortization'][index]:,.0f}M",
            f"${q['share_based_compensation'][index]:,.0f}M",
            f"${q['stock_repurchases'][index]:,.0f}M",
        ])

    ad_rows = []
    for index, period in enumerate(periods):
        ad_rows.append([
            period,
            f"{ads['ad_impressions_yoy_pct'][index]:+.0f}%",
            f"{ads['price_per_ad_yoy_pct'][index]:+.0f}%",
            f"{volume_price_product[index]:+.1f}% D",
            "—" if index < 4 else f"{yoy(advertising)[index]:+.1f}% D",
            f"{ads['family_daily_active_people_bn'][index]:.2f}B",
        ])

    quality_rows = [
        ["总收入", f"${snapshot['revenue_usd_m'][2]:,}M", f"${snapshot['revenue_usd_m'][1]:,}M",
         f"${snapshot['revenue_usd_m'][0]:,}M",
         f"{pct_change(snapshot['revenue_usd_m'][0], snapshot['revenue_usd_m'][1]):+.1f}%",
         f"{pct_change(snapshot['revenue_usd_m'][0], snapshot['revenue_usd_m'][2]):+.1f}%"],
        ["广告收入", f"${snapshot['advertising_revenue_usd_m'][2]:,}M",
         f"${snapshot['advertising_revenue_usd_m'][1]:,}M", f"${snapshot['advertising_revenue_usd_m'][0]:,}M",
         f"{pct_change(snapshot['advertising_revenue_usd_m'][0], snapshot['advertising_revenue_usd_m'][1]):+.1f}%",
         f"{pct_change(snapshot['advertising_revenue_usd_m'][0], snapshot['advertising_revenue_usd_m'][2]):+.1f}%"],
        ["Family of Apps 经营利润", f"${snapshot['family_of_apps_operating_income_usd_m'][2]:,}M",
         f"${snapshot['family_of_apps_operating_income_usd_m'][1]:,}M",
         f"${snapshot['family_of_apps_operating_income_usd_m'][0]:,}M",
         f"{pct_change(snapshot['family_of_apps_operating_income_usd_m'][0], snapshot['family_of_apps_operating_income_usd_m'][1]):+.1f}%",
         f"{pct_change(snapshot['family_of_apps_operating_income_usd_m'][0], snapshot['family_of_apps_operating_income_usd_m'][2]):+.1f}%"],
        ["Reality Labs 经营亏损", f"-${abs(snapshot['reality_labs_operating_loss_usd_m'][2]):,}M",
         f"-${abs(snapshot['reality_labs_operating_loss_usd_m'][1]):,}M",
         f"-${abs(snapshot['reality_labs_operating_loss_usd_m'][0]):,}M", "亏损扩大", "亏损扩大"],
        ["经营利润（GAAP）", f"${snapshot['operating_income_usd_m'][2]:,}M",
         f"${snapshot['operating_income_usd_m'][1]:,}M", f"${snapshot['operating_income_usd_m'][0]:,}M",
         f"{pct_change(snapshot['operating_income_usd_m'][0], snapshot['operating_income_usd_m'][1]):+.1f}%",
         f"{pct_change(snapshot['operating_income_usd_m'][0], snapshot['operating_income_usd_m'][2]):+.1f}%"],
        ["经营利润（调整后 D）", "—", "—",
         f"${snapshot['adjusted_operating_income_usd_m']:,}M", "—",
         f"{pct_change(snapshot['adjusted_operating_income_usd_m'], snapshot['operating_income_usd_m'][2]):+.1f}%"],
        ["稀释 EPS", f"${snapshot['diluted_eps_usd'][2]:.2f}", f"${snapshot['diluted_eps_usd'][1]:.2f}",
         f"${snapshot['diluted_eps_usd'][0]:.2f}",
         f"{pct_change(snapshot['diluted_eps_usd'][0], snapshot['diluted_eps_usd'][1]):+.1f}%",
         f"{pct_change(snapshot['diluted_eps_usd'][0], snapshot['diluted_eps_usd'][2]):+.1f}%"],
        ["经营现金流", f"${snapshot['operating_cash_flow_usd_m'][2]:,}M",
         f"${snapshot['operating_cash_flow_usd_m'][1]:,}M", f"${snapshot['operating_cash_flow_usd_m'][0]:,}M",
         f"{pct_change(snapshot['operating_cash_flow_usd_m'][0], snapshot['operating_cash_flow_usd_m'][1]):+.1f}%",
         f"{pct_change(snapshot['operating_cash_flow_usd_m'][0], snapshot['operating_cash_flow_usd_m'][2]):+.1f}%"],
        ["资本开支（含融资租赁）", f"${snapshot['capex_incl_finance_leases_usd_m'][2]:,}M",
         f"${snapshot['capex_incl_finance_leases_usd_m'][1]:,}M",
         f"${snapshot['capex_incl_finance_leases_usd_m'][0]:,}M",
         f"{pct_change(snapshot['capex_incl_finance_leases_usd_m'][0], snapshot['capex_incl_finance_leases_usd_m'][1]):+.1f}%",
         f"{pct_change(snapshot['capex_incl_finance_leases_usd_m'][0], snapshot['capex_incl_finance_leases_usd_m'][2]):+.1f}%"],
        ["自由现金流 D", f"${snapshot['free_cash_flow_usd_m'][2]:,}M",
         f"${snapshot['free_cash_flow_usd_m'][1]:,}M", f"${snapshot['free_cash_flow_usd_m'][0]:,}M",
         f"{pct_change(snapshot['free_cash_flow_usd_m'][0], snapshot['free_cash_flow_usd_m'][1]):+.1f}%",
         f"{pct_change(snapshot['free_cash_flow_usd_m'][0], snapshot['free_cash_flow_usd_m'][2]):+.1f}%"],
        ["计入应付的未付资本开支", f"${snapshot['unpaid_capex_in_payables_usd_m'][2]:,}M", "—",
         f"${snapshot['unpaid_capex_in_payables_usd_m'][0]:,}M", "—",
         f"{pct_change(snapshot['unpaid_capex_in_payables_usd_m'][0], snapshot['unpaid_capex_in_payables_usd_m'][2]):+.1f}%"],
        ["其他资产项下的受限现金", f"${snapshot['restricted_cash_in_other_assets_usd_m'][2]:,}M", "—",
         f"${snapshot['restricted_cash_in_other_assets_usd_m'][0]:,}M", "—", "公司未解释性质"],
        ["员工数", f"{snapshot['headcount'][2]:,}", f"{snapshot['headcount'][1]:,}",
         f"{snapshot['headcount'][0]:,}",
         f"{pct_change(snapshot['headcount'][0], snapshot['headcount'][1]):+.1f}%",
         f"{pct_change(snapshot['headcount'][0], snapshot['headcount'][2]):+.1f}%"],
    ]

    expense = staging["quarter_expense_lines_usd_m"]
    expense_rows = [
        [
            name,
            f"${prior:,}M",
            f"${current:,}M",
            f"{pct_change(current, prior):+.1f}%",
            f"{current / revenue_shown[-1] * 100:.2f}%",
        ]
        for name, current, prior in zip(expense["lines"], expense["current"], expense["prior_year"])
    ]
    expense_rows.append([
        "合计",
        f"${sum(expense['prior_year']):,}M",
        f"${sum(expense['current']):,}M",
        f"{pct_change(sum(expense['current']), sum(expense['prior_year'])):+.1f}%",
        f"{sum(expense['current']) / revenue_shown[-1] * 100:.2f}%",
    ])

    guidance_rows = [
        ["Q3 2026 收入", "—", "—",
         f"US${guidance['q3_revenue_usd_m'][0] / 1000:.0f}–{guidance['q3_revenue_usd_m'][1] / 1000:.0f}B",
         f"中点 ${q3_midpoint:,.0f}M，隐含同比 {signed(q3_yoy)} D"],
        ["FY2026 总费用",
         f"US${guidance['fy2026_expenses_prior_usd_bn'][0]}–{guidance['fy2026_expenses_prior_usd_bn'][1]}B",
         "—",
         f"US${guidance['fy2026_expenses_usd_bn'][0]}–{guidance['fy2026_expenses_usd_bn'][1]}B",
         "下限抬高 $3B 以吸收本季法律计提"],
        ["FY2026 CapEx",
         f"US${guidance['fy2026_capex_prior_usd_bn'][0]}–{guidance['fy2026_capex_prior_usd_bn'][1]}B",
         f"H1 已实现 ${guidance['h1_2026_capex_usd_m']:,}M",
         f"US${guidance['fy2026_capex_usd_bn'][0]}–{guidance['fy2026_capex_usd_bn'][1]}B",
         f"中点由 US${capex_guide_mid[1]:.0f}B 抬到 US${capex_guide_mid[2]:.1f}B D"],
        ["FY2026 经营利润", guidance["fy2026_operating_income_commitment"],
         f"H1 ${half_year_actual:,}M", guidance["fy2026_operating_income_commitment"],
         f"FY2025 为 ${fy2025['operating_income']:,}M；半程线 ${half_year_line:,.0f}M D"],
        ["余下各季有效税率",
         f"{guidance['tax_rate_prior_pct'][0]}–{guidance['tax_rate_prior_pct'][1]}%", "—",
         f"{guidance['tax_rate_pct'][0]}–{guidance['tax_rate_pct'][1]}%", "上调约 2pp"],
        ["FY2027 CapEx", "拒绝提供", "—", guidance["fy2027_capex"], "连续两季拒绝，可建模性为零"],
    ]

    tables = [
        threshold_table(
            first_table,
            "上季阈值与本季实际（原单位）",
            prior_kpi["quantified"],
            "actual",
            "Q2 2026 实际",
        ),
        threshold_table(
            first_table + 1,
            "下季阈值与当前值（原单位）",
            next_kpi["quantified"],
            "current",
            "当前值",
        ),
        {
            "n": first_table + 2,
            "title": "Q2 兑现、Q3 指引与全年 outlook",
            "headers": ["指标", "上季口径", "本季已实现", "本季新口径", "变化 / 备注"],
            "rows": guidance_rows,
        },
        {
            "n": first_table + 3,
            "title": "当季经营质量与可比性（Q2 2025 / Q1 2026 / Q2 2026）",
            "headers": ["指标", "Q2 2025", "Q1 2026", "Q2 2026", "QoQ", "YoY"],
            "rows": quality_rows,
        },
        {
            "n": first_table + 4,
            "title": "十二季度基础数据（前四季只用于计算同比）",
            "headers": ["期间", "总收入", "广告收入", "FoA Other", "Reality Labs", "经营利润",
                        "经营现金流", "资本开支", "自由现金流 D", "折旧摊销", "股权激励", "回购"],
            "rows": quarterly_rows,
        },
        {
            "n": first_table + 5,
            "title": "十二季度广告量价与用户",
            "headers": ["期间", "曝光 YoY", "单价 YoY", "量价乘积 D", "广告收入 YoY D", "Family DAP"],
            "rows": ad_rows,
        },
        {
            "n": first_table + 6,
            "title": "本季四条费用线（Q2 2026 vs Q2 2025）",
            "headers": ["费用线", "Q2 2025", "Q2 2026", "YoY", "占本季收入 D"],
            "rows": expense_rows,
        },
        ai_capex_cycle_table(first_table + 7),
    ]

    return {
        "schema_version": "quarterly-dashboard/meta-v1",
        "page": {"slug": "meta", "language": "zh-CN"},
        "company": {
            "ticker": "META",
            "name": "Meta Platforms",
            "group": "internet",
            "accounting_standard": "US GAAP",
        },
        "latest": {
            "disclosed_period_label": "Q2 2026",
            "full_financial_period_label": "Q2 2026",
            "period_end": "2026-06-30",
            "release_date": "2026-07-29",
            "analysis_date": "2026-07-30",
            "audit_status": "unaudited",
            "status": "history_ready",
        },
        "tracker": "Watchlist Quarterly Tracker · META",
        "title": "Meta Platforms (META)：Q2 2026 季报仪表盘",
        "subtitle": "截至 2026-06-30 · 发布 2026-07-29 · US GAAP · 未审计 · 金额单位为 $M，另有注明除外",
        "headline": (
            f"广告引擎本身没坏——收入 ${revenue_shown[-1]:,}M、同比 {revenue_yoy[-1]:.1f}%，"
            "量价桥两季都能闭合；但多做的收入不再产生利润："
            f"剔除 $3,580M 一次性项后经营利润仍环比 "
            f"{pct_change(snapshot['adjusted_operating_income_usd_m'], operating_income[-2]):.1f}%，"
            f"同比增量经营利润率只有 {adjusted_incremental_margin:.1f}%，"
            f"单季自由现金流塌到 ${fcf_shown[-1]:,}M。财报后股价下跌约 "
            f"{abs(price_high):.0f}%–{abs(price_low):.0f}%。"
        ),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>亮点</span><b>广告绝对竞争力没有裂缝</b>'
            f'<p>广告收入同比 {advertising_yoy[-1]:.1f}%，单价连续两季 +12%；'
            f'FoA Other 首破 $10 亿、同比 {foa_other_yoy[-1]:.0f}%。</p></article>'
            '<article><span>结构</span><b>减速全部来自量</b>'
            '<p>曝光同比 19% → 14%，价格贡献 0pp；曝光与 DAP 之间约 11pp 靠广告负载。</p></article>'
            '<article><span>存疑</span><b>增量资本没有产出增量利润</b>'
            f'<p>同比增量经营利润率 {adjusted_incremental_margin:.1f}%，'
            f'资本开支占收入 {capex_intensity[-1]:.1f}%。</p></article>'
            '</div>'
        ),
        "source": source,
        "source_url": "https://investor.atmeta.com/",
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {
                "id": "settled",
                "title": "一、上季跟踪指标兑现了吗",
                "description": "先结算上季留下的问题与阈值，再看本季数据——否则页面只会不断累积判断，从不闭环。",
                "exhibits": exhibits[: len(settled_charts)],
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": "收入与指引、广告的量价拆分、一次性项之后的经营利润、现金流与资本开支的两次上调。",
                "exhibits": exhibits[len(settled_charts): len(settled_charts) + len(highlights)],
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": "同一套口径向前看：当前值离下季阈值还有多远，统一用「距阈值余量」表示。",
                "exhibits": exhibits[
                    len(settled_charts) + len(highlights):
                    len(settled_charts) + len(highlights) + len(next_charts)
                ],
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": "META 专属的常规序列：折旧曲线、现金转换、非广告收入线与区域结构。",
                "exhibits": exhibits[-len(routine):],
            },
        ],
        "tables": tables,
        "notes": [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            f"Exhibit 3 与 Exhibit {len(settled_charts) + len(highlights) + 2} 的阈值是本地研究设定，"
            "不是公司指引，也不构成评级或投资建议；「距阈值余量」统一为正值代表安全侧。",
            "本页只发布公司披露值、可复算的简单派生值，以及明确标注的市场预期；D 标记代表 Derived / 自算。",
            "市场预期一律标注为「市场预期」并给出取数时点，不写卖方机构名，也不发布评级、目标价或估值。",
            "调整后经营利润 = GAAP 经营利润加回本季法律计提 $2,400M 与遣散费 $1,180M，是算术加总，"
            "不是公司定义的 non-GAAP 指标；两笔加回项未按分部披露，因此分部层面的调整后利润率无法拆分。",
            "同比增量经营利润率 = （本季经营利润 − 去年同期经营利润）÷（本季收入 − 去年同期收入），"
            "用同比而非环比，是因为 Q4 的季节性足以让环比口径每年两次翻转符号。",
            "广告收入 = 总收入 − Reality Labs − FoA Other，三条线始终加回报告总额；"
            "量价乘积为公司披露的曝光与单价同比相乘，与实际广告收入增速的差异来自整数舍入。",
            "自由现金流按公司口径 = 经营现金流 − 购买物业及设备 − 融资租赁本金偿付；资本开支同口径含融资租赁。",
            "资本开支指引只覆盖进入公司报表的部分；以合资、租赁与残值担保结构取得的算力不进入这条线，"
            "本页因此把资本强度曲线标注为下界而非全貌。",
            "财报后股价反应各公开来源报价不一致（约 7%–11%），本页只发布区间，不取单一数值。",
            "季度值来自各期 10-Q 与 10-K；无 10-Q 的第四季度按「全年 − 前三季」倒推，"
            "个别科目因公司按百万美元四舍五入，倒推值与逐季披露值存在 $1M 级差异。",
            "本页已知未接入：分部季度经营利润的完整历史、区域收入的多季序列、按分部拆分的一次性项、"
            "以及电话会口径的 Meta AI、business agents、AI 眼镜等运营 KPI（公司仅给相对数）。",
        ],
        "footer": (
            "META quarterly results · 数据来自 Meta Platforms 公开披露与透明自算 · "
            "仅供研究，不构成投资建议"
        ),
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "meta.js"), payload, "meta")
    shell_dir = ROOT / "meta"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(SHELL, encoding="utf-8")
    exhibits = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"META page: {exhibits} charts in 4 sections + {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
