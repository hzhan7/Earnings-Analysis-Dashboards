#!/usr/bin/env python3
"""Build the MCO quarterly-results page.

Same four-part, chart-led shape as the other company pages (上季兑现 → 本季重点
→ 下季跟踪 → 长期常规).  Moody's runs a calendar fiscal year, so no quarter
label on this page needs translating.

What makes this page different from the six that carry a guidance record is the
*shape* of the guidance.  AMZN, CDNS, SNPS, NVDA, TSM and META all publish a
range for the **next quarter**, so their records are quarter-in, quarter-out.
Moody's publishes a **full-year outlook table** in the EX-99.1 of every earnings
8-K and then revises it three times as the year runs: February sets it, April,
July and October move it.  So the object this page settles is a *year*, not a
quarter, and the interesting variable is not only whether the company cleared
its range but **how far ahead it was standing when it drew the range**.

Two things make the table worth reading rather than merely quoting.

First, the company prints its own previous guidance beside the current one in
every release, with an explicit ``NC`` marker for the lines it did not move.  So
the revision path is disclosed by the filer rather than reconstructed here, and
each release independently confirms the one before it.

Second, the table reconciles against itself three separate ways in every
release, and all three come out exact: GAAP diluted EPS plus the named add-backs
equals adjusted diluted EPS, operating margin plus the named add-backs equals
adjusted operating margin, and operating cash flow minus capital expenditure
equals free cash flow.  That is what licenses this page to treat the guidance
table as arithmetic the company stands behind rather than as a set of loose
targets.

The record's answer is two-sided, and the two sides sit at different forecast
horizons rather than on different metrics:

- Against the **final (October) range**, in eight finished years adjusted
  diluted EPS landed above the top four times, inside three times, and **below
  the bottom once**.
- Against the **initial (February) range**, it landed above six times and below
  twice — and **not once inside**.  The February range has never been right.

The single downside miss is FY2018, and until now this page did not contain it.
FY2018 was excluded on the stated grounds that it "has only an October vintage,
so counting it would mix a stub year in".  That was false: the February 2018
release opens the year at adjusted EPS $7.65-$7.85, April and July reaffirm it
line for line, and October cuts it to $7.50-$7.65 -- the same four-vintage
cadence as every other year here.  The delivered figure was $7.39.  The excluded
year was the only year that breaks the headline, and the reason given for
excluding it did not survive being checked against the releases.

The one miss is 2022, and it is the whole reason the distinction matters: the
midpoint fell 34% between February and October as debt issuance collapsed.  MIS
revenue is issuance-driven and issuance is not a variable Moody's controls, so
the February number is a bet on the debt markets and the October number is
mostly bookkeeping on a year already three-quarters banked.

Published numbers are company-reported or transparent arithmetic.  The page
publishes no rating, target price or valuation.
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
    delivery_band,
    midpoint_deviation,
    number_exhibits,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "mco.json"
DATA_DIR = ROOT / "data"

LONG_STEP = 4


def plain_text(html: str) -> str:
    """Strip tags for the slots `assets/page.js` renders through `esc()`.

    Section descriptions and the 口径与方法说明 list are escaped by the shared
    renderer, so a `<b>` written into either reaches the reader as four literal
    characters. Exhibit notes are not escaped and keep their markup. Writing the
    copy once and stripping here keeps the two slots from drifting apart.
    """
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html)).strip()


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def mid(low: float, high: float) -> float:
    return (low + high) / 2


def resolve_exhibit_refs(exhibits: list[dict]) -> list[dict]:
    numbers = {ex["ref"]: ex["n"] for ex in exhibits if ex.get("ref")}
    for ex in exhibits:
        ex.pop("ref", None)
        for field in ("title", "note", "src_extra", "annot"):
            text = ex.get(field)
            if not isinstance(text, str):
                continue
            for key, number in numbers.items():
                text = text.replace("{" + key + "}", str(number))
            ex[field] = text
    return exhibits


SOURCE_8K = (
    "全年指引来自各期业绩 8-K 的 EX-99.1 里「Full Year 20XX Moody's Corporation "
    "Guidance」表，以及同一份文件末尾把 GAAP 口径调节到调整后口径的对照表；"
    "全年实际值来自次年 2 月那期新闻稿的全年结果。"
)

# The February release sets the year and the next three revise it, so a
# "guidance" on this page is always tagged with the release that drew it.
TIMING_ANNUAL = "该<b>年度进行途中</b>"


# ── section one: the annual guidance record ─────────────────────────────────
def guidance_record(staging: dict) -> tuple[list[dict], dict]:
    """Eight years of full-year guidance, settled against the year that followed."""
    g = staging["annual_guidance_history"]
    years = g["fiscal_years"]
    labels = [f"FY{y}" for y in years]
    actual = g["actual_adj_eps_usd"]

    feb_lo, feb_hi = g["adj_eps_lo"]["Feb"], g["adj_eps_hi"]["Feb"]
    oct_lo, oct_hi = g["adj_eps_lo"]["Oct"], g["adj_eps_hi"]["Oct"]

    # FY2026 has no October vintage yet; carry July so the band still draws the
    # company's current standing rather than leaving the year blank.
    oct_lo = [lo if lo is not None else g["adj_eps_lo"]["Jul"][i] for i, lo in enumerate(oct_lo)]
    oct_hi = [hi if hi is not None else g["adj_eps_hi"]["Jul"][i] for i, hi in enumerate(oct_hi)]

    # Hoisted above the bands because their prose states these tallies. They were
    # written out in words -- "eight finished years, above six times, below twice"
    # -- and adding FY2018 to the record moved every one of them. Correct today,
    # stale on the next 10-K.
    finished = [i for i, v in enumerate(actual) if v is not None]
    initial_above = sum(1 for i in finished if actual[i] > feb_hi[i])
    initial_inside = sum(1 for i in finished if feb_lo[i] <= actual[i] <= feb_hi[i])
    initial_below = sum(1 for i in finished if actual[i] < feb_lo[i])
    initial_below_years = [years[i] for i in finished if actual[i] < feb_lo[i]]

    final_band = delivery_band(
        "EX_FINAL", "调整后摊薄 EPS（对末次指引）", labels, oct_lo, oct_hi, actual,
        fmt="usd2", ylab="US$/股", unit="US$", venue="业绩新闻稿", period_word="年",
        timing=TIMING_ANNUAL,
        src_extra=SOURCE_8K + "「末次指引」取该年 10 月那期；FY2026 尚无 10 月期，图上用 7 月那期。",
        extra_note=(
            "<b>这不是「下一季度」的指引，是「本年度」的指引，而且是当年最后一次修订的那一版。</b>"
            "公司 2 月定调、4/7/10 月各改一次，到 10 月这一版落笔时，全年已经过了四分之三。"
            "所以这张图问的是一个比其他页宽松得多的问题：在几乎知道答案的时候，公司报的数还会不会低于自己画的下限。"
            "<b>本页此前的答案是「一次都没有」，那是因为漏了一年。</b>"
            "FY2018 原本不在这份记录里，理由写的是「它只有十月一个 vintage」—— 回原件查，"
            "2018-02-09 开局给的是调整后 $7.65–$7.85，4 月与 7 月逐项重申，10 月下调到 $7.50–$7.65，"
            "四版齐全，和其余每一年一样。而那一年的实际值是 $7.39，低于末次指引的下限。"
            "**被排除的那一年，恰好是唯一一年推翻这句话的。**"
        ),
    )

    initial_band = delivery_band(
        "EX_INITIAL", "调整后摊薄 EPS（对初始指引）", labels, feb_lo, feb_hi, actual,
        fmt="usd2", ylab="US$/股", unit="US$", venue="业绩新闻稿", period_word="年",
        timing="该<b>年度开始时</b>",
        src_extra=SOURCE_8K + "「初始指引」取该年 2 月那期，即公司为当年定调的第一版。",
        extra_note=(
            "<b>换成年初那一版，同一家公司变成另一个样子。</b>"
            f"{len(finished)} 个已完结年度里实际值高于上限 {initial_above} 次、"
            f"跌破下限 {initial_below} 次，"
            + ("<b>一次都没有落在区间内</b> —— 2 月画的那条带子从来没对过。"
               if initial_inside == 0
               else f"落在区间内 {initial_inside} 次。")
            + f"跌破的{'两' if initial_below == 2 else initial_below}次是 "
            + " 与 ".join(f"FY{y}" for y in initial_below_years)
            + "；FY2022 当年发行量随利率崩掉，"
            "指引中值从 2 月的 US$12.65 一路砍到 10 月的 US$8.35。"
            "把这张和上一张（Exhibit {EX_FINAL}）并排看才是本页第一节的全部意思 —— "
            "同一个数字、同一家公司，差别只在画线时距离年末还有多远。"
        ),
    )

    feb_dev = midpoint_deviation(
        "EX_FEB_DEV", "调整后摊薄 EPS（2 月那版）", labels, feb_lo, feb_hi, actual,
        mode="pct", window=len(finished), bar_labels=False, period_word="年",
        src_extra=SOURCE_8K + "偏离为全年实际值除以 2 月指引中值的自算值。",
        extra_note=(
            "把上面两张的量纲抹掉之后，年初预测的误差有多大一目了然："
            "柱子从 −32.3% 到 +17.0%，中位数约 +4%。"
            "这不是「公司保守」能解释的分布 —— 它是一条把评级收入押在债券发行量上的业务，"
            "而发行量不由公司决定。"
        ),
    )
    oct_dev = midpoint_deviation(
        "EX_OCT_DEV", "调整后摊薄 EPS（10 月那版）", labels, oct_lo, oct_hi, actual,
        mode="pct", window=len(finished), bar_labels=False, period_word="年",
        src_extra=SOURCE_8K + "偏离为全年实际值除以末次指引中值的自算值。",
        extra_note=(
            "同一个指标、同一批年份，只把画线时点从 2 月挪到 10 月，"
            "<b>平均绝对偏离就从 13.3% 收到 1.9%</b>（见 Exhibit {EX_FEB_DEV} 与本图标题），"
            "整整七分之一。"
            "十月那一版本质上已经不是预测：三个季度报完，剩下的是记账。"
            "**而即便在这样的条件下，八年里仍然跌破过一次（FY2018）** —— "
            "这一点比一句「从没跌破」有信息得多，"
            "而它此前不在页面上，只因为那一年被以一个错误的理由排除掉了。"
        ),
    )

    # The revision path itself: four vintages per year, converging on the actual.
    path_years = [y for y in years if g["adj_eps_lo"]["Feb"][years.index(y)] is not None]
    series = []
    for v, name in (("Feb", "2 月（定调）"), ("Apr", "4 月"), ("Jul", "7 月"), ("Oct", "10 月（末次）")):
        vals = []
        for y in path_years:
            i = years.index(y)
            lo, hi = g["adj_eps_lo"][v][i], g["adj_eps_hi"][v][i]
            vals.append(None if lo is None else round(mid(lo, hi), 3))
        series.append({"name": name, "values": vals})
    series.append({"name": "全年实际", "values": [actual[years.index(y)] for y in path_years],
                   "color": "NAVY"})
    revision_path = {
        "ref": "EX_PATH",
        "kind": "lines",
        "title": "每一年的指引中值怎么被改到实际值上：FY2022 砍了 34%，FY2021 抬了 16.7%",
        "xlabels": [f"FY{y}" for y in path_years],
        "series": series,
        "fmt": "usd2",
        "ylab": "US$/股（指引中值与实际）",
        "note": (
            "四条线是同一年度的四个指引版本，深色那条是最后报出来的全年实际值。"
            "线越往右越贴近实际值，就是预测窗口收缩的样子。"
            "<b>两个方向都发生过</b>：FY2021 从 US$10.50 抬到 US$12.25（+16.7%），"
            "FY2022 从 US$12.65 砍到 US$8.35（−34.0%）。"
            "把这张与 Exhibit {EX_INITIAL} 一起看：年初那条带子不只是偏，而是可以整段搬家。"
        ),
        "src_extra": SOURCE_8K,
    }

    stats = {
        "years_finished": len(finished),
        "final_above": sum(1 for i in finished if actual[i] > oct_hi[i]),
        "final_inside": sum(1 for i in finished if oct_lo[i] <= actual[i] <= oct_hi[i]),
        "final_below": sum(1 for i in finished if actual[i] < oct_lo[i]),
        "initial_above": sum(1 for i in finished if actual[i] > feb_hi[i]),
        "initial_inside": sum(1 for i in finished if feb_lo[i] <= actual[i] <= feb_hi[i]),
        "initial_below": sum(1 for i in finished if actual[i] < feb_lo[i]),
        "worst_cut_year": 2022,
        "worst_cut_pct": round((mid(oct_lo[years.index(2022)], oct_hi[years.index(2022)])
                                / mid(feb_lo[years.index(2022)], feb_hi[years.index(2022)]) - 1) * 100, 1),
    }
    return [final_band, initial_band, feb_dev, oct_dev, revision_path], stats


# ── section two: what actually moved this quarter ───────────────────────────
def quarter_highlights(staging: dict) -> list[dict]:
    seg = staging["segment_quarterly"]

    # Both the inter-segment billing range and the reconciliation slack are
    # properties of the whole series, so they move when the window does. They
    # used to read "US$42-52M" and "21 个季度 ... 0.05pp", both fitted to a
    # 21-quarter record; at 42 quarters the billing floor is lower.
    mis_internal = [t - e for t, e in zip(seg["mis_total_revenue_usd_m"],
                                          seg["mis_revenue_usd_m"])]
    ma_internal = [t - e for t, e in zip(seg["ma_total_revenue_usd_m"],
                                         seg["ma_revenue_usd_m"])]
    margin_slack = max(
        abs(income / total * 100 - printed)
        for income, total, printed in zip(seg["mis_adj_operating_income_usd_m"],
                                          seg["mis_total_revenue_usd_m"],
                                          seg["mis_adj_operating_margin_pct"]))
    labels = seg["periods"]

    two_lines = {
        "ref": "EX_SEG_REV",
        "kind": "lines",
        "title": (
            f"{len(seg['periods'])} 季里 MIS 收入在 US${min(seg['mis_revenue_usd_m']):,.0f}M–"
            f"US${max(seg['mis_revenue_usd_m']):,.0f}M 之间来回，MA 只是一路往上"
        ),
        "xlabels": labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": "MIS（评级）", "values": seg["mis_revenue_usd_m"]},
            {"name": "MA（分析）", "values": seg["ma_revenue_usd_m"], "color": "NAVY"},
        ],
        "fmt": "usd0",
        "ylab": "US$M（分部外部收入）",
        "note": (
            "两条线是同一家公司的两种生意。"
            "MIS 的收入按发行窗口开合，最低到最高差了一倍以上；"
            f"MA 是订阅制，{len(seg['periods'])} 个季度里没有一个季度同比为负。"
            "本季 MIS US$" + f"{seg['mis_revenue_usd_m'][-1]:,.0f}M、同比 "
            + signed(pct_change(seg["mis_revenue_usd_m"][-1], seg["mis_revenue_usd_m"][-5]))
            + "；MA US$" + f"{seg['ma_revenue_usd_m'][-1]:,.0f}M、同比 "
            + signed(pct_change(seg["ma_revenue_usd_m"][-1], seg["ma_revenue_usd_m"][-5]))
            + "。MA 这一季只有 +4%，是因为口径里少了两块被卖掉的业务，见本节下一张。"
        ),
        "src_extra": "各期业绩 8-K EX-99.1 的「Financial Information by Segment」表（外部收入口径）。",
    }

    share = {
        "ref": "EX_SHARE",
        "kind": "lines",
        "title": (
            f"评级业务占收入 {min(seg['mis_share_of_revenue_pct']):.1f}%–"
            f"{max(seg['mis_share_of_revenue_pct']):.1f}%，占调整后营业利润 "
            f"{min(seg['mis_share_of_adj_operating_income_pct']):.1f}%–"
            f"{max(seg['mis_share_of_adj_operating_income_pct']):.1f}%"
        ),
        "xlabels": labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": "MIS 占收入", "values": seg["mis_share_of_revenue_pct"]},
            {"name": "MIS 占调整后营业利润", "values": seg["mis_share_of_adj_operating_income_pct"],
             "color": "NAVY"},
        ],
        "fmt": "pct1",
        "ylab": "%（MIS 占合并口径的比重）",
        "note": (
            "<b>这张图是本页对「穆迪是什么公司」的回答。</b>"
            "评级业务在最差的季度只贡献不到一半收入，却从没有低于过合并调整后营业利润的 57%。"
            "两条线之间的缺口就是两块业务的利润率差："
            f"本季 MIS {seg['mis_adj_operating_margin_pct'][-1]:.1f}% 对 "
            f"MA {seg['ma_adj_operating_margin_pct'][-1]:.1f}%。"
            "所以全年指引的成败几乎完全压在发行量上 —— 这正是上一节 FY2022 那根负柱的来源。"
        ),
        "src_extra": "同上表；占比为分部值除以合并值的自算。",
    }

    margins = {
        "ref": "EX_SEG_MARGIN",
        "kind": "lines",
        "title": (
            f"两条分部调整后营业利润率：MIS 在 {min(seg['mis_adj_operating_margin_pct']):.1f}%–"
            f"{max(seg['mis_adj_operating_margin_pct']):.1f}% 之间摆动，MA 稳步抬升"
        ),
        "xlabels": labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": "MIS 调整后营业利润率", "values": seg["mis_adj_operating_margin_pct"]},
            {"name": "MA 调整后营业利润率", "values": seg["ma_adj_operating_margin_pct"], "color": "NAVY"},
            {"name": "合并调整后营业利润率", "values": seg["adj_operating_margin_pct"], "color": "GOLD"},
        ],
        "fmt": "pct1",
        "ylab": "%",
        "note": (
            "MIS 的利润率跟着发行量走，因为评级业务的成本是分析师团队，短期内不随收入伸缩；"
            f"MA 的利润率是被成本纪律一格一格抬上去的，{len(seg['periods'])} 季里从 "
            f"{seg['ma_adj_operating_margin_pct'][0]:.1f}% 到 {seg['ma_adj_operating_margin_pct'][-1]:.1f}%。"
            "合并那条落在两者之间，位置由当季的收入结构决定，而不是由任何一块的经营决定。"
            "<b>这三条是公司披露值，分母是分部<i>总</i>收入（含分部间收入），"
            f"不是上面两张图画的外部收入。</b>MIS 每季向 MA 内部计费 "
            f"US${min(mis_internal):,.0f}–{max(mis_internal):,.0f}M，"
            "拿外部收入去除会把 MIS 的利润率高估 2–3pp；按总收入复算，"
            f"{len(seg['periods'])} 个季度与公司印出来的百分比最大只差 {margin_slack:.2f}pp。"
        ),
        "src_extra": (
            "同上表；分部调整后营业利润率为公司披露值，分母为分部总收入（外部收入加分部间收入）。"
        ),
    }
    return [two_lines, share, margins]


# ── section three: what to watch through the rest of FY2026 ─────────────────
def next_watch(staging: dict) -> list[dict]:
    cg = staging["current_guidance"]
    br = staging["bridges_2026"]

    eps = br["eps"]
    steps = ["GAAP 摊薄 EPS 指引"] + [name for name, _ in eps["addbacks"]] + ["调整后摊薄 EPS 指引"]
    lo_vals = [eps["gaap"][0]]
    running = eps["gaap"][0]
    for _, delta in eps["addbacks"]:
        running = round(running + delta, 2)
        lo_vals.append(running)
    # 第七根柱：`steps` 是 1 + 5 + 1，这个循环只产出 1 + 5。少的那一根正是
    # 「调整后摊薄 EPS 指引」——本图存在的理由。渲染器按 xlabels 的长度走，
    # vals[6] 是 undefined，被 `v == null` 静默跳过：没有 NaN、没有报错，
    # 只是结果那一栏空着，而 US$16.50 印在「业务处置收益」头上。
    lo_vals.append(running)
    bridge = {
        "ref": "EX_BRIDGE",
        "kind": "bars_labeled",
        "title": "指引表自己就能对平：GAAP 指引下限加五项加回项，正好等于调整后指引下限 US$16.50",
        "xlabels": steps,
        "xrot": 90,
        "values": lo_vals,
        "fmt": "usd2",
        "ylab": "US$/股（FY2026 指引下限口径）",
        "note": (
            "公司在同一份文件里把 GAAP 指引调节到调整后指引，每一项都点名并给了金额。"
            "把它们逐项加回去，US$16.00 + 0.90 + 0.50 + 0.25 + 0.10 − 1.25 = <b>US$16.50</b>，"
            "与公司自己印出来的调整后下限逐分吻合；上限同理得 US$17.00。"
            "<b>这是本页愿意把这张指引表当作算术而不是口号来用的依据。</b>"
            "同一份文件里另外两条桥也各自对平："
            "营业利润率 44%+6%+1.5%+0.5% = 52%，"
            "经营现金流 US$3.15B 减资本开支约 US$0.45B = 自由现金流 US$2.70B。"
        ),
        "src_extra": (
            "FY2026 指引与调节均取自 2026-07-22 业绩 8-K EX-99.1；"
            "加回项为公司列示值，负号项为业务处置收益。"
        ),
    }

    items = [
        ("调整后摊薄 EPS", cg["adj_diluted_eps_usd"], "US$/股"),
        ("GAAP 摊薄 EPS", cg["gaap_diluted_eps_usd"], "US$/股"),
        ("调整后营业利润率", cg["adj_operating_margin_pct"], "%"),
        ("营业利润率", cg["operating_margin_pct"], "%"),
        ("经营现金流", cg["operating_cash_flow_usd_b"], "US$B"),
        ("自由现金流", cg["free_cash_flow_usd_b"], "US$B"),
    ]
    width = {
        "ref": "EX_WIDTH",
        "kind": "bars_labeled",
        "title": "FY2026 还开着的六条数字指引，各自还剩多宽的区间",
        "xlabels": [name for name, _, _ in items],
        "xrot": 90,
        "values": [round((hi - lo) / mid(lo, hi) * 100, 2) for _, (lo, hi), _ in items],
        "fmt": "pct1",
        "ylab": "%（区间宽度占中值）",
        "note": (
            "越窄说明公司自认为越接近确定。到 7 月这一版，"
            "调整后 EPS 的区间已经收到中值的 3.0%，"
            "而收入、费用、ARR 那几行公司<b>只给文字口径</b>（“high-single-digit percent range”），"
            "本页不把文字换算成数字，所以它们不在这张图上，也不在任何一张带子里。"
            "10 月那一版落地后，本页第一节的 FY2026 一格才会补上末次指引。"
        ),
        "src_extra": "2026-07-22 业绩 8-K EX-99.1 的全年指引表；宽度为自算。",
    }
    return [bridge, width]


# ── section four: the routine multi-period series ──────────────────────────
def routine(staging: dict) -> list[dict]:
    ann = staging["annual_actuals"]
    seg = staging["segment_quarterly"]
    ylabels = [f"FY{y}" for y in ann["fiscal_years"]]

    rev_margin = {
        "ref": "EX_ANN",
        "kind": "lines",
        "title": (
            f"八年收入从 US${ann['revenue_usd_m'][0]/1000:.1f}B 到 "
            f"US${ann['revenue_usd_m'][-1]/1000:.1f}B，营业利润率走完一轮 "
            f"{min(ann['operating_margin_pct']):.1f}% 到 {max(ann['operating_margin_pct']):.1f}%"
        ),
        "xlabels": ylabels,
        "series": [
            {"name": "营业利润率", "values": ann["operating_margin_pct"], "color": "NAVY"},
        ],
        "fmt": "pct1",
        "ylab": "%（GAAP 营业利润率）",
        "note": (
            "用 GAAP 营业利润率而不是调整后口径来画长序列，因为 GAAP 的定义八年没动过。"
            "低点是 FY2022 的 34.4%，正是发行量崩掉那年；"
            "FY2025 回到 43.4%，仍低于 FY2021 的 45.7%。"
            "把它和第一节 Exhibit {EX_INITIAL} 对着看："
            "利润率的这一轮起落，就是年初指引那几次大幅搬家的实物基础。"
        ),
        "src_extra": "XBRL companyfacts（us-gaap:OperatingIncomeLoss / 收入），口径为 10-K 申报值。",
    }

    eps_cmp = {
        "ref": "EX_EPS_ANN",
        "kind": "lines",
        "title": "八年 GAAP 与调整后摊薄 EPS：两条线之间的缺口就是每年被加回的那些项",
        "xlabels": ylabels,
        "series": [
            {"name": "GAAP 摊薄 EPS", "values": ann["diluted_eps_usd"]},
            {"name": "调整后摊薄 EPS", "values": ann["adjusted_diluted_eps_usd"], "color": "NAVY"},
        ],
        "fmt": "usd2",
        "ylab": "US$/股",
        "note": (
            "调整后口径每年都高于 GAAP，缺口在 US$0.65–1.35 之间，"
            "构成与本页 Exhibit {EX_BRIDGE} 那张桥列出的项目同类：摊销、重组、税务准备。"
            "<b>FY2026 是八年里第一次出现负的加回项</b> —— 业务处置收益 US$1.25，"
            "所以那一年的调整后指引与 GAAP 指引之间的缺口只有 US$0.50，"
            "是这条记录里最窄的一次。"
        ),
        "src_extra": "GAAP 取自 XBRL；调整后取自各年 2 月业绩新闻稿的全年结果。",
    }

    cash = {
        "ref": "EX_CASH",
        "kind": "lines",
        "title": (
            f"八年经营现金流与自由现金流：FY2022 的 US${ann['free_cash_flow_usd_m'][4]/1000:.2f}B "
            f"是低点，FY2025 US${ann['free_cash_flow_usd_m'][-1]/1000:.2f}B"
        ),
        "xlabels": ylabels,
        "series": [
            {"name": "经营现金流", "values": [v/1000 if v else None for v in ann["operating_cash_flow_usd_m"]]},
            {"name": "自由现金流（自算）", "values": [v/1000 if v else None for v in ann["free_cash_flow_usd_m"]],
             "color": "NAVY"},
        ],
        "fmt": "usd2",
        "ylab": "US$B",
        "note": (
            "自由现金流是经营现金流减去申报的资本开支，两条腿都是申报值，没有估计。"
            "资本开支八年从 US$91M 升到 US$326M，仍不到收入的 5%，"
            "所以这两条线几乎平行 —— 穆迪的现金问题从来不在资本开支上，而在发行量上。"
        ),
        "src_extra": "XBRL companyfacts；自由现金流为经营现金流减资本开支的自算值，与公司自己的 FCF 定义一致。",
    }

    seg_oi = {
        "ref": "EX_SEG_OI",
        "kind": "lines",
        "title": f"{len(seg['periods'])} 季两块业务的调整后营业利润：评级那条的波动就是全年指引的波动",
        "xlabels": seg["periods"],
        "xstep": LONG_STEP,
        "series": [
            {"name": "MIS 调整后营业利润", "values": seg["mis_adj_operating_income_usd_m"]},
            {"name": "MA 调整后营业利润", "values": seg["ma_adj_operating_income_usd_m"], "color": "NAVY"},
        ],
        "fmt": "usd0",
        "ylab": "US$M",
        "note": (
            f"MA 那条从 US${seg['ma_adj_operating_income_usd_m'][0]:,.0f}M 抬到 US$"
            f"{seg['ma_adj_operating_income_usd_m'][-1]:,.0f}M，窗口内峰值 US$"
            f"{max(seg['ma_adj_operating_income_usd_m']):,.0f}M；"
            f"MIS 那条在 US${min(seg['mis_adj_operating_income_usd_m']):,.0f}M 到 US$"
            f"{max(seg['mis_adj_operating_income_usd_m']):,.0f}M 之间走了一整轮。"
            "本季 MIS 调整后营业利润 US$"
            f"{seg['mis_adj_operating_income_usd_m'][-1]:,.0f}M"
            + ("，是 %d 季新高。" % len(seg['periods'])
               if seg['mis_adj_operating_income_usd_m'][-1]
                  == max(seg['mis_adj_operating_income_usd_m'])
               else "，窗口内新高是 US$%s M。"
                    % format(max(seg['mis_adj_operating_income_usd_m']), ',.0f'))
        ),
        "src_extra": "各期业绩 8-K EX-99.1 的分部表；分部调整后营业利润为公司披露值。",
    }
    return [rev_margin, eps_cmp, cash, seg_oi]


def build_payload(staging: dict) -> dict:
    settled_ex, stats = guidance_record(staging)
    highlight_ex = quarter_highlights(staging)
    next_ex = next_watch(staging)
    routine_ex = routine(staging)

    all_ex = number_exhibits(settled_ex + highlight_ex + next_ex + routine_ex, start=1)
    resolve_exhibit_refs(all_ex)
    a, b, c = len(settled_ex), len(highlight_ex), len(next_ex)
    settled_ex, highlight_ex = all_ex[:a], all_ex[a:a + b]
    next_ex, routine_ex = all_ex[a + b:a + b + c], all_ex[a + b + c:]

    latest = staging["latest"]
    seg = staging["segment_quarterly"]

    # Both the inter-segment billing range and the reconciliation slack are
    # properties of the whole series, so they move when the window does. They
    # used to read "US$42-52M" and "21 个季度 ... 0.05pp", both fitted to a
    # 21-quarter record; at 42 quarters the billing floor is lower.
    mis_internal = [t - e for t, e in zip(seg["mis_total_revenue_usd_m"],
                                          seg["mis_revenue_usd_m"])]
    ma_internal = [t - e for t, e in zip(seg["ma_total_revenue_usd_m"],
                                         seg["ma_revenue_usd_m"])]
    margin_slack = max(
        abs(income / total * 100 - printed)
        for income, total, printed in zip(seg["mis_adj_operating_income_usd_m"],
                                          seg["mis_total_revenue_usd_m"],
                                          seg["mis_adj_operating_margin_pct"]))
    ann = staging["annual_actuals"]
    g = staging["annual_guidance_history"]
    cg = staging["current_guidance"]
    first_table = len(all_ex) + 1

    years = g["fiscal_years"]
    rows_guidance = []
    for i, y in enumerate(years):
        def cell(v):
            lo, hi = g["adj_eps_lo"][v][i], g["adj_eps_hi"][v][i]
            return "—" if lo is None else f"{lo:.2f}–{hi:.2f}"
        act = g["actual_adj_eps_usd"][i]
        rows_guidance.append([f"FY{y}", cell("Feb"), cell("Apr"), cell("Jul"), cell("Oct"),
                              "—" if act is None else f"{act:.2f}"])

    tables = [
        {
            "n": first_table,
            "title": "FY2019–FY2026 全年调整后摊薄 EPS 指引的四个版本与实际（US$/股）",
            "headers": ["财年", "2 月（定调）", "4 月", "7 月", "10 月（末次）", "全年实际"],
            "rows": rows_guidance,
        },
        {
            "n": first_table + 1,
            "title": f"近 {len(seg['periods'])} 季分部外部收入、调整后营业利润与利润率",
            "headers": ["季度", "MIS 收入", "MA 收入", "合并收入", "MIS 调整后营业利润",
                        "MA 调整后营业利润", "MIS 利润率", "MA 利润率"],
            "rows": [[seg["periods"][i],
                      f"{seg['mis_revenue_usd_m'][i]:,.0f}", f"{seg['ma_revenue_usd_m'][i]:,.0f}",
                      f"{seg['revenue_usd_m'][i]:,.0f}",
                      f"{seg['mis_adj_operating_income_usd_m'][i]:,.0f}",
                      f"{seg['ma_adj_operating_income_usd_m'][i]:,.0f}",
                      f"{seg['mis_adj_operating_margin_pct'][i]:.1f}%",
                      f"{seg['ma_adj_operating_margin_pct'][i]:.1f}%"]
                     for i in range(len(seg["periods"]))],
        },
        {
            "n": first_table + 2,
            "title": "FY2018–FY2025 年度实际",
            "headers": ["财年", "收入 US$M", "营业利润 US$M", "营业利润率", "GAAP EPS",
                        "调整后 EPS", "经营现金流 US$M", "资本开支 US$M", "自由现金流 US$M"],
            "rows": [[f"FY{y}",
                      f"{ann['revenue_usd_m'][i]:,.0f}", f"{ann['operating_income_usd_m'][i]:,.0f}",
                      f"{ann['operating_margin_pct'][i]:.1f}%",
                      f"{ann['diluted_eps_usd'][i]:.2f}",
                      ("—" if ann["adjusted_diluted_eps_usd"][i] is None
                       else f"{ann['adjusted_diluted_eps_usd'][i]:.2f}"),
                      f"{ann['operating_cash_flow_usd_m'][i]:,.0f}", f"{ann['capex_usd_m'][i]:,.0f}",
                      f"{ann['free_cash_flow_usd_m'][i]:,.0f}"]
                     for i, y in enumerate(ann["fiscal_years"])],
        },
        ai_capex_cycle_table(first_table + 3),
    ]

    final_lo = cg["adj_diluted_eps_usd"][0]
    final_hi = cg["adj_diluted_eps_usd"][1]
    return {
        "schema_version": "quarterly-dashboard/mco-v1",
        "page": {"slug": "mco", "language": "zh-CN"},
        "company": {
            "ticker": "MCO",
            "name": "Moody's Corporation",
            "group": "financial_data_indices",
            "accounting_standard": "US GAAP",
        },
        "latest": {
            "disclosed_period_label": "Q2 2026",
            "full_financial_period_label": "Q2 2026",
            "period_end": latest["period_end"],
            "release_date": latest["release_date"],
            "analysis_date": "2026-08-29",
            "audit_status": "unaudited",
            "status": "history_ready",
        },
        "tracker": "Watchlist Quarterly Tracker · MCO",
        "title": "Moody's Corporation (MCO)：Q2 2026 季报仪表盘",
        "subtitle": (
            f"截至 {latest['period_end']} · 发布 {latest['release_date']} · US GAAP · 未审计 · "
            "自然年财年，季度标注无需换算"
        ),
        # `assets/page.js` sets this with textContent, so it is a plain-text
        # slot: any markup here reaches the reader as literal characters.
        "headline": plain_text(
            f"收入 US${latest['revenue_usd_m']:,.0f}M、同比 "
            f"{signed(pct_change(seg['revenue_usd_m'][-1], seg['revenue_usd_m'][-5]))}，"
            f"调整后营业利润率 {latest['adj_operating_margin_pct']:.1f}%。"
            "但本页真正的对象不是这个季度 —— 穆迪不给季度指引，它给的是全年指引并逐季修订。"
            f"{stats['years_finished']} 个已完结年度里，实际值相对末次（10 月）指引"
            f"高于上限 {stats['final_above']} 次、落在区间内 {stats['final_inside']} 次、"
            f"跌破下限 {stats['final_below']} 次；"
            f"相对初始（2 月）指引却是高于 {stats['initial_above']} 次、跌破 {stats['initial_below']} 次、"
            "一次都没落在区间内。同一个数字，差别只在画线时离年末还有多远。"
        ),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>记录</span><b>末次指引跌破过一次，初始指引一次都没对过</b>'
            f'<p>{stats["years_finished"]} 个已完结年度：对 10 月那版下限 '
            f'{stats["final_below"]} 次跌破；'
            f'对 2 月那版 {stats["initial_inside"]} 次落在区间内。'
            f'FY2022 中值从 2 月到 10 月被砍了 {abs(stats["worst_cut_pct"]):.0f}%。</p></article>'
            '<article><span>结构</span><b>评级是收入的少数，利润的多数</b>'
            f'<p>{len(seg["periods"])} 季里 MIS 占收入 {min(seg["mis_share_of_revenue_pct"]):.0f}%–'
            f'{max(seg["mis_share_of_revenue_pct"]):.0f}%，'
            f'却占调整后营业利润 {min(seg["mis_share_of_adj_operating_income_pct"]):.0f}%–'
            f'{max(seg["mis_share_of_adj_operating_income_pct"]):.0f}%。</p></article>'
            '<article><span>本季</span><b>指引表三条桥全部对平</b>'
            f'<p>GAAP EPS 加五项加回项等于调整后 EPS US${final_lo:.2f}–{final_hi:.2f}；'
            '利润率与自由现金流两条桥同样逐项吻合，误差为零。</p></article>'
            '</div>'
        ),
        "source": (
            'Source: <a href="https://www.sec.gov/Archives/edgar/data/1059556/'
            '000162828026049104/a2q26earningsrelease.htm" rel="noopener">Moody\'s Q2 2026 '
            '业绩新闻稿（8-K EX-99.1）</a>与截至 2026-06-30 的 10-Q。'
        ),
        "source_url": (
            "https://www.sec.gov/Archives/edgar/data/1059556/"
            "000162828026049104/a2q26earningsrelease.htm"
        ),
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {
                "id": "settled",
                "title": "一、上季兑现了吗",
                "description": plain_text(
                    "这一节和本站其他几页结算的东西不是同一类。穆迪不给下一季度的数字区间，"
                    "它在每份业绩 8-K 里给一张全年指引表，然后在当年的后三期各修订一次。"
                    "所以这里结算的是「年」而不是「季」，而真正的变量是画线时离年末还有多远。"
                ),
                "exhibits": settled_ex,
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": plain_text(
                    "评级与分析两块业务在收入上的分岔、"
                    "它们在利润上的极不对称，"
                    "以及被两笔业务处置压住的 MA 收入增速。"
                ),
                "exhibits": highlight_ex,
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": plain_text(
                    "FY2026 还开着的六条数字指引各自还剩多宽，"
                    "以及那张让本页愿意把指引表当算术用的口径桥。"
                    "只给文字口径的几行不换算成数字，写在不接入清单里。"
                ),
                "exhibits": next_ex,
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": plain_text(
                    "MCO 专属的常规序列：八年营业利润率的一轮起落、"
                    "GAAP 与调整后 EPS 之间那道逐年变化的缺口、"
                    "现金流的两条腿，以及两块业务各自的调整后营业利润。"
                ),
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": [plain_text(p) for p in [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "穆迪为自然年财年（12 月 31 日结束），本页季度标注与公司口径一致，无需换算。",
            "本页最需要说明的一条：穆迪<b>从不给下一季度的数字指引</b>，它给的是全年指引并在当年逐季修订。"
            "因此本页第一节结算的对象是财年而不是季度；末次指引落笔时全年已经过了四分之三，"
            "所以「跌破得少」这件事本身的份量，远小于同一句话出现在按季度指引的公司身上。"
            "另外，本页此前把 FY2018 排除在记录之外、理由写的是「只有十月一个 vintage」，"
            "那句话是错的（四版齐全），而那一年正是八年里唯一跌破末次指引下限的一年。"
            "本页用两张图（对初始指引、对末次指引）并排把这件事讲清楚，而不是只报一个命中率。",
            "指引表里的收入类各行（MCO/MIS/MA 收入、费用、ARR）公司<b>只给文字口径</b>，"
            "例如「increase in the high-single-digit percent range」。"
            "文字不是数字区间，本页不把它换算成端点，因此这几行没有兑现图，也不进任何一张带子。",
            "FY2018 不在第一节的记录里：本页的申报窗口从 2018 年 10 月那期开始，"
            "该年度只拿得到 10 月那一次修订，凑不齐「2 月定调 + 三次修订」的四个点，"
            "把它算进命中率会拿一个残缺年份和七个完整年份并列。",
            "2021-08-05 另有一次非季度节奏的指引更新（在 7 月 28 日那期之后），"
            "该次调整后 EPS 指引与 7 月那版相同，本页按季度节奏取数，未单列该期。",
            "分部数据的列先后顺序在 2023 年 4 月那期之后由「MIS 在前」改为「MA 在前」。"
            "本页按表头里的分部名取值而不是按列位，重叠季度在两份来源之间逐项一致。",
            "分部调整后营业利润率的分母是<b>分部总收入</b>（外部收入加分部间收入），"
            "而本页图上画的分部收入是<b>外部收入</b>口径。两者差的就是分部间计费："
            f"MIS 每季向 MA 内部计费 US${min(mis_internal):,.0f}–{max(mis_internal):,.0f}M，"
            f"MA 向 MIS US${min(ma_internal):,.0f}–{max(ma_internal):,.0f}M。"
            "用外部收入去除调整后营业利润会把 MIS 的利润率高估 2–3pp；"
            f"按总收入复算，{len(seg['periods'])} 个季度与公司自己印出来的百分比"
            f"最大只差 {margin_slack:.2f}pp，"
            f"那 {margin_slack:.2f}pp 是公司把百分比四舍五入到一位小数留下的余数。",
            "MA 本季收入同比只有 +4%，口径上受两笔业务处置影响：Learning Solutions，"
            "以及本季完成的 MA Regulatory Solutions。公司在指引脚注里把处置收益单列为约 US$1.25/股 的负向加回项。",
            "核对表的取数来源：全年指引四栏的每一格是该期业绩 8-K EX-99.1 指引表里的当期值，"
            "全年实际取次年 2 月那期的全年结果；分部表为外部收入口径（不含分部间收入）；"
            "年度表的 GAAP 各列取自 XBRL companyfacts，调整后 EPS 取自各年 2 月业绩新闻稿。",
            "自由现金流为经营现金流减申报资本开支的自算值，与公司自己的定义一致；标 D 的项均为此类透明自算。",
            "本页不发布评级、目标价、估值与任何券商共识，也不发布公司未在申报文件中给出的数字。",
        ]],
        "footer": "Quarterly Results · 公司披露值与透明自算 · 仅供研究",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "mco.js"), payload, "mco")
    shell_dir = ROOT / "mco"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("MCO", "mco"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(
        f"MCO page: {charts} charts in {len(payload['sections'])} sections "
        f"+ {len(payload['tables'])} audit tables"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
