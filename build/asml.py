"""ASML Holding N.V. quarterly dashboard.

ASML is a Dutch lithography-system maker listed on Euronext Amsterdam and NASDAQ.
It reports under US GAAP in euro on a calendar fiscal year whose quarters close on
the Sunday nearest the quarter end, and it is a foreign private issuer: the annual
report is a 20-F and every quarterly release is furnished on 6-K. Each quarterly
6-K carries the same four documents -- a press release (EX-99.1), an investor
presentation whose slides are images (EX-99.2), a US GAAP statement exhibit with a
five-quarter trend (EX-99.3), and in July the statutory interim report -- so the
whole record back to 2016 is on EDGAR, and every quarter on this page was printed
by the company up to five times.

**Three structural facts shape the page.**

First, the quarterly statements carry two basis changes the company never
reconciled quarter by quarter. Metrology and inspection moved from service into
system sales on 1 January 2017 (the 2016 quarters were reprinted that way, and
this page uses the reprint). ASC 606 arrived on 1 January 2018 and the 2017
quarters were never restated: FY2017 was restated in the FY2018 20-F, not in any
quarterly exhibit. The quarterly charts therefore mark 2018Q1 as a break.

Second, the mix data comes at two resolutions with two different bases. The
slides give quarterly *percentages* of net system sales by technology, end use
and ship-to region; the 20-F and interim report give absolute *euro* figures, and
their region table is total net sales by the location of the customer's fab. The
page never puts the two region bases on one chart.

Third, quarterly bookings stopped after 2025Q4. The Q1 2026 release simply drops
the row from its table, its slides and its statement exhibit; no filing on EDGAR
says why. Year-end backlog is printed instead.

**The page runs in the site's four sections** (TSM is the reference): what last
quarter set up and this quarter settled -- the local report's follow-up list, its
quantified thresholds, and the company's own guidance record -- then this
quarter's findings, then the thresholds the current local report sets for the
next quarter, then the long series. The thresholds are research settings copied
from the reports' watch lists (series blocks `prior_kpi_settlement` / `next_kpi`);
the value each one is measured against is computed here from the series, never
typed next to it.

**A roll edits `series/asml.json` and nothing else** (CLAUDE.md §9). Every period,
count and figure on the page is computed from the series; every sentence that
states something the data could stop saying is printed only while the data says
it. Published figures are company-reported or transparent arithmetic (D).
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
    fill_story,
    headroom,
    headroom_exhibit,
    latest_block,
    minus_sign,
    number_exhibits,
    stamped_block,
    threshold_exhibit,
    threshold_table,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402

STAGING_PATH = ROOT / "series" / "asml.json"
DATA_DIR = ROOT / "data"

SRC_STATEMENTS = ("取自各季 6-K 的 US GAAP 报表附件（EX-99.3）；每个季度都取公司最后一次印出的口径，"
                  "与首次印出不同的格列在核对抽屉里。")
SRC_RELEASE = "取自各季 6-K 的业绩新闻稿（EX-99.1）与投资者演示（EX-99.2）的 Outlook 页。"
SRC_SLIDES = ("取自各季 6-K 投资者演示（EX-99.2）的「Net system sales breakdown」页，"
              "该页是图片，百分比按公司印出的整数读取；每季都被下一季的演示重印一次，两次读数逐格相符。")
SRC_20F = "取自各年 20-F 的分技术、分终端、分地区收入表；2016、2017 两年取 FY2018 20-F 按 ASC 606 重述后的比较列。"

TECH_GROUPS = [("EUV", ("EUV",), "NAVY"), ("ArF 浸没式", ("ArFi",), "MBLUE"),
               ("ArF 干式、KrF、I-line", ("ArF_dry", "KrF", "I_line"), "BLUE"),
               ("量测与检测", ("MI",), "GRAY")]
REGION_GROUPS = [("中国大陆", ("China",), "RED"), ("台湾", ("Taiwan",), "NAVY"),
                 ("韩国", ("South_Korea",), "MBLUE"), ("美国", ("United_States",), "BLUE"),
                 ("其他", ("Japan", "Singapore", "Rest_of_Asia", "Netherlands", "EMEA"), "GRAY")]


# ── small helpers ────────────────────────────────────────────────────────────
def pct(current: float, base: float) -> float:
    return (current / base - 1) * 100.0


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return minus_sign(f"{value:+.{digits}f}{suffix}")


def num(value: float, digits: int = 1) -> str:
    return minus_sign(f"{value:.{digits}f}")


def rounded(values, digits: int = 6):
    return [None if v is None else round(v, digits) for v in values]


def eur_m(value: float, digits: int = 1) -> str:
    """Euro millions, the unit of the company's statement exhibit (one decimal)."""
    return f"{'−' if value < 0 else ''}€{abs(value):,.{digits}f}M"


def eur_b(value: float, digits: int = 1) -> str:
    return f"{'−' if value < 0 else ''}€{abs(value) / 1000:,.{digits}f}B"


def guide_b(value: float, decimals: int) -> str:
    """A guided euro amount the way the company prints it: €9.0 billion -> '9.0'."""
    return f"{value / 1000:.{decimals}f}"


def guide_decimals(block: dict) -> int:
    """The company writes "€8.4 billion and €9.0 billion" but "€43 billion and €45 billion";
    the decimals follow its own sentence, so the page never prints "€8.4–9B"."""
    text = block.get("verbatim") or ""
    if re.search(r"\d\.\d+\s*billion", text):
        return 1
    return 0 if all(float(v) / 1000 == int(float(v) / 1000) for v in (block["low"], block["high"])) else 1


def guide_range(block: dict, unit: str = "B") -> str:
    if unit == "B":
        k = guide_decimals(block)
        lo, hi = guide_b(block["low"], k), guide_b(block["high"], k)
        return f"约 €{lo}B" if block["low"] == block["high"] else f"€{lo}–{hi}B"
    lo, hi = f"{block['low']:g}", f"{block['high']:g}"
    return f"约 {lo}%" if block["low"] == block["high"] else f"{lo}–{hi}%"


def quarter_cn(label: str) -> str:
    """``2026Q2`` -> ``2026 年第二季度``."""
    return f"{label[:4]} 年第{cn_ordinal(int(label[5]))}季度"


def resolve_exhibit_refs(exhibits: list[dict]) -> list[dict]:
    """Replace ``{EX_NAME}`` placeholders with the numbers assigned at render."""
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


def since_phrase(values: list[float | None], labels: list[str], *, higher: bool = True) -> str | None:
    """Where the last value sits in its own record, in words.

    "N 季里最高" when nothing before it reaches it; "P 以来最高" naming the last
    earlier point that reached it; None when the last value is not a new local
    extreme (the previous point already beat it), so no sentence is printed.
    """
    last = values[-1]
    if last is None:
        return None
    word = "最高" if higher else "最低"
    beats = (lambda v: v >= last) if higher else (lambda v: v <= last)
    earlier = [i for i in range(len(values) - 1) if values[i] is not None and beats(values[i])]
    if not earlier:
        return f"{cn_count(sum(1 for v in values if v is not None))}个季度里{word}"
    j = earlier[-1]
    if j == len(values) - 2:
        return None
    return f"{labels[j]} 以来{word}"


def year_list(P: list[str]) -> list[int]:
    return sorted({int(p[:4]) for p in P})


def year_sum(q: dict, key: str, year: int) -> float | None:
    P = q["periods"]
    cells = [q[key][P.index(f"{year}Q{n}")] if f"{year}Q{n}" in P else None for n in range(1, 5)]
    return None if any(c is None for c in cells) else sum(cells)


def complete_years(P: list[str]) -> list[int]:
    return [y for y in year_list(P) if all(f"{y}Q{n}" in P for n in range(1, 5))]


# ── guidance settlement ──────────────────────────────────────────────────────
ACTUAL_KEY = {"sales": "total_net_sales", "gross_margin": "gross_margin_printed_pct",
              "ibm": "ibm_sales"}


def settlement(s: dict, metric: str) -> dict:
    """For every quarter on the axis: the guidance given for it, the reported value,
    and where the second fell against the first.

    A single "around" figure is scored as a range of width zero: above it is above,
    below it is below. That is stricter than the word "around", and the page says so.
    """
    q = s["quarterly"]
    P = q["periods"]
    by_q = {g["guided_quarter"]: g for g in s["guidance"]}
    rows = []
    for i, p in enumerate(P):
        g = by_q.get(p)
        block = g.get(metric) if g else None
        actual = q[ACTUAL_KEY[metric]][i]
        if block is None:
            rows.append({"quarter": p, "guided": False, "withdrawn": bool(g and g.get("withdrawn")),
                         "actual": actual})
            continue
        lo, hi = block["low"], block["high"]
        mid = (lo + hi) / 2
        where = "above" if actual > hi else "below" if actual < lo else "in"
        rows.append({"quarter": p, "guided": True, "withdrawn": False, "form": block["form"],
                     "low": lo, "high": hi,
                     "mid": mid, "actual": actual, "where": where, "filed": g["filed"],
                     "verbatim": block.get("verbatim"),
                     "dev_pct": pct(actual, mid), "dev_pp": actual - mid})
    return {"rows": rows, "guided": [r for r in rows if r["guided"]]}


def verdict_words(guided: list[dict]) -> tuple[int, int, int]:
    return (sum(1 for r in guided if r["where"] == "above"),
            sum(1 for r in guided if r["where"] == "in"),
            sum(1 for r in guided if r["where"] == "below"))


def range_era_start(guided: list[dict]) -> str | None:
    """The first quarter after which every guidance was a range."""
    points = [i for i, r in enumerate(guided) if r["form"] != "range"]
    if not points:
        return guided[0]["quarter"] if guided else None
    k = points[-1] + 1
    return guided[k]["quarter"] if k < len(guided) else None


def fy_guidance(s: dict, year: int) -> list[dict]:
    """Every release's full-year euro sales guidance for `year`, in filing order."""
    out = []
    for g in s["guidance"]:
        for item in g["full_year"]:
            if item["year"] == year and item["metric"] == "total_net_sales" and item["unit"] == "eur_m":
                lo = item["low"] if item["low"] is not None else item["point"]
                hi = item["high"] if item["high"] is not None else item["point"]
                if lo is None or hi is None:
                    continue
                gm = next((it for it in g["full_year"] if it["year"] == year
                           and it["metric"] == "gross_margin_pct"), None)
                out.append({"filed": g["filed"], "reported_quarter": g["reported_quarter"],
                            "low": lo, "high": hi, "form": item["form"], "verbatim": item["verbatim"],
                            "gm_low": gm and (gm["low"] if gm["low"] is not None else gm["point"]),
                            "gm_high": gm and (gm["high"] if gm["high"] is not None else gm["point"])})
    return out


# ── section one: the quarter just reported ───────────────────────────────────
def period_charts(s: dict) -> list[dict]:
    q = s["quarterly"]
    P = q["periods"]
    year = int(P[-1][:4])
    exhibits = []

    path = fy_guidance(s, year)
    if path:
        mids = [(g["low"] + g["high"]) / 2 for g in path]
        moves = " → ".join(guide_range(g) for g in path)
        exhibits.append({
            "ref": "EX_FYPATH",
            "kind": "grouped_bars",
            "title": (f"{year} 年全年收入指引{cn_count(len(path))}次发布：{moves}"
                      + (f"，中值累计上移 {eur_b(mids[-1] - mids[0])}"
                         if len(path) > 1 and mids[-1] != mids[0] else "")),
            "xlabels": [f"{g['filed']} 发布" for g in path],
            "groups": [{"name": "指引下限", "color": "BLUE", "values": rounded([g["low"] for g in path])},
                       {"name": "指引上限", "color": "NAVY", "values": rounded([g["high"] for g in path])}],
            "bar_labels": True,
            "fmt": "f0c", "label_fmt": "f0c", "yfmt": "f0c",
            "ylab": "€M（全年总净销售）",
            "note": ("每一组是一份季度业绩发布里给出的全年总净销售区间。"
                     + ("同一组发布给的全年毛利率区间依次是 "
                        + " → ".join(f"{g['gm_low']:g}–{g['gm_high']:g}%" if g["gm_low"] != g["gm_high"]
                                     else f"约 {g['gm_low']:g}%" for g in path if g["gm_low"] is not None)
                        + "。" if any(g["gm_low"] is not None for g in path) else "")
                     + "下一张图把最新一次的区间换算成它对下半年的要求。"),
            "src_extra": SRC_RELEASE,
        })

    years = complete_years(P)
    ratio = {}
    for y in years:
        h1 = sum(q["total_net_sales"][P.index(f"{y}Q{n}")] for n in (1, 2))
        h2 = sum(q["total_net_sales"][P.index(f"{y}Q{n}")] for n in (3, 4))
        ratio[y] = pct(h2, h1)
    implied = None
    if f"{year}Q2" in P and f"{year}Q4" not in P and path:
        h1 = sum(q["total_net_sales"][P.index(f"{year}Q{n}")] for n in (1, 2))
        last = path[-1]
        implied = {"h1": h1, "low": pct(last["low"] - h1, h1), "mid": pct((last["low"] + last["high"]) / 2 - h1, h1),
                   "high": pct(last["high"] - h1, h1), "guide": last}
    labels = [str(y) for y in years] + ([f"{year} 指引隐含"] if implied else [])
    values = [ratio[y] for y in years] + ([implied["mid"]] if implied else [])
    if implied:
        higher = [y for y in years if ratio[y] > implied["mid"]]
        title = (f"{year} 年全年指引中值隐含下半年收入比上半年多 {num(implied['mid'])}%；"
                 f"过去{cn_count(len(years))}年里"
                 + (f"有{cn_count(len(higher))}年比这更高（"
                    + "、".join(f"{y} 年 {signed(ratio[y])}" for y in higher) + "）"
                    if higher else "没有一年比这更高"))
        note = (f"柱是每年下半年总净销售相对上半年的增幅，最后一根是 {year} 年上半年实际值 "
                f"{eur_m(implied['h1'])} 配上最新全年指引 {guide_range(implied['guide'])} 的中值（D）；"
                f"按区间两端算分别是 {signed(implied['low'])} 与 {signed(implied['high'])}。"
                f"过去{cn_count(len(years))}年里下半年比上半年多 30% 以上的有{cn_count(sum(1 for y in years if ratio[y] > 30))}年，"
                + (f"下半年少于上半年的有{cn_count(n_less)}年。"
                   if (n_less := sum(1 for y in years if ratio[y] < 0)) else "没有一年下半年少于上半年。")
                +
                "所以「指引严重后置」这句话本身说明不了多少，要看的是它离过去几年有多远。"
                + fourth_quarter_words(s))
    else:
        top = max(years, key=lambda y: ratio[y])
        title = (f"下半年相对上半年的收入增幅：{years[0]}–{years[-1]} 年里最高的是 {top} 年 "
                 f"{signed(ratio[top])}")
        note = "柱是每年下半年总净销售相对上半年的增幅（D）。本年上半年尚未走完或全年指引缺席时，不画隐含值。"
    exhibits.append({
        "ref": "EX_H2H1",
        "kind": "grouped_bars",
        "title": title,
        "xlabels": labels,
        "groups": [{"name": "下半年相对上半年 D", "color": "NAVY", "values": rounded(values, 1)}],
        "bar_labels": True,
        "fmt": "pct1", "label_fmt": "pct1", "yfmt": "pct1",
        "ylab": "下半年 / 上半年 − 1",
        "note": note,
        "src_extra": SRC_STATEMENTS + ("2016、2017 两年为 ASC 606 之前的口径，公司从未按季重述；"
                                       "比率是同一年内两半相比，不受跨年口径变化影响。"),
    })
    return exhibits


