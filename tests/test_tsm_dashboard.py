from __future__ import annotations

import copy
import json
import math
import re
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.all import build_all, roster_payload  # noqa: E402
from build.board import headroom  # noqa: E402
from build.tsm import build_payload, compact_period, iso_period, shift_period  # noqa: E402


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


class TsmDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "tsm.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]
        cls.by_section = {
            section["id"]: section["exhibits"] for section in cls.payload["sections"]
        }

    def test_all_historical_series_have_one_value_per_period(self) -> None:
        """The reviewed window used to be pinned at eight here; a roll appends a
        quarter, so what has to hold is an unbroken axis and one cell per
        quarter in every aligned block."""
        periods = self.source["periods"]
        for before, after in zip(periods, periods[1:]):
            self.assertEqual(shift_period(before, 1), after)
        for section in [
            "financials",
            "technology_mix_pct",
            "platform_mix_pct",
            "cash_flow_ntd_bn",
            "working_capital_days",
            "revenue_guidance_history_usd_bn",
        ]:
            for name, values in self.source[section].items():
                self.assertEqual(len(values), len(periods), f"{section}.{name}")
                # None is allowed and meaningful: a node with no row in the
                # company's table is not the same fact as a reported 0%.
                self.assertTrue(
                    all(value is None or math.isfinite(value) for value in values),
                    f"{section}.{name}",
                )
                self.assertIsNotNone(values[-1], f"{section}.{name} has no current value")

    def test_key_source_values_and_formulas(self) -> None:
        """The quarter's own figures are checked against `_checks` in
        TsmChecksTest; what is asserted here are the identities between blocks."""
        financials = self.source["financials"]
        snapshot = self.source["current_snapshot"]
        self.assertEqual(snapshot["revenue_usd_bn"][0], financials["revenue_usd_bn"][-1])
        self.assertEqual(snapshot["gross_margin_pct"][0], financials["gross_margin_pct"][-1])
        self.assertEqual(snapshot["operating_margin_pct"][0], financials["operating_margin_pct"][-1])
        self.assertEqual(snapshot["hpc_mix_pct"][0], self.source["platform_mix_pct"]["hpc"][-1])

        cash = self.source["cash_flow_ntd_bn"]
        for operating, capex, free_cash in zip(
            cash["operating_cash_flow"], cash["capital_expenditures"], cash["free_cash_flow"]
        ):
            self.assertAlmostEqual(round(operating - capex, 2), free_cash, places=2)

        bridge = self.source["net_income_bridge"]["values_ntd_bn"]
        self.assertAlmostEqual(bridge[0] - bridge[1], bridge[2], places=2)
        self.assertEqual(bridge[0], snapshot["net_income_ntd_bn"][0])
        self.assertEqual(bridge[3], self.source["market_expectation"]["net_income_ntd_bn"])

    def test_guidance_history_is_not_overstated(self) -> None:
        """The revenue band's own tally is the tally of the cells it draws.

        This used to pin the reviewed window's count (six quarters at or above
        the top of the range) -- true of those eight quarters and of no roll.
        What cannot change with a roll is that the title counts the cells the
        chart plots, at the precision the company prints (on the bound is in)."""
        band = next(ex for ex in self.by_section["settled"]
                    if ex["kind"] == "range_band" and ex["title"].startswith("收入"))
        done = [(lo, hi, a) for lo, hi, a in zip(band["lo"], band["hi"], band["actual"]) if a is not None]
        above = sum(1 for lo, hi, a in done if a > hi)
        below = sum(1 for lo, hi, a in done if a < lo)
        self.assertIn(f"{len(done)} 个已完结季里 {above} 季超出上限、{len(done) - above - below} 季落在区间内",
                      band["title"])
        history = self.source["revenue_guidance_history_usd_bn"]
        self.assertEqual(sum(1 for hi, a in zip(history["high"], history["actual"]) if a > hi),
                         sum(1 for lo, hi, a in done[-len(history["actual"]):] if a > hi))

    def test_page_is_chart_led(self) -> None:
        self.assertEqual(self.payload["summary"]["blocks"], [])
        self.assertIsNone(self.payload["guidance"])
        self.assertEqual(
            [ex["n"] for ex in self.exhibits], list(range(2, 2 + len(self.exhibits)))
        )
        for exhibit in self.exhibits:
            self.assertTrue(exhibit.get("kind"), exhibit["n"])
            self.assertTrue(exhibit.get("note"), f"exhibit {exhibit['n']} has no explanation")

    def test_section_order_matches_how_the_note_is_used(self) -> None:
        """Four sections in reading order. How many charts each carries depends
        on which one-quarter blocks the quarter has: the follow-up closure, this
        quarter against its guide, the market expectation, a falsified call with
        a long series, the capex outlook and a one-off in net income each bring
        their chart, and a quarter without one leaves it out."""
        source = self.source
        falsified = (source.get("followup_closure") or {}).get("falsified") or {}
        tracked = {"毛利率", "库存天数", "HPC 占比（集中度）", "2nm 占晶圆收入", "单季 CapEx"}
        expected = [
            ("settled", ("followup_closure" in source) + ("guidance_delivery" in source)
             + ("market_expectation" in source) + 7 + (falsified.get("metric") == "库存天数")),
            ("quarter_highlights", 3 + ("capex_guidance_history" in source)
             + ("net_income_bridge" in source and "market_expectation" in source) + 2),
            ("next_quarter", 1 + len(tracked & {e["metric"] for e in source["next_kpi"]["quantified"]})),
            ("routine", 4),
        ]
        self.assertEqual(
            [(section["id"], len(section["exhibits"])) for section in self.payload["sections"]],
            expected,
        )

    def test_the_page_carries_no_monthly_series(self) -> None:
        """The guidance charts were ported from a monthly-cadence dashboard.
        Everything they plot has to come from quarterly disclosure, or this page
        goes stale between earnings on a schedule its own subtitle denies."""
        text = json.dumps(self.source, ensure_ascii=False)
        for banned in ("monthly_revenue", "monthly_fx", "EXTAUS", "fred."):
            self.assertNotIn(banned, text)
        for exhibit in self.exhibits:
            self.assertNotIn("qtd", exhibit, f"exhibit {exhibit['n']}")
            self.assertNotEqual(exhibit["kind"], "year_lines", f"exhibit {exhibit['n']}")

    def test_the_two_guidance_blocks_never_disagree(self) -> None:
        """Both blocks are plotted in the settled section, side by side, over
        different windows; overlapping cells must be the same cells."""
        history = self.source["revenue_guidance_history_usd_bn"]
        guide = self.source["quarterly_guidance_history"]
        compact = [compact_period(period) for period in self.source["periods"]]
        self.assertEqual(compact[-1], compact_period(self.source["latest"]["period"]))
        overlap = guide["quarters"].index(iso_period(self.source["periods"][0]))
        window = slice(overlap, overlap + len(self.source["periods"]))
        self.assertEqual(guide["guide_low_usd_bn"][window], history["low"])
        self.assertEqual(guide["guide_high_usd_bn"][window], history["high"])
        self.assertEqual(guide["actual_revenue_usd_bn"][window], history["actual"])
        self.assertIsNone(guide["actual_revenue_usd_bn"][-1])
        self.assertIsNone(guide["actual_fx_ntd_per_usd"][-1])
        for name in ("guide_low_usd_bn", "guide_high_usd_bn", "guide_fx_ntd_per_usd",
                     "actual_revenue_usd_bn", "actual_fx_ntd_per_usd"):
            self.assertEqual(len(guide[name]), len(guide["quarters"]), name)

    def test_margin_guidance_reconciles_with_the_reported_margins(self) -> None:
        """Gross and operating margin are pulled from the same 6-K income
        statements the rest of the page uses, so the overlapping eight quarters
        must agree to the tenth of a point they are published at. A silent
        mismatch here would mean the range bands are plotting a different
        company than the margin trend chart in section two."""
        guide = self.source["quarterly_guidance_history"]
        overlap = guide["quarters"].index(iso_period(self.source["periods"][0]))
        window = slice(overlap, overlap + len(self.source["periods"]))
        for name, published in (
            ("gross_margin_actual_pct", "gross_margin_pct"),
            ("operating_margin_actual_pct", "operating_margin_pct"),
        ):
            for computed, reported in zip(guide[name][window], self.source["financials"][published]):
                self.assertAlmostEqual(computed, reported, delta=0.05, msg=name)
        # NT$ revenue from the same filings has to reproduce the snapshot too.
        by_quarter = dict(zip(guide["quarters"], guide["actual_revenue_ntd_bn"]))
        latest = self.source["periods"][-1]
        columns = [iso_period(shift_period(latest, step)) for step in (0, -1, -4)]
        for quarter, snapshot in zip(columns, self.source["current_snapshot"]["revenue_ntd_bn"]):
            self.assertAlmostEqual(by_quarter[quarter], snapshot, places=1, msg=quarter)
        for name in ("gross_margin_guide_low_pct", "gross_margin_guide_high_pct",
                     "gross_margin_actual_pct", "operating_margin_guide_low_pct",
                     "operating_margin_guide_high_pct", "operating_margin_actual_pct",
                     "actual_revenue_ntd_bn"):
            self.assertEqual(len(guide[name]), len(guide["quarters"]), name)
            self.assertIsNone(guide[name][-1] if name.endswith(("actual_pct", "ntd_bn")) else None)

    def test_every_guided_metric_gets_its_own_band(self) -> None:
        """Three guided metrics, three bands, each on its own axis -- percent and
        percentage points must never share one. And each band's plotted actual
        has to be the source array, not a re-derivation."""
        guide = self.source["quarterly_guidance_history"]
        bands = {
            ex["title"].split("：")[0]: ex
            for ex in self.by_section["settled"] if ex["kind"] == "range_band"
        }
        # The revenue band names its shorter window in its own title, so the
        # metric key is taken from the part before that parenthesis.
        bands = {name.split("（")[0]: ex for name, ex in bands.items()}
        self.assertEqual(set(bands), {"收入", "毛利率", "营业利润率"})
        for metric, keys in (
            ("收入", ("guide_low_usd_bn", "guide_high_usd_bn", "actual_revenue_usd_bn")),
            ("毛利率", ("gross_margin_guide_low_pct", "gross_margin_guide_high_pct",
                     "gross_margin_actual_pct")),
            ("营业利润率", ("operating_margin_guide_low_pct", "operating_margin_guide_high_pct",
                       "operating_margin_actual_pct")),
        ):
            band = bands[metric]
            # The dollar band is drawn over a shorter window on purpose (the
            # guided number runs 6.1 to 45.8, so early bands collapse on a
            # linear axis); the two percentage bands carry the whole record.
            width = len(band["xlabels"])
            self.assertEqual(band["lo"], guide[keys[0]][-width:], metric)
            self.assertEqual(band["hi"], guide[keys[1]][-width:], metric)
            self.assertEqual(band["actual"], guide[keys[2]][-width:], metric)
            self.assertEqual(band["xlabels"], guide["quarters"][-width:], metric)
            for low, high in zip(band["lo"], band["hi"]):
                self.assertLess(low, high, metric)
        self.assertEqual(bands["收入"]["fmt"], "usd1")
        self.assertEqual(bands["毛利率"]["fmt"], "pct1")
        # Operating margin cleared the upper bound in almost every quarter from
        # 2023 on -- and that is exactly why the record has to run longer than
        # that stretch. Over the whole record it lands inside the range and
        # below it too, so "the guidance is a floor" is a property of the
        # 2023-onward window, not of the company.
        quarters = guide["quarters"]
        operating = guide["operating_margin_actual_pct"]
        lows = guide["operating_margin_guide_low_pct"]
        highs = guide["operating_margin_guide_high_pct"]
        finished = [(q, a, lo, hi) for q, a, lo, hi in zip(quarters, operating, lows, highs)
                    if a is not None]
        self.assertEqual(len(finished), len(quarters) - 1, "only the guided next quarter is open")
        # The short-window reading this page used to publish was "all fourteen
        # cleared the upper bound". Two of those fourteen landed *exactly on*
        # the bound at the precision the company publishes (2024Q1 42.0 against
        # 40.0-42.0, 2025Q1 48.5 against 46.5-48.5); the old page called them
        # exceedances because it compared a two-decimal derived margin against a
        # one-decimal band. So the old claim was part window, part rounding --
        # and the note kept saying "每一季" for two more versions after the
        # title was fixed. The note's counts are now the data's.
        regime = [(q, a, lo, hi) for q, a, lo, hi in finished if q >= "2023Q1"]
        regime_above = sum(1 for _, a, _, hi in regime if a > hi)
        at_the_bound = [q for q, a, _, hi in regime if a == hi]
        self.assertLessEqual({"2024Q1", "2025Q1"}, set(at_the_bound))
        self.assertIn("两位小数", self.source["quarterly_guidance_history"]["precision_note"])
        note = bands["营业利润率"]["note"]
        self.assertIn(f"按 2023 年起的那 {len(regime)} 季读", note)
        self.assertIn(f"{regime_above} 季从上限穿出去、其余 {len(at_the_bound)} 季恰好落在上限上", note)
        self.assertNotIn("每一季都从上限穿出去", note)
        above = sum(1 for _, a, _, hi in finished if a > hi)
        below = sum(1 for _, a, lo, _ in finished if a < lo)
        inside = len(finished) - above - below
        self.assertIn(f"{len(finished)} 个已完结季里 {above} 季超出上限、{inside} 季落在区间内、"
                      f"{below} 季跌破下限", bands["营业利润率"]["title"])
        self.assertIn(f"落在区间内的季度有 {inside} 个，跌破下限的有 {below} 个", note)
        self.assertNotIn("全部超出指引上限", bands["营业利润率"]["title"])
        # And the reader has to be told the short reading was the artefact.
        self.assertIn("14 季", note)

    def test_expectation_chart_separates_headline_from_core(self) -> None:
        """The chart's whole claim is that the answer to "did it beat" flips
        depending on the profit line, so both must be plotted from the same
        consensus figure and the core one must be the smaller."""
        chart = next(
            ex for ex in self.by_section["settled"] if "对市场预期" in ex["title"]
        )
        values = dict(zip(chart["xlabels"], chart["values"]))
        self.assertEqual(chart["kind"], "diverging_bars")
        self.assertGreater(values["报告 EPS"], values["核心 EPS D"])
        self.assertGreater(values["报告净利"], values["核心净利 D"])
        bridge = self.source["net_income_bridge"]["values_ntd_bn"]
        consensus = self.source["market_expectation"]
        self.assertAlmostEqual(
            values["核心净利 D"], (bridge[2] / consensus["net_income_ntd_bn"] - 1) * 100, places=2
        )
        self.assertAlmostEqual(
            values["营收（NT$）"],
            (self.source["current_snapshot"]["revenue_ntd_bn"][0]
             / consensus["revenue_ntd_bn"] - 1) * 100,
            places=2,
        )
        clean = all(values[label] > 0 for label in ("营收（US$）", "营收（NT$）", "毛利率（pp）"))
        self.assertEqual("干净的超预期在营收与毛利率" in chart["note"],
                         clean and abs(values["核心净利 D"]) < 5)

    def test_beat_decomposition_multiplies_back_to_the_reported_beat(self) -> None:
        """The two-leg chart claims the split is exact, not an approximation.
        It is exact only because guidance is set at a stated assumption rate and
        the result is reported at the realised one, so the two legs compound. If
        that ever stops holding, the chart is silently pushing a residual into
        one of the legs."""
        settled = self.by_section["settled"]
        legs = next(ex for ex in settled if "两条腿" in ex["title"])
        midpoint_bars = next(
            ex for ex in settled if ex["kind"] == "grouped_bars" and len(ex["groups"]) == 1
        )
        operating, currency = (group["values"] for group in legs["groups"])
        dollar = midpoint_bars["groups"][0]["values"]
        self.assertEqual(legs["xlabels"], midpoint_bars["xlabels"])
        self.assertEqual(len(operating), len(dollar))
        for label, one, two, total in zip(legs["xlabels"], operating, currency, dollar):
            compounded = ((1 + one / 100) * (1 + two / 100) - 1) * 100
            self.assertAlmostEqual(compounded, total, delta=0.01, msg=label)
            # Adding the legs instead of compounding them is wrong, and on this
            # data it is visibly wrong, so nobody can "simplify" it back.
        worst = max(
            abs(one + two - total) for one, two, total in zip(operating, currency, dollar)
        )
        self.assertGreater(worst, 0.1)
        self.assertFalse(legs["bar_labels"])

    def test_exhibit_cross_references_are_resolved_to_real_numbers(self) -> None:
        """Captions point at other exhibits by number, and the numbers are
        assigned at render time; an unresolved placeholder would ship as
        literal '{EX_PACE}' text on the published page."""
        text = json.dumps(self.payload, ensure_ascii=False)
        self.assertNotIn("{EX_", text)
        numbers = {ex["n"] for ex in self.exhibits}
        settled = self.by_section["settled"]
        legs = next(ex for ex in settled if "两条腿" in ex["title"])
        deviations = [
            ex for ex in settled
            if ex["kind"] == "grouped_bars" and len(ex["groups"]) == 1
            and "相对指引中值的偏离" in ex["title"]
        ]
        revenue_deviation = next(ex for ex in deviations if ex["title"].startswith("收入"))
        # The decomposition splits the REVENUE deviation bar specifically, and it
        # no longer sits next to it, so the caption must name that exhibit by
        # number rather than say "上一图".
        self.assertIn(f"Exhibit {revenue_deviation['n']}", legs["note"])
        self.assertIn(f"Exhibit {legs['n']}", revenue_deviation["note"])
        self.assertNotIn("上一图", legs["note"])
        # Grouped by metric: each guided metric's band is followed immediately by
        # its own deviation chart, and revenue's FX decomposition rides with
        # revenue. Cross-metric comparison is carried by the captions, which name
        # the other exhibits by number. And no eight-quarter revenue band
        # survives beside the long one.
        bands = [ex for ex in settled if ex["kind"] == "range_band"]
        record = len(self.source["quarterly_guidance_history"]["quarters"])
        self.assertEqual([len(ex["xlabels"]) for ex in bands], [16, record, record])
        metrics = ["收入", "毛利率", "营业利润率"]
        self.assertEqual([ex["title"].split("：")[0].split("（")[0] for ex in bands], metrics)
        self.assertEqual([ex["title"].split("相对")[0] for ex in deviations], metrics)
        expected = [
            bands[0]["n"], deviations[0]["n"], legs["n"],
            bands[1]["n"], deviations[1]["n"],
            bands[2]["n"], deviations[2]["n"],
        ]
        lead = [ex["n"] for ex in settled].index(bands[0]["n"])
        self.assertEqual(expected, [ex["n"] for ex in settled][lead:lead + 7])
        self.assertEqual(expected, sorted(expected), "the block must stay in reading order")
        for note in self.payload["notes"]:
            for token in re.findall(r"Exhibit (\d+)", note):
                self.assertIn(int(token), numbers, note)
        # The note that names "the three guidance charts" names the three bands.
        # It used to read Exhibit 5/6/7 -- written when the three bands sat side
        # by side, and left pointing at the revenue band, its deviation chart and
        # the FX legs after the charts were regrouped by metric.
        three = next(note for note in self.payload["notes"] if note.startswith("第一节的指引兑现三张图"))
        self.assertIn("／".join(str(ex["n"]) for ex in bands), three)

    def test_midpoint_deviation_charts_reproduce_the_guided_midpoints(self) -> None:
        """One chart per guided metric, each recomputable from the 6-K columns.

        Revenue is guided as a level so its distance is relative (%); the two
        margins are already ratios so theirs is the arithmetic gap (pp). Mixing
        those two up is the mistake this test exists to catch -- it would print
        a plausible-looking number that no filing contains.
        """
        guide = self.source["quarterly_guidance_history"]
        settled = self.by_section["settled"]
        cases = [
            ("收入", "actual_revenue_usd_bn", "guide_low_usd_bn", "guide_high_usd_bn", "pct"),
            ("毛利率", "gross_margin_actual_pct",
             "gross_margin_guide_low_pct", "gross_margin_guide_high_pct", "pp"),
            ("营业利润率", "operating_margin_actual_pct",
             "operating_margin_guide_low_pct", "operating_margin_guide_high_pct", "pp"),
        ]
        for metric, actual_key, low_key, high_key, mode in cases:
            with self.subTest(metric=metric):
                exhibit = next(
                    ex for ex in settled
                    if ex["title"].startswith(f"{metric}相对指引中值的偏离")
                )
                self.assertEqual(exhibit["fmt"], "pct1" if mode == "pct" else "pp1")
                self.assertEqual(exhibit["ylab"], ("%" if mode == "pct" else "pp") + " vs 指引中值")
                finished = [
                    index for index, value in enumerate(guide[actual_key]) if value is not None
                ]
                expected = []
                for index in finished:
                    mid = (guide[low_key][index] + guide[high_key][index]) / 2
                    actual = guide[actual_key][index]
                    expected.append(actual / mid * 100 - 100 if mode == "pct" else actual - mid)
                plotted = exhibit["groups"][0]["values"]
                self.assertEqual(len(plotted), len(expected))
                for got, want in zip(plotted, expected):
                    self.assertAlmostEqual(got, want, places=6)
                # The headline count has to be the plotted data, not prose.
                above = sum(1 for value in expected if value > 0)
                self.assertIn(f"{len(expected)} 季里 {above} 季为正", exhibit["title"])

    def test_latest_quarter_deviations_match_the_delivery_chart(self) -> None:
        """The newest bar of each deviation chart is the same number the Q2
        delivery chart already prints, so the two cannot drift apart."""
        delivery = {
            entry["metric"]: (entry["value"], entry["unit"])
            for entry in self.source["guidance_delivery"]["items"]
        }
        settled = self.by_section["settled"]
        pairs = [
            ("收入", "收入 vs 指引中值"),
            ("毛利率", "毛利率 vs 指引中值"),
            ("营业利润率", "营业利润率 vs 指引中值"),
        ]
        for metric, delivery_key in pairs:
            with self.subTest(metric=metric):
                exhibit = next(
                    ex for ex in settled
                    if ex["title"].startswith(f"{metric}相对指引中值的偏离")
                )
                value, _unit = delivery[delivery_key]
                self.assertAlmostEqual(exhibit["groups"][0]["values"][-1], value, places=1)

    def test_implied_asp_reproduces_reported_revenue(self) -> None:
        """Implied ASP is the only plotted series that is not a reported level,
        so it has to invert back to reported revenue exactly."""
        long = self.source["long_history"]["financials"]
        exhibit = next(ex for ex in self.exhibits if "隐含 ASP" in ex["title"])
        asp = exhibit["yoy"]["values"]
        self.assertEqual(len(asp), len(self.source["long_history"]["quarters"]),
                         "the ratio now runs on the ten-year record")
        for index, value in enumerate(asp):
            shipments = long["wafer_shipments_kpcs_12in_equiv"][index]
            revenue = long["revenue_usd_bn"][index]
            self.assertAlmostEqual(value * shipments / 1_000_000, revenue, places=5)
        self.assertEqual(exhibit["values"], long["wafer_shipments_kpcs_12in_equiv"])
        # The reviewed quarters are the tail of it, unchanged.
        self.assertEqual(long["wafer_shipments_kpcs_12in_equiv"][-len(self.source["periods"]):],
                         self.source["financials"]["wafer_shipments_kpcs_12in_equiv"])

    def test_headroom_bars_reproduce_the_thresholds(self) -> None:
        entries = self.source["next_kpi"]["quantified"]
        exhibit = self.by_section["next_quarter"][0]
        self.assertEqual(exhibit["kind"], "diverging_bars")
        self.assertEqual(exhibit["xlabels"], [entry["metric"] for entry in entries])
        for entry, plotted in zip(entries, exhibit["values"]):
            expected = headroom(entry["direction"], entry["threshold"], entry["current"])
            self.assertAlmostEqual(plotted, round(expected, 1), places=6, msg=entry["metric"])
        breached = [
            label for label, value in zip(exhibit["xlabels"], exhibit["values"]) if value < 0
        ]
        # Which lines are breached is the quarter's data, not this file's: the
        # title may call one line "唯一" only while it is the only one.
        self.assertEqual("唯一" in exhibit["title"], len(breached) == 1)
        if len(breached) == 1:
            entry = next(e for e in entries if e["metric"] == breached[0])
            self.assertIn(entry.get("short", entry["metric"]), exhibit["title"])

    def test_every_tracked_metric_with_a_series_gets_its_own_chart(self) -> None:
        charted = {
            exhibit["title"].split("：")[0] for exhibit in self.by_section["next_quarter"][1:]
        }
        tracked = {entry["metric"] for entry in self.source["next_kpi"]["quantified"]}
        # Every tracked line the page holds a quarterly series for gets its own
        # chart; the spot FX rate has no published quarterly series to plot.
        with_series = {"毛利率", "库存天数", "HPC 占比（集中度）", "2nm 占晶圆收入", "单季 CapEx"}
        self.assertEqual(charted, tracked & with_series)
        for exhibit in self.by_section["next_quarter"][1:]:
            line = exhibit["series"][1]["values"]
            self.assertEqual(len(set(line)), 1, exhibit["title"])
            self.assertEqual(len(line), len(exhibit["series"][0]["values"]), exhibit["title"])

    def test_dollar_capex_backs_the_intensity_and_growth_charts(self) -> None:
        """CapEx is reported in NT$ but the intensity ratio and the growth
        crossover both need US$ on each side, so the dollar series has to carry
        four extra quarters and reconcile with the NT$ one."""
        block = self.source["capital_expenditures_usd_bn"]
        reviewed = len(self.source["periods"])
        self.assertEqual(len(block["values"]), reviewed + 4)
        self.assertEqual(len(block["periods"]), reviewed + 4)
        self.assertEqual(block["periods"][-reviewed:], self.source["periods"])
        ntd = self.source["cash_flow_ntd_bn"]["capital_expenditures"]
        for usd, nt in zip(block["values"][-reviewed:], ntd):
            self.assertTrue(28.0 < nt / usd < 34.0, f"implied FX {nt / usd:.1f}")
        # The intensity chart now runs on the ten-year record, and the twelve
        # quarters above are a slice of the SAME filings — so the overlap has to
        # agree exactly. Two CapEx sources on one page is the defect this pins.
        long = self.source["long_history"]
        intensity = next(
            ex for ex in self.exhibits if ex["title"].startswith("资本强度十年")
        )
        self.assertEqual(len(intensity["values"]), len(long["quarters"]))
        for index, value in enumerate(intensity["values"]):
            expected = (
                long["capital_intensity"]["capex_usd_bn"][index]
                / long["capital_intensity"]["revenue_usd_bn"][index] * 100
            )
            self.assertAlmostEqual(value, expected, places=6)
        for period, value in zip(block["periods"], block["values"]):
            quarter = "".join(reversed(period.split()))
            self.assertEqual(
                value,
                long["capital_intensity"]["capex_usd_bn"][long["quarters"].index(quarter)],
                f"{period}: the eight-quarter CapEx block disagrees with long_history",
            )
        for index, revenue in enumerate(self.source["financials"]["revenue_usd_bn"]):
            self.assertEqual(revenue, long["capital_intensity"]["revenue_usd_bn"][-reviewed:][index])
        crossover = next(ex for ex in self.exhibits if ex["title"].startswith("CapEx 增速"))
        revenue_yoy, capex_yoy = (series["values"] for series in crossover["series"])
        record = len(long["quarters"])
        self.assertEqual((len(revenue_yoy), len(capex_yoy)), (record, record))
        # 2015 is not in this record, so the first four cells have no
        # denominator. They are None rather than zero -- a zero would draw a
        # fabricated point at the left edge of both lines.
        self.assertEqual(revenue_yoy[:4], [None] * 4)
        self.assertEqual(capex_yoy[:4], [None] * 4)
        self.assertTrue(all(v is not None for v in revenue_yoy[4:]))
        self.assertTrue(all(v is not None for v in capex_yoy[4:]))
        for index in range(4, record):
            for plotted, source in ((revenue_yoy, long["capital_intensity"]["revenue_usd_bn"]),
                                    (capex_yoy, long["capital_intensity"]["capex_usd_bn"])):
                self.assertAlmostEqual(
                    plotted[index], (source[index] / source[index - 4] - 1) * 100, places=5)
        # The tail still reproduces the eight-quarter y/y the page used to plot,
        # to within the precision the company publishes it at. The two are not
        # the same object: `financials.revenue_yoy_pct` is the one-decimal
        # figure TSMC prints, the plotted line is computed from the dollar
        # revenues so it exists for all 38 quarters that have a denominator.
        # Agreement to 0.15pp is what makes the swap safe; equality would be
        # asserting that a derived series is a disclosed one. The tolerance is
        # not arbitrary: the dollar revenues are published to two decimals, so
        # a ratio of two of them carries about a tenth of a point of rounding
        # at these magnitudes (2025Q3 is the widest, 40.851 against a printed
        # 40.8). It is still tight enough to catch a series shifted by a
        # quarter, which is the error this assertion exists for.
        for plotted, disclosed in zip(revenue_yoy[-reviewed:],
                                      self.source["financials"]["revenue_yoy_pct"]):
            self.assertAlmostEqual(plotted, disclosed, delta=0.15)
        self.assertIn(" D", crossover["series"][0]["name"] + crossover["src_extra"])

    # Every exhibit whose x axis is time, and the reason it is allowed to be
    # shorter than the ten-year record. A chart that gets shortened without an
    # entry here turns this red -- which is the point: the previous version of
    # this page carried eleven eight-quarter charts and nothing anywhere said
    # eight was a choice rather than the length of the data.
    SHORT_BY_DESIGN = {
        "收入（本图仅近": "dollar band -- the guided number runs 6.1 to 45.8, so the "
                     "early bands collapse on a linear axis; the deviation "
                     "chart beside it carries all 42",
        "HPC 占比（集中度）": "TSMC first reported the platform split in 2018Q1",
        "HPC 从": "same disclosure limit as the threshold chart",
        "2nm 占晶圆收入": "2nm was inside 'advanced' until 2025Q2",
    }

    def test_every_time_axis_chart_reaches_2016(self) -> None:
        """The window is a decision, so it has to be visible in the payload.

        This is the assertion the whole ten-year rebuild exists for. Anything
        with a quarterly x axis runs from 2016Q1 unless it is named above with
        the disclosure that stops it -- and the names are checked too, so an
        entry cannot be added to silence a chart that was merely left short.
        """
        quarterly = re.compile(r"^(Q[1-4]'\d{2}|\d{4}Q[1-4]|[A-Z][a-z]{2}-\d{2})$")
        record = len(self.source["long_history"]["quarters"])
        checked = 0
        for exhibit in self.exhibits:
            labels = exhibit.get("xlabels") or []
            timed = [x for x in labels if quarterly.match(str(x))]
            if len(timed) < 5:
                continue          # categorical axis: KPI names, call dates, bridges
            checked += 1
            title = exhibit["title"]
            excuse = next((why for key, why in self.SHORT_BY_DESIGN.items() if key in title), None)
            if excuse is None:
                self.assertGreaterEqual(
                    len(timed), record,
                    f"{title[:40]} has a quarterly axis but only {len(timed)} points "
                    "and no entry in SHORT_BY_DESIGN",
                )
                continue
            self.assertLess(len(timed), record, f"{title[:40]} is full length; drop its excuse")
            self.assertTrue(excuse.strip(), title)
        # Seventeen time-axis charts are permanent; section one adds one more in
        # a quarter whose follow-up closure falsified a call with a long series.
        story = sum(1 for ex in self.exhibits if ex["title"].startswith("上季判断"))
        self.assertGreaterEqual(checked, 17 + story, "the scan stopped finding charts")
        # And the two disclosure limits named above are the ones the source
        # records, not numbers typed into this file.
        long = self.source["long_history"]
        self.assertEqual(long["platform_first_reported"], "2018Q1")
        self.assertEqual(long["node_first_reported"]["2nm"], "2025Q2")

    def test_the_guided_record_spans_the_whole_decade(self) -> None:
        guide = self.source["quarterly_guidance_history"]
        following = iso_period(shift_period(self.source["periods"][-1], 1))
        self.assertEqual((guide["quarters"][0], guide["quarters"][-1]), ("2016Q1", following))
        year, quarter = int(following[:4]), int(following[-1])
        self.assertEqual(len(guide["quarters"]), (year - 2016) * 4 + quarter)
        # Revenue was guided in NT$ until 2017Q2 and in US$ from 2017Q3. Both
        #原值 have to survive: the dollar figures for those six quarters are
        # this page's conversion at the company's own stated assumption, not a
        # number TSMC published, and the note has to say so.
        currencies = dict(zip(guide["quarters"], guide["guide_currency"]))
        ntd = [q for q, c in currencies.items() if c == "NTD"]
        self.assertEqual(ntd, ["2016Q1", "2016Q2", "2016Q3", "2016Q4", "2017Q1", "2017Q2"])
        for index, quarter in enumerate(guide["quarters"]):
            has_ntd = guide["guide_low_ntd_bn"][index] is not None
            self.assertEqual(has_ntd, currencies[quarter] == "NTD", quarter)
            if has_ntd:
                self.assertAlmostEqual(
                    guide["guide_low_usd_bn"][index],
                    guide["guide_low_ntd_bn"][index] / guide["guide_fx_ntd_per_usd"][index],
                    places=3, msg=quarter,
                )
        self.assertIn("机械换算", guide["currency_break"]["note"])

    def test_long_history_agrees_with_the_eight_reviewed_quarters(self) -> None:
        """The routine charts run on 42 quarters read from the filings, while the
        rest of the page runs on the 8 reviewed ones. Where they overlap they are
        the same disclosure, so any disagreement means one of the two was mis-read
        -- and the long series is the one nobody has eyeballed quarter by quarter."""
        long = self.source["long_history"]
        quarters = long["quarters"]
        latest = iso_period(self.source["periods"][-1])
        self.assertEqual((quarters[0], quarters[-1]), ("2016Q1", latest))
        self.assertEqual(len(quarters), (int(latest[:4]) - 2016) * 4 + int(latest[-1]))
        self.assertEqual(sorted(set(quarters)), sorted(quarters), "duplicate quarter")
        for block in ("technology_mix_pct", "platform_mix_pct", "working_capital_days",
                      "capital_intensity"):
            for name, values in long[block].items():
                self.assertEqual(len(values), len(quarters), f"{block}.{name}")

        overlap = slice(-len(self.source["periods"]), None)
        for name in ("2nm", "3nm", "5nm", "7nm", "advanced_7nm_and_below"):
            self.assertEqual(long["technology_mix_pct"][name][overlap],
                             self.source["technology_mix_pct"][name], name)
        for name in ("hpc", "smartphone"):
            self.assertEqual(long["platform_mix_pct"][name][overlap],
                             self.source["platform_mix_pct"][name], name)
        for name in ("receivable_days", "inventory_days"):
            self.assertEqual(long["working_capital_days"][name][overlap],
                             self.source["working_capital_days"][name], name)

    def test_long_history_respects_what_was_never_disclosed(self) -> None:
        """Three disciplines, each protecting against a plausible-looking lie:
        no HPC before TSMC reported a platform split, no node line before that
        node had a row, and the 7nm-and-below aggregate summed here rather than
        quoted from TSMC's own 'advanced technologies' headline, whose definition
        moved twice without restatement."""
        long = self.source["long_history"]
        quarters = long["quarters"]
        technology = long["technology_mix_pct"]

        platform_start = quarters.index(long["platform_first_reported"])
        self.assertEqual(long["platform_first_reported"], "2018Q1")
        for name in ("hpc", "smartphone"):
            values = long["platform_mix_pct"][name]
            self.assertTrue(all(v is None for v in values[:platform_start]),
                            f"{name} claims a value before TSMC reported platforms")
            self.assertTrue(all(v is not None for v in values[platform_start:]), name)

        for node, first in long["node_first_reported"].items():
            values = technology[node]
            start = quarters.index(first)
            self.assertTrue(all(v is None for v in values[:start]),
                            f"{node} has a value before its row existed")
            self.assertTrue(all(v is not None for v in values[start:]),
                            f"{node} has a hole after its row existed")
            # The first non-zero must not precede the first reported quarter, and
            # the stored date is the one the series itself shows (the page reads
            # it off the series, so a stale stored date would go unnoticed there).
            self.assertGreaterEqual(quarters.index(long["node_first_nonzero"][node]), start)
            self.assertEqual(long["node_first_nonzero"][node],
                             next(q for q, v in zip(quarters, values) if v), node)

        for index, quarter in enumerate(quarters):
            summed = sum(technology[node][index] or 0 for node in ("2nm", "3nm", "5nm", "7nm"))
            self.assertEqual(technology["advanced_7nm_and_below"][index], summed, quarter)
        # It is a derivation, so it must be labelled as one on the chart.
        chart = next(ex for ex in self.by_section["routine"] if "制程迁移" in ex["title"])
        aggregate = next(s for s in chart["series"] if "7nm 及以下" in s["name"])
        self.assertIn("D", aggregate["name"])
        self.assertIn("advanced technologies", chart["note"])

    def test_capex_threshold_is_converted_and_marked(self) -> None:
        """The CapEx line is tracked in US$ but reported in NT$, so the plotted
        threshold must be the converted value and must say so."""
        exhibit = next(ex for ex in self.by_section["next_quarter"][1:] if "CapEx" in ex["title"])
        rate = self.source["guidance"]["reported"]["usd_ntd"]
        line = next(e for e in self.source["next_kpi"]["quantified"] if e["metric"] == "单季 CapEx")
        self.assertEqual(exhibit["series"][1]["values"][0], round(line["threshold"] * rate, 1))
        self.assertIn("按本季实际汇率", exhibit["note"])
        self.assertIn("D", exhibit["note"])

    def test_market_expectation_is_labelled_and_unattributed(self) -> None:
        text = json.dumps(self.payload, ensure_ascii=False)
        self.assertIn("市场预期", text)
        for broker in ["FactSet", "Bloomberg", "LSEG", "QUICK", "consensus"]:
            self.assertNotIn(broker.lower(), text.lower())
        # Taken before the release it is compared with, never after.
        self.assertLessEqual(self.source["market_expectation"]["as_of"],
                             self.source["latest"]["release_date"])

    def test_audit_tables_back_every_derived_exhibit(self) -> None:
        tables = self.payload["tables"]
        first = len(self.exhibits) + 2
        self.assertEqual([table["n"] for table in tables], list(range(first, first + len(tables))))
        self.assertIn("AI capex", tables[-1]["title"])
        thresholds = next(table for table in tables if table["title"].startswith("下季阈值"))
        self.assertEqual(len(thresholds["rows"]), len(self.source["next_kpi"]["quantified"]))
        financials = next(table for table in tables if "隐含 ASP" in table["title"])
        for row in financials["rows"]:  # implied ASP travels with the raw inputs
            self.assertTrue(row[-1].endswith("D"))
        # A check table has to be as long as the chart it backs. Three of them
        # carry the ten-year record now, and the eight-quarter guidance table
        # that used to sit beside the 43-quarter one is gone -- two tables of
        # the same thing at different lengths is how they drift apart.
        long_rows = len(self.source["long_history"]["quarters"])
        for marker in ("隐含 ASP", "制程与平台", "现金流与营运资金"):
            table = next(item for item in tables if marker in item["title"])
            self.assertEqual(len(table["rows"]), long_rows, marker)
            self.assertTrue(table["title"].startswith(f"{long_rows} 季度"), marker)
        titles = " ".join(item["title"] for item in tables)
        self.assertNotIn("八季度", titles)
        delivery = next(item for item in tables if "指引兑现全表" in item["title"])
        self.assertEqual(len(delivery["rows"]),
                         len(self.source["quarterly_guidance_history"]["quarters"]))

    def test_cross_page_table_is_identical_on_every_page(self) -> None:
        """The AI-capex cross reference is the one object published byte-for-byte
        on every page; if a builder starts assembling its own copy, the pages
        quietly stop agreeing about the same quarters."""
        payloads = build_all()
        tables = [
            next(table for table in payload["tables"] if "AI capex" in table["title"])
            for payload in payloads.values()
        ]
        self.assertEqual(len(tables), len(payloads))
        for table in tables[1:]:
            self.assertEqual(table["rows"], tables[0]["rows"])
            self.assertEqual(table["headers"], tables[0]["headers"])
        self.assertEqual(len(tables[0]["rows"]), len(self.source["periods"]))
        # One column per hyperscaler, so the slice has to widen with the table:
        # pinning it at 1:4 would have kept passing while the newest column
        # silently filled with dashes.
        hyperscalers = sum(1 for header in tables[0]["headers"] if header.endswith("现金 CapEx"))
        self.assertEqual(hyperscalers, 4)
        for row in tables[0]["rows"]:
            self.assertNotIn("—", row[1:1 + hyperscalers],
                             "a hyperscaler capex column lost a quarter")

    def test_sources_are_official_http_links(self) -> None:
        allowed_hosts = {"investor.tsmc.com", "www.sec.gov"}
        for source in self.payload["source_links"]:
            parsed = urlparse(source["url"])
            self.assertEqual(parsed.scheme, "https")
            self.assertIn(parsed.hostname, allowed_hosts)

    def test_published_payload_roster_and_shell(self) -> None:
        self.assertEqual(js_payload(ROOT / "data" / "tsm.js", "window.DASH"), self.payload)
        # roster.js is loaded by every company page, so a stale one -- the exact
        # result of rebuilding one company instead of running build/all.py --
        # corrupts the cross-company nav on all of them. Assert equality, not
        # just the slug set.
        roster = js_payload(ROOT / "data" / "roster.js", "window.ROSTER")
        self.assertEqual(roster, roster_payload(build_all()))
        self.assertEqual(
            [item["slug"] for item in roster["items"]],
            [
             "amzn", "avgo", "axp", "bc", "cboe", "cdns", "cfr", "cme", "cost",
             "googl", "hkex", "ibkr", "ker", "ma", "mc", "mco", "meta", "msci",
             "msft",
             "mu", "ndaq", "nke", "nvda", "pm", "race", "rms", "samsung",
             "schw",
             "skhynix", "snps", "spgi", "tjx", "tsm", "v",
            ],
        )
        shell = (ROOT / "tsm" / "index.html").read_text(encoding="utf-8")
        self.assertIn('../data/tsm.js', shell)
        self.assertNotIn('../data/googl.js', shell)

    def test_shell_versions_every_script_by_content(self) -> None:
        """GitHub Pages caches everything for ten minutes and the HTML and the
        payload expire independently, so a bare `src` let a returning reader see
        the new page with the old data -- or a mix of both. Each script URL has
        to carry its own file's digest, and it has to be the CURRENT digest: a
        shell rendered before the payload was written would stamp the previous
        build's hash and cache exactly the file it was meant to bust."""
        import hashlib

        shell = (ROOT / "tsm" / "index.html").read_text(encoding="utf-8")
        sources = re.findall(r'<script src="\.\./([^"?]+)(\?v=([0-9a-f]+))?"', shell)
        self.assertEqual(
            [name for name, _, _ in sources],
            ["data/roster.js", "data/tsm.js", "assets/charts.js", "assets/page.js"],
        )
        for name, query, digest in sources:
            with self.subTest(script=name):
                self.assertTrue(query, f"{name} is served without a cache-busting version")
                expected = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()[: len(digest)]
                self.assertEqual(digest, expected, f"{name} carries a stale digest")

    def test_home_page_matches_roster(self) -> None:
        """index.html is hand-written and reads no payload, so it can silently
        keep advertising last quarter while the company pages move on."""
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        roster = js_payload(ROOT / "data" / "roster.js", "window.ROSTER")
        for item in roster["items"]:
            self.assertIn(f'href="{item["slug"]}/"', home)
            self.assertIn(item["latest_label"], home)
            self.assertIn(item["release_date"], home)

    def test_public_files_exclude_private_and_broker_material(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [
                ROOT / "series" / "tsm.json",
                ROOT / "data" / "tsm.js",
                ROOT / "tsm" / "index.html",
            ]
        ).lower()
        for forbidden in [
            "/users/",
            "/library/cloudstorage/",
            "onedrive",
            "seeking alpha",
            "alphastreet",
            "factset",
            "bloomberg",
            "yahoo finance",
            "谨慎多",
        ]:
            self.assertNotIn(forbidden, text)
        compact = "".join(text.split())
        self.assertNotIn(":nan", compact)
        self.assertNotIn(":infinity", compact)
        self.assertNotIn(":-infinity", compact)


