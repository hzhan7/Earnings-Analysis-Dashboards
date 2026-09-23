#!/usr/bin/env python3
"""Build the MCO quarterly-results page.

Same four-part, chart-led shape as the other company pages, and each part is
what its title says:

* 一、上季跟踪指标兑现了吗 -- (a) the follow-up questions last quarter's
  analysis left, as this quarter's analysis settled them (``followup_closure``);
  (b) last quarter's quantified thresholds, settled against this quarter's
  filings (``prior_kpi_settlement``); (c) the company's own full-year guidance
  record and the open year's EPS bridge.
* 二、本季重点 -- one chart per finding of this quarter's analysis that the
  filings can draw; its readings sit in the stamped ``quarter_story``.
* 三、下季要跟踪什么 -- this quarter's analysis §8 thresholds (``next_kpi``),
  with every current value computed from the series.
* 四、长期常规跟踪 -- the ten-year and 42-quarter routine series.

Moody's runs a calendar fiscal year, so no quarter label needs translating.

What makes the guidance record different from the six other pages that carry
one is the *shape* of the guidance.  AMZN, CDNS, SNPS, NVDA, TSM and META all
publish a range for the **next quarter** in their releases, so their records are
quarter-in, quarter-out.  Moody's earnings 8-K carries only a **full-year outlook
table** in its EX-99.1, re-issued three times as the year runs: February sets it,
April, July and October update it (a line it did not move is printed ``NC``).
A next-quarter figure has surfaced only on a few calls (Q1 2025 and Q2 2026
adjusted EPS), never in the 8-K, and the page does not score it.  So the object
the record settles is a *year*, not a quarter, and the interesting variable is
not only whether the company cleared its range but **how far ahead it was
standing when it drew the range**.

Two things make the table worth reading rather than merely quoting.

First, the company prints its own previous guidance beside the current one in
every release, with an explicit ``NC`` marker for the lines it did not move.  So
the revision path is disclosed by the filer rather than reconstructed here, and
each release independently confirms the one before it.

Second, the table reconciles against itself three separate ways in every
release: GAAP diluted EPS plus the named add-backs equals adjusted diluted EPS,
operating margin plus the named add-backs equals adjusted operating margin, and
operating cash flow minus capital expenditure equals free cash flow.  That is
what licenses this page to treat the guidance table as arithmetic the company
stands behind rather than as a set of loose targets -- and the page checks the
three sums on every build rather than asserting them.

The record's answer is two-sided, and the two sides sit at different forecast
horizons rather than on different metrics: against the final (October) range
the delivered adjusted EPS lands close, against the initial (February) range it
can miss by a third.  Every tally, extreme and year named in those sentences is
recounted from the series on each build.  They used to be typed, and the typed
ones went stale the moment FY2018 was added to the record and the annual window
was pulled back to FY2016.

FY2018 was once excluded on the stated grounds that it "has only an October
vintage".  That was false: the February 2018 release opens the year at adjusted
EPS $7.65-$7.85, April and July reaffirm it line for line, and October cuts it
to $7.50-$7.65 -- the same four-vintage cadence as every other year here.  The
delivered figure was $7.39, below the final range: the excluded year was the
only year that broke the page's headline.

The page is rolled by editing ``series/mco.json`` alone.  What only one quarter
has -- the open year's guidance table and its three bridges, the quarter's own
figures, the two analyses' closure and thresholds, and the quarter's story --
sits in blocks stamped with the quarter (``board.stamped_block``); the cash legs
and the MA KPIs are quarterly arrays aligned to ``segment_quarterly``.
``_checks`` is a separate reading of the quarter's release and of the two
analyses (``_checks["note"]``) that the tests hold the page to and this builder
never reads.

Published numbers are company-reported or transparent arithmetic.  The page
publishes no rating, target price or valuation.
"""

from __future__ import annotations

import json
import math
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import (  # noqa: E402
    ai_capex_cycle_table,
    cn_count,
    cn_fraction,
    delivery_band,
    fill_story,
    headroom,
    headroom_exhibit,
    latest_block,
    midpoint_deviation,
    number_exhibits,
    stamped_block,
    threshold_exhibit,
    unit_text,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "mco.json"
DATA_DIR = ROOT / "data"

LONG_STEP = 4

VINTAGES = ("Feb", "Apr", "Jul", "Oct")

# The guided lines the width chart draws: the numeric ranges that share a basis
# with the settled record (EPS, margins, cash). The table carries other numeric
# lines too -- interest, non-operating items, tax rate, segment margins -- which
# is why the chart names what it draws instead of calling it "the" numbers.
WIDTH_ITEMS = [
    ("调整后摊薄 EPS", "adj_diluted_eps_usd", "US$/股"),
    ("GAAP 摊薄 EPS", "gaap_diluted_eps_usd", "US$/股"),
    ("调整后营业利润率", "adj_operating_margin_pct", "%"),
    ("营业利润率", "operating_margin_pct", "%"),
    ("经营现金流", "operating_cash_flow_usd_b", "US$B"),
    ("自由现金流", "free_cash_flow_usd_b", "US$B"),
]
VINTAGE_MONTH = {"Feb": "2 月", "Apr": "4 月", "Jul": "7 月", "Oct": "10 月"}

# History that does not move with a roll, keyed by the year it belongs to: why
# the year that cut its guidance hardest cut it, why the lowest operating margin
# is where it is, why the lowest free cash flow is where it is.
CUT_STORY = {2022: "当年发行量随利率崩掉"}
MARGIN_STORY = {2016: "当年计提了与 DOJ 和解相关的一次性费用", 2022: "正是发行量崩掉那年"}
CASH_STORY = {2017: "那笔 DOJ 和解款实际付出去的一年", 2022: "发行量崩掉那年"}


def plain_text(html: str) -> str:
    """Strip tags for the slots `assets/page.js` renders through `esc()`.

    Section descriptions and the 口径与方法说明 list are escaped by the shared
    renderer, so a `<b>` written into either reaches the reader as four literal
    characters. Exhibit notes are not escaped and keep their markup. Writing the
    copy once and stripping here keeps the two slots from drifting apart.
    """
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html)).strip()


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def mid(low: float, high: float) -> float:
    return (low + high) / 2


def money(value: float) -> str:
    """``0.9`` → ``'0.90'``; the sign is written by the caller."""
    return f"{abs(value):.2f}"


def pct_words(value: float) -> str:
    """``44.0`` → ``'44%'``, ``1.5`` → ``'1.5%'`` -- a guided percentage as printed."""
    return f"{value:g}%"


def resolve_exhibit_refs(exhibits: list[dict]) -> list[dict]:
    numbers = {ex["ref"]: ex["n"] for ex in exhibits if ex.get("ref")}
    for ex in exhibits:
        ex.pop("ref", None)
        for field in ("title", "note", "src_extra", "annot"):
            text = ex.get(field)
            if not isinstance(text, str):
                continue
            for key, number in numbers.items():
                text = text.replace("{" + key + "}", str(number))
            ex[field] = text
    return exhibits


def release_source(staging: dict) -> dict:
    """This quarter's own release in `sources`, found by its label."""
    label = f"Moody’s {staging['segment_quarterly']['periods'][-1]} 业绩新闻稿"
    found = next((item for item in staging["sources"] if item["label"].startswith(label)), None)
    if found is None:
        raise ValueError(f"series `sources` has no entry for the {label}: add this "
                         "quarter's release with the roll")
    return found


def periodic_report_words(staging: dict) -> str:
    """「与截至 … 的 10-Q」 when `sources` carries the quarter's own 10-Q / 10-K."""
    seg = staging["segment_quarterly"]
    end, period = seg["period_ends"][-1], seg["periods"][-1]
    for form, label in (("10-Q", f"Moody’s 截至 {end} 的 10-Q"),
                        ("10-K", f"Moody’s FY{period[-4:]} 年报 10-K")):
        if any(item["label"].startswith(label) for item in staging["sources"]):
            return f"与截至 {end} 的 {form}"
    return ""


SOURCE_8K = (
    "全年指引来自各期业绩 8-K 的 EX-99.1 里「Full Year 20XX Moody's Corporation "
    "Guidance」表，以及同一份文件末尾把 GAAP 口径调节到调整后口径的对照表；"
    "全年实际值来自次年 2 月那期新闻稿的全年结果。"
)

# The February release sets the year and the next three revise it, so a
# "guidance" on this page is always tagged with the release that drew it.
TIMING_ANNUAL = "该<b>年度进行途中</b>"


def record_facts(staging: dict) -> dict:
    """Everything the guidance record says, counted once for every sentence that uses it."""
    g = staging["annual_guidance_history"]
    years = g["fiscal_years"]
    actual = g["actual_adj_eps_usd"]
    feb_lo, feb_hi = g["adj_eps_lo"]["Feb"], g["adj_eps_hi"]["Feb"]
    oct_lo, oct_hi = g["adj_eps_lo"]["Oct"], g["adj_eps_hi"]["Oct"]
    finished = [i for i, v in enumerate(actual) if v is not None]
    # The open year's latest vintage stands in for its missing October range.
    latest_vintage = {}
    for i in range(len(years)):
        latest_vintage[i] = next(v for v in reversed(VINTAGES) if g["adj_eps_lo"][v][i] is not None)
    final_lo = [g["adj_eps_lo"][latest_vintage[i]][i] for i in range(len(years))]
    final_hi = [g["adj_eps_hi"][latest_vintage[i]][i] for i in range(len(years))]
    feb_dev = {years[i]: pct_change(actual[i], mid(feb_lo[i], feb_hi[i])) for i in finished}
    oct_dev = {years[i]: pct_change(actual[i], mid(oct_lo[i], oct_hi[i])) for i in finished}
    path = {years[i]: pct_change(mid(oct_lo[i], oct_hi[i]), mid(feb_lo[i], feb_hi[i]))
            for i in range(len(years)) if oct_lo[i] is not None and feb_lo[i] is not None}
    return {
        "years": years, "finished": finished, "actual": actual,
        "feb_lo": feb_lo, "feb_hi": feb_hi, "final_lo": final_lo, "final_hi": final_hi,
        "latest_vintage": latest_vintage,
        "final_above": [years[i] for i in finished if actual[i] > oct_hi[i]],
        "final_inside": [years[i] for i in finished if oct_lo[i] <= actual[i] <= oct_hi[i]],
        "final_below": [years[i] for i in finished if actual[i] < oct_lo[i]],
        "initial_above": [years[i] for i in finished if actual[i] > feb_hi[i]],
        "initial_inside": [years[i] for i in finished if feb_lo[i] <= actual[i] <= feb_hi[i]],
        "initial_below": [years[i] for i in finished if actual[i] < feb_lo[i]],
        "feb_dev": feb_dev, "oct_dev": oct_dev, "path": path,
        "open": [years[i] for i in range(len(years)) if actual[i] is None],
    }


def aligned(staging: dict, key: str) -> dict:
    """A quarterly block that must run on `segment_quarterly`'s periods, cell for cell.

    The cash legs and the MA KPIs live in their own blocks because they come
    from different documents (XBRL cash-flow facts, the release's KPI tables);
    a roll that extends one and forgets the other would otherwise pair a
    quarter's buyback with the previous quarter's label.
    """
    block = staging[key]
    periods = staging["segment_quarterly"]["periods"]
    if block["periods"] != periods:
        raise ValueError(f"series block `{key}` runs {block['periods'][0]}–{block['periods'][-1]}, "
                         f"but segment_quarterly runs {periods[0]}–{periods[-1]}: extend it with the roll")
    return block


def following(period: str) -> str:
    """``'Q2 2026'`` → ``'Q3 2026'``, ``'Q4 2026'`` → ``'Q1 2027'``."""
    quarter, year = int(period[1]), int(period[-4:])
    return f"Q1 {year + 1}" if quarter == 4 else f"Q{quarter + 1} {year}"


def first_reported(values: list) -> int:
    """Index of the first quarter a KPI was printed; the chart starts there."""
    return next(i for i, value in enumerate(values) if value is not None)


def usd_m(value: float) -> str:
    return f"{'−' if value < 0 else ''}US${abs(value):,.0f}M"


def pct_text(value: float) -> str:
    """``8.5`` → ``'8.5%'``, ``9.0`` → ``'9%'`` -- a threshold as the report wrote it."""
    return f"{value:g}%"


def tracking_chart(title: str, labels: list[str], series: list[dict],
                   thresholds: list[tuple[str, float]], *, fmt: str, ylab: str, note: str,
                   src_extra: str) -> dict:
    """Actual lines against one or more flat threshold lines.

    `board.threshold_exhibit` draws one line against one threshold. Several of
    the report's rows are two-sided (a floor that says 减仓 and a bar that says
    加仓 on the same metric), and one of its metrics changed disclosure basis
    mid-window, so the series list and the threshold list are both open here.
    The first threshold keeps the site's threshold colour.
    """
    lines = [dict(line) for line in series]
    for (name, value), color in zip(thresholds, ("RED", "GOLD", "GRAY")):
        lines.append({"name": name, "values": [value] * len(labels), "color": color})
    chart = {
        "kind": "lines",
        "title": title,
        "xlabels": labels,
        "series": lines,
        "fmt": fmt,
        "yfmt": fmt,
        "label_fmt": fmt,
        "end_label": True,
        "ylab": ylab,
        "note": note,
        "src_extra": src_extra,
    }
    if len(labels) > 16:
        chart["xstep"] = LONG_STEP
    return chart


def trimmed(labels: list[str], *columns: list) -> tuple[list[str], list[list]]:
    """Cut the leading quarters in which none of the columns was printed yet."""
    start = min(first_reported(column) for column in columns)
    return labels[start:], [column[start:] for column in columns]


# ── section one (a)(b): what last quarter's analysis left to be settled ─────
CLOSURE_LABELS = ("已验证", "部分验证", "被证伪", "仍未披露", "指标设计失效")


def closure_counts(closure: dict) -> tuple[list[str], list[int]]:
    """Verdict tallies, counted from the items in a fixed order.

    The counts are not stored: a block that carried both the twelve verdicts and
    a tally could disagree with itself. A verdict outside the order stops the
    build instead of silently dropping out of the chart.
    """
    verdicts = [item["verdict"] for item in closure["items"]]
    unknown = sorted(set(verdicts) - set(CLOSURE_LABELS))
    if unknown:
        raise ValueError(f"series block `followup_closure` has verdicts this page does not chart: {unknown}")
    labels = [label for label in CLOSURE_LABELS if label in verdicts]
    return labels, [verdicts.count(label) for label in labels]


