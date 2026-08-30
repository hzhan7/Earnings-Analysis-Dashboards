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

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.all import ENTRIES  # noqa: E402

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
    "amzn": 9, "avgo": 0, "axp": 5, "bc": 0, "cboe": 9, "cdns": 9, "cme": 14,
    "cost": 7, "googl": 11, "ibkr": 21, "ma": 16, "mc": 0, "mco": 7, "meta": 10,
    "msci": 9, "msft": 8, "mu": 2, "ndaq": 8, "nke": 7, "nvda": 4, "pm": 6,
    "race": 9, "rms": 0, "samsung": 0, "schw": 10, "skhynix": 0, "snps": 3,
    "spgi": 2, "tjx": 8, "tsm": 18, "v": 14,
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
        "商业剩余履约义务": "Microsoft began giving the commercial RPO split five quarters "
                     "ago; earlier releases give the total and not the split.",
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
        "经营利润：": "same guidance record.",
        "经营利润相对指引中值": "the deviation view of the same record; its own floor is "
                        "later because Amazon only began giving an operating-income "
                        "range in the 2021Q3 release.",
        "把「超出自身指引」拆成两条腿": "same guidance record.",
        "指引隐含的经营利润率": "same guidance record.",
        "TTM 自由现金流": "Amazon's own trailing free-cash-flow figure, as the company "
                     "prints it, from the 2019Q1 release on.",
        "三个分部的经营利润率": "the North America and International segment tables begin "
                        "2019Q1; only AWS reaches 2016.",
        "北美分部经营利润率": "same segment floor.",
        "广告同比": "the seven product-line disaggregation begins with the 2020Q3 release.",
        "AWS backlog 单季净增": "Amazon has given the AWS backlog balance for four quarters.",
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
    "cboe": {
        "最想结清的那条指引": "organic net revenue growth was guided as a number only for "
                       "2022-2024; from 2025 the guidance is a phrase, and the page "
                       "does not convert phrases into endpoints.",
        "其中最关键的一条": "Cboe first printed a separate multi-listed options market "
                     "share in the 2019Q2 release; ADV and RPC -- and so the money "
                     "line beside it -- do run the whole window.",
        "同一形状在股票撮合里重演": "the off-exchange block (share, ADV, net capture) begins "
                          "2021Q1.",
        "五个分部的净收入": "the current five-segment split begins 2021Q3; the earlier "
                     "structure had different segments.",
        "毛收入与净收入之间那道楔子": "the cost-of-revenue components that make the wedge are "
                            "disclosed from 2017Q1.",
        "公司自己的第二套口径": "Cboe began the derivatives / cash-and-spot / data-vantage "
                       "categorisation in 2021Q1.",
        "回购与股息": "the capital block starts 2017Q1.",
    },
    "ndaq": {
        "全年非 GAAP 有效税率": "Nasdaq began guiding a non-GAAP tax-rate range for FY2019.",
        "FY2026 费用指引的三次发布": "three guidance vintages for one fiscal year -- the axis "
                            "is release dates, not quarters.",
        "「经纪、清算与交易所费用」拆开看": "the Section 31 fee split is disclosed from 2022Q1.",
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
        "ARR 两条腿": "Nasdaq began giving ARR by segment in 2023Q1.",
    },
    "mco": {
        # All five are the same record: Moody's began publishing a full-year
        # adjusted-EPS range with the FY2019 outlook. The axis is fiscal years,
        # not quarters, and there is nothing earlier to score.
        "调整后摊薄 EPS（对末次指引）": "the annual adjusted-EPS guidance record starts FY2019.",
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
        # Two floors. The annual guidance record starts with the FY2020 outlook
        # -- MSCI began giving full-year ranges for operating expenses, adjusted
        # EBITDA expenses and free cash flow then, and the axis is fiscal years.
        # The three quarter charts below need the revenue split by type and by
        # segment, which this file carries for the reviewed eight quarters only;
        # the run-rate, AUM and margin series beside them do run from 2016Q1.
        "营业费用：": "the annual expense guidance record starts with FY2020.",
        "营业费用相对指引中值": "the deviation view of the same record.",
        "调整后 EBITDA 费用：": "same annual record.",
        "调整后 EBITDA 费用相对指引中值": "the deviation view of the same record.",
        "自由现金流：": "same annual record.",
        "自由现金流相对指引中值": "the deviation view of the same record.",
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
    "tjx": {
        # Two floors. The quarterly guidance record on EDGAR starts with the
        # FY2023 releases -- before that TJX gave its next-quarter pretax-margin
        # and comp guidance in the CFO's prepared remarks on the call, which is
        # not a filed document and this site does not read. The four ten-year
        # charts run on fiscal years, not quarters, and ten years of them is the
        # whole of `long_history`.
        "摊薄每股收益（近 16 季）": "the filed next-quarter EPS guidance record starts with "
                          "the FY2023 releases.",
        "税前利润率：": "same guidance record; earlier quarters guided it only on the call.",
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
        "三条产品线的分化": "the three-category split is a later presentation; the "
                     "2016-2017 releases group products differently.",
        "GAAP 毛利率降到": "gross margin is carried for the reviewed window.",
        "本季非 GAAP 营业利润率": "this chart pairs the quarterly series with two guided "
                          "points, so it runs on the reviewed window plus two.",
        "单季非 GAAP 营业利润率": "the threshold view of the same quarterly margin series, "
                          "which this file carries for the reviewed window.",
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
    "tsm": {
        "收入（本图仅近": "dollar band; the guided number runs US$6.1B to US$45.8B, so the "
                     "early bands collapse to a few pixels on a linear axis. The "
                     "scale-free deviation chart beside it carries all 42.",
        "HPC 占比（集中度）": "TSMC first reported the platform split in 2018Q1.",
        "HPC 从": "same disclosure limit, long-run version of the same series.",
        "2nm 占晶圆收入": "2nm sat inside the 'advanced' aggregate until 2025Q2.",
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

    def test_converted_pages_have_no_unexplained_short_axis(self) -> None:
        for slug, excuses in CONVERTED.items():
            short = {}
            for exhibit, year in self.timed[slug]:
                if year <= TARGET_YEAR:
                    continue
                title = exhibit["title"]
                matched = [key for key in excuses if key in title]
                self.assertTrue(
                    matched,
                    f"{slug} Exhibit {exhibit['n']} starts in {year} and nothing says why: "
                    f"{title[:60]}",
                )
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


if __name__ == "__main__":
    unittest.main()
