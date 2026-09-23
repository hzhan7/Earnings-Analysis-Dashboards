"""Intel Corporation quarterly dashboard.

Intel is a US domestic filer, so its whole record is on EDGAR: a 10-Q or 10-K for
every quarter and an 8-K with the earnings release beside each one. Forty-three
releases carry this page -- the one of 2016-01-14, which gave the first
quarter's outlook, and the forty-two that reported 2016Q1 to 2026Q2.

**Three facts shape the charts.**

First, the guidance record is complete but not uniform. Every release from
2016 on gives the next quarter's revenue, and the *form* changed twice: a point
plus or minus US$500M to 2018Q3, a single "approximately" figure from 2018Q4 to
2022Q2, and a US$1B-wide range from 2022Q3. Gross margin was guided in
2016-2017 and again from 2021Q2; the thirteen quarters between were guided on
operating margin instead. EPS was first guided for 2017Q1. So each guided line
is scored only over the quarters it was actually guided, and the charts say so.

Second, "non-GAAP" is a definition Intel changed four times in this window
(2018, the NAND exclusion of 2021, share-based compensation from 2022, a fixed
long-term tax rate from 2023). Guidance is scored against the figure printed in
the quarter's own release -- the one on the same definition as the outlook --
and the reprint a year later is kept beside it, because the two disagree
exactly where the definition moved.

Third, the segment structure changed three times in the window. The page draws
segments only on the current basis (2024Q1 on, NEX folded in) and Intel Foundry
from 2023Q1, the earliest quarter the segment has ever been reported for, with
the 2024 restatement marked as a break rather than drawn through.

**A roll edits `series/intc.json` and nothing else** (CLAUDE.md §9). Every
period, count and figure on the page is computed from the series; what belongs
to one quarter only -- the EPS reconciliation legs, the prior quarter's open
questions, the next quarter's thresholds -- sits in period-stamped blocks and is
left out when absent.
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import (  # noqa: E402
    ai_capex_cycle_table,
    cn_count,
    cn_ordinal,
    display_period,
    headroom_exhibit,
    latest_block,
    midpoint_deviation,
    minus_sign,
    number_exhibits,
    stamped_block,
    threshold_exhibit,
    threshold_table,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402

STAGING_PATH = ROOT / "series" / "intc.json"
DATA_DIR = ROOT / "data"

SRC_RELEASES = "取自 Intel 各季业绩新闻稿（8-K EX-99.1），每一季都读它自己那份。"
SRC_FILINGS = "取自各季 10-Q 与 10-K 的合并报表；第四季度为全年减前三季。"


# ── small helpers ────────────────────────────────────────────────────────────
def qlab(label: str) -> str:
    """``2016Q1`` -> ``Q1'16``, the axis form every long chart on this site uses."""
    return f"Q{label[5]}'{label[2:4]}"


def quarter_of(day: str) -> str:
    """``2025-09-12`` -> ``2025Q3``."""
    return f"{day[:4]}Q{(int(day[5:7]) - 1) // 3 + 1}"


def next_quarter(label: str) -> str:
    y, n = int(label[:4]), int(label[5])
    return f"{y + 1}Q1" if n == 4 else f"{y}Q{n + 1}"


def check_alignment(s: dict) -> None:
    """Refuse a series whose blocks do not end on the same quarter.

    A roll that appends the quarter to the statement arrays and forgets the
    segment block would otherwise publish last quarter's DCAI margin and
    Foundry loss under this quarter's label, with every test green.
    """
    P = s["periods"]
    for a, b in zip(P, P[1:]):
        if b != next_quarter(a):
            raise ValueError(f"series periods are not consecutive at {a} -> {b}")
    for key in ("period_ends", "release_dates"):
        if len(s[key]) != len(P):
            raise ValueError(f"series `{key}` has {len(s[key])} entries for {len(P)} periods")
    for block in ("income_usd_m", "non_gaap_printed", "cash_flow_usd_m", "balance_sheet_usd_m"):
        for key, values in s[block].items():
            if isinstance(values, list) and len(values) != len(P):
                raise ValueError(f"series `{block}.{key}` has {len(values)} entries for {len(P)} periods")
    for block in ("segments", "foundry_external"):
        if s[block]["periods"][-1] != P[-1]:
            raise ValueError(f"series `{block}` ends at {s[block]['periods'][-1]} but the series ends "
                             f"at {P[-1]}: roll it with the quarter")
    if s["guidance"]["quarters"] != P + [next_quarter(P[-1])]:
        raise ValueError("series `guidance.quarters` must be every reported quarter plus the next one")


def largest_leg(story: dict) -> dict:
    legs = [leg for leg in story["eps_reconciliation"]["legs"] if round(leg["value"], 2) != 0]
    return max(legs, key=lambda leg: abs(leg["value"]))


def outlook_lead_days(s: dict) -> tuple[int, int]:
    """How far into each guided quarter its outlook was published, in days."""
    g, ends = s["guidance"], s["period_ends"]
    days = []
    for k in range(1, len(g["quarters"])):
        start = date.fromisoformat(ends[k - 1]) + timedelta(days=1)
        days.append((date.fromisoformat(g["issued_in_release"][k]) - start).days)
    return min(days), max(days)


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return minus_sign(f"{value:+.{digits}f}{suffix}")


def num(value: float, digits: int = 1) -> str:
    return minus_sign(f"{value:.{digits}f}")


def usd_bn(value_m: float, digits: int = 1) -> str:
    """US$ millions printed as billions, sign outside the symbol."""
    return f"{'−' if value_m < 0 else ''}US${abs(value_m) / 1000:,.{digits}f}B"


def usd_m(value_m: float) -> str:
    return f"{'−' if value_m < 0 else ''}US${abs(value_m):,.0f}M"


def usd_eps(value: float) -> str:
    return f"{'−' if value < 0 else ''}US${abs(value):.2f}"


def rounded(values, digits: int = 6):
    return [None if v is None else round(v, digits) for v in values]


def pct(current: float, base: float) -> float:
    return (current / base - 1) * 100.0


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


def gross_margin(s: dict) -> list[float]:
    inc = s["income_usd_m"]
    return [g / r * 100 for g, r in zip(inc["gross_profit"], inc["revenue"])]


def operating_margin(s: dict) -> list[float]:
    inc = s["income_usd_m"]
    return [o / r * 100 for o, r in zip(inc["operating_income"], inc["revenue"])]


def net_debt(s: dict) -> list[float]:
    b = s["balance_sheet_usd_m"]
    return [d - c for d, c in zip(b["total_debt"], b["cash_and_investments"])]


def capex_gross(s: dict) -> list[float]:
    return s["cash_flow_usd_m"]["capex_gross"]


def charge_note(s: dict, quarter: str) -> str:
    """The sourced one-line reason for a quarter's outlier, or nothing.

    A sentence explaining why the worst quarter is the worst is only printed
    when the series carries a sourced event for that quarter; a roll that makes
    some other quarter the worst leaves the sentence out rather than pinning the
    old reason on a new quarter.
    """
    event = next((e for e in s.get("charge_events", []) if e["period"] == quarter), None)
    if not event:
        return ""
    return f"{qlab(quarter)}：{event['what']}（{event['release']} 新闻稿）。"


def recast_events(s: dict) -> list[dict]:
    return s.get("restatement_events", [])


def escrow_sentence(story: dict | None) -> str:
    """What the escrow line is, attached only to a quarter that has one, with the
    word for its sign: a mark-to-market can be a gain as well as a loss."""
    if not story or not story.get("escrow_mtm_loss_usd_m"):
        return ""
    v = story["escrow_mtm_loss_usd_m"]
    return (f"托管股份按市值重估在净利润里是 {usd_m(abs(v))} 的{'损失' if v > 0 else '收益'} —— "
            "托管股份是按安全飞地（Secure Enclave）项目付款进度释放给美国商务部的 Intel 股票"
            "（到期仍未释放的一半无偿交付、一半注销），按公允价值计为负债，"
            "Intel 股价上涨时负债变大、计为损失，下跌时计为收益；它不是现金。")


def client_renamed(s: dict) -> bool:
    cs = s["segments"]["client_segment"]
    return cs["renamed_in_release"] <= s["release_dates"][-1]


def client_label(s: dict) -> str:
    cs = s["segments"]["client_segment"]
    return f"{cs['name']}（原 {cs['former_name']}）" if client_renamed(s) else cs["former_name"]


def client_short(s: dict) -> str:
    cs = s["segments"]["client_segment"]
    return cs["name"] if client_renamed(s) else cs["former_name"]


def client_rename_sentence(s: dict) -> str:
    cs = s["segments"]["client_segment"]
    if not client_renamed(s):
        return ""
    return (f"{cs['former_name']} 在 {cs['renamed_in_release']} 的新闻稿里改名 {cs['name']}"
            f"（{cs['full_name']}），公司重印的上年同期数与原数逐格相同，只是改名。")


def current_values(s: dict) -> dict:
    """The latest reading of every quantity a threshold or a follow-up names."""
    seg = s["segments"]
    ext = s["foundry_external"]
    altera = ext["altera_usd_m"][-1]
    return {
        "non_gaap_gm": s["non_gaap_printed"]["gross_margin_pct_first_print"][-1],
        "dcai_margin": seg["dcai_oi"][-1] / seg["dcai_revenue"][-1] * 100,
        "foundry_external": ext["external_revenue_usd_m"][-1],
        "foundry_external_ex_altera": (ext["external_revenue_usd_m"][-1] - altera
                                       if altera is not None else None),
        "net_debt": net_debt(s)[-1] / 1000,
        "adjusted_fcf": s["cash_flow_usd_m"]["adjusted_fcf_printed"][-1],
    }


