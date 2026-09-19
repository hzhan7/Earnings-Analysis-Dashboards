"""Checks for the CDNS page.

The page rests on four claims that a quarter roll can quietly invalidate, and
each one is pinned here:

* the guided record must stay paired guide-to-actual on the *guided* quarter.
  Cadence publishes each quarter's outlook alongside the previous quarter's
  results, so an off-by-one match would read a quarter's own result back as its
  forecast and turn the whole first section into a tautology;
* the record's shape is the page's headline finding -- forty-two finished
  quarters and not one reported revenue below the guided floor. The counts are
  asserted, not narrated, so a bad parse cannot quietly soften them;
* a guidance stated as "29% to 30%" is a range, not a point. Three 2018
  quarters were originally read as points because the parser only knew the dash
  form, which overstated each beat by about a hundred basis points;
* the twelve quarterly values must still add to the filed year. Every
  cash-flow line is reconstructed from year-to-date filings and the fiscal
  fourth quarter is the year minus the nine months, so a mis-stitch shows up as
  a sum that no longer closes.

Two further tests exist because the page publishes something the company does
not print. The non-GAAP operating margin is stated as a percent and the same
release states every operating add-back in thousands, so the percent has to be
reproducible from the statements; and China revenue is a *filed* dollar line
from the segment note rather than the integer share times revenue, which is the
derivation this page deliberately does not use.
"""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.all import build_all, roster_payload  # noqa: E402
from build.board import headroom  # noqa: E402
from build.cdns import build_payload  # noqa: E402

# The guided record's tallies are pinned exactly through this quarter; later
# quarters extend the record and are checked as invariants against the page.
PINNED_THROUGH = "2026Q2"


