"""Philip Morris International quarterly dashboard.

PMI is the first company on this site that guides **the same earnings number at
two horizons and on two definitions**, and the four records that fall out of
that disagree with each other. Every quarterly earnings 8-K since the 2008
spin-off carries a full-year EPS forecast, revised each quarter -- seventy-one
vintages across eighteen years, the longest guidance record here by a wide
margin. From the 2020 second quarter it also carries a *next-quarter* forecast,
and in 2022-2023 the guided quarterly metric moved from reported diluted EPS to
adjusted diluted EPS.

Read on the reported basis, the record is the only two-sided one on this site:
the year landed **below its own final range in five of sixteen** years, above in
seven and inside in four. Read on the adjusted basis -- same company, same
release, same horizon -- the next-quarter number has cleared the top of its
range in **twelve of twelve** finished quarters and the full year has missed
once in six.

The reason is written into the guidance itself rather than inferred. From the
2008 spin-off through the February 2022 release, every full-year forecast
carried the same clause: it excludes future acquisitions, unanticipated asset
impairment and exit-cost charges, and any unusual events. So the number labelled
GAAP was never a forecast of GAAP -- it was a GAAP number conditional on nothing
unusual happening, and each of the five misses is a year in which something
unusual happened. FY2024 is the clean case: reported EPS came in at US$4.52
against a final guidance of US$6.20-6.26, entirely because of a US$1.49 non-cash
impairment of the deconsolidated Canadian affiliate recognised after the
guidance was published. The adjusted line for the same year cleared its range.

Published numbers are company-reported or transparent arithmetic. No rating, no
target price and no broker-attributed estimate appears here.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import (  # noqa: E402
    ai_capex_cycle_table,
    delivery_band,
    headroom,
    headroom_exhibit,
    number_exhibits,
    threshold_exhibit,
    threshold_table,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "pm.json"
DATA_DIR = ROOT / "data"

# One tick per year keeps the thirty-eight-quarter axes readable.
LONG_STEP = 4

SEG_KEYS = ("international_smoke_free", "international_combustibles", "us")
SEG_NAMES = {"international_smoke_free": "国际无烟", "international_combustibles": "国际组合烟草",
             "us": "美国"}
SEG_COLORS = {"international_smoke_free": "NAVY", "international_combustibles": "BLUE",
              "us": "GOLD"}

# FY2019 and the FY2020 opening were published as a floor with no upper bound
# ("forecast to be at least $4.73"), so those years have no band to clear and
# sit outside the band chart rather than being drawn as a zero-width range.
FLOOR_YEARS = (2019,)


def rounded(values, digits: int = 6):
    return [None if v is None else round(v, digits) for v in values]


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100.0


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def mid(low: float, high: float) -> float:
    return (low + high) / 2


def resolve_exhibit_refs(exhibits: list[dict]) -> list[dict]:
    """Replace ``{EX_NAME}`` placeholders with the numbers assigned at render.

    Exhibits are numbered in render order by ``board.number_exhibits``, so a
    caption cannot name its neighbour until after numbering.
    """
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


def verdict_of(actual: float | None, low: float, high: float) -> str | None:
    if actual is None:
        return None
    if actual > high:
        return "above"
    if actual < low:
        return "below"
    return "inside"


def tally(rows: list[tuple[float | None, float, float]]) -> tuple[int, int, int, int]:
    """(finished, above, inside, below) for a list of (actual, low, high)."""
    verdicts = [verdict_of(a, lo, hi) for a, lo, hi in rows]
    done = [v for v in verdicts if v]
    return (len(done), done.count("above"), done.count("inside"), done.count("below"))


# ── section one: the guidance record ────────────────────────────────────────


def annual_records(staging: dict):
    """Split the annual record into the years a range was actually published."""
    banded, floors = [], []
    for record in staging["annual_guidance"]["records"]:
        last = record.get("last_guided")
        if not last:
            continue
        if last["form"] == "floor" or record["year"] in FLOOR_YEARS:
            floors.append(record)
        else:
            banded.append(record)
    return banded, floors


def annual_reported_band(staging: dict) -> dict:
    banded, floors = annual_records(staging)
    labels = [f"FY{r['year']}" for r in banded]
    low = [r["last_guided"]["low"] for r in banded]
    high = [r["last_guided"]["high"] for r in banded]
    actual = [r["actual_reported_eps"] for r in banded]
    years = [r["year"] for r in banded]
    # The axis jumps 2018 -> 2020 because 2019 was guided as a floor; the marker
    # says so rather than letting the gap read as a missing year.
    break_at = years.index(2020) if 2020 in years else None
    return delivery_band(
        "EX_FY_BAND", "全年报告口径摊薄每股收益", labels, low, high, actual,
        fmt="usd2", ylab="US$/股", unit="US$/股",
        venue="业绩新闻稿", period_word="年",
        timing="该年<b>当年内</b>",
        scope="（当年最后一次指引）",
        break_at=break_at,
        break_label="2019 年只给下限，不在本图",
        extra_note=(
            "画的是<b>当年最后一次</b>指引，通常发布于 10 月，此时全年已过去四分之三。"
            "横轴从 FY2018 跳到 FY2020，是因为 "
            + "、".join("FY%d" % r["year"] for r in floors) + " "
            "的指引是「至少 US$X」这样只有下限的形式，没有上限可以穿出，画成零宽区间会造出"
            "一个公司没说过的上界；这些年份的记录见核对抽屉。"
            "<b>更要紧的是这条指引长期带着一句排除条款</b>：2008 年 4 月到 2022 年 2 月的 56 份"
            "新闻稿里有 54 份写明该预测不含未来并购、未预料到的资产减值与退出成本、"
            "以及任何异常事件（两个例外是 2008-10-22，以及 2020-04-21 那份根本没给全年预测的）。所以这个挂着 GAAP 名字的数并不是对 GAAP 的预测，"
            f"而是「不出异常事件时的 GAAP」。同一记录换成公司自定义的调整后口径见 Exhibit {{EX_ADJ_BAND}}。"),
        src_extra=("指引取自各年最后一份季度业绩 8-K EX-99.1 的全年预测段；"
                   "实际值取自 XBRL companyfacts 的年度 EarningsPerShareDiluted。"),
    )


def annual_deviation(staging: dict) -> dict:
    """How far the year landed from its opening range and from its final one."""
    banded, _ = annual_records(staging)
    rows = [r for r in banded if r["actual_reported_eps"] is not None
            and r["first_guided"] and r["first_guided"].get("high")]
    labels = [f"FY{r['year']}" for r in rows]
    first = [pct_change(r["actual_reported_eps"],
                        mid(r["first_guided"]["low"], r["first_guided"]["high"])) for r in rows]
    last = [pct_change(r["actual_reported_eps"],
                       mid(r["last_guided"]["low"], r["last_guided"]["high"])) for r in rows]
    mean_first = statistics.fmean(abs(v) for v in first)
    mean_last = statistics.fmean(abs(v) for v in last)
    worst = max(first, key=abs)
    return {
        "ref": "EX_FY_DEV",
        "kind": "grouped_bars",
        "title": (f"同一年、两次指引：对年初那次平均绝对偏离 {mean_first:.1f}%，"
                  f"对年末那次 {mean_last:.1f}%"),
        "xlabels": labels,
        "xrot": 90,
        "groups": [
            {"name": "实际 vs 年初第一次指引中值", "color": "GOLD", "values": rounded(first, 2)},
            {"name": "实际 vs 当年最后一次指引中值", "color": "NAVY", "values": rounded(last, 2)},
        ],
        "bar_labels": False,
        "fmt": "pct1", "label_fmt": "pct1",
        "ylab": "% vs 指引中值",
        "note": (
            "两根柱的<b>差</b>就是一年里修订做的功。年初那次给的是十二个月的预测，"
            "年末那次发布时全年已经过去四分之三，所以后者更接近零是记账而不是预测能力 —— "
            "本站在 S&P Global 与穆迪两页上遇到过同样的形状。"
            f"窗口内对年初指引偏得最远的一年是 {labels[first.index(worst)]}，{worst:+.1f}%。"
            "注意这里两条腿都是<b>报告口径</b>：偏离里既有经营，也有汇率、税项与减值。"),
        "src_extra": "偏离 = 实际 ÷ 指引中值 − 1；两个中值分别取该年第一次与最后一次指引区间的中点。",
    }


def annual_adjusted_band(staging: dict) -> dict:
    """The same years on the company's own adjusted definition."""
    hist = staging["annual_guidance"]
    actuals = hist["annual_adjusted_eps_actual"]
    rows = []
    for record in hist["records"]:
        vintages = [v for v in record["vintages"] if v.get("adj_low") is not None]
        if not vintages:
            continue
        last = vintages[-1]
        rows.append((record["year"], last["adj_low"], last["adj_high"],
                     actuals.get(str(record["year"]))))
    labels = [f"FY{y}" for y, _, _, _ in rows]
    return delivery_band(
        "EX_ADJ_BAND", "全年调整后摊薄每股收益", labels,
        [lo for _, lo, _, _ in rows], [hi for _, _, hi, _ in rows],
        [a for _, _, _, a in rows],
        fmt="usd2", ylab="US$/股", unit="US$/股",
        venue="业绩新闻稿", period_word="年",
        timing="该年<b>当年内</b>",
        scope="（当年最后一次指引）",
        extra_note=(
            "<b>这张图和上面那张是同一家公司、同一批年份、同一份新闻稿里的同一张表</b>，"
            "唯一的差别是把公司自己点名并逐项计价的调整加回去。"
            "报告口径那条自 2009 年起有 16 个完整年度，调整后这条自 2020 年公司开始在预测表里"
            "并列两行才有，所以窗口短得多 —— 这是披露的限制，不是本页的取舍。"),
        src_extra=("指引取自各年最后一份业绩 8-K EX-99.1 全年预测表的 Adjusted Diluted EPS 行；"
                   "实际值取自次年第四季新闻稿标题与预测表的上年对照列，两处逐年一致。"),
    )


