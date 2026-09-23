"""MSCI Inc. quarterly dashboard.

MSCI is the first company on this site whose published guidance is **annual and
cost-side only**. Its "Full-Year Guidance" -- in every earnings 8-K EX-99.1, as a
paragraph plus the Outlook column of Tables 11/12 until the Q3 2020 release and
as a table since -- guides total operating expense, adjusted EBITDA expense,
interest expense, D&A, the effective tax rate, capital expenditures, operating
cash flow and free cash flow. It never guides revenue and it never guides EPS.
So the company-guidance part of the first section settles a *cost and cash*
record over the finished fiscal years rather than a revenue record over
quarters, and the page says why. Before it, the first section settles what the
previous quarter's local analysis left open: its follow-up questions, as the
current analysis's section 0 closed them (``followup_closure``), and its
quantified thresholds, against this quarter's filed figures
(``prior_kpi_settlement``) -- both stamped with the quarter.

The finding that record produces is two-sided and only visible because the same
table carries both legs: measured against the LAST guidance of each year,
operating expense lands inside its range far more often than against the FIRST
guidance of the same year, so the accuracy is a product of revision; free cash
flow beats the top of the range about as often on either vintage, so revising it
does not close the gap. Every count in those sentences is recounted from the
record on each build -- they were typed once, as 6/6, 3/6 and 4/6, and stayed
typed after the record was extended back to FY2015.

The page is rolled by editing ``series/msci.json`` alone. What only one quarter
has -- the next-quarter thresholds, and what that quarter's release said about
the guidance beyond the five ranges the record carries -- sits in blocks stamped
with the quarter (``board.stamped_block``); ``_checks`` is a separate reading of
the quarter's release that the tests hold the page to and this builder never
reads.

Published numbers are company-reported or transparent arithmetic. No market
expectation is published on this page: no dated, checkable public source for one
was available, and inventing one is worse than omitting the comparison.
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
    cn_count,
    cn_ordinal,
    delivery_band,
    display_period,
    fill_story,
    headroom,
    headroom_exhibit,
    latest_block,
    number_exhibits,
    stamped_block,
    threshold_exhibit,
    unit_text,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "msci.json"
DATA_DIR = ROOT / "data"

# One tick per year keeps the forty-odd-quarter axes readable.
LONG_STEP = 4

# The tolerance the identities below are checked to: the older quarters are
# read in thousands and the newer in tenths of a million, so a sum can miss by
# a rounding step without anything being wrong.
TOLERANCE = 0.15

# The five guided lines the annual record carries, in the order the revision
# chart draws them.
GUIDED = [("operating_expense", "营业费用"),
          ("adj_ebitda_expense", "调整后 EBITDA 费用"),
          ("op_cash_flow", "经营现金流"),
          ("capex", "资本开支"),
          ("free_cash_flow", "自由现金流")]

SEGMENTS = [("index", "Index"), ("analytics", "Analytics"),
            ("sustainability_climate", "Sustainability & Climate"),
            ("private_assets", "All Other – Private Assets")]

# The long series that start after the long axis does, named for the note that
# says so; the start is read off the series.
LATE_SERIES = [
    ("Sustainability and Climate 的留存率与净新增", "retention_rate_sustainability_pct"),
    ("All Other – Private Assets 的留存率", "retention_rate_private_assets_pct"),
    ("All Other – Private Assets 的有机收入增速", "organic_revenue_growth_private_assets_pct"),
    ("Analytics 的有机 Run Rate 增速", "organic_run_rate_growth_analytics_pct"),
]

# A basis-point fee is a level, not a change: the shared `bps` formatter prints
# a signed "+2bp" and `times` printed the fee as "2.28x".
LOCAL_UNITS = {"bp": lambda value: f"{value:.2f}bp",
               # Net new sales run in tens of millions and the release prints a
               # tenth: the shared `usd_m` rounds US$47.5M to "$48M".
               "usd_m1": lambda value: f"{'−' if value < 0 else ''}US${abs(value):,.1f}M"}


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100.0


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def rounded(values, digits: int = 6):
    return [None if v is None else round(v, digits) for v in values]


def mid(low, high):
    return [(a + b) / 2 for a, b in zip(low, high)]


def joined(names: list[str]) -> str:
    """``['A', 'B', 'C']`` → ``'A、B与C'``."""
    if len(names) < 2:
        return "".join(names)
    return "、".join(names[:-1]) + "与" + names[-1]


def quarter_words(label: str) -> str:
    """``'Q2 2026'`` → ``'2026 年第二季度'``."""
    quarter, year = display_period(label).split()
    return f"{year} 年第{cn_ordinal(int(quarter[1]))}季度"


def previous_label(label: str) -> str:
    """``'Q1 2026'`` → ``'Q4 2025'``."""
    quarter, year = display_period(label).split()
    number = int(quarter[1])
    return f"Q4 {int(year) - 1}" if number == 1 else f"Q{number - 1} {year}"


def quarter_values(staging: dict) -> dict[str, str]:
    """The numbers the quarter's own story blocks name, computed from the series.

    A sentence in a stamped block (``followup_closure``, ``prior_kpi_settlement``)
    names these as ``{placeholders}`` rather than typing them, so the story and the
    arrays cannot disagree (``board.fill_story``).
    """
    fin, om, seg = staging["financials"], staging["operating_metrics"], staging["segments_usd_m"]
    aum, market, inflow = om["aum_period_end_usd_b"], om["etf_market_appreciation_usd_b"], om["etf_cash_inflows_usd_b"]
    yoy = net_new_yoy(om)
    pa_margin = seg["private_assets"]["adj_ebitda_margin_pct"]
    # Table 7 prints the quarter's change as market appreciation plus cash
    # inflows, so the market's share is read from the same two cells.
    growth = market[-1] + inflow[-1]
    values = {
        "net_new": f"US${om['net_new_recurring_sales_usd_m'][-1]:.1f}M",
        "net_new_yoy": signed(yoy[-1]),
        "net_new_yoy_prev": signed(yoy[-2]),
        "pa_organic": f"{om['organic_revenue_growth_private_assets_pct'][-1]:.1f}%",
        "pa_margin": f"{pa_margin[-1]:.1f}%",
        "pa_margin_prev": f"{pa_margin[-2]:.1f}%",
        "pa_margin_yago": f"{pa_margin[-5]:.1f}%",
        "aum": f"US${aum[-1]:,.0f}B",
        "aum_prev": f"US${aum[-2]:,.0f}B",
        # The share of the quarter's AUM increase that the market supplied; it
        # has a meaning only when AUM grew.
        "market_share": f"{market[-1] / growth * 100:.1f}%" if growth > 0 else "—",
        "inflow": f"US${inflow[-1]:,.0f}B",
        "inflow_prev": f"US${inflow[-2]:,.0f}B",
        "fee": f"{om['aum_basis_point_fee'][-1]:.2f}bp",
        "fee_prev": f"{om['aum_basis_point_fee'][-2]:.2f}bp",
        "analytics_growth": signed(om["revenue_growth_analytics_pct"][-1]),
        "eps": f"US${fin['diluted_eps_usd'][-1]:.2f}",
        "eps_prev": f"US${fin['diluted_eps_usd'][-2]:.2f}",
        "adj_eps": f"US${fin['adjusted_eps_usd'][-1]:.2f}",
        "adj_eps_prev": f"US${fin['adjusted_eps_usd'][-2]:.2f}",
        "retention": f"{om['retention_rate_pct'][-1]:.1f}%",
        "retention_prev": f"{om['retention_rate_pct'][-2]:.1f}%",
        "sc_retention": f"{om['retention_rate_sustainability_pct'][-1]:.1f}%",
        "sc_retention_prev": f"{om['retention_rate_sustainability_pct'][-2]:.1f}%",
    }
    return values


def month_words(date: str) -> str:
    return f"{int(date[5:7])} 月"


def joined_months(dates: list[str]) -> str:
    """``['2026-01-28', '2026-04-21']`` → ``'1 月与 4 月'`` (a digit after 与 takes a space)."""
    words = [month_words(d) for d in dates]
    return words[0] if len(words) < 2 else "、".join(words[:-1]) + "与 " + words[-1]


def unit_words(unit: str, value: float) -> str:
    return LOCAL_UNITS[unit](value) if unit in LOCAL_UNITS else unit_text(unit, value)


def resolve_exhibit_refs(exhibits: list[dict]) -> list[dict]:
    """Replace ``{EX_NAME}`` placeholders with the numbers assigned at render.

    Exhibits are numbered in render order by ``board.number_exhibits``, so a
    caption cannot name its neighbour until after numbering.
    """
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


def release_source(staging: dict) -> dict:
    """This quarter's own release in `sources`, found by its label."""
    label = f"MSCI {quarter_words(staging['period_labels'][-1])}业绩新闻稿"
    found = next((item for item in staging["sources"] if item["label"].startswith(label)), None)
    if found is None:
        raise ValueError(f"series `sources` has no entry for the {label}: add this "
                         "quarter's release with the roll")
    return found


def periodic_report_words(staging: dict) -> str:
    """「与截至 … 的 10-Q」 when `sources` carries the quarter's own 10-Q / 10-K."""
    end = staging["period_ends"][-1]
    quarter, year = display_period(staging["period_labels"][-1]).split()
    for form, label in (("10-Q", f"MSCI 截至 {end} 的 10-Q"),
                        ("10-K", f"MSCI {year} 年度 10-K")):
        if any(item["label"].startswith(label) for item in staging["sources"]):
            return f"与截至 {end} 的 {form}"
    return ""


def path_values(staging: dict, path: str) -> list:
    block = staging
    for part in path.split("."):
        block = block[part]
    return block


def net_new_yoy(om: dict) -> list[float | None]:
    """Net new recurring subscription sales, year on year, on the long axis.

    The company printed this growth rate only from the Q3 2024 release on, and
    where it printed one the page uses it: the two 2026 releases compute theirs
    against a slightly restated year-ago quarter, so the ratio of the two levels
    this file keeps (each from its own release) reads 52.0% / 8.3% where the
    company printed 51.7% / 8.4%. Before Q3 2024 there is no printed rate and the
    thousand-dollar levels give it to the printed precision. The first four
    quarters have no base in this record and stay empty.
    """
    levels, printed = om["net_new_recurring_sales_usd_m"], om["net_new_recurring_sales_yoy_printed_pct"]
    out: list[float | None] = []
    for index, level in enumerate(levels):
        if printed[index] is not None:
            out.append(printed[index])
        elif index >= 4 and level is not None and levels[index - 4]:
            out.append(pct_change(level, levels[index - 4]))
        else:
            out.append(None)
    return out


def open_guidance(staging: dict, key: str) -> tuple[float, float]:
    """The open year's latest guided range for one line, in US$M."""
    hist = staging["annual_guidance_history"]
    guided = [g for g in hist["items"][key]["by_year"][str(max(hist["years"]))]["guided"] if g]
    return guided[-1][0], guided[-1][1]


def kpi_series(staging: dict, reads: str) -> list:
    """The whole series a threshold is read from, on the axis it is stored on."""
    if reads == "net_new_yoy":
        return net_new_yoy(staging["operating_metrics"])
    if reads.startswith("yoy:"):
        values = path_values(staging, reads[4:])
        return [None] * 4 + [pct_change(values[i], values[i - 4]) for i in range(4, len(values))]
    return path_values(staging, reads)


