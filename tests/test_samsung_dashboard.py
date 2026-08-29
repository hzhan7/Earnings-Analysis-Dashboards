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

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import samsung  # noqa: E402
from build.board import UNIT_FORMATS, headroom  # noqa: E402


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
        n = len(self.staging["periods"])
        self.assertEqual(n, 8)
        for block in ("financials_krw_bn", "segment_revenue_krw_tn",
                      "segment_operating_profit_krw_tn", "cash_flow_krw_tn",
                      "balance_sheet_krw_bn"):
            for name, values in self.staging[block].items():
                self.assertEqual(len(values), n, f"{block}.{name}")
        self.assertEqual(len(self.staging["net_cash_krw_tn"]), n)
        self.assertEqual(len(self.staging["final_release_dates"]), n)

    def test_income_statement_identities_close_every_quarter(self) -> None:
        """Revenue − COGS = gross, gross − SG&A = operating, PBT − tax = net."""
        fin = self.fin
        for i, period in enumerate(self.staging["periods"]):
            with self.subTest(period=period):
                self.assertAlmostEqual(
                    fin["revenue"][i] - fin["cost_of_sales"][i],
                    fin["gross_profit"][i], places=2)
                self.assertAlmostEqual(
                    fin["gross_profit"][i] - fin["sga_expenses"][i],
                    fin["operating_profit"][i], places=2)
                self.assertAlmostEqual(
                    fin["profit_before_tax"][i] - fin["income_tax"][i],
                    fin["net_profit"][i], places=2)
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
                # Eight quarters of it sit in a narrow band; a reading error
                # would put one outside.
                self.assertTrue(8.0 <= der["elimination_share"][i] <= 10.0,
                                der["elimination_share"][i])

    def test_segment_operating_profit_adds_up_to_consolidated(self) -> None:
        """The other side of the same footnote: operating profit has no elimination."""
        for i, period in enumerate(self.staging["periods"]):
            with self.subTest(period=period):
                total = sum(self.seg_op[key][i]
                            for key in ("dx", "ds", "sdc", "harman"))
                self.assertAlmostEqual(
                    total, self.fin["operating_profit"][i] / 1000, delta=0.11)

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
        allowed = {"www.samsung.com", "images.samsung.com", "dart.fss.or.kr"}
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
        must not manufacture one out of the qualitative bit-shipment phrase."""
        self.assertIsNone(self.payload["guidance"])
        wordings = " ".join(item["wording"] for item in self.staging["guidance"]["items"])
        self.assertIn("公司对 3Q ASP 不给任何指引", wordings)

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

    def test_the_dx_division_is_the_breached_line_this_quarter(self) -> None:
        """The quarter's whole point: the group is on both sides of the price
        move, and the handset side is the one that broke."""
        der = samsung.derived(self.staging)
        self.assertLess(der["dx_margin"][-1], 0)
        self.assertEqual(sum(1 for v in der["dx_margin"] if v < 0), 1)
        self.assertGreater(der["ds_margin"][-1], 60)

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

    def test_price_beat_volume_in_every_quarter_on_record(self) -> None:
        """The claim the first section is built on, asserted rather than argued:
        the variable the company guides moved single digits while the variable
        it never guides moved tens of per cent."""
        bits = self.staging["memory_bit_and_price"]
        for i, quarter in enumerate(bits["quarters"]):
            with self.subTest(quarter=quarter):
                self.assertGreater(bits["dram_asp_qoq_pct"][i], 20)
                self.assertGreater(bits["nand_asp_qoq_pct"][i], 20)
                if bits["dram_bit_actual"][i] is not None:
                    self.assertLess(bits["dram_bit_actual"][i], 20)

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

    def test_the_eight_quarter_tables_have_eight_rows(self) -> None:
        for table in self.payload["tables"]:
            if table["title"].startswith("八季"):
                self.assertEqual(len(table["rows"]), 8, table["title"])

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


if __name__ == "__main__":
    unittest.main()