# ── section one: the guidance record ─────────────────────────────────────────
def revenue_record(s: dict) -> dict:
    """Score every revenue outlook against the revenue that was then reported.

    A point outlook has no bound to clear, so "cleared the upper bound" would
    be a category error for the fifteen quarters Intel guided that way; they are
    counted separately, as above or below the point.
    """
    g = s["guidance"]
    rev = s["income_usd_m"]["revenue"]
    P = s["periods"]
    rows = []
    for i, quarter in enumerate(g["quarters"]):
        lo, hi = g["revenue_lo_usd_bn"][i], g["revenue_hi_usd_bn"][i]
        actual = rev[P.index(quarter)] / 1000 if quarter in P else None
        rows.append({"quarter": quarter, "lo": lo, "hi": hi, "actual": actual,
                     "point": lo == hi})
    done = [r for r in rows if r["actual"] is not None]
    ranged = [r for r in done if not r["point"]]
    points = [r for r in done if r["point"]]
    return {
        "rows": rows,
        "ranged": ranged,
        "points": points,
        "ranged_above": [r for r in ranged if r["actual"] > r["hi"]],
        "ranged_below": [r for r in ranged if r["actual"] < r["lo"]],
        "points_above": [r for r in points if r["actual"] > r["hi"]],
        "points_below": [r for r in points if r["actual"] < r["lo"]],
        # a point hit exactly is neither above nor below; without its own bucket
        # it would silently fall out of the title's counts
        "points_equal": [r for r in points if r["actual"] == r["lo"]],
    }


def revenue_forms_sentence(g: dict) -> str:
    """Describe the outlook's revenue forms as runs of quarters, from the data.

    The widths are measured, not remembered: the range era has one quarter
    that was guided US$1.2B wide, and a sentence saying "US$1B ranges" would
    be false of it.
    """
    forms, quarters = g["revenue_form"], g["quarters"]
    runs, start = [], 0
    for k in range(1, len(forms) + 1):
        if k == len(forms) or forms[k] != forms[start]:
            runs.append((forms[start], start, k - 1))
            start = k
    width = lambda k: round((g["revenue_hi_usd_bn"][k] - g["revenue_lo_usd_bn"][k]) * 10, 1)
    parts = []
    for form, a, b in runs:
        span = f"{qlab(quarters[a])} 到 {qlab(quarters[b])}" if b > a else qlab(quarters[a])
        if form == "point_pm":
            halves = sorted({width(k) / 2 for k in range(a, b + 1)})
            parts.append(f"{span} 是「某数 ± US${'/'.join(num(h, 0) for h in halves)} 亿」，本图画成区间")
        elif form == "point":
            parts.append(f"{span} 只给一个「约」数，在图上是一条没有宽度的细线")
        else:
            ws = [width(k) for k in range(a, b + 1)]
            mode = max(set(ws), key=ws.count)
            odd = [(quarters[k], width(k)) for k in range(a, b + 1) if width(k) != mode]
            parts.append(f"{span} 是 US${num(mode, 0)} 亿宽的区间"
                         + (("（其中 " + "、".join(f"{qlab(q)} 宽 US${num(w, 0)} 亿" for q, w in odd) + "）")
                            if odd else ""))
    head = f"指引的形式换过{cn_count(len(runs) - 1)}次：" if len(runs) > 1 else ""
    return head + "；".join(parts) + "。"


def guidance_charts(s: dict) -> list[dict]:
    g = s["guidance"]
    P = s["periods"]
    rec = revenue_record(s)
    xl = [qlab(q) for q in g["quarters"]]
    lo = [r["lo"] for r in rec["rows"]]
    hi = [r["hi"] for r in rec["rows"]]
    actual = [None if r["actual"] is None else round(r["actual"], 3) for r in rec["rows"]]
    ranged, points = rec["ranged"], rec["points"]
    r_above, r_below = len(rec["ranged_above"]), len(rec["ranged_below"])
    r_in = len(ranged) - r_above - r_below
    p_above, p_below, p_eq = len(rec["points_above"]), len(rec["points_below"]), len(rec["points_equal"])
    point_quarters = [r["quarter"] for r in rec["rows"] if r["point"]]
    pending = [r["quarter"] for r in rec["rows"] if r["actual"] is None]
    misses = sorted(rec["ranged_below"] + rec["points_below"], key=lambda r: r["quarter"])
    band = {
        "ref": "EX_REVBAND",
        "kind": "range_band",
        "title": (f"收入指引：{len(ranged) + len(points)} 个已完结季度里，给区间的 {len(ranged)} 季有 "
                  f"{r_above} 季超上限、{r_in} 季落在区间内、{r_below} 季跌破下限；"
                  f"只给单点的 {len(points)} 季 {p_above} 季高于、{p_below} 季低于"
                  + (f"、{p_eq} 季持平" if p_eq else "")),
        "xlabels": xl,
        "xrot": 90,
        "xstep": 4,
        "lo": lo,
        "hi": hi,
        "actual": actual,
        "actual_color": "NAVY",
        # 43 per-point labels on one axis collide in every browser width; the
        # figures are in the guidance table in the audit drawer.
        "bar_labels": False,
        "names": {"range": "公司收入指引（区间或单点）", "actual": "实际收入",
                  "lo": "指引下限（US$B）", "hi": "指引上限（US$B）"},
        "fmt": "usd1",
        "label_fmt": "usd1",
        "ylab": "US$B",
        "note": ((lambda lead: f"色块是公司在上一季的业绩新闻稿里给的本季收入指引 —— 发布时本季已经开始了 "
                                f"{lead[0]}–{lead[1]} 天；菱形是随后报出的 GAAP 收入。")(outlook_lead_days(s))
                 + revenue_forms_sentence(g)
                 + (f"跌破的{cn_count(len(misses))}次是 "
                    + "、".join(f"{qlab(r['quarter'])}（{usd_bn(r['actual'] * 1000)} 对 "
                                f"{'US$' + num(r['lo'], 1) + 'B'}）" for r in misses)
                    + "。" if misses else "")
                 + (f"最后一格 {qlab(pending[-1])} 只有指引，实际值待披露。" if pending else "")
                 + "纵轴不自 0 起，但没有任何点被截掉。"),
        "src_extra": SRC_RELEASES + "指引取自每份新闻稿的 Business Outlook 表，并已与同一份新闻稿里的 GAAP 与 non-GAAP 指引调节表逐格核对。",
    }
    if pending:
        band["annot"] = f"{qlab(pending[-1])}：仅指引，实际值待披露"

    dev = midpoint_deviation(
        "EX_REVDEV", "收入", g["quarters"], lo, hi, actual, mode="pct",
        window=len(g["quarters"]), label=qlab, bar_labels=False, xstep=4,
        src_extra=SRC_RELEASES,
        extra_note=(" 单点指引的季度，中值就是那个点。"),
    )

    # gross margin: only the quarters it was guided
    P = s["periods"]
    ng = s["non_gaap_printed"]
    gm_q = [q for q, v in zip(g["quarters"], g["non_gaap_gross_margin_pct"])
            if v is not None and q in P]
    gm_dev = [ng["gross_margin_pct_first_print"][P.index(q)]
              - g["non_gaap_gross_margin_pct"][g["quarters"].index(q)] for q in gm_q]
    gm_up = sum(1 for v in gm_dev if v > 0.05)
    gm_down = sum(1 for v in gm_dev if v < -0.05)
    gm_eq = len(gm_dev) - gm_up - gm_down
    worst = min(range(len(gm_dev)), key=lambda k: gm_dev[k])
    best = max(range(len(gm_dev)), key=lambda k: gm_dev[k])
    om_q = [q for q, v in zip(g["quarters"], g["non_gaap_operating_margin_pct"]) if v is not None]
    band_q = [q for q, b in zip(g["quarters"], g["gross_margin_band"]) if b]
    gm = {
        "ref": "EX_GMDEV",
        "kind": "grouped_bars",
        "title": (f"non-GAAP 毛利率对指引：给过毛利率指引的 {len(gm_q)} 季里 {gm_up} 季高于、"
                  f"{gm_down} 季低于" + (f"、{gm_eq} 季与指引相同" if gm_eq else "") + f"；最差一次 {qlab(gm_q[worst])} 差 {signed(gm_dev[worst], 1, 'pp')}，"
                  f"最好一次 {qlab(gm_q[best])} {signed(gm_dev[best], 1, 'pp')}"),
        "xlabels": [qlab(q) for q in gm_q],
        "xrot": 90,
        "xstep": 4,
        "groups": [{"name": "实际 non-GAAP 毛利率 − 指引值", "color": "BLUE",
                    "values": rounded(gm_dev, 2)}],
        "bar_labels": False,
        "fmt": "pp1", "label_fmt": "pp1",
        "ylab": "pp vs 指引",
        "note": ("横轴只列公司给过毛利率指引的季度："
                 + (f"{qlab(band_q[0])} 到 {qlab(band_q[-1])} 给的是一个点「± 几个百分点」，" if band_q else "")
                 + (f"{qlab(om_q[0])} 到 {qlab(om_q[-1])} 这{cn_count(len(om_q))}季公司改为指引营业利润率、"
                    "没有毛利率指引，所以横轴在这里跳过；" if om_q else "")
                 + ("之后每季给一个点。" if om_q and all(
                     g["gross_margin_band"][k] is None for k, q in enumerate(g["quarters"])
                     if q > om_q[-1] and g["non_gaap_gross_margin_pct"][k] is not None) else "")
                 + "实际值用该季自己那份新闻稿首次印出的 non-GAAP 毛利率 —— "
                 "与指引同一口径；一年后重印时公司可能已经改了口径（见本页第三节）。"
                 + charge_note(s, gm_q[worst])),
        "src_extra": SRC_RELEASES,
    }

    eps_q = [q for q, v in zip(g["quarters"], g["non_gaap_eps_usd"]) if v is not None and q in P]
    eps_dev = [ng["eps_usd_first_print"][P.index(q)] - g["non_gaap_eps_usd"][g["quarters"].index(q)]
               for q in eps_q]
    e_up = sum(1 for v in eps_dev if v > 0.004)
    e_down = sum(1 for v in eps_dev if v < -0.004)
    e_eq = len(eps_dev) - e_up - e_down
    first_eps = next(q for q, v in zip(g["quarters"], g["non_gaap_eps_usd"]) if v is not None)
    eps = {
        "ref": "EX_EPSDEV",
        "kind": "grouped_bars",
        "title": (f"non-GAAP EPS 对指引：自 {qlab(first_eps)} 起 {len(eps_q)} 季里 {e_up} 季高于、"
                  f"{e_down} 季低于" + (f"、{e_eq} 季持平" if e_eq else "")),
        "xlabels": [qlab(q) for q in eps_q],
        "xrot": 90,
        "xstep": 4,
        "groups": [{"name": "实际 non-GAAP EPS − 指引值（US$）", "color": "NAVY",
                    "values": rounded(eps_dev, 2)}],
        "bar_labels": False,
        "fmt": "usd2", "label_fmt": "usd2",
        "ylab": "US$ vs 指引",
        "note": (f"公司从 {qlab(first_eps)} 那一季的展望开始给季度 EPS 指引；在那之前的展望里没有 EPS 这一行，"
                 f"所以本图从 {qlab(first_eps)} 起。低于指引的{cn_count(e_down)}季是 "
                 + "、".join(qlab(q) for q, v in zip(eps_q, eps_dev) if v < -0.004)
                 + "。实际值同样用首次印出的数。"),
        "src_extra": SRC_RELEASES,
    }
    return [band, dev, gm, eps]


