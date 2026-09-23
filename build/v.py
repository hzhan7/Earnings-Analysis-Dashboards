#!/usr/bin/env python3
"""Build the V (Visa) quarterly-results page.

Same four-part, chart-led shape as the other company pages (上季兑现 → 本季重点
→ 下季跟踪 → 长期常规).  Visa's fiscal year ends 30 September, so every label
here is the calendar quarter the fiscal one covers: the quarter ended
2026-06-30 is the company's FY2026 Q3 and this page's ``Q2 2026``.

Two things make this page different from the guidance-record pages.

The first is a sourcing limit rather than an editorial choice.  **Visa has not
filed a numeric QUARTERLY outlook** in the releases this page has read: every
Financial Outlook was fiscal-full-year, so the object the Amazon, Cadence and
Synopsys pages are built on -- a next-quarter range and the quarter that settles
it -- does not exist here.  The full-year outlook is disappearing too: numeric on
some metrics through fiscal 2020, present but explicitly withheld in fiscal
2020-2021, absent for most of 2022-2023, reduced in fiscal 2024 to one sentence
pointing at an earnings presentation that is not archived on EDGAR, and gone
from every release after 2025-01-30.  The page says so instead of transcribing
webcast material that cannot be checked against a second source.

Deliberately absent: a count of how many releases carried a number.  A sampled
tally does not generalise to every release since the first guided year's
opening one, so the page describes the eras and leaves the arithmetic alone.

The second is what Visa *did* guide, and it happens to be the number this whole
page is about.  "Client incentives as a percent of gross revenues" was given as
a numeric range in the release that opened every fiscal year from 2013 to 2020
(the effective tax rate was given as a range too, in some years).  The record's
verdicts, counts and extremes are recomputed from ``series/v.json`` on each
build; none is typed here.

That rate is the page's spine, and it is a filed figure every quarter back to
2012: the four gross revenue lines and the client-incentive contra line are
disclosed separately, so the ratio is arithmetic on disclosed numbers, not an
estimate.

The page is rolled by editing ``series/v.json`` alone.  What only one quarter
has -- the closure of the last report's questions (``followup_closure``), the
settlement of the thresholds its section 8 set (``prior_kpi_settlement``), next
quarter's thresholds (``next_kpi``), the quarter's one-off items and sentences --
sits in blocks stamped with the quarter (``board.stamped_block``); ``_checks`` is
a separate reading of the quarter's release and of the two reports, which the
tests hold the page to and this builder never reads.

Section one and section three are the two ends of one cycle, so they share one
renderer: the entries section three draws against today's readings are, a
quarter later, moved into ``prior_kpi_settlement`` and drawn against that
quarter's -- ``threshold_charts`` with ``mode="prior"``.  Every quarter after
``SETTLED_FROM`` must carry that block; a roll that forgot it would drop last
quarter's thresholds from the page without a word, so the build stops.

Published numbers are company-reported or transparent arithmetic.  Market
expectations are labelled as such, with no broker attribution.
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import (  # noqa: E402
    ai_capex_cycle_table,
    cn_count,
    delivery_band,
    cn_fraction,
    cn_ordinal,
    fill_story,
    headroom,
    headroom_exhibit,
    latest_block,
    number_exhibits,
    stamped_block,
    threshold_table,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "v.json"
DATA_DIR = ROOT / "data"

# One tick per year keeps the long quarterly axes readable.
LONG_STEP = 4


# The site's window starts 2016Q1. `revenue_lines_usd_m` runs from Q4 2012, so
# the charts that used to take a hand-picked tail of 13 take this instead --
# one number, derived from the target rather than typed next to each chart.
def window_from_2016(staging: dict) -> int:
    quarters = staging["revenue_lines_usd_m"]["quarters"]
    return len(quarters) - quarters.index("Q1 2016")


def compact_period(period: str) -> str:
    """``'Q2 2026'`` → ``'Q2'26'``."""
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    """``+14.4%`` / ``-0.58pp``; a value that rounds to nothing prints unsigned
    (``0.00pp``) rather than as ``-0.00pp``."""
    if round(value, digits) == 0:
        return f"{0:.{digits}f}{suffix}"
    return f"{value:+.{digits}f}{suffix}"


def incentive_effect(gross: float, now: float, then: float, *, short: bool = False) -> str:
    """What the year-on-year move in the incentive rate did to net revenue by itself.

    A higher rate takes net revenue away; a lower one leaves more of it with
    Visa -- 「让出」 read both ways, so the words say which.
    """
    amount = gross * (now - then) / 100
    if round(amount) == 0:
        return "对净收入的影响不到 US$1M"
    if amount > 0:
        return f"单独吃掉约 US${amount:,.0f}M 净收入" if short else f"单独吃掉了约 US${amount:,.0f}M 的净收入"
    return f"单独多留下约 US${-amount:,.0f}M 净收入" if short else f"单独多留下了约 US${-amount:,.0f}M 的净收入"


def rounded(values: list[float | None], digits: int = 6) -> list[float | None]:
    return [None if value is None else round(value, digits) for value in values]


def usd_m(value: float) -> str:
    """``−US$500M`` / ``US$66M``: the sign sits outside the currency symbol."""
    return f"{'−' if value < 0 else ''}US${abs(value):,.0f}M"


def plain_text(html: str) -> str:
    """Strip inline markup for the two slots the renderer escapes rather than parses.

    `assets/page.js` writes exhibit notes with `innerHTML` but runs section
    descriptions and the 口径与方法说明 list through `esc()`, so a `<b>` that
    reads as emphasis on a chart caption reaches the reader as the literal
    characters `<b>` in those two places. The same sentence is often wanted in
    both, so it is written once with markup and stripped here.
    """
    return re.sub(r"<[^>]+>", "", html)


def joined(items: list[str]) -> str:
    """「A」 / 「A 与 B」 / 「A、B 与 C」."""
    return items[0] if len(items) == 1 else "、".join(items[:-1]) + " 与 " + items[-1]


def fiscal_words(label: str) -> str:
    """``'FY2026Q3'`` → ``'FY2026 Q3'``."""
    return f"{label[:6]} {label[6:]}"


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


def release_source(staging: dict) -> dict:
    """This quarter's own release in `sources`, found by its label."""
    label = f"Visa {fiscal_words(staging['fiscal_labels'][-1])} 业绩新闻稿"
    found = next((item for item in staging["sources"] if item["label"].startswith(label)), None)
    if found is None:
        raise ValueError(f"series `sources` has no entry for the {label}: add this "
                         "quarter's release with the roll")
    return found


def periodic_report_words(staging: dict) -> str:
    """「与截至 … 的 10-Q」 when `sources` carries the quarter's own 10-Q / 10-K."""
    end = staging["period_ends"][-1]
    for form in ("10-Q", "10-K"):
        if any(item["label"].startswith(f"Visa 截至 {end} 的 {form}") for item in staging["sources"]):
            return f"与截至 {end} 的 {form}"
    return ""


SOURCE_FILINGS = (
    "四条毛收入线（Service / Data processing / International transaction / Other）与"
    "Client incentives 抵减线均为各季 10-Q、10-K 收入分解附注里的<b>申报值</b>，"
    "本页的激励率 = 激励 ÷ 四条毛收入线之和，是申报值之间的除法，不含任何估计。"
)


def no_guidance_note(record: dict) -> str:
    return (
        "<b>Visa 从不在申报文件里给<u>季度</u>数字指引。</b>"
        "它历史上给过的 Financial Outlook 一律是<b>财年</b>口径，从来没有过下一季度的区间，"
        "因此其他几页那种「本季指引 → 本季实际」的逐季兑现对象，在 Visa 这里根本不存在。"
        "财年口径的那部分也在退场，分四个阶段："
        f"FY{record['first_guided_fiscal_year']}–FY{record['stopped_after_fiscal_year']} "
        "有 Financial Outlook，其中客户激励率与有效税率是数字区间、"
        "收入与 EPS 多为「mid-teens」这类文字区间；"
        "FY2020–FY2021 保留小节但明确不给指引；"
        "FY2022–FY2023 大部分季度连小节都没有；"
        "FY2024 只剩一句话，指向一份<b>未在 EDGAR 归档</b>的 earnings presentation；"
        "2025-01-30 之后的历次新闻稿连这句话也没有了。"
        "把无法与第二个来源核对的电话会内容抄成一份十几季的记录，正是本仓要避免的做法。"
    )


def release_count_words(staging: dict, facts: dict) -> str:
    """How many releases a tally of the outlook eras would have to read.

    One per quarter of the revenue-line record, plus the release that opened the
    first guided year: it reported the quarter before the record starts.
    """
    lines = staging["revenue_lines_usd_m"]
    first = facts["entries"][0]
    if lines["fiscal_labels"][0] != f"FY{first['fiscal_year']}Q1":
        raise ValueError("revenue_lines_usd_m no longer starts at the first guided year's first quarter")
    return (f"要给出这样的计数必须把 FY{first['fiscal_year']} 开局那份（{first['released']}）起的全部 "
            f"{len(lines['quarters']) + 1} 份新闻稿逐份读完")


def guidance_facts(staging: dict) -> dict:
    """The incentive-rate record, counted once for every sentence that uses it."""
    record = staging["incentive_guidance"]
    entries = record["entries"]
    years = [entry["fiscal_year"] for entry in entries]
    if years != list(range(years[0], years[0] + len(years))) or years[0] != record["first_guided_fiscal_year"] \
            or years[-1] != record["stopped_after_fiscal_year"]:
        raise ValueError("incentive guidance entries no longer run first_guided..stopped_after without a gap")
    below = [e["fiscal_year"] for e in entries if e["actual_pct"] < e["lo"]]
    inside = [e["fiscal_year"] for e in entries if e["lo"] <= e["actual_pct"] <= e["hi"]]
    above = [e["fiscal_year"] for e in entries if e["actual_pct"] > e["hi"]]
    gap = {e["fiscal_year"]: e["actual_pct"] - (e["lo"] + e["hi"]) / 2 for e in entries}
    return {"entries": entries, "years": years, "below": below, "inside": inside, "above": above,
            "gap": gap, "first": years[0], "last": years[-1]}


# ── section one: the one number Visa guided every year ────────────────────────
def incentive_guidance_charts(staging: dict, facts: dict) -> list[dict]:
    """Visa's longest-running filed forward number, against what it delivered.

    ``Client incentives as a percent of gross revenues`` appeared as a numeric
    range in the "Financial Outlook" block of the release that opened each
    fiscal year from 2013 through 2020, and nowhere since.  The floor is the
    quarterly series, not the guidance: gross revenue and the incentive line
    start at FY2013Q1, so FY2013 is the first year whose delivered rate can be
    computed on the same basis.  Both legs are filed: the guided range from the
    release, the delivered rate from that year's 10-K revenue note (four gross
    lines and the contra line, disclosed separately).
    """
    record = staging["incentive_guidance"]
    entries = facts["entries"]
    labels = [f"FY{year}" for year in facts["years"]]
    low = [entry["lo"] for entry in entries]
    high = [entry["hi"] for entry in entries]
    actual = [entry["actual_pct"] for entry in entries]

    # The one year whose two legs sit on different bases, written from the
    # record rather than typed beside it -- if a second one is ever added this
    # sentence grows by itself instead of going quietly out of date.
    breaks = "".join(
        f"<b>FY{entry['fiscal_year']} 有一处口径断点。</b>"
        + entry["basis_break"]["what"]
        + f"剔除该季后的 {entry['basis_break']['clean_quarters']} 季比率为 "
        + f"{entry['basis_break']['clean_actual_pct']:.2f}%，全年为 "
        + f"{entry['actual_pct']:.2f}%，"
        + ("两者落在同一侧，所以这一年的判定不依赖那个断点。"
           if entry["basis_break"]["verdict_unchanged"]
           else "<b>两者的判定不同，这一年只能当作存疑</b>。")
        for entry in entries if "basis_break" in entry
    )

    below, inside, above = facts["below"], facts["inside"], facts["above"]
    # The years the page used to leave out (it drew FY2017-FY2020 only); what
    # the note says about them is read off them.
    early = [entry for entry in entries if entry["fiscal_year"] < 2017]
    early_below = [(entry["actual_pct"] - entry["lo"], entry["fiscal_year"]) for entry in early
                   if entry["actual_pct"] < entry["lo"]]
    deepest = min(early_below) if early_below else None

    band = delivery_band(
        "EX_INC_BAND", "客户激励率", labels, low, high, actual,
        fmt="pct1", ylab="激励 / 毛收入", unit="%", venue="业绩发布",
        timing="该财年<b>开始时</b>", period_word="年",
        src_extra=(
            "指引区间逐字取自各财年开局那份业绩 8-K 的「Financial Outlook」块中"
            "「Client incentives as a percent of gross revenues」一行；"
            "实际值取自该财年 10-K 收入附注里的四条毛收入线与激励线。"
        ),
        extra_note=(
            "<b>方向要读反过来</b>：这条线低于区间是<b>好事</b> —— 返给客户的钱比承诺的少。"
            f"{len(entries)} 年里 {len(below)} 年跌破下限、{len(inside)} 年落在区间内、"
            f"{len(above)} 年高于上限。"
            + ("Visa 在自己愿意给数字的那些年里，从没有超发过激励。" if not above else "")
            + ((f"<b>这个结论把窗口从{cn_count(len([e for e in entries if e['fiscal_year'] >= 2017]))}年"
                f"拉到{cn_count(len(entries))}年之后仍然成立</b> —— " if not above else "")
               + f"新接进来的 FY{early[0]['fiscal_year']}–FY{early[-1]['fiscal_year']} 里最大的一次是 "
               f"FY{deepest[1]} 的 {deepest[0]:+.2f}pp，方向仍然是少发。" if deepest else "")
            + breaks
        ),
    )

    gap = [facts["gap"][year] for year in facts["years"]]
    positive = [year for year in facts["years"] if facts["gap"][year] > 0]
    stopped = record["stopped_after_fiscal_year"]
    since = int(staging["fiscal_labels"][-1][2:6]) - stopped
    deviation = {
        "ref": "EX_INC_DEV",
        "kind": "grouped_bars",
        "title": (
            f"实际激励率相对指引中值的偏离："
            f"{len(entries)} 年里 {sum(1 for value in gap if value < 0)} 年为负，平均 "
            f"{sum(gap) / len(gap):+.2f}pp"
        ),
        "xlabels": labels,
        "groups": [{
            "name": "实际激励率 − 指引中值",
            "color": "BLUE",
            "values": rounded(gap),
        }],
        "bar_labels": True,
        "fmt": "pp1",
        "label_fmt": "pp1",
        "ylab": "pp vs 指引中值",
        "note": (
            "负值 = 激励率低于公司自己给的中值，即少返给客户、多留给自己。"
            f"最大的一次是 {labels[gap.index(min(gap))]} 的 {min(gap):+.2f}pp。"
            + (f"<b>本页此前只画 FY2017–FY2020 四年，并印着「四年全部为负」——"
               f"那句话当时就是错的</b>，FY2020 的偏离是 {facts['gap'][2020]:+.2f}pp，为正。"
               if 2020 in facts["gap"] and facts["gap"][2020] > 0 else "")
            + f"{cn_count(len(entries))}年的窗口里为正的有{cn_count(len(positive))}年。"
            "<b>然后这条指引就消失了。</b>"
            f"公司在 FY{stopped} 之后再没有给过这个数字，"
            f"而同一个比率在其后{cn_count(since)}年里"
            + ("继续往上走" if staging["revenue_lines_usd_m"]["incentive_rate_pct"][-1] > entries[-1]["actual_pct"]
               else "没有再高过 FY%d 的 %.2f%%" % (stopped, entries[-1]["actual_pct"]))
            + " —— 见第四节的长序列。"
        ),
        "src_extra": "同上；单位是百分点，与收入类图的百分比不可直接比大小。",
    }
    return [band, deviation]


