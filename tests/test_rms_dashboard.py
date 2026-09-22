"""Hermès page: the reconciliations that license what the page publishes.

Three of these exist because of something specific to this filer rather than
because every page has one:

- `test_the_page_never_puts_profit_on_a_quarterly_axis` is the structural check.
  Hermès publishes revenue quarterly and an income statement twice a year, so
  the page carries two clocks. Nothing else in the suite notices a margin drawn
  against a quarter label: the values would be finite, the lengths would match,
  the build would be deterministic and the render gate would find no NaN. It
  would simply be a number the company never published, plotted under a label
  that says it did. This asserts the separation the module docstring promises,
  from the shape of each exhibit's own axis rather than from a list of exhibit
  names.
- `test_a_derived_constant_currency_rate_does_not_match_the_printed_one` is why
  the staging file forbids deriving one. Constant-currency rates are printed per
  line per period; a first half minus its first quarter looks like it should
  give the second quarter and does not, because every component is rounded to
  the million and the rate to a tenth of a point first. The page states how far
  off the subtraction lands and names the lines it lands furthest on; this
  re-derives both by a different route.
- `test_the_margin_bridge_closes_on_the_printed_statement` pins the €1M that the
  printed half-year income statement does not close by. Gross margin less
  selling and administrative expenses less other income and expenses is €3,350M
  against a printed recurring operating income of €3,351M, so a bridge built
  from the components alone lands 0.012pp away from the figure it is supposed to
  reach. The last leg absorbs it and this is what checks that it does.

A roll edits `series/rms.json` and nothing else (CLAUDE.md §9): nothing below
names a quarter, a half or a count. What one release printed is asserted from
`_checks` (`RmsChecksTest`), and `RmsRollTest` rolls the series a quarter back
and a quarter forward, tampers each stamped block, and makes each finding false
on a copy of the series to see its words go.
"""

from __future__ import annotations

import copy
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import rms  # noqa: E402
from build.board import cn_count, cn_ordinal, headroom  # noqa: E402


