"""How far back each page's time axes actually reach, pinned as a ratchet.

The owner's decision on 2026-08-30 was that every chart with a time axis runs
from 2016Q1, and that conclusions which do not survive the longer window are
exactly the ones worth correcting. That is a multi-page migration, so this file
is not a completeness gate -- it is a **ratchet**. Two things have to be true of
it at every point in the migration, and they pull in opposite directions:

* a page that has been converted must not slide back, and
* a page that has not been converted yet must not turn the suite red.

So each slug carries a pinned floor: the number of its time-axis exhibits that
reach 2016Q1 or earlier. Dropping below the floor fails. Rising above it *also*
fails, with a message naming the new number -- which is the whole point. The
count lands in the commit that earned it, and nobody can quietly move a page
backwards to make a different change easier.

Why not just assert "everything reaches 2016" and skip the rest? Because that
assertion is red on 29 of 31 pages today, and a gate that is red for a week is a
gate somebody turns off. The strict form does exist here, but it applies only to
slugs listed in ``CONVERTED`` -- and for those the escape hatch is per-exhibit
and has to carry a reason, so a chart cannot be left short by adding a line to a
list.

What this file deliberately does not check: whether the *labels* on a 42-point
axis collide. That needs text metrics, which means a real browser -- jsdom
returns zero for `getComputedTextLength`, and a rotated label's
`getBoundingClientRect` is the rotated box, which lies. See
`assets/charts.js`'s `xlCapAxis` for the renderer's own model and the TSM
commit message for how it was measured.
"""

from __future__ import annotations

import collections
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.all import ENTRIES  # noqa: E402
from tests.test_chart_contract import exhibits  # noqa: E402

TARGET_YEAR = 2016

# One pattern per label shape the site actually publishes.
#
# The load-bearing detail is the **anchor after the year group**, not the order
# inside the alternation -- that distinction was measured, not assumed, and the
# first draft of this file had it backwards. With `\b` or `$` behind the group,
# `(\d{2}|\d{4})` still yields 2017 for "FY2017": the two-digit branch matches
# "20", the anchor then fails against the "1" that follows, and the engine
# backtracks into the four-digit branch. Drop the anchor and the same pattern
# returns 20 -- which becomes the year 2020, a decade late, silently, and in the
# direction that makes an unconverted page look converted.
_PERIOD = [
    (re.compile(r"^Q([1-4])[ '](\d{4}|\d{2})\b"), 2),      # Q1'16 / Q1 2016
    (re.compile(r"^([1-4])Q ?(\d{4}|\d{2})\b"), 2),        # 1Q 2016
    (re.compile(r"^(\d{4}|\d{2})Q([1-4])$"), 1),           # 2016Q1 / 16Q1
    (re.compile(r"^FY ?(\d{4}|\d{2})\b"), 1),              # FY2016 / FY16 初
    (re.compile(r"^(?:1H|2H|H1|H2) ?(\d{4}|\d{2})$"), 1),  # H1 2016
    (re.compile(r"^(\d{4})H[12]$"), 1),                    # 2016H1
    (re.compile(r"^(\d{4})-\d{2}(-\d{2})?$"), 1),          # 2016-03 / 2016-03-31
    (re.compile(r"^[A-Z][a-z]{2}[- ](\d{4}|\d{2})$"), 1),  # Mar-16
    (re.compile(r"^(?:19|20)\d{2}$"), 0),                  # 2016
]


# A period token may be followed by a qualifier that still names a period -- a
# fiscal year's quarter ("FY19 Q2"), the opening vintage of a year's guidance
# ("FY23 初", "FY2019 initial"), a restated basis ("Q1 2026 原披露"), a footnote
# marker. It may NOT be followed by a metric or an event: "Q1 2026 non-GAAP EPS"
# and "Q2 2026 call" sit on axes that list metrics and earnings calls, and
# counting those as time axes would put pages under an obligation to extend a
# chart whose x axis is not time at all. The list is a whitelist on purpose --
# an unknown suffix is treated as "not a period", which can only ever leave a
# chart out of the ratchet, never invent one.
_QUALIFIER = re.compile(r"^(?:[Qq][1-4]|初|initial|基数|本季|原披露|重述后|→\s*FY\s*\d{2,4})[*†]?$")


def label_year(label: object) -> int | None:
    """The calendar year a chart label names, or None if it names no period."""
    if not isinstance(label, str) or not label.strip():
        return None
    text = label.strip()
    for pattern, group in _PERIOD:
        match = pattern.match(text)
        if not match:
            continue
        rest = text[match.end():].strip()
        if rest and not _QUALIFIER.match(rest):
            return None
        year = int(match.group(0) if group == 0 else match.group(group))
        if year < 100:
            year += 2000 if year < 80 else 1900
        return year if 1990 <= year <= 2030 else None
    return None


def first_year(exhibit: dict) -> int | None:
    """The earliest year on this exhibit's x axis, or None if the axis is not time.

    "Not time" is the common case and must not be guessed at: a KPI headroom bar
    lists metric names, a bridge lists its own legs, and a guidance-revision
    chart lists the calls that revised it. The test is whether the labels that
    carry text mostly parse as periods -- sparse axes label every fourth tick
    and leave the rest empty, so blanks are excluded from the denominator.
    """
    labels = exhibit.get("xlabels") or []
    years = [label_year(label) for label in labels]
    parsed = [year for year in years if year is not None]
    lettered = sum(1 for label in labels if isinstance(label, str) and label.strip())
    if len(parsed) < 2 or len(parsed) / max(1, lettered) < 0.6:
        return None
    return min(parsed)


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    return json.loads(text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0])


# ── the ratchet ──────────────────────────────────────────────────────────────
# Time-axis exhibits per page whose earliest label is 2016 or earlier. Raise a
# number when you convert a page; the assertion below refuses to let it drift in
# either direction, so the count is always the one the last commit measured.
REACH_2016 = {
    "amzn": 13, "avgo": 6, "axp": 11, "bc": 1, "cboe": 10, "cdns": 10, "cme": 14,
    "cost": 13, "googl": 11, "hkex": 13, "ibkr": 21, "ma": 16, "mc": 3, "mco": 7, "meta": 10,
    "msci": 15, "msft": 8, "mu": 7, "ndaq": 9, "nke": 8, "nvda": 10, "pm": 6,
    "race": 9, "rms": 0, "samsung": 0, "schw": 10, "skhynix": 3, "snps": 8,
    "spgi": 11, "tjx": 8, "tsm": 18, "v": 14,
}

