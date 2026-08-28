"""Reconciliation and shape tests for the V (Visa) page.

Same purpose as the other companies': nothing derived reaches the page until it
has been checked against a statement identity or a figure the company disclosed
separately.  Visa's page rests on three identities and one distinction.

The identities are what license the client-incentive rate, which is the number
this whole page is about.  Visa discloses the four gross revenue lines and the
client-incentive contra line separately, so the rate is a division of filed
figures rather than an estimate -- but only if the five really do reconcile to
the filed net revenue, in every one of the 55 quarters, including the fiscal
fourth quarters that are a year minus a nine-month column.  These tests pin
that, plus the geography split and the operating-income identity.

The distinction is the page's one flat contradiction of the local research note,
so it gets pinned by value rather than described.  The U.S. litigation escrow
funds U.S. covered litigation and nothing else; the balance-sheet "Accrued
litigation" line is larger because it also carries matters the escrow cannot
pay.  Measured against the accrual it actually funds, the account is in surplus.
Measured against the total, the same quarter looks short by several hundred
million.  A test that only checked "the page plots an escrow series" would not
notice if the two were ever swapped, so this one checks the sign of both.
"""

from __future__ import annotations

import json
import math
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.all import build_all, roster_payload  # noqa: E402
from build.board import headroom  # noqa: E402
from build.v import build_payload, compact_period  # noqa: E402


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


class VDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "v.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]
        cls.by_section = {
            section["id"]: section["exhibits"] for section in cls.payload["sections"]
        }
        cls.lines = cls.source["revenue_lines_usd_m"]

    # ── shape ────────────────────────────────────────────────────────────────
    def test_the_window_is_eight_quarters_and_complete(self) -> None:
        self.assertEqual(len(self.source["periods"]), 8)
        self.assertEqual(len(self.source["period_ends"]), 8)
        self.assertEqual(len(self.source["fiscal_labels"]), 8)
        for name, values in self.source["financials"].items():
            self.assertEqual(len(values), 8, name)
            self.assertTrue(
                all(value is not None and math.isfinite(value) for value in values), name)

    def test_the_long_record_is_one_row_per_quarter(self) -> None:
        length = len(self.lines["quarters"])
        self.assertGreaterEqual(length, 55)
        for name, values in self.lines.items():
            self.assertEqual(len(values), length, name)
        self.assertTrue(all(value is not None for value in self.lines["incentive_rate_pct"]))

    def test_quarters_are_contiguous_calendar_labels(self) -> None:
        for quarters in (self.lines["quarters"], self.source["periods"],
                         self.source["geography_usd_m"]["quarters"],
                         self.source["litigation"]["quarters"],
                         self.source["capital_allocation_usd_m"]["quarters"]):
            numbers = []
            for label in quarters:
                quarter, year = label.split()
                numbers.append(int(year) * 4 + int(quarter[1]) - 1)
            self.assertEqual(numbers, list(range(numbers[0], numbers[0] + len(numbers))),
                             quarters[:3])

    def test_the_window_is_the_tail_of_the_long_record(self) -> None:
        self.assertEqual(self.lines["quarters"][-8:], self.source["periods"])

    def test_fiscal_labels_map_to_the_calendar_labels_the_page_publishes(self) -> None:
        """FY Q1 → prior-year Q4, Q2 → Q1, Q3 → Q2, Q4 → Q3.

        Getting this backwards would silently shift every V row of the
        cross-company capex table by one quarter, which is exactly the failure
        the shared convention exists to prevent.
        """
        shift = {"1": (-1, "Q4"), "2": (0, "Q1"), "3": (0, "Q2"), "4": (0, "Q3")}
        for fiscal, calendar in zip(self.lines["fiscal_labels"], self.lines["quarters"]):
            year, number = int(fiscal[2:6]), fiscal[-1]
            offset, quarter = shift[number]
            self.assertEqual(calendar, f"{quarter} {year + offset}", fiscal)
        self.assertEqual(self.source["fiscal_labels"][-1], "FY2026Q3")
        self.assertEqual(self.source["periods"][-1], "Q2 2026")
        self.assertEqual(self.source["period_ends"][-1], "2026-06-30")

    # ── identities the filings have to satisfy ───────────────────────────────
    def test_gross_revenue_lines_less_incentives_equal_filed_net_revenue(self) -> None:
        """The identity that licenses the incentive rate.

        Every quarter, including the fiscal fourths that are a 10-K year minus
        the June 10-Q's nine-month column. A basis error in that subtraction
        would show up here before it reached a chart.
        """
        for index, period in enumerate(self.lines["quarters"]):
            gross = sum(self.lines[key][index] for key in
                        ("service", "data_processing", "international_transaction", "other"))
            self.assertAlmostEqual(gross, self.lines["gross_revenue"][index], places=3, msg=period)
            self.assertAlmostEqual(
                gross + self.lines["client_incentives"][index],
                self.lines["net_revenue"][index], delta=0.51, msg=period)

    def test_client_incentives_are_negative_everywhere(self) -> None:
        """A contra-revenue line that flipped sign would invert the whole page."""
        for index, period in enumerate(self.lines["quarters"]):
            self.assertLess(self.lines["client_incentives"][index], 0, period)

    def test_incentive_rate_is_the_ratio_of_two_filed_lines(self) -> None:
        for index, period in enumerate(self.lines["quarters"]):
            self.assertAlmostEqual(
                -self.lines["client_incentives"][index] / self.lines["gross_revenue"][index] * 100,
                self.lines["incentive_rate_pct"][index], places=6, msg=period)

    def test_geography_sums_to_filed_net_revenue(self) -> None:
        geo = self.source["geography_usd_m"]
        for index, period in enumerate(geo["quarters"]):
            self.assertAlmostEqual(geo["us"][index] + geo["international"][index],
                                   geo["net_revenue"][index], delta=0.51, msg=period)

    def test_net_revenue_less_operating_expenses_equals_operating_income(self) -> None:
        financials = self.source["financials"]
        for index, period in enumerate(self.source["periods"]):
            self.assertAlmostEqual(
                financials["net_revenue_usd_m"][index] - financials["total_opex_usd_m"][index],
                financials["operating_income_usd_m"][index], delta=0.51, msg=period)

    def test_the_geography_window_starts_where_the_disclosure_does(self) -> None:
        """ASC 606 introduced the split; earlier filings do not carry it.

        The window is short on purpose and must not be padded backwards from the
        longer revenue-line record.
        """
        geo = self.source["geography_usd_m"]
        self.assertLess(len(geo["quarters"]), len(self.lines["quarters"]))
        self.assertEqual(geo["quarters"][-1], self.lines["quarters"][-1])
        self.assertEqual(geo["quarters"][0], "Q4 2018")

    # ── the only filed forward number Visa ever repeated ─────────────────────
    def test_the_incentive_guidance_record_is_four_fiscal_years(self) -> None:
        entries = self.source["incentive_guidance"]["entries"]
        self.assertEqual([entry["fiscal_year"] for entry in entries],
                         [2017, 2018, 2019, 2020])
        for entry in entries:
            self.assertLess(entry["lo"], entry["hi"], entry["fiscal_year"])
            self.assertIsNotNone(entry["actual_pct"])
            self.assertTrue(entry["accession"].startswith("00014031610")
                            or entry["accession"].startswith("0001403161"))

    def test_three_of_four_guided_years_landed_below_the_guided_floor(self) -> None:
        """The finding, pinned by value.

        Below the floor is the GOOD direction here: a lower rate means Visa gave
        back less of its gross revenue than it had told the market it would. If
        a future rebuild flips any of these verdicts the headline is wrong.
        """
        entries = self.source["incentive_guidance"]["entries"]
        verdicts = [
            "below" if entry["actual_pct"] < entry["lo"]
            else "above" if entry["actual_pct"] > entry["hi"] else "inside"
            for entry in entries
        ]
        self.assertEqual(verdicts, ["below", "below", "below", "inside"])
        self.assertNotIn("above", verdicts)

    def test_the_guided_rate_was_abandoned_and_the_rate_kept_rising(self) -> None:
        record = self.source["incentive_guidance"]
        self.assertEqual(record["stopped_after_fiscal_year"], 2020)
        last_guided = record["entries"][-1]["actual_pct"]
        latest = self.lines["incentive_rate_pct"][-1]
        self.assertGreater(latest, last_guided + 4.0)

    def test_the_incentive_rate_is_a_long_one_way_climb(self) -> None:
        rate = self.lines["incentive_rate_pct"]
        self.assertLess(rate[0], 17.0)
        self.assertGreater(rate[-1], 28.0)
        self.assertGreater(rate[-1] - rate[0], 12.0)

    # ── the escrow distinction ───────────────────────────────────────────────
    def test_the_escrow_is_measured_against_the_accrual_it_funds(self) -> None:
        """Both signs pinned, because the whole point is that they differ.

        Against U.S. covered litigation -- the only thing the Retrospective
        Responsibility Plan escrow can pay -- the latest quarter is in surplus.
        Against the balance-sheet total, which also carries VE Territory and
        uncovered matters, the same quarter reads as a large shortfall. The page
        publishes the first and shows the second as context; swapping them would
        reverse the conclusion.
        """
        litigation = self.source["litigation"]
        escrow = litigation["escrow_usd_m"][-1]
        covered = litigation["us_covered_litigation_usd_m"][-1]
        total = litigation["accrued_litigation_total_usd_m"][-1]
        self.assertGreater(escrow - covered, 0)
        self.assertLess(escrow - total, -300)
        self.assertGreater(total, covered)

    def test_covered_litigation_never_exceeds_the_total_accrual(self) -> None:
        litigation = self.source["litigation"]
        for index, period in enumerate(litigation["quarters"]):
            covered = litigation["us_covered_litigation_usd_m"][index]
            total = litigation["accrued_litigation_total_usd_m"][index]
            if covered is None or total is None:
                continue
            self.assertLessEqual(covered, total + 0.51, period)

    # ── the page refuses a guidance record ───────────────────────────────────
    def test_the_page_carries_no_quarterly_guidance_block(self) -> None:
        """Visa files no quarterly numeric guidance, so the slot stays empty.

        This is the same sourcing limit the Microsoft and Alphabet pages carry.
        A future rebuild that filled it from call material would be inventing a
        record the filings cannot check.
        """
        self.assertIsNone(self.payload["guidance"])

    def test_no_range_band_exhibit_is_drawn_on_a_quarterly_axis(self) -> None:
        for exhibit in self.exhibits:
            if exhibit["kind"] != "range_band":
                continue
            for label in exhibit["xlabels"]:
                self.assertRegex(label, r"^FY\d{4}$", exhibit["title"])

    def test_the_page_does_not_publish_a_release_count(self) -> None:
        """The tally was sampled, not exhaustive, so it is not printed.

        An earlier draft said "1 of 18 releases". That ratio came from reading
        18 of a 40-plus release window and does not generalise, so the page
        describes the eras instead. This keeps the claim from creeping back.
        """
        text = json.dumps(self.payload, ensure_ascii=False)
        self.assertNotIn("18 份", text)
        self.assertNotIn("0 份", text)

    # ── section three thresholds ─────────────────────────────────────────────
    def test_every_threshold_has_a_current_value_and_a_direction(self) -> None:
        for entry in self.source["next_kpi"]["quantified"]:
            self.assertIn(entry["direction"], ("up", "down"))
            self.assertIsNotNone(entry["current"])
            self.assertNotEqual(entry["threshold"], 0)

    def test_headroom_bars_match_the_threshold_table(self) -> None:
        overview = self.by_section["next_quarter"][0]
        entries = self.source["next_kpi"]["quantified"]
        self.assertEqual(overview["kind"], "diverging_bars")
        self.assertEqual(overview["xlabels"], [entry["metric"] for entry in entries])
        for value, entry in zip(overview["values"], entries):
            self.assertAlmostEqual(
                value, round(headroom(entry["direction"], entry["threshold"],
                                      entry["current"]), 1), places=6, msg=entry["metric"])

    def test_the_escrow_threshold_is_measured_on_the_covered_basis(self) -> None:
        entry = next(e for e in self.source["next_kpi"]["quantified"] if "托管" in e["metric"])
        litigation = self.source["litigation"]
        self.assertAlmostEqual(
            entry["current"],
            round(litigation["escrow_usd_m"][-1]
                  - litigation["us_covered_litigation_usd_m"][-1], 1),
            places=6)

    # ── payload shape ───────────────────────────────────────────────────────
    def test_exhibits_are_numbered_in_render_order(self) -> None:
        numbers = [exhibit["n"] for exhibit in self.exhibits]
        self.assertEqual(numbers, list(range(2, 2 + len(numbers))))

    def test_no_exhibit_reference_placeholder_survives(self) -> None:
        text = json.dumps(self.payload, ensure_ascii=False)
        self.assertNotIn("{EX_", text)
        for exhibit in self.exhibits:
            self.assertNotIn("ref", exhibit)

    def test_every_exhibit_has_a_note_and_a_source(self) -> None:
        for exhibit in self.exhibits:
            self.assertTrue(exhibit.get("note"), exhibit["title"])
            self.assertTrue(exhibit.get("src_extra"), exhibit["title"])

    def test_tables_are_numbered_after_the_last_exhibit(self) -> None:
        last = self.exhibits[-1]["n"]
        self.assertEqual([table["n"] for table in self.payload["tables"]],
                         list(range(last + 1, last + 1 + len(self.payload["tables"]))))
        for table in self.payload["tables"]:
            for row in table["rows"]:
                self.assertEqual(len(row), len(table["headers"]), table["title"])

    def test_the_cross_company_capex_table_is_published_here_too(self) -> None:
        titles = [table["title"] for table in self.payload["tables"]]
        self.assertTrue(any("AI capex 循环" in title for title in titles))

    def test_the_excluded_list_names_what_cannot_be_sourced(self) -> None:
        excluded = self.source["next_kpi"]["excluded"]
        for term in ("non-GAAP 营业费用", "变现率", "增值服务"):
            self.assertIn(term, excluded)

    def test_the_notes_state_the_service_revenue_lag(self) -> None:
        """The lag is why the page refuses a revenue-versus-volume comparison.

        Visa recognises service revenue on the PRIOR quarter's payments volume
        and says so in every release, while the release's own headline table
        prints the CURRENT quarter's volume. Dropping this note would leave the
        refusal looking arbitrary.
        """
        notes = " ".join(self.payload["notes"])
        self.assertIn("上一季度", notes)
        self.assertIn("Key Business Drivers", notes)

    def test_compact_period_shortens_labels(self) -> None:
        self.assertEqual(compact_period("Q2 2026"), "Q2'26")

    # ── published artefacts ─────────────────────────────────────────────────
    def test_published_payload_roster_and_shell(self) -> None:
        published = js_payload(ROOT / "data" / "v.js", "window.DASH")
        self.assertEqual(published, self.payload)
        roster = js_payload(ROOT / "data" / "roster.js", "window.ROSTER")
        self.assertEqual(roster, roster_payload(build_all()))
        self.assertIn("v", [item["slug"] for item in roster["items"]])
        entry = next(item for item in roster["items"] if item["slug"] == "v")
        self.assertEqual(entry["latest_label"], "Q2 2026")
        self.assertEqual(entry["group"], "payment_networks")
        self.assertIn(entry["group"], {group["key"] for group in roster["groups"]})
        shell = (ROOT / "v" / "index.html").read_text(encoding="utf-8")
        self.assertIn("../data/v.js", shell)
        self.assertNotIn("../data/tsm.js", shell)

    def test_shell_versions_every_script_by_content(self) -> None:
        import hashlib

        shell = (ROOT / "v" / "index.html").read_text(encoding="utf-8")
        sources = re.findall(r'<script src="\.\./([^"?]+)(\?v=([0-9a-f]+))?"', shell)
        self.assertEqual(len(sources), 4)
        for relative, _query, digest in sources:
            target = ROOT / relative
            self.assertTrue(target.exists(), relative)
            self.assertEqual(
                digest, hashlib.sha256(target.read_bytes()).hexdigest()[:8], relative)

    def test_the_home_page_lists_the_company_once(self) -> None:
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertEqual(home.count('href="v/"'), 1)
        self.assertIn("支付网络", home)
        count = int(re.search(r"(\d+) 家公司", home).group(1))
        self.assertEqual(count, home.count('class="hcard"'))


if __name__ == "__main__":
    unittest.main()