def quarter_band(staging: dict) -> dict:
    rows = staging["quarterly_guidance"]
    labels = [r["period_label"] for r in rows]
    low = [r["low"] for r in rows]
    high = [r["high"] for r in rows]
    actual = [r["actual_eps"] for r in rows]
    first_adjusted = next(i for i, r in enumerate(rows) if r["basis"] != "reported")
    band = delivery_band(
        "EX_Q_BAND", "下季每股收益", labels, low, high, actual,
        fmt="usd2", ylab="US$/股", unit="US$/股",
        venue="业绩新闻稿",
        timing="该季<b>开始后 19–40 天</b>",
        break_at=first_adjusted,
        break_label="指引口径改为调整后",
        extra_note=(
            "<b>横轴上没有 2021 到 2025 的任何第四季，这不是缺数据</b>：PMI 只指引第一、二、"
            "三季，从不指引第四季 —— 唯一的例外是 2020 年第四季，那一次还是个单点（「约 "
            "US$1.16」）而不是区间。窗口内被指引的 20 个季度里有 2 个是单点，图上因此有两格"
            "没有宽度。左段的指引口径是<b>报告</b>每股收益，右段是<b>调整后</b>每股收益，"
            "2022 年第二、三季那两格还是剔除俄罗斯与乌克兰的 pro forma 口径 —— 实际值一律"
            "按各自当期的口径取，不跨口径比较。"),
        src_extra=("指引取自各季业绩 8-K EX-99.1 全年预测假设段的最后一条；实际值中报告口径"
                   "取自 companyfacts，调整后与 pro forma 口径取自随后那份新闻稿的标题与"
                   "EPS 调节表。"),
    )
    return band


def quarter_deviation(staging: dict) -> dict:
    rows = [r for r in staging["quarterly_guidance"] if r["actual_eps"] is not None]
    labels = [r["period_label"] for r in rows]

    def leg(reported: bool):
        return rounded([
            pct_change(r["actual_eps"], mid(r["low"], r["high"]))
            if ((r["basis"] == "reported") == reported) else None
            for r in rows], 2)

    rep, adj = leg(True), leg(False)
    rep_vals = [v for v in rep if v is not None]
    adj_vals = [v for v in adj if v is not None]
    return {
        "ref": "EX_Q_DEV",
        "kind": "grouped_bars",
        "title": (f"下季指引的偏离，按口径分开：报告口径 {len(rep_vals)} 季平均 "
                  f"{statistics.fmean(rep_vals):+.1f}%，调整后口径 {len(adj_vals)} 季平均 "
                  f"{statistics.fmean(adj_vals):+.1f}%"),
        "xlabels": labels,
        "xrot": 90,
        "groups": [
            {"name": "报告口径季度", "color": "GOLD", "values": rep},
            {"name": "调整后口径季度", "color": "NAVY", "values": adj},
        ],
        "bar_labels": False,
        "fmt": "pct1", "label_fmt": "pct1",
        "ylab": "% vs 指引中值",
        "note": (
            "同一家公司、同一段时间、同一份新闻稿里的同一句话，换个口径就换个分布。"
            "报告口径那 7 个季度里有正有负，唯一一次跌破下限是 2021 年第二季 —— 那一季"
            "沙特海关评估与退出成本压低了 GAAP 每股收益，而当季<b>调整后</b>每股收益是 "
            "US$1.57，仍在指引区间之上。调整后口径那 12 个季度<b>没有一次落在区间之内</b>，"
            "全部高于上限。"),
        "src_extra": "偏离 = 实际 ÷ 指引中值 − 1；单点指引的中值即该点。",
    }