# ── section two: the quarter ─────────────────────────────────────────────────
def quarter_charts(s: dict, story: dict | None) -> list[dict]:
    P = s["periods"]
    rev = s["income_usd_m"]["revenue"]
    yoy = [None if i < 4 else round(pct(rev[i], rev[i - 4]), 1) for i in range(len(P))]
    rated = [(i, v) for i, v in enumerate(yoy) if v is not None]
    fastest = max(rated, key=lambda t: t[1])[0]
    peak = max(range(len(P)), key=lambda i: rev[i])
    head = f"收入 {usd_bn(rev[-1])}、同比 {signed(yoy[-1])}"
    if fastest == len(P) - 1:
        head += f"，是 {len(rated)} 个可算同比的季度里最快的一季"
    if peak != len(P) - 1:
        head += f"；金额{'仍' if yoy[-1] > 0 else ''}低于 {qlab(P[peak])} 的 {usd_bn(rev[peak])}"
    revenue = {
        "ref": "EX_REV",
        "kind": "gs_bar",
        "title": head,
        "xlabels": [qlab(q) for q in P],
        "xstep": 4,
        "values": rounded([v / 1000 for v in rev], 3),
        "yoy": {"name": "同比（右轴）", "color": "GOLD", "values": yoy, "yfmt": "pct0"},
        "legend": "季度收入",
        "fmt": "usd1", "yfmt": "usd1", "label_fmt": "usd1",
        "ylab": "US$B",
        "ylab2": "同比 %",
        "note": ("GAAP 收入，每一季取自报出它的那份 10-Q 或 10-K。会进同比的口径事件有：53 周年（"
                 + "、".join(str(y) for y in s["company"]["fifty_three_week_years"])
                 + " 年，多出的一周都在第一季度）"
                 + "".join(f"；{e['date']} {e['what']}" for e in s.get("portfolio_events", [])
                           if e["date"] > s["period_ends"][0])
                 + "。业务出售或出表之后的季度不再含它的收入，而一年内的同比基数还含。"
                 f"前四格没有同比，因为本页的季度记录从 {qlab(P[0])} 开始。"),
        "src_extra": SRC_FILINGS,
    }
    out = [revenue]

    seg = s["segments"]
    SP = seg["periods"]
    client = client_label(s)
    names = [(client, "ccpg", "NAVY"), ("DCAI", "dcai", "MBLUE"),
             ("Intel Foundry", "foundry", "GOLD"), ("All Other", "all_other", "GRAY")]
    growth = {key: pct(seg[f"{key}_revenue"][-1], seg[f"{key}_revenue"][0]) for _, key, _ in names}
    lead = max(names[:3], key=lambda n: growth[n[1]])
    seg_rev = {
        "ref": "EX_SEGREV",
        "kind": "lines",
        "title": (f"四个分部的收入（现行口径 {len(SP)} 季）：{lead[0]} 从 "
                  f"{usd_bn(seg[lead[1] + '_revenue'][0])} 到 {usd_bn(seg[lead[1] + '_revenue'][-1])}，"
                  f"{signed(growth[lead[1]])}"),
        "xlabels": [qlab(q) for q in SP],
        "series": [{"name": zh, "color": color, "values": rounded(seg[f"{key}_revenue"])}
                   for zh, key, color in names],
        "end_label": True,
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M（含分部间收入）",
        "note": ("分部收入含分部间交易 —— Intel Foundry 的收入绝大部分来自给 Intel Products 代工，"
                 "所以四条线相加大于合并收入，差额是分部间抵销。"
                 "现行口径从 2025 年第一季度的新闻稿开始：NEX 并入 CCG 与 DCAI，2024 年各季被重述到这个口径。"
                 + client_rename_sentence(s)),
        "src_extra": SRC_RELEASES + "每季分部加抵销等于合并收入、分部营业利润加公司未分配与抵销等于合并营业利润，逐季核过。",
    }
    margin = {key: [o / r * 100 for o, r in zip(seg[f"{key}_oi"], seg[f"{key}_revenue"])]
              for _, key, _ in names[:3]}
    seg_margin = {
        "ref": "EX_SEGMARGIN",
        "kind": "lines",
        "title": (f"分部营业利润率：DCAI 从 {num(margin['dcai'][0])}% 到 {num(margin['dcai'][-1])}%，"
                  f"{client_short(s)} {num(margin['ccpg'][-1])}%，Intel Foundry {num(margin['foundry'][-1])}%"),
        "xlabels": [qlab(q) for q in SP],
        "series": [{"name": zh, "color": color, "values": rounded(margin[key], 1)}
                   for zh, key, color in names[:3]],
        "end_label": True,
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1",
        "ylab": "分部营业利润 / 分部收入 %",
        "note": ("分母是含分部间交易的分部收入。Intel Foundry 的收入大部分是向 Intel Products 的内部转移价"
                 "（公司说内部价格意在接近市场价），所以它的利润率取决于这个内部定价，不是纯粹对外经营的利润率。"
                 "股权激励、重组与收购摊销记在公司未分配费用里，不在任何一个分部。"),
        "src_extra": "由上一张图的同一组分部数相除得到（D）。",
    }
    out += [seg_rev, seg_margin]

    if story:
        rc = story["eps_reconciliation"]
        legs = [leg for leg in rc["legs"] if round(leg["value"], 2) != 0]
        big = max(legs, key=lambda leg: abs(leg["value"]))
        others = [leg for leg in legs if leg is not big]
        rest = sum(leg["value"] for leg in others)
        if abs(rc["gaap"] + sum(leg["value"] for leg in legs) - rc["non_gaap"]) >= 0.015:
            raise ValueError("quarter_story EPS reconciliation legs do not close to non-GAAP EPS")
        bridge = {
            "ref": "EX_EPSBRIDGE",
            "kind": "grouped_bars",
            "title": (f"GAAP EPS {usd_eps(rc['gaap'])} 到 non-GAAP {usd_eps(rc['non_gaap'])}："
                      f"{big['name']}一项就是 {usd_eps(big['value'])}"),
            "xlabels": ["GAAP EPS", big["name"], f"其余{cn_count(len(others))}项合计", "non-GAAP EPS"],
            "groups": [{"name": "每股（US$）", "color": "NAVY",
                        "values": rounded([rc["gaap"], big["value"], rest, rc["non_gaap"]], 2)}],
            "bar_labels": True,
            "fmt": "usd2", "label_fmt": "usd2",
            "ylab": "US$ / 股",
            "note": ("中间两根是公司调节表里的调整项。" + escrow_sentence(story)
                     + "其余各项是：" + "、".join(f"{leg['name']} {usd_eps(leg['value'])}" for leg in others)
                     + "。"),
            "src_extra": rc["source"] + "。",
        }
        out.append(bridge)
    return out


