from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import headroom  # noqa: E402
from build.googl import build_payload, parse_number  # noqa: E402


class GooglePageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads((ROOT / "series" / "googl.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.staging)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]
        cls.by_section = {
            section["id"]: section["exhibits"] for section in cls.payload["sections"]
        }

    def test_long_history_agrees_with_the_reviewed_quarters(self) -> None:
        """The ten-year series and the reviewed twelve must not disagree.

        Alphabet files its cash-flow lines year-to-date only, so every quarter
        but the first is one filed figure minus another; this is the check that
        those subtractions still land on numbers a human already reviewed.
        """
        long = self.staging["long_history"]
        quarterly = self.staging["quarterly"]
        index = {quarter: i for i, quarter in enumerate(long["quarters"])}
        pairs = [
            ("revenue_usd_m", "revenue_total"),
            ("capital_expenditures_usd_m", "capital_expenditures"),
            ("operating_cash_flow_usd_m", "operating_cash_flow"),
            ("depreciation_usd_m", "depreciation"),
        ]
        for long_key, reviewed_key in pairs:
            for period, expected in zip(quarterly["periods"], quarterly[reviewed_key]):
                quarter, year = period.split()
                self.assertEqual(
                    long[long_key][index[f"{year}Q{quarter[1]}"]], expected,
                    f"{long_key} {period}",
                )
        for region, values in quarterly["geography_usd_m"].items():
            for period, expected in zip(quarterly["periods"], values):
                quarter, year = period.split()
                self.assertEqual(
                    long["geography_usd_m"][region][index[f"{year}Q{quarter[1]}"]], expected,
                    f"geography {region} {period}",
                )

    def test_geography_still_sums_to_total_revenue(self) -> None:
        """The four regions are the whole of revenue, in every quarter of the
        long run.  If a region were dropped or double counted when the window
        was pulled back, this is what catches it."""
        long = self.staging["long_history"]
        regions = list(long["geography_usd_m"].values())
        for index, total in enumerate(long["revenue_usd_m"]):
            parts = [region[index] for region in regions]
            if any(part is None for part in parts):
                continue
            # Alphabet's regional split is exact, up to its own hedging line.
            self.assertLess(
                abs(sum(parts) - total) / total, 0.02,
                f"{long['quarters'][index]}: regions {sum(parts)} vs total {total}",
            )

    def test_quarterly_depreciation_is_two_captions_and_stays_two(self) -> None:
        """The chart reaches 2016 by drawing two lines, not by joining them.

        Alphabet's cash-flow statement called this line "depreciation and
        impairment of property and equipment" through 2023Q3 and "depreciation
        of property and equipment" from the FY2023 10-K on.  The two captions
        overlap for three quarters and disagree by hundreds of millions -- that
        gap is office-space impairment.  Splicing them would draw a one-off
        impairment as a step change in depreciation, so the page publishes both
        and lets the overlap show.  This test pins the overlap (the reason) and
        the two-series shape (the consequence); it is not satisfied by a single
        line that happens to be long.
        """
        long = self.staging["long_history"]
        start = long["quarters"].index(long["depreciation_first_reported"])
        self.assertTrue(all(v is None for v in long["depreciation_usd_m"][:start]))
        self.assertTrue(all(v is not None for v in long["depreciation_usd_m"][start:]))

        captions = self.staging["depreciation_two_captions"]
        prior = dict(zip(captions["prior_caption"]["quarters"],
                         captions["prior_caption"]["values"]))
        current = dict(zip(captions["current_caption"]["quarters"],
                           captions["current_caption"]["values"]))
        overlap = sorted(set(prior) & set(current))
        self.assertEqual(overlap, ["2023Q1", "2023Q2", "2023Q3"])
        # Every overlapping quarter disagrees, and always in the same direction:
        # the old caption is the larger one because it carries the impairment.
        for quarter in overlap:
            self.assertGreater(prior[quarter], current[quarter], quarter)
            self.assertGreater(prior[quarter] - current[quarter], 300.0, quarter)

        routine = self.by_section["routine"]
        chart = next(ex for ex in routine if "折旧同比" in ex["title"])
        self.assertEqual(len(chart["xlabels"]), len(long["quarters"]))
        names = [series["name"] for series in chart["series"]]
        self.assertEqual(len(names), 3)
        self.assertTrue(any("旧科目" in name for name in names), names)
        self.assertTrue(any("现科目" in name for name in names), names)
        # Both depreciation curves are holes outside their own caption's record.
        by_name = {series["name"]: series["values"] for series in chart["series"]}
        old_line = next(v for name, v in by_name.items() if "旧科目" in name)
        new_line = next(v for name, v in by_name.items() if "现科目" in name)
        self.assertTrue(any(value is None for value in old_line))
        self.assertTrue(any(value is None for value in new_line))
        # ...and they are never both absent in a quarter the record covers.
        covered = [index for index, quarter in enumerate(long["quarters"])
                   if quarter >= "2016Q1"]
        both_missing = [long["quarters"][index] for index in covered
                        if old_line[index] is None and new_line[index] is None]
        # Five quarters, and the fifth is the interesting one. 2016Q1-Q4 have no
        # year-ago base at all. 2023Q4 is the seam: the old caption stops at
        # 2023Q3 so it has no 2023Q4 numerator, and the new caption starts at
        # 2023Q1 so it has no 2022Q4 denominator. Exactly one quarter falls
        # between the two records -- that hole is the caption change, drawn.
        self.assertEqual(both_missing,
                         ["2016Q1", "2016Q2", "2016Q3", "2016Q4", "2023Q4"])
        self.assertEqual(len([ex for ex in routine if len(ex["xlabels"]) > 8]), 4)

    def test_currency_sign_parsing(self) -> None:
        self.assertEqual(parse_number("-$5,855M"), -5855)
        self.assertEqual(parse_number("($5,855M)"), -5855)
        self.assertEqual(parse_number("$5,855M"), 5855)

    def test_page_is_chart_led(self) -> None:
        """The page replaces a slide deck, so the lead modules are charts.  A
        table creeping back above the charts is the regression to catch."""
        self.assertEqual(self.payload["summary"]["blocks"], [])
        self.assertIsNone(self.payload["guidance"])
        self.assertEqual(
            [ex["n"] for ex in self.exhibits], list(range(2, 2 + len(self.exhibits)))
        )
        for exhibit in self.exhibits:
            self.assertTrue(exhibit.get("kind"), exhibit["n"])
            self.assertTrue(exhibit.get("note"), f"exhibit {exhibit['n']} has no explanation")

    def test_section_order_matches_how_the_note_is_used(self) -> None:
        self.assertEqual(
            [(section["id"], len(section["exhibits"])) for section in self.payload["sections"]],
            [("settled", 8), ("quarter_highlights", 6), ("next_quarter", 8), ("routine", 4)],
        )

    def test_headroom_bars_reproduce_the_thresholds(self) -> None:
        """Each tracking section opens with one normalised overview bar, so the
        mapping back to the source thresholds has to be exact."""
        for section_id, block, value_key in [
            ("settled", "prior_kpi_settlement", "actual"),
            ("next_quarter", "next_kpi", "current"),
        ]:
            entries = self.staging[block]["quantified"]
            exhibit = self.by_section[section_id][0]
            self.assertEqual(exhibit["kind"], "diverging_bars")
            self.assertEqual(exhibit["xlabels"], [entry["metric"] for entry in entries])
            for entry, plotted in zip(entries, exhibit["values"]):
                expected = headroom(entry["direction"], entry["threshold"], entry[value_key])
                self.assertAlmostEqual(plotted, round(expected, 1), places=6, msg=entry["metric"])

    def test_every_tracked_metric_with_a_history_gets_its_own_chart(self) -> None:
        """The overview bar says which line broke; only a per-metric chart says
        how it got there.  A metric silently dropping out of the section is the
        regression this catches."""
        for section_id, block in [
            ("settled", "prior_kpi_settlement"),
            ("next_quarter", "next_kpi"),
        ]:
            charted = {
                exhibit["title"].split("：")[0]
                for exhibit in self.by_section[section_id][1:]
            }
            tracked = {entry["metric"] for entry in self.staging[block]["quantified"]}
            self.assertEqual(tracked - charted, set(), section_id)

    def test_threshold_lines_match_the_declared_thresholds(self) -> None:
        for section_id, block, value_key in [
            ("settled", "prior_kpi_settlement", "actual"),
            ("next_quarter", "next_kpi", "current"),
        ]:
            thresholds = {
                entry["metric"]: entry["threshold"]
                for entry in self.staging[block]["quantified"]
            }
            for exhibit in self.by_section[section_id][1:]:
                metric = exhibit["title"].split("：")[0]
                line = exhibit["series"][1]["values"]
                self.assertEqual(len(set(line)), 1, metric)
                self.assertEqual(line[0], thresholds[metric], metric)
                actual = exhibit["series"][0]["values"]
                self.assertEqual(len(actual), len(line), metric)

    def test_only_the_cash_line_broke_last_quarter(self) -> None:
        settled = self.by_section["settled"][0]
        breached = [
            label for label, value in zip(settled["xlabels"], settled["values"]) if value < 0
        ]
        self.assertEqual(breached, ["TTM 自由现金流"])

    def test_market_expectation_is_labelled_and_unattributed(self) -> None:
        """Consensus is publishable here only as an unattributed, dated figure."""
        text = json.dumps(self.payload, ensure_ascii=False)
        self.assertIn("市场预期", text)
        for broker in ["FactSet", "Bloomberg", "LSEG", "Visible Alpha", "consensus"]:
            self.assertNotIn(broker.lower(), text.lower())
        expectation = self.staging["market_expectation"]
        self.assertEqual(expectation["as_of"], "2026-07-22")
        eps_exhibit = next(ex for ex in self.exhibits if "GAAP EPS" in ex["title"])
        self.assertEqual(eps_exhibit["values"][-1], expectation["operating_eps_mid"])

    def test_backlog_exhibit_keeps_the_net_add_collapse_visible(self) -> None:
        """Backlog comes from the filings, not call colour, and the net-add line
        has to be the first difference of the plotted levels."""
        backlog = next(ex for ex in self.exhibits if ex["kind"] == "bar_line")
        levels = backlog["bar"]["values"]
        full = self.staging["backlog"]["level_usd_bn"]
        self.assertEqual(len(levels), len(full))
        self.assertEqual(len(full), 27, "one quarter per filed RPO disclosure")
        self.assertEqual(self.staging["backlog"]["quarters"][0], "2019Q4")
        # 513.9 is the Google Cloud line in the Q2 2026 10-Q (filed 2026-07-23).
        # The page used to carry 514.0 with a note saying no 10-Q existed yet.
        self.assertEqual(levels[-1], 513.9)
        # The first quarter has no previous quarter, so the net-add line starts
        # as a hole rather than as a zero -- a zero there would read as "no
        # growth in 2019Q4", which is a claim the record cannot make.
        expected = [None] + [
            round(current - previous, 6)
            for previous, current in zip(full, full[1:])
        ]
        self.assertEqual(
            [None if v is None else round(v, 6) for v in backlog["line"]["values"]],
            expected,
        )
        self.assertIn("TPU", backlog["src_extra"])

    def test_audit_tables_back_every_derived_exhibit(self) -> None:
        tables = self.payload["tables"]
        first = len(self.exhibits) + 2
        self.assertEqual([table["n"] for table in tables], list(range(first, first + len(tables))))
        cross = next(table for table in tables if "AI capex" in table["title"])
        self.assertEqual(len(cross["rows"]), 8)
        # Thresholds must also be readable in their original units.
        self.assertEqual(
            len(tables[0]["rows"]), len(self.staging["prior_kpi_settlement"]["quantified"])
        )
        self.assertEqual(len(tables[1]["rows"]), len(self.staging["next_kpi"]["quantified"]))

    def test_published_payload_matches_builder(self) -> None:
        text = (ROOT / "data" / "googl.js").read_text(encoding="utf-8")
        body = text.split("window.DASH = ", 1)[1].rsplit(";", 1)[0]
        self.assertEqual(json.loads(body), self.payload)
        labels = {item["label"] for item in self.payload["source_links"]}
        self.assertIn("Q2 2026 Alphabet earnings call webcast", labels)

    def test_public_payload_excludes_restricted_material(self) -> None:
        text = json.dumps(self.payload, ensure_ascii=False).lower()
        for forbidden in [
            "谨慎多", "alphastreet", "yahoo finance", "bofa", "anthropic",
            "stockanalysis.com", "onedrive/",
        ]:
            self.assertNotIn(forbidden, text)
        self.assertNotIn("/users/", text)
        self.assertNotIn("/library/cloudstorage/", text)
        self.assertNotIn("经营口径 eps", text)

    def test_a_curve_may_start_late_but_never_has_a_hole_in_the_middle(self) -> None:
        """The replacement for "every curve spans the whole axis".

        That assertion was right while every chart ran on the same eight
        quarters.  It stops being right the moment the axis is the site's ten
        years, because three of the records on it genuinely begin later: the
        revenue lines in 2018Q4, Cloud's operating margin in 2022Q1, RPO in
        2019Q4.  Requiring a full span would force those to be padded, which is
        the opposite of what the page should do.

        What is still true, and is the thing worth pinning: a series may be
        missing at the *front* and it may be missing at the *back*, but a hole
        in the middle means a quarter was dropped rather than never disclosed.
        """
        for exhibit in self.exhibits:
            if exhibit["kind"] != "lines":
                continue
            for series in exhibit["series"]:
                values = series["values"]
                reported = [index for index, value in enumerate(values)
                            if value is not None]
                self.assertTrue(reported, f"{exhibit['title']} / {series['name']}")
                span = range(reported[0], reported[-1] + 1)
                holes = [index for index in span if values[index] is None]
                self.assertEqual(
                    holes, [],
                    f"{exhibit['title']} / {series['name']}: "
                    f"interior holes at {holes}",
                )

    def test_twelve_quarter_base_backs_every_yoy(self) -> None:
        q = self.staging["quarterly"]
        self.assertEqual(len(q["periods"]), 12)
        for key in ("revenue_total", "search_and_other", "youtube_ads", "cloud",
                    "depreciation", "operating_cash_flow", "capital_expenditures"):
            self.assertEqual(len(q[key]), 12, key)
        for region, values in q["geography_usd_m"].items():
            self.assertEqual(len(values), 12, region)
        table = next(t for t in self.payload["tables"] if "十二季度" in t["title"])
        self.assertEqual(len(table["rows"]), 12)

    def test_trailing_free_cash_flow_reconciles_with_the_quarters(self) -> None:
        """The local note recorded $73,552M as Q2 2025's trailing FCF; recomputing
        from the quarterly cash flows puts that figure at Q3 2025 and Q2 2025 at
        $66,728M. The page must publish the reconciled series."""
        q = self.staging["quarterly"]
        free_cash = [
            operating - capex
            for operating, capex in zip(q["operating_cash_flow"], q["capital_expenditures"])
        ]
        index = q["periods"].index("Q2 2025")
        self.assertEqual(sum(free_cash[index - 3:index + 1]), 66728)
        self.assertEqual(sum(free_cash[index - 2:index + 2]), 73552)
        self.assertTrue(any("66,728" in note and "73,552" in note for note in self.payload["notes"]))


if __name__ == "__main__":
    unittest.main()
