"""What the Zegna page has to keep true.

Three tests here carry most of the weight, and they are the three that would
have caught the defects this page actually shipped while everything else was
green:

* `test_a_negative_bar_sits_on_a_kind_that_can_draw_below_zero` -- the first
  draft drew the half's five growth rates as `bars_labeled`, whose y floor is
  pinned at zero (`assets/charts.js:876`). The last bar is −40.6%, so it was
  drawn from the zero line downwards, off the bottom of the card. No NaN, no
  exception, no empty element: the payload guard, the contract tests and the
  full suite were all green, and only the jsdom gate saw it.
* `test_the_geography_restatement_is_arithmetic_not_assertion` and
  `test_the_other_line_folds_are_arithmetic_not_assertion` -- the page says in
  two places that a basis change the company never explained reconciles exactly.
  Those sentences are the page's own evidence for restating eleven quarters, so
  the arithmetic is recomputed here from the figures as both bases printed them,
  rather than trusted.
* `test_the_quarterly_grid_closes_to_the_group_every_quarter` -- four
  independent decompositions of the same 22 quarters, each summed here rather
  than through the builder.

The page is rolled by editing `series/zgn.json` alone (CLAUDE.md §9), so nothing
below reads a figure out of `build/zgn.py`: every expected value is computed in
this file from the series, or from the payload by a different route than the one
the builder took.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import zgn  # noqa: E402
from build.all import ENTRIES  # noqa: E402
from build.board import display_period, round_half_up  # noqa: E402


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    return json.loads(text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0])


VALID_COLORS = {"NAVY", "BLUE", "MBLUE", "GRAY", "GREEN", "RED", "GOLD", "WHITE",
                "GRID", "AXIS", "INK"}
VALID_FORMATS = {"f1", "f0", "f0c", "int", "pct0", "pct1", "pct0z", "pp0", "pp1", "x0",
                 "usd0", "usd1", "usd2", "f2", "f3", "pct2", "usd3", "usd4"}
LITERAL_SLOTS = ("headline", "title", "subtitle", "tracker")
# Bar kinds whose y floor is pinned at zero, so a negative value is drawn off
# the canvas rather than below the axis.
ZERO_FLOORED_KINDS = {"bars_labeled", "gs_bar", "stacked_dual"}

QUARTER = re.compile(r"^\d{4}Q[1-4]$")
HALF = re.compile(r"^\d{4}H[12]$")


def text_of(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


class ZgnDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.st = json.loads(zgn.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = zgn.build_payload(cls.st)
        cls.exhibits = [ex for sec in cls.payload["sections"] for ex in sec["exhibits"]]
        cls.by_ref = {ex["ref"]: ex for ex in cls.exhibits if "ref" in ex}
        cls.q = cls.st["quarterly"]
        cls.h = cls.st["half"]
        cls.a = cls.st["annual"]
        cls.se = cls.st["segment_adjusted_ebit"]

    # ── the two axes this page runs on ───────────────────────────────────────
    def test_no_axis_mixes_quarters_and_halves(self) -> None:
        """One axis, one period type.

        The page carries a quarterly revenue record and a half-yearly profit
        record, and the whole reason it can do that is that the company prints
        discrete quarters for one and not the other. An axis holding both would
        put a half-year figure one tick away from a quarter.
        """
        for ex in self.exhibits:
            labels = [x for x in (ex.get("xlabels") or []) if isinstance(x, str)]
            kinds = {"quarter" if QUARTER.match(x) else "half" if HALF.match(x) else None
                     for x in labels}
            kinds.discard(None)
            self.assertLessEqual(len(kinds), 1,
                                 f"Ex{ex['n']} mixes {kinds} on one axis: {labels[:6]}")

    def test_no_half_year_profit_series_sits_on_a_quarterly_axis(self) -> None:
        """A profit line has no quarterly resolution to be drawn at."""
        half_only = {"gross_profit", "operating_profit", "adjusted_ebit", "profit"}
        available = {k for k in half_only if any(v is not None for v in self.h[k])}
        self.assertEqual(available, half_only, "the series lost a half-year profit line")
        for ex in self.exhibits:
            labels = [x for x in (ex.get("xlabels") or []) if isinstance(x, str)]
            if not labels or not all(QUARTER.match(x) for x in labels):
                continue
            names = [s.get("name", "") for key in ("series", "groups", "stacks")
                     for s in (ex.get(key) or [])]
            for block in ("line", "bar", "yoy"):
                if isinstance(ex.get(block), dict):
                    names.append(ex[block].get("name", ""))
            for name in names:
                self.assertNotIn("利润", name,
                                 f"Ex{ex['n']} draws {name!r} on a quarterly axis")

    def test_every_quarter_names_the_release_that_first_printed_it(self) -> None:
        """The provenance column is the page's claim that nothing was inferred."""
        q = self.q
        self.assertEqual(len(q["first_printed_by"]), len(q["periods"]))
        for period, when in zip(q["periods"], q["first_printed_by"]):
            with self.subTest(period=period):
                self.assertRegex(when, r"^\d{4}-\d{2}-\d{2}$")
                self.assertTrue(any(s.get("date") == when for s in self.st["sources"]),
                                f"{period} names a release {when} that `sources` does not list")
                # a quarter cannot have been printed before it ended
                self.assertGreater(when, q["period_ends"][q["periods"].index(period)])

    # ── the decompositions ───────────────────────────────────────────────────
    def test_the_quarterly_grid_closes_to_the_group_every_quarter(self) -> None:
        """Four independent cuts of the same quarter, each summed here."""
        q = self.q
        z = lambda block, key, i: (block[key][i] or 0.0)
        for i, period in enumerate(q["periods"]):
            total = q["revenue_eur_k"][i]
            b, ch, geo, seg = q["brand"], q["channel"], q["geography"], q["segment"]
            with self.subTest(period=period):
                self.assertEqual(
                    sum(z(b, k, i) for k in ("zegna", "thom_browne", "tff", "textile", "other")),
                    total, "brand")
                self.assertEqual(
                    z(ch, "dtc", i) + z(ch, "wholesale_branded", i)
                    + z(b, "textile", i) + z(b, "other", i), total, "channel")
                self.assertEqual(
                    sum(z(geo, k, i) for k in
                        ("emea", "americas", "greater_china", "rest_of_apac", "other")),
                    total, "geography")
                self.assertEqual(
                    sum(z(seg, k, i) for k in ("zegna", "thom_browne", "tff", "eliminations")),
                    total, "segment")
                self.assertEqual(
                    sum(z(ch, k, i) for k in ("dtc_zegna", "dtc_thom_browne", "dtc_tff")),
                    ch["dtc"][i], "DTC by brand")
                self.assertEqual(
                    sum(z(ch, k, i) for k in ("ws_zegna", "ws_thom_browne", "ws_tff")),
                    ch["wholesale_branded"][i], "wholesale by brand")

    def test_the_halves_reconcile_with_the_quarters(self) -> None:
        """The two axes have to agree where they overlap."""
        q, h = self.q, self.h
        checked = 0
        for i, half in enumerate(h["periods"]):
            if h["revenue"][i] is None:
                continue
            wanted = (1, 2) if half.endswith("H1") else (3, 4)
            try:
                summed = sum(q["revenue_eur_k"][q["periods"].index(f"{half[:4]}Q{n}")]
                             for n in wanted)
            except ValueError:
                continue
            with self.subTest(half=half):
                self.assertEqual(h["revenue"][i], summed)
            checked += 1
        self.assertGreaterEqual(checked, 9, "the overlap shrank; this test went quiet")

    def test_the_second_half_is_the_year_minus_the_first(self) -> None:
        """H2 is never a published period, and the file says which halves are."""
        h, a = self.h, self.a
        for i, half in enumerate(h["periods"]):
            printed = h["printed"][i]
            self.assertEqual(printed, half.endswith("H1"), half)
            if printed:
                continue
            year = int(half[:4])
            for line in ("revenue", "operating_profit", "profit", "adjusted_ebit"):
                fy = a[line][a["years"].index(year)]
                first = h[line][h["periods"].index(f"{year}H1")]
                with self.subTest(half=half, line=line):
                    if h[line][i] is None:
                        self.assertTrue(fy is None or first is None)
                    else:
                        self.assertEqual(h[line][i], fy - first)

    def test_segment_adjusted_ebit_sums_to_the_group_every_period(self) -> None:
        se = self.se
        for i, period in enumerate(se["periods"]):
            if se["total"][i] is None:
                continue
            parts = sum(se[k][i] or 0.0 for k in
                        ("zegna", "thom_browne", "tff", "corporate", "eliminations"))
            with self.subTest(period=period):
                self.assertEqual(parts, se["total"][i])

    def test_the_income_statement_closes_line_by_line(self) -> None:
        """Three identities, on every period that prints all of their legs."""
        for label, block, keys in (("FY", self.a, self.a["years"]),
                                   ("", self.h, self.h["periods"])):
            for i, key in enumerate(keys):
                g = lambda n: block[n][i]
                with self.subTest(period=f"{label}{key}"):
                    if None not in (g("revenue"), g("cost_of_sales"), g("gross_profit")):
                        self.assertEqual(g("revenue") + g("cost_of_sales"), g("gross_profit"))
                    if None not in (g("gross_profit"), g("sga"), g("marketing"),
                                    g("operating_profit")):
                        self.assertEqual(g("gross_profit") + g("sga") + g("marketing"),
                                         g("operating_profit"))
                    legs = ("operating_profit", "financial_income", "financial_expenses",
                            "fx", "equity_result")
                    if None not in [g(n) for n in legs] and g("pbt") is not None:
                        self.assertEqual(sum(g(n) for n in legs), g("pbt"))
                    if None not in (g("pbt"), g("tax"), g("profit")):
                        self.assertEqual(g("pbt") + g("tax"), g("profit"))

    # ── the basis changes the page restates on its own authority ─────────────
    def test_the_geography_restatement_is_arithmetic_not_assertion(self) -> None:
        """The page redraws eleven quarters onto regions the company introduced
        later, and its only warrant is that the two identities close on every
        period printed both ways. Recomputed here from both bases as printed."""
        ov = self.q["geography"]["basis_overlap"]
        periods = ov["periods"]
        self.assertGreaterEqual(len(periods), 7)
        self.assertEqual(len(periods), self.q["geography"]["periods_on_both_bases"])
        for i, period in enumerate(periods):
            with self.subTest(period=period):
                self.assertEqual(ov["old_north_america"][i] + ov["old_latin_america"][i],
                                 ov["new_americas"][i], "Americas")
                self.assertEqual(ov["old_apac"][i] - ov["old_greater_china"][i],
                                 ov["new_rest_of_apac"][i], "Rest of APAC")
                self.assertEqual(ov["old_emea"][i], ov["new_emea"][i], "EMEA")
        note = self.by_ref["EX_GEO"]["note"]
        self.assertIn("美洲 = 北美 + 拉美", note)
        self.assertIn(str(len(periods)), text_of(self.payload))

    def test_the_other_line_folds_are_arithmetic_not_assertion(self) -> None:
        """Two folds, each checked on the periods printed on both sides of it."""
        fold = self.q["brand"]["fold_overlap"]
        tpb, agn = fold["third_party_brands"], fold["agnona"]
        self.assertGreaterEqual(len(tpb["periods"]), 7)
        for i, period in enumerate(tpb["periods"]):
            with self.subTest(fold="third party brands", period=period):
                self.assertEqual(tpb["other_as_first_printed"][i] + tpb["third_party_brands"][i],
                                 tpb["other_as_refolded"][i])
        self.assertGreaterEqual(len(agn["periods"]), 2)
        for i, period in enumerate(agn["periods"]):
            with self.subTest(fold="agnona", period=period):
                self.assertEqual(agn["other_as_first_printed"][i] + agn["agnona"][i],
                                 agn["other_as_refolded"][i])

    def test_the_corporate_reallocation_is_the_corporate_line(self) -> None:
        """The page's largest restatement claim, restated as arithmetic."""
        r = next(x for x in self.st["restatements"]
                 if x["what"] == "corporate_costs_leave_the_zegna_segment")
        a = r["adjusted_ebit_eur_k"]
        for period in ("2022H1", "FY2021", "FY2020"):
            with self.subTest(period=period):
                self.assertEqual(a[f"{period}_as_restated"] + a[f"{period}_corporate_line"],
                                 a[f"{period}_as_first_published"])
        self.assertEqual(r["periods_on_both_bases"], 3)
        title = self.by_ref["EX_RESTATE"]["title"]
        self.assertIn(zgn.eur_m(abs(a["2022H1_corporate_line"])), title)
        self.assertIn(zgn.eur_m(a["2022H1_as_first_published"]), title)
        self.assertIn(zgn.eur_m(a["2022H1_as_restated"]), title)

    # ── the renderer contract, where this page has already been burned ───────
    def test_a_negative_bar_sits_on_a_kind_that_can_draw_below_zero(self) -> None:
        """`bars_labeled`, `gs_bar` and `stacked_dual` all pin `y0 = 0`
        (`assets/charts.js:874-876`), so a negative value on one of them is
        drawn from the zero line downwards and off the card. The first draft of
        Exhibit 2 did exactly that with a −40.6% bar and every gate in this
        suite stayed green; only `tests/render_check.js` saw it."""
        for ex in self.exhibits:
            if ex["kind"] not in ZERO_FLOORED_KINDS:
                continue
            values = list(ex.get("values") or [])
            for block in (ex.get("stacks") or []):
                values += list(block.get("values") or [])
            negative = [v for v in values if isinstance(v, (int, float)) and v < 0]
            with self.subTest(exhibit=ex["n"], kind=ex["kind"]):
                self.assertEqual(negative, [],
                                 f"Ex{ex['n']} is a {ex['kind']} carrying {negative}; that kind "
                                 "floors its y axis at zero, so those bars leave the canvas")

    def test_the_stacked_dual_declares_its_ceiling_inside_the_line(self) -> None:
        duals = [ex for ex in self.exhibits if ex["kind"] == "stacked_dual"]
        self.assertEqual(len(duals), 1)
        for ex in duals:
            self.assertNotIn("ymax", ex, "a top-level ymax is read by nothing")
            ceiling = ex["line"]["ymax"]
            self.assertIsInstance(ceiling, int)
            self.assertEqual(ceiling % 10, 0)
            self.assertGreaterEqual(ceiling, max(ex["line"]["values"]))

    def test_the_single_gs_bar_carries_a_yoy_line_and_no_average(self) -> None:
        bars = [ex for ex in self.exhibits if ex["kind"] == "gs_bar"]
        self.assertEqual(len(bars), 1)
        ex = bars[0]
        self.assertIn("yoy", ex)
        self.assertNotIn("avg12", ex)
        self.assertTrue(any(v is not None for v in ex["yoy"]["values"]))
        self.assertTrue(all(v >= 0 for v in ex["values"]))

    def test_every_exhibit_plots_one_point_per_x_label(self) -> None:
        for ex in self.exhibits:
            n = len(ex["xlabels"])
            self.assertGreater(n, 0, f"Ex{ex['n']}")
            blocks = []
            if ex.get("values") is not None:
                blocks.append(("values", ex["values"]))
            for key in ("yoy", "line", "bar", "net"):
                block = ex.get(key)
                if isinstance(block, dict):
                    blocks.append((key, block["values"]))
            for key in ("groups", "series", "stacks"):
                for i, block in enumerate(ex.get(key) or []):
                    blocks.append((f"{key}[{i}]", block["values"]))
            for name, values in blocks:
                with self.subTest(exhibit=ex["n"], block=name):
                    self.assertEqual(len(values), n)

    def test_exhibits_are_numbered_in_render_order_from_two(self) -> None:
        self.assertEqual([ex["n"] for ex in self.exhibits],
                         list(range(2, len(self.exhibits) + 2)))

    def test_tables_are_numbered_after_the_exhibits_and_carry_the_shared_table(self) -> None:
        tables = self.payload["tables"]
        first = self.exhibits[-1]["n"] + 1
        self.assertEqual([t["n"] for t in tables], list(range(first, first + len(tables))))
        cross = [t for t in tables if "跨页对照" in t["title"]]
        self.assertEqual(len(cross), 1, "the shared AI-capex table must appear exactly once")
        for table in tables:
            with self.subTest(table=table["n"]):
                self.assertEqual(set(table), {"n", "title", "headers", "rows"})
                for row in table["rows"]:
                    self.assertEqual(len(row), len(table["headers"]))

    def test_colour_and_formatter_names_are_ones_the_renderer_knows(self) -> None:
        def walk(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == "color" and isinstance(value, str):
                        self.assertIn(value, VALID_COLORS)
                    if key in ("fmt", "yfmt", "label_fmt") and isinstance(value, str):
                        self.assertIn(value, VALID_FORMATS)
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)
        walk(self.payload)

    def test_no_placeholder_or_markup_leaks_into_literal_slots(self) -> None:
        for slot in LITERAL_SLOTS:
            self.assertNotIn("<", self.payload[slot], slot)
            self.assertNotIn("{EX_", self.payload[slot], slot)
        for note in self.payload["notes"]:
            self.assertNotIn("<", note)
            self.assertNotIn("**", note)
        self.assertNotIn("{EX_", text_of(self.payload))

    # ── claims the page makes that the data could stop supporting ────────────
    def test_the_dtc_share_is_the_share_of_branded_revenue_not_of_the_group(self) -> None:
        """Two denominators are available and only one is the company's."""
        ch, i = self.q["channel"], len(self.q["periods"]) - 1
        branded = ch["dtc"][i] / (ch["dtc"][i] + ch["wholesale_branded"][i]) * 100
        of_group = ch["dtc"][i] / self.q["revenue_eur_k"][i] * 100
        self.assertGreater(branded, of_group)
        line = self.by_ref["EX_MIX"]["line"]
        self.assertEqual(round(line["values"][i], 1), round(branded, 1))
        self.assertIn(f"{branded:.1f}%", self.by_ref["EX_MIX"]["title"])
        self.assertNotIn(f"{of_group:.1f}%", self.by_ref["EX_MIX"]["title"])

    def test_the_americas_run_is_counted_not_typed(self) -> None:
        geo, periods = self.q["geography"], self.q["periods"]
        run = 0
        for i in range(len(periods) - 1, -1, -1):
            if geo["americas"][i] > geo["greater_china"][i]:
                run += 1
            else:
                break
        title = self.by_ref["EX_CROSS"]["title"]
        if run >= 2:
            self.assertIn(f"美洲已连续{zgn.cn_count(run)}个季度更大", title)
        else:
            self.assertNotIn("已连续", title)

    def test_the_zegna_share_of_group_ebit_is_recomputed(self) -> None:
        se = self.se
        ratio = se["zegna"][-1] / se["total"][-1] * 100
        self.assertIn(f"{ratio:.1f}%", self.by_ref["EX_SEGSHARE"]["title"])
        line = self.by_ref["EX_SEGSHARE"]["series"][0]["values"]
        self.assertEqual(round(line[-1], 1), round(ratio, 1))
        self.assertEqual(self.by_ref["EX_SEGSHARE"]["series"][1]["values"],
                         [100.0] * len(line))

    def test_the_cagr_settlement_is_recomputed_from_the_annual_record(self) -> None:
        """Rebuilt by a different route: the years summed from the quarters."""
        mt = self.st["medium_term_targets"]
        a, q = self.a, self.q
        base, last = mt["base_year"], 2025
        span = last - base
        def year_from_quarters(y):
            return sum(q["revenue_eur_k"][q["periods"].index(f"{y}Q{n}")] for n in (1, 2, 3, 4))
        self.assertEqual(year_from_quarters(base), a["revenue"][a["years"].index(base)])
        self.assertEqual(year_from_quarters(last), a["revenue"][a["years"].index(last)])
        rev = ((year_from_quarters(last) / year_from_quarters(base)) ** (1 / span) - 1) * 100
        title = self.by_ref["EX_TARGET"]["title"]
        self.assertIn(zgn.signed(rev), title)
        self.assertIn(mt["set_on"], title)
        # the base the company actually named has never been published, and the
        # page has to say so rather than quietly using the one it can compute
        self.assertIn("从未印出", self.by_ref["EX_TARGET"]["note"])

    def test_the_census_counts_are_recomputed(self) -> None:
        rows = self.st["republication_census"]["rows"]
        total = next(r for r in rows if r["kind"] == "segment" and r["row"] == "total")
        changed = [r for r in rows if r["periods_changed"] > 0]
        title = self.by_ref["EX_CENSUS"]["title"]
        self.assertIn(f"被重复公布 {total['periods_republished']} 次", title)
        self.assertIn(f"改过 {total['periods_changed']} 次", title)
        self.assertIn(f"有{zgn.cn_count(len(changed))}条改过", title)
        groups = self.by_ref["EX_CENSUS"]["groups"]
        self.assertEqual(groups[0]["values"], [r["periods_republished"] for r in rows])
        self.assertEqual(groups[1]["values"], [r["periods_changed"] for r in rows])
        for row in rows:
            self.assertLessEqual(row["periods_changed"], row["periods_republished"])

    # ── sourcing ─────────────────────────────────────────────────────────────
    def test_sources_are_official_sec_links(self) -> None:
        """Unlike the other European luxury pages, this issuer files with the
        SEC, so every original is on EDGAR and none of them is a company PDF."""
        links = self.payload["source_links"]
        self.assertGreaterEqual(len(links), 27)
        for link in links:
            with self.subTest(url=link["url"]):
                self.assertTrue(link["url"].startswith("https://www.sec.gov/"), link["url"])
                self.assertTrue(link["label"].strip())
        archives = [l for l in links if "/Archives/edgar/data/1877787/" in l["url"]]
        self.assertGreaterEqual(len(archives), 27)

    def test_the_only_dollars_on_the_page_are_the_shared_cross_page_table(self) -> None:
        cross = next(t for t in self.payload["tables"] if "跨页对照" in t["title"])
        body = copy.deepcopy(self.payload)
        body["tables"] = [t for t in body["tables"] if t["n"] != cross["n"]]
        self.assertNotIn("US$", text_of(body))
        self.assertIn("US$", text_of(cross))

    def test_the_guidance_slot_is_empty(self) -> None:
        """The company gives no quantified annual guidance; its only numeric
        forward statement is the medium-term set, which has its own section."""
        self.assertIsNone(self.payload["guidance"])

    # ── what is published ────────────────────────────────────────────────────
    def test_the_period_the_page_reports_is_the_last_half_in_the_series(self) -> None:
        h = self.h
        last = next(p for p in reversed(h["periods"])
                    if h["profit"][h["periods"].index(p)] is not None)
        self.assertEqual(self.payload["latest"]["disclosed_period_label"],
                         display_period(last))
        self.assertIn(str(int(last[:4])), self.payload["title"])

    def test_published_payload_and_shell(self) -> None:
        self.assertEqual(js_payload(ROOT / "data" / "zgn.js", "window.DASH"), self.payload)
        shell = (ROOT / "zgn" / "index.html").read_text(encoding="utf-8")
        self.assertIn("../data/zgn.js", shell)
        self.assertIn("ZGN", shell)
        self.assertNotIn("../data/ker.js", shell)

    def test_shell_versions_every_script_by_content(self) -> None:
        """A shell rendered before its payload stamps the previous build's
        digest (`build/page_shell.py:32-38`), and GitHub Pages then serves the
        new HTML with the old data for ten minutes."""
        shell = (ROOT / "zgn" / "index.html").read_text(encoding="utf-8")
        sources = re.findall(r'<script src="\.\./([^"?]+)(\?v=([0-9a-f]+))?"', shell)
        self.assertEqual([name for name, _, _ in sources],
                         ["data/roster.js", "data/zgn.js", "assets/charts.js", "assets/page.js"])
        for name, query, digest in sources:
            with self.subTest(script=name):
                self.assertTrue(query, f"{name} is served without a cache-busting version")
                expected = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()[:len(digest)]
                self.assertEqual(digest, expected, f"{name} carries a stale digest")

    def test_the_roster_entry_matches_the_payload(self) -> None:
        entry = next(e for e in ENTRIES if e["slug"] == "zgn")
        self.assertEqual(entry["ticker"], self.payload["company"]["ticker"])
        self.assertEqual(entry["group"], self.payload["company"]["group"])
        self.assertNotIn("headline_metrics", entry)
        # the fiscal year is the calendar year, so the page must not claim the
        # calendar-quarter relabelling that offset filers carry
        self.assertNotIn("本站按自然年季度标注", entry["cadence_label"])
        self.assertIn("单季", entry["cadence_label"])

    def test_the_home_page_card_matches_the_payload(self) -> None:
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        card = home.split('href="zgn/"', 1)[1].split("</a>", 1)[0]
        self.assertIn(self.payload["latest"]["release_date"], card)
        self.assertIn(self.payload["latest"]["disclosed_period_label"], card)
        self.assertIn("ZGN", card)
        self.assertIn(" · ".join(zgn.headline_metrics(self.st)), card)

    def test_the_card_figures_are_three_and_computed(self) -> None:
        metrics = zgn.headline_metrics(self.st)
        self.assertEqual(len(metrics), 3)
        self.assertTrue(all(m.strip() for m in metrics))
        h, i = self.h, self.h["periods"].index(
            self.payload["latest"]["disclosed_period_label"].replace("H1 ", "") + "H1")
        self.assertIn(zgn.eur_m(h["revenue"][i]), metrics[0])


