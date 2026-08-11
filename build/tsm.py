#!/usr/bin/env python3
"""Build the TSMC quarterly-results page.

Same four-part, chart-led shape as the GOOGL page (上季兑现 → 本季重点 →
下季跟踪 → 长期常规), but the routine series are the ones that actually decide
this company: volume vs price, node and platform mix, guidance delivery and
capital intensity.

The public payload contains only TSMC-reported figures, clearly labelled market
expectations, and arithmetic reproducible from the audit tables.
"""

from __future__ import annotations

import json
import statistics
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


STAGING_PATH = ROOT / "series" / "tsm.json"
DATA_DIR = ROOT / "data"


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100


def compact_period(period: str) -> str:
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def month_label(month: str) -> str:
    """``'2026-06'`` → ``'Jun-26'``."""
    year, number = month.split("-")
    return f"{MONTH_ABBR[int(number) - 1]}-{year[-2:]}"


def quarter_end_month(quarter: str) -> str:
    """``'2026Q2'`` → ``'2026-06'``."""
    year, number = quarter.split("Q")
    return f"{year}-{int(number) * 3:02d}"


def quarter_label(quarter: str) -> str:
    """``'2016Q1'`` → ``'Q1'16'``, matching `compact_period`'s output."""
    year, number = quarter.split("Q")
    return f"Q{number}'{year[-2:]}"


def leading_gap(values: list[float | None]) -> int:
    """Index of the first reported value; ``len(values)`` when there is none."""
    return next((i for i, value in enumerate(values) if value is not None), len(values))


def rounded(values: list[float | None], digits: int = 6) -> list[float | None]:
    """Round for the payload so a rebuild is idempotent, keeping ``None`` holes."""
    return [None if value is None else round(value, digits) for value in values]


def resolve_exhibit_refs(exhibits: list[dict]) -> list[dict]:
    """Substitute ``{ref}`` placeholders with the numbers `number_exhibits` assigned.

    Cross-references written as literal numbers break the moment a chart is
    inserted, and the page already refuses to hand-number the exhibits
    themselves; captions that point at them must follow the same rule.
    """
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


def delivery_band(ref: str, metric: str, quarters: list[str], low: list[float],
                  high: list[float], actual: list[float | None], *, fmt: str, ylab: str,
                  unit: str, src_extra: str, extra_note: str = "") -> dict:
    """One guided metric's own range against what was reported, quarter by quarter.

    The same object three times over, because the interesting part is the
    comparison between them: TSMC guides revenue, gross margin and operating
    margin every quarter with the same sentence structure, and the three have
    very different hit rates. A chart per metric keeps each on its own axis --
    percent and percentage points do not belong on one.
    """
    finished = [index for index, value in enumerate(actual) if value is not None]
    above = [index for index in finished if actual[index] > high[index]]
    below = [index for index in finished if actual[index] < low[index]]
    inside = len(finished) - len(above) - len(below)
    pending = [quarters[index] for index, value in enumerate(actual) if value is None]
    if below:
        verdict = (f"{len(finished)} 个已完结季里 {len(above)} 季超出上限、{inside} 季落在区间内、"
                   f"{len(below)} 季跌破下限")
    elif inside == 0:
        verdict = f"{len(finished)} 个已完结季全部超出指引上限，一次例外都没有"
    else:
        verdict = (f"{len(finished)} 个已完结季里 {len(above)} 季超出上限、{inside} 季落在区间内，"
                   "没有一季跌破下限")
    band = {
        "ref": ref,
        "kind": "range_band",
        "title": f"{metric}：{verdict}",
        "xlabels": list(quarters),
        "xrot": 90,
        "lo": list(low),
        "hi": list(high),
        "actual": list(actual),
        "actual_color": "NAVY",
        "names": {
            "range": f"公司{metric}指引区间",
            "actual": f"实际{metric}",
            "lo": f"指引下限（{unit}）",
            "hi": f"指引上限（{unit}）",
        },
        "fmt": fmt,
        "label_fmt": fmt,
        "ylab": ylab,
        "note": (
            f"色块是该季<b>开始前</b>公司在上一场法说会给出的{metric}区间，菱形是随后报出来的实际值。"
            + extra_note
            + (f"最后一格 {pending[-1]} 只有指引色块，实际值待披露。" if pending else "")
            + "纵轴不自 0 起，但没有任何点被截掉。"
        ),
        "src_extra": src_extra,
    }
    if pending:
        band["annot"] = f"{pending[-1]}：仅指引，实际值待披露"
    return band


def midpoint_deviation(ref: str, metric: str, quarters: list[str], low: list[float],
                       high: list[float], actual: list[float | None], *, mode: str,
                       src_extra: str, extra_note: str = "", window: int = 14) -> dict:
    """How far past the guided midpoint the quarter landed, for one guided metric.

    The band charts answer "did it clear the range at all", which saturates:
    operating margin has cleared the upper bound fifteen times running, so the
    band says the same thing every quarter. This asks the question that still
    has an answer -- by how much, and is that widening or narrowing.

    Two modes because the units genuinely differ. Revenue is guided as a level,
    so the honest distance is relative (%). Both margins are already ratios, so
    theirs is the arithmetic gap (pp): dividing a percentage by a percentage
    would print a number nobody quotes and that no company reports.
    """
    if mode not in ("pct", "pp"):
        raise ValueError(f"unknown mode {mode!r}")
    finished = [
        index for index, value in enumerate(actual) if value is not None
    ][-window:]
    midpoints = [(low[index] + high[index]) / 2 for index in finished]
    deviation = [
        (actual[index] / mid - 1) * 100 if mode == "pct" else actual[index] - mid
        for index, mid in zip(finished, midpoints)
    ]
    unit = "%" if mode == "pct" else "pp"
    above = sum(1 for value in deviation if value > 0)
    mean_absolute = statistics.fmean(abs(value) for value in deviation)
    biggest = max(deviation, key=abs)
    return {
        "ref": ref,
        "kind": "grouped_bars",
        "title": (
            f"{metric}相对指引中值的偏离：{len(deviation)} 季里 {above} 季为正，"
            f"平均绝对偏离 {mean_absolute:.1f}{unit}"
        ),
        "xlabels": [month_label(quarter_end_month(quarters[index])) for index in finished],
        "xrot": 90,
        "groups": [{
            "name": f"实际{metric} vs 指引中值",
            "color": "BLUE",
            "values": rounded(deviation),
        }],
        "bar_labels": True,
        "fmt": "pct1" if mode == "pct" else "pp1",
        "label_fmt": "pct1" if mode == "pct" else "pp1",
        "ylab": f"{unit} vs 指引中值",
        "note": (
            f"正值 = 高于指引区间的中值；长期为正说明公司指引偏保守，不是一连串意外。"
            f"x 轴标的是该季最后一个月。"
            f"窗口内最大的一次是 {month_label(quarter_end_month(quarters[finished[deviation.index(biggest)]]))} "
            f"的 {biggest:+.1f}{unit}。"
            + (
                "本图单位是<b>百分点</b>，与收入那张的<b>百分比</b>不可直接比大小 —— "
                "率的偏离取算术差，除一次只会得到一个没人引用的数。"
                if mode == "pp" else ""
            )
            + extra_note
        ),
        "src_extra": src_extra,
    }


