"""Checks for the MA page.

Three things here are worth pinning beyond the usual shape checks.

First, the rebate line. Under the presentation Mastercard adopted in 2023 the
four assessment lines are printed gross in a table and the payment network is
printed net, so the eighteen-quarter series rests on one subtraction. The
10-Q's MD&A states the quarter's rebate in dollars in a sentence and the
release states its growth; the subtraction has to land on both -- asserted
from `_checks`, the separate reading of this quarter's filings.

Second, the three-leg decomposition. Net revenue = gross assessments − rebates
+ value-added services is an identity, not an approximation, and the page says
so on the chart. If it ever stopped closing to the last dollar, the chart would
still draw.

Third, the adjusted operating margin. The page rebuilds Mastercard's own
adjusted operating margin from filed lines (operating income plus the
litigation provision plus the restructuring charge). The company's published
figure is carried in the source for every quarter it is compared on, so that
reconstruction can be checked against them; without that check the page would
be publishing a non-GAAP number of its own invention while calling it the
company's.

A roll edits `series/ma.json` and nothing else. `MaChecksTest` holds the page
to `_checks`; `MaRollTest` rolls the series a quarter back and two forward and
tampers each stamped block; `MaFindingsTest` forces each judgement the page
prints true and then false. What stays pinned by value is history a roll
cannot move: where the disaggregation starts, the Article 8 rows, the quarters
that carry a restructuring charge.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import ma  # noqa: E402
from build.board import cn_count, headroom, unit_text  # noqa: E402
from build.ma import ASSESSMENT_LINES, build_payload, compact_period  # noqa: E402


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


def exhibits_of(payload: dict) -> list[dict]:
    return [ex for section in payload["sections"] for ex in section["exhibits"]]


def own_text(payload: dict) -> str:
    """Everything the page says, less the cross-page table every page carries."""
    own = dict(payload, tables=[t for t in payload["tables"] if "AI capex" not in t["title"]])
    return json.dumps(own, ensure_ascii=False)


def staged() -> dict:
    return json.loads(ma.STAGING_PATH.read_text(encoding="utf-8"))


class MaDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = staged()
        cls.payload = build_payload(cls.source)
        cls.exhibits = exhibits_of(cls.payload)
        cls.by_section = {
            section["id"]: section["exhibits"] for section in cls.payload["sections"]
        }
        cls.by_ref = {ex["ref"]: ex for ex in cls.exhibits if "ref" in ex}
        cls.pn = cls.source["payment_network_usd_m"]
        cls.q = cls.source["quarterly_usd_m"]
        cls.annual = cls.source["annual_usd_m"]
        cls.periods = cls.source["periods"]
        # The page carries two windows. `periods` is the whole record; the
        # revenue disaggregation -- and everything derived from it -- starts
        # where Mastercard first published it.
        cls.dis_from = next(
            index for index, value
            in enumerate(cls.pn["payment_network_net_revenue"]) if value is not None)
        cls.dis_periods = cls.periods[cls.dis_from:]
        cls.gross = [
            sum(cls.pn[line][index] for line in ASSESSMENT_LINES)
            for index in range(cls.dis_from, len(cls.periods))
        ]
        cls.rebates = [
            gross - net
            for gross, net
            in zip(cls.gross, cls.pn["payment_network_net_revenue"][cls.dis_from:])
        ]

    def test_the_record_starts_2016_and_the_split_starts_2022(self) -> None:
        """Two windows, and which series gets which is a disclosure fact.

        Everything on the income statement, the balance sheet, the cash-flow
        statement and the three key drivers runs from 2016Q1. The revenue
        *disaggregation* -- four assessment lines, the payment-network /
        value-added-services split, and the per-line currency-neutral growth
        rates -- exists only from 2022Q1: no 10-Q from 2018Q1 to 2023Q3 and no
        10-K from FY2018 to FY2025 carries those lines in its revenue note, no
        2016-2022 release disaggregates revenue at all, and 2016-2017 has no
        revenue note (ASC 606 was adopted modified-retrospective on 2018-01-01).
        """
        n = len(self.periods)
        self.assertGreaterEqual(n, 42)
        self.assertEqual(self.periods[0], "Q1 2016")
        self.assertEqual(self.dis_periods[0], "Q1 2022")
        self.assertEqual(self.periods[-1], self.source["latest"]["period"])
        numbers = [int(p[-4:]) * 4 + int(p[1]) - 1 for p in self.periods]
        self.assertEqual(numbers, list(range(numbers[0], numbers[0] + n)))
        # The split is exactly the ten fields named in the series file, and the
        # holes are exactly the quarters before the split -- not a ragged edge.
        for field in self.source["not_backfilled"]["fields"]:
            block, key = field.split(".")
            values = self.source[block][key]
            self.assertEqual(values[:self.dis_from], [None] * self.dis_from, field)
            if block == "payment_network_usd_m":
                # The dollar lines are complete once they start.
                self.assertTrue(all(v is not None for v in values[self.dis_from:]),
                                field)
            else:
                # The currency-neutral rates have their own holes inside the
                # window, pinned by their own test.
                self.assertTrue(any(v is not None for v in values[self.dis_from:]),
                                field)
        # ...and total net revenue, which is not part of the split, is whole.
        self.assertTrue(all(v is not None for v in self.pn["total_net_revenue"]))
        holes = set(self.source["not_backfilled"]["fields"])
        for block in ("payment_network_usd_m", "quarterly_usd_m", "per_share",
                      "balance_sheet_usd_m"):
            for name, values in self.source[block].items():
                if not isinstance(values, list):
                    continue
                self.assertEqual(len(values), n, f"{block}.{name}")
                reported = [v for v in values if v is not None]
                if f"{block}.{name}" not in holes:
                    self.assertEqual(len(reported), n, f"{block}.{name}")
                self.assertTrue(all(math.isfinite(v) for v in reported),
                                f"{block}.{name}")
        # The three key drivers are release metrics and run the whole record.
        for name, values in self.source["key_drivers_local_pct"].items():
            self.assertEqual(len(values), n, name)
            self.assertTrue(all(v is not None for v in values), name)

    def test_gdv_growth_is_the_as_reported_row_in_every_quarter(self) -> None:
        """One row for the whole record, and the other one kept where it can be seen.

        Mastercard prints two worldwide GDV growth rows in this era: the trend
        table's as-reported row, and an "as adjusted for EU Regulation"
        (Article 8) row. Three quarters -- Q4 2016, Q1 2017, Q2 2017 -- carried
        the adjusted row at 9 / 8 / 9 against the reported 5 / 5 / 6, which
        flattened the reported deceleration to 5% out of the line.

        What makes the old state indefensible rather than merely a different
        choice is the boundary: Q3 2016 was equally Article-8 affected -- the
        same filings print 7 as reported and 11 as adjusted -- and the page took
        7. No sourcing rule yields 7, 9, 8, 9.

        The assertions are built so the adjusted row cannot come back quietly:
        the four quarters where the two rows differ are pinned to the reported
        value AND asserted unequal to the adjusted one, which is stored beside
        them. The stored row is checked for existence too, because the note that
        used to sit here claimed a comparison series was stored when none was.
        """
        drivers = self.source["key_drivers_local_pct"]
        periods = self.periods
        adjusted = self.source["gdv_eu_article8_adjusted_pct"]
        self.assertEqual(len(adjusted["quarters"]), len(adjusted["values"]))

        reported = {"Q3 2016": 7.0, "Q4 2016": 5.0, "Q1 2017": 5.0, "Q2 2017": 6.0}
        by_quarter = dict(zip(adjusted["quarters"], adjusted["values"]))
        for label, value in reported.items():
            with self.subTest(period=label):
                self.assertEqual(drivers["gdv"][periods.index(label)], value)
                self.assertNotEqual(
                    drivers["gdv"][periods.index(label)], by_quarter[label],
                    "the drawn series has taken the Article 8 adjusted row again")
        # and where the two rows converge the page is not carrying a third number
        for label in ("Q3 2017", "Q1 2018"):
            with self.subTest(period=label):
                self.assertEqual(drivers["gdv"][periods.index(label)], by_quarter[label])

    def test_regional_gdv_names_its_release_every_quarter(self) -> None:
        """One value per quarter on every row, and each quarter says which
        release's Operating Performance table it was read from."""
        gdv = self.source["gdv_by_region"]
        n = len(self.periods)
        rows = [key for key, values in gdv.items() if isinstance(values, list)]
        self.assertEqual(len(rows), 21)
        for key in rows:
            self.assertEqual(len(gdv[key]), n, key)
            self.assertTrue(all(value is not None for value in gdv[key]), key)
        self.assertEqual(list(gdv["source_by_period"]), self.periods)
        month = {"1": "March 31", "2": "June 30", "3": "September 30", "4": "December 31"}
        for period, text in gdv["source_by_period"].items():
            with self.subTest(period=period):
                self.assertRegex(text, r"acc 0001141391-\d{2}-\d{6}")
                self.assertRegex(text, rf"Months Ended {month[period[1]]}, {period[-4:]}」")
                self.assertIn("All Mastercard Credit, Charge and Debit Programs", text)

    def test_the_regions_add_up_to_worldwide(self) -> None:
        """Seven rows, rounded to the billion one by one: five regions sum to
        Worldwide, and Worldwide less United States plus United States is
        Worldwide, within rounding."""
        gdv = self.source["gdv_by_region"]
        regions = ("apmea", "canada", "europe", "latin_america", "united_states")
        for i, period in enumerate(self.periods):
            world = gdv["worldwide_usd_b"][i]
            with self.subTest(period=period):
                self.assertLessEqual(abs(sum(gdv[f"{r}_usd_b"][i] for r in regions) - world), 2)
                self.assertLessEqual(abs(gdv["worldwide_less_us_usd_b"][i] + gdv["united_states_usd_b"][i] - world), 1)
                self.assertLessEqual(abs(sum(gdv[f"{r}_usd_b"][i] for r in regions[:-1])
                                         - gdv["worldwide_less_us_usd_b"][i]), 2)
                # the US has no currency to translate
                self.assertEqual(gdv["united_states_growth_usd_pct"][i], gdv["united_states_growth_local_pct"][i])

    def test_worldwide_growth_agrees_with_the_key_drivers_row(self) -> None:
        """Two documents, two precisions: the release table prints Worldwide GDV
        growth to a tenth, the 10-Q (and the release's Key Business Drivers)
        to a whole percent. They must agree to within the rounding. This is
        what caught the 2022Q3 cell typed as 12% where both print 11%."""
        table = self.source["gdv_by_region"]["worldwide_growth_local_pct"]
        drivers = self.source["key_drivers_local_pct"]["gdv"]
        for period, precise, whole in zip(self.periods, table, drivers):
            with self.subTest(period=period):
                self.assertLessEqual(abs(precise - whole), 0.5)
        self.assertEqual(drivers[self.periods.index("Q3 2022")], 11)

    def test_the_regional_chart_draws_the_series(self) -> None:
        gdv = self.source["gdv_by_region"]
        chart = self.by_ref["EX_GDV_REGION"]
        self.assertEqual(chart["kind"], "stacked_dual")
        self.assertEqual(chart["xlabels"], [compact_period(p) for p in self.periods])
        drawn = {stack["name"]: stack["values"] for stack in chart["stacks"]}
        for name, key in (("美国", "united_states"), ("欧洲", "europe"), ("APMEA", "apmea"),
                          ("拉美", "latin_america"), ("加拿大", "canada")):
            self.assertEqual(drawn[name], gdv[f"{key}_usd_b"], name)
        share = [e / w * 100 for e, w in zip(gdv["europe_usd_b"], gdv["worldwide_usd_b"])]
        for got, want in zip(chart["line"]["values"], share):
            self.assertAlmostEqual(got, want, places=5)
        self.assertLessEqual(max(share), chart["line"]["ymax"])
        self.assertIn(f"欧洲 ${gdv['europe_usd_b'][-1]:,}B 占 {share[-1]:.1f}%", chart["title"])
        self.assertIn(chart, self.by_section["routine"])

    def test_no_quarter_is_missing_its_diluted_per_share_pair(self) -> None:
        """Q4 2020 and Q4 2021 were empty while the note promised the release.

        Both are printed in the fourth-quarter earnings release income statement,
        side by side with the prior year. Nothing pointed at the hole because the
        per-share block was never asserted complete.
        """
        per_share = self.source["per_share"]
        for name in ("diluted_eps_usd", "diluted_shares_m"):
            missing = [q for q, v in zip(self.periods, per_share[name]) if v is None]
            self.assertEqual(missing, [], f"{name} has holes")

    def test_quarterly_series_reconcile_with_the_full_year(self) -> None:
        """Every fourth quarter is `full year − nine months`, so the four
        quarters of each closed year have to add back to the filed annual."""
        years = self.annual["years"]
        offset = self.periods.index(f"Q1 {years[0]}")
        for name, values in list(self.pn.items()) + list(self.q.items()):
            if name not in self.annual:
                continue
            for position, year in enumerate(years):
                window = values[offset + position * 4:offset + position * 4 + 4]
                if any(value is None for value in window):
                    continue
                self.assertEqual(sum(window), self.annual[name][position],
                                 f"{year} {name}")

    def test_payment_network_and_vas_add_to_reported_net_revenue(self) -> None:
        """Where the split exists it must close on the total that always exists.

        Total net revenue is the income statement's first line and runs the
        whole record; the two halves start at 2022Q1. The identity is asserted
        exactly on the quarters that have both halves, and the quarters that do
        not are pinned as holes rather than skipped silently.
        """
        checked = 0
        for index, period in enumerate(self.periods):
            network = self.pn["payment_network_net_revenue"][index]
            vas = self.pn["value_added_services_net_revenue"][index]
            if network is None or vas is None:
                self.assertIsNone(network, period)
                self.assertIsNone(vas, period)
                self.assertIsNotNone(self.pn["total_net_revenue"][index], period)
                continue
            checked += 1
            self.assertEqual(network + vas, self.pn["total_net_revenue"][index], period)
        self.assertEqual(checked, len(self.dis_periods))

    def test_the_derived_rebate_is_the_series_ratio(self) -> None:
        self.assertEqual(ma.rebate_ratios(self.source),
                         [r / g * 100 for r, g in zip(self.rebates, self.gross)])
        table = next(t for t in self.payload["tables"] if "毛计费、返点与净收入" in t["title"])
        self.assertEqual([row[0] for row in table["rows"]], self.dis_periods)
        self.assertTrue(table["title"].startswith(f"{cn_count(len(self.dis_periods))}季"))

    def test_three_leg_decomposition_closes_to_the_dollar(self) -> None:
        """Gross − rebate + value-added services *is* the net revenue change."""
        chart = self.by_ref["EX_LEGS"]
        gross_leg, rebate_leg, vas_leg = (group["values"] for group in chart["groups"])
        self.assertEqual(len(gross_leg), len(self.dis_periods) - 4)
        for offset in range(len(self.dis_periods) - 4):
            index = self.dis_from + offset + 4
            reported = (
                self.pn["total_net_revenue"][index] - self.pn["total_net_revenue"][index - 4]
            )
            self.assertEqual(
                gross_leg[offset] + rebate_leg[offset] + vas_leg[offset],
                reported,
                self.periods[index],
            )
            # The rebate leg is drawn as the drag it is, not as a raw increase.
            self.assertLess(rebate_leg[offset], 0, self.periods[index])

    def test_adjusted_margin_matches_every_published_quarter(self) -> None:
        crosscheck = self.source["adjusted_margin_crosscheck"]
        for period, published in zip(crosscheck["periods"],
                                     crosscheck["company_published_pct"]):
            index = self.periods.index(period)
            rebuilt = (
                self.q["operating_income"][index]
                + self.q["provision_for_litigation"][index]
                + self.q["restructuring_charge"][index]
            ) / self.pn["total_net_revenue"][index] * 100
            self.assertAlmostEqual(rebuilt, published, delta=0.05, msg=period)
        # Every quarter that carries a restructuring charge has to be one the
        # company's own adjusted margin is checked on; otherwise the
        # reconstruction could drift silently on that quarter alone.
        charged = [
            self.periods[index]
            for index, value in enumerate(self.q["restructuring_charge"]) if value
        ]
        self.assertIn("Q1 2026", charged)
        for period in charged:
            self.assertIn(period, crosscheck["periods"])

    def test_the_page_publishes_no_guidance_record_and_says_why(self) -> None:
        """Mastercard files no forward number, so this page must not grow a
        guidance chart by imitation -- and must say that out loud."""
        self.assertIsNone(self.payload["guidance"])
        self.assertFalse(self.source["guidance_disclosure"]["files_numeric_guidance"])
        self.assertNotIn("range_band", [ex["kind"] for ex in self.exhibits])
        self.assertTrue(
            any("申报文件" in note and "指引" in note for note in self.payload["notes"]),
            "the sourcing limit has to be stated on the page, not only in the source",
        )
        wording = self.source["call_guidance"]["wording"]
        table = next(t for t in self.payload["tables"] if "前瞻指引" in t["title"])
        self.assertEqual(table["rows"], [list(row) for row in wording])

    def test_the_count_of_other_guided_pages_is_not_typed(self) -> None:
        """「本站其他六家公司」 went stale as pages were added; the note names the
        category instead of a count nobody recomputes."""
        text = " ".join(self.payload["notes"])
        self.assertNotRegex(text, r"其他[一二三四五六七八九十\d]+家公司")

    def test_currency_neutral_gaps_are_exactly_the_unpublished_quarters(self) -> None:
        """The company publishes each assessment line's currency-neutral growth
        only for the quarter just reported, and 2022 predates the presentation,
        so the holes are the four 2022 quarters plus every fourth quarter."""
        expected = {
            index for index, period in enumerate(self.periods)
            if index < self.dis_from or period.endswith("2022")
            or (index > self.dis_from + 4 and period.startswith("Q4"))
        }
        for name, values in self.source["assessment_currency_neutral_growth_pct"].items():
            self.assertEqual(
                {index for index, value in enumerate(values) if value is None},
                expected,
                name,
            )
        spread = next(ex for ex in self.exhibits if ex.get("ref") == "EX_SPREAD")
        for series in spread["series"]:
            self.assertEqual(len(series["values"]), len(self.periods))
            self.assertEqual(
                {index for index, value in enumerate(series["values"]) if value is None},
                expected,
                series["name"],
            )
        note = next(n for n in self.payload["notes"] if "固定汇率价差图" in n)
        gaps = [p for i, p in enumerate(self.periods) if i in expected and p.startswith("Q4")
                and int(p[-4:]) >= 2023]
        self.assertIn(f"2023 年起的 {len(gaps)} 个第四季是缺口", note)

    def test_repurchase_price_is_the_two_filed_numbers_divided(self) -> None:
        per_share = self.source["per_share"]
        prices = ma.repurchase_prices(self.source)
        for index, period in enumerate(self.periods):
            count = per_share["shares_repurchased_m"][index]
            if count:
                self.assertAlmostEqual(prices[index], self.q["stock_repurchases"][index] / count,
                                       places=9, msg=period)
            else:
                self.assertIsNone(prices[index], period)
        entry = next(e for e in ma.kpi_entries(self.source["next_kpi"], "current", self.source)
                     if e.get("reads") == "repurchase_price")
        self.assertEqual(entry["current"], prices[-1])

    def test_no_threshold_block_types_the_value_it_can_read(self) -> None:
        """The typed 499.8 put the price bar at −10.7% where 4,898 ÷ 9.8 gives −10.8%."""
        for block, key in (("prior_kpi_settlement", "actual"), ("next_kpi", "current")):
            for entry in self.source[block]["quantified"]:
                with self.subTest(metric=entry["metric"]):
                    if "reads" in entry:
                        self.assertNotIn(key, entry)
                    else:
                        self.assertTrue(entry.get("source"), "typed without a source")

    def test_headroom_bars_agree_with_the_thresholds_they_draw(self) -> None:
        pairs = [
            (self.by_section["settled"][1], "prior_kpi_settlement", "actual"),
            (self.by_section["next_quarter"][0], "next_kpi", "current"),
        ]
        for exhibit, block, key in pairs:
            entries = ma.kpi_entries(self.source[block], key, self.source)
            self.assertEqual(exhibit["kind"], "diverging_bars")
            self.assertEqual(exhibit["xlabels"], [entry["metric"] for entry in entries])
            for value, entry in zip(exhibit["values"], entries):
                self.assertAlmostEqual(
                    value,
                    round(headroom(entry["direction"], entry["threshold"], entry[key]), 1),
                    places=6,
                    msg=entry["metric"],
                )

    def test_exhibit_numbers_follow_render_order(self) -> None:
        self.assertEqual([ex["n"] for ex in self.exhibits],
                         list(range(2, 2 + len(self.exhibits))))
        numbers = [table["n"] for table in self.payload["tables"]]
        self.assertEqual(numbers[0], len(self.exhibits) + 2)
        self.assertEqual(numbers, list(range(numbers[0], numbers[0] + len(numbers))))
        for table in self.payload["tables"]:
            self.assertEqual(set(table), {"n", "title", "headers", "rows"}, table["title"])
            for row in table["rows"]:
                self.assertEqual(len(row), len(table["headers"]), table["title"])

    def test_no_placeholder_or_markup_leaks(self) -> None:
        text = own_text(self.payload)
        self.assertNotRegex(text, r"\{[a-z_]+\}")
        self.assertNotIn("**", text)
        self.assertNotRegex(text, r"US?\$-")
        for field in ("headline", "title", "subtitle", "tracker"):
            self.assertNotIn("<", self.payload[field], field)
        for section in self.payload["sections"]:
            self.assertNotIn("<", section["description"])
        for note in self.payload["notes"]:
            self.assertNotIn("<", note)

    def test_sources_are_official_http_links(self) -> None:
        allowed_hosts = {"investor.mastercard.com", "www.sec.gov"}
        for source in self.payload["source_links"]:
            parsed = urlparse(source["url"])
            self.assertEqual(parsed.scheme, "https")
            self.assertIn(parsed.hostname, allowed_hosts)
        self.assertEqual(urlparse(self.payload["source_url"]).hostname, "www.sec.gov")
        self.assertIn(self.payload["source_url"], self.payload["source"])

    def test_published_payload_and_home_card(self) -> None:
        self.assertEqual(js_payload(ROOT / "data" / "ma.js", "window.DASH"), self.payload)
        roster = js_payload(ROOT / "data" / "roster.js", "window.ROSTER")
        item = next(entry for entry in roster["items"] if entry["slug"] == "ma")
        self.assertEqual(item["group"], "payment_networks")
        self.assertIn(item["group"], {group["key"] for group in roster["groups"]})
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="ma/"', home)
        self.assertIn(item["latest_label"], home)
        self.assertIn(item["release_date"], home)
        self.assertIn(f'{len(roster["items"])} 家公司', home)
        self.assertEqual(home.count('class="hcard"'), len(roster["items"]))

    def test_the_shell_links_the_payload_by_content_hash(self) -> None:
        shell = (ROOT / "ma" / "index.html").read_text(encoding="utf-8")
        self.assertIn("<title>MA Quarterly Results</title>", shell)
        sources = re.findall(r'<script src="\.\./([^"?]+)(?:\?v=([0-9a-f]+))?"', shell)
        self.assertEqual(
            [name for name, _ in sources],
            ["data/roster.js", "data/ma.js", "assets/charts.js", "assets/page.js"],
        )
        for name, digest in sources:
            with self.subTest(script=name):
                self.assertTrue(digest, f"{name} is served without a cache-busting version")
                expected = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()[: len(digest)]
                self.assertEqual(digest, expected, f"{name} carries a stale digest")

    def test_labels_are_calendar_quarters(self) -> None:
        """Mastercard's fiscal year is the calendar year, so its quarters are the
        same three months as every other page's -- worth pinning, because the
        cross-company capex table would compare different periods otherwise."""
        latest = self.payload["latest"]
        self.assertEqual(latest["disclosed_period_label"], self.periods[-1])
        self.assertEqual(latest["full_financial_period_label"], self.periods[-1])
        month = {"1": "03-31", "2": "06-30", "3": "09-30", "4": "12-31"}[self.periods[-1][1]]
        self.assertEqual(latest["period_end"], f"{self.periods[-1][-4:]}-{month}")
        self.assertEqual(compact_period("Q2 2026"), "Q2'26")
        metrics = [entry["metric"] for entry in
                   self.source["prior_kpi_settlement"]["quantified"]
                   + self.source["next_kpi"]["quantified"]] + self.source["followup_closure"]["labels"]
        for exhibit in self.exhibits:
            for label in exhibit.get("xlabels", []):
                if re.fullmatch(r"Q[1-4]'\d{2}", label) or "阈值" in label:
                    continue
                self.assertIn(label, metrics, exhibit["title"])

    def test_public_files_exclude_private_and_broker_material(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [ROOT / "series" / "ma.json", ROOT / "data" / "ma.js"]
        ).lower()
        for forbidden in ("onedrive", "obsidian", "/users/", "seeking alpha",
                          "price target", "forward p/e", "stockanalysis.com"):
            self.assertNotIn(forbidden, text, forbidden)


