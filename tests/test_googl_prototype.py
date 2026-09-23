from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import headroom  # noqa: E402
from build.googl import SECTIONS, build_payload, parse_number, quarter_key  # noqa: E402


# Records with one reading and no history to draw: they are settled in the
# overview and the audit table only.
POINT_READINGS = {"net_cash", "atm_sold", "tax_rate_ex_gains"}


def independent_readings(staging: dict) -> dict:
    """This quarter's value of every record a threshold can read, computed here
    from the series by the test's own arithmetic -- never through build/googl.py,
    whose readings are what is being checked."""
    lines = staging["revenue_lines_usd_m"]
    seg = staging["segment_operating_income_usd_m"]
    long = staging["long_history"]
    levels = staging["backlog"]["level_usd_bn"]
    balance = staging["balance_sheet_usd_m"]
    rows = {row.get("key", row["label"]): row for row in staging["snapshot"]["rows"]}

    def growth(values: list, lag: int) -> float:
        return (values[-1] / values[-1 - lag] - 1) * 100

    def now(key: str) -> float:
        return rows[key]["values"][-1]

    fcf = [o - c for o, c in zip(long["operating_cash_flow_usd_m"], long["capital_expenditures_usd_m"])]
    return {
        "cloud_yoy": growth(lines["google_cloud"], 4),
        "cloud_opm": seg["oi_google_cloud"][-1] / lines["google_cloud"][-1] * 100,
        "search_yoy": growth(lines["search_and_other"], 4),
        "network_yoy": growth(lines["google_network"], 4),
        "backlog_qoq": growth(levels, 1),
        "backlog_net_add": levels[-1] - levels[-2],
        "capex_quarter": long["capital_expenditures_usd_m"][-1],
        "ttm_fcf": sum(fcf[-4:]),
        "dep_yoy": growth(long["depreciation_usd_m"], 4),
        "net_cash": balance["cash_and_marketable_securities"][-1] - balance["long_term_debt"][-1],
        "atm_sold": now("atm_sold"),
        "tax_rate_ex_gains": ((now("income_tax") - now("equity_gain_tax_effect"))
                              / (now("pretax_income") - now("equity_securities_gain")) * 100),
    }


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

    def test_the_page_has_the_four_sections_every_company_page_has(self) -> None:
        """Owner's rule (2026-09-23, TSM is the reference): exactly four sections,
        in this order, with these ids and these titles verbatim, none empty."""
        self.assertEqual([(s["id"], s["title"]) for s in self.payload["sections"]],
                         [("settled", "一、上季跟踪指标兑现了吗"), ("quarter_highlights", "二、本季重点"),
                          ("next_quarter", "三、下季要跟踪什么"), ("routine", "四、长期常规跟踪")])
        self.assertEqual(list(SECTIONS), [(s["id"], s["title"]) for s in self.payload["sections"]])
        self.assertTrue(all(section["exhibits"] for section in self.payload["sections"]))
        self.assertIn("本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列", self.payload["notes"][0])

    def test_each_tracking_section_is_its_overview_plus_one_chart_per_drawn_record(self) -> None:
        """Section one opens with the follow-up chart and the overview of last
        quarter's lines, section three with the overview of this quarter's; after
        each overview comes one chart per record that has a history to draw (the
        tiers of one record share it). The lengths follow the stamped blocks, not
        a typed 8."""
        for section_id, block, lead in (("settled", "prior_kpi_settlement", 2), ("next_quarter", "next_kpi", 1)):
            entries = self.staging[block]["quantified"]
            drawn = []
            for entry in entries:
                if entry["reads"] not in drawn and entry["reads"] not in POINT_READINGS:
                    drawn.append(entry["reads"])
            with self.subTest(section=section_id):
                self.assertEqual(len(self.by_section[section_id]), lead + len(drawn))
        self.assertEqual(self.by_section["settled"][0]["kind"], "bars_labeled")
        self.assertTrue(self.by_section["settled"][0]["title"].startswith("上季 "))
        for section_id, index, word in (("settled", 1, "上季"), ("next_quarter", 0, "下季")):
            overview = self.by_section[section_id][index]
            self.assertEqual(overview["kind"], "diverging_bars")
            self.assertTrue(overview["title"].startswith(f"{word} ") and "条量化阈值：" in overview["title"])

    def test_headroom_bars_reproduce_the_thresholds(self) -> None:
        """The overview bars are every line with a non-zero threshold, one bar per
        tier, and each bar is the headroom of this quarter's reading -- computed
        here from the series, not through the builder. A line at zero has no
        percentage headroom and stays off the overview."""
        readings = independent_readings(self.staging)
        for section_id, block, index in (("settled", "prior_kpi_settlement", 1), ("next_quarter", "next_kpi", 0)):
            priced = [entry for entry in self.staging[block]["quantified"] if entry["threshold"] != 0]
            exhibit = self.by_section[section_id][index]
            self.assertEqual(exhibit["xlabels"], [f"{entry['metric']}（{entry['tier']}）" for entry in priced])
            self.assertTrue(exhibit["title"].startswith(f"{'上季' if index else '下季'} {len(priced)} 条量化阈值："))
            for entry, plotted in zip(priced, exhibit["values"]):
                expected = headroom(entry["direction"], entry["threshold"], readings[entry["reads"]])
                self.assertAlmostEqual(plotted, round(expected, 1), places=6, msg=entry["id"])

    def test_every_line_the_analysis_drew_is_drawn_on_its_record(self) -> None:
        """One chart per record; on it the record itself and one flat series per
        tier at exactly the analysis's threshold -- a tier silently missing from
        the chart is the regression (the page used to draw one line per row)."""
        readings = independent_readings(self.staging)
        for section_id, block in (("settled", "prior_kpi_settlement"), ("next_quarter", "next_kpi")):
            charts = [ex for ex in self.by_section[section_id] if ex["kind"] == "lines"]
            groups = {}
            for entry in self.staging[block]["quantified"]:
                if entry["reads"] not in POINT_READINGS:
                    groups.setdefault(entry["reads"], []).append(entry)
            self.assertEqual(len(charts), len(groups), section_id)
            for chart, group in zip(charts, groups.values()):
                with self.subTest(section=section_id, record=group[0]["reads"]):
                    self.assertTrue(chart["title"].startswith(group[0]["metric"]), chart["title"])
                    record, *lines = chart["series"]
                    self.assertEqual(len(lines), len(group))
                    for line, entry in zip(lines, group):
                        self.assertEqual(set(line["values"]), {entry["threshold"]})
                        self.assertEqual(len(line["values"]), len(chart["xlabels"]))
                        self.assertIn(entry["tier"], line["name"])
                    self.assertEqual(len(record["values"]), len(chart["xlabels"]))
                    self.assertAlmostEqual(record["values"][-1], readings[group[0]["reads"]], places=6)

    def test_the_settlement_title_says_what_the_bars_show(self) -> None:
        """「经营类全部守住，击穿的是现金类的 …」 is printed only while the bars make
        it true -- the kinds are read from the stamped settlement, the verdicts
        from the bars."""
        overview = self.by_section["settled"][1]
        priced = [e for e in self.staging["prior_kpi_settlement"]["quantified"] if e["threshold"] != 0]
        broken = [e for e, value in zip(priced, overview["values"]) if value < 0]
        operating_safe = all(value >= 0 for e, value in zip(priced, overview["values"]) if e["kind"] == "operating")
        claim = "经营类全部守住，击穿的是现金类的"
        if broken and operating_safe and all(e["kind"] == "cash" for e in broken):
            self.assertIn(claim, overview["title"])
            for e in broken:
                self.assertIn(e["metric"], overview["title"])
        else:
            self.assertNotIn(claim, overview["title"])
        if not broken:
            self.assertTrue(overview["title"].endswith("全部守住"))

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
        # Both analyses' section 8 in full, in original units: one row per line,
        # retired line, condition and gated row -- nothing the analysis wrote is
        # left for the reader to reconstruct.
        prior, following = self.staging["prior_kpi_settlement"], self.staging["next_kpi"]
        self.assertEqual(len(tables[0]["rows"]), len(prior["quantified"]) + len(prior.get("retired", []))
                         + len(prior.get("conditions", [])))
        self.assertEqual(len(tables[1]["rows"]), len(following["quantified"]) + len(following.get("conditions", []))
                         + len(following.get("disclosure_gated", [])))
        for table, block in ((tables[0], prior), (tables[1], following)):
            self.assertEqual({int(row[0]) for row in table["rows"]}, {row["row"] for row in block["rows"]})

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