# ── section three: margins over ten years, and a definition that moved ──────
def margin_charts(s: dict) -> list[dict]:
    P = s["periods"]
    gm = gross_margin(s)
    om = operating_margin(s)
    ng = s["non_gaap_printed"]["gross_margin_pct_first_print"]
    hi = max(range(len(P)), key=lambda i: gm[i])
    lo = min(range(len(P)), key=lambda i: gm[i])
    margins = {
        "ref": "EX_MARGINS",
        "kind": "lines",
        "title": (f"GAAP 毛利率 {len(P)} 季：最高 {num(gm[hi])}%（{qlab(P[hi])}），"
                  f"最低 {num(gm[lo])}%（{qlab(P[lo])}），本季 {num(gm[-1])}%"),
        "xlabels": [qlab(q) for q in P],
        "xstep": 4,
        "series": [
            {"name": "GAAP 毛利率", "color": "NAVY", "values": rounded(gm, 2)},
            {"name": "non-GAAP 毛利率（首次印出）", "color": "MBLUE", "values": ng},
            {"name": "GAAP 营业利润率", "color": "RED", "values": rounded(om, 2)},
        ],
        "end_label": True,
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1",
        "ylab": "占收入 %",
        "note": ("GAAP 两条由报表现算（毛利 / 收入、营业利润 / 收入）；non-GAAP 毛利率用每季自己那份新闻稿"
                 "首次印出的数，口径随公司当时的定义。" + charge_note(s, P[lo])),
        "src_extra": SRC_FILINGS + "non-GAAP 一条" + SRC_RELEASES,
    }

    npr = s["non_gaap_printed"]
    pairs = [(i, a, b) for i, (a, b) in enumerate(zip(npr["eps_usd_first_print"],
                                                     npr["eps_usd_year_ago_reprint"]))
             if b is not None]
    moved = [(i, a, b) for i, a, b in pairs if abs(a - b) > 0.004]
    gm_moved = [i for i, (a, b) in enumerate(zip(npr["gross_margin_pct_first_print"],
                                                npr["gross_margin_pct_year_ago_reprint"]))
                if b is not None and abs(a - b) > 0.04]
    years = sorted({P[i][:4] for i, _, _ in moved})
    events = recast_events(s)
    explained = {e["restated_year"] for e in events}
    unexplained = sorted({P[i][:4] for i, _, _ in moved} | {P[i][:4] for i in gm_moved}) 
    unexplained = [y for y in unexplained if y not in explained]
    if unexplained:
        raise ValueError(f"first print and reprint differ in {unexplained}, which no "
                         "`restatement_events` entry restates: read those releases and record why")
    recast = {
        "ref": "EX_RECAST",
        "kind": "grouped_bars",
        "title": (f"同一季度的 non-GAAP EPS，一年后被公司重印成另一个数：{len(pairs)} 个有重印的季度里 "
                  f"{len(moved)} 个变了，全部落在 {'、'.join(years)} 年"),
        "xlabels": [qlab(P[i]) for i, _, _ in moved],
        "xrot": 90,
        "groups": [
            {"name": "该季自己的新闻稿首次印出", "color": "NAVY", "values": [a for _, a, _ in moved]},
            {"name": "一年后新闻稿的上年同期列", "color": "GOLD", "values": [b for _, _, b in moved]},
        ],
        "bar_labels": False,
        "fmt": "usd2", "label_fmt": "usd2",
        "ylab": "non-GAAP EPS（US$）",
        "note": ("每份新闻稿都把一年前那一季并排再印一次，所以每个季度的 non-GAAP 数都能读两遍。"
                 f"读下来 {len(pairs)} 对里有 {len(moved)} 对 EPS 不同、{len(gm_moved)} 对毛利率不同，"
                 "而它们全部落在公司改口径、并重印上一年的年份里："
                 + "；".join(f"{e['release'][:4]} 年{e['what']}（重印 {e['restated_year']} 年）" for e in events)
                 + "。其余季度两遍逐分相同。<b>所以本页给指引打分只用首次印出的数</b> —— 它和指引是同一个定义；"
                 "重印的数与指引不可比。"),
        "src_extra": SRC_RELEASES,
    }
    return [margins, recast]


# ── section four: Intel Foundry ──────────────────────────────────────────────
def foundry_charts(s: dict) -> list[dict]:
    seg = s["segments"]
    old = s["foundry_2024_basis"]
    early = [q for q in old["periods"] if q not in seg["periods"]]
    P = early + seg["periods"]
    rev = [old["foundry_revenue"][old["periods"].index(q)] for q in early] + seg["foundry_revenue"]
    oi = [old["foundry_oi"][old["periods"].index(q)] for q in early] + seg["foundry_oi"]
    overlap = [q for q in old["periods"] if q in seg["periods"]]
    d_rev = [seg["foundry_revenue"][seg["periods"].index(q)] - old["foundry_revenue"][old["periods"].index(q)]
             for q in overlap]
    d_oi = [seg["foundry_oi"][seg["periods"].index(q)] - old["foundry_oi"][old["periods"].index(q)]
            for q in overlap]
    cur = seg["foundry_oi"]
    smallest = max(range(len(cur)), key=lambda i: cur[i])
    total_loss = -sum(cur)
    head = (f"Intel Foundry 现行口径 {len(cur)} 季累计经营{'亏损' if total_loss > 0 else '盈利'} "
            f"{usd_bn(abs(total_loss))}；本季{'亏损' if oi[-1] < 0 else '盈利'} {usd_bn(abs(oi[-1]))}、"
            f"收入 {usd_bn(rev[-1])}")
    if oi[-1] < 0 and smallest == len(cur) - 1:
        head += f"，亏损是现行口径 {len(cur)} 季里最小的一季"
    chart = {
        "ref": "EX_FOUNDRY",
        "kind": "grouped_bars",
        "title": head,
        "xlabels": [qlab(q) for q in P],
        "xrot": 90,
        "groups": [
            {"name": "分部收入（含给 Intel Products 的内部代工）", "color": "GOLD", "values": rev},
            {"name": "分部营业利润", "color": "RED", "values": oi},
        ],
        "bar_labels": False,
        "fmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M",
        "break_at": len(early),
        "break_label": "2025 年重述口径",
        "note": (f"Intel Foundry 是 2024 年才设立的报告分部，公司只把它的季度数重述回 {qlab(P[0])}；"
                 "更早只有年度数。竖线两侧口径不同：左边是 2024 年的口径，右边是 2025 年起重述后的口径。"
                 f"两套口径都印过的{cn_count(len(overlap))}个季度（{'、'.join(qlab(q) for q in overlap)}）上，"
                 f"收入差 {'、'.join(signed(v, 0, '') for v in d_rev)}（US$M），"
                 f"营业利润差 {'、'.join(signed(v, 0, '') for v in d_oi)}（US$M），"
                 f"所以本图不把两段连成一条，标题里的累计也只加竖线右侧；左侧 {cn_count(len(early))}季"
                 f"另有经营{'亏损' if sum(oi[:len(early)]) < 0 else '盈利'} {usd_bn(abs(sum(oi[:len(early)])))}。"
                 + charge_note(s, P[min(range(len(oi)), key=lambda i: oi[i])])),
        "src_extra": ("竖线左侧取自 2024-04-25 8-K EX-99.2 的重述表与 2024 年各季新闻稿；右侧取自现行口径的"
                      "各季新闻稿，其中 2024 年四季用一年后新闻稿的上年同期列。"),
    }
    out = [chart]

    ext = s["foundry_external"]
    EP = ext["periods"]
    ev = ext["external_revenue_usd_m"]
    al = ext["altera_usd_m"]
    decon_q = quarter_of(ext["altera_deconsolidated_on"])
    decon = EP.index(decon_q)
    ex_alt = [None if a is None else e - a for e, a in zip(ev, al)]
    before = ev[:decon]
    hidden = [q for q in ext["altera_undisclosed"] if q in EP]
    now = (f"本季 {usd_m(ev[-1])}，扣掉 Altera 关联方收入 {usd_m(al[-1])} 后 {usd_m(ex_alt[-1])}"
           if al[-1] is not None else f"本季 {usd_m(ev[-1])}，Altera 的份额未披露")
    jump = next((k for k in range(decon, len(EP)) if ev[k] > max(before)), None)
    disclosed = [(EP[k], a) for k, a in enumerate(al) if a is not None]
    ext_chart = {
        "ref": "EX_FOUNDRYEXT",
        "kind": "grouped_bars",
        "title": (f"Intel Foundry 的外部收入：Altera 出表前每季 {usd_m(min(before))}–{usd_m(max(before))}，"
                  + now),
        "xlabels": [qlab(q) for q in EP],
        "groups": [
            {"name": "外部客户收入（公司口径）", "color": "GOLD", "values": ev},
            {"name": "Altera 关联方收入（本页视为外部收入的一部分）", "color": "GRAY", "values": al},
        ],
        "bar_labels": True,
        "fmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M",
        "note": (ext["what_it_is"] + f" Altera 在 {ext['altera_deconsolidated_on']} 出售 51% 后出表，从此成为 Intel Foundry 的外部客户，"
                 + (f"所以 {qlab(EP[jump])} 起的跳升有一部分只是同一笔生意换了记账位置。" if jump is not None else "")
                 + "公司没有明说 Altera 的关联方收入就在外部收入之内，本页按其性质（向 Altera 提供的晶圆代工服务）"
                   "视为其中一部分，所以「扣掉 Altera 后」的数是本页的推断。"
                 + (f"{'、'.join(qlab(q) for q in hidden)} 的 Altera 份额公司没有披露，图上那几格只有合计。" if hidden else "")
                 + "现行口径从 2025 年第一季度的重述开始，2024 年四季在重述前印的是 "
                 + "、".join(f"{v}" for v in ext["prior_basis_2024"]["external_revenue_usd_m"])
                 + "（US$M），公司没有说明是哪块业务被移走。"
                 f"与分部收入相比，外部收入本季只占 {num(ev[-1] / seg['foundry_revenue'][-1] * 100)}%。"),
        "src_extra": (ext["source"]
                      + ("公司披露过的 Altera 份额：" + "、".join(f"{qlab(q)} {usd_m(a)}" for q, a in disclosed) + "。"
                         if disclosed else "")),
    }
    out.append(ext_chart)
    return out


