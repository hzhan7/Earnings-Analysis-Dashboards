"""Samsung page: the reconciliations that license what the page publishes.

Three of these exist because of a failure mode this page hit and no other page
in the repo can hit:

- `test_quarters_sum_to_the_disclosed_full_year` is the check that would catch a
  column misread. Samsung's Earnings Release does not use a fixed column order:
  the 1Q 2024 deck prints `1Q24 | 4Q23 | 1Q23` (descending) while the 3Q 2024
  deck prints `3Q23 | 2Q24 | 3Q24` (ascending), and inside a single Q4 deck the
  cash-flow page reads `prior FY | Q4 | current FY` while the balance-sheet page
  beside it reads `prior year-end | prior quarter-end | current year-end`.
  Reading either by position yields a full set of plausible, finite, correctly
  formatted numbers that are simply the wrong quarters. The 2025 annual column
  is a different part of the deck from the quarterly columns, so this identity
  is a genuine second reading rather than the same input checked twice.
- `test_segment_revenue_exceeds_consolidated_every_quarter` pins the disclosure
  policy that makes the segment table look wrong: Samsung's segment revenue
  includes intersegment sales, so the four divisions must sum to MORE than
  consolidated revenue. A future edit that "fixed" this into balancing would be
  silently reporting a Samsung number that does not exist.
- `test_the_only_dollars_on_the_page_are_the_shared_cross_page_table` keeps the
  page in won. Samsung publishes no dollar financials, so any dollar figure the
  page produced itself would be a conversion it invented -- and `charts.js` has
  no won formatter, which makes reaching for `usd1` the easy mistake rather than
  the exotic one. The one dollar-denominated object here, the cross-page AI
  capex table, is asserted to still contain dollars rather than excluded
  silently: a test that cannot tell "none" from "some I forgot" is not a test.

The threshold entries deliberately use only unit keys `board.UNIT_FORMATS`
already carries (`pct`, `days`). There is no won formatter and this page does
not add one; a KRW magnitude key belongs to whichever page lands it first.
"""

from __future__ import annotations

import copy
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import samsung  # noqa: E402
from build.board import UNIT_FORMATS, cn_count, headroom  # noqa: E402