# ── rolling the series, the way a quarter's roll does ────────────────────────
QUARTER_END = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}
RELEASE_DAY = {1: "04-30", 2: "07-30", 3: "10-29", 4: "01-28"}
QUARTER_BLOCKS = ("current_snapshot", "market_expectation", "followup_closure",
                  "prior_kpi_settlement", "next_kpi", "call_guidance", "quarter_story")
AXIS_BLOCKS = ("payment_network_usd_m", "assessment_currency_neutral_growth_pct",
               "key_drivers_local_pct", "gdv_by_region", "quarterly_usd_m", "per_share",
               "balance_sheet_usd_m")
PLACEHOLDER = r"\{[a-z_]+\}"


def axis_lists(s: dict) -> list[tuple[dict, str]]:
    n = len(s["periods"])
    return [(s[block], key) for block in AXIS_BLOCKS for key, values in s[block].items()
            if isinstance(values, list) and len(values) == n]


def rolled_back(staging: dict) -> dict:
    """The series one quarter earlier, on the Q1 2026 figures the file already
    holds: the Q1 2026 release (acc 0001141391-26-000029) and 10-Q (…-000031),
    both filed 2026-04-30. The page went live at Q2 2026, so there are no Q1
    blocks to restore."""
    s = copy.deepcopy(staging)
    for container, key in axis_lists(s):
        container[key] = container[key][:-1]
    s["periods"] = s["periods"][:-1]
    check = s["adjusted_margin_crosscheck"]
    keep = [i for i, p in enumerate(check["periods"]) if p in s["periods"]]
    check["periods"] = [check["periods"][i] for i in keep]
    check["company_published_pct"] = [check["company_published_pct"][i] for i in keep]
    for key in ("_checks",) + QUARTER_BLOCKS:
        s.pop(key, None)
    s["latest"] = {"period": "Q1 2026", "period_end": "2026-03-31", "release_date": "2026-04-30",
                   "analysis_date": "2026-05-01", "audit_status": "unaudited"}
    s["sources"] = [src for src in s["sources"] if not src["label"].startswith("Q2 2026")]
    return s


