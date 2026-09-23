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

The threshold entries use the unit keys `board.UNIT_FORMATS` carries, plus one
page-local unit, `stores`: a store count formatted through the shared `million`
key printed 1,832 stores as `1832M`. `eur_m` / `eur_bn` / `eur_eps` exist
because Ferrari landed them.

**A roll edits `series/mc.json` and nothing else** (CLAUDE.md §9). So nothing
here asserts a quarter's figure as a literal: the quarter's own numbers are
checked against `_checks` (typed from the release, never read by the builder),
and every finding a chart states -- 「第一次不再下滑」「每一次都」「连续下降」 --
is recomputed, and made false on a copy of the series to prove the sentence
goes away with it.
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

    def test_the_rounding_gap_the_bridge_carries_is_real(self) -> None:
        """H1 2026's five divisions plus other sum to 8,690 against a printed
        8,691. The page puts that euro in the bridge's last leg rather than into
        a division, and says so only while the two really differ."""
        halves = self.staging["halves"]
        pro = self.staging["half_pro_eur_m"]
        bridge = next(ex for ex in self.exhibits if ex.get("ref") == "EX_BRIDGE_PRO")
        for half, printed in self.staging["half_pro_published_total_eur_m"].items():
            i = halves.index(half)
            parts = sum(pro[d][i] for d in DIVS) + pro["other"][i]
            with self.subTest(half=half):
                self.assertLessEqual(abs(printed - parts), 1)
                if half == halves[-1]:
                    self.assertEqual(printed != parts, "取整差" in bridge["note"])
                    self.assertEqual(printed != parts,
                                     any(f"公司印的集团合计是 {printed:,}" in n for n in self.payload["notes"]))

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
    def test_the_lead_finding_says_what_the_series_says(self) -> None:
        """The lead sentence is the quarter's story, written into `call_record`;
        where it says the division repeated exactly, the series must agree."""
        call = self.staging.get("call_record")
        if call is None:
            self.skipTest("no call record this quarter")
        lead = call["lead"]
        organic = self.der["organic"][lead["division"]]
        record = {item["key"]: item for item in call["items"]}
        text = lead["title"] + lead["note"]
        if "一模一样" in text or "完全相同" in text:
            self.assertEqual(organic[-1], organic[-2], "the lead finding no longer holds")
        self.assertIn(record[lead["item"]]["verdict"], ("missed", "caveat_held", "met", "beat"))
        if record[lead["item"]]["outcome_value"] is not None:
            self.assertEqual(record[lead["item"]]["outcome_value"], organic[-1])

    def test_most_of_the_reported_improvement_is_not_demand(self) -> None:
        step = self.der["reported_yoy"][-1] - self.der["reported_yoy"][-2]
        gap_step = self.der["gap"][-2] - self.der["gap"][-1]
        organic_step = self.der["organic"]["total"][-1] - self.der["organic"]["total"][-2]
        self.assertAlmostEqual(step, gap_step + organic_step, places=6,
                               msg="the decomposition does not close")
        claimed = "来自汇率与并表而不是需求" in self.payload["headline"]
        self.assertEqual(claimed, step > 0 and 0 < gap_step / step < 1,
                         "the headline's share sentence must follow the arithmetic")

    def test_the_seasonal_title_claims_every_year_only_when_every_year_does(self) -> None:
        pairs = self.der["half_pairs"]
        self.assertGreaterEqual(len(pairs), 1)
        season = next(ex for ex in self.exhibits if ex.get("ref") == "EX_SEASON")
        every = self.der["h2_bigger"] == len(pairs) == self.der["h2_thinner"]
        # 「每一次都」 alone is no longer the key: the title says it of revenue
        # (10/10) while denying it of margin (5/10), so the claim being guarded
        # here is the whole conjunction, not the adverb.
        self.assertEqual(every, "每一次都是收入更高、利润率更低" in season["title"])
        self.assertIn(f"{self.der['h2_bigger']}", season["title"])

    def test_a_division_called_first_positive_really_is(self) -> None:
        """「是 2024Q3 以来七个非正季度之后的第一个正数」 is recounted on the long series."""
        exhibit = next(ex for ex in self.exhibits if ex.get("ref") == "EX_DIVORG")
        match = re.search(r"<b>(\S+?)本季 [+-]\d+%，是 (\d{4}Q[1-4]) 以来(\S+?)个非正季度之后", exhibit["note"])
        self.assertEqual(match is not None, "个非正季度之后" in exhibit["note"], "the pattern stopped matching")
        if not match:
            return
        name, began, count = match.groups()
        key = next(k for k, v in mc.DIV_NAMES.items() if v == name)
        long_org = self.staging["organic_growth_pct"][key]
        start = self.staging["organic_quarters"].index(began)
        run = long_org[start:-1]
        self.assertGreater(long_org[-1], 0)
        self.assertTrue(all(v <= 0 for v in run))
        self.assertGreater(long_org[start - 1], 0, "the run started earlier than the sentence says")
        self.assertEqual(count, mc.cn_count(len(run)))

    def test_the_company_printed_components_are_not_treated_as_a_closing_identity(self) -> None:
        """LVMH prints +2 / -1 / -5 against a reported -3. The page must never
        add those three up; this asserts they really do not sum, so the note
        that explains the refusal cannot outlive the fact."""
        halves = self.staging["halves"]
        parts = self.staging["half_growth_components_pct"].get(halves[-1])
        if parts is None:
            self.skipTest("the company printed no split for this half")
        i_now = len(halves) - 1
        i_prior = halves.index(f"{halves[-1].split()[0]} {int(halves[-1].split()[1]) - 1}")
        revenue = self.staging["half_revenue_eur_m"]["total"]
        reported = mc.pct_change(revenue[i_now], revenue[i_prior])
        self.assertEqual(round(reported), parts["reported"])
        legs = parts["organic"] + parts["perimeter"] + parts["currency"]
        bridge = next(ex for ex in self.exhibits if ex.get("ref") == "EX_BRIDGE_REV")
        self.assertEqual(legs != parts["reported"], "能闭合的等式来用" in bridge["note"])

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
        self.assertGreaterEqual(len(items), 1)
        table = next(t for t in self.payload["tables"] if t["title"].startswith("上季电话会的"))
        self.assertIn(f"的{mc.cn_count(len(items))}条前瞻陈述", table["title"])
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
        # Membership rule, tied to the record rather than to the count: a
        # statement is plotted when it was given a number AND that number can
        # be checked in the terms it was said. The DFS perimeter statement was
        # quantified (-2 points on Selective Retailing in Q2) but the company
        # publishes no quarterly divisional perimeter, so it is recorded and
        # tabulated, not charted.
        items = self.staging["call_record"]["items"]
        plotted = [item for item in items
                   if item.get("quantified") is not None and item["verdict"] != "unverifiable"]
        self.assertEqual(len(plotted), len(said))
        self.assertEqual(sorted(i["key"] for i in plotted),
                         sorted(self.staging["call_record"]["score_order"]))
        self.assertTrue(exhibit["title"].startswith(f"{mc.cn_count(len(plotted))}条能落到数字上的陈述"))
        for item in items:
            if item.get("quantified") is not None and item["verdict"] == "unverifiable":
                self.assertNotIn(item.get("chart_label", "\0"), exhibit["xlabels"])
                self.assertIn(f"（{item['score_topic']}）", exhibit["note"])

    def test_the_forward_statements_are_the_ones_next_quarter_will_settle(self) -> None:
        forward = self.staging["forward_statements"]
        self.assertEqual(forward["made_on"], self.payload["latest"]["release_date"])
        self.assertGreaterEqual(len(forward["items"]), 1)
        for item in forward["items"]:
            self.assertTrue(item["said"].strip() and item["quantified"].strip())

    # ── thresholds ───────────────────────────────────────────────────────────
    def test_thresholds_use_only_units_the_shared_formatter_carries(self) -> None:
        for entry in self.staging["next_kpi"]["entries"]:
            self.assertIn(entry["unit"], set(UNIT_FORMATS) | {"stores"}, entry["metric"])
            self.assertIn(entry["direction"], ("up", "down"))
            self.assertTrue(entry["why"].strip())
            self.assertNotIn("current", entry, "the current value is read from the series, not typed")
        table = next(t for t in self.payload["tables"] if t["title"].startswith("下季跟踪阈值"))
        for row, entry in zip(table["rows"], self.staging["next_kpi"]["entries"]):
            if entry["unit"] == "stores":
                self.assertTrue(row[2].endswith(" 家") and row[3].endswith(" 家"), row)

    def test_threshold_current_values_match_the_series_they_are_read_from(self) -> None:
        """Each entry names the series value it tracks; the table prints that value."""
        organic, stores = self.der["organic"], self.staging["stores"]
        table = next(t for t in self.payload["tables"] if t["title"].startswith("下季跟踪阈值"))
        for row, entry in zip(table["rows"], mc.kpi_entries(self.staging, self.der,
                                                             self.staging["next_kpi"])):
            kind, _, key = entry["reads"].partition(".")
            expected = {"organic": lambda: organic[key][-1],
                        "half_margin": lambda: (self.der["half_margin"][-1] if key == "total"
                                                else self.der["div_half_margin"][key][-1]),
                        "gap": lambda: self.der["gap"][-1],
                        "stores": lambda: stores[key][-1]}[kind]()
            with self.subTest(metric=entry["metric"]):
                self.assertEqual(entry["current"], expected)
                self.assertEqual(row[3], mc.kpi_unit_text(entry["unit"], expected))

    def test_the_headroom_chart_agrees_with_the_audit_table(self) -> None:
        exhibit = next(ex for ex in self.exhibits if ex.get("ref") == "EX_NEXT_HEADROOM")
        entries = mc.kpi_entries(self.staging, self.der, self.staging["next_kpi"])
        self.assertEqual(exhibit["xlabels"], [e["metric"] for e in entries])
        self.assertEqual(
            exhibit["values"],
            [round(headroom(e["direction"], e["threshold"], e["current"]), 1) for e in entries])

    def test_the_headroom_title_counts_the_safe_lines(self) -> None:
        exhibit = next(ex for ex in self.exhibits if ex.get("ref") == "EX_NEXT_HEADROOM")
        safe = sum(1 for value in exhibit["values"] if value >= 0)
        self.assertEqual(exhibit["title"],
                         f"下季跟踪阈值：{mc.cn_count(len(exhibit['values']))}条线里{mc.cn_count(safe)}条仍在安全侧")

    # ── tables, payload, registry ────────────────────────────────────────────
    def test_tables_are_numbered_from_one_and_carry_the_shared_capex_table(self) -> None:
        tables = self.payload["tables"]
        self.assertEqual([t["n"] for t in tables], list(range(1, len(tables) + 1)))
        shared = [t for t in tables if "跨页对照" in t["title"]]
        self.assertEqual(len(shared), 1, "the cross-page table must be published here too")

    def test_the_period_tables_have_one_row_per_period(self) -> None:
        def table(words: str) -> dict:
            return next(t for t in self.payload["tables"] if words in t["title"])
        self.assertEqual(len(table("季分部收入")["rows"]), len(self.staging["quarters"]))
        self.assertEqual(len(table("季有机增速")["rows"]), len(self.staging["quarters"]))
        self.assertEqual(len(table("分部经营利润（€M）")["rows"]), len(self.staging["halves"]))
        self.assertEqual(len(table("分部经营利润率")["rows"]), len(self.staging["halves"]))
        self.assertEqual(len(table("现金流、资本强度")["rows"]), len(self.staging["cash_halves"]))
        self.assertEqual(len(table("时点的门店数")["rows"]), len(self.staging["store_dates"]))
        self.assertEqual(len(table("前瞻陈述，逐条结算")["rows"]), len(self.staging["call_record"]["items"]))
        for table in self.payload["tables"]:
            for row in table["rows"]:
                self.assertEqual(len(row), len(table["headers"]), table["title"])

    def test_the_quarter_the_page_reports_is_the_last_one_in_the_series(self) -> None:
        checks = self.staging["_checks"]
        self.assertEqual(mc.display_period(self.staging["quarters"][-1]), checks["period"])
        self.assertEqual(self.payload["latest"]["disclosed_period_label"], checks["period"])
        self.assertEqual(self.payload["latest"]["full_financial_period_label"], checks["half"])
        self.assertEqual(self.staging["halves"][-1], checks["half"])

    def test_the_page_has_the_four_sections_of_the_site_format(self) -> None:
        """Every company page runs 上季兑现 → 本季重点 → 下季跟踪 → 长期常规, with
        these ids and these titles verbatim. This page used to carry five: a
        half-year section between the quarter and the long record, and a last
        section that mixed the next thresholds with the routine charts."""
        self.assertEqual(
            [(s["id"], s["title"]) for s in self.payload["sections"]],
            [("settled", "一、上季跟踪指标兑现了吗"), ("quarter_highlights", "二、本季重点"),
             ("next_quarter", "三、下季要跟踪什么"), ("routine", "四、长期常规跟踪")])
        for section in self.payload["sections"]:
            self.assertTrue(section["exhibits"], f"{section['id']} is empty")

    def test_section_one_settles_questions_then_thresholds_then_the_company(self) -> None:
        """(a) last quarter's open questions, (b) its thresholds with one line per
        tracked series, (c) what the company itself said. The page used to open
        on (c) alone, as though the company's sentences were the whole record."""
        refs = [ex["ref"] for ex in self.payload["sections"][0]["exhibits"]]
        self.assertEqual(refs[:2], ["EX_CLOSURE", "EX_PRIOR_HEADROOM"])
        lines = [ref for ref in refs[2:] if ref.startswith("EX_PRIOR_")]
        self.assertTrue(lines, "no prior threshold has its own line")
        self.assertEqual(refs[2:], lines + ["EX_SAID", "EX_SCORE"])

    def test_the_half_year_rates_are_a_second_reading_of_their_quarters(self) -> None:
        """The company prints a half's organic rate in its own column beside the
        two quarters, and the half is a weighted mean of the quarters. Each figure
        is rounded to a whole percent, so the printed half can sit at most one
        point outside the printed quarters -- a column read from the wrong row or
        the wrong year lands further out than that."""
        half = self.staging["halves"][-1]
        number, year = mc.half_parts(half)
        pair = [f"{year}Q{2 * number - 1}", f"{year}Q{2 * number}"]
        checked = 0
        for block, quarters, rates in (
                ("half_organic_growth_pct", self.staging["organic_quarters"], self.staging["organic_growth_pct"]),
                ("region_half_organic_pct", self.staging["region_quarters"], self.staging["region_organic_pct"])):
            for key, value in self.staging[block][half].items():
                both = [rates[key][quarters.index(q)] for q in pair]
                with self.subTest(block=block, key=key):
                    self.assertLessEqual(min(both) - 1, value)
                    self.assertLessEqual(value, max(both) + 1)
                checked += 1
        self.assertGreaterEqual(checked, 10)
        self.assertEqual(self.staging["half_organic_growth_pct"][half]["total"],
                         self.staging["half_growth_components_pct"][half]["organic"])

    def test_sections_are_numbered_in_order_and_the_notes_say_how_many(self) -> None:
        """The long record was inserted as a second 「四、」 and the notes kept
        saying 「四段」; numbering and the count are now read off the sections."""
        sections = self.payload["sections"]
        for index, section in enumerate(sections, start=1):
            self.assertTrue(section["title"].startswith(f"{mc.cn_ordinal(index)}、"), section["title"])
        self.assertIn(f"」{mc.cn_count(len(sections))}段排列", self.payload["notes"][0])
        self.assertIn("「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」", self.payload["notes"][0])
        following = next(i for i, s in enumerate(sections, start=1) if s["id"] == "next_quarter")
        self.assertTrue(any(n.startswith(f"第{mc.cn_ordinal(following)}节的阈值") for n in self.payload["notes"]))

    def test_the_text_quotes_the_margin_the_company_printed(self) -> None:
        """The charts draw recomputed margins; a sentence quoting one uses the
        company's printed figure where the company printed one -- including the
        change on a year ago (Wines & Spirits: printed 20.3% -> 22.4% is +2.1pp;
        the recomputation 20.25% -> 22.40% would print +2.2pp)."""
        printed = self.staging["half_margin_company_printed_pct"]
        halves = self.staging["halves"]
        half = halves[-1]
        prior = halves[mc.year_ago_half(halves, half)]
        exhibit = next(ex for ex in self.exhibits if ex.get("ref") == "EX_DIVMARGIN")
        quoted = 0
        for key, value in printed.get(half, {}).items():
            if key == "total":
                continue
            name = mc.DIV_NAMES[key]
            recomputed = self.der["div_half_margin"][key][-1]
            with self.subTest(division=key):
                if f"{recomputed:.1f}" != f"{value:.1f}":
                    self.assertNotIn(f"{half} 是 {recomputed:.1f}%", exhibit["note"])
                if f"{name} {value:.1f}%（" in exhibit["note"] and key in printed.get(prior, {}):
                    change = value - printed[prior][key]
                    self.assertRegex(exhibit["note"], re.escape(f"{name} {value:.1f}%（") + r"(同比 )?"
                                     + re.escape(f"{change:+.1f}pp）"))
                    quoted += 1
        self.assertGreaterEqual(quoted, 1, "no printed margin is quoted with its change")

    def test_the_mix_title_counts_the_distance_it_names(self) -> None:
        """The first bar of an eight-quarter window is seven quarters back, not eight."""
        exhibit = next(ex for ex in self.exhibits if ex.get("ref") == "EX_MIX")
        n = len(self.staging["quarters"])
        self.assertIn(f"{mc.cn_count(n - 1)}季前是 {self.der['flg_share'][0]:.1f}%", exhibit["title"])

    def test_the_second_half_rhythm_is_claimed_division_by_division(self) -> None:
        """「各分部利润率同时呈现下半年更薄」 was printed while Fashion & Leather
        Goods' 2025 second half (35.2%) was thicker than its first (34.7%).

        Over three complete years the exceptions were named one by one. Over ten
        there are thirty-two of them, so each division carries its own count
        instead: bounded by the number of divisions, and still falsifiable --
        a division whose count is wrong fails here just as a missing exception did.
        """
        exhibit = next(ex for ex in self.exhibits if ex.get("ref") == "EX_DIVMARGIN")
        margins, pairs = self.der["div_half_margin"], self.der["half_pairs"]
        breaks = [(key, p["year"]) for key in DIVS for p in pairs
                  if margins[key][p["h2"]] >= margins[key][p["h1"]]]
        self.assertEqual(not breaks, "各分部利润率同时呈现下半年更薄" in exhibit["note"])
        if breaks:
            for key in DIVS:
                thin = sum(1 for p in pairs if margins[key][p["h2"]] < margins[key][p["h1"]])
                with self.subTest(division=key):
                    self.assertIn(f"{mc.DIV_NAMES[key]} {thin} 次", exhibit["note"])
            every = [key for key in DIVS
                     if all(margins[key][p["h2"]] < margins[key][p["h1"]] for p in pairs)]
            self.assertEqual(not every, "没有一个分部每年都薄" in exhibit["note"])

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