def js_payload(path: Path, marker: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{marker} = ", 1)[1].rstrip().rstrip(";")
    return json.loads(body)


# `charts.js` silently falls back to NAVY for any colour name it does not know,
# so a typo produces four same-coloured lines and a legend that still lists
# four series. The valid set is small enough to pin.
VALID_COLORS = {"NAVY", "BLUE", "MBLUE", "GRAY", "GREEN", "RED", "GOLD"}

# Slots `assets/page.js` writes with textContent or esc(): markup placed in any
# of them reaches the reader as visible angle brackets.
ESCAPED_SLOTS = ("tracker", "title", "subtitle", "headline")

MARKUP = re.compile(r"</?[a-z][a-z0-9]*>", re.I)


def exhibits(payload: dict) -> list[dict]:
    return [ex for section in payload["sections"] for ex in section["exhibits"]]


def series_values(exhibit: dict) -> list[list]:
    """Every plotted series in an exhibit, whatever kind it is."""
    out = []
    for key in ("values", "lo", "hi", "actual"):
        if isinstance(exhibit.get(key), list):
            out.append(exhibit[key])
    for key in ("groups", "series", "stacks"):
        for member in exhibit.get(key, []):
            out.append(member["values"])
    for key in ("bar", "line"):
        if isinstance(exhibit.get(key), dict):
            out.append(exhibit[key]["values"])
    return out


class SamsungDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(samsung.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = samsung.build_payload(cls.staging)
        cls.fin = cls.staging["financials_krw_bn"]
        cls.seg_rev = cls.staging["segment_revenue_krw_tn"]
        cls.seg_op = cls.staging["segment_operating_profit_krw_tn"]
        cls.cash = cls.staging["cash_flow_krw_tn"]

    # ── the source series ────────────────────────────────────────────────────
    def test_every_series_has_one_value_per_quarter(self) -> None:
        """One value per quarter, on an axis of consecutive calendar quarters.

        The window used to be pinned at eight here. A roll appends a quarter,
        so the pin would have failed every roll with nothing wrong on the page;
        what has to hold instead is that the axis is unbroken and that every
        aligned array has exactly one cell per quarter on it.
        """
        periods = self.staging["periods"]
        n = len(periods)
        for before, after in zip(periods, periods[1:]):
            self.assertEqual(samsung.shift_period(before, 1), after)
        quarter_end = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}
        self.assertEqual(len(self.staging["period_ends"]), n)
        for period, end in zip(periods, self.staging["period_ends"]):
            quarter, year = period.split()
            self.assertEqual(end, f"{year}-{quarter_end[int(quarter[1])]}")
        for block in ("financials_krw_bn", "segment_revenue_krw_tn",
                      "segment_operating_profit_krw_tn", "cash_flow_krw_tn",
                      "balance_sheet_krw_bn"):
            for name, values in self.staging[block].items():
                if not isinstance(values, list):
                    continue
                self.assertEqual(len(values), n, f"{block}.{name}")
        self.assertEqual(len(self.staging["net_cash_krw_tn"]), n)
        self.assertEqual(len(self.staging["final_release_dates"]), n)

    def test_income_statement_identities_close_every_quarter(self) -> None:
        """Revenue − COGS = gross, gross − SG&A = operating, PBT − tax = net."""
        fin = self.fin
        for i, period in enumerate(self.staging["periods"]):
            slack = 0.01
            with self.subTest(period=period):
                self.assertAlmostEqual(
                    fin["revenue"][i] - fin["cost_of_sales"][i],
                    fin["gross_profit"][i], delta=slack)
                self.assertAlmostEqual(
                    fin["gross_profit"][i] - fin["sga_expenses"][i],
                    fin["operating_profit"][i], delta=slack)
                self.assertAlmostEqual(
                    fin["profit_before_tax"][i] - fin["income_tax"][i],
                    fin["net_profit"][i], delta=slack)
                # R&D is a memo line inside SG&A, never larger than it.
                self.assertLess(fin["rnd_expenses"][i], fin["sga_expenses"][i])
                self.assertLessEqual(fin["profit_owners"][i], fin["net_profit"][i])

    def test_quarters_sum_to_the_disclosed_full_year(self) -> None:
        """The check that catches a column misread -- see this module's docstring.

        The 2025 annual figures come from the annual column of the 4Q 2025
        deck, a different part of the table from the quarterly columns, so
        agreement here is a second reading rather than a self-comparison.
        """
        annual = self.staging["annual_disclosed_2025"]
        q2025 = [i for i, p in enumerate(self.staging["periods"]) if p.endswith("2025")]
        self.assertEqual(len(q2025), 4)
        self.assertAlmostEqual(
            sum(self.fin["revenue"][i] for i in q2025) / 1000,
            annual["revenue_krw_tn"], delta=0.1)
        self.assertAlmostEqual(
            sum(self.fin["operating_profit"][i] for i in q2025) / 1000,
            annual["operating_profit_krw_tn"], delta=0.1)
        for key, target in (("operating", "cfo_krw_tn"),
                            ("depreciation", "depreciation_krw_tn"),
                            ("capex_ppe", "capex_ppe_krw_tn")):
            with self.subTest(row=key):
                self.assertAlmostEqual(
                    sum(self.cash[key][i] for i in q2025), annual[target], delta=0.02)

    def test_segment_revenue_exceeds_consolidated_every_quarter(self) -> None:
        """Segment revenue includes intersegment sales, so it must NOT balance.

        Samsung's own footnote: "the sales of business units include
        intersegment sales". The elimination has no line of its own in the
        deck, so the page derives it -- and a build that made these balance
        would be publishing a number Samsung does not report.
        """
        der = samsung.derived(self.staging)
        for i, period in enumerate(self.staging["periods"]):
            with self.subTest(period=period):
                self.assertGreater(der["segment_sum"][i], der["revenue_tn"][i])
                # The band was 8.0-10.0, fitted to eight quarters. Six earlier
                # quarters from Samsung's own decks land at 7.54% and 10.57%,
                # so the band was measuring the window rather than the company.
                # The strict claim is the line above -- segment revenue must
                # exceed consolidated, because it includes intersegment sales
                # and Samsung publishes no elimination line. This is the loose
                # sanity check around it. The comment above said it had been
                # sized to the record while the assertion still read 8.0-10.0
                # (the widening went out with the reverted 14-quarter trial) --
                # a pin that a roll would trip with nothing wrong on the page.
                # It is now sized to the record the comment cites, with room.
                self.assertTrue(7.0 <= der["elimination_share"][i] <= 11.0,
                                f"{period}: {der['elimination_share'][i]}")

    def test_segment_operating_profit_adds_up_to_consolidated(self) -> None:
        """The other side of the same footnote: operating profit has no elimination."""
        for i, period in enumerate(self.staging["periods"]):
            with self.subTest(period=period):
                total = sum(self.seg_op[key][i]
                            for key in ("dx", "ds", "sdc", "harman"))
                # Deck-sourced quarters carry one more unit of rounding slack:
                # the decks print KRW trillions to two decimals across four
                # segments, so 0.01 x 4 = 0.04 on top of the 0.11 the DART-era
                # quarters need.
                slack = 0.11
                self.assertAlmostEqual(
                    total, self.fin["operating_profit"][i] / 1000, delta=slack)

    def test_memory_never_exceeds_its_own_division(self) -> None:
        for i, period in enumerate(self.staging["periods"]):
            with self.subTest(period=period):
                self.assertLess(self.seg_rev["memory"][i], self.seg_rev["ds"][i])
                self.assertGreater(self.seg_rev["ds"][i] - self.seg_rev["memory"][i], 0)

    def test_dx_sub_segments_do_not_exceed_the_division(self) -> None:
        for i, period in enumerate(self.staging["periods"]):
            with self.subTest(period=period):
                self.assertLessEqual(
                    self.seg_rev["mx_nw"][i] + self.seg_rev["vd_da"][i],
                    self.seg_rev["dx"][i] + 1e-9)
                self.assertLessEqual(self.seg_rev["mx"][i], self.seg_rev["mx_nw"][i])
                self.assertLessEqual(self.seg_rev["vd"][i], self.seg_rev["vd_da"][i])

    def test_the_quarter_the_page_reports_is_the_last_one_in_the_series(self) -> None:
        latest = self.payload["latest"]
        self.assertEqual(latest["disclosed_period_label"], self.staging["periods"][-1])
        self.assertEqual(latest["release_date"], self.staging["final_release_dates"][-1])
        # release_date is the month-end full release, never the quarter-end flash.
        self.assertEqual(latest["release_date"],
                         self.staging["provisional_vs_final"]["final_date"][-1])
        self.assertNotEqual(latest["release_date"],
                            self.staging["provisional_vs_final"]["flash_date"][-1])
        self.assertEqual(latest["status"], "history_ready")
        self.assertEqual(latest["audit_status"], "unaudited")

    def test_the_flash_is_always_earlier_and_coarser_than_the_final(self) -> None:
        prov = self.staging["provisional_vs_final"]
        for i, quarter in enumerate(prov["quarters"]):
            with self.subTest(quarter=quarter):
                self.assertLess(prov["flash_date"][i], prov["final_date"][i])
                # The flash revenue is published rounded to the whole trillion,
                # which is why the page charts only the operating-profit gap.
                self.assertEqual(prov["flash_revenue_krw_tn"][i] % 1, 0.0)
                self.assertLessEqual(
                    abs(prov["final_operating_profit_krw_tn"][i]
                        - prov["flash_operating_profit_krw_tn"][i]), 0.5)

    # ── the payload the browser receives ─────────────────────────────────────
    def test_exhibits_are_numbered_in_render_order_from_two(self) -> None:
        numbers = [ex["n"] for ex in exhibits(self.payload)]
        self.assertEqual(numbers, list(range(2, 2 + len(numbers))))
        self.assertEqual(len(self.payload["sections"]), 4)
        self.assertEqual([s["id"] for s in self.payload["sections"]],
                         ["settled", "quarter_highlights", "next_quarter", "routine"])

    def test_every_exhibit_plots_one_point_per_x_label(self) -> None:
        """The structural identity a NaN scan cannot see: a series one short of
        its own axis draws a chart that is silently missing a bar."""
        for ex in exhibits(self.payload):
            with self.subTest(n=ex["n"], kind=ex["kind"]):
                width = len(ex["xlabels"])
                self.assertGreater(width, 0)
                for values in series_values(ex):
                    self.assertEqual(len(values), width)

    def test_no_exhibit_carries_an_unresolved_reference_placeholder(self) -> None:
        for ex in exhibits(self.payload):
            for field in ("title", "note", "src_extra", "annot"):
                text = ex.get(field)
                if isinstance(text, str):
                    self.assertNotRegex(text, r"\{EX_[A-Z_]+\}",
                                        f"exhibit {ex['n']} {field}")

    def test_every_colour_name_is_one_the_renderer_knows(self) -> None:
        """An unknown colour silently falls back to NAVY, so two series merge."""
        for ex in exhibits(self.payload):
            for key in ("groups", "series", "stacks"):
                for member in ex.get(key, []):
                    self.assertIn(member.get("color"), VALID_COLORS, f"exhibit {ex['n']}")
            for key in ("bar", "line"):
                member = ex.get(key)
                if isinstance(member, dict) and "color" in member:
                    self.assertIn(member["color"], VALID_COLORS, f"exhibit {ex['n']}")

    def test_stacked_dual_declares_a_right_axis_ceiling_above_its_own_data(self) -> None:
        """`charts.js` hardcodes the right axis to 60 when `ymax` is absent.

        Memory's share of group revenue is already above 70%, so without an
        explicit ceiling the line would be drawn at a negative y, clipped away
        by the browser, and still listed in the legend -- with every coordinate
        a finite, legal number that a NaN check cannot see.
        """
        stacked = [ex for ex in exhibits(self.payload) if ex["kind"] == "stacked_dual"]
        self.assertTrue(stacked)
        for ex in stacked:
            with self.subTest(n=ex["n"]):
                ceiling = ex["line"].get("ymax")
                self.assertIsNotNone(ceiling)
                self.assertGreaterEqual(ceiling, max(ex["line"]["values"]))

    def test_the_page_uses_no_gs_bar_and_no_unexercised_kind(self) -> None:
        """Kept off `gs_bar` on purpose: its census assertion is pinned by an
        equality in `test_chart_contract.py`, and its `avg12` branch has never
        been walked by real data. Nothing here needs it."""
        kinds = {ex["kind"] for ex in exhibits(self.payload)}
        self.assertNotIn("gs_bar", kinds)
        self.assertEqual(kinds - {"lines", "grouped_bars", "diverging_bars",
                                  "range_band", "bars_labeled", "bar_line_dual",
                                  "stacked_dual"}, set())

    def test_literal_slots_and_page_notes_carry_no_markup(self) -> None:
        """These reach the reader through textContent or esc()."""
        for slot in ESCAPED_SLOTS:
            self.assertNotRegex(self.payload[slot], MARKUP, slot)
        for note in self.payload["notes"]:
            self.assertNotRegex(note, MARKUP)
        for section in self.payload["sections"]:
            self.assertNotRegex(section["title"], MARKUP)
            self.assertNotRegex(section["description"], MARKUP)
        for table in self.payload["tables"]:
            self.assertNotRegex(table["title"], MARKUP)
        for ex in exhibits(self.payload):
            self.assertNotRegex(ex["title"], MARKUP, f"exhibit {ex['n']} title")

    def test_the_only_dollars_on_the_page_are_the_shared_cross_page_table(self) -> None:
        """Samsung publishes no dollar financials; a dollar figure this page
        produced itself would be a conversion it invented. `charts.js` has no
        won formatter, which makes `usd1` the easy wrong reach.

        The one legitimate exception is pinned rather than hidden:
        `ai_capex_cycle_table` is published byte-identically on all 26 pages and
        is denominated in dollars by construction. Excluding it silently would
        leave a test that cannot tell "no dollars" from "dollars I forgot about".
        """
        shared = next(t for t in self.payload["tables"] if "跨页对照" in t["title"])
        self.assertIn("US$", json.dumps(shared, ensure_ascii=False))

        own = dict(self.payload)
        own["tables"] = [t for t in self.payload["tables"] if t is not shared]
        blob = json.dumps(own, ensure_ascii=False)
        self.assertNotIn("US$", blob)
        self.assertNotRegex(blob, r"\$\d")
        for ex in exhibits(self.payload):
            for key in ("fmt", "yfmt", "label_fmt"):
                self.assertFalse(str(ex.get(key, "")).startswith("usd"),
                                 f"exhibit {ex['n']} {key}")
            for member_key in ("bar", "line"):
                member = ex.get(member_key)
                if isinstance(member, dict):
                    self.assertFalse(str(member.get("yfmt", "")).startswith("usd"),
                                     f"exhibit {ex['n']} {member_key}.yfmt")

    def test_no_source_on_this_page_points_at_edgar(self) -> None:
        """Samsung is not an SEC registrant: CIK 0000879316 holds only
        ownership and tender-offer forms, newest 2015. Every other page here
        traces to EDGAR; this one must not.

        The scan is on the *sourcing* fields only, not on prose. The page says
        the words "EDGAR" and "20-F" on purpose -- to state that it has neither
        -- so a blob-wide token ban would fail on its own disclosure and get
        deleted, which is how a gate that false-fails stops protecting anything.
        """
        sourcing = [link["url"] for link in self.payload["source_links"]]
        sourcing.append(self.payload["source_url"])
        sourcing += [ex.get("src_extra", "") for ex in exhibits(self.payload)]
        for text in sourcing:
            for token in ("sec.gov", "EDGAR", "edgar", "10-Q", "10-K"):
                self.assertNotIn(token, text)
        disclosure = " ".join(self.payload["notes"])
        self.assertIn("三星电子不是 SEC 注册人", disclosure)
        self.assertIn("0000879316", disclosure)

    def test_sources_are_official_https_links(self) -> None:
        allowed = {"www.samsung.com", "images.samsung.com", "dart.fss.or.kr", "ecos.bok.or.kr"}
        self.assertTrue(self.payload["source_links"])
        for link in self.payload["source_links"]:
            with self.subTest(url=link["url"]):
                self.assertTrue(link["url"].startswith("https://"))
                host = link["url"].split("/")[2]
                self.assertIn(host, allowed)
                self.assertTrue(link["label"].strip())
        self.assertIn(self.payload["source_url"],
                      [link["url"] for link in self.payload["source_links"]])

    def test_guidance_slot_is_empty_because_the_company_guides_no_financials(self) -> None:
        """Samsung gives no revenue, margin or profit guidance at all. The page
        must not manufacture one out of the qualitative bit-shipment phrase.

        The quarter's own guidance block says so in two flags, and a block that
        says otherwise stops the build: every section of this page is written
        on that premise, so a quarter that breaks it needs a rebuilt first
        section rather than a changed sentence.
        """
        self.assertIsNone(self.payload["guidance"])
        guidance = self.staging["guidance"]
        self.assertFalse(guidance["guides_financials"])
        self.assertFalse(guidance["asp_guided"])
        asp = next(item for item in guidance["items"] if "ASP" in item["metric"])
        self.assertEqual(asp["quantified"], "未披露")
        for flag in ("guides_financials", "asp_guided"):
            broken = copy.deepcopy(self.staging)
            broken["guidance"][flag] = True
            with self.subTest(flag=flag):
                with self.assertRaisesRegex(ValueError, "guiding neither"):
                    samsung.build_payload(broken)

    # ── the threshold block ──────────────────────────────────────────────────
    def test_thresholds_use_only_units_the_shared_formatter_carries(self) -> None:
        """This page adds no unit key to `board.UNIT_FORMATS`; a won magnitude
        belongs to whichever page lands it first."""
        for entry in self.staging["next_kpi"]["entries"]:
            with self.subTest(metric=entry["metric"]):
                self.assertIn(entry["unit"], UNIT_FORMATS)
                self.assertIn(entry["unit"], {"pct", "days"})
                self.assertIn(entry["direction"], ("up", "down"))
                self.assertNotEqual(entry["threshold"], 0)
                self.assertTrue(entry["why"].strip())

    def test_threshold_current_values_match_the_series(self) -> None:
        der = samsung.derived(self.staging)
        expected = {
            "合并营业利润率": der["operating_margin"][-1],
            "Memory 占合并收入": der["memory_share"][-1],
            "DX 分部营业利润率": der["dx_margin"][-1],
            "库存天数": der["inventory_days"][-1],
            "现金 CapEx / 经营现金流": der["capex_to_cfo"][-1],
            "SDC 分部营业利润率": der["sdc_margin"][-1],
            "有效税率": der["effective_tax"][-1],
        }
        by_metric = {e["metric"]: e for e in self.staging["next_kpi"]["entries"]}
        for metric, value in expected.items():
            with self.subTest(metric=metric):
                self.assertAlmostEqual(by_metric[metric]["current"], value, places=1)

    def test_the_headroom_chart_agrees_with_the_audit_table(self) -> None:
        chart = next(ex for ex in exhibits(self.payload)
                     if ex["kind"] == "diverging_bars" and "距阈值" in ex["legend"])
        entries = self.staging["next_kpi"]["entries"]
        self.assertEqual(chart["xlabels"], [e["metric"] for e in entries])
        self.assertEqual(
            chart["values"],
            [round(headroom(e["direction"], e["threshold"], e["current"]), 1)
             for e in entries])

    def test_the_dx_sentences_follow_the_dx_line(self) -> None:
        """The handset loss is written up only while the data has one.

        This used to assert the loss itself (DX negative, exactly once, DS above
        60%) -- facts about one quarter, which a roll into a quarter where DX
        is back in profit would have turned red with nothing wrong on the page.
        What must hold every quarter is that the page's DX sentences agree with
        the DX line, so both directions are checked here.
        """
        der = samsung.derived(self.staging)
        blob = json.dumps(self.payload, ensure_ascii=False)
        losses = sum(1 for v in der["dx_margin"] if v < 0)
        quarters = cn_count(len(self.staging["periods"]))
        claims = (f"{quarters}季首次为负", f"{quarters}季首次营业亏损", "唯一的负值",
                  "唯一一次分部亏损", "DX 那根负柱")
        if der["dx_margin"][-1] < 0 and losses == 1:
            for claim in claims:
                self.assertIn(claim, blob)
        recovered = copy.deepcopy(self.staging)
        recovered["segment_operating_profit_krw_tn"]["dx"][-1] = 1.2
        after = json.dumps(samsung.build_payload(recovered), ensure_ascii=False)
        for claim in claims:
            with self.subTest(claim=claim):
                self.assertNotIn(claim, after)

    # ── the numeric-band readings the page makes from company wording ────────
    def test_bit_bands_are_ordered_and_the_actual_sits_inside_its_own_band(self) -> None:
        bits = self.staging["memory_bit_and_price"]
        for name in ("dram", "nand"):
            low = bits[f"{name}_bit_guide_low"]
            high = bits[f"{name}_bit_guide_high"]
            actual = bits[f"{name}_bit_actual"]
            for i, quarter in enumerate(bits["quarters"]):
                with self.subTest(product=name, quarter=quarter):
                    if low[i] is None:
                        self.assertIsNone(high[i])
                        continue
                    self.assertLess(low[i], high[i])
                    self.assertIsNotNone(actual[i])
        guide = bits["next_quarter_guide"]
        self.assertLess(guide["dram_low"], guide["dram_high"])
        self.assertLess(guide["nand_low"], guide["nand_high"])
        # Every wording the page turns into a number is published beside it.
        for i in range(len(bits["quarters"])):
            self.assertTrue(bits["dram_bit_actual_wording"][i].strip())
            self.assertTrue(bits["dram_asp_qoq_wording"][i].strip())

    def test_price_beat_volume_only_while_the_record_says_so(self) -> None:
        """The claim the first section is built on -- the variable the company
        guides moved single digits while the one it never guides moved tens of
        per cent -- is printed only while every quarter on record bears it out.

        It used to be asserted as a fact about the record (every ASP above 20%,
        every bit move below 20%), which a quarter of falling prices would have
        turned red with the page itself still right. Now the data decides the
        sentence, and one quarter of small price moves must take it off the page.
        """
        bits = self.staging["memory_bit_and_price"]
        claims = ("本轮业绩不是由被指引的那个变量决定的", "决定业绩的是价")
        dominant = all(
            min(abs(bits["dram_asp_qoq_pct"][i]), abs(bits["nand_asp_qoq_pct"][i]))
            > max([abs(v) for v in (bits["dram_bit_actual"][i], bits["nand_bit_actual"][i])
                   if v is not None], default=0)
            for i in range(len(bits["quarters"])))
        blob = json.dumps(self.payload, ensure_ascii=False)
        for claim in claims:
            self.assertEqual(claim in blob, dominant, claim)
        flat = copy.deepcopy(self.staging)
        flat["memory_bit_and_price"]["nand_asp_qoq_pct"][-1] = 1.0
        after = json.dumps(samsung.build_payload(flat), ensure_ascii=False)
        for claim in claims:
            with self.subTest(claim=claim):
                self.assertNotIn(claim, after)

    def test_every_numeric_reading_follows_the_pages_own_rule(self) -> None:
        """「about X%」取 X、low X0% 取 X1、mid-X0% 取 X5、high X0% 取 X8.

        The note prints each phrase beside the number the bar is drawn at, and
        it used to print 「high 80%」取 88 and 「high 60%」取 65 in the same
        sentence -- the second is the rule's mid reading. Each bar is checked
        against its own phrase, and each phrase against the wording it quotes.
        """
        bits = self.staging["memory_bit_and_price"]
        offset = {"low": 1, "mid": 5, "high": 8}
        for name in ("dram", "nand"):
            for i, quarter in enumerate(bits["quarters"]):
                phrase = bits[f"{name}_asp_qoq_phrase"][i]
                with self.subTest(product=name, quarter=quarter):
                    self.assertIn(phrase, bits[f"{name}_asp_qoq_wording"][i])
                    match = re.match(r"^(?:about (\d+)%|(low|mid|high)[ -](\d)0% ?(?:range)?)$", phrase)
                    self.assertIsNotNone(match, phrase)
                    expected = (float(match.group(1)) if match.group(1) else
                                float(match.group(3)) * 10 + offset[match.group(2)])
                    self.assertEqual(bits[f"{name}_asp_qoq_pct"][i], expected)
                    self.assertIn(f"「{phrase}」取 {expected:.0f}",
                                  next(ex for ex in exhibits(self.payload)
                                       if ex["title"].startswith("同期公司自述的环比 ASP"))["note"])

    def test_the_company_verdicts_agree_with_the_numeric_bands(self) -> None:
        """met / exceeded / missed is the company's own word for each quarter;
        where the page also holds the guided band and the actual, the two
        readings have to agree, or the "全部达标或超标" sentence rests on one of
        them being wrong."""
        bits = self.staging["memory_bit_and_price"]
        for name in ("dram", "nand"):
            for i, quarter in enumerate(bits["quarters"]):
                low, high = bits[f"{name}_bit_guide_low"][i], bits[f"{name}_bit_guide_high"][i]
                actual = bits[f"{name}_bit_actual"][i]
                verdict = bits[f"{name}_bit_vs_guide"][i]
                with self.subTest(product=name, quarter=quarter):
                    self.assertIn(verdict, ("met", "exceeded", "missed"))
                    if low is None or actual is None:
                        continue
                    expected = ("exceeded" if actual > high else
                                "missed" if actual < low else "met")
                    self.assertEqual(verdict, expected)

    # ── audit tables ─────────────────────────────────────────────────────────
    def test_tables_are_numbered_from_one_and_carry_the_shared_capex_table(self) -> None:
        tables = self.payload["tables"]
        self.assertEqual([t["n"] for t in tables], list(range(1, len(tables) + 1)))
        for table in tables:
            with self.subTest(table=table["n"]):
                self.assertTrue(table["rows"])
                for row in table["rows"]:
                    self.assertEqual(len(row), len(table["headers"]))
        cross_page = [t for t in tables if "跨页对照" in t["title"]]
        self.assertEqual(len(cross_page), 1)
        # Carrying the table is not the same as being a column in it: Samsung is
        # on the supply side of the AI capex cycle, not among the four buyers.
        self.assertNotIn("Samsung", " ".join(cross_page[0]["headers"]))

    def test_the_window_tables_have_one_row_per_quarter(self) -> None:
        """The four window tables name the window's length in their titles, and
        that length is the series' own, not a typed 「八季」."""
        n = len(self.staging["periods"])
        window = [t for t in self.payload["tables"] if t["title"].startswith(f"{cn_count(n)}季")]
        self.assertEqual(len(window), 4)
        for table in window:
            self.assertEqual(len(table["rows"]), n, table["title"])
            self.assertEqual([row[0] for row in table["rows"]], self.staging["periods"])

    # ── published artefacts ──────────────────────────────────────────────────
    def test_published_payload_and_shell(self) -> None:
        self.assertEqual(js_payload(ROOT / "data" / "samsung.js", "window.DASH"),
                         self.payload)
        shell = (ROOT / "samsung" / "index.html").read_text(encoding="utf-8")
        self.assertIn("../data/samsung.js", shell)
        self.assertNotIn("../data/tsm.js", shell)
        self.assertIn("<title>005930.KS Quarterly Results</title>", shell)

    def test_the_roster_entry_matches_the_payload(self) -> None:
        roster = js_payload(ROOT / "data" / "roster.js", "window.ROSTER")
        entry = next(item for item in roster["items"] if item["slug"] == "samsung")
        self.assertEqual(entry["latest_label"],
                         self.payload["latest"]["disclosed_period_label"])
        self.assertEqual(entry["release_date"], self.payload["latest"]["release_date"])
        self.assertEqual(entry["group"], "semiconductor_ai")
        self.assertIn(entry["group"], {g["key"] for g in roster["groups"]})
        # The README paragraph matches company names by two-way containment.
        self.assertIn("Samsung", entry["aliases"])


class SamsungRollTest(unittest.TestCase):
    """What a quarter roll has to change in `series/samsung.json`, and what the
    page does when it does not.

    Everything that belongs to one quarter -- the call quotes and the bonus
    accrual and the Bank of Korea rates behind the currency note
    (`quarter_story`), the forward statements (`guidance`), the thresholds
    (`next_kpi`), the bit and price record, the flash-versus-final record, the next
    quarter's bit guide -- carries the quarter it describes. A block stamped
    with another quarter is last quarter's story and stops the build; a block
    that is absent means this quarter has no such story, and the page leaves
    that part out rather than borrowing it.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads(samsung.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = samsung.build_payload(cls.source)
        cls.blob = json.dumps(cls.payload, ensure_ascii=False)

    def build(self, staging: dict) -> str:
        return json.dumps(samsung.build_payload(staging), ensure_ascii=False)

    def test_a_block_stamped_with_another_quarter_stops_the_build(self) -> None:
        tamper = {
            "quarter_story": lambda d: d["quarter_story"].__setitem__("period", "Q1 1999"),
            "guidance": lambda d: d["guidance"].__setitem__("period", "Q1 1999"),
            "guidance.quarter": lambda d: d["guidance"].__setitem__("quarter", "Q1 1999"),
            "next_kpi": lambda d: d["next_kpi"].__setitem__("period", "Q1 1999"),
            "fx quarters": lambda d: d["quarter_story"]["krw_per_usd_average"]["quarters"].__setitem__(-1, "Q1 1999"),
            "bits": lambda d: d["memory_bit_and_price"]["quarters"].__setitem__(-1, "Q1 1999"),
            "next_bit_guide": lambda d: d["memory_bit_and_price"]["next_quarter_guide"].__setitem__("quarter", "Q1 1999"),
            "flash": lambda d: d["provisional_vs_final"]["quarters"].__setitem__(-1, "Q1 1999"),
        }
        for name, change in tamper.items():
            stale = copy.deepcopy(self.source)
            change(stale)
            with self.subTest(block=name):
                with self.assertRaisesRegex(ValueError, "stamped|guides"):
                    samsung.build_payload(stale)
        stale = copy.deepcopy(self.source)
        release = f"Samsung {samsung.deck_period(self.source['periods'][-1])} Earnings Release"
        stale["sources"] = [item for item in stale["sources"] if not item["label"].startswith(release)]
        self.assertLess(len(stale["sources"]), len(self.source["sources"]))
        with self.assertRaisesRegex(ValueError, "sources"):
            samsung.build_payload(stale)

    def test_a_quarter_without_a_story_leaves_it_out(self) -> None:
        story = self.source["quarter_story"]
        bonus = story["special_bonus"]
        present = (f"{bonus['basis']}的 {bonus['pct']:.1f}%", f"{story['accrual_capex_krw_tn']:.1f} 兆韩元",
                   f"约 {story['fx_operating_profit_qoq_krw_tn']:.1f} 兆韩元",
                   story["dx_outlook_quote"], story["dx_reason_quote"], "季度历史新高",
                   "公司自称缺货", "随销售结转", "韩国银行", "ecos.bok.or.kr")
        for text in present:
            self.assertIn(text, self.blob)
        bare = copy.deepcopy(self.source)
        del bare["quarter_story"]
        after = self.build(bare)
        for text in present:
            with self.subTest(text=text):
                self.assertNotIn(text, after)

        unguided = copy.deepcopy(self.source)
        del unguided["guidance"]
        payload = samsung.build_payload(unguided)
        self.assertEqual(len(payload["tables"]), len(self.payload["tables"]) - 1)
        self.assertEqual([t["n"] for t in payload["tables"]],
                         list(range(1, len(payload["tables"]) + 1)))
        after = json.dumps(payload, ensure_ascii=False)
        for text in ("公司对价格从不给指引", "一个字都没给", "对 ASP 一个字都不给"):
            with self.subTest(text=text):
                self.assertIn(text, self.blob)
                self.assertNotIn(text, after)

    def test_a_sell_side_range_in_the_series_does_not_reach_the_page(self) -> None:
        """The page used to print a sell-side range for next quarter's ASP under
        one threshold. No original source for it was found (2026-09-19), and the
        site publishes a market expectation only as a dated, unattributed point
        with a checkable source, so the builder no longer reads such a block at
        all: putting one back into the series must leave the page byte-identical.
        """
        seeded = copy.deepcopy(self.source)
        seeded["next_kpi"]["sellside_asp_assumption"] = {
            "quarter": samsung.shift_period(self.source["periods"][-1], 1),
            "low_pct": 12, "high_pct": 20, "source": "test"}
        self.assertEqual(self.build(seeded), self.blob)
        self.assertNotIn("卖方对", self.blob)

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        """Break each "all / first / only / highest" claim in the data once; the
        sentence that made it must go. A sentence that survived its counter-
        example would be a remembered claim, not a computed one."""
        cases = {
            "flash revised down once": (
                lambda d: d["provisional_vs_final"]["final_operating_profit_krw_tn"].__setitem__(
                    0, d["provisional_vs_final"]["flash_operating_profit_krw_tn"][0] - 0.05),
                ("全部为正", "都没有下修", "全部为正上修")),
            "a bit guide missed": (
                lambda d: d["memory_bit_and_price"]["nand_bit_vs_guide"].__setitem__(-1, "missed"),
                ("全部达标或超标",)),
            "margin below its peak": (
                lambda d: d["financials_krw_bn"]["operating_profit"].__setitem__(
                    -1, d["financials_krw_bn"]["operating_profit"][-2]
                    / d["financials_krw_bn"]["revenue"][-2] * d["financials_krw_bn"]["revenue"][-1] * 0.9),
                ("本季是窗口内最高",)),
            "R&D below an earlier quarter": (
                lambda d: d["financials_krw_bn"]["rnd_expenses"].__setitem__(
                    -1, min(d["financials_krw_bn"]["rnd_expenses"]) - 1),
                ("创季度新高", "季度历史新高")),
            "non-memory DS grew": (
                lambda d: d["segment_revenue_krw_tn"]["ds"].__setitem__(
                    -1, d["segment_revenue_krw_tn"]["memory"][-1] + 9.0),
                ("没有增长", "全部增量都是存储")),
            "flash revenue no longer drawn from the same weeks": (
                lambda d: d["provisional_vs_final"]["flash_date"].__setitem__(-1, "2026-07-28"),
                ("季末后 1–2 周",)),
        }
        for name, (change, claims) in cases.items():
            broken = copy.deepcopy(self.source)
            change(broken)
            after = self.build(broken)
            for claim in claims:
                with self.subTest(case=name, claim=claim):
                    self.assertIn(claim, self.blob)
                    self.assertNotIn(claim, after)

    def test_the_days_title_says_which_way_each_line_moved(self) -> None:
        """It said 「两条同时在涨」 while receivable days had fallen from 55 to 51."""
        der = samsung.derived(self.source)
        chart = next(ex for ex in exhibits(self.payload) if ex["title"].startswith("库存天数"))
        inventory_up = der["inventory_days"][-1] > der["inventory_days"][-2]
        receivable_up = der["receivable_days"][-1] > der["receivable_days"][-2]
        expected = {(True, True): "两条同时在涨", (False, False): "两条同时在降",
                    (True, False): "库存在涨、应收在降", (False, True): "库存在降、应收在涨"}
        self.assertTrue(chart["title"].endswith(expected[(inventory_up, receivable_up)]),
                        chart["title"])
        both_up = copy.deepcopy(self.source)
        both_up["balance_sheet_krw_bn"]["receivables"][-1] *= 1.2
        payload = samsung.build_payload(both_up)
        title = next(ex for ex in exhibits(payload) if ex["title"].startswith("库存天数"))["title"]
        self.assertTrue(title.endswith("两条同时在涨"), title)

    def test_the_window_start_is_named_by_its_label(self) -> None:
        """The first point of the window was called 「八季前」 while it is seven
        quarters before the last; the eight-quarters-ago figure is a different
        number (Q2 2024's operating margin was 14.1%, the chart's first point is
        Q3 2024's 11.6%). Each comparison with the window start names it."""
        der = samsung.derived(self.source)
        first = samsung.compact_period(self.source["periods"][0])
        top = next(ex for ex in exhibits(self.payload) if ex["title"].startswith("合并收入"))
        self.assertIn(f"（{first} 为 {der['operating_margin'][0]:.1f}%）", top["title"])
        self.assertNotIn("八季前", self.blob)
        self.assertNotIn(f"{cn_count(len(self.source['periods']))}季前", self.blob)


class SamsungChecksTest(unittest.TestCase):
    """The page's quarter against a record keyed separately from the release.

    `_checks` is typed once per quarter from Samsung's own Earnings Release
    deck (the trillions and percentages it prints), with the page it was read
    from; the series carries the DART-based billions and the deck's two-decimal
    cash-flow lines. The builder never reads `_checks` (asserted in
    `test_data_only_roll`). A roll that misaligns a column, drops the new
    quarter or keeps last quarter's sentence fails here. Where the page prints
    a ratio it computes and the deck prints the same ratio, they must round to
    the same figure: the page uses the company's number when they differ.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(samsung.STAGING_PATH.read_text(encoding="utf-8"))
        cls.checks = cls.staging["_checks"]
        cls.payload = samsung.build_payload(cls.staging)
        cls.der = samsung.derived(cls.staging)
        cls.exhibits = exhibits(cls.payload)

    def test_the_page_names_the_checked_quarter(self) -> None:
        self.assertIn(self.checks["period"], self.payload["title"])
        self.assertIn(f"截至 {self.checks['period_end']}", self.payload["subtitle"])
        self.assertIn(f"发布 {self.checks['release_date']}", self.payload["subtitle"])
        self.assertIn(samsung.deck_period(self.checks["period"]), self.payload["source"])

    def test_the_series_ends_on_the_deck_figures(self) -> None:
        c, fin = self.checks, self.staging["financials_krw_bn"]
        seg_rev = self.staging["segment_revenue_krw_tn"]
        seg_op = self.staging["segment_operating_profit_krw_tn"]
        cash = self.staging["cash_flow_krw_tn"]
        bs = self.staging["balance_sheet_krw_bn"]
        # DART's billions, rounded the way the deck prints trillions: the two
        # chains agreeing on the new quarter is what the sourcing line claims.
        self.assertEqual(round(fin["revenue"][-1] / 1000, 1), c["revenue_krw_tn"])
        self.assertEqual(round(fin["operating_profit"][-1] / 1000, 1), c["operating_profit_krw_tn"])
        self.assertEqual(round(fin["rnd_expenses"][-1] / 1000, 1), c["rnd_krw_tn"])
        self.assertEqual(fin["eps_krw"][-1], c["eps_krw"])
        for key in ("ds", "memory", "dx", "sdc", "harman"):
            self.assertEqual(seg_rev[key][-1], c[f"{key}_revenue_krw_tn"], key)
        for key in ("ds", "dx", "sdc", "harman"):
            self.assertEqual(seg_op[key][-1], c[f"{key}_operating_profit_krw_tn"], key)
        self.assertEqual(cash["operating"][-1], c["operating_cash_flow_krw_tn"])
        self.assertEqual(cash["capex_ppe"][-1], c["purchase_of_ppe_krw_tn"])
        self.assertEqual(cash["depreciation"][-1], c["depreciation_krw_tn"])
        self.assertEqual(self.staging["net_cash_krw_tn"][-1], c["net_cash_krw_tn"])
        self.assertEqual(bs["total_assets"][-1], c["total_assets_krw_bn"])
        self.assertEqual(bs["inventories"][-1], c["inventories_krw_bn"])
        self.assertEqual(bs["receivables"][-1], c["receivables_krw_bn"])

    def test_the_ratios_the_page_computes_round_to_the_ones_the_deck_prints(self) -> None:
        c, der, fin = self.checks, self.der, self.staging["financials_krw_bn"]
        self.assertEqual(round(der["gross_margin"][-1], 1), c["gross_margin_pct"])
        self.assertEqual(round(der["operating_margin"][-1], 1), c["operating_margin_pct"])
        self.assertEqual(round(der["net_margin"][-1], 1), c["owners_margin_pct"])
        self.assertEqual(round(der["dx_margin"][-1]), c["dx_operating_margin_pct"])
        self.assertEqual(round(pct_change := (fin["rnd_expenses"][-1] / fin["rnd_expenses"][-2] - 1) * 100),
                         c["rnd_qoq_pct"], pct_change)

    def test_the_page_prints_the_checked_figures(self) -> None:
        c = self.checks
        headline = self.payload["headline"]
        self.assertIn(f"合并收入 {c['revenue_krw_tn']:.1f} 兆韩元", headline)
        self.assertIn(f"营业利润 {c['operating_profit_krw_tn']:.1f} 兆韩元", headline)
        self.assertIn(f"营业利润率 {c['operating_margin_pct']:.1f}%", headline)
        margins = next(ex for ex in self.exhibits if ex["title"].startswith("三条利润率"))
        self.assertIn(f"毛利率 {c['gross_margin_pct']:.1f}%", margins["title"])
        self.assertIn(f"归母净利率 {c['owners_margin_pct']:.1f}%", margins["title"])
        cash = next(ex for ex in self.exhibits if ex["title"].startswith("经营现金流"))
        self.assertIn(f"经营现金流 {c['operating_cash_flow_krw_tn']:.1f} 兆韩元", cash["title"])
        net_cash = next(ex for ex in self.exhibits if ex["title"].startswith("净现金"))
        self.assertIn(f"净现金 {c['net_cash_krw_tn']:.1f} 兆韩元", net_cash["title"])
        rnd = next(ex for ex in self.exhibits if ex["title"].startswith("研发支出"))
        self.assertIn(f"研发支出 {c['rnd_krw_tn']:.1f} 兆韩元", rnd["title"])
        self.assertIn(f"环比 +{c['rnd_qoq_pct']}%", rnd["note"])

    def test_the_won_move_is_the_bank_of_korea_averages(self) -> None:
        """The currency note's rates and depreciation against the Bank of Korea
        averages keyed into `_checks`: depreciation measured on the won's own
        price in dollars, 1 − year-ago ÷ this quarter, printed to one decimal."""
        c = self.checks
        period = c["period"]
        year_ago = samsung.shift_period(period, -4)
        rates = c["krw_per_usd_average"]
        fx = self.staging["quarter_story"]["krw_per_usd_average"]
        self.assertEqual(dict(zip(fx["quarters"], fx["krw_per_usd"])), rates)
        self.assertEqual(round((1 - rates[year_ago] / rates[period]) * 100, 1),
                         c["krw_depreciation_yoy_pct"])
        note = next(n for n in self.payload["notes"] if n.startswith("全页以韩元列示"))
        self.assertIn(f"{rates[year_ago]:,.2f} 韩元/美元", note)
        self.assertIn(f"{rates[period]:,.2f}", note)
        self.assertIn(f"对美元贬值 {c['krw_depreciation_yoy_pct']:.1f}% D", note)
        self.assertIn(fx["source_url"], [link["url"] for link in self.payload["source_links"]])


if __name__ == "__main__":
    unittest.main()