def currency_path(staging: dict) -> dict:
    """How far the dollar guidance moved in a year against the ex-currency one."""
    rows = []
    for record in staging["annual_guidance"]["records"]:
        vs = [v for v in record["vintages"]
              if v.get("adj_low") is not None and v.get("xfx_low") is not None]
        if len(vs) < 2:
            continue
        # FY2022's two rows sat on different bases -- the dollar band was the
        # group and the ex-currency band the pro forma (ex Russia and Ukraine)
        # -- so subtracting one from the other would compare two companies.
        if record["year"] == 2022:
            continue
        rows.append((
            record["year"],
            mid(vs[-1]["adj_low"], vs[-1]["adj_high"]) - mid(vs[0]["adj_low"], vs[0]["adj_high"]),
            mid(vs[-1]["xfx_low"], vs[-1]["xfx_high"]) - mid(vs[0]["xfx_low"], vs[0]["xfx_high"]),
        ))
    labels = [f"FY{y}" for y, _, _ in rows]
    return {
        "ref": "EX_FX",
        "kind": "grouped_bars",
        "title": ("年内指引移动了多少：美元口径与剔除汇率口径，"
                  f"{labels[0]}–{labels[-1]} 共 {len(labels)} 年"
                  "（FY2022 两行口径不可比，不在图上）"),
        "xlabels": labels,
        "groups": [
            {"name": "调整后 EPS 指引中值移动（美元口径）", "color": "BLUE",
             "values": rounded([d for _, d, _ in rows], 3)},
            {"name": "同一指引剔除汇率后的移动", "color": "NAVY",
             "values": rounded([x for _, _, x in rows], 3)},
        ],
        "bar_labels": True,
        "fmt": "usd2", "label_fmt": "usd2",
        "ylab": "US$/股（年末指引中值 − 年初指引中值）",
        "note": (
            "两条腿都是公司自己在同一张预测表里印出来的行：Adjusted Diluted EPS 与 "
            "Adjusted Diluted EPS, excluding currency，中间隔着一行 Less Currency。"
            "<b>它们经常朝相反方向走</b>：FY2024 剔除汇率的指引一年抬了 US$0.39，美元口径只抬了 "
            "US$0.10，差额被汇率吃掉；FY2026 到目前为止剔除汇率的区间三次发布<b>逐字未动</b>"
            "（US$8.11–8.26），而美元口径的中值降了 US$0.12。"
            "这解释了 PMI 新闻稿标题里反复出现的那句「仅因汇率调整全年预测」—— "
            "它不是修辞，是这张表里可以逐分核对的算术。"
            "FY2022 不在图上：那三期的美元行是集团口径而剔除汇率行是剔除俄乌的 pro forma 口径，"
            "相减等于把两家公司相减。"),
        "src_extra": "各年第一次与最后一次业绩 8-K EX-99.1 全年预测表的两行中值之差。",
    }


# ── section two: what moved this quarter ───────────────────────────────────


def revenue_bridge(staging: dict) -> dict:
    bridge = staging["revenue_bridge"]
    latest = bridge["2026Q2"]
    columns = ["PMI 合计", "国际无烟", "国际组合烟草", "美国"]
    return {
        "ref": "EX_BRIDGE",
        "kind": "grouped_bars",
        "title": (f"本季净收入增量 US${latest['end'][0] - latest['base'][0]:,.0f}M 的来源："
                  f"价格 US${latest['price'][0]:,.0f}M、汇率 US${latest['currency'][0]:,.0f}M、"
                  f"量与结构 US${latest['volume_mix_other'][0]:,.0f}M"),
        "xlabels": columns,
        "groups": [
            {"name": "价格", "color": "NAVY", "values": rounded(latest["price"])},
            {"name": "量、结构与其他", "color": "BLUE", "values": rounded(latest["volume_mix_other"])},
            {"name": "收购与处置", "color": "GRAY", "values": rounded(latest["acq_div"])},
            {"name": "汇率", "color": "GOLD", "values": rounded(latest["currency"])},
        ],
        "bar_labels": True,
        "fmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M（vs Q2 2025）",
        "note": (
            "这是公司自己印的分解，四段相加等于本季与去年同期的差额，误差不超过四舍五入的 "
            "US$1M。<b>三个分部的形状完全不同</b>：国际无烟的增量主要来自量与结构，"
            "国际组合烟草几乎全部来自价格而量与结构是负的，美国两项都是负的、只靠一点点价格"
            "和汇率托住。把集团那一列单独读，会把「涨价 + 汇率」读成「增长」。"
            f"上一季（Q1 2026）同一张表里量与结构对集团是 "
            f"US${bridge['2026Q1']['volume_mix_other'][0]:,.0f}M，本季转正。"),
        "src_extra": "2026 年第二季度业绩 8-K EX-99.1「Second-Quarter 2026 Operating Review」净收入表。",
    }


def segment_revenue(staging: dict) -> dict:
    seg = staging["segments"]
    rev = seg["net_revenues_usd_m"]
    return {
        "ref": "EX_SEG_REV",
        "kind": "grouped_bars",
        "title": (f"三个报告分部的净收入：国际组合烟草仍是最大一块（本季 "
                  f"US${rev['international_combustibles'][-1]:,.0f}M），"
                  f"美国是唯一同比下降的（US${rev['us'][-1]:,.0f}M）"),
        "xlabels": seg["period_labels"],
        "groups": [{"name": SEG_NAMES[k], "color": SEG_COLORS[k], "values": rounded(rev[k])}
                   for k in SEG_KEYS],
        "bar_labels": True,
        "fmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M",
        "note": (
            "<b>只有四个季度，而且不会再多。</b>PMI 自 2026 年第一季度起把六个地理分部改成"
            "这三个，历史没有按新口径重述到申报里；图上的两个 2025 季度是 2026 年那两份新闻稿"
            "各自印出的上年对照列，除此之外没有第三个可用的季度。本页因此不把这条线接到它"
            "取代的六个地理分部上 —— 那会是把两套口径画成一条。三个分部相加等于合并净收入，"
            "四个季度逐季核对无差。"),
        "src_extra": "2026 年第一、二季度业绩 8-K EX-99.1 的经营回顾表与同期 10-Q 分部附注。",
    }