# ── section five: capital, cash and debt ─────────────────────────────────────
def capital_charts(s: dict) -> list[dict]:
    P = s["periods"]
    cf = s["cash_flow_usd_m"]
    ocf, capex = cf["ocf"], capex_gross(s)
    rev = s["income_usd_m"]["revenue"]
    over = [i for i in range(len(P)) if capex[i] > ocf[i]]
    first_over = over[0] if over else None
    cash = {
        "ref": "EX_CASH",
        "kind": "grouped_bars",
        "title": (f"{len(P)} 季里经营现金流合计 {usd_bn(sum(ocf), 0)}、总资本开支 {usd_bn(sum(capex), 0)}"
                  + (f"；其中 {len(over)} 季资本开支超过经营现金流，最早一次在 {qlab(P[first_over])}"
                     if over else "")),
        "xlabels": [qlab(q) for q in P],
        "xstep": 4,
        "groups": [
            {"name": "经营现金流", "color": "NAVY", "values": rounded([v / 1000 for v in ocf], 3)},
            {"name": "总资本开支（购置不动产、厂房与设备）", "color": "GOLD",
             "values": rounded([v / 1000 for v in capex], 3)},
        ],
        "bar_labels": False,
        "fmt": "usd1", "label_fmt": "usd1",
        "ylab": "US$B（单季）",
        "note": ("总资本开支是现金流量表里「购置不动产、厂房与设备」的毛额，没有扣政府补贴与合伙人出资；"
                 f"{qlab(cf['financing_capex_first_quarter'])} 起还有一部分按延长付款条件购置、列在筹资活动里，"
                 "本页把两处相加，与公司新闻稿里的「gross capital expenditures」一致。"),
        "src_extra": SRC_FILINGS,
    }
    intensity = [c / r * 100 for c, r in zip(capex, rev)]
    peak = max(range(len(P)), key=lambda i: intensity[i])
    capint = {
        "ref": "EX_CAPINT",
        "kind": "lines",
        "title": (f"资本强度：从 {num(intensity[0])}%（{qlab(P[0])}）到峰值 {num(intensity[peak])}%"
                  f"（{qlab(P[peak])}），本季 {num(intensity[-1])}%"),
        "xlabels": [qlab(q) for q in P],
        "xstep": 4,
        "series": [{"name": "总资本开支 / 收入", "color": "NAVY", "values": rounded(intensity, 2)}],
        "end_label": True,
        "zero_base": True,
        "fmt": "pct1", "yfmt": "pct0", "label_fmt": "pct1",
        "ylab": "占收入 %",
        "note": "同一季的总资本开支除以同一季的 GAAP 收入（D）。季度之间付款节奏不均，看趋势比看单季更有意义。",
        "src_extra": SRC_FILINGS,
    }

    partner = cf["partner_contributions_net"]
    scip = s["equity"]["scip"]
    first_p = next(i for i, v in enumerate(partner) if v)
    axis = range(first_p, len(P))
    big_in = max(axis, key=lambda i: partner[i])
    big_out = min(axis, key=lambda i: partner[i])
    total = sum(partner[i] for i in axis)
    why = {scip["apollo_contribution_quarter"]:
               f"{qlab(scip['apollo_contribution_quarter'])} 的流入是 Apollo 投入爱尔兰 Fab 34 合资公司的 "
               f"US${num(scip['apollo_contribution_usd_bn'])}B。",
           quarter_of(scip["fab34_repurchase"]["closed"]):
               f"{qlab(quarter_of(scip['fab34_repurchase']['closed']))} 的流出是向合作方的分配：{scip['fab34_repurchase']['what']}"}
    tiers = {"own_release": "该季自己的新闻稿", "year_ago_release": "一年后新闻稿的上年同期列",
             "next_year_10q_comparative": "次年 10-Q 的比较列（年初至今相减，D）",
             "statement_as_filed": "该季 10-Q/10-K 的现金流量表（年初至今相减，D）"}
    used = [t for t in tiers if t in {cf["partner_contributions_net_source"][i] for i in axis}]
    funding = {
        "ref": "EX_PARTNER",
        "kind": "grouped_bars",
        "title": (f"合伙人出资净额：{qlab(P[first_p])} 起累计 {usd_bn(total)}；最大一笔流入在 "
                  f"{qlab(P[big_in])}（{usd_bn(partner[big_in])}）"
                  + (f"，最大一笔流出在 {qlab(P[big_out])}（{usd_bn(-partner[big_out])}）"
                     if partner[big_out] < 0 else "")),
        "xlabels": [qlab(q) for q in P[first_p:]],
        "xrot": 90,
        "groups": [
            {"name": "合伙人出资净额（出资 − 分配）", "color": "MBLUE",
             "values": rounded([v / 1000 for v in partner[first_p:]], 3)},
            {"name": "资本相关政府补贴到账", "color": "GREEN",
             "values": rounded([v / 1000 for v in cf["gov_incentives"][first_p:]], 3)},
        ],
        "bar_labels": False,
        "fmt": "usd1", "label_fmt": "usd1",
        "ylab": "US$B（单季）",
        "note": ("合伙人出资是晶圆厂共同投资安排（SCIP）里合作方投入的现金，列在筹资活动；"
                 f"{qlab(P[first_p])} 之前现金流量表里没有这一行。"
                 + "".join(text for q, text in why.items() if q in (P[big_in], P[big_out]))),
        "src_extra": ("每季按以下优先次序取数：" + "、".join(tiers[t] for t in used)
                      + "；取不到前一层才用后一层。"),
    }

    b = s["balance_sheet_usd_m"]
    nd = net_debt(s)
    net_cash = [P[i] for i in range(len(P)) if nd[i] < 0]
    debt = {
        "ref": "EX_DEBT",
        "kind": "lines",
        "title": (f"净债务（本页口径）{usd_bn(nd[-1])}：总债务 {usd_bn(b['total_debt'][-1])}、现金与短期投资 "
                  f"{usd_bn(b['cash_and_investments'][-1])}"
                  + (f"；{qlab(P[0])} 时是净现金 {usd_bn(-nd[0])}" if nd[0] < 0 else "")),
        "xlabels": [qlab(q) for q in P],
        "xstep": 4,
        "series": [
            {"name": "总债务（短期 + 长期）", "color": "RED", "values": rounded([v / 1000 for v in b["total_debt"]], 3)},
            {"name": "现金、短期投资与交易性资产", "color": "NAVY",
             "values": rounded([v / 1000 for v in b["cash_and_investments"]], 3)},
            {"name": "净债务", "color": "GOLD", "values": rounded([v / 1000 for v in nd], 3)},
        ],
        "end_label": True,
        "fmt": "usd1", "yfmt": "usd0", "label_fmt": "usd1",
        "ylab": "US$B（季末）",
        "note": ("净债务 = 总债务 − 现金、短期投资与交易性资产（D）；公司新闻稿不印这个数，口径是本页的。"
                 + (f"{len(P)} 个季末里是净现金的只有 {'、'.join(qlab(q) for q in net_cash)}，其余都是净债务。"
                    if net_cash else f"{len(P)} 个季末全部是净债务。")
                 + f"{qlab(b['fold_into_short_term_investments']['from'])} 起公司把原列在非流动资产的有价债务投资并入短期投资，"
                 f"按后来重述的口径 2021 年末的现金一侧会多 US${b['fold_into_short_term_investments']['dec_2021_restated_difference_usd_m']:,}M；"
                 "本图各季都用该季首次申报的数，不回改。股权投资不计入现金一侧。"),
        "src_extra": "各季末取自该季 10-Q 或 10-K 的资产负债表，并与同季新闻稿的资产负债表逐格核对。",
    }
    return [cash, capint, funding, debt]


