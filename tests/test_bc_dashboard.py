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

**A roll edits `series/bc.json` and nothing else** (CLAUDE.md §9). So the
period's own figures are checked against `_checks` (typed from the release,
never read by the builder), the counts are recomputed rather than pinned, every
finding the page states is made false on a copy of the series to prove its words
go with it, and the page is built once more from the series as it stood before
this half -- a full-year page -- without touching the builder.
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

from build import bc  # noqa: E402
from build.board import cn_count, headroom  # noqa: E402

MARKUP = re.compile(r"</?[a-z][a-z0-9]*>", re.I)

FOUR_PARTS = [("settled", "一、上季跟踪指标兑现了吗"), ("quarter_highlights", "二、本季重点"),
              ("next_quarter", "三、下季要跟踪什么"), ("routine", "四、长期常规跟踪")]


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
        rough = set(q.get("narrative_q3_approximate", []))
        self.assertGreaterEqual(len(quoted), 3)
        for period, stated in quoted.items():
            derived = q["revenue_eur_k"][q["periods"].index(period)] / 1000
            # 2024 is quoted only as "about 300"; the others to 0.1, so the
            # tolerance is the printed precision.
            tolerance = 50.0 if period in rough else 0.05
            self.assertLessEqual(abs(derived - stated), tolerance,
                                 f"{period}: derived {derived:.1f} vs quoted {stated}")

    def test_the_year_sum_is_not_treated_as_a_check(self) -> None:
        """Pinned as a tautology so it is never promoted to evidence.

        Q4 is defined as FY - 9M, so this closes by construction for every year
        and would keep closing if every input were wrong together.
        """
        c = self.s["cumulative_revenue_eur_k"]
        q = self.s["quarterly"]
        years = [y for y in c["years"] if all(f"{y}Q{n}" in q["periods"] for n in (1, 2, 3, 4))]
        self.assertGreaterEqual(len(years), 4)
        for year in years:
            total = sum(q["revenue_eur_k"][q["periods"].index(f"{year}Q{n}")] for n in (1, 2, 3, 4))
            self.assertEqual(total, c["fy"][c["years"].index(year)])
        self.assertIn("不构成验证", " ".join(self.payload["notes"]))

    def test_the_half_year_series_marks_which_halves_were_published(self) -> None:
        h = self.s["half"]
        self.assertEqual(len(h["periods"]), len(h["printed"]))
        for period, printed in zip(h["periods"], h["printed"]):
            self.assertEqual(printed, period.endswith("H1"), period)
        # Every H1 is company-printed, every H2 is the year minus the first half;
        # the per-period assertion above already stops an H2 that ever arrives
        # printed from slipping in as though it were derived. The counts the
        # page prints are these two, recounted: the note used to say 18 quarters
        # and 11 halves long after the series reached 26 and 21.
        firsts = sum(1 for period in h["periods"] if period.endswith("H1"))
        self.assertEqual(sum(h["printed"]), firsts)
        note = next(n for n in self.payload["notes"] if n.startswith("披露节奏"))
        self.assertIn(f"{len(h['periods'])} 个半年里只有 {firsts} 个是公司印出的", note)
        q = self.s["quarterly"]
        self.assertIn(f"{len(q['periods'])} 个季度里只有 {q['basis'].count('printed')} 个是公司印出的", note)

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

    def test_the_derived_latest_ebitda_uses_that_definition(self) -> None:
        h = self.s["half"]
        i = max(k for k, period in enumerate(h["periods"]) if period.endswith("H1"))
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

    def test_the_straddle_is_claimed_only_when_the_bases_straddle(self) -> None:
        """The headline claim -- above on one basis, below on the other -- is
        printed from the arithmetic, not remembered."""
        view = bc.period_view(self.s)
        guide = bc.guidance_for(self.s, view["year"])
        straddle = view["cfx"] > guide["high"] and view["reported"] < guide["low"]
        chart = next(ex for ex in exhibits(self.payload) if ex.get("ref") == "EX_STRADDLE")
        self.assertEqual(straddle, "唯一要回答的问题" in chart["note"])
        self.assertEqual(straddle, f"前者高于全年指引上限 {guide['high']:g}%，后者低于下限 {guide['low']:g}%"
                         in self.payload["headline"])

    def test_the_strict_judgeable_count_is_smaller_than_the_met_count(self) -> None:
        st = self.s["annual_revenue_guidance"]["strict_judgeability"]
        self.assertEqual(st["met"], st["completed_quantified_targets"])
        self.assertEqual(st["missed"], 0)
        self.assertLess(st["scoreable_once_an_unstated_basis_is_treated_as_unjudgeable"],
                        st["completed_quantified_targets"])

    # ── the withdrawn disclosure ────────────────────────────────────────────
    def test_the_lease_adjusted_line_stops_where_disclosure_stopped(self) -> None:
        dec = self.s["ifrs16_disclosure_decay"]
        both, bridge = dec["both_bases_printed"], dec["bridge_printed"]
        # once withdrawn, never back: each flag is a run of True then a run of False
        for flags in (both, bridge):
            self.assertEqual(flags, sorted(flags, reverse=True))
        self.assertLessEqual(sum(bridge), sum(both), "the bridge went before the line did")
        self.assertEqual(dec["ebitda_token_count"][-1], 0)
        h = self.s["half"]
        for period, printed in zip(dec["periods"], both):
            value = h["ebitda_ex_ifrs16_eur_k"][h["periods"].index(period.split()[1] + period.split()[0])]
            self.assertEqual(value is not None, printed, period)

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
        # the prose must agree with the count rather than be written by hand
        self.assertIn(f"{cn_count(breached)}条已经越线", chart["note"])
        # and the split between company targets and local lines is counted from
        # the entries: the wholesale line sits at 34%, not at the company's 30%.
        company = [e for e in entries if e["source"] == "company"]
        self.assertIn(f"其中{cn_count(len(company))}条的阈值取自公司自己给出的年度目标", chart["note"])
        for entry in entries:
            if entry["source"] == "company":
                self.assertIn(entry["target_words"], chart["note"])

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

        # EX_MIX: the plateau band -- the years it names sit inside it, the year
        # before them and the latest year do not
        ch = self.s["channel_h1_eur_k"]
        share = [round(r / (r + w) * 100, 1) for r, w in zip(ch["retail"], ch["wholesale"])]
        mix = by_ref["EX_MIX"]["title"]
        self.assertIn(f"{share[-1]:.1f}%", mix)
        match = re.search(r"连续(\S+?)年停在 ([\d.]+)%–([\d.]+)%", mix)
        if match:
            count, low, high = match.group(1), float(match.group(2)), float(match.group(3))
            n = next(k for k in range(2, len(share)) if cn_count(k) == count)
            band = share[-1 - n:-1]
            self.assertEqual((min(band), max(band)), (low, high))
            self.assertLessEqual(high - low, 0.5)
            self.assertFalse(low <= share[-1] <= high)
            self.assertGreater(max(band + [share[-2 - n]]) - min(band + [share[-2 - n]]), 0.5)

    def test_year_on_year_wording_compares_like_named_halves(self) -> None:
        """On the H1-only series a neighbouring index IS a year; on the
        half-by-half series it is six months. Anything the page calls a
        year-on-year change must come from two same-named halves."""
        h = self.s["half"]
        i26 = max(k for k, period in enumerate(h["periods"]) if period.endswith("H1"))
        i25 = h["periods"].index(f"{int(h['periods'][i26][:4]) - 1}H1")
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

    def test_the_record_spread_is_the_widest_and_narrowest_the_page_holds(self) -> None:
        """The note said 0.5pp to 5.9pp; FY2024 is 0.2pp (12.2% against 12.4%) and
        nothing on the page reaches 5.9pp. The range is now read off the record."""
        a, gr = self.s["annual"], self.s["growth_h1_pct"]
        spreads = [abs(r - c) for r, c in zip(a["revenue_yoy_reported_pct"], a["revenue_yoy_cfx_pct"])
                   if r is not None and c is not None]
        spreads += [abs(r - c) for r, c in zip(gr["reported"], gr["cfx"])]
        note = next(n for n in self.payload["notes"] if n.startswith("口径的取舍"))
        self.assertIn(f"介于 {min(spreads):.1f}pp 与 {max(spreads):.1f}pp 之间", note)

    def test_the_constant_currency_years_the_page_names_are_the_ones_it_has(self) -> None:
        """「恒定汇率口径公司自 2022 年起才逐年给出」 outlived the 2016 backfill,
        which brought in FY2017-FY2019 constant-currency growth."""
        a = self.s["annual"]
        conv = next(ex for ex in exhibits(self.payload) if ex.get("ref") == "EX_CONV")
        missing = [y for y, v in zip(a["years"], a["revenue_yoy_cfx_pct"])
                   if v is None and min(y2 for y2, v2 in zip(a["years"], a["revenue_yoy_cfx_pct"]) if v2 is not None) < y]
        for year in missing:
            self.assertIn(str(year), conv["src_extra"])
        self.assertNotIn("起才逐年给出", conv["src_extra"])

    def test_the_undisclosed_items_are_listed_rather_than_estimated(self) -> None:
        excluded = self.s["next_kpi"]["excluded"]
        self.assertGreaterEqual(len(excluded), 4)
        self.assertTrue(any("like-for-like" in item for item in excluded))
        joined = json.dumps(self.payload, ensure_ascii=False)
        self.assertNotIn("同店销售增长率", joined)

    # ── publication ─────────────────────────────────────────────────────────
    def test_the_page_has_the_four_parts_of_the_site_format(self) -> None:
        """The TSM page's four titles, word for word, on a half-year page too:
        this page used to call them 「公司的指引，和它没说的口径」「本期重点」
        「下半年要跟踪什么」, and the structure sentence in the notes named the
        same private order."""
        self.assertEqual([(s["id"], s["title"]) for s in self.payload["sections"]], FOUR_PARTS)
        for section in self.payload["sections"]:
            self.assertTrue(section["exhibits"], section["id"])
        self.assertIn("本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列",
                      " ".join(self.payload["notes"]))

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