REQUIRED_STAMPED = ("followup_closure", "prior_kpi_settlement", "next_kpi", "snapshot")
OPTIONAL_STAMPED = ("market_expectation", "quarter_story", "local_note_errata")
STAMPED = REQUIRED_STAMPED + OPTIONAL_STAMPED


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
                             ("总 TAC", "tac_usd_m"), ("员工人数", "employees")):
            with self.subTest(row=label):
                self.assertEqual(rows[label]["values"][-1], c[check])
        # The two balance-sheet lines are a series now (net cash and the buyback
        # condition read them); their last cells are the quarter's balance sheet.
        balance = s["balance_sheet_usd_m"]
        self.assertEqual(balance["long_term_debt"][-1], c["long_term_debt_usd_m"])
        self.assertEqual(balance["cash_and_marketable_securities"][-1], c["cash_and_marketable_securities_usd_m"])
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
        for key in OPTIONAL_STAMPED:
            del bare[key]
        payload = build_payload(bare)
        # The four sections stay: an optional block takes only its own part with it.
        self.assertEqual([(s["id"], s["title"]) for s in payload["sections"]], list(SECTIONS))
        self.assertTrue(all(section["exhibits"] for section in payload["sections"]))
        text = published_text(payload)
        for gone in ("财报当日股价", "GAAP EPS", "市场预期约", "本地分析稿"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, text)
        # The snapshot is required now (thresholds read it), so its table stays.
        self.assertIn("关键指标一览", text)

    def test_a_quarter_without_its_settlement_or_its_section_8_does_not_build(self) -> None:
        """Sections one and three are not optional: the site has analysed Alphabet
        since its first report, so every quarter the page can be rolled to has a
        previous analysis to settle and a section 8 to track."""
        for key in REQUIRED_STAMPED:
            bare = copy.deepcopy(self.source)
            del bare[key]
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "required every quarter"):
                    build_payload(bare)

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

        # The one next-quarter line the reading sits beyond is the Q3 CapEx floor:
        # move this quarter's CapEx above it and the 「唯一」 must go. (Readings
        # are read from the series, so the case edits the series, not the block.)
        all_safe = copy.deepcopy(self.source)
        floor = next(e["threshold"] for e in all_safe["next_kpi"]["quantified"] if e["id"] == "capex_low")
        all_safe["long_history"]["capital_expenditures_usd_m"][-1] = floor + 1000
        cases.append(("every next-quarter line safe", all_safe, ["是唯一在另一侧的一条"]))

        # Cloud growth under the previous analysis's warning line: an operating
        # line broken beside the cash one, so the split claim must go.
        operating_break = copy.deepcopy(self.source)
        lines = operating_break["revenue_lines_usd_m"]
        lines["google_cloud"][-1] = round(lines["google_cloud"][-5] * 1.5)
        cases.append(("an operating line broke too", operating_break, ["经营类全部守住，击穿的是现金类的"]))

        # Backlog growth under the previous warning line: the title must stop saying it held.
        net_add_break = copy.deepcopy(self.source)
        levels = net_add_break["backlog"]["level_usd_bn"]
        levels[-1] = levels[-2] + 10.0
        cases.append(("backlog QoQ under last quarter's warning line", net_add_break, ["守住上季警示线 10.0%"]))

        for name, series, claims in cases:
            after = published_text(build_payload(series))
            for claim in claims:
                with self.subTest(case=name, claim=claim):
                    self.assertIn(claim, before)
                    self.assertNotIn(claim, after)

    def test_the_threshold_charts_only_say_never_crossed_when_it_was_not(self) -> None:
        """「八季里它一次都没被穿过」 was once printed under every threshold chart,
        including a TTM line whose current quarter had just crossed it. Each tier
        on each chart now states its own count, recounted here from the chart's
        own series: never crossed, or crossed N times of which M in the last eight."""
        for section in self.payload["sections"]:
            if section["id"] not in ("settled", "next_quarter"):
                continue
            for exhibit in section["exhibits"]:
                if exhibit["kind"] != "lines":
                    continue
                record, *lines = exhibit["series"]
                reported = [v for v in record["values"] if v is not None]
                self.assertIn(f"这条线自己的记录有 {len(reported)} 个季度", exhibit["note"])
                for line in lines:
                    threshold = line["values"][0]
                    safe_above = "上方" in line["name"]
                    crossed = [v for v in reported if (v < threshold if safe_above else v > threshold)]
                    recent = [v for v in reported[-8:] if (v < threshold if safe_above else v > threshold)]
                    tier = line["name"].split("（安全侧")[0][2:].strip()
                    with self.subTest(chart=exhibit["title"][:30], line=tier):
                        if crossed:
                            self.assertIn(f"{tier} 的不安全一侧有 {len(crossed)} 个（最近八季 {len(recent)} 个）",
                                          exhibit["note"])
                        else:
                            self.assertIn(f"{tier} 一次都没越过", exhibit["note"])

