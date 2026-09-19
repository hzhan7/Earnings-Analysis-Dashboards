"""Checks for the SPGI page.

The page rests on claims a quarter roll can quietly invalidate, and each one is
pinned here rather than narrated:

* the guidance record is **annual**, not quarterly. S&P Global has never filed a
  quarterly outlook, so every band on this page is a fiscal year's revision path
  and the year's reported result must land on the vintage that settles it -- the
  *final* one. An actual that drifted onto an earlier vintage would claim the
  year was settled against a forecast made before it happened;
* the record's shape is the page's headline, and it is two-sided: adjusted
  diluted EPS has not landed below its final range, while GAAP diluted EPS on
  the same table has, repeatedly. The counts are recounted here from the series
  and held to what the page prints, so a bad parse cannot quietly soften either
  half and a roll cannot leave a stale count behind;
* an actual may only be placed where that metric actually carries a band.
  Free cash flow guidance starts with the FY2018 opening release, but FY2018-
  FY2020 give it in that release only -- their final vintage has no cash range
  -- and dropping those years' reported figures onto it would invent a
  settlement;
* `delivery_band` and `midpoint_deviation` both default to counting quarters.
  This page counts fiscal years, so the titles are checked for it -- a chart
  reading "10 季里" for a ten-year record is wrong in a way no arithmetic test
  would catch;
* Mobility is still a reportable segment in every filed statement. The spin-off
  took effect 2026-07-01, one day after the quarter this page reports, and the
  recast has not reached any filing. A test asserts the page still carries it,
  because the failure mode is someone "helpfully" removing it early;
* the segment and revenue-type disaggregations must still add back to filed
  consolidated revenue, and the fiscal fourth quarters are derived by
  subtraction, so a mis-stitch shows up as a sum that no longer closes.

One test exists because the page publishes a margin the company does not print.
The operating margin excluding disposition gains is computed as revenue minus
total expenses -- not as operating profit minus the gain -- because the filer
never tags the gain for a fiscal fourth quarter, and the second form would put a
hole in every Q4. The test pins that the two agree wherever the gain is filed.

A roll edits `series/spgi.json` and nothing else. What the quarter's release
printed is asserted from `_checks` (`SpgiChecksTest`); `SpgiRollTest` rolls the
series a quarter back and two forward and tampers each stamped block; and
`SpgiFindingsTest` forces each judgement true and then false and checks that the
words follow. What stays pinned by value is history a roll cannot move.
"""

from __future__ import annotations

import copy
import json
import re
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import spgi  # noqa: E402
from build.all import build_all, roster_payload  # noqa: E402
from build.board import cn_count, headroom  # noqa: E402
from build.spgi import STAGING_PATH, build_payload, operating_margin_ex_credits  # noqa: E402


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


# Title shapes of the exhibits a builder ref names, for tests that follow a
# 「见 Exhibit N」 to the chart it has to land on.
REF_TITLES = {
    "EX_Q_RATINGS": lambda title: title.startswith("Ratings 的两条腿："),
    "EX_L_RATINGS": lambda title: "季 Ratings 两条腿：" in title,
    "EX_ADJ_BAND": lambda title: title.startswith("调整后摊薄 EPS："),
    "EX_Q_ISSUANCE": lambda title: title.startswith("计费发行量 US$"),
}


TYPES = ("subscription", "non_subscription_transaction", "non_transaction",
         "asset_linked_fees", "sales_usage_royalties", "recurring_variable")
SEGMENTS = ("ratings", "indices", "energy", "market_intelligence", "mobility",
            "engineering_solutions")


class SpgiDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "spgi.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]
        cls.by_section = {
            section["id"]: section["exhibits"] for section in cls.payload["sections"]
        }
        cls.record = cls.source["annual_guidance_history"]
        cls.long = cls.source["long_history"]
        cls.financials = cls.source["financials"]
        cls.segments = cls.source["segments_usd_m"]
        cls.types = cls.source["revenue_by_type_usd_m"]
        cls.split = cls.source["ratings_revenue_split_usd_m"]

    # ── the series itself ────────────────────────────────────────────────────
    def test_every_series_in_a_block_has_one_value_per_quarter(self) -> None:
        for name, block, key in (("窗口", self.financials, "periods"),
                                 ("长序列", self.long, "quarters"),
                                 ("分部", self.segments, "quarters"),
                                 ("收入类型", self.types, "quarters"),
                                 ("Ratings 拆分", self.split, "quarters")):
            length = len(self.source["periods"] if key == "periods" else block[key])
            # `structural_break_*` describe the axis, not a value per quarter:
            # each is a list of break positions and their labels.
            metadata = {key, "derived_quarters", "quarters", "periods",
                        "structural_break_at", "structural_break_label"}
            for field, values in block.items():
                if not isinstance(values, list) or field in metadata:
                    continue
                with self.subTest(block=name, series=field):
                    self.assertEqual(len(values), length)

    def test_income_statement_identity_holds_each_quarter(self) -> None:
        """SPGI's statement is revenue − expenses + gain + equity = operating
        profit. The two credits are untagged in every fiscal fourth quarter, so
        the identity is only checkable where both are filed -- and there it has
        to close exactly."""
        financials = self.financials
        checked = 0
        for index, period in enumerate(self.source["periods"]):
            gain = financials["gain_on_dispositions_usd_m"][index]
            equity = financials["equity_income_usd_m"][index]
            if gain is None or equity is None:
                continue
            checked += 1
            with self.subTest(period=period):
                self.assertAlmostEqual(
                    financials["revenue_usd_m"][index]
                    - financials["total_expenses_usd_m"][index] + gain + equity,
                    financials["operating_income_usd_m"][index],
                    delta=0.51,
                )
        self.assertGreaterEqual(checked, 9)

    def test_quarterly_revenue_reconciles_with_the_filed_year(self) -> None:
        """Every fiscal fourth quarter is the filed year minus the filed nine
        months, so the only way to know the stitch is right is that the four
        quarters still add back to the annual figure the company printed."""
        quarterly = dict(zip(self.long["quarters"], self.long["revenue_usd_m"]))
        actuals = self.source["annual_actuals"]
        checked = 0
        for year, filed in zip(actuals["fiscal_years"], actuals["revenue_usd_m"]):
            quarters = [value for period, value in quarterly.items()
                        if period.endswith(str(year))]
            if len(quarters) != 4:
                continue
            checked += 1
            with self.subTest(year=year):
                # each leg is rounded to the million before it is added
                self.assertLessEqual(abs(sum(quarters) - filed), 1.0)
        # every filed year is covered by the long record, so every one is checked
        self.assertEqual(checked, len(actuals["fiscal_years"]))
        self.assertGreaterEqual(checked, 7)

    def test_six_revenue_types_add_back_to_filed_revenue(self) -> None:
        """The company discloses six revenue types in dollars and nets the
        intersegment elimination inside the non-transaction column, so the six
        gross lines less that elimination is consolidated revenue exactly."""
        revenue = dict(zip(self.long["quarters"], self.long["revenue_usd_m"]))
        # S&P Global files no fourth-quarter 10-Q, so every fiscal Q4 in the
        # backfilled era is "full year minus nine months" -- a subtraction of
        # two rounded figures, which can land a dollar out. That slack is given
        # only to those quarters, and only to the era that needed deriving: the
        # quarters the company printed directly still have to close exactly.
        derived_q4 = {"Q4 2018", "Q4 2019", "Q4 2020", "Q4 2021"}
        exact = 0
        for index, period in enumerate(self.types["quarters"]):
            gross = sum(self.types[name][index] for name in TYPES)
            slack = 1.01 if period in derived_q4 else 0.51
            with self.subTest(period=period):
                self.assertAlmostEqual(
                    gross - self.types["intersegment_elimination"][index],
                    revenue[period], delta=slack)
            if period not in derived_q4:
                exact += 1
        # and the loosened set stays small: only those four quarters are excused
        self.assertEqual(exact, len(self.types["quarters"]) - len(derived_q4))

    def test_segments_add_back_to_filed_revenue_and_operating_profit(self) -> None:
        revenue = dict(zip(self.long["quarters"], self.long["revenue_usd_m"]))
        operating = dict(zip(self.long["quarters"], self.long["operating_income_usd_m"]))
        for index, period in enumerate(self.segments["quarters"]):
            if period not in revenue:
                continue
            segment_revenue = sum((self.segments["revenue"][name][index] or 0)
                                  for name in SEGMENTS)
            segment_profit = sum((self.segments["operating_profit"][name][index] or 0)
                                 for name in SEGMENTS)
            with self.subTest(period=period, leg="revenue"):
                self.assertLessEqual(
                    abs(segment_revenue
                        + self.segments["intersegment_elimination"][index]
                        + (self.segments["corporate_revenue"][index] or 0)
                        - revenue[period]), 1.0)
            with self.subTest(period=period, leg="operating_profit"):
                self.assertLessEqual(
                    abs(segment_profit
                        - (self.segments["corporate_unallocated_expense"][index] or 0)
                        + (self.segments["equity_income"][index] or 0)
                        - operating[period]), 1.0)

    def test_ratings_two_legs_add_to_the_segment(self) -> None:
        segment = dict(zip(self.segments["quarters"], self.segments["revenue"]["ratings"]))
        checked = 0
        for index, period in enumerate(self.split["quarters"]):
            if period not in segment or segment[period] is None:
                continue
            checked += 1
            with self.subTest(period=period):
                self.assertLessEqual(
                    abs(self.split["transaction"][index]
                        + self.split["non_transaction"][index] - segment[period]), 1.0)
        self.assertGreaterEqual(checked, 30)

    def test_margin_ex_credits_matches_the_other_derivation_where_filed(self) -> None:
        """The page computes it as revenue − expenses, because the disposition
        gain is untagged in every fiscal fourth quarter. Where the gain *is*
        filed, that form and `operating profit − gain − equity` must agree."""
        margin = operating_margin_ex_credits(self.long)
        checked = 0
        for index, period in enumerate(self.long["quarters"]):
            gain = self.long["gain_on_dispositions_usd_m"][index]
            equity = self.long["equity_income_usd_m"][index]
            if gain is None or equity is None:
                continue
            checked += 1
            revenue = self.long["revenue_usd_m"][index]
            with self.subTest(period=period):
                self.assertAlmostEqual(
                    margin[index],
                    (self.long["operating_income_usd_m"][index] - gain - equity)
                    / revenue * 100,
                    delta=0.03)
        self.assertGreaterEqual(checked, 15)

    def test_the_disposition_gain_is_null_not_zero_where_untagged(self) -> None:
        """Writing 0.0 into an untagged quarter asserts a zero gain. 2025Q4 had
        roughly US$270M, and the margin chart would have drawn it as clean
        operating profit."""
        gains = self.long["gain_on_dispositions_usd_m"]
        missing = {period for period, value in zip(self.long["quarters"], gains)
                   if value is None}
        self.assertTrue(missing)
        # the invariant that forced the derivation: no fiscal fourth quarter
        # anywhere in the record carries a tagged disposition gain
        fourths = {period for period in self.long["quarters"]
                   if period.startswith("Q4 ")}
        self.assertTrue(fourths)
        self.assertTrue(fourths <= missing)

    # ── the annual guidance record ───────────────────────────────────────────
    def test_the_record_is_annual_and_covers_every_vintage(self) -> None:
        """Every fiscal year from FY2016 on, each with its slots in order and no
        gap -- so a roll that adds a vintage and forgets a column, or skips a
        revision, fails here rather than on the chart."""
        record = self.record
        length = len(record["vintages"])
        for key, values in record.items():
            if isinstance(values, list):
                with self.subTest(series=key):
                    self.assertEqual(len(values), length)
        years = sorted(set(record["fiscal_years"]))
        self.assertEqual(years[0], 2016)
        self.assertEqual(years, list(range(2016, years[-1] + 1)))
        for year in years:
            slots = [slot for fy, slot in zip(record["fiscal_years"], record["vintage_slots"])
                     if fy == year]
            with self.subTest(year=year):
                self.assertEqual(slots, ["initial", "q1", "q2", "q3"][:len(slots)])
                if year < years[-1]:
                    self.assertEqual(len(slots), 4)

    def test_each_vintage_was_published_inside_the_year_it_guides(self) -> None:
        """A full-year outlook is revised during the year it covers, so every
        filing date has to fall inside that fiscal year -- never after it, which
        would mean the row is reading a result back as its own forecast."""
        for year, filed, label in zip(self.record["fiscal_years"],
                                      self.record["filed"], self.record["vintages"]):
            with self.subTest(vintage=label):
                self.assertEqual(int(filed[:4]), year)

    def test_the_actual_lands_only_on_the_vintage_that_settles_the_year(self) -> None:
        """The year is settled against its *final* revision. An actual on an
        earlier vintage would silently make the record easier to clear."""
        record = self.record
        last = {}
        for index, year in enumerate(record["fiscal_years"]):
            last[year] = index
        for slot in ("adjusted_eps", "gaap_eps", "revenue_growth_pct",
                     "adjusted_fcf_usd_m", "adjusted_tax_pct"):
            placed = [index for index, value in enumerate(record[f"actual_{slot}"])
                      if value is not None]
            with self.subTest(metric=slot):
                self.assertTrue(placed)
                for index in placed:
                    self.assertEqual(index, last[record["fiscal_years"][index]])

    def test_no_actual_sits_on_a_vintage_that_has_no_band(self) -> None:
        """FY2018-FY2020 guided free cash flow in the opening release only, so
        their final vintage has no cash range. Landing those years' reported
        figures on it would invent a settlement that never happened."""
        record = self.record
        for slot, guide in (("adjusted_eps", "guide_adjusted_eps_lo"),
                            ("gaap_eps", "guide_gaap_eps_lo"),
                            ("revenue_growth_pct", "guide_revenue_growth_lo_pct"),
                            ("adjusted_fcf_usd_m", "guide_adjusted_fcf_lo_usd_m"),
                            ("adjusted_tax_pct", "guide_adjusted_tax_lo_pct")):
            for index, value in enumerate(record[f"actual_{slot}"]):
                if value is None:
                    continue
                with self.subTest(metric=slot, vintage=record["vintages"][index]):
                    self.assertIsNotNone(record[guide][index])

    def tally(self, lo: str, hi: str, actual: str) -> tuple[int, int, int]:
        above = inside = below = 0
        for low, high, value in zip(self.record[lo], self.record[hi], self.record[actual]):
            if value is None or low is None:
                continue
            if value > high:
                above += 1
            elif value < low:
                below += 1
            else:
                inside += 1
        return above, inside, below

    def test_the_record_is_two_sided_and_the_counts_are_asserted(self) -> None:
        """The page's headline finding: adjusted EPS has never missed its final
        range, while the GAAP number on the same table misses in most of the
        years that carry a GAAP range. Recounted here and held to every place
        the page prints it -- the counts were typed as 「七年里三次」 and stayed
        typed after the record reached back to FY2016.

        The two denominators differ on purpose. FY2016 has an adjusted range and
        no GAAP one -- the company said it could not reconcile the two "without
        unreasonable effort" -- so its reported GAAP EPS is deliberately absent
        from the record rather than sitting on a cell with no band."""
        adjusted = self.tally("guide_adjusted_eps_lo", "guide_adjusted_eps_hi", "actual_adjusted_eps")
        gaap = self.tally("guide_gaap_eps_lo", "guide_gaap_eps_hi", "actual_gaap_eps")
        finished, gaap_years = sum(adjusted), sum(gaap)
        self.assertEqual(adjusted[2], 0)
        self.assertGreater(2 * gaap[2], gaap_years)
        self.assertIn(f"{finished} 个已完结财年里，调整后摊薄 EPS 一次都没有跌破过", self.payload["headline"])
        self.assertIn(f"GAAP 摊薄 EPS 却跌破了 {gaap[2]} 次", self.payload["headline"])
        self.assertIn(f"{adjusted[0]} 年超出上限、{adjusted[1]} 年落在区间内、{adjusted[2]} 年跌破；"
                      f"GAAP EPS 在有 GAAP 指引的 {gaap_years} 年里跌破 {gaap[2]} 次", self.payload["brief"])
        band = self.by_section["settled"]
        self.assertTrue(any(ex["title"].startswith(
            f"GAAP 摊薄 EPS：{gaap_years} 个已完结年里 {gaap[0]} 年超出上限、{gaap[1]} 年落在区间内、"
            f"{gaap[2]} 年跌破下限") for ex in band))
        # FY2016 settles adjusted EPS and deliberately does not settle GAAP
        opening = self.record["vintages"].index("FY16 Q3")
        self.assertIsNotNone(self.record["actual_adjusted_eps"][opening])
        self.assertIsNone(self.record["actual_gaap_eps"][opening])
        self.assertIsNone(self.record["guide_gaap_eps_lo"][opening])
        self.assertEqual(finished - gaap_years, 1)

    def test_the_fcf_note_scopes_its_only_to_what_the_record_shows(self) -> None:
        """「这是记录里唯一一条经常做不到的指引」 and 「每股收益的指引几乎不失手」
        were written beside a GAAP EPS band that misses in most of its years.
        The note now names the other often-missed line and scopes the EPS claim
        to the adjusted number."""
        fcf = self.tally("guide_adjusted_fcf_lo_usd_m", "guide_adjusted_fcf_hi_usd_m",
                         "actual_adjusted_fcf_usd_m")
        gaap = self.tally("guide_gaap_eps_lo", "guide_gaap_eps_hi", "actual_gaap_eps")
        note = next(ex for ex in self.by_section["settled"]
                    if ex["title"].startswith("调整后自由现金流：") and ex["kind"] == "range_band")["note"]
        self.assertIn(f"{cn_count(sum(fcf))}个已完结财年里{cn_count(fcf[2])}年跌破下限", note)
        if 2 * fcf[2] >= sum(fcf) and 2 * gaap[2] >= sum(gaap):
            self.assertIn("这是记录里除 GAAP EPS 之外唯一一条经常做不到的指引", note)
        self.assertNotIn("<b>每股收益的指引几乎不失手", note)
        self.assertIn("调整后每股收益的指引几乎不失手", note)

    def test_the_opening_vintage_is_the_one_that_carries_information(self) -> None:
        """Eight of ten opening guidances were beaten, the single miss is still
        FY2022 -- the year the company withdrew guidance mid-year -- and FY2018
        is the one year the opening range was merely *met*.

        Extending the record to FY2016 did not overturn the finding; it added a
        third category to it. On the FY2019-start record every settled opening
        guidance was either beaten or missed, so "beaten + missed" covered the
        field and the test only had to count two things."""
        record = self.record
        settled = {}
        for index, value in enumerate(record["actual_adjusted_eps"]):
            if value is not None:
                settled[record["fiscal_years"][index]] = value
        beaten, missed = 0, []
        for index, slot in enumerate(record["vintage_slots"]):
            year = record["fiscal_years"][index]
            if slot != "initial" or year not in settled:
                continue
            high = record["guide_adjusted_eps_hi"][index]
            low = record["guide_adjusted_eps_lo"][index]
            if settled[year] > high:
                beaten += 1
            elif settled[year] < low:
                missed.append(year)
        converge = next(ex for ex in self.by_section["settled"] if ex["title"].startswith("实际结果相对"))
        opened = sum(1 for index, slot in enumerate(record["vintage_slots"])
                     if slot == "initial" and record["fiscal_years"][index] in settled)
        self.assertIn(f"开局那一档 {opened} 年里 {beaten} 年偏正", converge["title"])
        # FY2022 is history: the year guidance was withdrawn, the only year the
        # opening range was broken -- and the note says so only while it is
        self.assertEqual(missed, [2022])
        self.assertEqual(record["suspension"]["announced"], "2022-06-01")
        ratings = next(ex for ex in self.by_section["routine"] if ex["title"].endswith("没有塌陷过"))
        self.assertIn(f"{opened} 年里唯一一次开局指引被<b>跌破</b>的财年是 2022 年", ratings["note"])

    def test_the_opening_misses_are_every_year_below_the_midpoint(self) -> None:
        """「唯一低于开局指引的是 FY2018，而那一年正是公司自己撤回指引的那一年」:
        two years settled below their opening midpoint, and the withdrawal year
        was the other one. The note now lists each with its own deviation."""
        record = self.record
        converge = next(ex for ex in self.by_section["settled"] if ex["title"].startswith("实际结果相对"))
        dev = spgi.vintage_deviations(record)
        below = [(year, value) for year, value in zip(dev["years"], dev["initial"])
                 if value is not None and value < 0]
        self.assertGreaterEqual(len(below), 2)
        self.assertIn(f"低于开局指引中值的{cn_count(len(below))}年里", converge["note"])
        for year, value in below:
            with self.subTest(year=year):
                self.assertIn(f"{year} 差 {spgi.minus(value)}", converge["note"])
        self.assertNotIn("唯一低于开局指引的是 FY2018", converge["note"])
        self.assertNotIn("跌到整段记录的最低点", converge["note"])

    def test_every_backfilled_cash_cell_names_its_filing(self) -> None:
        """The FY2018-FY2022 cash cells were typed from the releases one by
        one; each keeps its release's accession and the sentence itself, and the
        sentence has to print the cell's own endpoints. The two settled cells
        name where their result was read."""
        record = self.record
        sources = record["guide_adjusted_fcf_sources"]
        for index, label in enumerate(record["vintages"]):
            if record["guide_adjusted_fcf_lo_usd_m"][index] is None or record["fiscal_years"][index] >= 2023:
                continue
            with self.subTest(vintage=label):
                self.assertIn(label, sources)
        for label, entry in sources.items():
            index = record["vintages"].index(label)
            with self.subTest(vintage=label):
                self.assertRegex(entry["accession"], r"^\d{10}-\d{2}-\d{6}$")
                printed = {round(float(x), 3) for x in re.findall(r"\$(\d+(?:\.\d+)?) billion", entry["quote"])}
                self.assertIn(round(record["guide_adjusted_fcf_lo_usd_m"][index] / 1000, 3), printed)
                self.assertIn(round(record["guide_adjusted_fcf_hi_usd_m"][index] / 1000, 3), printed)
                if record["filed_in_8k"][index]:
                    self.assertEqual(entry["filed"], record["filed"][index])
                actual = record["actual_adjusted_fcf_usd_m"][index]
                if actual is not None:
                    self.assertIn(f"${actual:,.0f}", entry["actual_source"])

    def test_a_point_guidance_is_never_recorded_as_a_range(self) -> None:
        """Adjusted free cash flow is written "approximately $5.2 billion" in
        some vintages and as a two-sided range in others; the form flag and the
        endpoints have to agree."""
        record = self.record
        for index, label in enumerate(record["vintages"]):
            form = record["guide_adjusted_fcf_form"][index]
            low = record["guide_adjusted_fcf_lo_usd_m"][index]
            high = record["guide_adjusted_fcf_hi_usd_m"][index]
            with self.subTest(vintage=label):
                if form is None:
                    self.assertIsNone(low)
                    continue
                self.assertEqual(form == "point", low == high)
        # and the deviation chart names every settled year guided to a point
        rows = spgi.final_rows(record, "guide_adjusted_fcf_lo_usd_m", "guide_adjusted_fcf_hi_usd_m",
                               "actual_adjusted_fcf_usd_m")
        points = [row for row in rows if row[1] == row[2]]
        note = next(ex for ex in self.by_section["settled"]
                    if ex["title"].startswith("调整后自由现金流相对指引中值的偏离"))["note"]
        for year, low, _, _ in points:
            with self.subTest(year=year):
                self.assertIn(f"FY{year}", note)
                self.assertIn(f"${low / 1000:g} billion", note)

    def test_the_one_unfiled_vintage_is_flagged(self) -> None:
        """FY2022's opening guidance came from an investor day and reaches EDGAR
        only as a recital inside a later 8-K. It is published, and marked."""
        record = self.record
        unfiled = [label for label, in_8k in zip(record["vintages"], record["filed_in_8k"])
                   if not in_8k]
        self.assertIn("FY22 初*", unfiled)
        self.assertEqual(record["fiscal_years"][record["vintages"].index("FY22 初*")], 2022)
        for label in unfiled:
            with self.subTest(vintage=label):
                self.assertTrue(label.endswith("*"))
        converge = next(ex for ex in self.by_section["settled"] if ex["title"].startswith("实际结果相对"))
        if len(unfiled) == 1:
            self.assertIn(f"{unfiled[0].split()[0]} 那一年的开局指引是唯一一档没有进入 8-K 的",
                          converge["note"])

    def test_the_mobility_rebase_is_marked_rather_than_smoothed(self) -> None:
        record = self.record
        at = record["basis_break_at"]
        # history: the first vintage on the new basis is FY2026's Q2 revision
        self.assertEqual(record["vintages"][at], "FY26 Q2†")
        self.assertIn("Mobility", record["basis_break_label"])
        band = next(ex for ex in self.by_section["settled"]
                    if ex["kind"] == "range_band" and "调整后摊薄 EPS" in ex["title"])
        self.assertEqual(band["break_at"], at)
        # the breaching bar is kept, not edited away
        self.assertEqual(band["lo"][at], 17.50)
        self.assertEqual(band["hi"][at], 17.75)
        self.assertAlmostEqual(band["lo"][at - 1], 19.40)
        # 「最右边那一档」 only while it is the rightmost one
        where = "最右边那一档" if at == len(record["vintages"]) - 1 else f"{record['vintages'][at]} 那一档"
        self.assertIn(f"<b>{where}是口径重设，不是下调。</b>", band["note"])

    def test_no_invented_bridge_across_the_rebase(self) -> None:
        """The company disclosed a pro forma FY2025 base and no FY2026 bridge.
        The page may quote the first -- the add-back is derived from it rather
        than stored beside it -- and must not derive the second."""
        record = self.record
        actuals = self.source["annual_actuals"]
        year = record["fiscal_years"][record["basis_break_at"]]
        base = actuals["adjusted_eps"][actuals["fiscal_years"].index(year - 1)]
        addback = base - record["proforma_base_adjusted_eps_usd"]
        self.assertNotIn("mobility_addback_adjusted_eps_usd", record)
        self.assertTrue(any(f"两者相差 US${addback:.2f}/股" in note for note in self.payload["notes"]))
        charts = [ex for ex in self.by_section["quarter_highlights"] if f"FY{year} 指引中值" in ex["title"]]
        if record["filed"][record["basis_break_at"]] == self.source["latest"]["release_date"]:
            self.assertEqual(len(charts), 1)
            self.assertIn("不发布任何自算的桥", charts[0]["note"])
            self.assertIn(f"两者相差 US${addback:.2f}", charts[0]["note"])
            self.assertIn(f"取自 {record['proforma_base_filed']} 的 {record['proforma_base_form']}",
                          charts[0]["src_extra"])
            # the 「−9.7%」 is new guidance against old guidance, not against the old base
            drop = spgi.pct_change(
                (record["guide_adjusted_eps_lo"][record["basis_break_at"]]
                 + record["guide_adjusted_eps_hi"][record["basis_break_at"]]) / 2,
                (record["guide_adjusted_eps_lo"][record["basis_break_at"] - 1]
                 + record["guide_adjusted_eps_hi"][record["basis_break_at"] - 1]) / 2)
            self.assertIn(f"直接比金色的旧指引，得到的那个「{spgi.minus(drop)}」", charts[0]["note"])
            self.assertNotIn("用新指引对旧基数", charts[0]["note"])
        else:
            self.assertEqual(charts, [])

    # ── the record is measured in years, not quarters ────────────────────────
    def test_every_guidance_chart_counts_fiscal_years(self) -> None:
        """`delivery_band` and `midpoint_deviation` both default to 「季」. This
        record is annual, and a title reading "7 季里" would be wrong in a way
        no arithmetic check would catch."""
        charts = [ex for ex in self.by_section["settled"]
                  if ex["kind"] in ("range_band", "grouped_bars")]
        self.assertGreaterEqual(len(charts), 9)
        annual = [ex for ex in charts if "已完结年" in ex["title"] or "年里" in ex["title"]]
        self.assertGreaterEqual(len(annual), 8)
        for exhibit in charts:
            with self.subTest(exhibit=exhibit["n"]):
                self.assertNotIn("已完结季", exhibit["title"])
                self.assertNotIn("季里", exhibit["title"])

    def test_the_page_states_the_record_is_not_ex_ante(self) -> None:
        """The final vintage is published with roughly ten of twelve months
        already banked, which is what makes "never missed" weaker than it reads."""
        bands = [ex for ex in self.by_section["settled"] if ex["kind"] == "range_band"]
        self.assertEqual(len(bands), 4)
        for exhibit in bands:
            with self.subTest(exhibit=exhibit["n"]):
                self.assertIn("进行途中", exhibit["note"])
        self.assertTrue(any("时效性" in note for note in self.payload["notes"]))

    # ── Mobility is still consolidated ───────────────────────────────────────
    def test_mobility_is_still_a_reportable_segment(self) -> None:
        """The spin took effect 2026-07-01, one day after this quarter ended, so
        every filed statement still consolidates it. Removing it early would
        make this page disagree with the filings it cites."""
        if self.source["period_ends"][-1] >= "2026-07-01":
            return  # from Q3 2026 the recast is the filed basis and this no longer applies
        mobility = self.segments["revenue"]["mobility"]
        self.assertIsNotNone(mobility[-1])
        self.assertGreater(mobility[-1], 0)
        self.assertEqual(self.segments["quarters"][-1], self.source["periods"][-1])
        self.assertTrue(any("2026-07-01" in note for note in self.payload["notes"]))
        self.assertTrue(any("终止经营" in note for note in self.payload["notes"]))
        self.assertTrue(any(f"本季收入 US${mobility[-1]:,.0f}M" in note for note in self.payload["notes"]))

    def test_the_long_series_carries_both_breaks(self) -> None:
        """Two now, not one: the pension re-presentation at 2017Q1 as well as
        the merger at 2022Q1. Both are discontinuities in the drawn line that
        no reader could infer from the shape alone."""
        self.assertEqual([self.long["quarters"][i]
                          for i in self.long["structural_break_at"]],
                         ["Q1 2017", "Q1 2022"])
        margin = next(ex for ex in self.by_section["routine"]
                      if "营业利润率" in ex["title"])
        self.assertEqual(margin["break_at"], self.long["structural_break_at"])
        self.assertEqual(len(margin["break_label"]),
                         len(self.long["structural_break_at"]))
        revenue = next(ex for ex in self.by_section["routine"] if ex["kind"] == "gs_bar")
        self.assertIn("并表", revenue["title"])

    def test_the_three_places_that_describe_the_spike_agree_with_the_data(self) -> None:
        """A margin spike caused by one disposal is described in three notes.

        All three used to hard-code 2022Q1 / 79.2% / US$1,344M. That was right
        for a record starting in 2017 and wrong the moment it reached 2016 --
        the J.D. Power sale put a bigger spike in 2016Q3 -- and the failure mode
        was the nasty one: the sentence derived its quarter and its percentage
        but not its dollar figure or its explanation, so it re-pointed itself at
        2016Q3 and went on attributing an IHS-Markit-era antitrust divestiture
        to it. Half a derived sentence is worse than none.
        """
        from build.spgi import disposition_spike
        spike = disposition_spike(self.long)
        # the spike is what the data says it is, not what a note says
        self.assertEqual(spike["quarter"], "Q3 2016")
        self.assertAlmostEqual(spike["gain"], 722.0, delta=0.5)

        prose = [ex.get("note") or "" for section in self.payload["sections"]
                 for ex in section["exhibits"]]
        prose += list(self.payload["notes"])
        # only the notes that actually point at the spike quarter -- other notes
        # mention a disposition gain for the quarter they are about, which is a
        # different (and correct) number
        mentions = [text for text in prose
                    if spike["label"] in text and "处置收益" in text]
        self.assertGreaterEqual(len(mentions), 3)
        amount = f"US${spike['gain']:,.0f}M"
        for text in mentions:
            with self.subTest(note=text[:40]):
                self.assertIn(amount, text)
                self.assertNotIn("1,344", text)

    def test_the_pre_2017_basis_is_carried_but_declared(self) -> None:
        """FY2016 was never re-presented under ASU 2017-07, so those four
        quarters can only exist on the superseded basis. This page used to floor
        the series at 2017Q1 for that reason. The floor is gone, but only
        because the step is now measured rather than feared: the 2018Q1 10-Q
        restated each of 2017's first three quarters by exactly $9.0M, so the
        discontinuity has a known size, is drawn as a break, and is stated in
        prose. Extending onto an undeclared basis change would still be wrong --
        what changed is that it is declared."""
        self.assertEqual(self.long["quarters"][0], "Q1 2016")
        self.assertEqual(self.long["quarters"][self.long["structural_break_at"][0]],
                         "Q1 2017")
        note = self.long["basis_break_2016_2017"]
        self.assertIn("9.0", note)
        self.assertIn("ASU 2017-07", note)
        # and the reader of the page, not just of the series file, is told
        self.assertTrue(any("养老金" in n for n in self.payload["notes"]),
                        "the pension basis break is not stated on the page")

    # ── thresholds ───────────────────────────────────────────────────────────
    def test_headroom_bars_reproduce_the_thresholds(self) -> None:
        for section, block, key in (("settled", "prior_kpi_settlement", "actual"),
                                    ("next_quarter", "next_kpi", "current")):
            entries = spgi.with_current(self.source, self.source[block], key)
            chart = next(ex for ex in self.by_section[section]
                         if ex["kind"] == "diverging_bars")
            with self.subTest(section=section):
                self.assertEqual(chart["xlabels"], [e["metric"] for e in entries])
                self.assertEqual(
                    chart["values"],
                    [round(headroom(e["direction"], e["threshold"], e[key]), 1)
                     for e in entries])
                # the value is read from the series, never typed into the block
                for entry in self.source[block]["quantified"]:
                    self.assertNotIn(key, entry)
                    self.assertIn("reads", entry)

    def test_the_withdrawn_threshold_is_retired_rather_than_settled(self) -> None:
        """Its basis was replaced mid-quarter by the spin-off, so it cannot be
        resolved against the new guidance at all."""
        settlement = self.source["prior_kpi_settlement"]
        self.assertNotIn("FY2026 调整后 EPS 指引中值",
                         [entry["metric"] for entry in settlement["quantified"]])
        self.assertTrue(any("无法结算" in text for text in settlement["retired"]))
        chart = next(ex for ex in self.by_section["settled"]
                     if ex["kind"] == "diverging_bars")
        self.assertIn("无法结算", chart["note"])

    def test_every_tracked_metric_with_a_series_gets_its_own_chart(self) -> None:
        """The overview bar says which line broke; only the per-metric chart
        says how it got there.

        Each tracked reading is drawn once: section one draws what last
        quarter's note settled, section three the rest of what points forward,
        and both overview bars say where every other reading went. That is
        worked out from the builder's own table, because the typed list sent
        「Ratings 非交易性收入同比」 to a section-three chart that never existed."""
        def number_of(ref: str) -> int:
            return next(ex["n"] for ex in self.exhibits if REF_TITLES[ref](ex["title"]))

        drawn = set()
        for section, block in (("settled", "prior_kpi_settlement"), ("next_quarter", "next_kpi")):
            bar = next(ex for ex in self.by_section[section] if ex["kind"] == "diverging_bars")
            here = [ex["title"] for ex in self.by_section[section]]
            for entry in self.source[block]["quantified"]:
                name = spgi.short_name(entry["metric"])
                stem = entry["metric"].split("（")[0].strip()
                with self.subTest(section=section, metric=name):
                    if entry["reads"] in spgi.CHART_BUILDERS:
                        owners = [ex for ex in self.exhibits
                                  if ex["title"].startswith(stem) and "vs 阈值" in ex["title"]]
                        self.assertEqual(len(owners), 1, [ex["title"] for ex in owners])
                        drawn.add(entry["reads"])
                        if owners[0]["title"] not in here:
                            self.assertIn(f"「{name}」", bar["note"])
                            if section == "settled":
                                self.assertIn(f"Exhibit {owners[0]['n']}", bar["note"])
                    else:
                        words, refs = spgi.LEVELS_DRAWN_AT[entry["reads"]]
                        where = " 与 ".join(f"Exhibit {number_of(ref)}" for ref in refs)
                        self.assertIn(f"「{name}」{words} {where}。", bar["note"])
        self.assertGreaterEqual(len(drawn), 7)
        settled = next(ex for ex in self.by_section["settled"] if ex["kind"] == "diverging_bars")
        self.assertNotIn("它们各自的历史图在第三节向前指", settled["note"])

    # ── page shape and boundary ──────────────────────────────────────────────
    def test_page_is_chart_led(self) -> None:
        self.assertGreaterEqual(len(self.exhibits), 28)
        self.assertEqual(self.payload["summary"]["blocks"], [])
        for exhibit in self.exhibits:
            with self.subTest(exhibit=exhibit["n"]):
                self.assertTrue(exhibit["note"])
                self.assertTrue(exhibit["src_extra"])

    def test_section_order_matches_how_the_note_is_used(self) -> None:
        self.assertEqual(
            [section["id"] for section in self.payload["sections"]],
            ["settled", "quarter_highlights", "next_quarter", "routine"])

    def test_exhibit_numbers_are_assigned_in_render_order(self) -> None:
        self.assertEqual([ex["n"] for ex in self.exhibits],
                         list(range(2, 2 + len(self.exhibits))))
        for exhibit in self.exhibits:
            with self.subTest(exhibit=exhibit["n"]):
                self.assertNotIn("{EX_", json.dumps(exhibit, ensure_ascii=False))

    def test_every_gs_bar_carries_its_right_hand_series(self) -> None:
        """`charts.js` treats `yoy` as optional and falls back to a twelve-period
        moving average, which is NaN on a short axis and silently drops the
        line. Every published gs_bar on this site passes it."""
        for exhibit in self.exhibits:
            if exhibit["kind"] != "gs_bar":
                continue
            with self.subTest(exhibit=exhibit["n"]):
                self.assertIn("yoy", exhibit)
                self.assertTrue(exhibit["yoy"]["values"])

    def test_escaped_slots_carry_no_markup(self) -> None:
        """`title`, `subtitle`, `headline` and `tracker` are written with
        `textContent`, and the notes and section descriptions run through
        `esc()`. A `<b>` in any of them reaches the reader as characters."""
        for field in ("title", "subtitle", "headline", "tracker"):
            with self.subTest(field=field):
                self.assertNotRegex(self.payload[field], r"<[^>]+>")
        for index, note in enumerate(self.payload["notes"]):
            with self.subTest(note=index):
                self.assertNotRegex(note, r"<[^>]+>")
        for section in self.payload["sections"]:
            with self.subTest(section=section["id"]):
                self.assertNotRegex(section["description"], r"<[^>]+>")

    def test_spgi_is_not_in_the_cross_page_capex_table(self) -> None:
        """The shared table is hyperscaler capex into foundry wafers; S&P Global
        sits outside that chain and must not be spliced into it."""
        table = next(t for t in self.payload["tables"] if "AI capex" in t["title"])
        self.assertNotIn("SPGI", " ".join(table["headers"]))
        for row in table["rows"]:
            self.assertNotIn("SPGI", " ".join(str(cell) for cell in row))

    def test_the_shared_capex_table_is_explained_rather_than_left_bare(self) -> None:
        """It is published byte-identically on every page, so a reader opening
        the drawer on a ratings company needs to be told why a wafer table is
        there."""
        self.assertTrue(any("跨页对照" in note and "不是对" in note
                            for note in self.payload["notes"]))

    def test_market_expectation_is_labelled_and_unattributed(self) -> None:
        consensus = self.source["market_expectation"]
        self.assertTrue(consensus["as_of"])
        self.assertIn("市场预期", consensus["basis"])
        blob = json.dumps(self.payload, ensure_ascii=False).lower()
        for broker in ("zacks", "marketbeat", "seeking alpha", "investing.com",
                       "benzinga", "stifel", "benchmark", "bloomberg",
                       "visible alpha", "factset"):
            with self.subTest(broker=broker):
                self.assertNotIn(broker, blob)
        for banned in ("加仓", "减仓", "买入", "卖出", "撤销条件", "概率加权",
                       "forward p/e", "ev/revenue", "terminal multiple"):
            with self.subTest(term=banned):
                self.assertNotIn(banned, blob)

    def test_sources_are_official_http_links(self) -> None:
        for source in self.source["sources"]:
            with self.subTest(label=source["label"]):
                host = urlparse(source["url"]).netloc
                self.assertTrue(host.endswith("sec.gov") or host.endswith("spglobal.com"),
                                host)

    def test_published_payload_roster_and_shell(self) -> None:
        published = js_payload(ROOT / "data" / "spgi.js", "window.DASH")
        self.assertEqual(published, self.payload)
        roster = js_payload(ROOT / "data" / "roster.js", "window.ROSTER")
        self.assertEqual(roster, roster_payload(build_all()))
        shell = (ROOT / "spgi" / "index.html").read_text(encoding="utf-8")
        self.assertIn("../data/spgi.js", shell)
        self.assertNotIn("../data/tsm.js", shell)

    def test_the_roster_group_resolves_to_a_declared_group(self) -> None:
        """`page.js` builds the company dropdown as `groups.forEach` into a map
        keyed by `ENTRIES.group`. A key with no matching group makes the company
        vanish from the nav on every page, with every test still green."""
        roster = js_payload(ROOT / "data" / "roster.js", "window.ROSTER")
        keys = {group["key"] for group in roster["groups"]}
        self.assertIn(self.payload["company"]["group"], keys)
        item = next(i for i in roster["items"] if i["slug"] == "spgi")
        self.assertEqual(item["group"], self.payload["company"]["group"])

    def test_home_page_carries_the_new_company(self) -> None:
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="spgi/"', home)
        self.assertIn(self.payload["latest"]["disclosed_period_label"], home)
        self.assertIn(self.payload["latest"]["release_date"], home)
        roster = js_payload(ROOT / "data" / "roster.js", "window.ROSTER")
        group = next(g for g in roster["groups"]
                     if g["key"] == self.payload["company"]["group"])
        # the hub heading is hand-written and reads no payload, so nothing else
        # would notice it drifting from the group label the nav uses
        self.assertIn(f'<h2 class="hubgrp">{group["label"]}</h2>', home)
        self.assertEqual(home.count('class="hcard"'), len(roster["items"]))

    def test_public_files_exclude_private_and_broker_material(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [ROOT / "series" / "spgi.json", ROOT / "data" / "spgi.js"]
        )
        for banned in ("OneDrive", "/Users/", ".pptx", "transcript.pdf",
                       "Seeking Alpha", "Zacks", "MarketBeat", "Stifel", "Benchmark"):
            with self.subTest(term=banned):
                self.assertNotIn(banned, text)

    def test_no_payload_string_trips_the_infinity_guard(self) -> None:
        """`payload_guard` rejects the stems nan/inf/infinity, and its error
        names only the payload key. A source URL carrying `financial-info` would
        fail the build with a message that reads like a data bug."""
        pattern = re.compile(
            r"(?<![A-Za-z_])(?:nan|infinity|inf)(?:[A-Za-z]{1,2})?(?![A-Za-z_])",
            re.IGNORECASE)
        blob = json.dumps(self.payload, ensure_ascii=False)
        self.assertIsNone(pattern.search(blob))


    # ── sentences that used to be typed and are now read off the series ─────
    def test_the_vintage_count_and_span_are_read_from_the_record(self) -> None:
        """「FY2019–FY2026 的 43 档」 in the headline and 「31 档 … FY2019–FY2026」
        on the audit table both survived the record's extension to FY2016."""
        record = self.record
        span = f"FY{record['fiscal_years'][0]}–FY{record['fiscal_years'][-1]}"
        self.assertIn(f"{span} 的 {len(record['vintages'])} 档 vintage", self.payload["headline"])
        self.assertIn(f"全部 {len(record['vintages'])} 档 vintage 与被它们指引的那一年（{span}）",
                      self.payload["tables"][0]["title"])
        self.assertEqual(len(self.payload["tables"][0]["rows"]), len(record["vintages"]))

    def test_the_segment_gap_is_the_intersegment_revenue(self) -> None:
        """The two segment bases differ by the intersegment revenue, which the
        elimination line carries: US$53M this quarter (Ratings 46, Market
        Intelligence 4, Indices 3 in the 10-Q), not the US$45M the notes said."""
        gap = -self.segments["intersegment_elimination"][-1]
        segment = next(ex for ex in self.by_section["quarter_highlights"] if ex["title"].startswith("本季"))
        self.assertIn(f"两者本季相差 US${gap:,.0f}M", segment["note"])
        self.assertTrue(any(f"两种口径本季相差 US${gap:,.0f}M" in n for n in self.payload["notes"]))
        self.assertNotIn("US$45M", json.dumps(self.payload, ensure_ascii=False))

    def test_the_identity_sentences_name_what_closes(self) -> None:
        """「五条分部收入加上分部间抵销恒等于申报的合并收入」 does not close: the
        identity needs Engineering Solutions (2022Q1-2023Q2) and 2018's corporate
        revenue too, and only then is the largest residual US$1M. The revenue-type
        note checked 「18 个季度」 on a series of 34."""
        check = spgi.segment_identity(self.source)
        self.assertEqual(check["checked"], len(self.segments["quarters"]))
        self.assertLessEqual(check["worst"], 1.0)
        self.assertIn("engineering_solutions", check["others"])
        segment = next(ex for ex in self.by_section["quarter_highlights"] if ex["title"].startswith("本季"))
        self.assertIn(f"本页 {check['checked']} 个季度逐季核对过", segment["note"])
        self.assertIn("Engineering Solutions", segment["note"])
        self.assertIn("公司层收入", segment["note"])
        self.assertNotIn("五条分部收入加上分部间抵销恒等于", segment["note"])
        types = next(ex for ex in self.by_section["routine"] if ex["title"].startswith("六条申报收入类型"))
        self.assertIn(f"本页 {len(self.types['quarters'])} 个季度逐季核对过", types["note"])

    def test_the_trough_is_the_drawdown_trough(self) -> None:
        """The brief printed min(transaction) -- 2016Q1's US$225M -- as 「2022Q3
        只有」. The 2022 trough is the bottom of the fall from the 2020 peak."""
        peak, trough, fall = spgi.deepest_fall(self.split["transaction"])
        label = spgi.year_quarter(self.split["quarters"][trough])
        value = f"US${self.split['transaction'][trough]:,.0f}M"
        self.assertIn(f"而它在 {label} 只有 {value}", self.payload["brief"])
        ratings = next(ex for ex in self.by_section["quarter_highlights"] if ex["title"].startswith("Ratings 的两条腿"))
        self.assertIn(f"而它在 {label} 曾经只有 {value}", ratings["note"])
        self.assertNotEqual(self.split["transaction"][trough], min(self.split["transaction"]))

    def test_the_first_quarter_seasonality_is_counted(self) -> None:
        """「每年第一季度都是四季里最低的一档」: in 2017 the second quarter was lower."""
        capital = self.source["capital_allocation_usd_m"]
        for values, section, words in (
                (spgi.free_cash_flow(self.source), "next_quarter", "第一季度是四季里最低的一档"),
                (capital["operating_cash_flow"], "quarter_highlights", "第一季度的经营现金流")):
            full, low = spgi.q1_low_years(capital["quarters"], values)
            note = " ".join(ex["note"] for ex in self.by_section[section])
            with self.subTest(section=section):
                self.assertIn(words, note)
                if len(low) < len(full):
                    self.assertIn(f"{cn_count(len(full))}个完整年份里有{cn_count(len(low))}年", note)
                    for year in set(full) - set(low):
                        self.assertIn(f"{year}", note)
        self.assertNotIn("每年第一季度都是四季里最低的一档", json.dumps(self.payload, ensure_ascii=False))

    def test_the_revenue_type_window_is_named_from_the_series(self) -> None:
        """「窗口从 2022Q1 开始」 on a chart that starts at 2018Q1, and 「订阅稳定在
        五成上下」 on a share that ran from 37.6% to 57.9%."""
        chart = next(ex for ex in self.by_section["routine"] if ex["title"].startswith("六条申报收入类型"))
        self.assertIn(f"窗口从 {spgi.year_quarter(self.types['quarters'][0])} 开始", chart["note"])
        share = spgi.subscription_share(self.types)
        self.assertIn(f"订阅在 {min(share):.1f}%–{max(share):.1f}% 之间", chart["title"])
        self.assertNotIn("五成上下", chart["title"])

    def test_the_pension_step_is_measured(self) -> None:
        """9.0 on quarterly revenue of US$1.3-1.5B moves the 2016 margins by
        0.6-0.7pp, not 「0.6–1.8pp」."""
        shift = self.long["pension_restatement_per_quarter_usd_m"]
        year = str(self.long["pension_unrestated_year"])
        moved = [shift / r * 100 for q, r in zip(self.long["quarters"], self.long["revenue_usd_m"])
                 if q.endswith(year)]
        self.assertEqual(len(moved), 4)
        margin = next(ex for ex in self.by_section["routine"] if "季营业利润率" in ex["title"])
        self.assertIn(f"每季 {shift:.1f}，对营业利润率的影响 {min(moved):.1f}–{max(moved):.1f}pp", margin["note"])
        self.assertIn(f"{shift:.1f}", self.long["basis_break_2016_2017"])

    def test_the_page_prints_no_markdown(self) -> None:
        """Exhibit notes are innerHTML: `**年度**` reached the reader as asterisks."""
        self.assertNotIn("**", json.dumps(self.payload, ensure_ascii=False))

    def test_the_dividend_sentence_counts_the_years(self) -> None:
        """「逐季缓慢抬升」: quarterly dividends fell quarter on quarter 21 times
        in 41, and FY2024's total was below FY2023's."""
        capital = self.source["capital_allocation_usd_m"]
        full, _ = spgi.q1_low_years(capital["quarters"], capital["dividends"])
        annual = {year: sum(capital["dividends"][capital["quarters"].index(f"Q{n} {year}")] for n in (1, 2, 3, 4))
                  for year in full}
        fell = [year for year in full[1:] if annual[year] < annual[year - 1]]
        note = next(ex for ex in self.by_section["routine"] if "自由现金流与股东回报" in ex["title"])["note"]
        self.assertIn(f"全年分红从 FY{full[0]} 的 US${annual[full[0]]:,.0f}M 走到 "
                      f"FY{full[-1]} 的 US${annual[full[-1]]:,.0f}M", note)
        for year in fell:
            self.assertIn(f"FY{year}", note)
        self.assertNotIn("逐季缓慢抬升", note)

    def test_the_sources_open_the_documents_they_name(self) -> None:
        """The withdrawal 8-K used to open EDGAR's filing list."""
        for source in self.source["sources"]:
            if any(form in source["label"] for form in ("10-Q", "10-K", "8-K")):
                with self.subTest(label=source["label"]):
                    self.assertIn("/Archives/edgar/data/64040/", source["url"])

    def test_the_deviation_notes_describe_their_own_bars(self) -> None:
        """「柱子全部为正，而且长度在收敛」 under a chart with a negative FY18 bar,
        and 「最深的一根出现在 FY2023」 under one whose deepest is FY17."""
        adjusted = spgi.final_deviations(self.record, "guide_adjusted_eps_lo", "guide_adjusted_eps_hi",
                                         "actual_adjusted_eps")
        gaap = spgi.final_deviations(self.record, "guide_gaap_eps_lo", "guide_gaap_eps_hi", "actual_gaap_eps")
        adj_note = next(ex for ex in self.by_section["settled"]
                        if ex["title"].startswith("调整后摊薄 EPS相对指引中值"))["note"]
        gaap_note = next(ex for ex in self.by_section["settled"]
                         if ex["title"].startswith("GAAP 摊薄 EPS相对指引中值"))["note"]
        negative = [(year, value) for year, value in adjusted if value <= 0]
        if negative:
            self.assertNotIn("柱子全部为正", adj_note)
            for year, value in negative:
                self.assertIn(f"{year} 为 {spgi.minus(value)}", adj_note)
        deepest = min(gaap, key=lambda row: row[1])
        if deepest[0] != "FY23":
            self.assertNotIn("最深的一根出现在 FY2023", gaap_note)
            self.assertIn(f"仅次于 FY20{deepest[0][2:]}", gaap_note)

    def test_the_empty_gaap_cells_are_all_named(self) -> None:
        """The list of vintages with an adjusted range and no GAAP one left out
        FY2016's four."""
        note = next(ex for ex in self.by_section["settled"]
                    if ex["title"].startswith("GAAP 摊薄 EPS：") and ex["kind"] == "range_band")["note"]
        words = spgi.empty_gaap_words(self.record)
        self.assertIn(f"另有几格是空的：{words}，", note)
        for year, adjusted, gaap in zip(self.record["fiscal_years"], self.record["guide_adjusted_eps_lo"],
                                        self.record["guide_gaap_eps_lo"]):
            if adjusted is not None and gaap is None:
                self.assertIn(f"FY{year} ", words)

    def test_the_filing_months_are_read_from_the_record(self) -> None:
        """「2 月、4-5 月…」: FY2022's opening range was given on 2022-03-01."""
        months = spgi.vintage_months(self.record)
        self.assertTrue(months.startswith("2-3 月"))
        band = next(ex for ex in self.by_section["settled"] if ex["kind"] == "range_band")
        self.assertIn(f"分别发布在该年的 {months}", band["note"])
        self.assertTrue(any(f"分别发布在该财年的 {months}" in n for n in self.payload["notes"]))

    def test_the_payout_target_is_the_companys_current_wording(self) -> None:
        """「把约 85% 的调整后自由现金流返还给股东」 is in no filing the page cites;
        the 2026 releases say 「100% or more」 and then 「more than $7 billion」."""
        note = next(ex for ex in self.by_section["next_quarter"]
                    if ex["title"].startswith("单季股东回报"))["note"]
        self.assertNotIn("85%", note)
        story = self.source.get("quarter_story") or {}
        if story.get("payout_target"):
            self.assertIn("「return 100% or more of adjusted Free Cash Flow」", note)
            self.assertIn(self.record["filed"][-1], note)

    def test_the_issuance_note_counts_its_quarters(self) -> None:
        """「那条 35 季的收入线」 was the Ratings split before it reached 2016."""
        issuance = self.source["billed_issuance_usd_bn"]
        note = next(ex for ex in self.by_section["quarter_highlights"]
                    if ex["title"].startswith("计费发行量 US$"))["note"]
        self.assertIn(f"那条 {len(self.split['quarters'])} 季的收入线", note)
        self.assertIn(f"其余{cn_count(len(issuance['quarters']) - len(issuance['derived_quarters']))}季", note)
        threshold = next(ex for ex in self.by_section["next_quarter"] if ex["title"].startswith("计费发行量 vs"))
        self.assertIn(f"窗口只有 {len(issuance['quarters'])} 季", threshold["note"])

    def test_the_only_one_claims_are_counted(self) -> None:
        """Two 「唯一」 claims the page's own charts contradicted: ETF AUM is not
        the only quantity the company does not control (billed issuance follows
        the bond window), and the share threshold is not the only one where
        lower is safer (the payout ratio is another)."""
        aum = next(ex for ex in self.by_section["routine"] if ex["title"].startswith("跟踪 S&P 指数"))
        self.assertNotIn("唯一一条不由公司经营决定的量", aum["note"])
        self.assertIn("涨到原来的", aum["title"])
        share = next(ex for ex in self.by_section["next_quarter"] if ex["title"].startswith("交易性收入占"))
        downs = [spgi.short_name(e["metric"]) for e in self.source["next_kpi"]["quantified"]
                 if e["direction"] == "down" and e["reads"] != "transaction_share"]
        for name in downs:
            self.assertIn(f"「{name}」", share["note"])

    def test_the_cash_flow_line_count_is_the_series(self) -> None:
        """「六条现金流线」 against a series that carries five."""
        lines = [key for key, values in self.source["capital_allocation_usd_m"].items()
                 if key != "quarters" and isinstance(values, list)]
        self.assertEqual(sorted(lines), sorted(spgi.CASH_FLOW_LINES))
        self.assertTrue(any(f"{cn_count(len(lines))}条现金流线全部残差为零" in n for n in self.payload["notes"]))


