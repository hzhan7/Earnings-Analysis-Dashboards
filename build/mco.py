#!/usr/bin/env python3
"""Build the MCO quarterly-results page.

Same four-part, chart-led shape as the other company pages (上季兑现 → 本季重点
→ 下季跟踪 → 长期常规).  Moody's runs a calendar fiscal year, so no quarter
label on this page needs translating.

What makes this page different from the six that carry a guidance record is the
*shape* of the guidance.  AMZN, CDNS, SNPS, NVDA, TSM and META all publish a
range for the **next quarter**, so their records are quarter-in, quarter-out.
Moody's publishes a **full-year outlook table** in the EX-99.1 of every earnings
8-K and then re-issues it three times as the year runs: February sets it, April,
July and October update it (a line it did not move is printed ``NC``).  So the
object this page settles is a *year*, not a quarter, and the interesting
variable is not only whether the company cleared its range but **how far ahead
it was standing when it drew the range**.

Two things make the table worth reading rather than merely quoting.

First, the company prints its own previous guidance beside the current one in
every release, with an explicit ``NC`` marker for the lines it did not move.  So
the revision path is disclosed by the filer rather than reconstructed here, and
each release independently confirms the one before it.

Second, the table reconciles against itself three separate ways in every
release: GAAP diluted EPS plus the named add-backs equals adjusted diluted EPS,
operating margin plus the named add-backs equals adjusted operating margin, and
operating cash flow minus capital expenditure equals free cash flow.  That is
what licenses this page to treat the guidance table as arithmetic the company
stands behind rather than as a set of loose targets -- and the page checks the
three sums on every build rather than asserting them.

The record's answer is two-sided, and the two sides sit at different forecast
horizons rather than on different metrics: against the final (October) range
the delivered adjusted EPS lands close, against the initial (February) range it
can miss by a third.  Every tally, extreme and year named in those sentences is
recounted from the series on each build.  They used to be typed, and the typed
ones went stale the moment FY2018 was added to the record and the annual window
was pulled back to FY2016.

FY2018 was once excluded on the stated grounds that it "has only an October
vintage".  That was false: the February 2018 release opens the year at adjusted
EPS $7.65-$7.85, April and July reaffirm it line for line, and October cuts it
to $7.50-$7.65 -- the same four-vintage cadence as every other year here.  The
delivered figure was $7.39, below the final range: the excluded year was the
only year that broke the page's headline.

The page is rolled by editing ``series/mco.json`` alone.  What only one quarter
has -- the open year's guidance table and its three bridges, the quarter's two
EPS figures, and the quarter's story -- sits in blocks stamped with the quarter
(``board.stamped_block``); ``_checks`` is a separate reading of the quarter's
release that the tests hold the page to and this builder never reads.

Published numbers are company-reported or transparent arithmetic.  The page
publishes no rating, target price or valuation.
"""

from __future__ import annotations

