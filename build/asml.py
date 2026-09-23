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
    latest_block,
    minus_sign,
    number_exhibits,
    stamped_block,
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
                "所以「指引严重后置」这句话本身说明不了多少，要看的是它离过去几年有多远。")
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
        out.append({
            "ref": "EX_MEMORY",
            "kind": "lines",
            "title": (f"存储芯片客户占净系统销售：本季 {mem[-1]}%"
                      + (f"，{rank}" if rank else "")
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
                     "2017 年第四季度两种分法都印过，Foundry 加 IDM 恰好等于 Logic，Memory 一项两边相同。"),
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
                 "要追的是它在资产负债表上的对应项，而季度报表附件只印流动负债合计，不单列合同负债。"
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
    story = stamped_block(s, "quarter_story", period)

    period_ex = period_charts(s)
    guide_ex = guidance_charts(s)
    struct_ex = structure_charts(s, story)
    cust_ex = customer_charts(s)
    order_ex = order_charts(s)
    cash_ex = margin_cash_charts(s)
    groups = [period_ex, guide_ex, struct_ex, cust_ex, order_ex, cash_ex]
    exhibits = number_exhibits([ex for grp in groups for ex in grp])
    resolve_exhibit_refs(exhibits)
    cuts, at = [], 0
    for grp in groups:
        cuts.append(exhibits[at:at + len(grp)])
        at += len(grp)
    period_ex, guide_ex, struct_ex, cust_ex, order_ex, cash_ex = cuts

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
        cards.append(
            '<article><span>指引</span><b>下半年重于上半年，是常态</b>'
            f'<p>{ratio_ex["title"]}。见图 {ratio_ex["n"]}。</p></article>')
    top = max(range(len(bk["net_bookings"])), key=lambda k: bk["net_bookings"][k])
    cards.append(
        '<article><span>订单</span><b>季度订单不再公布</b>'
        f'<p>最后一次是 {bk["periods"][-1]}：{eur_m(bk["net_bookings"][-1], 0)}'
        + (f"，{cn_count(len(bk['periods']))}季里最高" if top == len(bk["net_bookings"]) - 1 else "")
        + "。此后的发布删掉了这一行；本页检索过的 EDGAR 申报没有一份说明原因。</p></article>")

    sections = [
        {"id": "period", "short": "本季",
         "title": f"{quarter_cn(P[-1])}：" + ("，".join(
             ([f"收入{'高于' if now['where'] == 'above' else '低于' if now['where'] == 'below' else '落在'}指引"
               + ('上限' if now['where'] == 'above' else '下限' if now['where'] == 'below' else '区间内')]
              if now["guided"] else [])
             + (["全年指引上调"] if len(path) >= 2 and path[-1]["reported_quarter"] == P[-1]
                and path[-1]["low"] + path[-1]["high"] > path[-2]["low"] + path[-2]["high"] else []))
             or "指引与全年展望"),
         "description": "全年收入指引在一年内的几次改动，以及最新区间对下半年意味着什么。",
         "exhibits": period_ex},
        {"id": "guidance", "short": "指引兑现", "title": "每一份发布给下一季的指引，和随后报出来的数",
         "description": f"{cn_count(len(P))}个季度的收入、毛利率与装机管理指引结算。",
         "exhibits": guide_ex},
        {"id": "structure", "short": "卖的是什么", "title": "系统与装机管理，EUV 与 DUV",
         "description": "收入按系统与服务、按技术拆开。",
         "exhibits": struct_ex},
        {"id": "customers", "short": "卖给谁", "title": "存储与逻辑，中国大陆、韩国与台湾",
         "description": "终端与地区构成；季度是演示页的百分比，全年是 20-F 的金额，两者口径不同。",
         "exhibits": cust_ex},
        {"id": "orders", "short": "订单", "title": "订单停在哪一季，之后看什么",
         "description": "季度净订单到停止公布为止，以及公司改为公布的年末积压订单。",
         "exhibits": order_ex},
        {"id": "cash", "short": "利润与现金", "title": "利润率、现金流的季节性与股东回报",
         "description": "利润率的长期轨迹，经营现金流为什么集中在年底，以及现金去了哪里。",
         "exhibits": cash_ex},
    ]
    sections = [sec for sec in sections if sec["exhibits"]]
    for index, section in enumerate(sections, start=1):
        section["title"] = f"{cn_ordinal(index)}、{section['title']}"
    order = " → ".join(section.pop("short") for section in sections)

    first_table = exhibits[-1]["n"] + 1
    by_q = {g["guided_quarter"]: g for g in s["guidance"]}
    tables = [{
        "n": first_table,
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
        "n": first_table + 1,
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
    }, {
        "n": first_table + 2,
        "title": "净订单（公司印出值，€M）",
        "headers": ["期间", "净订单", "其中 EUV（公司印出，四舍五入到 0.1 十亿）", "Memory 占订单",
                    "订单 / 净系统销售 D"],
        "rows": [[p, eur_m(bk["net_bookings"][k], 0),
                  eur_m(bk["euv_bookings_printed_eur_m"][k], 0) if bk["euv_bookings_printed_eur_m"][k] else "—",
                  f"{bk['memory_pct'][k]}%" if bk["memory_pct"][k] is not None else "—",
                  f"{bk['net_bookings'][k] / q['net_system_sales'][P.index(p)]:.2f}"]
                 for k, p in enumerate(bk["periods"])],
    }, {
        "n": first_table + 3,
        "title": "全年净系统销售按技术（€M / 台）",
        "headers": ["年份", "EUV", "ArF 浸没式", "ArF 干式", "KrF", "I-line", "量测与检测", "合计", "口径来源"],
        "rows": [[y] + [
            (f"{eur_m(s['annual_mix'][y]['technology_eur_m'][k])} / {s['annual_mix'][y]['technology_units'][k]}"
             if s["annual_mix"][y]["technology_eur_m"][k] is not None else "—")
            for k in ("EUV", "ArFi", "ArF_dry", "KrF", "I_line", "MI")]
            + [eur_m(s["annual_mix"][y]["net_system_sales"]), s["annual_mix"][y]["basis_source"]]
            for y in sorted(s["annual_mix"])],
    }, {
        "n": first_table + 4,
        "title": "首次印出之后被公司改过的格（€M）",
        "headers": ["期间", "科目", "首次印出", "最后一次印出", "改在哪一份发布"],
        "rows": [[d["quarter"], d["line"], f"{d['first_print']:,.1f}", f"{d['restated']:,.1f}", d["restated_in"]]
                 for d in q["first_print_diffs"] if d["quarter"] in P],
    }]
    tables.append(ai_capex_cycle_table(first_table + len(tables)))

    notes = [
        f"本页按「{order}」{cn_count(len(sections))}段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
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
        "法定中期报告按 EU-IFRS 编制，与新闻稿的 US GAAP 在毛利、净利润上差别很大，本页不混用，"
        "只用它核对上半年的收入拆分（两套准则下的收入自 2018 年起相同）。",
        "季度的技术、终端与地区构成来自演示页上的整数百分比，分母是净系统销售，地区按发货地；"
        "全年的金额来自 20-F，其中地区表的分母是总净销售、按客户工厂所在地。两套口径本页分图呈现，不互相推算。",
        f"季度净订单公布到 {bk['periods'][-1]} 为止。{bk['first_release_without']} 的发布起，新闻稿表格、演示页与报表附件里都不再有这一行，"
        "本页检索过的 EDGAR 申报没有一份说明原因（电话会不在 EDGAR 上，本页没有读）；本页对「为什么停」不作判断。"
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