class McChecksTest(unittest.TestCase):
    """The page's quarter and half against a record keyed separately from the release.

    `_checks` in the series file is typed once per roll from the results release
    itself, with the page and table each figure was read from; the builder never
    reads it (asserted in `test_data_only_roll`). Each assertion compares what the
    builder computed from the arrays with that separate reading, so a roll that
    misaligns a column, drops the new quarter or keeps last quarter's sentence
    fails here. Rolling re-keys `_checks`; this file does not change.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(mc.STAGING_PATH.read_text(encoding="utf-8"))
        cls.checks = cls.staging["_checks"]
        cls.payload = mc.build_payload(cls.staging)
        cls.der = mc.derived(cls.staging)
        cls.exhibits = {ex.get("ref"): ex for section in cls.payload["sections"]
                        for ex in section["exhibits"]}

    def test_the_page_names_the_checked_quarter_and_half(self) -> None:
        checks = self.checks
        self.assertIn(checks["period"], self.payload["title"])
        self.assertIn(checks["half"], self.payload["title"])
        self.assertIn(f"截至 {checks['period_end']}", self.payload["subtitle"])
        self.assertIn(f"发布 {checks['release_date']}", self.payload["subtitle"])

    def test_the_quarterly_series_ends_on_the_checked_quarter(self) -> None:
        checks, staging = self.checks, self.staging
        revenue = staging["quarterly_revenue_eur_m"]["total"]
        organic = staging["organic_growth_pct"]
        self.assertEqual(staging["quarter_period_ends"][-1], checks["period_end"])
        self.assertEqual(revenue[-1], checks["quarter_revenue_eur_m"])
        self.assertEqual(revenue[-2], checks["prior_quarter_revenue_eur_m"])
        self.assertEqual(organic["total"][-1], checks["quarter_organic_pct"])
        self.assertEqual(organic["total"][-2], checks["prior_quarter_organic_pct"])
        for key, value in checks["quarter_organic_by_division_pct"].items():
            with self.subTest(division=key):
                self.assertEqual(organic[key][-1], value)

    def test_the_half_series_ends_on_the_checked_half(self) -> None:
        checks, staging = self.checks, self.staging
        halves = staging["halves"]
        number, year = mc.half_parts(checks["half"])
        prior = halves.index(f"H{number} {year - 1}")
        revenue = staging["half_revenue_eur_m"]["total"]
        profit = staging["half_pro_eur_m"]
        self.assertEqual(halves[-1], checks["half"])
        self.assertEqual(revenue[-1], checks["half_revenue_eur_m"])
        self.assertEqual(revenue[prior], checks["half_revenue_prior_year_eur_m"])
        self.assertEqual(round(mc.pct_change(revenue[-1], revenue[prior])), checks["half_reported_change_pct"])
        self.assertEqual(staging["half_growth_components_pct"][checks["half"]],
                         {"organic": checks["half_organic_pct"], "perimeter": checks["half_perimeter_pct"],
                          "currency": checks["half_currency_pct"],
                          "reported": checks["half_reported_change_pct"]})
        self.assertEqual(staging["half_pro_published_total_eur_m"][checks["half"]],
                         checks["profit_from_recurring_operations_eur_m"])
        self.assertEqual(profit["total"][-1], checks["profit_from_recurring_operations_eur_m"])
        self.assertEqual(profit["total"][prior], checks["profit_from_recurring_operations_prior_year_eur_m"])
        for key, value in checks["division_profit_from_recurring_operations_eur_m"].items():
            with self.subTest(division=key):
                self.assertEqual(profit[key][-1], value)
        # The release prints the margin to one decimal; the recomputation must
        # round to it, and the page carries the printed one.
        self.assertEqual(staging["half_margin_company_printed_pct"][checks["half"]]["total"],
                         checks["operating_margin_pct"])
        self.assertEqual(round(self.der["half_margin"][-1], 1), checks["operating_margin_pct"])
        cash = staging["half_cash_eur_m"]
        self.assertEqual(staging["cash_halves"][-1], checks["half"])
        self.assertEqual(cash["ocf"][-1], checks["net_cash_from_operating_activities_eur_m"])
        self.assertEqual(cash["capex"][-1], checks["operating_investments_eur_m"])
        self.assertEqual(cash["lease_repaid"][-1], checks["repayment_of_lease_liabilities_eur_m"])
        self.assertEqual(cash["ofcf"][-1], checks["operating_free_cash_flow_eur_m"])
        self.assertEqual(staging["net_financial_debt_eur_m"][-1], checks["net_financial_debt_eur_m"])
        self.assertEqual(staging["equity_eur_m"][-1], checks["equity_eur_m"])

    def test_the_headline_charts_and_card_print_the_checked_figures(self) -> None:
        checks = self.checks
        headline = self.payload["headline"]
        self.assertIn(f"半年收入 €{checks['half_revenue_eur_m'] / 1000:.1f}B", headline)
        self.assertIn(f"报告口径 {checks['half_reported_change_pct']:+d}%", headline)
        self.assertIn(f"有机 {checks['half_organic_pct']:+d}%", headline)
        self.assertIn(f"经营利润 €{checks['profit_from_recurring_operations_eur_m']:,}M", headline)
        self.assertIn(f"集团季度收入 €{checks['quarter_revenue_eur_m']:,}M", self.exhibits["EX_REV"]["title"])
        self.assertIn(f"有机 {checks['quarter_organic_pct']:+d}%", self.exhibits["EX_REV"]["title"])
        self.assertIn(f"半年经营自由现金流 €{checks['operating_free_cash_flow_eur_m']:,}M",
                      self.exhibits["EX_CASH"]["title"])
        self.assertIn(f"半年经营性投资 €{checks['operating_investments_eur_m']:,}M",
                      self.exhibits["EX_CAPEX"]["title"])
        card = mc.headline_metrics(self.staging)
        self.assertIn(f"半年经营利润率 {checks['operating_margin_pct']:.1f}%", card)
        self.assertIn(f"本季有机 {checks['quarter_organic_pct']:+d}%", card)

    # ── the two local reports, as `_checks.note` records them ────────────────
    def test_the_closure_counts_are_the_reports_section_zero(self) -> None:
        note = self.checks["note"]["followup_closure"]
        exhibit = self.exhibits["EX_CLOSURE"]
        self.assertEqual(dict(zip(exhibit["xlabels"], exhibit["values"])), note["counts"])
        self.assertEqual(sum(exhibit["values"]), note["total"])
        self.assertTrue(exhibit["title"].startswith(f"上季 {note['total']} 条待验证问题："), exhibit["title"])
        for label, count in note["counts"].items():
            if count:
                self.assertIn(f"{count} 条{label}", exhibit["title"])
            else:
                self.assertIn(f"没有一条{label}", exhibit["title"])
        table = next(t for t in self.payload["tables"] if t["title"].startswith("上季本地分析稿的"))
        self.assertEqual(len(table["rows"]), note["total"])
        tally = {label: sum(1 for row in table["rows"] if row[2] == label) for label in note["counts"]}
        self.assertEqual(tally, note["counts"])

    def test_the_prior_thresholds_are_the_reports_section_eight(self) -> None:
        """Every threshold, comparison and number as the prior note wrote it, and
        each one's words found in the row of that note it was read from."""
        note = self.checks["note"]["prior_thresholds"]
        block = self.staging["prior_kpi_settlement"]
        said = {row["row"]: row["said"] for row in block["rows"]}
        self.assertEqual([(q["metric"], q["op"], q["threshold"]) for q in block["quantified"]],
                         [(e["metric"], e["op"], e["threshold"]) for e in note["settled"]])
        for entry, expected in zip(block["quantified"], note["settled"]):
            with self.subTest(metric=entry["metric"]):
                self.assertIn(expected["said"], said[entry["row"]])
                self.assertEqual(expected["direction"], "up" if entry["op"] in ("≥", ">") else "down")
        self.assertEqual([(r["metric"], r["op"], r["threshold"]) for r in block["reverse"]],
                         [(e["metric"], e["op"], e["threshold"]) for e in note["reverse"]])
        self.assertEqual([u["metric"] for u in block["unsettled"]], [e["metric"] for e in note["unsettled"]])
        for item, expected in zip(block["reverse"] + block["unsettled"], note["reverse"] + note["unsettled"]):
            self.assertIn(expected["said"], said[item["row"]], item["metric"])
        self.assertEqual(self.exhibits["EX_PRIOR_HEADROOM"]["xlabels"], [e["metric"] for e in note["settled"]])

    def test_the_prior_thresholds_are_settled_on_the_staged_figures(self) -> None:
        """Readings recomputed here from the staged figures, not through the builder,
        and measured in points: three of these thresholds are zero."""
        block = self.staging["prior_kpi_settlement"]
        exhibit = self.exhibits["EX_PRIOR_HEADROOM"]
        self.assertEqual(exhibit["fmt"], "pp1")
        held = 0
        for entry, value in zip(block["quantified"], exhibit["values"]):
            got = staged_reading(self.staging, entry["reads"])
            up = entry["op"] in ("≥", ">")
            with self.subTest(metric=entry["metric"]):
                self.assertAlmostEqual(value, round((got - entry["threshold"]) * (1 if up else -1), 1))
            held += {"≥": got >= entry["threshold"], ">": got > entry["threshold"],
                     "≤": got <= entry["threshold"], "<": got < entry["threshold"]}[entry["op"]]
        n = len(block["quantified"])
        self.assertEqual(exhibit["title"], f"上季 {n} 条量化阈值："
                         + (f"{n} 条全部守住" if held == n else f"{held} 条守住、{n - held} 条被击穿"))
        # the tracked series behind the quarterly one is drawn whole, against its line
        for entry in block["quantified"]:
            kind, _, key = entry["reads"].partition(".")
            if kind != "organic":
                continue
            line = self.exhibits[f"EX_PRIOR_{entry['id'].upper()}"]
            self.assertEqual(line["series"][0]["values"], self.staging["organic_growth_pct"][key])
            self.assertEqual(set(line["series"][1]["values"]), {entry["threshold"]})
            self.assertEqual(len(line["xlabels"]), len(self.staging["organic_quarters"]))


