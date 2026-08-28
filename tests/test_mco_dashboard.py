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
of the first section. Against the final (October) range the record looks like
every other "never missed" record on this site; against the initial (February)
range the same seven years look nothing like it. A test that only counted
"cleared its guidance" would not notice if the two were ever conflated, so this
one pins both tallies separately, and pins that they disagree.

One more thing is pinned because it was a live trap rather than a hypothesis:
the segment columns in the earnings releases swapped order in April 2023 (MIS
first, then MA first). The series is read by segment name rather than by column
position, and the quarters that appear in two releases agree item by item. The
test asserts the resulting shape -- MIS's share of adjusted operating income
exceeds its share of revenue in every quarter -- which is false under a swap.
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

from build.all import ENTRIES, GROUPS, build_all, roster_payload  # noqa: E402
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
        eps = self.source["bridges_2026"]["eps"]
        addbacks = sum(delta for _, delta in eps["addbacks"])
        for i in (0, 1):
            self.assertAlmostEqual(eps["gaap"][i] + addbacks, eps["adjusted"][i], places=2)
        self.assertEqual(eps["adjusted"], [16.50, 17.00])
        # The negative add-back is what makes FY2026 unlike the earlier years.
        self.assertTrue(any(delta < 0 for _, delta in eps["addbacks"]))

    def test_the_margin_bridge_closes_to_a_tenth_of_a_point(self) -> None:
        margin = self.source["bridges_2026"]["margin"]
        addbacks = sum(delta for _, delta in margin["addbacks"])
        for i in (0, 1):
            self.assertAlmostEqual(margin["gaap"][i] + addbacks, margin["adjusted"][i], places=1)
        self.assertEqual(margin["adjusted"], [52.0, 53.0])

    def test_the_cash_flow_bridge_closes(self) -> None:
        fcf = self.source["bridges_2026"]["fcf"]
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

    def test_the_final_guidance_was_never_broken_on_the_downside(self) -> None:
        above, inside, below = self._tally("Oct")
        self.assertEqual((above, inside, below), (4, 3, 0))
        self.assertEqual(above + inside + below, 7, "seven finished years")

    def test_the_initial_guidance_was_never_once_right(self) -> None:
        """Not a rounding of the same fact: the February range never contained it."""
        above, inside, below = self._tally("Feb")
        self.assertEqual((above, inside, below), (6, 0, 1))

    def test_the_two_horizons_disagree(self) -> None:
        """The page's first section exists only because these two differ."""
        self.assertNotEqual(self._tally("Oct"), self._tally("Feb"))

    def test_fy2022_is_the_one_miss_and_it_was_cut_by_a_third(self) -> None:
        g = self.source["annual_guidance_history"]
        i = g["fiscal_years"].index(2022)
        feb = (g["adj_eps_lo"]["Feb"][i] + g["adj_eps_hi"]["Feb"][i]) / 2
        oct_ = (g["adj_eps_lo"]["Oct"][i] + g["adj_eps_hi"]["Oct"][i]) / 2
        self.assertAlmostEqual(feb, 12.65, places=2)
        self.assertAlmostEqual(oct_, 8.35, places=2)
        self.assertLess((oct_ / feb - 1) * 100, -33.0)
        # And the actual still cleared that final, cut-down range.
        self.assertGreater(g["actual_adj_eps_usd"][i], g["adj_eps_hi"]["Oct"][i])

    def test_fy2018_is_not_in_the_record(self) -> None:
        """It has only an October vintage, so counting it would mix a stub year in."""
        self.assertNotIn(2018, self.source["annual_guidance_history"]["fiscal_years"])
        self.assertIn(2018, self.source["annual_actuals"]["fiscal_years"])

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
        charts overstates MIS's margin by roughly 2-3pp, because MIS bills MA
        around US$50M a quarter internally. Against total revenue the identity
        closes to within 0.05pp in all 21 quarters -- that residual is the
        rounding of the published percentage, nothing else. Pinned tightly on
        purpose: a loose tolerance here would accept the wrong denominator.
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

    def test_adjusted_eps_exceeds_gaap_eps_every_year(self) -> None:
        ann = self.source["annual_actuals"]
        for i, year in enumerate(ann["fiscal_years"]):
            self.assertGreater(ann["adjusted_diluted_eps_usd"][i],
                               ann["diluted_eps_usd"][i], f"FY{year}")

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

        A `note` on a table dict is silently discarded -- it never reaches the
        page, but it reads in the source like a published caveat, so the next
        editor writes the qualification there and believes it shipped. This page
        did exactly that on its first build: three tables carried notes no
        reader could see, and the substance now lives in `notes`, which is
        rendered. Every other page on the site carries zero.
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
        self.assertIn("一次都没落在区间内", headline)


if __name__ == "__main__":
    unittest.main()