import json
import math
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import (  # noqa: E402
    ai_capex_cycle_table,
    cn_count,
    cn_fraction,
    delivery_band,
    fill_story,
    latest_block,
    midpoint_deviation,
    number_exhibits,
    stamped_block,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "mco.json"
DATA_DIR = ROOT / "data"

LONG_STEP = 4

VINTAGES = ("Feb", "Apr", "Jul", "Oct")

# The guided lines the width chart draws: the numeric ranges that share a basis
# with the settled record (EPS, margins, cash). The table carries other numeric
# lines too -- interest, non-operating items, tax rate, segment margins -- which
# is why the chart names what it draws instead of calling it "the" numbers.
WIDTH_ITEMS = [
    ("调整后摊薄 EPS", "adj_diluted_eps_usd", "US$/股"),
    ("GAAP 摊薄 EPS", "gaap_diluted_eps_usd", "US$/股"),
    ("调整后营业利润率", "adj_operating_margin_pct", "%"),
    ("营业利润率", "operating_margin_pct", "%"),
    ("经营现金流", "operating_cash_flow_usd_b", "US$B"),
    ("自由现金流", "free_cash_flow_usd_b", "US$B"),
]
VINTAGE_MONTH = {"Feb": "2 月", "Apr": "4 月", "Jul": "7 月", "Oct": "10 月"}

# History that does not move with a roll, keyed by the year it belongs to: why
# the year that cut its guidance hardest cut it, why the lowest operating margin
# is where it is, why the lowest free cash flow is where it is.
CUT_STORY = {2022: "当年发行量随利率崩掉"}
MARGIN_STORY = {2016: "当年计提了与 DOJ 和解相关的一次性费用", 2022: "正是发行量崩掉那年"}
CASH_STORY = {2017: "那笔 DOJ 和解款实际付出去的一年", 2022: "发行量崩掉那年"}


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


def money(value: float) -> str:
    """``0.9`` → ``'0.90'``; the sign is written by the caller."""
    return f"{abs(value):.2f}"


def pct_words(value: float) -> str:
    """``44.0`` → ``'44%'``, ``1.5`` → ``'1.5%'`` -- a guided percentage as printed."""
    return f"{value:g}%"


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


def release_source(staging: dict) -> dict:
    """This quarter's own release in `sources`, found by its label."""
    label = f"Moody’s {staging['segment_quarterly']['periods'][-1]} 业绩新闻稿"
    found = next((item for item in staging["sources"] if item["label"].startswith(label)), None)
    if found is None:
        raise ValueError(f"series `sources` has no entry for the {label}: add this "
                         "quarter's release with the roll")
    return found


def periodic_report_words(staging: dict) -> str:
    """「与截至 … 的 10-Q」 when `sources` carries the quarter's own 10-Q / 10-K."""
    seg = staging["segment_quarterly"]
    end, period = seg["period_ends"][-1], seg["periods"][-1]
    for form, label in (("10-Q", f"Moody’s 截至 {end} 的 10-Q"),
                        ("10-K", f"Moody’s FY{period[-4:]} 年报 10-K")):
        if any(item["label"].startswith(label) for item in staging["sources"]):
            return f"与截至 {end} 的 {form}"
    return ""


SOURCE_8K = (
    "全年指引来自各期业绩 8-K 的 EX-99.1 里「Full Year 20XX Moody's Corporation "
    "Guidance」表，以及同一份文件末尾把 GAAP 口径调节到调整后口径的对照表；"
    "全年实际值来自次年 2 月那期新闻稿的全年结果。"
)

# The February release sets the year and the next three revise it, so a
# "guidance" on this page is always tagged with the release that drew it.
TIMING_ANNUAL = "该<b>年度进行途中</b>"


def record_facts(staging: dict) -> dict:
    """Everything the guidance record says, counted once for every sentence that uses it."""
    g = staging["annual_guidance_history"]
    years = g["fiscal_years"]
    actual = g["actual_adj_eps_usd"]
    feb_lo, feb_hi = g["adj_eps_lo"]["Feb"], g["adj_eps_hi"]["Feb"]
    oct_lo, oct_hi = g["adj_eps_lo"]["Oct"], g["adj_eps_hi"]["Oct"]
    finished = [i for i, v in enumerate(actual) if v is not None]
    # The open year's latest vintage stands in for its missing October range.
    latest_vintage = {}
    for i in range(len(years)):
        latest_vintage[i] = next(v for v in reversed(VINTAGES) if g["adj_eps_lo"][v][i] is not None)
    final_lo = [g["adj_eps_lo"][latest_vintage[i]][i] for i in range(len(years))]
    final_hi = [g["adj_eps_hi"][latest_vintage[i]][i] for i in range(len(years))]
    feb_dev = {years[i]: pct_change(actual[i], mid(feb_lo[i], feb_hi[i])) for i in finished}
    oct_dev = {years[i]: pct_change(actual[i], mid(oct_lo[i], oct_hi[i])) for i in finished}
    path = {years[i]: pct_change(mid(oct_lo[i], oct_hi[i]), mid(feb_lo[i], feb_hi[i]))
            for i in range(len(years)) if oct_lo[i] is not None and feb_lo[i] is not None}
    return {
        "years": years, "finished": finished, "actual": actual,
        "feb_lo": feb_lo, "feb_hi": feb_hi, "final_lo": final_lo, "final_hi": final_hi,
        "latest_vintage": latest_vintage,
        "final_above": [years[i] for i in finished if actual[i] > oct_hi[i]],
        "final_inside": [years[i] for i in finished if oct_lo[i] <= actual[i] <= oct_hi[i]],
        "final_below": [years[i] for i in finished if actual[i] < oct_lo[i]],
        "initial_above": [years[i] for i in finished if actual[i] > feb_hi[i]],
        "initial_inside": [years[i] for i in finished if feb_lo[i] <= actual[i] <= feb_hi[i]],
        "initial_below": [years[i] for i in finished if actual[i] < feb_lo[i]],
        "feb_dev": feb_dev, "oct_dev": oct_dev, "path": path,
        "open": [years[i] for i in range(len(years)) if actual[i] is None],
    }


# ── section one: the annual guidance record ─────────────────────────────────
def guidance_record(staging: dict, facts: dict) -> list[dict]:
    """The full-year guidance record, settled against the year that followed."""
    g = staging["annual_guidance_history"]
    years = facts["years"]
    labels = [f"FY{y}" for y in years]
    actual = facts["actual"]
    feb_lo, feb_hi = facts["feb_lo"], facts["feb_hi"]
    oct_lo, oct_hi = facts["final_lo"], facts["final_hi"]
    n_done = len(facts["finished"])
    carried = [(years[i], facts["latest_vintage"][i]) for i in range(len(years))
               if facts["latest_vintage"][i] != "Oct"]

    first = years.index(2018) if 2018 in years else None
    fy2018 = ""
    if first is not None and facts["final_below"] == [2018]:
        fy2018 = (
            "<b>本页此前的答案是「一次都没有」，那是因为漏了一年。</b>"
            "FY2018 原本不在这份记录里，理由写的是「它只有十月一个 vintage」—— 回原件查，"
            f"{g['release_dates']['2018']['Feb']} 开局给的是调整后 ${feb_lo[first]:.2f}–${feb_hi[first]:.2f}，"
            "4 月与 7 月逐项重申，"
            f"10 月下调到 ${g['adj_eps_lo']['Oct'][first]:.2f}–${g['adj_eps_hi']['Oct'][first]:.2f}，"
            "四版齐全，和其余每一年一样。"
            f"而那一年的实际值是 ${actual[first]:.2f}，低于末次指引的下限。"
            "<b>被排除的那一年，恰好是唯一一年推翻这句话的。</b>"
        )
    final_band = delivery_band(
        "EX_FINAL", "调整后摊薄 EPS（对末次指引）", labels, oct_lo, oct_hi, actual,
        fmt="usd2", ylab="US$/股", unit="US$", venue="业绩新闻稿", period_word="年",
        timing=TIMING_ANNUAL,
        src_extra=(SOURCE_8K + "「末次指引」取该年 10 月那期"
                   + "".join(f"；FY{y} 尚无 10 月期，图上用 {VINTAGE_MONTH[v]}那期" for y, v in carried)
                   + "。"),
        extra_note=(
            "<b>这不是「下一季度」的指引，是「本年度」的指引，而且是当年最后一次修订的那一版。</b>"
            "公司 2 月定调、4/7/10 月各更新一次（没动的行印 NC），到 10 月这一版落笔时，全年已经过了四分之三。"
            "所以这张图问的是一个比其他页宽松得多的问题：在几乎知道答案的时候，公司报的数还会不会低于自己画的下限。"
            + fy2018
        ),
    )

    below = facts["initial_below"]
    worst_cut = min(facts["path"], key=facts["path"].get)
    wi = years.index(worst_cut)
    initial_band = delivery_band(
        "EX_INITIAL", "调整后摊薄 EPS（对初始指引）", labels, feb_lo, feb_hi, actual,
        fmt="usd2", ylab="US$/股", unit="US$", venue="业绩新闻稿", period_word="年",
        timing="该<b>年度开始时</b>",
        src_extra=SOURCE_8K + "「初始指引」取该年 2 月那期，即公司为当年定调的第一版。",
        extra_note=(
            "<b>换成年初那一版，同一家公司变成另一个样子。</b>"
            f"{n_done} 个已完结年度里实际值高于上限 {len(facts['initial_above'])} 次、"
            f"跌破下限 {len(below)} 次，"
            + ("<b>一次都没有落在区间内</b> —— 2 月画的那条带子从来没对过。"
               if not facts["initial_inside"]
               else f"落在区间内 {len(facts['initial_inside'])} 次。")
            + (f"跌破的{cn_count(len(below))}次是 " + " 与 ".join(f"FY{y}" for y in below) + "；"
               if below else "")
            + f"FY{worst_cut} "
            + (f"{CUT_STORY[worst_cut]}，" if worst_cut in CUT_STORY else "")
            + f"指引中值从 2 月的 US${mid(feb_lo[wi], feb_hi[wi]):.2f} 一路砍到 10 月的 "
            f"US${mid(g['adj_eps_lo']['Oct'][wi], g['adj_eps_hi']['Oct'][wi]):.2f}。"
            "把这张和上一张（Exhibit {EX_FINAL}）并排看才是本页第一节的全部意思 —— "
            "同一个数字、同一家公司，差别只在画线时距离年末还有多远。"
        ),
    )

    feb_values = list(facts["feb_dev"].values())
    feb_dev = midpoint_deviation(
        "EX_FEB_DEV", "调整后摊薄 EPS（2 月那版）", labels, feb_lo, feb_hi, actual,
        mode="pct", window=n_done, bar_labels=False, period_word="年",
        src_extra=SOURCE_8K + "偏离为全年实际值除以 2 月指引中值的自算值。",
        extra_note=(
            "把上面两张的量纲抹掉之后，年初预测的误差有多大一目了然："
            f"柱子从 {min(feb_values):+.1f}% 到 {max(feb_values):+.1f}%，"
            f"中位数约 {statistics.median(feb_values):+.0f}%。".replace("-", "−")
            + "这不是「公司保守」能解释的分布 —— 它是一条把评级收入押在债券发行量上的业务，"
            "而发行量不由公司决定。"
        ),
    )
    feb_mean = statistics.fmean(abs(v) for v in feb_values)
    oct_mean = statistics.fmean(abs(v) for v in facts["oct_dev"].values())
    final_below = facts["final_below"]
    oct_dev = midpoint_deviation(
        "EX_OCT_DEV", "调整后摊薄 EPS（10 月那版）", labels, oct_lo, oct_hi, actual,
        mode="pct", window=n_done, bar_labels=False, period_word="年",
        src_extra=SOURCE_8K + "偏离为全年实际值除以末次指引中值的自算值。",
        extra_note=(
            "同一个指标、同一批年份，只把画线时点从 2 月挪到 10 月，"
            f"<b>平均绝对偏离就从 {feb_mean:.1f}% 收到 {oct_mean:.1f}%</b>"
            "（见 Exhibit {EX_FEB_DEV} 与本图标题），"
            f"约{cn_fraction(oct_mean / feb_mean)}。"
            "十月那一版本质上已经不是预测：三个季度报完，剩下的是记账。"
            + (f"<b>而即便在这样的条件下，{cn_count(n_done)}年里仍然跌破过"
               f"{cn_count(len(final_below))}次（{'、'.join(f'FY{y}' for y in final_below)}）</b> —— "
               "这一点比一句「从没跌破」有信息得多"
               + ("，而它此前不在页面上，只因为那一年被以一个错误的理由排除掉了。"
                  if final_below == [2018] else "。")
               if final_below else
               f"<b>{cn_count(n_done)}年里一次都没有跌破过末次指引的下限。</b>")
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
    path = facts["path"]
    raise_year = max(path, key=path.get)

    def endpoints(year: int) -> str:
        i = years.index(year)
        return (f"US${mid(feb_lo[i], feb_hi[i]):.2f}",
                f"US${mid(g['adj_eps_lo']['Oct'][i], g['adj_eps_hi']['Oct'][i]):.2f}")

    both_ways = path[worst_cut] < 0 < path[raise_year]
    revision_path = {
        "ref": "EX_PATH",
        "kind": "lines",
        "title": (f"每一年的指引中值怎么被改到实际值上：FY{worst_cut} 砍了 {abs(path[worst_cut]):.0f}%，"
                  f"FY{raise_year} 抬了 {path[raise_year]:.1f}%"),
        "xlabels": [f"FY{y}" for y in path_years],
        "series": series,
        "fmt": "usd2",
        "ylab": "US$/股（指引中值与实际）",
        "note": (
            "四条线是同一年度的四个指引版本，深色那条是最后报出来的全年实际值。"
            "线越往右越贴近实际值，就是预测窗口收缩的样子。"
            + (f"<b>两个方向都发生过</b>：FY{raise_year} 从 {endpoints(raise_year)[0]} 抬到 "
               f"{endpoints(raise_year)[1]}（{path[raise_year]:+.1f}%），"
               f"FY{worst_cut} 从 {endpoints(worst_cut)[0]} 砍到 {endpoints(worst_cut)[1]}"
               f"（{minus(path[worst_cut])}）。" if both_ways else "")
            + "把这张与 Exhibit {EX_INITIAL} 一起看：年初那条带子不只是偏，而是可以整段搬家。"
        ),
        "src_extra": SOURCE_8K,
    }
    if not both_ways:
        revision_path["title"] = (f"每一年的指引中值怎么被改到实际值上：改得最多的是 FY{raise_year} 的 "
                                  f"{path[raise_year]:+.1f}%")
    return [final_band, initial_band, feb_dev, oct_dev, revision_path]


def minus(value: float) -> str:
    """``-34.0`` → ``'−34.0%'`` with the typographic minus the prose uses."""
    return f"{value:+.1f}%".replace("-", "−")


# ── section two: what actually moved this quarter ───────────────────────────
def segment_facts(staging: dict) -> dict:
    seg = staging["segment_quarterly"]
    periods = seg["periods"]
    mis_internal = [t - e for t, e in zip(seg["mis_total_revenue_usd_m"], seg["mis_revenue_usd_m"])]
    ma_internal = [t - e for t, e in zip(seg["ma_total_revenue_usd_m"], seg["ma_revenue_usd_m"])]
    margin_slack = max(
        abs(income / total * 100 - printed)
        for income, total, printed in zip(seg["mis_adj_operating_income_usd_m"],
                                          seg["mis_total_revenue_usd_m"],
                                          seg["mis_adj_operating_margin_pct"]))
    # How far the external-revenue denominator would overstate MIS's margin.
    overstated = [income / external * 100 - income / total * 100
                  for income, external, total in zip(seg["mis_adj_operating_income_usd_m"],
                                                     seg["mis_revenue_usd_m"],
                                                     seg["mis_total_revenue_usd_m"])]
    ma = seg["ma_revenue_usd_m"]
    ma_margin = seg["ma_adj_operating_margin_pct"]
    return {
        "mis_internal": mis_internal, "ma_internal": ma_internal, "margin_slack": margin_slack,
        "overstated": (min(overstated), max(overstated)),
        "ma_dips": [periods[i] for i in range(1, len(ma)) if ma[i] < ma[i - 1]],
        "ma_yoy_negative": [periods[i] for i in range(4, len(ma)) if ma[i] < ma[i - 4]],
        "ma_yoy_count": max(len(ma) - 4, 0),
        "ma_margin_dips": [i for i in range(1, len(ma_margin)) if ma_margin[i] < ma_margin[i - 1]],
    }


def overstated_words(facts: dict) -> str:
    low, high = facts["overstated"]
    return f"{low:.1f}–{high:.1f}pp"


def quarter_highlights(staging: dict, facts: dict, sf: dict, story: dict | None,
                       values: dict) -> list[dict]:
    seg = staging["segment_quarterly"]
    labels = seg["periods"]
    n = len(labels)
    mis_rev = seg["mis_revenue_usd_m"]

    ma_words = ("MA 只是一路往上" if not sf["ma_dips"] else
                "MA 同比从未为负" if not sf["ma_yoy_negative"] else
                f"MA 有{cn_count(len(sf['ma_yoy_negative']))}季同比为负")
    two_lines = {
        "ref": "EX_SEG_REV",
        "kind": "lines",
        "title": (
            f"{n} 季里 MIS 收入在 US${min(mis_rev):,.0f}M–"
            f"US${max(mis_rev):,.0f}M 之间来回，{ma_words}"
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
            + ("MIS 的收入按发行窗口开合，最低到最高差了一倍以上；" if max(mis_rev) >= 2 * min(mis_rev)
               else f"MIS 的收入按发行窗口开合，最高是最低的 {max(mis_rev) / min(mis_rev):.1f} 倍；")
            + ((f"MA 是订阅制，{sf['ma_yoy_count']} 个有同比基数的季度里没有一个季度同比为负。")
               if not sf["ma_yoy_negative"] else
               f"MA 是订阅制，但 {sf['ma_yoy_count']} 个有同比基数的季度里有"
               f"{cn_count(len(sf['ma_yoy_negative']))}季同比为负（{'、'.join(sf['ma_yoy_negative'])}）。")
            + "本季 MIS US$" + f"{mis_rev[-1]:,.0f}M、同比 "
            + signed(pct_change(mis_rev[-1], mis_rev[-5]))
            + "；MA US$" + f"{seg['ma_revenue_usd_m'][-1]:,.0f}M、同比 "
            + signed(pct_change(seg["ma_revenue_usd_m"][-1], seg["ma_revenue_usd_m"][-5]))
            + "。"
            + (fill_story(story["ma_note"], values) if story and story.get("ma_note") else "")
        ),
        "src_extra": "各期业绩 8-K EX-99.1 的「Financial Information by Segment」表（外部收入口径）。",
    }

    share_rev, share_oi = seg["mis_share_of_revenue_pct"], seg["mis_share_of_adj_operating_income_pct"]
    worst_feb = min(facts["feb_dev"], key=facts["feb_dev"].get)
    share = {
        "ref": "EX_SHARE",
        "kind": "lines",
        "title": (
            f"评级业务占收入 {min(share_rev):.1f}%–"
            f"{max(share_rev):.1f}%，占调整后营业利润 "
            f"{min(share_oi):.1f}%–"
            f"{max(share_oi):.1f}%"
        ),
        "xlabels": labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": "MIS 占收入", "values": share_rev},
            {"name": "MIS 占调整后营业利润", "values": share_oi, "color": "NAVY"},
        ],
        "fmt": "pct1",
        "ylab": "%（MIS 占合并口径的比重）",
        "note": (
            "<b>这张图是本页对「穆迪是什么公司」的回答。</b>"
            + (f"评级业务在最差的季度只贡献不到一半收入，却从没有低于过合并调整后营业利润的 "
               f"{math.floor(min(share_oi))}%。" if min(share_rev) < 50 else
               f"评级业务在最差的季度也贡献 {min(share_rev):.0f}% 的收入、"
               f"{math.floor(min(share_oi))}% 以上的调整后营业利润。")
            + "两条线之间的缺口就是两块业务的利润率差："
            f"本季 MIS {seg['mis_adj_operating_margin_pct'][-1]:.1f}% 对 "
            f"MA {seg['ma_adj_operating_margin_pct'][-1]:.1f}%。"
            "所以全年指引的成败几乎完全压在发行量上"
            + (f" —— 这正是上一节 FY{worst_feb} 那根负柱的来源。" if facts["feb_dev"][worst_feb] < 0 else "。")
        ),
        "src_extra": "同上表；占比为分部值除以合并值的自算。",
    }

    ma_margin = seg["ma_adj_operating_margin_pct"]
    low_i = ma_margin.index(min(ma_margin))
    dips = sf["ma_margin_dips"]
    margins = {
        "ref": "EX_SEG_MARGIN",
        "kind": "lines",
        "title": (
            f"两条分部调整后营业利润率：MIS 在 {min(seg['mis_adj_operating_margin_pct']):.1f}%–"
            f"{max(seg['mis_adj_operating_margin_pct']):.1f}% 之间摆动，"
            + ("MA 稳步抬升" if not dips else f"MA 从 {ma_margin[0]:.1f}% 抬到 {ma_margin[-1]:.1f}%")
        ),
        "xlabels": labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": "MIS 调整后营业利润率", "values": seg["mis_adj_operating_margin_pct"]},
            {"name": "MA 调整后营业利润率", "values": ma_margin, "color": "NAVY"},
            {"name": "合并调整后营业利润率", "values": seg["adj_operating_margin_pct"], "color": "GOLD"},
        ],
        "fmt": "pct1",
        "ylab": "%",
        "note": (
            "MIS 的利润率跟着发行量走，因为评级业务的成本是分析师团队，短期内不随收入伸缩；"
            + (f"MA 的利润率是被成本纪律一格一格抬上去的，{n} 季里从 "
               f"{ma_margin[0]:.1f}% 到 {ma_margin[-1]:.1f}%。" if not dips else
               f"MA 的利润率 {n} 季里从 {ma_margin[0]:.1f}% 抬到 {ma_margin[-1]:.1f}%，"
               f"但不是一格一格抬上去的：{n - 1} 次环比里 {len(dips)} 次回落，"
               f"最低一格是 {labels[low_i]} 的 {ma_margin[low_i]:.1f}%。")
            + "合并那条落在两者之间，位置由当季的收入结构决定，而不是由任何一块的经营决定。"
            "<b>这三条是公司披露值，分母是分部<i>总</i>收入（含分部间收入），"
            f"不是上面两张图画的外部收入。</b>MIS 每季向 MA 内部计费 "
            f"US${min(sf['mis_internal']):,.0f}–{max(sf['mis_internal']):,.0f}M，"
            f"拿外部收入去除会把 MIS 的利润率高估 {overstated_words(sf)}；按总收入复算，"
            f"{n} 个季度与公司印出来的百分比最大只差 {sf['margin_slack']:.2f}pp。"
        ),
        "src_extra": (
            "同上表；分部调整后营业利润率为公司披露值，分母为分部总收入（外部收入加分部间收入）。"
        ),
    }
    return [two_lines, share, margins]


# ── section three: what to watch through the rest of the open year ─────────
def margin_point(margin: dict) -> bool:
    """A GAAP margin guided as one number ("Approximately 45%") against a range."""
    return margin["gaap"][0] == margin["gaap"][1] and margin["adjusted"][0] != margin["adjusted"][1]


def bridge_sums(bridges: dict) -> dict:
    """Whether each of the three printed bridges adds up.

    A range bridges to a range end for end. A GAAP margin the company guided as
    a single number cannot land on both ends of an adjusted range; it closes when
    it lands inside it (April 2026: about 45% plus 7.5 points is 52.5%, inside
    52%-53%).
    """
    eps, margin, fcf = bridges["eps"], bridges["margin"], bridges["fcf"]
    eps_add = sum(delta for _, delta in eps["addbacks"])
    margin_add = sum(delta for _, delta in margin["addbacks"])
    if margin_point(margin):
        margin_ok = margin["adjusted"][0] - 0.05 <= margin["gaap"][0] + margin_add <= margin["adjusted"][1] + 0.05
    else:
        margin_ok = all(abs(g + margin_add - a) < 0.05 for g, a in zip(margin["gaap"], margin["adjusted"]))
    return {
        "eps": all(abs(g + eps_add - a) < 0.005 for g, a in zip(eps["gaap"], eps["adjusted"])),
        "margin": margin_ok,
        "fcf": all(abs(o - fcf["capex"] - f) < 0.005 for o, f in zip(fcf["ocf"], fcf["fcf"])),
    }


def margin_bridge_words(margin: dict) -> str:
    total = margin["gaap"][0] + sum(delta for _, delta in margin["addbacks"])
    terms = (f"{pct_words(margin['gaap'][0])}"
             + "".join(f"+{pct_words(delta)}" for _, delta in margin["addbacks"]))
    if margin_point(margin):
        return (f"营业利润率约 {terms} = {pct_words(round(total, 2))}，落在调整后区间 "
                f"{pct_words(margin['adjusted'][0])}–{pct_words(margin['adjusted'][1])} 之内")
    return f"营业利润率 {terms} = {pct_words(margin['adjusted'][0])}"


def next_watch(staging: dict, guidance: dict | None, bridges: dict | None,
               story: dict | None, release_date: str) -> list[dict]:
    charts = []
    year = guidance["fiscal_year"] if guidance else None
    if bridges:
        eps = bridges["eps"]
        closes = bridge_sums(bridges)
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
        count = cn_count(len(eps["addbacks"]))
        sum_words = (f"US${eps['gaap'][0]:.2f}"
                     + "".join(f" {'+' if delta >= 0 else '−'} {money(delta)}" for _, delta in eps["addbacks"])
                     + f" = <b>US${running:.2f}</b>")
        margin = bridges["margin"]
        cash = bridges["fcf"]
        negative = [name for name, delta in eps["addbacks"] if delta < 0]
        charts.append({
            "ref": "EX_BRIDGE",
            "kind": "bars_labeled",
            "title": (f"指引表自己就能对平：GAAP 指引下限加{count}项加回项，正好等于调整后指引下限 "
                      f"US${eps['adjusted'][0]:.2f}" if closes["eps"] else
                      f"指引表的 EPS 桥：GAAP 指引下限加{count}项加回项是 US${running:.2f}，"
                      f"公司印的调整后下限是 US${eps['adjusted'][0]:.2f}"),
            "xlabels": steps,
            "xrot": 90,
            "values": lo_vals,
            "fmt": "usd2",
            "ylab": f"US$/股（FY{year} 指引下限口径）",
            "note": (
                "公司在同一份文件里把 GAAP 指引调节到调整后指引，每一项都点名并给了金额。"
                f"把它们逐项加回去，{sum_words}，"
                + (f"与公司自己印出来的调整后下限逐分吻合；上限同理得 US${eps['adjusted'][1]:.2f}。"
                   "<b>这是本页愿意把这张指引表当作算术而不是口号来用的依据。</b>"
                   if closes["eps"] else
                   f"与公司印出来的调整后下限 US${eps['adjusted'][0]:.2f} 对不上。")
                + ("同一份文件里另外两条桥也各自对平：" if closes["margin"] and closes["fcf"] else
                   "同一份文件里另外两条桥：")
                + margin_bridge_words(margin) + "，"
                f"经营现金流 US${cash['ocf'][0]:.2f}B 减资本开支约 US${cash['capex']:.2f}B = "
                f"自由现金流 US${cash['fcf'][0]:.2f}B。"
            ),
            "src_extra": (
                f"FY{year} 指引与调节均取自 {release_date} 业绩 8-K EX-99.1；"
                "加回项为公司列示值"
                + (f"，负号项为{'、'.join(negative)}。" if negative else "。")
            ),
        })

    if guidance:
        items = [(name, guidance[key], unit) for name, key, unit in WIDTH_ITEMS]
        g = staging["annual_guidance_history"]
        month = VINTAGE_MONTH[next(v for v in reversed(VINTAGES)
                                   if g["release_dates"][str(year)][v] == guidance["as_of"])]
        lo, hi = guidance["adj_diluted_eps_usd"]
        has_october = g["release_dates"][str(year)]["Oct"] is not None
        charts.append({
            "ref": "EX_WIDTH",
            "kind": "bars_labeled",
            "title": f"FY{year} 还开着的数字指引里，EPS、利润率与现金流这{cn_count(len(items))}条各自还剩多宽的区间",
            "xlabels": [name for name, _, _ in items],
            "xrot": 90,
            "values": [round((b - a) / mid(a, b) * 100, 2) for _, (a, b), _ in items],
            "fmt": "pct1",
            "ylab": "%（区间宽度占中值）",
            "note": (
                f"越窄说明公司自认为越接近确定。到 {month}这一版，"
                f"调整后 EPS 的区间已经收到中值的 {(hi - lo) / mid(lo, hi) * 100:.1f}%，"
                "而收入、费用、ARR 那几行公司<b>只给文字口径</b>"
                + (f"（{story['verbal_quote']}）" if story and story.get("verbal_quote") else "")
                + "，本页不把文字换算成数字，所以它们不在这张图上，也不在任何一张带子里。"
                + ("" if has_october else
                   f"10 月那一版落地后，本页第一节的 FY{year} 一格才会补上末次指引。")
            ),
            "src_extra": f"{guidance['as_of']} 业绩 8-K EX-99.1 的全年指引表；宽度为自算。",
        })
    return charts


# ── section four: the routine multi-period series ──────────────────────────
def routine(staging: dict, bridges: dict | None) -> list[dict]:
    ann = staging["annual_actuals"]
    seg = staging["segment_quarterly"]
    years = ann["fiscal_years"]
    ylabels = [f"FY{y}" for y in years]
    n_years = cn_count(len(years))

    margin = ann["operating_margin_pct"]
    low_all = years[margin.index(min(margin))]
    adjusted_from = next(y for y, v in zip(years, ann["adjusted_diluted_eps_usd"]) if v is not None)
    recent = [(y, m) for y, m in zip(years, margin) if y >= adjusted_from]
    low_recent = min(recent, key=lambda pair: pair[1])
    top = years[margin.index(max(margin))]

    low_words = (f"低点是 FY{low_all} 的 {min(margin):.1f}%"
                 + ((f"（{MARGIN_STORY[low_all]}）" if low_all in MARGIN_STORY else "")
                    + f"；FY{adjusted_from} 以来的低点是 FY{low_recent[0]} 的 {low_recent[1]:.1f}%"
                    + (f"，{MARGIN_STORY[low_recent[0]]}" if low_recent[0] in MARGIN_STORY else "")
                    if low_recent[0] != low_all else
                    (f"，{MARGIN_STORY[low_all]}" if low_all in MARGIN_STORY else "")))
    rev_margin = {
        "ref": "EX_ANN",
        "kind": "lines",
        "title": (
            f"{n_years}年收入从 US${ann['revenue_usd_m'][0]/1000:.1f}B 到 "
            f"US${ann['revenue_usd_m'][-1]/1000:.1f}B，营业利润率走完一轮 "
            f"{min(margin):.1f}% 到 {max(margin):.1f}%"
        ),
        "xlabels": ylabels,
        "series": [
            {"name": "营业利润率", "values": margin, "color": "NAVY"},
        ],
        "fmt": "pct1",
        "ylab": "%（GAAP 营业利润率）",
        "note": (
            "用 GAAP 营业利润率而不是调整后口径来画长序列，因为 GAAP 的定义"
            f"自 FY{adjusted_from} 起的{cn_count(len(recent))}年没动过"
            + (f"（更早的 FY{years[0]}–FY{adjusted_from - 1} 取当年 10-K 首次申报的值）"
               if years[0] < adjusted_from else "")
            + f"。{low_words}；"
            + (f"FY{years[-1]} 回到 {margin[-1]:.1f}%，仍低于 FY{top} 的 {max(margin):.1f}%。"
               if years[-1] != top else f"FY{years[-1]} 的 {margin[-1]:.1f}% 是窗口内最高。")
            + "把它和第一节 Exhibit {EX_INITIAL} 对着看："
            "利润率的这一轮起落，就是年初指引那几次大幅搬家的实物基础。"
        ),
        "src_extra": "XBRL companyfacts（us-gaap:OperatingIncomeLoss / 收入），口径为 10-K 申报值。",
    }

    gaap, adjusted = ann["diluted_eps_usd"], ann["adjusted_diluted_eps_usd"]
    gaps = [(y, a - g) for y, a, g in zip(years, adjusted, gaap) if a is not None]
    n_adjusted = len(gaps)
    negatives = ann.get("negative_adjustments_usd", {})
    neg_years = sorted(int(y) for y in negatives)
    largest = min(((int(y), name, value) for y, rows in negatives.items() for name, value in rows),
                  key=lambda row: row[2], default=None)
    fy_gap = ""
    if bridges:
        guided_gap = bridges["eps"]["adjusted"][0] - bridges["eps"]["gaap"][0]
        guided_neg = [(name, delta) for name, delta in bridges["eps"]["addbacks"] if delta < 0]
        year = int(bridges["period"][-4:])
        narrowest = guided_gap < min(gap for _, gap in gaps)
        if guided_neg:
            name, delta = min(guided_neg, key=lambda row: row[1])
            fy_gap = (f"<b>FY{year} 的指引里有一项 US${money(delta)} 的负加回</b> —— {name}；"
                      + (f"负加回此前也出现过，{cn_count(n_adjusted)}个有调整后口径的年度里有"
                         f"{cn_count(len(neg_years))}年，最大的是 FY{largest[0]} 的{largest[1]} "
                         f"−US${money(largest[2])}"
                         + (f"，这一次是它的{cn_count(int(abs(delta) / abs(largest[2])))}倍多" if abs(delta) >= 2 * abs(largest[2]) else "")
                         + "。" if largest else "")
                      + f"所以那一年的调整后指引与 GAAP 指引之间的缺口只有 US${guided_gap:.2f}"
                      + ("，是这条记录里最窄的一次。" if narrowest else "。"))
    eps_cmp = {
        "ref": "EX_EPS_ANN",
        "kind": "lines",
        "title": (f"{n_years}年 GAAP 与{cn_count(n_adjusted)}年调整后摊薄 EPS：两条线之间的缺口就是每年被加回的那些项"
                  if n_adjusted != len(years) else
                  f"{n_years}年 GAAP 与调整后摊薄 EPS：两条线之间的缺口就是每年被加回的那些项"),
        "xlabels": ylabels,
        "series": [
            {"name": "GAAP 摊薄 EPS", "values": gaap},
            {"name": "调整后摊薄 EPS", "values": adjusted, "color": "NAVY"},
        ],
        "fmt": "usd2",
        "ylab": "US$/股",
        "note": (
            ("调整后口径每年都高于 GAAP，" if all(gap > 0 for _, gap in gaps) else "")
            + f"缺口在 US${min(g for _, g in gaps):.2f}–{max(g for _, g in gaps):.2f} 之间，"
            + ("构成与本页 Exhibit {EX_BRIDGE} 那张桥列出的项目同类：摊销、重组、税务准备。"
               if bridges else "主要是摊销与重组。")
            + fy_gap
        ),
        "src_extra": "GAAP 取自 XBRL；调整后取自各年 2 月业绩新闻稿的全年结果。",
    }

    fcf = ann["free_cash_flow_usd_m"]
    fcf_low = years[fcf.index(min(fcf))]
    capex_share = [c / r * 100 for c, r in zip(ann["capex_usd_m"], ann["revenue_usd_m"])]
    top_share = years[capex_share.index(max(capex_share))]
    # The lowest cash year is explained by what happened in it, when this page
    # knows; the original sentence said issuance, which was true only while the
    # window started at FY2018.
    cash_story = (f"所以这两条线几乎平行 —— 穆迪的现金波动从来不来自资本开支：FY{fcf_low} 那个低点是"
                  f"{CASH_STORY[fcf_low]}"
                  + ("，FY2022 的回落跟着发行量走。" if fcf_low != 2022 and 2022 in years else "。")
                  if fcf_low in CASH_STORY and fcf_low != 2022 else
                  "所以这两条线几乎平行 —— 穆迪的现金问题从来不在资本开支上，而在发行量上。")
    cash = {
        "ref": "EX_CASH",
        "kind": "lines",
        "title": (
            f"{n_years}年经营现金流与自由现金流：FY{fcf_low} 的 US${min(fcf)/1000:.2f}B "
            f"是低点，FY{years[-1]} US${fcf[-1]/1000:.2f}B"
        ),
        "xlabels": ylabels,
        "series": [
            {"name": "经营现金流", "values": [v/1000 if v else None for v in ann["operating_cash_flow_usd_m"]]},
            {"name": "自由现金流（自算）", "values": [v/1000 if v else None for v in fcf],
             "color": "NAVY"},
        ],
        "fmt": "usd2",
        "ylab": "US$B",
        "note": (
            "自由现金流是经营现金流减去申报的资本开支，两条腿都是申报值，没有估计。"
            f"资本开支{n_years}年从 US${ann['capex_usd_m'][0]:,.0f}M 升到 US${ann['capex_usd_m'][-1]:,.0f}M，"
            + ("仍不到收入的 5%，" if max(capex_share) < 5 else
               f"最高也只占收入的 {max(capex_share):.1f}%（FY{top_share}），")
            + cash_story
        ),
        "src_extra": "XBRL companyfacts；自由现金流为经营现金流减资本开支的自算值，与公司自己的 FCF 定义一致。",
    }

    mis_oi = seg["mis_adj_operating_income_usd_m"]
    seg_oi = {
        "ref": "EX_SEG_OI",
        "kind": "lines",
        "title": f"{len(seg['periods'])} 季两块业务的调整后营业利润：评级那条的波动就是全年指引的波动",
        "xlabels": seg["periods"],
        "xstep": LONG_STEP,
        "series": [
            {"name": "MIS 调整后营业利润", "values": mis_oi},
            {"name": "MA 调整后营业利润", "values": seg["ma_adj_operating_income_usd_m"], "color": "NAVY"},
        ],
        "fmt": "usd0",
        "ylab": "US$M",
        "note": (
            f"MA 那条从 US${seg['ma_adj_operating_income_usd_m'][0]:,.0f}M 抬到 US$"
            f"{seg['ma_adj_operating_income_usd_m'][-1]:,.0f}M，窗口内峰值 US$"
            f"{max(seg['ma_adj_operating_income_usd_m']):,.0f}M；"
            f"MIS 那条在 US${min(mis_oi):,.0f}M 到 US$"
            f"{max(mis_oi):,.0f}M 之间走了一整轮。"
            "本季 MIS 调整后营业利润 US$"
            f"{mis_oi[-1]:,.0f}M"
            + ("，是 %d 季新高。" % len(seg['periods'])
               if mis_oi[-1] == max(mis_oi)
               else "，窗口内新高是 US$%s M。" % format(max(mis_oi), ',.0f'))
        ),
        "src_extra": "各期业绩 8-K EX-99.1 的分部表；分部调整后营业利润为公司披露值。",
    }
    return [rev_margin, eps_cmp, cash, seg_oi]


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    q = staging["segment_quarterly"]
    figures = stamped_block(staging, "quarter_figures", q["periods"][-1])
    return [f"Revenue ${q['revenue_usd_m'][-1] / 1000:.2f}B",
            f"MIS adj OpM {q['mis_adj_operating_margin_pct'][-1]:.1f}%",
            (f"调整后 EPS ${figures['adj_diluted_eps_usd']:.2f}" if figures else
             f"MA adj OpM {q['ma_adj_operating_margin_pct'][-1]:.1f}%")]


def build_payload(staging: dict) -> dict:
    seg = staging["segment_quarterly"]
    period = seg["periods"][-1]
    latest = latest_block(staging, period=period, period_end=seg["period_ends"][-1])
    release = release_source(staging)
    guidance = stamped_block(staging, "current_guidance", period)
    bridges = stamped_block(staging, "guidance_bridges", period)
    story = stamped_block(staging, "quarter_story", period)
    # Only the home card reads it, but a stale one must stop the page as well.
    stamped_block(staging, "quarter_figures", period)

    facts = record_facts(staging)
    sf = segment_facts(staging)
    ma_yoy = pct_change(seg["ma_revenue_usd_m"][-1], seg["ma_revenue_usd_m"][-5])
    values = {"ma_yoy": f"{ma_yoy:+.0f}%"}
    if bridges:
        negative = [delta for _, delta in bridges["eps"]["addbacks"] if delta < 0]
        if negative:
            values["gain"] = money(min(negative))

    settled_ex = guidance_record(staging, facts)
    highlight_ex = quarter_highlights(staging, facts, sf, story, values)
    next_ex = next_watch(staging, guidance, bridges, story, latest["release_date"])
    routine_ex = routine(staging, bridges)

    all_ex = number_exhibits(settled_ex + highlight_ex + next_ex + routine_ex, start=1)
    resolve_exhibit_refs(all_ex)
    a, b, c = len(settled_ex), len(highlight_ex), len(next_ex)
    settled_ex, highlight_ex = all_ex[:a], all_ex[a:a + b]
    next_ex, routine_ex = all_ex[a + b:a + b + c], all_ex[a + b + c:]

    ann = staging["annual_actuals"]
    g = staging["annual_guidance_history"]
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
            "title": f"FY{years[0]}–FY{years[-1]} 全年调整后摊薄 EPS 指引的四个版本与实际（US$/股）",
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
            "title": f"FY{ann['fiscal_years'][0]}–FY{ann['fiscal_years'][-1]} 年度实际",
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

    n_done = len(facts["finished"])
    worst_cut = min(facts["path"], key=facts["path"].get)
    final_below, initial_inside = facts["final_below"], facts["initial_inside"]
    audit_words = {"unaudited": "未审计", "audited": "已审计"}[latest["audit_status"]]
    closes = bridge_sums(bridges) if bridges else None
    record_title = (
        ("末次指引跌破过" + cn_count(len(final_below)) + "次" if final_below else "末次指引从没跌破过")
        + "，"
        + ("初始指引一次都没对过" if not initial_inside else
           f"初始指引对过{cn_count(len(initial_inside))}次"))
    articles = [
        f'<article><span>记录</span><b>{record_title}</b>'
        f'<p>{n_done} 个已完结年度：对 10 月那版下限 '
        f'{len(final_below)} 次跌破；'
        f'对 2 月那版 {len(initial_inside)} 次落在区间内。'
        f'FY{worst_cut} 中值从 2 月到 10 月被砍了 {abs(facts["path"][worst_cut]):.0f}%。</p></article>',
        '<article><span>结构</span><b>'
        + ("评级是收入的少数，利润的多数" if min(seg["mis_share_of_revenue_pct"]) < 50
           < min(seg["mis_share_of_adj_operating_income_pct"]) else "评级在利润里的份量大于在收入里的份量")
        + '</b>'
        f'<p>{len(seg["periods"])} 季里 MIS 占收入 {min(seg["mis_share_of_revenue_pct"]):.0f}%–'
        f'{max(seg["mis_share_of_revenue_pct"]):.0f}%，'
        f'却占调整后营业利润 {min(seg["mis_share_of_adj_operating_income_pct"]):.0f}%–'
        f'{max(seg["mis_share_of_adj_operating_income_pct"]):.0f}%。</p></article>',
    ]
    if bridges:
        eps = bridges["eps"]
        articles.append(
            '<article><span>本季</span><b>'
            + ("指引表三条桥全部对平" if all(closes.values()) else "指引表三条桥没有全部对平")
            + '</b>'
            f'<p>GAAP EPS 加{cn_count(len(eps["addbacks"]))}项加回项'
            + ("等于" if closes["eps"] else "不等于")
            + f'调整后 EPS US${eps["adjusted"][0]:.2f}–{eps["adjusted"][1]:.2f}；'
            + (('利润率桥落在调整后区间之内，自由现金流桥逐项吻合。' if margin_point(bridges["margin"]) else
                '利润率与自由现金流两条桥同样逐项吻合，误差为零。')
               if closes["margin"] and closes["fcf"] else
               '利润率与自由现金流两条桥没有全部对上，差额写在桥图的说明里。')
            + '</p></article>')

    seg_rev = seg["revenue_usd_m"]
    open_year = guidance["fiscal_year"] if guidance else None
    notes = [
        "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
        "穆迪为自然年财年（12 月 31 日结束），本页季度标注与公司口径一致，无需换算。",
        "本页最需要说明的一条：穆迪<b>从不给下一季度的数字指引</b>，它给的是全年指引并在当年逐季修订。"
        "因此本页第一节结算的对象是财年而不是季度；末次指引落笔时全年已经过了四分之三，"
        "所以「跌破得少」这件事本身的份量，远小于同一句话出现在按季度指引的公司身上。"
        + ("另外，本页此前把 FY2018 排除在记录之外、理由写的是「只有十月一个 vintage」，"
           f"那句话是错的（四版齐全），而那一年正是{cn_count(n_done)}年里唯一跌破末次指引下限的一年。"
           if final_below == [2018] else "")
        + "本页用两张图（对初始指引、对末次指引）并排把这件事讲清楚，而不是只报一个命中率。",
        "指引表里的收入类各行（MCO/MIS/MA 收入、费用、ARR）公司<b>只给文字口径</b>，"
        "例如「increase in the high-single-digit percent range」。"
        "文字不是数字区间，本页不把它换算成端点，因此这几行没有兑现图，也不进任何一张带子。",
        "2021-08-05 另有一次非季度节奏的指引更新（在 7 月 28 日那期之后），"
        "该次调整后 EPS 指引与 7 月那版相同，本页按季度节奏取数，未单列该期。",
        "分部数据的列先后顺序在 2023 年 4 月那期之后由「MIS 在前」改为「MA 在前」。"
        "本页按表头里的分部名取值而不是按列位，重叠季度在两份来源之间逐项一致。",
        "分部调整后营业利润率的分母是<b>分部总收入</b>（外部收入加分部间收入），"
        "而本页图上画的分部收入是<b>外部收入</b>口径。两者差的就是分部间计费："
        f"MIS 每季向 MA 内部计费 US${min(sf['mis_internal']):,.0f}–{max(sf['mis_internal']):,.0f}M，"
        f"MA 向 MIS US${min(sf['ma_internal']):,.0f}–{max(sf['ma_internal']):,.0f}M。"
        f"用外部收入去除调整后营业利润会把 MIS 的利润率高估 {overstated_words(sf)}；"
        f"按总收入复算，{len(seg['periods'])} 个季度与公司自己印出来的百分比"
        f"最大只差 {sf['margin_slack']:.2f}pp，"
        f"那 {sf['margin_slack']:.2f}pp 是公司把百分比四舍五入到一位小数留下的余数。",
    ]
    if story and story.get("divestitures"):
        notes.append(fill_story(story["divestitures"], values))
    notes += [
        "核对表的取数来源：全年指引四栏的每一格是该期业绩 8-K EX-99.1 指引表里的当期值，"
        "全年实际取次年 2 月那期的全年结果；分部表为外部收入口径（不含分部间收入）；"
        "年度表的 GAAP 各列取自 XBRL companyfacts，调整后 EPS 取自各年 2 月业绩新闻稿。",
        "自由现金流为经营现金流减申报资本开支的自算值，与公司自己的定义一致；标 D 的项均为此类透明自算。",
        "本页不发布评级、目标价、估值与任何券商共识，也不发布公司未在申报文件中给出的数字。",
    ]
    return {
        "schema_version": "quarterly-dashboard/mco-v1",
        "page": {"slug": "mco", "language": "zh-CN"},
        "company": {
            "ticker": "MCO",
            "name": "Moody's Corporation",
            "group": "financial_data_indices",
            "accounting_standard": "US GAAP",
        },
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · MCO",
        "title": f"Moody's Corporation (MCO)：{period} 季报仪表盘",
        "subtitle": (
            f"截至 {latest['period_end']} · 发布 {latest['release_date']} · US GAAP · {audit_words} · "
            "自然年财年，季度标注无需换算"
        ),
        # `assets/page.js` sets this with textContent, so it is a plain-text
        # slot: any markup here reaches the reader as literal characters.
        "headline": plain_text(
            f"收入 US${seg_rev[-1]:,.0f}M、同比 "
            f"{signed(pct_change(seg_rev[-1], seg_rev[-5]))}，"
            f"调整后营业利润率 {seg['adj_operating_margin_pct'][-1]:.1f}%。"
            "但本页真正的对象不是这个季度 —— 穆迪不给季度指引，它给的是全年指引并逐季修订。"
            f"{n_done} 个已完结年度里，实际值相对末次（10 月）指引"
            f"高于上限 {len(facts['final_above'])} 次、落在区间内 {len(facts['final_inside'])} 次、"
            f"跌破下限 {len(final_below)} 次；"
            f"相对初始（2 月）指引却是高于 {len(facts['initial_above'])} 次、"
            f"跌破 {len(facts['initial_below'])} 次、"
            + ("一次都没落在区间内。" if not initial_inside else f"落在区间内 {len(initial_inside)} 次。")
            + "同一个数字，差别只在画线时离年末还有多远。"
        ),
        "brief": (
            f'<h4>本季{cn_count(len(articles))}条主线</h4><div class="takeaway-grid">'
            + "".join(articles)
            + '</div>'
        ),
        "source": (
            f'Source: <a href="{release["url"]}" rel="noopener">Moody\'s {period} '
            f'业绩新闻稿（8-K EX-99.1）</a>{periodic_report_words(staging)}。'
        ),
        "source_url": release["url"],
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {
                "id": "settled",
                "title": "一、上季兑现了吗",
                "description": plain_text(
                    "这一节和本站其他几页结算的东西不是同一类。穆迪不给下一季度的数字区间，"
                    "它在每份业绩 8-K 里给一张全年指引表，然后在当年的后三期各更新一次。"
                    "所以这里结算的是「年」而不是「季」，而真正的变量是画线时离年末还有多远。"
                ),
                "exhibits": settled_ex,
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": plain_text(
                    "评级与分析两块业务在收入上的分岔"
                    + ("、它们在利润上的极不对称，" + story["section_tail"] + "。"
                       if story and story.get("section_tail") else
                       "，以及它们在利润上的极不对称。")
                ),
                "exhibits": highlight_ex,
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": plain_text(
                    (f"FY{open_year} 还开着的数字指引里 EPS、利润率与现金流"
                     f"{cn_count(len(WIDTH_ITEMS))}条各自还剩多宽，"
                     if guidance else "")
                    + ("以及那张让本页愿意把指引表当算术用的口径桥。" if bridges else "")
                    + ("" if guidance or bridges else "本季没有接入全年指引表，本节没有图。")
                    + "只给文字口径的几行不换算成数字，写在口径说明里。"
                ),
                "exhibits": next_ex,
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": plain_text(
                    f"MCO 专属的常规序列：{cn_count(len(ann['fiscal_years']))}年营业利润率的一轮起落、"
                    "GAAP 与调整后 EPS 之间那道逐年变化的缺口、"
                    "现金流的两条腿，以及两块业务各自的调整后营业利润。"
                ),
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": [plain_text(p) for p in notes],
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
