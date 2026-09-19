"""Reconciliation, shape and roll tests for the TJX page.

Same purpose as the other companies': nothing derived reaches the page until it
has been checked against a statement identity or a figure the company disclosed
separately.  TJX gives two identities that close exactly, which is what licenses
the quarterly series to be published without a single estimate in it:

    net sales − cost of sales − SG&A − other charges + net interest income = income before taxes
    Σ segment profit − general corporate expense − other charges + net interest income = income before taxes

Both hold to the dollar in every quarter, including the fiscal fourths that have
no 10-Q behind them, because TJX prints a thirteen-week column in its Q4 release
rather than leaving the quarter to be differenced out of the year.

The guidance record needs its own guards.  It runs across a stock split, a
seven-quarter withdrawal and quarters whose adjusting item did not exist when
the range was set, and the tempting mistake in every one of those places is to
make the record look cleaner than it is.  So the counts through the quarter this
page was migrated at are pinned by value (``PINNED_THROUGH``), the withdrawal is
pinned as a gap rather than a run of misses, the split conversion is pinned on
the one pair that straddles it, and the publication lag -- the fact that the
outlook goes out *after* the quarter has begun -- is recomputed from the dates.

Rolling the page is a data edit (CLAUDE.md §9): nothing in this file names the
page's quarter or its figures.  `TjxChecksTest` compares the page with
`_checks`, a separate reading of the quarter's release; `TjxRollTest` breaks and
rolls the series to show that a stale block stops the build, an absent story
takes its sentences with it, every "only / never / first / lowest since" claim is
computed rather than remembered, and a next, fourth and first quarter build
without touching the code.  Expected values are computed here, independently of
the builder's helpers.
"""

from __future__ import annotations

import copy
import datetime
import json
import re
import statistics
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.all import ENTRIES, GROUPS, build_all, roster_payload  # noqa: E402
from build.board import headroom  # noqa: E402
from build.tjx import STAGING_PATH, build_payload, compact_period  # noqa: E402

# History up to here is closed and is pinned by value; anything later is checked
# as an invariant. It sits well before the quarter this page was migrated at
# (Q2 2026), so a rehearsal that rolls the series back a few quarters still
# carries every pinned quarter.
PINNED_THROUGH = "Q4 2024"
# The series carried only for the reviewed quarters start here.
THIN_FROM = "Q3 2024"
# Two finished quarters of the EPS record have no actual in the series (the
# FY2013 and FY2014 fourth quarters); they are holes, not misses.
EPS_HOLES = ("Q4 2012", "Q4 2013")
STAMPED = ("prior_kpi", "next_kpi", "followup_closure", "ytd_usd_m", "full_year_outlook",
           "one_off_usd_m", "adjusted_segment_margins_pct", "store_plan", "guidance",
           "quarter_story")
STORIES = tuple(key for key in STAMPED if key != "ytd_usd_m")
SEGMENTS = ("marmaxx", "homegoods", "canada", "international")
CN = "零一二三四五六七八九"


def load() -> dict:
    return json.loads(STAGING_PATH.read_text(encoding="utf-8"))


def js_payload(path: Path, assignment: str) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split(f"{assignment} = ", 1)[1].rsplit(";", 1)[0]
    return json.loads(body)


def exhibits_of(payload: dict) -> list[dict]:
    return [ex for section in payload["sections"] for ex in section["exhibits"]]


def find(payload: dict, prefix: str) -> dict | None:
    return next((ex for ex in exhibits_of(payload) if ex["title"].startswith(prefix)), None)


