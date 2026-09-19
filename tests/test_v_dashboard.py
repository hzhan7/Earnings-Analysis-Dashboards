"""Reconciliation and shape tests for the V (Visa) page.

Same purpose as the other companies': nothing derived reaches the page until it
has been checked against a statement identity or a figure the company disclosed
separately.  Visa's page rests on three identities and one distinction.

The identities are what license the client-incentive rate, which is the number
this whole page is about.  Visa discloses the four gross revenue lines and the
client-incentive contra line separately, so the rate is a division of filed
figures rather than an estimate -- but only if the five really do reconcile to
the filed net revenue in every quarter of the record, including the fiscal
fourth quarters that are a year minus a nine-month column.  These tests pin
that, plus the geography split and the operating-income identity.

The distinction is the page's one flat contradiction of the local research note.
The U.S. litigation escrow funds U.S. covered litigation and nothing else; the
balance-sheet "Accrued litigation" line is larger because it also carries
matters the escrow cannot pay.  The page measures the escrow against the first
and shows the second as context; the tests pin which series is which and that
the words follow the sign, whichever way a quarter lands.

A roll edits `series/v.json` and nothing else.  What the quarter's release and
10-Q printed is asserted from `_checks` (`VChecksTest`); `VRollTest` rolls the
series a quarter back and two forward and tampers each stamped block; and
`VFindingsTest` forces each judgement the page prints true and then false and
checks that the words follow.  What stays pinned by value is history a roll
cannot move: the guidance record, its verdicts, where the geography split
starts.
"""

from __future__ import annotations

import copy
import json
import math
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import v  # noqa: E402
from build.all import build_all, roster_payload  # noqa: E402
from build.board import cn_count, headroom, unit_text  # noqa: E402
from build.v import build_payload, compact_period  # noqa: E402


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
    return json.loads(v.STAGING_PATH.read_text(encoding="utf-8"))


class VDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = staged()
        cls.payload = build_payload(cls.source)
        cls.exhibits = exhibits_of(cls.payload)
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
                         self.source["capital_allocation_usd_m"]["quarters"],
                         self.source["income_long_usd_m"]["quarters"]):
            numbers = []
            for label in quarters:
                quarter, year = label.split()
                numbers.append(int(year) * 4 + int(quarter[1]) - 1)
            self.assertEqual(numbers, list(range(numbers[0], numbers[0] + len(numbers))),
                             quarters[:3])

    def test_the_per_share_record_skips_exactly_the_fiscal_fourths(self) -> None:
        """No 10-Q, and EPS does not subtract: those quarters are absent, not estimated."""
        per_share = self.source["per_share"]["quarters"]
        fiscal_of = dict(zip(self.lines["quarters"], self.lines["fiscal_labels"]))
        start = self.lines["quarters"].index(per_share[0])
        expected = [q for q in self.lines["quarters"][start:] if not fiscal_of[q].endswith("Q4")]
        self.assertEqual(per_share, expected)

    def test_every_long_block_ends_on_the_page_s_quarter(self) -> None:
        """A roll that appends to one block and forgets another would chart two
        different quarters under one label."""
        period = self.source["periods"][-1]
        self.assertEqual(self.source["latest"]["period"], period)
        for block in ("revenue_lines_usd_m", "geography_usd_m", "litigation",
                      "capital_allocation_usd_m", "income_long_usd_m"):
            self.assertEqual(self.source[block]["quarters"][-1], period, block)
        volumes = self.source["operating_volumes"]
        self.assertEqual(volumes["processed_transactions_quarters"][-1], period)

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
        self.assertEqual(self.source["fiscal_labels"], self.lines["fiscal_labels"][-8:])
        self.assertEqual(self.source["period_ends"], self.lines["period_ends"][-8:])

    def test_the_fiscal_fourth_quarters_are_the_differenced_ones(self) -> None:
        """The basis marker the audit table prints is the fiscal quarter, not a note."""
        for fiscal, basis in zip(self.lines["fiscal_labels"], self.lines["basis"]):
            self.assertEqual(basis, "fy_minus_9m" if fiscal.endswith("Q4") else "filed_3m", fiscal)
        capital = self.source["capital_allocation_usd_m"]
        fiscal_of = dict(zip(self.lines["quarters"], self.lines["fiscal_labels"]))
        for quarter, basis in zip(capital["quarters"], capital["basis"]):
            self.assertEqual(basis, "filed_3m" if fiscal_of[quarter].endswith("Q1") else "ytd_difference",
                             quarter)

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

    def test_the_eight_quarter_window_is_the_long_record_s_tail(self) -> None:
        financials = self.source["financials"]
        for key, line in (("net_revenue_usd_m", "net_revenue"), ("gross_revenue_usd_m", "gross_revenue"),
                          ("client_incentives_usd_m", "client_incentives"),
                          ("incentive_rate_pct", "incentive_rate_pct")):
            for got, want in zip(financials[key], self.lines[line][-8:]):
                self.assertAlmostEqual(got, want, places=6, msg=key)
        income = self.source["income_long_usd_m"]
        for key in ("operating_income_usd_m", "total_opex_usd_m"):
            self.assertEqual(financials[key], income[key][-8:], key)

    def test_geography_sums_to_filed_net_revenue(self) -> None:
        geo = self.source["geography_usd_m"]
        net = dict(zip(self.lines["quarters"], self.lines["net_revenue"]))
        for index, period in enumerate(geo["quarters"]):
            self.assertAlmostEqual(geo["us"][index] + geo["international"][index],
                                   geo["net_revenue"][index], delta=0.51, msg=period)
            self.assertAlmostEqual(geo["net_revenue"][index], net[period], delta=0.51, msg=period)

    def test_net_revenue_less_operating_expenses_equals_operating_income(self) -> None:
        income = self.source["income_long_usd_m"]
        net = dict(zip(self.lines["quarters"], self.lines["net_revenue"]))
        for index, period in enumerate(income["quarters"]):
            self.assertAlmostEqual(
                net[period] - income["total_opex_usd_m"][index],
                income["operating_income_usd_m"][index], delta=0.51, msg=period)

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
    def test_the_incentive_guidance_record_runs_from_the_first_computable_year(self) -> None:
        """Eight years, and the floor is the *series*, not the guidance.

        The page shipped four years for a long time. The metric was guided from
        fiscal 2013: the four earlier releases were read one by one (each
        accession is in the record below). The reason the record stops at 2013
        is that ``revenue_lines_usd_m`` starts at FY2013Q1, so FY2012 has no
        delivered rate that can be computed the same way -- a series floor, not
        a disclosure floor, and the two are worth keeping apart.
        """
        entries = self.source["incentive_guidance"]["entries"]
        self.assertEqual([entry["fiscal_year"] for entry in entries],
                         [2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020])
        first_fiscal_quarter = self.lines["fiscal_labels"][0]
        self.assertEqual(first_fiscal_quarter, "FY2013Q1")
        for entry in entries:
            self.assertLess(entry["lo"], entry["hi"], entry["fiscal_year"])
            self.assertIsNotNone(entry["actual_pct"])
            # Two filer prefixes, not one: Visa filed through an agent
            # (0001193125) up to and including the fiscal 2016 outlook and
            # self-filed (0001403161) from the fiscal 2017 one on. Pinning the
            # 0001403161 prefix -- which is what this assertion used to do --
            # would reject every year added below 2017 for a reason that has
            # nothing to do with the numbers.
            self.assertRegex(entry["accession"], r"^\d{10}-\d{2}-\d{6}$")
            self.assertIn(entry["accession"][:10], {"0001403161", "0001193125"})
            self.assertTrue(entry["file"].endswith(".htm"), entry["fiscal_year"])

    def test_the_verdicts_survive_the_longer_window(self) -> None:
        """The finding, pinned by value, on all eight years.

        Below the floor is the GOOD direction here: a lower rate means Visa gave
        back less of its gross revenue than it had told the market it would. The
        guidance stopped after fiscal 2020, so no roll can move these; the page's
        sentences about them are counted from the record on every build.
        """
        entries = self.source["incentive_guidance"]["entries"]
        verdicts = [
            "below" if entry["actual_pct"] < entry["lo"]
            else "above" if entry["actual_pct"] > entry["hi"] else "inside"
            for entry in entries
        ]
        self.assertEqual(verdicts, ["below", "inside", "below", "inside",
                                    "below", "below", "below", "inside"])
        facts = v.guidance_facts(self.source)
        self.assertEqual(facts["below"], [2013, 2015, 2017, 2018, 2019])
        self.assertEqual(facts["inside"], [2014, 2016, 2020])
        self.assertEqual(facts["above"], [])

    def test_every_delivered_rate_is_recomputable_from_the_quarterly_series(self) -> None:
        """The stored actual is not an independent number -- so check it isn't.

        Four of these eight entries were archived long before this window was
        extended, with their own gross-revenue and incentive totals. Summing the
        four fiscal quarters out of ``revenue_lines_usd_m`` reproduces all four
        to the cent, which is what licenses computing the other four the same
        way instead of re-keying them out of four more 10-Ks.
        """
        lines = self.lines
        totals: dict[str, list] = {}
        for label, gross, incentives in zip(lines["fiscal_labels"],
                                            lines["gross_revenue"],
                                            lines["client_incentives"]):
            bucket = totals.setdefault(label[:6], [0.0, 0.0, 0])
            bucket[0] += gross
            bucket[1] += incentives
            bucket[2] += 1
        for entry in self.source["incentive_guidance"]["entries"]:
            gross, incentives, quarters = totals["FY%d" % entry["fiscal_year"]]
            self.assertEqual(quarters, 4, entry["fiscal_year"])
            self.assertAlmostEqual(gross, entry["gross_revenue_usd_m"], places=6)
            self.assertAlmostEqual(incentives, entry["client_incentives_usd_m"],
                                   places=6)
            self.assertAlmostEqual(abs(incentives) / gross * 100,
                                   entry["actual_pct"], places=6)

    def test_the_fiscal_2016_basis_break_does_not_decide_that_year(self) -> None:
        """The one year in the new stretch where the two legs disagree.

        The FY2016 outlook says in the release itself that it excludes any Visa
        Europe impact; the delivered rate includes Visa Europe from the fourth
        fiscal quarter on. That is a real break and the note says so. What makes
        it publishable rather than misleading is that the verdict does not turn
        on it: drop the contaminated quarter and the three clean quarters land
        inside the same band.
        """
        record = self.source["incentive_guidance"]
        broken = [entry for entry in record["entries"] if "basis_break" in entry]
        self.assertEqual([entry["fiscal_year"] for entry in broken], [2016])
        entry, = broken
        break_ = entry["basis_break"]

        # The clean legs are recomputed here, not read: the stored ones are the
        # claim under test.
        lines = self.lines
        clean = [index for index, label in enumerate(lines["fiscal_labels"])
                 if label.startswith("FY2016")
                 and label != break_["excluded_fiscal_quarter"]]
        self.assertEqual(len(clean), break_["clean_quarters"])
        gross = sum(lines["gross_revenue"][index] for index in clean)
        incentives = sum(lines["client_incentives"][index] for index in clean)
        self.assertAlmostEqual(gross, break_["clean_gross_revenue_usd_m"], places=6)
        self.assertAlmostEqual(incentives, break_["clean_client_incentives_usd_m"],
                               places=6)
        clean_rate = abs(incentives) / gross * 100
        self.assertAlmostEqual(clean_rate, break_["clean_actual_pct"], places=6)

        # The break is real -- the two rates differ -- and it does not decide
        # the year, which is the only thing that makes the year publishable.
        self.assertNotAlmostEqual(clean_rate, entry["actual_pct"], places=2)
        both_inside = all(entry["lo"] <= rate <= entry["hi"]
                          for rate in (clean_rate, entry["actual_pct"]))
        self.assertEqual(break_["verdict_unchanged"], both_inside)
        self.assertTrue(both_inside)

    def test_the_deviation_headline_counts_instead_of_asserting(self) -> None:
        """The specific way this exhibit was wrong before, made unrepeatable.

        The published title read "four years, all negative" while FY2020's
        deviation was +0.37pp. Nothing measured it: the average beside it was
        derived and correct, the count next to it was typed. Two of the eight
        deviations are positive now, so a title that says they are all negative
        cannot be produced by counting.
        """
        entries = self.source["incentive_guidance"]["entries"]
        gaps = [entry["actual_pct"] - (entry["lo"] + entry["hi"]) / 2
                for entry in entries]
        negative = sum(1 for gap in gaps if gap < 0)
        self.assertEqual(negative, 6)
        self.assertEqual(len(gaps) - negative, 2)
        title = next(ex["title"] for ex in self.exhibits
                     if ex["title"].startswith("实际激励率相对指引中值的偏离"))
        self.assertIn("%d 年里 %d 年为负" % (len(gaps), negative), title)
        self.assertNotIn("全部为负", title)

    def test_the_record_stops_at_the_last_numeric_outlook(self) -> None:
        record = self.source["incentive_guidance"]
        self.assertEqual(record["stopped_after_fiscal_year"], 2020)
        self.assertEqual(record["first_guided_fiscal_year"], 2013)
        self.assertEqual(record["entries"][-1]["fiscal_year"], record["stopped_after_fiscal_year"])

    def test_the_fiscal_year_rates_count_full_years_only(self) -> None:
        """「每一年都比上一年高」 is read off whole fiscal years; the open one is not one."""
        yearly = v.fiscal_year_rates(self.lines)
        counts: dict[int, int] = {}
        for label in self.lines["fiscal_labels"]:
            counts[int(label[2:6])] = counts.get(int(label[2:6]), 0) + 1
        self.assertEqual(sorted(yearly), sorted(year for year, n in counts.items() if n == 4))
        open_year = int(self.lines["fiscal_labels"][-1][2:6])
        self.assertEqual(open_year in yearly, self.lines["fiscal_labels"][-1].endswith("Q4"))

    # ── the escrow distinction ───────────────────────────────────────────────
    def test_the_escrow_is_measured_against_the_accrual_it_funds(self) -> None:
        """The chart carries the three lines in a fixed order, and its title and
        reading are the escrow less the U.S. covered accrual -- never less the
        balance-sheet total, which also carries what the escrow cannot pay."""
        litigation = self.source["litigation"]
        escrow = litigation["escrow_usd_m"][-1]
        covered = litigation["us_covered_litigation_usd_m"][-1]
        total = litigation["accrued_litigation_total_usd_m"][-1]
        self.assertGreater(total, covered)
        chart = next(ex for ex in self.exhibits if ex["title"].startswith("托管账户对它真正负责的那笔负债"))
        self.assertEqual([s["values"][-1] for s in chart["series"]], [escrow, covered, total])
        word = "盈余" if escrow >= covered else "缺口"
        self.assertIn(f"{word} US${abs(escrow - covered):,.0f}M", chart["title"])
        self.assertEqual("若改用合计口径去比" in chart["note"], escrow < total)

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
        18 of the release window and does not generalise, so the page describes
        the eras instead. This keeps the claim from creeping back.
        """
        text = json.dumps(self.payload, ensure_ascii=False)
        self.assertNotIn("18 份", text)
        self.assertNotIn("0 份", text)

    # ── section three thresholds ─────────────────────────────────────────────
    def test_every_threshold_reads_its_value_from_the_series(self) -> None:
        """A current value typed into the block went stale against its own series:
        the international line's 6.06 was typed where the series gives 6.0566,
        and the headroom bar printed +51.5% instead of +51.4%."""
        block = self.source["next_kpi"]
        for entry in block["quantified"]:
            self.assertIn(entry["direction"], ("up", "down"))
            self.assertNotEqual(entry["threshold"], 0)
            self.assertIn("reads", entry, entry["metric"])
            self.assertNotIn("current", entry, entry["metric"])
        for entry in v.kpi_entries(block, self.source):
            self.assertTrue(math.isfinite(entry["current"]), entry["metric"])

    def test_headroom_bars_match_the_threshold_table(self) -> None:
        overview = self.by_section["next_quarter"][0]
        entries = v.kpi_entries(self.source["next_kpi"], self.source)
        self.assertEqual(overview["kind"], "diverging_bars")
        self.assertEqual(overview["xlabels"], [entry["metric"] for entry in entries])
        for value, entry in zip(overview["values"], entries):
            self.assertAlmostEqual(
                value, round(headroom(entry["direction"], entry["threshold"],
                                      entry["current"]), 1), places=6, msg=entry["metric"])
        table = next(t for t in self.payload["tables"] if t["title"].startswith("下季阈值与当前值"))
        for row, entry in zip(table["rows"], entries):
            self.assertEqual(row[3], unit_text(entry["unit"], entry["current"]), entry["metric"])

    def test_the_escrow_threshold_is_measured_on_the_covered_basis(self) -> None:
        entry = next(e for e in v.kpi_entries(self.source["next_kpi"], self.source)
                     if e["reads"] == "escrow_surplus")
        litigation = self.source["litigation"]
        self.assertAlmostEqual(
            entry["current"],
            litigation["escrow_usd_m"][-1] - litigation["us_covered_litigation_usd_m"][-1],
            places=6)

    def test_the_excluded_list_is_counted_where_it_is_printed(self) -> None:
        excluded = self.source["next_kpi"]["excluded"]
        note = self.by_section["next_quarter"][0]["note"]
        self.assertIn(f"另有{cn_count(len(excluded))}条本页<b>不接入</b>", note)
        for item in excluded:
            self.assertIn(item, note)

    # ── payload shape ───────────────────────────────────────────────────────
    def test_exhibits_are_numbered_in_render_order(self) -> None:
        numbers = [exhibit["n"] for exhibit in self.exhibits]
        self.assertEqual(numbers, list(range(2, 2 + len(numbers))))

    def test_no_placeholder_survives(self) -> None:
        text = json.dumps(self.payload, ensure_ascii=False)
        self.assertNotIn("{EX_", text)
        self.assertNotRegex(text, r"\{[a-z_]+\}")
        for exhibit in self.exhibits:
            self.assertNotIn("ref", exhibit)

    def test_the_wedge_reference_lands_on_the_wedge(self) -> None:
        margin = next(ex for ex in self.exhibits if ex["title"].startswith("GAAP 营业利润率"))
        number = int(re.search(r"见 Exhibit (\d+)", margin["note"]).group(1))
        target = next(ex for ex in self.exhibits if ex["n"] == number)
        self.assertTrue(target["title"].startswith("本季 GAAP 营业费用"), target["title"])

    def test_every_exhibit_has_a_note_and_a_source(self) -> None:
        for exhibit in self.exhibits:
            self.assertTrue(exhibit.get("note"), exhibit["title"])
            self.assertTrue(exhibit.get("src_extra"), exhibit["title"])

    def test_tables_are_numbered_after_the_last_exhibit(self) -> None:
        last = self.exhibits[-1]["n"]
        self.assertEqual([table["n"] for table in self.payload["tables"]],
                         list(range(last + 1, last + 1 + len(self.payload["tables"]))))
        for table in self.payload["tables"]:
            self.assertEqual(set(table), {"n", "title", "headers", "rows"}, table["title"])
            for row in table["rows"]:
                self.assertEqual(len(row), len(table["headers"]), table["title"])

    def test_literal_text_fields_carry_no_markup(self) -> None:
        """`page.js` writes these with textContent or through esc()."""
        for field in ("headline", "title", "subtitle", "tracker"):
            self.assertNotIn("<", self.payload[field], field)
        for section in self.payload["sections"]:
            self.assertNotIn("<", section["title"])
            self.assertNotIn("<", section["description"])
        for note in self.payload["notes"]:
            self.assertNotIn("<", note)
        for table in self.payload["tables"]:
            self.assertNotIn("<", table["title"])

    def test_the_page_prints_no_markdown(self) -> None:
        self.assertNotIn("**", own_text(self.payload))

    def test_no_currency_amount_carries_its_sign_inside(self) -> None:
        """「US$-386M」 was printed for a shortfall written as a negative number."""
        self.assertNotRegex(own_text(self.payload), r"US\$[-−]")

    def test_the_cross_company_capex_table_is_published_here_too(self) -> None:
        titles = [table["title"] for table in self.payload["tables"]]
        self.assertTrue(any("AI capex 循环" in title for title in titles))

    def test_the_notes_name_what_the_page_does_not_wire(self) -> None:
        notes = " ".join(self.payload["notes"])
        for term in ("跨境交易额的绝对金额",
                     "增值服务（VAS）收入（10-Q 按季印着金额，本页尚未接入）", "non-GAAP 营业费用"):
            self.assertIn(term, notes)
        # the quarterly nominal payments volume is wired now: the not-wired
        # list must not keep claiming otherwise
        self.assertNotIn("分季名义支付额（10-Q 印着金额，本页尚未接入）", notes)
        self.assertNotIn("本页尚未接入，详见", own_text(self.payload))

    def test_every_payments_volume_cell_names_the_filing_it_was_read_from(self) -> None:
        """Per-cell provenance, and the printed figures in it are the cells.

        Three quarters a year are printed by one 10-Q (its MD&A carries the
        PRIOR quarter's three-month column); April-June is printed by nothing
        and is the 10-K's twelve months to June less the June 10-Q's nine
        months to March, so those cells must show that subtraction.
        """
        volumes = self.source["operating_volumes"]
        source = volumes["nominal_payments_volume_source"]
        self.assertEqual(list(source), volumes["payments_volume_quarters"])
        month = {"Q1": "March 31", "Q2": "June 30", "Q3": "September 30", "Q4": "December 31"}
        for quarter, value in zip(volumes["payments_volume_quarters"],
                                  volumes["nominal_payments_volume_usd_b"]):
            text = source[quarter]
            amounts = [int(a.replace(",", "")) for a in re.findall(r"US\$([\d,]+)B", text)]
            with self.subTest(quarter=quarter):
                self.assertRegex(text, r"acc \d{10}-\d{2}-\d{6}")
                if quarter.startswith("Q2"):
                    self.assertIn(f"Twelve Months Ended June 30, {quarter[-4:]}", text)
                    self.assertIn(f"Nine Months Ended March 31, {quarter[-4:]}", text)
                    self.assertEqual(amounts[0] - amounts[1], value)
                    self.assertEqual(amounts[2], value)
                    self.assertIn(" D", text)
                else:
                    self.assertIn(f"Three Months Ended {month[quarter[:2]]}, {quarter[-4:]}", text)
                    self.assertTrue(text.startswith("10-Q"))
                    self.assertEqual(amounts, [value])

    def test_payments_volume_splits_into_its_two_regions(self) -> None:
        volumes = self.source["operating_volumes"]
        for quarter, total, us, intl in zip(volumes["payments_volume_quarters"],
                                            volumes["nominal_payments_volume_usd_b"],
                                            volumes["us_usd_b"], volumes["international_usd_b"]):
            # a printed column rounds once; an April-June cell is a difference of
            # two rounded columns on each of its three rows
            with self.subTest(quarter=quarter):
                self.assertLessEqual(abs(us + intl - total), 2 if quarter.startswith("Q2") else 1)

    def test_the_service_yield_is_service_over_the_prior_quarter_s_volume(self) -> None:
        """Worked out here from the two filed series, not from the builder."""
        chart = next(ex for ex in self.exhibits if ex["title"].startswith("Service revenue ÷ 上一季名义支付额"))
        volumes = self.source["operating_volumes"]
        volume = dict(zip(volumes["payments_volume_quarters"], volumes["nominal_payments_volume_usd_b"]))
        lines = self.source["revenue_lines_usd_m"]
        quarters = lines["quarters"][lines["quarters"].index("Q1 2016"):]
        self.assertEqual(chart["xlabels"], [compact_period(q) for q in quarters])
        order = {q: i for i, q in enumerate(lines["quarters"])}
        for q, drawn in zip(quarters, chart["values"]):
            prior = lines["quarters"][order[q] - 1] if order[q] else None
            expected = lines["service"][order[q]] / volume[prior] * 10
            with self.subTest(quarter=q):
                self.assertAlmostEqual(drawn, expected, places=5)
        self.assertEqual(chart["kind"], "gs_line")
        self.assertIn(f"本季 {chart['values'][-1]:.2f} 个基点", chart["title"])
        self.assertIn(f"{len(quarters)} 个季度", chart["title"])

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
        self.assertEqual(entry["latest_label"], self.source["latest"]["period"])
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


# ── rolling the series, the way a quarter's roll does ────────────────────────
QUARTER_END = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}
RELEASE_DAY = {1: "04-28", 2: "07-28", 3: "10-27", 4: "01-28"}
QUARTER_BLOCKS = ("followup_closure", "tracked_metric_verdicts", "next_kpi", "quarter_one_offs",
                  "quarter_story", "printed_growth_pct")
LONG_BLOCKS = ("revenue_lines_usd_m", "geography_usd_m", "capital_allocation_usd_m", "litigation",
               "per_share", "income_long_usd_m")
PLACEHOLDER = r"\{[a-z_]+\}"


def fiscal_of(label: str) -> str:
    quarter, year = int(label[1]), int(label[-4:])
    return f"FY{year + 1}Q1" if quarter == 4 else f"FY{year}Q{quarter + 1}"


def window_lists(s: dict) -> list[tuple[dict, str]]:
    """The eight-quarter window: the page's own axis and the figures on it."""
    out = [(s, "periods"), (s, "period_ends"), (s, "fiscal_labels")]
    return out + [(s["financials"], key) for key in s["financials"]]


def long_lists(s: dict, fiscal: str = "") -> list[tuple[dict, str]]:
    """Every list that runs along one of the long quarterly axes; the per-share
    record has no row for a fiscal fourth quarter."""
    out = []
    for name in LONG_BLOCKS:
        if name == "per_share" and fiscal.endswith("Q4"):
            continue
        block = s[name]
        n = len(block["quarters"])
        out += [(block, key) for key, values in block.items() if isinstance(values, list) and len(values) == n]
    volumes = s["operating_volumes"]
    for axis in ("payments_volume_quarters", "processed_transactions_quarters"):
        n = len(volumes[axis])
        keys = ([axis, "nominal_payments_volume_usd_b", "us_usd_b", "international_usd_b"]
                if axis.startswith("payments") else [axis, "processed_transactions_m"])
        out += [(volumes, key) for key in keys if len(volumes[key]) == n]
    return out


def rolled_back(staging: dict) -> dict:
    """The series one quarter earlier, on the Q1 2026 figures the file already
    holds: the FY2026 Q2 release (0001403161-26-000077, 2026-04-28) and 10-Q
    (0001403161-26-000079). No note was written for that quarter, so it has no
    stamped blocks."""
    s = copy.deepcopy(staging)
    for container, key in window_lists(s) + long_lists(s, staging["fiscal_labels"][-1]):
        container[key] = container[key][:-1]
    for key in ("_checks",) + QUARTER_BLOCKS:
        s.pop(key, None)
    s["latest"] = {"period": s["periods"][-1], "release_date": "2026-04-28",
                   "analysis_date": "2026-04-30", "audit_status": "unaudited"}
    base = "https://www.sec.gov/Archives/edgar/data/1403161/"
    s["sources"] = ([{"label": "Visa FY2026 Q2 业绩新闻稿（8-K EX-99.1）",
                      "url": base + "000140316126000077/q22026earningsrelease.htm"},
                     {"label": "Visa 截至 2026-03-31 的 10-Q（收入分解附注、法律事项附注、现金流量表）",
                      "url": base + "000140316126000079/v-20260331.htm"}]
                    + [src for src in s["sources"]
                       if not src["label"].startswith("Visa FY2026 Q3") and "10-Q" not in src["label"]])
    return s


def rolled_forward(staging: dict) -> dict:
    """One quarter later with made-up figures that keep the identities: the
    lines grow 2%, the incentive rate is 28.9%, operating expenses grow 2%."""
    s = copy.deepcopy(staging)
    last = s["periods"][-1]
    quarter, year = int(last[1]), int(last[-4:])
    quarter, year = (1, year + 1) if quarter == 4 else (quarter + 1, year)
    label, end = f"Q{quarter} {year}", f"{year}-{QUARTER_END[quarter]}"
    fiscal = fiscal_of(label)
    release = f"{year + 1 if quarter == 4 else year}-{RELEASE_DAY[quarter]}"

    def grown(values: list) -> object:
        return None if values[-1] is None else round(values[-1] * 1.02, 4)

    for container, key in window_lists(s):
        values = container[key][1:]
        values.append({"periods": label, "period_ends": end, "fiscal_labels": fiscal}.get(key)
                      or grown(container[key]))
        container[key] = values
    for container, key in long_lists(s, fiscal):
        values = container[key]
        if key in ("quarters", "processed_transactions_quarters"):
            values.append(label)
        elif key == "payments_volume_quarters":
            values.append(last)
        elif key == "period_ends":
            values.append(end)
        elif key == "fiscal_labels":
            values.append(fiscal)
        elif key == "basis" and container is s["revenue_lines_usd_m"]:
            values.append("fy_minus_9m" if fiscal.endswith("Q4") else "filed_3m")
        elif key == "basis":
            values.append("filed_3m" if fiscal.endswith("Q1") else "ytd_difference")
        else:
            values.append(grown(values))
    lines = s["revenue_lines_usd_m"]
    gross = sum(lines[key][-1] for key in ("service", "data_processing", "international_transaction", "other"))
    lines["gross_revenue"][-1] = gross
    lines["client_incentives"][-1] = round(-gross * 0.289, 4)
    lines["net_revenue"][-1] = gross + lines["client_incentives"][-1]
    lines["incentive_rate_pct"][-1] = -lines["client_incentives"][-1] / gross * 100
    fin = s["financials"]
    for key, line in (("net_revenue_usd_m", "net_revenue"), ("gross_revenue_usd_m", "gross_revenue"),
                      ("client_incentives_usd_m", "client_incentives"),
                      ("incentive_rate_pct", "incentive_rate_pct")):
        fin[key][-1] = lines[line][-1]
    fin["operating_income_usd_m"][-1] = fin["net_revenue_usd_m"][-1] - fin["total_opex_usd_m"][-1]
    income = s["income_long_usd_m"]
    income["total_opex_usd_m"][-1] = fin["total_opex_usd_m"][-1]
    income["operating_income_usd_m"][-1] = fin["operating_income_usd_m"][-1]
    geo = s["geography_usd_m"]
    geo["net_revenue"][-1] = lines["net_revenue"][-1]
    geo["international"][-1] = geo["net_revenue"][-1] - geo["us"][-1]
    for key in ("_checks",) + QUARTER_BLOCKS:
        s.pop(key, None)
    s["latest"] = {"period": label, "release_date": release, "analysis_date": release,
                   "audit_status": "unaudited"}
    s["sources"] = ([{"label": f"Visa {fiscal[:6]} {fiscal[6:]} 业绩新闻稿（8-K EX-99.1）",
                      "url": f"https://www.sec.gov/Archives/edgar/data/1403161/next{fiscal}/release.htm"}]
                    + [src for src in s["sources"]
                       if "业绩新闻稿（8-K" not in src["label"] and "10-Q" not in src["label"]])
    return s


class VChecksTest(unittest.TestCase):
    """The page's quarter against a record keyed separately from the filings.

    `_checks` is typed once per quarter from the earnings 8-K and the 10-Q, with
    the place in each document every figure was read from; the builder never
    reads it (asserted in `test_data_only_roll`). The release prints growth as
    whole percentages, so computed growth is compared at that precision -- and
    where the two land on different sides of a half, the page prints the
    company's figure.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = staged()
        cls.checks = cls.staging["_checks"]
        cls.payload = build_payload(cls.staging)
        cls.exhibits = exhibits_of(cls.payload)
        cls.lines = cls.staging["revenue_lines_usd_m"]

    def test_the_page_names_the_checked_quarter(self) -> None:
        c = self.checks
        self.assertIn(f"{c['period']} 季报仪表盘", self.payload["title"])
        self.assertIn(f"截至 {c['period_end']}", self.payload["subtitle"])
        self.assertIn(f"发布 {c['release_date']}", self.payload["subtitle"])
        self.assertIn(f"即公司所称 {c['fiscal_label'][:6]} {c['fiscal_label'][6:]}", self.payload["subtitle"])
        self.assertEqual(self.staging["fiscal_labels"][-1], c["fiscal_label"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        c, lines, fin = self.checks, self.lines, self.staging["financials"]
        for key, value in c["revenue_usd_m"].items():
            with self.subTest(key=key):
                self.assertEqual(lines[key][-1], value)
        self.assertEqual(fin["net_revenue_usd_m"][-1], c["revenue_usd_m"]["net_revenue"])
        self.assertEqual(fin["client_incentives_usd_m"][-1], c["revenue_usd_m"]["client_incentives"])
        for key, check in (("total_opex_usd_m", "total_opex_usd_m"),
                           ("litigation_provision_usd_m", "litigation_provision_usd_m"),
                           ("operating_income_usd_m", "operating_income_usd_m"),
                           ("net_income_usd_m", "net_income_usd_m")):
            with self.subTest(key=key):
                self.assertEqual(fin[key][-1], c[check])
        geo = self.staging["geography_usd_m"]
        for key, value in c["net_revenue_by_geography_usd_m"].items():
            self.assertEqual(geo[key][-1], value, key)
        litigation = self.staging["litigation"]
        for key, check in (("escrow_usd_m", "escrow"), ("us_covered_litigation_usd_m", "us_covered"),
                           ("accrued_litigation_total_usd_m", "accrued_total")):
            self.assertEqual(litigation[key][-1], c["litigation_usd_m"][check], key)
        per_share = self.staging["per_share"]
        self.assertEqual(per_share["quarters"][-1], c["period"])
        self.assertEqual(per_share["class_a_diluted_eps_usd"][-1], c["diluted_eps_usd"])
        volumes = self.staging["operating_volumes"]
        prior = c["nominal_payments_volume_prior_quarter_usd_b"]
        self.assertEqual(volumes["payments_volume_quarters"][-1], prior["period"])
        self.assertEqual(volumes["nominal_payments_volume_usd_b"][-1], prior["value"])
        self.assertEqual(self.staging["quarter_one_offs"]["severance_usd_m"],
                         c["special_items_usd_m"]["severance"])

    def test_computed_growth_rounds_to_the_printed_growth(self) -> None:
        """Other printed 45% where 1,496 ÷ 1,028 is 45.5%: the release divides
        unrounded figures. That line's title carries the company's 45%."""
        printed = self.checks["growth_printed_pct"]
        page_block = self.staging.get("printed_growth_pct", {})
        title = next(ex for ex in self.exhibits if ex["title"].startswith("四条毛收入线的同比增速"))["title"]
        for name, key in v.LINE_KEYS:
            computed = v.pct_change(self.lines[key][-1], self.lines[key][-5])
            with self.subTest(key=key):
                self.assertIn(f"{name} {printed[key]:+d}%", title)
                if v.whole_percent(computed) != printed[key]:
                    self.assertEqual(page_block.get(key), printed[key])
        for key in ("client_incentives", "net_revenue"):
            computed = v.pct_change(self.lines[key][-1], self.lines[key][-5])
            self.assertEqual(v.whole_percent(computed), printed[key], key)
        opex = self.staging["financials"]["total_opex_usd_m"]
        self.assertEqual(v.whole_percent(v.pct_change(opex[-1], opex[-5])), printed["total_opex"])

    def test_the_page_s_printed_rates_are_the_release_s(self) -> None:
        block = self.staging["printed_growth_pct"]
        for key, value in block.items():
            if key != "period":
                self.assertEqual(value, self.checks["growth_printed_pct"][key], key)

    def test_the_prior_year_quarter_is_the_series_one(self) -> None:
        prior, fin = self.checks["prior_year"], self.staging["financials"]
        self.assertEqual(self.staging["periods"][-5], prior["period"])
        self.assertEqual(self.lines["quarters"][-5], prior["period"])
        self.assertEqual(fin["net_revenue_usd_m"][-5], prior["net_revenue_usd_m"])
        self.assertEqual(fin["total_opex_usd_m"][-5], prior["total_opex_usd_m"])
        self.assertEqual(fin["litigation_provision_usd_m"][-5], prior["litigation_provision_usd_m"])
        self.assertEqual(self.lines["international_transaction"][-5], prior["international_transaction_usd_m"])
        self.assertEqual(self.lines["client_incentives"][-5], prior["client_incentives_usd_m"])

    def test_the_year_to_date_cash_flow_is_the_fiscal_quarters_summed(self) -> None:
        """Every quarter after a fiscal first is a difference of two filed
        year-to-date columns, so the quarters of this fiscal year must add back
        to the column this quarter's filing printed."""
        ytd = self.checks["cash_flow_year_to_date_usd_m"]
        n = ytd["months"] // 3
        self.assertEqual(int(self.checks["fiscal_label"][-1]), n)
        capital = self.staging["capital_allocation_usd_m"]
        self.assertEqual(capital["quarters"][-1], self.checks["period"])
        self.assertEqual(capital["basis"][-n], "filed_3m")
        for key, check in (("operating_cash_flow", "operating"), ("capex", "capex"),
                           ("buyback", "buyback"), ("dividends", "dividends")):
            self.assertAlmostEqual(sum(capital[key][-n:]), ytd[check], places=6, msg=key)

    def test_the_threshold_readings_match_the_filings(self) -> None:
        """Each current value, recomputed from `_checks` and compared at the
        precision the audit table prints -- not through the builder's own
        reader, which would only be checking itself."""
        c, prior = self.checks, self.checks["prior_year"]
        r = c["revenue_usd_m"]
        gross = sum(r[key] for key in ("service", "data_processing", "international_transaction", "other"))
        ytd, capital = c["cash_flow_year_to_date_usd_m"], self.staging["capital_allocation_usd_m"]
        n = ytd["months"] // 3
        quarter = {key: ytd[check] - sum(capital[series][-n:-1])
                   for key, check, series in (("o", "operating", "operating_cash_flow"), ("c", "capex", "capex"),
                                              ("b", "buyback", "buyback"), ("d", "dividends", "dividends"))}
        expected = {
            "revenue_lines_usd_m.incentive_rate_pct": -r["client_incentives"] / gross * 100,
            "yoy:revenue_lines_usd_m.international_transaction":
                (r["international_transaction"] / prior["international_transaction_usd_m"] - 1) * 100,
            "escrow_surplus": c["litigation_usd_m"]["escrow"] - c["litigation_usd_m"]["us_covered"],
            "yoy:financials.net_revenue_usd_m": (r["net_revenue"] / prior["net_revenue_usd_m"] - 1) * 100,
            "payout_to_fcf": -(quarter["b"] + quarter["d"]) / (quarter["o"] + quarter["c"]) * 100,
        }
        table = next(t for t in self.payload["tables"] if t["title"].startswith("下季阈值与当前值"))
        rows = {row[0]: row for row in table["rows"]}
        bars = next(ex for ex in self.exhibits if ex["kind"] == "diverging_bars")
        bar = dict(zip(bars["xlabels"], bars["values"]))
        for entry in self.staging["next_kpi"]["quantified"]:
            with self.subTest(metric=entry["metric"]):
                self.assertIn(entry["reads"], expected,
                              "a new kind of reading needs its figure in `_checks` and here")
                value = expected[entry["reads"]]
                room = headroom(entry["direction"], entry["threshold"], value)
                self.assertEqual(rows[entry["metric"]][3], unit_text(entry["unit"], value))
                self.assertEqual(rows[entry["metric"]][4], f"{room:+.1f}%")
                self.assertEqual(bar[entry["metric"]], round(room, 1))

    def test_the_page_prints_the_checked_figures(self) -> None:
        c = self.checks
        r = c["revenue_usd_m"]
        gross = sum(r[key] for key in ("service", "data_processing", "international_transaction", "other"))
        rate = -r["client_incentives"] / gross * 100
        self.assertIn(f"净收入 US${r['net_revenue']:,.0f}M", self.payload["headline"])
        self.assertIn(f"{rate:.2f}%", self.payload["headline"])
        escrow, covered = c["litigation_usd_m"]["escrow"], c["litigation_usd_m"]["us_covered"]
        chart = next(ex for ex in self.exhibits if ex["title"].startswith("托管账户对它真正负责的那笔负债"))
        self.assertIn(f"本季 US${escrow:,.0f}M vs US${covered:,.0f}M", chart["title"])
        wedge = next(ex for ex in self.exhibits if ex["title"].startswith("本季 GAAP 营业费用"))
        self.assertIn(f"US${c['total_opex_usd_m']:,.0f}M", wedge["title"])
        self.assertIn(f"遣散费 US${c['special_items_usd_m']['severance']:,.0f}M", wedge["note"])
        self.assertIn(f"诉讼计提 US${c['litigation_provision_usd_m']:,.0f}M", wedge["note"])
        margin = next(ex for ex in self.exhibits if ex["title"].startswith("GAAP 营业利润率"))
        self.assertIn(f"GAAP 营业利润率 {c['operating_income_usd_m'] / r['net_revenue'] * 100:.1f}%",
                      margin["title"])
        self.assertEqual(v.headline_metrics(self.staging),
                         [f"Net revenue ${r['net_revenue'] / 1000:.1f}B", f"激励率 {rate:.1f}%",
                          f"GAAP OpM {c['operating_income_usd_m'] / r['net_revenue'] * 100:.1f}%"])
        volume = c["nominal_payments_volume_prior_quarter_usd_b"]
        self.assertIn(f"本季 10-Q 印的是 {volume['period']} 那一季的 US${volume['value']:,.0f}B",
                      " ".join(self.payload["notes"]))

    def test_the_service_yield_is_the_checked_figures_divided(self) -> None:
        c = self.checks
        volume = c["nominal_payments_volume_prior_quarter_usd_b"]
        bps = c["revenue_usd_m"]["service"] / volume["value"] * 10
        chart = next(ex for ex in self.exhibits if ex["title"].startswith("Service revenue ÷ 上一季名义支付额"))
        self.assertIn(f"本季 {bps:.2f} 个基点", chart["title"])
        self.assertAlmostEqual(chart["values"][-1], bps, places=5)
        self.assertIn(f"acc {self.staging['_checks']['source'].split('10-Q（acc ')[1][:20]}",
                      self.staging["operating_volumes"]["nominal_payments_volume_source"][volume["period"]])

    def test_the_source_line_links_this_quarter_s_release(self) -> None:
        accession = re.search(r"acc (\d{10})-(\d{2})-(\d{6})", self.checks["source"]).groups()
        self.assertIn("".join(accession), self.payload["source_url"])
        self.assertIn(self.payload["source_url"], [src["url"] for src in self.staging["sources"]])
        self.assertTrue(all(src["url"].startswith("https://") for src in self.staging["sources"]))


class VRollTest(unittest.TestCase):
    """What a roll can change without touching the builder."""

    STORY_ONLY = ("被证伪的那条是把商业支付收入的加速当成结构性变化", "稳定币结算 run rate",
                  "阈值取的是本季再向上一个季度级别的台阶", "剔除两笔一次性后为",
                  "员工人数与裁员规模（本季电话会未量化", "公司按未取整的数印的是")

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
        bare["sources"] = [src for src in bare["sources"] if "业绩新闻稿（8-K" not in src["label"]]
        self.assertLess(len(bare["sources"]), len(self.s["sources"]))
        with self.assertRaisesRegex(ValueError, "sources"):
            build_payload(bare)

    def test_a_printed_rate_far_from_the_series_stops_the_build(self) -> None:
        typo = copy.deepcopy(self.s)
        typo["printed_growth_pct"]["other"] = 54
        with self.assertRaisesRegex(ValueError, "printed_growth_pct"):
            build_payload(typo)

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
        self.assertFalse(any(ex["kind"] == "bars_labeled" for ex in sections["settled"]["exhibits"]))
        self.assertNotIn("先结清上一份笔记留下的问题", sections["settled"]["description"])
        self.assertNotIn("见 Exhibit", text)
        self.assertIn("GAAP 营业利润率，", sections["quarter_highlights"]["description"])
        self.assertFalse(any(t["title"].startswith("下季阈值") for t in payload["tables"]))
        numbers = [ex["n"] for ex in exhibits_of(payload)]
        self.assertEqual(numbers, list(range(2, 2 + len(numbers))))
        self.assertNotRegex(text, PLACEHOLDER)
        self.assertNotRegex(text, r"\{EX_[A-Z_]+\}")

    def test_the_quarter_before_builds_from_the_series_alone(self) -> None:
        rolled = rolled_back(self.s)
        payload = build_payload(rolled)
        label = rolled["periods"][-1]
        self.assertEqual(label, "Q1 2026")
        self.assertEqual(payload["latest"]["disclosed_period_label"], label)
        self.assertIn(f"{label} 季报仪表盘", payload["title"])
        self.assertIn("本页 Q1 2026 即公司所称 FY2026 Q2", payload["subtitle"])
        self.assertIn("000140316126000077/q22026earningsrelease.htm", payload["source"])
        self.assertIn("与截至 2026-03-31 的 10-Q", payload["source"])
        text = own_text(payload)
        for token in (self.s["periods"][-1], "FY2026 Q3", self.s["latest"]["release_date"],
                      "Q2'26", "US$3,728B"):
            self.assertNotIn(token, text)
        self.assertNotRegex(text, PLACEHOLDER)
        self.assertNotRegex(text, r"\{EX_[A-Z_]+\}")
        # the counts move with the axis
        window = len(rolled["revenue_lines_usd_m"]["quarters"]) - \
            rolled["revenue_lines_usd_m"]["quarters"].index("Q1 2016")
        self.assertEqual(window, 41)
        self.assertIn(f"{cn_count(window)}个季度里只有一段负增长", text)
        self.assertIn("本季 10-Q 印的是 Q4 2025 那一季的 US$3,868B", text)
        self.assertIn(f"起的全部 {len(rolled['revenue_lines_usd_m']['quarters']) + 1} 份新闻稿", text)

    def test_the_quarters_after_build_from_the_series_alone(self) -> None:
        s = self.s
        texts = []
        for _ in range(2):
            s = rolled_forward(s)
            payload = build_payload(s)
            text = own_text(payload)
            texts.append((s, payload, text))
            self.assertIn(f"{s['periods'][-1]} 季报仪表盘", payload["title"])
            self.assertEqual(len(s["periods"]), 8)
            self.assertNotRegex(text, PLACEHOLDER)
            self.assertNotRegex(text, r"\{EX_[A-Z_]+\}")
            self.assertNotRegex(text, r"US\$[-−]")
        (q3, p3, t3), (q4, p4, t4) = texts
        # a fiscal fourth quarter has no 10-Q, so nothing on the page may quote one
        self.assertIn("本页 Q3 2026 即公司所称 FY2026 Q4", p3["subtitle"])
        self.assertNotIn("本季 10-Q 印的是", t3)
        self.assertNotIn("10-Q", p3["source"])
        self.assertIn("本页 Q4 2026 即公司所称 FY2027 Q1", p4["subtitle"])
        self.assertIn("本季 10-Q 印的是 Q3 2026 那一季的", t4)
        # the open year closed: FY2026 is a full year now and counts in the ramp
        self.assertIn("FY2013–FY2026 每一年都比上一年高", t4)
        self.assertIn("四十四个季度里只有一段负增长", t4)
        self.assertIn(f"起的全部 {len(q4['revenue_lines_usd_m']['quarters']) + 1} 份新闻稿", t4)
        self.assertIn("而同一个比率在其后七年里继续往上走", t4)

    def test_the_spans_in_years_move_with_the_window(self) -> None:
        """「十年的窗口」「十年抬高了」 were typed; the 2016 window turns eleven years
        long three quarters from now."""
        s = self.s
        for _ in range(3):
            s = rolled_forward(s)
        s["next_kpi"] = dict(self.s["next_kpi"], period=s["periods"][-1])
        text = own_text(build_payload(s))
        self.assertIn("<b>十一年的窗口里这四条从没有同时为负过</b>", text)
        self.assertIn("十一年抬高了约", text)
        self.assertNotIn("十年抬高了", text)


class VFindingsTest(unittest.TestCase):
    """Every judgement on the page says what the series says, both ways.

    Each case forces the series into a state where a finding is true, then into
    one where it is false, and checks that the words follow. Forcing rather than
    flipping today's data keeps these valid after a roll.
    """

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
        return s["revenue_lines_usd_m"]["quarters"].index(label)

    def test_the_headline_names_every_range_the_record_holds(self) -> None:
        """「它恰好是 Visa 唯一一个在申报文件里给过数字区间的前瞻指标」 stood
        beside an effective tax rate range the same releases printed."""
        self.assertNotIn("唯一一个在申报文件里给过数字区间", self.clean)
        self.assertIn("FY2013–FY2020 每个财年开局的申报文件里给过它的数字区间"
                      "（有效税率也给过区间，例如 FY2020 的 19%–19.5%）", self.clean)

        def no_other_ranges(s):
            s["incentive_guidance"]["other_numeric_ranges"] = []

        bare = self.page(no_other_ranges)
        self.assertNotIn("有效税率也给过区间", bare)
        self.assertIn("给过它的数字区间 —— 给到 FY2020 为止", bare)

    def test_the_record_counts_follow_the_entries(self) -> None:
        """The brief said 「FY2017–FY2020 给过四次、三次低于下限」 after the record
        had been extended to eight years."""
        self.assertIn("FY2013–FY2020 公司在申报文件里给过八次激励率区间，五次实际低于下限（少返给客户）。", self.clean)
        self.assertIn("八年里五年实际低于指引下限、没有一年高于上限", self.clean)
        self.assertIn("公司曾经连续八年在申报文件里给出", self.clean)
        self.assertIn("Visa 申报文件里的客户激励率指引记录，FY2013–FY2020", self.clean)

        def one_above(s):
            entry = s["incentive_guidance"]["entries"][1]
            entry["actual_pct"] = entry["hi"] + 0.4

        above = self.page(one_above)
        self.assertIn("五次实际低于下限（少返给客户）、一次高于上限。", above)
        self.assertIn("八年里五年实际低于指引下限、一年高于上限", above)
        self.assertNotIn("从没有超发过激励", above)

    def test_the_net_revenue_note_names_its_one_negative_run(self) -> None:
        """「2020 财年的四个季度，最深一格是 2020 年 6 月止季的 −17.3%」: the run
        is Q2 2020–Q1 2021 (FY2020 Q3–FY2021 Q2) and the trough is −17.2%."""
        self.assertIn("<b>四十二个季度里只有一段负增长</b>：Q2 2020 到 Q1 2021 这四个季度"
                      "（公司 FY2020 Q3 至 FY2021 Q2），最深一格是 Q2 2020 的 −17.2%", self.clean)

        def second_run(s):
            net = s["revenue_lines_usd_m"]["net_revenue"]
            i = self.at(s, "Q1 2017")
            net[i] = net[i - 4] * 0.9

        self.assertNotIn("只有一段负增长", self.page(second_run))

    def test_the_incentive_window_note_reads_its_own_window(self) -> None:
        """「近十三季这条线在 27%–29% 之间来回」 captioned a 42-quarter chart
        that runs from 17.87%."""
        self.assertIn("这张图画的是 42 季（Q1'16 起），从 17.87% 走到 28.69%", self.clean)
        self.assertIn("本季 28.69% 是窗口内最高", self.clean)
        note = next(ex["note"] for ex in exhibits_of(build_payload(copy.deepcopy(self.s)))
                    if ex["title"].startswith("激励率本季"))
        self.assertNotIn("近十三季", note)
        self.assertNotIn("十三年的斜坡", note)

        def earlier_peak(s):
            s["revenue_lines_usd_m"]["incentive_rate_pct"][self.at(s, "Q1 2024")] = 30.0

        self.assertNotIn("是窗口内最高", self.page(earlier_peak))

    def test_the_lines_note_counts_the_negative_lines(self) -> None:
        """「十年的窗口里这四条同时为负过一次」: at most three were ever negative
        together (Q2 2020), Data processing never went below zero."""
        self.assertIn("<b>十年的窗口里这四条从没有同时为负过</b>：最多是 Q2 2020 的三条，"
                      "最低一格是 International transaction 在 Q2 2020 的 -44%", self.clean)

        def all_four(s):
            service = s["revenue_lines_usd_m"]["service"]
            i = self.at(s, "Q2 2020")
            service[i] = service[i - 4] * 0.95

        forced = self.page(all_four)
        self.assertIn("<b>十年的窗口里这四条同时为负过</b>", forced)
        self.assertNotIn("从没有同时为负过", forced)

    def test_the_ranking_sentence_counts_the_bottom_quarters(self) -> None:
        """「2016 到 2019 年它长期在最下面」: 6 of the 8 quarters of 2016-2017, and
        in 2018-2019 Other was at the bottom in none."""
        self.assertIn("今天 Other 在最上面，而 2016—2017 年的 8 个季度里它有 6 个在最下面。", self.clean)

        def other_fast_early(s):
            other = s["revenue_lines_usd_m"]["other"]
            for label in ("Q1 2016", "Q2 2016", "Q3 2016", "Q4 2016", "Q1 2017", "Q2 2017"):
                i = self.at(s, label)
                other[i] = other[i - 4] * 1.5

        self.assertNotIn("个在最下面", self.page(other_fast_early))

    def test_the_lines_title_prints_the_release_s_rates(self) -> None:
        self.assertIn("本季分道扬镳：Other +45%、Data processing +17%、Service +14%、"
                      "International transaction +6%", self.clean)
        self.assertIn("Other 本季算出来是 +45.5%，公司按未取整的数印的是 +45%", self.clean)

        def no_block(s):
            del s["printed_growth_pct"]

        bare = self.page(no_block)
        self.assertIn("Other +46%", bare)
        self.assertNotIn("公司按未取整的数印的是", bare)

        def converge(s):
            del s["printed_growth_pct"]
            lines = s["revenue_lines_usd_m"]
            for _, key in v.LINE_KEYS:
                lines[key][-1] = lines[key][-5] * 1.10

        converged = self.page(converge)
        self.assertNotIn("分道扬镳", converged)
        self.assertIn("四条毛收入线的同比增速：", converged)

    def test_the_margin_note_names_the_framework_loss_only_at_its_quarter(self) -> None:
        """「那一季计提了收购 Visa Europe 相关的诉讼准备」: the 10-Q line is a
        US$1,877M Visa Europe Framework Agreement loss, not a litigation provision."""
        self.assertIn("那一季记了一笔 US$1,877M 的 Visa Europe Framework Agreement loss", self.clean)
        self.assertNotIn("诉讼准备，把营业利润", self.clean)
        self.assertIn("除那一格之外，最低的几格是 Q2 2018（55.1%）、Q1 2025（56.6%）、Q2 2022（57.0%）", self.clean)

        def no_loss(s):
            income = s["income_long_usd_m"]
            i = income["quarters"].index("Q2 2016")
            income["operating_income_usd_m"][i] *= 5

        forced = self.page(no_loss)
        self.assertNotIn("Framework Agreement loss", forced)
        self.assertIn("最低一格是 Q2 2018 的 55.1%", forced)

    def test_the_escrow_note_counts_the_shortfalls(self) -> None:
        """「42 季里只有 0 季出现过缺口」 and 「US$-386M 的「缺口」」."""
        self.assertIn("42 季里一次缺口都没有出现过", self.clean)
        self.assertIn("会得到 US$386M 的「缺口」", self.clean)

        def one_short(s):
            lit = s["litigation"]
            i = lit["quarters"].index("Q1 2019")
            lit["escrow_usd_m"][i] = lit["us_covered_litigation_usd_m"][i] - 10

        self.assertIn("42 季里有 1 季出现过缺口", self.page(one_short))

    def test_the_escrow_words_follow_the_sign(self) -> None:
        self.assertIn("<span>更正</span><b>托管账户没有欠资</b>", self.clean)
        self.assertIn("<h4>本季三条主线</h4>", self.clean)

        def short_now(s):
            lit = s["litigation"]
            lit["escrow_usd_m"][-1] = lit["us_covered_litigation_usd_m"][-1] - 40

        short = self.page(short_now)
        self.assertIn("缺口 US$40M", short)
        self.assertNotIn("托管账户没有欠资", short)
        self.assertIn("<h4>本季两条主线</h4>", short)

    def test_the_incentive_threshold_note_reads_the_fiscal_years(self) -> None:
        """「四十二个季度里这条线一路向上」 over a line with 15 quarter-on-quarter falls."""
        self.assertIn("<b>四十二个季度里这条线的方向是向上的</b>：41 次环比变化里有 15 次是下降，"
                      "但按财年算每一年都比上一年高", self.clean)
        self.assertIn("十年抬高了约 11 个百分点", self.clean)
        self.assertNotIn("一路向上", self.clean)

        def fy2019_dips(s):
            lines = s["revenue_lines_usd_m"]
            for i, label in enumerate(lines["fiscal_labels"]):
                if label.startswith("FY2019"):
                    lines["client_incentives"][i] *= 0.8
                    lines["incentive_rate_pct"][i] = -lines["client_incentives"][i] / lines["gross_revenue"][i] * 100

        dipped = self.page(fy2019_dips)
        self.assertNotIn("的方向是向上的", dipped)
        self.assertNotIn("单向斜坡", dipped)
        self.assertIn("拉到 55 季才看得出它的长期走向", dipped)

    def test_the_intl_threshold_note_reads_its_runs(self) -> None:
        """「2020 财年那四个季度整条线深度为负」: FY2020 Q1 was +2.1%; the negative
        run is Q2 2020–Q1 2021, inside a five-quarter run below +4%."""
        self.assertIn("Q1 2020 到 Q1 2021（公司 FY2020 Q2 至 FY2021 Q2）连续 5 季在阈值之下，"
                      "其中 Q2 2020 到 Q1 2021 这 4 季为负、最低 -44.3%；Q1 2019（+2.5%）也在阈值之下。",
                      self.clean)
        self.assertIn("它是否还能守住 +4%", self.clean)

        def q1_2019_fine(s):
            intl = s["revenue_lines_usd_m"]["international_transaction"]
            intl[self.at(s, "Q1 2018")] *= 0.97

        fine = self.page(q1_2019_fine)
        self.assertNotIn("Q1 2019（+2.5%）", fine)
        self.assertIn("这 4 季为负、最低 -44.3%。", fine)

    def test_the_mix_note_reads_the_recovery_and_the_peak(self) -> None:
        """「疫情前的约 24%… 至今没有回到 2019 年的水平」 (it was 25.9% and came back
        to 27.0% in 2022Q3); 「Data processing 则一路向上」 (it peaked in FY2021)."""
        self.assertIn("从疫情前（2019Q4）的 25.9% 掉到 17.4%；它在 2022Q3 回到过 27.0%，"
                      "在 2019 年的区间之内，本季是 23.6%", self.clean)
        self.assertIn("Data processing 按财年算在 FY2021 升到最高的 39.4%，之后回落，FY2025 是 35.9%", self.clean)

        def never_back(s):
            lines = s["revenue_lines_usd_m"]
            for i in range(self.at(s, "Q1 2021"), len(lines["quarters"])):
                lines["international_transaction"][i] *= 0.6

        self.assertIn("至今没有回到 2019 年的水平", self.page(never_back))

        def dp_climbs(s):
            del s["printed_growth_pct"]
            lines = s["revenue_lines_usd_m"]
            for i, label in enumerate(lines["fiscal_labels"]):
                share = 0.30 + 0.005 * (int(label[2:6]) - 2013)
                lines["data_processing"][i] = lines["gross_revenue"][i] * share

        self.assertIn("Data processing 则一路向上", self.page(dp_climbs))

    def test_the_mix_title_words_follow_the_shares(self) -> None:
        self.assertIn("Data processing 从 32.8% 升到 37.0%，Service 从 38.2% 降到 30.2%", self.clean)

        def dp_falls(s):
            del s["printed_growth_pct"]
            lines = s["revenue_lines_usd_m"]
            lines["data_processing"][-1] *= 0.7

        self.assertIn("Data processing 从 32.8% 降到", self.page(dp_falls))

    def test_the_long_rate_note_prints_one_way_only_when_every_year_rises(self) -> None:
        self.assertIn("走了十三年的单向斜坡（按财年算，FY2013–FY2025 每一年都比上一年高）", self.clean)

    def test_the_deviation_note_keeps_the_rate_rising_only_when_it_did(self) -> None:
        self.assertIn("而同一个比率在其后六年里继续往上走", self.clean)

        def fell_back(s):
            lines = s["revenue_lines_usd_m"]
            lines["incentive_rate_pct"][-1] = 20.0

        self.assertIn("没有再高过 FY2020 的", self.page(fell_back))

    def test_the_payments_volume_clause_needs_the_aligned_quarter(self) -> None:
        """「公司只披露支付额的同比百分比，从不按季披露绝对金额」: the 10-Q's
        MD&A prints the prior quarter's nominal payments volume in dollars."""
        self.assertIn("本季 10-Q 印的是 Q1 2026 那一季的 US$3,728B", self.clean)
        self.assertIn("本季对的是 Q1 2026 那一季的 US$3,728B", self.clean)
        self.assertNotIn("从不按季披露", self.clean)

        def misaligned(s):
            volumes = s["operating_volumes"]
            for key in ("payments_volume_quarters", "nominal_payments_volume_usd_b", "us_usd_b",
                        "international_usd_b"):
                volumes[key] = volumes[key][:-1]

        forced = self.page(misaligned)
        self.assertNotIn("那一季的 US$", forced)

    def test_the_service_yield_words_follow_the_record(self) -> None:
        """「42 个季度里最高」「已高过并入前」 are claims about the whole line."""
        self.assertIn("本季 13.20 个基点，42 个季度里最高", self.clean)
        self.assertIn("比率从 13.05 掉到 9.67", self.clean)
        self.assertIn("此后回升到本季的 13.20，已高过并入前", self.clean)

        def volume_rose(s):
            volumes = s["operating_volumes"]
            volumes["nominal_payments_volume_usd_b"][-1] = round(volumes["nominal_payments_volume_usd_b"][-1] * 1.08)

        fell = self.page(volume_rose)
        self.assertNotIn("个季度里最高", fell)
        self.assertRegex(fell, r"本季 12\.\d\d 个基点（42 个季度区间 9\.67–13\.05）")
        self.assertIn("仍低于并入前", fell)
        self.assertNotIn("已高过并入前", fell)

    def test_the_yield_chart_stops_where_the_volume_does(self) -> None:
        """A fiscal fourth quarter is released weeks before the 10-K that
        carries April-June volume: the chart then ends a quarter early and
        says which quarter it is, instead of calling it this quarter."""

        def no_volume_yet(s):
            volumes = s["operating_volumes"]
            for key in ("payments_volume_quarters", "nominal_payments_volume_usd_b", "us_usd_b",
                        "international_usd_b"):
                volumes[key] = volumes[key][:-1]

        text = self.page(no_volume_yet)
        self.assertIn("Service revenue ÷ 上一季名义支付额：Q1 2026 12.88 个基点", text)

        def hole(s):
            volumes = s["operating_volumes"]
            i = volumes["payments_volume_quarters"].index("Q2 2020")
            for key in ("payments_volume_quarters", "nominal_payments_volume_usd_b"):
                del volumes[key][i]

        with self.assertRaisesRegex(ValueError, "hole"):
            self.page(hole)

    def test_the_closure_note_counts_its_own_items(self) -> None:
        self.assertIn("仍未披露的四条里有三条是公司从未在申报文件里给过的拆分", self.clean)
        self.assertIn("上一份笔记留下的 10 条待验问题：3 条已验证、4 条公司仍未披露", self.clean)

        def more_open(s):
            block = s["followup_closure"]
            block["counts"][block["labels"].index("仍未披露")] = 5
            block["figures"]["never_filed"] = 2

        forced = self.page(more_open)
        self.assertIn("仍未披露的五条里有两条", forced)
        self.assertIn("上一份笔记留下的 11 条待验问题：3 条已验证、5 条公司仍未披露", forced)

    def test_the_incentive_effect_is_worded_by_its_sign(self) -> None:
        """「激励率这 -0.58pp 单独让出了约 US$91M 的净收入」 read as a loss when a
        falling rate leaves Visa more net revenue."""
        self.assertIn("激励率这 +0.61pp 单独吃掉了约 US$99M 的净收入", self.clean)
        self.assertIn("激励率同比 +0.61pp，单独吃掉约 US$99M 净收入", self.clean)

        def rate_fell(s):
            lines = s["revenue_lines_usd_m"]
            lines["incentive_rate_pct"][-5] = lines["incentive_rate_pct"][-1] + 0.5

        fell = self.page(rate_fell)
        self.assertIn("单独多留下了约 US$", fell)
        self.assertIn("单独多留下约 US$", fell)
        self.assertNotIn("让出", fell)

    def test_a_change_that_rounds_to_nothing_has_no_sign(self) -> None:
        def flat(s):
            lines = s["revenue_lines_usd_m"]
            lines["incentive_rate_pct"][-2] = lines["incentive_rate_pct"][-1] + 0.001

        text = self.page(flat)
        self.assertIn("环比 0.00pp", text)
        self.assertNotRegex(text, r"[-−]0\.00pp")

    def test_faster_is_judged_at_the_printed_precision(self) -> None:
        self.assertIn("<b>毛收入比净收入快</b>", self.clean)
        self.assertIn("毛收入同比 +15.3% 更快", self.clean)

        def level(s):
            fin = s["financials"]
            gross_yoy = fin["gross_revenue_usd_m"][-1] / fin["gross_revenue_usd_m"][-5]
            fin["net_revenue_usd_m"][-1] = fin["net_revenue_usd_m"][-5] * gross_yoy - 1

        same = self.page(level)
        self.assertIn("<b>毛收入与净收入一样快</b>", same)
        self.assertNotIn("更快", same)

    def test_the_release_count_is_the_record_s(self) -> None:
        """「全部四十余份新闻稿」: the eras run from the FY2013 opening release on."""
        self.assertIn("要给出这样的计数必须把 FY2013 开局那份（2012-10-31）起的全部 56 份新闻稿逐份读完", self.clean)
        self.assertNotIn("四十余份", self.clean)


if __name__ == "__main__":
    unittest.main()