# ── section four: the long filed record ──────────────────────────────────────
def fiscal_year_rates(lines: dict, key: str | None = None) -> dict[int, float]:
    """Full fiscal years only: incentive rate, or one line's share of gross revenue."""
    sums: dict[int, list[float]] = {}
    counts: dict[int, int] = {}
    for i, label in enumerate(lines["fiscal_labels"]):
        year = int(label[2:6])
        num = -lines["client_incentives"][i] if key is None else lines[key][i]
        sums.setdefault(year, [0.0, 0.0])
        sums[year][0] += num
        sums[year][1] += lines["gross_revenue"][i]
        counts[year] = counts.get(year, 0) + 1
    return {year: a / b * 100 for year, (a, b) in sums.items() if counts[year] == 4}


def incentive_rate_long(staging: dict) -> dict:
    lines = staging["revenue_lines_usd_m"]
    labels = [compact_period(period) for period in lines["quarters"]]
    rate = lines["incentive_rate_pct"]
    low_at = labels[rate.index(min(rate))]
    high_at = labels[rate.index(max(rate))]
    yearly = fiscal_year_rates(lines)
    years = sorted(yearly)
    one_way = all(yearly[b] > yearly[a] for a, b in zip(years, years[1:]))
    recent = rate[-8:]
    gross_growth = lines["gross_revenue"][-1] / lines["gross_revenue"][0] - 1
    span_years = (len(lines["quarters"]) - 1) // 4
    return {
        "ref": "EX_INC_LONG",
        "kind": "gs_line",
        "title": (
            f"客户激励率 {len(rate)} 个季度从 {rate[0]:.1f}% {'升到' if rate[-1] > rate[0] else '降到'} "
            f"{rate[-1]:.1f}%："
            f"每一美元毛收入返给客户的钱{'多' if rate[-1] > rate[0] else '少'}了 {abs(rate[-1] - rate[0]):.1f} 美分"
        ),
        "xlabels": labels,
        "xstep": LONG_STEP,
        "values": rounded(rate),
        "legend": "Client incentives / 毛收入",
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "占毛收入比",
        "note": (
            f"区间 {min(rate):.1f}%（{low_at}）到 {max(rate):.1f}%（{high_at}）。"
            "这是本页最重要的一条线，也是八个季度的窗口<b>看不出来</b>的那种线："
            + (f"近八季它在 {int(min(recent))}%–{int(max(recent)) + 1}% 之间小幅摆动，像噪声；"
               if int(max(recent)) + 1 - int(min(recent)) <= 2 else "")
            + (f"拉到 {len(rate)} 季才看得出这是一条走了{cn_count(span_years)}年的单向斜坡"
               f"（按财年算，FY{years[0]}–FY{years[-1]} 每一年都比上一年高）。" if one_way else
               f"拉到 {len(rate)} 季才看得出它的长期走向。")
            + "它衡量的是网络生意的定价权 —— 分子是为留住发卡行与收单方付出的对价，"
            "分母是在没有这些对价之前 Visa 本可以收到的钱。"
            + ("<b>比率上行不等于绝对额失控</b>：同期毛收入本身涨了近四倍，"
               "激励是跟着规模一起长的，这条线说的是<b>每一美元</b>里被让渡的份额在变大。"
               if 3.5 <= gross_growth < 4 and rate[-1] > rate[0] else "")
            + SOURCE_FILINGS
        ),
        "src_extra": "各季 10-Q / 10-K 收入分解附注。",
    }


def previous_quarter(period: str) -> str:
    """``'Q1 2016'`` → ``'Q4 2015'``."""
    quarter, year = int(period[1]), int(period[-4:])
    return f"Q4 {year - 1}" if quarter == 1 else f"Q{quarter - 1} {year}"


def service_yield_long(staging: dict) -> dict:
    """Service revenue over the payments volume it is recognised on -- the prior quarter's.

    The 10-Q's MD&A prints the prior quarter's nominal payments volume in
    dollars, the base the company says service revenue is assessed on, so this
    is the one revenue-to-volume pair the filings line up. The ratio is in basis
    points of volume. Visa Europe (acquired June 2016) joins the denominator
    with its April-June 2016 volume; that step is named, not counted back from
    the end.
    """
    lines = staging["revenue_lines_usd_m"]
    volumes = staging["operating_volumes"]
    volume = dict(zip(volumes["payments_volume_quarters"], volumes["nominal_payments_volume_usd_b"]))
    window = lines["quarters"][lines["quarters"].index("Q1 2016"):]
    quarters = [q for q in window if previous_quarter(q) in volume]
    if not quarters or quarters != window[:len(quarters)]:
        raise ValueError("operating_volumes has a hole in the 2016 window: each quarter's service "
                         "revenue needs the prior quarter's nominal payments volume")
    bps = [lines["service"][lines["quarters"].index(q)] / volume[previous_quarter(q)] * 10
           for q in quarters]
    now = "本季" if quarters[-1] == lines["quarters"][-1] else quarters[-1]
    step = quarters.index("Q3 2016") if "Q3 2016" in quarters[1:] else None
    return {
        "ref": "EX_SVC_YIELD",
        "kind": "gs_line",
        "title": (
            f"Service revenue ÷ 上一季名义支付额：{now} {bps[-1]:.2f} 个基点"
            + (f"，{len(bps)} 个季度里最高" if bps[-1] >= max(bps) else
               f"，{len(bps)} 个季度里最低" if bps[-1] <= min(bps) else
               f"（{len(bps)} 个季度区间 {min(bps):.2f}–{max(bps):.2f}）")
        ),
        "xlabels": [compact_period(q) for q in quarters],
        "xstep": LONG_STEP,
        "values": rounded(bps),
        "legend": "Service revenue / 上一季名义支付额",
        "fmt": "f2",
        "yfmt": "f2",
        "label_fmt": "f2",
        "ylab": "基点（0.01%）",
        "note": (
            "分子是当季 Service revenue，分母是公司据以确认它的上一季名义支付额"
            "（10-Q 的 MD&A 按季印着美元金额；4–6 月那一季没有单独一栏，取 10-K 十二个月栏减 6 月 10-Q 九个月栏），"
            "比率是两者相除的自算值 D。"
            + (f"{quarters[step]} 起分母并入 2016 年 6 月收购的 Visa Europe，比率从 {bps[step - 1]:.2f} 掉到 "
               f"{bps[step]:.2f}（这一格与下一格的分母还含 2016 年底起不再计入的欧洲 co-badged 支付额），"
               + (f"此后回升到{now}的 {bps[-1]:.2f}，已高过并入前。" if bps[-1] > bps[step - 1] else
                  f"{now}是 {bps[-1]:.2f}，仍低于并入前。")
               if step is not None else "")
        ),
        "src_extra": "分子：各季 10-Q / 10-K 收入分解附注；分母：各季 10-Q MD&A 名义支付额表，逐格出处在 series 里。",
    }


def revenue_mix_long(staging: dict) -> dict:
    lines = staging["revenue_lines_usd_m"]
    labels = [compact_period(period) for period in lines["quarters"]]
    gross = lines["gross_revenue"]
    shares = {
        name: [value / total * 100 for value, total in zip(lines[key], gross)]
        for name, key in (
            ("Service", "service"),
            ("Data processing", "data_processing"),
            ("International transaction", "international_transaction"),
            ("Other", "other"),
        )
    }
    dp = shares["Data processing"]
    intl = shares["International transaction"]
    trough = intl.index(min(intl))
    # The last quarter before the pandemic reached cross-border travel is named,
    # not counted back from the end: an index from the end moves every roll.
    before = lines["quarters"].index("Q4 2019")
    y2019 = [intl[i] for i, q in enumerate(lines["quarters"]) if q.endswith("2019")]
    after = [(intl[i], i) for i in range(trough + 1, len(intl))]
    back = [(value, i) for value, i in after if value >= min(y2019)]
    dp_years = fiscal_year_rates(lines, "data_processing")
    dp_order = sorted(dp_years)
    dp_peak = max(dp_years, key=dp_years.get)
    return {
        "ref": "EX_MIX_LONG",
        "kind": "lines",
        "title": (
            f"四条毛收入线各自占毛收入的比重：Data processing 从 {dp[0]:.1f}% "
            f"{'升到' if dp[-1] > dp[0] else '降到'} {dp[-1]:.1f}%，"
            f"Service 从 {shares['Service'][0]:.1f}% "
            f"{'升到' if shares['Service'][-1] > shares['Service'][0] else '降到'} {shares['Service'][-1]:.1f}%；"
            f"International transaction 在 {lines['quarters'][trough][-4:]} 年一度掉到 {min(intl):.1f}%"
        ),
        "xlabels": labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": "Service", "values": rounded(shares["Service"]), "color": "NAVY"},
            {"name": "Data processing", "values": rounded(shares["Data processing"]),
             "color": "BLUE"},
            {"name": "International transaction",
             "values": rounded(shares["International transaction"]), "color": "GOLD"},
            {"name": "Other", "values": rounded(shares["Other"]), "color": "GREEN"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "占毛收入比",
        "note": (
            "分母是四条线之和（毛收入），不是净收入，所以四条线加起来恒等于 100%，"
            "激励率的变化不会串到这张图里 —— 两张图各管一件事。"
            f"<b>{lines['quarters'][trough][-4:]} 年那道深谷是疫情</b>：International transaction 依赖跨境交易，"
            f"当季占比从疫情前（{lines['quarters'][before].split()[1]}Q{lines['quarters'][before][1]}）"
            f"的 {intl[before]:.1f}% 掉到 {min(intl):.1f}%"
            + (f"；它在 {lines['quarters'][max(back)[1]].split()[1]}Q{lines['quarters'][max(back)[1]][1]} "
               f"回到过 {max(back)[0]:.1f}%，在 2019 年的区间之内，本季是 {intl[-1]:.1f}%。"
               if back else "，至今没有回到 2019 年的水平。")
            + (f"Data processing 按财年算在 FY{dp_peak} 升到最高的 {dp_years[dp_peak]:.1f}%，"
               f"之后回落，FY{dp_order[-1]} 是 {dp_years[dp_order[-1]]:.1f}%"
               if dp_peak != dp_order[-1] else
               "Data processing 则一路向上" if all(dp_years[b] > dp_years[a] for a, b in zip(dp_order, dp_order[1:]))
               else f"Data processing 按财年算在 FY{dp_peak} 最高")
            + " —— 它按处理笔数计费，是四条线里与「交易笔数」最直接挂钩的一条。"
        ),
        "src_extra": "各季 10-Q / 10-K 收入分解附注。",
    }


def geography_long(staging: dict) -> dict:
    geo = staging["geography_usd_m"]
    labels = [compact_period(period) for period in geo["quarters"]]
    us_share = [value / total * 100
                for value, total in zip(geo["us"], geo["net_revenue"])]
    return {
        "ref": "EX_GEO",
        "kind": "gs_line",
        "title": (
            f"美国以外贡献净收入的 {100 - us_share[-1]:.1f}%，"
            f"{len(labels)} 季里从 {100 - us_share[0]:.1f}% 起步"
        ),
        "xlabels": labels,
        "xstep": LONG_STEP,
        "values": rounded([100 - value for value in us_share]),
        "legend": "International 占净收入比",
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "占净收入比",
        "note": (
            "公司在收入附注里把净收入拆成 U.S. 与 International 两行申报，"
            "两行相加恒等于申报净收入，本页逐季核对过。"
            "这条线只有 ASC 606 之后才有 —— 更早的申报文件不披露这个拆分，"
            "所以窗口从 2018 年底开始，不往前补。"
            "<b>它比区域增速更耐读</b>：占比是两条申报值的比，不受汇率换算口径影响，"
            "而公司从不单独披露分地区的恒定汇率增速。"
        ),
        "src_extra": "各季 10-Q / 10-K 收入分解附注的 U.S. / International 两行。",
    }


def margin_long(staging: dict) -> dict:
    lines = staging["revenue_lines_usd_m"]
    labels = [compact_period(period) for period in lines["quarters"]]
    return {
        "ref": "EX_MARGIN",
        "kind": "lines",
        "title": "净收入与毛收入的两条增速：中间的缺口就是激励率在动",
        "xlabels": labels[4:],
        "xstep": LONG_STEP,
        "series": [
            {"name": "毛收入 YoY", "values": rounded(
                [pct_change(lines["gross_revenue"][i], lines["gross_revenue"][i - 4])
                 for i in range(4, len(labels))]), "color": "GOLD"},
            {"name": "净收入 YoY", "values": rounded(
                [pct_change(lines["net_revenue"][i], lines["net_revenue"][i - 4])
                 for i in range(4, len(labels))]), "color": "NAVY"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "同比增速",
        "note": (
            "<b>这两条线之间的距离，就是上一张图那条斜坡的一阶导数。</b>"
            "毛收入增速高于净收入增速的季度，激励率在上升；反过来则在下降。"
            "把它画成两条增速而不是一条差值，是因为差值会把"
            "「毛收入加速、激励同步加速」和「毛收入减速、激励不减速」画成同一个数，"
            "而这两件事对生意的含义完全不同。"
            "两条线都用申报值计算，同比分母取四个季度之前的同一条线。"
        ),
        "src_extra": "各季 10-Q / 10-K 收入分解附注。",
    }


def capital_return_long(staging: dict) -> dict:
    capital = staging["capital_allocation_usd_m"]
    labels = [compact_period(period) for period in capital["quarters"]]
    ocf = capital["operating_cash_flow"]
    capex = capital["capex"]
    buyback = capital["buyback"]
    dividends = capital["dividends"]
    fcf = [None if o is None or c is None else o + c for o, c in zip(ocf, capex)]
    ret = [None if b is None or d is None else -(b + d) for b, d in zip(buyback, dividends)]
    ratio = [None if f is None or r is None or f <= 0 else r / f * 100
             for f, r in zip(fcf, ret)]
    over = sum(1 for value in ratio if value is not None and value > 100)
    return {
        "ref": "EX_RETURN",
        "kind": "lines",
        "title": (
            f"股东回报与自由现金流：{len(labels)} 季里有 {over} 季回报超过当季自由现金流"
        ),
        "xlabels": labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": "自由现金流 D（经营现金流 − 资本开支）",
             "values": rounded([None if v is None else v / 1000 for v in fcf]), "color": "NAVY"},
            {"name": "回购 + 分红", "values": rounded(
                [None if v is None else v / 1000 for v in ret]), "color": "RED"},
        ],
        "fmt": "usd1",
        "yfmt": "usd1",
        "label_fmt": "usd1",
        "end_label": True,
        "ylab": "US$B",
        "note": (
            "现金流量表在 10-Q 里只有年初至今栏，因此除会计第一季外，"
            "每个季度的四条现金流都是相邻两次申报值之差 —— 两端都是申报值，中间没有估计。"
            "<b>单季穿越并不稀奇</b>，回购按授权节奏走、现金流按季节走，"
            "值得看的是连续几季都在上面的那些窗口。"
            "自由现金流在这里是「经营现金流 − 购置不动产设备与技术」，"
            "是本页自算口径（D）；公司自己不发布自由现金流数字。"
        ),
        "src_extra": "各季 10-Q / 10-K 合并现金流量表。",
    }


# ── section two: this quarter ────────────────────────────────────────────────
def escrow_exhibit(staging: dict) -> dict:
    """The escrow against the accrual it actually funds, not the one it does not.

    This is the page's one flat contradiction of the local note, and it is a
    disclosure question rather than a judgement call: Visa prints the U.S.
    covered accrual separately from the balance-sheet total.
    """
    litigation = staging["litigation"]
    labels = [compact_period(period) for period in litigation["quarters"]]
    escrow = litigation["escrow_usd_m"]
    covered = litigation["us_covered_litigation_usd_m"]
    total = litigation["accrued_litigation_total_usd_m"]
    surplus = [None if e is None or c is None else e - c for e, c in zip(escrow, covered)]
    short_vs_total = escrow[-1] - total[-1]
    compared = [value for value in surplus if value is not None]
    negative = sum(1 for value in compared if value < 0)
    return {
        "ref": "EX_ESCROW",
        "kind": "lines",
        "title": (
            f"托管账户对它真正负责的那笔负债：本季 US${escrow[-1]:,.0f}M vs "
            f"US${covered[-1]:,.0f}M，{'盈余' if surplus[-1] >= 0 else '缺口'} US${abs(surplus[-1]):,.0f}M"
        ),
        "xlabels": labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": "美国诉讼托管账户（受限现金）", "values": rounded(escrow), "color": "NAVY"},
            {"name": "U.S. covered litigation 计提", "values": rounded(covered), "color": "RED"},
            {"name": "计提的诉讼负债合计（含不受托管账户覆盖的部分）",
             "values": rounded(total), "color": "GOLD"},
        ],
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "end_label": True,
        "ylab": "US$M",
        "note": (
            "<b>这张图上有三条线，而只有前两条该放在一起比。</b>"
            "美国追溯责任计划（RRP）下的托管账户只为一件事存在："
            "偿付 <b>U.S. covered litigation</b>。"
            "资产负债表上的「Accrued litigation」是更大的一个数，"
            "它还装着 VE Territory covered 与完全不在覆盖范围内的诉讼 —— "
            "那些钱托管账户既不负责、也不能用来付。"
            "10-Q 的法律事项附注把 U.S. covered 计提单独印成一张表（Accrual Summary—U.S. Covered Litigation），"
            "XBRL 里这组表就叫「Schedule of Accrued Litigation for Both Covered and Non-Covered Litigation」，"
            "所以覆盖口径是<b>申报值</b>，不需要任何推算。"
            f"<b>读数：</b>本季托管账户 US${escrow[-1]:,.0f}M、"
            f"U.S. covered 计提 US${covered[-1]:,.0f}M，账户是"
            + (f"<b>盈余</b> US${surplus[-1]:,.0f}M；" if surplus[-1] >= 0 else
               f"<b>缺口</b> US${-surplus[-1]:,.0f}M；")
            + (f"{len(compared)} 季里一次缺口都没有出现过。" if not negative else
               f"{len(compared)} 季里有 {negative} 季出现过缺口。")
            + (f"若改用合计口径去比，会得到 US${-short_vs_total:,.0f}M 的「缺口」并据此预判一次大额补存 —— "
               "那是拿托管账户去对一笔它不负责的负债。" if short_vs_total < 0 else "")
        ),
        "src_extra": (
            "托管账户余额取自各季资产负债表的受限现金行与现金附注；"
            "两个计提口径取自法律事项附注的 covered / non-covered 计提表。"
        ),
    }


