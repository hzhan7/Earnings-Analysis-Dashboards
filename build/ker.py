#!/usr/bin/env python3
"""Kering quarterly dashboard.

Kering publishes revenue four times a year and profit twice. The first and third
quarter releases are revenue announcements; the income statement, the Houses'
recurring operating income, the cash flow and the balance sheet exist only at the
half-year and the full year. So this page runs two independent x axes -- revenue by
quarter, profit by half -- and never puts a profit figure on a quarterly axis.

Kering is not an SEC filer: EDGAR holds only ADR depositary paperwork (F-6EF,
F-6 POS, 424B3) under CIK 1445465. Every number comes from kering.com downloads, read
twice by transcribers blind to each other, every disagreement
settled against the page. `series/ker.json` is built from those ledgers and records
the document behind every cell.

**The disclosure changed shape four times in the window, and each change is a
place where a long line can lie without any sum failing:**

- Q1 2018: PUMA, Volcom, Stella McCartney (and later Christopher Kane) moved to
  discontinued operations. Group revenue and "Other Houses" before 2018 exist on
  two perimeters; this page uses the one the FY2018 release uses, which the June
  2018 "KPIs restated IFRS 5" file prints back to 2016Q1.
- 2019: IFRS 16. Kering printed 2018 on both bases; the half-year profit lines
  switch basis at 2018 and say so on the axis.
- Q1 2022: "Corporate and other" became "Kering Eyewear and Corporate" plus an
  eliminations line, and 2021 Other Houses was re-presented about €4-6M higher per
  quarter with no stated reason. The page keeps each quarter's first publication.
- FY2025 / Q1 2026: Kering Beauté to IFRS 5, then a new segment grid (Fashion &
  Leather Goods, Jewelry, Eyewear, Corporate & Other). Saint Laurent, Bottega
  Veneta and Other Houses stop being disclosed after 2025Q4.

A reprint of a brand quarter that differs from its first publication is listed in
the series (`reprint_exceptions`, one so far: Saint Laurent 2021Q3). The census claim
that there is no other -- and the claim that every document was read twice -- are
statements about the documents read up to the page's quarter, so they are printed
only while `corpus_audit` is stamped for that quarter.

Published numbers are company-reported or transparent arithmetic (marked D).
The page runs in TSM's four sections: what last quarter set and this quarter
settles, this quarter's findings, what the next quarter is tracked against, and
the long record. Thresholds in the third section are local research settings, not
company guidance.

Rolling the page is a data edit (CLAUDE.md §9). A first- or third-quarter roll
appends a quarter and leaves the half-year arrays alone; a second- or fourth-quarter
roll appends a half as well. Every period label, count and figure in the prose is
computed from the series. What belongs to one release -- the outlook paragraph and
the thresholds (stamped with the quarter), the half-year margin bridge and the
net-debt story (stamped with the half) -- sits in blocks read through
`board.stamped_block`: a block stamped for another period stops the build, an absent
one takes its chart or sentence with it. Every "first / all / only / lowest"
sentence is printed only while the data still says so. What stays in this file is
fixed history that no roll moves: the 2024 profit guides and their verdicts, the
2019 and 2022 medium-term targets, the three basis switches on the half-year axis,
the net-debt climb from 2021 to 2024 and the Capital Markets Day of 2026-04-16.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import (  # noqa: E402
    ai_capex_cycle_table,
    cn_count,
    cn_ordinal,
    display_period,
    headroom,
    headroom_exhibit,
    latest_block,
    minus_sign,
    number_exhibits,
    round_half_up,
    stamped_block,
    threshold_exhibit,
    threshold_table,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "ker.json"
DATA_DIR = ROOT / "data"

HOUSE_ZH = {"gucci": "Gucci", "saint_laurent": "Saint Laurent", "bottega_veneta": "Bottega Veneta",
            "other_houses": "其他品牌"}
LONG_STEP = 4

SOURCE_Q = ("季度收入与可比增速逐季取自当季首次公布它的那份公告：第一、三季度取季度收入公告，"
            "第二季度取半年度业绩新闻稿附表，第四季度取全年业绩新闻稿附表。")
SOURCE_H = ("半年数取自半年度业绩新闻稿与半年度财务报告；H2 各行为「全年减上半年」并标 D。"
            "公司不按季披露任何利润行。")
SOURCE_G = "指引原话逐字取自当期公告与演示材料；结算值取自其后的半年度与全年业绩新闻稿。"

# ── fixed history: none of this moves with a roll ────────────────────────────
# What changes the half-year numbers, as opposed to a label rename. The page draws
# a break wherever the family changes; a family change this table does not know
# stops the build, because the note that explains the breaks would not cover it.
BASIS_FAMILY = {
    "published_incl_sport_lifestyle": "incl_sport_lifestyle",
    "continuing_restated_ifrs5": "continuing_ias17",
    "ifrs16_restated": "continuing_ifrs16", "published": "continuing_ifrs16",
    "published_incl_beaute": "continuing_ifrs16",
    "restated_ex_beaute": "ex_beaute", "published_new_grid": "ex_beaute",
}
SWITCH_LABEL = {
    ("incl_sport_lifestyle", "continuing_ias17"): "剔除 Puma",
    ("continuing_ias17", "continuing_ifrs16"): "IFRS 16",
    ("continuing_ifrs16", "ex_beaute"): "剔除 Kering Beauté",
}
# The one net-debt climb the page explains, and what drove it. Printed only while
# the series' own low and high are still these two year-ends.
NET_DEBT_CLIMB = ("2021-12-31", "2024-12-31",
                  "期间有 2023 年 Creed 收购与 Valentino 30% 股权、2024 年的房地产购置。")
# The FY2022 Universal Registration Document's medium-term targets (pages 47, 49, 59).
TARGETS_2022 = {"gucci_revenue": 15000, "sl_revenue": 5000, "sl_margin": 33,
                "eyewear_revenue": 2000, "eyewear_margin": 15}
# The verdicts on the two "approximately" guides of 2024 are the page's reading of
# fixed history: −51.6% against "approximately 30%" is a miss, €2,554M against
# "approximately €2.5 billion" is not. The first-half range is settled by arithmetic.
APPROX_VERDICT = {"h2_2024": "未兑现", "fy_2024": "兑现"}


# ── helpers ──────────────────────────────────────────────────────────────────
def compact_quarter(period: str) -> str:
    """`2026Q2` -> `Q2'26`."""
    return f"{period[4:]}'{period[2:4]}"


def quarter_parts(period: str) -> tuple[int, int]:
    """`2026Q2` -> `(2026, 2)`."""
    return int(period[:4]), int(period[-1])


def quarter_cn(period: str) -> str:
    """`2016Q1` -> `2016 年一季度`."""
    year, number = quarter_parts(period)
    return f"{year} 年{cn_ordinal(number)}季度"


def year_ago_index(quarters: list[str], i: int) -> int | None:
    year, number = quarter_parts(quarters[i])
    label = f"{year - 1}Q{number}"
    return quarters.index(label) if label in quarters else None


def half_word(half: str) -> str:
    return "上半年" if half.startswith("H1") else "下半年"


def release_doc(period: str) -> str:
    """The document that first publishes a quarter's revenue."""
    year, number = quarter_parts(period)
    return {1: f"KER_{year}Q1_revenue_release", 2: f"KER_H1_{year}_results_release",
            3: f"KER_{year}Q3_revenue_release", 4: f"KER_FY_{year}_results_release"}[number]


def release_cn(doc: str, formal: bool = False) -> str:
    """`KER_H1_2026_results_release` -> `2026 上半年新闻稿` (`formal`: `…业绩新闻稿`)."""
    word = "业绩新闻稿" if formal else "新闻稿"
    match = re.fullmatch(r"KER_H1_(\d{4})_results_release", doc)
    if match:
        return f"{match.group(1)} 上半年{word}"
    match = re.fullmatch(r"KER_FY_(\d{4})_results_release", doc)
    if match:
        return f"{match.group(1)} 全年{word}"
    match = re.fullmatch(r"KER_(\d{4})Q([13])_revenue_release", doc)
    if match:
        return f"{match.group(1)} {cn_ordinal(int(match.group(2)))}季度收入公告"
    raise ValueError(f"no reader-facing name for release {doc!r}")


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def flat_signed(value: float) -> str:
    """Like ``signed(value, 0)`` but a flat quarter reads 「0%」, not 「+0%」."""
    text = signed(value, 0)
    return "0%" if text in ("+0%", "-0%") else text


def euro_m(value: float) -> str:
    """`€3,324M`; a negative amount (net cash, on a net-debt line) keeps its sign outside: `−€500M`."""
    return f"{'−' if value < 0 else ''}€{abs(value):,.0f}M"


def euro_delta(value: float) -> str:
    """`+€64M` / `−€38M`: the sign outside the currency symbol."""
    return f"{'−' if value < 0 else '+'}€{abs(value):,.0f}M"


def rounded(values, digits: int = 6):
    return [None if v is None else round(v, digits) for v in values]


def ratio(num, den):
    return None if num is None or not den else num / den * 100.0


def resolve_exhibit_refs(exhibits: list[dict]) -> list[dict]:
    numbers = {ex["ref"]: ex["n"] for ex in exhibits if "ref" in ex}
    for exhibit in exhibits:
        for key in ("note", "src_extra", "title"):
            text = exhibit.get(key)
            if not text:
                continue
            for ref, number in numbers.items():
                text = text.replace("{" + ref + "}", str(number))
            exhibit[key] = text
    return exhibits


def trailing_streak(values: list, predicate) -> int:
    n = 0
    for v in reversed(values):
        if v is None or not predicate(v):
            break
        n += 1
    return n


def trailing_run_start(values: list, predicate) -> int | None:
    """Index where the unbroken run satisfying `predicate` up to the last value begins."""
    n = trailing_streak(values, predicate)
    return len(values) - n if n else None


def doc_label(doc: str) -> str:
    """A reader-facing name for a normalised corpus file name."""
    d = doc.replace("KER_", "")
    kinds = {
        "revenue_release": "收入公告", "revenue_presentation": "收入演示材料",
        "results_release": "业绩新闻稿", "presentation": "业绩演示材料",
        "financial_report": "半年度财务报告", "financial_document": "年度 Financial Document",
        "universal_registration_document": "Universal Registration Document",
        "reference_document": "Document de référence",
        "ifrs5_restated_kpis": "按 IFRS 5 重述的关键指标（2018-06）",
        "proforma_quarterly_sales": "2017 年备考季度收入（2018-04）",
        "proforma_revenue_release": "2017 年备考收入公告（2018-04）",
        "ifrs16_restated": "按 IFRS 16 重述的 2018 年数据",
        "dos_count_quarterly_restatement": "新门店计数口径下的 2018 年季度重述",
        "ifrs5_beaute_restatement_release": "剔除 Kering Beauté 的 IFRS 5 重述公告（2025-12-11）",
        "segment_reporting_restatement_release": "新分部口径重述公告（2026-03-16）",
        "covid_initial_estimate_release": "新冠影响初步估计公告（2020-03-20）",
        "preliminary_information_release": "一季度初步信息公告（2024-03-19）",
        "Capital_Markets_Day": "资本市场日演示材料（2026-04-16）",
    }
    for key, zh in kinds.items():
        if d.endswith(key):
            period = d[: -len(key)].strip("_").replace("_", " ")
            return f"Kering {period} {zh}".replace("  ", " ")
    return f"Kering {d}"


def year_end_label(date: str) -> str:
    """`2025-12-31` -> `2025 年末`; `2025-06-30` -> `2025 年 6 月末`."""
    year, month = date[:4], int(date[5:7])
    return f"{year} 年末" if month == 12 else f"{year} 年 {month} 月末"


def basis_switches(basis: list[str]) -> list[tuple[int, str]]:
    """Where the half-year basis family changes, with the label the page draws."""
    families = []
    for label in basis:
        if label not in BASIS_FAMILY:
            raise ValueError(f"half-year basis {label!r} is not one this page knows how to mark")
        families.append(BASIS_FAMILY[label])
    switches = []
    for i in range(1, len(families)):
        if families[i] != families[i - 1]:
            pair = (families[i - 1], families[i])
            if pair not in SWITCH_LABEL:
                raise ValueError(f"half-year basis switches from {pair[0]} to {pair[1]} at "
                                 "an unexplained point: the group-margin note covers only the known three")
            switches.append((i, SWITCH_LABEL[pair]))
    return switches


def check_half_matches_quarter(st: dict) -> None:
    """Kering prints each half with a quarter's revenue: H1 with Q2, the year with Q4.

    So a first-quarter page stands on last year's second half, a second- or
    third-quarter page on this year's first half. A roll that appends the quarter
    and not the half (or the other way round) would print one period's profit
    beside another period's revenue under the wrong title.
    """
    year, number = quarter_parts(st["long_quarters"][-1])
    expected = {1: f"H2 {year - 1}", 2: f"H1 {year}", 3: f"H1 {year}", 4: f"H2 {year}"}[number]
    if st["halves"][-1] != expected:
        raise ValueError(f"series ends at quarter {st['long_quarters'][-1]!r} and half {st['halves'][-1]!r}; "
                         f"that quarter's release carries {expected!r}")


def retail_regions(st: dict) -> dict:
    """Gucci's retail growth by region on the new segment grid, ending on the page's quarter."""
    block = st["new_grid_retail_regions"]
    if block["quarters"][-1] != st["long_quarters"][-1]:
        raise ValueError(f"series `new_grid_retail_regions` ends at {block['quarters'][-1]!r}, "
                         f"but the page's quarter is {st['long_quarters'][-1]!r}: add the quarter's regions")
    for region, values in block["gucci"].items():
        if len(values) != len(block["quarters"]):
            raise ValueError(f"series `new_grid_retail_regions` {region!r} is not as long as its quarters")
    return block


def check_release_in_sources(st: dict) -> str:
    """The release that first publishes the page's quarter has to be in `sources`."""
    doc = release_doc(st["long_quarters"][-1])
    if doc not in {item["doc"] for item in st["sources"]}:
        raise ValueError(f"series `sources` has no entry {doc!r}: add this quarter's release with the roll")
    return doc


def half_bridge_block(st: dict) -> dict | None:
    """The half's income-statement bridge, checked against the half-year series."""
    block = stamped_block(st, "half_bridge", st["halves"][-1])
    if block is None:
        return None
    hg = st["half_group"]
    current = block["current"]
    for key, series_key in (("revenue", "revenue"), ("gross_margin", "gross_margin"),
                            ("recurring_operating_income", "recurring_operating_income")):
        if current[key] != hg[series_key]["values"][-1]:
            raise ValueError(f"series block `half_bridge` has {key} {current[key]!r} for "
                             f"{block['period']}, the half-year series {hg[series_key]['values'][-1]!r}")
    return block