# Pages whose migration is finished. For these the strict rule applies: every
# time-axis exhibit reaches 2016 unless it is named below with the disclosure
# that stops it. An entry that no longer matches a short exhibit fails too --
# otherwise the list would slowly fill with excuses for charts that were fixed.
CONVERTED = {
    "v": {
        # Visa adopted ASC 606 with the fiscal 2019 first quarter and published
        # its first disaggregation-of-revenue note in the 10-Q filed
        # 2019-01-31. The twelve quarterly filings from 2016-01-28 through
        # 2018-07-27 carry a geographic breakdown of long-lived *assets* and
        # nothing else -- there is no US / international split of revenue to
        # read, in any of them, on any basis. So this one exhibit floors at the
        # disclosure, not at the window.
        "美国以外贡献净收入": "revenue by geography begins with Visa's first ASC 606 "
                       "disaggregation note (10-Q filed 2019-01-31); the earlier "
                       "10-Qs disaggregate long-lived assets, not revenue.",
    },
    "googl": {
        # Two floors, both disclosure floors, both stated on the charts they
        # govern. Alphabet published no breakdown of revenue into Search /
        # YouTube / Network / subscriptions / Cloud before the 2018Q4 release,
        # and no remaining-performance-obligation figure before the FY2019 10-K.
        "Cloud 收入 YoY": "revenue by line begins with the 2018Q4 release.",
        "Cloud 经营利润率": "same line floor; the margin's own numerator is later still "
                      "(2022Q1), which the chart says on itself.",
        "Search & other YoY": "revenue by line begins with the 2018Q4 release.",
        "Cloud backlog 环比": "remaining performance obligations first appear in the "
                         "FY2019 10-K.",
        "Cloud backlog 单季净增": "same RPO floor.",
        "backlog 创": "same RPO floor; this is the level-and-net-add view of it.",
        "Cloud 增速本季": "revenue by line begins with the 2018Q4 release.",
        "Search 增速本季": "revenue by line begins with the 2018Q4 release.",
    },
    "msft": {
        # Four floors, all of them disclosure floors.
        "Azure 固定汇率增速": "Microsoft publishes an Azure growth rate and no Azure "
                        "revenue, so there is no filed series to lengthen.",
        "Intelligent Cloud 分部毛利率": "the segment's cost of revenue -- the denominator "
                                 "-- is only in the reviewed eight quarters.",
        "Intelligent Cloud 本季首次超过": "segment revenue in this file covers the reviewed "
                                  "eight quarters only.",
        "商业剩余履约义务": 'date corrected, and the excuse was measuring the wrong thing: Microsoft has disclosed the dollar split between total and commercial remaining performance obligations in every 10-Q/10-K since the quarter ended 2020-03-31 -- 21 quarters earlier than "five quarters ago". What genuinely started recently is a *percentage* metric, which is not what this chart plots (it plots the balance). Real floor 2020Q1; the metric did not exist before that.',
        "FY2026 股东回报": "an annual ratio built from the 10-K, two fiscal years wide.",
        "季度折旧": "quarterly depreciation only reaches 2024Q3 -- before that Microsoft "
                "disclosed it annually and the page will not spread a year over four "
                "quarters.",
    },
    "amzn": {
        # Two floors: the guidance record and the segment tables. Both are the
        # earliest quarter the disclosure exists in, not the earliest fetched.
        "净销售额": "the quarterly outlook record in this file starts with the 2017Q3 "
                "release.",
        "经营利润相对指引中值": 'not a floor at all -- checked against the filings: Amazon has guided operating income as a RANGE in every quarterly release since at least 2011. The Q1 2016 release guiding Q2 2016 reads "Operating income is expected to be between $375 million and $975 million" (0001018724-16-000225). This is a fetch gap; the backfill is in flight.',
        "TTM 自由现金流": "Amazon's own trailing free-cash-flow figure, as the company "
                     "prints it, from the 2019Q1 release on.",
        "三个分部的经营利润率": "the North America and International segment tables begin "
                        "2019Q1; only AWS reaches 2016.",
        "北美分部经营利润率": "same segment floor.",
        "广告同比": 'verified against the filings and correct: the seven-line revenue disaggregation\'s earliest available quarter is 2020Q3, published retroactively alongside five newer quarters in the 2021Q4 release. Advertising sat inside "Other" before that.',
        "AWS backlog 单季净增": "checked: Amazon has disclosed AWS-related unrecognized customer-contract commitments (original term over one year) in the commitments note of every 10-Q/10-K since the quarter ended 2018-03-31 -- about 30 quarters, not four. 2016-2017 is genuinely absent, so this chart's honest floor is 2018Q1 rather than 2016Q1. Fetch gap for everything after that.",
        "单季现金 CapEx（净额": "the net measure needs proceeds from sales and incentives, "
                          "which this file carries for twelve quarters.",
        "总收入同比": "a year-on-year line has no base for 2016Q1-Q4; the record starts "
                  "2017Q1.",
        "资本强度": "quarterly *gross* capital expenditure does not exist for 2016 -- "
                "Amazon's 2016 cash-flow statements print one net line and only "
                "from 2017 split gross from proceeds. The four 2016 cells this "
                "chart used to draw were the net measure under a gross heading, "
                "so the chart now starts where its own basis does.",
    },
    # Checked by reading American Express's FY2017 quarters as originally filed
    # (8-K 0000004962-18-000012) against the same quarters "As Recast"
    # (0000004962-18-000056). ASC 606 was a gross-up: discount revenue +19.2% to
    # +19.4%, marketing +75% to +84%, total expenses +14.4% to +14.9% -- and the
    # two sides nearly cancel, leaving the bottom line within 1.4%. So a chart's
    # floor here depends on which side of that its inputs sit on, and each entry
    # below says which.
    "axp": {
        "税前利润同比增量拆成两条腿": "needs a year-over-year pair, so it starts one quarter "
                        "short of a year after its inputs. Applied: both legs "
                        "now carry 2016 on one basis, so the chart runs from "
                        "2017Q1 rather than 2018Q1. It cannot reach 2016 itself "
                        "-- a year-over-year chart never can, on any data.",
        "消费额同比": "billed business carries 2016Q3-Q4 and not 2016Q1-Q2, and a "
                 "year-over-year chart needs four quarters of run-up, so the "
                 "chart runs from 2017Q3. The open half of this entry has now "
                 "been checked, and it is a disclosure floor rather than a "
                 "coverage one: the figure here is the PROPRIETARY (ex-Global "
                 "Network Services) total, which American Express first printed "
                 "as its own consolidated dollar line in the Q3 2017 release, "
                 "whose trailing window reaches back five quarters to 2016Q3 "
                 "and stops. Before that the split existed only inside the "
                 "segment tables, so 2016Q1-Q2 are obtainable only as a "
                 "subtraction the company never performed. Its plain worldwide "
                 "billed business WAS printed for those two quarters ($253.8bn "
                 "and $269.3bn) -- filling them with that would silently mix two "
                 "definitions in one line.",
        "jaws（收入增速 − 费用增速）": "the difference of two year-over-year growth rates. Both "
                            "sides used to stop at the recast boundary, which "
                            "put the floor at 2018Q1; both now carry 2016 on the "
                            "recast basis, so it starts 2017Q1. Like every "
                            "year-over-year chart it cannot itself reach 2016.",
        "四个分部的税前利润率": "nothing to do with ASC 606: American Express restated its "
                      "reportable segments in 2020, and the four-segment pretax "
                      "margin has no earlier counterpart.",
        "VCE 占收入比": "business development did not exist as a separate disclosed line "
                   "until 2021 -- before that it sat inside Marketing, so the "
                   "value-creating-expense ratio cannot be assembled.",
        "全年摊薄 EPS相对指引中值的偏离": "the annual guidance record, whose own floor this "
                             "follows.",
        "全年收入增速相对指引中值的偏离": "same annual guidance record.",
        "收入增速：对年初那一档": "same annual guidance record, read at two vintages.",
    },
    "cboe": {
        "最想结清的那条指引": "organic net revenue growth was guided as a number only for "
                       "2022-2024; from 2025 the guidance is a phrase, and the page "
                       "does not convert phrases into endpoints.",
        "其中最关键的一条": "Cboe first printed a separate multi-listed options market "
                     "share in the 2019Q2 release; ADV and RPC -- and so the money "
                     "line beside it -- do run the whole window.",
        "同一形状在股票撮合里重演": 'verified: Cboe acquired BIDS Trading on 2020-12-31, so the off-exchange block (share, ADV, net capture) genuinely begins 2021Q1.',
        "五个分部的净收入": 'was wrong and is now fixed in the builder: the five-segment series runs unbroken to 2017Q2 and is already in this repo -- the chart was drawing the last 20 of 37 because of a hardcoded tail, not because of anything in the filings. It now draws all 37. 2017Q2 is the real floor (Bats consolidated 2017-02-28, so 2017Q1 carries one month of the combined company).',
        "毛收入与净收入之间那道楔子": 'verified: a genuine Bats-driven structural break -- the pre-2017 income statement had no net-revenue/liquidity-payment structure to build the wedge from.',
        "公司自己的第二套口径": 'date corrected: Cboe introduced this three-category view in its Q1 2022 release (filed 2022-04-29), not 2021Q1. The four 2021 quarters exist only as retroactive comparatives inside the 2022 releases, which is why 2021Q1 is the practical floor -- but the reason is the recast, not an original disclosure.',
    },
    # Micron's two records give opposite answers, both read off the filings.
    "mu": {
        "收入相对指引中值的偏离": "a genuine disclosure floor, and an unusually clean one: "
                        "Micron's filed releases contain no forward guidance of "
                        "any kind -- not even qualitative -- from FQ2-16 through "
                        "FQ1-19, and the FQ2-19/FQ3-19/FQ4-19 releases say "
                        "outright that guidance will be given on the call, which "
                        "never enters a filing. The first printed Business "
                        "Outlook table is in the FQ4-19 release of 2019-09-26, "
                        "and every number in it matches this record's first row.",
        "non-GAAP 毛利率": "same guidance record, same floor.",
        "non-GAAP 每股收益": "same guidance record; drawn on a shorter window still "
                        "because the per-share guide came later than the revenue "
                        "and margin guides.",
        "收入（本图仅近 12 季）": "same guidance record, deliberately windowed -- the full "
                          "record is the deviation chart beside it.",
        "把「超出自身指引」拆成三条腿": "the decomposition of the same guided record.",
        "一年之间收入": "cost of goods sold is not continuous: Micron's releases printed "
                  "it through FQ3-17 and again from FQ4-21, with a "
                  "seventeen-quarter hole between. A chart of revenue against "
                  "COGS can only live where both exist.",
        "存货 US$8.6B": "inventory days shares that same COGS hole -- days on hand is "
                    "inventory over cost of goods sold.",
        "四个业务单元的收入": "Micron reorganised its reportable business units into the "
                     "current data-centre-centric four (CMBU/CDBU/MCBU/AEBU) in "
                     "2024; the earlier CNBU/MBU/SBU/EBU structure is a different "
                     "cut of the same revenue, not an earlier part of this one.",
        "业务单元毛利率": "same 2024 business-unit reorganisation.",
        "按技术拆收入": "the DRAM/NAND split has no quarters list of its own and aligns to "
                  "the top-level axis by position; it carries real values only "
                  "from FQ4-21. The earlier quarters are a fetch gap, not an "
                  "absence -- Micron does print the split in older releases.",
    },
    "ndaq": {
        "全年非 GAAP 有效税率": 'verified, with the wording tightened: Nasdaq guided a non-GAAP tax rate for FY2018 in its January 2018 release but never disclosed an FY2018 actual, so FY2019 is the first year carrying both a guided range and a reported result.',
        "FY2026 费用指引的三次发布": "three guidance vintages for one fiscal year -- the axis "
                            "is release dates, not quarters.",
        "Market Services 毛收入的去向": "the 2022 reorganisation moved Trade Management "
                                "Services out of Market Services, so the denominator "
                                "changed; 2022Q3 reads 305 on the old basis and 245 "
                                "on the new one.",
        "三个分部的净收入": "same 2022Q4 segment floor.",
        "Financial Technology 的三条子线": "same segment floor; one sub-line begins later "
                                  "still and is left empty rather than filled.",
        "Index：挂钩纳斯达克指数的 ETP AUM": "the Index revenue line was re-drawn in the 2018Q2 "
                                   "Information Services split; the 43-quarter AUM "
                                   "series is published on its own chart.",
        "ARR 两条腿": 'date corrected: Nasdaq introduced the Financial Technology / Capital Access Platforms ARR split in its Q1 2024 release (filed 2024-04-25), not 2023Q1. The 2023 quarters are recoverable only from the four YoY comparatives inside the 2024 releases, so 2023Q1 stands as the practical floor -- but as a recast, not as an original disclosure.',
    },
    # All five checked against the filing immediately before each start; every
    # one is a real disclosure floor, and four of the five share a single cause:
    # Costco's supplemental EX-99.2 deck did not exist before 2024-05-30, and
    # the pre-deck filings never quantify these metrics at all.
    'cost': {
        '会员续费率': "precision floor, not an availability one: the renewal rate is "
                  "printed as a whole percent through the 10-Q for FY2023 Q1 "
                  "(period 2022-11-20, \"93%/90%\") and to one decimal from FY2023 "
                  "Q2 (period 2023-02-12, \"92.6%/90.5%\"). Splicing the two would "
                  "put a step of up to half a point into a series whose whole "
                  "point is half-point moves.",
        '每股收益增速拆成四条腿': "a clean year-over-year pair needs both quarters free of "
                       "the noncontrolling-interest line (the Taiwan joint "
                       "venture), which was not fully gone until FY2023 -- so "
                       "the first true pair is FY2024 Q1 against FY2023 Q1.",
        '客流与客单': "two floors stacked: the supplemental deck that carries traffic and "
                 "average ticket begins 2024-05-30, and the gasoline-and-FX-adjusted "
                 "ticket sub-table inside it begins later still, 2025-03-06.",
        '公司自己估的财年末仓库数': "same supplemental deck, first published 2024-05-30. "
                          "Earlier filings give the warehouse count but never the "
                          "company's own forward estimate of the year-end figure.",
        'Executive 会员': "same supplemental deck. Filings before it never quantify the "
                       "Executive member count or its penetration -- the earlier "
                       "language is qualitative only.",
        '四条商品线对净销售额增速的贡献': "same supplemental EX-99.2 deck (first "
                            "published 2024-05-30): the four-merchandise-line "
                            "contribution to sales growth is not quantified in any "
                            "earlier filing.",
        '毛利率 11.04%': "the eight-quarter margin panel is a current-quarter view by "
                    "design; the long gross-margin series it summarises is the "
                    "core-merchandise chart above, which now runs 42 quarters.",
        '三个地区分部的营业利润率': "segment operating margin by geography comes from the same "
                        "2024-05-30 deck; the 10-K gives segment operating income "
                        "annually, not by quarter.",
    },
    "mco": {
        # All five are the same record: Moody's began publishing a full-year
        # adjusted-EPS range with the FY2019 outlook. The axis is fiscal years,
        # not quarters, and there is nothing earlier to score.
        "调整后摊薄 EPS（对末次指引）": "not fetched yet, not absent: Moody's 2018-02-09 release "
                          "guides FY2018 diluted EPS at $7.20-$7.40 and adjusted "
                          "diluted EPS at $7.65-$7.85. This file's record starts "
                          "FY2019 because that is where the extraction started.",
        "调整后摊薄 EPS（对初始指引）": "same record, read at its first vintage.",
        "调整后摊薄 EPS（2 月那版）": "the deviation view of the February vintage.",
        "调整后摊薄 EPS（10 月那版）": "the deviation view of the October vintage.",
        "每一年的指引中值怎么被改到实际值上": "the same record again, as a revision path.",
    },
    "ma": {
        # One floor, five charts. Mastercard's revenue disaggregation -- the four
        # assessment lines and the payment-network / value-added-services split
        # -- exists only from 2022Q1. No 10-Q from 2018Q1 to 2023Q3 and no 10-K
        # from FY2018 to FY2025 carries those lines in its revenue note; no
        # release from 2016 to 2022 disaggregates revenue at all; and 2016-2017
        # has no revenue note, because ASC 606 was adopted modified-retrospective
        # on 2018-01-01 and the earlier years were never restated. Everything
        # else on this page -- income statement, balance sheet, cash flow, and
        # the three key drivers -- does run from 2016Q1.
        "净收入的同比增量拆成三条腿": "the rebate leg needs gross billings, which is the sum "
                          "of the four assessment lines.",
        "毛计费的同比增量": "same disaggregation floor.",
        "返点占毛计费从": "same disaggregation floor.",
        "返点占比的同比变化": "same disaggregation floor, one more year in for the "
                      "year-on-year run-up.",
        "四条计费线": "the four assessment lines themselves.",
    },
    "msci": {
        # The annual guidance exemptions that used to sit here are gone: the
        # record was never short, it was unfetched. It runs from FY2015 -- five
        # years earlier than this file claimed -- and the release before it
        # (2014-02-06) carries no quantified forward range at all, which is the
        # actual floor. The three quarter charts below are a different, real
        # limit: they need the revenue split by type and by segment, which this
        # file carries for the reviewed eight quarters only; the run-rate, AUM
        # and margin series beside them do run from 2016Q1.
        "三条收入腿": "revenue split into recurring subscription, asset-based fees and "
                 "non-recurring is carried here for the reviewed eight quarters.",
        "四个分部": "the four-segment revenue split is carried for the reviewed eight.",
        "分部调整后 EBITDA 利润率": "same segment window.",
    },
    "schw": {
        # Four floors, each named on the chart it governs.
        "NIM（环比是否恢复增长）": "net interest margin has three interior holes in the "
                          "repo's own 2020-2021 stretch, so the longest complete "
                          "tail this chart can draw starts after them.",
        "NIM：": "same three holes.",
        "调整后 Tier 1 杠杆率": "the adjusted (AOCI-inclusive) leverage ratio is a "
                        "company-defined measure Schwab began giving in 2024; the "
                        "2016-2019 filings carry only the GAAP Tier 1 ratio, which "
                        "is a different number.",
        "五条收入线": "bank deposit account fees arrived with TD Ameritrade "
                 "(closed 2020-10-06), so the five lines only coexist from 2020Q4.",
        "季度净新增资产按渠道": "2020Q4's net new assets include the TD Ameritrade client "
                       "base arriving at once (US$1,690.7B), which is an "
                       "acquisition rather than asset gathering.",
        "经营杠杆": "a twenty-quarter view by design; the underlying revenue and "
                "expense lines do run the whole record.",
    },
    # Verified against the filings, including the repo's own prior claim about
    # the operating-income line, which turned out to be true.
    "skhynix": {
        "DRAM 平均售价的环比": "the four bucket-word series (DRAM/NAND bit shipment and ASP, quarter on quarter) come from one table that covers 1Q2023-1Q2026 and nothing earlier. Checked rather than assumed, and the first version of this reason was wrong: the table is NOT unique to the 424B4 of 2026-07-10. It appears verbatim in six SEC filings -- the DRS/A of 2026-05-29, two later DRS/A, the F-1, both F-1/A, and the 424B4 -- and every one of them carries the identical thirteen quarters. The earlier DRS (2026-03-24) and the 2026-05-08 DRS/A do not carry it at all. So the limit is not which document you read, it is that no document holds an earlier instance. The vocabulary itself does predate 2023 in SK hynix's earnings calls, but spoken guidance is a different disclosure from this four-series table, not an earlier printing of it. Splicing the pre-2021 practice on is worse: back then the ordinary releases gave EXACT numeric percentages, which is a finer and different regime, with a gap through 2021-2022 where neither appears. That gap was censused rather than assumed: the English releases give all four numeric series through 4Q2020, drop ASP but keep bit shipment at 1Q2021, then say nothing at all for eight straight quarters, 2Q2021 through 1Q2023. One thing this floor could still move on, and has not: the Korean DART quarterly filings carry the same bucket wording in their 가격변동추이 section from 1Q2022, four quarters earlier than the 424B4 table, so the honest floor is 1Q2022 rather than 1Q2023 -- at the cost of a Korean-to-English vocabulary mapping this page does not have. Before 1Q2022 that section is qualitative with no numbers at all, back through FY2015, so it does not reach 2016 either way.",
        "NAND 平均售价的环比": "same table, same thirteen quarters, same reason as "
                        "the DRAM band above.",
        "DRAM 的量与价": "both legs are read out of the same thirteen-quarter table, "
                   "so the pair cannot start earlier than either leg.",
        "NAND 的量与价": "same table, same thirteen quarters.",
    },
    "snps": {
        "把「超出自身指引」拆成两条腿": "the expense leg is revenue minus non-GAAP operating "
                            "income, and Synopsys's reconciliation carried no "
                            "operating-income line before the release of "
                            "2019-02-20 -- it bridged GAAP net income straight to "
                            "non-GAAP net income. Eleven reported quarters "
                            "therefore have no leg split at all.",
        "未来 12 个月可确认 backlog": "backlog reaches 2018Q4 and no further: before ASC 606 "
                            "Synopsys disclosed backlog only annually and on a "
                            "different definition (FY2016 $3.5B, FY2017 $3.7B, "
                            "FY2018 $4.0B, with no FSA split). That is a "
                            "different series, not an earlier part of this one.",
        "FSA 占 backlog": "same backlog note -- the FSA split does not exist at all in "
                       "the pre-ASC 606 annual disclosure.",
        "backlog 自": "same backlog note.",
        "收入 US$2,477M": "the current-quarter panel; the long revenue record is in this "
                      "page's own long section.",
        "Design IP 连续三季": "the two-segment split dates from the fiscal 2019 "
                        "reorganisation and the current Design Automation / "
                        "Design IP naming from later still.",
        "两个分部的调整后营业利润率": "same two-segment structure.",
        "GAAP 与 non-GAAP 营业利润之间隔着": "current-quarter bridge, eight quarters by design.",
        "八季里收入指数化到": "an explicitly eight-quarter index, stated in its own title.",
        "FY2026 收入指引四次上调": "one fiscal year's four guidance vintages -- the axis is "
                          "vintages, not time.",
        "non-GAAP 营业利润率：下季阈值": "next-quarter threshold chart, recent by design.",
        "Design IP 收入同比：下季阈值": "next-quarter threshold chart, recent by design.",
        "摊薄股数：下季阈值": "next-quarter threshold chart, recent by design.",
        "中国占比": "the geographic disaggregation reaches 2022Q4. Earlier quarters exist "
               "only on the pre-divestiture basis that still included Software "
               "Integrity, which is not comparable with the continuing-operations "
               "series this chart draws.",
    },
    # Three different answers on one page, each read off the filings.
    "spgi": {
        "五个分部各自占分部收入合计的比重": "a real structural floor. 2016's first three quarters "
                            "use FOUR segments, one of which (\"C&C\") bundles "
                            "Platts with J.D. Power and others; Q4 2016 collapses "
                            "that to three; Platts becomes its own segment only "
                            "on 2018-01-01. No filing in 2016-2017 prints a "
                            "standalone Platts figure -- the MD&A narrates "
                            "\"growth driven by Platts\" without a number. "
                            "Filling only Ratings and Indices would break this "
                            "block's own identity and print \"cannot be "
                            "decomposed\" as \"zero\".",
        "六条申报收入类型各自占毛收入的比重": "the five-category company-wide table first appears "
                            "in the Q1 2018 10-Q, alongside the ASC 606 adoption "
                            "of 2018-01-01; before that the company disclosed "
                            "only a two-way subscription/non-subscription split.",
        "订阅型收入占毛收入比重": "same revenue-type table, same 2018Q1 floor.",
        "计费发行量": "the dollar, rating-category metric first appears in the Q1 2024 "
                 "10-Q (carrying a 2023 comparative) and appears in no earnings "
                 "8-K at all. What the pre-2023 MD&A prints instead is a "
                 "different series -- \"Market Issuance Volumes\", year-over-year "
                 "percentages by geography, sourced from SDC Platinum -- with no "
                 "dollar overlap to splice to.",
        "GAAP 摊薄 EPS相对指引中值的偏离": "follows the GAAP guidance record, which starts FY2017: "
                             "for FY2016 the company gave adjusted-EPS guidance "
                             "and explicitly declined to reconcile it to GAAP "
                             "\"without unreasonable effort\".",
        "GAAP 收入增速相对指引中值的偏离": "revenue-growth guidance began later than the EPS "
                            "guidance on the same table; this follows its own "
                            "metric's floor.",
        "调整后自由现金流相对指引中值的偏离": "adjusted free cash flow was not guided before "
                             "FY2023.",
        "Ratings 的两条腿": "a deliberately recent view; the same two legs run the full 42 "
                       "quarters in the long-record section of this page.",
        "交易性收入占 Ratings 比重": "same pair, drawn recent by design.",
        "Ratings 交易性收入同比": "a next-quarter threshold chart, drawn on recent context by "
                          "design.",
        "营业利润率（剔除处置损益与联营收益 D）vs 阈值": "same, a threshold chart by design; the full "
                                        "42-quarter version is in the long-record "
                                        "section.",
        "本季自由现金流": "threshold chart, recent by design.",
        "单季自由现金流 D vs 阈值": "threshold chart, recent by design.",
        "单季股东回报 / 自由现金流 D vs 阈值": "threshold chart, recent by design.",
    },
    "tjx": {
        # Two floors. The quarterly guidance record on EDGAR starts with the
        # FY2023 releases -- before that TJX gave its next-quarter pretax-margin
        # and comp guidance in the CFO's prepared remarks on the call, which is
        # not a filed document and this site does not read. The four ten-year
        # charts run on fiscal years, not quarters, and ten years of them is the
        # whole of `long_history`.
        "摊薄每股收益（近 16 季）": "not fetched yet, not absent: TJX's 2019-05-21 EX-99.1 gives "
                          "a second-quarter EPS outlook and the comp-sales growth it "
                          "rests on, in the filed exhibit. FY2023 is where the "
                          "extraction started, not where the disclosure does.",
        "税前利润率：": "same record. The earlier claim that pre-FY2023 quarters guided "
                 "this only on the call is withdrawn -- the FY2020 exhibits carry a "
                 "next-quarter outlook.",
        "税前利润率相对指引中值": "the deviation view of the same record.",
        "合并同店销售：": "same guidance record.",
        "合并同店销售相对指引中值": "the deviation view of the same record.",
        "十年税前利润率与资本强度": "an annual chart -- ten fiscal years, not quarters.",
        "十年门店数与总面积": "annual.",
        "十年回购与股数": "annual.",
        "十年经营现金流、资本开支与股东回报": "annual.",
    },
    "cdns": {
        # Three families. The guidance *bands* are drawn on the recent twenty by
        # design, and the chart says so on itself: revenue went from US$0.45B to
        # US$1.58B over this record while the guided band stayed a few million
        # wide, so on a linear dollar axis the early bands are one or two pixels.
        # The full 43-quarter record is on the deviation chart beside each one,
        # in a unit that does not depend on magnitude.
        "收入（本图仅近 20 季）": "the band is drawn on the recent twenty because a "
                          "US$5M band on a US$450M quarter and the same band on a "
                          "US$1,580M quarter are the same proportion and a very "
                          "different number of pixels; all 43 quarters are on the "
                          "deviation chart.",
        "非 GAAP 营业利润率（本图仅近 20 季）": "same reason, same pairing.",
        "非 GAAP EPS（本图仅近 20 季）": "same reason, same pairing.",
        # Then the disclosure floors.
        "季末 backlog": "Cadence's backlog definition rests on ASC 606 remaining "
                    "performance obligations, which do not exist before 2018Q1; "
                    "the 2017 year-end figure is annual and has no quarterly "
                    "series behind it.",
        "backlog 创纪录": "same RPO floor.",
        "backlog / 过去四季收入": "same RPO floor.",
        "中国收入 $": "the 2016-2017 geographic disclosure is Americas / Asia / EMEA / "
                 "Japan with the United States singled out; China is not broken "
                 "out at all, so this file carries Asia-ex-Japan instead.",
        "中国收入占比": "same geographic floor.",
        # And the metrics this file carries for the reviewed window only.
        "单季经营现金流": "quarterly cash flow is carried for the reviewed window.",
        "经营现金流 $635M": "same.",
        "单季回购金额": "same.",
        "单季回购 $200M": "same.",
        "三条产品线的分化": 'not a floor: Cadence\'s "Revenue Mix by Product Group" table is unchanged in structure back to 2016Q1 -- the same categories this chart plots. The claim that the 2016-2017 releases grouped products differently does not survive reading them. Fetch gap; backfill in flight.',
        "GAAP 毛利率降到": "gross margin is carried for the reviewed window.",
        "本季非 GAAP 营业利润率": "this chart pairs the quarterly series with two guided "
                          "points, so it runs on the reviewed window plus two.",
        "单季非 GAAP 营业利润率": "the threshold view of the same quarterly margin series, "
                          "which this file carries for the reviewed window.",
    },
    "nke": {
        # Nike's segment revenue and EBIT reach 2016; the currency-neutral growth
        # rates beside them do not, because the company prints those as integer
        # percentages per release rather than as a series, and this file carries
        # the eight it reviewed.
        "大中华区收入同比（固定汇率）": "currency-neutral growth is an integer printed per "
                              "release, carried here for the reviewed eight.",
        "北美收入同比（固定汇率）": "same.",
        "投入资本回报率": "an annual measure against two filed targets, on a fiscal-year "
                  "axis starting FY2020.",
        "应收账款": "the balance sheet is carried for the reviewed eight quarters.",
        "三年遣散与重组费用": "three fiscal years of a restructuring programme; there is no "
                     "earlier programme to draw.",
        "毛利率同比（剔除关税退款）": "the tariff-refund adjustment exists only in the quarters "
                          "that have a refund.",
        "三十二个季度的直营占比": 'date corrected, and the direction of the error matters: Nike\'s MD&A "Supplemental NIKE Brand Revenues Details" table has split wholesale from direct-to-consumer in dollars every quarter since Q1 FY2013 (quarter ended 2012-08-31). What happened in 2017-2018 was a rename -- "Sales Direct to Consumer" became "NIKE Direct" -- not a new disclosure. Fetch gap.',
        "十年经营现金流": "an annual chart -- ten fiscal years, not quarters.",
        "十年回购与资本强度": "annual.",
        "回购的成交均价": "four fiscal years of a buyback programme.",
    },
    "avgo": {
        # Broadcom's window is 41 quarters, not 42: the fiscal quarter matching
        # calendar Q2 2026 has not been reported. The eight added in front
        # (Q1 2016 - Q4 2017) carry the income statement, cash flow, balance
        # sheet and working capital; four families genuinely do not exist there.
        "收入（仅公司给过区间的 5 季）": "Broadcom guided a revenue *range* in only five "
                              "quarters; the rest of the record is a single point, "
                              "which is the chart beside this one.",
        "收入（公司只给单点的 20 季）": "the point-guidance era; the two together cover the "
                            "whole guided record.",
        "收入相对指引中值的偏离": "the guidance record itself starts with the 2018-06-07 "
                       "release, which is the first Broadcom Inc. release.",
        "Adjusted EBITDA 利润率：18": "the term 'Adjusted EBITDA' appears in no Broadcom "
                              "Limited release; its first appearance is the "
                              "2018-06-07 reconciliation.",
        "Adjusted EBITDA 利润率相对指引中值": "same floor.",
        "把「超出自身指引」拆成两条腿": "one leg is the EBITDA margin, so it inherits that floor.",
        "收入 US$22,187M": "the semiconductor / infrastructure-software split does not "
                       "exist before 2018 -- the earlier segments are Wired / "
                       "Wireless / Enterprise storage / Industrial, which the "
                       "company never mapped onto the later two.",
        "两个引擎": "same segment floor.",
        "两个分部的申报营业利润": "same segment floor.",
        "AI 半导体收入：公司口头指引": "Broadcom began giving a quarterly AI revenue figure in "
                          "the 2024-06-12 release; before that there is nothing "
                          "to plot.",
        "AI 半导体收入（季）": "same floor.",
        "基础设施软件收入": "same segment floor.",
        "营运资本随 AI 放量变重": "inventory and receivables do reach 2016; this chart pairs "
                        "them with the AI-era commentary and runs on the "
                        "reviewed window.",
        "Adjusted EBITDA 利润率：阈值": "the threshold view of the same measure, which no "
                              "Broadcom Limited release contains.",
        "non-GAAP 营业利润率：阈值": "the pre-2018 non-GAAP definition adds revenue back and "
                           "is presented on continuing operations, so it is not "
                           "the same measure and is not spliced.",
        "季度回购：阈值": "no repurchase line exists in any 2016-2017 cash-flow statement "
                   "-- Broadcom was not buying back stock then.",
        "股东回报与其资金来源": "the buyback leg has the same floor, and the dividend leg "
                     "cannot be split into common-only before 2018 because the "
                     "filings give one blended total including the Broadcom "
                     "Cayman L.P. distribution.",
    },
    "meta": {
        "收入指引兑现": "Meta published no quarterly revenue outlook range before the "
                  "2022Q1 release; the record starts where the guidance does.",
        "收入相对指引中值": "the deviation view of the same record, so the same floor.",
        "FoA Other 单季收入": "segment revenue begins with the 2020Q4 release -- before that "
                        "the categories did not exist.",
        "两条非广告收入线": "same segment floor, long-run version.",
        "折旧摊销同比": "a year-on-year line has no denominator for the first four quarters "
                  "of the record, so it starts in 2017Q1.",
    },
    "bc": {
        "26 个季度里只有": "Brunello Cucinelli prints only cumulative figures, so three "
                    "quarters in four are a subtraction -- and the subtraction "
                    "needs a thousand-level table to subtract from. For 2016-2018 "
                    "no such table exists in any document, contemporaneous or "
                    "retroactive: those years' Q1 and nine-month releases are "
                    "prose, rounded to EUR 0.1M. 2019Q3 is the earliest quarter "
                    "any filing supports.",
    },
    "mc": {
        "葡萄酒与烈酒的两条腿": "LVMH first split Wines & Spirits into Champagne-and-Wines "
                      "versus Cognac-and-Spirits in 2024Q1; every full-year "
                      "appendix from 2016 through 2023 carries it as a single "
                      "line, checked one by one. The only chart on this page "
                      "that genuinely cannot reach 2016.",
    },
    "pm": {
        "下季每股收益": "Philip Morris began giving next-quarter EPS guidance with the "
                  "2020 releases; before that its only forward figure was the "
                  "full-year range.",
        "下季指引的偏离，按口径分开": "the deviation view of the same next-quarter record.",
    },
    "race": {
        # Ferrari guided only shipments, revenue, adjusted EBITDA and net debt
        # before 2019 -- twelve outlooks read one by one. No EPS or industrial
        # free cash flow guidance means no settlement to draw, and the axis of
        # these four is fiscal years, not quarters.
        "调整后 EBITDA": "annual guidance axis; the company first guided this metric for FY2019.",
        "调整后摊薄 EPS：": "annual guidance axis; EPS was never guided before 2019.",
        "工业自由现金流": "annual guidance axis; industrial FCF was disclosed as an actual "
                  "from the start but only guided from 2019.",
        "调整后摊薄 EPS 相对": "the deviation view of the same record, so the same floor.",
        "美洲出货同比": "a year-on-year line starts one year into the record, because the "
                  "first four quarters have no denominator. 2016 is the first year "
                  "Ferrari reported as a listed company.",
    },
    "cme": {
        "调整后营业费用（除许可费）": "same numerator, same 2024Q3 floor; the licensing leg alone "
                            "has 54 quarters.",
        "调整后营业利润率对": "same numerator again -- this is the threshold view of it.",
        "抵押品净利差": "the two figures are first quantified in the 10-Q filed 2022-11-02, "
                  "which carries 2022Q3 and the prior-year 2021Q3. Every earlier "
                  "filing discusses the same items only qualitatively.",
    },
    "hkex": {
        # All four are the same limit, not four separate ones: HKEX only began
        # printing a three-month market-statistics table in the announcement
        # body in 2022, in a "this quarter vs the same quarter last year"
        # section that carries exactly one prior-year comparative column. That
        # one column is what reaches back to 2021Q1 and no further. The page's
        # first draft said "the company only started printing quarterly figures
        # in 2021", which was the same mistake the page itself was rewritten to
        # fix -- a rule read off one file series and stated as a fact about the
        # company. The annual report has carried quarterly figures since FY2016;
        # what it does not carry is these market statistics.
        "现货市场日均成交额与交易结算费": "2022 年起公告正文才带三个月市场统计表，且只有一个上年比较列。",
        "越往损益表下面走": "same disclosure limit, the pass-through version of the same series.",
        "三条量：期货": "same disclosure limit, volumes rather than value.",
        "互联互通：北向日均": "same disclosure limit, Connect volumes.",
    },
    "tsm": {
        "收入（本图仅近": "dollar band; the guided number runs US$6.1B to US$45.8B, so the "
                     "early bands collapse to a few pixels on a linear axis. The "
                     "scale-free deviation chart beside it carries all 42.",
        "HPC 占比（集中度）": "TSMC changed the revenue split from by-application to "
                        "by-platform in 2019Q1 -- that report prints both bases plus a "
                        "mapping table. The series reaches 2018Q1 only because the 2019 "
                        "reports restate it in their prior-year columns; 2016-2017 "
                        "quarterly platform values were never published.",
        "HPC 从": "same disclosure limit, long-run version of the same series.",
        "2nm 占晶圆收入": "2nm sat inside the 'advanced' aggregate until 2025Q2.",
    },
}