# ── section two: forty-odd quarters of guidance ──────────────────────────────
def guidance_charts(s: dict) -> list[dict]:
    q = s["quarterly"]
    P = q["periods"]
    out = []

    sales = settlement(s, "sales")
    g = sales["guided"]
    a, i_, b = verdict_words(g)
    era = range_era_start(g)
    era_rows = [r for r in g if era and r["quarter"] >= era]
    era_below = sum(1 for r in era_rows if r["where"] == "below")
    withdrawn = [r["quarter"] for r in sales["rows"] if r["withdrawn"]]
    last = sales["rows"][-1]
    beaten_by = [r for r in era_rows[:-1] if last["guided"] and r["dev_pct"] >= last["dev_pct"]]
    below_rows = [r for r in g if r["where"] == "below"]
    out.append({
        "ref": "EX_SALESDEV",
        "kind": "grouped_bars",
        "title": (f"总净销售对指引：给了指引的 {len(g)} 季里 {a} 季高于上限、{i_} 季落在区间内、"
                  f"{b} 季低于下限"),
        "xlabels": list(P),
        "xstep": 4,
        "groups": [{"name": "实际相对指引中值 D", "color": "NAVY",
                    "values": rounded([r["dev_pct"] if r["guided"] else None for r in sales["rows"]], 2)}],
        "bar_labels": False,
        "fmt": "pct1", "label_fmt": "pct1", "yfmt": "pct1",
        "ylab": "% vs 指引中值",
        "note": ("每根柱是该季实际总净销售相对上一份发布所给指引中值的偏离。"
                 "公司早年常只给一个「around」的单点，本图把单点当作宽度为零的区间来计分，"
                 "这比「around」这个词本身更严。"
                 + (f"{era} 起每一季都给区间，此后 {len(era_rows)} 季"
                    + ("没有一季低于下限。" if era_below == 0 else f"有 {era_below} 季低于下限。")
                    if era and len(era_rows) >= 8 else "")
                 + ("低于下限的是 " + "、".join(
                     f"{r['quarter']}（{signed(r['dev_pct'])}）" for r in below_rows) + "。"
                    if below_rows else "")
                 + "".join(f"{v['quarter']} 的指引在 {v['announced']} 另发公告改为 €{guide_b(v['low'], 1)}–"
                           f"{guide_b(v['high'], 1)}B，本图仍按原始指引结算。"
                           for v in s.get("guidance_revisions", []) if v["quarter"] in P)
                 + (f"{'、'.join(withdrawn)} 公司以新冠不确定性为由没有给指引，柱位留空。" if withdrawn else "")
                 + (f"本季 {signed(last['dev_pct'])}，"
                    + (f"是 {beaten_by[-1]['quarter']} 以来偏离最大的一次。" if beaten_by
                       else f"是 {era} 以来偏离最大的一次。")
                    if last["guided"] and last["where"] == "above" and era else "")),
        "src_extra": SRC_RELEASE + "实际值" + SRC_STATEMENTS,
    })

    gm = settlement(s, "gross_margin")
    g = gm["guided"]
    a, i_, b = verdict_words(g)
    below_rows = [r for r in g if r["where"] == "below"]
    last = gm["rows"][-1]
    out.append({
        "ref": "EX_GMDEV",
        "kind": "grouped_bars",
        "title": (f"毛利率对指引：{len(g)} 季里 {a} 季高于上限、{i_} 季落在区间内、{b} 季低于下限"),
        "xlabels": list(P),
        "xstep": 4,
        "groups": [{"name": "实际毛利率相对指引中值 D", "color": "MBLUE",
                    "values": rounded([r["dev_pp"] if r["guided"] else None for r in gm["rows"]], 2)}],
        "bar_labels": False,
        "fmt": "pp1", "label_fmt": "pp1", "yfmt": "pp1",
        "ylab": "pp vs 指引中值",
        "note": ("本图单位是百分点，与上一张的百分比不可直接比大小。"
                 "实际值取公司印到一位小数的毛利率，指引是公司印出的整数区间。"
                 + ("低于下限的是 " + "、".join(
                     f"{r['quarter']}（{signed(r['dev_pp'], 1, 'pp')}）" for r in below_rows) + "。"
                    if below_rows else "")
                 + (f"本季 {signed(last['dev_pp'], 1, 'pp')}。" if last["guided"] else "")),
        "src_extra": SRC_RELEASE + "实际值" + SRC_STATEMENTS,
    })

    ibm = settlement(s, "ibm")
    g = ibm["guided"]
    if g:
        a, i_, b = verdict_words(g)
        first = g[0]["quarter"]
        last = ibm["rows"][-1]
        out.append({
            "ref": "EX_IBMDEV",
            "kind": "grouped_bars",
            "title": (f"装机管理收入对指引：公司自 {first} 起给这条单点指引，{len(g)} 季里 "
                      + "、".join(f"{n} 季{w}" for n, w in ((a, "高于"), (i_, "恰好相等"), (b, "低于")) if n)),
            "xlabels": list(P),
            "xstep": 4,
            "groups": [{"name": "实际装机管理收入相对指引 D", "color": "GOLD",
                        "values": rounded([r["dev_pct"] if r["guided"] else None for r in ibm["rows"]], 2)}],
            "bar_labels": False,
            "fmt": "pct1", "label_fmt": "pct1", "yfmt": "pct1",
            "ylab": "% vs 指引",
            "note": ("装机管理（Installed Base Management）即公司报表里的服务与现场选配收入。"
                     f"这条指引只出现在投资者演示的 Outlook 页上，新闻稿正文里从来没有；{first} 之前的柱位留空，"
                     "因为公司那时不给。它一律是「around」的单点。"
                     + (f"本季实际 {eur_m(last['actual'])}，比指引多 {eur_m(last['actual'] - last['mid'])}"
                        f"（{signed(last['dev_pct'])}）。" if last["guided"] else "")),
            "src_extra": "指引取自各季投资者演示（EX-99.2）的 Outlook 页；实际值" + SRC_STATEMENTS,
        })
    return out


# ── section three: what is sold ──────────────────────────────────────────────
def deck_reconciliation(s: dict, key: str, techkey: str) -> dict:
    """Slide percentages (integers of net system sales) against the euro figures the
    20-F and the interim report print for the same periods -- two different documents.

    A quarter's integer share can be off by half a point, so the allowance for a
    period is half a percent of each quarter's net system sales, summed.
    """
    q, d = s["quarterly"], s["deck_mix"]
    P = q["periods"]
    out = {"years": [], "halves": []}
    for label, table, quarters_of in (
            ("years", s["annual_mix"], lambda y: [f"{y}Q{n}" for n in range(1, 5)]),
            ("halves", s["h1_mix"], lambda y: [f"{y}Q1", f"{y}Q2"])):
        for y in sorted(table):
            qs = quarters_of(int(y))
            if not all(p in P and d[key][P.index(p)] is not None for p in qs):
                continue
            euro = table[y]["technology_eur_m"].get(techkey)
            if euro is None:
                continue
            implied = sum(d[key][P.index(p)] / 100 * q["net_system_sales"][P.index(p)] for p in qs)
            allowance = sum(0.005 * q["net_system_sales"][P.index(p)] for p in qs)
            out[label].append({"period": y, "implied": implied, "printed": euro,
                               "gap": implied - euro, "allowance": allowance,
                               "ok": abs(implied - euro) <= allowance})
    return out


def half_year_euv_words(s: dict) -> str:
    """The interim report's euro EUV figure for the latest first half, beside the slide's percentages."""
    years = h1_years(s)
    if len(years) < 2:
        return ""
    now, before = s["h1_mix"][str(years[-1])], s["h1_mix"][str(years[-2])]
    share = lambda half: half["technology_eur_m"]["EUV"] / half["net_system_sales"] * 100  # noqa: E731
    exe_eur, exe_units = now["technology_eur_m"].get("EUV_EXE"), now["technology_units"].get("EUV_EXE")
    return (f"法定中期报告的金额：{years[-1]} 年上半年 EUV {eur_m(now['technology_eur_m']['EUV'])}，"
            f"占净系统销售 {num(share(now))}%（{years[-2]} 年上半年 {num(share(before))}%）"
            + (f"，其中高数值孔径 {exe_units} 台、{eur_m(exe_eur)}" if exe_eur and exe_units else "")
            + "。")


