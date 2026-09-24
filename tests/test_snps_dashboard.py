"""Reconciliation and shape tests for the SNPS page.

Same purpose as the other companies': nothing derived reaches the page until it
has been checked against a statement identity or a figure the company disclosed
separately.  Synopsys adds two identities the other pages do not have.

The first is that its guidance is *self-reconciling*.  Every earnings 8-K guides
revenue, non-GAAP expenses, non-GAAP other income, the non-GAAP tax rate and the
diluted share count, and then guides the non-GAAP EPS those five imply -- so
running the five midpoints through the arithmetic has to reproduce the sixth.
It does, to within the rounding of the published endpoints, which is what
licenses the page to treat "guided revenue minus guided expenses" as the
company's own operating-income number.

The second is a hazard rather than a help: Software Integrity moved to
discontinued operations in the quarter ended 2024-04-30, so that one quarter was
guided on one basis and reported on another.  The test pins the add-back that
shows the apparent miss is the basis change and not a miss, because a page that
quietly dropped that quarter would be hiding its most interesting data point.
"""

from __future__ import annotations

import copy
import json
import math
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.all import build_all, roster_payload  # noqa: E402
from build.board import cn_count, headroom  # noqa: E402
from build.payload_guard import check as guard_check  # noqa: E402
from build.snps import build_payload, compact_period, fiscal_words  # noqa: E402

# Record tallies are pinned exactly through the last quarter guided when this
# page was migrated; later quarters extend the record and are checked as
# invariants against what the page prints.
PINNED_THROUGH = "Q3 2026"