FLOOR_KIND = {
    'hkex': {
        '现货市场日均成交额与交易结算费': 'disclosure',
        '越往损益表下面走': 'disclosure',
        '三条量：期货': 'disclosure',
        '互联互通：北向日均': 'disclosure',
    },
    'avgo': {
        '把「超出自身指引」拆成两条腿': 'coverage',
        '收入（仅公司给过区间的 5 季）': 'disclosure',
        '收入（公司只给单点的 20 季）': 'disclosure',
        '收入相对指引中值的偏离': 'disclosure',
        'Adjusted EBITDA 利润率：18': 'disclosure',
        'Adjusted EBITDA 利润率相对指引中值': 'disclosure',
        '收入 US$22,187M': 'disclosure',
        '两个引擎': 'disclosure',
        '两个分部的申报营业利润': 'disclosure',
        'AI 半导体收入：公司口头指引': 'disclosure',
        'AI 半导体收入（季）': 'disclosure',
        '基础设施软件收入': 'disclosure',
        '营运资本随 AI 放量变重': 'coverage',
        'Adjusted EBITDA 利润率：阈值': 'disclosure',
        'non-GAAP 营业利润率：阈值': 'disclosure',
        '季度回购：阈值': 'disclosure',
        '股东回报与其资金来源': 'disclosure',
    },
    # Why each exemption is short, in four kinds. The kind matters more than the
    # prose: three of these entries used to read like "the company never
    # published this earlier" when what was true was "this repo has not fetched
    # it yet", and that difference is the whole point of the ratchet. Moody's
    # guided FY2018 adjusted EPS on 2018-02-09 (.65-.85), MSCI guided FY2019
    # operating expenses on 2019-01-31, and TJX gave next-quarter EPS and comp
    # guidance in its FY2020 8-K exhibits -- all three were written down here as
    # "the record starts at" and all three were wrong.
    #
    #   "disclosure" -- a pre-floor filing was read and the figure is not in it
    #   "design"     -- deliberately short for a rendering reason, not a data one
    #   "coverage"   -- the filings have it; this repo has not fetched it yet
    #   "unverified" -- the reason was inherited and no pre-floor filing was read
    #
    #  and  are a to-do list, not an answer. The test below
    # prints them so they cannot quietly become permanent.
    'amzn': {
        '净销售额': 'coverage',
        '经营利润相对指引中值': 'coverage',
        'TTM 自由现金流': 'coverage',
        '三个分部的经营利润率': 'coverage',
        '北美分部经营利润率': 'coverage',
        '广告同比': 'disclosure',
        'AWS backlog 单季净增': 'coverage',
        '单季现金 CapEx（净额': 'coverage',
        '总收入同比': 'coverage',
        '资本强度': 'disclosure',
    },
    'cboe': {
        '最想结清的那条指引': 'disclosure',
        '其中最关键的一条': 'disclosure',
        '同一形状在股票撮合里重演': 'disclosure',
        '五个分部的净收入': 'disclosure',
        '毛收入与净收入之间那道楔子': 'disclosure',
        '公司自己的第二套口径': 'disclosure',
    },
    'cdns': {
        '收入（本图仅近 20 季）': 'design',
        '非 GAAP 营业利润率（本图仅近 20 季）': 'design',
        '非 GAAP EPS（本图仅近 20 季）': 'design',
        '季末 backlog': 'disclosure',
        'backlog 创纪录': 'disclosure',
        'backlog / 过去四季收入': 'disclosure',
        '中国收入 $': 'disclosure',
        '中国收入占比': 'disclosure',
        '单季经营现金流': 'coverage',
        '经营现金流 $635M': 'coverage',
        '单季回购金额': 'coverage',
        '单季回购 $200M': 'coverage',
        '三条产品线的分化': 'coverage',
        'GAAP 毛利率降到': 'coverage',
        '本季非 GAAP 营业利润率': 'coverage',
        '单季非 GAAP 营业利润率': 'coverage',
    },
    'cme': {
        '调整后营业费用（除许可费）': 'disclosure',
        '调整后营业利润率对': 'disclosure',
        '抵押品净利差': 'disclosure',
    },
    'googl': {
        'Cloud 收入 YoY': 'disclosure',
        'Cloud 经营利润率': 'disclosure',
        'Search & other YoY': 'disclosure',
        'Cloud backlog 环比': 'disclosure',
        'Cloud backlog 单季净增': 'disclosure',
        'backlog 创': 'disclosure',
        'Cloud 增速本季': 'disclosure',
        'Search 增速本季': 'disclosure',
    },
    'ma': {
        '净收入的同比增量拆成三条腿': 'disclosure',
        '毛计费的同比增量': 'disclosure',
        '返点占毛计费从': 'disclosure',
        '返点占比的同比变化': 'disclosure',
        '四条计费线': 'disclosure',
    },
    # All five were 'coverage' -- "the filings have it, we have not fetched it".
    # They have now been fetched, back to FY2011, and the answer is that this is
    # a disclosure floor after all. Three separate reasons, none of which was
    # visible before the fetch:
    #   * FY2015 has no adjusted-EPS guidance of any vintage. The outlook table
    #     that year labels its single EPS line "GAAP EPS". So a band drawn back
    #     past FY2016 has a hole in the middle of it, not at its edge.
    #   * Moody's broadened its non-GAAP definition with the FY2017 disclosures
    #     to also exclude amortisation of acquired intangibles (Bureau van Dijk),
    #     and restated FY2016's adjusted EPS 4.81 -> 4.94 for it. FY2013-2015
    #     never reappear as a comparator after that change, so no filing bridges
    #     them: charting them on one axis would splice two non-GAAP definitions
    #     with no way to mark where.
    #   * FY2011's adjusted figures exist only as a one-time look-back printed in
    #     the Feb-2013 release, under a narrower definition again, single-sourced.
    # The guided *ranges* do go back to FY2011 and are recorded; what cannot be
    # extended is the guide-versus-actual comparison these five charts draw.
    'mco': {
        '调整后摊薄 EPS（对末次指引）': 'disclosure',
        '调整后摊薄 EPS（对初始指引）': 'disclosure',
        '调整后摊薄 EPS（2 月那版）': 'disclosure',
        '调整后摊薄 EPS（10 月那版）': 'disclosure',
        '每一年的指引中值怎么被改到实际值上': 'disclosure',
    },
    'meta': {
        '收入指引兑现': 'disclosure',
        '收入相对指引中值': 'disclosure',
        'FoA Other 单季收入': 'disclosure',
        '两条非广告收入线': 'disclosure',
        '折旧摊销同比': 'coverage',
    },
    'axp': {
        '税前利润同比增量拆成两条腿': 'design',
        '消费额同比': 'disclosure',
        'jaws（收入增速 − 费用增速）': 'design',
        '四个分部的税前利润率': 'disclosure',
        'VCE 占收入比': 'disclosure',
        '全年摊薄 EPS相对指引中值的偏离': 'disclosure',
        '全年收入增速相对指引中值的偏离': 'disclosure',
        '收入增速：对年初那一档': 'disclosure',
    },
    'cost': {
        '会员续费率': 'disclosure',
        '每股收益增速拆成四条腿': 'disclosure',
        '客流与客单': 'disclosure',
        '公司自己估的财年末仓库数': 'disclosure',
        'Executive 会员': 'disclosure',
        '四条商品线对净销售额增速的贡献': 'disclosure',
        '毛利率 11.04%': 'design',
        '三个地区分部的营业利润率': 'disclosure',
    },
    'mu': {
        '收入相对指引中值的偏离': 'disclosure',
        'non-GAAP 毛利率': 'disclosure',
        'non-GAAP 每股收益': 'disclosure',
        '收入（本图仅近 12 季）': 'design',
        '把「超出自身指引」拆成三条腿': 'disclosure',
        '一年之间收入': 'disclosure',
        '存货 US$8.6B': 'disclosure',
        '四个业务单元的收入': 'disclosure',
        '业务单元毛利率': 'disclosure',
        '按技术拆收入': 'coverage',
    },
    'msci': {
        '三条收入腿': 'coverage',
        '四个分部': 'coverage',
        '分部调整后 EBITDA 利润率': 'coverage',
    },
    'msft': {
        'Azure 固定汇率增速': 'disclosure',
        'Intelligent Cloud 分部毛利率': 'coverage',
        'Intelligent Cloud 本季首次超过': 'coverage',
        '商业剩余履约义务': 'coverage',
        'FY2026 股东回报': 'design',
        '季度折旧': 'disclosure',
    },
    'ndaq': {
        '全年非 GAAP 有效税率': 'disclosure',
        'FY2026 费用指引的三次发布': 'design',
        'Market Services 毛收入的去向': 'disclosure',
        '三个分部的净收入': 'disclosure',
        'Financial Technology 的三条子线': 'disclosure',
        'Index：挂钩纳斯达克指数的 ETP AUM': 'disclosure',
        'ARR 两条腿': 'disclosure',
    },
    'nke': {
        '大中华区收入同比（固定汇率）': 'coverage',
        '北美收入同比（固定汇率）': 'coverage',
        '投入资本回报率': 'design',
        '应收账款': 'coverage',
        '三年遣散与重组费用': 'disclosure',
        '毛利率同比（剔除关税退款）': 'disclosure',
        '三十二个季度的直营占比': 'coverage',
        '十年经营现金流': 'design',
        '十年回购与资本强度': 'design',
        '回购的成交均价': 'design',
    },
    'bc': {
        '26 个季度里只有': 'disclosure',
    },
    'mc': {
        '葡萄酒与烈酒的两条腿': 'disclosure',
    },
    'pm': {
        '下季每股收益': 'disclosure',
        '下季指引的偏离，按口径分开': 'disclosure',
    },
    'race': {
        '调整后 EBITDA': 'disclosure',
        '调整后摊薄 EPS：': 'disclosure',
        '工业自由现金流': 'disclosure',
        '调整后摊薄 EPS 相对': 'disclosure',
        '美洲出货同比': 'disclosure',
    },
    'schw': {
        'NIM（环比是否恢复增长）': 'coverage',
        'NIM：': 'coverage',
        '调整后 Tier 1 杠杆率': 'disclosure',
        '五条收入线': 'disclosure',
        '季度净新增资产按渠道': 'design',
        '经营杠杆': 'design',
    },
    'skhynix': {
        'DRAM 平均售价的环比': 'disclosure',
        'NAND 平均售价的环比': 'disclosure',
        'DRAM 的量与价': 'disclosure',
        'NAND 的量与价': 'disclosure',
    },
    'snps': {
        '把「超出自身指引」拆成两条腿': 'disclosure',
        '未来 12 个月可确认 backlog': 'disclosure',
        'FSA 占 backlog': 'disclosure',
        'backlog 自': 'disclosure',
        '收入 US$2,477M': 'design',
        'Design IP 连续三季': 'disclosure',
        '两个分部的调整后营业利润率': 'disclosure',
        'GAAP 与 non-GAAP 营业利润之间隔着': 'design',
        '八季里收入指数化到': 'design',
        'FY2026 收入指引四次上调': 'design',
        'non-GAAP 营业利润率：下季阈值': 'design',
        'Design IP 收入同比：下季阈值': 'design',
        '摊薄股数：下季阈值': 'design',
        '中国占比': 'disclosure',
    },
    'spgi': {
        '五个分部各自占分部收入合计的比重': 'disclosure',
        '六条申报收入类型各自占毛收入的比重': 'disclosure',
        '订阅型收入占毛收入比重': 'disclosure',
        '计费发行量': 'disclosure',
        'GAAP 摊薄 EPS相对指引中值的偏离': 'disclosure',
        'GAAP 收入增速相对指引中值的偏离': 'disclosure',
        '调整后自由现金流相对指引中值的偏离': 'disclosure',
        'Ratings 的两条腿': 'design',
        '交易性收入占 Ratings 比重': 'design',
        'Ratings 交易性收入同比': 'design',
        '营业利润率（剔除处置损益与联营收益 D）vs 阈值': 'design',
        '本季自由现金流': 'design',
        '单季自由现金流 D vs 阈值': 'design',
        '单季股东回报 / 自由现金流 D vs 阈值': 'design',
    },
    'tjx': {
        '摊薄每股收益（近 16 季）': 'coverage',
        '税前利润率：': 'coverage',
        '税前利润率相对指引中值': 'coverage',
        '合并同店销售：': 'coverage',
        '合并同店销售相对指引中值': 'coverage',
        '十年税前利润率与资本强度': 'design',
        '十年门店数与总面积': 'design',
        '十年回购与股数': 'design',
        '十年经营现金流、资本开支与股东回报': 'design',
    },
    'tsm': {
        '收入（本图仅近': 'design',
        'HPC 占比（集中度）': 'disclosure',
        'HPC 从': 'disclosure',
        '2nm 占晶圆收入': 'disclosure',
    },
    'v': {
        '美国以外贡献净收入': 'disclosure',
    },
}


class ChartWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pages = {
            entry["slug"]: js_payload(ROOT / "data" / f"{entry['slug']}.js", "window.DASH")
            for entry in ENTRIES
        }
        cls.timed = {}
        for slug, payload in cls.pages.items():
            found = []
            for section in payload["sections"]:
                for exhibit in section["exhibits"]:
                    year = first_year(exhibit)
                    if year is not None:
                        found.append((exhibit, year))
            cls.timed[slug] = found

    def test_the_ratchet_names_every_published_page(self) -> None:
        self.assertEqual(set(REACH_2016), set(self.pages))
        self.assertLessEqual(set(CONVERTED), set(self.pages))

    def test_no_page_loses_ground(self) -> None:
        """Below the pin is a regression; above it is progress that has to be recorded."""
        moved = []
        for slug, found in sorted(self.timed.items()):
            reached = sum(1 for _, year in found if year <= TARGET_YEAR)
            pinned = REACH_2016[slug]
            self.assertGreaterEqual(
                reached, pinned,
                f"{slug}: {reached} exhibits reach {TARGET_YEAR}, down from the pinned "
                f"{pinned}. A page does not go backwards -- if a chart was shortened on "
                "purpose, say why in the commit and lower the pin deliberately.",
            )
            if reached > pinned:
                moved.append(f'"{slug}": {reached}  (was {pinned})')
        self.assertEqual(
            moved, [],
            "these pages now reach further back than the ratchet records; update "
            "REACH_2016 in this file so the count lands in the commit that earned it:\n  "
            + "\n  ".join(moved),
        )

    def test_every_exemption_declares_what_kind_of_floor_it_is(self) -> None:
        """The prose alone was not enough, and it failed three times.

        An exemption saying "the record starts at 2019" reads as a fact about
        the company. Three of them were facts about this repo instead:

          * Moody's 2018-02-09 release guides FY2018 adjusted diluted EPS at
            $7.65-$7.85, so "the annual record starts FY2019" was a fetch floor.
          * MSCI's 2019-01-31 release guides FY2019 total operating expenses at
            $772-800M -- exactly the metric the page scores.
          * TJX's FY2020 8-K exhibits give next-quarter EPS and comp guidance,
            so "earlier quarters guided it only on the call" was wrong.

        None of those was caught by reading the sentence, because all three
        sentences were well-formed. `FLOOR_KIND` makes the claim explicit and
        separable: a "disclosure" floor asserts something about the filings and
        has to have been checked against one; a "coverage" floor asserts nothing
        except that the work is not done.
        """
        for slug, exemptions in CONVERTED.items():
            kinds = FLOOR_KIND.get(slug, {})
            self.assertEqual(
                sorted(exemptions), sorted(kinds),
                f"{slug}: every exemption needs a FLOOR_KIND and vice versa")
            for title, kind in kinds.items():
                self.assertIn(kind, ("disclosure", "design", "coverage", "unverified"),
                              f"{slug} / {title}")

    def test_the_unfinished_exemptions_stay_visible(self) -> None:
        """Two of the four kinds are a to-do list; this is where it is printed.

        A `coverage` or `unverified` floor is not an answer to "why does this
        chart stop in 2019" -- it is a note that nobody has answered it yet. The
        count is pinned so that clearing one is a deliberate edit here, and so
        that adding one is too.
        """
        pending = [(slug, title, kind)
                   for slug, kinds in sorted(FLOOR_KIND.items())
                   for title, kind in kinds.items()
                   if kind in ("coverage", "unverified")]
        by_kind = {}
        for slug, title, kind in pending:
            by_kind.setdefault(kind, []).append(f"{slug}/{title}")
        self.assertEqual(len(by_kind.get("coverage", [])), 37,
                         "charts whose data exists and has not been fetched")
        # Zero, and that is the point: every exemption on this page has now been
        # read against an actual pre-floor filing. The fourteen that had never
        # been checked were checked, and only four of them were right -- six were
        # fetch gaps wearing a disclosure excuse, four had the wrong date. An
        # unverified excuse is not a weaker reason, it is not a reason.
        self.assertEqual(len(by_kind.get("unverified", [])), 0,
                         "charts whose stated reason has never been checked "
                         "against a pre-floor filing")
        # ...and the two settled kinds, so the split cannot drift silently.
        settled = [kind for kinds in FLOOR_KIND.values() for kind in kinds.values()
                   if kind in ("disclosure", "design")]
        self.assertEqual(settled.count("disclosure"), 121)
        self.assertEqual(settled.count("design"), 34)

    def test_no_page_has_an_unexplained_short_axis_beyond_the_pinned_backlog(self) -> None:
        """Every short chart either names its reason or is counted here.

        This used to iterate `CONVERTED.items()` -- that is, it policed exactly
        the pages that had already been written up, and a page with no entry at
        all was invisible to it. The guarantee everyone read into it ("every
        chart that stops after 2016 says why") held for 18 of 31 pages; the
        other 12 carried 151 short charts with no statement of any kind. The
        check's domain was derived from the very map it was checking, so adding
        a page to the map was the only way to come under scrutiny.

        Scanning every page instead. The 151 are not excuses -- they are an
        admission, pinned per page so the number is visible and can only move
        deliberately: a new short chart without a reason pushes a count up, and
        writing a real reason pushes it down. Either way this turns red and
        someone has to look.
        """
        by_page, by_design, by_length = {}, {}, {}
        for label, exhibit in exhibits():
            year = first_year(exhibit)
            if year is None or year <= TARGET_YEAR:
                continue
            slug = label.split()[0]
            title = exhibit["title"]
            if any(key in title for key in CONVERTED.get(slug, {})):
                continue
            by_page[slug] = by_page.get(slug, 0) + 1
            bucket = (by_design if len(exhibit.get("xlabels") or []) <= 8
                      else by_length)
            bucket[slug] = bucket.get(slug, 0) + 1
        combined = {slug: SHORT_BY_DESIGN.get(slug, 0) + UNEXPLAINED_LONG.get(slug, 0)
                    for slug in set(SHORT_BY_DESIGN) | set(UNEXPLAINED_LONG)}
        self.assertEqual(by_page, combined)
        self.assertEqual(sum(SHORT_BY_DESIGN.values()), 64)
        # Zero, as of the SK hynix backfill. This number is not load-bearing on
        # its own -- an empty dict sums to zero for free -- but `by_length ==
        # UNEXPLAINED_LONG` two lines down is, and that one is what turns red if
        # a long chart appears without a reason. Keep both: this one says what
        # the site's backlog IS, that one says the pin was measured.
        self.assertEqual(sum(UNEXPLAINED_LONG.values()), 0)
        # and the pins are the split the data actually has, not a hand-typed one
        self.assertEqual(by_design, SHORT_BY_DESIGN)
        self.assertEqual(by_length, UNEXPLAINED_LONG)

    def test_converted_pages_have_no_unexplained_short_axis(self) -> None:
        """Every excuse on a page is real, distinct, and non-empty.

        This used to also require that a page in CONVERTED explain *every* one of
        its short charts. That made sense while CONVERTED was the only mechanism,
        but the backlog census now scans all 31 pages and accounts for whatever
        has no excuse yet. Keeping both rules created a perverse incentive:
        writing one well-evidenced excuse for a page pulled in an obligation to
        write one for every other chart on it, so the cheapest way to stay green
        was to write none at all. Same shape as the domain bug above -- a check
        whose scope was set by the very map it was checking.

        So completeness now lives in one place, the census, and this test keeps
        the part that is genuinely local: that each excuse matches exactly one
        chart and says something.
        """
        for slug, excuses in CONVERTED.items():
            short = {}
            for exhibit, year in self.timed[slug]:
                if year <= TARGET_YEAR:
                    continue
                title = exhibit["title"]
                matched = [key for key in excuses if key in title]
                if not matched:
                    continue        # accounted for by the census instead
                # One key per chart. Overlapping keys ("调整后摊薄 EPS" also matches
                # "调整后摊薄 EPS 相对…") make the match order-dependent, and the
                # loser then looks unused below -- which is how this was found.
                self.assertEqual(
                    len(matched), 1,
                    f"{slug}: {matched} all match one title; make the keys distinct",
                )
                self.assertTrue(excuses[matched[0]].strip(),
                                f"{slug}: empty reason for {title[:40]}")
                short[matched[0]] = True
            unused = sorted(set(excuses) - set(short))
            self.assertEqual(
                unused, [],
                f"{slug}: these exhibits are no longer short, so drop their entries "
                f"from CONVERTED: {unused}",
            )

    def test_the_site_total_is_pinned_too(self) -> None:
        """One number, so the migration's progress is legible in one place."""
        reached = sum(
            1 for found in self.timed.values() for _, year in found if year <= TARGET_YEAR
        )
        total = sum(len(found) for found in self.timed.values())
        self.assertEqual(reached, sum(REACH_2016.values()))
        # The denominator moves when a page gains or loses an exhibit, so it is
        # a range rather than a point -- tight enough to notice a page vanishing.
        self.assertGreaterEqual(total, 540)
        self.assertLessEqual(total, 620)

    def test_flipping_the_alternation_changes_nothing(self) -> None:
        """The property that makes the parser safe, stated as a property.

        A year group with nothing behind it lets the two-digit branch win on a
        four-digit year: "FY2017" reads as 20, which becomes 2020. The failure
        is silent and it moves charts in the *safe* direction, so a page under
        the ratchet would look further along than it is.

        What actually prevents it is the anchor after the group, not the order
        inside it -- with `\\b` or `$` behind, the engine backtracks out of the
        short branch. So the check is: rewrite every pattern with the branches
        swapped and confirm the parse is identical on every label the site
        publishes. If a pattern is ever added without an anchor, the swap starts
        producing 2020s and this turns red. Asserting a list of anchors instead
        would have to be taught what counts as one -- a literal `-` anchors just
        as well as `\\b`.
        """
        swapped = [
            (re.compile(p.pattern.replace(r"(\d{4}|\d{2})", r"(\d{2}|\d{4})")), g)
            for p, g in _PERIOD
        ]
        self.assertNotEqual(
            [p.pattern for p, _ in swapped], [p.pattern for p, _ in _PERIOD],
            "no pattern has a two-branch year group any more; this test is now vacuous",
        )

        def parse_with(patterns: list, label: str) -> int | None:
            for pattern, group in patterns:
                match = pattern.match(label)
                if not match:
                    continue
                rest = label[match.end():].strip()
                if rest and not _QUALIFIER.match(rest):
                    return None
                year = int(match.group(0) if group == 0 else match.group(group))
                return year + 2000 if year < 80 else (year + 1900 if year < 100 else year)
            return None

        labels = {
            label
            for payload in self.pages.values()
            for section in payload["sections"]
            for exhibit in section["exhibits"]
            for label in (exhibit.get("xlabels") or [])
            if isinstance(label, str) and label.strip()
        }
        self.assertGreater(len(labels), 300, "the label corpus collapsed")
        differing = sorted(
            label for label in labels
            if parse_with(_PERIOD, label.strip()) != parse_with(swapped, label.strip())
        )
        self.assertEqual(
            differing, [],
            "these labels parse differently once the year alternation is swapped, "
            "which means the pattern that matched them has no anchor behind its "
            f"year group: {differing[:8]}",
        )

    def test_the_year_parser_reads_the_shapes_the_site_publishes(self) -> None:
        """The behavioural half. Every shape below appears in a live payload."""
        for label, expected in [
            ("Q1 2017", 2017), ("Q1'17", 2017), ("2017Q1", 2017), ("17Q1", 2017),
            ("FY2017", 2017), ("FY17 初", 2017), ("Mar-17", 2017), ("2017-03-31", 2017),
            ("H1 2017", 2017), ("2017H1", 2017), ("1Q 2017", 2017), ("2017", 2017),
        ]:
            self.assertEqual(label_year(label), expected, label)
        for label in ["收入", "已验证", "", "美国与加拿大", "毛利率", None]:
            self.assertIsNone(label_year(label), repr(label))
        # A period followed by a qualifier is still a period...
        for label, expected in [("FY19 Q2", 2019), ("FY23 初", 2023), ("FY2019 initial", 2019),
                                ("Q1 2026 原披露", 2026), ("FY22 初*", 2022), ("Q2'24→FY24", 2024)]:
            self.assertEqual(label_year(label), expected, label)
        # ...but a period followed by a metric or an event is not a period at
        # all: those axes list metrics and earnings calls, and counting them
        # would put a page under an obligation to extend a chart whose x axis
        # is not time.
        for label in ["Q1 2026 non-GAAP EPS", "Q2 2026 call", "Q4 2025 电话会",
                      "Q1 2026 期货与期权清算费", "FY2026 CapEx 指引中点", "Q1 2026 报告同比"]:
            self.assertIsNone(label_year(label), label)

    def test_a_categorical_axis_is_not_counted_as_time(self) -> None:
        """Otherwise the ratchet could be satisfied by a KPI list that happens to
        name two years."""
        self.assertIsNone(first_year({"xlabels": ["收入", "毛利率", "2026 指引"]}))
        self.assertIsNone(first_year({"xlabels": []}))
        self.assertIsNone(first_year({"xlabels": ["Q1 2016"]}))
        self.assertEqual(first_year({"xlabels": ["Q1 2016", "", "", "", "Q1 2017"]}), 2016)


