"""Arm Holdings plc quarterly dashboard.

Arm is a UK company listed on Nasdaq since 2023-09-14 and a foreign private
issuer: the annual report is a 20-F and every quarter reaches EDGAR as two
6-Ks on the same day -- an earnings 6-K carrying the shareholder letter
(EX-99.2), and a second 6-K carrying the interim condensed consolidated
financial statements with full XBRL. The fiscal year ends on 31 March, so
Q1 FYE27 is April-June 2026; this site labels it 2026Q2.

**Three structural facts shape the page.**

First, the quarterly record starts at January-March 2022 and cannot start
earlier from Arm's own filings. Arm was taken private by SoftBank Group in
September 2016 and published nothing quarterly until the IPO prospectus, whose
one quarterly table begins with the quarter ended 31 March 2022. The ARM
Holdings plc that filed 6-Ks until 2016 is a different registrant with a
different perimeter; this page does not splice it on.

Second, the shareholder letter and the financial statements are two documents,
and they do not print the same things. From Q1 FYE27 the letter stopped
printing remaining performance obligations and the Total Access / Flexible
Access licence counts; the statements furnished the same day still carry RPO.
Where the two overlap this page reads both, and says which one each cell came
from.

Third, a third of revenue now comes from related parties: Arm China, in which
a SoftBank-controlled vehicle holds about 48%, and companies under SoftBank's
common control. The letter prints the total; the split is in the statements'
related-party note.

**A roll edits `series/arm.json` and nothing else** (CLAUDE.md §9). Every
period, count and figure on the page is computed from the series, and every
sentence the data could stop supporting is printed only while it does.
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
    cn_ordinal,
    delivery_band,
    display_period,
    latest_block,
    minus_sign,
    number_exhibits,
    round_half_up,
    stamped_block,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402

STAGING_PATH = ROOT / "series" / "arm.json"
DATA_DIR = ROOT / "data"

SOURCE_LETTERS = ("季度数取自各季股东信（6-K EX-99.2）与招股书（424B4）的季度表；"
                  "公司是外国私人发行人，全部原件都在 EDGAR 上。")
SOURCE_STATEMENTS = ("取自同日报送的中期财务报表 6-K 与 20-F 附注（XBRL）；"
                     "1–3 月季度由全年减前九个月得到，表里逐格标明。")


# ── small helpers ────────────────────────────────────────────────────────────
def pct(current: float, base: float) -> float:
    return (current / base - 1) * 100.0


def share(part: float, whole: float) -> float:
    return part / whole * 100.0


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return minus_sign(f"{value:+.{digits}f}{suffix}")


def num(value: float, digits: int = 1) -> str:
    return minus_sign(f"{value:.{digits}f}")


def usd_m(value: float, digits: int = 0) -> str:
    """US$ millions the way the letters print them: ``$1,289M``, ``−$65M``."""
    return f"{'−' if value < 0 else ''}${abs(value):,.{digits}f}M"


def yi(billions: float) -> str:
    """US$ billions in the unit Chinese prose counts in: ``2`` -> ``20 亿美元``."""
    return f"{billions * 10:g} 亿美元"


def usd_eps(value: float) -> str:
    return f"{'−' if value < 0 else ''}${abs(value):.2f}"


def rounded(values, digits: int = 6):
    return [None if v is None else round(v, digits) for v in values]


def quarter_cn(label: str) -> str:
    """``2026Q2`` -> ``2026 年第二季度``."""
    return f"{label[:4]} 年第{cn_ordinal(int(label[5]))}季度"


def fiscal_cn(label: str) -> str:
    """``Q1 FYE27`` -> ``FY27 Q1``, the form the prose uses."""
    quarter, year = label.split()
    return f"FY{year[3:]} {quarter}"


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


def span(values: list, periods: list[str]) -> tuple[list[str], list]:
    """Trim leading/trailing nulls: the axis starts where the series does."""
    idx = [i for i, v in enumerate(values) if v is not None]
    if not idx:
        return [], []
    return periods[idx[0]:idx[-1] + 1], values[idx[0]:idx[-1] + 1]


def at(block: dict, key: str, period: str, periods_key: str = "periods"):
    """The value of ``block[key]`` for ``period``, or None when it is not on the axis."""
    periods = block[periods_key]
    return block[key][periods.index(period)] if period in periods else None


def since(s: dict, last_printed: str) -> str:
    """「本季起」 while the stop is this quarter's news, 「2026Q2 起」 once it is history."""
    P = s["quarterly"]["periods"]
    k = P.index(calendar_of(last_printed))
    if k == len(P) - 1:
        raise ValueError(f"since(): {last_printed} is the latest quarter, so nothing has stopped; "
                         "the caller should not be describing a stop")
    return "本季起" if P[k + 1] == P[-1] else f"{P[k + 1]} 起"


def last_printed(values: list, dates: list[str]) -> str:
    """The last quarter-end at which a metric was printed."""
    return max(d for d, v in zip(dates, values) if v is not None)


def calendar_of(date: str) -> str:
    """``2026-06-30`` -> ``2026Q2``."""
    return f"{date[:4]}Q{(int(date[5:7]) - 1) // 3 + 1}"


# ── what 「本期」 means on this page ──────────────────────────────────────────
def period_view(s: dict) -> dict:
    q = s["quarterly"]
    i = len(q["periods"]) - 1
    period = q["periods"][i]
    prior = q["periods"].index(f"{int(period[:4]) - 1}{period[4:]}")
    return {
        "period": period, "i": i, "prior": prior,
        "fiscal": q["fiscal_labels"][i],
        "period_end": q["period_ends"][i],
        "release_date": q["first_printed_by"][i],
        "revenue": q["revenue"][i],
        "revenue_prior": q["revenue"][prior],
    }


# ── section one: the guided quarter ──────────────────────────────────────────
def guidance_rows(s: dict) -> list[dict]:
    return s["guidance"]["quarterly"]


