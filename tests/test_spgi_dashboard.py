"""Checks for the SPGI page.

The page rests on claims a quarter roll can quietly invalidate, and each one is
pinned here rather than narrated:

* the guidance record is **annual**, not quarterly. S&P Global has never filed a
  quarterly outlook, so every band on this page is a fiscal year's revision path
  and the year's reported result must land on the vintage that settles it -- the
  *final* one. An actual that drifted onto an earlier vintage would claim the
  year was settled against a forecast made before it happened;
* the record's shape is the page's headline, and it is two-sided: adjusted
  diluted EPS never landed below its final range in seven finished years, while
  GAAP diluted EPS landed below in three of the same seven. Both counts are
  asserted, so a bad parse cannot quietly soften either half;
* an actual may only be placed where that metric actually carries a band.
  Adjusted free cash flow was not guided at all before FY2023, and dropping
  FY2019's reported figure onto a cell with no range would invent a settlement;
* `delivery_band` and `midpoint_deviation` both default to counting quarters.
  This page counts fiscal years, so the titles are checked for it -- a chart
  reading "7 季里" for a seven-year record is wrong in a way no arithmetic test
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
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.all import build_all, roster_payload  # noqa: E402
from build.board import headroom  # noqa: E402
from build.spgi import build_payload, operating_margin_ex_credits  # noqa: E402


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


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
        self.assertEqual(checked, 7)

    def test_six_revenue_types_add_back_to_filed_revenue(self) -> None:
        """The company discloses six revenue types in dollars and nets the
        intersegment elimination inside the non-transaction column, so the six
        gross lines less that elimination is consolidated revenue exactly."""
        revenue = dict(zip(self.long["quarters"], self.long["revenue_usd_m"]))
        for index, period in enumerate(self.types["quarters"]):
            gross = sum(self.types[name][index] for name in TYPES)
            with self.subTest(period=period):
                self.assertAlmostEqual(
                    gross - self.types["intersegment_elimination"][index],
                    revenue[period], delta=0.51)

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
        record = self.record
        self.assertEqual(len(record["vintages"]), 31)
        length = len(record["vintages"])
        for key, values in record.items():
            if isinstance(values, list):
                with self.subTest(series=key):
                    self.assertEqual(len(values), length)
        self.assertEqual(sorted(set(record["fiscal_years"])),
                         [2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026])

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
        """Adjusted free cash flow was not guided before FY2023. Landing an
        earlier year's reported figure on a cell with no range would invent a
        settlement that never happened."""
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

    def test_the_record_is_two_sided_and_the_counts_are_asserted(self) -> None:
        """The page's headline finding. Adjusted EPS has never missed; the GAAP
        number on the same table missed three times in the same seven years."""
        def tally(lo, hi, actual):
            above = inside = below = 0
            for low, high, value in zip(self.record[lo], self.record[hi],
                                        self.record[actual]):
                if value is None or low is None:
                    continue
                if value > high:
                    above += 1
                elif value < low:
                    below += 1
                else:
                    inside += 1
            return above, inside, below

        self.assertEqual(
            tally("guide_adjusted_eps_lo", "guide_adjusted_eps_hi",
                  "actual_adjusted_eps"), (5, 2, 0))
        self.assertEqual(
            tally("guide_gaap_eps_lo", "guide_gaap_eps_hi", "actual_gaap_eps"),
            (2, 2, 3))
        self.assertEqual(
            tally("guide_revenue_growth_lo_pct", "guide_revenue_growth_hi_pct",
                  "actual_revenue_growth_pct"), (1, 2, 0))
        # the metric that behaves the other way round
        self.assertEqual(
            tally("guide_adjusted_fcf_lo_usd_m", "guide_adjusted_fcf_hi_usd_m",
                  "actual_adjusted_fcf_usd_m"), (1, 0, 2))

    def test_the_opening_vintage_is_the_one_that_carries_information(self) -> None:
        """Six of seven opening guidances were beaten, and the single miss is
        FY2022 -- the year the company withdrew guidance mid-year."""
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
        self.assertEqual(beaten, 6)
        self.assertEqual(missed, [2022])
        self.assertEqual(record["suspension"]["announced"], "2022-06-01")

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
        self.assertEqual(
            sum(1 for form in record["guide_adjusted_fcf_form"] if form == "point"), 5)

    def test_the_one_unfiled_vintage_is_flagged(self) -> None:
        """FY2022's opening guidance came from an investor day and reaches EDGAR
        only as a recital inside a later 8-K. It is published, and marked."""
        record = self.record
        unfiled = [label for label, in_8k in zip(record["vintages"], record["filed_in_8k"])
                   if not in_8k]
        self.assertEqual(unfiled, ["FY22 初*"])
        self.assertEqual(record["fiscal_years"][record["vintages"].index("FY22 初*")], 2022)

    def test_the_mobility_rebase_is_marked_rather_than_smoothed(self) -> None:
        record = self.record
        self.assertEqual(record["basis_break_at"], len(record["vintages"]) - 1)
        self.assertIn("Mobility", record["basis_break_label"])
        band = next(ex for ex in self.by_section["settled"]
                    if ex["kind"] == "range_band" and "调整后摊薄 EPS" in ex["title"])
        self.assertEqual(band["break_at"], record["basis_break_at"])
        # the breaching bar is kept, not edited away
        self.assertEqual(band["lo"][-1], 17.50)
        self.assertEqual(band["hi"][-1], 17.75)
        self.assertAlmostEqual(band["lo"][-2], 19.40)

    def test_no_invented_bridge_across_the_rebase(self) -> None:
        """The company disclosed a Mobility add-back for FY2025 and none for
        FY2026. The page may quote the first and must not derive the second."""
        record = self.record
        self.assertAlmostEqual(record["mobility_addback_adjusted_eps_usd"], 1.98)
        self.assertAlmostEqual(record["fy2025_proforma_adjusted_eps_usd"], 15.85)
        chart = next(ex for ex in self.by_section["quarter_highlights"]
                     if "FY2026 指引中值" in ex["title"])
        self.assertIn("不发布任何自算的桥", chart["note"])

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
        mobility = self.segments["revenue"]["mobility"]
        self.assertIsNotNone(mobility[-1])
        self.assertGreater(mobility[-1], 0)
        self.assertEqual(self.segments["quarters"][-1], "Q2 2026")
        self.assertTrue(any("2026-07-01" in note for note in self.payload["notes"]))
        self.assertTrue(any("终止经营" in note for note in self.payload["notes"]))

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
            entries = self.source[block]["quantified"]
            chart = next(ex for ex in self.by_section[section]
                         if ex["kind"] == "diverging_bars")
            with self.subTest(section=section):
                self.assertEqual(chart["xlabels"], [e["metric"] for e in entries])
                self.assertEqual(
                    chart["values"],
                    [round(headroom(e["direction"], e["threshold"], e[key]), 1)
                     for e in entries])

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
        says how it got there."""
        # Each tracked metric gets exactly one history chart, and the two
        # sections split them rather than drawing every line twice: the three
        # that settle last quarter's judgement sit in section one, the four
        # that point forward sit in section three. Both overview bars name what
        # they do not re-draw, which is the README's rule for anything left out.
        elsewhere = {
            "settled": {"Ratings 非交易性收入同比", "单季自由现金流 D", "计费发行量"},
            "next_quarter": {"Ratings 交易性收入同比",
                             "营业利润率（剔除处置损益与联营收益 D）",
                             "订阅型收入占毛收入比重"},
        }
        drawn = 0
        for section, block, key in (("settled", "prior_kpi_settlement", "actual"),
                                    ("next_quarter", "next_kpi", "current")):
            titles = " ".join(ex["title"] for ex in self.by_section[section])
            for entry in self.source[block]["quantified"]:
                name = entry["metric"]
                if name in elsewhere[section]:
                    continue
                drawn += 1
                stem = name.split("（")[0].strip()
                with self.subTest(section=section, metric=name):
                    self.assertIn(stem, titles)
        self.assertEqual(drawn, 7)
        # and every metric deferred out of one section is drawn in the other
        settled = {e["metric"] for e in self.source["prior_kpi_settlement"]["quantified"]}
        upcoming = {e["metric"] for e in self.source["next_kpi"]["quantified"]}
        self.assertTrue(elsewhere["settled"] <= upcoming | {"Ratings 非交易性收入同比"})
        self.assertTrue(elsewhere["next_quarter"] <= settled)

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


if __name__ == "__main__":
    unittest.main()
