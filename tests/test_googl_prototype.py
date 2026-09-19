from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import headroom  # noqa: E402
from build.googl import build_payload, parse_number, quarter_key  # noqa: E402


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
        """Each tracking section is one overview bar plus one chart per threshold,
        so its length follows the quarter's thresholds rather than a typed 8."""
        self.assertEqual(
            [(section["id"], len(section["exhibits"])) for section in self.payload["sections"]],
            [("settled", 1 + len(self.staging["prior_kpi_settlement"]["quantified"])),
             ("quarter_highlights", 6),
             ("next_quarter", 1 + len(self.staging["next_kpi"]["quantified"])),
             ("routine", 4)],
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

    def test_the_settlement_title_says_what_the_bars_show(self) -> None:
        """「经营类全部安全，被击穿的是现金类」 is printed only while the bars below
        it make it true -- the kinds are read from the stamped settlement."""
        settled = self.by_section["settled"][0]
        entries = {e["metric"]: e for e in self.staging["prior_kpi_settlement"]["quantified"]}
        breached = [label for label, value in zip(settled["xlabels"], settled["values"]) if value < 0]
        operating_safe = all(value >= 0 for label, value in zip(settled["xlabels"], settled["values"])
                             if entries[label]["kind"] == "operating")
        claim = "经营类全部安全，被击穿的是现金类"
        if breached and operating_safe and all(entries[b]["kind"] == "cash" for b in breached):
            self.assertIn(claim, settled["title"])
        else:
            self.assertNotIn(claim, settled["title"])
        if len(breached) == 1:
            self.assertIn(f"唯一被击穿的是 {breached[0]}", settled["note"])
        else:
            self.assertNotIn("唯一被击穿", settled["note"])

    def test_market_expectation_is_labelled_and_unattributed(self) -> None:
        """Consensus is publishable here only as an unattributed, dated figure."""
        text = json.dumps(self.payload, ensure_ascii=False)
        self.assertIn("市场预期", text)
        for broker in ["FactSet", "Bloomberg", "LSEG", "Visible Alpha", "consensus"]:
            self.assertNotIn(broker.lower(), text.lower())
        expectation = self.staging["market_expectation"]
        self.assertEqual(expectation["as_of"], self.staging["latest"]["release_date"])
        eps_exhibit = next(ex for ex in self.exhibits if "GAAP EPS" in ex["title"])
        self.assertEqual(eps_exhibit["values"][-1], expectation["operating_eps_mid"])

    def test_backlog_exhibit_keeps_the_net_add_collapse_visible(self) -> None:
        """Backlog comes from the filings, not call colour, and the net-add line
        has to be the first difference of the plotted levels."""
        backlog = next(ex for ex in self.exhibits if ex["kind"] == "bar_line")
        levels = backlog["bar"]["values"]
        full = self.staging["backlog"]["level_usd_bn"]
        self.assertEqual(len(levels), len(full))
        quarters = self.staging["backlog"]["quarters"]
        self.assertEqual(quarters[0], "2019Q4")
        # One quarter per filed RPO disclosure, from the first one to the page's quarter.
        self.assertEqual(quarters[-1], quarter_key(self.staging["latest"]["period"]))
        last_year, last_quarter = int(quarters[-1][:4]), int(quarters[-1][-1])
        self.assertEqual(len(full), (last_year - 2019) * 4 + last_quarter - 3,
                         "the RPO record has no missing quarter")
        # The page used to carry 514.0 for 2026Q2 with a note saying no 10-Q
        # existed yet; the level is the Google Cloud line of the quarter's 10-Q.
        self.assertEqual(levels[-1], self.staging["_checks"]["cloud_backlog_usd_bn"])
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
        period = self.staging["latest"]["period"]
        self.assertIn(f"{period} Alphabet earnings call webcast", labels)
        self.assertIn(f"{period} SEC Exhibit 99.1", labels)

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
        # The note belongs to the quarter whose year-on-year base it corrects, so
        # it is stamped; while it is there it has to name both figures.
        if self.staging.get("local_note_errata"):
            self.assertTrue(any("66,728" in note and "73,552" in note for note in self.payload["notes"]))


STAMPED = ("prior_kpi_settlement", "next_kpi", "market_expectation", "snapshot",
           "quarter_story", "local_note_errata")


def published_text(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


class GooglChecksTest(unittest.TestCase):
    """The page's quarter against a record keyed separately from the filing.

    `_checks` is typed once per quarter from the earnings release itself (and,
    for backlog, the quarter's 10-Q), with the place in the document each figure
    was read from. It is not copied out of the arrays, and the builder never
    reads it (`test_data_only_roll`). Every assertion here compares what the
    builder computed from the series with that separate reading, so a roll that
    misaligns a column, drops the new quarter or keeps last quarter's figure
    fails here. Rolling a quarter re-keys `_checks`; this class does not change.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads((ROOT / "series" / "googl.json").read_text(encoding="utf-8"))
        cls.checks = cls.staging["_checks"]
        cls.payload = build_payload(cls.staging)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]

    def test_the_page_names_the_checked_quarter(self) -> None:
        self.assertIn(self.checks["period"], self.payload["title"])
        self.assertIn(f"截至 {self.checks['period_end']}", self.payload["subtitle"])
        self.assertIn(f"发布 {self.checks['release_date']}", self.payload["subtitle"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        c, s = self.checks, self.staging
        q, long, lines = s["quarterly"], s["long_history"], s["revenue_lines_usd_m"]
        seg = s["segment_operating_income_usd_m"]
        self.assertEqual(q["revenue_total"][-1], c["revenue_usd_m"])
        self.assertEqual(q["revenue_total"][-5], c["revenue_year_ago_usd_m"])
        self.assertEqual(long["revenue_usd_m"][-1], c["revenue_usd_m"])
        for key, check in (("google_services", "google_services_usd_m"),
                           ("search_and_other", "search_and_other_usd_m"),
                           ("youtube_ads", "youtube_ads_usd_m"),
                           ("google_network", "google_network_usd_m"),
                           ("google_subscriptions_platforms_devices", "subscriptions_platforms_devices_usd_m"),
                           ("google_cloud", "google_cloud_usd_m"),
                           ("other_bets", "other_bets_usd_m")):
            with self.subTest(line=key):
                self.assertEqual(lines[key][-1], c[check])
        self.assertEqual(lines["google_cloud"][-5], c["google_cloud_year_ago_usd_m"])
        self.assertEqual(seg["oi_total"][-1], c["operating_income_usd_m"])
        for key, check in (("oi_google_services", "google_services"), ("oi_google_cloud", "google_cloud"),
                           ("oi_other_bets", "other_bets"), ("oi_reconciling", "alphabet_level")):
            with self.subTest(segment=key):
                self.assertEqual(seg[key][-1], c["segment_operating_income_usd_m"][check])
        self.assertEqual(q["operating_cash_flow"][-1], c["operating_cash_flow_usd_m"])
        self.assertEqual(q["capital_expenditures"][-1], c["capital_expenditures_usd_m"])
        self.assertEqual(q["depreciation"][-1], c["depreciation_usd_m"])
        self.assertEqual(q["repurchases_of_stock"][-1], c["repurchases_usd_m"])
        for region, value in c["geography_usd_m"].items():
            with self.subTest(region=region):
                self.assertEqual(q["geography_usd_m"][region][-1], value)
        self.assertEqual(s["backlog"]["level_usd_bn"][-1], c["cloud_backlog_usd_bn"])
        # The rows the series does not carry come from the stamped snapshot;
        # their current column is what the release prints.
        rows = {row["label"]: row for row in s["snapshot"]["rows"]}
        for label, check in (("OI&E", "other_income_usd_m"), ("— 权益证券收益", "equity_securities_gain_usd_m"),
                             ("净利润（归属普通股）", "net_income_to_common_usd_m"),
                             ("GAAP 摊薄 EPS", "diluted_eps_usd"),
                             ("股权激励费用", "stock_based_compensation_usd_m"),
                             ("总 TAC", "tac_usd_m"), ("员工人数", "employees"),
                             ("长期债务", "long_term_debt_usd_m")):
            with self.subTest(row=label):
                self.assertEqual(rows[label]["values"][-1], c[check])
        self.assertEqual(rows["EPS（剔权益证券收益，简单自算）"]["less_per_share"][-1],
                         c["equity_gain_diluted_eps_effect_usd"])

    def test_computed_figures_round_to_what_the_release_prints(self) -> None:
        """The page's own arithmetic against the release's printed rounding --
        the place an official figure and a computed one would part."""
        c, s = self.checks, self.staging
        q = s["quarterly"]
        self.assertEqual(round((c["revenue_usd_m"] / c["revenue_year_ago_usd_m"] - 1) * 100),
                         c["revenue_growth_printed_pct"])
        self.assertEqual(round((c["google_cloud_usd_m"] / c["google_cloud_year_ago_usd_m"] - 1) * 100),
                         c["google_cloud_growth_printed_pct"])
        self.assertEqual(round(c["operating_income_usd_m"] / c["revenue_usd_m"] * 100),
                         c["operating_margin_printed_pct"])
        fcf = [o - k for o, k in zip(q["operating_cash_flow"], q["capital_expenditures"])]
        self.assertEqual(fcf[-1], c["free_cash_flow_usd_m"])
        self.assertEqual(sum(fcf[-4:]), c["ttm_free_cash_flow_usd_m"])
        rows = {row["label"]: row for row in s["snapshot"]["rows"]}
        cc = rows["固定汇率收入 YoY"]["values"][-1]
        self.assertEqual(cc, c["constant_currency_growth_printed_pct"])

    def test_the_page_prints_the_checked_figures(self) -> None:
        c = self.checks
        growth = (c["revenue_usd_m"] / c["revenue_year_ago_usd_m"] - 1) * 100
        cloud = (c["google_cloud_usd_m"] / c["google_cloud_year_ago_usd_m"] - 1) * 100
        self.assertIn(f"收入 {growth:+.1f}%、Cloud {cloud:+.1f}%", self.payload["headline"])
        fcf_chart = next(ex for ex in self.exhibits if ex["title"].startswith("单季自由现金流"))
        self.assertIn(f"${c['free_cash_flow_usd_m'] / 1000:,.1f}B", fcf_chart["title"])
        eps = next(ex for ex in self.exhibits if "GAAP EPS" in ex["title"])
        self.assertEqual(eps["values"][0], c["diluted_eps_usd"])
        self.assertEqual(eps["values"][1], c["equity_gain_diluted_eps_effect_usd"])
        snapshot = next(t for t in self.payload["tables"] if t["title"].startswith("关键指标一览"))
        rows = {row[0]: row for row in snapshot["rows"]}
        self.assertEqual(rows["总收入"][3], f"${c['revenue_usd_m']:,}M")
        self.assertEqual(rows["TTM 自由现金流"][3], f"${c['ttm_free_cash_flow_usd_m']:,}M")
        self.assertEqual(rows["Cloud backlog"][3], f"${c['cloud_backlog_usd_bn'] * 1000:,.0f}M")
        self.assertEqual(rows["股票回购"][3], f"${c['repurchases_usd_m']:,}M")
        self.assertEqual(rows["GAAP 摊薄 EPS"][3], f"${c['diluted_eps_usd']:.2f}")
        self.assertEqual(rows["折旧"][3], f"${c['depreciation_usd_m']:,}M")


class GooglRollTest(unittest.TestCase):
    """What a quarter roll can and cannot get past."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "googl.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)

    def test_a_block_stamped_with_another_quarter_stops_the_build(self) -> None:
        for key in STAMPED:
            stale = copy.deepcopy(self.source)
            stale[key]["period"] = "Q1 1999"
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    build_payload(stale)

    def test_a_missing_quarter_block_leaves_its_part_out(self) -> None:
        bare = copy.deepcopy(self.source)
        for key in STAMPED:
            del bare[key]
        payload = build_payload(bare)
        ids = [section["id"] for section in payload["sections"]]
        self.assertEqual(ids, ["quarter_highlights", "routine"])
        text = published_text(payload)
        for gone in ("财报当日股价", "GAAP EPS", "关键指标一览", "市场预期约", "本地分析稿"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, text)

    def test_the_quarter_release_must_be_in_the_sources(self) -> None:
        missing = copy.deepcopy(self.source)
        period = missing["latest"]["period"]
        missing["sources"] = [s for s in missing["sources"] if not s["label"].startswith(period)]
        with self.assertRaisesRegex(ValueError, "sources"):
            build_payload(missing)

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        """Change the one fact each claim rests on; the claim must go with it."""
        before = published_text(self.payload)
        cases = []

        earlier_negative = copy.deepcopy(self.source)
        earlier_negative["long_history"]["capital_expenditures_usd_m"][10] += 100000
        cases.append(("an earlier quarter of negative FCF", earlier_negative,
                      ["四十二季里唯一的一次", "「首次转负」这句话仍然成立"]))

        higher_intensity = copy.deepcopy(self.source)
        higher_intensity["long_history"]["capital_expenditures_usd_m"][20] = 60000
        cases.append(("an earlier capital-intensity peak", higher_intensity,
                      ["且尚未见顶", "当前值是十年区间的顶点"]))

        backlog_peak = copy.deepcopy(self.source)
        backlog_peak["backlog"]["level_usd_bn"][-2] = 600.0
        cases.append(("an earlier backlog high", backlog_peak, ["backlog 创 $514B 新高", "backlog 新高"]))

        one_zero = copy.deepcopy(self.source)
        one_zero["quarterly"]["repurchases_of_stock"][-2] = 5000
        cases.append(("buybacks resumed last quarter", one_zero, ["回购连续两季归零"]))

        cut = copy.deepcopy(self.source)
        guide = cut["capex_guidance_history"]
        guide["calls"][-1] = "Q2 2026 电话会"
        guide["low_usd_bn"][-1], guide["high_usd_bn"][-1] = 170, 180
        cases.append(("a guidance cut", cut, ["半年内两次上调", "次上调，中点从", "抬到"]))

        search_once = copy.deepcopy(self.source)
        lines = search_once["revenue_lines_usd_m"]
        at = lines["quarters"].index("2022Q4")
        lines["search_and_other"][at] = lines["search_and_other"][at - 4] * 1.01
        cases.append(("Search negative only once", search_once, ["跌破过零两次", "Search 两次"]))

        all_safe = copy.deepcopy(self.source)
        for entry in all_safe["next_kpi"]["quantified"]:
            if entry["metric"].startswith("Q3 CapEx"):
                entry["current"] = entry["threshold"] + 1000
        cases.append(("every next-quarter line safe", all_safe, ["是唯一需要往上走的一条"]))

        operating_break = copy.deepcopy(self.source)
        for entry in operating_break["prior_kpi_settlement"]["quantified"]:
            if entry["metric"] == "Cloud 收入 YoY":
                entry["actual"] = entry["threshold"] - 1
        cases.append(("an operating line broke too", operating_break,
                      ["经营类全部安全，被击穿的是现金类", "唯一被击穿的是"]))

        for name, series, claims in cases:
            after = published_text(build_payload(series))
            for claim in claims:
                with self.subTest(case=name, claim=claim):
                    self.assertIn(claim, before)
                    self.assertNotIn(claim, after)

    def test_the_threshold_charts_only_say_never_crossed_when_it_was_not(self) -> None:
        """「八季里它一次都没被穿过」 was printed under every threshold chart,
        including a TTM line whose current quarter had just crossed it."""
        for section in self.payload["sections"]:
            if section["id"] not in ("settled", "next_quarter"):
                continue
            for exhibit in section["exhibits"][1:]:
                actual, line = exhibit["series"][0]["values"], exhibit["series"][1]["values"]
                safe_above = "上方" in exhibit["series"][1]["name"]
                reported = [v for v in actual if v is not None]
                unsafe = [v for v in reported if (v < line[0] if safe_above else v > line[0])]
                recent = [v for v in reported[-8:] if (v < line[0] if safe_above else v > line[0])]
                with self.subTest(chart=exhibit["title"][:30]):
                    if not unsafe:
                        self.assertIn("没有一个落在阈值的不安全一侧", exhibit["note"])
                    elif recent:
                        self.assertIn(f"最近八季里就有 {len(recent)} 季落在不安全一侧", exhibit["note"])
                    else:
                        self.assertIn("八季里它一次都没被穿过", exhibit["note"])


if __name__ == "__main__":
    unittest.main()