def entry_facts(entry: dict) -> dict:
    """The facts `_checks["note"]` records about one threshold line."""
    facts = {key: entry[key] for key in ("id", "row", "threshold", "direction")}
    if "consecutive" in entry:
        facts["consecutive"] = entry["consecutive"]
    return facts


class SectionsAgainstTheAnalysesTest(unittest.TestCase):
    """Sections one and three against `_checks["note"]`.

    The note is the two local analyses' own facts -- section 0's tally, the
    previous and this quarter's section 8 lines -- typed once per roll from the
    reports, separately from the blocks the builder reads (the builder never
    reads `_checks`). Nothing here names a quarter or a threshold, so a roll
    re-keys the note and leaves this class alone.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads((ROOT / "series" / "googl.json").read_text(encoding="utf-8"))
        cls.note = cls.staging["_checks"]["note"]
        cls.payload = build_payload(cls.staging)
        cls.sections = {section["id"]: section for section in cls.payload["sections"]}

    def test_the_note_names_both_analyses(self) -> None:
        source = self.note["source"]
        self.assertTrue(source["this_quarter"] and source["previous_quarter"])
        self.assertIn(self.staging["latest"]["release_date"], source["this_quarter"])

    def test_the_closure_chart_counts_what_section_0_judged(self) -> None:
        closure = self.note["followup_closure"]
        chart = self.sections["settled"]["exhibits"][0]
        self.assertEqual(chart["kind"], "bars_labeled")
        self.assertEqual(dict(zip(chart["xlabels"], chart["values"])), closure["counts"])
        self.assertEqual(sum(chart["values"]), closure["total"])
        # Every category, in the analysis's order, adds up to the total in front.
        self.assertEqual(chart["title"], f"上季 {closure['total']} 条待验证问题：" + "、".join(
            f"{count} 条{label}" for label, count in closure["counts"].items() if count))
        items = self.staging["followup_closure"]["items"]
        self.assertEqual({str(item["n"]): item["verdict"] for item in items}, closure["by_question"])
        for item in items:
            self.assertIn(f"#{item['n']} ", chart["note"])

    def test_every_line_of_the_previous_section_8_is_settled(self) -> None:
        prior = self.staging["prior_kpi_settlement"]
        got = ([entry_facts(entry) for entry in prior["quantified"]]
               + [{**entry_facts(entry), "retired": True} for entry in prior.get("retired", [])])
        by_id = lambda items: sorted(items, key=lambda item: item["id"])  # noqa: E731
        self.assertEqual(by_id(got), by_id(self.note["prior_thresholds"]))
        rows = [row["row"] for row in prior["rows"]]
        self.assertEqual(rows, list(range(1, self.note["prior_rows"] + 1)))
        # The conditions' verdicts as the page publishes them (the table's last
        # column), whether the builder judged them or carried the analysis's.
        table = self.payload["tables"][0]
        self.assertTrue(table["title"].startswith(f"上季（{prior['set_in']}）本地分析第 8 节 {len(rows)} 行"))
        verdicts = {row[0]: row[-1] for row in table["rows"] if row[3] == "条件"}
        self.assertEqual(verdicts, self.note["prior_conditions"])
        # The one retired line is settled in the table and kept off the overview.
        retired = {entry["id"] for entry in prior.get("retired", [])}
        overview = self.sections["settled"]["exhibits"][1]
        for entry in prior.get("retired", []):
            self.assertNotIn(f"{entry['metric']}（{entry['tier']}）", overview["xlabels"])
        self.assertEqual(len([row for row in table["rows"] if row[-1].startswith("未触发；已退役")]), len(retired))

    def test_every_line_of_this_section_8_is_tracked(self) -> None:
        following = self.staging["next_kpi"]
        self.assertEqual(sorted((entry_facts(entry) for entry in following["quantified"]),
                                key=lambda item: item["id"]),
                         sorted(self.note["next_thresholds"], key=lambda item: item["id"]))
        rows = [row["row"] for row in following["rows"]]
        self.assertEqual(rows, list(range(1, self.note["next_rows"] + 1)))
        self.assertEqual(sorted(item["row"] for item in following["conditions"]), self.note["next_conditions"])
        self.assertEqual(sorted(item["row"] for item in following["disclosure_gated"]), self.note["next_gated"])
        # Nothing the analysis wrote is dropped silently: each condition and each
        # gated row is named in the section's own description with its reason.
        description = self.sections["next_quarter"]["description"]
        for item in following["conditions"] + following["disclosure_gated"]:
            self.assertIn(f"第 {item['row']} 行", description)
            self.assertIn(item["short"], description)
        for item in following["disclosure_gated"]:
            self.assertIn(item["why"], description)

if __name__ == "__main__":
    unittest.main()