def line_yoy(lines: dict, key: str, start: int) -> list[float]:
    values = lines[key]
    return [pct_change(values[i], values[i - 4]) for i in range(start, len(values))]


LINE_KEYS = (("Service", "service"), ("Data processing", "data_processing"),
             ("International transaction", "international_transaction"), ("Other", "other"))


def whole_percent(value: float) -> int:
    """Half away from zero, the way a release rounds a growth rate to a whole percent."""
    return int(math.copysign(math.floor(abs(value) + 0.5), value))


def printed_growth(staging: dict) -> dict[str, int]:
    """The whole-percent growth each revenue line's row printed in this quarter's release.

    The page's own rate divides two filed figures that are already rounded to
    the million; the company divides unrounded ones, so the two can land on
    different sides of a half.  Where they do, the page prints the company's.
    A printed rate more than a point from the series is a typing error in one of
    the two, and stops the build.
    """
    lines = staging["revenue_lines_usd_m"]
    block = stamped_block(staging, "printed_growth_pct", lines["quarters"][-1]) or {}
    printed = {key: value for key, value in block.items() if key != "period"}
    for key, value in printed.items():
        computed = pct_change(lines[key][-1], lines[key][-5])
        if abs(computed - value) > 1:
            raise ValueError(f"printed_growth_pct.{key} = {value}% is more than a point from the "
                             f"series' {computed:+.2f}%: check the release against the series")
    return printed