def kpi_reading(staging: dict, reads: str) -> float:
    """The current value of a threshold, read from the series it names.

    ``guide_mid:<line>`` / ``guide_high:<line>`` read the open year's latest
    guided range instead: a threshold on the guidance is a threshold on the
    next release's table, not on a quarterly series.
    """
    if reads.startswith(("guide_mid:", "guide_high:")):
        kind, key = reads.split(":")
        low, high = open_guidance(staging, key)
        return (low + high) / 2 if kind == "guide_mid" else high
    return kpi_series(staging, reads)[-1]


def settle(staging: dict, entries: list[dict], key: str) -> list[dict]:
    """Attach each threshold's value: read from the series it names, or -- for a
    figure no filing carries, such as a region's sales on the earnings slides --
    typed into the stamped block with the place it was read."""
    out = []
    for entry in entries:
        typed = entry.get("actual", entry.get("current"))
        if ("reads" in entry) == (typed is not None):
            raise ValueError(f"threshold `{entry.get('id', entry['metric'])}` needs exactly one of "
                             "`reads` or a typed value")
        if typed is not None and not entry.get("actual_source"):
            raise ValueError(f"threshold `{entry.get('id', entry['metric'])}` is typed without its source")
        out.append({**entry, key: kpi_reading(staging, entry["reads"]) if "reads" in entry else typed})
    return out


# How each settled series is drawn: name, chart format, axis label.
SETTLED_SERIES = {
    "net_new_yoy": ("经常性订阅净新增同比", "pct1", "同比 %"),
    "operating_metrics.net_new_recurring_sales_usd_m": ("经常性订阅净新增", "f1", "US$M"),
    "operating_metrics.organic_revenue_growth_private_assets_pct": ("Private Assets 分部有机收入增速", "pct1", "有机增速 %"),
    "operating_metrics.revenue_growth_analytics_pct": ("Analytics 收入同比", "pct1", "同比 %"),
}

# The colour of the second, third and fourth threshold line on one chart; the
# first is the RED that `board.threshold_exhibit` draws.
EXTRA_LINE_COLORS = ["GOLD", "GREEN", "GRAY"]


def closure_chart(block: dict, values: dict[str, str]) -> dict:
    """Last quarter's follow-up questions, counted by verdict.

    The counts are computed from the items, never typed: each item names the
    bucket it is counted in, and an item whose bucket is not one of the block's
    labels stops the build rather than silently dropping out of the total.
    """
    labels = block["labels"]
    buckets = [item["bucket"] for item in block["items"]]
    unknown = sorted(set(buckets) - set(labels))
    if unknown:
        raise ValueError(f"followup_closure: buckets {unknown} are not among its labels {labels}")
    counts = [buckets.count(label) for label in labels]
    verdict = "、".join(f"{count} 条{label}" for label, count in zip(labels, counts) if count)
    lines = "".join(
        f"<br>{number}. {item['question']} —— <b>{item['verdict']}</b>：{fill_story(item['evidence'], values)}。"
        for number, item in enumerate(block["items"], 1))
    return {
        "ref": "EX_CLOSURE",
        "kind": "bars_labeled",
        "title": f"上季 {len(buckets)} 条待验证问题：{verdict}",
        "xlabels": list(labels),
        "values": counts,
        "legend": "问题条数",
        "fmt": "f0", "yfmt": "f0", "label_fmt": "f0",
        "ylab": "条",
        "note": block["note"] + lines,
        "src_extra": (f"问题清单出自上季（{display_period(block['set_in'])}）本地分析稿的 Follow-up Questions，"
                      "判定照录本季分析稿第 0 节；证据回到本季业绩 8-K EX-99.1 与公司业绩演示稿。"),
    }


def precision_range(entry: dict, entries: list[dict], denominator: float) -> tuple[float, float]:
    """The range a share can take when its numerator is printed to a coarse step."""
    numerator = next(e for e in entries if e["id"] == entry["numerator_id"])
    half = entry["printed_step"] / 2
    return ((numerator["actual"] - half) / denominator * 100,
            (numerator["actual"] + half) / denominator * 100)


def prior_settlement(staging: dict, block: dict, long_labels: list[str],
                     values: dict[str, str]) -> tuple[list[dict], list[list[str]]]:
    """Section one (b): last quarter's quantified thresholds, settled.

    One headroom bar per threshold number the prior note set for this quarter --
    a band is two numbers, and a warning line beside it is two more -- then one
    line chart per series that has a history, with every threshold on that series
    drawn on it. Returns the charts and the rows of the audit table.
    """
    entries = settle(staging, block["quantified"], "actual")
    safe = [headroom(e["direction"], e["threshold"], e["actual"]) >= 0 for e in entries]
    limited = block.get("precision_limited", [])
    denominator = staging["operating_metrics"]["net_new_recurring_sales_usd_m"][-1]
    limited_rows, limited_words = [], []
    for entry in limited:
        low, high = precision_range(entry, entries, denominator)
        if not low < entry["threshold"] < high:
            raise ValueError(f"prior threshold `{entry['id']}` can be settled at its printed precision "
                             f"({low:.1f}%–{high:.1f}%): move it to `quantified`")
        values[f"{entry['id']}_range"] = f"{low:.1f}%–{high:.1f}%"
        limited_words.append(f"「{entry['metric']}」无法结算：{fill_story(entry['reason'], values)}。")
        limited_rows.append([entry["metric"], "高于阈值为安全" if entry["direction"] == "up" else "低于阈值为安全",
                             unit_words(entry["unit"], entry["threshold"]), f"{low:.1f}%–{high:.1f}%", "—",
                             "精度不足，无法结算"])
    typed = [e["metric"] for e in entries if "actual_source" in e]
    note = ("正值 = 守住。阈值照录上季分析稿第 8 节，能在本季结算的数字逐条列出（一个区间是两条，旁边的警示线再算两条）"
            + (f"；{'、'.join(typed)} 这{cn_count(len(typed))}条的实际值取自公司业绩演示稿，申报文件不按地区拆销售"
               if typed else "")
            + "。" + "".join(limited_words)
            + ("另有" + cn_count(len(block.get("not_due", []))) + "条还没到期：" + "；".join(block["not_due"]) + "。"
               if block.get("not_due") else "")
            + ("上季还有一条没有给数：" + "；".join(block["unquantified"]) + "。" if block.get("unquantified") else ""))
    held = sum(safe)
    charts = [headroom_exhibit(
        f"上季 {len(entries)} 条量化阈值：{held} 条守住、{len(entries) - held} 条击穿"
        + (f"，另有{cn_count(len(limited))}条精度不足、无法结算" if limited else ""),
        entries, "actual", note,
        f"阈值为上季本地分析稿第 8 节的研究设定，不是公司指引；实际值为本季披露值（{display_period(staging['period_labels'][-1])}）。")]
    charts[0]["ref"] = "EX_PRIOR"

    groups: dict[str, list[dict]] = {}
    for entry in entries:
        if entry.get("chart"):
            groups.setdefault(entry["reads"], []).append(entry)
    for reads, group in groups.items():
        name, fmt, ylab = SETTLED_SERIES[reads]
        series = kpi_series(staging, reads)
        if len(series) != len(long_labels):
            raise ValueError(f"`{reads}` is not on the long axis")
        actual = group[0]["actual"]
        shown = unit_words(group[0]["unit"], actual) if group[0]["unit"] != "pct" else signed(actual)
        broke = [e["line"] for e in group if headroom(e["direction"], e["threshold"], e["actual"]) < 0]
        kept = [e["line"] for e in group if headroom(e["direction"], e["threshold"], e["actual"]) >= 0]
        verdicts = "；".join(part for part in (
            ("击穿上季" + "、".join(broke)) if broke else "",
            (("守住" if broke else "守住上季") + "、".join(kept)) if kept else "") if part)
        first = next(i for i, v in enumerate(series) if v is not None)
        in_record = [v for v in series if v is not None]
        chart = threshold_exhibit(
            f"{name}本季 {shown}：{verdicts}",
            long_labels, rounded(series), group[0]["threshold"],
            fmt=fmt, ylab=ylab, actual_name=name, threshold_name=f"上季{group[0]['line']}",
            note=settled_note(fill_story(block.get("series_notes", {}).get(reads, ""), values),
                              group, in_record, series_start_words(staging, reads, long_labels, first)),
            src_extra=SETTLED_SOURCES[reads], xstep=LONG_STEP)
        for extra, color in zip(group[1:], EXTRA_LINE_COLORS):
            chart["series"].append({"name": f"上季{extra['line']}",
                                    "values": [extra["threshold"]] * len(long_labels), "color": color})
        charts.append(chart)

    rows = [[e["metric"], "高于阈值为安全" if e["direction"] == "up" else "低于阈值为安全",
             unit_words(e["unit"], e["threshold"]), unit_words(e["unit"], e["actual"]),
             f"{headroom(e['direction'], e['threshold'], e['actual']):+.1f}%",
             "守住" if ok else "击穿"] for e, ok in zip(entries, safe)]
    rows += limited_rows
    rows += [[text.split("」")[0].lstrip("「"), "—", "—", "—", "—", "未到期"] for text in block.get("not_due", [])]
    rows += [[text.split(" —— ")[0], "—", "—", "—", "—", "上季没有给数"] for text in block.get("unquantified", [])]
    return charts, rows


# What each settled series is, where it comes from, and what its window can say.
SETTLED_SOURCES = {
    "net_new_yoy": ("各季业绩 8-K EX-99.1 的 Table 6「Consolidated」：2024Q3 起为公司印出的增速，"
                    "此前按本季与去年同季两个金额自算（D）。"),
    "operating_metrics.net_new_recurring_sales_usd_m": "各季业绩 8-K EX-99.1 的 Table 6「Consolidated」。",
    "operating_metrics.organic_revenue_growth_private_assets_pct": (
        "各季业绩 8-K EX-99.1 的有机收入增速调节表，All Other - Private Assets 区块 Total 列；公司印出值。"),
    "operating_metrics.revenue_growth_analytics_pct": (
        "各季业绩 8-K EX-99.1 的 Table 5，Analytics 区块 Total operating revenues 的同比 % Change；公司印出值。"),
}


# How each tracked series is drawn in section three: name, chart format, axis
# label, and -- for a series that starts after the long axis does -- why.
NEXT_SERIES = {
    "operating_metrics.net_new_recurring_sales_usd_m": ("经常性订阅净新增", "f1", "US$M", ""),
    "operating_metrics.aum_basis_point_fee": ("期末基点费率", "f2", "bp", ""),
    "operating_metrics.etf_cash_inflows_usd_b": ("挂钩 ETF 季度现金净流入", "f0c", "US$B", ""),
    "operating_metrics.organic_run_rate_growth_analytics_pct": (
        "Analytics 有机经常性订阅 Run Rate 增速", "pct1", "%",
        "公司从 {start} 那份发布起才按分部印有机 Run Rate 增速（此前只印全公司一个数），序列从那一季起画。"),
    "operating_metrics.retention_rate_sustainability_pct": (
        "Sustainability and Climate 留存率", "pct1", "%",
        "该分部单列之前只有 ESG、Real Estate 与 Burgiss 合在一起的 All Other，序列从公司重述出的第一季 {start} 起画，不拼接旧分部。"),
    "operating_metrics.net_new_recurring_sales_sustainability_usd_m": (
        "Sustainability and Climate 净新增", "f1", "US$M",
        "同上，序列从 {start} 起画。"),
}


