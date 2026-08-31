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
negative value handed to one of those kinds is drawn below the canvas and
clipped — no NaN, no empty element, no exception, and the repo's own rendered-SVG
gate cannot see it because its out-of-canvas check only inspects `fill="none"`
paths. The assertion is a containment rule over the payload, so it holds for
values nobody has plotted yet.
"""

from __future__ import annotations

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
        below = self.staging["q2_2026_below_operating_profit_krw_bn"]
        pre_tax, net = below["profit_before_tax"][1], below["net_income"][1]
        operating = below["operating_profit"][1]
        self.assertAlmostEqual(pre_tax - net, 28785.8, delta=0.5)
        self.assertAlmostEqual(pre_tax - operating, 62165.8, delta=0.5)
        self.assertAlmostEqual((pre_tax - net) / pre_tax * 100, 23.46, delta=0.05)
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
        self.assertLess(max(ratios) - min(ratios), 5.0,
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
        self.assertEqual(one_sided, 4)
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
        self.assertEqual(len(widths), 52)
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
        `assets/charts.js`. A negative bar is then drawn below the viewBox and
        clipped by the browser: the axis looks right, the value is right, no NaN
        is produced, and the repo's rendered-SVG gate misses it because its
        out-of-canvas check only inspects `fill="none"` paths. This page plots a
        −66.9% margin and four loss-making quarters, so the containment rule is
        asserted over the payload instead of hoped for.
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

        So the pair is pinned instead: the actual must fall inside, and the band
        must stay wide enough that falling inside carries almost no information.
        If the band ever narrows to where containment is a real test, the note
        explaining why it is not one has to be rewritten, and this fails first.
        """
        chart = next(e for e in self.exhibits() if "连乘" in e["title"])
        low = dict(zip(chart["xlabels"], chart["groups"][0]["values"]))
        high = dict(zip(chart["xlabels"], chart["groups"][1]["values"]))
        actual = dict(zip(chart["xlabels"], chart["groups"][2]["values"]))
        for product in ("DRAM", "NAND"):
            self.assertLessEqual(low[product], actual[product], product)
            self.assertLessEqual(actual[product], high[product], product)
            self.assertGreater(high[product] - low[product], 40.0,
                               f"{product}: a band this wide is the finding; a "
                               f"narrow one would make containment meaningful "
                               f"and the note would then be misleading")
        self.assertIn("并不构成一次验证", chart["note"].replace("不构成一次验证",
                                                            "并不构成一次验证"))

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


if __name__ == "__main__":
    unittest.main()