def segment_margin(staging: dict) -> dict:
    seg = staging["segments"]
    gm = seg["adjusted_gross_margin_pct"]
    us_gap = gm["us"][-1] - gm["us"][1]
    return {
        "ref": "EX_SEG_GM",
        "kind": "lines",
        "title": (f"分部调整后毛利率：国际无烟 {gm['international_smoke_free'][-1]:.1f}%，"
                  f"美国 {gm['us'][-1]:.1f}%，同比 {us_gap:+.1f}pp"),
        "xlabels": seg["period_labels"],
        "series": (
            [{"name": "PMI 合计", "values": rounded(gm["pmi"]), "color": "GRAY"}]
            + [{"name": SEG_NAMES[k], "values": rounded(gm[k]), "color": SEG_COLORS[k]}
               for k in SEG_KEYS]),
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
        "ylab": "调整后毛利率 %",
        "note": (
            "<b>这是本季真正的张力，也是集团数字看不出来的那一层。</b>"
            "集团调整后毛利率同比还在抬，国际无烟与国际组合烟草两条都在抬，"
            f"只有美国一条在塌：Q1 2026 同比 −14.7pp，Q2 2026 同比 {us_gap:+.1f}pp。"
            "公司给的原因是产能扩张带来的制造成本、品牌与渠道投入，以及 Wellness 的确认节奏。"
            "所以「毛利率在改善」和「美国单位经济性在恶化」这两句话同时为真，"
            "而后者是估值的边际变量。"
            "上年同期的百分比是当期表里印出的百分点变化倒推的（68.1 − 0.6 = 67.5），"
            "是公司自己的算术，不是本页的估计。"),
        "src_extra": "2026 年第一、二季度业绩 8-K EX-99.1 经营回顾的毛利表；上年同期由同表印出的 pp 变化倒推。",
    }


def zyn_offtake(staging: dict) -> dict:
    zyn = staging["zyn"]
    values = zyn["offtake_yoy_pct"]
    known = [v for v in values if v is not None]
    return {
        "ref": "EX_ZYN",
        "kind": "bars_labeled",
        "title": (f"美国 ZYN 零售出货同比（公司引用的 Nielsen 口径）：从 {known[1]:.0f}% "
                  f"降到 {known[-1]:.0f}%，最后一格公司只给了措辞"),
        "xlabels": zyn["period_labels"],
        "values": rounded(values),
        "fmt": "pct1", "label_fmt": "pct1",
        "ylab": "同比 %",
        "annot": f"Q2 2026：公司口径为「{zyn['offtake_latest_words']}」，无数字",
        "note": (
            "<b>最后一格是空的，不是零。</b>公司在本季新闻稿里把美国 ZYN 的零售出货描述为"
            f"「{zyn['offtake_latest_words']}」，没有给百分比，所以这里留空而不是填 0 —— "
            "填 0 会把一句措辞变成一个可以进模型的数。"
            "出货量（发给渠道）与零售出货（卖给消费者）在这段时间里差得很远，"
            "因为渠道库存先补后去。公司披露的出货口径依次是："
            + "；".join(f"{label} {words}"
                          for label, words in zip(zyn["period_labels"],
                                                  zyn["shipment_words"])) + "。"
            "两条口径里，判断需求要看后者。"),
        "src_extra": "各季业绩 8-K EX-99.1 正文；Nielsen 为公司引用的第三方零售监测口径。",
    }


# ── section four: the long routine series ──────────────────────────────────


def smoke_free_transition(staging: dict) -> dict:
    annual = staging["annual"]
    years = annual["years"]
    share = annual["smoke_free_share_pct"]
    return {
        "ref": "EX_SF",
        "kind": "stacked_dual",
        "title": (f"无烟产品净收入占比：{years[0]} 年 {share[0]:.1f}% → "
                  f"{years[-1]} 年 {share[-1]:.1f}%"),
        "xlabels": [f"FY{y}" for y in years],
        "stacks": [
            {"name": "组合烟草产品", "color": "GRAY", "values": rounded(annual["combustible_usd_m"])},
            {"name": "无烟产品", "color": "NAVY", "values": rounded(annual["smoke_free_usd_m"])},
        ],
        # `stacked_dual` is the one chart kind whose right axis does not read
        # the data: it draws `ticks(0, ex.line.ymax || 60, 6)`. This share is at
        # 41.5% and climbing about 4pp a year, so the undeclared default was
        # roughly four years from silently mis-scaling it. Declared, not left to
        # the default -- and note it belongs inside `line`, not at the top level,
        # where it is accepted and ignored.
        "line": {"name": "无烟产品占净收入 (RHS)", "color": "RED",
                 "values": rounded(share), "yfmt": "pct1", "ymax": 60},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M", "ylab2": "无烟占比",
        "note": (
            "<b>这条线是申报里的美元，不是新闻稿里的百分比。</b>PMI 在 10-K 的分部附注里"
            "按产品类别披露净收入的美元金额，本图逐年读的是那张表；两段相加等于合并净收入，"
            "十年里只有 2017 年差 US$1M，是各自四舍五入的结果。"
            "两个口径细节写在这里而不是抹掉：该行的名称从「reduced-risk products」改成"
            "「smoke-free products」，而 2020 与 2021 两年在 FY2022 的 10-K 里被重述过"
            "（Wellness and Healthcare 并入无烟口径），本图取较新的申报值。"
            "组合烟草的绝对金额十年几乎没动，无烟从 US$733M 长到 "
            f"US${annual['smoke_free_usd_m'][-1]:,.0f}M —— 转型是加出来的，不是替换出来的。"),
        "src_extra": "各年 Form 10-K 的 Segment Reporting 附注「Net revenues by product category」。",
    }