def next_quarter_charts(staging: dict, block: dict,
                        long_labels: list[str]) -> tuple[list[dict], list[dict], list[dict]]:
    """Section three: this quarter's section 8, one headroom bar per threshold number.

    Section 8 sets two kinds of line on the same metric -- a risk line (减仓 /
    警示) and an add or stable line (加仓 / 稳定) -- and both belong in the
    overview, so the bars read "on the favourable side" rather than "safe": a
    risk line is favourable while untriggered, an add line once reached. A
    threshold of zero has no percentage headroom; it is drawn on its series'
    chart and listed in the audit table instead. Guidance thresholds have no
    quarterly series and appear as bars only.
    """
    entries = settle(staging, block["quantified"], "current")
    zero = settle(staging, block.get("zero_lines", []), "current")
    om = staging["operating_metrics"]
    favourable = [headroom(e["direction"], e["threshold"], e["current"]) >= 0 for e in entries]
    risk = [ok for e, ok in zip(entries, favourable) if e["kind"] == "risk"]
    upside = [ok for e, ok in zip(entries, favourable) if e["kind"] == "upside"]
    title = (f"下季 {len(entries)} 条阈值：{len(risk)} 条风险线"
             + ("都没触发" if all(risk) else f"有 {len(risk) - sum(risk)} 条已触发")
             + f"，{len(upside)} 条加仓 / 稳定线达到 {sum(upside)} 条")
    guided = [e for e in entries if e["reads"].startswith("guide_")]
    note = ("正值 = 在阈值的有利一侧：风险线（减仓 / 警示）为正表示还没触发，加仓 / 稳定线为正表示已经达到。"
            "阈值照录本季本地分析稿第 8 节，不是公司指引。"
            + "".join(f"「{z['metric']}」阈值为零，折不成百分比余量，不进柱图，画在它那条序列的图上"
                      f"（本季 {unit_words(z['unit'], z['current'])}）。" for z in zero)
            + (f"FY{max(staging['annual_guidance_history']['years'])} 指引的{cn_count(len(guided))}条没有季度序列，"
               f"只进柱图，要等 {display_period(block['for_period'])} 的业绩发布更新 Full-Year Guidance 表才能结算；"
               "当前值读自本季那张表。" if guided else ""))
    charts = [headroom_exhibit(title, entries, "current", note,
                               f"阈值为本季本地分析稿第 8 节的研究设定；当前值为 {display_period(staging['period_labels'][-1])} 披露值。")]
    charts[0].update({"ref": "EX_NEXT", "positive_label": "在阈值有利一侧", "negative_label": "在阈值不利一侧"})

    groups: dict[str, list[dict]] = {}
    for entry in entries + zero:
        if entry["reads"].startswith("operating_metrics."):
            groups.setdefault(entry["reads"], []).append(entry)
    for reads, group in groups.items():
        group.sort(key=lambda e: e["kind"] != "risk")
        name, fmt, ylab, start_words = NEXT_SERIES[reads]
        series = path_values(staging, reads)
        current = group[0]["current"]
        first = next(i for i, v in enumerate(series) if v is not None)
        in_record = [v for v in series if v is not None]
        sides = "；".join(side_words(e, in_record) for e in group)
        chart = threshold_exhibit(
            f"{name}：下季阈值 " + " / ".join(unit_words(e["unit"], e["threshold"]) for e in group)
            + f"，当前 {unit_words(group[0]['unit'], current)}",
            long_labels, rounded(series), group[0]["threshold"],
            fmt=fmt, ylab=ylab, actual_name=name, threshold_name=f"下季{group[0]['line']}",
            note=(f"有数的{cn_count(len(in_record))}个季度里，{sides}。"
                  + (start_words.format(start=long_labels[first]) if first else "")
                  + "，".join(words for kind, words in (("risk", "红线是风险线"), ("upside", "绿线是加仓 / 稳定线"))
                             if any(e["kind"] == kind for e in group))
                  + "；阈值照录本季分析稿第 8 节，不是公司指引。"),
            src_extra=NEXT_SOURCES[reads], xstep=LONG_STEP)
        chart["series"][1]["color"] = "RED" if group[0]["kind"] == "risk" else "GREEN"
        for extra in group[1:]:
            chart["series"].append({"name": f"下季{extra['line']}",
                                    "values": [extra["threshold"]] * len(long_labels),
                                    "color": "RED" if extra["kind"] == "risk" else "GREEN"})
        charts.append(chart)
    return charts, entries, zero


def side_words(entry: dict, in_record: list[float]) -> str:
    """How often a series' own record sat on the side of a line that matters:
    past a risk line, or at or beyond an add / stable line."""
    up = entry["direction"] == "up"
    favourable = [v >= entry["threshold"] if up else v <= entry["threshold"] for v in in_record]
    if entry["kind"] == "risk":
        return f"{'低于' if up else '高于'}{entry['line']} 的有 {favourable.count(False)} 个"
    return f"{'不低于' if up else '不高于'}{entry['line']} 的有 {favourable.count(True)} 个"


NEXT_SOURCES = {
    "operating_metrics.net_new_recurring_sales_usd_m": "各季业绩 8-K EX-99.1 的 Table 6「Consolidated」。",
    "operating_metrics.aum_basis_point_fee": "各季业绩 8-K EX-99.1 的 Table 7 期末基点费率（2020Q2 之前标签为 Avg.，定义未变）。",
    "operating_metrics.etf_cash_inflows_usd_b": "各季业绩 8-K EX-99.1 的 Table 7 Cash Inflows；负值为净流出。",
    "operating_metrics.organic_run_rate_growth_analytics_pct": (
        "各季业绩 8-K EX-99.1 正文的分部有机 Run Rate 增速，2025Q1 起同时印在 Table 8 的 Organic Run Rate Growth 列。"),
    "operating_metrics.retention_rate_sustainability_pct": (
        "各季业绩 8-K EX-99.1 的 Table 6；2020 年四季取自 2021-02-23 的分部重述 8-K。"),
    "operating_metrics.net_new_recurring_sales_sustainability_usd_m": (
        "各季业绩 8-K EX-99.1 的 Table 6；2020 年四季取自 2021-02-23 的分部重述 8-K。"),
}


def settled_note(lead: str, group: list[dict], in_record: list[float], window: str) -> str:
    """The caption of one settled series: what the prior note asked of it (``lead``,
    from the stamped block), then how often its own record sat on each side."""
    sides = "；".join(
        f"{'不低于' if e['direction'] == 'up' else '不高于'}{e['line']} 的有 "
        f"{sum(1 for v in in_record if (v >= e['threshold'] if e['direction'] == 'up' else v <= e['threshold']))} 个"
        for e in group)
    return f"{lead}有数的{cn_count(len(in_record))}个季度里，{sides}。{window}"


def series_start_words(staging: dict, reads: str, long_labels: list[str], first: int) -> str:
    """Why a settled series starts where it does, read off the series itself."""
    om = staging["operating_metrics"]
    if reads == "net_new_yoy":
        printed = om["net_new_recurring_sales_yoy_printed_pct"]
        since = next(i for i, v in enumerate(printed) if v is not None)
        return (f"前{cn_count(first)}格没有同比：本记录从 {long_labels[0]} 起，去年同季不在记录里。"
                f"{long_labels[since]} 起是公司印出的增速，更早的季度公司没印这一列，按两季金额自算（D）。")
    if first:
        return f"该分部 {long_labels[first]} 起才单列为报告分部，序列从那一季起画，不向前回补。"
    return ""


def threshold_audit_table(n: int, title: str, entries: list[dict], zero: list[dict]) -> dict:
    """`board.threshold_table`, with the basis-point level this page needs, the
    kind of each line, and the zero-valued lines that have no percentage headroom."""
    def row(entry: dict, room: str) -> list[str]:
        return [entry["metric"],
                "风险线" if entry["kind"] == "risk" else "加仓 / 稳定线",
                "高于阈值为有利" if entry["direction"] == "up" else "低于阈值为有利",
                unit_words(entry["unit"], entry["threshold"]),
                unit_words(entry["unit"], entry["current"]),
                room]
    return {
        "n": n,
        "title": title,
        "headers": ["指标", "类型", "方向", "阈值", "当前值", "余量 D"],
        "rows": ([row(e, f"{headroom(e['direction'], e['threshold'], e['current']):+.1f}%") for e in entries]
                 + [row(z, "—（阈值为零，不折百分比）") for z in zero]),
    }


def finished_years(hist: dict) -> list[int]:
    """Years every guided line has an actual for -- the ones a record can settle."""
    return [year for year in hist["years"]
            if all(item["by_year"][str(year)]["actual"] is not None
                   for item in hist["items"].values())]


def tally(hist: dict, key: str, vintage: int) -> dict:
    """Where each finished year's actual landed against one vintage of its range."""
    counts = {"n": 0, "inside": 0, "above": 0, "below": 0}
    for year in finished_years(hist):
        block = hist["items"][key]["by_year"][str(year)]
        low, high, _ = [g for g in block["guided"] if g][vintage]
        counts["n"] += 1
        if block["actual"] > high:
            counts["above"] += 1
        elif block["actual"] < low:
            counts["below"] += 1
        else:
            counts["inside"] += 1
    return counts


def opens_with_first_release(hist: dict, key: str) -> bool:
    """Whether every finished year's first guide of `key` is its year's first release."""
    for year in finished_years(hist):
        block = hist["items"][key]["by_year"][str(year)]
        first = next(date for g, date in zip(block["guided"], block["releases"]) if g)
        if first != block["releases"][0]:
            return False
    return True


def open_year_moves(hist: dict) -> dict:
    """How the open year's guidance moved, release by release.

    `steps[r]` maps each guided line to the change of its midpoint between
    release r-1 and release r (None for the first release); `net` is the move
    from the year's first range to its latest one, in percent.
    """
    year = max(hist["years"])
    releases = hist["releases_by_year"][str(year)]
    midpoints = {}
    for key, _ in GUIDED:
        guided = hist["items"][key]["by_year"][str(year)]["guided"]
        midpoints[key] = [None if g is None else (g[0] + g[1]) / 2 for g in guided]
    steps = []
    for index in range(len(releases)):
        step = {}
        for key, _ in GUIDED:
            now = midpoints[key][index]
            before = midpoints[key][index - 1] if index else None
            step[key] = None if now is None or before is None else pct_change(now, before)
        steps.append(step)
    net = {}
    for key, _ in GUIDED:
        present = [m for m in midpoints[key] if m is not None]
        net[key] = pct_change(present[-1], present[0]) if len(present) > 1 else 0.0
    moved = [index for index, step in enumerate(steps)
             if any(v for v in step.values() if v is not None)]
    return {"year": year, "releases": releases, "steps": steps, "net": net, "moved": moved}