def published_text(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def quarter_order(label: str) -> int:
    quarter, year = label.split()
    return int(year) * 4 + int(quarter[1])


def pinned(record: dict) -> list[int]:
    return [i for i, q in enumerate(record["quarters"]) if quarter_order(q) <= quarter_order(PINNED_THROUGH)]


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


# ── threshold lines, recomputed here rather than through the builder ─────────
GOOD = {"hurdle": "达到", "guard": "守住"}
BAD = {"hurdle": "没到", "guard": "越线"}
COMPARE = {"<": lambda v, t: v < t, "≤": lambda v, t: v <= t, ">": lambda v, t: v > t, "≥": lambda v, t: v >= t}


def shifted(label: str, by: int) -> str:
    number = quarter_order(label) - 1 + by
    return f"Q{number % 4 + 1} {number // 4}"


def eda_pairs(source: dict) -> list[tuple[float, float]]:
    """EDA without Ansys per window quarter, (this quarter, a year earlier), from the block's pairs."""
    def amount(parts: dict) -> float:
        if "three_months" in parts:
            share, base = parts["three_months"]
            return share * base / 100
        (fy_share, fy_base), (nine_share, nine_base) = parts["full_year"], parts["nine_months"]
        return (fy_share * fy_base - nine_share * nine_base) / 100
    return [(amount(r["now"]), amount(r["year_ago"])) for r in source["eda_product_group"]["readings"]]


def ansys_by_quarter(source: dict) -> dict[str, float]:
    block = source["ansys_revenue"]
    revenue = dict(zip(source["periods"], source["financials"]["revenue_usd_m"]))
    out = {}
    for i, quarter in enumerate(block["quarters"]):
        if block["printed_usd_m"][i] is not None:
            out[quarter] = block["printed_usd_m"][i]
        elif block["share_pct"][i] is not None:
            out[quarter] = block["share_pct"][i] / 100 * revenue[quarter]
        else:
            year = block["fiscal_labels"][i][:6]
            out[quarter] = block["fiscal_year_usd_m"][year] - sum(
                out[q] for q, f in zip(block["quarters"][:i], block["fiscal_labels"][:i]) if f[:6] == year)
    return out


def history(source: dict, reads: str) -> list[float | None]:
    """The quarterly history a line reads, aligned to its chart's axis."""
    fin, seg = source["financials"], source["segments_usd_m"]
    periods = source["periods"]
    ip = dict(zip(periods, seg["design_ip_revenue"]))
    for label, value in seg.get("design_ip_revenue_prior_year_outside_window", {}).items():
        ip.setdefault(shifted(label, -4), value)
    if reads == "eda_yoy":
        return [(a / b - 1) * 100 for a, b in eda_pairs(source)]
    if reads == "eda_resid":
        ansys = ansys_by_quarter(source)
        return [da - ansys.get(p, 0.0) for p, da in zip(periods, seg["design_automation_revenue"])]
    if reads == "margin":
        return [oi / rev * 100 for oi, rev in zip(fin["non_gaap_operating_income_usd_m"], fin["revenue_usd_m"])]
    if reads == "fy_margin":
        out = []
        for i, label in enumerate(source["fiscal_labels"]):
            start = i - int(label[-1]) + 1
            if start >= 0:
                out.append(sum(fin["non_gaap_operating_income_usd_m"][start:i + 1])
                           / sum(fin["revenue_usd_m"][start:i + 1]) * 100)
        return out
    if reads == "ip_yoy":
        return [None if shifted(p, -4) not in ip else (ip[p] / ip[shifted(p, -4)] - 1) * 100 for p in periods]
    if reads == "ip_qoq":
        return [None if shifted(p, -1) not in ip else (ip[p] / ip[shifted(p, -1)] - 1) * 100 for p in periods]
    backlog = source["backlog"]
    if reads == "backlog_12m":
        return [(b - f) * p / 100 for b, f, p in zip(backlog["backlog_usd_b"], backlog["fsa_usd_b"],
                                                      backlog["next_12m_pct_of_ex_fsa"])]
    if reads == "backlog_total":
        return list(backlog["backlog_usd_b"])
    raise KeyError(reads)


def line_value(source: dict, line: dict) -> float | None:
    if line.get("period") and quarter_order(line["period"]) != quarter_order(source["periods"][-1]):
        return None
    values = history(source, line["reads"])
    run = line.get("consecutive", 1)
    if run > 1:
        recent = values[-run:]
        return max(recent) if line["trigger"] in ("<", "≤") else min(recent)
    return values[-1]


def line_outcome(line: dict, value: float | None) -> str:
    if value is None:
        return "未到期"
    hit = COMPARE[line["trigger"]](value, line["threshold"])
    return (GOOD if hit == (line["kind"] == "hurdle") else BAD)[line["kind"]]


def line_headroom(line: dict, value: float) -> float:
    upward = line["trigger"] in (">", "≥")
    safe_up = upward if line["kind"] == "hurdle" else not upward
    return headroom("up" if safe_up else "down", line["threshold"], value)


def check_stand_ins(test: unittest.TestCase, source: dict, judged: list, rows: list) -> None:
    """A full-year margin line is read on the year to date until the fiscal year's last
    quarter, and the drawer says so; on the fourth quarter the reading is the year."""
    year_open = not source["fiscal_labels"][-1].endswith("Q4")
    for (entry, value), row in zip(sorted(judged, key=lambda p: p[0]["row"]), rows):
        if entry["reads"] == "fy_margin" and value is not None:
            test.assertEqual("年初至今" in row[3], year_open, row)
            test.assertIn(f"{value:.1f}%", row[3], row)


def check_closure(test: unittest.TestCase, source: dict, payload: dict) -> None:
    """Section one's follow-up chart and drawer table against the note's record of §0."""
    note = source["_checks"]["note"]["closure"]
    items = source["followup_closure"]["items"]
    settled = next(s for s in payload["sections"] if s["id"] == "settled")["exhibits"]
    chart = settled[0]
    test.assertEqual(chart["kind"], "bars_labeled")
    test.assertTrue(chart["title"].startswith(f"上季 {note['total']} 条待验证问题："), chart["title"])
    test.assertEqual(dict(zip(chart["xlabels"], chart["values"])), note["counts"])
    test.assertEqual(len(items), note["total"])
    test.assertEqual([item["verdict_text"] for item in items], note["verdicts_verbatim"])
    table = next(t for t in payload["tables"] if t["title"] == f"上季 {note['total']} 条待验证问题与本季判定")
    test.assertEqual([row[2] for row in table["rows"]], note["verdicts_verbatim"])


def check_prior_lines(test: unittest.TestCase, source: dict, payload: dict) -> None:
    """Last quarter's §8 lines: block, overview, charts and table against the note.

    Every reading is recomputed here from the series, so this holds on any
    quarter a roll produces: nothing in it names a quarter or a value.
    """
    note = source["_checks"]["note"]
    block = source["prior_kpi_settlement"]
    test.assertEqual(block["rows"], note["prior_rows"])
    test.assertEqual(
        [(e["row"], e["metric"], e["kind"], e["trigger"], e["threshold"], e.get("consecutive", 1))
         for e in block["quantified"]],
        [(t["row"], t["metric"], t["kind"], t["trigger"], t["threshold"], t.get("consecutive", 1))
         for t in note["prior_thresholds"]])
    test.assertEqual(sorted(str(item["row"]) for item in block.get("unsettled", [])),
                     sorted(note.get("prior_unquantified_rows", {})))
    for entry in block["quantified"]:
        test.assertNotIn("current", entry)
        test.assertNotIn("actual", entry)
    judged = [(entry, line_value(source, entry)) for entry in block["quantified"]]
    table = next(t for t in payload["tables"] if t["title"].startswith("上季（") and "阈值与本季读数" in t["title"])
    rows = [row for row in table["rows"] if row[1] != "—"]
    test.assertEqual([row[5] for row in rows],
                     [line_outcome(entry, value) for entry, value in sorted(judged, key=lambda p: p[0]["row"])])
    check_stand_ins(test, source, judged, rows)
    settled = next(s for s in payload["sections"] if s["id"] == "settled")["exhibits"]
    overview = next(ex for ex in settled if ex["kind"] == "diverging_bars" and ex["title"].startswith("上季"))
    bars = [(entry, value) for entry, value in judged
            if line_outcome(entry, value) in ("达到", "没到", "守住", "越线") and entry["threshold"] != 0]
    test.assertTrue(overview["title"].startswith(f"上季 {len(bars)} 条量化阈值："), overview["title"])
    test.assertEqual(overview["values"], [round(line_headroom(entry, value), 1) + 0.0 for entry, value in bars])
    charts = [ex for ex in settled if ex["kind"] == "lines" and "上季" in ex["title"]]
    for entry, value in judged:
        flat = [chart for chart in charts for series in chart["series"]
                if series["name"].startswith("上季") and f" {entry['trigger']} " in series["name"]
                and all(v == entry["threshold"] for v in series["values"])]
        if entry["threshold"] == 0 and not flat:
            test.assertIn(f"「{entry['metric']} {entry['trigger']}", overview["note"], entry["id"])
            continue
        test.assertEqual(len(flat), 1, entry["id"])
        test.assertIn(line_outcome(entry, value), flat[0]["title"], entry["id"])
        test.assertAlmostEqual(flat[0]["series"][0]["values"][-1], history(source, entry["reads"])[-1], places=4)


def check_next_lines(test: unittest.TestCase, source: dict, payload: dict) -> None:
    """This quarter's §8 lines: block, overview, charts and table against the note."""
    note = source["_checks"]["note"]
    block = source["next_kpi"]
    test.assertEqual(block["rows"], note["next_rows"])
    test.assertEqual(
        [(e["row"], e["metric"], e["kind"], e["trigger"], e["threshold"], e.get("period")) for e in block["quantified"]],
        [(t["row"], t["metric"], t["kind"], t["trigger"], t["threshold"], t.get("period"))
         for t in note["next_thresholds"]])
    test.assertEqual(sorted({str(item["row"]) for item in block.get("not_drawn", [])}),
                     sorted(note.get("next_unquantified_rows", {})))
    for entry in block["quantified"]:
        test.assertNotIn("current", entry)
        test.assertNotIn("actual", entry)
    judged = [(entry, line_value(source, entry)) for entry in block["quantified"]]
    table = next(t for t in payload["tables"] if t["title"] == "下季阈值与本季读数（原单位）")
    rows = [row for row in table["rows"] if row[1] != "—"]
    test.assertEqual([row[5] for row in rows],
                     [line_outcome(entry, value) for entry, value in sorted(judged, key=lambda p: p[0]["row"])])
    check_stand_ins(test, source, judged, rows)
    section = next(s for s in payload["sections"] if s["id"] == "next_quarter")["exhibits"]
    overview = section[0]
    bars = [(entry, value) for entry, value in judged
            if line_outcome(entry, value) in ("达到", "没到", "守住", "越线") and entry["threshold"] != 0]
    test.assertEqual(overview["kind"], "diverging_bars")
    test.assertTrue(overview["title"].startswith(f"下季 {len(bars)} 条量化阈值："), overview["title"])
    # the lines are due next quarter: their 没到 / 守住 here is where the reading stands now
    test.assertIn("按本季读数", overview["title"])
    test.assertEqual(overview["values"], [round(line_headroom(entry, value), 1) + 0.0 for entry, value in bars])
    charts = section[1:]
    for chart in charts:
        test.assertEqual(chart["kind"], "lines")
        test.assertRegex(chart["title"], r"：下季.*，当前 ")
    for entry, value in judged:
        flat = [chart for chart in charts for series in chart["series"]
                if series["name"].startswith("下季") and f" {entry['trigger']} " in series["name"]
                and all(v == entry["threshold"] for v in series["values"])]
        if entry["threshold"] == 0 and not flat:
            test.assertIn(f"「{entry['metric']} {entry['trigger']}", overview["note"], entry["id"])
            continue
        test.assertEqual(len(flat), 1, entry["id"])
        test.assertAlmostEqual(flat[0]["series"][0]["values"][-1], history(source, entry["reads"])[-1], places=4)


class SnpsDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "snps.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]
        cls.by_section = {
            section["id"]: section["exhibits"] for section in cls.payload["sections"]
        }
        cls.record = cls.source["quarterly_guidance_history"]

    # ── the four sections ────────────────────────────────────────────────────
    def test_the_page_has_the_site_s_four_sections_in_order(self) -> None:
        self.assertEqual(
            [(section["id"], section["title"]) for section in self.payload["sections"]],
            [("settled", "一、上季跟踪指标兑现了吗"), ("quarter_highlights", "二、本季重点"),
             ("next_quarter", "三、下季要跟踪什么"), ("routine", "四、长期常规跟踪")])
        for section in self.payload["sections"]:
            with self.subTest(section=section["id"]):
                self.assertTrue(section["exhibits"])
                self.assertTrue(section["description"].strip())
        self.assertIn("本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列",
                      self.payload["notes"][0])

    def test_this_quarter_s_readings_sit_in_section_two(self) -> None:
        """The market-expectation panel and the backlog chart read this quarter.

        Both used to sit elsewhere: the expectation panel in section one, among
        what was set last quarter, and the backlog chart -- whose title is this
        quarter's reading, three declines since the fiscal year-end -- among the
        long-run series of section four.
        """
        legends = {section["id"]: [ex.get("legend") for ex in section["exhibits"]]
                   for section in self.payload["sections"]}
        self.assertIn("较对照的幅度", legends["quarter_highlights"])
        self.assertNotIn("较对照的幅度", legends["settled"])
        backlog = [section["id"] for section in self.payload["sections"] for ex in section["exhibits"]
                   if any(s["name"].startswith("backlog（含 FSA）") for s in ex.get("series", []))]
        self.assertEqual(backlog, ["quarter_highlights"])

    # ── shape ────────────────────────────────────────────────────────────────
    def test_the_quarterly_margin_guidance_is_not_the_full_year_one(self) -> None:
        """The two midpoints in the release are the fiscal year's, not Q4's.

        They used to sit in `guidance.q3_2026_next_quarter`, and the page's
        guidance table printed one of them as the next quarter's margin: "about
        41.5%", "-0.1pp versus this quarter". Both are wrong in a way nothing
        looked broken by, because the *values* are right -- they are simply the
        wrong period's. Midpoint arithmetic settles it without reading the HTML:
        the full year implies 41.48% and 10.40%, matching the stored figures to
        the digit, while the fourth quarter implies 42.66% and 11.45%.
        """
        guidance = self.source["guidance"]
        quarter = guidance["next_quarter"]
        year = guidance["full_year"]["current"]
        self.assertNotIn("non_gaap_operating_margin_midpoint_pct", quarter)
        self.assertNotIn("gaap_operating_margin_midpoint_pct", quarter)

        def midpoint(values):
            return sum(values) / 2

        year_revenue = midpoint(year["revenue_usd_m"])
        self.assertAlmostEqual(
            (year_revenue - midpoint(year["non_gaap_expenses_usd_m"])) / year_revenue * 100,
            year["non_gaap_operating_margin_midpoint_pct"], places=1)
        self.assertAlmostEqual(
            (year_revenue - midpoint(year["gaap_expenses_usd_m"])) / year_revenue * 100,
            year["gaap_operating_margin_midpoint_pct"], places=1)

        quarter_revenue = midpoint(quarter["revenue_usd_m"])
        implied = ((quarter_revenue - midpoint(quarter["non_gaap_expenses_usd_m"]))
                   / quarter_revenue * 100)
        self.assertGreater(implied, year["non_gaap_operating_margin_midpoint_pct"] + 1.0,
                           "the quarter and the year are more than a point apart, "
                           "which is why filing one under the other was visible "
                           "on the page")
        table = next(t for t in self.payload["tables"] if "指引" in t["title"])
        row = next(r for r in table["rows"] if r[0] == "non-GAAP 营业利润率")
        self.assertIn(f"{implied:.2f}%", row[4])
        self.assertNotIn("41.5%", row[4])

    def test_the_page_does_not_say_ansys_revenue_is_unprinted(self) -> None:
        """Twice the page gave a reason for not drawing EDA without Ansys, and twice
        the filings said otherwise.

        First "the company has never broken out Ansys revenue in any filing";
        then, narrowed, "no dollar figure is printed, and the product-group
        percentages exist only for the few quarters since the merger". The 10-Q
        MD&A prints Ansys's contribution in dollars (US$885.6M for fiscal 2026
        Q1, US$652.4M for Q2, the US$622.2M year-on-year increase for Q3), the
        10-K prints fiscal 2025's US$756.6M, and the product-group table has been
        in every 10-Q and 10-K since fiscal 2019 -- only its Ansys row is new. So
        the page now draws the split, and must not print either reason again.
        """
        text = published_text(self.payload)
        for stale in ("公司不按季印 Ansys", "不印 Ansys 的季度收入", "只覆盖并入之后的几季", "拉不出一条长序列",
                      "全页唯一能把并购与原生分开", "唯一一次在申报文件里给该会计项标价", "那句话太宽了"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, text)
        block = self.source["ansys_revenue"]
        for quarter, amount in zip(block["quarters"], block["printed_usd_m"]):
            if amount is not None:
                self.assertIn(f"US${amount:,.1f}M", " ".join(self.payload["notes"]), quarter)
        split = next(ex for ex in self.by_section["quarter_highlights"] if ex["title"].startswith("剔除 Ansys"))
        ansys = ansys_by_quarter(self.source)
        self.assertEqual([None if v is None else round(v, 6) for v in split["groups"][1]["values"]],
                         [round(ansys[p], 6) if p in ansys else None for p in self.source["periods"]])
        self.assertAlmostEqual(split["groups"][0]["values"][-1], history(self.source, "eda_resid")[-1], places=4)

    def test_the_window_is_eight_quarters_and_complete(self) -> None:
        length = len(self.source["periods"])
        self.assertGreaterEqual(length, 8)
        self.assertEqual(len(self.source["period_ends"]), length)
        self.assertEqual(len(self.source["fiscal_labels"]), length)
        for group in ("financials", "segments_usd_m"):
            for name, values in self.source[group].items():
                if not isinstance(values, list):
                    continue
                self.assertEqual(len(values), length, f"{group}.{name}")
                self.assertTrue(
                    all(value is not None and math.isfinite(value) for value in values),
                    f"{group}.{name}",
                )

    def test_the_guided_record_is_one_row_per_quarter(self) -> None:
        length = len(self.record["quarters"])
        self.assertGreaterEqual(length, 43)
        for name, values in self.record.items():
            if not isinstance(values, list):
                continue
            self.assertEqual(len(values), length, name)
        # The record ends on a quarter that has been guided but not reported.
        self.assertIsNone(self.record["actual_revenue_usd_m"][-1])
        self.assertTrue(all(value is not None
                            for value in self.record["actual_revenue_usd_m"][:-1]))
        # ... and that quarter is the one after the page's.
        last = self.source["periods"][-1]
        following = quarter_order(last) + 1
        self.assertEqual(quarter_order(self.record["quarters"][-1]), following)
        self.assertEqual(self.record["quarters"][-1], self.source["guidance"]["next_quarter"]["period"])
        self.assertEqual(self.record["fiscal_labels"][-1],
                         self.source["guidance"]["next_quarter"]["fiscal_label"])

    def test_quarters_are_contiguous_calendar_labels(self) -> None:
        for quarters in (self.record["quarters"], self.source["periods"],
                         self.source["backlog"]["quarters"],
                         self.source["disaggregation_usd_m"]["quarters"]):
            numbers = []
            for label in quarters:
                quarter, year = label.split()
                numbers.append(int(year) * 4 + int(quarter[1]) - 1)
            self.assertEqual(numbers, list(range(numbers[0], numbers[0] + len(numbers))),
                             quarters[:3])

    def test_the_window_is_the_tail_of_the_guided_record(self) -> None:
        self.assertEqual(self.record["quarters"][-9:-1], self.source["periods"])

    def test_fiscal_labels_map_to_the_calendar_labels_the_page_publishes(self) -> None:
        """FY Q1 → prior-year Q4, Q2 → Q1, Q3 → Q2, Q4 → Q3.

        Getting this backwards would silently shift every SNPS row of the
        cross-company capex table by one quarter, which is exactly the failure
        the shared convention exists to prevent.
        """
        shift = {"1": (-1, "Q4"), "2": (0, "Q1"), "3": (0, "Q2"), "4": (0, "Q3")}
        for fiscal, calendar in zip(self.record["fiscal_labels"], self.record["quarters"]):
            year, number = int(fiscal[2:6]), fiscal[-1]
            offset, quarter = shift[number]
            self.assertEqual(calendar, f"{quarter} {year + offset}", fiscal)
        checks = self.source["_checks"]
        self.assertEqual(self.source["fiscal_labels"][-1], checks["fiscal_label"].replace(" ", ""))
        self.assertEqual(self.source["periods"][-1], checks["period"])
        self.assertEqual(self.source["period_ends"][-1], checks["period_end"])

    # ── identities the filings have to satisfy ───────────────────────────────
    def test_segment_revenue_sums_to_total_revenue(self) -> None:
        segments = self.source["segments_usd_m"]
        for index, period in enumerate(self.source["periods"]):
            self.assertAlmostEqual(
                segments["design_automation_revenue"][index]
                + segments["design_ip_revenue"][index],
                self.source["financials"]["revenue_usd_m"][index],
                places=3,
                msg=period,
            )

    def test_geography_and_revenue_type_each_sum_to_total_revenue(self) -> None:
        disagg = self.source["disaggregation_usd_m"]
        # The two earliest quarters were recovered from a later filing's
        # comparative columns, which carry the geography split but not the
        # revenue-type one. So the two identities are checkable over different
        # spans, and both spans are asserted -- otherwise dropping a leg would
        # look like the identity still holding everywhere it is checked.
        geography = revenue_type = 0
        for index, period in enumerate(disagg["quarters"]):
            total = disagg["revenue_usd_m"][index]
            geo = [disagg[key][index]
                   for key in ("united_states", "europe", "korea", "china", "other")]
            if None not in geo:
                geography += 1
                self.assertAlmostEqual(sum(geo), total, places=3,
                                       msg=f"geography {period}")
            legs = [disagg[key][index]
                    for key in ("time_based", "upfront", "maintenance_and_service")]
            if None not in legs:
                revenue_type += 1
                self.assertAlmostEqual(sum(legs), total, places=3,
                                       msg=f"revenue type {period}")
        self.assertEqual(geography, len(disagg["quarters"]))
        self.assertEqual(revenue_type, len(disagg["quarters"]) - 2)

    def test_the_overlapping_quarters_agree_across_the_two_windows(self) -> None:
        """The disaggregation series and the eight-quarter window are separate reads."""
        disagg = self.source["disaggregation_usd_m"]
        for index, period in enumerate(self.source["periods"]):
            position = disagg["quarters"].index(period)
            self.assertAlmostEqual(
                disagg["revenue_usd_m"][position],
                self.source["financials"]["revenue_usd_m"][index],
                places=3, msg=period)

    def test_operating_margins_are_the_ratio_they_claim_to_be(self) -> None:
        financials = self.source["financials"]
        for index, period in enumerate(self.source["periods"]):
            revenue = financials["revenue_usd_m"][index]
            self.assertAlmostEqual(
                financials["gaap_operating_margin_pct"][index],
                financials["gaap_operating_income_usd_m"][index] / revenue * 100,
                places=4, msg=period)
            self.assertAlmostEqual(
                financials["non_gaap_operating_margin_pct"][index],
                financials["non_gaap_operating_income_usd_m"][index] / revenue * 100,
                places=4, msg=period)

    def test_non_gaap_operating_income_exceeds_gaap_every_quarter(self) -> None:
        financials = self.source["financials"]
        for index, period in enumerate(self.source["periods"]):
            self.assertGreater(
                financials["non_gaap_operating_income_usd_m"][index],
                financials["gaap_operating_income_usd_m"][index], period)

    def test_year_over_year_uses_the_restated_continuing_operations_base(self) -> None:
        """The first four YoY readings need a base outside the window.

        Using the as-originally-reported base instead would overstate the
        year-ago quarter by the Software Integrity revenue and understate every
        one of those four growth rates.
        """
        financials = self.source["financials"]
        base = {"Q3 2024": 1467.383, "Q4 2024": 1510.989,
                "Q1 2025": 1454.712, "Q2 2025": 1525.749}
        for index, period in enumerate(self.source["periods"]):
            revenue = financials["revenue_usd_m"][index]
            prior = base.get(period) or financials["revenue_usd_m"][index - 4]
            self.assertAlmostEqual(financials["revenue_yoy_pct"][index],
                                   (revenue / prior - 1) * 100, places=3, msg=period)

    # ── the guidance table reconciles to itself ──────────────────────────────
    def test_the_guided_eps_midpoint_is_implied_by_the_other_five_guided_lines(self) -> None:
        """(revenue − expenses + other) × (1 − tax) ÷ shares reproduces guided EPS.

        This is what lets the page treat "guided revenue minus guided expenses"
        as an operating income the company itself stands behind.

        It reproduces it *approximately*, and how approximately turns out to
        depend on the era — which is only visible now that the record reaches
        2016. On the 24 quarters this file used to cover, the reconstruction was
        within 2.2% of the printed EPS midpoint every time. Across the 19
        backfilled quarters it is within 8.4%, and the median is four times
        looser (2.1% against 0.5%). Q3 2018 is the extreme: every input matches
        the 2018-08-22 release verbatim -- revenue $774-804M, non-GAAP expenses
        $655-665M, other income $(3)-(1)M, tax 13%, shares 153-156M, non-GAAP
        EPS $0.76-0.80 -- and the midpoints still only reconstruct $0.715
        against a printed $0.78. The company does not compute its EPS midpoint
        from its own range midpoints, and the gap shows up most where the EPS
        base is smallest.

        So this is asserted per era rather than with one tolerance wide enough
        to cover both, which would have stopped saying anything about the recent
        quarters. Widening a bound until it passes is how a gate quietly retires.
        """
        record = self.record
        gaps, relative = [], []
        for index in pinned(record):
            revenue = (record["guide_revenue_lo_usd_m"][index]
                       + record["guide_revenue_hi_usd_m"][index]) / 2
            expenses = (record["guide_non_gaap_expenses_lo_usd_m"][index]
                        + record["guide_non_gaap_expenses_hi_usd_m"][index]) / 2
            other = (record["guide_non_gaap_other_income_lo_usd_m"][index]
                     + record["guide_non_gaap_other_income_hi_usd_m"][index]) / 2
            shares = (record["guide_shares_lo_m"][index]
                      + record["guide_shares_hi_m"][index]) / 2
            tax = record["guide_non_gaap_tax_rate_pct"][index] / 100
            printed = (record["guide_non_gaap_eps_lo_usd"][index]
                       + record["guide_non_gaap_eps_hi_usd"][index]) / 2
            gap = abs((revenue - expenses + other) * (1 - tax) / shares - printed)
            gaps.append(gap)
            relative.append(gap / printed * 100)

        # The era boundary is where this file's record used to begin.
        split = record["quarters"].index("Q4 2020")
        self.assertEqual(split, 19)
        early, recent = relative[:split], relative[split:]

        # Recent quarters keep the tight bound the original assertion had.
        self.assertLessEqual(max(recent), 2.5, "the modern reconstruction slipped")
        self.assertLessEqual(max(early), 9.0, "the early reconstruction slipped")
        self.assertLessEqual(max(gaps), 0.07)
        self.assertGreaterEqual(sum(1 for gap in gaps if gap <= 0.02), 26)

        # The difference between the eras is itself the finding, so it is
        # asserted -- but counted, not maximised. A max-based version of this
        # passed even after the single worst early quarter was smoothed flat
        # (mutation-checked: it survived by 0.11pp, which is not an assertion,
        # it is a coincidence). Counting how many quarters clear the threshold
        # makes any one of them being quietly fixed turn this red.
        loose = 2.0
        self.assertEqual(sum(1 for value in early if value > loose), 10)
        self.assertEqual(sum(1 for value in recent if value > loose), 2)
        self.assertGreater(_median(early), _median(recent) * 2)

    def test_the_two_legs_add_up_to_the_operating_income_beat(self) -> None:
        """Revenue leg + expense leg = actual non-GAAP OI − guided-implied OI, exactly."""
        record = self.record
        for index, quarter in enumerate(record["quarters"]):
            actual_revenue = record["actual_revenue_usd_m"][index]
            if actual_revenue is None:
                continue
            actual_income = record["actual_non_gaap_operating_income_usd_m"][index]
            # Reported and decomposable are different questions: Synopsys's
            # reconciliation carried no operating-income line before the release
            # of 2019-02-20, so eleven reported quarters have no leg split.
            if actual_income is None:
                continue
            guided_revenue = (record["guide_revenue_lo_usd_m"][index]
                              + record["guide_revenue_hi_usd_m"][index]) / 2
            guided_expense = (record["guide_non_gaap_expenses_lo_usd_m"][index]
                              + record["guide_non_gaap_expenses_hi_usd_m"][index]) / 2
            revenue_leg = actual_revenue - guided_revenue
            expense_leg = guided_expense - (actual_revenue - actual_income)
            self.assertAlmostEqual(revenue_leg + expense_leg,
                                   actual_income - (guided_revenue - guided_expense),
                                   places=6, msg=quarter)

    def test_the_guidance_tally_the_page_publishes_is_the_one_in_the_data(self) -> None:
        record = self.record
        def tally(low, high, actual):
            above = inside = below = 0
            for lo, hi, value in zip(low, high, actual):
                if value is None:
                    continue
                if value > hi:
                    above += 1
                elif value < lo:
                    below += 1
                else:
                    inside += 1
            return above, inside, below

        keep = pinned(record)
        def cut(key):
            return [record[key][i] for i in keep]
        self.assertEqual(tally(cut("guide_revenue_lo_usd_m"), cut("guide_revenue_hi_usd_m"),
                               cut("actual_revenue_usd_m")), (17, 23, 2))
        self.assertEqual(tally(cut("guide_non_gaap_eps_lo_usd"), cut("guide_non_gaap_eps_hi_usd"),
                               cut("actual_non_gaap_eps_usd")), (32, 8, 2))
        # What the page prints is the whole record, recounted.
        revenue = tally(record["guide_revenue_lo_usd_m"], record["guide_revenue_hi_usd_m"],
                        record["actual_revenue_usd_m"])
        eps = tally(record["guide_non_gaap_eps_lo_usd"], record["guide_non_gaap_eps_hi_usd"],
                    record["actual_non_gaap_eps_usd"])
        titles = {exhibit["title"] for exhibit in self.by_section["settled"]}
        self.assertTrue(any(f"{revenue[1]} 季落在区间内" in title for title in titles), titles)
        self.assertTrue(any(f"{eps[0]} 季超出上限、{eps[1]} 季落在区间内" in title for title in titles), titles)
        finished = sum(revenue)
        # The side-by-side reading of the two records sits with the EPS band; the
        # brief now leads with the quarter, not the ten-year record.
        band = next(ex for ex in self.by_section["settled"] if ex["title"].startswith("non-GAAP EPS："))
        self.assertIn(f"收入指引 {finished} 季里 {revenue[1]} 季被<b>命中</b>，EPS 指引却有 {eps[0]} 季被<b>穿透</b>",
                      band["note"])
        self.assertNotIn("<span>记录</span>", self.payload["brief"])

    def test_the_one_basis_break_is_marked_and_explained(self) -> None:
        """Q1 2024 was guided with Software Integrity in and reported with it out."""
        record = self.record
        index = record["basis_break_at"]
        self.assertEqual(record["fiscal_labels"][index], "FY2024Q2")
        self.assertEqual(record["quarters"][index], "Q1 2024")
        actual = record["actual_revenue_usd_m"][index]
        low = record["guide_revenue_lo_usd_m"][index]
        high = record["guide_revenue_hi_usd_m"][index]
        self.assertLess(actual, low)
        # The 10-Q's discontinued-operations note put Software Integrity's
        # three months at 126.421 -- the segment table cannot supply it, because
        # that table had already removed the business from every period. Adding
        # it back lands inside the range the company had guided, which is what
        # licenses the page to call the apparent miss a basis change.
        addback = record["basis_break_addback_usd_m"]
        self.assertAlmostEqual(addback, 126.421, places=3)
        self.assertTrue(low <= actual + addback <= high,
                        f"{actual} + {addback} should be inside {low}-{high}")
        marked = [exhibit for exhibit in self.by_section["settled"]
                  if exhibit.get("break_at") is not None]
        self.assertEqual({exhibit["break_at"] for exhibit in marked}, {index})
        self.assertGreaterEqual(len(marked), 2)

    def test_the_only_other_revenue_miss_is_the_ansys_close_quarter(self) -> None:
        record = self.record
        misses = [record["quarters"][index]
                  for index, value in enumerate(record["actual_revenue_usd_m"])
                  if value is not None and value < record["guide_revenue_lo_usd_m"][index]
                  and index in pinned(record)]
        self.assertEqual(misses, ["Q1 2024", "Q2 2025"])
        # That quarter is also the only one whose share count came in above the
        # guided range, because the merger issued stock inside the quarter.
        above = [record["quarters"][index]
                 for index, value in enumerate(record["actual_diluted_shares_m"])
                 if value is not None and value > record["guide_shares_hi_m"][index]
                 and index in pinned(record)]
        self.assertEqual(above, ["Q2 2025"])

    # ── derived series the page publishes ────────────────────────────────────
    def test_twelve_month_backlog_uses_the_filing_s_own_ex_fsa_base(self) -> None:
        """The filed percentage applies to backlog *excluding* the FSA commitments."""
        backlog = self.source["backlog"]
        checks = self.source["_checks"]
        latest = ((checks["backlog_usd_bn"] - checks["fsa_usd_bn"])
                  * checks["next_12m_pct_of_ex_fsa"] / 100)
        self.assertAlmostEqual(history(self.source, "backlog_12m")[-1], latest, places=6)
        entries = [item for item in self.source["next_kpi"]["quantified"] if item["reads"] == "backlog_12m"]
        self.assertTrue(entries)
        table = next(t for t in self.payload["tables"] if t["title"].startswith("下季阈值"))
        for entry in entries:
            self.assertNotIn("current", entry, "the current value is computed, not typed")
            row = next(r for r in table["rows"] if r[1].startswith(f"{entry['metric']} {entry['trigger']} "))
            self.assertEqual(row[3], f"US${latest:.2f}B")
        for index, quarter in enumerate(backlog["quarters"]):
            self.assertLess(backlog["fsa_usd_b"][index], backlog["backlog_usd_b"][index], quarter)

    def test_long_history_amortization_is_the_sum_of_the_two_income_statement_lines(self) -> None:
        long = self.source["long_history"]
        self.assertEqual(len(long["fiscal_years"]), 10)
        self.assertEqual(long["fiscal_years"][0], "FY2016")
        self.assertEqual(long["fiscal_years"][-1], "FY2025")
        # FY2016 read straight off that year's 10-K: 102.118 in cost of revenue
        # and 27.507 in operating expenses, against revenue of 2,422.532.
        self.assertAlmostEqual(long["amortization_cost_of_revenue_usd_m"][0], 102.118, places=3)
        self.assertAlmostEqual(long["amortization_opex_usd_m"][0], 27.507, places=3)
        self.assertAlmostEqual(long["revenue_usd_m"][0], 2422.532, places=3)
        # The restated column exists only for the years a later 10-K recast.
        recast = {year for year, value
                  in zip(long["fiscal_years"], long["restated_revenue_usd_m"])
                  if value is not None}
        self.assertEqual(recast, {"FY2017", "FY2018", "FY2022", "FY2023", "FY2024"})
        self.assertAlmostEqual(long["restated_revenue_usd_m"][6], 4615.714, places=3)
        self.assertAlmostEqual(long["restated_revenue_usd_m"][7], 5318.014, places=3)

    def test_the_buyback_series_has_the_two_zero_years_the_page_claims(self) -> None:
        long = self.source["long_history"]
        zero = [year for year, value
                in zip(long["fiscal_years"], long["share_repurchases_usd_m"]) if value == 0]
        self.assertEqual(zero, ["FY2024", "FY2025"])
        self.assertTrue(all(value > 0 for value in long["share_repurchases_usd_m"][:8]))

    def test_the_fy2026_guidance_raise_splits_the_way_the_page_says(self) -> None:
        footnote = self.source["guidance"]["full_year_revenue_footnote"]
        mid = [(lo + hi) / 2 for lo, hi
               in zip(footnote["revenue_lo_usd_m"], footnote["revenue_hi_usd_m"])]
        ansys = footnote["expected_ansys_revenue_usd_m"]
        core = [total - value for total, value in zip(mid, ansys)]
        if footnote["fiscal_year"] == "FY2026":
            self.assertAlmostEqual(mid[-1] - mid[0], 105.0, places=6)
            self.assertAlmostEqual(ansys[-1] - ansys[0], 80.0, places=6)
            self.assertAlmostEqual(core[-1] - core[0], 25.0, places=6)
        # The title counts raises, not vintages: four FY2026 releases carried
        # the guidance, and only two of them raised its midpoint (February
        # repeated December's range). The page used to say 「四次上调」.
        raises = sum(1 for a, b in zip(mid, mid[1:]) if b > a)
        chart = next(ex for ex in self.by_section["quarter_highlights"] if "收入指引" in ex["title"])
        self.assertIn(f"全年累计{cn_count(raises)}次上调共 US${mid[-1] - mid[0]:,.0f}M", chart["title"])
        self.assertGreater(mid[-1], mid[0], "「上调」 carries the sign: the page prints the size")
        self.assertEqual(chart["xlabels"], footnote["releases"])
        # The title leads with this quarter's revision, split the way the footnote splits it.
        self.assertTrue(chart["title"].startswith(
            f"{footnote['fiscal_year']} 收入指引本季上调 US${mid[-1] - mid[-2]:,.0f}M：Ansys 脚注 "
            f"+US${ansys[-1] - ansys[-2]:,.0f}M、其余业务 +US${core[-1] - core[-2]:,.0f}M"), chart["title"])

    # ── thresholds ───────────────────────────────────────────────────────────
    def test_this_quarters_lines_are_watched_as_the_analysis_wrote_them(self) -> None:
        check_next_lines(self, self.source, self.payload)
        self.assertEqual(len(self.source["next_kpi"].get("followups", [])),
                         self.source["_checks"]["note"]["followups_total"])

    def test_section_three_carries_no_line_the_analysis_did_not_write(self) -> None:
        """Two of the five lines the page used to watch were not in section 8.

        The share count's 194M was the company's own guided ceiling, and the FSA
        share's 18% came from the analysis' insight section and follow-up list,
        not its tracking table; the margin line read the quarter against a
        threshold the analysis set on the fiscal year. Every line is now one
        the note records from section 8, and nothing is typed beside it.
        """
        metrics = {entry["metric"] for entry in self.source["next_kpi"]["quantified"]}
        for gone in ("摊薄股数", "FSA 占 backlog"):
            self.assertNotIn(gone, metrics)
        margin = [e for e in self.source["next_kpi"]["quantified"] if "营业利润率" in e["metric"]]
        self.assertTrue(margin)
        self.assertTrue(all(e["reads"] == "fy_margin" for e in margin))
        self.assertNotIn("取自公司自己的指引上限", published_text(self.payload))

    def test_what_section_three_cannot_draw_is_named_with_its_reason(self) -> None:
        kpi = self.source["next_kpi"]
        section = next(s for s in self.payload["sections"] if s["id"] == "next_quarter")
        overview = section["exhibits"][0]
        for item in kpi.get("not_drawn", []):
            with self.subTest(row=item["row"]):
                self.assertIn(item["text"], overview["note"])
                self.assertIn(item["why"], overview["note"])
                self.assertIn(item["short"], section["description"])
        waiting = [e for e in kpi["quantified"] if e.get("period")]
        for entry in waiting:
            self.assertIn(f"「{entry['metric']} {entry['trigger']}", overview["note"])
        if waiting:
            self.assertIn(f"{cn_count(len(waiting))}条读的是下季本身的数", section["description"])
        table = next(t for t in self.payload["tables"] if t["title"].startswith("下季待验证问题"))
        self.assertEqual([row[1] for row in table["rows"]], [item["question"] for item in kpi["followups"]])

    # ── payload hygiene ──────────────────────────────────────────────────────
    def test_exhibits_are_numbered_in_render_order_and_refs_resolve(self) -> None:
        numbers = [exhibit["n"] for exhibit in self.exhibits]
        self.assertEqual(numbers, list(range(2, 2 + len(self.exhibits))))
        for exhibit in self.exhibits:
            self.assertNotIn("ref", exhibit)
            for field in ("title", "note", "src_extra", "annot"):
                text = exhibit.get(field)
                if isinstance(text, str):
                    self.assertNotRegex(text, r"\{EX_[A-Z_]+\}", f"{exhibit['n']} {field}")

    def test_tables_are_numbered_after_the_exhibits(self) -> None:
        first = len(self.exhibits) + 2
        self.assertEqual([table["n"] for table in self.payload["tables"]],
                         list(range(first, first + len(self.payload["tables"]))))
        for table in self.payload["tables"]:
            for row in table["rows"]:
                self.assertEqual(len(row), len(table["headers"]), table["title"])

    def test_every_exhibit_carries_a_note_and_a_source_line(self) -> None:
        for exhibit in self.exhibits:
            self.assertTrue(exhibit.get("note"), exhibit["title"])
            self.assertTrue(exhibit.get("src_extra"), exhibit["title"])

    def test_the_published_payload_matches_a_fresh_build(self) -> None:
        """`python3 build/all.py && git status` stays the drift check."""
        published = js_payload(ROOT / "data" / "snps.js", "window.DASH")
        self.assertEqual(published, self.payload)

    def test_the_page_declares_the_fiscal_year_convention_in_its_subtitle(self) -> None:
        checks = self.source["_checks"]
        self.assertIn(f"本页 {checks['period']} 即公司所称 {checks['fiscal_label']}", self.payload["subtitle"])
        self.assertIn(checks["period"], self.payload["title"])
        self.assertEqual(self.payload["latest"]["period_end"], checks["period_end"])
        self.assertEqual(self.payload["latest"]["release_date"], checks["release_date"])

    def test_market_expectation_is_labelled_and_dated_but_unattributed(self) -> None:
        expectation = self.source["market_expectation"]
        self.assertIn(self.source["latest"]["release_date"], expectation["as_of"])
        self.assertIn("不具名", expectation["basis"])
        joined = json.dumps(self.payload, ensure_ascii=False)
        self.assertIn("市场预期", joined)
        # No broker or vendor may be named anywhere in the payload. The words
        # 评级 / 目标价 themselves are not banned: they appear in the page's own
        # boundary statement saying it publishes neither.
        for named in ("Baird", "Wolfe", "Needham", "Morgan Stanley", "Citi",
                      "Mizuho", "Zacks", "Benzinga"):
            self.assertNotIn(named, joined)
        for exhibit in self.exhibits:
            self.assertNotIn("目标价", exhibit.get("note", ""))
            self.assertNotIn("评级", exhibit.get("note", ""))

    def test_the_roster_carries_snps_with_the_payload_s_own_labels(self) -> None:
        payloads = build_all()
        self.assertIn("snps", payloads)
        roster = roster_payload(payloads)
        entry = next(item for item in roster["items"] if item["slug"] == "snps")
        self.assertEqual(entry["latest_label"], self.payload["latest"]["disclosed_period_label"])
        self.assertEqual(entry["release_date"], self.payload["latest"]["release_date"])
        self.assertEqual(entry["group"], "semiconductor_ai")

    def test_the_shell_links_the_payload_by_content_hash(self) -> None:
        """Every `?v=` in the committed shell must be that file's CURRENT digest.

        Checking only the shape of the query string is not enough, and this test
        used to do exactly that. On 2026-08-29 a commit updated `data/snps.js`
        but left `snps/index.html` out of its explicit path list, so the shell
        went on stamping the previous payload's digest. Nothing caught it: the
        renderer is correct (main() writes the payload before rendering the
        shell), the working tree was consistent, and all 201 tests passed --
        because they run after `build/all.py` has already regenerated the shell.
        Only `git status` after a build showed it, and only if you looked.

        The consequence is precisely what the fingerprint exists to prevent: the
        payload bytes changed, its URL did not, so a reader who had already
        loaded the old `data/snps.js?v=...` kept being served it from cache.
        """
        import hashlib

        shell = (ROOT / "snps" / "index.html").read_text(encoding="utf-8")
        self.assertIn("<title>SNPS Quarterly Results</title>", shell)
        sources = re.findall(r'<script src="\.\./([^"?]+)(?:\?v=([0-9a-f]+))?"', shell)
        self.assertEqual(
            [name for name, _ in sources],
            ["data/roster.js", "data/snps.js", "assets/charts.js", "assets/page.js"],
        )
        for name, digest in sources:
            with self.subTest(script=name):
                self.assertTrue(digest, f"{name} is served without a cache-busting version")
                expected = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()[: len(digest)]
                self.assertEqual(digest, expected, f"{name} carries a stale digest")

    def test_compact_period_round_trips_the_labels_the_charts_use(self) -> None:
        self.assertEqual(compact_period("Q2 2026"), "Q2'26")
        self.assertEqual(compact_period("Q4 2020"), "Q4'20")
        for exhibit in self.by_section["settled"]:
            if exhibit["kind"] == "range_band":
                self.assertTrue(all(re.fullmatch(r"Q[1-4]'\d{2}", label)
                                    for label in exhibit["xlabels"]), exhibit["title"])


class SnpsChecksTest(unittest.TestCase):
    """The page's quarter against a record keyed separately from the filings.

    `_checks` is typed once per quarter from the earnings 8-K's EX-99.1 and the
    10-Q, with the place each figure was read; the builder never reads it
    (asserted in `test_data_only_roll`). Rolling a quarter re-keys `_checks`;
    this class does not change.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "snps.json").read_text(encoding="utf-8"))
        cls.checks = cls.source["_checks"]
        cls.payload = build_payload(cls.source)
        cls.text = published_text(cls.payload)
        cls.exhibits = [ex for section in cls.payload["sections"] for ex in section["exhibits"]]

    def test_the_page_names_the_checked_quarter(self) -> None:
        c = self.checks
        self.assertIn(c["period"], self.payload["title"])
        self.assertIn(f"截至 {c['period_end']} · 发布 {c['release_date']}", self.payload["subtitle"])
        self.assertIn(f"本页 {c['period']} 即公司所称 {c['fiscal_label']}", self.payload["subtitle"])
        record = self.source["quarterly_guidance_history"]
        self.assertEqual(record["guided_in_release"][-1], c["release_date"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        c, fin, seg = self.checks, self.source["financials"], self.source["segments_usd_m"]
        self.assertEqual(round(fin["revenue_usd_m"][-1] * 1000), c["revenue_usd_k"])
        self.assertEqual(round(fin["revenue_usd_m"][-5] * 1000), c["revenue_year_ago_usd_k"])
        self.assertEqual(round(fin["gaap_operating_income_usd_m"][-1] * 1000), c["gaap_operating_income_usd_k"])
        adj = c["segment_adjusted_operating_income_usd_m"]
        self.assertEqual(round(seg["design_automation_adj_op_income"][-1], 1), adj["design_automation"])
        self.assertEqual(round(seg["design_ip_adj_op_income"][-1], 1), adj["design_ip"])
        self.assertAlmostEqual(fin["non_gaap_operating_income_usd_m"][-1],
                               adj["design_automation"] + adj["design_ip"], places=6)
        self.assertEqual(round(seg["design_ip_revenue"][-1] * 1000), c["design_ip_revenue_usd_k"])
        self.assertEqual(round(seg["design_ip_revenue"][-5] * 1000), c["design_ip_revenue_year_ago_usd_k"])
        self.assertEqual(fin["gaap_eps_usd"][-1], c["gaap_diluted_eps_usd"])
        self.assertEqual(fin["non_gaap_eps_usd"][-1], c["non_gaap_diluted_eps_usd"])
        self.assertEqual(round(fin["diluted_shares_m"][-1] * 1000), c["diluted_shares_k"])
        self.assertEqual(round(fin["non_gaap_net_income_usd_m"][-1], 1), c["non_gaap_net_income_usd_m"])
        backlog = self.source["backlog"]
        self.assertEqual(backlog["backlog_usd_b"][-1], c["backlog_usd_bn"])
        self.assertEqual(backlog["fsa_usd_b"][-1], c["fsa_usd_bn"])
        self.assertEqual(backlog["next_12m_pct_of_ex_fsa"][-1], c["next_12m_pct_of_ex_fsa"])
        ansys = self.source["ansys_revenue"]
        self.assertEqual(ansys["quarters"][-1], c["period"])
        self.assertEqual(ansys["share_pct"][-1], c["ansys_share_pct"])
        self.assertEqual(self.source["quarter_story"]["non_gaap_tax_rate_actual_pct"], c["non_gaap_tax_rate_pct"])

    def test_the_outlook_is_the_checked_outlook(self) -> None:
        guide, c = self.source["guidance"], self.checks
        nq, cnq = guide["next_quarter"], c["next_quarter"]
        self.assertEqual(nq["period"], cnq["period"])
        self.assertEqual(nq["fiscal_label"], cnq["fiscal_label"].replace(" ", ""))
        for key in ("revenue_usd_m", "non_gaap_expenses_usd_m", "non_gaap_eps_usd", "diluted_shares_m"):
            with self.subTest(key=key):
                self.assertEqual(nq[key], cnq[key])
        self.assertEqual(nq["non_gaap_tax_rate_pct"], cnq["non_gaap_tax_rate_pct"])
        full, cfull = guide["full_year"], c["full_year"]
        self.assertEqual(full["fiscal_year"], cfull["fiscal_year"])
        for key in ("revenue_usd_m", "non_gaap_eps_usd", "operating_cash_flow_usd_m",
                    "free_cash_flow_usd_m", "capex_usd_m"):
            with self.subTest(key=key):
                self.assertEqual(full["current"][key], cfull[key])
        self.assertEqual(guide["full_year_revenue_footnote"]["expected_ansys_revenue_usd_m"][-1],
                         cfull["expected_ansys_revenue_usd_m"])
        self.assertEqual(full["previous"]["released"], cfull["previous_released"])
        self.assertEqual(full["previous"]["revenue_usd_m"], cfull["previous_revenue_usd_m"])
        self.assertEqual(full["previous"]["non_gaap_eps_usd"], cfull["previous_non_gaap_eps_usd"])
        self.assertEqual(full["previous"]["operating_cash_flow_usd_m"],
                         cfull["previous_operating_cash_flow_usd_m"])

    def test_the_page_prints_the_checked_figures(self) -> None:
        c = self.checks
        self.assertIn(f"收入 US${c['revenue_usd_k'] / 1000:,.0f}M", self.payload["headline"])
        growth = (c["design_ip_revenue_usd_k"] / c["design_ip_revenue_year_ago_usd_k"] - 1) * 100
        self.assertIn(f"同比 {growth:+.1f}%", next(ex["title"] for ex in self.exhibits
                                                  if ex["title"].startswith("Design IP")
                                                  and ex["kind"] == "grouped_bars"))
        table = next(t for t in self.payload["tables"] if t["title"].startswith("本季兑现"))
        tax = next(r for r in table["rows"] if r[0] == "non-GAAP 税率")
        self.assertEqual(tax[2], f"{c['non_gaap_tax_rate_pct']:.1f}%")
        eps_move = sum(c["full_year"]["non_gaap_eps_usd"]) / 2 - sum(c["full_year"]["previous_non_gaap_eps_usd"]) / 2
        self.assertIn(f"上调 ${eps_move:.2f}", published_text(table))


class SnpsSettlementTest(unittest.TestCase):
    """Section one against `_checks["note"]`, typed from the two analyses.

    The note records what this quarter's analysis wrote in its section 0 (each
    follow-up's verdict, verbatim, and its verdict on each of last quarter's
    section-8 rows) and what last quarter's analysis wrote in its section 8
    (each line: metric, comparison, threshold). The builder never reads the
    note; the checks hold the series blocks and the published page to it and
    recompute every reading, so a roll that re-keys both passes unedited.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "snps.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)
        cls.settled = next(s for s in cls.payload["sections"] if s["id"] == "settled")

    def test_the_closure_counts_section_zero_as_written(self) -> None:
        check_closure(self, self.source, self.payload)

    def test_the_verdicts_are_the_analysis_own(self) -> None:
        chart = next(ex for ex in self.settled["exhibits"] if "条跟踪指标" in ex["title"])
        self.assertEqual(dict(zip(chart["xlabels"], chart["values"])), self.source["_checks"]["note"]["verdicts"])

    def test_last_quarters_lines_are_settled_as_the_analysis_wrote_them(self) -> None:
        check_prior_lines(self, self.source, self.payload)

    def test_a_consecutive_line_needs_the_whole_run(self) -> None:
        """「连续 2 季」is judged on the quarter of the run furthest from tripping it.

        On this quarter's data both EDA quarters sit under 9%, so a builder that
        ignored the run would print the same verdicts and pass. The state where
        the run matters is built here: the quarter before read above 9%, so the
        guard has held for one quarter, not two.
        """
        changed = copy.deepcopy(self.source)
        reading = changed["eda_product_group"]["readings"][-2]["now"]["three_months"]
        before = copy.deepcopy(reading)
        reading[0] = round(reading[0] * 1.1, 1)
        self.assertNotEqual(reading, before)
        values = history(changed, "eda_yoy")
        self.assertGreaterEqual(values[-2], 9.0)
        self.assertLess(values[-1], 9.0)
        payload = build_payload(changed)
        check_prior_lines(self, changed, payload)
        table = next(t for t in payload["tables"] if t["title"].startswith("上季（"))
        row = next(r for r in table["rows"] if r[1].startswith("EDA 收入同比（不含 Ansys） < "))
        self.assertEqual(row[5], "守住")

    def test_section_one_opens_with_the_settlement_then_the_guidance(self) -> None:
        kinds = [ex["kind"] for ex in self.settled["exhibits"]]
        titles = [ex["title"] for ex in self.settled["exhibits"]]
        self.assertTrue(titles[0].startswith("上季") and "待验证问题" in titles[0])
        self.assertTrue(titles[1].startswith("上季") and "跟踪指标" in titles[1])
        self.assertTrue(titles[2].startswith("上季") and "量化阈值" in titles[2])
        first_guide = next(i for i, title in enumerate(titles) if "优于指引中值" in title)
        self.assertTrue(all(title.startswith("上季") or "上季" in title for title in titles[:first_guide]))
        self.assertEqual(kinds[first_guide + 1], "range_band")
        self.assertNotIn("本站唯一一家", self.settled["description"])
        self.assertNotIn("第一份季报分析", self.settled["description"])

    def test_the_margin_line_is_not_said_to_have_held_three_quarters(self) -> None:
        """The analysis' 「连续第三季兑现」 is its beat-and-raise line; the quarterly
        margin the page prints was under 41% the quarter before."""
        margins = self.source["financials"]["non_gaap_operating_margin_pct"]
        chart = next(ex for ex in self.settled["exhibits"] if "条跟踪指标" in ex["title"])
        self.assertNotIn("non-GAAP 营业利润率连续第三季兑现", chart["note"])
        if margins[-2] < 41 <= margins[-1]:
            self.assertIn(f"上一季是 {margins[-2]:.1f}%", chart["note"])

    def test_the_eda_reading_agrees_with_the_company_s_own_figure(self) -> None:
        """The product-group shares reproduce what management said on the call."""
        said = self.source["_checks"]["note"]["management_eda_yoy_pct"]
        self.assertEqual(round(history(self.source, "eda_yoy")[-1], 1), said)

    def test_the_eda_shares_multiply_the_revenue_the_page_publishes(self) -> None:
        fin = self.source["financials"]
        for index, reading in enumerate(self.source["eda_product_group"]["readings"]):
            with self.subTest(quarter=self.source["periods"][index]):
                now, then = reading["now"], reading["year_ago"]
                base = now["three_months"][1] if "three_months" in now else \
                    now["full_year"][1] - now["nine_months"][1]
                self.assertAlmostEqual(base, fin["revenue_usd_m"][index], places=3)
                before = then["three_months"][1] if "three_months" in then else \
                    then["full_year"][1] - then["nine_months"][1]
                self.assertAlmostEqual((fin["revenue_usd_m"][index] / before - 1) * 100,
                                       fin["revenue_yoy_pct"][index], places=4)

    def test_the_ansys_quarters_reconcile_across_filings(self) -> None:
        """Where two filings print the same quarter they agree within rounding."""
        block = self.source["ansys_revenue"]
        revenue = dict(zip(self.source["periods"], self.source["financials"]["revenue_usd_m"]))
        ansys = ansys_by_quarter(self.source)
        for i, quarter in enumerate(block["quarters"]):
            printed, share = block["printed_usd_m"][i], block["share_pct"][i]
            if printed is not None and share is not None:
                self.assertLessEqual(abs(share / 100 * revenue[quarter] - printed),
                                     0.0005 * revenue[quarter] + 0.05, quarter)
            increase = block["printed_increase_usd_m"][i]
            if increase is not None:
                before = shifted(quarter, -4)
                self.assertLessEqual(abs(ansys[quarter] - ansys.get(before, 0.0) - increase),
                                     0.0005 * (revenue[quarter] + revenue.get(before, 0.0)) + 0.05, quarter)
        for year, total in block["fiscal_year_usd_m"].items():
            self.assertAlmostEqual(sum(value for q, f, value in zip(block["quarters"], block["fiscal_labels"],
                                                                    [ansys[q] for q in block["quarters"]])
                                       if f[:6] == year), total, places=6)
        with self.assertRaisesRegex(ValueError, "printed increase"):
            changed = copy.deepcopy(self.source)
            changed["ansys_revenue"]["printed_increase_usd_m"][-1] += 5
            build_payload(changed)