class ZgnRollTest(unittest.TestCase):
    """What a roll has to change in `series/zgn.json`, and what the page does
    when it does not."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads(zgn.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = zgn.build_payload(cls.source)

    def test_a_block_stamped_with_another_period_stops_the_build(self) -> None:
        stale = copy.deepcopy(self.source)
        stale["half_story"]["period"] = "H1 1999"
        with self.assertRaisesRegex(ValueError, "stamped"):
            zgn.build_payload(stale)

        stale_latest = copy.deepcopy(self.source)
        stale_latest["latest"]["period"] = "H1 1999"
        with self.assertRaisesRegex(ValueError, "stamped"):
            zgn.build_payload(stale_latest)

        orphan = copy.deepcopy(self.source)
        period = self.payload["latest"]["disclosed_period_label"]
        year = period.split()[-1]
        orphan["sources"] = [s for s in orphan["sources"]
                             if not s["label"].startswith(f"{year} 年上半年业绩")]
        with self.assertRaisesRegex(ValueError, "sources"):
            zgn.build_payload(orphan)

    def test_a_half_without_its_story_leaves_it_out(self) -> None:
        """An optional stamped block is a half's story, not a fixture."""
        full = zgn.build_payload(self.source)
        bare = zgn.build_payload({k: v for k, v in self.source.items() if k != "half_story"})
        self.assertIn("看跌期权", text_of(full))
        self.assertNotIn("看跌期权", text_of(bare))

        full_ex = [ex for sec in full["sections"] for ex in sec["exhibits"]]
        bare_ex = [ex for sec in bare["sections"] for ex in sec["exhibits"]]
        self.assertEqual(len(bare_ex), len(full_ex) - 1)
        self.assertEqual([ex["n"] for ex in bare_ex], list(range(2, len(bare_ex) + 2)))
        self.assertNotIn("{EX_", text_of(bare))
        first = bare["tables"][0]["n"]
        self.assertEqual(first, bare_ex[-1]["n"] + 1)

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        """Break each universal claim in the data and watch its sentence go.

        Recomputing the numbers cannot see a universal proposition turn false,
        which is why each of these makes the claim false and asserts on the
        wording that disappears.
        """
        # 1. "the group total has never come back different"
        moved = copy.deepcopy(self.source)
        row = next(r for r in moved["republication_census"]["rows"]
                   if r["kind"] == "segment" and r["row"] == "total")
        row["periods_changed"] = 1
        title = next(ex for sec in zgn.build_payload(moved)["sections"]
                     for ex in sec["exhibits"] if ex.get("ref") == "EX_CENSUS")["title"]
        self.assertIn("改过 1 次", title)
        self.assertNotIn("改过 0 次", title)

        # 2. "the Americas has been larger for N consecutive quarters"
        broken = copy.deepcopy(self.source)
        geo = broken["quarterly"]["geography"]
        geo["americas"][-1] = geo["greater_china"][-1] - 1.0
        geo["emea"][-1] += 1.0
        title = next(ex for sec in zgn.build_payload(broken)["sections"]
                     for ex in sec["exhibits"] if ex.get("ref") == "EX_CROSS")["title"]
        self.assertNotIn("已连续", title)

        # 3. "every line above the operating result rose"
        fell = copy.deepcopy(self.source)
        h = fell["half"]
        i = h["periods"].index("2026H1")
        h["gross_profit"][i] = h["gross_profit"][h["periods"].index("2025H1")] - 1.0
        title = next(ex for sec in zgn.build_payload(fell)["sections"]
                     for ex in sec["exhibits"] if ex.get("ref") == "EX_LADDER")["title"]
        self.assertNotIn("全部为正", title)

        # 4. "the Zegna segment alone is more than the group"
        shrunk = copy.deepcopy(self.source)
        se = shrunk["segment_adjusted_ebit"]
        se["zegna"][-1] = se["total"][-1] / 2
        se["corporate"][-1] = se["total"][-1] - sum(
            se[k][-1] or 0.0 for k in ("zegna", "thom_browne", "tff", "eliminations")
            if k != "corporate")
        title = next(ex for sec in zgn.build_payload(shrunk)["sections"]
                     for ex in sec["exhibits"] if ex.get("ref") == "EX_SEGSHARE")["title"]
        self.assertNotIn("已连续", title)

    def test_the_next_half_rolls_without_touching_the_code(self) -> None:
        """Append a synthetic half and rebuild: no code change, new labels."""
        rolled = copy.deepcopy(self.source)
        h, q = rolled["half"], rolled["quarterly"]
        for n in (3, 4):
            q["periods"].append(f"2026Q{n}")
            q["period_ends"].append(f"2026-{'09-30' if n == 3 else '12-31'}")
            q["first_printed_by"].append("2026-10-22" if n == 3 else "2027-01-27")
            q["revenue_eur_k"].append(q["revenue_eur_k"][-4])
            for group in ("brand", "channel", "geography", "segment"):
                for key, values in q[group].items():
                    if isinstance(values, list) and len(values) == len(q["periods"]) - 1:
                        values.append(values[-4])
        h["periods"].append("2026H2")
        h["printed"].append(False)
        for key, values in h.items():
            if isinstance(values, list) and len(values) == len(h["periods"]) - 1:
                values.append(values[-2])
        rolled["latest"] = dict(rolled["latest"], period="H2 2026",
                                period_end="2026-12-31", release_date="2027-03-19")
        rolled["half_story"]["period"] = "H2 2026"
        rolled["sources"] = rolled["sources"] + [
            {"label": "2026 年下半年业绩新闻稿（6-K EX-99.1，2027-03-19）",
             "url": "https://www.sec.gov/Archives/edgar/data/1877787/x/y.htm",
             "date": "2027-03-19"}]
        payload = zgn.build_payload(rolled)
        self.assertEqual(payload["latest"]["disclosed_period_label"], "H2 2026")
        self.assertIn("2026 年下半年", payload["title"])
        mix = next(ex for sec in payload["sections"] for ex in sec["exhibits"]
                   if ex.get("ref") == "EX_MIX")
        self.assertEqual(mix["xlabels"][-1], "2026Q4")
        self.assertEqual(len(mix["stacks"][0]["values"]), len(mix["xlabels"]))


