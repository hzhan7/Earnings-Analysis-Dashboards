"""Checks for the AVGO page.

Broadcom's page rests on four claims that would each fail silently on a quarter
roll, so each one is a test rather than a sentence:

* **The fiscal fourth quarter is stitched from a second document type.** XBRL
  carries no standalone quarterly fact for it, so those five values come from
  the quarter's own earnings release while the other twenty-eight come from the
  statements. The only independent check on that seam is that the four quarters
  of each year still add to the filed year, so that is pinned for every complete
  fiscal year, on revenue and on GAAP operating income.
* **The two segments' filed operating incomes sum to the company's non-GAAP
  operating income exactly.** The page attributes the guided margin to a
  semiconductor engine and a software engine on the strength of that identity;
  if it ever stopped holding, the attribution would silently become an estimate.
  FY2019 and earlier need the third, since-retired IP-licensing segment included.
* **The guided record must stay paired to the quarter it guides**, not the one
  the release reports. Every number in section one is worthless if a release's
  Outlook block is ever matched to the wrong quarter, and the two are only ever
  one row apart.
* **The beat decomposition must remain an identity**, because the page says in
  as many words that it is one.

Two more guard things the page asserts about *itself*: that the record's
one-sidedness is real (never below the guided point or midpoint in any finished
quarter, on either metric), and that the outlook is published after the guided
quarter has already begun -- the caveat that stops "never missed" from reading
as a forecasting record.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.all import ENTRIES, build_all, roster_payload  # noqa: E402
from build.board import headroom  # noqa: E402
from build.avgo import build_payload  # noqa: E402


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


class AvgoDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "avgo.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]
        cls.by_section = {s["id"]: s["exhibits"] for s in cls.payload["sections"]}
        cls.fin = cls.source["financials_usd_m"]
        cls.seg = cls.source["segments_usd_m"]
        cls.guide = cls.source["quarterly_guidance_history"]
        cls.years = cls.source["filed_fiscal_years"]
        cls.ends = cls.source["period_ends"]

    # ── the series itself ────────────────────────────────────────────────────
    def test_every_quarterly_series_is_the_same_length_and_in_order(self) -> None:
        n = len(self.ends)
        for group in ("financials_usd_m", "segments_usd_m", "cash_flow_usd_m",
                      "capital_allocation_usd_m", "working_capital_usd_m",
                      "purchase_commitments_usd_m"):
            for name, values in self.source[group].items():
                with self.subTest(series=f"{group}.{name}"):
                    self.assertEqual(len(values), n)
        self.assertEqual(self.ends, sorted(self.ends))
        self.assertEqual(len(set(self.ends)), n)

    def test_calendar_labels_follow_the_fiscal_mapping(self) -> None:
        """The site labels every page by calendar quarter; getting this wrong is
        invisible on the page and wrong in the cross-company capex table.

        Broadcom's year ends in early November, so the company's FY Q1 is the
        previous calendar year's Q4 and each later fiscal quarter maps one step
        back -- the same rule the Synopsys page uses for its October year-end.
        """
        month_to_quarter = {1: "Q4", 2: "Q4", 4: "Q1", 5: "Q1",
                            7: "Q2", 8: "Q2", 10: "Q3", 11: "Q3"}
        for end, period, fiscal in zip(self.ends, self.source["periods"],
                                       self.source["fiscal_labels"]):
            with self.subTest(period_end=end):
                year, month = int(end[:4]), int(end[5:7])
                quarter = month_to_quarter[month]
                calendar_year = year - 1 if quarter == "Q4" else year
                self.assertEqual(period, f"{quarter} {calendar_year}")
                fiscal_quarter = {1: 1, 2: 1, 4: 2, 5: 2, 7: 3, 8: 3, 10: 4, 11: 4}[month]
                self.assertEqual(fiscal, f"FY{year} Q{fiscal_quarter}")

    def test_quarterly_series_reconcile_with_the_filed_full_year(self) -> None:
        """The fiscal fourth quarter comes from the release, not the statements.

        Every other quarter is an XBRL fact; the fiscal fourth is not tagged
        standalone and is read off that quarter's own earnings release instead.
        A mis-stitched fourth quarter would look perfectly ordinary on the page,
        and the year total is the only thing that would notice.
        """
        by_end = dict(zip(self.ends, self.fin["revenue"]))
        oi_by_end = dict(zip(self.ends, self.fin["gaap_operating_income"]))
        checked = 0
        for index, year_end in enumerate(self.years["fiscal_year_ends"]):
            quarters = [end for end in self.ends if end <= year_end][-4:]
            if len(quarters) < 4 or quarters[0] < self.ends[0]:
                continue
            # only a year whose four quarters are all inside the reviewed window
            span_start = quarters[0]
            if (int(year_end[:4]) - int(span_start[:4])) > 1:
                continue
            with self.subTest(fiscal_year_end=year_end):
                self.assertAlmostEqual(
                    sum(by_end[q] for q in quarters),
                    self.years["revenue_usd_m"][index], delta=1.0)
                self.assertAlmostEqual(
                    sum(oi_by_end[q] for q in quarters),
                    self.years["gaap_operating_income_usd_m"][index], delta=1.0)
                checked += 1
        self.assertGreaterEqual(checked, 7)

    def test_segment_revenue_sums_to_the_consolidated_statement(self) -> None:
        """Two reportable segments today, three until the FY2019 IP-licensing
        line was wound down. Dropping the third would leave a residual that
        looks like a rounding error and is not one."""
        checked = 0
        for index, end in enumerate(self.ends):
            semi = self.seg["semiconductor_revenue"][index]
            isg = self.seg["infrastructure_software_revenue"][index]
            if semi is None or isg is None:
                continue
            ipl = self.seg["ip_licensing_revenue"][index] or 0.0
            with self.subTest(period_end=end):
                self.assertAlmostEqual(semi + isg + ipl, self.fin["revenue"][index], delta=1.0)
                checked += 1
        self.assertGreaterEqual(checked, 30)

    def test_segment_operating_income_sums_to_non_gaap_operating_income(self) -> None:
        """The identity the whole segment view rests on.

        Broadcom's segment note measures each segment's operating income before
        the items its own non-GAAP definition removes, so the segments add up to
        the non-GAAP line rather than the GAAP one. That is what lets the page
        split a guided *margin* between the two engines with no estimate. It has
        held exactly -- not approximately -- in every quarter the note covers.
        """
        checked = 0
        for index, end in enumerate(self.ends):
            semi = self.seg["semiconductor_operating_income"][index]
            isg = self.seg["infrastructure_software_operating_income"][index]
            if semi is None or isg is None:
                continue
            ipl = self.seg["ip_licensing_operating_income"][index] or 0.0
            with self.subTest(period_end=end):
                self.assertAlmostEqual(
                    semi + isg + ipl,
                    self.fin["non_gaap_operating_income"][index], delta=0.5)
                checked += 1
        self.assertGreaterEqual(checked, 30)

    def test_undisclosed_quarters_stay_empty(self) -> None:
        """FY2018's reportable segments were four product lines, not the two the
        page plots, so those quarters must be holes rather than being padded."""
        for index, end in enumerate(self.ends):
            if end >= "2019-02-03":
                continue
            with self.subTest(period_end=end):
                self.assertIsNone(self.seg["semiconductor_revenue"][index])
                self.assertIsNone(self.seg["infrastructure_software_revenue"][index])

    def test_segment_gross_margin_is_not_published(self) -> None:
        """Segment cost of revenue was first disclosed under ASU 2023-07 in the
        FY2025 10-K, so it exists for two quarters and cannot carry a series.
        The page reports the threshold that needed it as unsettleable; if the
        data ever became long enough this test is the reminder to revisit."""
        disclosed = [v for v in self.seg["semiconductor_cost_of_revenue"] if v is not None]
        self.assertLessEqual(len(disclosed), 4)
        self.assertNotIn("分部毛利率", " ".join(
            ex.get("title", "") for ex in self.exhibits))

    # ── the guided record ────────────────────────────────────────────────────
    def test_guidance_record_is_paired_on_the_guided_quarter(self) -> None:
        """Each Outlook block guides the quarter *after* the one being reported.

        Pairing a release to the quarter it reports rather than the one it
        guides would shift the entire record by one row and still look
        plausible, because consecutive quarters are similar. Two independent
        facts pin it: the release must fall inside the quarter it guides, and it
        must be the release that immediately precedes that quarter's own.
        """
        release_of = dict(zip(self.ends, self.source["release_dates"]))
        for index, end in enumerate(self.guide["period_ends"]):
            released = self.guide["guided_in_release"][index]
            with self.subTest(guided_quarter=end):
                self.assertLess(released, end)
                if end in release_of:
                    self.assertLess(released, release_of[end])

    def test_guidance_is_published_after_the_guided_quarter_has_begun(self) -> None:
        """The caveat that keeps 'never missed' honest.

        Broadcom publishes each quarter's outlook alongside the previous
        quarter's results, which lands about a third of the way into the quarter
        being guided. A record with no misses means something much weaker when
        part of the quarter is already banked, so the page prints this on every
        guidance chart -- and the numbers behind it are checked here.
        """
        for index, end in enumerate(self.guide["period_ends"]):
            days = self.guide["days_into_quarter_at_release"][index]
            length = self.guide["quarter_length_days"][index]
            with self.subTest(guided_quarter=end):
                self.assertGreater(days, 0, "guidance would be ex-ante, contradicting the page")
                self.assertLess(days, length)
        median = sorted(self.guide["days_into_quarter_at_release"])[
            len(self.guide["days_into_quarter_at_release"]) // 2]
        self.assertGreaterEqual(median, 24)
        self.assertLessEqual(median, 40)
        for exhibit in self.by_section["settled"][3:]:
            with self.subTest(exhibit=exhibit["n"]):
                self.assertIn("时点提醒", exhibit["note"] + exhibit.get("src_extra", ""))

    def test_guidance_form_flag_agrees_with_its_endpoints(self) -> None:
        """A point drawn as a band would invent a width the company never gave."""
        for index, form in enumerate(self.guide["revenue_form"]):
            lo = self.guide["guide_revenue_lo_usd_m"][index]
            hi = self.guide["guide_revenue_hi_usd_m"][index]
            mid = self.guide["guide_revenue_usd_m"][index]
            with self.subTest(quarter=self.guide["periods"][index], form=form):
                self.assertIn(form, ("range", "point"))
                if form == "point":
                    self.assertEqual(lo, mid)
                    self.assertEqual(hi, mid)
                else:
                    self.assertLess(lo, hi)
                    self.assertAlmostEqual((lo + hi) / 2, mid, places=6)

    def test_the_record_never_landed_below_the_guided_number(self) -> None:
        """The page's central claim, on both guided metrics."""
        finished = [i for i, v in enumerate(self.guide["actual_revenue_usd_m"]) if v is not None]
        self.assertGreaterEqual(len(finished), 24)
        for index in finished:
            with self.subTest(quarter=self.guide["periods"][index]):
                self.assertGreaterEqual(
                    self.guide["actual_revenue_usd_m"][index],
                    self.guide["guide_revenue_lo_usd_m"][index])
                self.assertGreaterEqual(
                    self.guide["actual_revenue_usd_m"][index],
                    self.guide["guide_revenue_usd_m"][index])
        margin = [i for i in finished
                  if self.guide["guide_ebitda_margin_pct"][i] is not None]
        self.assertGreaterEqual(len(margin), 18)
        for index in margin:
            with self.subTest(quarter=self.guide["periods"][index], metric="ebitda margin"):
                self.assertGreater(
                    self.guide["actual_ebitda_margin_pct"][index],
                    self.guide["guide_ebitda_margin_pct"][index])

    def test_every_range_quarter_landed_inside_its_range(self) -> None:
        """The other half of the two-sided finding: when there was a band, the
        quarter stayed in it -- above it zero times, below it zero times."""
        ranges = [i for i, f in enumerate(self.guide["revenue_form"]) if f == "range"]
        self.assertEqual(len(ranges), 5)
        for index in ranges:
            actual = self.guide["actual_revenue_usd_m"][index]
            with self.subTest(quarter=self.guide["periods"][index]):
                self.assertIsNotNone(actual)
                self.assertGreaterEqual(actual, self.guide["guide_revenue_lo_usd_m"][index])
                self.assertLessEqual(actual, self.guide["guide_revenue_hi_usd_m"][index])

    def test_actual_ebitda_margin_is_the_reported_ratio(self) -> None:
        by_end = dict(zip(self.ends, zip(self.fin["adjusted_ebitda"], self.fin["revenue"],
                                         self.fin["non_gaap_operating_income"])))
        for index, end in enumerate(self.guide["period_ends"]):
            if end not in by_end:
                continue
            ebitda, revenue, ng_oi = by_end[end]
            with self.subTest(period_end=end):
                self.assertAlmostEqual(self.guide["actual_ebitda_margin_pct"][index],
                                       ebitda / revenue * 100, places=3)
                self.assertAlmostEqual(
                    self.guide["actual_non_gaap_operating_margin_pct"][index],
                    ng_oi / revenue * 100, places=3)

    def test_beat_decomposition_is_an_identity(self) -> None:
        """actual − guided revenue × guided margin == revenue leg + margin leg."""
        checked = 0
        for index, guided_margin in enumerate(self.guide["guide_ebitda_margin_pct"]):
            actual_margin = self.guide["actual_ebitda_margin_pct"][index]
            if guided_margin is None or actual_margin is None:
                continue
            guided_revenue = self.guide["guide_revenue_usd_m"][index]
            actual_revenue = self.guide["actual_revenue_usd_m"][index]
            implied = guided_revenue * guided_margin / 100
            actual = self.guide["actual_adjusted_ebitda_usd_m"][index]
            revenue_leg = (actual_revenue - guided_revenue) * guided_margin / 100
            margin_leg = actual_revenue * (actual_margin - guided_margin) / 100
            with self.subTest(quarter=self.guide["periods"][index]):
                self.assertAlmostEqual(actual - implied, revenue_leg + margin_leg, delta=0.01)
                checked += 1
        self.assertGreaterEqual(checked, 18)

    def test_annual_only_guidance_covers_the_gaps_in_the_quarterly_record(self) -> None:
        """Eight reported quarters were never guided as quarters. The page shows
        them as gaps rather than zeros, and lists the annual guidance that
        replaced them, so the record's holes are visible instead of implied."""
        guided = set(self.guide["period_ends"])
        first = min(guided)
        gaps = [end for end in self.ends if end >= first and end not in guided]
        self.assertEqual(len(gaps), 8)
        self.assertEqual(len(self.source["annual_only_guidance"]), 8)
        for entry in self.source["annual_only_guidance"]:
            with self.subTest(released=entry["released"]):
                self.assertLess(entry["released"], entry["fiscal_year_end"])
                self.assertGreater(entry["revenue_usd_m"], 0)

    def test_non_gaap_operating_margin_guidance_has_no_record_yet(self) -> None:
        """It appears in exactly one of the 33 releases, so the page carries it
        as a single guided point and builds no delivery record for it."""
        single = self.source["non_gaap_operating_margin_guidance"]
        self.assertEqual(single["guided_in_release"], "2026-06-03")
        self.assertNotIn(single["period_end"], set(self.ends))

    # ── AI revenue is a different tier of disclosure ─────────────────────────
    def test_ai_revenue_is_labelled_as_a_quote_not_a_segment(self) -> None:
        """It comes from the CEO quote, not the Business Outlook block and not
        the segment note; mixing it into the formal record would overstate what
        the filings support."""
        ai = self.source["ai_semiconductor_disclosures"]
        self.assertIn(None, ai["actual_usd_bn"], "the quarter with no level must stay empty")
        self.assertTrue(any(ai["actual_is_floor"]), "the 'over $4.4 billion' floor must be flagged")
        chart = next(ex for ex in self.by_section["highlights"] if "AI 半导体收入" in ex["title"])
        self.assertIn("不是", chart["note"])
        self.assertIn("引语", chart["note"] + chart["src_extra"])
        self.assertNotIn("AI", " ".join(
            ex.get("title", "") for ex in self.by_section["settled"]))

    # ── the page ─────────────────────────────────────────────────────────────
    def test_page_is_chart_led(self) -> None:
        self.assertGreaterEqual(len(self.exhibits), 20)
        for exhibit in self.exhibits:
            with self.subTest(exhibit=exhibit.get("n")):
                self.assertTrue(exhibit.get("title"))
                self.assertTrue(exhibit.get("note"))
                self.assertIn("n", exhibit)

    def test_exhibit_numbers_are_sequential_and_refs_resolved(self) -> None:
        numbers = [ex["n"] for ex in self.exhibits]
        self.assertEqual(numbers, list(range(2, 2 + len(numbers))))
        for exhibit in self.exhibits:
            for field in ("title", "note", "src_extra"):
                with self.subTest(exhibit=exhibit["n"], field=field):
                    self.assertNotIn("{EX_", exhibit.get(field) or "")
                    self.assertNotIn("ref", exhibit)

    def test_section_order_matches_how_the_note_is_used(self) -> None:
        self.assertEqual([s["id"] for s in self.payload["sections"]],
                         ["settled", "highlights", "next_quarter", "routine"])

    def test_headroom_bars_reproduce_the_next_quarter_thresholds(self) -> None:
        entries = self.source["next_kpi"]["quantified"]
        chart = self.by_section["next_quarter"][0]
        self.assertEqual(chart["xlabels"], [e["metric"] for e in entries])
        for value, entry in zip(chart["values"], entries):
            with self.subTest(metric=entry["metric"]):
                self.assertAlmostEqual(
                    value, round(headroom(entry["direction"], entry["threshold"],
                                          entry["current"]), 1), places=6)

    def test_every_tracked_metric_with_a_series_gets_its_own_chart(self) -> None:
        entries = self.source["next_kpi"]["quantified"]
        charts = self.by_section["next_quarter"][1:]
        self.assertEqual(len(charts), len(entries))
        for entry, chart in zip(entries, charts):
            with self.subTest(metric=entry["metric"]):
                self.assertIn(entry["metric"], chart["title"])
        # The metrics that have no series must be named where the reader is
        # looking at the ones that do, not dropped silently.
        self.assertTrue(self.source["next_kpi"]["excluded"])
        self.assertIn(self.source["next_kpi"]["excluded"],
                      self.by_section["next_quarter"][0]["note"])

    def test_audit_tables_back_every_derived_exhibit(self) -> None:
        tables = self.payload["tables"]
        self.assertEqual([t["n"] for t in tables], list(range(1, len(tables) + 1)))
        for table in tables:
            with self.subTest(table=table["n"]):
                self.assertTrue(table["title"])
                self.assertTrue(table["rows"])
                for row in table["rows"]:
                    self.assertEqual(len(row), len(table["headers"]))

    def test_guidance_record_table_covers_every_guided_quarter(self) -> None:
        table = self.payload["tables"][0]
        self.assertEqual(len(table["rows"]), len(self.guide["period_ends"]))
        verdicts = {row[7] for row in table["rows"]}
        self.assertNotIn("低于下限", verdicts)
        self.assertNotIn("低于", verdicts)
        self.assertIn("待披露", verdicts)

    def test_avgo_is_absent_from_the_cross_page_capex_table(self) -> None:
        """Deliberate, and recorded here so a later change is a decision.

        The shared table runs hyperscaler cash capex -> NVDA Data Center -> TSMC
        wafers. Broadcom is neither a hyperscaler nor a foundry, and its own cash
        capex is about 1% of revenue, so adding a column would say nothing about
        the cycle and would rewrite every other page's payload to do it.
        """
        table = next(t for t in self.payload["tables"] if "AI capex" in t["title"])
        self.assertNotIn("AVGO", " ".join(table["headers"]))

    def test_market_expectation_is_labelled_and_unattributed(self) -> None:
        expectation = self.source["market_expectation"]
        self.assertTrue(expectation["as_of"])
        for banned in ("摩根", "高盛", "JPMorgan", "Goldman", "Morgan Stanley",
                       "Bernstein", "HSBC", "Macquarie", "RBC"):
            self.assertNotIn(banned, json.dumps(self.payload, ensure_ascii=False))

    def test_no_rating_or_target_price_is_published(self) -> None:
        """The words appear on the page only where it says it does not publish
        them, so scanning the whole payload would flag the disclaimer itself.
        What must be clean is everywhere a rating could actually be asserted:
        the headline, the takeaways, chart titles, and every audit-table cell.
        """
        published = [self.payload["headline"], self.payload["brief"],
                     self.payload["title"], self.payload["subtitle"]]
        published += [ex.get("title", "") for ex in self.exhibits]
        published += [str(cell) for table in self.payload["tables"]
                      for row in table["rows"] for cell in row]
        published += [h for table in self.payload["tables"] for h in table["headers"]]
        for banned in ("目标价", "评级", "增持", "减持", "买入", "卖出",
                       "target price", "Overweight", "Underweight"):
            for text in published:
                with self.subTest(term=banned, text=text[:40]):
                    self.assertNotIn(banned, text)
        notes = " ".join(self.payload["notes"])
        self.assertIn("不发布评级、目标价或估值", notes)

    def test_sources_are_official_http_links(self) -> None:
        for link in self.payload["source_links"]:
            with self.subTest(link=link["label"]):
                parsed = urlparse(link["url"])
                self.assertEqual(parsed.scheme, "https")
                self.assertIn(parsed.netloc, ("www.sec.gov", "investors.broadcom.com"))

    def test_published_payload_roster_and_shell(self) -> None:
        published = js_payload(ROOT / "data" / "avgo.js", "window.DASH")
        self.assertEqual(published, self.payload)
        roster = js_payload(ROOT / "data" / "roster.js", "window.ROSTER")
        self.assertEqual(roster, roster_payload(build_all()))
        entry = next(item for item in roster["items"] if item["slug"] == "avgo")
        self.assertEqual(entry["latest_label"], self.payload["latest"]["disclosed_period_label"])
        self.assertEqual(entry["release_date"], self.payload["latest"]["release_date"])
        self.assertEqual(entry["group"], "semiconductor_ai")
        self.assertIn(entry["group"], {group["key"] for group in roster["groups"]})

    def test_home_page_carries_the_new_company(self) -> None:
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="avgo/"', home)
        self.assertIn("Broadcom", home)
        cards = home.count('class="hcard"')
        self.assertEqual(cards, len(ENTRIES))
        masthead = re.search(r'<span class="meta">(\d+) 家公司 · (\d+) 季趋势</span>', home)
        self.assertIsNotNone(masthead, "masthead count line changed shape")
        self.assertEqual(int(masthead.group(1)), len(ENTRIES))
        self.assertEqual(int(masthead.group(2)), 8, "the second number is the window, not a count")

    def test_the_shell_links_the_payload_by_content_hash(self) -> None:
        """Every `?v=` in the committed shell must be that file's CURRENT digest.

        Checking the shape of the query string is not enough. A commit that
        updates `data/avgo.js` but leaves `avgo/index.html` out of its explicit
        path list publishes a shell that goes on stamping the previous payload's
        digest -- the bytes change, the URL does not, and a reader who already
        loaded the old payload keeps being served it from cache. This exact
        failure shipped on the SNPS page on 2026-08-29. The whole-suite run
        cannot see it, because tests run after `build/all.py` has regenerated
        the shell; asserting the digest by value is what catches it.
        """
        shell = (ROOT / "avgo" / "index.html").read_text(encoding="utf-8")
        self.assertIn("<title>AVGO Quarterly Results</title>", shell)
        sources = re.findall(r'<script src="\.\./([^"?]+)(?:\?v=([0-9a-f]+))?"', shell)
        self.assertEqual([name for name, _ in sources],
                         ["data/roster.js", "data/avgo.js", "assets/charts.js", "assets/page.js"])
        for name, digest in sources:
            with self.subTest(script=name):
                self.assertTrue(digest, f"{name} is served without a cache-busting version")
                expected = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()[: len(digest)]
                self.assertEqual(digest, expected, f"{name} carries a stale digest")

    def test_every_exhibit_matches_the_renderer_contract(self) -> None:
        """Charts that the renderer cannot draw fail silently in the browser.

        `assets/charts.js` dispatches on `kind` and looks `fmt` up in a table
        whose miss case falls back to one decimal place rather than raising, and
        it zips series values against `xlabels` positionally. So an unknown kind
        draws nothing, an unknown format quietly loses precision, and a series
        one element short shifts every point after the gap -- three failures that
        a passing build and a green suite would not otherwise notice.
        """
        js = (ROOT / "assets" / "charts.js").read_text(encoding="utf-8")
        kinds = set(re.findall(r"kind ?=== ?'([a-z_]+)'", js))
        formats = set(re.findall(r"^\s{4}([a-z0-9]+):\s*function", js, re.M))
        self.assertIn("grouped_bars", kinds)
        self.assertIn("pct1", formats)
        for exhibit in self.exhibits:
            with self.subTest(exhibit=exhibit["n"]):
                self.assertIn(exhibit["kind"], kinds)
                for key in ("fmt", "yfmt", "label_fmt"):
                    if key in exhibit:
                        self.assertIn(exhibit[key], formats)
                width = len(exhibit.get("xlabels", []))
                self.assertGreater(width, 0)
                if "values" in exhibit:
                    self.assertEqual(len(exhibit["values"]), width)
                for series in exhibit.get("groups", []) + exhibit.get("series", []):
                    self.assertEqual(len(series["values"]), width, series["name"])
                    self.assertTrue(any(v is not None for v in series["values"]),
                                    f"{series['name']} is entirely empty")
                for key in ("lo", "hi", "actual"):
                    if key in exhibit:
                        self.assertEqual(len(exhibit[key]), width)
                if exhibit.get("yoy"):
                    self.assertEqual(len(exhibit["yoy"]["values"]), width)

    def test_payload_carries_no_local_paths_or_private_material(self) -> None:
        blob = json.dumps(self.payload, ensure_ascii=False)
        for banned in ("/Users/", "OneDrive", "Obsidian", ".pptx", ".pdf", "transcript.pdf"):
            with self.subTest(term=banned):
                self.assertNotIn(banned, blob)


if __name__ == "__main__":
    unittest.main()