def rolled_forward(source: dict, growth: float = 1.0) -> dict:
    """The series as a data-only roll to the next quarter would leave it, in memory.

    The window moves one quarter: every aligned array drops its first cell and
    gains the same quarter a year earlier, flows scaled by ``growth``, share
    counts kept, ratios recomputed, so every identity the real quarters satisfy
    still holds and the rehearsal tests the mechanics, not invented figures. The
    guided record fills the quarter it was waiting on and opens the next one.
    The one-quarter blocks go the way a roll takes them: this quarter's
    `next_kpi` moves, as it stood, into `prior_kpi_settlement`; a
    `followup_closure` judges this quarter's follow-up questions; the lines not
    dated to the new quarter move on into a re-stamped `next_kpi`; the blocks
    that need a release's own words (guidance, market, story, verdicts, the
    restructuring plan) are left out, as a quarter without them would be. The
    note is re-keyed from those blocks. Nothing here is written to disk.
    """
    s = copy.deepcopy(source)
    period, first = s["periods"][-1], s["periods"][0]
    new = shifted(period, 1)
    fiscal = s["fiscal_labels"][-1]
    year, number = int(fiscal[2:6]), int(fiscal[-1])
    new_fiscal = f"FY{year + 1}Q1" if number == 4 else f"FY{year}Q{number + 1}"
    ya = s["periods"].index(shifted(new, -4))
    released = f"{int(s['period_ends'][ya][:4]) + 1}-12-10" if number == 3 else f"{int(s['period_ends'][ya][:4]) + 1}-03-01"

    def slide(values: list, appended) -> list:
        return values[1:] + [appended]

    new_end = f"{int(s['period_ends'][ya][:4]) + 1}{s['period_ends'][ya][4:]}"
    fin = s["financials"]
    flows = ("revenue_usd_m", "gaap_operating_income_usd_m", "non_gaap_operating_income_usd_m",
             "gaap_net_income_usd_m", "non_gaap_net_income_usd_m", "acquisition_amortization_usd_m",
             "stock_based_compensation_usd_m", "restructuring_usd_m")
    new_fin = {key: fin[key][ya] * growth for key in flows}
    new_fin["diluted_shares_m"] = fin["diluted_shares_m"][-1]
    new_fin["revenue_yoy_pct"] = (growth - 1) * 100
    new_fin["gaap_operating_margin_pct"] = new_fin["gaap_operating_income_usd_m"] / new_fin["revenue_usd_m"] * 100
    new_fin["non_gaap_operating_margin_pct"] = (new_fin["non_gaap_operating_income_usd_m"]
                                                / new_fin["revenue_usd_m"] * 100)
    new_fin["gaap_eps_usd"] = round(new_fin["gaap_net_income_usd_m"] / new_fin["diluted_shares_m"], 2)
    new_fin["non_gaap_eps_usd"] = round(new_fin["non_gaap_net_income_usd_m"] / new_fin["diluted_shares_m"], 2)
    for key in fin:
        fin[key] = slide(fin[key], new_fin[key])
    seg = s["segments_usd_m"]
    outside = seg["design_ip_revenue_prior_year_outside_window"]
    outside.pop(first, None)
    outside[shifted(first, 4)] = seg["design_ip_revenue"][0]
    for key in ("design_automation_revenue", "design_ip_revenue",
                "design_automation_adj_op_income", "design_ip_adj_op_income"):
        seg[key] = slide(seg[key], seg[key][ya] * growth)
    eda = s["eda_product_group"]
    ya_reading = eda["readings"][ya]

    def amount(parts: dict) -> float:
        if "three_months" in parts:
            return parts["three_months"][0] * parts["three_months"][1] / 100
        return (parts["full_year"][0] * parts["full_year"][1] - parts["nine_months"][0] * parts["nine_months"][1]) / 100
    ya_revenue = source["financials"]["revenue_usd_m"][ya]
    share = amount(ya_reading["now"]) / ya_revenue * 100
    eda["quarters"] = slide(eda["quarters"], new)
    eda["readings"] = slide(eda["readings"], {
        "fiscal": new_fiscal, "now": {"three_months": [share, new_fin["revenue_usd_m"]]},
        "year_ago": {"three_months": [share, ya_revenue]}, "source": "换季演练：取自去年同季"})
    ansys = s["ansys_revenue"]
    ansys_ya = ansys_by_quarter(source)[shifted(new, -4)]
    ansys["quarters"].append(new)
    ansys["fiscal_labels"].append(new_fiscal)
    ansys["printed_usd_m"].append(None)
    ansys["share_pct"].append(ansys_ya / ya_revenue * 100)
    ansys["printed_increase_usd_m"].append(None)
    ansys["sources"].append("换季演练：取自去年同季的占比")
    s["periods"] = slide(s["periods"], new)
    s["period_ends"] = slide(s["period_ends"], new_end)
    s["fiscal_labels"] = slide(s["fiscal_labels"], new_fiscal)

    backlog = s["backlog"]
    b_ya = backlog["quarters"].index(shifted(new, -4))
    for key in ("backlog_usd_b", "fsa_usd_b", "next_12m_pct_of_ex_fsa"):
        backlog[key].append(backlog[key][b_ya])
    backlog["quarters"].append(new)
    backlog["fiscal_labels"].append(new_fiscal)
    backlog["period_ends"].append(new_end)
    backlog["filed_sentence_dates"].append("换季演练")
    disagg = s["disaggregation_usd_m"]
    d_ya = disagg["quarters"].index(shifted(new, -4))
    width = len(disagg["quarters"])
    for key, values in disagg.items():
        if isinstance(values, list) and len(values) == width and key not in ("quarters", "fiscal_labels"):
            values.append(None if values[d_ya] is None else values[d_ya] * growth)
    disagg["quarters"].append(new)
    disagg["fiscal_labels"].append(new_fiscal)
    capital = s["capital_allocation_usd_m"]
    for key in ("buyback_usd_m", "debt_repaid_usd_m", "debt_proceeds_usd_m"):
        capital[key].append(0.0)
    capital["capex_usd_m"].append(capital["capex_usd_m"][capital["quarters"].index(shifted(new, -4))] * growth)
    capital["remaining_authorization_usd_m"].append(capital["remaining_authorization_usd_m"][-1])
    capital["derived"].append(True)
    capital["quarters"].append(new)
    capital["fiscal_labels"].append(new_fiscal)

    record = s["quarterly_guidance_history"]
    row = record["quarters"].index(new)
    record["actual_revenue_usd_m"][row] = new_fin["revenue_usd_m"]
    record["actual_non_gaap_operating_income_usd_m"][row] = new_fin["non_gaap_operating_income_usd_m"]
    record["actual_non_gaap_eps_usd"][row] = new_fin["non_gaap_eps_usd"]
    record["actual_gaap_eps_usd"][row] = new_fin["gaap_eps_usd"]
    record["actual_diluted_shares_m"][row] = new_fin["diluted_shares_m"]
    width = len(record["quarters"])
    template = record["quarters"].index(shifted(new, -3))
    for key, values in record.items():
        if not isinstance(values, list) or len(values) != width:
            continue
        if key == "quarters":
            values.append(shifted(new, 1))
        elif key == "fiscal_labels":
            values.append(f"FY{int(new_fiscal[2:6]) + (1 if new_fiscal.endswith('Q4') else 0)}Q"
                          f"{1 if new_fiscal.endswith('Q4') else int(new_fiscal[-1]) + 1}")
        elif key == "period_ends":
            values.append(f"{int(values[template][:4]) + 1}{values[template][4:]}")
        elif key == "guided_in_release":
            values.append(released)
        elif key.startswith("actual_"):
            values.append(None)
        else:
            values.append(values[template])

    s["latest"] = {**s["latest"], "period": new, "release_date": released}
    s["sources"].insert(0, {"label": f"Synopsys {fiscal_words(new_fiscal)} 业绩新闻稿（换季演练）",
                            "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000883241"})
    for key in ("guidance", "market_expectation", "quarter_story", "tracked_metric_verdicts", "restructuring_plan"):
        s.pop(key, None)

    kpi = s["next_kpi"]
    labels = ["已验证", "部分验证", "仍未披露", "被证伪"]
    items = [{"question": item["question"], "verdict_text": labels[i % len(labels)], "verdict": labels[i % len(labels)],
              "evidence": "换季演练：判定按问题顺序轮换"} for i, item in enumerate(kpi["followups"])]
    s["followup_closure"] = {"period": new, "set_in": period, "labels": labels, "items": items,
                             "note": "换季演练：判定按问题顺序轮换。"}
    s["prior_kpi_settlement"] = {"period": new, "set_in": period, "rows": kpi["rows"],
                                 "quantified": copy.deepcopy(kpi["quantified"]),
                                 "unsettled": copy.deepcopy(kpi.get("not_drawn", []))}
    carried = [entry for entry in kpi["quantified"] if not entry.get("period")]
    rows = sorted({entry["row"] for entry in carried} | {item["row"] for item in kpi.get("not_drawn", [])})
    s["next_kpi"] = {
        "period": new, "set_in": new, "for_period": shifted(new, 1), "rows": len(rows),
        "quantified": [{**entry, "row": rows.index(entry["row"]) + 1} for entry in carried],
        "not_drawn": [{**item, "row": rows.index(item["row"]) + 1} for item in kpi.get("not_drawn", [])],
        "followups": kpi["followups"],
    }
    note = s["_checks"]["note"]
    s["_checks"] = {**s["_checks"], "period": new, "period_end": new_end, "release_date": released,
                    "fiscal_label": fiscal_words(new_fiscal), "source": "换季演练：各格取自去年同季，不是申报读数"}
    s["_checks"]["note"] = {
        "source": {"this_quarter": "换季演练", "last_quarter": note["source"]["this_quarter"]},
        "closure": {"total": len(items), "verdicts_verbatim": [item["verdict_text"] for item in items],
                    "counts": {label: sum(1 for item in items if item["verdict"] == label) for label in labels}},
        "prior_rows": kpi["rows"],
        "prior_thresholds": copy.deepcopy(note["next_thresholds"]),
        "prior_unquantified_rows": copy.deepcopy(note.get("next_unquantified_rows", {})),
        "next_rows": len(rows),
        "next_thresholds": [{**t, "row": rows.index(t["row"]) + 1} for t in note["next_thresholds"]
                            if not t.get("period")],
        "next_unquantified_rows": {str(rows.index(int(key)) + 1): value
                                   for key, value in note.get("next_unquantified_rows", {}).items()},
        "followups_total": len(kpi["followups"]),
    }
    return s


