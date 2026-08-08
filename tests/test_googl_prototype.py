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
        self.assertEqual(len(levels), 8)
        self.assertEqual(levels[-1], 514.0)
        # The first shown net add legitimately reaches one quarter before the
        # window, which is why the series carries nine points and shows eight.
        full = self.staging["backlog"]["level_usd_bn"]
        self.assertEqual(len(full), 9)
        expected = [
            round(current - previous, 6)
            for previous, current in zip(full, full[1:])
        ]
        self.assertEqual(
            [round(v, 6) for v in backlog["line"]["values"]], expected
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

    def test_every_plotted_curve_spans_the_full_window(self) -> None:
        """The point of carrying four extra quarters is that no y/y line starts
        halfway across the axis.  A short series means the backfill regressed."""
        for exhibit in self.exhibits:
            if exhibit["kind"] != "lines":
                continue
            if not exhibit["title"].endswith("%") and "YoY" not in exhibit["title"]:
                continue
            for series in exhibit["series"]:
                if series["name"].endswith("阈值") or "阈值" in series["name"]:
                    continue
                self.assertTrue(
                    all(value is not None for value in series["values"]),
                    f"{exhibit['title']} / {series['name']}",
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
