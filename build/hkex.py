"""Hong Kong Exchanges and Clearing Limited (00388.HK) quarterly dashboard.

HKEX is a Hong Kong issuer reporting under HKFRS in Hong Kong dollars on a
calendar fiscal year. It is not an SEC registrant, so neither the rendered
statements nor XBRL companyfacts reach it: the forty-two quarterly, interim and
annual results announcements it has published since 2016, together with the ten
annual reports that carry the same years' quarterly tables, are the entire
source. The announcements alone are not: reading only them is what produced the
error described below.

**Three facts about how this company discloses decide what the page can be.**

The first is a clock, not a hole -- and the first draft of this page got it
wrong. The condensed income statement in a first-quarter announcement has a
three-month column, and so does the one in a third-quarter announcement. The
interim announcement prints six months and nothing else; the annual prints
twelve. So the second and fourth quarters are obtained here by subtraction: H1
minus Q1, the full year minus the nine months, twenty-one of the forty-two.
This page originally concluded from that "the second and fourth quarters have
never been printed by anyone". **That is false.** Every annual report carries
an `Analysis of Results by Quarter` table with all four quarters printed as
discrete columns, and it has done so since FY2016; from FY2021 the same table
moved into the annual results announcement. The error was not arithmetic --
every derived cell reproduces the company's own printed one exactly, 296
comparisons across ten years, 148 of them on cells this page derived, no
exceptions. The error was reading one document series and stating the result
as a property of the company.

What is true is the wait, and it is narrower than "even quarters are slow".
A first or third quarter is public 19 to 42 days after it ends, in its own
announcement. A fourth quarter arrives with the annual results announcement,
54 to 79 days out, and has never been the outlier. **It is the second quarter
alone that waited** -- for the annual report, 257 to 263 days, every year from
2016 to 2021. Eight and a half months. From 2022 the interim announcement began
carrying an even-quarter summary box and that collapsed to 47-52 days in a
single step: no second quarter has ever landed between 60 and 250 days, so the
page draws a cliff rather than a trend.

What is genuinely never printed is narrower and more interesting than the
claim it replaced: the **revenue decomposition** of an even quarter. The annual
table ran from "Revenue and other income" downwards until FY2022 added the six
fee lines, so for the twelve even quarters of 2016-2021 -- plus the quarter
just reported, which waits for February 2027 -- no document anywhere splits the
revenue. Thirteen quarters. On those, and only those, the page's own arithmetic
is the only source that exists.

The second is that the volume statistics cannot be subtracted at all. They are
averages per trading day, and a six-month average minus a three-month average
is not the second quarter. So the trick that produces the even quarters for
money does not work for volume, and the quarterly market statistics simply do
not exist before 2021Q1. That is a disclosure floor, not a gap, and the volume
section says so instead of interpolating across it.

The third is the one that changes how the money is read. HKEX reinvests the
margin funds its clearing houses hold and rebates most of the interest back to
Clearing Participants. Gross investment income and the rebate appear **only in
the half-year and annual statements**; the quarterly statement prints a single
net number. Over the twenty-one halves the rebate went from 13 per cent of
gross to 70 per cent and back to 56 -- so the gross line and the net line have
told opposite stories about the same portfolio, twice, and only one of them is
visible at quarterly frequency.

Published figures are company-reported or transparent arithmetic. The company
publishes no financial guidance of any kind -- across the forty-two
announcements, twenty-four forward statements carry a number and not one of
them is a revenue, profit, expense or capital-expenditure figure -- so this
page has no delivery chart, and the thresholds in section three are research
settings rather than anything the company said.

The page runs in the four sections every page on this site uses: what last
quarter's analysis left open and how it settled, this quarter, what to watch
next quarter, and the long-run series. The disclosure-structure charts above
are long-run series about this company's calendar, so they sit in the fourth.
"""

from __future__ import annotations

