"""The luxury cross-company page, re-derived from the six series it reads.

Every other page on this site is settled twice: its `_checks` block says the
figures match the filing, and its own test says the payload matches the series.
A cross page cannot use the first of those. Copying the six companies' `_checks`
into `series/luxury.json` would only prove that file equals those six, which is
the shape CLAUDE.md §5 calls 「共享同一个输入的两个读数」 -- and the question a
cross page actually raises is not "is this number right" (six pages already
answer that) but "was it joined and computed right".

So this file is the second reading, and it is only a second reading if it does
not go through the thing it is checking. **Nothing here imports `build.luxury`.**
The window intersection, the year-on-year arithmetic, the euro-thousand
conversions, the trailing-four-quarter sums, the half-year margins and the
basis-gap measurement are all written again, from the raw series, and compared
against the published payload. Where the two agree, two independent paths
produced the same number; where this file merely re-read a constant out of the
payload, it would prove nothing, so it does not do that anywhere.

The one thing it does import from the builder's world is the member list in
`series/luxury.json`, because that is the page's subject rather than its
arithmetic -- and `test_the_members_are_all_registered_companies` checks it
against `ENTRIES` so the page cannot quietly be about a different six.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.all import CROSS_ENTRIES, ENTRIES  # noqa: E402

SLUG = "luxury"
MEMBERS = ["mc", "cfr", "rms", "ker", "zgn", "bc"]


def load_series(slug: str) -> dict:
    return json.loads((ROOT / "series" / f"{slug}.json").read_text(encoding="utf-8"))


def load_payload(slug: str) -> dict:
    text = (ROOT / "data" / f"{slug}.js").read_text(encoding="utf-8")
    return json.loads(text.split(" = ", 1)[1].rstrip().rstrip(";\n"))


def norm_quarter(label: str) -> str:
    """``Q2 2026`` / ``2026Q2`` -> ``2026Q2``. Written again, not imported."""
    text = str(label).strip()
    match = re.fullmatch(r"(\d{4})Q([1-4])", text)
    if match:
        return text
    match = re.fullmatch(r"Q([1-4])\s+(\d{4})", text)
    if match:
        return f"{match.group(2)}Q{match.group(1)}"
    raise AssertionError(f"unrecognised quarter label: {label!r}")


def norm_half(label: str) -> str:
    """``2026H1`` / ``H1 2026`` -> ``H1 2026``."""
    text = str(label).strip()
    match = re.fullmatch(r"(\d{4})H([12])", text)
    if match:
        return f"H{match.group(2)} {match.group(1)}"
    match = re.fullmatch(r"H([12])\s+(\d{4})", text)
    if match:
        return text
    raise AssertionError(f"unrecognised half label: {label!r}")


# The six accessors, written independently of `build/luxury.py`'s. They are
# deliberately in the same shape -- there is only one place each figure lives --
# but the normalisation, the unit conversion and every derived quantity below
# are this file's own.
def quarterly_revenue_eur_m(slug: str, data: dict) -> dict[str, float]:
    if slug == "mc":
        labels, values, scale = data["long_quarters"], data["quarterly_revenue_eur_m"]["total"], 1
    elif slug == "cfr":
        labels, values, scale = data["quarters"], data["quarterly_eur_m"]["total"], 1
    elif slug == "rms":
        labels, values, scale = data["periods"], data["group_revenue"]["revenue_eur_m"], 1
    elif slug == "ker":
        labels = data["long_quarters"]
        values, scale = data["quarterly_revenue_eur_m"]["group_first_published"], 1
    elif slug == "zgn":
        labels, values, scale = (data["quarterly"]["periods"],
                                 data["quarterly"]["revenue_eur_k"], 0.001)
    elif slug == "bc":
        labels, values, scale = (data["quarterly"]["periods"],
                                 data["quarterly"]["revenue_eur_k"], 0.001)
    else:
        raise AssertionError(slug)
    return {norm_quarter(label): value * scale
            for label, value in zip(labels, values) if value is not None}


def printed_growth(slug: str, data: dict) -> dict[str, float] | None:
    """The company's own quarterly rate, or None when this site has not connected one."""
    if slug == "mc":
        return {norm_quarter(q): float(v) for q, v in
                zip(data["organic_quarters"], data["organic_growth_pct"]["total"]) if v is not None}
    if slug == "cfr":
        return {norm_quarter(q): float(v) for q, v in
                zip(data["quarters"], data["quarterly_cer_pct"]["total"]) if v is not None}
    if slug == "rms":
        return {norm_quarter(q): float(v) for q, v in
                zip(data["periods"], data["group_revenue"]["cc_pct"]) if v is not None}
    if slug == "ker":
        return {norm_quarter(q): float(v) for q, v in
                zip(data["long_quarters"],
                    data["quarterly_comparable_pct"]["group_first_published"]) if v is not None}
    return None