def expectation_chart(staging: dict) -> dict:
    """Reported beat versus core beat, against the same market expectation.

    The page's other guidance charts ask whether the quarter cleared the
    company's own bar. This asks whether it cleared the market's -- and it is
    the one place where the answer changes depending on which profit line you
    use. Both are plotted so the reader sees the gap rather than being told
    about it.
    """
    consensus = staging["market_expectation"]
    snapshot = staging["current_snapshot"]
    bridge = staging["net_income_bridge"]["values_ntd_bn"]
    financials = staging["financials"]

    reported_net, core_net = bridge[0], bridge[2]
    reported_eps = financials["eps_ntd"][-1]
    # Core EPS is not disclosed: the one-off is a pre-tax non-operating gain, so
    # scaling reported EPS by the core/reported profit ratio is the only
    # arithmetic available and it is marked D like every other derived figure.
    core_eps = reported_eps * core_net / reported_net

    rows = [
        ("营收（US$）", pct_change(financials["revenue_usd_bn"][-1], consensus["revenue_usd_bn"])),
        ("营收（NT$）", pct_change(snapshot["revenue_ntd_bn"][0], consensus["revenue_ntd_bn"])),
        ("毛利率（pp）", financials["gross_margin_pct"][-1] - consensus["gross_margin_pct"]),
        ("报告净利", pct_change(reported_net, consensus["net_income_ntd_bn"])),
        ("报告 EPS", pct_change(reported_eps, consensus["eps_ntd"])),
        ("核心净利 D", pct_change(core_net, consensus["net_income_ntd_bn"])),
        ("核心 EPS D", pct_change(core_eps, consensus["eps_ntd"])),
    ]
    headline = pct_change(reported_eps, consensus["eps_ntd"])
    core = pct_change(core_eps, consensus["eps_ntd"])
    one_off = bridge[1]
    return {
        "ref": "EX_EXPECTATION",
        "kind": "diverging_bars",
        "title": (
            f"对市场预期：报告 EPS beat {headline:+.1f}%，剔除一次性后只有 {core:+.1f}%"
        ),
        "xlabels": [label for label, _ in rows],
        "values": [round(value, 2) for _, value in rows],
        "legend": "较市场预期",
        "positive_label": "高于市场预期",
        "negative_label": "低于市场预期",
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "% 或 pp",
        "zero_line": True,
        "note": (
            f"处置世界先进股份与保留股份重估的税前一次性收益 NT${one_off:.2f}B 解释了净利超预期金额的"
            f"绝大部分：剔除后核心净利较预期只有 {pct_change(core_net, consensus['net_income_ntd_bn']):+.1f}%。"
            "<b>干净的超预期在营收与毛利率，不在利润</b>。"
            "毛利率一项是百分点，其余是百分比，两类单位并列只用于比较方向与相对幅度。"
        ),
        "src_extra": (
            f"实际值来自 {staging['latest']['period']} earnings release / management report；"
            f"市场预期为财报前一致预期（{consensus['as_of']}），不具名。"
            "核心净利 = 报告净利减一次性税前收益，未做税务调整；"
            "核心 EPS 按核心 / 报告净利之比折算报告 EPS，均为自算，不是公司定义的调整后指标。"
        ),
    }


