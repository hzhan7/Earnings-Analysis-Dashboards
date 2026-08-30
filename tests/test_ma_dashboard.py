"""Checks for the MA page.

Three things here are worth pinning beyond the usual shape checks.

First, the rebate line. Mastercard does not print "payment network rebates and
incentives" anywhere: the four assessment lines are printed gross and the
payment network is printed net, so the whole page rests on one subtraction.
The company does publish that line's *growth rate* in its earnings release, and
the subtraction has to reproduce it -- that is the only external check this
series has, so it is a test rather than a comment.

Second, the three-leg decomposition. Net revenue = gross assessments − rebates
+ value-added services is an identity, not an approximation, and the page says
so on the chart. If it ever stopped closing to the last dollar, the chart would
still draw.

Third, the adjusted operating margin. The page rebuilds Mastercard's own
adjusted operating margin from filed lines (operating income plus the
litigation provision plus the one restructuring charge). Eight quarters of the
company's published figure are carried in the source so that reconstruction can
be checked against them; without that check the page would be publishing a
non-GAAP number of its own invention while calling it the company's.
"""

from __future__ import annotations

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

from build.board import headroom  # noqa: E402
from build.ma import ASSESSMENT_LINES, build_payload, compact_period  # noqa: E402

WINDOW = 18


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


class MaDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "ma.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]
        cls.by_section = {
            section["id"]: section["exhibits"] for section in cls.payload["sections"]
        }
        cls.by_ref = {ex["ref"]: ex for ex in cls.exhibits if "ref" in ex}
        cls.pn = cls.source["payment_network_usd_m"]
        cls.q = cls.source["quarterly_usd_m"]
        cls.annual = cls.source["annual_usd_m"]
        cls.periods = cls.source["periods"]
        # The page now carries two windows. `periods` is the whole record; the
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

    def test_the_record_is_forty_two_quarters_and_the_split_is_eighteen(self) -> None:
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
        self.assertEqual(len(self.periods), 42)
        self.assertEqual(self.periods[0], "Q1 2016")
        self.assertEqual(len(self.dis_periods), WINDOW)
        self.assertEqual(self.dis_periods[0], "Q1 2022")
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
        self.assertEqual(self.periods[-1], "Q2 2026")
        holes = set(self.source["not_backfilled"]["fields"])
        for block in ("payment_network_usd_m", "quarterly_usd_m", "per_share",
                      "balance_sheet_usd_m"):
            for name, values in self.source[block].items():
                if not isinstance(values, list):
                    continue
                self.assertEqual(len(values), 42, f"{block}.{name}")
                reported = [v for v in values if v is not None]
                if f"{block}.{name}" not in holes:
                    # Two per-share cells are genuinely absent: the SEC removed
                    # the quarterly-data note in 2021, so the fourth quarters of
                    # 2020 and 2021 have no filed EPS or weighted share count,
                    # and neither is additive.
                    self.assertGreaterEqual(len(reported), 40, f"{block}.{name}")
                self.assertTrue(all(math.isfinite(v) for v in reported),
                                f"{block}.{name}")
        # The three key drivers are release metrics and run the whole record.
        for name, values in self.source["key_drivers_local_pct"].items():
            self.assertEqual(len(values), 42, name)
            self.assertTrue(all(v is not None for v in values), name)

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
        self.assertEqual(checked, WINDOW)

    def test_the_derived_rebate_reproduces_the_companys_published_growth(self) -> None:
        """The only external check the rebate series has.

        Mastercard prints no rebate dollar figure under the current
        presentation, but its earnings release states the growth rate: +22% for
        the quarter and +22% for the six months. The subtraction has to land on
        those once rounded, or the two subtrahends are not the pair the company
        is netting.
        """
        latest, year_ago = WINDOW - 1, WINDOW - 5
        quarter_growth = self.rebates[latest] / self.rebates[year_ago] * 100 - 100
        self.assertEqual(round(quarter_growth), 22)
        half = sum(self.rebates[latest - 1:latest + 1])
        prior_half = sum(self.rebates[year_ago - 1:year_ago + 1])
        self.assertEqual(round(half / prior_half * 100 - 100), 22)
        # The two anchors the local note independently confirmed from the
        # company's own footnote, to the dollar.
        self.assertEqual(self.rebates[latest], 5997)
        self.assertEqual(self.rebates[year_ago], 4923)

    def test_three_leg_decomposition_closes_to_the_dollar(self) -> None:
        """Gross − rebate + value-added services *is* the net revenue change."""
        chart = self.by_ref["EX_LEGS"]
        gross_leg, rebate_leg, vas_leg = (group["values"] for group in chart["groups"])
        self.assertEqual(len(gross_leg), WINDOW - 4)
        for offset in range(WINDOW - 4):
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
        # Only one quarter in the window carries a restructuring charge; if a
        # second ever appeared without being sourced, the reconstruction above
        # would drift silently on that quarter alone.
        charged = [
            self.periods[index]
            for index, value in enumerate(self.q["restructuring_charge"]) if value
        ]
        self.assertEqual(charged, ["Q1 2026"])

    def test_the_page_publishes_no_guidance_record_and_says_why(self) -> None:
        """Six companies here settle a filed guidance range every quarter.
        Mastercard files no forward number, so this page must not grow a
        guidance chart by imitation -- and must say that out loud."""
        self.assertIsNone(self.payload["guidance"])
        self.assertFalse(self.source["guidance_disclosure"]["files_numeric_guidance"])
        self.assertNotIn("range_band", [ex["kind"] for ex in self.exhibits])
        self.assertTrue(
            any("申报文件" in note and "指引" in note for note in self.payload["notes"]),
            "the sourcing limit has to be stated on the page, not only in the source",
        )
        wording = self.source["guidance_disclosure"]["latest_wording"]
        table = next(t for t in self.payload["tables"] if "前瞻指引" in t["title"])
        self.assertEqual(len(table["rows"]), len(wording))

    def test_currency_neutral_gaps_are_exactly_the_unpublished_quarters(self) -> None:
        """The company publishes each assessment line's currency-neutral growth
        only for the quarter just reported, and 2022 predates the presentation,
        so the holes are the four 2022 quarters plus every fourth quarter."""
        # Three reasons a cell is empty, and they are different reasons:
        # before 2022Q1 the disaggregation does not exist at all; 2022 predates
        # the currency-neutral presentation of it; and from 2023 the company
        # gives these rates only for the quarter just reported, so each fourth
        # quarter -- reported in the annual release -- has none.
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

    def test_repurchase_price_is_the_two_filed_numbers_divided(self) -> None:
        per_share = self.source["per_share"]
        latest = len(self.periods) - 1
        price = self.q["stock_repurchases"][latest] / per_share["shares_repurchased_m"][latest]
        self.assertAlmostEqual(price, 499.80, delta=0.01)
        current = next(
            entry for entry in self.source["next_kpi"]["quantified"]
            if entry["metric"] == "回购隐含均价"
        )
        self.assertAlmostEqual(current["current"], price, delta=0.01)

    def test_headroom_bars_agree_with_the_thresholds_they_draw(self) -> None:
        pairs = [
            (self.by_section["settled"][1], self.source["prior_kpi_settlement"]["quantified"], "actual"),
            (self.by_section["next_quarter"][0], self.source["next_kpi"]["quantified"], "current"),
        ]
        for exhibit, entries, key in pairs:
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

    def test_sources_are_official_http_links(self) -> None:
        allowed_hosts = {"investor.mastercard.com", "www.sec.gov"}
        for source in self.payload["source_links"]:
            parsed = urlparse(source["url"])
            self.assertEqual(parsed.scheme, "https")
            self.assertIn(parsed.hostname, allowed_hosts)

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
        # The masthead count is hand-written and nothing else reads the roster.
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
        """Mastercard's fiscal year is the calendar year, so its Q2 2026 is the
        same three months as every other page's -- worth pinning, because the
        cross-company capex table would compare different periods otherwise."""
        self.assertEqual(self.payload["latest"]["disclosed_period_label"], "Q2 2026")
        self.assertEqual(self.payload["latest"]["period_end"], "2026-06-30")
        self.assertEqual(
            self.payload["latest"]["full_financial_period_label"], "Q2 2026")
        self.assertEqual(compact_period("Q2 2026"), "Q2'26")
        for exhibit in self.exhibits:
            for label in exhibit.get("xlabels", []):
                if re.fullmatch(r"Q[1-4]'\d{2}", label) or "阈值" in label:
                    continue
                self.assertIn(
                    label,
                    [entry["metric"] for entry in
                     self.source["prior_kpi_settlement"]["quantified"]
                     + self.source["next_kpi"]["quantified"]]
                    + self.source["followup_closure"]["labels"],
                    exhibit["title"],
                )

    def test_public_files_exclude_private_and_broker_material(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [ROOT / "series" / "ma.json", ROOT / "data" / "ma.js"]
        ).lower()
        for forbidden in ("onedrive", "obsidian", "/users/", "seeking alpha",
                          "price target", "forward p/e", "stockanalysis.com"):
            self.assertNotIn(forbidden, text, forbidden)


if __name__ == "__main__":
    unittest.main()