import datetime
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import (  # noqa: E402
    ai_capex_cycle_table,
    cn_count,
    cn_fraction,
    cn_ordinal,
    display_period,
    headroom,
    headroom_exhibit,
    latest_block,
    minus_sign,
    number_exhibits,
    round_half_up,
    stamped_block,
    threshold_exhibit,
    unit_text,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402

STAGING_PATH = ROOT / "series" / "hkex.json"
DATA_DIR = ROOT / "data"

# One tick per year on the forty-two-quarter axes; one per half-year on the
# twenty-two-quarter volume axes.  The renderer's own font shrinking floors out
# around thirty labels, so a long axis without a step prints an unreadable smear.
LONG_STEP = 4
KPI_STEP = 2

# The ten income-statement lines whose disclosure status the page tracks.  Six
# fee lines plus revenue, revenue and other income, EBITDA and profit
# attributable: everything a reader would use to decompose a quarter.
TRACKED_LINES = [
    "trading_fees", "clearing_fees", "listing_fees", "depository_fees",
    "market_data_fees", "other_revenue", "revenue", "revenue_and_other_income",
    "ebitda", "profit_attributable",
]
# The subset the company prints for an even quarter, in the summary box.
BOX_LINES = ["revenue_and_other_income", "ebitda", "profit_attributable"]


AUDIT_WORDS = {"unaudited": "未审计", "audited": "已审计"}

# The announcement each quarter's results arrive in, by the quarter's number.
ANNOUNCEMENT_KIND = {"1": "第一季度业绩公告", "2": "中期业绩公告",
                     "3": "第三季度业绩公告", "4": "全年业绩公告"}

# The two stretches the gross-and-net chart tells as stories (fixed history):
# rates at the floor, measured from the half the rebate share was last near
# 30 per cent to the half it bottomed; and rates coming back, one year on from
# the half the gross line bottomed.
FLOOR_EPISODE = ("2020H1", "2021H1")
RISE_EPISODE = ("2022H1", "2023H1")


def pct(current: float, base: float) -> float:
    return (current / base - 1) * 100.0


def half_words(staging: dict) -> str:
    """「本半年」 when the page's quarter closes the latest half, else that half by name.

    A first- or third-quarter page reports a half-year that ended a quarter
    earlier; calling it 本半年 there would put last half's rebate under this
    quarter's label.
    """
    last, half = staging["quarters"][-1], staging["halves"][-1]
    closes = half == f"{last[:4]}H{1 if last[5] == '2' else 2}" and last[5] in "24"
    return "本半年" if closes else f"最近一个半年（{half}）"


def announcement_label(period: str) -> str:
    """``'Q2 2026'`` → ``'HKEX 2026 年中期业绩公告'``, the way `sources` labels it."""
    quarter, year = period.split()
    return f"HKEX {year} 年{ANNOUNCEMENT_KIND[quarter[1]]}"


def release_source(staging: dict) -> dict:
    label = announcement_label(display_period(staging["quarters"][-1]))
    found = next((item for item in staging["sources"] if item["label"].startswith(label)), None)
    if found is None:
        raise ValueError(f"series `sources` has no entry for the {label}: add this "
                         "quarter's announcement with the roll")
    return found


def fee_split_gaps(staging: dict) -> tuple[list[str], list[str]]:
    """Quarters whose fee lines nobody has printed, split at FY2022.

    Before FY2022 the annual quarter table stopped at revenue and other income,
    so every even quarter of 2016-2021 is permanent. From FY2022 the table
    carries the fee lines, so an even quarter is missing only until the annual
    results that print its year -- that is the recent part, and it moves.
    """
    missing = never_printed(staging, FEE_LINES)
    return [q for q in missing if q < "2022"], [q for q in missing if q >= "2022"]


def pending_words(staging: dict, recent: list[str], wait: bool = True,
                  spaced: bool = True) -> str:
    """「刚发布的 2026Q2（要等 2027 年 2 月的全年公告）」 for each quarter still waiting.

    ``spaced`` puts the space this site sets between a Chinese word and a period
    label in front of a label that does not start with 「刚发布的」; a caller
    whose text ends in a full-width comma passes False.
    """
    latest = staging["quarters"][-1]
    words = "、".join(("刚发布的 " if quarter == latest else "") + quarter
                      + (f"（要等 {int(quarter[:4]) + 1} 年 2 月的全年公告）" if wait else "")
                      for quarter in recent)
    return words if words.startswith("刚发布的") or not spaced else " " + words


def elasticities(staging: dict) -> dict:
    """Slope and R² of three revenue lines on headline turnover, from the series.

    These used to be read from a block stored beside the arrays; a roll that
    extended the arrays and not the block would have printed last quarter's
    regression under this quarter's axis.
    """
    kq = staging["kpi_quarters"]
    quarters, q = staging["quarters"], staging["quarterly"]
    index_of = [quarters.index(x) for x in kq]
    turnover = qoq(staging["kpi_quarterly"]["adt_headline"])
    out = {"steps": len(turnover)}
    lines = {
        "trading_clearing": [q["trading_fees"][i] + q["clearing_fees"][i] for i in index_of],
        "revenue": [q["revenue"][i] for i in index_of],
        "revenue_and_other_income": [q["revenue_and_other_income"][i] for i in index_of],
    }
    for name, values in lines.items():
        slope, r2 = slope_and_r2(turnover, qoq(values))
        out[f"slope_{name}"], out[f"r2_{name}"] = slope, r2
    out["opposite_direction_steps"] = sum(
        1 for a, b in zip(turnover, qoq(lines["trading_clearing"])) if a * b < 0)
    return out


def half_direction_steps(staging: dict) -> tuple[int, int]:
    """Half-on-half steps in which gross investment income and net moved opposite ways."""
    gross, net = staging["half_investment"]["gross"], staging["half_investment"]["net"]
    steps = list(zip(zip(gross, gross[1:]), zip(net, net[1:])))
    opposite = sum(1 for (g0, g1), (n0, n1) in steps if (g1 - g0) * (n1 - n0) < 0)
    return opposite, len(steps)


def company_margin_gap(staging: dict) -> tuple[float, float] | None:
    """How far the company's EBITDA margin sits above this page's, where both exist.

    The company divides by revenue and other income less transaction-related
    expenses; the page by revenue and other income. The page used to say the
    two stay within one percentage point; 2023Q3-2024Q3 are 1.1-1.2 apart.
    """
    q = staging["quarterly"]
    gaps = [e / (r + t) * 100 - e / r * 100
            for e, r, t in zip(q["ebitda"], q["revenue_and_other_income"], q["transaction_expenses"])
            if t is not None]
    return (min(gaps), max(gaps)) if gaps else None


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def signed_int(value: float) -> str:
    """``290`` → ``'+290'``, ``-14`` → ``'-14'``, ``0`` → ``'0'`` (the company prints nil as '-')."""
    return "0" if value == 0 else f"{value:+,.0f}"


def rounded(values, digits: int = 6):
    return [None if v is None else round(v, digits) for v in values]


def hkd_m(value: float, digits: int = 0) -> str:
    """HK$m with the minus outside the currency symbol, as `board` formats money."""
    return f"{'−' if value < 0 else ''}HK${abs(value):,.{digits}f}M"


def qoq(values: list[float]) -> list[float]:
    return [(values[i] / values[i - 1] - 1) * 100 for i in range(1, len(values))]


def slope_and_r2(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Least-squares slope of y on x and the R-squared, both from the series.

    Published rather than asserted: the claim that HKEX's revenue is damped
    against turnover is a claim about a slope, and a page that only says
    "revenue moves less than volume" cannot be checked against what it ships.
    """
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    return sxy / sxx, sxy ** 2 / (sxx * syy)


def yoy_series(values: list[float | None]) -> list[float | None]:
    """Year-on-year percentage change, four quarters back, holes preserved."""
    out: list[float | None] = []
    for index, value in enumerate(values):
        base = values[index - 4] if index >= 4 else None
        out.append(None if value is None or base in (None, 0) else pct(value, base))
    return out


def printed_line_count(staging: dict, quarter: str) -> int:
    """How many of the ten tracked lines the company printed for that quarter."""
    index = staging["quarters"].index(quarter)
    if staging["quarter_basis"][index] == "printed":
        return sum(1 for f in TRACKED_LINES
                   if staging["quarterly"][f][index] is not None)
    box = staging["printed_box"].get(quarter, {})
    return sum(1 for f in BOX_LINES if f in box)


def box_check(staging: dict) -> dict:
    """Recount the printed-box comparison the page's headline claims.

    The claim is that every derived quarter the company also printed comes back
    identical.  Recomputing it here rather than storing a sentence means the
    number in the headline cannot drift away from the series underneath it.
    """
    comparisons = mismatches = derived_comparisons = 0
    covered = []
    for quarter, box in staging["printed_box"].items():
        if quarter not in staging["quarters"]:
            continue
        index = staging["quarters"].index(quarter)
        derived = staging["quarter_basis"][index] == "derived"
        for field in BOX_LINES:
            if field not in box:
                continue
            ours = staging["quarterly"][field][index]
            if ours is None:
                continue
            comparisons += 1
            if derived:
                derived_comparisons += 1
            if abs(box[field] - ours) > 0.5:
                mismatches += 1
        if derived and any(f in box for f in BOX_LINES):
            covered.append(quarter)
    derived_total = sum(1 for b in staging["quarter_basis"] if b == "derived")
    # Two counts, because they answer different questions and only one of them
    # is evidence for the subtraction. On a printed quarter the box merely
    # cross-checks the statement parse against the summary; on a derived one it
    # is the only outside reading this page's arithmetic can be held against.
    return {
        "comparisons": comparisons,
        "derived_comparisons": derived_comparisons,
        "mismatches": mismatches,
        "covered": sorted(covered),
        "derived_total": derived_total,
        "unchecked": derived_total - len(covered),
    }


HEADLINE_LINES = ("revenue_and_other_income", "operating_expenses", "ebitda",
                  "profit_attributable")
FEE_LINES = ("trading_fees", "clearing_fees", "listing_fees", "depository_fees",
             "market_data_fees")


QUARTER_END = {"1": "-03-31", "2": "-06-30", "3": "-09-30", "4": "-12-31"}

# Which built chart goes to which of the four sections. Section one is built
# from its own stamped blocks; section three from `next_kpi`.
HIGHLIGHT_REFS = ("EX_ROI", "EX_PROFIT", "EX_SEGQOQ", "EX_DEPOSITORY", "EX_CONNECT_HOLD",
                  "EX_REBATE", "EX_CAPEX")
ROUTINE_REFS = ("EX_LAG", "EX_FEESPLIT", "EX_CHECK",
                "EX_MARGIN", "EX_MIX", "EX_NONTRADE", "EX_OPEX",
                "EX_NETINV", "EX_GROSSNET",
                "EX_ADT", "EX_SLOPE", "EX_ADV", "EX_CONNECT", "EX_ANNUAL")


def lag_days(quarter: str, published: str) -> int:
    """Calendar days from a quarter's end to a publication date.

    Derived here rather than stored beside the date in the series. It was
    stored once, and a mutation that moved a publication date a year later
    left every gate green because the stale `lag_days` next to it was what
    the page actually read -- two copies of one number, and the page read the
    copy that was not the source.
    """
    end = datetime.date.fromisoformat(f"{quarter[:4]}{QUARTER_END[quarter[5]]}")
    return (datetime.date.fromisoformat(published) - end).days


def first_printed(staging: dict, quarter: str, field: str) -> dict | None:
    """The earliest document that printed this line as a discrete quarter."""
    return staging["first_printed"].get(f"{quarter}|{field}")


def disclosure_lag(staging: dict, quarter: str, fields) -> int | None:
    """Days from quarter end until every one of ``fields`` had been printed.

    ``None`` means at least one of them has never appeared as a discrete
    quarter anywhere.  That is a different statement from "late", and the page
    is wrong unless it can tell the two apart -- the first draft of this page
    could not, and called the whole of both categories "never printed".
    """
    entries = [first_printed(staging, quarter, f) for f in fields]
    if any(e is None for e in entries):
        return None
    return max(lag_days(quarter, e["published"]) for e in entries)


def never_printed(staging: dict, fields) -> list[str]:
    """Quarters for which at least one of ``fields`` has never been printed."""
    return [quarter for quarter in staging["quarters"]
            if disclosure_lag(staging, quarter, fields) is None]


def reconcile_against_printed(staging: dict) -> dict:
    """Hold every published cell against the company's own quarterly table.

    The page shipped first with a much weaker version of this: it compared the
    eleven even quarters that carry a Key Financials summary box, and said the
    other ten had no counterpart at all.  They do.  Every annual report since
    FY2016 carries an `Analysis of Results by Quarter` table with all four
    quarters printed as discrete columns, so the arithmetic is now checked
    against four times as many company-printed cells, and the count of derived
    cells with no counterpart is zero rather than ten.
    """
    tables = staging["ar_quarter_tables"]["by_year"]
    quarters, q = staging["quarters"], staging["quarterly"]
    compared = derived_compared = mismatches = 0
    per_year, bad = {}, []
    for year, block in sorted(tables.items()):
        for field, vals in block["values"].items():
            if field not in q:
                continue
            for k in range(4):
                quarter = f"{year}Q{k + 1}"
                if quarter not in quarters:
                    continue
                ours = q[field][quarters.index(quarter)]
                if ours is None:
                    continue
                compared += 1
                per_year[year] = per_year.get(year, 0) + 1
                if quarter[-1] in "24":
                    derived_compared += 1
                if abs(abs(ours) - abs(vals[k])) > 0.5:
                    mismatches += 1
                    bad.append((quarter, field, ours, vals[k]))
    covered = sorted({f"{y}Q{k + 1}" for y in tables for k in range(4)
                      if f"{y}Q{k + 1}" in quarters and (k + 1) % 2 == 0})
    derived_total = sum(1 for b in staging["quarter_basis"] if b == "derived")
    return {
        "compared": compared,
        "derived_compared": derived_compared,
        "mismatches": mismatches,
        "per_year": per_year,
        "bad": bad,
        "years": sorted(tables),
        "covered_even": covered,
        "uncovered_even": [qq for qq in quarters
                           if qq[-1] in "24" and qq not in covered],
        "derived_total": derived_total,
    }


def resolve_refs(exhibits: list[dict]) -> list[dict]:
    """Replace ``{EX_…}`` placeholders in captions with the numbers assigned.

    The captions on this page used to point at their neighbours by position
    ("下面第一张", "第三节第一张", "上一张"). Regrouping the page into four
    sections moved almost every chart, and a positional pointer does not move
    with the chart it names. The ``ref`` key stays on the exhibit so a test can
    find a chart without knowing its number.
    """
    numbers = {exhibit["ref"]: exhibit["n"] for exhibit in exhibits if exhibit.get("ref")}
    for exhibit in exhibits:
        for field in ("title", "note", "src_extra"):
            text = exhibit.get(field)
            if not isinstance(text, str) or "{EX_" not in text:
                continue
            for ref, number in numbers.items():
                text = text.replace("{" + ref + "}", str(number))
            if "{EX_" in text:
                raise ValueError(f"exhibit {exhibit.get('ref')} points at a chart that is not "
                                 f"on the page: {text[text.index('{EX_'):][:24]}")
            exhibit[field] = text
    return exhibits


# ── section one (a): last quarter's open questions, closed or not ────────────

def closure_counts(closure: dict) -> dict[str, int]:
    """Verdicts counted from the items, never typed beside them.

    The block lists each of last quarter's questions with the verdict the
    current analysis gave it. A count stored next to the list could disagree
    with the list; counting the list cannot.
    """
    counts = {label: 0 for label in closure["labels"]}
    for item in closure["items"]:
        if item["verdict"] not in counts:
            raise ValueError(f"followup_closure item {item['n']} has verdict "
                             f"{item['verdict']!r}, which is not one of {closure['labels']}")
        counts[item["verdict"]] += 1
    numbers = [item["n"] for item in closure["items"]]
    if numbers != list(range(1, len(numbers) + 1)):
        raise ValueError(f"followup_closure items must be numbered 1..n in order, got {numbers}")
    return counts


def closure_exhibit(closure: dict) -> dict:
    counts = closure_counts(closure)
    total = len(closure["items"])
    drawn = [label for label in closure["labels"] if counts[label]]
    absent = [label for label in closure["labels"] if not counts[label]]
    by_verdict = {label: [item for item in closure["items"] if item["verdict"] == label]
                  for label in closure["labels"]}
    verified = by_verdict.get("已验证", [])
    # Verified is not the same as "went the way last quarter hoped": the
    # analysis marks the one whose answer came back worse, and the note says so.
    worse = [item for item in verified if item.get("against_prior") == "worse"]
    open_items = by_verdict.get("仍未披露", [])
    note = ""
    if verified:
        note += (f"已验证的{cn_count(len(verified))}条是第 "
                 + "、".join(str(item["n"]) for item in verified) + " 条"
                 + ("" if not worse else
                    "；其中" + "、".join(f"第 {item['n']} 条（{item['topic']}）" for item in worse)
                    + "的答案比上季预期差：" + "；".join(item["reading"] for item in worse))
                 + "。")
    if open_items:
        note += (f"仍未披露的{cn_count(len(open_items))}条："
                 + "；".join(f"第 {item['n']} 条（{item['topic']}）—— {item['reading']}"
                            for item in open_items)
                 + "。")
    return {
        "ref": "EX_CLOSURE",
        "kind": "bars_labeled",
        "title": (f"上季 {total} 条待验证问题："
                  + "、".join(f"{counts[label]} 条{label}" for label in drawn)
                  + ("，" + "、".join(f"没有一条{label}" for label in absent) if absent else "")),
        # A verdict nobody received is named in the title, not drawn as an
        # empty labelled column.
        "xlabels": drawn,
        "values": [counts[label] for label in drawn],
        "legend": "问题条数",
        "fmt": "f0",
        "yfmt": "f0",
        "label_fmt": "f0",
        "ylab": "条",
        "note": note,
        "src_extra": ("问题清单出自上季本地分析稿文末的 Follow-up；逐条判定取自本季分析稿第 0 节，"
                      "判定所依据的数字来自本季与上季的业绩公告。"),
    }


# ── quarterly series read from cumulative tables ─────────────────────────────
#
# The segment table and the Corporate Funds table are printed for three, six,
# nine and twelve months -- never for a second, third or fourth quarter on its
# own. The same subtraction the income statement needs applies, one level more
# often: here only the first quarter is printed as itself.

CUMULATIVE = {"1": ("Q1", None), "2": ("H1", "Q1"), "3": ("9M", "H1"), "4": ("FY", "9M")}
DOC_WORDS = {"Q1": "第一季度业绩公告", "H1": "中期业绩公告", "Q3": "第三季度业绩公告", "FY": "全年业绩公告"}


def doc_words(doc: str) -> str:
    """``'2026_Q1'`` → ``'2026 年第一季度业绩公告'``."""
    year, kind = doc.split("_")
    return f"{year} 年{DOC_WORDS[kind]}"


def quarters_between(first: str, last: str) -> list[str]:
    if first > last:
        raise ValueError(f"no quarters from {first} to {last}")
    out, (year, number) = [], (int(first[:4]), int(first[5]))
    while True:
        quarter = f"{year}Q{number}"
        out.append(quarter)
        if quarter == last:
            return out
        year, number = (year + 1, 1) if number == 4 else (year, number + 1)


def cumulative_readings(readings: list[dict], value) -> dict[str, float]:
    """One value per cumulative period ('2026Q1', '2026H1', '20269M', '2026FY').

    Most periods are printed twice -- in their own announcement and a year
    later as the comparative column. The two must agree; a period printed as
    two different numbers is a restatement, and which basis the page uses is a
    decision for a person, not for this function.
    """
    by_period: dict[str, set] = {}
    docs: dict[str, list] = {}
    for reading in readings:
        by_period.setdefault(reading["period"], set()).add(value(reading))
        docs.setdefault(reading["period"], []).append(reading["doc"])
    out = {}
    for period, values in by_period.items():
        if len(values) > 1:
            raise ValueError(f"{period} is printed as {sorted(values)} in {docs[period]}: "
                             "a restatement -- decide which basis the page uses")
        out[period] = values.pop()
    return out


def discrete_quarters(cumulative: dict[str, float], quarters: list[str]) -> list[float | None]:
    """Q1 as printed; Q2 = H1 − Q1, Q3 = 9M − H1, Q4 = FY − 9M."""
    out: list[float | None] = []
    for quarter in quarters:
        span, before = CUMULATIVE[quarter[5]]
        now = cumulative.get(f"{quarter[:4]}{span}")
        base = cumulative.get(f"{quarter[:4]}{before}") if before else 0
        out.append(None if now is None or base is None else now - base)
    return out


def commodities_series(staging: dict) -> dict:
    """The commodities segment on the 2023 basis, quarter by quarter from 2022Q1."""
    readings = staging["segment_readings"]["readings"]
    revenue = cumulative_readings(readings, lambda r: r["roi_less_txn"]["commodities"])
    ebitda = cumulative_readings(readings, lambda r: r["ebitda"]["commodities"])
    first = min(period for period in revenue if period[4:] == "Q1")
    quarters = quarters_between(first, staging["quarters"][-1])
    rev, ebit = discrete_quarters(revenue, quarters), discrete_quarters(ebitda, quarters)
    if rev[-1] is None or ebit[-1] is None:
        raise ValueError(f"segment_readings has no reading that completes {quarters[-1]}: "
                         "add this quarter's segment table with the roll")
    return {
        "quarters": quarters,
        "revenue": rev,
        "ebitda": ebit,
        "margin": [None if r is None or e is None else e / r * 100 for r, e in zip(rev, ebit)],
        "derived": [quarter[5] != "1" for quarter in quarters],
    }


def segment_ebitda_by_quarter(staging: dict, quarters: list[str]) -> dict[str, list[float | None]]:
    readings = staging["segment_readings"]["readings"]
    return {segment: discrete_quarters(cumulative_readings(readings, lambda r, s=segment: r["ebitda"][s]),
                                       quarters)
            for segment in list(staging["segment_readings"]["segments"]) + ["group"]}


def unlisted_equity_series(staging: dict) -> dict:
    """Gains and losses on the unlisted minority stakes, quarter by quarter from 2021Q1."""
    block = staging["unlisted_equity"]
    readings = [r for r in block["readings"] if not r["column"].startswith("three months")]
    cumulative = cumulative_readings(readings, lambda r: r["value"])
    first = min(period for period in cumulative if period[4:] == "Q1")
    quarters = quarters_between(first, staging["quarters"][-1])
    values = discrete_quarters(cumulative, quarters)
    if values[-1] is None:
        raise ValueError(f"unlisted_equity has no reading that completes {quarters[-1]}: "
                         "add this quarter's Corporate Funds table with the roll")
    return {"quarters": quarters, "values": values,
            "derived": [quarter[5] != "1" for quarter in quarters]}


# ── section one (b): last quarter's quantified thresholds, settled ────────────

LOCAL_UNITS = {
    "count": lambda value: f"{value:.0f} 家",
    "hkd_m": lambda value: hkd_m(value),
    "pct2": lambda value: f"{value:.2f}%",
}


def unit_words(unit: str, value: float) -> str:
    return LOCAL_UNITS[unit](value) if unit in LOCAL_UNITS else unit_text(unit, value)


def settlement_values(staging: dict, prior: dict, commod: dict, equity: dict) -> dict[str, list[float]]:
    """The settled quarter and the one before it, for every quantified line.

    Two quarters because two of last quarter's lines ask for two in a row
    (「连续 2 季」). Every value is read or subtracted from a printed figure;
    nothing here is typed.
    """
    quarters = staging["quarters"]
    settled = quarters[-2:]
    roi = dict(zip(quarters, staging["quarterly"]["revenue_and_other_income"]))
    readings = prior["readings"]

    def from_cumulative(name: str, value) -> list[float]:
        values = discrete_quarters({r["period"]: value(r) for r in readings[name]}, settled)
        if None in values:
            raise ValueError(f"prior_kpi_settlement.readings.{name} does not cover {settled}")
        return [round(v, 6) for v in values]

    kq, adt = staging["kpi_quarters"], staging["kpi_quarterly"]["adt_headline"]
    if kq[-2:] != settled:
        raise ValueError("kpi_quarters must end on the settled quarter")
    connect = from_cumulative("connect_revenue_hkd_m", lambda r: r["value"])

    def last_two(series: dict, key: str) -> list[float]:
        if series["quarters"][-2:] != settled:
            raise ValueError(f"series for {key} does not end on {settled[-1]}")
        return series[key][-2:]

    return {
        "adt_vs_prior": [adt[-2] / adt[-3] * 100, adt[-1] / adt[-2] * 100],
        "connect_share": [c / roi[q] * 100 for c, q in zip(connect, settled)],
        "ipo_funds": from_cumulative("ipo_funds_hkd_bn", lambda r: r["value"]),
        "ipo_listings": from_cumulative("newly_listed", lambda r: r["main_board"] + r["gem"]),
        "commodities_margin": last_two(commod, "margin"),
        "commodities_revenue": last_two(commod, "revenue"),
        "unlisted_equity": [abs(v) for v in last_two(equity, "values")],
    }


def settle_prior(prior: dict, values: dict[str, list[float]]) -> list[dict]:
    """Each quantified line with its actual: the settled quarter against the risk
    line, and -- where a line asks for N quarters in a row -- the weakest of the
    last N against the bull line."""
    entries = []
    for entry in prior["quantified"]:
        series = values[entry["id"]]
        row = dict(entry, actual=series[-1])
        if "bull_threshold" in entry:
            window = series[-entry.get("bull_quarters", 1):]
            row["bull_actual"] = min(window) if entry["direction"] == "up" else max(window)
        entries.append(row)
    return entries


def risk_held(entry: dict) -> bool:
    return headroom(entry["direction"], entry["threshold"], entry["actual"]) >= 0


def bull_cleared(entry: dict) -> bool:
    return headroom(entry["direction"], entry["bull_threshold"], entry["bull_actual"]) >= 0


def indicator_verdicts(prior: dict, entries: list[dict]) -> list[tuple[dict, str]]:
    """What the numbers say about each of last quarter's indicators, checked
    against the verdict the current analysis gave it.

    A breached risk line decides the indicator; otherwise it is `bull` only if
    every bull line it carries cleared. If the data and the report's verdict
    disagree the block was written for another quarter, and the build stops
    rather than printing a verdict the numbers no longer support.
    """
    out = []
    for indicator in prior["indicators"]:
        rows = [e for e in entries if e["indicator"] == indicator["n"]]
        risk = any("threshold" in e and not risk_held(e) for e in rows)
        bulls = [e for e in rows if "bull_threshold" in e]
        kind = "risk" if risk else ("bull" if bulls and all(bull_cleared(e) for e in bulls) else "none")
        if kind != indicator["verdict_kind"]:
            raise ValueError(f"prior_kpi_settlement indicator {indicator['n']}: the analysis says "
                             f"{indicator['report_verdict']!r} ({indicator['verdict_kind']}), the data "
                             f"says {kind}: rewrite the block for this quarter")
        out.append((indicator, kind))
    return out


def two_line_chart(title: str, xlabels: list[str], values: list[float | None], entry: dict, *,
                   fmt: str, ylab: str, actual_name: str, note: str, src_extra: str,
                   risk_label: str, bull_label: str, value_key: str = "threshold",
                   lower: bool = False) -> dict:
    """A threshold chart that also draws the bull line where the line has one.

    `board.threshold_exhibit` draws one line. Last quarter's indicators on
    this page mostly came with two, and the verdict turned on the second one
    as often as on the first.
    """
    side = "上方" if entry["direction"] == "up" else "下方"
    chart = threshold_exhibit(title, xlabels, rounded(values), entry[value_key],
                              fmt=fmt, ylab=ylab, actual_name=actual_name,
                              threshold_name=f"{risk_label}（安全侧在{side}）",
                              note=note, src_extra=src_extra,
                              xstep=KPI_STEP if len(xlabels) > 16 else None)
    if lower:
        # A two-sided line (「收益或损失超过 X」): the safe side is between them.
        chart["series"].append({"name": f"{risk_label.replace('+', '−')}（安全侧在上方）",
                                "values": [-entry[value_key]] * len(xlabels), "color": "RED"})
    if "bull_threshold" in entry:
        chart["series"].append({"name": bull_label, "values": [entry["bull_threshold"]] * len(xlabels),
                                "color": "GOLD"})
    return chart


def settled_threshold_section(staging: dict, prior: dict) -> tuple[list[dict], list[dict]]:
    commod = commodities_series(staging)
    equity = unlisted_equity_series(staging)
    values = settlement_values(staging, prior, commod, equity)
    entries = settle_prior(prior, values)
    verdicts = indicator_verdicts(prior, entries)
    by_id = {entry["id"]: entry for entry in entries}
    risk = [entry for entry in entries if "threshold" in entry]
    bull = [entry for entry in entries if "bull_threshold" in entry]
    breached = [entry for entry in risk if not risk_held(entry)]
    cleared = [entry for entry in bull if bull_cleared(entry)]
    kq, kpi = staging["kpi_quarters"], staging["kpi_quarterly"]
    qualitative = {item["indicator"]: item["text"] for item in prior.get("qualitative", [])}
    docs = sorted({r["doc"] for rows in prior["readings"].values() for r in rows},
                  key=lambda doc: (doc[:4], list(DOC_WORDS).index(doc[5:])))

    verdict_words = "、".join(f"第 {indicator['n']} 个{indicator['report_verdict']}"
                              for indicator, _ in verdicts)
    risk_chart = headroom_exhibit(
        f"上季 {len(risk)} 条量化阈值：{len(risk) - len(breached)} 条守住、{len(breached)} 条被击穿"
        + (f"（{'、'.join(entry['metric'].split('（')[0] for entry in breached)}）" if breached else ""),
        risk, "actual",
        note=(
            "正值 = 仍在安全侧。"
            f"上季分析稿第 8 节留下 {len(prior['indicators'])} 个指标，每个都写了一条风险线，"
            "多数还写了一条加仓线；本图画风险线，下一张画加仓线。"
            f"本季分析稿给这 {len(prior['indicators'])} 个指标的判定依次是：{verdict_words} —— "
            "与两张图逐条一致（本页构建时逐条核对，不一致就停下）。"
            + "".join(f"第 {n} 个指标：{text}" for n, text in sorted(qualitative.items()))),
        src_extra=(
            "阈值逐字取自上季本地分析稿第 8 节，不是公司指引。实际值：现货日均成交额取自各期公告的市场统计表；"
            "Stock Connect 收入、IPO 募资额与新上市家数取自 " + "与 ".join(doc_words(d) for d in docs)
            + "（第二季 = 中期 − 第一季）；商品分部取自分部表，未上市股权取自 Corporate Funds 净投资收益分析表，"
            "两者的第二季同样是中期减第一季，来历见核对抽屉。"),
    )
    risk_chart["ref"] = "EX_PRIOR_RISK"

    bull_chart = {
        "ref": "EX_PRIOR_BULL",
        "kind": "diverging_bars",
        "title": (f"换成上季的加仓线再看：{len(bull)} 条里 {len(cleared)} 条兑现"
                  + (f"（{'、'.join(entry['metric'] for entry in cleared)}）" if cleared else "")),
        "xlabels": [entry["metric"] for entry in bull],
        "values": [round(headroom(entry["direction"], entry["bull_threshold"], entry["bull_actual"]), 1)
                   for entry in bull],
        "legend": "距加仓线的余量",
        "positive_label": "加仓线兑现",
        "negative_label": "未到加仓线",
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "距加仓线 %",
        "zero_line": True,
        "note": (
            "正值 = 兑现。写着「连续 2 季」的线按最近两季里较弱的那一季算 —— "
            + "；".join(f"{entry['metric']}两季依次是 "
                       + "、".join(unit_words(entry["unit"], v)
                                  for v in values[entry["id"]][-entry["bull_quarters"]:])
                       for entry in bull if entry.get("bull_quarters", 1) > 1)
            + "。"),
        "src_extra": "加仓线同为上季本地分析稿第 8 节的设定；单位各不相同，只比较方向与相对幅度，原值见核对抽屉。",
    }

    # ── the three lines that have a quarterly series behind them ────────────
    adt = kpi["adt_headline"]
    ratio = [adt[i] / adt[i - 1] * 100 for i in range(1, len(adt))]
    adt_entry = by_id["adt_vs_prior"]
    below_bull = [q for q, r in zip(kq[1:], ratio) if r < adt_entry["bull_threshold"]]
    below_risk = [q for q, r in zip(kq[1:], ratio) if r < adt_entry["threshold"]]
    nb = kpi["adt_northbound"]
    adt_chart = two_line_chart(
        f"现货日均成交额为上季的 {ratio[-1]:.1f}%："
        + ("守住" if risk_held(adt_entry) else "击穿") + f"上季阈值 {adt_entry['threshold']:.0f}%，"
        + ("也越过了" if bull_cleared(adt_entry) else "没到") + f"加仓线 {adt_entry['bull_threshold']:.0f}%",
        list(kq[1:]), ratio, adt_entry,
        fmt="pct1", ylab="本季 ÷ 上季", actual_name="现货日均成交额 ÷ 上季",
        risk_label=f"上季阈值 {adt_entry['threshold']:.0f}%",
        bull_label=f"加仓线 {adt_entry['bull_threshold']:.0f}%",
        note=(
            f"本季现货日均成交额 HK${adt[-1]:,.1f}B，上季 HK${adt[-2]:,.1f}B。"
            f"{len(ratio)} 次环比里有 {len(below_bull)} 次低于 {adt_entry['bull_threshold']:.0f}%"
            + (f"、{len(below_risk)} 次低于 {adt_entry['threshold']:.0f}%" if below_risk
               else f"，一次都没有低于 {adt_entry['threshold']:.0f}%")
            + "。上季这条指标还带着北向那一半 ——「北向维持」—— 没有写成数字："
            f"北向日均成交额从上季 RMB{nb[-2]:,.1f}B 到本季 RMB{nb[-1]:,.1f}B"
            f"（{signed(pct(nb[-1], nb[-2]))}）。"),
        src_extra=("季度日均成交额取自各期公告的市场统计表，比值为本页自算；"
                   f"市场统计是每交易日的平均，不能相减，季度读数只回到 {kq[0]}。"),
    )
    adt_chart["ref"] = "EX_PRIOR_ADT"

    margin_entry = by_id["commodities_margin"]
    margins = commod["margin"]
    above = [q for q, m in zip(commod["quarters"], margins) if m is not None and m >= margin_entry["threshold"]]
    commod_chart = two_line_chart(
        f"商品分部 EBITDA 利润率：本季 {margins[-1]:.1f}%，"
        + ("守住" if risk_held(margin_entry) else "击穿") + f"上季阈值 {margin_entry['threshold']:.0f}%",
        list(commod["quarters"]), margins, margin_entry,
        fmt="pct1", ylab="EBITDA ÷ 收入", actual_name="商品分部 EBITDA 利润率（第二至四季为 D）",
        risk_label=f"上季阈值 {margin_entry['threshold']:.0f}%",
        bull_label=f"加仓线 {margin_entry['bull_threshold']:.0f}%（须连续两季）",
        note=(
            f"本季收入 {hkd_m(commod['revenue'][-1])}、EBITDA {hkd_m(commod['ebitda'][-1])}；"
            f"上季 {margins[-2]:.1f}%。"
            f"<b>这条线画出来的 {len(margins)} 个季度里，达到 {margin_entry['threshold']:.0f}% 的只有 "
            + "、".join(above) + "</b>"
            + (" —— 上季的阈值是对着这一个季度设的。" if len(above) == 1 and above[0] == commod["quarters"][-2] else "。")
            + "分部表只印三个月、六个月、九个月与全年，所以第二、三、四季都是本页减出来的，只有第一季是印出来的。"),
        src_extra=("分部口径 2023 年重组：交易与结算按资产类别合并，商品分部从此含 LME Clear 与所分配的保证金投资收益；"
                   f"本图从 {commod['quarters'][0]} 起画，因为 2022 年只在 2023 年公告的比较列里按新口径重印过，"
                   "更早的季度只有旧口径（结算另成一个分部），不可比。"),
    )
    commod_chart["ref"] = "EX_PRIOR_COMMOD"

    eq_entry = by_id["unlisted_equity"]
    eq = equity["values"]
    big = [(q, v) for q, v in zip(equity["quarters"], eq) if v is not None and abs(v) > 100]
    off_clock = [q for q, _ in big if q[5] in "13"]
    quiet = max(abs(v) for q, v in zip(equity["quarters"], eq) if v is not None and q[5] in "13")
    ours = dict(zip(equity["quarters"], eq))
    printed = ([(r["period"], r["value"]) for r in staging["unlisted_equity"]["readings"]
                if r["column"].startswith("three months")]
               + [(p["quarter"], p["value"]) for p in staging["unlisted_equity"]["prose_quarters"]])
    checks = [ours[q] - v for q, v in printed if q in ours]
    eq_chart = two_line_chart(
        f"未上市股权估值收益：本季 {'+' if eq[-1] > 0 else ''}{hkd_m(eq[-1])}，"
        + ("守住" if risk_held(eq_entry) else "击穿") + f"上季阈值 ±{hkd_m(eq_entry['threshold'])}",
        list(equity["quarters"]), eq, eq_entry,
        fmt="f0c", ylab="HK$M", actual_name="未上市股权估值收益 / 损失（第二至四季为 D）",
        risk_label=f"上季阈值 +{hkd_m(eq_entry['threshold'])}", bull_label="", lower=True,
        note=(
            f"{len(eq)} 个季度里绝对值超过 HK$100M 的有 {len(big)} 次："
            + "、".join(f"{q} {'+' if v > 0 else ''}{hkd_m(v)}" for q, v in big)
            + ("，<b>全部落在第二或第四季</b>" if big and not off_clock else "")
            + f"；第一、三季的绝对值最大只有 {hkd_m(quiet)}。"
            "这就是本季分析稿说的「半年一估」：中期简明综合财务报表的公允价值附注写明，"
            "这几笔对未上市公司的少数股权投资属第三层级，估值每半年做一次，在中期与年度报告日。"
            # A quarter that is not a valuation date and still moves more than
            # this threshold is exactly what the analysis says would falsify it.
            + (f"<b>但 {'、'.join(off_clock)} 不是估值季，却超过了 HK$100M。</b>" if off_clock else "")),
        src_extra=("取自 Corporate Funds 净投资收益分析表「Equity securities」一行（脚注：对未上市公司的少数股权投资），"
                   f"从 {equity['quarters'][0]} 起 —— 这一行带着这个脚注从 2021 年全年公告起才出现。"
                   f"第二、三、四季为累计期相减；公司另行印出的单季数有 {len(checks)} 处（第三季度公告的三个月列，"
                   f"以及全年与中期公告正文），与本页相减值不同的有 {sum(1 for c in checks if c)} 处，见核对抽屉。"),
    )
    eq_chart["ref"] = "EX_PRIOR_EQUITY"
    return [risk_chart, bull_chart, adt_chart, commod_chart, eq_chart], entries


# ── section two: this quarter's findings that need charts of their own ──────

def signed_hkd(value: float) -> str:
    return ("+" if value > 0 else "") + hkd_m(value)


def segment_qoq_chart(staging: dict, context: dict | None) -> dict:
    """Where the quarter-on-quarter EBITDA came from, segment by segment."""
    last_two = staging["quarters"][-2:]
    ebitda = segment_ebitda_by_quarter(staging, last_two)
    names = staging["segment_readings"]["segments"]
    deltas = {segment: ebitda[segment][1] - ebitda[segment][0] for segment in names}
    group = ebitda["group"][1] - ebitda["group"][0]
    if sum(deltas.values()) != group:
        raise ValueError("segment EBITDA changes do not add up to the group's")
    q = staging["quarterly"]
    if (ebitda["group"][1], ebitda["group"][0]) != (q["ebitda"][-1], q["ebitda"][-2]):
        raise ValueError("segment table group EBITDA is not the income statement's")
    operating = sum(v for s, v in deltas.items() if s != "corporate_items")
    corporate = deltas["corporate_items"]
    equity = unlisted_equity_series(staging)
    eq_prev, eq_now = equity["values"][-2], equity["values"][-1]
    profit = q["profit_attributable"]
    core = (context or {}).get("core_business_q1_q2")
    return {
        "ref": "EX_SEGQOQ",
        "kind": "diverging_bars",
        "title": (f"集团 EBITDA 环比 {signed_hkd(group)}：{names['corporate_items']}一项 {signed_hkd(corporate)}，"
                  f"四个经营分部合计 {signed_hkd(operating)}"),
        "xlabels": [names[s] for s in names],
        "values": [deltas[s] for s in names],
        "legend": f"EBITDA 环比变动（{last_two[1]} 减 {last_two[0]}）",
        "positive_label": "环比增加",
        "negative_label": "环比减少",
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "HK$M",
        "zero_line": True,
        "note": (
            f"股东应占溢利环比 {signed_hkd(profit[-1] - profit[-2])}（{hkd_m(profit[-2])} → {hkd_m(profit[-1])}），"
            f"而{names['corporate_items']}里的未上市股权估值收益从 {signed_hkd(eq_prev)} 变成 {signed_hkd(eq_now)}"
            f"（{signed_hkd(eq_now - eq_prev)}）—— <b>一笔半年一估的重估，比整个季度的溢利增量还大</b>。"
            if eq_now - eq_prev > profit[-1] - profit[-2] > 0 else
            f"股东应占溢利环比 {signed_hkd(profit[-1] - profit[-2])}；未上市股权估值收益从 {signed_hkd(eq_prev)} "
            f"变成 {signed_hkd(eq_now)}。")
        + (f"公司自己在中期演示稿第 {core_page(context)} 页把「核心业务」单独列出："
           f"核心业务 EBITDA {hkd_m(core['ebitda'][0])} → {hkd_m(core['ebitda'][1])}，"
           f"核心业务股东应占溢利 {hkd_m(core['profit_attributable'][0])} → {hkd_m(core['profit_attributable'][1])}"
           f"（{signed(pct(core['profit_attributable'][1], core['profit_attributable'][0]))}）。" if core else "")
        + f"分部表只印累计期，{last_two[1]} 的分部数是中期减第一季。",
        "src_extra": ("分部 EBITDA 取自各期公告的分部表（Results by segment）；五个分部相加等于集团 EBITDA，"
                      "集团数与本页损益表一致。核心业务口径取自公司中期业绩演示稿。"),
    }


def core_page(context: dict) -> int:
    return context["core_business_q1_q2"]["page"]


def depository_chart(staging: dict) -> dict:
    """The second-quarter jump in depository fees, year by year."""
    quarters, dep = staging["quarters"], staging["quarterly"]["depository_fees"]
    value = dict(zip(quarters, dep))
    years = sorted({quarter[:4] for quarter in quarters})
    grid = {n: [value.get(f"{year}Q{n}") for year in years] for n in (1, 2, 3, 4)}
    both = [(y, a, b) for y, a, b in zip(years, grid[1], grid[2]) if a is not None and b is not None]
    q2_up = [y for y, a, b in both if b > a]
    third = [(y, b, c) for y, b, c in zip(years, grid[2], grid[3]) if b is not None and c is not None]
    q3_not_lower = [y for y, b, c in third if c >= b]
    return {
        "ref": "EX_DEPOSITORY",
        "kind": "grouped_bars",
        "title": (f"存管、托管及代理人服务费：本季 {hkd_m(dep[-1])}、环比 {signed(pct(dep[-1], dep[-2]))}；"
                  + (f"{cn_count(len(both))}年里每一年的第二季都高于第一季" if len(q2_up) == len(both)
                     else f"{cn_count(len(both))}年里有{cn_count(len(q2_up))}年第二季高于第一季")),
        "xlabels": years,
        "groups": [{"name": f"第{cn_ordinal(n)}季", "values": rounded(grid[n]),
                    "color": color} for n, color in zip((1, 2, 3, 4), ("GRAY", "NAVY", "MBLUE", "BLUE"))],
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "HK$M",
        "bar_labels": False,
        "note": (
            ("<b>第二季的跳升年年都有，是日历，不是趋势。</b>" if len(q2_up) == len(both) else "")
            + (f"但接下来的第三季并不总是回落 —— {'、'.join(q3_not_lower)} 年第三季不低于第二季"
               f"（{len(third)} 个有第三季读数的年份里 {len(q3_not_lower)} 个）。" if q3_not_lower else
               f"{len(third)} 个有第三季读数的年份里，第三季每一年都低于第二季。")
            + "集团口径，含股本证券及金融衍生产品分部的少量同类收费；第二、四季为本页减出（中期 − 第一季、全年 − 前九个月）。"),
        "src_extra": "存管、托管及代理人服务费逐季取自损益表，与本页其余 42 季序列同一套减法与对照。",
    }


def turnover(readings: dict, side: str, when: str) -> float:
    """Average daily turnover over period-end holdings, both sides as printed."""
    unit = "rmb" if side == "northbound" else "hkd"
    return (readings[f"{side}_adt_{unit}_bn"][when] / readings[f"{side}_holdings_{unit}_bn"][when] * 100)


def connect_holdings_chart(block: dict) -> dict:
    """Northbound grew by trading more, southbound by holding more."""
    r = block["readings"]
    growth = {key: pct(value["now"], value["year_ago"]) for key, value in r.items()}
    nb_t, nb_h = growth["northbound_adt_rmb_bn"], growth["northbound_holdings_rmb_bn"]
    sb_t, sb_h = growth["southbound_adt_hkd_bn"], growth["southbound_holdings_hkd_bn"]
    return {
        "ref": "EX_CONNECT_HOLD",
        "kind": "grouped_bars",
        "title": (f"北向成交 {signed(nb_t)}、持仓只 {signed(nb_h)}；南向成交 {signed(sb_t)}、持仓 {signed(sb_h)}"),
        "xlabels": ["北向（人民币）", "南向（港元）"],
        "groups": [
            {"name": "上半年日均成交额同比", "values": [round(nb_t, 1), round(sb_t, 1)], "color": "NAVY"},
            {"name": "6 月 30 日持仓市值同比", "values": [round(nb_h, 1), round(sb_h, 1)], "color": "GOLD"},
        ],
        "fmt": "pct1",
        "yfmt": "pct0",
        "label_fmt": "pct1",
        "ylab": "同比",
        "bar_labels": True,
        "note": (
            f"北向：上半年日均 RMB{r['northbound_adt_rmb_bn']['year_ago']:,.1f}B → "
            f"RMB{r['northbound_adt_rmb_bn']['now']:,.1f}B，6 月 30 日持仓 RMB{r['northbound_holdings_rmb_bn']['year_ago']:,.0f}B → "
            f"RMB{r['northbound_holdings_rmb_bn']['now']:,.0f}B；南向：日均 HK${r['southbound_adt_hkd_bn']['year_ago']:,.1f}B → "
            f"HK${r['southbound_adt_hkd_bn']['now']:,.1f}B，持仓 HK${r['southbound_holdings_hkd_bn']['year_ago']:,.0f}B → "
            f"HK${r['southbound_holdings_hkd_bn']['now']:,.0f}B。"
            + "日均成交 ÷ 期末持仓："
            f"北向 {turnover(r, 'northbound', 'year_ago'):.1f}% → {turnover(r, 'northbound', 'now'):.1f}%，"
            f"南向 {turnover(r, 'southbound', 'year_ago'):.1f}% → {turnover(r, 'southbound', 'now'):.1f}%"
            + (" —— <b>北向是同一批持仓换手更快，南向两者同步</b>。"
               if nb_t > 2 * nb_h and abs(sb_t - sb_h) < 2 else "。")
            + "两条日均成交额都按买卖双边计（公告同一个脚注），持仓是期末时点值、含股价涨跌。"),
        "src_extra": "日均成交额取自中期业绩公告的六个月市场统计（去掉并入数字的纪录上标），持仓市值取自同一份公告的 Key Market Indicators。",
    }


def capex_chart(staging: dict, context: dict | None) -> dict:
    """The headquarters purchase, instalment by instalment."""
    block = staging["capex_quarterly"]
    rows = block["readings"]
    labels = [row["quarter"] for row in rows]
    if labels[-1] != staging["quarters"][-1]:
        raise ValueError("capex_quarterly does not reach the latest quarter: add it with the roll")
    hq = [row["hq"] for row in rows]
    others = [row["others"] for row in rows]
    payments = [(q, v) for q, v in zip(labels, hq) if v]
    commitment = block["commitment"]
    purchase = block["purchase"]
    # The cash-flow statement is half-yearly; its reading only pairs with the
    # profit of the same six months on a second-quarter page.
    cash = (context or {}).get("principal_operating_cash_h1") if staging["quarters"][-1][5] == "2" else None
    profit = staging["quarterly"]["profit_attributable"]
    h1 = sum(profit[-2:]), sum(profit[-6:-4])
    return {
        "ref": "EX_CAPEX",
        "kind": "grouped_bars",
        "title": (f"资本开支 {hkd_m(hq[-1] + others[-1])}，其中总部物业 {hkd_m(hq[-1])}"
                  + (f"：{cn_count(len(labels))}个季度里第{cn_ordinal(len(payments))}笔总部物业支出"
                     if hq[-1] and len(payments) > 1 else "")),
        "xlabels": labels,
        "groups": [
            {"name": "总部物业", "values": hq, "color": "GOLD"},
            {"name": "其余资本开支", "values": others, "color": "NAVY"},
        ],
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "HK$M",
        "bar_labels": True,
        "note": (
            f"总部物业是 {purchase['agreed'][:4]} 年 {int(purchase['agreed'][5:])} 月签约、总价 HK${purchase['total_consideration_hkd_bn']:.1f}B、"
            "分期交割的购置，不是一笔买断：本图里已入账的有 "
            + "、".join(f"{q} {hkd_m(v)}" for q, v in payments)
            + f"，合计 {hkd_m(sum(v for _, v in payments))}；"
            f"中期财务报表附注 26 列出已签约、尚未入账的总部物业承担还有 {hkd_m(commitment['contracted_not_provided_hkd_m'])}"
            f"（半年前 {hkd_m(commitment['a_half_earlier_hkd_m'])}）。"
            + (f"同一张现金流量表上，主要经营活动现金流入 {hkd_m(cash['now'])}（上年同期 {hkd_m(cash['year_ago'])}），"
               f"是上半年股东应占溢利 {hkd_m(h1[0])} 的 {cash['now'] / h1[0] * 100:.1f}%"
               f"（上年同期 {cash['year_ago'] / h1[1] * 100:.1f}%）。" if cash else "")
            + "只画最近八个季度：这张图讲的是这笔购置。"),
        "src_extra": ("资本开支取自各季业绩公告 Key Financials 框（2025 年中期起分总部物业与其余两行）；"
                      "总价与分期交割取自 2025 年中期与全年业绩公告的附注，承担余额取自 2026 年中期简明综合财务报表附注 26。"),
    }


# ── section three: what the current analysis says to watch next ─────────────

def agreeing(readings: list[dict], key: str, value) -> dict:
    """``key -> value``; a value printed twice must be printed the same."""
    out: dict = {}
    for reading in readings:
        k, v = reading[key], value(reading)
        if k in out and out[k] != v:
            raise ValueError(f"{k} is printed as {out[k]} and as {v}: decide which the page uses")
        out[k] = v
    return out


def prev_half(half: str) -> str:
    """``'2026H1'`` → ``'2025H1'``."""
    return f"{int(half[:4]) - 1}{half[4:]}"


def margin_fund_halves(staging: dict) -> tuple[list[str], list[float]]:
    returns = agreeing(staging["margin_fund_returns"]["readings"], "half", lambda r: r["annualised_return_pct"])
    halves = sorted(h for h in returns if h >= staging["halves"][0])
    return halves, [returns[h] for h in halves]


def pipeline_series(staging: dict) -> tuple[list[str], list[float | None]]:
    counts = agreeing(staging["ipo_pipeline"]["readings"], "quarter", lambda r: r["count"])
    quarters = quarters_between(min(counts), staging["quarters"][-1])
    return quarters, [counts.get(q) for q in quarters]


def latest(labels: list[str], values: list) -> tuple[str, float]:
    for label, value in zip(reversed(labels), reversed(values)):
        if value is not None:
            return label, value
    raise ValueError("series has no reading")


def next_quarter_section(staging: dict, kpi: dict) -> tuple[list[dict], list[dict]]:
    kq, kpi_q = staging["kpi_quarters"], staging["kpi_quarterly"]
    commod = commodities_series(staging)
    equity = unlisted_equity_series(staging)
    halves, returns = margin_fund_halves(staging)
    pipe_q, pipe = pipeline_series(staging)
    # The unlisted stakes are valued at interim and annual reporting dates, so a
    # threshold on next quarter is compared with the latest quarter on the same
    # clock: a first or third quarter for a first or third, and vice versa.
    next_n = kpi["for_period"].split()[0][1]
    valuation = next_n in "24"
    same_clock = [(q, v) for q, v in zip(equity["quarters"], equity["values"])
                  if (q[5] in "24") == valuation]
    eq_q, eq_v = latest([q for q, _ in same_clock], [v for _, v in same_clock])
    ret_h, ret_v = latest(halves, returns)
    pipe_at, pipe_v = latest(pipe_q, pipe)
    series = {
        "adt_quarter": (list(kq), kpi_q["adt_headline"]),
        "unlisted_equity": (equity["quarters"], equity["values"]),
        "margin_fund_return": (halves, returns),
        "lme_adv": (list(kq), kpi_q["adv_lme"]),
        "commodities_margin": (commod["quarters"], commod["margin"]),
        "ipo_applications": (pipe_q, pipe),
    }
    current = {
        "adt_quarter": (kq[-1], kpi_q["adt_headline"][-1]),
        "unlisted_equity": (eq_q, eq_v),
        "margin_fund_return": (ret_h, ret_v),
        "lme_adv": (kq[-1], kpi_q["adv_lme"][-1]),
        "commodities_margin": (commod["quarters"][-1], commod["margin"][-1]),
        "ipo_applications": (pipe_at, pipe_v),
    }
    entries = [dict(entry, current=current[entry["id"]][1], as_of=current[entry["id"]][0])
               for entry in kpi["quantified"]]
    breached = [e for e in entries if headroom(e["direction"], e["threshold"], e["current"]) < 0]
    latest_q = staging["quarters"][-1]
    stale = [e for e in entries if e["as_of"] != latest_q]
    gated = {item["indicator"]: item["text"] for item in kpi.get("not_on_page", [])}

    overview = headroom_exhibit(
        f"下季 {len(entries)} 条阈值："
        + (f"{len(breached)} 条当前已越过（{'、'.join(e['metric'] for e in breached)}）" if breached
           else "当前全部在安全侧"),
        entries, "current",
        note=(
            "正值 = 仍在安全侧。阈值逐字取自本季分析稿第 8 节，当前值取各自最近一次印出的读数；"
            + "；".join(f"{e['metric']}取 {e['as_of']}" for e in stale)
            + ("。" if stale else "")
            + "".join(f"第 {n} 个指标：{text}" for n, text in sorted(gated.items()))),
        src_extra=("阈值为本地季报分析稿的设定，不是公司指引；港交所不发布任何财务指引。"
                   "当前值的来历见各条走势图与核对抽屉。"),
    )
    overview["ref"] = "EX_NEXT"

    def line_chart(entry_id: str, *, fmt: str, ylab: str, actual_name: str, note: str,
                   src_extra: str, as_of_words: str = "") -> dict:
        entry = next(e for e in entries if e["id"] == entry_id)
        xlabels, values = series[entry_id]
        chart = two_line_chart(
            f"{entry['metric']}：下季阈值 {unit_words(entry['unit'], entry['threshold'])}，"
            f"当前 {unit_words(entry['unit'], entry['current'])}{as_of_words}",
            list(xlabels), values, entry, fmt=fmt, ylab=ylab, actual_name=actual_name,
            risk_label=f"下季阈值 {unit_words(entry['unit'], entry['threshold'])}",
            bull_label=(f"加仓线 {unit_words(entry['unit'], entry['bull_threshold'])}"
                        if "bull_threshold" in entry else ""),
            note=note, src_extra=src_extra)
        chart["ref"] = "EX_NEXT_" + entry_id.upper()
        return chart

    adt = kpi_q["adt_headline"]
    adt_e = next(e for e in entries if e["id"] == "adt_quarter")
    year_ago = f"{int(latest_q[:4]) - 1}Q{int(latest_q[5]) % 4 + 1}"
    below = [q for q, v in zip(kq, adt) if v < adt_e["threshold"]]
    adt_chart = line_chart(
        "adt_quarter", fmt="f1", ylab="HK$bn / 日", actual_name="现货日均成交额（季均）",
        note=(f"{len(adt)} 个季度里低于 {unit_words('hkd_bn', adt_e['threshold'])} 的有 {len(below)} 个"
              + (f"（最近一次 {below[-1]}）" if below else "")
              + (f"；下季的上年同季 {year_ago} 为 {unit_words('hkd_bn', adt[kq.index(year_ago)])}，"
                 "所以跌破这条线也就意味着同比转负" if year_ago in kq and adt[kq.index(year_ago)] > adt_e["threshold"] else "")
              + "。" + gated.get(adt_e["indicator"], "")),
        src_extra=f"季度日均成交额取自各期公告的市场统计表，只回到 {kq[0]}（市场统计不能相减）。")

    eq_e = next(e for e in entries if e["id"] == "unlisted_equity")
    eq_chart = line_chart(
        "unlisted_equity", fmt="f0c", ylab="HK$M", actual_name="未上市股权估值收益 / 损失（第二至四季为 D）",
        as_of_words=f"（{eq_q}，{'估值季' if valuation else '非估值季'}）",
        note=(f"阈值问的是 {kpi['for_period']}，那是{'估值季' if valuation else '非估值季'}，"
              f"所以当前值取最近一个同类季度（{eq_q}）：{signed_hkd(eq_v)}"
              + ("" if equity["quarters"][-1] == eq_q else
                 f"；本季 {equity['quarters'][-1]} 的读数 {signed_hkd(equity['values'][-1])} 在另一种季度上，不是这条线的比较对象")
              + f"。{len(same_clock)} 个同类季度里绝对值最大的是 "
              f"{hkd_m(max(abs(v) for _, v in same_clock))}。"
              + gated.get(eq_e["indicator"], "")),
        src_extra="取自 Corporate Funds 净投资收益分析表「Equity securities」一行；第二至四季为累计期相减，来历见核对抽屉。")

    ret_e = next(e for e in entries if e["id"] == "margin_fund_return")
    below_r = [h for h, v in zip(halves, returns) if v < ret_e["threshold"]]
    funds = {r["half"]: r for r in staging["margin_fund_returns"]["readings"]}
    ret_chart = line_chart(
        "margin_fund_return", fmt="pct2", ylab="年化回报", actual_name="保证金及结算所基金年化净投资回报率（上半年）",
        as_of_words=f"（{ret_h}）",
        note=(f"{len(halves)} 个上半年里有 {len(below_r)} 个低于 {ret_e['threshold']:.1f}%："
              + "、".join(f"{h} {v:.2f}%" for h, v in zip(halves, returns) if v < ret_e["threshold"])
              + "。这条警示线另带一个条件「平均规模未缩水」："
              f"{ret_h} 平均规模 HK${funds[ret_h]['average_fund_size_hkd_bn']:,.1f}B"
              + (f"（上年同期 HK${funds[prev_half(ret_h)]['average_fund_size_hkd_bn']:,.1f}B）"
                 if prev_half(ret_h) in funds else "")
              + "。" + gated.get(ret_e["indicator"], "")),
        src_extra="取自各年中期业绩公告的保证金及结算所基金净投资收益表（合计列，已扣除给结算参与者的利息回赠）。")

    lme_e = next(e for e in entries if e["id"] == "lme_adv")
    lme = kpi_q["adv_lme"]
    lme_chart = line_chart(
        "lme_adv", fmt="f0c", ylab="千手 / 日", actual_name="LME 计费日均手数",
        note=(f"{len(lme)} 个季度里低于 {lme_e['threshold']:,.0f} 千手的有 {sum(1 for v in lme if v < lme_e['threshold'])} 个、"
              f"达到 {lme_e['bull_threshold']:,.0f} 千手的有 {sum(1 for v in lme if v >= lme_e['bull_threshold'])} 个"
              f"（最高 {max(lme):,.0f} 千手，{kq[lme.index(max(lme))]}）。"
              "这一条与 Exhibit {EX_NEXT_COMMODITIES_MARGIN} 的商品分部利润率是同一个指标的两半："
              "减仓线是「或」，加仓线是「且」。"),
        src_extra=f"计费日均手数（剔除管理性交易）取自各期公告的市场统计表，只回到 {kq[0]}。")

    cm_e = next(e for e in entries if e["id"] == "commodities_margin")
    cm = [v for v in commod["margin"] if v is not None]
    cm_chart = line_chart(
        "commodities_margin", fmt="pct1", ylab="EBITDA ÷ 收入", actual_name="商品分部 EBITDA 利润率（第二至四季为 D）",
        note=(f"{len(cm)} 个季度里达到 {cm_e['threshold']:.0f}% 的有 {sum(1 for v in cm if v >= cm_e['threshold'])} 个，"
              f"达到 {cm_e['bull_threshold']:.0f}% 的有 {sum(1 for v in cm if v >= cm_e['bull_threshold'])} 个。"
              "分部表只印累计期，第三季的分部数要等第三季度公告的前九个月减上半年。"),
        src_extra=f"商品分部为 2023 年重组后的口径，从 {commod['quarters'][0]} 起；来历见核对抽屉。")

    ip_e = next(e for e in entries if e["id"] == "ipo_applications")
    missing = [q for q, v in zip(pipe_q, pipe) if v is None]
    # An empty cell must say why; a gap nobody explained is a reading nobody took.
    why = {item["quarter"]: item["text"] for item in staging["ipo_pipeline"].get("not_printed", [])}
    unexplained = [q for q in missing if q not in why]
    if unexplained:
        raise ValueError(f"ipo_pipeline has no reading and no not_printed note for {unexplained}")
    ip_chart = line_chart(
        "ipo_applications", fmt="f0", ylab="家（季末）", actual_name="有效 IPO 申请数（季末）",
        as_of_words=f"（{pipe_at} 末）",
        note=(f"最近一次印出的是 {pipe_at} 末的 {pipe_v:,.0f} 家"
              + (f"，<b>已经高过 {ip_e['bull_threshold']:,.0f} 家那条线</b>" if pipe_v >= ip_e["bull_threshold"] else "")
              + "。"
              + "".join(f"{q} 那一格是空的：{why[q]}" for q in missing)
              + f"这个数从 {pipe_q[0]} 起按季末印出；更早只有「超过 150 家」这样的说法。"),
        src_extra="有效 IPO 申请数取自各期业绩公告正文，逐条出处见 series 的 ipo_pipeline。")

    return [overview, adt_chart, eq_chart, ret_chart, lme_chart, cm_chart, ip_chart], entries

def disclosure_section(staging: dict, check: dict, recon: dict) -> list[dict]:
    quarters = staging["quarters"]
    q = staging["quarterly"]
    basis = staging["quarter_basis"]
    printed = [i for i, b in enumerate(basis) if b == "printed"]
    derived = [i for i, b in enumerate(basis) if b == "derived"]

    roi = q["revenue_and_other_income"]
    revenue_bar = {
        "ref": "EX_ROI",
        "kind": "gs_bar",
        # This quarter's reading first; the disclosure story is the note's.
        "title": (f"收入及其他收益 {hkd_m(roi[-1])}、同比 {signed(pct(roi[-1], roi[-5]))}"
                  + (f"，{len(quarters)} 季里最高" if roi[-1] == max(roi) and roi[-1] > max(roi[:-1]) else "")
                  + f"；柱子有 {len(derived)} 根是本页减出来的"),
        "xlabels": list(quarters),
        "xrot": 90,
        "xstep": LONG_STEP,
        "values": rounded(roi),
        "legend": "季度收入及其他收益",
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "HK$M",
        "ylab2": "同比增速",
        "yoy": {"name": "同比 (RHS)", "values": rounded(yoy_series(roi)),
                "color": "GREEN", "yfmt": "pct0"},
        "note": (
            "<b>柱子高低是真的；一半柱子的来历是本页的算术，但不是只有本页有。</b>"
            "第一、三季度的业绩公告各带一个「三个月」列；中期公告只印六个月、"
            "全年公告只印十二个月，所以本页这 "
            f"{len(derived)} 格是 H1 减 Q1、全年减前九个月得到的。"
            "<b>但公司自己也把这些季度印出来过</b> —— 每份年报里的"
            "「Analysis of Results by Quarter」按列印全四个季度，只是要晚得多。"
            # Named by number, not by position: 「下面两张图」 was wrong once (the
            # reconciliation was the third chart below), and after the page was
            # regrouped into four sections neither chart sits below this one.
            "Exhibit {EX_LAG} 与 Exhibit {EX_CHECK} 分别是「晚多久」和「本页的减法对不对」。"),
        "src_extra": (
            f"各季数字取自公司 {len(staging['announcements'])} 份业绩公告的简明综合损益表。"
            "解析后先用报表自身的算术核对：六项费用相加等于收入、加其他收入等于收入及其他收益、"
            "EBITDA 减折旧摊销等于经营溢利、除税前溢利减税项等于期内溢利、"
            "股东应占加非控股权益等于期内溢利 —— "
            f"{staging['statement_identities']['documents']} 份公告共 "
            f"{staging['statement_identities']['identities']} 条恒等式全部成立。"),
    }

    lag_head = [disclosure_lag(staging, qq, HEADLINE_LINES) for qq in quarters]
    by_pos = {n: [v for qq, v in zip(quarters, lag_head) if int(qq[5]) == n]
              for n in (1, 2, 3, 4)}
    odd_lags = by_pos[1] + by_pos[3]
    q2_old = [v for qq, v in zip(quarters, lag_head) if qq[5] == "2" and qq < "2022"]
    q2_new = [v for qq, v in zip(quarters, lag_head) if qq[5] == "2" and qq >= "2022"]
    box_from = min((qq for qq in quarters if qq[-1] in "24"
                    and (first_printed(staging, qq, "ebitda") or {}).get("doc", "")
                    .endswith("(Key Financials)")), default=None)
    q2_all = by_pos[2]
    cliff = ("<b>图上那一道是断崖不是斜坡</b>：没有任何一个第二季落在 60 天与 250 天之间。"
             if not any(60 <= v <= 250 for v in q2_all if v is not None) else "")
    all_printed = all(v is not None for v in lag_head)
    coverage = {
        "ref": "EX_LAG",
        "kind": "gs_line",
        "title": (f"每个季度都被印出来过，等待却差一个数量级：第二季 "
                  f"{max(q2_old)} 天 → {min(q2_new)} 天，"
                  f"其余三季始终在 {min(odd_lags)}–{max(by_pos[4])} 天之间"),
        "xlabels": list(quarters),
        "xrot": 90,
        "xstep": LONG_STEP,
        "values": lag_head,
        "legend": "季末到该季主线首次被印出的天数",
        "fmt": "f0",
        "yfmt": "f0",
        "label_fmt": "f0",
        "ylab": "天",
        "note": (
            "<b>这一页最初写的是「第二、四季度从未被印成损益表」。那是错的，"
            "而这张图是改正后的样子。</b>"
            "每一份年报里都有一张「Analysis of Results by Quarter」，"
            "把当年四个季度按列印全 —— <b>FY2016 就有</b>。"
            + (f"所以 {len(quarters)} 个季度的主线没有一个是没被印过的，差别只在等多久 —— "
               if all_printed else "所以主线的差别主要在等多久 —— ")
            + "<b>而慢的不是「双数季」，是第二季一个。</b>"
            f"第一、三季度在自己的季度公告里（{min(odd_lags)}–{max(odd_lags)} 天）；"
            f"第四季随全年业绩公告一起出来（{min(by_pos[4])}–{max(by_pos[4])} 天，"
            "从来不是异类）。只有第二季要等年报："
            f"连续{cn_count(len(q2_old))}年 {min(q2_old)}–{max(q2_old)} 天，也就是八个半月。"
            f"{box_from} 起中期公告正文补印双数季摘要框，第二季的等待一步降到 "
            f"{min(q2_new)}–{max(q2_new)} 天。"
            + cliff),
        "src_extra": (
            "每一格是「季末日」到「最早印出该季全部四条主线的那份文件的发布日」的日历天数。"
            "文件与发布日逐格记在 series 的 first_printed 里，"
            "年报发布日取自公司刊发公告，季度与全年公告发布日取自各份公告首页。"),
    }

    fee_quarters = [qq for qq in quarters
                    if disclosure_lag(staging, qq, FEE_LINES) is not None]
    fee_lags = [disclosure_lag(staging, qq, FEE_LINES) for qq in fee_quarters]
    missing = never_printed(staging, FEE_LINES)
    old_gaps, recent_gaps = fee_split_gaps(staging)
    fee_view = {
        "ref": "EX_FEESPLIT",
        "kind": "gs_line",
        "title": (f"收入怎么拆开的，只有 {len(fee_quarters)} 个季度被印过；"
                  f"另外 {len(missing)} 个季度至今没有"),
        "xlabels": list(fee_quarters),
        "xrot": 90,
        "xstep": 2,
        "values": fee_lags,
        "legend": "季末到该季六项费用收入被印出的天数",
        "fmt": "f0",
        "yfmt": "f0",
        "label_fmt": "f0",
        "ylab": "天",
        "note": (
            "<b>x 轴是一个集合，不是一个窗口</b> —— 只有被印过的季度在图上，"
            "所以相邻两格之间可能隔着一个没被印过的季度。"
            "年报那张季度表在 FY2016–FY2021 只印到「收入及其他收益」为止，"
            "六项费用收入是 <b>FY2022 才加进去的</b>。"
            f"于是单数季从 2016 年起一直有（在自己的季度公告里），"
            f"双数季要到 2022 年才有；{len(missing)} 个季度至今没有任何人印过它的收入分项："
            f"{old_gaps[0]}–{old_gaps[-1]} 的全部双数季"
            + (f"，加上{pending_words(staging, recent_gaps)}" if recent_gaps else "")
            + "。"
            "<b>Exhibit {EX_MIX} 那张收入构成图里，这些季度的分项是本页减出来的。</b>"),
        "src_extra": (
            "「印过」的判据是该季六项费用收入全部出现在某一份文件的三个月列或年度季度表里；"
            "逐格记在 series 的 first_printed 里。"),
    }

    even = [qq for qq in recon["covered_even"]]
    ours = [q["revenue_and_other_income"][quarters.index(qq)] for qq in even]
    theirs = [staging["ar_quarter_tables"]["by_year"][qq[:4]]["values"]
              ["revenue_and_other_income"][int(qq[5]) - 1] for qq in even]
    reconcile = {
        "ref": "EX_CHECK",
        "kind": "lines_endlabels",
        "title": (f"本页减出来的每一格，公司都印过一格对得上："
                  f"{recon['compared']} 次比对、{recon['mismatches']} 处不同"),
        "xlabels": list(even),
        "xrot": 90,
        "series": [
            {"name": "公司季度表印出的收入及其他收益", "values": rounded(theirs), "color": "NAVY"},
            {"name": "本页由 H1−Q1 / FY−9M 减出的同一格", "values": rounded(ours), "color": "GOLD"},
        ],
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "end_label": True,
        "ylab": "HK$M",
        "note": (
            "<b>两条线完全重合，这就是本图要说的事。</b>"
            f"本页把 {len(even)} 个双数季的收入及其他收益与公司季度表逐格比对；"
            f"把全部 {len(recon['years'])} 年、全部科目算进来是 {recon['compared']} 次比对，"
            f"其中 {recon['derived_compared']} 次落在本页用减法得到的格子上，"
            f"<b>{recon['mismatches']} 处不同</b>。"
            "先前这一页只拿到 33 次比对，因为它只知道 2022 年起的摘要框；"
            "年报那张季度表把同一道算术的对照物扩到四倍"
            + ((f"，而唯一还没有对照物的是{'刚发布的 ' if recon['uncovered_even'][0] == quarters[-1] else ' '}"
                f"{recon['uncovered_even'][0]}。")
               if len(recon["uncovered_even"]) == 1 else
               (f"，而还没有对照物的是 {'、'.join(recon['uncovered_even'])}。"
                if recon["uncovered_even"] else "，双数季已经全部有对照物。"))
            + "两条线画在一起而不是画差额：差额恒为零，画出来是一排看不见的柱子。"),
        "src_extra": (
            "公司值取自各年年报或全年业绩公告的「Analysis of Results by Quarter」表；"
            "本页值取自季度公告损益表的减法结果。两者的来源文件互不相同。"),
    }

    return [revenue_bar, coverage, fee_view, reconcile]


# ── section two: this quarter, on the lines that exist every quarter ─────────

def quarter_section(staging: dict, context: dict | None) -> list[dict]:
    quarters = staging["quarters"]
    q = staging["quarterly"]
    roi = q["revenue_and_other_income"]
    ebitda = q["ebitda"]
    margin = [e / r * 100 for e, r in zip(ebitda, roi)]
    profit = q["profit_attributable"]
    tax_rate = [-t / p * 100 for t, p in zip(q["taxation"], q["profit_before_tax"])]

    fee_lines = ["trading_fees", "clearing_fees", "listing_fees",
                 "depository_fees", "market_data_fees", "other_revenue"]
    fee_names = ["交易费及交易系统使用费", "结算及交收费", "上市费",
                 "存管、托管及代理人服务费", "市场数据费", "其他收入"]
    fee_colors = ["NAVY", "MBLUE", "BLUE", "GREEN", "GOLD", "GRAY"]
    non_fee = [r - v for r, v in zip(roi, q["revenue"])]
    non_fee_share = [n / r * 100 for n, r in zip(non_fee, roi)]
    trading_share = [(a + b) / r * 100
                     for a, b, r in zip(q["trading_fees"], q["clearing_fees"], roi)]

    non_trading = [a + b + c for a, b, c in zip(q["listing_fees"], q["depository_fees"],
                                                q["market_data_fees"])]
    non_trading_share = [n / r * 100 for n, r in zip(non_trading, q["revenue"])]

    staff = q["staff_costs"]
    opex_other = []
    for index in range(len(quarters)):
        total = roi[index] - ebitda[index]
        opex_other.append(total + staff[index])   # staff是负数，total为正的开支合计
    opex_total = [-(s) + o for s, o in zip(staff, opex_other)]
    txn_latest = q["transaction_expenses"][-1]
    printed_margin = (context or {}).get("printed_ebitda_margin_pct")
    gap = company_margin_gap(staging)
    old_gaps, recent_gaps = fee_split_gaps(staging)
    worst = min(range(len(non_fee)), key=lambda i: non_fee[i])
    nt_high = non_trading_share.index(max(non_trading_share))
    nt_low = non_trading_share.index(min(non_trading_share))

    margin_line = {
        "ref": "EX_MARGIN",
        "kind": "gs_line",
        "title": (f"EBITDA 利润率：本季 {margin[-1]:.1f}%，"
                  f"{len(quarters)} 季里最高 {max(margin):.1f}%、最低 {min(margin):.1f}%"),
        "xlabels": list(quarters),
        "xrot": 90,
        "xstep": LONG_STEP,
        "values": rounded(margin),
        "legend": "EBITDA / 收入及其他收益",
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "EBITDA 利润率",
        "note": (
            "公司自己在摘要框里印的 EBITDA 利润率用的是<b>扣除交易相关支出后的收入</b>做分母，"
            "而那一行只从 2020 年才出现在损益表上，所以本页统一用「EBITDA ÷ 收入及其他收益」"
            "自算全窗口 —— 口径一致优先于与公司口径逐格相同。"
            + (f"本季自算 {margin[-1]:.1f}%，公司在同一份公告里印的是 {printed_margin:.0f}%"
               "（其分母较小，因此略高）。" if printed_margin is not None else
               f"本季自算 {margin[-1]:.1f}%。")
            # 「两者的差在 1 个百分点以内」: 2023Q3-2024Q3 are 1.1-1.2 apart.
            + (f"两者的差在 {gap[0]:.1f}–{gap[1]:.1f} 个百分点之间，且方向固定。" if gap else "")),
        "src_extra": "EBITDA 与收入及其他收益均取自各期损益表；比值为本页自算。",
    }

    mix = {
        "ref": "EX_MIX",
        "kind": "stacked_dual",
        "title": (f"收入构成：六项费用收入 {hkd_m(q['revenue'][-1])}，"
                  f"其中交易费与结算费占收入及其他收益 {trading_share[-1]:.1f}%"),
        "xlabels": list(quarters),
        "xrot": 90,
        "xstep": LONG_STEP,
        "stacks": [{"name": name, "color": color, "values": rounded(q[field])}
                   for field, name, color in zip(fee_lines, fee_names, fee_colors)],
        "line": {"name": "交易费与结算费占收入及其他收益（右轴）", "color": "RED",
                 "values": rounded(trading_share), "ymax": 100},
        "fmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "HK$M",
        "ylab2": "交易与结算费占比 %",
        "note": (
            "<b>这张图的双数季分项，2022 年之前没有任何人印过。</b>柱是六项费用收入，"
            "双数季的六项由 H1 减 Q1、全年减前九个月得到；FY2022 起年报那张季度表"
            "加入了六项费用收入，所以 2022 年之后的双数季有公司自己的对照，"
            # This said 13 earlier quarters; the 13th is the one just published,
            # which waits for next year's annual results rather than predating 2022.
            f"{len(old_gaps)} 个更早的季度没有"
            + (f"，{pending_words(staging, recent_gaps, wait=False, spaced=False)} 要等到 "
               f"{int(recent_gaps[-1][:4]) + 1} 年 2 月的全年公告才有" if recent_gaps else "")
            + "。"
            "红线是最直接跟着成交量走的那两条"
            "（交易费与结算交收费）占收入及其他收益的比例。"
            f"这一比例在窗口里在 {min(trading_share):.1f}% 与 {max(trading_share):.1f}% 之间，"
            f"本季 {trading_share[-1]:.1f}%。"
            + ("<b>右轴画的是这一条而不是投资及其他收益的占比，理由见 Exhibit {EX_NETINV}</b>："
               f"后者在 {quarters[worst]} 为负，而这一图型的右轴自零点起算，负值会被画到画布外。"
               if non_fee[worst] < 0 else "")
            + "右轴另显式设了 100% 的上界 —— 它默认封顶在 60，超过就同样落在画布外。"),
        "src_extra": "六项费用收入与收入及其他收益逐期取自损益表；占比为本页自算。",
    }

    profit_tax = {
        "ref": "EX_PROFIT",
        "kind": "bar_line_dual",
        "title": (f"股东应占溢利 {hkd_m(profit[-1])}、同比 {signed(pct(profit[-1], profit[-5]))}"
                  + (f"，{len(quarters)} 季里最高" if profit[-1] > max(profit[:-1]) else "")
                  + f"；有效税率 {tax_rate[-1]:.1f}%"),
        "xlabels": list(quarters),
        "xrot": 90,
        "xstep": LONG_STEP,
        "bar": {"name": "股东应占溢利", "values": rounded(profit), "color": "NAVY"},
        "line": {"name": "有效税率（右轴）", "values": rounded(tax_rate),
                 "color": "RED", "yfmt": "pct1"},
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "HK$M",
        "ylab2": "有效税率",
        "note": (
            f"有效税率为「税项 ÷ 除税前溢利」，{len(quarters)} 季里在 "
            f"{min(tax_rate):.1f}% 到 {max(tax_rate):.1f}% 之间。"
            "香港利得税率 16.5%，本页窗口里的偏离主要来自英国子公司（LME）与"
            "各期的过往年度调整，2024 年起另有 OECD 支柱二的补足税。"
            "双数季的溢利同样是减出来的，而它属于 Exhibit {EX_CHECK} 那道对照覆盖到的科目 —— "
            "公司季度表印出的除税前溢利、税项与股东应占溢利，与本页的减法逐格相同。"),
        "src_extra": "溢利、除税前溢利与税项逐期取自损益表；有效税率为本页自算。",
    }

    non_trading_ex = {
        "ref": "EX_NONTRADE",
        "kind": "stacked_dual",
        "title": (f"不随成交量走的那部分收入：上市费、存管与市场数据合计 "
                  f"{hkd_m(non_trading[-1])}，占费用收入 {non_trading_share[-1]:.1f}%"),
        "xlabels": list(quarters),
        "xrot": 90,
        "xstep": LONG_STEP,
        "stacks": [
            {"name": "上市费", "color": "BLUE", "values": rounded(q["listing_fees"])},
            {"name": "存管、托管及代理人服务费", "color": "GREEN",
             "values": rounded(q["depository_fees"])},
            {"name": "市场数据费", "color": "GOLD", "values": rounded(q["market_data_fees"])},
        ],
        "line": {"name": "占六项费用收入比例（右轴）", "color": "RED",
                 "values": rounded(non_trading_share), "ymax": 100},
        "fmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "HK$M",
        "ylab2": "占费用收入 %",
        "note": (
            "交易所最像订阅制的三条腿：上市费按年摊、存管费按持仓与动作收、市场数据费按终端收。"
            # 「一路降到」: the share zig-zags with the seasons (2023Q4 is 27.4%);
            # what is true is the high and the low and when each came.
            f"三者合计占六项费用收入的比例从 {quarters[nt_high]} 的 {max(non_trading_share):.1f}% "
            f"{'降' if nt_high < nt_low else '升'}到 {quarters[nt_low]} 的 "
            f"{min(non_trading_share):.1f}%，本季 {non_trading_share[-1]:.1f}% —— "
            "<b>不是它们缩小了，是交易费和结算费涨得更快。</b>"
            "读这条线要注意分母：成交清淡的季度它会自动抬高。"
            "右轴同样显式设了 100% 的上界。"),
        "src_extra": "三项收入逐期取自损益表；占比分母为同期六项费用收入合计。",
    }

    opex = {
        "ref": "EX_OPEX",
        "kind": "stacked_dual",
        "title": (f"营业开支与交易相关支出合计 {hkd_m(opex_total[-1])}，其中员工成本 "
                  f"{hkd_m(-staff[-1])}（占 {-staff[-1] / opex_total[-1] * 100:.1f}%）"),
        "xlabels": list(quarters),
        "xrot": 90,
        "xstep": LONG_STEP,
        "stacks": [
            {"name": "员工成本及相关开支", "color": "NAVY", "values": rounded([-v for v in staff])},
            {"name": "其余营业开支", "color": "GOLD", "values": rounded(opex_other)},
        ],
        "line": {"name": "营业开支占收入及其他收益（右轴）", "color": "RED",
                 "values": rounded([o / r * 100 for o, r in zip(opex_total, roi)]),
                 "ymax": 100},
        "fmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "HK$M",
        "ylab2": "开支占收入 %",
        "note": (
            "<b>开支合计不是从明细行相加得到的，是从 EBITDA 倒推的</b>："
            "「收入及其他收益 − EBITDA」。因此它比公司自己印的「营业开支」多一块 —— "
            f"多的是交易相关支出，本季 {hkd_m(-txn_latest)}："
            f"本季倒推值 {hkd_m(opex_total[-1])}，公司印出的营业开支 "
            f"{hkd_m(opex_total[-1] + txn_latest)}。"
            "之所以不逐季扣掉那一块，是因为它 2020 年才独立成行，"
            "扣了会让 2020 年之前与之后不是同一个口径。"
            "从 EBITDA 倒推的理由是明细行的行数在窗口内变过三次"
            "（2018 年起信息技术开支独立成行、2020 年起慈善捐款独立成行），"
            "而两个端点的定义十年没变。员工成本一行则全窗口都在，直接取自损益表。"
            "「其余营业开支」因此是差额，把定义变过的那几行都收在里面 —— "
            "它是一个残差，不是公司印出的科目。"),
        "src_extra": "员工成本取自损益表；开支合计由收入及其他收益减 EBITDA 得到。",
    }
    return [margin_line, mix, profit_tax, non_trading_ex, opex]


# ── section three: the rebate, which is only visible twice a year ───────────

def investment_section(staging: dict) -> list[dict]:
    quarters = staging["quarters"]
    q = staging["quarterly"]
    roi = q["revenue_and_other_income"]
    non_fee = [r - v for r, v in zip(roi, q["revenue"])]
    non_fee_share = [n / r * 100 for n, r in zip(non_fee, roi)]
    worst = min(range(len(non_fee)), key=lambda i: non_fee[i])
    opposite_halves, half_steps = half_direction_steps(staging)

    quarterly_net = {
        "ref": "EX_NETINV",
        "kind": "bar_line_dual",
        "title": (f"季度能看见的只有净额：本季投资及其他收益 {hkd_m(non_fee[-1])}，"
                  f"占收入及其他收益 {non_fee_share[-1]:.1f}%"),
        "xlabels": list(quarters),
        "xrot": 90,
        "xstep": LONG_STEP,
        "bar": {"name": "投资及其他收益（收入及其他收益 − 六项费用收入）",
                "values": rounded(non_fee), "color": "GOLD"},
        "line": {"name": "占收入及其他收益（右轴）", "values": rounded(non_fee_share),
                 "color": "RED", "yfmt": "pct1"},
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "HK$M",
        "ylab2": "占比",
        "note": (
            ((f"<b>{quarters[worst]} 这一格是负的 —— {hkd_m(non_fee[worst])}，占比 "
              f"{non_fee_share[worst]:.2f}%。</b>"
              + ("那一季公司报的是一笔净投资亏损，"
                 "集体投资计划的公允价值在 2020 年 3 月被打下去。" if quarters[worst] == "2020Q1" else "")
              + "本页把这一条单独画成柱线图而不是画在 Exhibit {EX_MIX} 那张收入构成图的右轴上，"
              "就是因为这一格：堆叠双轴图的右轴自零点起算，"
              f"一个 {minus_sign(f'{non_fee_share[worst]:.2f}')}% 的点会被静默画到画布之外，而图例照常显示它。"
              "柱线图的右轴按数据算，负值画得出来。")
             if non_fee[worst] < 0 else "")
            + "这条线是季度频率能看到的全部 —— 它的毛额与返还额只在半年报上，见 Exhibit {EX_REBATE}。"),
        "src_extra": (
            "投资及其他收益为「收入及其他收益 − 六项费用收入」，两个端点均取自损益表；"
            "它等于净投资收益加慈善基金捐款收入与杂项收入，"
            "而后两项在窗口前段并未单列成行，因此本页取差额而不是取那一行。"),
    }

    halves = staging["halves"]
    basis = staging["half_basis"]
    gross = staging["half_investment"]["gross"]
    rebates = staging["half_investment"]["rebates"]
    net = staging["half_investment"]["net"]
    share = [-r / g * 100 for r, g in zip(rebates, gross)]
    derived = sum(1 for b in basis if b == "derived")
    peak = share.index(max(share))
    trough = share.index(min(share))
    at = {half: i for i, half in enumerate(halves)}
    f0, f1 = (at[h] for h in FLOOR_EPISODE)
    r0, r1 = (at[h] for h in RISE_EPISODE)

    # The same half a year earlier: the list alternates H1, H2.
    ago = len(halves) - 3
    if halves[ago] != f"{int(halves[-1][:4]) - 1}{halves[-1][4:]}":
        raise ValueError(f"half_investment: {halves[ago]} is not the half a year before {halves[-1]}")
    funds = {r["half"]: r for r in staging["margin_fund_returns"]["readings"]}
    now_f, ago_f = funds.get(halves[-1]), funds.get(halves[ago])
    fund_words = (
        f"中期公告那张保证金及结算所基金表（{doc_words(now_f['doc'])}第 {now_f['page']} 页）："
        f"平均规模 HK${ago_f['average_fund_size_hkd_bn']:,.1f}B → HK${now_f['average_fund_size_hkd_bn']:,.1f}B，"
        f"净投资收益 {hkd_m(ago_f['net_investment_income_hkd_m'])} → {hkd_m(now_f['net_investment_income_hkd_m'])}，"
        f"年化回报 {ago_f['annualised_return_pct']:.2f}% → {now_f['annualised_return_pct']:.2f}% —— "
        "<b>规模变大了，收益反而少了</b>。"
        if now_f and ago_f and now_f["annualised_return_pct"] < ago_f["annualised_return_pct"]
        and now_f["average_fund_size_hkd_bn"] > ago_f["average_fund_size_hkd_bn"] else "")
    spread = {
        "ref": "EX_REBATE",
        "kind": "stacked_dual",
        "title": (f"保证金投资收益：{half_words(staging)}返还给结算参与者 {hkd_m(-rebates[-1])}、"
                  f"同比 {signed(pct(rebates[-1], rebates[ago]))}；毛额 {signed(pct(gross[-1], gross[ago]))}，"
                  f"公司留下的净额 {signed(pct(net[-1], net[ago]))}"),
        "xlabels": list(halves),
        "xrot": 90,
        "stacks": [
            {"name": "留在公司（净投资收益）", "color": "NAVY", "values": rounded(net)},
            {"name": "返还给结算参与者", "color": "GOLD", "values": rounded([-r for r in rebates])},
        ],
        "line": {"name": "返还比例（右轴）", "color": "RED", "values": rounded(share), "ymax": 100},
        "fmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "HK$M",
        "ylab2": "返还比例 %",
        "note": (
            "<b>柱高是毛额，两段的分法才是这门生意。</b>公司把清算会员缴来的保证金拿去投资，"
            "再把其中大部分利息按约定返还给会员；损益表上「投资收益」与"
            "「支付予参与者的利息回赠」是两行，「净投资收益」是它们的和。"
            # 「一路走到」: it went to 1.4% in 2020H2 on the way; the next chart says so.
            f"返还比例从 {halves[0]} 的 {share[0]:.1f}% 走到 "
            f"{halves[peak]} 的 {max(share):.1f}%"
            + (f"（中间在 {halves[trough]} 低到 {min(share):.1f}%）" if 0 < trough < peak else "")
            + f"，{half_words(staging)} {share[-1]:.1f}%（上年同期 {share[ago]:.1f}%）。"
            + fund_words
            + "<b>利率上行时毛额和返还一起涨，净额涨得慢得多</b> —— "
            "把这门生意当成利率的线性敞口，会在两个方向上都算错。"
            "右轴显式设了 100% 的上界。"),
        "src_extra": (
            "毛额与返还额只出现在中期与全年业绩公告的损益表上，季度损益表只印净额；"
            f"因此本图按半年频率，{len(halves)} 个半年里 {derived} 个下半年由全年减上半年得到。"),
    }

    gross_net = {
        "ref": "EX_GROSSNET",
        "kind": "lines_endlabels",
        "title": (f"同一个组合的两条线：毛额自 {halves[0]} 起涨了 "
                  f"{pct(gross[-1], gross[0]):.0f}%，净额只涨了 {pct(net[-1], net[0]):.0f}%"),
        "xlabels": list(halves),
        "xrot": 90,
        "series": [
            {"name": "投资收益毛额", "values": rounded(gross), "color": "GOLD"},
            {"name": "净投资收益（公司留下的）", "values": rounded(net), "color": "NAVY"},
        ],
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "end_label": True,
        "ylab": "HK$M",
        "note": (
            "<b>这两条线在窗口里两次讲了相反的故事。</b>"
            # 「毛额腰斩而净额几乎没动 —— 返还比例同期从 28% 掉到 3%」: over the
            # halves where the share went 28% to 3% the gross fell 32%, not half.
            f"2020 下半年到 2021 上半年利率见底：{FLOOR_EPISODE[0]} 到 {FLOOR_EPISODE[1]} "
            f"毛额 {minus_sign(signed(pct(gross[f1], gross[f0]), 0))}、"
            f"净额只 {minus_sign(signed(pct(net[f1], net[f0]), 0))} —— "
            f"返还比例同期从 {share[f0]:.0f}% 掉到 {share[f1]:.0f}%，会员那一侧先被压缩。"
            "2022 下半年起利率回升，毛额一年之内"
            + ("涨了十倍以上" if gross[r1] / gross[r0] - 1 >= 10 else
               f"涨到 {gross[r1] / gross[r0]:.1f} 倍")
            + f"，净额跟不上，因为返还比例同时冲到{cn_count(round(share[r0 + 1] / 10))}成。"
            # Moved here from the page's old brief when the brief became the
            # quarter's three findings: the count is a fact about this chart.
            + f"毛额与净额在 {half_steps} 次半年环比里有 {opposite_halves} 次走出相反方向。"
            "<b>季度损益表上只有其中一条线看得见</b>，"
            "而它恰好是变动较小的那条。"),
        "src_extra": "两条线均取自中期与全年业绩公告的损益表；下半年为全年减上半年。",
    }
    return [quarterly_net, spread, gross_net]


# ── section four: volume, and the part of it that cannot be drawn ───────────

def volume_section(staging: dict) -> list[dict]:
    kq = staging["kpi_quarters"]
    kpi = staging["kpi_quarterly"]
    quarters = staging["quarters"]
    q = staging["quarterly"]
    index_of = [quarters.index(x) for x in kq]
    trading_clearing = [q["trading_fees"][i] + q["clearing_fees"][i] for i in index_of]
    adt = kpi["adt_headline"]

    elasticity = elasticities(staging)
    steps_x = qoq(adt)
    steps_y = qoq(trading_clearing)
    slope, r2 = slope_and_r2(steps_x, steps_y)
    opposite = sum(1 for a, b in zip(steps_x, steps_y) if a * b < 0)

    adt_fees = {
        "ref": "EX_ADT",
        "kind": "bar_line_dual",
        "title": (f"现货市场日均成交额与交易结算费：本季 HK${adt[-1]:,.1f}bn、"
                  f"费 {hkd_m(trading_clearing[-1])}"),
        "xlabels": list(kq),
        "xrot": 90,
        "xstep": KPI_STEP,
        "bar": {"name": "交易费 + 结算交收费", "values": rounded(trading_clearing), "color": "NAVY"},
        "line": {"name": "现货日均成交额（右轴，HK$bn）", "values": rounded(adt),
                 "color": "RED", "yfmt": "f0"},
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "HK$M",
        "ylab2": "HK$bn / 日",
        "note": (
            f"<b>这张图从 {kq[0]} 起画，不是因为更早的数据没找到，是因为它不存在。</b>"
            "市场统计是「每个交易日的平均」，六个月的平均减三个月的平均不等于第二季 —— "
            "把损益表那道减法搬过来会造出一个没有意义的数。"
            "更准确地说是：公司从 2022 年起在公告正文加了「本季 vs 去年同季」一节，"
            "那一节带一张三个月的市场统计表，且只带一个上年比较列 —— "
            f"所以能拿到的最早一个离散季度就是 {kq[0]}，再往前公告只印一季度、"
            "上半年、前九个月与全年四种累计口径。"
            f"这 {len(kq)} 季里，日均成交额每环比变动 1%，交易与结算费变动 {slope:.3f}%"
            f"（R² {r2:.2f}），{len(steps_x)} 次环比里只有 {opposite} 次方向相反。"),
        "src_extra": (
            "日均成交额取自各期公告的市场统计表；交易费与结算交收费取自损益表。"
            "市场统计表<b>不从 PDF 的文本层读取</b>：公司用上标标注纪录，"
            "纯文本导出会把上标并进数字本身（日均 283.0 变成 283.04），"
            f"{staging['text_layer']['figures_compared']} 个数字里有 "
            f"{staging['text_layer']['corrupted_by_glued_marker']} 个会被这样读错，"
            "而读错之后仍是一个合法的数。本页按字形磅值筛选后再解析。"),
    }

    damping = {
        "ref": "EX_SLOPE",
        "kind": "lines_endlabels",
        "title": (f"越往损益表下面走，成交额的波动被削得越平："
                  f"斜率 {elasticity['slope_trading_clearing']:.2f} → "
                  f"{elasticity['slope_revenue']:.2f} → "
                  f"{elasticity['slope_revenue_and_other_income']:.2f}"),
        "xlabels": list(kq),
        "xrot": 90,
        "xstep": KPI_STEP,
        "series": [
            {"name": "现货日均成交额（指数，首季 = 100）", "color": "RED",
             "values": rounded([v / adt[0] * 100 for v in adt])},
            {"name": "交易费 + 结算交收费", "color": "NAVY",
             "values": rounded([v / trading_clearing[0] * 100 for v in trading_clearing])},
            {"name": "收入及其他收益", "color": "GREEN",
             "values": rounded([q["revenue_and_other_income"][i]
                                / q["revenue_and_other_income"][index_of[0]] * 100
                                for i in index_of])},
        ],
        "fmt": "f0",
        "yfmt": "f0",
        "label_fmt": "f0",
        "end_label": True,
        "ylab": "指数（首季 = 100）",
        "note": (
            "三条线同起点，斜率来自环比回归而不是端点："
            f"日均成交额每变动 1%，交易与结算费变动 "
            f"{elasticity['slope_trading_clearing']:.3f}%（R² {elasticity['r2_trading_clearing']:.2f}）、"
            f"六项费用收入变动 {elasticity['slope_revenue']:.3f}%"
            f"（R² {elasticity['r2_revenue']:.2f}）、"
            f"收入及其他收益变动 {elasticity['slope_revenue_and_other_income']:.3f}%"
            f"（R² {elasticity['r2_revenue_and_other_income']:.2f}）。"
            "<b>削平它的不是费率分档</b>（港交所现货交易费是按成交金额定率收的），"
            "而是混合：衍生品与 LME 的量、上市费与市场数据的订阅性收入，"
            "以及一整块跟着利率而不是跟着成交额走的投资收益。"),
        "src_extra": (f"指数化仅用于同图比较；斜率与 R² 由本页对 {elasticity['steps']} 次环比变动"
                      "做最小二乘回归得到。"),
    }

    volumes = {
        "ref": "EX_ADV",
        "kind": "lines_endlabels",
        "title": (f"三条量：期货 {kpi['adv_futures'][-1]:,.0f} 千张、"
                  f"股票期权 {kpi['adv_stock_opts'][-1]:,.0f} 千张、"
                  f"LME {kpi['adv_lme'][-1]:,.0f} 千手"),
        "xlabels": list(kq),
        "xrot": 90,
        "xstep": KPI_STEP,
        "series": [
            {"name": "期交所衍生品日均张数", "values": rounded(kpi["adv_futures"]), "color": "NAVY"},
            {"name": "股票期权日均张数", "values": rounded(kpi["adv_stock_opts"]), "color": "BLUE"},
            {"name": "LME 计费日均手数", "values": rounded(kpi["adv_lme"]), "color": "GOLD"},
        ],
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "end_label": True,
        "ylab": "千张 / 千手（日均）",
        "note": (
            "三条量各自对应一个分部，且互不联动：期交所衍生品与股票期权跟着香港股市的波动率走，"
            "LME 跟着全球金属的实货与套保需求走。"
            "LME 那一行 2018 年及以前公司印的是绝对手数（如 629,556），2019 年起改印千手，"
            "并且口径同时从「日均成交量」改成「计费日均手数」（剔除管理性交易）—— "
            "<b>不是同一个数换了单位，是换了一个数</b>，因此本页不把两代接在一起，"
            "这张图只画公司按季印出的那一段。"),
        "src_extra": "三条量取自各期公告的市场统计表，读法同 Exhibit {EX_ADT}（按字形磅值筛选上标）。",
    }

    connect = {
        "ref": "EX_CONNECT",
        "kind": "lines_endlabels",
        "title": (f"互联互通：北向日均 RMB{kpi['adt_northbound'][-1]:,.1f}bn、"
                  f"南向日均 HK${kpi['adt_southbound'][-1]:,.1f}bn"),
        "xlabels": list(kq),
        "xrot": 90,
        "xstep": KPI_STEP,
        "series": [
            {"name": "北向日均成交额（人民币 bn）", "values": rounded(kpi["adt_northbound"]),
             "color": "NAVY"},
            {"name": "南向日均成交额（港元 bn）", "values": rounded(kpi["adt_southbound"]),
             "color": "GOLD"},
            {"name": "债券通北向日均（人民币 bn）", "values": rounded(kpi["adt_bond_conn"]),
             "color": "GREEN"},
        ],
        "fmt": "f1",
        "yfmt": "f0",
        "label_fmt": "f1",
        "end_label": True,
        "ylab": "十亿 / 日",
        "note": (
            "<b>三条线、两种货币，图上只能比形状不能比高低。</b>"
            "北向与债券通北向以人民币计、南向以港元计，"
            "公司在同一张表里就是这样并排印的，本页不做换算 —— "
            "换算需要选一个汇率口径，而公司没有给。"
            "南向成交计入现货市场的日均成交额（公司在表下注明），北向不计入。"),
        "src_extra": "三条互联互通日均值取自各期公告的市场统计表。",
    }

    years = staging["kpi_years"]
    annual = staging["kpi_annual"]
    long_view = {
        "ref": "EX_ANNUAL",
        "kind": "bars_labeled",
        "title": (f"季度成交数据只回到 {kq[0]}，年度口径回到 {years[0]}：现货日均成交额 "
                  f"HK${annual['adt_headline'][0]:,.1f}bn → HK${annual['adt_headline'][-1]:,.1f}bn"),
        "xlabels": list(years),
        "values": rounded(annual["adt_headline"]),
        "legend": "现货市场日均成交额（HK$bn）",
        "fmt": "f1",
        "yfmt": "f0",
        "label_fmt": "f1",
        "ylab": "HK$bn / 日",
        "note": (
            # 「本页唯一一张年度图」stopped being true when section two gained a
            # year-by-year depository chart; what is true is narrower.
            "<b>这张年度成交图只画一条序列 —— 那是这张图真正的结论。</b>"
            f"现货市场日均成交额这一行{cn_count(len(years))}年同一口径，每一年的值在两份公告里各出现一次"
            "（当年全年公告的本期列、次年全年公告的比较列），逐年两两核对无差异。"
            "<b>衍生品与 LME 的年度成交量本来也该画在这张图的右轴上，本页不画</b>："
            "公司在同一个窗口里改过三次口径 —— FY2018 把 LME 那一行从「ADV」改成"
            "「Chargeable ADV」（剔除管理性交易）并把 2017 年比较值从 624,480 重述为 601,067；"
            "FY2019 把单位从绝对手数改成千手；FY2021 又把算法从「总成交量 ÷ 总交易日」"
            "改成「各产品 ADV 之和」，并重述了全部比较值。"
            "三代不是同一个数换了单位，接成一条线会得到一条每隔几年就跳一次的假趋势。"),
        "src_extra": ("年度值取自各年全年业绩公告的市场统计表；口径变化三处分别见 FY2018、FY2019 "
                      "两份公告的行名，以及 FY2021 公告附注 4 的原文说明。"),
    }
    return [adt_fees, damping, volumes, connect, long_view]


# ── audit tables ────────────────────────────────────────────────────────────

def line_words(entry: dict, key: str) -> str:
    """``≥ 65.0%`` / ``≤ HK$200M（绝对值）`` / ``≥ 70.0%（连续 2 季）``."""
    words = ("≥ " if entry["direction"] == "up" else "≤ ") + unit_words(entry["unit"], entry[key])
    if entry.get("absolute"):
        words += "（绝对值）"
    if key == "bull_threshold" and entry.get("bull_quarters", 1) > 1:
        words += f"（连续 {entry['bull_quarters']} 季）"
    return words


def prior_table(prior: dict, entries: list[dict]) -> dict:
    verdicts = {indicator["n"]: indicator["report_verdict"] for indicator in prior["indicators"]}
    rows = []
    for entry in entries:
        rows.append([
            f"{entry['indicator']}. {entry['metric']}",
            line_words(entry, "threshold") if "threshold" in entry else "—",
            line_words(entry, "bull_threshold") if "bull_threshold" in entry else "—",
            unit_words(entry["unit"], entry["actual"]),
            (f"{headroom(entry['direction'], entry['threshold'], entry['actual']):+.1f}%"
             if "threshold" in entry else "—"),
            (f"{headroom(entry['direction'], entry['bull_threshold'], entry['bull_actual']):+.1f}%"
             if "bull_threshold" in entry else "—"),
            verdicts[entry["indicator"]],
        ])
    return {
        "n": 0,
        "title": "上季阈值与本季实际（原单位；阈值取自上季本地分析稿第 8 节）",
        "headers": ["指标", "风险线", "加仓线", "本季实际", "风险线余量 D", "加仓线余量 D", "本季分析稿判定"],
        "rows": rows,
    }


def derived_series_table(staging: dict) -> dict:
    """Every quarter of the two series this page reads from cumulative tables, with its basis."""
    commod = commodities_series(staging)
    equity = unlisted_equity_series(staging)
    at = {quarter: i for i, quarter in enumerate(commod["quarters"])}
    rows = []
    for i, quarter in enumerate(equity["quarters"]):
        j = at.get(quarter)
        rows.append([
            quarter,
            "—" if j is None else f"{commod['revenue'][j]:,.0f}",
            "—" if j is None else f"{commod['ebitda'][j]:,.0f}",
            # half up, the way a filer's own text rounds: 432 / 768 is 56.25%,
            # and Python's format would print 56.2.
            "—" if j is None else f"{round_half_up(commod['margin'][j], 1)}%",
            signed_int(equity["values"][i]),
            "印出" if quarter[5] == "1" else "本页减出 D",
        ])
    return {
        "n": 0,
        "title": (f"商品分部（{commod['quarters'][0]} 起，2023 年口径）与未上市股权估值收益"
                  f"（{equity['quarters'][0]} 起）的季度值（HK$M）"),
        "headers": ["季度", "商品分部收入", "商品分部 EBITDA", "利润率", "未上市股权估值收益", "来历"],
        "rows": rows,
    }


def equity_prose_table(staging: dict) -> dict:
    """The discrete quarters the company printed in words, against this page's subtraction."""
    equity = unlisted_equity_series(staging)
    ours = dict(zip(equity["quarters"], equity["values"]))
    printed = [r for r in staging["unlisted_equity"]["readings"] if r["column"].startswith("three months")]
    rows = [[r["period"], signed_int(r["value"]), f"{doc_words(r['doc'])}第 {r['page']} 页（三个月列）",
             signed_int(ours[r["period"]]), signed_int(ours[r["period"]] - r["value"])]
            for r in printed if r["period"] in ours]
    rows += [[p["quarter"], signed_int(p["value"]), f"{doc_words(p['doc'])}第 {p['page']} 页（正文）",
              signed_int(ours[p["quarter"]]), signed_int(ours[p["quarter"]] - p["value"])]
             for p in staging["unlisted_equity"]["prose_quarters"] if p["quarter"] in ours]
    rows.sort(key=lambda row: (row[0], row[2]))
    return {
        "n": 0,
        "title": "未上市股权：公司单独印过的季度数，对本页的减法",
        "headers": ["季度", "公司印出", "出处", "本页相减", "差额"],
        "rows": rows,
    }


def audit_tables(staging: dict, entries: list[dict], check: dict,
                 recon: dict, first: int, extra: list[dict] | None = None) -> list[dict]:
    quarters = staging["quarters"]
    q = staging["quarterly"]
    rows = []
    for index, quarter in enumerate(quarters):
        rows.append([
            quarter,
            "公司印出" if staging["quarter_basis"][index] == "printed" else "本页减出 D",
            f"{q['revenue_and_other_income'][index]:,.0f}",
            f"{q['revenue'][index]:,.0f}",
            f"{q['ebitda'][index]:,.0f}",
            f"{q['profit_attributable'][index]:,.0f}",
            "、".join(staging["quarter_sources"][quarter]),
        ])
    ledger = {
        "n": first,
        "title": f"{len(quarters)} 个季度的原值与来历（HK$M）",
        "headers": ["季度", "来历", "收入及其他收益", "六项费用收入", "EBITDA",
                    "股东应占溢利", "来源公告"],
        "rows": rows,
    }

    tables_by_year = staging["ar_quarter_tables"]["by_year"]
    check_rows = []
    for year in sorted(tables_by_year):
        block = tables_by_year[year]
        cells = derived = bad = 0
        for field, vals in block["values"].items():
            if field not in q:
                continue
            for k in range(4):
                quarter = f"{year}Q{k + 1}"
                if quarter not in quarters:
                    continue
                ours = q[field][quarters.index(quarter)]
                if ours is None:
                    continue
                cells += 1
                if quarter[-1] in "24":
                    derived += 1
                if abs(abs(ours) - abs(vals[k])) > 0.5:
                    bad += 1
        check_rows.append([
            year, block["source"].replace(".txt", ""),
            str(len(block["values"])), str(cells), str(derived), str(bad),
        ])
    reconcile = {
        "n": first + 1,
        "title": (f"逐格对照公司自己的季度表：{recon['compared']} 格，"
                  f"其中 {recon['derived_compared']} 格是本页减出来的，"
                  f"{recon['mismatches']} 处不同"),
        "headers": ["年度", "公司文件", "该表科目数", "可比对格数", "其中本页减出", "不符"],
        "rows": check_rows,
    }

    census_rows = [[
        row["period"], row["field"],
        f"{row['first']:,.0f}", f"{row['again']:,.0f}",
        f"{row['again'] - row['first']:+,.0f}",
        f"{row['first_doc']} → {row['again_doc']}",
    ] for row in staging["restatement_census"]]
    census = {
        "n": first + 2,
        "title": (f"重述普查：每个期间被公司印过两次，"
                  f"{staging['restatement_paired_readings']:,} 对读数里 "
                  f"{len(census_rows)} 处不同"),
        "headers": ["期间", "科目", "首次印出", "一年后重印", "差额", "两份公告"],
        "rows": census_rows or [["—", "—", "—", "—", "—", "—"]],
    }

    tables = [ledger, reconcile, census]
    for table in extra or []:
        tables.append({**table, "n": first + len(tables)})
    if entries:
        tables.append({
            "n": first + len(tables),
            "title": "下季阈值与当前值（原单位；阈值取自本季本地分析稿第 8 节）",
            "headers": ["指标", "下季阈值", "加仓线", "当前值", "读数时点", "余量 D"],
            "rows": [[f"{e['indicator']}. {e['metric']}", line_words(e, "threshold"),
                      line_words(e, "bull_threshold") if "bull_threshold" in e else "—",
                      unit_words(e["unit"], e["current"]), e["as_of"],
                      f"{headroom(e['direction'], e['threshold'], e['current']):+.1f}%"]
                     for e in entries],
        })
    tables.append(ai_capex_cycle_table(first + len(tables)))
    return tables


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    q = staging["quarterly"]
    derived = sum(1 for basis in staging["quarter_basis"] if basis == "derived")
    return [f"收入及其他收益 HK${q['revenue_and_other_income'][-1]:,.0f}M",
            f"EBITDA 利润率 {q['ebitda'][-1] / q['revenue_and_other_income'][-1] * 100:.1f}%",
            f"{len(staging['quarters'])} 季里 {derived} 季为自算"]


def build_payload(staging: dict) -> dict:
    check = box_check(staging)
    recon = reconcile_against_printed(staging)
    quarters = staging["quarters"]
    q = staging["quarterly"]
    roi = q["revenue_and_other_income"]
    profit = q["profit_attributable"]
    rebates = staging["half_investment"]["rebates"]
    derived_total = sum(1 for b in staging["quarter_basis"] if b == "derived")
    period = display_period(staging["quarters"][-1])
    kpi = stamped_block(staging, "next_kpi", period)
    context = stamped_block(staging, "quarter_context", period)
    closure = stamped_block(staging, "followup_closure", period)
    prior = stamped_block(staging, "prior_kpi_settlement", period)
    release = release_source(staging)

    connect = stamped_block(staging, "connect_holdings", period)
    disclosure_ex = disclosure_section(staging, check, recon)
    quarter_ex = quarter_section(staging, context)
    investment_ex = investment_section(staging)
    volume_ex = volume_section(staging)
    built = {exhibit["ref"]: exhibit for exhibit in
             disclosure_ex + quarter_ex + investment_ex + volume_ex}
    built["EX_SEGQOQ"] = segment_qoq_chart(staging, context)
    built["EX_DEPOSITORY"] = depository_chart(staging)
    built["EX_CAPEX"] = capex_chart(staging, context)
    if connect:
        built["EX_CONNECT_HOLD"] = connect_holdings_chart(connect)
    # Four sections, in the order every page on this site uses. Each list names
    # its charts by ref; the check below refuses a chart that was built and not
    # placed, which is how a chart silently drops off a regrouped page.
    prior_ex, prior_entries = settled_threshold_section(staging, prior) if prior else ([], [])
    settled_ex = ([closure_exhibit(closure)] if closure else []) + prior_ex
    highlight_ex = [built[ref] for ref in HIGHLIGHT_REFS if ref in built]
    next_ex, entries = next_quarter_section(staging, kpi) if kpi else ([], [])
    routine_ex = [built[ref] for ref in ROUTINE_REFS]
    placed = [exhibit["ref"] for exhibit in highlight_ex + routine_ex]
    if sorted(placed) != sorted(built):
        raise ValueError(f"charts built but not placed in a section: {sorted(set(built) - set(placed))}; "
                         f"placed twice: {sorted(r for r in placed if placed.count(r) > 1)}")
    exhibits = resolve_refs(number_exhibits(settled_ex + highlight_ex + next_ex + routine_ex, start=1))
    number = {exhibit["ref"]: exhibit["n"] for exhibit in exhibits if exhibit.get("ref")}
    extra_tables = ([prior_table(prior, prior_entries), derived_series_table(staging),
                     equity_prose_table(staging)] if prior else [])
    tables = audit_tables(staging, entries, check, recon, len(exhibits) + 1, extra_tables)

    latest = latest_block(staging, period=period)
    old_gaps, recent_gaps = fee_split_gaps(staging)
    records = [name for name, field in (("收入及其他收益", "revenue_and_other_income"),
                                        ("股东应占溢利", "profit_attributable"))
               if q[field][-1] > max(q[field][:-1])]
    record_words = ("两者都是" if len(records) == 2 else (f"{records[0]}是" if records else "两者都不是"))
    margin_gap = company_margin_gap(staging)

    # ── the quarter in the analysis's own terms, recomputed ─────────────────
    equity = unlisted_equity_series(staging)
    eq_prev, eq_now = equity["values"][-2], equity["values"][-1]
    last_two = segment_ebitda_by_quarter(staging, quarters[-2:])
    ops_delta = sum(last_two[s][1] - last_two[s][0]
                    for s in staging["segment_readings"]["segments"] if s != "corporate_items")
    profit_delta = profit[-1] - profit[-2]
    large = [(qq, v) for qq, v in zip(equity["quarters"], equity["values"]) if v is not None and abs(v) > 100]
    on_clock = bool(large) and all(qq[5] in "24" for qq, _ in large)
    articles = []
    if eq_now - eq_prev > profit_delta > 0:
        articles.append((
            "构成", "新高的增量来自一笔半年一估的重估",
            f"股东应占溢利环比 {signed_hkd(profit_delta)}，未上市股权估值收益 {signed_hkd(eq_prev)} → "
            f"{signed_hkd(eq_now)}；四个经营分部的 EBITDA 环比合计 {signed_hkd(ops_delta)}。"))
    if connect:
        c = connect["readings"]
        nb_t, nb_h, sb_t, sb_h = (pct(c[k]["now"], c[k]["year_ago"]) for k in (
            "northbound_adt_rmb_bn", "northbound_holdings_rmb_bn",
            "southbound_adt_hkd_bn", "southbound_holdings_hkd_bn"))
        articles.append((
            "互联互通", "北向是换手，南向是配置" if nb_t > 2 * nb_h and abs(sb_t - sb_h) < 2 else "北向与南向",
            f"上半年北向日均成交额 {signed(nb_t)}、6 月 30 日持仓 {signed(nb_h)}；"
            f"南向 {signed(sb_t)}、{signed(sb_h)}。"))
    funds = {r["half"]: r for r in staging["margin_fund_returns"]["readings"]}
    half_now = staging["halves"][-1]
    if half_now in funds and prev_half(half_now) in funds:
        f_now, f_ago = funds[half_now], funds[prev_half(half_now)]
        articles.append((
            "浮存金",
            ("规模变大，收益变少" if f_now["average_fund_size_hkd_bn"] > f_ago["average_fund_size_hkd_bn"]
             and f_now["net_investment_income_hkd_m"] < f_ago["net_investment_income_hkd_m"] else "保证金投资收益"),
            f"保证金及结算所基金平均规模 HK${f_ago['average_fund_size_hkd_bn']:,.1f}B → "
            f"HK${f_now['average_fund_size_hkd_bn']:,.1f}B，年化回报 {f_ago['annualised_return_pct']:.2f}% → "
            f"{f_now['annualised_return_pct']:.2f}%；返还给结算参与者同比 {signed(pct(rebates[-1], rebates[-3]))}。"))
    return {
        "schema_version": "quarterly-dashboard/hkex-v1",
        "page": {"slug": "hkex", "language": "zh-CN"},
        "company": {
            "ticker": "00388.HK",
            "name": "Hong Kong Exchanges and Clearing Limited",
            "group": "exchanges",
            "accounting_standard": "HKFRS",
        },
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · HKEX",
        "title": f"香港交易及结算所有限公司 (00388.HK)：{period} 季报仪表盘",
        "subtitle": (
            f"截至 {latest['period_end']} · 发布 {latest['release_date']} · HKFRS · "
            f"{AUDIT_WORDS[latest['audit_status']]} · "
            "自然年财年，季度标注无需换算"),
        # The owner's analysis puts the quarter in one sentence: two records, and
        # an increment that came from a revaluation the company books twice a
        # year. Every part of that sentence is recomputed here, and the second
        # half only prints while the numbers still say it.
        "headline": (
            f"收入及其他收益 {hkd_m(roi[-1])}、股东应占溢利 {hkd_m(profit[-1])}，"
            + (f"{record_words} {len(quarters)} 季新高" if records else f"都不是 {len(quarters)} 季新高")
            + (f"；但溢利环比只多 {hkd_m(profit_delta)}，未上市股权估值收益一项就从 {signed_hkd(eq_prev)} "
               f"变成 {signed_hkd(eq_now)}，四个经营分部的 EBITDA 环比合计 {signed_hkd(ops_delta)}"
               + ("。那笔重估半年一估，大额读数只出现在第二、四季。" if on_clock else "。")
               if eq_now - eq_prev > profit_delta > 0 else f"；溢利环比 {signed_hkd(profit_delta)}。")),
        "brief": (
            f'<h4>本季{cn_count(len(articles))}条主线</h4><div class="takeaway-grid">'
            + "".join(f"<article><span>{tag}</span><b>{head}</b><p>{body}</p></article>"
                      for tag, head, body in articles)
            + '</div>'
        ),
        "source": (
            'Source: <a href="' + release["url"] + '" rel="noopener">'
            + announcement_label(period) + f'（{latest["release_date"]}）</a>与 '
            f'{staging["announcements"][0]["doc"][:4]} 年以来的 {len(staging["announcements"])} 份'
            '季度／中期／全年业绩公告。'
        ),
        "source_url": (
            "https://www.hkexgroup.com/Investor-Relations/"
            "Financial-Results-and-Presentations?sc_lang=en"),
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {"id": "settled", "title": "一、上季跟踪指标兑现了吗",
             "description": (
                 "先结算上一季留下的东西。"
                 + (f"上季分析稿留下的 {len(closure['items'])} 条待验证问题，本季分析稿逐条给了判定。"
                    if closure else "")
                 + (f"上季分析稿第 8 节的 {len(prior['indicators'])} 个量化指标，用本季的一手数据逐条结算："
                    "风险线一张、加仓线一张，有季度序列可画的再各画一张走势。"
                    if prior else "")
                 + "第三类「公司自己的指引兑现了没有」这里没有：港交所不发布任何财务指引 —— "
                 f"{staging['guidance_census']['documents']} 份业绩公告里带数字的前瞻表述共 "
                 f"{staging['guidance_census']['forward_statements_with_a_number']} 处，"
                 "全部是产品上线时点、指数纳入、股息寄发日期与税务措辞，"
                 "没有一处是收入、利润、费用或资本开支的数字，分析师演示材料里也没有。"),
             "exhibits": settled_ex},
            {"id": "quarter_highlights", "title": "二、本季重点",
             "description": (
                 f"{cn_count(len(highlight_ex))}张图，按本季分析稿第 1、7 节的结论排：收入与溢利的读数，"
                 "EBITDA 的环比增量落在哪个分部，存管费的季节性，北向与南向的成交和持仓，"
                 "保证金投资收益的价差，以及资本开支里的总部物业。"
                 "收入那一张的柱子有"
                 f"{cn_fraction(derived_total / len(quarters))}是本页减出来的，来历见第四板块开头。"
                 "分析稿里还有一条结论本页不画：业绩相对市场一致预期与股价的反应 —— 本站不发布券商共识与股价。"),
             "exhibits": highlight_ex},
            {"id": "next_quarter", "title": "三、下季要跟踪什么",
             "description": (
                 (f"本季分析稿第 8 节留下 {len(kpi['indicators'])} 个指标，写成 {len(entries)} 条可量化的阈值，"
                  "开头那张总览看当前值离阈值还有多远（正值 = 仍在安全侧），后面逐条画走势，加仓线一并画出。"
                  f"另有{cn_count(len(kpi.get('not_on_page', [])))}处写不进或写不准本页数字的，列在这里："
                  + "；".join(item["text"].rstrip("。") for item in kpi.get("not_on_page", []))
                  + "。阈值是本地研究设定：港交所不发布任何财务指引。"
                  if kpi else "港交所不发布任何财务指引。")),
             "exhibits": next_ex},
            {"id": "routine", "title": "四、长期常规跟踪",
             "description": (
                 "港交所特有的长期序列。先是这一页每个数字的来历：第一、三季的损益表按季印出，"
                 "第二、四季本页由半年与全年减出来 —— 公司自己也把它们印过，只是要晚得多，"
                 "所以先画「等多久」、再画哪些收入分项至今只有本页的算术、再逐格检验本页的减法。"
                 "然后是利润率、收入构成与开支，投资收益，最后是成交量："
                 "市场统计是每交易日的平均，那道减法用不了，"
                 f"季度成交数据只回到 {staging['kpi_quarters'][0]}，更长的背景用年度口径。"),
             "exhibits": routine_ex},
        ],
        "tables": tables,
        "notes": [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，"
            "每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "港交所为自然年财年（12 月 31 日结束），本页季度标注与公司口径一致，无需换算。"
            "记账货币为港元，本页所有金额单位为百万港元（HK$M），成交额为十亿港元（HK$bn）。",
            "本页最需要说明的一条：公司按季印出的是第一季与第三季的完整损益表；"
            "中期与全年公告只印六个月与十二个月，所以本页 "
            f"{len(quarters)} 个季度里的 {derived_total} 个由「上半年减第一季」与"
            "「全年减前九个月」得到，全部标 D。"
            "但这些季度公司自己也印过：每一份年报里都有一张"
            "「Analysis of Results by Quarter」把四个季度按列印全，FY2016 就有 —— "
            "本页第一稿把这件事写成了「第二、四季度从未被印成损益表」，那是错的，"
            "错在只读了业绩公告这一个文件系列。"
            f"改正后的对照是：{recon['compared']} 次比对里 {recon['derived_compared']} 次"
            f"落在减出来的格子上，{recon['mismatches']} 处不同。"
            "真正没有被任何人印过的是双数季的收入分项："
            "年报那张季度表在 FY2022 才加入六项费用收入，所以 2016–2021 的双数季"
            + (f"（连同{pending_words(staging, recent_gaps, wait=False)}）" if recent_gaps else "")
            + f"共 {len(never_printed(staging, FEE_LINES))} 个季度的收入拆分只有本页的算术。",
            "每一个期间都被公司印过两次：一次在当期公告里作为本期，一次在一年后的同类公告里"
            "作为比较期。本页把两次读数逐格比对，"
            f"{staging['restatement_paired_readings']:,} 对读数里只有 "
            f"{len(staging['restatement_census'])} 处不同，都在 2020 年第三季与前九个月的"
            f"「其他收入」一行：{abs(staging['restatement_census'][0]['again'] - staging['restatement_census'][0]['first']):,.0f} "
            "百万港元从其他收入被重分类到当年新增的「慈善基金捐款收入」一行，"
            "收入及其他收益合计不变。"
            f"说清楚这句话的范围：这是本页逐格比对的那 {staging['restatement_paired_readings']:,} 对读数里唯一的一处，"
            "不是「公司在本窗口内只重分类过一次」—— 比对只覆盖本页跟踪的那些行，"
            "覆盖不到的行有没有动过，本页没有读数，也就不作断言。",
            "季度损益表只印一个「净投资收益」，投资收益毛额与「支付予参与者的利息回赠」"
            f"只出现在中期与全年的损益表上。因此 Exhibit {number['EX_REBATE']} 与 "
            f"Exhibit {number['EX_GROSSNET']} 按半年频率，"
            f"{len(staging['halves'])} 个半年里下半年由全年减上半年得到。"
            "把返还比例读成利率的函数是对的，但要注意它同时也是保证金规模与合约结构的函数。",
            "EBITDA 利润率本页统一用「EBITDA ÷ 收入及其他收益」自算。"
            "公司自己印的那个比率分母是「扣除交易相关支出后的收入及其他收益」，"
            "而那一行 2020 年才出现在损益表上，用它会让 2020 年之前的窗口没有可比口径。"
            + (f"两者的差在 {margin_gap[0]:.1f}–{margin_gap[1]:.1f} 个百分点之间，方向固定（公司口径略高）。"
               if margin_gap else ""),
            "营业开支合计由「收入及其他收益 − EBITDA」倒推，不由明细行相加："
            "明细行的行数在窗口内变过三次（2018 年起信息技术开支独立成行、"
            "2020 年起慈善基金捐款独立成行），而两个端点的定义十年没变。"
            f"Exhibit {number['EX_OPEX']} 里的「其余营业开支」因此是一个残差，不是公司印出的科目。",
            "市场统计（日均成交额、日均张数、计费日均手数）不能用损益表那道减法："
            "它们是每交易日的平均值，六个月的平均减三个月的平均不是第二季，"
            "而正确的还原需要各期的交易日数，公司不在公告里印它。"
            # 「公司自 2021Q1 起按季印出」: the company began printing them in
            # 2022, with one prior-year column that reaches back to 2021Q1 (the
            # volume section's first chart says so).
            "公司自 2022 年起在公告正文按季印出这些平均值，并带一个上年比较列，"
            f"最早的离散季度因此是 {staging['kpi_quarters'][0]}，第四板块的季度成交图从那里开始，"
            "更早的部分本页留空而不是补出来。",
            "市场统计不从 PDF 的文本层读取。公司用上标标注「新的季度／半年度纪录」，"
            "而纯文本导出会把上标并进数字本身：日均成交额 283.0 变成 283.04、"
            "衍生品日均 849 变成 8494。"
            f"逐格对照后，{staging['text_layer']['figures_compared']} 个市场统计数字里有 "
            f"{staging['text_layer']['corrupted_by_glued_marker']} 个会被这样读错，"
            "而读错之后全部是合法的、看不出问题的数。本页按字形磅值筛选"
            "（正文 10pt、上标 6.5pt）后再解析。",
            "LME 那一行在 2019 年发生过一次同时换单位又换定义的变化："
            "2018 年及以前印的是绝对手数的「日均成交量」，2019 年起印的是千手的"
            "「计费日均手数」（剔除管理性交易）。两代不是同一个数换了单位，"
            "因此本页不把它们接成一条线，第四板块只画公司按季印出的那一段。",
            "互联互通两条线的货币不同：北向以人民币计价、南向以港元计价，"
            "公司在同一张表里并排印出，本页照原样画，不做换算 —— "
            "换算需要选一个汇率口径而公司没有给。南向成交计入现货市场日均成交额，北向不计入。",
            "本页不发布评级、目标价、估值与任何券商共识。"
            + (f"Exhibit {number['EX_PRIOR_RISK']} 与 Exhibit {number['EX_NEXT']} 的阈值取自本地季报分析稿第 8 节"
               "（上季稿与本季稿各一份），不是公司指引；「距阈值余量」统一为正值代表安全侧。本页没有可以兑现的公司指引："
               if "EX_PRIOR_RISK" in number and "EX_NEXT" in number else "本页没有可以兑现的公司指引：")
            + f"{staging['guidance_census']['documents']} 份公告里带数字的前瞻表述 "
            f"{staging['guidance_census']['forward_statements_with_a_number']} 处，"
            "没有一处是收入、利润、费用或资本开支的数字指引，分析师演示材料里也没有。",
            "本页跨页对照表与其他公司页逐字相同，港交所本身不在那张表的任何一列里 —— "
            "带着这张表和成为表里的一列是两件事。",
        ],
        "footer": "Quarterly Results · 公司披露值与透明自算 · 仅供研究",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "hkex.js"), payload, "hkex")
    shell_dir = ROOT / "hkex"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("00388.HK", "hkex"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"HKEX page: {charts} charts in {len(payload['sections'])} sections "
          f"+ {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