# ── derivations ──────────────────────────────────────────────────────────────
def derived(st: dict) -> dict:
    q = st["long_quarters"]
    rev = st["quarterly_revenue_eur_m"]
    comp = st["quarterly_comparable_pct"]
    halves = st["halves"]
    hg = st["half_group"]
    hh = st["half_house"]

    group_margin = [ratio(r, v) for r, v in zip(hg["recurring_operating_income"]["values"], hg["revenue"]["values"])]
    gross_rate = [ratio(g, v) for g, v in zip(hg["gross_margin"]["values"], hg["revenue"]["values"])]
    house_margin = {h: [ratio(r, v) for r, v in zip(hh[h]["roi_eur_m"], hh[h]["revenue_eur_m"])]
                    + [None] * (len(halves) - len(hh[h]["roi_eur_m"]))
                    for h in ("gucci", "saint_laurent", "bottega_veneta")}

    houses_sum = [None if rev["other_houses"][i] is None else
                  sum(rev[h][i] for h in ("gucci", "saint_laurent", "bottega_veneta", "other_houses"))
                  for i in range(len(q))]
    gucci_share = [None if s is None else rev["gucci"][i] / s * 100 for i, s in enumerate(houses_sum)]

    gucci_neg_streak = trailing_streak(comp["gucci"], lambda v: v < 0)
    group_c = comp["group_first_published"]
    last_positive_before = next((i for i in range(len(q) - 2, -1, -1) if group_c[i] > 0), None)

    # the latest half's margin bridge, in percentage points of revenue
    block = half_bridge_block(st)
    bridge = None
    if block is not None:
        a, b = block["prior"], block["current"]
        rate = lambda row, k: row[k] / row["revenue"] * 100
        bridge = {
            "gross": rate(b, "gross_margin") - rate(a, "gross_margin"),
            "personnel": rate(b, "personnel_expenses") - rate(a, "personnel_expenses"),
            "other": rate(b, "other_recurring_operating_income_expenses") - rate(a, "other_recurring_operating_income_expenses"),
            "from": rate(a, "recurring_operating_income"),
            "to": rate(b, "recurring_operating_income"),
        }

    # guidance settlement (published basis; see the footnote note)
    idx = {h: i for i, h in enumerate(halves)}
    roi = hg["recurring_operating_income"]["values"]
    h1_23, h2_23 = roi[idx["H1 2023"]], roi[idx["H2 2023"]]
    h1_24, h2_24 = roi[idx["H1 2024"]], roi[idx["H2 2024"]]
    fy_23, fy_24 = h1_23 + h2_23, h1_24 + h2_24
    fy_guide = st["guidance_record"]["roi_2024"][2]["point_eur_m"]
    settle = {
        "h1": (h1_24 / h1_23 - 1) * 100, "h2": (h2_24 / h2_23 - 1) * 100,
        "fy": (fy_24 / fy_23 - 1) * 100, "fy_implied": (fy_guide / fy_23 - 1) * 100,
        "fy_eur": fy_24, "fy_23": fy_23, "h1_23": h1_23, "h2_23": h2_23, "h1_24": h1_24, "h2_24": h2_24,
    }

    ann = st["annual_house"]
    ann_margin = {h: [r / v * 100 for r, v in zip(ann[h]["roi_eur_m"], ann[h]["revenue_eur_m"])] for h in ann}

    # The Capital Markets Day target is defined on FY2025, so FY2025 is fixed here.
    fy25_margin = (hg["recurring_operating_income"]["values"][idx["H1 2025"]]
                   + hg["recurring_operating_income"]["values"][idx["H2 2025"]]) / (
        hg["revenue"]["values"][idx["H1 2025"]] + hg["revenue"]["values"][idx["H2 2025"]]) * 100

    cmd_line = 2 * fy25_margin
    above = [halves[i] for i, m in enumerate(group_margin) if m is not None and m > cmd_line]

    return {
        "halves_above_cmd": len(above), "last_above_cmd": above[-1] if above else "—",
        "group_margin": group_margin, "gross_rate": gross_rate, "house_margin": house_margin,
        "houses_sum": houses_sum, "gucci_share": gucci_share,
        "gucci_neg_streak": gucci_neg_streak, "last_positive_before": last_positive_before,
        "bridge": bridge, "bridge_block": block, "settle": settle, "ann_margin": ann_margin,
        "fy25_margin": fy25_margin, "cmd_margin_line": 2 * fy25_margin,
    }


def targets_2022(st: dict, der: dict) -> dict:
    """「实际 ÷ 目标」 for the five FY2022 targets, in FY2022 and in the last year all five have."""
    ann = st["annual_house"]
    g_years, s_years = ann["gucci"]["years"], ann["saint_laurent"]["years"]
    g_rev, s_rev = ann["gucci"]["revenue_eur_m"], ann["saint_laurent"]["revenue_eur_m"]
    s_m = der["ann_margin"]["saint_laurent"]
    ey = st["targets_2022"]["eyewear_fy2025"]
    now = ey["year"]
    if now not in g_years or now not in s_years:
        raise ValueError(f"the eyewear actuals are for {now}, which the brand series do not both carry")
    ig22, is22 = g_years.index("FY2022"), s_years.index("FY2022")
    ig, is_ = g_years.index(now), s_years.index(now)
    ey_m = ey["roi_eur_m"] / ey["revenue_eur_m"] * 100
    t = TARGETS_2022
    items = [("Gucci 收入", g_rev[ig22] / t["gucci_revenue"] * 100, g_rev[ig] / t["gucci_revenue"] * 100),
             ("SL 收入", s_rev[is22] / t["sl_revenue"] * 100, s_rev[is_] / t["sl_revenue"] * 100),
             ("SL 利润率", s_m[is22] / t["sl_margin"] * 100, s_m[is_] / t["sl_margin"] * 100),
             ("眼镜收入", None, ey["revenue_eur_m"] / t["eyewear_revenue"] * 100),
             ("眼镜利润率", None, ey_m / t["eyewear_margin"] * 100)]
    return {"now": now, "items": items, "ey_m": ey_m,
            "g22": g_rev[ig22], "g_now": g_rev[ig], "s_m22": s_m[is22], "s_m_now": s_m[is_]}


# ── section one (a)(b): last quarter's questions and thresholds ──────────────
# Readers' names for the quantities a threshold block may name. The half-year and
# net-debt measures and the two 42-quarter comparable lines can be drawn against
# their thresholds; the new-grid ones have only the quarters since the 2026 segment
# change and are drawn in the quarter's own charts instead.
MEASURE_NAMES = {
    "group_comparable": "集团季度可比增速", "gucci_comparable": "Gucci 季度可比增速",
    "gucci_na_retail": "Gucci 北美零售可比增速", "gucci_retail": "Gucci 零售可比增速",
    "jewelry_comparable": "珠宝季度可比增速", "eyewear_comparable": "眼镜季度可比增速",
    "half_gross_margin": "半年毛利率", "half_recurring_margin": "半年经常性营业利润率",
    "net_debt": "期末净负债", "half_group_comparable": "上半年集团可比增速",
    "half_jewelry_comparable": "上半年珠宝可比增速",
}
BULL = "加仓"


def previous_quarter(period: str) -> str:
    """`2026Q2` -> `2026Q1`; `2026Q1` -> `2025Q4`."""
    year, number = quarter_parts(period)
    return f"{year - (number == 1)}Q{(number - 2) % 4 + 1}"


def threshold_text(entry: dict) -> str:
    """How a threshold reads in a label: growth signed, margins plain, net debt in billions."""
    t = entry["threshold"]
    if entry["unit"] == "eur_m":
        return f"€{t / 1000:.1f}B"
    digits = 0 if float(t).is_integer() else 1
    return minus_sign(signed(t, digits)) if entry.get("signed") else f"{t:.{digits}f}%"


def value_text(entry: dict, value: float) -> str:
    """A measured value in the same dress as its threshold."""
    if entry["unit"] == "eur_m":
        return euro_m(value)
    digits = 0 if float(value).is_integer() else 1
    if not entry.get("signed"):
        return f"{value:.{digits}f}%"
    return minus_sign(flat_signed(value) if digits == 0 else signed(value, digits))


def joined_words(words: list[str]) -> str:
    """「警示」「警示与减仓」「警示、减仓与跟踪」."""
    if len(words) <= 1:
        return "".join(words)
    return "、".join(words[:-1]) + "与" + words[-1]


def gate_label(entry: dict) -> str:
    """「H1 集团可比 ≥+2%（加仓）」: the report's own comparator and action. A bare
    「<」 would be read as markup in a chart label, so it prints full width."""
    rule = {"<": "＜", ">": "＞"}.get(entry["rule"], entry["rule"])
    return f"{entry['metric']} {rule}{threshold_text(entry)}（{entry['gate']}）"


def on_good_side(entry: dict, key: str = "actual") -> bool:
    """A buy line is on its good side once reached; any other line while not triggered."""
    return headroom(entry["direction"], entry["threshold"], entry[key]) >= 0


def followup_items(st: dict) -> dict | None:
    """Report §0's closure of last quarter's questions, stamped with the quarter it closes in."""
    period = st["long_quarters"][-1]
    block = stamped_block(st, "followup_closure", display_period(period))
    if block is None:
        return None
    if block["set_in"] != display_period(previous_quarter(period)):
        raise ValueError(f"series block `followup_closure` closes questions set in {block['set_in']!r}, "
                         f"but last quarter was {display_period(previous_quarter(period))!r}")
    unknown = sorted({item["label"] for item in block["items"]} - set(block["labels"]))
    if unknown:
        raise ValueError(f"series block `followup_closure` uses labels {unknown} it does not declare")
    return block


def prior_entries(st: dict, der: dict) -> tuple[dict, list[dict]] | None:
    """Last quarter's thresholds with this quarter's value beside each.

    A value the series can measure is measured; a typed `actual` beside it would be a
    second copy free to drift, so it stops the build. A value the series does not carry
    (a half-year comparable rate) is typed once, with where it was read.
    """
    period = st["long_quarters"][-1]
    block = stamped_block(st, "prior_kpi_settlement", display_period(period))
    if block is None:
        return None
    if block["set_in"] != display_period(previous_quarter(period)):
        raise ValueError(f"series block `prior_kpi_settlement` settles thresholds set in {block['set_in']!r}, "
                         f"but last quarter was {display_period(previous_quarter(period))!r}")
    values = measured(st, der)
    entries = []
    for entry in block["entries"]:
        if entry["measure"] in values:
            if "actual" in entry:
                raise ValueError(f"threshold on {entry['measure']!r} is measured from the series; "
                                 "remove its typed actual")
            actual = values[entry["measure"]]
        elif "actual" in entry and entry.get("source"):
            actual = entry["actual"]
        else:
            raise ValueError(f"threshold on {entry['measure']!r} has no value and no source for one")
        entries.append({**entry, "actual": actual, "label": gate_label(entry)})
    return block, entries


def long_series(st: dict, der: dict, measure: str) -> dict | None:
    """The long line a threshold on `measure` can be drawn against, or None."""
    q = st["long_quarters"]
    comp = st["quarterly_comparable_pct"]
    if measure in ("group_comparable", "gucci_comparable"):
        key = "group_first_published" if measure == "group_comparable" else "gucci"
        return {"xlabels": [compact_quarter(p) for p in q], "values": rounded(comp[key]), "fmt": "pct0",
                "ylab": "可比增速", "xstep": LONG_STEP, "zero_line": True,
                "break": ((q.index("2018Q1"), "此前含 Puma") if measure == "group_comparable" else None)}
    basis = st["half_group"]["recurring_operating_income"]["basis"]
    if measure == "half_recurring_margin":
        switches = basis_switches(basis)
        return {"xlabels": st["halves"], "values": rounded(der["group_margin"]), "fmt": "pct1",
                "ylab": "半年经常性营业利润率 D", "xstep": 2,
                "break": ([i for i, _ in switches], [label for _, label in switches])}
    if measure == "half_gross_margin":
        switches = [(i, label) for i, label in basis_switches(basis)
                    if BASIS_FAMILY[basis[i]] != "continuing_ifrs16"]
        return {"xlabels": st["halves"], "values": rounded(der["gross_rate"]), "fmt": "pct1",
                "ylab": "半年毛利率 D", "xstep": 2,
                "break": ([i for i, _ in switches], [label for _, label in switches])}
    if measure == "net_debt":
        return {"xlabels": st["balance_dates"], "values": rounded(st["net_debt_eur_m"], 1), "fmt": "f0c",
                "ylab": "€M（期末）", "xstep": 2, "break": None}
    return None


def gate_chart(title: str, spec: dict, entries: list[dict], value_key: str, word: str,
               note: str, src_extra: str) -> dict:
    """One measure against every threshold set on it: the helper's line for the first,
    one more flat line per further threshold. Buy lines are green, the rest red."""
    first = entries[0]
    side = lambda e: "上方" if e["direction"] == "up" else "下方"
    chart = threshold_exhibit(
        title, spec["xlabels"], spec["values"], first["threshold"],
        fmt=spec["fmt"], ylab=spec["ylab"], actual_name=MEASURE_NAMES[first["measure"]],
        threshold_name=f"{word}{first['gate']}线 {threshold_text(first)}（有利一侧在{side(first)}）",
        note=note, src_extra=src_extra, xstep=spec["xstep"])
    chart["series"][1]["color"] = "GREEN" if first["gate"] == BULL else "RED"
    for entry in entries[1:]:
        chart["series"].append({
            "name": f"{word}{entry['gate']}线 {threshold_text(entry)}（有利一侧在{side(entry)}）",
            "values": [entry["threshold"]] * len(spec["xlabels"]),
            "color": "GREEN" if entry["gate"] == BULL else "RED"})
    if spec.get("zero_line"):
        chart["zero_line"] = True
    if spec.get("break"):
        at, label = spec["break"]
        chart["break_at"], chart["break_label"] = at, label
    return chart