# Short charts that carry no stated reason at all, per page. This is a backlog,
# not a set of excuses -- see
# `test_no_page_has_an_unexplained_short_axis_beyond_the_pinned_backlog`.
# Every one of these pages sits outside CONVERTED entirely, which is why nothing
# was asking them the question.
# Split by length, because the two halves are different problems and one number
# hides that. The criterion is structural (how many points the chart draws), NOT
# a judgement that any particular chart is unextendable -- none of the 151 has
# been checked against a pre-floor filing, which is exactly what makes them a
# backlog rather than a set of excuses.
#
# Eight points or fewer: on this site that is the current-quarter detail
# convention -- bridges, KPI headroom bars, this-quarter-versus-last panels. The
# window migration is not really about these, but `first_year()` counts them, so
# they sit in the 550 denominator and have to be accounted for somewhere.
SHORT_BY_DESIGN = {
    'bc': 7,
    'mc': 10,
    'nvda': 11,
    'pm': 9,
    'rms': 7,
    'samsung': 15,
    'skhynix': 5,

}

# More than eight points: a chart that already draws a long series and still
# stops after 2016. This is where the remaining work actually is. Several are
# one short hop from the floor -- six AXP charts start in 2017.
UNEXPLAINED_LONG = {

}


# ── the prose census ────────────────────────────────────────────────────────
# Extending a window re-derives every number a chart *computes*, and silently
# invalidates every number its prose *states*. That is not hypothetical: pulling
# MSCI, Moody's and NVIDIA out to 42 quarters left "31 季利润率" on a 42-quarter
# chart, "21 季两块业务" on another, and -- worst -- an NVIDIA note still saying
# gross margin broke its floor "三次" when the longer window shows five, and that
# Q2'22 was the "唯一一次" revenue miss when Q4'18 was deeper. Those read as facts
# about the company; they were facts about the left edge of the window.
#
# So every quarter-count in published prose has to be *licensed* by something
# measurable in the exhibit that prints it -- its window length, a lag of that
# window, the non-null length of one of its series, or a sibling chart's window
# on the same page (cross-references like "完整 43 季记录见下一张" are legitimate
# and common). What is left over is pinned here, one line of reason each.
#
# The pin is the point. A count that cannot be derived is not necessarily wrong
# -- all eight below are correct -- but it is a number no rebuild can correct,
# so it has to be re-read by a person whenever it moves.