def guidance_charts(s: dict, view: dict) -> list[dict]:
    rows = guidance_rows(s)
    labels = [r["period"] for r in rows]
    low = [r["revenue_low"] for r in rows]
    high = [r["revenue_high"] for r in rows]
    actual = [r["revenue_actual"] for r in rows]
    done = [k for k, r in enumerate(rows) if r["revenue_actual"] is not None]
    above = [k for k in done if actual[k] > high[k]]
    lead = 0
    for k in done:
        if k in above:
            lead += 1
        else:
            break
    after = done[lead:]
    after_above = [k for k in after if k in above]
    widths = [high[k] - low[k] for k in range(len(rows))]
    widened = next((k for k in range(1, len(rows)) if widths[k] != widths[k - 1]
                    and k in done and k >= lead), None)
    ended_with_widening = widened is not None and widened == lead
    form_switch = next((k for k in range(1, len(rows))
                        if rows[k]["revenue_form"] != rows[k - 1]["revenue_form"]), None)
    note = ""
    if lead >= 2 and after:
        note += (f"前{cn_count(lead)}个指引季（{labels[done[0]]}–{labels[done[lead - 1]]}）全部高于区间上沿，"
                 f"此后{cn_count(len(after))}季只有{cn_count(len(after_above))}季。")
    if ended_with_widening:
        note += (f"连续超出上沿的纪录，恰好在区间宽度从 {usd_m(widths[widened - 1])} "
                 f"放宽到 {usd_m(widths[widened])} 的那一季（{labels[widened]}）结束；")
    if form_switch is not None:
        note += (f"{labels[form_switch]} 起公司把区间写成「中值 ± {usd_m(widths[form_switch] / 2)}」，"
                 + ("宽度未变，只是写法变了。" if widths[form_switch] == widths[form_switch - 1]
                    else f"宽度同时从 {usd_m(widths[form_switch - 1])} 变成 {usd_m(widths[form_switch])}。"))
    band = delivery_band(
        "EX_REV_BAND", "收入", labels, low, high, actual,
        fmt="f0c", ylab="US$M（单季）", unit="US$M",
        venue="业绩发布", timing="该季<b>开始后约一个月</b>",
        src_extra=("区间取自上一季股东信的「Guidance and Results」表，实际值取自结算那一季的同一张表"
                   "的「Results」栏（即首次公布值）。"),
        extra_note=note,
        pending_label="实际值待下一封股东信",
    )

    excess = [None if actual[k] is None else actual[k] - (low[k] + high[k]) / 2 for k in range(len(rows))]
    half = [w / 2 for w in widths]
    first = [excess[k] for k in done[:lead]]
    later = [excess[k] for k in after]
    title = "收入超出指引中值多少，与区间半宽并排"
    if first and later:
        title = (f"超出指引中值：前{cn_count(len(first))}季平均 {usd_m(sum(first) / len(first))}、"
                 f"此后{cn_count(len(later))}季 {usd_m(sum(later) / len(later))}；"
                 f"区间半宽从 {usd_m(half[done[0]])} 起步、本季 {usd_m(half[done[-1]])}")
    tightest = min(half[j] for j in done[:lead]) if lead else None
    narrow = [k for k in after if excess[k] > tightest] if lead else []
    excess_ex = {
        "ref": "EX_REV_EXCESS",
        "kind": "grouped_bars",
        "title": title,
        "xlabels": [labels[k] for k in done],
        "groups": [
            {"name": "实际收入 − 指引中值", "color": "NAVY", "values": rounded([excess[k] for k in done], 1)},
            {"name": "区间半宽（超过它即高于上沿）", "color": "GOLD", "values": rounded([half[k] for k in done], 1)},
        ],
        "bar_labels": True,
        "fmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M",
        "xrot": 90,
        "note": ("深色柱比浅色柱高，就是那一季超出了区间上沿 —— 上一张图的结论在这里拆成两个量："
                 "公司超出中值多少，和它给自己留了多宽的区间。"
                 + (f"如果区间一直保持连续超出上沿那几季里最窄的半宽 {usd_m(tightest)}，"
                    f"后面{cn_count(len(after))}季里有{cn_count(len(narrow))}季仍会高于上沿 —— "
                    "这一句是假设，不是公司说过的话。" if lead and after else "")),
        "src_extra": "由上一张图的同一组区间与实际值相减得到（D）。",
    }

    eps_low = [r["eps_low"] for r in rows]
    eps_high = [r["eps_high"] for r in rows]
    eps_actual = [r["eps_actual"] for r in rows]
    recast = [c for row in s["republication_census"]["rows"] if row["row"] == "diluted_eps"
              and row["basis"] == "non_gaap" for c in row["changes"]]
    eps = delivery_band(
        "EX_EPS_BAND", "non-GAAP 摊薄 EPS", labels, eps_low, eps_high, eps_actual,
        fmt="usd2", ylab="US$ / 股", unit="US$",
        venue="业绩发布", timing="该季<b>开始后约一个月</b>",
        src_extra="区间与实际值取自股东信的「Guidance and Results」表。",
        extra_note=("实际值一律用结算那一季股东信印出的首次公布值，也就是指引当时所依据的口径。"
                    + (f"公司后来重述过其中{cn_count(len(recast))}季的 non-GAAP EPS"
                       f"（{'、'.join(f'{c['period']} {usd_eps(c['first'])}→{usd_eps(c['later'])}' for c in recast)}），"
                       "重述后的数不用来结算当时的指引。" if recast else "")),
        pending_label="实际值待下一封股东信",
    )
    return [band, excess_ex, eps]