def revenue_series(staging: dict) -> dict:
    long = staging["long"]
    rev = long["net_revenues_usd_m"]
    return {
        "ref": "EX_REV",
        "kind": "bar_line",
        "title": (f"{len(rev)} 个季度的净收入与毛利率：本季 US${rev[-1]:,.0f}M、"
                  f"毛利率 {long['gross_margin_pct'][-1]:.1f}%"),
        "xlabels": long["period_labels"],
        "bar": {"name": "净收入", "values": rounded(rev), "color": "BLUE"},
        "line": {"name": "毛利率", "values": rounded(long["gross_margin_pct"]), "color": "RED",
                 "yfmt": "pct1"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M", "xstep": LONG_STEP,
        "note": (
            "<b>本页此前写着「序列从 2017 年开始，因为 PMI 2016 年之前按含消费税的口径报收入"
            "（2015 年 US$73.9B），2016 年起才改成净收入口径（同年 US$26.7B）」—— 那句话是错的。</b>"
            "PMI 的口径从来没变过：损益表上一直同时有含消费税的一行和扣除后的一行。"
            "73.9B 是 2015 年的<b>含税</b>数，26.7B 是 2016 年的<b>扣税</b>数 —— "
            "拿两个不同年份的两个不同口径相比，于是看见了一条并不存在的断崖。"
            "2015 年扣税后的净收入是 US$26.8B（73,908 − 47,114），与 2016 年的 26,685 同一量级。"
            "真正的坑在标签上：2016/2017 的申报里，损益表上标着「Net revenues」的那一行是 "
            "us-gaap:SalesRevenueNet，它是<b>含</b>消费税的；扣除后的口径直到 2018 年的 10-Q "
            "才有自己的 XBRL 标签。本站按「含税收入 − 消费税」计算，得到的 FY2016 = 26,685 "
            "与 FY2018 10-K 逐字重印的 FY2016 净收入相同。"
            "第四季没有 10-Q，其收入与毛利为全年减去前九个月，两条腿都是申报值；"
            "四个季度相加等于全年，逐年核对无差。"
            "季节性明显：每年第一季是低点，第二、三季是高点。"),
        "src_extra": "XBRL companyfacts 的季度与年度收入、毛利；第四季为年度减前九个月。",
    }


def margin_series(staging: dict) -> dict:
    long = staging["long"]
    gm, om = long["gross_margin_pct"], long["operating_margin_pct"]
    # Which quarters those troughs are is derived, not remembered: a first draft
    # of this caption named 2024Q4 from recall and it is not in the bottom four.
    # The operating-margin line has four holes at the front -- 2016's quarters
    # are on the pre-ASU-2017-07 basis and were never restated quarterly -- so
    # the ranking has to skip them rather than sort None against float.
    reported_om = [(value, label) for value, label
                   in zip(om, long["period_labels"]) if value is not None]
    deepest = sorted(reported_om)[:2]
    om_from = long["period_labels"][len(om) - len(reported_om)]
    return {
        "ref": "EX_MARGIN",
        "kind": "lines",
        "title": (f"毛利率与经营利润率：本季 {gm[-1]:.1f}% 与 {om[-1]:.1f}%，"
                  f"窗口内毛利率区间 {min(gm):.1f}–{max(gm):.1f}%"),
        "xlabels": long["period_labels"],
        "series": [
            {"name": "毛利率", "values": rounded(gm), "color": "NAVY"},
            {"name": "经营利润率（报告口径）", "values": rounded(om), "color": "BLUE"},
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
        "ylab": "%", "xstep": LONG_STEP,
        "note": (
            "<b>两条线的缺口比任何一条自己的水平更有信息。</b>毛利率的趋势向上 —— "
            f"窗口首季 {gm[0]:.1f}%、末季 {gm[-1]:.1f}%，是无烟产品占比上升的直接读数 —— "
            "但它不是单调的，季节性与地域结构每年都会把它拉回去。"
            "经营利润率则时不时被单季的减值、诉讼与重组砸出坑："
            f"窗口内最深的两个是 {deepest[0][1]} 的 {deepest[0][0]:.1f}% 与 "
            f"{deepest[1][1]} 的 {deepest[1][0]:.1f}%。"
            "这正是第一节里那条 GAAP 指引会踩空的地方：坑本身是真的，"
            "只是公司的全年预测从一开始就写明不含它们。"
            "经营利润率是报告口径，不是调整后口径。"
            f"<b>这条线的左端比毛利率短四格，那是洞不是缺数据。</b>"
            f"它从 {om_from} 起画。2016 四个季度的营业利润都读到了"
            "（2,473 / 2,753 / 2,977 / 2,612，两条独立路径逐格相同，"
            "四季加总 10,815 与年报恒等），但它们在 ASU 2017-07 之前的口径上："
            "养老金的非服务成本当时还在营业利润里。PMI 2018 年初追溯采用该准则，"
            "2017 四季因此各被上调 16–22 US$M，而**公司从未按季重述过 2016** —— "
            "重述后的 2016 只有一个年度数。把未重述的四季接在重述后的 2017 前面，"
            "接缝上会出现一个纯由准则变更产生的台阶，所以这四格留空。"
            "毛利率不受影响：2018 年的业绩发布把 2017 四季的净收入与销货成本逐字重印，"
            "两者一个数都没动。"),
        "src_extra": "XBRL companyfacts 的季度收入、毛利与经营利润；第四季为年度减前九个月。",
    }


def cash_series(staging: dict) -> dict:
    annual = staging["annual"]
    years = annual["years"]
    ocf = annual["operating_cash_flow_usd_m"]
    capex = annual["capex_usd_m"]
    intensity = [round(c / o * 100, 2) for c, o in zip(capex, ocf)]
    return {
        "ref": "EX_CASH",
        "kind": "bar_line_dual",
        "title": (f"经营现金流与资本开支：{years[-1]} 年 US${ocf[-1]:,.0f}M 对 "
                  f"US${capex[-1]:,.0f}M，资本开支只占 {intensity[-1]:.1f}%"),
        "xlabels": [f"FY{y}" for y in years],
        "bar": {"name": "经营现金流", "values": rounded(ocf), "color": "NAVY"},
        "line": {"name": "资本开支 ÷ 经营现金流 (RHS)", "values": rounded(intensity),
                 "color": "RED", "yfmt": "pct1"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M", "rhs_label": "资本开支占经营现金流 %",
        "note": (
            "<b>把这一页放在本站其他公司旁边，这张图是最大的反差。</b>"
            "核对抽屉里那张跨页对照表追的是四家云厂的现金资本开支，"
            "八个季度里它们合计增长了 2.8 倍；"
            f"PMI 十年里资本开支从没超过经营现金流的 {max(intensity):.1f}%，"
            f"本年是 {intensity[-1]:.1f}%。"
            "本季管理层说要在美国「加大投入」，而全年资本开支指引是 US$14–16 亿、"
            "相对上年 US$1,569M 是 −10.8% 到 +2.0% —— 也就是说这笔投入进的是销售与市场费用，"
            "不是资产负债表。这条判断下一季可以用同一张表证伪。"),
        "src_extra": "XBRL companyfacts 的年度经营现金流与购置不动产、厂房及设备支出。",
    }


# ── payload ────────────────────────────────────────────────────────────────


def build_payload(staging: dict) -> dict:
    fin = staging["financials"]
    labels = staging["period_labels"]
    long = staging["long"]
    seg = staging["segments"]
    annual = staging["annual"]

    rev = fin["net_revenues_usd_m"]
    adj_eps = fin["adjusted_diluted_eps_usd"]
    rep_eps = fin["reported_diluted_eps_usd"]

    banded, floors = annual_records(staging)
    fy_rows = [(r["actual_reported_eps"], r["last_guided"]["low"], r["last_guided"]["high"])
               for r in banded]
    fy_n, fy_above, fy_inside, fy_below = tally(fy_rows)

    q_rows = staging["quarterly_guidance"]
    q_adj = [(r["actual_eps"], r["low"], r["high"]) for r in q_rows if r["basis"] != "reported"]
    q_rep = [(r["actual_eps"], r["low"], r["high"]) for r in q_rows if r["basis"] == "reported"]
    qa_n, qa_above, qa_inside, qa_below = tally(q_adj)
    qr_n, qr_above, qr_inside, qr_below = tally(q_rep)

    settled = [
        annual_reported_band(staging),
        annual_deviation(staging),
        annual_adjusted_band(staging),
        currency_path(staging),
        quarter_band(staging),
        quarter_deviation(staging),
    ]
    highlights = [
        revenue_bridge(staging),
        segment_revenue(staging),
        segment_margin(staging),
        zyn_offtake(staging),
    ]

    kpi = staging["next_kpi"]["quantified"]
    next_block = [headroom_exhibit(
        f"下季 {len(kpi)} 条阈值：当前值离阈值的余量",
        kpi, "current",
        ("正值表示仍在安全侧。阈值多为本地研究设定，<b>不是公司指引</b> —— "
         "公司自己的下季指引只有一条，就是调整后摊薄每股收益 US$2.20–2.25，"
         f"已经画在第一节的 Exhibit {{EX_Q_BAND}} 上。"
         "唯一的例外是「集团有机收入增速」那条：5.0% 取的是公司全年有机收入指引"
         "区间的下限，属于公司披露值，其余五条都是本地设定。"
         + staging["next_kpi"]["excluded"]),
        "当前值为 2026 年第二季度披露值（ZYN 零售出货为 2026 年第一季度，见下）；阈值为本地研究设定。")]

    seg_gm = seg["adjusted_gross_margin_pct"]
    series_for = {
        "美国分部调整后毛利率": (seg_gm["us"], seg["period_labels"], "pct1", "%"),
        "国际无烟分部调整后毛利率": (seg_gm["international_smoke_free"], seg["period_labels"],
                                     "pct1", "%"),
        "集团调整后经营利润率": (seg["adjusted_oi_margin_pct"], seg["period_labels"], "pct1", "%"),
        "美国 ZYN 零售出货同比（Nielsen）": (staging["zyn"]["offtake_yoy_pct"],
                                             staging["zyn"]["period_labels"], "pct1", "%"),
    }
    for entry in kpi:
        if entry["metric"] not in series_for:
            continue
        values, xlab, fmt, unit = series_for[entry["metric"]]
        exhibit = threshold_exhibit(
            f"{entry['metric']}：当前 {entry['current']:.1f}{unit}，阈值 {entry['threshold']:.1f}{unit}",
            xlab, rounded(values), entry["threshold"],
            fmt=fmt, ylab=unit,
            actual_name=entry["metric"], threshold_name="本地阈值",
            note=("红线是本地研究设定的阈值，不是公司指引，也不是公司披露的目标。"
                  "序列从公司按现行口径开始披露该指标的那一季起画，不向前回补 —— "
                  "现行分部口径 2026 年第一季度才启用，本节前三条线因此只有四个季度。"),
            src_extra="2026 年各季业绩 8-K EX-99.1；阈值为本地研究设定。")
        if entry["metric"].startswith("美国 ZYN"):
            exhibit["note"] = (
                "红线是本地研究设定的阈值，不是公司指引。"
                "<b>最后一格没有点</b>：本季公司只用措辞描述这个指标，没有给数字，"
                "所以当前值取的是上一季的 10%，而不是把措辞折算成一个数。"
                "一个分辨率高于披露的阈值不能被结清 —— 本站在万事达页上退役过一条同样的阈值。")
        next_block.append(exhibit)

    routine = [
        smoke_free_transition(staging),
        revenue_series(staging),
        margin_series(staging),
        cash_series(staging),
    ]

    exhibits = number_exhibits(settled + highlights + next_block + routine)
    resolve_exhibit_refs(exhibits)
    n_settled, n_high, n_next = len(settled), len(highlights), len(next_block)
    settled_ex = exhibits[:n_settled]
    highlight_ex = exhibits[n_settled:n_settled + n_high]
    next_ex = exhibits[n_settled + n_high:n_settled + n_high + n_next]
    routine_ex = exhibits[n_settled + n_high + n_next:]

    first_table = exhibits[-1]["n"] + 1
    tables = []

    def verdict_text(actual, low, high):
        v = verdict_of(actual, low, high)
        return {"above": "高于上限", "inside": "区间内", "below": "跌破下限", None: "待披露"}[v]

    tables.append({
        "n": first_table,
        "title": "全年报告口径每股收益指引：年初、年末与实际（含只给下限的年份）",
        "headers": ["年度", "年初第一次指引", "当年最后一次指引", "全年实际", "对最后一次指引"],
        "rows": [[
            f"FY{r['year']}",
            (f"${r['first_guided']['low']:.2f}–{r['first_guided']['high']:.2f}"
             if r["first_guided"] and r["first_guided"].get("high")
             else (f"至少 ${r['first_guided']['low']:.2f}" if r["first_guided"] else "—")),
            (f"${r['last_guided']['low']:.2f}–{r['last_guided']['high']:.2f}"
             if r["last_guided"].get("high") else f"至少 ${r['last_guided']['low']:.2f}"),
            f"${r['actual_reported_eps']:.2f}" if r["actual_reported_eps"] is not None else "待披露",
            (verdict_text(r["actual_reported_eps"], r["last_guided"]["low"], r["last_guided"]["high"])
             if r["last_guided"].get("high") else
             ("高于下限" if r["actual_reported_eps"] is not None
              and r["actual_reported_eps"] >= r["last_guided"]["low"] else "跌破下限")),
        ] for r in sorted(banded + floors, key=lambda r: r["year"])],
    })
    adj_actual = staging["annual_guidance"]["annual_adjusted_eps_actual"]
    adj_rows = []
    for record in staging["annual_guidance"]["records"]:
        vs = [v for v in record["vintages"] if v.get("adj_low") is not None]
        if not vs:
            continue
        last, actual = vs[-1], adj_actual.get(str(record["year"]))
        adj_rows.append([
            f"FY{record['year']}",
            f"${vs[0]['adj_low']:.2f}–{vs[0]['adj_high']:.2f}",
            f"${last['adj_low']:.2f}–{last['adj_high']:.2f}",
            f"${actual:.2f}" if actual is not None else "待披露",
            verdict_text(actual, last["adj_low"], last["adj_high"]),
        ])
    tables.append({
        "n": first_table + 1,
        "title": "全年调整后每股收益指引：同一批年份、同一份新闻稿、另一个口径",
        # FY2020 has only one adjusted vintage (the October release), so the
        # first column is "the first release that carried this basis", not
        # "the February release" the reported-EPS table above it can promise.
        "headers": ["年度", "首次给出该口径的指引", "当年最后一次指引", "全年实际",
                    "对最后一次指引"],
        "rows": adj_rows,
    })
    tables.append({
        "n": first_table + 2,
        "title": "下季每股收益指引与随后实际（按各自当期口径）",
        "headers": ["被指引季度", "指引发布日", "口径", "指引", "实际", "结果"],
        "rows": [[
            r["period_label"], r["release_date"],
            {"reported": "报告", "adjusted": "调整后",
             "pro_forma_adjusted": "调整后（剔除俄乌）"}[r["basis"]],
            (f"${r['low']:.2f}（单点）" if r["point"] else f"${r['low']:.2f}–{r['high']:.2f}"),
            f"${r['actual_eps']:.2f}" if r["actual_eps"] is not None else "待披露",
            verdict_text(r["actual_eps"], r["low"], r["high"]),
        ] for r in q_rows],
    })
    tables.append({
        "n": first_table + 3,
        "title": "近八季合并损益与每股收益（公司披露值）",
        "headers": ["期间", "净收入", "毛利", "经营利润", "毛利率", "经营利润率",
                    "报告口径摊薄 EPS", "调整后摊薄 EPS"],
        "rows": [[
            labels[i], f"${rev[i]:,.0f}M", f"${fin['gross_profit_usd_m'][i]:,.0f}M",
            f"${fin['operating_income_usd_m'][i]:,.0f}M",
            f"{fin['gross_margin_pct'][i]:.1f}%", f"{fin['operating_margin_pct'][i]:.1f}%",
            f"${rep_eps[i]:.2f}", f"${adj_eps[i]:.2f}",
        ] for i in range(len(labels))],
    })
    tables.append(threshold_table(first_table + 4, "下季阈值与当前值（原始单位）",
                                  kpi, "current", "当前值"))
    tables.append(ai_capex_cycle_table(first_table + 5))

    us_gm = seg_gm["us"]
    return {
        "schema_version": "quarterly-dashboard/pm-v1",
        "page": {"slug": "pm", "language": "zh-CN"},
        "company": {
            "ticker": "PM",
            "name": "Philip Morris International",
            "group": "consumer_staples",
            "accounting_standard": "US GAAP",
        },
        "latest": {
            "disclosed_period_label": "Q2 2026",
            "full_financial_period_label": "Q2 2026",
            "period_end": "2026-06-30",
            "release_date": "2026-07-22",
            "analysis_date": "2026-08-29",
            "audit_status": "unaudited",
            "status": "history_ready",
        },
        "tracker": "Watchlist Quarterly Tracker · PM",
        "title": "Philip Morris International (PM)：Q2 2026 季报仪表盘",
        "subtitle": ("截至 2026-06-30 · 发布 2026-07-22 · US GAAP · 未审计 · "
                     "自然年财年，季度标注与财年一致"),
        "headline": (
            f"净收入 US${rev[-1]:,.0f}M、同比 {signed(pct_change(rev[-1], rev[-5]))}，"
            f"调整后摊薄每股收益 US${adj_eps[-1]:.2f} 高于公司自己给的 US$2.02–2.07；"
            f"但报告口径每股收益 US${rep_eps[-1]:.2f} 同比下降，"
            f"美国分部调整后毛利率 {us_gm[-1]:.1f}%、同比 {us_gm[-1] - us_gm[1]:+.1f}pp —— "
            "同一份新闻稿里，公司定义的那个数在兑现，GAAP 那个数在被一次性项目拿走。"),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>记录</span><b>同一年被指引两次，两条记录不一样</b>'
            f'<p>报告口径的全年指引，{fy_n} 个完整年度里 {fy_above} 年高于上限、{fy_inside} 年'
            f'落在区间内、{fy_below} 年跌破下限；换成公司自定义的调整后口径，下季指引 '
            f'{qa_n} 季<b>全部</b>高于上限。</p></article>'
            '<article><span>亮点</span><b>增量从「价格＋汇率」变成「价格＋正的量与结构」</b>'
            f'<p>本季净收入增量里价格 US$689M、汇率 US$299M，量与结构 US$81M —— '
            f'上一季这一项是 −US$206M。</p></article>'
            '<article><span>代价</span><b>美国分部的单位经济性还在恶化</b>'
            f'<p>调整后毛利率 {us_gm[-1]:.1f}%，同比 {us_gm[-1] - us_gm[1]:+.1f}pp；'
            f'ZYN 零售出货从 39% 一路降到公司只肯用措辞描述。</p></article>'
            '</div>'),
        "source": ('Source: <a href="https://www.sec.gov/Archives/edgar/data/1413329/'
                   '000162828026049107/earningsreleasepm-ex991xq2.htm" rel="noopener">'
                   'PMI 2026 年第二季度业绩新闻稿（8-K EX-99.1）</a>'
                   '与截至 2026-06-30 的 Form 10-Q。'),
        "source_url": ("https://www.sec.gov/Archives/edgar/data/1413329/"
                       "000162828026049107/earningsreleasepm-ex991xq2.htm"),
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": {
            "title": "公司指引（2026-07-22 业绩新闻稿全年预测表与假设段，公司披露值）",
            "headers": ["指标", "本期指引", "上一期指引（2026-04-22）", "变动"],
            "rows": [
                ["2026 年第三季度调整后摊薄 EPS", "$2.20 – $2.25",
                 "—（上一期只给第二季 $2.02 – $2.07）", "新季度对象，含约 8 美分不利汇率"],
                ["2026 全年报告口径摊薄 EPS", "$7.19 – $7.34", "$7.56 – $7.71", "下调 $0.37"],
                ["2026 全年调整后摊薄 EPS", "$8.26 – $8.41", "$8.36 – $8.51", "下调 $0.10"],
                ["2026 全年调整后摊薄 EPS（剔除汇率）", "$8.11 – $8.26", "$8.11 – $8.26", "逐字未变"],
                ["全年有机收入增速", "+5% ~ +7%", "+5% ~ +7%", "重申"],
                ["全年有机经营利润增速", "+7% ~ +9%", "+7% ~ +9%", "重申"],
                ["全年卷烟出货量", "−2% ~ −3%", "约 −3%", "上调"],
                ["全年经营现金流 / 资本开支", "约 $13.5B / $1.4 – $1.6B", "同上", "重申"],
                ["资本回报", "无回购；持续提高股息；目标年底杠杆接近 2.0×", "同上", "重申"],
            ],
            "note": ("公司在同一张预测表里并列报告口径与调整后口径，中间逐项列出调整。"
                     "本期报告口径下调 $0.37、调整后下调 $0.10，而「剔除汇率的区间三次发布逐字未变」"
                     "（$8.11–8.26）—— 公司自己的标题就写「仅因汇率更新全年调整后 EPS 预测」。"
                     "下季指引只覆盖第三季：PMI 从不指引第四季，2020 年第四季那次单点是唯一例外。"),
        },
        "sections": [
            {"id": "settled", "title": "一、公司自己的指引兑现了吗",
             "description": (
                 "PMI 把同一个盈利数字指引两次 —— 一次是全年，一次是下一个季度 —— 而且中途"
                 "把被指引的口径从 GAAP 换成了公司自定义的调整后口径。四条记录因此互相矛盾，"
                 "这一节把它们并排结清，并说明矛盾来自哪里。"),
             "exhibits": settled_ex},
            {"id": "quarter_highlights", "title": "二、本季重点",
             "description": ("增量的来源、三个报告分部的分化，以及美国单位经济性这条"
                             "决定估值边际的线。"),
             "exhibits": highlight_ex},
            {"id": "next_quarter", "title": "三、下季要跟踪什么",
             "description": "当前值离下季阈值还有多远，统一用「距阈值余量」口径；不接入的四条也写在这里。",
             "exhibits": next_ex},
            {"id": "routine", "title": "四、长期常规跟踪",
             "description": ("PMI 专属的常规序列：十年无烟转型的美元金额、38 个季度的收入与"
                             "两条利润率，以及一家现金强、资本轻的公司的现金结构。"),
             "exhibits": routine_ex},
        ],
        "tables": tables,
        "notes": [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "PMI 财年即自然年，本页季度标注与公司自己的口径一致，无需换算。",
            "第一节结清的是「两个层级、两种口径」的指引记录，这是本站唯一一家同时具备的公司。"
            "全年指引自 2008 年分拆起在每一份季度业绩新闻稿里发布并逐季修订，本页收录 2009–2026 共 "
            f"{len(staging['annual_guidance']['records'])} 个年度、70 次发布；下季指引自 2020 年第二季度"
            "起发布，共 20 次。",
            "FY2008 不在记录内：公司 2008 年 3 月才分拆，当年的预测是按 pro forma「调整后」口径"
            "对 2007 年 pro forma 基数给出的（新闻稿原文如此），拿它对报告口径的实际值结清是口径错误"
            "而不是一次落空。",
            "FY2019 与 FY2020 年初的指引是「至少 US$X」这样「只有下限」的形式，没有上限可以穿出，"
            "所以不进区间图，只进核对表。2020 年 4 月 21 日公司因新冠「撤回」全年指引并改为按季度"
            "指引，同年 7 月恢复全年指引 —— 这是记录里唯一一次撤回。",
            "2008 年 4 月到 2022 年 2 月的 56 份新闻稿里，有 54 份给全年预测时附同一句排除条款："
            "不含未来并购、未预料到的资产减值与退出成本、以及任何异常事件（例外是 2008-10-22 "
            "和 2020-04-21 那份撤回全年指引的）。2022 年第二季起公司改用「报告口径 + 逐项"
            "列名的调整 + 调整后口径」的预测表，排除项因此从一句概括变成了逐项计价。本页把两个时期"
            "画在同一张图上，但在图注里说明这条差别 —— 它正是报告口径那条记录会踩空的原因。",
            "下季指引的口径在记录中期发生变化：2020 年第二季至 2023 年第一季为「报告」每股收益，"
            "2023 年第二季起为「调整后」每股收益，2022 年第二、三季两格另为剔除俄罗斯与乌克兰的 "
            "pro forma 调整后口径。实际值一律按指引当期的同一口径取，不跨口径比较；图上有结构断点标记。",
            "第四季度没有 10-Q，所以本页季度序列里的第四季收入、毛利与经营利润为全年申报值减去前九个月"
            "申报值，两条腿都是申报数字；每股收益不可加总，第四季读自当期新闻稿的 EPS 调节表。"
            "四季相加等于全年，2024 与 2025 两年逐项核对无差。",
            "长期季度序列自 2017 年第一季度起，不向前回补：PMI 在 2016 年之前按含消费税的口径报收入，"
            "2016 年起改为净收入口径，两段不是一条线。",
            "分部序列只有四个季度，也不会更长：公司自 2026 年第一季度起把六个地理分部改为国际无烟、"
            "国际组合烟草与美国三个报告分部，历史未按新口径重述进申报。图上那两个 2025 季度是 2026 年"
            "两份新闻稿各自印出的上年对照列。",
            "无烟产品收入占比取自各年 10-K 分部附注里按产品类别的「美元」金额，不是新闻稿里的整数"
            "百分比。该行的名称在 2019 年前后从 reduced-risk products 改为 smoke-free products，"
            "2020 与 2021 两年在 FY2022 的 10-K 里被重述（Wellness and Healthcare 并入无烟口径），"
            "本页取较新的申报值。",
            "本页不发布市场一致预期：没有可核对的、带日期的公开来源。本页同样不发布评级、目标价与估值。",
            "本页只发布公司披露值、可复算的简单派生值；D 标记代表 Derived / 自算。",
            "核对抽屉最后那张「AI capex 循环」是全站共用的跨页对照块，在每一页都逐字节相同，不是对 PM 的判断。"
            "它追的是四家云厂现金资本开支 → NVDA 数据中心收入 → TSM 晶圆这条链，PMI 不在这条链的任何一环上。"
            "把它放在这里是为了让读者在任意一页都能查到同一份上下游对照。它在折叠的抽屉里，不参与本页的论证。",
            "本页已知未接入：ZYN 美国零售价值份额与净债务 / 调整后 EBITDA（前者只在电话会上给出、"
            "后者的分母是公司只按年披露的自定义口径）、ZYN Ultra 的净增量与自我蚕食（公司明确拒绝量化）、"
            "季度自由现金流（第二季 10-Q 在新闻稿两天后才提交，本页现金流序列只到年度层面），"
            "以及 2026 年 7 月 22 日申报之后的任何数据。",
            "业绩电话会文字稿仅链接官方 IR 与 SEC 托管版本，公开仓不复制原件或逐字内容。",
        ],
        "footer": "PM quarterly results · 数据来自 PMI 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "pm.js"), payload, "pm")
    shell_dir = ROOT / "pm"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("PM", "pm"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"PM page: {charts} charts in {len(payload['sections'])} sections "
          f"+ {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