def rolled_forward(staging: dict) -> dict:
    """One quarter later with made-up figures that keep the page's identities."""
    s = copy.deepcopy(staging)
    last = s["periods"][-1]
    quarter, year = int(last[1]), int(last[-4:])
    quarter, year = (1, year + 1) if quarter == 4 else (quarter + 1, year)
    label = f"Q{quarter} {year}"
    release = f"{year + 1 if quarter == 4 else year}-{RELEASE_DAY[quarter]}"
    for container, key in axis_lists(s):
        values = container[key]
        if container is s["assessment_currency_neutral_growth_pct"]:
            previous = next(v for v in reversed(values) if v is not None)
            values.append(None if quarter == 4 else previous)
        elif values[-1] is None:
            values.append(None)
        elif isinstance(values[-1], int):
            values.append(round(values[-1] * 1.02))
        else:
            values.append(round(values[-1] * 1.02, 4))
    s["periods"].append(label)
    pn, q, bs = s["payment_network_usd_m"], s["quarterly_usd_m"], s["balance_sheet_usd_m"]
    gross = sum(pn[line][-1] for line in ASSESSMENT_LINES)
    pn["payment_network_net_revenue"][-1] = round(gross * 0.47)
    pn["total_net_revenue"][-1] = pn["payment_network_net_revenue"][-1] + pn["value_added_services_net_revenue"][-1]
    q["provision_for_litigation"][-1] = 0
    q["restructuring_charge"][-1] = 0
    q["operating_income"][-1] = round(pn["total_net_revenue"][-1] * 0.6)
    bs["remaining_repurchase_authorization"][-1] = max(
        bs["remaining_repurchase_authorization"][-2] - q["stock_repurchases"][-1], 0)
    for key in ("_checks",) + QUARTER_BLOCKS:
        s.pop(key, None)
    s["latest"] = {"period": label, "period_end": f"{year}-{QUARTER_END[quarter]}",
                   "release_date": release, "analysis_date": release, "audit_status": "unaudited"}
    s["sources"] = ([{"label": f"{label} 业绩发布 8-K EX-99.1",
                      "url": f"https://www.sec.gov/Archives/edgar/data/1141391/next{year}q{quarter}/ex991.htm"}]
                    + [src for src in s["sources"] if "业绩发布 8-K" not in src["label"]])
    return s


