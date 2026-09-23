"""Reconciliation and shape tests for the MCO (Moody's) page.

Same purpose as the other companies': nothing derived reaches the page until it
has been checked against an identity the filer printed, or against a figure the
company disclosed separately.

This page rests on one licence and one distinction.

The licence is the guidance table's internal arithmetic. Moody's prints, in the
same EX-99.1, a reconciliation from GAAP diluted EPS to adjusted diluted EPS, a
second from operating margin to adjusted operating margin, and a third from
operating cash flow to free cash flow -- each with every bridging item named and
quantified. All three close exactly. That is what allows the page to treat the
full-year outlook table as arithmetic the company stands behind rather than as
a set of soft targets, so the tests pin all three to the cent and the tenth of a
point.

The distinction is between the two forecast horizons, and it is the whole point
of the guidance record in section one. Against the final (October) range the record looks like
every other "never missed" record on this site; against the initial (February)
range the same seven years look nothing like it. A test that only counted
"cleared its guidance" would not notice if the two were ever conflated, so this
one pins both tallies separately, and pins that they disagree.

A roll edits `series/mco.json` and nothing else (CLAUDE.md §9). Tallies,
extremes and years named on the page are recounted here from the series rather
than pinned; what stays pinned is history that a roll cannot move (FY2018's four
vintages, FY2022's cut, the FY2016-17 holes). What the quarter's release printed
is asserted from `_checks` (`McoChecksTest`), and what the owner's two analyses
concluded from `_checks["note"]` (`McoFourPartTest`); `McoRollTest` rolls the series a
quarter back and a quarter forward and tampers each stamped block; and
`McoFindingsTest` forces each judgement true and then false and checks that the
words follow.

One more thing is pinned because it was a live trap rather than a hypothesis:
the segment columns in the earnings releases swapped order in April 2023 (MIS
first, then MA first). The series is read by segment name rather than by column
position, and the quarters that appear in two releases agree item by item. The
test asserts the resulting shape -- MIS's share of adjusted operating income
exceeds its share of revenue in every quarter -- which is false under a swap.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import statistics
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.all import ENTRIES, GROUPS, build_all, roster_payload  # noqa: E402
from build import mco  # noqa: E402
from build.board import cn_count, cn_fraction  # noqa: E402
from build.mco import STAGING_PATH, build_payload, plain_text  # noqa: E402


def js_payload(path: Path, var: str) -> dict:
    text = path.read_text(encoding="utf-8")
    return json.loads(text.split(f"{var} = ", 1)[1].rstrip().rstrip(";\n").rstrip(";"))


class McoDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)

    # ── the licence: three printed reconciliations, all exact ───────────────
    def test_the_eps_bridge_closes_to_the_cent(self) -> None:
        """GAAP EPS guidance plus the named add-backs is the adjusted guidance.

        Five items, one of them negative (the divestiture gain), and the sum has
        to land on the company's own printed endpoints rather than near them.
        """
        eps = self.source["guidance_bridges"]["eps"]
        addbacks = sum(delta for _, delta in eps["addbacks"])
        for i in (0, 1):
            self.assertAlmostEqual(eps["gaap"][i] + addbacks, eps["adjusted"][i], places=2)
        checks = self.source["_checks"]
        self.assertEqual(eps["adjusted"], checks["guidance_current"]["adj_diluted_eps_usd"])
        self.assertEqual(eps["gaap"], checks["guidance_current"]["gaap_diluted_eps_usd"])
        self.assertEqual([delta for _, delta in eps["addbacks"]], checks["eps_bridge_usd"])

    def test_the_margin_bridge_closes_to_a_tenth_of_a_point(self) -> None:
        margin = self.source["guidance_bridges"]["margin"]
        addbacks = sum(delta for _, delta in margin["addbacks"])
        for i in (0, 1):
            self.assertAlmostEqual(margin["gaap"][i] + addbacks, margin["adjusted"][i], places=1)
        self.assertEqual(margin["adjusted"], self.source["_checks"]["guidance_current"]["adj_operating_margin_pct"])

    def test_the_cash_flow_bridge_closes(self) -> None:
        fcf = self.source["guidance_bridges"]["fcf"]
        for i in (0, 1):
            self.assertAlmostEqual(fcf["ocf"][i] - fcf["capex"], fcf["fcf"][i], places=2)

    # ── the distinction: two horizons, two different records ────────────────
    def _tally(self, vintage: str) -> tuple[int, int, int]:
        g = self.source["annual_guidance_history"]
        lo, hi = g[f"adj_eps_lo"][vintage], g[f"adj_eps_hi"][vintage]
        actual = g["actual_adj_eps_usd"]
        above = inside = below = 0
        for i, value in enumerate(actual):
            if value is None or lo[i] is None:
                continue
            if value > hi[i]:
                above += 1
            elif value < lo[i]:
                below += 1
            else:
                inside += 1
        return above, inside, below

    def test_the_final_guidance_was_broken_on_the_downside_exactly_once(self) -> None:
        """This test used to assert zero, and the zero came from an exclusion.

        FY2018 was kept out of the record on the stated ground that it "has only
        an October vintage". Reading the releases: 2018-02-09 opens the year at
        adjusted EPS $7.65-$7.85, 2018-04-27 and 2018-07-27 reaffirm it line for
        line, and 2018-10-26 cuts it to $7.50-$7.65 -- four vintages, the same
        cadence as every other year here. The delivered figure was $7.39.

        So the excluded year was the one year that breaks the headline, and the
        reason for excluding it was not true. Pinning the 1 rather than the 0 is
        the point of this test now.
        """
        above, inside, below = self._tally("Oct")
        finished = sum(1 for v in self.source["annual_guidance_history"]["actual_adj_eps_usd"]
                       if v is not None)
        self.assertEqual(above + inside + below, finished)
        years = self.source["annual_guidance_history"]["fiscal_years"]
        actual = self.source["annual_guidance_history"]["actual_adj_eps_usd"]
        low = self.source["annual_guidance_history"]["adj_eps_lo"]["Oct"]
        misses = [year for year, value, floor in zip(years, actual, low)
                  if value is not None and floor is not None and value < floor]
        # FY2018 is history: whatever later years do, it stays a miss.
        self.assertIn(2018, misses)
        self.assertEqual(len(misses), below)
        headline = self.payload["headline"]
        self.assertIn(f"{finished} 个已完结年度里，实际值相对末次（10 月）指引"
                      f"高于上限 {above} 次、落在区间内 {inside} 次、跌破下限 {below} 次", headline)

    def test_the_initial_guidance_claim_follows_its_tally(self) -> None:
        """「一次都没落在区间内」 is a finding about the record, so it stays on the
        page exactly as long as the February range has never contained a year."""
        above, inside, below = self._tally("Feb")
        headline = self.payload["headline"]
        self.assertIn(f"相对初始（2 月）指引却是高于 {above} 次、跌破 {below} 次", headline)
        self.assertEqual("一次都没落在区间内" in headline, inside == 0)
        self.assertEqual("初始指引一次都没对过" in self.payload["brief"], inside == 0)

    def test_the_two_horizons_disagree(self) -> None:
        """The page's first section exists only because these two differ."""
        self.assertNotEqual(self._tally("Oct"), self._tally("Feb"))

    def test_fy2022_was_cut_by_a_third(self) -> None:
        g = self.source["annual_guidance_history"]
        i = g["fiscal_years"].index(2022)
        feb = (g["adj_eps_lo"]["Feb"][i] + g["adj_eps_hi"]["Feb"][i]) / 2
        oct_ = (g["adj_eps_lo"]["Oct"][i] + g["adj_eps_hi"]["Oct"][i]) / 2
        self.assertAlmostEqual(feb, 12.65, places=2)
        self.assertAlmostEqual(oct_, 8.35, places=2)
        self.assertLess((oct_ / feb - 1) * 100, -33.0)
        # And the actual still cleared that final, cut-down range.
        self.assertGreater(g["actual_adj_eps_usd"][i], g["adj_eps_hi"]["Oct"][i])

    def test_fy2018_is_in_the_record_and_has_all_four_vintages(self) -> None:
        """The replacement for `test_fy2018_is_not_in_the_record`.

        That test asserted an exclusion whose stated reason -- "only an October
        vintage" -- is contradicted by the releases. Neither reading of it
        survives: the November 2017 release contains no FY2018 guidance at all,
        so there is no autumn-2017 vintage to be the only one; and October 2018
        is the fourth of four, not the first.

        The four dates are pinned here because the exclusion is the kind of thing
        that comes back: FY2018 is the only year that costs this page its
        headline, so any future rebuild that drops it needs to fail loudly.
        """
        history = self.source["annual_guidance_history"]
        self.assertIn(2018, history["fiscal_years"])
        self.assertEqual(history["fiscal_years"][0], 2018)
        self.assertIn(2018, self.source["annual_actuals"]["fiscal_years"])
        dates = history["release_dates"]["2018"]
        self.assertEqual(dates, {"Feb": "2018-02-09", "Apr": "2018-04-27",
                                 "Jul": "2018-07-27", "Oct": "2018-10-26"})
        index = history["fiscal_years"].index(2018)
        for vintage in history["vintages"]:
            self.assertIsNotNone(history["adj_eps_lo"][vintage][index], vintage)
            self.assertIsNotNone(history["adj_eps_hi"][vintage][index], vintage)
        # February opens it, October cuts it, and the year lands under the cut.
        self.assertEqual((history["adj_eps_lo"]["Feb"][index],
                          history["adj_eps_hi"]["Feb"][index]), (7.65, 7.85))
        self.assertEqual((history["adj_eps_lo"]["Oct"][index],
                          history["adj_eps_hi"]["Oct"][index]), (7.50, 7.65))
        self.assertEqual(history["actual_adj_eps_usd"][index], 7.39)
        self.assertIn("那句话是错的", history["fy2018_note"])
        # The note that still said FY2018 was outside the record shipped beside
        # the one saying it was inside, until 2026-09-19.
        self.assertFalse(any("FY2018 不在第一节的记录里" in note for note in self.payload["notes"]))

    def test_the_cadence_words_match_the_record(self) -> None:
        """「4/7/10 月各改一次」 and 「后三期各修订一次」 read as though every
        release moved the range; FY2018's April and July, FY2019's April,
        FY2023's October and FY2026's April repeated the one before (NC)."""
        g = self.source["annual_guidance_history"]
        repeats = 0
        for i in range(len(g["fiscal_years"])):
            for before, after in (("Feb", "Apr"), ("Apr", "Jul"), ("Jul", "Oct")):
                lo, hi = g["adj_eps_lo"], g["adj_eps_hi"]
                if lo[after][i] is not None and (lo[after][i], hi[after][i]) == (lo[before][i], hi[before][i]):
                    repeats += 1
        blob = json.dumps(self.payload, ensure_ascii=False)
        if repeats:
            self.assertNotIn("各改一次", blob)
            self.assertNotIn("各修订一次", blob)

    def test_the_denominator_overstatement_is_measured(self) -> None:
        """The note said external revenue overstates MIS's margin by 「2–3pp」;
        across the window it runs past 3.6pp. The range is measured, not typed."""
        seg = self.source["segment_quarterly"]
        over = [income / external * 100 - income / total * 100
                for income, external, total in zip(seg["mis_adj_operating_income_usd_m"],
                                                   seg["mis_revenue_usd_m"], seg["mis_total_revenue_usd_m"])]
        words = f"高估 {min(over):.1f}–{max(over):.1f}pp"
        margin = next(ex for s in self.payload["sections"] for ex in s["exhibits"]
                      if ex["title"].startswith("两条分部调整后营业利润率"))
        self.assertIn(words, margin["note"])
        self.assertTrue(any(words in note for note in self.payload["notes"]))

    def test_every_finished_year_has_all_four_vintages(self) -> None:
        g = self.source["annual_guidance_history"]
        for i, year in enumerate(g["fiscal_years"]):
            if g["actual_adj_eps_usd"][i] is None:
                continue
            for vintage in ("Feb", "Apr", "Jul", "Oct"):
                self.assertIsNotNone(g["adj_eps_lo"][vintage][i], f"FY{year} {vintage}")

    # ── the segment column-order trap ───────────────────────────────────────
    def test_ratings_is_a_minority_of_revenue_and_a_majority_of_profit(self) -> None:
        """False in every quarter if the MA/MIS columns were ever read by position."""
        seg = self.source["segment_quarterly"]
        for i, period in enumerate(seg["periods"]):
            self.assertGreater(
                seg["mis_share_of_adj_operating_income_pct"][i],
                seg["mis_share_of_revenue_pct"][i],
                f"{period}: MIS profit share must exceed its revenue share",
            )
        self.assertLess(min(seg["mis_share_of_revenue_pct"]), 50.0)
        self.assertGreater(min(seg["mis_share_of_adj_operating_income_pct"]), 55.0)

    def test_segment_revenue_sums_close_to_consolidated(self) -> None:
        seg = self.source["segment_quarterly"]
        for i, period in enumerate(seg["periods"]):
            total = seg["ma_revenue_usd_m"][i] + seg["mis_revenue_usd_m"][i]
            self.assertAlmostEqual(total, seg["revenue_usd_m"][i], delta=1.0, msg=period)

    def test_segment_margin_is_income_over_TOTAL_revenue(self) -> None:
        """The denominator is total segment revenue, not the external revenue plotted.

        Dividing adjusted operating income by the external revenue this page
        charts overstates MIS's margin by 2-4pp, because MIS bills MA tens of
        millions a quarter internally. Against total revenue the identity closes
        to within 0.05pp in every quarter -- that residual is the rounding of the
        published percentage, nothing else. Pinned tightly on purpose: a loose
        tolerance here would accept the wrong denominator.
        """
        seg = self.source["segment_quarterly"]
        for i, period in enumerate(seg["periods"]):
            for who in ("ma", "mis"):
                derived = (seg[f"{who}_adj_operating_income_usd_m"][i]
                           / seg[f"{who}_total_revenue_usd_m"][i] * 100)
                self.assertAlmostEqual(derived, seg[f"{who}_adj_operating_margin_pct"][i],
                                       delta=0.06, msg=f"{period} {who}")

    def test_intersegment_revenue_is_the_gap_between_the_two_bases(self) -> None:
        seg = self.source["segment_quarterly"]
        for i, period in enumerate(seg["periods"]):
            for who in ("ma", "mis"):
                gap = seg[f"{who}_total_revenue_usd_m"][i] - seg[f"{who}_revenue_usd_m"][i]
                self.assertGreaterEqual(gap, 0.0, f"{period} {who}")
        # MIS bills MA far more than the other way round, which is why only
        # MIS's margin moves materially between the two bases.
        mis_gap = [seg["mis_total_revenue_usd_m"][i] - seg["mis_revenue_usd_m"][i]
                   for i in range(len(seg["periods"]))]
        ma_gap = [seg["ma_total_revenue_usd_m"][i] - seg["ma_revenue_usd_m"][i]
                  for i in range(len(seg["periods"]))]
        self.assertGreater(min(mis_gap), max(ma_gap))

    # ── annual actuals ──────────────────────────────────────────────────────
    def test_free_cash_flow_is_operating_cash_flow_minus_capex(self) -> None:
        ann = self.source["annual_actuals"]
        for i, year in enumerate(ann["fiscal_years"]):
            self.assertAlmostEqual(
                ann["operating_cash_flow_usd_m"][i] - ann["capex_usd_m"][i],
                ann["free_cash_flow_usd_m"][i], places=1, msg=f"FY{year}")

    def test_adjusted_eps_exceeds_gaap_eps_in_every_year_that_has_one(self) -> None:
        """The add-backs only ever go one way -- where both figures exist.

        FY2016 and FY2017 have a GAAP diluted EPS and no adjusted one. That is
        deliberate: Moody's redefines the adjusted measure from year to year,
        this file's adjusted record starts at FY2018, and neither substituting
        GAAP nor summing four quarterly adjusted EPS (EPS is not additive)
        would produce a figure the company ever published. So the two years are
        holes, and this test asserts the relation only where both legs are real
        -- while still pinning that the holes are exactly those two years, so a
        future gap cannot hide behind the same exemption.
        """
        ann = self.source["annual_actuals"]
        missing = [year for year, value
                   in zip(ann["fiscal_years"], ann["adjusted_diluted_eps_usd"])
                   if value is None]
        self.assertEqual(missing, [2016, 2017])
        self.assertIn("EPS 不可加", ann["adjusted_eps_hole_note"])
        for i, year in enumerate(ann["fiscal_years"]):
            if ann["adjusted_diluted_eps_usd"][i] is None:
                continue
            self.assertGreater(ann["adjusted_diluted_eps_usd"][i],
                               ann["diluted_eps_usd"][i], f"FY{year}")

    def test_the_settlement_year_is_on_the_chart_rather_than_smoothed(self) -> None:
        """The reason the annual charts were worth lengthening.

        On the eight-year window that started at FY2018, Moody's operating
        margin never leaves the 34-46% band and the story is a steady business
        with one COVID-era dip. FY2016 is outside that band by a distance: a
        one-off charge tied to the DOJ settlement put operating income at 638.7
        on revenue of 3,604.2, and FY2017's operating cash flow is where that
        money actually left. Both are filed figures, and pinning them here is
        what stops a later rebuild from quietly trimming the window back to the
        comfortable part.
        """
        ann = self.source["annual_actuals"]
        self.assertEqual(ann["fiscal_years"][0], 2016)
        # The stored margin is a ratio of two stored legs, so it is checked
        # against them rather than read. Without this the margin and the income
        # it comes from can drift apart and every assertion below still passes.
        for year, income, revenue, margin in zip(
                ann["fiscal_years"], ann["operating_income_usd_m"],
                ann["revenue_usd_m"], ann["operating_margin_pct"]):
            self.assertAlmostEqual(income / revenue * 100, margin, places=1,
                                   msg=f"FY{year}")
        # ...and free cash flow is the other derived leg, same treatment.
        for year, ocf, capex, fcf in zip(
                ann["fiscal_years"], ann["operating_cash_flow_usd_m"],
                ann["capex_usd_m"], ann["free_cash_flow_usd_m"]):
            self.assertAlmostEqual(ocf - capex, fcf, delta=1.0, msg=f"FY{year}")
        margins = dict(zip(ann["fiscal_years"], ann["operating_margin_pct"]))
        self.assertLess(margins[2016], 20.0)
        self.assertGreater(min(value for year, value in margins.items()
                               if year >= 2018), 30.0)
        cash = dict(zip(ann["fiscal_years"], ann["operating_cash_flow_usd_m"]))
        self.assertLess(cash[2017], cash[2016])
        self.assertLess(cash[2017], min(value for year, value in cash.items()
                                        if year >= 2018))

    # ── page shape and boundary ─────────────────────────────────────────────
    def test_four_sections_with_exhibits_numbered_in_render_order(self) -> None:
        sections = self.payload["sections"]
        self.assertEqual([s["id"] for s in sections],
                         ["settled", "quarter_highlights", "next_quarter", "routine"])
        numbers = [ex["n"] for s in sections for ex in s["exhibits"]]
        self.assertEqual(numbers, list(range(1, len(numbers) + 1)))
        self.assertEqual([t["n"] for t in self.payload["tables"]],
                         list(range(len(numbers) + 1, len(numbers) + 1 + len(self.payload["tables"]))))

    def test_plain_text_slots_carry_no_markup(self) -> None:
        """Four slots reach the reader as text, so markup in them is literal.

        `page.js` escapes `notes` and each section's `description`, and sets
        `headline`, `title` and `subtitle` with `textContent`. A `<b>` written
        into any of them shows up as four characters on the page. This is not
        hypothetical: the headline shipped with markup on the first build of
        this page and nothing but loading it in a browser showed it, because
        the payload guard inspects values and the suite never rendered one.
        Exhibit notes are NOT in this list -- those go through innerHTML and
        keep their markup.
        """
        for note in self.payload["notes"]:
            self.assertNotIn("<", note)
        for section in self.payload["sections"]:
            self.assertNotIn("<", section["description"])
        for key in ("headline", "title", "subtitle"):
            self.assertNotIn("<", self.payload[key], key)
        self.assertEqual(plain_text("a<b>c</b>d"), "acd")

    def test_audit_tables_carry_no_field_the_renderer_drops(self) -> None:
        """`tableHTML(title, headers, rows, cls)` is all the appendix drawer reads.

        A `note` on a **`D.tables`** dict is silently discarded -- it never
        reaches the page, but it reads in the source like a published caveat, so
        the next editor writes the qualification there and believes it shipped.
        This page did exactly that on its first build: three tables carried notes
        no reader could see, and the substance now lives in `notes`, which is
        rendered. Every other page on the site carries zero.

        **Scoped to `D.tables` deliberately, because `note` is not universally
        dead on table-shaped dicts.** `D.guidance` is built by the same
        `tableHTML` call, but `page.js` follows it with
        `esc(D.guidance.note || '')`, so a guidance note *is* rendered -- AMZN
        ships one 147 characters long. Widening this assertion to anything that
        looks like a table would go red there, and the tempting way to green it
        would delete a caption a reader can see. Two slots, one renderer call,
        one reads the key and one drops it: the difference is a single line
        after the call, not anything visible in the payload.
        """
        allowed = {"n", "title", "headers", "rows"}
        for table in self.payload["tables"]:
            self.assertLessEqual(set(table) - allowed, set(),
                                 f"table {table['n']} carries a field the renderer drops")

    def test_exhibit_notes_may_still_carry_markup(self) -> None:
        """The complement of the test above: this page does use bold in notes."""
        notes = [ex.get("note", "") for s in self.payload["sections"] for ex in s["exhibits"]]
        self.assertTrue(any("<b>" in note for note in notes))

    def test_no_verbal_guidance_is_turned_into_a_number(self) -> None:
        """The revenue lines are words, not ranges; the page must not invent endpoints."""
        verbal = self.source["current_guidance"]["verbal"]
        self.assertIn("MCO Revenue", verbal)
        blob = json.dumps(self.payload, ensure_ascii=False)
        self.assertIn("只给文字口径", blob)
        # No exhibit may plot a band for a metric the company gave in words.
        for section in self.payload["sections"]:
            for ex in section["exhibits"]:
                if ex.get("kind") == "range_band":
                    self.assertIn("EPS", ex["title"])

    def test_mco_is_not_in_the_cross_page_capex_table(self) -> None:
        """The shared table is hyperscaler capex into foundry wafers; Moody's is not on it."""
        table = next(t for t in self.payload["tables"] if "AI capex" in t["title"])
        self.assertNotIn("MCO", " ".join(table["headers"]))

    def test_roster_entry_names_a_group_that_exists(self) -> None:
        entry = next(e for e in ENTRIES if e["slug"] == "mco")
        self.assertEqual(entry["group"], "financial_data_indices")
        self.assertIn(entry["group"], {g["key"] for g in GROUPS})
        roster = roster_payload(build_all())
        self.assertIn("mco", [i["slug"] for i in roster["items"]])

    def test_published_payload_and_shell(self) -> None:
        self.assertEqual(js_payload(ROOT / "data" / "mco.js", "window.DASH"), self.payload)
        shell = (ROOT / "mco" / "index.html").read_text(encoding="utf-8")
        self.assertIn("<title>MCO Quarterly Results</title>", shell)
        self.assertIn("../data/mco.js", shell)
        self.assertNotIn("../data/tsm.js", shell)

    def test_the_shell_stamps_the_current_payload_digest(self) -> None:
        """Pinned by value: post-build `git status` is otherwise the only thing
        that shows a shell committed with the previous payload's hash."""
        digest = hashlib.sha256((ROOT / "data" / "mco.js").read_bytes()).hexdigest()[:8]
        shell = (ROOT / "mco" / "index.html").read_text(encoding="utf-8")
        self.assertIn(f"../data/mco.js?v={digest}", shell)
        for name in ("roster.js", "charts.js", "page.js"):
            self.assertRegex(shell, rf"{re.escape(name)}\?v=[0-9a-f]{{8}}")

    def test_sources_are_official_sec_links(self) -> None:
        for source in self.payload["source_links"]:
            self.assertTrue(source["url"].startswith("https://www.sec.gov/"), source["url"])

    def test_headline_states_both_tallies(self) -> None:
        headline = self.payload["headline"]
        self.assertIn("末次", headline)
        self.assertIn("初始", headline)

    def test_the_page_prints_no_markdown(self) -> None:
        """Exhibit notes are innerHTML: `**` reaches the reader as two asterisks.
        Two notes shipped that way until 2026-09-19."""
        blob = json.dumps(self.payload, ensure_ascii=False)
        self.assertNotIn("**", blob)

    def test_the_sources_open_the_documents_they_name(self) -> None:
        """The 10-Q and 10-K entries used to open EDGAR's filing list, not the
        filing; a label that names one document links to that document."""
        for source in self.payload["source_links"]:
            if "10-Q" in source["label"] or "10-K" in source["label"]:
                self.assertIn("/Archives/edgar/data/1059556/", source["url"], source["label"])

    def test_the_record_extremes_are_the_series_extremes(self) -> None:
        """「柱子从 −32.3% 到 +17.0%，中位数约 +4%」 and 「平均绝对偏离从 13.3%」 were
        typed before FY2018 joined the record; the series says +17.4%, +6% and
        12.2%. Recounted here along a second route."""
        g = self.source["annual_guidance_history"]
        feb, oct_ = [], []
        for i, actual in enumerate(g["actual_adj_eps_usd"]):
            if actual is None:
                continue
            feb.append((actual / ((g["adj_eps_lo"]["Feb"][i] + g["adj_eps_hi"]["Feb"][i]) / 2) - 1) * 100)
            oct_.append((actual / ((g["adj_eps_lo"]["Oct"][i] + g["adj_eps_hi"]["Oct"][i]) / 2) - 1) * 100)
        exhibits = [ex for s in self.payload["sections"] for ex in s["exhibits"]]
        feb_chart = next(ex for ex in exhibits if ex["title"].startswith("调整后摊薄 EPS（2 月那版）"))
        self.assertIn(f"到 {max(feb):+.1f}%，中位数约 {statistics.median(feb):+.0f}%", feb_chart["note"])
        oct_chart = next(ex for ex in exhibits if ex["title"].startswith("调整后摊薄 EPS（10 月那版）"))
        feb_mean = statistics.fmean(abs(v) for v in feb)
        oct_mean = statistics.fmean(abs(v) for v in oct_)
        self.assertIn(f"平均绝对偏离就从 {feb_mean:.1f}% 收到 {oct_mean:.1f}%", oct_chart["note"])
        self.assertIn(f"约{cn_fraction(oct_mean / feb_mean)}", oct_chart["note"])
        self.assertIn(f"平均绝对偏离 {feb_mean:.1f}%", feb_chart["title"])

    def test_the_annual_window_is_named_by_its_length(self) -> None:
        """「八年」 survived the window's extension to FY2016 in four titles and a
        section description, and so did 「FY2022 是低点」 on a chart whose low is
        FY2017."""
        ann = self.source["annual_actuals"]
        n = cn_count(len(ann["fiscal_years"]))
        routine = next(s for s in self.payload["sections"] if s["id"] == "routine")
        self.assertIn(f"{n}年营业利润率", routine["description"])
        for ex in routine["exhibits"][:3]:
            self.assertTrue(ex["title"].startswith(f"{n}年"), ex["title"])
        fcf = ann["free_cash_flow_usd_m"]
        low = ann["fiscal_years"][fcf.index(min(fcf))]
        self.assertIn(f"FY{low} 的 US${min(fcf) / 1000:.2f}B 是低点", routine["exhibits"][2]["title"])
        margin = ann["operating_margin_pct"]
        self.assertIn(f"低点是 FY{ann['fiscal_years'][margin.index(min(margin))]} 的 {min(margin):.1f}%",
                      routine["exhibits"][0]["note"])
        tables = {t["title"] for t in self.payload["tables"]}
        self.assertIn(f"FY{ann['fiscal_years'][0]}–FY{ann['fiscal_years'][-1]} 年度实际", tables)
        g = self.source["annual_guidance_history"]["fiscal_years"]
        self.assertIn(f"FY{g[0]}–FY{g[-1]} 全年调整后摊薄 EPS 指引的四个版本与实际（US$/股）", tables)

    def test_the_negative_addback_sentence_counts_the_record(self) -> None:
        """「FY2026 是八年里第一次出现负的加回项」 was false: FY2018, FY2021, FY2022,
        FY2024 and FY2025 all carried one. The sentence now counts them."""
        ann = self.source["annual_actuals"]
        negatives = ann["negative_adjustments_usd"]
        eps = next(ex for s in self.payload["sections"] for ex in s["exhibits"]
                   if ex["title"].endswith("两条线之间的缺口就是每年被加回的那些项"))
        self.assertNotIn("第一次出现负的加回项", eps["note"])
        adjusted_years = sum(1 for v in ann["adjusted_diluted_eps_usd"] if v is not None)
        self.assertIn(f"{cn_count(adjusted_years)}个有调整后口径的年度里有{cn_count(len(negatives))}年", eps["note"])
        gaps = [a - g for a, g in zip(ann["adjusted_diluted_eps_usd"], ann["diluted_eps_usd"]) if a is not None]
        self.assertIn(f"缺口在 US${min(gaps):.2f}–{max(gaps):.2f} 之间", eps["note"])