def exhibits_of(payload: dict) -> list[dict]:
    return [ex for section in payload["sections"] for ex in section["exhibits"]]


def own_text(payload: dict) -> str:
    """Everything the page says, less the cross-page table every page carries."""
    own = dict(payload, tables=[t for t in payload["tables"] if "AI capex" not in t["title"]])
    return json.dumps(own, ensure_ascii=False)


QUARTER_BLOCKS = ("prior_kpi_settlement", "next_kpi", "quarter_figures", "quarter_story")
QUARTERLY = ("long_history", "capital_allocation_usd_m", "ratings_revenue_split_usd_m",
             "revenue_by_type_usd_m", "segments_usd_m", "billed_issuance_usd_bn", "indices_kpi")
PLACEHOLDER = r"\{[a-z_]+\}"


def aligned(s: dict) -> list[tuple[dict, str, str]]:
    """(container, key, kind) for every list that runs along a quarter axis."""
    seen, out = set(), []

    def add(container, key, kind):
        if (id(container), key) not in seen:
            seen.add((id(container), key))
            out.append((container, key, kind))

    n = len(s["periods"])
    add(s, "periods", "label")
    add(s, "period_ends", "end")
    for key, values in s["financials"].items():
        if isinstance(values, list) and len(values) == n:
            add(s["financials"], key, "value")
    for name in QUARTERLY:
        block = s[name]
        axes = [key for key in ("quarters", "etf_aum_quarters") if key in block]
        for axis in axes:
            length = len(block[axis])
            add(block, axis, "label")
            for key, values in block.items():
                if key in axes:
                    continue
                if isinstance(values, list) and len(values) == length:
                    add(block, key, "value")
                elif isinstance(values, dict):
                    for inner, series in values.items():
                        if isinstance(series, list) and len(series) == length:
                            add(values, inner, "value")
    return out