def guidance_charts(staging: dict) -> tuple[list[dict], list[dict]]:
    """The annual guidance record: three metrics, band then deviation each."""
    hist = staging["annual_guidance_history"]
    finished = finished_years(hist)
    labels = [f"FY{y}" for y in finished]

    def legs(key):
        """First and last guided range per year, plus which release each came from.

        `guided` keeps one slot per release of that year, and a slot is None
        when the metric was not guided that quarter -- MSCI did not guide free
        cash flow at all until 2015-07-30, so FY2015 has two leading Nones.
        Dropping them and calling what is left `guided[0]` would silently
        promote a July vintage into a column headed "年初第一次指引", which is
        the one thing this record must not do. So the release date travels with
        the value and the copy below asks whether they actually agree.
        """
        by_year = hist["items"][key]["by_year"]
        first_lo, first_hi, last_lo, last_hi, actual = [], [], [], [], []
        first_is_opening = []
        for y in finished:
            block = by_year[str(y)]
            pairs = [(g, d) for g, d in zip(block["guided"], block["releases"]) if g]
            (flo, fhi, _), fdate = pairs[0]
            (llo, lhi, _), _ = pairs[-1]
            first_lo.append(flo); first_hi.append(fhi)
            last_lo.append(llo); last_hi.append(lhi)
            actual.append(block["actual"])
            first_is_opening.append(fdate == block["releases"][0])
        return first_lo, first_hi, last_lo, last_hi, actual, first_is_opening

    charts, tables = [], []
    spec = [
        ("operating_expense", "营业费用", "EX_OPEX"),
        ("adj_ebitda_expense", "调整后 EBITDA 费用", "EX_AEBX"),
        ("free_cash_flow", "自由现金流", "EX_FCF"),
    ]
    for key, name, ref in spec:
        flo, fhi, llo, lhi, act, opening = legs(key)
        # A year whose first guide is not the year's opening release gets its
        # date printed instead of a bare range, so the column never claims a
        # vintage it does not have.
        late = [(lab, hist["items"][key]["by_year"][str(y)]["releases"][
                     [g is not None for g in
                      hist["items"][key]["by_year"][str(y)]["guided"]].index(True)])
                for lab, y, ok in zip(labels, finished, opening) if not ok]
        late_note = ("" if not late else
                     "　该指标并非每年都在年初就被指引："
                     + "、".join(f"{lab} 的第一次指引发布于 {d}" for lab, d in late)
                     + "，那一年没有年初口径可比，本页用的是它真正的第一次。")
        charts.append(delivery_band(
            f"{ref}_BAND", name, labels, llo, lhi, act,
            fmt="f0c", ylab="US$M", unit="US$M",
            venue="业绩新闻稿",
            timing="该年<b>当年内</b>",
            period_word="年",
            extra_note=(
                "这里画的是<b>当年最后一次</b>指引，不是年初那一次 —— MSCI 每季在业绩新闻稿里"
                "重新给一次全年指引，最后一次通常发布于 10 月底，此时全年已过去四分之三。"
                f"同一指标对<b>年初第一次</b>指引的兑现情况见 Exhibit {{{ref}_DEV}}。"),
            src_extra=("指引取自各年业绩 8-K EX-99.1 的 Full-Year Guidance 表；"
                       "实际值取自次年 Q4 发布中 Table 11 与 Table 12 的 Year Ended 列。"),
        ))
        charts.append(annual_deviation(
            f"{ref}_DEV", name, labels, llo, lhi, act,
            src_extra="偏离 = 实际值 ÷ 指引中值 − 1，中值取当年最后一次指引区间的中点。",
            extra_note=(
                "<b>同一年、同一指标，换成年内第一次指引就是另一幅样子</b>："
                + "、".join(
                    f"{lab} 对第一次指引{'高' if a > (lo + hi) / 2 else '低'}"
                    f" {abs(pct_change(a, (lo + hi) / 2)):.1f}%"
                    for lab, lo, hi, a in zip(labels, flo, fhi, act))
                + "。" + late_note),
        ))
        rows = [[lab,
                 f"${lo:,.0f}–{hi:,.0f}M" + ("" if ok else "（首次指引发布于年中）"),
                 f"${l2:,.0f}–{h2:,.0f}M", f"${a:,.0f}M",
                 "区间内" if l2 <= a <= h2 else ("高于上限" if a > h2 else "低于下限")]
                for lab, lo, hi, l2, h2, a, ok
                in zip(labels, flo, fhi, llo, lhi, act, opening)]
        tables.append({"title": f"{name}：年内第一次指引、年末指引与全年实际",
                       "headers": ["年度", "年内第一次指引", "当年最后一次指引", "全年实际", "对最后一次指引"],
                       "rows": rows})
    return charts, tables


def annual_deviation(ref: str, metric: str, years: list[str], low: list[float],
                     high: list[float], actual: list[float], *, src_extra: str,
                     extra_note: str = "") -> dict:
    """Distance from the guided midpoint, for an ANNUAL record.

    ``board.midpoint_deviation`` hard-codes the word 季 into every sentence it
    builds, so an annual series renders as "7 季里 6 季为正". Rather than add a
    parameter to a shared helper that another session is already changing, this
    page builds its own annual twin; the arithmetic is the same.
    """
    midpoints = mid(low, high)
    deviation = [(a / m - 1) * 100 for a, m in zip(actual, midpoints)]
    above = sum(1 for v in deviation if v > 0)
    mean_abs = statistics.fmean(abs(v) for v in deviation)
    biggest = max(deviation, key=abs)
    return {
        "ref": ref,
        "kind": "grouped_bars",
        "title": (f"{metric}相对指引中值的偏离：{len(deviation)} 个完整年度里 {above} 年为正，"
                  f"平均绝对偏离 {mean_abs:.1f}%"),
        "xlabels": list(years),
        "groups": [{"name": f"实际{metric} vs 指引中值", "color": "BLUE",
                    "values": rounded(deviation)}],
        "bar_labels": True,
        "fmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "% vs 指引中值",
        "note": ("正值 = 高于指引区间的中值。"
                 f"窗口内最大的一次是 {years[deviation.index(biggest)]} 的 {biggest:+.1f}%。"
                 + extra_note),
        "src_extra": src_extra,
    }


def revision_chart(staging: dict, moves: dict, story: dict | None) -> dict | None:
    """The open year's guidance: how far each line moved since its first range.

    Drawn only when the year has been revised at all -- a year with one release,
    or with releases that repeat the first, would be a row of zero bars.
    """
    year, releases, net = moves["year"], moves["releases"], moves["net"]
    if len(releases) < 2 or not moves["moved"]:
        return None
    last = len(releases) - 1
    opex, fcf = net["operating_expense"], net["free_cash_flow"]
    verb = "上调" if opex > 0 else "下调" if opex < 0 else "未动"
    title = (f"FY{year} 指引{cn_count(len(releases))}次发布后的净移动：营业费用中值{verb}"
             + (f" {opex:+.1f}%" if opex else "")
             + f"，自由现金流{'仅 ' if opex and abs(fcf) < abs(opex) / 2 else ''}{fcf:+.1f}%")
    step = {key: value or 0.0 for key, value in moves["steps"][last].items()}
    first_move = moves["moved"][0] == last
    five = cn_count(len(GUIDED))
    names = dict(GUIDED)
    if first_move:
        lead = (f"<b>本季（{releases[last]}）是 FY{year} 指引里本图{five}项第一次移动</b>："
                f"{joined_months(releases[:last])}{cn_count(last)}次发布里"
                f"这{five}项一字未动{(story or {}).get('earlier_note', '')}，")
    elif last in moves["moved"]:
        lead = (f"<b>本季（{releases[last]}）FY{year} 指引第{cn_ordinal(len(moves['moved']))}次移动</b>：")
    else:
        lead = (f"<b>本季（{releases[last]}）FY{year} 指引没有再动</b>，图上是此前的累计移动。")
    body = ""
    if last in moves["moved"]:
        expense_up = [names[k] for k in ("operating_expense", "adj_ebitda_expense") if step[k] > 0]
        cash = [step["op_cash_flow"], step["free_cash_flow"]]
        capex = step["capex"]
        if len(expense_up) == 2 and first_move:
            raised = expense_up + list((story or {}).get("also_raised", []))
            cash_words = ("现金流两条只跟着抬了很小一步"
                          if all(0 < c < step["operating_expense"] / 2 for c in cash) else
                          "现金流两条没动" if all(c == 0 for c in cash) else
                          "现金流两条也跟着上调" if all(c > 0 for c in cash) else
                          "现金流两条下调" if all(c < 0 for c in cash) else "现金流两条一升一降")
            capex_words = ("资本开支完全没动" if capex == 0 else
                           "资本开支上调" if capex > 0 else "资本开支下调")
            body = (f"{month_words(releases[last])}把{joined(raised)}一起上调，"
                    f"{cash_words}，{capex_words}。")
        else:
            body = ("本季相对上一次发布，" + "、".join(
                f"{names[k]}中值 {step[k]:+.1f}%" for k, _ in GUIDED if step[k] is not None) + "。")
    reading = (story or {}).get("reading")
    tail = (f"{reading} —— 这条判断的兑现要等 FY{year} 的 Q4 发布才能结清，"
            if reading else f"这次修订的兑现要等 FY{year} 的 Q4 发布才能结清，")
    return {
        "ref": f"EX_FY{str(year)[2:]}",
        "kind": "diverging_bars",
        "title": title,
        "xlabels": [name for _, name in GUIDED],
        "values": [round(net[key], 2) for key, _ in GUIDED],
        "legend": "相对年初指引中值的移动",
        "positive_label": "上调",
        "negative_label": "下调",
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1",
        "ylab": "% vs 年初指引中值",
        "zero_line": True,
        "note": lead + body + tail + "届时会并入 Exhibit {EX_OPEX_BAND}。",
        "src_extra": (f"{cn_count(len(releases))}次发布：{'、'.join(releases)} 的业绩 8-K EX-99.1 "
                      "Full-Year Guidance 表；移动为最后一次中值相对第一次中值的百分比。"),
    }


def aum_flow_chart(om: dict) -> dict:
    """Where the quarter's AUM increase came from: the market, or new money.

    Table 7 splits each quarter's change in ETF assets linked to MSCI equity
    indexes into market appreciation and cash inflows; asset-based fees are
    charged on the resulting balance either way, but only the inflow is a
    client's choice.
    """
    quarters, labels = om["quarters"], om["period_labels"]
    market, inflow = om["etf_market_appreciation_usd_b"], om["etf_cash_inflows_usd_b"]
    change = market[-1] + inflow[-1]
    if change > 0 and market[-1] > inflow[-1]:
        title = (f"本季挂钩 ETF 的 AUM 增加 US${change:,.0f}B，{market[-1] / change * 100:.1f}% 来自市场升值："
                 f"现金净流入 US${inflow[-1]:,.0f}B，上季 US${inflow[-2]:,.0f}B")
    else:
        title = (f"本季挂钩 ETF 的 AUM {'增加' if change >= 0 else '减少'} US${abs(change):,.0f}B："
                 f"市场升值 US${market[-1]:,.0f}B、现金净流入 US${inflow[-1]:,.0f}B")
    outflows = [quarters[i] for i, v in enumerate(inflow) if v < 0]
    market_led = sum(1 for m, c in zip(market, inflow) if m + c > 0 and m > c)
    growing = sum(1 for m, c in zip(market, inflow) if m + c > 0)
    return {
        "ref": "EX_FLOW",
        "kind": "grouped_bars",
        "title": title,
        "xlabels": labels,
        "groups": [
            {"name": "市场升值 / 贬值", "color": "BLUE", "values": rounded(market)},
            {"name": "现金净流入", "color": "NAVY", "values": rounded(inflow)},
        ],
        "fmt": "f0c", "label_fmt": "f0c", "ylab": "US$B", "xstep": LONG_STEP,
        "note": ("资产型费用按挂钩 ETF 的资产规模计费，市场涨跌与投资者净申购都会改变这个规模，但只有净流入是客户自己的选择。"
                 f"本季净流入比上季{'少' if inflow[-1] < inflow[-2] else '多'} "
                 f"{abs(pct_change(inflow[-1], inflow[-2])):.1f}%。"
                 f"{cn_count(len(quarters))}个季度里 AUM 增加的有{cn_count(growing)}个，其中市场升值大过净流入的有"
                 f"{cn_count(market_led)}个；净流入为负的"
                 + (f"有{cn_count(len(outflows))}个（{'、'.join(outflows)}）。" if outflows else "一个都没有。")),
        "src_extra": "各季业绩 8-K EX-99.1 的 Table 7；两项相加等于该季期末与期初 AUM 之差。",
    }