def cn_count(n: int) -> str:
    """Written out the way the page writes it, spelled here rather than imported."""
    digits = "零一二三四五六七八九"
    if n < 0 or n > 99:
        return str(n)
    if n < 10:
        return "两" if n == 2 else digits[n]
    tens, ones = divmod(n, 10)
    return ("" if tens == 1 else digits[tens]) + "十" + ("" if ones == 0 else digits[ones])


def half_margin(slug: str, data: dict) -> dict[str, float]:
    if slug == "mc":
        labels = data["halves"]
        revenue, profit = data["half_revenue_eur_m"]["total"], data["half_pro_eur_m"]["total"]
    elif slug == "ker":
        labels = data["halves"]
        revenue = data["half_group"]["revenue"]["values"]
        profit = data["half_group"]["recurring_operating_income"]["values"]
    elif slug == "rms":
        labels = [h["label"] for h in data["half_years"]]
        revenue = [h["revenue_eur_m"] for h in data["half_years"]]
        profit = [h["recurring_operating_income_eur_m"] for h in data["half_years"]]
    elif slug == "zgn":
        labels = data["half"]["periods"]
        revenue, profit = data["half"]["revenue"], data["half"]["operating_profit"]
    elif slug == "bc":
        labels = data["half"]["periods"]
        revenue, profit = data["half"]["revenue_eur_k"], data["half"]["ebit_eur_k"]
    else:
        raise AssertionError(f"{slug} has no calendar half-year")
    return {norm_half(label): profit_value / revenue_value * 100
            for label, revenue_value, profit_value in zip(labels, revenue, profit)
            if revenue_value and profit_value is not None}


def year_on_year(revenue: dict[str, float], quarter: str) -> float | None:
    year, number = int(quarter[:4]), quarter[5]
    prior = f"{year - 1}Q{number}"
    if quarter not in revenue or prior not in revenue or not revenue[prior]:
        return None
    return (revenue[quarter] / revenue[prior] - 1) * 100


class LuxuryCrossPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = load_payload(SLUG)
        cls.staging = load_series(SLUG)
        cls.series = {slug: load_series(slug) for slug in MEMBERS}
        cls.revenue = {slug: quarterly_revenue_eur_m(slug, data)
                       for slug, data in cls.series.items()}
        cls.window = sorted(set.intersection(*(set(r) for r in cls.revenue.values())),
                            key=lambda q: (int(q[:4]), int(q[5])))
        # Two windows. Every member has a euro figure across `window`; a growth
        # reading additionally needs either a rate the company printed or a
        # year-ago euro quarter to divide by, and neither is available for the
        # whole of it. Recomputed here rather than read off the payload, which
        # is the number under test.
        # Over the **union** of every member's quarters, not the intersection:
        # a chart drawn from four of the six runs on the window those four
        # share, which reaches further back than the six-company one, and a
        # rate map cut to the intersection could not check it.
        cls.union = sorted(set().union(*(set(r) for r in cls.revenue.values())),
                           key=lambda q: (int(q[:4]), int(q[5])))
        cls.rates = {}
        for slug in MEMBERS:
            published = printed_growth(slug, cls.series[slug])
            if published is not None:
                cls.rates[slug] = {q: published[q] for q in cls.union if q in published}
            else:
                cls.rates[slug] = {q: year_on_year(cls.revenue[slug], q) for q in cls.union
                                   if year_on_year(cls.revenue[slug], q) is not None}
        cls.rate_window = [q for q in cls.window if all(q in cls.rates[s] for s in MEMBERS)]
        cls.exhibits = {exhibit["n"]: exhibit
                        for section in cls.payload["sections"]
                        for exhibit in section["exhibits"]}

    def exhibit_titled(self, fragment: str) -> dict:
        found = [e for e in self.exhibits.values() if fragment in e["title"]]
        self.assertEqual(len(found), 1,
                         f"expected exactly one exhibit whose title contains {fragment!r}")
        return found[0]

    def series_named(self, exhibit: dict, fragment: str) -> list:
        found = [s for s in exhibit["series"] if fragment in s["name"]]
        self.assertEqual(len(found), 1,
                         f"Ex{exhibit['n']}: expected one series matching {fragment!r}, "
                         f"got {[s['name'] for s in exhibit['series']]}")
        return found[0]["values"]

    # ── the page is wired in, and wired in as a non-company ─────────────────
    def test_the_page_is_registered_as_a_cross_page_not_a_company(self) -> None:
        """The distinction the whole registration rests on, asserted once.

        A cross page in `ENTRIES` would be counted in 「N 家公司」, would get a
        company card, and would be required to have a `series/<slug>.json` full
        of filings. It is none of those things, and every one of those failures
        would be silent -- the count would simply be one too high and the home
        page's own census would certify it.
        """
        self.assertIn(SLUG, {entry["slug"] for entry in CROSS_ENTRIES})
        self.assertNotIn(SLUG, {entry["slug"] for entry in ENTRIES})
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn(f'class="xcard" href="{SLUG}/"', home)
        self.assertNotIn(f'class="hcard" href="{SLUG}/"', home)
        self.assertIn(f"{len(ENTRIES)} 家公司", home)

    def test_the_members_are_all_registered_companies(self) -> None:
        """The page cannot quietly become about a different six."""
        entry = next(e for e in CROSS_ENTRIES if e["slug"] == SLUG)
        self.assertEqual(entry["members"], MEMBERS)
        self.assertEqual([m["slug"] for m in self.staging["members"]], MEMBERS)
        registered = {e["slug"]: e for e in ENTRIES}
        for slug in MEMBERS:
            self.assertIn(slug, registered, f"{slug} is not a registered company page")
            self.assertEqual(registered[slug]["group"], "luxury_brands")
        # The site's `luxury_brands` group is 「奢侈品与豪华汽车」 and also holds
        # Ferrari. The page covers the six luxury-goods houses and leaves the
        # carmaker out on purpose -- it runs on a different disclosure shape
        # entirely (a full quarterly income statement in a 6-K, where these six
        # publish profit twice a year). Asserting the exclusion, rather than
        # asserting a set equality that quietly hides it, is what keeps that a
        # decision instead of an oversight.
        in_group = {e["slug"] for e in ENTRIES if e["group"] == "luxury_brands"}
        self.assertTrue(set(MEMBERS) < in_group)
        self.assertEqual(sorted(in_group - set(MEMBERS)), ["race"])
        self.assertIn("法拉利", " ".join(self.payload["notes"]),
                      "the page must say which group member it leaves out, and why")

    def test_the_page_appears_in_the_navigation_payload(self) -> None:
        """A page nobody can reach from another page is a page nobody reads."""
        roster = json.loads(
            (ROOT / "data" / "roster.js").read_text(encoding="utf-8")
            .split(" = ", 1)[1].rstrip().rstrip(";\n"))
        self.assertIn(SLUG, {item["slug"] for item in roster["cross"]})
        self.assertNotIn(SLUG, {item["slug"] for item in roster["items"]})
        renderer = (ROOT / "assets" / "page.js").read_text(encoding="utf-8")
        self.assertIn("R.cross", renderer,
                      "page.js does not read the roster key the cross pages live in")
        self.assertEqual(self.payload["page"]["slug"], SLUG,
                         "the dropdown marks the current page by page.slug")

    def test_the_shell_stamps_the_payload_it_loads(self) -> None:
        import hashlib
        shell = (ROOT / SLUG / "index.html").read_text(encoding="utf-8")
        found = re.findall(r'src="\.\./(\S+?)\?v=([0-9a-f]+)"', shell)
        self.assertEqual(len(found), 4, "shell should link roster, payload, charts, page")
        for relative, digest in found:
            actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            self.assertTrue(actual.startswith(digest), f"{relative} digest is stale")

    def test_the_page_carries_the_cross_page_table(self) -> None:
        titles = [table["title"] for table in self.payload["tables"]]
        self.assertEqual(sum("AI capex" in title for title in titles), 1)

    # ── the window ──────────────────────────────────────────────────────────
    def test_the_common_window_is_the_intersection_of_the_six(self) -> None:
        """Recomputed here; the page states it in four separate places."""
        exhibit = self.exhibit_titled("六家在共同的")
        self.assertEqual(exhibit["xlabels"], self.rate_window)
        self.assertLess(len(self.rate_window), len(self.window),
                        "the rate window is the shorter of the two; if it stops "
                        "being shorter, the note explaining why is now false")
        self.assertEqual(self.payload["latest"]["disclosed_period_label"],
                         f"Q{self.window[-1][5]} {self.window[-1][:4]}")
        self.assertIn(f"{self.window[0]}–{self.window[-1]}", self.payload["subtitle"])

    def test_the_window_chart_counts_what_each_series_actually_holds(self) -> None:
        exhibit = self.exhibit_titled("每家在本站可画的季度数")
        groups = {group["name"]: group["values"] for group in exhibit["groups"]}
        printed = next(v for name, v in groups.items() if "公司印出" in name)
        derived = next(v for name, v in groups.items() if "相减" in name)
        missing = next(v for name, v in groups.items() if "无法还原" in name)
        for index, slug in enumerate(MEMBERS):
            plottable = len(self.revenue[slug])
            self.assertEqual(printed[index] + derived[index], plottable,
                             f"{slug}: printed + derived should be the plottable quarters")
            if slug == "cfr":
                basis = self.series[slug]["quarter_basis"]
                self.assertEqual(printed[index], basis.count("printed"))
                self.assertEqual(derived[index], basis.count("derived"))
                self.assertEqual(missing[index], basis.count("missing"))
            elif slug == "bc":
                basis = self.series[slug]["quarterly"]["basis"]
                self.assertEqual(printed[index], basis.count("printed"))
                self.assertEqual(missing[index], 0)
            else:
                self.assertEqual(derived[index], 0)
                self.assertEqual(missing[index], 0)

    def test_the_long_window_chart_runs_the_union_of_the_six(self) -> None:
        union = sorted(set().union(*(set(r) for r in self.revenue.values())),
                       key=lambda q: (int(q[:4]), int(q[5])))
        for fragment in ("把窗口拉到", "两种算法", "谁让你按季度看见中国", "直营占比"):
            self.assertEqual(self.exhibit_titled(fragment)["xlabels"], union,
                             f"{fragment}: the long charts share one axis")

    # ── the numbers ─────────────────────────────────────────────────────────
    def test_every_own_basis_rate_is_the_companys_own_or_is_marked_derived(self) -> None:
        """The page's central chart, cell by cell.

        The two claims being checked together: a company that publishes a
        quarterly rate is shown that rate untouched, and a company that does not
        is shown this page's own arithmetic *and labelled as such*. Getting the
        second half wrong is the quiet failure -- a derived rate printed without
        the D reads exactly like a disclosed one.
        """
        exhibit = self.exhibit_titled("六家在共同的")
        short = {m["slug"]: m["short"] for m in self.staging["members"]}
        for slug in MEMBERS:
            published = printed_growth(slug, self.series[slug])
            values = self.series_named(exhibit, short[slug])
            if published is None:
                name = next(s["name"] for s in exhibit["series"] if short[slug] in s["name"])
                self.assertIn("D", name, f"{slug}: a self-computed rate must be marked")
            expected = [self.rates[slug][q] for q in self.rate_window]
            for quarter, got, want in zip(self.rate_window, values, expected):
                self.assertAlmostEqual(got, want, places=4,
                                       msg=f"{slug} {quarter}")

    def test_the_spread_is_the_column_range_of_that_chart(self) -> None:
        spread = self.exhibit_titled("之间的极差")
        six = next(s for s in spread["series"] if s["name"].startswith("六家"))
        # The spread chart now runs on the longer four-company axis, so the
        # six-company line is null before the six-company window opens and is
        # the column range of Exhibit 「六家在共同的」 inside it.
        own = self.exhibit_titled("六家在共同的")
        offset = spread["xlabels"].index(own["xlabels"][0])
        for index in range(len(spread["xlabels"])):
            if index < offset:
                self.assertIsNone(six["values"][index], spread["xlabels"][index])
                continue
            column = [s["values"][index - offset] for s in own["series"]]
            self.assertAlmostEqual(six["values"][index], max(column) - min(column),
                                   places=4, msg=spread["xlabels"][index])

    def test_the_scale_bars_are_four_quarters_of_euro_revenue(self) -> None:
        exhibit = self.exhibit_titled("最近四个季度的收入合计")
        last_four = self.window[-4:]
        short = {m["slug"]: m["short"] for m in self.staging["members"]}
        self.assertEqual(exhibit["xlabels"], [short[slug] for slug in MEMBERS])
        for index, slug in enumerate(MEMBERS):
            expected = sum(self.revenue[slug][q] for q in last_four)
            self.assertAlmostEqual(exhibit["values"][index], expected, places=4, msg=slug)

    def test_the_two_small_caps_are_converted_out_of_euro_thousands(self) -> None:
        """The unit trap, asserted as an order of magnitude rather than a value.

        Zegna and Cucinelli file in euro thousands and the other four in euro
        millions. A missed conversion would put two bars a thousand times too
        tall on a chart whose whole content is relative size, and every other
        check in this file would still pass, because the two paths would have
        made the same mistake only if this file also skipped it -- which is why
        the assertion is against the raw series, not against the accessor.
        """
        exhibit = self.exhibit_titled("最近四个季度的收入合计")
        for slug in ("zgn", "bc"):
            raw = self.series[slug]["quarterly"]["revenue_eur_k"][-1]
            index = MEMBERS.index(slug)
            self.assertLess(exhibit["values"][index], raw / 100,
                            f"{slug} looks like it is still in euro thousands")
            self.assertGreater(exhibit["values"][index], 100,
                               f"{slug} is implausibly small even in euro millions")

    def test_the_wedge_is_the_companys_rate_minus_this_pages_arithmetic(self) -> None:
        exhibit = self.exhibit_titled("公司自己的口径比欧元口径高出多少")
        short = {m["slug"]: m["short"] for m in self.staging["members"]}
        drawn = {s["name"] for s in exhibit["series"]}
        for slug in MEMBERS:
            published = printed_growth(slug, self.series[slug])
            if published is None:
                self.assertNotIn(short[slug], "".join(drawn),
                                 f"{slug} has no company rate and cannot have a wedge")
                continue
            values = self.series_named(exhibit, short[slug])
            # This chart runs on the window its own four members share, which is
            # longer than the six-company one.
            for index, quarter in enumerate(exhibit["xlabels"]):
                if quarter not in self.rates[slug]:
                    self.assertIsNone(values[index], f"{slug} {quarter}")
                    continue
                reported = year_on_year(self.revenue[slug], quarter)
                if reported is None:
                    # No year-ago euro figure on this site, so there is nothing
                    # to subtract. A zero here would read as "no wedge", which
                    # is the opposite of "not measurable".
                    self.assertIsNone(values[index], f"{slug} {quarter}")
                    continue
                self.assertAlmostEqual(values[index], self.rates[slug][quarter] - reported,
                                       places=4, msg=f"{slug} {quarter}")

    def test_the_seam_chart_measures_the_gap_it_describes(self) -> None:
        """Richemont's two rates, and the size of their disagreement.

        This is the page's evidence for refusing to divide a euro line by its
        own year-ago value, so the note states a number. The number is checked
        here against the series rather than against the chart that prints it.
        """
        data = self.series["cfr"]
        printed = {norm_quarter(q): float(v) for q, v in
                   zip(data["quarters"], data["quarterly_actual_pct"]["total"]) if v is not None}
        gaps = {}
        for quarter, rate in printed.items():
            mine = year_on_year(self.revenue["cfr"], quarter)
            if mine is not None:
                gaps[quarter] = abs(mine - rate)
        self.assertTrue(gaps)
        worst = max(gaps, key=gaps.get)
        exhibit = self.exhibit_titled("两种算法")
        self.assertIn(f"{gaps[worst]:.1f}pp", exhibit["note"])
        self.assertIn(worst, exhibit["note"])
        for quarter in (q for q, gap in gaps.items() if gap > 1.0):
            self.assertIn(quarter, exhibit["note"],
                          "every quarter where the two disagree is named in the note")

    def test_the_margin_chart_excludes_the_company_on_another_clock(self) -> None:
        """Five lines, not six, and the sixth is on its own chart.

        Richemont's financial year ends 31 March, so it closes halves on
        30 September and 31 March. Putting it on the shared axis would read its
        April-September against everyone else's January-June -- a comparison
        that looks fine and is off by a quarter.
        """
        exhibit = self.exhibit_titled("同一根日历轴上")
        calendar = [slug for slug in MEMBERS if slug != "cfr"]
        margins = {slug: half_margin(slug, self.series[slug]) for slug in calendar}
        # The union, from the first half any of them can fill: cutting to the
        # intersection made this seven halves long while three of the five
        # reach 2016. A member that has not started yet is a gap.
        shared = sorted(set().union(*(set(m) for m in margins.values())),
                        key=lambda h: (h.split()[1], h.split()[0]))
        self.assertEqual(exhibit["xlabels"], shared)
        self.assertGreaterEqual(len(shared), 20, "the half axis should reach 2016")
        self.assertEqual(len(exhibit["series"]), len(calendar))
        short = {m["slug"]: m["short"] for m in self.staging["members"]}
        self.assertNotIn(short["cfr"], "".join(s["name"] for s in exhibit["series"]))
        for slug in calendar:
            values = self.series_named(exhibit, short[slug])
            for index, half in enumerate(shared):
                if half not in margins[slug]:
                    self.assertIsNone(values[index], f"{slug} {half}")
                    continue
                self.assertAlmostEqual(values[index], margins[slug][half], places=4,
                                       msg=f"{slug} {half}")

    def test_a_line_that_starts_late_is_named_and_dated(self) -> None:
        """A short line has to say where it starts, and whose floor it is.

        Four of the five lines were seven halves long until LVMH's profit was
        typed back to 2016; the one that stayed short is a different kind of
        gap. Neither the reader nor this page can tell "the company did not
        publish" from "this site has not read it" by looking at the chart, so
        the note names the line, dates its first reading and says the floor is
        the site's until someone checks. A line that later reaches the left
        edge turns this red, which is the point.
        """
        exhibit = self.exhibit_titled("同一根日历轴上")
        calendar = [slug for slug in MEMBERS if slug != "cfr"]
        short = {m["slug"]: m["short"] for m in self.staging["members"]}
        zh = {m["slug"]: m["zh"] for m in self.staging["members"]}
        axis = exhibit["xlabels"]
        late = {}
        for slug in calendar:
            values = self.series_named(exhibit, short[slug])
            first = next((i for i, v in enumerate(values) if v is not None), None)
            self.assertIsNotNone(first, f"{slug} has no reading at all")
            if first:
                late[slug] = first
        note = exhibit["note"]
        if not late:
            self.assertIn(f"{cn_count(len(calendar))}条线都画满了", note)
            return
        for slug, first in late.items():
            self.assertIn(f"{zh[slug]}从 {axis[first]} 起（{len(axis) - first}/{len(axis)}）", note)
        self.assertIn("是本站的接入边界", note)
        # The count of full-length lines, so a backfill that lands has to be
        # recorded here rather than quietly leaving the sentence behind.
        self.assertIn(cn_count(len(calendar) - len(late)) + "条画满了", note)

    def test_the_off_clock_chart_runs_the_fiscal_halves(self) -> None:
        exhibit = self.exhibit_titled("自己的时钟")
        data = self.series["cfr"]
        self.assertEqual(exhibit["xlabels"], data["halves"])
        self.assertEqual(exhibit["bar"]["values"], data["half_eur_m"]["sales"])
        for index, label in enumerate(data["halves"]):
            expected = (data["half_eur_m"]["operating_profit"][index]
                        / data["half_eur_m"]["sales"][index] * 100)
            self.assertAlmostEqual(exhibit["line"]["values"][index], expected, places=4,
                                   msg=label)

    # ── the sentences that a roll could turn false ──────────────────────────
    def test_the_china_claim_counts_the_companies_that_actually_print_one(self) -> None:
        """「只有一家」 is a universal claim, so it is checked against the six.

        Zegna is the only one of the six whose series carries a Greater China
        line at quarterly cadence. That is a fact about this site's connected
        data as much as about the companies, and the page says so -- but the
        count itself must not be able to go stale, which is what this checks.
        """
        with_china = [slug for slug in MEMBERS
                      if "greater_china" in json.dumps(self.series[slug].get("quarterly", {}))]
        self.assertEqual(with_china, ["zgn"],
                         "the China sentence on this page names one company; "
                         "re-read it before moving this assertion")
        exhibit = self.exhibit_titled("谁让你按季度看见中国")
        self.assertIn("只有", exhibit["note"])
        short = {m["slug"]: m["short"] for m in self.staging["members"]}
        self.assertIn(short["zgn"], exhibit["note"])
        self.assertEqual(
            len([s for s in exhibit["series"] if "大中华区" in s["name"]]), 1)

    def test_the_exclusion_rule_census_matches_the_definitions_on_file(self) -> None:
        rules = {}
        for entry in self.staging["growth_metrics"]:
            key = "unknown" if entry["excludes"] is None else " + ".join(sorted(entry["excludes"]))
            rules.setdefault(key, []).append(entry["slug"])
        self.assertEqual(set(rules) - {"unknown"}, {"fx", "fx + perimeter"})
        headline = self.payload["headline"]
        self.assertIn("两种剔除法", headline,
                      "the headline counts the exclusion rules; recount before editing")
        self.assertEqual(sorted(e["slug"] for e in self.staging["growth_metrics"]), sorted(MEMBERS))

    def test_no_quarterly_profit_figure_reaches_the_page(self) -> None:
        """The page claims none of the six publishes a quarterly income statement.

        Checked as a property of the published payload rather than of the
        companies: whatever the filings do, no chart here may put a profit or a
        margin on a quarterly axis, because that would be a number this page
        invented.
        """
        for exhibit in self.exhibits.values():
            labels = exhibit.get("xlabels") or []
            quarterly = all(re.fullmatch(r"\d{4}Q[1-4]", str(label)) for label in labels)
            if not quarterly or not labels:
                continue
            self.assertNotIn("利润率", exhibit["title"],
                             f"Ex{exhibit['n']} puts a margin on a quarterly axis")

    def test_the_page_states_its_period_once_and_from_the_data(self) -> None:
        latest = self.window[-1]
        display = f"Q{latest[5]} {latest[:4]}"
        self.assertEqual(self.payload["latest"]["disclosed_period_label"], display)
        self.assertEqual(self.staging["latest"]["period"], display)
        self.assertEqual(self.staging["quarter_story"]["period"], display)
        self.assertTrue(self.payload["headline"].startswith(display))
        releases = {
            "mc": self.series["mc"]["latest"]["release_date"],
            "cfr": self.series["cfr"]["latest"]["release_date"],
            "ker": self.series["ker"]["latest"]["release_date"],
            "zgn": self.series["zgn"]["latest"]["release_date"],
            "bc": self.series["bc"]["latest"]["release_date"],
            "rms": self.series["rms"]["release_dates"][self.series["rms"]["latest"]["period"]],
        }
        self.assertEqual(self.payload["latest"]["release_date"], max(releases.values()),
                         "a cross page is only as current as its slowest member")

    def test_a_stale_period_stamp_stops_the_build(self) -> None:
        """The roll guard, exercised rather than trusted.

        `series/luxury.json` carries no figures, so the only thing a roll can
        leave behind is its review date -- and a review date that silently
        belongs to the previous quarter is exactly the failure the rest of this
        repo's `latest` blocks exist to stop.
        """
        from build import luxury
        stale = json.loads(json.dumps(self.staging))
        stale["latest"]["period"] = "Q1 2019"
        with self.assertRaises(ValueError):
            luxury.build_payload(stale)
        stale = json.loads(json.dumps(self.staging))
        stale["quarter_story"]["period"] = "Q1 2019"
        with self.assertRaises(ValueError):
            luxury.build_payload(stale)

    def test_mislabelling_a_companys_clock_stops_the_build(self) -> None:
        """The other half of the two-clock rule, exercised.

        `test_the_margin_chart_excludes_the_company_on_another_clock` checks the
        published chart. This checks what happens when the builder is told the
        wrong thing: before the guard existed, marking Richemont as a
        calendar-half filer produced an `IndexError` from an empty intersection
        several functions later. The build did stop, but by accident and with a
        message that named neither company nor clock -- which is the difference
        between a gate and a crash.
        """
        from build import luxury
        original = luxury.cfr_view

        def on_the_wrong_clock(data: dict) -> dict:
            return {**original(data), "calendar_halves": True}

        luxury.cfr_view = on_the_wrong_clock
        luxury.VIEWS["cfr"] = on_the_wrong_clock
        try:
            with self.assertRaises(ValueError) as caught:
                luxury.build_payload(self.staging)
            self.assertIn("cfr", str(caught.exception))
            self.assertIn("calendar_halves", str(caught.exception))
        finally:
            luxury.cfr_view = original
            luxury.VIEWS["cfr"] = original

    def test_no_story_placeholder_reaches_the_reader(self) -> None:
        """`fill_story` only substitutes lower-case names, and says nothing about the rest.

        `{ac4}` shipped verbatim into the headline for exactly this reason: a
        digit in the name put it outside the substitution pattern, so it was
        neither filled nor reported -- it was simply printed. The builder cannot
        catch this; the published payload can.
        """
        text = json.dumps(self.payload, ensure_ascii=False)
        self.assertEqual(re.findall(r"\{[a-z_][a-z_0-9]*\}", text), [])

    def test_the_page_reads_only_the_six_series_it_declares(self) -> None:
        """No filings data of its own, and no seventh company smuggled in."""
        source = (ROOT / "build" / "luxury.py").read_text(encoding="utf-8")
        named = set(re.findall(r'_load\("([a-z]+)"\)', source))
        self.assertEqual(named, set(), "series are loaded through the member list, not by name")
        self.assertNotIn("_checks", self.staging,
                         "a cross page's checks are this file, not a copied block")
        figures = [key for key in self.staging
                   if key not in {"schema_version", "_provenance", "_no_checks_rationale",
                                  "page", "members", "latest", "growth_metrics",
                                  "quarter_story", "sources", "factor_panel", "regimes"}]
        self.assertEqual(figures, [], f"unexpected data in series/luxury.json: {figures}")


if __name__ == "__main__":
    unittest.main()
