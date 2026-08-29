"""Nasdaq, Inc. quarterly dashboard.

Nasdaq guides **two numbers and no others**: full-year non-GAAP operating expense
and the full-year non-GAAP effective tax rate. It has never published revenue
guidance, EPS guidance or margin guidance, and it says so in a footnote to the
guidance section of every release. So the object this page's first section
settles is not a forecast of the business -- it is the company's own budget.

That changes what a hit rate means. Over eleven finished years the full-year
non-GAAP operating expense landed inside the year's LAST guidance range 7 times
and above it 4 times, and **not once below it**: the floor of the expense band
has never bound. Over seven finished years the non-GAAP effective tax rate landed
inside 5 times and below twice, and **not once above**. The two numbers the
company controls each miss in one direction only, and in opposite directions.

Against the year's FIRST (January) range the expense record is a different
object: 5 inside, 3 above, 3 below. The mean absolute distance from the guided
midpoint runs 2.84% in January against 0.97% in October, and the range itself
narrows from US$60M wide to US$22M. Most of what looks like discipline in the
October record is the ten months already banked when it is published.

Three of the four "above" verdicts have an explanation the page carries rather
than smooths: FY2022 clears the top by exactly US$1M, FY2023's final range was
set two weeks before the Adenza acquisition closed, and FY2020's overshoot was
pre-announced in a separate 8-K twelve days after the guided year had already
ended. Two of the three "below vs January" verdicts are divestitures, not thrift.

Published numbers are company-reported or transparent arithmetic. No market
expectation is published on this page: no dated, checkable public source for one
was available, and inventing one is worse than omitting the comparison.
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


STAGING_PATH = ROOT / "series" / "ndaq.json"
DATA_DIR = ROOT / "data"

# One tick per year keeps the forty-six-quarter axes readable.
LONG_STEP = 4


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100.0


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def rounded(values, digits: int = 6):
    return [None if v is None else round(v, digits) for v in values]


def mid(low: float, high: float) -> float:
    return (low + high) / 2


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


def finished_years(item: dict) -> list[int]:
    return [year for year in item["years"] if item["by_year"][str(year)]["actual"] is not None]


def vintages(item: dict, year: int) -> tuple[list, list]:
    block = item["by_year"][str(year)]
    guided = [g for g in block["guided"] if g]
    return guided[0], guided[-1]


def tally(item: dict, which: int) -> dict[str, int]:
    counts = {"inside": 0, "above": 0, "below": 0}
    for year in finished_years(item):
        low, high, _ = vintages(item, year)[which]
        actual = item["by_year"][str(year)]["actual"]
        counts["inside" if low <= actual <= high
               else ("above" if actual > high else "below")] += 1
    return counts


def annual_deviation(ref: str, metric: str, years: list[str], first: list[tuple],
                     last: list[tuple], actual: list[float], *, unit: str,
                     src_extra: str, extra_note: str = "") -> dict:
    """Distance from each of the two guided midpoints, for an ANNUAL record.

    ``board.midpoint_deviation`` hard-codes 「季」 into every sentence it builds,
    so an annual series renders as "11 季里 8 季为正". This is its annual twin and
    it draws both vintages side by side, because the whole finding is that the
    two answers differ: the January range is a forecast and the October one is
    largely bookkeeping on a year three-quarters banked.
    """
    dev_first = [(a / mid(lo, hi) - 1) * 100 for (lo, hi, _), a in zip(first, actual)]
    dev_last = [(a / mid(lo, hi) - 1) * 100 for (lo, hi, _), a in zip(last, actual)]
    mean_first = statistics.fmean(abs(v) for v in dev_first)
    mean_last = statistics.fmean(abs(v) for v in dev_last)
    biggest = max(dev_first, key=abs)
    return {
        "ref": ref,
        "kind": "grouped_bars",
        "title": (f"{metric}相对指引中值的偏离：对年初那次平均绝对偏离 {mean_first:.2f}%，"
                  f"对年末那次 {mean_last:.2f}%"),
        "xlabels": list(years),
        "groups": [
            {"name": "vs 年初第一次指引中值", "color": "GOLD", "values": rounded(dev_first)},
            {"name": "vs 当年最后一次指引中值", "color": "NAVY", "values": rounded(dev_last)},
        ],
        "bar_labels": True,
        "fmt": "pct1",
        "label_fmt": "pct1",
        "ylab": f"% vs 指引中值（{unit}）",
        "note": ("正值 = 实际值高于指引区间的中值。"
                 "<b>两组柱子的高度差就是这一年里指引被修订的幅度</b>：金色是年初那次、"
                 "深蓝是年末那次，年末那次总是更贴近实际，因为它发布时全年已过去约十个月。"
                 f"金色柱里最大的一次是 {years[dev_first.index(biggest)]} 的 {biggest:+.2f}%。"
                 + extra_note),
        "src_extra": src_extra,
    }


def guidance_section(staging: dict) -> tuple[list[dict], list[dict]]:
    """The annual guidance record: expense and tax rate, two vintages each."""
    hist = staging["annual_guidance_history"]
    charts: list[dict] = []
    tables: list[dict] = []

    opex = hist["operating_expense"]
    years = finished_years(opex)
    labels = [f"FY{y}" for y in years]
    first = [vintages(opex, y)[0] for y in years]
    last = [vintages(opex, y)[1] for y in years]
    actual = [opex["by_year"][str(y)]["actual"] for y in years]
    t_last, t_first = tally(opex, 1), tally(opex, 0)

    charts.append(delivery_band(
        "EX_OPEX_LAST", "全年非 GAAP 营业费用", labels,
        [g[0] for g in last], [g[1] for g in last], actual,
        fmt="f0c", ylab="US$M", unit="US$M",
        venue="业绩新闻稿", timing="该年<b>当年内最后一次</b>", period_word="年",
        extra_note=(
            f"<b>{len(years)} 个完整年度里没有一年低于下限</b> —— 落在区间内 "
            f"{t_last['inside']} 次、高于上限 {t_last['above']} 次、低于下限 "
            f"{t_last['below']} 次。费用指引的下限从来没有约束过这家公司："
            "它要么花在区间内，要么花得更多，但从未比自己说的少花。"
            "这条记录的分量要打折：这里画的是<b>当年最后一次</b>指引，通常发布于 10 月下旬，"
            "此时全年已过去约十个月，更接近记账而不是预测；"
            f"同一指标对<b>年初第一次</b>指引的结果完全不同，见 Exhibit {{EX_OPEX_FIRST}}。"
            "四次「高于上限」里有三次另有说法："
            "FY2022 只超出上限 US$1M，落在百万美元级四舍五入之内；"
            "FY2023 的最后一次指引发布于 2023-10-18，而 Adenza 收购在两周后的 11 月 1 日才交割，"
            "实际值含两个月 Adenza 费用，超出的 US$25M 与之量级相当；"
            "FY2020 的超支由公司在 2021-01-12 一份单独的 8-K 里提前披露，"
            "而那已是被指引年度结束后第 12 天。"),
        src_extra=("指引取自各年业绩 8-K EX-99.1 的费用指引段落；"
                   "实际值取自次年 Q4 业绩新闻稿非 GAAP 营业费用调节表的 Year Ended 列。"),
    ))
    charts.append(delivery_band(
        "EX_OPEX_FIRST", "全年非 GAAP 营业费用（对年初第一次指引）", labels,
        [g[0] for g in first], [g[1] for g in first], actual,
        fmt="f0c", ylab="US$M", unit="US$M",
        venue="业绩新闻稿", timing="该年<b>年初第一次</b>", period_word="年",
        extra_note=(
            f"<b>换成年初那次指引，同样 {len(years)} 年就成了双向的</b>：区间内 "
            f"{t_first['inside']} 次、高于上限 {t_first['above']} 次、低于下限 "
            f"{t_first['below']} 次。这才是十二个月视角下的记录。"
            "三次「低于下限」里有两次不是省钱而是缩表："
            "FY2018 的年初指引明确包含整年约 US$170M 的 Public Relations Solutions 与 "
            "Digital Media Services 费用，该业务当年 4 月出售，指引随即下调 US$80M；"
            "FY2019 的年初指引下调则是因为 BWise 出售。把它们读成「指引保守」是错的。"
            "FY2015 与 FY2016 每年只有两次指引（公司在这两年的第二、三季度没有发布费用指引），"
            "所以这两年的「第一次」与「最后一次」相隔只有一个季度。"),
        src_extra=("年初第一次指引取自各年 1 月的业绩 8-K EX-99.1；"
                   "FY2015 与 FY2016 的最后一次分别为当年 4 月发布。"),
    ))
    charts.append(annual_deviation(
        "EX_OPEX_DEV", "全年非 GAAP 营业费用", labels, first, last, actual,
        unit="US$M",
        src_extra="偏离 = 实际值 ÷ 指引中值 − 1；两组柱分别取该年第一次与最后一次指引区间的中点。",
        extra_note=(
            "同一段记录还可以从区间宽度上读："
            f"年初那次的平均宽度是 US${statistics.fmean(g[1] - g[0] for g in first):.0f}M，"
            f"年末那次是 US${statistics.fmean(g[1] - g[0] for g in last):.0f}M。"
            "指引在一年里既向实际值靠拢，也把自己收窄，两件事一起发生。"),
    ))

    tax = hist["tax_rate"]
    tax_years = finished_years(tax)
    tax_labels = [f"FY{y}" for y in tax_years]
    tax_first = [vintages(tax, y)[0] for y in tax_years]
    tax_last = [vintages(tax, y)[1] for y in tax_years]
    tax_actual = [tax["by_year"][str(y)]["actual"] for y in tax_years]
    tt = tally(tax, 1)
    on_floor = sum(1 for (lo, _hi, _d), a in zip(tax_last, tax_actual) if abs(a - lo) < 0.05)
    charts.append(delivery_band(
        "EX_TAX", "全年非 GAAP 有效税率", tax_labels,
        [g[0] for g in tax_last], [g[1] for g in tax_last], tax_actual,
        fmt="pct1", ylab="%", unit="%",
        venue="业绩新闻稿", timing="该年<b>当年内最后一次</b>", period_word="年",
        extra_note=(
            f"<b>这是另一条单边记录，而且方向相反</b>：{len(tax_years)} 个完整年度里区间内 "
            f"{tt['inside']} 次、低于下限 {tt['below']} 次、"
            f"高于上限 {tt['above']} 次。税率从未高于公司自己说的上限。"
            f"而且 {on_floor} 次「区间内」其实正落在区间的<b>下沿</b>上（FY2019、FY2020 报 26.0%，"
            "指引下限就是 26.0%；FY2022 报 24.0%，下限就是 24.0%），"
            "所以说「落在区间内」比说「贴着下限」要宽容得多。"
            "税率指引自 2018 年 1 月那期新闻稿才开始发布，FY2018 全年只发布过一次、"
            "且当年没有可用的实际值（公司披露非 GAAP 有效税率是从 FY2019 起），因此本图从 FY2019 起算。"),
        src_extra=("指引取自各年业绩 8-K EX-99.1；实际值为公司在 10-K 「NON-GAAP FINANCIAL MEASURES」"
                   "一节印出的 Non-GAAP effective tax rate，业绩新闻稿从不印这个数。"),
    ))

    open_year = str(max(opex["years"]))
    open_block = opex["by_year"][open_year]
    open_guided = [g for g in open_block["guided"] if g]
    moves = [(g[2], mid(g[0], g[1])) for g in open_guided]
    charts.append({
        "ref": "EX_FY26",
        "kind": "grouped_bars",
        "title": (f"FY{open_year} 费用指引的三次发布：中值从 US${moves[0][1]:,.0f}M 抬到 "
                  f"US${moves[-1][1]:,.0f}M，{signed(pct_change(moves[-1][1], moves[0][1]))}"),
        "xlabels": [date for date, _ in moves],
        "groups": [
            {"name": "指引区间下限", "color": "BLUE", "values": [g[0] for g in open_guided]},
            {"name": "指引区间中值", "color": "NAVY", "values": [round(m, 1) for _, m in moves]},
            {"name": "指引区间上限", "color": "GOLD", "values": [g[1] for g in open_guided]},
        ],
        "bar_labels": True,
        "fmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M",
        "note": (
            f"<b>FY{open_year} 是唯一还没结清的年度，三次发布都在往上走。</b>"
            f"区间宽度同时从 US${open_guided[0][1] - open_guided[0][0]:,.0f}M 收到 "
            f"US${open_guided[-1][1] - open_guided[-1][0]:,.0f}M —— 抬中值与收区间同时发生，"
            "和前十一年每一年的形状一样。"
            f"上半年已发生的非 GAAP 营业费用是 US${_h1(staging):,.0f}M，"
            f"按最新指引上限倒推，下半年还剩 US${open_guided[-1][1] - _h1(staging):,.0f}M 的额度，"
            f"折合每季 US${(open_guided[-1][1] - _h1(staging)) / 2:,.1f}M。"
            f"这一年怎么结清，要等 {int(open_year) + 1} 年 1 月那期新闻稿，届时会并入 "
            "Exhibit {EX_OPEX_LAST}。"),
        "src_extra": (f"三次发布：{'、'.join(date for date, _ in moves)} 的业绩 8-K EX-99.1；"
                      "中值为本页自算（D）。"),
    })

    def verdict(low, high, actual):
        return "区间内" if low <= actual <= high else ("高于上限" if actual > high else "低于下限")

    tables.append({
        "title": "全年非 GAAP 营业费用：年初指引、年末指引与实际（US$M）",
        "headers": ["年度", "指引次数", "年初第一次", "当年最后一次", "全年实际",
                    "对年初", "对最后一次"],
        "rows": [[f"FY{y}", str(len([g for g in opex['by_year'][str(y)]['guided'] if g])),
                  f"${f[0]:,.0f}–{f[1]:,.0f}",
                  f"${l[0]:,.0f}–{l[1]:,.0f}",
                  f"${a:,.0f}",
                  verdict(f[0], f[1], a), verdict(l[0], l[1], a)]
                 for y, f, l, a in zip(years, first, last, actual)]
        + [[f"FY{open_year}", str(len(open_guided)),
            f"${open_guided[0][0]:,.0f}–{open_guided[0][1]:,.0f}",
            f"${open_guided[-1][0]:,.0f}–{open_guided[-1][1]:,.0f}",
            "未完结", "—", "—"]],
    })
    tables.append({
        "title": "全年非 GAAP 有效税率：指引与实际（%）",
        "headers": ["年度", "年初第一次", "当年最后一次", "全年实际", "对最后一次"],
        "rows": [[f"FY{y}", f"{f[0]:.1f}–{f[1]:.1f}%", f"{l[0]:.1f}–{l[1]:.1f}%",
                  f"{a:.1f}%", verdict(l[0], l[1], a)]
                 for y, f, l, a in zip(tax_years, tax_first, tax_last, tax_actual)],
    })
    return charts, tables


def _h1(staging: dict) -> float:
    """Non-GAAP operating expense already spent in the open year, US$M."""
    fin = staging["financials"]
    periods = staging["periods"]
    year = periods[-1][:4]
    return sum(v for p, v in zip(periods, fin["nongaap_opex"]) if p.startswith(year))


def _on_segment_window(staging: dict, key: str) -> list[float]:
    """A `long` series cut to the segment window, so one chart has one basis."""
    lng = staging["long"]
    index = {q: i for i, q in enumerate(lng["quarters"])}
    return [abs(lng[key][index[q]]) for q in staging["segments"]["quarters"]]


def _seg_rebates(staging: dict) -> list[float]:
    return _on_segment_window(staging, "rebates")


def _seg_bcef(staging: dict) -> list[float]:
    return _on_segment_window(staging, "bcef")


def _aum_on_segment_window(staging: dict) -> list[float]:
    aum = staging["etp_aum"]
    index = {q: i for i, q in enumerate(aum["quarters"])}
    return [aum["period_end_usd_b"][index[q]] for q in staging["segments"]["quarters"]]


def _retained_capture(staging: dict) -> list[float]:
    """Rebates as a share of gross trading revenue with the SEC fee taken out.

    The headline pass-through ratio moves whenever the Section 31 rate moves,
    which is a regulator's decision and not a fact about the business. Netting
    the fee out of both legs leaves the part volume and pricing actually drive.
    """
    seg = staging["segments"]
    rebates, bcef = _seg_rebates(staging), _seg_bcef(staging)
    return [100.0 * r / (g - b) for r, b, g in zip(rebates, bcef, seg["ms_gross"])]


def quarter_section(staging: dict) -> list[dict]:
    """What moved this quarter, and the pass-through the gross line hides."""
    s31 = staging["section_31"]
    seg = staging["segments"]
    lng = staging["long"]
    fin = staging["financials"]
    aum = staging["etp_aum"]
    arr = staging["arr"]

    share = [100.0 * f / b if b else None
             for f, b in zip(s31["fees_usd_m"], s31["bcef_usd_m"])]
    charts = [{
        "ref": "EX_S31",
        "kind": "stacked_dual",
        "title": (f"「经纪、清算与交易所费用」拆开看：本季 SEC Section 31 规费 "
                  f"US${s31['fees_usd_m'][-1]:,.0f}M，上一季是 US$0M"),
        "xlabels": s31["period_labels"],
        "stacks": [
            {"name": "SEC Section 31 规费（代收代付）", "color": "NAVY",
             "values": rounded(s31["fees_usd_m"]), "label": True, "label_color": "WHITE"},
            {"name": "其余经纪与清算费用", "color": "GOLD",
             "values": rounded(s31["residual_usd_m"])},
        ],
        "line": {"name": "Section 31 占该行的比重 (RHS)", "color": "RED",
                 "values": rounded(share), "yfmt": "pct1", "ymax": 100},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M", "ylab2": "Section 31 占比",
        "note": (
            "<b>这条支出行几乎全部不是纳斯达克的成本，而是它替 SEC 收的一笔税。</b>"
            "10-Q 的原话是：Section 31 规费同时计入收入与交易性支出，"
            "「由于计入收入的金额等于计入 Section 31 规费的金额，对我们的净收入没有影响」。"
            f"把它剥掉之后剩下的真实经纪与清算费用，18 个季度里始终在 US$"
            f"{min(s31['residual_usd_m']):.0f}M–US${max(s31['residual_usd_m']):.0f}M 之间，"
            "几乎是一条直线。"
            f"而规费本身在同一窗口里从 US$0M 走到 US${max(s31['fees_usd_m']):,.0f}M："
            "2025Q3 至 2026Q1 连续三个季度为零，本季又回到 US$"
            f"{s31['fees_usd_m'][-1]:,.0f}M。费率由 SEC 定，不由公司定。"),
        "src_extra": ("Section 31 规费逐季数值取自各期 10-Q / 10-K 的 MD&A 表格"
                      "（U.S. Equity Derivative Trading 与 Cash Equity Trading 两块相加）；"
                      "该行总额取自各季业绩 8-K EX-99.1 的合并损益表；"
                      "其余经纪与清算费用为两者之差（D）。各年第四季由 10-K 全年数减前三季得到。"),
    }, {
        "ref": "EX_GROSSNET",
        "kind": "stacked_dual",
        "title": (f"Market Services 毛收入的去向：本季毛 US${seg['ms_gross'][-1]:,.0f}M，"
                  f"留在公司的净收入 US${seg['ms_net'][-1]:,.0f}M（{100 * seg['ms_net'][-1] / seg['ms_gross'][-1]:.1f}%）"),
        "xlabels": seg["period_labels"],
        "stacks": [
            {"name": "交易返点（付给流动性提供方）", "color": "BLUE",
             "values": rounded(_seg_rebates(staging))},
            {"name": "经纪、清算与交易所费用（近全部为 SEC 规费）", "color": "GOLD",
             "values": rounded(_seg_bcef(staging))},
            {"name": "Market Services 净收入", "color": "NAVY",
             "values": rounded(seg["ms_net"])},
        ],
        "line": {"name": "返点 ÷（毛收入 − 规费）(RHS)", "color": "RED",
                 "yfmt": "pct1", "ymax": 100,
                 "values": rounded(_retained_capture(staging))},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M", "ylab2": "返点占比",
        "note": (
            "<b>交易所毛收入线里，只有约四分之一留在公司。</b>"
            "三段自下而上是付给做市商与流动性提供方的返点、上一张图那笔 SEC 规费，"
            "以及公司真正留下的净收入。"
            "<b>窗口只画 2022Q4 之后的 15 个季度，是因为再往前不是同一个口径</b>："
            "2022 年那次重组把不产生交易性支出的 Trade Management Services 移出了 Market Services，"
            "分母因此变窄 —— 同一个 2022Q3，旧口径净收入 US$305M、新口径 US$245M，"
            "拿旧口径的比例和新口径连成一条线，会把一次重分类读成过路成本的上升。"
            "红线是剥掉规费之后的返点占比，规费的开关动不了它："
            f"15 个季度里它从 {_retained_capture(staging)[0]:.1f}% 走到 "
            f"{max(v for v in _retained_capture(staging)):.1f}% 的高点，本季 "
            f"{_retained_capture(staging)[-1]:.1f}%。这条线才是量与价的真实变化。"),
        "src_extra": ("毛收入、返点与经纪清算费均取自各季 EX-99.1 合并损益表与 Revenue Detail 表；"
                      "三段相加等于毛收入，15 个季度逐季核对无差。红线为本页自算（D）。"),
    }, {
        "ref": "EX_SEG",
        "kind": "grouped_bars",
        "title": (f"三个分部的净收入：Capital Access US${seg['cap'][-1]:,.0f}M、"
                  f"Financial Technology US${seg['fin'][-1]:,.0f}M、"
                  f"Market Services 净 US${seg['ms_net'][-1]:,.0f}M"),
        "xlabels": seg["period_labels"],
        "groups": [
            {"name": "Capital Access Platforms", "color": "NAVY", "values": rounded(seg["cap"])},
            {"name": "Financial Technology", "color": "BLUE", "values": rounded(seg["fin"])},
            {"name": "Market Services（净）", "color": "GOLD", "values": rounded(seg["ms_net"])},
            {"name": "Other", "color": "RED", "values": rounded(seg["other"])},
        ],
        "fmt": "f0c", "label_fmt": "f0c", "ylab": "US$M",
        "note": (
            "四条相加等于合并净收入，15 个季度逐季核对无差。"
            "<b>窗口从 2022Q4 起，不向前回补</b>：这套三分部结构是 2023 年那次重组的产物，"
            "在此之前公司先后用过 Market Services / Listing Services / Information Services / "
            "Technology Solutions、Market Services / Corporate Services / Information Services / "
            "Market Technology、以及 Market Platforms / Capital Access Platforms / "
            "Anti-Financial Crime 三套完全不同的分部口径，各季的分部数不可直接相接。"
            f"本季三条腿同比分别为 {signed(pct_change(seg['cap'][-1], seg['cap'][-5]))}、"
            f"{signed(pct_change(seg['fin'][-1], seg['fin'][-5]))}、"
            f"{signed(pct_change(seg['ms_net'][-1], seg['ms_net'][-5]))}。"),
        "src_extra": ("各季业绩 8-K EX-99.1 的 Revenue Detail 表。"
                      "每个季度的四条腿取自<b>同一份</b>新闻稿：分季取各自最早出现的那份，"
                      "会把重组前后的两套口径拼在一起，加总比净收入少 US$9M。"),
    }, {
        "ref": "EX_FINSUB",
        "kind": "grouped_bars",
        "title": (f"Financial Technology 的三条子线：Capital Markets Tech "
                  f"US${seg['fin_cmt'][-1]:,.0f}M、Regulatory Tech US${seg['fin_reg'][-1]:,.0f}M、"
                  f"Financial Crime Management US${seg['fin_fcmt'][-1]:,.0f}M"),
        "xlabels": seg["period_labels"],
        "groups": [
            {"name": "Capital Markets Technology", "color": "NAVY", "values": rounded(seg["fin_cmt"])},
            {"name": "Regulatory Technology", "color": "BLUE", "values": rounded(seg["fin_reg"])},
            {"name": "Financial Crime Management Technology", "color": "GOLD",
             "values": rounded(seg["fin_fcmt"])},
        ],
        "fmt": "f0c", "label_fmt": "f0c", "ylab": "US$M",
        "break_at": seg["quarters"].index("2023Q4"),
        "break_label": "Adenza 交割（2023-11-01）",
        "note": (
            "<b>2023Q4 那道竖线是收购，不是增长。</b>Adenza 于 2023-11-01 交割，"
            "AxiomSL 并入 Regulatory Technology、Calypso 并入 Capital Markets Technology，"
            "两条线因此分别从 US$35M、US$145M 一步跳到 US$110M、US$229M；"
            "该季只含两个月的被收购业务，下一季才是完整季度。"
            "跨这道线比较同比增速没有意义，本页也不这样比。"
            f"2024Q1 之后三条线都是内生的：本季分别同比 "
            f"{signed(pct_change(seg['fin_cmt'][-1], seg['fin_cmt'][-5]))}、"
            f"{signed(pct_change(seg['fin_reg'][-1], seg['fin_reg'][-5]))}、"
            f"{signed(pct_change(seg['fin_fcmt'][-1], seg['fin_fcmt'][-5]))}。"),
        "src_extra": ("各季 EX-99.1 的 Revenue Detail 表。"
                      "Financial Crime Management Technology 是 2024 年 4 月那期新闻稿才从 "
                      "Regulatory Technology 里单列出来的，并回溯重述了 2023 各季；"
                      "2022Q4 没有这条子线，图上留空不补。"),
    }, {
        "ref": "EX_INDEX",
        "kind": "bar_line",
        "title": (f"Index：挂钩纳斯达克指数的 ETP AUM 期末 US${aum['period_end_usd_b'][-1]:,.0f}B "
                  f"首次站上一万亿，Index 收入同比 "
                  f"{signed(pct_change(seg['cap_index'][-1], seg['cap_index'][-5]))}"),
        "xlabels": seg["period_labels"],
        "bar": {"name": "期末 ETP AUM", "values": rounded(_aum_on_segment_window(staging)),
                "color": "BLUE"},
        "line": {"name": "Index 分部收入（US$M，RHS）", "color": "RED", "yfmt": "f0c",
                 "values": rounded(seg["cap_index"])},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$B", "ylab2": "Index 收入 US$M",
        "note": (
            "<b>标题里那个 +38.3% 是报告口径，公司自己给的调整后口径是 +35%</b> —— "
            "差额是本季 Index 业务一笔合同修改带来的一次性收入，公司在新闻稿脚注里"
            "把它从调整后同比中剔除，但没有披露金额。两个数都印在这里，因为只引报告值会高估这条腿的斜率。"
            "<b>本页不把这两条线相除。</b>Index 分部收入除了挂钩 AUM 的 ETP 授权费，"
            "还包含指数期权与期货的授权收入 —— 公司本季自己说指数期权收入已连续四个季度同比翻倍 —— "
            "所以「收入 ÷ AUM」不是费率，印成基点会让读者以为那是一个可比的过路费。"
            "公司也从不披露这个费率。两条线各自看，差距的方向才是信息："
            f"窗口内 AUM 涨了 {_aum_on_segment_window(staging)[-1] / _aum_on_segment_window(staging)[0]:.1f} 倍，"
            f"Index 收入涨了 {seg['cap_index'][-1] / seg['cap_index'][0]:.1f} 倍。"
            "本图只画现行分部口径下的 15 个季度；AUM 自己的 43 季长序列见 Exhibit {EX_AUMLONG}。"),
        "src_extra": ("AUM 取自各季 EX-99.1 的 Key Drivers 表，Index 收入取自同一份新闻稿的 "
                      "Revenue Detail 表。窗口与分部图一致，因为 Index 这条收入线在 2018 年"
                      "第二季度的 Information Services 拆分中被重新划过一次，"
                      "更早的读数与现行口径不可直接相接。"),
    }, {
        "ref": "EX_ARR",
        "kind": "grouped_bars",
        "title": (f"ARR 两条腿：Financial Technology US${arr['arr_fin'][-1]:,.0f}M、同比 "
                  f"{signed(arr['fin_yoy_pct'][-1])}；"
                  f"Capital Access US${arr['arr_cap'][-1]:,.0f}M、同比 "
                  f"{signed(arr['cap_yoy_pct'][-1])}"),
        "xlabels": arr["period_labels"],
        "groups": [
            {"name": "Financial Technology ARR", "color": "NAVY", "values": rounded(arr["arr_fin"])},
            {"name": "Capital Access Platforms ARR", "color": "BLUE", "values": rounded(arr["arr_cap"])},
        ],
        "fmt": "f0c", "label_fmt": "f0c", "ylab": "US$M",
        "break_at": arr["quarters"].index("2023Q4"),
        "break_label": "Adenza 交割（2023-11-01）",
        "note": (
            f"两条相加是公司口径的总 ARR，本季 US${arr['arr_fin'][-1] + arr['arr_cap'][-1]:,.0f}M。"
            "<b>两条腿的增速差了一倍</b>，而订阅这件事对二者的含义并不相同："
            "Capital Access 那条主要是上市公司年费与数据订阅，随上市公司家数走；"
            "Financial Technology 那条是软件合同，随签约与交叉销售走。"
            "<b>标题里的同比取自同一份新闻稿里并排印出的两列，而不是本图两根柱子相除</b>："
            "公司在 2025 年 10 月卖掉 Solovis 并把它从 Capital Access 移入 Other、重述了可比期，"
            f"所以 2025Q2 的 Capital Access ARR 有两个值 —— 当期印的 US${arr['arr_cap'][-5]:,.0f}M 与"
            f"重述后的 US${arr['cap_prior_year_same_release'][-1]:,.0f}M。拿本季除以当期那个会得出 +5.6%，"
            f"而同口径是 {signed(arr['cap_yoy_pct'][-1])}，也正是公司自己在这份新闻稿里写的 8%。"
            "ARR 是合同的年化值而不是收入，公司自己也说它「不是预测」，"
            "与已确认收入之间没有恒等式，本页不把两者相除。"),
        "src_extra": ("各季 EX-99.1 的 Key Drivers 表；柱子为各季首次披露值，"
                      "同比为同一份新闻稿内当期与去年同期两列之比（D）。"
                      "2023 各季的 ARR 在当期新闻稿里按当时的分部口径印出，2024 年的新闻稿按现行口径重述过；"
                      "本页每季取<b>同一份</b>新闻稿里两条腿同时存在的那一版，"
                      "分季取最早出现的那版会把 Capital Access 的 ARR 画出一个 2.4 倍的假跳升。"),
    }]
    return charts


def next_section(staging: dict) -> list[dict]:
    kpi = staging["next_kpi"]["quantified"]
    lng = staging["long"]
    fin = staging["financials"]
    exhibits = [headroom_exhibit(
        f"下季 {len(kpi)} 条阈值：当前值离阈值的余量",
        kpi, "current",
        ("正值表示仍在安全侧。阈值为本地研究设定，<b>不是公司指引</b> —— "
         "纳斯达克只指引全年非 GAAP 营业费用与非 GAAP 有效税率两个数，"
         "从不指引收入、每股收益或利润率，见第一节。"
         + staging["next_kpi"]["excluded"]),
        "当前值为 2026Q2 披露值或本页自算；阈值为本地研究设定。")]

    exhibits.append(threshold_exhibit(
        "非 GAAP 经营利润率：当前 "
        f"{fin['nongaap_margin_pct'][-1]:.1f}%，阈值 55.0%",
        lng["period_labels"], rounded(lng["nongaap_margin_pct"]), 55.0,
        fmt="pct1", ylab="%",
        actual_name="非 GAAP 经营利润率", threshold_name="本地阈值",
        note=("红线是本地研究设定的阈值，不是公司指引 —— 公司从不指引利润率。"
              "46 个季度里这条线从 46.4% 走到 "
              f"{lng['nongaap_margin_pct'][-1]:.1f}%，几乎单调向上；"
              "分母是净收入（已扣除交易性支出），所以上一节那笔 SEC 规费的开关不影响它。"),
        src_extra="各季业绩 8-K EX-99.1 的非 GAAP 经营利润调节表；分母为净收入。"))
    exhibits[-1]["xstep"] = LONG_STEP

    aum = staging["etp_aum"]
    exhibits.append(threshold_exhibit(
        f"期末 ETP AUM：当前 US${aum['period_end_usd_b'][-1]:,.0f}B，阈值 US$1,000B",
        aum["period_labels"], rounded(aum["period_end_usd_b"]), 1000.0,
        fmt="f0c", ylab="US$B",
        actual_name="期末 ETP AUM", threshold_name="本地阈值",
        note=("红线是本地研究设定的阈值，不是公司指引 —— 公司从不指引 AUM。"
              "本季是这条序列首次站上一万亿美元，所以阈值设在整数关口上，"
              "问的是下一季会不会掉回去。它同时是市场涨跌的读数而不只是经营的读数："
              "公司自己披露的滚动十二个月数据里，增量中净增值大于净流入。"),
        src_extra="各季业绩 8-K EX-99.1 的 Key Drivers 表；公司披露值。"))
    exhibits[-1]["xstep"] = LONG_STEP
    return exhibits


def routine_section(staging: dict) -> list[dict]:
    lng = staging["long"]
    fin = staging["financials"]
    aum = staging["etp_aum"]
    gap = [None if None in (a, b) else a - b
           for a, b in zip(lng["nongaap_margin_pct"], lng["gaap_margin_pct"])]
    return [{
        "ref": "EX_MARGIN",
        "kind": "lines",
        "title": (f"46 季经营利润率：非 GAAP {lng['nongaap_margin_pct'][-1]:.1f}%、"
                  f"GAAP {lng['gaap_margin_pct'][-1]:.1f}%"),
        "xlabels": lng["period_labels"],
        "series": [
            {"name": "非 GAAP 经营利润率", "values": rounded(lng["nongaap_margin_pct"]), "color": "NAVY"},
            {"name": "GAAP 经营利润率", "values": rounded(lng["gaap_margin_pct"]), "color": "BLUE"},
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
        "ylab": "%", "xstep": LONG_STEP,
        "note": (
            "两条线的<b>缺口</b>就是被调整掉的成本 —— 主要是收购无形资产摊销，"
            f"其次是重组与并购费用。缺口在 46 个季度里从 {gap[0]:.1f}pp 走到 {gap[-1]:.1f}pp，"
            "2023Q4 Adenza 交割后明显走阔，因为摊销基数一次性变大。"
            "两条线的分母都是净收入。第一节结清的费用指引只针对非 GAAP 口径，"
            "公司在每份新闻稿里都写明不提供 GAAP 费用指引。"),
        "src_extra": "各季业绩 8-K EX-99.1；GAAP 利润率为经营利润 ÷ 净收入（D），与公司披露值一致。",
    }, {
        "ref": "EX_MIX",
        "kind": "lines",
        "title": (f"46 季净收入与 Market Services 净收入：后者占比 "
                  f"{100 * lng['ms_net'][-1] / lng['net_revenue'][-1]:.1f}%"),
        "xlabels": lng["period_labels"],
        "series": [
            {"name": "合并净收入", "values": rounded(lng["net_revenue"]), "color": "NAVY"},
            {"name": "Market Services 净收入", "values": rounded(lng["ms_net"]), "color": "BLUE"},
        ],
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c", "end_label": True,
        "ylab": "US$M", "xstep": LONG_STEP,
        "break_at": lng["quarters"].index("2022Q4"),
        "break_label": "Market Services 口径变窄（2022Q4）",
        "note": (
            "<b>这张图是这家公司十一年里最大的一次自我改写，但其中有一步不是业务变化。</b>"
            f"2015Q1 交易业务占净收入 {100 * lng['ms_net'][0] / lng['net_revenue'][0]:.1f}%，"
            f"本季 {100 * lng['ms_net'][-1] / lng['net_revenue'][-1]:.1f}%。"
            "这十四个百分点里，约 6.6pp 出现在 2022Q4 那一格：重组把 Trade Management Services "
            "移出了 Market Services，同一个季度的口径落差是 US$305M 对 US$245M，"
            "分母（合并净收入）不变。<b>剩下的约七到八个百分点才是业务本身的变化</b> —— "
            "合并净收入涨了近两倍，交易那条腿几乎原地踏步，差额来自上市与数据、指数，"
            "以及 2021 年之后靠 Verafin 与 Adenza 买进来的软件业务。"
            "合并净收入那条线不受这次重分类影响，跨全窗口连续。"),
        "src_extra": ("各季业绩 8-K EX-99.1 的合并损益表与 Revenue Detail 表，均为公司披露值。"
                      "口径落差由同一季度在重组前后两份新闻稿里的两个读数直接得到，非估算。"),
    }, {
        "ref": "EX_AUMLONG",
        "kind": "lines",
        "title": (f"43 季挂钩纳斯达克指数的 ETP AUM：US${aum['period_end_usd_b'][0]:,.0f}B → "
                  f"US${aum['period_end_usd_b'][-1]:,.0f}B"),
        "xlabels": aum["period_labels"],
        "series": [
            {"name": "期末 ETP AUM", "values": rounded(aum["period_end_usd_b"]), "color": "NAVY"},
            {"name": "当季平均 ETP AUM", "values": rounded(aum["average_usd_b"]), "color": "BLUE"},
        ],
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c", "end_label": True,
        "ylab": "US$B", "xstep": LONG_STEP,
        "note": (
            "期末值受季末一天的市场影响，平均值不受 —— 两条线拉开的地方就是季内的波动。"
            "<b>平均值序列自 2022Q4 才有披露，之前只有期末值，图上因此从那里开始，不向前回补。</b>"
            f"本季平均 US${aum['average_usd_b'][-1]:,.0f}B、期末 "
            f"US${aum['period_end_usd_b'][-1]:,.0f}B，两者都是有披露以来的最高。"),
        "src_extra": "各季业绩 8-K EX-99.1 的 Key Drivers 表；均为公司披露值。",
    }]


def build_payload(staging: dict) -> dict:
    fin = staging["financials"]
    seg = staging["segments"]
    lng = staging["long"]
    arr = staging["arr"]
    aum = staging["etp_aum"]
    labels = staging["period_labels"]
    hist = staging["annual_guidance_history"]

    settled, settled_tables = guidance_section(staging)
    highlights = quarter_section(staging)
    next_block = next_section(staging)
    routine = routine_section(staging)

    exhibits = number_exhibits(settled + highlights + next_block + routine)
    resolve_exhibit_refs(exhibits)
    n1, n2, n3 = len(settled), len(highlights), len(next_block)
    settled_ex = exhibits[:n1]
    highlight_ex = exhibits[n1:n1 + n2]
    next_ex = exhibits[n1 + n2:n1 + n2 + n3]
    routine_ex = exhibits[n1 + n2 + n3:]

    first_table = exhibits[-1]["n"] + 1
    tables = [{**t, "n": first_table + i} for i, t in enumerate(settled_tables)]
    tables.append({
        "n": first_table + len(settled_tables),
        "title": "近八季合并损益与交易性支出（公司披露值，US$M）",
        "headers": ["期间", "总收入", "交易返点", "经纪清算与交易所费用", "净收入",
                    "营业费用", "经营利润", "GAAP 利润率", "非 GAAP 营业费用",
                    "非 GAAP 利润率", "GAAP 摊薄 EPS", "非 GAAP 摊薄 EPS"],
        "rows": [[labels[i],
                  f"${fin['total_revenues'][i]:,.0f}",
                  f"−${abs(fin['rebates'][i]):,.0f}",
                  f"−${abs(fin['bcef'][i]):,.0f}",
                  f"${fin['net_revenue'][i]:,.0f}",
                  f"${fin['opex'][i]:,.0f}",
                  f"${fin['op_income'][i]:,.0f}",
                  f"{fin['gaap_margin_pct'][i]:.1f}%",
                  f"${fin['nongaap_opex'][i]:,.0f}",
                  f"{fin['nongaap_margin_pct'][i]:.1f}%",
                  f"${fin['diluted_eps'][i]:.2f}",
                  f"${fin['nongaap_eps'][i]:.2f}"]
                 for i in range(len(labels))],
    })
    tables.append({
        "n": first_table + len(settled_tables) + 1,
        "title": "Section 31 规费与它所在的支出行（US$M）",
        "headers": ["期间", "SEC Section 31 规费", "经纪清算与交易所费用合计",
                    "其余经纪与清算费用 D", "Section 31 占该行 D"],
        "rows": [[staging["section_31"]["period_labels"][i],
                  f"${staging['section_31']['fees_usd_m'][i]:,.0f}",
                  f"${staging['section_31']['bcef_usd_m'][i]:,.0f}",
                  f"${staging['section_31']['residual_usd_m'][i]:,.1f}",
                  f"{100 * staging['section_31']['fees_usd_m'][i] / staging['section_31']['bcef_usd_m'][i]:.1f}%"]
                 for i in range(len(staging["section_31"]["quarters"]))],
    })
    tables.append(threshold_table(first_table + len(settled_tables) + 2,
                                  "下季阈值与当前值（原始单位）",
                                  staging["next_kpi"]["quantified"], "current", "当前值"))
    tables.append(ai_capex_cycle_table(first_table + len(settled_tables) + 3))

    opex = hist["operating_expense"]
    t_last = tally(opex, 1)
    t_first = tally(opex, 0)
    tax_last = tally(hist["tax_rate"], 1)
    n_years = len(finished_years(opex))
    n_tax = len(finished_years(hist["tax_rate"]))

    return {
        "schema_version": "quarterly-dashboard/ndaq-v1",
        "page": {"slug": "ndaq", "language": "zh-CN"},
        "company": {
            "ticker": "NDAQ",
            "name": "Nasdaq, Inc.",
            "group": "financial_data_indices",
            "accounting_standard": "US GAAP",
        },
        "latest": {
            "disclosed_period_label": "Q2 2026",
            "full_financial_period_label": "Q2 2026",
            "period_end": "2026-06-30",
            "release_date": "2026-07-23",
            "analysis_date": "2026-08-29",
            "audit_status": "unaudited",
            "status": "history_ready",
        },
        "tracker": "Watchlist Quarterly Tracker · NDAQ",
        "title": "Nasdaq, Inc. (NDAQ)：Q2 2026 季报仪表盘",
        "subtitle": ("截至 2026-06-30 · 发布 2026-07-23 · US GAAP · 未审计 · "
                     "自然年财年，季度标注与财年一致"),
        "headline": (
            f"净收入 US${fin['net_revenue'][-1]:,.0f}M、同比 "
            f"{signed(pct_change(fin['net_revenue'][-1], fin['net_revenue'][-5]))}，"
            f"Index 收入同比 {signed(pct_change(seg['cap_index'][-1], seg['cap_index'][-5]))}、"
            f"挂钩指数的 ETP AUM 首次突破一万亿美元（期末 US${aum['period_end_usd_b'][-1]:,.0f}B）；"
            f"公司唯一给的两条指引都只关于自己的成本 —— {n_years} 个完整年度里全年非 GAAP 营业费用"
            f"没有一年低于指引下限，{n_tax} 个年度里非 GAAP 有效税率没有一年高于指引上限。"),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>记录</span><b>只指引成本，而且是单边的</b>'
            f'<p>{n_years} 年里全年非 GAAP 营业费用对当年最后一次指引 {t_last["inside"]} 次落在区间内、'
            f'{t_last["above"]} 次高于上限、{t_last["below"]} 次低于下限；换成年初那次是 '
            f'{t_first["inside"]}/{t_first["above"]}/{t_first["below"]}。'
            f'税率 {n_tax} 年里 {tax_last["above"]} 次高于上限。</p></article>'
            '<article><span>亮点</span><b>Index 与 FinTech 是加速的两条腿</b>'
            f'<p>Index 收入 US${seg["cap_index"][-1]:,.0f}M、同比 '
            f'{signed(pct_change(seg["cap_index"][-1], seg["cap_index"][-5]))}；'
            f'Financial Technology ARR US${arr["arr_fin"][-1]:,.0f}M、同比 '
            f'{signed(arr["fin_yoy_pct"][-1])}，'
            f'而 Capital Access ARR 只有 '
            f'{signed(arr["cap_yoy_pct"][-1])}。</p></article>'
            '<article><span>口径</span><b>毛收入里有一笔 SEC 规费</b>'
            f'<p>本季 Section 31 规费 US${staging["section_31"]["fees_usd_m"][-1]:,.0f}M，'
            f'前三个季度是 US$0M。它同时进收入与支出，对净收入没有影响；'
            f'毛收入同比 {signed(pct_change(seg["ms_gross"][-1], seg["ms_gross"][-5]))} 与净收入同比 '
            f'{signed(pct_change(seg["ms_net"][-1], seg["ms_net"][-5]))} 的差距几乎全在这里。</p></article>'
            '</div>'),
        "source": ('Source: <a href="https://www.sec.gov/Archives/edgar/data/1120193/'
                   '000112019326000011/earningsrelease2q26ex-991.htm" rel="noopener">'
                   'Nasdaq 2026 年第二季度业绩新闻稿（8-K EX-99.1）</a>'
                   '与截至 2026-06-30 的 10-Q。'),
        "source_url": ("https://www.sec.gov/Archives/edgar/data/1120193/"
                       "000112019326000011/earningsrelease2q26ex-991.htm"),
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {"id": "settled", "title": "一、公司自己的指引兑现了吗",
             "description": ("纳斯达克只指引两个数：全年非 GAAP 营业费用与全年非 GAAP 有效税率，"
                             "两者都是年度的，都在每季业绩新闻稿里更新一次。"
                             "它从不指引收入、每股收益或利润率，也从不提供任何 GAAP 口径的指引。"
                             "所以这一节结清的是公司自己的预算，不是它对业务的预测；"
                             "并且把「年初那次」与「当年最后一次」分开算，因为两者的答案不一样。"),
             "exhibits": settled_ex},
            {"id": "quarter_highlights", "title": "二、本季重点",
             "description": ("先把毛收入里那笔代收代付的 SEC 规费剥掉，再看三个分部与两条 ARR；"
                             "Index 与 Financial Technology 是本季加速的来源。"),
             "exhibits": highlight_ex},
            {"id": "next_quarter", "title": "三、下季要跟踪什么",
             "description": "当前值离下季阈值还有多远，统一用「距阈值余量」口径；不接入的几条也写在这里。",
             "exhibits": next_ex},
            {"id": "routine", "title": "四、长期常规跟踪",
             "description": ("纳斯达克专属的常规序列：46 季两条利润率与它们的调整缺口、"
                             "交易业务在净收入里退到三成以下的过程，以及指数资产十年十倍的曲线。"),
             "exhibits": routine_ex},
        ],
        "tables": tables,
        "notes": [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "纳斯达克财年即自然年，本页季度标注与公司自己的口径一致，无需换算。",
            "第一节结清的是年度指引而不是季度指引，而且只覆盖成本与税率：公司在每季业绩新闻稿里给出并更新一次全年非 GAAP 营业费用指引与全年非 GAAP 有效税率指引，从不指引收入、每股收益或利润率。每份新闻稿都用同一句脚注说明不提供 GAAP 口径的费用与税率指引，理由是外汇变动与非经常项目难以量化。本站其他公司页第一节结清的多是季度收入区间，本页不是，差别源于公司披露口径而非编辑选择。",
            "费用指引记录自 2015 年 1 月那期新闻稿起算，共 43 次发布、覆盖 FY2015 至 FY2026 十二个年度，其中十一个已完结。2015 与 2016 两年公司只在第一、二季度发布过费用指引，第三、四季度没有发布，因此这两年的「当年最后一次」是 4 月而不是 10 月；已逐份读过这四期新闻稿确认不是漏读。记录不向 2014 年之前延伸，是因为非 GAAP 营业费用的定义在 2015 年 4 月那期发生过变化（收购无形资产摊销自那时起才被列为非 GAAP 调整项），跨越该点的比较不同基准。",
            "税率指引自 2018 年 1 月那期新闻稿起才有，FY2018 全年只发布过一次且当年无可用实际值，因此税率图从 FY2019 起算，共七个完整年度。全年实际的非 GAAP 有效税率业绩新闻稿从不印，取自各年 10-K 的非 GAAP 财务指标一节；用新闻稿里的税前利润与税项调整独立复算的结果与之逐年相差不超过 0.04 个百分点。",
            "另有一次费用指引更新不在季度新闻稿里：2021-01-12 的一份 8-K 在披露 12 月成交量的同时，说明 2020 年非 GAAP 营业费用将「超出此前指引区间上限约 4,500 万美元」。该文件发布于被指引年度结束后第 12 天，且没有给出新的区间，因此不计入本页的指引 vintage；但它是理解 FY2020 那次超支的必要背景，实际值 US$1,414M 与它隐含的约 US$1,415M 相差 US$1M。",
            "FY2017 的全年实际值有两个版本：首次披露为 US$1,280M，2018 年采用 ASC 606 全面追溯法后重述为 US$1,271M。本页取首次披露值，因为 FY2017 的指引本身写在 ASC 606 之前的基准上，两者相比才是同口径；若改用重述值，该年对最后一次指引的判定会由「区间内」变为「低于下限」，十一年的记录随之变为 6 内 / 4 上 / 1 下。这是窗口内唯一一个实际值被重述过的年度。",
            "分部收入、ARR 与分部子线的每一个季度都取自同一份新闻稿。公司在 2023 与 2024 年两次重述过分部与子线口径，逐条按「该指标最早出现的那份新闻稿」取值会把重述前后的两套基准拼在一起：分部加总会比净收入少 US$9M，Capital Access 的 ARR 会画出一个 2.4 倍的假跳升。两处都已按同一份文件取值消除。",
            "Section 31 规费的逐季数值不在业绩新闻稿里，也没有 XBRL 标记、不在 R-file 中，只存在于 10-Q 与 10-K 的 MD&A 正文表格；本页逐份解析主文档取得，各年第四季由 10-K 的全年数减去前三季得到。与合并损益表里「经纪、清算与交易所费用」一行相减后的余额，18 个季度全部落在 US$4M 至 US$8M 之间，这一稳定性是该拆分成立的证据。",
            "ARR 的同比一律取自同一份新闻稿里并排印出的两列，不由本页的柱子相除。2025 年 10 月出售 Solovis 后公司把它从 Capital Access Platforms 移入 Other 并重述了可比期，因此 2025Q2 的 Capital Access ARR 有两个值（当期 1,315、重述后 1,286）；跨基准相除会把该分部的同比从 8% 读成 5.6%。公司在本季新闻稿里同时给出总 ARR 的两个增速，报告口径 11%、有机口径 12%，差别正是这次剥离：前者拿本季比去年当期印出的数，后者两端都在剥离后的口径上。本页图表标注有机口径可比的同一份读数。",
            "本页不发布 Index 分部收入除以 ETP AUM 得到的「基点费率」：Index 收入还包含指数期权与期货的授权收入，两者相除得到的不是过路费率，公司自己也从不披露这个数。同理不把 ARR 与已确认收入相除 —— ARR 是合同的年化值，公司明确说明它不是预测，与收入之间没有恒等式。",
            "每股收益序列跨越 2022 年 8 月的三比一拆股。本页近八季表格全部位于拆股之后，不受影响；长期序列不画每股收益，因此没有需要拼接的地方。",
            "合并净收入是本页唯一一条可以从 2015 年直接画到 2026 年的序列：46 个季度里公司始终把它定义为总收入减去交易返点与经纪清算费用这两项、且只有这两项，跨越四次分部重组数值都能对上。它在窗口内有一处未经说明的口径变动：2018 年 4 月采用 ASC 606 时公司重述了 2017 各季，全年由 US$2,428M 降为 US$2,411M，逐季幅度 US$2M 至 US$6M（不到 1%），新闻稿的收入表对此没有任何注释。本页长期序列取各季首次披露值，因此 2017 与 2018 之间存在这一处小台阶，图上未画断点标记，因为它小于线宽；在此写明。",
            "最新一期新闻稿（2026-07-23）由公司自行报送，HTML 结构与此前 47 期由代理机构报送的版本不同，纯文本化后会丢失表格行列。本页的所有数值均直接解析 HTML 表格并按印出的期间表头对列，不依赖文本转换，也不按列的位置取值。该期「经纪、清算与交易所费用」印出的三个月为 US$320M、六个月为 US$326M，看似矛盾，实际正确：2026 年第一季度的 Section 31 规费为零，该季只剩约 US$6M 的经纪清算费用，两者相加正是 US$326M。",
            "本页不发布市场一致预期：没有可核对的、带日期的公开来源，站点规则允许发布带日期的「市场预期」对照点，但不允许凭印象填一个数。本页同样不发布评级、目标价与估值。",
            "本页只发布公司披露值、可复算的简单派生值；D 标记代表 Derived / 自算。",
            "核对抽屉最后那张「AI capex 循环」是全站共用的跨页对照块，在每一页都逐字节相同，不是对 NDAQ 的判断。它追的是四家云厂现金资本开支 → NVDA 数据中心收入 → TSM 晶圆这条链，纳斯达克不在这条链的任何一环上。把它放在这里是为了让读者在任意一页都能查到同一份上下游对照。它在折叠的抽屉里，不参与本页的论证。",
            "本页已知未接入：公司在投资者日发布的中期分部有机增长目标（不在任何申报文件里）、2024 至 2025 年提到而 2026 三期新闻稿均未再提的「2027 年前交叉销售运行率收入超过 1 亿美元」目标、各交易所的市占率与行业成交量序列（同一标签在一份新闻稿里出现两次、分别属于期权与现货两块，按出现次序取值会静默取错，故不接入）、现金流与资本回报的逐季序列（业绩新闻稿不含现金流量表），以及 2026 年第三季度之后的任何数据（本页数据截至 2026-07-23 的申报）。",
            "业绩电话会文字稿仅链接官方 IR 与 SEC 托管版本，公开仓不复制原件或逐字内容。",
        ],
        "footer": "NDAQ quarterly results · 数据来自 Nasdaq 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "ndaq.js"), payload, "ndaq")
    shell_dir = ROOT / "ndaq"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("NDAQ", "ndaq"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"NDAQ page: {charts} charts in {len(payload['sections'])} sections "
          f"+ {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