def text_of(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def short(period: str) -> str:
    quarter, year = period.split()
    return f"{quarter}'{year[2:]}"


def cn(n: int) -> str:
    """A small count the way the page spells it."""
    if n == 2:
        return "两"
    if n < 10:
        return CN[n]
    tens, ones = divmod(n, 10)
    return ("" if tens == 1 else CN[tens]) + "十" + (CN[ones] if ones else "")


def order(period: str) -> int:
    quarter, year = period.split()
    return int(year) * 4 + int(quarter[1])


def next_period(period: str) -> str:
    quarter, year = int(period[1]), int(period.split()[1])
    return f"Q1 {year + 1}" if quarter == 4 else f"Q{quarter + 1} {year}"


def next_fiscal(label: str) -> str:
    year, quarter = int(label[2:6]), int(label[-1])
    return f"FY{year + 1}Q1" if quarter == 4 else f"FY{year}Q{quarter + 1}"


def day(text: str) -> datetime.date:
    return datetime.date.fromisoformat(text)


def starts(st: dict) -> list[datetime.date]:
    """First day of each guided quarter, from the quarter ends the series carries."""
    rec = st["quarterly_guidance_history"]
    ends = {**rec["early_quarter_ends"], **dict(zip(st["periods"], st["period_ends"]))}
    out = []
    for quarter in rec["quarters"]:
        number, year = int(quarter[1]), int(quarter.split()[1])
        before = f"Q4 {year - 1}" if number == 1 else f"Q{number - 1} {year}"
        out.append(day(ends[before]) + datetime.timedelta(days=1))
    return out


def pinned(record: dict) -> int:
    """How many leading entries of the guidance record are closed history."""
    return sum(1 for q in record["quarters"] if order(q) <= order(PINNED_THROUGH))


def story_texts(block: dict) -> list[str]:
    """The literal sentences a story block carries -- the ones with no placeholder."""
    texts = []
    for value in block.values():
        values = value if isinstance(value, list) else [value]
        for text in values:
            if isinstance(text, str) and len(text) >= 8 and "{" not in text:
                texts.append(text.strip())
    return texts


def with_thresholds(src: dict) -> dict:
    """The series with threshold blocks for its own quarter, invented if it has none."""
    st = copy.deepcopy(src)
    period = st["periods"][-1]
    if "prior_kpi" not in st:
        st["prior_kpi"] = {"period": period, "quantified": [
            {"metric": "合并同店销售", "direction": "up", "threshold": 3.0, "unit": "pct",
             "measure": "comp_consolidated", "meaning": "测试用的门槛"},
            {"metric": "Marmaxx 同店销售", "direction": "up", "threshold": 2.0, "unit": "pct",
             "measure": "comp_marmaxx"},
            {"metric": "毛利率", "direction": "up", "threshold": 30.0, "unit": "pct",
             "measure": "gross_margin_adjusted"},
            {"metric": "每店存货同比 D", "direction": "down", "threshold": 5.0, "unit": "pct",
             "measure": "inventory_per_store_yoy"},
            {"metric": "累计资本开支 / 销售额 D", "direction": "down", "threshold": 3.8, "unit": "pct",
             "measure": "ytd_capex_intensity"}],
            "inventory_warning": {"comp_below_pct": 3.0, "inventory_yoy_above_pct": 5.0}}
    if "next_kpi" not in st:
        st["next_kpi"] = {"period": period, "quantified": [
            {"metric": "HomeGoods 分部利润率", "direction": "up", "threshold": 10.0, "unit": "pct",
             "measure": "homegoods_margin_adjusted"},
            {"metric": "税前利润率", "direction": "up", "threshold": 11.0, "unit": "pct",
             "measure": "pretax_margin_adjusted"}]}
    st["prior_kpi"]["period"] = st["next_kpi"]["period"] = period
    return st


def roll_forward(src: dict) -> dict:
    """The series one quarter on, with plausible synthetic figures and no story.

    Every array gets a cell (from the year-ago cell, grown), the pending guided
    quarter is settled above its range, the next one is guided, the year-to-date
    block is re-summed for the new fiscal quarter and the release is added to
    `sources`. Blocks that describe one release are dropped, as a roll that has
    not yet written them would have them.
    """
    st = copy.deepcopy(src)
    st.pop("_checks", None)
    for key in STORIES:
        st.pop(key, None)
    period = next_period(st["periods"][-1])
    fiscal = next_fiscal(st["fiscal_labels"][-1])
    end = day(st["period_ends"][-1]) + datetime.timedelta(weeks=13)
    release = end + datetime.timedelta(days=18)
    st["periods"].append(period)
    st["period_ends"].append(end.isoformat())
    st["fiscal_labels"].append(fiscal)
    st["release_dates"].append(release.isoformat())
    fin, seg, segm = st["financials"], st["segments_usd_m"], st["segment_margins_pct"]
    for key in ("net_sales_usd_m", "cost_of_sales_usd_m", "sga_usd_m", "pretax_income_usd_m",
                "income_tax_usd_m", "net_income_usd_m", "interest_income_net_usd_m"):
        fin[key].append(round(fin[key][-4] * 1.05, 3))
    fin["diluted_shares_m"].append(fin["diluted_shares_m"][-1] - 4)
    fin["diluted_eps_usd"].append(round(fin["diluted_eps_usd"][-4] * 1.08, 2))
    for key in ("adjusted_diluted_eps_usd", "adjusted_pretax_margin_pct",
                "adjusted_gross_margin_pct", "other_charges_usd_m"):
        fin[key].append(None)
    fin["dividend_declared_per_share_usd"].append(fin["dividend_declared_per_share_usd"][-1])
    sales = fin["net_sales_usd_m"]
    fin["net_sales_yoy_pct"].append(round((sales[-1] / sales[-5] - 1) * 100, 4))
    fin["gross_margin_pct"].append(round((sales[-1] - fin["cost_of_sales_usd_m"][-1]) / sales[-1] * 100, 4))
    fin["sga_pct_of_sales"].append(round(fin["sga_usd_m"][-1] / sales[-1] * 100, 4))
    fin["pretax_margin_pct"].append(round(fin["pretax_income_usd_m"][-1] / sales[-1] * 100, 4))
    fin["effective_tax_rate_pct"].append(fin["effective_tax_rate_pct"][-4])
    for name in SEGMENTS:
        for part in ("sales", "profit"):
            key = f"{name}_{part}"
            seg[key].append(round(seg[key][-4] * 1.05, 3))
        segm[f"{name}_margin_pct"].append(round(seg[f"{name}_profit"][-1] / seg[f"{name}_sales"][-1] * 100, 4))
    seg["total_segment_profit"].append(round(sum(seg[f"{n}_profit"][-1] for n in SEGMENTS), 3))
    seg["general_corporate_expense_prior_year"].append(seg["general_corporate_expense"][-4])
    seg["general_corporate_expense"].append(round(seg["general_corporate_expense"][-4] * 1.05, 3))
    comp = st["comparable_sales_pct"]
    for key, value in zip(("consolidated", "marmaxx", "homegoods", "canada", "international"),
                          (4.0, 3.0, 5.0, 4.0, 5.0)):
        comp[key].append(value)
    ops = st["operations"]
    ops["store_count"].append(ops["store_count"][-1] + 25)
    ops["store_net_additions"].append(25)
    ops["square_feet_m"].append(round(ops["square_feet_m"][-1] + 0.5, 1))
    ops["merchandise_inventories_usd_m"].append(round(ops["merchandise_inventories_usd_m"][-4] * 1.04))
    ops["inventory_per_store_usd_k"].append(
        round(ops["merchandise_inventories_usd_m"][-1] * 1000 / ops["store_count"][-1], 2))
    rec = st["quarterly_guidance_history"]
    pending = len(rec["quarters"]) - 1
    rec["actual_eps_usd"][pending] = round(rec["guide_eps_hi_usd"][pending] + 0.03, 2)
    rec["actual_pretax_margin_pct"][pending] = round(rec["guide_pretax_margin_hi_pct"][pending] + 0.3, 4)
    rec["actual_comp_pct"][pending] = rec["guide_comp_hi_pct"][pending] + 1
    guided = next_period(period)
    for key, value in (("quarters", guided), ("fiscal_labels", next_fiscal(fiscal)),
                       ("guidance_published", release.isoformat()),
                       ("guide_eps_lo_usd", 1.30), ("guide_eps_hi_usd", 1.33),
                       ("actual_eps_usd", None), ("guide_pretax_margin_lo_pct", 11.8),
                       ("guide_pretax_margin_hi_pct", 11.9), ("actual_pretax_margin_pct", None),
                       ("guide_comp_lo_pct", 2.0), ("guide_comp_hi_pct", 3.0), ("actual_comp_pct", None)):
        rec[key].append(value)
    fq = int(fiscal[-1])
    this = sales[-fq:]
    last = sales[-fq - 4:-4]
    st["ytd_usd_m"] = {
        "period": period,
        "periods": [f"YTD {fiscal[:6]} prior", f"YTD {fiscal[:6]}"],
        "operating_cash_flow": [round(sum(last) * 0.12), round(sum(this) * 0.13)],
        "capital_expenditures": [round(sum(last) * 0.035), round(sum(this) * 0.036)],
        "share_repurchases": [700 * fq, 750 * fq],
        "dividends_paid": [450 * fq, 500 * fq],
        "receivables_and_other_assets_change": [-40, 60],
        "inventories_change": [-500, -450],
    }
    st["sources"].insert(0, {"label": f"TJX FY{fiscal[2:6]} Q{fq} 业绩新闻稿（8-K EX-99.1，{release}）",
                             "url": "https://www.sec.gov/Archives/edgar/data/109198/synthetic.htm"})
    st["latest"].update({"period": period, "fiscal_label": f"FY{fiscal[2:6]} Q{fq}",
                         "period_end": end.isoformat(), "release_date": release.isoformat(),
                         "analysis_date": (release + datetime.timedelta(days=10)).isoformat(),
                         "audit_status": "unaudited"})
    return st


class TjxDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = load()
        cls.payload = build_payload(cls.source)
        cls.exhibits = exhibits_of(cls.payload)
        cls.by_section = {
            section["id"]: section["exhibits"] for section in cls.payload["sections"]
        }
        cls.record = cls.source["quarterly_guidance_history"]
        cls.fin = cls.source["financials"]
        cls.seg = cls.source["segments_usd_m"]
        cls.periods = cls.source["periods"]

    # ── shape ────────────────────────────────────────────────────────────────
    def test_the_comp_series_declares_its_e_commerce_boundary(self) -> None:
        """One seam the filings footnote and the page did not.

        TJX began including e-commerce in comparable sales with the quarter ended
        2025-05-03 (its FY2026 Q1, this page's Q1 2025 -- the release footnote
        reads "Comparable sales for FY2026 include e-commerce") and has never
        restated the earlier quarters, so the line joins two populations. Nothing
        here is provably wrong -- e-commerce is about 2% of sales, the company
        calls the consolidated impact immaterial, and comps print as whole
        integers, so no cell can be shown to differ. That is exactly why it needs
        saying rather than fixing: an unprovable seam is one no arithmetic check
        will ever raise.

        A refutation pass killed the other half of the original report: the 2019
        Sierra footnote change is NOT a second seam, because TJX printed all four
        FY2019 quarters under both footnote regimes and all twenty division cells
        are identical. Only this one survived. The page once dated the boundary
        「2025 年第二季」, the company's quarter number printed under this page's
        calendar year; the label is now read from the series.
        """
        drawn = " ".join(
            ex.get("src_extra", "") for section in self.payload["sections"]
            for ex in section["exhibits"])
        self.assertIn("2025-05-03", drawn,
                      "the e-commerce boundary is not stated anywhere a reader sees")
        self.assertIn("电商", drawn)
        index = self.source["period_ends"].index("2025-05-03")
        quarter, year = self.periods[index].split()
        self.assertIn(f"{year} 年第{CN[int(quarter[1])]}季（截至 2025-05-03）", drawn)

    def test_no_caption_carries_markdown(self) -> None:
        """Captions are HTML: a `**` in them prints as two asterisks."""
        for exhibit in self.exhibits:
            for field in ("title", "note", "src_extra"):
                with self.subTest(exhibit=exhibit["n"], field=field):
                    self.assertNotIn("**", exhibit.get(field) or "")
        self.assertNotIn("**", self.payload["brief"] + self.payload["headline"])

    def test_the_window_starts_in_2016_and_says_where_it_is_thin(self) -> None:
        """Every block is on one axis; the short series are named and sit in a tail.

        The series carried for the reviewed quarters only are listed in
        `short_series_notes`, each with its reason, and every value they hold
        sits at or after THIN_FROM. Comparable sales is thin in a different way
        and for a stated reason too: twelve of the quarters to 2026 have no
        consolidated comp at all -- one release printed none, seven published
        only an "open-only" comp against stores that were actually open, and the
        2022 releases gave U.S. comps only.
        """
        periods = self.periods
        self.assertEqual(periods[0], "Q1 2016")
        self.assertEqual([order(p) for p in periods],
                         list(range(order(periods[0]), order(periods[0]) + len(periods))))
        for key in ("period_ends", "fiscal_labels", "release_dates"):
            self.assertEqual(len(self.source[key]), len(periods), key)
        thin = set(self.source["short_series_notes"])
        tail = periods.index(THIN_FROM)
        for group in ("financials", "segments_usd_m", "segment_margins_pct",
                      "comparable_sales_pct", "operations"):
            for key, values in self.source[group].items():
                if key.startswith("_") or not isinstance(values, list):
                    continue
                self.assertEqual(len(values), len(periods), f"{group}.{key}")
                reported = [i for i, value in enumerate(values) if value is not None]
                if key in thin:
                    self.assertTrue(all(i >= tail for i in reported), f"{group}.{key}")
                elif group == "comparable_sales_pct":
                    # the holes are the 2020-2022 closures and U.S.-only years; none since
                    holes = [i for i, value in enumerate(values) if value is None]
                    self.assertTrue(all(order(periods[i]) <= order(PINNED_THROUGH) for i in holes),
                                    f"{group}.{key}")
                elif key in ("other_charges_usd_m", "adjusted_pretax_margin_pct"):
                    continue
                elif key == "net_sales_yoy_pct":
                    self.assertEqual(reported, list(range(4, len(periods))), "no year-ago base for 2016")
                else:
                    self.assertEqual(len(reported), len(periods), f"{group}.{key}")
        closed = sum(1 for p in periods if order(p) <= order(PINNED_THROUGH))
        self.assertEqual(sum(1 for v in self.source["comparable_sales_pct"]["consolidated"][:closed]
                             if v is None), 12)

    def test_calendar_labels_map_onto_the_fiscal_ones(self) -> None:
        """TJX's FY(N) Qk is this page's Qk (N-1); a slip here silently

        compares different three-month periods against the other pages."""
        for period, fiscal in zip(self.periods, self.source["fiscal_labels"]):
            quarter, year = period.split()
            fiscal_year, fiscal_quarter = re.match(r"FY(\d{4})Q(\d)", fiscal).groups()
            self.assertEqual(quarter, f"Q{fiscal_quarter}")
            self.assertEqual(int(year), int(fiscal_year) - 1)

    def test_every_quarter_is_thirteen_or_fourteen_weeks(self) -> None:
        """The subtitle counts the weeks from the dates; the dates have to allow it."""
        ends = [day(end) for end in self.source["period_ends"]]
        for before, after, period in zip(ends, ends[1:], self.periods[1:]):
            with self.subTest(period=period):
                self.assertIn((after - before).days, (91, 98))
        weeks = (ends[-1] - ends[-2]).days // 7
        self.assertTrue(self.payload["subtitle"].startswith(f"{cn(weeks)}周截至 {ends[-1]}"))

    # ── statement identities ─────────────────────────────────────────────────
    def test_income_statement_closes_to_the_dollar(self) -> None:
        """Sales - cost - SG&A - other charges + net interest = pretax income.

        The "other charges" term is the one the eight-quarter window never
        needed: six quarters since 2016 carry a named line between SG&A and
        pretax (impairment, litigation, restructuring), and without it the
        identity misses by the whole charge -- 82.9 in Q3 2016, 312.2 in Q4 2020.
        """
        fin = self.fin
        for index, period in enumerate(self.periods):
            derived = (fin["net_sales_usd_m"][index]
                       - fin["cost_of_sales_usd_m"][index]
                       - fin["sga_usd_m"][index]
                       - (fin["other_charges_usd_m"][index] or 0.0)
                       + fin["interest_income_net_usd_m"][index])
            # assertEqual on floats: this passed on eight quarters and started
            # failing at 824.9689999999998 != 824.969 the moment the record grew.
            # The identity is exact in the filing; binary addition of
            # three-decimal dollars is not, so the tolerance is a hundredth of a
            # million -- far tighter than any real misread.
            self.assertAlmostEqual(derived, fin["pretax_income_usd_m"][index],
                                   delta=0.01, msg=period)

    def test_segment_bridge_closes_to_the_dollar(self) -> None:
        """Σ segment profit − corporate expense + net interest = pretax income.

        This is the bridge the page warns is unreadable *quarter to quarter*,
        because general corporate expense swings by tens of millions. That
        warning is about comparability across quarters, not about the
        arithmetic: within a single quarter it closes exactly, and if it ever
        stopped closing the corporate-expense line would be the first thing to
        have been misread.
        """
        seg, fin = self.seg, self.fin
        for index, period in enumerate(self.periods):
            total = sum(seg[f"{name}_profit"][index] for name in SEGMENTS)
            self.assertAlmostEqual(total, seg["total_segment_profit"][index],
                                   delta=0.01, msg=period)
            # ...and the "other charges" term sits below total segment profit in
            # five of the six quarters that have one -- but not in Q4 2017,
            # where the impairment was booked *inside* Marmaxx and is therefore
            # already in the segment total. A fixed formula misses that quarter
            # by 99.25, which is 8.9% of its pretax income and would look like a
            # data error rather than a presentation one.
            charge = fin["other_charges_usd_m"][index] or 0.0
            if period in self.source["other_charges_note"]["inside_a_segment"]:
                charge = 0.0
            derived = (total - seg["general_corporate_expense"][index] - charge
                       + fin["interest_income_net_usd_m"][index])
            self.assertAlmostEqual(derived, fin["pretax_income_usd_m"][index],
                                   delta=0.01, msg=period)

    def test_the_identity_note_counts_the_quarters_it_closes_over(self) -> None:
        """The note once said the identities closed "在八个季度里" on a 42-quarter page."""
        n = len(self.periods)
        charged = sum(1 for v in self.fin["other_charges_usd_m"] if v is not None)
        note = next(text for text in self.payload["notes"] if "两条恒等式" in text)
        self.assertIn(f"在 {n} 个季度里逐季对得上", note)
        self.assertIn(f"{n} 季核心表", note)
        self.assertIn(f"其中{cn(charged)}季在 SG&A 与税前之间多一条具名费用行", note)
        core = next(t for t in self.payload["tables"] if "核心" in t["title"])
        self.assertTrue(core["title"].startswith(f"{n} 季核心"))
        self.assertEqual(len(core["rows"]), n)

    def test_segment_sales_sum_to_consolidated_net_sales(self) -> None:
        seg, fin = self.seg, self.fin
        for index, period in enumerate(self.periods):
            total = sum(seg[f"{name}_sales"][index] for name in SEGMENTS)
            self.assertAlmostEqual(total, fin["net_sales_usd_m"][index],
                                   delta=0.01, msg=period)

    def test_year_to_date_sales_match_the_quarters_the_company_printed(self) -> None:
        """The page adds the fiscal year's quarters for its year-to-date net sales and
        corporate expense; the release prints both columns, and the sums have to be them."""
        checks = self.source["_checks"]
        fq = int(self.source["fiscal_labels"][-1][-1])
        sales, gce = self.fin["net_sales_usd_m"], self.seg["general_corporate_expense"]
        self.assertAlmostEqual(checks["ytd_net_sales_usd_m"], sum(sales[-fq:]), delta=0.01)
        self.assertAlmostEqual(checks["prior_ytd_net_sales_usd_m"], sum(sales[-fq - 4:-4]), delta=0.01)
        self.assertAlmostEqual(checks["ytd_general_corporate_expense_usd_m"], sum(gce[-fq:]), delta=0.01)
        self.assertAlmostEqual(checks["prior_ytd_general_corporate_expense_usd_m"],
                               sum(gce[-fq - 4:-4]), delta=0.01)
        self.assertNotIn("net_sales", self.source["ytd_usd_m"], "added from the series, not typed")

    def test_the_prior_year_corporate_expense_column_agrees_with_our_own_series(self) -> None:
        """Each release prints last year's corporate expense beside this year's.

        With the series reaching back to 2016 every one of those printed
        comparatives is a quarter this page already carries, so they are a free
        check on the extraction: if the two ever disagree, a quarter was read
        out of the wrong column.
        """
        current, prior = (self.seg["general_corporate_expense"],
                          self.seg["general_corporate_expense_prior_year"])
        reported = [i for i, value in enumerate(prior) if value is not None]
        self.assertEqual(reported, list(range(self.periods.index(THIN_FROM), len(prior))))
        for index in reported:
            self.assertAlmostEqual(prior[index], current[index - 4], delta=0.01,
                                   msg=self.periods[index])

    def test_the_corporate_expense_chart_carries_a_yoy_line(self) -> None:
        """`gs_bar` draws a twelve-period moving average only when handed one,

        and this chart has a filed prior-year column to build a year-on-year
        line from instead; it is the argument the chart makes.
        """
        chart = next(ex for ex in self.by_section["quarter_highlights"]
                     if ex["kind"] == "gs_bar")
        self.assertIn("yoy", chart)
        values = chart["yoy"]["values"]
        self.assertEqual(len(values), len(chart["xlabels"]))
        prior = self.seg["general_corporate_expense_prior_year"]
        self.assertEqual([i for i, v in enumerate(values) if v is not None],
                         [i for i, v in enumerate(prior) if v is not None])
        for value in values:
            if value is not None:
                self.assertIsInstance(value, float)
        checks = self.source["_checks"]
        self.assertAlmostEqual(values[-1], (checks["general_corporate_expense_usd_m"]
                                            / checks["prior_year_general_corporate_expense_usd_m"] - 1) * 100,
                               places=3)

    def test_derived_ratios_match_their_own_inputs(self) -> None:
        fin, ops = self.fin, self.source["operations"]
        for index, period in enumerate(self.periods):
            sales = fin["net_sales_usd_m"][index]
            self.assertAlmostEqual(
                fin["gross_margin_pct"][index],
                (sales - fin["cost_of_sales_usd_m"][index]) / sales * 100, places=3, msg=period)
            self.assertAlmostEqual(
                fin["pretax_margin_pct"][index],
                fin["pretax_income_usd_m"][index] / sales * 100, places=3, msg=period)
            if index >= 4:
                self.assertAlmostEqual(
                    fin["net_sales_yoy_pct"][index],
                    (sales / fin["net_sales_usd_m"][index - 4] - 1) * 100, places=3, msg=period)
            if ops["merchandise_inventories_usd_m"][index] is None:
                self.assertIsNone(ops["inventory_per_store_usd_k"][index], period)
                continue
            self.assertAlmostEqual(
                ops["inventory_per_store_usd_k"][index],
                ops["merchandise_inventories_usd_m"][index] * 1000
                / ops["store_count"][index], places=1, msg=period)

    def test_the_adjusted_segment_margins_are_the_companys_own_arithmetic(self) -> None:
        """reported + disclosed tariff impact = disclosed adjusted, per segment."""
        adj = self.source.get("adjusted_segment_margins_pct")
        if not adj:
            return
        segm = self.source["segment_margins_pct"]
        for name in SEGMENTS:
            block = adj[name]
            self.assertAlmostEqual(block["reported"] + block["tariff_refund_pp"], block["adjusted"],
                                   places=6, msg=name)
            # …and the reported half agrees with the filed dollars it comes from.
            self.assertAlmostEqual(segm[f"{name}_margin_pct"][-1], block["reported"],
                                   places=1, msg=name)

    # ── the guidance record ──────────────────────────────────────────────────
    def test_the_record_is_as_long_as_the_page_says(self) -> None:
        record = self.record
        n = len(record["quarters"])
        for key in ("fiscal_labels", "guidance_published", "guide_eps_lo_usd",
                    "guide_eps_hi_usd", "actual_eps_usd", "guide_pretax_margin_lo_pct",
                    "guide_pretax_margin_hi_pct", "actual_pretax_margin_pct",
                    "guide_comp_lo_pct", "guide_comp_hi_pct", "actual_comp_pct"):
            self.assertEqual(len(record[key]), n, key)
        # every guided quarter up to the page's has its actual, save two old holes;
        # the one after the page's is still pending
        page = record["quarters"].index(self.periods[-1])
        self.assertEqual(page, n - 2)
        self.assertIsNone(record["actual_eps_usd"][-1])
        missing = [q for q, a in zip(record["quarters"][:page + 1], record["actual_eps_usd"])
                   if a is None]
        self.assertEqual(missing, list(EPS_HOLES))
        finished = sum(1 for v in record["actual_eps_usd"] if v is not None)
        band = find(self.payload, "摊薄每股收益（近 16 季）")
        self.assertIn(f"整段记录（{n} 季指引、{finished} 季已完结）", band["note"])

    def test_eps_hit_rate_is_pinned_by_value(self) -> None:
        """32 above / 8 inside / 3 below through PINNED_THROUGH (38 / 8 / 3 when the page
        was migrated at Q2 2026), and the page prints whatever the record now says."""
        record = self.record
        lo, hi = record["guide_eps_lo_usd"], record["guide_eps_hi_usd"]
        actual = record["actual_eps_usd"]
        finished = [i for i, v in enumerate(actual[:pinned(record)]) if v is not None]
        above = [i for i in finished if actual[i] > hi[i]]
        below = [i for i in finished if actual[i] < lo[i]]
        self.assertEqual((len(above), len(finished) - len(above) - len(below), len(below)),
                         (32, 8, 3))
        # The three breaches, named on the chart, are these three quarters.
        self.assertEqual([record["quarters"][i] for i in below],
                         ["Q1 2014", "Q1 2020", "Q1 2022"])
        every = [i for i, v in enumerate(actual) if v is not None]
        up = sum(1 for i in every if actual[i] > hi[i])
        down = sum(1 for i in every if actual[i] < lo[i])
        dev = find(self.payload, "摊薄每股收益相对指引中值的偏离")
        self.assertIn(f"{len(every)} 个已完结季里 {up} 季高于指引上限、"
                      f"{len(every) - up - down} 季落在区间内、{down} 季跌破下限", dev["note"])
        self.assertIn(f"{len(every)} 季已完结的每股收益指引里 {up} 季穿出上限、只有 {down} 季跌破",
                      self.payload["brief"])

    def test_pretax_margin_and_comp_hit_rates_are_pinned_by_value(self) -> None:
        record = self.record
        closed = pinned(record)
        lo, hi = record["guide_pretax_margin_lo_pct"], record["guide_pretax_margin_hi_pct"]
        actual = record["actual_pretax_margin_pct"]
        finished = [i for i, v in enumerate(actual[:closed]) if v is not None and lo[i] is not None]
        above = [i for i in finished if actual[i] > hi[i]]
        below = [i for i in finished if actual[i] < lo[i]]
        self.assertEqual((len(above), len(finished) - len(above) - len(below), len(below)),
                         (9, 0, 1))
        self.assertEqual([record["quarters"][i] for i in below], ["Q4 2022"])

        clo, chi = record["guide_comp_lo_pct"], record["guide_comp_hi_pct"]
        cactual = record["actual_comp_pct"]
        cfinished = [i for i, v in enumerate(cactual[:closed]) if v is not None and clo[i] is not None]
        cabove = [i for i in cfinished if cactual[i] > chi[i]]
        cbelow = [i for i in cfinished if cactual[i] < clo[i]]
        self.assertEqual((len(cabove), len(cfinished) - len(cabove) - len(cbelow), len(cbelow)),
                         (5, 3, 0))

    def test_the_withdrawal_is_a_gap_and_not_a_run_of_misses(self) -> None:
        """Seven quarters have no guidance at all, and the axis has to show it.

        Counting "never missed" over a record that quietly drops the quarters a
        company refused to guide is the failure this test exists to prevent.
        The page once said "五份业绩稿"; seven releases, 2020-05-21 through
        2021-11-17, each say the company is not providing guidance.
        """
        record = self.record
        self.assertEqual(len(record["guidance_gap_quarters"]), 7)
        for quarter in record["guidance_gap_quarters"]:
            self.assertNotIn(quarter, record["quarters"])
        ordinals = [order(q) for q in record["quarters"]]
        jumps = [i for i in range(1, len(ordinals)) if ordinals[i] - ordinals[i - 1] > 1]
        self.assertEqual(len(jumps), 1, "the record has exactly one discontinuity")
        self.assertEqual(ordinals[jumps[0]] - ordinals[jumps[0] - 1] - 1, 7)
        self.assertEqual(record["quarters"][jumps[0] - 1], "Q1 2020")
        self.assertEqual(record["quarters"][jumps[0]], "Q1 2022")
        deviation = find(self.payload, "摊薄每股收益相对指引中值的偏离")
        self.assertEqual(deviation["break_at"], jumps[0])
        releases = record["withheld_releases"]
        self.assertEqual(len(releases), len(record["guidance_gap_quarters"]))
        self.assertIn(f"的{cn(len(releases))}份业绩稿里写明", deviation["note"])
        self.assertTrue(any(f"的{cn(len(releases))}份业绩稿里写明不提供指引" in note
                            for note in self.payload["notes"]))

    def test_the_split_conversion_is_pinned_on_the_pair_that_straddles_it(self) -> None:
        """Guidance for Q3 2018 was published before the 2018-11-06 two-for-one

        and the quarter was reported after it. Converted, US$1.18-1.20 becomes
        US$0.59-0.60 against a reported US$0.61 -- above the range, as the
        unconverted comparison would never have shown.
        """
        record = self.record
        index = record["quarters"].index("Q3 2018")
        self.assertAlmostEqual(record["guide_eps_lo_usd"][index], 0.59, places=6)
        self.assertAlmostEqual(record["guide_eps_hi_usd"][index], 0.60, places=6)
        self.assertEqual(record["actual_eps_usd"][index], 0.61)
        self.assertEqual(record["split_adjusted_before"], "Q3 2018")
        # Every pre-split guidance endpoint is a clean half-cent multiple, which
        # is what a division by two of a cent-quoted range leaves behind.
        for value in record["guide_eps_lo_usd"][:index]:
            self.assertAlmostEqual(value * 200, round(value * 200), places=6)

    def test_the_publication_lag_is_computed_from_the_dates(self) -> None:
        """The outlook goes out with the previous quarter's results, so it lands
        inside the quarter it guides. The page used to carry the lag as a typed
        "9–24 天"; counted from each quarter's first day, the earliest release
        in the record is day 16, not day 9.
        """
        record = self.record
        # the early quarter ends, as the releases printed them, are 13 or 14 weeks
        # apart and run straight into the first quarter of the series
        early = sorted(record["early_quarter_ends"].values()) + [self.source["period_ends"][0]]
        for before, after in zip(early, early[1:]):
            with self.subTest(end=after):
                self.assertIn((day(after) - day(before)).days, (91, 98))
        began = starts(self.source)
        lags = [(day(p) - b).days for p, b in zip(record["guidance_published"], began)]
        self.assertTrue(all(10 < lag < 40 for lag in lags))
        closed = pinned(record)
        self.assertEqual((min(lags[:closed]), max(lags[:closed])), (16, 24))
        timing = f"开始后 {min(lags)}–{max(lags)} 天"
        for exhibit in self.by_section["settled"]:
            if exhibit["kind"] in ("range_band",) or "相对指引中值" in exhibit["title"]:
                with self.subTest(exhibit=exhibit["n"]):
                    self.assertIn(timing, exhibit["note"])
        self.assertIn(f"最早的一次是第 {min(lags)} 天、最晚的一次是第 {max(lags)} 天，"
                      f"平均第 {statistics.fmean(lags):.0f} 天",
                      find(self.payload, "摊薄每股收益（近 16 季）")["note"])
        self.assertIn(f"该季开始后 {min(lags)}–{max(lags)} 天才发布", self.payload["brief"])
        table = next(t for t in self.payload["tables"] if t["title"].startswith("指引兑现明细"))
        self.assertIn(f"已过去 {min(lags)}–{max(lags)} 天", table["title"])

    def test_adjusted_basis_is_used_only_where_the_company_judged_on_it(self) -> None:
        """Q4 2025 (litigation settlement) and Q2 2026 (tariff refunds) are scored
        on the company's adjusted figures, because neither event existed when the
        range was set. Everywhere else the reported figure is used -- including
        Q1 2022, where the company also printed an adjusted EPS (US$0.68, above
        plan) and the page says so rather than claiming none was printed.
        """
        record = self.record
        index = {p: i for i, p in enumerate(self.periods)}
        scored = [q for q in record["scored_on_adjusted"] if q in record["quarters"]
                  and record["actual_eps_usd"][record["quarters"].index(q)] is not None]
        self.assertTrue(scored)
        for quarter in scored:
            r = record["quarters"].index(quarter)
            with self.subTest(quarter=quarter):
                self.assertEqual(record["actual_eps_usd"][r], self.fin["adjusted_diluted_eps_usd"][index[quarter]])
                self.assertAlmostEqual(record["actual_pretax_margin_pct"][r],
                                       self.fin["adjusted_pretax_margin_pct"][index[quarter]], places=6)
        self.assertIn("Q4 2025", scored)
        for quarter, item in record["scored_on_reported_despite_adjusted"].items():
            r = record["quarters"].index(quarter)
            self.assertEqual(record["actual_eps_usd"][r], item["reported"])
            self.assertGreater(item["adjusted"], record["guide_eps_hi_usd"][r])
        note = next(text for text in self.payload["notes"] if "相对 plan" in text)
        self.assertNotIn("其余季度公司未披露调整项", note)
        self.assertIn("Q1 2022（报表 US$0.49", note)

    def test_every_miss_is_explained_and_the_explanation_is_the_filings(self) -> None:
        """The three EPS misses and the one margin miss each carry a reason, and
        Q1 2022's is the Familia write-down the release names -- not "2022 年的成本
        冲击": the release's adjusted EPS cleared the top of the range."""
        dev = find(self.payload, "摊薄每股收益相对指引中值的偏离")
        self.assertIn("Q1'14 差 US$0.005（拆股调整后）", dev["note"])
        self.assertIn("Familia", dev["note"])
        self.assertNotIn("成本冲击", dev["note"])
        band = find(self.payload, "税前利润率：")
        rec = self.record
        below = [q for q, lo, a in zip(rec["quarters"], rec["guide_pretax_margin_lo_pct"],
                                       rec["actual_pretax_margin_pct"])
                 if lo is not None and a is not None and a < lo]
        self.assertIn("Q4 2022", below)
        if len(below) == 1:
            self.assertIn("<b>唯一一次跌破是 Q4'22 的 9.2% 对 9.5–9.8%</b>", band["note"])
        else:
            self.assertIn(f"<b>{cn(len(below))}次跌破：</b>", band["note"])
        self.assertIn("unplanned shrink charge", band["note"])

    def test_the_marmaxx_low_is_named_from_the_record(self) -> None:
        """「八季最低」on a 42-quarter chart was the window talking, not the record:
        the low is named by the last earlier quarter at or below this one, and only
        while this quarter is below each of the four before it."""
        mmx = self.source["comparable_sales_pct"]["marmaxx"]
        earlier = [(i, v) for i, v in enumerate(mmx[:-1]) if v is not None]
        chart = find(self.payload, "Marmaxx 同店销售")
        if all(v > mmx[-1] for _, v in earlier[-4:]):
            at_or_below = [i for i, v in earlier if v <= mmx[-1]]
            expected = f"{short(self.periods[at_or_below[-1]])} 以来最低" if at_or_below else "季最低"
            self.assertIn(expected, chart["title"])
        else:
            self.assertNotIn("以来最低", chart["title"])
        self.assertNotIn("八季", chart["title"])

    def test_the_comp_record_says_it_starts_where_it_was_read_not_where_the_disclosure_does(self) -> None:
        """Consolidated comp guidance is in the filed releases long before 2023 --
        as the comp growth each EPS outlook rested on (2020-02-26: 2% to 3%). The
        page used to say the guidance "从 Q1'23 才开始"."""
        band = find(self.payload, "合并同店销售：")
        self.assertNotIn("才开始", band["note"])
        self.assertIn("本页尚未接入", band["note"])
        self.assertIn("2020-02-26", band["note"])

    def test_the_half_and_half_arithmetic_behind_the_slope_chart(self) -> None:
        """Rest-of-year implied = full-year guided midpoint − year to date, both filed."""
        outlook = self.source.get("full_year_outlook")
        chart = find(self.payload, "全年指引拆成")
        if outlook is None or self.source["fiscal_labels"][-1].endswith("Q4"):
            self.assertIsNone(chart, "a fourth quarter has no rest of the year to split off")
            return
        prior, current = chart["groups"][0]["values"], chart["groups"][1]["values"]
        mid = sum(outlook["fy_guide_usd"]) / 2
        self.assertAlmostEqual(current[0], outlook["ytd_eps_usd"], places=6)
        self.assertAlmostEqual(current[1], mid - outlook["ytd_eps_usd"], places=6)
        self.assertAlmostEqual(prior[1], outlook["prior_fy_eps_usd"] - outlook["prior_ytd_eps_usd"], places=6)
        ytd_growth = (current[0] / prior[0] - 1) * 100
        rest_growth = (current[1] / prior[1] - 1) * 100
        self.assertIn(f"同比 {ytd_growth:+.1f}%", chart["title"])
        if rest_growth < ytd_growth:
            self.assertIn(f"隐含只有 {rest_growth:+.1f}%", chart["title"])
            self.assertIn(f"只隐含 {rest_growth:+.1f}%", self.payload["headline"])
        # the company prints the year-to-date growth rounded; the page's figure rounds to it
        printed = self.source["_checks"].get("ytd_adjusted_eps_growth_pct_printed")
        if printed is not None:
            self.assertEqual(round(ytd_growth), printed)

    def test_the_full_year_raise_equals_the_quarter_beat(self) -> None:
        """The page says the raise moved nothing into the rest of the year. Both
        midpoints minus their own year-to-date have to land on the same number."""
        outlook = self.source.get("full_year_outlook")
        chart = find(self.payload, "全年指引拆成")
        if chart is None:
            return
        record = self.record
        r = record["quarters"].index(self.periods[-1])
        guided_mid = (record["guide_eps_lo_usd"][r] + record["guide_eps_hi_usd"][r]) / 2
        actual = record["actual_eps_usd"][r]
        old_mid, new_mid = sum(outlook["prior_fy_guide_usd"]) / 2, sum(outlook["fy_guide_usd"]) / 2
        unmoved = abs((new_mid - outlook["ytd_eps_usd"])
                      - (old_mid - (outlook["ytd_eps_usd"] - actual + guided_mid))) < 5e-4
        same = abs((new_mid - old_mid) - (actual - guided_mid)) < 5e-4
        self.assertEqual("<b>一分没动</b>" in chart["note"], unmoved and new_mid > old_mid)
        self.assertEqual("恰好等于本季超出指引中值的幅度" in chart["note"], same and new_mid > old_mid)
        if self.payload["guidance"] and "{rest_now}" in self.source["guidance"]["note"]:
            self.assertIn(f"${new_mid - outlook['ytd_eps_usd']:.3f}", self.payload["guidance"]["note"])

    # ── thresholds ───────────────────────────────────────────────────────────
    def measured(self, measure: str) -> float:
        """What each threshold measure reads, computed here independently."""
        fin, comp = self.fin, self.source["comparable_sales_pct"]
        ips = self.source["operations"]["inventory_per_store_usd_k"]
        ytd = self.source["ytd_usd_m"]
        adj = self.source.get("adjusted_segment_margins_pct")
        return {
            "comp_consolidated": comp["consolidated"][-1],
            "comp_marmaxx": comp["marmaxx"][-1],
            "gross_margin_adjusted": fin["adjusted_gross_margin_pct"][-1] or fin["gross_margin_pct"][-1],
            "pretax_margin_adjusted": fin["adjusted_pretax_margin_pct"][-1] or fin["pretax_margin_pct"][-1],
            "homegoods_margin_adjusted": (adj["homegoods"]["adjusted"] if adj
                                          else self.source["segment_margins_pct"]["homegoods_margin_pct"][-1]),
            "inventory_per_store_yoy": (ips[-1] / ips[-5] - 1) * 100,
            "ytd_capex_intensity": ytd["capital_expenditures"][1] / sum(
                fin["net_sales_usd_m"][-int(self.source["fiscal_labels"][-1][-1]):]) * 100,
        }[measure]

    def test_threshold_current_values_come_from_the_series(self) -> None:
        for key, table in (("prior_kpi", "上季阈值核对（原始单位）"), ("next_kpi", "下季阈值（原始单位）")):
            block = self.source.get(key)
            titles = [t["title"] for t in self.payload["tables"]]
            if block is None:
                self.assertNotIn(table, titles)
                continue
            rows = next(t for t in self.payload["tables"] if t["title"] == table)["rows"]
            self.assertEqual(len(rows), len(block["quantified"]))
            for entry, row in zip(block["quantified"], rows):
                value = self.measured(entry["measure"])
                with self.subTest(block=key, metric=entry["metric"]):
                    self.assertNotIn("actual", entry)
                    self.assertNotIn("current", entry)
                    self.assertEqual(row[0], entry["metric"])
                    self.assertEqual(row[3], f"{value:.1f}%")
                    self.assertEqual(row[4], f"{headroom(entry['direction'], entry['threshold'], value):+.1f}%")

    def test_the_headroom_titles_count_what_the_bars_show(self) -> None:
        for key, prefix in (("prior_kpi", "上季设下的"), ("next_kpi", "下季")):
            block = self.source.get(key)
            if block is None:
                continue
            room = [headroom(e["direction"], e["threshold"], self.measured(e["measure"]))
                    for e in block["quantified"]]
            chart = next(ex for ex in self.exhibits if ex["kind"] == "diverging_bars"
                         and ex["title"].startswith(prefix))
            self.assertEqual(chart["values"], [round(v, 1) for v in room])
            breached = sum(1 for v in room if v < 0)
            with self.subTest(block=key):
                self.assertIn(f"{cn(len(room))}条阈值", chart["title"])
                self.assertIn(f"{cn(breached)}条", chart["title"])

    def test_every_threshold_entry_is_renderable(self) -> None:
        for key in ("prior_kpi", "next_kpi"):
            for item in self.source.get(key, {}).get("quantified", []):
                self.assertIn(item["direction"], ("up", "down"), item["metric"])
                self.assertNotEqual(item["threshold"], 0, item["metric"])
                self.assertIsInstance(self.measured(item["measure"]), (int, float))

    def test_the_peer_gap_is_counted_from_both_companies_numbers(self) -> None:
        """The threshold this page cannot plot is still settled on numbers: the
        peer's two printed comps less Marmaxx's, and "确实触发" only while both clear it."""
        entry = next((e for e in self.source.get("prior_kpi", {}).get("not_plotted", [])
                      if e["kind"] == "peer_gap"), None)
        if entry is None:
            self.assertNotIn("同业同期 comp 差距」需要另一家公司", text_of(self.payload))
            return
        own = self.source["comparable_sales_pct"]["marmaxx"][-len(entry["peer_comp_pct"]):]
        gaps = [p - o for p, o in zip(entry["peer_comp_pct"], own)]
        note = next(ex for ex in self.exhibits if ex["title"].startswith("上季设下的"))["note"]
        self.assertIn(f"差距 {gaps[-1]:.0f}pp", note)
        self.assertIn("确实触发" if min(gaps) >= entry["threshold_pp"] else "没有触发", note)

    # ── page wiring ──────────────────────────────────────────────────────────
    def test_exhibit_numbers_run_without_a_gap(self) -> None:
        numbers = [ex["n"] for ex in self.exhibits]
        self.assertEqual(numbers, list(range(1, len(numbers) + 1)))
        table_numbers = [table["n"] for table in self.payload["tables"]]
        self.assertEqual(table_numbers,
                         list(range(numbers[-1] + 1, numbers[-1] + 1 + len(table_numbers))))

    def test_no_exhibit_carries_an_unresolved_reference(self) -> None:
        for exhibit in self.exhibits:
            for field in ("title", "note", "src_extra", "annot"):
                text = exhibit.get(field)
                if isinstance(text, str):
                    self.assertNotIn("{EX_", text, f"exhibit {exhibit['n']} {field}")
                    self.assertIsNone(re.search(r"\{[a-z_]+\}", text), f"exhibit {exhibit['n']} {field}")

    def test_the_page_refuses_to_publish_the_de_tariffed_earnings(self) -> None:
        """The company says "mostly" and never a number, so neither does the

        page. This pins the refusal: turning "mostly" into a figure needs a
        self-chosen ratio, which is an assumption and not arithmetic.
        """
        notes = " ".join(self.payload["notes"])
        if self.source.get("quarter_story", {}).get("not_published_note"):
            self.assertIn("不发布", notes)
            self.assertIn("mostly", notes)
        blob = text_of(self.payload)
        # The local research note puts the de-tariffed figure at roughly
        # US$1.16-1.18 against a reported US$1.22. None of that may be
        # published -- but US$1.17 legitimately appears as the top of the
        # quarter's *guided* range, so the assertion has to name the estimate
        # rather than a bare number that also occurs for an honest reason.
        for invented in ("$1.16", "1.16–1.18", "1.16-1.18", "去关税"):
            self.assertNotIn(invented, blob,
                             "an estimated de-tariffed EPS reached the payload")
        r = self.record["quarters"].index(self.periods[-1])
        self.assertIn(f"${self.record['guide_eps_lo_usd'][r]:.2f}–{self.record['guide_eps_hi_usd'][r]:.2f}",
                      blob, "the guided range itself is publishable")

    def test_the_cross_page_capex_table_is_carried_and_explained(self) -> None:
        """TJX carries the shared AI-capex block like every other page, and says

        what it is. Carrying the table and being a *column* in it are separate
        things -- Cadence, Synopsys, TSMC and NVIDIA all publish it without
        appearing in `_CASH_CAPEX_SOURCES` either. It renders in the collapsed
        audit drawer rather than the chart flow, which is why it does not owe
        the page's "every chart must earn its place" justification. What it does
        owe the reader is one sentence saying it is a site-wide cross-reference
        and not a claim about an off-price retailer; the first pages outside the
        chain shipped it with no note at all, which is the gap this pins.
        """
        titles = [table["title"] for table in self.payload["tables"]]
        self.assertTrue(any("AI capex" in title for title in titles))
        explained = [note for note in self.payload["notes"] if "AI capex" in note]
        self.assertEqual(len(explained), 1)
        self.assertIn("跨页对照", explained[0])
        blob = text_of(self.payload)
        self.assertNotIn("TJX 不在这条链上的任何一环；每张图", blob)
        self.assertNotIn("本站最长", blob)

    def test_sources_are_direct_links_and_carry_this_quarters_release(self) -> None:
        links = self.source["sources"]
        for item in links:
            with self.subTest(label=item["label"]):
                self.assertTrue(item["url"].startswith("https://www.sec.gov/"))
                self.assertNotIn("-index.htm", item["url"], "link the document, not the filing index")
        fy, fq = self.source["fiscal_labels"][-1][2:6], self.source["fiscal_labels"][-1][-1]
        release = next(item for item in links
                       if f"FY{fy} Q{fq}" in item["label"] and self.source["release_dates"][-1] in item["label"])
        self.assertEqual(self.payload["source_url"], release["url"])
        self.assertIn(release["url"], self.payload["source"])

    def test_published_payload_matches_a_fresh_build(self) -> None:
        self.assertEqual(js_payload(ROOT / "data" / "tjx.js", "window.DASH"), self.payload)

    def test_roster_and_shell(self) -> None:
        roster = js_payload(ROOT / "data" / "roster.js", "window.ROSTER")
        self.assertEqual(roster, roster_payload(build_all()))
        entry = next(item for item in roster["items"] if item["slug"] == "tjx")
        self.assertEqual(entry["latest_label"], self.payload["latest"]["disclosed_period_label"])
        self.assertEqual(entry["release_date"], self.payload["latest"]["release_date"])
        shell = (ROOT / "tjx" / "index.html").read_text(encoding="utf-8")
        self.assertIn("../data/tjx.js", shell)
        self.assertNotIn("../data/tsm.js", shell)

    def test_the_home_page_counts_the_companies_it_renders(self) -> None:
        """The masthead number is hand-written and merges cleanly when two

        people both increment it. Counting is the only thing that survives.

        `test_v_dashboard` already checks the masthead against the rendered card
        count, which catches the two disagreeing. It cannot catch both being
        stale together -- add an ENTRIES row and forget `index.html` entirely and
        that assertion still passes. This one ties both to `len(ENTRIES)`.
        """
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertEqual(home.count('class="hcard"'), len(ENTRIES))
        self.assertIn(f'<span class="meta">{len(ENTRIES)} 家公司', home)
        self.assertIn('href="tjx/"', home)
        for group in GROUPS:
            self.assertIn(group["label"], home, group["key"])

    def test_compact_period(self) -> None:
        self.assertEqual(compact_period("Q2 2026"), "Q2'26")




class TjxChecksTest(unittest.TestCase):
    """The page's quarter against a record keyed separately from the filing.

    `_checks` in the series file is typed once per quarter from the earnings
    release itself, with the place in the document it was read from -- it is
    not copied out of the arrays, and the builder never reads it (asserted in
    `test_data_only_roll`). Every assertion here compares what the builder
    computed from the arrays with that separate reading, so a roll that
    misaligns a column, drops the new quarter or keeps last quarter's sentence
    fails here. Rolling a quarter re-keys `_checks`; this file does not change.
    Figures a quarter may not have (an adjusted EPS, a store target) are checked
    when `_checks` carries them.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.staging = load()
        cls.checks = cls.staging["_checks"]
        cls.fin = cls.staging["financials"]
        cls.payload = build_payload(cls.staging)

    def test_the_page_names_the_checked_quarter_both_ways(self) -> None:
        checks = self.checks
        self.assertIn(checks["period"], self.payload["title"])
        self.assertIn(f"本页 {checks['period']} 即公司所称 {checks['fiscal_label']}", self.payload["subtitle"])
        self.assertIn(f"{cn(checks['weeks'])}周截至 {checks['period_end']}", self.payload["subtitle"])
        self.assertIn(f"发布 {checks['release_date']}", self.payload["subtitle"])
        self.assertEqual(self.payload["latest"]["disclosed_period_label"], checks["period"])

    def test_the_series_ends_on_the_checked_figures(self) -> None:
        checks, fin, st = self.checks, self.fin, self.staging
        self.assertEqual(fin["net_sales_usd_m"][-1], checks["net_sales_usd_m"])
        self.assertEqual(fin["net_sales_usd_m"][-5], checks["prior_year_net_sales_usd_m"])
        for key, value in checks["comparable_sales_pct"].items():
            with self.subTest(comp=key):
                self.assertEqual(st["comparable_sales_pct"][key][-1], value)
                self.assertEqual(st["comparable_sales_pct"][key][-5],
                                 checks["prior_year_comparable_sales_pct"][key])
        # The release prints margins to one decimal; the series carries them
        # unrounded, so they must round to what was printed.
        self.assertEqual(round(fin["gross_margin_pct"][-1], 1), checks["gross_margin_pct"])
        self.assertEqual(round(fin["sga_pct_of_sales"][-1], 1), checks["sga_pct"])
        self.assertEqual(round(fin["pretax_margin_pct"][-1], 1), checks["pretax_margin_pct"])
        self.assertEqual(fin["diluted_eps_usd"][-1], checks["diluted_eps_usd"])
        for key in ("adjusted_gross_margin_pct", "adjusted_pretax_margin_pct", "adjusted_diluted_eps_usd"):
            with self.subTest(adjusted=key):
                self.assertEqual(fin[key][-1], checks.get(key))
        if checks.get("adjusted_diluted_eps_usd") is not None:
            self.assertEqual(round(fin["diluted_eps_usd"][-1] - fin["adjusted_diluted_eps_usd"][-1], 2),
                             checks["adjusting_item_net_eps_usd"])
        for key, value in checks["segment_sales_usd_m"].items():
            self.assertEqual(st["segments_usd_m"][f"{key}_sales"][-1], value)
        self.assertEqual(st["segments_usd_m"]["general_corporate_expense"][-1],
                         checks["general_corporate_expense_usd_m"])
        self.assertEqual(st["segments_usd_m"]["general_corporate_expense_prior_year"][-1],
                         checks["prior_year_general_corporate_expense_usd_m"])
        self.assertEqual(st["operations"]["merchandise_inventories_usd_m"][-1],
                         checks["merchandise_inventories_usd_m"])
        self.assertEqual(st["operations"]["store_count"][-1], checks["store_count"])
        ytd = st["ytd_usd_m"]
        self.assertEqual(ytd["operating_cash_flow"][1], checks["ytd_operating_cash_flow_usd_m"])
        self.assertEqual(ytd["capital_expenditures"][1], checks["ytd_property_additions_usd_m"])
        fq = int(st["fiscal_labels"][-1][-1])
        self.assertEqual(sum(fin["net_sales_usd_m"][-fq:]), checks["ytd_net_sales_usd_m"])
        outlook = st.get("full_year_outlook")
        if "ytd_adjusted_eps_usd" in checks:
            self.assertEqual(outlook["ytd_eps_usd"], checks["ytd_adjusted_eps_usd"])
            self.assertEqual(outlook["prior_ytd_eps_usd"], checks["prior_ytd_adjusted_eps_usd"])
        if "full_year_adjusted_eps_outlook_usd" in checks:
            self.assertEqual(outlook["fy_guide_usd"], checks["full_year_adjusted_eps_outlook_usd"])
        if "long_term_store_target" in checks:
            self.assertEqual(st["store_plan"]["target"], checks["long_term_store_target"])
        rec = st["quarterly_guidance_history"]
        guided = checks["next_quarter_outlook"]
        self.assertEqual([rec["guide_comp_lo_pct"][-1], rec["guide_comp_hi_pct"][-1]], guided["comp_pct"])
        self.assertEqual([rec["guide_pretax_margin_lo_pct"][-1], rec["guide_pretax_margin_hi_pct"][-1]],
                         guided["pretax_margin_pct"])
        self.assertEqual([rec["guide_eps_lo_usd"][-1], rec["guide_eps_hi_usd"][-1]], guided["diluted_eps_usd"])
        self.assertEqual(rec["guidance_published"][-1], checks["release_date"])

    def test_the_rounding_the_page_uses_is_the_companys(self) -> None:
        """Where the release prints a rate the page prints more finely, the page's
        figure has to round to the company's."""
        fin = self.fin
        self.assertEqual(round(fin["net_sales_yoy_pct"][-1]), self.checks["net_sales_growth_pct_printed"])
        self.assertIn(f"同比 {fin['net_sales_yoy_pct'][-1]:+.1f}%", self.payload["headline"])

    def test_the_headline_prints_the_checked_figures(self) -> None:
        headline = self.payload["headline"]
        checks = self.checks
        comps = checks["comparable_sales_pct"]
        self.assertIn(f"US${checks['net_sales_usd_m']:,}", headline)
        self.assertIn(f"合并 comp {comps['consolidated']:+d}%", headline)
        self.assertIn(f"税前利润率 {checks['pretax_margin_pct']:.1f}%", headline)
        self.assertEqual(f"Marmaxx 只有 {comps['marmaxx']:+d}%" in headline,
                         comps["marmaxx"] < comps["consolidated"])

    def test_the_capital_intensity_chart_prints_the_checked_year_to_date(self) -> None:
        checks = self.checks
        chart = find(self.payload, "资本强度：")
        now = checks["ytd_property_additions_usd_m"] / checks["ytd_net_sales_usd_m"] * 100
        self.assertIn(f"资本开支占销售额 {now:.2f}%", chart["title"])
        self.assertIn(f"经营现金流 ${checks['ytd_operating_cash_flow_usd_m']:,}M", chart["note"])

    def test_the_eps_chart_and_the_outlook_table_print_the_checked_figures(self) -> None:
        checks = self.checks
        layers = find(self.payload, "本季每股收益")
        if checks.get("adjusted_diluted_eps_usd") is not None and "one_off_usd_m" in self.staging:
            self.assertIn(f"报表 ${checks['diluted_eps_usd']:.2f} → 公司调整后 "
                          f"${checks['adjusted_diluted_eps_usd']:.2f}", layers["title"])
        else:
            self.assertIsNone(layers)
        guidance = self.payload["guidance"]
        cells = [cell for row in (guidance or {}).get("rows", []) for cell in row]
        if "full_year_adjusted_eps_outlook_usd" in checks and guidance:
            lo, hi = checks["full_year_adjusted_eps_outlook_usd"]
            self.assertIn(f"${lo:.2f} ~ ${hi:.2f}", cells)
        if guidance:
            eps_lo, eps_hi = checks["next_quarter_outlook"]["diluted_eps_usd"]
            self.assertIn(f"${eps_lo:.2f} ~ ${eps_hi:.2f}", cells)
        if "long_term_store_target" in checks:
            stores = next(ex for ex in exhibits_of(self.payload) if "门店数与总面积" in ex["title"])
            self.assertIn(f"{checks['long_term_store_target']:,}", stores["title"])


class TjxRollTest(unittest.TestCase):
    """What a roll has to change in `series/tjx.json`, and what the page does when it does not.

    Blocks that describe one release carry its quarter (`STAMPED`). A stale one
    stops the build; an absent story takes its sentences with it; every claim
    about a whole record is made true in the data here and then broken, and the
    sentence has to follow; and the next, fourth and first quarters build from
    data alone. Nothing below depends on which quarter the series ends at.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = load()
        cls.payload = build_payload(cls.source)
        cls.blob = text_of(cls.payload)

    def test_a_block_stamped_with_another_quarter_stops_the_build(self) -> None:
        full = with_thresholds(self.source)
        self.assertIn("ytd_usd_m", full)
        for key in STAMPED:
            if key not in full:
                continue
            stale = copy.deepcopy(full)
            stale[key]["period"] = "Q1 1999"
            with self.subTest(block=key):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    build_payload(stale)

    def test_what_a_roll_forgets_stops_the_build(self) -> None:
        full = with_thresholds(self.source)
        cases = {}
        bare = copy.deepcopy(full)
        del bare["ytd_usd_m"]
        cases["`ytd_usd_m` is missing"] = bare
        unknown = copy.deepcopy(full)
        unknown["next_kpi"]["quantified"][0]["measure"] = "not_a_measure"
        cases["does not know how to measure"] = unknown
        orphan = copy.deepcopy(full)
        url = self.payload["source_url"]
        orphan["sources"] = [s for s in orphan["sources"] if s["url"] != url]
        cases["`sources` has no entry"] = orphan
        audited = copy.deepcopy(full)
        audited["latest"]["audit_status"] = "reviewed"
        cases["audit_status"] = audited
        undated = copy.deepcopy(full)
        del undated["quarterly_guidance_history"]["early_quarter_ends"]["Q2 2013"]
        cases["early_quarter_ends has no end for 'Q2 2013'"] = undated
        unexplained = copy.deepcopy(full)
        rec = unexplained["quarterly_guidance_history"]
        r = rec["quarters"].index(unexplained["periods"][-1])
        rec["actual_eps_usd"][r] = rec["guide_eps_lo_usd"][r] - 0.05
        cases["miss_notes.eps says nothing about"] = unexplained
        misdated = copy.deepcopy(full)
        misdated["period_ends"][-1] = (day(misdated["period_ends"][-1]) + datetime.timedelta(days=2)).isoformat()
        cases["not a whole number of weeks"] = misdated
        for message, staging in cases.items():
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, re.escape(message)):
                    build_payload(staging)

    def test_a_quarter_without_a_story_leaves_it_out(self) -> None:
        """Every block that describes one release can be absent; its sentences go with it."""
        full = with_thresholds(self.source)
        blob = text_of(build_payload(full))
        probes = {
            "prior_kpi": ["上季阈值核对（原始单位）", "上季设下的"],
            "next_kpi": ["下季阈值（原始单位）"],
            "followup_closure": ["待验证问题的结清情况"],
            "one_off_usd_m": ["本季每股收益"],
            "full_year_outlook": ["全年指引拆成"],
            "store_plan": ["长期目标刚从"],
            "adjusted_segment_margins_pct": ["对每个分部利润率的影响"],
            "guidance": [(full.get("guidance") or {}).get("title") or "公司指引（"],
            "quarter_story": [text for text in story_texts(full.get("quarter_story", {}))
                              if text in blob],
        }
        for key, texts in probes.items():
            if key not in full:
                continue
            bare = copy.deepcopy(full)
            del bare[key]
            if key == "full_year_outlook":
                # what names a number read from the outlook goes with the outlook
                bare.get("next_kpi", {})["not_plotted"] = [
                    item for item in bare.get("next_kpi", {}).get("not_plotted", [])
                    if "{raise}" not in item["why"]]
                bare.pop("guidance", None)
            if key == "one_off_usd_m":
                bare.pop("store_plan", None)
            after = text_of(build_payload(bare))
            for text in texts:
                if key == "store_plan" and full["store_plan"]["announced"] != full["release_dates"][-1]:
                    continue
                with self.subTest(block=key, text=text[:30]):
                    self.assertIn(text, blob)
                    self.assertNotIn(text, after)

    def test_the_record_sentences_are_computed_not_remembered(self) -> None:
        """Make each "never / only / every / first / lowest since / all" claim true in
        the data, check the page says it, then break it once: the sentence has to go."""
        base = with_thresholds(self.source)
        labels = [short(p) for p in base["periods"]]

        def page(mutate) -> str:
            st = copy.deepcopy(base)
            mutate(st)
            return text_of(build_payload(st))

        def rec(st):
            return st["quarterly_guidance_history"]

        def comp_clean(st):
            r = rec(st)
            for i, a in enumerate(r["actual_comp_pct"]):
                if a is not None and r["guide_comp_lo_pct"][i] is not None:
                    r["actual_comp_pct"][i] = max(a, r["guide_comp_lo_pct"][i])
            for i, a in enumerate(r["actual_pretax_margin_pct"]):
                if a is not None and r["guide_pretax_margin_lo_pct"][i] is not None \
                        and r["quarters"][i] != "Q4 2022":
                    r["actual_pretax_margin_pct"][i] = max(a, r["guide_pretax_margin_hi_pct"][i] + 0.1)

        def comp_miss(st):
            comp_clean(st)
            r = rec(st)
            i = r["quarters"].index("Q1 2024")
            r["actual_comp_pct"][i] = r["guide_comp_lo_pct"][i] - 1

        def margin_second_miss(st):
            comp_clean(st)
            r = rec(st)
            i = r["quarters"].index("Q1 2024")
            r["actual_pretax_margin_pct"][i] = r["guide_pretax_margin_lo_pct"][i] - 0.2
            r["miss_notes"]["pretax_margin"]["Q1 2024"] = "（测试用的原因）"

        def lags_clean(st):
            r = rec(st)
            for i, (label, first) in enumerate(zip(r["fiscal_labels"], starts(st))):
                offset = 24 if label.endswith("Q1") else 16
                r["guidance_published"][i] = (first + datetime.timedelta(days=offset)).isoformat()

        def lags_broken(st):
            lags_clean(st)
            r = rec(st)
            i = next(i for i, label in enumerate(r["fiscal_labels"]) if label.endswith("Q2"))
            r["guidance_published"][i] = (starts(st)[i] + datetime.timedelta(days=30)).isoformat()

        k = len(base["periods"]) - 12

        def homegoods_first(st):
            segm = st["segment_margins_pct"]
            for i in range(len(base["periods"])):
                segm["homegoods_margin_pct"][i] = segm["marmaxx_margin_pct"][i] - 1.0
            segm["homegoods_margin_pct"][k] = segm["marmaxx_margin_pct"][k] + 1.0
            segm["homegoods_margin_pct"][-1] = segm["marmaxx_margin_pct"][-1] + 1.0

        def homegoods_again(st):
            homegoods_first(st)
            segm = st["segment_margins_pct"]
            segm["homegoods_margin_pct"][-2] = segm["marmaxx_margin_pct"][-2] + 1.0

        def marmaxx_low(st):
            mmx = st["comparable_sales_pct"]["marmaxx"]
            for i, v in enumerate(mmx):
                if v is not None:
                    mmx[i] = 5.0
            mmx[k] = -9.0
            mmx[-1] = -8.0

        def marmaxx_not_low(st):
            marmaxx_low(st)
            st["comparable_sales_pct"]["marmaxx"][-3] = -8.5

        def gce_low(st):
            gce = st["segments_usd_m"]["general_corporate_expense"]
            for i in range(len(gce)):
                gce[i] = 200.0
            gce[k] = 90.0
            gce[-2] = 100.0

        def gce_not_low(st):
            gce_low(st)
            st["segments_usd_m"]["general_corporate_expense"][-4] = 95.0

        n_years = len(base["long_history"]["fiscal_years"])
        years = "十年" if n_years == 10 else f"{cn(n_years)}年"

        def both_top(st):
            long = st["long_history"]
            long["capex_intensity_pct"][-1] = max(long["capex_intensity_pct"]) + 0.5
            long["pretax_margin_pct"][-1] = max(long["pretax_margin_pct"]) + 0.5

        def capex_not_top(st):
            both_top(st)
            long = st["long_history"]
            long["capex_intensity_pct"][-2] = long["capex_intensity_pct"][-1] + 0.1

        def rising(st):
            long = st["long_history"]
            start = long["fiscal_years"].index("FY2021")
            for i in range(start + 1, n_years):
                long["pretax_margin_pct"][i] = 8.0 + i

        def dipping(st):
            rising(st)
            st["long_history"]["pretax_margin_pct"][-2] = 50.0

        def one_gap(st):
            long = st["long_history"]
            for i, fy in enumerate(long["fiscal_years"]):
                if fy != "FY2021":
                    fcf = long["operating_cash_flow_usd_m"][i] - long["capital_expenditures_usd_m"][i]
                    long["share_repurchases_usd_m"][i] = fcf
                    long["dividends_paid_usd_m"][i] = 0.0

        def two_gaps(st):
            one_gap(st)
            long = st["long_history"]
            long["share_repurchases_usd_m"][0] = long["dividends_paid_usd_m"][0] = 1.0

        def one_mid(st):
            r = rec(st)
            for i, lo in enumerate(r["guide_comp_lo_pct"]):
                if lo is not None:
                    r["guide_comp_lo_pct"][i], r["guide_comp_hi_pct"][i] = 2.0, 3.0

        def mixed_mids(st):
            r = rec(st)
            for n, i in enumerate(i for i, lo in enumerate(r["guide_comp_lo_pct"]) if lo is not None):
                r["guide_comp_lo_pct"][i], r["guide_comp_hi_pct"][i] = 1.0 + n, 2.0 + n

        def upward(st):
            r = rec(st)
            for i, a in enumerate(r["actual_eps_usd"]):
                if a is not None:
                    r["actual_eps_usd"][i] = round((r["guide_eps_lo_usd"][i] + r["guide_eps_hi_usd"][i]) / 2 * 1.06, 4)

        def not_upward(st):
            upward(st)
            r = rec(st)
            done = [i for i, a in enumerate(r["actual_eps_usd"]) if a is not None]
            for i in done[: len(done) // 5]:
                r["actual_eps_usd"][i] = r["guide_eps_lo_usd"][i]

        def one_rising(st):
            comp = st["comparable_sales_pct"]
            comp["consolidated"][-1] = 4.0
            for key, (before, now) in {"marmaxx": (6.0, 1.0), "homegoods": (8.0, 7.0),
                                       "canada": (7.0, 6.0), "international": (4.0, 7.0)}.items():
                comp[key][-2], comp[key][-1] = before, now

        def two_rising(st):
            one_rising(st)
            st["comparable_sales_pct"]["homegoods"][-1] = 9.0

        def both_beat(st):
            r = rec(st)
            i = r["quarters"].index(st["periods"][-1])
            r["actual_comp_pct"][i] = r["guide_comp_hi_pct"][i] + 1
            r["actual_pretax_margin_pct"][i] = r["guide_pretax_margin_hi_pct"][i] + 0.5

        def comp_inside(st):
            both_beat(st)
            r = rec(st)
            i = r["quarters"].index(st["periods"][-1])
            r["actual_comp_pct"][i] = r["guide_comp_lo_pct"][i]

        def carried(st):
            one_rising(st)
            entry = next(e for e in st["prior_kpi"]["quantified"] if e["measure"] == "comp_consolidated")
            entry["threshold"] = 4.0

        def not_carried(st):
            carried(st)
            st["comparable_sales_pct"]["canada"][-1] = 3.0

        def q3_peaks(st):
            ips = st["operations"]["inventory_per_store_usd_k"]
            for i in range(len(ips) - 9, len(ips)):
                ips[i] = 2000.0 + i if base["periods"][i].startswith("Q3") else 1400.0 + i

        def q1_peak(st):
            q3_peaks(st)
            ips = st["operations"]["inventory_per_store_usd_k"]
            first_q1 = next(i for i, label in enumerate(base["periods"])
                            if ips[i] is not None and label.startswith("Q1"))
            ips[first_q1] = 3000.0

        cases = [
            (comp_clean, comp_miss, ["<b>一次都没有跌破过下限</b>", "一次没跌破过。"]),
            (comp_clean, margin_second_miss, ["唯一一次跌破是 Q4'22"]),
            (lags_clean, lags_broken, ["会计季 Q1 最迟"]),
            (homegoods_first, homegoods_again, [f"{labels[k]} 以来第一次高过 Marmaxx"]),
            (marmaxx_low, marmaxx_not_low, [f"{labels[k]} 以来最低", f"是 {labels[k]} 以来的最低点"]),
            (gce_low, gce_not_low, [f"{labels[k]} 以来的低点"]),
            (both_top, capex_not_top, [f"利润率与资本强度同时创{years}高"]),
            (rising, dipping, ["此后利润率连年抬升"]),
            (one_gap, two_gaps, ["是唯一一年三者脱节"]),
            (one_mid, mixed_mids, ["季是同一个数"]),
            (upward, not_upward, ["柱子几乎清一色朝上"]),
            (one_rising, two_rising, ["是唯一环比加速的分部", "（唯一加速的）"]),
            (both_beat, comp_inside, ["双双高于自身指引"]),
            (carried, not_carried, ["过线全靠 Marmaxx 以外的三个分部", "三强一弱"]),
            (q3_peaks, q1_peak, ["两格的高点是进入假日季前的季节性备货"]),
        ]
        for make_true, break_it, claims in cases:
            true, broken = page(make_true), page(break_it)
            for claim in claims:
                with self.subTest(claim=claim):
                    self.assertIn(claim, true, f"{make_true.__name__} does not make it true")
                    self.assertNotIn(claim, broken, f"{break_it.__name__} leaves it standing")
        # the floor under the buybacks is read off the data, whatever it is
        long = base["long_history"]
        after = long["share_repurchases_usd_m"][long["fiscal_years"].index("FY2021") + 1:]
        self.assertIn(f"此后每年都在 US${int(min(after) / 100) / 10:.1f}B 以上", self.blob)

    def test_the_next_quarter_rolls_without_touching_the_code(self) -> None:
        rolled = roll_forward(self.source)
        payload = build_payload(rolled)
        period = rolled["periods"][-1]
        self.assertEqual(payload["title"], f"The TJX Companies (TJX)：{period} 季报仪表盘")
        self.assertIn(f"截至 {rolled['period_ends'][-1]} · 发布 {rolled['release_dates'][-1]}",
                      payload["subtitle"])
        self.assertEqual(payload["source_url"], rolled["sources"][0]["url"])
        blob = text_of(payload)
        for text in story_texts(self.source.get("quarter_story", {})):
            with self.subTest(story=text[:30]):
                self.assertNotIn(text, blob)
        band = find(payload, "摊薄每股收益（近 16 季）")
        self.assertEqual(band["xlabels"][-1], short(rolled["quarterly_guidance_history"]["quarters"][-1]))
        self.assertEqual(len(find(payload, "一般公司费用")["xlabels"]), len(rolled["periods"]))
        fq = int(rolled["fiscal_labels"][-1][-1])
        self.assertIn(f"资本强度：{ {1: '一季度', 2: '上半年', 3: '前三季', 4: '全年'}[fq] }资本开支占销售额",
                      blob.replace("{", "").replace("}", ""))

    def test_restamped_thresholds_measure_the_new_quarter(self) -> None:
        rolled = with_thresholds(roll_forward(self.source))
        rolled["next_kpi"]["not_plotted"] = []
        payload = build_payload(rolled)
        table = next(t for t in payload["tables"] if t["title"] == "上季阈值核对（原始单位）")
        comp = rolled["comparable_sales_pct"]
        ips = rolled["operations"]["inventory_per_store_usd_k"]
        ytd = rolled["ytd_usd_m"]
        fq = int(rolled["fiscal_labels"][-1][-1])
        sales = sum(rolled["financials"]["net_sales_usd_m"][-fq:])
        expected = {"comp_consolidated": comp["consolidated"][-1], "comp_marmaxx": comp["marmaxx"][-1],
                    "gross_margin_adjusted": rolled["financials"]["gross_margin_pct"][-1],
                    "pretax_margin_adjusted": rolled["financials"]["pretax_margin_pct"][-1],
                    "homegoods_margin_adjusted": rolled["segment_margins_pct"]["homegoods_margin_pct"][-1],
                    "inventory_per_store_yoy": (ips[-1] / ips[-5] - 1) * 100,
                    "ytd_capex_intensity": ytd["capital_expenditures"][1] / sales * 100}
        for entry, row in zip(rolled["prior_kpi"]["quantified"], table["rows"]):
            with self.subTest(metric=entry["metric"]):
                self.assertEqual(row[3], f"{expected[entry['measure']]:.1f}%")

    def test_a_fiscal_fourth_quarter_rolls_and_reads_as_a_year(self) -> None:
        st = self.source
        while not st["fiscal_labels"][-1].endswith("Q4"):
            st = roll_forward(st)
        payload = build_payload(st)
        blob = text_of(payload)
        self.assertIn(f"与截至 {st['period_ends'][-1]} 的 10-K。", payload["source"])
        self.assertIn("资本强度：全年资本开支占销售额", blob)
        self.assertNotIn("全年指引拆成", blob)
        self.assertIn(f"本页 {st['periods'][-1]} 即公司所称 FY{st['fiscal_labels'][-1][2:6]} Q4",
                      payload["subtitle"])
        gce = find(payload, "一般公司费用")
        self.assertIn("全年累计", gce["note"])
        self.assertIn("跨季只能用全年口径", gce["note"])

    def test_a_first_quarter_rolls_without_a_year_to_date_comparison(self) -> None:
        st = self.source
        while not st["fiscal_labels"][-1].endswith("Q1"):
            st = roll_forward(st)
        payload = build_payload(st)
        blob = text_of(payload)
        self.assertIn("资本强度：一季度资本开支占销售额", blob)
        gce = find(payload, "一般公司费用")
        self.assertNotIn("累计 $", gce["note"])
        self.assertIn("跨季只能用累计口径", gce["note"])
        self.assertEqual(payload["title"], f"The TJX Companies (TJX)：{st['periods'][-1]} 季报仪表盘")


if __name__ == "__main__":
    unittest.main()