def structure_charts(s: dict, story: dict | None) -> list[dict]:
    q = s["quarterly"]
    P = q["periods"]
    share = [ibm / tot * 100 for ibm, tot in zip(q["ibm_sales"], q["total_net_sales"])]
    asc606 = P.index("2018Q1") if "2018Q1" in P else None
    rank = since_phrase(share, P)
    out = [{
        "ref": "EX_MIX",
        "kind": "stacked_dual",
        "title": (f"总净销售 = 系统 + 装机管理：本季装机管理占 {num(share[-1])}%"
                  + (f"，{rank}" if rank else "")),
        "xlabels": list(P),
        "xstep": 4,
        "stacks": [{"name": "净系统销售", "color": "NAVY", "values": rounded(q["net_system_sales"])},
                   {"name": "装机管理（服务与现场选配）", "color": "BLUE", "values": rounded(q["ibm_sales"])}],
        "line": {"name": "装机管理占总净销售 D（右轴）", "color": "GOLD", "values": rounded(share, 1),
                 "yfmt": "pct1", "ymax": 50},
        "fmt": "f0c", "label_fmt": "f0c", "yfmt": "f0c",
        "ylab": "€M（单季）", "ylab2": "占比 %",
        "break_at": asc606, "break_label": "ASC 606",
        "note": ("2016 年四个季度取 2017 年发布里的重印值：公司 2017 年起把量测与检测从服务收入挪进系统销售，"
                 "并按新口径重印了 2016 年，总额不变。"
                 "竖线处起按 ASC 606 列报；公司没有按季重述 2017 年，所以竖线两侧的季度不可逐格比较。"
                 f"右轴上界显式设在 50%，写在 line 里；本图的占比最高是 {num(max(share))}%。"),
        "src_extra": SRC_STATEMENTS,
    }]

    deck = s["deck_mix"]
    euv, arfi = deck["euv_pct"], deck["arfi_pct"]
    have = [i for i, v in enumerate(euv) if v is not None]
    if have:
        peak = max(have, key=lambda i: euv[i])
        first = have[0]
        rec = deck_reconciliation(s, "euv_pct", "EUV")
        yr_ok = sum(1 for r in rec["years"] if r["ok"])
        h_ok = sum(1 for r in rec["halves"] if r["ok"])
        misses = [r for r in rec["years"] + rec["halves"] if not r["ok"]]
        recon_words = (
            f"把每季的百分比乘回当季净系统销售、加总成全年，与 20-F 印出的 EUV 金额相比，"
            f"{cn_count(len(rec['years']))}个年份里{cn_count(yr_ok)}个落在整数舍入能解释的范围内；"
            f"加总成上半年与中期报告相比，{cn_count(len(rec['halves']))}个半年里{cn_count(h_ok)}个落在范围内"
            + ("，" + "、".join(f"{'上半年 ' if r in rec['halves'] else ''}{r['period']} 差 {eur_m(r['gap'])}"
                               f"（舍入可解释 {eur_m(r['allowance'])}）" for r in misses)
               if misses else "")
            + "。") if rec["years"] else ""
        out.append({
            "ref": "EX_EUVQ",
            "kind": "lines",
            "title": (f"EUV 占净系统销售：本季 {euv[-1]}%，最高是 "
                      + " 与 ".join(P[i] for i in have if euv[i] == euv[peak]) + f" 的 {euv[peak]}%"),
            "xlabels": list(P),
            "xstep": 4,
            "series": [{"name": "EUV 占净系统销售", "color": "NAVY", "values": list(euv)},
                       {"name": "ArF 浸没式占净系统销售", "color": "MBLUE", "values": list(arfi)}],
            "fmt": "pct0", "yfmt": "pct0", "label_fmt": "pct0",
            "zero_base": True, "end_label": True,
            "ylab": "% of 净系统销售",
            "note": ("公司在演示页上逐季印出按金额计的技术构成，精确到整数百分比；"
                     "单季的 EUV 收入确认取决于当季有几台完成验收，所以这条线逐季跳得很厉害，看趋势要看全年那张。"
                     + (f"{'、'.join(deck['no_euv_slice'])} 的饼图没有 EUV 一片、其余各片加总正好 100，本页记为 0。"
                        if deck.get("no_euv_slice") else "")
                     + recon_words
                     + half_year_euv_words(s)
                     + (f"{cn_count(len(P) - len(have))}个季度的演示页没有这项拆分，线在那里断开。"
                        if len(have) < len(P) else "")),
            "src_extra": SRC_SLIDES,
        })

    am = s["annual_mix"]
    years = sorted(am)
    stacks = []
    for name, keys, color in TECH_GROUPS:
        stacks.append({"name": name, "color": color,
                       "values": rounded([sum(am[y]["technology_eur_m"][k] or 0.0 for k in keys) for y in years])})
    euv_share = [am[y]["technology_eur_m"]["EUV"] / am[y]["net_system_sales"] * 100 for y in years]
    exe = [(y, am[y]["technology_eur_m"].get("EUV_EXE"), am[y]["technology_units"].get("EUV_EXE"))
           for y in years if am[y]["technology_eur_m"].get("EUV_EXE")]
    y0, y1 = years[0], years[-1]
    out.append({
        "ref": "EX_TECHY",
        "kind": "stacked_dual",
        "title": (f"全年净系统销售按技术：EUV 占比从 {y0} 年的 {num(euv_share[0])}% 升到 {y1} 年的 "
                  f"{num(euv_share[-1])}%，{y1} 年 EUV 收入 {eur_b(am[y1]['technology_eur_m']['EUV'])}"),
        "xlabels": years,
        "stacks": stacks,
        "line": {"name": "EUV 占净系统销售 D（右轴）", "color": "GOLD", "values": rounded(euv_share, 1),
                 "yfmt": "pct1", "ymax": 100},
        "fmt": "f0c", "label_fmt": "f0c", "yfmt": "f0c",
        "ylab": "€M（全年）", "ylab2": "EUV 占比 %",
        "note": ("EUV 含低数值孔径（NXE）与高数值孔径（EXE）两代机型。"
                 + (f"高数值孔径机型（EXE）自 {exe[0][0]} 年起单列："
                    + "；".join(f"{y} 年 {u} 台、{eur_m(v)}" for y, v, u in exe) + "。"
                    if exe else "")
                 + f"{y1} 年 EUV 共 {am[y1]['technology_units']['EUV']} 台，"
                 f"ArF 浸没式 {am[y1]['technology_units']['ArFi']} 台、{eur_b(am[y1]['technology_eur_m']['ArFi'])}。"
                 "全部为全年值：季度只有演示页上的百分比，没有金额。"),
        "src_extra": SRC_20F,
    })

    low_na = [(am[y]["technology_units"]["EUV"] or 0) - (am[y]["technology_units"].get("EUV_EXE") or 0)
              for y in years]
    arfi = [am[y]["technology_units"]["ArFi"] for y in years]
    labels = [str(y) for y in years]
    euv_bars, arfi_bars = list(low_na), list(arfi)
    cap = {c["tool"]: c for c in (story or {}).get("capacity", [])}
    euv_cap, duv_cap = cap.get("低数值孔径 EUV"), cap.get("DUV 浸没式")
    if euv_cap and duv_cap and euv_cap["base_year"] == duv_cap["base_year"]:
        by = euv_cap["base_year"]
        labels += [f"{by} 产能", f"{by + 1} 计划 D"]
        euv_bars += [euv_cap["base_units"], euv_cap["base_units"] * (1 + euv_cap["next_year_add_pct"] / 100)]
        arfi_bars += [duv_cap["base_units"], duv_cap["base_units"] * (1 + duv_cap["next_year_add_pct"] / 100)]
        same = euv_cap["next_year_add_pct"] == duv_cap["next_year_add_pct"]
        title = (f"{by} 年产能：低数值孔径 EUV 约 {euv_cap['base_units']} 台（{years[-1]} 年卖出 {low_na[-1]} 台），"
                 f"DUV 浸没式约 {duv_cap['base_units']} 台（{years[-1]} 年卖出 {arfi[-1]} 台）；"
                 + (f"{by + 1} 年两者各加 {euv_cap['next_year_add_pct']}%" if same else
                    f"{by + 1} 年分别加 {euv_cap['next_year_add_pct']}% 与 {duv_cap['next_year_add_pct']}%"))
        cap_words = (f"最后两组不是销售台数：「{by} 产能」是公司在 {story['release']} 的发布里说的年产能，"
                     f"「{by + 1} 计划」是按它说的 +{euv_cap['next_year_add_pct']}% 换算的（D）；"
                     f"公司还说 {by + 2} 年在研究再加 {euv_cap['year_after_add_pct_investigating']}%，"
                     "那是研究中的选项，本图不画。")
    else:
        title = (f"低数值孔径 EUV 与 ArF 浸没式的年销售台数：{years[-1]} 年分别 {low_na[-1]} 台与 {arfi[-1]} 台")
        cap_words = ""
    out.append({
        "ref": "EX_UNITSY",
        "kind": "grouped_bars",
        "title": title,
        "xlabels": labels,
        "groups": [{"name": "低数值孔径 EUV（NXE）", "color": "NAVY", "values": rounded(euv_bars, 1)},
                   {"name": "ArF 浸没式", "color": "MBLUE", "values": rounded(arfi_bars, 1)}],
        "bar_labels": True,
        "fmt": "f0", "label_fmt": "f0", "yfmt": "f0",
        "ylab": "台（全年）",
        "note": ("销售台数取 20-F 的分技术表；高数值孔径（EXE）另列，不计入这里的 EUV。"
                 "产能与销售不是同一个量：产能是一年能造多少台，销售是一年确认了多少台的收入。"
                 + cap_words),
        "src_extra": SRC_20F + ("产能取自当季新闻稿 CEO 陈述。" if cap_words else ""),
    })
    return out


# ── the interim report's first half, beside the slides' quarters ─────────────
H1_REGIONS = [("韩国", "South_Korea", "MBLUE"), ("台湾", "Taiwan", "NAVY"),
              ("中国大陆", "China", "RED"), ("美国", "United_States", "BLUE")]


def half_year_memory(s: dict) -> tuple[str, str]:
    """The interim report's memory figure for the latest first half: a title clause and
    a note sentence. Same denominator as the slide's percentage (net system sales)."""
    years = [y for y in h1_years(s) if (s["h1_mix"][str(y)].get("end_use_eur_m") or {}).get("Memory")]
    if not years:
        return "", ""
    shares = []
    for y in years:
        use = s["h1_mix"][str(y)]["end_use_eur_m"]
        shares.append(use["Memory"] / (use["Memory"] + use["Logic"]) * 100)
    rank = since_phrase(shares, [f"{y}H1" for y in years])
    latest = years[-1]
    now = s["h1_mix"][str(latest)]
    title = f"；{latest} 年上半年 {num(shares[-1])}%" + (f"（{rank}）" if rank else "")
    note = (f"法定中期报告按终端印出上半年金额：{latest} 年上半年 Memory {eur_m(now['end_use_eur_m']['Memory'])}、"
            f"Logic {eur_m(now['end_use_eur_m']['Logic'])}")
    before = s["h1_mix"].get(str(latest - 1), {})
    if (before.get("end_use_eur_m") or {}).get("Memory"):
        note += (f"，Memory 比 {latest - 1} 年上半年的 {eur_m(before['end_use_eur_m']['Memory'])} 多 "
                 f"{num(pct(now['end_use_eur_m']['Memory'], before['end_use_eur_m']['Memory']))}%")
        units_now, units_before = now.get("end_use_units"), before.get("end_use_units")
        if units_now and units_before:
            per = now["end_use_eur_m"]["Memory"] / units_now["Memory"]
            per_before = before["end_use_eur_m"]["Memory"] / units_before["Memory"]
            note += (f"；台数 {units_before['Memory']} → {units_now['Memory']}，平均每台 {eur_m(per_before)} → "
                     f"{eur_m(per)}（D）。台数里 EUV 与 DUV 混在一起，这个平均数反映的是机型组合，"
                     "不是同一台机器的价格")
    return title, note + "。"


def half_year_region_chart(s: dict) -> dict | None:
    """Total net sales by customer location, first half by first half (interim report)."""
    years = h1_years(s)
    if len(years) < 2:
        return None
    labels = [f"{y}H1" for y in years]
    shares = {key: [h1_share(s, y, key) for y in years] for _, key, _ in H1_REGIONS}
    latest = years[-1]
    now = s["h1_mix"][str(latest)]
    before = s["h1_mix"][str(latest - 1)] if latest - 1 in years else None
    top_name, top_key, _ = max(H1_REGIONS, key=lambda r: shares[r[1]][-1])
    top_rank = since_phrase(shares[top_key], labels)
    china_rank = since_phrase(shares["China"], labels, higher=False)
    moves = ""
    if before:
        moves = "；".join(
            f"{name} {eur_m(now['region_eur_m'][key])}，比 {latest - 1} 年上半年"
            f"{'多' if now['region_eur_m'][key] >= before['region_eur_m'][key] else '少'} "
            f"{num(abs(pct(now['region_eur_m'][key], before['region_eur_m'][key])))}%"
            for name, key, _ in H1_REGIONS[:3])
    return {
        "ref": "EX_REGIONH",
        "kind": "lines",
        "title": (f"上半年总净销售按客户所在地：{latest} 年上半年{top_name}占 {num(shares[top_key][-1])}%"
                  + (f"（{top_rank}）" if top_rank else "") + "，是最大的地区"
                  + (f"；中国大陆 {num(shares['China'][-1])}%" + (f"（{china_rank}）" if china_rank else "")
                     if top_key != "China" else "")),
        "xlabels": labels,
        "series": [{"name": name, "color": color, "values": [round(v, 1) for v in shares[key]]}
                   for name, key, color in H1_REGIONS],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1",
        "zero_base": True, "end_label": True,
        "ylab": "% of 总净销售（上半年）",
        "note": ("口径是法定中期报告的地区表：<b>总净销售、按客户工厂所在地</b>，与 20-F 的全年地区表相同；"
                 "第四节演示页的季度百分比是净系统销售、按发货地，两者不能互相核对。"
                 + (moves + "。" if moves else "")),
        "src_extra": SRC_INTERIM,
    }


def receivables_chart(s: dict, story: dict | None, conversion_ref: str | None) -> dict:
    """Receivables at quarter end against the quarter's sales, and the first half's cash.

    ``conversion_ref`` names the free-cash-flow threshold chart when section three
    draws one, so the note can point at the full-year outcome of past first halves.
    """
    q = s["quarterly"]
    P = q["periods"]
    year = int(P[-1][:4])
    ar, sales = q["accounts_receivable"], q["total_net_sales"]
    ratio = [a / t * 100 for a, t in zip(ar, sales)]
    level_rank = since_phrase(ar, P)
    ratio_rank = since_phrase(ratio, P)
    peak = max(range(len(P)), key=lambda i: ratio[i])
    idx = quarters_of_year(P, year)
    cash = year_to_date_cash(s)
    cfo, capex = cash["cfo"], cash["capex"]
    start = ar[P.index(f"{year - 1}Q4")] if f"{year - 1}Q4" in P else None
    factoring = (story or {}).get("factoring")
    asc606 = P.index("2018Q1") if "2018Q1" in P else None
    _, _, half = conversion_years(s)
    earlier_negative = [y for y in sorted(half) if half[y] < 0 and y != year]
    note = ((f"应收账款从 {year - 1} 年末的 {eur_m(start)} {'升' if ar[-1] >= start else '降'}到本季末的 "
             f"{eur_m(ar[-1])}。" if start is not None else "")
            + f"{year} 年{year_to_date_word(len(idx))}经营现金流 {eur_m(cfo)}，减去购置固定资产与无形资产 "
            f"{eur_m(-capex)}" + ("（公司印出的年初至今列）" if cash["printed"] else "（各季相加）")
            + f"，自由现金流 {eur_m(cfo + capex)}（D）"
            + (f"；上半年自由现金流为负此前出现过{cn_count(len(earlier_negative))}次"
               f"（{'、'.join(str(y) for y in earlier_negative)}）"
               + (f"，那几年全年的结果见 Exhibit {{{conversion_ref}}}" if conversion_ref else "")
               if len(idx) == 2 and cfo + capex < 0 and earlier_negative else "")
            + "。"
            + (f"法定中期报告附注写明：{factoring['half'][:4]} 年上半年"
               + ("没有" if not factoring["sold_eur_m"] else f"有 {eur_b(factoring['sold_eur_m'])} ")
               + f"应收账款以保理方式卖出，{int(factoring['half'][:4]) - 1} 年上半年是 "
               f"{eur_b(factoring['prior_half_sold_eur_m'])}；保理收到的现金计入经营活动现金流"
               "（中期报告按 EU-IFRS 编制）。" if factoring else "")
            + f"应收占当季收入的最高点是 {P[peak]} 的 {num(ratio[peak])}%。"
            "季度报表附件只单列非流动的合同负债"
            f"（本季末 {eur_m(q['contract_liabilities_noncurrent'][-1])}），流动部分并在流动负债合计里，"
            "所以客户预付款的变化这里看不全。竖线处起按 ASC 606 列报，2017 年未按季重述。")
    return {
        "ref": "EX_AR",
        "kind": "grouped_bars",
        "title": (f"应收账款季末 {eur_m(ar[-1])}" + (f"，{level_rank}" if level_rank else "")
                  + f"；相当于当季总净销售的 {num(ratio[-1])}%" + (f"，{ratio_rank}" if ratio_rank else "")),
        "xlabels": list(P),
        "xstep": 4,
        "groups": [{"name": "应收账款（季末）", "color": "NAVY", "values": rounded(ar)},
                   {"name": "当季总净销售", "color": "BLUE", "values": rounded(sales)}],
        "line": {"name": "应收 / 当季总净销售 D（右轴）", "color": "GOLD", "values": rounded(ratio, 1),
                 "yfmt": "pct0"},
        "bar_labels": False,
        "fmt": "f0c", "label_fmt": "f0c", "yfmt": "f0c",
        "ylab": "€M", "ylab2": "应收 / 当季收入 %",
        "break_at": asc606, "break_label": "ASC 606",
        "note": note,
        "src_extra": SRC_STATEMENTS + ("保理一句取自当年 7 月 6-K 所附法定中期报告的附注。" if factoring else ""),
    }