class SnpsRollRehearsalTest(unittest.TestCase):
    """The next quarter, built from the series alone (CLAUDE.md §9).

    `rolled_forward` moves the window, fills the guided record and moves this
    quarter's `next_kpi` into `prior_kpi_settlement` unchanged. If a reading a
    line uses could only be computed by editing `build/snps.py` -- or if
    section one could not draw a settlement block it has never seen -- the build
    stops here instead of at the real roll. Two growth rates, so the lines land
    on different sides of their thresholds.
    """

    GROWTH = (1.0, 1.3)

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "snps.json").read_text(encoding="utf-8"))
        cls.rolled = {growth: rolled_forward(cls.source, growth) for growth in cls.GROWTH}
        cls.payloads = {growth: build_payload(staging) for growth, staging in cls.rolled.items()}

    def test_the_next_quarter_builds_from_the_series_alone(self) -> None:
        for growth, staging in self.rolled.items():
            payload = self.payloads[growth]
            with self.subTest(growth=growth):
                guard_check(payload)
                self.assertEqual([s["id"] for s in payload["sections"]],
                                 ["settled", "quarter_highlights", "next_quarter", "routine"])
                self.assertTrue(all(s["exhibits"] for s in payload["sections"]))
                self.assertIn(staging["periods"][-1], payload["title"])
                exhibits = [ex for s in payload["sections"] for ex in s["exhibits"]]
                self.assertEqual([ex["n"] for ex in exhibits], list(range(2, 2 + len(exhibits))))
                for ex in exhibits:
                    for key in ("title", "note", "src_extra"):
                        self.assertNotRegex(ex.get(key) or "", r"\{[A-Za-z_:]+\}", ex["title"])
                # ...and the builder still never reads `_checks`.
                self.assertEqual(build_payload({k: v for k, v in staging.items() if k != "_checks"}), payload)

    def test_section_one_settles_what_this_quarter_set(self) -> None:
        for growth, staging in self.rolled.items():
            payload = self.payloads[growth]
            with self.subTest(growth=growth):
                self.assertEqual(staging["prior_kpi_settlement"]["quantified"],
                                 self.source["next_kpi"]["quantified"])
                check_closure(self, staging, payload)
                check_prior_lines(self, staging, payload)
                check_next_lines(self, staging, payload)
                # The lines dated to the new quarter are due now, so none waits.
                table = next(t for t in payload["tables"] if "阈值与本季读数" in t["title"] and t["title"].startswith("上季"))
                self.assertNotIn("未到期", [row[5] for row in table["rows"]])

    def test_the_rehearsals_reach_every_settled_verdict(self) -> None:
        """Otherwise the rehearsal could pass on lines that never leave one state."""
        seen = set()
        for payload in self.payloads.values():
            table = next(t for t in payload["tables"] if "阈值与本季读数" in t["title"] and t["title"].startswith("上季"))
            seen |= {row[5] for row in table["rows"]}
        self.assertLessEqual({"达到", "没到", "守住", "越线"}, seen)