def guidance_delivery_charts(staging: dict) -> tuple[list[dict], dict]:
    """The full guided record for all three guided metrics, and what the beats are made of.

    TSMC guides three numbers every quarter -- revenue, gross margin, operating
    margin -- plus the exchange rate it assumed when setting them. The eight
    quarters the rest of the page carries cannot say whether beating the range
    is normal for this company; fifteen can, and the answer differs sharply by
    metric.

    The beat decomposition is an identity rather than an estimate. Revenue is
    guided in US dollars at an FX assumption stated on the call and reported at
    the rate the quarter realised, so:

        (1 + dollar beat) = (1 + NT$ operating beat) x (assumption / realised)

    Every term is a company-reported quarterly number, so the split needs no
    monthly series and no market rate.
    """
    guide = staging["quarterly_guidance_history"]
    quarters = guide["quarters"]
    low = guide["guide_low_usd_bn"]
    high = guide["guide_high_usd_bn"]
    midpoint = {
        quarter: (lo + hi) / 2 for quarter, lo, hi in zip(quarters, low, high)
    }
    guide_fx = dict(zip(quarters, guide["guide_fx_ntd_per_usd"]))
    actual_fx = dict(zip(quarters, guide["actual_fx_ntd_per_usd"]))
    actual = dict(zip(quarters, guide["actual_revenue_usd_bn"]))

    finished = [quarter for quarter in quarters if actual[quarter] is not None]
    beats = {quarter: (actual[quarter] / midpoint[quarter] - 1) * 100 for quarter in finished}

    SOURCE_6K = (
        "指引区间与假设汇率来自各季法说会当场发布的 6-K；"
        "实际值来自随后一季 6-K 所载合并损益表。"
    )
    revenue_band = delivery_band(
        "EX_RANGE", "收入", quarters, low, high, [actual[q] for q in quarters],
        fmt="usd1", ylab="US$B", unit="US$B", src_extra=SOURCE_6K,
        extra_note=(
            "指引与实际都是公司自己给的美元数，而美元数是新台币结果除以当季实际汇率的产物，"
            "所以每一格里都含一条汇率腿 —— 拆开见 Exhibit {EX_LEGS}。"
        ),
    )
    margin_band = delivery_band(
        "EX_GM", "毛利率", quarters,
        guide["gross_margin_guide_low_pct"], guide["gross_margin_guide_high_pct"],
        guide["gross_margin_actual_pct"],
        fmt="pct1", ylab="毛利率", unit="%",
        src_extra=SOURCE_6K + "实际毛利率 = 该季 6-K 合并损益表的毛利 ÷ 净销售额 D。",
        extra_note=(
            "毛利率的兑现纪律比收入还稳：区间宽度一律 2pp，公司从不给单点。"
            "本季 67.7% 超出上限 0.2pp，而下季指引中值已回到 66%，"
            "管理层同时把 2H26 的 N2 稀释量化为 3–4pp —— 这条线的方向已经确定向下。"
        ),
    )
    operating_band = delivery_band(
        "EX_OM", "营业利润率", quarters,
        guide["operating_margin_guide_low_pct"], guide["operating_margin_guide_high_pct"],
        guide["operating_margin_actual_pct"],
        fmt="pct1", ylab="营业利润率", unit="%",
        src_extra=SOURCE_6K + "实际营业利润率 = 该季 6-K 合并损益表的营业利益 ÷ 净销售额 D。",
        extra_note=(
            "<b>这是三条指引里最极端的一条</b>：窗口内没有任何一季落回区间之内，"
            "全部从上限穿出去。它说明营业利润率的指引不是预测而是底线 —— "
            "读这张图要问的不是「有没有超」，而是「超得比上季多还是少」。"
        ),
    )

    # ── Distance from the guided midpoint, one chart per guided metric ────────
    window = finished[-14:]
    midpoint_chart = midpoint_deviation(
        "EX_MIDPOINT", "收入", quarters, low, high, guide["actual_revenue_usd_bn"],
        mode="pct", src_extra=SOURCE_6K + "偏离为实际收入除以指引中值的自算值。",
        extra_note=(
            "<b>柱高不是纯经营偏离</b> —— 指引按业绩会写明的<b>假设</b>汇率给出，"
            "实际收入按当季实际汇率折算，每根柱里都含一条汇率腿，拆开见 Exhibit {EX_LEGS}。"
        ),
    )
    # The two margins share the revenue guidance's FX assumption -- it is one
    # column in the same 6-K -- so their gaps carry an FX component too. The
    # direction is stated, not the size: TSMC publishes no sensitivity in these
    # filings and this page does not invent one.
    FX_SHARED = (
        "毛利率指引与收入指引写在同一份 6-K 里、共用同一个假设汇率，"
        "所以这条偏离同样含汇率成分（新台币比假设弱时对利润率是顺风）；"
        "哪几季顺风、哪几季逆风见 Exhibit {EX_LEGS} 的金色腿。"
        "本页不给汇率对利润率的敏感度系数 —— 这批 6-K 没有披露，不自行编造。"
    )
    gm_midpoint_chart = midpoint_deviation(
        "EX_GM_MIDPOINT", "毛利率", quarters,
        guide["gross_margin_guide_low_pct"], guide["gross_margin_guide_high_pct"],
        guide["gross_margin_actual_pct"], mode="pp",
        src_extra=(SOURCE_6K + "实际毛利率 = 该季 6-K 合并损益表的毛利 ÷ 净销售额 D；"
                   "偏离为实际值减指引中值的自算值。"),
        extra_note=FX_SHARED,
    )
    om_midpoint_chart = midpoint_deviation(
        "EX_OM_MIDPOINT", "营业利润率", quarters,
        guide["operating_margin_guide_low_pct"], guide["operating_margin_guide_high_pct"],
        guide["operating_margin_actual_pct"], mode="pp",
        src_extra=(SOURCE_6K + "实际营业利润率 = 该季 6-K 合并损益表的营业利益 ÷ 净销售额 D；"
                   "偏离为实际值减指引中值的自算值。"),
        extra_note=(
            "这一条的柱<b>全部为正</b>，与 Exhibit {EX_OM} 的「没有一季落回区间内」是同一件事的"
            "两种说法 —— 区间图已经饱和（每季都超上限，看不出多少），要读幅度只能看这张。"
            + FX_SHARED.replace("毛利率指引", "营业利润率指引")
        ),
    )

    # ── What the beat is made of ──────────────────────────────────────────────
    operating_leg = [
        (actual[quarter] * actual_fx[quarter] / (midpoint[quarter] * guide_fx[quarter]) - 1) * 100
        for quarter in window
    ]
    fx_leg = [(guide_fx[quarter] / actual_fx[quarter] - 1) * 100 for quarter in window]
    opposed = [
        quarter for quarter, one, two in zip(window, operating_leg, fx_leg) if one * two < 0
    ]
    flipped = [
        quarter for quarter, one in zip(window, operating_leg) if one * beats[quarter] < 0
    ]
    fx_dominant = [
        quarter for quarter, one, two in zip(window, operating_leg, fx_leg) if abs(two) > abs(one)
    ]
    headwind = sum(1 for value in fx_leg if value < 0)
    legs_chart = {
        "ref": "EX_LEGS",
        "kind": "grouped_bars",
        "title": (
            f"把收入超额拆成两条腿：{len(window)} 季里 {len(opposed)} 季方向相反，"
            + (
                f"{'、'.join(flipped)} 一季美元 beat 而新台币 miss"
                if len(flipped) == 1
                else f"{len(flipped)} 季两个口径给出相反结论"
            )
        ),
        "xlabels": [month_label(quarter_end_month(quarter)) for quarter in window],
        "xrot": 90,
        "groups": [
            {"name": "新台币经营超额", "color": "NAVY", "values": rounded(operating_leg)},
            {"name": "汇率腿（假设 vs 实际）", "color": "GOLD", "values": rounded(fx_leg)},
        ],
        # 28 bars in one card cannot carry 28 labels without overlapping; the
        # numbers live one click away in this card's own table view.
        "bar_labels": False,
        "fmt": "pp1",
        "label_fmt": "pp1",
        "ylab": "pp",
        "note": (
            "这是 Exhibit {EX_MIDPOINT} 那根柱的拆解，不是新数据：公司在业绩会上同时给出收入区间和"
            "<b>假设汇率</b>，季报又按当季<b>实际汇率</b>折出美元收入，所以美元偏离恰好等于"
            "两项<b>相乘</b>（不是相加）—— 深蓝是新台币经营超额，金色是假设汇率相对实际汇率的差。"
            f"{len(window)} 季里 {len(opposed)} 季两条腿方向相反，但只有 {len(fx_dominant)} 季"
            "汇率腿盖过经营腿"
            + (
                f"（{flipped[0]}：美元口径 {beats[flipped[0]]:+.1f}%、新台币经营 "
                f"{operating_leg[window.index(flipped[0])]:+.2f}pp，整个超额来自假设 "
                f"{guide_fx[flipped[0]]:.1f} 而实际 {actual_fx[flipped[0]]:.3f}）"
                if flipped
                else ""
            )
            + f"；其余 {headwind} 季汇率是<b>逆风</b>，美元口径反而低估了经营超额。"
        ),
        "src_extra": SOURCE_6K + "两条腿均为自算，原值见核对表。",
    }

    # 按指标分组（用户 2026-08 定）：一个指标的「区间 → 偏离」连着读完再换下一个，
    # 收入那条后面直接跟它专属的汇率拆解。跨指标的对照靠图注点名，不靠版面相邻 ——
    # 营业利润率那两张的图注各自写明了与另外两条指引的差别。
    charts = [
        revenue_band, midpoint_chart, legs_chart,
        margin_band, gm_midpoint_chart,
        operating_band, om_midpoint_chart,
    ]

    table = {
        "title": f"指引兑现全表（{len(quarters)} 季）：三项指引区间、汇率假设与超额分解",
        "headers": ["期间", "收入指引", "实际收入", "较中值",
                    "毛利率指引", "实际毛利率", "营业利润率指引", "实际营业利润率",
                    "假设汇率", "实际汇率", "经营超额 D", "汇率腿 D"],
        "rows": [],
    }
    for index, quarter in enumerate(quarters):
        reported = actual[quarter]
        realised = actual_fx[quarter]
        gm = guide["gross_margin_actual_pct"][index]
        om = guide["operating_margin_actual_pct"][index]
        derived = reported is not None and realised is not None
        table["rows"].append([
            quarter,
            f"US${low[index]:.1f}–{high[index]:.1f}B",
            f"US${reported:.2f}B" if reported is not None else "—",
            f"{beats[quarter]:+.2f}% D" if reported is not None else "—",
            f"{guide['gross_margin_guide_low_pct'][index]:.1f}–"
            f"{guide['gross_margin_guide_high_pct'][index]:.1f}%",
            f"{gm:.2f}% D" if gm is not None else "—",
            f"{guide['operating_margin_guide_low_pct'][index]:.1f}–"
            f"{guide['operating_margin_guide_high_pct'][index]:.1f}%",
            f"{om:.2f}% D" if om is not None else "—",
            f"{guide_fx[quarter]:.1f}",
            f"{realised:.3f}" if realised is not None else "—",
            f"{(reported * realised / (midpoint[quarter] * guide_fx[quarter]) - 1) * 100:+.2f}pp D"
            if derived else "—",
            f"{(guide_fx[quarter] / realised - 1) * 100:+.2f}pp D" if derived else "—",
        ])

    return charts, table