# A number that is licensed by an anchor elsewhere in the same exhibit's prose
# ("42 季里 39 季为正" licenses the 39) is not listed; the anchor is checked
# exhibit-wide, not field by field, because a title routinely anchors its note.
UNDERIVABLE_QUARTER_COUNTS = {
    "hkex Ex3": ([13], "Ex3 的 x 轴是 29 个「收入分项被公司印过」的季度；13 是它在 42 季"
                       "窗口里的补集，而 42 是别的图的轴长、不是这张图的任何属性 —— 这张图"
                       "自己没有任何地方声明窗口有多长。那 13 个季度本身在本页 8 张 42 季图"
                       "上都画着（画的是它们的合计数，减出来的是收入分项），只是没有任何一张"
                       "图把它们单独成组，所以也不是「补集没被画」。"),
    "avgo Ex16": ([32], "「前 32 个季度这条线一直在…」——序列内一段前缀，不是窗口长度"),
    "cdns Ex11": ([43], "指向完整指引记录的交叉引用；本图只画近 20 季"),
    "cme Ex14":  ([37], "锚是同句里用中文写的「五十四个季度里」，数字形式的锚不存在"),
    "cme Ex21":  ([34], "税改前 7 季 / 之后 34 季的分段均值，两段都短于窗口"),
    "ibkr Ex9":  ([34], "已由 len(reported) 算出：该行有披露的季度数，非窗口长度"),
    "ibkr Ex18": ([16], "佣金曾连续 16 季是第一大收入来源，是一段区间的长度"),
    "meta Ex9":  ([13], "价格腿同比为负的季度数，是条件计数"),
    "ndaq Ex7":  ([18], "Section 31 规费按金额单列的季度数（18 季），少于该图 42 季的窗口 —— "
                        "更早的季度只在 MD&A 脚注里给合计，未按两条收入线拆开"),
    "axp Ex16":  ([16], "两条口径同时被印出来的季度数（16 季），是重叠区间的长度，"
                        "不是该图 42 季的窗口 —— 图注拿它论证两条线不能接成一条"),
    "axp Ex17":  ([16], "同上，同一句重叠区间长度出现在另一张信用图的图注里"),
    "skhynix Ex7": ([22], "这一页此前的窗口长度。图注解释的正是「从 22 季拉到 42 季」"
                          "改变了什么，所以那个 22 指的是旧窗口，不是本图的任何一段"),
    "tsm Ex26":  ([22], "自 2021Q1 起两口径逐季相等的季度数，起点晚于窗口左端"),
}


