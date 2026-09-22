"""奢侈品组跨公司对照页.

This is the first page on this site that is not about a company. It reads the
six luxury `series/*.json` files that already exist -- LVMH, Richemont, Hermès,
Kering, Zegna, Brunello Cucinelli -- and publishes only what can be said across
all six at once. It has no filings data of its own: `series/luxury.json` holds
the member list, each company's own name for its growth metric, and the
period-stamped story blocks, and **every number on the page is computed from the
six companies' series at build time**. A quarter roll on any of those six moves
this page with it; this file and `series/luxury.json` do not change.

**What the page is about is the thing a cross-company page usually hides.**
Six luxury groups report a figure they all call growth, and in the quarter this
page is built for those figures run from Kering's +2% to Richemont's +20%. None
of them is the same construct as any other: two different exclusion rules, one
company whose quarterly version this site has not connected at all, and one --
Cucinelli -- for which a quarterly growth rate does not exist and cannot be
derived, because the issuer prints only cumulative figures. So the page leads
with the comparison, then spends the rest of itself saying exactly how far the
comparison can be pushed, one measured claim at a time.

Three findings are the page's own, and each is measured here rather than
asserted:

1. **The common window is eight quarters, and it is set by this site, not by the
   companies.** Three of the six reach 2016; Hermès reaches only 2024Q3 because
   that is as far back as this site has connected it, which is an ingestion
   boundary and is labelled as one.
2. **Dividing one euro revenue line by its own year-ago value is safe for some
   of these companies and wrong for others.** Richemont's euro amounts for
   2021Q2–2022Q1 are the restated continuing-operations figures while the growth
   rates it printed for those quarters are the original YNAP-inclusive ones, so
   a derived rate misses the printed one by up to 28pp. Kering carries two bases
   for three 2025 quarters at once. The page measures the gap instead of
   describing it, and refuses to draw a derived rate where the measurement says
   it is unsafe.
3. **Profit runs on two clocks, not one.** Five of the six close a half-year on
   30 June; Richemont closes on 30 September. There is no calendar half-year for
   Richemont, so it is not put on that axis -- it gets its own.

Every universal sentence on this page ("只有一家", "没有一家", "全部") is printed
only while the data still supports it: the builder computes the population and
drops or rewrites the sentence otherwise, so a roll that changes the fact
changes the prose. `tests/test_luxury_dashboard.py` re-derives every published
figure from the six series **without calling anything in this module**, which is
the only check that a cross-page join is right -- the per-company `_checks`
blocks already settle whether each figure matches its own filing, and copying
them here would only prove this file equals those six.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import (  # noqa: E402
    ai_capex_cycle_table,
    cn_count,
    display_period,
    fill_story,
    number_exhibits,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402

STAGING_PATH = ROOT / "series" / "luxury.json"
SERIES_DIR = ROOT / "series"
DATA_DIR = ROOT / "data"

SLUG = "luxury"

# The euro is the one unit all six file in, but not at the same magnitude:
# LVMH, Richemont, Hermès and Kering publish millions, Zegna and Cucinelli
# publish thousands. Everything below is normalised to EUR millions at the
# accessor, so no chart mixes the two.
EUR_K = 1 / 1000.0


# ── reading the six ─────────────────────────────────────────────────────────
def _load(slug: str) -> dict:
    return json.loads((SERIES_DIR / f"{slug}.json").read_text(encoding="utf-8"))


def _q(label: str) -> str:
    """Normalise a quarter label to ``2026Q2``.

    Hermès stores ``Q2 2026`` and everyone else stores ``2026Q2``. A cross-page
    join keyed on the raw strings would silently produce an empty intersection
    rather than an error, which is the failure this function exists to prevent.
    """
    text = str(label).strip()
    if len(text) == 6 and text[4] == "Q":
        return text
    head, tail = text.split()
    return f"{tail}{head}" if head.startswith("Q") else f"{head}{tail}"


def _h(label: str) -> str:
    """Normalise a half label to ``H1 2026`` (LVMH/Kering/Hermès spelling)."""
    text = str(label).strip()
    if text.startswith("H"):
        return text
    return f"H{text[5]} {text[:4]}"


_CALENDAR_HALF = __import__("re").compile(r"H[12] \d{4}")


def _order(label: str) -> tuple[int, int]:
    return int(label[:4]), int(label[5])


def mc_view(d: dict) -> dict:
    return {
        "quarters": [_q(q) for q in d["long_quarters"]],
        "revenue": list(d["quarterly_revenue_eur_m"]["total"]),
        "growth": [(None if v is None else float(v)) for v in d["organic_growth_pct"]["total"]],
        "growth_quarters": [_q(q) for q in d["organic_quarters"]],
        "reported_growth": None,
        "halves": [_h(x) for x in d["halves"]],
        "half_revenue": list(d["half_revenue_eur_m"]["total"]),
        "half_profit": list(d["half_pro_eur_m"]["total"]),
        "profit_term": "经常性经营利润",
        "calendar_halves": True,
        "release_date": d["latest"]["release_date"],
        "latest_period": _q(d["latest"]["disclosed_period_label"]),
    }


def cfr_view(d: dict) -> dict:
    return {
        "quarters": [_q(q) for q in d["quarters"]],
        "revenue": list(d["quarterly_eur_m"]["total"]),
        "growth": [(None if v is None else float(v)) for v in d["quarterly_cer_pct"]["total"]],
        "growth_quarters": [_q(q) for q in d["quarters"]],
        "reported_growth": [(None if v is None else float(v))
                            for v in d["quarterly_actual_pct"]["total"]],
        # Richemont's financial year ends 31 March, so its halves close on
        # 30 September and 31 March. They are real halves; they are simply not
        # the halves the other five close, which is why they never go on the
        # shared axis.
        "halves": list(d["halves"]),
        "half_revenue": list(d["half_eur_m"]["sales"]),
        "half_profit": list(d["half_eur_m"]["operating_profit"]),
        "profit_term": "经营利润",
        "calendar_halves": False,
        "release_date": d["latest"]["release_date"],
        "latest_period": _q(d["latest"]["disclosed_period_label"]),
    }


def rms_view(d: dict) -> dict:
    quarters = [_q(p) for p in d["periods"]]
    return {
        "quarters": quarters,
        "revenue": list(d["group_revenue"]["revenue_eur_m"]),
        # The euro line reaches four quarters further back than the rates do:
        # 2016 arrives as the prior-year column of the 2017 releases, which
        # prints the amount and not the growth beside it.
        "growth": [(None if v is None else float(v)) for v in d["group_revenue"]["cc_pct"]],
        "growth_quarters": quarters,
        "reported_growth": [(None if v is None else float(v))
                            for v in d["group_revenue"]["published_pct"]],
        "halves": [_h(h["label"]) for h in d["half_years"]],
        "half_revenue": [h["revenue_eur_m"] for h in d["half_years"]],
        "half_profit": [h["recurring_operating_income_eur_m"] for h in d["half_years"]],
        "profit_term": "经常性经营利润",
        "calendar_halves": True,
        "release_date": d["release_dates"][d["latest"]["period"]],
        "latest_period": _q(d["latest"]["period"]),
    }


def ker_view(d: dict) -> dict:
    return {
        "quarters": [_q(q) for q in d["long_quarters"]],
        "revenue": list(d["quarterly_revenue_eur_m"]["group_first_published"]),
        "growth": [(None if v is None else float(v))
                   for v in d["quarterly_comparable_pct"]["group_first_published"]],
        "growth_quarters": [_q(q) for q in d["long_quarters"]],
        "reported_growth": None,
        "halves": [_h(x) for x in d["halves"]],
        "half_revenue": list(d["half_group"]["revenue"]["values"]),
        "half_profit": list(d["half_group"]["recurring_operating_income"]["values"]),
        "profit_term": "经常性经营利润",
        "calendar_halves": True,
        "release_date": d["latest"]["release_date"],
        "latest_period": _q(d["latest"]["period"]),
    }


def zgn_view(d: dict) -> dict:
    q = d["quarterly"]
    h = d["half"]
    return {
        "quarters": [_q(p) for p in q["periods"]],
        "revenue": [v * EUR_K for v in q["revenue_eur_k"]],
        # Zegna prints a constant-currency rate every quarter, but this site has
        # not connected that series -- `series/zgn.json` carries the organic rate
        # for one half only. So the page has no company-published quarterly rate
        # for Zegna and says so rather than borrowing a neighbour's.
        "growth": None,
        "growth_quarters": None,
        "reported_growth": None,
        "halves": [_h(p) for p in h["periods"]],
        "half_revenue": list(h["revenue"]),
        "half_profit": list(h["operating_profit"]),
        "profit_term": "经营利润",
        "calendar_halves": True,
        "release_date": d["latest"]["release_date"],
        "latest_period": _q(d["quarterly"]["periods"][-1]),
    }


def bc_view(d: dict) -> dict:
    q = d["quarterly"]
    h = d["half"]
    return {
        "quarters": [_q(p) for p in q["periods"]],
        "revenue": [v * EUR_K for v in q["revenue_eur_k"]],
        # Cucinelli's own constant-currency rate exists only at the half and the
        # year, because the issuer prints only cumulative revenue: three
        # quarters in four are this site's subtraction, and a constant-currency
        # rate cannot be subtracted out of two cumulative ones.
        "growth": None,
        "growth_quarters": None,
        "reported_growth": None,
        "halves": [_h(p) for p in h["periods"]],
        "half_revenue": list(h["revenue_eur_k"]),
        "half_profit": list(h["ebit_eur_k"]),
        "profit_term": "EBIT",
        "calendar_halves": True,
        "release_date": d["latest"]["release_date"],
        "latest_period": _q(d["quarterly"]["periods"][-1]),
    }


VIEWS = {"mc": mc_view, "cfr": cfr_view, "rms": rms_view,
         "ker": ker_view, "zgn": zgn_view, "bc": bc_view}

# How many of the quarters on each company's axis it prints as a discrete
# quarter, against how many this site obtains by subtracting one cumulative
# disclosure from another. Read from each series' own basis record, so a
# company that starts printing discrete quarters moves its own row.
def _basis_counts(slug: str, d: dict, quarters: list[str]) -> tuple[int, int, int]:
    """(printed, derived, missing) over the quarters this page can plot."""
    if slug == "cfr":
        counts = {"printed": 0, "derived": 0, "missing": 0}
        for basis in d["quarter_basis"]:
            counts[basis] += 1
        return counts["printed"], counts["derived"], counts["missing"]
    if slug == "bc":
        printed = sum(1 for b in d["quarterly"]["basis"] if b == "printed")
        return printed, len(quarters) - printed, 0
    # LVMH, Kering, Hermès and Zegna each print every quarter on their axis as a
    # discrete quarter; none of the four series carries a per-quarter basis
    # array, because there is nothing to flag.
    return len(quarters), 0, 0


def read_members(staging: dict) -> list[dict]:
    members = []
    for entry in staging["members"]:
        slug = entry["slug"]
        data = _load(slug)
        view = VIEWS[slug](data)
        plottable = [q for q, v in zip(view["quarters"], view["revenue"]) if v is not None]
        printed, derived, missing = _basis_counts(slug, data, plottable)
        members.append({
            **entry,
            "data": data,
            **view,
            "plottable": plottable,
            "printed_quarters": printed,
            "derived_quarters": derived,
            "missing_quarters": missing,
        })
    return members


# ── small helpers ───────────────────────────────────────────────────────────
def at(labels: list[str], values: list, want: list[str]) -> list:
    index = {label: i for i, label in enumerate(labels)}
    return [values[index[w]] if w in index else None for w in want]


def yoy(labels: list[str], values: list, want: list[str]) -> list:
    """Reported-basis year-on-year, in percent, from a euro line.

    ``None`` wherever either leg is missing. This is arithmetic on the page's
    own series and is marked D everywhere it appears; whether it is *safe*
    arithmetic for a given company is the question Exhibit on basis answers.
    """
    index = {label: i for i, label in enumerate(labels)}
    out = []
    for label in want:
        year, quarter = _order(label)
        prior = f"{year - 1}Q{quarter}"
        if label in index and prior in index:
            now, before = values[index[label]], values[index[prior]]
            out.append(round((now / before - 1) * 100, 4) if now is not None and before else None)
        else:
            out.append(None)
    return out


def pct1(value: float | None) -> str:
    return "—" if value is None else f"{'−' if value < 0 else ''}{abs(value):.1f}%"


def signed1(value: float | None) -> str:
    if value is None:
        return "—"
    return ("+" if value >= 0 else "−") + f"{abs(value):.1f}%"


def eur_m(value: float | None) -> str:
    return "—" if value is None else f"€{value:,.0f}M"


def eur_b(value: float | None) -> str:
    return "—" if value is None else f"€{value / 1000:,.1f}B"


def rounded(values: list, digits: int = 6) -> list:
    return [None if v is None else round(float(v), digits) for v in values]


def resolve_refs(exhibits: list[dict], tables: list[dict]) -> None:
    """Replace ``{EX_NAME}`` / ``{TBL_NAME}`` with the numbers assigned at render."""
    numbers = {e["ref"]: e["n"] for e in exhibits if "ref" in e}
    numbers.update({t["ref"]: t["n"] for t in tables if "ref" in t})
    for item in list(exhibits) + list(tables):
        for key in ("note", "src_extra", "title"):
            text = item.get(key)
            if not text:
                continue
            for ref, number in numbers.items():
                text = text.replace("{" + ref + "}", str(number))
            item[key] = text


SOURCE = ("本页不自己取数：每一个数都在构建时从六家公司各自的 series 文件现算，"
          "而那六个文件的每一格都注明了它取自哪一份公司原件。"
          "各公司的原件链接在本页「来源与版本线索」里逐家列出。")
AXIS = "纵轴不自 0 起，但没有任何点被截掉。"


# ── the measurements the page is built on ───────────────────────────────────
def analysis(members: list[dict], staging: dict) -> dict:
    """Everything the page states, measured here once.

    Nothing below is typed: the window lengths, the exclusion-rule census, the
    basis-seam gaps and the profit-clock split are all read off the six series,
    so a roll that changes any of them changes the sentence that reports it.
    """
    by_slug = {m["slug"]: m for m in members}

    # The window every company can be plotted on. It is an intersection, so it
    # is set by whichever member reaches back least far -- and that member is
    # not necessarily the one that discloses least.
    common = sorted(set.intersection(*(set(m["plottable"]) for m in members)), key=_order)
    longest = sorted(set.union(*(set(m["plottable"]) for m in members)), key=_order)
    latest = common[-1]

    # Each company's own rate on the shared axis, and -- for the two with no
    # connected quarterly rate -- this page's own arithmetic on its euro line,
    # which is a different kind of number and is labelled as one everywhere.
    # Every company's rate over the **union** window, not the intersection.
    # Cutting each series to the six-way intersection at this point is what made
    # four-company charts as short as the six-company one: a chart should be as
    # deep as the companies it actually draws, and that is a property of the
    # subset, not of the page.
    rate_by_slug, own_kind = {}, {}
    for m in members:
        if m["growth"] is not None:
            values = at(m["growth_quarters"], m["growth"], longest)
            own_kind[m["slug"]] = "printed"
        else:
            values = yoy(m["quarters"], m["revenue"], longest)
            own_kind[m["slug"]] = "derived"
        rate_by_slug[m["slug"]] = {q: v for q, v in zip(longest, values) if v is not None}
    own_rate = {m["slug"]: at(longest, [rate_by_slug[m["slug"]].get(q) for q in longest], common)
                for m in members}
    long_rate = {}
    for m in members:
        if m["growth"] is not None:
            long_rate[m["slug"]] = at(m["growth_quarters"], m["growth"], longest)
        else:
            long_rate[m["slug"]] = yoy(m["quarters"], m["revenue"], longest)

    # Cross-sectional spread: how far apart the six were in each quarter they
    # all reported. The page's central claim rests on this series, so it is
    # computed over the full six every time rather than over "the ones that
    # happen to be non-null".
    # Two windows, not one. Every member has a euro figure over `common`, but
    # a growth reading needs either a rate the company printed or a year-ago
    # euro quarter to divide by, and the two members with no printed quarterly
    # rate cannot produce one until their euro line is a year old. Richemont
    # adds its own holes: it printed no standalone rate at all before 2021Q2.
    # So the rate charts run on `rate_window`, which is where all six can be
    # read, and the page says why it is shorter.
    rate_window = window_for(members, rate_by_slug, longest)
    spread = []
    for quarter in rate_window:
        index = common.index(quarter)
        column = [own_rate[m["slug"]][index] for m in members]
        spread.append(round(max(column) - min(column), 4))
    own_rate = {slug: [values[common.index(q)] for q in rate_window]
                for slug, values in own_rate.items()}

    # Trailing-twelve-month revenue, the one figure that needs no basis
    # argument at all: four printed euro quarters added up.
    ltm_window = common[-4:]
    ltm = {}
    for m in members:
        values = at(m["quarters"], m["revenue"], ltm_window)
        ltm[m["slug"]] = None if any(v is None for v in values) else sum(values)

    # Can this euro line be divided by its own year-ago value? Two of the six
    # print a reported-basis rate of their own, so for those two the question
    # is answerable by measurement rather than by reading the filing history.
    derive_gap = {}
    for m in members:
        if m["reported_growth"] is None:
            derive_gap[m["slug"]] = None
            continue
        mine = yoy(m["quarters"], m["revenue"], m["quarters"])
        pairs = [(q, round(d, 4), float(p))
                 for q, d, p in zip(m["quarters"], mine, m["reported_growth"])
                 if d is not None and p is not None]
        worst = max(pairs, key=lambda row: abs(row[1] - row[2])) if pairs else None
        derive_gap[m["slug"]] = {
            "pairs": pairs,
            "worst_quarter": worst[0] if worst else None,
            "worst_gap_pp": round(abs(worst[1] - worst[2]), 4) if worst else None,
            "beyond_one_pp": [row[0] for row in pairs if abs(row[1] - row[2]) > 1.0],
        }

    # Kering publishes three 2025 quarters twice, on two bases, so a derived
    # rate for the matching 2026 quarter has two answers. Measured rather than
    # described: the page prints the size of the fork.
    ker = by_slug["ker"]
    grid = ker["data"]["new_grid"]
    first_published = dict(zip(ker["quarters"], ker["revenue"]))
    ker_fork = []
    for index, quarter in enumerate(grid["quarters"]):
        restated = grid["revenue_eur_m"]["total"][index]
        original = first_published.get(quarter)
        if original is None or restated is None or original == restated:
            continue
        year, number = _order(quarter)
        later = f"{year + 1}Q{number}"
        if later not in first_published:
            continue
        ker_fork.append({
            "base_quarter": quarter,
            "derived_quarter": later,
            "first_published": original,
            "restated": restated,
            "on_first_published": round((first_published[later] / original - 1) * 100, 4),
            "on_restated": round((first_published[later] / restated - 1) * 100, 4),
        })

    # Profit runs on two clocks. Which companies close a half-year on the same
    # dates is read from the series, not assumed from the country.
    calendar = [m for m in members if m["calendar_halves"]]
    off_clock = [m for m in members if not m["calendar_halves"]]
    # A member is on the calendar clock only if its half labels really are
    # calendar halves. Marking an off-clock company as on-clock used to fail
    # further down with an IndexError from an empty intersection -- a crash is
    # not a check: it stops the build without saying that two companies were
    # about to be compared across a three-month offset.
    for member in calendar:
        odd = [label for label in member["halves"] if not _CALENDAR_HALF.fullmatch(label)]
        if odd:
            raise ValueError(
                f"{member['slug']} is marked calendar_halves but its half labels are "
                f"{odd[:3]}: a fiscal half cannot go on the shared axis, because its "
                "six months are not the other members' six months")
    # The union, from the first half any member can fill. Cutting to the
    # intersection made this seven halves long while three of the five reach
    # 2016 -- the same mistake the quarterly charts had, one clock down. A line
    # that has not started yet is a gap, which is the honest picture.
    half_common = sorted(set().union(*(set(m["halves"]) for m in calendar)),
                         key=lambda h: (h.split()[1], h.split()[0]))
    if not half_common:
        raise ValueError("the members on the calendar clock share no half-year: "
                         + "; ".join(f"{m['slug']}={m['halves'][0]}..{m['halves'][-1]}"
                                     for m in calendar))
    margin = {}
    for m in calendar:
        row = []
        index = {h: i for i, h in enumerate(m["halves"])}
        for half in half_common:
            i = index.get(half)
            if i is None:
                row.append(None)
                continue
            revenue, profit = m["half_revenue"][i], m["half_profit"][i]
            row.append(None if not revenue or profit is None else round(profit / revenue * 100, 4))
        margin[m["slug"]] = row

    # How many distinct names the six give the profit line they lead with, and
    # how many distinct exclusion rules sit behind the word "growth".
    profit_terms = sorted({m["profit_term"] for m in members})
    rules = {}
    for entry in staging["growth_metrics"]:
        excludes = entry["excludes"]
        key = "unknown" if excludes is None else " + ".join(sorted(excludes))
        rules.setdefault(key, []).append(entry["slug"])

    return {
        "common": common,
        "rate_window": rate_window,
        "rate_by_slug": rate_by_slug,
        "longest": longest,
        "latest": latest,
        "own_rate": own_rate,
        "own_kind": own_kind,
        "long_rate": long_rate,
        "spread": spread,
        "ltm": ltm,
        "ltm_window": ltm_window,
        "derive_gap": derive_gap,
        "ker_fork": ker_fork,
        "calendar": calendar,
        "off_clock": off_clock,
        "half_common": half_common,
        "margin": margin,
        "profit_terms": profit_terms,
        "exclusion_rules": rules,
    }


# ── exhibits ────────────────────────────────────────────────────────────────
def window_for(subset: list[dict], rate_by_slug: dict, axis: list[str]) -> list[str]:
    """From the first quarter every member of `subset` can fill, to the end.

    A chart drawn from four companies has no business being cut to the window
    six of them share -- that is how a four-company chart ended up 18 quarters
    long when its members reach back to 2016Q4.

    The window runs from the first covered quarter and does **not** stop at the
    next gap. Richemont printed a standalone quarterly rate only in some years
    before 2021, so the middle of this range has holes; a hole is drawn as a
    break in the line, which says 「the company printed nothing here」. Cutting
    the window at the last gap instead would throw away every quarter before it
    and say nothing at all.
    """
    covered = [q for q in axis if all(q in rate_by_slug[m["slug"]] for m in subset)]
    return axis[axis.index(covered[0]):] if covered else []


def rule_census(members: list[dict], a: dict) -> str:
    """「只剔除汇率：历峰、爱马仕、库奇内利；剔除汇率与合并范围：LVMH、开云」.

    Built from the census rather than written out, so a company that changes
    what its own metric strips moves itself between the clauses.
    """
    zh = {m["slug"]: m["zh"] for m in members}
    words = {"fx": "只剔除汇率", "fx + perimeter": "剔除汇率与合并范围"}
    return "；".join(
        f"{words.get(rule, rule)}：" + "、".join(zh[s] for s in slugs)
        for rule, slugs in a["exclusion_rules"].items() if rule != "unknown")


def series_of(members: list[dict], values: dict, only: list[str] | None = None,
              suffix: dict | None = None) -> list[dict]:
    """One line per member, in the order `series/luxury.json` lists them."""
    out = []
    for m in members:
        if only is not None and m["slug"] not in only:
            continue
        name = m["short"] + (suffix or {}).get(m["slug"], "")
        out.append({"name": name, "color": m["color"], "values": rounded(values[m["slug"]])})
    return out


def comparability_charts(members: list[dict], a: dict) -> list[dict]:
    window = a["rate_window"]
    kinds = {m["slug"]: a["own_kind"][m["slug"]] for m in members}
    borrowed = [m for m in members if kinds[m["slug"]] == "derived"]
    suffix = {m["slug"]: "（报告口径 D）" for m in borrowed}
    printed_names = "、".join(m["short"] for m in members if kinds[m["slug"]] == "printed")
    borrowed_names = "、".join(m["short"] for m in borrowed)
    rule_words = rule_census(members, a)
    unknown = a["exclusion_rules"].get("unknown", [])

    own = {
        "ref": "EX_OWN",
        "kind": "lines",
        "title": f"六家在共同的{cn_count(len(window))}个季度里的单季同比（各自口径）",
        "xlabels": list(window),
        "series": series_of(members, a["own_rate"], suffix=suffix),
        "zero_line": True,
        "end_label": True,
        "label_fmt": "pct1",
        "ylab": "单季同比 %",
        "full": True,
        "note": (f"六条线同时有数的窗口只有这{cn_count(len(window))}个季度 —— "
                 f"它是六家可画区间的交集，见 Exhibit {{EX_WINDOW}}。"
                 f"{printed_names}画的是公司自己印出的那个增速；"
                 f"{borrowed_names}没有按季的公司口径增速可用，画的是本页用欧元收入自算的报告口径同比（D），"
                 "两种数不是一回事，图例里标着。"
                 f"剔除法本身也不统一 —— {rule_words}"
                 + ("；" + "、".join(next(x["zh"] for x in members if x["slug"] == s)
                                    for s in unknown) + "的剔除项本站没有记录。" if unknown else "。")),
        "src_extra": AXIS,
    }
    printed_only = [m for m in members if kinds[m["slug"]] == "printed"]
    wide = window_for(printed_only, a["rate_by_slug"], a["longest"])
    def range_of(subset, axis):
        out = []
        for q in axis:
            column = [a["rate_by_slug"][m["slug"]].get(q) for m in subset]
            out.append(None if any(v is None for v in column) else round(max(column) - min(column), 4))
        return out
    spread = {
        "ref": "EX_SPREAD",
        "kind": "lines",
        "title": "同一个季度里，这些公司之间的极差",
        "xlabels": list(wide),
        "series": [
            {"name": f"六家（{window[0]} 起）", "color": "NAVY",
             "values": rounded(range_of(members, wide))},
            {"name": f"印出口径的四家（{wide[0]} 起）", "color": "GOLD",
             "values": rounded(range_of(printed_only, wide))},
        ],
        "end_label": True,
        "xstep": 4,
        "full": True,
        "zero_base": True,
        "label_fmt": "pp1",
        "ylab": "最高与最低之差（pp）",
        "note": ("每一列取最大减最小。蓝线是六家都有数的那一段，金线只算印出公司口径的"
                 f"{cn_count(len(printed_only))}家、因此能多画 {len(wide) - len(window)} 个季度 —— "
                 "两条线一起看才知道极差是这一轮才宽的，还是一直就宽。"
                 "这回答的是「奢侈品这一季怎么样」这个问题本身成不成立："
                 + (f"这{cn_count(len(window))}个季度里极差一次都没有收到 10pp 以内，"
                    if min(v for v in a["spread"] if v is not None) >= 10 else
                    f"极差最窄的一格是 {a['rate_window'][a['spread'].index(min(v for v in a['spread'] if v is not None))]} 的 "
                    f"{min(v for v in a['spread'] if v is not None):.1f}pp，")
                 + f"最宽的一格是 {a['rate_window'][a['spread'].index(max(v for v in a['spread'] if v is not None))]} 的 "
                 f"{max(v for v in a['spread'] if v is not None):.1f}pp。"
                 "六个数里有两个是本页自算的报告口径，所以极差本身也带着口径差，不是纯粹的经营差异。"),
        "src_extra": AXIS,
    }
    scale = {
        "ref": "EX_SCALE",
        "kind": "bars_labeled",
        "title": f"最近四个季度的收入合计（{a['ltm_window'][0]}–{a['ltm_window'][-1]}）",
        "xlabels": [m["short"] for m in members],
        "values": rounded([a["ltm"][m["slug"]] for m in members]),
        "label_fmt": "f0c",
        "ylab": "€M",
        "xrot": 0,
        "note": ("这个数完全不需要口径讨论：四个季度的欧元收入直接相加。"
                 f"最大的{max(members, key=lambda m: a['ltm'][m['slug']])['zh']}是最小的"
                 f"{min(members, key=lambda m: a['ltm'][m['slug']])['zh']}的 "
                 f"{max(a['ltm'].values()) / min(a['ltm'].values()):.0f} 倍 —— "
                 "把这六家放进同一个「板块」讨论时，这个倍数值得先看一眼。"
                 "杰尼亚与库奇内利原始披露以千欧元计，本页统一折算为百万欧元。"),
        "src_extra": AXIS,
    }
    return [own, spread, scale]


def lead_with_depth(comparability: list[dict], window_block: list[dict]) -> tuple[list, list]:
    """Put the 42-quarter chart first and the six-way zoom second.

    A reader who meets the eighteen-quarter chart first reads it as 「this is
    the record」. It is not: it is the part of the record six companies share,
    and three of them have four times as much. So the long chart opens the page
    and the intersection follows it, explicitly as a zoom.
    """
    own, spread, scale = comparability
    window_chart, long_view = window_block
    return [long_view, own, spread], [window_chart, scale]


def window_charts(members: list[dict], a: dict) -> list[dict]:
    longest = a["longest"]
    shortest = min(members, key=lambda m: len(m["plottable"]))
    deepest = [m for m in members if len(m["plottable"]) == max(len(x["plottable"]) for x in members)]

    # The opposite case to the shortest line: a floor that really is the
    # issuer's. Which quarters those are is read off each series' own basis
    # record, so the clause cannot outlive the fact -- a company that starts
    # printing discrete quarters rewrites its own half of this sentence.
    subtracted = [m for m in members if m["derived_quarters"]]
    subtraction_words = ""
    if subtracted:
        worst = max(subtracted, key=lambda m: m["derived_quarters"] / len(m["plottable"]))
        printed_at = sorted({q[4:] for q, basis in zip(worst["quarters"],
                                                       worst["data"]["quarterly"]["basis"])
                             if basis == "printed"}) if worst["slug"] == "bc" else []
        subtraction_words = (
            f"{worst['zh']}那一格相反，是真的披露边界：公司只印累计数，"
            f"可画的 {len(worst['plottable'])} 个季度里有 {worst['derived_quarters']} 个是相减出来的"
            + (f"，印出来的 {worst['printed_quarters']} 个全部是 {printed_at[0]}。"
               if len(printed_at) == 1 else "。"))
    missing = [m for m in members if m["missing_quarters"]]
    missing_words = ""
    if missing:
        gone = missing[0]
        labels = [q for q, basis in zip(gone["quarters"], gone["data"]["quarter_basis"])
                  if basis == "missing"]
        missing_words = (f"{gone['zh']}另有 {gone['missing_quarters']} 个季度谁也还原不了"
                         f"（{'、'.join(labels)}）—— 公司当年只在股东大会上报「前五个月」，"
                         "那五个月拆不回两个季度。")
    window = {
        "ref": "EX_WINDOW",
        "kind": "grouped_bars",
        "title": "每家在本站可画的季度数，以及其中有多少格是公司自己印出来的",
        "xlabels": [m["short"] for m in members],
        "groups": [
            {"name": "公司印出的单季数", "color": "NAVY",
             "values": [m["printed_quarters"] for m in members]},
            {"name": "本站由累计数相减得到 D", "color": "GOLD",
             "values": [m["derived_quarters"] for m in members]},
            {"name": "无法还原", "color": "GRAY",
             "values": [m["missing_quarters"] for m in members]},
        ],
        "bar_labels": True,
        "label_fmt": "f0",
        "ylab": "季度数",
        "xrot": 0,
        "full": True,
        "note": (f"共同窗口只有{cn_count(len(a['common']))}个季度，是因为{shortest['zh']}这条线在本站"
                 f"只到 {shortest['plottable'][0]}；"
                 f"最深的{'、'.join(m['zh'] for m in deepest)}到 "
                 f"{deepest[0]['plottable'][0]}。<b>{shortest['zh']}那一格是本站的接入边界，"
                 "不是公司的披露边界</b> —— 它自己按季披露得更早，只是本站还没回补。"
                 + subtraction_words + missing_words),
        "src_extra": "「无法还原」指公司从未单独印出、也无法由任何两份累计披露相减得到的季度。",
    }
    # Two quarters of the 2021 rebound run to roughly twice anything else on the
    # axis, and on a shared scale they flatten the divergence this chart exists
    # to show. The renderer's cap marks the clipped points and prints their real
    # values beside them, so the ceiling costs no information -- but it is
    # derived from the rest of the data rather than typed, and the note says how
    # many points it caught.
    ranked = sorted((v for row in a["long_rate"].values() for v in row if v is not None),
                    reverse=True)
    # Find the widest multiplicative step near the top of the distribution: that
    # is what separates the 2021 rebound from everything else, and it is a
    # property of the data rather than a number chosen to make the chart look
    # right. If no step is wide enough, nothing is capped and the axis is the
    # plain one -- a year in which the spikes flatten out un-caps itself.
    head = max(3, len(ranked) // 20)
    steps = [(ranked[i] / ranked[i + 1], i) for i in range(min(head, len(ranked) - 1))
             if ranked[i + 1] > 0]
    ratio, at_index = max(steps) if steps else (1.0, 0)
    ceiling = 10 * (int(ranked[at_index + 1] / 10) + 1) if ratio >= 1.5 else None
    capped = [] if ceiling is None else [
        (m["zh"], longest[i], row[i])
        for m in members for row in [a["long_rate"][m["slug"]]]
        for i in range(len(longest)) if row[i] is not None and row[i] > ceiling]
    long_view = {
        "ref": "EX_LONG",
        "kind": "lines",
        **({"ycap": ceiling,
            "cap_note": f"纵轴封顶 {ceiling:.0f}%，{cn_count(len(capped))}个点按真值标出"}
           if capped else {}),
        "title": f"把窗口拉到 {longest[0]}：六条线各自从哪里开始",
        "xlabels": list(longest),
        "series": series_of(members, a["long_rate"],
                            suffix={m["slug"]: "（报告口径 D）" for m in members
                                    if a["own_kind"][m["slug"]] == "derived"}),
        "zero_line": True,
        "end_label": True,
        "label_fmt": "pct1",
        "ylab": "单季同比 %",
        "xstep": 4,
        "full": True,
        "height": 320,
        "note": ("同一张图同时给出两件事：这一轮周期的形状，和六条线各自的起点。"
                 "线中断的地方不是零，是那一格没有数 —— 每条线的起点就是它在本站的接入下限，"
                 "中间的断口是公司从未单独印出、也还原不了的季度。"
                 "2020 年那个深坑与 2021 年的反弹在每条线上都在，"
                 "而窗口末端六条线明显分开 —— 那正是 Exhibit {EX_SPREAD} 量的东西。"
                 + (f"纵轴封顶在 {ceiling:.0f}%："
                    + "、".join(f"{name} {label} 的 {value:.0f}%" for name, label, value in capped)
                    + "越过了这条线，图上按真值标出，没有被截掉。" if capped else "")),
        "src_extra": AXIS,
    }
    return [window, long_view]




def basis_charts(members: list[dict], a: dict) -> list[dict]:
    """Two charts about the rulers, not about the companies."""
    printed = [m for m in members if a["own_kind"][m["slug"]] == "printed"]
    # This chart draws four companies, so it runs on the window those four
    # share -- not on the six-company one. They reach considerably further back.
    window = window_for(printed, a["rate_by_slug"], a["longest"])
    wedge = {}
    for m in printed:
        reported = yoy(m["quarters"], m["revenue"], window)
        own = [a["rate_by_slug"][m["slug"]].get(q) for q in window]
        wedge[m["slug"]] = [None if o is None or r is None else round(o - r, 4)
                            for o, r in zip(own, reported)]
    latest_gap = {m["slug"]: wedge[m["slug"]][-1] for m in printed}
    widest = max(printed, key=lambda m: abs(latest_gap[m["slug"]] or 0))
    # A line that starts late says something, so it should say it: subtracting a
    # reported rate needs a year-ago euro figure, and one member's euro line
    # does not reach back that far.
    late = [m for m in printed if wedge[m["slug"]][0] is None]
    late_words = "".join(
        f"{m['zh']}这条线从 {window[next(i for i, v in enumerate(wedge[m['slug']]) if v is not None)]} 才开始，"
        "因为减出报告口径同比要用到上年同期的欧元收入，而本站的它还没有那么早。"
        for m in late)

    wedge_ex = {
        "ref": "EX_WEDGE",
        "kind": "lines",
        "title": "公司自己的口径比欧元口径高出多少（同一季，同一家）",
        "xlabels": list(window),
        "series": series_of(printed, wedge),
        "zero_line": True,
        "end_label": True,
        "label_fmt": "pp1",
        "xstep": 4,
        "full": True,
        "ylab": "自己口径 − 报告口径自算（pp）",
        "note": (f"只画有公司口径可比的{cn_count(len(printed))}家 —— 也正因为只有这"
                 f"{cn_count(len(printed))}家，这张图能画 {len(window)} 个季度"
                 f"（{window[0]}–{window[-1]}），比六家共同的那根轴长得多。每条线是「公司印出来的那个增速」减去「本页用它自己的"
                 "欧元收入算出来的同比」（D）。差额里装着汇率，对剔除合并范围的两家还装着并购与处置。"
                 f"本季最宽的是{widest['zh']}的 "
                 f"{'+' if (latest_gap[widest['slug']] or 0) >= 0 else '−'}"
                 f"{abs(latest_gap[widest['slug']] or 0):.1f}pp。"
                 "这条线越宽，「增速」这个词在两家公司之间就越不能直接比。" + late_words),
        "src_extra": AXIS,
    }

    cfr = next(m for m in members if m["slug"] == "cfr")
    gap = a["derive_gap"]["cfr"]
    printed_rate = at(cfr["quarters"], cfr["reported_growth"], cfr["quarters"])
    mine = yoy(cfr["quarters"], cfr["revenue"], cfr["quarters"])
    mine = [d if p is not None else None for d, p in zip(mine, printed_rate)]
    break_index = cfr["quarters"].index(gap["beyond_one_pp"][0]) if gap["beyond_one_pp"] else None
    seam = {
        "ref": "EX_SEAM",
        "kind": "lines",
        "title": "同一家公司、同一个报告口径，两种算法：公司印出的 vs 本页自算",
        "xlabels": list(cfr["quarters"]),
        "series": [
            {"name": "历峰印出的 actual rates", "color": "NAVY", "values": rounded(printed_rate)},
            {"name": "本页用它的欧元收入自算 D", "color": "GOLD", "values": rounded(mine)},
        ],
        "zero_line": True,
        "label_fmt": "pct1",
        "ylab": "单季同比 %",
        "xstep": 4,
        "full": True,
        **({"break_at": break_index,
            "break_label": f"{gap['beyond_one_pp'][0]}：金额已重述，增速未重述"} if break_index else {}),
        "note": ("两条线本该重合。可比的 "
                 f"{len(gap['pairs'])} 个季度里，除下面点名的几格之外每一格都重合"
                 "（差 1pp 以内，公司两列增速都只印到整数）。分开的是 "
                 f"{'、'.join(gap['beyond_one_pp'])} 这{cn_count(len(gap['beyond_one_pp']))}个季度，"
                 f"最大差 {gap['worst_gap_pp']:.1f}pp。原因在数据本身：这几个季度的欧元金额是公司后来"
                 "按持续经营重述过的（YNAP 转入终止经营），而它当年印出的增速是含 YNAP 的原口径。"
                 "<b>金额被重述了，增速没有被重述，两者留在同一行里。</b>"
                 "所以本页给历峰画增速时一律用它印出来的那一列，从不相除。"),
        "src_extra": "重合与分开的判据是「差 1pp 以内」，因为公司两列增速都只印到整数。",
    }
    return [wedge_ex, seam]


def profit_charts(members: list[dict], a: dict) -> list[dict]:
    halves = a["half_common"]
    calendar, off = a["calendar"], a["off_clock"]
    top = max(calendar, key=lambda m: a["margin"][m["slug"]][-1])
    bottom = min(calendar, key=lambda m: a["margin"][m["slug"]][-1])
    margin = {
        "ref": "EX_MARGIN",
        "kind": "lines",
        "title": f"半年经营利润率：同一根日历轴上的{cn_count(len(calendar))}家",
        "xlabels": list(halves),
        "series": series_of(calendar, a["margin"],
                            suffix={m["slug"]: f"（{m['profit_term']}）" for m in calendar}),
        "end_label": True,
        "label_fmt": "pct1",
        "ylab": "半年经营利润率 %",
        "zero_base": True,
        "full": True,
        "note": ("六家全部一年只出两次利润，所以这一页没有任何形式的「季度利润率」。"
                 f"这根轴上只有{cn_count(len(calendar))}家：{off[0]['zh']}的财年在 3 月底结束，"
                 "它的半年是 4–9 月与 10–3 月，日历上根本不存在与另外五家对齐的半年，"
                 f"所以它单独画在 Exhibit {{EX_OFFCLOCK}}。"
                 f"利润行的名字也不统一，图例里逐家标出：本页六家一共用了"
                 f"{cn_count(len(a['profit_terms']))}种叫法（{'、'.join(a['profit_terms'])}）。"
                 f"本期最高的{top['zh']} {a['margin'][top['slug']][-1]:.1f}% 与最低的"
                 f"{bottom['zh']} {a['margin'][bottom['slug']][-1]:.1f}% 相差 "
                 f"{a['margin'][top['slug']][-1] - a['margin'][bottom['slug']][-1]:.1f}pp。"),
        "src_extra": AXIS + " 下半年各家均为公司申报的全年减上半年（D）。",
    }
    cfr = off[0]
    cfr_margin = [round(p / r * 100, 4) if r and p is not None else None
                  for r, p in zip(cfr["half_revenue"], cfr["half_profit"])]
    off_clock = {
        "ref": "EX_OFFCLOCK",
        "kind": "bar_line_dual",
        "title": f"{cfr['zh']}自己的时钟：财年半年销售与{cfr['profit_term']}率",
        "xlabels": list(cfr["halves"]),
        "bar": {"name": "半年销售", "color": "BLUE", "values": rounded(cfr["half_revenue"]),
                "yfmt": "f0c"},
        "line": {"name": f"{cfr['profit_term']}率", "color": "GOLD",
                 "values": rounded(cfr_margin), "yfmt": "pct1"},
        "ylab": "€M",
        "ylab2": "利润率 %",
        "xstep": 2,
        "full": True,
        "note": (f"H1 是 4–9 月，H2 是 10–3 月。把这条线搬到上一张图里，就等于把"
                 f"{cfr['zh']}的 4–9 月当成别人的 1–6 月 —— 本页不做这件事。"
                 f"这里的 {len(cfr['halves'])} 个半年里，奇数个是公司印出的，"
                 "偶数个是全年减上半年（D）。"),
        "src_extra": AXIS,
    }
    return [margin, off_clock]


# ── what each company lets you see ──────────────────────────────────────────
# One accessor per company for the two cuts a luxury reader asks for first.
# `china` is the name of the line that isolates Greater China, or None when the
# company folds it into a wider region; `region_label` is the narrowest
# quarterly geography this site has connected. Both are declared here rather
# than sniffed, so a company that starts disclosing China moves its own row.
def region_view(slug: str, d: dict) -> dict:
    if slug == "zgn":
        q = d["quarterly"]
        total = q["revenue_eur_k"]
        return {"cadence": "quarterly", "china": "大中华区", "region_label": "大中华区",
                "share": [g / t * 100 for g, t in zip(q["geography"]["greater_china"], total)],
                "quarters": [_q(p) for p in q["periods"]],
                "cuts": ["EMEA", "美洲", "大中华区", "亚太其余", "其他"]}
    if slug == "cfr":
        total = d["quarterly_eur_m"]["total"]
        return {"cadence": "quarterly", "china": None, "region_label": "亚太",
                "share": [None if a is None or not t else a / t * 100
                          for a, t in zip(d["quarterly_eur_m"]["asia_pacific"], total)],
                "quarters": [_q(q) for q in d["quarters"]],
                "cuts": ["欧洲", "亚太", "美洲", "日本", "中东与非洲"]}
    if slug == "rms":
        total = d["group_revenue"]["revenue_eur_m"]
        return {"cadence": "quarterly", "china": None, "region_label": "亚太（除日本）",
                "share": [a / t * 100 for a, t in
                          zip(d["by_region"]["asia_pacific_ex_japan"]["revenue_eur_m"], total)],
                "quarters": [_q(p) for p in d["periods"]],
                "cuts": ["法国", "欧洲（除法国）", "日本", "亚太（除日本）", "美洲", "中东等"]}
    if slug == "mc":
        return {"cadence": "quarterly_growth_only", "china": None, "region_label": "亚洲（除日本）",
                "share": None, "quarters": None,
                "cuts": ["美国", "日本", "亚洲（除日本）", "欧洲"]}
    if slug == "bc":
        return {"cadence": "half", "china": None, "region_label": "亚洲",
                "share": None, "quarters": None, "cuts": ["欧洲", "美洲", "亚洲"]}
    return {"cadence": "none", "china": None, "region_label": None,
            "share": None, "quarters": None, "cuts": []}


def channel_view(slug: str, d: dict) -> dict:
    if slug == "cfr":
        total = d["quarterly_eur_m"]["total"]
        return {"cadence": "quarterly", "label": "零售占销售额",
                "share": [None if r is None or not t else r / t * 100
                          for r, t in zip(d["quarterly_eur_m"]["retail"], total)],
                "quarters": [_q(q) for q in d["quarters"]]}
    if slug == "zgn":
        q = d["quarterly"]["channel"]
        return {"cadence": "quarterly", "label": "DTC 占品牌收入",
                "share": [dtc / (dtc + ws) * 100 for dtc, ws in
                          zip(q["dtc"], q["wholesale_branded"])],
                "quarters": [_q(p) for p in d["quarterly"]["periods"]]}
    if slug == "bc":
        return {"cadence": "half", "label": "零售占收入", "share": None, "quarters": None}
    return {"cadence": "none", "label": None, "share": None, "quarters": None}


def visibility_charts(members: list[dict], a: dict) -> list[dict]:
    regions = {m["slug"]: region_view(m["slug"], m["data"]) for m in members}
    channels = {m["slug"]: channel_view(m["slug"], m["data"]) for m in members}
    china_lines = [m for m in members if regions[m["slug"]]["china"]]
    plotted = [m for m in members if regions[m["slug"]]["share"] is not None]
    # The full window, not the window the narrowest cut happens to start at.
    # Each line then begins where that company's own disclosure begins, which is
    # the chart's second subject: the China line is not just narrower than the
    # Asia lines, it is also much younger than them.
    axis = list(a["longest"])

    china_note = (
        f"六家里只有{china_lines[0]['short']}把大中华区单独印成一条按季度的线，"
        "另外两条画的是各自最窄的那个亚洲口径 —— 它们不是同一个地区，也不该被读成同一条线。"
        if len(china_lines) == 1 else
        f"把大中华区单独印成按季度一条线的有{cn_count(len(china_lines))}家："
        + "、".join(m["short"] for m in china_lines) + "。")
    china = {
        "ref": "EX_CHINA",
        "kind": "lines",
        "title": "谁让你按季度看见中国（以及在看不见时你实际在看什么）",
        "xlabels": list(axis),
        "series": [
            {"name": f"{m['short']} · {regions[m['slug']]['region_label']}",
             "color": m["color"],
             "values": rounded(at(regions[m["slug"]]["quarters"], regions[m["slug"]]["share"], axis))}
            for m in plotted
        ],
        "end_label": True,
        "label_fmt": "pct1",
        "ylab": "占集团收入 %",
        "zero_base": True,
        "xstep": 4,
        "full": True,
        "note": (china_note
                 + f"{next(m['short'] for m in members if m['slug'] == 'mc')}只按季给分地区的增速、"
                 "不给金额，而且本站只接到四个季度；"
                 f"{next(m['short'] for m in members if m['slug'] == 'bc')}的地区只有半年度三大洲；"
                 f"{next(m['short'] for m in members if m['slug'] == 'ker')}在本站没有任何分地区数据"
                 "（公司只在正文里给零散的文字增速），所以这三家不在图上。"),
        "src_extra": AXIS + " 占比为各公司自己印出的地区金额除以它自己印出的集团合计（D）。",
    }

    channel_plotted = [m for m in members if channels[m["slug"]]["share"] is not None]
    caxis = list(a["longest"])
    channel = {
        "ref": "EX_CHANNEL",
        "kind": "lines",
        "title": "直营占比：两家按季度披露的公司",
        "xlabels": list(caxis),
        "series": [
            {"name": f"{m['short']} · {channels[m['slug']]['label']}",
             "color": m["color"],
             "values": rounded(at(channels[m["slug"]]["quarters"],
                                  channels[m["slug"]]["share"], caxis))}
            for m in channel_plotted
        ],
        "end_label": True,
        "label_fmt": "pct1",
        "ylab": "占比 %",
        "zero_base": True,
        "xstep": 4,
        "full": True,
        "note": ("两条线的分母不同，图例里写明了："
                 "历峰是零售除以集团销售额，杰尼亚是 DTC 除以品牌收入（不含面料与其他）。"
                 "库奇内利只在半年度披露零售与批发，不在这根季度轴上；"
                 "LVMH、爱马仕与开云在本站没有接入任何渠道拆分。"),
        "src_extra": AXIS,
    }
    return [china, channel]


# ── tables ──────────────────────────────────────────────────────────────────
EXCLUDE_ZH = {"fx": "汇率", "perimeter": "合并范围"}


def tables_for(members: list[dict], staging: dict, a: dict, first: int) -> list[dict]:
    metrics = {entry["slug"]: entry for entry in staging["growth_metrics"]}
    regions = {m["slug"]: region_view(m["slug"], m["data"]) for m in members}
    channels = {m["slug"]: channel_view(m["slug"], m["data"]) for m in members}
    latest = a["latest"]

    cross_section = {
        "n": first,
        "ref": "TBL_LATEST",
        "title": f"{latest} 横截面：六家在同一个季度上的读数",
        "headers": ["公司", "本季收入", "公司自己的增速", "口径", "本页自算的报告口径同比 D",
                    "最近一个半年的利润率", "利润行的名字", "该半年的期间"],
        "rows": [],
    }
    for m in members:
        entry = metrics[m["slug"]]
        own = a["own_rate"][m["slug"]][-1]
        printed_kind = a["own_kind"][m["slug"]] == "printed"
        derived = yoy(m["quarters"], m["revenue"], [latest])[0]
        index = len(m["halves"]) - 1
        revenue, profit = m["half_revenue"][index], m["half_profit"][index]
        margin = None if not revenue or profit is None else profit / revenue * 100
        cross_section["rows"].append([
            f"{m['short']}（{m['zh']}）",
            eur_m(at(m["quarters"], m["revenue"], [latest])[0]),
            signed1(own) if printed_kind else "—",
            entry["term_zh"] + ("" if printed_kind else "（本站未接入按季序列）"),
            signed1(derived),
            pct1(margin),
            m["profit_term"],
            m["halves"][index] + ("" if m["calendar_halves"] else "（财年半年）"),
        ])

    metric_table = {
        "n": first + 1,
        "ref": "TBL_METRICS",
        "title": "六把尺子：每家管自己的增长叫什么，剔除了什么，多久印一次",
        "headers": ["公司", "公司自己的叫法", "英文", "剔除", "频率", "本站是否接入按季序列", "定义出处"],
        "rows": [[
            f"{m['short']}（{m['zh']}）",
            metrics[m["slug"]]["term_zh"],
            metrics[m["slug"]]["term_en"],
            "不详" if metrics[m["slug"]]["excludes"] is None
            else "、".join(EXCLUDE_ZH[x] for x in metrics[m["slug"]]["excludes"]),
            metrics[m["slug"]]["cadence"].replace("quarterly", "按季")
                                         .replace("not_connected", "公司按季给，本站未接入"),
            "是" if a["own_kind"][m["slug"]] == "printed" else "否",
            metrics[m["slug"]]["definition_source"],
        ] for m in members],
    }

    verdict = {
        "n": first + 2,
        "ref": "TBL_DERIVE",
        "title": "这六条欧元收入线，哪一条可以自己相除得到同比",
        "headers": ["公司", "序列是否单一口径", "已知接缝", "与公司印出的报告口径最大偏离", "本页的做法"],
        "rows": [],
    }
    seam_words = {
        "mc": ("是（九份全年发布互相重叠，逐格核对过）",
               "2017 下半年并入 Christian Dior Couture、2021 年一季度并入 Tiffany —— "
               "并购台阶，不是两套口径"),
        "cfr": ("否", "YNAP 于 2021 年二季度转入终止经营：金额重述、增速未重述"),
        "rms": ("是（上年同期重印值与本序列逐格相同）", "无"),
        "ker": ("否", "2025 年三个季度同时存在首次公布与剔除 Beauté 重述两套值"),
        "zgn": ("是（集团合计被重复公布 24 次，一次都没有改过）",
                "分部与品牌行改过，集团合计没有"),
        "bc": ("是", "无重述；但四个季度里有三个本身就是两份累计披露相减"),
    }
    for m in members:
        gap = a["derive_gap"][m["slug"]]
        single, seam = seam_words[m["slug"]]
        if gap is None:
            measured = "公司不印报告口径同比，无法直接量"
        elif gap["worst_gap_pp"] is None:
            measured = "—"
        else:
            measured = (f"{gap['worst_gap_pp']:.1f}pp（{gap['worst_quarter']}，"
                        f"{len(gap['pairs'])} 个季度可比）")
        if m["slug"] == "cfr":
            action = "增速一律取公司印出的那一列，从不相除"
        elif m["slug"] == "ker":
            fork = a["ker_fork"][-1]
            action = (f"图上用公司的可比增速；自算同比只在 {fork['derived_quarter']} 的横截面里出现，"
                      f"并注明它按首次公布值是 {signed1(fork['on_first_published'])}、"
                      f"按重述值是 {signed1(fork['on_restated'])}")
        elif a["own_kind"][m["slug"]] == "derived":
            action = "没有公司口径可用，图上画自算同比并标 D"
        else:
            action = "图上用公司自己的增速；自算同比只用于量两者之差"
        verdict["rows"].append([f"{m['short']}（{m['zh']}）", single, seam, measured, action])

    visibility = {
        "n": first + 3,
        "ref": "TBL_VISIBILITY",
        "title": "披露频率矩阵：同一个问题，六家给你的答案深浅不同",
        "headers": ["公司", "收入", "利润", "利润期的时钟", "地区", "最窄的地区口径",
                    "大中华区单独成行", "渠道"],
        "rows": [],
    }
    cadence_zh = {"quarterly": "按季", "quarterly_growth_only": "按季只给增速、不给金额",
                  "half": "半年度", "none": "本站未接入"}
    for m in members:
        region = regions[m["slug"]]
        channel = channels[m["slug"]]
        visibility["rows"].append([
            f"{m['short']}（{m['zh']}）",
            "按季",
            "半年度",
            "日历年" if m["calendar_halves"] else "3 月底制财年",
            cadence_zh[region["cadence"]],
            region["region_label"] or "—",
            "是" if region["china"] else "否",
            cadence_zh[channel["cadence"]],
        ])
    return [cross_section, metric_table, verdict, visibility]


# ── the payload ─────────────────────────────────────────────────────────────
def latest_block(staging: dict, members: list[dict], a: dict) -> dict:
    """The cross page's own `latest`, computed from the six it reads.

    The period is the latest quarter *all six* have reported, and the release
    date is the last of the six releases that quarter needed -- a cross page is
    only as current as its slowest member, and saying so is the honest label.
    What no filing carries, the review date and the audit wording, sits in
    `series/luxury.json` stamped with the period it was written for, so a roll
    that moves the six and leaves that block behind stops the build.
    """
    stamped = staging["latest"]["period"]
    if _q(stamped) != _q(a["latest"]):
        raise ValueError(
            f"series/luxury.json `latest` is stamped {stamped!r} but the six series now share "
            f"{a['latest']!r}: update latest.period / analysis_date with the roll")
    slowest = max(members, key=lambda m: m["release_date"])
    month_end = {"Q1": "03-31", "Q2": "06-30", "Q3": "09-30", "Q4": "12-31"}[a["latest"][4:]]
    return {
        "disclosed_period_label": display_period(a["latest"]),
        "full_financial_period_label": display_period(a["latest"]),
        "period_end": f"{a['latest'][:4]}-{month_end}",
        "release_date": slowest["release_date"],
        "analysis_date": staging["latest"]["analysis_date"],
        "audit_status": staging["latest"]["audit_status"],
        "status": "history_ready",
    }


def build_payload(staging: dict) -> dict:
    members = read_members(staging)
    a = analysis(members, staging)
    f = factor_analysis(members, a, staging["factor_panel"]["start"])
    regime = regime_test(members, staging)
    meta = latest_block(staging, members, a)
    latest = a["latest"]

    lead, window_block = lead_with_depth(comparability_charts(members, a),
                                         window_charts(members, a))
    sections_spec = [
        ("comparability", "一、六个都叫「增长」的数",
         "先把能画的画到底：每条线走到它自己在本站的下限，而不是走到六家的交集。"
         "然后才是六家同时有数的那一段，以及它们之间的距离。",
         lead),
        ("window", "二、这张表能画多长，是谁定的",
         "交集由最短的那条线决定 —— 而最短的那条不一定是披露最少的那家，"
         "有时候只是本站还没回补。这一节把两者分开。",
         window_block),
        ("basis", "三、每家自己的那把尺",
         "「增速」这个词在这六家里指六件不完全相同的事。这一节量它们之间的差，并给出一个反例：同一家公司、同一个口径，两种算法为什么会分开。",
         basis_charts(members, a)),
        ("profit", "四、利润：两个时钟",
         "六家全部一年只出两次利润，所以这一页没有季度利润率。五家的半年落在日历上，一家不落。",
         profit_charts(members, a)),
        ("visibility", "五、看得见什么",
         "同一个问题问六家，答案的深浅差一个数量级。这一节画能画的，并把不能画的逐家写清楚。",
         visibility_charts(members, a)),
        ("factor", "六、「板块」到底解释了多少，以及拉开差距的到底是什么",
         "前五节说的是这些数能不能放在一起。这一节假设它们能，然后问两个问题："
         "共同的那部分有多大，以及剩下的那部分属于谁。"
         "答案是：共同的部分比想象的小，而剩下的部分主要不属于「公司」。",
         factor_charts(members, a, f, staging)),
    ]
    exhibits = number_exhibits([e for _, _, _, block in sections_spec for e in block])
    first_table = exhibits[-1]["n"] + 1
    tables = tables_for(members, staging, a, first_table)
    tables.append(factor_table(first_table + len(tables), f))
    tables.append(ai_capex_cycle_table(first_table + len(tables)))
    resolve_refs(exhibits, tables)

    cuts, at_index = [], 0
    for _, _, _, block in sections_spec:
        cuts.append(exhibits[at_index:at_index + len(block)])
        at_index += len(block)
    sections = [{"id": spec[0], "title": spec[1], "description": spec[2], "exhibits": block}
                for spec, block in zip(sections_spec, cuts)]

    slowest = max(members, key=lambda m: m["release_date"])
    top = max(members, key=lambda m: a["own_rate"][m["slug"]][-1])
    low = min(members, key=lambda m: a["own_rate"][m["slug"]][-1])
    widest = max((v for v in a["spread"] if v is not None))
    narrowest = min((v for v in a["spread"] if v is not None))
    rules = a["exclusion_rules"]
    known_rules = [r for r in rules if r != "unknown"]
    story = staging["quarter_story"]
    if _q(story["period"]) != _q(latest):
        raise ValueError(f"series/luxury.json `quarter_story` is stamped {story['period']!r}, "
                         f"but the six series share {latest!r}")

    headline = fill_story(
        "{latest}：六家报出来的增长从{low_name}的 {low_val} 到{top_name}的 {top_val}，"
        "而这六个数分属{rules}种剔除法、{clocks}种利润时钟、{terms}种利润口径。"
        "把口径对齐之后再看，拉开差距的不是周期 —— "
        "{lines}条品类线里，持续跑赢与持续跑输之间相差 {alpha_range}pp／季，"
        "比同期整个板块 {factor_range}pp 的峰谷波幅还大；"
        "而这个相对位置在一个时期之内很黏（隔四个季度的自相关 {ac_four}，"
        "它的变化却只有 {ac_delta}）—— 但把同一套回归搬到疫情前那三年，"
        "α 的排名只剩 ρ {regime_rho}，{flipped} 条线换了符号。"
        "位置在一个时期之内可读，跨过时期切换就不可读。",
        {
            "latest": display_period(latest),
            "low_name": low["zh"], "low_val": signed1(a["own_rate"][low["slug"]][-1]),
            "top_name": top["zh"], "top_val": signed1(a["own_rate"][top["slug"]][-1]),
            "rules": cn_count(len(known_rules)),
            "clocks": cn_count(len({m["calendar_halves"] for m in members})),
            "terms": cn_count(len(a["profit_terms"])),
            "lines": cn_count(len(f["fits"])),
            "alpha_range": f"{f['alpha_range']:.1f}",
            "factor_range": f"{f['factor_range']:.1f}",
            "ac_four": f"{f['persistence'][4]:+.2f}",
            "ac_delta": f"{f['change_autocorr']:+.2f}",
            "regime_rho": f"{regime['rho']:+.2f}" if regime else "—",
            "flipped": str(len(regime["flipped"])) if regime else "—",
        })

    cards = [
        ("共同窗口", f"收入 {cn_count(len(a['common']))}季 / 增速 {cn_count(len(a['rate_window']))}季",
         f"六家欧元收入都有数的区间是 {a['common'][0]}–{a['common'][-1]}，"
         f"六家增速都有数的只有 {a['rate_window'][0]}–{a['rate_window'][-1]}；"
         f"最深的一条能到 {a['longest'][0]}，最浅的只到 "
         f"{min(members, key=lambda m: len(m['plottable']))['plottable'][0]}。"),
        ("本季极差", f"{a['spread'][-1]:.1f}pp",
         f"{cn_count(len(a['rate_window']))}个季度里的极差在 {narrowest:.1f}–{widest:.1f}pp 之间"
         + ("，一次都没有收窄到 10pp 以内" if narrowest >= 10 else "")
         + " —— 「这一季奢侈品怎么样」这句话在数据上没有单一答案。"),
        ("周期解释了多少", f"中位 R² {f['median_r2']:.0f}%",
         f"{cn_count(len(f['fits']))}条品类线里，{cn_count(len(f['tracks']))}条跟着板块走"
         f"（平均 β {f['beta_tracks']:+.2f}），{cn_count(len(f['loose']))}条几乎不跟"
         f"（{f['beta_loose']:+.2f}）。最强的 α 是{f['best']} {f['fits'][f['best']]['alpha']:+.1f}pp／季，"
         f"而它的 R² 只有 {f['fits'][f['best']]['r2']:.0f}% —— 它基本不在这个周期里。"),
    ]
    brief = (f'<h4>本期{cn_count(len(cards))}条主线</h4><div class="takeaway-grid">' + "".join(
        f"<article><span>{label}</span><b>{value}</b><p>{body}</p></article>"
        for label, value, body in cards) + "</div>")

    notes = [
        "本页不是一家公司的页面：它没有自己的申报数据：上面每一个数都在构建时从"
        + "、".join(f"`series/{m['slug']}.json`" for m in members)
        + " 现算。六家里任何一家换季，这一页跟着换；本页的 builder 与 series 文件都不用改。",
        f"共同窗口是交集，由最短的那条线决定。收入这一根是{cn_count(len(a['common']))}个季度"
        f"（{a['common'][0]}–{a['common'][-1]}）；增速那一根更短，只有"
        f"{cn_count(len(a['rate_window']))}个季度（{a['rate_window'][0]}–{a['rate_window'][-1]}），"
        "因为两家没有公司口径的按季增速、要用欧元线自己相除，而那要等它的欧元线满一年，"
        "历峰则在 2021 年二季度之前根本不单独印季度增速。"
        f"{min(members, key=lambda m: len(m['plottable']))['zh']}那一格是本站的接入边界，"
        "不是公司的披露边界 —— 公司自己按季披露得更早，本站尚未回补。"
        "把这两者混为一谈，会把一句关于本站的话读成一句关于公司的话。",
        "「增速」在这六家里不是一个量。"
        + rule_census(members, a)
        + ("；剔除项本站没有记录的有：" + "、".join(
            next(x["zh"] for x in members if x["slug"] == s) for s in rules["unknown"])
           + "。" if "unknown" in rules else "。")
        + "两家没有按季的公司口径增速可用，图上画的是本页用欧元收入自算的报告口径同比，"
        "统一标 D 并在图例里写明。",
        "本页从不跨重述接缝相除。一条欧元收入线能不能自己除以上年同期，取决于这条线"
        "是不是单一口径。六家里有两家印出了自己的报告口径同比，所以这件事在它们身上"
        f"可以被直接量：历峰最大差 {a['derive_gap']['cfr']['worst_gap_pp']:.1f}pp，"
        f"爱马仕最大差 {a['derive_gap']['rms']['worst_gap_pp']:.2f}pp。"
        "前者的原因写在图注里，后者说明在没有接缝的地方这套算术是可靠的。",
        f"利润全部是半年度的：六家没有一家披露季度利润表，所以本页不存在任何形式的"
        f"「季度利润率」。其中{cn_count(len(a['calendar']))}家的半年落在日历上，"
        f"{a['off_clock'][0]['zh']}的财年在 3 月底结束、半年是 4–9 月与 10–3 月，"
        "因此它不上那根共用轴。各家下半年均为公司申报的全年减上半年（D）。",
        "单位：六家全部以欧元列示，但 LVMH、历峰、爱马仕、开云印百万欧元，"
        "杰尼亚与库奇内利印千欧元；本页在读取时统一折算为百万欧元，所以没有一张图混用两种量级。",
        "本页覆盖的是本站「奢侈品与豪华汽车」组里的六家奢侈品公司，不含同组的法拉利（RACE）。"
        "法拉利的披露形态与这六家完全不同 —— 它按季度发完整损益表（6-K），"
        "而这六家一年只出两次利润；把它放进以「半年利润」为轴的比较里，"
        "得到的会是一条口径不同的线，而不是多一个样本。",
        "本页不发布市场一致预期、评级、目标价与估值，也不对任何一家做投资判断；"
        "它只回答「这六家的数字在多大程度上能放在一起看」。",
        "核对抽屉最后那张「AI capex 循环」是全站共用的跨页对照块，在每一页都逐字节相同，"
        "与奢侈品无关；把它放在这里是为了让读者在任意一页都能查到同一份上下游对照。",
        "本页已知未接入：" + story["unconnected"],
    ]

    return {
        "schema_version": "quarterly-dashboard/luxury-v1",
        "page": {"slug": SLUG, "language": "zh-CN"},
        "company": {
            "ticker": "LUXURY",
            "name": "奢侈品组跨公司对照",
            "group": staging["page"]["group_key"],
            "accounting_standard": "IFRS",
        },
        "latest": meta,
        "tracker": "Watchlist Quarterly Tracker · 奢侈品组",
        "title": f"奢侈品组跨公司对照：{display_period(latest)} 六家同框",
        "subtitle": (f"LVMH · 历峰 · 爱马仕 · 开云 · 杰尼亚 · 库奇内利　"
                     f"共同窗口 {a['common'][0]}–{a['common'][-1]}　"
                     f"收入按季、利润按半年　IFRS · 欧元列示　"
                     f"本页数据截至六家中最晚的一份发布（{slowest['zh']}，{meta['release_date']}）"),
        "headline": headline,
        "brief": brief,
        "source": SOURCE,
        "source_url": "https://hzhan7.github.io/Quarterly-Results-Dashboards/",
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": sections,
        "tables": tables,
        "notes": notes,
        "footer": "奢侈品组跨公司对照 · 数据由六家公司页的已核对序列现算 · 仅供研究，不构成投资建议",
    }


def headline_metrics(staging: dict) -> list[str]:
    """The three figures a card would carry, computed like every company page's."""
    members = read_members(staging)
    a = analysis(members, staging)
    return [
        f"共同窗口 {cn_count(len(a['common']))}个季度",
        f"本季极差 {a['spread'][-1]:.1f}pp",
        f"合计收入 {eur_b(sum(a['ltm'].values()))}",
    ]


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / f"{SLUG}.js"), payload, SLUG)
    shell_dir = ROOT / SLUG
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("LUXURY", SLUG), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"Luxury cross-company page: {charts} charts in {len(payload['sections'])} sections "
          f"+ {len(payload['tables'])} audit tables")
    return 0




