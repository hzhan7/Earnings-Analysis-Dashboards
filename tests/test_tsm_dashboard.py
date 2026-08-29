from __future__ import annotations

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
from build.tsm import build_payload, compact_period  # noqa: E402


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

    def test_all_historical_series_have_eight_quarters(self) -> None:
        self.assertEqual(len(self.source["periods"]), 8)
        for section in [
            "financials",
            "technology_mix_pct",
            "platform_mix_pct",
            "cash_flow_ntd_bn",
            "working_capital_days",
            "revenue_guidance_history_usd_bn",
        ]:
            for name, values in self.source[section].items():
                self.assertEqual(len(values), 8, f"{section}.{name}")
                # None is allowed and meaningful: a node with no row in the
                # company's table is not the same fact as a reported 0%.
                self.assertTrue(
                    all(value is None or math.isfinite(value) for value in values),
                    f"{section}.{name}",
                )
                self.assertIsNotNone(values[-1], f"{section}.{name} has no current value")

    def test_key_source_values_and_formulas(self) -> None:
        financials = self.source["financials"]
        snapshot = self.source["current_snapshot"]
        self.assertEqual(financials["revenue_usd_bn"][-1], 40.20)
        self.assertEqual(financials["gross_margin_pct"][-1], 67.7)
        self.assertEqual(financials["operating_margin_pct"][-1], 60.3)
        self.assertEqual(self.source["technology_mix_pct"]["2nm"][-1], 3)
        self.assertEqual(self.source["platform_mix_pct"]["hpc"][-1], 66)

        cash = self.source["cash_flow_ntd_bn"]
        for operating, capex, free_cash in zip(
            cash["operating_cash_flow"], cash["capital_expenditures"], cash["free_cash_flow"]
        ):
            self.assertAlmostEqual(round(operating - capex, 2), free_cash, places=2)

        bridge = self.source["net_income_bridge"]["values_ntd_bn"]
        self.assertAlmostEqual(bridge[0] - bridge[1], bridge[2], places=2)
        self.assertEqual(bridge[1], snapshot["vis_disposal_and_mark_to_market_gain_pretax_ntd_bn"])

    def test_guidance_history_is_not_overstated(self) -> None:
        history = self.source["revenue_guidance_history_usd_bn"]
        at_or_above_high = 0
        for low, high, actual in zip(history["low"], history["high"], history["actual"]):
            midpoint = (low + high) / 2
            self.assertGreaterEqual(actual, midpoint)
            at_or_above_high += int(actual >= high)
        self.assertEqual(at_or_above_high, 6)
        self.assertLess(history["actual"][1], history["high"][1])  # Q4'24 remained in range.

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
        self.assertEqual(
            [(section["id"], len(section["exhibits"])) for section in self.payload["sections"]],
            [
                ("settled", 11),
                ("quarter_highlights", 7),
                ("next_quarter", 6),
                ("routine", 4),
            ],
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
        self.assertEqual(compact[-1], "Q2'26")
        overlap = guide["quarters"].index("2024Q3")
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
        overlap = guide["quarters"].index("2024Q3")
        window = slice(overlap, overlap + len(self.source["periods"]))
        for name, published in (
            ("gross_margin_actual_pct", "gross_margin_pct"),
            ("operating_margin_actual_pct", "operating_margin_pct"),
        ):
            for computed, reported in zip(guide[name][window], self.source["financials"][published]):
                self.assertAlmostEqual(computed, reported, delta=0.05, msg=name)
        # NT$ revenue from the same filings has to reproduce the snapshot too.
        by_quarter = dict(zip(guide["quarters"], guide["reported_revenue_ntd_bn"]))
        for quarter, snapshot in zip(
            ("2026Q2", "2026Q1", "2025Q2"), self.source["current_snapshot"]["revenue_ntd_bn"]
        ):
            self.assertAlmostEqual(by_quarter[quarter], snapshot, places=1, msg=quarter)
        for name in ("gross_margin_guide_low_pct", "gross_margin_guide_high_pct",
                     "gross_margin_actual_pct", "operating_margin_guide_low_pct",
                     "operating_margin_guide_high_pct", "operating_margin_actual_pct",
                     "reported_revenue_ntd_bn"):
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
        self.assertEqual(set(bands), {"收入", "毛利率", "营业利润率"})
        for metric, keys in (
            ("收入", ("guide_low_usd_bn", "guide_high_usd_bn", "actual_revenue_usd_bn")),
            ("毛利率", ("gross_margin_guide_low_pct", "gross_margin_guide_high_pct",
                     "gross_margin_actual_pct")),
            ("营业利润率", ("operating_margin_guide_low_pct", "operating_margin_guide_high_pct",
                       "operating_margin_actual_pct")),
        ):
            band = bands[metric]
            self.assertEqual(band["lo"], guide[keys[0]], metric)
            self.assertEqual(band["hi"], guide[keys[1]], metric)
            self.assertEqual(band["actual"], guide[keys[2]], metric)
            self.assertEqual(band["xlabels"], guide["quarters"], metric)
            for low, high in zip(band["lo"], band["hi"]):
                self.assertLess(low, high, metric)
        self.assertEqual(bands["收入"]["fmt"], "usd1")
        self.assertEqual(bands["毛利率"]["fmt"], "pct1")
        # Operating margin has never once landed back inside its range.
        operating = guide["operating_margin_actual_pct"]
        highs = guide["operating_margin_guide_high_pct"]
        finished = [(a, h) for a, h in zip(operating, highs) if a is not None]
        self.assertEqual(len(finished), 14)
        self.assertTrue(all(a > h for a, h in finished))
        self.assertIn("全部超出指引上限", bands["营业利润率"]["title"])

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
        self.assertTrue(all(value > 0 for value in chart["values"]))

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
        self.assertEqual([len(ex["xlabels"]) for ex in bands], [15, 15, 15])
        metrics = ["收入", "毛利率", "营业利润率"]
        self.assertEqual([ex["title"].split("：")[0] for ex in bands], metrics)
        self.assertEqual([ex["title"].split("相对")[0] for ex in deviations], metrics)
        expected = [
            bands[0]["n"], deviations[0]["n"], legs["n"],
            bands[1]["n"], deviations[1]["n"],
            bands[2]["n"], deviations[2]["n"],
        ]
        self.assertEqual(expected, [ex["n"] for ex in settled][3:10])
        self.assertEqual(expected, sorted(expected), "the block must stay in reading order")
        for note in self.payload["notes"]:
            for token in re.findall(r"Exhibit (\d+)", note):
                self.assertIn(int(token), numbers, note)

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
            for entry in self.source["q2_guidance_delivery"]
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
        exhibit = next(ex for ex in self.exhibits if "隐含 ASP" in ex["title"])
        asp = exhibit["yoy"]["values"]
        for index, value in enumerate(asp):
            shipments = self.source["financials"]["wafer_shipments_kpcs_12in_equiv"][index]
            revenue = self.source["financials"]["revenue_usd_bn"][index]
            self.assertAlmostEqual(value * shipments / 1_000_000, revenue, places=6)
        self.assertEqual(exhibit["values"], self.source["financials"]["wafer_shipments_kpcs_12in_equiv"])

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
        self.assertEqual(breached, ["2nm 占晶圆收入"])

    def test_every_tracked_metric_with_a_series_gets_its_own_chart(self) -> None:
        charted = {
            exhibit["title"].split("：")[0] for exhibit in self.by_section["next_quarter"][1:]
        }
        tracked = {entry["metric"] for entry in self.source["next_kpi"]["quantified"]}
        # The spot FX rate has no published quarterly series to plot against.
        self.assertEqual(tracked - charted, {"USD/TWD 即期（升值为逆风）"})
        for exhibit in self.by_section["next_quarter"][1:]:
            line = exhibit["series"][1]["values"]
            self.assertEqual(len(set(line)), 1, exhibit["title"])
            self.assertEqual(len(line), len(exhibit["series"][0]["values"]), exhibit["title"])

    def test_dollar_capex_backs_the_intensity_and_growth_charts(self) -> None:
        """CapEx is reported in NT$ but the intensity ratio and the growth
        crossover both need US$ on each side, so the dollar series has to carry
        four extra quarters and reconcile with the NT$ one."""
        block = self.source["capital_expenditures_usd_bn"]
        self.assertEqual(len(block["values"]), 12)
        self.assertEqual(len(block["periods"]), 12)
        self.assertEqual(block["periods"][-8:], self.source["periods"])
        ntd = self.source["cash_flow_ntd_bn"]["capital_expenditures"]
        for usd, nt in zip(block["values"][-8:], ntd):
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
            self.assertEqual(revenue, long["capital_intensity"]["revenue_usd_bn"][-8:][index])
        crossover = next(ex for ex in self.exhibits if "反超收入增速" in ex["title"])
        self.assertEqual(
            crossover["series"][0]["values"], self.source["financials"]["revenue_yoy_pct"]
        )
        self.assertEqual(len(crossover["series"][1]["values"]), 8)
        self.assertTrue(all(v is not None for v in crossover["series"][1]["values"]))

    def test_long_history_agrees_with_the_eight_reviewed_quarters(self) -> None:
        """The routine charts run on 42 quarters read from the filings, while the
        rest of the page runs on the 8 reviewed ones. Where they overlap they are
        the same disclosure, so any disagreement means one of the two was mis-read
        -- and the long series is the one nobody has eyeballed quarter by quarter."""
        long = self.source["long_history"]
        quarters = long["quarters"]
        self.assertEqual(len(quarters), 42)
        self.assertEqual((quarters[0], quarters[-1]), ("2016Q1", "2026Q2"))
        self.assertEqual(sorted(set(quarters)), sorted(quarters), "duplicate quarter")
        for block in ("technology_mix_pct", "platform_mix_pct", "working_capital_days",
                      "capital_intensity"):
            for name, values in long[block].items():
                self.assertEqual(len(values), 42, f"{block}.{name}")

        overlap = slice(-8, None)
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
            # The first non-zero must not precede the first reported quarter.
            self.assertGreaterEqual(quarters.index(long["node_first_nonzero"][node]), start)

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
        rate = self.source["guidance"]["q2_actual"]["usd_ntd"]
        self.assertEqual(exhibit["series"][1]["values"][0], round(19.0 * rate, 1))
        self.assertIn("按本季实际汇率", exhibit["note"])
        self.assertIn("D", exhibit["note"])

    def test_market_expectation_is_labelled_and_unattributed(self) -> None:
        text = json.dumps(self.payload, ensure_ascii=False)
        self.assertIn("市场预期", text)
        for broker in ["FactSet", "Bloomberg", "LSEG", "QUICK", "consensus"]:
            self.assertNotIn(broker.lower(), text.lower())
        self.assertEqual(self.source["market_expectation"]["as_of"], "2026-07-16")

    def test_audit_tables_back_every_derived_exhibit(self) -> None:
        tables = self.payload["tables"]
        first = len(self.exhibits) + 2
        self.assertEqual([table["n"] for table in tables], list(range(first, first + 8)))
        self.assertIn("AI capex", tables[-1]["title"])
        self.assertEqual(len(tables[1]["rows"]), len(self.source["next_kpi"]["quantified"]))
        financials = next(table for table in tables if "隐含 ASP" in table["title"])
        for row in financials["rows"]:  # implied ASP travels with the raw inputs
            self.assertTrue(row[-1].endswith("D"))

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
             "amzn", "avgo", "axp", "cboe", "cdns", "cme", "cost", "googl",
             "ibkr", "ma", "mco", "meta", "msci", "msft", "ndaq", "nke",
             "nvda", "pm", "race", "schw", "skhynix", "snps", "spgi",
             "tjx", "tsm", "v",
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


if __name__ == "__main__":
    unittest.main()