def exhibits_of(payload: dict) -> list[dict]:
    return [ex for section in payload["sections"] for ex in section["exhibits"]]


def own_text(payload: dict) -> str:
    """Everything the page says, less the cross-page table every page carries."""
    own = dict(payload, tables=[t for t in payload["tables"] if "AI capex" not in t["title"]])
    return json.dumps(own, ensure_ascii=False)


QUARTER_BLOCKS = ("quarter_figures", "current_guidance", "guidance_bridges", "quarter_story",
                  "followup_closure", "prior_kpi_settlement", "next_kpi")
# Quarterly blocks that carry their own `periods` and must move with segment_quarterly.
ALIGNED_BLOCKS = ("quarterly_cash", "ma_kpi_quarterly")
PLACEHOLDER = r"\{[a-z_]+\}"


class McoChecksTest(unittest.TestCase):
    """The page's quarter against a record keyed separately from the release.

    `_checks` is typed once per quarter from the earnings release itself, with
    the place in the document each figure was read from; the builder never reads
    it (asserted in `test_data_only_roll`). The release prints growth as whole
    percentages, so the page's one-decimal growth is compared at that precision.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
        cls.checks = cls.staging["_checks"]
        cls.seg = cls.staging["segment_quarterly"]
        cls.payload = build_payload(cls.staging)

    def test_the_page_names_the_checked_quarter(self) -> None:
        self.assertIn(self.checks["period"], self.payload["title"])
        self.assertIn(f"截至 {self.checks['period_end']}", self.payload["subtitle"])
        self.assertIn(f"发布 {self.checks['release_date']}", self.payload["subtitle"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        for key in ("revenue_usd_m", "mis_revenue_usd_m", "ma_revenue_usd_m", "mis_total_revenue_usd_m",
                    "ma_total_revenue_usd_m", "mis_adj_operating_income_usd_m", "ma_adj_operating_income_usd_m",
                    "adj_operating_income_usd_m", "adj_operating_margin_pct", "mis_adj_operating_margin_pct",
                    "ma_adj_operating_margin_pct"):
            with self.subTest(key=key):
                self.assertEqual(self.seg[key][-1], self.checks[key])
        figures = self.staging["quarter_figures"]
        self.assertEqual(figures["diluted_eps_usd"], self.checks["diluted_eps_usd"])
        self.assertEqual(figures["adj_diluted_eps_usd"], self.checks["adj_diluted_eps_usd"])

    def test_computed_growth_rounds_to_the_printed_growth(self) -> None:
        for key, printed in (("revenue_usd_m", "revenue_growth_pct"), ("mis_revenue_usd_m", "mis_growth_pct"),
                             ("ma_revenue_usd_m", "ma_growth_pct")):
            values = self.seg[key]
            with self.subTest(key=key):
                self.assertEqual(round((values[-1] / values[-5] - 1) * 100), self.checks[printed])

    def test_the_open_year_ends_on_the_checked_guidance(self) -> None:
        guidance = self.staging["current_guidance"]
        for key, value in self.checks["guidance_current"].items():
            with self.subTest(key=key):
                self.assertEqual(guidance[key], value)
        g = self.staging["annual_guidance_history"]
        year = str(guidance["fiscal_year"])
        vintage = next(v for v in ("Oct", "Jul", "Apr", "Feb") if g["release_dates"][year][v] == guidance["as_of"])
        i = g["fiscal_years"].index(guidance["fiscal_year"])
        self.assertEqual([g["adj_eps_lo"][vintage][i], g["adj_eps_hi"][vintage][i]],
                         self.checks["guidance_current"]["adj_diluted_eps_usd"])
        self.assertEqual([g["gaap_eps_lo"][vintage][i], g["gaap_eps_hi"][vintage][i]],
                         self.checks["guidance_current"]["gaap_diluted_eps_usd"])
        before = ("Feb", "Apr", "Jul", "Oct")[("Feb", "Apr", "Jul", "Oct").index(vintage) - 1]
        self.assertEqual([g["adj_eps_lo"][before][i], g["adj_eps_hi"][before][i]],
                         self.checks["guidance_prior"]["adj_diluted_eps_usd"])
        self.assertEqual(self.staging["latest"]["release_date"], guidance["as_of"])

    def test_the_page_prints_the_checked_figures(self) -> None:
        c = self.checks
        headline = self.payload["headline"]
        self.assertIn(f"收入 US${c['revenue_usd_m']:,.0f}M", headline)
        self.assertIn(f"调整后营业利润率 {c['adj_operating_margin_pct']:.1f}%", headline)
        self.assertIn(f"US${c['guidance_current']['adj_diluted_eps_usd'][0]:.2f}–"
                      f"{c['guidance_current']['adj_diluted_eps_usd'][1]:.2f}", self.payload["brief"])
        self.assertEqual(mco.headline_metrics(self.staging)[2], f"调整后 EPS ${c['adj_diluted_eps_usd']:.2f}")
        share = next(ex for ex in exhibits_of(self.payload) if ex["title"].startswith("评级业务占收入"))
        self.assertIn(f"本季 MIS {c['mis_adj_operating_margin_pct']:.1f}% 对 MA {c['ma_adj_operating_margin_pct']:.1f}%",
                      share["note"])
        bridge = next(ex for ex in exhibits_of(self.payload) if ex["title"].startswith("指引表自己就能对平"))
        self.assertIn(f"US${c['guidance_current']['adj_diluted_eps_usd'][0]:.2f}", bridge["title"])


class McoFourPartTest(unittest.TestCase):
    """The four sections say what their titles promise, and say what the analyses say.

    What the owner's two analyses concluded -- the closure tally, last quarter's
    thresholds, this quarter's thresholds -- is keyed once per roll into
    `_checks["note"]`, re-read from the report files rather than copied from the
    series blocks, and the builder never sees it. So a roll edits the series file
    alone; nothing the reports said is written into this file.
    """

    SECTIONS = [("settled", "一、上季跟踪指标兑现了吗"), ("quarter_highlights", "二、本季重点"),
                ("next_quarter", "三、下季要跟踪什么"), ("routine", "四、长期常规跟踪")]
    ORDER = ("已验证", "部分验证", "被证伪", "仍未披露", "指标设计失效")

    @classmethod
    def setUpClass(cls) -> None:
        cls.s = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
        cls.note = cls.s["_checks"]["note"]
        cls.payload = build_payload(cls.s)
        cls.sections = {section["id"]: section for section in cls.payload["sections"]}

    def overview(self, section: str, prefix: str) -> dict:
        return next(ex for ex in self.sections[section]["exhibits"]
                    if ex["kind"] == "diverging_bars" and ex["title"].startswith(prefix))

    def test_the_four_sections_carry_the_four_titles(self) -> None:
        self.assertEqual([(s["id"], s["title"]) for s in self.payload["sections"]], self.SECTIONS)
        for section in self.payload["sections"]:
            self.assertTrue(section["exhibits"], section["id"])
        self.assertIn("本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列", self.payload["notes"][0])

    def test_the_closure_is_the_analysis_section_zero(self) -> None:
        closure = self.s["followup_closure"]
        self.assertEqual(closure["set_in"], self.s["segment_quarterly"]["periods"][-2])
        expected = [(label, self.note["closure"]["counts"][label]) for label in self.ORDER
                    if self.note["closure"]["counts"].get(label)]
        chart = self.sections["settled"]["exhibits"][0]
        self.assertEqual(chart["kind"], "bars_labeled")
        self.assertEqual(list(zip(chart["xlabels"], chart["values"])), expected)
        total = self.note["closure"]["total"]
        self.assertEqual(sum(chart["values"]), total)
        self.assertTrue(chart["title"].startswith(f"上季 {total} 条待验证问题："), chart["title"])
        for label, count in expected:
            self.assertIn(f"{count} 条{label}", chart["title"])

    def test_a_verdict_the_chart_does_not_know_stops_the_build(self) -> None:
        odd = copy.deepcopy(self.s)
        odd["followup_closure"]["items"][0]["verdict"] = "大致验证"
        with self.assertRaisesRegex(ValueError, "verdicts"):
            build_payload(odd)

    def test_the_prior_thresholds_are_the_last_analysis_section_eight(self) -> None:
        prior = self.s["prior_kpi_settlement"]
        self.assertEqual(prior["set_in"], self.s["segment_quarterly"]["periods"][-2])
        self.assertEqual(len(prior["dispositions"]), self.note["prior_rows"])
        typed = [(entry["metric"], entry.get("threshold", 0.0), entry["direction"]) for entry in prior["quantified"]]
        self.assertEqual(typed, [(row["metric"], row["threshold"], row["direction"])
                                 for row in self.note["prior_thresholds"]])
        self.assertFalse(any("actual" in entry for entry in prior["quantified"]))

    def test_the_prior_settlement_is_read_from_the_series(self) -> None:
        """Recomputed along a second route: from the arrays, not the builder's functions.

        A zero threshold (「同比为负即警示」) has no percentage headroom, so it is
        settled as a level -- the same quarter a year earlier -- whose headroom is
        the growth rate itself.
        """
        seg, cash, kpi = self.s["segment_quarterly"], self.s["quarterly_cash"], self.s["ma_kpi_quarterly"]
        now = {"ma_arr_growth": kpi["arr_growth_pct"][-1],
               "ma_organic_growth": kpi["organic_cc_revenue_growth_pct"][-1],
               "mis_revenue": seg["mis_revenue_usd_m"][-1],
               "share_repurchases": cash["share_repurchases_usd_m"][-1]}
        expected = []
        for row, entry in zip(self.note["prior_thresholds"], self.s["prior_kpi_settlement"]["quantified"]):
            actual = now[entry["series"]]
            # 0% growth has no percentage headroom: settle it as the year-ago level
            threshold = seg["mis_revenue_usd_m"][-5] if row["threshold"] == 0 else row["threshold"]
            sign = 1 if row["direction"] == "up" else -1
            expected.append(round(sign * (actual - threshold) / abs(threshold) * 100, 1))
        overview = self.overview("settled", "上季")
        self.assertEqual(overview["xlabels"], [row["metric"] for row in self.note["prior_thresholds"]])
        self.assertEqual(overview["values"], expected)
        held = sum(1 for value in expected if value >= 0)
        self.assertTrue(overview["title"].startswith(
            f"上季 {len(expected)} 条量化阈值：{held} 条守住、{len(expected) - held} 条被击穿"), overview["title"])

    def test_the_rounding_that_decides_a_threshold_is_named(self) -> None:
        """MA organic constant-currency revenue printed a whole-percent rate against a bar
        set at the same whole percent; its own printed amounts can land on the other side.
        The page settles on the company's figure and says which side the amounts fall."""
        now, before = self.s["quarter_figures"]["ma_organic_cc_revenue_usd_m"]
        exact = (now / before - 1) * 100
        printed = self.s["ma_kpi_quarterly"]["organic_cc_revenue_growth_pct"][-1]
        self.assertEqual(printed, self.s["_checks"]["ma_organic_cc_revenue_growth_pct"])
        self.assertEqual(round(exact), printed)
        bar = next(row["threshold"] for row in self.note["prior_thresholds"]
                   if row["metric"] == "MA 有机固定汇率收入同比")
        overview = self.overview("settled", "上季")
        self.assertIn(f"算是 {exact:.2f}%", overview["note"])
        self.assertEqual("只在整数精度上达到" in overview["note"], exact < bar <= printed)

    def test_the_next_thresholds_are_this_analysis_section_eight(self) -> None:
        block = self.s["next_kpi"]
        quarter, year = self.s["segment_quarterly"]["periods"][-1].split()
        after = f"Q1 {int(year) + 1}" if quarter == "Q4" else f"Q{int(quarter[1]) + 1} {year}"
        self.assertEqual(block["for_period"], after)
        typed =[(entry["metric"], entry["threshold"], entry["direction"]) for entry in block["quantified"]]
        self.assertEqual(typed, [(row["metric"], row["threshold"], row["direction"])
                                 for row in self.note["next_thresholds"]])
        self.assertFalse(any("current" in entry for entry in block["quantified"]))

    def test_the_next_thresholds_are_measured_from_the_series(self) -> None:
        seg, cash, kpi = self.s["segment_quarterly"], self.s["quarterly_cash"], self.s["ma_kpi_quarterly"]
        g = self.s["annual_guidance_history"]
        latest = next(v for v in ("Oct", "Jul", "Apr", "Feb") if g["fcf_usd_b_lo"][v][-1] is not None)
        quarter = int(seg["periods"][-1][1])
        fcf = [o - c for o, c in zip(cash["operating_cash_flow_usd_m"], cash["capital_additions_usd_m"])]
        paid = [b + d for b, d in zip(cash["share_repurchases_usd_m"], cash["dividends_paid_usd_m"])]
        ratio = sum(paid[-quarter:]) / sum(fcf[-quarter:]) * 100
        current = {"mis_revenue": seg["mis_revenue_usd_m"][-1], "ma_arr_growth": kpi["arr_growth_pct"][-1],
                   "ma_recurring_growth": kpi["organic_cc_recurring_growth_pct"][-1],
                   "ma_margin": seg["ma_adj_operating_margin_pct"][-1],
                   "fcf_guide_low": g["fcf_usd_b_lo"][latest][-1], "returns_to_fcf_ytd": ratio}
        expected = []
        for row, entry in zip(self.note["next_thresholds"], self.s["next_kpi"]["quantified"]):
            sign = 1 if row["direction"] == "up" else -1
            expected.append(round(sign * (current[entry["series"]] - row["threshold"])
                                  / abs(row["threshold"]) * 100, 1))
        overview = self.overview("next_quarter", "下季")
        self.assertEqual(overview["xlabels"], [row["metric"] for row in self.note["next_thresholds"]])
        self.assertEqual(overview["values"], expected)
        self.assertTrue(overview["title"].startswith(f"下季 {len(expected)} 条量化阈值："), overview["title"])
        # every threshold is drawn as a flat line on the chart of the series it watches
        drawn = [line["values"][0] for ex in self.sections["next_quarter"]["exhibits"][1:]
                 for line in ex["series"] if len(set(line["values"])) == 1]
        self.assertEqual(sorted(drawn), sorted(row["threshold"] for row in self.note["next_thresholds"]))

    def test_section_two_carries_no_range_only_chart(self) -> None:
        """「42 季里 X 在 a–b 之间」 is a routine chart; section two leads with the quarter."""
        n = len(self.s["segment_quarterly"]["periods"])
        for ex in self.sections["quarter_highlights"]["exhibits"]:
            self.assertNotRegex(ex["title"], rf"^{n} 季里.*之间", ex["title"])
        routine_titles = [ex["title"] for ex in self.sections["routine"]["exhibits"]]
        for prefix in (f"{n} 季里 MIS 收入在", "评级业务占收入", "两条分部调整后营业利润率"):
            self.assertTrue(any(title.startswith(prefix) for title in routine_titles), prefix)

    def test_section_two_numbers_are_the_filings(self) -> None:
        seg, checks = self.s["segment_quarterly"], self.s["_checks"]
        titles = [ex["title"] for ex in self.sections["quarter_highlights"]["exhibits"]]
        d_rev = seg["revenue_usd_m"][-1] - seg["revenue_usd_m"][-2]
        d_aoi = seg["adj_operating_income_usd_m"][-1] - seg["adj_operating_income_usd_m"][-2]
        self.assertTrue(titles[0].startswith(f"环比多出的 US${d_rev:,.0f}M 收入里有 US${d_aoi:,.0f}M"), titles[0])
        bridge = next(ex for ex in self.sections["quarter_highlights"]["exhibits"] if ex["kind"] == "bars_labeled")
        self.assertEqual(bridge["values"][0], checks["diluted_eps_usd"])
        self.assertEqual(bridge["values"][-1], checks["adj_diluted_eps_usd"])
        steps = self.s["quarter_figures"]["eps_bridge_usd"]
        self.assertAlmostEqual(checks["diluted_eps_usd"] + sum(v for _, v in steps), checks["adj_diluted_eps_usd"],
                               places=2)
        ytd = checks["ytd_cash_usd_m"]
        quarter = int(seg["periods"][-1][1])
        cash = self.s["quarterly_cash"]
        for key, column in (("operating_cash_flow", "operating_cash_flow_usd_m"),
                            ("capital_additions", "capital_additions_usd_m"),
                            ("treasury_shares", "share_repurchases_usd_m"), ("dividends", "dividends_paid_usd_m")):
            self.assertEqual(round(sum(cash[column][-quarter:])), ytd[key], key)
        returns = ytd["treasury_shares"] + ytd["dividends"]
        fcf = ytd["operating_cash_flow"] - ytd["capital_additions"]
        self.assertTrue(any(f"回购加股息 US${returns:,.0f}M，是同期自由现金流 US${fcf:,.0f}M 的 "
                            f"{returns / fcf * 100:.0f}%" in title for title in titles), titles)

    def test_a_threshold_on_a_series_the_page_holds_cannot_carry_a_typed_value(self) -> None:
        """A typed current next to a computed one is two copies free to disagree; a metric
        no series here carries (next quarter's analysis may add one) must bring its source."""
        typed = copy.deepcopy(self.s)
        typed["next_kpi"]["quantified"][0]["current"] = 1.0
        with self.assertRaisesRegex(ValueError, "computed from the series"):
            build_payload(typed)
        bare = copy.deepcopy(self.s)
        bare["next_kpi"]["quantified"].append({"id": "new", "metric": "新指标", "condition": "x", "action": "y",
                                               "direction": "up", "threshold": 10.0, "unit": "pct"})
        with self.assertRaisesRegex(ValueError, "no series to read"):
            build_payload(bare)
        bare["next_kpi"]["quantified"][-1].update(current=12.0, source="某份申报某表")
        overview = next(ex for s in build_payload(bare)["sections"] for ex in s["exhibits"]
                        if ex["title"].startswith("下季"))
        self.assertEqual(overview["xlabels"][-1], "新指标")
        self.assertEqual(overview["values"][-1], 20.0)

    def test_the_ma_growth_rates_are_the_releases(self) -> None:
        kpi, checks = self.s["ma_kpi_quarterly"], self.s["_checks"]
        self.assertEqual(kpi["arr_growth_pct"][-1], checks["ma_arr_growth_pct"])
        self.assertEqual(kpi["organic_cc_recurring_growth_pct"][-1], checks["ma_organic_cc_recurring_growth_pct"])
        self.assertEqual(kpi["periods"], self.s["segment_quarterly"]["periods"])

    def test_the_page_no_longer_says_moodys_never_guides_a_quarter(self) -> None:
        """Heuland on the Q1 2026 call: 「For the second quarter, we expect … adjusted diluted
        EPS of approximately $4.15 to $4.30」. The quarter's numbers are call-only, not absent."""
        correction = "本页此前写的是「从不给下一季度的数字指引」"
        text = own_text(self.payload)
        self.assertIn(correction, text)
        for phrase in ("从不给下一季度的数字指引", "穆迪不给季度指引", "穆迪不给下一季度的数字区间",
                       "本页真正的对象不是这个季度"):
            self.assertNotIn(phrase, text.replace(correction, ""))