RELEASE_DAY = {1: "04-28", 2: "07-28", 3: "10-28"}
QUARTER_END = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}


def release_words(label: str) -> str:
    quarter, year = label.split()
    return f"S&P Global {year} 年第{'一二三四'[int(quarter[1]) - 1]}季度业绩新闻稿（8-K EX-99.1）"


def rolled_back(staging: dict) -> dict:
    """The series one quarter earlier: every quarterly array loses its last
    cell, the open year loses its latest vintage, and the quarter's own blocks
    go. The Q1 2026 figures this leaves are the filed ones."""
    s = copy.deepcopy(staging)
    current = s["periods"][-1]
    for container, key, _ in aligned(s):
        container[key] = container[key][:-1]
    g = s["annual_guidance_history"]
    n = len(g["vintages"])
    for key, values in g.items():
        if isinstance(values, list) and len(values) == n:
            g[key] = values[:-1]
    if g["basis_break_at"] is not None and g["basis_break_at"] >= n - 1:
        g["basis_break_at"] = None
    for key in ("_checks",) + QUARTER_BLOCKS:
        s.pop(key, None)
    label = s["periods"][-1]
    s["latest"] = dict(s["latest"], period=label, period_end=s["period_ends"][-1],
                       release_date=g["filed"][-1])
    s["sources"] = ([{"label": release_words(label),
                      "url": "https://www.sec.gov/Archives/edgar/data/64040/000006404026000019/"
                             "spgi1q2026-earningsrelease.htm"}]
                    + [src for src in s["sources"]
                       if not src["label"].startswith(release_words(current)[:-12])
                       and "10-Q" not in src["label"]])
    return s