def closure_chart(closure: dict, values: dict) -> dict:
    labels, counts = closure_counts(closure)
    return {
        "kind": "bars_labeled",
        "title": (f"上季 {len(closure['items'])} 条待验证问题："
                  + "、".join(f"{count} 条{label}" for label, count in zip(labels, counts))),
        "xlabels": labels,
        "values": counts,
        "legend": "问题条数",
        "fmt": "f0",
        "yfmt": "f0",
        "label_fmt": "f0",
        "ylab": "条",
        "note": "".join(fill_story(closure[key], values)
                        for key in ("falsified_note", "undisclosed_note", "design_note", "earlier_note")
                        if closure.get(key)),
        "src_extra": (f"问题清单是上季（{closure['set_in']}）本站季报分析留下的 follow-up，逐条判定取自本季"
                      "分析第 0 节；其中能核的证据（ARR、有机增速、出售收益、回购、准备金）已回本季业绩 8-K "
                      "EX-99.1 逐项核对，判定与申报一致。逐条清单见核对表。"),
    }


def prior_entries(staging: dict, prior: dict) -> list[dict]:
    """Last quarter's thresholds with this quarter's actual, read from the series.

    The block carries only what the report wrote -- metric, direction, threshold
    -- so a typed actual would be a second copy of a number the arrays already
    hold, free to disagree with them. One threshold is not a number in the
    report at all but a rule (「Q2 同比为负」), and it resolves to the
    same quarter a year earlier.
    """
    seg = staging["segment_quarterly"]
    cash = aligned(staging, "quarterly_cash")
    kpi = aligned(staging, "ma_kpi_quarterly")
    actual = {
        "ma_arr_growth": lambda: kpi["arr_growth_pct"][-1],
        "ma_organic_growth": lambda: kpi["organic_cc_revenue_growth_pct"][-1],
        "mis_revenue": lambda: seg["mis_revenue_usd_m"][-1],
        "share_repurchases": lambda: cash["share_repurchases_usd_m"][-1],
    }
    rule = {"same_quarter_last_year": lambda: seg["mis_revenue_usd_m"][-5]}
    entries = []
    for entry in prior["quantified"]:
        settled = dict(entry)
        if "threshold_rule" in entry:
            settled["threshold"] = rule[entry["threshold_rule"]]()
        if entry.get("series") in actual:
            if "actual" in entry:
                raise ValueError(f"threshold `{entry['id']}` is computed from the series; remove its typed actual")
            settled["actual"] = actual[entry["series"]]()
        elif "actual" in entry and entry.get("source"):
            # A metric no series on this page carries (a new KPI in next quarter's
            # analysis) is typed once, with the place in the filing it was read.
            settled["actual"] = entry["actual"]
        else:
            raise ValueError(f"threshold `{entry['id']}` has no series to read and no typed actual with a source")
        entries.append(settled)
    return entries


def exact_growth_words(entry: dict, printed_levels: list[float]) -> str:
    """Whether a whole-percent growth rate and the rate its own printed amounts give
    fall on the same side of a threshold set to a finer grain than the company prints."""
    exact = pct_change(*printed_levels)
    side_printed = entry["actual"] >= entry["threshold"]
    side_exact = exact >= entry["threshold"]
    return (f"按它自己印的两期金额 {usd_m(printed_levels[0])} 对 {usd_m(printed_levels[1])} 算是 {exact:.2f}%"
            + ("，同样在阈值之上" if side_printed and side_exact else
               "，同样在阈值之下" if not side_printed and not side_exact else
               f"——<b>只在整数精度上{'达到' if side_printed else '没达到'}</b> {pct_text(entry['threshold'])}"))


def prior_settlement(staging: dict, prior: dict, figures: dict | None, guidance: dict | None,
                     values: dict) -> list[dict]:
    """(b): last quarter's quantified thresholds, settled against this quarter."""
    seg = staging["segment_quarterly"]
    labels = seg["periods"]
    cash = aligned(staging, "quarterly_cash")
    kpi = aligned(staging, "ma_kpi_quarterly")
    entries = prior_entries(staging, prior)
    by_id = {entry["id"]: entry for entry in entries}
    breached = [entry for entry in entries
                if headroom(entry["direction"], entry["threshold"], entry["actual"]) < 0]
    groups = sorted({entry["group"] for entry in breached})
    title = (f"上季 {len(entries)} 条量化阈值：{len(entries) - len(breached)} 条守住、{len(breached)} 条被击穿"
             + (f"——被击穿的{cn_count(len(breached))}条都是{groups[0]}" if len(breached) > 1 and len(groups) == 1
                else ""))

    exactness = {}
    if figures:
        for key, levels in (("ma_arr", "ma_arr_usd_m"), ("ma_organic", "ma_organic_cc_revenue_usd_m")):
            if key in by_id and levels in figures:
                exactness[key] = exact_growth_words(by_id[key], figures[levels])
    note = ("正值 = 仍在安全侧。"
            + ("两条增速按公司印的整数百分比结算：" + "；".join(
                f"{by_id[key]['metric']}公司印 {pct_text(by_id[key]['actual'])}，{words}"
                for key, words in exactness.items()) + "。" if exactness else "")
            + fill_story(prior.get("note", ""), values))
    overview = headroom_exhibit(
        title, entries, "actual", note,
        src_extra=("阈值逐字取自上季（" + prior["set_in"] + "）本站季报分析的「关键观察指标」，不是公司指引；"
                   "实际值为本季申报值：ARR 与有机增速取业绩 8-K EX-99.1，回购取现金流量表「Treasury shares」"
                   "（XBRL 年初至今数相减），MIS 收入取分部表。"
                   + ("另有" + cn_count(len(prior["unquantified"])) + "行无法按数字结算，逐条写在核对表里。"
                      if prior.get("unquantified") else "")),
    )

    charts = [overview]
    held_word = lambda entry: ("守住" if headroom(entry["direction"], entry["threshold"], entry["actual"]) >= 0
                               else "已击穿")
    for key, name, columns in (
            ("ma_arr", "MA ARR 同比", [("arr_growth_pct", "MA ARR 同比（公司印）", "NAVY")]),
            ("ma_organic", "MA 有机固定汇率收入同比",
             [("organic_cc_revenue_growth_pct", "有机固定汇率口径（公司印）", "NAVY"),
              ("cc_revenue_growth_pct", "固定汇率口径（2023–2024 公司只印这一口径）", "MBLUE")])):
        entry = by_id.get(key)
        if entry is None:
            continue
        axis, drawn = trimmed(labels, *(kpi[column] for column, _, _ in columns))
        charts.append(tracking_chart(
            f"{name}：{held_word(entry)}上季阈值 {pct_text(entry['threshold'])}",
            axis,
            [{"name": label, "values": values_drawn, "color": color}
             for (_, label, color), values_drawn in zip(columns, drawn)],
            [(f"上季阈值 {pct_text(entry['threshold'])}（安全侧在上方）", entry["threshold"])],
            fmt="pct1", ylab="同比 %",
            note=(f"阈值 {pct_text(entry['threshold'])}，本季公司印 {pct_text(entry['actual'])}"
                  + (f"；{exactness[key]}" if key in exactness else "")
                  + "。" + kpi["notes"][columns[0][0]]),
            src_extra=kpi["source"],
        ))
    mis = by_id.get("mis_yoy")
    if mis is not None:
        revenue = seg["mis_revenue_usd_m"]
        yoy = [None if i < 4 else round(pct_change(revenue[i], revenue[i - 4]), 2) for i in range(len(revenue))]
        finished = [value for value in yoy if value is not None]
        negative = sum(1 for value in finished if value < 0)
        charts.append(threshold_exhibit(
            f"MIS 收入同比：{held_word(mis)}上季阈值 0%（同比为负即警示）",
            labels, yoy, 0.0, fmt="pct1", ylab="同比 %", actual_name="MIS 收入同比",
            threshold_name="上季阈值 0%（安全侧在上方）", xstep=LONG_STEP,
            note=(f"上季这一行原文是「{mis['condition']} → {mis['action']}」，所以阈值是 0%，折成金额就是去年同期的 "
                  f"{usd_m(mis['threshold'])}；本季 {usd_m(mis['actual'])}、同比 "
                  f"{signed(pct_change(mis['actual'], mis['threshold']))}。"
                  f"{len(finished)} 个有同比基数的季度里 MIS 同比为负的有 {negative} 个 —— "
                  "发行窗口一关，这条线就会掉到零下，所以它守住与否是一个季度的事，不是趋势。"),
            src_extra="各期业绩 8-K EX-99.1 的分部表（外部收入口径）；同比为自算。",
        ))
    buybacks = sorted((entry for entry in entries if entry.get("series") == "share_repurchases"),
                      key=lambda entry: -entry["threshold"])
    if buybacks:
        spent = cash["share_repurchases_usd_m"]
        held = [entry for entry in buybacks
                if headroom(entry["direction"], entry["threshold"], entry["actual"]) >= 0]
        both = "（" + " 与 ".join(usd_m(entry["threshold"]) for entry in buybacks) + "）"
        if not held:
            verdict = f"击穿上季{cn_count(len(buybacks))}条阈值{both}"
        elif len(held) == len(buybacks):
            verdict = f"守住上季{cn_count(len(buybacks))}条阈值{both}"
        else:
            verdict = "、".join(f"{'守住' if entry in held else '没到'}{entry['side']}线 {usd_m(entry['threshold'])}"
                               for entry in buybacks)
        top = buybacks[0]["threshold"]
        above = sum(1 for value in spent if value is not None and value >= top)
        charts.append(tracking_chart(
            f"{labels[-1].split()[0]} 回购 {usd_m(spent[-1])}：{verdict}",
            labels,
            [{"name": "单季回购（Treasury shares）", "values": spent, "color": "NAVY"}],
            [(f"上季{entry['side']}线 {usd_m(entry['threshold'])}", entry["threshold"]) for entry in buybacks],
            fmt="usd0", ylab="US$M（单季回购）",
            note=(f"{len(labels)} 季里单季回购"
                  + (f"达到过 {usd_m(top)} 的只有{cn_count(above)}季" if above else f"一季都没到过 {usd_m(top)}")
                  + f"，最高一季是 {labels[spent.index(max(spent))]} 的 {usd_m(max(spent))}。"
                  + fill_story(prior.get("buyback_note", ""), values)
                  + (f"本季公司把全年回购指引改成「最多 US${guidance['share_repurchases_usd_b_upto']:.1f}B」。"
                     if guidance and guidance.get("share_repurchases_usd_b_upto") else "")),
            src_extra=cash["source"],
        ))
    return charts