def rolled_back(staging: dict) -> dict:
    """The series one quarter earlier: the segment arrays lose their last cell,
    the open year loses its latest vintage, and the quarter's own blocks go."""
    s = copy.deepcopy(staging)
    seg = s["segment_quarterly"]
    for block in [seg] + [s[key] for key in ALIGNED_BLOCKS]:
        for key, values in block.items():
            if isinstance(values, list) and len(values) == len(staging["segment_quarterly"]["periods"]):
                block[key] = values[:-1]
    g = s["annual_guidance_history"]
    year = max(g["fiscal_years"])
    i = g["fiscal_years"].index(year)
    dates = g["release_dates"][str(year)]
    vintage = next(v for v in ("Oct", "Jul", "Apr", "Feb") if dates[v] is not None)
    dates[vintage] = None
    for key in list(g):
        if isinstance(g[key], dict) and vintage in g[key] and isinstance(g[key][vintage], list):
            g[key][vintage][i] = None
    previous = next(v for v in ("Oct", "Jul", "Apr", "Feb") if dates[v] is not None)
    for key in ("_checks",) + QUARTER_BLOCKS:
        s.pop(key, None)
    s["latest"] = dict(s["latest"], period_label=seg["periods"][-1], period_end=seg["period_ends"][-1],
                       release_date=dates[previous])
    s["sources"] = ([{"label": f"Moody’s {seg['periods'][-1]} 业绩新闻稿（8-K EX-99.1）",
                      "url": "https://www.sec.gov/Archives/edgar/data/1059556/000162828026026383/previous.htm"}]
                    + [src for src in s["sources"] if "业绩新闻稿" not in src["label"] and "10-Q" not in src["label"]])
    return s


