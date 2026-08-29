"""CME Group Inc. quarterly dashboard.

Three things about this filer decide what the page can be.

**It guides one number, and it is not the one the market models.** Every quarter
the sell side builds CME's cost line off a full-year "adjusted operating expense
excluding license fees" figure -- US$1,695M for 2026. That number is said out
loud on the earnings call and appears in **no** SEC filing: the four most recent
earnings releases, the last three 10-Qs and the FY2025 10-K were searched for it
line by line and it is not there. What *is* in a filing, once a year for
seventeen years running, is a single sentence in the 10-K's liquidity section:
"In 2026, we expect capital expenditures to total approximately $85.0 million."
So the first section settles capital expenditure, and the record it settles is
one-sided in the opposite direction from what a cost guidance usually shows --
over sixteen finished years the actual came in **below** the guidance eleven
times, above it four, inside its band once. Three of the four overshoots are
consecutive -- 2018, 2019 and 2020, the NEX integration and the data-centre
build -- and the fourth is 2024.

**Its revenue does not follow its volume one-for-one, and that is measurable
rather than asserted.** CME's fee schedule steps down as a client's monthly
volume rises, so a quiet quarter pushes contracts back into higher tiers and the
average rate per contract goes *up*. Over the 53 quarterly changes in this
window, total revenue moved 0.66% for every 1% move in contracts (R-squared
0.92), clearing and transaction fees 0.79%, and average rate per contract moved
against volume in 37 of 53 quarters. This quarter's own reading -- contracts
-16.3%, revenue -9.2% -- is that same mechanism, not a new fact about pricing.
The consequence is symmetric and it is the modelling error the page is built to
prevent: a high-volume quarter does not carry this quarter's US$0.678 rate.

**Its second income stream is a spread, not a rate bet.** CME reinvests cash
performance bonds and hands most of the interest back to clearing firms; what it
keeps is disclosed in the 10-Q as two prose figures, and dividing the difference
by the average collateral balance gives a retained spread that has sat between
25 and 36 basis points in every one of the eleven post-2022 quarters while the
gross yield on the same balance ran from 194 to 511 and back to 344. In 2021 the
same spread was 5 basis points. The balance is a period-end number and the page
says so: against the one daily average the company has ever quoted, this method
reads about 8% high on the balance and so about 8% low on the spread.

Published numbers are company-reported or transparent arithmetic. No market
expectation, rating, target price or valuation is published, and neither is the
call-only expense guidance -- see the note on what this page refuses to carry.
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


STAGING_PATH = ROOT / "series" / "cme.json"
DATA_DIR = ROOT / "data"

# One tick per year keeps the fifty-four-quarter axes readable.
LONG_STEP = 4

CLASSES = [
    ("rates", "利率", "NAVY"),
    ("equity", "股指", "MBLUE"),
    ("fx", "外汇", "BLUE"),
    ("energy", "能源", "GREEN"),
    ("ags", "农产品", "GOLD"),
    ("metals", "金属", "GRAY"),
]


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100.0


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def rounded(values, digits: int = 6):
    return [None if v is None else round(v, digits) for v in values]


def mid(low: float, high: float) -> float:
    return (low + high) / 2


def usd_m(value: float, digits: int = 1) -> str:
    """US$M with the minus outside the currency symbol, as `board` formats it."""
    return f"{'−' if value < 0 else ''}US${abs(value):,.{digits}f}M"


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


def slope_and_r2(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Least-squares slope of y on x, and the R-squared, both from the series.

    Published rather than described: the whole argument about the fee schedule
    is a claim about a slope, and a page that only asserts "revenue is less
    volatile than volume" cannot be checked against the data it ships.
    """
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    return sxy / sxx, sxy ** 2 / (sxx * syy)


def qoq(values: list[float]) -> list[float]:
    return [(values[i] / values[i - 1] - 1) * 100 for i in range(1, len(values))]


def finished_capex_years(capex: dict) -> list[str]:
    return [y for y in capex["years"] if capex["by_year"][y]["actual"] is not None]


def capex_tally(capex: dict) -> dict[str, int]:
    counts = {"inside": 0, "above": 0, "below": 0}
    for year in finished_capex_years(capex):
        block = capex["by_year"][year]
        actual = block["actual"]
        counts["inside" if block["low"] <= actual <= block["high"]
               else ("above" if actual > block["high"] else "below")] += 1
    return counts


# ── section one: the only guidance that lives in a filing ────────────────────

def capex_section(staging: dict) -> tuple[list[dict], list[dict]]:
    capex = staging["capex_guidance"]
    years = capex["years"]
    low = [capex["by_year"][y]["low"] for y in years]
    high = [capex["by_year"][y]["high"] for y in years]
    actual = [capex["by_year"][y]["actual"] for y in years]
    labels = [f"FY{y}" for y in years]
    ranges = [y for y in years if capex["by_year"][y]["form"] == "range"]
    tally = capex_tally(capex)
    finished = finished_capex_years(capex)

    band = delivery_band(
        "EX_CAPEX", "全年资本开支", labels, low, high, actual,
        fmt="f0c", ylab="US$M", unit="US$M",
        venue="10-K",
        timing="该年<b>开始后两个月内</b>",
        period_word="年",
        extra_note=(
            f"<b>{len(years) - len(ranges)} 个年度的指引是一个单点（「approximately $X million」），"
            f"只有 {'、'.join('FY' + y for y in ranges)} 这 {len(ranges)} 年给的是区间</b>，"
            "所以图上多数色块没有宽度 —— 这不是渲染问题，是公司的指引本来就没有宽度。"
            f"因此「落在区间内」这一档在 {len(finished)} 个已完结年度里只可能属于那三年，"
            f"实际也只发生过 {tally['inside']} 次（FY2012，实际 US$141.8M 落在 140–150 之间）。"),
        src_extra=("指引句逐年读自各年 10-K 的流动性与资本资源一节（例如 FY2026：「In 2026, we "
                   "expect capital expenditures to total approximately $85.0 million.」）；"
                   "实际值取各年 10-K 现金流量表的 Purchases of property 一行，"
                   "每个年度都在 2–3 份 10-K 的三年比较列里出现过，逐份核对无差异。"),
    )

    deviation = [(a / mid(lo, hi) - 1) * 100
                 for lo, hi, a in zip(low, high, actual) if a is not None]
    dev_labels = [f"FY{y}" for y in finished]
    over = [d for d in deviation if d > 0]
    mean_abs = statistics.fmean(abs(d) for d in deviation)
    biggest = max(deviation, key=abs)
    dev = {
        "ref": "EX_CAPEX_DEV",
        "kind": "grouped_bars",
        "title": (f"资本开支实际值相对指引中值的偏离：{len(deviation)} 年里 {len(over)} 年为正，"
                  f"平均绝对偏离 {mean_abs:.1f}%"),
        "xlabels": dev_labels,
        "xrot": 90,
        "groups": [{"name": "实际资本开支 vs 指引中值", "color": "BLUE",
                    "values": rounded(deviation)}],
        "bar_labels": True,
        "fmt": "pct0",
        "label_fmt": "pct0",
        "ylab": "% vs 指引中值",
        "note": (
            "<b>这张图说明的不是「指引准不准」，而是它一直往同一个方向不准。</b>"
            f"平均绝对偏离 {mean_abs:.1f}%，窗口内最大的一次是 "
            f"{dev_labels[deviation.index(biggest)]} 的 {biggest:+.0f}%。"
            "十六个年度里只有四年高于指引中值：连续的 FY2018、FY2019、FY2020 —— "
            "那三年正是 NEX 并购整合与自建数据中心同时在跑的三年 —— 以及 FY2024；"
            "其余十二年全部低于指引中值。<b>一个长期只往下偏的资本开支指引，"
            "对现金流模型的含义是上偏而不是中性</b> —— 但它的绝对量级很小，"
            f"FY2025 的 US${capex['by_year']['2025']['actual']:.1f}M 只相当于当年营业利润的个位数百分比，"
            "所以它值得看的地方在于口径本身，而不在于它对自由现金流的影响。"),
        "src_extra": "同 Exhibit {EX_CAPEX}；中值对单点指引即该点本身。",
    }

    table = {
        "n": 0,
        "title": "全年资本开支：10-K 指引 vs 现金流量表实际值（US$M）",
        "headers": ["年度", "指引形式", "指引", "实际", "相对中值 D", "判定 D", "指引出处"],
        "rows": [[
            f"FY{y}",
            "单点" if capex["by_year"][y]["form"] == "point" else "区间",
            (f"${capex['by_year'][y]['low']:,.1f}"
             if capex["by_year"][y]["form"] == "point"
             else f"${capex['by_year'][y]['low']:,.1f}–${capex['by_year'][y]['high']:,.1f}"),
            (f"${capex['by_year'][y]['actual']:,.1f}"
             if capex["by_year"][y]["actual"] is not None else "待披露"),
            (f"{(capex['by_year'][y]['actual'] / mid(capex['by_year'][y]['low'], capex['by_year'][y]['high']) - 1) * 100:+.1f}%"
             if capex["by_year"][y]["actual"] is not None else "—"),
            ("—" if capex["by_year"][y]["actual"] is None else
             ("区间内" if capex["by_year"][y]["low"] <= capex["by_year"][y]["actual"] <= capex["by_year"][y]["high"]
              else ("高于上限" if capex["by_year"][y]["actual"] > capex["by_year"][y]["high"] else "低于下限"))),
            f"{capex['by_year'][y]['source_filed']} 的 10-K",
        ] for y in years],
    }
    return [band, dev], [table]