# ── section four: who buys, and where ────────────────────────────────────────
def customer_charts(s: dict) -> list[dict]:
    q = s["quarterly"]
    P = q["periods"]
    deck = s["deck_mix"]
    bk = s["bookings"]
    out = []

    mem = deck["memory_pct"]
    have = [i for i, v in enumerate(mem) if v is not None]
    book_mem = [bk["memory_pct"][bk["periods"].index(p)] if p in bk["periods"] else None for p in P]
    if have:
        rank = since_phrase([mem[i] for i in have], [P[i] for i in have])
        half_title, half_note = half_year_memory(s)
        out.append({
            "ref": "EX_MEMORY",
            "kind": "lines",
            "title": (f"存储芯片客户占净系统销售：本季 {mem[-1]}%"
                      + (f"，{rank}" if rank else "")
                      + half_title
                      + f"；最后一次公布的订单里占 {book_mem[P.index(bk['periods'][-1])]}%"),
            "xlabels": list(P),
            "xstep": 4,
            "series": [{"name": "Memory 占净系统销售", "color": "NAVY", "values": list(mem)},
                       {"name": "Memory 占净订单", "color": "GOLD", "values": book_mem}],
            "fmt": "pct0", "yfmt": "pct0", "label_fmt": "pct0",
            "zero_base": True, "end_label": True,
            "ylab": "Memory 占比 %",
            "note": ("两条线都是公司在演示页上印出的整数百分比。销售一线是当季确认收入的系统，"
                     "订单一线是当季新签的系统订单，两者不是同一批机器。"
                     f"订单一线停在 {bk['periods'][-1]}，因为公司此后不再公布季度订单。"
                     "2017 年底之前按 Memory / Foundry / IDM 三分，此后按 Memory / Logic 两分；"
                     "2017 年第四季度两种分法都印过，Foundry 加 IDM 恰好等于 Logic，Memory 一项两边相同。"
                     + half_note),
            "src_extra": SRC_SLIDES,
        })

    china, korea, taiwan = deck["china_pct"], deck["korea_pct"], deck["taiwan_pct"]
    have = [i for i, v in enumerate(china) if v is not None]
    if have:
        peak = max(have, key=lambda i: china[i])
        out.append({
            "ref": "EX_REGIONQ",
            "kind": "lines",
            "title": (f"净系统销售按发货地：中国大陆本季 {china[-1]}%"
                      + (f"（{low_rank}）" if (low_rank := since_phrase(list(china), P, higher=False)) else "")
                      + f"，最高是 {' 与 '.join(P[i] for i in have if china[i] == china[peak])} 的 {china[peak]}%；"
                      f"韩国 {korea[-1]}%、台湾 {taiwan[-1]}%"),
            "xlabels": list(P),
            "xstep": 4,
            "series": [{"name": "中国大陆", "color": "RED", "values": list(china)},
                       {"name": "韩国", "color": "MBLUE", "values": list(korea)},
                       {"name": "台湾", "color": "NAVY", "values": list(taiwan)}],
            "fmt": "pct0", "yfmt": "pct0", "label_fmt": "pct0",
            "zero_base": True, "end_label": True,
            "ylab": "% of 净系统销售",
            "note": ("口径是<b>净系统销售、按发货地</b>，与下一张 20-F 的「总净销售、按客户工厂所在地」不同，"
                     "两张图的数不能互相核对，也不画在一起。"
                     + (f"{'、'.join(over)} 的饼图把一个为负的地区排除在外，印出的百分比加总超过 100，"
                        "本页照印出值不做调整。" if (over := [p for p, r in zip(P, deck["region_pct"])
                                                         if r and sum(r.values()) > 100]) else "")),
            "src_extra": SRC_SLIDES,
        })

    am = s["annual_mix"]
    years = sorted(am)
    stacks = [{"name": name, "color": color,
               "values": rounded([sum(am[y]["region_eur_m"].get(k) or 0.0 for k in keys) for y in years])}
              for name, keys, color in REGION_GROUPS]
    china_share = [am[y]["region_eur_m"]["China"] / am[y]["total_net_sales"] * 100 for y in years]
    top = max(range(len(years)), key=lambda k: china_share[k])
    out.append({
        "ref": "EX_REGIONY",
        "kind": "stacked_dual",
        "title": (f"全年总净销售按客户所在地：中国大陆占比 {years[0]} 年 {num(china_share[0])}% → "
                  f"{years[top]} 年 {num(china_share[top])}% → {years[-1]} 年 {num(china_share[-1])}%"),
        "xlabels": years,
        "stacks": stacks,
        "line": {"name": "中国大陆占总净销售 D（右轴）", "color": "GOLD", "values": rounded(china_share, 1),
                 "yfmt": "pct1", "ymax": 100},
        "fmt": "f0c", "label_fmt": "f0c", "yfmt": "f0c",
        "ylab": "€M（全年）", "ylab2": "中国大陆占比 %",
        "note": ("20-F 的地区表按「客户工厂所在地」归属<b>总净销售</b>（含装机管理），"
                 "这是公司在每一份年报里写明的口径。「其他」合并日本、新加坡、亚洲其他、荷兰与 EMEA。"),
        "src_extra": SRC_20F,
    })
    return out


# ── section five: orders ─────────────────────────────────────────────────────
def order_charts(s: dict) -> list[dict]:
    q = s["quarterly"]
    P = q["periods"]
    bk = s["bookings"]
    BP = bk["periods"]
    nb = bk["net_bookings"]
    sys_sales = [q["net_system_sales"][P.index(p)] for p in BP]
    b2b = [n / v for n, v in zip(nb, sys_sales)]
    top = max(range(len(nb)), key=lambda k: nb[k])
    stopped = BP[-1] != P[-1]
    out = [{
        "ref": "EX_BOOK",
        "kind": "grouped_bars",
        "title": (f"净订单与净系统销售：最后一次公布的季度订单是 {BP[-1]} 的 {eur_m(nb[-1], 0)}"
                  + (f"，{cn_count(len(BP))}季里最高" if top == len(nb) - 1 else "")
                  + (f"；此后公司不再公布" if stopped else "")),
        "xlabels": list(BP),
        "xstep": 4,
        "groups": [{"name": "净订单", "color": "NAVY", "values": rounded(nb)},
                   {"name": "净系统销售", "color": "BLUE", "values": rounded(sys_sales)}],
        "line": {"name": "订单 / 系统销售 D（右轴）", "color": "RED", "values": rounded(b2b, 2), "yfmt": "f2"},
        "bar_labels": False,
        "fmt": "f0c", "label_fmt": "f0c", "yfmt": "f0c",
        "ylab": "€M（单季）", "ylab2": "订单 / 系统销售",
        "note": ("净订单是公司口径的系统订单（光刻机与量测检测），不含装机管理，所以分母取净系统销售。"
                 + (f"{BP[-1]} 之后的发布把「Net bookings」一行从新闻稿表格、演示页与报表附件里一并删掉，"
                    "连已公布过的上年同期比较列也一起删了。本页检索了 2024 年 10 月以来的季度发布（新闻稿、演示页、报表附件）、"
                    "两份年报与 2024 年投资者日的申报，没有一份说明原因。"
                    "取而代之的是年末积压订单，见下一张。" if stopped else "")),
        "src_extra": "净订单取自各季新闻稿表格，逐季与报表附件（EX-99.3）的同一行核对相符。",
    }]

    backlog = {}
    for e in s["backlog"]:
        if e["as_of"].endswith("-12-31") and e["eur_m"] is not None:
            backlog[int(e["as_of"][:4])] = e
    years = [y for y in year_list(P) if y <= max(backlog)]
    missing = [y for y in years if y not in backlog]
    last_y = max(backlog)
    out.append({
        "ref": "EX_BACKLOG",
        "kind": "bars_labeled",
        "title": (f"年末积压订单：{last_y} 年末 {eur_m(backlog[last_y]['eur_m'], 0)}"
                  + (f"；{'、'.join(str(y) for y in missing)} 年末公司没有印出"
                     if missing else "")),
        "xlabels": [str(y) for y in years],
        "values": [backlog[y]["eur_m"] if y in backlog else None for y in years],
        "fmt": "f0c", "label_fmt": "f0c", "yfmt": "f0c",
        "ylab": "€M（年末）",
        "note": ("积压订单只在部分时点被印出：到 2017 年第四季度为止每季都有，与新收入准则开始实施同时停止；"
                 "此后只有零星几个年末数。"
                 + (f"{'、'.join(str(y) for y in years if y in backlog and 'billion' in (backlog[y].get('printed') or ''))}"
                    " 年末的数公司只印到 0.1 十亿欧元。"
                    if any('billion' in (backlog[y].get('printed') or '') for y in backlog if y in years) else "")
                 + (f"{last_y} 年末的拆分是 "
                    + "、".join(f"{k} {v}%" for k, v in
                                ((backlog[last_y].get("split") or {}).get("end_use_pct") or {}).items())
                    + "。" if (backlog[last_y].get("split") or {}).get("end_use_pct") else "")),
        "src_extra": "取自各季新闻稿、演示页与 20-F 中印出积压订单的位置。",
    })
    return out


# ── section six: margins, cash and returns ───────────────────────────────────
def margin_cash_charts(s: dict) -> list[dict]:
    q = s["quarterly"]
    P = q["periods"]
    gm, om = q["gross_margin_printed_pct"], q["operating_margin_printed_pct"]
    asc606 = P.index("2018Q1") if "2018Q1" in P else None
    gm_rank, om_rank = since_phrase(gm, P), since_phrase(om, P)
    out = [{
        "ref": "EX_MARGIN",
        "kind": "lines",
        "title": (f"毛利率本季 {num(gm[-1])}%" + (f"（{gm_rank}）" if gm_rank else "")
                  + f"，经营利润率 {num(om[-1])}%" + (f"（{om_rank}）" if om_rank else "")),
        "xlabels": list(P),
        "xstep": 4,
        "series": [{"name": "毛利率", "color": "NAVY", "values": list(gm)},
                   {"name": "经营利润率", "color": "GOLD", "values": list(om)}],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1",
        "zero_base": True, "end_label": True,
        "ylab": "% of 总净销售",
        "break_at": asc606, "break_label": "ASC 606",
        "note": "两条线都取公司印到一位小数的比率，本页不自己重算。竖线处起按 ASC 606 列报，2017 年未按季重述。",
        "src_extra": SRC_STATEMENTS,
    }]

    cfo, ni = q["cfo"], q["net_income"]
    years = complete_years(P)
    q4_share = {y: cfo[P.index(f"{y}Q4")] / year_sum(q, "cfo", y) * 100 for y in years
                if year_sum(q, "cfo", y) and year_sum(q, "cfo", y) > 0}
    majority = [y for y, v in q4_share.items() if v > 50]
    negative = [p for p, v in zip(P, cfo) if v < 0]
    ly = years[-1]
    out.append({
        "ref": "EX_CFO",
        "kind": "grouped_bars",
        "title": (f"经营现金流按季大起大落：{ly} 年全年的 {num(q4_share[ly])}% 落在第四季度；"
                  + (f"{cn_count(len(q4_share))}年里每一年的第四季度都占到全年一半以上"
                     if len(majority) == len(q4_share) else
                     f"{cn_count(len(q4_share))}年里{cn_count(len(majority))}年第四季度占到全年一半以上")),
        "xlabels": list(P),
        "xstep": 4,
        "groups": [{"name": "经营活动现金流", "color": "NAVY", "values": rounded(cfo)},
                   {"name": "净利润", "color": "BLUE", "values": rounded(ni)}],
        "bar_labels": False,
        "fmt": "f0c", "label_fmt": "f0c", "yfmt": "f0c",
        "ylab": "€M（单季）",
        "note": ("净利润逐季相对平滑，经营现金流却集中在第四季度、随后几季回落甚至转负。"
                 "公司的新闻稿不解释这个季节性，本页也不替它解释；"
                 "要追的是它在资产负债表上的对应项，而季度报表附件的流动负债只印一个合计，"
                 "流动部分的合同负债不单列（单列的只有非流动部分）。"
                 + (f"经营现金流为负的季度有 {'、'.join(negative)}。" if negative else "")
                 + f"本季经营现金流 {eur_m(cfo[-1])}，净利润 {eur_m(ni[-1])}。"),
        "src_extra": SRC_STATEMENTS + "2017Q4–2018Q3 的现金流取 2019 年按 ASU 2016-15 重分类后的重印值。",
    })

    fcf, returned, div, bb = [], [], [], []
    for y in years:
        c = year_sum(q, "cfo", y)
        cap = year_sum(q, "capex_ppe", y) + year_sum(q, "capex_intangibles", y)
        fcf.append(c + cap)
        div.append(-year_sum(q, "dividends_paid", y))
        bb.append(-year_sum(q, "share_buybacks", y))
        returned.append(div[-1] + bb[-1])
    ratio = sum(returned) / sum(fcf) * 100
    out.append({
        "ref": "EX_RETURN",
        "kind": "grouped_bars",
        "title": (f"{years[0]}–{years[-1]} 年自由现金流合计 {eur_b(sum(fcf))}，"
                  f"分红与回购合计 {eur_b(sum(returned))}，相当于前者的 {num(ratio, 0)}%"),
        "xlabels": [str(y) for y in years],
        "groups": [{"name": "自由现金流 D", "color": "NAVY", "values": rounded(fcf)},
                   {"name": "分红", "color": "GOLD", "values": rounded(div)},
                   {"name": "回购", "color": "BLUE", "values": rounded(bb)}],
        "bar_labels": False,
        "fmt": "f0c", "label_fmt": "f0c", "yfmt": "f0c",
        "ylab": "€M（全年）",
        "note": ("自由现金流 = 经营活动现金流 − 购置固定资产 − 购置无形资产（D），均按四个季度相加。"
                 "分红与回购取现金流量表的实付额，不是宣告额。"),
        "src_extra": SRC_STATEMENTS,
    })
    return out


# ── thresholds the local reports set ─────────────────────────────────────────
# A report's watch list gives most metrics two levels: the one at which its
# reading is confirmed (its green or white row, "兑现线") and the one at which it
# turns to a warning (its red or orange row, "警戒线"). Both are thresholds the
# report wrote down, so both are drawn, and each keeps the verb that fits it:
# a confirmation level is reached or not, a warning level is held or broken.
LINE_COLOURS = {"兑现线": "GREEN", "警戒线": "RED"}
LINE_VERBS = {"兑现线": ("达到", "未达"), "警戒线": ("守住", "击穿")}
ONE_QUARTER_BLOCKS = ("quarter_story", "followup_closure", "prior_kpi_settlement", "next_kpi")
EURO_MEASURES = ("total_net_sales", "q4_sales_guide", "h1_buyback")
MEASURE_UNITS = {"total_net_sales": "eur_m", "q4_sales_guide": "eur_m", "h1_buyback": "eur_m",
                 "gross_margin": "pct", "china_share_h1": "pct", "fcf_conversion": "pct",
                 "interim_dividend_growth": "pct", "china_system_share": "pct"}
