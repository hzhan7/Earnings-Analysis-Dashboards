"""Brunello Cucinelli page: what licenses a page built out of subtraction.

Almost every number this page draws was obtained by subtracting one cumulative
disclosure from the next, because the issuer publishes only to-date figures: a
first quarter, a half, nine months, a year. It has never printed a second,
third or fourth quarter, nor a second half. That makes two of these tests
load-bearing in a way the other company pages do not need.

- `test_the_derived_third_quarter_matches_the_figure_the_company_quotes` is the
  **only** external check on the subtraction anywhere in the record. The issuer
  quotes a standalone third quarter in prose three times without ever tabling
  it, and those three quotes are the one place a reader can see whether
  9M - H1 reproduces what the company thinks its third quarter was.
- `test_the_year_sum_is_not_treated_as_a_check` exists to stop a future reader
  reaching for the obvious identity instead. Four quarters do sum to the filed
  year here, and that proves nothing at all: the fourth quarter is *defined* as
  the year minus nine months, so the sum is an algebraic tautology. A check
  that derives its expected value from the thing it is checking cannot fail.
  It is pinned as a tautology so nobody promotes it to evidence.

The third one worth naming is `test_the_geography_rows_sum_to_the_printed_total`.
The issuer changed its regional presentation in H1 2025 -- four rows became
three, Italy folded into Europe, the prior year re-presented -- and said so
nowhere in words. The only evidence is arithmetic, so the arithmetic is the test.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import bc  # noqa: E402
from build.board import headroom  # noqa: E402

MARKUP = re.compile(r"</?[a-z][a-z0-9]*>", re.I)


def exhibits(payload: dict) -> list[dict]:
    return [ex for section in payload["sections"] for ex in section["exhibits"]]


class BcDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.s = json.loads(bc.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = bc.build_payload(json.loads(bc.STAGING_PATH.read_text(encoding="utf-8")))

    # ── the subtraction, and what does and does not check it ────────────────
    def test_the_quarterly_series_is_the_stated_subtraction(self) -> None:
        c = self.s["cumulative_revenue_eur_k"]
        years = c["years"]
        q = self.s["quarterly"]
        for index, period in enumerate(q["periods"]):
            year, quarter = int(period[:4]), int(period[-1])
            j = years.index(year)
            if quarter == 1:
                expected = c["q1"][j]
            elif quarter == 2:
                expected = c["h1"][j] - c["q1"][j]
            elif quarter == 3:
                expected = c["nine_m"][j] - c["h1"][j]
            else:
                expected = c["fy"][j] - c["nine_m"][j]
            self.assertEqual(q["revenue_eur_k"][index], expected, period)

    def test_no_quarter_or_half_is_a_hole(self) -> None:
        """Every quarter is either printed or obtainable by one subtraction, so a
        `None` here is a lost point rather than an honest gap. Found by mutation:
        blanking the last quarter left the rendered-chart check green, because
        that check counted the payload's own finite values on both sides.
        """
        q = self.s["quarterly"]
        self.assertEqual(len(q["revenue_eur_k"]), len(q["periods"]))
        self.assertEqual(len(q["basis"]), len(q["periods"]))
        for period, value in zip(q["periods"], q["revenue_eur_k"]):
            self.assertIsNotNone(value, period)
            self.assertGreater(value, 0, period)
        h = self.s["half"]
        for key in ("revenue_eur_k", "ebit_eur_k", "ebitda_eur_k", "net_profit_eur_k"):
            for period, value in zip(h["periods"], h[key]):
                self.assertIsNotNone(value, f"{period} {key}")

    def test_the_derived_third_quarter_matches_the_figure_the_company_quotes(self) -> None:
        """The only external check on the subtraction that exists."""
        q = self.s["quarterly"]
        quoted = q["narrative_q3_crosscheck_eur_m"]
        self.assertEqual(len(quoted), 3)
        for period, stated in quoted.items():
            derived = q["revenue_eur_k"][q["periods"].index(period)] / 1000
            # 2024 is quoted only to the nearest hundred million; the other two
            # are quoted to 0.1, so the tolerance is the printed precision.
            tolerance = 50.0 if stated == round(stated, -2) and stated == 300.0 else 0.05
            self.assertLessEqual(abs(derived - stated), tolerance,
                                 f"{period}: derived {derived:.1f} vs quoted {stated}")

    def test_the_year_sum_is_not_treated_as_a_check(self) -> None:
        """Pinned as a tautology so it is never promoted to evidence.

        Q4 is defined as FY - 9M, so this closes by construction for every year
        and would keep closing if every input were wrong together.
        """
        c = self.s["cumulative_revenue_eur_k"]
        q = self.s["quarterly"]
        for year in (2022, 2023, 2024, 2025):
            total = sum(q["revenue_eur_k"][q["periods"].index(f"{year}Q{n}")] for n in (1, 2, 3, 4))
            self.assertEqual(total, c["fy"][c["years"].index(year)])
        self.assertIn("不构成验证", " ".join(self.payload["notes"]))

    def test_the_half_year_series_marks_which_halves_were_published(self) -> None:
        h = self.s["half"]
        self.assertEqual(len(h["periods"]), len(h["printed"]))
        for period, printed in zip(h["periods"], h["printed"]):
            self.assertEqual(printed, period.endswith("H1"), period)
        self.assertEqual(sum(h["printed"]), 6)
        self.assertEqual(len(h["periods"]) - sum(h["printed"]), 5)

    def test_second_halves_are_the_year_minus_the_first_half(self) -> None:
        h, a = self.s["half"], self.s["annual"]
        for index, period in enumerate(h["periods"]):
            if not period.endswith("H2"):
                continue
            year = int(period[:4])
            j, first = a["years"].index(year), h["periods"].index(f"{year}H1")
            for key in ("revenue_eur_k", "ebit_eur_k", "ebitda_eur_k",
                        "net_profit_eur_k", "ebitda_ex_ifrs16_eur_k"):
                annual, half = a[key][j], h[key][first]
                expected = None if annual is None or half is None else annual - half
                self.assertEqual(h[key][index], expected, f"{period} {key}")

    # ── the identity that licenses the one derived EBITDA ───────────────────
    def test_company_ebitda_equals_operating_income_plus_depreciation(self) -> None:
        """Five printed periods close exactly, which is what lets H1 2026's
        EBITDA be derived on the same definition rather than assumed."""
        h = self.s["half"]
        checked = 0
        for index, period in enumerate(h["periods"]):
            da, ebitda, ebit = (h["da_eur_k"][index], h["ebitda_eur_k"][index],
                                h["ebit_eur_k"][index])
            if da is None or ebitda is None:
                continue
            self.assertEqual(ebitda, ebit + da, period)
            checked += 1
        self.assertGreaterEqual(checked, 6)

    def test_the_derived_2026_ebitda_uses_that_definition(self) -> None:
        h = self.s["half"]
        i = h["periods"].index("2026H1")
        self.assertEqual(h["ebitda_eur_k"][i], h["ebit_eur_k"][i] + h["da_eur_k"][i])

    # ── the silent re-presentation ──────────────────────────────────────────
    def test_the_geography_rows_sum_to_the_printed_total(self) -> None:
        g, c = self.s["geography_h1_eur_k"], self.s["cumulative_revenue_eur_k"]
        for index, year in enumerate(g["years"]):
            total = c["h1"][c["years"].index(year)]
            self.assertEqual(
                g["europe_total"][index] + g["americas"][index] + g["asia"][index],
                total, f"{year}H1 geography")

    def test_europe_is_italy_inclusive_in_every_year(self) -> None:
        """The 2024 re-presentation is the only evidence the change happened."""
        g = self.s["geography_h1_eur_k"]
        i = g["years"].index(2024)
        self.assertEqual(g["europe_total"][i], 152959 + 68093)
        separate = [v for v in g["italy_row_when_separate"] if v is not None]
        self.assertEqual(len(separate), 4, "Italy was a separate row for four years")
        self.assertIsNone(g["italy_row_when_separate"][g["years"].index(2025)])

    def test_the_channel_rows_sum_to_the_printed_total(self) -> None:
        ch, c = self.s["channel_h1_eur_k"], self.s["cumulative_revenue_eur_k"]
        for index, year in enumerate(ch["years"]):
            self.assertEqual(ch["retail"][index] + ch["wholesale"][index],
                             c["h1"][c["years"].index(year)], f"{year}H1 channel")

    # ── the guidance basis, which is the page's argument ────────────────────
    def test_the_basis_census_adds_up(self) -> None:
        cen = self.s["guidance_basis_census"]
        by = self.s["guidance_basis_by_year"]
        self.assertEqual(cen["fx_basis_stated"] + cen["fx_basis_unstated"],
                         cen["quantified_rows"])
        self.assertEqual(sum(by["basis_stated"]), cen["fx_basis_stated"])
        self.assertEqual(sum(by["basis_unstated"]), cen["fx_basis_unstated"])

    def test_no_basis_was_stated_before_the_year_the_page_names(self) -> None:
        """The claim is 'every stated one is December 2025 or later'."""
        by = self.s["guidance_basis_by_year"]
        first = int(self.s["guidance_basis_census"]["first_stated_date"][:4])
        for year, stated in zip(by["years"], by["basis_stated"]):
            if year < first:
                self.assertEqual(stated, 0, f"{year} states a basis")
        self.assertGreater(sum(s for y, s in zip(by["years"], by["basis_stated"])
                               if y >= first), 0)

    def test_each_guidance_year_is_settled_on_its_own_basis(self) -> None:
        """Pairing the constant-rate leg with reported revenue is the trap this
        page is about; the series must not encode that pairing."""
        g = self.s["annual_revenue_guidance"]
        i = g["target_years"].index(2025)
        self.assertEqual(g["final_basis"][i], "reported")
        self.assertGreaterEqual(g["actual_reported_pct"][i], g["final_low"][i])
        # and the constant-rate leg settles inside its own range
        self.assertGreaterEqual(g["actual_cfx_pct"][i], g["cfx_leg_low"][i])
        self.assertLessEqual(g["actual_cfx_pct"][i], g["cfx_leg_high"][i])

    def test_the_two_bases_straddle_the_current_guidance(self) -> None:
        """The headline claim: above on one basis, below on the other."""
        g = self.s["annual_revenue_guidance"]
        gr = self.s["growth_h1_pct"]
        i = g["target_years"].index(2026)
        low, high = g["final_low"][i], g["final_high"][i]
        self.assertEqual(g["final_basis"][i], "cfx")
        self.assertGreater(gr["cfx"][-1], high)
        self.assertLess(gr["reported"][-1], low)

    def test_the_strict_judgeable_count_is_smaller_than_the_met_count(self) -> None:
        st = self.s["annual_revenue_guidance"]["strict_judgeability"]
        self.assertEqual(st["met"], st["completed_quantified_targets"])
        self.assertEqual(st["missed"], 0)
        self.assertLess(st["scoreable_once_an_unstated_basis_is_treated_as_unjudgeable"],
                        st["completed_quantified_targets"])

    # ── the withdrawn disclosure ────────────────────────────────────────────
    def test_the_lease_adjusted_line_stops_where_disclosure_stopped(self) -> None:
        dec = self.s["ifrs16_disclosure_decay"]
        self.assertEqual(dec["ebitda_token_count"][-1], 0)
        self.assertEqual(dec["both_bases_printed"], [True, True, True, True, False, False])
        self.assertEqual(dec["bridge_printed"], [True, True, True, False, False, False])
        h = self.s["half"]
        for year in (2025, 2026):
            self.assertIsNone(h["ebitda_ex_ifrs16_eur_k"][h["periods"].index(f"{year}H1")])

    def test_the_page_says_the_gap_was_narrowing_when_it_was_withdrawn(self) -> None:
        """Refusing the easy story is the point; the numbers have to back it."""
        h = self.s["half"]
        gaps = []
        for year in (2021, 2022, 2023, 2024):
            i = h["periods"].index(f"{year}H1")
            rev = h["revenue_eur_k"][i]
            gaps.append(h["ebitda_eur_k"][i] / rev * 100
                        - h["ebitda_ex_ifrs16_eur_k"][i] / rev * 100)
        self.assertLess(gaps[-1], gaps[0], "the disclosed wedge was not narrowing")
        self.assertAlmostEqual(gaps[0], 13.0, delta=0.1)
        self.assertAlmostEqual(gaps[-1], 9.2, delta=0.1)

    # ── render contract ─────────────────────────────────────────────────────
    def test_every_series_matches_its_axis(self) -> None:
        for ex in exhibits(self.payload):
            width = len(ex["xlabels"])
            for series in ex.get("series", []) + ex.get("groups", []) + ex.get("stacks", []):
                self.assertEqual(len(series["values"]), width,
                                 f"Ex{ex['n']} {series.get('name')}")
            for key in ("values", "lo", "hi", "actual"):
                if isinstance(ex.get(key), list):
                    self.assertEqual(len(ex[key]), width, f"Ex{ex['n']} {key}")
            for key in ("yoy", "line", "net"):
                if isinstance(ex.get(key), dict):
                    self.assertEqual(len(ex[key]["values"]), width, f"Ex{ex['n']} {key}")

    def test_stacked_dual_declares_a_right_axis_ceiling_above_its_own_data(self) -> None:
        """`charts.js` hardcodes the right axis to 60 when `line.ymax` is absent,
        and the key is read off `ex.line`, not off the exhibit."""
        found = 0
        for ex in exhibits(self.payload):
            if ex.get("kind") != "stacked_dual":
                continue
            found += 1
            line = ex["line"]
            self.assertIn("ymax", line, f"Ex{ex['n']} would be capped at 60")
            self.assertGreaterEqual(line["ymax"], max(v for v in line["values"] if v is not None))
        self.assertGreaterEqual(found, 1)

    def test_every_gs_bar_carries_a_year_on_year_block(self) -> None:
        """Without `yoy` the renderer looks for `avg12`, which no payload here
        supplies; the site census asserts that branch stays unexercised."""
        for ex in exhibits(self.payload):
            if ex.get("kind") != "gs_bar":
                continue
            self.assertTrue(ex.get("yoy"), f"Ex{ex['n']} has no yoy block")
            self.assertNotIn("avg12", ex)
            self.assertTrue(any(v is not None for v in ex["yoy"]["values"]))

    def test_bar_charts_carry_a_value_for_every_label_they_print(self) -> None:
        """The payload-side half of the same check, so it holds without node.

        Found by mutation: blanking one quarter kept every length equal and left
        both the site-wide length check and the rendered-chart check green, the
        latter because it counted the payload's own finite values on both sides
        of the comparison. A bar chart declaring 18 x labels promises 18 bars.
        """
        for ex in exhibits(self.payload):
            if ex.get("kind") not in ("gs_bar", "bars_labeled"):
                continue
            values = ex["values"]
            self.assertEqual(len(values), len(ex["xlabels"]), f"Ex{ex['n']} length")
            self.assertEqual(
                sum(1 for v in values if v is not None), len(ex["xlabels"]),
                f"Ex{ex['n']} prints {len(ex['xlabels'])} labels but has a hole")

    def test_every_bridge_column_draws_something(self) -> None:
        for ex in exhibits(self.payload):
            if ex.get("kind") != "bridge_bar":
                continue
            self.assertIsInstance(ex["net"], dict)
            for index, label in enumerate(ex["xlabels"]):
                drawn = any(s["values"][index] not in (None, 0) for s in ex["stacks"])
                drawn = drawn or ex["net"]["values"][index] not in (None, 0)
                self.assertTrue(drawn, f"Ex{ex['n']} column {label!r} is empty")

    def test_the_headroom_bars_agree_with_the_audit_table(self) -> None:
        entries = self.s["next_kpi"]["quantified"]
        chart = next(ex for ex in exhibits(self.payload) if ex["kind"] == "diverging_bars")
        for entry, value in zip(entries, chart["values"]):
            self.assertAlmostEqual(
                value, round(headroom(entry["direction"], entry["threshold"], entry["current"]), 1),
                places=6, msg=entry["metric"])
        breached = sum(1 for v in chart["values"] if v < 0)
        self.assertEqual(breached, 3, "three thresholds are currently breached")
        # and the prose must agree with the count rather than be written by hand
        self.assertIn("三条已经越线", chart["note"])

    # ── counts printed in prose, which nothing else guards ─────────────────
    def test_every_count_quoted_in_prose_is_recomputed_from_the_data(self) -> None:
        """Hand-typed counts in a title or a note have no gate behind them, and
        on a half-year axis they are unusually easy to get wrong: "a year ago"
        is two indices back, not four. Three shipped in the first draft of this
        page -- a six-half run described as five with 2025H1 dropped out of the
        list, a region named as the smallest block when it was the middle one,
        and a three-year span called two. All are derived now; this asserts the
        prose still agrees with the arithmetic.
        """
        by_ref = {ex["ref"]: ex for ex in exhibits(self.payload) if "ref" in ex}
        h = self.s["half"]
        margin = [e / r * 100 for e, r in zip(h["ebit_eur_k"], h["revenue_eur_k"])]

        # EX_MARGIN: the run length and every value in it
        start = h["periods"].index("2023H2")
        run = margin[start:]
        note = by_ref["EX_MARGIN"]["note"]
        self.assertIn(f"共 {len(run)} 个半年", note)
        self.assertIn("、".join(f"{v:.1f}" for v in run), note)
        self.assertIn(f"{len(run)} 个半年", by_ref["EX_MARGIN"]["title"])

        # EX_REGION: which block was largest, first half and last
        geo = self.s["geography_h1_eur_k"]
        rows = {"欧洲": geo["europe_total"], "美洲": geo["americas"], "亚洲": geo["asia"]}
        first = {k: v[0] for k, v in rows.items()}
        last = {k: v[-1] for k, v in rows.items()}
        title = by_ref["EX_REGION"]["title"]
        self.assertIn(f"从{max(first, key=first.get)}换成{max(last, key=last.get)}", title)
        # and the block the page says shrank must actually be the one that shrank
        totals = [sum(col[i] for col in rows.values()) for i in range(len(geo["years"]))]
        drop = (first["欧洲"] / totals[0] - last["欧洲"] / totals[-1]) * 100
        self.assertIn(f"{drop:.1f} 个百分点", title)

        # EX_DEBT: the span is measured from the trough, not asserted
        nd = self.s["net_debt_h1_eur_k"]
        trough = nd["pre_ifrs16"].index(min(nd["pre_ifrs16"]))
        self.assertIn(f"{nd['years'][-1] - nd['years'][trough]} 年", by_ref["EX_DEBT"]["title"])

        # EX_MIX: the plateau band
        ch = self.s["channel_h1_eur_k"]
        share = [r / (r + w) * 100 for r, w in zip(ch["retail"], ch["wholesale"])]
        mix = by_ref["EX_MIX"]["title"]
        self.assertIn(f"{min(share[2:5]):.1f}%–{max(share[2:5]):.1f}%", mix)
        self.assertIn(f"{share[-1]:.1f}%", mix)

    def test_year_on_year_wording_compares_like_named_halves(self) -> None:
        """On the H1-only series a neighbouring index IS a year; on the
        half-by-half series it is six months. Anything the page calls a
        year-on-year change must come from two same-named halves."""
        h = self.s["half"]
        i26, i25 = h["periods"].index("2026H1"), h["periods"].index("2025H1")
        self.assertEqual(i26 - i25, 2, "H1 to H1 is two indices on this axis")
        ebit = (h["ebit_eur_k"][i26] / h["ebit_eur_k"][i25] - 1) * 100
        net = (h["net_profit_eur_k"][i26] / h["net_profit_eur_k"][i25] - 1) * 100
        ladder = next(ex for ex in exhibits(self.payload) if ex.get("ref") == "EX_LADDER")
        self.assertAlmostEqual(ladder["values"][2], round(ebit, 1), places=6)
        self.assertAlmostEqual(ladder["values"][3], round(net, 1), places=6)
        # the H1-only blocks are single-frequency, so -1/-2 there really is a year
        for block in ("channel_h1_eur_k", "geography_h1_eur_k", "net_debt_h1_eur_k"):
            years = self.s[block]["years"]
            self.assertEqual(years[-1] - years[-2], 1, block)

    # ── copy boundary ───────────────────────────────────────────────────────
    def test_literal_text_fields_carry_no_markup(self) -> None:
        for note in self.payload["notes"]:
            self.assertNotRegex(note, MARKUP)
        for section in self.payload["sections"]:
            self.assertNotRegex(section["title"], MARKUP)
            self.assertNotRegex(section["description"], MARKUP)
        for table in self.payload["tables"]:
            self.assertNotRegex(table["title"], MARKUP)
        for field in ("title", "subtitle", "headline", "tracker"):
            self.assertNotRegex(self.payload[field], MARKUP)

    def test_the_only_dollars_on_the_page_are_the_shared_cross_page_table(self) -> None:
        """The issuer reports in euro and `charts.js` has no euro formatter, so
        `usd1` is the easy wrong reach. The one legitimate exception is pinned
        rather than excluded silently."""
        shared = next(t for t in self.payload["tables"] if "AI capex" in t["title"])
        rest = json.dumps({k: v for k, v in self.payload.items() if k != "tables"},
                          ensure_ascii=False)
        others = json.dumps([t for t in self.payload["tables"] if t is not shared],
                            ensure_ascii=False)
        self.assertNotIn("$", rest)
        self.assertNotIn("$", others)
        self.assertIn("$", json.dumps(shared, ensure_ascii=False))
        self.assertIn("€", rest)

    def test_the_page_publishes_no_sell_side_packaging(self) -> None:
        surface = json.dumps(self.payload, ensure_ascii=False).lower()
        for term in ("target price", "price target", "consensus", "outperform",
                     "overweight", "underweight", "ev/ebitda", "forward p/e"):
            self.assertNotIn(term, surface)
        for term in ("目标价", "评级", "一致预期"):
            self.assertNotIn(term, json.dumps(self.payload["sections"], ensure_ascii=False))

    def test_the_thresholds_are_declared_as_local_settings(self) -> None:
        joined = " ".join(self.payload["notes"])
        self.assertIn("阈值是本地研究设定", joined)
        self.assertIn("不是公司指引", joined)

    def test_the_page_records_that_it_is_not_an_sec_filer(self) -> None:
        joined = " ".join(self.payload["notes"])
        self.assertIn("12g3-2(b)", joined)
        self.assertNotIn("10-Q", self.payload["subtitle"])

    def test_the_undisclosed_items_are_listed_rather_than_estimated(self) -> None:
        excluded = self.s["next_kpi"]["excluded"]
        self.assertGreaterEqual(len(excluded), 4)
        self.assertTrue(any("like-for-like" in item for item in excluded))
        joined = json.dumps(self.payload, ensure_ascii=False)
        self.assertNotIn("同店销售增长率", joined)

    # ── publication ─────────────────────────────────────────────────────────
    def test_the_page_carries_the_cross_page_capex_table(self) -> None:
        titles = [table["title"] for table in self.payload["tables"]]
        self.assertTrue(any("跨页对照" in title for title in titles))
        joined = " ".join(self.payload["notes"])
        self.assertIn("AI capex", joined)
        self.assertIn("跨页对照", joined)

    def test_exhibits_are_numbered_in_render_order(self) -> None:
        numbers = [ex["n"] for ex in exhibits(self.payload)]
        self.assertEqual(numbers, list(range(2, 2 + len(numbers))))
        first_table = self.payload["tables"][0]["n"]
        self.assertEqual(first_table, numbers[-1] + 1)

    def test_the_registry_row_matches_the_payload(self) -> None:
        from build.all import ENTRIES
        entry = next(e for e in ENTRIES if e["slug"] == "bc")
        self.assertEqual(entry["group"], self.payload["company"]["group"])
        self.assertEqual(entry["ticker"], self.payload["company"]["ticker"])
        self.assertNotIn("本站按自然年季度标注", entry["cadence_label"])

    def test_the_published_payload_matches_a_fresh_build(self) -> None:
        published = (ROOT / "data" / "bc.js").read_text(encoding="utf-8")
        body = published.split(" = ", 1)[1].rstrip().rstrip(";\n")
        self.assertEqual(json.loads(body), self.payload)


if __name__ == "__main__":
    unittest.main()
