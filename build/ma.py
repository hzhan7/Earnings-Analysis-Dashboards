#!/usr/bin/env python3
"""Build the MA quarterly-results page.

Same four-part, chart-led shape as the other company pages (上季兑现 → 本季重点
→ 下季跟踪 → 长期常规).  Mastercard's calendar year is its fiscal year, so no
relabelling is needed here.

What this page has instead of a guidance record.  Several companies on this
site put a quarterly range in a filing, which lets their first section settle
"guidance versus actual" quarter by quarter.  Mastercard files no forward
number at all -- its earnings 8-K contains no Outlook block and the words
``outlook``, ``guidance`` and ``we expect`` do not appear in it; the outlook is
given on the call as "high end of low double-digit", which has neither a floor
nor a ceiling to clear.  So the page carries the one quantity the company must
publish every quarter and that *can* be settled against itself: the share of
gross billings it hands back to issuers as rebates and incentives.

Under the presentation Mastercard adopted in the first quarter of 2023 the four
assessment lines are printed gross in a table and the payment network is
printed net, so the rebate is the difference of two filed figures.  The 10-Q's
MD&A also states the rebate in dollars in a sentence ("included $5,997 million
of rebates and incentives"), and the subtraction reproduces it to the dollar --
which is what licenses the eighteen-quarter series the table cannot print.

The page is rolled by editing ``series/ma.json`` alone.  Every count, span,
record and direction in the prose is recomputed from the series on each build.
What only one quarter has -- the closure of last quarter's questions and
thresholds, next quarter's thresholds, the release's own figures, the market
expectation, the call's wording and the quarter's sentences -- sits in blocks
stamped with the quarter (``board.stamped_block``); ``_checks`` is a separate
reading of the quarter's release and 10-Q that the tests hold the page to and
this builder never reads.

Published numbers are company-reported or transparent arithmetic.  Market
expectations are labelled as such, with no broker attribution.
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
    fill_story,
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


STAGING_PATH = ROOT / "series" / "ma.json"
DATA_DIR = ROOT / "data"

# Four quarters of base are needed before any year-over-year line exists.
YOY_FROM = 4
# The disaggregation window is its own record, so its year-on-year run-up is
# counted from its own start rather than from the page's.
DIS_YOY_FROM = 4
# 「卡在」 a band: the trailing run of net payment-network increments whose
# range stays within this share of the run's largest value.
PLATEAU_WIDTH = 0.15
# 「窄带」: the drivers' last six quarters span no more than this many points.
NARROW_BAND_PP = 3

ASSESSMENT_LINES = (
    "domestic_assessments",
    "cross_border_assessments",
    "transaction_processing_assessments",
    "other_network_assessments",
)

# How the year-to-date window is named once the quarter is known.
YTD_WORDS = {1: "一季度", 2: "上半年", 3: "前三季度", 4: "全年"}

# The first MA analysis in the owner's notes covers this quarter; its section 0
# says there was no earlier note to answer. That quarter has nothing of a
# previous report's to settle, and section one says so rather than invent it.
FIRST_REPORT_PERIOD = "Q1 2026"


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
    """``+16.0%`` / ``-3.0%``; a value that rounds to nothing prints unsigned."""
    if round(value, digits) == 0:
        return f"{0:.{digits}f}{suffix}"
    return f"{value:+.{digits}f}{suffix}"


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100


def rounded(values: list[float | None], digits: int = 6) -> list[float | None]:
    return [None if value is None else round(value, digits) for value in values]


def plain_text(html: str) -> str:
    """Strip markup for the slots the renderer writes through ``esc()``."""
    return re.sub(r"<[^>]+>", "", html)


def joined(items: list[str]) -> str:
    """「A」 / 「A 与 B」 / 「A、B 与 C」."""
    return items[0] if len(items) == 1 else "、".join(items[:-1]) + " 与 " + items[-1]


def trailing_run(values: list, test) -> int:
    """How many of the last values in a row pass ``test``."""
    run = 0
    for value in reversed(values):
        if value is None or not test(value):
            break
        run += 1
    return run


def falling_run(values: list[float]) -> int:
    """Consecutive quarter-on-quarter declines ending at the latest value."""
    run = 0
    for index in range(len(values) - 1, 0, -1):
        if values[index] < values[index - 1]:
            run += 1
        else:
            break
    return run


def plateau_run(values: list[float | None]) -> int:
    """The longest trailing run whose range stays within ``PLATEAU_WIDTH`` of its top."""
    run = 0
    for start in range(len(values) - 1, -1, -1):
        window = values[start:]
        if any(value is None for value in window):
            break
        if max(window) - min(window) > PLATEAU_WIDTH * max(window):
            break
        run = len(window)
    return run


GDV_REGIONS = (("美国", "united_states", "NAVY"), ("欧洲", "europe", "MBLUE"),
               ("APMEA", "apmea", "BLUE"), ("拉美", "latin_america", "GOLD"),
               ("加拿大", "canada", "GRAY"))


def regional_gdv_exhibit(staging: dict) -> dict:
    """GDV in dollars by region, stacked, with Europe's share on the right axis.

    Every earnings release's Operating Performance table prints each region's
    GDV in US$ billions (converted at the quarter's average rates) beside its
    USD and local-currency growth. The page stacks the five regions and quotes
    the growth rates the company printed, not ones recomputed from amounts the
    next year's release revises.
    """
    periods = staging["periods"]
    gdv = staging["gdv_by_region"]
    for key, values in gdv.items():
        if isinstance(values, list) and len(values) != len(periods):
            raise ValueError(f"gdv_by_region.{key} is not one value per quarter")
    world = gdv["worldwide_usd_b"]
    europe, us = gdv["europe_usd_b"], gdv["united_states_usd_b"]
    share = [e / w * 100 for e, w in zip(europe, world)]
    ahead = trailing_run([e - u for e, u in zip(europe, us)], lambda gap: gap > 0)
    gap = max(abs(sum(gdv[f"{code}_usd_b"][i] for _, code, _ in GDV_REGIONS) - world[i])
              for i in range(len(periods)))
    by_local = sorted(GDV_REGIONS, key=lambda region: gdv[f"{region[1]}_growth_local_pct"][-1],
                      reverse=True)
    return {
        "ref": "EX_GDV_REGION",
        "kind": "stacked_dual",
        "title": (
            f"分地区 GDV：本季 ${world[-1]:,}B，欧洲 ${europe[-1]:,}B 占 {share[-1]:.1f}%"
            + (f"，已连续 {ahead} 季高于美国的 ${us[-1]:,}B" if ahead >= 2 else
               f"，本季高于美国的 ${us[-1]:,}B" if ahead == 1 else
               f"，美国 ${us[-1]:,}B")
        ),
        "xlabels": [compact_period(period) for period in periods],
        "xrot": 90,
        "xstep": 4,
        "stacks": [{"name": name, "color": color, "values": gdv[f"{code}_usd_b"]}
                   for name, code, color in GDV_REGIONS],
        "line": {"name": "欧洲占全球 GDV (RHS) D", "color": "GREEN", "values": rounded(share),
                 "yfmt": "pct1", "ymax": 60},
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "$B",
        "ylab2": "%",
        "note": (
            "金额是业绩发布 Operating Performance 表按当季平均汇率折成的美元"
            f"（每季取当季发布首次印出的数，五个地区相加与 Worldwide 一栏最多差 ${gap}B，是舍入），"
            "所以欧洲占比里有汇率："
            f"本季欧洲本地货币增速 {signed(gdv['europe_growth_local_pct'][-1])}、"
            f"美元口径 {signed(gdv['europe_growth_usd_pct'][-1])}。"
            "本季各地区的本地货币增速（公司印的数）："
            + "、".join(f"{name} {signed(gdv[f'{code}_growth_local_pct'][-1])}"
                       for name, code, _ in by_local) + "。"
        ),
        "src_extra": ("各季业绩发布 8-K EX-99.1 的 Operating Performance 表"
                      "（All Mastercard Credit, Charge and Debit Programs 一段），逐季出处在 series 里；"
                      "欧洲占比为两栏相除的自算值。"),
    }


def release_source(staging: dict) -> dict:
    """This quarter's own earnings release in `sources`, found by its label."""
    label = f"{staging['periods'][-1]} 业绩发布 8-K EX-99.1"
    found = next((item for item in staging["sources"] if item["label"] == label), None)
    if found is None:
        raise ValueError(f"series `sources` has no entry labelled {label!r}: add this "
                         "quarter's release with the roll")
    return found


def periodic_report(staging: dict) -> str:
    """「与截至 … 的 10-Q」 when `sources` carries the quarter's own 10-Q / 10-K."""
    end = staging["latest"]["period_end"]
    for item in staging["sources"]:
        form = next((f for f in ("10-Q", "10-K") if f in item["label"]), None)
        if form and f"期末 {end}" in item["label"]:
            return f"与截至 {end} 的 {form}"
    return ""


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    pn = staging["payment_network_usd_m"]
    gross = sum(pn[line][-1] for line in ASSESSMENT_LINES)
    rebates = gross - pn["payment_network_net_revenue"][-1]
    return [f"Revenue ${pn['total_net_revenue'][-1] / 1000:.2f}B",
            f"Rebate ratio {rebates / gross * 100:.1f}%",
            f"VAS share {pn['value_added_services_net_revenue'][-1] / pn['total_net_revenue'][-1] * 100:.1f}%"]


def special_items_words(q: dict, index: int) -> str:
    """「$202M 重组」 / 「$82M 诉讼计提」 / both, read off the two filed lines."""
    parts = [f"${q[key][index]:,}M {name}"
             for key, name in (("restructuring_charge", "重组"), ("provision_for_litigation", "诉讼计提"))
             if q[key][index]]
    return "、".join(parts)


def special_items_sentence(q: dict, index: int) -> str:
    """Last quarter's and this quarter's special items, however many there are."""
    before, now = special_items_words(q, index - 1), special_items_words(q, index)
    if before and now:
        return f"上季的特殊项是 {before}、本季是 {now}，"
    if before:
        return f"上季的特殊项是 {before}、本季没有，"
    if now:
        return f"上季没有特殊项、本季是 {now}，"
    return "两季都没有特殊项。"


def closure_counts(block: dict) -> list[int]:
    """Per-label counts derived from the items, so a label and its tally cannot disagree.

    A label no item carries stays on the chart as a zero: the labels are the
    classes the stated rule sorts into, and 「0 条已验证」 is a finding."""
    stray = sorted({item["label"] for item in block["items"]} - set(block["labels"]))
    if stray:
        raise ValueError(f"followup_closure items carry labels {stray} the block does not list")
    return [sum(1 for item in block["items"] if item["label"] == label) for label in block["labels"]]


def rebate_ratios(staging: dict) -> list[float]:
    """Rebates over gross billings, per quarter of the disaggregation window."""
    pn = staging["payment_network_usd_m"]
    out = []
    for index, net in enumerate(pn["payment_network_net_revenue"]):
        if net is None:
            continue
        gross = sum(pn[line][index] for line in ASSESSMENT_LINES)
        out.append((gross - net) / gross * 100)
    return out


def repurchase_prices(staging: dict) -> list[float | None]:
    """The average price the company printed for each quarter's buybacks.

    Every 10-Q (Part II Item 2) and 10-K (Item 5) carries an Issuer Purchases
    table whose Total row gives the quarter's shares to the unit and the average
    price paid, on a cash basis; shares times price lands on the cash-flow
    statement's repurchases within $1M in every quarter. Cash over the release's
    share count -- printed to 0.1 million -- is what this page used to draw, and
    it missed the printed price by up to $10 (Q4 2023). A quarter without a
    buyback (2020Q2, the COVID suspension) has no price rather than a zero.
    """
    prices = staging["per_share"]["repurchase_avg_price_usd"]
    for period, price, spent in zip(staging["periods"], prices,
                                    staging["quarterly_usd_m"]["stock_repurchases"]):
        if (price is None) != (not spent):
            raise ValueError(f"{period}: buyback cash and the printed average price disagree on "
                             "whether there was a buyback")
    return list(prices)


def vas_ex_acquisitions(staging: dict) -> list[float | None]:
    """VAS currency-neutral growth less the acquisition share the release printed beside it.

    The release says so in the same sentence («This includes a 4 percentage point
    increase from acquisitions»); a quarter whose sentence names no acquisition
    has nothing to take away."""
    block = staging["segment_growth_printed_pct"]
    # Where the release prints the remainder itself («The remaining 15 percentage
    # point increase», Q1 2025, one more than 18 − 4 because of rounding), the
    # printed number is the one used.
    return [printed if printed is not None else None if value is None else value - (acquired or 0)
            for value, acquired, printed in zip(block["value_added_services_cn"],
                                                block["value_added_services_acquisitions_pp"],
                                                block["value_added_services_ex_acquisitions_printed_pp"])]


def board_added_authority(staging: dict) -> float:
    """New buyback authority granted in the quarter, in $M: the change in remaining
    authority plus what the quarter spent. Remaining authority is printed to the
    $0.1B, so anything under $100M is rounding."""
    remaining = staging["balance_sheet_usd_m"]["remaining_repurchase_authorization"]
    return remaining[-1] - remaining[-2] + staging["quarterly_usd_m"]["stock_repurchases"][-1]


def ytd_conversions(staging: dict) -> list[float]:
    """Operating cash flow over net income, year to date."""
    q = staging["quarterly_usd_m"]
    out: list[float] = []
    cash_sum = income_sum = 0.0
    for index, label in enumerate(staging["periods"]):
        if label.startswith("Q1"):
            cash_sum = income_sum = 0.0
        cash_sum += q["operating_cash_flow"][index]
        income_sum += q["net_income"][index]
        out.append(cash_sum / income_sum * 100)
    return out


def kpi_reading(staging: dict, reads: str) -> float:
    """The quarter's value of one tracked metric, read from the series.

    A current value typed into the threshold block was rounded before it was
    compared, and that moved the last printed digit of a headroom bar.
    """
    if reads == "rebate_ratio":
        return rebate_ratios(staging)[-1]
    if reads == "repurchase_price":
        return repurchase_prices(staging)[-1]
    if reads == "ytd_conversion":
        return ytd_conversions(staging)[-1]
    if reads == "vas_cn_ex_acquisitions":
        return vas_ex_acquisitions(staging)[-1]
    if reads == "payment_network_cn":
        return staging["segment_growth_printed_pct"]["payment_network_cn"][-1]
    block, key = reads.split(".")
    return staging[block][key][-1]


def kpi_entries(block: dict | None, key: str, staging: dict, part: str = "quantified") -> list[dict]:
    """A threshold block's entries with their value: read from the series where
    the series has it, typed with a source where only a release or deck does."""
    if not block:
        return []
    out = []
    for entry in block.get(part, []):
        if "reads" in entry:
            value = kpi_reading(staging, entry["reads"])
            if value is None:
                raise ValueError(f"threshold {entry['metric']!r}: the series has no reading this quarter")
            out.append({**entry, key: value})
        elif entry.get(key) is not None and entry.get("source"):
            out.append(dict(entry))
        else:
            raise ValueError(f"threshold {entry['metric']!r} has neither `reads` nor a sourced `{key}`")
    return out


# A report's thresholds come in two kinds. A 减仓 / 警示 / 跟踪 / 下调 line is
# defended: the good news is that the reading has not crossed it. A 加仓 / 解除 /
# 护城河 line is reached: the good news is that the reading has got there. Each
# tier's `direction` names the side that is good news, so one headroom axis
# reads both ways -- positive is the favourable side of that line.
GOOD_ROLES = ("加仓", "解除", "护城河")


def tier_label(entry: dict) -> str:
    """「单季回购金额（加仓线）」: one bar per tier, with the report's role for it."""
    return f"{entry['metric']}（{entry['role']}线）"


def on_good_side(entry: dict, key: str) -> bool:
    return headroom(entry["direction"], entry["threshold"], entry[key]) >= 0


def tier_hit(entry: dict, key: str) -> bool:
    """The tier's own trigger, on the number alone: a reached line is hit when the
    reading is on its side, a defended line when the reading has crossed it."""
    good = on_good_side(entry, key)
    return good if entry["role"] in GOOD_ROLES else not good


def tier_verb(entry: dict, key: str, when: str) -> str:
    """「达到上季加仓线 $4,500M」 / 「守住上季警示线 16.0%」 / 「击穿…」 / 「未达到…」."""
    good = on_good_side(entry, key)
    verb = (("达到" if good else "未达到") if entry["role"] in GOOD_ROLES else
            ("守住" if good else "击穿"))
    return f"{verb}{when}{entry['role']}线 {unit_text(entry['unit'], entry['threshold'])}"


def condition_met(entry: dict, staging: dict) -> bool | None:
    """A tier's non-numeric half (「且董事会扩大授权」): read from the series where
    it can be, typed with its source where only the call says it."""
    condition = entry.get("condition")
    if not condition:
        return None
    if condition.get("reads") == "board_added_authority":
        return board_added_authority(staging) >= 100
    if "reads" in condition:
        raise ValueError(f"unknown condition reading {condition['reads']!r}")
    if "met" in condition and condition.get("source"):
        return bool(condition["met"])
    raise ValueError(f"condition {condition['text']!r} has neither `reads` nor a sourced `met`")


def row_verdicts(entries: list[dict], key: str, block: dict, staging: dict) -> list[dict]:
    """Each report row's actions, settled the way the report wrote them.

    Tiers of one action in one row combine with 且 unless the tier says 或
    (`combine`), and a non-numeric condition has to hold as well: last
    quarter's buyback row reached its $4.5B line, but the other half -- the
    board widening the authorisation -- did not happen, so the row did not
    fire. Rows keep the order of their first tier."""
    groups: dict[tuple, list[dict]] = {}
    for entry in entries:
        groups.setdefault((entry["row"], entry["role"]), []).append(entry)
    out = []
    for (row, role), tiers in groups.items():
        hits = [tier_hit(tier, key) for tier in tiers]
        numeric = any(hits) if tiers[0].get("combine") == "or" else all(hits)
        conditions = [(tier["condition"]["text"], condition_met(tier, staging))
                      for tier in tiers if tier.get("condition")]
        blocked = [text for text, met in conditions if met is False]
        out.append({"row": row, "role": role, "name": block["rows"][str(row)], "tiers": tiers,
                    "numeric": numeric, "blocked": blocked if numeric else [],
                    "fired": numeric and not blocked})
    return out


def spaced(name: str) -> str:
    """「跨境 travel 的」 but 「回购的」: a space only after a Latin word."""
    return name + (" " if name[-1].isascii() and name[-1].isalpha() else "")


def threshold_lines(title: str, labels: list[str], actual: list[dict], tiers: list[dict], when: str,
                    *, fmt: str, ylab: str, note: str, src_extra: str) -> dict:
    """One tracked series (or two) with every tier the report set on it drawn as its
    own flat line -- green where reaching it is the good news, red where crossing it
    is the bad news. The multi-tier form of `threshold_exhibit`."""
    n = len(labels)
    series = list(actual)
    for tier in tiers:
        series.append({
            "name": (f"{when}{tier['role']}线 {unit_text(tier['unit'], tier['threshold'])}"
                     + (f"（需连续{cn_count(tier['quarters'])}季）" if tier.get("quarters") else "")),
            "values": [tier["threshold"]] * n,
            "color": "GREEN" if tier["role"] in GOOD_ROLES else "RED",
        })
    return {
        "kind": "lines",
        "title": title,
        "xlabels": labels,
        "xrot": 90,
        "series": series,
        "fmt": fmt,
        "yfmt": fmt,
        "label_fmt": fmt,
        "end_label": True,
        "ylab": ylab,
        "note": note,
        "src_extra": src_extra,
    }


def growth_text(value: float) -> str:
    return f"{value:+.0f}%"


def call_reading(staging: dict, reads: str) -> tuple[float, str]:
    """This quarter's actual for one item of a call's guidance, and how the page says it.

    The guidance is the call's wording; the actual is the release's or the series'.
    """
    snapshot = staging["current_snapshot"]
    neutral = snapshot["currency_neutral_growth_pct"]
    if reads == "net_revenue_cn":
        return neutral["net_revenue"], growth_text(neutral["net_revenue"])
    if reads == "fx_net_revenue_pp":
        total = staging["payment_network_usd_m"]["total_net_revenue"]
        reported = round(pct_change(total[-1], total[-5]))
        gap = reported - neutral["net_revenue"]
        return gap, (f"报告口径 {growth_text(reported)}、固定汇率 {growth_text(neutral['net_revenue'])}，"
                     f"{'顺风' if gap >= 0 else '逆风'} {abs(gap):.0f} ppt")
    if reads == "adjusted_opex_cn":
        inorganic = snapshot["adjusted_operating_expenses_inorganic_pp"]
        value = neutral["adjusted_operating_expenses"]
        return value, (f"调整后 {growth_text(value)}"
                       + (f"，其中收购与处置带来 {abs(inorganic):.0f} ppt 的{'好处' if inorganic < 0 else '拖累'}"
                          f"（剔除后约 {growth_text(value - inorganic)}）" if inorganic else ""))
    if reads == "adjusted_other_income_expense":
        value = snapshot["adjusted_other_income_expense_usd_m"]
        return value, unit_text("usd_m", value)
    if reads == "adjusted_tax_rate":
        value = snapshot["adjusted_effective_tax_rate_pct"]
        return value, f"{value:.1f}%"
    if reads == "rebate_ratio_qoq":
        ratios = rebate_ratios(staging)
        move = ratios[-1] - ratios[-2]
        return move, f"{ratios[-1]:.2f}%，上季 {ratios[-2]:.2f}%（环比 {signed(move, 2, 'pp')}）"
    raise ValueError(f"unknown call-guidance reading {reads!r}")


def call_verdict(item: dict, value: float) -> str:
    """How an actual sits against what the call gave: a range, a rough point, a direction."""
    guided = item.get("guided")
    if not guided:
        return "只给了措辞，没有上下限"
    if "low" in guided:
        return ("在区间内" if guided["low"] <= value <= guided["high"] else
                "高于区间" if value > guided["high"] else "低于区间")
    if "direction" in guided:
        went = "down" if value < 0 else "up" if value > 0 else "flat"
        return "方向与指引一致" if went == guided["direction"] else "方向与指引相反"
    # 「approximately $150 million」 has no tolerance, so the page states the gap
    # and does not call it met or missed.
    gap = abs(value) - abs(guided["point"])
    if gap == 0:
        return "与指引的约数相同"
    amount = (unit_text("usd_m", abs(gap)) if guided["unit"] == "usd_m" else f"{abs(gap):g} ppt")
    return f"绝对值比指引的约数{'小' if gap < 0 else '大'} {amount}（约数没有容差，不判定）"


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    period = periods[-1]
    labels = [compact_period(period) for period in periods]
    pn = staging["payment_network_usd_m"]
    q = staging["quarterly_usd_m"]
    ps = staging["per_share"]
    bs = staging["balance_sheet_usd_m"]
    drivers = staging["key_drivers_local_pct"]
    cn = staging["assessment_currency_neutral_growth_pct"]
    disclosure = staging["guidance_disclosure"]
    crosscheck = staging["adjusted_margin_crosscheck"]
    latest_meta = latest_block(staging, period=period)
    release = release_source(staging)
    snapshot = stamped_block(staging, "current_snapshot", period)
    consensus = stamped_block(staging, "market_expectation", period)
    closure = stamped_block(staging, "followup_closure", period)
    prior_kpi = stamped_block(staging, "prior_kpi_settlement", period)
    next_kpi = stamped_block(staging, "next_kpi", period)
    call = stamped_block(staging, "call_guidance", period)
    prior_call = stamped_block(staging, "prior_call_guidance", period)
    story = stamped_block(staging, "quarter_story", period) or {}

    net_revenue = pn["total_net_revenue"]

    # ── Two windows on this page, and the split is a disclosure split ────────
    # Everything on the income statement, the balance sheet, the cash flow and
    # the three key drivers runs the whole record. The revenue *disaggregation*
    # -- the four assessment lines, the payment-network and value-added-services
    # split, and the per-line currency-neutral growth rates -- does not exist
    # before 2022Q1 in any filing: Mastercard's revenue note carries none of
    # those lines in any 10-Q from 2018Q1 to 2023Q3 or any 10-K from FY2018 to
    # FY2025, no release in 2016-2022 disaggregates revenue at all, and 2016-2017
    # has no revenue note (ASC 606 was adopted modified-retrospective on
    # 2018-01-01). The repo's own 2022 quarters can only have come from the
    # restated comparatives in the 2023 filings, which is where they start.
    dis_from = next(index for index, value
                    in enumerate(pn["payment_network_net_revenue"])
                    if value is not None)
    dis_labels = labels[dis_from:]
    dis_periods = periods[dis_from:]
    network_net = pn["payment_network_net_revenue"][dis_from:]
    vas = pn["value_added_services_net_revenue"][dis_from:]
    dis_net_revenue = net_revenue[dis_from:]

    # ── The one derived line the whole page rests on ─────────────────────────
    # Gross billings is the sum of the four printed assessment lines; the
    # payment network is printed net of rebates. The difference is therefore
    # the rebate, from two filed numbers and no estimate.
    gross = [sum(pn[line][index] for line in ASSESSMENT_LINES)
             for index in range(dis_from, len(periods))]
    rebates = [g - n for g, n in zip(gross, network_net)]
    rebate_ratio = [r / g * 100 for r, g in zip(rebates, gross)]
    ratio_change = increments(rebate_ratio)

    gross_yoy = yoy(gross)
    network_yoy = yoy(network_net)
    gross_step = increments(gross)
    network_step = increments(network_net)
    rebate_step = increments(rebates)
    vas_step = increments(vas)
    net_step = increments(dis_net_revenue)
    vas_share = [v / total * 100 for v, total in zip(vas, dis_net_revenue)]

    # The company's own adjusted operating margin, rebuilt from filed lines:
    # its only operating-expense adjustments are the litigation provision (its
    # own income-statement line) and the restructuring charge.
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
    # Mastercard bought back nothing in 2020Q2 -- the COVID suspension -- so the
    # implied price is undefined there rather than zero. A zero would be drawn
    # as "they paid nothing per share", which is a different and false claim.
    repurchase_price = repurchase_prices(staging)
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
    # front-loaded, so the same point in the year is the comparable one.
    ytd_conversion = ytd_conversions(staging)

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

    latest = len(periods) - 1
    dis_latest = len(dis_periods) - 1
    n_ytd = int(period[1])
    ytd_words = YTD_WORDS[n_ytd]
    year_start = latest - n_ytd  # the last quarter of the previous year

    def ytd_growth(values: list[float]) -> float:
        return pct_change(sum(values[-n_ytd:]), sum(values[-n_ytd - 4:-4]))

    ocf_ytd = ytd_growth(q["operating_cash_flow"])
    income_ytd = ytd_growth(q["net_income"])

    comparable = ratio_change[DIS_YOY_FROM:]
    ratio_up = sum(1 for value in comparable if value > 0)
    ratio_down = len(comparable) - ratio_up
    worst_ratio_move = min(comparable)
    ratio_qoq_down = [index for index in range(1, len(rebate_ratio))
                      if rebate_ratio[index] < rebate_ratio[index - 1]]
    # The one seasonal fact the ratio notes lean on: the annual peak is always
    # the fourth quarter, and the first half gives some of it back.
    q4_peaks = all(
        max((rebate_ratio[i], dis_periods[i]) for i in range(len(dis_periods))
            if dis_periods[i].endswith(year))[1].startswith("Q4")
        for year in {label[-4:] for label in dis_periods if label.startswith("Q4")})
    h1_falls = [dis_periods[i] for i in ratio_qoq_down]
    h1_every_year = all(
        f"{quarter} {year}" in h1_falls
        for year in {label[-4:] for label in dis_periods[DIS_YOY_FROM:]}
        for quarter in ("Q1", "Q2")
        if f"{quarter} {year}" in dis_periods)

    run = plateau_run(network_step)
    plateau = network_step[-run:] if run else []
    plateau_start = len(network_step) - run
    run_words = cn_count(run)

    # Two "how long has this been true" counts the copy quotes; both are read
    # off the series rather than typed, so a new quarter cannot leave them stale.
    vas_gap = [
        None if network is None else pct_change(vas[index], vas[index - 4]) - network
        for index, network in enumerate(network_yoy)
    ]
    gap_run = trailing_run(vas_gap, lambda value: value >= 8)
    price_run = 0
    for value in reversed(repurchase_price[:-1]):
        if value is None or value <= repurchase_price[latest]:
            break
        price_run += 1
    price_fall = falling_run([value for value in repurchase_price])
    leverage = [debt / equity for debt, equity in zip(total_debt, bs["total_equity"])]
    driver_band = drivers["gdv"][-6:] + drivers["switched"][-6:]
    cross_fall = falling_run(drivers["cross_border"])
    record_buyback = q["stock_repurchases"][latest] == max(q["stock_repurchases"])
    # A new authorisation shows up as remaining authority that fell by less than
    # the quarter's buyback; the release rounds both to US$0.1B.
    new_authority = (bs["remaining_repurchase_authorization"][latest]
                     - bs["remaining_repurchase_authorization"][latest - 1]
                     + q["stock_repurchases"][latest])
    cross_above = trailing_run(
        [c - d for c, d in zip(pn["cross_border_assessments"][dis_from:],
                               pn["domestic_assessments"][dis_from:])],
        lambda value: value > 0)
    largest_line = max(ASSESSMENT_LINES, key=lambda line: pn[line][latest])

    period_end = latest_meta["period_end"]
    source = (
        f'Source: <a href="{release["url"]}" rel="noopener">'
        f'Mastercard {period} 业绩发布（8-K EX-99.1）</a>{periodic_report(staging)}'
        '（逐季数据经 SEC EDGAR 的 10-Q / 10-K / 8-K 回源；电话会措辞见核对表）。'
    )
    source_filings = (
        "毛计费四条线取自各期 10-Q / 10-K 管理层讨论与分析里的「Key Metrics related to the "
        "Payment Network」表，支付网络与增值服务的净收入取自同期收入附注；返点为两者相减的自算值。"
    )

    def source_note(detail: str) -> str:
        return f"{detail}；历史期同口径。自算项目均可在核对表中复核。"

    segment = staging["segment_growth_printed_pct"]
    for key, values in segment.items():
        if isinstance(values, list) and len(values) != len(periods):
            raise ValueError(f"segment_growth_printed_pct.{key} is not one value per quarter")
    prior_entries = kpi_entries(prior_kpi, "actual", staging)
    prior_pending = kpi_entries(prior_kpi, "actual", staging, "pending")
    next_entries = kpi_entries(next_kpi, "current", staging)
    vas_cn_series = segment["value_added_services_cn"]
    vas_acq_series = segment["value_added_services_acquisitions_pp"]
    vas_ex = vas_ex_acquisitions(staging)
    qtd = (snapshot or {}).get("quarter_to_date_repurchase")
    # The figures a quarter's own sentences may quote; typed into none of them.
    figures = {
        "auth_prev": f"${bs['remaining_repurchase_authorization'][latest - 1] / 1000:.1f}B",
        "auth_now": f"${bs['remaining_repurchase_authorization'][latest] / 1000:.1f}B",
        "price_prev": f"${repurchase_price[latest - 1]:.2f}",
        "price": f"${repurchase_price[latest]:.2f}",
        "buyback": f"${q['stock_repurchases'][latest]:,}M",
        "vas_share": f"{vas_share[dis_latest]:.1f}%",
        "vas_cn_now": growth_text(vas_cn_series[latest]),
        "vas_cn_prev": growth_text(vas_cn_series[latest - 1]),
        "margin_now": f"{adjusted_margin[latest]:.1f}%",
        "margin_prior": f"{adjusted_margin[latest - 4]:.1f}%",
        "ocf_ytd": signed(ocf_ytd),
        "income_ytd": f"{income_ytd:+.1f}%",
        "ytd_words": ytd_words,
        "prior_period": periods[latest - 4],
        "gdv_prior": f"{drivers['gdv'][latest - 4]:g}%",
        "cross_prior": f"{drivers['cross_border'][latest - 4]:g}%",
        "switched_prior": f"{drivers['switched'][latest - 4]:g}%",
    }
    if snapshot:
        figures["opex_cn"] = f"{snapshot['currency_neutral_growth_pct']['adjusted_operating_expenses']:g}"
    if qtd:
        figures["qtd_day"] = str(int(qtd["through"][-2:]))
        figures["qtd_cost"] = unit_text("usd_m", qtd["cost_usd_m"])

    # Three of the four run the whole record; the rebate ratio cannot, because
    # its denominator is the revenue disaggregation. It is padded to the same
    # axis rather than given a shorter one, so the four threshold charts stay
    # comparable and the gap is visible instead of implied.
    tracked = {
        "quarterly_usd_m.stock_repurchases": (q["stock_repurchases"], "f0c", "$M", "单季回购"),
        "repurchase_price": (repurchase_price, "usd0", "$/股", "回购均价（公司印）"),
        "rebate_ratio": ([None] * dis_from + rebate_ratio,
                         "pct1", "占毛计费", "返点占比 D"),
        "ytd_conversion": (ytd_conversion, "pct1", "累计比率", "年初至今 OCF / 净利润 D"),
    }

    def tracking_charts(entries, value_key, threshold_label, headline) -> list[dict]:
        charts = []
        for entry in entries:
            if entry.get("reads") not in tracked:
                continue
            values, fmt, ylab, actual_name = tracked[entry["reads"]]
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
                    + ("均价是 10-Q 第二部分第 2 项表里公司自己印的数（股数印到个位）。"
                       if entry["reads"] == "repurchase_price" else "")
                    + ("第一季只含三个月、第二季含六个月，这条线因此每年重新起跳；"
                       "可比的是同一季之间的高低，不是相邻两点。"
                       if entry["reads"] == "ytd_conversion" else "")
                ),
                src_extra=(
                    "实际值来自各期 10-Q / 10-K 与当季 earnings release；"
                    "阈值为本地研究设定，不是公司指引。"
                ),
            ))
        return charts

    # ── 一、上季兑现 ─────────────────────────────────────────────────────────
    settled_charts = []
    if closure:
        counts = closure_counts(closure)
        settled_charts.append({
            "kind": "bars_labeled",
            "title": (f"上季 {len(closure['items'])} 条待验证问题："
                      + "、".join(f"{count} 条{label}" for label, count in zip(closure["labels"], counts))),
            "xlabels": closure["labels"],
            "values": counts,
            "legend": "问题条数",
            "fmt": "f0",
            "yfmt": "f0",
            "label_fmt": "f0",
            "ylab": "条",
            "note": (closure["note"] + "<br>"
                     + "<br>".join(f"{item['n']}. {item['question']} —— 判定「<b>{item['verdict']}</b>」，"
                                   f"打分「{item['score']}」。{fill_story(item['evidence'], figures)}。"
                                   for item in closure["items"])),
            "src_extra": f"问题清单：{closure['set_in']}；判定与打分：{closure['closed_in']}。",
        })

    def recent_vas_words(count: int) -> str:
        """「Q2'25 +22%（其中收购 +4pp）」 for the last few quarters, as printed."""
        words = []
        for index in range(max(latest - count + 1, 0), latest + 1):
            if vas_cn_series[index] is None:
                continue
            acquired = vas_acq_series[index]
            note = ("未提收购" if acquired is None else
                    "收购贡献不到 0.5pp" if acquired == 0 else f"其中收购 +{acquired:g}pp")
            words.append(f"{labels[index]} {growth_text(vas_cn_series[index])}（{note}）")
        return "、".join(words)

    def streak(values: list, floor: float, since: int = 0) -> int:
        run = 0
        for index in range(latest, since - 1, -1):
            if values[index] is None or values[index] < floor:
                break
            run += 1
        return run

    def settled_track(reads: str, tiers: list[dict], pending: list[dict]) -> dict | None:
        """Last report's tiers on one series, drawn against this quarter's reading."""
        lead = tiers[0] if tiers else pending[0]
        value = lead["actual"]
        verbs = "、".join(tier_verb(tier, "actual", "上季") for tier in tiers)
        blocked = [tier["condition"]["text"] for tier in tiers
                   if tier_hit(tier, "actual") and condition_met(tier, staging) is False]
        src = "阈值：" + prior_kpi["set_in"] + "，是研究设定，不是公司指引。"
        if reads == "quarterly_usd_m.stock_repurchases":
            added = board_added_authority(staging)
            words = "；".join(f"「{tier['words']}」" for tier in tiers)
            conditional = [tier for tier in tiers if tier.get("condition")]
            return threshold_lines(
                f"{lead['metric']}：本季 {unit_text('usd_m', value)}"
                + (f" 创 {len(periods)} 季新高" if record_buyback else "")
                + f"，{verbs}"
                + (f"；加仓的另一半「{blocked[0]}」没有成立" if blocked else ""),
                labels, [{"name": "单季回购金额", "values": q["stock_repurchases"], "color": "NAVY"}],
                tiers, "上季", fmt="f0c", ylab="$M",
                note=(
                    "回购金额是现金流量表「Purchases of treasury stock」的逐季值（10-Q 只印年初至今，逐季相减）。"
                    f"上季报告第 8 节的原文是{words}。"
                    + (f"剩余授权从季初 {figures['auth_prev']} 降到季末 {figures['auth_now']}，"
                       + ("降幅就是本季花掉的回购额，董事会本季没有扩大授权"
                          if added < 100 else f"董事会本季新增了约 {unit_text('usd_m', added)} 授权")
                       + "。")
                    + "".join(
                        f"{tier['role']}那一档还要求「{tier['condition']['text']}」：金额"
                        + ("" if tier_hit(tier, "actual") else "没有")
                        + ("达到" if tier["role"] in GOOD_ROLES else "越过")
                        + f" {unit_text(tier['unit'], tier['threshold'])}，另一半"
                        + ("成立" if condition_met(tier, staging) else "不成立")
                        + ("，这一档触发。" if tier_hit(tier, "actual") and condition_met(tier, staging)
                           else "，这一档不触发。")
                        for tier in conditional)
                ),
                src_extra=src + "".join(f"「{tier['condition']['text']}」：{tier['condition']['source']}。"
                                        for tier in conditional if tier["condition"].get("source")),
            )
        if reads == "vas_cn_ex_acquisitions":
            since = periods.index(prior_kpi["set_in_period"])
            pending_words = "".join(
                f"另一档「{tier['words']}」要看连续{cn_count(tier['quarters'])}季："
                f"本季报告从设阈值的 {labels[since]} 起算，写「{tier['report_count']}」"
                f"（从 {labels[since]} 起数是 {streak(vas_ex, tier['threshold'], since)} 季）；"
                f"按上面这些申报数往前数，剔除收购后已连续 {streak(vas_ex, tier['threshold'])} 季不低于 "
                f"{unit_text(tier['unit'], tier['threshold'])}。两种数法给出不同的结论，本页两个数都列出，不替读者选。"
                for tier in pending)
            return threshold_lines(
                f"{lead['metric']}：本季 {unit_text(lead['unit'], value)}，{verbs}",
                labels,
                [{"name": "增值服务固定汇率同比（公司印）", "values": vas_cn_series, "color": "GRAY"},
                 {"name": "剔除公司印的收购贡献 D", "values": vas_ex, "color": "NAVY"}],
                tiers + pending, "上季", fmt="pct0", ylab="同比增速",
                note=(
                    "上一份报告的阈值写的是剔除收购贡献的固定汇率增速。业绩发布在同一句里印出收购贡献"
                    "（「This includes a 4 percentage point increase from acquisitions」），深蓝线就是两个数相减；"
                    + (f"撑起连续记录的这几季加上它前面那一季：{recent_vas_words(streak(vas_ex, pending[0]['threshold']) + 1)}。"
                       if pending else f"最近四季：{recent_vas_words(4)}。")
                    + f"两条线从 {labels[vas_cn_series.index(next(v for v in vas_cn_series if v is not None))]} 起才有："
                    "增值服务作为一条收入线是 2023 年启用的新口径，2023 年的业绩发布才开始印它的增速。"
                    + pending_words
                ),
                src_extra=src + "增速与收购贡献：各季业绩发布正文（Q1–Q3 另在同季 10-Q 的管理层讨论与分析里核过，逐格相同）。",
            )
        return None

    if prior_entries:
        verdicts = row_verdicts(prior_entries, "actual", prior_kpi, staging)
        fired = [v for v in verdicts if v["fired"]]
        blocked_rows = [v for v in verdicts if v["numeric"] and v["blocked"]]
        typed = [entry for entry in prior_entries if "reads" not in entry]
        typed_sources = list(dict.fromkeys(entry["source"] for entry in typed))
        not_settled = prior_kpi.get("unsettleable", []) + prior_kpi.get("retired", [])

        def row_words(row: int) -> str:
            parts = []
            for v in (v for v in verdicts if v["row"] == row):
                parts.append(f"{v['role']}" + ("成立" if v["fired"] else "不成立" if v["blocked"] else "未触发")
                             + (f"（数字过线，但「{'、'.join(v['blocked'])}」没有成立）" if v["blocked"] else ""))
            return "，".join(parts)

        rows_in_order = list(dict.fromkeys(v["row"] for v in verdicts))
        settled_charts.append(headroom_exhibit(
            f"上季 {len(prior_entries)} 条量化阈值："
            + ("、".join(f"{spaced(v['name'])}的{v['role']}条件成立" for v in fired) if fired else "没有一行的条件成立")
            + "".join(f"；{v['name']}过了{v['role']}线，但「{'、'.join(v['blocked'])}」没有成立" for v in blocked_rows),
            [{**entry, "metric": tier_label(entry)} for entry in prior_entries],
            "actual",
            (
                "正值 = 在该线的有利一侧：减仓、警示、跟踪线是还没越过，加仓线是已经达到。"
                "阈值与方向逐字取自上季报告第 8 节（原文见核对表）；同一行设了几档的逐档一根柱，"
                "同一行同一动作的几档按原文的「且 / 或」合起来读。逐行看："
                + "；".join(f"{prior_kpi['rows'][str(row)]} —— {row_words(row)}" for row in rows_in_order)
                + "。"
                + "".join(f"还有一档要连续{cn_count(tier['quarters'])}季才能结算：{tier['metric']}「{tier['words']}」，"
                          f"见下面增值服务那张图。" for tier in prior_pending)
                + (f"不结算的{cn_count(len(not_settled))}行："
                   + "；".join(f"{item['name']}（原文「{item['words']}」）—— {item['why']}" for item in not_settled)
                   + "。" if not_settled else "")
                + fill_story(story.get("settled_note_tail", ""),
                             {**figures, "rows_cn": cn_count(len(prior_kpi["rows"]))})
            ),
            src_extra=(
                f"阈值：{prior_kpi['set_in']}，是研究设定，不是公司指引；实际值：本季申报与业绩发布"
                + (f"，其中{'、'.join(dict.fromkeys(entry['metric'] for entry in typed))}取自：{'；'.join(typed_sources)}"
                   if typed else "")
                + "。"
            ),
        ))
        settled_charts[-1]["positive_label"] = "有利一侧"
        settled_charts[-1]["negative_label"] = "不利一侧"
        by_reads: dict[str, list[dict]] = {}
        for entry in prior_entries + prior_pending:
            if "reads" in entry:
                by_reads.setdefault(entry["reads"], []).append(entry)
        for reads, group in by_reads.items():
            chart = settled_track(reads, [e for e in group if e in prior_entries],
                                  [e for e in group if e in prior_pending])
            if chart:
                settled_charts.append(chart)
    # The three key drivers are this quarter's reading of volume, not a
    # threshold last quarter set: last quarter's travel line lives in the
    # investor deck, not in these three. The chart is drawn among the
    # quarter's highlights (see where `drivers_chart` is placed below).
    band_low, band_high = min(driver_band), max(driver_band)
    drivers_chart = {
        "ref": "EX_DRIVERS",
        "kind": "lines",
        "title": (
            "Key Business Drivers 的三条量："
            + (f"跨境量增速已连续{cn_count(cross_fall)}季走低到 {drivers['cross_border'][latest]}%，"
               if cross_fall >= 2 else f"跨境量增速本季 {drivers['cross_border'][latest]}%，")
            + f"GDV 与换手笔数六个季度都在 {band_low}–{band_high}% "
            + ("的窄带里" if band_high - band_low <= NARROW_BAND_PP else "之间")
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
            story.get("drivers_lead", "")
            + "<b>申报文件里没有这个拆分</b>。"
            + (("三条都指向同一件事：量的贡献在变薄——"
                f"跨境量连续{cn_count(cross_fall)}季走低（"
                + " → ".join(f"{value}%" for value in drivers["cross_border"][-cross_fall - 1:])
                + "），") if cross_fall >= 2 else "")
            + f"GDV 与换手笔数六个季度都落在 {band_low}–{band_high}% 之间。"
            "2022 年的报告增速被俄罗斯业务退出压低：公司在 2022 年起的 10-Q 里另给了剔除俄罗斯的口径"
            "（例如 2022Q2 跨境量报告 +58%、剔除后 +64%），那几个高点来自疫情后的反弹，不是退出的基数效应。"
        ),
        "src_extra": (
            "三条驱动指标的季度增速取自各期 10-Q 的「Key Metrics」表；第四季没有 10-Q，"
            "取自当季 earnings release 的 Key Business Drivers 表。"
            "跨境量与换手笔数只披露增速；GDV 另有分地区金额（业绩发布的 Operating Performance 表），见「分地区 GDV」那张图。"
            + fill_story(story.get("drivers_src_tail", ""), figures)
        ),
    }

    # ── 二、本季重点 ─────────────────────────────────────────────────────────
    cross_cn = cn["cross_border"][latest]
    cross_growth = (f"{cross_cn:+.0f}%" if cross_cn is not None else
                    signed(pct_change(pn["cross_border_assessments"][latest],
                                      pn["cross_border_assessments"][latest - 4]), 0))
    rebates_printed = (snapshot or {}).get("rebates_printed")
    rebate_check = ""
    if rebates_printed:
        if rebates_printed["quarter_usd_m"] != rebates[dis_latest]:
            raise ValueError("current_snapshot.rebates_printed.quarter_usd_m is not the subtraction: "
                             "check the 10-Q against the assessment lines")
        ytd_rebates = sum(rebates[-n_ytd:])
        ytd_prior = sum(rebates[-n_ytd - 4:-4])
        rebate_check = (
            f"10-Q 的管理层讨论与分析里用一句话印着本季返点 ${rebates_printed['quarter_usd_m']:,}M"
            + (f"、{ytd_words} ${rebates_printed['ytd_usd_m']:,}M" if n_ytd > 1 else "")
            + "，与本页的减法一分不差；公司说本季同比 "
            f"+{rebates_printed['quarter_growth_pct']}%，减法给出 {pct_change(rebates[dis_latest], rebates[dis_latest - 4]):+.2f}%"
            + (f"，{ytd_words}公司说 +{rebates_printed['ytd_growth_pct']}%、减法给出 "
               f"{pct_change(ytd_rebates, ytd_prior):+.2f}%" if n_ytd > 1 else "")
            + "，四舍五入后一致。"
        )
    vas_increment_share = vas_step[dis_latest] / net_step[dis_latest] * 100
    highlights = [
        {
            "ref": "EX_LEGS",
            "kind": "grouped_bars",
            "title": (
                f"净收入的同比增量拆成三条腿：毛计费 +${gross_step[dis_latest]:,.0f}M、"
                f"返点 −${rebate_step[dis_latest]:,.0f}M、增值服务 +${vas_step[dis_latest]:,.0f}M"
            ),
            "xlabels": dis_labels[DIS_YOY_FROM:],
            "xrot": 90,
            "groups": [
                {"name": "毛计费腿", "color": "NAVY", "values": rounded(gross_step[DIS_YOY_FROM:])},
                {"name": "返点腿", "color": "RED",
                 "values": rounded([-value for value in rebate_step[DIS_YOY_FROM:]])},
                {"name": "增值服务腿", "color": "GOLD", "values": rounded(vas_step[DIS_YOY_FROM:])},
            ],
            "bar_labels": False,
            "fmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M vs 去年同期",
            "note": (
                "这不是估计，是恒等式：净收入 = 四条计费线合计 − 返点 + 增值服务，"
                "所以同比增量<b>恰好</b>等于三条腿之和，"
                f"本季 ${gross_step[dis_latest]:,.0f} − ${rebate_step[dis_latest]:,.0f} + "
                f"${vas_step[dis_latest]:,.0f} = ${net_step[dis_latest]:,.0f}M，与申报的净收入增量一分不差。"
                f"<b>读数：</b>返点腿吃掉了毛计费腿的 "
                f"{rebate_step[dis_latest] / gross_step[dis_latest] * 100:.0f}%，"
                f"剩给支付网络的只有 ${network_step[dis_latest]:,.0f}M；"
                f"净增量里 {vas_increment_share:.0f}% 来自增值服务，"
                "而增值服务不承担返点。"
            ),
            "src_extra": source_filings,
        },
        {
            "ref": "EX_PLATEAU",
            "kind": "lines",
            "title": (
                f"毛计费的同比增量从 ${gross_step[DIS_YOY_FROM]:,.0f}M "
                f"{'涨到' if gross_step[dis_latest] > gross_step[DIS_YOY_FROM] else '降到'} "
                f"${gross_step[dis_latest]:,.0f}M"
                + (f"，落到净支付网络收入的增量连续{run_words}季卡在 ${min(plateau):,.0f}–${max(plateau):,.0f}M"
                   if run >= 4 else
                   f"，落到净支付网络收入的增量本季是 ${network_step[dis_latest]:,.0f}M")
            ),
            "xlabels": dis_labels[DIS_YOY_FROM:],
            "xrot": 90,
            "series": [
                {"name": "毛计费同比增量", "values": rounded(gross_step[DIS_YOY_FROM:]), "color": "NAVY"},
                {"name": "净支付网络收入同比增量", "values": rounded(network_step[DIS_YOY_FROM:]), "color": "GOLD"},
            ],
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "zero_base": True,
            "end_label": True,
            "ylab": "$M vs 去年同期",
            "note": (
                "<b>这是全页最要紧的一张。</b>两条线之间的缺口就是返点腿。"
                f"毛计费的年增量从 {dis_labels[DIS_YOY_FROM]} 到本季"
                f"{'增加' if gross_step[dis_latest] > gross_step[DIS_YOY_FROM] else '减少'}了 "
                f"{abs(pct_change(gross_step[dis_latest], gross_step[DIS_YOY_FROM])):.0f}%"
                + (("，而它落到净收入上的部分几乎没有动："
                    + "、".join(f"{dis_labels[index]} ${network_step[index]:,.0f}M"
                               for index in range(plateau_start, len(dis_periods)))
                    + "。")
                   if run >= 4 else "。")
                + (f"多计的费全部被返点接走了，所以「跨境计费同比 {cross_growth}」这类数字"
                   "在毛口径上成立，在净口径上不成立。"
                   if run >= 4 and gross_step[dis_latest] > gross_step[plateau_start]
                   and network_step[dis_latest] <= network_step[plateau_start] else "")
            ),
            "src_extra": source_filings,
        },
        {
            "ref": "EX_RATIO",
            "kind": "gs_line",
            "title": (
                f"返点占毛计费从 {rebate_ratio[0]:.1f}% 升到 {rebate_ratio[dis_latest]:.1f}%，"
                f"峰值 {max(rebate_ratio):.1f}% 出现在 "
                f"{dis_labels[rebate_ratio.index(max(rebate_ratio))]}"
            ) if rebate_ratio[dis_latest] > rebate_ratio[0] else (
                f"返点占毛计费从 {rebate_ratio[0]:.1f}% 降到 {rebate_ratio[dis_latest]:.1f}%，"
                f"峰值 {max(rebate_ratio):.1f}% 出现在 "
                f"{dis_labels[rebate_ratio.index(max(rebate_ratio))]}"
            ),
            "xlabels": dis_labels,
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
                f"本季环比 {signed(rebate_ratio[dis_latest] - rebate_ratio[dis_latest - 1], 2, 'pp')}"
                + ((f" 是季节性的回落：{len(rebate_ratio) - 1} 次环比里有 {len(ratio_qoq_down)} 次下降，"
                    f"{dis_periods[DIS_YOY_FROM][-4:]} 年起每年的第一、二季都比前一季低，而每年的峰值都在第四季。"
                    if h1_every_year and q4_peaks else
                    f"：{len(rebate_ratio) - 1} 次环比里有 {len(ratio_qoq_down)} 次下降。")
                   if rebate_ratio[dis_latest] < rebate_ratio[dis_latest - 1] else "。")
                + story.get("ratio_call", "")
                + (f"可比的 {ratio_up + ratio_down} 次同比里只有一次下降（见下一张）。" if ratio_down == 1 else
                   f"可比的 {ratio_up + ratio_down} 次同比里 {ratio_down} 次下降（见下一张）。")
            ),
            "src_extra": source_filings + rebate_check,
        },
        {
            "ref": "EX_RATIO_YOY",
            "kind": "diverging_bars",
            "title": (
                f"返点占比的同比变化：{ratio_up + ratio_down} 个可比季里 {ratio_up} 次上升，"
                + (f"唯一一次下降只有 {abs(worst_ratio_move):.2f}pp" if ratio_down == 1 else
                   f"{ratio_down} 次下降，最大一次 {abs(worst_ratio_move):.2f}pp" if ratio_down else
                   "没有一次下降")
            ),
            "xlabels": dis_labels[DIS_YOY_FROM:],
            "xrot": 90,
            "values": rounded(ratio_change[DIS_YOY_FROM:]),
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
                f"<b>这个比例有没有回过头</b>。{ratio_up + ratio_down} 次里"
                + (f"只有一次，而且只有 {abs(worst_ratio_move):.2f}pp。" if ratio_down == 1 else
                   f"有 {ratio_down} 次，最大一次 {abs(worst_ratio_move):.2f}pp。" if ratio_down else
                   "一次都没有。")
                + ("一条几乎单向的比率不是「这一季偏高」，是结构。" if ratio_down * 5 <= ratio_up + ratio_down else "")
                + "注意方向：正值代表公司让出去的比例更大，不是更小。"
            ),
            "src_extra": source_filings,
        },
    ]
    cross_spread = spreads["跨境计费 vs 跨境量"]
    clearing = spreads["清算计费 vs 换手笔数"]
    cross_record = cross_spread[latest] is not None and cross_spread[latest] == max(
        value for value in cross_spread if value is not None)
    cn_q4_gaps = [periods[index] for index, value in enumerate(cn["cross_border"])
                  if value is None and periods[index].startswith("Q4")
                  and any(v is not None for v in cn["cross_border"][:index])]
    cn_first = next(periods[index] for index, value in enumerate(cn["cross_border"]) if value is not None)
    before = next((index for index in range(latest - 1, -1, -1) if clearing[index] is not None), None)
    if cross_spread[latest] is not None and clearing[latest] is not None and before is not None:
        spread_title = (
            f"固定汇率的价差：跨境这条本季 {cross_spread[latest]:+.0f}pp"
            + ("，是记录里最高的一次" if cross_record else "")
            + (f"；清算那条从{'上季' if before == latest - 1 else ' ' + labels[before] + ' '}的 {clearing[before]:+.0f}pp "
               + ("收窄到" if clearing[latest] < clearing[before] else "扩大到")
               + f" {clearing[latest]:+.0f}pp"
               if clearing[latest] != clearing[before] else
               f"；清算那条与{'上季' if before == latest - 1 else ' ' + labels[before] + ' '}持平在 {clearing[latest]:+.0f}pp")
        )
    else:
        spread_title = "固定汇率的价差：本季没有各条计费线的固定汇率季度增速"
    highlights += [
        {
            "ref": "EX_SPREAD",
            "kind": "lines",
            "title": spread_title,
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
                f"{cn_first[-4:]} 年以后每个第四季都是缺口，因为公司只在当季 10-Q 里给出该季各条线的固定汇率增速，"
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
                f"增值服务已占净收入 {vas_share[dis_latest]:.1f}%，"
                f"{dis_labels[0]} 是 {vas_share[0]:.1f}%；"
                f"柱子回到 {labels[0]}，占比那条线回不到"
            ),
            "xlabels": labels,
            "xrot": 90,
            "xstep": 4,
            "values": net_revenue,
            "legend": "净收入",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "ylab2": "增值服务占比",
            "yoy": {
                "name": "增值服务 / 净收入 (RHS) D",
                "values": [None] * dis_from + rounded(vas_share),
                "color": "GOLD",
                "yfmt": "pct1",
            },
            "note": (
                f"增值服务本季 ${vas[dis_latest]:,}M、同比 {pct_change(vas[dis_latest], vas[dis_latest - 4]):+.1f}%"
                + (f"（公司口径固定汇率 +{snapshot['currency_neutral_growth_pct']['value_added_services']}%）"
                   if snapshot else "")
                + story.get("vas_organic", "。")
                + f"<b>柱子有 {len(periods)} 季，金色那条只有 {len(dis_periods)} 季 —— 那不是缺数据。</b>"
                "净收入是损益表第一行，公司一直在印；把它拆成支付网络与增值服务两半，"
                f"则是 {periods[dis_from][-4:]}{periods[dis_from][:2]} 才开始的披露。"
                "这条线之所以关键，是因为增值服务不进返点的分母也不进它的分子："
                "它是公司唯一一块收入不必先经过发卡行分成的业务。"
            ),
            "src_extra": source_filings,
        },
        drivers_chart,
    ]
    conversion_low = min((value, index) for index, value in enumerate(trailing_conversion)
                         if value is not None)
    low_label = periods[conversion_low[1]]
    amort_now, amort_then = (sum(q["amortization_of_customer_incentives"][-n_ytd:]),
                             sum(q["amortization_of_customer_incentives"][-n_ytd - 4:-4]))
    amort_before = sum(q["amortization_of_customer_incentives"][-n_ytd - 8:-8])
    amort_growth = pct_change(amort_now, amort_then)
    amort_faster = amort_growth > pct_change(amort_then, amort_before)
    highlights += [
        {
            "ref": "EX_CASH",
            "kind": "lines",
            "title": (
                f"滚动四季经营现金流 / 净利润从 {trailing_conversion[latest - 4]:.0f}% "
                f"{'降到' if trailing_conversion[latest] < trailing_conversion[latest - 4] else '升到'} "
                f"{trailing_conversion[latest]:.0f}%；{ytd_words}口径是 "
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
                + (("深蓝线消掉了季节性，方向一样：从四个季度前的 "
                    f"{trailing_conversion[latest - 4]:.0f}% 掉到 {trailing_conversion[latest]:.0f}%，"
                    "一年抹掉了 "
                    f"{trailing_conversion[latest - 4] - trailing_conversion[latest]:.0f}pp。"
                    + (f"<b>但它不是窗口里的最低点</b>：{low_label[-4:]} 年第{cn_ordinal(int(low_label[1]))}季这条线曾低到 "
                       f"{conversion_low[0]:.0f}%，所以现在的读数是「回到几年前的水平」，不是「破了记录」。"
                       if conversion_low[1] != latest else
                       "<b>这是窗口里的最低点。</b>"))
                   if trailing_conversion[latest] < trailing_conversion[latest - 4]
                   and ytd_conversion[latest] < ytd_conversion[latest - 4] else
                   "深蓝线消掉了季节性：四个季度前是 "
                   f"{trailing_conversion[latest - 4]:.0f}%，本季 {trailing_conversion[latest]:.0f}%。")
                + ("下一张说明缺口去了哪里。" if ytd_conversion[latest] < ytd_conversion[latest - 4] else "")
            ),
            "src_extra": source_note(
                "经营现金流与净利润逐季来自现金流量表（10-Q 只按年初至今披露，"
                "逐季由相邻两个年初至今值相减，第四季为全年 − 前九个月）"),
        },
        {
            "ref": "EX_INCENTIVE_CASH",
            "kind": "grouped_bars",
            "title": (
                f"预付费用现金流出减客户激励摊销：本季 ${incentive_cash_drain[latest]:,.0f}M，"
                + (f"{ytd_words} ${sum(incentive_cash_drain[-n_ytd:]):,.0f}M，" if n_ytd > 1 else "")
                + "是上年同期的 "
                + f"{sum(incentive_cash_drain[-n_ytd:]) / sum(incentive_cash_drain[-n_ytd - 4:-4]):.1f} 倍"
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
                + (f"摊销本身也在加速——{ytd_words} ${amort_now:,}M，"
                   f"同比 {amort_growth:+.1f}%，"
                   "说明前几年签下的单子正在加速进成本。"
                   if amort_faster else
                   f"摊销{ytd_words} ${amort_now:,}M，同比 {amort_growth:+.1f}%。")
                + "<b>口径提醒：</b>「预付费用」这一行不只含客户激励，公司没有逐项拆分；"
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
                ("两根柱子交叉的那一刻，回购就不再是「把多余的现金还回去」了。"
                 if trailing_coverage[latest] > 100 else "")
                + (f"差额由资产负债表补：总债务从上季末的 ${total_debt[latest - 1]:,}M 增到 "
                   f"${total_debt[latest]:,}M，同期总权益从 ${bs['total_equity'][latest - 1]:,}M 降到 "
                   f"${bs['total_equity'][latest]:,}M。"
                   if trailing_coverage[latest] > 100 and total_debt[latest] > total_debt[latest - 1]
                   and bs["total_equity"][latest] < bs["total_equity"][latest - 1] else
                   f"总债务上季末 ${total_debt[latest - 1]:,}M、本季末 ${total_debt[latest]:,}M，"
                   f"总权益 ${bs['total_equity'][latest - 1]:,}M → ${bs['total_equity'][latest]:,}M。")
                + "自由现金流按经营现金流减去购置不动产设备与资本化软件计算，与公司现金流量表的三行一致。"
            ),
            "src_extra": source_note("经营现金流、资本开支、回购与分红均来自现金流量表"),
        },
    ]

    # ── 三、下季跟踪 ─────────────────────────────────────────────────────────
    next_charts = []
    if next_entries:
        breached = [entry for entry in next_entries
                    if headroom(entry["direction"], entry["threshold"], entry["current"]) < 0]
        gated = next_kpi.get("disclosure_gated", [])
        by_reads = {entry.get("reads"): entry for entry in next_entries}
        ratio_entry = by_reads.get("rebate_ratio")
        conversion_entry = by_reads.get("ytd_conversion")
        price_entry = by_reads.get("repurchase_price")
        where = {"ytd_conversion": "现金转化", "repurchase_price": "管理层自己的买入价",
                 "rebate_ratio": "返点占比", "quarterly_usd_m.stock_repurchases": "回购金额"}
        named = [where.get(entry.get("reads"), entry["metric"])
                 for entry in sorted(breached, key=lambda e: list(where).index(e["reads"])
                                     if e.get("reads") in where else len(where))]
        next_charts.append(headroom_exhibit(
            f"下季 {len(next_entries)} 条量化阈值："
            + ("没有一条被击穿" if not breached else
               f"被击穿的{cn_count(len(breached))}条一条在{named[0]}、一条在{named[1]}" if len(breached) == 2 else
               f"被击穿的{cn_count(len(breached))}条在" + joined(named)),
            next_entries,
            "current",
            (
                "正值 = 仍在安全侧。"
                + (f"返点占比离 {ratio_entry['threshold']:g}% 的红线"
                   + ("还有余量" if headroom(ratio_entry["direction"], ratio_entry["threshold"], ratio_entry["current"]) >= 0
                      else "已经越过")
                   + (f"，{story['ratio_next']}" if story.get("ratio_next") else "") + "；"
                   if ratio_entry else "")
                + (f"现金转化的年初至今读数 {ytd_conversion[latest]:.1f}% 已经在 "
                   f"{conversion_entry['threshold']:g}% 之下；"
                   if conversion_entry and conversion_entry in breached else "")
                + (f"回购隐含均价 ${repurchase_price[latest]:.0f} 低于 ${price_entry['threshold']:.0f}，"
                   "这一条的方向要反过来读——<b>价格越高越说明管理层认可自己的估值</b>，"
                   "所以「越过阈值」在这里表示公司自己在更低的价位才愿意买。"
                   if price_entry and price_entry in breached else "")
            ),
            src_extra=(
                "阈值为本地研究设定，不是公司指引；当前值为本季披露值或其自算比率。"
                + (f"另有 {len(gated)} 条需等披露才能判定：" + "；".join(fill_story(item, figures) for item in gated)
                   + "。" if gated else "")
            ),
        ))
        next_charts += tracking_charts(
            next_entries,
            "current",
            "下季阈值",
            lambda entry: (
                f"{entry['metric']}：下季阈值 {unit_text(entry['unit'], entry['threshold'])}，"
                f"当前 {unit_text(entry['unit'], entry['current'])}"
            ),
        )

    # ── 四、长期常规 ─────────────────────────────────────────────────────────
    q4_network_falls = [dis_periods[index] for index in range(1, len(dis_periods))
                        if dis_periods[index].startswith("Q4") and network_net[index] < network_net[index - 1]]
    q4_all = [label for label in dis_periods[1:] if label.startswith("Q4")]
    margin_record = adjusted_margin[latest] == max(adjusted_margin)
    leverage_record = round(leverage[latest], 1) > round(max(leverage[:-1]), 1)
    gaap_move = gaap_margin[latest] - gaap_margin[latest - 1]
    adjusted_move = adjusted_margin[latest] - adjusted_margin[latest - 1]
    cross_diffs = [abs(adjusted_margin[periods.index(label)] - published)
                   for label, published in zip(crosscheck["periods"], crosscheck["company_published_pct"])]
    cross_first = min(crosscheck["periods"], key=periods.index)
    restructured = [periods[index] for index, value in enumerate(q["restructuring_charge"]) if value]
    fall_start = latest - price_fall
    routine = [
        {
            "kind": "lines",
            "title": (
                f"两条腿的 {len(dis_periods)} 季：支付网络净收入 ${network_net[dis_latest]:,}M、"
                f"增值服务 ${vas[dis_latest]:,}M"
                + (f"，两者的同比增速差已连续 {gap_run} 季在 8pp 以上" if gap_run >= 2 else "")
            ),
            "xlabels": labels,
            "xrot": 90,
            "xstep": 4,
            "series": [
                {"name": f"净收入（合计，回到 {periods[0][-4:]}{periods[0][:2]}）",
                 "values": rounded(net_revenue), "color": "GRAY"},
                {"name": "支付网络净收入",
                 "values": [None] * dis_from + rounded(network_net), "color": "NAVY"},
                {"name": "增值服务与解决方案净收入",
                 "values": [None] * dis_from + rounded(vas), "color": "GOLD"},
            ],
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "zero_base": True,
            "end_label": True,
            "ylab": "$M",
            "note": (
                f"支付网络本季同比 {network_yoy[dis_latest]:+.1f}%，增值服务 "
                f"{pct_change(vas[dis_latest], vas[dis_latest - 4]):+.1f}%。"
                f"<b>灰线是两条腿的合计，它回到 {periods[0][-4:]}{periods[0][:2]}；两条腿本身回不到。</b>"
                "净收入是损益表第一行，一直在印；把它劈成这两半是 "
                f"{periods[dis_from][-4:]}{periods[dis_from][:2]} 起才有的披露，"
                f"所以这张图上灰线比两条彩色线长 {dis_from} 格。"
                + ("支付网络那条每年第四季都会回落一格——第四季返点最重，"
                   "这是这家公司的季节性，不是异常。"
                   if q4_all and q4_network_falls == q4_all and q4_peaks else "")
                + "两条线从 2022 年第一季起可比：新口径在 2023 年第一季启用，"
                "当期 10-Q 同时重述了 2022 年的四个季度；再往前没有任何文件给出新口径的季度值，本页不外推。"
            ),
            "src_extra": source_filings,
        },
        {
            "kind": "lines",
            "title": (
                f"经营利润率：GAAP {gaap_margin[latest]:.1f}%，"
                f"剔除诉讼计提与重组后 {adjusted_margin[latest]:.1f}% —— "
                f"环比 GAAP 跳了 {signed(gaap_move, 1, 'pp')}，"
                f"同口径只有 {signed(adjusted_move, 2, 'pp')}"
                if abs(gaap_move) > abs(adjusted_move) else
                f"经营利润率：GAAP {gaap_margin[latest]:.1f}%，"
                f"剔除诉讼计提与重组后 {adjusted_margin[latest]:.1f}% —— "
                f"环比 GAAP {signed(gaap_move, 1, 'pp')}，同口径 {signed(adjusted_move, 2, 'pp')}"
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
                special_items_sentence(q, latest)
                + (f"所以直接比较两季的 GAAP 利润率会把改善放大约 {gaap_move / adjusted_move:.1f} 倍。"
                   if adjusted_move > 0 and gaap_move > adjusted_move else
                   "所以两季的 GAAP 利润率不能直接比。"
                   if special_items_words(q, latest) or special_items_words(q, latest - 1) else "")
                + "深蓝那条不是本站自定义的口径：公司在业绩发布里公布的调整后经营利润率，"
                "正好等于把这两项加回经营利润再除以净收入，"
                f"{len(crosscheck['periods'])} 个可对照的季度（{cross_first} 起）逐季吻合——"
                + ("公司只公布到 0.1pp，差异全部在 0.05pp 以内。" if max(cross_diffs) <= 0.05 else
                   f"公司只公布到 0.1pp，最大差异 {max(cross_diffs):.2f}pp。")
                + (f"本季 {adjusted_margin[latest]:.2f}% 是这 {len(periods)} 季里的最高值。" if margin_record else "")
            ),
            "src_extra": (
                "经营利润与诉讼计提为利润表原行，重组费用取自"
                + "、".join(f" {label} 10-Q" for label in restructured) + " 的说明；"
                "公司公布的调整后利润率见核对表，用于验证本页的加回口径。"
                if restructured else
                "经营利润与诉讼计提为利润表原行；"
                "公司公布的调整后利润率见核对表，用于验证本页的加回口径。"
            ),
        },
        {
            "kind": "lines",
            "title": (
                f"资本结构：总债务 ${total_debt[latest]:,}M，总权益 ${bs['total_equity'][latest]:,}M，"
                f"倍数 {leverage[latest]:.1f}x"
                + (f" 是 {len(periods)} 季里的最高值（此前最高 {max(leverage[:-1]):.1f}x）" if leverage_record else
                   f"，与此前最高持平" if round(leverage[latest], 1) == round(max(leverage[:-1]), 1) else
                   f"（{len(periods)} 季里最高 {max(leverage):.1f}x）")
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
                f"本季净{'增' if total_debt[latest] >= total_debt[latest - 1] else '减'}债务约 "
                f"${abs(total_debt[latest] - total_debt[latest - 1]):,}M，"
                f"权益{'减少' if bs['total_equity'][latest] <= bs['total_equity'][latest - 1] else '增加'} "
                f"${abs(bs['total_equity'][latest - 1] - bs['total_equity'][latest]):,}M"
                + (" —— 权益被压低的直接原因是库存股按成本累加，与经营无关；"
                   "但两件事同时发生说明这一轮回购的资金来源已经换了。"
                   if total_debt[latest] > total_debt[latest - 1]
                   and bs["total_equity"][latest] < bs["total_equity"][latest - 1] else "。")
                + story.get("other_expense_call", "")
            ),
            "src_extra": source_note("三条线均为各期资产负债表原行；总债务为两行相加"),
        },
        {
            "kind": "gs_bar",
            "title": (
                f"回购均价 ${repurchase_price[latest]:.2f}："
                + ("本季买得最多，" if record_buyback else "")
                + (f"价格却低于此前连续 {price_run} 个季度的每一季" if price_run >= 2 else
                   f"上季是 ${repurchase_price[latest - 1]:.2f}")
            ),
            "xlabels": labels,
            "xrot": 90,
            "values": q["stock_repurchases"],
            "legend": "单季回购金额",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "$M",
            "ylab2": "回购均价",
            "yoy": {
                "name": "回购均价，公司印 (RHS)",
                "values": rounded(repurchase_price),
                "color": "RED",
                "yfmt": "usd0",
            },
            "note": (
                "均价是公司自己印的「Average Price Paid per Share」：10-Q 第二部分第 2 项（第四季在 10-K 第 5 项）"
                "那张回购表的 Total 行，按现金口径，股数印到个位；股数乘均价与现金流量表的回购额逐季相差不到 $1M。"
                + (f"从 {labels[fall_start]} 的 ${repurchase_price[fall_start]:.2f} 一路降到本季的 "
                   f"${repurchase_price[latest]:.2f}，同期金额从 ${q['stock_repurchases'][fall_start]:,}M "
                   f"{'升到' if q['stock_repurchases'][latest] > q['stock_repurchases'][fall_start] else '降到'} "
                   f"${q['stock_repurchases'][latest]:,}M。" if price_fall >= 2 else "")
                + "剩余授权从上季末的 "
                f"${bs['remaining_repurchase_authorization'][latest - 1]:,}M "
                f"{'降到' if bs['remaining_repurchase_authorization'][latest] < bs['remaining_repurchase_authorization'][latest - 1] else '升到'} "
                f"${bs['remaining_repurchase_authorization'][latest]:,}M，"
                + ("本季董事会未新增授权。" if new_authority < 100 else
                   f"本季董事会新增了约 ${new_authority:,.0f}M 授权。")
            ),
            "src_extra": (
                "回购现金来自现金流量表；均价与股数来自各期 10-Q 第二部分第 2 项与 10-K 第 5 项的"
                "「Issuer Purchases of Equity Securities」表 Total 行；剩余授权来自各期资产负债表日的披露。"
            ),
        },
        {
            "kind": "lines",
            "title": (
                f"摊薄股数 {len(periods)} 季从 {ps['diluted_shares_m'][0]:,.0f} 百万"
                f"{'降到' if ps['diluted_shares_m'][latest] < ps['diluted_shares_m'][0] else '升到'} "
                f"{ps['diluted_shares_m'][latest]:,.0f} 百万，累计"
                f"{'缩' if ps['diluted_shares_m'][latest] < ps['diluted_shares_m'][0] else '增'}了 "
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
                f"{dis_labels[0]} 只有 "
                f"${pn['cross_border_assessments'][dis_from]:,}M"
            ),
            "xlabels": dis_labels,
            "xrot": 90,
            "series": [
                {"name": "交易处理计费",
                 "values": pn["transaction_processing_assessments"][dis_from:], "color": "NAVY"},
                {"name": "跨境计费",
                 "values": pn["cross_border_assessments"][dis_from:], "color": "MBLUE"},
                {"name": "境内计费",
                 "values": pn["domestic_assessments"][dis_from:], "color": "GOLD"},
                {"name": "其他网络计费",
                 "values": pn["other_network_assessments"][dis_from:], "color": "GRAY"},
            ],
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "zero_base": True,
            "end_label": True,
            "ylab": "$M",
            "note": (
                (("跨境这条本季超过境内，成为第二大计费线："
                  if cross_above == 1 else
                  f"跨境这条自 {dis_labels[-cross_above]} 起连续 {cross_above} 季高于境内，是第二大计费线：")
                 + f"${pn['cross_border_assessments'][latest]:,}M vs "
                 f"${pn['domestic_assessments'][latest]:,}M。"
                 if cross_above and largest_line == "transaction_processing_assessments" else "")
                + "四条线合计就是上面那些图的分母，它们全部印在 10-Q 里；"
                "唯一不印在表里的是把它们变成净收入的那一步（返点只在管理层讨论与分析的正文里写一句金额）。"
                f"<b>这四条线只能回到 {periods[dis_from][-4:]}{periods[dis_from][:2]}，"
                f"本页其余多数图回到 {periods[0][-4:]}{periods[0][:2]}。</b>"
                "这不是没取：2016–2017 年的申报里根本没有收入附注"
                "（ASC 606 于 2018-01-01 采用、之前不重述），"
                "2018Q1–2023Q3 每一份 10-Q 与 FY2018–FY2025 每一份 10-K 的收入附注里"
                "也从来没有这四条线，2016–2022 年没有一份新闻稿拆过收入。"
            ),
            "src_extra": source_filings,
        },
    ]
    routine.append(regional_gdv_exhibit(staging))

    exhibits = number_exhibits(settled_charts + highlights + next_charts + routine)
    first_table = len(exhibits) + 2
    settled_headroom = next((ex for ex in exhibits if ex["kind"] == "diverging_bars"
                             and ex["title"].startswith("上季")), None)
    next_headroom = next((ex for ex in exhibits if ex["kind"] == "diverging_bars"
                          and ex["title"].startswith("下季")), None)

    revenue_rows = []
    for index, label in enumerate(dis_periods):
        revenue_rows.append([
            label,
            f"${pn['domestic_assessments'][dis_from + index]:,}M",
            f"${pn['cross_border_assessments'][dis_from + index]:,}M",
            f"${pn['transaction_processing_assessments'][dis_from + index]:,}M",
            f"${pn['other_network_assessments'][dis_from + index]:,}M",
            f"${gross[index]:,}M D",
            f"${rebates[index]:,}M D",
            f"{rebate_ratio[index]:.2f}% D",
            f"${network_net[index]:,}M",
            f"${vas[index]:,}M",
            f"${dis_net_revenue[index]:,}M",
        ])

    cash_rows = []
    for index, label in enumerate(periods):
        cash_rows.append([
            label,
            f"${q['operating_cash_flow'][index]:,}M",
            f"${q['net_income'][index]:,}M",
            f"{q['operating_cash_flow'][index] / q['net_income'][index] * 100:.0f}% D",
            f"${q['prepaid_expense_cash_outflow'][index]:,}M",
            f"${q['amortization_of_customer_incentives'][index]:,}M",
            f"${free_cash_flow[index]:,}M D",
            f"${q['stock_repurchases'][index]:,}M",
            f"{ps['shares_repurchased_m'][index]:.2f}M",
            ("—" if repurchase_price[index] is None
             else f"${repurchase_price[index]:,.2f}"),
            f"${q['dividends_paid'][index]:,}M",
            f"${total_debt[index]:,}M D",
        ])

    driver_rows = []
    for index, label in enumerate(periods):
        def spread_text(key: str) -> str:
            value = spreads[key][index]
            return "—" if value is None else f"{value:+.0f}pp D"
        driver_rows.append([
            label,
            f"{drivers['gdv'][index]}%",
            f"{drivers['cross_border'][index]}%",
            f"{drivers['switched'][index]}%",
            spread_text("境内计费 vs GDV"),
            spread_text("跨境计费 vs 跨境量"),
            spread_text("清算计费 vs 换手笔数"),
        ])

    margin_rows = []
    for index, label in enumerate(crosscheck["periods"]):
        position = periods.index(label)
        margin_rows.append([
            label,
            f"{gaap_margin[position]:.2f}%",
            f"${q['provision_for_litigation'][position]:,}M",
            f"${q['restructuring_charge'][position]:,}M",
            f"{adjusted_margin[position]:.2f}% D",
            f"{crosscheck['company_published_pct'][index]:.1f}%",
        ])

    # Section one says what it settles, in counts read off the blocks it settles.
    described = []
    if closure:
        described.append(f"上一份报告（{closure['set_in'][:10]}）文末的 {len(closure['items'])} 条待验证问题，"
                         "按本季报告第 0 节的判定与打分逐条归类")
    if prior_entries:
        rows_left = []
        if prior_pending:
            rows_left.append(f"{cn_count(len(prior_pending))}档要连续几季才能结算")
        if prior_kpi.get("unsettleable"):
            rows_left.append(f"{cn_count(len(prior_kpi['unsettleable']))}行没有数字可对照")
        if prior_kpi.get("retired"):
            rows_left.append(f"{cn_count(len(prior_kpi['retired']))}行已被本季报告降级")
        described.append(f"它第 8 节的 {len(prior_kpi['rows'])} 行关键观察指标拆成 {len(prior_entries)} 档可量化的阈值，"
                         "逐档对本季实际值"
                         + (f"，另有{'、'.join(rows_left)}，原因写在图注里" if rows_left else ""))
    call_words = ""
    if prior_call and snapshot:
        judged = [(item, call_verdict(item, call_reading(staging, item["reads"])[0]))
                  for item in prior_call["items"]]
        kinds = [("low", "给了区间的", "在区间内", "都在区间内", "落在区间外"),
                 ("direction", "给了方向的", "方向与指引一致", "都与实际一致", "与实际相反")]
        phrases = []
        for key, lead_words, ok_words, all_words, miss_words in kinds:
            group = [verdict for item, verdict in judged if key in (item.get("guided") or {})]
            if group:
                ok = sum(1 for verdict in group if verdict == ok_words)
                phrases.append(f"{lead_words}{cn_count(len(group))}项"
                               + ((all_words.removeprefix("都") if ok else miss_words) if len(group) == 1 else
                                  all_words if ok == len(group) else f"里{cn_count(ok)}项{ok_words}"))
        points = [item for item, _ in judged if "point" in (item.get("guided") or {})]
        if points:
            phrases.append(f"只给约数的{cn_count(len(points))}项不判定")
        words_only = [item for item, _ in judged if not item.get("guided")]
        if words_only:
            phrases.append(f"只给措辞的{cn_count(len(words_only))}项没有上下限可对照")
        call_words = (f"上季电话会对本季的 {len(judged)} 项指引与本季实际并排列在核对表："
                      + "，".join(phrases) + "。")
    settled_description = (
        ("先结算上一份报告留下、本季到期的东西：" + "；".join(described) + "。" if described else
         f"本站对 Mastercard 的第一份季报分析是 {FIRST_REPORT_PERIOD}，没有上季留下的跟踪指标可结算；"
         "本节结算的是公司上季给出、本季到期的指引。" if period == FIRST_REPORT_PERIOD else
         "本季没有录入上季留下的问题与阈值。")
        + "公司不在申报文件里给指引（业绩发布 8-K 没有 Outlook 段落），电话会给的是措辞加少数几个数，"
        "所以本节没有指引兑现图"
        + ("；" + call_words if call_words else "；本季也没有录入上季电话会的指引。")
        + ("" if settled_charts else "本节没有图。")
    )

    not_wired = ["跨境量里 travel 与电商的月度拆分", "增值服务的子线增速"]
    not_wired += story.get("not_wired", [])
    tables = []
    if prior_entries:
        rows = []
        for entry in prior_entries + prior_pending:
            pending_tier = entry in prior_pending
            rows.append([
                tier_label(entry) + (f"（需连续{cn_count(entry['quarters'])}季）" if pending_tier else ""),
                "高于阈值为有利" if entry["direction"] == "up" else "低于阈值为有利",
                unit_text(entry["unit"], entry["threshold"]),
                unit_text(entry["unit"], entry["actual"]),
                "—" if pending_tier else
                f"{headroom(entry['direction'], entry['threshold'], entry['actual']):+.1f}%",
                entry["words"],
            ])
        for item in prior_kpi.get("unsettleable", []) + prior_kpi.get("retired", []):
            rows.append([item["name"], "—", "—", "—", "—", item["words"]])
        tables.append({
            "n": first_table + len(tables),
            "title": "上季第 8 节的阈值逐档与本季实际（原单位；最后一列是上季报告原文）",
            "headers": ["指标（档）", "方向", "阈值", f"{period} 实际", "余量 D", "上季报告原文"],
            "rows": rows,
        })
    if prior_call and snapshot:
        rows = []
        for item in prior_call["items"]:
            value, text = call_reading(staging, item["reads"])
            rows.append([item["item"], item["wording"], text, call_verdict(item, value)])
        tables.append({
            "n": first_table + len(tables),
            "title": f"上季电话会对本季的指引与本季实际（{prior_call['set_in']}；指引是电话会原话，不是申报数）",
            "headers": ["项目", "上季电话会原话", "本季实际（业绩发布）", "对照"],
            "rows": rows,
        })
    if next_entries:
        tables.append(threshold_table(first_table + len(tables), "下季阈值与当前值（原单位）",
                                      next_entries, "current", "当前值"))
    tables += [
        {
            "n": first_table + len(tables),
            "title": f"{cn_count(len(dis_periods))}季毛计费、返点与净收入（返点与占比为自算）",
            "headers": ["期间", "境内计费", "跨境计费", "交易处理计费", "其他网络计费",
                        "毛计费合计 D", "返点与激励 D", "返点 / 毛计费 D",
                        "支付网络净收入", "增值服务净收入", "净收入合计"],
            "rows": revenue_rows,
        },
    ]
    tables += [
        {
            "n": first_table + len(tables),
            "title": f"{len(periods)} 季现金流、回购与资本结构",
            "headers": ["期间", "经营现金流", "净利润", "OCF / 净利润 D", "预付费用现金流出",
                        "客户激励摊销", "自由现金流 D", "回购金额", "回购股数",
                        "回购均价（公司印）", "分红", "总债务 D"],
            "rows": cash_rows,
        },
    ]
    tables += [
        {
            "n": first_table + len(tables),
            "title": "关键经营驱动增速与固定汇率价差（第四季无固定汇率季度数）",
            "headers": ["期间", "GDV（本地货币）", "跨境量（本地货币）", "换手笔数",
                        "境内价差 D", "跨境价差 D", "清算价差 D"],
            "rows": driver_rows,
        },
    ]
    tables += [
        {
            "n": first_table + len(tables),
            "title": "调整后经营利润率的口径核对：加回两项即得公司公布值",
            "headers": ["期间", "GAAP 经营利润率", "诉讼计提", "重组费用",
                        "加回后 D", "公司公布的调整后经营利润率"],
            "rows": margin_rows,
        },
    ]
    if call:
        tables.append({
            "n": first_table + len(tables),
            "title": f"公司口径的前瞻指引（{call['set_in']}；电话会原话，申报文件里没有这些数）",
            "headers": ["项目", "管理层措辞"],
            "rows": [[item["item"], item["wording"]] for item in call["items"]],
        })
    tables.append(ai_capex_cycle_table(first_table + len(tables)))

    brief = [
        '<article><span>结构</span><b>'
        + ("返点吃掉了多收的费" if rebate_step[dis_latest] * 3 >= gross_step[dis_latest] * 2 else
           f"返点拿走了多收的费的 {rebate_step[dis_latest] / gross_step[dis_latest] * 100:.0f}%")
        + '</b>'
        f'<p>毛计费同比增量 ${gross_step[dis_latest]:,.0f}M，返点腿 −${rebate_step[dis_latest]:,.0f}M，'
        f'净支付网络收入只多了 ${network_step[dis_latest]:,.0f}M。</p></article>',
        '<article><span>亮点</span><b>'
        + ("增值服务撑起过半增量" if vas_increment_share > 50 else "增值服务撑起近半增量"
           if vas_increment_share >= 40 else "增值服务贡献增量")
        + '</b>'
        f'<p>${vas[dis_latest]:,}M、占净收入 {vas_share[dis_latest]:.1f}%，'
        f'贡献了净收入同比增量的 {vas_increment_share:.0f}%，'
        '且不承担返点。</p></article>',
    ]
    if ytd_conversion[latest] < ytd_conversion[latest - 4] and leverage[latest] > leverage[latest - 1]:
        brief.append(
            '<article><span>存疑</span><b>现金转化与杠杆同向恶化</b>'
            f'<p>{ytd_words} OCF / 净利润 {ytd_conversion[latest]:.1f}%（上年 '
            f'{ytd_conversion[latest - 4]:.1f}%），滚动四季股东回报已占自由现金流 '
            f'{trailing_coverage[latest]:.0f}%。</p></article>')

    faster_gross = gross_yoy[dis_latest] > gross_yoy[dis_latest - 4]
    slower_network = network_yoy[dis_latest] <= network_yoy[dis_latest - 4]
    headline = (
        ("账单比一年前涨得快，留下的钱没有：" if faster_gross and slower_network else "")
        + f"毛计费 ${gross[dis_latest]:,}M、同比 "
        f"{signed(gross_yoy[dis_latest])}（一年前 {signed(gross_yoy[dis_latest - 4])}），"
        f"而净支付网络收入只有 {signed(network_yoy[dis_latest])}"
        f"（一年前 {signed(network_yoy[dis_latest - 4])}）——"
        f"返点占毛计费 {rebate_ratio[dis_latest]:.2f}%，"
        f"{ratio_up + ratio_down} 个可比季里 {ratio_up} 次同比走高。"
        f"毛计费的年增量从 {dis_labels[DIS_YOY_FROM]} 起"
        f"{'涨' if gross_step[dis_latest] > gross_step[DIS_YOY_FROM] else '降'}了 "
        f"{abs(pct_change(gross_step[dis_latest], gross_step[DIS_YOY_FROM])):.0f}%"
        + (f"，落到净收入上的部分连续{run_words}季卡在 ${min(plateau):,.0f}–${max(plateau):,.0f}M。"
           if run >= 4 else "。")
        + f"同期{ytd_words}经营现金流同比 {signed(ocf_ytd)}"
        f"、净利润 {income_ytd:+.1f}%"
        + (f"，缺口由年初以来净增的 ${total_debt[latest] - total_debt[year_start]:,}M 债务补进了"
           + ("创纪录的回购。" if record_buyback else "回购。")
           if ocf_ytd < income_ytd and total_debt[latest] > total_debt[year_start] else "。")
        + (f"财报当日股价 {signed(consensus['post_earnings_price_change_pct'])}。" if consensus else "")
    )

    return {
        "schema_version": "quarterly-dashboard/ma-v1",
        "page": {"slug": "ma", "language": "zh-CN"},
        "company": {
            "ticker": "MA",
            "name": "Mastercard",
            "group": "payment_networks",
            "accounting_standard": "US GAAP",
        },
        "latest": latest_meta,
        "tracker": "Watchlist Quarterly Tracker · MA",
        "title": f"Mastercard (MA)：{period} 季报仪表盘",
        "subtitle": (
            f"截至 {period_end} · 发布 {latest_meta['release_date']} · US GAAP · "
            f"{ {'unaudited': '未审计', 'audited': '已审计'}[latest_meta['audit_status']] } · "
            "金额单位为 $M，另有注明除外"
        ),
        "headline": headline,
        "brief": (
            f'<h4>本季{cn_count(len(brief))}条主线</h4><div class="takeaway-grid">'
            + "".join(brief)
            + '</div>'
        ),
        "source": source,
        "source_url": release["url"],
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {
                "id": "settled",
                "title": "一、上季跟踪指标兑现了吗",
                "description": settled_description,
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
                "description": (
                    "同一套口径向前看：当前值离下季阈值还有多远，统一用「距阈值余量」表示。"
                    if next_charts else "本季没有新立的下季阈值，本节没有图。"
                ),
                "exhibits": exhibits[
                    len(settled_charts) + len(highlights):
                    len(settled_charts) + len(highlights) + len(next_charts)
                ],
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": "MA 专属的常规序列：两条业务腿、利润率的同口径对照、资本结构、回购价格、四条计费线与分地区 GDV。",
                "exhibits": exhibits[-len(routine):],
            },
        ],
        "tables": tables,
        "notes": [plain_text(note) for note in [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，"
            "每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "Mastercard 的财年即自然年，本页的季度标注与公司口径一致，无需换算。",
            disclosure["statement"] + disclosure["why_no_record"],
            "返点与激励在现行口径下不是印在表里的一行，而是「四条计费线合计 − 支付网络净收入」这个减法，"
            "两个被减数都是申报数。"
            + rebate_check.replace("本页的减法", "这个减法") + "这是这条序列的外部校验。"
            if rebate_check else
            "返点与激励在现行口径下不是印在表里的一行，而是「四条计费线合计 − 支付网络净收入」这个减法，"
            "两个被减数都是申报数。",
            f"收入拆分的逐季记录从 {periods[dis_from][-4:]}{periods[dis_from][:2]} 起。"
            "「支付网络 / 增值服务」与四条计费线是公司 2023 年第一季度换用的新口径，"
            "当季 10-Q 同时重述了 2022 年的可比季度；更早的季度只有旧口径，"
            "旧口径的分母把增值服务也算在内，两条线不是一条线，本页不拼接。",
            "第四季没有 10-Q，每个第四季都是「全年 − 前九个月」，两端都是申报数；"
            "第四季的摊薄股数与摊薄每股收益取自当季 earnings release 的三个月列，"
            "因为按全年减九个月得到的每股收益不是第四季的每股收益。",
            "公司只在当季 10-Q 里给出该季各条计费线的固定汇率增速，第四季只有全年数，"
            f"因此固定汇率价差图在 {cn_first[-4:]} 年起的 {len(cn_q4_gaps)} 个第四季是缺口，本页留空而不是插值；"
            f"{cn_first[-4:]} 年之前没有新口径的固定汇率数，图上那一段是空的。",
            "回购均价与回购股数取公司在 10-Q 第二部分第 2 项、10-K 第 5 项「Issuer Purchases of Equity Securities」表"
            "Total 行印的数（按现金口径，股数印到个位），不是自算：股数乘均价与现金流量表的回购额逐季相差不到 $1M。",
            "「剔除诉讼计提与重组」的经营利润率是把两条申报行加回经营利润，"
            "不是本站自定义的非 GAAP 指标：它逐季吻合公司自己公布的调整后经营利润率，"
            f"核对表列出{cn_count(len(crosscheck['periods']))}个对照季。",
            ((f"Exhibit {settled_headroom['n']} 与 Exhibit {next_headroom['n']} 的阈值是本地研究设定，"
              if settled_headroom and next_headroom else
              f"Exhibit {(settled_headroom or next_headroom)['n']} 的阈值是本地研究设定，")
             + "不是公司指引，也不构成评级或投资建议；「距阈值余量」统一为正值代表在该线的有利一侧"
             "（减仓、警示类的线是还没越过，加仓类的线是已经达到）。"
             if settled_headroom or next_headroom else ""),
            "市场预期一律标注为「市场预期」并给出取数时点，不写卖方机构名，也不发布评级、目标价或估值。"
            + (f"本季净收入 ${net_revenue[latest]:,}M、公司口径调整后每股收益 "
               f"${snapshot['adjusted_diluted_eps_usd'][0]:.2f}，"
               + ("均高于" if net_revenue[latest] / 1000 > consensus["net_revenue_usd_bn"]
                  and snapshot["adjusted_diluted_eps_usd"][0] > consensus["adjusted_diluted_eps_usd"]
                  else "对照")
               + f" {consensus['as_of']} 的市场预期"
               f"（净收入 US${consensus['net_revenue_usd_bn']:.2f}B、调整后每股收益 "
               f"${consensus['adjusted_diluted_eps_usd']:.2f}）。" if consensus and snapshot else ""),
            fill_story(story.get("drivers_note", ""), figures),
            "本页已知未接入：" + "、".join(not_wired[:-1]) + "、以及" + not_wired[-1] + "。",
        ] if note],
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