def quarter_revenue_lines(staging: dict) -> dict:
    lines = staging["revenue_lines_usd_m"]
    window = window_from_2016(staging)
    start = len(lines["quarters"]) - window
    quarters = lines["quarters"][start:]
    labels = [compact_period(period) for period in quarters]
    yoy = {name: line_yoy(lines, key, start) for name, key in LINE_KEYS}
    service, dp = yoy["Service"], yoy["Data processing"]
    intl, other = yoy["International transaction"], yoy["Other"]
    single = [name for name, values in yoy.items() if abs(values[-1]) < 10]
    negatives = [sum(1 for name in yoy if yoy[name][i] < 0) for i in range(len(quarters))]
    worst = min((min(values), name) for name, values in yoy.items())
    worst_at = quarters[yoy[worst[1]].index(worst[0])]
    rank = [sorted(yoy, key=lambda name: yoy[name][i], reverse=True).index("Other") + 1
            for i in range(len(quarters))]
    early = [i for i, q in enumerate(quarters) if q.endswith(("2016", "2017"))]
    early_bottom = [i for i in early if rank[i] == 4]
    top_now = rank[-1] == 1
    payments = staging["operating_volumes"]
    aligned = payments["payments_volume_quarters"][-1]
    prior_quarter = lines["quarters"][-2]
    printed = printed_growth(staging)
    now = {name: printed.get(key, whole_percent(yoy[name][-1])) for name, key in LINE_KEYS}
    order = sorted(now, key=lambda name: yoy[name][-1], reverse=True)
    apart = [(name, yoy[name][-1], now[name]) for name, _ in LINE_KEYS
             if whole_percent(yoy[name][-1]) != now[name]]
    span = cn_count((len(quarters) - 1) // 4)
    return {
        "ref": "EX_LINES_YOY",
        "kind": "lines",
        "title": (
            "四条毛收入线的同比增速"
            + ("本季分道扬镳：" if max(now.values()) - min(now.values()) >= 20 else "：")
            + "、".join(f"{name} {now[name]:+d}%" for name in order)
        ),
        "xlabels": labels,
        "xrot": 90,
        "xstep": LONG_STEP,
        "series": [
            {"name": "Service", "values": rounded(service), "color": "NAVY"},
            {"name": "Data processing", "values": rounded(dp), "color": "BLUE"},
            {"name": "International transaction", "values": rounded(intl), "color": "GOLD"},
            {"name": "Other", "values": rounded(other), "color": "GREEN"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "同比增速",
        "note": (
            "<b>这四条线不能按同一个时点去读，公司自己在每份新闻稿里都写明了这一点。</b>"
            "Service revenue 按<b>上一个季度</b>的支付额确认，其余三条按<b>当季</b>活动确认。"
            "因此把 Service 的增速对着当季支付额增速看，会整整错开一个季度；"
            "而新闻稿开头那张「Key Business Drivers」表印的恰恰是<b>当季</b>的支付额。"
            "本页不发布「收入增速 vs 当季支付额增速」的对照图；能对齐的那一组 —— "
            "Service revenue 对上一季的名义支付额 —— 10-Q 的 MD&A 按季印着美元金额"
            + (f"（本季对的是 {aligned} 那一季的 US${payments['nominal_payments_volume_usd_b'][-1]:,.0f}B）"
               if aligned == prior_quarter and not lines["fiscal_labels"][-1].endswith("Q4") else "")
            + "，本页把这一组画在「Service revenue ÷ 上一季名义支付额」那张图里。"
            + "".join(f"标题里的增速是新闻稿印的整数；图上的线是本页拿取整到百万美元的申报值相除（D），"
                      f"{name} 本季算出来是 {computed:+.1f}%，公司按未取整的数印的是 {official:+d}%。"
                      for name, computed, official in apart)
            + (f"International transaction 本季 {signed(intl[-1])}，是四条线里唯一进入个位数的一条。"
               if single == ["International transaction"] else "")
            + (f"<b>{span}年的窗口里这四条从没有同时为负过</b>：最多是 {quarters[negatives.index(max(negatives))]} "
               f"的{cn_count(max(negatives))}条，最低一格是 {worst[1]} 在 {worst_at} 的 {signed(worst[0], 0)}。"
               if max(negatives) < 4 else
               f"<b>{span}年的窗口里这四条同时为负过</b>，最低一格是 {worst[1]} 在 {worst_at} 的 {signed(worst[0], 0)}。")
            + ("除那一段之外，四条线的排序换过多次 —— "
               + ("今天 Other 在最上面，" if top_now else "")
               + (f"而 2016—2017 年的 {len(early)} 个季度里它有 {len(early_bottom)} 个在最下面。"
                  if len(early_bottom) * 2 > len(early) else "")
               if top_now or early_bottom else "")
        ),
        "src_extra": "各季 10-Q / 10-K 收入分解附注；确认时点的表述见各季业绩 8-K 的 EX-99.1。",
    }


def incentive_quarter(staging: dict) -> dict:
    lines = staging["revenue_lines_usd_m"]
    window = window_from_2016(staging)
    labels = [compact_period(period) for period in lines["quarters"][-window:]]
    rate = lines["incentive_rate_pct"][-window:]
    full = lines["incentive_rate_pct"]
    yoy_gap = rate[-1] - full[-5]
    qoq_gap = rate[-1] - full[-2]
    return {
        "ref": "EX_INC_Q",
        "kind": "gs_line",
        "title": (
            f"激励率本季 {rate[-1]:.2f}%，同比 {signed(yoy_gap, 2, 'pp')}、环比 {signed(qoq_gap, 2, 'pp')}"
        ),
        "xlabels": labels,
        "xrot": 90,
        "xstep": LONG_STEP,
        "values": rounded(rate),
        "legend": "Client incentives / 毛收入",
        "fmt": "pct2",
        "yfmt": "pct2",
        "label_fmt": "pct2",
        "ylab": "占毛收入比",
        "note": (
            f"<b>把这张图和第四节那条从 {lines['fiscal_labels'][0][:6]} 起的长坡一起读。</b>"
            f"这张图画的是 {len(rate)} 季（{labels[0]} 起），"
            f"从 {rate[0]:.2f}% 走到 {rate[-1]:.2f}%，也就是那条长坡的最后 {len(rate)} 个点。"
            + (f"本季 {rate[-1]:.2f}% 是窗口内最高。" if rate[-1] == max(rate) else "")
            + "反事实很好算，也全部是申报值："
            f"若激励率维持去年同期的 {full[-5]:.2f}%，"
            f"本季净收入会是 US${lines['gross_revenue'][-1] * (1 - full[-5] / 100):,.0f}M，"
            f"而不是申报的 US${lines['net_revenue'][-1]:,.0f}M —— "
            f"激励率这 {signed(yoy_gap, 2, 'pp')} "
            + incentive_effect(lines["gross_revenue"][-1], rate[-1], full[-5]) + "。"
        ),
        "src_extra": "各季 10-Q 收入分解附注。",
    }


def non_vas_growth_band(staging: dict) -> tuple[float, float] | None:
    """Nominal growth of net revenue outside value-added services, as the range the
    10-Q's US$0.1B rounding of both years' value-added services figures allows."""
    vas = staging["vas_revenue"]
    lines = staging["revenue_lines_usd_m"]
    if vas["quarters"][-1] != staging["periods"][-1] or len(vas["quarters"]) < 5:
        return None
    net = dict(zip(lines["quarters"], lines["net_revenue"]))
    now, then = vas["usd_bn"][-1] * 1000, vas["usd_bn"][-5] * 1000
    net_now, net_then = net[vas["quarters"][-1]], net[vas["quarters"][-5]]
    half = 50.0
    band = [pct_change(net_now - (now + a), net_then - (then + b)) for a in (half, -half) for b in (-half, half)]
    return min(band), max(band)


def highlights_description(staging: dict, vas_chart: dict | None, reconciliation: dict | None,
                           story: dict, gap_in_section_one: bool) -> str:
    """Section two's lead: the report's conclusions in the order the charts take them,
    every figure read from the series; what cannot be drawn is named with why."""
    lines = staging["revenue_lines_usd_m"]
    financials = staging["financials"]
    net, gross = financials["net_revenue_usd_m"], financials["gross_revenue_usd_m"]
    rate = lines["incentive_rate_pct"]
    printed = printed_growth(staging)
    growth = {name: printed.get(key, whole_percent(pct_change(lines[key][-1], lines[key][-5])))
              for name, key in LINE_KEYS}
    lowest = min(growth, key=growth.get)
    parts = [
        story.get("lead", "")
        + f"净收入同比 {signed(pct_change(net[-1], net[-5]))}、毛收入 {signed(pct_change(gross[-1], gross[-5]))}，"
        + (f"差的那一截是客户激励率升到 {rate[-1]:.2f}%（同比 {signed(rate[-1] - rate[-5], 2, 'pp')}）；"
           if rate[-1] > rate[-5] and pct_change(gross[-1], gross[-5]) > pct_change(net[-1], net[-5]) else
           f"客户激励率 {rate[-1]:.2f}%（同比 {signed(rate[-1] - rate[-5], 2, 'pp')}）；")
        + f"四条毛收入线里 {lowest} 最低（{growth[lowest]:+.0f}%）"
    ]
    vas = staging["vas_revenue"]
    if vas_chart:
        share = vas["usd_bn"][-1] * 1000 / net[-1]
        parts.append(f"；增值服务 US${vas['usd_bn'][-1]:.1f}B，约占净收入{cn_fraction(share)}")
    changes = margin_changes(staging) if reconciliation else []
    if changes and changes[-1][0] == staging["periods"][-1]:
        run = 0
        for _, _, _, change in reversed(changes):
            if change >= 0:
                break
            run += 1
        parts.append(f"；公司口径的营业利润率同比 {signed(changes[-1][3], 2, 'pp')}"
                     + (f"，已连续{cn_count(run)}季下降" if run > 1 else ""))
    per_share = staging["per_share"]
    period = staging["periods"][-1]
    year_ago = f"{period[:2]} {int(period[-4:]) - 1}"
    if period in per_share["quarters"] and year_ago in per_share["quarters"]:
        i, j = per_share["quarters"].index(period), per_share["quarters"].index(year_ago)
        shares = per_share["class_a_diluted_shares_m"]
        eps = per_share["class_a_diluted_eps_usd"]
        income = financials["net_income_usd_m"]
        parts.append(f"；摊薄 A 类股同比 {signed(pct_change(shares[i], shares[j]))}，"
                     f"所以 GAAP 每股收益 {signed(pct_change(eps[i], eps[j]))} 快于净利润 "
                     f"{signed(pct_change(income[-1], income[-5]))}")
    parts.append("；最后是诉讼托管账户，它只对应 U.S. covered 计提。"
                 + ("跨境变现率（国际交易收入增速对跨境交易额增速）的差画在第一节。" if gap_in_section_one else ""))
    undrawn = story.get("undrawn", [])
    if undrawn:
        parts.append("本季报告里画不出来的：" + "；".join(undrawn) + "。")
    return "".join(parts)


def vas_exhibit(staging: dict) -> dict | None:
    """Value-added services inside net revenue, for the quarters the 10-Qs print it.

    The 10-Q rounds the figure to US$0.1B, so every derived quantity here is
    stated as the range that rounding allows, not as a point.
    """
    vas = staging["vas_revenue"]
    lines = staging["revenue_lines_usd_m"]
    period = staging["periods"][-1]
    if vas["quarters"][-1] != period:
        return None
    net = dict(zip(lines["quarters"], lines["net_revenue"]))
    quarters = vas["quarters"]
    amounts = [value * 1000 for value in vas["usd_bn"]]
    rest = [net[q] - value for q, value in zip(quarters, amounts)]
    share = [value / net[q] * 100 for q, value in zip(quarters, amounts)]
    now, then = amounts[-1], amounts[-5]
    net_now, net_then = net[quarters[-1]], net[quarters[-5]]
    half = 50.0  # half of the US$0.1B the 10-Q rounds to
    rest_growth = non_vas_growth_band(staging)
    added = [((now + a) - (then + b)) / (net_now - net_then) * 100 for a in (-half, half) for b in (half, -half)]
    growth = vas["growth_printed_pct"][-1]
    first_printed = next(i for i, value in enumerate(vas["growth_printed_pct"]) if value is not None)
    return {
        "ref": "EX_VAS",
        "kind": "stacked_dual",
        "title": (f"增值服务收入 US${vas['usd_bn'][-1]:.1f}B、同比 "
                  + (f"{growth:+.0f}%" if growth is not None else signed(pct_change(now, then)))
                  + f"：约占净收入{cn_fraction(share[-1] / 100)}"),
        "xlabels": [compact_period(q) for q in quarters],
        "stacks": [
            {"name": "增值服务收入（10-Q 印，US$0.1B 精度）", "color": "NAVY", "values": rounded(amounts)},
            {"name": "其余净收入 D", "color": "GRAY", "values": rounded(rest)},
        ],
        "line": {"name": "增值服务占净收入 (RHS)", "color": "RED", "values": rounded(share),
                 "yfmt": "pct1", "ymax": 50},
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$M",
        "ylab2": "占净收入",
        "note": (
            f"本季增值服务占净收入约 {share[-1]:.1f}%，去年同季约 {share[-5]:.1f}%"
            "（10-Q 只印到 US$0.1B，每个比重有约 ±0.4 个百分点的取整误差）。"
            f"净收入同比多出的 US${net_now - net_then:,.0f}M 里，增值服务贡献了 "
            f"{min(added):.0f}%–{max(added):.0f}%；其余部分的名义同比落在 "
            f"{signed(min(rest_growth))}–{signed(max(rest_growth))} 之间 —— 两个区间都是取整误差允许的范围。"
            "增值服务收入分散记在 Data processing、Other 与 Service 三条收入线里，公司不单列它的利润率；"
            f"公司从截至 {vas['period_ends'][first_printed]} 的 10-Q 起才按季印这个数（附去年同季栏），"
            f"所以这张图从那份 10-Q 的去年同季栏 {quarters[0]} 开始。"
        ),
        "src_extra": "各季 10-Q 收入附注与 MD&A 的「value-added services」段；会计第四季为 10-K 全年减九个月（D）。",
    }


def margin_changes(staging: dict) -> list[tuple[str, float, float, float]]:
    """(quarter, non-GAAP operating margin, year-ago margin, change in points), per quarter.

    Both non-GAAP expense figures come from ONE release's reconciliation table
    -- its own quarter's column and the year-ago column printed beside it --
    and net revenue from the filed revenue lines, so no margin is chained
    across releases whose exclusions differ.
    """
    recon = staging["nongaap_recon_usd_m"]
    lines = staging["revenue_lines_usd_m"]
    net = dict(zip(lines["quarters"], lines["net_revenue"]))
    out = []
    for q, now, then in zip(recon["quarters"], recon["nongaap_opex"], recon["prior_year_nongaap_opex"]):
        year_ago = f"{q[:2]} {int(q[-4:]) - 1}"
        if q not in net or year_ago not in net:
            continue
        m1 = (net[q] - now) / net[q] * 100
        m0 = (net[year_ago] - then) / net[year_ago] * 100
        out.append((q, m1, m0, m1 - m0))
    return out


def opex_reconciliation_exhibit(staging: dict, block: dict) -> dict:
    """This quarter's GAAP operating expenses taken to the company's non-GAAP figure,
    item by item as the release's reconciliation table lists them."""
    period = staging["periods"][-1]
    financials = staging["financials"]
    gaap = financials["total_opex_usd_m"][-1]
    items = block["items"]
    nongaap = gaap - sum(item["usd_m"] for item in items)
    recon = staging["nongaap_recon_usd_m"]
    if recon["quarters"][-1] != period or abs(recon["nongaap_opex"][-1] - nongaap) > 0.5:
        raise ValueError(f"opex_reconciliation items take GAAP US${gaap:,.0f}M to US${nongaap:,.0f}M, but "
                         f"nongaap_recon_usd_m does not end on {period} at that figure: add this quarter's "
                         "reconciliation columns with the roll")
    opex = staging["nongaap_opex"]
    printed = opex["growth_printed_pct"][-1] if opex["quarters"][-1] == period else None
    computed = pct_change(nongaap, recon["prior_year_nongaap_opex"][-1])
    if printed is not None and abs(computed - printed) > 1:
        raise ValueError(f"nongaap_opex printed {printed}% is more than a point from the reconciliation's "
                         f"{computed:+.2f}%: check the release")
    net = financials["net_revenue_usd_m"]
    changes = margin_changes(staging)
    run = []
    for q, m1, m0, change in reversed(changes):
        if change >= 0:
            break
        run.append((q, change))
    run.reverse()
    _, m1, m0, change = changes[-1]
    litigation_line = financials["litigation_provision_usd_m"][-1] or 0.0
    litigation_item = next((item["usd_m"] for item in items if item["name"].startswith("诉讼计提")), None)
    values = {"litigation_line": usd_m(litigation_line),
              "litigation_item": usd_m(litigation_item) if litigation_item is not None else "—",
              "margin_run": cn_count(len(run))}
    growth_words = f"{printed:+.0f}%" if printed is not None else signed(computed)
    return {
        "ref": "EX_WEDGE",
        "kind": "bars_labeled",
        "title": (
            f"本季 GAAP 营业费用 US${gaap:,.0f}M、同比 {signed(pct_change(gaap, financials['total_opex_usd_m'][-5]))}；"
            f"剔除{cn_count(len(items))}项后公司口径 US${nongaap:,.0f}M、同比 {growth_words}"
        ),
        "xlabels": ["GAAP 营业费用"] + [f"其中：{item['name']}" for item in items] + ["公司口径 non-GAAP"],
        "values": [gaap] + [item["usd_m"] for item in items] + [nongaap],
        "legend": "US$M",
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$M",
        "note": (
            f"公司在新闻稿的 Non-GAAP 对账表里从 GAAP 营业费用中剔除这{cn_count(len(items))}项。"
            + fill_story(block.get("note", ""), values)
            + f"公司口径营业费用同比 {growth_words}（对账表两栏相除 {signed(computed)}），"
            f"净收入同比 {signed(pct_change(net[-1], net[-5]))}：non-GAAP 营业利润率 {m1:.2f}%，"
            f"去年同季 {m0:.2f}%，同比 {signed(change, 2, 'pp')}。"
            + (f"<b>这已是连续第{cn_ordinal(len(run))}季同比下降</b>（"
               + "、".join(f"{q} {signed(c, 2, 'pp')}" for q, c in run) + "）"
               + ("，本季降得最多。" if min(c for _, c in run) == run[-1][1] else "。")
               if len(run) > 1 else "")
            # the stamped sentence contradicts a report that called this decline the
            # first; it is only true while the computed run is longer than one quarter
            + (fill_story(block.get("report", ""), values) if len(run) > 1 else "")
            + "利润率是本页用对账表两栏与申报净收入相除（D），不把不同年份新闻稿里的 non-GAAP 水平接成一条线。"
        ),
        "src_extra": (
            "GAAP 营业费用取自 10-Q 合并损益表；剔除项与公司口径营业费用取自本季业绩 8-K EX-99.1 的 "
            "Non-GAAP 对账表（本季栏与去年同季栏）。"
        ),
    }


# ── the readings a threshold is settled against ──────────────────────────────
def payout_ratio(staging: dict) -> list[float | None]:
    capital = staging["capital_allocation_usd_m"]
    out = []
    for o, c, b, d in zip(capital["operating_cash_flow"], capital["capex"],
                          capital["buyback"], capital["dividends"]):
        if None in (o, c, b, d) or o + c <= 0:
            out.append(None)
        else:
            out.append(-(b + d) / (o + c) * 100)
    return out


def escrow_surplus(staging: dict) -> list[float | None]:
    lit = staging["litigation"]
    return [None if e is None or c is None else e - c
            for e, c in zip(lit["escrow_usd_m"], lit["us_covered_litigation_usd_m"])]


def cross_border_gaps(staging: dict) -> tuple[list[str], list[int], list[int | None]]:
    """Cross-border volume growth less international transaction revenue growth, in points.

    Both legs are the whole-number rates the quarter's own release printed, so
    each cell carries up to a point of rounding either way. Two bases, because
    the two reports this page is settled against use different ones: the
    2026-04-29 report set its thresholds on constant-dollar volume ex
    intra-Europe (its own reading was 11% − 6% = 5pp), the 2026-07-28 report
    moved to nominal volume, which the releases print from fiscal 2020 Q3 on.
    """
    cb = staging["cross_border_growth_pct"]
    revenue = cb["international_transaction_printed"]
    constant = [c - r for c, r in zip(cb["ex_intra_europe_constant"], revenue)]
    nominal = [None if n is None else n - r for n, r in zip(cb["ex_intra_europe_nominal"], revenue)]
    return cb["quarters"], constant, nominal


def us_payments_yoy(staging: dict) -> tuple[list[str], list[float]]:
    """U.S. nominal payments volume against the same quarter a year earlier.

    Both legs come from the same table of the same filing: the quarter's column
    and the year-ago column printed beside it (the Apr-Jun quarter is a 10-K
    twelve-month column less a nine-month one, for both years). Dividing first
    prints across years instead would splice two definitions -- Visa added
    Visa Direct push volume in fiscal 2019 and reprinted earlier periods.
    """
    volumes = staging["operating_volumes"]
    return (list(volumes["payments_volume_quarters"]),
            [pct_change(cur, prior) for cur, prior in zip(volumes["us_usd_b"], volumes["us_prior_year_usd_b"])])


def kpi_reading(staging: dict, reads: str) -> float | None:
    """The quarter's value of one tracked metric, read from the series.

    A current value typed into the threshold block was rounded before it was
    compared, and that moved the last printed digit of a headroom bar.

    ``None`` means the page's quarter has no filed reading of it -- a fiscal
    fourth quarter's value-added services growth, which only the 10-K's
    full-year figure covers. The caller says so instead of settling against the
    quarter before.
    """
    period = staging["periods"][-1]
    if reads == "payout_to_fcf":
        return payout_ratio(staging)[-1]
    if reads == "escrow_surplus":
        return escrow_surplus(staging)[-1]
    if reads in ("cross_border_gap", "cross_border_gap_min2"):
        quarters, constant, _ = cross_border_gaps(staging)
        if quarters[-1] != period:
            return None
        return float(constant[-1] if reads == "cross_border_gap" else min(constant[-2:]))
    if reads == "vas_yoy":
        vas = staging["vas_revenue"]
        if vas["quarters"][-1] != period or vas["growth_printed_pct"][-1] is None:
            return None
        return float(vas["growth_printed_pct"][-1])
    if reads == "nongaap_opex_yoy":
        opex = staging["nongaap_opex"]
        return float(opex["growth_printed_pct"][-1]) if opex["quarters"][-1] == period else None
    if reads == "us_payments_yoy":
        # the 10-Q prints the quarter BEFORE the one it reports (service revenue is
        # recognised on it), so the reading belongs to the previous quarter; a
        # fiscal fourth quarter's roll may land before the 10-K prints it
        quarters, us = us_payments_yoy(staging)
        return us[-1] if quarters and quarters[-1] == previous_quarter(period) else None
    if reads.startswith("yoy:"):
        block, key = reads[4:].split(".")
        values = staging[block][key]
        return pct_change(values[-1], values[-5])
    block, key = reads.split(".")
    return staging[block][key][-1]


def kpi_entries(block: dict, staging: dict, key: str = "current") -> list[dict]:
    """The block's quantified thresholds, each with its reading under ``key``."""
    out = []
    for entry in block["quantified"]:
        if "reads" not in entry:
            raise ValueError(f"threshold {entry['metric']!r} has no `reads`")
        out.append({**entry, key: kpi_reading(staging, entry["reads"])})
    return out


def threshold_words(entry: dict) -> str:
    """How a threshold is named on its own chart."""
    if entry["unit"] == "usd_m":
        return usd_m(entry["threshold"])
    if entry["unit"] == "pp":
        return f"{entry['threshold']:.0f}pp"
    if entry["reads"].startswith("yoy:") or entry["reads"] in GROWTH_READS:
        return f"{entry['threshold']:+.1f}%"
    return f"{entry['threshold']:.2f}%"


# Readings that are growth rates although their `reads` does not start with `yoy:`.
GROWTH_READS = ("vas_yoy", "nongaap_opex_yoy", "us_payments_yoy")


def entry_words(staging: dict, entry: dict) -> dict[str, str]:
    """What a stamped threshold sentence may name, computed rather than typed."""
    words = {"threshold": story_threshold(entry)}
    if entry.get("volume_condition") is not None:
        words["volume_condition"] = f"{entry['volume_condition']:+.0f}%"
    if entry["reads"] == "escrow_surplus":
        lit = staging["litigation"]
        words["total_basis"] = usd_m(lit["escrow_usd_m"][-1] - lit["accrued_litigation_total_usd_m"][-1])
    return words


def story_threshold(entry: dict) -> str:
    """The threshold as a sentence names it: 「+4%」「−US$1,000M」「3pp」."""
    if entry["unit"] == "usd_m":
        return usd_m(entry["threshold"])
    if entry["unit"] == "pp":
        return f"{entry['threshold']:.0f}pp"
    if entry["reads"].startswith("yoy:") or entry["reads"] in GROWTH_READS:
        return f"{entry['threshold']:+.0f}%"
    return f"{entry['threshold']:.2f}%"


def is_held(entry: dict, key: str) -> bool:
    return headroom(entry["direction"], entry["threshold"], entry[key]) >= 0


def line_name(entry: dict) -> str:
    """A threshold line's name: the report's role for it, or plain 「阈值」.

    Last quarter's report drew two lines on some metrics -- one it would add
    on, one it would watch -- and the chart has to say which is which.
    """
    rule = (f"（连续{cn_count(entry['quarters'])}季）" if entry.get("quarters") else "")
    role = entry.get("role")
    return (f"{role}线 {story_threshold(entry)}{rule}" if role else f"阈值 {threshold_words(entry)}")


def settled_words(group: list[dict], key: str) -> str:
    """「击穿上季加仓线 15%、守住上季重置线 20%」 for a prior-quarter chart title."""
    return "、".join(f"{'守住' if is_held(entry, key) else '击穿'}上季{line_name(entry)}"
                     for entry in group)


def threshold_lines_exhibit(title: str, xlabels: list[str], actual: list[dict], group: list[dict],
                            mode: str, *, fmt: str, ylab: str, note: str, src_extra: str,
                            xstep: int | None = None) -> dict:
    """One tracked series (or two, when two bases are compared) with every threshold
    set on it drawn as its own flat line -- the multi-line form of `threshold_exhibit`."""
    n = len(xlabels)
    series = list(actual)
    for entry in group:
        good = entry.get("role") in ("加仓", "可控")
        series.append({
            "name": (f"上季{line_name(entry)}" if mode == "prior" else f"下季{line_name(entry)}"),
            "values": [entry["threshold"]] * n,
            "color": "GREEN" if good else "RED",
        })
    chart = {
        "kind": "lines",
        "title": title,
        "xlabels": xlabels,
        "series": series,
        "fmt": fmt,
        "yfmt": fmt,
        "label_fmt": fmt,
        "end_label": True,
        "ylab": ylab,
        "note": note,
        "src_extra": src_extra,
    }
    if xstep:
        chart["xstep"] = xstep
    return chart


def headline_for(name: str, reading: str, group: list[dict], mode: str, key: str) -> str:
    if mode == "prior":
        return f"{name} {reading}：{settled_words(group, key)}"
    return (f"{name}：下季" + "、".join(line_name(entry) for entry in group) + f"，当前 {reading}")


def runs_where(flags: list[bool]) -> list[list[int]]:
    """Index runs where `flags` is true: [[3, 4, 5], [9]]."""
    runs, run = [], []
    for i, flag in enumerate(flags):
        if flag:
            run.append(i)
        elif run:
            runs.append(run)
            run = []
    if run:
        runs.append(run)
    return runs


def track_nongaap_opex(staging: dict, group: list[dict], mode: str, key: str) -> dict:
    """The company's own printed non-GAAP (earlier: adjusted) opex growth, one release per point."""
    opex = staging["nongaap_opex"]
    start = opex["quarters"].index("Q1 2016")
    quarters = opex["quarters"][start:]
    growth = opex["growth_printed_pct"][start:]
    entry = group[0]
    words = entry_words(staging, entry)
    over = [value > entry["threshold"] for value in growth]
    tail = runs_where(over)
    current_run = tail[-1] if tail and tail[-1][-1] == len(growth) - 1 else []
    recon = staging["nongaap_recon_usd_m"]
    amounts = ""
    if recon["quarters"][-1] == quarters[-1]:
        now, then = recon["nongaap_opex"][-1], recon["prior_year_nongaap_opex"][-1]
        amounts = (f"（同一份对账表里本季 US${now:,.0f}M、去年同季 US${then:,.0f}M，相除 "
                   f"{signed(pct_change(now, then))}）")
    asc = opex.get("asc606_pp", {})
    return threshold_lines_exhibit(
        headline_for("non-GAAP 营业费用同比", f"{growth[-1]:+.0f}%", group, mode, key),
        [compact_period(q) for q in quarters],
        [{"name": "公司印的 non-GAAP（2019 年前称 adjusted）营业费用同比", "values": growth, "color": "NAVY"}],
        group, mode, fmt="pct0", ylab="同比增速", xstep=LONG_STEP,
        note=(
            f"本季公司印 {growth[-1]:+.0f}%{amounts}。"
            + fill_story(entry.get("rationale", ""), words)
            + f"{cn_count(len(growth))}个季度里有{cn_count(sum(over))}季高于 {story_threshold(entry)}"
            + (f"，本季是连续第{cn_ordinal(len(current_run))}季" if len(current_run) > 1 else
               "，本季是其中之一" if current_run else "，本季不在其中")
            + "。每一格都是报告该季的那份新闻稿自己印的整数增速，分子分母同出一份新闻稿；剔除哪些项目由公司逐季决定，"
            "所以跨格口径不完全相同：2016 年 7–9 月到 2017 年 4–6 月的分子含并入的 Visa Europe、分母不含"
            + (f"；{joined(list(asc))} 公司自己写明新收入准则把这几季的增速抬高了 "
               f"{min(asc.values()):.1f}–{max(asc.values()):.1f} 个百分点" if asc else "")
            + "。"
        ),
        src_extra="各季业绩 8-K EX-99.1 的营业费用段落与 Non-GAAP 对账表；逐格原句在 series 里。",
    )


def track_us_payments(staging: dict, group: list[dict], mode: str, key: str) -> dict:
    """U.S. nominal payments volume growth, as far as the 10-Qs have printed it."""
    quarters, yoy = us_payments_yoy(staging)
    start = quarters.index("Q1 2016")
    quarters, yoy = quarters[start:], yoy[start:]
    entry = group[0]
    words = entry_words(staging, entry)
    below = [value < entry["threshold"] for value in yoy]
    runs = runs_where(below)
    longest = max(runs, key=len) if runs else []
    recent = [i for i, q in enumerate(quarters) if int(q[-4:]) >= int(quarters[-1][-4:]) - 2]
    return threshold_lines_exhibit(
        headline_for("美国名义支付额同比", f"{signed(yoy[-1])}（{quarters[-1]}）", group, mode, key),
        [compact_period(q) for q in quarters],
        [{"name": "美国名义支付额同比（同一份申报的两栏相除 D）", "values": rounded(yoy), "color": "NAVY"}],
        group, mode, fmt="pct1", ylab="同比增速", xstep=LONG_STEP,
        note=(
            fill_story(entry.get("rationale", ""), words)
            + f"所以这张图停在 {quarters[-1]}。"
            + (f"{cn_count(len(yoy))}个季度里有{cn_count(sum(below))}季低于 {story_threshold(entry)}，"
               f"最长的一段是 {quarters[longest[0]]} 到 {quarters[longest[-1]]} 的{cn_count(len(longest))}季；"
               f"{quarters[recent[0]][-4:]} 年以来的{cn_count(len(recent))}季里有"
               f"{cn_count(sum(1 for i in recent if below[i]))}季低于它 —— 按季度看，这条线最近几年常在阈值附近。"
               if runs else f"{cn_count(len(yoy))}个季度里没有一季低于 {story_threshold(entry)}。")
            + "每一格是同一份 10-Q（4–6 月那一季是 10-K 十二个月栏减 10-Q 九个月栏）里本期与去年同期两栏相除，"
            "不拿首印值跨年相除 —— 公司 FY2019 把 Visa Direct 推送支付额计入支付额并重印了此前各期。"
        ),
        src_extra="各季 10-Q / 10-K MD&A 名义支付额表的 U.S. 栏；逐格出处在 series 里。",
    )


def track_intl_yoy(staging: dict, group: list[dict], mode: str, key: str) -> dict:
    lines = staging["revenue_lines_usd_m"]
    long_from = lines["quarters"].index("Q1 2016")
    long_labels = [compact_period(q) for q in lines["quarters"][long_from:]]
    entry = group[0]
    words = entry_words(staging, entry)
    yoy = line_yoy(lines, "international_transaction", long_from)
    quarters = lines["quarters"][long_from:]
    below = [i for i, value in enumerate(yoy) if value < entry["threshold"]]
    runs, run = [], []
    for i in below:
        if run and i != run[-1] + 1:
            runs.append(run)
            run = []
        run.append(i)
    if run:
        runs.append(run)
    deep = max(runs, key=len) if runs else []
    others = [i for r in runs if r is not deep for i in r]
    others_yoy = {name: line_yoy(lines, k, long_from) for name, k in LINE_KEYS}
    single = [name for name, values in others_yoy.items() if abs(values[-1]) < 10]
    fiscal = lines["fiscal_labels"][long_from:]
    actual = [{"name": "International transaction YoY", "values": rounded(yoy), "color": "NAVY"}]
    condition = ""
    volume_at = entry.get("volume_condition")
    if volume_at is not None:
        cb = staging["cross_border_growth_pct"]
        by_quarter = dict(zip(cb["quarters"], cb["ex_intra_europe_nominal"]))
        nominal = [by_quarter.get(q) for q in quarters]
        actual.append({"name": "名义跨境交易额（不含欧洲区内）同比，新闻稿印", "values": nominal, "color": "GOLD"})
        actual.append({"name": f"量的限定条件 {volume_at:+.0f}%", "values": [volume_at] * len(quarters),
                       "color": "GRAY"})
        if nominal[-1] is not None:
            revenue_broke = yoy[-1] < entry["threshold"]
            volume_strong = nominal[-1] > volume_at
            condition = (
                f"本季两条件：收入 {signed(yoy[-1])}，{'已跌破' if revenue_broke else '在'} {story_threshold(entry)}"
                f"{'' if revenue_broke else ' 之上'}；名义跨境交易额 {nominal[-1]:+.0f}%，"
                f"{'高于' if volume_strong else '不高于'} {volume_at:+.0f}% —— "
                + ("两件事同时成立，减仓条件触发。" if revenue_broke and volume_strong else
                   "只有量这一半成立，减仓条件没有触发。" if volume_strong else
                   "收入跌破了，但量也不强，按报告的定义不算变现率塌陷。" if revenue_broke else
                   "两件事都没有成立。"))
    return threshold_lines_exhibit(
        headline_for("International transaction 收入同比", signed(yoy[-1]), group, mode, key),
        long_labels, actual, group, mode, fmt="pct1", ylab="同比增速", xstep=LONG_STEP,
        note=(
            ("这是四条毛收入线里本季唯一掉进个位数的一条。"
             if single == ["International transaction"] else "")
            + fill_story(entry.get("rationale", ""), words)
            + condition
            + (f"<b>拉到{cn_count(len(yoy))}季之后，跌破 {entry['threshold']:+.0f}% 不再是罕见事</b>："
               f"{quarters[deep[0]]} 到 {quarters[deep[-1]]}（公司 {fiscal_words(fiscal[deep[0]])} 至 "
               f"{fiscal_words(fiscal[deep[-1]])}）连续 {len(deep)} 季在阈值之下"
               + ((f"，其中 {quarters[neg[0]]} 到 {quarters[neg[-1]]} 这 {len(neg)} 季为负、"
                   f"最低 {signed(min(yoy[i] for i in neg))}")
                  if (neg := [i for i in deep if yoy[i] < 0]) else "")
               + ("；" + joined([f"{quarters[i]}（{signed(yoy[i])}）" for i in others])
                  + "也在阈值之下。" if others else "。")
               if deep else "")
            + fill_story(entry.get("rationale_tail", ""), words)
        ),
        src_extra="各季 10-Q 收入分解附注。",
    )


def track_escrow(staging: dict, group: list[dict], mode: str, key: str) -> dict:
    entry = group[0]
    words = entry_words(staging, entry)
    surplus = escrow_surplus(staging)
    lit = staging["litigation"]
    against_total = [None if e is None or t is None else e - t
                     for e, t in zip(lit["escrow_usd_m"], lit["accrued_litigation_total_usd_m"])]
    return threshold_lines_exhibit(
        headline_for("托管账户相对 U.S. covered 计提的盈余", usd_m(surplus[-1]), group, mode, key),
        [compact_period(period) for period in staging["litigation"]["quarters"]],
        [{"name": "托管账户 − U.S. covered 计提 D", "values": rounded(surplus), "color": "NAVY"},
         {"name": "托管账户 − 计提合计 D（报告用的口径）", "values": rounded(against_total), "color": "GOLD"}],
        group, mode, fmt="f0c", ylab="US$M", xstep=LONG_STEP,
        note=(
            "分子分母都是申报值，差值是本页自算（D）。"
            + fill_story(entry.get("rationale", ""), words)
            + f"本季为{'盈余' if surplus[-1] >= 0 else '缺口'} US${abs(surplus[-1]):,.0f}M。"
        ),
        src_extra="各季 10-Q 资产负债表、现金附注与法律事项附注。",
    )


def track_incentives_yoy(staging: dict, group: list[dict], mode: str, key: str) -> dict:
    """Client incentives against the same quarter a year earlier, the 2016 window on."""
    lines = staging["revenue_lines_usd_m"]
    long_from = lines["quarters"].index("Q1 2016")
    yoy = line_yoy(lines, "client_incentives", long_from)
    words = {"threshold": story_threshold(group[0])}
    counts = "；".join(
        f"高于 {entry['threshold']:.0f}% 的有{cn_count(sum(1 for v in yoy if v > entry['threshold']))}季"
        for entry in sorted(group, key=lambda e: e["threshold"]))
    vas = staging["vas_revenue"]
    mix = ""
    if vas["quarters"][-1] == lines["quarters"][-1] and len(vas["quarters"]) >= 5:
        now = vas["usd_bn"][-1] * 1000 / lines["net_revenue"][-1] * 100
        then = vas["usd_bn"][-5] * 1000 / lines["net_revenue"][lines["quarters"].index(vas["quarters"][-5])] * 100
        mix = (f"增值服务占净收入的比重本季约 {now:.1f}%，去年同季约 {then:.1f}%"
               f"（10-Q 的增值服务额只印到 US$0.1B，两个比重各有约 ±0.4 个百分点的取整误差），"
               + ("上一份报告加仓线的另一半条件「增值服务占比继续上升」成立。" if now > then else
                  "上一份报告加仓线的另一半条件「增值服务占比继续上升」不成立。"))
    return threshold_lines_exhibit(
        headline_for("客户激励同比", signed(yoy[-1]), group, mode, key),
        [compact_period(q) for q in lines["quarters"][long_from:]],
        [{"name": "Client incentives 同比", "values": rounded(yoy), "color": "NAVY"}], group, mode,
        fmt="pct1", ylab="同比增速", xstep=LONG_STEP,
        note=(
            f"本季 {signed(yoy[-1])}、上季 {signed(yoy[-2])}，两个数都是收入附注里的激励行相除（D）。"
            + fill_story(group[0].get("rationale", ""), words)
            + f"{cn_count(len(yoy))}个季度里，{counts}。"
            + mix
        ),
        src_extra="各季 10-Q 收入分解附注的 Client incentives 行；增值服务额取自 10-Q 收入附注。",
    )


def track_vas_yoy(staging: dict, group: list[dict], mode: str, key: str) -> dict:
    """Value-added services growth as the 10-Q printed it -- a short record by disclosure."""
    vas = staging["vas_revenue"]
    growth = vas["growth_printed_pct"]
    first = next(i for i, value in enumerate(growth) if value is not None)
    quarters = vas["quarters"][first:]
    values = growth[first:]
    holes = [q for q, value in zip(quarters, values) if value is None]
    words = {"threshold": story_threshold(group[0])}
    return threshold_lines_exhibit(
        headline_for("增值服务收入同比", f"{values[-1]:+.0f}%" if values[-1] is not None else "本季未印",
                     group, mode, key),
        [compact_period(q) for q in quarters],
        [{"name": "增值服务收入名义同比（10-Q 印）", "values": values, "color": "NAVY"}], group, mode,
        fmt="pct0", ylab="同比增速",
        note=(
            "增速是 10-Q 自己印的名义同比；公司从截至 "
            f"{vas['period_ends'][first]} 的 10-Q 起才按季印增值服务收入并给增速，所以线从 {quarters[0]} 开始。"
            + (joined(holes) + " 是会计第四季，只有 10-K 的全年数，季度增速没有印，那一格空着。" if holes else "")
            + fill_story(group[0].get("rationale", ""), words)
        ),
        src_extra="各季 10-Q 收入附注与 MD&A 的「value-added services」段。",
    )


def track_cross_border_gap(staging: dict, group: list[dict], mode: str, key: str) -> dict:
    quarters, constant, nominal = cross_border_gaps(staging)
    words = {"threshold": story_threshold(group[0])}
    reading = (f"本季 {constant[-1]:.0f}pp、上季 {constant[-2]:.0f}pp" if mode == "prior"
               else f"{constant[-1]:.0f}pp")
    both = [q for q, n in zip(quarters, nominal) if n is not None]
    # A run-length rule ("two quarters running at or above 6pp") read on both
    # bases: the two reports this chart settles use different ones, and the
    # verdict can differ between them -- which is worth saying, not choosing.
    basis_words = ""
    for entry in group:
        run = entry.get("quarters")
        if not run or None in nominal[-run:]:
            continue
        on_constant = all(value >= entry["threshold"] for value in constant[-run:])
        on_nominal = all(value >= entry["threshold"] for value in nominal[-run:])
        rule = f"连续{cn_count(run)}季都不低于 {story_threshold(entry)}"
        if on_constant == on_nominal:
            basis_words += f"「{rule}」这条在两个口径下判定相同，都{'触发' if on_constant else '没有触发'}。"
        else:
            basis_words += (f"「{rule}」这条<b>换一个口径判定就不同</b>：恒定汇率口径"
                            f"{'触发' if on_constant else '没有触发'}，名义口径{'触发' if on_nominal else '没有触发'}；"
                            "本页按上一份报告设阈值时的口径结算，两条线都画出来。")
    return threshold_lines_exhibit(
        headline_for("跨境交易额增速 − 国际交易收入增速", reading, group, mode, key),
        [compact_period(q) for q in quarters],
        [{"name": "恒定汇率口径（上一份报告设阈值时用的口径）", "values": constant, "color": "NAVY"},
         {"name": "名义口径（本季报告改用的口径）", "values": nominal, "color": "GOLD"}],
        group, mode, fmt="pp0", ylab="百分点", xstep=LONG_STEP,
        note=(
            "两边都是当季新闻稿印的整数增速：跨境交易额取不含欧洲区内的那一行（它才对应国际交易收入），"
            "差值是本页相减（D），每一格有约 ±1 个百分点的取整误差。"
            f"不含欧洲区内的增速从 {quarters[0]} 起才有 —— FY2020 Q3 的新闻稿第一次印这一栏并往回滚了四季，"
            f"名义那一栏从 {both[0]} 起。"
            f"恒定汇率口径本季 {constant[-1]:.0f}pp、上季 {constant[-2]:.0f}pp；"
            f"名义口径本季 {nominal[-1]:.0f}pp、上季 {nominal[-2]:.0f}pp。"
            + basis_words
            + fill_story(group[0].get("rationale", ""), words)
        ),
        src_extra="各季业绩 8-K EX-99.1 的 Key Business Drivers 表与收入表；逐格出处在 series 里。",
    )


TRACKS = {
    "nongaap_opex_yoy": track_nongaap_opex,
    "us_payments_yoy": track_us_payments,
    "yoy:revenue_lines_usd_m.international_transaction": track_intl_yoy,
    "escrow_surplus": track_escrow,
    "incentives_yoy": track_incentives_yoy,
    "vas_yoy": track_vas_yoy,
    "cross_border_gap": track_cross_border_gap,
}


def threshold_charts(staging: dict, entries: list[dict], mode: str = "next") -> list[dict]:
    """One chart per tracked series, every threshold set on it drawn as its own line.

    Used for both halves of the settlement cycle: section three draws this
    report's thresholds against today's readings (``mode="next"``, readings
    under ``current``), and next quarter section one draws the same entries --
    moved into `prior_kpi_settlement` by editing the series -- against that
    quarter's readings (``mode="prior"``, under ``actual``). A threshold whose
    series has no chart here simply has no chart; its headroom bar still shows.
    """
    key = "actual" if mode == "prior" else "current"
    groups: dict[str, list[dict]] = {}
    for entry in entries:
        groups.setdefault(entry.get("chart", entry["reads"]), []).append(entry)
    charts = []
    for chart_key, group in groups.items():
        track = TRACKS.get(chart_key)
        if track is not None:
            charts.append(track(staging, group, mode, key))
    return charts


def settlement_values(staging: dict) -> dict[str, str]:
    """Numbers a stamped settlement sentence may name, computed from the series."""
    vas = staging["vas_revenue"]["growth_printed_pct"]
    _, constant, nominal = cross_border_gaps(staging)

    def pct(value):
        return "未印" if value is None else f"{value:+.0f}%"

    def pp(value):
        return "未印" if value is None else f"{value:.0f}pp"

    return {
        "vas_now": pct(vas[-1]), "vas_prev": pct(vas[-2]),
        "gap_constant_now": pp(constant[-1]), "gap_constant_prev": pp(constant[-2]),
        "gap_nominal_now": pp(nominal[-1]), "gap_nominal_prev": pp(nominal[-2]),
        "litigation": usd_m(staging["financials"]["litigation_provision_usd_m"][-1] or 0.0),
    }


def closure_exhibit(closure: dict, values: dict[str, str]) -> dict:
    """Last report's questions, each under the verdict the quarter's report gave it.

    The counts are derived from the items, so a label and its tally cannot
    disagree; the note prints every item with its verdict word for word.
    """
    labels = closure["labels"]
    items = closure["items"]
    stray = sorted({item["label"] for item in items} - set(labels))
    if stray:
        raise ValueError(f"followup_closure items carry labels {stray} the block does not list")
    counts = [sum(1 for item in items if item["label"] == label) for label in labels]
    if 0 in counts:
        raise ValueError("followup_closure lists a label no item carries")
    return {
        "kind": "bars_labeled",
        "title": (f"上季 {len(items)} 条待验证问题："
                  + "、".join(f"{count} 条{label}" for label, count in zip(labels, counts))),
        "xlabels": labels,
        "values": counts,
        "legend": "问题条数",
        "fmt": "f0",
        "yfmt": "f0",
        "label_fmt": "f0",
        "ylab": "条",
        "note": (fill_story(closure["note"], values) + "<br>"
                 + "<br>".join(f"{item['n']}. {item['question']} —— <b>{item['verdict']}</b>："
                               f"{fill_story(item['evidence'], values)}。" for item in items)),
        "src_extra": (f"问题清单：{closure['set_in']}；判定：{closure['closed_in']}；"
                      "证据回本季与上季的业绩 8-K EX-99.1 与 10-Q 核过。"),
    }


def prior_headroom(prior: dict, readable: list[dict], unread: list[dict], values: dict[str, str]) -> dict:
    held = sum(1 for entry in readable if is_held(entry, "actual"))
    missing = [f"{item['metric']}（原文「{item['words']}」）—— {item['why']}"
               for item in prior.get("unsettleable", [])]
    missing += [f"{entry['metric']} —— 本季没有申报读数" for entry in unread]
    return headroom_exhibit(
        f"上季 {len(readable)} 条量化阈值：{held} 条守住、{len(readable) - held} 条击穿",
        readable, "actual",
        note=(fill_story(prior["note"], values)
              + (f"另有{cn_count(len(missing))}条画不成柱：" + "；".join(missing) + "。" if missing else "")),
        src_extra=f"阈值：{prior['set_in']}，不是公司指引；实际值：本季业绩 8-K 与 10-Q 的申报值。",
    )


# Every quarter after this one settles the report before it: Q2 2026's report
# set section-8 thresholds, so a later quarter without `prior_kpi_settlement`
# would drop them without a word. The build stops instead.
SETTLED_FROM = "Q2 2026"


def quarter_order(label: str) -> tuple[int, int]:
    quarter, year = label.split()
    return int(year), int(quarter[1])


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    fin = staging["financials"]
    return [f"Net revenue ${fin['net_revenue_usd_m'][-1] / 1000:.1f}B",
            f"激励率 {fin['incentive_rate_pct'][-1]:.1f}%",
            f"GAAP OpM {fin['operating_income_usd_m'][-1] / fin['net_revenue_usd_m'][-1] * 100:.1f}%"]


def build_payload(staging: dict) -> dict:
    financials = staging["financials"]
    periods = staging["periods"]
    period = periods[-1]
    latest = latest_block(staging, period=period, period_end=staging["period_ends"][-1])
    release = release_source(staging)
    closure = stamped_block(staging, "followup_closure", period)
    prior = stamped_block(staging, "prior_kpi_settlement", period)
    if prior is None and quarter_order(period) > quarter_order(SETTLED_FROM):
        raise ValueError(f"the report before {period} set section-8 thresholds: stamp "
                         f"`prior_kpi_settlement` (and `followup_closure`) for {period}")
    next_kpi = stamped_block(staging, "next_kpi", period)
    reconciliation = stamped_block(staging, "opex_reconciliation", period)
    story = stamped_block(staging, "quarter_story", period)
    lines = staging["revenue_lines_usd_m"]
    net_revenue = financials["net_revenue_usd_m"]
    gross = financials["gross_revenue_usd_m"]
    rate = financials["incentive_rate_pct"]
    operating_income = financials["operating_income_usd_m"]
    margin = [income / revenue * 100
              for income, revenue in zip(operating_income, net_revenue)]
    full_rate = lines["incentive_rate_pct"]
    fiscal_now = staging["fiscal_labels"][-1]
    if lines["quarters"][-1] != period or lines["fiscal_labels"][-1] != fiscal_now:
        raise ValueError("revenue_lines_usd_m does not end on the page's quarter")

    # The 2016-onward window. `revenue_lines_usd_m` carries net revenue back to
    # Q4 2012 and `income_long_usd_m` carries operating income back to Q4 2015,
    # so both of the charts below run the whole window off series that were
    # already reconciled against the eight quarters the page used to show.
    long_from = lines["quarters"].index("Q1 2016")
    long_quarters = lines["quarters"][long_from:]
    long_labels = [compact_period(q) for q in long_quarters]
    long_net_revenue = lines["net_revenue"][long_from:]
    income_long = staging["income_long_usd_m"]
    inc_from = income_long["quarters"].index("Q1 2016")
    long_operating_income = income_long["operating_income_usd_m"][inc_from:]
    assert income_long["quarters"][inc_from:] == long_quarters
    long_margin = [income / revenue * 100 for income, revenue
                   in zip(long_operating_income, long_net_revenue)]

    # ── section one ─────────────────────────────────────────────────────────
    facts = guidance_facts(staging)
    guidance_ex = incentive_guidance_charts(staging, facts)
    record = staging["incentive_guidance"]
    settled_ex = []
    story_numbers = settlement_values(staging)
    if closure:
        settled_ex.append(closure_exhibit(closure, story_numbers))
    prior_entries = []
    if prior:
        prior_entries = kpi_entries(prior, staging, "actual")
        readable = [entry for entry in prior_entries if entry["actual"] is not None]
        unread = [entry for entry in prior_entries if entry["actual"] is None]
        settled_ex.append(prior_headroom(prior, readable, unread, story_numbers))
        settled_ex += threshold_charts(staging, readable, "prior")
        prior_entries = readable
    settled_ex += guidance_ex

    # ── section two ─────────────────────────────────────────────────────────
    net_yoy = [None if i < 4 else pct_change(long_net_revenue[i], long_net_revenue[i - 4])
               for i in range(len(long_net_revenue))]
    negative = [i for i, value in enumerate(net_yoy) if value is not None and value < 0]
    runs, run = [], []
    for i in negative:
        if run and i != run[-1] + 1:
            runs.append(run)
            run = []
        run.append(i)
    if run:
        runs.append(run)
    fiscal_long = lines["fiscal_labels"][long_from:]
    gross_yoy = pct_change(gross[-1], gross[-5])
    net_yoy_now = pct_change(net_revenue[-1], net_revenue[-5])
    # compared at the precision the page prints them, so 「更快」 never sits
    # between two equal-looking numbers
    faster = ("gross" if round(gross_yoy, 1) > round(net_yoy_now, 1) else
              "net" if round(net_yoy_now, 1) > round(gross_yoy, 1) else "same")
    lows = sorted(range(len(long_margin)), key=long_margin.__getitem__)
    pandemic = [i for i in range(len(long_margin)) if long_quarters[i].endswith("2020")]
    pandemic_low = min(pandemic, key=long_margin.__getitem__) if pandemic else None
    next_lows = [i for i in lows[1:4]]
    highlight_ex = [
        {
            "kind": "gs_bar",
            "title": (
                f"净收入 US${net_revenue[-1]:,.0f}M、同比 "
                f"{signed(net_yoy_now)}；"
                f"毛收入同比 {signed(gross_yoy)}"
            ),
            "xlabels": long_labels,
            "xstep": LONG_STEP,
            "values": rounded(long_net_revenue),
            "legend": "净收入",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "US$M",
            "ylab2": "同比增速",
            "yoy": {
                "name": "净收入 YoY (RHS)",
                "values": rounded(net_yoy),
                "color": "GREEN",
                "yfmt": "pct1",
            },
            "note": (
                "净收入是四条毛收入线减去客户激励之后的数，公司损益表上的第一行。"
                f"本季毛收入同比 {signed(gross_yoy)}、"
                f"净收入同比 {signed(net_yoy_now)}"
                + (" —— 两者相差的那一截就是激励率上行，下一张图专门讲它。"
                   if faster == "gross" else "。")
                + (f"<b>{cn_count(len(long_net_revenue))}个季度里只有一段负增长</b>："
                   f"{long_quarters[runs[0][0]]} 到 {long_quarters[runs[0][-1]]} 这"
                   f"{cn_count(len(runs[0]))}个季度（公司 {fiscal_words(fiscal_long[runs[0][0]])} 至 "
                   f"{fiscal_words(fiscal_long[runs[0][-1]])}），最深一格是 "
                   f"{long_quarters[min(runs[0], key=lambda i: net_yoy[i])]} 的 "
                   f"{net_yoy[min(runs[0], key=lambda i: net_yoy[i])]:+.1f}%".replace("-", "−")
                   + "；在那之前和之后，净收入同比没有一个季度落到零以下。"
                   if len(runs) == 1 else "")
            ),
            "src_extra": "各季 10-Q 合并损益表。",
        },
        incentive_quarter(staging),
        quarter_revenue_lines(staging),
        {
            "kind": "lines",
            "title": (
                f"GAAP 营业利润率 {margin[-1]:.1f}%，同比 {signed(margin[-1] - margin[-5], 1, 'pp')}；"
                f"{cn_count(len(long_margin))}季里的最低一格是 {min(long_margin):.1f}%"
            ),
            "xlabels": long_labels,
            "xstep": LONG_STEP,
            "series": [
                {"name": "GAAP 营业利润率", "values": rounded(long_margin), "color": "NAVY"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "end_label": True,
            "ylab": "营业利润率",
            "note": (
                "<b>这条线是 GAAP 口径。</b>"
                "公司口径的 non-GAAP 利润率需要剔除诉讼计提、遣散费、并购摊销等特殊项，"
                "而每一季剔除哪几项由公司当季决定，"
                "把一条 non-GAAP 利润率连起来会把口径变化画成经营变化"
                + ("；本季的 non-GAAP 读数只拿同一份对账表的本季栏与去年同季栏相比，见 Exhibit {EX_WEDGE}。"
                   if reconciliation else "。")
                + "<b>而 GAAP 口径本身也不是一条平线</b>："
                + (f"2016 年 6 月止季只有 {min(long_margin):.1f}%，"
                   "那一季记了一笔 US$1,877M 的 Visa Europe Framework Agreement loss"
                   "（收购 Visa Europe 时对双方框架协议的实质清算，不是诉讼准备），"
                   "把营业利润压到了净收入的十分之一出头；"
                   if long_quarters[lows[0]] == "Q2 2016" else
                   f"最低一格是 {long_quarters[lows[0]]} 的 {min(long_margin):.1f}%；")
                + "除那一格之外，最低的几格是 "
                + "、".join(f"{long_quarters[i]}（{long_margin[i]:.1f}%）" for i in next_lows)
                + (f"；2020 年疫情季最低只到 {long_quarters[pandemic_low]} 的 {long_margin[pandemic_low]:.1f}%，"
                   "那次是收入端而不是费用端。" if pandemic_low is not None and pandemic_low not in next_lows
                   else "。")
                + (f"本季 GAAP 口径里有公司剔除的{cn_count(len(reconciliation['items']))}项，"
                   "读同比时要连着那张对账图一起看。" if reconciliation else "")
            ),
            "src_extra": "各季 10-Q 合并损益表。",
        },
    ]
    vas_chart = vas_exhibit(staging)
    if vas_chart:
        highlight_ex.insert(3, vas_chart)
    if reconciliation:
        highlight_ex.append(opex_reconciliation_exhibit(staging, reconciliation))
    highlight_ex.append(escrow_exhibit(staging))

    # ── section three ───────────────────────────────────────────────────────
    entries = kpi_entries(next_kpi, staging) if next_kpi else []
    band = non_vas_growth_band(staging)
    band_words = ({"non_vas_low": signed(band[0]), "non_vas_high": signed(band[1])} if band
                  else {"non_vas_low": "—", "non_vas_high": "—"})
    excluded = [fill_story(text, band_words) for text in (next_kpi.get("excluded", []) if next_kpi else [])]
    excluded += [f"{entry['metric']} —— 本季没有申报读数" for entry in entries if entry["current"] is None]
    entries = [entry for entry in entries if entry["current"] is not None]
    next_ex = []
    if entries:
        next_ex.append(headroom_exhibit(
            f"下季 {len(entries)} 条阈值与当前值的距离（正数 = 仍在安全侧）",
            entries, "current",
            note=(
                f"阈值与方向逐字取自{next_kpi['set_in']}，是研究设定，不是公司指引，也不是评级。"
                "把百分比与美元金额归一到「距阈值余量」这一个口径，"
                "是为了让一张图能同时回答「哪几条已经越线」；当前值是本季读数，阈值是给下一季的。"
                + (f"另有{cn_count(len(excluded))}条本页<b>不接入</b>，原因写在这里而不是省略掉："
                   + "；".join(excluded) + "。" if excluded else "")
            ),
            src_extra="当前值全部来自本季 10-Q 与业绩 8-K 的申报值。",
        ))
        next_ex += threshold_charts(staging, entries, "next")

    # ── section four ────────────────────────────────────────────────────────
    routine_ex = [
        incentive_rate_long(staging),
        service_yield_long(staging),
        margin_long(staging),
        revenue_mix_long(staging),
        geography_long(staging),
        capital_return_long(staging),
    ]

    exhibits = number_exhibits(settled_ex + highlight_ex + next_ex + routine_ex, start=2)
    resolve_exhibit_refs(exhibits)
    first_table = exhibits[-1]["n"] + 1

    # ── audit tables ────────────────────────────────────────────────────────
    guide_rows = [
        [f"FY{entry['fiscal_year']}",
         f"{entry['lo']:.1f}%–{entry['hi']:.1f}%",
         f"{entry['actual_pct']:.2f}%",
         "跌破下限（少返给客户）" if entry["actual_pct"] < entry["lo"] else
         "高于上限（多返给客户）" if entry["actual_pct"] > entry["hi"] else "区间内",
         f"{entry['actual_pct'] - (entry['lo'] + entry['hi']) / 2:+.2f}pp",
         f"毛收入 ${entry['gross_revenue_usd_m']:,.0f}M · 激励 ${-entry['client_incentives_usd_m']:,.0f}M",
         entry["released"]]
        for entry in facts["entries"]
    ]

    quarterly_rows = [
        [periods[index], staging["fiscal_labels"][index],
         f"${gross[index]:,.0f}M",
         f"${-financials['client_incentives_usd_m'][index]:,.0f}M",
         f"{rate[index]:.2f}%",
         f"${net_revenue[index]:,.0f}M",
         signed(pct_change(net_revenue[index], net_revenue[index - 4])) if index >= 4 else "—",
         f"${financials['total_opex_usd_m'][index]:,.0f}M",
         f"${operating_income[index]:,.0f}M",
         f"{margin[index]:.2f}%"]
        for index in range(len(periods))
    ]

    line_rows = [
        [lines["quarters"][index], lines["fiscal_labels"][index],
         f"${lines['service'][index]:,.0f}M",
         f"${lines['data_processing'][index]:,.0f}M",
         f"${lines['international_transaction'][index]:,.0f}M",
         f"${lines['other'][index]:,.0f}M",
         f"${lines['gross_revenue'][index]:,.0f}M",
         f"${-lines['client_incentives'][index]:,.0f}M",
         f"{lines['incentive_rate_pct'][index]:.2f}%",
         f"${lines['net_revenue'][index]:,.0f}M",
         "10-K 全年减九个月 D" if lines["basis"][index] == "fy_minus_9m" else "10-Q 申报三个月栏"]
        for index in range(len(lines["quarters"]) - 21, len(lines["quarters"]))
    ]

    litigation = staging["litigation"]
    litigation_rows = [
        [litigation["quarters"][index],
         f"${litigation['escrow_usd_m'][index]:,.0f}M",
         f"${litigation['us_covered_litigation_usd_m'][index]:,.0f}M"
         if litigation["us_covered_litigation_usd_m"][index] is not None else "—",
         f"${litigation['escrow_usd_m'][index] - litigation['us_covered_litigation_usd_m'][index]:,.0f}M D"
         if litigation["us_covered_litigation_usd_m"][index] is not None else "—",
         f"${litigation['accrued_litigation_total_usd_m'][index]:,.0f}M"
         if litigation["accrued_litigation_total_usd_m"][index] is not None else "—"]
        for index in range(len(litigation["quarters"]) - 13, len(litigation["quarters"]))
    ]

    capital = staging["capital_allocation_usd_m"]
    capital_rows = [
        [capital["quarters"][index],
         f"${capital['operating_cash_flow'][index]:,.0f}M"
         if capital["operating_cash_flow"][index] is not None else "—",
         f"${-capital['capex'][index]:,.0f}M" if capital["capex"][index] is not None else "—",
         f"${-capital['buyback'][index]:,.0f}M" if capital["buyback"][index] is not None else "—",
         f"${-capital['dividends'][index]:,.0f}M" if capital["dividends"][index] is not None else "—",
         "10-Q 三个月栏" if capital["basis"][index] == "filed_3m" else "相邻两次年初至今之差 D"]
        for index in range(len(capital["quarters"]) - 13, len(capital["quarters"]))
    ]

    tables = [
        {
            "n": first_table,
            "title": (f"Visa 申报文件里的客户激励率指引记录，"
                      f"FY{facts['first']}–FY{facts['last']}"),
            "headers": ["财年", "指引区间", "实际", "兑现", "相对中值", "构成", "指引发布日"],
            "rows": guide_rows,
        },
    ]
    if prior_entries:
        tables.append(threshold_table(first_table + len(tables), "上季阈值与本季实际（原单位）",
                                      prior_entries, "actual", "本季实际"))
    if entries:
        tables.append(threshold_table(first_table + len(tables), "下季阈值与当前值（原单位）",
                                      entries, "current", "当前值"))
    tables += [
        {
            "n": first_table + len(tables),
            "title": "八季度毛收入、激励与利润率",
            "headers": ["期间", "公司口径", "毛收入", "客户激励", "激励率 D", "净收入",
                        "净收入 YoY", "营业费用", "营业利润", "营业利润率 D"],
            "rows": quarterly_rows,
        },
    ]
    tables += [
        {
            "n": first_table + len(tables),
            "title": "近二十一季四条毛收入线与激励（每季注明是申报三个月栏还是差分）",
            "headers": ["期间", "公司口径", "Service", "Data processing",
                        "International transaction", "Other", "毛收入 D", "客户激励",
                        "激励率 D", "净收入", "取数方式"],
            "rows": line_rows,
        },
    ]
    recon = staging["nongaap_recon_usd_m"]
    printed_opex = dict(zip(staging["nongaap_opex"]["quarters"], staging["nongaap_opex"]["growth_printed_pct"]))
    margins = {q: (m1, m0, change) for q, m1, m0, change in margin_changes(staging)}
    tables += [
        {
            "n": first_table + len(tables),
            "title": (f"公司口径营业费用对账：{recon['quarters'][0]} 起每份新闻稿的本季栏与去年同季栏"),
            "headers": ["期间", "non-GAAP 营业费用", "去年同季（同一份表）", "同比 D", "公司印的同比",
                        "non-GAAP 营业利润率 D", "去年同季 D", "变化 D"],
            "rows": [
                [q, f"${now:,.0f}M", f"${then:,.0f}M", signed(pct_change(now, then)),
                 f"{printed_opex[q]:+.0f}%" if q in printed_opex else "—",
                 f"{margins[q][0]:.2f}%" if q in margins else "—",
                 f"{margins[q][1]:.2f}%" if q in margins else "—",
                 signed(margins[q][2], 2, "pp") if q in margins else "—"]
                for q, now, then in zip(recon["quarters"], recon["nongaap_opex"], recon["prior_year_nongaap_opex"])
            ],
        },
    ]
    tables += [
        {
            "n": first_table + len(tables),
            "title": "近十三季诉讼托管账户与两个计提口径",
            "headers": ["期间", "托管账户", "U.S. covered 计提",
                        "盈余 / 缺口 D", "计提合计（含未覆盖）"],
            "rows": litigation_rows,
        },
    ]
    tables += [
        {
            "n": first_table + len(tables),
            "title": "近十三季现金流与股东回报",
            "headers": ["期间", "经营现金流", "资本开支", "回购", "分红", "取数方式"],
            "rows": capital_rows,
        },
    ]
    tables.append(ai_capex_cycle_table(first_table + len(tables)))

    latest_rate = full_rate[-1]
    stopped = record["stopped_after_fiscal_year"]
    years_since = int(fiscal_now[2:6]) - stopped
    surplus_now = litigation["escrow_usd_m"][-1] - litigation["us_covered_litigation_usd_m"][-1]
    n_guided = len(facts["entries"])
    story_values = {"quarter_fiscal": fiscal_words(fiscal_now)}
    not_wired = [fill_story(text, story_values) for text in (story or {}).get("not_wired", [])]
    aligned = staging["operating_volumes"]["payments_volume_quarters"][-1]
    articles = [
        '<article><span>记录</span><b>激励率的数字指引，停在'
        + cn_count(years_since) + '年前</b>'
        f'<p>FY{facts["first"]}–FY{facts["last"]} 公司在申报文件里给过{cn_count(n_guided)}次激励率区间，'
        f'{cn_count(len(facts["below"]))}次实际低于下限（少返给客户）'
        + (f'、{cn_count(len(facts["above"]))}次高于上限' if facts["above"] else "")
        + f'。此后停止披露，比率从 {facts["entries"][-1]["actual_pct"]:.1f}% 走到 {latest_rate:.2f}%。</p></article>',
        '<article><span>本季</span><b>'
        + ("毛收入比净收入快" if faster == "gross" else
           "净收入比毛收入快" if faster == "net" else "毛收入与净收入一样快") + '</b>'
        f'<p>毛收入同比 {signed(gross_yoy)}、'
        f'净收入 {signed(net_yoy_now)}；'
        f'激励率同比 {signed(latest_rate - full_rate[-5], 2, "pp")}，'
        + incentive_effect(gross[-1], latest_rate, full_rate[-5], short=True) + '。</p></article>',
    ]
    if surplus_now >= 0 and litigation["escrow_usd_m"][-1] < litigation["accrued_litigation_total_usd_m"][-1]:
        articles.append(
            '<article><span>更正</span><b>托管账户没有欠资</b>'
            f'<p>US${litigation["escrow_usd_m"][-1]:,.0f}M 对应的是 U.S. covered 计提 '
            f'US${litigation["us_covered_litigation_usd_m"][-1]:,.0f}M，'
            f'盈余 US${surplus_now:,.0f}M；'
            '拿它去比计提合计才会看出「缺口」。</p></article>')

    return {
        "schema_version": "quarterly-dashboard/v-v1",
        "page": {"slug": "v", "language": "zh-CN"},
        "company": {
            "ticker": "V",
            "name": "Visa",
            "group": "payment_networks",
            "accounting_standard": "US GAAP",
        },
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · V",
        "title": f"Visa (V)：{period} 季报仪表盘",
        "subtitle": (
            f"截至 {latest['period_end']} · 发布 {latest['release_date']} · US GAAP · "
            f"{ {'unaudited': '未审计', 'audited': '已审计'}[latest['audit_status']] } · "
            f"9 月制财年，本站按自然年季度标注：本页 {period} 即公司所称 {fiscal_words(fiscal_now)}"
        ),
        "headline": (
            f"净收入 US${net_revenue[-1]:,.0f}M、同比 "
            f"{signed(net_yoy_now)}，"
            f"毛收入同比 {signed(gross_yoy)}"
            + (f" 更快 —— 差的那一截是客户激励率升到 {latest_rate:.2f}%，"
               if faster == "gross" and latest_rate > full_rate[-5] else
               f"，客户激励率 {latest_rate:.2f}%，")
            + f"同比 {signed(latest_rate - full_rate[-5], 2, 'pp')}。"
            f"这个比率在本页的 {len(full_rate)} 个季度里从 {full_rate[0]:.1f}% 一路走到今天，"
            f"而 Visa 曾在 FY{facts['first']}–FY{stopped} 每个财年开局的申报文件里给过它的数字区间"
            + "".join(f"（{item['metric']}也给过区间，例如 FY{item['fiscal_year']} 的 {item['range']}）"
                      for item in record.get("other_numeric_ranges", [])[:1])
            + ("" if record.get("other_numeric_ranges") else " ")
            + f"—— 给到 FY{stopped} 为止，此后再没给过。"
        ),
        "brief": (
            f'<h4>本季{cn_count(len(articles))}条主线</h4><div class="takeaway-grid">'
            + "".join(articles)
            + '</div>'
        ),
        "source": (
            f'Source: <a href="{release["url"]}" rel="noopener">Visa {fiscal_words(fiscal_now)} '
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
                    (prior["lead"] if prior and prior.get("lead") else
                     "先结清上一份笔记留下的问题，再看新数字。" if closure else "")
                    + ("再结清公司自己给过的指引，这一半和本站其他几页不一样。" if prior or closure
                       else "这一节和本站其他几页不一样。")
                    + no_guidance_note(record)
                    + "公司自己的指引里能结算的只剩一件事，但它恰好是本页最要紧的那件 —— "
                    f"公司曾经连续{cn_count(n_guided)}年在申报文件里给出<b>客户激励率</b>的数字区间，"
                    "而那正是本页从头讲到尾的那个比率。"
                ),
                "exhibits": settled_ex,
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": plain_text(highlights_description(
                    staging, vas_chart, reconciliation, story or {},
                    any(ex["title"].startswith("跨境交易额增速 − 国际交易收入增速") for ex in settled_ex))),
                "exhibits": highlight_ex,
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": plain_text(
                    (f"阈值与方向逐字取自{next_kpi['set_in']}；当前值取自本季申报，"
                     "统一用「距阈值余量」口径，再逐条画出它的历史。"
                     + (f"另有{cn_count(len(excluded))}条画不了，原因写在总览图的图注里，不给近似值。"
                        if excluded else ""))
                    if entries else "本季没有新立的下季阈值，本节没有图。"
                ),
                "exhibits": next_ex,
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": plain_text(
                    f"V 专属的常规序列：{cn_count((len(lines['quarters']) - 1) // 4)}年的客户激励率、"
                    "Service revenue 对上一季名义支付额的比率、毛收入与净收入的两条增速、四条毛收入线的结构迁移、"
                    "美国以外的收入占比，以及股东回报与自由现金流的关系。"
                ),
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": [plain_text(_p) for _p in [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            f"本页所有季度按自然年标注。Visa 财年 9 月底结束，故本页的 {period} 是截至 {latest['period_end']} 的季度，"
            f"公司自己称之为 {fiscal_words(fiscal_now)}；映射规则为公司 FY 的 Q1→上一自然年 Q4、Q2→Q1、Q3→Q2、Q4→Q3。"
            "不统一成一种约定，跨公司的资本开支对照表就会把不同的三个月放在一起比较。",
            "<b>Visa 从不在申报文件里给季度数字指引，因此本页没有逐季的指引兑现记录。</b>"
            "这是取数限制而不是编辑取舍。它历史上给过的 Financial Outlook 一律是<b>财年</b>口径，"
            "从来没有过下一季度的数字区间，所以「本季指引 → 本季实际」这个对象在 Visa 这里不存在。"
            f"财年口径的那部分也在逐步退场：FY{record['first_guided_fiscal_year']}–FY{stopped} 有 Financial Outlook 小节，"
            "其中客户激励率与有效税率是数字区间，收入与 EPS 多为「mid-teens」这类文字区间；"
            "FY2020–FY2021 保留小节但明确不给指引；FY2022–FY2023 多数季度没有该小节；"
            "FY2024 只剩一句指向未在 EDGAR 归档的 earnings presentation；"
            "2025-01-30 之后的历次新闻稿连这句也没有。"
            "微软与 Alphabet 两页出于同样的理由也没有这类记录。"
            "<b>本页不发布「多少份新闻稿里有几份给了数字」这类计数</b> —— "
            + release_count_words(staging, facts) + "，抽样得到的比例会失真。",
            "客户激励率是其中逐年都给了数字区间的一条：「Client incentives as a percent of gross revenues」"
            f"在 FY{facts['first']}–FY{facts['last']} 每个财年开局的业绩新闻稿「Financial Outlook」块里都是一个数字区间，"
            f"本页第一节把这{cn_count(n_guided)}年逐年对上了该财年 10-K 的实际值。"
            f"{cn_count(n_guided)}年里{cn_count(len(facts['below']))}年实际低于指引下限"
            + (f"、没有一年高于上限" if not facts["above"] else f"、{cn_count(len(facts['above']))}年高于上限")
            + " —— 方向上是<b>好消息</b>，返给客户的钱比承诺的少。"
            f"FY{stopped} 之后公司停止给这个数字：FY2024 的 outlook 块完全不提客户激励，FY2026 的新闻稿没有 outlook 小节。",
            "激励率 = Client incentives ÷（Service + Data processing + International transaction + Other 四条毛收入线之和）。"
            "五个数都是各季 10-Q、10-K 收入分解附注里的申报值，比率是申报值之间的除法，不含任何估计；"
            f"四条毛收入线减去激励等于申报净收入，{len(lines['quarters'])} 个季度逐季核对全部相等。",
            "会计季 Q1–Q3 的损益表数字直接取自 10-Q 自己印的三个月栏，无需差分；"
            "会计季 Q4 没有 10-Q，其损益表各行为 10-K 全年数减去 6 月 10-Q 的九个月栏，两端都是申报值，核对表逐行标注。"
            "现金流量表在 10-Q 里只有年初至今栏，因此除会计第一季外每季均为相邻两次申报值之差。",
            "<b>每股口径在会计季 Q4 是空档而不是推算值。</b>"
            "EPS 不是可加项，加权平均股数也无法由减法还原，"
            "因此本页不对会计第四季给出 Class A 摊薄 EPS 或股数，也不用全年数去近似。",
            "<b>Service revenue 不对着当季支付额增速去读。</b>"
            "公司在每份业绩新闻稿里都写明：Service revenue 按<b>上一季度</b>的支付额确认，"
            "其余收入线按<b>当季</b>活动确认；而新闻稿开头的「Key Business Drivers」表印的是<b>当季</b>支付额。"
            "把两者对齐来看会整整错开一个季度。"
            "能对齐的那一组数据在申报文件里：10-Q 的 MD&A 按季印着上一季的<b>名义支付额</b>美元金额"
            + (f"（本季 10-Q 印的是 {aligned} 那一季的 "
               f"US${staging['operating_volumes']['nominal_payments_volume_usd_b'][-1]:,.0f}B）"
               if aligned == lines["quarters"][-2] and not fiscal_now.endswith("Q4") else "")
            + "，本页据此画了「Service revenue ÷ 上一季名义支付额」那张图"
            "（4–6 月那一季没有单独一栏，取 10-K 十二个月栏减 6 月 10-Q 九个月栏）。"
            "国际交易收入按<b>当季</b>跨境活动确认，所以它可以直接对着同一张表里当季的跨境交易额增速读，"
            "本页第一节画的就是两者之差；跨境交易额只印<b>同比百分比</b>、不印金额，"
            "所以国际交易收入的单位变现率只能复算它的同比变化，复算不出水平。",
            "诉讼托管账户与计提额的对照口径：美国追溯责任计划下的托管账户只为偿付 "
            "<b>U.S. covered litigation</b> 而存在，资产负债表上的「Accrued litigation」合计还包含 "
            "VE Territory covered 与不在覆盖范围内的诉讼。10-Q 的法律事项附注把 U.S. covered 计提单独印成一张表"
            "（XBRL 里这组表叫「Schedule of Accrued Litigation for Both Covered and Non-Covered Litigation」），"
            "因此本页用托管账户对 U.S. covered 计提，"
            "并在图上同时画出计提合计，标明它不是托管账户负责的对象。",
            "自由现金流是本页自算口径（D）：经营现金流减去购置不动产、设备与技术的现金支出。"
            "公司自己不发布自由现金流数字，也没有自定义口径可援引。",
            "核对抽屉最后那张「AI capex 循环」是全站<b>共用</b>的跨页对照块，"
            "在每一页都逐字节相同，不是对 Visa 的判断。"
            "它追的是四家云厂的现金资本开支 → NVDA 数据中心收入 → TSM 晶圆这条链，"
            "Visa 不在这条链的任何一环上：它既不是其中的支出方，也不是供应方。"
            "把它放在这里是为了让读者在任意一页都能查到同一份上下游对照，"
            "而不是暗示支付网络与这条链有关联。它在折叠的抽屉里，不参与本页的论证。",
            "本页只发布公司披露值、可复算的简单派生值，以及明确标注的市场预期；D 标记代表 Derived / 自算。",
            "市场预期一律标注为「市场预期」并给出取数时点，不写卖方机构名，也不发布评级、目标价或估值。",
            "本页已知未接入：跨境交易额的<b>绝对金额</b>（公司只给同比百分比）、"
            "单位跨境交易变现率的水平（只有同比变化能由两个印出的增速复算）、"
            "商业支付（CMS）的分部收入绝对额（公司不在申报文件里拆分）、"
            "消费支付的单独收入口径、公司口径 non-GAAP 营业费用与利润率的<b>水平</b>长序列（每季剔除项由公司当季决定；"
            "本页只发布每份新闻稿自己印的同比增速，以及同一份对账表本季栏与去年同季栏的比较）、"
            + "".join(text + "、" for text in not_wired)
            + "以及任何来自业绩电话会而无法与第二个来源核对的前瞻数字。",
            "业绩电话会文字稿仅链接官方 IR 与 SEC 托管版本，公开仓不复制原件或逐字内容。",
        ]],
        "footer": "V quarterly results · 数据来自 Visa 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "v.js"), payload, "v")
    shell_dir = ROOT / "v"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("V", "v"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(
        f"V page: {charts} charts in {len(payload['sections'])} sections "
        f"+ {len(payload['tables'])} audit tables"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