def eps_gap_chart(om: dict, notes: dict | None) -> dict:
    """Diluted against adjusted EPS: the quarter the two cross is a one-off, not a trend."""
    quarters, labels = om["quarters"], om["period_labels"]
    diluted, adjusted = om["diluted_eps_usd"], om["adjusted_eps_usd"]
    gap, gap_prev = diluted[-1] - adjusted[-1], diluted[-2] - adjusted[-2]
    above = [quarters[i] for i, (d, a) in enumerate(zip(diluted, adjusted)) if d > a]
    return {
        "ref": "EX_EPS",
        "kind": "lines",
        "title": (f"摊薄 EPS 环比 {signed(pct_change(diluted[-1], diluted[-2]))}、调整后 EPS 环比 "
                  f"{signed(pct_change(adjusted[-1], adjusted[-2]))}：上季摊薄比调整后"
                  f"{'高' if gap_prev > 0 else '低'} US${abs(gap_prev):.2f}，本季{'高' if gap > 0 else '低'} US${abs(gap):.2f}"),
        "xlabels": labels,
        "series": [{"name": "摊薄 EPS", "values": rounded(diluted), "color": "NAVY"},
                   {"name": "调整后 EPS", "values": rounded(adjusted), "color": "BLUE"}],
        "fmt": "f2", "yfmt": "f2", "label_fmt": "f2", "end_label": True,
        "ylab": "US$ / 股", "xstep": LONG_STEP,
        "note": ("调整后 EPS 是摊薄 EPS 加回收购无形资产摊销、并在个别季度剔除离散税项等一次性项目（公司口径）；"
                 f"{cn_count(len(quarters))}个季度里摊薄高过调整后的有{cn_count(len(above))}个"
                 + (f"（{'、'.join(above)}）。" if above else "。")
                 + ((notes or {}).get("eps", ""))),
        "src_extra": "各季业绩 8-K EX-99.1 首页摘要表的 Diluted EPS 与 Adjusted EPS；两条都是公司印出值。",
    }


# The retention lines drawn side by side: name, series, colour, and -- for the two
# smaller segments -- the subscription run rate their weight can be read from.
RETENTION_LINES = [
    ("总留存率", "retention_rate_pct", "NAVY", None),
    ("Index", "retention_rate_index_pct", "MBLUE", None),
    ("Analytics", "retention_rate_analytics_pct", "BLUE", None),
    ("Sustainability and Climate", "retention_rate_sustainability_pct", "GOLD", "run_rate_sustainability_usd_m"),
    ("All Other – Private Assets", "retention_rate_private_assets_pct", "GREEN", "run_rate_private_assets_usd_m"),
]


def segment_retention_chart(om: dict) -> dict:
    """The consolidated retention rate against the four segments it is made of."""
    segments = [(name, key, weight) for name, key, _, weight in RETENTION_LINES[1:]]
    now = {name: om[key][-1] for name, key, _ in segments}
    lowest = min(now, key=now.get)
    highest = max(now, key=now.get)
    total = om["retention_rate_pct"]
    low_key, low_weight = next((key, weight) for name, key, weight in segments if name == lowest)
    low_series = om[low_key]
    weight_words = (f"它只占订阅 Run Rate 的 {om[low_weight][-1] / om['run_rate_recurring_usd_m'][-1] * 100:.0f}%，"
                    "所以它的下滑在总数里几乎看不出来。" if low_weight else "")
    net_new_words = (f"同期该分部经常性订阅净新增 US${om['net_new_recurring_sales_sustainability_usd_m'][-1]:.1f}M、"
                     f"去年同季 US${om['net_new_recurring_sales_sustainability_usd_m'][-5]:.1f}M。"
                     if low_key == "retention_rate_sustainability_pct" else "")
    return {
        "ref": "EX_RETSEG",
        "kind": "lines",
        "title": (f"总留存率 {total[-1]:.1f}%，四个分部里 {lowest} 最低（{now[lowest]:.1f}%）、"
                  f"{highest} 最高（{now[highest]:.1f}%）"),
        "xlabels": om["period_labels"],
        "series": [{"name": name, "values": rounded(om[key]), "color": color}
                   for name, key, color, _ in RETENTION_LINES],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
        "ylab": "%", "xstep": LONG_STEP,
        "note": (f"{lowest} 本季 {now[lowest]:.1f}%，去年同季 {low_series[-5]:.1f}%；" + weight_words + net_new_words
                 + "留存率有第四季集中续约带来的季节性，跨年比较要同季对同季（总留存率的长序列见第四板块）。"
                 "Sustainability and Climate 与 All Other – Private Assets 两条从公司重述出的第一季起画：两者 2021 年才单列，"
                 "此前只有合在一起的 All Other。"),
        "src_extra": ("各季业绩 8-K EX-99.1 的 Table 6（2018Q2 之前叫 Aggregate Retention Rate，定义未变）；"
                      "两个 2021 年单列的分部，2020 年四季取自 2021-02-23 的分部重述 8-K。"),
    }


def guidance_headline(moves: dict) -> str:
    """The last clause of the headline: what this quarter's release did to the year."""
    year, releases, steps = moves["year"], moves["releases"], moves["steps"]
    if len(releases) == 1:
        return f"公司本季给出 FY{year} 的第一份全年指引。"
    step = {key: value or 0.0 for key, value in steps[-1].items()}
    opex = step["operating_expense"]
    if not opex:
        return f"公司本季维持 FY{year} 费用指引。"
    up = opex > 0
    same_way = sum(1 for s in steps[1:] if s["operating_expense"]
                   and (s["operating_expense"] > 0) == up)
    ordinal = "首次" if same_way == 1 else f"第{cn_ordinal(same_way)}次"
    cash = [step["op_cash_flow"], step["free_cash_flow"]]
    cash_words = ("现金流两条几乎没动" if all(abs(c) < abs(opex) / 2 for c in cash) else
                  "现金流两条同向调整" if all((c > 0) == up and c for c in cash) else
                  "现金流两条反向调整")
    return f"公司本季{ordinal}{'上调' if up else '下调'} FY{year} 费用指引，{cash_words}。"


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    fin = staging["financials"]
    return [f"Revenue ${fin['revenue_usd_m'][-1]:.0f}M",
            f"ETF AUM ${staging['operating_metrics']['aum_period_end_usd_b'][-1]:,.0f}B",
            f"Adj EBITDA {fin['adj_ebitda_margin_pct'][-1]:.1f}%"]


