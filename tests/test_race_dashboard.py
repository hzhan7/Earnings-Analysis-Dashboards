"""Ferrari page: the reconciliations that license what the page publishes.

Two of these tests exist because a specific silent failure happened while the
series was being built, and neither would have been caught by the checks the
other company pages carry:

- `test_quarters_sum_to_the_filed_full_year` is the only check that catches the
  period-column flip. Ferrari's 2016-2018 Q2/Q3 releases print the cumulative
  block where the later ones print the quarter, and reading the wrong one puts
  half-year and nine-month figures into a quarterly series. Every other
  identity here still closed while that was true -- revenue lines summed,
  shipments summed, the EBIT bridge balanced -- because all the components were
  cumulative together.
- `test_the_guidance_column_is_not_a_fixed_position` pins the FY2026 vintages,
  which are the ones whose outlook table puts the guidance column FIRST after
  eight years of putting it last.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import race  # noqa: E402
from build.board import headroom  # noqa: E402


def js_payload(path: Path, marker: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{marker} = ", 1)[1].rstrip().rstrip(";")
    return json.loads(body)


METRICS = ["revenue", "adj_ebitda", "adj_ebit", "adj_eps", "ifcf"]


class RaceDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(race.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = race.build_payload(cls.staging)
        cls.long = cls.staging["long_history"]

    # ── the windows ─────────────────────────────────────────────────────────
    def test_the_window_is_eight_contiguous_quarters(self) -> None:
        periods = self.staging["periods"]
        self.assertEqual(len(periods), 8)
        for earlier, later in zip(periods, periods[1:]):
            y1, q1 = int(earlier[-4:]), int(earlier[1])
            y2, q2 = int(later[-4:]), int(later[1])
            self.assertEqual((y2, q2), (y1 + 1, 1) if q1 == 4 else (y1, q1 + 1))

    def test_the_long_series_is_forty_two_contiguous_quarters(self) -> None:
        quarters = self.long["quarters"]
        self.assertEqual(len(quarters), 42)
        self.assertEqual(quarters[0], "Q1 2016")
        self.assertEqual(quarters[-1], "Q2 2026")
        for earlier, later in zip(quarters, quarters[1:]):
            y1, q1 = int(earlier[-4:]), int(earlier[1])
            y2, q2 = int(later[-4:]), int(later[1])
            self.assertEqual((y2, q2), (y1 + 1, 1) if q1 == 4 else (y1, q1 + 1))

    def test_the_window_is_the_tail_of_the_long_series(self) -> None:
        """The two windows must not disagree about an overlapping quarter."""
        self.assertEqual(self.long["quarters"][-8:], self.staging["periods"])
        for key, values in self.staging["financials"].items():
            self.assertEqual(values, self.long[key][-8:], key)

    # ── identities inside a quarter ─────────────────────────────────────────
    def test_regions_sum_to_total_shipments_every_quarter(self) -> None:
        long = self.long
        for index, quarter in enumerate(long["quarters"]):
            total = (long["shipments_emea"][index] + long["shipments_americas"][index]
                     + long["shipments_china_hk_taiwan"][index]
                     + long["shipments_rest_of_apac"][index])
            self.assertEqual(total, long["shipments_units"][index], quarter)

    def test_revenue_lines_sum_to_total_revenue_every_quarter(self) -> None:
        long = self.long
        for index, quarter in enumerate(long["quarters"]):
            legs = [long["cars_and_spare_parts_eur_m"][index],
                    long["sponsorship_commercial_brand_eur_m"][index],
                    long["other_revenues_eur_m"][index]]
            engines = long["engines_eur_m"][index]
            if engines is not None:
                legs.append(engines)
            self.assertAlmostEqual(sum(legs), long["net_revenues_eur_m"][index],
                                   delta=1.5, msg=quarter)

    def test_ebitda_less_depreciation_is_ebit_every_quarter(self) -> None:
        long = self.long
        for index, quarter in enumerate(long["quarters"]):
            self.assertAlmostEqual(long["ebitda_eur_m"][index] - long["da_eur_m"][index],
                                   long["ebit_eur_m"][index], delta=1.5, msg=quarter)

    def test_quarters_sum_to_the_filed_full_year(self) -> None:
        """The check that catches the period-column flip, and the only one that does.

        Ferrari prints the cumulative block LEFT of the label in the 2016-2018
        Q2 and Q3 releases and RIGHT of it from 2019, so a positional read puts
        H1 and 9M figures into three years of quarterly slots. Every other
        identity in this file still passed while that was true.
        """
        long = self.long
        checked = 0
        for year, filed in long["full_year_actuals"].items():
            indices = [long["quarters"].index(f"Q{q} {year}") for q in range(1, 5)
                       if f"Q{q} {year}" in long["quarters"]]
            if len(indices) != 4:
                continue
            for series_key, filed_key in [
                ("net_revenues_eur_m", "net_revenues_eur_m"),
                ("shipments_units", "shipments_units"),
                ("ebitda_eur_m", "ebitda_eur_m"),
                ("ebit_eur_m", "ebit_eur_m"),
                ("da_eur_m", "da_eur_m"),
                ("net_profit_eur_m", "net_profit_eur_m"),
                ("industrial_fcf_eur_m", "industrial_fcf_eur_m"),
            ]:
                total = sum(long[series_key][i] for i in indices)
                self.assertAlmostEqual(total, filed[filed_key], delta=1.5,
                                       msg=f"{year} {series_key}")
                checked += 1
        self.assertGreaterEqual(checked, 70)

    def test_margins_are_the_ratio_they_claim_to_be(self) -> None:
        long = self.long
        for index, quarter in enumerate(long["quarters"]):
            revenue = long["net_revenues_eur_m"][index]
            self.assertAlmostEqual(long["ebit_eur_m"][index] / revenue * 100,
                                   long["ebit_margin_pct"][index], places=3, msg=quarter)
            self.assertAlmostEqual(long["ebitda_eur_m"][index] / revenue * 100,
                                   long["ebitda_margin_pct"][index], places=3, msg=quarter)

    def test_revenue_per_unit_is_cars_revenue_over_shipments(self) -> None:
        long = self.long
        for index, quarter in enumerate(long["quarters"]):
            derived = (long["cars_and_spare_parts_eur_m"][index] * 1000
                       / long["shipments_units"][index])
            self.assertAlmostEqual(derived, long["cars_revenue_per_unit_eur_k"][index],
                                   places=3, msg=quarter)

    # ── series that start or stop where disclosure does ─────────────────────
    def test_engines_is_a_hole_after_the_presentation_change_not_a_zero(self) -> None:
        """Filling it with zero would draw a reporting change as a business exit."""
        long = self.long
        engines = long["engines_eur_m"]
        first_gap = engines.index(None)
        self.assertEqual(long["quarters"][first_gap], "Q1 2024")
        self.assertTrue(all(value is None for value in engines[first_gap:]))
        self.assertTrue(all(value is not None for value in engines[:first_gap]))

    def test_net_industrial_debt_is_the_level_not_the_change(self) -> None:
        """Q2 2016 was published as +19 for a while. It is -763.

        The Q2 2016 release prints `Net industrial debt (763) (782) 19` across
        three columns -- Jun 30, Mar 31, and the *change* between them. This
        page held the change as if it were the level, which turned EUR 763M of
        net debt into EUR 19M of net cash and put a spike between two quarters
        of -782 and -585.

        The assertion is deliberately built on the arithmetic that explains the
        mistake rather than on the corrected number alone: the value the old
        page carried is exactly this quarter's change, so pinning both makes a
        silent revert impossible and says what went wrong.
        """
        long = self.long
        index = long["quarters"].index("Q2 2016")
        level = long["net_industrial_debt_eur_m"]
        self.assertEqual(level[index], -763.0)
        self.assertEqual(level[index - 1], -782.0)
        self.assertAlmostEqual(level[index] - level[index - 1], 19.0, places=6,
                               msg="the number this page used to publish was the change")
        # And the series does not swing across zero between neighbours anywhere
        # else in 2016-2017, which is what made the old value look wrong.
        for i in range(1, long["quarters"].index("Q4 2017") + 1):
            self.assertFalse(
                level[i - 1] < -300 < 0 < level[i],
                f"{long['quarters'][i]}: net industrial debt jumped from deep net debt "
                "to net cash in one quarter -- check whether a change column was read "
                "as a level",
            )
        self.assertIn("Change", long["backfill_note"])

    def test_capex_now_runs_the_whole_record_and_says_how(self) -> None:
        """The quarterly Capex and R&D table only starts in 2019 -- the earlier
        quarters are reconstructed, and the reconstruction has to be checkable.

        Ferrari prints cumulative capex in each interim report and the full year
        in the 20-F, so 2016-2018 comes out by differencing: Q1 is the printed
        three-month column, Q2 and Q3 are cumulative differences, Q4 is the
        20-F year less nine months. That is a derivation, so what is pinned here
        is not the values but the two identities that make them publishable --
        each year's four quarters summing to the printed full year, and the 2018
        quarters matching the prior-year columns that the 2019 releases printed
        independently.
        """
        long = self.long
        capex = long["capex_eur_m"]
        development = long["capitalised_development_eur_m"]
        self.assertEqual(long["quarters"][0], "Q1 2016")
        self.assertTrue(all(v is not None for v in capex), "capex has a hole")
        # Capitalised development is missing exactly one quarter, and that is a
        # disclosure gap rather than a reconstruction failure.
        missing = [q for q, v in zip(long["quarters"], development) if v is None]
        self.assertEqual(missing, ["Q1 2025"])
        # The reconstruction identity, for the three years that needed it.
        printed_full_year = {2016: (342, 141), 2017: (392, 185), 2018: (639, 318)}
        for year, (capex_year, dev_year) in printed_full_year.items():
            rows = [i for i, q in enumerate(long["quarters"]) if q.endswith(str(year))]
            self.assertEqual(len(rows), 4, year)
            self.assertAlmostEqual(sum(capex[i] for i in rows), capex_year, places=6, msg=year)
            self.assertAlmostEqual(sum(development[i] for i in rows), dev_year, places=6, msg=year)
        # And the page says the early quarters are derived rather than printed.
        self.assertIn("累计相减", long["backfill_note"])

    # ── the annual guidance record ──────────────────────────────────────────
    def test_the_record_is_thirty_one_vintages_over_eight_fiscal_years(self) -> None:
        record = self.staging["annual_guidance_history"]
        self.assertEqual(len(record["vintages"]), 31)
        self.assertEqual(sorted(set(record["fiscal_years"])), list(range(2019, 2027)))
        for key in ("vintage_slots", "release_dates", "fiscal_years", "source_quarters"):
            self.assertEqual(len(record[key]), 31, key)

    def test_only_the_final_vintage_of_a_finished_year_carries_an_actual(self) -> None:
        record = self.staging["annual_guidance_history"]
        for metric in METRICS:
            actual = record["items"][metric]["actual"]
            for index, value in enumerate(actual):
                year = record["fiscal_years"][index]
                is_last = (index + 1 == len(actual)
                           or record["fiscal_years"][index + 1] != year)
                if year < 2026 and is_last:
                    self.assertIsNotNone(value, f"{metric} {year}")
                else:
                    self.assertIsNone(value, f"{metric} {year} index {index}")

    def test_a_range_has_its_endpoints_the_right_way_round(self) -> None:
        record = self.staging["annual_guidance_history"]
        for metric in METRICS:
            item = record["items"][metric]
            for low, high, form in zip(item["lo"], item["hi"], item["form"]):
                if low is None:
                    continue
                self.assertLessEqual(low, high, metric)
                if form != "range":
                    self.assertEqual(low, high, f"{metric} {form}")

    def test_the_form_tally_the_page_publishes_is_the_one_in_the_data(self) -> None:
        """The headline claim: the year-end vintage carries one range in 35.

        If the data stops saying that, the page must not keep saying it.
        """
        record = self.staging["annual_guidance_history"]
        counts: dict[str, dict[str, int]] = {}
        for index, slot in enumerate(record["vintage_slots"]):
            bucket = counts.setdefault(slot, {})
            for metric in METRICS:
                form = record["items"][metric]["form"][index]
                if form:
                    bucket[form] = bucket.get(form, 0) + 1
        self.assertEqual(counts["q3"].get("range", 0), 1)
        self.assertEqual(sum(counts["q3"].values()), 35)
        self.assertEqual(counts["initial"].get("range", 0), 15)
        self.assertEqual(sum(counts["initial"].values()), 40)
        for slot in ("initial", "q1", "q2"):
            self.assertGreaterEqual(counts[slot].get("range", 0), 15, slot)

    def test_every_year_that_opened_as_a_range_closed_as_something_else(self) -> None:
        record = self.staging["annual_guidance_history"]
        item = record["items"]["adj_ebitda"]
        opened_as_range = 0
        for year in sorted(set(record["fiscal_years"])):
            indices = [i for i, fy in enumerate(record["fiscal_years"]) if fy == year]
            forms = [item["form"][i] for i in indices]
            if forms[0] == "range":
                opened_as_range += 1
                self.assertNotEqual(forms[-1], "range", f"FY{year}")
        self.assertEqual(opened_as_range, 5)

    def test_no_finished_year_landed_below_its_final_guidance(self) -> None:
        record = self.staging["annual_guidance_history"]
        for metric in METRICS:
            item = record["items"][metric]
            for low, high, form, actual in zip(item["lo"], item["hi"],
                                               item["form"], item["actual"]):
                if actual is None or low is None:
                    continue
                self.assertNotEqual(race.verdict(low, high, form, actual), "below",
                                    f"{metric} {actual}")

    def test_a_point_guidance_is_settled_at_its_printed_precision(self) -> None:
        """FY2019 adjusted EBITDA is 1.269 against a guided ~1.27, i.e. on it.

        Scoring that as a miss would apply a threshold finer than the
        disclosure it is measured against.
        """
        self.assertEqual(race.verdict(1.27, 1.27, "point", 1.269), "met")
        self.assertEqual(race.verdict(1.27, 1.27, "point", 1.30), "above")
        self.assertEqual(race.verdict(1.27, 1.27, "point", 1.20), "below")

    def test_the_guidance_column_is_not_a_fixed_position(self) -> None:
        """FY2026's outlook table puts the guidance FIRST; every earlier one last.

        Taking a fixed column would have published the prior-year actual
        (EUR 7.15B) as the FY2026 revenue guidance.
        """
        record = self.staging["annual_guidance_history"]
        fy26 = [i for i, fy in enumerate(record["fiscal_years"]) if fy == 2026]
        revenue = [record["items"]["revenue"]["hi"][i] for i in fy26]
        self.assertEqual(revenue, [7.5, 7.5, 7.6])
        eps = [record["items"]["adj_eps"]["hi"][i] for i in fy26]
        self.assertEqual(eps, [9.45, 9.45, 9.68])
        self.assertNotIn(7.15, revenue)

    def test_the_open_year_is_never_drawn_as_settled(self) -> None:
        record = self.staging["annual_guidance_history"]
        for index, year in enumerate(record["fiscal_years"]):
            if year == 2026:
                for metric in METRICS:
                    self.assertIsNone(record["items"][metric]["actual"][index], metric)

    # ── thresholds ──────────────────────────────────────────────────────────
    def test_every_quantified_threshold_has_a_headroom_bar(self) -> None:
        kpi = self.staging["next_kpi"]["quantified"]
        bar = self.payload["sections"][2]["exhibits"][0]
        self.assertEqual(bar["xlabels"], [entry["metric"] for entry in kpi])
        for entry, value in zip(kpi, bar["values"]):
            self.assertAlmostEqual(
                headroom(entry["direction"], entry["threshold"], entry["current"]),
                value, places=1, msg=entry["metric"])

    def test_thresholds_are_current_with_the_latest_quarter(self) -> None:
        kpi = {entry["metric"]: entry["current"]
               for entry in self.staging["next_kpi"]["quantified"]}
        financials = self.staging["financials"]
        self.assertAlmostEqual(kpi["EBIT 利润率"], financials["ebit_margin_pct"][-1], places=2)
        self.assertAlmostEqual(kpi["单季 D&A"], financials["da_eur_m"][-1], places=2)

    def test_what_the_page_refuses_to_publish_is_named(self) -> None:
        excluded = self.staging["next_kpi"]["excluded"]
        for term in ["个性化", "订单簿", "对冲", "车型级"]:
            self.assertIn(term, excluded)

    def test_no_market_expectation_or_rating_is_published(self) -> None:
        """No plotted or tabulated figure may be a consensus, rating or target.

        Scanning the whole payload for those words was the first version of
        this test and it failed on the note that says the page does not publish
        them -- a check that cannot distinguish a disclaimer from the thing it
        disclaims. So it looks at the places a number would actually appear.
        """
        self.assertNotIn("market_expectation", self.staging)
        forbidden = ["市场预期", "目标价", "一致预期", "评级"]
        surfaces: list[str] = []
        for section in self.payload["sections"]:
            for exhibit in section["exhibits"]:
                surfaces.append(exhibit["title"])
                surfaces.extend(s["name"] for s in exhibit.get("series", []))
                surfaces.extend(g["name"] for g in exhibit.get("groups", []))
                surfaces.extend(exhibit.get("xlabels", []))
        for table in self.payload["tables"]:
            surfaces.append(table["title"])
            surfaces.extend(table["headers"])
            surfaces.extend(str(cell) for row in table["rows"] for cell in row)
        for surface in surfaces:
            for term in forbidden:
                self.assertNotIn(term, surface, surface[:60])

    # ── currency ────────────────────────────────────────────────────────────
    def test_money_is_printed_in_euro_not_dollars(self) -> None:
        """Ferrari reports in euro; a dollar sign here is a unit error."""
        quarterly = next(table for table in self.payload["tables"]
                         if "近八季" in table["title"])
        for row in quarterly["rows"]:
            for cell in row:
                self.assertNotIn("$", cell, cell)
        self.assertTrue(any("€" in cell for row in quarterly["rows"] for cell in row))

    # ── exhibits and publication ────────────────────────────────────────────
    def test_the_page_carries_the_cross_page_capex_table(self) -> None:
        """Published byte-identically on every page, including pages outside the chain."""
        titles = [table["title"] for table in self.payload["tables"]]
        self.assertTrue(any("AI capex" in title for title in titles), titles)

    def test_exhibits_are_numbered_in_render_order_and_refs_resolve(self) -> None:
        numbers = [ex["n"] for section in self.payload["sections"]
                   for ex in section["exhibits"]]
        self.assertEqual(numbers, list(range(2, 2 + len(numbers))))
        text = json.dumps(self.payload, ensure_ascii=False)
        self.assertNotRegex(text, r"\{EX_[A-Z_]+\}")

    def test_tables_are_numbered_after_the_exhibits(self) -> None:
        last = max(ex["n"] for section in self.payload["sections"]
                   for ex in section["exhibits"])
        self.assertEqual([table["n"] for table in self.payload["tables"]],
                         list(range(last + 1, last + 1 + len(self.payload["tables"]))))

    def test_every_exhibit_carries_a_note_and_a_source_line(self) -> None:
        for section in self.payload["sections"]:
            for exhibit in section["exhibits"]:
                self.assertTrue(exhibit.get("note"), exhibit["title"])
                self.assertTrue(exhibit.get("src_extra"), exhibit["title"])

    def test_literal_text_fields_carry_no_markup(self) -> None:
        """`page.js` escapes or textContents these, so a tag would print raw."""
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
        """`tableHTML(title, headers, rows, cls)` is all of it; a `note` is dropped."""
        for table in self.payload["tables"]:
            self.assertEqual(set(table), {"n", "title", "headers", "rows"},
                             table["title"][:40])

    def test_every_table_row_matches_its_header_width(self) -> None:
        for table in self.payload["tables"]:
            for row in table["rows"]:
                self.assertEqual(len(row), len(table["headers"]), table["title"][:40])

    def test_the_page_declares_its_filing_and_currency_basis(self) -> None:
        subtitle = self.payload["subtitle"]
        self.assertIn("IFRS", subtitle)
        self.assertIn("欧元", subtitle)
        self.assertIn("6-K", subtitle)
        joined = " ".join(self.payload["notes"])
        self.assertIn("20-F", joined)
        self.assertIn("10-Q", joined)

    def test_the_published_payload_matches_a_fresh_build(self) -> None:
        published = js_payload(ROOT / "data" / "race.js", "window.DASH")
        self.assertEqual(published, self.payload)


if __name__ == "__main__":
    unittest.main()
