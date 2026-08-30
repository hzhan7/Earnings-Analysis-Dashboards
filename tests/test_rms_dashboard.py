"""Hermès page: the reconciliations that license what the page publishes.

Three of these exist because of something specific to this filer rather than
because every page has one:

- `test_the_page_never_puts_profit_on_a_quarterly_axis` is the structural check.
  Hermès publishes revenue quarterly and an income statement twice a year, so
  the page carries two clocks. Nothing else in the suite notices a margin drawn
  against `Q2 2026`: the values would be finite, the lengths would match, the
  build would be deterministic and the render gate would find no NaN. It would
  simply be a number the company never published, plotted under a label that
  says it did. This asserts the separation the module docstring promises, from
  the shape of each exhibit's own axis rather than from a list of exhibit names.
- `test_a_derived_constant_currency_rate_does_not_match_the_printed_one` is why
  the staging file forbids deriving one. Constant-currency rates are printed per
  line per period; a first half minus its second quarter looks like it should
  give the first quarter and does not, because every component is rounded to the
  million and the rate to a tenth of a point first. The two lines pinned here
  come out 0.3pp away, which is the size of the accelerations this page reads.
- `test_the_margin_bridge_closes_on_the_printed_statement` pins the €1M that the
  printed half-year income statement does not close by. Gross margin less
  selling and administrative expenses less other income and expenses is €3,350M
  against a printed recurring operating income of €3,351M, so a bridge built
  from the components alone lands 0.012pp away from the figure it is supposed to
  reach. The last leg absorbs it and this is what checks that it does.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import rms  # noqa: E402
from build.board import headroom  # noqa: E402


def js_payload(path: Path, marker: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{marker} = ", 1)[1].rstrip().rstrip(";")
    return json.loads(body)


QUARTER = re.compile(r"^Q[1-4] \d{4}$")
YEAR = re.compile(r"^\d{4}$")
# Words that can only belong to a figure this company publishes twice a year.
PROFIT_WORDS = ("利润", "每股", "现金流", "投资")


class RmsSeriesTest(unittest.TestCase):
    """The transcription, checked against identities the company itself prints."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(rms.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = rms.build_payload(cls.staging)

    def test_the_window_is_eight_contiguous_quarters(self) -> None:
        periods = self.staging["periods"]
        self.assertEqual(len(periods), 8)
        for earlier, later in zip(periods, periods[1:]):
            y1, q1 = int(earlier[-4:]), int(earlier[1])
            y2, q2 = int(later[-4:]), int(later[1])
            self.assertEqual((y2, q2), (y1 + 1, 1) if q1 == 4 else (y1, q1 + 1))

    def test_every_quarterly_series_is_as_long_as_the_window(self) -> None:
        width = len(self.staging["periods"])
        for name in ("by_sector", "by_region"):
            for key, block in self.staging[name].items():
                for field in ("revenue_eur_m", "published_pct", "cc_pct", "prior_year_eur_m"):
                    self.assertEqual(len(block[field]), width, f"{name}.{key}.{field}")

    def test_the_seven_metiers_sum_to_the_printed_group_total(self) -> None:
        """Each line is printed to the million, so ±1 is the whole tolerance."""
        for index, period in enumerate(self.staging["periods"]):
            total = self.staging["group_revenue"]["revenue_eur_m"][index]
            summed = sum(block["revenue_eur_m"][index]
                         for block in self.staging["by_sector"].values())
            self.assertLessEqual(abs(summed - total), 1, f"{period}: {summed} vs {total}")

    def test_the_six_regions_sum_to_the_printed_group_total(self) -> None:
        for index, period in enumerate(self.staging["periods"]):
            total = self.staging["group_revenue"]["revenue_eur_m"][index]
            summed = sum(block["revenue_eur_m"][index]
                         for block in self.staging["by_region"].values())
            self.assertLessEqual(abs(summed - total), 1, f"{period}: {summed} vs {total}")

    def test_the_four_quarters_of_2025_equal_the_filed_full_year(self) -> None:
        """The one check that would catch a cumulative column read as a quarter.

        Three of the four quarters in this window come out of three different
        document types -- a quarterly revenue announcement, a half-year results
        release and a full-year results release -- and each of those prints a
        cumulative table beside the quarterly one. Reading the wrong block would
        leave every within-period identity intact, because the métiers and the
        regions would go cumulative together and still sum to the cumulative
        total. Only the year does not close.
        """
        periods = self.staging["periods"]
        quarters = sum(self.staging["group_revenue"]["revenue_eur_m"][i]
                       for i, p in enumerate(periods) if p.endswith("2025"))
        self.assertEqual(quarters, self.staging["full_years"]["2025"]["revenue_eur_m"])

    def test_the_two_2026_quarters_equal_the_printed_first_half(self) -> None:
        periods = self.staging["periods"]
        first, second = periods.index("Q1 2026"), periods.index("Q2 2026")
        half = self.staging["first_half_2026"]
        for name in ("by_sector", "by_region"):
            for key, row in half[name].items():
                block = self.staging[name][key]
                summed = block["revenue_eur_m"][first] + block["revenue_eur_m"][second]
                self.assertLessEqual(abs(summed - row["revenue_eur_m"]), 1,
                                     f"{name}.{key}: {summed} vs {row['revenue_eur_m']}")
                prior = block["prior_year_eur_m"][first] + block["prior_year_eur_m"][second]
                self.assertLessEqual(abs(prior - row["prior_year_eur_m"]), 1,
                                     f"{name}.{key} prior year")

    def test_a_derived_constant_currency_rate_does_not_match_the_printed_one(self) -> None:
        """Why the staging forbids deriving a rate rather than reading one.

        Weighting each printed rate by the prior-year column it is printed
        beside gives a euro increment, so a first-half increment minus a
        second-quarter increment should give the first quarter's. It does not,
        and the gap is not negligible: ready-to-wear derives to +0.5% against a
        printed +0.4%, watches to −3.4% against a printed −3.7%. Both land
        inside the range this page reads accelerations in, so the difference
        between the two habits is the difference between two answers.
        """
        periods = self.staging["periods"]
        first = periods.index("Q1 2026")
        second = periods.index("Q2 2026")
        half = self.staging["first_half_2026"]["by_sector"]
        seen = {}
        for key, row in half.items():
            block = self.staging["by_sector"][key]
            half_increment = row["prior_year_eur_m"] * row["cc_pct"] / 100
            q2_increment = (block["prior_year_eur_m"][second] * block["cc_pct"][second] / 100)
            derived = ((half_increment - q2_increment)
                       / block["prior_year_eur_m"][first] * 100)
            seen[key] = round(derived, 1)
        self.assertEqual(seen["ready_to_wear_accessories"], 0.5)
        self.assertEqual(self.staging["by_sector"]["ready_to_wear_accessories"]["cc_pct"][first], 0.4)
        self.assertEqual(seen["watches"], -3.4)
        self.assertEqual(self.staging["by_sector"]["watches"]["cc_pct"][first], -3.7)
        worst = max(abs(seen[k] - self.staging["by_sector"][k]["cc_pct"][first]) for k in seen)
        self.assertGreaterEqual(round(worst, 1), 0.3)

    def test_every_derived_half_is_the_filed_year_minus_the_filed_half(self) -> None:
        halves = {h["label"]: h for h in self.staging["half_years"]}
        fields = ("revenue_eur_m", "recurring_operating_income_eur_m",
                  "net_profit_group_eur_m", "operating_cash_flows_eur_m",
                  "operating_investments_eur_m", "adjusted_fcf_eur_m")
        derived = [h for h in self.staging["half_years"] if h["derived"]]
        self.assertEqual([h["label"] for h in derived], ["H2 2023", "H2 2024", "H2 2025"])
        for half in derived:
            year = half["label"].split()[1]
            full = self.staging["full_years"][year]
            first = halves[f"H1 {year}"]
            for field in fields:
                self.assertEqual(half[field], full[field] - first[field],
                                 f"{half['label']}.{field}")

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

    def test_the_first_half_outearns_the_second_in_every_finished_year(self) -> None:
        """The page states this as the reason 41% is not a full-year figure."""
        halves = {h["label"]: h["roi_margin_pct"] for h in self.staging["half_years"]}
        gaps = []
        for year in ("2023", "2024", "2025"):
            gap = halves[f"H1 {year}"] - halves[f"H2 {year}"]
            self.assertGreater(gap, 0, year)
            gaps.append(gap)
        self.assertEqual(gaps, sorted(gaps, reverse=True), "the gap is stated as narrowing")

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
        segments = self.staging["h1_segments"]
        lines = {key: (cur, prior) for key, _, cur, prior in self.staging["h1_income"]["lines"]}
        self.assertEqual(sum(s["roi_2026"] for s in segments),
                         lines["recurring_operating_income"][0])
        self.assertEqual(sum(s["roi_2025"] for s in segments),
                         lines["recurring_operating_income"][1])
        # Revenue in the segment note is printed to the million per region and
        # carries its own rounding: the six add to €8,164M against a group line
        # of €8,163M. Profit is not rounded away in the same table and does add
        # exactly, so the two are asserted at different tolerances on purpose.
        operating = [s for s in segments if s["key"] != "unallocated"]
        self.assertLessEqual(abs(sum(s["revenue_2026"] for s in operating) - lines["revenue"][0]), 1)
        self.assertLessEqual(abs(sum(s["revenue_2025"] for s in operating) - lines["revenue"][1]), 1)

    def test_the_six_operating_regions_shrank_while_the_group_grew(self) -> None:
        """The claim the page's headline rests on, asserted from the note itself."""
        segments = self.staging["h1_segments"]
        operating = [s for s in segments if s["key"] != "unallocated"]
        self.assertLess(sum(s["roi_2026"] for s in operating),
                        sum(s["roi_2025"] for s in operating))
        lines = {key: (cur, prior) for key, _, cur, prior in self.staging["h1_income"]["lines"]}
        self.assertGreater(lines["recurring_operating_income"][0],
                           lines["recurring_operating_income"][1])

    def test_the_outlook_is_one_sentence_with_no_number_in_it(self) -> None:
        outlook = self.staging["outlook"]
        self.assertEqual(outlook["numbers_in_sentence"], 0)
        self.assertFalse(re.search(r"\d", outlook["sentence"]), outlook["sentence"])
        self.assertEqual(outlook["sentence"].count("."), 1)
        self.assertGreaterEqual(len(outlook["releases"]), 15)
        dates = [r["date"] for r in outlook["releases"]]
        self.assertEqual(dates, sorted(dates))
        self.assertEqual(len(dates), len(set(dates)))