# ── section two: this quarter ────────────────────────────────────────────────

def quarter_section(staging: dict) -> list[dict]:
    fin = staging["financials"]
    lng = staging["long"]
    labels = staging["period_labels"]
    coll = staging["collateral"]

    share = [100 * c / r for c, r in zip(fin["clearing_fees"], fin["total_revenues"])]
    mix = {
        "ref": "EX_MIX",
        "kind": "stacked_dual",
        "title": (f"近八季三条收入线：清算与交易费 US${fin['clearing_fees'][-1]:,.1f}M，"
                  f"占总收入 {share[-1]:.1f}%"),
        "xlabels": labels,
        "stacks": [
            {"name": "清算与交易费", "color": "NAVY", "values": rounded(fin["clearing_fees"])},
            {"name": "行情数据与信息服务", "color": "MBLUE", "values": rounded(fin["market_data"])},
            {"name": "其他收入", "color": "BLUE", "values": rounded(fin["other_revenue"])},
        ],
        # `stacked_dual` scales its right axis to `ticks(0, ymax || 60, 6)`,
        # not to the data. This share sits around 80%, so without a ymax the
        # line is drawn above the top of the canvas and vanishes silently.
        "line": {"name": "清算与交易费占比 (RHS)", "color": "GOLD",
                 "values": rounded(share), "yfmt": "pct1", "ymax": 100},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M", "rhs_label": "%",
        "note": (
            f"<b>本季总收入同比只增长 "
            f"{signed(pct_change(fin['total_revenues'][-1], fin['total_revenues'][-5]))}，"
            f"而这一点点增长全部来自最窄的那条腿。</b>"
            f"清算与交易费同比 {signed(pct_change(fin['clearing_fees'][-1], fin['clearing_fees'][-5]))}，"
            f"是窗口内第一次同比转负；行情数据同比 "
            f"{signed(pct_change(fin['market_data'][-1], fin['market_data'][-5]))}；"
            f"其他收入同比 {signed(pct_change(fin['other_revenue'][-1], fin['other_revenue'][-5]))}。"
            f"逐条相加：US${fin['market_data'][-1] - fin['market_data'][-5]:+,.1f}M 加上 "
            f"US${fin['other_revenue'][-1] - fin['other_revenue'][-5]:+,.1f}M，"
            f"再减去 US${abs(fin['clearing_fees'][-1] - fin['clearing_fees'][-5]):,.1f}M，"
            f"得到 US${fin['total_revenues'][-1] - fin['total_revenues'][-5]:+,.1f}M。"),
        "src_extra": "各季业绩新闻稿（8-K EX-99.1）的合并损益表；均为公司披露值。",
    }

    # The volume/price bridge, built from the company's own ADV, trading days
    # and RPC rather than from the reported fee line -- the two differ by the
    # cash and FX businesses, which have no published volume at all.
    prev_contracts = lng["contracts_m"][-2]
    contracts = lng["contracts_m"][-1]
    prev_rpc, this_rpc = lng["rpc"][-2], lng["rpc"][-1]
    volume_effect = (contracts - prev_contracts) * prev_rpc
    rate_effect = (this_rpc - prev_rpc) * contracts
    prev_fees, fees = lng["fo_clearing_fees"][-2], lng["fo_clearing_fees"][-1]
    bridge = {
        "ref": "EX_BRIDGE",
        "kind": "bridge_bar",
        "title": (f"期货与期权清算费环比 {usd_m(fees - prev_fees)}：量减 "
                  f"{usd_m(abs(volume_effect))}，费率回升补回 {usd_m(rate_effect)}"),
        "xlabels": [f"{labels[-2]} 期货与期权清算费", "成交合约数变动", "平均每手费率变动",
                    f"{labels[-1]} 期货与期权清算费"],
        "stacks": [{"name": "环比拆解", "color": "NAVY",
                    "values": rounded([prev_fees, volume_effect, rate_effect, None])}],
        "net": rounded([None, None, None, fees]),
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M",
        "note": (
            f"<b>合约数环比 {qoq(lng['contracts_m'])[-1]:+.1f}%，但这条费用线只跌了 "
            f"{qoq(lng['fo_clearing_fees'])[-1]:+.1f}% —— 差额就是分级费率。</b>"
            f"{labels[-2]} 成交 {prev_contracts:,.1f} 百万张、每手 ${prev_rpc:.3f}；"
            f"{labels[-1]} 成交 {contracts:,.1f} 百万张、每手 ${this_rpc:.3f}。"
            "量效应按上季费率计价，费率效应按本季成交量计价，两者相加与直接相减完全吻合。"
            "<b>费率不是被提上去的</b>：客户当月累计成交量越大、落进的费率档越低，"
            "所以量一少，同一批客户自动退回较高的档位。Exhibit {EX_ADV_LONG} 把这条机制"
            "放在五十四个季度上，Exhibit {EX_CLASS_RPC} 说明它在六个品种里同时发生。"),
        "src_extra": ("ADV、交易日与 RPC 均为业绩新闻稿披露值；"
                      "期货与期权清算费 = ADV × 交易日 × RPC，是公司口径的乘积 D，"
                      "与合并损益表的清算与交易费一行相差的部分见 Exhibit {EX_RESIDUAL}。"),
    }

    adv_qoq = [pct_change(lng[f"adv_{k}"][-1], lng[f"adv_{k}"][-2]) for k, _, _ in CLASSES]
    rpc_qoq = [pct_change(lng[f"rpc_{k}"][-1], lng[f"rpc_{k}"][-2]) for k, _, _ in CLASSES]
    class_rpc = {
        "ref": "EX_CLASS_RPC",
        "kind": "grouped_bars",
        "title": (f"六个品种的量与价同时反向：ADV 环比 {sum(1 for v in adv_qoq if v < 0)} 跌 "
                  f"{sum(1 for v in adv_qoq if v >= 0)} 涨，每手费率环比 "
                  f"{sum(1 for v in rpc_qoq if v > 0)} 个上升"),
        "xlabels": [name for _, name, _ in CLASSES],
        "groups": [
            {"name": "ADV 环比", "color": "NAVY", "values": rounded(adv_qoq)},
            {"name": "每手费率 RPC 环比", "color": "GOLD", "values": rounded(rpc_qoq)},
        ],
        "bar_labels": True,
        "fmt": "pct1", "label_fmt": "pct1",
        "ylab": "环比 %",
        "note": (
            "<b>六个品种的费率没有一个下降，而这六个品种的成交量方向并不一致 —— "
            "只有一个与量相关的机制能同时解释六条。</b>"
            f"跌得最狠的金属 ADV 环比 {adv_qoq[5]:+.1f}%，它的每手费率反而升了 "
            f"{rpc_qoq[5]:+.1f}%，是六个里最大的一格。"
            "把上季各品种的费率固定住、只换成本季的成交结构，混合费率是 "
            f"${weighted_rpc(lng):.4f}，比上季实际的 ${lng['rpc'][-2]:.3f} 还要低 —— "
            f"也就是说<b>结构效应是负的（{(weighted_rpc(lng) - lng['rpc'][-2]) * 1000:+.1f} 厘），"
            f"整个 ${lng['rpc'][-1] - lng['rpc'][-2]:+.3f} 的回升都来自品种内部</b>，"
            "而不是成交向高费率品种迁移。"),
        "src_extra": "各季业绩新闻稿的分品种 ADV 与 RPC 五季表；结构分解为固定上季费率的加权重算 D。",
    }

    margin = {
        "ref": "EX_MARGIN",
        "kind": "lines",
        "title": (f"近八季两条营业利润率：调整后 {fin['adj_margin_pct'][-1]:.1f}%，"
                  f"GAAP {fin['gaap_margin_pct'][-1]:.1f}%"),
        "xlabels": labels,
        "series": [
            {"name": "调整后营业利润率", "values": rounded(fin["adj_margin_pct"]), "color": "NAVY"},
            {"name": "GAAP 营业利润率", "values": rounded(fin["gaap_margin_pct"]), "color": "BLUE"},
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
        "ylab": "%",
        "note": (
            f"<b>上季的 {fin['adj_margin_pct'][-2]:.1f}% 是这八个季度里最高的一格，本季回落 "
            f"{fin['adj_margin_pct'][-1] - fin['adj_margin_pct'][-2]:.1f} 个百分点，"
            "而费用几乎没动。</b>"
            f"调整后费用环比 {signed(pct_change(fin['adj_total_expenses'][-1], fin['adj_total_expenses'][-2]))}，"
            f"收入环比 {signed(pct_change(fin['total_revenues'][-1], fin['total_revenues'][-2]))} —— "
            "利润率的落差几乎全部来自分母。两条线之间的缺口是并购无形资产摊销、"
            "重组与遣散、递延薪酬与诉讼等调整项，"
            f"本季 {fin['adj_margin_pct'][-1] - fin['gaap_margin_pct'][-1]:.1f} 个百分点。"),
        "src_extra": ("调整后营业利润取自各季业绩新闻稿的 Reconciliation of Adjusted Operating "
                      "Income 表；两个利润率均为该口径营业利润 ÷ 总收入 D，与公司披露的分子一致。"),
    }

    opex = {
        "ref": "EX_OPEX",
        "kind": "bar_line_dual",
        "title": (f"调整后营业费用（除许可费）US${fin['adj_opex_ex_license'][-1]:,.1f}M，"
                  f"许可费 US${fin['licensing_expense'][-1]:,.1f}M 单独一条"),
        "xlabels": labels,
        "bar": {"name": "调整后营业费用（除许可费）", "color": "NAVY",
                "values": rounded(fin["adj_opex_ex_license"])},
        "line": {"name": "许可与其他费用协议 (RHS)", "color": "GOLD",
                 "values": rounded(fin["licensing_expense"]), "yfmt": "f0c"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M", "rhs_label": "US$M",
        "note": (
            "<b>这条线是市场唯一拿来给 CME 建成本模型的口径，而公司从不把它写进任何申报文件。</b>"
            "本页能画出它，是因为它等于业绩新闻稿里的调整后费用合计减去合并损益表里的"
            "「许可与其他费用协议」一行，两个数都是披露值；但公司对它的<b>全年指引</b>只在"
            "业绩电话会上给，2025 年 6 月以来的三份 10-Q、一份 10-K 与四份业绩新闻稿逐字搜过，"
            "一次都没有出现。<b>所以第一节结清的是资本开支，不是它。</b>"
            f"把许可费单画一条是因为它跟着股指成交量走而不是跟着成本走："
            f"本季许可费同比 "
            f"{signed(pct_change(fin['licensing_expense'][-1], fin['licensing_expense'][-5]))}，"
            f"同期股指 ADV 同比 {signed(pct_change(lng['adv_equity'][-1], lng['adv_equity'][-5]))}。"),
        "src_extra": ("调整后费用合计取自 Reconciliation of Adjusted Operating Income 表"
                      "（公司自 2025 年第三季度业绩新闻稿起才印这张表，因此本页的调整后费用"
                      "序列正好只有八个季度）；许可费取自合并损益表。差额为 D。"),
    }

    md_yoy = [pct_change(fin["market_data"][i], staging["long"]["market_data"][-8 - 4 + i])
              for i in range(8)]
    market_data = {
        "ref": "EX_MKTDATA",
        "kind": "bar_line_dual",
        "title": (f"行情数据与信息服务 US${fin['market_data'][-1]:,.1f}M，"
                  f"同比 {signed(md_yoy[-1])}，八个季度全部创纪录"),
        "xlabels": labels,
        "bar": {"name": "行情数据与信息服务收入", "color": "MBLUE",
                "values": rounded(fin["market_data"])},
        "line": {"name": "同比 (RHS)", "color": "RED", "values": rounded(md_yoy), "yfmt": "pct1"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M", "rhs_label": "同比 %",
        "note": (
            "<b>这条线现在扛着 CME 全部的同比增长，而它的加速与成交量无关。</b>"
            f"同比从 {md_yoy[0]:+.1f}% 一路走到 {md_yoy[-1]:+.1f}%，"
            f"环比 {signed(pct_change(fin['market_data'][-1], fin['market_data'][-2]))}。"
            "<b>本页不拆分这条线的价与量</b>：公司既不披露提价幅度，也不披露订阅数的绝对值，"
            "电话会上给过的「专业订阅数环比」与「同比」是两个不同口径的数，"
            "把它们当同一个序列相减会造出一个不存在的量增长。"
            "能从申报文件里读到的只有这条收入线本身，以及它在总收入里的占比 —— "
            f"本季 {100 * fin['market_data'][-1] / fin['total_revenues'][-1]:.1f}%，"
            "见 Exhibit {EX_MKTDATA_LONG} 的长序列。"),
        "src_extra": "合并损益表的行情数据与信息服务一行；同比由本页对同一序列相除 D。",
    }

    eps = {
        "ref": "EX_EPS",
        "kind": "lines",
        "title": (f"近八季两条摊薄每股收益：调整后 ${fin['adj_diluted_eps'][-1]:.2f}，"
                  f"GAAP ${fin['diluted_eps'][-1]:.2f}"),
        "xlabels": labels,
        "series": [
            {"name": "调整后摊薄 EPS", "values": rounded(fin["adj_diluted_eps"]), "color": "NAVY"},
            {"name": "GAAP 摊薄 EPS", "values": rounded(fin["diluted_eps"]), "color": "BLUE"},
        ],
        "fmt": "usd2", "yfmt": "usd2", "label_fmt": "usd2", "end_label": True,
        "ylab": "US$/股",
        "note": (
            f"<b>本季 GAAP 与调整后的缺口收窄到 "
            f"${fin['adj_diluted_eps'][-1] - fin['diluted_eps'][-1]:.2f}，是八季里最窄的一格。</b>"
            f"GAAP 有效税率 {fin['effective_tax_pct'][-1]:.2f}%，比上季的 "
            f"{fin['effective_tax_pct'][-2]:.2f}% 低 "
            f"{(fin['effective_tax_pct'][-2] - fin['effective_tax_pct'][-1]) * 100:.0f} 个基点，"
            "GAAP 那条线因此被抬高；而公司的调整口径把当季的离散税项整笔剔除，"
            "所以调整后那条线没有被同一件事抬到。"
            f"摊薄股数从上季的 {fin['diluted_shares_k'][-2]:,.0f} 千股降到 "
            f"{fin['diluted_shares_k'][-1]:,.0f} 千股，"
            "上季含 2026-03-05 优先股转普通股的加权影响，两季分母口径不同。"),
        "src_extra": ("GAAP 每股收益与摊薄股数取自合并损益表，调整后每股收益取自 Reconciliation "
                      "of Adjusted Net Income 表；有效税率为所得税费用 ÷ 税前利润 D。"),
    }
    return [mix, bridge, class_rpc, margin, opex, market_data, eps]


def weighted_rpc(lng: dict) -> float:
    """This quarter's volume mix priced at last quarter's per-class rates."""
    total = sum(lng[f"adv_{k}"][-1] for k, _, _ in CLASSES)
    return sum(lng[f"adv_{k}"][-1] * lng[f"rpc_{k}"][-2] for k, _, _ in CLASSES) / total


# ── section three: what the next release settles ─────────────────────────────

def next_section(staging: dict) -> list[dict]:
    fin = staging["financials"]
    labels = staging["period_labels"]
    entries = staging["next_kpi"]["quantified"]
    bar = headroom_exhibit(
        "下季阈值：当前值离每条线还有多远",
        entries, "current",
        note=(
            "<b>六条线的单位互不相同，所以画的是「距阈值还有百分之几」而不是原值</b>；"
            "原始单位见核对抽屉里的阈值表。正值在安全侧，负值已经越线 —— "
            "本季已经越线的是利率类 ADV 的同比。"
            "六条全部可以在下一份业绩新闻稿里直接读到，不需要任何未披露的数据："
            "四条来自合并损益表与调整对账表，两条来自同一份文件里的 ADV/RPC 五季表。"
            "<b>其中「调整后营业费用（除许可费）」的阈值是本页自己设的警戒线，"
            "不是公司的指引</b> —— 公司的全年费用指引不在任何申报文件里，本页不接入它，"
            "所以也不用它反推季度阈值。"
            + staging["next_kpi"]["excluded"]),
        src_extra=("阈值为本页设定；当前值全部取自 2026 年第二季度业绩新闻稿"
                   "（合并损益表、调整对账表与 ADV/RPC 五季表）。"),
    )
    bar["ref"] = "EX_HEADROOM"

    margin_line = threshold_exhibit(
        "调整后营业利润率对 67.5% 这条线",
        labels, rounded(fin["adj_margin_pct"]), 67.5,
        fmt="pct1", ylab="%",
        actual_name="调整后营业利润率", threshold_name="阈值 67.5%",
        note=(
            "<b>余量条回答「哪条线破了」，这张回答「它是怎么走到这里的」。</b>"
            f"八个季度里最高的一格是 {labels[fin['adj_margin_pct'].index(max(fin['adj_margin_pct']))]} 的 "
            f"{max(fin['adj_margin_pct']):.1f}%，最低是 "
            f"{labels[fin['adj_margin_pct'].index(min(fin['adj_margin_pct']))]} 的 "
            f"{min(fin['adj_margin_pct']):.1f}%，本季 {fin['adj_margin_pct'][-1]:.1f}%。"
            "阈值 67.5% 是本页设定的，不是公司的任何披露："
            f"它取窗口内最低的一格再往下一点，因此「跌破」意味着这八个季度里没有出现过的事。"),
        src_extra="调整后营业利润 ÷ 总收入 D，分子取自各季业绩新闻稿的调整对账表。",
    )
    margin_line["ref"] = "EX_MARGIN_LINE"

    rpc_line = threshold_exhibit(
        "平均每手费率对 $0.670 这条线",
        labels, rounded(staging["long"]["rpc"][-8:]), 0.670,
        fmt="usd3", ylab="US$/手",
        actual_name="平均每手费率 RPC", threshold_name="阈值 $0.670",
        note=(
            "<b>这条线要和成交量一起读，单独看会给出相反的结论。</b>"
            f"本季 ${staging['long']['rpc'][-1]:.3f}，比上季高 "
            f"${staging['long']['rpc'][-1] - staging['long']['rpc'][-2]:.3f}，"
            "但 Exhibit {EX_ADV_LONG} 说明这个回升是成交量下滑的机械结果。"
            "<b>所以真正有信息量的组合是「量回来了而费率没掉」</b>："
            f"若下季 ADV 回到 32,000 千手以上而费率仍不低于 $0.675，"
            "才说明存在与成交量无关的费率改善；"
            "若量价同时落到阈值以下，则说明连分级费率的缓冲也没兜住。"),
        src_extra="各季业绩新闻稿五季表的 Average RPC 一行；阈值为本页设定。",
    )
    rpc_line["ref"] = "EX_RPC_LINE"
    return [bar, margin_line, rpc_line]


# ── section four: the long series ────────────────────────────────────────────

def routine_section(staging: dict) -> list[dict]:
    lng = staging["long"]
    coll = staging["collateral"]
    labels = lng["period_labels"]
    n = len(labels)

    adv_long = {
        "ref": "EX_ADV_LONG",
        "kind": "bar_line_dual",
        "title": (f"{n} 季量与价：ADV {lng['adv_k'][-1] / 1000:.1f}M 手/日，"
                  f"平均每手费率 ${lng['rpc'][-1]:.3f}"),
        "xlabels": labels,
        "bar": {"name": "季度 ADV（千手/日）", "color": "BLUE", "values": rounded(lng["adv_k"])},
        "line": {"name": "平均每手费率 RPC", "color": "NAVY", "values": rounded(lng["rpc"]),
                 "yfmt": "usd3"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "千手/日", "rhs_label": "US$/手", "xstep": LONG_STEP,
        "note": (
            f"<b>五十四个季度里，成交量与每手费率有 {opposite_moves(lng)} 个季度朝相反方向走。</b>"
            f"把两者的环比变动回归，斜率是 {rpc_slope(lng):.2f}（费率环比 % 对成交量环比 %），"
            f"R² {rpc_r2(lng):.2f}。这不是定价能力，是分级费率的算术："
            "客户当月累计成交量越大，边际合约落进的档位费率越低，所以量涨价跌、量跌价涨。"
            f"窗口内 ADV 最低的一季是 {labels[lng['adv_k'].index(min(lng['adv_k']))]}"
            f"（{min(lng['adv_k']) / 1000:.1f}M 手/日），"
            f"最高的是 {labels[lng['adv_k'].index(max(lng['adv_k']))]}"
            f"（{max(lng['adv_k']) / 1000:.1f}M 手/日）。"),
        "src_extra": ("每季 ADV 与 RPC 取自当季业绩新闻稿的五季表；"
                      "同一个季度在其后四份新闻稿里重复出现，逐份核对无差异。"),
    }

    contracts_qoq = qoq(lng["contracts_m"])
    revenue_qoq = qoq(lng["total_revenues"])
    fee_qoq = qoq(lng["clearing_fees"])
    beta_rev, r2_rev = slope_and_r2(contracts_qoq, revenue_qoq)
    beta_fee, r2_fee = slope_and_r2(contracts_qoq, fee_qoq)
    beta = {
        "ref": "EX_BETA",
        "kind": "lines",
        "title": (f"{len(contracts_qoq)} 次环比变动：成交量动 1%，总收入只动 "
                  f"{beta_rev:.2f}%（R² {r2_rev:.2f}）"),
        "xlabels": labels[1:],
        "series": [
            {"name": "成交合约数环比", "values": rounded(contracts_qoq), "color": "GRAY"},
            {"name": "清算与交易费环比", "values": rounded(fee_qoq), "color": "BLUE"},
            {"name": "总收入环比", "values": rounded(revenue_qoq), "color": "NAVY"},
        ],
        "fmt": "pct0", "yfmt": "pct0", "label_fmt": "pct0",
        "ylab": "环比 %", "xstep": LONG_STEP, "zero_line": True,
        "note": (
            "<b>三条线的形状一样，振幅一层比一层小 —— 这就是这家公司最被低估的属性。</b>"
            f"把成交合约数的环比变动作自变量：清算与交易费的斜率是 {beta_fee:.2f}"
            f"（R² {r2_fee:.2f}），总收入的斜率是 {beta_rev:.2f}（R² {r2_rev:.2f}）。"
            f"本季自己的读数是成交量 {contracts_qoq[-1]:+.1f}%、清算费 {fee_qoq[-1]:+.1f}%、"
            f"总收入 {revenue_qoq[-1]:+.1f}%，落在这条长期关系上而不是外面。"
            "<b>它是对称的，这一点比抗跌更重要</b>：同一个系数意味着量能回升时收入也只跟一半多一点，"
            f"所以用本季 ${lng['rpc'][-1]:.3f} 的费率去乘一个高成交量假设，"
            "会同时高估价和量。"),
        "src_extra": ("成交合约数 = ADV × 交易日（两者均为公司披露值）D；收入取自合并损益表。"
                      "斜率与 R² 为对本页所载序列的最小二乘回归 D，可用图下数据复算。"),
    }

    residual = {
        "ref": "EX_RESIDUAL",
        "kind": "lines",
        "title": (f"清算与交易费拆成两块：期货与期权 US${lng['fo_clearing_fees'][-1]:,.0f}M，"
                  f"其余 US${lng['other_clearing_fees'][-1]:,.0f}M"),
        "xlabels": labels,
        "series": [
            {"name": "清算与交易费（报表值）", "values": rounded(lng["clearing_fees"]), "color": "NAVY"},
            {"name": "期货与期权：ADV × 交易日 × RPC", "values": rounded(lng["fo_clearing_fees"]),
             "color": "BLUE"},
            {"name": "其余（现券、外汇等）", "values": rounded(lng["other_clearing_fees"]),
             "color": "GOLD"},
        ],
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c", "end_label": True,
        "ylab": "US$M", "xstep": LONG_STEP,
        "break_at": lng["quarters"].index("2018Q4"),
        "break_label": "NEX（BrokerTec 与 EBS）并表（2018Q4）",
        "note": (
            "<b>公司披露的 ADV 与 RPC 只覆盖期货与期权，而报表的清算与交易费还包含 BrokerTec "
            "的现券与 EBS 的外汇 —— 这张图把那块差额单独画出来，因为本页所有量价分析都不覆盖它。</b>"
            f"差额本季 US${lng['other_clearing_fees'][-1]:,.1f}M，占清算与交易费 "
            f"{100 * lng['other_clearing_fees'][-1] / lng['clearing_fees'][-1]:.1f}%。"
            "<b>这条差额线自己就是这套推算是否成立的证据</b>：它在 2018 年第三季度之前的"
            f"二十三个季度里从没超过 US${max(lng['other_clearing_fees'][:23]):,.0f}M，"
            "而 2018 年 11 月 NEX 并表的那一个季度直接跳到 "
            f"US${lng['other_clearing_fees'][23]:,.0f}M，此后再没回去过 —— "
            "台阶落在收购当季，而不是落在任何一次费率或口径变动上。"
            "<b>这块的内部量价结构完全不可见</b>：公司不公布现券与外汇的成交量或费率，"
            "所以本页不对它做任何拆解，只标出它有多大。"),
        "src_extra": ("报表值取自合并损益表；期货与期权部分为公司披露的 ADV × 交易日 × RPC D；"
                      "差额为两者相减 D。"),
    }

    invest = {
        "ref": "EX_INVEST",
        "kind": "lines",
        "title": (f"{n} 季投资收益与利息分配支出：从近乎为零到 "
                  f"US${lng['investment_income'][-1]:,.0f}M 再回落"),
        "xlabels": labels,
        "series": [
            {"name": "投资收益", "values": rounded(lng["investment_income"]), "color": "NAVY"},
            {"name": "其他非经营收支（主要是付给清算会员的利息分配）",
             "values": rounded(lng["other_nonop"]), "color": "BLUE"},
        ],
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c", "end_label": True,
        "ylab": "US$M", "xstep": LONG_STEP, "zero_line": True,
        "note": (
            "<b>两条线几乎是镜像，而这正是它们容易被读错的原因。</b>"
            f"投资收益从 {labels[0]} 的 US${lng['investment_income'][0]:,.1f}M 涨到本季的 "
            f"US${lng['investment_income'][-1]:,.0f}M，看起来是一条巨大的利率敞口；"
            "但同期公司付给清算会员的利息分配几乎等额地跟着涨。"
            "<b>本页不把这两条相减当成利差</b>：其他非经营收支里还有非抵押品的项目，"
            "2021 年那一格是正的，因为里面装着一笔与利率无关的一次性收益。"
            "真正只属于抵押品的那一段公司在 10-Q 里单独用文字给出，见 Exhibit {EX_SPREAD}。"),
        "src_extra": "两条均为合并损益表的原始行，未做任何合并或净额处理。",
    }

    spread = {
        "ref": "EX_SPREAD",
        "kind": "bar_line_dual",
        "title": (f"抵押品净利差 US${coll['net'][-1]:,.1f}M，"
                  f"折合留存约 {coll['retained_bp'][-1]:.0f} 个基点"),
        "xlabels": coll["period_labels"],
        "bar": {"name": "抵押品再投资收益 − 利息分配支出（US$M）", "color": "NAVY",
                "values": rounded(coll["net"])},
        "line": {"name": "折合留存利差 (RHS)", "color": "GOLD",
                 "values": rounded(coll["retained_bp"]), "yfmt": "f0"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M", "rhs_label": "基点",
        "note": (
            "<b>这条收入被普遍当成利率敞口，但它是一个基点数，不是一个利率。</b>"
            f"{len(coll['quarters']) - 2} 个 2022 年以来的季度里，留存利差落在 "
            f"{min(x for x in coll['retained_bp'][2:]):.0f} 到 "
            f"{max(coll['retained_bp'][2:]):.0f} 个基点之间，"
            f"而同一笔余额上的毛收益率从 {min(coll['gross_bp'][2:]):.0f} 个基点走到 "
            f"{max(coll['gross_bp'][2:]):.0f} 个基点又回到 {coll['gross_bp'][-1]:.0f}。"
            f"最左边两格是零利率年代：{coll['period_labels'][0]} 的留存利差只有 "
            f"{coll['retained_bp'][0]:.0f} 个基点，净额 US${coll['net'][0]:.1f}M。"
            "<b>所以常规降息压缩的是分子和分母，留存的基点数基本不动；"
            "真正的风险是利率低到这个基点数没地方赚 —— 那种情形图上左端已经出现过一次。</b>"
            "反过来说，留存额随余额复利增长，而余额跟着未平仓合约走。"),
        "src_extra": (
            "再投资收益与利息分配支出是 10-Q 与 10-K 正文里逐季用文字给出的两个数（附注四与 "
            "MD&A，两处口径一致，本页交叉核对过）；余额取合并资产负债表的 Performance bonds "
            "and guaranty fund contributions 一行、按本季末与上季末取平均 D。"
            "<b>那是期末数不是日均数</b>：公司唯一一次公开的日均现金抵押品余额比本页这个"
            "两点平均低约 8%，因此本页的基点数相应偏低约 8%，趋势不受影响。"),
    }

    md_share = [100 * m / r for m, r in zip(lng["market_data"], lng["total_revenues"])]
    md_long = {
        "ref": "EX_MKTDATA_LONG",
        "kind": "bar_line_dual",
        "title": (f"{n} 季行情数据收入：US${lng['market_data'][0]:,.0f}M → "
                  f"US${lng['market_data'][-1]:,.0f}M，占总收入 {md_share[-1]:.1f}%"),
        "xlabels": labels,
        "bar": {"name": "行情数据与信息服务收入", "color": "MBLUE",
                "values": rounded(lng["market_data"])},
        "line": {"name": "占总收入 (RHS)", "color": "NAVY", "values": rounded(md_share),
                 "yfmt": "pct1"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$M", "rhs_label": "%", "xstep": LONG_STEP,
        "note": (
            "<b>这条线在十三年半里翻了一倍多，而它在总收入里的占比几乎没动 —— "
            "因为清算费也涨了同样多。</b>"
            f"占比从 {md_share[0]:.1f}% 走到 {md_share[-1]:.1f}%，"
            f"窗口内的低点是 {labels[md_share.index(min(md_share))]} 的 {min(md_share):.1f}%。"
            "<b>本季是这条线第一次单独扛起全公司的同比增长</b>，"
            "不是因为它突然加速，而是因为另外两条腿停了。"),
        "src_extra": "合并损益表的行情数据与信息服务一行与总收入一行；占比为两者相除 D。",
    }

    # The 2017 tax act remeasured deferred tax liabilities in one quarter and
    # produced an effective rate of -411%. Drawn on one axis with the rest, that
    # single point compresses the other fifty-three into the top 5% of the
    # canvas -- a chart that passes every gate and shows nothing. The window
    # therefore starts where the statutory rate does: 35% federal before 2018,
    # 21% after, which is two regimes rather than one series anyway.
    tax_start = lng["quarters"].index("2018Q1")
    tax_labels = labels[tax_start:]
    tax_values = lng["effective_tax_pct"][tax_start:]
    pre = lng["effective_tax_pct"][:tax_start]
    tax = {
        "ref": "EX_TAX",
        "kind": "lines",
        "title": (f"{len(tax_labels)} 季 GAAP 有效税率（2018 年税改之后）：本季 "
                  f"{tax_values[-1]:.1f}%"),
        "xlabels": tax_labels,
        "series": [
            {"name": "GAAP 有效税率", "values": rounded(tax_values), "color": "NAVY"},
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
        "ylab": "%", "xstep": LONG_STEP,
        "note": (
            "<b>这张图从 2018 年第一季度开始，而不是像本节其他图那样从 2013 年开始，"
            "原因写在这里而不是留给读者猜。</b>"
            f"2017 年第四季度美国税改一次性重估递延所得税负债，当季有效税率是 "
            f"{min(pre):.1f}% —— 一个把其余五十三个季度压进画布顶端百分之五的数。"
            "而且联邦法定税率本身在 2018 年 1 月从 35% 降到 21%，"
            "跨越那一点的税率序列是两套制度而不是一条线。"
            f"窗口内最低的一季是 {tax_labels[tax_values.index(min(tax_values))]} 的 "
            f"{min(tax_values):.1f}%，最高的是 "
            f"{tax_labels[tax_values.index(max(tax_values))]} 的 {max(tax_values):.1f}%；"
            f"本季 {tax_values[-1]:.1f}%，比上季低 "
            f"{(tax_values[-2] - tax_values[-1]) * 100:.0f} 个基点。"
            "公司的调整口径把当季的离散税项整笔剔除，所以它只影响 GAAP 这一条线，"
            "不影响 Exhibit {EX_EPS} 里的调整后每股收益。"),
        "src_extra": ("所得税费用 ÷ 税前利润，两者均取自合并损益表 D。"
                      "2013Q1 至 2017Q4 的读数仍在核对抽屉之外的原始序列里，只是不画在这张图上。"),
    }
    class_adv = {
        "ref": "EX_CLASS_ADV",
        "kind": "lines",
        "title": f"{n} 季六个品种的 ADV：利率一条腿占 {100 * lng['adv_rates'][-1] / lng['adv_k'][-1]:.0f}%",
        "xlabels": labels,
        "series": [
            {"name": name, "values": rounded(lng[f"adv_{key}"]), "color": color}
            for key, name, color in CLASSES
        ],
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "千手/日", "xstep": LONG_STEP,
        "note": (
            "<b>利率是这家公司的主干，也是它唯一一条被点名挑战的产品线。</b>"
            f"本季利率 ADV {lng['adv_rates'][-1]:,.0f} 千手、同比 "
            f"{signed(pct_change(lng['adv_rates'][-1], lng['adv_rates'][-5]))}；"
            f"股指同比 {signed(pct_change(lng['adv_equity'][-1], lng['adv_equity'][-5]))}，"
            "是本季六个品种里同比幅度最大的一条。"
            f"窗口内利率 ADV 的最高一季是 {labels[lng['adv_rates'].index(max(lng['adv_rates']))]} 的 "
            f"{max(lng['adv_rates']):,.0f} 千手。"
            "<b>本页不发布任何竞争对手的成交量</b>：那些数字来自对手方的季报与新闻稿，"
            "口径与这张图的合约张数不可比，混在一起画会造出一个两边都不成立的份额。"),
        "src_extra": "各季业绩新闻稿的分品种 ADV 五季表；均为公司披露值。",
    }
    return [adv_long, beta, residual, invest, spread, md_long, class_adv, tax]


def opposite_moves(lng: dict) -> int:
    a, r = qoq(lng["adv_k"]), qoq(lng["rpc"])
    return sum(1 for x, y in zip(a, r) if x * y < 0)


def rpc_slope(lng: dict) -> float:
    return slope_and_r2(qoq(lng["adv_k"]), qoq(lng["rpc"]))[0]


def rpc_r2(lng: dict) -> float:
    return slope_and_r2(qoq(lng["adv_k"]), qoq(lng["rpc"]))[1]


# ── payload ──────────────────────────────────────────────────────────────────

def build_payload(staging: dict) -> dict:
    fin = staging["financials"]
    lng = staging["long"]
    coll = staging["collateral"]
    capex = staging["capex_guidance"]
    labels = staging["period_labels"]

    settled, settled_tables = capex_section(staging)
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

    tally = capex_tally(capex)
    finished = finished_capex_years(capex)
    contracts_qoq = qoq(lng["contracts_m"])
    beta_rev, r2_rev = slope_and_r2(contracts_qoq, qoq(lng["total_revenues"]))
    post_zirp = [bp for bp in coll["retained_bp"][2:]]

    first_table = exhibits[-1]["n"] + 1
    tables = [{**t, "n": first_table + i} for i, t in enumerate(settled_tables)]
    tables.append({
        "n": first_table + len(settled_tables),
        "title": "近八季合并损益与非 GAAP 对账（公司披露值，US$M）",
        "headers": ["期间", "清算与交易费", "行情数据", "其他收入", "总收入",
                    "营业费用", "经营利润", "GAAP 利润率", "调整后费用",
                    "调整后费用（除许可费）", "调整后经营利润", "调整后利润率",
                    "GAAP 摊薄 EPS", "调整后摊薄 EPS"],
        "rows": [[labels[i],
                  f"${fin['clearing_fees'][i]:,.1f}",
                  f"${fin['market_data'][i]:,.1f}",
                  f"${fin['other_revenue'][i]:,.1f}",
                  f"${fin['total_revenues'][i]:,.1f}",
                  f"${fin['total_expenses'][i]:,.1f}",
                  f"${fin['operating_income'][i]:,.1f}",
                  f"{fin['gaap_margin_pct'][i]:.1f}%",
                  f"${fin['adj_total_expenses'][i]:,.1f}",
                  f"${fin['adj_opex_ex_license'][i]:,.1f} D",
                  f"${fin['adj_operating_income'][i]:,.1f}",
                  f"{fin['adj_margin_pct'][i]:.1f}% D",
                  f"${fin['diluted_eps'][i]:.2f}",
                  f"${fin['adj_diluted_eps'][i]:.2f}"]
                 for i in range(len(labels))],
    })
    tables.append({
        "n": first_table + len(settled_tables) + 1,
        "title": "近八季量价与清算费拆分（ADV 与 RPC 为公司披露值）",
        "headers": ["期间", "ADV（千手/日）", "交易日", "平均每手费率",
                    "成交合约数（百万张）D", "期货与期权清算费 D",
                    "报表清算与交易费", "其余（现券、外汇等）D"],
        "rows": [[labels[i],
                  f"{lng['adv_k'][-8 + i]:,.0f}",
                  f"{lng['trading_days'][-8 + i]:d}",
                  f"${lng['rpc'][-8 + i]:.3f}",
                  f"{lng['contracts_m'][-8 + i]:,.1f}",
                  f"${lng['fo_clearing_fees'][-8 + i]:,.1f}",
                  f"${lng['clearing_fees'][-8 + i]:,.1f}",
                  f"${lng['other_clearing_fees'][-8 + i]:,.1f}"]
                 for i in range(len(labels))],
    })
    tables.append({
        "n": first_table + len(settled_tables) + 2,
        "title": "抵押品再投资：申报文件逐季给出的两个数与由它们得到的利差（US$M）",
        "headers": ["期间", "再投资收益", "利息分配支出", "净额 D",
                    "净额占再投资收益 D", "期末与上季末平均余额 D",
                    "毛收益率（年化）D", "留存利差（年化）D"],
        "rows": [[coll["period_labels"][i],
                  f"${coll['earnings'][i]:,.1f}",
                  f"${coll['distribution'][i]:,.1f}",
                  f"${coll['net'][i]:,.1f}",
                  f"{coll['retained_pct_of_gross'][i]:.2f}%",
                  (f"${coll['avg_balance_usd_m'][i] / 1000:,.1f}B"
                   if coll["avg_balance_usd_m"][i] is not None else "—"),
                  (f"{coll['gross_bp'][i]:.0f}bp" if coll["gross_bp"][i] is not None else "—"),
                  (f"{coll['retained_bp'][i]:.1f}bp" if coll["retained_bp"][i] is not None else "—")]
                 for i in range(len(coll["quarters"]))],
    })
    tables.append(threshold_table(first_table + len(settled_tables) + 3,
                                  "下季阈值与当前值（原始单位）",
                                  staging["next_kpi"]["quantified"], "current", "当前值"))
    tables.append(ai_capex_cycle_table(first_table + len(settled_tables) + 4))

    return {
        "schema_version": "quarterly-dashboard/cme-v1",
        "page": {"slug": "cme", "language": "zh-CN"},
        "company": {
            "ticker": "CME",
            "name": "CME Group Inc.",
            "group": "exchanges",
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
        "tracker": "Watchlist Quarterly Tracker · CME",
        "title": "CME Group Inc. (CME)：Q2 2026 季报仪表盘",
        "subtitle": ("截至 2026-06-30 · 发布 2026-07-22 · US GAAP · 未审计 · "
                     "自然年财年，季度标注与财年一致"),
        "headline": (
            f"总收入 US${fin['total_revenues'][-1]:,.1f}M、同比 "
            f"{signed(pct_change(fin['total_revenues'][-1], fin['total_revenues'][-5]))}，"
            f"清算与交易费同比 "
            f"{signed(pct_change(fin['clearing_fees'][-1], fin['clearing_fees'][-5]))}、"
            f"是本窗口内第一次转负，全部同比增量来自行情数据一条线（同比 "
            f"{signed(pct_change(fin['market_data'][-1], fin['market_data'][-5]))}）；"
            f"成交合约数环比 {contracts_qoq[-1]:.1f}% 而总收入只跌 "
            f"{abs(qoq(lng['total_revenues'])[-1]):.1f}%，"
            f"这是五十三次环比变动测出来的同一条斜率（{beta_rev:.2f}）。"),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>记录</span><b>申报文件里只有一条指引，而且它一直偏高</b>'
            f'<p>{len(finished)} 个已完结年度里全年资本开支对 10-K 的指引 '
            f'{tally["below"]} 年低于下限、{tally["above"]} 年高于上限、'
            f'{tally["inside"]} 年落在区间内；三次超支是连续的 FY2018–FY2020。'
            '市场真正拿来建模的全年费用指引只在电话会上给，任何申报文件里都没有，本页不接入。</p></article>'
            '<article><span>机制</span><b>量动一个点，收入只动零点六六个点</b>'
            f'<p>五十三次环比变动里，总收入对成交合约数的斜率是 {beta_rev:.2f}（R² {r2_rev:.2f}），'
            f'清算与交易费是 {slope_and_r2(contracts_qoq, qoq(lng["clearing_fees"]))[0]:.2f}；'
            f'成交量与每手费率有 {opposite_moves(lng)}/{len(contracts_qoq)} 个季度反向。'
            f'本季成交量 {contracts_qoq[-1]:+.1f}%、收入 {qoq(lng["total_revenues"])[-1]:+.1f}%，'
            '落在这条长期关系上。</p></article>'
            '<article><span>口径</span><b>抵押品那条线是基点，不是利率</b>'
            f'<p>2022 年以来 {len(post_zirp)} 个季度的留存利差落在 {min(post_zirp):.0f}–'
            f'{max(post_zirp):.0f} 个基点之间，而同一笔余额上的毛收益率从 '
            f'{min(coll["gross_bp"][2:]):.0f} 走到 {max(coll["gross_bp"][2:]):.0f} 个基点。'
            f'零利率的 {coll["period_labels"][0]} 那一格只有 {coll["retained_bp"][0]:.0f} 个基点。</p></article>'
            '</div>'),
        "source": ('Source: <a href="https://www.sec.gov/Archives/edgar/data/1156375/'
                   '000115637526000042/exhibit9916302026.htm" rel="noopener">'
                   'CME Group 2026 年第二季度业绩新闻稿（8-K EX-99.1）</a>'
                   '与截至 2026-06-30 的 10-Q、截至 2025-12-31 的 10-K。'),
        "source_url": ("https://www.sec.gov/Archives/edgar/data/1156375/"
                       "000115637526000042/exhibit9916302026.htm"),
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {"id": "settled", "title": "一、申报文件里唯一的那条指引兑现了吗",
             "description": ("CME 每年在 10-K 的流动性一节里用一句话给出全年资本开支的预期，"
                             "十七年没有断过；除此之外，它在申报文件里不指引收入、每股收益、"
                             "利润率，也不指引费用。市场用来给它建成本模型的那个全年调整后"
                             "营业费用指引只出现在业绩电话会上，本页逐份检索过最近的三份 10-Q、"
                             "一份 10-K 与四份业绩新闻稿，一次都没有找到，因此不接入。"
                             "这一节结清的是那条唯一有申报出处的指引。"),
             "exhibits": settled_ex},
            {"id": "quarter_highlights", "title": "二、本季重点",
             "description": ("先把三条收入线分开，再把清算费的环比变动拆成量与价两块，"
                             "然后看六个品种里量价同时反向这件事，"
                             "最后是利润率、费用与每股收益。"),
             "exhibits": highlight_ex},
            {"id": "next_quarter", "title": "三、下季要跟踪什么",
             "description": ("六条阈值，全部能在下一份业绩新闻稿里直接读到；"
                             "统一用「距阈值余量」口径，再把其中两条画回它们自己的历史。"
                             "不接入的几类数据也写在这里。"),
             "exhibits": next_ex},
            {"id": "routine", "title": "四、长期常规跟踪",
             "description": ("五十四个季度的量与价、收入对成交量的斜率、清算费里看不见的那一块、"
                             "投资收益与利息分配的镜像，以及抵押品利差、行情数据与有效税率。"),
             "exhibits": routine_ex},
        ],
        "tables": tables,
        "notes": [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "CME 财年即自然年，本页季度标注与公司自己的口径一致，无需换算。",
            "第一节结清的是资本开支，不是费用。市场给 CME 建成本模型用的是「全年调整后营业费用（除许可费）」，2026 年的口径是约 16.95 亿美元；这个数只在业绩电话会上出现。本页逐字检索过 2025 年 6 月以来的三份 10-Q、FY2025 的 10-K 与最近四份业绩新闻稿，其中没有任何一处给出全年费用指引，8-K 正文同样没有。本站只发布有申报出处的指引，所以第一节结清的是每年 10-K 里那句「In 20XX, we expect capital expenditures to total approximately $X million」。这不是说费用指引不重要，而是说它不满足本站对可核对来源的要求。",
            "资本开支指引的形式在窗口内换过一次：FY2010、FY2012、FY2013 给的是区间，其余十四个年度给的是一个单点。因此「落在区间内」这一档在图上只对那三年有意义，十六个已完结年度里只发生过一次（FY2012）。单点指引在图上没有宽度，这是公司的指引本来就没有宽度，不是渲染缺陷。",
            "资本开支的实际值取各年 10-K 现金流量表的 Purchases of property 一行。每个年度都在两到三份 10-K 的三年比较列里重复出现过，逐份核对没有任何一年被重述。指引与实际因此跨十七年在同一个口径上。",
            "分品种的 ADV 与 RPC 只覆盖期货与期权，公司在五季表的脚注里写明这一点。报表的清算与交易费还包含 BrokerTec 的现券与 EBS 的外汇业务，公司不披露这两块的成交量或费率。本页把差额单独画成一条线并标出它的大小，但不对它做任何量价拆解。",
            "本页的品种标签在窗口内改过名：2018 年第四季度以前公司写的是 Interest rate、Equity、Agricultural commodity、Metal 的单数形式，2013 年上半年股指那一行叫 Equities。数值没有变，只有标签变了；本页逐份按标签的历史拼写取值，因此六个品种的序列在五十四个季度上连续。若只按现在的复数拼写取值，会有二十一个季度的品种行取不到，而合计行仍然取得到 —— 那种缺失在图上看不出来。",
            "成交场所的拆分（CME Globex、公开喊价、私下议价）本页不接入。公司在 2013 年第三季度换过一次场所口径，此前用的是 Exchange-traded 与 CME ClearPort 两分法；同一个 2013 年第一季度按不同新闻稿读出的私下议价成交量是 275 千手或 691 千手。本页其余每一条序列在所有出现过它的新闻稿里都完全一致，只有这一条不是，所以不发布。",
            "调整后的费用、经营利润与利润率只有八个季度，因为公司是从 2025 年第三季度那期业绩新闻稿起才开始印 Reconciliation of Adjusted Operating Income 这张表的。此前各期只印调整后净利润与调整后每股收益的对账。调整后每股收益本身还有一段 2014 年第四季度至 2018 年第三季度的更早记录，但公司在 2016 年改过调整项的定义并重述了 2015 年第四季度与 2016 年第一季度（例如 2015 年第四季度的调整后每股收益由 0.92 美元改为 0.97 美元），跨越这次改动的比较不同基准，因此本页不把两段接起来。",
            "「调整后营业费用（除许可费）」是调整后费用合计减去合并损益表里「许可与其他费用协议」一行，两个数都是公司披露值，相减是本页做的。用这个口径是因为公司自己的全年指引就是按它给的；把许可费单画一条，是因为它随股指成交量变动而不是随成本决策变动。",
            "抵押品再投资收益与利息分配支出这两个数不在业绩新闻稿里，只在 10-Q 与 10-K 的正文中以文字给出，且同一份文件里出现两次、写法不同：附注四写成「本季与年初至今」两个数并列，MD&A 写成「本季与去年同期」两个数并列。两处口径一致，本页交叉核对过每一个季度。取值一律按名词认期间，不按位置；同一句话里第二个数在附注四里是年初至今、在 MD&A 里是去年同期，按位置取会把两者互换。这项披露自 2021 年第三季度起才有，更早的季度没有，因此该序列只有十四个季度而不是五十四个。",
            "留存利差的分母是合并资产负债表上 Performance bonds and guaranty fund contributions 一行，按本季末与上季末取平均。这是期末数不是日均数：公司唯一一次公开过的日均现金抵押品余额约为 1,490 亿美元，本页同期的两点平均是 1,623 亿美元，高约 8%，因此本页算出的基点数相应偏低约 8%。趋势与区间不受影响，绝对水平要按这个偏差读。",
            "投资收益与其他非经营收支这两条线本页不相减。其他非经营收支里除了付给清算会员的利息分配还有别的项目，2021 年该行是正数，里面装着一笔与利率无关的一次性收益；相减会得到一条把它算进利差的曲线。只属于抵押品的那一段用上一条注释里的文字披露单独画。",
            "收入对成交量的斜率与决定系数是本页对所载序列做的最小二乘回归，自变量是成交合约数的环比变动，样本是窗口内五十三次环比。成交合约数由公司披露的 ADV 与交易日相乘得到。斜率可以用核对抽屉里的量价表复算。本页不把它当作预测模型，它只说明历史上量与收入的振幅关系，任何一个季度都可能偏离。",
            "有效税率序列里 2017 年第四季度那一格是美国税改一次性重估递延所得税负债的结果，与经营无关。本页把它留在图上并在图注里说明，而不是剔除，因为剔除之后那条线看起来会像一条平稳的税率而它不是。",
            "本页不发布市场一致预期、评级、目标价与估值，也不发布任何竞争对手的成交量或市占率。竞品的量取自对手方自己的季报，合约口径与本页的合约张数不可比。",
            "本页只发布公司披露值、可复算的简单派生值；D 标记代表 Derived / 自算。",
            "核对抽屉最后那张「AI capex 循环」是全站共用的跨页对照块，在每一页都逐字节相同，不是对 CME 的判断。它追的是四家云厂现金资本开支到 NVDA 数据中心收入再到 TSM 晶圆这条链，CME 不在这条链的任何一环上。把它放在这里是为了让读者在任意一页都能查到同一份上下游对照。它在折叠的抽屉里，不参与本页的论证。",
            "本页已知未接入：全年调整后营业费用指引（电话会口径，无申报出处）、日均保证金效率（只以「超过」的形式出现，无逐季序列与定义）、未平仓合约的绝对值（申报文件只有同比百分比）、事件合约与预测市场的成交与收入（两季口径基数不同，不能连成序列）、成交场所拆分、非美成交量占比（同样只在电话会与新闻稿正文里以单点形式出现），以及 2026 年第三季度之后的任何数据（本页数据截至 2026-07-24 的申报）。",
            "业绩电话会文字稿仅链接官方 IR 与 SEC 托管版本，公开仓不复制原件或逐字内容。",
        ],
        "footer": "CME quarterly results · 数据来自 CME Group 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "cme.js"), payload, "cme")
    shell_dir = ROOT / "cme"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("CME", "cme"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"CME page: {charts} charts in {len(payload['sections'])} sections "
          f"+ {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
