"""Reconciliation and shape tests for the SCHW page.

Same purpose as the other companies': nothing derived reaches the page until it
has been checked against a statement identity or a figure the company disclosed
separately.  Schwab's page rests on three of them.

The first two are the income statement itself.  Its five revenue lines -- net
interest revenue, asset management and administration fees, trading revenue,
bank deposit account fees and other -- add to the net revenues the company
prints, and net revenues minus total expenses excluding interest is the pre-tax
income it prints.  Both are pinned for every quarter in the window, because the
whole revenue-mix argument of section two is that these five lines move against
each other; a mix chart whose parts do not add up is not evidence of anything.

The third is the one that matters most, because it is the only check on a
figure no filing states.  Schwab files no 10-Q for its fourth quarter, so every
fourth quarter here is the 10-K's full year minus the three quarters filed
during it.  That subtraction could be silently wrong.  What catches it is that
the earnings press release prints a `Pre-tax profit margin` for that same
quarter: dividing the *derived* pre-tax income by the *derived* net revenues
has to reproduce the number the company published.  It does, for every year in
the window, which is what licenses the page to plot those quarters at all.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import headroom  # noqa: E402
from build.schw import build_payload, compact  # noqa: E402


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


class SchwDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "schw.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]
        cls.by_section = {
            section["id"]: section["exhibits"] for section in cls.payload["sections"]
        }
        cls.fin = cls.source["financials"]
        cls.ops = cls.source["operating"]
        cls.periods = cls.source["periods"]

    # ── shape ────────────────────────────────────────────────────────────────
    def test_the_channel_split_carries_the_published_recast_and_declares_its_break(self) -> None:
        """The reclassification moves balances between the two channels only.

        Schwab moved Retirement Business Services from Advisor Services to
        Investor Services in 4Q24 and recast prior periods back to 2023-12-31 --
        no further, because that is as far as the 4Q24 and 1Q25 releases reprint.
        This page carried the pre-recast side for 2023Q4-2024Q3 until 2026-08-31,
        which made Advisor Services appear to fall 5.1% into 2024Q4 while total
        client assets rose.

        The sum identity the page already asserts -- the two channels adding to
        the disclosed total -- is satisfied on BOTH bases, because the transfer
        is between them. So it is pinned here by value against the published
        recast, and the pre-2023Q4 quarters are asserted to remain on the old
        basis with the break declared on the page rather than smoothed over.
        """
        ops, periods = self.source["operating"], self.source["operating"]["periods"]
        recast = {
            "client_assets_investor_services_usd_bn": {"2023Q4": 4759.2, "2024Q3": 5576.7},
            "client_assets_advisor_services_usd_bn": {"2023Q4": 3757.4, "2024Q3": 4343.8},
            "net_new_assets_investor_services_usd_bn": {"2023Q4": 28.1, "2024Q3": 37.2},
            "net_new_assets_advisor_services_usd_bn": {"2023Q4": 38.2, "2024Q3": 53.6},
        }
        for series, moves in recast.items():
            for period, value in moves.items():
                with self.subTest(series=series, period=period):
                    self.assertEqual(ops[series][periods.index(period)], value)
        # pre-recast side kept, because the company published nothing earlier
        self.assertEqual(ops["client_assets_advisor_services_usd_bn"][periods.index("2023Q3")],
                         3666.8)
        note = self.source["_rbs_reclassification_note"]
        self.assertIn("2023-12-31", note)
        self.assertIn("Retirement Business Services", note)
        # and the break has to reach a reader, not only the JSON
        drawn = " ".join(ex.get("note", "") for section in self.payload["sections"]
                         for ex in section["exhibits"])
        self.assertIn("Retirement Business Services", drawn,
                      "the basis break is declared in the data and nowhere on the page")

    def test_the_window_is_calendar_quarters_without_holes(self) -> None:
        periods = self.periods
        self.assertEqual(periods[0], "2016Q1")
        self.assertEqual(periods[-1], "2026Q2")
        self.assertEqual(len(periods), 42)
        expected = [f"{year}Q{q}" for year in range(2016, 2027) for q in (1, 2, 3, 4)]
        self.assertEqual(periods, [p for p in expected if "2016Q1" <= p <= "2026Q2"])
        self.assertEqual(len(self.source["period_ends"]), len(periods))

    def test_every_financial_series_is_full_length(self) -> None:
        for key, values in self.fin.items():
            with self.subTest(series=key):
                self.assertEqual(len(values), len(self.periods))
                if key == "bda_usd_m":
                    # Bank deposit account fees arrive with TD Ameritrade
                    # (closed 2020-10-06); before that the line does not exist.
                    continue
                self.assertTrue(all(v is not None for v in values))

    def test_operating_series_are_aligned_with_their_own_period_list(self) -> None:
        ops = self.ops
        self.assertEqual(ops["periods"], self.periods,
                         "the two blocks used to run on different axes")
        self.assertEqual(ops["periods"][0], "2016Q1")
        self.assertEqual(ops["periods"][-1], "2026Q2")
        for key, values in ops.items():
            if key in ("periods", "period_ends") or not isinstance(values, list):
                continue
            with self.subTest(series=key):
                self.assertEqual(len(values), len(ops["periods"]))
        # Two operating series are empty before 2020 and say why in the file.
        for key in self.source["operating_notes"]["not_backfilled"]:
            self.assertTrue(all(v is None for v in ops[key][:ops["periods"].index("2020Q1")]),
                            key)

    # ── identities ───────────────────────────────────────────────────────────
    def test_five_revenue_lines_add_to_net_revenues_each_quarter(self) -> None:
        """...and 2016 needs a sixth term, because the statement had one.

        Schwab's 2016 income statement carried "Provision for loan losses"
        *inside* net revenues (-2 / +2 / +5 / 0) and moved it out from 2017. So
        the five lines close on their own from 2017Q1 and close on 2016 only
        once that item is added back. It is kept as its own four-cell record
        rather than folded into one of the five, and the residual is asserted
        to equal it exactly -- which is what makes the 2016 quarters usable
        rather than merely plausible.
        """
        fin = self.fin
        notes = self.source["financials_notes"]
        provision = dict(zip(notes["loan_loss_provision_quarters"],
                             notes["loan_loss_provision_in_revenue_2016_usd_m"]))
        for index, period in enumerate(self.periods):
            parts = [
                fin["net_interest_revenue_usd_m"][index],
                fin["amaf_usd_m"][index],
                fin["trading_usd_m"][index],
                fin["bda_usd_m"][index] or 0,
                fin["other_usd_m"][index],
            ]
            with self.subTest(period=period):
                self.assertAlmostEqual(
                    sum(parts) + provision.get(period, 0.0),
                    fin["revenue_usd_m"][index], places=6)
        self.assertEqual(sorted(provision), ["2016Q1", "2016Q2", "2016Q3", "2016Q4"])

    def test_income_statement_identity_holds_each_quarter(self) -> None:
        fin = self.fin
        for index, period in enumerate(self.periods):
            with self.subTest(period=period):
                self.assertAlmostEqual(
                    fin["revenue_usd_m"][index] - fin["total_expenses_usd_m"][index],
                    fin["pretax_usd_m"][index],
                    places=6,
                )

    def test_net_income_reconciles_to_the_common_line(self) -> None:
        fin = self.fin
        for index, period in enumerate(self.periods):
            with self.subTest(period=period):
                self.assertAlmostEqual(
                    fin["pretax_usd_m"][index] - fin["tax_usd_m"][index],
                    fin["net_income_usd_m"][index],
                    places=6,
                )
                self.assertAlmostEqual(
                    fin["net_income_usd_m"][index] - fin["preferred_dividends_usd_m"][index],
                    fin["net_income_common_usd_m"][index],
                    places=6,
                )

    def test_quarterly_series_reconcile_with_the_full_year(self) -> None:
        """Four quarters must add to the annual figure the 10-K filed."""
        for year, annual in self.source["annual_filed_usd_m"].items():
            quarters = [f"{year}Q{q}" for q in (1, 2, 3, 4)]
            if not all(q in self.periods for q in quarters):
                continue
            index = [self.periods.index(q) for q in quarters]
            for key, filed in annual.items():
                with self.subTest(year=year, line=key):
                    self.assertAlmostEqual(
                        sum(self.fin[key][i] for i in index), filed, places=6
                    )

    def test_derived_fourth_quarters_match_the_margin_the_company_published(self) -> None:
        """The only independent check on a quarter no 10-Q covers.

        Q4 is the filed year minus the three filed quarters.  The company never
        states that quarter's revenue or pre-tax income, but it does state the
        quarter's `Pre-tax profit margin` in the earnings release -- so the
        ratio of two derived numbers has to reproduce a disclosed one.
        """
        ops = self.ops
        checked = 0
        for period in self.source["derived_fourth_quarters"]:
            if period not in ops["periods"]:
                continue
            disclosed = ops["pretax_margin_pct_disclosed"][ops["periods"].index(period)]
            if disclosed is None:
                continue
            index = self.periods.index(period)
            derived = self.fin["pretax_usd_m"][index] / self.fin["revenue_usd_m"][index] * 100
            with self.subTest(period=period):
                # The company rounds its published margin to one decimal.
                self.assertAlmostEqual(derived, disclosed, delta=0.05)
            checked += 1
        self.assertGreaterEqual(checked, 6, "too few derived quarters were cross-checked")

    def test_channel_splits_add_to_their_disclosed_totals(self) -> None:
        ops = self.ops
        for index, period in enumerate(ops["periods"]):
            with self.subTest(period=period, split="client assets"):
                self.assertAlmostEqual(
                    ops["client_assets_investor_services_usd_bn"][index]
                    + ops["client_assets_advisor_services_usd_bn"][index],
                    ops["client_assets_usd_bn"][index],
                    delta=0.05,
                )
            with self.subTest(period=period, split="net new assets"):
                self.assertAlmostEqual(
                    ops["net_new_assets_investor_services_usd_bn"][index]
                    + ops["net_new_assets_advisor_services_usd_bn"][index],
                    ops["net_new_assets_usd_bn"][index],
                    delta=0.05,
                )

    def test_disclosed_pretax_margin_matches_the_statement_for_filed_quarters(self) -> None:
        """Not only the derived quarters: the filed ones must agree too."""
        ops = self.ops
        for index, period in enumerate(ops["periods"]):
            if period not in self.periods:
                continue
            disclosed = ops["pretax_margin_pct_disclosed"][index]
            fin_index = self.periods.index(period)
            derived = (self.fin["pretax_usd_m"][fin_index]
                       / self.fin["revenue_usd_m"][fin_index] * 100)
            with self.subTest(period=period):
                self.assertAlmostEqual(derived, disclosed, delta=0.05)

    def test_net_interest_revenue_is_interest_revenue_minus_interest_expense(self) -> None:
        fin = self.fin
        for index, period in enumerate(self.periods):
            with self.subTest(period=period):
                self.assertAlmostEqual(
                    fin["interest_revenue_usd_m"][index] - fin["interest_expense_usd_m"][index],
                    fin["net_interest_revenue_usd_m"][index],
                    places=6,
                )

    def test_the_gross_interest_legs_come_from_the_10q_not_the_release(self) -> None:
        """Two of Schwab's own filings print different pairs for the same quarter.

        For 2026Q2 the earnings release prints 4,432 / (1,075) and the 10-Q prints
        4,146 / (789); net interest revenue is 3,357 in both, because a Q2 2026
        presentation change nets other interest revenue and expense against each
        other in the 10-Q (372 - 286 = 86) and prior periods are not recast.

        The page's provenance declares the income statement comes from the 10-Q
        and 10-K R-files, so the 10-Q pair is the right one -- and the assertion
        has to say which, because the difference identity already on this page is
        satisfied by both pairs.

        The negative half is the load-bearing half. A check that only pinned
        4,146 / 789 would also pass if someone later re-derived them from the
        release and happened to land there; asserting they are NOT the release's
        pair is what ties this to a source. It is also the assertion this test
        was missing when it briefly pinned the release's pair instead.
        """
        fin = self.fin
        index = self.periods.index("2026Q2")
        self.assertEqual(fin["interest_revenue_usd_m"][index], 4146.0)
        self.assertEqual(fin["interest_expense_usd_m"][index], 789.0)
        self.assertNotEqual(fin["interest_revenue_usd_m"][index], 4432.0,
                            "that is the earnings release's figure, not the 10-Q's")
        self.assertNotEqual(fin["interest_expense_usd_m"][index], 1075.0,
                            "that is the earnings release's figure, not the 10-Q's")
        note = self.source["_2026q2_gross_legs_note"]
        self.assertIn("4,432", note)
        self.assertIn("4,146", note)

    # ── thresholds ───────────────────────────────────────────────────────────
    def test_threshold_headroom_signs_match_the_stated_verdicts(self) -> None:
        """Two of last quarter's four thresholds held; the page must say so."""
        entries = self.source["settled_thresholds"]
        held = [e["metric"] for e in entries
                if headroom(e["direction"], e["threshold"], e["actual"]) >= 0]
        broken = [e["metric"] for e in entries
                  if headroom(e["direction"], e["threshold"], e["actual"]) < 0]
        self.assertEqual(len(held), 2, held)
        self.assertEqual(len(broken), 2, broken)
        overview = next(ex for ex in self.by_section["settled"]
                        if ex["kind"] == "diverging_bars")
        self.assertIn("2 条守住", overview["title"])

    def test_every_threshold_names_a_direction_and_a_real_series(self) -> None:
        ops = self.ops
        for group in ("settled_thresholds",):
            for entry in self.source[group]:
                with self.subTest(metric=entry["metric"]):
                    self.assertIn(entry["direction"], ("up", "down"))
                    if entry.get("series_key"):
                        self.assertIn(entry["series_key"], ops)
        for entry in self.source["next_kpi"]["entries"]:
            with self.subTest(metric=entry["metric"]):
                self.assertIn(entry["direction"], ("up", "down"))
                if entry.get("series_key"):
                    self.assertIn(entry["series_key"], ops)

    def test_a_threshold_without_a_series_is_named_as_excluded(self) -> None:
        """A metric left off the per-metric charts has to say why on the page."""
        without = [e["metric"] for e in self.source["settled_thresholds"]
                   if not e.get("series_key")]
        self.assertEqual(without, ["交易性 sweep 现金（季末）"])
        self.assertIn("sweep", self.source["settled_excluded"])

    # ── content boundary ─────────────────────────────────────────────────────
    def test_the_page_publishes_no_rating_or_valuation(self) -> None:
        """The underlying note carries all of these; the page must carry none.

        Scanned over the content the page actually asserts -- charts, tables
        and the masthead copy -- and not over `notes`, because the notes are
        where the page *states* what it refuses to publish and naming a thing
        in order to exclude it is the opposite of publishing it.  The repo's
        shared guard leaves these terms out of `FORBIDDEN` for the same reason.
        """
        scanned = {k: v for k, v in self.payload.items() if k != "notes"}
        text = json.dumps(scanned, ensure_ascii=False).lower()
        for banned in ("目标价", "评级", "估值", "p/e", "dcf", "sotp",
                       "加仓", "减仓", "止损", "可比公司"):
            with self.subTest(term=banned):
                self.assertNotIn(banned, text)
        # The notes may name them, but only inside the exclusion sentence.
        notes = " ".join(self.payload["notes"])
        self.assertIn("不发布评级、目标价、估值倍数", notes)

    def test_the_page_states_why_it_has_no_guidance_record(self) -> None:
        notes = " ".join(self.payload["notes"])
        self.assertIn("取数限制", notes)
        self.assertIn("Business Update", notes)
        self.assertFalse(
            any(ex["kind"] == "range_band" for ex in self.exhibits),
            "SCHW files no numeric guidance range; the page must not draw one",
        )

    def test_the_page_states_why_it_drops_the_monthly_series(self) -> None:
        notes = " ".join(self.payload["notes"])
        self.assertIn("不发布月度数据", notes)
        self.assertIn("119.8", notes)  # the aggregation is shown to be checkable
        self.assertIn("月度", self.source["next_kpi"]["excluded_note"])

    def test_no_exhibit_plots_a_monthly_series(self) -> None:
        """Every x axis is quarter labels, never months."""
        month = re.compile(r"(?i)\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b|月")
        for exhibit in self.exhibits:
            for label in exhibit.get("xlabels", []):
                with self.subTest(title=exhibit["title"], label=label):
                    self.assertIsNone(month.search(str(label)))

    def test_notes_carry_no_markup(self) -> None:
        """`notes` is escaped on render; chart notes are not.

        `page.js` builds the notes list as `'<li>' + esc(note) + '</li>'`, so a
        tag there reaches the reader as literal `<b>` characters.  `charts.js`
        concatenates `ex.note` and `ex.src_extra` raw, so markup in those is
        correct and deliberate -- this asserts the difference rather than
        banning tags from the payload.  Three notes shipped with `<b>` before
        this test existed.
        """
        import re
        tag = re.compile(r"</?[a-z][a-z0-9]*[^>]*>", re.I)
        for index, note in enumerate(self.payload["notes"]):
            with self.subTest(note=index):
                self.assertIsNone(tag.search(note), f"notes[{index}] carries markup")
        for field in ("headline", "title", "subtitle", "tracker"):
            with self.subTest(field=field):
                self.assertIsNone(tag.search(self.payload[field]))
        for section in self.payload["sections"]:
            with self.subTest(section=section["id"]):
                self.assertIsNone(tag.search(section["title"]))
                self.assertIsNone(tag.search(section["description"]))
        # The raw-rendered fields keep theirs, and that is the point.
        self.assertIn("<b>", self.payload["brief"])

    # ── published payload ────────────────────────────────────────────────────
    def test_published_payload_matches_a_rebuild(self) -> None:
        published = js_payload(ROOT / "data" / "schw.js", "window.DASH")
        self.assertEqual(published, self.payload)

    def test_exhibit_numbers_run_in_render_order(self) -> None:
        numbers = [ex["n"] for ex in self.exhibits]
        self.assertEqual(numbers, list(range(2, 2 + len(numbers))))

    def test_shell_versions_every_script_by_content(self) -> None:
        """A committed shell whose digest is stale serves a cached payload forever.

        The order of the four scripts is `page_shell.render_shell`'s fixed
        output order, not an incidental one, so it is asserted rather than
        compared as a set.
        """
        shell = (ROOT / "schw" / "index.html").read_text(encoding="utf-8")
        self.assertIn("<title>SCHW Quarterly Results</title>", shell)
        sources = re.findall(r'<script src="\.\./([^"?]+)(?:\?v=([0-9a-f]+))?"', shell)
        self.assertEqual(
            [name for name, _ in sources],
            ["data/roster.js", "data/schw.js", "assets/charts.js", "assets/page.js"],
        )
        for name, digest in sources:
            with self.subTest(script=name):
                self.assertTrue(digest, f"{name} is served without a cache-busting version")
                expected = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()[: len(digest)]
                self.assertEqual(digest, expected, f"{name} carries a stale digest")

    def test_compact_shortens_the_period_labels_the_charts_use(self) -> None:
        self.assertEqual(compact("2026Q2"), "26Q2")
        self.assertEqual(compact("2020Q4"), "20Q4")
        for exhibit in self.exhibits:
            for label in exhibit.get("xlabels", []):
                if label and re.fullmatch(r"\d{4}Q[1-4]", str(label)):
                    self.fail(f"{exhibit['title']} carries a four-digit year label")


if __name__ == "__main__":
    unittest.main()