class MaChecksTest(unittest.TestCase):
    """The page's quarter against a record keyed separately from the filings.

    `_checks` is typed once per quarter from the earnings 8-K and the 10-Q, with
    the place in each document every figure was read from; the builder never
    reads it (asserted in `test_data_only_roll`). The release prints growth as
    whole percentages, so computed growth is compared at that precision.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.s = staged()
        cls.c = cls.s["_checks"]
        cls.payload = build_payload(cls.s)
        cls.exhibits = exhibits_of(cls.payload)
        cls.periods = cls.s["periods"]

    def growth(self, values: list, back: int = 4) -> float:
        return (values[-1] / values[-1 - back] - 1) * 100

    def test_the_page_names_the_checked_quarter(self) -> None:
        c = self.c
        self.assertIn(f"{c['period']} 季报仪表盘", self.payload["title"])
        self.assertIn(f"截至 {c['period_end']}", self.payload["subtitle"])
        self.assertIn(f"发布 {c['release_date']}", self.payload["subtitle"])
        accession = re.search(r"acc (\d{10})-(\d{2})-(\d{6})", c["source"]).groups()
        self.assertIn("".join(accession), self.payload["source_url"])

    def test_the_regional_gdv_is_the_release_s(self) -> None:
        """The last cell of every regional row is the release's table, typed
        separately into `_checks`, and the page prints those figures."""
        c, gdv = self.c["gdv_by_region"], self.s["gdv_by_region"]
        for column, suffix in (("usd_b", "usd_b"), ("growth_usd_pct", "growth_usd_pct"),
                               ("growth_local_pct", "growth_local_pct")):
            for region, value in c[column].items():
                with self.subTest(region=region, column=column):
                    self.assertEqual(gdv[f"{region}_{suffix}"][-1], value)
        accession = re.search(r"acc (\d{10}-\d{2}-\d{6})", c["source"]).group(1)
        self.assertIn(f"acc {accession}", gdv["source_by_period"][self.c["period"]])
        chart = next(ex for ex in self.exhibits if ex["title"].startswith("分地区 GDV"))
        usd = c["usd_b"]
        self.assertIn(f"本季 ${usd['worldwide']:,}B，欧洲 ${usd['europe']:,}B "
                      f"占 {usd['europe'] / usd['worldwide'] * 100:.1f}%", chart["title"])
        self.assertIn(f"美国的 ${usd['united_states']:,}B", chart["title"])
        for name, region in (("拉美", "latin_america"), ("欧洲", "europe"), ("美国", "united_states")):
            self.assertIn(f"{name} {c['growth_local_pct'][region]:+.1f}%", chart["note"])
        self.assertIn(f"美元口径 {c['growth_usd_pct']['europe']:+.1f}%", chart["note"])
        self.assertEqual(round(c["growth_local_pct"]["worldwide"]), self.c["key_drivers_pct"]["gdv"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        c, s = self.c, self.s
        pn, q, ps, bs = (s["payment_network_usd_m"], s["quarterly_usd_m"], s["per_share"],
                         s["balance_sheet_usd_m"])
        for got, want, name in (
                (pn["total_net_revenue"][-1], c["net_revenue_usd_m"], "net revenue"),
                (q["operating_expenses"][-1], c["operating_expenses_usd_m"], "opex"),
                (q["provision_for_litigation"][-1], c["provision_for_litigation_usd_m"], "litigation"),
                (q["operating_income"][-1], c["operating_income_usd_m"], "operating income"),
                (q["net_income"][-1], c["net_income_usd_m"], "net income"),
                (ps["diluted_eps_usd"][-1], c["diluted_eps_usd"], "eps"),
                (ps["diluted_shares_m"][-1], c["diluted_shares_m"], "shares"),
                (ps["shares_repurchased_m"][-1], c["shares_repurchased_m"], "repurchased"),
                (pn["payment_network_net_revenue"][-1], c["payment_network_net_revenue_usd_m"], "network"),
                (pn["value_added_services_net_revenue"][-1], c["value_added_services_net_revenue_usd_m"], "vas"),
                (bs["remaining_repurchase_authorization"][-1], c["remaining_repurchase_authorization_usd_m"],
                 "authorization")):
            with self.subTest(name=name):
                self.assertEqual(got, want)
        for line, value in c["assessments_usd_m"].items():
            self.assertEqual(pn[line][-1], value, line)
            self.assertEqual(pn[line][-5], c["prior_year"]["assessments_usd_m"][line], line)
        for key, value in c["balance_sheet_usd_m"].items():
            self.assertEqual(bs[key][-1], value, key)
        prior = c["prior_year"]
        self.assertEqual(self.periods[-5], prior["period"])
        self.assertEqual(pn["total_net_revenue"][-5], prior["net_revenue_usd_m"])
        self.assertEqual(pn["payment_network_net_revenue"][-5], prior["payment_network_net_revenue_usd_m"])
        self.assertEqual(ps["diluted_eps_usd"][-5], prior["diluted_eps_usd"])
        drivers = s["key_drivers_local_pct"]
        for key, value in c["key_drivers_pct"].items():
            self.assertEqual(drivers[key][-1], value, key)
            self.assertEqual(drivers[key][-5], prior["key_drivers_pct_as_reprinted"][key], key)

    def test_the_rebate_subtraction_is_the_printed_rebate(self) -> None:
        """The 10-Q states $5,997 million in a sentence; the page's subtraction
        lands on it to the dollar, and on the year-to-date $11,636 million."""
        c, s = self.c, self.s
        pn = s["payment_network_usd_m"]
        rebates = [sum(pn[line][i] for line in ASSESSMENT_LINES) - pn["payment_network_net_revenue"][i]
                   for i in range(len(self.periods)) if pn["payment_network_net_revenue"][i] is not None]
        n = int(c["period"][1])
        self.assertEqual(rebates[-1], c["rebates_usd_m"]["quarter"])
        self.assertEqual(sum(rebates[-n:]), c["rebates_usd_m"]["ytd"])
        self.assertEqual(rebates[-5], c["prior_year"]["rebates_usd_m"])
        self.assertEqual(round((rebates[-1] / rebates[-5] - 1) * 100), c["growth_printed_pct"]["rebates"][0])
        self.assertEqual(round((sum(rebates[-n:]) / sum(rebates[-n - 4:-4]) - 1) * 100),
                         c["growth_printed_pct"]["rebates_ytd"][0])
        printed = s["current_snapshot"]["rebates_printed"]
        self.assertEqual(printed, {"quarter_usd_m": c["rebates_usd_m"]["quarter"],
                                   "ytd_usd_m": c["rebates_usd_m"]["ytd"],
                                   "quarter_growth_pct": c["growth_printed_pct"]["rebates"][0],
                                   "ytd_growth_pct": c["growth_printed_pct"]["rebates_ytd"][0]})

    def test_computed_growth_rounds_to_the_printed_growth(self) -> None:
        c, s = self.c, self.s
        pn, q, ps = s["payment_network_usd_m"], s["quarterly_usd_m"], s["per_share"]
        for values, key in ((pn["total_net_revenue"], "net_revenue"),
                            (pn["payment_network_net_revenue"], "payment_network_net_revenue"),
                            (pn["value_added_services_net_revenue"], "value_added_services_net_revenue"),
                            (q["net_income"], "net_income"),
                            (ps["diluted_eps_usd"], "diluted_eps")):
            with self.subTest(key=key):
                self.assertEqual(round(self.growth(values)), c["growth_printed_pct"][key][0])
        for line, (reported, _neutral) in c["assessments_growth_printed_pct"].items():
            self.assertEqual(round(self.growth(pn[line])), reported, line)

    def test_the_year_to_date_cash_flow_is_the_quarters_summed(self) -> None:
        ytd = self.c["cash_flow_ytd_usd_m"]
        n = ytd["months"] // 3
        self.assertEqual(int(self.c["period"][1]), n)
        q = self.s["quarterly_usd_m"]
        for series, key in (("operating_cash_flow", "operating"), ("net_income", "net_income"),
                            ("prepaid_expense_cash_outflow", "prepaid_expenses"),
                            ("amortization_of_customer_incentives", "amortization_of_customer_incentives"),
                            ("purchases_of_property_and_equipment", "purchases_of_property_and_equipment"),
                            ("capitalized_software", "capitalized_software"),
                            ("stock_repurchases", "purchases_of_treasury_stock"),
                            ("dividends_paid", "dividends_paid")):
            with self.subTest(series=series):
                self.assertEqual(sum(q[series][-n:]), abs(ytd[key]))
        for series, key in (("operating_cash_flow", "operating_prior"), ("net_income", "net_income_prior"),
                            ("prepaid_expense_cash_outflow", "prepaid_expenses_prior"),
                            ("amortization_of_customer_incentives", "amortization_of_customer_incentives_prior")):
            self.assertEqual(sum(q[series][-n - 4:-4]), abs(ytd[key]), series)

    def test_the_threshold_readings_match_the_filings(self) -> None:
        """Each current value recomputed from `_checks` -- the quarter's buyback
        is the year-to-date cash column less the year's earlier quarters."""
        c, s = self.c, self.s
        ytd = c["cash_flow_ytd_usd_m"]
        n = ytd["months"] // 3
        q = s["quarterly_usd_m"]
        buyback = abs(ytd["purchases_of_treasury_stock"]) - sum(q["stock_repurchases"][-n:-1])
        expected = {
            "rebate_ratio": c["rebates_usd_m"]["quarter"] / sum(c["assessments_usd_m"].values()) * 100,
            "quarterly_usd_m.stock_repurchases": buyback,
            "repurchase_price": buyback / c["shares_repurchased_m"],
            "ytd_conversion": ytd["operating"] / ytd["net_income"] * 100,
        }
        table = next(t for t in self.payload["tables"] if t["title"].startswith("下季阈值与当前值"))
        rows = {row[0]: row for row in table["rows"]}
        for entry in s["next_kpi"]["quantified"]:
            with self.subTest(metric=entry["metric"]):
                if "reads" not in entry:
                    self.assertEqual(entry["current"], c["growth_printed_pct"]["payment_network_net_revenue"][1])
                    continue
                self.assertIn(entry["reads"], expected, "a new kind of reading needs its figure here")
                value = expected[entry["reads"]]
                self.assertEqual(rows[entry["metric"]][3], unit_text(entry["unit"], value))
                self.assertEqual(rows[entry["metric"]][4],
                                 f"{headroom(entry['direction'], entry['threshold'], value):+.1f}%")
        vas = next(e for e in s["prior_kpi_settlement"]["quantified"] if "增值服务" in e["metric"])
        self.assertEqual(vas["actual"], c["growth_printed_pct"]["value_added_services_net_revenue"][1])

    def test_the_snapshot_and_crosscheck_are_the_release_s(self) -> None:
        c, snap = self.c, self.s["current_snapshot"]
        self.assertEqual(snap["adjusted_diluted_eps_usd"][0], c["adjusted_diluted_eps_usd"])
        self.assertEqual(snap["adjusted_operating_margin_pct"][0], c["adjusted_operating_margin_pct"])
        neutral = snap["currency_neutral_growth_pct"]
        self.assertEqual(neutral["net_revenue"], c["growth_printed_pct"]["net_revenue"][1])
        self.assertEqual(neutral["payment_network"], c["growth_printed_pct"]["payment_network_net_revenue"][1])
        self.assertEqual(neutral["value_added_services"],
                         c["growth_printed_pct"]["value_added_services_net_revenue"][1])
        check = self.s["adjusted_margin_crosscheck"]
        self.assertEqual(check["company_published_pct"][check["periods"].index(c["period"])],
                         c["adjusted_operating_margin_pct"])

    def test_the_page_prints_the_checked_figures(self) -> None:
        c = self.c
        gross = sum(c["assessments_usd_m"].values())
        self.assertIn(f"毛计费 ${gross:,}M", self.payload["headline"])
        self.assertIn(f"返点占毛计费 {c['rebates_usd_m']['quarter'] / gross * 100:.2f}%", self.payload["headline"])
        mix = next(ex for ex in self.exhibits if ex.get("ref") == "EX_MIX")
        self.assertIn(f"增值服务本季 ${c['value_added_services_net_revenue_usd_m']:,}M", mix["note"])
        rebate = next(ex for ex in self.exhibits if ex.get("ref") == "EX_RATIO")
        self.assertIn(f"本季返点 ${c['rebates_usd_m']['quarter']:,}M", rebate["src_extra"])
        self.assertEqual(ma.headline_metrics(self.s)[0], f"Revenue ${c['net_revenue_usd_m'] / 1000:.2f}B")