def rolled_forward(staging: dict) -> dict:
    """The series one quarter later with made-up figures; a fourth quarter's
    release settles the year and opens the next with a February range."""
    s = copy.deepcopy(staging)
    seg = s["segment_quarterly"]
    last = seg["periods"][-1]
    quarter, year = int(last[1]), int(last[-4:])
    quarter, year = (1, year + 1) if quarter == 4 else (quarter + 1, year)
    label = f"Q{quarter} {year}"
    ends = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}
    n = len(seg["periods"])
    for block in [seg] + [s[key] for key in ALIGNED_BLOCKS]:
        for key, values in block.items():
            if not isinstance(values, list) or len(values) != n:
                continue
            if key == "periods":
                values.append(label)
            elif key == "period_ends":
                values.append(f"{year}-{ends[quarter]}")
            else:
                values.append(None if values[-1] is None else values[-1] * 1.01)
    g = s["annual_guidance_history"]
    open_year = max(g["fiscal_years"])
    i = g["fiscal_years"].index(open_year)
    dates = g["release_dates"][str(open_year)]
    release = {1: f"{year}-04-25", 2: f"{year}-07-25", 3: f"{year}-10-25", 4: f"{year + 1}-02-15"}[quarter]
    missing = next((v for v in ("Feb", "Apr", "Jul", "Oct") if dates[v] is None), None)
    if missing:
        before = ("Feb", "Apr", "Jul", "Oct")[("Feb", "Apr", "Jul", "Oct").index(missing) - 1]
        dates[missing] = release
        for key in list(g):
            if isinstance(g[key], dict) and missing in g[key] and isinstance(g[key][missing], list):
                g[key][missing][i] = g[key][before][i]
    if quarter == 4:
        g["actual_adj_eps_usd"][i] = (g["adj_eps_lo"]["Oct"][i] + g["adj_eps_hi"]["Oct"][i]) / 2
        g["fiscal_years"].append(open_year + 1)
        g["actual_adj_eps_usd"].append(None)
        g["release_dates"][str(open_year + 1)] = {"Feb": release, "Apr": None, "Jul": None, "Oct": None}
        for key in list(g):
            if isinstance(g[key], dict) and "Feb" in g[key] and isinstance(g[key]["Feb"], list):
                for v in ("Feb", "Apr", "Jul", "Oct"):
                    g[key][v].append(g[key]["Oct"][i] if v == "Feb" else None)
        ann = s["annual_actuals"]
        for key, values in ann.items():
            if isinstance(values, list):
                values.append(open_year if key == "fiscal_years" else values[-1] * 1.05)
        ann["adjusted_diluted_eps_usd"][-1] = g["actual_adj_eps_usd"][i]
        ann["free_cash_flow_usd_m"][-1] = ann["operating_cash_flow_usd_m"][-1] - ann["capex_usd_m"][-1]
    for key in ("_checks",) + QUARTER_BLOCKS:
        s.pop(key, None)
    s["latest"] = dict(s["latest"], period_label=label, period_end=f"{year}-{ends[quarter]}", release_date=release)
    s["sources"] = [{"label": f"Moody’s {label} 业绩新闻稿（8-K EX-99.1）",
                     "url": "https://www.sec.gov/Archives/edgar/data/1059556/next.htm"}] + s["sources"]
    return s