def rolled_forward(staging: dict) -> dict:
    """The series one quarter later with made-up figures. A fourth quarter's
    release settles the open year on its last vintage and opens the next."""
    s = copy.deepcopy(staging)
    last = s["periods"][-1]
    quarter, year = int(last[1]), int(last[-4:])
    quarter, year = (1, year + 1) if quarter == 4 else (quarter + 1, year)
    label = f"Q{quarter} {year}"
    end = f"{year}-{QUARTER_END[quarter]}"
    release = f"{year}-{RELEASE_DAY[quarter]}" if quarter < 4 else f"{year + 1}-02-10"
    for container, key, kind in aligned(s):
        values = container[key]
        if kind == "label":
            values.append(label)
        elif kind == "end":
            values.append(end)
        else:
            values.append(None if values[-1] is None else values[-1] * 1.01)
    g = s["annual_guidance_history"]
    n = len(g["vintages"])
    lists = [key for key, values in g.items() if isinstance(values, list) and len(values) == n]
    open_year = max(g["fiscal_years"])

    def add_vintage(fiscal_year, slot, name, scale):
        for key in lists:
            value = g[key][-1]
            if key == "vintages":
                value = name
            elif key == "fiscal_years":
                value = fiscal_year
            elif key == "vintage_slots":
                value = slot
            elif key == "filed":
                value = release
            elif key == "filed_in_8k":
                value = True
            elif key.startswith("actual_"):
                value = None
            elif key.startswith("guide_") and "eps" in key and value is not None:
                value = round(value * scale, 2)
            g[key].append(value)

    if quarter < 4:
        add_vintage(open_year, f"q{quarter}", f"FY{str(open_year)[2:]} Q{quarter}", 1.0)
    else:
        i = n - 1
        for metric, lo, hi in (("adjusted_eps", "guide_adjusted_eps_lo", "guide_adjusted_eps_hi"),
                               ("gaap_eps", "guide_gaap_eps_lo", "guide_gaap_eps_hi"),
                               ("revenue_growth_pct", "guide_revenue_growth_lo_pct", "guide_revenue_growth_hi_pct"),
                               ("adjusted_fcf_usd_m", "guide_adjusted_fcf_lo_usd_m", "guide_adjusted_fcf_hi_usd_m"),
                               ("adjusted_tax_pct", "guide_adjusted_tax_lo_pct", "guide_adjusted_tax_hi_pct")):
            if g[lo][i] is not None:
                g[f"actual_{metric}"][i] = round((g[lo][i] + g[hi][i]) / 2, 2)
        actuals = s["annual_actuals"]
        quarters = s["long_history"]["quarters"]
        revenue = sum(s["long_history"]["revenue_usd_m"][quarters.index(f"Q{k} {open_year}")] for k in (1, 2, 3, 4))
        filled = {"fiscal_years": open_year, "adjusted_eps": g["actual_adjusted_eps"][i],
                  "gaap_eps": g["actual_gaap_eps"][i], "revenue_usd_m": revenue,
                  "adjusted_fcf_usd_m": g["actual_adjusted_fcf_usd_m"][i],
                  "adjusted_tax_pct": g["actual_adjusted_tax_pct"][i], "nci_distributions_usd_m": None}
        for key, values in actuals.items():
            if isinstance(values, list):
                values.append(filled[key])
        add_vintage(open_year + 1, "initial", f"FY{str(open_year + 1)[2:]} 初", 1.1)
    for key in ("_checks",) + QUARTER_BLOCKS:
        s.pop(key, None)
    s["latest"] = dict(s["latest"], period=label, period_end=end, release_date=release)
    s["sources"] = [{"label": release_words(label),
                     "url": "https://www.sec.gov/Archives/edgar/data/64040/next.htm"}] + s["sources"]
    return s