# ── section two: the two revenue lines ───────────────────────────────────────
def revenue_charts(s: dict, view: dict) -> list[dict]:
    q = s["quarterly"]
    P = q["periods"]
    royalty_share = [share(r, t) for r, t in zip(q["royalty"], q["revenue"])]
    low_k = min(range(len(P)), key=lambda k: royalty_share[k])
    # a fiscal Q4 whose whole fiscal year is on the axis: the three quarters before it
    fiscal_q4 = [k for k, f in enumerate(q["fiscal_labels"]) if f.startswith("Q4") and k >= 3]
    peaks = [k for k in fiscal_q4 if q["license"][k] == max(q["license"][k - 3:k + 1])]
    mix = {
        "ref": "EX_MIX",
        "kind": "stacked_dual",
        "title": (f"{cn_count(len(P))}个季度的两条收入腿：本季 royalty {usd_m(q['royalty'][-1])}、"
                  f"license {usd_m(q['license'][-1])}，royalty 占 {num(royalty_share[-1])}%"),
        "xlabels": list(P),
        "stacks": [
            {"name": "Royalty（按客户出货计提）", "color": "NAVY", "values": rounded(q["royalty"])},
            {"name": "License and other（授权、服务等）", "color": "GOLD", "values": rounded(q["license"])},
        ],
        "line": {"name": "Royalty 占收入（右轴）", "color": "RED",
                 "values": rounded(royalty_share, 1), "ymax": 100},
        "fmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M（单季）",
        "ylab2": "Royalty 占比 %",
        "xrot": 90,
        "note": (f"royalty 占比最低的一季是 {P[low_k]}（{num(royalty_share[low_k])}%）。"
                 + (f"整个财年都在轴上的{cn_count(len(fiscal_q4))}个财年里，有{cn_count(len(peaks))}个的 license "
                    "在第四季（1–3 月）达到全年最高 —— license 按签约与交付确认，财年末集中，所以不宜做环比。"
                    if fiscal_q4 else "")
                 + "右轴显式设了 100% 上界，且写在 line 里：这一图型的右轴默认封顶在 60。"),
        "src_extra": SOURCE_LETTERS,
    }

    ry = [None if k < 4 else pct(q["royalty"][k], q["royalty"][k - 4]) for k in range(len(P))]
    ly = [None if k < 4 else pct(q["license"][k], q["license"][k - 4]) for k in range(len(P))]
    labels, _ = span(ry, P)
    start = P.index(labels[0])
    faster = sum(1 for k in range(start, len(P)) if ry[k] > ly[k])
    ry_k = [ry[k] for k in range(start, len(P))]
    yoy = {
        "ref": "EX_YOY",
        "kind": "lines",
        "title": (f"两条腿的同比：royalty 本季 {signed(ry[-1])}、license {signed(ly[-1])}；"
                  f"{cn_count(len(labels))}季里 royalty 跑赢 license 的有{cn_count(faster)}季"),
        "xlabels": labels,
        "series": [
            {"name": "Royalty 同比", "color": "NAVY", "values": rounded(ry_k, 1)},
            {"name": "License and other 同比", "color": "GOLD", "values": rounded(ly[start:], 1)},
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1",
        "end_label": True,
        "ylab": "同比 %",
        "xrot": 90,
        "note": (f"royalty 同比在窗口内的区间是 {signed(min(ry_k))} 到 {signed(max(ry_k))}，"
                 f"license 是 {signed(min(ly[start:]))} 到 {signed(max(ly[start:]))}，"
                 f"振幅是 royalty 的 {num((max(ly[start:]) - min(ly[start:])) / (max(ry_k) - min(ry_k)))} 倍 —— "
                 "license 按签约与交付一次性确认，royalty 按客户出货逐季计提。"
                 f"同比从 {labels[0]} 起算，因为季度记录从 {P[0]} 开始。"),
        "src_extra": SOURCE_LETTERS,
    }
    return [mix, yoy]


# ── section three: what the letter stopped printing ──────────────────────────
def visibility_charts(s: dict, view: dict) -> list[dict]:
    kpi, rs = s["kpi"], s["rpo_statements"]
    acv = {calendar_of(d): v for d, v in zip(kpi["dates"], kpi["acv"]) if v is not None}
    rpo = {calendar_of(d): v for d, v in zip(rs["dates"], rs["rpo"]) if v is not None}
    rpo_letter = {calendar_of(d): v for d, v in zip(kpi["dates"], kpi["rpo_letter"]) if v is not None}
    for period, value in rpo_letter.items():
        rpo.setdefault(period, value)
    P = s["quarterly"]["periods"]
    axis = [p for p in P if p in acv and p in rpo]
    # the axis must be contiguous for a line to mean anything
    first = next(k for k in range(len(axis)) if all(p in acv and p in rpo for p in P[P.index(axis[k]):]))
    axis = P[P.index(axis[first]):]
    letter_last = max(d for d, v in zip(kpi["dates"], kpi["rpo_letter"]) if v is not None)
    statements_only = [p for p in axis if p not in rpo_letter]
    rpo_yoy = [(p, pct(rpo[p], rpo[f"{int(p[:4]) - 1}{p[4:]}"])) for p in axis
               if f"{int(p[:4]) - 1}{p[4:]}" in rpo]
    acv_yoy = [(p, pct(acv[p], acv[f"{int(p[:4]) - 1}{p[4:]}"])) for p in axis
               if f"{int(p[:4]) - 1}{p[4:]}" in acv]
    acv_by = dict(acv_yoy)
    both = [(p, v, acv_by[p]) for p, v in rpo_yoy if p in acv_by]
    falling = [p for p, v, _ in both if v < 0]
    acv_falling = [p for p, _, a in both if a < 0]
    run = 0
    for _, v in reversed(rpo_yoy):
        if v < 0:
            run += 1
        else:
            break
    lines = {
        "ref": "EX_ACV_RPO",
        "kind": "lines",
        "title": (f"ACV 同比 {signed(acv_yoy[-1][1])}，RPO 同比 {signed(rpo_yoy[-1][1])}"
                  + (f"、已连续{cn_count(run)}季下降" if run >= 2 else "")
                  + (f"；股东信印到 {calendar_of(letter_last)} 为止，财务报表照印" if statements_only else "")),
        "xlabels": axis,
        "series": [
            {"name": "ACV（年化合同价值，股东信口径）", "color": "NAVY", "values": rounded([acv[p] for p in axis], 1)},
            {"name": "RPO（剩余履约义务）", "color": "RED", "values": rounded([rpo[p] for p in axis], 1)},
        ],
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "end_label": True,
        "ylab": "US$M（季末）",
        "xrot": 90,
        "note": ("两个量都不含未来的 royalty。ACV 是公司自定义的经营指标：所有有效授权合同的年化承诺费用；"
                 "RPO 是会计准则要求披露的已签约、未确认收入。"
                 f"两者都能算同比的{cn_count(len(both))}个季末里，RPO 同比为负的有{cn_count(len(falling))}个，"
                 + (f"ACV 为负的有{cn_count(len(acv_falling))}个。" if acv_falling else "ACV 一个都没有。")
                 + (f"股东信从 {fiscal_cn(s['quarterly']['fiscal_labels'][P.index(statements_only[0])])} 起不再印 RPO，"
                    "脚注给的理由是业务已扩展到量产芯片，这几个数对增长不再那么相关；"
                    f"同一天报送的中期财务报表仍在收入附注里披露它，所以本图最后"
                    f"{cn_count(len(statements_only))}个点只有财务报表印过。" if statements_only else "")),
        "src_extra": ("ACV 取自股东信与招股书的经营指标表；RPO 取自财务报表附注，"
                      f"与股东信印出的 RPO 在两者重叠的季末逐一核对（截至 {letter_last}）；"
                      "财务报表从 2023 年 9 月末起才有 XBRL 附注，更早的季末用股东信与招股书印出的值。"),
    }

    ata = [(d, a, f) for d, a, f in zip(kpi["dates"], kpi["ata_licenses"], kpi["afa_licenses"])
           if a is not None and f is not None]
    # contiguous quarterly run only
    run_dates = [ata[-1]]
    for item in reversed(ata[:-1]):
        prev = run_dates[0][0]
        want = calendar_of(prev)
        year, quarter = int(want[:4]), int(want[5])
        before = f"{year - 1}Q4" if quarter == 1 else f"{year}Q{quarter - 1}"
        if calendar_of(item[0]) == before:
            run_dates.insert(0, item)
        else:
            break
    labels = [calendar_of(d) for d, _, _ in run_dates]
    stopped = labels[-1] != P[-1]
    licences = {
        "ref": "EX_LICENCES",
        "kind": "bar_line_dual",
        "title": (f"Arm Total Access 授权从 {run_dates[0][1]} 家到 {run_dates[-1][1]} 家，"
                  f"Flexible Access 从 {run_dates[0][2]} 家到 {run_dates[-1][2]} 家"
                  + (f"；{since(s, run_dates[-1][0])}两个数都不再公布" if stopped else "")),
        "xlabels": labels,
        "bar": {"name": "Arm Total Access 有效授权数", "color": "NAVY", "values": [a for _, a, _ in run_dates]},
        "line": {"name": "Arm Flexible Access 有效授权数（右轴）", "color": "GOLD",
                 "values": [f for _, _, f in run_dates], "yfmt": "f0"},
        "fmt": "f0", "label_fmt": "f0", "yfmt": "f0",
        "ylab": "家（Total Access）",
        "ylab2": "家（Flexible Access）",
        "xrot": 90,
        "note": ("两类都是「一揽子」授权：Total Access 含最新产品，Flexible Access 不含最新产品、"
                 "客户流片时才按件付费。招股书说这两个家数「可能是」更多芯片采用 Arm 设计、"
                 "从而带来更多 royalty 的领先指标。"
                 + (f"{since(s, run_dates[-1][0])}它们与 RPO 在同一个脚注里、以同一个理由退役；"
                    "它们不在中期财务报表里，所以本页在最后一次被印出的季末停下。" if stopped else "")),
        "src_extra": "取自招股书与各季股东信的经营指标表。",
    }
    return [lines, licences]


# ── section four: related parties ────────────────────────────────────────────
def related_charts(s: dict, view: dict) -> list[dict]:
    rp = s["related_party"]
    q = s["quarterly"]
    P = rp["periods"]
    total_rev = [q["revenue"][q["periods"].index(p)] for p in P]
    rp_share = [share(t, r) for t, r in zip(rp["total"], total_rev)]
    derived = [p for p, d in zip(P, rp["derived"]) if d]
    peak = max(range(len(P)), key=lambda k: rp_share[k])
    first = min(range(len(P)), key=lambda k: rp_share[k])
    share_ex = {
        "ref": "EX_RELATED",
        "kind": "bar_line_dual",
        "title": (f"关联方收入 {usd_m(rp['total'][-1])}、占总收入 {num(rp_share[-1])}%；"
                  f"{cn_count(len(P))}季里最高是 {P[peak]} 的 {num(rp_share[peak])}%"),
        "xlabels": list(P),
        "bar": {"name": "来自关联方的收入", "color": "NAVY", "values": rounded(rp["total"])},
        "line": {"name": "占总收入（右轴）", "color": "RED", "values": rounded(rp_share, 1),
                 "yfmt": "pct1"},
        "fmt": "f0c", "label_fmt": "f0c", "yfmt": "f0c",
        "ylab": "US$M（单季）",
        "ylab2": "占总收入 %",
        "xrot": 90,
        "note": (f"占比最低的一季是 {P[first]}（{num(rp_share[first])}%）。"
                 "合计取自股东信利润表的「Revenue from related parties」一行，"
                 "与财务报表关联方附注逐季核对一致。"),
        "src_extra": SOURCE_LETTERS,
    }

    china, sb = rp["arm_china"], rp["softbank_controlled"]
    sb_first = next(k for k, v in enumerate(sb) if v >= 10)
    over = [P[k] for k in range(len(P)) if sb[k] > china[k]]
    china_yoy = pct(china[-1], china[-5]) if len(P) >= 5 else None
    split = {
        "ref": "EX_RELATED_SPLIT",
        "kind": "lines",
        "title": ("关联方里的两家：本季软银控制的公司 "
                  f"{usd_m(sb[-1], 1)}、Arm China {usd_m(china[-1], 1)}"
                  + (f"；前者高于后者的季度有{cn_count(len(over))}个" if over else "")),
        "xlabels": list(P),
        "series": [
            {"name": "Arm China", "color": "NAVY", "values": rounded(china, 1)},
            {"name": "软银控制的公司", "color": "RED", "values": rounded(sb, 1)},
        ],
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "end_label": True,
        "ylab": "US$M（单季）",
        "xrot": 90,
        "note": ("Arm China 是招股书口中「最大的单一客户」，由一家软银控制、Arm 持 10% 无投票权股份的实体"
                 "持有约 48%；财务报表说 Arm 来自中国的收入几乎全部经由它。"
                 + (f"Arm China 本季同比 {signed(china_yoy)}。" if china_yoy is not None else "")
                 + f"软银控制的公司从 {P[sb_first]} 起成为一条有量的收入线；本季附注把其中 "
                 f"{usd_m(rp['softbank_affiliate'][-1], 1)} 列在 Arm 向软银及其关联方提供技术咨询与顾问服务的协议名下"
                 + (f"。{'、'.join(over)} 这几季它比 Arm China 还大。" if over else "。")
                 + "附注里「Common Control in SoftBank」这个名目在 2024 年 9 月那份报表起换了含义"
                 "（此前指软银旗下其他小额交易对手），名字没变，本页按交易内容分开读；"
                 "Ampere 在 2025 年 11 月被软银收购后计入软银控制的公司，此前计入其他关联方。"
                 + (f"{cn_count(len(derived))}个 1–3 月季度（{'、'.join(derived)}）的拆分由 20-F 全年减前九个月得到。"
                    if derived else "")),
        "src_extra": SOURCE_STATEMENTS,
    }

    ca = s["contract_assets"]
    keep = [k for k, basis in enumerate(ca["related_basis"]) if basis == "balance-sheet parenthetical"]
    run = [keep[-1]]
    for k in reversed(keep[:-1]):
        want = calendar_of(ca["dates"][run[0]])
        year, qn = int(want[:4]), int(want[5])
        before = f"{year - 1}Q4" if qn == 1 else f"{year}Q{qn - 1}"
        if calendar_of(ca["dates"][k]) == before:
            run.insert(0, k)
        else:
            break
    labels = [calendar_of(ca["dates"][k]) for k in run]
    total = [ca["current_total"][k] for k in run]
    related = [ca["current_related"][k] for k in run]
    ca_share = [share(r, t) for r, t in zip(related, total)]
    sb_ca = ca["softbank_affiliate_note"][run[-1]]
    contract = {
        "ref": "EX_CONTRACT",
        "kind": "bar_line_dual",
        "title": (f"流动合同资产 {usd_m(total[-1])}，其中关联方 {usd_m(related[-1])}、"
                  f"占 {num(ca_share[-1])}%；{labels[0]} 是 {num(ca_share[0])}%"),
        "xlabels": labels,
        "bar": {"name": "流动合同资产（已确认收入、尚未开票）", "color": "NAVY", "values": rounded(total, 1)},
        "line": {"name": "其中关联方占比（右轴）", "color": "RED", "values": rounded(ca_share, 1),
                 "yfmt": "pct1"},
        "fmt": "f0c", "label_fmt": "f0c", "yfmt": "f0c",
        "ylab": "US$M（季末）",
        "ylab2": "关联方占比 %",
        "xrot": 90,
        "note": ("合同资产是已经记为收入、但还没有开票收款的部分；"
                 "关联方占比升高，说明关联方收入有相当一部分先进了资产负债表而不是现金。"
                 + (f"本季附注把其中 {usd_m(sb_ca, 1)} 列在软银关联方名下。" if sb_ca is not None else "")
                 + f"本图从 {labels[0]} 起，那是资产负债表连续单列关联方部分的第一个季末。"),
        "src_extra": "取自各期资产负债表括注（including contract assets from related parties）。",
    }
    return [share_ex, split, contract]


# ── section five: profit bases and cash ──────────────────────────────────────
def profit_charts(s: dict, view: dict) -> list[dict]:
    q = s["quarterly"]
    P = q["periods"]
    ng = q["non_gaap"]["operating_income"]
    g = q["gaap"]["operating_income"]
    labels, _ = span(ng, P)
    start = P.index(labels[0])
    rev = q["revenue"][start:]
    gm = [share(v, r) for v, r in zip(g[start:], rev)]
    nm = [share(v, r) for v, r in zip(ng[start:], rev)]
    gap = [b - a for a, b in zip(gm, nm)]
    widest = max(range(len(gap)), key=lambda k: gap[k])
    year_ago = len(gap) - 5
    margins = {
        "ref": "EX_MARGIN",
        "kind": "lines",
        "title": (f"本季 GAAP 营业利润率 {num(gm[-1])}%、non-GAAP {num(nm[-1])}%："
                  f"两者相差 {num(gap[-1])} 个百分点，一年前是 {num(gap[year_ago])}"),
        "xlabels": labels,
        "series": [
            {"name": "non-GAAP 营业利润率", "color": "NAVY", "values": rounded(nm, 1)},
            {"name": "GAAP 营业利润率", "color": "RED", "values": rounded(gm, 1)},
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1",
        "end_label": True,
        "ylab": "占收入 %",
        "xrot": 90,
        "note": ("两条线之间的距离几乎全是股权激励（SBC）及其雇主税："
                 f"差距最大的一季是 {labels[widest]}（{num(gap[widest])} 个百分点），"
                 "那是上市所在的季度。"
                 f"non-GAAP 用的是公司最新一次印出的口径 —— {recast_from(s)} 起公司把 SBC 相关雇主税也剔除，"
                 f"并重述了{cn_count(len(s['republication_census']['recast_footnotes']))}个旧季度，详见最后一节。"),
        "src_extra": SOURCE_LETTERS,
    }

    cash = q["cash"]
    capex = cash["purchases_of_property_and_equipment"]
    labels_c, _ = span(capex, P)
    c0 = P.index(labels_c[0])
    intensity = [share(capex[k], q["revenue"][k]) for k in range(c0, len(P))]
    fy = [(q["fiscal_labels"][k], k) for k in range(c0, len(P))]
    capex_ex = {
        "ref": "EX_CAPEX",
        "kind": "bar_line_dual",
        "title": (f"购置物业设备本季 {usd_m(capex[-1])}、占收入 {num(intensity[-1])}%；"
                  f"{labels_c[0]} 是 {usd_m(capex[c0])}、{num(intensity[0])}%"),
        "xlabels": labels_c,
        "bar": {"name": "购置物业与设备（现金）", "color": "NAVY", "values": rounded(capex[c0:])},
        "line": {"name": "占收入（右轴）", "color": "RED", "values": rounded(intensity, 1), "yfmt": "pct1"},
        "fmt": "f0c", "label_fmt": "f0c", "yfmt": "f0c",
        "ylab": "US$M（单季）",
        "ylab2": "占收入 %",
        "xrot": 90,
        "note": ("一家只卖设计的公司不需要多少物业设备。"
                 f"窗口内资本强度最高的一季是 {labels_c[max(range(len(intensity)), key=lambda k: intensity[k])]}"
                 f"（{num(max(intensity))}%）。公司在 2026 年 3 月宣布自研量产芯片 AGI CPU；"
                 "本图只画现金流量表上的购置额，不推断其中多少与芯片有关 —— 公司没有拆分。"),
        "src_extra": "取自各季股东信的自由现金流调节表（三个月口径）。",
    }

    fcf = cash["free_cash_flow"]
    wt = s["withholding_tax_on_vested_shares"]
    common = [p for p in labels_c if p in wt["periods"] and at(wt, "values", p) is not None]
    first = next(k for k in range(len(common)) if common[k:] == labels_c[labels_c.index(common[k]):])
    common = common[first:]
    fcf_v = [fcf[P.index(p)] for p in common]
    wt_v = [at(wt, "values", p) for p in common]
    ratio = share(wt_v[-1], fcf_v[-1]) if fcf_v[-1] > 0 else None
    fcf_ex = {
        "ref": "EX_FCF",
        "kind": "grouped_bars",
        "title": (f"本季自由现金流 {usd_m(fcf_v[-1])}；同季为员工归属股份代缴税款 {usd_m(wt_v[-1])}"
                  + (f"，相当于前者的 {num(ratio)}%" if ratio is not None else "")),
        "xlabels": common,
        "groups": [
            {"name": "non-GAAP 自由现金流", "color": "NAVY", "values": rounded(fcf_v)},
            {"name": "代缴员工归属股份税款（筹资活动）", "color": "RED", "values": rounded(wt_v)},
        ],
        "bar_labels": False,
        "fmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M（单季）",
        "xrot": 90,
        "note": ("公司的自由现金流 = 经营现金流 − 购置物业设备 − 购置无形资产 − 支付无形资产价款。"
                 "员工股份归属时公司代扣代缴的税款记在筹资活动里，不进这个定义，"
                 "但它是股份归属时公司实际付出去的现金。"
                 f"窗口内自由现金流为负的季度有{cn_count(sum(1 for v in fcf_v if v < 0))}个。"),
        "src_extra": ("自由现金流取自股东信调节表；代缴税款取自中期财务报表现金流量表"
                      "（year-to-date 相减得单季，D）。"),
    }
    return [margins, capex_ex, fcf_ex]


def recast_from(s: dict) -> str:
    """The letter that first printed a recast comparative: when the non-GAAP definition moved."""
    return min(f["letter"] for f in s["republication_census"]["recast_footnotes"])


def fy_revenue(s: dict, fiscal_year: str) -> float:
    """``FYE25`` -> the FY2025 revenue the income statement prints (not the letter's rounded cell)."""
    a = s["annual"]
    return a["revenue"][a["years"].index(f"FY20{fiscal_year[3:]}")]


# ── section six: guidance history and what was reprinted ─────────────────────
def record_charts(s: dict, view: dict) -> list[dict]:
    ann = s["guidance"]["annual"]
    labels, low, high, actual = [], [], [], []
    for year in ann:
        for k, v in enumerate(year["vintages"]):
            labels.append(f"{year['fiscal_year']} 第{cn_ordinal(k + 1)}版（{v['given_on']}）")
            low.append(v["revenue_low"])
            high.append(v["revenue_high"])
            actual.append(fy_revenue(s, year["fiscal_year"]))
    years = [y["fiscal_year"] for y in ann]
    last = s["guidance"]["annual_last_printed_in"]
    later_letters = [src for src in s["sources"] if src.get("kind") == "letter" and src["date"] > last]
    annual = {
        "ref": "EX_ANNUAL",
        "kind": "range_band",
        "title": (f"股东信里的全年收入指引只有{cn_count(len(ann))}个财年（{'、'.join(years)}），"
                  f"{last} 那封之后的{cn_count(len(later_letters))}封都没有"),
        "xlabels": labels,
        "xrot": 90,
        "lo": low, "hi": high, "actual": actual,
        "actual_color": "NAVY",
        "names": {"range": "全年收入指引区间", "actual": "该财年实际收入",
                  "lo": "指引下限（US$M）", "hi": "指引上限（US$M）"},
        "fmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M（财年）",
        "note": ("每个色块是一版全年指引，同一财年的各版并排；菱形是该财年最后印出的实际收入，"
                 "所以同一财年的菱形高度相同。"
                 + "；".join(f"{y['fiscal_year']} 的实际收入 {usd_m(fy_revenue(s, y['fiscal_year']))} "
                             + ("高于最后一版区间的上沿" if fy_revenue(s, y["fiscal_year"]) > y["vintages"][-1]["revenue_high"]
                                else "低于最后一版区间的下沿" if fy_revenue(s, y["fiscal_year"]) < y["vintages"][-1]["revenue_low"]
                                else "落在最后一版区间内")
                             for y in ann)
                 + "。此后各封股东信的指引表只有下一季一栏。"),
        "src_extra": "取自各季股东信的「Annual Guidance」表。",
    }

    groups = census_groups(s["republication_census"]["rows"])
    readings = sum(g["republished"] for g in groups)
    moved = sum(g["changed"] for g in groups)
    non_gaap = next(g for g in groups if g["key"] == "non_gaap")
    others = [g for g in groups if g["key"] != "non_gaap" and g["changed"]]
    recast = sorted({c["period"] for r in s["republication_census"]["rows"] if r["basis"] == "non_gaap"
                     for c in r["changes"]})
    census = {
        "ref": "EX_CENSUS",
        "kind": "grouped_bars",
        "title": (f"同一季度一年后再印一次：{readings} 个读数里 {moved} 个变了，"
                  f"其中 {non_gaap['changed']} 个是 non-GAAP"
                  + (f"，另外{cn_count(sum(g['changed'] for g in others))}个是"
                     + "、".join(g["label"] for g in others) if others else "")),
        "xlabels": [g["label"] for g in groups],
        "groups": [
            {"name": "被第二次印出的读数（行 × 季度）", "color": "NAVY",
             "values": [g["republished"] for g in groups]},
            {"name": "其中数字变了的", "color": "RED", "values": [g["changed"] for g in groups]},
        ],
        "bar_labels": True,
        "fmt": "f0", "label_fmt": "f0",
        "ylab": "读数个数",
        "xrot": 0,
        "note": ("每封股东信都把一年前的同一季并排印一遍（上市前的季度则是招股书与股东信各印一次），"
                 "本图逐行、逐季比对两次印出的数。"
                 + (f"non-GAAP 的变动全部落在 {'、'.join(recast)}：{recast_from(s)} 起公司把 SBC 相关雇主税"
                    f"从 non-GAAP 里剔除，并在比较栏里重述了这{cn_count(len(recast))}个季度，脚注写明了调整额"
                    f"（{'、'.join(f'{f['period']} {usd_m(f['adjustment'])}' for f in s['republication_census']['recast_footnotes'])}）。"
                    if recast else "")
                 + "".join(g["why"] for g in others)
                 + ("收入、GAAP 损益、关联方收入与现金流在所有重印里一次都没变。"
                    if all(g["changed"] == 0 for g in groups if g["key"] in ("revenue", "related", "gaap", "cash"))
                    else "")
                 + (f"另有{cn_count(sum(g['rounding'] for g in groups))}处只是少印了一位小数，不计为变动。"
                    if any(g["rounding"] for g in groups) else "")),
        "src_extra": "普查范围为招股书与本页 sources 里的全部股东信；比对在同一季度、同一行名之间进行。",
    }
    return [annual, census]


METRIC_NAMES = {"acv": "ACV", "rpo": "RPO", "ata": " Arm Total Access 授权家数",
                "afa": " Arm Flexible Access 授权家数", "employees": "员工数", "engineers": "工程师数"}


def census_groups(rows: list[dict]) -> list[dict]:
    """Fold the census rows into the six families the chart draws."""
    families = [
        ("revenue", "收入三行", lambda r: r["basis"] == "gaap" and r["row"] in ("revenue", "license", "royalty")),
        ("related", "关联方收入", lambda r: r["basis"] == "gaap" and r["row"] == "related_party_revenue"),
        ("gaap", "GAAP 损益其余行", lambda r: r["basis"] == "gaap"),
        ("non_gaap", "non-GAAP 损益", lambda r: r["basis"] == "non_gaap"),
        ("cash", "现金流", lambda r: r["basis"].startswith("cash")),
        ("metric", "经营指标", lambda r: r["basis"] == "metric"),
    ]
    out = {key: {"key": key, "label": label, "republished": 0, "changed": 0, "rounding": 0, "why": ""}
           for key, label, _ in families}
    for row in rows:
        key = next(k for k, _, test in families if test(row))
        out[key]["republished"] += row["periods_republished"]
        out[key]["changed"] += row["periods_changed"]
        out[key]["rounding"] += len(row.get("rounding_only", []))
        for c in row["changes"]:
            if key == "metric":
                name = METRIC_NAMES.get(row["row"], row["row"])
                out[key]["why"] += (f"经营指标里那一处是 {c['period']} 的{name}：先印 {c['first']:g}，"
                                    f"{c['later_in']} 的股东信改为 {c['later']:g}"
                                    + ("，脚注说明了原因。" if "footnote" in c.get("later_doc", "") else "。"))
    return list(out.values())


# ── the page ─────────────────────────────────────────────────────────────────
def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    q = staging["quarterly"]
    rev = q["revenue"][-1]
    return [f"Revenue {usd_m(rev)}",
            f"non-GAAP 营业利润率 {num(share(q['non_gaap']['operating_income'][-1], rev))}%",
            f"关联方收入占比 {num(share(q['related_party_revenue'][-1], rev))}%"]


def build_payload(staging: dict) -> dict:
    s = staging
    view = period_view(s)
    period = display_period(view["period"])
    latest = latest_block(s, period=period, period_end=view["period_end"],
                          release_date=view["release_date"])
    fiscal = view["fiscal"]
    if not any(source["label"].startswith(f"{fiscal} 股东信") for source in s["sources"]):
        raise ValueError(f"series `sources` has no {fiscal} shareholder letter: add it with the roll")
    story = stamped_block(s, "quarter_story", period)
    kpi = s["kpi"]
    rs = s["rpo_statements"]
    rpo_letter_last = last_printed(kpi["rpo_letter"], kpi["dates"])
    rpo_stopped = rpo_letter_last < rs["dates"][-1]
    counts_last = last_printed(kpi["ata_licenses"], kpi["dates"])
    counts_stopped = calendar_of(counts_last) != view["period"]

    sections_raw = [
        ("period", "本期", f"{quarter_cn(view['period'])}（{fiscal_cn(fiscal)}）：收入落在指引区间的哪里",
         "公司每季只给下一季的收入与 EPS 区间。本节把每一季的实际值放回当时的区间里，"
         "再把「高于上沿」拆成超出中值多少与区间有多宽两件事。",
         guidance_charts(s, view)),
        ("revenue", "两条收入腿", "royalty 与 license：一条按出货计提，一条按签约确认",
         "两条线的节奏完全不同，合在一起的收入增速要分开看。",
         revenue_charts(s, view)),
        ("visibility", "许可端的可见度", "股东信撤下的三个数",
         ("ACV、RPO 与两类一揽子授权的家数"
          + (f" —— 股东信{since(s, rpo_letter_last)}只剩 ACV，RPO 仍在财务报表里。" if rpo_stopped else "。")),
         visibility_charts(s, view)),
        ("related", "关联方", "三成收入来自同一个股东圈",
         "Arm China 与软银控制的公司，以及这部分收入在资产负债表上留下的痕迹。",
         related_charts(s, view)),
        ("profit", "利润与现金", "GAAP 与 non-GAAP 之间，以及资本开支",
         "营业利润率的两个口径、购置物业设备与自由现金流。",
         profit_charts(s, view)),
        ("record", "指引与重印", "全年指引的去向，和被重印过的数",
         "全年指引给过两个财年；同一季度一年后再印一次，有的数变了。",
         record_charts(s, view)),
    ]
    flat = [ex for *_, exs in sections_raw for ex in exs]
    exhibits = number_exhibits(flat)
    resolve_exhibit_refs(exhibits)

    q = s["quarterly"]
    P = q["periods"]
    i, j = view["i"], view["prior"]
    first_table = exhibits[-1]["n"] + 1
    gv = s["guidance"]["quarterly"]
    rp = s["related_party"]
    kpi = s["kpi"]
    tables = [{
        "n": first_table,
        "title": "季度损益（公司披露值；non-GAAP 为最新一次印出的口径）",
        "headers": ["期间", "财季", "首次印出", "收入", "License", "Royalty", "GAAP 营业利润",
                    "non-GAAP 营业利润", "GAAP 净利润", "关联方收入", "自由现金流"],
        "rows": [[P[k], q["fiscal_labels"][k], q["first_printed_by"][k],
                  usd_m(q["revenue"][k]), usd_m(q["license"][k]), usd_m(q["royalty"][k]),
                  usd_m(q["gaap"]["operating_income"][k]),
                  usd_m(q["non_gaap"]["operating_income"][k]) if q["non_gaap"]["operating_income"][k] is not None else "—",
                  usd_m(q["gaap"]["net_income"][k]),
                  usd_m(q["related_party_revenue"][k]) if q["related_party_revenue"][k] is not None else "—",
                  usd_m(q["cash"]["free_cash_flow"][k]) if q["cash"]["free_cash_flow"][k] is not None else "—"]
                 for k in range(len(P))],
    }, {
        "n": first_table + 1,
        "title": "季度指引与结算（股东信「Guidance and Results」表）",
        "headers": ["被指引的季度", "给出日", "收入区间", "实际收入", "EPS 区间", "实际 EPS",
                    "opex 指引（约）", "实际 opex"],
        "rows": [[r["period"], r["given_on"],
                  f"{usd_m(r['revenue_low'])}–{usd_m(r['revenue_high'])}",
                  usd_m(r["revenue_actual"]) if r["revenue_actual"] is not None else "待公布",
                  f"{usd_eps(r['eps_low'])}–{usd_eps(r['eps_high'])}",
                  usd_eps(r["eps_actual"]) if r["eps_actual"] is not None else "待公布",
                  usd_m(r["opex_approx"]),
                  usd_m(r["opex_actual"]) if r["opex_actual"] is not None else "待公布"]
                 for r in gv],
    }, {
        "n": first_table + 2,
        "title": "关联方收入拆分（中期财务报表附注；1–3 月季度为全年减前九个月 D）",
        "headers": ["期间", "来源", "关联方合计", "Arm China", "软银控制的公司", "其他关联方"],
        "rows": [[p, "全年减前九个月 D" if rp["derived"][k] else "附注三个月栏",
                  usd_m(rp["total"][k], 1), usd_m(rp["arm_china"][k], 1),
                  usd_m(rp["softbank_controlled"][k], 1), usd_m(rp["other"][k], 1)]
                 for k, p in enumerate(rp["periods"])],
    }, {
        "n": first_table + 3,
        "title": "经营指标（季末；股东信 / 招股书口径，RPO 另列财务报表口径）",
        "headers": ["日期", "ACV", "RPO（股东信）", "RPO（财务报表）", "Total Access", "Flexible Access",
                    "首次印出"],
        "rows": [[d,
                  usd_m(kpi["acv"][k]) if kpi["acv"][k] is not None else "—",
                  usd_m(kpi["rpo_letter"][k], 1) if kpi["rpo_letter"][k] is not None else "—",
                  (usd_m(s["rpo_statements"]["rpo"][s["rpo_statements"]["dates"].index(d)], 1)
                   if d in s["rpo_statements"]["dates"] else "—"),
                  str(kpi["ata_licenses"][k]) if kpi["ata_licenses"][k] is not None else "—",
                  str(kpi["afa_licenses"][k]) if kpi["afa_licenses"][k] is not None else "—",
                  kpi["printed_by"][k]]
                 for k, d in enumerate(kpi["dates"])],
    }]
    tables.append(ai_capex_cycle_table(first_table + len(tables)))

    rev, rev_prior = view["revenue"], view["revenue_prior"]
    ng_now = q["non_gaap"]["operating_income"][i]
    g_now = q["gaap"]["operating_income"][i]
    this_guide = next(r for r in gv if r["period"] == view["period"])
    next_guide = next((r for r in gv if r["revenue_actual"] is None), None)
    rp_share = share(q["related_party_revenue"][i], rev)
    rp_share_prior = share(q["related_party_revenue"][j], rev_prior)
    rpo_now, rpo_prior = rs["rpo"][-1], rs["rpo"][rs["dates"].index(f"{int(rs['dates'][-1][:4]) - 1}{rs['dates'][-1][4:]}")]
    acv_now = kpi["acv"][kpi["dates"].index(rs["dates"][-1])]
    acv_prior = kpi["acv"][kpi["dates"].index(f"{int(rs['dates'][-1][:4]) - 1}{rs['dates'][-1][4:]}")]
    position = ("高于区间上沿" if rev > this_guide["revenue_high"] else
                "低于区间下沿" if rev < this_guide["revenue_low"] else "落在区间内")

    headline = (f"{quarter_cn(view['period'])}（{fiscal_cn(fiscal)}）收入 {usd_m(rev)}，同比 "
                f"{signed(pct(rev, rev_prior))}，{position}"
                f"（指引 {usd_m(this_guide['revenue_low'])}–{usd_m(this_guide['revenue_high'])}）；"
                f"non-GAAP 营业利润率 {num(share(ng_now, rev))}%、GAAP {num(share(g_now, rev))}%。"
                f"关联方收入占 {num(rp_share)}%（上年同期 {num(rp_share_prior)}%）。"
                + (f"股东信{since(s, rpo_letter_last)}不再印 RPO，同日的财务报表仍印：{usd_m(rpo_now, 1)}，"
                   if rpo_letter_last < rs["dates"][-1] else f"RPO {usd_m(rpo_now, 1)}，")
                + f"同比 {signed(pct(rpo_now, rpo_prior))}，而 ACV 同比 {signed(pct(acv_now, acv_prior))}。")

    cards = [
        '<article><span>本期</span><b>'
        + f"收入{position}"
        + ("、EPS 高于上沿" if this_guide["eps_actual"] > this_guide["eps_high"] else "")
        + '</b>'
        f'<p>收入 {usd_m(rev)} 对指引 {usd_m(this_guide["revenue_low"])}–{usd_m(this_guide["revenue_high"])}；'
        f'non-GAAP EPS {usd_eps(this_guide["eps_actual"])} 对 '
        f'{usd_eps(this_guide["eps_low"])}–{usd_eps(this_guide["eps_high"])}。'
        + (f'下一季收入指引 {usd_m(next_guide["revenue_low"])}–{usd_m(next_guide["revenue_high"])}。'
           if next_guide else '')
        + '</p></article>',
        '<article><span>可见度</span><b>'
        + ("信里撤下 RPO，报表照印" if rpo_letter_last < rs["dates"][-1] else "RPO 与 ACV") + '</b>'
        f'<p>RPO {usd_m(rpo_now, 1)}、同比 {signed(pct(rpo_now, rpo_prior))}；'
        f'ACV {usd_m(acv_now)}、同比 {signed(pct(acv_now, acv_prior))}。'
        + (f'Total Access / Flexible Access 两个家数{since(s, counts_last)}与 RPO 在同一个脚注里退役。'
           if counts_stopped else '')
        + '</p></article>',
        '<article><span>关联方</span><b>三成收入来自同一个股东圈</b>'
        f'<p>关联方收入 {usd_m(q["related_party_revenue"][i])}，占 {num(rp_share)}%：'
        f'Arm China {usd_m(rp["arm_china"][-1], 1)}、软银控制的公司 {usd_m(rp["softbank_controlled"][-1], 1)}。'
        + (f'AGI CPU：信里写客户需求超过 {yi(story["demand_floor_usd_bn"])}（{story["demand_window"]}），'
           + ('与上一封信是同一个数' if story["demand_floor_usd_bn"] == story["demand_floor_prior_letter_usd_bn"]
              else f'上一封信是 {yi(story["demand_floor_prior_letter_usd_bn"])}')
           + f'；公司据以展望的机会仍是 {yi(story["opportunity_usd_bn"])}。'
           if story else '')
        + '</p></article>',
    ]

    sections = []
    for index, (sid, short, title, desc, exs) in enumerate(sections_raw, start=1):
        sections.append({"id": sid, "short": short, "title": f"{cn_ordinal(index)}、{title}",
                         "description": desc, "exhibits": exs})
    order = " → ".join(section.pop("short") for section in sections)

    derived_rp = [p for p, d in zip(rp["periods"], rp["derived"]) if d]
    gap_k = max(range(len(rp["periods"])), key=lambda k: abs(rp["unattributed"][k]))
    gap_p, gap_v = rp["periods"][gap_k], rp["unattributed"][gap_k]
    notes = [
        f"本页按「{order}」{cn_count(len(sections))}段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
        "Arm Holdings plc 在英国注册、在纳斯达克上市，按美国 GAAP 以美元列报，财年截至 3 月 31 日。本站按自然年季度标注：FY27 Q1 是 2026 年 4–6 月，记作 2026Q2。它是美国证券法下的外国私人发行人：年报为 20-F，每季在同一天报送两份 6-K —— 一份附股东信（EX-99.2），一份是带 XBRL 的中期简明合并财务报表。",
        f"季度记录的下限是 {P[0]}，而且不能更早：公司自己的文件里最早的季度表是招股书的「Three Months Ended」表，从 2022 年 1–3 月开始。Arm 在 1998–2016 年于伦敦与纳斯达克上市，2016 年 9 月被软银集团私有化，此后到 2023 年 9 月上市前不公布季度数。1999–2016 年在 EDGAR 上报送的 ARM Holdings plc 是另一个申报主体（CIK 1057997，2016-09-13 以 15-12G 注销登记；招股书说它 2018 年更名为 SVF HoldCo (UK) Limited），本页不把它接在同一条轴上。",
        "每封股东信把一年前的同一季并排印出，所以 2022Q3 以后的大多数季度被印过两次。2024 年 11 月起公司把 SBC 相关雇主税从 non-GAAP 里剔除，并在比较栏里重述了两个旧季度；本页的时间序列用最新一次印出的口径，结算指引时用首次印出的口径，两者在最后一节逐行对照。",
        "股东信与财务报表是两份文件，印的东西不完全一样。"
        + (f"股东信{since(s, rpo_letter_last)}不再印 RPO；RPO 仍在财务报表的收入附注里，本页从那里续上。"
           if rpo_stopped else "")
        + (f"两类一揽子授权的家数只在股东信与招股书里出现过，{since(s, counts_last)}不再印，本页停在它最后一次被印出的季末。"
           if counts_stopped else ""),
        "关联方收入的合计取自股东信的利润表（Revenue from related parties），拆分取自财务报表的关联方附注。附注里的名目换过：Arm China 一行先叫 Service Share Arrangement，FY26 的 20-F 起叫 IP Licensing Revenue；「Common Control in SoftBank」在 2024 年 9 月末那份报表起改指软银关联方的咨询与授权收入，原先那类小额交易改列 Other Entities Controlled By SoftBank Group —— 两者都是软银控制的公司，本页合并为一条。"
        + (f"{cn_count(len(derived_rp))}个 1–3 月季度没有单独的三个月附注，由 20-F 全年减第三季累计得到。" if derived_rp else "")
        + (f"合计与附注各交易对手之和的差额，除 {gap_p} 为 {usd_m(gap_v, 1)} 外都在 ±$0.5M 以内（附注到 $0.1M、合计到 $1M）；本页读过的文件没有交代那一季的差额。"
           if abs(gap_v) > 0.5 else ""),
        "non-GAAP 是公司自定义口径：剔除股权激励、SBC 相关雇主税、处置与重组费用、股权投资损益及其税务影响。本页照用公司印出的值，不自行调整。",
        "本页不发布市场一致预期、评级、目标价与估值；AGI CPU 的需求与机会只引用股东信原文里的数字，不据此做预测。",
        "本页只发布公司披露值与可复算的简单派生值；D 标记代表 Derived / 自算。",
        f"本页已知未接入：{quarter_cn(view['period'])}之后的任何数据；数据中心 royalty —— 股东信只写「同比翻倍以上」，本页读过的文件里没有它的绝对值，所以没有可画的数。",
        "核对抽屉最后那张「AI capex 循环」是全站共用的跨页对照块，在每一页都逐字节相同，不是对本公司的判断。它追的是四家云厂现金资本开支到 NVDA 数据中心收入再到 TSM 晶圆这条链；它在折叠的抽屉里，不参与本页的论证。",
    ]

    return {
        "schema_version": "quarterly-dashboard/arm-v1",
        "page": {"slug": "arm", "language": "zh-CN"},
        "company": {"ticker": "ARM", "name": "Arm Holdings plc",
                    "group": "semiconductor_ai", "accounting_standard": "US GAAP"},
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · ARM",
        "title": f"Arm Holdings plc (ARM)：{quarter_cn(view['period'])}（{fiscal_cn(fiscal)}）业绩仪表盘",
        "subtitle": (f"截至 {latest['period_end']} · 发布 {latest['release_date']} · US GAAP · 美元列示 · "
                     "3 月底制财年，本站按自然年季度标注 · "
                     "数据来自公司 6-K 股东信、中期财务报表、20-F 与招股书"),
        "headline": headline,
        "brief": (f'<h4>本期{cn_count(len(cards))}条主线</h4><div class="takeaway-grid">'
                  + "".join(cards) + '</div>'),
        "source": ('Source: <a href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany'
                   '&CIK=0001973239&type=6-K&dateb=&owner=include&count=40" rel="noopener">'
                   'Arm Holdings plc 在 SEC EDGAR 的申报（CIK 1973239）</a>。'
                   '公司为外国私人发行人，年度报告为 20-F，期间披露以 6-K 报送。'),
        "source_url": ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
                       "&CIK=0001973239&type=6-K&dateb=&owner=include&count=40"),
        "source_links": [{k: v for k, v in src.items() if k in ("label", "url")} for src in s["sources"]],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": sections,
        "tables": tables,
        "notes": notes,
        "footer": ("Arm Holdings quarterly results · 数据来自公司公开披露与透明自算 · "
                   "仅供研究，不构成投资建议"),
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "arm.js"), payload, "arm")
    shell_dir = ROOT / "arm"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("ARM", "arm"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"ARM page: {charts} charts in {len(payload['sections'])} sections "
          f"+ {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