def published_text(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def ng_operating_income(source: dict) -> list[float]:
    """Non-GAAP operating income to the thousand, recomputed here, not by the builder."""
    q = source["quarterly_usd_m"]
    adds = source["non_gaap_reconciliation_usd_m"]["operating_addbacks"]
    return [oi + add for oi, add in zip(q["operating_income"], adds)]


def expected_value(source: dict, entry_id: str) -> float:
    """A threshold's current value, computed independently of the builder."""
    q, qp, qo = source["quarterly_usd_m"], source["quarterly_pct"], source["quarterly_other"]
    revenue = q["revenue_total"]
    guide = source["guidance"]
    if entry_id == "backlog":
        return qo["backlog_usd_bn"][-1]
    if entry_id == "ocf":
        return q["operating_cash_flow"][-1]
    if entry_id == "buyback":
        return q["stock_repurchases"][-1]
    if entry_id == "china_share":
        return qp["geo_china"][-1]
    if entry_id == "margin":
        return qp["non_gaap_operating_margin"][-1]
    if entry_id == "coverage":
        return qo["backlog_usd_bn"][-1] * 1000 / sum(revenue[-4:])
    if entry_id == "ip_yoy":
        key = "category_semiconductor_ip"
        return (qp[key][-1] * revenue[-1]) / (qp[key][-5] * revenue[-5]) * 100 - 100
    if entry_id == "eps_guide":
        return round(sum(guide["full_year"]["current"]["non_gaap_eps"]) / 2, 2)
    if entry_id == "implied_margin":
        full = guide["full_year"]
        year = str(full["fiscal_year"])
        done = [i for i, p in enumerate(source["periods"]) if p.endswith(year)]
        oi = ng_operating_income(source)
        nq = guide["next_quarter"]
        nq_revenue = sum(nq["revenue_usd_m"]) / 2
        nq_oi = nq_revenue * sum(nq["non_gaap_operating_margin_pct"]) / 2 / 100
        rest_revenue = (sum(full["current"]["revenue_usd_m"]) / 2
                        - sum(revenue[i] for i in done) - nq_revenue)
        rest_oi = (full["current"]["non_gaap_operating_income_midpoint_usd_m"]
                   - sum(oi[i] for i in done) - nq_oi)
        return rest_oi / rest_revenue * 100
    raise KeyError(entry_id)


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


class CdnsDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "cdns.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]
        cls.by_section = {
            section["id"]: section["exhibits"] for section in cls.payload["sections"]
        }
        cls.q = cls.source["quarterly_usd_m"]
        cls.pct = cls.source["quarterly_pct"]
        cls.other = cls.source["quarterly_other"]
        cls.guide = cls.source["quarterly_guidance_history"]

    # ── the series itself ────────────────────────────────────────────────────
    def test_twelve_quarter_base_backs_every_yoy(self) -> None:
        """Eight quarters are drawn and four more exist only to divide by."""
        length = len(self.source["periods"])
        self.assertGreaterEqual(length, 12)
        for block in ("quarterly_usd_m", "quarterly_pct", "quarterly_other"):
            for name, values in self.source[block].items():
                with self.subTest(series=name):
                    self.assertEqual(len(values), length)
        self.assertEqual(self.source["non_gaap_reconciliation_usd_m"]["periods"], self.source["periods"])

    def test_income_statement_identity_holds_each_quarter(self) -> None:
        """Revenue less total costs and expenses is operating income, filed."""
        for index, period in enumerate(self.source["periods"]):
            with self.subTest(period=period):
                self.assertAlmostEqual(
                    self.q["revenue_total"][index] - self.q["costs_and_expenses"][index],
                    self.q["operating_income"][index],
                    delta=0.002,
                )

    def test_revenue_splits_into_the_two_filed_lines(self) -> None:
        for index, period in enumerate(self.source["periods"]):
            with self.subTest(period=period):
                self.assertAlmostEqual(
                    self.q["revenue_product_and_maintenance"][index]
                    + self.q["revenue_services"][index],
                    self.q["revenue_total"][index],
                    delta=0.002,
                )

    def test_quarterly_series_reconcile_with_the_full_year(self) -> None:
        """Every cash-flow line is stitched from year-to-date filings, and the
        fiscal fourth quarter is the year minus the nine months, so the only
        way to know the stitch is right is that the four quarters still add to
        the filed annual figure."""
        annual = self.source["annual_reconciliation_usd_m"]
        periods = self.source["periods"]
        for position, year in enumerate(annual["years"]):
            quarters = [i for i, period in enumerate(periods) if period.endswith(year)]
            self.assertEqual(len(quarters), 4, year)
            for name in ("revenue_total", "operating_income", "research_and_development",
                         "net_income", "operating_cash_flow", "capital_expenditures",
                         "stock_repurchases", "china_revenue"):
                with self.subTest(year=year, series=name):
                    self.assertAlmostEqual(
                        sum(self.q[name][index] for index in quarters),
                        annual[name][position],
                        delta=0.05,
                    )

    def test_non_gaap_margin_is_reproducible_from_the_statements(self) -> None:
        """The company prints the margin as a percent and the add-backs in
        thousands; the page publishes the percent, so the two have to agree."""
        recon = self.source["non_gaap_reconciliation_usd_m"]
        for index, period in enumerate(self.source["periods"]):
            addbacks = recon["operating_addbacks"][index]
            disclosed = self.pct["non_gaap_operating_margin"][index]
            if addbacks is None or disclosed is None:
                continue
            with self.subTest(period=period):
                derived = (self.q["operating_income"][index] + addbacks) \
                    / self.q["revenue_total"][index] * 100
                self.assertAlmostEqual(derived, disclosed, delta=0.06)

    def test_mix_percentages_close_to_one_hundred(self) -> None:
        geography = ["geo_americas", "geo_china", "geo_other_asia", "geo_emea", "geo_japan"]
        category = ["category_core_eda", "category_semiconductor_ip",
                    "category_system_design_analysis"]
        for index, period in enumerate(self.source["periods"]):
            for name, keys in (("地域", geography), ("产品线", category)):
                values = [self.pct[key][index] for key in keys]
                if any(value is None for value in values):
                    continue
                with self.subTest(period=period, mix=name):
                    # integer percentages, so the sum is 100 give or take the
                    # rounding the company itself footnotes
                    self.assertLessEqual(abs(sum(values) - 100), 1)

    def test_china_is_the_filed_dollar_line_not_the_derived_one(self) -> None:
        """The segment note discloses China in dollars, so the page must not be
        plotting the integer share times revenue -- a derivation that reads the
        latest year-over-year move as +107% where the filing says +95.7%."""
        for index, period in enumerate(self.source["periods"]):
            filed = self.q["china_revenue"][index]
            share = self.pct["geo_china"][index]
            if filed is None or share is None:
                continue
            derived = share / 100 * self.q["revenue_total"][index]
            with self.subTest(period=period):
                self.assertNotAlmostEqual(filed, derived, delta=0.0005)
                # but the two must still describe the same quarter
                self.assertLess(abs(filed - derived) / filed * 100, 8.0)
        checks = self.source["_checks"]
        filed = checks["china_revenue_usd_k"] / checks["china_revenue_year_ago_usd_k"] * 100 - 100
        self.assertIn(f"同比 {filed:+.1f}%", published_text(self.payload))

    # ── the guided record ────────────────────────────────────────────────────
    def test_guidance_record_is_paired_on_the_guided_quarter(self) -> None:
        """Cadence guides quarter N in the release that reports quarter N-1, so
        every row's guidance date has to fall after that earlier quarter ended
        and inside the quarter being guided -- never after it."""
        record = self.guide
        length = len(record["quarters"])
        for key, values in record.items():
            if isinstance(values, list):
                with self.subTest(series=key):
                    self.assertEqual(len(values), length)
        month_end = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}
        month_start = {1: "01-01", 2: "04-01", 3: "07-01", 4: "10-01"}
        for quarter, filed in zip(record["quarters"], record["guided_on"]):
            year, number = int(quarter[:4]), int(quarter[-1])
            with self.subTest(quarter=quarter):
                self.assertGreater(filed, f"{year}-{month_start[number]}")
                self.assertLess(filed, f"{year}-{month_end[number]}")

    def test_only_the_pending_quarter_lacks_an_actual(self) -> None:
        record = self.guide
        for key in ("revenue_actual_usd_m", "non_gaap_operating_margin_actual_pct",
                    "non_gaap_eps_actual"):
            missing = [q for q, v in zip(record["quarters"], record[key]) if v is None]
            with self.subTest(series=key):
                self.assertEqual(missing, [record["quarters"][-1]])

    def test_the_record_never_broke_the_floor_on_revenue_or_eps(self) -> None:
        """The record's shape through the migrated quarter, pinned; the page's
        claims about it are checked against the whole record below."""
        record = self.guide

        def tally(low, high, actual):
            above = inside = below = 0
            for quarter, lo, hi, value in zip(record["quarters"], record[low], record[high], record[actual]):
                if value is None or quarter > PINNED_THROUGH:
                    continue
                if value > hi:
                    above += 1
                elif value < lo:
                    below += 1
                else:
                    inside += 1
            return above, inside, below

        self.assertEqual(
            tally("revenue_guide_low_usd_m", "revenue_guide_high_usd_m", "revenue_actual_usd_m"),
            (25, 17, 0),
        )
        self.assertEqual(
            tally("non_gaap_eps_guide_low", "non_gaap_eps_guide_high", "non_gaap_eps_actual"),
            (35, 7, 0),
        )
        above, inside, below = tally(
            "non_gaap_operating_margin_guide_low_pct",
            "non_gaap_operating_margin_guide_high_pct",
            "non_gaap_operating_margin_actual_pct",
        )
        self.assertEqual((above, inside, below), (37, 3, 2))

    def test_both_margin_shortfalls_were_against_a_point_guidance(self) -> None:
        """The page says the misses were against a guidance with no width; the
        sentence is printed only while the record says so."""
        record = self.guide
        misses = []
        for index, quarter in enumerate(record["quarters"]):
            actual = record["non_gaap_operating_margin_actual_pct"][index]
            low = record["non_gaap_operating_margin_guide_low_pct"][index]
            if actual is None or actual >= low:
                continue
            misses.append((record["non_gaap_operating_margin_guide_form"][index], low - actual))
        note = next(ex["note"] for ex in self.by_section["settled"]
                    if ex["title"].startswith("非 GAAP 营业利润率相对指引中值"))
        all_point = bool(misses) and all(form == "point" for form, _ in misses)
        self.assertEqual("发生在<b>单点指引</b>上" in note, all_point)
        if all_point and len(misses) == 2:
            self.assertIn(" 与 ".join(f"{gap:.1f}pp" for _, gap in misses), note)

    def test_a_two_sided_guidance_is_never_recorded_as_a_point(self) -> None:
        """Cadence writes some ranges as "29% to 30%" rather than with a dash.
        Reading those as a point overstated three 2018 beats by about a hundred
        basis points each, so the form flag and the endpoints have to agree."""
        record = self.guide
        for index, quarter in enumerate(record["quarters"]):
            form = record["non_gaap_operating_margin_guide_form"][index]
            low = record["non_gaap_operating_margin_guide_low_pct"][index]
            high = record["non_gaap_operating_margin_guide_high_pct"][index]
            with self.subTest(quarter=quarter):
                self.assertEqual(form == "point", low == high)
        for quarter, expected in (("2018Q2", (27.0, 28.0)), ("2018Q3", (27.0, 28.0)),
                                  ("2018Q4", (29.0, 30.0))):
            index = record["quarters"].index(quarter)
            with self.subTest(quarter=quarter):
                self.assertEqual(
                    (record["non_gaap_operating_margin_guide_low_pct"][index],
                     record["non_gaap_operating_margin_guide_high_pct"][index]),
                    expected,
                )

    def test_the_page_states_the_guidance_is_not_ex_ante(self) -> None:
        """Every delivery chart has to carry the timing caveat: the guidance is
        published inside the quarter it guides, which is what makes a perfect
        record less remarkable than it first reads."""
        delivery = [ex for ex in self.by_section["settled"]
                    if ex["kind"] in ("range_band", "grouped_bars")]
        self.assertEqual(len(delivery), 6)
        for exhibit in delivery:
            with self.subTest(exhibit=exhibit["n"]):
                self.assertIn("不是事前预测", exhibit["src_extra"])
        self.assertTrue(any("不是事前预测" in note for note in self.payload["notes"]))

    # ── the derived numbers the page argues from ─────────────────────────────
    def test_implied_fourth_quarter_margin_is_an_identity(self) -> None:
        """Full year less the year's reported quarters less the next quarter's
        guided midpoint leaves the rest of the year, with no estimate anywhere.
        The year's reported non-GAAP operating income is summed from each
        release's reconciliation to the thousand; the CFO Commentary's rounded
        "non-GAAP costs" put the first half at US$1,380.7M, which moved the
        implied fourth quarter from 42.89% to 42.84%."""
        implied = expected_value(self.source, "implied_margin")
        chart = next(ex for ex in self.by_section["quarter_highlights"]
                     if ex["title"].startswith("本季非 GAAP 营业利润率"))
        self.assertIn(f"只有 {implied:.2f}%", chart["title"])
        self.assertAlmostEqual(chart["series"][1]["values"][-1], implied, places=9)
        year = str(self.source["guidance"]["full_year"]["fiscal_year"])
        done = [i for i, p in enumerate(self.source["periods"]) if p.endswith(year)]
        ytd_oi = sum(ng_operating_income(self.source)[i] for i in done)
        self.assertIn(f"实际 ${ytd_oi:,.0f}M", chart["note"])

    def test_backlog_coverage_is_read_against_the_same_quarter(self) -> None:
        """The multiple is drawn down every first half, so the chart must not
        argue from a sequential fall alone."""
        chart = next(ex for ex in self.by_section["quarter_highlights"]
                     if "backlog" in ex["title"] and ex["kind"] == "gs_bar")
        self.assertIn("去年同期", chart["note"])
        self.assertIn("季节性", chart["note"])

    # ── thresholds ───────────────────────────────────────────────────────────
    def test_headroom_bars_reproduce_the_thresholds(self) -> None:
        """No threshold carries a typed current value: each is recomputed here
        from the series. The typed ones had drifted -- the IP rate was keyed as
        43.4 against 43.3, the coverage ratio as the rounded 1.39."""
        for section, block in (("settled", "prior_kpi_settlement"), ("next_quarter", "next_kpi")):
            entries = self.source[block]["quantified"]
            chart = next(ex for ex in self.by_section[section]
                         if ex["kind"] == "diverging_bars")
            with self.subTest(section=section):
                self.assertEqual(chart["xlabels"], [e["metric"] for e in entries])
                for entry in entries:
                    self.assertNotIn("current", entry)
                    self.assertNotIn("actual", entry)
                self.assertEqual(
                    chart["values"],
                    [round(headroom(e["direction"], e["threshold"], expected_value(self.source, e["id"])), 1)
                     for e in entries],
                )

    def test_book_to_bill_is_retired_rather_than_settled(self) -> None:
        """Its numerator is the difference of two figures the company rounds to
        US$0.1B, so the ratio cannot be resolved against a 1.10x line at all."""
        settlement = self.source["prior_kpi_settlement"]
        self.assertNotIn("单季 book-to-bill",
                         [entry["metric"] for entry in settlement["quantified"]])
        self.assertTrue(any("book-to-bill" in text for text in settlement["retired"]))
        chart = next(ex for ex in self.by_section["settled"] if ex["kind"] == "diverging_bars")
        self.assertIn("无法结算", chart["note"])

    def test_every_tracked_metric_with_a_series_gets_its_own_chart(self) -> None:
        """The overview bar says which line broke; only the per-metric chart
        says how it got there. Which metrics get one is the block's own flag."""
        for section, block in (("settled", "prior_kpi_settlement"), ("next_quarter", "next_kpi")):
            titles = [ex["title"] for ex in self.by_section[section] if ex["kind"] == "lines"]
            for entry in self.source[block]["quantified"]:
                charted = any(title.startswith(entry["metric"] + "：") for title in titles)
                with self.subTest(section=section, metric=entry["metric"]):
                    self.assertEqual(charted, entry["chart"])

    # ── page shape and boundary ──────────────────────────────────────────────
    def test_page_is_chart_led(self) -> None:
        self.assertGreaterEqual(len(self.exhibits), 24)
        self.assertEqual(self.payload["summary"]["blocks"], [])
        for exhibit in self.exhibits:
            with self.subTest(exhibit=exhibit["n"]):
                self.assertTrue(exhibit["note"])
                self.assertTrue(exhibit["src_extra"])

    def test_section_order_matches_how_the_note_is_used(self) -> None:
        self.assertEqual(
            [section["id"] for section in self.payload["sections"]],
            ["settled", "quarter_highlights", "next_quarter", "routine"],
        )

    def test_exhibit_numbers_are_assigned_in_render_order(self) -> None:
        self.assertEqual([ex["n"] for ex in self.exhibits],
                         list(range(2, 2 + len(self.exhibits))))
        for exhibit in self.exhibits:
            with self.subTest(exhibit=exhibit["n"]):
                self.assertNotIn("{EX_", json.dumps(exhibit, ensure_ascii=False))

    def test_cdns_is_not_in_the_cross_page_capex_table(self) -> None:
        """The shared table is hyperscaler capex into foundry wafers; Cadence
        sits outside that chain and must not be spliced into it."""
        table = next(t for t in self.payload["tables"] if "AI capex" in t["title"])
        self.assertNotIn("CDNS", " ".join(table["headers"]))

    def test_market_expectation_is_labelled_and_unattributed(self) -> None:
        consensus = self.source["market_expectation"]
        self.assertIn("市场预期", consensus["label"])
        self.assertTrue(consensus["as_of"])
        blob = json.dumps(self.payload, ensure_ascii=False).lower()
        for broker in ("zacks", "marketbeat", "seeking alpha", "investing.com", "benzinga",
                       "stifel", "benchmark", "bloomberg", "visible alpha", "factset"):
            with self.subTest(broker=broker):
                self.assertNotIn(broker, blob)
        # 目标价 / 评级 / 估值 are deliberately absent from this list: they appear
        # in the page's own boundary statement, exactly as on every other page,
        # so a substring test on them fires on a clean tree. What must never
        # appear is a position instruction or a valuation multiple carried over
        # from the local note.
        for banned in ("加仓", "减仓", "买入", "卖出", "撤销条件", "情景", "概率加权",
                       "forward p/e", "ev/revenue", "terminal multiple"):
            with self.subTest(term=banned):
                self.assertNotIn(banned, blob)

    def test_sources_are_official_http_links(self) -> None:
        for source in self.source["sources"]:
            with self.subTest(label=source["label"]):
                host = urlparse(source["url"]).netloc
                self.assertTrue(host.endswith("sec.gov") or host.endswith("cadence.com"), host)

    def test_published_payload_roster_and_shell(self) -> None:
        published = js_payload(ROOT / "data" / "cdns.js", "window.DASH")
        self.assertEqual(published, self.payload)
        roster = js_payload(ROOT / "data" / "roster.js", "window.ROSTER")
        self.assertEqual(roster, roster_payload(build_all()))
        shell = (ROOT / "cdns" / "index.html").read_text(encoding="utf-8")
        self.assertIn("../data/cdns.js", shell)
        self.assertNotIn("../data/tsm.js", shell)

    def test_home_page_carries_the_new_company(self) -> None:
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="cdns/"', home)
        self.assertIn(self.payload["latest"]["disclosed_period_label"], home)
        self.assertIn(self.payload["latest"]["release_date"], home)

    def test_public_files_exclude_private_and_broker_material(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [ROOT / "series" / "cdns.json", ROOT / "data" / "cdns.js"]
        )
        for banned in ("OneDrive", "/Users/", ".pptx", "transcript.pdf", "Seeking Alpha",
                       "Zacks", "MarketBeat", "Stifel", "Benchmark"):
            with self.subTest(term=banned):
                self.assertNotIn(banned, text)