# ── section one (c): the annual guidance record ─────────────────────────────
def guidance_record(staging: dict, facts: dict) -> list[dict]:
    """The full-year guidance record, settled against the year that followed."""
    g = staging["annual_guidance_history"]
    years = facts["years"]
    labels = [f"FY{y}" for y in years]
    actual = facts["actual"]
    feb_lo, feb_hi = facts["feb_lo"], facts["feb_hi"]
    oct_lo, oct_hi = facts["final_lo"], facts["final_hi"]
    n_done = len(facts["finished"])
    carried = [(years[i], facts["latest_vintage"][i]) for i in range(len(years))
               if facts["latest_vintage"][i] != "Oct"]

    first = years.index(2018) if 2018 in years else None
    fy2018 = ""
    if first is not None and facts["final_below"] == [2018]:
        fy2018 = (
            "<b>本页此前的答案是「一次都没有」，那是因为漏了一年。</b>"
            "FY2018 原本不在这份记录里，理由写的是「它只有十月一个 vintage」—— 回原件查，"
            f"{g['release_dates']['2018']['Feb']} 开局给的是调整后 ${feb_lo[first]:.2f}–${feb_hi[first]:.2f}，"
            "4 月与 7 月逐项重申，"
            f"10 月下调到 ${g['adj_eps_lo']['Oct'][first]:.2f}–${g['adj_eps_hi']['Oct'][first]:.2f}，"
            "四版齐全，和其余每一年一样。"
            f"而那一年的实际值是 ${actual[first]:.2f}，低于末次指引的下限。"
            "<b>被排除的那一年，恰好是唯一一年推翻这句话的。</b>"
        )
    final_band = delivery_band(
        "EX_FINAL", "调整后摊薄 EPS（对末次指引）", labels, oct_lo, oct_hi, actual,
        fmt="usd2", ylab="US$/股", unit="US$", venue="业绩新闻稿", period_word="年",
        timing=TIMING_ANNUAL,
        src_extra=(SOURCE_8K + "「末次指引」取该年 10 月那期"
                   + "".join(f"；FY{y} 尚无 10 月期，图上用 {VINTAGE_MONTH[v]}那期" for y, v in carried)
                   + "。"),
        extra_note=(
            "<b>这不是「下一季度」的指引，是「本年度」的指引，而且是当年最后一次修订的那一版。</b>"
            "公司 2 月定调、4/7/10 月各更新一次（没动的行印 NC），到 10 月这一版落笔时，全年已经过了四分之三。"
            "所以这张图问的是一个比其他页宽松得多的问题：在几乎知道答案的时候，公司报的数还会不会低于自己画的下限。"
            + fy2018
        ),
    )

    below = facts["initial_below"]
    worst_cut = min(facts["path"], key=facts["path"].get)
    wi = years.index(worst_cut)
    initial_band = delivery_band(
        "EX_INITIAL", "调整后摊薄 EPS（对初始指引）", labels, feb_lo, feb_hi, actual,
        fmt="usd2", ylab="US$/股", unit="US$", venue="业绩新闻稿", period_word="年",
        timing="该<b>年度开始时</b>",
        src_extra=SOURCE_8K + "「初始指引」取该年 2 月那期，即公司为当年定调的第一版。",
        extra_note=(
            "<b>换成年初那一版，同一家公司变成另一个样子。</b>"
            f"{n_done} 个已完结年度里实际值高于上限 {len(facts['initial_above'])} 次、"
            f"跌破下限 {len(below)} 次，"
            + ("<b>一次都没有落在区间内</b> —— 2 月画的那条带子从来没对过。"
               if not facts["initial_inside"]
               else f"落在区间内 {len(facts['initial_inside'])} 次。")
            + (f"跌破的{cn_count(len(below))}次是 " + " 与 ".join(f"FY{y}" for y in below) + "；"
               if below else "")
            + f"FY{worst_cut} "
            + (f"{CUT_STORY[worst_cut]}，" if worst_cut in CUT_STORY else "")
            + f"指引中值从 2 月的 US${mid(feb_lo[wi], feb_hi[wi]):.2f} 一路砍到 10 月的 "
            f"US${mid(g['adj_eps_lo']['Oct'][wi], g['adj_eps_hi']['Oct'][wi]):.2f}。"
            "把这张和上一张（Exhibit {EX_FINAL}）并排看才是本页第一节的全部意思 —— "
            "同一个数字、同一家公司，差别只在画线时距离年末还有多远。"
        ),
    )

    feb_values = list(facts["feb_dev"].values())
    feb_dev = midpoint_deviation(
        "EX_FEB_DEV", "调整后摊薄 EPS（2 月那版）", labels, feb_lo, feb_hi, actual,
        mode="pct", window=n_done, bar_labels=False, period_word="年",
        src_extra=SOURCE_8K + "偏离为全年实际值除以 2 月指引中值的自算值。",
        extra_note=(
            "把上面两张的量纲抹掉之后，年初预测的误差有多大一目了然："
            f"柱子从 {min(feb_values):+.1f}% 到 {max(feb_values):+.1f}%，"
            f"中位数约 {statistics.median(feb_values):+.0f}%。".replace("-", "−")
            + "这不是「公司保守」能解释的分布 —— 它是一条把评级收入押在债券发行量上的业务，"
            "而发行量不由公司决定。"
        ),
    )
    feb_mean = statistics.fmean(abs(v) for v in feb_values)
    oct_mean = statistics.fmean(abs(v) for v in facts["oct_dev"].values())
    final_below = facts["final_below"]
    oct_dev = midpoint_deviation(
        "EX_OCT_DEV", "调整后摊薄 EPS（10 月那版）", labels, oct_lo, oct_hi, actual,
        mode="pct", window=n_done, bar_labels=False, period_word="年",
        src_extra=SOURCE_8K + "偏离为全年实际值除以末次指引中值的自算值。",
        extra_note=(
            "同一个指标、同一批年份，只把画线时点从 2 月挪到 10 月，"
            f"<b>平均绝对偏离就从 {feb_mean:.1f}% 收到 {oct_mean:.1f}%</b>"
            "（见 Exhibit {EX_FEB_DEV} 与本图标题），"
            f"约{cn_fraction(oct_mean / feb_mean)}。"
            "十月那一版本质上已经不是预测：三个季度报完，剩下的是记账。"
            + (f"<b>而即便在这样的条件下，{cn_count(n_done)}年里仍然跌破过"
               f"{cn_count(len(final_below))}次（{'、'.join(f'FY{y}' for y in final_below)}）</b> —— "
               "这一点比一句「从没跌破」有信息得多"
               + ("，而它此前不在页面上，只因为那一年被以一个错误的理由排除掉了。"
                  if final_below == [2018] else "。")
               if final_below else
               f"<b>{cn_count(n_done)}年里一次都没有跌破过末次指引的下限。</b>")
        ),
    )

    # The revision path itself: four vintages per year, converging on the actual.
    path_years = [y for y in years if g["adj_eps_lo"]["Feb"][years.index(y)] is not None]
    series = []
    for v, name in (("Feb", "2 月（定调）"), ("Apr", "4 月"), ("Jul", "7 月"), ("Oct", "10 月（末次）")):
        vals = []
        for y in path_years:
            i = years.index(y)
            lo, hi = g["adj_eps_lo"][v][i], g["adj_eps_hi"][v][i]
            vals.append(None if lo is None else round(mid(lo, hi), 3))
        series.append({"name": name, "values": vals})
    series.append({"name": "全年实际", "values": [actual[years.index(y)] for y in path_years],
                   "color": "NAVY"})
    path = facts["path"]
    raise_year = max(path, key=path.get)

    def endpoints(year: int) -> str:
        i = years.index(year)
        return (f"US${mid(feb_lo[i], feb_hi[i]):.2f}",
                f"US${mid(g['adj_eps_lo']['Oct'][i], g['adj_eps_hi']['Oct'][i]):.2f}")

    both_ways = path[worst_cut] < 0 < path[raise_year]
    revision_path = {
        "ref": "EX_PATH",
        "kind": "lines",
        "title": (f"每一年的指引中值怎么被改到实际值上：FY{worst_cut} 砍了 {abs(path[worst_cut]):.0f}%，"
                  f"FY{raise_year} 抬了 {path[raise_year]:.1f}%"),
        "xlabels": [f"FY{y}" for y in path_years],
        "series": series,
        "fmt": "usd2",
        "ylab": "US$/股（指引中值与实际）",
        "note": (
            "四条线是同一年度的四个指引版本，深色那条是最后报出来的全年实际值。"
            "线越往右越贴近实际值，就是预测窗口收缩的样子。"
            + (f"<b>两个方向都发生过</b>：FY{raise_year} 从 {endpoints(raise_year)[0]} 抬到 "
               f"{endpoints(raise_year)[1]}（{path[raise_year]:+.1f}%），"
               f"FY{worst_cut} 从 {endpoints(worst_cut)[0]} 砍到 {endpoints(worst_cut)[1]}"
               f"（{minus(path[worst_cut])}）。" if both_ways else "")
            + "把这张与 Exhibit {EX_INITIAL} 一起看：年初那条带子不只是偏，而是可以整段搬家。"
        ),
        "src_extra": SOURCE_8K,
    }
    if not both_ways:
        revision_path["title"] = (f"每一年的指引中值怎么被改到实际值上：改得最多的是 FY{raise_year} 的 "
                                  f"{path[raise_year]:+.1f}%")
    return [final_band, initial_band, feb_dev, oct_dev, revision_path]


def minus(value: float) -> str:
    """``-34.0`` → ``'−34.0%'`` with the typographic minus the prose uses."""
    return f"{value:+.1f}%".replace("-", "−")


# ── section four, the two businesses: facts shared by the routine charts ────
def segment_facts(staging: dict) -> dict:
    seg = staging["segment_quarterly"]
    periods = seg["periods"]
    mis_internal = [t - e for t, e in zip(seg["mis_total_revenue_usd_m"], seg["mis_revenue_usd_m"])]
    ma_internal = [t - e for t, e in zip(seg["ma_total_revenue_usd_m"], seg["ma_revenue_usd_m"])]
    margin_slack = max(
        abs(income / total * 100 - printed)
        for income, total, printed in zip(seg["mis_adj_operating_income_usd_m"],
                                          seg["mis_total_revenue_usd_m"],
                                          seg["mis_adj_operating_margin_pct"]))
    # How far the external-revenue denominator would overstate MIS's margin.
    overstated = [income / external * 100 - income / total * 100
                  for income, external, total in zip(seg["mis_adj_operating_income_usd_m"],
                                                     seg["mis_revenue_usd_m"],
                                                     seg["mis_total_revenue_usd_m"])]
    ma = seg["ma_revenue_usd_m"]
    ma_margin = seg["ma_adj_operating_margin_pct"]
    return {
        "mis_internal": mis_internal, "ma_internal": ma_internal, "margin_slack": margin_slack,
        "overstated": (min(overstated), max(overstated)),
        "ma_dips": [periods[i] for i in range(1, len(ma)) if ma[i] < ma[i - 1]],
        "ma_yoy_negative": [periods[i] for i in range(4, len(ma)) if ma[i] < ma[i - 4]],
        "ma_yoy_count": max(len(ma) - 4, 0),
        "ma_margin_dips": [i for i in range(1, len(ma_margin)) if ma_margin[i] < ma_margin[i - 1]],
    }


def overstated_words(facts: dict) -> str:
    low, high = facts["overstated"]
    return f"{low:.1f}–{high:.1f}pp"


def segment_long_charts(staging: dict, facts: dict, sf: dict, story: dict | None,
                        values: dict) -> list[dict]:
    """The two businesses over the whole window -- routine series, not this quarter's story.

    These three used to be section two. Each is a 42-quarter range chart
    (「42 季里在 X–Y 之间」) with no reading of the quarter in its title, which
    is the routine section's job; the quarter's own findings are drawn in
    `quarter_highlights` from the Q2 analysis.
    """
    seg = staging["segment_quarterly"]
    labels = seg["periods"]
    n = len(labels)
    mis_rev = seg["mis_revenue_usd_m"]

    ma_words = ("MA 只是一路往上" if not sf["ma_dips"] else
                "MA 同比从未为负" if not sf["ma_yoy_negative"] else
                f"MA 有{cn_count(len(sf['ma_yoy_negative']))}季同比为负")
    two_lines = {
        "ref": "EX_SEG_REV",
        "kind": "lines",
        "title": (
            f"{n} 季里 MIS 收入在 US${min(mis_rev):,.0f}M–"
            f"US${max(mis_rev):,.0f}M 之间来回，{ma_words}"
        ),
        "xlabels": labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": "MIS（评级）", "values": seg["mis_revenue_usd_m"]},
            {"name": "MA（分析）", "values": seg["ma_revenue_usd_m"], "color": "NAVY"},
        ],
        "fmt": "usd0",
        "ylab": "US$M（分部外部收入）",
        "note": (
            "两条线是同一家公司的两种生意。"
            + ("MIS 的收入按发行窗口开合，最低到最高差了一倍以上；" if max(mis_rev) >= 2 * min(mis_rev)
               else f"MIS 的收入按发行窗口开合，最高是最低的 {max(mis_rev) / min(mis_rev):.1f} 倍；")
            + ((f"MA 是订阅制，{sf['ma_yoy_count']} 个有同比基数的季度里没有一个季度同比为负。")
               if not sf["ma_yoy_negative"] else
               f"MA 是订阅制，但 {sf['ma_yoy_count']} 个有同比基数的季度里有"
               f"{cn_count(len(sf['ma_yoy_negative']))}季同比为负（{'、'.join(sf['ma_yoy_negative'])}）。")
            + "本季 MIS US$" + f"{mis_rev[-1]:,.0f}M、同比 "
            + signed(pct_change(mis_rev[-1], mis_rev[-5]))
            + "；MA US$" + f"{seg['ma_revenue_usd_m'][-1]:,.0f}M、同比 "
            + signed(pct_change(seg["ma_revenue_usd_m"][-1], seg["ma_revenue_usd_m"][-5]))
            + "。"
            + (fill_story(story["ma_note"], values) if story and story.get("ma_note") else "")
        ),
        "src_extra": "各期业绩 8-K EX-99.1 的「Financial Information by Segment」表（外部收入口径）。",
    }

    share_rev, share_oi = seg["mis_share_of_revenue_pct"], seg["mis_share_of_adj_operating_income_pct"]
    worst_feb = min(facts["feb_dev"], key=facts["feb_dev"].get)
    share = {
        "ref": "EX_SHARE",
        "kind": "lines",
        "title": (
            f"评级业务占收入 {min(share_rev):.1f}%–"
            f"{max(share_rev):.1f}%，占调整后营业利润 "
            f"{min(share_oi):.1f}%–"
            f"{max(share_oi):.1f}%"
        ),
        "xlabels": labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": "MIS 占收入", "values": share_rev},
            {"name": "MIS 占调整后营业利润", "values": share_oi, "color": "NAVY"},
        ],
        "fmt": "pct1",
        "ylab": "%（MIS 占合并口径的比重）",
        "note": (
            "<b>这张图是本页对「穆迪是什么公司」的回答。</b>"
            + (f"评级业务在最差的季度只贡献不到一半收入，却从没有低于过合并调整后营业利润的 "
               f"{math.floor(min(share_oi))}%。" if min(share_rev) < 50 else
               f"评级业务在最差的季度也贡献 {min(share_rev):.0f}% 的收入、"
               f"{math.floor(min(share_oi))}% 以上的调整后营业利润。")
            + "两条线之间的缺口就是两块业务的利润率差："
            f"本季 MIS {seg['mis_adj_operating_margin_pct'][-1]:.1f}% 对 "
            f"MA {seg['ma_adj_operating_margin_pct'][-1]:.1f}%。"
            "所以全年指引的成败几乎完全压在发行量上"
            + (f" —— 这正是第一板块 Exhibit {{EX_FEB_DEV}} 里 FY{worst_feb} 那根负柱的来源。"
               if facts["feb_dev"][worst_feb] < 0 else "。")
        ),
        "src_extra": "同上表；占比为分部值除以合并值的自算。",
    }

    ma_margin = seg["ma_adj_operating_margin_pct"]
    low_i = ma_margin.index(min(ma_margin))
    dips = sf["ma_margin_dips"]
    margins = {
        "ref": "EX_SEG_MARGIN",
        "kind": "lines",
        "title": (
            f"两条分部调整后营业利润率：MIS 在 {min(seg['mis_adj_operating_margin_pct']):.1f}%–"
            f"{max(seg['mis_adj_operating_margin_pct']):.1f}% 之间摆动，"
            + ("MA 稳步抬升" if not dips else f"MA 从 {ma_margin[0]:.1f}% 抬到 {ma_margin[-1]:.1f}%")
        ),
        "xlabels": labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": "MIS 调整后营业利润率", "values": seg["mis_adj_operating_margin_pct"]},
            {"name": "MA 调整后营业利润率", "values": ma_margin, "color": "NAVY"},
            {"name": "合并调整后营业利润率", "values": seg["adj_operating_margin_pct"], "color": "GOLD"},
        ],
        "fmt": "pct1",
        "ylab": "%",
        "note": (
            "MIS 的利润率跟着发行量走，因为评级业务的成本是分析师团队，短期内不随收入伸缩；"
            + (f"MA 的利润率是被成本纪律一格一格抬上去的，{n} 季里从 "
               f"{ma_margin[0]:.1f}% 到 {ma_margin[-1]:.1f}%。" if not dips else
               f"MA 的利润率 {n} 季里从 {ma_margin[0]:.1f}% 抬到 {ma_margin[-1]:.1f}%，"
               f"但不是一格一格抬上去的：{n - 1} 次环比里 {len(dips)} 次回落，"
               f"最低一格是 {labels[low_i]} 的 {ma_margin[low_i]:.1f}%。")
            + "合并那条落在两者之间，位置由当季的收入结构决定，而不是由任何一块的经营决定。"
            "<b>这三条是公司披露值，分母是分部<i>总</i>收入（含分部间收入），"
            "不是 Exhibit {EX_SEG_REV} 与 Exhibit {EX_SHARE} 画的外部收入。</b>MIS 每季向 MA 内部计费 "
            f"US${min(sf['mis_internal']):,.0f}–{max(sf['mis_internal']):,.0f}M，"
            f"拿外部收入去除会把 MIS 的利润率高估 {overstated_words(sf)}；按总收入复算，"
            f"{n} 个季度与公司印出来的百分比最大只差 {sf['margin_slack']:.2f}pp。"
        ),
        "src_extra": (
            "同上表；分部调整后营业利润率为公司披露值，分母为分部总收入（外部收入加分部间收入）。"
        ),
    }
    return [two_lines, share, margins]


