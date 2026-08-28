#!/usr/bin/env python3
"""Build the CDNS quarterly-results page.

Same four-part, chart-led shape as the other company pages (上季兑现 → 本季重点
→ 下季跟踪 → 长期常规).  Cadence's fiscal quarters have ended on the calendar
quarter since 2023 and within a few days of it before that, so every label on
this page is already a calendar quarter and needs no restatement.

What makes this page different from its neighbours is the length of the guided
record.  Cadence files a CFO Commentary as EX-99.02 of every quarterly earnings
8-K, and that document states the next quarter's revenue, GAAP and non-GAAP
operating margin and GAAP and non-GAAP EPS.  Forty-three consecutive quarters of
it are on file, which turns "did the quarter clear the company's own bar" from
an anecdote into a distribution -- and the distribution is the most one-sided on
this site: in 42 finished quarters the reported revenue has never once landed
below the guided floor.

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
    delivery_band,
    headroom,
    headroom_exhibit,
    midpoint_deviation,
    number_exhibits,
    threshold_exhibit,
    threshold_table,
    unit_text,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "cdns.json"
DATA_DIR = ROOT / "data"

WINDOW = 8
# Forty-three quarterly labels at ninety degrees is already a dense axis; one
# tick per year is the only way the long routine charts stay navigable.
LONG_STEP = 4


def compact_period(period: str) -> str:
    """``'Q2 2026'`` → ``'Q2'26'``."""
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


def quarter_label(quarter: str) -> str:
    """``'2018Q1'`` → ``'Q1'18'``, matching `compact_period`'s output."""
    year, number = quarter.split("Q")
    return f"Q{number}'{year[-2:]}"


def shown(values: list) -> list:
    return values[-WINDOW:]


def yoy(values: list[float | None]) -> list[float | None]:
    out: list[float | None] = [None] * 4
    for index in range(4, len(values)):
        current, base = values[index], values[index - 4]
        out.append(None if current is None or not base else (current / base - 1) * 100)
    return out


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def leading_gap(values: list[float | None]) -> int:
    """Index of the first reported value; ``len(values)`` when there is none."""
    return next((i for i, value in enumerate(values) if value is not None), len(values))


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


BACKLOG_PRECISION = (
    "backlog 只披露到 US$0.1B，所以水平值可判、而两季相减得到的净增不可判——"
    "上季设的 book-to-bill 阈值因此本季退役，理由见核对表。"
)

SEASONALITY_CAVEAT = (
    "<b>这条阈值有季节性，请连着历史一起读</b>：backlog 每年上半年都被消耗，"
    "该倍数因此在第二、三季走低、第四季回补，图上过去两年的第三季都低于 1.35x。"
    "把它设成下季硬阈值意味着一次正常的季节性回落也会触发，"
    "本页保留该设定并把历史画出来，而不是悄悄换一个更容易过的数。"
)

SOURCE_8K = (
    "指引区间来自各季业绩 8-K 的 EX-99.02 CFO Commentary 里「Q&lt;n&gt; &lt;year&gt; Outlook」段落；"
    "实际收入来自各期 10-Q / 10-K，实际非 GAAP 营业利润率与非 GAAP EPS 来自其后各期 "
    "CFO Commentary 的五季对照表。"
)

GUIDED_WHEN = "该季<b>刚开始不久时</b>"

# Cadence publishes each quarter's outlook alongside the *previous* quarter's
# results, and that release lands inside the quarter being guided -- about four
# weeks in for Q2/Q3/Q4, and past the halfway point for Q1, whose guidance waits
# for the mid-February annual release.  Every page module that draws this record
# has to say so, because "did it clear its own bar" means something weaker when
# a third to a half of the quarter is already in the books.
TIMING_CAVEAT = (
    "<b>口径提示：这不是事前预测。</b>Cadence 与上一季财报同时给出本季指引，"
    "发布日已经落在被指引季度<b>之内</b>——第二、三、四季通常已过约 4 周，"
    "第一季因四季报在 2 月中下旬发布，往往已过半个季度（例：2021Q1 的指引发布于 2021-02-22，"
    "该季 91 天已过 50 天）。核对表里的「指引发布日」一列可逐季复核。"
)