class MaRollTest(unittest.TestCase):
    """What a roll can change without touching the builder."""

    STORY_ONLY = ("收购按预告在下季交割但连续三季不给单位经济", "而本季真正变化的两件事",
                  "上季那条阈值挂在跨境量里的 travel 一条上", "管理层在电话会上已经预告下季这个比例会环比再升",
                  "10-Q 的增长归因表把这一栏印作", "6 月发债", "尚未交割的收购",
                  "公司口径的前瞻指引", "财报当日股价", "BVNK")

    @classmethod
    def setUpClass(cls) -> None:
        cls.s = staged()
        cls.payload = build_payload(cls.s)
        cls.text = own_text(cls.payload)

    def test_a_block_stamped_for_another_quarter_stops_the_build(self) -> None:
        for key in QUARTER_BLOCKS:
            stale = copy.deepcopy(self.s)
            stale[key]["period"] = "Q1 1999"
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    build_payload(stale)

    def test_the_quarters_own_release_must_be_in_the_sources(self) -> None:
        bare = copy.deepcopy(self.s)
        bare["sources"] = [src for src in bare["sources"] if src["label"] != "Q2 2026 业绩发布 8-K EX-99.1"]
        self.assertLess(len(bare["sources"]), len(self.s["sources"]))
        with self.assertRaisesRegex(ValueError, "sources"):
            build_payload(bare)

    def test_a_printed_rebate_that_is_not_the_subtraction_stops_the_build(self) -> None:
        wrong = copy.deepcopy(self.s)
        wrong["current_snapshot"]["rebates_printed"]["quarter_usd_m"] += 1
        with self.assertRaisesRegex(ValueError, "rebates_printed"):
            build_payload(wrong)

    def test_a_threshold_without_a_reading_or_a_source_stops_the_build(self) -> None:
        bare = copy.deepcopy(self.s)
        entry = bare["next_kpi"]["quantified"][1]
        entry.pop("source")
        with self.assertRaisesRegex(ValueError, "neither"):
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
        sections = {section["id"]: section for section in payload["sections"]}
        self.assertEqual(sections["next_quarter"]["exhibits"], [])
        self.assertIn("本节没有图", sections["next_quarter"]["description"])
        self.assertFalse(any(ex["kind"] == "diverging_bars" and ex["title"].startswith(("上季", "下季"))
                             for ex in exhibits_of(payload)))
        self.assertFalse(any("阈值" in t["title"] for t in payload["tables"]))
        self.assertNotRegex(text, PLACEHOLDER)
        self.assertNotRegex(text, r"Exhibit \d+ 与 Exhibit")
        numbers = [ex["n"] for ex in exhibits_of(payload)]
        self.assertEqual(numbers, list(range(2, 2 + len(numbers))))

    def test_the_quarter_before_builds_from_the_series_alone(self) -> None:
        rolled = rolled_back(self.s)
        payload = build_payload(rolled)
        self.assertEqual(payload["latest"]["disclosed_period_label"], "Q1 2026")
        self.assertIn("Q1 2026 季报仪表盘", payload["title"])
        self.assertIn("000114139126000029/ma03312026-exx991xearnings.htm", payload["source"])
        self.assertIn("与截至 2026-03-31 的 10-Q", payload["source"])
        text = own_text(payload)
        for token in ("Q2 2026", "Q2'26", "2026-07-30", "上半年", "$11,448M", "$4,898M"):
            self.assertNotIn(token, text)
        self.assertIn("一季度经营现金流同比", text)
        self.assertNotRegex(text, PLACEHOLDER)
        self.assertNotRegex(text, r"US?\$-")

    def test_the_quarters_after_build_from_the_series_alone(self) -> None:
        s = self.s
        pages = []
        for _ in range(2):
            s = rolled_forward(s)
            payload = build_payload(s)
            text = own_text(payload)
            pages.append((s, payload, text))
            self.assertIn(f"{s['periods'][-1]} 季报仪表盘", payload["title"])
            self.assertNotRegex(text, PLACEHOLDER)
            self.assertNotRegex(text, r"US?\$-")
            # the made-up quarters land on the edge cases the real one does not
            self.assertNotRegex(text, r"[-−]0\.0+(pp|%)")
            self.assertNotIn("是 没有", text)
            self.assertNotIn('，"', text)
            self.assertNotIn("（此前最高 4.4x）", text)
        (q3, p3, t3), (q4, p4, t4) = pages
        self.assertIn("前三季度经营现金流同比", t3)
        debt = [a + b for a, b in zip(q3["balance_sheet_usd_m"]["short_term_debt"],
                                      q3["balance_sheet_usd_m"]["long_term_debt"])]
        since = debt[-1] - debt[q3["periods"].index("Q4 2025")]
        self.assertIn(f"缺口由年初以来净增的 ${since:,}M 债务", t3)
        self.assertIn("全年经营现金流同比", t4)
        self.assertIn(f"{len(q4['periods'])} 季现金流、回购与资本结构", t4)
        self.assertIn(f"摊薄股数 {len(q4['periods'])} 季从", t4)
        # a fourth quarter has no line-level currency-neutral growth
        spread = next(ex for ex in exhibits_of(p4) if ex.get("ref") == "EX_SPREAD")
        self.assertEqual(spread["title"], "固定汇率的价差：本季没有各条计费线的固定汇率季度增速")


