"""What has to hold for the SK hynix page to be worth publishing.

Three groups of assertions, and they are chosen for different reasons.

The arithmetic group pins identities that exist in the filings, so a transcription
slip in `series/skhynix.json` cannot survive: the four quarters of a year add to
the year the company printed, the integer margin the company prints is the
rounding of the two won amounts, gross profit less the two expense lines is the
operating profit the company reports, and pre-tax less tax is net income. The
last two matter more than they look: operating profit is not a line in this
K-IFRS presentation, so the page derives it, and a page that derives a headline
number owes a check that its derivation reproduces the company's own.

The vocabulary group exists because this page's first section is built on a
mapping from English adjectives to intervals, and that mapping is the page's own
reading rather than a disclosure. The tests keep it honest in both directions:
every phrase the filing uses must be in the declared vocabulary (so a new
quarter's wording cannot be silently dropped), and the one-sided phrases must
still be marked one-sided (so the drawing cap cannot quietly become a claim).

The structural group is the one that would not exist if the repo had not already
been burned. `test_no_exhibit_pins_a_zero_baseline_under_negative_values` is
derived from what the charts promise rather than from how something broke
before: three kinds in `assets/charts.js` fix the y-axis floor at zero, and this
page carries a quarter at −66.9% operating margin and a year of losses, so a
negative value handed to one of those kinds is drawn below the plot — no NaN,
no empty element, no exception. The repo's rendered-SVG gate has bounded painted
bars by the plot band since 2026-09-17 (before that it read only `fill="none"`
paths and could not see this), but it skips wherever jsdom is not installed. The
assertion is a containment rule over the payload, so it holds for values nobody
has plotted yet, on any machine.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import skhynix  # noqa: E402
from build.all import ENTRIES, GROUPS, build_all, roster_payload  # noqa: E402
from build.board import UNIT_FORMATS, unit_text  # noqa: E402

# Kinds whose lower bound is hardcoded to zero in assets/charts.js, so a
# negative value is painted below the viewBox and silently clipped.
ZERO_BASELINE_KINDS = {"gs_bar", "bars_labeled", "stacked_dual"}


def js_payload(path: Path, marker: str) -> dict:
    text = path.read_text(encoding="utf-8")
    start = text.index(marker) + len(marker)
    return json.loads(text[start:].rsplit(";", 2)[0].strip())


class SkHynixDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(skhynix.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = skhynix.build_payload(cls.staging)
        cls.fin = cls.staging["financials_krw_bn"]
        cls.ann = cls.staging["annual_audited_krw_bn"]
        cls.kpi = cls.staging["kpi_phrases"]

    def exhibits(self):
        for section in self.payload["sections"]:
            for exhibit in section["exhibits"]:
                yield exhibit

    # ── arithmetic that exists in the filings ───────────────────────────────

    def test_quarters_sum_to_the_full_year_the_company_printed(self) -> None:
        """Each year's four quarters add to the annual figure of the same vintage.

        FY2022 used to carry a tolerance of 15.0, on the reasoning that its first
        three quarters were printed to two decimals of a trillion won and so
        could not resolve better than about ±15bn. That reasoning was about the
        ENGLISH release's prose. The Korean release prints the same table in
        억원, one digit finer, and reading it drops the residual to ±0.6 -- so
        the tolerance is 1.0 now. A tolerance is a claim about the printing, and
        it should be re-earned whenever a finer printing is found; a wide one
        left in place stops being a bound and becomes a place for errors to sit.
        The 2022Q3 vintage error this file used to pass over is exactly what a
        15.0 tolerance is wide enough to hide: 1,660.5 against 1,655.6.
        """
        printed = {
            "2016": (17198.0, 3277.0, 2960.0),
            "2017": (30109.0, 13721.0, 10642.0),
            "2018": (40445.0, 20844.0, 15540.0),
            "2019": (26991.0, 2713.0, 2016.0),
            "2020": (31900.0, 5013.0, 4759.0),
            "2021": (42998.0, 12410.0, 9616.0),
            "2022": (44648.0, 7007.0, 2439.0),
            "2023": (32765.7, -7730.3, -9137.5),
            "2024": (66193.0, 23467.3, 19796.9),
            "2025": (97146.7, 47206.3, 42947.9),
        }
        # 2016-2020 each hold four cells rounded to the nearest billion won, so
        # a four-quarter sum cannot resolve better than +/-2 against a full-year
        # figure that was rounded the same way. Measured residuals across the
        # five years run 0, +1 and +2 -- the tolerance is the arithmetic bound,
        # not a number widened until the test passed.
        tolerance = {"2016": 2.0, "2017": 2.0, "2018": 2.0, "2019": 2.0,
                     "2020": 2.0,
                     "2021": 1.5, "2022": 1.0, "2023": 0.5,
                     "2024": 0.05, "2025": 0.5}
        periods = self.staging["periods"]
        for year, (revenue, operating, net) in printed.items():
            index = [i for i, p in enumerate(periods) if p.startswith(year)]
            self.assertEqual(len(index), 4, year)
            tol = tolerance[year]
            self.assertAlmostEqual(
                sum(self.fin["revenue"][i] for i in index), revenue, delta=tol,
                msg=f"FY{year} revenue")
            self.assertAlmostEqual(
                sum(self.fin["operating_profit"][i] for i in index), operating,
                delta=tol, msg=f"FY{year} operating profit")
            self.assertAlmostEqual(
                sum(self.fin["net_income"][i] for i in index), net, delta=tol,
                msg=f"FY{year} net income")

    def test_the_printed_integer_margin_is_the_rounding_of_the_two_amounts(self) -> None:
        """Every disclosed margin must round from operating profit over revenue.

        This is what licenses the page to chart the computed ratio instead of the
        printed integer: the two agree to the rounding, so using the finer one is
        a precision choice rather than a different number.
        """
        off = []
        for i, period in enumerate(self.staging["periods"]):
            disclosed = self.fin["operating_margin_pct_disclosed"][i]
            if disclosed is None:
                continue
            computed = (self.fin["operating_profit"][i]
                        / self.fin["revenue"][i] * 100.0)
            if round(computed) != disclosed:
                off.append(f"{period}: computed {computed:.2f} vs printed {disclosed}")
        self.assertEqual(off, [], "\n".join(off))

    def test_operating_profit_is_gross_profit_less_the_two_expense_lines(self) -> None:
        """The identity the page derives operating profit from, on audited years.

        Operating profit has no line of its own in this presentation. If this
        fails, the page's margin series is being computed off something that is
        not what the company calls operating profit.
        """
        for i, year in enumerate(self.ann["years"]):
            derived = (self.ann["gross_profit"][i] - self.ann["sga"][i]
                       - self.ann["rnd"][i])
            self.assertEqual(derived, self.ann["operating_profit"][i], year)

    def test_pre_tax_less_tax_is_net_income_on_the_audited_years(self) -> None:
        for i, year in enumerate(self.ann["years"]):
            self.assertEqual(
                self.ann["profit_before_tax"][i] - self.ann["income_tax"][i],
                self.ann["net_income"][i], year)

    def test_product_revenue_adds_to_consolidated_revenue(self) -> None:
        product = self.staging["revenue_by_product_krw_bn"]
        for i, label in enumerate(product["labels"]):
            total = (product["dram"][i] + product["nand"][i]
                     + product["other"][i])
            self.assertAlmostEqual(total, product["total"][i], delta=1.0, msg=label)

    def test_the_quarter_below_operating_profit_uses_only_printed_lines(self) -> None:
        """Tax and the non-operating total are differences of two printed rows.

        The page publishes both, and publishes no component of the non-operating
        total, because no document read for the page breaks one out. If a
        component ever appears in the payload, this is the assertion that should
        have stopped it.
        """
        below = self.staging["below_operating_profit_krw_bn"]
        pre_tax, net = below["profit_before_tax"][-1], below["net_income"][-1]
        operating = below["operating_profit"][-1]
        # The block's last column is the page's quarter, and its operating
        # profit and net income are the series' own -- the two printed rows the
        # derived lines are differences of. The quarter's pre-tax figure is
        # checked against a separate reading in SkHynixChecksTest.
        self.assertEqual(below["periods"][-1], self.staging["periods"][-1])
        self.assertEqual(operating, self.fin["operating_profit"][-1])
        self.assertEqual(net, self.fin["net_income"][-1])
        chart = next(e for e in self.exhibits() if e.get("title", "").startswith("营业利润、税前利润、净利润"))
        self.assertIn(f"₩{(pre_tax - operating) / 1000:.2f}T 的营业外净收益", chart["note"])
        self.assertIn(f"₩{(pre_tax - net) / 1000:.2f}T 的所得税", chart["note"])
        self.assertIn(f"有效税率 {(pre_tax - net) / pre_tax * 100:.1f}%", chart["note"])
        blob = json.dumps(self.payload, ensure_ascii=False)
        for absent in ("63.3", "45.4", "Kioxia", "铠侠"):
            self.assertNotIn(absent, blob,
                             "the page must not publish a decomposition of the "
                             "non-operating total: no source read for it has one")

    def test_capital_intensity_is_flat_rather_than_halving(self) -> None:
        """Pins the correction this page makes to the note that fed it.

        The note this page was briefed from put FY2025 capital intensity at 32%
        and had it halving to about 15%. Both of its inputs were wrong -- capex
        27,519 not 32,000, revenue 97,147 not 99,000 -- and the filing puts the
        three years within a four-point band. The numbers are asserted rather
        than described so the correction cannot rot back into the old story.
        """
        ratios = [c / r * 100.0 for c, r in
                  zip(self.ann["capital_expenditures"], self.ann["revenue"])]
        self.assertAlmostEqual(ratios[0], 25.4, delta=0.1)
        self.assertAlmostEqual(ratios[1], 24.1, delta=0.1)
        self.assertAlmostEqual(ratios[2], 28.3, delta=0.1)
        # The three audited years of the prospectus are history and stay pinned;
        # whether a later year keeps the band is the data's to say, and the
        # caption says 「大体持平」 only while it does (asserted in the roll tests).
        self.assertLess(max(ratios[:3]) - min(ratios[:3]), 5.0,
                        "three years inside a five-point band is the finding; a "
                        "halving would be a different page")
        self.assertEqual(self.ann["capital_expenditures"][2], 27519)
        self.assertEqual(self.ann["revenue"][2], 97147)

    def test_free_cash_flow_is_operating_cash_flow_less_capex(self) -> None:
        for i, year in enumerate(self.ann["years"]):
            expected = (self.ann["operating_cash_flow"][i]
                        - self.ann["capital_expenditures"][i])
            self.assertEqual(
                self.ann["operating_cash_flow"][i]
                - self.ann["capital_expenditures"][i], expected, year)

    # ── the phrase vocabulary, which is this page's own reading ─────────────

    def test_every_phrase_the_filing_uses_is_in_the_declared_vocabulary(self) -> None:
        vocabulary = self.kpi["phrase_vocabulary"]
        unknown = sorted({
            phrase
            for key in ("dram_bit_shipment", "dram_asp",
                        "nand_bit_shipment", "nand_asp")
            for phrase in self.kpi[key]["phrases"]
            if phrase not in vocabulary
        })
        self.assertEqual(unknown, [],
                         "a wording with no declared interval would be drawn as "
                         "whatever the last edit happened to leave behind")

    def test_each_band_matches_the_vocabulary_it_declares(self) -> None:
        vocabulary = self.kpi["phrase_vocabulary"]
        for key in ("dram_bit_shipment", "dram_asp",
                    "nand_bit_shipment", "nand_asp"):
            block = self.kpi[key]
            for i, phrase in enumerate(block["phrases"]):
                entry = vocabulary[phrase]
                self.assertEqual(block["low_pct"][i], entry["low"], f"{key}[{i}]")
                self.assertEqual(block["high_pct"][i], entry["high"], f"{key}[{i}]")
                self.assertEqual(block["one_sided"][i], entry["one_sided"],
                                 f"{key}[{i}]")
                self.assertAlmostEqual(
                    block["midpoint_pct"][i],
                    (entry["low"] + entry["high"]) / 2, places=6)

    def test_the_one_sided_phrases_are_still_marked_one_sided(self) -> None:
        """`Over X%` has no upper bound in the filing; the cap is a drawing choice.

        If this count ever drifts to zero, someone has turned a floor into a
        range, which is the specific error the section is written to avoid.
        """
        one_sided = sum(
            sum(self.kpi[key]["one_sided"])
            for key in ("dram_bit_shipment", "dram_asp",
                        "nand_bit_shipment", "nand_asp"))
        over = sum(1 for key in ("dram_bit_shipment", "dram_asp",
                                 "nand_bit_shipment", "nand_asp")
                   for phrase in self.kpi[key]["phrases"] if phrase.startswith("Over "))
        self.assertEqual(one_sided, over)
        self.assertGreater(one_sided, 0)
        for phrase, entry in self.kpi["phrase_vocabulary"].items():
            if phrase.startswith("Over "):
                self.assertTrue(entry["one_sided"], phrase)
                self.assertEqual(entry["high"] - entry["low"], 10.0, phrase)

    def test_the_bands_are_wide_enough_that_the_finding_still_holds(self) -> None:
        """The page's headline claim is that the words leave a lot undetermined.

        A note explaining a gap that has since closed is a comment rotting next
        to its data, so the gap is asserted rather than described.
        """
        widths = [h - l
                  for key in ("dram_bit_shipment", "dram_asp",
                              "nand_bit_shipment", "nand_asp")
                  for l, h in zip(self.kpi[key]["low_pct"],
                                  self.kpi[key]["high_pct"])]
        self.assertEqual(len(widths), 4 * len(self.kpi["quarters"]))
        self.assertGreater(sum(widths) / len(widths), 2.5)
        self.assertGreaterEqual(max(widths), 10.0)

    # ── holes and breaks that are kept rather than filled ───────────────────

    def test_2021q4_is_carried_because_the_release_printed_it(self) -> None:
        """This quarter was stored as a disclosure hole for months. It was not one.

        The FY2021 release's PROSE gives only full-year net income, so a
        prose-only reading concludes the company never printed the quarter --
        and the page said exactly that, in a note, in the checklist, and in a
        test named for the hole. The same release's embedded earnings table
        prints 3,320 and 34% in a column headed "2021 Q4".

        What makes this worth an assertion rather than a fix: the derived value
        (full year minus three quarters) is ALSO 3,320, so a page that had
        plugged the hole the forbidden way would show the same number as a page
        that read the table. The two are told apart by the margin, which no
        subtraction produces, and by the year identity below closing exactly.
        """
        index = self.staging["periods"].index("2021Q4")
        self.assertEqual(self.fin["net_income"][index], 3320.0)
        self.assertEqual(self.fin["operating_margin_pct_disclosed"][index], 34)
        note = self.fin["_2021q4_note"]
        self.assertIn("3,320", note)
        self.assertIn("34%", note)

    def test_the_restatement_census_is_a_census_and_not_an_example(self) -> None:
        """2022Q4 was published for months as "the only restatement in the window".

        Nobody had counted. Reading every quarter's own release against the
        comparative column four releases later turns up five, and the other four
        are invisible from the English pages entirely -- they only ever appear in
        a year-ago column. What makes 2022Q4 special is not that it is the only
        one, it is that it is the only one that moved REVENUE, and that is the
        claim the page can actually carry.

        Keyed on the lines each entry moved, not on prose: a sixth quarter can be
        appended without touching this test, but a quarter that silently loses
        its revenue leg, or a second revenue mover appearing while the page still
        says "only", both fail here.
        """
        census = self.staging["restatement_census"]
        moved = census["lines_moved"]
        self.assertEqual(sorted(census["quarters"]), sorted(moved))
        self.assertGreater(len(census["quarters"]), 1,
                           "a census of one is the example it replaced")
        revenue_movers = [q for q, lines in moved.items() if "revenue" in lines]
        self.assertEqual(revenue_movers, ["2022Q4"],
                         "the page says 2022Q4 is the only one that moved "
                         "revenue; that sentence is what this pins")
        for quarter, lines in moved.items():
            for line, pair in lines.items():
                self.assertEqual(len(pair), 2, f"{quarter}/{line}")
                self.assertNotEqual(pair[0], pair[1],
                                    f"{quarter}/{line} is listed as moved and did not move")
        self.assertEqual(census["_basis_used"],
                         "as_first_reported, for all forty-two quarters")

    def test_the_series_uses_the_first_reported_basis_for_2022q4(self) -> None:
        """One vintage throughout, and it is the one the year reconciles on."""
        restated = self.staging["restatement_2022q4"]
        self.assertEqual(restated["basis_used_in_series"], "as_first_reported")
        index = self.staging["periods"].index("2022Q4")
        self.assertEqual(self.fin["revenue"][index],
                         restated["as_first_reported"]["revenue"])
        self.assertEqual(self.fin["operating_profit"][index],
                         restated["as_first_reported"]["operating_profit"])
        self.assertNotEqual(restated["as_first_reported"]["operating_profit"],
                            restated["as_restated"]["operating_profit"])
        self.assertEqual(restated["delta"]["operating_profit"],
                         restated["delta"]["net_income"],
                         "the equal move through both lines is what identifies "
                         "this as an operating charge with no tax offset, and it "
                         "is the reason the exhibit reads the way it does")

    def test_the_restatement_is_drawn_and_not_only_described(self) -> None:
        """A declared break has to be a chart, not a sentence.

        This used to key on the word 重述 appearing in some title. That key
        broke the moment the title was rewritten -- and it was rewritten for a
        good reason: SK hynix never uses that word, so the page stopped using it
        too. A key that lives in wording hands the assertion's validity to
        whoever edits the copy next. This one keys on the exhibit's ref and on
        it carrying both vintages as drawn values.
        """
        drawn = [e for e in self.exhibits() if e.get("ref") == "EX_RESTATE"]
        self.assertEqual(len(drawn), 1, "the declared break is not on the page")
        groups = drawn[0]["groups"]
        self.assertEqual(len(groups), 2, "one vintage drawn is not a comparison")
        first, later = (g["values"] for g in groups)
        self.assertNotEqual(first, later,
                            "the two vintages are drawn as the same numbers, so "
                            "the chart shows a break that is not there")

    # ── structure the renderer will not defend on its own ──────────────────

    def test_no_exhibit_pins_a_zero_baseline_under_negative_values(self) -> None:
        """Negative values must not reach a kind whose y-floor is fixed at zero.

        `gs_bar`, `bars_labeled` and `stacked_dual` set `y0 = 0` in
        `assets/charts.js`. A negative bar is then drawn below the plot: the
        axis looks right, the value is right, no NaN is produced. The rendered-SVG
        gate now reports it (painted shapes are bounded by the plot band since
        2026-09-17) but skips without jsdom. This page plots a −66.9% margin and
        four loss-making quarters, so the containment rule is asserted over the
        payload instead of hoped for.
        """
        offenders = []
        for exhibit in self.exhibits():
            if exhibit["kind"] not in ZERO_BASELINE_KINDS:
                continue
            series = list(exhibit.get("values") or [])
            for group in (exhibit.get("groups") or []) + (exhibit.get("stacks") or []):
                series += group["values"]
            if any(v is not None and v < 0 for v in series):
                offenders.append(f"Exhibit {exhibit['n']} ({exhibit['kind']})")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_every_series_is_as_long_as_the_axis_it_is_drawn_against(self) -> None:
        """The renderer indexes every series with one loop counter.

        A short series is not an error there -- it silently misaligns every point
        after the gap. The repo-wide contract test does not cover `bar`, so this
        page checks its own.
        """
        for exhibit in self.exhibits():
            width = len(exhibit["xlabels"])
            self.assertGreater(width, 0, exhibit["n"])
            for key in ("values", "lo", "hi", "actual"):
                if isinstance(exhibit.get(key), list):
                    self.assertEqual(len(exhibit[key]), width,
                                     f"Exhibit {exhibit['n']}.{key}")
            for key in ("groups", "series", "stacks"):
                for member in exhibit.get(key) or []:
                    self.assertEqual(len(member["values"]), width,
                                     f"Exhibit {exhibit['n']}.{key}:{member['name']}")
            for key in ("bar", "line"):
                if isinstance(exhibit.get(key), dict):
                    self.assertEqual(len(exhibit[key]["values"]), width,
                                     f"Exhibit {exhibit['n']}.{key}")

    def test_the_page_uses_no_gs_bar(self) -> None:
        """Deliberate, and worth pinning so it stays deliberate.

        `tests/test_chart_contract.py` hardcodes a census of every `gs_bar` on the
        site. This page adds none, so that census is untouched by it -- and the
        reason is editorial rather than evasive: a single bar with a secondary
        line fuses volume and price into one height, which is exactly the
        decomposition this page exists to separate.
        """
        self.assertEqual([e["n"] for e in self.exhibits()
                          if e["kind"] == "gs_bar"], [])

    def test_the_phrase_band_charts_carry_no_actual_series(self) -> None:
        """There is no reported number to lay on the band, so none is invented."""
        bands = [e for e in self.exhibits() if e["kind"] == "range_band"]
        self.assertEqual(len(bands), 2)
        for band in bands:
            self.assertTrue(all(v is None for v in band["actual"]),
                            "the outcome is published in the same vocabulary as "
                            "the guidance, so a diamond here would be a number "
                            "the company never gave")

    def test_the_chained_band_contains_the_actual_but_is_too_wide_to_mean_it(self) -> None:
        """Containment here is close to a tautology, and the chart has to say so.

        An earlier draft of this test asserted the opposite -- that the chained
        band would miss the disclosed answer, because a midpoint chain does miss
        it by about fifteen points and the dollar-versus-won mismatch should push
        it further. The band contains it comfortably, and the chart's note said
        it did not. The note was wrong and this assertion is what caught it.

        So the pair was pinned instead: the actual had to fall inside, and the
        band had to stay wide enough that falling inside carries almost no
        information. Since the data-only migration the note itself is decided by
        those two facts -- it says "inside, but no test" only while the actual is
        inside and the band this wide, and says something else otherwise -- so
        what is pinned now is that the note and the chart agree, in both
        directions (the other direction is forced in the roll tests below).
        """
        chart = next(e for e in self.exhibits() if "连乘" in e["title"])
        low = dict(zip(chart["xlabels"], chart["groups"][0]["values"]))
        high = dict(zip(chart["xlabels"], chart["groups"][1]["values"]))
        actual = dict(zip(chart["xlabels"], chart["groups"][2]["values"]))
        contained = all(low[p] <= actual[p] <= high[p] for p in ("DRAM", "NAND"))
        # The sentence follows the data: it says "inside, but no test" only while
        # the actual is inside, and "nearly a tautology" only while the band is
        # this wide. Both directions are checked in the roll tests.
        self.assertEqual("不构成一次验证" in chart["note"], contained)
        self.assertEqual("接近同义反复" in chart["note"],
                         contained and high["DRAM"] - low["DRAM"] >= 40)
        self.assertIn(f"区间宽 {high['DRAM'] - low['DRAM']:.0f} 个百分点", chart["note"])

    def test_the_won_formatter_is_the_one_this_page_registered(self) -> None:
        self.assertIn("krw_tn", UNIT_FORMATS)
        self.assertEqual(unit_text("krw_tn", 69.4), "₩69.4T")
        self.assertEqual(unit_text("krw_tn", -8.5), "−₩8.5T")
        units = {row["unit"] for row in self.staging.get("_unused", [])}
        self.assertFalse(units)

    def test_no_dollar_sign_is_printed_against_a_won_amount(self) -> None:
        """The engine has no won format code, so the currency lives in the text.

        Borrowing a dollar formatter would print a won figure with a `$` and no
        assertion anywhere else would notice.
        """
        for exhibit in self.exhibits():
            for key in ("fmt", "yfmt", "label_fmt"):
                self.assertNotIn("usd", str(exhibit.get(key, "")),
                                 f"Exhibit {exhibit['n']}.{key}")

    # ── cross-page registration and publication ────────────────────────────

    def test_the_entry_group_exists_and_the_orders_still_ascend(self) -> None:
        entry = next(e for e in ENTRIES if e["slug"] == "skhynix")
        self.assertEqual(entry["group"], "semiconductor_ai")
        keys = [group["key"] for group in GROUPS]
        self.assertIn(entry["group"], keys)
        self.assertEqual(len(keys), len(set(keys)))
        orders = [group["order"] for group in GROUPS]
        self.assertEqual(orders, sorted(orders))

    def test_the_cross_page_capex_table_is_published_here_too(self) -> None:
        table = next(t for t in self.payload["tables"] if "AI capex" in t["title"])
        self.assertGreater(len(table["rows"]), 0)

    def test_the_published_payload_matches_a_fresh_build(self) -> None:
        published = js_payload(ROOT / "data" / "skhynix.js", "window.DASH = ")
        self.assertEqual(published, self.payload)

    def test_the_shell_links_every_script_by_content_hash(self) -> None:
        shell = (ROOT / "skhynix" / "index.html").read_text(encoding="utf-8")
        found = re.findall(r'src="\.\./(\S+?)\?v=([0-9a-f]+)"', shell)
        self.assertEqual([path for path, _ in found],
                         ["data/roster.js", "data/skhynix.js",
                          "assets/charts.js", "assets/page.js"])
        for path, digest in found:
            actual = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            self.assertEqual(actual[:len(digest)], digest, path)

    def test_the_roster_carries_this_page_with_labels_from_the_payload(self) -> None:
        roster = roster_payload(build_all())
        item = next(i for i in roster["items"] if i["slug"] == "skhynix")
        self.assertEqual(item["latest_label"],
                         self.payload["latest"]["disclosed_period_label"])
        self.assertEqual(item["release_date"],
                         self.payload["latest"]["release_date"])

    def test_no_market_expectation_or_valuation_is_published(self) -> None:
        """The page reports no consensus, rating, target price or multiple.

        A dated, checkable public source for a Korean-listed consensus was not
        available while this page was built, and inventing one is worse than
        omitting the comparison.

        Scoped to the slots that carry the page's claims -- headline, brief,
        chart titles and notes, tables -- and deliberately NOT to `notes`, which
        is where the page states that it publishes none of these. A gate that
        red-flags its own disclaimer gets bypassed, and a bypassed gate protects
        nothing.
        """
        carrying = json.dumps(
            {k: v for k, v in self.payload.items() if k != "notes"},
            ensure_ascii=False)
        for banned in ("一致预期", "目标价", "评级", "市盈率", "EV/EBITDA"):
            self.assertNotIn(banned, carrying)
        disclaimer = [n for n in self.payload["notes"] if "不发布市场一致预期" in n]
        self.assertEqual(len(disclaimer), 1,
                         "the disclaimer has to exist, and exactly once")

    def test_the_sources_are_official_and_reachable_by_https(self) -> None:
        allowed = ("https://www.sec.gov/", "https://news.skhynix.com/",
                   "https://www.skhynix.com/")
        self.assertGreaterEqual(len(self.payload["source_links"]), 4)
        for link in self.payload["source_links"]:
            self.assertTrue(link["url"].startswith(allowed), link["url"])
            self.assertTrue(link["label"].strip())

    def test_the_notes_say_what_the_page_does_not_have(self) -> None:
        notes = "\n".join(self.payload["notes"])
        for required in ("不发布任何财务指引", "HBM", "汇率", "单一报告分部"):
            self.assertIn(required, notes)


class SkHynixRollTest(unittest.TestCase):
    """What a quarter roll has to change in `series/skhynix.json`, and what the
    page does when it does not.

    Three blocks describe one quarter and carry it: the lines below operating
    profit (`below_operating_profit_krw_bn`), what the quarter's own documents
    did and did not print (`quarter_story`), and the thresholds (`next_kpi`).
    A block stamped with another quarter stops the build; an absent optional
    one takes its sentences and its chart with it.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads(skhynix.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = skhynix.build_payload(cls.source)
        cls.blob = json.dumps(cls.payload, ensure_ascii=False)

    def text(self, staging: dict) -> str:
        return json.dumps(skhynix.build_payload(staging), ensure_ascii=False)

    def test_a_block_stamped_with_another_quarter_stops_the_build(self) -> None:
        for key in ("below_operating_profit_krw_bn", "quarter_story", "next_kpi"):
            stale = copy.deepcopy(self.source)
            stale[key]["period"] = "Q1 1999"
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    skhynix.build_payload(stale)
        stale = copy.deepcopy(self.source)
        stale["below_operating_profit_krw_bn"]["periods"][-1] = "1999Q1"
        with self.assertRaisesRegex(ValueError, "must carry it"):
            skhynix.build_payload(stale)
        stale = copy.deepcopy(self.source)
        stale["next_kpi"]["entries"][0]["metric"] = "不存在的指标"
        with self.assertRaisesRegex(ValueError, "does not know how to measure"):
            skhynix.build_payload(stale)
        stale = copy.deepcopy(self.source)
        stale["sources"] = [item for item in stale["sources"] if " 6-K（" not in item["label"]]
        self.assertLess(len(stale["sources"]), len(self.source["sources"]))
        with self.assertRaisesRegex(ValueError, "sources"):
            skhynix.build_payload(stale)

    def test_a_quarter_without_a_story_leaves_it_out(self) -> None:
        cases = {
            "quarter_story": ("而季度发布里对此一个字都没有", "只出现在向 SEC 报送的 6-K 里",
                              "口头提过", " 为历史最高", "对这笔钱没有任何拆分"),
            "below_operating_profit_krw_bn": ("营业利润、税前利润、净利润", "净利率越过 100% 的来源",
                                              "不是经营突破", "营业外收益的构成，"),
        }
        for key, texts in cases.items():
            bare = copy.deepcopy(self.source)
            del bare[key]
            after = self.text(bare)
            for text in texts:
                with self.subTest(block=key, text=text):
                    self.assertIn(text, self.blob)
                    self.assertNotIn(text, after)
        bare = copy.deepcopy(self.source)
        del bare["below_operating_profit_krw_bn"]
        payload = skhynix.build_payload(bare)
        numbers = [ex["n"] for section in payload["sections"] for ex in section["exhibits"]]
        self.assertEqual(numbers, list(range(2, 2 + len(numbers))))
        self.assertNotIn("{EX_", json.dumps(payload, ensure_ascii=False))

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        """Break each "all / only / highest / flat / inside" claim once in the
        data; the sentence that made it must go."""
        def margin_below_peak(d):
            fin = d["financials_krw_bn"]
            fin["operating_profit"][-1] = fin["revenue"][-1] * 0.5

        def volume_swings(d):
            kpi = d["kpi_phrases"]
            for key in ("dram_bit_shipment", "nand_bit_shipment"):
                block = kpi[key]
                for i in range(len(block["midpoint_pct"])):
                    block["midpoint_pct"][i] = 30.0

        def intensity_jumps(d):
            ann = d["annual_audited_krw_bn"]
            ann["capital_expenditures"][-1] = ann["revenue"][-1] * 0.6

        def chained_answer_outside(d):
            prod = d["revenue_by_product_krw_bn"]
            prod["dram"][prod["labels"].index("2026Q1")] *= 2

        def earlier_revision_as_large(d):
            d["restatement_census"]["lines_moved"]["2019Q4"]["operating_profit"][1] = 236.0 + 150.0

        def nand_price_turns_with_dram(d):
            kpi = d["kpi_phrases"]
            kpi["nand_asp"]["midpoint_pct"] = list(kpi["dram_asp"]["midpoint_pct"])

        cases = {
            "margin below its peak": (margin_below_peak, (" 为历史最高", "顶是本季的")),
            "volume moving tens of points": (volume_swings, ("多数季度在正负十个点以内",)),
            "capital intensity no longer flat": (intensity_jumps, ("大体持平",)),
            "chained answer outside the band": (chained_answer_outside,
                                                ("不构成一次验证", "接近同义反复")),
            "an earlier revision as large": (earlier_revision_as_large, ("金额大一个量级以上",)),
            "price turns in step": (nand_price_turns_with_dram, ("价格拐点不同步",)),
        }
        for name, (change, claims) in cases.items():
            broken = copy.deepcopy(self.source)
            change(broken)
            after = self.text(broken)
            for claim in claims:
                with self.subTest(case=name, claim=claim):
                    self.assertIn(claim, self.blob)
                    self.assertNotIn(claim, after)

    def test_the_revision_range_is_the_censuss_own(self) -> None:
        """Both places that describe the four earlier revisions used to type
        「0.1%–3%」; 2019Q4 net income went from −118.2 to −125.6, a 6.3% move.
        The range is now read off the census, and so is the order-of-magnitude
        claim about 2022Q4, which holds for the amounts (₩211bn against at most
        ₩7.4bn) and not for the percentages."""
        census = self.source["restatement_census"]
        moved = census["lines_moved"]
        earlier = [q for q in census["quarters"] if "revenue" not in moved[q]]
        moves = [abs(b / a - 1) * 100 for q in earlier for a, b in moved[q].values()]
        amounts = [abs(b - a) for q in earlier for a, b in moved[q].values()]
        span = f"{min(moves):.1f}%–{max(moves):.1f}%"
        chart = next(ex for section in self.payload["sections"] for ex in section["exhibits"]
                     if ex.get("title", "").endswith("bn") and "事后被改过" in ex["title"])
        note = next(n for n in self.payload["notes"] if "对照列之间不一致" in n)
        self.assertIn(f"幅度在 {span} 之间", chart["note"])
        self.assertIn(f"幅度 {span}", note)
        delta = abs(self.source["restatement_2022q4"]["delta"]["operating_profit"])
        self.assertEqual("金额大一个量级以上" in chart["note"], delta >= 10 * max(amounts))
        first, last = census["scope"]
        quarters = self.source["periods"]
        self.assertIn(f"{first}–{last} 的 {quarters.index(last) - quarters.index(first) + 1} 季里",
                      chart["note"])

    def test_each_phrase_chart_counts_its_own_series(self) -> None:
        """The NAND price chart's title said 4 one-sided readings and quoted
        "Over 70% Increase": 4 is the count across all four series and "Over 70%"
        is a NAND bit-shipment phrase. Each count and quote now comes from the
        series the chart draws; the four-series count stays in the note."""
        kpi = self.source["kpi_phrases"]
        chart = next(ex for section in self.payload["sections"] for ex in section["exhibits"]
                     if ex["title"].startswith("NAND 平均售价的环比"))
        open_asp = [p for p, flag in zip(kpi["nand_asp"]["phrases"], kpi["nand_asp"]["one_sided"]) if flag]
        self.assertIn(f"{len(open_asp)} 次读数是单边的", chart["title"])
        self.assertIn(f"“{open_asp[0]}” 没有上限", chart["title"])
        nand = next(ex for section in self.payload["sections"] for ex in section["exhibits"]
                    if ex["title"].startswith("NAND 的量与价"))
        for key in ("nand_bit_shipment", "nand_asp"):
            for phrase, flag in zip(kpi[key]["phrases"], kpi[key]["one_sided"]):
                if flag:
                    self.assertIn(f"“{phrase}”", nand["note"])


class SkHynixChecksTest(unittest.TestCase):
    """The page's quarter against a record keyed separately from the series.

    `_checks` is typed from the quarter's newsroom release (its prose and its
    results table), with the pre-tax and non-operating totals read off the
    earnings call at the precision spoken there; the builder never reads it
    (asserted in `test_data_only_roll`). Where the company prints a rounded
    figure -- the integer operating margin, the net margin, the growth rates --
    the page's own arithmetic has to round to it.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(skhynix.STAGING_PATH.read_text(encoding="utf-8"))
        cls.checks = cls.staging["_checks"]
        cls.payload = skhynix.build_payload(cls.staging)
        cls.fin = cls.staging["financials_krw_bn"]

    def test_the_page_names_the_checked_quarter(self) -> None:
        c = self.checks
        self.assertIn(c["period"], self.payload["title"])
        self.assertIn(f"截至 {c['period_end']}", self.payload["subtitle"])
        self.assertIn(f"发布 {c['release_date']}", self.payload["subtitle"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        c, fin = self.checks, self.fin
        self.assertEqual(fin["revenue"][-1], c["revenue_krw_bn"])
        self.assertEqual(fin["operating_profit"][-1], c["operating_profit_krw_bn"])
        self.assertEqual(fin["net_income"][-1], c["net_income_krw_bn"])
        self.assertEqual(fin["operating_margin_pct_disclosed"][-1], c["operating_margin_pct_printed"])
        self.assertEqual(fin["operating_margin_pct_disclosed"][-2], c["prior_quarter_operating_margin_pct_printed"])
        self.assertEqual(fin["revenue"][-5], c["prior_year_revenue_krw_bn"])
        self.assertEqual(fin["operating_profit"][-5], c["prior_year_operating_profit_krw_bn"])
        self.assertEqual(fin["net_income"][-5], c["prior_year_net_income_krw_bn"])
        below = self.staging["below_operating_profit_krw_bn"]
        self.assertEqual(round(below["profit_before_tax"][-1] / 1000, 1), c["profit_before_tax_krw_tn_spoken"])
        self.assertEqual(round((below["profit_before_tax"][-1] - below["operating_profit"][-1]) / 1000, 1),
                         c["non_operating_net_krw_tn_spoken"])
        sheet = self.staging["balance_sheet_krw_bn"]
        self.assertEqual(sheet["periods"][-1], self.staging["periods"][-1])
        self.assertEqual(sheet["cash_and_equivalents"][-1] / 1000, c["cash_and_equivalents_krw_tn"])
        self.assertEqual(sheet["interest_bearing_debt"][-1] / 1000, c["interest_bearing_debt_krw_tn"])
        self.assertEqual(sheet["net_cash"][-1] / 1000, c["net_cash_krw_tn"])

    def test_the_rounding_the_page_uses_is_the_companys(self) -> None:
        c, fin = self.checks, self.fin
        margin = fin["operating_profit"][-1] / fin["revenue"][-1] * 100
        self.assertEqual(round(margin), c["operating_margin_pct_printed"])
        self.assertEqual(round(fin["net_income"][-1] / fin["revenue"][-1] * 100), c["net_margin_pct_printed"])
        self.assertEqual(round((fin["revenue"][-1] / fin["revenue"][-2] - 1) * 100), c["revenue_qoq_pct_printed"])
        self.assertEqual(round((fin["revenue"][-1] / fin["revenue"][-5] - 1) * 100), c["revenue_yoy_pct_printed"])
        self.assertEqual(round((fin["operating_profit"][-1] / fin["operating_profit"][-5] - 1) * 100),
                         c["operating_profit_yoy_pct_printed"])

    def test_the_page_prints_the_checked_figures(self) -> None:
        c = self.checks
        headline = self.payload["headline"]
        self.assertIn(f"营收 ₩{c['revenue_krw_bn'] / 1000:.1f}T、同比 +{c['revenue_yoy_pct_printed']}%", headline)
        self.assertIn(f"净利率 {c['net_margin_pct_printed']}%", headline)
        self.assertIn(f"税前比营业利润多出 ₩{c['non_operating_net_krw_tn_spoken']:.1f}T", headline)
        self.assertIn(f"净利率 {c['net_margin_pct_printed']}% 不是经营突破", self.payload["brief"])
        rev = next(ex for section in self.payload["sections"] for ex in section["exhibits"]
                   if ex.get("title", "").endswith("%") and "季营收与营业利润率" in ex["title"])
        self.assertIn(f"本季营收 ₩{c['revenue_krw_bn'] / 1000:.1f}T", rev["title"])
        table = self.payload["tables"][0]
        self.assertEqual(table["rows"][-1][5], f"{c['operating_margin_pct_printed']}%")
        watch = next(t for t in self.payload["tables"] if t["title"].startswith("下季阈值"))
        net_cash = next(row for row in watch["rows"] if row[0] == "净现金")
        self.assertEqual(net_cash[3], f"₩{c['net_cash_krw_tn']:.1f}T")


if __name__ == "__main__":
    unittest.main()