class SpgiChecksTest(unittest.TestCase):
    """The page's quarter against a record keyed separately from the release.

    `_checks` is typed once per quarter from the earnings release itself, with
    the place in the document each figure was read from; the builder never
    reads it (asserted in `test_data_only_roll`). The release prints growth as
    whole percentages, so computed growth is compared at that precision.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
        cls.checks = cls.staging["_checks"]
        cls.payload = build_payload(cls.staging)

    def test_the_page_names_the_checked_quarter(self) -> None:
        self.assertIn(f"{self.checks['period']} 季报仪表盘", self.payload["title"])
        self.assertIn(f"截至 {self.checks['period_end']}", self.payload["subtitle"])
        self.assertIn(f"发布 {self.checks['release_date']}", self.payload["subtitle"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        fin, c = self.staging["financials"], self.checks
        for key, check in (("revenue_usd_m", "revenue_usd_m"), ("total_expenses_usd_m", "expenses_usd_m"),
                           ("gain_on_dispositions_usd_m", "gain_on_dispositions_usd_m"),
                           ("operating_income_usd_m", "operating_profit_usd_m"),
                           ("net_income_usd_m", "net_income_usd_m"), ("diluted_eps_usd", "diluted_eps_usd"),
                           ("diluted_shares_m", "diluted_shares_m"),
                           ("pro_forma_adjusted_diluted_eps_usd", "pro_forma_adjusted_diluted_eps_usd")):
            with self.subTest(key=key):
                self.assertEqual(fin[key][-1], c[check])
        segments = self.staging["segments_usd_m"]
        for key, value in c["segment_revenue_usd_m"].items():
            with self.subTest(segment=key):
                self.assertEqual(segments["revenue"][key][-1], value)
        self.assertEqual(segments["intersegment_elimination"][-1], c["intersegment_elimination_usd_m"])
        split = self.staging["ratings_revenue_split_usd_m"]
        self.assertEqual(split["transaction"][-1], c["ratings_transaction_usd_m"])
        self.assertEqual(split["non_transaction"][-1], c["ratings_non_transaction_usd_m"])
        types = self.staging["revenue_by_type_usd_m"]
        for key, value in c["revenue_by_type_usd_m"].items():
            with self.subTest(type=key):
                if key == "non_transaction_net":
                    self.assertEqual(types["non_transaction"][-1] - types["intersegment_elimination"][-1], value)
                else:
                    self.assertEqual(types[key][-1], value)

    def test_computed_growth_rounds_to_the_printed_growth(self) -> None:
        split = self.staging["ratings_revenue_split_usd_m"]
        for key, printed in (("transaction", "ratings_transaction_growth_pct"),
                             ("non_transaction", "ratings_non_transaction_growth_pct")):
            values = split[key]
            with self.subTest(key=key):
                self.assertEqual(round(spgi.pct_change(values[-1], values[-5])), self.checks[printed])

    def test_the_open_year_ends_on_the_checked_guidance(self) -> None:
        g = self.staging["annual_guidance_history"]
        self.assertEqual(g["filed"][-1], self.checks["release_date"])
        self.assertEqual([g["guide_adjusted_eps_lo"][-1], g["guide_adjusted_eps_hi"][-1]],
                         self.checks["guidance_adjusted_eps_usd"])
        self.assertEqual([g["guide_gaap_eps_lo"][-1], g["guide_gaap_eps_hi"][-1]],
                         self.checks["guidance_gaap_eps_usd"])
        self.assertEqual([g["guide_revenue_growth_lo_pct"][-1], g["guide_revenue_growth_hi_pct"][-1]],
                         self.checks["guidance_revenue_growth_pct"])

    def test_the_page_prints_the_checked_figures(self) -> None:
        c = self.checks
        cards = spgi.headline_metrics(self.staging)
        self.assertEqual(cards[0], f"Revenue ${c['revenue_usd_m'] / 1000:.2f}B")
        self.assertEqual(cards[1], f"Ratings 交易性 {c['ratings_transaction_growth_pct']:+d}%")
        self.assertEqual(cards[2], f"调整后 EPS ${c['pro_forma_adjusted_diluted_eps_usd']:.2f}")
        ratings = next(ex for ex in exhibits_of(self.payload) if ex["title"].startswith("Ratings 的两条腿"))
        self.assertIn(f"交易性 US${c['ratings_transaction_usd_m']:,.0f}M（同比 "
                      f"+{c['ratings_transaction_growth_pct']}%），非交易性 "
                      f"US${c['ratings_non_transaction_usd_m']:,.0f}M（+{c['ratings_non_transaction_growth_pct']}%）",
                      ratings["title"])
        margin = next(ex for ex in exhibits_of(self.payload) if ex["title"].startswith("同一个季度的"))
        self.assertIn(f"申报 {c['operating_profit_usd_m'] / c['revenue_usd_m'] * 100:.1f}%", margin["title"])
        row = next(t for t in self.payload["tables"] if t["title"].endswith("两个营业利润率口径"))["rows"][-1]
        self.assertEqual(row[:2], [c["period"], f"${c['revenue_usd_m']:,.0f}M"])
        self.assertEqual(row[8], f"${c['diluted_eps_usd']:,.2f}")

    def test_the_quoted_margin_is_the_computed_pro_forma_margin(self) -> None:
        """The release's 「to 47.8%」 is quoted in a story sentence; the bar beside
        it is computed from the pro forma block. Both have to say the same."""
        figures = self.staging["quarter_figures"]
        quoted = re.search(r"to (\d+\.\d)%", self.staging["quarter_story"]["margin_note"])
        computed = figures["pro_forma_operating_profit_usd_m"] / figures["pro_forma_revenue_usd_m"] * 100
        self.assertEqual(quoted.group(1), f"{computed:.1f}")


class SpgiRollTest(unittest.TestCase):
    """What a roll can change without touching the builder."""

    STORY_ONLY = ("按同口径看是上调", "Mobility 这一根是最后一次出现在这张图上",
                  "说的是 pro forma 口径", "return 100% or more", "另外这条线在 FY2026 直接消失了")

    @classmethod
    def setUpClass(cls) -> None:
        cls.s = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.s)
        cls.text = own_text(cls.payload)

    def test_a_block_stamped_for_another_quarter_stops_the_build(self) -> None:
        for key in QUARTER_BLOCKS:
            stale = copy.deepcopy(self.s)
            stale[key]["period"] = "Q1 1999"
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    build_payload(stale)
        stale = copy.deepcopy(self.s)
        stale["latest"]["period"] = "Q1 1999"
        with self.assertRaisesRegex(ValueError, "stamped"):
            build_payload(stale)

    def test_the_quarters_own_release_must_be_in_the_sources(self) -> None:
        bare = copy.deepcopy(self.s)
        prefix = release_words(self.s["periods"][-1])[:-12]
        bare["sources"] = [src for src in bare["sources"] if not src["label"].startswith(prefix)]
        self.assertLess(len(bare["sources"]), len(self.s["sources"]))
        with self.assertRaisesRegex(ValueError, "sources"):
            build_payload(bare)

    def test_a_quarter_without_its_blocks_leaves_them_out(self) -> None:
        bare = copy.deepcopy(self.s)
        for key in QUARTER_BLOCKS:
            del bare[key]
        payload = build_payload(bare)
        text = own_text(payload)
        for phrase in self.STORY_ONLY:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)
                self.assertNotIn(phrase, text)
        sections = {section["id"]: section["exhibits"] for section in payload["sections"]}
        self.assertEqual(sections["next_quarter"], [])
        self.assertFalse(any(ex["kind"] == "diverging_bars" for ex in sections["settled"]))
        numbers = [ex["n"] for ex in exhibits_of(payload)]
        self.assertEqual(numbers, list(range(2, 2 + len(numbers))))
        self.assertEqual([t["n"] for t in payload["tables"]],
                         list(range(numbers[-1] + 1, numbers[-1] + 1 + len(payload["tables"]))))
        self.assertNotRegex(text, PLACEHOLDER)
        self.assertNotRegex(text, r"\{EX_[A-Z_]+\}")
        margin = next(ex for ex in exhibits_of(payload) if ex["title"].startswith("同一个季度的"))
        self.assertTrue(margin["title"].startswith("同一个季度的两个营业利润率口径"))
        self.assertIn("本季两条主线", payload["brief"])

    def test_the_quarter_before_builds_from_the_series_alone(self) -> None:
        rolled = rolled_back(self.s)
        payload = build_payload(rolled)
        label = rolled["periods"][-1]
        self.assertEqual(payload["latest"]["disclosed_period_label"], label)
        self.assertIn(f"{label} 季报仪表盘", payload["title"])
        text = own_text(payload)
        self.assertNotIn(self.s["periods"][-1], text)
        self.assertNotRegex(text, PLACEHOLDER)
        self.assertNotRegex(text, r"\{EX_[A-Z_]+\}")
        # before the rebase there is no rebase to explain
        self.assertNotIn("口径重设", text)
        self.assertFalse(any("指引中值掉了" in ex["title"] for ex in exhibits_of(payload)))
        self.assertIn("一次都没有跌破过", payload["headline"])

    def test_the_quarters_after_build_from_the_series_alone(self) -> None:
        s = self.s
        for _ in range(2):
            s = rolled_forward(s)
            payload = build_payload(s)
            text = own_text(payload)
            self.assertIn(f"{s['periods'][-1]} 季报仪表盘", payload["title"])
            self.assertNotRegex(text, PLACEHOLDER)
            self.assertNotRegex(text, r"\{EX_[A-Z_]+\}")
            # the rebase is history now: marked on the band, no longer this quarter's chart
            self.assertIn("FY26 Q2† 那一档是口径重设", text)
            self.assertFalse(any("指引中值掉了" in ex["title"] for ex in exhibits_of(payload)))
        # the fourth quarter settles FY2026 on its new basis: the two vintages
        # guided before the spin are kept out of every comparison with it
        g = s["annual_guidance_history"]
        self.assertIsNotNone(g["actual_adjusted_eps"][g["vintages"].index("FY26 Q3")])
        converge = next(ex for ex in exhibits_of(payload) if ex["title"].startswith("实际结果相对"))
        self.assertIn("FY2026 在 2026-07-28 换了口径，此前的两档（FY26 初、FY26 Q1）", converge["note"])
        dev = spgi.vintage_deviations(g)
        self.assertIsNone(dev["initial"][dev["years"].index("FY2026")])
        self.assertNotIn(2026, spgi.opening_breaks(g)[1])
        self.assertIn("本季两条主线", payload["brief"])


class SpgiFindingsTest(unittest.TestCase):
    """Every judgement on the page says what the series says, both ways.

    Each case forces the series into a state where a finding is true, then into
    one where it is false, and checks that the words follow. Forcing rather than
    flipping today's data keeps these valid after a roll.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.s = json.loads(STAGING_PATH.read_text(encoding="utf-8"))

    def page(self, *edits) -> str:
        staged = copy.deepcopy(self.s)
        for edit in edits:
            edit(staged)
        return own_text(build_payload(staged))

    def test_the_adjusted_record_claims(self) -> None:
        def one_miss(s):
            g = s["annual_guidance_history"]
            i = g["vintages"].index("FY20 Q3")
            g["actual_adjusted_eps"][i] = g["guide_adjusted_eps_lo"][i] - 0.5

        clean = self.page()
        self.assertIn("一次都没有跌破过自己的末次指引下限", clean)
        self.assertIn("那条从不失手的曲线，是公司自己定义的那一条", clean)
        missed = self.page(one_miss)
        self.assertNotIn("一次都没有跌破过自己的末次指引下限", missed)
        self.assertIn("跌破过自己的末次指引下限 1 次", missed)
        self.assertNotIn("那条从不失手的曲线", missed)
        self.assertNotIn("不失手的是公司自己定义的那条", missed)

    def test_the_gaap_deviation_claims(self) -> None:
        def fy23_deepest(s):
            g = s["annual_guidance_history"]
            i = g["vintages"].index("FY23 Q3")
            g["actual_gaap_eps"][i] = 7.0

        self.assertIn("而且最深的一根出现在 FY2023 —— 那一年 Engineering Solutions", self.page(fy23_deepest))
        current = self.page()
        self.assertIn("仅次于 FY2017 —— 那一年 Engineering Solutions", current)
        self.assertNotIn("最深的一根出现在 FY2023", current)

    def test_the_opening_miss_claims(self) -> None:
        def fy18_beaten(s):
            g = s["annual_guidance_history"]
            i = g["vintages"].index("FY18 Q3")
            g["actual_adjusted_eps"][i] = 8.6

        once = self.page(fy18_beaten)
        self.assertIn("唯一低于开局指引中值的是 FY2022，差 −16.5%，跌破了开局区间", once)
        self.assertIn("FY2022 正是公司自己在年中<b>撤回</b>全年指引的那一年", once)
        self.assertIn("FY2018 差 −0.3%，仍在开局区间之内", self.page())

    def test_the_transaction_high_claims(self) -> None:
        def off_the_high(s):
            split = s["ratings_revenue_split_usd_m"]
            split["transaction"][-1] = max(split["transaction"][:-1]) - 10

        current = self.page()
        self.assertIn("创记录内新高", current)
        self.assertIn("又回到高点", current)
        lower = self.page(off_the_high)
        self.assertNotIn("创记录内新高", lower)
        self.assertNotIn("又回到高点", lower)
        self.assertNotIn("回到今天的新高", lower)
        self.assertIn("本记录内的最高值是", lower)

    def test_the_non_transaction_collapse_claims(self) -> None:
        def collapse(s):
            values = s["ratings_revenue_split_usd_m"]["non_transaction"]
            values[30] = values[29] * 0.6

        current = self.page()
        self.assertIn("非交易性同期没有塌陷过", current)
        self.assertIn("整段没有出现过深蓝那样的塌陷", current)
        fell = self.page(collapse)
        self.assertIn("非交易性同期也塌陷过", fell)
        self.assertNotIn("整段没有出现过深蓝那样的塌陷", fell)
        self.assertNotIn("从未塌陷", fell)

    def test_the_first_quarter_claims(self) -> None:
        def q1_always_lowest(s):
            capital = s["capital_allocation_usd_m"]
            i = capital["quarters"].index("Q1 2017")
            capital["operating_cash_flow"][i] = 100.0

        text = self.page(q1_always_lowest)
        self.assertIn("每年第一季度都是四季里最低的一档", text)
        self.assertIn("第一季度的经营现金流每年都是全年最低的一档", text)
        self.assertIn("例外是 2017 年", self.page())

    def test_the_dividend_claims(self) -> None:
        def rising(s):
            capital = s["capital_allocation_usd_m"]
            for q in (1, 2, 3, 4):
                capital["dividends"][capital["quarters"].index(f"Q{q} 2024")] += 4

        self.assertIn("逐年抬升", self.page(rising))
        self.assertIn("只有 FY2024 比上一年少", self.page())

    def test_the_segment_ranking_claims(self) -> None:
        def energy_leads(s):
            energy = s["segments_usd_m"]["revenue"]["energy"]
            energy[-1] = energy[-5] * 1.5

        text = self.page(energy_leads)
        self.assertIn("本季五个分部的收入同比：Energy +50%", text)
        self.assertNotIn("Energy +2% 落后", text)

    def test_the_threshold_verdict_claims(self) -> None:
        def crossed(s):
            s["prior_kpi_settlement"]["quantified"][0]["threshold"] = 99.0

        def no_payout(s):
            s["next_kpi"]["quantified"] = [e for e in s["next_kpi"]["quantified"]
                                           if e["reads"] != "payout_to_fcf"]

        self.assertIn("本季六条全部为正", self.page())
        text = self.page(crossed)
        self.assertIn("本季六条里五条为正、一条已越过阈值", text)
        self.assertIn("与「单季股东回报 / 自由现金流」相同、与其余几条相反", self.page())
        self.assertIn("与本节其他几条相反", self.page(no_payout))

    def test_the_issuance_cycle_claims(self) -> None:
        def downturn(s):
            total = s["billed_issuance_usd_bn"]["total"]
            total[8] = total[4] * 0.7

        self.assertIn("看不到一次下行周期", self.page())
        text = self.page(downturn)
        self.assertNotIn("看不到一次下行周期", text)
        self.assertNotIn("且不含一次下行周期", text)

    def test_the_margin_basis_claims(self) -> None:
        def big_gain(s):
            lh = s["long_history"]
            lh["operating_income_usd_m"][-1] += 400
            lh["gain_on_dispositions_usd_m"][-1] += 400

        current = self.page()
        self.assertIn("所以第一、二根几乎一样高", current)
        text = self.page(big_gain)
        self.assertNotIn("几乎一样高", text)
        self.assertIn("第一根比第二根高", text)

    def test_the_fcf_often_claims(self) -> None:
        def gaap_clean(s):
            g = s["annual_guidance_history"]
            for i, value in enumerate(g["actual_gaap_eps"]):
                if value is not None:
                    g["actual_gaap_eps"][i] = g["guide_gaap_eps_hi"][i]

        self.assertIn("这是记录里唯一一条经常做不到的指引", self.page(gaap_clean))
        self.assertIn("这是记录里除 GAAP EPS 之外唯一一条经常做不到的指引", self.page())

    def test_the_unsettled_cash_years_claims(self) -> None:
        """FY2018-FY2020 guided cash in the opening release only, so the band
        has no final cell to settle them on. The sentence names exactly those
        years and goes when the state it describes goes."""
        def restated(year):
            def edit(s):
                g = s["annual_guidance_history"]
                opening = g["vintages"].index(f"FY{str(year)[2:]} 初")
                for i in range(opening + 1, opening + 4):
                    for key in ("guide_adjusted_fcf_lo_usd_m", "guide_adjusted_fcf_hi_usd_m",
                                "guide_adjusted_fcf_form"):
                        g[key][i] = g[key][opening]
                g["actual_adjusted_fcf_usd_m"][opening + 3] = g["guide_adjusted_fcf_hi_usd_m"][opening]
            return edit

        self.assertIn("FY2018–FY2020 的现金指引只在年初那一档给过", self.page())
        one = self.page(restated(2019))
        self.assertIn("FY2018、FY2020 的现金指引只在年初那一档给过", one)
        self.assertIn("所以图上这几年只有年初一格", one)
        none = self.page(restated(2018), restated(2019), restated(2020))
        self.assertNotIn("的现金指引只在年初那一档给过", none)
        self.assertNotIn("没有末次那一格可结算", none)


if __name__ == "__main__":
    unittest.main()