class McoRollTest(unittest.TestCase):
    """What a roll can change without touching the builder."""

    STORY_ONLY = ("被两笔业务处置压住的 MA 报告收入增速", "见口径说明", "Learning Solutions",
                  "“high-single-digit percent range”", "它给的证伪条件是", "low-single-digit 增长")

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
        stale["quarter_figures"]["period"] = "Q1 1999"
        with self.assertRaisesRegex(ValueError, "stamped"):
            mco.headline_metrics(stale)

    def test_the_quarters_own_release_must_be_in_the_sources(self) -> None:
        bare = copy.deepcopy(self.s)
        prefix = f"Moody’s {self.s['segment_quarterly']['periods'][-1]} 业绩新闻稿"
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
        section = next(s for s in payload["sections"] if s["id"] == "next_quarter")
        self.assertEqual(section["exhibits"], [])
        numbers = [ex["n"] for ex in exhibits_of(payload)]
        self.assertEqual(numbers, list(range(1, len(numbers) + 1)))
        self.assertEqual([t["n"] for t in payload["tables"]],
                         list(range(numbers[-1] + 1, numbers[-1] + 1 + len(payload["tables"]))))
        self.assertNotRegex(text, PLACEHOLDER)
        self.assertNotRegex(text, r"\{EX_[A-Z_]+\}")
        self.assertTrue(mco.headline_metrics(bare)[2].startswith("MA adj OpM"))

    def test_the_quarter_before_builds_from_the_series_alone(self) -> None:
        rolled = rolled_back(self.s)
        payload = build_payload(rolled)
        label = rolled["segment_quarterly"]["periods"][-1]
        self.assertEqual(payload["latest"]["disclosed_period_label"], label)
        self.assertIn(f"{label} 季报仪表盘", payload["title"])
        self.assertNotIn(self.s["segment_quarterly"]["periods"][-1], own_text(payload))
        final_band = exhibits_of(payload)[0]
        year = max(rolled["annual_guidance_history"]["fiscal_years"])
        self.assertIn(f"FY{year} 尚无 10 月期，图上用 4 月那期", final_band["src_extra"])

    def test_the_quarters_after_build_from_the_series_alone(self) -> None:
        s = self.s
        for _ in range(2):
            s = rolled_forward(s)
            payload = build_payload(s)
            self.assertIn(f"{s['segment_quarterly']['periods'][-1]} 季报仪表盘", payload["title"])
            self.assertNotRegex(own_text(payload), PLACEHOLDER)
        g = s["annual_guidance_history"]
        closed = max(g["fiscal_years"]) - 1
        final_band = exhibits_of(payload)[0]
        self.assertEqual(final_band["xlabels"][-2], f"FY{closed}")
        self.assertIn(f"FY{closed + 1} 尚无 10 月期，图上用 2 月那期", final_band["src_extra"])
        finished = sum(1 for v in g["actual_adj_eps_usd"] if v is not None)
        self.assertIn(f"{finished} 个已完结年度里", payload["headline"])


