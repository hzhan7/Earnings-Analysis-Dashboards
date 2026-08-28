#!/usr/bin/env python3
"""Build the MA quarterly-results page.

Same four-part, chart-led shape as the other company pages (上季兑现 → 本季重点
→ 下季跟踪 → 长期常规).  Mastercard's calendar year is its fiscal year, so no
relabelling is needed here.

What this page has instead of a guidance record.  Six of the companies on this
site put a quarterly range in a filing, which lets their first section settle
"guidance versus actual" quarter by quarter.  Mastercard files no forward
number at all -- its earnings 8-K contains no Outlook block and the words
``outlook``, ``guidance`` and ``we expect`` do not appear in it; the outlook is
given on the call as "high end of low double-digit", which has neither a floor
nor a ceiling to clear.  So the page carries the one quantity the company must
publish every quarter and that *can* be settled against itself: the share of
gross billings it hands back to issuers as rebates and incentives.

That number is not printed either.  Under the presentation Mastercard adopted
in the first quarter of 2023 the four assessment lines are printed gross and
the payment network is printed net, so the rebate is the difference of two
filed figures -- and the company's own stated rebate growth rate reproduces
from it, which is what licenses the series.

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


STAGING_PATH = ROOT / "series" / "ma.json"
DATA_DIR = ROOT / "data"

# The record is eighteen quarters, not eight: one quarter cannot say whether a
# rebate ratio of 52% is high for this company, and the eight-quarter window
# would start after the ratio had already moved most of the way.
WINDOW = 18
# Four quarters of base are needed before any year-over-year line exists.
YOY_FROM = 4

ASSESSMENT_LINES = (
    "domestic_assessments",
    "cross_border_assessments",
    "transaction_processing_assessments",
    "other_network_assessments",
)


def compact_period(period: str) -> str:
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


def yoy(values: list[float]) -> list[float | None]:
    return [None] * 4 + [
        (values[index] / values[index - 4] - 1) * 100 for index in range(4, len(values))
    ]


def increments(values: list[float]) -> list[float | None]:
    return [None] * 4 + [values[index] - values[index - 4] for index in range(4, len(values))]


def trailing(values: list[float]) -> list[float | None]:
    return [None] * 3 + [sum(values[index - 3:index + 1]) for index in range(3, len(values))]


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100


def rounded(values: list[float | None], digits: int = 6) -> list[float | None]:
    return [None if value is None else round(value, digits) for value in values]


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    labels = [compact_period(period) for period in periods]
    pn = staging["payment_network_usd_m"]
    q = staging["quarterly_usd_m"]
    ps = staging["per_share"]
    bs = staging["balance_sheet_usd_m"]
    drivers = staging["key_drivers_local_pct"]
    cn = staging["assessment_currency_neutral_growth_pct"]
    snapshot = staging["current_snapshot"]
    disclosure = staging["guidance_disclosure"]
    consensus = staging["market_expectation"]
    closure = staging["followup_closure"]
    prior_kpi = staging["prior_kpi_settlement"]
    next_kpi = staging["next_kpi"]
    crosscheck = staging["adjusted_margin_crosscheck"]

    net_revenue = pn["total_net_revenue"]
    network_net = pn["payment_network_net_revenue"]
    vas = pn["value_added_services_net_revenue"]

    # ── The one derived line the whole page rests on ─────────────────────────
    # Gross billings is the sum of the four printed assessment lines; the
    # payment network is printed net of rebates. The difference is therefore
    # the rebate, from two filed numbers and no estimate.
    gross = [sum(pn[line][index] for line in ASSESSMENT_LINES) for index in range(len(periods))]
    rebates = [g - n for g, n in zip(gross, network_net)]
    rebate_ratio = [r / g * 100 for r, g in zip(rebates, gross)]
    ratio_change = increments(rebate_ratio)

    gross_yoy = yoy(gross)
    network_yoy = yoy(network_net)
    gross_step = increments(gross)
    network_step = increments(network_net)
    rebate_step = increments(rebates)
    vas_step = increments(vas)
    net_step = increments(net_revenue)
    vas_share = [v / total * 100 for v, total in zip(vas, net_revenue)]

    # The company's own adjusted operating margin, rebuilt from filed lines:
    # its only operating-expense adjustments are the litigation provision (its
    # own income-statement line) and the one restructuring charge.
    adjusted_operating_income = [
        income + litigation + restructuring
        for income, litigation, restructuring in zip(
            q["operating_income"], q["provision_for_litigation"], q["restructuring_charge"]
        )
    ]
    gaap_margin = [
        income / total * 100 for income, total in zip(q["operating_income"], net_revenue)
    ]
    adjusted_margin = [
        income / total * 100 for income, total in zip(adjusted_operating_income, net_revenue)
    ]

    free_cash_flow = [
        operating - property_spend - software
        for operating, property_spend, software in zip(
            q["operating_cash_flow"],
            q["purchases_of_property_and_equipment"],
            q["capitalized_software"],
        )
    ]
    shareholder_returns = [
        repurchase + dividend
        for repurchase, dividend in zip(q["stock_repurchases"], q["dividends_paid"])
    ]
    incentive_cash_drain = [
        prepaid - amortisation
        for prepaid, amortisation in zip(
            q["prepaid_expense_cash_outflow"], q["amortization_of_customer_incentives"]
        )
    ]
    repurchase_price = [
        cost / count for cost, count in zip(q["stock_repurchases"], ps["shares_repurchased_m"])
    ]
    total_debt = [
        short + long for short, long in zip(bs["short_term_debt"], bs["long_term_debt"])
    ]

    trailing_operating_cash = trailing(q["operating_cash_flow"])
    trailing_net_income = trailing(q["net_income"])
    trailing_conversion = [
        None if cash is None else cash / income * 100
        for cash, income in zip(trailing_operating_cash, trailing_net_income)
    ]
    trailing_free_cash = trailing(free_cash_flow)
    trailing_returns = trailing(shareholder_returns)
    trailing_coverage = [
        None if cash is None else returns / cash * 100
        for cash, returns in zip(trailing_free_cash, trailing_returns)
    ]

    # Year-to-date conversion is what the tracked threshold is written on, and
    # it is the reading that moved: the company's cash customer incentives are
    # front-loaded, so the first-half number is the comparable one.
    ytd_conversion: list[float] = []
    cash_sum = income_sum = 0.0
    for index, period in enumerate(periods):
        if period.startswith("Q1"):
            cash_sum = income_sum = 0.0
        cash_sum += q["operating_cash_flow"][index]
        income_sum += q["net_income"][index]
        ytd_conversion.append(cash_sum / income_sum * 100)

    # Currency-neutral price spread: the company publishes each assessment
    # line's currency-neutral growth only for the quarter just reported, so the
    # fourth quarters are holes rather than interpolations.
    spreads = {
        "境内计费 vs GDV": [
            None if value is None else value - volume
            for value, volume in zip(cn["domestic"], drivers["gdv"])
        ],
        "跨境计费 vs 跨境量": [
            None if value is None else value - volume
            for value, volume in zip(cn["cross_border"], drivers["cross_border"])
        ],
        "清算计费 vs 换手笔数": [
            None if value is None else value - volume
            for value, volume in zip(cn["transaction"], drivers["switched"])
        ],
    }

    plateau = [value for value in network_step[-7:]]
    ratio_up = sum(1 for value in ratio_change[YOY_FROM:] if value > 0)
    ratio_down = len(ratio_change) - YOY_FROM - ratio_up
    latest = len(periods) - 1
    worst_ratio_move = min(ratio_change[YOY_FROM:])

    # Two "how long has this been true" counts the copy quotes; both are read
    # off the series rather than typed, so a new quarter cannot leave them stale.
    vas_gap = [
        None if network is None else pct_change(vas[index], vas[index - 4]) - network
        for index, network in enumerate(network_yoy)
    ]
    gap_run = 0
    for value in reversed(vas_gap):
        if value is None or value < 8:
            break
        gap_run += 1
    price_run = 0
    for value in reversed(repurchase_price[:-1]):
        if value <= repurchase_price[latest]:
            break
        price_run += 1
    leverage = [debt / equity for debt, equity in zip(total_debt, bs["total_equity"])]
    driver_band = drivers["gdv"][-6:] + drivers["switched"][-6:]

    source = (
        'Source: <a href="https://investor.mastercard.com/" rel="noopener">'
        'Mastercard Investor Relations</a>（Q2 2026 earnings release 与电话会；'
        '逐季数据经 SEC EDGAR 的 10-Q / 10-K / 8-K 回源）。'
    )
    source_filings = (
        "毛计费四条线取自各期 10-Q / 10-K 管理层讨论与分析里的「Key Metrics related to the "
        "Payment Network」表，支付网络与增值服务的净收入取自同期收入附注；返点为两者相减的自算值。"
    )

    def source_note(detail: str) -> str:
        return f"{detail}；历史期同口径。自算项目均可在核对表中复核。"

    tracked = {
        "单季回购金额": (q["stock_repurchases"], "f0c", "$M", "单季回购"),
        "回购隐含均价": (repurchase_price, "usd0", "$/股", "隐含均价 D"),
        "返点占毛计费比率": (rebate_ratio, "pct1", "占毛计费", "返点占比 D"),
        "年初至今经营现金流 / 净利润": (ytd_conversion, "pct1", "累计比率", "年初至今 OCF / 净利润 D"),
    }

    def tracking_charts(entries, value_key, threshold_label, headline) -> list[dict]:
        charts = []
        for entry in entries:
            metric = entry["metric"]
            if metric not in tracked:
                continue
            values, fmt, ylab, actual_name = tracked[metric]
            side = "上方" if entry["direction"] == "up" else "下方"
            charts.append(threshold_exhibit(
                headline(entry),
                labels,
                rounded(values),
                entry["threshold"],
                fmt=fmt,
                ylab=ylab,
                actual_name=actual_name,
                threshold_name=f"{threshold_label}（安全侧在{side}）",
                note=(
                    f"阈值 {unit_text(entry['unit'], entry['threshold'])}，"
                    f"当前 {unit_text(entry['unit'], entry[value_key])}，"
                    f"余量 {headroom(entry['direction'], entry['threshold'], entry[value_key]):+.1f}%。"
                    + ("回购股数按 0.1 百万股披露，两个累计值相减后本季均价的区间是 "
                       f"${q['stock_repurchases'][latest] / (ps['shares_repurchased_m'][latest] + 0.1):.0f}–"
                       f"${q['stock_repurchases'][latest] / (ps['shares_repurchased_m'][latest] - 0.1):.0f}。"
                       if metric == "回购隐含均价" else "")
                    + ("第一季只含三个月、第二季含六个月，这条线因此每年重新起跳；"
                       "可比的是同一季之间的高低，不是相邻两点。"
                       if metric == "年初至今经营现金流 / 净利润" else "")
                ),
                src_extra=(
                    "实际值来自各期 10-Q / 10-K 与当季 earnings release；"
                    "阈值为本地研究设定，不是公司指引。"
                ),
            ))
        return charts

    # ── 一、上季兑现 ─────────────────────────────────────────────────────────
    settled_charts = [
        {
            "kind": "bars_labeled",
            "title": (
                f"上季 5 条待验证问题：{closure['counts'][0]} 条已验证、"
                f"{closure['counts'][1]} 条部分验证、{closure['counts'][2]} 条被证伪"
            ),
            "xlabels": closure["labels"],
            "values": closure["counts"],
            "legend": "问题条数",
            "fmt": "f0",
            "yfmt": "f0",
            "label_fmt": "f0",
            "ylab": "条",
            "note": (
                "三条「部分验证」的共同点是公司答了时点、没答经济性："
                "中东影响的恢复轨迹兑现了但管理层把下半年假设改成「维持本季末水平」，"
                "增值服务守住了增速但拒绝更新子线口径，收购按预告在下季交割但连续三季不给单位经济。"
                "两条被证伪的都指向资本与成本：回购节奏与运营杠杆的方向都与上季判断相反。"
            ),
            "src_extra": (
                "问题清单来自上季本地分析稿的 follow-up；验证结果依据本季 earnings release、"
                "电话会与 Q2 2026 10-Q。"
            ),
        },
        headroom_exhibit(
            "上季 4 条可结算阈值全部守住 —— 而本季真正变化的两件事，它们一条都没覆盖",
            prior_kpi["quantified"],
            "actual",
            (
                "正值 = 仍在安全侧。四条都过了，但本季移动的是另外两处："
                f"返点占毛计费同比再升 {ratio_change[latest]:+.2f}pp，"
                f"上半年经营现金流同比 {pct_change(sum(q['operating_cash_flow'][-2:]), sum(q['operating_cash_flow'][-6:-4])):.1f}%、"
                f"净利润 {pct_change(sum(q['net_income'][-2:]), sum(q['net_income'][-6:-4])):+.1f}%。"
                "<b>上季五条阈值全部落在损益表和外部环境上，没有一条指向现金流量表</b>，"
                "所以它们全部守住并不说明这一季没有问题。"
            ),
            src_extra=(
                "阈值为上季本地研究设定，不是公司指引；实际值为本季披露值。"
                "跨境 travel 的两条只出现在公司季度业绩演示文稿，不进任何申报文件——"
                "本站因此不为它建历史序列，只结算本季读数。"
                "另有两条已退役：全年收入固定汇率增速那条无法结算（见下段），"
                "CCCA 议题热度连续两季零信号且不是任何申报文件里的量。"
            ),
        ),
    ]
    settled_charts += tracking_charts(
        [entry for entry in prior_kpi["quantified"] if entry["metric"] == "单季回购金额"],
        "actual",
        "上季阈值",
        lambda entry: (
            f"{entry['metric']}：本季 ${q['stock_repurchases'][latest]:,}M 创十八季新高，"
            f"守住上季 {unit_text(entry['unit'], entry['threshold'])} 的阈值"
        ),
    )
    settled_charts.append({
        "kind": "lines",
        "title": (
            f"申报文件能给的三条量：跨境量增速已连续三季走低到 "
            f"{drivers['cross_border'][latest]}%，GDV 与换手笔数六个季度都在 "
            f"{min(driver_band)}–{max(driver_band)}% 的窄带里"
        ),
        "xlabels": labels,
        "xrot": 90,
        "series": [
            {"name": "跨境量（本地货币）", "values": drivers["cross_border"], "color": "NAVY"},
            {"name": "GDV（本地货币）", "values": drivers["gdv"], "color": "MBLUE"},
            {"name": "换手笔数", "values": drivers["switched"], "color": "GRAY"},
        ],
        "fmt": "pct0",
        "yfmt": "pct0",
        "label_fmt": "pct0",
        "zero_base": True,
        "end_label": True,
        "ylab": "同比增速",
        "note": (
            "上季那条阈值挂在跨境量里的 travel 一条上，而 travel 与 CNP 的拆分只在演示文稿里，"
            "<b>申报文件只给这三条</b>。三条都指向同一件事：量的贡献在变薄——"
            f"跨境量连续三季走低（{drivers['cross_border'][-4]}% → {drivers['cross_border'][-3]}% → "
            f"{drivers['cross_border'][-2]}% → {drivers['cross_border'][latest]}%），"
            f"GDV 与换手笔数六个季度都落在 {min(driver_band)}–{max(driver_band)}% 之间。"
            "2022 年那几个高点带着俄罗斯业务退出的基数效应，公司在当期文件里另给了剔除口径。"
        ),
        "src_extra": (
            "三条驱动指标的季度增速取自各期 10-Q 的「Key Metrics」表；第四季没有 10-Q，"
            "取自当季 earnings release 的 Key Business Drivers 表。公司只披露增速、不披露金额。"
            "2026 年起这几条指标并入了委内瑞拉的跨境活动并追溯重述，10-Q 有脚注但未量化其贡献。"
        ),
    })

    # ── 二、本季重点 ─────────────────────────────────────────────────────────
    highlights = [
        {
            "ref": "EX_LEGS",
            "kind": "grouped_bars",
            "title": (
                f"净收入的同比增量拆成三条腿：毛计费 +${gross_step[latest]:,.0f}M、"
                f"返点 −${rebate_step[latest]:,.0f}M、增值服务 +${vas_step[latest]:,.0f}M"
            ),
            "xlabels": labels[YOY_FROM:],
            "xrot": 90,
            "groups": [
                {"name": "毛计费腿", "color": "NAVY", "values": rounded(gross_step[YOY_FROM:])},
                {"name": "返点腿", "color": "RED",
                 "values": rounded([-value for value in rebate_step[YOY_FROM:]])},
                {"name": "增值服务腿", "color": "GOLD", "values": rounded(vas_step[YOY_FROM:])},
            ],
            "bar_labels": False,
            "fmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M vs 去年同期",
            "note": (
                "这不是估计，是恒等式：净收入 = 四条计费线合计 − 返点 + 增值服务，"
                "所以同比增量<b>恰好</b>等于三条腿之和，"
                f"本季 ${gross_step[latest]:,.0f} − ${rebate_step[latest]:,.0f} + "
                f"${vas_step[latest]:,.0f} = ${net_step[latest]:,.0f}M，与申报的净收入增量一分不差。"
                f"<b>读数：</b>返点腿吃掉了毛计费腿的 "
                f"{rebate_step[latest] / gross_step[latest] * 100:.0f}%，"
                f"剩给支付网络的只有 ${network_step[latest]:,.0f}M；"
                f"净增量里 {vas_step[latest] / net_step[latest] * 100:.0f}% 来自增值服务，"
                "而增值服务不承担返点。"
            ),
            "src_extra": source_filings,
        },
        {
            "ref": "EX_PLATEAU",
            "kind": "lines",
            "title": (
                f"毛计费的同比增量从 ${gross_step[YOY_FROM]:,.0f}M 涨到 ${gross_step[latest]:,.0f}M，"
                f"落到净支付网络收入的增量连续七季卡在 ${min(plateau):,.0f}–${max(plateau):,.0f}M"
            ),
            "xlabels": labels[YOY_FROM:],
            "xrot": 90,
            "series": [
                {"name": "毛计费同比增量", "values": rounded(gross_step[YOY_FROM:]), "color": "NAVY"},
                {"name": "净支付网络收入同比增量", "values": rounded(network_step[YOY_FROM:]), "color": "GOLD"},
            ],
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "zero_base": True,
            "end_label": True,
            "ylab": "$M vs 去年同期",
            "note": (
                "<b>这是全页最要紧的一张。</b>两条线之间的缺口就是返点腿。"
                f"毛计费的年增量从 {labels[YOY_FROM]} 到本季增加了 "
                f"{pct_change(gross_step[latest], gross_step[YOY_FROM]):.0f}%，"
                "而它落到净收入上的部分几乎没有动："
                + "、".join(f"{labels[index]} ${network_step[index]:,.0f}M"
                           for index in range(len(periods) - 7, len(periods)))
                + "。多计的费全部被返点接走了，所以「跨境计费同比 +20%」这类数字"
                "在毛口径上成立，在净口径上不成立。"
            ),
            "src_extra": source_filings,
        },
        {
            "ref": "EX_RATIO",
            "kind": "gs_line",
            "title": (
                f"返点占毛计费从 {rebate_ratio[0]:.1f}% 升到 {rebate_ratio[latest]:.1f}%，"
                f"峰值 {max(rebate_ratio):.1f}% 出现在 {labels[rebate_ratio.index(max(rebate_ratio))]}"
            ),
            "xlabels": labels,
            "xrot": 90,
            "values": rounded(rebate_ratio),
            "legend": "返点 / 毛计费 D",
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "ylab": "占毛计费",
            "note": (
                "分子分母是同一季、同一币种的两个申报数相减与相除，所以这条线不受汇率影响，"
                "也不需要固定汇率口径。"
                f"本季环比 {rebate_ratio[latest] - rebate_ratio[latest - 1]:+.2f}pp 是记录里少见的回落，"
                "但管理层在电话会上已经预告下季这个比例会环比再升。"
                f"可比的 {ratio_up + ratio_down} 次同比里只有一次下降（见下一张）。"
            ),
            "src_extra": source_filings + (
                "公司自己在业绩发布里说本季返点同比 +22%，本页的减法给出 "
                f"{pct_change(rebates[latest], rebates[latest - 4]):+.1f}%；"
                "六个月口径公司说 +22%、减法给出 +22.5%，四舍五入后一致。"
            ),
        },
        {
            "ref": "EX_RATIO_YOY",
            "kind": "diverging_bars",
            "title": (
                f"返点占比的同比变化：{ratio_up + ratio_down} 个可比季里 {ratio_up} 次上升，"
                f"唯一一次下降只有 {abs(worst_ratio_move):.2f}pp"
            ),
            "xlabels": labels[YOY_FROM:],
            "xrot": 90,
            "values": rounded(ratio_change[YOY_FROM:]),
            "legend": "返点占比同比变化",
            "positive_label": "返点更重",
            "negative_label": "返点更轻",
            "fmt": "pp1",
            "yfmt": "pp1",
            "label_fmt": "pp1",
            "ylab": "pp vs 去年同期",
            "zero_line": True,
            "note": (
                "本站其他公司页的第一节问「这一季有没有跌破自己的指引下限」；这张问的是同一类问题——"
                f"<b>这个比例有没有回过头</b>。{ratio_up + ratio_down} 次里只有一次，而且只有 "
                f"{abs(worst_ratio_move):.2f}pp。"
                "一条几乎单向的比率不是「这一季偏高」，是结构。"
                "注意方向：正值代表公司让出去的比例更大，不是更小。"
            ),
            "src_extra": source_filings,
        },
        {
            "ref": "EX_SPREAD",
            "kind": "lines",
            "title": (
                f"固定汇率的价差：跨境这条本季 {spreads['跨境计费 vs 跨境量'][latest]:+.0f}pp，"
                f"是记录里最高的一次；清算那条从上季的 "
                f"{spreads['清算计费 vs 换手笔数'][latest - 1]:+.0f}pp 收窄到 "
                f"{spreads['清算计费 vs 换手笔数'][latest]:+.0f}pp"
            ),
            "xlabels": labels,
            "xrot": 90,
            "series": [
                {"name": "跨境计费 − 跨境量", "values": spreads["跨境计费 vs 跨境量"], "color": "NAVY"},
                {"name": "清算计费 − 换手笔数", "values": spreads["清算计费 vs 换手笔数"], "color": "MBLUE"},
                {"name": "境内计费 − GDV", "values": spreads["境内计费 vs GDV"], "color": "GRAY"},
            ],
            "fmt": "pp0",
            "yfmt": "pp0",
            "label_fmt": "pp0",
            "ylab": "pp（计费增速 − 量增速）",
            "note": (
                "两条腿都是公司自己披露的固定汇率数，所以这个差里没有汇率。"
                "正值 = 每一元交易额收到的费在涨。"
                "<b>但价差是毛口径的</b>：它衡量的是账单，不是留下的钱——"
                "上面那张已经说明多收的部分去了哪里。"
                "2023 年以后每个第四季都是缺口，因为公司只在当季 10-Q 里给出该季各条线的固定汇率增速，"
                "第四季只有全年数；2022 年的四个季度整体没有新口径的固定汇率数，本页不往前接。"
            ),
            "src_extra": (
                "计费线的固定汇率增速取自各期 10-Q 的 Key Metrics 表；"
                "量增速为同表的本地货币口径。两者均为公司披露值，差为自算。"
            ),
        },
        {
            "ref": "EX_MIX",
            "kind": "gs_bar",
            "title": (
                f"增值服务已占净收入 {vas_share[latest]:.1f}%，"
                f"十八季前是 {vas_share[0]:.1f}%"
            ),
            "xlabels": labels,
            "xrot": 90,
            "values": net_revenue,
            "legend": "净收入",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "ylab2": "增值服务占比",
            "yoy": {
                "name": "增值服务 / 净收入 (RHS) D",
                "values": rounded(vas_share),
                "color": "GOLD",
                "yfmt": "pct1",
            },
            "note": (
                f"增值服务本季 ${vas[latest]:,}M、同比 {pct_change(vas[latest], vas[latest - 4]):+.1f}%（"
                f"公司口径固定汇率 +{snapshot['currency_neutral_growth_pct']['value_added_services']}%），"
                "而且 10-Q 明确其中收购与处置的贡献是<b>轻微负值</b>，即增速全部是内生的。"
                "这条线之所以关键，是因为增值服务不进返点的分母也不进它的分子："
                "它是公司唯一一块收入不必先经过发卡行分成的业务。"
            ),
            "src_extra": source_filings,
        },
        {
            "ref": "EX_CASH",
            "kind": "lines",
            "title": (
                f"滚动四季经营现金流 / 净利润从 {trailing_conversion[latest - 4]:.0f}% 降到 "
                f"{trailing_conversion[latest]:.0f}%；上半年口径是 "
                f"{ytd_conversion[latest]:.1f}%，上年同期 {ytd_conversion[latest - 4]:.1f}%"
            ),
            "xlabels": labels,
            "xrot": 90,
            "series": [
                {"name": "滚动四季 OCF / 净利润 D", "values": rounded(trailing_conversion), "color": "NAVY"},
                {"name": "年初至今 OCF / 净利润 D", "values": rounded(ytd_conversion), "color": "GRAY"},
            ],
            "fmt": "pct0",
            "yfmt": "pct0",
            "label_fmt": "pct0",
            "end_label": True,
            "ylab": "现金转化率",
            "note": (
                "两条线画的是同一件事的两个窗口。灰线每年第一季重新起跳，"
                "所以它只能与同一季的历史比——本季 "
                f"{ytd_conversion[latest]:.1f}% 对上年同期 {ytd_conversion[latest - 4]:.1f}%。"
                "深蓝线消掉了季节性，方向一样：从四个季度前的 "
                f"{trailing_conversion[latest - 4]:.0f}% 掉到 {trailing_conversion[latest]:.0f}%，"
                "一年抹掉了 "
                f"{trailing_conversion[latest - 4] - trailing_conversion[latest]:.0f}pp。"
                "<b>但它不是窗口里的最低点</b>：2024 年上半年这条线曾低到 "
                f"{min(value for value in trailing_conversion if value is not None):.0f}%，"
                "所以现在的读数是「回到几年前的水平」，不是「破了记录」。"
                "下一张说明缺口去了哪里。"
            ),
            "src_extra": source_note(
                "经营现金流与净利润逐季来自现金流量表（10-Q 只按年初至今披露，"
                "逐季由相邻两个年初至今值相减，第四季为全年 − 前九个月）"),
        },
        {
            "ref": "EX_INCENTIVE_CASH",
            "kind": "grouped_bars",
            "title": (
                f"客户激励的现金净消耗本季 ${incentive_cash_drain[latest]:,.0f}M，"
                f"上半年 ${sum(incentive_cash_drain[-2:]):,.0f}M，是上年同期的 "
                f"{sum(incentive_cash_drain[-2:]) / sum(incentive_cash_drain[-6:-4]):.1f} 倍"
            ),
            "xlabels": labels,
            "xrot": 90,
            "groups": [
                {"name": "预付客户激励等现金流出", "color": "NAVY",
                 "values": q["prepaid_expense_cash_outflow"]},
                {"name": "客户激励摊销（非现金加回）", "color": "GOLD",
                 "values": q["amortization_of_customer_incentives"]},
            ],
            "bar_labels": False,
            "fmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "note": (
                "现金流量表里这两行方向相反：赢单时先付现金（记进预付费用），"
                "之后按合同期摊销回损益。两者的差就是这一季从现金里净拿走的金额。"
                f"摊销本身也在加速——上半年 ${sum(q['amortization_of_customer_incentives'][-2:]):,}M，"
                f"同比 {pct_change(sum(q['amortization_of_customer_incentives'][-2:]), sum(q['amortization_of_customer_incentives'][-6:-4])):+.1f}%，"
                "说明前几年签下的单子正在加速进成本。"
                "<b>口径提醒：</b>「预付费用」这一行不只含客户激励，公司没有逐项拆分；"
                "本页据此只画这行的总额，不把它整条改名为返点。"
            ),
            "src_extra": source_note("两行均为现金流量表原行，逐季由年初至今值相减"),
        },
        {
            "ref": "EX_RETURNS",
            "kind": "grouped_bars",
            "title": (
                f"滚动四季股东回报已达自由现金流的 {trailing_coverage[latest]:.0f}%，"
                f"一年前是 {trailing_coverage[latest - 4]:.0f}%"
            ),
            "xlabels": labels[3:],
            "xrot": 90,
            "groups": [
                {"name": "滚动四季自由现金流 D", "color": "NAVY",
                 "values": rounded(trailing_free_cash[3:])},
                {"name": "滚动四季股东回报（回购 + 分红）", "color": "GOLD",
                 "values": rounded(trailing_returns[3:])},
            ],
            "bar_labels": False,
            "fmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M（滚动四季）",
            "note": (
                "两根柱子交叉的那一刻，回购就不再是「把多余的现金还回去」了。"
                f"差额由资产负债表补：总债务从上季末的 ${total_debt[latest - 1]:,}M 增到 "
                f"${total_debt[latest]:,}M，同期总权益从 ${bs['total_equity'][latest - 1]:,}M 降到 "
                f"${bs['total_equity'][latest]:,}M。"
                "自由现金流按经营现金流减去购置不动产设备与资本化软件计算，与公司现金流量表的三行一致。"
            ),
            "src_extra": source_note("经营现金流、资本开支、回购与分红均来自现金流量表"),
        },
    ]

    # ── 三、下季跟踪 ─────────────────────────────────────────────────────────
    next_charts = [
        headroom_exhibit(
            "下季 5 条量化阈值：被击穿的两条一条在现金转化、一条在管理层自己的买入价",
            next_kpi["quantified"],
            "current",
            (
                "正值 = 仍在安全侧。返点占比离 54% 的红线还有余量，但管理层已经预告下季会环比再升；"
                f"现金转化的年初至今读数 {ytd_conversion[latest]:.1f}% 已经在 85% 之下；"
                f"回购隐含均价 ${repurchase_price[latest]:.0f} 低于 $560，"
                "这一条的方向要反过来读——<b>价格越高越说明管理层认可自己的估值</b>，"
                "所以「越过阈值」在这里表示公司自己在更低的价位才愿意买。"
            ),
            src_extra=(
                "阈值为本地研究设定，不是公司指引；当前值为本季披露值或其自算比率。"
                "另有 4 条需等披露才能判定，见下方核对表。"
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

    # ── 四、长期常规 ─────────────────────────────────────────────────────────
    routine = [
        {
            "kind": "lines",
            "title": (
                f"两条腿的十八季：支付网络净收入 ${network_net[latest]:,}M、"
                f"增值服务 ${vas[latest]:,}M，两者的同比增速差已连续 {gap_run} 季在 8pp 以上"
            ),
            "xlabels": labels,
            "xrot": 90,
            "series": [
                {"name": "支付网络净收入", "values": network_net, "color": "NAVY"},
                {"name": "增值服务与解决方案净收入", "values": vas, "color": "GOLD"},
            ],
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "zero_base": True,
            "end_label": True,
            "ylab": "$M",
            "note": (
                f"支付网络本季同比 {network_yoy[latest]:+.1f}%，增值服务 "
                f"{pct_change(vas[latest], vas[latest - 4]):+.1f}%。"
                "支付网络那条每年第四季都会回落一格——第四季返点最重，"
                "这是这家公司的季节性，不是异常。"
                "两条线从 2022 年第一季起可比：新口径在 2023 年第一季启用，"
                "当期 10-Q 同时重述了 2022 年的四个季度；再往前没有任何文件给出新口径的季度值，本页不外推。"
            ),
            "src_extra": source_filings,
        },
        {
            "kind": "lines",
            "title": (
                f"经营利润率：GAAP {gaap_margin[latest]:.1f}%，"
                f"剔除诉讼计提与重组后 {adjusted_margin[latest]:.1f}% —— "
                f"环比 GAAP 跳了 {gaap_margin[latest] - gaap_margin[latest - 1]:+.1f}pp，"
                f"同口径只有 {adjusted_margin[latest] - adjusted_margin[latest - 1]:+.2f}pp"
            ),
            "xlabels": labels,
            "xrot": 90,
            "series": [
                {"name": "经营利润率（GAAP）", "values": rounded(gaap_margin), "color": "GRAY"},
                {"name": "剔除诉讼计提与重组 D", "values": rounded(adjusted_margin), "color": "NAVY"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "end_label": True,
            "ylab": "经营利润率",
            "note": (
                "上季的特殊项是 $202M 重组、本季是 $82M 诉讼计提，"
                "所以直接比较两季的 GAAP 利润率会把改善放大约五倍。"
                "深蓝那条不是本站自定义的口径：公司在业绩发布里公布的调整后经营利润率，"
                "正好等于把这两项加回经营利润再除以净收入，"
                f"{len(crosscheck['periods'])} 个可对照的季度（{crosscheck['periods'][0]} 起）逐季吻合——"
                "公司只公布到 0.1pp，差异全部在 0.05pp 以内。"
                f"本季 {adjusted_margin[latest]:.2f}% 是这十八季里的最高值。"
            ),
            "src_extra": (
                "经营利润与诉讼计提为利润表原行，重组费用取自 Q1 2026 10-Q 的说明；"
                "公司公布的调整后利润率见核对表，用于验证本页的加回口径。"
            ),
        },
        {
            "kind": "lines",
            "title": (
                f"资本结构：总债务 ${total_debt[latest]:,}M，总权益 ${bs['total_equity'][latest]:,}M，"
                f"倍数 {leverage[latest]:.1f}x 是十八季里的最高值（此前最高 {max(leverage[:-1]):.1f}x）"
            ),
            "xlabels": labels,
            "xrot": 90,
            "series": [
                {"name": "总债务（短期 + 长期）D", "values": total_debt, "color": "NAVY"},
                {"name": "总权益", "values": bs["total_equity"], "color": "GOLD"},
                {"name": "现金及等价物", "values": bs["cash_and_equivalents"], "color": "GRAY"},
            ],
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "zero_base": True,
            "end_label": True,
            "ylab": "$M",
            "note": (
                f"本季净增债务约 ${total_debt[latest] - total_debt[latest - 1]:,}M，"
                f"权益减少 ${bs['total_equity'][latest - 1] - bs['total_equity'][latest]:,}M —— "
                "权益被压低的直接原因是库存股按成本累加，与经营无关；"
                "但两件事同时发生说明这一轮回购的资金来源已经换了。"
                "公司同时预告下季其他收入（费用）会因 6 月发债走高到约 −$125M。"
            ),
            "src_extra": source_note("三条线均为各期资产负债表原行；总债务为两行相加"),
        },
        {
            "kind": "gs_bar",
            "title": (
                f"回购隐含均价 ${repurchase_price[latest]:.0f}：本季买得最多，"
                f"价格却低于此前连续 {price_run} 个季度的每一季"
            ),
            "xlabels": labels,
            "xrot": 90,
            "values": q["stock_repurchases"],
            "legend": "单季回购金额",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "ylab2": "隐含均价",
            "yoy": {
                "name": "回购隐含均价 (RHS) D",
                "values": rounded(repurchase_price),
                "color": "RED",
                "yfmt": "usd0",
            },
            "note": (
                f"均价 = 当季回购现金 ÷ 当季回购股数，两者都是申报数。"
                f"从 {labels[-4]} 的 ${repurchase_price[-4]:.0f} 一路降到本季的 "
                f"${repurchase_price[latest]:.0f}，同期金额从 ${q['stock_repurchases'][-4]:,}M 升到 "
                f"${q['stock_repurchases'][latest]:,}M。"
                "股数按 0.1 百万股披露，相减后的误差让本季均价落在约 "
                f"${q['stock_repurchases'][latest] / (ps['shares_repurchased_m'][latest] + 0.1):.0f}–"
                f"${q['stock_repurchases'][latest] / (ps['shares_repurchased_m'][latest] - 0.1):.0f} 之间，"
                "不影响方向。剩余授权从上季末的 "
                f"${bs['remaining_repurchase_authorization'][latest - 1]:,}M 降到 "
                f"${bs['remaining_repurchase_authorization'][latest]:,}M，本季董事会未新增授权。"
            ),
            "src_extra": (
                "回购现金来自现金流量表，回购股数来自权益附注，剩余授权来自各期资产负债表日的披露；"
                "第四季的股数取自当季 earnings release 的三个月口径。均价为两者相除的自算值。"
            ),
        },
        {
            "kind": "lines",
            "title": (
                f"摊薄股数十八季从 {ps['diluted_shares_m'][0]:,.0f} 百万降到 "
                f"{ps['diluted_shares_m'][latest]:,.0f} 百万，累计缩了 "
                f"{abs(pct_change(ps['diluted_shares_m'][latest], ps['diluted_shares_m'][0])):.1f}%"
            ),
            "xlabels": labels,
            "xrot": 90,
            "series": [
                {"name": "摊薄加权平均股数", "values": ps["diluted_shares_m"], "color": "NAVY"},
            ],
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "end_label": True,
            "ylab": "百万股",
            "note": (
                f"本季摊薄每股收益 ${ps['diluted_eps_usd'][latest]:.2f}、同比 "
                f"{pct_change(ps['diluted_eps_usd'][latest], ps['diluted_eps_usd'][latest - 4]):+.1f}%，"
                f"而净利润同比 {pct_change(q['net_income'][latest], q['net_income'][latest - 4]):+.1f}%；"
                "两者之差就是这条线。股本收缩是真实的股东价值，"
                "但它与净收入增速无关，读每股收益增速时要先把它扣掉。"
                "第四季的股数与每股收益取自当季 earnings release 的三个月列——"
                "按全年减九个月得到的每股收益不是第四季的每股收益。"
            ),
            "src_extra": source_note("摊薄股数与每股收益来自各期利润表与第四季 earnings release"),
        },
        {
            "kind": "lines",
            "title": (
                f"四条计费线：跨境本季 ${pn['cross_border_assessments'][latest]:,}M，"
                f"十八季前只有 ${pn['cross_border_assessments'][0]:,}M"
            ),
            "xlabels": labels,
            "xrot": 90,
            "series": [
                {"name": "交易处理计费", "values": pn["transaction_processing_assessments"], "color": "NAVY"},
                {"name": "跨境计费", "values": pn["cross_border_assessments"], "color": "MBLUE"},
                {"name": "境内计费", "values": pn["domestic_assessments"], "color": "GOLD"},
                {"name": "其他网络计费", "values": pn["other_network_assessments"], "color": "GRAY"},
            ],
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "zero_base": True,
            "end_label": True,
            "ylab": "$M",
            "note": (
                "跨境这条本季超过境内，成为第二大计费线："
                f"${pn['cross_border_assessments'][latest]:,}M vs "
                f"${pn['domestic_assessments'][latest]:,}M。"
                "四条线合计就是上面那些图的分母，它们全部印在 10-Q 里；"
                "唯一不印的是把它们变成净收入的那一步。"
            ),
            "src_extra": source_filings,
        },
    ]

    exhibits = number_exhibits(settled_charts + highlights + next_charts + routine)
    first_table = len(exhibits) + 2

    revenue_rows = []
    for index, period in enumerate(periods):
        revenue_rows.append([
            period,
            f"${pn['domestic_assessments'][index]:,}M",
            f"${pn['cross_border_assessments'][index]:,}M",
            f"${pn['transaction_processing_assessments'][index]:,}M",
            f"${pn['other_network_assessments'][index]:,}M",
            f"${gross[index]:,}M D",
            f"${rebates[index]:,}M D",
            f"{rebate_ratio[index]:.2f}% D",
            f"${network_net[index]:,}M",
            f"${vas[index]:,}M",
            f"${net_revenue[index]:,}M",
        ])

    cash_rows = []
    for index, period in enumerate(periods):
        cash_rows.append([
            period,
            f"${q['operating_cash_flow'][index]:,}M",
            f"${q['net_income'][index]:,}M",
            f"{q['operating_cash_flow'][index] / q['net_income'][index] * 100:.0f}% D",
            f"${q['prepaid_expense_cash_outflow'][index]:,}M",
            f"${q['amortization_of_customer_incentives'][index]:,}M",
            f"${free_cash_flow[index]:,}M D",
            f"${q['stock_repurchases'][index]:,}M",
            f"{ps['shares_repurchased_m'][index]:.1f}M",
            f"${repurchase_price[index]:,.0f} D",
            f"${q['dividends_paid'][index]:,}M",
            f"${total_debt[index]:,}M D",
        ])

    driver_rows = []
    for index, period in enumerate(periods):
        def spread_text(key: str) -> str:
            value = spreads[key][index]
            return "—" if value is None else f"{value:+.0f}pp D"
        driver_rows.append([
            period,
            f"{drivers['gdv'][index]}%",
            f"{drivers['cross_border'][index]}%",
            f"{drivers['switched'][index]}%",
            spread_text("境内计费 vs GDV"),
            spread_text("跨境计费 vs 跨境量"),
            spread_text("清算计费 vs 换手笔数"),
        ])

    margin_rows = []
    for index, period in enumerate(crosscheck["periods"]):
        position = periods.index(period)
        margin_rows.append([
            period,
            f"{gaap_margin[position]:.2f}%",
            f"${q['provision_for_litigation'][position]:,}M",
            f"${q['restructuring_charge'][position]:,}M",
            f"{adjusted_margin[position]:.2f}% D",
            f"{crosscheck['company_published_pct'][index]:.1f}%",
        ])

    guidance_rows = [[item, wording] for item, wording in disclosure["latest_wording"]]

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
            "title": "十八季毛计费、返点与净收入（返点与占比为自算）",
            "headers": ["期间", "境内计费", "跨境计费", "交易处理计费", "其他网络计费",
                        "毛计费合计 D", "返点与激励 D", "返点 / 毛计费 D",
                        "支付网络净收入", "增值服务净收入", "净收入合计"],
            "rows": revenue_rows,
        },
        {
            "n": first_table + 3,
            "title": "十八季现金流、回购与资本结构",
            "headers": ["期间", "经营现金流", "净利润", "OCF / 净利润 D", "预付费用现金流出",
                        "客户激励摊销", "自由现金流 D", "回购金额", "回购股数",
                        "隐含均价 D", "分红", "总债务 D"],
            "rows": cash_rows,
        },
        {
            "n": first_table + 4,
            "title": "关键经营驱动增速与固定汇率价差（第四季无固定汇率季度数）",
            "headers": ["期间", "GDV（本地货币）", "跨境量（本地货币）", "换手笔数",
                        "境内价差 D", "跨境价差 D", "清算价差 D"],
            "rows": driver_rows,
        },
        {
            "n": first_table + 5,
            "title": "调整后经营利润率的口径核对：加回两项即得公司公布值",
            "headers": ["期间", "GAAP 经营利润率", "诉讼计提", "重组费用",
                        "加回后 D", "公司公布的调整后经营利润率"],
            "rows": margin_rows,
        },
        {
            "n": first_table + 6,
            "title": "公司口径的前瞻指引（全部来自电话会，申报文件里没有数字）",
            "headers": ["项目", "管理层措辞"],
            "rows": guidance_rows,
        },
        ai_capex_cycle_table(first_table + 7),
    ]

    return {
        "schema_version": "quarterly-dashboard/ma-v1",
        "page": {"slug": "ma", "language": "zh-CN"},
        "company": {
            "ticker": "MA",
            "name": "Mastercard",
            "group": "payment_networks",
            "accounting_standard": "US GAAP",
        },
        "latest": {
            "disclosed_period_label": "Q2 2026",
            "full_financial_period_label": "Q2 2026",
            "period_end": "2026-06-30",
            "release_date": "2026-07-30",
            "analysis_date": "2026-07-31",
            "audit_status": "unaudited",
            "status": "history_ready",
        },
        "tracker": "Watchlist Quarterly Tracker · MA",
        "title": "Mastercard (MA)：Q2 2026 季报仪表盘",
        "subtitle": (
            "截至 2026-06-30 · 发布 2026-07-30 · US GAAP · 未审计 · "
            "金额单位为 $M，另有注明除外"
        ),
        "headline": (
            f"账单在加速，留下的钱没有：毛计费 ${gross[latest]:,}M、同比 "
            f"{signed(gross_yoy[latest])}，而净支付网络收入只有 {signed(network_yoy[latest])}——"
            f"返点占毛计费 {rebate_ratio[latest]:.2f}%，"
            f"{ratio_up + ratio_down} 个可比季里 {ratio_up} 次同比走高。"
            f"毛计费的年增量从 {labels[YOY_FROM]} 起涨了 "
            f"{pct_change(gross_step[latest], gross_step[YOY_FROM]):.0f}%，"
            f"落到净收入上的部分连续七季卡在 ${min(plateau):,.0f}–${max(plateau):,.0f}M。"
            f"同期上半年经营现金流同比 "
            f"{pct_change(sum(q['operating_cash_flow'][-2:]), sum(q['operating_cash_flow'][-6:-4])):.1f}%"
            f"、净利润 {pct_change(sum(q['net_income'][-2:]), sum(q['net_income'][-6:-4])):+.1f}%，"
            f"缺口由年初以来净增的 ${total_debt[latest] - total_debt[latest - 2]:,}M 债务补进了创纪录的回购。"
            f"财报当日股价 {signed(consensus['post_earnings_price_change_pct'])}。"
        ),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>结构</span><b>返点吃掉了多收的费</b>'
            f'<p>毛计费同比增量 ${gross_step[latest]:,.0f}M，返点腿 −${rebate_step[latest]:,.0f}M，'
            f'净支付网络收入只多了 ${network_step[latest]:,.0f}M。</p></article>'
            '<article><span>亮点</span><b>增值服务撑起过半增量</b>'
            f'<p>${vas[latest]:,}M、占净收入 {vas_share[latest]:.1f}%，'
            f'贡献了净收入同比增量的 {vas_step[latest] / net_step[latest] * 100:.0f}%，'
            '且不承担返点。</p></article>'
            '<article><span>存疑</span><b>现金转化与杠杆同向恶化</b>'
            f'<p>上半年 OCF / 净利润 {ytd_conversion[latest]:.1f}%（上年 '
            f'{ytd_conversion[latest - 4]:.1f}%），滚动四季股东回报已占自由现金流 '
            f'{trailing_coverage[latest]:.0f}%。</p></article>'
            '</div>'
        ),
        "source": source,
        "source_url": "https://investor.mastercard.com/",
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {
                "id": "settled",
                "title": "一、上季跟踪指标兑现了吗",
                "description": "先结算上季留下的问题与阈值，再看本季数据——本季的关键正在于阈值没有覆盖的地方。",
                "exhibits": exhibits[: len(settled_charts)],
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": (
                    "公司不在申报文件里给数字指引，所以这一节承担别的页面由「指引兑现」承担的作用："
                    "记录一条每季必须披露、且可以逐季结算的量——毛计费里有多少被返点拿回去。"
                ),
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
                "description": "MA 专属的常规序列：两条业务腿、利润率的同口径对照、资本结构、回购价格与四条计费线。",
                "exhibits": exhibits[-len(routine):],
            },
        ],
        "tables": tables,
        "notes": [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，"
            "每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "Mastercard 的财年即自然年，本页的季度标注与公司口径一致，无需换算。",
            disclosure["statement"] + disclosure["why_no_record"],
            "返点与激励在现行口径下不是印在表里的一行，而是「四条计费线合计 − 支付网络净收入」这个减法，"
            "两个被减数都是申报数。公司在业绩发布里说本季返点同比 +22%，本页的减法给出 +21.8%，"
            "六个月口径公司说 +22%、减法给出 +22.5%，四舍五入后一致——这是这条序列的外部校验。",
            "逐季记录从 2022Q1 起。「支付网络 / 增值服务」与四条计费线是公司 2023 年第一季度换用的新口径，"
            "当季 10-Q 同时重述了 2022 年的可比季度；更早的季度只有旧口径，"
            "旧口径的分母把增值服务也算在内，两条线不是一条线，本页不拼接。",
            "第四季没有 10-Q，每个第四季都是「全年 − 前九个月」，两端都是申报数；"
            "第四季的摊薄股数与摊薄每股收益取自当季 earnings release 的三个月列，"
            "因为按全年减九个月得到的每股收益不是第四季的每股收益。",
            "公司只在当季 10-Q 里给出该季各条计费线的固定汇率增速，第四季只有全年数，"
            "因此固定汇率价差图有三处缺口，本页留空而不是插值。",
            "回购隐含均价 = 当季回购现金 ÷ 当季回购股数。股数按 0.1 百万股披露，"
            "两个累计值相减后误差可达 ±0.1 百万股，本季对应约 ±$5 的区间。",
            "「剔除诉讼计提与重组」的经营利润率是把两条申报行加回经营利润，"
            "不是本站自定义的非 GAAP 指标：它逐季吻合公司自己公布的调整后经营利润率，核对表列出八个对照季。",
            f"Exhibit 3 与 Exhibit {len(settled_charts) + len(highlights) + 2} 的阈值是本地研究设定，"
            "不是公司指引，也不构成评级或投资建议；「距阈值余量」统一为正值代表安全侧。"
            "其中跨境 travel 的两条只出现在公司季度业绩演示文稿，不进任何申报文件，本站不为其建历史序列。",
            "市场预期一律标注为「市场预期」并给出取数时点，不写卖方机构名，也不发布评级、目标价或估值。"
            f"本季净收入 ${net_revenue[latest]:,}M、公司口径调整后每股收益 "
            f"${snapshot['adjusted_diluted_eps_usd'][0]:.2f}，均高于 {consensus['as_of']} 的市场预期"
            f"（净收入 US${consensus['net_revenue_usd_bn']:.2f}B、调整后每股收益 "
            f"${consensus['adjusted_diluted_eps_usd']:.2f}）。",
            "2026 年起公司把委内瑞拉的跨境活动并入 GDV、跨境量与换手笔数并追溯重述前期，"
            "10-Q 有脚注说明但没有量化其贡献；本页因此不把跨境计费的价差全部读成提价。",
            "本页已知未接入：跨境量里 travel 与电商的月度拆分、增值服务的子线增速、"
            "分地区的 GDV 金额（公司只披露增速）、以及尚未交割的收购对收入与费用的单位经济。",
        ],
        "footer": (
            "MA quarterly results · 数据来自 Mastercard 公开披露与透明自算 · "
            "仅供研究，不构成投资建议"
        ),
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "ma.js"), payload, "ma")
    shell_dir = ROOT / "ma"
    shell_dir.mkdir(exist_ok=True)
    # Rendered here, not at import: the shell stamps the payload's content
    # hash into its <script src>, so it has to be built after write_dash.
    (shell_dir / "index.html").write_text(
        render_shell("MA", "ma"), encoding="utf-8")
    exhibits = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"MA page: {exhibits} charts in 4 sections + {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