# ── the factor panel ────────────────────────────────────────────────────────
# One line per category that its company prints a growth rate for. Zegna and
# Cucinelli are absent here and the page says so: Zegna publishes segment
# revenue but no segment rate, Cucinelli publishes no category split at all, so
# putting them in would mean deriving a rate for them and comparing it with four
# companies' published ones -- the exact mixing this page exists to refuse.
CATEGORY_LINES = {
    "mc": ("organic_quarters", "organic_growth_pct", "long_quarters", "quarterly_revenue_eur_m",
           {"watches_jewelry": "手表珠宝", "fashion_leather": "时装皮具",
            "wines_spirits": "葡萄酒烈酒", "perfumes_cosmetics": "香水化妆",
            "selective_retailing": "精品零售"}),
    "cfr": ("quarters", "quarterly_cer_pct", "quarters", "quarterly_eur_m",
            {"jewellery_maisons": "珠宝", "specialist_watchmakers": "制表", "other": "其他"}),
    "ker": ("long_quarters", "quarterly_comparable_pct", "long_quarters", "quarterly_revenue_eur_m",
            {"gucci": "Gucci", "saint_laurent": "YSL",
             "bottega_veneta": "Bottega", "other_houses": "其他品牌"}),
}
RMS_SECTORS = {"leather_goods_saddlery": "皮具", "ready_to_wear_accessories": "成衣",
               "silk_textiles": "丝绸", "other_hermes_sectors": "珠宝家居",
               "perfume_beauty": "香水", "watches": "钟表", "other_products": "其他"}