# ── section two: this quarter's findings, from this quarter's analysis ─────
def cash_facts(staging: dict) -> dict:
    """Free cash flow and shareholder returns per quarter, and year-to-date ratios.

    Returns are the company's own definition in the release ("returned … in share
    repurchases and dividends"): Treasury shares plus dividends paid, without the
    shares withheld for stock-based compensation. A year-to-date ratio whose free
    cash flow is not positive (Q1 2017, the DOJ settlement quarter) has no
    meaning and is left out rather than drawn as a negative percentage.
    """
    cash = aligned(staging, "quarterly_cash")
    periods = cash["periods"]
    fcf = [round(o - c, 1) for o, c in zip(cash["operating_cash_flow_usd_m"], cash["capital_additions_usd_m"])]
    returns = [round(b + d, 1) for b, d in zip(cash["share_repurchases_usd_m"], cash["dividends_paid_usd_m"])]
    ytd_ratio, ttm_ratio = [], []
    for i, period in enumerate(periods):
        quarter = int(period[1])
        ytd_fcf = sum(fcf[i - quarter + 1: i + 1])
        ytd_ret = sum(returns[i - quarter + 1: i + 1])
        ytd_ratio.append(round(ytd_ret / ytd_fcf * 100, 2) if ytd_fcf > 0 else None)
        ttm = sum(fcf[i - 3: i + 1]) if i >= 3 else None
        ttm_ratio.append(round(sum(returns[i - 3: i + 1]) / ttm * 100, 2) if ttm and ttm > 0 else None)
    quarter = int(periods[-1][1])
    halves = {}
    for i, period in enumerate(periods):
        if period.startswith("Q2"):
            halves[period[-4:]] = (sum(returns[i - 1: i + 1]), sum(fcf[i - 1: i + 1]))
    return {"fcf": fcf, "returns": returns, "ytd_ratio": ytd_ratio, "ttm_ratio": ttm_ratio,
            "ytd_returns": sum(returns[-quarter:]), "ytd_fcf": sum(fcf[-quarter:]), "halves": halves}


def told(story: dict | None, key: str, values: dict) -> str:
    """A sentence that belongs to one quarter, from the stamped story block, or nothing.

    The readings of the quarter's analysis and the call's colour are not facts a
    roll can recompute, so they live in `quarter_story` (stamped with its period)
    and disappear with it -- a new quarter without its own story block prints no
    reading rather than last quarter's.
    """
    return fill_story(story[key], values) if story and story.get(key) else ""


def ytd_words(period: str) -> str:
    """``'Q2 2026'`` → ``'上半年'``: how the release itself names a year-to-date span."""
    return {"Q1": "一季度", "Q2": "上半年", "Q3": "前三季度", "Q4": "全年"}[period.split()[0]]


def quarter_highlights(staging: dict, figures: dict | None, guidance: dict | None, bridges: dict | None,
                       story: dict | None, prior: dict | None, values: dict) -> list[dict]:
    """Section two: one chart per finding of the quarter's analysis that filings can draw."""
    seg = staging["segment_quarterly"]
    labels = seg["periods"]
    period, previous = labels[-1], labels[-2]
    kpi = aligned(staging, "ma_kpi_quarterly")
    charts = []

    # Insight 1: the window reopened and nearly all of the extra revenue reached profit.
    d_rev = {who: seg[f"{key}revenue_usd_m"][-1] - seg[f"{key}revenue_usd_m"][-2]
             for who, key in (("MIS", "mis_"), ("MA", "ma_"), ("合并", ""))}
    d_aoi = {who: seg[f"{key}adj_operating_income_usd_m"][-1] - seg[f"{key}adj_operating_income_usd_m"][-2]
             for who, key in (("MIS", "mis_"), ("MA", "ma_"), ("合并", ""))}
    mis_margin = seg["mis_adj_operating_margin_pct"]
    incremental = d_aoi["合并"] / d_rev["合并"] * 100 if d_rev["合并"] > 0 else None
    mix = ""
    if figures and figures.get("transaction_revenue_usd_m"):
        now, before = figures["transaction_revenue_usd_m"]
        if d_rev["合并"] > 0:
            mix = (f"合并收入的环比增量里 {usd_m(now - before)} 来自交易性收入（{(now - before) / d_rev['合并'] * 100:.0f}%）"
                   "—— 周期性的那一部分。")
    charts.append({
        "ref": "EX_LEVERAGE",
        "kind": "grouped_bars",
        "title": (f"环比多出的 {usd_m(d_rev['合并'])} 收入里有 {usd_m(d_aoi['合并'])} 落成调整后营业利润"
                  + (f"：增量利润率 {incremental:.0f}%" if incremental is not None else "")),
        "xlabels": ["MIS", "MA", "合并"],
        "groups": [
            {"name": f"收入环比变动（{previous} → {period}）", "values": [d_rev[w] for w in ("MIS", "MA", "合并")],
             "color": "BLUE"},
            {"name": "调整后营业利润环比变动", "values": [d_aoi[w] for w in ("MIS", "MA", "合并")], "color": "NAVY"},
        ],
        "bar_labels": True,
        "fmt": "usd0",
        "label_fmt": "usd0",
        "ylab": "US$M（环比变动）",
        "note": (
            f"MIS 收入环比 {'+' if d_rev['MIS'] >= 0 else '−'}{usd_m(abs(d_rev['MIS']))}、调整后营业利润 "
            f"{'+' if d_aoi['MIS'] >= 0 else '−'}{usd_m(abs(d_aoi['MIS']))}；MA 收入 "
            f"{'+' if d_rev['MA'] >= 0 else '−'}{usd_m(abs(d_rev['MA']))}，调整后营业利润却 "
            f"{'+' if d_aoi['MA'] >= 0 else '−'}{usd_m(abs(d_aoi['MA']))}。" + mix
            + f"MIS 调整后营业利润率 {mis_margin[-1]:.1f}%"
            + (f"，{len(labels)} 季最高" if mis_margin[-1] == max(mis_margin) else "")
            + "。" + told(story, "leverage_reading", values)
        ),
        "src_extra": "各期业绩 8-K EX-99.1 的分部表：收入为外部收入口径，调整后营业利润为公司披露值；环比变动为自算。"
                     + ("交易性收入取 Table 6（Transaction and Recurring Revenue）。" if mix else ""),
    })

    if figures and figures.get("mis_lines_growth_pct"):
        lines = figures["mis_lines_growth_pct"]
        body = list(zip(lines["labels"][:-1], lines["prior"][:-1], lines["this"][:-1]))
        accelerated = [name for name, before, now in body if now > before]
        fastest = max(body, key=lambda row: row[2])
        second = sorted(body, key=lambda row: -row[2])[1]
        issuance = figures.get("mis_rated_issuance_growth_pct")
        transaction = figures.get("mis_transaction_revenue_growth_pct")
        charts.append({
            "ref": "EX_MIS_LINES",
            "kind": "grouped_bars",
            "title": (f"MIS 同比从 {previous.split()[0]} 的 {lines['prior'][-1]:+.0f}% 跳到 {lines['this'][-1]:+.0f}%："
                      + (f"{cn_count(len(body))}条业务线全部加速" if len(accelerated) == len(body) else
                         f"{cn_count(len(accelerated))}条业务线加速")
                      + f"，{short_line(fastest[0])} {fastest[2]:+.0f}%、{short_line(second[0])} {second[2]:+.0f}%"),
            "xlabels": [short_line(name) for name in lines["labels"]],
            "groups": [
                {"name": f"{previous} 同比", "values": lines["prior"], "color": "BLUE"},
                {"name": f"{period} 同比", "values": lines["this"], "color": "NAVY"},
            ],
            "bar_labels": True,
            "fmt": "pct0",
            "label_fmt": "pct0",
            "ylab": "同比 %（公司印的整数）",
            "note": (
                "柱子是公司印的整数增速。"
                + (f"本季 MIS 交易性收入 {transaction:+.0f}%、评级发行量 {issuance:+.0f}%"
                   + ("，同比算下来的单位变现率基本持平。" if abs(transaction - issuance) <= 2 else
                      f"，交易性收入比发行量{'快' if transaction > issuance else '慢'} "
                      f"{abs(transaction - issuance):.0f} 个百分点。")
                   if issuance is not None and transaction is not None else "")
                + told(story, "mis_lines_reading", values)
            ),
            "src_extra": f"{period} 与 {previous} 业绩 8-K EX-99.1 的 MIS 分业务线表与发行量表（增速为公司印的整数）。",
        })

    if figures and figures.get("ma_arr_lines_growth_pct"):
        lines = figures["ma_arr_lines_growth_pct"]
        body = list(zip(lines["labels"], lines["prior"], lines["this"]))[:-1]
        up = [(name, now - before) for name, before, now in body if now > before and "合计" not in name]
        down = [(name, before, now) for name, before, now in body if now < before and "合计" not in name]
        reported = pct_change(seg["ma_revenue_usd_m"][-1], seg["ma_revenue_usd_m"][-5])
        organic = kpi["organic_cc_revenue_growth_pct"][-1]
        charts.append({
            "ref": "EX_ARR_LINES",
            "kind": "grouped_bars",
            "title": (f"MA ARR 同比从 {lines['prior'][-1]:.0f}% 到 {lines['this'][-1]:.0f}%："
                      + "、".join(f"{short_line(name)} 加速 {gap:.0f} 个百分点" for name, gap in up)
                      + ("，" + "、".join(f"{short_line(name)} 从 {before:.0f}% 降到 {now:.0f}%" for name, before, now in down)
                         if down else "")),
            "xlabels": [short_line(name) for name in lines["labels"]],
            "groups": [
                {"name": f"{previous} ARR 同比", "values": lines["prior"], "color": "BLUE"},
                {"name": f"{period} ARR 同比", "values": lines["this"], "color": "NAVY"},
            ],
            "bar_labels": True,
            "fmt": "pct0",
            "label_fmt": "pct0",
            "ylab": "ARR 同比 %（公司印的整数）",
            "note": (
                f"MA 报告收入同比 {signed(reported)}、有机固定汇率 {organic:+.0f}%"
                + ("，差的是两笔业务处置（见口径说明）" if story and story.get("divestitures") else "")
                + "。" + told(story, "arr_reading", values)
            ),
            "src_extra": f"{period} 与 {previous} 业绩 8-K EX-99.1 的 MA ARR 分线表（固定汇率、剔除 12 个月内并购与处置）。",
        })

    if figures and figures.get("eps_bridge_usd"):
        gaap = figures["diluted_eps_usd"]
        steps = figures["eps_bridge_usd"]
        running, values_drawn = gaap, [gaap]
        for _, delta in steps:
            running = round(running + delta, 2)
            values_drawn.append(running)
        values_drawn.append(running)
        gain = next((delta for name, delta in steps if "处置" in name), None)
        full_year = next((delta for name, delta in (bridges or {}).get("eps", {}).get("addbacks", [])
                          if "处置" in name), None)
        charts.append({
            "ref": "EX_EPS_BRIDGE",
            "kind": "bars_labeled",
            "title": (f"GAAP 摊薄 EPS US${gaap:.2f} 里有 US${abs(gain):.2f} 是业务处置收益：调整后 US${running:.2f}"
                      if gain is not None else f"GAAP 摊薄 EPS US${gaap:.2f}，调整后 US${running:.2f}"),
            "xlabels": ["GAAP 摊薄 EPS"] + [name for name, _ in steps] + ["调整后摊薄 EPS"],
            "xrot": 90,
            "values": values_drawn,
            "fmt": "usd2",
            "ylab": f"US$/股（{period} 单季）",
            "note": (
                f"逐项加减：US${gaap:.2f}"
                + "".join(f" {'+' if delta >= 0 else '−'} {money(delta)}" for _, delta in steps)
                + f" = <b>US${running:.2f}</b>，与公司印的调整后 EPS 一致。"
                + (f"全年指引桥里的处置收益约 US${abs(full_year):.2f}/股，本季确认 US${abs(gain):.2f}，"
                   f"余下约 US${abs(full_year) - abs(gain):.2f} 要在后面几季确认。"
                   if gain is not None and full_year is not None else "")
                + told(story, "eps_reading", values)
                + ("看经营要看调整后 EPS；GAAP EPS 的同比被一次性收益放大了。" if gain is not None else "")
            ),
            "src_extra": f"{period} 业绩 8-K EX-99.1 Table 11 的每股调节（各项为税后）。",
        })

    cf = cash_facts(staging)
    ratio = cf["ytd_returns"] / cf["ytd_fcf"] * 100
    span = ytd_words(period)
    past = {year: r / f * 100 for year, (r, f) in cf["halves"].items() if f > 0 and year != period[-4:]}
    top_year = max(past, key=past.get) if past else None
    net_debt = ""
    if figures and figures.get("balance_sheet"):
        bs = figures["balance_sheet"]
        start, end = (bs["debt_usd_m"][i] - bs["cash_usd_m"][i] - bs["short_term_investments_usd_m"][i]
                      for i in (0, 1))
        net_debt = (f"净债务（总借款减现金与短期投资）从 {bs['dates'][0]} 的 {usd_m(start)} 升到 "
                    f"{bs['dates'][1]} 的 {usd_m(end)}，{'+' if end >= start else '−'}{usd_m(abs(end - start))}。")
    guide = ""
    g = staging["annual_guidance_history"]
    if guidance:
        year = str(guidance["fiscal_year"])
        vintage = next(v for v in reversed(VINTAGES) if g["release_dates"][year][v] == guidance["as_of"])
        before = VINTAGES[VINTAGES.index(vintage) - 1] if vintage != "Feb" else None
        i = g["fiscal_years"].index(guidance["fiscal_year"])
        if before:
            lo_b, hi_b = g["fcf_usd_b_lo"][before][i], g["fcf_usd_b_hi"][before][i]
            lo, hi = guidance["free_cash_flow_usd_b"]
            guide = (f"同一份新闻稿里，FY{year} 自由现金流指引从 US${lo_b:.1f}–{hi_b:.1f}B "
                     + ("下调到" if lo < lo_b else "改为") + f" US${lo:.1f}–{hi:.1f}B，"
                     + (f"回购指引却从约 US${prior['buyback_guide_prior_usd_b']:.1f}B "
                        if prior and prior.get("buyback_guide_prior_usd_b") else "回购指引")
                     + f"提高到「最多 US${guidance['share_repurchases_usd_b_upto']:.1f}B」。")
    charts.append({
        "ref": "EX_RETURNS",
        "kind": "grouped_bars",
        "title": (f"{span}回购加股息 {usd_m(cf['ytd_returns'])}，是同期自由现金流 {usd_m(cf['ytd_fcf'])} 的 {ratio:.0f}%"),
        "xlabels": labels,
        "xstep": LONG_STEP,
        "groups": [
            {"name": "自由现金流 D", "values": cf["fcf"], "color": "BLUE"},
            {"name": "回购 + 股息", "values": cf["returns"], "color": "NAVY"},
        ],
        "bar_labels": False,
        "fmt": "usd0",
        "label_fmt": "usd0",
        "ylab": "US$M（单季）",
        "note": (
            guide + net_debt
            + (f"{len(past)} 个往年的上半年里，比率最高的是 {top_year} 年的 {past[top_year]:.0f}%"
               + ("，本季的比率不是纪录" if top_year and past[top_year] > ratio else "，本季比它们都高")
               + "。" if top_year and period.startswith("Q2") else "")
            + told(story, "returns_reading", values)
        ),
        "src_extra": (aligned(staging, "quarterly_cash")["source"]
                      + (" 净债务取本季业绩 8-K EX-99.1 Table 2 的两栏。" if net_debt else "")),
    })
    return charts