def by_measure(entries: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for entry in entries:
        grouped.setdefault(entry["measure"], []).append(entry)
    return grouped


def next_threshold_sets(st: dict, der: dict) -> dict[str, frozenset]:
    """Which measures section three draws, with which thresholds -- a prior chart that
    would repeat one of them exactly is left to section three."""
    sets: dict[str, set] = {}
    for entry in threshold_entries(st, der):
        if long_series(st, der, entry["measure"]) is not None:
            sets.setdefault(entry["measure"], set()).add(entry["threshold"])
    return {k: frozenset(v) for k, v in sets.items()}


def settled_story_charts(st: dict, der: dict) -> list[dict]:
    """Section one (a) and (b): report §0's closure, then last quarter's thresholds."""
    charts = []
    closure = followup_items(st)
    if closure is not None:
        items = closure["items"]
        counts = [(label, sum(1 for item in items if item["label"] == label)) for label in closure["labels"]]
        shown = [(label, n) for label, n in counts if n]
        failed = [item["question"] for item in items if item["label"] == "上季判断失效"]
        open_ = [item["question"] for item in items if item["label"] == "未回答"]
        charts.append({
            "ref": "EX_CLOSURE",
            "kind": "bars_labeled",
            "title": f"上季 {len(items)} 条待验证问题：" + "、".join(f"{n} 条{label}" for label, n in shown),
            "xlabels": [label for label, _ in shown],
            "values": [n for _, n in shown],
            "legend": "问题条数",
            "fmt": "f0", "yfmt": "f0", "label_fmt": "f0",
            "ylab": "条",
            "note": ((f"<b>上季判断失效的是「{'」「'.join(failed)}」</b>" if failed else "")
                     + ("；" if failed and open_ else "")
                     + (f"没有得到回答的是「{'」「'.join(open_)}」。" if open_ else ("。" if failed else ""))
                     + "本季分析稿第 0 节逐条给了判定、没有给汇总数，图上按判定原话归类："
                     "强验证、闭环与已给出答案的算已闭环；部分验证、方向对但幅度或量化缺失、主问题有答案而子问题"
                     "未答的算部分闭环。每一条的原话见核对表。"),
            "src_extra": ("问题清单来自上季两份本地分析稿的 Follow-up，被本季本地分析稿第 0 节合并逐条核验；"
                          "判定依据本季新闻稿、演示材料与电话会。"),
        })
    prior = prior_entries(st, der)
    if prior is None:
        return charts
    block, entries = prior
    bull = [e for e in entries if e["gate"] == BULL]
    bear = [e for e in entries if e["gate"] != BULL]
    bull_hit = [e for e in bull if on_good_side(e)]
    bull_missed = [e for e in bull if not on_good_side(e)]
    bear_hit = [e for e in bear if not on_good_side(e)]
    present = {e["gate"] for e in bear}
    gates = joined_words([g for g in ("警示", "减仓", "跟踪") if g in present]
                         + sorted(present - {"警示", "减仓", "跟踪"}))
    parts = []
    if bull:
        bits = ([f"{len(bull_hit)} 条达到"] if bull_hit else []) + (
            [f"{len(bull_missed)} 条没够着"] if bull_missed else [])
        parts.append(f"{len(bull)} 条加仓线 " + "、".join(bits))
    if bear:
        parts.append(f"{len(bear)} 条{gates}线" + ("一条都没碰到" if not bear_hit else
                                                  f"有 {len(bear_hit)} 条被触发"))
    missed_words = "；".join(f"{e['metric']} {value_text(e, e['actual'])} 对 {threshold_text(e)}"
                             for e in bull_missed)
    hit_words = "；".join(f"{e['metric']} {value_text(e, e['actual'])} 触发了{e['gate']}线 {threshold_text(e)}"
                          for e in bear_hit)
    # The two half-year group lines do not say which growth rate they mean. The page
    # settles them on the comparable rate -- the basis of the 「当前」 column beside them
    # -- and says what the reported rate would do to the lower one.
    basis_words = ""
    group_lower = [e for e in entries if e["measure"] == "half_group_comparable" and e["gate"] != BULL]
    hg = st["half_group"]["revenue"]["values"]
    if group_lower and len(hg) >= 3:
        reported = (hg[-1] / hg[-3] - 1) * 100
        lower = group_lower[0]
        crosses = not on_good_side({**lower, "actual": round(reported)})
        basis_words = ("H1 集团那两条原话没写是可比还是报告口径，这里按可比口径（与原话「当前」一栏同一口径）结算；"
                       f"报告口径是 {minus_sign(f'{reported:.0f}')}%，"
                       + (f"按它算会触发{lower['gate']}线 {threshold_text(lower)}。" if crosses
                          else f"按它算也没有碰到{lower['gate']}线 {threshold_text(lower)}。"))
    note = ("正值 = 在这条线有利的一侧：加仓线是已经达到，警示、减仓与跟踪线是没有触发。"
            + (f"<b>没够着的加仓线：{missed_words}。</b>" if bull_missed else "")
            + (f"<b>被触发的：{hit_words}。</b>" if bear_hit else "")
            + block.get("conjunctions", "")
            + basis_words
            + (f"另有{cn_count(len(block['unsettled']))}条本季无法结算，原因列在核对表里。"
               if block.get("unsettled") else ""))
    charts.append({"ref": "EX_PRIOR_HEADROOM"} | headroom_exhibit(
        f"上季 {len(entries)} 条量化阈值：" + "，".join(parts),
        [{**e, "metric": e["label"]} for e in entries], "actual", note,
        "阈值与动作逐字取自上季两份本地分析稿第 8 节，不是公司指引；实际值是本季公司印出的数字，出处见核对表。"))

    # one chart per measure that has a long line, unless section three draws the
    # same measure against exactly the same thresholds
    following = next_threshold_sets(st, der)
    for measure, group in by_measure(entries).items():
        spec = long_series(st, der, measure)
        if spec is None or following.get(measure) == frozenset(e["threshold"] for e in group):
            continue
        actual = group[0]["actual"]
        verdicts = []
        for e in group:
            if e["gate"] == BULL:
                verdicts.append(f"{'达到' if on_good_side(e) else '没够着'}上季加仓线 {threshold_text(e)}")
            else:
                verdicts.append(f"{'没碰到' if on_good_side(e) else '触发了'}上季{e['gate']}线 {threshold_text(e)}")
        charts.append({"ref": f"EX_PRIOR_{measure.upper()}"} | gate_chart(
            f"{MEASURE_NAMES[measure]} {value_text(group[0], actual)}：" + "，".join(verdicts),
            spec, group, "actual", "上季",
            "；".join(f"{e['gate']}线 {threshold_text(e)}，余量 "
                     f"{headroom(e['direction'], e['threshold'], e['actual']):+.1f}%" for e in group)
            + f"。当前 {value_text(group[0], actual)}"
            + ("（公司印出的一位小数；线上画的是未取整的自算值）" if measure == "half_recurring_margin" else "")
            + "。",
            "阈值逐字取自上季本地分析稿第 8 节，不是公司指引；实际值取自各期公司公告。"))
    return charts


# ── section one (c): the numbers Kering itself gave, settled ─────────────────
def gucci_target_facts(st: dict, der: dict) -> dict:
    ann = st["annual_house"]["gucci"]
    years, g_rev, g_m = ann["years"], ann["revenue_eur_m"], der["ann_margin"]["gucci"]
    target = st["guidance_record"]["medium_term_2019"][0]
    rev_goal, margin_goal = target["revenue_targets_eur_m"][0], target["margin_targets_pct"][0]
    rev_hit = [years[i] for i, v in enumerate(g_rev) if v >= rev_goal]
    m_hit = [years[i] for i, v in enumerate(g_m) if v >= margin_goal]
    both = [years[i] for i in range(len(years)) if g_rev[i] >= rev_goal and g_m[i] >= margin_goal]
    return {"target": target, "rev_goal": rev_goal, "margin_goal": margin_goal,
            "rev_hit": rev_hit, "m_hit": m_hit, "both": both}


def settled_charts(st: dict, der: dict) -> list[dict]:
    s = der["settle"]
    g = st["guidance_record"]
    h1_guide, h2_guide, fy_guide = g["roi_2024"]
    ann = st["annual_house"]
    years = ann["gucci"]["years"]
    g_rev, g_m = ann["gucci"]["revenue_eur_m"], der["ann_margin"]["gucci"]
    sl_years = ann["saint_laurent"]["years"]
    y_rev, y_m = ann["saint_laurent"]["revenue_eur_m"], der["ann_margin"]["saint_laurent"]

    # The words the note quotes are the record's own; a quote the record does not
    # contain is a second copy that has drifted.
    for fragment, guide in (("a decline of 40 to 45%", h1_guide), ("could be down by approximately 30%", h2_guide),
                            ("approximately €2.5 billion", fy_guide)):
        if fragment not in guide["quote"]:
            raise ValueError(f"the 2024 guidance note quotes {fragment!r}, which the record's quote lacks")
    h1_inside = h1_guide["low"] <= s["h1"] <= h1_guide["high"]
    h2_gap = abs(s["h2"] - h2_guide["point"])
    h2_gap_text = "二十多个百分点" if 20 <= h2_gap < 30 else f"{h2_gap:.1f} 个百分点"
    month = lambda date: f"{int(date[5:7])} 月"

    gt = gucci_target_facts(st, der)
    g_rev_hit, g_m_hit, g_both = gt["rev_hit"], gt["m_hit"], gt["both"]
    after = max(years.index(g_rev_hit[0]), years.index(g_m_hit[0]))
    both_fall = after < len(years) - 1 and all(g_rev[i] < g_rev[i - 1] and g_m[i] < g_m[i - 1]
                                                 for i in range(after + 1, len(years)))

    sl_target = g["medium_term_2019"][1]
    tiers = list(zip(sl_target["revenue_targets_eur_m"], sl_target["margin_targets_pct"]))
    firsts = [next((i for i, v in enumerate(y_rev) if v >= rev_goal), None) for rev_goal, _ in tiers]
    all_tiers = all(i is not None for i in firsts)
    margins_above = all_tiers and all(y_m[i] > m_goal for i, (_, m_goal) in zip(firsts, tiers))
    top = tiers[-1][0]

    t = targets_2022(st, der)
    items = t["items"]
    t22 = [a for _, a, _ in items]
    tnow = [b for _, _, b in items]
    on_target = [label for label, _, b in items if b is not None and b >= 100]
    prose = st["targets_2022"]["eyewear_fy2022_prose"]
    if "€1.1 billion" not in prose:
        raise ValueError("the targets note quotes eyewear's FY2022 revenue as 「€1.1 billion」, which the record lacks")
    if on_target == ["眼镜利润率"]:
        on_target_text = f"图上五项里只有眼镜的利润率站在目标上：{t['now']} 为 {t['ey_m']:.1f}%。"
    elif not on_target:
        on_target_text = f"图上{cn_count(len(items))}项没有一项站在目标上。"
    else:
        on_target_text = f"图上{cn_count(len(items))}项里站在目标上的是{'、'.join(on_target)}。"

    return [
        {
            "ref": "EX_G2024",
            "kind": "grouped_bars",
            "title": (f"2024 年三次利润指引：上半年落在区间{'里' if h1_inside else '外'}，"
                      f"下半年的「约 {minus_sign(str(h2_guide['point']))}%」实际是 {s['h2']:.1f}%"),
            "xlabels": ["2024 上半年", "2024 下半年", "2024 全年"],
            "xrot": 0,
            # Plotted as the size of the decline: an all-negative grouped_bars
            # puts its axis top at max x 1.22, still below zero, and every bar
            # is drawn from zero straight off the canvas.
            "groups": [
                {"name": "公司所述降幅（区间取中点；全年为 €2.5B 折算 D）", "color": "GOLD",
                 "values": rounded([-(h1_guide["low"] + h1_guide["high"]) / 2, float(-h2_guide["point"]),
                                    -s["fy_implied"]])},
                {"name": "实际降幅（报告口径 D）", "color": "NAVY",
                 "values": rounded([-s["h1"], -s["h2"], -s["fy"]])},
            ],
            "bar_labels": True,
            "fmt": "pct1", "label_fmt": "pct1", "yfmt": "pct0",
            "ylab": "经常性营业利润同比降幅",
            "note": ("<b>2024 年 Kering 三次在新闻稿里给出经常性营业利润的数字。</b>"
                     f"{h1_guide['release_date']} 的一季度收入公告说上半年经常性营业利润将「a decline of 40 to 45%」，"
                     f"实际 €{s['h1_24']:,.0f}M 对 €{s['h1_23']:,.0f}M，{s['h1']:.1f}%，"
                     f"{'落在区间里' if h1_inside else '落在区间外'}。"
                     f"{month(h2_guide['release_date'])}的半年报接着说下半年「could be down by approximately 30%」；"
                     f"实际下半年是 €{s['h2_24']:,.0f}M D 对 €{s['h2_23']:,.0f}M D，{s['h2']:.1f}% —— "
                     f"差了{h2_gap_text}。{month(fy_guide['release_date'])}的三季度收入公告把它换成了全年"
                     "「approximately €2.5 billion」，"
                     f"实际 €{s['fy_eur']:,.0f}M，这一次{APPROX_VERDICT['fy_2024']}。"
                     "两句下半年与全年指引都带脚注「Based on the scope of consolidation and exchange rates」"
                     "（当时的合并范围与汇率）；公司从未按那个口径公布实际值，本页用报告口径结算，"
                     "而同期三季度收入公告给的汇率影响只有约 −1%，解释不了这个差。"),
            "src_extra": SOURCE_G,
        },
        {
            "ref": "EX_GUCCI_TARGET",
            "kind": "bar_line_dual",
            "title": (f"Gucci 的中期目标「收入 €{gt['rev_goal'] / 1000:.0f}B / 利润率 {gt['margin_goal']}%+」："
                      f"收入在 {g_rev_hit[0]} 达到、"
                      f"利润率在 {g_m_hit[0]} 达到，{'从未同一年' if not g_both else '同年达到'}"),
            "xlabels": years,
            "bar": {"name": "Gucci 全年收入", "values": rounded(g_rev, 1), "color": "NAVY"},
            "line": {"name": "Gucci 全年经常性营业利润率 D (RHS)", "values": rounded(g_m), "color": "RED",
                     "yfmt": "pct0"},
            "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
            "ylab": "€M（全年）", "ylab2": "经常性营业利润率",
            "note": (f"<b>这是 {gt['target']['release_date']} 全年业绩演示材料上给 Gucci 的中期目标："
                     f"「{gt['target']['quote']}」。</b>"
                     f"利润率在 {g_m_hit[0]} 做到 {g_m[years.index(g_m_hit[0])]:.1f}%，那一年收入 "
                     f"€{g_rev[years.index(g_m_hit[0])]:,.0f}M；收入在 {g_rev_hit[0]} 做到 "
                     f"€{g_rev[years.index(g_rev_hit[0])]:,.0f}M，那一年利润率 "
                     f"{g_m[years.index(g_rev_hit[0])]:.1f}%。{'之后两条线一起往下走，' if both_fall else ''}"
                     f"{years[-1]} 收入 €{g_rev[-1]:,.0f}M、利润率 {g_m[-1]:.1f}%。"
                     "利润率按公司印出的品牌经常性营业利润 ÷ 品牌收入重算；2018 年及以前为 IAS 17 口径，"
                     "2019 年起为 IFRS 16 口径，按当年公布值、不做回溯。"),
            "src_extra": (f"目标取自 FY2018 业绩演示材料第 {gt['target']['source_pages']} 页；"
                          "实际值取自各年全年业绩新闻稿。"),
        },
        {
            "ref": "EX_YSL_TARGET",
            "kind": "bar_line_dual",
            "title": (f"Saint Laurent 的{cn_count(len(tiers))}级目标"
                      + ("都兑现：" if all_tiers else "：")
                      + "、".join(f"€{rev_goal / 1000:.0f}B 在 {sl_years[i]}" if i is not None
                                 else f"€{rev_goal / 1000:.0f}B 未达到"
                                 for i, (rev_goal, _) in zip(firsts, tiers))
                      + ("，利润率当年都在目标之上" if margins_above else "")),
            "xlabels": sl_years,
            "bar": {"name": "Saint Laurent 全年收入", "values": rounded(y_rev, 1), "color": "NAVY"},
            "line": {"name": "Saint Laurent 全年经常性营业利润率 D (RHS)", "values": rounded(y_m),
                     "color": "RED", "yfmt": "pct0"},
            "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
            "ylab": "€M（全年）", "ylab2": "经常性营业利润率",
            "note": (f"同一份演示材料写的是「{sl_target['quote']}」。"
                     + "；".join(f"{sl_years[i]} 收入 €{y_rev[i]:,.0f}M、利润率 {y_m[i]:.1f}%"
                                for i in firsts if i is not None) + "。"
                     + ("<b>同一份材料上两个品牌、两种结局</b>：Saint Laurent 在收入跨过每一级目标的那一年，"
                        "利润率都已在对应目标之上；Gucci 的两条是在不同年份分别碰到线（见上一张）。"
                        if margins_above and not g_both else "")
                     + f"{sl_years[-1]} Saint Laurent 收入 €{y_rev[-1]:,.0f}M"
                     + (f"，已回到 €{top / 1000:.0f}B 之下。" if y_rev[-1] < top else "。")),
            "src_extra": (f"目标取自 FY2018 业绩演示材料第 {sl_target['source_pages']} 页；"
                          "实际值取自各年全年业绩新闻稿。"),
        },
        {
            "ref": "EX_TARGETS_2022",
            "kind": "grouped_bars",
            "title": (f"FY2022 年报里的中期目标：Gucci €15B 在 {t['now']} 只完成 {tnow[0]:.0f}%，"
                      f"比 FY2022 的 {t22[0]:.0f}% 更{'远' if tnow[0] < t22[0] else '近'}"),
            "xlabels": [lab for lab, _, _ in items],
            "groups": [
                {"name": "FY2022", "color": "GOLD", "values": rounded(t22)},
                {"name": t["now"], "color": "NAVY", "values": rounded(tnow)},
            ],
            "bar_labels": True,
            "fmt": "pct0", "label_fmt": "pct0", "yfmt": "pct0",
            "ylab": "实际 ÷ 目标 D",
            "note": ("<b>FY2022 Universal Registration Document 把三个业务的中期目标写成了新的数字</b>"
                     "（Saint Laurent 与眼镜两处都注明是 2022 年更新）：Gucci「medium-term sales target of €15 billion」；Saint Laurent「revenue (now €5 billion) "
                     "and recurring operating margin (now 33%)」；Kering Eyewear「€2 billion in revenue and operating margin of over "
                     "15%」。图上每根柱是「实际 ÷ 目标」：Gucci 收入对 €15B，SL（Saint Laurent）收入对 €5B、利润率对 33%，"
                     "眼镜收入对 €2B、利润率对 15%。"
                     f"Gucci 从 FY2022 的 €{t['g22']:,.0f}M 走到 {t['now']} 的 €{t['g_now']:,.0f}M；"
                     f"Saint Laurent 利润率从 {t['s_m22']:.1f}% {'降到' if t['s_m_now'] < t['s_m22'] else '升到'} "
                     f"{t['s_m_now']:.1f}%。"
                     + on_target_text +
                     "眼镜 FY2022 的收入公司只在正文里写了「€1.1 billion」、利润没有单列，所以那两根柱留空；"
                     "Gucci 目标里的利润率只写了「historical recurring operating margin」，没有数字，不画。"),
            "src_extra": (f"目标取自 FY2022 Universal Registration Document 第 47、49、59 页；"
                          f"实际值取自 FY2022 与 {t['now']} 全年业绩新闻稿。"),
        },
    ]


# ── section two: the quarter ─────────────────────────────────────────────────
def group_turn(st: dict, der: dict) -> dict:
    """Where the group's comparable growth stands against its own recent run."""
    q = st["long_quarters"]
    group_c = st["quarterly_comparable_pct"]["group_first_published"]
    lp = der["last_positive_before"]
    cur = group_c[-1]
    return {"cur": cur, "lp": lp,
            "first_again": cur > 0 and lp is not None and lp < len(q) - 2,
            "pos_streak": trailing_streak(group_c, lambda v: v > 0),
            "nonpos_streak": trailing_streak(group_c, lambda v: v <= 0)}


def quarter_bridge(st: dict) -> dict | None:
    """The latest quarter against the same quarter a year earlier, on the new segment grid."""
    q = st["long_quarters"]
    grid = st["new_grid"]
    gq = grid["quarters"]
    if gq[-1] != q[-1]:
        raise ValueError(f"series `new_grid` ends at {gq[-1]!r}, but the page's quarter is {q[-1]!r}")
    i_now = len(gq) - 1
    i_ago = year_ago_index(gq, i_now)
    if i_ago is None:
        return None
    gr = grid["revenue_eur_m"]
    legs = [("时装与皮具", "fashion_leather_goods"), ("珠宝", "jewelry"), ("眼镜", "eyewear"),
            ("集团其他", "corporate_and_other"), ("内部抵销", "eliminations")]
    deltas = [(zh, gr[k][i_now] - gr[k][i_ago]) for zh, k in legs]
    prev_ago = year_ago_index(gq, i_now - 1) if i_now >= 1 else None
    prev_net = None if prev_ago is None else gr["total"][i_now - 1] - gr["total"][prev_ago]
    return {
        "i_now": i_now, "i_ago": i_ago, "deltas": deltas,
        "net": gr["total"][i_now] - gr["total"][i_ago],
        "jewelry_eyewear": sum(d for zh, d in deltas if zh in ("珠宝", "眼镜")),
        "gucci": gr["gucci"][i_now] - gr["gucci"][i_ago],
        "prev_net": prev_net,
        "restated": "restatement" in grid["src"][i_ago],
        "now": display_period(gq[i_now]), "ago": display_period(gq[i_ago]),
        "doc": grid["src"][i_now],
    }


def census_sentence(st: dict) -> str:
    """What the corpus says about reprints of the three brand lines, if it has been read for this quarter."""
    audit = stamped_block(st, "corpus_audit", display_period(st["long_quarters"][-1]))
    if audit is None or not audit.get("reprint_census"):
        return ""
    exceptions = st["reprint_exceptions"]
    lines = ("gucci", "bottega_veneta", "saint_laurent")
    clean = [HOUSE_ZH[h] for h in lines if not any(x["line"] == h for x in exceptions)]
    text = ""
    if clean:
        text += (f"{' 与 '.join(clean)} 的季度收入在本页读过的全部文件里，"
                 "每一次被后续公告重印都与首次公布相同")
    for h in lines:
        mine = [x for x in exceptions if x["line"] == h]
        if not mine:
            continue
        spots = "、".join(f"{quarter_cn(x['period'])}" for x in mine)
        values = "；".join(f"{x['first_published']:g} 与 {x['reprinted']:g}" for x in mine)
        text += f"；{HOUSE_ZH[h]} 只有 {spots}{cn_count(len(mine))}处（{values}）"
    return text.lstrip("；") + "。"


def quarter_charts(st: dict, der: dict) -> list[dict]:
    q = st["long_quarters"]
    labels = [compact_quarter(p) for p in q]
    rev = st["quarterly_revenue_eur_m"]
    comp = st["quarterly_comparable_pct"]
    grid = st["new_grid"]
    gq = grid["quarters"]
    gc = grid["comparable_pct"]
    group_c = comp["group_first_published"]
    turn = group_turn(st, der)
    lp = turn["lp"]
    break_2018 = q.index("2018Q1")

    # ── group comparable growth
    if turn["first_again"]:
        comp_title = f"集团可比增速本季 {flat_signed(group_c[-1])}：{compact_quarter(q[lp])} 之后第一次为正"
        comp_lead = (f"<b>{compact_quarter(q[lp])} 的 {signed(group_c[lp], 0)} 之后，集团可比增速"
                     f"经历了 {len(q) - 2 - lp} 个非正季度</b>（最后一季 {compact_quarter(q[-2])} 为 "
                     f"{group_c[-2]:+.0f}%）".replace("+0%", "0%") + f"，本季回到 {signed(group_c[-1], 0)}。")
    elif turn["cur"] > 0:
        comp_title = f"集团可比增速本季 {flat_signed(group_c[-1])}：连续 {turn['pos_streak']} 个季度为正"
        comp_lead = f"<b>集团可比增速连续 {turn['pos_streak']} 个季度为正。</b>"
    else:
        comp_title = f"集团可比增速本季 {flat_signed(group_c[-1])}：连续 {turn['nonpos_streak']} 个季度不为正"
        comp_lead = (f"<b>集团可比增速连续 {turn['nonpos_streak']} 个季度不为正</b>"
                     + (f"（上一次为正是 {compact_quarter(q[lp])} 的 {signed(group_c[lp], 0)}）" if lp is not None else "")
                     + "。")
    lo = min(range(len(q)), key=lambda i: group_c[i])
    hi = max(range(len(q)), key=lambda i: group_c[i])
    extremes = ((f"2020 年二季度的 {signed(min(group_c), 0)} 是门店关闭，2021 年二季度的 "
                 f"{signed(max(group_c), 0)} 是对着那个低基数。")
                if (q[lo], q[hi]) == ("2020Q2", "2021Q2") else "")

    exhibits = [
        {
            "ref": "EX_GROUP_COMP",
            "kind": "lines",
            "title": comp_title,
            "xlabels": labels,
            "series": [{"name": "集团季度可比增速（当季首次公布）", "values": rounded(group_c), "color": "NAVY"}],
            "fmt": "pct0", "yfmt": "pct0", "label_fmt": "pct0",
            "ylab": "可比增速", "zero_line": True, "end_label": True, "xstep": LONG_STEP,
            "break_at": break_2018, "break_label": "此前含 Puma",
            "note": (comp_lead +
                     "可比增速按定义剔除汇率与合并范围变化，所以这条线能跨越 2018 年 Puma 分拆、"
                     "2023 年 Creed 并表与 2025 年 Kering Beauté 出售连续读；"
                     "但 2018 年以前的读数本身包含 Puma 等运动与生活方式业务，红色虚线标出这一处。"
                     + extremes),
            "src_extra": SOURCE_Q,
        },
    ]

    # ── the quarter's reported change, by segment
    br = quarter_bridge(st)
    if br is not None:
        deltas, net = br["deltas"], br["net"]
        _, number = quarter_parts(q[-1])
        if net > 0:
            prev_growing = br["prev_net"] is not None and br["prev_net"] > 0
            lead = ("<b>报告口径收入" + ("继续增长" if prev_growing else "回到增长")
                    + ("，不是 Gucci 带回来的。</b>" if br["gucci"] <= 0 else "。</b>"))
        else:
            lead = "<b>报告口径收入低于去年同季。</b>"
        restated = "（剔除 Kering Beauté 的重述值）" if br["restated"] else ""
        exhibits.append({
            "ref": "EX_Q2_BRIDGE",
            "kind": "bridge_bar",
            "title": ((f"本季报告口径收入多了 €{net:,.0f}M：" if net > 0 else
                       f"本季报告口径收入少了 €{-net:,.0f}M：" if net < 0 else "本季报告口径收入与去年同季持平：")
                      + f"珠宝与眼镜合计 {euro_delta(br['jewelry_eyewear'])}，"
                      f"时装与皮具 {euro_delta(deltas[0][1])}"),
            # a leg that did not move draws an empty column, so it is left off the chart
            "xlabels": [zh for zh, d in deltas if d != 0] + [f"Q{number} 收入同比变动"],
            "stacks": [{"name": "各分部同比变动（€M）", "color": "NAVY",
                        "values": rounded([d for _, d in deltas if d != 0] + [None], 1)}],
            "net": {"name": f"集团 {br['now']} 对 {br['ago']}{' 重述' if br['restated'] else ''}（€M）",
                    "values": [None] * sum(1 for _, d in deltas if d != 0) + [round(net, 6)]},
            "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
            "ylab": "€M（季度）",
            "note": (lead +
                     f"{br['now']} 集团 €{grid['revenue_eur_m']['total'][br['i_now']]:,}M 对 {br['ago']}{restated}"
                     f"€{grid['revenue_eur_m']['total'][br['i_ago']]:,}M，{'多' if net >= 0 else '少'} €{abs(net):,.0f}M；"
                     f"其中珠宝 {deltas[1][1]:+,.0f}、眼镜 {deltas[2][1]:+,.0f}，"
                     f"时装与皮具 {deltas[0][1]:+,.0f}（其中 Gucci {br['gucci']:+,.0f}）。"
                     + ("分部口径是 2026 年一季度起的新口径，2025 年各季由公司在 2026-03-16 的公告中重述，"
                        "所以这张桥只能对着重述值画，没有更早的同口径对照。" if br["restated"]
                        else "分部口径是 2026 年一季度起的新口径。")),
            "src_extra": (f"{br['now']} 与{'重述后的 ' if br['restated'] else ' '}{br['ago']} 取自 "
                          f"{release_cn(br['doc'], formal=True)}附表。"),
        })

    # ── the new segment grid
    n = len(gq)
    gucci_neg = sum(1 for v in gc["gucci"] if v < 0)
    if gucci_neg == n:
        gucci_part = f"Gucci {cn_count(n)}季全负"
    elif gucci_neg:
        gucci_part = f"Gucci {cn_count(n)}季里{cn_count(gucci_neg)}季为负"
    else:
        gucci_part = f"Gucci {cn_count(n)}季都不为负"
    jewelry_from = trailing_run_start(gc["jewelry"], lambda v: v >= 10)
    jewelry_part = (f"珠宝从 {compact_quarter(gq[jewelry_from])} 起两位数" if jewelry_from is not None
                    else f"珠宝本季 {signed(gc['jewelry'][-1], 0)}")
    g0, g1 = gc["gucci"][0], gc["gucci"][-1]
    gucci_move = ("收窄到" if g0 < 0 and g1 < 0 and g1 > g0 else "扩大到" if g0 < 0 and g1 < g0
                  else "转为" if g0 < 0 <= g1 else "变为")
    restated_n = sum(1 for src in grid["src"] if "restatement" in src)
    later_years = sorted({p[:4] for p, src in zip(gq, grid["src"]) if "restatement" not in src})
    later = (f"{later_years[0]} 年" if len(later_years) == 1
             else f"{later_years[0]}–{later_years[-1]} 年")
    exhibits.append({
        "ref": "EX_GRID",
        "kind": "grouped_bars",
        "title": f"新分部口径下的可比增速：{gucci_part}，{jewelry_part}",
        "xlabels": [compact_quarter(p) for p in gq],
        "groups": [
            {"name": "Gucci", "color": "NAVY", "values": rounded(gc["gucci"])},
            {"name": "时装与皮具（含 Gucci）", "color": "MBLUE", "values": rounded(gc["fashion_leather_goods"])},
            {"name": "珠宝", "color": "GOLD", "values": rounded(gc["jewelry"])},
            {"name": "眼镜", "color": "GREEN", "values": rounded(gc["eyewear"])},
        ],
        "bar_labels": True,
        "fmt": "pct0", "label_fmt": "pct0", "yfmt": "pct0",
        "ylab": "可比增速",
        "note": (f"<b>这张图只有{cn_count(n)}个季度，因为这套分部只存在{cn_count(n)}个季度。</b>"
                 "Kering 在 2026-03-16 宣布新分部（时装与皮具、珠宝、眼镜、集团其他），"
                 "只把 2025 年四个季度按新口径重述；珠宝此前包含在「其他品牌」里，没有按季单列的收入。"
                 f"Gucci 从 {signed(g0, 0)} {gucci_move} {signed(g1, 0)}，"
                 f"珠宝本季 {signed(gc['jewelry'][-1], 0)}、眼镜 {signed(gc['eyewear'][-1], 0)}。"
                 "Saint Laurent 与 Bottega Veneta 自 2026 年起不再单独披露收入。"),
        "src_extra": (f"2025 年{cn_count(restated_n)}个季度取自新分部口径重述公告（2026-03-16）；"
                      f"{later}取自当季公告。"),
    })

    # ── Gucci on the long axis
    streak = der["gucci_neg_streak"]
    gu = comp["gucci"]
    peak = rev["gucci"].index(max(rev["gucci"]))
    y2017 = [v for p, v in zip(q, gu) if p.startswith("2017")]
    if streak:
        gucci_title = (f"Gucci 本季收入 €{rev['gucci'][-1]:,.0f}M，可比增速连续 "
                       f"{streak} 个季度为负（本季 {signed(gu[-1], 0)}）")
    else:
        ended = trailing_streak(gu[:-1], lambda v: v < 0)
        gucci_title = (f"Gucci 本季收入 €{rev['gucci'][-1]:,.0f}M，可比增速 {flat_signed(gu[-1])}"
                       + (f"，此前连续 {ended} 个季度为负" if ended else ""))
    prev, cur = gu[-2], gu[-1]
    move = ("收窄到" if prev < 0 and cur < 0 and cur > prev else "扩大到" if prev < 0 and cur < prev
            else "转为" if prev < 0 <= cur else "变为")
    peak_text = (f"<b>峰值是 {compact_quarter(q[peak])} 的 €{max(rev['gucci']):,.0f}M，"
                 f"本季只有它的 {rev['gucci'][-1] / max(rev['gucci']) * 100:.0f}%。</b>"
                 if peak != len(q) - 1 else
                 f"<b>本季 €{rev['gucci'][-1]:,.0f}M 是这条线的峰值。</b>")
    exhibits.append({
        "ref": "EX_GUCCI_Q",
        "kind": "gs_bar",
        "title": gucci_title,
        "xlabels": labels,
        "values": rounded(rev["gucci"], 1),
        "legend": "Gucci 季度收入",
        "yoy": {"name": "可比增速 (RHS)", "values": rounded(gu), "yfmt": "pct0"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "€M", "ylab2": "可比增速", "xstep": LONG_STEP,
        "note": (peak_text +
                 f"可比增速在 2017 年最高到 {signed(max(y2017), 1)}，"
                 + (f"自 {compact_quarter(q[len(q) - streak])} 起每一季为负，" if streak else "")
                 + f"本季从上季的 {signed(prev, 0)} {move} {signed(cur, 0)}。"
                 + census_sentence(st)),
        "src_extra": SOURCE_Q,
    })
    return exhibits


REGION_ZH = [("western_europe", "西欧"), ("north_america", "北美"), ("japan", "日本"),
             ("asia_pacific", "亚太"), ("rest_of_world", "其他地区")]


def gucci_regions_chart(st: dict) -> list[dict]:
    """Gucci's retail growth by region, this quarter against the one before.

    Kering prints the table in every quarter's presentation; the 2026-03-16 segment
    release reprints 2025 on the new grid. Mainland China is not broken out -- it is
    inside Asia-Pacific -- so the page cannot say anything about China in numbers.
    """
    block = retail_regions(st)
    gq, g = block["quarters"], block["gucci"]
    if len(gq) < 2:
        return []
    now, before = len(gq) - 1, len(gq) - 2
    positive = [(key, zh) for key, zh in REGION_ZH if g[key][now] > 0]
    improved = [zh for key, zh in REGION_ZH if g[key][now] > g[key][before]]
    na = g["north_america"]
    turned = trailing_run_start(na, lambda v: v > 0)
    if len(positive) == 1:
        key, zh = positive[0]
        lead = f"{zh} {minus_sign(flat_signed(g[key][now]))} 是唯一为正的地区"
    elif positive:
        lead = f"{joined_words([zh for _, zh in positive])}为正"
    else:
        lead = f"{cn_count(len(REGION_ZH))}个地区都还是负的"
    tail = (f"，{cn_count(len(REGION_ZH))}个地区都比上季好" if len(improved) == len(REGION_ZH)
            else f"，{cn_count(len(improved))}个地区比上季好" if improved else "，没有一个地区比上季好")
    total_now, total_before = g["total"][now], g["total"][before]
    return [{
        "ref": "EX_GUCCI_REGIONS",
        "kind": "grouped_bars",
        "title": "Gucci 零售分地区可比增速：" + lead + tail,
        "xlabels": [zh for _, zh in REGION_ZH] + ["零售合计"],
        "groups": [
            {"name": compact_quarter(gq[before]), "color": "GRAY",
             "values": rounded([g[key][before] for key, _ in REGION_ZH] + [total_before])},
            {"name": compact_quarter(gq[now]), "color": "NAVY",
             "values": rounded([g[key][now] for key, _ in REGION_ZH] + [total_now])},
        ],
        "bar_labels": True,
        "fmt": "pct0", "label_fmt": "pct0", "yfmt": "pct0",
        "ylab": "零售可比增速",
        "note": (f"<b>零售合计从上季的 {minus_sign(flat_signed(total_before))} "
                 f"{'收窄到' if total_before < total_now <= 0 else '变为'} {minus_sign(flat_signed(total_now))}。</b>"
                 + (f"北美在 {compact_quarter(gq[0])} 还是 {minus_sign(flat_signed(na[0]))}，"
                    f"{compact_quarter(gq[turned])} 起转正。" if turned is not None and turned > 0 else "")
                 + "这张表不单列中国大陆，它在亚太里，所以本页没有中国的数字。"
                 "这是直营零售的可比增速，不含批发。"
                 f"新分部口径下本页录入了这张表的{cn_count(len(gq))}个季度，完整序列见核对表。"),
        "src_extra": (f"{doc_label(block['src'][before])} 与 {doc_label(block['src'][now])} 的 Gucci"
                      "「Retail by geography」表；2025 年各季同时见 2026-03-16 新分部重述公告第 4 页。"),
    }]


# ── half-year profit: this half's bridge (section two), the record (four) ────
def half_charts(st: dict, der: dict) -> list[dict]:
    halves = st["halves"]
    hg = st["half_group"]
    gm = der["group_margin"]
    hm = der["house_margin"]
    idx = {h: i for i, h in enumerate(halves)}
    last = len(halves) - 1
    g_peak = max(range(len(halves)), key=lambda i: hm["gucci"][i] or -1)
    grp_peak = max(range(len(halves)), key=lambda i: gm[i] or -1)
    b = der["bridge"]
    block = der["bridge_block"]
    gross = der["gross_rate"]
    basis = hg["recurring_operating_income"]["basis"]
    switches = basis_switches(basis)
    cont_from = switches[0][0]
    gross_cont = [(gross[i], halves[i]) for i in range(cont_from, len(halves)) if gross[i] is not None]
    lowest = min(gross_cont)
    dates = st["balance_dates"]
    nd = st["net_debt_eur_m"]
    i_low = nd.index(min(nd))
    i_high = nd.index(max(nd))
    sl_last = max(i for i, v in enumerate(hm["saint_laurent"]) if v is not None)
    bv_last = max(i for i, v in enumerate(hm["bottega_veneta"]) if v is not None)
    if bv_last != sl_last:
        raise ValueError("Saint Laurent and Bottega Veneta margins stop at different halves; "
                         "the house-margin note says they stop together")

    # ── house margins
    g_top = hm["gucci"][g_peak]
    house_title = (f"半年经常性营业利润率：Gucci 从 {g_top:.1f}%（{halves[g_peak]}）降到 {hm['gucci'][-1]:.1f}%"
                   if g_peak != last else
                   f"半年经常性营业利润率：Gucci {hm['gucci'][-1]:.1f}%，为 {len(halves)} 个半年里最高")
    gap = g_top - hm["saint_laurent"][g_peak]
    at_last_g, at_last_s = hm["gucci"][sl_last], hm["saint_laurent"][sl_last]

    # ── group margin against the same half a year earlier
    year_ago = last - 2
    if year_ago >= 0 and BASIS_FAMILY[basis[year_ago]] == BASIS_FAMILY[basis[last]]:
        against = (f"本半年 {gm[-1]:.1f}% 对 {halves[year_ago]}"
                   f"{' 重述值' if basis[year_ago].startswith('restated') else ''} {gm[year_ago]:.1f}%")
    elif year_ago >= 0:
        against = (f"本半年 {gm[-1]:.1f}%，去年同期 {halves[year_ago]} 为"
                   f"{BASIS_ZH[basis[year_ago]]}、不可直接比")
    else:
        against = f"本半年 {gm[-1]:.1f}%"
    g_min = min(range(len(halves)), key=lambda i: gm[i])
    if g_min == last - 1:
        lowest_text = f"{halves[g_min]} 是 {gm[g_min]:.1f}%，也是这 {len(halves)} 个半年里最低的。"
    elif g_min == last:
        lowest_text = f"本半年也是这 {len(halves)} 个半年里最低的。"
    else:
        lowest_text = f"这 {len(halves)} 个半年里最低的是 {halves[g_min]} 的 {gm[g_min]:.1f}%。"
    explained = [label for _, label in switches] == ["剔除 Puma", "IFRS 16", "剔除 Kering Beauté"]
    if not explained:
        raise ValueError("the group-margin note explains exactly the three known basis switches")

    exhibits = [
        {
            "ref": "EX_HOUSE_MARGIN",
            "kind": "lines",
            "title": house_title,
            "xlabels": halves,
            "series": [
                {"name": "Gucci", "values": rounded(hm["gucci"]), "color": "NAVY"},
                {"name": "Saint Laurent", "values": rounded(hm["saint_laurent"]), "color": "GOLD"},
                {"name": "Bottega Veneta", "values": rounded(hm["bottega_veneta"]), "color": "GREEN"},
            ],
            "fmt": "pct1", "yfmt": "pct0", "label_fmt": "pct1",
            "ylab": "半年经常性营业利润率 D", "end_label": True, "xstep": 2,
            "break_at": idx["H1 2018"], "break_label": "2018 起为 IFRS 16 口径",
            "note": ("<b>这是半年图，不是季度图 —— 公司不按季披露品牌利润。</b>"
                     f"Gucci 在 {halves[g_peak]} 做到 {g_top:.1f}%，比同期 Saint Laurent "
                     f"{'高' if gap >= 0 else '低'} {abs(gap):.1f}pp；"
                     f"到 {halves[sl_last]} Gucci {at_last_g:.1f}%，"
                     f"{'已低于' if at_last_g < at_last_s else '仍高于'} Saint Laurent 的 {at_last_s:.1f}%。"
                     + (f"Saint Laurent 与 Bottega Veneta 自 2026 年起不再披露，线停在 {halves[sl_last]}。"
                        if sl_last != last else "")
                     + "利润率 = 品牌经常性营业利润 ÷ 品牌收入（两季相加），H2 为「全年减上半年」，标 D；"
                     "2018 年两个半年用公司按 IFRS 16 重述的数，与 2019 年起口径一致。"),
            "src_extra": SOURCE_H,
        },
        {
            "ref": "EX_GROUP_MARGIN",
            "kind": "bar_line_dual",
            "title": (f"集团半年经常性营业利润 €{hg['recurring_operating_income']['values'][-1]:,.0f}M、"
                      f"利润率 {gm[-1]:.1f}%，峰值是 {halves[grp_peak]} 的 {gm[grp_peak]:.1f}%"),
            "xlabels": halves,
            "bar": {"name": "半年经常性营业利润", "values": rounded(hg["recurring_operating_income"]["values"], 1),
                    "color": "NAVY"},
            "line": {"name": "半年经常性营业利润率 D (RHS)", "values": rounded(gm), "color": "RED", "yfmt": "pct0"},
            "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
            "ylab": "€M（半年）", "ylab2": "半年利润率", "xstep": 2,
            "break_at": [i for i, _ in switches],
            "break_label": [label for _, label in switches],
            "note": (f"<b>这条线上有{cn_count(len(switches))}处口径切换，每一处都用虚线标出，没有一处被接平。</b>"
                     "2016 年为当时公布的集团口径（含 Puma 等运动与生活方式业务）；2017 年用公司 2018 年按 IFRS 5 "
                     "重述的持续经营口径；2018 年用按 IFRS 16 重述的数；2025 年起剔除 Kering Beauté。"
                     "2024 年下半年无法按剔除 Beauté 的口径算，因为公司没有重述 2024 年上半年的利润。"
                     f"{against}；{lowest_text}"),
            "src_extra": SOURCE_H,
        },
    ]

    # ── the half's margin bridge (only while its block is stamped for this half)
    if b is not None:
        delta = b["to"] - b["from"]
        costs = b["personnel"] + b["other"]
        restated = bool(block.get("prior_restated"))
        if b["gross"] < 0 and delta > 0:
            tail, lead = "被两项费用率抵掉还有余", "<b>利润率的改善全部来自费用，毛利率在往下走。</b>"
        elif b["gross"] < 0:
            tail, lead = "两项费用率没有抵掉", "<b>毛利率在往下走，费用率没能抵掉。</b>"
        elif delta >= b["gross"]:
            tail, lead = f"两项费用率再加 {costs:+.2f}pp", "<b>毛利率与费用率一起改善了利润率。</b>"
        else:
            tail, lead = f"被两项费用率吃掉 {-costs:.2f}pp", "<b>毛利率在改善，费用率吃掉了其中一部分。</b>"
        exhibits.append({
            "ref": "EX_H1_BRIDGE",
            "kind": "bridge_bar",
            "title": f"{half_word(block['period'])}利润率 {delta:+.2f}pp：毛利率 {b['gross']:+.2f}pp，{tail}",
            "xlabels": ["毛利率变动", "人员费用率变动", "其他经常性费用率变动", "经常性营业利润率变动"],
            "stacks": [{"name": "占收入比例的变动（pp）", "color": "NAVY",
                        "values": rounded([b["gross"], b["personnel"], b["other"], None])}],
            "net": {"name": f"{block['period']} 对 {block['compare']}{' 重述' if restated else ''}（pp）",
                    "values": [None, None, None, round(delta, 6)]},
            "fmt": "pp1", "yfmt": "pp1", "label_fmt": "pp1",
            "ylab": "百分点（半年）",
            "note": (lead +
                     f"经常性营业利润率从 {b['from']:.2f}% 到 {b['to']:.2f}%。"
                     "三条腿按损益表逐行算：毛利、人员费用、其他经常性经营收支各自除以收入，"
                     "三项之差相加恰好等于利润率之差 —— 这是恒等式，不是近似。"
                     f"对照是公司在 {release_cn(block['doc'])}里印出的、"
                     + (f"剔除 {block['prior_restated']} 的 {block['compare']} 重述损益表。" if restated
                        else f"{block['compare']} 损益表。")),
            "src_extra": f"两期损益表均取自 {release_cn(block['doc'], formal=True)}。",
        })

    # ── gross margin
    gross_switches = [(i, label) for i, label in switches if BASIS_FAMILY[basis[i]] != "continuing_ifrs16"]
    exhibits.append({
        "ref": "EX_GROSS",
        "kind": "lines",
        "title": (f"半年毛利率 {gross[-1]:.1f}%：持续经营口径（{halves[cont_from]} 起）"
                  f"{'以来最低' if lowest[1] == halves[-1] else '低点是 ' + lowest[1]}"),
        "xlabels": halves,
        "series": [{"name": "半年毛利率 D", "values": rounded(gross), "color": "NAVY"}],
        "fmt": "pct1", "yfmt": "pct0", "label_fmt": "pct1",
        "ylab": "半年毛利率", "end_label": True, "xstep": 2,
        "break_at": [i for i, _ in gross_switches],
        "break_label": [label for _, label in gross_switches],
        "note": (f"2016 年两个半年含 Puma，毛利率只有 {gross[0]:.1f}% 与 {gross[1]:.1f}%，"
                 "与之后不可比，所以用虚线隔开。"
                 f"持续经营口径下毛利率在 {max(gross_cont)[1]} 最高、为 {max(gross_cont)[0]:.1f}%，"
                 f"本半年 {gross[-1]:.1f}%。"
                 "毛利率不受 IFRS 16 影响（租赁费用在毛利以下），所以 2018 年直接用公布值。"
                 "H2 为「全年毛利 − 上半年毛利」÷「全年收入 − 上半年收入」，标 D。"),
        "src_extra": SOURCE_H,
    })

    # ── net debt
    story = stamped_block(st, "net_debt_story", halves[-1])
    if i_low < i_high < len(nd) - 1 and nd[-1] < nd[i_high]:
        nd_title = (f"净负债 {euro_m(nd[-1])}：{dates[i_low][:7]} 的 {euro_m(nd[i_low])} 涨到 "
                    f"{dates[i_high][:7]} 的 {euro_m(nd[i_high])} 再降回来")
    elif i_low < i_high:
        nd_title = f"净负债 {euro_m(nd[-1])}：从 {dates[i_low][:7]} 的 {euro_m(nd[i_low])} 涨到序列最高"
    else:
        nd_title = (f"净负债 {euro_m(nd[-1])}：从 {dates[i_high][:7]} 的 {euro_m(nd[i_high])} "
                    f"降到 {dates[i_low][:7]} 的 {euro_m(nd[i_low])}")
    climb = NET_DEBT_CLIMB[2] if (dates[i_low], dates[i_high]) == NET_DEBT_CLIMB[:2] else ""
    change = nd[-2] - nd[-1]
    exhibits.append({
        "ref": "EX_NET_DEBT",
        "kind": "bars_labeled",
        "title": nd_title,
        "xlabels": dates,
        "values": rounded(nd, 1),
        "label_fmt": "f0c", "fmt": "f0c", "yfmt": "f0c",
        "ylab": "€M（期末）", "xstep": 2,
        "note": ("<b>净负债按公司定义不含租赁负债，整条序列口径没有变过。</b>"
                 + (f"从 {dates[i_low]} 的 {euro_m(nd[i_low])} 涨到 {dates[i_high]} 的 {euro_m(nd[i_high])}，{climb}"
                    if i_low < i_high else "")
                 + f"本期末 {euro_m(nd[-1])}，比 {year_end_label(dates[-2])}{'少' if change >= 0 else '多'} "
                 f"{euro_m(abs(change))}"
                 + (f"；{story['note']}" if story else "。")),
        "src_extra": "期末净负债取自各期半年度财务报告与全年业绩新闻稿的净负债表（精确值）。",
    })
    if min(nd) < 0:
        # `bars_labeled` draws from a zero floor; a period of net cash would be painted
        # below the plot. The grouped form carries negatives with the same labels.
        chart = exhibits[-1]
        values = chart.pop("values")
        chart.update(kind="grouped_bars", bar_labels=True,
                     groups=[{"name": "期末净负债（负值为净现金）", "color": "NAVY", "values": values}])
    return exhibits


# ── section four: the long record ────────────────────────────────────────────
def long_charts(st: dict, der: dict) -> list[dict]:
    q = st["long_quarters"]
    rev = st["quarterly_revenue_eur_m"]
    comp = st["quarterly_comparable_pct"]
    end = max(i for i, v in enumerate(rev["saint_laurent"]) if v is not None) + 1
    labels = [compact_quarter(p) for p in q[:end]]
    share = der["gucci_share"][:end]
    peak = max(range(end), key=lambda i: share[i])
    break_2022 = q.index("2022Q1")
    g, sl, bv = comp["gucci"], comp["saint_laurent"], comp["bottega_veneta"]
    run = trailing_run_start([None if sl[i] is None or g[i] is None else sl[i] - g[i] for i in range(end)],
                             lambda d: d > 0)
    stopped = end < len(q)
    stop_text = f"{quarter_cn(q[end - 1])}"
    y2017 = [v for p, v in zip(q, g) if p.startswith("2017")]
    bv2016 = [v for p, v in zip(q, bv) if p.startswith("2016")]
    bv_recent = [v for v in bv[:end][-12:] if v is not None]
    bv_text = ("2016 年四季全负" if bv2016 and all(v < 0 for v in bv2016) else "")
    if bv_recent and sum(1 for v in bv_recent if v > 0) * 2 > len(bv_recent):
        bv_text += ("、" if bv_text else "") + "近年多为正"
    same_extremes = all((q[min(range(end), key=lambda i: s[i] if s[i] is not None else 1e9)],
                         q[max(range(end), key=lambda i: s[i] if s[i] is not None else -1e9)])
                        == ("2020Q2", "2021Q2") for s in (g, sl, bv))

    return [
        {
            "ref": "EX_HOUSES",
            "kind": "stacked_dual",
            "title": (f"四条品牌线的季度收入：Gucci 占比从 {labels[peak]} 的 {share[peak]:.1f}% "
                      f"降到 {labels[-1]} 的 {share[-1]:.1f}%" if peak != end - 1 else
                      f"四条品牌线的季度收入：Gucci 占比 {share[-1]:.1f}%，为这条线的最高点"),
            "xlabels": labels,
            "stacks": [
                {"name": "Gucci", "color": "NAVY", "values": rounded(rev["gucci"][:end], 1)},
                {"name": "Saint Laurent", "color": "GOLD", "values": rounded(rev["saint_laurent"][:end], 1)},
                {"name": "Bottega Veneta", "color": "GREEN", "values": rounded(rev["bottega_veneta"][:end], 1)},
                {"name": "其他品牌", "color": "GRAY", "values": rounded(rev["other_houses"][:end], 1)},
            ],
            "line": {"name": "Gucci 占四条品牌线合计 D (RHS)", "color": "RED", "values": rounded(share),
                     "yfmt": "pct1", "ymax": 100},
            "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
            "ylab": "€M", "ylab2": "Gucci 占比", "xstep": LONG_STEP,
            "break_at": break_2022, "break_label": "其他品牌 2022 年起列报方式变更",
            "note": ((f"<b>这张图停在 {stop_text}：{q[end][:4]} 年起 Saint Laurent、Bottega Veneta 与「其他品牌」"
                      "不再单独披露。</b>" if stopped else "")
                     + "「其他品牌」在 2018 年一季度以前用公司 2018 年 6 月按 IFRS 5 重述的口径"
                     "（剔除 Stella McCartney 与 Christopher Kane），与之后连续；"
                     "2022 年一季度起公司把 2021 年「其他品牌」每季上调约 €4–6M 重新列报、未说明原因，"
                     "本页保留每季首次公布值，并在那一处画虚线。"
                     "占比的分母是四条品牌线之和，不是集团收入 —— 集团收入里还有眼镜、集团其他与内部抵销，"
                     "而且口径换过三次。"),
            "src_extra": SOURCE_Q + " 2016–2017 年「其他品牌」取自按 IFRS 5 重述的关键指标（2018-06）。",
        },
        {
            "ref": "EX_HOUSE_COMP",
            "kind": "lines",
            "title": ("三个品牌的季度可比增速："
                      + (f"Saint Laurent 从 {compact_quarter(q[run])} 起每一季都跑赢 Gucci"
                         if run is not None and run < end - 1 else "Gucci、Saint Laurent 与 Bottega Veneta")),
            "xlabels": [compact_quarter(p) for p in q],
            "series": [
                {"name": "Gucci", "values": rounded(comp["gucci"]), "color": "NAVY"},
                {"name": "Saint Laurent", "values": rounded(comp["saint_laurent"]), "color": "GOLD"},
                {"name": "Bottega Veneta", "values": rounded(comp["bottega_veneta"]), "color": "GREEN"},
            ],
            "fmt": "pct0", "yfmt": "pct0", "label_fmt": "pct0",
            "ylab": "可比增速", "zero_line": True, "end_label": True, "xstep": LONG_STEP,
            "note": ("可比增速是公司口径，剔除汇率与合并范围变化，是三条品牌线里最能连续读的一种量。"
                     f"Gucci 2017 年{cn_count(len(y2017))}个季度在 {min(y2017):+.1f}% 到 {max(y2017):+.1f}% 之间"
                     + (f"；Bottega Veneta 反过来，{bv_text}。" if bv_text else "。")
                     + (f"Saint Laurent 与 Bottega Veneta 的线停在 {stop_text}，"
                        f"因为 {q[end][:4]} 年起不再单独披露。" if stopped else "")
                     + ("2020 年二季度与 2021 年二季度的两个极值是门店关闭与低基数，三个品牌同时出现。"
                        if same_extremes else "")),
            "src_extra": SOURCE_Q,
        },
    ]


# ── section three: next-quarter tracking ─────────────────────────────────────
def measured(st: dict, der: dict) -> dict:
    """What the page can measure a threshold against, keyed by the block's `measure`.

    Kering prints its recurring operating margin to one decimal, and that printed
    figure is what the threshold is compared with; its gross margin it does not
    print at all, so that one is the page's own arithmetic, unrounded.
    """
    comp = st["quarterly_comparable_pct"]
    grid = st["new_grid"]["comparable_pct"]
    gucci_retail = retail_regions(st)["gucci"]
    return {
        "group_comparable": comp["group_first_published"][-1],
        "gucci_comparable": comp["gucci"][-1],
        "gucci_retail": gucci_retail["total"][-1],
        "gucci_na_retail": gucci_retail["north_america"][-1],
        "jewelry_comparable": grid["jewelry"][-1],
        "eyewear_comparable": grid["eyewear"][-1],
        "half_gross_margin": der["gross_rate"][-1],
        "half_recurring_margin": float(round_half_up(der["group_margin"][-1], 1)),
        "net_debt": st["net_debt_eur_m"][-1],
    }


def threshold_entries(st: dict, der: dict) -> list[dict]:
    kpi = stamped_block(st, "next_kpi", display_period(st["long_quarters"][-1]))
    if kpi is None:
        raise ValueError("series block `next_kpi` is missing: the tracking section has no thresholds")
    values = measured(st, der)
    entries = []
    for entry in kpi["entries"]:
        if entry["measure"] not in values:
            raise ValueError(f"series block `next_kpi` asks for {entry['measure']!r}, which this page "
                             "does not know how to measure")
        entries.append({"metric": entry["metric"], "measure": entry["measure"], "direction": entry["direction"],
                        "threshold": entry["threshold"], "unit": entry["unit"],
                        "current": values[entry["measure"]], "why": entry["why"]})
    return entries


def outlook_sentence(st: dict) -> str:
    outlook = stamped_block(st, "outlook", display_period(st["long_quarters"][-1]))
    if outlook is None:
        return ""
    if outlook.get("has_figures"):
        return f"<b>{release_cn(outlook['doc'])}的展望段落</b>写的是「{outlook['quote']}」；"
    return f"<b>{release_cn(outlook['doc'])}的展望段落里没有数字</b>，只写「{outlook['quote']}」；"


def routine_charts(st: dict, der: dict) -> tuple[list[dict], list[dict]]:
    """The next quarter's thresholds (section three) and the Capital Markets Day
    target drawn on the long half-year margin line (section four)."""
    entries = threshold_entries(st, der)
    breached = [e["metric"] for e in entries if headroom(e["direction"], e["threshold"], e["current"]) < 0]
    gm_now = der["group_margin"][-1]
    line = der["cmd_margin_line"]
    above = der["halves_above_cmd"]
    return [
        headroom_exhibit(
            f"下季跟踪阈值：{len(entries)} 条里 {len(entries) - len(breached)} 条在安全侧",
            entries, "current",
            ("阈值是本地研究设定，不是公司指引。正值代表仍在安全侧。"
             + outlook_sentence(st) +
             "资本市场日给的是中期目标（利润率为 FY2025 的两倍以上），"
             "画在第四节。原始单位的阈值与当前值见核对表。"),
            "阈值与理由见核对表；当前值取自本页已列示的公司披露值与透明自算。",
        ),
    ], [
        {"ref": "EX_CMD_LINE"} | threshold_exhibit(
            f"半年利润率对资本市场日的中期目标：FY2025 的两倍是 {line:.1f}%",
            st["halves"], rounded(der["group_margin"]), round(line, 2),
            fmt="pct1", ylab="半年经常性营业利润率 D",
            actual_name="半年经常性营业利润率 D",
            threshold_name=f"FY2025 利润率 × 2（{line:.1f}%）",
            note=("2026-04-16 资本市场日第 121 页：「More than double FY 2025 recurring operating margin percentage」，"
                  "期限写的是「MID-TERM」，没有年份。"
                  f"FY2025 全年利润率 {der['fy25_margin']:.1f}%（剔除 Kering Beauté），两倍是 "
                  f"{line:.1f}%；本半年 {gm_now:.1f}%，"
                  + (f"差 {line - gm_now:.1f}pp。" if gm_now < line else f"已高于这条线 {gm_now - line:.1f}pp。")
                  + (f"{len(st['halves'])} 个半年里有 {above} 个高于这条线，最近一次是 "
                     f"{der['last_above_cmd']} —— 目标不是没到过的水平，而是回到过去的水平。" if above else
                     f"{len(st['halves'])} 个半年里没有一个高于这条线。")
                  + "口径切换见 Exhibit {EX_GROUP_MARGIN}。"),
            src_extra=SOURCE_H + " 目标取自 2026 资本市场日演示材料。",
            xstep=2,
        ),
    ]


BASIS_ZH = {"published_incl_sport_lifestyle": "公布值（含运动与生活方式）",
            "continuing_restated_ifrs5": "IFRS 5 重述的持续经营口径",
            "ifrs16_restated": "IFRS 16 重述", "published": "公布值",
            "published_incl_beaute": "公布值（含 Kering Beauté）",
            "restated_ex_beaute": "重述（剔除 Kering Beauté）", "published_new_grid": "公布值（新分部口径）"}


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    comp = staging["quarterly_comparable_pct"]
    half = staging["half_group"]
    return [minus_sign(f"本季可比 {comp['group_first_published'][-1]:+.0f}%"),
            minus_sign(f"Gucci 可比 {comp['gucci'][-1]:+.0f}%"),
            "半年利润率 "
            f"{half['recurring_operating_income']['values'][-1] / half['revenue']['values'][-1] * 100:.1f}%"]


def build_payload(st: dict) -> dict:
    check_half_matches_quarter(st)
    check_release_in_sources(st)
    der = derived(st)
    # Four sections, TSM's order: what last quarter set and this quarter settles,
    # this quarter's findings, what the next quarter is tracked against, and the
    # long record. The half-year profit charts are split by what they say: the
    # half that ends with this quarter has a finding of its own (the margin
    # bridge, stamped with the half), the twenty-one-half lines are the record.
    story_ex = settled_story_charts(st, der)
    said_ex = settled_charts(st, der)
    quarter_ex = quarter_charts(st, der)
    regions_ex = gucci_regions_chart(st)
    half = {ex["ref"]: ex for ex in half_charts(st, der)}
    half_now = [half.pop("EX_H1_BRIDGE")] if "EX_H1_BRIDGE" in half else []
    long_ex = long_charts(st, der)
    next_ex, target_ex = routine_charts(st, der)
    # (a) last quarter's questions, (b) its thresholds, (c) the company's own targets
    settled_group = story_ex + said_ex
    highlight_group = quarter_ex + regions_ex + half_now
    next_group = next_ex
    # the long record: the brand lines by quarter, then profitability by half
    # (brands, group, the mid-term target on the group line, gross margin), then
    # the balance sheet
    routine_group = (long_ex + [half.pop("EX_HOUSE_MARGIN"), half.pop("EX_GROUP_MARGIN")]
                     + target_ex + [half.pop("EX_GROSS"), half.pop("EX_NET_DEBT")])
    if half:
        raise ValueError(f"half-year charts {sorted(half)} have no section")
    exhibits = number_exhibits(settled_group + highlight_group + next_group + routine_group)
    resolve_exhibit_refs(exhibits)

    q = st["long_quarters"]
    rev = st["quarterly_revenue_eur_m"]
    comp = st["quarterly_comparable_pct"]
    halves = st["halves"]
    hg = st["half_group"]
    hh = st["half_house"]
    grid = st["new_grid"]
    period = display_period(q[-1])
    latest = latest_block(st, period=period, full_label=halves[-1])

    fmt = lambda v, d=1: "—" if v is None else f"{v:,.{d}f}"
    pct = lambda v: "—" if v is None else f"{v:+g}%"
    q_rows = [[p] + [fmt(rev[h][i]) for h in ("gucci", "saint_laurent", "bottega_veneta", "other_houses")]
              + [pct(comp[h][i]) for h in ("gucci", "saint_laurent", "bottega_veneta", "other_houses")]
              + [fmt(rev["group_first_published"][i]), pct(comp["group_first_published"][i])]
              for i, p in enumerate(q)]
    perim_rows = ([[x["period"], fmt(x["first_published"]), fmt(x["ifrs5_june_2018"]), fmt(x["proforma_april_2018"]),
                    "本页采用 IFRS 5（2018-06）口径"] for x in st["other_houses_perimeter_2016_2018"]]
                  + [[x["period"], fmt(x["first_published"]), "—", "—",
                      f"2022 年重列为 {fmt(x['represented_2022'])}；本页保留首次公布值"]
                     for x in st["other_houses_representation_2021"]])
    grid_lines = [("时装与皮具", "fashion_leather_goods"), ("其中 Gucci", "gucci"), ("珠宝", "jewelry"),
                  ("眼镜", "eyewear"), ("集团其他", "corporate_and_other"), ("内部抵销", "eliminations"),
                  ("集团合计", "total")]
    grid_rows = [[compact_quarter(p)] + [f"{grid['revenue_eur_m'][k][i]:,}" for _, k in grid_lines]
                 + [pct(grid["comparable_pct"][k][i]) for _, k in grid_lines[:4]] + [pct(grid["comparable_pct"]["total"][i])]
                 for i, p in enumerate(grid["quarters"])]
    half_rows = [[h, "公司印出" if hg["revenue"]["flag"][i] == "printed" else "全年减上半年 D",
                  BASIS_ZH[hg["revenue"]["basis"][i]],
                  fmt(hg["revenue"]["values"][i]), fmt(hg["gross_margin"]["values"][i]),
                  fmt(hg["recurring_operating_income"]["values"][i]),
                  fmt(der["gross_rate"][i], 2) + "%", fmt(der["group_margin"][i], 2) + "%"]
                 for i, h in enumerate(halves)]
    house_rows = []
    for i, h in enumerate(halves):
        row = [h]
        for k in ("gucci", "saint_laurent", "bottega_veneta"):
            r = hh[k]["roi_eur_m"][i] if i < len(hh[k]["roi_eur_m"]) else None
            m = der["house_margin"][k][i]
            row += [fmt(r), "—" if m is None else f"{m:.2f}%"]
        house_rows.append(row)
    nd_rows = [[d, f"{v:,.1f}", doc_label(s)] for d, v, s in zip(st["balance_dates"], st["net_debt_eur_m"],
                                                                 st["net_debt_src"])]
    g = st["guidance_record"]
    s = der["settle"]
    h1_guide, h2_guide, fy_guide = g["roi_2024"]
    h1_inside = h1_guide["low"] <= s["h1"] <= h1_guide["high"]
    gt = gucci_target_facts(st, der)
    sl_target = g["medium_term_2019"][1]
    sl_ann = st["annual_house"]["saint_laurent"]
    sl_m = der["ann_margin"]["saint_laurent"]
    sl_tiers = list(zip(sl_target["revenue_targets_eur_m"], sl_target["margin_targets_pct"]))
    sl_firsts = [next((i for i, v in enumerate(sl_ann["revenue_eur_m"]) if v >= r), None) for r, _ in sl_tiers]
    sl_same_year = all(i is not None and sl_m[i] > m for i, (_, m) in zip(sl_firsts, sl_tiers))
    guide_rows = [
        ["2024 上半年经常性营业利润", h1_guide["release_date"], h1_guide["quote"],
         f"{minus_sign(str(h1_guide['high']))}% 至 {minus_sign(str(h1_guide['low']))}%", f"{s['h1']:.1f}%",
         "兑现" if h1_inside else "未兑现"],
        ["2024 下半年经常性营业利润", h2_guide["release_date"], h2_guide["quote"],
         f"约 {minus_sign(str(h2_guide['point']))}%", f"{s['h2']:.1f}%", APPROX_VERDICT["h2_2024"]],
        ["2024 全年经常性营业利润", fy_guide["release_date"], fy_guide["quote"],
         f"约 €{fy_guide['point_eur_m']:,}M", f"€{s['fy_eur']:,.0f}M", APPROX_VERDICT["fy_2024"]],
        ["Gucci 中期", gt["target"]["release_date"], gt["target"]["quote"],
         f"收入 €{gt['rev_goal'] / 1000:.0f}B / 利润率 {gt['margin_goal']}%+",
         "分别在不同年份达到，从未同年" if gt["rev_hit"] and gt["m_hit"] and not gt["both"]
         else ("同年达到" if gt["both"] else "未达到"),
         "未同时兑现" if not gt["both"] else "兑现"],
        ["Saint Laurent 中长期", sl_target["release_date"], sl_target["quote"],
         "，再 ".join(f"€{r / 1000:.0f}B 与 {m}%" for r, m in sl_tiers),
         f"{cn_count(len(sl_tiers))}级都与利润率同年达到" if sl_same_year else "未全部与利润率同年达到",
         "兑现" if sl_same_year else "未兑现"],
    ] + [["集团中期（资本市场日）", c["release_date"], c["quote"], "—", "尚未到期", "待结算"] for c in g["cmd_2026"]]

    entries = threshold_entries(st, der)
    kpi = threshold_table(0, "下季跟踪阈值与当前值（原始单位）", entries, "current", "当前值")
    kpi["headers"] = kpi["headers"] + ["为什么是这条线"]
    kpi["rows"] = [row + [e["why"]] for row, e in zip(kpi["rows"], entries)]

    story_tables = []
    closure = followup_items(st)
    if closure is not None:
        story_tables.append({
            "title": f"上季{cn_count(len(closure['items']))}条待验证问题的闭环（本季本地分析稿第 0 节原话）",
            "headers": ["#", "上季问题", "本季分析稿的判定（原话）", "本页归类"],
            "rows": [[str(i), item["question"], item["verdict"], item["label"]]
                     for i, item in enumerate(closure["items"], 1)]})
    prior = prior_entries(st, der)
    if prior is not None:
        block, prior_list = prior

        def outcome(e: dict) -> str:
            if e["gate"] == BULL:
                return "达到" if on_good_side(e) else "没够着"
            return "没触发" if on_good_side(e) else "触发"

        story_tables.append({
            "title": "上季量化阈值的结算（原始单位）",
            "headers": ["阈值", "本季实际", "结果", "余量 D", "原话（上季本地分析稿第 8 节）", "出自", "实际值出处"],
            "rows": [[e["label"], value_text(e, e["actual"]), outcome(e),
                      f"{headroom(e['direction'], e['threshold'], e['actual']):+.1f}%", e["quote"],
                      "估值与隐性指引版" if "估值" in e["report"] else "普通版",
                      e.get("source", "本页序列（见其余核对表）")]
                     for e in prior_list]})
        if block.get("unsettled"):
            story_tables.append({
                "title": "上季阈值里本季无法结算的条目",
                "headers": ["阈值", "出自", "为什么结不了"],
                "rows": [[u["item"], "估值与隐性指引版" if "估值" in u["report"] else "普通版", u["why"]]
                         for u in block["unsettled"]]})
    regions = retail_regions(st)
    region_rows = [[compact_quarter(p)] + [minus_sign(flat_signed(regions["gucci"][key][i])) for key, _ in REGION_ZH]
                   + [minus_sign(flat_signed(regions["gucci"]["total"][i])), doc_label(regions["src"][i])]
                   for i, p in enumerate(regions["quarters"])]

    first_table = exhibits[-1]["n"] + 1
    tables = story_tables + [
        {"title": f"{cn_count(len(q))}季品牌线收入（€M）与可比增速（当季首次公布）",
         "headers": ["季度", "Gucci", "Saint Laurent", "Bottega Veneta", "其他品牌",
                     "Gucci 可比", "SL 可比", "BV 可比", "其他品牌可比", "集团收入（首次公布）", "集团可比"],
         "rows": q_rows},
        {"title": "「其他品牌」的三种口径：2016–2018 年的合并范围，与 2021 年的重新列报",
         "headers": ["季度", "首次公布", "IFRS 5 重述（2018-06）", "备考（2018-04）", "本页取法"],
         "rows": perim_rows},
        {"title": f"新分部口径的{cn_count(len(grid['quarters']))}个季度（€M 与可比增速）",
         "headers": ["季度"] + [zh for zh, _ in grid_lines] + ["时装与皮具可比", "Gucci 可比", "珠宝可比", "眼镜可比", "集团可比"],
         "rows": grid_rows},
        {"title": f"Gucci 直营零售分地区可比增速（新分部口径的{cn_count(len(regions['quarters']))}个季度）",
         "headers": ["季度"] + [zh for _, zh in REGION_ZH] + ["零售合计", "取自"],
         "rows": region_rows},
        {"title": f"{cn_count(len(halves))}个半年的集团收入、毛利与经常性营业利润（€M）；H2 为全年减上半年",
         "headers": ["半年", "来源", "口径", "收入", "毛利", "经常性营业利润", "毛利率 D", "利润率 D"],
         "rows": half_rows},
        {"title": "品牌半年经常性营业利润（€M）与利润率（本页重算）",
         "headers": ["半年", "Gucci 利润", "Gucci 利润率 D", "SL 利润", "SL 利润率 D", "BV 利润", "BV 利润率 D"],
         "rows": house_rows},
        {"title": "期末净负债（€M，不含租赁负债）与取值文件",
         "headers": ["日期", "净负债", "取自"], "rows": nd_rows},
        {"title": "公司给过的数字目标与结算（原话逐字）",
         "headers": ["主题", "发布日期", "原话", "所述", "实际", "判词"], "rows": guide_rows},
        kpi,
        ai_capex_cycle_table(0),
    ]
    for offset, table in enumerate(tables):
        table["n"] = first_table + offset
        # keep key order n, title, headers, rows
    tables = [{"n": t["n"], "title": t["title"], "headers": t["headers"], "rows": t["rows"]} for t in tables]

    gm = der["group_margin"]
    b = der["bridge"]
    block = der["bridge_block"]
    nd = st["net_debt_eur_m"]
    story = stamped_block(st, "net_debt_story", halves[-1])
    turn = group_turn(st, der)
    streak = der["gucci_neg_streak"]
    gu = comp["gucci"]

    # ── headline
    headline = (f"本季集团可比增速 {flat_signed(turn['cur'])}，Gucci {flat_signed(gu[-1])}"
                + (f"、连续 {streak} 个季度为负；" if streak else "；")
                + f"{half_word(halves[-1])}利润率 {gm[-1]:.1f}%")
    if b is not None:
        delta = b["to"] - b["from"]
        headline += (f"，比{'重述后的' if block.get('prior_restated') else ''}上年同期"
                     f"{'高' if delta >= 0 else '低'} {abs(delta):.2f}pp")
        if delta > 0 and b["gross"] < 0:
            headline += f"，但毛利率低了 {-b['gross']:.2f}pp —— 改善来自费用率，不是来自毛利"
        else:
            headline += f"，毛利率{'高' if b['gross'] >= 0 else '低'}了 {abs(b['gross']):.2f}pp"
    headline += (f"；净负债{'降到' if nd[-1] < nd[-2] else '升到'} {euro_m(nd[-1])}"
                 + (f"，{story['headline']}" if story else "") + "。")

    # ── brief
    br = quarter_bridge(st)
    articles = []
    if turn["cur"] > 0 and gu[-1] < 0:
        rev_bold = "集团转正了，Gucci 还没有" if turn["first_again"] else "集团为正，Gucci 仍为负"
    elif turn["cur"] > 0:
        rev_bold = "集团与 Gucci 都为正"
    elif gu[-1] < 0:
        rev_bold = "集团与 Gucci 都还没有转正"
    else:
        rev_bold = "Gucci 为正，集团没有"
    if br is not None:
        _, number = quarter_parts(q[-1])
        net = br["net"]
        flg = br["deltas"][0][1]
        rev_text = (f"Q{number} 报告口径{'多出' if net >= 0 else '少了'} €{abs(net):,}M："
                    f"珠宝与眼镜合计 {'−' if br['jewelry_eyewear'] < 0 else '+'}€{abs(br['jewelry_eyewear']):,}M，"
                    f"时装与皮具 {'−' if flg < 0 else '+'}€{abs(flg):,}M。")
    else:
        rev_text = f"集团可比 {flat_signed(turn['cur'])}，Gucci 可比 {flat_signed(gu[-1])}。"
    articles.append(f'<article><span>收入</span><b>{rev_bold}</b><p>{rev_text}</p></article>')
    if b is not None:
        delta = b["to"] - b["from"]
        profit_bold = ("利润率改善来自费用，毛利率在下降" if delta > 0 and b["gross"] < 0 else
                       "利润率与毛利率都在改善" if delta > 0 else
                       "利润率与毛利率都在下降" if b["gross"] < 0 else
                       "毛利率改善，费用率吃掉了它")
        articles.append('<article><span>利润</span>'
                        f'<b>{profit_bold}</b>'
                        f'<p>毛利率 {b["gross"]:+.2f}pp，人员与其他费用率合计 {b["personnel"] + b["other"]:+.2f}pp。</p></article>')
    t = targets_2022(st, der)
    t_gucci_22, t_gucci_now = t["items"][0][1], t["items"][0][2]
    articles.append('<article><span>兑现</span><b>说得最具体的一次没兑现</b>'
                    f'<p>2024 年下半年指引约 {minus_sign(str(h2_guide["point"]))}%，实际 {s["h2"]:.1f}%；'
                    f'Gucci 的 €{gt["rev_goal"] / 1000:.0f}B 与 {gt["margin_goal"]}% '
                    + ("从未同年到达" if not gt["both"] else "同年到达过")
                    + f'，2022 年再提的 €15B 更{"远" if t_gucci_now < t_gucci_22 else "近"}。</p></article>')
    brief = (f'<h4>本季{cn_count(len(articles))}条主线</h4><div class="takeaway-grid">'
             + "".join(articles) + '</div>')

    # ── sections, notes
    end = max(i for i, v in enumerate(rev["saint_laurent"]) if v is not None) + 1
    if turn["first_again"]:
        s2_lead = "集团回到增长，增长来自哪里。"
    elif turn["cur"] > 0:
        s2_lead = "集团在增长，增长来自哪里。"
    else:
        s2_lead = "集团与 Gucci 都在哪里。"
    audit = stamped_block(st, "corpus_audit", period)
    exceptions = st["reprint_exceptions"]
    reprint_notes = []
    for x in exceptions:
        doc_year = re.match(r"KER_(?:H1_|FY_)?(\d{4})", x["doc"]).group(1)
        reprint_notes.append(
            f"{HOUSE_ZH[x['line']]} {quarter_cn(x['period'])}收入首次公布为 {x['first_published']:g} 百万欧元，"
            f"在 {doc_year} 年的重新列报表里印作 {x['reprinted']:g}；"
            + ("文件没有说明这是凑整还是重述。" if not x.get("explained") else "")
            + "本页保留首次公布值。")
    if reprint_notes and audit is not None and audit.get("reprint_census"):
        reprint_notes[-1] += ("在本页读过的全部文件里，这是三条品牌线唯一一处与首次公布不同的重印。"
                              if len(exceptions) == 1 else
                              f"在本页读过的全部文件里，三条品牌线与首次公布不同的重印共{cn_count(len(exceptions))}处。")

    looks = []
    if closure is not None:
        looks.append(f"上季本地分析稿留下的{cn_count(len(closure['items']))}条问题闭环到哪一步")
    if prior is not None:
        looks.append(f"上季分析稿第 8 节里能用本季公司数字结算的{cn_count(len(prior[1]))}条阈值落在哪一侧")
    s1_description = (("先看" + "，再看".join(looks) + "；最后结算 " if looks else "")
                      + "Kering 自己给过、能在原口径上核的数字目标：2024 年三次利润指引、2019 年与 2022 年的品牌"
                      "中期目标（其余目标逐条列在核对表里；资本市场日的中期目标尚未到期，画在第四节）。")
    prior_bar = next((ex for ex in settled_group if ex.get("ref") == "EX_PRIOR_HEADROOM"), None)
    next_bar = next((ex for ex in next_group if ex["kind"] == "diverging_bars"), None)
    threshold_note = ((f"Exhibit {prior_bar['n']} 与 Exhibit {next_bar['n']} 的阈值是本地研究设定"
                       "（上季与本季本地分析稿第 8 节），" if prior_bar and next_bar else
                       "第三节的阈值是本地研究设定，")
                      + "不是公司指引，也不构成评级或投资建议；「距阈值余量」统一为正值代表安全侧。")

    notes = [
        "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，支撑表格收在核对抽屉里。",
        "Kering 一年发四次收入、只发两次利润。第一与第三季度只发收入公告；损益表、品牌经常性营业利润、现金流与资产负债表只在半年度与全年披露。所以收入用季度轴、利润用半年轴，两条轴各自独立，本页不做任何按季摊平。",
        "Kering 不是 SEC 报告发行人：EDGAR 上 CIK 1445465 名下只有 ADR 存托登记文件（F-6EF、F-6 POS、424B3），没有任何财务报表。本页全部数据取自 kering.com 发布的文件。",
    ]
    if audit is not None and audit.get("double_read"):
        notes.append("本页用到的每一份文件都由两个互不知情的转录者各读一遍，逐格比对，所有不一致的格子回到原页裁定；再按期间把同一季度在不同文件里的全部读数排在一起，凡是与首次公布不同的，都能对上一次有记录的口径变更。")
    notes += [
        "季度收入与可比增速一律取当季首次公布它的那份公告：第二季度取半年度业绩新闻稿附表，第四季度取全年业绩新闻稿附表。",
        "口径变更一：2018 年一季度起 Puma、Volcom、Stella McCartney（后来加上 Christopher Kane）转入终止经营。本页「其他品牌」在 2018 年以前采用公司 2018 年 6 月按 IFRS 5 重述的关键指标，与 2018 年全年新闻稿的比较数一致；2018 年 4 月的备考文件口径略不同（仍含 Christopher Kane），两套数并列在核对表里。",
        "口径变更二：2019 年起适用 IFRS 16。公司把 2018 年按 IFRS 16 重述过，本页半年利润图 2018 年起用 IFRS 16 口径；2016–2017 年为 IAS 17 口径，图上画了虚线。毛利率不受 IFRS 16 影响，2018 年直接用公布值。",
        "口径变更三：2022 年一季度起「集团其他」改为「Kering Eyewear 与集团」并单列内部抵销，同时 2021 年「其他品牌」每季被重新列报高出约 €4–6M，公司没有说明原因。本页保留 2021 年各季首次公布值，重列值并列在核对表第二张。",
        "口径变更四：2025 年全年起 Kering Beauté 转入终止经营，2024 年与 2025 年前三季收入重述；2026 年一季度起采用新分部（时装与皮具、珠宝、眼镜、集团其他），公司只把 2025 年按新分部重述。2024 年上半年利润没有剔除 Beauté 的重述，所以 2024 年两个半年保持含 Beauté 的公布值。",
    ] + reprint_notes + [
        "H2 各行由「全年减上半年」得出并标 D；半年品牌收入取当季首次公布的两个季度相加，与公司印出的半年表逐一核对过。",
        "2024 年下半年与全年利润指引都附脚注「Based on the scope of consolidation and exchange rates」（当时的合并范围与汇率）；公司从未按该口径公布实际值，本页用报告口径结算，并在图注里写明。",
        "净负债按公司定义不含租赁负债，整条序列口径一致；公告正文只印到 0.1 十亿欧元，本页取半年度财务报告与全年新闻稿净负债表里的精确值。",
        threshold_note,
        "本页只发布公司披露值与可复算的简单派生值；D 标记代表 Derived / 自算。电话会记录仅作背景，不作为本页任何数字的来源。",
        "本页已知未接入：品牌的分地区收入（公司只给零散的文字增速）、按季的零售与批发拆分、门店数（两份文件对同一时点的门店数不一致，见各年财务文件）、2026 年起 Saint Laurent 与 Bottega Veneta 的任何数字（公司不再披露）。",
    ]

    return {
        "schema_version": "quarterly-dashboard/ker-v1",
        "page": {"slug": "ker", "language": "zh-CN"},
        "company": {"ticker": "KER.PA", "name": "Kering SA", "group": "luxury_brands",
                    "accounting_standard": "IFRS"},
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · KER.PA",
        "title": f"Kering（KER.PA）：{period} / {halves[-1]} 季报仪表盘",
        "subtitle": (f"截至 {latest['period_end']} · 发布 {latest['release_date']} · IFRS 合并 · 全部以欧元列示 · "
                     "收入按季披露，利润只有半年度 · 2026 年起采用新分部口径"),
        "headline": headline,
        "brief": brief,
        "source": ('Source: <a href="https://www.kering.com/en/finance/publications/" rel="noopener">Kering Finance '
                   'Publications</a>（季度收入公告、半年度与全年业绩新闻稿、半年度财务报告、Financial Document、'
                   '演示材料与重述公告）。Kering 不是 SEC 报告发行人，本页没有任何 EDGAR 来源。'),
        "source_url": "https://www.kering.com/en/finance/publications/",
        "source_links": [{"label": doc_label(x["doc"]), "url": x["url"]} for x in st["sources"]],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {"id": "settled",
             "title": "一、上季跟踪指标兑现了吗",
             "description": s1_description,
             "exhibits": settled_group},
            {"id": "quarter_highlights",
             "title": "二、本季重点",
             "description": (s2_lead + "季度口径只有收入：集团可比增速、分部贡献与 Gucci 本身。"
                             f"{half_word(halves[-1])}在本季结束，所以本期半年利润率的结论也放在这一节。"
                             if half_now else
                             s2_lead + "季度口径只有收入：集团可比增速、分部贡献与 Gucci 本身。"),
             "exhibits": highlight_group},
            {"id": "next_quarter",
             "title": "三、下季要跟踪什么",
             "description": "阈值为本地研究设定，不是公司指引；当前值离下季阈值还有多远，统一用「距阈值余量」口径。",
             "exhibits": next_group},
            {"id": "routine",
             "title": "四、长期常规跟踪",
             "description": (f"Kering 特有的长期序列：品牌季度收入与可比增速回到 {quarter_cn(q[0])}，"
                             f"品牌线停在 {quarter_cn(q[end - 1])}（之后不再披露）；半年利润率与毛利率回到 "
                             f"{halves[0]}，x 轴是半年、不是季度；资本市场日的中期利润率目标画在集团半年利润率上；"
                             "净负债是期末时点。"),
             "exhibits": routine_group},
        ],
        "tables": tables,
        "notes": notes,
        "footer": "Kering quarterly results · 数据来自公司公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "ker.js"), payload, "ker")
    shell_dir = ROOT / "ker"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("KER.PA", "ker"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"Kering page: {charts} charts in {len(payload['sections'])} sections "
          f"+ {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