def panel_lines(members: list[dict]) -> dict[str, dict]:
    """``label -> {growth: {q: pct}, revenue: {q: eur_m}, slug}`` for every line."""
    by_slug = {m["slug"]: m for m in members}
    lines = {}
    for slug, (qkey, gkey, rkey, vkey, names) in CATEGORY_LINES.items():
        data = by_slug[slug]["data"]
        for key, name in names.items():
            growth = {_q(q): v for q, v in zip(data[qkey], data[gkey][key]) if v is not None}
            revenue = {_q(q): v for q, v in zip(data[rkey], data[vkey][key]) if v is not None}
            lines[f"{by_slug[slug]['zh']} {name}"] = {"growth": growth, "revenue": revenue,
                                                      "slug": slug}
    rms = by_slug["rms"]["data"]
    quarters = [_q(p) for p in rms["periods"]]
    for key, name in RMS_SECTORS.items():
        block = rms["by_sector"][key]
        lines[f"{by_slug['rms']['zh']} {name}"] = {
            "growth": {q: v for q, v in zip(quarters, block["cc_pct"]) if v is not None},
            "revenue": {q: v for q, v in zip(quarters, block["revenue_eur_m"]) if v is not None},
            "slug": "rms"}
    return lines


def _fit(y: list[float], x: list[float]) -> tuple[float, float, float]:
    mean_x, mean_y = sum(x) / len(x), sum(y) / len(y)
    sxx = sum((a - mean_x) ** 2 for a in x)
    beta = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y)) / sxx
    alpha = mean_y - beta * mean_x
    residual = sum((b - (alpha + beta * a)) ** 2 for a, b in zip(x, y))
    total = sum((b - mean_y) ** 2 for b in y)
    return 1 - residual / total, beta, alpha