class SnpsRollTest(unittest.TestCase):
    """A roll edits the series and nothing else."""

    STAMPED = ("guidance", "market_expectation", "followup_closure", "tracked_metric_verdicts",
               "next_kpi", "restructuring_plan", "quarter_story")

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = json.loads((ROOT / "series" / "snps.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(cls.source)
        cls.text = published_text(cls.payload)

    def rebuilt(self, edit) -> dict:
        changed = copy.deepcopy(self.source)
        edit(changed)
        return build_payload(changed)

    def moves(self, claims, edit) -> None:
        after = published_text(self.rebuilt(edit))
        for claim in claims:
            with self.subTest(claim=claim):
                self.assertIn(claim, self.text)
                self.assertNotIn(claim, after)

    def test_quarter_blocks_refuse_to_publish_under_another_quarter(self) -> None:
        for key in self.STAMPED + ("prior_kpi_settlement",):
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    self.rebuilt(lambda s, key=key: s[key].__setitem__("period", "Q1 1999"))
        with self.assertRaisesRegex(ValueError, "sources"):
            self.rebuilt(lambda s: s.__setitem__(
                "sources", [x for x in s["sources"] if "业绩新闻稿" not in x["label"]]))
        with self.assertRaisesRegex(ValueError, "footnote"):
            self.rebuilt(lambda s: s["guidance"]["full_year_revenue_footnote"]["releases"].__setitem__(
                -1, "1999-01-01"))

    def test_a_quarter_without_its_blocks_leaves_them_out(self) -> None:
        def strip(s):
            for key in self.STAMPED:
                del s[key]
        payload = self.rebuilt(strip)
        text = published_text(payload)
        for gone in ("条跟踪指标", "条待验证问题", "EPS 指引中值高出预期", "Processor IP Solutions 出售",
                     "收入指引本季上调", "本季兑现与下季／全年指引", "2026 Plan", "投资者日", "条结论不出图"):
            with self.subTest(gone=gone):
                self.assertIn(gone, self.text)
                self.assertNotIn(gone, text)
        self.assertEqual([s["id"] for s in payload["sections"]],
                         ["settled", "quarter_highlights", "next_quarter", "routine"])
        sections = {s["id"]: s for s in payload["sections"]}
        self.assertEqual(sections["next_quarter"]["exhibits"], [])
        # Last quarter's thresholds are not optional once there was a last analysis.
        self.assertTrue(any(ex["title"].startswith("上季") and "量化阈值" in ex["title"]
                            for ex in sections["settled"]["exhibits"]))

    def test_a_later_quarter_must_settle_the_previous_analysis(self) -> None:
        """The first local analysis covers FY2026 Q1 (this page's Q4 2025); every
        quarter after it owes a settlement of the one before, so a roll that
        leaves `prior_kpi_settlement` out stops rather than publishing a section
        one that silently skipped it -- and a block settling another quarter's
        analysis stops too."""
        with self.assertRaisesRegex(ValueError, "set thresholds in its section 8"):
            self.rebuilt(lambda s: s.pop("prior_kpi_settlement"))
        for key in ("prior_kpi_settlement", "followup_closure"):
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "last quarter was"):
                    self.rebuilt(lambda s, key=key: s[key].__setitem__("set_in", "Q1 1999"))
        with self.assertRaisesRegex(ValueError, "accounted for"):
            self.rebuilt(lambda s: s["prior_kpi_settlement"]["unsettled"].pop())
        with self.assertRaisesRegex(ValueError, "typed"):
            self.rebuilt(lambda s: s["prior_kpi_settlement"]["quantified"][0].__setitem__("actual", 8.5))

    def test_a_story_whose_premise_fails_stops_the_build(self) -> None:
        def guide_below(s):
            s["guidance"]["next_quarter"]["non_gaap_eps_usd"] = [3.70, 3.76]
        with self.assertRaisesRegex(ValueError, "guide_beats_quarter"):
            self.rebuilt(guide_below)

        def typed_again(s):
            s["next_kpi"]["quantified"][0]["current"] = 41.6
        with self.assertRaisesRegex(ValueError, "typed"):
            self.rebuilt(typed_again)

        def unknown_reading(s):
            s["next_kpi"]["quantified"][0]["reads"] = "not_a_reading"
        with self.assertRaisesRegex(KeyError, "does not compute"):
            self.rebuilt(unknown_reading)

        def row_dropped(s):
            s["next_kpi"]["not_drawn"] = [item for item in s["next_kpi"]["not_drawn"] if item["row"] != 2]
        with self.assertRaisesRegex(ValueError, "next_kpi"):
            self.rebuilt(row_dropped)

        def dated_in_the_past(s):
            s["next_kpi"]["quantified"][0]["period"] = "Q1 1999"
        with self.assertRaisesRegex(ValueError, "settle it on its own quarter"):
            self.rebuilt(dated_in_the_past)

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        record = self.source["quarterly_guidance_history"]

        def deeper_miss(s):
            r = s["quarterly_guidance_history"]
            row = r["quarters"].index("Q2 2019")
            r["actual_revenue_usd_m"][row] = r["guide_revenue_lo_usd_m"][row] * 0.9
        self.moves(("看上去是本记录里最大的一次跌破",), deeper_miss)

        def only_two_eps_misses(s):
            r = s["quarterly_guidance_history"]
            row = r["quarters"].index("Q2 2017")
            r["actual_non_gaap_eps_usd"][row] = r["guide_non_gaap_eps_hi_usd"][row]
        after = published_text(self.rebuilt(only_two_eps_misses))
        self.assertIn("三次为负", self.text)
        self.assertIn("两次为负仍是同样的两季", after)

        def ip_streak_shorter(s):
            s["segments_usd_m"]["design_ip_revenue_prior_year_outside_window"]["Q2 2025"] = 400.0
        after = published_text(self.rebuilt(ip_streak_shorter))
        self.assertIn("Design IP 连续四季同比负增长后重新转正", self.text)
        self.assertIn("Design IP 连续三季同比负增长后重新转正", after)

        def amortisation_monotonic(s):
            s["long_history"]["amortization_cost_of_revenue_usd_m"][2] = 70.0
        after = published_text(self.rebuilt(amortisation_monotonic))
        self.assertIn("小幅回升", self.text)
        self.assertNotIn("小幅回升", after)
        self.assertIn("一路降到", after)

        def recognisable_fell(s):
            year_end = max(i for i, label in enumerate(s["backlog"]["fiscal_labels"]) if label.endswith("Q4"))
            s["backlog"]["next_12m_pct_of_ex_fsa"][year_end] = 49.0
        self.moves(("但可确认的那一半从", "深蓝在降、金色在升"), recognisable_fell)

        def korea_not_leading(s):
            d = s["disaggregation_usd_m"]
            d["korea"][-1] -= 40.0
            d["other"][-1] += 40.0
        self.moves(("是全公司最强的一格",), korea_not_leading)

        def shares_over_twice(s):
            r = s["quarterly_guidance_history"]
            row = r["quarters"].index("Q2 2016")
            r["actual_diluted_shares_m"][row] = r["guide_shares_hi_m"][row] + 1
        self.moves(("唯一一次冲出上限的",), shares_over_twice)

        def both_legs_on_break(s):
            r = s["quarterly_guidance_history"]
            row = r["basis_break_at"]
            r["actual_non_gaap_operating_income_usd_m"][row] = 300.0
        after = published_text(self.rebuilt(both_legs_on_break))
        self.assertIn("两条腿同时为负的只有 Q3'21", self.text)
        self.assertIn("Q1'24（", after)
        self.assertEqual(record["quarters"][record["basis_break_at"]], "Q1 2024")

    def test_the_counts_on_the_page_are_recounted_here(self) -> None:
        record = self.source["quarterly_guidance_history"]
        n = sum(1 for v in record["actual_revenue_usd_m"] if v is not None)
        self.assertIn(f"在这里有 {n} 季的完整答案", self.text)
        geo = len(self.source["disaggregation_usd_m"]["quarters"])
        self.assertIn(f"全部{cn_count(geo)}季均为剔除 Software Integrity", self.text)
        self.assertIn(f"{cn_count(len(self.source['backlog']['quarters']))}季度 backlog 与资本配置", self.text)
        # Europe's step is read at the first full Ansys quarter, not at a fixed
        # index: backfilling two quarters at the front had moved a hard-coded
        # [9] - [8] onto Q1'25 - Q4'24 (+1.6pp) under a sentence naming Q3'25.
        d = self.source["disaggregation_usd_m"]
        full = d["quarters"].index("Q2 2025") + 1
        jump = (d["europe"][full] / d["revenue_usd_m"][full]
                - d["europe"][full - 1] / d["revenue_usd_m"][full - 1]) * 100
        self.assertIn(f"欧洲占比在 {compact_period(d['quarters'][full])} 单季跳升 {jump:.1f}pp", self.text)
        self.assertGreater(jump, 0)
        footnote = self.source["guidance"]["full_year_revenue_footnote"]
        mids = [(lo + hi) / 2 for lo, hi in zip(footnote["revenue_lo_usd_m"], footnote["revenue_hi_usd_m"])]
        self.assertIn(f"全年累计{cn_count(sum(1 for a, b in zip(mids, mids[1:]) if b > a))}次上调", self.text)

    def test_the_flat_stretch_is_measured_not_assumed(self) -> None:
        # The gold line is flat only while it stays inside the band the buyback years held it in.
        long = self.source["long_history"]
        buys, shares = long["share_repurchases_usd_m"], long["diluted_shares_m"]
        paid = [s for b, s in zip(buys, shares) if b > 0]
        low, high = min(paid) * 0.99, max(paid) * 1.01
        flat = next((i for i, s in enumerate(shares) if not low <= s <= high), len(shares))
        self.assertLess(flat, len(shares), "the Ansys shares sit above the buyback band")
        self.assertIn(f"金线前{cn_count(flat)}年几乎是一条平线", self.text)

        def no_step(s):
            s["long_history"]["diluted_shares_m"][-1] = max(paid)
        self.assertIn(f"金线{cn_count(len(shares))}年几乎是一条平线", published_text(self.rebuilt(no_step)))

    def test_one_footnote_vintage_draws_no_split_and_points_at_none(self) -> None:
        def one_vintage(s):
            footnote = s["guidance"]["full_year_revenue_footnote"]
            for key, value in footnote.items():
                if isinstance(value, list):
                    footnote[key] = value[-1:]
        text = published_text(self.rebuilt(one_vintage))
        self.assertIn("次上调共", self.text)
        self.assertNotIn("次上调共", text)
        self.assertNotIn("拆解见 Exhibit", text)
        self.assertNotIn("单独成图", text)
        self.assertIsNone(re.search(r"\{[A-Za-z_:]+\}", text))

    def test_a_verb_that_carries_the_direction_prints_the_size(self) -> None:
        for text in (self.text, published_text(self.rebuilt(lambda s: None))):
            self.assertIsNone(re.search(r"(上调共|上修了|下修了|跳升|抬到|降到|升到|掉到) ?(US\$)?[+−-]\d", text))

    def test_no_markdown_reaches_the_page(self) -> None:
        """Exhibit notes and source lines are innerHTML: `**` prints as asterisks."""
        for section in self.payload["sections"]:
            for ex in section["exhibits"]:
                with self.subTest(exhibit=ex["n"]):
                    self.assertNotIn("**", ex.get("note", "") + ex.get("src_extra", ""))


if __name__ == "__main__":
    unittest.main()