class CdnsChecksTest(unittest.TestCase):
    """The page's quarter against a record keyed separately from the filings.

    `_checks` is typed once per quarter from the earnings 8-K (EX-99.01 and the
    EX-99.02 CFO Commentary) and the 10-Q, with the place each figure was read;
    the builder never reads it (asserted in `test_data_only_roll`). Rolling a
    quarter re-keys `_checks`; this class does not change.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "cdns.json").read_text(encoding="utf-8"))
        cls.checks = cls.source["_checks"]
        cls.payload = build_payload(cls.source)
        cls.text = published_text(cls.payload)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]

    def test_the_page_names_the_checked_quarter(self) -> None:
        self.assertIn(self.checks["period"], self.payload["title"])
        self.assertIn(f"截至 {self.checks['period_end']}", self.payload["subtitle"])
        self.assertIn(f"发布 {self.checks['release_date']}", self.payload["subtitle"])
        # The release that reported this quarter guided the next one.
        record = self.source["quarterly_guidance_history"]
        self.assertEqual(record["guided_on"][-1], self.checks["release_date"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        c, q = self.checks, self.source["quarterly_usd_m"]
        qp, qo = self.source["quarterly_pct"], self.source["quarterly_other"]
        self.assertEqual(round(q["revenue_total"][-1] * 1000), c["revenue_usd_k"])
        self.assertEqual(round(q["revenue_total"][-5] * 1000), c["revenue_year_ago_usd_k"])
        year = self.checks["period"].split()[1]
        six = [v for p, v in zip(self.source["periods"], q["revenue_total"]) if p.endswith(year)]
        self.assertEqual(round(sum(six) * 1000), c["revenue_six_months_usd_k"])
        self.assertEqual(qp["gaap_operating_margin"][-1], c["gaap_operating_margin_pct"])
        self.assertEqual(qp["non_gaap_operating_margin"][-1], c["non_gaap_operating_margin_pct"])
        self.assertEqual(qo["gaap_eps"][-1], c["gaap_diluted_eps_usd"])
        self.assertEqual(qo["non_gaap_eps"][-1], c["non_gaap_diluted_eps_usd"])
        self.assertEqual(round(self.source["non_gaap_reconciliation_usd_m"]["operating_addbacks"][-1] * 1000),
                         c["operating_addbacks_usd_k"])
        self.assertEqual(qo["backlog_usd_bn"][-1], c["backlog_usd_bn"])
        self.assertEqual(round(q["operating_cash_flow"][-1]), c["operating_cash_flow_usd_m"])
        self.assertEqual(round(q["stock_repurchases"][-1]), c["share_repurchase_usd_m"])
        self.assertEqual(qp["geo_china"][-1], c["china_share_pct"])
        self.assertEqual(round(q["china_revenue"][-1] * 1000), c["china_revenue_usd_k"])
        self.assertEqual(round(q["china_revenue"][-5] * 1000), c["china_revenue_year_ago_usd_k"])
        # The margin the release prints is what the reconciliation reproduces.
        derived = (q["operating_income"][-1] * 1000 + c["operating_addbacks_usd_k"]) / c["revenue_usd_k"] * 100
        self.assertEqual(round(derived, 1), c["non_gaap_operating_margin_pct"])

    def test_the_outlook_is_the_checked_outlook(self) -> None:
        guide, c = self.source["guidance"], self.checks
        nq, cnq = guide["next_quarter"], c["next_quarter"]
        self.assertEqual(nq["period"], cnq["period"])
        self.assertEqual(nq["revenue_usd_m"], cnq["revenue_usd_m"])
        self.assertEqual(nq["non_gaap_operating_margin_pct"], cnq["non_gaap_operating_margin_pct"])
        self.assertEqual(nq["non_gaap_eps"], cnq["non_gaap_eps_usd"])
        full, cfull = guide["full_year"], c["full_year"]
        self.assertEqual(full["fiscal_year"], cfull["fiscal_year"])
        self.assertEqual(full["current"]["revenue_usd_m"], cfull["revenue_usd_m"])
        self.assertEqual(full["current"]["non_gaap_operating_margin_pct"], cfull["non_gaap_operating_margin_pct"])
        self.assertEqual(full["current"]["non_gaap_eps"], cfull["non_gaap_eps_usd"])
        self.assertEqual(full["current"]["non_gaap_operating_income_midpoint_usd_m"],
                         cfull["non_gaap_operating_income_midpoint_usd_m"])
        self.assertEqual(full["previous"]["revenue_usd_m"], cfull["previous_revenue_usd_m"])
        self.assertEqual(full["previous"]["non_gaap_operating_income_midpoint_usd_m"],
                         cfull["previous_non_gaap_operating_income_midpoint_usd_m"])

    def test_the_page_prints_the_checked_figures(self) -> None:
        c = self.checks
        self.assertIn(f"收入 ${c['revenue_usd_k'] / 1000:,.1f}M", self.payload["headline"])
        self.assertIn(f"US${c['backlog_usd_bn']:.1f}B", self.payload["headline"])
        # The next quarter's implied growth is read against the same quarter a
        # year earlier, and lands inside the range the company printed for it.
        # (It used to divide by the quarter after that one: +11.8% for +20.3%.)
        cnq = c["next_quarter"]
        middle = sum(cnq["revenue_usd_m"]) / 2
        year_ago = self.source["periods"].index(
            f"{cnq['period'].split()[0]} {int(cnq['period'].split()[1]) - 1}")
        yoy = (middle / self.source["quarterly_usd_m"]["revenue_total"][year_ago] - 1) * 100
        low, high = cnq["revenue_yoy_growth_pct"]
        self.assertTrue(low <= yoy <= high)
        qoq = (middle * 1000 / c["revenue_usd_k"] - 1) * 100
        self.assertTrue(cnq["revenue_qoq_growth_pct"][0] <= qoq <= cnq["revenue_qoq_growth_pct"][1])
        revenue_chart = next(ex for ex in self.exhibits if ex["kind"] == "gs_bar" and ex["title"].startswith("收入 $"))
        self.assertIn(f"隐含同比 {yoy:+.1f}%", revenue_chart["note"])
        table = next(t for t in self.payload["tables"] if t["title"] == "下季与全年指引")
        self.assertIn(f"同比 {yoy:+.1f}%", table["rows"][0][3])


class CdnsRollTest(unittest.TestCase):
    """A roll edits the series and nothing else: the one-quarter blocks carry
    their quarter, the story blocks name the facts they rest on, and every
    sentence about the record is recounted from it."""

    STAMPED = ("followup_closure", "prior_kpi_settlement", "next_kpi", "guidance",
               "market_expectation", "quarter_story", "balance_sheet_usd_m", "ytd_cash_bridge_usd_m")

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "cdns.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)
        cls.text = published_text(cls.payload)

    def rebuilt(self, edit) -> dict:
        changed = copy.deepcopy(self.source)
        edit(changed)
        return build_payload(changed)

    def moves(self, claims, edit) -> None:
        after = published_text(self.rebuilt(edit))
        for claim in claims:
            with self.subTest(claim=claim):
                self.assertIn(claim, self.text)
                self.assertNotIn(claim, after)

    def test_quarter_blocks_refuse_to_publish_under_another_quarter(self) -> None:
        for key in self.STAMPED:
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    self.rebuilt(lambda s, key=key: s[key].__setitem__("period", "Q1 1999"))
        with self.assertRaisesRegex(ValueError, "stamped"):
            self.rebuilt(lambda s: s["operating_kpi"]["category_growth_company_pct"].__setitem__(
                "period", "Q1 1999"))
        period = self.source["latest"]["period"]
        with self.assertRaisesRegex(ValueError, "sources"):
            self.rebuilt(lambda s: s.__setitem__(
                "sources", [x for x in s["sources"] if not x["label"].startswith(f"{period} 业绩发布 8-K")]))

    def test_a_quarter_without_its_blocks_leaves_them_out(self) -> None:
        def strip(s):
            for key in self.STAMPED:
                del s[key]
            del s["operating_kpi"]["category_growth_company_pct"]
        payload = self.rebuilt(strip)
        text = published_text(payload)
        for gone in ("低续约年", "危机季", "无人过问", "targeted investments", "待验证问题",
                     "量化阈值", "盘后", "现金桥", "资产负债表变动", "下季与全年指引", "2026E"):
            with self.subTest(gone=gone):
                self.assertIn(gone, self.text)
                self.assertNotIn(gone, text)
        self.assertEqual([s["id"] for s in payload["sections"]],
                         ["settled", "quarter_highlights", "next_quarter", "routine"])
        self.assertEqual(len(payload["sections"][0]["exhibits"]), 6)

    def test_a_story_whose_premise_fails_stops_the_build(self) -> None:
        def backlog_fell(s):
            s["quarterly_other"]["backlog_usd_bn"][-1] = 7.5
        with self.assertRaisesRegex(ValueError, "ytd_backlog_grew"):
            self.rebuilt(backlog_fell)

        def threshold_moved(s):
            s["prior_kpi_settlement"]["quantified"][0]["threshold"] = 8.0
        with self.assertRaisesRegex(ValueError, "prior_kpi_settlement"):
            self.rebuilt(threshold_moved)

        def typed_again(s):
            s["next_kpi"]["quantified"][1]["current"] = 1.39
        with self.assertRaisesRegex(ValueError, "computed from the series"):
            self.rebuilt(typed_again)

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        def revenue_missed(s):
            record = s["quarterly_guidance_history"]
            row = record["quarters"].index("2020Q1")
            record["revenue_actual_usd_m"][row] = record["revenue_guide_low_usd_m"][row] - 1
        self.moves(("一次都没有跌破过指引下限，也一次都没有低于指引中值", "与收入同样从未跌破下限"),
                   revenue_missed)

        def margin_miss_on_a_range(s):
            record = s["quarterly_guidance_history"]
            row = record["quarters"].index("2019Q2")
            record["non_gaap_operating_margin_actual_pct"][row] = record["non_gaap_operating_margin_guide_low_pct"][row] - 1
        self.moves(("唯二两次为负的季度都发生在<b>单点指引</b>上",), margin_miss_on_a_range)

        def margin_fell_before(s):
            s["fiscal_year"]["non_gaap_operating_margin_pct"][3] = 29.0
        self.moves(("十年里第一次同比下降", "连续九年上行"), margin_fell_before)

        def second_negative_quarter(s):
            s["long_history"]["revenue_usd_m"][20] = s["long_history"]["revenue_usd_m"][16] - 1
        self.moves(("窗口里唯一一个负增长季",), second_negative_quarter)

        def coverage_moved(s):
            s["fiscal_year"]["year_end_backlog_usd_bn"][-1] = 8.5
        self.moves(("一模一样地停在", "连续三年停在"), coverage_moved)

        def sbc_never_dipped(s):
            s["fiscal_year"]["stock_based_compensation_pct_of_revenue"][3:8] = [8.1, 8.2, 8.3, 8.35, 8.38]
        after = published_text(self.rebuilt(sbc_never_dipped))
        self.assertIn("中间在 2019–2021 年回落过", self.text)
        self.assertNotIn("回落过", after)
        self.assertIn("一路走到", after)

        def buyback_varied(s):
            s["quarterly_usd_m"]["stock_repurchases"][-2] = 180.0
        self.moves(("金额固定",), buyback_varied)

        def backlog_not_record(s):
            s["quarterly_other"]["backlog_usd_bn"][-6] = 8.4
        self.moves(("backlog 创纪录的", "绝对额是历史最高"), backlog_not_record)

        def admin_slower(s):
            s["quarterly_usd_m"]["general_and_administrative"][-1] = 70.0
        self.moves(("后者是三条费用线里最快的一条",), admin_slower)

        def gaap_peak_later(s):
            s["fiscal_year"]["gaap_operating_margin_pct"][-1] = 31.0
        self.moves(("GAAP 口径在 2023 年见顶 30.6% 后回落了两年",), gaap_peak_later)

    def test_the_counts_on_the_page_are_recounted_here(self) -> None:
        record = self.source["quarterly_guidance_history"]
        finished = [i for i, v in enumerate(record["revenue_actual_usd_m"]) if v is not None]
        self.assertIn(f"{len(finished)} 个已完结季里，实际收入", self.text)
        margin = [(record["non_gaap_operating_margin_actual_pct"][i],
                   record["non_gaap_operating_margin_guide_high_pct"][i]) for i in finished]
        above = sum(1 for actual, high in margin if actual > high)
        self.assertIn(f"在 {len(finished)} 个已完结季里有 {above} 季高于自己的指引上限", self.text)
        points = sum(1 for form in record["non_gaap_operating_margin_guide_form"] if form == "point")
        self.assertIn(f"整段 {len(record['quarters'])} 季记录里有 {points} 季公司给的是", self.text)
        fy = self.source["fiscal_year"]
        cover = [round(b * 1000 / r, 2) for b, r in zip(fy["year_end_backlog_usd_bn"], fy["revenue_usd_m"])]
        flat = 1
        while cover[-1 - flat] == cover[-1]:
            flat += 1
        self.assertIn(f"随后 {'、'.join(fy['labels'][-flat:])}", self.text)
        long = self.source["long_history"]
        self.assertIn(f"收入 {len(long['quarters'])} 个季度（前 "
                      f"{long['accounting_standard'].count('ASC 605')} 季为 ASC 605）", self.text)

    def test_no_markdown_reaches_an_exhibit_note(self) -> None:
        """Exhibit notes are innerHTML: a markdown `**` prints as two asterisks."""
        for section in self.payload["sections"]:
            for ex in section["exhibits"]:
                with self.subTest(exhibit=ex["n"]):
                    self.assertNotIn("**", ex.get("note", "") + ex.get("src_extra", ""))


if __name__ == "__main__":
    unittest.main()