def js_payload(path: Path, marker: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{marker} = ", 1)[1].rstrip().rstrip(";")
    return json.loads(body)


def exhibits(payload: dict) -> list[dict]:
    return [ex for section in payload["sections"] for ex in section["exhibits"]]


def own_text(payload: dict) -> str:
    """Everything the page says, less the cross-page table every page carries."""
    own = dict(payload, tables=[t for t in payload["tables"] if "AI capex" not in t["title"]])
    return json.dumps(own, ensure_ascii=False)


QUARTER = re.compile(r"^Q[1-4] \d{4}$")
YEAR = re.compile(r"^\d{4}$")
# Words that can only belong to a figure this company publishes twice a year.
PROFIT_WORDS = ("利润", "每股", "现金流", "投资")
# The blocks that describe one quarter, and the ones that describe one half.
QUARTER_BLOCKS = ("next_kpi", "quasi_guidance", "quarter_story")
HALF_BLOCKS = ("first_half", "h1_income", "h1_segments", "half_story")
PLACEHOLDER = r"\{[A-Za-z_]+(?::[a-z_]+)?\}"


def rated(staging: dict) -> list[int]:
    """Indices whose quarter carries both printed rates.

    The revenue window runs four quarters longer than the rate window: 2016
    reaches this file as the prior-year column of the 2017 releases, which
    prints the euro amount without the growth beside it. Written again here
    rather than imported from `build/rms.py`, because a test that borrowed the
    builder's own idea of which quarters count could not catch the builder
    counting the wrong ones.
    """
    group = staging["group_revenue"]
    return [i for i in range(len(staging["periods"]))
            if group["published_pct"][i] is not None and group["cc_pct"][i] is not None]


def quarter_of(period: str) -> tuple[int, int]:
    return int(period[-4:]), int(period[1])


def span_words(releases: list[dict]) -> str:
    """How long the outlook sentence has stood, counted in the quarters its releases cover.

    ``Q1 2021 收入公告`` covers the first quarter of 2021 and ``2026 半年度业绩``
    runs to the second of 2026: twenty-two quarters, 「五年半」.
    """
    def last_quarter(label: str) -> tuple[int, int]:
        match = re.match(r"Q([1-4]) (\d{4})", label)
        if match:
            return int(match.group(2)), int(match.group(1))
        return int(label[:4]), 2 if "半年" in label else 4
    (y1, q1), (y2, q2) = last_quarter(releases[0]["label"]), last_quarter(releases[-1]["label"])
    quarters = (y2 - y1) * 4 + q2 - q1 + 1
    return cn_count(quarters // 4) + "年" + ["", "多", "半", "半多"][quarters % 4]


def increments(block: dict, keys, index: int) -> dict:
    """Printed rate times printed prior-year base, written out again here."""
    return {k: block[k]["prior_year_eur_m"][index] * block[k]["cc_pct"][index] / 100 for k in keys}


class RmsSeriesTest(unittest.TestCase):
    """The transcription, checked against identities the company itself prints."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(rms.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = rms.build_payload(cls.staging)
        cls.reconciliations = next(n for n in cls.payload["notes"] if n.startswith("已做的对账"))

    def test_the_window_is_contiguous_quarters(self) -> None:
        periods = self.staging["periods"]
        self.assertGreaterEqual(len(periods), 5, "the wedge note compares a quarter with its year-ago one")
        self.assertEqual(periods[-1], self.staging["latest"]["period"])
        for earlier, later in zip(periods, periods[1:]):
            y1, q1 = quarter_of(earlier)
            y2, q2 = quarter_of(later)
            self.assertEqual((y2, q2), (y1 + 1, 1) if q1 == 4 else (y1, q1 + 1))

    def test_every_quarterly_series_is_as_long_as_the_window(self) -> None:
        width = len(self.staging["periods"])
        for field in ("revenue_eur_m", "published_pct", "cc_pct", "prior_year_eur_m"):
            self.assertEqual(len(self.staging["group_revenue"][field]), width, f"group.{field}")
        for name in ("by_sector", "by_region"):
            for key, block in self.staging[name].items():
                for field in ("revenue_eur_m", "published_pct", "cc_pct", "prior_year_eur_m"):
                    self.assertEqual(len(block[field]), width, f"{name}.{key}.{field}")

    def test_the_seven_metiers_sum_to_the_printed_group_total(self) -> None:
        """The issuer's own rows against the issuer's own total.

        The tolerance was ±1 while the window held only the whole-million era's
        last eight quarters. Over the full 42 it has to be ±2, because Hermès's
        own printed rows miss its own printed total by 2 in Q3 2023 (3,363
        against 3,365) -- seven rows each rounded to the million can lose that
        much, and both of this repo's independent transcriptions read the same
        figures. The bound is re-measured below rather than widened by guess,
        and the worst residual is pinned so it cannot creep.
        """
        self.assertEqual(sorted(self.staging["by_sector"]), sorted(rms.SECTOR_ORDER))
        worst = 0
        for index, period in enumerate(self.staging["periods"]):
            total = self.staging["group_revenue"]["revenue_eur_m"][index]
            summed = sum(block["revenue_eur_m"][index]
                         for block in self.staging["by_sector"].values())
            self.assertLessEqual(abs(summed - total), 2, f"{period}: {summed} vs {total}")
            worst = max(worst, abs(summed - total))
        self.assertEqual(worst, 2, "re-measure this bound; do not widen it")

    def test_the_six_regions_sum_to_the_printed_group_total(self) -> None:
        self.assertEqual(sorted(self.staging["by_region"]), sorted(rms.REGION_ORDER))
        worst = 0
        for index, period in enumerate(self.staging["periods"]):
            total = self.staging["group_revenue"]["revenue_eur_m"][index]
            summed = sum(block["revenue_eur_m"][index]
                         for block in self.staging["by_region"].values())
            self.assertLessEqual(abs(summed - total), 1, f"{period}: {summed} vs {total}")
            worst = max(worst, abs(summed - total))
        self.assertEqual(worst, 1, "re-measure this bound; do not widen it")

    def test_every_complete_year_in_the_window_equals_the_filed_full_year(self) -> None:
        """The one check that would catch a cumulative column read as a quarter.

        The quarters in this window come out of three different document types
        -- a quarterly revenue announcement, a half-year results release and a
        full-year results release -- and each of those prints a cumulative
        table beside the quarterly one. Reading the wrong block would leave
        every within-period identity intact, because the métiers and the
        regions would go cumulative together and still sum to the cumulative
        total. Only the year does not close. Eight contiguous quarters always
        hold one whole calendar year.
        """
        periods = self.staging["periods"]
        years = [y for y in sorted({p[-4:] for p in periods})
                 if all(f"Q{k} {y}" in periods for k in (1, 2, 3, 4)) and y in self.staging["full_years"]]
        self.assertTrue(years)
        # The window now holds ten of these, and one of them does not close:
        # Hermès printed 13,427 for 2023 while its own four printed quarters
        # sum to 13,426, the euro entering at the half (a printed H1 of 6,698
        # against Q1+Q2 = 6,697). So the assertion is no longer equality -- it
        # is that the page states whichever of the two it found. An exact-match
        # rule here would have forced the backfill to drop the one year that
        # actually has something to say.
        self.assertTrue(years)
        gaps = {}
        for year in years:
            quarters = sum(self.staging["group_revenue"]["revenue_eur_m"][periods.index(f"Q{k} {year}")]
                           for k in (1, 2, 3, 4))
            filed = self.staging["full_years"][year]["revenue_eur_m"]
            self.assertLessEqual(abs(quarters - filed), 1, f"{year}: {quarters} vs {filed}")
            if quarters == filed:
                self.assertIn(f"{year} 年四个季度相加等于公司申报的全年 €{quarters:,}M", self.reconciliations)
            else:
                gaps[year] = abs(quarters - filed)
                digits = 1 if any(float(v) != int(v) for v in (quarters, filed)) else 0
                self.assertIn(f"{year} 年四个季度相加 €{quarters:,}M，"
                              f"与公司申报的全年 €{filed:,}M 差 €{gaps[year]:,.{digits}f}M",
                              self.reconciliations)
        # Pinned so a second non-closing year cannot slip in unremarked.
        # 2021 is here because the filed value was repaired: the file used to
        # carry 8,982.1, which is nine months at one decimal plus a whole-million
        # fourth quarter -- a number no Hermès document prints. The company
        # prints 8,982 in five places. Putting the printed value back makes this
        # check able to fail, and the 0.1 it now reports is the splice.
        self.assertEqual({y: round(g, 4) for y, g in gaps.items()},
                         {"2021": 0.1, "2023": 1})

    def test_the_two_quarters_of_the_half_equal_the_printed_first_half(self) -> None:
        """To the million, each row -- and the note says by how much it misses."""
        half = self.staging["first_half"]
        year = half["period"].split()[1]
        periods = self.staging["periods"]
        first, second = periods.index(f"Q1 {year}"), periods.index(f"Q2 {year}")
        worst = 0
        rows = [("group", half["group"], self.staging["group_revenue"])]
        rows += [(f"{name}.{key}", row, self.staging[name][key])
                 for name in ("by_sector", "by_region") for key, row in half[name].items()]
        for where, row, block in rows:
            for field in ("revenue_eur_m", "prior_year_eur_m"):
                summed = block[field][first] + block[field][second]
                self.assertLessEqual(abs(summed - row[field]), 1, f"{where}.{field}: {summed} vs {row[field]}")
                worst = max(worst, abs(summed - row[field]))
        if worst:
            self.assertIn(f"{year} 年第一、二季度相加与公司印出的上半年累计各行最多差 €{worst}M",
                          self.reconciliations)
        else:
            self.assertIn(f"{year} 年第一、二季度相加等于公司印出的上半年累计各行", self.reconciliations)

    def test_a_derived_constant_currency_rate_does_not_match_the_printed_one(self) -> None:
        """Why the staging forbids deriving a rate rather than reading one.

        Weighting each printed rate by the prior-year column it is printed
        beside gives a euro increment, so a first-half increment minus a
        first-quarter increment, over what is left of the base, should give the
        second quarter's rate. It does not: watches derives to +4.7% against a
        printed +4.4% for the second quarter of 2026. The page's note says how
        far the worst line lands and names the two furthest that round to a
        different tenth; both are re-derived here.
        """
        half = self.staging["first_half"]
        year = half["period"].split()[1]
        periods = self.staging["periods"]
        first, second = periods.index(f"Q1 {year}"), periods.index(f"Q2 {year}")
        seen = {}
        for name, short in (("by_sector", rms.SECTOR_SHORT), ("by_region", rms.REGION_SHORT)):
            for key, row in half[name].items():
                block = self.staging[name][key]
                half_increment = row["prior_year_eur_m"] * row["cc_pct"] / 100
                q1_increment = block["prior_year_eur_m"][first] * block["cc_pct"][first] / 100
                base = row["prior_year_eur_m"] - block["prior_year_eur_m"][first]
                seen[short[key]] = (block["cc_pct"][second], (half_increment - q1_increment) / base * 100)
        worst = max(abs(derived - printed) for printed, derived in seen.values())
        note = next(n for n in self.payload["notes"] if "半年减第一季" in n)
        self.assertIn(f"与官方值最大相差 {worst:.1f}pp", note)
        named = re.findall(r"(?:例如|、)([^、（]+?(?:（[^）]+）)?)的 ([+−]\d+\.\d)% 会被反推成 ([+−]\d+\.\d)%", note)
        off = sorted((name for name, (p, d) in seen.items() if round(d, 1) != p),
                     key=lambda name: -abs(seen[name][1] - seen[name][0]))
        self.assertEqual([name for name, _, _ in named], off[:2])
        for name, printed, derived in named:
            self.assertEqual(float(printed.replace("−", "-")), seen[name][0], name)
            self.assertEqual(float(derived.replace("−", "-")), round(seen[name][1], 1), name)
            self.assertNotEqual(printed, derived, name)

    def test_every_derived_half_is_the_filed_year_minus_the_filed_half(self) -> None:
        halves = {h["label"]: h for h in self.staging["half_years"]}
        # Adjusted free cash flow is a company-defined line the pre-2023
        # releases do not print, so it is absent from the backfilled halves.
        # Asking every year for it would fail on the data's shape rather than
        # on the identity this test is about.
        fields = ("revenue_eur_m", "recurring_operating_income_eur_m",
                  "net_profit_group_eur_m", "operating_cash_flows_eur_m",
                  "operating_investments_eur_m", "adjusted_fcf_eur_m")
        derived = [h for h in self.staging["half_years"] if h["derived"]]
        self.assertTrue(derived)
        for half in derived:
            year = half["label"].split()[1]
            full = self.staging["full_years"][year]
            first = halves[f"H1 {year}"]
            for field in fields:
                if any(row.get(field) is None for row in (half, full, first)):
                    continue
                self.assertAlmostEqual(half[field], full[field] - first[field], places=4,
                                       msg=f"{half['label']}.{field}")
        self.assertIn(f"{cn_count(len(derived))}个财年的上下半年相加都等于公司申报的全年", self.reconciliations)

    def test_only_the_second_halves_are_flagged_derived(self) -> None:
        """A first half is filed; nothing about it may be marked as computed."""
        for half in self.staging["half_years"]:
            self.assertEqual(half["derived"], half["label"].startswith("H2"), half["label"])

    def test_each_half_margin_is_its_own_two_filed_numbers(self) -> None:
        for half in self.staging["half_years"]:
            self.assertAlmostEqual(
                half["roi_margin_pct"],
                half["recurring_operating_income_eur_m"] / half["revenue_eur_m"] * 100,
                places=3, msg=half["label"])

    def test_the_first_half_outearns_the_second_only_where_the_page_says_so(self) -> None:
        """The page states this as the reason 41% is not a full-year figure.

        The first halves are taken as the company printed them where the
        recomputation rounds differently, the second halves are derived.
        """
        halves = {h["label"]: h for h in self.staging["half_years"]}

        def first_half_margin(h: dict) -> float:
            printed = h.get("roi_margin_printed_pct")
            return printed if printed is not None and round(h["roi_margin_pct"], 1) != printed else h["roi_margin_pct"]
        years = [y for y in sorted({h["label"].split()[1] for h in self.staging["half_years"]})
                 if f"H1 {y}" in halves and f"H2 {y}" in halves]
        gaps = [first_half_margin(halves[f"H1 {y}"]) - halves[f"H2 {y}"]["roi_margin_pct"] for y in years]
        seasonality = next(ex for ex in exhibits(self.payload) if ex.get("ref") == "EX_HALF_MARGIN")
        every = bool(gaps) and all(g > 0 for g in gaps)
        self.assertEqual("每一次都高于下半年" in seasonality["title"], every)
        if every:
            self.assertIn("落差依次是 " + "、".join(f"{g:.2f}pp" for g in gaps), seasonality["note"])
            self.assertEqual("收窄到" in seasonality["title"], gaps[-1] < gaps[0])

    def test_the_printed_income_statement_closes_where_it_can(self) -> None:
        lines = {key: (cur, prior) for key, _, cur, prior in self.staging["h1_income"]["lines"]}
        for index in (0, 1):
            self.assertEqual(lines["revenue"][index] + lines["cost_of_sales"][index],
                             lines["gross_margin"][index])
        detail = {key: (cur, prior) for key, _, cur, prior in
                  self.staging["h1_income"]["other_detail"]}
        for index in (0, 1):
            summed = sum(value[index] for value in detail.values())
            self.assertLessEqual(abs(summed - lines["other_income_expenses"][index]), 1)

    def test_the_segment_note_adds_up_to_the_group(self) -> None:
        rows = self.staging["h1_segments"]["rows"]
        lines = {key: (cur, prior) for key, _, cur, prior in self.staging["h1_income"]["lines"]}
        self.assertEqual(sum(s["roi_now"] for s in rows), lines["recurring_operating_income"][0])
        self.assertEqual(sum(s["roi_prior"] for s in rows), lines["recurring_operating_income"][1])
        # Revenue in the segment note is printed to the million per region and
        # carries its own rounding: the six add to €8,164M against a group line
        # of €8,163M. Profit is not rounded away in the same table and does add
        # exactly, so the two are asserted at different tolerances on purpose.
        operating = [s for s in rows if s["key"] != "unallocated"]
        self.assertLessEqual(abs(sum(s["revenue_now"] for s in operating) - lines["revenue"][0]), 1)
        self.assertLessEqual(abs(sum(s["revenue_prior"] for s in operating) - lines["revenue"][1]), 1)

    def test_the_headline_credits_the_unallocated_column_only_when_the_regions_shrank(self) -> None:
        """The claim the page's headline rests on, asserted from the note itself."""
        rows = self.staging["h1_segments"]["rows"]
        operating = [s for s in rows if s["key"] != "unallocated"]
        lines = {key: (cur, prior) for key, _, cur, prior in self.staging["h1_income"]["lines"]}
        shrank = sum(s["roi_now"] for s in operating) < sum(s["roi_prior"] for s in operating)
        grew = lines["recurring_operating_income"][0] > lines["recurring_operating_income"][1]
        self.assertEqual("全部来自未分配一栏" in self.payload["headline"], shrank and grew)

    def test_the_outlook_is_one_sentence_with_no_number_in_it(self) -> None:
        outlook = self.staging["outlook"]
        self.assertEqual(outlook["numbers_in_sentence"], 0)
        self.assertFalse(re.search(r"\d", outlook["sentence"]), outlook["sentence"])
        self.assertEqual(outlook["sentence"].count("."), 1)
        self.assertGreaterEqual(len(outlook["releases"]), 15)
        dates = [r["date"] for r in outlook["releases"]]
        self.assertEqual(dates, sorted(dates))
        self.assertEqual(len(dates), len(set(dates)))
        self.assertEqual(dates[-1], self.staging["release_dates"][self.staging["periods"][-1]])


class RmsPayloadTest(unittest.TestCase):
    """What the page is allowed to draw and say."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(rms.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = rms.build_payload(cls.staging)
        cls.exhibits = exhibits(cls.payload)
        cls.by_ref = {ex["ref"]: ex for ex in cls.exhibits if "ref" in ex}
        cls.entries = rms.kpi_entries(cls.staging, cls.staging["next_kpi"])

    # ── the two clocks ──────────────────────────────────────────────────────
    def test_the_page_never_puts_profit_on_a_quarterly_axis(self) -> None:
        for exhibit in self.exhibits:
            labels = exhibit.get("xlabels") or []
            if not labels or not all(QUARTER.match(str(label)) for label in labels):
                continue
            surface = exhibit["title"] + " " + str(exhibit.get("ylab", ""))
            for word in PROFIT_WORDS:
                self.assertNotIn(word, surface,
                                 f"{exhibit['n']} is on a quarterly axis: {surface[:70]}")

    def test_every_profit_exhibit_says_so_in_its_own_title(self) -> None:
        """A reader scrolling one page past two clocks has only the title."""
        for exhibit in self.exhibits:
            surface = exhibit["title"] + " " + str(exhibit.get("ylab", ""))
            if not any(word in surface for word in PROFIT_WORDS):
                continue
            self.assertIn("半年", exhibit["title"],
                          f"{exhibit['n']} plots a half-yearly figure: {exhibit['title'][:70]}")

    def test_a_half_yearly_exhibit_is_never_labelled_with_quarters(self) -> None:
        for exhibit in self.exhibits:
            if "半年" not in (exhibit["title"] + str(exhibit.get("ylab", ""))):
                continue
            for label in exhibit.get("xlabels") or []:
                self.assertFalse(QUARTER.match(str(label)),
                                 f"{exhibit['n']} mixes clocks at {label}")

    def test_the_roster_labels_the_two_periods_differently(self) -> None:
        """The first page here whose profit period is not its revenue period."""
        latest = self.payload["latest"]
        self.assertEqual(latest["disclosed_period_label"], self.staging["periods"][-1])
        self.assertEqual(latest["full_financial_period_label"], self.staging["half_years"][-1]["label"])
        self.assertNotEqual(latest["disclosed_period_label"],
                            latest["full_financial_period_label"])

    # ── the arithmetic the page prints in its own titles ────────────────────
    def test_the_margin_bridge_closes_on_the_printed_statement(self) -> None:
        bridge = next(ex for ex in self.exhibits if ex["kind"] == "bridge_bar")
        legs = [v for v in bridge["stacks"][0]["values"] if v is not None]
        net = [v for v in bridge["net"]["values"] if v is not None]
        self.assertEqual(len(net), 1)
        # Everything in the payload is rounded to six decimal places, so the
        # tolerance is that rounding and not a floating-point epsilon.
        self.assertLess(abs(sum(legs) - net[0]), 5e-4)
        self.assertEqual(len(legs) + 1, len(bridge["xlabels"]))
        # every leg draws something -- a zero column would print a label over
        # empty canvas, which is what the site-level bridge gate exists for
        for leg in legs:
            self.assertNotEqual(leg, 0)
        lines = {key: (cur, prior) for key, _, cur, prior in self.staging["h1_income"]["lines"]}
        expected = (lines["recurring_operating_income"][0] / lines["revenue"][0] * 100
                    - lines["recurring_operating_income"][1] / lines["revenue"][1] * 100)
        self.assertLess(abs(net[0] - expected), 5e-4)
        self.assertIn(f"按科目重算净{'降' if expected < 0 else '升'} {expected:+.2f}pp", bridge["title"])

    def test_the_bridge_note_ranks_impairment_the_way_the_bridge_does(self) -> None:
        """Two claims, and the first one is the one that is easy to get wrong.

        Selling and administrative expenses can be a bigger drag than impairment
        (H1 2026: −0.46pp against −0.33pp), so 「费用端最大的一项是减值」 read
        across the whole bridge would be false. What the note may say is that
        the gross-margin gain and the SG&A drag cancel to almost nothing,
        leaving the net decline inside the other-income line, where impairment
        is the largest item -- and it says so only while each half of that is
        true.
        """
        bridge = next(ex for ex in self.exhibits if ex["kind"] == "bridge_bar")
        legs = dict(zip(bridge["xlabels"], bridge["stacks"][0]["values"]))
        note = bridge["note"]
        self.assertNotIn("费用端最大的一项是减值", note)
        cancel = abs(legs["毛利率"] + legs["销售及管理费用"]) < 0.05
        self.assertEqual("头两根柱几乎正好抵消" in note, cancel)
        inside = {k: legs[k] for k in ("折旧与摊销", "减值损失", "免费股计划费用")}
        net = next(v for v in bridge["net"]["values"] if v is not None)
        claimed = "而那一行里最大的一项既不是广告也不是折旧，是<b>减值损失</b>" in note
        self.assertEqual(claimed, cancel and net < 0 and min(inside, key=inside.get) == "减值损失")
        if claimed:
            self.assertIn(f"净降幅的 {abs(legs['减值损失'] / net) * 100:.0f}%", note)

    def test_the_contribution_shares_sum_to_one_hundred(self) -> None:
        for ref in ("EX_SECTOR_MIX", "EX_REGION_MIX"):
            exhibit = self.by_ref[ref]
            for group in exhibit["groups"]:
                self.assertAlmostEqual(sum(group["values"]), 100.0, places=1,
                                       msg=f"{ref} / {group['name']}")

    def test_the_weighted_increments_reconcile_with_the_group_rate(self) -> None:
        """The one derivation this page adds, checked against the group's own rate
        -- and the note says 「不到 1%」 only while it is."""
        group = self.staging["group_revenue"]
        latest = len(self.staging["periods"]) - 1
        top_down = group["prior_year_eur_m"][latest] * group["cc_pct"][latest] / 100
        bottom_up = sum(increments(self.staging["by_sector"], rms.SECTOR_ORDER, latest).values())
        note = self.by_ref["EX_SECTOR_MIX"]["note"]
        self.assertEqual("两者相差不到 1%" in note, abs(bottom_up / top_down - 1) < 0.01)
        self.assertIn(f"合计 €{bottom_up:.0f}M；用集团口径复核是 €{top_down:.0f}M", note)
        for block, order in (("by_sector", rms.SECTOR_ORDER), ("by_region", rms.REGION_ORDER)):
            _, summed = rms.cc_increments(self.staging[block], order, latest)
            self.assertAlmostEqual(summed, sum(increments(self.staging[block], order, latest).values()), places=6)

    def test_the_wedge_exhibit_is_the_difference_of_the_two_rate_lines(self) -> None:
        rates = self.by_ref["EX_RATES"]
        wedge = self.by_ref["EX_WEDGE"]
        published, cc = (series["values"] for series in rates["series"])
        self.assertEqual(len(wedge["values"]), len(published))
        for index, value in enumerate(wedge["values"]):
            if published[index] is None or cc[index] is None:
                self.assertIsNone(value, f"index {index}: no rate, so no wedge")
                continue
            self.assertAlmostEqual(value, published[index] - cc[index], places=6)

    def test_the_sign_flips_the_page_counts_are_the_ones_in_the_data(self) -> None:
        """The note counts the region-quarters; a new one appearing must be said,
        and 「全部落在日本与亚太」 must stop being said the day it is not."""
        periods = self.staging["periods"]
        flips = [(periods[index], key)
                 for key, block in self.staging["by_region"].items()
                 for index in rated(self.staging)
                 if block["published_pct"][index] * block["cc_pct"][index] < 0]
        exhibit = self.by_ref["EX_REGION_RATES"]
        self.assertIn(f"<b>{len(flips)} 格的两个口径符号相反</b>", exhibit["note"])
        for period, key in flips:
            self.assertIn(f"{period} 的{self.staging['by_region'][key]['label']}", exhibit["note"])
        self.assertEqual("全部落在日本与亚太（除日本）" in exhibit["note"],
                         bool(flips) and {key for _, key in flips} == {"japan", "asia_pacific_ex_japan"})

    def test_the_region_rank_in_the_title_is_the_rank_in_the_data(self) -> None:
        """The title once called Japan 「全集团最快」 in a quarter the Americas grew faster."""
        latest = len(self.staging["periods"]) - 1
        regions = self.staging["by_region"]
        title = self.by_ref["EX_REGION_RATES"]["title"]
        named = next(k for k in rms.REGION_ORDER if f"：{regions[k]['label']} published" in title)
        rank = sorted(rms.REGION_ORDER, key=lambda k: -regions[k]["cc_pct"][latest]).index(named) + 1
        if "一个口径说它在萎缩" in title:
            self.assertEqual("全集团最快" in title, rank == 1)
            if rank > 1:
                self.assertIn(f"增长第{cn_ordinal(rank)}快的", title)

    # ── thresholds ──────────────────────────────────────────────────────────
    def test_every_quantified_threshold_has_a_headroom_bar(self) -> None:
        exhibit = next(ex for ex in self.exhibits if ex["kind"] == "diverging_bars"
                       and ex["ylab"] == "距阈值 %")
        self.assertEqual(len(exhibit["values"]), len(self.entries))
        for index, entry in enumerate(self.entries):
            self.assertAlmostEqual(
                exhibit["values"][index],
                round(headroom(entry["direction"], entry["threshold"], entry["current"]), 1),
                places=6, msg=entry["metric"])

    def test_thresholds_read_their_current_value_from_the_latest_quarter(self) -> None:
        """A threshold left at last quarter's reading would show a stale bar, so
        no entry types one: each names the series it reads, read back here."""
        latest = len(self.staging["periods"]) - 1
        raw = self.staging["next_kpi"]["quantified"]
        self.assertEqual(len(self.entries), len(raw))
        for entry, source in zip(self.entries, raw):
            self.assertNotIn("current", source, source["metric"])
            parts = source["reads"].split(".")
            if parts[0] == "increment_share":
                shares = increments(self.staging["by_sector"], rms.SECTOR_ORDER, latest)
                expected = round(shares[parts[1]] / sum(shares.values()) * 100, 1)
            elif parts[0] == "group_revenue":
                expected = self.staging["group_revenue"][parts[1]][latest]
            else:
                expected = self.staging[parts[0]][parts[1]][parts[2]][latest]
            self.assertEqual(entry["current"], expected, source["metric"])

    def test_every_threshold_can_be_settled_by_the_next_release(self) -> None:
        """A first- or third-quarter release has no income statement, so a profit
        threshold there would be one nobody could check until the next half."""
        _, number = quarter_of(self.staging["periods"][-1])
        revenue_only = number % 4 + 1 in (1, 3)
        for entry in self.staging["next_kpi"]["quantified"]:
            self.assertEqual(entry["unit"], "pct", entry["metric"])
            if revenue_only:
                self.assertTrue(any(word in entry["metric"] for word in ("增速", "增量")), entry["metric"])
        for entry in self.staging["next_kpi"]["full_year_only"]:
            self.assertEqual(set(entry), {"metric", "current", "threshold", "why"}, entry["metric"])

    # ── boundary ────────────────────────────────────────────────────────────
    def test_no_market_expectation_or_rating_is_published(self) -> None:
        forbidden = ["市场预期", "目标价", "一致预期", "评级", "增持", "买入"]
        surfaces: list[str] = []
        for exhibit in self.exhibits:
            surfaces.append(exhibit["title"])
            surfaces.extend(s["name"] for s in exhibit.get("series", []))
            surfaces.extend(g["name"] for g in exhibit.get("groups", []))
            surfaces.extend(str(label) for label in exhibit.get("xlabels", []))
        for table in self.payload["tables"]:
            surfaces.append(table["title"])
            surfaces.extend(table["headers"])
            surfaces.extend(str(cell) for row in table["rows"] for cell in row)
        for surface in surfaces:
            for term in forbidden:
                self.assertNotIn(term, surface, surface[:60])

    def test_money_is_printed_in_euro_not_dollars(self) -> None:
        """A dollar sign on a euro filer is a unit error a reader cannot see through."""
        for table in self.payload["tables"]:
            if "AI capex" in table["title"]:
                continue  # the shared cross-page block is in US dollars by design
            for row in table["rows"]:
                for cell in row:
                    self.assertNotIn("$", str(cell), table["title"][:30])
        window = cn_count(len(self.staging["periods"]))
        quarterly = next(table for table in self.payload["tables"] if f"近{window}季分板块" in table["title"])
        self.assertTrue(any("€" in cell for row in quarterly["rows"] for cell in row))

    def test_the_page_states_that_this_filer_reaches_no_sec_schedule(self) -> None:
        joined = " ".join(self.payload["notes"])
        self.assertIn("12g3-2", joined)
        self.assertIn("20-F", joined)
        self.assertIn("10-Q", joined)
        subtitle = self.payload["subtitle"]
        self.assertIn("IFRS", subtitle)
        self.assertIn("欧元", subtitle)
        self.assertIn("半年", subtitle)

    def test_the_page_publishes_no_guidance_block(self) -> None:
        """There is no numeric guidance to settle, so there is nothing to draw."""
        self.assertIsNone(self.payload["guidance"])
        titles = [table["title"] for table in self.payload["tables"]]
        self.assertTrue(any("准指引" in title for title in titles), titles)
        quasi = next(t for t in self.payload["tables"] if "准指引" in t["title"])
        self.assertEqual(len(quasi["rows"]), len(self.staging["quasi_guidance"]["items"]))

    def test_the_outlook_card_counts_the_periods_the_sentence_has_stood(self) -> None:
        releases = self.staging["outlook"]["releases"]
        self.assertIn(f"展望{span_words(releases)}没换过一个字", self.payload["brief"])
        self.assertIn(f"手上 {len(releases)} 份公告的 Outlook 段", self.payload["brief"])

    # ── the shapes the renderer reads ───────────────────────────────────────
    def test_the_page_carries_the_cross_page_capex_table(self) -> None:
        titles = [table["title"] for table in self.payload["tables"]]
        self.assertTrue(any("AI capex" in title for title in titles), titles)

    def test_exhibits_are_numbered_in_render_order_and_refs_resolve(self) -> None:
        numbers = [ex["n"] for ex in self.exhibits]
        self.assertEqual(numbers, list(range(2, 2 + len(numbers))))
        text = json.dumps(self.payload, ensure_ascii=False)
        self.assertNotRegex(text, r"\{EX_[A-Z_]+\}")
        self.assertNotRegex(text, PLACEHOLDER)

    def test_tables_are_numbered_after_the_exhibits(self) -> None:
        last = max(ex["n"] for ex in self.exhibits)
        self.assertEqual([table["n"] for table in self.payload["tables"]],
                         list(range(last + 1, last + 1 + len(self.payload["tables"]))))

    def test_every_exhibit_carries_a_note_and_a_source_line(self) -> None:
        for exhibit in self.exhibits:
            self.assertTrue(exhibit.get("note"), exhibit["title"])
            self.assertTrue(exhibit.get("src_extra"), exhibit["title"])

    def test_every_series_is_as_long_as_its_own_axis(self) -> None:
        for exhibit in self.exhibits:
            width = len(exhibit.get("xlabels") or [])
            self.assertGreater(width, 0, exhibit["title"][:40])
            for key in ("values",):
                if isinstance(exhibit.get(key), list):
                    self.assertEqual(len(exhibit[key]), width, exhibit["title"][:40])
            for key in ("series", "groups", "stacks"):
                for block in exhibit.get(key) or []:
                    self.assertEqual(len(block["values"]), width,
                                     f"{exhibit['title'][:40]} / {block.get('name')}")

    def test_literal_text_fields_carry_no_markup(self) -> None:
        for key in ("headline", "title", "subtitle", "tracker"):
            self.assertNotIn("<", self.payload[key], key)
        for section in self.payload["sections"]:
            self.assertNotIn("<", section["title"], section["id"])
            self.assertNotIn("<", section["description"], section["id"])
        for note in self.payload["notes"]:
            self.assertNotIn("<", note, note[:40])
        for table in self.payload["tables"]:
            self.assertNotIn("<", table["title"], table["title"][:40])
            for row in table["rows"]:
                for cell in row:
                    self.assertNotIn("<", str(cell), str(cell)[:40])

    def test_table_dicts_carry_only_the_keys_the_renderer_reads(self) -> None:
        for table in self.payload["tables"]:
            self.assertEqual(set(table), {"n", "title", "headers", "rows"},
                             table["title"][:40])

    def test_every_table_row_matches_its_header_width(self) -> None:
        for table in self.payload["tables"]:
            for row in table["rows"]:
                self.assertEqual(len(row), len(table["headers"]), table["title"][:40])

    def test_no_exhibit_uses_a_renderer_branch_this_page_cannot_feed(self) -> None:
        """`gs_bar` without a `yoy` block draws a NaN reference line, and
        `stacked_dual` hardcodes its right axis at 60. This page uses neither,
        and saying so here is what keeps a later exhibit from reaching for one
        without reading those branches first."""
        kinds = {ex["kind"] for ex in self.exhibits}
        self.assertNotIn("gs_bar", kinds)
        self.assertNotIn("stacked_dual", kinds)
        self.assertLessEqual(kinds, {"lines", "diverging_bars", "grouped_bars", "bridge_bar"})

    # ── counts printed in prose ─────────────────────────────────────────────
    def test_every_tally_the_page_prints_is_the_tally_in_the_data(self) -> None:
        """A number inside a sentence has nothing checking it.

        The first draft of this page printed five of them by hand and **all five
        were wrong**: the threshold chart said three lines had been breached when
        four had, the Asia-Pacific note said five quarters of eight were below
        the threshold when four were, the métier trend note said all seven lines
        were double-digit in the peak quarter when five were and said watches had
        been positive three quarters running when it had alternated, and the
        acceleration note said three of the four accelerating lines came off a
        window low when two did. Every gate was green for all five: they are
        finite strings in a note, so `payload_guard` sees nothing, the render
        gate sees nothing, and no assertion read them.

        So each one is now derived in the builder, and this reads the number back
        out of the rendered sentence and re-derives it here from the staging by a
        different route. Two independent paths to the same integer is the point;
        asserting the builder against itself would not be.
        """
        latest = len(self.staging["periods"]) - 1
        sectors = self.staging["by_sector"]
        pace = self.by_ref["EX_SECTOR_PACE"]["title"] + " " + self.by_ref["EX_SECTOR_PACE"]["note"]
        trend = self.by_ref["EX_SECTOR_TREND"]["note"]

        # the pace chart: accelerating lines, and those whose previous reading was the window low
        accelerating = [k for k in rms.SECTOR_ORDER
                        if sectors[k]["cc_pct"][latest] > sectors[k]["cc_pct"][latest - 1]]
        off_low = sum(1 for k in accelerating
                      if sectors[k]["cc_pct"][latest - 1]
                      == min(sectors[k]["cc_pct"][i] for i in rated(self.staging)))
        self.assertIn(f"：{len(accelerating)} 个在加速", pace)
        if len(accelerating) >= 2 and off_low:
            self.assertIn(f"这{cn_count(len(accelerating))}条里有 {off_low} 条", pace)

        # the trend chart: double-digit lines in the window's peak quarter
        cc = self.staging["group_revenue"]["cc_pct"]
        peak = max(rated(self.staging), key=lambda i: cc[i])
        if f"{self.staging['periods'][peak]} 那一格是本窗口的顶" in trend:
            double = sum(1 for k in rms.SECTOR_ORDER if sectors[k]["cc_pct"][peak] >= 10.0)
            self.assertIn(f"{cn_count(len(rms.SECTOR_ORDER))}条线里有 {double} 条在两位数以上", trend)
        watches = sectors["watches"]["cc_pct"]
        if "钟表那条线" in trend:
            self.assertIn(f"最近四季里有 {sum(1 for v in watches[-4:] if v > 0)} 季为正", trend)

        # headroom: how many thresholds are on the wrong side of their own line
        headroom_ex = next(ex for ex in self.exhibits if ex.get("ylab") == "距阈值 %")
        text = headroom_ex["title"] + " " + headroom_ex["note"]
        breached = [e for e in self.entries
                    if headroom(e["direction"], e["threshold"], e["current"]) < 0]
        self.assertIn(f"本季已有 {len(breached)} 条落在阈值的另一侧", text)
        if breached:
            self.assertIn(f"共 {len(breached)} 条", text)
        for entry in breached:
            self.assertIn(entry["metric"], text)

        # each threshold chart: quarters on either side of its own line
        by_metric = {e["metric"]: e for e in self.entries}
        raw = {e["metric"]: e for e in self.staging["next_kpi"]["quantified"]}
        for metric in self.staging["next_kpi"]["threshold_charts"]:
            kind, key, _ = raw[metric]["reads"].split(".")
            # Only the quarters that carry a rate are scored: a quarter with a
            # euro amount and no growth beside it is neither above the
            # threshold nor below it.
            values = [self.staging[kind][key]["cc_pct"][i] for i in rated(self.staging)]
            threshold = by_metric[metric]["threshold"]
            chart = next(ex for ex in self.exhibits if ex["title"].startswith(
                f"{self.staging[kind][key]['label']}固定汇率增速与 {threshold:g}% 阈值"))
            self.assertIn(f"{sum(1 for v in values if v >= threshold)} 季在阈值之上", chart["title"])
            if kind == "by_region":
                self.assertIn(f"{sum(1 for v in values if v < threshold)} 季低于 {threshold:g}%", chart["note"])

    def test_the_section_and_table_headings_count_their_own_contents(self) -> None:
        kpi = self.staging["next_kpi"]
        section = next(s for s in self.payload["sections"] if s["id"] == "next_quarter")
        self.assertIn(f"{len(kpi['quantified'])} 条可在", section["description"])
        self.assertIn(f"{len(kpi['full_year_only'])} 条要等", section["description"])
        quasi = next(t for t in self.payload["tables"] if "准指引" in t["title"])
        self.assertIn(f"{len(quasi['rows'])} 条", quasi["title"])
        later = next(t for t in self.payload["tables"] if "只有全年业绩" in t["title"])
        self.assertIn(f"{len(later['rows'])} 条", later["title"])
        self.assertIn(f"{cn_count(len(self.payload['sections']))}段排列", self.payload["notes"][0])
        for index, section in enumerate(self.payload["sections"], start=1):
            self.assertTrue(section["title"].startswith(f"{cn_ordinal(index)}、"), section["title"])

    def test_every_year_on_year_pair_on_the_half_year_clock_is_same_named(self) -> None:
        """A half-year series indexes 「a year earlier」 differently from a
        quarterly one, and a chart whose x axis is a list of regions hides the
        time span inside the title. Both ends of every such comparison on this
        page have to be two halves with the same name, or two full years.
        """
        halves = {h["label"]: h for h in self.staging["half_years"]}
        segments = self.staging["h1_segments"]
        year = int(segments["period"].split()[1])
        # The segment chart takes its two ends from two columns the note itself
        # heads with the same half of two years, so there is no index
        # arithmetic to get wrong -- asserted here so a later rewrite cannot
        # quietly introduce some.
        for row in segments["rows"]:
            self.assertLessEqual({"roi_now", "roi_prior", "revenue_now", "revenue_prior"}, set(row))
        self.assertEqual([g["name"] for g in self.by_ref["EX_SEGMENT_ROI"]["groups"]],
                         [f"上半年 {year - 1}", f"上半年 {year}"])
        self.assertEqual(segments["period"], self.staging["half_years"][-1]["label"])
        # The capex chart's second halves are the filed year minus the filed
        # first half of the SAME year, and they are compared same-named.
        years = sorted({h["label"].split()[1] for h in self.staging["half_years"]})
        for y in years:
            if f"H2 {y}" in halves:
                # Almost-equal, not equal: the backfilled years are printed to
                # one decimal, so a derived half is a float difference and exact
                # equality is not a property the data can have.
                self.assertAlmostEqual(
                    halves[f"H2 {y}"]["operating_investments_eur_m"],
                    self.staging["full_years"][y]["operating_investments_eur_m"]
                    - halves[f"H1 {y}"]["operating_investments_eur_m"], places=4, msg=y)
        capex = self.by_ref["EX_CAPEX"]
        self.assertEqual(capex["xlabels"], years)
        for group in capex["groups"]:
            self.assertEqual(len(group["values"]), len(years))

    def test_every_derived_value_prints_the_digit_the_exact_figure_prints(self) -> None:
        """The renderer rounds a second time, and that pass can move a digit.

        A payload value stored at the precision it will be printed at has
        already lost the information the display rounding needs. This page did
        it once: 香水与美妆's share of the quarter's constant-currency increment
        is −4.3527%, the builder stored −4.35, and `pct1` printed −4.3% —
        rounding away from the true figure rather than towards it. Nothing saw
        it: the number is finite, the length is right, and it is one digit.

        The first version of this test guessed at the defect from the shape of
        the stored number — "expressible in one more place than it is printed
        at" — and immediately flagged H1 2024's margin, which is 41.950959 and
        lands on that grid by coincidence. A test that cannot tell a flattened
        value from a coincidence is the same mistake as measuring rotated text
        with an axis-aligned box. So this recomputes each figure from the
        staging and compares the two rendered strings, which is the only
        comparison that answers the question.

        One kind of point is stored at the company's precision on purpose: a
        first half whose printed margin the recomputation from rounded amounts
        does not round to (H1 2026 is printed 41.0%; 3,351 / 8,163 is 41.05%).
        """
        def pct1(v): return f"{v:.1f}%"
        def pct2(v): return f"{v:.2f}%"
        def pp1(v): return f"{v:+.1f}pp"

        latest = len(self.staging["periods"]) - 1
        group = self.staging["group_revenue"]
        by_ref = self.by_ref
        mismatch = []

        def compare(where, stored, exact, fmt):
            if fmt(stored) != fmt(exact):
                mismatch.append(f"{where}: stored prints {fmt(stored)}, "
                                f"the exact figure prints {fmt(exact)}")

        # the wedge is a difference of two printed rates
        for i, stored in enumerate(by_ref["EX_WEDGE"]["values"]):
            if group["published_pct"][i] is None or group["cc_pct"][i] is None:
                self.assertIsNone(stored)
                continue
            compare(f"EX_WEDGE[{i}]", stored,
                    group["published_pct"][i] - group["cc_pct"][i], pp1)

        # shares of revenue and of the constant-currency increment
        for ref, block, order in (("EX_SECTOR_MIX", "by_sector", rms.SECTOR_ORDER),
                                  ("EX_REGION_MIX", "by_region", rms.REGION_ORDER)):
            shares = increments(self.staging[block], order, latest)
            total = sum(shares.values())
            weight, share = by_ref[ref]["groups"]
            for i, key in enumerate(order):
                compare(f"{ref} weight {key}", weight["values"][i],
                        self.staging[block][key]["revenue_eur_m"][latest]
                        / group["revenue_eur_m"][latest] * 100, pct1)
                compare(f"{ref} share {key}", share["values"][i],
                        shares[key] / total * 100, pct1)

        # the half-year margins, printed to two places
        halves = {h["label"]: h for h in self.staging["half_years"]}
        years = by_ref["EX_HALF_MARGIN"]["xlabels"]
        for series, prefix in zip(by_ref["EX_HALF_MARGIN"]["series"], ("H1", "H2")):
            for i, year in enumerate(years):
                stored = series["values"][i]
                if stored is None:
                    continue
                half = halves[f"{prefix} {year}"]
                exact = half["recurring_operating_income_eur_m"] / half["revenue_eur_m"] * 100
                printed = half.get("roi_margin_printed_pct")
                if printed is not None and round(exact, 1) != printed:
                    exact = printed
                compare(f"EX_HALF_MARGIN {prefix} {year}", stored, exact, pct2)

        # segment margin change in percentage points
        operating = [x for x in self.staging["h1_segments"]["rows"] if x["key"] != "unallocated"]
        for i, row in enumerate(operating):
            compare(f"EX_SEGMENT_MARGIN {row['key']}",
                    by_ref["EX_SEGMENT_MARGIN"]["values"][i],
                    row["roi_now"] / row["revenue_now"] * 100
                    - row["roi_prior"] / row["revenue_prior"] * 100, pp1)

        self.assertEqual(mismatch, [], "\n".join(mismatch))

    def test_the_published_payload_matches_a_fresh_build(self) -> None:
        published = js_payload(ROOT / "data" / "rms.js", "window.DASH")
        self.assertEqual(published, self.payload)


class RmsChecksTest(unittest.TestCase):
    """The page's quarter and half against a record keyed separately from the release.

    `_checks` is typed once per roll from the results release itself, with the
    page and table each figure was read from; the builder never reads it
    (`test_data_only_roll`). Each assertion compares what the builder computed
    from the arrays with that separate reading.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.s = json.loads(rms.STAGING_PATH.read_text(encoding="utf-8"))
        cls.checks = cls.s["_checks"]
        cls.payload = rms.build_payload(cls.s)
        cls.text = json.dumps(cls.payload, ensure_ascii=False)
        cls.halves = {h["label"]: h for h in cls.s["half_years"]}

    def test_the_page_names_the_checked_quarter_and_half(self) -> None:
        c = self.checks
        self.assertIn(f"{c['period']} 收入与 {c['half']} 利润仪表盘", self.payload["title"])
        self.assertIn(f"收入截至 {c['period_end']} 单季", self.payload["subtitle"])
        self.assertIn(f"发布 {c['release_date']}", self.payload["subtitle"])
        self.assertEqual(self.payload["latest"]["full_financial_period_label"], c["half"])

    def test_the_quarter_ends_on_the_checked_figures(self) -> None:
        c, s = self.checks, self.s
        g = s["group_revenue"]
        self.assertEqual(s["periods"][-1], c["period"])
        self.assertEqual(g["revenue_eur_m"][-1], c["quarter_revenue_eur_m"])
        self.assertEqual(g["prior_year_eur_m"][-1], c["quarter_prior_year_eur_m"])
        self.assertEqual(g["published_pct"][-1], c["quarter_published_pct"])
        self.assertEqual(g["cc_pct"][-1], c["quarter_cc_pct"])
        # the printed published rate is the two printed revenues' ratio, to a tenth
        self.assertEqual(round((c["quarter_revenue_eur_m"] / c["quarter_prior_year_eur_m"] - 1) * 100, 1),
                         c["quarter_published_pct"])
        for key, value in c["quarter_sector_cc_pct"].items():
            self.assertEqual(s["by_sector"][key]["cc_pct"][-1], value, key)
        for key, value in c["quarter_region_cc_pct"].items():
            self.assertEqual(s["by_region"][key]["cc_pct"][-1], value, key)
        for key, value in c["quarter_region_published_pct"].items():
            self.assertEqual(s["by_region"][key]["published_pct"][-1], value, key)

    def test_the_half_ends_on_the_checked_figures(self) -> None:
        c, s = self.checks, self.s
        year = int(c["half"].split()[1])
        half, prior = self.halves[c["half"]], self.halves[f"H1 {year - 1}"]
        self.assertEqual(s["half_years"][-1]["label"], c["half"])
        cumulative = s["first_half"]["group"]
        self.assertEqual((cumulative["revenue_eur_m"], cumulative["prior_year_eur_m"],
                          cumulative["published_pct"], cumulative["cc_pct"]),
                         (c["half_revenue_eur_m"], c["half_prior_year_eur_m"],
                          c["half_published_pct"], c["half_cc_pct"]))
        self.assertEqual((half["revenue_eur_m"], prior["revenue_eur_m"]),
                         (c["half_revenue_eur_m"], c["half_prior_year_eur_m"]))
        self.assertEqual((half["recurring_operating_income_eur_m"], prior["recurring_operating_income_eur_m"]),
                         (c["recurring_operating_income_eur_m"], c["recurring_operating_income_prior_year_eur_m"]))
        self.assertEqual(half["net_profit_group_eur_m"], c["net_profit_group_eur_m"])
        self.assertEqual(half["operating_cash_flows_eur_m"], c["operating_cash_flows_eur_m"])
        self.assertEqual((half["operating_investments_eur_m"], prior["operating_investments_eur_m"]),
                         (c["operating_investments_eur_m"], c["operating_investments_prior_year_eur_m"]))
        self.assertEqual(s["full_years"][str(year - 1)]["operating_investments_eur_m"],
                         c["operating_investments_prior_full_year_eur_m"])
        self.assertEqual(half["adjusted_fcf_eur_m"], c["adjusted_fcf_eur_m"])
        income = s["h1_income"]
        lines = {key: (cur, prev) for key, _, cur, prev in income["lines"]}
        self.assertEqual(lines["revenue"], (c["half_revenue_eur_m"], c["half_prior_year_eur_m"]))
        self.assertEqual(lines["recurring_operating_income"],
                         (c["recurring_operating_income_eur_m"], c["recurring_operating_income_prior_year_eur_m"]))
        self.assertEqual(lines["cost_of_sales"][0], c["cost_of_sales_eur_m"])
        self.assertEqual(lines["gross_margin"][0], c["gross_margin_eur_m"])
        self.assertEqual(lines["sga"][0], c["sga_eur_m"])
        self.assertEqual(lines["other_income_expenses"][0], c["other_income_expenses_eur_m"])
        self.assertEqual(list(income["eps_diluted_eur"]), [c["diluted_eps_eur"], c["diluted_eps_prior_year_eur"]])
        self.assertEqual(s["next_kpi"]["settles_on"], c["next_quarter_release"])
        self.assertEqual(s["next_kpi"]["full_year_settles_on"], c["full_year_release"])

    def test_the_series_carries_the_margins_the_company_printed(self) -> None:
        """The recomputation must round to the printed margin, or the printed one is stored."""
        c = self.checks
        year = int(c["half"].split()[1])
        for half, printed in ((self.halves[c["half"]], c["recurring_operating_margin_pct"]),
                              (self.halves[f"H1 {year - 1}"], c["recurring_operating_margin_prior_year_pct"])):
            with self.subTest(half=half["label"]):
                self.assertEqual(round(rms.official_margin(half), 1), printed)
                if round(half["roi_margin_pct"], 1) != printed:
                    self.assertEqual(half.get("roi_margin_printed_pct"), printed)
        full = self.s["full_years"][str(year - 1)]
        computed = full["recurring_operating_income_eur_m"] / full["revenue_eur_m"] * 100
        if round(computed, 1) != c["prior_full_year_recurring_operating_margin_pct"]:
            self.assertEqual(full.get("roi_margin_printed_pct"), c["prior_full_year_recurring_operating_margin_pct"])

    def test_the_page_prints_the_company_margin_where_the_recomputation_disagrees(self) -> None:
        """3,351 / 8,163 is 41.05%, which rounds to 41.1%; Hermès printed 41.0%."""
        c = self.checks
        year = int(c["half"].split()[1])
        self.assertIn(f"经常性经营利润率 {c['recurring_operating_margin_pct']:.1f}%", self.payload["headline"])
        bridge = next(ex for ex in exhibits(self.payload) if ex.get("ref") == "EX_MARGIN_BRIDGE")
        self.assertIn(f"{c['recurring_operating_margin_prior_year_pct']:.1f}% → "
                      f"{c['recurring_operating_margin_pct']:.1f}%", bridge["title"])
        seasonality = next(ex for ex in exhibits(self.payload) if ex.get("ref") == "EX_HALF_MARGIN")
        # Printed only while every year in the window has H1 above H2. On the
        # 21-half window two years break it -- 2020 (COVID: 21.5% against 37.1%)
        # and, less excusably for the old sentence, 2017 (34.3% against 34.9%)
        # in an ordinary year. The page stops claiming it; this checks that the
        # claim and the sentence move together.
        blocks = self.halves
        pairs = [y for y in sorted({h["label"].split()[1] for h in self.s["half_years"]})
                 if f"H1 {y}" in blocks and f"H2 {y}" in blocks]
        always = all(
            blocks[f"H1 {y}"]["recurring_operating_income_eur_m"] / blocks[f"H1 {y}"]["revenue_eur_m"]
            > blocks[f"H2 {y}"]["recurring_operating_income_eur_m"] / blocks[f"H2 {y}"]["revenue_eur_m"]
            for y in pairs)
        self.assertFalse(always, "re-read the seasonality sentence: it holds again")
        self.assertNotIn("被广泛引用", seasonality["note"])
        for label in (c["half"], f"H1 {year - 1}"):
            half = self.halves[label]
            computed = half["roi_margin_pct"]
            printed = half.get("roi_margin_printed_pct")
            if printed is not None and round(computed, 1) != printed:
                with self.subTest(half=label):
                    self.assertNotIn(f"{computed:.2f}%", self.text)
                    self.assertNotIn(f"率 {computed:.1f}%", self.text)
                    self.assertIn(f"{printed:.1f}%（公司印）", self.text)

    def test_the_headline_and_card_print_the_checked_figures(self) -> None:
        c = self.checks
        head = self.payload["headline"]
        _, number = quarter_of(c["period"])
        self.assertIn(f"第{cn_ordinal(number)}季度收入 €{c['quarter_revenue_eur_m']:,}M", head)
        self.assertIn(f"published {c['quarter_published_pct']:+.1f}% 而固定汇率 {c['quarter_cc_pct']:+.1f}%", head)
        self.assertEqual(rms.headline_metrics(self.s),
                         [f"{c['period'].split()[0]} revenue €{c['quarter_revenue_eur_m']:,}M",
                          f"固定汇率 {c['quarter_cc_pct']:+.1f}%",
                          f"{c['half'].split()[0]} 经营利润率 {c['recurring_operating_margin_pct']:.1f}%"])


def roll_back_a_quarter(staging: dict) -> dict:
    """The series as it stood on the release before its latest one.

    The latest quarter comes off every array; a half or a year that quarter
    closed comes off too, with every block stamped for it. The blocks stamped
    for the quarter go (there is no earlier original in git: the page was built
    on its first quarter), and the source list names the release the page
    would then be built on.
    """
    s = copy.deepcopy(staging)
    last = s["periods"][-1]
    year, number = quarter_of(last)
    width = len(s["periods"])
    s["periods"] = s["periods"][:-1]
    prev = s["periods"][-1]

    def trim(block: dict) -> None:
        for field, value in list(block.items()):
            if isinstance(value, list) and len(value) == width:
                block[field] = value[:-1]
    trim(s["group_revenue"])
    for name in ("by_sector", "by_region"):
        for block in s[name].values():
            trim(block)
    for key in ("release_dates", "release_titles"):
        s[key].pop(last)
    blocks = list(QUARTER_BLOCKS) + ["_checks"]
    if number in (2, 4):
        s["half_years"] = [h for h in s["half_years"] if h["label"] != f"H{number // 2} {year}"]
        if number == 4:
            s["full_years"].pop(str(year))
        blocks += HALF_BLOCKS
    for key in blocks:
        s.pop(key, None)
    s["outlook"]["releases"] = s["outlook"]["releases"][:-1]
    prev_year, prev_number = quarter_of(prev)
    s["latest"] = {"period": prev,
                   "period_end": f"{prev_year}-{prev_number * 3:02d}-{30 if prev_number in (2, 3) else 31}",
                   "analysis_date": s["release_dates"][prev],
                   "audit_status": {2: "limited_review", 4: "audited"}.get(prev_number, "unaudited")}
    s["sources"] = [src for src in s["sources"] if not src["label"].startswith(rms.release_prefix(last))]
    if not any(src["label"].startswith(rms.release_prefix(prev)) for src in s["sources"]):
        s["sources"].append({"label": f"{rms.release_prefix(prev)}（{s['release_dates'][prev]}）",
                             "url": "https://finance.hermes.com/en/publications/"})
    return s


def roll_forward_a_quarter(staging: dict) -> dict:
    """A made-up next quarter, revenue only, on the same window length.

    Every line grows at a round made-up rate on the prior-year base the window
    already holds; the blocks stamped for the latest quarter go, the half's stay.
    """
    s = copy.deepcopy(staging)
    last = s["periods"][-1]
    year, number = quarter_of(last)
    nxt = f"Q{number % 4 + 1} {year + (number == 4)}"
    ago = s["periods"].index(f"Q{number % 4 + 1} {year - 1 + (number == 4)}")
    s["periods"] = s["periods"][1:] + [nxt]
    rates = dict(zip(rms.SECTOR_ORDER, (8.0, 4.0, 3.0, 5.0, 1.0, -2.0, 2.0)))
    rates.update(zip(rms.REGION_ORDER, (4.0, 6.0, 7.0, 4.0, 9.0, 1.0)))

    def roll(block: dict, rate: float) -> None:
        base = block["revenue_eur_m"][ago]
        for field in ("revenue_eur_m", "published_pct", "cc_pct", "prior_year_eur_m"):
            block[field] = block[field][1:]
        block["prior_year_eur_m"].append(base)
        block["cc_pct"].append(rate)
        block["published_pct"].append(round(rate - 2.0, 1))
        block["revenue_eur_m"].append(round(base * (1 + (rate - 2.0) / 100)))
    for name in ("by_sector", "by_region"):
        for key, block in s[name].items():
            roll(block, rates[key])
    group = s["group_revenue"]
    base = group["revenue_eur_m"][ago]
    for field in ("revenue_eur_m", "published_pct", "cc_pct", "prior_year_eur_m"):
        group[field] = group[field][1:]
    total = sum(s["by_sector"][k]["revenue_eur_m"][-1] for k in rms.SECTOR_ORDER)
    group["prior_year_eur_m"].append(base)
    group["revenue_eur_m"].append(total)
    group["published_pct"].append(round((total / base - 1) * 100, 1))
    grown = sum(increments(s["by_sector"], rms.SECTOR_ORDER, len(s["periods"]) - 1).values())
    group["cc_pct"].append(round(grown / base * 100, 1))
    s["by_region"]["asia_pacific_ex_japan"]["revenue_eur_m"][-1] += (
        total - sum(s["by_region"][k]["revenue_eur_m"][-1] for k in rms.REGION_ORDER))
    released = f"{year + (number == 4)}-10-22"
    s["release_dates"][nxt] = released
    s["release_titles"][nxt] = "made-up revenue release"
    for key in list(QUARTER_BLOCKS) + ["_checks"]:
        s.pop(key, None)
    s["outlook"]["releases"].append({"date": released, "label": f"{nxt} 收入公告"})
    s["latest"] = {"period": nxt, "period_end": released, "analysis_date": released,
                   "audit_status": "unaudited"}
    s["sources"].append({"label": f"{rms.release_prefix(nxt)}（{released}）",
                         "url": "https://finance.hermes.com/en/publications/"})
    return s


class RmsRollTest(unittest.TestCase):
    """What a roll can change without touching the builder."""

    # Words that exist only because a stamped block said them.
    STORY_ONLY = ("这是本季管理层叙述的支点", "有时候是去年太差", "都没有解释原因",
                  "集团的单点依赖没有消失", "大中华区的量化增速", "不是汇率转向",
                  "生产线上的个别资产", "同期期间平均股价下跌", "日元贬值同时压低了",
                  "管理层口头说下半年会加速", "法国大企业特别税", "准指引",
                  "分析师在电话会上按亚太约 5% 的提价幅度提问", "兑现了上一季管理层")
    # Some of these ride a condition as well as a block. 「有时候是去年太差」 is
    # printed only while an accelerating métier's previous reading is the
    # window's own low, and on the 42-quarter window nothing is: the 2020 floor
    # is lower than anything since. That is the page working, not failing -- the
    # sentence was true of an eight-quarter window and is false of this one --
    # so the guard below asks that most of these are live rather than all.
    STORY_ONLY_LIVE_FLOOR = 12

    @classmethod
    def setUpClass(cls) -> None:
        cls.s = json.loads(rms.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = rms.build_payload(cls.s)
        cls.text = json.dumps(cls.payload, ensure_ascii=False)

    def test_a_block_stamped_for_another_period_stops_the_build(self) -> None:
        for key in QUARTER_BLOCKS + HALF_BLOCKS:
            stale = copy.deepcopy(self.s)
            stale[key]["period"] = "Q1 1999" if key in QUARTER_BLOCKS else "H1 1999"
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    rms.build_payload(stale)

    def test_the_quarters_own_release_must_be_in_the_sources(self) -> None:
        bare = copy.deepcopy(self.s)
        prefix = rms.release_prefix(self.s["periods"][-1])
        bare["sources"] = [src for src in bare["sources"] if not src["label"].startswith(prefix)]
        self.assertLess(len(bare["sources"]), len(self.s["sources"]))
        with self.assertRaisesRegex(ValueError, "sources"):
            rms.build_payload(bare)

    def test_a_period_without_its_blocks_leaves_them_out(self) -> None:
        bare = copy.deepcopy(self.s)
        for key in QUARTER_BLOCKS + HALF_BLOCKS:
            del bare[key]
        payload = rms.build_payload(bare)
        text = json.dumps(payload, ensure_ascii=False)
        live = [phrase for phrase in self.STORY_ONLY if phrase in self.text]
        self.assertGreaterEqual(
            len(live), self.STORY_ONLY_LIVE_FLOOR,
            "too few of these sentences are being printed at all -- this check "
            "goes vacuous if the list drifts away from what the page says")
        for phrase in self.STORY_ONLY:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, text)
        self.assertNotIn("next_quarter", [s["id"] for s in payload["sections"]])
        for index, section in enumerate(payload["sections"], start=1):
            self.assertTrue(section["title"].startswith(f"{cn_ordinal(index)}、"))
        numbers = [ex["n"] for ex in exhibits(payload)]
        self.assertEqual(numbers, list(range(2, 2 + len(numbers))))
        self.assertEqual([t["n"] for t in payload["tables"]],
                         list(range(numbers[-1] + 1, numbers[-1] + 1 + len(payload["tables"]))))
        self.assertNotRegex(text, PLACEHOLDER)
        self.assertIn(f"{cn_count(len(payload['sections']))}段排列", payload["notes"][0])

    def test_the_quarter_before_builds_from_the_series_alone(self) -> None:
        rolled = roll_back_a_quarter(self.s)
        payload = rms.build_payload(rolled)
        prev, half = rolled["periods"][-1], rolled["half_years"][-1]["label"]
        self.assertEqual(payload["latest"]["disclosed_period_label"], prev)
        self.assertEqual(payload["latest"]["full_financial_period_label"], half)
        profit = f"{half} 利润" if half.startswith("H1") else f"{half.split()[1]} 全年利润"
        self.assertIn(f"{prev} 收入与 {profit}仪表盘", payload["title"])
        self.assertTrue(payload["headline"].startswith(f"第{cn_ordinal(quarter_of(prev)[1])}季度收入"))
        text = own_text(payload)
        self.assertNotIn(self.s["periods"][-1], text)
        if half != self.s["half_years"][-1]["label"]:
            self.assertNotIn(self.s["half_years"][-1]["label"], text)
        self.assertNotRegex(text, PLACEHOLDER)
        self.assertNotIn("未接入：以及", text)
        self.assertIn(f"展望{span_words(rolled['outlook']['releases'])}没换过一个字", payload["brief"])

    def test_a_revenue_only_quarter_builds_from_the_series_alone(self) -> None:
        rolled = roll_forward_a_quarter(self.s)
        payload = rms.build_payload(rolled)
        nxt = rolled["periods"][-1]
        self.assertEqual(payload["latest"]["disclosed_period_label"], nxt)
        self.assertIn(f"{nxt} 收入与", payload["title"])
        text = json.dumps(payload, ensure_ascii=False)
        self.assertNotRegex(text, PLACEHOLDER)
        # the half's own words stay, but not the ones written for the quarter it was reported in
        if "half_story" in rolled:
            self.assertIn("生产线上的个别资产", text)
            self.assertNotIn("与本季普遍的读法相反", text)
        self.assertNotIn(self.s["periods"][0], payload["sections"][0]["exhibits"][0]["xlabels"])

    def test_the_flip_sentence_appears_only_while_the_flips_are_confined(self) -> None:
        """The other direction of a computed sentence, which is the harder one.

        On the eight-quarter window every sign flip fell in Japan and
        Asia-Pacific, and the page said so. On the 42-quarter window there are
        15 of them and three of the six regions are involved, so the page stops
        saying it -- correctly, and silently, which is why this exists. Removing
        the Americas flips should bring the sentence back; if it does not, the
        sentence has stopped being computed from the data at all.
        """
        self.assertNotIn("全部落在日本与亚太（除日本）", self.text)
        s = copy.deepcopy(self.s)
        keep = rated(s)
        block = s["by_region"]["americas"]
        touched = 0
        for i in keep:
            if block["published_pct"][i] * block["cc_pct"][i] < 0:
                block["published_pct"][i] = abs(block["published_pct"][i]) * (
                    1 if block["cc_pct"][i] > 0 else -1)
                touched += 1
        self.assertEqual(touched, 3, "re-measure: the Americas flips moved")
        self.assertIn("全部落在日本与亚太（除日本）",
                      json.dumps(rms.build_payload(s), ensure_ascii=False))

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        """Make each finding false on a copy of the series: its words must go."""
        latest = len(self.s["periods"]) - 1
        skipped: list[str] = []
        cases = []

        s = copy.deepcopy(self.s)
        s["by_sector"]["other_products"]["cc_pct"][latest] = -1.0
        cases += [(s, "个板块里唯一负增长的一个"), (s, "唯一没有回到正区间的是"),
                  (s, "是唯一一条本季仍在零以下并且还在下探的线")]
        s = copy.deepcopy(self.s)
        g = s["group_revenue"]
        keep = rated(s)
        wedge = [None if g["published_pct"][i] is None or g["cc_pct"][i] is None
                 else g["published_pct"][i] - g["cc_pct"][i] for i in range(len(g["cc_pct"]))]
        peak = max(keep, key=lambda i: wedge[i])
        g["published_pct"][peak + 2] = round(g["cc_pct"][peak + 2] + wedge[peak + 1] + 0.5, 1)
        cases += [(s, "两条线一路分开"), (s, "转为拖累并逐季加深")]
        s = copy.deepcopy(self.s)
        next(h for h in s["half_years"] if h["label"].startswith("H2"))["roi_margin_pct"] = 50.0
        cases += [(s, "每一次都高于下半年"), (s, "上半年每次都高于下半年"), (s, "全年落在")]
        s = copy.deepcopy(self.s)
        france = next(r for r in s["h1_segments"]["rows"] if r["key"] == "france")
        france["roi_now"] = france["roi_prior"] + 40
        cases += [(s, "全部来自未分配一栏"), (s, "全靠未分配一栏"), (s, "唯一量与利润率同时改善的是")]
        s = copy.deepcopy(self.s)
        next(line for line in s["h1_income"]["lines"] if line[0] == "cost_of_sales")[2] -= 10
        cases.append((s, "一分未涨"))
        s = copy.deepcopy(self.s)
        s["by_region"]["france"]["published_pct"][latest] += 0.5
        cases.append((s, "法国两根柱一样高"))
        s = copy.deepcopy(self.s)
        s["half_story"]["capex"]["target_eur_m"] = 1300
        cases += [(s, "问题在于今年的爬坡比往年弱"), (s, "自由现金流的顺风"), (s, "账上的同比下降")]
        s = copy.deepcopy(self.s)
        next(h for h in s["half_years"] if h["label"].startswith("H2"))["revenue_eur_m"] += 1
        cases.append((s, "个财年的上下半年相加都等于公司申报的全年"))
        s = copy.deepcopy(self.s)
        cc = s["group_revenue"]["cc_pct"]
        top = max(rated(s), key=lambda i: cc[i])
        leather = s["by_sector"]["leather_goods_saddlery"]["cc_pct"]
        leather[top + 1] = leather[top] + 1
        cases.append((s, "那一格是本窗口的顶"))
        s = copy.deepcopy(self.s)
        del next(h for h in s["half_years"] if h["label"] == s["first_half"]["period"])["roi_margin_printed_pct"]
        cases.append((s, "（公司印）"))
        for staging, phrase in cases:
            with self.subTest(phrase=phrase):
                if phrase not in self.text:
                    # The finding is already false on today's window, so there
                    # is no sentence to knock out. 「转为拖累并逐季加深」 went
                    # this way when the window widened: it needs the wedge to
                    # fall monotonically from its peak to its trough, which
                    # holds over eight quarters and does not over thirty-eight.
                    skipped.append(phrase)
                    continue
                self.assertNotIn(phrase, json.dumps(rms.build_payload(staging), ensure_ascii=False))

        # Five, and each is the window working rather than a bug:
        # 「转为拖累并逐季加深」 needs a monotone wedge from peak to trough;
        # 「每一次都高于下半年」/「上半年每次都高于下半年」/「全年落在」 all rest on H1
        # beating H2 in every year, which 2017 and 2020 break; and
        # 「上下半年相加都等于公司申报的全年」 stops holding once the filed 2021
        # revenue is the printed 8,982 instead of the spliced 8,982.1.
        self.assertLessEqual(
            len(skipped), 5,
            f"too many findings are already false, so this check is mostly "
            f"skipping: {skipped}")

    def test_worded_findings_switch_with_the_data(self) -> None:
        """Where a finding has two wordings, the data picks one."""
        latest = len(self.s["periods"]) - 1
        region_title = next(ex for ex in exhibits(self.payload) if ex.get("ref") == "EX_REGION_RATES")["title"]
        # the region flagged in the title becomes the fastest of the six
        s = copy.deepcopy(self.s)
        s["by_region"]["japan"]["cc_pct"][latest] = max(b["cc_pct"][latest] for b in s["by_region"].values()) + 1
        title = next(ex for ex in exhibits(rms.build_payload(s)) if ex.get("ref") == "EX_REGION_RATES")["title"]
        if "日本 published" in region_title and "一个口径说它在萎缩" in region_title:
            self.assertNotIn("全集团最快", region_title)
            self.assertIn("全集团最快", title)
            self.assertNotIn("快的", title)
        # watches' two double-digit falls become consecutive
        s = copy.deepcopy(self.s)
        watches = s["by_sector"]["watches"]["cc_pct"]
        deep = [i for i, v in enumerate(watches[:len(watches) // 2])
                if v is not None and v <= -10]
        if len(deep) == 2 and deep[1] - deep[0] == 2:
            watches[deep[0] + 1] = -12.0
            changed = json.dumps(rms.build_payload(s), ensure_ascii=False)
            self.assertIn("两度出现两位数负增长", self.text)
            self.assertNotIn("是连续的两位数负增长", self.text)
            self.assertIn("是连续的两位数负增长", changed)
            self.assertNotIn("两度出现两位数负增长", changed)
        # the half's two quarters add up to the cumulative table exactly
        s = copy.deepcopy(self.s)
        half = s["first_half"]
        year = half["period"].split()[1]
        q1, q2 = s["periods"].index(f"Q1 {year}"), s["periods"].index(f"Q2 {year}")
        rows = [(half["group"], s["group_revenue"])] + [
            (half[name][key], s[name][key]) for name in ("by_sector", "by_region") for key in half[name]]
        for row, block in rows:
            for field in ("revenue_eur_m", "prior_year_eur_m"):
                row[field] = block[field][q1] + block[field][q2]
        changed = json.dumps(rms.build_payload(s), ensure_ascii=False)
        self.assertIn(f"{year} 年第一、二季度相加等于公司印出的上半年累计各行", changed)
        self.assertNotIn("与公司印出的上半年累计各行最多差", changed)


if __name__ == "__main__":
    unittest.main()