SRC_INTERIM = ("取自各年 7 月 6-K 所附法定中期报告的地区表（EU-IFRS；按客户工厂所在地归属总净销售）；"
               "占比是同一张表里的两个数相除，不受两套准则差异影响。")
MEASURE_SOURCES = {"total_net_sales": SRC_STATEMENTS, "gross_margin": SRC_STATEMENTS,
                   "fcf_conversion": SRC_STATEMENTS, "h1_buyback": SRC_STATEMENTS,
                   "china_share_h1": SRC_INTERIM, "china_system_share": SRC_SLIDES}


def shift_quarter(label: str, step: int) -> str:
    """``2026Q2`` shifted by ``+1`` -> ``2026Q3``."""
    year, quarter = int(label[:4]), int(label[5])
    index = year * 4 + quarter - 1 + step
    return f"{index // 4}Q{index % 4 + 1}"


def quarter_blocks(s: dict) -> dict:
    """Every one-quarter block, refusing one written for another quarter.

    `next_kpi` is required: the third section *is* the current report's watch
    list, and a roll that has not carried it over would publish an empty section.
    The two blocks that settle last quarter name the quarter that set them up,
    and that has to be the one before the series' last.
    """
    P = s["quarterly"]["periods"]
    period = display_period(P[-1])
    blocks = {key: stamped_block(s, key, period) for key in ONE_QUARTER_BLOCKS}
    if blocks["next_kpi"] is None:
        raise ValueError("series block `next_kpi` is required every quarter: it is the watch "
                         "list the page's third section draws")
    following = display_period(shift_quarter(P[-1], 1))
    if display_period(blocks["next_kpi"]["for_period"]) != following:
        raise ValueError(f"series block `next_kpi` is stamped for {blocks['next_kpi']['for_period']!r}, "
                         f"but the quarter after {period!r} is {following!r}")
    previous = display_period(shift_quarter(P[-1], -1))
    for key in ("followup_closure", "prior_kpi_settlement"):
        block = blocks[key]
        if block is not None and display_period(block["set_in"]) != previous:
            raise ValueError(f"series block `{key}` settles what {block['set_in']!r} set up, "
                             f"but the quarter before {period!r} is {previous!r}")
    return blocks


def quarters_of_year(P: list[str], year: int) -> list[int]:
    return [P.index(f"{year}Q{n}") for n in range(1, 5) if f"{year}Q{n}" in P]


def free_cash_flow(q: dict, idx: list[int]) -> float:
    """Operating cash flow less purchases of PP&E and intangibles (D); both capex lines are negative."""
    return sum(q["cfo"][i] + q["capex_ppe"][i] + q["capex_intangibles"][i] for i in idx)


def year_to_date_word(quarters: int) -> str:
    return {1: "第一季度", 2: "上半年", 3: "前三季度", 4: "全年"}[quarters]


def year_to_date_cash(s: dict) -> dict:
    """Operating cash flow and capex for the year so far: the company's own
    year-to-date column where the series carries it for this quarter, else the
    reported quarters summed (D). The two differ by rounding -- €0.1M on the first
    half of 2026 -- and the printed column is the official figure."""
    q = s["quarterly"]
    P = q["periods"]
    year = int(P[-1][:4])
    idx = quarters_of_year(P, year)
    printed = (s.get("half_year_cash_printed") or {}).get(str(year))
    if printed and printed["through"] == P[-1]:
        capex = printed["capex_ppe"] + printed["capex_intangibles"]
        return {"cfo": printed["cfo"], "capex": capex, "quarters": len(idx), "printed": True}
    return {"cfo": sum(q["cfo"][i] for i in idx),
            "capex": sum(q["capex_ppe"][i] + q["capex_intangibles"][i] for i in idx),
            "quarters": len(idx), "printed": False}


def h1_years(s: dict) -> list[int]:
    """Years whose first half is both in the quarterly series and in the interim-report table."""
    P = s["quarterly"]["periods"]
    return sorted(int(y) for y in s["h1_mix"] if f"{y}Q1" in P and f"{y}Q2" in P)


def h1_share(s: dict, year: int, region: str) -> float:
    half = s["h1_mix"][str(year)]
    return half["region_eur_m"][region] / half["total_net_sales"] * 100


def h1_buybacks(s: dict) -> dict[int, float]:
    """First-half purchases of treasury shares, as paid in the cash-flow statement."""
    q = s["quarterly"]
    P = q["periods"]
    return {y: -sum(q["share_buybacks"][P.index(f"{y}Q{n}")] for n in (1, 2))
            for y in year_list(P) if f"{y}Q1" in P and f"{y}Q2" in P}


def conversion_years(s: dict) -> tuple[list[int], dict[int, float], dict[int, float]]:
    """Free cash flow over net income (D), for every complete year and every first half."""
    q = s["quarterly"]
    P = q["periods"]
    full, half = {}, {}
    for y in year_list(P):
        idx = quarters_of_year(P, y)
        if len(idx) == 4:
            full[y] = free_cash_flow(q, idx) / sum(q["net_income"][i] for i in idx) * 100
        if len(idx) >= 2 and P[idx[1]] == f"{y}Q2":
            first = idx[:2]
            half[y] = free_cash_flow(q, first) / sum(q["net_income"][i] for i in first) * 100
    return year_list(P), full, half


def guided_sales(s: dict, quarter: str) -> dict | None:
    return next((g["sales"] for g in s["guidance"]
                 if g["guided_quarter"] == quarter and g.get("sales")), None)


def guided_margin(s: dict, quarter: str) -> dict | None:
    return next((g["gross_margin"] for g in s["guidance"]
                 if g["guided_quarter"] == quarter and g.get("gross_margin")), None)


def fourth_quarter_guide(s: dict) -> dict:
    """The fourth quarter's sales guide, or -- until the company gives one -- the one
    its full-year range implies: the range's midpoint less the quarters already
    reported and the midpoint of every quarter guided in between (D)."""
    q = s["quarterly"]
    P = q["periods"]
    year = int(P[-1][:4])
    q4 = f"{year}Q4"
    if q4 in P:
        raise ValueError(f"{q4} is already reported: a threshold on its guidance has nothing left to measure")
    guide = guided_sales(s, q4)
    if guide is not None:
        return {"value": (guide["low"] + guide["high"]) / 2, "implied": False, "guide": guide}
    path = fy_guidance(s, year)
    if not path:
        raise ValueError(f"no full-year {year} sales guidance to back the fourth quarter out of")
    fy_mid = (path[-1]["low"] + path[-1]["high"]) / 2
    reported = sum(q["total_net_sales"][i] for i in quarters_of_year(P, year))
    between, step = [], 1
    while (quarter := shift_quarter(P[-1], step)) < q4:
        guide = guided_sales(s, quarter)
        if guide is None:
            raise ValueError(f"no sales guidance for {quarter}: the {q4} the full-year range "
                             "implies cannot be backed out")
        between.append((quarter, (guide["low"] + guide["high"]) / 2))
        step += 1
    return {"value": fy_mid - reported - sum(mid for _, mid in between), "implied": True,
            "fy": path[-1], "fy_mid": fy_mid, "reported": reported, "between": between}


def fourth_quarter_words(s: dict) -> str:
    """The one quarter the full-year range leaves for the fourth, set against the
    largest quarter the page has drawn (D). Empty once the company guides it."""
    q = s["quarterly"]
    P = q["periods"]
    year = int(P[-1][:4])
    if f"{year}Q4" in P or not fy_guidance(s, year):
        return ""
    try:
        q4 = fourth_quarter_guide(s)
    except ValueError:
        return ""
    if not q4["implied"]:
        return ""
    top = max(range(len(P)), key=lambda i: q["total_net_sales"][i])
    record = q["total_net_sales"][top]
    lead = ("再按 " + "、".join(f"{p} 指引中值 €{m / 1000:g}B" for p, m in q4["between"]) + " 倒推"
            if q4["between"] else "再按已报告的季度倒推")
    return (f"{lead}，{year}Q4 一季要做 {eur_m(q4['value'])}（D），"
            + (f"比{cn_count(len(P))}个季度里最高的 {P[top]}（{eur_m(record)}）还高 {num(pct(q4['value'], record))}%。"
               if q4["value"] > record else
               f"没有超过{cn_count(len(P))}个季度里最高的 {P[top]}（{eur_m(record)}）。"))


def measure(s: dict, key: str) -> float:
    """The value a threshold is judged against, computed from the series."""
    q = s["quarterly"]
    P = q["periods"]
    year = int(P[-1][:4])
    if key == "total_net_sales":
        return q["total_net_sales"][-1]
    if key == "gross_margin":
        return q["gross_margin_printed_pct"][-1]
    if key == "q4_sales_guide":
        return fourth_quarter_guide(s)["value"]
    if key == "china_share_h1":
        return h1_share(s, h1_years(s)[-1], "China")
    if key == "fcf_conversion":
        idx = quarters_of_year(P, year)
        return free_cash_flow(q, idx) / sum(q["net_income"][i] for i in idx) * 100
    if key == "h1_buyback":
        if f"{year}Q2" not in P:
            raise ValueError(f"the first half of {year} is not reported yet")
        return h1_buybacks(s)[year]
    if key == "interim_dividend_growth":
        per_share = s["dividends_per_share_by_year"]
        return (per_share[str(year)]["interim"] / per_share[str(year - 1)]["interim"] - 1) * 100
    if key == "china_system_share":
        return s["deck_mix"]["china_pct"][-1]
    raise ValueError(f"unknown threshold measure {key!r}")


def measure_name(key: str, subject: str) -> str:
    """What a threshold is on, named for the quarter it is judged in."""
    names = {"total_net_sales": f"{subject} 总净销售", "gross_margin": f"{subject} 毛利率",
             "q4_sales_guide": f"{subject[:4]}Q4 收入指引", "china_share_h1": "中国大陆占总净销售",
             "fcf_conversion": "全年自由现金流 / 净利润", "h1_buyback": "上半年回购",
             "interim_dividend_growth": "每股中期股息增速", "china_system_share": "中国大陆占净系统销售"}
    if key not in names:
        raise ValueError(f"unknown threshold measure {key!r}")
    return names[key]


def measure_text(key: str, value: float) -> str:
    if key in EURO_MEASURES:
        return eur_m(value)
    if key == "china_system_share":
        return f"{value:g}%"
    return f"{num(value)}%"


def threshold_text(key: str, value: float) -> str:
    return f"€{value / 1000:g}B" if key in EURO_MEASURES else f"{value:g}%"


def threshold_entries(s: dict, block: dict, value_key: str, subject: str) -> list[dict]:
    """The block's thresholds, each with its value computed from the series.

    A typed value next to a threshold is where these blocks go wrong -- it can
    disagree with the series it claims to read -- so one is refused outright.
    """
    out = []
    for spec in block["quantified"]:
        for typed in ("actual", "current", "metric", "unit"):
            if typed in spec:
                raise ValueError(f"threshold on {spec['measure']!r} carries a typed {typed!r}; "
                                 "the builder derives it from the series")
        if spec["line"] not in LINE_COLOURS:
            raise ValueError(f"unknown threshold line {spec['line']!r}")
        out.append({**spec, "metric": f"{measure_name(spec['measure'], subject)}（{spec['line']}）",
                    "unit": MEASURE_UNITS[spec["measure"]],
                    value_key: measure(s, spec["measure"])})
    return out


def on_safe_side(entry: dict, value_key: str) -> bool:
    """At the precision the headroom bar prints: a reading on the line is not a breach."""
    return round(headroom(entry["direction"], entry["threshold"], entry[value_key]), 1) >= 0