def short_line(name: str) -> str:
    """A line-of-business name short enough for an axis label."""
    return {"Public, Project and Infrastructure Finance": "PPIF", "Corporate Finance": "CFG",
            "Structured Finance": "SFG", "Financial Institutions": "FIG",
            "Research and Insights": "R&I", "Data and Information": "D&I",
            "Decision Solutions 合计": "Decision Solutions"}.get(name, name)


# ── section one (c) bridge, then section three: the next quarter's thresholds
def margin_point(margin: dict) -> bool:
    """A GAAP margin guided as one number ("Approximately 45%") against a range."""
    return margin["gaap"][0] == margin["gaap"][1] and margin["adjusted"][0] != margin["adjusted"][1]


def bridge_sums(bridges: dict) -> dict:
    """Whether each of the three printed bridges adds up.

    A range bridges to a range end for end. A GAAP margin the company guided as
    a single number cannot land on both ends of an adjusted range; it closes when
    it lands inside it (April 2026: about 45% plus 7.5 points is 52.5%, inside
    52%-53%).
    """
    eps, margin, fcf = bridges["eps"], bridges["margin"], bridges["fcf"]
    eps_add = sum(delta for _, delta in eps["addbacks"])
    margin_add = sum(delta for _, delta in margin["addbacks"])
    if margin_point(margin):
        margin_ok = margin["adjusted"][0] - 0.05 <= margin["gaap"][0] + margin_add <= margin["adjusted"][1] + 0.05
    else:
        margin_ok = all(abs(g + margin_add - a) < 0.05 for g, a in zip(margin["gaap"], margin["adjusted"]))
    return {
        "eps": all(abs(g + eps_add - a) < 0.005 for g, a in zip(eps["gaap"], eps["adjusted"])),
        "margin": margin_ok,
        "fcf": all(abs(o - fcf["capex"] - f) < 0.005 for o, f in zip(fcf["ocf"], fcf["fcf"])),
    }


def margin_bridge_words(margin: dict) -> str:
    total = margin["gaap"][0] + sum(delta for _, delta in margin["addbacks"])
    terms = (f"{pct_words(margin['gaap'][0])}"
             + "".join(f"+{pct_words(delta)}" for _, delta in margin["addbacks"]))
    if margin_point(margin):
        return (f"营业利润率约 {terms} = {pct_words(round(total, 2))}，落在调整后区间 "
                f"{pct_words(margin['adjusted'][0])}–{pct_words(margin['adjusted'][1])} 之内")
    return f"营业利润率 {terms} = {pct_words(margin['adjusted'][0])}"


def guidance_bridge(guidance: dict | None, bridges: dict | None, release_date: str) -> list[dict]:
    """The open year's EPS bridge: the licence for reading the guidance table as arithmetic."""
    charts = []
    year = guidance["fiscal_year"] if guidance else None
    if bridges:
        eps = bridges["eps"]
        closes = bridge_sums(bridges)
        steps = ["GAAP 摊薄 EPS 指引"] + [name for name, _ in eps["addbacks"]] + ["调整后摊薄 EPS 指引"]
        lo_vals = [eps["gaap"][0]]
        running = eps["gaap"][0]
        for _, delta in eps["addbacks"]:
            running = round(running + delta, 2)
            lo_vals.append(running)
        # 第七根柱：`steps` 是 1 + 5 + 1，这个循环只产出 1 + 5。少的那一根正是
        # 「调整后摊薄 EPS 指引」——本图存在的理由。渲染器按 xlabels 的长度走，
        # vals[6] 是 undefined，被 `v == null` 静默跳过：没有 NaN、没有报错，
        # 只是结果那一栏空着，而 US$16.50 印在「业务处置收益」头上。
        lo_vals.append(running)
        count = cn_count(len(eps["addbacks"]))
        sum_words = (f"US${eps['gaap'][0]:.2f}"
                     + "".join(f" {'+' if delta >= 0 else '−'} {money(delta)}" for _, delta in eps["addbacks"])
                     + f" = <b>US${running:.2f}</b>")
        margin = bridges["margin"]
        cash = bridges["fcf"]
        negative = [name for name, delta in eps["addbacks"] if delta < 0]
        charts.append({
            "ref": "EX_BRIDGE",
            "kind": "bars_labeled",
            "title": (f"指引表自己就能对平：GAAP 指引下限加{count}项加回项，正好等于调整后指引下限 "
                      f"US${eps['adjusted'][0]:.2f}" if closes["eps"] else
                      f"指引表的 EPS 桥：GAAP 指引下限加{count}项加回项是 US${running:.2f}，"
                      f"公司印的调整后下限是 US${eps['adjusted'][0]:.2f}"),
            "xlabels": steps,
            "xrot": 90,
            "values": lo_vals,
            "fmt": "usd2",
            "ylab": f"US$/股（FY{year} 指引下限口径）",
            "note": (
                "公司在同一份文件里把 GAAP 指引调节到调整后指引，每一项都点名并给了金额。"
                f"把它们逐项加回去，{sum_words}，"
                + (f"与公司自己印出来的调整后下限逐分吻合；上限同理得 US${eps['adjusted'][1]:.2f}。"
                   "<b>这是本页愿意把这张指引表当作算术而不是口号来用的依据。</b>"
                   if closes["eps"] else
                   f"与公司印出来的调整后下限 US${eps['adjusted'][0]:.2f} 对不上。")
                + ("同一份文件里另外两条桥也各自对平：" if closes["margin"] and closes["fcf"] else
                   "同一份文件里另外两条桥：")
                + margin_bridge_words(margin) + "，"
                f"经营现金流 US${cash['ocf'][0]:.2f}B 减资本开支约 US${cash['capex']:.2f}B = "
                f"自由现金流 US${cash['fcf'][0]:.2f}B。"
            ),
            "src_extra": (
                f"FY{year} 指引与调节均取自 {release_date} 业绩 8-K EX-99.1；"
                "加回项为公司列示值"
                + (f"，负号项为{'、'.join(negative)}。" if negative else "。")
            ),
        })
    return charts


def open_year_fcf_guide(staging: dict) -> tuple[int, list[str], list[float], list[float]]:
    """The open fiscal year's free-cash-flow guidance, vintage by vintage, from the record."""
    g = staging["annual_guidance_history"]
    i = len(g["fiscal_years"]) - 1
    drawn = [v for v in VINTAGES if g["fcf_usd_b_lo"][v][i] is not None]
    return (g["fiscal_years"][i], [VINTAGE_MONTH[v] + "版" for v in drawn],
            [g["fcf_usd_b_lo"][v][i] for v in drawn], [g["fcf_usd_b_hi"][v][i] for v in drawn])


def next_entries(staging: dict, next_kpi: dict) -> list[dict]:
    """This quarter's §8 thresholds with the current reading, computed from the series."""
    seg = staging["segment_quarterly"]
    kpi = aligned(staging, "ma_kpi_quarterly")
    cf = cash_facts(staging)
    current = {
        "mis_revenue": lambda: seg["mis_revenue_usd_m"][-1],
        "ma_arr_growth": lambda: kpi["arr_growth_pct"][-1],
        "ma_recurring_growth": lambda: kpi["organic_cc_recurring_growth_pct"][-1],
        "ma_margin": lambda: seg["ma_adj_operating_margin_pct"][-1],
        "fcf_guide_low": lambda: open_year_fcf_guide(staging)[2][-1],
        "returns_to_fcf_ytd": lambda: round(cf["ytd_returns"] / cf["ytd_fcf"] * 100, 2),
    }
    entries = []
    for entry in next_kpi["quantified"]:
        if entry.get("series") in current:
            if "current" in entry:
                raise ValueError(f"threshold `{entry['id']}` is computed from the series; remove its typed current")
            value = current[entry["series"]]()
            if value is None:
                raise ValueError(f"threshold `{entry['id']}` has no {entry['series']} reading for the quarter")
        elif "current" in entry and entry.get("source"):
            value = entry["current"]    # a metric no series here carries: typed once, with its source
        else:
            raise ValueError(f"threshold `{entry['id']}` has no series to read and no typed current with a source")
        entries.append({**entry, "current": value})
    return entries