def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    labels = [compact_period(period) for period in periods]
    financials = staging["financials"]
    technology = staging["technology_mix_pct"]
    platform = staging["platform_mix_pct"]
    cash = staging["cash_flow_ntd_bn"]
    working = staging["working_capital_days"]
    guide_history = staging["revenue_guidance_history_usd_bn"]
    snapshot = staging["current_snapshot"]
    guidance = staging["guidance"]
    consensus = staging["market_expectation"]
    net_income_bridge = staging["net_income_bridge"]
    capex_guide = staging["capex_guidance_history"]
    delivery = staging["q2_guidance_delivery"]
    closure = staging["followup_closure"]
    next_kpi = staging["next_kpi"]

    source = (
        'Source: <a href="https://investor.tsmc.com/english/quarterly-results/2026/q2" '
        'rel="noopener">TSMC Investor Relations</a>（2Q26 earnings release、'
        'management report 与 earnings conference）。'
    )

    # Implied ASP is the cheapest honest volume/price split available: both
    # inputs are reported every quarter, and it separates "more wafers" from
    # "richer wafers" without assuming anything about node pricing.
    shipments = financials["wafer_shipments_kpcs_12in_equiv"]
    asp = [
        financials["revenue_usd_bn"][index] * 1_000_000 / shipments[index]
        for index in range(len(periods))
    ]

    q3_midpoint = sum(guidance["q3_new"]["revenue_usd_bn"]) / 2
    q3_midpoint_growth = pct_change(q3_midpoint, guidance["q2_actual"]["revenue_usd_bn"])
    q3_gm_midpoint = sum(guidance["q3_new"]["gross_margin_pct"]) / 2
    capex_guide_mid = [
        (low + high) / 2
        for low, high in zip(capex_guide["low_usd_bn"], capex_guide["high_usd_bn"])
    ]
    revenue_ntd_yoy = pct_change(snapshot["revenue_ntd_bn"][0], snapshot["revenue_ntd_bn"][2])
    capex_ntd_yoy = pct_change(
        snapshot["capital_expenditures_ntd_bn"][0], snapshot["capital_expenditures_ntd_bn"][2]
    )
    shipment_qoq = pct_change(shipments[-1], shipments[-2])
    asp_qoq = pct_change(asp[-1], asp[-2])
    core_beat = pct_change(net_income_bridge["values_ntd_bn"][2], consensus["net_income_ntd_bn"])
    headline_beat = pct_change(net_income_bridge["values_ntd_bn"][0], consensus["net_income_ntd_bn"])
    gm_floor = guidance["long_term_gross_margin_floor_pct"]

    # US-dollar CapEx carries twelve quarters so its y/y is populated from the
    # first column, and both sides of the intensity ratio stay in one currency.
    capex_usd_all = staging["capital_expenditures_usd_bn"]["values"]
    capex_usd = capex_usd_all[-len(periods):]
    capex_usd_yoy = [
        (capex_usd_all[index] / capex_usd_all[index - 4] - 1) * 100
        for index in range(len(capex_usd_all) - len(periods), len(capex_usd_all))
    ]
    capex_intensity_usd = [
        capex / revenue * 100
        for capex, revenue in zip(capex_usd, financials["revenue_usd_bn"])
    ]

    # ── The four routine charts run on the ten-year record, not the eight ─────
    # Eight quarters cannot show whether a mix shift is a trend or a wobble, and
    # for capital intensity eight quarters is barely one build cycle. Everything
    # below is company-reported per quarter; see long_history.provenance for the
    # three disciplines that keep it honest (no platform back-cast before 2018,
    # no derived days, no quoting of TSMC's own "advanced" aggregate).
    long = staging["long_history"]
    long_labels = [quarter_label(quarter) for quarter in long["quarters"]]
    long_tech = long["technology_mix_pct"]
    long_platform = long["platform_mix_pct"]
    long_working = long["working_capital_days"]
    long_capex = long["capital_intensity"]
    # One x label per year: 42 quarterly labels at 90 degrees turn the axis into
    # a hairbrush, and the reader only ever navigates this axis by year.
    LONG_STEP = 4
    long_intensity = [
        capex / revenue * 100
        for capex, revenue in zip(long_capex["capex_usd_bn"], long_capex["revenue_usd_bn"])
    ]
    # Platform gets its own shorter axis rather than eight blank quarters on the
    # left: TSMC did not report HPC before 2019Q1 and only ever restated 2018.
    platform_from = leading_gap(long_platform["hpc"])
    platform_labels = long_labels[platform_from:]
    node_birth = long["node_first_reported"]
    node_first_real = long["node_first_nonzero"]

    # CapEx is reported in NT$ but tracked against a US$ line, so the threshold
    # is converted at the quarter's own realised rate and marked as derived.
    capex_threshold_ntd = round(19.0 * guidance["q2_actual"]["usd_ntd"], 1)
    tracked = {
        "毛利率": (labels, financials["gross_margin_pct"], "pct1", "毛利率", "毛利率", None),
        "库存天数": (labels, working["inventory_days"], "f0", "天", "库存天数", None),
        "HPC 占比（集中度）": (labels, platform["hpc"], "pct0", "净收入占比", "HPC 占比", None),
        "2nm 占晶圆收入": (labels, technology["2nm"], "pct0", "晶圆收入占比", "2nm 占比", None),
        "单季 CapEx": (
            labels, cash["capital_expenditures"], "f0c", "NT$B", "单季 CapEx", capex_threshold_ntd,
        ),
    }

    def tracking_charts(entries, value_key, threshold_label, headline) -> list[dict]:
        charts = []
        for entry in entries:
            metric = entry["metric"]
            if metric not in tracked:
                continue
            xlabels, values, fmt, ylab, actual_name, override = tracked[metric]
            side = "上方" if entry["direction"] == "up" else "下方"
            threshold = entry["threshold"] if override is None else override
            converted = (
                ""
                if override is None
                else f"（US${entry['threshold']:.0f}B 按本季实际汇率 {guidance['q2_actual']['usd_ntd']} 折为 NT${override:,.1f}B D）"
            )
            charts.append(threshold_exhibit(
                headline(entry),
                xlabels,
                values,
                threshold,
                fmt=fmt,
                ylab=ylab,
                actual_name=actual_name,
                threshold_name=f"{threshold_label}（安全侧在{side}）",
                note=(
                    f"阈值 {unit_text(entry['unit'], entry['threshold'])}{converted}，"
                    f"当前 {unit_text(entry['unit'], entry[value_key])}，"
                    f"余量 {headroom(entry['direction'], entry['threshold'], entry[value_key]):+.1f}%。"
                ),
                src_extra=(
                    "实际值来自各季 earnings release / management report；"
                    "阈值为本地研究设定，不是公司指引。"
                ),
            ))
        return charts

    built = [
        {
            "kind": "bars_labeled",
            "title": "上季 12 条待验证问题：3 条已验证、1 条被证伪、4 条仍未披露",
            "xlabels": closure["labels"],
            "values": closure["counts"],
            "legend": "问题条数",
            "fmt": "f0",
            "yfmt": "f0",
            "label_fmt": "f0",
            "ylab": "条",
            "note": (
                "被证伪的是库存天数——上季判断会回落到 75–78 天，实际升到 87 天；"
                "仍未披露的四条集中在节点毛利率与长期目标上修。"
            ),
            "src_extra": "问题清单来自上季本地分析稿的 follow-up；验证结果依据 2Q26 earnings conference 与 management report。",
        },
        {
            "kind": "diverging_bars",
            "title": "Q2 全线优于自身指引中值，只有汇率是逆风",
            "xlabels": [item["metric"] for item in delivery],
            "values": [item["value"] for item in delivery],
            "legend": "优于指引中值的幅度",
            "positive_label": "优于指引",
            "negative_label": "逊于指引",
            "fmt": "f1",
            "yfmt": "f1",
            "label_fmt": "f1",
            "ylab": "% 或 pp",
            "zero_line": True,
            "note": (
                "毛利率与营业利润率都超出指引区间上限，且是在新台币较汇率假设小幅升值的逆风下做到的。"
            ),
            "src_extra": (
                "收入与汇率为百分比，毛利率 / 营业利润率 / 税率为百分点，两类单位并列于同一轴上，"
                "只用于比较方向与相对幅度；原值见核对表。"
            ),
        },
        {
            "kind": "gs_bar",
            "title": "收入 US$40.20B 落指引上端，全年增速指引从 30%+ 上调到略高于 40%",
            "xlabels": labels,
            "values": financials["revenue_usd_bn"],
            "legend": "季度收入",
            "fmt": "usd1",
            "yfmt": "usd1",
            "label_fmt": "usd1",
            "ylab": "US$B",
            "ylab2": "同比增速",
            "yoy": {
                "name": "收入 YoY (RHS)",
                "values": financials["revenue_yoy_pct"],
                "color": "GREEN",
                "yfmt": "pct1",
            },
            "note": (
                f"环比 +12.0%、同比 +33.7%，较市场预期 US${consensus['revenue_usd_bn']:.2f}B 高 "
                f"{pct_change(financials['revenue_usd_bn'][-1], consensus['revenue_usd_bn']):.1f}%；"
                f"Q3 指引中值 US${q3_midpoint:.1f}B，环比 {signed(q3_midpoint_growth)}，不减速。"
            ),
            "src_extra": "美元收入与同比来自各季 earnings release；市场预期为财报前一致预期，不具名。",
        },
        {
            "kind": "gs_bar",
            "title": f"环比 +12.0% 里约三分之二来自价与结构：出货仅 {signed(shipment_qoq)}，隐含 ASP {signed(asp_qoq)}",
            "xlabels": labels,
            "values": shipments,
            "legend": "晶圆出货（12 吋等值）",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "千片",
            "ylab2": "隐含 ASP（美元 / 片）",
            "yoy": {
                "name": "隐含 ASP（美元/片，RHS） D",
                "values": asp,
                "color": "GOLD",
                "yfmt": "f0c",
            },
            "note": (
                f"隐含 ASP = 季度美元收入 / 晶圆出货，Q2 为 ${asp[-1]:,.0f}/片；"
                "抬价的是 2nm 首季贡献 3%、3nm 占比 +5pp 与 HPC mix，不是单纯提价。"
            ),
            "src_extra": (
                "出货量与美元收入来自各季 earnings release / management report；隐含 ASP 为两者相除的自算值，"
                "不是公司披露的定价指标，也不区分制程与封装口径。"
            ),
        },
        {
            "kind": "lines",
            "title": "毛利率 67.7% 超指引上限，但 Q3 指引中值已降到 66%",
            "ref": "EX_MARGIN_LEVEL",
            "xlabels": labels,
            "series": [
                {"name": "毛利率", "values": financials["gross_margin_pct"], "color": "NAVY"},
                {"name": "营业利润率", "values": financials["operating_margin_pct"], "color": "MBLUE"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "end_label": True,
            "ylab": "利润率",
            "note": (
                f"管理层首次量化 2H26 的 N2 稀释 3–4pp，叠加海外厂后期 3–4pp；"
                f"Q3 指引中值 {q3_gm_midpoint:.1f}%，较本季 -1.7pp。67.7% 大概率是本周期顶点。"
                "本图画的是水平，逐季指引区间与兑现记录见 Exhibit {EX_GM}。"
            ),
            "src_extra": "利润率与指引来自 TSMC earnings release；稀释幅度为管理层在电话会上的量化口径。",
        },
        {
            "kind": "bars_labeled",
            "title": "FY2026 CapEx 预算半年内两次上调，中点从 US$54B 抬到 US$62B",
            "xlabels": capex_guide["calls"],
            "values": capex_guide_mid,
            "legend": "FY2026 CapEx 指引中点",
            "fmt": "usd0",
            "yfmt": "usd0",
            "label_fmt": "usd0",
            "ylab": "US$B",
            "note": (
                f"新台币口径下本季 CapEx 同比 {signed(capex_ntd_yoy)}、收入同比 {signed(revenue_ntd_yoy)}；"
                "两条增速的八季美元口径对照见下一节。"
            ),
            "src_extra": (
                "三次口径依次为 1 月 US$52–56B、4 月 closer to US$56B、7 月 US$60–64B；"
                "同比增速为新台币口径自算，避免与全年美元预算混用。"
            ),
        },
        {
            "kind": "bars_labeled",
            "title": f"净利大幅超预期，但剔除 VIS 一次性后核心 beat 只有 {core_beat:+.1f}%",
            "xlabels": net_income_bridge["labels"],
            "values": net_income_bridge["values_ntd_bn"],
            "legend": "净利润",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "NT$B",
            "note": (
                f"报告净利较市场预期高 {headline_beat:+.1f}%，但处置世界先进股份与保留股份重估的"
                f"税前一次性收益 NT$63.20B 解释了其中绝大部分；真正干净的超预期在收入与毛利率。"
                "本图是净利的金额桥，各项相对市场预期的百分比见 Exhibit {EX_EXPECTATION}。"
            ),
            "src_extra": (
                "报告净利与 VIS 相关收益来自 2Q26 management report；核心净利为两者相减的自算值（未做税务调整），"
                "市场预期为财报前一致预期，不具名。"
            ),
        },
        {
            "kind": "grouped_bars",
            "title": "CapEx 环比 +41%，自由现金流反而下降 17.5%",
            "xlabels": labels,
            "groups": [
                {"name": "经营现金流", "values": cash["operating_cash_flow"], "color": "BLUE"},
                {"name": "资本开支", "values": cash["capital_expenditures"], "color": "NAVY"},
                {"name": "自由现金流 D", "values": cash["free_cash_flow"], "color": "MBLUE"},
            ],
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "NT$B",
            "bar_labels": False,
            "note": (
                "资本强度从 30.9% 跳到 39.0%；股息年化 NT$622B，本年自由现金流仍可覆盖约两倍，"
                "现金流压缩暂未威胁股东回报。"
            ),
            "src_extra": "季度新台币现金流口径；FCF = 经营现金流 − 现金支付资本开支，按 TSMC 定义复算。",
        },
        headroom_exhibit(
            "下季 6 条量化阈值：2nm 占比是唯一需要大幅上行才能达标的一条",
            next_kpi["quantified"],
            "current",
            (
                "正值 = 仍在安全侧。2nm 当前 3%，而 Q3 的「steep ramp」需要至少 5%，"
                "是唯一明显在阈值之下的指标；库存天数离 90 天的警戒只剩 3.3%。"
            ),
            src_extra=(
                "阈值为本地研究设定，不是公司指引；当前值为 Q2 2026 实际。"
                "另有 4 条需等披露才能判定（Q3 实际收入、2027 CapEx 指引、长期毛利率目标、Smartphone 连续负增长）。"
            ),
        ),
        {
            "kind": "lines",
            "title": (
                f"十年制程迁移：7nm 及以下从 0% 升到 "
                f"{long_tech['advanced_7nm_and_below'][-1]}%，2nm 本季首次单列为 "
                f"{long_tech['2nm'][-1]}%"
            ),
            "xlabels": long_labels,
            "xstep": LONG_STEP,
            "series": [
                {"name": "2nm", "values": long_tech["2nm"], "color": "GOLD"},
                {"name": "3nm", "values": long_tech["3nm"], "color": "NAVY"},
                {"name": "5nm", "values": long_tech["5nm"], "color": "MBLUE"},
                {"name": "7nm", "values": long_tech["7nm"], "color": "GRAY"},
                {"name": "7nm 及以下 D", "values": long_tech["advanced_7nm_and_below"],
                 "color": "GREEN"},
            ],
            "fmt": "pct0",
            "yfmt": "pct0",
            "label_fmt": "pct0",
            "zero_base": True,
            "end_label": True,
            "ylab": "晶圆收入占比",
            "note": (
                "<b>每条线从该节点第一次出现在公司表里的那一季起画，之前是空的 —— 那不是缺数据，"
                "是当时表上根本没有这一行</b>（起始季 / 首次非零季）："
                + "、".join(
                    f"{node} {quarter_label(node_birth[node])} / "
                    f"{quarter_label(node_first_real[node])}"
                    for node in node_birth
                )
                + "。两个日期不同，是因为新节点常先以公司自己印的 0% 出现在后续报告的"
                "比较列里，几个季度后才真正放量。之后某季若该行没印出来，表示舍入到 0.5% 以下，"
                "按 0 计（依据是该季印出来的各行仍合计 100%）。"
                "<b>绿线「7nm 及以下」是本页自己把印出来的 2/3/5/7nm 四行相加</b>，"
                "不是公司披露的 advanced technologies 口径 —— 那个口径 2019Q1 从「28nm 及以下」"
                "改成「16nm 及以下」、2021Q1 再改成「7nm 及以下」，且从未重述，直接连起来会在"
                "这两处砸出纯定义性的假悬崖（2021Q1 报出来是 62%→49%，同口径其实是微升）。"
                "自算值与公司口径在 2021Q1 起的 22 个季度逐季相等。"
            ),
            "src_extra": (
                "制程组合分母为 total wafer revenue，口径十年未变；逐季读自各季 "
                "quarterly management report 的 Wafer Revenue by Technology 表。"
            ),
        },
        {
            "kind": "lines",
            "title": (
                f"HPC 从 {long_platform['hpc'][platform_from]}% 升到 "
                f"{long_platform['hpc'][-1]}%，智能手机从 "
                f"{long_platform['smartphone'][platform_from]}% 降到 "
                f"{long_platform['smartphone'][-1]}%"
            ),
            "xlabels": platform_labels,
            "xstep": LONG_STEP,
            "series": [
                {"name": "HPC", "values": long_platform["hpc"][platform_from:], "color": "NAVY"},
                {"name": "Smartphone",
                 "values": long_platform["smartphone"][platform_from:], "color": "MBLUE"},
            ],
            "fmt": "pct0",
            "yfmt": "pct0",
            "label_fmt": "pct0",
            "zero_base": True,
            "end_label": True,
            "ylab": "净收入占比",
            "note": (
                "<b>这条线只能回到 2018Q1，不能到 2016，原因是口径断层不是数据缺失</b>："
                "台积电 2019Q1 才把收入拆分从「按应用」（Communication / Computer / Consumer / "
                "Industrial-Standard）改成「按平台」，<b>在那之前根本没有 HPC 这个类别</b>。"
                "2018 那四季用的是公司自己在 2019 各季报告的去年同期列里给出的重述值，属公司报告值；"
                "2016–2017 公司只发过年度平台数、季度值从未发布。两套类别是交叉分类而非重切"
                "（公司给的映射是「Computer >95% 归 HPC」「Communication 约 2/3 是 Smartphone」"
                "这类 30–60% 的定性区间），拿它换算就是估算，本页不做。"
                "集中度是这条曲线的另一面，HPC 站上 68% 即触发本页的集中度跟踪线。"
            ),
            "src_extra": (
                "平台组合分母为 net revenue，逐季读自各季 quarterly management report 的 "
                "Net Revenue by Platform 表；本页仅接入 HPC 与 Smartphone 两类，"
                "IoT / 汽车 / DCE 尚未接入。"
            ),
        },
        {
            "kind": "lines",
            "title": (
                f"库存天数十年区间 {min(long_working['inventory_days'])}–"
                f"{max(long_working['inventory_days'])} 天，本季 "
                f"{long_working['inventory_days'][-1]} 天；应收天数一路降到 "
                f"{long_working['receivable_days'][-1]} 天"
            ),
            "xlabels": long_labels,
            "xstep": LONG_STEP,
            "series": [
                {"name": "库存天数", "values": long_working["inventory_days"], "color": "NAVY"},
                {"name": "应收天数", "values": long_working["receivable_days"], "color": "MBLUE"},
            ],
            "fmt": "f0",
            "yfmt": "f0",
            "label_fmt": "f0",
            "end_label": True,
            "ylab": "天",
            "note": (
                "本季公司归因于 N2 爬坡备货；若下季 2nm 占比已跳升而库存仍不回落，备货解释即失效。"
                "拉长看，库存天数在 2016–2019 年长期在 40–70 天，2021 年后台阶式抬到 80–99 天，"
                "当前 " + str(long_working["inventory_days"][-1]) + " 天仍在这个高台阶内而非异常值；"
                "应收天数则是单向下行，从 2016 年的 40 天出头降到二十几天。"
                "<b>两条都是公司印在报告里的原值，本页不自己推导</b> —— 实测任何"
                "「余额 ÷ 日均」的公式都复现不出这 42 个季度（最好的一版只精确命中一成），"
                "公司也未公开其天数惯例。"
            ),
            "src_extra": (
                "应收与库存天数逐季读自各季 quarterly management report 的 "
                "「III - 2. Receivable/Inventory Days」表原值。"
            ),
        },
    ]
    financial_table = []
    mix_table = []
    cash_table = []
    guidance_table = []
    for index, period in enumerate(periods):
        financial_table.append([
            period,
            f"US${financials['revenue_usd_bn'][index]:.2f}B",
            f"{financials['revenue_yoy_pct'][index]:.1f}%",
            f"{financials['gross_margin_pct'][index]:.1f}%",
            f"{financials['operating_margin_pct'][index]:.1f}%",
            f"NT${financials['eps_ntd'][index]:.2f}",
            f"{shipments[index] / 1000:.3f}M",
            f"${asp[index]:,.0f} D",
        ])
        # "—" is not a formatting nicety: a node with no row in the company's
        # table is a different fact from a reported 0%, and printing "0%" for it
        # is the thing the mix_notes used to have to apologise for.
        def mix_cell(values: list[float | None]) -> str:
            value = values[index]
            return "—" if value is None else f"{value:.0f}%"

        mix_table.append([
            period,
            mix_cell(technology["2nm"]),
            mix_cell(technology["3nm"]),
            mix_cell(technology["5nm"]),
            mix_cell(technology["7nm"]),
            mix_cell(technology["advanced_7nm_and_below"]),
            mix_cell(platform["hpc"]),
            mix_cell(platform["smartphone"]),
        ])
        cash_table.append([
            period,
            f"NT${cash['operating_cash_flow'][index]:,.2f}B",
            f"NT${cash['capital_expenditures'][index]:,.2f}B",
            f"NT${cash['free_cash_flow'][index]:,.2f}B D",
            f"{working['receivable_days'][index]}天",
            f"{working['inventory_days'][index]}天",
        ])
        midpoint = (guide_history["low"][index] + guide_history["high"][index]) / 2
        guidance_table.append([
            period,
            f"US${guide_history['low'][index]:.1f}–{guide_history['high'][index]:.1f}B",
            f"US${midpoint:.2f}B D",
            f"US${guide_history['actual'][index]:.2f}B",
            f"{signed(pct_change(guide_history['actual'][index], midpoint))} D",
        ])

    guide_rows = [
        [
            "收入（美元）",
            "US$39.0–40.2B",
            "US$40.20B",
            "区间上端",
            "US$44.6–45.8B",
            f"中值 US${q3_midpoint:.1f}B；环比 {signed(q3_midpoint_growth)} D",
        ],
        ["毛利率", "65.5–67.5%", "67.7%", "高于上端 0.2pp D", "65.0–67.0%", "中值环比 -1.7pp D"],
        ["营业利润率", "56.5–58.5%", "60.3%", "高于上端 1.8pp D", "56.0–58.0%", "中值环比 -3.3pp D"],
        ["USD / NTD", "31.7", "31.60", "较假设低 0.3% D", "32.0", "较 Q2 实际高 1.3% D"],
        ["FY2026 美元收入增速", "高于 30%", "—", "上调", "略高于 40%", "公司年度 outlook"],
        ["FY2026 CapEx", "US$52–56B；接近上端", "—", "上调", "US$60–64B", "中值较先前高端锚点 +US$6B D"],
        ["2H26 N2 毛利率稀释", "—", "—", "—", "3–4pp", "管理层量化"],
        ["海外厂毛利率稀释", "—", "—", "—", "初期 2–3pp", "后期扩大至 3–4pp"],
        [
            "长期 through-cycle 毛利率",
            f"{gm_floor}% 及以上",
            "67.7%",
            f"高出 {financials['gross_margin_pct'][-1] - gm_floor:.1f}pp D",
            f"{gm_floor}% 及以上",
            "长期目标未上修，也未下修",
        ],
    ]

    inventory_expectation = threshold_exhibit(
        "上季判断库存回落到 75–78 天，实际升到 87 天（被证伪）",
        labels,
        working["inventory_days"],
        78.0,
        fmt="f0",
        ylab="天",
        actual_name="库存天数",
        threshold_name="上季预期上沿 78 天",
        note=(
            "管理层归因于 N2 爬坡备货；这是上季 12 条判断里唯一被明确证伪的一条，"
            "也是本页把 90 天设为下季警戒线的由来。"
        ),
        src_extra="库存天数来自各季 management report；75–78 天为上季本地分析稿的预期区间。",
    )

    intensity_low = min(long_intensity)
    intensity_low_at = long_labels[long_intensity.index(intensity_low)]
    intensity_high = max(long_intensity)
    intensity_high_at = long_labels[long_intensity.index(intensity_high)]
    capex_intensity_chart = {
        "kind": "gs_line",
        "title": (
            f"资本强度十年从 {long_intensity[0]:.1f}% 升到 {long_intensity[-1]:.1f}%，"
            f"期间峰值 {intensity_high:.1f}%（{intensity_high_at}）"
        ),
        "xlabels": long_labels,
        "xstep": LONG_STEP,
        "values": [round(value, 6) for value in long_intensity],
        "legend": "CapEx / 收入（美元口径）",
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "占收入比",
        "note": (
            f"本季 {long_intensity[-1]:.1f}%，较上季 {long_intensity[-2]:.1f}% 跳升。"
            f"十年区间 {intensity_low:.1f}%（{intensity_low_at}）到 "
            f"{intensity_high:.1f}%（{intensity_high_at}）—— <b>本季并不是历史高位</b>，2021 年那轮扩产把单季资本支出打到收入的三分之二以上，八季的窗口看不到这件事。"
            "单季比值天然比年度口径抖，因为 CapEx 按付款节奏落账、收入按季确认，"
            "看趋势要顺着几个季度读，不要盯单点。"
            "这条线与 GOOGL 页同口径，可直接对照上下游的资本强度。"
        ),
        "src_extra": (
            "美元 CapEx 逐季读自各季 quarterly management report 的「V. Capital Expenditures」"
            "美元表（1Q16 的单位是 US$ millions，其余季为 billions），美元收入来自各季 "
            "earnings release 原句；比值为自算，两侧同币种，不与新台币现金流口径混用。"
        ),
    }

    growth_crossover_chart = {
        "kind": "lines",
        "title": (
            f"CapEx 增速 {capex_usd_yoy[-1]:+.0f}% 反超收入增速 "
            f"{financials['revenue_yoy_pct'][-1]:+.0f}%"
        ),
        "xlabels": labels,
        "series": [
            {"name": "收入 YoY", "values": financials["revenue_yoy_pct"], "color": "NAVY"},
            {"name": "CapEx YoY", "values": capex_usd_yoy, "color": "RED"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "同比增速",
        "note": (
            "上季管理层称「收入增速快于 CapEx 增速」；本季两条线交叉，这是股价的直接压制项。"
            "两条都是美元口径，不含汇率错配。"
        ),
        "src_extra": (
            "收入同比为公司披露，CapEx 同比按各季 earnings conference 的美元 CapEx 自算；"
            "同比需要上年同期，故序列多带四个季度，只展示最近八季。"
        ),
    }

    # Section one now carries the whole "did the quarter clear the bar" story in
    # one place: the company's own three guided metrics over the full guided
    # record, then the market's bar, then the follow-up list it was supposed to
    # settle. The eight-quarter revenue range band that used to sit here was
    # removed -- the fifteen-quarter one below is the same chart over a longer
    # window, and two of them side by side said nothing the longer one did not.
    delivery_charts, delivery_table = guidance_delivery_charts(staging)
    settled_charts = (
        built[0:2] + [expectation_chart(staging)] + delivery_charts + [inventory_expectation]
    )
    highlights = built[2:8] + [growth_crossover_chart]
    next_charts = [built[8]] + tracking_charts(
        next_kpi["quantified"],
        "current",
        "下季阈值",
        lambda entry: (
            f"{entry['metric']}：下季阈值 {unit_text(entry['unit'], entry['threshold'])}，"
            f"当前 {unit_text(entry['unit'], entry['current'])}"
        ),
    )
    routine = built[9:] + [capex_intensity_chart]

    exhibits = resolve_exhibit_refs(
        number_exhibits(settled_charts + highlights + next_charts + routine)
    )
    # Slice by cumulative length rather than by hand-written indices: the
    # sections are the same list, cut in order, so inserting a chart into one of
    # them cannot silently move a chart into its neighbour.
    grouped = []
    cursor = 0
    for group in (settled_charts, highlights, next_charts, routine):
        grouped.append(exhibits[cursor:cursor + len(group)])
        cursor += len(group)
    settled_ex, highlight_ex, next_ex, routine_ex = grouped
    next_table_number = len(exhibits) + 2

    tables = [
        {
            # Reference detail, not a lead module: the decision-relevant parts of
            # guidance are already in the settled and highlight sections.
            "n": next_table_number,
            "title": "Q2 兑现、Q3 指引与全年 outlook",
            "headers": ["指标", "Q2 原指引", "Q2 实际", "兑现", "Q3 / FY26 新口径", "变化 / 备注"],
            "rows": guide_rows,
        },
        threshold_table(
            next_table_number + 1,
            "下季阈值与当前值（原单位）",
            next_kpi["quantified"],
            "current",
            "当前值",
        ),
        {
            "n": next_table_number + 2,
            "title": "八季度财务、出货与隐含 ASP",
            "headers": ["期间", "收入", "收入 YoY", "毛利率", "营业利润率", "稀释 EPS", "晶圆出货", "隐含 ASP"],
            "rows": financial_table,
        },
        {
            "n": next_table_number + 3,
            "title": "八季度制程与平台收入组合",
            "headers": ["期间", "2nm", "3nm", "5nm", "7nm", "≤7nm", "HPC", "Smartphone"],
            "rows": mix_table,
        },
        {
            "n": next_table_number + 4,
            "title": "八季度现金流与营运资金",
            "headers": ["期间", "经营现金流", "资本开支", "自由现金流", "应收天数", "库存天数"],
            "rows": cash_table,
        },
        {
            "n": next_table_number + 5,
            "title": "八季度美元收入指引兑现",
            "headers": ["期间", "公司指引", "中值", "实际", "较中值"],
            "rows": guidance_table,
        },
        {**delivery_table, "n": next_table_number + 6},
        ai_capex_cycle_table(next_table_number + 7),
    ]

    return {
        "schema_version": "quarterly-dashboard/tsm-v3",
        "page": {"slug": "tsm", "language": "zh-CN"},
        "company": {
            "ticker": "TSM",
            "name": "TSMC",
            "group": "semiconductor_ai",
            "accounting_standard": "TIFRS",
        },
        "latest": {
            "disclosed_period_label": "Q2 2026",
            "full_financial_period_label": "Q2 2026",
            "period_end": "2026-06-30",
            "release_date": "2026-07-16",
            "analysis_date": "2026-07-18",
            "audit_status": "unaudited",
            "status": "history_ready",
        },
        "tracker": "Watchlist Quarterly Tracker · TSM",
        "title": "TSMC (TSM)：Q2 2026 季报仪表盘",
        "subtitle": "截至 2026-06-30 · 发布 2026-07-16 · TIFRS · 未审计 · 收入为美元，现金流为新台币，另有注明除外",
        "headline": (
            "基本面全线更强——收入落指引上端、毛利率 67.7% 超上限、全年增速指引由 30%+ 上调到略高于 40%；"
            f"但股价当日 {consensus['post_earnings_price_change_pct']}%，市场卖的是资本强度："
            f"全年 CapEx 上调至 US$60–64B，新台币口径 CapEx 同比 {signed(capex_ntd_yoy)} 已快于收入的 {signed(revenue_ntd_yoy)}。"
        ),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>亮点</span><b>收入与毛利率双超指引上限</b>'
            '<p>US$40.20B 落区间上端；GM 67.7%、OM 60.3%，均超上限。</p></article>'
            '<article><span>结构</span><b>增长约三分之二来自价与 mix</b>'
            '<p>出货环比 +3.9%，隐含 ASP +7.8%；2nm 首季即贡献 3%。</p></article>'
            '<article><span>存疑</span><b>净利大 beat 含一次性</b>'
            f'<p>VIS 税前收益 NT$63.20B；核心净利较预期仅 {core_beat:+.1f}%。</p></article>'
            '</div>'
        ),
        "source": source,
        "source_url": "https://investor.tsmc.com/english/quarterly-results/2026/q2",
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {
                "id": "settled",
                "title": "一、上季跟踪指标兑现了吗",
                "description": (
                    "先看上季留的问题闭环了几条、这一季对公司自己的指引和对市场预期各兑现到什么程度，"
                    "再谈本季。公司每季指引三个数——收入、毛利率、营业利润率——三张图各给一条完整记录，"
                    "最后拆开超额里经营与汇率各占多少。"
                ),
                "exhibits": settled_ex,
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": "收入与指引、量价拆分、毛利率拐点、资本开支上调，以及净利里的一次性成分。",
                "exhibits": highlight_ex,
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": "当前值离下季阈值还有多远，统一用「距阈值余量」口径。",
                "exhibits": next_ex,
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": "TSM 专属的常规序列：制程世代迁移、平台结构与营运资金。",
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            f"Exhibit {next_ex[0]['n']} 与其后各图的阈值是本地研究设定，不是公司指引，也不构成评级或投资建议；「距阈值余量」统一为正值代表安全侧。",
            f"第一节的指引兑现三张图（Exhibit {settled_ex[3]['n']}／{settled_ex[4]['n']}／{settled_ex[5]['n']}）用的是同一批 6-K：每份法说会 6-K 同时给出下一季的收入区间、毛利率区间、营业利润率区间与假设汇率，实际值取自随后一季 6-K 的合并损益表；毛利率与营业利润率由毛利、营业利益分别除以净销售额得出，与本页 financials 的八季逐季对到小数点后一位。",
            f"Exhibit {settled_ex[2]['n']} 的「核心」口径是报告净利减 VIS 税前一次性收益的算术差，未做税务调整；核心 EPS 按核心 / 报告净利之比折算报告 EPS。两者都不是公司定义的调整后指标，只用于回答「这个季度是不是真的超预期」。",
            "本页不接入月度营收公告，全页维持季度更新节奏。",
            "本页只发布公司披露值、可复算的简单派生值，以及明确标注的市场预期；D 标记代表 Derived / 自算。",
            "市场预期一律标注为「市场预期」并给出取数时点，不写卖方机构名，也不发布评级、目标价或估值。",
            "隐含 ASP 为季度美元收入除以晶圆出货，仅用于量价拆分，不等同任何制程或封装的实际定价。",
            "核心净利为报告净利减 VIS 相关税前收益的算术差，未做税务调整，也不是公司定义的调整后利润。",
            "自由现金流按 TSMC 口径，以经营现金流减季度现金支付资本开支复算；不是利润表 non-GAAP 指标。",
            "收入趋势采用美元口径，现金流采用新台币口径；季度现金支付 CapEx 不与全年美元 CapEx 预算相加。",
            "制程占比的分母为晶圆收入，平台占比的分母为净收入；两组 mix 不可直接相加。",
            "本页已知未接入：ROE、折旧、R&D / SG&A 费用线、IoT / 汽车 / DCE 平台占比、地区与客户类型组合，以及收入以外的指引兑现历史（毛利率 / 营业利润率 / 税率的逐季指引区间尚未录入）。",
            "电话会文字稿仅链接 TSMC 官方 IR 托管版本，公开仓不复制原件或逐字内容。",
        ],
        "footer": "TSM quarterly results · 数据来自 TSMC 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "tsm.js"), payload, "tsm")
    shell_dir = ROOT / "tsm"
    shell_dir.mkdir(exist_ok=True)
    # Rendered here, not at import: the shell stamps the payload's content
    # hash into its <script src>, so it has to be built after write_dash.
    (shell_dir / "index.html").write_text(
        render_shell("TSM", "tsm"), encoding="utf-8")
    # Counted, not typed: this line claimed "13 charts in 4 sections" while the
    # page had grown to 21.
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(
        f"TSM page: {charts} charts in {len(payload['sections'])} sections "
        f"+ {len(payload['tables'])} audit tables"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