class ProseQuarterCountTest(unittest.TestCase):
    """Every quarter-count printed in prose is derivable, or pinned with a reason."""

    #    「42 季里 …」/「42 个已完结季中 …」-- an anchor that licenses the tallies
    #    stated beside it.
    ANCHOR = re.compile(r"(\d+)\s*(?:个)?(?:已完结)?季(?:度)?(?:里|中)")
    #    Any quarter-count. The lookbehind drops fiscal years and quarter labels
    #    ("FY2025 季均线", "Q3'20 起的窗口"), which are not counts of anything.
    COUNT = re.compile(r"(?<![FYQ\d'\u2019])(\d+)\s*(?:个)?(?:已完结)?季(?:度)?")

    @staticmethod
    def _derivable(exhibit: dict) -> tuple[int, set]:
        """Counts this exhibit can honestly name, from its own payload."""
        labels = exhibit.get("xlabels") or exhibit.get("x") or []
        n = len(labels)
        # n-1 and n-4 are the quarter-on-quarter and year-on-year lags: a 42
        # quarter series yields 41 changes and 38 year-on-year comparisons, and
        # notes legitimately say so.
        ok = {n, max(n - 1, 0), max(n - 4, 0)}
        for key in ("series", "values", "lines", "bars", "stack", "yoy", "line"):
            value = exhibit.get(key)
            blocks = []
            if isinstance(value, list) and value:
                blocks = value if isinstance(value[0], dict) else [{"values": value}]
            elif isinstance(value, dict):
                blocks = [value]
            for block in blocks:
                values = block.get("values") or block.get("v") or []
                if isinstance(values, list):
                    ok |= {len(values), sum(1 for v in values if v is not None)}
        return n, ok

    def test_every_quarter_count_in_prose_is_derivable_or_pinned(self) -> None:
        by_page = collections.defaultdict(set)
        every = list(exhibits())
        for label, exhibit in every:
            by_page[label.split()[0]] |= self._derivable(exhibit)[1]

        found = {}
        for label, exhibit in every:
            n, ok = self._derivable(exhibit)
            # Charts shorter than a year make no window claim worth policing.
            if n < 12:
                continue
            ok |= by_page[label.split()[0]]
            prose = " ".join(exhibit.get(field) or "" for field in
                             ("title", "note", "subtitle")
                             if isinstance(exhibit.get(field), str))
            if {int(m.group(1)) for m in self.ANCHOR.finditer(prose)} & ok:
                continue
            loose = sorted({int(m.group(1)) for m in self.COUNT.finditer(prose)
                            if int(m.group(1)) >= 12} - ok)
            if loose:
                found[label] = loose

        expected = {k: v[0] for k, v in UNDERIVABLE_QUARTER_COUNTS.items()}
        self.assertEqual(
            found, expected,
            "a quarter-count in published prose is no longer derivable from the "
            "chart that prints it. Re-read the sentence against the current "
            "window -- do not just move the pin: this check exists because "
            "extending a window turns a true sentence into a false one without "
            "touching it. If the number is right, add it to "
            "UNDERIVABLE_QUARTER_COUNTS with the reason it cannot be derived.")

    def test_the_census_does_not_pin_charts_that_no_longer_exist(self) -> None:
        """A pin outliving its exhibit would silently stop protecting anything."""
        live = {label for label, _ in exhibits()}
        self.assertEqual(sorted(set(UNDERIVABLE_QUARTER_COUNTS) - live), [])

    def test_a_year_label_is_not_read_as_a_quarter_count(self) -> None:
        """「FY2025 季均线」and「Q3'20 起」name periods, not counts of them."""
        self.assertEqual([m.group(1) for m in self.COUNT.finditer("FY2025 季均线")], [])
        self.assertEqual([m.group(1) for m in self.COUNT.finditer("Q3'20 起的 24 季窗口")],
                         ["24"])
        self.assertEqual([m.group(1) for m in self.COUNT.finditer("42 季里 39 季为正")],
                         ["42", "39"])


if __name__ == "__main__":
    unittest.main()