class TsmRollTest(unittest.TestCase):
    """What a quarter roll has to change in `series/tsm.json`, and what the page
    does when it does not.

    Every block that describes one quarter carries that quarter: the snapshot
    columns, this call's guidance and full-year outlook, the market
    expectation, a one-off in net income, the capex outlook, the delivery
    against guidance, the follow-up closure, the thresholds and the call's own
    readings (`quarter_story`). A block stamped with another quarter is last
    quarter's story and stops the build; an absent one means this quarter has
    no such story, and the page leaves that part out rather than borrowing it.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "tsm.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)
        cls.blob = json.dumps(cls.payload, ensure_ascii=False)

    def build(self, staging: dict) -> dict:
        return build_payload(staging)

    def text(self, staging: dict) -> str:
        return json.dumps(build_payload(staging), ensure_ascii=False)

    def test_a_block_stamped_with_another_quarter_stops_the_build(self) -> None:
        stamped = ("current_snapshot", "declared_dividend", "guidance", "market_expectation",
                   "net_income_bridge", "capex_guidance_history", "guidance_delivery",
                   "followup_closure", "next_kpi", "quarter_story")
        for key in stamped:
            stale = copy.deepcopy(self.source)
            stale[key]["period"] = "Q1 1999"
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    build_payload(stale)
        tamper = {
            "next guide": lambda d: d["guidance"]["next_guide"].__setitem__("quarter", "Q1 1999"),
            "thresholds for": lambda d: d["next_kpi"].__setitem__("for_period", "Q1 1999"),
            "closure set in": lambda d: d["followup_closure"].__setitem__("set_in", "Q1 1999"),
            "guided record": lambda d: d["quarterly_guidance_history"]["quarters"].__setitem__(-1, "1999Q1"),
            "long record": lambda d: d["long_history"]["quarters"].__setitem__(-1, "1999Q1"),
        }
        for name, change in tamper.items():
            stale = copy.deepcopy(self.source)
            change(stale)
            with self.subTest(block=name):
                with self.assertRaisesRegex(ValueError, "stamped|closes"):
                    build_payload(stale)
        stale = copy.deepcopy(self.source)
        hub = f"TSMC {self.source['periods'][-1]} quarterly"
        stale["sources"] = [item for item in stale["sources"] if not item["label"].startswith(hub)]
        self.assertLess(len(stale["sources"]), len(self.source["sources"]))
        with self.assertRaisesRegex(ValueError, "sources"):
            build_payload(stale)

    def test_a_quarter_without_a_story_leaves_it_out(self) -> None:
        """Each one-quarter block, removed alone, takes its own sentences with it."""
        bridge = self.source["net_income_bridge"]
        closure = self.source["followup_closure"]
        story = self.source["quarter_story"]
        cases = {
            "net_income_bridge": (f"剔除 {bridge['one_off_short']} 一次性", "核心净利 D",
                                  bridge["one_off_description"], "「核心」口径"),
            "followup_closure": ("待验证问题", "（被证伪）", closure["undisclosed_topics"][0]),
            "quarter_story": (f"市场卖的是{story['market_sold']}", story["prior_call_quote"],
                              story["inventory_test"], "管理层首次量化"),
            "guidance": ("兑现、", "全年 outlook", "海外厂毛利率稀释"),
            "capex_guidance_history": ("CapEx 预算半年内", "口径依次为"),
            "declared_dividend": ("股息约 NT$", "股息年化 =",
                                  self.source["declared_dividend"]["links"][0]["url"]),
        }
        for key, texts in cases.items():
            bare = copy.deepcopy(self.source)
            del bare[key]
            after = self.text(bare)
            for text in texts:
                with self.subTest(block=key, text=text):
                    self.assertIn(text, self.blob)
                    self.assertNotIn(text, after)
        # Charts drop out and the numbering closes up behind them.
        bare = copy.deepcopy(self.source)
        for key in ("net_income_bridge", "followup_closure", "guidance_delivery",
                    "capex_guidance_history", "quarter_story"):
            del bare[key]
        payload = build_payload(bare)
        numbers = [ex["n"] for s in payload["sections"] for ex in s["exhibits"]]
        self.assertEqual(numbers, list(range(2, 2 + len(numbers))))
        self.assertEqual(len(numbers), len([ex for s in self.payload["sections"] for ex in s["exhibits"]]) - 5)

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        """Break each "all / every / never / first / only / highest" claim in the
        data once; the sentence that made it must go."""
        def widen_one_gm_band(d):
            d["quarterly_guidance_history"]["gross_margin_guide_high_pct"][5] += 0.5

        def om_breaks_floor_since_2023(d):
            guide = d["quarterly_guidance_history"]
            index = guide["quarters"].index("2024Q2")
            guide["operating_margin_actual_pct"][index] = guide["operating_margin_guide_low_pct"][index] - 1

        def capex_slows(d):
            long = d["long_history"]["capital_intensity"]
            long["capex_usd_bn"][-1] = long["capex_usd_bn"][-5]

        def intensity_peaks_now(d):
            long = d["long_history"]["capital_intensity"]
            long["capex_usd_bn"][-1] = long["revenue_usd_bn"][-1] * 0.9

        def negative_fcf_recently(d):
            cash = d["long_history"]["cash_flow_ntd_bn"]
            cash["free_cash_flow"][-3] = -5.0

        def two_nm_older(d):
            d["long_history"]["technology_mix_pct"]["2nm"][-2] = 1

        def receivable_new_low(d):
            d["long_history"]["working_capital_days"]["receivable_days"][-1] = 20

        cases = {
            "gross-margin bands not all 2pp": (widen_one_gm_band, ("区间宽度一律",)),
            "operating margin below its floor after 2023": (
                om_breaks_floor_since_2023, ("「指引是底线」是 2023 年以后才成立的性质",
                                             "看起来像一条底线而不是预测")),
            "capex growth back below revenue growth": (
                capex_slows, ("反超收入增速", "本季两条线交叉")),
            "capital intensity at its peak this quarter": (
                intensity_peaks_now, ("本季并不是历史高位",)),
            "a negative free-cash-flow quarter in the window": (
                negative_fcf_recently, ("的窗口里一次都看不到",)),
            "2nm not new this quarter": (two_nm_older, ("本季首次单列", "2nm 首季")),
            "receivable days at a new low": (receivable_new_low, ("应收天数从 ",)),
        }
        for name, (change, claims) in cases.items():
            broken = copy.deepcopy(self.source)
            change(broken)
            after = self.text(broken)
            for claim in claims:
                with self.subTest(case=name, claim=claim):
                    self.assertIn(claim, self.blob)
                    self.assertNotIn(claim, after)

    def test_the_crossover_note_lists_every_crossing(self) -> None:
        """It said the earlier crossings all came when revenue growth was low or
        negative and that this one was the first above 30%; 2021Q1, 2022Q4 and
        2024Q4 crossed at +25% to +37%. The note now lists every crossing from
        below with the revenue growth at the time, counted from the chart."""
        chart = next(ex for ex in self.payload["sections"][1]["exhibits"]
                     if ex["title"].startswith("CapEx 增速"))
        revenue, capex = (series["values"] for series in chart["series"])
        crossings = [i for i in range(5, len(revenue))
                     if capex[i] > revenue[i] and capex[i - 1] <= revenue[i - 1]]
        self.assertIn(f"从下方穿上来的有 {len(crossings)} 次", chart["note"])
        for i in crossings:
            self.assertIn(f"{revenue[i]:+.1f}%", chart["note"])
        self.assertNotIn("下行段", chart["note"])


class TsmChecksTest(unittest.TestCase):
    """The page's quarter against a record keyed separately from the filings.

    `_checks` is typed once per quarter from the 6-K earnings release and the
    quarterly management report, with the place each figure was read; the
    builder never reads it (asserted in `test_data_only_roll`). A roll that
    misaligns a column, drops the new quarter or keeps last quarter's sentence
    fails here. TSMC prints its margins, mixes and days itself; where the page
    prints the same figure it must be the company's.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "tsm.json").read_text(encoding="utf-8"))
        cls.checks = cls.source["_checks"]
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]

    def test_the_page_names_the_checked_quarter(self) -> None:
        c = self.checks
        self.assertIn(c["period"], self.payload["title"])
        self.assertIn(f"截至 {c['period_end']}", self.payload["subtitle"])
        self.assertIn(f"发布 {c['release_date']}", self.payload["subtitle"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        c, s = self.checks, self.source
        fin, snap, long = s["financials"], s["current_snapshot"], s["long_history"]
        self.assertEqual(fin["revenue_usd_bn"][-1], c["revenue_usd_bn"])
        self.assertEqual(snap["revenue_ntd_bn"][0], c["revenue_ntd_bn"])
        self.assertEqual(fin["revenue_yoy_pct"][-1], c["revenue_usd_yoy_pct"])
        self.assertEqual(fin["gross_margin_pct"][-1], c["gross_margin_pct"])
        self.assertEqual(fin["operating_margin_pct"][-1], c["operating_margin_pct"])
        self.assertEqual(fin["eps_ntd"][-1], c["eps_ntd"])
        self.assertEqual(snap["net_income_ntd_bn"][0], c["net_income_ntd_bn"])
        for node, value in c["wafer_revenue_mix_pct"].items():
            self.assertEqual(s["technology_mix_pct"][node][-1], value, node)
        self.assertEqual(s["platform_mix_pct"]["hpc"][-1], c["hpc_pct"])
        self.assertEqual(s["platform_mix_pct"]["smartphone"][-1], c["smartphone_pct"])
        self.assertEqual(fin["wafer_shipments_kpcs_12in_equiv"][-1], c["wafer_shipments_kpcs_12in_equiv"])
        self.assertEqual(long["financials"]["usd_ntd_actual"][-1], c["average_usd_ntd"])
        self.assertEqual(s["working_capital_days"]["receivable_days"][-1], c["receivable_days"])
        self.assertEqual(s["working_capital_days"]["inventory_days"][-1], c["inventory_days"])
        cash = s["cash_flow_ntd_bn"]
        self.assertEqual(cash["operating_cash_flow"][-1], c["operating_cash_flow_ntd_bn"])
        self.assertEqual(cash["capital_expenditures"][-1], c["capital_expenditures_ntd_bn"])
        self.assertEqual(cash["free_cash_flow"][-1], c["free_cash_flow_ntd_bn"])
        self.assertEqual(long["capital_intensity"]["capex_usd_bn"][-1], c["capital_expenditures_usd_bn"])
        self.assertEqual(snap["cash_dividends_ntd_bn"][0], c["cash_dividends_ntd_bn"])
        self.assertEqual(s["net_income_bridge"]["values_ntd_bn"][1], c["vis_gain_ntd_bn"])
        upcoming = s["guidance"]["next_guide"]
        self.assertEqual(upcoming["revenue_usd_bn"], c["next_quarter_revenue_usd_bn"])
        self.assertEqual(upcoming["usd_ntd"], c["next_quarter_usd_ntd_assumption"])
        self.assertEqual(upcoming["gross_margin_pct"], c["next_quarter_gross_margin_pct"])
        self.assertEqual(upcoming["operating_margin_pct"], c["next_quarter_operating_margin_pct"])
        guide = s["quarterly_guidance_history"]
        self.assertEqual([guide["guide_low_usd_bn"][-1], guide["guide_high_usd_bn"][-1]],
                         c["next_quarter_revenue_usd_bn"])

    def test_the_rounding_the_page_prints_is_the_companys(self) -> None:
        """Quarter-on-quarter revenue and shipments are printed by the company to
        one decimal; the page computes them from the levels and must land on the
        same figure."""
        c = self.checks
        long = self.source["long_history"]["financials"]
        revenue, shipments = long["revenue_usd_bn"], long["wafer_shipments_kpcs_12in_equiv"]
        self.assertEqual(round((revenue[-1] / revenue[-2] - 1) * 100, 1), c["revenue_usd_qoq_pct"])
        self.assertEqual(round((shipments[-1] / shipments[-2] - 1) * 100, 1), c["wafer_shipments_qoq_pct"])
        snap = self.source["current_snapshot"]["revenue_ntd_bn"]
        self.assertEqual(round((snap[0] / snap[2] - 1) * 100, 1), c["revenue_ntd_yoy_pct"])

    def test_the_page_prints_the_checked_figures(self) -> None:
        c = self.checks
        self.assertIn(f"毛利率 {c['gross_margin_pct']:.1f}%", self.payload["headline"])
        self.assertIn(f"US${c['revenue_usd_bn']:.2f}B", self.payload["brief"])
        self.assertIn(f"GM {c['gross_margin_pct']:.1f}%、OM {c['operating_margin_pct']:.1f}%",
                      self.payload["brief"])
        self.assertIn(f"出货环比 +{c['wafer_shipments_qoq_pct']:.1f}%", self.payload["brief"])
        revenue = next(ex for ex in self.exhibits if ex["title"].startswith("收入 US$"))
        self.assertIn(f"收入 US${c['revenue_usd_bn']:.2f}B", revenue["title"])
        self.assertIn(f"环比 +{c['revenue_usd_qoq_pct']:.1f}%、同比 +{c['revenue_usd_yoy_pct']:.1f}%",
                      revenue["note"])
        tech = next(ex for ex in self.exhibits if "制程迁移" in ex["title"])
        self.assertIn(f"升到 {c['wafer_revenue_mix_pct']['advanced_7nm_and_below']}%", tech["title"])
        working = next(ex for ex in self.exhibits if ex["title"].startswith("库存天数") and "区间" in ex["title"])
        self.assertIn(f"本季 {c['inventory_days']} 天", working["title"])
        rows = {row[0]: row for row in self.payload["tables"][0]["rows"]}
        low, high = c["next_quarter_revenue_usd_bn"]
        self.assertEqual(rows["收入（美元）"][4], f"US${low:.1f}–{high:.1f}B")

    def test_the_annualised_dividend_is_the_declared_rate_times_the_shares(self) -> None:
        """The cash-flow note annualises the dividend the board last declared,
        per share × 4 × shares outstanding, both keyed into `_checks` from the
        6-Ks -- not four times the cash paid this quarter, which is the dividend
        declared two quarters earlier. Recomputed here from `_checks`, not
        through the builder."""
        c, block = self.checks, self.source["declared_dividend"]
        self.assertEqual(block["per_share_ntd"], c["declared_dividend_per_share_ntd"])
        self.assertEqual(block["dividend_quarter"], c["declared_dividend_quarter"])
        self.assertEqual(block["board_date"], c["declared_dividend_board_date"])
        self.assertEqual(block["shares_outstanding_thousands"], c["shares_outstanding_thousands"])
        self.assertIn(f"NT${c['declared_dividend_per_share_ntd']:.1f} per share", block["wording"])
        annual = c["declared_dividend_per_share_ntd"] * 4 * c["shares_outstanding_thousands"] / 1e6
        cash = next(ex for ex in self.exhibits if "自由现金流" in ex["title"] and "股息" in ex["note"])
        self.assertIn(f"股息约 NT${annual:.0f}B", cash["note"])
        self.assertNotIn(f"NT${self.source['current_snapshot']['cash_dividends_ntd_bn'][0] * 4:.0f}B",
                         cash["note"])
        self.assertIn(f"{c['shares_outstanding_thousands']:,} 千股", cash["src_extra"])


if __name__ == "__main__":
    unittest.main()