def by_measure(entries: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for entry in entries:
        grouped.setdefault(entry["measure"], []).append(entry)
    return grouped


def measure_series(s: dict, key: str) -> dict | None:
    """The history a threshold is drawn against, or None where the measure has none."""
    q = s["quarterly"]
    P = q["periods"]
    asc606 = P.index("2018Q1") if "2018Q1" in P else None
    if key == "total_net_sales":
        return {"xlabels": list(P), "values": rounded(q["total_net_sales"]), "fmt": "f0c",
                "ylab": "€M（单季）", "name": "总净销售", "xstep": 4, "break_at": asc606}
    if key == "gross_margin":
        return {"xlabels": list(P), "values": list(q["gross_margin_printed_pct"]), "fmt": "pct1",
                "ylab": "% of 总净销售", "name": "毛利率（公司印出）", "xstep": 4, "break_at": asc606}
    if key == "china_system_share":
        return {"xlabels": list(P), "values": list(s["deck_mix"]["china_pct"]), "fmt": "pct0",
                "ylab": "% of 净系统销售", "name": "中国大陆占净系统销售（发货地）", "xstep": 4}
    if key == "china_share_h1":
        years = h1_years(s)
        return {"xlabels": [f"{y}H1" for y in years],
                "values": [round(h1_share(s, y, "China"), 1) for y in years], "fmt": "pct1",
                "ylab": "% of 总净销售", "name": "中国大陆占总净销售（上半年，客户所在地）"}
    if key == "h1_buyback":
        spent = h1_buybacks(s)
        years = sorted(spent)
        return {"xlabels": [f"{y}H1" for y in years], "values": rounded([spent[y] for y in years], 1),
                "fmt": "f0c", "ylab": "€M（上半年）", "name": "上半年回购（现金流量表实付）"}
    if key == "fcf_conversion":
        years, full, half = conversion_years(s)
        return {"xlabels": [str(y) for y in years],
                "values": [round(full[y], 1) if y in full else None for y in years], "fmt": "pct0",
                "ylab": "自由现金流 / 净利润 %", "name": "全年 D",
                "extra": [{"name": "上半年 D", "color": "GOLD",
                           "values": [round(half[y], 1) if y in half else None for y in years]}]}
    return None


def threshold_lines(s: dict, key: str, group: list[dict], title: str, note: str,
                    src_extra: str) -> dict | None:
    """One measure's history with every threshold the report set on it (`board.threshold_exhibit`,
    one flat line per threshold: green for a confirmation level, red for a warning level)."""
    spec = measure_series(s, key)
    if spec is None:
        return None
    chart = threshold_exhibit(title, spec["xlabels"], spec["values"], group[0]["threshold"],
                              fmt=spec["fmt"], ylab=spec["ylab"], actual_name=spec["name"],
                              threshold_name=group[0]["line"], note=note, src_extra=src_extra,
                              xstep=spec.get("xstep"))
    lines = [{"name": (f"{entry['line']} {threshold_text(key, entry['threshold'])}"
                       f"（安全侧在{'上方' if entry['direction'] == 'up' else '下方'}）"),
              "values": [entry["threshold"]] * len(spec["xlabels"]),
              "color": LINE_COLOURS[entry["line"]]}
             for entry in sorted(group, key=lambda e: e["threshold"])]
    chart["series"] = [chart["series"][0]] + spec.get("extra", []) + lines
    if spec.get("break_at") is not None:
        chart["break_at"] = spec["break_at"]
        chart["break_label"] = "ASC 606"
    return chart


def lines_phrase(key: str, group: list[dict]) -> str:
    return "、".join(f"{entry['line']} {threshold_text(key, entry['threshold'])}"
                    for entry in sorted(group, key=lambda e: e["threshold"]))


def next_note(s: dict, key: str, group: list[dict], following: str) -> str:
    """What the current reading of one next-quarter measure means, from the series."""
    q = s["quarterly"]
    P = q["periods"]
    year = int(P[-1][:4])
    lines = {entry["line"]: entry["threshold"] for entry in group}
    if key == "total_net_sales":
        now = q["total_net_sales"][-1]
        guide = guided_sales(s, following)
        top = max(range(len(P)), key=lambda i: q["total_net_sales"][i])
        above = [e for e in group if e["threshold"] > q["total_net_sales"][top]]
        text = f"当前值是本季实际 {eur_m(now)}。"
        if guide:
            mid = (guide["low"] + guide["high"]) / 2
            text += (f"{following} 的指引是 {guide_range(guide)}，本身就要求比本季多 "
                     f"{num(pct(guide['low'], now))}% 到 {num(pct(guide['high'], now))}%"
                     + ("；兑现线是这个区间的中值" if lines.get("兑现线") == mid else "")
                     + ("，警戒线是它的下限" if lines.get("警戒线") == guide["low"] else "") + "。")
        text += (f"{cn_count(len(P))}个季度里最高的单季是 {P[top]} 的 {eur_m(q['total_net_sales'][top])}"
                 + (f"，{cn_count(len(group))}条线都在它之上。" if len(above) == len(group)
                    else "。"))
        return text
    if key == "gross_margin":
        now = q["gross_margin_printed_pct"][-1]
        guide = guided_margin(s, following)
        target = lines.get("兑现线")
        reached = [P[i] for i, v in enumerate(q["gross_margin_printed_pct"])
                   if target is not None and v >= target]
        text = f"当前值是本季印出的 {num(now)}%。"
        if guide:
            text += (f"{following} 的毛利率指引是 {guide_range(guide, '%')}"
                     + ("，兑现线是它的下限" if target == guide["low"] else "") + "。")
        if target is not None:
            text += (f"{cn_count(len(P))}个季度里毛利率达到 {target:g}% 的季度"
                     + (f"有{cn_count(len(reached))}个（{'、'.join(reached)}）。" if reached
                        else "一个都没有。"))
        return text
    if key == "china_share_h1":
        latest = h1_years(s)[-1]
        half = s["h1_mix"][str(latest)]
        years = h1_years(s)
        target = lines.get("兑现线")
        over = [y for y in years if target is not None and h1_share(s, y, "China") >= target]
        return (f"当前值是 {latest} 年上半年法定中期报告的中国大陆占比 {num(h1_share(s, latest, 'China'))}%"
                f"（{eur_m(half['region_eur_m']['China'])} / {eur_m(half['total_net_sales'])}），"
                "口径是总净销售、按客户工厂所在地。季度没有这一口径：演示页的百分比是净系统销售、按发货地，"
                f"本季 {s['deck_mix']['china_pct'][-1]}%，两者不能互相核对。"
                + (f"{cn_count(len(years))}个上半年里到过兑现线的是 "
                   + "、".join(f"{y} 年（{num(h1_share(s, y, 'China'))}%）" for y in over) + "。"
                   if over else ""))
    if key == "fcf_conversion":
        years, full, half = conversion_years(s)
        idx = quarters_of_year(P, year)
        fcf = free_cash_flow(q, idx)
        income = sum(q["net_income"][i] for i in idx)
        guard = lines.get("警戒线")
        negative = [y for y in sorted(half) if half[y] < 0]
        settled = [y for y in negative if y in full]
        below = [y for y in sorted(full) if guard is not None and full[y] < guard]
        text = (f"当前值是 {year} 年{year_to_date_word(len(idx))}的比值：自由现金流 {eur_m(fcf)} / "
                f"净利润 {eur_m(income)}（D）。{cn_count(len(half))}个上半年里自由现金流为负的有"
                f"{cn_count(len(negative))}个（{'、'.join(str(y) for y in negative)}）")
        if settled and guard is not None:
            held = [y for y in settled if full[y] >= guard]
            text += (f"，其中已走完全年的{cn_count(len(settled))}年"
                     + ("全年都在警戒线以上" if len(held) == len(settled)
                        else f"有{cn_count(len(held))}年全年回到警戒线以上"))
        text += "。"
        if below:
            text += (f"{cn_count(len(full))}个完整年份里全年低于警戒线的"
                     + ("只有 " if len(below) == 1 else "有 ")
                     + "、".join(f"{y} 年（{num(full[y])}%，那年上半年 {signed(half[y])}）"
                                for y in below) + "。")
        return text
    return ""


def next_quarter_charts(s: dict, block: dict) -> tuple[list[dict], list[dict]]:
    """Section three: the current report's thresholds, each measured from the series."""
    q = s["quarterly"]
    P = q["periods"]
    year = int(P[-1][:4])
    following = shift_quarter(P[-1], 1)
    entries = threshold_entries(s, block, "current", following)
    grouped = by_measure(entries)
    safe = [e for e in entries if on_safe_side(e, "current")]
    on_line = [e for e in safe if round(headroom(e["direction"], e["threshold"], e["current"]), 1) == 0]
    words = []
    if "total_net_sales" in grouped:
        words.append(f"{following} 总净销售的当前值是本季实际，负柱说的是指引本身要求的环比跳升，"
                     "不是已经发生的未达")
    if "q4_sales_guide" in grouped:
        q4 = fourth_quarter_guide(s)
        if q4["implied"]:
            words.append(f"{year}Q4 收入指引的当前值是全年指引 {guide_range(q4['fy'])} 的中值减去"
                         f"已报告的 {eur_m(q4['reported'])}、"
                         + "、".join(f"再减 {p} 指引中值 €{m / 1000:g}B" for p, m in q4["between"])
                         + f" 倒推出的 {eur_m(q4['value'])}（D），公司要到下一份发布才给这一季的指引")
    if "china_share_h1" in grouped:
        words.append("中国大陆两条用的是上半年法定中期报告的占比，季度只有另一个口径")
    if "fcf_conversion" in grouped:
        words.append(f"现金流一条是{year_to_date_word(len(quarters_of_year(P, year)))}的比值，"
                     "全年要到第四季度走完才结算")
    headroom_chart = headroom_exhibit(
        (f"下季 {len(entries)} 条阈值：按本季读数 {len(safe)} 条在安全侧"
         + (f"（其中 {len(on_line)} 条压线）" if on_line else "")
         + f"、{len(entries) - len(safe)} 条还没到"),
        entries, "current",
        ("正值 = 已在安全侧。兑现线是报告里「兑现」一档的门槛，警戒线是「警示」一档的门槛。"
         + "；".join(words) + ("。" if words else "")),
        ("阈值取自本季本地分析稿的「关键观察指标」，是研究设定，不是公司指引；当前值为本季申报值或据其自算（D）。"
         + (f"另有{cn_count(len(block.get('not_quantified', [])))}条无法量化或只是方向条件，列在核对抽屉里并说明原因。"
            if block.get("not_quantified") else "")),
    )
    headroom_chart["ref"] = "EX_NEXT"
    charts = [headroom_chart]
    for key, group in grouped.items():
        if measure_series(s, key) is None:
            continue
        current = group[0]["current"]
        period_word = ""
        if key == "china_share_h1":
            period_word = f"（{h1_years(s)[-1]} 年上半年）"
        elif key == "fcf_conversion":
            period_word = f"（{year} 年{year_to_date_word(len(quarters_of_year(P, year)))}）"
        why = "".join(entry.get("why", "") for entry in group)
        chart = threshold_lines(
            s, key, group,
            f"{measure_name(key, following)}：下季阈值 {lines_phrase(key, group)}，"
            f"当前 {measure_text(key, current)}{period_word}",
            next_note(s, key, group, following) + why,
            "阈值取自本季本地分析稿的「关键观察指标」，是研究设定，不是公司指引；实际值"
            + MEASURE_SOURCES[key],
        )
        chart["ref"] = f"EX_NEXT_{key.upper()}"
        charts.append(chart)
    return charts, entries


# ── section one: what last quarter's report left to settle ───────────────────
UNFILLED = re.compile(r"\{[a-z][a-z_0-9]*")


def filled(text: str, values: dict[str, str]) -> str:
    """`board.fill_story`, then refuse any brace it did not recognise as a placeholder.

    Its pattern reads lower-case letters and underscores only, so a name with a
    digit in it would pass through as literal braces instead of raising.
    """
    out = fill_story(text, values)
    if UNFILLED.search(out):
        raise ValueError(f"unfilled placeholder in a one-quarter sentence: {out[:80]!r}")
    return out


def closure_values(s: dict, story: dict | None) -> dict[str, str]:
    """The figures the follow-up evidence cites, computed from the series."""
    q = s["quarterly"]
    P = q["periods"]
    year = int(P[-1][:4])
    following = shift_quarter(P[-1], 1)
    values = {"sales": eur_m(q["total_net_sales"][-1]), "next_quarter": following,
              "last_booking": s["bookings"]["periods"][-1]}
    this_guide, next_guide = guided_sales(s, P[-1]), guided_sales(s, following)
    if this_guide:
        values["sales_guide"] = guide_range(this_guide)
    if next_guide:
        values["next_guide"] = guide_range(next_guide)
    path = fy_guidance(s, year)
    if len(path) >= 2:
        values["fy_before"], values["fy_now"] = guide_range(path[-2]), guide_range(path[-1])
    latest = h1_years(s)[-1]
    half = s["h1_mix"][str(latest)]
    values["china_half"] = f"{num(h1_share(s, latest, 'China'))}%"
    values["china_half_eur"] = f"{eur_m(half['region_eur_m']['China'])} / {eur_m(half['total_net_sales'])}"
    immersion = next((c for c in (story or {}).get("capacity", []) if c["tool"] == "DUV 浸没式"), None)
    if immersion:
        values.update({"this_year": str(immersion["base_year"]),
                       "next_year": str(immersion["base_year"] + 1),
                       "year_after": str(immersion["base_year"] + 2),
                       "immersion_capacity": f"{immersion['base_units']}",
                       "capacity_add": f"{immersion['next_year_add_pct']}%",
                       "capacity_add_later": f"{immersion['year_after_add_pct_investigating']}%"})
    return values


def closure_chart(block: dict, values: dict[str, str]) -> dict:
    """Last report's follow-up list, counted by this report's verdicts.

    The counts are read off the items, so the bar and the list under it cannot
    disagree; a verdict outside the block's own labels stops the build.
    """
    labels, items = block["labels"], block["items"]
    unknown = sorted({item["verdict"] for item in items} - set(labels))
    if unknown:
        raise ValueError(f"series block `followup_closure` has verdicts {unknown} outside its labels")
    counts = [sum(1 for item in items if item["verdict"] == label) for label in labels]
    said = "、".join(f"{count} 条{label}" for label, count in zip(labels, counts) if count)
    lines = "".join(f"<br>{i}. {item['question']} —— <b>{item['verdict']}</b>："
                    f"{filled(item['evidence'], values)}" for i, item in enumerate(items, start=1))
    return {
        "ref": "EX_CLOSURE",
        "kind": "bars_labeled",
        "title": (f"上季 {len(items)} 条待验证问题：{said}"
                  + "".join(f"，没有一条{label}" for label, count in zip(labels, counts) if not count)),
        "xlabels": list(labels),
        "values": counts,
        "legend": "问题条数",
        "fmt": "f0",
        "yfmt": "f0",
        "label_fmt": "f0",
        "ylab": "条",
        "note": filled(block["note"], values) + lines,
        "src_extra": (f"问题清单来自上季（{block['set_in']}）本地分析稿文末的 Follow-up，判定取本季"
                      f"（{block['period']}）本地分析稿第 0 节；证据一栏只写本季 6-K（新闻稿、演示、报表附件、"
                      "法定中期报告）里核得到的部分。"),
    }


def line_verdicts(entries: list[dict], value_key: str) -> str:
    """「两条警戒线都守住，三条兑现线里两条达到」, counted from the entries."""
    parts = []
    for line in ("警戒线", "兑现线"):
        kind = [e for e in entries if e["line"] == line]
        if not kind:
            continue
        good, bad = LINE_VERBS[line]
        ok = sum(1 for e in kind if on_safe_side(e, value_key))
        if ok == len(kind):
            parts.append(f"{cn_count(len(kind))}条{line}都{good}" if len(kind) > 1 else f"一条{line}{good}")
        elif ok == 0:
            parts.append(f"{cn_count(len(kind))}条{line}都{bad}" if len(kind) > 1 else f"一条{line}{bad}")
        else:
            parts.append(f"{cn_count(len(kind))}条{line}里{cn_count(ok)}条{good}")
    return "，".join(parts)


def prior_note(s: dict, key: str, group: list[dict]) -> str:
    """What one settled measure's reading rests on, from the series."""
    q = s["quarterly"]
    P = q["periods"]
    year = int(P[-1][:4])
    if key == "h1_buyback":
        spent = h1_buybacks(s)
        target = next((e["threshold"] for e in group if e["line"] == "兑现线"), None)
        over = [y for y in sorted(spent) if target is not None and spent[y] >= target]
        return (f"按现金流量表「购买库存股」的实付额：{year} 年一季度 "
                f"{eur_m(-q['share_buybacks'][P.index(f'{year}Q1')])}、二季度 "
                f"{eur_m(-q['share_buybacks'][P.index(f'{year}Q2')])}。"
                + (f"{cn_count(len(spent))}个上半年里回购到过兑现线的"
                   + (("只有 " if len(over) == 1 else "有 ")
                      + "、".join(f"{y} 年（{eur_m(spent[y])}）" for y in over) if over else "一个都没有")
                   + "。" if target is not None else ""))
    if key == "china_system_share":
        china = s["deck_mix"]["china_pct"]
        window = [len(P) - 3, len(P) - 2, len(P) - 1]
        falling = all(china[a] > china[b] for a, b in zip(window, window[1:]))
        return ("上季报告要的是上半年逐季下行到兑现线以下："
                + " → ".join(f"{P[i]} {china[i]}%" for i in window)
                + ("，逐季下行" if falling else "，并不是逐季下行")
                + "。口径是演示页的净系统销售、按发货地（报告原话是「China systems revenue 占比」）；"
                "中期报告的总净销售口径画在第三节。")
    return ""


def prior_settlement_charts(s: dict, block: dict) -> tuple[list[dict], list[dict]]:
    """Section one, part two: last report's thresholds that fell due this quarter."""
    q = s["quarterly"]
    P = q["periods"]
    year = int(P[-1][:4])
    entries = threshold_entries(s, block, "actual", P[-1])
    grouped = by_measure(entries)
    misses = [e for e in entries if not on_safe_side(e, "actual")]
    explain = []
    if "h1_buyback" in grouped:
        explain.append("回购按现金流量表的实付额，是一、二季度之和")
    if "interim_dividend_growth" in grouped:
        per_share = s["dividends_per_share_by_year"]
        explain.append(f"股息增速是 {year} 年第一次中期股息 €{per_share[str(year)]['interim']:.2f} 对 "
                       f"{year - 1} 年每次中期股息 €{per_share[str(year - 1)]['interim']:.2f}（D），"
                       "全年股息要到年底才宣告")
    if "china_system_share" in grouped:
        explain.append("中国占比是演示页的净系统销售、按发货地口径")
    not_settled = block.get("not_settled", [])
    headroom_chart = headroom_exhibit(
        (f"上季 {len(entries)} 条量化阈值：{line_verdicts(entries, 'actual')}"
         + ("——" + "、".join(f"{LINE_VERBS[e['line']][1]}的是{measure_name(e['measure'], P[-1])}"
                               f"（{measure_text(e['measure'], e['actual'])}，{e['line']} "
                               f"{threshold_text(e['measure'], e['threshold'])}）" for e in misses)
            if misses else "")),
        entries, "actual",
        "正值 = 在安全侧：兑现线为已达到，警戒线为守住。" + "；".join(explain) + ("。" if explain else ""),
        (f"阈值取自上季（{block['set_in']}）本地分析稿的「关键观察指标」，是研究设定，不是公司指引；"
         "实际值为本季申报值或据其自算（D）。"
         + (f"上季另有{cn_count(len(not_settled))}条本季不结算，理由列在核对抽屉里。" if not_settled else "")),
    )
    headroom_chart["ref"] = "EX_PRIOR"
    charts = [headroom_chart]
    for key, group in grouped.items():
        if measure_series(s, key) is None:
            continue
        actual = group[0]["actual"]
        reading = (f"{year} 年上半年 {measure_text(key, actual)}" if key == "h1_buyback"
                   else f"本季 {measure_text(key, actual)}")
        charts.append(threshold_lines(
            s, key, group,
            (f"{measure_name(key, P[-1])}："
             + "、".join(f"{LINE_VERBS[e['line']][0 if on_safe_side(e, 'actual') else 1]}上季{e['line']} "
                        f"{threshold_text(key, e['threshold'])}" for e in sorted(group, key=lambda e: e["threshold"]))
             + f"（{reading}）"),
            prior_note(s, key, group),
            "阈值取自上季本地分析稿的「关键观察指标」，是研究设定，不是公司指引；实际值" + MEASURE_SOURCES[key],
        ))
    return charts, entries


# ── the page ─────────────────────────────────────────────────────────────────
def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    q = staging["quarterly"]
    year = int(q["periods"][-1][:4])
    path = fy_guidance(staging, year)
    third = (f"FY{year} 指引 {guide_range(path[-1])}" if path else
             f"装机管理占比 {num(q['ibm_sales'][-1] / q['total_net_sales'][-1] * 100)}%")
    return [f"Total net sales {eur_m(q['total_net_sales'][-1])}",
            f"毛利率 {num(q['gross_margin_printed_pct'][-1])}%",
            third]


def build_payload(staging: dict) -> dict:
    s = staging
    q = s["quarterly"]
    P = q["periods"]
    period = display_period(P[-1])
    latest = latest_block(s, period=period, period_end=q["period_ends"][-1],
                          release_date=q["release_dates"][-1])
    label = f"{P[-1][:4]} 年第{cn_ordinal(int(P[-1][5]))}季度业绩新闻稿"
    if not any(src["label"].startswith(label) for src in s["sources"]):
        raise ValueError(f"series `sources` has no entry for the {label}: add it with the roll")
    blocks = quarter_blocks(s)
    story = blocks["quarter_story"]
    next_kpi = blocks["next_kpi"]

    period_ex = period_charts(s)
    guide_ex = guidance_charts(s)
    struct_ex = structure_charts(s, story)
    cust_ex = customer_charts(s)
    order_ex = order_charts(s)
    cash_ex = margin_cash_charts(s)
    ref = {ex["ref"]: ex for ex in period_ex + struct_ex + cust_ex + order_ex + cash_ex}
    closure = blocks["followup_closure"]
    prior_kpi = blocks["prior_kpi_settlement"]
    closure_ex = [closure_chart(closure, closure_values(s, story))] if closure else []
    prior_ex, prior_entries = prior_settlement_charts(s, prior_kpi) if prior_kpi else ([], [])
    next_ex, next_entries = next_quarter_charts(s, next_kpi)
    conversion_ref = next((ex["ref"] for ex in next_ex if ex.get("ref") == "EX_NEXT_FCF_CONVERSION"), None)
    region_half = half_year_region_chart(s)
    if region_half:
        ref["EX_REGIONH"] = region_half
    ref["EX_AR"] = receivables_chart(s, story, conversion_ref)

    # The four sections, in the site's order. Each list holds the exhibit objects
    # themselves, so numbering them in render order numbers them in place.
    # Section one settles in the order last quarter set things up: its questions,
    # its thresholds, then the company's own guidance record.
    settled_ex = closure_ex + prior_ex + guide_ex
    # Section two follows the report's own order: the full-year raise and what it
    # asks of the second half, the memory customers, the first half's regions and
    # cash, then the capacity plan the release announced.
    highlight_words = {"EX_FYPATH": "全年指引的几次改动", "EX_H2H1": "最新区间对下半年的要求",
                       "EX_MEMORY": "存储客户的占比", "EX_REGIONH": "上半年的地区构成",
                       "EX_AR": "应收账款与年初至今的现金流",
                       "EX_UNITSY": ("下一年的产能计划" if (story or {}).get("capacity")
                                     else "两类主力机型的年销售台数")}
    highlight_ex = [ref[key] for key in highlight_words if key in ref]
    routine_ex = [ref[key] for key in ("EX_MIX", "EX_EUVQ", "EX_TECHY", "EX_REGIONQ", "EX_REGIONY",
                                       "EX_BOOK", "EX_BACKLOG", "EX_MARGIN", "EX_CFO", "EX_RETURN")
                  if key in ref]
    groups = [settled_ex, highlight_ex, next_ex, routine_ex]
    exhibits = number_exhibits([ex for grp in groups for ex in grp])
    resolve_exhibit_refs(exhibits)

    year = int(P[-1][:4])
    sales = settlement(s, "sales")
    gms = settlement(s, "gross_margin")
    ibm = settlement(s, "ibm")
    now, gm_now, ibm_now = sales["rows"][-1], gms["rows"][-1], ibm["rows"][-1]
    path = fy_guidance(s, year)
    bk = s["bookings"]
    words = {"above": "高于", "in": "落在", "below": "低于"}
    where = {"above": "上限", "in": "区间内", "below": "下限"}

    headline = (f"{quarter_cn(P[-1])}总净销售 {eur_m(q['total_net_sales'][-1])}"
                + (f"，{words[now['where']]}上一季给出的 {guide_range(now)} 指引{where[now['where']]}"
                   if now["guided"] else "")
                + f"；毛利率 {num(q['gross_margin_printed_pct'][-1])}%"
                + (f"（指引 {guide_range(gm_now, '%')}）" if gm_now["guided"] else "")
                + "。")
    ahead = next((g for g in reversed(s["guidance"])
                  if g["guided_quarter"] not in P and g.get("sales")), None)
    if ahead:
        headline += (f"对 {ahead['guided_quarter']} 的指引是总净销售 {guide_range(ahead['sales'])}"
                     + (f"、毛利率 {guide_range(ahead['gross_margin'], '%')}" if ahead.get("gross_margin") else "")
                     + "。")
    if len(path) >= 2 and path[-1]["reported_quarter"] == P[-1]:
        headline += (f"同一份发布把 {year} 年全年收入指引从 {guide_range(path[-2])} 改为 "
                     f"{guide_range(path[-1])}。")
    ratio_ex = next(ex for ex in period_ex if ex.get("ref") == "EX_H2H1")
    implied = ratio_ex["xlabels"][-1].endswith("指引隐含")
    if implied:
        headline += (f"按新区间的中值，下半年收入要比上半年多 {num(ratio_ex['groups'][0]['values'][-1])}%"
                     + ("；" + ratio_ex["title"].split("；", 1)[1] if "；" in ratio_ex["title"] else "")
                     + "。")

    cards = []
    if ibm_now["guided"] and now["guided"] and now["where"] == "above":
        over = now["actual"] - now["high"]
        ibm_over = ibm_now["actual"] - ibm_now["mid"]
        share = ibm_over / over * 100
        cards.append(
            '<article><span>本季</span><b>'
            + (f"超出指引上限的部分，{'大半' if share >= 50 else '一部分'}来自装机管理" if ibm_over > 0
               else "超出指引上限，装机管理没有超") + '</b>'
            f'<p>总净销售比指引上限多 {eur_m(over)}，装机管理比它自己的单点指引多 {eur_m(ibm_over)}'
            f'（相当于前者的 {num(share, 0)}%）。按指引中值算，总净销售多出 {eur_m(now["actual"] - now["mid"])}。'
            f'毛利率 {num(gm_now["actual"])}%，指引 {guide_range(gm_now, "%")}。</p></article>')
    if implied:
        try:
            q4 = fourth_quarter_guide(s)
        except ValueError:
            q4 = None
        beyond = bool(q4 and q4["implied"] and q4["value"] > max(q["total_net_sales"]))
        cards.append(
            '<article><span>指引</span><b>下半年重于上半年是常态'
            + (f"，{year}Q4 却要高过{cn_count(len(P))}季里的任何一季" if beyond else "") + '</b>'
            f'<p>{ratio_ex["title"]}。{fourth_quarter_words(s)}见图 {ratio_ex["n"]}。</p></article>')
    this_year = quarters_of_year(P, year)
    cash = year_to_date_cash(s)
    first_half_fcf = cash["cfo"] + cash["capex"]
    _, _, half_conversion = conversion_years(s)
    negative = [y for y in sorted(half_conversion) if half_conversion[y] < 0]
    if len(this_year) == 2 and first_half_fcf < 0 and year in negative and f"{year - 1}Q4" in P:
        factoring = (story or {}).get("factoring")
        cards.append(
            '<article><span>现金</span><b>'
            f'上半年自由现金流为负，{cn_count(len(half_conversion))}年里第{cn_ordinal(negative.index(year) + 1)}次</b>'
            f'<p>经营现金流 {eur_m(cash["cfo"])}、自由现金流 {eur_m(first_half_fcf)}（D）；'
            f'应收账款从上年末 {eur_m(q["accounts_receivable"][P.index(f"{year - 1}Q4")])} '
            f'{"升" if q["accounts_receivable"][-1] >= q["accounts_receivable"][P.index(f"{year - 1}Q4")] else "降"}到 '
            f'{eur_m(q["accounts_receivable"][-1])}'
            + (f"，而上年同期有 {eur_b(factoring['prior_half_sold_eur_m'])} 应收账款以保理方式卖出、今年没有"
               if factoring and not factoring["sold_eur_m"] and factoring["prior_half_sold_eur_m"] else "")
            + f'。见图 {ref["EX_AR"]["n"]}。</p></article>')
    top = max(range(len(bk["net_bookings"])), key=lambda k: bk["net_bookings"][k])
    cards.append(
        '<article><span>订单</span><b>季度订单不再公布</b>'
        f'<p>最后一次是 {bk["periods"][-1]}：{eur_m(bk["net_bookings"][-1], 0)}'
        + (f"，{cn_count(len(bk['periods']))}季里最高" if top == len(bk["net_bookings"]) - 1 else "")
        + "。此后的发布删掉了这一行；本页检索过的 EDGAR 申报没有一份说明原因。</p></article>")

    guided_from = next(r["quarter"] for r in sales["rows"] if r["guided"])
    ibm_from = next((r["quarter"] for r in ibm["rows"] if r["guided"]), None)
    gm_from = next((r["quarter"] for r in gms["rows"] if r["guided"]), None)
    kpi_numbers = {item["kpi"] for item in next_kpi["quantified"] + next_kpi.get("not_quantified", [])}
    quantified_kpis = {item["kpi"] for item in next_kpi["quantified"]}
    half_quantified = {item["kpi"] for item in next_kpi.get("not_quantified", [])} & quantified_kpis
    sections = [
        {"id": "settled", "title": "一、上季跟踪指标兑现了吗",
         "description": (
             ("先看" + "、".join(
                 ([f"上季本地分析稿留下的 {len(closure['items'])} 条问题闭环了几条"] if closure else [])
                 + ([f"{'它' if closure else '上季本地分析稿'}的 {len(prior_entries)} 条本季到期的量化阈值"
                     "各落在哪一边"] if prior_kpi else []))
              + "，再看公司自己的指引兑现记录："
              if closure or prior_kpi else
              "本季没有上季留下的跟踪指标可结算；本节只看公司上季给出、本季到期的指引兑现到什么程度：")
             + "、".join(f"{name}从 {start}" for name, start in
                        (("收入", guided_from), ("毛利率", gm_from), ("装机管理", ibm_from)) if start)
             + " 起各自连到本季，本季那一格在每张图的最右。"
             + (f"上季报告另有{cn_count(len(prior_kpi['not_settled']))}条本季不结算，理由列在核对抽屉里。"
                if prior_kpi and prior_kpi.get("not_settled") else "")),
         "exhibits": settled_ex},
        {"id": "quarter_highlights", "title": "二、本季重点",
         "description": ("本季本地分析稿的核心结论里能用申报数据画出来的："
                         + "、".join(highlight_words[ex["ref"]] for ex in highlight_ex) + "。"
                         + ("画不了的在这里交代：" + "；".join((story or {})["highlights_untracked"]) + "。"
                            if (story or {}).get("highlights_untracked") else "")),
         "exhibits": highlight_ex},
        {"id": "next_quarter", "title": "三、下季要跟踪什么",
         "description": (
             f"本季本地分析稿的「关键观察指标」{cn_count(len(kpi_numbers))}条里，{cn_count(len(quantified_kpis))}条能量化成 "
             f"{len(next_entries)} 条阈值（兑现线与警戒线各算一条），离线多远统一用「距阈值余量」表示，"
             "有历史序列的再逐条画在长序列上"
             + ("；" + "，".join(
                 ([f"{cn_count(len(kpi_numbers - quantified_kpis))}条无法量化"]
                  if kpi_numbers - quantified_kpis else [])
                 + ([f"{cn_count(len(half_quantified))}条有一半只是方向条件"] if half_quantified else []))
                + "，都列在核对抽屉里并说明原因"
                if kpi_numbers - quantified_kpis or half_quantified else "")
             + "。"),
         "exhibits": next_ex},
        {"id": "routine", "title": "四、长期常规跟踪",
         "description": (f"ASML 专属的长期序列，季度图从 {P[0]} 起、全年图从 {min(s['annual_mix'])} 年起：系统与装机管理的结构、"
                         "EUV 与技术构成、季度与全年的地区构成、季度订单到停止公布为止与年末积压、利润率、"
                         "经营现金流的季节性与股东回报。"),
         "exhibits": routine_ex},
    ]

    first_table = exhibits[-1]["n"] + 1
    by_q = {g["guided_quarter"]: g for g in s["guidance"]}
    next_table = threshold_table(0, "下季阈值与当前值（原单位）", next_entries, "current", "当前值")
    next_table.pop("n")
    for item in next_kpi.get("not_quantified", []):
        next_table["rows"].append([item["metric"], "—", item["condition"], "—", "不作图：" + item["why"]])
    threshold_tables = [next_table]
    if prior_kpi:
        prior_table = threshold_table(0, "上季阈值的本季结算（原单位）", prior_entries, "actual", "本季实际")
        prior_table.pop("n")
        for item in prior_kpi.get("not_settled", []):
            prior_table["rows"].append([item["metric"], "—", item["condition"], "—", "不结算：" + item["why"]])
        threshold_tables.insert(0, prior_table)
    tables = [{
        "title": "单季损益与台数（公司印出值，€M）",
        "headers": ["期间", "季末", "发布", "总净销售", "净系统销售", "装机管理", "毛利率",
                    "经营利润率", "净利润", "基本 EPS（€）", "光刻机台数（新 / 二手）"],
        "rows": [[P[k], q["period_ends"][k], q["release_dates"][k],
                  eur_m(q["total_net_sales"][k]), eur_m(q["net_system_sales"][k]), eur_m(q["ibm_sales"][k]),
                  f"{num(q['gross_margin_printed_pct'][k])}%", f"{num(q['operating_margin_printed_pct'][k])}%",
                  eur_m(q["net_income"][k]), f"{q['eps_basic'][k]:.2f}",
                  (f"{q['litho_units'][k]:.0f}（{q['new_units'][k]} / {q['used_units'][k]}）"
                   if q["new_units"][k] is not None else f"{q['litho_units'][k]:.0f}")]
                 for k in range(len(P))],
    }, {
        "title": "每一份发布给下一季的指引与随后的实际",
        "headers": ["指引季度", "发布日", "收入指引", "实际总净销售", "偏离中值 D", "毛利率指引",
                    "实际毛利率", "装机管理指引", "实际装机管理", "备注"],
        "rows": [[r["quarter"],
                  by_q[r["quarter"]]["filed"] if r["quarter"] in by_q else "—",
                  guide_range(r) if r["guided"] else ("撤回" if r["withdrawn"] else "—"),
                  eur_m(r["actual"]),
                  signed(r["dev_pct"]) if r["guided"] else "—",
                  guide_range(g, "%") if g["guided"] else "—",
                  f"{num(g['actual'])}%",
                  guide_range(m) if m["guided"] else "—",
                  eur_m(m["actual"]),
                  "；".join([f"{v['announced']} 另发公告改为 €{guide_b(v['low'], 1)}–{guide_b(v['high'], 1)}B、"
                             f"毛利率 {v['gm_low']:g}–{v['gm_high']:g}%"
                             for v in s.get("guidance_revisions", []) if v["quarter"] == r["quarter"]]
                            + (["公司以新冠不确定性为由撤回季度与全年指引"] if r["withdrawn"] else []))
                  or "—"]
                 for r, g, m in zip(sales["rows"], gms["rows"], ibm["rows"])],
    }] + threshold_tables + [{
        "title": "净订单（公司印出值，€M）",
        "headers": ["期间", "净订单", "其中 EUV（公司印出，四舍五入到 0.1 十亿）", "Memory 占订单",
                    "订单 / 净系统销售 D"],
        "rows": [[p, eur_m(bk["net_bookings"][k], 0),
                  eur_m(bk["euv_bookings_printed_eur_m"][k], 0) if bk["euv_bookings_printed_eur_m"][k] else "—",
                  f"{bk['memory_pct'][k]}%" if bk["memory_pct"][k] is not None else "—",
                  f"{bk['net_bookings'][k] / q['net_system_sales'][P.index(p)]:.2f}"]
                 for k, p in enumerate(bk["periods"])],
    }, {
        "title": "全年净系统销售按技术（€M / 台）",
        "headers": ["年份", "EUV", "ArF 浸没式", "ArF 干式", "KrF", "I-line", "量测与检测", "合计", "口径来源"],
        "rows": [[y] + [
            (f"{eur_m(s['annual_mix'][y]['technology_eur_m'][k])} / {s['annual_mix'][y]['technology_units'][k]}"
             if s["annual_mix"][y]["technology_eur_m"][k] is not None else "—")
            for k in ("EUV", "ArFi", "ArF_dry", "KrF", "I_line", "MI")]
            + [eur_m(s["annual_mix"][y]["net_system_sales"]), s["annual_mix"][y]["basis_source"]]
            for y in sorted(s["annual_mix"])],
    }, {
        "title": "首次印出之后被公司改过的格（€M）",
        "headers": ["期间", "科目", "首次印出", "最后一次印出", "改在哪一份发布"],
        "rows": [[d["quarter"], d["line"], f"{d['first_print']:,.1f}", f"{d['restated']:,.1f}", d["restated_in"]]
                 for d in q["first_print_diffs"] if d["quarter"] in P],
    }]
    # Numbered in drawer order after the last exhibit; `n` leads each table's keys.
    tables = [{"n": first_table + offset, **table} for offset, table in enumerate(tables)]
    tables.append(ai_capex_cycle_table(first_table + len(tables)))

    next_headroom = next(ex for ex in next_ex if ex.get("ref") == "EX_NEXT")
    prior_headroom = next((ex for ex in prior_ex if ex.get("ref") == "EX_PRIOR"), None)
    notes = [
        "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
        ((f"Exhibit {prior_headroom['n']} 与 Exhibit {next_headroom['n']} 的阈值是本地研究设定"
          "（上季与本季本地分析稿的「关键观察指标」）" if prior_headroom else
          f"Exhibit {next_headroom['n']} 起的第三节阈值是本地研究设定（本季本地分析稿的「关键观察指标」）")
         + "，不是公司指引，也不构成评级或投资建议；「距阈值余量」统一为正值代表安全侧。"
         "兑现线是报告里「兑现」一档的门槛，警戒线是「警示」一档的门槛。"),
        "公司在荷兰注册，在阿姆斯特丹泛欧交易所与纳斯达克上市，季度业绩与年报按 US GAAP 以欧元列报；"
        "它是美国证券法下的外国私人发行人，年报为 20-F，季度业绩以 6-K 报送，所以 2016 年以来的全部原件都在 EDGAR 上，"
        "本页 sources 逐份直链。季度在最接近季末的周日结账，第四季度固定结在 12 月 31 日；本页按自然年季度标注。",
        "每一份季度 6-K 都带同样的四份文件：新闻稿、投资者演示、带五季趋势的 US GAAP 报表附件，七月那份另附法定中期报告。"
        "所以每个季度都被公司印过最多五次。本页每个季度取公司最后一次印出的口径；与首次印出不同的每一格，"
        "连同改动所在的发布，都列在核对抽屉里。",
        "两次口径变化必须先说明：2017 年 1 月起量测与检测从服务收入挪进系统销售，公司按新口径重印了 2016 年四个季度，本页用重印值；"
        f"2018 年 1 月起按 ASC 606 列报，公司在 FY2018 的 20-F 里重述了 2017 全年（总净销售由四个季度相加的 "
        f"{eur_m(year_sum(q, 'total_net_sales', 2017))} 改为 {eur_m(s['annual_mix']['2017']['total_net_sales'])}），"
        "但从未按季重述，所以本页季度图在 2018Q1 画一条断点线。全年图的 2016、2017 两年取 FY2018 20-F 的重述值。",
        "法定中期报告按 EU-IFRS 编制，与新闻稿的 US GAAP 在毛利、净利润上差别很大，本页不混用："
        "只用它的收入拆分（技术、终端与地区的金额和台数；两套准则下的收入自 2018 年起相同）和附注里的文字说明，"
        "不用它的利润与现金流数字。",
        "季度的技术、终端与地区构成来自演示页上的整数百分比，分母是净系统销售，地区按发货地；"
        "全年与上半年的金额来自 20-F 与法定中期报告，其中地区表的分母是总净销售、按客户工厂所在地。"
        "两套口径本页分图呈现，不互相推算。",
        f"季度净订单公布到 {bk['periods'][-1]} 为止。{bk['first_release_without']} 的发布起，新闻稿表格、演示页与报表附件里都不再有这一行，"
        "本页检索过的 EDGAR 申报没有一份说明原因（电话会不在 EDGAR 上）；本页对「为什么停」不作判断。"
        "年末积压订单在第四季度的发布里首次作为表格行出现。",
        "指引结算用的是上一份发布里给下一季的指引。公司早年常给「around」的单点，本页把单点当作宽度为零的区间计分，"
        "比公司措辞更严；2020 年第二季度公司以新冠不确定性为由撤回了季度与全年指引，那一季不计分。"
        "2020 年第一季度的指引在 3 月 30 日另发公告下调过，本页按原始指引结算，下调后的区间记在指引表的备注里。",
        "本页不发布市场一致预期、评级、目标价与估值；公司给出的长期情景只在它出现的那份发布的语境里引用，本页不作预测。",
        "本页只发布公司披露值与可复算的简单派生值；D 标记代表 Derived / 自算。",
        "核对抽屉最后那张「AI capex 循环」是全站共用的跨页对照块，在每一页都逐字节相同，不是对本公司的判断。"
        "它追的是四家云厂现金资本开支到 NVDA 数据中心收入再到 TSM 晶圆这条链，本公司是这条链上游的设备供应商，"
        "不在表里的任何一列；它在折叠的抽屉里，不参与本页的论证。",
    ]

    return {
        "schema_version": "quarterly-dashboard/asml-v1",
        "page": {"slug": "asml", "language": "zh-CN"},
        "company": {"ticker": "ASML", "name": "ASML Holding N.V.",
                    "group": "semiconductor_ai", "accounting_standard": "US GAAP"},
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · ASML",
        "title": f"ASML Holding N.V. (ASML)：{quarter_cn(P[-1])}业绩仪表盘",
        "subtitle": (f"截至 {latest['period_end']} · 发布 {latest['release_date']} · US GAAP · 欧元列示 · "
                     "自然年财年（季度结于最接近季末的周日） · "
                     "数据来自公司 6-K 新闻稿、演示、报表附件与 20-F"),
        "headline": headline,
        "brief": (f'<h4>本季{cn_count(len(cards))}条主线</h4><div class="takeaway-grid">'
                  + "".join(cards) + '</div>'),
        "source": ('Source: <a href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany'
                   '&CIK=0000937966&type=6-K&dateb=&owner=include&count=40" rel="noopener">'
                   'ASML Holding N.V. 在 SEC EDGAR 的申报（CIK 937966）</a>。'
                   '公司为外国私人发行人，年度报告为 20-F，季度业绩以 6-K 报送。'),
        "source_url": ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
                       "&CIK=0000937966&type=6-K&dateb=&owner=include&count=40"),
        "source_links": s["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": sections,
        "tables": tables,
        "notes": notes,
        "footer": ("ASML quarterly results · 数据来自公司公开披露与透明自算 · "
                   "仅供研究，不构成投资建议"),
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "asml.js"), payload, "asml")
    shell_dir = ROOT / "asml"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("ASML", "asml"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"ASML page: {charts} charts in {len(payload['sections'])} sections "
          f"+ {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