def next_watch(staging: dict, next_kpi: dict | None, guidance: dict | None, story: dict | None,
               figures: dict | None, values: dict) -> list[dict]:
    """Section three: the quarter analysis's §8 thresholds, one chart per tracked series."""
    if next_kpi is None:
        return []
    seg = staging["segment_quarterly"]
    labels = seg["periods"]
    period = labels[-1]
    target = next_kpi["for_period"]
    kpi = aligned(staging, "ma_kpi_quarterly")
    entries = next_entries(staging, next_kpi)
    gap = {entry["id"]: headroom(entry["direction"], entry["threshold"], entry["current"]) for entry in entries}
    breached = [entry for entry in entries if gap[entry["id"]] < 0]
    on_line = [entry for entry in entries if gap[entry["id"]] == 0]
    down = [entry for entry in entries if entry.get("revocation") == "down"]
    up = [entry for entry in entries if entry.get("revocation") == "up"]

    def bar(entry: dict) -> str:
        sign = "≥" if entry["direction"] == "up" else "≤"
        return f"{entry['metric']} {sign} {unit_value(entry['unit'], entry['threshold'])}"

    overview = headroom_exhibit(
        (f"下季 {len(entries)} 条量化阈值："
         + (f"{len(breached)} 条当前已越过 —— " + "、".join(entry["metric"] for entry in breached)
            if breached else "当前全部在安全侧")),
        entries, "current",
        ("正值 = 仍在安全侧。当前值是 " + period + " 的读数，阈值针对 " + target
         + (f"；正好压在线上的有{cn_count(len(on_line))}条（" + "、".join(entry["metric"] for entry in on_line) + "）"
            if on_line else "")
         + "。本季分析的立场撤销条件：向下 —— " + "、".join(
             f"{entry['metric']}{'低于' if entry['direction'] == 'up' else '高于'} {unit_value(entry['unit'], entry['threshold'])}"
             for entry in down)
         + "；向上 —— " + "、".join(bar(entry) for entry in up) + "。"),
        src_extra=("阈值逐字取自本季（" + period + "）本站季报分析第 8 节「关键观察指标」，不是公司指引；"
                   "当前值为本季申报值或据其自算。另有" + cn_count(len(next_kpi.get("disclosure_gated", [])))
                   + "条无法按数字跟踪，写在本节说明与核对表里。"),
    )
    charts = [overview]

    def group(series: str) -> list[dict]:
        return sorted((entry for entry in entries if entry.get("series") == series), key=lambda e: e["threshold"])

    def title(name: str, members: list[dict], fmt) -> str:
        return (f"{name}：下季阈值 " + " / ".join(fmt(entry["threshold"]) for entry in members)
                + f"，当前 {fmt(members[0]['current'])}")

    mis = group("mis_revenue")
    if mis:
        revenue = seg["mis_revenue_usd_m"]
        quarter = target.split()[0]
        year_ago = f"{quarter} {int(target[-4:]) - 1}"
        base = revenue[labels.index(year_ago)] if year_ago in labels else None
        years = sorted({int(label[-4:]) for label in labels})
        seasonal = [y for y in years if f"{quarter} {y}" in labels and f"Q2 {y}" in labels]
        lower = [y for y in seasonal if revenue[labels.index(f"{quarter} {y}")] < revenue[labels.index(f"Q2 {y}")]]
        charts.append(tracking_chart(
            title(f"{quarter} MIS 收入", mis, usd_m), labels,
            [{"name": "MIS 季度收入", "values": revenue, "color": "NAVY"}],
            [(f"{entry['metric']} {usd_m(entry['threshold'])}", entry["threshold"]) for entry in mis],
            fmt="usd0", ylab="US$M（MIS 外部收入）",
            note=((f"去年同期（{year_ago}）是 {usd_m(base)}，所以 "
                   + "、".join(f"{usd_m(entry['threshold'])} 约等于同比 {signed(pct_change(entry['threshold'], base))}"
                              for entry in mis) + "。" if base else "")
                  + (f"当前值是 {period} 的，而 MIS 有季节性：{len(seasonal)} 年里 {quarter} 低于同年 Q2 的有 "
                     f"{len(lower)} 年。" if quarter != "Q2" and seasonal else "")
                  + (told(story, "mis_next_words", values) + "；" if story and story.get("mis_next_words") else "")
                  + "全年 MIS 收入指引是文字口径"
                  + (f"（{story['verbal_quote']}）" if story and story.get("verbal_quote") else "")
                  + " —— 本页不把文字换算成端点。"),
            src_extra="各期业绩 8-K EX-99.1 的分部表（外部收入口径）。",
        ))

    for series, name, columns in (
            ("ma_arr_growth", "MA ARR 同比", [("arr_growth_pct", "MA ARR 同比（公司印）", "NAVY")]),
            ("ma_recurring_growth", "MA 有机固定汇率经常性收入同比",
             [("organic_cc_recurring_growth_pct", "有机固定汇率口径（公司印）", "NAVY"),
              ("cc_recurring_growth_pct", "固定汇率口径（2023–2024 公司只印这一口径）", "MBLUE")])):
        members = group(series)
        if not members:
            continue
        axis, drawn = trimmed(labels, *(kpi[column] for column, _, _ in columns))
        charts.append(tracking_chart(
            title(name, members, pct_text), axis,
            [{"name": label, "values": values_drawn, "color": color}
             for (_, label, color), values_drawn in zip(columns, drawn)],
            [(f"{entry['metric'].split('（')[-1].rstrip('）')} {pct_text(entry['threshold'])}", entry["threshold"])
             for entry in members],
            fmt="pct1", ylab="同比 %",
            note=(" / ".join(f"{pct_text(entry['threshold'])}：{entry['condition']} → {entry['action']}" for entry in members)
                  + "（ARR 与有机固定汇率经常性收入两条一起判）。" + kpi["notes"][columns[0][0]]),
            src_extra=kpi["source"],
        ))

    margin = group("ma_margin")
    if margin:
        entry = margin[0]
        values_ma = seg["ma_adj_operating_margin_pct"]
        quarter = target.split()[0]
        years = sorted({int(label[-4:]) for label in labels})
        pairs = [y for y in years if f"{quarter} {y}" in labels and f"Q2 {y}" in labels]
        higher = [y for y in pairs if values_ma[labels.index(f"{quarter} {y}")] > values_ma[labels.index(f"Q2 {y}")]]
        half = [i for i, label in enumerate(labels) if label[-4:] == period[-4:]]
        h1 = (sum(seg["ma_adj_operating_income_usd_m"][i] for i in half)
              / sum(seg["ma_total_revenue_usd_m"][i] for i in half) * 100)
        band = guidance.get("ma_adj_operating_margin_pct") if guidance else None
        charts.append(tracking_chart(
            f"{quarter} MA 调整后营业利润率：下季阈值 {pct_text(entry['threshold'])}，当前 {entry['current']:.1f}%",
            labels, [{"name": "MA 调整后营业利润率", "values": values_ma, "color": "NAVY"}],
            [(f"下季阈值 {pct_text(entry['threshold'])}（{entry['condition']} → {entry['action']}）", entry["threshold"])],
            fmt="pct1", ylab="%（公司披露，分母为分部总收入）",
            note=(f"年初至今 {h1:.1f}%（按分部表逐季的调整后营业利润与总收入相加复算）"
                  + (f"，低于全年指引 {pct_text(band[0])}–{pct_text(band[1])}，所以余下几季平均必须高于全年区间"
                     if band and h1 < band[0] else "")
                  + "。" + (f"{len(pairs)} 年里 {quarter} 的 MA 利润率高于同年 Q2 的有 {len(higher)} 年。"
                             if quarter != "Q2" and pairs else "")),
            src_extra="各期业绩 8-K EX-99.1 的分部表；全年指引取本季指引表的 MA Adjusted Operating Margin 行。",
        ))

    fcf_guide = group("fcf_guide_low")
    if fcf_guide:
        entry = fcf_guide[0]
        year, months, low, high = open_year_fcf_guide(staging)
        charts.append(tracking_chart(
            f"FY{year} 自由现金流指引下限：下季阈值 US${entry['threshold']:.1f}B，当前 US${entry['current']:.1f}B",
            months,
            [{"name": "指引下限", "values": low, "color": "NAVY"}, {"name": "指引上限", "values": high, "color": "MBLUE"}],
            [(f"下季阈值 US${entry['threshold']:.1f}B（{entry['condition']} → {entry['action']}）", entry["threshold"])],
            fmt="usd1", ylab=f"US$B（FY{year} 自由现金流指引）",
            note=(f"FY{year} 这一年的指引依次是 " + "、".join(
                f"{month} US${a:.1f}–{b:.1f}B" for month, a, b in zip(months, low, high))
                + (f"；最近一版的下限已经压在 US${entry['threshold']:.1f}B 上，再下调一次就越线。"
                   if low[-1] == entry["threshold"] else "。")),
            src_extra="各期业绩 8-K EX-99.1 的全年指引表（Free Cash Flow 行）。",
        ))

    ratio = group("returns_to_fcf_ytd")
    if ratio:
        entry = ratio[0]
        cf = cash_facts(staging)
        ttm = cf["ttm_ratio"][-1]
        net_debt = ""
        if figures and figures.get("balance_sheet"):
            bs = figures["balance_sheet"]
            start, end = (bs["debt_usd_m"][i] - bs["cash_usd_m"][i] - bs["short_term_investments_usd_m"][i]
                          for i in (0, 1))
            net_debt = (f"另一半条件「净债务继续上升」：{bs['dates'][0]} 到 {bs['dates'][1]} 净债务从 {usd_m(start)} "
                        f"{'升' if end > start else '降'}到 {usd_m(end)}。")
        charts.append(tracking_chart(
            f"股东回报 / 自由现金流（年初至今）：下季阈值 {pct_text(entry['threshold'])}，当前 {entry['current']:.0f}%",
            labels, [{"name": "年初至今回购 + 股息 ÷ 自由现金流", "values": cf["ytd_ratio"], "color": "NAVY"}],
            [(f"下季阈值 {pct_text(entry['threshold'])}（安全侧在下方）", entry["threshold"])],
            fmt="pct0", ylab="%（年初至今）",
            note=(f"阈值按本季分析的口径用年初至今（{ytd_words(period)}）；换成过去四季则是 {ttm:.0f}%"
                  + ("，在阈值之内 —— 这一条越没越线，取决于窗口怎么取。" if ttm is not None and ttm <= entry["threshold"]
                     else "。")
                  + net_debt
                  + "自由现金流不为正的年初至今（2017 年一季度付出 DOJ 和解款）不画比率。"),
            src_extra=aligned(staging, "quarterly_cash")["source"],
        ))
    return charts


def unit_value(unit: str, value: float) -> str:
    """A threshold or reading in the page's own money style (US$ prefix), not `board.unit_text`'s.

    A whole-percent figure prints as the company printed it (「9%」); a computed
    ratio keeps one decimal (「165.1%」) instead of every digit the float carries.
    """
    own = {"usd_m": usd_m,
           "pct": lambda v: pct_text(v) if float(v).is_integer() else f"{v:.1f}%",
           "usd_bn": lambda v: f"US${v:.1f}B"}
    return own[unit](value) if unit in own else unit_text(unit, value)


def guidance_vintage_table(staging: dict, guidance: dict | None, prior: dict | None) -> dict | None:
    """The open year's numeric guidance, this release against the one before, with widths.

    This used to be a bar chart in section three. It is not one of the quarter
    analysis's thresholds, so it moved to the audit drawer; the verbal lines
    (revenue, expenses, ARR) stay out of it for the same reason as everywhere.
    """
    if not guidance:
        return None
    g = staging["annual_guidance_history"]
    year = guidance["fiscal_year"]
    i = g["fiscal_years"].index(year)
    vintage = next(v for v in reversed(VINTAGES) if g["release_dates"][str(year)][v] == guidance["as_of"])
    before = VINTAGES[VINTAGES.index(vintage) - 1] if vintage != "Feb" else None
    rows = []
    keys = {"adj_diluted_eps_usd": "adj_eps", "gaap_diluted_eps_usd": "gaap_eps",
            "adj_operating_margin_pct": "adj_op_margin", "operating_margin_pct": "op_margin",
            "operating_cash_flow_usd_b": "ocf_usd_b", "free_cash_flow_usd_b": "fcf_usd_b"}
    for name, key, unit in WIDTH_ITEMS:
        lo, hi = guidance[key]
        fmt = (lambda v: f"{v:g}%") if unit == "%" else (lambda v: f"{v:.2f}")
        cell = lambda a, b: fmt(a) if a == b else f"{fmt(a)}–{fmt(b)}"
        old = ((g[f"{keys[key]}_lo"][before][i], g[f"{keys[key]}_hi"][before][i]) if before else None)
        rows.append([f"{name}（{unit}）", cell(*old) if old else "—", cell(lo, hi),
                     "NC" if old == (lo, hi) else "变动", f"{(hi - lo) / mid(lo, hi) * 100:.1f}%"])
    if guidance.get("share_repurchases_usd_b_upto") is not None:
        old = prior.get("buyback_guide_prior_usd_b") if prior else None
        rows.append(["回购（US$B）", f"约 {old:.1f}" if old else "—",
                     f"最多 {guidance['share_repurchases_usd_b_upto']:.1f}", "变动", "—"])
    return {
        "title": (f"FY{year} 全年指引的数字行："
                  + (f"{VINTAGE_MONTH[before]}版 → " if before else "")
                  + f"{VINTAGE_MONTH[vintage]}版（宽度 = 区间宽度占中值）"),
        "headers": ["指引项", f"{VINTAGE_MONTH[before]}版" if before else "上一版", f"{VINTAGE_MONTH[vintage]}版",
                    "变化", "宽度"],
        "rows": rows,
    }


# ── section four: the routine multi-period series ──────────────────────────
def routine(staging: dict, bridges: dict | None) -> list[dict]:
    ann = staging["annual_actuals"]
    seg = staging["segment_quarterly"]
    years = ann["fiscal_years"]
    ylabels = [f"FY{y}" for y in years]
    n_years = cn_count(len(years))

    margin = ann["operating_margin_pct"]
    low_all = years[margin.index(min(margin))]
    adjusted_from = next(y for y, v in zip(years, ann["adjusted_diluted_eps_usd"]) if v is not None)
    recent = [(y, m) for y, m in zip(years, margin) if y >= adjusted_from]
    low_recent = min(recent, key=lambda pair: pair[1])
    top = years[margin.index(max(margin))]

    low_words = (f"低点是 FY{low_all} 的 {min(margin):.1f}%"
                 + ((f"（{MARGIN_STORY[low_all]}）" if low_all in MARGIN_STORY else "")
                    + f"；FY{adjusted_from} 以来的低点是 FY{low_recent[0]} 的 {low_recent[1]:.1f}%"
                    + (f"，{MARGIN_STORY[low_recent[0]]}" if low_recent[0] in MARGIN_STORY else "")
                    if low_recent[0] != low_all else
                    (f"，{MARGIN_STORY[low_all]}" if low_all in MARGIN_STORY else "")))
    rev_margin = {
        "ref": "EX_ANN",
        "kind": "lines",
        "title": (
            f"{n_years}年收入从 US${ann['revenue_usd_m'][0]/1000:.1f}B 到 "
            f"US${ann['revenue_usd_m'][-1]/1000:.1f}B，营业利润率走完一轮 "
            f"{min(margin):.1f}% 到 {max(margin):.1f}%"
        ),
        "xlabels": ylabels,
        "series": [
            {"name": "营业利润率", "values": margin, "color": "NAVY"},
        ],
        "fmt": "pct1",
        "ylab": "%（GAAP 营业利润率）",
        "note": (
            "用 GAAP 营业利润率而不是调整后口径来画长序列，因为 GAAP 的定义"
            f"自 FY{adjusted_from} 起的{cn_count(len(recent))}年没动过"
            + (f"（更早的 FY{years[0]}–FY{adjusted_from - 1} 取当年 10-K 首次申报的值）"
               if years[0] < adjusted_from else "")
            + f"。{low_words}；"
            + (f"FY{years[-1]} 回到 {margin[-1]:.1f}%，仍低于 FY{top} 的 {max(margin):.1f}%。"
               if years[-1] != top else f"FY{years[-1]} 的 {margin[-1]:.1f}% 是窗口内最高。")
            + "把它和第一节 Exhibit {EX_INITIAL} 对着看："
            "利润率的这一轮起落，就是年初指引那几次大幅搬家的实物基础。"
        ),
        "src_extra": "XBRL companyfacts（us-gaap:OperatingIncomeLoss / 收入），口径为 10-K 申报值。",
    }

    gaap, adjusted = ann["diluted_eps_usd"], ann["adjusted_diluted_eps_usd"]
    gaps = [(y, a - g) for y, a, g in zip(years, adjusted, gaap) if a is not None]
    n_adjusted = len(gaps)
    negatives = ann.get("negative_adjustments_usd", {})
    neg_years = sorted(int(y) for y in negatives)
    largest = min(((int(y), name, value) for y, rows in negatives.items() for name, value in rows),
                  key=lambda row: row[2], default=None)
    fy_gap = ""
    if bridges:
        guided_gap = bridges["eps"]["adjusted"][0] - bridges["eps"]["gaap"][0]
        guided_neg = [(name, delta) for name, delta in bridges["eps"]["addbacks"] if delta < 0]
        year = int(bridges["period"][-4:])
        narrowest = guided_gap < min(gap for _, gap in gaps)
        if guided_neg:
            name, delta = min(guided_neg, key=lambda row: row[1])
            fy_gap = (f"<b>FY{year} 的指引里有一项 US${money(delta)} 的负加回</b> —— {name}；"
                      + (f"负加回此前也出现过，{cn_count(n_adjusted)}个有调整后口径的年度里有"
                         f"{cn_count(len(neg_years))}年，最大的是 FY{largest[0]} 的{largest[1]} "
                         f"−US${money(largest[2])}"
                         + (f"，这一次是它的{cn_count(int(abs(delta) / abs(largest[2])))}倍多" if abs(delta) >= 2 * abs(largest[2]) else "")
                         + "。" if largest else "")
                      + f"所以那一年的调整后指引与 GAAP 指引之间的缺口只有 US${guided_gap:.2f}"
                      + ("，是这条记录里最窄的一次。" if narrowest else "。"))
    eps_cmp = {
        "ref": "EX_EPS_ANN",
        "kind": "lines",
        "title": (f"{n_years}年 GAAP 与{cn_count(n_adjusted)}年调整后摊薄 EPS：两条线之间的缺口就是每年被加回的那些项"
                  if n_adjusted != len(years) else
                  f"{n_years}年 GAAP 与调整后摊薄 EPS：两条线之间的缺口就是每年被加回的那些项"),
        "xlabels": ylabels,
        "series": [
            {"name": "GAAP 摊薄 EPS", "values": gaap},
            {"name": "调整后摊薄 EPS", "values": adjusted, "color": "NAVY"},
        ],
        "fmt": "usd2",
        "ylab": "US$/股",
        "note": (
            ("调整后口径每年都高于 GAAP，" if all(gap > 0 for _, gap in gaps) else "")
            + f"缺口在 US${min(g for _, g in gaps):.2f}–{max(g for _, g in gaps):.2f} 之间，"
            + ("构成与本页 Exhibit {EX_BRIDGE} 那张桥列出的项目同类：摊销、重组、税务准备。"
               if bridges else "主要是摊销与重组。")
            + fy_gap
        ),
        "src_extra": "GAAP 取自 XBRL；调整后取自各年 2 月业绩新闻稿的全年结果。",
    }

    fcf = ann["free_cash_flow_usd_m"]
    fcf_low = years[fcf.index(min(fcf))]
    capex_share = [c / r * 100 for c, r in zip(ann["capex_usd_m"], ann["revenue_usd_m"])]
    top_share = years[capex_share.index(max(capex_share))]
    # The lowest cash year is explained by what happened in it, when this page
    # knows; the original sentence said issuance, which was true only while the
    # window started at FY2018.
    cash_story = (f"所以这两条线几乎平行 —— 穆迪的现金波动从来不来自资本开支：FY{fcf_low} 那个低点是"
                  f"{CASH_STORY[fcf_low]}"
                  + ("，FY2022 的回落跟着发行量走。" if fcf_low != 2022 and 2022 in years else "。")
                  if fcf_low in CASH_STORY and fcf_low != 2022 else
                  "所以这两条线几乎平行 —— 穆迪的现金问题从来不在资本开支上，而在发行量上。")
    cash = {
        "ref": "EX_CASH",
        "kind": "lines",
        "title": (
            f"{n_years}年经营现金流与自由现金流：FY{fcf_low} 的 US${min(fcf)/1000:.2f}B "
            f"是低点，FY{years[-1]} US${fcf[-1]/1000:.2f}B"
        ),
        "xlabels": ylabels,
        "series": [
            {"name": "经营现金流", "values": [v/1000 if v else None for v in ann["operating_cash_flow_usd_m"]]},
            {"name": "自由现金流（自算）", "values": [v/1000 if v else None for v in fcf],
             "color": "NAVY"},
        ],
        "fmt": "usd2",
        "ylab": "US$B",
        "note": (
            "自由现金流是经营现金流减去申报的资本开支，两条腿都是申报值，没有估计。"
            f"资本开支{n_years}年从 US${ann['capex_usd_m'][0]:,.0f}M 升到 US${ann['capex_usd_m'][-1]:,.0f}M，"
            + ("仍不到收入的 5%，" if max(capex_share) < 5 else
               f"最高也只占收入的 {max(capex_share):.1f}%（FY{top_share}），")
            + cash_story
        ),
        "src_extra": "XBRL companyfacts；自由现金流为经营现金流减资本开支的自算值，与公司自己的 FCF 定义一致。",
    }

    mis_oi = seg["mis_adj_operating_income_usd_m"]
    seg_oi = {
        "ref": "EX_SEG_OI",
        "kind": "lines",
        "title": f"{len(seg['periods'])} 季两块业务的调整后营业利润：评级那条的波动就是全年指引的波动",
        "xlabels": seg["periods"],
        "xstep": LONG_STEP,
        "series": [
            {"name": "MIS 调整后营业利润", "values": mis_oi},
            {"name": "MA 调整后营业利润", "values": seg["ma_adj_operating_income_usd_m"], "color": "NAVY"},
        ],
        "fmt": "usd0",
        "ylab": "US$M",
        "note": (
            f"MA 那条从 US${seg['ma_adj_operating_income_usd_m'][0]:,.0f}M 抬到 US$"
            f"{seg['ma_adj_operating_income_usd_m'][-1]:,.0f}M，窗口内峰值 US$"
            f"{max(seg['ma_adj_operating_income_usd_m']):,.0f}M；"
            f"MIS 那条在 US${min(mis_oi):,.0f}M 到 US$"
            f"{max(mis_oi):,.0f}M 之间走了一整轮。"
            "本季 MIS 调整后营业利润 US$"
            f"{mis_oi[-1]:,.0f}M"
            + ("，是 %d 季新高。" % len(seg['periods'])
               if mis_oi[-1] == max(mis_oi)
               else "，窗口内新高是 US$%s M。" % format(max(mis_oi), ',.0f'))
        ),
        "src_extra": "各期业绩 8-K EX-99.1 的分部表；分部调整后营业利润为公司披露值。",
    }
    return [rev_margin, eps_cmp, cash, seg_oi]


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    q = staging["segment_quarterly"]
    figures = stamped_block(staging, "quarter_figures", q["periods"][-1])
    return [f"Revenue ${q['revenue_usd_m'][-1] / 1000:.2f}B",
            f"MIS adj OpM {q['mis_adj_operating_margin_pct'][-1]:.1f}%",
            (f"调整后 EPS ${figures['adj_diluted_eps_usd']:.2f}" if figures else
             f"MA adj OpM {q['ma_adj_operating_margin_pct'][-1]:.1f}%")]


