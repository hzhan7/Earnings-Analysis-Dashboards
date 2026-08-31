"""LVMH page: the reconciliations that license what the page publishes.

Three of these exist because of a disclosure shape no other page in this repo
has to deal with:

- `test_no_profit_series_is_carried_on_the_quarterly_axis` is the load-bearing
  one. LVMH publishes revenue four times a year and profit twice: the first and
  third quarter releases carry divisional euro amounts and organic growth rates
  and not one line of profit. So none of the eight quarters on this page has a
  profit figure of its own, and the single most valuable thing a future edit
  could do to this page is quietly invent one -- by halving a half, by
  interpolating, or by carrying a `half_pro` list onto a quarterly x axis where
  it would line up against the wrong periods without changing its length. The
  test asserts the separation structurally: every profit series is exactly as
  long as `halves`, and the quarterly block contains no profit key at all.
- `test_recomputed_half_margins_match_the_percentages_the_company_printed`
  is a genuine second reading rather than the same input checked twice. The
  euro amounts and the margin percentages are printed in different parts of the
  release -- the amounts in the two summary tables, the percentages in the
  divisional commentary and on the results slides -- so a division misread in
  one place does not move the other. The tolerance is 0.06pp because the
  company's own two figures do not agree to better than that: Perfumes &
  Cosmetics recomputes to 10.65% against a printed 10.6%, which is the company
  rounding a delta onto a rounded base, not an error here.
- `test_the_company_printed_components_are_not_treated_as_a_closing_identity`
  pins a refusal. LVMH's own H1 revenue bridge prints organic +2%, perimeter
  -1% and currency -5% against a reported total of -3%; the three integers sum
  to -4%. Every component is rounded independently, so the bridge does not
  close, and any page that adds them up publishes a number the company does
  not. The page therefore derives its currency leg as a residual and says so;
  this test asserts the arithmetic really does fail to close, so that the note
  explaining it cannot outlive the fact.

The threshold entries use only unit keys `board.UNIT_FORMATS` already carries.
`eur_m` / `eur_bn` / `eur_eps` exist because Ferrari landed them; this page adds
no formatter.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import mc  # noqa: E402
from build.all import ENTRIES  # noqa: E402
from build.board import UNIT_FORMATS, headroom  # noqa: E402


def js_payload(path: Path, marker: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{marker} = ", 1)[1].rstrip().rstrip(";")
    return json.loads(body)


# `charts.js` falls back to NAVY for any colour name it does not know, so a
# name outside this set draws two series in the same colour under a legend that
# still lists two. The site currently ships 23 such declarations across other
# pages (ORANGE, GREY, TEAL); this page ships none.
VALID_COLORS = {"NAVY", "BLUE", "MBLUE", "GRAY", "GREEN", "RED", "GOLD"}

# Formatter keys `charts.js` actually implements. `fmtOf` falls back to `f1` in
# silence, which would print a 19,524 euro-million bar as "19524.0".
VALID_FORMATS = {"f1", "f0", "f0c", "int", "pct0", "pct1", "pct0z", "pp0", "pp1",
                 "x0", "usd0", "usd1", "usd2", "f2", "f3", "pct2", "usd3", "usd4"}

# Slots `assets/page.js` writes with textContent or esc(): markup placed in any
# of them reaches the reader as literal angle brackets.
LITERAL_SLOTS = ("headline", "title", "subtitle", "tracker")

DIVS = ["wines_spirits", "fashion_leather", "perfumes_cosmetics",
        "watches_jewelry", "selective_retailing"]


class McDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(mc.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = mc.build_payload(cls.staging)
        cls.der = mc.derived(cls.staging)
        cls.exhibits = [ex for section in cls.payload["sections"]
                        for ex in section["exhibits"]]

    # ── the disclosure shape this page exists to respect ─────────────────────
    def test_no_profit_series_is_carried_on_the_quarterly_axis(self) -> None:
        quarterly = {key for key in self.staging if key.startswith("quarterly_")}
        self.assertTrue(quarterly, "the quarterly block moved or was renamed")
        for key in quarterly:
            self.assertNotIn("pro", key.split("_"),
                             f"{key} puts a profit series on the quarterly axis")
            self.assertNotIn("margin", key, f"{key} puts a margin on the quarterly axis")
        halves = len(self.staging["halves"])
        for name, block in self.staging["half_pro_eur_m"].items():
            self.assertEqual(len(block), halves,
                             f"half_pro_eur_m.{name} is not on the half-year axis")

    def test_every_half_year_chart_says_so_on_its_own_axis(self) -> None:
        """A half read as a quarter halves every denominator on the page."""
        half_labels = set(self.staging["halves"]) | set(self.staging["cash_halves"])
        for exhibit in self.exhibits:
            if not set(exhibit.get("xlabels") or []) & half_labels:
                continue
            axis = (exhibit.get("ylab") or "") + (exhibit.get("ylab2") or "")
            self.assertIn("半年", axis,
                          f"Ex{exhibit['n']} plots half-years without saying so on its axis")

    def test_the_quarterly_axis_carries_no_half_year_label(self) -> None:
        quarters = {mc.compact_quarter(q) for q in self.staging["long_quarters"]}
        for exhibit in self.exhibits:
            labels = exhibit.get("xlabels") or []
            if not set(labels) & quarters:
                continue
            self.assertFalse([lab for lab in labels if lab.startswith(("H1", "H2"))],
                             f"Ex{exhibit['n']} mixes quarters and halves on one axis")

    # ── the staged series against the company's own control totals ───────────
    def test_divisions_and_the_residual_reach_the_published_group_total(self) -> None:
        rev = self.staging["quarterly_revenue_eur_m"]
        for i, quarter in enumerate(self.staging["long_quarters"]):
            with self.subTest(quarter=quarter):
                self.assertEqual(
                    sum(rev[d][i] for d in DIVS) + self.der["other"][i],
                    rev["total"][i])

    def test_the_derived_residual_matches_the_line_the_company_prints(self) -> None:
        """Two roads to the same line: the company prints "other activities and
        eliminations" directly, and it is also the group total minus the five
        divisions. They differ where the company's own rounding differs, which
        is at most one euro million and is carried in the audit table."""
        printed = self.staging["quarterly_revenue_other_published_eur_m"]
        gaps = [abs(self.der["other"][i] - printed[i])
                for i in range(len(self.staging["long_quarters"]))]
        self.assertLessEqual(max(gaps), 1, "residual and printed line diverge by more than rounding")
        self.assertGreater(sum(1 for g in gaps if g == 0), 0, "no quarter agrees at all")

    def test_champagne_and_cognac_add_up_to_their_own_division(self) -> None:
        split = self.staging["quarterly_wines_split_eur_m"]
        rev = self.staging["quarterly_revenue_eur_m"]["wines_spirits"]
        checked = 0
        for i in range(len(self.staging["long_quarters"])):
            if split["champagne_wines"][i] is None:
                self.assertIsNone(split["cognac_spirits"][i], "one leg present, the other absent")
                continue
            checked += 1
            self.assertLessEqual(
                abs(split["champagne_wines"][i] + split["cognac_spirits"][i] - rev[i]), 1)
        self.assertGreaterEqual(checked, 10, "the sub-split stopped being read")

    def test_half_year_divisions_add_up_to_the_half_year_total(self) -> None:
        for block in ("half_revenue_eur_m", "half_pro_eur_m"):
            data = self.staging[block]
            for i, half in enumerate(self.staging["halves"]):
                with self.subTest(block=block, half=half):
                    self.assertLessEqual(
                        abs(sum(data[d][i] for d in DIVS) + data["other"][i] - data["total"][i]), 1)

    def test_the_one_euro_million_gap_the_bridge_carries_is_real(self) -> None:
        """H1 2026's five divisions plus other sum to 8,690 against a printed
        8,691. The page puts that euro in the bridge's last leg rather than into
        a division; if the company ever reprints the table the gap goes away and
        this test should go with it."""
        halves = self.staging["halves"]
        i = halves.index("H1 2026")
        pro = self.staging["half_pro_eur_m"]
        self.assertEqual(sum(pro[d][i] for d in DIVS) + pro["other"][i], 8690)
        self.assertEqual(self.staging["half_pro_published_total_eur_m"]["H1 2026"], 8691)

    def test_recomputed_half_margins_match_the_percentages_the_company_printed(self) -> None:
        printed = self.staging["half_margin_company_printed_pct"]
        checked = 0
        for half, values in printed.items():
            i = self.staging["halves"].index(half)
            for key, stated in values.items():
                got = (self.der["half_margin"][i] if key == "total"
                       else self.der["div_half_margin"][key][i])
                with self.subTest(half=half, division=key):
                    self.assertLessEqual(abs(got - stated), 0.06,
                                         f"recomputed {got:.2f} vs printed {stated}")
                checked += 1
        self.assertGreaterEqual(checked, 9, "the printed-margin control stopped being read")

    def test_operating_free_cash_flow_is_the_company_definition(self) -> None:
        cash = self.staging["half_cash_eur_m"]
        for i, half in enumerate(self.staging["cash_halves"]):
            with self.subTest(half=half):
                self.assertEqual(cash["ocf"][i] - cash["capex"][i] - cash["lease_repaid"][i],
                                 cash["ofcf"][i])

    def test_store_regions_add_up_to_the_published_total(self) -> None:
        stores = self.staging["stores"]
        regions = [k for k in stores if k != "total"]
        for i, date in enumerate(self.staging["store_dates"]):
            with self.subTest(date=date):
                self.assertEqual(sum(stores[k][i] for k in regions), stores["total"][i])

    def test_reported_growth_has_a_full_year_of_history_behind_it(self) -> None:
        """A year-on-year rate computed off a window that starts at the window's
        own first quarter is not a year-on-year rate."""
        long_q = self.staging["long_quarters"]
        start = long_q.index(self.staging["quarters"][0])
        self.assertGreaterEqual(start, 4, "no prior-year quarters staged")
        self.assertEqual(len(self.der["reported_yoy"]), len(self.staging["quarters"]))

    # ── the findings the page states in its own titles ───────────────────────
    def test_the_division_told_not_to_repeat_repeated_exactly(self) -> None:
        organic = self.der["organic"]["wines_spirits"]
        self.assertEqual(organic[-1], organic[-2],
                         "the page's lead finding no longer holds")
        record = {item["key"]: item for item in self.staging["call_record"]["items"]}
        self.assertEqual(record["wines_spirits_q2"]["verdict"], "missed")
        self.assertEqual(record["wines_spirits_q2"]["outcome_value"], organic[-1])

    def test_most_of_the_reported_improvement_is_not_demand(self) -> None:
        step = self.der["reported_yoy"][-1] - self.der["reported_yoy"][-2]
        gap_step = self.der["gap"][-2] - self.der["gap"][-1]
        organic_step = self.der["organic"]["total"][-1] - self.der["organic"]["total"][-2]
        self.assertAlmostEqual(step, gap_step + organic_step, places=6,
                               msg="the decomposition does not close")
        self.assertGreater(gap_step / step, 0.5,
                           "the page claims most of the improvement came from the gap")

    def test_every_complete_year_has_a_bigger_and_thinner_second_half(self) -> None:
        pairs = self.der["half_pairs"]
        self.assertGreaterEqual(len(pairs), 3, "fewer complete years than the page claims")
        self.assertEqual(self.der["h2_bigger"], len(pairs))
        self.assertEqual(self.der["h2_thinner"], len(pairs))

    def test_fashion_and_leather_turned_positive_after_a_run_of_negatives(self) -> None:
        organic = self.der["organic"]["fashion_leather"]
        self.assertGreater(organic[-1], 0)
        self.assertTrue(all(v <= 0 for v in organic[:-1]),
                        "the page calls this the first positive quarter in the window")

    def test_the_company_printed_components_are_not_treated_as_a_closing_identity(self) -> None:
        """LVMH prints +2 / -1 / -5 against a reported -3. The page must never
        add those three up; this asserts they really do not sum, so the note
        that explains the refusal cannot outlive the fact."""
        halves = self.staging["halves"]
        i_now, i_prior = halves.index("H1 2026"), halves.index("H1 2025")
        revenue = self.staging["half_revenue_eur_m"]["total"]
        reported = mc.pct_change(revenue[i_now], revenue[i_prior])
        self.assertNotAlmostEqual(2 - 1 - 5, reported, places=0)
        self.assertAlmostEqual(reported, -3, places=0)

    def test_the_store_chart_measures_the_span_its_sentence_claims(self) -> None:
        """The store series is semi-annual, so twelve months ago is index -3.
        The first draft of this chart read index 0 -- eighteen months -- printed
        "one year" in the title, and then divided that eighteen-month drop by
        the twelve-month-ago base to print a percentage neither number
        supports. Every figure in the title and the note is recomputed here."""
        stores = self.staging["stores"]
        exhibit = next(ex for ex in self.exhibits if ex.get("ref") == "EX_STORES")
        asia = stores["asia_ex_japan"][-3] - stores["asia_ex_japan"][-1]
        total = stores["total"][-3] - stores["total"][-1]
        self.assertIn(f"少了 {asia} 家", exhibit["title"])
        self.assertIn(f"只少了 {total} 家", exhibit["title"])
        self.assertIn(f"{-asia / stores['asia_ex_japan'][-3] * 100:.1f}%", exhibit["note"])
        for key in ("asia_ex_japan", "united_states", "other_markets"):
            self.assertIn(f"{stores[key][-3]:,}", exhibit["note"], key)
            self.assertIn(f"{stores[key][-1]:,}", exhibit["note"], key)

    def test_the_division_margin_tally_is_counted_rather_than_typed(self) -> None:
        margins = self.der["div_half_margin"]
        improved = sum(1 for d in DIVS if margins[d][-1] > margins[d][-3])
        exhibit = next(ex for ex in self.exhibits if ex.get("ref") == "EX_DIVMARGIN")
        self.assertIn(f"{improved} 个同比走高", exhibit["title"])
        self.assertIn(f"{len(DIVS) - improved} 个走低", exhibit["title"])

    # ── exhibit structure ────────────────────────────────────────────────────
    def test_exhibits_are_numbered_in_render_order_from_two(self) -> None:
        self.assertEqual([ex["n"] for ex in self.exhibits],
                         list(range(2, len(self.exhibits) + 2)))

    def test_every_exhibit_plots_one_point_per_x_label(self) -> None:
        for exhibit in self.exhibits:
            width = len(exhibit.get("xlabels") or [])
            self.assertGreater(width, 0, f"Ex{exhibit['n']} has no xlabels")
            named = [("values", exhibit.get("values"))]
            for key in ("yoy", "line", "net"):
                block = exhibit.get(key)
                if isinstance(block, dict):
                    named.append((key, block.get("values")))
            if isinstance(exhibit.get("bar"), dict):
                named.append(("bar", exhibit["bar"].get("values")))
            for key in ("groups", "series", "stacks"):
                for block in exhibit.get(key) or []:
                    named.append((f"{key}:{block.get('name')}", block.get("values")))
            for name, values in named:
                if values is None:
                    continue
                self.assertEqual(len(values), width,
                                 f"Ex{exhibit['n']} {name}: {len(values)} for {width} labels")

    def test_every_column_of_every_bar_chart_has_something_to_draw(self) -> None:
        """A column whose every series is zero or null draws a label over empty
        canvas. A single zero inside a column that has other bars is fine and is
        deliberate here -- "flattish" is zero, and its label prints at the axis."""
        for exhibit in self.exhibits:
            blocks = (exhibit.get("groups") or []) + (exhibit.get("stacks") or [])
            if not blocks:
                continue
            net = exhibit.get("net") or {}
            netvals = net.get("values") if isinstance(net, dict) else []
            for i, label in enumerate(exhibit["xlabels"]):
                drawn = [b["values"][i] for b in blocks
                         if isinstance(b["values"][i], (int, float)) and b["values"][i] != 0]
                netv = netvals[i] if isinstance(netvals, list) and i < len(netvals) else None
                self.assertTrue(drawn or isinstance(netv, (int, float)),
                                f"Ex{exhibit['n']} column {i} ({label!r}) draws nothing")

    def test_the_bridges_hand_the_renderer_the_shape_it_reads(self) -> None:
        bridges = [ex for ex in self.exhibits if ex["kind"] == "bridge_bar"]
        self.assertEqual(len(bridges), 2)
        for exhibit in bridges:
            net = exhibit["net"]
            self.assertIsInstance(net, dict, "charts.js starts at ex.net.values")
            self.assertIsInstance(net["values"], list)
            self.assertTrue(net.get("name"), "the legend reads ex.net.name")
            self.assertEqual(sum(1 for v in net["values"] if isinstance(v, (int, float))), 1)

    def test_the_profit_bridge_closes_on_the_published_total(self) -> None:
        exhibit = next(ex for ex in self.exhibits if ex.get("ref") == "EX_BRIDGE_PRO")
        legs = [v for v in exhibit["stacks"][0]["values"] if v is not None]
        closing = next(v for v in exhibit["net"]["values"] if v is not None)
        self.assertAlmostEqual(sum(legs), closing, places=6)
        self.assertEqual(closing, self.staging["half_pro_eur_m"]["total"][-1])

    def test_the_revenue_bridge_closes_on_the_reported_rate(self) -> None:
        exhibit = next(ex for ex in self.exhibits if ex.get("ref") == "EX_BRIDGE_REV")
        legs = [v for v in exhibit["stacks"][0]["values"] if v is not None]
        closing = next(v for v in exhibit["net"]["values"] if v is not None)
        self.assertAlmostEqual(sum(legs), closing, places=6)
        self.assertAlmostEqual(closing, self.der["reported_yoy"][-1], places=6)

    def test_the_single_gs_bar_carries_a_yoy_line(self) -> None:
        """`test_chart_contract.py` asserts `avgo Ex16` is the only gs_bar with
        neither `yoy` nor `avg12`, and that assertion is the evidence that the
        `avg12` branch has never been exercised -- the branch that shipped
        `<line y1="NaN">`. A gs_bar added here without `yoy` would take that
        evidence away."""
        bars = [ex for ex in self.exhibits if ex["kind"] == "gs_bar"]
        # Two now: the eight-quarter current view and the 42-quarter long record
        # added when the series reached 2016Q1. Both carry `yoy`; neither may
        # ever carry `avg12`.
        self.assertEqual(len(bars), 2)
        for bar in bars:
            self.assertTrue(bar["yoy"]["values"])
            self.assertNotIn("avg12", bar)

    def test_the_stacked_dual_declares_a_right_axis_ceiling_for_its_share_line(self) -> None:
        """`charts.js:914` reads `rc.ymax || 60` for this kind and never looks at
        the data, so a percentage line without an explicit ceiling is drawn off
        the canvas the moment it passes 60 -- finite coordinates, no NaN, and
        the legend still names the series."""
        for exhibit in self.exhibits:
            if exhibit["kind"] != "stacked_dual":
                continue
            line = exhibit["line"]
            self.assertEqual(line["ymax"], 100)
            self.assertLessEqual(max(line["values"]), line["ymax"])

    def test_every_colour_name_is_one_the_renderer_knows(self) -> None:
        def walk(node):
            if isinstance(node, dict):
                if isinstance(node.get("color"), str):
                    self.assertIn(node["color"], VALID_COLORS)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)
        walk(self.payload)

    def test_every_formatter_name_is_one_the_renderer_implements(self) -> None:
        for exhibit in self.exhibits:
            for key in ("fmt", "yfmt", "label_fmt"):
                if exhibit.get(key):
                    self.assertIn(exhibit[key], VALID_FORMATS, f"Ex{exhibit['n']}.{key}")
            for block in (exhibit.get("line"), exhibit.get("yoy")):
                if isinstance(block, dict) and block.get("yfmt"):
                    self.assertIn(block["yfmt"], VALID_FORMATS)

    def test_no_exhibit_carries_an_unresolved_reference_placeholder(self) -> None:
        for exhibit in self.exhibits:
            for key in ("title", "note", "src_extra"):
                self.assertNotRegex(exhibit.get(key) or "", r"\{[A-Z_]+\}",
                                    f"Ex{exhibit['n']}.{key}")
        for table in self.payload["tables"]:
            self.assertNotRegex(table["title"], r"\{[A-Z_]+\}")

    def test_literal_slots_and_page_notes_carry_no_markup(self) -> None:
        for slot in LITERAL_SLOTS:
            self.assertNotRegex(self.payload[slot], r"</?[a-z][a-z0-9]*>", slot)
        for note in self.payload["notes"]:
            self.assertNotRegex(note, r"</?[a-z][a-z0-9]*>")
        for section in self.payload["sections"]:
            for key in ("title", "description"):
                self.assertNotRegex(section[key], r"</?[a-z][a-z0-9]*>")

    # ── sourcing ─────────────────────────────────────────────────────────────
    def test_no_link_on_this_page_points_at_edgar(self) -> None:
        """LVMH stopped filing in 2004 and deregistered in 2009; the two 20-Fs
        under its CIK cover FY2001 and FY2002. An EDGAR link here would point at
        a document about a company two decades removed from this page.

        Asserted on URLs, not on prose. The first spelling of this test scanned
        the whole payload for the string "EDGAR" and went red on the page note
        that exists to say there is no EDGAR source -- a gate that fires on its
        own subject matter is a gate someone routes around."""
        urls = re.findall(r'href="([^"]+)"', json.dumps(self.payload, ensure_ascii=False))
        urls += [source["url"] for source in self.payload["source_links"]]
        urls.append(self.payload["source_url"])
        self.assertGreaterEqual(len(urls), 7, "no links found; the scan missed them")
        for url in urls:
            self.assertNotIn("sec.gov", url, "an SEC link on a page with no SEC filings")

    def test_sources_are_official_https_links(self) -> None:
        for source in self.payload["source_links"]:
            self.assertTrue(source["url"].startswith("https://www.lvmh.com/"), source["url"])
            self.assertTrue(source["label"])
        self.assertGreaterEqual(len(self.payload["source_links"]), 6)

    def test_the_only_dollars_on_the_page_are_the_shared_cross_page_table(self) -> None:
        """LVMH publishes no dollar financials, so a dollar figure produced here
        would be a conversion the page invented. The one dollar-denominated
        object is the shared AI capex table, asserted to still contain dollars
        rather than excluded silently."""
        shared = next(t for t in self.payload["tables"] if "跨页对照" in t["title"])
        self.assertRegex(json.dumps(shared, ensure_ascii=False), r"US\$|\$\d")
        rest = {k: v for k, v in self.payload.items() if k != "tables"}
        rest["tables"] = [t for t in self.payload["tables"] if t is not shared]
        self.assertNotRegex(json.dumps(rest, ensure_ascii=False), r"US\$|\$\d")

    def test_the_guidance_slot_is_empty_because_the_company_issues_none(self) -> None:
        self.assertIsNone(self.payload["guidance"])
        self.assertEqual(self.staging["disclosure_cadence"]["never_quantified"],
                         ["下一季或全年的收入、利润或利润率的数字指引"])

    # ── the call record ──────────────────────────────────────────────────────
    def test_every_recorded_statement_carries_a_verdict_and_a_verbatim_quote(self) -> None:
        allowed = {"met", "beat", "missed", "caveat_held", "unverifiable"}
        items = self.staging["call_record"]["items"]
        self.assertEqual(len(items), 6)
        for item in items:
            with self.subTest(topic=item["topic"]):
                self.assertIn(item["verdict"], allowed)
                self.assertTrue(item["said"].strip())
                self.assertRegex(item["said"], r"[a-z]", "the quote should be the English original")
                self.assertTrue(item["outcome_zh"].strip())

    def test_the_unverifiable_statement_carries_no_outcome_value(self) -> None:
        """A verdict of "cannot be checked in the terms it was said" has to be
        backed by an absent number, or it is a checked statement wearing a
        hedge."""
        for item in self.staging["call_record"]["items"]:
            if item["verdict"] == "unverifiable":
                self.assertIsNone(item["outcome_value"])
            else:
                self.assertIsNotNone(item["outcome_value"])

    def test_the_score_chart_plots_only_statements_that_were_quantified(self) -> None:
        exhibit = next(ex for ex in self.exhibits if ex.get("ref") == "EX_SCORE")
        said = exhibit["groups"][0]["values"]
        actual = exhibit["groups"][1]["values"]
        self.assertEqual(len(said), len(actual))
        self.assertEqual(len(said), 4)
        # Membership rule, tied to the record rather than to the count: a
        # statement is plotted when it was given a number AND that number can
        # be checked in the terms it was said. The DFS perimeter statement was
        # quantified (-2 points on Selective Retailing in Q2) but the company
        # publishes no quarterly divisional perimeter, so it is recorded and
        # tabulated, not charted.
        plotted = [item for item in self.staging["call_record"]["items"]
                   if item.get("quantified") is not None
                   and item["verdict"] != "unverifiable"]
        self.assertEqual(len(plotted), len(said))
        self.assertEqual(
            [item for item in self.staging["call_record"]["items"]
             if item.get("quantified") is not None and item["verdict"] == "unverifiable"],
            [item for item in self.staging["call_record"]["items"]
             if item["key"] == "dfs_perimeter"])

    def test_the_forward_statements_are_the_ones_next_quarter_will_settle(self) -> None:
        forward = self.staging["forward_statements"]
        self.assertEqual(forward["made_on"], self.payload["latest"]["release_date"])
        self.assertGreaterEqual(len(forward["items"]), 8)
        for item in forward["items"]:
            self.assertTrue(item["said"].strip() and item["quantified"].strip())

    # ── thresholds ───────────────────────────────────────────────────────────
    def test_thresholds_use_only_units_the_shared_formatter_carries(self) -> None:
        for entry in self.staging["next_kpi"]["entries"]:
            self.assertIn(entry["unit"], UNIT_FORMATS, entry["metric"])
            self.assertIn(entry["direction"], ("up", "down"))
            self.assertTrue(entry["why"].strip())

    def test_threshold_current_values_match_the_series_they_are_read_from(self) -> None:
        current = {e["metric"]: e["current"] for e in self.staging["next_kpi"]["entries"]}
        organic = self.der["organic"]
        self.assertEqual(current["时装与皮具季度有机增速"], organic["fashion_leather"][-1])
        self.assertEqual(current["集团季度有机增速"], organic["total"][-1])
        self.assertEqual(current["手表与珠宝季度有机增速"], organic["watches_jewelry"][-1])
        self.assertAlmostEqual(current["半年集团经营利润率"], self.der["half_margin"][-1], places=2)
        self.assertAlmostEqual(current["半年时装与皮具经营利润率"],
                               self.der["div_half_margin"]["fashion_leather"][-1], places=2)
        self.assertAlmostEqual(current["季度报告增速与有机增速之差"], self.der["gap"][-1], places=2)
        self.assertEqual(current["亚洲（除日本）门店数"], self.staging["stores"]["asia_ex_japan"][-1])

    def test_the_headroom_chart_agrees_with_the_audit_table(self) -> None:
        exhibit = next(ex for ex in self.exhibits if ex["kind"] == "diverging_bars")
        entries = self.staging["next_kpi"]["entries"]
        self.assertEqual(exhibit["xlabels"], [e["metric"] for e in entries])
        self.assertEqual(
            exhibit["values"],
            [round(headroom(e["direction"], e["threshold"], e["current"]), 1) for e in entries])

    def test_exactly_one_threshold_is_breached_this_quarter(self) -> None:
        exhibit = next(ex for ex in self.exhibits if ex["kind"] == "diverging_bars")
        breached = [label for label, value in zip(exhibit["xlabels"], exhibit["values"])
                    if value < 0]
        self.assertEqual(breached, ["时装与皮具季度有机增速"])

    # ── tables, payload, registry ────────────────────────────────────────────
    def test_tables_are_numbered_from_one_and_carry_the_shared_capex_table(self) -> None:
        tables = self.payload["tables"]
        self.assertEqual([t["n"] for t in tables], list(range(1, len(tables) + 1)))
        shared = [t for t in tables if "跨页对照" in t["title"]]
        self.assertEqual(len(shared), 1, "the cross-page table must be published here too")

    def test_the_period_tables_have_one_row_per_period(self) -> None:
        by_n = {t["n"]: t for t in self.payload["tables"]}
        self.assertEqual(len(by_n[1]["rows"]), len(self.staging["quarters"]))
        self.assertEqual(len(by_n[2]["rows"]), len(self.staging["quarters"]))
        self.assertEqual(len(by_n[3]["rows"]), len(self.staging["halves"]))
        self.assertEqual(len(by_n[4]["rows"]), len(self.staging["halves"]))
        self.assertEqual(len(by_n[5]["rows"]), len(self.staging["cash_halves"]))
        self.assertEqual(len(by_n[6]["rows"]), len(self.staging["store_dates"]))
        self.assertEqual(len(by_n[7]["rows"]), len(self.staging["call_record"]["items"]))
        for table in self.payload["tables"]:
            for row in table["rows"]:
                self.assertEqual(len(row), len(table["headers"]), table["title"])

    def test_the_quarter_the_page_reports_is_the_last_one_in_the_series(self) -> None:
        self.assertEqual(self.staging["quarters"][-1], "2026Q2")
        self.assertEqual(self.payload["latest"]["disclosed_period_label"], "Q2 2026")
        self.assertEqual(self.payload["latest"]["full_financial_period_label"], "H1 2026")
        self.assertEqual(self.staging["halves"][-1], "H1 2026")

    def test_published_payload_and_shell(self) -> None:
        self.assertEqual(js_payload(ROOT / "data" / "mc.js", "window.DASH"), self.payload)
        shell = (ROOT / "mc" / "index.html").read_text(encoding="utf-8")
        self.assertIn("../data/mc.js", shell)
        self.assertNotIn("../data/mco.js", shell)
        self.assertIn("MC.PA", shell)

    def test_the_roster_entry_matches_the_payload(self) -> None:
        entry = next(e for e in ENTRIES if e["slug"] == "mc")
        self.assertEqual(entry["ticker"], self.payload["company"]["ticker"])
        self.assertEqual(entry["group"], self.payload["company"]["group"])
        self.assertIn("LVMH", entry["name"])
        # The site-wide README gate keys on this exact phrase in cadence_label
        # and would then require the README to name this page among the
        # off-calendar filers. LVMH reports on calendar quarters.
        self.assertNotIn("本站按自然年季度标注", entry["cadence_label"])
        self.assertIn("半年", entry["cadence_label"])

    def test_the_home_page_card_matches_the_payload(self) -> None:
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="mc/"', home)
        card = home.split('href="mc/"', 1)[1].split("</a>", 1)[0]
        self.assertIn(self.payload["latest"]["release_date"], card)
        self.assertIn("MC.PA", card)


if __name__ == "__main__":
    unittest.main()