def staged_reading(staging: dict, reads: str) -> float:
    """The latest staged figure a threshold names, read straight off the series."""
    kind, _, key = reads.partition(".")
    halves = staging["halves"]
    half = halves[-1]
    number, year = mc.half_parts(half)
    ago = f"H{number} {year - 1}"
    if kind == "organic":
        return staging["organic_growth_pct"][key][-1]
    if kind == "half_organic":
        return staging["half_organic_growth_pct"][half][key]
    if kind == "half_region":
        return staging["region_half_organic_pct"][half][key]
    if kind == "margin_change":
        printed = staging["half_margin_company_printed_pct"]
        return round(printed[half][key] - printed[ago][key], 1)
    if kind == "organic_negative_run":
        run = 0
        for value in reversed(staging["organic_growth_pct"][key]):
            if value >= 0:
                break
            run += 1
        return run
    raise KeyError(reads)


def roll_forward(staging: dict) -> dict:
    """The series as a Q3 roll would leave it: one revenue-only quarter appended.

    Synthetic figures, the shape a real roll has: the quarter arrays gain a
    column, the half-year arrays do not (LVMH prints no Q3 profit), the
    quarter-stamped story blocks are gone because nobody has written them yet,
    and the half's story stays because the latest half is still the same half.
    """
    rolled = copy.deepcopy(staging)
    new = mc.quarter_before(rolled["quarters"][-1], -1)
    year, number = mc.quarter_parts(new)
    rolled["quarters"] = rolled["quarters"][1:] + [new]
    rolled["quarter_period_ends"] = rolled["quarter_period_ends"][1:] + [f"{year}-09-30"]
    rolled["long_quarters"].append(new)
    rolled["organic_quarters"].append(new)
    revenue = rolled["quarterly_revenue_eur_m"]
    other = rolled["quarterly_revenue_other_published_eur_m"]
    for key in DIVS:
        revenue[key].append(round(revenue[key][-4] * 1.02))
    other.append(other[-4])
    revenue["total"].append(sum(revenue[key][-1] for key in DIVS) + other[-1])
    split = rolled["quarterly_wines_split_eur_m"]
    split["champagne_wines"].append(round(revenue["wines_spirits"][-1] * 0.55))
    split["cognac_spirits"].append(revenue["wines_spirits"][-1] - split["champagne_wines"][-1])
    for key in rolled["organic_growth_pct"]:
        rolled["organic_growth_pct"][key].append(2)
    rolled["quarter_release_dates"][new] = f"{year}-10-14"
    rolled["latest"].update({"disclosed_period_label": mc.display_period(new),
                             "period_end": f"{year}-09-30", "release_date": f"{year}-10-14",
                             "audit_status": "unaudited"})
    rolled["sources"].append({"label": f"Q{number} {year} 收入公告（{year}-10-14）",
                              "url": "https://www.lvmh.com/en/investors/investors-and-analysts"})
    for key in ("followup_closure", "prior_kpi_settlement", "call_record", "forward_statements",
                "next_kpi", "quarter_story", "_checks"):
        del rolled[key]
    return rolled