class McoFindingsTest(unittest.TestCase):
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

    def test_the_ma_revenue_claims(self) -> None:
        def rising(s):
            ma = s["segment_quarterly"]["ma_revenue_usd_m"]
            for i in range(1, len(ma)):
                ma[i] = max(ma[i], ma[i - 1] + 1)

        def one_down_year(s):
            rising(s)
            ma = s["segment_quarterly"]["ma_revenue_usd_m"]
            ma[10] = ma[6] - 1

        up = self.page(rising)
        self.assertIn("之间来回，MA 只是一路往上", up)
        self.assertIn("有同比基数的季度里没有一个季度同比为负", up)
        down = self.page(one_down_year)
        self.assertIn("MA 有一季同比为负", down)
        self.assertNotIn("没有一个季度同比为负", down)
        self.assertIn("MA 同比从未为负", self.page())

    def test_the_ma_margin_claims(self) -> None:
        def steady(s):
            m = s["segment_quarterly"]["ma_adj_operating_margin_pct"]
            for i in range(len(m)):
                m[i] = 20.0 + 0.3 * i

        climbing = self.page(steady)
        self.assertIn("MA 稳步抬升", climbing)
        self.assertIn("一格一格抬上去的", climbing)
        bumpy = self.page()
        self.assertNotIn("稳步抬升", bumpy)
        self.assertIn("但不是一格一格抬上去的", bumpy)

    def test_the_final_guidance_claims(self) -> None:
        def never_below(s):
            g = s["annual_guidance_history"]
            for i, actual in enumerate(g["actual_adj_eps_usd"]):
                if actual is not None:
                    g["actual_adj_eps_usd"][i] = max(actual, g["adj_eps_lo"]["Oct"][i])

        clean = self.page(never_below)
        self.assertIn("末次指引从没跌破过", clean)
        self.assertIn("年里一次都没有跌破过末次指引的下限", clean)
        self.assertNotIn("被排除的那一年，恰好是唯一一年推翻这句话的", clean)
        self.assertNotIn("唯一跌破末次指引下限的一年", clean)
        current = self.page()
        self.assertIn("被排除的那一年，恰好是唯一一年推翻这句话的", current)

    def test_the_initial_guidance_claims(self) -> None:
        def one_inside(s):
            g = s["annual_guidance_history"]
            i = next(i for i, v in enumerate(g["actual_adj_eps_usd"]) if v is not None)
            g["actual_adj_eps_usd"][i] = (g["adj_eps_lo"]["Feb"][i] + g["adj_eps_hi"]["Feb"][i]) / 2

        once = self.page(one_inside)
        self.assertIn("初始指引对过一次", once)
        self.assertNotIn("一次都没落在区间内", once)
        self.assertNotIn("2 月画的那条带子从来没对过", once)

    def test_the_revision_extremes(self) -> None:
        def deeper_cut(s):
            g = s["annual_guidance_history"]
            i = g["fiscal_years"].index(2019)
            g["adj_eps_lo"]["Oct"][i], g["adj_eps_hi"]["Oct"][i] = 4.0, 4.2

        text = self.page(deeper_cut)
        self.assertIn("FY2019 砍了", text)
        self.assertIn("FY2019 指引中值从 2 月的", text)
        self.assertNotIn("FY2019 当年发行量随利率崩掉", text)

    def test_the_annual_lows(self) -> None:
        def no_settlement(s):
            ann = s["annual_actuals"]
            ann["operating_margin_pct"][0] = 50.0
            ann["free_cash_flow_usd_m"][1] = 3000.0

        text = self.page(no_settlement)
        self.assertIn("低点是 FY2022 的 34.4%，正是发行量崩掉那年；", text)
        self.assertIn("穆迪的现金问题从来不在资本开支上，而在发行量上", text)
        current = self.page()
        self.assertIn("FY2017 那个低点是那笔 DOJ 和解款实际付出去的一年", current)

    def test_the_capex_share_claim(self) -> None:
        def light(s):
            ann = s["annual_actuals"]
            ann["capex_usd_m"] = [r * 0.03 for r in ann["revenue_usd_m"]]

        self.assertIn("仍不到收入的 5%", self.page(light))
        self.assertIn("最高也只占收入的", self.page())

    def test_the_bridge_claims(self) -> None:
        def broken(s):
            s["guidance_bridges"]["eps"]["addbacks"][0][1] += 0.05

        text = self.page(broken)
        self.assertNotIn("指引表自己就能对平", text)
        self.assertIn("指引表的 EPS 桥：GAAP 指引下限加五项加回项是", text)
        self.assertIn("对不上", text)
        self.assertIn("指引表自己就能对平", self.page())


if __name__ == "__main__":
    unittest.main()