def build_payload(staging: dict) -> dict:
    seg = staging["segment_quarterly"]
    period = seg["periods"][-1]
    latest = latest_block(staging, period=period, period_end=seg["period_ends"][-1])
    release = release_source(staging)
    guidance = stamped_block(staging, "current_guidance", period)
    bridges = stamped_block(staging, "guidance_bridges", period)
    story = stamped_block(staging, "quarter_story", period)
    figures = stamped_block(staging, "quarter_figures", period)
    closure = stamped_block(staging, "followup_closure", period)
    prior = stamped_block(staging, "prior_kpi_settlement", period)
    next_kpi = stamped_block(staging, "next_kpi", period)
    previous = seg["periods"][-2]
    for key, block in (("followup_closure", closure), ("prior_kpi_settlement", prior)):
        if block and block["set_in"] != previous:
            raise ValueError(f"series block `{key}` settles what {block['set_in']!r} set, "
                             f"but the quarter before {period!r} is {previous!r}")
    if next_kpi and next_kpi["for_period"] != following(period):
        raise ValueError(f"series block `next_kpi` is written for {next_kpi['for_period']!r}, "
                         f"but the quarter after {period!r} is {following(period)!r}")
    cash = aligned(staging, "quarterly_cash")
    kpi_now = aligned(staging, "ma_kpi_quarterly")

    facts = record_facts(staging)
    sf = segment_facts(staging)
    ma_yoy = pct_change(seg["ma_revenue_usd_m"][-1], seg["ma_revenue_usd_m"][-5])
    mis = seg["mis_revenue_usd_m"]
    buybacks = cash["share_repurchases_usd_m"]
    values = {
        "ma_yoy": f"{ma_yoy:+.0f}%",
        "mis_yoy": signed(pct_change(mis[-1], mis[-5])),
        "mis_yoy_prev": signed(pct_change(mis[-2], mis[-6])),
        "buyback_now": usd_m(buybacks[-1]),
        "buyback_prev": usd_m(buybacks[-2]),
    }
    if prior:
        top = max((entry for entry in prior["quantified"] if entry.get("series") == "share_repurchases"),
                  key=lambda entry: entry["threshold"], default=None)
        if top:
            values["buyback_threshold"] = usd_m(top["threshold"])
        if prior.get("buyback_guide_prior_usd_b") is not None:
            values["buyback_guide_prior"] = f"US${prior['buyback_guide_prior_usd_b']:.1f}B"
            # What last quarter's full-year figure left for the rest of the year
            # once that quarter's buyback was spent -- the arithmetic the analysis
            # used to retire the single-quarter threshold.
            values["buyback_room"] = usd_m(prior["buyback_guide_prior_usd_b"] * 1000 - buybacks[-2])
    if bridges:
        negative = [delta for _, delta in bridges["eps"]["addbacks"] if delta < 0]
        if negative:
            values["gain"] = money(min(negative))

    settled_ex = ([closure_chart(closure, values)] if closure else [])
    settled_ex += prior_settlement(staging, prior, figures, guidance, values) if prior else []
    settled_ex += guidance_record(staging, facts)
    settled_ex += guidance_bridge(guidance, bridges, latest["release_date"])
    highlight_ex = quarter_highlights(staging, figures, guidance, bridges, story, prior, values)
    next_ex = next_watch(staging, next_kpi, guidance, story, figures, values)
    annual_and_segment = routine(staging, bridges)
    routine_ex = (annual_and_segment[:3] + segment_long_charts(staging, facts, sf, story, values)
                  + annual_and_segment[3:])

    all_ex = number_exhibits(settled_ex + highlight_ex + next_ex + routine_ex, start=1)
    resolve_exhibit_refs(all_ex)
    a, b, c = len(settled_ex), len(highlight_ex), len(next_ex)
    settled_ex, highlight_ex = all_ex[:a], all_ex[a:a + b]
    next_ex, routine_ex = all_ex[a + b:a + b + c], all_ex[a + b + c:]

    ann = staging["annual_actuals"]
    g = staging["annual_guidance_history"]
    first_table = len(all_ex) + 1

    years = g["fiscal_years"]
    rows_guidance = []
    for i, y in enumerate(years):
        def cell(v):
            lo, hi = g["adj_eps_lo"][v][i], g["adj_eps_hi"][v][i]
            return "—" if lo is None else f"{lo:.2f}–{hi:.2f}"
        act = g["actual_adj_eps_usd"][i]
        rows_guidance.append([f"FY{y}", cell("Feb"), cell("Apr"), cell("Jul"), cell("Oct"),
                              "—" if act is None else f"{act:.2f}"])

    settlement_tables = []
    if closure:
        settlement_tables.append({
            "title": f"上季 {len(closure['items'])} 条待验证问题的逐条判定（本季分析第 0 节）",
            "headers": ["#", "上季问题", "本季判定", "说明"],
            "rows": [[str(i), item["question"], item["verdict"], item["follow"]]
                     for i, item in enumerate(closure["items"], start=1)],
        })
    if prior:
        settled_entries = prior_entries(staging, prior)
        settlement_tables.append({
            "title": f"上季（{prior['set_in']}）量化阈值与本季实际值（上季分析的关键观察指标）",
            "headers": ["指标", "触发条件（原文）", "动作", "阈值", "本季实际", "余量 D"],
            "rows": [[entry["metric"], entry["condition"], entry["action"],
                      unit_value(entry["unit"], entry["threshold"]), unit_value(entry["unit"], entry["actual"]),
                      f"{headroom(entry['direction'], entry['threshold'], entry['actual']):+.1f}%"]
                     for entry in settled_entries],
        })
        settlement_tables.append({
            "title": f"上季 {len(prior['dispositions'])} 行关键观察指标：本季分析给出的处置",
            "headers": ["上季指标（原文）", "处置"],
            "rows": [list(row) for row in prior["dispositions"]],
        })
        if prior.get("unquantified"):
            settlement_tables.append({
                "title": "上季指标里无法按数字结算的几条",
                "headers": ["#", "原因"],
                "rows": [[str(i), text] for i, text in enumerate(prior["unquantified"], start=1)],
            })
    if next_kpi:
        entries = next_entries(staging, next_kpi)
        settlement_tables.append({
            "title": f"下季（{next_kpi['for_period']}）量化阈值与当前值（本季分析第 8 节）",
            "headers": ["指标", "触发条件（原文）", "动作", "阈值", "当前值", "余量 D"],
            "rows": [[entry["metric"], entry["condition"], entry["action"],
                      unit_value(entry["unit"], entry["threshold"]), unit_value(entry["unit"], entry["current"]),
                      f"{headroom(entry['direction'], entry['threshold'], entry['current']):+.1f}%"]
                     for entry in entries],
        })
        if next_kpi.get("disclosure_gated"):
            settlement_tables.append({
                "title": "下季指标里无法按数字跟踪的几条",
                "headers": ["#", "内容与原因"],
                "rows": [[str(i), text] for i, text in enumerate(next_kpi["disclosure_gated"], start=1)],
            })
        if next_kpi.get("followups"):
            settlement_tables.append({
                "title": f"下季待验证问题（本季分析末节 {len(next_kpi['followups'])} 条，{next_kpi['for_period']} 那一期结算）",
                "headers": ["#", "问题", "为什么重要"],
                "rows": [[str(i), question, why] for i, (question, why) in enumerate(next_kpi["followups"], start=1)],
            })
    vintage_table = guidance_vintage_table(staging, guidance, prior)
    if vintage_table:
        settlement_tables.append(vintage_table)
    for offset, table in enumerate(settlement_tables):
        table["n"] = first_table + offset
    first_table += len(settlement_tables)

    tables = settlement_tables + [
        {
            "n": first_table,
            "title": f"FY{years[0]}–FY{years[-1]} 全年调整后摊薄 EPS 指引的四个版本与实际（US$/股）",
            "headers": ["财年", "2 月（定调）", "4 月", "7 月", "10 月（末次）", "全年实际"],
            "rows": rows_guidance,
        },
        {
            "n": first_table + 1,
            "title": f"近 {len(seg['periods'])} 季分部外部收入、调整后营业利润与利润率",
            "headers": ["季度", "MIS 收入", "MA 收入", "合并收入", "MIS 调整后营业利润",
                        "MA 调整后营业利润", "MIS 利润率", "MA 利润率"],
            "rows": [[seg["periods"][i],
                      f"{seg['mis_revenue_usd_m'][i]:,.0f}", f"{seg['ma_revenue_usd_m'][i]:,.0f}",
                      f"{seg['revenue_usd_m'][i]:,.0f}",
                      f"{seg['mis_adj_operating_income_usd_m'][i]:,.0f}",
                      f"{seg['ma_adj_operating_income_usd_m'][i]:,.0f}",
                      f"{seg['mis_adj_operating_margin_pct'][i]:.1f}%",
                      f"{seg['ma_adj_operating_margin_pct'][i]:.1f}%"]
                     for i in range(len(seg["periods"]))],
        },
        {
            "n": first_table + 2,
            "title": f"FY{ann['fiscal_years'][0]}–FY{ann['fiscal_years'][-1]} 年度实际",
            "headers": ["财年", "收入 US$M", "营业利润 US$M", "营业利润率", "GAAP EPS",
                        "调整后 EPS", "经营现金流 US$M", "资本开支 US$M", "自由现金流 US$M"],
            "rows": [[f"FY{y}",
                      f"{ann['revenue_usd_m'][i]:,.0f}", f"{ann['operating_income_usd_m'][i]:,.0f}",
                      f"{ann['operating_margin_pct'][i]:.1f}%",
                      f"{ann['diluted_eps_usd'][i]:.2f}",
                      ("—" if ann["adjusted_diluted_eps_usd"][i] is None
                       else f"{ann['adjusted_diluted_eps_usd'][i]:.2f}"),
                      f"{ann['operating_cash_flow_usd_m'][i]:,.0f}", f"{ann['capex_usd_m'][i]:,.0f}",
                      f"{ann['free_cash_flow_usd_m'][i]:,.0f}"]
                     for i, y in enumerate(ann["fiscal_years"])],
        },
        ai_capex_cycle_table(first_table + 3),
    ]

    n_done = len(facts["finished"])
    worst_cut = min(facts["path"], key=facts["path"].get)
    final_below, initial_inside = facts["final_below"], facts["initial_inside"]
    audit_words = {"unaudited": "未审计", "audited": "已审计"}[latest["audit_status"]]
    record_title = (
        ("末次指引跌破过" + cn_count(len(final_below)) + "次" if final_below else "末次指引从没跌破过")
        + "，"
        + ("初始指引一次都没对过" if not initial_inside else
           f"初始指引对过{cn_count(len(initial_inside))}次"))
    d_rev = seg["revenue_usd_m"][-1] - seg["revenue_usd_m"][-2]
    d_aoi = seg["adj_operating_income_usd_m"][-1] - seg["adj_operating_income_usd_m"][-2]
    mis_margin = seg["mis_adj_operating_margin_pct"]
    cf = cash_facts(staging)
    span = ytd_words(period)
    ratio = cf["ytd_returns"] / cf["ytd_fcf"] * 100
    articles = [
        '<article><span>本季</span><b>'
        + ("环比增量几乎全额落到利润" if d_rev > 0 and d_aoi / d_rev >= 0.9 else "收入与利润的环比变化")
        + '</b>'
        f'<p>环比收入 {"+" if d_rev >= 0 else "−"}{usd_m(abs(d_rev))}、调整后营业利润 '
        f'{"+" if d_aoi >= 0 else "−"}{usd_m(abs(d_aoi))}；MIS 同比 {values["mis_yoy"]}、'
        f'调整后营业利润率 {mis_margin[-1]:.1f}%'
        + (f'（{len(seg["periods"])} 季最高）' if mis_margin[-1] == max(mis_margin) else '')
        + '。</p></article>',
    ]
    if guidance:
        g_hist = staging["annual_guidance_history"]
        year = str(guidance["fiscal_year"])
        vintage = next(v for v in reversed(VINTAGES) if g_hist["release_dates"][year][v] == guidance["as_of"])
        i_year = g_hist["fiscal_years"].index(guidance["fiscal_year"])
        before = VINTAGES[VINTAGES.index(vintage) - 1] if vintage != "Feb" else None
        eps_lo, eps_hi = guidance["adj_diluted_eps_usd"]
        fcf_lo, fcf_hi = guidance["free_cash_flow_usd_b"]
        changes = f'全年调整后 EPS 指引 US${eps_lo:.2f}–{eps_hi:.2f}'
        if before:
            b_lo, b_hi = g_hist["adj_eps_lo"][before][i_year], g_hist["adj_eps_hi"][before][i_year]
            f_lo = g_hist["fcf_usd_b_lo"][before][i_year]
            changes += (f'（{VINTAGE_MONTH[before]}版 US${b_lo:.2f}–{b_hi:.2f}）'
                        + f'，自由现金流指引 US${fcf_lo:.1f}–{fcf_hi:.1f}B（{VINTAGE_MONTH[before]}版下限 US${f_lo:.1f}B）')
        changes += (f'，回购最多 US${guidance["share_repurchases_usd_b_upto"]:.1f}B'
                    if guidance.get("share_repurchases_usd_b_upto") else '')
        articles.append(
            '<article><span>资本</span><b>'
            + ("回购超过了内生现金" if ratio > 100 else "股东回报在自由现金流之内")
            + '</b>'
            f'<p>{span}回购加股息 {usd_m(cf["ytd_returns"])}，是同期自由现金流的 {ratio:.0f}%。{changes}。</p></article>')
    if closure:
        labels_c, counts_c = closure_counts(closure)
        tally = dict(zip(labels_c, counts_c))
        prior_line = ""
        if prior:
            settled = prior_entries(staging, prior)
            held = sum(1 for entry in settled if headroom(entry["direction"], entry["threshold"], entry["actual"]) >= 0)
            prior_line = f'上季 {len(settled)} 条量化阈值 {held} 条守住。'
        verified = tally.get("已验证", 0)
        articles.append(
            '<article><span>上季</span><b>'
            + (f'{len(closure["items"])} 条问题完全验证的只有{cn_count(verified)}条' if verified else
               f'{len(closure["items"])} 条问题没有一条完全验证')
            + '</b>'
            '<p>' + '、'.join(f'{label} {count}' for label, count in zip(labels_c, counts_c)) + '。'
            + prior_line + '</p></article>')
    articles.append(
        f'<article><span>记录</span><b>{record_title}</b>'
        f'<p>{n_done} 个已完结年度：对 10 月那版下限 '
        f'{len(final_below)} 次跌破；'
        f'对 2 月那版 {len(initial_inside)} 次落在区间内。'
        f'FY{worst_cut} 中值从 2 月到 10 月被砍了 {abs(facts["path"][worst_cut]):.0f}%。</p></article>')

    seg_rev = seg["revenue_usd_m"]
    notes = [
        "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
        "穆迪为自然年财年（12 月 31 日结束），本页季度标注与公司口径一致，无需换算。",
        "本页最需要说明的一条：穆迪的业绩 8-K 里<b>只有全年指引表</b>，并在当年逐季修订；下一季度的数字"
        "只在个别电话会上口头给过（例如 2025 年 2 月那场给 Q1、2026 年 4 月那场给 Q2 的调整后 EPS 区间），"
        "业绩 8-K 里没有，本页不发布也不结算。本页此前写的是「从不给下一季度的数字指引」，那是错的。"
        "因此第一节后半结算的对象是财年而不是季度；末次指引落笔时全年已经过了四分之三，"
        "所以「跌破得少」这件事本身的份量，远小于同一句话出现在按季度指引的公司身上。"
        + ("另外，本页此前把 FY2018 排除在记录之外、理由写的是「只有十月一个 vintage」，"
           f"那句话是错的（四版齐全），而那一年正是{cn_count(n_done)}年里唯一跌破末次指引下限的一年。"
           if final_below == [2018] else "")
        + "本页用两张图（对初始指引、对末次指引）并排把这件事讲清楚，而不是只报一个命中率。",
        "指引表里的收入类各行（MCO/MIS/MA 收入、费用、ARR）公司<b>只给文字口径</b>，"
        "例如「increase in the high-single-digit percent range」。"
        "文字不是数字区间，本页不把它换算成端点，因此这几行没有兑现图，也不进任何一张带子。",
        "2021-08-05 另有一次非季度节奏的指引更新（在 7 月 28 日那期之后），"
        "该次调整后 EPS 指引与 7 月那版相同，本页按季度节奏取数，未单列该期。",
        "分部数据的列先后顺序在 2023 年 4 月那期之后由「MIS 在前」改为「MA 在前」。"
        "本页按表头里的分部名取值而不是按列位，重叠季度在两份来源之间逐项一致。",
        "分部调整后营业利润率的分母是<b>分部总收入</b>（外部收入加分部间收入），"
        "而本页图上画的分部收入是<b>外部收入</b>口径。两者差的就是分部间计费："
        f"MIS 每季向 MA 内部计费 US${min(sf['mis_internal']):,.0f}–{max(sf['mis_internal']):,.0f}M，"
        f"MA 向 MIS US${min(sf['ma_internal']):,.0f}–{max(sf['ma_internal']):,.0f}M。"
        f"用外部收入去除调整后营业利润会把 MIS 的利润率高估 {overstated_words(sf)}；"
        f"按总收入复算，{len(seg['periods'])} 个季度与公司自己印出来的百分比"
        f"最大只差 {sf['margin_slack']:.2f}pp，"
        f"那 {sf['margin_slack']:.2f}pp 是公司把百分比四舍五入到一位小数留下的余数。",
    ]
    if story and story.get("divestitures"):
        notes.append(fill_story(story["divestitures"], values))
    prior_n = next((ex["n"] for ex in settled_ex
                    if ex["kind"] == "diverging_bars" and ex["title"].startswith("上季")), None)
    next_n = next((ex["n"] for ex in next_ex
                   if ex["kind"] == "diverging_bars" and ex["title"].startswith("下季")), None)
    if prior_n and next_n:
        notes.append(f"Exhibit {prior_n} 与 Exhibit {next_n} 的阈值是本站季报分析设定的，不是公司指引："
                     "数值与方向逐字取自上季与本季分析的「关键观察指标」，实际值与当前值一律从申报现算；"
                     "公司只印整数的增速（ARR、有机增速），按公司印的整数结算，由它自己印的金额算出的精确值写在图注里。")
    notes += [
        "核对表的取数来源：全年指引四栏的每一格是该期业绩 8-K EX-99.1 指引表里的当期值，"
        "全年实际取次年 2 月那期的全年结果；分部表为外部收入口径（不含分部间收入）；"
        "年度表的 GAAP 各列取自 XBRL companyfacts，调整后 EPS 取自各年 2 月业绩新闻稿。",
        "自由现金流为经营现金流减申报资本开支的自算值，与公司自己的定义一致；标 D 的项均为此类透明自算。",
        "本页不发布评级、目标价、估值与任何券商共识，也不发布公司未在申报文件中给出的数字。",
    ]
    return {
        "schema_version": "quarterly-dashboard/mco-v1",
        "page": {"slug": "mco", "language": "zh-CN"},
        "company": {
            "ticker": "MCO",
            "name": "Moody's Corporation",
            "group": "financial_data_indices",
            "accounting_standard": "US GAAP",
        },
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · MCO",
        "title": f"Moody's Corporation (MCO)：{period} 季报仪表盘",
        "subtitle": (
            f"截至 {latest['period_end']} · 发布 {latest['release_date']} · US GAAP · {audit_words} · "
            "自然年财年，季度标注无需换算"
        ),
        # `assets/page.js` sets this with textContent, so it is a plain-text
        # slot: any markup here reaches the reader as literal characters.
        "headline": plain_text(
            f"收入 US${seg_rev[-1]:,.0f}M、同比 "
            f"{signed(pct_change(seg_rev[-1], seg_rev[-5]))}：MIS {values['mis_yoy']}、"
            f"MA {signed(ma_yoy)}（有机固定汇率 {kpi_now['organic_cc_revenue_growth_pct'][-1]:+.0f}%）；"
            + (f"环比多出的 {usd_m(d_rev)} 收入里 {usd_m(d_aoi)} 落成调整后营业利润，" if d_rev > 0 else "")
            + f"调整后营业利润率 {seg['adj_operating_margin_pct'][-1]:.1f}%。"
            f"{span}回购加股息是自由现金流的 {ratio:.0f}%。"
            "穆迪的业绩 8-K 只给全年指引并逐季修订："
            f"{n_done} 个已完结年度里，实际值相对末次（10 月）指引"
            f"高于上限 {len(facts['final_above'])} 次、落在区间内 {len(facts['final_inside'])} 次、"
            f"跌破下限 {len(final_below)} 次；"
            f"相对初始（2 月）指引却是高于 {len(facts['initial_above'])} 次、"
            f"跌破 {len(facts['initial_below'])} 次、"
            + ("一次都没落在区间内。" if not initial_inside else f"落在区间内 {len(initial_inside)} 次。")
            + "同一个数字，差别只在画线时离年末还有多远。"
        ),
        "brief": (
            f'<h4>本季{cn_count(len(articles))}条主线</h4><div class="takeaway-grid">'
            + "".join(articles)
            + '</div>'
        ),
        "source": (
            f'Source: <a href="{release["url"]}" rel="noopener">Moody\'s {period} '
            f'业绩新闻稿（8-K EX-99.1）</a>{periodic_report_words(staging)}。'
        ),
        "source_url": release["url"],
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {
                "id": "settled",
                "title": "一、上季跟踪指标兑现了吗",
                "description": plain_text(
                    (f"先结算上季（{closure['set_in']}）本站季报分析留下的 {len(closure['items'])} 条待验证问题"
                     if closure else "")
                    + (f"与 {len(prior['dispositions'])} 行关键观察指标" if prior else "")
                    + ("，再看公司自己的指引记录。" if closure or prior else "本季没有上季留下的问题与阈值要结算，只看公司自己的指引记录。")
                    + "穆迪的业绩 8-K 只印全年指引表，在当年后三期各更新一次；下一季度的数字只在个别电话会上"
                    "口头出现过，业绩 8-K 里没有，本页不结算。所以后半节结算的是「年」而不是「季」，"
                    "真正的变量是画线时离年末还有多远。"
                ),
                "exhibits": settled_ex,
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": plain_text(
                    "本季分析第 1、2、3、7 节里能用一手数据画的结论，一图一个"
                    + (("：" + told(story, "highlights_scope", values) + "。")
                       if story and story.get("highlights_scope") else "。")
                    + told(story, "highlights_not_drawn", values)
                ),
                "exhibits": highlight_ex,
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": plain_text(
                    (f"本季分析第 8 节「关键观察指标」拆成 {len(next_entries(staging, next_kpi))} 条可量化阈值"
                     "（一行里的警示线与加速线各算一条），阈值与方向逐字取自报告，当前值是"
                     f" {period} 的申报读数。"
                     + ("无法按数字跟踪的：" + "；".join(text.split("：")[0] for text in next_kpi["disclosure_gated"])
                        + "，原因写在核对表里。" if next_kpi.get("disclosure_gated") else "")
                     + (f"报告末节的 {len(next_kpi['followups'])} 条下季待验证问题也收在核对表里，"
                        f"{next_kpi['for_period']} 那一期结算。" if next_kpi.get("followups") else "")
                     if next_kpi else "本季分析没有留下下季阈值，本节没有图。")
                ),
                "exhibits": next_ex,
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": plain_text(
                    f"MCO 专属的常规序列：{cn_count(len(ann['fiscal_years']))}年营业利润率的一轮起落、"
                    "GAAP 与调整后 EPS 之间那道逐年变化的缺口、现金流的两条腿，"
                    f"以及 {len(seg['periods'])} 季里两块业务各自的收入、利润占比、利润率与调整后营业利润。"
                ),
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": [plain_text(p) for p in notes],
        "footer": "Quarterly Results · 公司披露值与透明自算 · 仅供研究",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "mco.js"), payload, "mco")
    shell_dir = ROOT / "mco"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("MCO", "mco"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(
        f"MCO page: {charts} charts in {len(payload['sections'])} sections "
        f"+ {len(payload['tables'])} audit tables"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
