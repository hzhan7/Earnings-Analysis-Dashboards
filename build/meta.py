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

Rolling the page to a new quarter edits `series/meta.json` and nothing else.
Every figure, period label, count and record claim is computed here from the
series; a sentence such as "the lower bound has never been tested", "the only
time" or "for the first time" is printed only while the series makes it true.
What belongs to one quarter -- the settlement of last quarter's thresholds and
questions, the new thresholds, the market's expectation, the call's outlook
wording, the quarter's one-off items and the rows of the quality table the
series does not carry -- lives in blocks stamped with that quarter and is read
through `board.stamped_block`: a block stamped with another quarter stops the
build, a missing one leaves its part of the page out.  The three guidance
records (quarterly revenue, annual expenses, annual capex) are read from
`quarterly_guidance_history` alone; the page no longer keeps its own copies.
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import (  # noqa: E402
    ai_capex_cycle_table,
    cn_count,
    cn_ordinal,
    headroom,
    headroom_exhibit,
    latest_block,
    number_exhibits,
    stamped_block,
    threshold_exhibit,
    threshold_table,
    unit_text,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "meta.json"
DATA_DIR = ROOT / "data"

AUDIT_WORDS = {"unaudited": "未审计", "audited": "已审计"}

# The source carries twelve quarters so every displayed quarter has a year-ago
# base; the page shows the last eight.
WINDOW = 8

# The year the capital build-out left its old range; the capital-intensity note
# measures "the previous high" on the record before it. A fact about the past.
BUILD_OUT_FROM = "2023Q1"


def compact_period(period: str) -> str:
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


def shown(values: list) -> list:
    return values[-WINDOW:]


def quarter_label(quarter: str) -> str:
    """``'2016Q1'`` → ``'Q1'16'``, matching the eight-quarter labels."""
    year, number = quarter.split("Q")
    return f"Q{number}'{year[-2:]}"


def quarter_key(period: str) -> str:
    """``'Q2 2026'`` → ``'2026Q2'``."""
    quarter, year = period.split()
    return f"{year}{quarter}"


def period_of(key: str) -> str:
    """``'2026Q2'`` → ``'Q2 2026'``."""
    return f"{key[4:]} {key[:4]}"


def next_key(key: str) -> str:
    year, quarter = int(key[:4]), int(key[-1])
    return f"{year + (quarter == 4)}Q{1 if quarter == 4 else quarter + 1}"


def call_of(filed: str) -> str:
    """The quarter whose results a release on ``filed`` reported: the last quarter
    that ended before it. Meta reports a month after each quarter closes."""
    day = datetime.date.fromisoformat(filed)
    quarter = (day.month - 1) // 3          # quarters fully ended this year
    year = day.year if quarter else day.year - 1
    return f"Q{quarter or 4} {year}"


def leading_gap(values: list[float | None]) -> int:
    """Index of the first reported value; ``len(values)`` when there is none."""
    return next((i for i, value in enumerate(values) if value is not None), len(values))


def runs(values: list, test) -> list[tuple[int, int]]:
    """Maximal stretches (first, last index) where ``test(value)`` holds; None breaks a run."""
    found, start = [], None
    for index, value in enumerate(values):
        hit = value is not None and test(value)
        if hit and start is None:
            start = index
        if not hit and start is not None:
            found.append((start, index - 1))
            start = None
    if start is not None:
        found.append((start, len(values) - 1))
    return found


def runs_over_holes(values: list, test) -> list[tuple[int, int]]:
    """Like `runs`, but a hole (None) neither breaks nor extends a run: a missing
    fourth-quarter reading between two price-led quarters is not a regime change."""
    known = [(index, value) for index, value in enumerate(values) if value is not None]
    found, start, last = [], None, None
    for index, value in known:
        if test(value):
            if start is None:
                start = index
            last = index
        elif start is not None:
            found.append((start, last))
            start = None
    if start is not None:
        found.append((start, last))
    return found


def spaced(word: str) -> str:
    """「隐含 H2 还要」 but 「隐含余下三季还要」: only Latin tokens get spaces around them."""
    return f" {word} " if word[:1].isascii() else word


def span_text(quarters: list[str], first: int, last: int) -> str:
    return quarters[first] if first == last else f"{quarters[first]}–{quarters[last]}"


# One x label per year: forty-two quarterly labels at 90 degrees turn the axis
# into a hairbrush, and this axis is only ever navigated by year.
LONG_STEP = 4


def guidance_band(quarters: list[str], low: list[float], high: list[float],
                  actual: list[float | None]) -> dict:
    """Meta's own revenue range against what it then reported, quarter by quarter.

    Deliberately local rather than shared with the TSMC page.  TSMC guides three
    numbers and needs a generalised helper; META guides exactly one, and the
    shared version is being rewritten in another session as this is written, so
    depending on its signature would make this page break on someone else's
    unrelated edit.
    """
    finished = [index for index, value in enumerate(actual) if value is not None]
    above = [i for i in finished if actual[i] > high[i]]
    below = [i for i in finished if actual[i] < low[i]]
    inside = len(finished) - len(above) - len(below)
    pending = [quarters[i] for i, value in enumerate(actual) if value is None]
    return {
        "ref": "meta_revenue_band",
        "kind": "range_band",
        "title": (
            f"收入指引兑现：{len(finished)} 个已完结季里 {len(above)} 季超出上限、"
            f"{inside} 季落在区间内，"
            + ("没有一季跌破下限" if not below else f"{len(below)} 季跌破下限")
        ),
        "xlabels": [quarter_label(quarter) for quarter in quarters],
        "xrot": 90,
        "lo": list(low),
        "hi": list(high),
        "actual": list(actual),
        "actual_color": "NAVY",
        "names": {
            "range": "公司收入指引区间",
            "actual": "实际收入",
            "lo": "指引下限（US$B）",
            "hi": "指引上限（US$B）",
        },
        "fmt": "f1",
        "label_fmt": "f1",
        "ylab": "US$B",
        "note": (
            "色块是该季<b>开始前</b>公司在上一季财报里给出的收入区间，菱形是随后报出来的实际值。"
            + (f"<b>下限从未被测试过</b>：{len(finished)} 季里一次都没有跌破，"
               "所以这条区间的下沿不是预测的一端，是公司愿意公开承诺的地板。"
               if not below else
               f"<b>下限被跌破过 {len(below)} 次</b>（"
               + "、".join(quarter_label(quarters[i]) for i in below) + "）。")
            + (f"最后一格 {quarter_label(pending[-1])} 只有指引色块，实际值待披露。"
               if pending else "")
            + "纵轴不自 0 起，但没有任何点被截掉。"
        ),
        "src_extra": (
            "指引区间逐季读自各季财报 8-K 的 EX-99.1 新闻稿「Outlook」段落；"
            "实际收入取同批申报的 XBRL 收入事实。"
        ),
    }


def guidance_deviation(quarters: list[str], low: list[float], high: list[float],
                       actual: list[float | None]) -> dict:
    """How far past the guided midpoint each quarter landed.

    The band chart saturates once a metric has cleared the same bound many times
    running -- it then says the same thing every quarter.  This asks the question
    that still has an answer: by how much, and is that widening or narrowing.
    """
    finished = [index for index, value in enumerate(actual) if value is not None]
    midpoints = [(low[i] + high[i]) / 2 for i in finished]
    deviation = [
        round((actual[i] / mid - 1) * 100, 6) for i, mid in zip(finished, midpoints)
    ]
    above = sum(1 for value in deviation if value > 0)
    biggest = max(deviation, key=abs)
    recent = deviation[-4:]
    recent_mean = sum(recent) / len(recent)
    # The comparison year is the last calendar year the record has in full.
    by_year: dict[str, list[float]] = {}
    for i, value in zip(finished, deviation):
        by_year.setdefault(quarters[i][:4], []).append(value)
    full_years = [year for year, values in by_year.items() if len(values) == 4]
    last_year = max(full_years) if full_years else None
    year_mean = (sum(by_year[last_year]) / 4) if last_year else None
    if year_mean is None:
        trend = ""
    elif recent_mean < year_mean:
        trend = (f"<b>这张图比上面那张多说的一句是「超额在收窄」</b>：最近四季平均 "
                 f"{recent_mean:+.1f}%，低于 {last_year} 全年的水平 —— "
                 "区间照样年年清得掉，但清出来的余量不如从前厚。")
    else:
        trend = (f"最近四季平均 {recent_mean:+.1f}%，不低于 {last_year} 全年的 {year_mean:+.1f}%。")
    return {
        "ref": "meta_revenue_midpoint",
        "kind": "grouped_bars",
        "title": (
            f"收入相对指引中值的偏离：{len(deviation)} 季里 {above} 季为正，"
            f"平均绝对偏离 {sum(abs(v) for v in deviation) / len(deviation):.1f}%"
        ),
        "xlabels": [quarter_label(quarters[i]) for i in finished],
        "xrot": 90,
        "groups": [{
            "name": "实际收入 vs 指引中值",
            "color": "BLUE",
            "values": deviation,
        }],
        "bar_labels": True,
        "fmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "% vs 指引中值",
        "note": (
            "正值 = 高于指引区间的中值；长期为正说明公司指引偏保守，不是一连串意外。"
            f"窗口内最大的一次是 {quarter_label(quarters[finished[deviation.index(biggest)]])} "
            f"的 {biggest:+.1f}%。"
            + trend
        ),
        "src_extra": "指引中值为区间上下限的算术平均（自算）；两条腿均为公司申报值。",
    }


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


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    q = staging["quarterly_usd_m"]
    ads = [total - reality - other for total, reality, other in
           zip(q["revenue_total"], q["reality_labs_revenue"], q["foa_other_revenue"])]
    fcf = (q["operating_cash_flow"][-1] - q["purchases_of_property_and_equipment"][-1]
           - q["finance_lease_principal"][-1])
    return [f"Revenue ${q['revenue_total'][-1] / 1000:.1f}B",
            f"Ads {(ads[-1] / ads[-5] - 1) * 100:+.1f}%",
            f"FCF {'-' if fcf < 0 else ''}${abs(fcf) / 1000:.1f}B"]


def guided_calls(records: list[dict], year: str) -> list[dict]:
    """Every call that guided ``year``, in filing order."""
    return sorted((call for call in records if call["year"] == year), key=lambda call: call["filed"])


def range_text(low: float, high: float) -> str:
    """``130.0, 145.0`` → ``'130–145'``; a fractional bound keeps its decimal."""
    def one(value):
        return f"{value:g}"
    return f"{one(low)}–{one(high)}"


def regional_chart(geography: dict, quarter_revenue: float, period: str) -> dict:
    """The quarter's revenue growth by region, as the 10-Q prints it.

    A one-quarter reading, so it sits with the quarter's other findings rather
    than among the long series.
    """
    growth = geography["user_geography_yoy_pct"]
    order = sorted(range(len(growth)), key=lambda i: -growth[i])
    regions = geography["regions"]
    share = geography["customer_address_current"][0] / quarter_revenue * 100
    address_growth = pct_change(geography["customer_address_current"][0],
                                geography["customer_address_prior_year"][0])
    return {
        "kind": "bars_labeled",
        "title": (f"本季四大区域收入同比：{regions[order[0]]}最快，"
                  f"{regions[order[-2]]}与{regions[order[-1]]}落在后两位"),
        "xlabels": regions,
        "values": growth,
        "legend": "收入同比",
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "同比增速",
        "note": (
            f"{regions[0]}同比 {growth[0]:g}%（公司按用户所在地印的口径）；按收入分解附注的客户所在地口径，"
            f"它占本季收入 {share:.1f}%、同比 {address_growth:.1f}% —— 两个口径不同，本图画前者。"
            + geography.get("management_remark", "")
        ),
        "src_extra": (
            f"区域同比取 {period} 10-Q MD&A「revenue by user geography」一段公司印出的整数百分比；"
            "收入分解附注按客户所在地分区，那张表算出的同比是 "
            + "、".join(f"{pct_change(c, p):.1f}%" for c, p in
                       zip(geography["customer_address_current"], geography["customer_address_prior_year"]))
            + "，口径不同、不混用。公司未按区域披露利润，本页不做区域盈利推断。"
        ),
    }


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    period = periods[-1]
    prev_period, year_ago = periods[-2], periods[-5]
    key = quarter_key(period)
    latest = latest_block(staging, period=period)
    if not any(item["label"] == f"{period} 业绩发布 8-K" for item in staging["sources"]):
        raise ValueError(f"series `sources` has no {period} 业绩发布 8-K: add the quarter's "
                         "release with the roll")

    labels = [compact_period(p) for p in shown(periods)]
    q = staging["quarterly_usd_m"]
    ads = staging["advertising_metrics"]
    closure = stamped_block(staging, "followup_closure", period)
    prior_kpi = stamped_block(staging, "prior_kpi_settlement", period)
    next_kpi = stamped_block(staging, "next_kpi", period)
    consensus = stamped_block(staging, "market_expectation", period)
    outlook = stamped_block(staging, "outlook", period)
    snapshot = stamped_block(staging, "quarter_snapshot", period)
    geography = stamped_block(staging, "quarter_geography", period)
    expense = stamped_block(staging, "quarter_expense_lines_usd_m", period)
    if snapshot is not None and snapshot["columns"] != [period, prev_period, year_ago]:
        raise ValueError(f"series block `quarter_snapshot` columns {snapshot['columns']} are not "
                         f"{[period, prev_period, year_ago]}: re-key them with the roll")
    history = staging["quarterly_guidance_history"]

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

    one_offs = (snapshot or {}).get("one_off_items", [])
    one_off_total = sum(item["usd_m"] for item in one_offs)
    one_off_words = "与 ".join(f"${item['usd_m']:,}M {item['name']}" for item in one_offs)
    one_off_words_named_first = " 与".join(f"{item['name']} ${item['usd_m']:,}M" for item in one_offs)
    adjusted_operating_income = operating_income[-1] + one_off_total

    # ΔOI / ΔRevenue on a year-over-year base. Quarter-over-quarter would be
    # cleaner arithmetic but META's Q4 is seasonally large enough to flip the
    # sign twice a year, which would make the series unreadable.
    adjusted_incremental_margin = (
        (adjusted_operating_income - operating_income[-5])
        / (revenue[-1] - revenue[-5]) * 100
    )

    volume_price_product = [
        ((1 + impressions / 100) * (1 + price / 100) - 1) * 100
        for impressions, price in zip(
            ads["ad_impressions_yoy_pct"], ads["price_per_ad_yoy_pct"]
        )
    ]

    # ── The routine charts run on the ten-year record, not the eight ─────────
    # Everything below is a filed number or the difference of two filed numbers.
    # The cash-flow lines exist only year-to-date in a 10-Q, so each quarter
    # after the first is one year-to-date figure minus the previous one; see
    # long_history.provenance.
    long = staging["long_history"]
    quarters = long["quarters"]
    if quarters[-1] != key:
        raise ValueError(f"long_history ends at {quarters[-1]} but the page is {period}")
    long_labels = [quarter_label(quarter) for quarter in quarters]
    years = len(quarters) // 4
    long_revenue = long["revenue_usd_m"]
    long_depreciation = long["depreciation_and_amortization_usd_m"]
    long_revenue_yoy = yoy(long_revenue)
    long_depreciation_yoy = yoy(long_depreciation)
    yoy_from = leading_gap(long_revenue_yoy)

    # META's own free-cash-flow definition nets finance-lease principal, which
    # is on every cash-flow statement in the record (under its pre-ASC 842 name
    # before 2019) -- see long_history.finance_lease_note.
    long_lease = long["finance_lease_principal_usd_m"]
    long_fcf = [
        None if lease is None else operating - purchases - lease
        for operating, purchases, lease in zip(
            long["operating_cash_flow_usd_m"],
            long["capital_expenditures_usd_m"],
            long_lease,
        )
    ]
    long_ttm_fcf = [
        None if any(value is None for value in long_fcf[index - 3:index + 1])
        else sum(long_fcf[index - 3:index + 1])
        for index in range(len(long_fcf))
    ]
    long_ttm_fcf[:3] = [None] * 3
    ttm_from = leading_gap(long_ttm_fcf)

    # The two segment lines only exist from the quarter META first reported
    # segments; before that the categories did not exist, so the chart carries
    # its own shorter axis rather than twenty blank quarters on the left.
    long_reality = long["reality_labs_revenue_usd_m"]
    long_foa_other = long["foa_other_revenue_usd_m"]
    segment_from = leading_gap(long_reality)

    # The advertising engine, on the ten-year window. The two rate lines have
    # holes -- one per fourth quarter from 2016 through 2020 -- because the 10-K
    # states only the full-year change and the 8-K did not carry the quarterly
    # bullet until 2021Q4. Holes, not interpolation: a line drawn through them
    # would invent readings the company never gave.
    long_advertising = long["advertising_revenue_usd_m"]
    long_advertising_yoy = yoy(long_advertising)
    long_impressions = long["ad_impressions_yoy_pct"]
    long_price = long["price_per_ad_yoy_pct"]
    ad_rate_holes = [
        long_labels[index] for index, value in enumerate(long_impressions) if value is None
    ]

    # Capex on the company's own definition -- purchases of property and
    # equipment plus finance-lease principal -- which is why it needed the lease
    # line backfilled before this chart could run the whole record.
    long_capex = [
        purchases + lease
        for purchases, lease in zip(long["capital_expenditures_usd_m"], long_lease)
    ]
    long_capex_intensity = [
        capex / revenue * 100 for capex, revenue in zip(long_capex, long_revenue)
    ]

    revenue_shown = shown(revenue)
    revenue_yoy = shown(yoy(revenue))
    advertising_yoy = shown(yoy(advertising))
    foa_other_shown = shown(q["foa_other_revenue"])
    foa_other_yoy = shown(yoy(q["foa_other_revenue"]))
    reality_labs_shown = shown(q["reality_labs_revenue"])
    capex_shown = shown(capex_total)
    capex_intensity = [
        capex / total * 100 for capex, total in zip(capex_shown, revenue_shown)
    ]
    fcf_shown = shown(free_cash_flow)
    ttm_fcf = shown(trailing(free_cash_flow))
    depreciation_shown = shown(q["depreciation_and_amortization"])
    depreciation_yoy = shown(yoy(q["depreciation_and_amortization"]))

    # The three guidance records, read from the filed history alone.
    guided_year = key[:4]
    capex_calls = guided_calls(history["capex_guidance_calls"], guided_year)
    expense_calls = guided_calls(history["expense_guidance_calls"], guided_year)
    capex_guide_mid = [(call["low"] + call["high"]) / 2 for call in capex_calls]
    coming = next_key(key)
    q3_low = history["guide_low_usd_bn"][history["quarters"].index(coming)] \
        if coming in history["quarters"] else None
    q3_high = history["guide_high_usd_bn"][history["quarters"].index(coming)] \
        if coming in history["quarters"] else None
    q3_midpoint = (q3_low + q3_high) / 2 * 1000 if q3_low is not None else None
    q3_yoy = pct_change(q3_midpoint, revenue[-4]) if q3_midpoint else None
    annual = staging["annual_actuals_usd_m"]
    base_year = str(int(guided_year) - 1)
    base = annual.get(base_year)
    in_year = [i for i, p in enumerate(periods) if p.endswith(guided_year)]
    year_to_date_capex = sum(capex_total[i] for i in in_year)
    year_to_date_oi = sum(operating_income[i] for i in in_year)
    elapsed = len(in_year)
    so_far = {1: "Q1", 2: "H1", 3: "前三季"}.get(elapsed, f"前{elapsed}季")
    so_far_words = {1: "一季度", 2: "上半年", 3: "前三季"}.get(elapsed, f"前{elapsed}季")
    rest = {1: "余下三季", 2: "H2", 3: "Q4"}.get(elapsed, "")
    line_words = {1: "四分之一线", 2: "半程线", 3: "四分之三线"}.get(elapsed, "全年线")
    base_quarterly_average = base["operating_income"] / 4 if base else None
    pace_line = base["operating_income"] * elapsed / 4 if base else None
    price_low, price_high = (consensus or {}).get("post_earnings_price_change_range_pct", (None, None))

    source = (
        'Source: <a href="https://investor.atmeta.com/" rel="noopener">Meta Investor Relations</a>'
        f'（{period} earnings release 与电话会；历史季度经 SEC EDGAR 的 10-Q / 10-K 回源）。'
    )

    def source_note(detail: str) -> str:
        return f"{detail}；历史期同口径。自算项目均可在核对表中复核。"

    # Two tracked metrics are settled on the adjusted basis while their history
    # only exists on the GAAP one, so those charts carry a second short line:
    # it coincides with the GAAP line through last quarter (which had no
    # comparable one-off items) and separates only where the add-backs land.
    # Without it the plotted last point and the stated "current" value disagree.
    def adjusted_tail(previous: float, current: float, length: int) -> dict:
        return {
            "name": "调整后（本季）D",
            "values": [None] * (length - 2) + [round(previous, 2), round(current, 2)],
            "color": "GOLD",
        }

    # One entry per tracked metric, so §1 and §3 can each draw the metric's own
    # history under its own threshold instead of only a normalised bar.
    # Each tracked metric runs on the longest window its own series has, and
    # carries the labels that go with it.
    long_operating = long["operating_income_usd_m"]
    long_operating_margin = [
        income / sales * 100 for income, sales in zip(long_operating, long_revenue)
    ]
    long_incremental_margin = [
        None if index < 4 or long_revenue[index] == long_revenue[index - 4]
        else (long_operating[index] - long_operating[index - 4])
        / (long_revenue[index] - long_revenue[index - 4]) * 100
        for index in range(len(long_revenue))
    ]
    long_volume_price = [
        None if impressions is None or price is None
        else ((1 + impressions / 100) * (1 + price / 100) - 1) * 100
        for impressions, price in zip(long_impressions, long_price)
    ]
    segment_labels = long_labels[segment_from:]
    tracked = {
        "经营利润率（调整后）": (
            long_labels, long_operating_margin, "pct1", "经营利润率", "经营利润率（GAAP）",
            adjusted_tail(
                long_operating_margin[-2],
                adjusted_operating_income / revenue[-1] * 100,
                len(long_labels),
            ) if one_offs else None,
        ),
        "平均每条广告价格 YoY": (
            long_labels, long_price, "pct0", "同比", "平均每条广告价格 YoY", None,
        ),
        "同比增量经营利润率": (
            long_labels, long_incremental_margin, "pct1", "ΔOI / ΔRevenue",
            "同比增量经营利润率（GAAP）D",
            adjusted_tail(long_incremental_margin[-2], adjusted_incremental_margin,
                          len(long_labels)) if one_offs else None,
        ),
        "广告量价乘积（隐含收入增速）": (
            long_labels, long_volume_price, "pct1", "隐含同比", "量价乘积 D", None,
        ),
        "FoA Other 单季收入": (
            segment_labels, long_foa_other[segment_from:], "f0c", "$M", "FoA Other 收入", None,
        ),
    }
    if base:
        tracked[f"单季经营利润 vs FY{base_year} 季均线"] = (
            long_labels, long_operating, "f0c", "$M", "单季经营利润", None,
        )

    def tracking_charts(entries, value_key, threshold_label, headline) -> list[dict]:
        charts = []
        for entry in entries:
            metric = entry["metric"]
            if metric not in tracked:
                continue
            metric_labels, values, fmt, ylab, actual_name, adjusted = tracked[metric]
            side = "上方" if entry["direction"] == "up" else "下方"
            adjusted_note = (
                ""
                if adjusted is None
                else f"金色线为剔除本季 {one_off_words}后的同一指标，阈值按该口径结算。"
            )
            exhibit = threshold_exhibit(
                headline(entry),
                metric_labels,
                values,
                entry["threshold"],
                xstep=LONG_STEP if len(metric_labels) > 16 else None,
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

    def margin_of(entry: dict, value_key: str) -> float:
        return headroom(entry["direction"], entry["threshold"], entry[value_key])

    # ── section one ──────────────────────────────────────────────────────────
    settled_charts: list[dict] = []
    expense_raise = None
    if len(expense_calls) >= 2:
        expense_raise = expense_calls[-1]["low"] - expense_calls[-2]["low"]
    if closure is not None:
        counts = dict(zip(closure["labels"], closure["counts"]))
        settled_charts.append({
            "kind": "bars_labeled",
            "title": (
                f"上季 {sum(closure['counts'])} 条待验证问题：{counts.get('已验证', 0)} 条已验证、"
                f"{counts.get('被证伪', 0)} 条被证伪、{counts.get('部分验证', 0)} 条只做到部分验证"
            ),
            "xlabels": closure["labels"],
            "values": closure["counts"],
            "legend": "问题条数",
            "fmt": "f0",
            "yfmt": "f0",
            "label_fmt": "f0",
            "ylab": "条",
            "note": closure["note"].format(
                positions=f"{(snapshot or {}).get('workforce_reduction_positions', 0):,}",
                severance=next((f"${item['usd_m']:,}M" for item in one_offs if item["name"] == "遣散费"), ""),
                expense_low_raise=f"${expense_raise:g}B" if expense_raise is not None else "",
                partial=cn_count(counts.get("部分验证", 0)),
            ),
            "src_extra": (
                "问题清单来自上季本地分析稿的 follow-up；验证结果依据本季 earnings release、"
                f"电话会与 {period} 10-Q。"
            ),
        })
    if prior_kpi is not None:
        entries = prior_kpi["quantified"]
        # Listed closest breach first: a line that missed by a whisker and one
        # that missed by a mile are different news.
        broken = sorted((entry for entry in entries if margin_of(entry, "actual") < 0),
                        key=lambda entry: -margin_of(entry, "actual"))
        held = len(entries) - len(broken)
        if not broken:
            verdict = "全部守住"
        elif len(broken) == 1:
            verdict = f"{cn_count(held)}条守住，被击穿的一条在{broken[0]['area']}"
        else:
            verdict = (f"{cn_count(held)}条守住，被击穿的{cn_count(len(broken))}条"
                       + "、".join(f"一条在{entry['area']}" for entry in broken))
        price_entry = next((entry for entry in entries if entry["metric"].startswith("平均每条广告价格")), None)
        ad_slowdown = (yoy(advertising)[-2] or 0) - (yoy(advertising)[-1] or 0)
        adjusted_entry = next((entry for entry in entries if entry.get("basis") == "adjusted"), None)
        gaap_margin = operating_income[-1] / revenue[-1] * 100
        lead = prior_kpi.get("lead", "")
        if price_entry and lead:
            lead = lead.format(price_margin=f"{margin_of(price_entry, 'actual'):+.0f}%",
                               ad_slowdown=f"{ad_slowdown:.1f}pp")
        settled_charts.append(headroom_exhibit(
            f"上季 {len(entries)} 条量化阈值：{verdict}",
            entries,
            "actual",
            "正值 = 仍在安全侧。" + lead,
            src_extra=(
                f"阈值为上季本地研究设定，不是公司指引；实际值为 {period} 披露值。"
                + (f"经营利润率一条按剔除 {one_off_words}后的 {adjusted_entry['actual']:.2f}% 结算，"
                   + (f"GAAP 口径的 {gaap_margin:.2f}% 击穿得更深。"
                      if gaap_margin < adjusted_entry["actual"] < adjusted_entry["threshold"] else
                      f"GAAP 口径是 {gaap_margin:.2f}%。")
                   if adjusted_entry and one_offs else "")
                + "下面逐条给出可绘制指标自身完整记录的走势。"
            ),
        ))
    # Section one settles what last quarter left in the order it was left: the
    # follow-up questions, then the previous analysis's thresholds (overview,
    # then each line against its own record), and only then the company's own
    # guidance record.
    if prior_kpi is not None:
        settled_charts += tracking_charts(
            [entry for entry in prior_kpi["quantified"]
             if entry["metric"] in ("经营利润率（调整后）", "平均每条广告价格 YoY")],
            "actual",
            "上季阈值",
            lambda entry: (
                f"{entry['metric']}："
                f"{'守住' if margin_of(entry, 'actual') >= 0 else '已击穿'}"
                f"上季阈值 {unit_text(entry['unit'], entry['threshold'])}"
            ),
        )
    # META is the only US filer on this site that puts its quarterly guidance in
    # a filing, so it is the only one that can carry TSMC's guidance record.
    # Microsoft's own release says guidance is given on the webcast instead, and
    # Alphabet gives no quarterly number at all -- both are stated on their pages
    # rather than silently left out.
    settled_charts += [
        guidance_band(history["quarters"], history["guide_low_usd_bn"],
                      history["guide_high_usd_bn"], history["actual_revenue_usd_bn"]),
        guidance_deviation(history["quarters"], history["guide_low_usd_bn"],
                           history["guide_high_usd_bn"], history["actual_revenue_usd_bn"]),
    ]

    # ── section two ──────────────────────────────────────────────────────────
    revenue_step = long_revenue_yoy[-1] - long_revenue_yoy[-2]
    impressions_now, impressions_before = long_impressions[-1], long_impressions[-2]
    price_now, price_before = long_price[-1], long_price[-2]
    volume_led_slowdown = (advertising_yoy[-1] < advertising_yoy[-2]
                           and impressions_now < impressions_before and price_now >= price_before)
    negative_price = sum(1 for v in long_price if v is not None and v < 0)
    price_dips = runs_over_holes(long_price, lambda value: value < 0)
    leader = []
    for impressions, price in zip(long_impressions, long_price):
        if impressions is None or price is None or impressions == price:
            leader.append(None)
        else:
            leader.append("价" if price > impressions else "量")
    known = [(i, side) for i, side in enumerate(leader) if side]
    switches = sum(1 for (_, a), (_, b) in zip(known, known[1:]) if a != b)
    price_led = runs_over_holes(leader, lambda side: side == "价")
    dap = ads["family_daily_active_people_bn"]
    dap_growth = pct_change(dap[-1], dap[-5])
    bridge_gap = abs(volume_price_product[-1] - advertising_yoy[-1])
    closes_twice = all(abs(volume_price_product[i] - yoy(advertising)[i]) < 1.0 for i in (-1, -2))

    fcf_now, fcf_before = long_fcf[-1], long_fcf[-2]
    reported_fcf = [v for v in long_fcf if v is not None]
    fcf_high, fcf_low = max(reported_fcf), min(reported_fcf)
    trough = 0 <= fcf_now <= max(v for v in long_fcf if v is not None) * 0.1
    low_while_growing = [i for i in range(len(long_fcf) - 1)
                         if long_fcf[i] is not None and long_fcf[i] <= fcf_now
                         and long_revenue_yoy[i] is not None and long_revenue_yoy[i] >= 10]
    buybacks = q["stock_repurchases"]
    zero_run = 0
    for value in reversed(buybacks):
        if value != 0:
            break
        zero_run += 1
    ocf_step = pct_change(q["operating_cash_flow"][-1], q["operating_cash_flow"][-2])

    build_start = quarters.index(BUILD_OUT_FROM)
    earlier_peak_at = max(range(build_start), key=lambda i: long_capex_intensity[i])
    first_above = next((i for i in range(build_start, len(quarters))
                        if long_capex_intensity[i] > long_capex_intensity[earlier_peak_at]), None)
    intensity_ratio = long_capex_intensity[-1] / long_capex_intensity[0]

    highlights = [
        {
            "kind": "gs_bar",
            "title": (
                f"收入 ${long_revenue[-1]:,.0f}M、同比 {long_revenue_yoy[-1]:.1f}%，"
                f"较上季{'减速' if revenue_step < 0 else '加速'} {abs(revenue_step):.1f}pp"
            ),
            "xlabels": long_labels,
            "xstep": LONG_STEP,
            "values": long_revenue,
            "legend": "总收入",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "ylab2": "同比增速",
            "yoy": {
                "name": "同比增速 (RHS) D",
                "values": long_revenue_yoy,
                "color": "GREEN",
                "yfmt": "pct1",
            },
            "note": (
                (f"较市场预期 ${consensus['revenue_usd_m']:,.0f}M "
                 f"{'高' if revenue_shown[-1] >= consensus['revenue_usd_m'] else '低'} "
                 f"{abs(pct_change(revenue_shown[-1], consensus['revenue_usd_m'])):.1f}%；"
                 if consensus else "")
                + (f"{period_of(coming)[:2]} 指引中点 ${q3_midpoint:,.0f}M，隐含同比 {signed(q3_yoy)}，"
                   + (f"再减速约 {revenue_yoy[-1] - q3_yoy:.0f}pp。" if q3_yoy < revenue_yoy[-1]
                      else f"较本季加速约 {q3_yoy - revenue_yoy[-1]:.0f}pp。")
                   if q3_midpoint else "")
            ),
            "src_extra": source_note("收入来自各期 10-Q / 10-K 与当季 release，同比为自算"),
        },
        {
            "kind": "lines",
            "title": (
                ("广告减速全部来自量：" if volume_led_slowdown else f"广告同比 {advertising_yoy[-1]:.1f}%：")
                + f"曝光同比 {impressions_now:.0f}%，"
                f"单价 {price_now:.0f}%，而{cn_count(years)}年里价这条线有 "
                f"{negative_price} 个季度是负的"
            ),
            "xlabels": long_labels,
            "xstep": LONG_STEP,
            "series": [
                {"name": "广告收入 YoY D", "values": long_advertising_yoy, "color": "NAVY"},
                {"name": "广告曝光 YoY", "values": long_impressions, "color": "MBLUE"},
                {"name": "平均每条广告价格 YoY", "values": long_price, "color": "GOLD"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "zero_base": True,
            "end_label": True,
            "ylab": "同比增速",
            "note": (
                (f"量价相乘可以闭合：" if bridge_gap < 1.0 else "量价相乘与实际差 "
                 f"{bridge_gap:.1f}pp：")
                + f"{(1 + ads['ad_impressions_yoy_pct'][-1] / 100):.2f} × "
                f"{(1 + ads['price_per_ad_yoy_pct'][-1] / 100):.2f} − 1 = "
                f"{volume_price_product[-1]:.1f}%，对上实际的 {advertising_yoy[-1]:.1f}%。"
                f"同期 Family DAP 仅 {dap[-1]:.2f}B、同比 {dap_growth:.0f}%，"
                f"曝光与用户之间约 {impressions_now - dap_growth:.0f}pp 的缺口来自广告负载与人均时长。"
                f"<b>{cn_count(years)}年的窗口里「量价谁在拉动」的答案换过{cn_count(switches)}次</b>："
                "价格跑赢曝光的只有 "
                + "、".join(span_text(quarters, a, b) for a, b in price_led)
                + f" {cn_count(len(price_led))}段，其余季度量不慢于价；"
                f"金色那条价格线有 {negative_price} 个季度为负"
                f"（最低 {min(v for v in long_price if v is not None):.0f}%），集中在 "
                + "、".join(span_text(quarters, a, b) for a, b in price_dips)
                + "。"
                f"<b>价与量两条线上有{cn_count(len(ad_rate_holes))}个缺口</b>（{'、'.join(ad_rate_holes)}）："
                f"那{cn_count(len(ad_rate_holes))}年公司只在 10-K 里给全年变动，第四季的季度值不存在于任何申报，"
                "本页留空而不是插值。"
            ),
            "src_extra": (
                "曝光与单价同比为公司披露的百分比；广告收入 = 总收入 − Reality Labs − FoA Other，"
                "同比为自算。量价乘积与实际增速的差异来自公司披露值的整数舍入。"
            ),
        },
    ]
    if geography is not None:
        highlights.append(regional_chart(geography, revenue_shown[-1], period))
    if one_offs:
        highlights.append({
            "kind": "bars_labeled",
            "title": (
                f"剔除 ${one_off_total:,}M 一次性项后，经营利润仍较上季"
                + (f"少 ${operating_income[-2] - adjusted_operating_income:,.0f}M"
                   if adjusted_operating_income < operating_income[-2] else
                   f"多 ${adjusted_operating_income - operating_income[-2]:,.0f}M")
            ),
            "xlabels": [f"{prev_period} 经营利润", f"{period} GAAP", f"{period} 调整后 D"],
            "values": [operating_income[-2], operating_income[-1], adjusted_operating_income],
            "legend": "经营利润",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "note": (
                f"加回{one_off_words_named_first} 得到 "
                f"${adjusted_operating_income:,}M；"
                f"同期收入环比 {signed(pct_change(revenue[-1], revenue[-2]))}，"
                + ("所以环比的经营杠杆是负的，与一次性项无关。"
                   if revenue[-1] > revenue[-2] and adjusted_operating_income < operating_income[-2] else
                   "剔除一次性项后环比经营杠杆不为负。")
            ),
            "src_extra": (
                f"GAAP 经营利润来自 {period} 10-Q；{cn_count(len(one_offs))}笔加回项的金额来自当季 release 与分部附注，"
                "调整后经营利润为两者相加的自算值，不是公司定义的 non-GAAP 指标。"
            ),
        })
    collapsed = 0 <= fcf_now < fcf_before * 0.5
    if not trough:
        trough_words = "。"
    elif long_revenue_yoy[-1] < 10:
        trough_words = "，本季收入增速也不在两位数。"
    elif not low_while_growing:
        trough_words = "，但它是唯一一次在收入仍在两位数增长时掉到这个水平。"
    else:
        trough_words = ("，收入仍在两位数增长时掉到这个水平，此前还有 "
                        + "、".join(f"{long_labels[i]}（${long_fcf[i]:,.0f}M，收入同比 "
                                   f"{long_revenue_yoy[i]:+.1f}%）" for i in low_while_growing) + "。")
    fcf_title = (f"单季自由现金流塌到 ${fcf_now:,.0f}M，环比 {pct_change(fcf_now, fcf_before):.1f}% —— "
                 if collapsed else
                 f"单季自由现金流 ${fcf_now:,.0f}M，环比 {pct_change(fcf_now, fcf_before):.1f}% —— ")
    highlights += [
        {
            "kind": "diverging_bars",
            "title": (
                fcf_title
                + f"{len(long_fcf)} 季里为负的有 {sum(1 for v in long_fcf if v is not None and v < 0)} 季"
            ),
            "xlabels": long_labels,
            "xstep": LONG_STEP,
            "values": long_fcf,
            "legend": "自由现金流",
            "positive_label": "正自由现金流",
            "negative_label": "负自由现金流",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "zero_line": True,
            "note": (
                f"经营现金流 ${q['operating_cash_flow'][-1]:,.0f}M "
                + ("基本持平，" if abs(ocf_step) < 2 else f"环比 {signed(ocf_step)}，")
                + (f"资本开支却从 ${capex_shown[-2]:,.0f}M 跳到 ${capex_shown[-1]:,.0f}M；"
                   if capex_shown[-1] > capex_shown[-2] else
                   f"资本开支从 ${capex_shown[-2]:,.0f}M 降到 ${capex_shown[-1]:,.0f}M；")
                + (f"同季净发债 ${snapshot['net_debt_issuance_usd_m']:,}M、"
                   if snapshot and snapshot.get("net_debt_issuance_usd_m") else "")
                + (f"回购连续第{cn_ordinal(zero_run)}季为 $0。"
                   if zero_run >= 2 else "本季回购为 $0。" if zero_run == 1 else
                   f"本季回购 ${buybacks[-1]:,.0f}M。")
                + f"<b>{cn_count(years)}年的窗口给这一格一个参照</b>：{len(long_fcf)} 季里自由现金流的最高是 "
                f"${fcf_high:,.0f}M（{long_labels[long_fcf.index(fcf_high)]}），"
                f"最低 ${fcf_low:,.0f}M（{long_labels[long_fcf.index(fcf_low)]}）—— "
                + ("本季不是这条线最差的一格" if fcf_now > fcf_low else "本季是这条线最差的一格")
                + trough_words
            ),
            "src_extra": source_note(
                "FCF 按公司口径 = 经营现金流 − 购买物业及设备 − 融资租赁本金偿付"
            ),
        },
        {
            "kind": "gs_bar",
            "title": (
                f"资本开支 ${long_capex[-1]:,.0f}M、占收入 {long_capex_intensity[-1]:.1f}%，"
                f"{cn_count(years)}年前是 {long_capex_intensity[0]:.1f}%"
            ),
            "xlabels": long_labels,
            "xstep": LONG_STEP,
            "values": long_capex,
            "legend": "单季资本开支（含融资租赁）",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "ylab2": "占收入比",
            "yoy": {
                "name": "CapEx / 收入 (RHS) D",
                "values": long_capex_intensity,
                "color": "GOLD",
                "yfmt": "pct1",
            },
            "note": (
                f"<b>右轴那条占收入比是这张图的主角</b>：{cn_count(years)}年区间 "
                f"{min(long_capex_intensity):.1f}%–{max(long_capex_intensity):.1f}%，"
                f"{quarters[0]} 是 {long_capex_intensity[0]:.1f}%，本季 {long_capex_intensity[-1]:.1f}% —— "
                + ("资本强度翻了不止一倍" if intensity_ratio >= 2 else
                   f"资本强度是那时的 {intensity_ratio:.1f} 倍")
                + (f"，而越过 {quarters[earlier_peak_at]} 的前高 "
                   f"{long_capex_intensity[earlier_peak_at]:.1f}% 是 {quarters[first_above]} 以后才发生的。"
                   if first_above is not None else "。")
                + (f"{so_far} 已实现 ${year_to_date_capex:,}M，全年指引下限 "
                   f"US${capex_calls[-1]['low']:g}B 隐含{spaced(rest)}还要再做 "
                   f"${capex_calls[-1]['low'] * 1000 - year_to_date_capex:,.0f}M，"
                   + ("即单季规模较本季再上一个台阶。"
                      if (capex_calls[-1]['low'] * 1000 - year_to_date_capex) / (4 - elapsed) > capex_total[-1]
                      else "单季规模不必再高于本季。")
                   if capex_calls and 0 < elapsed < 4 else "")
            ),
            "src_extra": (
                "资本开支为购买物业及设备加融资租赁本金，与公司指引口径一致；占收入比为自算。"
                "指引不覆盖以合资与租赁结构取得的算力，因此这条线是资本强度的下界而非全貌。"
            ),
        },
    ]
    capex_raises = sum(1 for a, b in zip(capex_guide_mid, capex_guide_mid[1:]) if b > a)
    if capex_calls:
        raises = sum(1 for a, b in zip(capex_guide_mid, capex_guide_mid[1:]) if b > a)
        cuts = sum(1 for a, b in zip(capex_guide_mid, capex_guide_mid[1:]) if b < a)
        span_days = (datetime.date.fromisoformat(capex_calls[-1]["filed"])
                     - datetime.date.fromisoformat(capex_calls[0]["filed"])).days
        within = "半年内" if span_days <= 184 else ("一年内" if span_days <= 366 else "")
        if len(capex_calls) == 1:
            capex_title = f"FY{guided_year} CapEx 首次指引 US${range_text(capex_calls[0]['low'], capex_calls[0]['high'])}B"
        elif cuts == 0 and raises == len(capex_calls) - 1:
            capex_title = (f"FY{guided_year} CapEx 指引{within}{cn_count(raises)}次上调，"
                           f"中点从 US${capex_guide_mid[0]:.0f}B 抬到 US${capex_guide_mid[-1]:.1f}B")
        else:
            capex_title = (f"FY{guided_year} CapEx 指引{within}改过{cn_count(len(capex_calls) - 1)}次"
                           f"（{cn_count(raises)}次上调、{cn_count(cuts)}次下调），"
                           f"中点从 US${capex_guide_mid[0]:.0f}B 到 US${capex_guide_mid[-1]:.1f}B")
        last, before = capex_calls[-1], capex_calls[-2] if len(capex_calls) > 1 else None
        narrowed_up = (before is not None and last["low"] > before["low"] and last["high"] == before["high"])
        prior_actual = (base["purchases_of_property_and_equipment"] + base["finance_lease_principal"]
                        if base else None)
        highlights.append({
            "kind": "bars_labeled",
            "title": capex_title,
            "xlabels": [f"{call_of(call['filed'])} call" for call in capex_calls],
            "values": capex_guide_mid,
            "legend": f"FY{guided_year} CapEx 指引中点",
            "fmt": "usd1",
            "yfmt": "usd1",
            "label_fmt": "usd1",
            "ylab": "US$B",
            "note": (
                "区间依次为 " + "、".join(f"US${range_text(call['low'], call['high'])}B" for call in capex_calls)
                + "。"
                + ("最新一次是区间收窄，但收窄的方式是抬高下限——中点仍在上移。" if narrowed_up else "")
            ),
            "src_extra": (
                f"{cn_count(len(capex_calls))}次口径来自对应季度的 earnings call；中点为自算。"
                + (f"较 FY{base_year} 实际的 ${prior_actual:,}M 为同一口径对照。" if prior_actual else "")
            ),
        })

    # ── section three ────────────────────────────────────────────────────────
    next_charts: list[dict] = []
    if next_kpi is not None:
        entries = next_kpi["quantified"]
        below = [entry for entry in entries if margin_of(entry, "current") < 0]
        themed = [entry for entry in below if entry.get("theme")]
        theme_words = next_kpi.get("theme_words", {})
        if not below:
            state = "当前值全部在安全侧"
        elif themed and len(themed) == len(below):
            state = (f"{cn_count(len(below))}条已在阈值之下，且都直接指向"
                     f"「{theme_words[themed[0]['theme']]}」")
        elif themed:
            state = (f"{cn_count(len(below))}条已在阈值之下，其中{cn_count(len(themed))}条直接指向"
                     f"「{theme_words[themed[0]['theme']]}」")
        else:
            state = f"{cn_count(len(below))}条已在阈值之下"
        profit_lines = [entry for entry in below if entry.get("theme") == "incremental_profit"]
        pace_words = ""
        if base and len(profit_lines) >= 2:
            pace_words = (
                "增量经营利润率与单季经营利润两条都在线下：本季 GAAP 经营利润 "
                f"${operating_income[-1]:,}M，{'低于' if operating_income[-1] < base_quarterly_average else '高于'} "
                f"FY{base_year} 经营利润的季均值 ${base_quarterly_average:,.0f}M；{so_far_words}累计 ${year_to_date_oi:,}M，"
                + (f"只比全年承诺的{line_words} ${pace_line:,.0f}M 高 ${year_to_date_oi - pace_line:,.0f}M。"
                   if year_to_date_oi >= pace_line else
                   f"比全年承诺的{line_words} ${pace_line:,.0f}M 低 ${pace_line - year_to_date_oi:,.0f}M。")
            )
        gated = next_kpi.get("disclosure_gated", [])
        next_charts.append(headroom_exhibit(
            f"下季 {len(entries)} 条量化阈值：{state}",
            entries,
            "current",
            "正值 = 仍在安全侧。" + pace_words,
            src_extra=(
                f"阈值为本地研究设定，不是公司指引；当前值为 {period} 实际。"
                + ("增量经营利润率的当前值取剔除一次性项后的口径。"
                   if any(entry.get("basis") == "adjusted" for entry in entries) and one_offs else "")
                + (f"另有 {len(gated)} 条需等披露才能判定（"
                   + "、".join(item["short"] for item in gated) + "）。" if gated else "")
            ),
        ))
        next_charts += tracking_charts(
            entries,
            "current",
            "下季阈值",
            lambda entry: (
                f"{entry['metric']}：下季阈值 {unit_text(entry['unit'], entry['threshold'])}，"
                f"当前 {unit_text(entry['unit'], entry['current'])}"
            ),
        )

    # ── section four ─────────────────────────────────────────────────────────
    ahead = runs([None if a is None or b is None else a - b
                  for a, b in zip(long_depreciation_yoy, long_revenue_yoy)], lambda gap: gap > 0)
    current_run = ahead[-1] if ahead and ahead[-1][1] == len(quarters) - 1 else None
    earlier_runs = [run for run in ahead if run is not current_run]
    multiple_now = capex_shown[-1] / depreciation_shown[-1]
    multiple_before = capex_shown[-2] / depreciation_shown[-2]
    peak_ttm = max(v for v in long_ttm_fcf if v is not None)
    turned_last_quarter = (long_ttm_fcf[-1] < long_ttm_fcf[-2] and long_ttm_fcf[-2] > long_ttm_fcf[-3])
    rl_yoy = yoy(q["reality_labs_revenue"])
    long_reality_yoy = [None] * 4 + [
        None if long_reality[i] is None or not long_reality[i - 4] else pct_change(long_reality[i], long_reality[i - 4])
        for i in range(4, len(long_reality))]
    rl_step = ("首次转正" if rl_yoy[-1] > 0 and all(v is None or v <= 0 for v in long_reality_yoy[:-1])
               else "转正" if rl_yoy[-1] > 0 and rl_yoy[-2] <= 0
               else "为正" if rl_yoy[-1] > 0
               else "转负" if rl_yoy[-2] > 0 else "仍为负")
    foa_first_billion = foa_other_shown[-1] >= 1000 > max(v for v in long_foa_other[:-1] if v is not None)
    routine = [
        {
            "kind": "lines",
            "title": (
                f"折旧摊销同比 {depreciation_yoy[-1]:+.1f}%，"
                f"{'快' if depreciation_yoy[-1] > revenue_yoy[-1] else '慢'}于收入的 {revenue_yoy[-1]:+.1f}%"
            ),
            "xlabels": long_labels[yoy_from:],
            "xstep": LONG_STEP,
            "series": [
                {"name": "折旧摊销同比", "values": long_depreciation_yoy[yoy_from:],
                 "color": "RED"},
                {"name": "收入同比", "values": long_revenue_yoy[yoy_from:], "color": "NAVY"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "end_label": True,
            "ylab": "同比增速",
            "note": (
                f"本季资本开支是折旧摊销的 {multiple_now:.1f} 倍，"
                "意味着这条线的上行才刚开始；折旧曲线与收入曲线的交叉点，是这轮资本周期的定价问题。"
                f"<b>把两条同比放在一张图上，{cn_count(years)}年里折旧跑赢收入的有{cn_count(len(ahead))}段</b> —— "
                + "、".join(span_text(quarters, a, b) for a, b in ahead)
                + (f"；上一段持续了{cn_count(earlier_runs[-1][1] - earlier_runs[-1][0] + 1)}季"
                   if earlier_runs else "")
                + ("，而这一次资本开支与折旧的倍数还在扩大。" if current_run and multiple_now > multiple_before
                   else "。")
            ),
            "src_extra": source_note(
                "折旧摊销逐季来自各期现金流量表（只按年初至今披露，逐季由相邻两个年初至今值"
                "相减，第四季为全年 − 前三季）；同比为自算"),
        },
        {
            "kind": "lines",
            "title": (
                f"TTM 自由现金流由 ${peak_ttm:,.0f}M 回落到 ${ttm_fcf[-1]:,.0f}M"
                if ttm_fcf[-1] < peak_ttm else f"TTM 自由现金流创新高：${ttm_fcf[-1]:,.0f}M"
            ),
            "xlabels": long_labels[ttm_from:],
            "xstep": LONG_STEP,
            "series": [
                {"name": "TTM 自由现金流", "values": long_ttm_fcf[ttm_from:], "color": "NAVY"},
            ],
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "end_label": True,
            "ylab": "$M",
            "note": (
                f"滚动四季口径把单季税款与季节性摊平；同比 "
                f"{pct_change(ttm_fcf[-1], ttm_fcf[-5]):+.1f}%"
                + ("，拐点出现在上一季。" if turned_last_quarter else "。")
                + f"<b>这条线从 {long_labels[ttm_from]} 起</b>：滚动四季要先攒满四个季度。"
                f"{long['finance_lease_note']}"
            ),
            "src_extra": source_note("按各季经营现金流减资本开支（含融资租赁本金）滚动四季求和（自算）"),
        },
        {
            "kind": "lines",
            "title": (
                "两条非广告收入线分道扬镳："
                + (f"FoA Other 首破 $10 亿" if foa_first_billion else f"FoA Other ${foa_other_shown[-1]:,.0f}M")
                + f"，Reality Labs 仍在 ${reality_labs_shown[-1]:,.0f}M"
            ),
            "xlabels": long_labels[segment_from:],
            "xstep": LONG_STEP,
            "series": [
                {"name": "FoA Other", "values": long_foa_other[segment_from:], "color": "NAVY"},
                {"name": "Reality Labs", "values": long_reality[segment_from:],
                 "color": "MBLUE"},
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
                f"Reality Labs 收入同比 {pct_change(reality_labs_shown[-1], reality_labs_shown[-5]):+.1f}% {rl_step}"
                + (f"，但本季经营亏损仍有 ${abs(snapshot['reality_labs_operating_loss_usd_m'][0]):,}M。"
                   if snapshot else "。")
                + f"<b>这张图只能回到 {long_labels[segment_from]}，不能到 {quarters[0][:4]}</b>：{long['segment_note']}"
            ),
            "src_extra": (
                "两条分项收入逐季来自各期 10-Q / 10-K 收入分解附注的分部维度事实；"
                "第四季取公司 Q4 新闻稿印出来的三个月列，而不是「全年 − 前三季」的相减值 —— "
                "相减的两条腿各自已四舍五入到百万，2024Q4 因此会算出 519 与 522 两个版本，"
                "公司自己印的是 519。Reality Labs 的 Q4 有硬件季节性，不宜按环比读。"
            ),
        },
    ]

    exhibits = number_exhibits(settled_charts + highlights + next_charts + routine)
    first_table = len(exhibits) + 2

    quarterly_rows = []
    for index, p in enumerate(periods):
        quarterly_rows.append([
            p,
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
    for index, p in enumerate(periods):
        ad_rows.append([
            p,
            f"{ads['ad_impressions_yoy_pct'][index]:+.0f}%",
            f"{ads['price_per_ad_yoy_pct'][index]:+.0f}%",
            f"{volume_price_product[index]:+.1f}% D",
            "—" if index < 4 else f"{yoy(advertising)[index]:+.1f}% D",
            f"{ads['family_daily_active_people_bn'][index]:.2f}B",
        ])

    def three(values: list, money: bool = True) -> list[str]:
        """This quarter, last quarter, a year ago → the table's three period cells and two changes."""
        cur, prev, prior = values
        cell = (lambda v: "—" if v is None else f"${v:,}M") if money else (lambda v: "—" if v is None else v)
        return [cell(prior), cell(prev), cell(cur),
                "—" if prev is None else f"{pct_change(cur, prev):+.1f}%",
                "—" if prior is None else f"{pct_change(cur, prior):+.1f}%"]

    def loss_words(cur: float, base_value: float) -> str:
        return "亏损扩大" if cur < base_value else "亏损收窄"

    series_three = lambda values: [values[-1], values[-2], values[-5]]  # noqa: E731
    quality_rows = []
    if snapshot is not None:
        rl_loss = snapshot["reality_labs_operating_loss_usd_m"]
        eps = snapshot["diluted_eps_usd"]
        unpaid = snapshot["unpaid_capex_in_payables_usd_m"]
        restricted = snapshot["restricted_cash_in_other_assets_usd_m"]
        heads = snapshot["headcount"]
        quality_rows = [
            ["总收入"] + three(series_three(revenue)),
            ["广告收入"] + three(series_three(advertising)),
            ["Family of Apps 经营利润"] + three(snapshot["family_of_apps_operating_income_usd_m"]),
            ["Reality Labs 经营亏损", f"-${abs(rl_loss[2]):,}M", f"-${abs(rl_loss[1]):,}M",
             f"-${abs(rl_loss[0]):,}M", loss_words(rl_loss[0], rl_loss[1]), loss_words(rl_loss[0], rl_loss[2])],
            ["经营利润（GAAP）"] + three(series_three(operating_income)),
            ["经营利润（调整后 D）", "—", "—",
             f"${adjusted_operating_income:,}M", "—",
             f"{pct_change(adjusted_operating_income, operating_income[-5]):+.1f}%"],
            ["稀释 EPS", f"${eps[2]:.2f}", f"${eps[1]:.2f}", f"${eps[0]:.2f}",
             f"{pct_change(eps[0], eps[1]):+.1f}%", f"{pct_change(eps[0], eps[2]):+.1f}%"],
            ["经营现金流"] + three(series_three(q["operating_cash_flow"])),
            ["资本开支（含融资租赁）"] + three(series_three(capex_total)),
            ["自由现金流 D"] + three(series_three(free_cash_flow)),
            ["计入应付的未付资本开支"] + three(unpaid),
            ["其他资产项下的受限现金", f"${restricted[2]:,}M", "—", f"${restricted[0]:,}M", "—",
             snapshot.get("restricted_cash_remark") or f"{pct_change(restricted[0], restricted[2]):+.1f}%"],
            ["员工数", f"{heads[2]:,}", f"{heads[1]:,}", f"{heads[0]:,}",
             f"{pct_change(heads[0], heads[1]):+.1f}%", f"{pct_change(heads[0], heads[2]):+.1f}%"],
        ]
        if one_offs:
            if len(one_offs) != 2:
                pass
        else:
            quality_rows = [row for row in quality_rows if not row[0].startswith("经营利润（调整后")]

    expense_rows = []
    if expense is not None:
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

    guidance_rows = []
    if q3_midpoint:
        guidance_rows.append(
            [f"{period_of(coming)} 收入", "—", "—", f"US${q3_low:.0f}–{q3_high:.0f}B",
             f"中点 ${q3_midpoint:,.0f}M，隐含同比 {signed(q3_yoy)} D"])
    if len(expense_calls) >= 2:
        before_exp, now_exp = expense_calls[-2], expense_calls[-1]
        move = []
        if now_exp["low"] != before_exp["low"]:
            move.append(f"下限{'抬高' if now_exp['low'] > before_exp['low'] else '下调'} "
                        f"${abs(now_exp['low'] - before_exp['low']):g}B")
        if now_exp["high"] != before_exp["high"]:
            move.append(f"上限{'抬高' if now_exp['high'] > before_exp['high'] else '下调'} "
                        f"${abs(now_exp['high'] - before_exp['high']):g}B")
        guidance_rows.append(
            [f"FY{guided_year} 总费用", f"US${range_text(before_exp['low'], before_exp['high'])}B", "—",
             f"US${range_text(now_exp['low'], now_exp['high'])}B",
             ("、".join(move) + (" " + outlook["expense_change_reason"]
                                 if outlook and outlook.get("expense_change_reason") else "")) if move else "不变"])
    if len(capex_calls) >= 2:
        guidance_rows.append(
            [f"FY{guided_year} CapEx", f"US${range_text(capex_calls[-2]['low'], capex_calls[-2]['high'])}B",
             f"{so_far} 已实现 ${year_to_date_capex:,}M",
             f"US${range_text(capex_calls[-1]['low'], capex_calls[-1]['high'])}B",
             f"中点由 US${capex_guide_mid[-2]:.0f}B {'抬到' if capex_guide_mid[-1] > capex_guide_mid[-2] else '改为'} "
             f"US${capex_guide_mid[-1]:.1f}B D"])
    if outlook is not None:
        if base:
            guidance_rows.append(
                [f"FY{guided_year} 经营利润", outlook["operating_income_commitment_prior"],
                 f"{so_far} ${year_to_date_oi:,}M", outlook["operating_income_commitment"],
                 f"FY{base_year} 为 ${base['operating_income']:,}M；{line_words} ${pace_line:,.0f}M D"])
        tax_move = ((outlook["tax_rate_pct"][0] + outlook["tax_rate_pct"][1])
                    - (outlook["tax_rate_prior_pct"][0] + outlook["tax_rate_prior_pct"][1])) / 2
        guidance_rows.append(
            ["余下各季有效税率",
             f"{outlook['tax_rate_prior_pct'][0]}–{outlook['tax_rate_prior_pct'][1]}%", "—",
             f"{outlook['tax_rate_pct'][0]}–{outlook['tax_rate_pct'][1]}%",
             "持平" if tax_move == 0 else f"{'上调' if tax_move > 0 else '下调'}约 {abs(round(tax_move)):.0f}pp"])
        guidance_rows.append(
            [f"FY{int(guided_year) + 1} CapEx", outlook["fy2027_capex_prior"], "—",
             outlook["fy2027_capex"], outlook["fy2027_capex_remark"]])

    tables = []
    if prior_kpi is not None:
        tables.append(threshold_table(0, "上季阈值与本季实际（原单位）",
                                      prior_kpi["quantified"], "actual", f"{period} 实际"))
    if next_kpi is not None:
        tables.append(threshold_table(0, "下季阈值与当前值（原单位）",
                                      next_kpi["quantified"], "current", "当前值"))
    if guidance_rows:
        tables.append({
            "n": 0,
            "title": f"{period[:2]} 兑现、{period_of(coming)[:2]} 指引与全年 outlook",
            "headers": ["指标", "上季口径", "本季已实现", "本季新口径", "变化 / 备注"],
            "rows": guidance_rows,
        })
    if quality_rows:
        tables.append({
            "n": 0,
            "title": f"当季经营质量与可比性（{year_ago} / {prev_period} / {period}）",
            "headers": ["指标", year_ago, prev_period, period, "QoQ", "YoY"],
            "rows": quality_rows,
        })
    tables += [
        {
            "n": 0,
            "title": f"{cn_count(len(periods))}季度基础数据（前四季只用于计算同比）",
            "headers": ["期间", "总收入", "广告收入", "FoA Other", "Reality Labs", "经营利润",
                        "经营现金流", "资本开支", "自由现金流 D", "折旧摊销", "股权激励", "回购"],
            "rows": quarterly_rows,
        },
        {
            "n": 0,
            "title": f"{cn_count(len(periods))}季度广告量价与用户",
            "headers": ["期间", "曝光 YoY", "单价 YoY", "量价乘积 D", "广告收入 YoY D", "Family DAP"],
            "rows": ad_rows,
        },
    ]
    if expense_rows:
        tables.append({
            "n": 0,
            "title": f"本季{cn_count(len(expense['lines']))}条费用线（{period} vs {year_ago}）",
            "headers": ["费用线", year_ago, period, "YoY", "占本季收入 D"],
            "rows": expense_rows,
        })
    tables.append(ai_capex_cycle_table(0))
    for offset, table in enumerate(tables):
        table["n"] = first_table + offset

    # ── the lines the page leads with ───────────────────────────────────────
    adjusted_margin = adjusted_operating_income / revenue[-1] * 100
    headline = (
        ("广告引擎本身没坏——" if closes_twice else "")
        + f"收入 ${revenue_shown[-1]:,}M、同比 {revenue_yoy[-1]:.1f}%"
        + ("，量价桥两季都能闭合；" if closes_twice else "；")
        + (("但多做的收入不再产生利润：" if adjusted_operating_income < operating_income[-2] and revenue[-1] > revenue[-2] else "")
           + (f"剔除 ${one_off_total:,}M 一次性项后经营利润仍环比 "
              f"{pct_change(adjusted_operating_income, operating_income[-2]):.1f}%，" if one_offs else
              f"经营利润环比 {pct_change(operating_income[-1], operating_income[-2]):.1f}%，"))
        + f"同比增量经营利润率{'只有' if adjusted_incremental_margin < adjusted_margin else '为'} "
        f"{adjusted_incremental_margin:.1f}%，"
        + (f"单季自由现金流塌到 ${fcf_shown[-1]:,}M。" if collapsed
           else f"单季自由现金流 ${fcf_shown[-1]:,}M。")
        + (f"财报后股价下跌约 {abs(price_high):.0f}%–{abs(price_low):.0f}%。"
           if price_high is not None and price_high < 0 else "")
    )
    price_streak = 1
    for index in range(len(long_price) - 1, 0, -1):
        if long_price[index - 1] is None or long_price[index - 1] != long_price[-1]:
            break
        price_streak += 1
    brief = (
        '<h4>本季三条主线</h4><div class="takeaway-grid">'
        '<article><span>亮点</span><b>广告绝对竞争力没有裂缝</b>'
        f'<p>广告收入同比 {advertising_yoy[-1]:.1f}%，'
        + (f'单价连续{cn_count(price_streak)}季 {price_now:+.0f}%；' if price_streak >= 2
           else f'单价 {price_now:+.0f}%；')
        + (f'FoA Other 首破 $10 亿、同比 {foa_other_yoy[-1]:.0f}%。' if foa_first_billion
           else f'FoA Other ${foa_other_shown[-1]:,.0f}M、同比 {foa_other_yoy[-1]:.0f}%。')
        + '</p></article>'
        + ('<article><span>结构</span><b>减速全部来自量</b>' if volume_led_slowdown
           else '<article><span>结构</span><b>量与价</b>')
        + f'<p>曝光同比 {impressions_before:.0f}% → {impressions_now:.0f}%，'
        f'价格贡献 {price_now - price_before:.0f}pp；曝光与 DAP 之间约 {impressions_now - dap_growth:.0f}pp 靠广告负载。</p></article>'
        + ('<article><span>存疑</span><b>增量资本没有产出增量利润</b>'
           if adjusted_incremental_margin < adjusted_margin / 2 else
           '<article><span>观察</span><b>增量利润率与资本强度</b>')
        + f'<p>同比增量经营利润率 {adjusted_incremental_margin:.1f}%，'
        f'资本开支占收入 {capex_intensity[-1]:.1f}%。</p></article>'
        '</div>'
    )

    parts = ((["上季兑现"] if settled_charts else []) + ["本季重点"]
             + (["下季跟踪"] if next_charts else []) + ["长期常规"])
    notes = [
        f"本页按「{' → '.join(parts)}」{cn_count(len(parts))}段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
    ]
    if prior_kpi is not None and next_kpi is not None:
        settled_bar = next(ex for ex in settled_charts if ex["kind"] == "diverging_bars")
        notes.append(f"Exhibit {settled_bar['n']} 与 Exhibit {next_charts[0]['n']} 的阈值是本地研究设定，"
                     "不是公司指引，也不构成评级或投资建议；「距阈值余量」统一为正值代表安全侧。")
    notes += [
        "本页只发布公司披露值、可复算的简单派生值，以及明确标注的市场预期；D 标记代表 Derived / 自算。",
        "市场预期一律标注为「市场预期」并给出取数时点，不写卖方机构名，也不发布评级、目标价或估值。",
    ]
    if one_offs:
        notes.append(f"调整后经营利润 = GAAP 经营利润加回本季{one_off_words_named_first}，是算术加总，"
                     f"不是公司定义的 non-GAAP 指标；{cn_count(len(one_offs))}笔加回项未按分部披露，因此分部层面的调整后利润率无法拆分。")
    notes += [
        "同比增量经营利润率 = （本季经营利润 − 去年同期经营利润）÷（本季收入 − 去年同期收入），"
        "用同比而非环比，是因为 Q4 的季节性足以让环比口径每年两次翻转符号。",
        "广告收入 = 总收入 − Reality Labs − FoA Other，三条线始终加回报告总额；"
        "量价乘积为公司披露的曝光与单价同比相乘，与实际广告收入增速的差异来自整数舍入。",
        "自由现金流按公司口径 = 经营现金流 − 购买物业及设备 − 融资租赁本金偿付；资本开支同口径含融资租赁。",
        "资本开支指引只覆盖进入公司报表的部分；以合资、租赁与残值担保结构取得的算力不进入这条线，"
        "本页因此把资本强度曲线标注为下界而非全貌。",
    ]
    if price_high is not None:
        notes.append(f"财报后股价反应各公开来源报价不一致（约 {abs(price_high):.0f}%–{abs(price_low):.0f}%），本页只发布区间，不取单一数值。")
    notes += [
        "季度值来自各期 10-Q 与 10-K；无 10-Q 的第四季度按「全年 − 前三季」倒推，"
        "个别科目因公司按百万美元四舍五入，倒推值与逐季披露值存在 $1M 级差异。",
        "本页已知未接入：分部季度经营利润的完整历史、区域收入的多季序列、按分部拆分的一次性项、"
        "以及电话会口径的 Meta AI、business agents、AI 眼镜等运营 KPI（公司仅给相对数）。",
    ]

    sections = []
    if settled_charts:
        sections.append({
            "id": "settled",
            "title": "一、上季跟踪指标兑现了吗",
            "description": "先结算上季留下的问题与阈值，再看本季数据——否则页面只会不断累积判断，从不闭环。",
            "exhibits": exhibits[: len(settled_charts)],
        })
    sections.append({
        "id": "quarter_highlights",
        "title": "二、本季重点",
        "description": ("收入与指引、广告的量价拆分"
                        + ("与各区域的收入增速" if geography is not None else "")
                        + ("、一次性项之后的经营利润" if one_offs else "")
                        + (f"、现金流与资本开支的{cn_count(capex_raises)}次上调。" if capex_raises else "、现金流与资本开支。")),
        "exhibits": exhibits[len(settled_charts): len(settled_charts) + len(highlights)],
    })
    if next_charts:
        sections.append({
            "id": "next_quarter",
            "title": "三、下季要跟踪什么",
            "description": "同一套口径向前看：当前值离下季阈值还有多远，统一用「距阈值余量」表示。",
            "exhibits": exhibits[
                len(settled_charts) + len(highlights):
                len(settled_charts) + len(highlights) + len(next_charts)
            ],
        })
    sections.append({
        "id": "routine",
        "title": "四、长期常规跟踪",
        "description": "META 专属的常规序列：折旧曲线、现金转换与非广告收入线。",
        "exhibits": exhibits[-len(routine):],
    })

    return {
        "schema_version": "quarterly-dashboard/meta-v1",
        "page": {"slug": "meta", "language": "zh-CN"},
        "company": {
            "ticker": "META",
            "name": "Meta Platforms",
            "group": "internet",
            "accounting_standard": "US GAAP",
        },
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · META",
        "title": f"Meta Platforms (META)：{period} 季报仪表盘",
        "subtitle": (f"截至 {latest['period_end']} · 发布 {latest['release_date']} · US GAAP · "
                     f"{AUDIT_WORDS[latest['audit_status']]} · 金额单位为 $M，另有注明除外"),
        "headline": headline,
        "brief": brief,
        "source": source,
        "source_url": "https://investor.atmeta.com/",
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": sections,
        "tables": tables,
        "notes": notes,
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
    # Rendered here, not at import: the shell stamps the payload's content
    # hash into its <script src>, so it has to be built after write_dash.
    (shell_dir / "index.html").write_text(
        render_shell("META", "meta"), encoding="utf-8")
    exhibits = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"META page: {exhibits} charts in {len(payload['sections'])} sections + "
          f"{len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