class RmsPayloadTest(unittest.TestCase):
    """What the page is allowed to draw and say."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(rms.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = rms.build_payload(cls.staging)
        cls.exhibits = [ex for section in cls.payload["sections"]
                        for ex in section["exhibits"]]

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
        self.assertEqual(latest["disclosed_period_label"], "Q2 2026")
        self.assertEqual(latest["full_financial_period_label"], "H1 2026")
        self.assertNotEqual(latest["disclosed_period_label"],
                            latest["full_financial_period_label"])

    # ── the arithmetic the page prints in its own titles ────────────────────
    def test_the_margin_bridge_closes_on_the_printed_statement(self) -> None:
        bridge = next(ex for ex in self.exhibits if ex["kind"] == "bridge_bar")
        legs = [v for v in bridge["stacks"][0]["values"] if v is not None]
        net = [v for v in bridge["net"]["values"] if v is not None]
        self.assertEqual(len(net), 1)
        # Everything in the payload is rounded to four decimal places, so the
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

    def test_the_bridge_note_ranks_impairment_the_way_the_bridge_does(self) -> None:
        """Two claims, and the first one is the one that is easy to get wrong.

        Selling and administrative expenses are a bigger drag than impairment
        (−0.46pp against −0.33pp), so 「费用端最大的一项是减值」 read across the
        whole bridge would be false. What is true is that the gross-margin gain
        and the SG&A drag cancel to almost nothing, leaving the net decline
        inside the other-income line, where impairment is the largest item and
        is itself the size of the whole net change.
        """
        bridge = next(ex for ex in self.exhibits if ex["kind"] == "bridge_bar")
        legs = dict(zip(bridge["xlabels"], bridge["stacks"][0]["values"]))
        self.assertLess(legs["销管费用"], legs["减值损失"],
                        "SG&A is the larger drag; the note must not say otherwise")
        self.assertLess(abs(legs["毛利率"] + legs["销管费用"]), 0.01)
        inside = {k: legs[k] for k in ("折旧与摊销", "减值损失", "免费股计划")}
        self.assertEqual(min(inside, key=lambda k: inside[k]), "减值损失")
        net = next(v for v in bridge["net"]["values"] if v is not None)
        self.assertGreater(abs(legs["减值损失"] / net), 0.9)

    def test_the_contribution_shares_sum_to_one_hundred(self) -> None:
        for ref in ("EX_SECTOR_MIX", "EX_REGION_MIX"):
            exhibit = next(ex for ex in self.exhibits if ex.get("ref") == ref)
            for group in exhibit["groups"]:
                self.assertAlmostEqual(sum(group["values"]), 100.0, places=1,
                                       msg=f"{ref} / {group['name']}")

    def test_the_weighted_increments_reconcile_with_the_group_rate(self) -> None:
        """The one derivation this page adds, checked against the group's own rate."""
        group = self.staging["group_revenue"]
        latest = len(self.staging["periods"]) - 1
        top_down = group["prior_year_eur_m"][latest] * group["cc_pct"][latest] / 100
        for block, order in (("by_sector", rms.SECTOR_ORDER), ("by_region", rms.REGION_ORDER)):
            _, bottom_up = rms.cc_increments(self.staging[block], order, latest)
            self.assertLess(abs(bottom_up / top_down - 1), 0.01, block)

    def test_the_wedge_exhibit_is_the_difference_of_the_two_rate_lines(self) -> None:
        rates = next(ex for ex in self.exhibits if ex.get("ref") == "EX_RATES")
        wedge = next(ex for ex in self.exhibits if ex.get("ref") == "EX_WEDGE")
        published, cc = (series["values"] for series in rates["series"])
        self.assertEqual(len(wedge["values"]), len(published))
        for index, value in enumerate(wedge["values"]):
            self.assertAlmostEqual(value, published[index] - cc[index], places=6)

    def test_the_sign_flips_the_page_counts_are_the_ones_in_the_data(self) -> None:
        """The note names four region-quarters; a fifth appearing must be said."""
        periods = self.staging["periods"]
        flips = [(period, key)
                 for key, block in self.staging["by_region"].items()
                 for index, period in enumerate(periods)
                 if block["published_pct"][index] * block["cc_pct"][index] < 0]
        self.assertEqual(len(flips), 4)
        self.assertEqual({key for _, key in flips}, {"japan", "asia_pacific_ex_japan"})
        exhibit = next(ex for ex in self.exhibits if ex.get("ref") == "EX_REGION_RATES")
        self.assertIn(f"<b>{len(flips)} 格的两个口径符号相反</b>", exhibit["note"])

    # ── thresholds ──────────────────────────────────────────────────────────
    def test_every_quantified_threshold_has_a_headroom_bar(self) -> None:
        entries = self.staging["next_kpi"]["quantified"]
        exhibit = next(ex for ex in self.exhibits if ex["kind"] == "diverging_bars"
                       and ex["ylab"] == "距阈值 %")
        self.assertEqual(len(exhibit["values"]), len(entries))
        for index, entry in enumerate(entries):
            self.assertAlmostEqual(
                exhibit["values"][index],
                round(headroom(entry["direction"], entry["threshold"], entry["current"]), 1),
                places=6, msg=entry["metric"])

    def test_thresholds_read_their_current_value_from_the_latest_quarter(self) -> None:
        """A threshold left at last quarter's reading would show a stale bar."""
        latest = len(self.staging["periods"]) - 1
        by_metric = {
            "集团 cc 增速": self.staging["group_revenue"]["cc_pct"][latest],
            "皮具 cc 增速": self.staging["by_sector"]["leather_goods_saddlery"]["cc_pct"][latest],
            "亚太 cc 增速": self.staging["by_region"]["asia_pacific_ex_japan"]["cc_pct"][latest],
            "美洲 cc 增速": self.staging["by_region"]["americas"]["cc_pct"][latest],
            "中东 cc 增速": self.staging["by_region"]["other_middle_east"]["cc_pct"][latest],
            "香水 cc 增速": self.staging["by_sector"]["perfume_beauty"]["cc_pct"][latest],
        }
        entries = {entry["metric"]: entry for entry in self.staging["next_kpi"]["quantified"]}
        self.assertEqual(set(by_metric) | {"皮具增量占比"}, set(entries))
        for metric, expected in by_metric.items():
            self.assertEqual(entries[metric]["current"], expected, metric)
        increments, total = rms.cc_increments(self.staging["by_sector"], rms.SECTOR_ORDER, latest)
        self.assertAlmostEqual(entries["皮具增量占比"]["current"],
                               increments["leather_goods_saddlery"] / total * 100, places=1)

    def test_every_threshold_can_be_settled_by_a_revenue_only_release(self) -> None:
        """The next release has no income statement, so a profit threshold there
        would be one nobody could check until February."""
        for entry in self.staging["next_kpi"]["quantified"]:
            self.assertEqual(entry["unit"], "pct", entry["metric"])
            self.assertTrue(
                any(word in entry["metric"] for word in ("增速", "增量")),
                entry["metric"])
            # These names are also the x labels of the headroom chart. Measured
            # in a browser, anything much longer overlaps its neighbour on that
            # axis, and no gate in this repo looks at a text bounding box.
            self.assertLessEqual(len(entry["metric"]), 9, entry["metric"])
        self.assertGreaterEqual(len(self.staging["next_kpi"]["full_year_only"]), 4)

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
        quarterly = next(table for table in self.payload["tables"] if "近八季分板块" in table["title"])
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
        self.assertEqual(len(quasi["rows"]), 6)

    # ── the shapes the renderer reads ───────────────────────────────────────
    def test_the_page_carries_the_cross_page_capex_table(self) -> None:
        titles = [table["title"] for table in self.payload["tables"]]
        self.assertTrue(any("AI capex" in title for title in titles), titles)

    def test_exhibits_are_numbered_in_render_order_and_refs_resolve(self) -> None:
        numbers = [ex["n"] for ex in self.exhibits]
        self.assertEqual(numbers, list(range(2, 2 + len(numbers))))
        text = json.dumps(self.payload, ensure_ascii=False)
        self.assertNotRegex(text, r"\{EX_[A-Z_]+\}")

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
        self.assertEqual(kinds, {"lines", "diverging_bars", "grouped_bars", "bridge_bar"})

    def test_the_published_payload_matches_a_fresh_build(self) -> None:
        published = js_payload(ROOT / "data" / "rms.js", "window.DASH")
        self.assertEqual(published, self.payload)


if __name__ == "__main__":
    unittest.main()