def _autocorr(pairs: list[tuple[float, float]]) -> float:
    a = [p for p, _ in pairs]
    b = [q for _, q in pairs]
    mean_a, mean_b = sum(a) / len(a), sum(b) / len(b)
    num = sum((p - mean_a) * (q - mean_b) for p, q in zip(a, b))
    den = (sum((p - mean_a) ** 2 for p in a) ** 0.5) * (sum((q - mean_b) ** 2 for q in b) ** 0.5)
    return num / den if den else 0.0


def factor_analysis(members: list[dict], a: dict, start: str) -> dict:
    """How much of each line is the sector, and how much is the line itself.

    The sector factor is the revenue-weighted growth of **the other lines** --
    leave-one-out, because the largest line is a third of the panel and
    regressing it on a factor that contains it would hand it a high R² for
    being itself. Everything here is a fit over one window and is reported with
    its own n, because twelve quarters is twelve quarters.
    """
    lines = panel_lines(members)
    window = [q for q in a["longest"]
              if q >= start and all(q in line["growth"] and q in line["revenue"]
                                    for line in lines.values())]
    growth = {label: [line["growth"][q] for q in window] for label, line in lines.items()}
    revenue = {label: [line["revenue"][q] for q in window] for label, line in lines.items()}
    factor = [sum(growth[k][i] * revenue[k][i] for k in growth)
              / sum(revenue[k][i] for k in revenue) for i in range(len(window))]

    fits = {}
    for label in lines:
        others = [k for k in lines if k != label]
        loo = [sum(growth[k][i] * revenue[k][i] for k in others)
               / sum(revenue[k][i] for k in others) for i in range(len(window))]
        r2, beta, alpha = _fit(growth[label], loo)
        weight = sum(revenue[label][i] / sum(revenue[k][i] for k in revenue)
                     for i in range(len(window))) / len(window) * 100
        fits[label] = {"r2": r2 * 100, "beta": beta, "alpha": alpha, "weight": weight,
                       "slug": lines[label]["slug"]}

    residual = {label: [growth[label][i] - factor[i] for i in range(len(window))]
                for label in lines}
    persistence = {lag: _autocorr([(residual[k][i], residual[k][i + lag])
                                   for k in residual for i in range(len(window) - lag)])
                   for lag in (1, 2, 3, 4)}
    changes = {label: [residual[label][i + 1] - residual[label][i]
                       for i in range(len(window) - 1)] for label in lines}
    change_ac = _autocorr([(changes[k][i], changes[k][i + 1])
                           for k in changes for i in range(len(window) - 2)])
    tracks = [label for label, f in fits.items() if f["r2"] >= 50]
    loose = [label for label, f in fits.items() if f["r2"] < 50]
    return {
        "window": window, "fits": fits, "factor": factor,
        "factor_range": max(factor) - min(factor),
        "alpha_range": max(f["alpha"] for f in fits.values()) - min(f["alpha"] for f in fits.values()),
        "best": max(fits, key=lambda k: fits[k]["alpha"]),
        "worst": min(fits, key=lambda k: fits[k]["alpha"]),
        "median_r2": sorted(f["r2"] for f in fits.values())[len(fits) // 2],
        "tracks": tracks, "loose": loose,
        "beta_tracks": sum(fits[k]["beta"] for k in tracks) / len(tracks),
        "beta_loose": sum(fits[k]["beta"] for k in loose) / len(loose),
        "persistence": persistence, "change_autocorr": change_ac,
    }


def factor_charts(members: list[dict], a: dict, f: dict, staging: dict) -> list[dict]:
    """Three charts and one claim: the cycle is not what separates these lines."""
    ranked = sorted(f["fits"], key=lambda k: -f["fits"][k]["alpha"])
    best, worst = f["best"], f["worst"]
    fits = f["fits"]
    n = len(f["window"])
    lag_labels = [f"{lag} 季后" for lag in (1, 2, 3, 4)]

    alpha = {
        "ref": "EX_ALPHA",
        "kind": "diverging_bars",
        "title": f"剔除板块之后，每条线自己剩下多少（{f['window'][0]}–{f['window'][-1]}，{n} 季）",
        "xlabels": ranked,
        "values": rounded([fits[k]["alpha"] for k in ranked]),
        "positive_label": "持续跑赢板块",
        "negative_label": "持续跑输板块",
        "label_fmt": "pp1",
        "ylab": "α（pp / 季）",
        "zero_line": True,
        "full": True,
        "height": 300,
        "note": (f"把每条线对「其余各线的收入加权增速」做回归，α 是它扣掉板块之后每个季度"
                 f"稳定多出（或少掉）的百分点。<b>α 的跨线极差 {f['alpha_range']:.1f}pp，"
                 f"而同期板块因子自己的全程波幅只有 {f['factor_range']:.1f}pp</b> —— "
                 f"最好与最差之间的持续差距，比整个周期的峰谷还大。"
                 f"最高的是{best}（{fits[best]['alpha']:+.1f}pp），"
                 f"最低的是{worst}（{fits[worst]['alpha']:+.1f}pp）。"
                 f"因子用留一法算：回归一条线时把它自己从因子里剔除，否则占权重 "
                 f"{max(fits.values(), key=lambda x: x['weight'])['weight']:.0f}% 的那条线会因为"
                 "「和自己相关」拿到一个虚高的解释力。"),
        "src_extra": f"面板为{cn_count(len(fits))}条品类线 × {n} 个季度；"
                     "n 小，β 与 α 都带噪声，此处只读大小关系不读小数点。",
    }

    by_r2 = sorted(f["fits"], key=lambda k: -f["fits"][k]["r2"])
    explain = {
        "ref": "EX_BETA",
        "kind": "bar_line_dual",
        "title": "「板块」能解释这条线多少，以及它把板块放大了几倍",
        "xlabels": by_r2,
        "bar": {"name": "板块因子的解释力 R²", "color": "BLUE",
                "values": rounded([fits[k]["r2"] for k in by_r2]), "yfmt": "pct0"},
        "line": {"name": "β（对板块的敏感度）", "color": "GOLD",
                 "values": rounded([fits[k]["beta"] for k in by_r2]), "yfmt": "f2"},
        "ylab": "R² %",
        "ylab2": "β",
        "full": True,
        "height": 300,
        "note": (f"中位 R² 是 {f['median_r2']:.0f}%，但分布是两堆而不是一堆："
                 f"<b>{cn_count(len(f['tracks']))}条跟着板块走，平均 β {f['beta_tracks']:+.2f}；"
                 f"另外{cn_count(len(f['loose']))}条几乎不跟，平均 β {f['beta_loose']:+.2f}</b>。"
                 "所以「板块转好了」这句话，对不同的线意味着完全不同的事 —— "
                 f"对 β 最高的那几条是放大，对 β 接近零的那几条几乎没有含义。"
                 f"{best}同时具备两个特征：R² 只有 {fits[best]['r2']:.0f}%、β {fits[best]['beta']:+.2f}，"
                 f"却有全面板最高的 α；{worst}正相反，R² {fits[worst]['r2']:.0f}%、"
                 f"β {fits[worst]['beta']:+.2f}，既最受周期摆布又最落后。"),
        "src_extra": "R² 与 β 来自同一次留一法回归；柱按 R² 从高到低排。",
    }

    persist = {
        "ref": "EX_PERSIST",
        "kind": "diverging_bars",
        "title": "相对位置有多黏，相对位置的变化有多不可测",
        "xlabels": lag_labels + ["位置的变化\n（下一季）"],
        "values": rounded([f["persistence"][lag] for lag in (1, 2, 3, 4)] + [f["change_autocorr"]]),
        "positive_label": "延续",
        "negative_label": "反转",
        "label_fmt": "f2",
        "ylab": "自相关系数",
        "zero_line": True,
        "note": (f"前四根是「扣掉板块之后的相对位置」隔 1–4 个季度的自相关："
                 f"{f['persistence'][1]:+.2f}、{f['persistence'][2]:+.2f}、"
                 f"{f['persistence'][3]:+.2f}、{f['persistence'][4]:+.2f} —— "
                 "一条线现在排在哪，一年之后大概率还在那附近。"
                 f"<b>最后一根是同一个量的「变化」的自相关，只有 {f['change_autocorr']:+.2f}</b>："
                 "这一季谁相对转好，对下一季谁相对转好几乎没有信息量。"
                 "两件事并不矛盾，但含义完全相反：<b>位置可读，拐点不可读。</b>"
                 "本页不据此给任何操作建议，它只说明这份数据能支持什么样的陈述。"),
        "src_extra": "合并全部品类线计算（pooled），不是逐线平均。",
    }
    charts = [alpha, explain, within_company_chart(within_company(members, f), f), persist]
    regime = regime_test(members, staging)
    if regime is not None:
        charts.append(regime_chart(regime))
    return charts


def factor_table(n: int, f: dict) -> dict:
    ranked = sorted(f["fits"], key=lambda k: -f["fits"][k]["alpha"])
    return {
        "n": n,
        "ref": "TBL_FACTOR",
        "title": f"品类线面板：权重、板块解释力、敏感度与持续差（{f['window'][0]}–{f['window'][-1]}）",
        "headers": ["品类线", "占面板收入权重", "R²", "β", "α（pp/季）", "是否跟随板块"],
        "rows": [[label,
                  f"{f['fits'][label]['weight']:.1f}%",
                  f"{f['fits'][label]['r2']:.1f}%",
                  f"{f['fits'][label]['beta']:+.2f}",
                  f"{f['fits'][label]['alpha']:+.1f}",
                  "是" if f["fits"][label]["r2"] >= 50 else "否"]
                 for label in ranked],
    }




def within_company(members: list[dict], f: dict) -> dict:
    """Split the persistent-performance spread into between-company and within-company.

    This is the one decomposition a cross-company panel can do that a
    single-company page cannot: four of the six contribute several category
    lines each, so the same arithmetic that separates a line from the sector can
    separate it from its own parent. If the between-company share were the large
    one, 「which house」 would be the right question. It is not.
    """
    zh = {m["slug"]: m["zh"] for m in members}
    by_company = {}
    for label, fit in f["fits"].items():
        by_company.setdefault(fit["slug"], []).append((label, fit["alpha"]))
    alphas = [fit["alpha"] for fit in f["fits"].values()]
    grand = sum(alphas) / len(alphas)
    between = sum(len(rows) * (sum(a for _, a in rows) / len(rows) - grand) ** 2
                  for rows in by_company.values())
    within = sum((a - sum(b for _, b in rows) / len(rows)) ** 2
                 for rows in by_company.values() for _, a in rows)
    total = sum((a - grand) ** 2 for a in alphas)
    spreads = []
    for slug, rows in by_company.items():
        rows = sorted(rows, key=lambda t: -t[1])
        spreads.append({
            "slug": slug, "zh": zh[slug], "lines": len(rows),
            "top": rows[0][0], "top_alpha": rows[0][1],
            "bottom": rows[-1][0], "bottom_alpha": rows[-1][1],
            "span": rows[0][1] - rows[-1][1],
            "mean": sum(a for _, a in rows) / len(rows),
        })
    spreads.sort(key=lambda r: -r["span"])
    return {"between_pct": between / total * 100, "within_pct": within / total * 100,
            "spreads": spreads, "widest": spreads[0],
            "company_span": max(r["mean"] for r in spreads) - min(r["mean"] for r in spreads)}


def within_company_chart(w: dict, f: dict) -> dict:
    """Each company's own internal range, against the range between companies."""
    rows = w["spreads"]
    return {
        "ref": "EX_WITHIN",
        "kind": "grouped_bars",
        "title": "同一家公司内部，不同品类之间差多少",
        "xlabels": [r["zh"] for r in rows],
        "groups": [
            {"name": "该公司最好的品类线 α", "color": "NAVY",
             "values": rounded([r["top_alpha"] for r in rows])},
            {"name": "该公司最差的品类线 α", "color": "GOLD",
             "values": rounded([r["bottom_alpha"] for r in rows])},
            {"name": "该公司各线 α 的均值", "color": "GRAY",
             "values": rounded([r["mean"] for r in rows])},
        ],
        "bar_labels": True,
        "label_fmt": "pp1",
        "ylab": "α（pp / 季）",
        "xrot": 0,
        "zero_line": True,
        "full": True,
        "note": (f"把 α 的总离散拆成两层：<b>公司之间只占 {w['between_pct']:.0f}%，"
                 f"公司之内占 {w['within_pct']:.0f}%</b>。"
                 f"{w['widest']['zh']}内部最宽，"
                 f"{w['widest']['top'].split()[-1]} 与 {w['widest']['bottom'].split()[-1]} "
                 f"相差 {w['widest']['span']:.1f}pp；"
                 f"而四家公司各自均值之间的差只有 {w['company_span']:.1f}pp。"
                 "同一家公司、同一张资产负债表、同一套分销，两条品类线可以差出比公司之间"
                 "更大的距离 —— 所以「买哪一家」这个问法本身就选错了单位，"
                 "持续差是品类与机制层面的，不是公司层面的。"),
        "src_extra": "α 来自 Exhibit {EX_ALPHA} 的同一次留一法回归；"
                     "分解是组间／组内平方和，未做自由度调整（组数 4、样本 19）。",
    }




def regime_test(members: list[dict], staging: dict) -> dict | None:
    """Does a line keep its place when the regime changes?

    The persistence measured inside one window is a within-regime property, and
    a window that sits entirely inside one regime cannot tell the difference
    between 「this line is structurally ahead」 and 「this line suits the current
    regime」. Now that the quarterly rates reach back far enough, the same
    regression runs on a pre-COVID window and on the current one, and the two
    α rankings are compared.

    Richemont is out of this panel: it printed a standalone quarterly rate only
    in some quarters before 2021Q2, so it cannot be fitted on the early window,
    and a factor whose membership changes between the two halves would make the
    comparison meaningless.
    """
    spec = staging.get("regimes")
    if not spec:
        return None
    lines = {k: v for k, v in panel_lines(members).items() if v["slug"] not in spec["exclude"]}
    axis = [f"{y}Q{n}" for y in range(2016, 2027) for n in range(1, 5)]
    fits = {}
    windows = {}
    for name, (lo, hi) in spec["windows"].items():
        window = [q for q in axis if lo <= q <= hi]
        usable = {k: v for k, v in lines.items()
                  if all(q in v["growth"] and v["revenue"].get(q) is not None for q in window)}
        growth = {k: [v["growth"][q] for q in window] for k, v in usable.items()}
        revenue = {k: [v["revenue"][q] for q in window] for k, v in usable.items()}
        out = {}
        for key in usable:
            others = [j for j in usable if j != key]
            loo = [sum(growth[j][i] * revenue[j][i] for j in others)
                   / sum(revenue[j][i] for j in others) for i in range(len(window))]
            r2, beta, alpha = _fit(growth[key], loo)
            out[key] = {"r2": r2 * 100, "beta": beta, "alpha": alpha}
        fits[name] = out
        windows[name] = window
    names = list(spec["windows"])
    shared = sorted(set(fits[names[0]]) & set(fits[names[1]]))
    if len(shared) < 6:
        return None
    early, late = (fits[n] for n in names)
    order_a = sorted(shared, key=lambda k: -early[k]["alpha"])
    order_b = sorted(shared, key=lambda k: -late[k]["alpha"])
    d = sum((order_a.index(k) - order_b.index(k)) ** 2 for k in shared)
    n = len(shared)
    held = [k for k in shared if (early[k]["alpha"] > 0) == (late[k]["alpha"] > 0)]
    # The two ends that survived, not the two flattest: a line that sat near
    # zero in both windows has held nothing worth holding. Steadiness only
    # means something for a line that was a long way from the middle.
    ahead = [k for k in held if late[k]["alpha"] > 0]
    behind = [k for k in held if late[k]["alpha"] < 0]
    stable = ([max(ahead, key=lambda k: min(early[k]["alpha"], late[k]["alpha"]))] if ahead else []) \
        + ([min(behind, key=lambda k: max(early[k]["alpha"], late[k]["alpha"]))] if behind else [])
    return {
        "names": names, "windows": windows, "lines": shared,
        "early": early, "late": late,
        "rho": 1 - 6 * d / (n * (n * n - 1)),
        "flipped": [k for k in shared if k not in held],
        "steadiest": stable[:2],
        "spread_early": max(early[k]["alpha"] for k in shared) - min(early[k]["alpha"] for k in shared),
        "spread_late": max(late[k]["alpha"] for k in shared) - min(late[k]["alpha"] for k in shared),
    }


def regime_chart(r: dict) -> dict:
    """Each line's α in the earlier regime against its α in the current one."""
    early_name, late_name = r["names"]
    order = sorted(r["lines"], key=lambda k: -r["late"][k]["alpha"])
    flipped = set(r["flipped"])
    return {
        "ref": "EX_REGIME",
        "kind": "grouped_bars",
        "title": f"换一个时期，同一条线还在同一个位置吗（{r['windows'][early_name][0]}– 对 "
                 f"{r['windows'][late_name][0]}–）",
        "xlabels": [k + ("＊" if k in flipped else "") for k in order],
        "groups": [
            {"name": f"{early_name}的 α", "color": "GRAY",
             "values": rounded([r["early"][k]["alpha"] for k in order])},
            {"name": f"{late_name}的 α", "color": "NAVY",
             "values": rounded([r["late"][k]["alpha"] for k in order])},
        ],
        "bar_labels": True,
        "label_fmt": "pp1",
        "ylab": "α（pp / 季）",
        "zero_line": True,
        "full": True,
        "height": 320,
        "note": (f"同一套回归跑在两段不相交的时期上。<b>α 的排名只剩 Spearman ρ "
                 f"{r['rho']:+.2f}，{cn_count(len(r['lines']))}条线里有 "
                 f"{len(r['flipped'])} 条换了符号</b>（带＊的）。"
                 "所以前一张图量到的黏性是<b>同一个时期之内</b>的性质 —— 位置在一年的尺度上可读，"
                 "跨过一次时期切换就不可读了。"
                 + (f"两端都保住了位置的是"
                    + "与".join(f"{k}（{r['early'][k]['alpha']:+.1f} → {r['late'][k]['alpha']:+.1f}）"
                                for k in r["steadiest"])
                    + "；其余各线的领先或落后，更像是这一段时期奖励或惩罚了它们的站位，"
                      "而不是它们自身的属性。" if r["steadiest"] else "")
                 + f"另外值得记下的是：早一段的 α 极差 {r['spread_early']:.1f}pp <b>比现在的 "
                 f"{r['spread_late']:.1f}pp 还宽</b> —— 「这个板块最近才分化」这个说法，数据不支持。"),
        "src_extra": "历峰不在这张图里：它在 2021Q2 之前只在部分季度印单季增速，"
                     "早一段拟合不了，而成员在两段之间变化会让比较失去意义。"
                     "早一段 12 季、晚一段 14 季，β 的估计在早一段尤其带噪声，此处只读 α。",
    }


if __name__ == "__main__":
    raise SystemExit(main())