# ── section six: shares ──────────────────────────────────────────────────────
def share_charts(s: dict, story: dict | None) -> list[dict]:
    P = s["periods"]
    eq = s["equity"]
    after = (story or {}).get("after_quarter")
    sh = s["balance_sheet_usd_m"]["shares_outstanding_m"]
    low = min(range(len(P)), key=lambda i: sh[i])
    shares = {
        "ref": "EX_SHARES",
        "kind": "lines",
        "title": (f"季末流通股：从 {sh[0]:,.0f}M {'回购' if any(s['cash_flow_usd_m']['buybacks'][:low + 1]) else '减'}"
                  f"到低点 {sh[low]:,.0f}M（{qlab(P[low])}），"
                  f"本季末 {sh[-1]:,.0f}M，比低点多 {num(pct(sh[-1], sh[low]))}%"),
        "xlabels": [qlab(q) for q in P],
        "xstep": 4,
        "series": [{"name": "季末已发行且流通的普通股", "color": "NAVY", "values": sh}],
        "end_label": True,
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "百万股",
        "note": ("取资产负债表股本一行括注的「issued and outstanding」股数。" + issuance_sentence(s)
                 + (f"截至 {eq['escrow_remaining_as_of']} 仍有 {eq['escrow_remaining_m']}M 股在托管中、不计入流通股；"
                    if eq["escrow_remaining_as_of"] == s["period_ends"][-1] else "")
                 + f"另有 2025 年发行的 {eq['warrants_m']}M 股认股权证，{eq['warrant_trigger']}。"
                 + (f"{after['what']}，不在本图里。" if after else "")),
        "src_extra": "各季末取自该季 10-Q 或 10-K 资产负债表的股本行。",
    }
    cf = s["cash_flow_usd_m"]
    div, buy = cf["dividends"], cf["buybacks"]
    last_buy = max((i for i, v in enumerate(buy) if v > 0), default=None)
    last_div = max((i for i, v in enumerate(div) if v > 0), default=None)
    returns = {
        "ref": "EX_RETURNS",
        "kind": "grouped_bars",
        "title": (f"股东回报：{len(P)} 季共 {usd_bn(sum(div) + sum(buy), 0)}"
                  + (f"，回购最后一次在 {qlab(P[last_buy])}" if last_buy is not None and last_buy < len(P) - 1 else "")
                  + (f"，股息最后一次在 {qlab(P[last_div])}" if last_div is not None and last_div < len(P) - 1 else "")),
        "xlabels": [qlab(q) for q in P],
        "xstep": 4,
        "groups": [
            {"name": "股息", "color": "NAVY", "values": rounded([v / 1000 for v in div], 3)},
            {"name": "回购", "color": "MBLUE", "values": rounded([v / 1000 for v in buy], 3)},
        ],
        "bar_labels": False,
        "fmt": "usd1", "label_fmt": "usd1",
        "ylab": "US$B（单季现金）",
        "note": (f"股息合计 {usd_bn(sum(div))}、回购合计 {usd_bn(sum(buy))}，都是现金流量表里的实付额。"),
        "src_extra": SRC_FILINGS,
    }
    return [shares, returns]


def issuance_sentence(s: dict) -> str:
    """How much of the share count's rise since the placements the placements explain."""
    P, eq = s["periods"], s["equity"]
    sh = s["balance_sheet_usd_m"]["shares_outstanding_m"]
    done = [it for it in eq["issuances"] if quarter_of(it["closed"]) <= P[-1]]
    if not done:
        return ""
    base = P.index(quarter_of(min(it["closed"] for it in done))) - 1
    placed = sum(it["shares_m"] for it in done)
    delta = sh[-1] - sh[base]
    return (f"{qlab(P[base])} 末到本季末流通股增加 {delta:,.0f}M，其中 {placed:,.0f}M 来自"
            f"{cn_count(len(done))}笔发行（"
            + "；".join(f"{it['counterparty']}，{it['kind']}，{it['closed']}，{num(it['shares_m'], 1)}M 股"
                       + (f"，另有 {num(it['escrow_m'], 1)}M 股进托管" if it.get("escrow_m") else "")
                       for it in done)
            + "），其余来自员工股权计划与托管股份的陆续释放等。")


# ── section seven: last quarter's questions, next quarter's lines ───────────
VERDICT_ORDER = ["通过", "部分通过", "未兑现", "未通过"]


def tracking_charts(s: dict, followup: dict | None, thresholds: dict | None) -> list[dict]:
    out = []
    cur = current_values(s)
    if followup:
        items = followup["items"]
        checked = [it for it in items if it.get("metric")]
        for item in checked:
            value = cur[item["metric"]]
            met = value >= item["threshold"]
            # met: the verdict may not be a failure; missed: it may not be a pass
            if (met and item["verdict"] in ("未兑现", "未通过")) or (not met and item["verdict"] == "通过"):
                raise ValueError(f"follow-up verdict {item['verdict']!r} contradicts the data for "
                                 f"{item['metric']}: {value} vs {item['threshold']}")
        counts = [(v, sum(1 for it in items if it["verdict"] == v)) for v in VERDICT_ORDER]
        counts = [(v, c) for v, c in counts if c]
        readings = []
        for k, it in enumerate(items, start=1):
            if it.get("metric") == "non_gaap_gm":
                got = f"实际 {num(cur['non_gaap_gm'])}%"
            elif it.get("metric") == "foundry_external":
                got = (f"公司口径 {usd_m(cur['foundry_external'])}"
                       + (f"，扣掉 Altera 关联方收入后（本页推断）{usd_m(cur['foundry_external_ex_altera'])}"
                          if cur["foundry_external_ex_altera"] is not None else ""))
            elif it.get("metric") == "adjusted_fcf":
                got = f"公司口径调整后自由现金流 {usd_bn(cur['adjusted_fcf'])}；" + it["reading"]
            else:
                got = it["reading"]
            readings.append(f"{k}. {it['question']} —— {it['verdict']}（{got}）")
        out.append({
            "ref": "EX_FOLLOWUP",
            "kind": "bars_labeled",
            "title": (f"上季留下的 {len(items)} 条待验证问题："
                      + "、".join(f"{c} 条{v}" for v, c in counts)),
            "xlabels": [v for v, _ in counts],
            "values": [c for _, c in counts],
            "fmt": "f0", "label_fmt": "f0", "yfmt": "f0",
            "ylab": "条",
            "note": ("问题与判定出自本地研究在 " + followup["asked_in"] + " 季报分析里写下的跟踪问题，"
                     f"不是公司的口径；能用数据判定的{cn_count(len(checked))}条由本页按数据复核。<br>"
                     + "<br>".join(readings)),
            "src_extra": "判定所用的数取自本季新闻稿与 10-Q。",
        })
    if thresholds:
        entries = []
        for item in thresholds["items"]:
            value = cur[item["key"]]
            if value is None:
                continue
            entries.append({**item, "current": value})
        breached = [e for e in entries if (e["current"] < e["threshold"]) == (e["direction"] == "up")]
        head = headroom_exhibit(
            (f"下季 {len(entries)} 条量化阈值：" + (f"{cn_count(len(breached))}条已经越线" if breached
                                                 else "全部仍在安全侧")),
            entries, "current",
            note=("每根柱是当前值离警戒线还有多远，按阈值的百分比计，正值 = 仍在安全侧。阈值出自"
                  + thresholds["set_in"] + "，是研究设定，不是公司指引。"
                  + ("已越线的是：" + "、".join(e["metric"] for e in breached) + "。" if breached else "")
                  + ("「剔除 Altera 的外部 Foundry 收入」一条用的是本页的推断（见第四节外部收入图的注）。"
                     if any(e["key"] == "foundry_external_ex_altera" for e in entries) else "")),
            src_extra="当前值由本页 series 现算。",
        )
        head["ref"] = "EX_HEADROOM"
        out.append(head)
        P = s["periods"]
        gm_item = next((e for e in entries if e["key"] == "non_gaap_gm"), None)
        if gm_item:
            ng = s["non_gaap_printed"]["gross_margin_pct_first_print"]
            below = [q for q, v in zip(P, ng) if v < gm_item["threshold"]]
            ex = threshold_exhibit(
                (f"non-GAAP 毛利率对 {num(gm_item['threshold'], 0)}% 警戒线：本季 {num(ng[-1])}%，"
                 f"{len(P)} 季里 {len(below)} 季在线下"),
                [qlab(q) for q in P], ng, gm_item["threshold"],
                fmt="pct1", ylab="non-GAAP 毛利率 %", actual_name="non-GAAP 毛利率（首次印出）",
                threshold_name=f"警戒线 {num(gm_item['threshold'], 0)}%",
                note=(f"加仓线是 {num(gm_item['add_threshold'], 0)}%。"
                      + (f"线下的季度最早一次是 {qlab(below[0])}。" if below else "")),
                src_extra=SRC_RELEASES, xstep=4)
            ex["ref"] = "EX_GMLINE"
            out.append(ex)
        nd_item = next((e for e in entries if e["key"] == "net_debt"), None)
        if nd_item:
            nd = [v / 1000 for v in net_debt(s)]
            over = [q for q, v in zip(P, nd) if v > nd_item["threshold"]]
            ex = threshold_exhibit(
                (f"净债务对 US${num(nd_item['threshold'], 0)}B 警戒线：本季末 US${num(nd[-1])}B，"
                 + (f"离线还有 US${num(nd_item['threshold'] - nd[-1])}B" if nd[-1] <= nd_item["threshold"]
                    else f"已越线 US${num(nd[-1] - nd_item['threshold'])}B")
                 + (f"；{len(P)} 季里越线的只有 {'、'.join(qlab(q) for q in over)}" if over else "")),
                [qlab(q) for q in P], rounded(nd, 3), nd_item["threshold"],
                fmt="usd1", ylab="US$B（季末）", actual_name="净债务（D）",
                threshold_name=f"警戒线 US${num(nd_item['threshold'], 0)}B",
                note="净债务口径同第五节。", src_extra="同第五节净债务图。", xstep=4)
            ex["ref"] = "EX_NDLINE"
            out.append(ex)
    return out