class MaFindingsTest(unittest.TestCase):
    """Every judgement on the page says what the series says, both ways."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.s = staged()
        cls.clean = own_text(build_payload(copy.deepcopy(cls.s)))

    def page(self, *edits) -> str:
        s = copy.deepcopy(self.s)
        for edit in edits:
            edit(s)
        return own_text(build_payload(s))

    def at(self, s: dict, label: str) -> int:
        return s["periods"].index(label)

    def test_the_headline_compares_billing_growth_with_a_year_ago(self) -> None:
        """「账单在加速」: gross billings grew +16.0% after +17.5% the quarter before.
        They did grow faster than a year earlier (+14.8%)."""
        self.assertNotIn("账单在加速", self.clean)
        self.assertIn("账单比一年前涨得快，留下的钱没有：毛计费 $11,448M、同比 +16.0%（一年前 +14.8%）", self.clean)
        self.assertIn("毛计费的年增量从 Q1'23 起涨了 67%", self.clean)
        self.assertNotIn("从 Q1'17 起", self.clean)

        def slower(s):
            pn = s["payment_network_usd_m"]
            pn["domestic_assessments"][-1] -= 700
            pn["payment_network_net_revenue"][-1] -= 700
            pn["total_net_revenue"][-1] -= 700

        self.assertNotIn("账单比一年前涨得快", self.page(slower))

    def test_the_settled_title_counts_the_held_thresholds(self) -> None:
        self.assertIn("上季 4 条可结算阈值全部守住", self.clean)

        def vas_missed(s):
            s["prior_kpi_settlement"]["quantified"][2]["actual"] = 15.0

        missed = self.page(vas_missed)
        self.assertIn("上季 4 条可结算阈值里 3 条守住", missed)
        self.assertIn("三条守住、一条越线", missed)

    def test_the_cash_flow_sentence_names_what_the_thresholds_missed(self) -> None:
        """「没有一条指向现金流量表」 beside a settled buyback threshold, which is a
        cash-flow statement line."""
        self.assertNotIn("没有一条指向现金流量表", self.clean)
        self.assertIn("<b>上季五条阈值没有一条看经营现金流</b>", self.clean)

    def test_the_unsettled_thresholds_are_printed_not_referenced(self) -> None:
        """「另有两条已退役：全年收入……（见下段）」 pointed at no paragraph."""
        self.assertNotIn("见下段", self.clean)
        self.assertIn("另有两条不结算：全年净收入固定汇率增速", self.clean)
        self.assertIn("剩余授权从上季末的 $13.4B 降到本季末的 $8.5B", self.clean)
        self.assertIn("回购隐含均价从上季的 $517 降到 $500", self.clean)

    def test_the_buyback_record_is_measured_on_the_whole_axis(self) -> None:
        """「创十八季新高」 on a 42-quarter chart."""
        self.assertIn("本季 $4,898M 创 42 季新高", self.clean)
        self.assertNotIn("十八季新高", self.clean)

        def bigger_before(s):
            s["quarterly_usd_m"]["stock_repurchases"][self.at(s, "Q2 2022")] = 6000

        forced = self.page(bigger_before)
        self.assertNotIn("季新高", forced)
        self.assertNotIn("创纪录的回购", forced)
        self.assertNotIn("本季买得最多", forced)

    def test_the_drivers_title_counts_the_falling_quarters(self) -> None:
        self.assertIn("跨境量增速已连续三季走低到 12%", self.clean)
        self.assertIn("（15% → 14% → 13% → 12%）", self.clean)

        def rebound(s):
            s["key_drivers_local_pct"]["cross_border"][-1] = 16

        forced = self.page(rebound)
        self.assertIn("跨境量增速本季 16%", forced)
        self.assertNotIn("连续三季走低", forced)

    def test_the_russia_sentence_has_the_direction_the_10q_gives(self) -> None:
        """「2022 年那几个高点带着俄罗斯业务退出的基数效应」: the 2022Q2 10-Q
        prints cross-border +58% reported and +64% excluding Russia."""
        self.assertNotIn("带着俄罗斯业务退出的基数效应", self.clean)
        self.assertIn("2022 年的报告增速被俄罗斯业务退出压低", self.clean)

    def test_the_plateau_is_the_trailing_run_in_its_band(self) -> None:
        self.assertIn("落到净支付网络收入的增量连续七季卡在 $506–$570M", self.clean)

        def higher_base_quarter(s):
            pn = s["payment_network_usd_m"]
            i = self.at(s, "Q2 2024")
            pn["payment_network_net_revenue"][i] -= 230
            pn["value_added_services_net_revenue"][i] += 230

        forced = self.page(higher_base_quarter)
        self.assertNotIn("连续七季卡在", forced)
        self.assertIn("连续四季卡在 $506–$550M", forced)

        def no_band(s):
            pn = s["payment_network_usd_m"]
            i = self.at(s, "Q1 2025")
            pn["payment_network_net_revenue"][i] -= 300
            pn["value_added_services_net_revenue"][i] += 300

        self.assertIn("落到净支付网络收入的增量本季是 $506M", self.page(no_band))

    def test_the_ratio_dip_is_called_seasonal_because_it_is(self) -> None:
        """「本季环比 -0.88pp 是记录里少见的回落」: 8 of 17 changes are falls,
        every first and second quarter since 2023 fell."""
        self.assertNotIn("少见的回落", self.clean)
        self.assertIn("本季环比 -0.88pp 是季节性的回落：17 次环比里有 8 次下降，"
                      "2023 年起每年的第一、二季都比前一季低，而每年的峰值都在第四季。", self.clean)

        def q1_rose(s):
            # Q1 2024 edges above Q4 2023 (51.34%) and stays under Q4 2024
            # (51.46%), so the fourth quarter is still each year's peak.
            pn = s["payment_network_usd_m"]
            i = self.at(s, "Q1 2024")
            pn["payment_network_net_revenue"][i] -= 25
            pn["value_added_services_net_revenue"][i] += 25

        rose = self.page(q1_rose)
        self.assertNotIn("每年的第一、二季都比前一季低", rose)
        self.assertIn("本季环比 -0.88pp：17 次环比里有 7 次下降。", rose)

    def test_the_only_yoy_fall_is_counted(self) -> None:
        self.assertIn("14 个可比季里 13 次上升，唯一一次下降只有 0.31pp", self.clean)

        def two_falls(s):
            pn = s["payment_network_usd_m"]
            i = self.at(s, "Q2 2025")
            pn["payment_network_net_revenue"][i] += 400
            pn["value_added_services_net_revenue"][i] -= 400

        forced = self.page(two_falls)
        self.assertNotIn("唯一一次下降", forced)
        self.assertIn("14 个可比季里 12 次上升，2 次下降", forced)

    def test_the_first_split_quarter_is_named_not_counted(self) -> None:
        """「18 季前是 34.2%」「18 季前只有 $1,390M」: Q1'22 is 17 quarters back."""
        self.assertNotIn("18 季前", self.clean)
        self.assertIn("增值服务已占净收入 41.2%，Q1'22 是 34.2%", self.clean)
        self.assertIn("跨境本季 $3,460M，Q1'22 只有 $1,390M", self.clean)

    def test_the_vas_share_of_the_increment_words(self) -> None:
        self.assertIn("<b>增值服务撑起过半增量</b>", self.clean)

        def network_leads(s):
            pn = s["payment_network_usd_m"]
            pn["payment_network_net_revenue"][-1] += 900
            pn["total_net_revenue"][-1] += 900
            pn["domestic_assessments"][-1] += 900

        self.assertNotIn("撑起过半增量", self.page(network_leads))

    def test_the_conversion_low_is_located_on_the_whole_axis(self) -> None:
        """「2024 年上半年这条线曾低到 94%」: the 94% is 2019Q3; 2024H1 was 99%."""
        self.assertIn("2019 年第三季这条线曾低到 94%", self.clean)
        self.assertNotIn("2024 年上半年这条线", self.clean)

        def lower_in_2023(s):
            q = s["quarterly_usd_m"]
            q["operating_cash_flow"][self.at(s, "Q3 2023")] -= 2000

        self.assertIn("2023 年第三季这条线曾低到", self.page(lower_in_2023))

    def test_the_incentive_cash_title_matches_its_note(self) -> None:
        """The title said 「客户激励的现金净消耗」 while the note says the prepaid
        line is not only customer incentives."""
        self.assertNotIn("客户激励的现金净消耗", self.clean)
        self.assertIn("预付费用现金流出减客户激励摊销：本季 $1,084M", self.clean)
        self.assertIn("摊销本身也在加速——上半年 $1,310M，同比 +31.9%", self.clean)

        def flat_amortisation(s):
            q = s["quarterly_usd_m"]["amortization_of_customer_incentives"]
            for i in (self.at(s, "Q1 2026"), self.at(s, "Q2 2026")):
                q[i] = q[i - 4]

        self.assertNotIn("摊销本身也在加速", self.page(flat_amortisation))

    def test_the_next_headroom_names_what_is_breached(self) -> None:
        self.assertIn("下季 5 条量化阈值：被击穿的两条一条在现金转化、一条在管理层自己的买入价", self.clean)
        self.assertNotIn("见下方核对表", self.clean)
        self.assertIn("另有 4 条需等披露才能判定：月度跨境细项", self.clean)

        def cash_recovered(s):
            q = s["quarterly_usd_m"]
            q["operating_cash_flow"][-1] += 1500

        forced = self.page(cash_recovered)
        self.assertIn("被击穿的一条在管理层自己的买入价", forced)
        self.assertNotIn("已经在 85% 之下", forced)

    def test_the_margin_note_measures_the_magnification(self) -> None:
        """「放大约五倍」: +1.79pp against +0.27pp is 6.6 times."""
        self.assertIn("上季的特殊项是 $202M 重组、本季是 $82M 诉讼计提，所以直接比较两季的 GAAP 利润率会把改善放大约 6.6 倍", self.clean)
        self.assertIn("本季 61.11% 是这 42 季里的最高值", self.clean)
        self.assertNotIn("这十八季里的最高值", self.clean)

        def earlier_peak(s):
            q = s["quarterly_usd_m"]
            q["operating_income"][self.at(s, "Q3 2025")] += 500

        self.assertNotIn("是这 42 季里的最高值", self.page(earlier_peak))

    def test_the_leverage_record_is_measured_on_the_whole_axis(self) -> None:
        self.assertIn("倍数 4.4x 是 42 季里的最高值（此前最高 2.9x）", self.clean)

        def old_peak(s):
            s["balance_sheet_usd_m"]["total_equity"][self.at(s, "Q1 2018")] = 1000

        self.assertNotIn("是 42 季里的最高值（此前", self.page(old_peak))

    def test_the_buyback_price_run_and_authority(self) -> None:
        self.assertIn("从 Q3'25 的 $574 一路降到本季的 $500", self.clean)
        self.assertIn("本季董事会未新增授权", self.clean)

        def new_authority(s):
            s["balance_sheet_usd_m"]["remaining_repurchase_authorization"][-1] += 10000

        self.assertIn("本季董事会新增了约 $9,998M 授权", self.page(new_authority))

    def test_the_share_count_span_is_the_axis(self) -> None:
        """「摊薄股数十八季从 1,112 百万」: 1,112 is 2016Q1, 42 quarters back."""
        self.assertIn("摊薄股数 42 季从 1,112 百万降到 883 百万", self.clean)
        self.assertIn("42 季现金流、回购与资本结构", self.clean)

    def test_cross_border_overtook_domestic_quarters_ago(self) -> None:
        """「跨境这条本季超过境内」: it has been above since Q2'25."""
        self.assertIn("跨境这条自 Q2'25 起连续 5 季高于境内", self.clean)

        def just_now(s):
            pn = s["payment_network_usd_m"]
            i = self.at(s, "Q1 2026")
            pn["cross_border_assessments"][i] -= 400
            pn["domestic_assessments"][i] += 400

        self.assertIn("跨境这条本季超过境内", self.page(just_now))

    def test_the_rebate_check_is_at_a_precision_that_decides_the_rounding(self) -> None:
        """「减法给出 +22.5%、四舍五入后一致」 invites 23; the subtraction is 22.46%."""
        self.assertIn("上半年公司说 +22%、减法给出 +22.46%", self.clean)
        self.assertIn("10-Q 的管理层讨论与分析里用一句话印着本季返点 $5,997M", self.clean)
        self.assertNotIn("+22.5%", self.clean)

    def test_the_q4_seasonality_claim_needs_every_q4(self) -> None:
        self.assertIn("支付网络那条每年第四季都会回落一格", self.clean)

        def q4_up(s):
            pn = s["payment_network_usd_m"]
            i = self.at(s, "Q4 2023")
            pn["payment_network_net_revenue"][i] += 400
            pn["value_added_services_net_revenue"][i] -= 400

        self.assertNotIn("每年第四季都会回落一格", self.page(q4_up))

    def test_the_venezuela_note_says_what_the_filings_say(self) -> None:
        """「并追溯重述前期」: the 10-Q's Q2 2025 comparatives are the first prints."""
        self.assertNotIn("追溯重述", self.clean)
        self.assertIn("没有重述前期：10-Q 里 Q2 2025 的三条增速（GDV 9%、跨境量 15%、换手笔数 10%）", self.clean)

    def test_regional_gdv_is_not_growth_only(self) -> None:
        """「分地区的 GDV 金额（公司只披露增速）」: the release's Operating
        Performance table prints GDV in US$ billions by region -- and the page
        now draws it, so the not-wired list may not name it either."""
        self.assertNotIn("公司只披露增速、不披露金额", self.clean)
        self.assertNotIn("分地区的 GDV 金额（公司只披露增速）", self.clean)
        self.assertNotIn("分地区的 GDV 金额（业绩发布的 Operating Performance 表按地区印着金额", self.clean)
        self.assertNotIn("申报文件只给这三条", self.clean)
        self.assertIn("分地区 GDV：本季 $2,881B", self.clean)

    def test_the_regional_title_follows_europe_against_the_us(self) -> None:
        self.assertIn("欧洲 $1,025B 占 35.6%，已连续 13 季高于美国的 $858B", self.clean)

        def us_ahead(s):
            gdv = s["gdv_by_region"]
            gdv["united_states_usd_b"][-1] = gdv["europe_usd_b"][-1] + 1

        behind = self.page(us_ahead)
        self.assertNotIn("高于美国", behind)
        self.assertIn("占 35.6%，美国 $1,026B", behind)

        def just_passed(s):
            gdv = s["gdv_by_region"]
            gdv["united_states_usd_b"][-2] = gdv["europe_usd_b"][-2] + 1

        once = self.page(just_passed)
        self.assertIn("，本季高于美国的 $858B", once)
        self.assertNotRegex(once, r"已连续 \d+ 季高于美国")


if __name__ == "__main__":
    unittest.main()