class BcChecksTest(unittest.TestCase):
    """The page's half against a record keyed separately from the release.

    `_checks` is typed once per roll from the results release itself, with the
    page and table each figure was read from; the builder never reads it
    (`test_data_only_roll`). Each assertion compares what the builder computed
    from the arrays with that separate reading.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.s = json.loads(bc.STAGING_PATH.read_text(encoding="utf-8"))
        cls.checks = cls.s["_checks"]
        cls.payload = bc.build_payload(cls.s)
        cls.by_ref = {ex["ref"]: ex for ex in exhibits(cls.payload) if "ref" in ex}

    def test_the_page_names_the_checked_half(self) -> None:
        checks = self.checks
        half, year = checks["period"].split()
        self.assertIn(f"{year} 年{'上半年' if half == 'H1' else '全年'}业绩仪表盘", self.payload["title"])
        self.assertIn(f"截至 {checks['period_end']}", self.payload["subtitle"])
        self.assertIn(f"发布 {checks['release_date']}", self.payload["subtitle"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        checks, s = self.checks, self.s
        h = s["half"]
        year = int(checks["period"].split()[1])
        now, prior = h["periods"].index(f"{year}H1"), h["periods"].index(f"{year - 1}H1")
        self.assertEqual(now, len(h["periods"]) - 1)
        self.assertEqual(h["revenue_eur_k"][now], checks["revenue_eur_k"])
        self.assertEqual(h["revenue_eur_k"][prior], checks["revenue_prior_year_eur_k"])
        self.assertEqual(h["ebit_eur_k"][now], checks["ebit_eur_k"])
        self.assertEqual(h["ebit_eur_k"][prior], checks["ebit_prior_year_eur_k"])
        self.assertEqual(h["net_profit_eur_k"][now], checks["net_profit_eur_k"])
        self.assertEqual(h["net_profit_eur_k"][prior], checks["net_profit_prior_year_eur_k"])
        self.assertEqual(h["da_eur_k"][now], checks["depreciation_amortisation_eur_k"])
        # the release prints each rate to one decimal; the recomputation must round to it
        self.assertEqual(round(h["ebit_eur_k"][now] / h["revenue_eur_k"][now] * 100, 1), checks["ebit_margin_pct"])
        self.assertEqual(round(h["ebit_eur_k"][prior] / h["revenue_eur_k"][prior] * 100, 1),
                         checks["ebit_margin_prior_year_pct"])
        self.assertEqual(round(bc.pct(h["ebit_eur_k"][now], h["ebit_eur_k"][prior]), 1), checks["ebit_growth_pct"])
        self.assertEqual(round(bc.pct(h["net_profit_eur_k"][now], h["net_profit_eur_k"][prior]), 1),
                         checks["net_profit_growth_pct"])
        gr = s["growth_h1_pct"]
        self.assertEqual(gr["years"][-1], year)
        self.assertEqual(gr["cfx"][-1], checks["revenue_growth_cfx_pct"])
        self.assertEqual(gr["reported"][-1], checks["revenue_growth_reported_pct"])
        ch, geo = s["channel_h1_eur_k"], s["geography_h1_eur_k"]
        self.assertEqual((ch["retail"][-1], ch["wholesale"][-1]), (checks["retail_eur_k"], checks["wholesale_eur_k"]))
        self.assertEqual((ch["retail"][-2], ch["wholesale"][-2]),
                         (checks["retail_prior_year_eur_k"], checks["wholesale_prior_year_eur_k"]))
        self.assertEqual((geo["europe_total"][-1], geo["americas"][-1], geo["asia"][-1]),
                         (checks["europe_eur_k"], checks["americas_eur_k"], checks["asia_eur_k"]))
        nd = s["net_debt_h1_eur_k"]
        self.assertEqual(round(nd["pre_ifrs16"][-1] / 1000, 1), checks["core_net_financial_debt_eur_m"])
        self.assertEqual(round(nd["pre_ifrs16"][-2] / 1000, 1), checks["core_net_financial_debt_prior_year_eur_m"])
        self.assertEqual(round(s["net_debt_year_end_eur_k"][str(year - 1)] / 1000, 1),
                         checks["core_net_financial_debt_prior_year_end_eur_m"])
        guide = bc.guidance_for(s, checks["guidance_year"])
        self.assertEqual((guide["low"], guide["high"], guide["basis"]),
                         (checks["guidance_cfx_low_pct"], checks["guidance_cfx_high_pct"], "cfx"))

    def test_the_thresholds_carry_the_printed_rates(self) -> None:
        """Where the release prints the rate a threshold tracks, the table uses it."""
        current = {e["metric"]: e["current"] for e in self.s["next_kpi"]["quantified"]}
        self.assertEqual(current["H2 零售渠道 cFX 增速"], self.checks["retail_growth_cfx_pct"])
        self.assertEqual(current["批发渠道占收入比重"], self.checks["wholesale_share_pct"])
        self.assertEqual(current["资本开支占收入比重（指引约 6%）"], self.checks["investments_pct_of_revenue"])
        self.assertEqual(round(current["EBIT 利润率（指引约 17%）"], 1), self.checks["ebit_margin_pct"])
        self.assertEqual(current["报告口径半年营收增速"], self.checks["revenue_growth_reported_pct"])

    def test_the_headline_and_card_print_the_checked_figures(self) -> None:
        checks = self.checks
        head = self.payload["headline"]
        self.assertIn(f"收入 €{checks['revenue_eur_k']:,} 千", head)
        self.assertIn(f"恒定汇率 {checks['revenue_growth_cfx_pct']:+.1f}%", head)
        self.assertIn(f"报告口径 {checks['revenue_growth_reported_pct']:+.1f}%", head)
        self.assertIn(f"EBIT 增 {checks['ebit_growth_pct']:+.1f}%", head)
        self.assertIn(f"{checks['net_profit_growth_pct']:+.1f}%", head)
        card = bc.headline_metrics(self.s)
        self.assertEqual(card, [f"Revenues €{checks['revenue_eur_k'] / 1000:.1f}M",
                                f"恒定汇率 {checks['revenue_growth_cfx_pct']:+.1f}%",
                                f"EBIT 利润率 {checks['ebit_margin_pct']:.1f}%"])


def roll_back_to_full_year(staging: dict) -> dict:
    """The series as it stood on the full-year release before this half.

    Everything this half added comes off: the half, its H1-only rows, the
    quarters of its year, the cumulative figures for its year, the year's
    guidance record. The one-half blocks go too (there is no earlier original
    in git: the page was built on this half), and the release list names the
    full-year release the page would then be built on.
    """
    s = copy.deepcopy(staging)
    year = int(s["half"]["periods"][-1][:4])
    q = s["quarterly"]
    keep = [i for i, period in enumerate(q["periods"]) if int(period[:4]) < year]
    for key in ("periods", "revenue_eur_k", "basis"):
        q[key] = [q[key][i] for i in keep]
    c = s["cumulative_revenue_eur_k"]
    j = c["years"].index(year)
    for key in ("years", "q1", "h1", "nine_m", "fy"):
        del c[key][j]
    h = s["half"]
    for key in [k for k, v in h.items() if isinstance(v, list)]:
        h[key] = h[key][:-1]
    for block in ("geography_h1_eur_k", "channel_h1_eur_k", "growth_h1_pct", "net_debt_h1_eur_k"):
        width = len(s[block]["years"])
        for key, value in s[block].items():
            if isinstance(value, list) and len(value) == width:
                s[block][key] = value[:-1]
    s["net_debt_h1_eur_k"]["post_ifrs16_derived_years"] = []
    dec = s["ifrs16_disclosure_decay"]
    for key in [k for k, v in dec.items() if isinstance(v, list)]:
        dec[key] = dec[key][:-1]
    g = s["annual_revenue_guidance"]
    j = g["target_years"].index(year)
    for key in [k for k, v in g.items() if isinstance(v, list)]:
        del g[key][j]
    for key in ("next_kpi", "half_story", "company_targets", "_checks"):
        s.pop(key, None)
    s["latest"] = {"period": f"H2 {year - 1}", "period_end": f"{year - 1}-12-31",
                   "release_date": f"{year}-02-18", "analysis_date": f"{year}-03-01",
                   "audit_status": "audited"}
    s["sources"] = [src for src in s["sources"] if not src["label"].startswith(f"{year} 年")]
    s["sources"].append({"label": f"{year - 1} 年全年业绩新闻稿（{year}-02-18）",
                         "url": "https://investor.brunellocucinelli.com/en/services/archive/investor/press-releases"})
    return s


class BcRollTest(unittest.TestCase):
    """What a roll can change without touching the builder."""

    STORY_ONLY = ("本期跳升不是零售突然加速", "隐含下半年要压到", "两家券商",
                  "年指引：约", "而公司给的年末目标是收入的")

    @classmethod
    def setUpClass(cls) -> None:
        cls.s = json.loads(bc.STAGING_PATH.read_text(encoding="utf-8"))
        cls.payload = bc.build_payload(cls.s)
        cls.text = json.dumps(cls.payload, ensure_ascii=False)

    def test_a_block_stamped_for_another_half_stops_the_build(self) -> None:
        for key in ("next_kpi", "half_story"):
            stale = copy.deepcopy(self.s)
            stale[key]["period"] = "H1 1999"
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    bc.build_payload(stale)

    def test_the_halfs_own_release_must_be_in_the_sources(self) -> None:
        bare = copy.deepcopy(self.s)
        bare["sources"] = [src for src in bare["sources"] if "上半年业绩" not in src["label"]]
        self.assertLess(len(bare["sources"]), len(self.s["sources"]))
        with self.assertRaisesRegex(ValueError, "sources"):
            bc.build_payload(bare)

    def test_targets_are_published_only_in_their_own_year(self) -> None:
        other = copy.deepcopy(self.s)
        other["company_targets"]["year"] -= 1
        text = json.dumps(bc.build_payload(other), ensure_ascii=False)
        self.assertIn("而公司给的年末目标是收入的", self.text)
        self.assertNotIn("而公司给的年末目标是收入的", text)
        self.assertNotIn("年指引：约", text)

    def test_a_half_without_its_story_leaves_it_out(self) -> None:
        bare = copy.deepcopy(self.s)
        for key in ("next_kpi", "half_story", "company_targets"):
            del bare[key]
        payload = bc.build_payload(bare)
        text = json.dumps(payload, ensure_ascii=False)
        for phrase in self.STORY_ONLY:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)
                self.assertNotIn(phrase, text)
        for index, section in enumerate(payload["sections"], start=1):
            self.assertTrue(section["title"].startswith(f"{bc.cn_ordinal(index)}、"))
        first = payload["tables"][0]["n"]
        self.assertEqual([t["n"] for t in payload["tables"]], list(range(first, first + len(payload["tables"]))))

    def test_the_full_year_before_this_half_builds_from_the_series_alone(self) -> None:
        rolled = roll_back_to_full_year(self.s)
        payload = bc.build_payload(rolled)
        year = int(self.s["half"]["periods"][-1][:4]) - 1
        self.assertIn(f"{year} 年全年业绩仪表盘", payload["title"])
        self.assertEqual(payload["latest"]["disclosed_period_label"], f"H2 {year}")
        self.assertTrue(payload["headline"].startswith("全年收入"))
        # a full-year page keeps the same four titles; none of them names a half
        self.assertEqual([(s["id"], s["title"]) for s in payload["sections"]], FOUR_PARTS)
        text = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn(f"{year + 1} 年上半年", text)

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        """Make each finding false on a copy of the series: its words must go."""
        cases = []
        s = copy.deepcopy(self.s)
        s["channel_h1_eur_k"]["wholesale"][-1] = round(s["channel_h1_eur_k"]["wholesale"][-2] * 1.05)
        cases += [(s, "批发在连续增长四年之后停住"), (s, "批发停住，增长只剩一条腿")]
        s = copy.deepcopy(self.s)
        s["channel_h1_eur_k"]["wholesale"][2] = s["channel_h1_eur_k"]["wholesale"][1] - 1
        cases.append((s, "在此之前它连续四年每年都增长"))
        s = copy.deepcopy(self.s)
        s["channel_h1_eur_k"]["retail"][-3] = round(s["channel_h1_eur_k"]["retail"][-3] * 0.9)
        cases.append((s, "零售占比连续三年停在"))
        s = copy.deepcopy(self.s)
        s["growth_h1_pct"]["cfx"][-1] = 10.5
        cases += [(s, "唯一要回答的问题"), (s, "前者高于全年指引上限")]
        s = copy.deepcopy(self.s)
        g = s["annual_revenue_guidance"]
        g["actual_reported_pct"][g["target_years"].index(2025)] = 9.0
        cases.append((s, "两条实际线都稳稳高于指引"))
        s = copy.deepcopy(self.s)
        s["half"]["net_profit_eur_k"][-1] = round(s["half"]["net_profit_eur_k"][-3] * 1.2)
        cases += [(s, "真正的断层在 EBIT 之下"), (s, "断层在 EBIT 以下，不在收入")]
        s = copy.deepcopy(self.s)
        s["annual_revenue_guidance"]["strict_judgeability"]["met"] -= 1
        cases += [(s, "全部达成"), (s, "条条达成")]
        s = copy.deepcopy(self.s)
        s["guidance_basis_census"]["lease_basis_stated"] = 1
        cases.append((s, "一次都没有</b>被说明过"))
        for staging, phrase in cases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)
                self.assertNotIn(phrase, json.dumps(bc.build_payload(staging), ensure_ascii=False))
        # The debt chart's own sentence (the thresholds' story says it too, in
        # words written for this half, so the chart is where the arithmetic is).
        s = copy.deepcopy(self.s)
        s["net_debt_year_end_eur_k"][str(int(s["half"]["periods"][-1][:4]) - 1)] = 999999
        debt = next(ex for ex in exhibits(bc.build_payload(s)) if ex.get("ref") == "EX_DEBT")
        self.assertIn("同时高于上年末", next(ex for ex in exhibits(self.payload) if ex.get("ref") == "EX_DEBT")["note"])
        self.assertNotIn("同时高于上年末", debt["note"])


if __name__ == "__main__":
    unittest.main()