class McRollTest(unittest.TestCase):
    """What a roll can change without touching the builder."""

    STAMPED = ("followup_closure", "prior_kpi_settlement", "call_record", "forward_statements",
               "next_kpi", "quarter_story", "half_story")
    STORY_ONLY = ("predominantly driven by volume growth", "Bvlgari", "entirely driven by currencies",
                  "10% or more per year", "VSOP", "欧元对美元、日元与韩元", "DFS 大中华",
                  "剔除中东本季", "Saks", "50.21%", "上季 12 条待验证问题")

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = json.loads(mc.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = mc.build_payload(cls.staging)
        cls.text = json.dumps(cls.payload, ensure_ascii=False)

    def test_a_block_stamped_for_another_period_stops_the_build(self) -> None:
        for key in self.STAMPED:
            stale = copy.deepcopy(self.staging)
            stale[key]["period"] = "H1 1999" if key == "half_story" else "Q1 1999"
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    mc.build_payload(stale)

    def test_a_settlement_of_some_other_quarters_notes_stops_the_build(self) -> None:
        """Stamped for this quarter is not enough: what section one settles has to
        be what last quarter's note set, not a copy carried over from further back."""
        for key in ("followup_closure", "prior_kpi_settlement"):
            stale = copy.deepcopy(self.staging)
            stale[key]["set_in"] = "Q4 2025"
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "last quarter"):
                    mc.build_payload(stale)

    def test_the_quarters_own_release_must_be_in_the_sources(self) -> None:
        prefix = mc.release_prefix(self.staging["quarters"][-1])
        bare = copy.deepcopy(self.staging)
        bare["sources"] = [s for s in bare["sources"] if not s["label"].startswith(f"{prefix} ")]
        self.assertLess(len(bare["sources"]), len(self.staging["sources"]))
        with self.assertRaisesRegex(ValueError, "sources"):
            mc.build_payload(bare)

    def test_a_period_without_its_story_leaves_it_out(self) -> None:
        bare = copy.deepcopy(self.staging)
        for key in self.STAMPED:
            del bare[key]
        payload = mc.build_payload(bare)
        text = json.dumps(payload, ensure_ascii=False)
        for phrase in self.STORY_ONLY:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)
                self.assertNotIn(phrase, text)
        # The four sections keep their places and titles; the one with nothing to
        # settle says so instead of disappearing and renumbering the rest.
        self.assertEqual([s["id"] for s in payload["sections"]],
                         ["settled", "quarter_highlights", "next_quarter", "routine"])
        settled = payload["sections"][0]
        self.assertEqual(settled["exhibits"], [])
        self.assertIn("这一节留空", settled["description"])
        for index, section in enumerate(payload["sections"], start=1):
            self.assertTrue(section["title"].startswith(f"{mc.cn_ordinal(index)}、"))
        self.assertNotRegex(text, r"\{(TBL|EX)_[A-Z_]+\}")
        self.assertEqual([t["n"] for t in payload["tables"]], list(range(1, len(payload["tables"]) + 1)))
        cards = payload["brief"].count("<article>")
        self.assertIn(f"本季{mc.cn_count(cards)}条主线", payload["brief"])

    def test_a_revenue_only_quarter_builds_from_the_series_alone(self) -> None:
        rolled = roll_forward(self.staging)
        payload = mc.build_payload(rolled)
        quarter, half = mc.display_period(rolled["quarters"][-1]), rolled["halves"][-1]
        self.assertEqual(payload["title"], f"LVMH（MC.PA）：{quarter} 季报仪表盘（利润截至 {half}）")
        self.assertEqual(payload["latest"]["disclosed_period_label"], quarter)
        self.assertIn("未经审阅", payload["subtitle"])
        self.assertIn(f"利润要等 {mc.half_of_quarter(rolled['quarters'][-1])}", payload["headline"])
        text = json.dumps(payload, ensure_ascii=False)
        # the half's own story still belongs to the latest half ...
        self.assertIn("entirely driven by currencies", text)
        # ... but the regional table, which the half-year appendix carries, is no
        # longer "this quarter", and nothing quotes last quarter's call.
        region = next(ex for s in payload["sections"] for ex in s["exhibits"] if ex.get("ref") == "EX_REGION")
        self.assertNotIn("本季", region["note"])
        self.assertNotIn("predominantly volume growth", text)

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        """Make each claim false on a copy of the series: its words must go."""
        cases = []
        # an earlier quarter in the window that did not decline
        s = copy.deepcopy(self.staging)
        i = s["long_quarters"].index(s["quarters"][3])
        total = s["quarterly_revenue_eur_m"]["total"]
        bump = total[i - 4] * 1.05 - total[i]
        total[i] += bump
        s["quarterly_revenue_eur_m"]["selective_retailing"][i] += bump
        cases.append((None, s, "季里第一次不再下滑"))
        # Three sentences the ten-year window no longer earns: over 2023-2025
        # every second half was thinner than its first, over 2016-2025 only five
        # of ten were. The page is right to have dropped them, so the control
        # that proves the words can still appear has to be built here -- an
        # assertNotIn against words that no branch can produce passes for free.
        # 「下半年更薄」 and 「上半年高于全年」 are the same statement: a full year
        # is the revenue-weighted average of its halves, so one mutation is
        # expected to take all three phrases.
        every_thinner = copy.deepcopy(self.staging)
        halves = every_thinner["halves"]
        rev = every_thinner["half_revenue_eur_m"]["total"]
        pro = every_thinner["half_pro_eur_m"]["total"]
        for i, half in enumerate(halves):
            if half.startswith("H2"):
                j = halves.index(f"H1 {mc.half_parts(half)[1]}")
                pro[i] = round(rev[i] * (pro[j] / rev[j] - 0.02))
        s = copy.deepcopy(every_thinner)
        h2 = next(i for i, h in enumerate(s["halves"]) if h.startswith("H2"))
        j = s["halves"].index(f"H1 {mc.half_parts(s['halves'][h2])[1]}")
        s["half_pro_eur_m"]["total"][h2] = round(
            s["half_revenue_eur_m"]["total"][h2]
            * (s["half_pro_eur_m"]["total"][j] / s["half_revenue_eur_m"]["total"][j] + 0.005))
        cases += [(every_thinner, s, "下半年每一次都是"),
                  (every_thinner, s, "方向没有例外"),
                  (every_thinner, s, "上半年高于全年是这家公司的常态")]
        # capital intensity that rose once
        s = copy.deepcopy(self.staging)
        s["half_cash_eur_m"]["capex"][2] = s["half_cash_eur_m"]["capex"][1] * 1.5
        cases.append((None, s, "连续下降"))
        # a June below the December before it
        s = copy.deepcopy(self.staging)
        s["net_financial_debt_eur_m"][-1] = s["net_financial_debt_eur_m"][-2] - 1
        cases.append((None, s, "每年 6 月都比前一个 12 月高"))
        # this half below the previous full year
        s = copy.deepcopy(self.staging)
        s["half_pro_eur_m"]["total"][-1] = round(s["half_revenue_eur_m"]["total"][-1] * 0.20)
        cases.append((None, s, "以来第一次同时做到"))
        # the division that "turned positive" had a positive quarter inside its run
        s = copy.deepcopy(self.staging)
        s["organic_growth_pct"]["fashion_leather"][-3] = 1
        cases.append((None, s, "个非正季度之后的第一个正数"))
        # the currency gap widened instead of snapping back
        s = copy.deepcopy(self.staging)
        s["organic_growth_pct"]["total"][-1] = 10
        cases.append((None, s, "本季骤缩到"))
        for base, staging, phrase in cases:
            with self.subTest(phrase=phrase):
                text = (self.text if base is None
                        else json.dumps(mc.build_payload(base), ensure_ascii=False))
                self.assertIn(phrase, text)
                self.assertNotIn(phrase, json.dumps(mc.build_payload(staging), ensure_ascii=False))

    def test_a_habit_of_the_last_few_years_is_not_called_a_property(self) -> None:
        """The sentences that replaced the three the window falsified.

        「下半年更薄」 holds in 2022-2025 and in one of the six years before them.
        Saying so is only worth a sentence while it stays a streak: if every year
        were thinner the page owes the universal claim instead, and if the streak
        breaks it owes neither. Both directions are checked by rebuilding.
        """
        halves = self.staging["halves"]
        rev, pro = (self.staging["half_revenue_eur_m"]["total"],
                    self.staging["half_pro_eur_m"]["total"])
        years = [mc.half_parts(h)[1] for h in halves if h.startswith("H2")]
        thin = []
        for year in years:
            h1, h2 = halves.index(f"H1 {year}"), halves.index(f"H2 {year}")
            thin.append(pro[h2] / rev[h2] < pro[h1] / rev[h1])
        run = next((i for i, flag in enumerate(reversed(thin)) if not flag), len(thin))
        earlier = thin[:len(thin) - run]
        recent = run >= 2 and bool(earlier) and sum(earlier) * 3 <= len(earlier)
        self.assertTrue(recent, "the window no longer makes this a streak; revisit the sentence")
        claim = f"是最近{mc.cn_count(run)}年才成立的"
        self.assertIn(claim, self.text)
        self.assertIn(f"{years[len(thin) - run]}–{years[-1]} 连续{mc.cn_count(run)}次更薄", self.text)

        # every year thinner: the universal sentence is owed, not this one
        s = copy.deepcopy(self.staging)
        for year in years:
            h1, h2 = halves.index(f"H1 {year}"), halves.index(f"H2 {year}")
            s["half_pro_eur_m"]["total"][h2] = round(rev[h2] * (pro[h1] / rev[h1] - 0.02))
        text = json.dumps(mc.build_payload(s), ensure_ascii=False)
        self.assertNotIn(claim, text)
        self.assertIn("方向没有例外", text)

        # the streak broken in its middle: neither sentence is owed
        s = copy.deepcopy(self.staging)
        h1, h2 = halves.index(f"H1 {years[-2]}"), halves.index(f"H2 {years[-2]}")
        s["half_pro_eur_m"]["total"][h2] = round(rev[h2] * (pro[h1] / rev[h1] + 0.02))
        text = json.dumps(mc.build_payload(s), ensure_ascii=False)
        self.assertNotIn(claim, text)
        self.assertNotIn("方向没有例外", text)

    def test_the_two_halves_of_the_same_arithmetic_are_named_as_one(self) -> None:
        """A full year is the revenue-weighted average of its halves, so
        「下半年更薄」 and 「上半年高于全年」 cannot disagree. The page says so
        only when both counts, taken at printed precision, land on the same year.
        """
        halves = self.staging["halves"]
        rev, pro = (self.staging["half_revenue_eur_m"]["total"],
                    self.staging["half_pro_eur_m"]["total"])
        margin = [100.0 * a / b for a, b in zip(pro, rev)]
        years = [mc.half_parts(h)[1] for h in halves if h.startswith("H2")]
        thin, above = [], []
        for year in years:
            h1, h2 = halves.index(f"H1 {year}"), halves.index(f"H2 {year}")
            thin.append(pro[h2] / rev[h2] < pro[h1] / rev[h1])
            whole = 100.0 * (pro[h1] + pro[h2]) / (rev[h1] + rev[h2])
            above.append(round(margin[h1], 1) > round(whole, 1))
        turn = lambda f: len(f) - next((i for i, x in enumerate(reversed(f)) if not x), len(f))
        same = turn(thin) == turn(above)
        self.assertEqual(same, "在算术上是同一句话" in self.text)
        if same:
            self.assertIn(f"上半年高于它自己那一整年，是 {years[turn(above)]} 年以后才有的事", self.text)

        # The two counts are equivalent in exact arithmetic, so the only thing
        # that can separate them is the rounding the page prints at -- which is
        # what 2018 already does at 0.02pp. A second half thinner by less than
        # that lengthens one streak and not the other, and then the page may not
        # call them the same sentence. Without this the claim is unfalsifiable:
        # the condition is true of the real data, so forcing it true changes
        # nothing and a gate that can only be satisfied proves nothing.
        s = copy.deepcopy(self.staging)
        year = years[turn(thin) - 1]
        h1, h2 = halves.index(f"H1 {year}"), halves.index(f"H2 {year}")
        s["half_pro_eur_m"]["total"][h2] = rev[h2] * (pro[h1] / rev[h1] - 0.000_01)
        text = json.dumps(mc.build_payload(s), ensure_ascii=False)
        self.assertNotIn("在算术上是同一句话", text)


if __name__ == "__main__":
    unittest.main()