class ZgnChecksTest(unittest.TestCase):
    """`_checks` is an independent re-read of the primary filing.

    The rest of this series is built from the 6-K earnings releases. `_checks`
    was typed from the Semi-Annual Report furnished with the same results --
    a different document, with its own tables -- so the two agreeing is
    evidence rather than a tautology. The builder never reads the block
    (`tests/test_data_only_roll.py` proves that), which is what keeps it so.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.st = json.loads(zgn.STAGING_PATH.read_text(encoding="utf-8"))
        cls.c = cls.st["_checks"]
        cls.payload = zgn.build_payload(cls.st)
        cls.h = cls.st["half"]
        cls.q = cls.st["quarterly"]

    def test_the_page_names_the_checked_period(self) -> None:
        c, latest = self.c, self.payload["latest"]
        self.assertEqual(c["period"], latest["disclosed_period_label"])
        self.assertEqual(c["period_end"], latest["period_end"])
        self.assertEqual(c["release_date"], latest["release_date"])
        self.assertIn(f"截至 {c['period_end']}", self.payload["subtitle"])
        self.assertIn(f"发布 {c['release_date']}", self.payload["subtitle"])
        self.assertTrue(c["source"].strip())
        self.assertIn("Semi-Annual Report", c["source"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        """Each checked figure against the series cell it should equal."""
        c, h, q = self.c, self.h, self.q
        i = h["periods"].index("2026H1")
        j = h["periods"].index("2025H1")
        for key, got in (("revenue_eur_k", h["revenue"][i]),
                         ("revenue_prior_year_eur_k", h["revenue"][j]),
                         ("gross_profit_eur_k", h["gross_profit"][i]),
                         ("operating_profit_eur_k", h["operating_profit"][i]),
                         ("operating_profit_prior_year_eur_k", h["operating_profit"][j]),
                         ("adjusted_ebit_eur_k", h["adjusted_ebit"][i]),
                         ("adjusted_ebit_prior_year_eur_k", h["adjusted_ebit"][j]),
                         ("profit_eur_k", h["profit"][i]),
                         ("profit_prior_year_eur_k", h["profit"][j])):
            with self.subTest(key=key):
                self.assertEqual(got, c[key])

        idx = [q["periods"].index(p) for p in ("2026Q1", "2026Q2")]
        prior = [q["periods"].index(p) for p in ("2025Q1", "2025Q2")]
        self.assertEqual(sum(q["revenue_eur_k"][k] for k in idx), c["revenue_eur_k"])
        self.assertEqual(sum(q["channel"]["dtc"][k] for k in idx), c["dtc_eur_k"])
        self.assertEqual(sum(q["channel"]["wholesale_branded"][k] for k in idx),
                         c["wholesale_branded_eur_k"])
        # the same brand on two bases, which is why both are pinned
        self.assertEqual(sum(q["brand"]["thom_browne"][k] for k in prior),
                         c["thom_browne_revenue_brand_basis_prior_year_eur_k"])
        self.assertEqual(sum(q["segment"]["thom_browne"][k] for k in prior),
                         c["thom_browne_revenue_segment_basis_prior_year_eur_k"])
        self.assertNotEqual(c["thom_browne_revenue_brand_basis_prior_year_eur_k"],
                            c["thom_browne_revenue_segment_basis_prior_year_eur_k"])

        se = self.st["segment_adjusted_ebit"]
        k = se["periods"].index("2026H1")
        for key, got in (("segment_adjusted_ebit_zegna_eur_k", se["zegna"][k]),
                         ("segment_adjusted_ebit_thom_browne_eur_k", se["thom_browne"][k]),
                         ("segment_adjusted_ebit_tff_eur_k", se["tff"][k]),
                         ("segment_adjusted_ebit_corporate_eur_k", se["corporate"][k])):
            with self.subTest(key=key):
                self.assertEqual(got, c[key])

        nfp = self.st["net_financial_position"]
        self.assertEqual(-nfp["net_debt_eur_k"][nfp["dates"].index(c["period_end"])],
                         c["net_cash_surplus_eur_k"])
        cash = self.st["cash"]
        self.assertEqual(cash["half_capex_eur_k"][-1], c["capex_eur_k"])
        self.assertEqual(cash["half_free_cash_flow_eur_k"][-1], c["free_cash_flow_eur_k"])
        st = self.st["stores"]
        self.assertEqual(st["dates"][-1], c["period_end"])
        for brand, key in (("ZEGNA", "dos_zegna"), ("Thom Browne", "dos_thom_browne"),
                           ("TOM FORD FASHION", "dos_tff"), ("Group", "dos_group")):
            with self.subTest(brand=brand):
                self.assertEqual(st["dtc"][brand][-1], c[key])

        put = self.st["half_story"]
        self.assertEqual(put["fair_value_swing_eur_k"], c["put_option_fair_value_swing_eur_k"])
        self.assertEqual(put["fx_swing_eur_k"], c["put_option_fx_swing_eur_k"])
        self.assertEqual(put["liability_eur_k"], c["thom_browne_put_option_eur_k"])

    def test_the_rounding_the_page_uses_is_the_companys(self) -> None:
        """Where the page recomputes a percentage the filer also printed, its
        rounding has to land on the filer's digit."""
        c, h, q = self.c, self.h, self.q
        i = h["periods"].index("2026H1")
        for key, value, digits in (
                ("gross_margin_printed_pct", h["gross_profit"][i] / h["revenue"][i] * 100, 1),
                ("adjusted_ebit_margin_printed_pct",
                 h["adjusted_ebit"][i] / h["revenue"][i] * 100, 1),
                ("revenue_growth_reported_pct",
                 (h["revenue"][i] / h["revenue"][h["periods"].index("2025H1")] - 1) * 100, 1),
                ("capex_pct_of_revenue_printed_pct",
                 self.st["cash"]["half_capex_eur_k"][-1] / h["revenue"][i] * 100, 1)):
            with self.subTest(key=key):
                self.assertEqual(float(round_half_up(value, digits)), float(c[key]))
        idx = [q["periods"].index(p) for p in ("2026Q1", "2026Q2")]
        dtc = sum(q["channel"]["dtc"][k] for k in idx)
        ws = sum(q["channel"]["wholesale_branded"][k] for k in idx)
        self.assertEqual(int(round_half_up(dtc / (dtc + ws) * 100, 0)),
                         c["dtc_share_of_branded_printed_pct"])

    def test_the_page_prints_the_checked_figures(self) -> None:
        """The last edge: `_checks` against what a reader actually sees."""
        c, payload = self.c, self.payload
        head = payload["headline"]
        self.assertIn(zgn.eur_m(c["revenue_eur_k"]), head)
        self.assertIn(zgn.eur_m(c["adjusted_ebit_eur_k"]), head)
        self.assertIn(zgn.eur_m(c["profit_eur_k"]), head)
        self.assertIn(f"{c['adjusted_ebit_margin_printed_pct']:.1f}%", head)

        by_ref = {ex["ref"]: ex for sec in payload["sections"] for ex in sec["exhibits"]
                  if "ref" in ex}
        put_title = by_ref["EX_PUT"]["title"]
        swing = c["put_option_fair_value_swing_eur_k"] + c["put_option_fx_swing_eur_k"]
        self.assertIn(zgn.eur_m(swing), put_title)
        self.assertIn(zgn.eur_m(c["thom_browne_put_option_eur_k"]), by_ref["EX_PUT"]["note"])
        self.assertIn(f"{c['effective_tax_rate_printed_pct']:.1f}%", by_ref["EX_PUT"]["note"])

        doors_title = by_ref["EX_DOORS"]["title"]
        self.assertIn(str(c["dos_group"]), doors_title)
        self.assertIn(f"{c['dtc_share_of_branded_printed_pct']}%", by_ref["EX_MIX"]["note"])

        table = next(t for t in payload["tables"] if "单季收入" in t["title"])
        self.assertEqual(table["rows"][-1][0], self.q["periods"][-1])


if __name__ == "__main__":
    unittest.main()