def guidance_delivery_charts(staging: dict) -> list[dict]:
    """The full guided record for the three metrics Cadence files a range for.

    Cadence guides revenue, non-GAAP operating margin and non-GAAP EPS every
    quarter in the same filed document, so each gets the same pair -- the range
    against the reported result, then the distance from the guided midpoint --
    grouped so one metric is read through before the next begins.

    The three answers are not the same answer.  Revenue and EPS have never once
    landed under the floor in 42 quarters; the margin has, twice, and both times
    against a guidance that was a single number rather than a range.
    """
    record = staging["quarterly_guidance_history"]
    quarters = record["quarters"]
    labels = [quarter_label(quarter) for quarter in quarters]

    revenue_lo = record["revenue_guide_low_usd_m"]
    revenue_hi = record["revenue_guide_high_usd_m"]
    revenue_actual = record["revenue_actual_usd_m"]
    margin_lo = record["non_gaap_operating_margin_guide_low_pct"]
    margin_hi = record["non_gaap_operating_margin_guide_high_pct"]
    margin_actual = record["non_gaap_operating_margin_actual_pct"]
    margin_form = record["non_gaap_operating_margin_guide_form"]
    eps_lo = record["non_gaap_eps_guide_low"]
    eps_hi = record["non_gaap_eps_guide_high"]
    eps_actual = record["non_gaap_eps_actual"]

    finished = [index for index, value in enumerate(revenue_actual) if value is not None]
    point_quarters = sum(1 for form in margin_form if form == "point")
    # ASC 606 replaced ASC 605 for the quarter beginning 2018-01-01 and Cadence
    # did not restate the earlier years, so the level charts carry a break there.
    break_at = quarters.index("2018Q1")

    # A ±$15M band on a $450M quarter and the same band on a $1,600M quarter are
    # the same *proportion* and a very different number of pixels, so the band
    # chart draws the recent window and the deviation chart carries all 43.
    band_window = slice(len(quarters) - 20, len(quarters))
    band_labels = labels[band_window]

    revenue_band = delivery_band(
        "EX_REV_RANGE", "收入", band_labels, revenue_lo[band_window], revenue_hi[band_window],
        revenue_actual[band_window],
        fmt="f0c", ylab="$M", unit="$M", venue="财报的 CFO Commentary", timing=GUIDED_WHEN,
        scope="（本图仅近 20 季）",
        src_extra=SOURCE_8K + TIMING_CAVEAT,
        extra_note=(
            "<b>这张只画最近 20 季，不是数据缺失</b>：本页的指引记录一路回到 2016Q1，"
            "而收入在这段时间从 US$0.45B 长到 US$1.58B，早年的指引区间只有 ±$5M，"
            "放在同一根线性美元轴上会被压成一两个像素。"
            "完整 43 季的同一问题改用与量级无关的口径回答，见 Exhibit {EX_REV_DEV}。"
        ),
        break_at=max(0, break_at - band_window.start) if break_at >= band_window.start else None,
        break_label="ASC 606",
    )
    revenue_dev = midpoint_deviation(
        "EX_REV_DEV", "收入", quarters, revenue_lo, revenue_hi, revenue_actual,
        mode="pct", window=len(finished), label=quarter_label, bar_labels=False,
        src_extra=SOURCE_8K + "偏离为实际收入除以指引中值的自算值。" + TIMING_CAVEAT,
        extra_note=(
            f"<b>这是全页最该先读的一张</b>：{len(finished)} 个已完结季里，实际收入"
            "<b>一次都没有跌破过指引下限，也一次都没有低于指引中值</b>——"
            "不是很少，是零次，跨越十年半、两任产品周期、一次会计准则切换和一次出口管制冲击。"
            "柱高在这里可比，因为口径是百分比，不受收入量级三倍变化的影响。"
            "2018Q1 起收入确认改用 ASC 606：每一对「指引 vs 实际」都落在同一套准则内，"
            "所以偏离序列不受影响，只有上一张的水平值跨 2018Q1 不可直接连读。"
        ),
    )
    margin_band = delivery_band(
        "EX_MARGIN_RANGE", "非 GAAP 营业利润率", band_labels,
        margin_lo[band_window], margin_hi[band_window], margin_actual[band_window],
        fmt="pct1", ylab="非 GAAP 营业利润率", unit="%", venue="财报的 CFO Commentary", timing=GUIDED_WHEN,
        scope="（本图仅近 20 季）",
        src_extra=SOURCE_8K + (
            "公司在部分季度给的是单点数（原文写作 ~30% 或 approximately 30%）而不是区间，"
            "那些季的色块没有宽度；写作「29% to 30%」的季度是区间，不是单点。"
        ) + TIMING_CAVEAT,
        extra_note=(
            f"整段 43 季记录里有 {point_quarters} 季公司给的是<b>一个点</b>而不是区间"
            "（新闻稿原文写作 ~30% 这种形式），那些季在图上没有宽度可言——"
            "这不是渲染问题，是指引本身没有宽度。"
            "同样只画最近 20 季，完整记录见 Exhibit {EX_MARGIN_DEV}。"
        ),
        break_at=max(0, break_at - band_window.start) if break_at >= band_window.start else None,
        break_label="ASC 606",
    )
    margin_dev = midpoint_deviation(
        "EX_MARGIN_DEV", "非 GAAP 营业利润率", quarters, margin_lo, margin_hi, margin_actual,
        mode="pp", window=len(finished), label=quarter_label, bar_labels=False,
        src_extra=SOURCE_8K + "偏离为实际利润率减指引中值的算术差。" + TIMING_CAVEAT,
        extra_note=(
            "唯二两次为负的季度都发生在<b>单点指引</b>上，而且差距分别只有 0.3pp 与 0.1pp——"
            "在一个没有宽度的指引面前，这两次与其说是「跌破」，不如说是四舍五入。"
        ),
    )
    eps_band = delivery_band(
        "EX_EPS_RANGE", "非 GAAP EPS", band_labels, eps_lo[band_window], eps_hi[band_window],
        eps_actual[band_window],
        fmt="usd2", ylab="US$/股", unit="US$", venue="财报的 CFO Commentary", timing=GUIDED_WHEN,
        scope="（本图仅近 20 季）",
        src_extra=SOURCE_8K + TIMING_CAVEAT,
        extra_note=(
            "EPS 的指引区间始终是双边的，43 季无一例外，宽度长期维持在 ±$0.02–0.03。"
            "完整记录见 Exhibit {EX_EPS_DEV}。"
        ),
        break_at=max(0, break_at - band_window.start) if break_at >= band_window.start else None,
        break_label="ASC 606",
    )
    eps_dev = midpoint_deviation(
        "EX_EPS_DEV", "非 GAAP EPS", quarters, eps_lo, eps_hi, eps_actual,
        mode="pct", window=len(finished), label=quarter_label, bar_labels=False,
        src_extra=SOURCE_8K + "偏离为实际非 GAAP EPS 除以指引中值的自算值。" + TIMING_CAVEAT,
        extra_note=(
            "与收入同样从未跌破下限，但幅度的走向相反：2018–2022 年常见 +5% 以上，"
            "近八季收敛到 +1% 上下。<b>指引仍是底线，只是留出的余量在变薄</b>，"
            "这与本季收入端「基本符合、EPS 小超」的读数是同一件事的两个切面。"
        ),
    )
    return [revenue_band, revenue_dev, margin_band, margin_dev, eps_band, eps_dev]


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    labels = [compact_period(period) for period in shown(periods)]
    q = staging["quarterly_usd_m"]
    qp = staging["quarterly_pct"]
    qo = staging["quarterly_other"]
    fy = staging["fiscal_year"]
    kpi = staging["operating_kpi"]
    guidance = staging["guidance"]
    consensus = staging["market_expectation"]
    closure = staging["followup_closure"]
    prior_kpi = staging["prior_kpi_settlement"]
    next_kpi = staging["next_kpi"]
    balance = staging["balance_sheet_usd_m"]
    bridge = staging["h1_cash_bridge_usd_m"]

    revenue = q["revenue_total"]
    revenue_shown = shown(revenue)
    revenue_yoy = shown(yoy(revenue))
    services = shown(q["revenue_services"])

    non_gaap_margin = shown(qp["non_gaap_operating_margin"])
    gaap_margin = shown(qp["gaap_operating_margin"])
    gaap_gross = shown(qp["gaap_gross_margin"])
    non_gaap_gross = shown(qp["non_gaap_gross_margin"])
    amortisation_drag = [
        gross_non_gaap - gross_gaap
        for gross_non_gaap, gross_gaap in zip(non_gaap_gross, gaap_gross)
    ]

    operating_cash_flow = shown(q["operating_cash_flow"])
    capex = shown(q["capital_expenditures"])
    free_cash_flow = [flow - spend for flow, spend in zip(operating_cash_flow, capex)]
    buybacks = shown(q["stock_repurchases"])
    buyback_shares = shown(qo["buyback_shares_m"])
    diluted_shares = shown(qo["diluted_shares_m"])
    research = shown(q["research_and_development"])
    research_yoy = shown(yoy(q["research_and_development"]))
    marketing_yoy = shown(yoy(q["marketing_and_sales"]))
    admin_yoy = shown(yoy(q["general_and_administrative"]))
    sbc = shown(q["stock_based_compensation"])
    sbc_ratio = [value / total * 100 for value, total in zip(sbc, revenue_shown)]

    backlog = shown(qo["backlog_usd_bn"])
    # Coverage, not level: the backlog is a record in dollars and shrinking in
    # months, and only the ratio shows the second thing.
    # Computed over all twelve quarters held, so the eight drawn ones can be
    # compared against the same quarter a year and two years earlier -- the
    # multiple is drawn down every first half and a sequential read misleads.
    coverage_all = [
        None if index < 3 or qo["backlog_usd_bn"][index] is None
        else qo["backlog_usd_bn"][index] * 1000 / sum(revenue[index - 3: index + 1])
        for index in range(len(revenue))
    ]
    coverage = coverage_all[-WINDOW:]
    # Book-to-bill: one quarter's revenue plus the quarter's change in backlog,
    # over that revenue.  Both legs are disclosed; the backlog is only published
    # to US$0.1B, which is why the number is quoted to two decimals and no more.
    book_to_bill = []
    for index, level in enumerate(backlog):
        previous = qo["backlog_usd_bn"][len(revenue) - WINDOW + index - 1]
        if level is None or previous is None:
            book_to_bill.append(None)
            continue
        net_add = (level - previous) * 1000
        book_to_bill.append((revenue_shown[index] + net_add) / revenue_shown[index])

    # ── product category and geography are published as integer percentages ──
    # of total revenue and nothing else, so every dollar figure below is that
    # percentage times the reported total, and carries the rounding with it.
    def mix_series(key: str, window: int) -> tuple[list[str], list[float | None]]:
        share = qp[key]
        start = leading_gap(share)
        picked = list(range(max(start, len(share) - window), len(share)))
        return (
            [compact_period(periods[index]) for index in picked],
            [share[index] / 100 * revenue[index] for index in picked],
        )

    category_labels, core_eda = mix_series("category_core_eda", WINDOW + 2)
    _, semiconductor_ip = mix_series("category_semiconductor_ip", WINDOW + 2)
    _, system_design = mix_series("category_system_design_analysis", WINDOW + 2)
    def mix_yoy(key: str) -> float:
        return pct_change(qp[key][-1] / 100 * revenue[-1], qp[key][-5] / 100 * revenue[-5])

    ip_yoy = mix_yoy("category_semiconductor_ip")
    core_eda_yoy = mix_yoy("category_core_eda")
    system_design_yoy = mix_yoy("category_system_design_analysis")
    company_growth = kpi["category_growth_company_pct"]

    # The quarter's own guided range, read from the record rather than retyped.
    record_index = staging["quarterly_guidance_history"]["quarters"].index("2026Q2")
    quarter_guide_low = staging["quarterly_guidance_history"]["revenue_guide_low_usd_m"][record_index]
    quarter_guide_high = staging["quarterly_guidance_history"]["revenue_guide_high_usd_m"][record_index]
    quarter_guide_mid = (quarter_guide_low + quarter_guide_high) / 2

    long = staging["long_history"]
    long_labels = [quarter_label(quarter) for quarter in long["quarters"]]
    long_revenue = long["revenue_usd_m"]
    long_revenue_yoy = yoy(long_revenue)
    long_research = long["research_and_development_usd_m"]
    long_research_ratio = [
        None if value is None else value / total * 100
        for value, total in zip(long_research, long_revenue)
    ]
    long_opex_ratio = [
        (rnd + sell + admin) / total * 100
        for rnd, sell, admin, total in zip(
            long_research, long["marketing_and_sales_usd_m"],
            long["general_and_administrative_usd_m"], long_revenue)
    ]
    reported_yoy = [(index, value) for index, value in enumerate(long_revenue_yoy) if value is not None]
    max_index, max_yoy = max(reported_yoy, key=lambda pair: pair[1])
    min_index, min_yoy = min(reported_yoy, key=lambda pair: pair[1])
    peak_quarter = quarter_label(long["quarters"][max_index])
    negative_quarter = quarter_label(long["quarters"][min_index])
    trough_index, min_recent_yoy = min(
        [pair for pair in reported_yoy if pair[0] > max_index], key=lambda pair: pair[1])
    trough_quarter = quarter_label(long["quarters"][trough_index])
    # China is disclosed in dollars in the segment note, so the line is filed
    # rather than derived; the integer share reaches further back but is only
    # ever used as a share.
    china_from = leading_gap(q["china_revenue"])
    china_labels = [compact_period(period) for period in periods[china_from:]]
    china_revenue = q["china_revenue"][china_from:]
    china_share_exact = [
        None if value is None else value / total * 100
        for value, total in zip(china_revenue, revenue[china_from:])
    ]
    china_yoy = yoy(q["china_revenue"])[china_from:]
    long_china_share = long["china_share_pct"]

    # ── the arithmetic the quarter turns on ─────────────────────────────────
    # The full-year non-GAAP operating income at the guidance midpoint, less
    # what the first half actually earned, less what the third quarter is guided
    # to earn, is the fourth quarter the company has implicitly guided to. Every
    # input is a filed number; nothing here is an estimate.
    fy_operating_income = guidance["fy2026_current"]["non_gaap_operating_income_midpoint_usd_m"]
    fy_revenue_mid = sum(guidance["fy2026_current"]["revenue_usd_m"]) / 2
    h1_revenue = guidance["h1_2026_actual"]["revenue_usd_m"]
    h1_operating_income = guidance["h1_2026_actual"]["non_gaap_operating_income_usd_m"]
    h1_margin = h1_operating_income / h1_revenue * 100
    h2_revenue = fy_revenue_mid - h1_revenue
    h2_operating_income = fy_operating_income - h1_operating_income
    h2_margin = h2_operating_income / h2_revenue * 100
    q3_revenue_mid = sum(guidance["q3_2026"]["revenue_usd_m"]) / 2
    q3_margin_mid = sum(guidance["q3_2026"]["non_gaap_operating_margin_pct"]) / 2
    q3_operating_income = q3_revenue_mid * q3_margin_mid / 100
    q4_revenue = h2_revenue - q3_revenue_mid
    q4_operating_income = h2_operating_income - q3_operating_income
    q4_margin = q4_operating_income / q4_revenue * 100
    # What the second half gives up against simply holding the first half's rate.
    h2_giveback = h2_revenue * h1_margin / 100 - h2_operating_income

    raise_revenue = (sum(guidance["fy2026_current"]["revenue_usd_m"]) / 2
                     - sum(guidance["fy2026_previous"]["revenue_usd_m"]) / 2)
    raise_operating_income = (fy_operating_income
                              - guidance["fy2026_previous"]["non_gaap_operating_income_midpoint_usd_m"])
    incremental_margin = raise_operating_income / raise_revenue * 100
    # The company prints its non-GAAP operating income to the million, so the
    # same ratio taken from the guidance midpoints themselves is a shade lower;
    # both are published rather than silently picking the flattering one.
    exact_raise = (sum(guidance["fy2026_current"]["revenue_usd_m"]) / 2
                   * sum(guidance["fy2026_current"]["non_gaap_operating_margin_pct"]) / 2 / 100
                   - sum(guidance["fy2026_previous"]["revenue_usd_m"]) / 2
                   * sum(guidance["fy2026_previous"]["non_gaap_operating_margin_pct"]) / 2 / 100)
    incremental_margin_exact = exact_raise / raise_revenue * 100

    guidance_revenue_yoy = pct_change(q3_revenue_mid, revenue[-3])

    source = (
        'Source: <a href="https://www.cadence.com/en_US/home/company/investor-relations.html" '
        'rel="noopener">Cadence Investor Relations</a>（Q2 2026 业绩 8-K 的新闻稿与 CFO Commentary；'
        '历史季度经 SEC EDGAR 的 10-Q / 10-K 与历次 8-K 回源）。'
    )

    def source_note(detail: str) -> str:
        return f"{detail}；历史期同口径。自算项目均可在核对表中复核。"

    MIX_PROVENANCE = (
        "公司只披露产品线与地域的<b>收入占比整数百分位</b>，不披露分部金额，"
        "因此本图金额均为占比 × 当季总收入的自算值，含 ±$8M 量级的四舍五入误差；"
        "公司自己给的同比口径（Core EDA +18%、IP「超过 40%」、SD&A +37%）与占比法互有出入，"
        "两者都列在核对表里。"
    )

    # ── section one: settle what was set last quarter ───────────────────────
    tracked = {
        "季末 backlog": (backlog, "usd1", "US$B", "季末 backlog"),
        "单季经营现金流": (operating_cash_flow, "f0c", "$M", "单季经营现金流"),
        "单季回购金额": (buybacks, "f0c", "$M", "单季回购金额"),
        "中国收入占比": (shown(qp["geo_china"]), "pct0", "占总收入", "中国收入占比"),
        "backlog / 过去四季收入": (coverage, "f2", "倍", "覆盖倍数 D"),
        "单季非 GAAP 营业利润率": (non_gaap_margin, "pct1", "非 GAAP 营业利润率", "非 GAAP 营业利润率"),
    }

    def tracking_charts(entries, value_key, threshold_label, headline, only=None) -> list[dict]:
        charts = []
        for entry in entries:
            metric = entry["metric"]
            if metric not in tracked or (only is not None and metric not in only):
                continue
            values, fmt, ylab, actual_name = tracked[metric]
            side = "上方" if entry["direction"] == "up" else "下方"
            charts.append(threshold_exhibit(
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
                ),
                src_extra=(
                    "实际值来自各季 CFO Commentary 与各期 10-Q / 10-K；"
                    "阈值为本地研究设定，不是公司指引。"
                    + (BACKLOG_PRECISION if metric == "季末 backlog" else "")
                    + (SEASONALITY_CAVEAT if metric == "backlog / 过去四季收入" else "")
                ),
            ))
        return charts

    prior_breached = [
        entry for entry in prior_kpi["quantified"]
        if headroom(entry["direction"], entry["threshold"], entry["actual"]) < 0
    ]
    next_breached = [
        entry for entry in next_kpi["quantified"]
        if headroom(entry["direction"], entry["threshold"], entry["current"]) < 0
    ]

    settled_charts = [
        {
            "kind": "bars_labeled",
            "title": "上季 11 条待验证问题：5 条已验证、2 条部分验证、3 条仍未披露、1 条判断错误",
            "xlabels": closure["labels"],
            "values": closure["counts"],
            "legend": "问题条数",
            "fmt": "f0",
            "yfmt": "f0",
            "label_fmt": "f0",
            "ylab": "条",
            "note": closure["falsified_item"] + "。",
            "src_extra": (
                "问题清单来自上季本地分析稿的 follow-up；验证结果依据本季新闻稿、"
                "CFO Commentary 与电话会。"
            ),
        },
        headroom_exhibit(
            (
                f"上季 {len(prior_kpi['quantified'])} 条量化阈值："
                f"{len(prior_kpi['quantified']) - len(prior_breached)} 条守住、"
                f"{len(prior_breached)} 条被击穿，被击穿的全在订单与资本分配上"
            ),
            prior_kpi["quantified"],
            "actual",
            (
                f"正值 = 仍在安全侧。经营与现金面超额兑现——经营现金流 "
                f"${operating_cash_flow[-1]:,.0f}M 是 $400M 阈值的 "
                f"{operating_cash_flow[-1] / 400:.1f} 倍，中国占比与全年 EPS 指引也都在安全侧。"
                "越线的两条是 backlog 没有摸到 $8.2B、回购没有回到 $250M/季——"
                "都不是经营质量问题，但都是上季据以看多的直接依据。"
                "第六条上季阈值（单季 book-to-bill ≥ 1.10x）本季<b>无法结算</b>而非被击穿："
                "它的分子是两季 backlog 之差，而 backlog 只披露到 US$0.1B，"
                "算出来的区间 1.00x–1.13x 恰好横跨阈值。该指标已退役，理由见核对表。"
            ),
            src_extra=(
                "阈值为上季本地研究设定，不是公司指引；实际值为本季披露值或据其自算。"
                "另有三条上季指标已退役或转为披露受限，理由列在核对表下方。"
            ),
        ),
    ]
    settled_charts += tracking_charts(
        prior_kpi["quantified"],
        "actual",
        "上季阈值",
        lambda entry: (
            f"{entry['metric']}："
            f"{'守住' if headroom(entry['direction'], entry['threshold'], entry['actual']) >= 0 else '已击穿'}"
            f"上季阈值 {unit_text(entry['unit'], entry['threshold'])}"
        ),
        only={"季末 backlog", "单季经营现金流", "单季回购金额"},
    )
    settled_charts += guidance_delivery_charts(staging)

    # ── section two: what actually moved ────────────────────────────────────
    highlights = [
        {
            "kind": "gs_bar",
            "title": (
                f"收入 ${revenue_shown[-1]:,.0f}M、同比 {revenue_yoy[-1]:.1f}%，"
                f"但落在指引区间之内而不是之上"
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
                f"本季指引区间 ${quarter_guide_low:,.0f}–{quarter_guide_high:,.0f}M，"
                f"实际 ${revenue_shown[-1]:,.0f}M，仅高出中值 "
                f"{pct_change(revenue_shown[-1], quarter_guide_mid):+.1f}%；"
                f"下季指引中值 ${q3_revenue_mid:,.0f}M 隐含同比 {signed(guidance_revenue_yoy)}、"
                f"环比仅 {signed(pct_change(q3_revenue_mid, revenue_shown[-1]))}。"
                f"服务收入同比 {signed(pct_change(services[-1], shown(q['revenue_services'])[-5]))}，"
                "主要来自并表而非主业结构变化。"
            ),
            "src_extra": source_note(
                "收入来自各期 10-Q / 10-K 与本季新闻稿损益表；同比与环比为自算"),
        },
        {
            "kind": "lines",
            "title": (
                "三条产品线的分化：公司口径 Semiconductor IP「超过 40%」、"
                f"Core EDA +{company_growth['core_eda_yoy']:.0f}%、"
                f"SD&A +{company_growth['system_design_analysis_yoy']:.0f}%"
            ),
            "xlabels": category_labels,
            "series": [
                {"name": "Core EDA D", "values": core_eda, "color": "NAVY"},
                {"name": "System Design & Analysis D", "values": system_design, "color": "MBLUE"},
                {"name": "Semiconductor IP D", "values": semiconductor_ip, "color": "GOLD"},
            ],
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "zero_base": True,
            "end_label": True,
            "ylab": "$M",
            "note": (
                f"按整数占比反推，同期 IP {ip_yoy:+.0f}%、Core EDA {core_eda_yoy:+.0f}%、"
                f"SD&A {system_design_yoy:+.0f}%——与公司口径的差在 SD&A 上最大（5pp），"
                "因此本页两套数都列，不在两者间取舍。"
                "IP 是本季最快的一条，也是最该打折的一条：CFO 在电话会上主动设限"
                "「IP revenue can be timing dependent from quarter-to-quarter... "
                "I wouldn't annualize any one quarter」，而 Intel 协议正是在本季签署。"
                "SD&A 的表观增速里超过三分之二来自 Hexagon D&E 并表，不是经营。"
            ),
            "src_extra": MIX_PROVENANCE,
        },
        {
            "kind": "gs_bar",
            "title": (
                f"中国收入 ${china_revenue[-1]:,.0f}M、同比 {china_yoy[-1]:+.1f}%——"
                f"仍低于 2025Q3 的 ${max(v for v in china_revenue if v is not None):,.0f}M"
            ),
            "xlabels": china_labels,
            "values": china_revenue,
            "legend": "中国收入（申报值）",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "ylab2": "占总收入",
            "yoy": {
                "name": "占总收入 (RHS) D",
                "values": china_share_exact,
                "color": "RED",
                "yfmt": "pct1",
            },
            "note": (
                f"<b>翻倍几乎全部是基数</b>：去年同期正处在出口管制与调查期的低谷"
                f"（${china_revenue[-5]:,.0f}M），而本季的绝对额仍低于 2025Q3。"
                "中国不是在突破，是在高位震荡。麻烦在下一季——2025Q3 是全序列最硬的基数，"
                "而管理层本季<b>没有重申</b>上季给出的「全年约 13%」口径，"
                "15 个分析师问题里中国出现 0 次。全年指引本身则明确建立在「出口管制维持现状」的假设上。"
            ),
            "src_extra": staging["china_provenance"],
        },
        {
            "kind": "lines",
            "title": (
                f"GAAP 毛利率降到 {gaap_gross[-1]:.1f}%，非 GAAP 毛利率反而升到 {non_gaap_gross[-1]:.1f}%"
            ),
            "xlabels": labels,
            "series": [
                {"name": "非 GAAP 毛利率", "values": non_gaap_gross, "color": "NAVY"},
                {"name": "GAAP 毛利率", "values": gaap_gross, "color": "MBLUE"},
                {"name": "两者之差（主要是无形资产摊销）D", "values": amortisation_drag, "color": "RED"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "end_label": True,
            "ylab": "毛利率",
            "note": (
                f"两条线的缺口从 {amortisation_drag[-5]:.1f}pp 张到 {amortisation_drag[-1]:.1f}pp，"
                "全部来自 Hexagon D&E 带来的无形资产摊销。"
                f"<b>只看 GAAP 会得出「产品结构恶化」的结论，而底层毛利率同比是 "
                f"{non_gaap_gross[-1] - non_gaap_gross[-5]:+.1f}pp</b>——"
                "在硬件（低毛利）创纪录、并购资产（低毛利）刚并表的一季里仍在扩张。"
            ),
            "src_extra": (
                "GAAP 与非 GAAP 毛利率均为公司在各季 CFO Commentary 披露值；"
                "两者之差为自算，其构成以无形资产摊销为主，另含少量股权激励与并购整合费用。"
            ),
        },
        {
            "kind": "lines",
            "title": (
                f"本季非 GAAP 营业利润率 {non_gaap_margin[-1]:.1f}%，"
                f"而全年指引隐含的 Q4 只有 {q4_margin:.2f}%"
            ),
            "xlabels": labels + ["Q3'26E", "Q4'26E"],
            "series": [
                {
                    "name": "非 GAAP 营业利润率",
                    "values": non_gaap_margin + [None, None],
                    "color": "NAVY",
                },
                {
                    "name": "下季指引中值 / 全年指引隐含 D",
                    "values": [None] * (WINDOW - 1) + [non_gaap_margin[-1], q3_margin_mid, q4_margin],
                    "color": "GOLD",
                },
                {
                    "name": "GAAP 营业利润率",
                    "values": gaap_margin + [None, None],
                    "color": "GRAY",
                },
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "end_label": True,
            "ylab": "营业利润率",
            "note": (
                f"算式全部是申报值：全年非 GAAP 营业利润中值 ${fy_operating_income:,.0f}M "
                f"− 上半年实际 ${h1_operating_income:,.0f}M = 下半年 ${h2_operating_income:,.0f}M（{h2_margin:.2f}%），"
                f"再减去 Q3 指引中值隐含的 ${q3_operating_income:,.0f}M，剩下的 Q4 就是 {q4_margin:.2f}%。"
                f"<b>这个数与 2025Q2 持平</b>——而那一季正是承受 $128.5M 或有负债、中国占比跌到 9% 的受损季。"
                f"若下半年只是维持上半年的 {h1_margin:.2f}%，将多出 ${h2_giveback:,.0f}M 经营利润；"
                "管理层把这笔让步称作「targeted investments」，但没有给出任何金额。"
            ),
            "src_extra": (
                "实际值为公司披露的季度非 GAAP 营业利润率；Q3'26E 为公司指引区间中值，"
                "Q4'26E 为全年指引中值扣除上半年实际与 Q3 指引后的隐含值（自算 D，无估计成分）。"
                "口径提示：这条线与 Exhibit {EX_MARGIN_DEV} 的偏离序列同源，"
                "该序列显示公司在 42 个已完结季里有 37 季高于自己的指引上限。"
            ),
        },
        {
            "kind": "grouped_bars",
            "title": (
                f"经营现金流 ${operating_cash_flow[-1]:,.0f}M、同比 "
                f"{signed(pct_change(operating_cash_flow[-1], operating_cash_flow[-5]))}，"
                "上季的现金流质疑被彻底证伪"
            ),
            "xlabels": labels,
            "groups": [
                {"name": "经营现金流", "values": operating_cash_flow, "color": "NAVY"},
                {"name": "自由现金流 D", "values": free_cash_flow, "color": "BLUE"},
                {"name": "资本开支", "values": capex, "color": "GRAY"},
            ],
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "bar_labels": False,
            "ylab": "$M",
            "note": (
                f"上半年经营现金流 ${bridge['values'][1]:,.1f}M，全年指引由 $1,875–1,975M 上修到约 "
                f"${guidance['fy2026_current']['operating_cash_flow_usd_m']:,.0f}M。"
                f"资本开支同比 {signed(pct_change(capex[-1], capex[-5]))}，"
                f"全年口径约 ${guidance['fy2026_current']['capital_expenditures_usd_m']:,.0f}M，"
                f"较 2025 年的 ${guidance['fy2025_actual']['capital_expenditures_usd_m']:,.0f}M 增 "
                f"{pct_change(guidance['fy2026_current']['capital_expenditures_usd_m'], guidance['fy2025_actual']['capital_expenditures_usd_m']):.0f}%——"
                "自研硬件与数据中心，对一家资产轻的软件公司来说是新出现的一条腿。"
            ),
            "src_extra": source_note(
                "经营现金流与资本开支逐季来自各期现金流量表（10-Q 只按年初至今披露，"
                "逐季由相邻两个年初至今值相减，财政第四季为全年 − 前三季）；自由现金流为两者之差"),
        },
        {
            "kind": "gs_bar",
            "title": (
                f"backlog 创纪录的 US${backlog[-1]:.1f}B，"
                f"覆盖倍数 {coverage[-1]:.2f}x 高于去年同期的 {coverage_all[-5]:.2f}x"
            ),
            "xlabels": labels,
            "values": backlog,
            "legend": "季末 backlog",
            "fmt": "usd1",
            "yfmt": "usd1",
            "label_fmt": "usd1",
            "ylab": "US$B",
            "ylab2": "覆盖倍数",
            "yoy": {
                "name": "backlog / 过去四季收入 (RHS) D",
                "values": coverage,
                "color": "RED",
                "yfmt": "f2",
            },
            "note": (
                f"绝对额是历史最高，覆盖倍数 {coverage[-3]:.2f}x → {coverage[-2]:.2f}x → "
                f"{coverage[-1]:.2f}x 连续两季走低。"
                "<b>但这条线有季节性，不能按环比读</b>：管理层自己的说法是"
                "「normally, first half, we draw down on our backlog」，"
                f"所以有意义的比较是同一季度——本季 {coverage[-1]:.2f}x，"
                f"去年同期 {coverage_all[-5]:.2f}x，前年同期 {coverage_all[-9]:.2f}x。"
                "真正的新信息是：在一个管理层承认的「低续约年」里，"
                f"上半年 backlog 逆季节性净增 $300M。本季隐含 book-to-bill 的中枢读数是 "
                f"{book_to_bill[-1]:.2f}x，但 backlog 只披露到 US$0.1B，两季相减后的区间是 "
                "1.00x–1.13x——这个比率因此只能当方向看，不能当阈值判，本页据此已把它退役。"
            ),
            "src_extra": (
                "backlog 为公司在各季 CFO Commentary 披露值，精度到 US$0.1B，"
                "2020Q1 起逐季给出、此前只在年末给出；"
                "覆盖倍数与 book-to-bill 为自算，后者受 backlog 只到 US$0.1B 的精度限制。"
            ),
        },
        {
            "kind": "gs_bar",
            "title": (
                f"单季回购 ${buybacks[-1]:,.0f}M，摊薄股数却升到 {diluted_shares[-1]:.1f}M"
            ),
            "xlabels": labels,
            "values": buybacks,
            "legend": "单季回购金额",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "ylab2": "摊薄股数",
            "yoy": {
                "name": "摊薄股数 (RHS)",
                "values": diluted_shares,
                "color": "RED",
                "yfmt": "f1",
            },
            "note": (
                f"本季回购均价 ${buybacks[-1] / buyback_shares[-1]:.0f}/股，"
                f"上季 ${buybacks[-2] / buyback_shares[-2]:.0f}、去年同期 "
                f"${buybacks[-5] / buyback_shares[-5]:.0f}——金额固定、对价格不敏感，"
                "股价越高买到的股数越少。"
                f"全年摊薄股数指引 {guidance['fy2026_current']['diluted_shares_m'][0]:.1f}–"
                f"{guidance['fy2026_current']['diluted_shares_m'][1]:.1f}M，高于 2025 年的 "
                f"{guidance['fy2025_actual']['diluted_shares_m']:.1f}M。"
                f"<b>按公司承诺的「全年约 50% 自由现金流用于回购」，这笔钱的全部作用是抵消股权激励稀释</b>，"
                "并非缩股：本季股权激励占收入 "
                f"{sbc_ratio[-1]:.1f}%，与去年同期持平。"
            ),
            "src_extra": (
                "回购金额与股数、摊薄股数均为公司披露值；回购均价为两者相除的自算值。"
                "全年股数上升还包含 Hexagon D&E 交易中以股票支付的对价，公司未单独披露其股数。"
            ),
        },
    ]

    # ── section three: the same discipline pointed forward ──────────────────
    next_charts = [
        headroom_exhibit(
            "下季 6 条量化阈值：5 条在安全侧，唯一为负的是公司自己指引出来的 Q4 利润率",
            next_kpi["quantified"],
            "current",
            (
                f"正值 = 仍在安全侧。经营与订单五条都还有余量，"
                f"被击穿的那条不是已经发生的事——是全年指引隐含的 Q4 非 GAAP 营业利润率 {q4_margin:.2f}%，"
                f"比阈值低 {abs(headroom('up', 44.0, q4_margin)):.1f}%。"
                "换句话说，这一季唯一越线的数字是公司自己指引出来的，不是市场或经营给的。"
            ),
            src_extra=(
                "阈值为本地研究设定，不是公司指引；当前值为本季实际或据全年指引自算。"
                "另有 5 条需等披露才能判定，列在核对表下方。"
                "<b>Semiconductor IP 增速这一条精度远低于其余五条</b>：公司只给整数占比，"
                "两个整数各带 ±0.5pp，复合到增速上约 ±10pp，所以 +43% 应读成「40% 出头」，"
                "与新闻稿的「超过 40%」一致；好在阈值 30% 离这个区间足够远，判定仍然成立。"
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
        only={"单季非 GAAP 营业利润率", "中国收入占比", "backlog / 过去四季收入"},
    )

    # ── section four: the routine series chosen for this company ────────────
    fy_labels = fy["labels"] + ["2026E"]
    fy_gaap_margin = fy["gaap_operating_margin_pct"] + [
        sum(fy["guided_2026e"]["gaap_operating_margin_pct"]) / 2]
    fy_non_gaap_margin = fy["non_gaap_operating_margin_pct"] + [
        sum(fy["guided_2026e"]["non_gaap_operating_margin_pct"]) / 2]
    fy_sbc = fy["stock_based_compensation_pct_of_revenue"] + [
        fy["guided_2026e"]["stock_based_compensation_pct_of_revenue"]]
    fy_ex_sbc = fy["non_gaap_operating_margin_ex_sbc_pct"] + [
        fy["guided_2026e"]["non_gaap_operating_margin_ex_sbc_pct"]]
    fy_backlog = fy["year_end_backlog_usd_bn"]
    fy_revenue = fy["revenue_usd_m"]
    fy_coverage = [
        None if level is None else level * 1000 / total
        for level, total in zip(fy_backlog, fy_revenue)
    ]

    routine = [
        {
            "kind": "gs_bar",
            "title": (
                f"收入自 ASC 606 以来的 {len(long_labels)} 个季度：从 ${long_revenue[0]:,.0f}M 到 "
                f"${long_revenue[-1]:,.0f}M，本季同比 {long_revenue_yoy[-1]:.1f}%"
            ),
            "xlabels": long_labels,
            "xstep": LONG_STEP,
            "values": long_revenue,
            "legend": "季度总收入",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "ylab2": "同比增速",
            "yoy": {
                "name": "同比增速 (RHS) D",
                "values": long_revenue_yoy,
                "color": "GREEN",
                "yfmt": "pct0",
            },
            "note": (
                f"<b>八季的窗口会把当前这段读成一条直线，八年的窗口说的是一段过山车</b>："
                f"同比增速在 {peak_quarter} 见顶 {max_yoy:.1f}%，"
                f"到 {trough_quarter} 掉到 {min_recent_yoy:.1f}%，本季回到 {long_revenue_yoy[-1]:.1f}%。"
                f"窗口里唯一一个负增长季是 {negative_quarter}（{min_yoy:.1f}%）。"
                f"{long['provenance']}"
            ),
            "src_extra": source_note("季度收入来自各期 10-Q / 10-K；同比为自算"),
        },
        {
            "kind": "lines",
            "title": (
                f"利润率十年：非 GAAP 从 {fy_non_gaap_margin[0]:.0f}% 升到 "
                f"{fy_non_gaap_margin[-2]:.1f}%，2026E 却是十年里第一次同比下降"
            ),
            "xlabels": fy_labels,
            "series": [
                {"name": "非 GAAP 营业利润率", "values": fy_non_gaap_margin, "color": "NAVY"},
                {"name": "GAAP 营业利润率", "values": fy_gaap_margin, "color": "MBLUE"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "end_label": True,
            "ylab": "营业利润率",
            "note": (
                f"非 GAAP 口径连续九年上行，2026E 中值 {fy_non_gaap_margin[-1]:.2f}% 是这条线"
                f"<b>十年里第一次同比走低</b>（2025 年为 {fy_non_gaap_margin[-2]:.1f}%）。"
                f"GAAP 口径在 2022 年见顶 {max(v for v in fy_gaap_margin if v is not None):.1f}% 后已经回落了四年，"
                "两条线的缺口自 2024 年起加速张开——那是并购摊销与整合费用累积的结果。"
                "管理层对 2027 年的明示承诺是「better operating margins next year」，"
                f"即必须高于 2026E 的 {fy_non_gaap_margin[-1]:.2f}%；这是一句可证伪的话。"
            ),
            "src_extra": (
                "2016–2025 为公司在历年 CFO Commentary 的五年财务指标表中披露的年度值"
                "（2016–2020 的 GAAP 口径由当年 10-K 的营业利润 ÷ 收入自算，公司当年未在该表列示）；"
                "2026E 为本季全年指引区间的中值。"
            ),
        },
        {
            "kind": "lines",
            "title": (
                f"扣掉股权激励之后：SBC 占收入十年从 {fy_sbc[0]:.0f}% 升到 {fy_sbc[-1]:.1f}%，"
                f"调整后利润率 2026E 反而回落到 {fy_ex_sbc[-1]:.2f}%"
            ),
            "xlabels": fy_labels,
            "series": [
                {"name": "非 GAAP 营业利润率", "values": fy_non_gaap_margin, "color": "GRAY"},
                {"name": "SBC 调整后非 GAAP 营业利润率", "values": fy_ex_sbc, "color": "NAVY"},
                {"name": "股权激励占收入", "values": fy_sbc, "color": "RED"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "zero_base": True,
            "end_label": True,
            "ylab": "占收入比",
            "note": (
                f"<b>这是本季唯一一个真实倒退的盈利指标，而且倒退幅度是表观的两倍</b>："
                f"表观非 GAAP 利润率 2026E 较 2025 年降 "
                f"{fy_non_gaap_margin[-1] - fy_non_gaap_margin[-2]:.2f}pp，"
                f"而把股权激励还原成成本后降 {fy_ex_sbc[-1] - fy_ex_sbc[-2]:.2f}pp。"
                "两条线的缺口就是 SBC，它十年间从 6% 一路走到 9%。"
                "这一行与上一行都是公司自己在 CFO Commentary 里并列披露的，不是本页的再加工。"
            ),
            "src_extra": (
                "三行均取自历年 CFO Commentary 的「Profitability Trends」表（公司披露值）；"
                "2026E 为公司给出的全年指引中值。"
            ),
        },
        {
            "kind": "gs_bar",
            "title": (
                f"研发绝对额八年 {long_research[-1] / long_research[0]:.1f} 倍，"
                f"占收入比却从 {long_research_ratio[0]:.1f}% 降到 {long_research_ratio[-1]:.1f}%"
            ),
            "xlabels": long_labels,
            "xstep": LONG_STEP,
            "values": long_research,
            "legend": "季度研发费用",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "ylab2": "占收入比",
            "yoy": {
                "name": "研发 / 收入 (RHS) D",
                "values": long_research_ratio,
                "color": "RED",
                "yfmt": "pct0",
            },
            "note": (
                f"<b>十年利润率扩张的来源就在这条线上</b>：研发、营销与管理三项合计占收入"
                f"由 {long_opex_ratio[0]:.1f}% 降到 {long_opex_ratio[-1]:.1f}%，"
                f"同期非 GAAP 营业利润率从 26% 走到 44.6%——不是提价，是费用被收入摊薄。"
                f"这条线季节性明显（第四季收入高、比率低），窗口内最低到过 "
                f"{min(v for v in long_research_ratio if v is not None):.1f}%。"
                f"本季研发同比 {research_yoy[-1]:.1f}%，管理层口径的全年研发同比约 +19%"
                "（2025 年为 +10%），是下半年利润率让步的主要去向；"
                f"营销费用同比 {marketing_yoy[-1]:.1f}%、管理费用同比 {admin_yoy[-1]:.1f}%，"
                "后者是三条费用线里最快的一条。"
            ),
            "src_extra": source_note(
                "研发费用逐季来自各期 10-Q / 10-K，财政第四季为全年 − 前三季；占收入比为自算"),
        },
        {
            "kind": "gs_bar",
            "title": (
                f"年末 backlog 十年从 US${fy_backlog[0]:.1f}B 到 US${fy_backlog[-1]:.1f}B，"
                f"覆盖倍数在 2022 年见顶 {max(v for v in fy_coverage if v is not None):.2f}x "
                f"后连续三年停在 {fy_coverage[-1]:.2f}x"
            ),
            "xlabels": fy["labels"],
            "values": fy_backlog,
            "legend": "年末 backlog",
            "fmt": "usd1",
            "yfmt": "usd1",
            "label_fmt": "usd1",
            "ylab": "US$B",
            "ylab2": "覆盖倍数",
            "yoy": {
                "name": "backlog / 当年收入 (RHS) D",
                "values": fy_coverage,
                "color": "RED",
                "yfmt": "f2",
            },
            "note": (
                "<b>十年窗口才说得清「创纪录 backlog」到底意味着什么</b>：绝对额年年新高，"
                f"而以当年收入衡量的覆盖倍数在 2019 年就到过 {fy_coverage[3]:.2f}x、"
                f"2022 年见顶 {max(v for v in fy_coverage if v is not None):.2f}x，"
                f"随后 2023、2024、2025 三年<b>一模一样地停在 {fy_coverage[-1]:.2f}x</b>。"
                "订单存量与收入是同步长大的，没有跑赢——所以「record backlog」的 de-risk 含义"
                "比标题读起来小，可见度既没有变长，也没有变短。"
            ),
            "src_extra": (
                "backlog 为公司在历年 CFO Commentary 的 Backlog 表中披露的年末值，精度到 US$0.1B；"
                "覆盖倍数为其除以同年收入的自算值。"
            ),
        },
    ]

    exhibits = resolve_exhibit_refs(
        number_exhibits(settled_charts + highlights + next_charts + routine)
    )
    grouped = []
    cursor = 0
    for group in (settled_charts, highlights, next_charts, routine):
        grouped.append(exhibits[cursor:cursor + len(group)])
        cursor += len(group)
    settled_ex, highlight_ex, next_ex, routine_ex = grouped
    first_table = len(exhibits) + 2

    # ── audit tables ────────────────────────────────────────────────────────
    record = staging["quarterly_guidance_history"]
    delivery_rows = []
    for index, quarter in enumerate(record["quarters"]):
        def verdict(actual, low, high):
            if actual is None:
                return "待披露"
            if actual > high:
                return "高于上限"
            if actual < low:
                return "低于下限"
            return "区间内"
        actual_revenue = record["revenue_actual_usd_m"][index]
        actual_margin = record["non_gaap_operating_margin_actual_pct"][index]
        actual_eps = record["non_gaap_eps_actual"][index]
        low, high = record["revenue_guide_low_usd_m"][index], record["revenue_guide_high_usd_m"][index]
        m_low = record["non_gaap_operating_margin_guide_low_pct"][index]
        m_high = record["non_gaap_operating_margin_guide_high_pct"][index]
        e_low, e_high = record["non_gaap_eps_guide_low"][index], record["non_gaap_eps_guide_high"][index]
        delivery_rows.append([
            quarter_label(quarter),
            record["guided_on"][index],
            f"${low:,.0f}–{high:,.0f}M",
            "—" if actual_revenue is None else f"${actual_revenue:,.1f}M",
            verdict(actual_revenue, low, high),
            (f"{m_low:.2f}%" if record["non_gaap_operating_margin_guide_form"][index] == "point"
             else f"{m_low:.2f}–{m_high:.2f}%"),
            "—" if actual_margin is None else f"{actual_margin:.1f}%",
            verdict(actual_margin, m_low, m_high),
            f"${e_low:.2f}–{e_high:.2f}",
            "—" if actual_eps is None else f"${actual_eps:.2f}",
            verdict(actual_eps, e_low, e_high),
        ])

    quarterly_rows = []
    for index, period in enumerate(periods):
        def cell(name, fmt="${:,.1f}M"):
            value = q[name][index]
            return "—" if value is None else fmt.format(value)
        quarterly_rows.append([
            period,
            cell("revenue_total"),
            cell("revenue_product_and_maintenance"),
            cell("revenue_services"),
            cell("operating_income"),
            cell("research_and_development"),
            cell("marketing_and_sales"),
            cell("general_and_administrative"),
            cell("stock_based_compensation"),
            cell("operating_cash_flow"),
            cell("capital_expenditures"),
            f"${q['operating_cash_flow'][index] - q['capital_expenditures'][index]:,.1f}M D",
            cell("stock_repurchases"),
            "—" if qo["diluted_shares_m"][index] is None else f"{qo['diluted_shares_m'][index]:.3f}M",
        ])

    mix_rows = []
    for index, period in enumerate(periods[-WINDOW:], start=len(periods) - WINDOW):
        def share(name):
            value = qp[name][index]
            return "—" if value is None else f"{value:.0f}%"

        def amount(name):
            value = qp[name][index]
            return "—" if value is None else f"${value / 100 * revenue[index]:,.0f}M D"
        mix_rows.append([
            period,
            share("category_core_eda"), amount("category_core_eda"),
            share("category_semiconductor_ip"), amount("category_semiconductor_ip"),
            share("category_system_design_analysis"), amount("category_system_design_analysis"),
            share("geo_americas"), share("geo_china"),
            "—" if q["china_revenue"][index] is None else f"${q['china_revenue'][index]:,.1f}M",
            share("geo_other_asia"), share("geo_emea"), share("geo_japan"),
            "—" if qp["recurring_revenue"][index] is None else f"{qp['recurring_revenue'][index]:.0f}%",
        ])

    annual_rows = []
    for index, year in enumerate(fy["labels"]):
        def fy_cell(name, fmt="{:,.0f}"):
            value = fy[name][index]
            return "—" if value is None else fmt.format(value)
        annual_rows.append([
            year,
            f"${fy['revenue_usd_m'][index]:,.0f}M",
            fy_cell("gaap_operating_margin_pct", "{:.1f}%"),
            fy_cell("non_gaap_operating_margin_pct", "{:.1f}%"),
            fy_cell("stock_based_compensation_pct_of_revenue", "{:.1f}%"),
            fy_cell("non_gaap_operating_margin_ex_sbc_pct", "{:.1f}%"),
            fy_cell("non_gaap_eps", "${:.2f}"),
            fy_cell("diluted_shares_m", "{:.1f}M"),
            fy_cell("operating_cash_flow_usd_m", "${:,.1f}M"),
            fy_cell("capital_expenditures_usd_m", "${:,.1f}M"),
            fy_cell("stock_repurchases_usd_m", "${:,.1f}M"),
            fy_cell("year_end_backlog_usd_bn", "US${:.1f}B"),
        ])
    guided = fy["guided_2026e"]
    annual_rows.append([
        "2026E（指引）",
        f"${guided['revenue_usd_m'][0]:,.0f}–{guided['revenue_usd_m'][1]:,.0f}M",
        f"{guided['gaap_operating_margin_pct'][0]:.2f}–{guided['gaap_operating_margin_pct'][1]:.2f}%",
        f"{guided['non_gaap_operating_margin_pct'][0]:.2f}–{guided['non_gaap_operating_margin_pct'][1]:.2f}%",
        f"{guided['stock_based_compensation_pct_of_revenue']:.1f}%",
        f"{guided['non_gaap_operating_margin_ex_sbc_pct']:.2f}%",
        f"${guided['non_gaap_eps'][0]:.2f}–{guided['non_gaap_eps'][1]:.2f}",
        f"{guided['diluted_shares_m'][0]:.1f}–{guided['diluted_shares_m'][1]:.1f}M",
        f"约 ${guided['operating_cash_flow_usd_m']:,.0f}M",
        f"约 ${guided['capital_expenditures_usd_m']:,.0f}M",
        "约 50% 自由现金流",
        "—",
    ])

    q3 = guidance["q3_2026"]
    current = guidance["fy2026_current"]
    previous = guidance["fy2026_previous"]
    guidance_rows = [
        ["下季收入", f"${revenue[-1]:,.1f}M（本季实际）",
         f"${q3['revenue_usd_m'][0]:,.0f}–{q3['revenue_usd_m'][1]:,.0f}M",
         f"中值隐含同比 {signed(guidance_revenue_yoy)}、环比 "
         f"{signed(pct_change(q3_revenue_mid, revenue[-1]))} D"],
        ["下季非 GAAP 营业利润率", f"{non_gaap_margin[-1]:.1f}%（本季实际）",
         f"{q3['non_gaap_operating_margin_pct'][0]:.1f}–{q3['non_gaap_operating_margin_pct'][1]:.1f}%",
         f"中值较本季实际 {q3_margin_mid - non_gaap_margin[-1]:+.1f}pp D"],
        ["下季非 GAAP EPS", f"${qo['non_gaap_eps'][-1]:.2f}（本季实际）",
         f"${q3['non_gaap_eps'][0]:.2f}–{q3['non_gaap_eps'][1]:.2f}",
         f"中值环比 {pct_change(sum(q3['non_gaap_eps']) / 2, qo['non_gaap_eps'][-1]):+.1f}% D"],
        ["下季回购", f"${buybacks[-1]:,.0f}M（本季实际）", f"约 ${q3['buyback_usd_m']:,.0f}M", "连续第四季持平"],
        ["全年收入", f"${previous['revenue_usd_m'][0]:,.0f}–{previous['revenue_usd_m'][1]:,.0f}M",
         f"${current['revenue_usd_m'][0]:,.0f}–{current['revenue_usd_m'][1]:,.0f}M",
         f"上修 ${raise_revenue:,.0f}M D，全部有机（并购口径未变）"],
        ["全年非 GAAP 营业利润率",
         f"{previous['non_gaap_operating_margin_pct'][0]:.2f}–{previous['non_gaap_operating_margin_pct'][1]:.2f}%",
         f"{current['non_gaap_operating_margin_pct'][0]:.2f}–{current['non_gaap_operating_margin_pct'][1]:.2f}%",
         "中值上修 25bp，仍低于 2025 年的 44.6%"],
        ["全年非 GAAP EPS", f"${previous['non_gaap_eps'][0]:.2f}–{previous['non_gaap_eps'][1]:.2f}",
         f"${current['non_gaap_eps'][0]:.2f}–{current['non_gaap_eps'][1]:.2f}",
         f"中值上修 $0.20；增量经营利润率 {incremental_margin:.1f}% D"
         f"（用公司印出的经营利润 ${fy_operating_income:,.0f}M 与 "
         f"${guidance['fy2026_previous']['non_gaap_operating_income_midpoint_usd_m']:,.0f}M 相减）；"
         f"改用指引区间中值直接相乘为 {incremental_margin_exact:.1f}%，差异来自公司对经营利润的四舍五入"],
        ["全年经营现金流",
         f"${previous['operating_cash_flow_usd_m'][0]:,.0f}–{previous['operating_cash_flow_usd_m'][1]:,.0f}M",
         f"约 ${current['operating_cash_flow_usd_m']:,.0f}M", "上修约 $75M"],
        ["全年收入中来自期初 backlog 的比例",
         f"约 {previous['revenue_from_beginning_backlog_pct']}%",
         f"约 {current['revenue_from_beginning_backlog_pct']}%",
         "只披露到整数位；方向是新签订单的贡献在上升，比例本身不稳健"],
        ["Q4 2026 隐含非 GAAP 营业利润率", "—", f"{q4_margin:.2f}% D",
         f"由全年中值 ${fy_operating_income:,.0f}M − 上半年实际 − Q3 指引中值倒推；"
         f"与 2025Q2 的 42.8% 持平"],
        ["全年指引的政策前提", "—", "出口管制维持现状", guidance["export_control_assumption"]],
    ]

    balance_rows = []
    for name, chinese in [
        ("cash_and_equivalents", "现金及等价物"),
        ("receivables_net", "应收账款净额"),
        ("inventories", "存货"),
        ("goodwill", "商誉"),
        ("acquired_intangibles_net", "无形资产净额"),
        ("deferred_revenue_current", "当期递延收入"),
        ("deferred_revenue_long_term", "长期递延收入"),
        ("long_term_debt", "长期借款（账面）"),
        ("other_long_term_liabilities", "其他长期负债"),
        ("stockholders_equity", "股东权益"),
        ("total_assets", "资产总额"),
    ]:
        start, end = balance[name]
        balance_rows.append([
            chinese, f"${start:,.1f}M", f"${end:,.1f}M",
            f"${end - start:+,.1f}M", f"{pct_change(end, start):+.1f}% D",
        ])

    bridge_rows = [
        [name, f"${value:+,.1f}M" if index not in (0, len(bridge["labels"]) - 1) else f"${value:,.1f}M"]
        for index, (name, value) in enumerate(zip(bridge["labels"], bridge["values"]))
    ]

    tables = [
        threshold_table(
            first_table, "上季阈值与本季实际（原单位）",
            prior_kpi["quantified"], "actual", "Q2 2026 实际",
        ),
        threshold_table(
            first_table + 1, "下季阈值与当前值（原单位）",
            next_kpi["quantified"], "current", "当前值",
        ),
        {
            "n": first_table + 2,
            "title": f"指引兑现记录：{len(record['quarters'])} 个季度的三项指引与实际（原单位）",
            "headers": ["季度", "指引发布日", "收入指引", "实际收入", "结果",
                        "非 GAAP 营业利润率指引", "实际", "结果",
                        "非 GAAP EPS 指引", "实际", "结果"],
            "rows": delivery_rows,
        },
        {
            "n": first_table + 3,
            "title": "下季与全年指引",
            "headers": ["指标", "上季 / 本季实际", "新口径", "变化 / 备注"],
            "rows": guidance_rows,
        },
        {
            "n": first_table + 4,
            "title": "十二季度基础数据（前四季只用于计算同比）",
            "headers": ["期间", "总收入", "产品与维护", "服务", "GAAP 经营利润", "研发", "营销",
                        "管理", "股权激励", "经营现金流", "资本开支", "自由现金流 D", "回购", "摊薄股数"],
            "rows": quarterly_rows,
        },
        {
            "n": first_table + 5,
            "title": "八季度产品线与地域占比（公司只披露整数百分位，金额为自算）",
            "headers": ["期间", "Core EDA", "金额 D", "IP", "金额 D", "SD&A", "金额 D",
                        "美洲", "中国占比", "中国收入（申报值）", "其他亚洲", "EMEA", "日本", "经常性收入"],
            "rows": mix_rows,
        },
        {
            "n": first_table + 6,
            "title": "十年年度记录与 2026 全年指引",
            "headers": ["年度", "收入", "GAAP 营业利润率", "非 GAAP 营业利润率", "SBC 占收入",
                        "SBC 调整后非 GAAP 营业利润率", "非 GAAP EPS", "摊薄股数",
                        "经营现金流", "资本开支", "回购", "年末 backlog"],
            "rows": annual_rows,
        },
        {
            "n": first_table + 7,
            "title": "资产负债表变动（2025-12-31 → 2026-06-30）",
            "headers": ["项目", "2025-12-31", "2026-06-30", "变动", "变动率"],
            "rows": balance_rows,
        },
        {
            "n": first_table + 8,
            "title": "上半年现金桥（逐项取自现金流量表）",
            "headers": ["项目", "金额"],
            "rows": bridge_rows,
        },
        ai_capex_cycle_table(first_table + 9),
    ]

    china_peak = max(v for v in china_revenue if v is not None)

    return {
        "schema_version": "quarterly-dashboard/cdns-v1",
        "page": {"slug": "cdns", "language": "zh-CN"},
        "company": {
            "ticker": "CDNS",
            "name": "Cadence Design Systems",
            "group": "semiconductor_ai",
            "accounting_standard": "US GAAP",
        },
        "latest": {
            "disclosed_period_label": "Q2 2026",
            "full_financial_period_label": "Q2 2026（自然年季度）",
            "period_end": "2026-06-30",
            "release_date": "2026-07-27",
            "analysis_date": "2026-07-28",
            "audit_status": "unaudited",
            "status": "history_ready",
        },
        "tracker": "Watchlist Quarterly Tracker · CDNS",
        "title": "Cadence Design Systems (CDNS)：Q2 2026 季报仪表盘",
        "subtitle": (
            "截至 2026-06-30 · 发布 2026-07-27 · US GAAP · 未经审计 · "
            "金额单位为 $M，另有注明除外"
        ),
        "headline": (
            f"真正变强的不是收入而是订单：收入 ${revenue[-1]:,.1f}M 落在指引区间之内、"
            f"只比中值高 {pct_change(revenue[-1], quarter_guide_mid):.1f}%，"
            f"但在管理层自己称的「低续约年」里，上半年 backlog 逆季节性净增 $300M 到 "
            f"US${backlog[-1]:.1f}B。代价写在下半年："
            f"全年收入上修 ${raise_revenue:,.0f}M 只换来 ${raise_operating_income:,.0f}M 经营利润，"
            f"倒推出的 Q4 非 GAAP 营业利润率 {q4_margin:.2f}% 与危机季 2025Q2 持平。"
            f"财报当日盘后 {signed(consensus['post_earnings_price_change_pct'], 0)}。"
        ),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>亮点</span><b>低续约年里订单逆季节性净增</b>'
            f'<p>backlog US${backlog[-1]:.1f}B 创纪录，上半年逆季节性净增 $300M；'
            f'经营现金流 ${operating_cash_flow[-1]:,.0f}M、同比 '
            f'{pct_change(operating_cash_flow[-1], operating_cash_flow[-5]):+.0f}%。</p></article>'
            '<article><span>张力</span><b>全年上修，下半年利润率却在让步</b>'
            f'<p>收入 +${raise_revenue:,.0f}M 换 OpInc +${raise_operating_income:,.0f}M；'
            f'倒推 Q4 非 GAAP 营业利润率 {q4_margin:.2f}%，'
            f'较上半年实际低 {h1_margin - q4_margin:.1f}pp，金额未披露。</p></article>'
            '<article><span>存疑</span><b>中国占比创两年新高却无人过问</b>'
            f'<p>占比 {china_share_exact[-1]:.1f}%、金额 ${china_revenue[-1]:,.0f}M，仍低于 2025Q3 的 '
            f'${china_peak:,.0f}M；管理层未重申全年口径，问答中零提及。</p></article>'
            '</div>'
        ),
        "source": source,
        "source_url": "https://www.cadence.com/en_US/home/company/investor-relations.html",
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {
                "id": "settled",
                "title": "一、上季跟踪指标兑现了吗",
                "description": (
                    "先结算上季留下的问题与阈值，再把同一个问题问给公司自己："
                    f"{len(record['quarters'])} 个季度的指引与实际摆在一起，"
                    "本季这份成绩单才有参照系。"
                ),
                "exhibits": settled_ex,
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": (
                    "收入与产品线结构、中国这条没人问的线、GAAP 与非 GAAP 毛利率的背离、"
                    "全年指引倒推出来的 Q4 利润率，以及订单存量与资本分配。"
                ),
                "exhibits": highlight_ex,
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": "同一套口径向前看：当前值离下季阈值还有多远，统一用「距阈值余量」表示。",
                "exhibits": next_ex,
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": (
                    "CDNS 专属的常规序列：ASC 606 以来的收入曲线、十年利润率、"
                    "把股权激励还原成成本之后的利润率、研发强度，以及订单存量的覆盖倍数。"
                ),
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": [
            "本页统一用自然年季度标注。Cadence 自 2023 财年起各季结束于自然季末，"
            "2022 及以前为 52/53 周制、季末落在自然季末前后数日；本页按公司自己的财季归入相应自然年季度，"
            "不做任何日历调整。",
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，"
            "每张图下一到两句解释；支撑表格收在核对抽屉里。",
            f"Exhibit 2 与 Exhibit {len(settled_ex) + len(highlight_ex) + 2} 的阈值是本地研究设定，"
            "不是公司指引，也不构成评级或投资建议；「距阈值余量」统一为正值代表安全侧。",
            "本页只发布公司披露值、可复算的简单派生值，以及明确标注的市场预期；D 标记代表 Derived / 自算。",
            "指引兑现记录取自各季业绩 8-K 的 EX-99.02 CFO Commentary，"
            f"覆盖 {record['quarters'][0][:4]}Q{record['quarters'][0][-1]} 起共 {len(record['quarters'])} 个季度，"
            "其中最后一季只有指引、实际值待披露。"
            "<b>该指引与上一季财报同时发布，发布日已落在被指引季度之内</b>——"
            "第二、三、四季通常已过约 4 周，第一季往往已过半个季度，因此它不是事前预测；"
            "核对表的「指引发布日」一列可逐季复核。"
            "非 GAAP 营业利润率的指引在部分季度是单点数（原文写作 ~30% 或 approximately 30%）而不是区间，"
            "写作「29% to 30%」的则是区间；核对表按公司原样列示，单点季在图上因此没有宽度。",
            "2018Q1 起收入确认采用 ASC 606，2017 及以前按 ASC 605 报告且公司未重述，"
            "两段水平值不可直接连读；本页的长期序列因此自 2018Q1 起，"
            "指引兑现的水平图在该季打断点，而偏离序列不受影响——每一对指引与实际都落在同一套准则内。",
            "产品线（Core EDA / Semiconductor IP / System Design and Analysis）只披露"
            "<b>收入占比的整数百分位</b>，公司不披露该口径的分部金额。本页相关金额均为占比 × 当季总收入的自算值，"
            "含 ±$8M 量级的四舍五入误差；两个整数占比相除得到的同比增速误差可达 ±10pp，"
            "因此 IP 的「+43%」只应读作「40% 出头」。公司自己给出的分部同比"
            "（Core EDA +18%、IP「超过 40%」、SD&A +37%）与占比法反推的结果互有出入，"
            "两者都列在核对表里，本页不在两者间取舍。",
            "<b>地域是例外：中国收入有申报金额，不需要用占比反推。</b>"
            "10-Q / 10-K 的分部附注按地域披露收入金额（千美元），本页中国那张图用的就是这个金额；"
            "季度值自 2023Q1 起可得，财政第四季为全年 − 前三季。"
            "用整数占比反推会系统性偏离——按占比法本季中国同比为 +107%，按申报金额为 "
            f"{china_yoy[-1]:+.1f}%。CFO Commentary 的整数占比可回溯到 2018Q1，本页只把它当占比用。",
            "Q4 2026 隐含非 GAAP 营业利润率为算术倒推：全年指引中值的非 GAAP 营业利润 "
            "− 上半年实际 − Q3 指引中值隐含值，除以同法倒推的 Q4 收入。四个输入全部是公司披露值，"
            "没有估计成分；但它是<b>指引隐含值而非公司给出的 Q4 指引</b>，公司并未单独给 Q4 数字。",
            "backlog 覆盖倍数为自算（季末 backlog ÷ 过去四季收入）。backlog 只披露到 US$0.1B，"
            "水平值与覆盖倍数受此限制但仍可判；<b>两季相减得到的 book-to-bill 则不可判</b>——"
            "本季 $100M 的净增带 ±$100M 的四舍五入区间，比率落在 1.00x–1.13x，"
            "恰好横跨上季设定的 1.10x 阈值，因此该指标已退役而不是被判为击穿。"
            "覆盖倍数另有季节性：backlog 每年上半年被消耗，该倍数在第二、三季走低、第四季回补，"
            "只能同比不能环比读。",
            "市场预期一律标注为「市场预期」并给出取数时点，不写卖方机构名，也不发布评级、目标价或估值。"
            + consensus["source_conflict_note"] + "。",
            "本页已知未接入：Hexagon D&E 的单季收入贡献与利润率（公司只在 Q1 2026 给过一次全年口径，"
            "本季被直接问到未重申）、Intel 协议的金额与年限、下半年「targeted investments」的具体金额、"
            "agentic AI 相关的任何收入或 ARR（管理层已说明其在结构上会被吸收进 Core EDA 与经常性收入）、"
            "以及其他长期负债单季增加 $339.3M 的构成。",
        ],
        "footer": (
            "CDNS quarterly results · 数据来自 Cadence 公开披露与透明自算 · "
            "仅供研究，不构成投资建议"
        ),
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "cdns.js"), payload, "cdns")
    shell_dir = ROOT / "cdns"
    shell_dir.mkdir(exist_ok=True)
    # Rendered here, not at import: the shell stamps the payload's content
    # hash into its <script src>, so it has to be built after write_dash.
    (shell_dir / "index.html").write_text(
        render_shell("CDNS", "cdns"), encoding="utf-8")
    exhibits = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"CDNS page: {exhibits} charts in 4 sections + {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