def build_payload(staging: dict) -> dict:
    fin = staging["financials"]
    seg = staging["segments_usd_m"]
    om = staging["operating_metrics"]
    hist = staging["annual_guidance_history"]
    labels = staging["period_labels"]
    period = labels[-1]
    latest = latest_block(staging, period=period, period_end=staging["period_ends"][-1])
    release = release_source(staging)
    update = stamped_block(staging, "guidance_update", period)
    kpi_block = stamped_block(staging, "next_kpi", period)

    finished = finished_years(hist)
    oe_last, oe_first = tally(hist, "operating_expense", -1), tally(hist, "operating_expense", 0)
    fcf_last, fcf_first = tally(hist, "free_cash_flow", -1), tally(hist, "free_cash_flow", 0)
    oe_n = oe_last["n"]

    long_labels = om["period_labels"]
    quarters = om["quarters"]

    revenue = fin["revenue_usd_m"]
    aum = om["aum_period_end_usd_b"]
    bp = om["aum_basis_point_fee"]
    run_rate = om["run_rate_total_usd_m"]

    # ── section one: what last quarter left to settle, then the company's record
    closure_block = stamped_block(staging, "followup_closure", period)
    prior_block = stamped_block(staging, "prior_kpi_settlement", period)
    for name, block in (("followup_closure", closure_block), ("prior_kpi_settlement", prior_block)):
        if block and display_period(block["set_in"]) != previous_label(period):
            raise ValueError(f"series block `{name}` settles what was set in {block['set_in']!r}, "
                             f"but the quarter before {period!r} is {previous_label(period)!r}")
    values = quarter_values(staging)
    settled, settled_tables = guidance_charts(staging)
    lead_charts, prior_rows = [], []
    if closure_block:
        lead_charts.append(closure_chart(closure_block, values))
    if prior_block:
        prior_charts, prior_rows = prior_settlement(staging, prior_block, long_labels, values)
        lead_charts += prior_charts
    settled = lead_charts + settled

    # ── section two opens on this quarter's revision of the open year ───────
    # The revision is news of this quarter (the July release moved the year's
    # ranges), not a settlement of anything set last quarter, so it leads the
    # highlights rather than the settled section; it is settled only when the
    # year's Q4 release lands and the year joins the bands in section one.
    moves = open_year_moves(hist)
    revision = revision_chart(staging, moves, update)

    # ── section two: what moved this quarter ────────────────────────────────
    rec, abf, non = fin["recurring_usd_m"], fin["abf_usd_m"], fin["nonrecurring_usd_m"]
    legs_ok = all(abs(rec[i] + abf[i] + non[i] - revenue[i]) <= TOLERANCE for i in range(len(labels)))
    mix_chart = {
        "ref": "EX_MIX",
        "kind": "grouped_bars",
        "title": (f"三条收入腿：资产型费用同比 "
                  f"{signed(pct_change(abf[-1], abf[-5]))}，订阅 "
                  f"{signed(pct_change(rec[-1], rec[-5]))}"),
        "xlabels": labels,
        "groups": [
            {"name": "经常性订阅", "color": "NAVY", "values": rounded(rec)},
            {"name": "资产型费用", "color": "BLUE", "values": rounded(abf)},
            {"name": "非经常性", "color": "GOLD", "values": rounded(non)},
        ],
        "fmt": "f0c", "label_fmt": "f0c", "ylab": "US$M",
        "note": ("<b>三条腿的性质不同</b>：订阅收入按合同确认、随 Run Rate 走；"
                 "资产型费用直接挂在挂钩 MSCI 股票指数的 ETF 资产规模上，随市场涨跌；"
                 "非经常性是一次性授权与咨询。"
                 f"本季资产型费用占总收入 {abf[-1] / revenue[-1] * 100:.1f}%，"
                 f"四个季度前是 {abf[-5] / revenue[-5] * 100:.1f}%。"
                 + (f"三条相加等于合并收入，{len(labels)} 个季度逐季核对无差。" if legs_ok else "")),
        "src_extra": "各季业绩 8-K EX-99.1 的 Table 5「Consolidated」区块。",
    }

    segment_sum_ok = all(abs(sum(seg[key]["revenue"][i] for key, _ in SEGMENTS) - revenue[i]) <= TOLERANCE
                         for i in range(len(labels)))
    after_split = int(display_period(labels[0]).split()[1]) >= 2021
    # Year-on-year growth by segment across the part of the window that has a
    # base, first quarter against last: which segments sped up.
    yoy_from = 4
    rising = []
    for key, name in SEGMENTS:
        values = seg[key]["revenue"]
        start, end = pct_change(values[yoy_from], values[yoy_from - 4]), pct_change(values[-1], values[-5])
        # Compared at the precision the note prints, so 「+9.7% → +9.7%」 is not a rise.
        if round(end, 1) > round(start, 1):
            rising.append((key, name, start, end))
    if [key for key, *_ in rising] == ["index"]:
        speed_words = "，也是唯一在本窗口内加速的分部。"
    elif rising:
        rising.sort(key=lambda row: row[3] - row[2], reverse=True)
        named = [f"{name}（{signed(a)} → {signed(b)}）" for _, name, a, b in rising]
        speed_words = (f"。{labels[yoy_from]} 到 {labels[-1]}，同比增速抬升的是 "
                       + ("、".join(named[:-1]) + "与 " + named[-1] if len(named) > 1 else named[0])
                       + (f"，其余{cn_count(len(SEGMENTS) - len(rising))}个放缓。"
                          if len(rising) < len(SEGMENTS) else "。"))
    else:
        speed_words = f"。{labels[yoy_from]} 到 {labels[-1]}，四个分部的同比增速都在放缓。"
    seg_rev_chart = {
        "ref": "EX_SEG",
        "kind": "grouped_bars",
        "title": (f"四个分部：Index 一家贡献本季收入的 "
                  f"{seg['index']['revenue'][-1] / revenue[-1] * 100:.0f}%"),
        "xlabels": labels,
        "groups": [{"name": name, "color": c,
                    "values": rounded(seg[key]["revenue"])}
                   for (key, name), c in zip(SEGMENTS, ["NAVY", "BLUE", "GOLD", "RED"])],
        "fmt": "f0c", "label_fmt": "f0c", "ylab": "US$M",
        "note": ("Index 是唯一同时拥有订阅与资产型费用两条腿的分部" + speed_words
                 + ("四个分部收入相加等于合并收入，逐季核对无差。" if segment_sum_ok else "")
                 + ("2021 年之前 ESG 与 Private Assets 合并为一个 All Other 分部，"
                    "本图窗口全部在拆分之后。" if after_split else "")),
        "src_extra": "各季业绩 8-K EX-99.1 的 Table 5 四个分部区块。",
    }

    margins = {key: seg[key]["adj_ebitda_margin_pct"] for key, _ in SEGMENTS}
    spread = min(max(m[i] for m in margins.values()) - min(m[i] for m in margins.values())
                 for i in range(len(labels)))
    own = max(max(m) - min(m) for m in margins.values())
    index_m, pa_m = margins["index"], margins["private_assets"]
    seg_margin_chart = {
        "ref": "EX_SEGM",
        "kind": "lines",
        "title": (f"分部调整后 EBITDA 利润率：Index "
                  f"{seg['index']['adj_ebitda_margin_pct'][-1]:.1f}%，"
                  f"Private Assets {seg['private_assets']['adj_ebitda_margin_pct'][-1]:.1f}%"),
        "xlabels": labels,
        "series": [{"name": name, "values": rounded(seg[key]["adj_ebitda_margin_pct"]),
                    "color": c}
                   for (key, name), c in zip(SEGMENTS, ["NAVY", "BLUE", "GOLD", "RED"])],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
        "ylab": "调整后 EBITDA 利润率 %",
        "note": (("四条线之间的差距，比任何一条自己的变化都大：" if spread > own else
                  "四条线各自的起伏与它们之间的差距同一量级：")
                 + f"Index 的分部利润率在 {min(index_m):.1f}%–{max(index_m):.1f}% 之间，"
                 f"Private Assets 在 {min(pa_m):.1f}%–{max(pa_m):.1f}%。"
                 + ("合并利润率因此主要由收入落在哪个分部决定，"
                    "而不是由任何一个分部自己的成本控制决定。" if spread > own else "")),
        "src_extra": "各季业绩 8-K EX-99.1 的 Table 5；分部利润率为公司披露值，不是自算。",
    }

    bp_start = next(i for i, v in enumerate(bp) if v is not None)
    aum_start = next(i for i, v in enumerate(aum) if v is not None)
    aum_chart = {
        "ref": "EX_AUM",
        "kind": "bar_line",
        "title": (f"挂钩 MSCI 股票指数的 ETF AUM 与基点费率："
                  f"AUM US${aum[-1]:,.0f}B，费率 {bp[-1]:.2f}bp"),
        "xlabels": long_labels,
        "bar": {"name": "期末 AUM", "values": rounded(aum), "color": "BLUE"},
        "line": {"name": "期末基点费率", "values": rounded(bp), "color": "RED", "yfmt": "f2"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$B",
        "xstep": LONG_STEP,
        "note": (f"<b>这张图是这家公司的核心张力</b>：{len(aum)} 个季度里 AUM 从 "
                 f"US${aum[0]:,.0f}B 涨到 US${aum[-1]:,.0f}B"
                 f"（约 {aum[-1] / aum[0]:.1f} 倍），"
                 f"同期期末基点费率从 {max(v for v in bp if v is not None):.2f}bp 降到 {bp[-1]:.2f}bp。"
                 "资产型费用收入是两者相乘，所以规模增长里有一部分被费率稀释掉了。"
                 "<b>本页此前写着「费率序列自 2020Q2 起 —— 公司此前不披露这个数」，那句话是错的。</b>"
                 "公司一直在业绩发布的 Table 7 里印它：2020Q1 那份的五季表就同时印着 "
                 "2.71 / 2.82 / 2.81 / 2.85 / 2.88（2020Q1 与 2019 四季）。"
                 "2020Q2 起标签从 Avg. 改成 Period-End，但脚注的定义文字一字未变，"
                 "而且那一份自己的五季表里同时印着改名前后的五个数。"
                 "所以那段空白是漏采，不是政策 —— "
                 + (f"现在这条线和 AUM 一样回到 {quarters[bp_start]}。" if bp_start == aum_start
                    else f"现在这条线回到 {quarters[bp_start]}。")),
        "src_extra": "各季业绩 8-K EX-99.1 的 Table 7；费率为公司披露的期末基点费率。",
    }
    rr_chart = {
        "ref": "EX_RR",
        "kind": "lines",
        "title": (f"Run Rate 与收入的同比增速：Run Rate "
                  f"{pct_change(run_rate[-1], run_rate[-5]):+.1f}%，收入 "
                  f"{pct_change(revenue[-1], revenue[-5]):+.1f}%"),
        # The axis is the whole record and the first four quarters are holes:
        # a year-on-year line has no base there, and cutting the axis instead
        # would put this chart on a different window from every other one here.
        "xlabels": long_labels,
        "series": [
            {"name": "Run Rate 同比", "color": "NAVY",
             "values": [None] * 4 + rounded([pct_change(run_rate[i], run_rate[i - 4])
                                             for i in range(4, len(run_rate))])},
            {"name": "收入同比", "color": "BLUE",
             "values": [None] * 4 + rounded(
                 [pct_change(om["revenue_usd_m"][i], om["revenue_usd_m"][i - 4])
                  for i in range(4, len(om["revenue_usd_m"]))])},
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
        "ylab": "同比 %", "xstep": LONG_STEP,
        "note": ("Run Rate 是公司对「按当前合同价格与资产规模，未来 12 个月能确认多少收入」"
                 "的口径，因此它领先收入。两条线的<b>差</b>比各自的水平更有意义："
                 "Run Rate 高于收入时，未来几个季度的收入还有上行空间。"),
        "src_extra": "Run Rate 取自各季 Table 8，收入取自 Table 5；同比为本页自算（D）。",
    }
    flow_chart = aum_flow_chart(om)
    eps_chart = eps_gap_chart(om, stamped_block(staging, "quarter_notes", period))
    retention_chart = segment_retention_chart(om)
    highlights = ([mix_chart, flow_chart] + ([revision] if revision else [])
                  + [eps_chart, retention_chart, seg_rev_chart, seg_margin_chart])

    # ── section three: what to watch next ───────────────────────────────────
    next_ex, kpi, zero_lines = [], [], []
    if kpi_block:
        next_ex, kpi, zero_lines = next_quarter_charts(staging, kpi_block, long_labels)

    # ── section four: the long routine series ──────────────────────────────
    margin, op_margin = om["adj_ebitda_margin_pct"], om["operating_margin_pct"]
    first_quarters = []   # (year, both lines lower than the fourth quarter before)
    for index, quarter in enumerate(quarters):
        if quarter.endswith("Q1") and index:
            first_quarters.append((int(quarter[:4]), margin[index] < margin[index - 1]
                                   and op_margin[index] < op_margin[index - 1]))
    dips = [year for year, dipped in first_quarters if dipped]
    streak = 0
    while streak < len(first_quarters) and first_quarters[-1 - streak][1]:
        streak += 1
    if len(dips) == len(first_quarters):
        q1_words = "每年第一季两条线同时下沉，是薪酬税与年度激励集中在 Q1 确认所致，属于季节性而非趋势。"
    elif streak >= 2 and len(dips) == streak:
        q1_words = (f"{first_quarters[-streak][0]} 年起每年第一季两条线同时下沉，"
                    "是薪酬税与年度激励集中在 Q1 确认所致，属于季节性而非趋势；"
                    f"此前{cn_count(len(first_quarters) - streak)}个第一季没有一个是两条线同时下沉的。")
    else:
        q1_words = (f"{cn_count(len(first_quarters))}个第一季里有{cn_count(len(dips))}个"
                    "两条线同时下沉，不构成每年都有的季节性。")

    retention = om["retention_rate_pct"]
    years_full = sorted({int(q[:4]) for q in quarters
                         if all(f"{q[:4]}Q{n}" in quarters for n in range(1, 5))})
    q4_lowest, exceptions, q4_below_q3 = 0, [], True
    for year in years_full:
        by_q = {n: retention[quarters.index(f"{year}Q{n}")] for n in range(1, 5)}
        others = {n: v for n, v in by_q.items() if n != 4}
        low_q = min(others, key=others.get)
        if by_q[4] < others[low_q]:
            q4_lowest += 1
        elif by_q[4] == others[low_q]:
            exceptions.append(f"{year} 年与第{cn_ordinal(low_q)}季持平")
        else:
            exceptions.append(f"{year} 年第{cn_ordinal(low_q)}季更低")
        q4_below_q3 = q4_below_q3 and by_q[4] < by_q[3]
    retention_words = (
        ("留存率有强季节性：每年第四季是合同集中续约的季度，读数系统性低于其余三季。"
         if not exceptions else
         f"留存率有强季节性：第四季是合同集中续约的季度，{cn_count(len(years_full))}个完整年度里"
         f"有{cn_count(q4_lowest)}年第四季是全年最低（{'，'.join(exceptions)}）。")
        + ("跨年比较必须同季对同季，否则每年年底都会读出一次「恶化」。" if q4_below_q3 else
           "跨年比较必须同季对同季，否则年底常会读出一次「恶化」。"))

    abf_rr, rec_rr = om["run_rate_abf_usd_m"], om["run_rate_recurring_usd_m"]
    runs, current = [], []
    for index in range(1, len(abf_rr)):
        if abf_rr[index] < abf_rr[index - 1]:
            current.append(index)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    rec_steady = all(rec_rr[i] >= rec_rr[i - 1] for i in range(1, len(rec_rr)))
    rr_words = ("资产型那条腿随市场波动，订阅那条腿不。" if rec_steady else
                "资产型那条腿随市场波动，订阅那条腿的起伏小得多。")
    if runs:
        longest = max(len(run) for run in runs)
        worst = [run for run in runs if len(run) == longest]
        rec_rose = all(rec_rr[i] > rec_rr[i - 1] for run in worst for i in run)
        if len(worst) == 1:
            rr_words += (f"{quarters[worst[0][0]][:4]} 年的市场回撤在这张图上是唯一一次资产型 Run Rate "
                         f"连续{cn_count(longest)}季下行")
        else:
            rr_words += (f"资产型 Run Rate 连续{cn_count(longest)}季下行在这张图上出现过"
                         f"{cn_count(len(worst))}次（"
                         + "、".join(f"{quarters[run[0]]}–{quarters[run[-1]]}" for run in worst) + "）")
        rr_words += (("，而订阅腿在同期继续上行" if len(worst) == 1 else
                      f"，订阅腿在这{cn_count(len(worst))}段里都继续上行")
                     + " —— 这是这家公司抗周期性的直接读数。" if rec_rose else "。")
    routine = [
        {
            "ref": "EX_MARGIN",
            "kind": "lines",
            "title": (f"{len(om['period_labels'])} 季利润率：调整后 EBITDA {om['adj_ebitda_margin_pct'][-1]:.1f}%，"
                      f"经营 {om['operating_margin_pct'][-1]:.1f}%"),
            "xlabels": long_labels,
            "series": [
                {"name": "调整后 EBITDA 利润率", "values": rounded(om["adj_ebitda_margin_pct"]), "color": "NAVY"},
                {"name": "经营利润率", "values": rounded(om["operating_margin_pct"]), "color": "BLUE"},
            ],
            "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
            "ylab": "%", "xstep": LONG_STEP,
            "note": ("两条线的<b>缺口</b>就是折旧摊销（含无形资产摊销）等被调整掉的成本"
                     "（股权激励不在其中：公司的调整后 EBITDA 不加回它），"
                     f"{len(om['period_labels'])} 季里它从 "
                     f"{om['adj_ebitda_margin_pct'][0] - om['operating_margin_pct'][0]:.1f}pp 走到 "
                     f"{om['adj_ebitda_margin_pct'][-1] - om['operating_margin_pct'][-1]:.1f}pp。"
                     + q1_words),
            "src_extra": "各季业绩 8-K EX-99.1 的 Table 5「Consolidated」区块，均为公司披露值。",
        },
        {
            "ref": "EX_RET",
            "kind": "lines",
            "title": (f"{len(om['period_labels'])} 季总留存率：本季 {om['retention_rate_pct'][-1]:.1f}%，"
                      f"窗口内区间 {min(v for v in om['retention_rate_pct'] if v is not None):.1f}–"
                      f"{max(v for v in om['retention_rate_pct'] if v is not None):.1f}%"),
            "xlabels": long_labels,
            "series": [{"name": "总留存率", "values": rounded(om["retention_rate_pct"]), "color": "NAVY"}],
            "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
            "ylab": "%", "xstep": LONG_STEP,
            "note": retention_words,
            "src_extra": "各季业绩 8-K EX-99.1 的 Table 6；公司披露值。",
        },
        {
            "ref": "EX_RRMIX",
            "kind": "grouped_bars",
            "title": (f"Run Rate 的两条腿：订阅 US${om['run_rate_recurring_usd_m'][-1]:,.0f}M、"
                      f"资产型 US${om['run_rate_abf_usd_m'][-1]:,.0f}M"),
            "xlabels": long_labels,
            "groups": [
                {"name": "经常性订阅 Run Rate", "color": "NAVY",
                 "values": rounded(om["run_rate_recurring_usd_m"])},
                {"name": "资产型费用 Run Rate", "color": "BLUE",
                 "values": rounded(om["run_rate_abf_usd_m"])},
            ],
            "fmt": "f0c", "label_fmt": "f0c", "ylab": "US$M", "xstep": LONG_STEP,
            "note": rr_words,
            "src_extra": "各季业绩 8-K EX-99.1 的 Table 8；两条腿相加等于总 Run Rate。",
        },
    ]
    # The AUM-and-fee chart and the run-rate lead chart draw the whole record and
    # carry no finding of this quarter's own: they are the long structure the
    # quarter sits on, so they open the routine section instead of the highlights.
    routine = [aum_chart, rr_chart] + routine

    exhibits = number_exhibits(settled + highlights + next_ex + routine)
    resolve_exhibit_refs(exhibits)
    # Sliced by cumulative length, so inserting a chart into one section can
    # never silently move a chart into its neighbour.
    grouped, cursor = [], 0
    for group in (settled, highlights, next_ex, routine):
        grouped.append(exhibits[cursor:cursor + len(group)])
        cursor += len(group)
    settled_ex, highlight_ex, next_block, routine_ex = grouped

    first_table = exhibits[-1]["n"] + 1
    lead_tables = ([{"title": "上季量化阈值的结算（原始单位）",
                     "headers": ["指标", "方向", "阈值", "本季实际", "余量 D", "结算"],
                     "rows": prior_rows}] if prior_rows else [])
    tables = [{**t, "n": first_table + i} for i, t in enumerate(lead_tables + settled_tables)]
    tables.append({
        "n": first_table + len(tables),
        "title": f"近{cn_count(len(labels))}季合并损益与收入结构（公司披露值）",
        "headers": ["期间", "收入", "经常性订阅", "资产型费用", "非经常性",
                    "调整后 EBITDA", "调整后 EBITDA 利润率", "经营利润率",
                    "摊薄 EPS", "Adjusted EPS"],
        "rows": [[labels[i], f"${revenue[i]:,.1f}M", f"${rec[i]:,.1f}M", f"${abf[i]:,.1f}M",
                  f"${non[i]:,.1f}M", f"${fin['adj_ebitda_usd_m'][i]:,.1f}M",
                  f"{fin['adj_ebitda_margin_pct'][i]:.1f}%",
                  f"{fin['operating_margin_pct'][i]:.1f}%",
                  f"${fin['diluted_eps_usd'][i]:.2f}", f"${fin['adjusted_eps_usd'][i]:.2f}"]
                 for i in range(len(labels))],
    })
    if kpi:
        tables.append(threshold_audit_table(first_table + len(tables),
                                            "下季阈值与当前值（原始单位）", kpi, zero_lines))
    tables.append(ai_capex_cycle_table(first_table + len(tables)))

    # The three revenue legs: which grow faster than revenue as a whole, and
    # which sped up against the quarter before.
    legs = {"recurring": rec, "abf": abf, "nonrecurring": non}
    yoy_now = {k: pct_change(v[-1], v[-5]) for k, v in legs.items()}
    yoy_before = {k: pct_change(v[-2], v[-6]) for k, v in legs.items()}
    # Growth rates are compared at the precision the page prints them.
    faster = [k for k in legs if round(yoy_now[k], 1) > round(fin["revenue_yoy_pct"][-1], 1)]
    sped_up = [k for k in legs if round(yoy_now[k], 1) > round(yoy_before[k], 1)]
    total_sped_up = round(fin["revenue_yoy_pct"][-1], 1) > round(fin["revenue_yoy_pct"][-2], 1)
    if total_sped_up and sped_up == ["abf"]:
        abf_role, abf_title = "是全部加速的来源", "资产型费用是唯一的加速腿"
    elif faster == ["abf"]:
        abf_role, abf_title = "是三条收入腿里唯一快过总收入的", "资产型费用是唯一快过总收入的一条腿"
    elif "abf" in faster:
        others = "、".join({"recurring": "订阅", "nonrecurring": "非经常性收入"}[k]
                          for k in faster if k != "abf")
        abf_role, abf_title = f"，与{others}一样快过总收入", f"资产型费用与{others}都快过总收入"
    else:
        abf_role, abf_title = "", "三条收入腿各走各的"

    aum_record = aum[-1] == max(v for v in aum if v is not None)
    fee_fell = bp[-1] < bp[-2]
    fee_low = bp[-1] == min(v for v in bp if v is not None)
    fee_ties = sum(1 for v in bp if v == bp[-1]) > 1
    headline = (
        f"收入 US${revenue[-1]:,.1f}M、同比 {signed(fin['revenue_yoy_pct'][-1])}，"
        f"资产型费用同比 {signed(pct_change(abf[-1], abf[-5]))}"
        + ((abf_role if abf_role.startswith("，") else f" {abf_role}") + "；" if abf_role else "；")
        + (f"挂钩 ETF 的 AUM 创 US${aum[-1]:,.0f}B 新高，" if aum_record else
           f"挂钩 ETF 的 AUM 为 US${aum[-1]:,.0f}B，")
        + ("但" if fee_fell and aum_record else "")
        + (f"期末基点费率同时降到 {bp[-1]:.2f}bp" if fee_fell else f"期末基点费率为 {bp[-1]:.2f}bp")
        + ((f"、与更早一季并列 {long_labels[bp_start]} 以来最低；" if fee_ties else
            f"、为 {long_labels[bp_start]} 以来最低；") if fee_low else "；")
        + guidance_headline(moves))

    record_title = ("费用指引靠修订，现金流指引靠低估"
                    if oe_last["inside"] > oe_first["inside"]
                    and 2 * fcf_first["above"] > fcf_first["n"] and 2 * fcf_last["above"] > fcf_last["n"]
                    else "费用与现金流指引：年初那次与年末那次")
    first_word = "年初第一次" if opens_with_first_release(hist, "operating_expense") else "年内第一次"
    record_body = (
        f"{cn_count(oe_n)}个完整年度里，营业费用对<b>当年最后一次</b>指引 {oe_last['inside']} 次"
        f"{'全部' if oe_last['inside'] == oe_n else ''}落在区间内，对<b>{first_word}</b>指引"
        f"{'只有' if oe_first['inside'] < oe_last['inside'] else '是'} {oe_first['inside']} 次。"
        + (f"自由现金流两种口径都是 {fcf_last['above']} 次穿出上限。"
           if fcf_first["above"] == fcf_last["above"] else
           f"自由现金流对第一次指引 {fcf_first['above']} 次、对最后一次 {fcf_last['above']} 次穿出上限。"))
    flow_market, flow_inflow = om["etf_market_appreciation_usd_b"], om["etf_cash_inflows_usd_b"]
    flow_change = flow_market[-1] + flow_inflow[-1]
    flow_words = (f"但本季挂钩 ETF 的 AUM 增量里 {flow_market[-1] / flow_change * 100:.1f}% 来自市场升值，"
                  f"现金净流入 US${flow_inflow[-1]:,.0f}B、上季 US${flow_inflow[-2]:,.0f}B。"
                  if flow_change > 0 and flow_market[-1] > flow_inflow[-1] else "")
    seg_now = {name: om[key][-1] for name, key, _, _ in RETENTION_LINES[1:]}
    weakest = min(seg_now, key=seg_now.get)
    total_retention = om["retention_rate_pct"][-1]
    articles = [
        f'<article><span>记录</span><b>{record_title}</b><p>{record_body}</p></article>',
        f'<article><span>来源</span><b>{abf_title}</b>'
        f'<p>US${abf[-1]:,.1f}M、同比 {signed(pct_change(abf[-1], abf[-5]))}，'
        f'占收入 {abf[-1] / revenue[-1] * 100:.1f}%；订阅腿同比 '
        f'{signed(pct_change(rec[-1], rec[-5]))}。{flow_words}</p></article>',
        '<article><span>代价</span><b>规模在涨，过路费率在降</b>'
        f'<p>AUM {len(aum)} 季涨约 {aum[-1] / aum[0]:.1f} 倍，期末基点费率从 {bp[0]:.2f}bp 降到 '
        f'{bp[-1]:.2f}bp，资产型收入是两者相乘。</p></article>'
        if aum[-1] > aum[0] and bp[-1] < bp[bp_start] else
        '<article><span>代价</span><b>规模与过路费率</b>'
        f'<p>AUM {len(aum)} 季从 US${aum[0]:,.0f}B 到 US${aum[-1]:,.0f}B，期末基点费率从 {bp[bp_start]:.2f}bp '
        f'到 {bp[-1]:.2f}bp，资产型收入是两者相乘。</p></article>',
    ]
    if seg_now[weakest] < total_retention:
        weak_key = next(key for name, key, _, _ in RETENTION_LINES if name == weakest)
        articles.append(
            f'<article><span>分部</span><b>总留存率 {total_retention:.1f}% 盖住了 {weakest} 的 {seg_now[weakest]:.1f}%</b>'
            f'<p>{weakest} 去年同季是 {om[weak_key][-5]:.1f}%；四个分部里最高的 '
            f'{max(seg_now, key=seg_now.get)} 为 {max(seg_now.values()):.1f}%。</p></article>')

    audit_words = {"unaudited": "未审计", "audited": "已审计"}[latest["audit_status"]]
    fcf_identity = sum(
        1 for year in finished
        if abs(hist["items"]["op_cash_flow"]["by_year"][str(year)]["actual"]
               - hist["items"]["capex"]["by_year"][str(year)]["actual"]
               - hist["items"]["free_cash_flow"]["by_year"][str(year)]["actual"]) <= TOLERANCE)
    releases_total = sum(len(dates) for dates in hist["releases_by_year"].values())
    first_year = min(hist["years"])
    late_starts = []
    for name, key in LATE_SERIES:
        start = next(i for i, v in enumerate(om[key]) if v is not None)
        if start:
            late_starts.append((name, quarters[start]))
    return {
        "schema_version": "quarterly-dashboard/msci-v1",
        "page": {"slug": "msci", "language": "zh-CN"},
        "company": {
            "ticker": "MSCI",
            "name": "MSCI Inc.",
            "group": "financial_data_indices",
            "accounting_standard": "US GAAP",
        },
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · MSCI",
        "title": f"MSCI Inc. (MSCI)：{period} 季报仪表盘",
        "subtitle": (f"截至 {latest['period_end']} · 发布 {latest['release_date']} · US GAAP · {audit_words} · "
                     "自然年财年，季度标注与财年一致"),
        "headline": headline,
        "brief": (
            f'<h4>本季{cn_count(len(articles))}条主线</h4><div class="takeaway-grid">'
            + "".join(articles)
            + '</div>'),
        "source": (f'Source: <a href="{release["url"]}" rel="noopener">'
                   f'MSCI {quarter_words(period)}业绩新闻稿（8-K EX-99.1）</a>'
                   f'{periodic_report_words(staging)}。'),
        "source_url": release["url"],
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {"id": "settled", "title": "一、上季跟踪指标兑现了吗",
             "description": (
                 ("先结上季留下的："
                  + (f"上季本地分析稿的{cn_count(len(closure_block['items']))}条待验证问题闭环了几条"
                     if closure_block else "")
                  + ("、" if closure_block and prior_block else "")
                  + ("上季第 8 节设的量化阈值守住了几条" if prior_block else "")
                  + "；再看公司自己的指引兑现记录。" if closure_block or prior_block else
                  "本季的分析稿没有核验上季留下的问题与阈值，本节只结算公司自己的指引。")
                 + "MSCI 的指引是年度的，而且只覆盖成本与现金 —— 费用、税率、"
                 "资本开支、经营现金流与自由现金流，从不指引收入与 EPS。"
                 f"所以指引这一段结清的是{cn_count(len(finished))}个完整年度的费用与现金记录，"
                 "并且把「年初那次」与「年末那次」分开算，因为两者的答案不一样。"),
             "exhibits": settled_ex},
            {"id": "quarter_highlights", "title": "二、本季重点",
             "description": (f"本季的{cn_count(len(highlight_ex))}件事，一图一个结论：三条收入腿、挂钩 ETF 的 AUM 增量从哪来、"
                             + (f"FY{moves['year']} 指引的修订、" if revision else "")
                             + "摊薄与调整后 EPS 的差、四个分部的留存率，以及四个分部的收入与利润率。"
                             "本季分析稿还讲了单季自由现金流与资本开支，本页没有收季度现金流序列，所以没有单独成图；"
                             "全年现金流对指引的兑现见第一节。"),
             "exhibits": highlight_ex},
            {"id": "next_quarter", "title": "三、下季要跟踪什么",
             "description": (("本季本地分析稿第 8 节设的阈值，统一用「距阈值余量」口径：风险线（减仓 / 警示）与加仓 / 稳定线同列，"
                              "正值都表示在有利一侧；有季度序列的逐条画出历史与阈值线"
                              + ("，FY 指引那几条没有季度序列、只进柱图" if any(e["reads"].startswith("guide_") for e in kpi)
                                 else "")
                              + ("，阈值为零的那条只画在它的序列图上" if zero_lines else "")
                              + "。")
                             if kpi else "本季没有设定下季阈值，本节没有图。"),
             "exhibits": next_block},
            {"id": "routine", "title": "四、长期常规跟踪",
             "description": ("MSCI 专属的常规序列"
                             + (f"，全部回到 {long_labels[0]}"
                                if all(ex["xlabels"][0] == long_labels[0] for ex in routine_ex) else "")
                             + "：挂钩 ETF 的 AUM 与期末基点费率、Run Rate 对收入的领先、利润率与它的调整缺口、"
                             "留存率的季节性，以及 Run Rate 的两条腿。"),
             "exhibits": routine_ex},
        ],
        "tables": tables,
        "notes": [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "MSCI 财年即自然年，本页季度标注与公司自己的口径一致，无需换算。",
            "第一节末尾的公司指引记录结清的是年度指引而不是季度指引：MSCI 在每季业绩新闻稿里给出并更新一次全年 Guidance 表，但从不给季度指引，也从不指引收入与每股收益。本站其他公司页结清的多是季度收入区间，本页不是，差别源于公司披露口径而非编辑选择。",
            ("全年 Guidance 表自 2020 年第三季度业绩新闻稿起以表格形式发布，此前同一组指引以正文段落给出。"
             f"本页的指引记录起于 FY{first_year} 的第一份发布（{hist['releases_by_year'][str(first_year)][0]}），"
             f"共 {releases_total} 次发布、覆盖 FY{first_year} 至 FY{max(hist['years'])} "
             f"{cn_count(len(hist['years']))}个年度，其中{cn_count(len(finished))}个年度已完结。"),
            f"同一年的指引在四次发布中会被修订，本页把「年内第一次」与「当年最后一次」分别对全年实际结清，两个答案不同：营业费用对最后一次是 {oe_last['inside']} 年落在区间内（共 {oe_n} 个已完结年），对第一次只有 {oe_first['inside']} 年。把这两者混为一谈，会把修订的功劳读成预测的准确。",
            ("全年实际值一律取次年第一季发布（各年 Q4 业绩新闻稿）中 Table 11 与 Table 12 的 Year Ended 列，不使用年初至今列差分。"
             + (f"自由现金流 = 经营现金流 − 资本开支，{cn_count(fcf_identity)}个年度逐年核对该恒等式均成立。"
                if fcf_identity == len(finished) else
                f"自由现金流 = 经营现金流 − 资本开支，{cn_count(len(finished))}个年度里有{cn_count(fcf_identity)}个核对成立。")),
            "各表的金额单位在不同年份、不同表之间在千美元、百万美元与十亿美元之间切换，本页逐表读该表自己的单位表头后统一换算为百万美元；AUM 保留十亿美元。",
            ("2021 年之前 ESG 与 Real Estate、Burgiss 合并为一个 All Other 分部；2021-01-01 起 ESG 单列为报告分部并改名 ESG and Climate"
             "（2025 年起的发布称 Sustainability and Climate），Real Estate 与 Burgiss 并入 All Other – Private Assets，"
             "公司在 2021-02-23 的 8-K 里按新分部重述了 2020 年四个季度。"
             + ("分部图的窗口全部落在拆分之后；" if after_split else "")
             + f"{len(om['period_labels'])} 季的合并口径序列不受影响"
             + (f"，分部相加等于合并收入在本页收录分部收入的 {len(labels)} 季均成立。" if segment_sum_ok else "。")),
            ((f"期末基点费率与 AUM 一样从 {quarters[bp_start]} 起画" if bp_start == aum_start else
              f"期末基点费率从 {quarters[bp_start]} 起画，不向前回补")
             + ("；" + "、".join(f"{name}从 {start}" for name, start in late_starts)
                + " 起画，不向前回补：那是分部单列或公司开始按这个口径印数的那一季。" if late_starts else "。")),
            "本页不发布市场一致预期：没有可核对的、带日期的公开来源，站点规则允许发布带日期的「市场预期」对照点，但不允许凭印象填一个数。本页同样不发布评级、目标价与估值。",
            "本页只发布公司披露值、可复算的简单派生值；D 标记代表 Derived / 自算。",
            "核对抽屉最后那张「AI capex 循环」是全站共用的跨页对照块，在每一页都逐字节相同，不是对 MSCI 的判断。它追的是四家云厂现金资本开支 → NVDA 数据中心收入 → TSM 晶圆这条链，MSCI 不在这条链的任何一环上：它既不是其中的支出方，也不是供应方。把它放在这里是为了让读者在任意一页都能查到同一份上下游对照。它在折叠的抽屉里，不参与本页的论证。",
            f"本页已知未接入：非 ETF 指数产品与固定收益产品挂钩的资产规模（公司只按季披露挂钩其股票指数的 ETF AUM）、分部层面的资本开支与现金流（公司只在合并层面披露）、客户集中度，以及 {quarter_words(period)}之后的任何数据（本页数据截至 {latest['release_date']} 的申报）。",
            "业绩电话会文字稿仅链接官方 IR 与 SEC 托管版本，公开仓不复制原件或逐字内容。",
        ],
        "footer": "MSCI quarterly results · 数据来自 MSCI 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "msci.js"), payload, "msci")
    shell_dir = ROOT / "msci"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("MSCI", "msci"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"MSCI page: {charts} charts in {len(payload['sections'])} sections "
          f"+ {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