# ── the page ─────────────────────────────────────────────────────────────────
def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    rev = staging["income_usd_m"]["revenue"][-1]
    ng = staging["non_gaap_printed"]["gross_margin_pct_first_print"][-1]
    foundry = staging["segments"]["foundry_oi"][-1]
    return [f"Revenue {usd_bn(rev)}",
            f"non-GAAP 毛利率 {num(ng)}%",
            f"Foundry 营业利润 {usd_bn(foundry)}"]


def build_payload(staging: dict) -> dict:
    s = staging
    check_alignment(s)
    P = s["periods"]
    period = display_period(P[-1])
    latest = latest_block(s, period=period, period_end=s["period_ends"][-1],
                          release_date=s["release_dates"][-1])
    label = f"Intel {P[-1][:4]} 年第 {P[-1][5]} 季度业绩新闻稿"
    if not any(src["label"].startswith(label) for src in s["sources"]):
        raise ValueError(f"series `sources` has no entry for {label}: add it with the roll")

    story = stamped_block(s, "quarter_story", period)
    followup = stamped_block(s, "followup", period)
    thresholds = stamped_block(s, "thresholds", period)

    groups = [guidance_charts(s), quarter_charts(s, story), margin_charts(s),
              foundry_charts(s), capital_charts(s), share_charts(s, story),
              tracking_charts(s, followup, thresholds)]
    exhibits = number_exhibits([ex for group in groups for ex in group])
    resolve_exhibit_refs(exhibits)
    cuts, at = [], 0
    for group in groups:
        cuts.append(exhibits[at:at + len(group)])
        at += len(group)
    guide_ex, quarter_ex, margin_ex, foundry_ex, capital_ex, share_ex, track_ex = cuts

    inc = s["income_usd_m"]
    g = s["guidance"]
    rec = revenue_record(s)
    gm = gross_margin(s)
    ng = s["non_gaap_printed"]
    nd = net_debt(s)
    seg = s["segments"]
    cf = s["cash_flow_usd_m"]
    rev_yoy = pct(inc["revenue"][-1], inc["revenue"][-5])
    gi = g["quarters"].index(P[-1])
    mid = (g["revenue_lo_usd_bn"][gi] + g["revenue_hi_usd_bn"][gi]) / 2
    beat = pct(inc["revenue"][-1] / 1000, mid)
    nxt = g["quarters"][-1]
    first_table = exhibits[-1]["n"] + 1

    headline = (f"{P[-1][:4]} 年第 {P[-1][5]} 季度收入 {usd_bn(inc['revenue'][-1])}，同比 {signed(rev_yoy)}，"
                f"比指引中值{'高' if beat >= 0 else '低'} {num(abs(beat))}%；non-GAAP 毛利率 {num(ng['gross_margin_pct_first_print'][-1])}%、"
                f"non-GAAP EPS {usd_eps(ng['eps_usd_first_print'][-1])}，而 GAAP EPS "
                f"{usd_eps(inc['eps_diluted_usd'][-1])}"
                + ((lambda big: f" —— 两者之间最大的一项是{big['name']}，每股 {usd_eps(big['value'])}")
                   (largest_leg(story)) if story else "")
                + f"。同季调整后自由现金流 {usd_bn(cf['adjusted_fcf_printed'][-1])}，"
                f"季末净债务（本页口径）{usd_bn(nd[-1])}。")

    below = sorted(rec["ranged_below"] + rec["points_below"], key=lambda r: r["quarter"])
    gm_q = [q for q, v in zip(g["quarters"], g["non_gaap_gross_margin_pct"]) if v is not None and q in P]
    gm_devs = {q: ng["gross_margin_pct_first_print"][P.index(q)]
               - g["non_gaap_gross_margin_pct"][g["quarters"].index(q)] for q in gm_q}
    worst_q = min(gm_devs, key=gm_devs.get)
    lo_now, hi_now = g["revenue_lo_usd_bn"][gi], g["revenue_hi_usd_bn"][gi]
    rev_now = inc["revenue"][-1] / 1000
    gm_gap = ng["gross_margin_pct_first_print"][-1] - g["non_gaap_gross_margin_pct"][gi]
    rev_word = ("高于指引上限" if rev_now > hi_now else "低于指引下限" if rev_now < lo_now else "落在指引区间内")
    gm_word = "高于" if gm_gap > 0.05 else "低于" if gm_gap < -0.05 else "等于"
    afcf = cf["adjusted_fcf_printed"][-1]
    cards = [
        f'<article><span>本季</span><b>收入{rev_word}，non-GAAP 毛利率{gm_word}指引</b>'
        f'<p>收入比指引中值 {signed(beat)}，non-GAAP 毛利率 {num(ng["gross_margin_pct_first_print"][-1])}% 对指引 '
        f'{num(g["non_gaap_gross_margin_pct"][gi])}%；DCAI 营业利润率 '
        f'{num(seg["dcai_oi"][-1] / seg["dcai_revenue"][-1] * 100)}%。下季指引收入 '
        f'US${num(g["revenue_lo_usd_bn"][-1])}–{num(g["revenue_hi_usd_bn"][-1])}B、'
        f'non-GAAP 毛利率 {num(g["non_gaap_gross_margin_pct"][-1])}%。</p></article>',
        f'<article><span>指引记录</span><b>收入跌破指引 {len(below)} 次，毛利率最深一次差 '
        f'{signed(gm_devs[worst_q], 1, "pp")}</b>'
        f'<p>{len(rec["ranged"]) + len(rec["points"])} 个已完结季度里收入低于指引的是 '
        + "、".join(qlab(r["quarter"]) for r in below)
        + f'；给过毛利率指引的 {len(gm_q)} 季里 {sum(1 for v in gm_devs.values() if v < -0.05)} 季低于，'
        f'最深一次在 {qlab(worst_q)}。</p></article>',
        f'<article><span>资本</span><b>调整后自由现金流 {usd_bn(afcf)}，净债务 {usd_bn(nd[-1])}（本页口径）</b>'
        f'<p>本季合伙人出资净额 {usd_bn(cf["partner_contributions_net"][-1])}，总资本开支 '
        f'{usd_bn(capex_gross(s)[-1])}；季末流通股 '
        f'{s["balance_sheet_usd_m"]["shares_outstanding_m"][-1]:,.0f}M。</p></article>',
    ]

    def rows_of(values, fmt):
        return [fmt(v) if v is not None else "—" for v in values]

    tables = [{
        "n": first_table,
        "title": f"季度指引与实际（{cn_count(len(g['quarters']))}次展望，公司披露值）",
        "headers": ["季度", "指引发布日", "收入指引（US$B）", "实际收入", "non-GAAP 毛利率指引", "实际（首印）",
                    "non-GAAP EPS 指引", "实际（首印）"],
        "rows": [[q, g["issued_in_release"][k],
                  (f"{num(g['revenue_lo_usd_bn'][k])}–{num(g['revenue_hi_usd_bn'][k])}"
                   if g["revenue_lo_usd_bn"][k] != g["revenue_hi_usd_bn"][k] else f"约 {num(g['revenue_lo_usd_bn'][k])}"),
                  usd_bn(inc["revenue"][P.index(q)], 2) if q in P else "—",
                  (f"{num(g['non_gaap_gross_margin_pct'][k])}%" if g["non_gaap_gross_margin_pct"][k] is not None
                   else ("营业利润率 " + num(g["non_gaap_operating_margin_pct"][k]) + "%"
                         if g["non_gaap_operating_margin_pct"][k] is not None else "—")),
                  f"{num(ng['gross_margin_pct_first_print'][P.index(q)])}%" if q in P else "—",
                  usd_eps(g["non_gaap_eps_usd"][k]) if g["non_gaap_eps_usd"][k] is not None else "—",
                  usd_eps(ng["eps_usd_first_print"][P.index(q)]) if q in P else "—"]
                 for k, q in enumerate(g["quarters"])],
    }, {
        "n": first_table + 1,
        "title": "季度利润表与现金（公司披露值，利润率为 D）",
        "headers": ["季度", "收入", "GAAP 毛利率 D", "GAAP 营业利润", "归属 Intel 净利润", "GAAP 摊薄 EPS",
                    "经营现金流", "总资本开支", "季末净债务 D"],
        "rows": [[q, usd_bn(inc["revenue"][k], 2), f"{num(gm[k])}%", usd_bn(inc["operating_income"][k], 2),
                  usd_bn(inc["net_income_attributable_to_intel"][k], 2), usd_eps(inc["eps_diluted_usd"][k]),
                  usd_bn(cf["ocf"][k], 2), usd_bn(capex_gross(s)[k], 2), usd_bn(nd[k], 2)]
                 for k, q in enumerate(P)],
    }, {
        "n": first_table + 2,
        "title": "分部收入与营业利润（现行口径，US$M，公司披露值）",
        "headers": ["季度", f"{client_short(s)} 收入", "DCAI 收入", "Foundry 收入", "All Other 收入", "抵销", "合并收入",
                    f"{client_short(s)} 利润", "DCAI 利润", "Foundry 利润", "All Other 利润", "公司未分配", "抵销", "合并营业利润"],
        "rows": [[q] + rows_of([seg[k][i] for k in ("ccpg_revenue", "dcai_revenue", "foundry_revenue",
                                                    "all_other_revenue", "eliminations_revenue", "total_revenue",
                                                    "ccpg_oi", "dcai_oi", "foundry_oi", "all_other_oi",
                                                    "corporate_oi", "eliminations_oi", "total_oi")],
                                 lambda v: minus_sign(f"{v:,.0f}"))
                 for i, q in enumerate(seg["periods"])],
    }]
    if thresholds:
        cur = current_values(s)
        entries = [{**item, "current": cur[item["key"]]} for item in thresholds["items"]
                   if cur[item["key"]] is not None]
        tables.append(threshold_table(first_table + len(tables), "下季阈值的原始单位（研究设定）",
                                      entries, "current", "当前值"))
    tables.append(ai_capex_cycle_table(first_table + len(tables)))

    sections = [
        {"id": "guidance", "short": "指引记录",
         "title": f"{cn_count(len(g['quarters']))}次季度展望，兑现得怎样",
         "description": ("收入、毛利率与 EPS 三条指引，各自只在公司真正给过的季度上打分；"
                         "第一张图横跨全部展望，最后一格是下季。"),
         "exhibits": guide_ex},
        {"id": "quarter", "short": "本季",
         "title": (f"{period}：收入、分部" + ("，与 GAAP 和 non-GAAP 之间的那一项" if story else "")),
         "description": (f"季度收入在全部 {len(P)} 季里的位置、现行口径下的四个分部"
                         + ("，以及 GAAP 与 non-GAAP 每股收益之间差得最多的那一项" if story else "") + "。"),
         "exhibits": quarter_ex},
        {"id": "margins", "short": "利润率与口径",
         "title": f"毛利率 {len(P)} 季，与被重印过的旧季度",
         "description": "GAAP 与 non-GAAP 的毛利率、营业利润率，以及公司重印旧季度时改掉的数。",
         "exhibits": margin_ex},
        {"id": "foundry", "short": "Intel Foundry",
         "title": "代工分部：分部损益与外部收入",
         "description": "分部收入与营业利润（两段口径），以及外部客户收入里有多少来自 Altera。",
         "exhibits": foundry_ex},
        {"id": "capital", "short": "资本与负债",
         "title": "资本开支、合伙人资金与净债务",
         "description": "经营现金流对总资本开支、资本强度、晶圆厂合伙人的出资与分配，以及净债务的走向。",
         "exhibits": capital_ex},
        {"id": "shares", "short": "股本",
         "title": "股本与股东回报",
         "description": "季末流通股与股东回报的现金。",
         "exhibits": share_ex},
        {"id": "tracking", "short": "跟踪",
         "title": "与".join(part for part, on in (("上季的问题", followup), ("下季的警戒线", thresholds)) if on),
         "description": ("、".join(part for part, on in (("上季留下的待验证问题的判定", followup),
                                                        ("下季的量化阈值", thresholds)) if on)
                         + " —— 都是研究设定，不是公司口径。"),
         "exhibits": track_ex},
    ]
    sections = [sec for sec in sections if sec["exhibits"]]
    for index, section in enumerate(sections, start=1):
        section["title"] = f"{cn_ordinal(index)}、{section['title']}"
    order = " → ".join(section.pop("short") for section in sections)

    om_q = [q for q, v in zip(g["quarters"], g["non_gaap_operating_margin_pct"]) if v is not None]
    first_eps = next(q for q, v in zip(g["quarters"], g["non_gaap_eps_usd"]) if v is not None)
    notes = [
        f"本页按「{order}」{cn_count(len(sections))}段排列，以图为主；支撑表格收在核对抽屉里。",
        ("Intel 是美国本土申报人，每个季度都有 10-Q 或 10-K，每份业绩新闻稿都作为 8-K 的 EX-99.1 报送，全部原件在 EDGAR 上；"
         "本页 sources 直链每一份业绩新闻稿、本季 10-Q 与页面引用到的其他申报。"
         f"财年是 {s['company']['fiscal_year']}，本页按自然季度标注；"
         + "、".join(str(y) for y in s["company"]["fifty_three_week_years"]) + " 年是 53 周年，多出的一周都在第一季度。"),
        (lambda v: f"利润表、现金流量表与资产负债表的数取自各季 10-Q 与 10-K，第四季度的流量为全年减前三季；"
                   "每股收益与加权股数不能相减，第四季度取第四季度新闻稿的三个月列。"
                   f"另把 {qlab(v['from'])} 到 {qlab(min(v['to'], P[-1]))} 每季新闻稿的利润表独立再读了一遍，与报表逐格相同。")(
            s["verification"]["income_statement_reread_from_releases"]),
        (lambda v: f"指引取自每份新闻稿的 Business Outlook（{g['issued_in_release'][0]} 那份给出 {qlab(g['quarters'][0])} 的展望），"
                   f"{qlab(v['from'])} 到 {qlab(v['to'])} 的每个值都与同一份新闻稿里的 GAAP 与 non-GAAP 指引调节表核对过。"
                   f"收入指引的形式换过几次（见第一张图的注），毛利率在 {qlab(om_q[0])} 到 {qlab(om_q[-1])} "
                   f"这{cn_count(len(om_q))}季没有指引（公司改为指引营业利润率），EPS 从 {qlab(first_eps)} 起才有季度指引。"
                   "本页只在给过的季度上打分。")(s["verification"]["guidance_checked_against_reconciliation"]),
        ("non-GAAP 的实际值一律用该季自己那份新闻稿首次印出的数，因为那是与指引同一个定义的数；"
         + "公司在 " + "、".join(e["release"][:4] for e in recast_events(s) if e["kind"] == "non_gaap_definition")
         + " 年各改过一次 non-GAAP 定义并重印了上一年，第三节把这些重印的差别单独画出来。"),
        "2021 年四个季度的指引里，GAAP 与 non-GAAP 的收入指引不同：non-GAAP 剔除了待售的 NAND 业务。本页的收入一律用 GAAP，打分也用 GAAP 收入指引。2016 年第一季度的 non-GAAP 收入指引多出 Altera 递延收入减记的加回，同样不用。",
        ("分部数只画现行口径：2025 年起 NEX 并入 CCG 与 DCAI，2024 年各季被重述到这个口径。" + client_rename_sentence(s)
         + "Intel Foundry 的季度数最早只重述到 2023 年第一季度，更早只有年度数；2024 年的口径与 2025 年重述后的口径"
         "在四个季度上都印过，差额写在该图的注里。"),
        ("外部 Foundry 收入取自 10-Q 与 10-K 的分部附注；Altera 的关联方收入取自 10-Q 投资附注里 Altera 一段。"
         f"Altera 在 {s['foundry_external']['altera_deconsolidated_on']} 出售 51% 后出表，此后按外部客户计；"
         "公司没有明说这笔关联方收入就在外部收入之内，页面上「扣掉 Altera 后」的数是本页的推断。"),
        "净债务是本页的口径（总债务减现金、短期投资与交易性资产），公司新闻稿不印这个数；自由现金流用公司印出的调整后自由现金流，其定义在这些年里改过，见该图的注。",
        "跟踪一节的问题、判定与阈值出自本地研究的季报分析，是研究设定而不是公司口径；页面上凡能用数据判定的，都由本页从 series 现算并复核。",
        "本页不发布市场一致预期、评级、目标价与估值。",
        ("本页发布公司披露值与可复算的简单派生值（D 标记代表 Derived / 自算）"
         + ("；另有跟踪一节的研究判定与阈值，以及引用的电话会口径，都已在原处标明" if (followup or thresholds) else "")
         + "。"),
        (f"本页已知未接入：{period} 之后的数据"
         + (f"（{story['after_quarter']['date']} 的季后增发只在股本图注里提及）"
            if story and story.get("after_quarter") else "")
         + f"；下季展望（{display_period(nxt)}）只作为最后一格指引出现。"),
        "核对抽屉最后那张「AI capex 循环」是全站共用的跨页对照块，在每一页都逐字节相同，不是对本公司的判断。它追的是四家云厂现金资本开支到 NVDA 数据中心收入再到 TSM 晶圆这条链；它在折叠的抽屉里，不参与本页的论证。",
    ]

    return {
        "schema_version": "quarterly-dashboard/intc-v1",
        "page": {"slug": "intc", "language": "zh-CN"},
        "company": {"ticker": "INTC", "name": "Intel Corporation",
                    "group": "semiconductor_ai", "accounting_standard": "US GAAP"},
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · INTC",
        "title": f"Intel Corporation (INTC)：{period} 季报仪表盘",
        "subtitle": (f"截至 {latest['period_end']} · 发布 {latest['release_date']} · US GAAP · 美元列示 · "
                     "52 或 53 周财年，按自然季度标注 · 数据来自 10-Q、10-K 与业绩新闻稿（8-K）"),
        "headline": headline,
        "brief": (f'<h4>本季{cn_count(len(cards))}条主线</h4><div class="takeaway-grid">'
                  + "".join(cards) + '</div>'),
        "source": ('Source: <a href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany'
                   '&CIK=0000050863&type=8-K&dateb=&owner=include&count=40" rel="noopener">'
                   'Intel Corporation 在 SEC EDGAR 的申报（CIK 50863）</a>。'),
        "source_url": ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
                       "&CIK=0000050863&type=8-K&dateb=&owner=include&count=40"),
        "source_links": s["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": sections,
        "tables": tables,
        "notes": notes,
        "footer": "Intel quarterly results · 数据来自公司公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "intc.js"), payload, "intc")
    shell_dir = ROOT / "intc"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("INTC", "intc"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"INTC page: {charts} charts in {len(payload['sections'])} sections "
          f"+ {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
