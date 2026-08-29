#!/usr/bin/env python3
"""Build the Samsung Electronics quarterly-results page.

Same four-part, chart-led shape as the other pages (上季兑现 → 本季重点 →
下季跟踪 → 长期常规), but the first section has to be built differently here,
because Samsung guides almost nothing a reader would expect.

Two facts drive the whole layout:

1. **Samsung is not an SEC registrant.** Every other page in this repo can be
   traced to EDGAR -- even Ferrari, through its 6-K exhibits. Samsung cannot:
   CIK 0000879316 holds 251 filings that are all beneficial-ownership and
   tender-offer forms, the newest from 2015. There is no 20-F, no 6-K, no
   F-1. The numbers here come from the company's own quarterly Earnings
   Release and from DART, and the two are used as independent readings of each
   other rather than as one source quoted twice.

2. **The company guides the quantity, not the price.** The only forward number
   management gives is next quarter's DRAM and NAND bit shipment growth, and
   even that is a phrase rather than a figure. Average selling price -- which
   is what actually moved earnings this cycle -- is described only in
   retrospect and never guided. So section one is not "did it beat its
   revenue guidance"; it is the narrower,真实 question: the one thing it
   guides, does it hit, and does hitting it explain anything.

Everything in the payload is a Samsung-disclosed figure, a DART-disclosed
figure, or arithmetic reproducible from the audit tables and marked D.
Currency is Korean won throughout; nothing is converted to dollars, because
Samsung publishes no dollar figures and a conversion would put a number on the
page that no filing contains -- and, this cycle, would fold a 6.7% year-on-year
won depreciation into every growth rate the page is trying to read.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import (  # noqa: E402
    ai_capex_cycle_table,
    delivery_band,
    headroom_exhibit,
    number_exhibits,
    threshold_exhibit,
    threshold_table,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "samsung.json"
DATA_DIR = ROOT / "data"

# Days in each reported quarter, used only for the two working-capital ratios.
# Written out rather than derived so the leap-year question is answered once,
# in the open: none of the eight quarters here sits in a leap February.
QUARTER_DAYS = [92, 92, 90, 91, 92, 92, 90, 91]


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100


def compact_period(period: str) -> str:
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


def rounded(values: list[float | None], digits: int = 6) -> list[float | None]:
    """Round for the payload so a rebuild is idempotent, keeping ``None`` holes."""
    return [None if value is None else round(value, digits) for value in values]


def resolve_exhibit_refs(exhibits: list[dict]) -> list[dict]:
    """Substitute ``{ref}`` placeholders with the numbers `number_exhibits` assigned.

    Cross-references written as literal numbers break the moment a chart is
    inserted, so captions that point at an exhibit follow the same rule the
    exhibits themselves do.
    """
    numbers = {exhibit["ref"]: exhibit["n"] for exhibit in exhibits if exhibit.get("ref")}
    for exhibit in exhibits:
        exhibit.pop("ref", None)
        for field in ("title", "note", "src_extra", "annot"):
            text = exhibit.get(field)
            if not isinstance(text, str):
                continue
            for key, number in numbers.items():
                text = text.replace("{" + key + "}", str(number))
            exhibit[field] = text
    return exhibits


# ── Sources reused across several captions ────────────────────────────────────
SRC_DECK = (
    "来自公司每季自行发布的 Earnings Release（IR 网站英文版）四页财务附录："
    "Appendix 1 合并损益表、Appendix 2 分部经营实绩、Appendix 3 资产负债表、"
    "Appendix 4 现金流量表。"
)
SRC_DART = (
    "来自 DART 电子公告的「연결재무제표 기준 영업(잠정)실적(공정공시)」，"
    "与公司 Earnings Release 互为独立读数：八个季度的合并营业收入与营业利润两边逐季吻合。"
)
SRC_CALL = "来自该季电话会英文逐字稿，措辞照抄，未改词序。"

# The segment footnote is the single most load-bearing caveat on this page and
# gets repeated wherever a segment number is drawn, because a reader who lands
# on one chart cannot see the others' captions.
SEG_FOOTNOTE = (
    "公司分部表的脚注原文：「the sales of business units include intersegment sales」，"
    "所以<b>四个分部收入之和大于合并收入</b>，差额是分部间抵销；"
    "而<b>分部营业利润侧没有抵销</b>，可以直接加总。"
)


def derived(staging: dict) -> dict:
    """Every number the charts need that is not a disclosed line item.

    Kept in one place so the audit tables and the charts cannot drift: each
    table below prints the same list the chart above it plots.
    """
    fin = staging["financials_krw_bn"]
    rev_tn = [value / 1000 for value in fin["revenue"]]
    cogs_tn = [value / 1000 for value in fin["cost_of_sales"]]
    seg_rev = staging["segment_revenue_krw_tn"]
    seg_op = staging["segment_operating_profit_krw_tn"]
    cash = staging["cash_flow_krw_tn"]
    bs = staging["balance_sheet_krw_bn"]

    segment_sum = [
        seg_rev["dx"][i] + seg_rev["ds"][i] + seg_rev["sdc"][i] + seg_rev["harman"][i]
        for i in range(len(rev_tn))
    ]
    return {
        "revenue_tn": rev_tn,
        "cogs_tn": cogs_tn,
        "gross_margin": [g / r * 100 for g, r in zip(fin["gross_profit"], fin["revenue"])],
        "operating_margin": [o / r * 100 for o, r in zip(fin["operating_profit"], fin["revenue"])],
        "net_margin": [n / r * 100 for n, r in zip(fin["profit_owners"], fin["revenue"])],
        "effective_tax": [t / p * 100 for t, p in zip(fin["income_tax"], fin["profit_before_tax"])],
        "memory_share": [m / r * 100 for m, r in zip(seg_rev["memory"], rev_tn)],
        "ds_non_memory": [d - m for d, m in zip(seg_rev["ds"], seg_rev["memory"])],
        "segment_sum": segment_sum,
        "elimination": [s - r for s, r in zip(segment_sum, rev_tn)],
        "elimination_share": [(s - r) / r * 100 for s, r in zip(segment_sum, rev_tn)],
        "dx_margin": [o / r * 100 for o, r in zip(seg_op["dx"], seg_rev["dx"])],
        "ds_margin": [o / r * 100 for o, r in zip(seg_op["ds"], seg_rev["ds"])],
        "sdc_margin": [o / r * 100 for o, r in zip(seg_op["sdc"], seg_rev["sdc"])],
        "fcf": [c - k for c, k in zip(cash["operating"], cash["capex_ppe"])],
        "capex_to_cfo": [k / c * 100 for k, c in zip(cash["capex_ppe"], cash["operating"])],
        "inventory_days": [
            bs["inventories"][i] / 1000 / cogs_tn[i] * QUARTER_DAYS[i] for i in range(len(rev_tn))
        ],
        "receivable_days": [
            bs["receivables"][i] / 1000 / rev_tn[i] * QUARTER_DAYS[i] for i in range(len(rev_tn))
        ],
        "rnd_intensity": [d / r * 100 for d, r in zip(fin["rnd_expenses"], fin["revenue"])],
        "net_cash_to_assets": [
            n * 1000 / a * 100 for n, a in zip(staging["net_cash_krw_tn"], bs["total_assets"])
        ],
    }


# ── Section 1: what the company actually guided ───────────────────────────────
def bit_delivery_charts(staging: dict) -> list[dict]:
    """The only guided number Samsung publishes, and the number that mattered.

    The pairing is the point. The bit-shipment band is the whole of the
    company's forward disclosure, and it is hit every time; the price line
    beside it, which the company never guides, is what moved earnings by an
    order of magnitude. A page that showed only the first would report a
    company in complete control of its own outlook.
    """
    bits = staging["memory_bit_and_price"]
    quarters = bits["quarters"]
    labels = [compact_period(q) for q in quarters]
    guide = bits["next_quarter_guide"]

    # Q4'25 is deliberately absent from this chart: the guidance that set it was
    # given on the 3Q25 call, whose transcript this page does not hold. Drawing
    # it with a zero-width band at zero would put a shape on the chart that
    # stands for "no data", which is exactly the confusion a band chart cannot
    # survive. The quarter still appears in the price chart and the audit table,
    # where "本页未取得该季指引原文" can be written out in words.
    guided = [i for i, low in enumerate(bits["dram_bit_guide_low"]) if low is not None]
    band_labels = [labels[i] for i in guided] + [compact_period(guide["quarter"])]
    dram = delivery_band(
        "EX_BIT", "DRAM 出货 bit 环比", band_labels,
        [bits["dram_bit_guide_low"][i] for i in guided] + [guide["dram_low"]],
        [bits["dram_bit_guide_high"][i] for i in guided] + [guide["dram_high"]],
        [bits["dram_bit_actual"][i] for i in guided] + [None],
        fmt="pct1", ylab="环比 %", unit="%",
        src_extra=(
            SRC_CALL
            + "区间与实际都是本页对公司定性措辞的数值化读数 D，公司本身从未给过数字："
            "low single digit=1–4%、mid-single digit=4–7%、high single digit=7–10%、"
            "single digit=1–10%、low teens=10–13%；实际值取该措辞区间的中点。"
            "对照表见数据核对抽屉。"
        ),
        extra_note=(
            "<b>Q4'25 不在这张图上</b>：给出它的是 3Q25 电话会，本页没有那份逐字稿，"
            "只有该季公司自述「consistent with our bit growth guidance from the previous quarter」。"
            "宁可让那一格缺席，也不画一条代表「没有数据」的零宽区间。"
        ),
    )

    price = {
        "ref": "EX_ASP",
        "kind": "grouped_bars",
        "title": (
            "同期公司自述的环比 ASP：DRAM "
            + "、".join(f"{v:+.0f}%" for v in bits["dram_asp_qoq_pct"])
            + " —— 公司对价格从不给指引"
        ),
        "xlabels": labels,
        "groups": [
            {"name": "DRAM 环比 ASP", "color": "NAVY", "values": rounded(bits["dram_asp_qoq_pct"])},
            {"name": "NAND 环比 ASP", "color": "GOLD", "values": rounded(bits["nand_asp_qoq_pct"])},
        ],
        "bar_labels": True,
        "fmt": "pct0",
        "label_fmt": "pct0",
        "ylab": "环比 %",
        "note": (
            "把这张图和 Exhibit {EX_BIT} 并排看：公司唯一指引的<b>量</b>，三季全部达标或超标，"
            "环比幅度个位数到十几个百分点；公司从不指引的<b>价</b>，同期环比 25% 到 91%。"
            "<b>本轮业绩不是由被指引的那个变量决定的</b> —— 这也是为什么这一页没有「收入指引兑现」"
            "那类图：三星不提供收入、毛利率或营业利润的数字指引，一条都没有。"
            "柱高是公司措辞的数值化 D：「about 40%」取 40、「mid-40%」取 45、"
            "「low 90% range」取 91、「high 80%」取 88、「high 60%」取 65、「mid-20%」取 25。"
        ),
        "src_extra": SRC_CALL + "逐季原话见数据核对抽屉的量价对照表。",
    }

    prov = staging["provisional_vs_final"]
    gap = [
        f - p
        for f, p in zip(prov["final_operating_profit_krw_tn"], prov["flash_operating_profit_krw_tn"])
    ]
    provisional = {
        "ref": "EX_PROV",
        "kind": "diverging_bars",
        "title": (
            f"速报数到确定数的营业利润修正：有记录的 {len(gap)} 季全部为正，"
            f"幅度 {min(gap):+.2f}～{max(gap):+.2f} 兆韩元"
        ),
        "xlabels": [compact_period(q) for q in prov["quarters"]],
        "values": rounded(gap, 2),
        "legend": "确定数 − 速报数",
        "positive_label": "确定数更高",
        "negative_label": "确定数更低",
        "fmt": "f2",
        "yfmt": "f2",
        "label_fmt": "f2",
        "ylab": "兆韩元",
        "zero_line": True,
        "note": (
            "三星每季披露两次：季末后 1–2 周先发速报（잠정실적，只给营业收入与营业利润），"
            "月末再发完整财报。这张图量的是两次之间营业利润被改动了多少。"
            "<b>只画营业利润，不画收入</b>：速报的收入按兆韩元<b>取整</b>发布（86 / 93 / 133 / 171），"
            "所以收入那一栏的「差额」几乎全是取整而不是修正，画出来会是一张读者会误读的图。"
            f"<b>{len(gap)} 季不足以支撑「总是上修」这个结论</b>，只够说明这四次都没有下修 —— "
            "更早的季度本页没有拿到速报公告原文，缺口写在口径说明里。"
        ),
        "src_extra": SRC_DART + "速报与确定数的发布日期逐季列在数据核对抽屉里。",
    }
    return [dram, price, provisional]


# ── Section 2: the quarter ────────────────────────────────────────────────────
def quarter_charts(staging: dict, der: dict, labels: list[str]) -> list[dict]:
    fin = staging["financials_krw_bn"]
    seg_rev = staging["segment_revenue_krw_tn"]
    seg_op = staging["segment_operating_profit_krw_tn"]

    headline_chart = {
        "ref": "EX_TOP",
        "kind": "bar_line_dual",
        "title": (
            f"合并收入 {der['revenue_tn'][-1]:.1f} 兆韩元、营业利润率 {der['operating_margin'][-1]:.1f}%"
            f"（八季前为 {der['operating_margin'][0]:.1f}%）"
        ),
        "xlabels": labels,
        "bar": {"name": "合并收入（兆韩元）", "color": "NAVY",
                "values": rounded(der["revenue_tn"], 2), "yfmt": "f1"},
        "line": {"name": "营业利润率", "color": "GOLD",
                 "values": rounded(der["operating_margin"], 2), "yfmt": "pct0"},
        "ylab": "兆韩元",
        "ylab2": "营业利润率",
        "yfmt": "f0",
        "note": (
            f"收入两年翻了一倍多（{der['revenue_tn'][0]:.1f} → {der['revenue_tn'][-1]:.1f} 兆韩元），"
            f"但营业利润率从 {der['operating_margin'][0]:.1f}% 走到 {der['operating_margin'][-1]:.1f}%，"
            "是收入倍数的好几倍 —— 这一轮的增量几乎不带成本，拆解见 Exhibit {EX_BRIDGE}。"
            "本页全部以韩元列示，不折美元。"
        ),
        "src_extra": SRC_DECK + SRC_DART,
    }

    mix_chart = {
        "ref": "EX_MIX",
        "kind": "stacked_dual",
        "title": (
            f"分部收入结构：Memory 占合并收入从 {der['memory_share'][0]:.1f}% 升到 "
            f"{der['memory_share'][-1]:.1f}%"
        ),
        "xlabels": labels,
        "stacks": [
            {"name": "DS（半导体）", "color": "NAVY", "values": rounded(seg_rev["ds"], 1)},
            {"name": "DX（手机与家电）", "color": "BLUE", "values": rounded(seg_rev["dx"], 1)},
            {"name": "SDC（显示）", "color": "MBLUE", "values": rounded(seg_rev["sdc"], 1)},
            {"name": "Harman", "color": "GRAY", "values": rounded(seg_rev["harman"], 1)},
        ],
        # 右轴上界必须显式给：渲染器在没有 ymax 时把上界写死在 60，
        # 而 Memory 占比本季已经 70.4%，越界的线会被画到负 y、被浏览器裁掉，
        # 而图例照常写着它，且坐标全是合法有限数字，只查 NaN 的断言看不见。
        "line": {"name": "Memory 占合并收入", "color": "GOLD",
                 "values": rounded(der["memory_share"], 1), "yfmt": "pct0", "ymax": 100},
        "ylab2": "Memory 占合并收入",
        "note": (
            "堆叠的是四个分部的收入，" + SEG_FOOTNOTE
            + f"所以柱高（本季 {der['segment_sum'][-1]:.1f}）高于合并收入"
            f"（{der['revenue_tn'][-1]:.1f}），差额 {der['elimination'][-1]:.1f} 兆韩元见 "
            "Exhibit {EX_ELIM}。金色线的分母是<b>合并</b>收入，不是柱高。"
        ),
        "src_extra": SRC_DECK,
    }

    op_chart = {
        "ref": "EX_SEGOP",
        "kind": "grouped_bars",
        "title": (
            f"分部营业利润：DS 从 {seg_op['ds'][3]:.1f} 走到 {seg_op['ds'][-1]:.1f} 兆韩元，"
            f"同一季 DX 转为 {seg_op['dx'][-1]:.1f}"
        ),
        "xlabels": labels,
        "groups": [
            {"name": "DS（半导体）", "color": "NAVY", "values": rounded(seg_op["ds"], 2)},
            {"name": "DX（手机与家电）", "color": "BLUE", "values": rounded(seg_op["dx"], 2)},
            {"name": "SDC（显示）", "color": "MBLUE", "values": rounded(seg_op["sdc"], 2)},
            {"name": "Harman", "color": "GRAY", "values": rounded(seg_op["harman"], 2)},
        ],
        "bar_labels": False,
        "fmt": "f1",
        "label_fmt": "f1",
        "ylab": "兆韩元",
        "note": (
            "<b>本季最该看的一格是 DX 那根负柱</b>：八季里唯一一次分部亏损，公司给的原因是"
            "「Operating results declined due to rising component costs」—— 推高它成本的正是"
            "自家 DS 卖出的存储。集团内部同时坐在这轮涨价的两边，一边赚的比另一边亏的多两个数量级，"
            "但对手机业务而言这是真实的利润损失，管理层预期压力延续至下半年。"
            + SEG_FOOTNOTE + "分部营业利润逐季加总与合并数的差在 ±0.1 兆韩元以内，见核对表。"
        ),
        "src_extra": SRC_DECK,
    }

    margin_chart = {
        "ref": "EX_MARGIN",
        "kind": "lines",
        "title": (
            f"三条利润率：毛利率 {der['gross_margin'][-1]:.1f}%、"
            f"营业利润率 {der['operating_margin'][-1]:.1f}%、归母净利率 {der['net_margin'][-1]:.1f}%"
        ),
        "xlabels": labels,
        "series": [
            {"name": "毛利率", "values": rounded(der["gross_margin"], 2), "color": "NAVY"},
            {"name": "营业利润率", "values": rounded(der["operating_margin"], 2), "color": "BLUE"},
            {"name": "归母净利率", "values": rounded(der["net_margin"], 2), "color": "GOLD"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "zero_base": True,
        "ylab": "占收入 %",
        "note": (
            "三条线的间距在收窄：毛利率与营业利润率之间是费用率，"
            f"本季 {der['gross_margin'][-1] - der['operating_margin'][-1]:.1f}pp，"
            f"八季前是 {der['gross_margin'][0] - der['operating_margin'][0]:.1f}pp。"
            "营业利润率与净利率之间反而拉开，主因是有效税率从 2.1% 升到 "
            f"{der['effective_tax'][-1]:.1f}%（见 Exhibit {{EX_HEADROOM}} 的阈值列表）。"
            "纵轴自 0 起，没有截轴。"
        ),
        "src_extra": SRC_DECK + SRC_DART + "三条比率均为各利润行除以合并收入 D。",
    }

    delta_rev = der["revenue_tn"][-1] - der["revenue_tn"][-2]
    delta_cogs = der["cogs_tn"][-1] - der["cogs_tn"][-2]
    delta_sga = (fin["sga_expenses"][-1] - fin["sga_expenses"][-2]) / 1000
    delta_op = (fin["operating_profit"][-1] - fin["operating_profit"][-2]) / 1000
    bridge_chart = {
        "ref": "EX_BRIDGE",
        "kind": "grouped_bars",
        "title": (
            f"本季环比增量拆解：收入 +{delta_rev:.1f} 兆韩元，销货成本只 +{delta_cogs:.1f}，"
            f"增量毛利率 {(delta_rev - delta_cogs) / delta_rev * 100:.1f}%"
        ),
        "xlabels": ["合并收入", "销货成本", "销管费用（含 R&D）", "营业利润"],
        "groups": [{
            "name": "2026Q2 较 2026Q1 的绝对变动",
            "color": "NAVY",
            "values": rounded([delta_rev, delta_cogs, delta_sga, delta_op], 2),
        }],
        "bar_labels": True,
        "fmt": "f1",
        "label_fmt": "f1",
        "ylab": "兆韩元",
        "note": (
            f"这是本季度最反常的一格：收入环比多了 {delta_rev:.1f} 兆韩元，而销货成本只多了 "
            f"{delta_cogs:.1f} —— <b>增量里 {(delta_rev - delta_cogs) / delta_rev * 100:.1f}% 直接落进毛利</b>。"
            "存储涨价不需要多投一片晶圆，这是价格驱动周期与产量驱动周期在报表上的分界线。"
            f"销管费用同期 +{delta_sga:.1f}，其中含公司口径为「上半年累计营业利润的 10.5%」的"
            "特别绩效奖金一次性补提（1Q26 零计提）；公司未拆分其中多少被资本化进在产品存货，"
            "所以这根柱不是纯费用增长。四根柱不是瀑布图，不相互加总。"
        ),
        "src_extra": SRC_DECK + "四项均为公司披露值的相邻两季算术差 D；奖金口径来自 2Q26 电话会 CFO 原话。",
    }

    memory_chart = {
        "ref": "EX_NONMEM",
        "kind": "lines",
        "title": (
            f"Memory 收入 {seg_rev['memory'][0]:.1f} → {seg_rev['memory'][-1]:.1f} 兆韩元，"
            f"DS 里的非存储部分八季一直卡在 {min(der['ds_non_memory']):.1f}–{max(der['ds_non_memory']):.1f}"
        ),
        "xlabels": labels,
        "series": [
            {"name": "Memory 收入", "values": rounded(seg_rev["memory"], 1), "color": "NAVY"},
            {"name": "DS 减 Memory（System LSI + Foundry）D",
             "values": rounded(der["ds_non_memory"], 1), "color": "GOLD"},
        ],
        "fmt": "f1",
        "yfmt": "f0",
        "label_fmt": "f1",
        "end_label": True,
        "zero_base": True,
        "ylab": "兆韩元",
        "note": (
            "<b>金色那条线是本页唯一能说明代工与非存储芯片的数字，而它是减出来的。</b>"
            "公司在 DS 之下只披露 Memory 一行收入，System LSI 与 Foundry 的收入、利润"
            "<b>一个季度都没有单独披露过</b>，Memory 自己的营业利润也没有。"
            "所以市面上「代工亏损 X 兆」这类数字全部是卖方估计，不是公司口径，本页不采用。"
            "另有一层失真：Foundry 为自家 HBM 生产 base die 的收入计入 Foundry 再在合并时抵销，"
            "所以这条残值线含内部收入，绝对水平不精确 —— 它能说明的只有一件事："
            "八季来它没有增长，DS 的全部增量都是存储。"
        ),
        "src_extra": SRC_DECK + "残值 = 披露的 DS 收入减披露的 Memory 收入 D。",
    }
    return [headline_chart, mix_chart, op_chart, margin_chart, bridge_chart, memory_chart]


# ── Section 3: thresholds ─────────────────────────────────────────────────────
def tracking_charts(staging: dict, der: dict, labels: list[str]) -> list[dict]:
    entries = staging["next_kpi"]["entries"]
    headroom = headroom_exhibit(
        "距阈值余量：八条跟踪线里 "
        f"{sum(1 for e in entries if (e['current'] - e['threshold']) * (1 if e['direction'] == 'up' else -1) < 0)}"
        " 条已经越过",
        entries, "current",
        note=(
            "阈值是<b>本地研究设定</b>，不是公司指引 —— 三星不提供收入、毛利率或营业利润的数字指引，"
            "所以这一节没有可兑现的公司承诺可用。正值代表仍在安全侧；口径统一为「距阈值百分之多少」，"
            "好让百分比、天数这些不同单位的线并排可读。原始单位的阈值与当前值见核对表。"
            "每条线为什么选这个阈值，写在同一张表的最后一列。"
        ),
        src_extra=SRC_DECK + "当前值全部由公司披露值算出 D，算式见八季核对表。",
    )
    headroom["ref"] = "EX_HEADROOM"

    opm = threshold_exhibit(
        f"合并营业利润率对 35% 的阈值：本季 {der['operating_margin'][-1]:.1f}%",
        labels, rounded(der["operating_margin"], 2), 35.0,
        fmt="pct1", ylab="营业利润率",
        actual_name="合并营业利润率", threshold_name="阈值 35%",
        note=(
            "选 35% 不是因为它是某个共识，而是因为它把「涨价减速」和「周期翻转」分开："
            "卖方对 3Q26 存储混合 ASP 的假设落在 +12% 到 +20% 之间，<b>没有一家假设转负</b>，"
            "而公司自己对 3Q ASP 一个字都没给。若真跌破 35%，说明减速的假设本身错了。"
            "八季里这条线从 8.4% 的谷底走到 52.2%，本季是窗口内最高。"
        ),
        src_extra=SRC_DECK + "阈值为本地设定；实际值 = 合并营业利润 ÷ 合并收入 D。",
    )
    opm["ref"] = "EX_OPM"

    dx = threshold_exhibit(
        f"DX 分部营业利润率对 1% 的阈值：本季 {der['dx_margin'][-1]:.2f}%，八季首次为负",
        labels, rounded(der["dx_margin"], 2), 1.0,
        fmt="pct1", ylab="DX 营业利润率",
        actual_name="DX 分部营业利润率", threshold_name="阈值 1%",
        note=(
            "这条线是集团内部矛盾的温度计：DX 买存储，DS 卖存储，两者在同一张合并报表里。"
            f"本季 DX 营业利润 {staging['segment_operating_profit_krw_tn']['dx'][-1]:.1f} 兆韩元，"
            "是八季唯一的负值。阈值取 1% 而不是 0，是因为「距零阈值的百分比余量」在算术上没有定义。"
            "管理层对下半年的说法是 <b>we expect that soft burden to continue</b>，"
            "并预期全年手机出货下降 —— 也就是说这条线在公司自己的预期里还会往下。"
        ),
        src_extra=SRC_DECK + "实际值 = DX 分部营业利润 ÷ DX 分部收入（含分部间销售）D。",
    )
    dx["ref"] = "EX_DX"
    return [headroom, opm, dx]


# ── Section 4: the routine series ─────────────────────────────────────────────
def routine_charts(staging: dict, der: dict, labels: list[str]) -> list[dict]:
    cash = staging["cash_flow_krw_tn"]
    fin = staging["financials_krw_bn"]

    cash_chart = {
        "ref": "EX_CASH",
        "kind": "lines",
        "title": (
            f"经营现金流 {cash['operating'][-1]:.1f} 兆韩元，自由现金流 {der['fcf'][-1]:.1f}，"
            f"而现金资本开支 {cash['capex_ppe'][-1]:.1f} 与八季前几乎一样"
        ),
        "xlabels": labels,
        "series": [
            {"name": "经营现金流", "values": rounded(cash["operating"], 2), "color": "NAVY"},
            {"name": "自由现金流 D", "values": rounded(der["fcf"], 2), "color": "GOLD"},
            {"name": "现金资本开支（购置 PP&E）", "values": rounded(cash["capex_ppe"], 2), "color": "MBLUE"},
            {"name": "折旧", "values": rounded(cash["depreciation"], 2), "color": "GRAY"},
        ],
        "fmt": "f1",
        "yfmt": "f0",
        "label_fmt": "f1",
        "end_label": True,
        "zero_base": True,
        "ylab": "兆韩元",
        "note": (
            "<b>这张图最该注意的是那条几乎水平的浅蓝线。</b>八个季度里经营现金流从 22.2 涨到 105.1 兆韩元，"
            "现金资本开支却在 10.8–17.1 之间横着走，本季甚至环比下降 3.0。"
            "公司在电话会上给的口径与此相反 —— IR 口径的应计资本开支本季 16.8 兆韩元、环比 <b>+5.5</b>，"
            "现金流量表的购置 PP&E 却是环比 <b>−3.0</b>。<b>两个口径同时由公司给出，方向相反，公司没有作调节。</b>"
            "本页画的是现金流量表那一条，因为它是八季都有、口径一致的那条；"
            "但读者不该由此得出「资本开支在降」的结论。"
        ),
        "src_extra": SRC_DECK + "自由现金流 = 经营现金流 − 购置 PP&E D，不是公司定义的指标；应计口径来自电话会。",
    }

    net_cash_chart = {
        "ref": "EX_NETCASH",
        "kind": "bar_line_dual",
        "title": (
            f"净现金 {staging['net_cash_krw_tn'][-1]:.1f} 兆韩元，一个季度增加 "
            f"{staging['net_cash_krw_tn'][-1] - staging['net_cash_krw_tn'][-2]:.1f}"
        ),
        "xlabels": labels,
        "bar": {"name": "净现金（现金及等价物减有息负债）", "color": "NAVY",
                "values": rounded(staging["net_cash_krw_tn"], 2), "yfmt": "f1"},
        "line": {"name": "净现金 / 总资产", "color": "GOLD",
                 "values": rounded(der["net_cash_to_assets"], 2), "yfmt": "pct0"},
        "ylab": "兆韩元",
        "ylab2": "净现金 / 总资产",
        "yfmt": "f0",
        "note": (
            "净现金是公司自己在资产负债表页给出的行（Cash − Debts，其中 Cash 含短期金融工具），"
            "不是本页算的。八季前它是 86.8 兆韩元、占总资产 17.7%，本季 167.6 兆韩元、占 22.1%。"
            "注意这个分母也在膨胀：总资产同期从 491 兆涨到 759 兆韩元，"
            "所以占比的上升比绝对额的上升温和得多。"
        ),
        "src_extra": SRC_DECK + "占比为净现金除以总资产 D。",
    }

    days_chart = {
        "ref": "EX_DAYS",
        "kind": "lines",
        "title": (
            f"库存天数 {der['inventory_days'][-1]:.0f} 天、应收天数 {der['receivable_days'][-1]:.0f} 天，"
            "两条同时在涨"
        ),
        "xlabels": labels,
        "series": [
            {"name": "库存天数 D", "values": rounded(der["inventory_days"], 1), "color": "NAVY"},
            {"name": "应收天数 D", "values": rounded(der["receivable_days"], 1), "color": "GOLD"},
        ],
        "fmt": "f0",
        "yfmt": "f0",
        "label_fmt": "f0",
        "end_label": True,
        "zero_base": True,
        "ylab": "天",
        "note": (
            "在一个公司自称缺货的季度里库存天数从 101 天涨到 124 天，值得停一下。"
            "两个解释都被公司自己的披露支持，且公司没有拆分："
            "一是特别绩效奖金中被<b>资本化进在产品存货</b>的部分（CFO 说从 3Q 起随销售结转），"
            "二是存储涨价同时抬高了在产品的账面单价。"
            "分母用当季销货成本、按实际日历天数年化 D。"
        ),
        "src_extra": SRC_DECK + "库存与应收为资产负债表披露值；天数为本页自算 D。",
    }

    elim_chart = {
        "ref": "EX_ELIM",
        "kind": "bar_line_dual",
        "title": (
            f"分部间抵销额从 {der['elimination'][0]:.1f} 涨到 {der['elimination'][-1]:.1f} 兆韩元，"
            f"但占合并收入始终在 {min(der['elimination_share']):.1f}%–{max(der['elimination_share']):.1f}% 之间"
        ),
        "xlabels": labels,
        "bar": {"name": "分部间抵销额 D", "color": "NAVY",
                "values": rounded(der["elimination"], 2), "yfmt": "f1"},
        "line": {"name": "占合并收入", "color": "GOLD",
                 "values": rounded(der["elimination_share"], 2), "yfmt": "pct0"},
        "ylab": "兆韩元",
        "ylab2": "占合并收入",
        "yfmt": "f0",
        "note": (
            "<b>这一整张图都是减出来的：公司的分部表里没有抵销这一行。</b>"
            + SEG_FOOTNOTE
            + "所以抵销额 = 四个分部收入之和 − 合并收入，是本页的算术，不是三星披露的数字。"
            "绝对额两年翻了一倍多，而占合并收入的比例一直待在一条窄带里 —— "
            "这说明内部供货的<b>物量</b>没有暴增，是内部转移价随存储价格一起被抬高了。"
            "（最后这句是本页的判断，不是公司说法。）"
        ),
        "src_extra": SRC_DECK + "抵销额与占比均为本页自算 D。",
    }

    rnd_chart = {
        "ref": "EX_RND",
        "kind": "bar_line_dual",
        "title": (
            f"研发支出 {fin['rnd_expenses'][-1] / 1000:.1f} 兆韩元创季度新高，"
            f"但占收入降到 {der['rnd_intensity'][-1]:.1f}%"
        ),
        "xlabels": labels,
        "bar": {"name": "研发支出（销管费用之内）", "color": "NAVY",
                "values": rounded([v / 1000 for v in fin["rnd_expenses"]], 2), "yfmt": "f1"},
        "line": {"name": "研发 / 收入", "color": "GOLD",
                 "values": rounded(der["rnd_intensity"], 2), "yfmt": "pct0"},
        "ylab": "兆韩元",
        "ylab2": "研发 / 收入",
        "yfmt": "f0",
        "note": (
            "两条线方向相反，是这一页反复出现的同一件事：分子在涨，分母涨得更快。"
            f"研发支出本季 {fin['rnd_expenses'][-1] / 1000:.1f} 兆韩元、环比 "
            f"{pct_change(fin['rnd_expenses'][-1], fin['rnd_expenses'][-2]):+.0f}%，是季度历史新高；"
            f"但研发强度从八季前的 {der['rnd_intensity'][0]:.1f}% 降到 {der['rnd_intensity'][-1]:.1f}%。"
            "研发列在销管费用之内，不是单独的报表行。"
        ),
        "src_extra": SRC_DECK + SRC_DART + "研发强度为研发支出除以合并收入 D。",
    }
    return [cash_chart, net_cash_chart, days_chart, elim_chart, rnd_chart]


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    labels = [compact_period(period) for period in periods]
    der = derived(staging)
    fin = staging["financials_krw_bn"]
    seg_rev = staging["segment_revenue_krw_tn"]
    seg_op = staging["segment_operating_profit_krw_tn"]
    cash = staging["cash_flow_krw_tn"]
    bits = staging["memory_bit_and_price"]
    prov = staging["provisional_vs_final"]

    settled_ex = bit_delivery_charts(staging)
    highlight_ex = quarter_charts(staging, der, labels)
    next_ex = tracking_charts(staging, der, labels)
    routine_ex = routine_charts(staging, der, labels)
    resolve_exhibit_refs(
        number_exhibits(settled_ex + highlight_ex + next_ex + routine_ex)
    )

    # ── audit tables ──────────────────────────────────────────────────────────
    income_rows = [
        [
            periods[i],
            f"{der['revenue_tn'][i]:,.2f}",
            f"{fin['gross_profit'][i] / 1000:,.2f}",
            f"{fin['operating_profit'][i] / 1000:,.2f}",
            f"{fin['profit_owners'][i] / 1000:,.2f}",
            f"{fin['eps_krw'][i]:,}",
            f"{der['operating_margin'][i]:.1f}%",
        ]
        for i in range(len(periods))
    ]
    segment_rev_rows = [
        [
            periods[i],
            f"{seg_rev['ds'][i]:.1f}",
            f"{seg_rev['memory'][i]:.1f}",
            f"{der['ds_non_memory'][i]:.1f}",
            f"{seg_rev['dx'][i]:.1f}",
            f"{seg_rev['sdc'][i]:.1f}",
            f"{seg_rev['harman'][i]:.1f}",
            f"{der['segment_sum'][i]:.1f}",
            f"{der['elimination'][i]:.1f}",
        ]
        for i in range(len(periods))
    ]
    segment_op_rows = [
        [
            periods[i],
            f"{seg_op['ds'][i]:.2f}",
            f"{seg_op['dx'][i]:.2f}",
            f"{seg_op['sdc'][i]:.2f}",
            f"{seg_op['harman'][i]:.2f}",
            f"{seg_op['ds'][i] + seg_op['dx'][i] + seg_op['sdc'][i] + seg_op['harman'][i]:.2f}",
            f"{fin['operating_profit'][i] / 1000:.2f}",
            f"{fin['operating_profit'][i] / 1000 - (seg_op['ds'][i] + seg_op['dx'][i] + seg_op['sdc'][i] + seg_op['harman'][i]):+.2f}",
        ]
        for i in range(len(periods))
    ]
    cash_rows = [
        [
            periods[i],
            f"{cash['operating'][i]:.2f}",
            f"{cash['capex_ppe'][i]:.2f}",
            f"{der['fcf'][i]:.2f}",
            f"{cash['depreciation'][i]:.2f}",
            f"{staging['net_cash_krw_tn'][i]:.2f}",
            f"{der['inventory_days'][i]:.0f} 天",
            f"{der['receivable_days'][i]:.0f} 天",
        ]
        for i in range(len(periods))
    ]
    provisional_rows = [
        [
            prov["quarters"][i],
            prov["flash_date"][i],
            f"{prov['flash_revenue_krw_tn'][i]:.2f}",
            f"{prov['flash_operating_profit_krw_tn'][i]:.2f}",
            prov["final_date"][i],
            f"{prov['final_revenue_krw_tn'][i]:.2f}",
            f"{prov['final_operating_profit_krw_tn'][i]:.2f}",
            f"{prov['final_operating_profit_krw_tn'][i] - prov['flash_operating_profit_krw_tn'][i]:+.2f}",
        ]
        for i in range(len(prov["quarters"]))
    ]
    bit_rows = [
        [
            bits["quarters"][i],
            bits["dram_bit_guide_wording"][i] or "本页未取得该季指引原文",
            bits["dram_bit_actual_wording"][i],
            bits["dram_asp_qoq_wording"][i],
            bits["nand_bit_actual_wording"][i],
            bits["nand_asp_qoq_wording"][i],
        ]
        for i in range(len(bits["quarters"]))
    ]
    guidance_rows = [
        [item["metric"], item["wording"], item["quantified"]]
        for item in staging["guidance"]["items"]
    ]
    threshold_entries = staging["next_kpi"]["entries"]
    threshold = threshold_table(
        7, "下季跟踪阈值与当前值（原始单位）", threshold_entries, "current", "本季值",
    )
    threshold["headers"] = threshold["headers"] + ["为什么是这条线"]
    threshold["rows"] = [
        row + [entry["why"]] for row, entry in zip(threshold["rows"], threshold_entries)
    ]

    tables = [
        {"n": 1, "title": "八季合并损益（兆韩元，EPS 为韩元）",
         "headers": ["期间", "合并收入", "毛利", "营业利润", "归母净利", "基本 EPS", "营业利润率 D"],
         "rows": income_rows},
        {"n": 2, "title": "八季分部收入（兆韩元，含分部间销售）",
         "headers": ["期间", "DS", "其中 Memory", "DS 减 Memory D", "DX", "SDC", "Harman",
                     "四分部合计 D", "抵销额 D"],
         "rows": segment_rev_rows},
        {"n": 3, "title": "八季分部营业利润与加总校验（兆韩元）",
         "headers": ["期间", "DS", "DX", "SDC", "Harman", "分部合计 D", "合并营业利润", "差额 D"],
         "rows": segment_op_rows},
        {"n": 4, "title": "八季现金流与营运资金（兆韩元）",
         "headers": ["期间", "经营现金流", "现金 CapEx", "自由现金流 D", "折旧", "净现金",
                     "库存天数 D", "应收天数 D"],
         "rows": cash_rows},
        {"n": 5, "title": "速报（잠정）与确定数对照（兆韩元）",
         "headers": ["期间", "速报日", "速报收入", "速报营业利润", "确定日", "确定收入",
                     "确定营业利润", "营业利润修正 D"],
         "rows": provisional_rows},
        {"n": 6, "title": "存储量价：公司逐季原话（英文照抄）",
         "headers": ["期间", "上季给出的 DRAM bit 指引", "该季 DRAM bit 实际",
                     "该季 DRAM ASP", "该季 NAND bit 实际", "该季 NAND ASP"],
         "rows": bit_rows},
        threshold,
        {"n": 8, "title": "公司对 3Q 2026 与全年给出的全部前瞻（原话）",
         "headers": ["项目", "公司原话", "可数字化的部分"],
         "rows": guidance_rows},
        ai_capex_cycle_table(9),
    ]

    memory_share = der["memory_share"][-1]
    return {
        "schema_version": "quarterly-dashboard/samsung-v1",
        "page": {"slug": "samsung", "language": "zh-CN"},
        "company": {
            "ticker": "005930.KS",
            "name": "Samsung Electronics Co., Ltd.",
            "group": "semiconductor_ai",
            "accounting_standard": "K-IFRS",
        },
        "latest": {
            "disclosed_period_label": "Q2 2026",
            "full_financial_period_label": "Q2 2026",
            "period_end": "2026-06-30",
            "release_date": "2026-07-30",
            "analysis_date": "2026-08-29",
            "audit_status": "unaudited",
            "status": "history_ready",
        },
        "tracker": "Watchlist Quarterly Tracker · 005930.KS",
        "title": "Samsung Electronics（005930.KS）：Q2 2026 季报仪表盘",
        "subtitle": (
            "截至 2026-06-30 · 发布 2026-07-30 · K-IFRS 合并 · 外部审阅前的初步数 · "
            "全部以韩元列示，不折美元"
        ),
        "headline": (
            f"合并收入 {der['revenue_tn'][-1]:.1f} 兆韩元、营业利润 "
            f"{fin['operating_profit'][-1] / 1000:.1f} 兆韩元，营业利润率 "
            f"{der['operating_margin'][-1]:.1f}%；环比增量里 "
            f"{(der['revenue_tn'][-1] - der['revenue_tn'][-2] - der['cogs_tn'][-1] + der['cogs_tn'][-2]) / (der['revenue_tn'][-1] - der['revenue_tn'][-2]) * 100:.0f}% "
            f"直接落进毛利；Memory 已占合并收入 {memory_share:.1f}%，而同一季 DX 分部录得八季首次营业亏损 "
            f"{seg_op['dx'][-1]:.1f} 兆韩元 —— 集团同时坐在这轮存储涨价的两边。"
        ),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>亮点</span><b>增量几乎不带成本</b>'
            f'<p>收入环比 +{der["revenue_tn"][-1] - der["revenue_tn"][-2]:.1f} 兆韩元，'
            f'销货成本只 +{der["cogs_tn"][-1] - der["cogs_tn"][-2]:.1f}，增量毛利率近 100%。</p></article>'
            '<article><span>结构</span><b>集团已经是一家存储公司</b>'
            f'<p>Memory 占合并收入 {memory_share:.1f}%（八季前 {der["memory_share"][0]:.1f}%）；'
            'DS 里的非存储部分八季没有增长。</p></article>'
            '<article><span>存疑</span><b>公司指引的是量，决定业绩的是价</b>'
            '<p>唯一前瞻数字是下季 bit 出货的定性区间；对 ASP 一个字都不给。</p></article>'
            '</div>'
        ),
        "source": (
            'Source: <a href="https://www.samsung.com/global/ir/financial-information/earnings-release/" '
            'rel="noopener">Samsung Electronics Investor Relations</a>'
            '（2Q 2026 Earnings Release 与电话会）与 '
            '<a href="https://dart.fss.or.kr/dsab007/main.do" rel="noopener">DART 电子公告</a>。'
            '三星不是 SEC 注册人，本页没有任何 EDGAR 来源。'
        ),
        "source_url": "https://www.samsung.com/global/ir/financial-information/earnings-release/",
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {
                "id": "settled",
                "title": "一、公司到底指引了什么，兑现了吗",
                "description": (
                    "三星不提供收入、毛利率或营业利润的数字指引，所以这一节不是常规的指引兑现。"
                    "公司唯一给的前瞻数字是下一季 DRAM 与 NAND 的出货 bit 增速，而且是定性措辞；"
                    "价格只在事后回顾时说。三张图分别是：这条唯一的指引兑现得怎么样、"
                    "同期没有被指引的价格走了多少、以及季末速报数到月末确定数之间被改动了多少。"
                ),
                "exhibits": settled_ex,
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": (
                    "收入与利润率、分部结构、增量的成本构成，以及 DS 之下那条唯一披露的 Memory 收入线。"
                ),
                "exhibits": highlight_ex,
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": "当前值离阈值还有多远，统一用「距阈值余量」口径；阈值为本地设定，不是公司指引。",
                "exhibits": next_ex,
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": "现金流与资本强度、净现金、营运资金、分部间抵销与研发强度。",
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "三星电子不是 SEC 注册人。EDGAR 上 CIK 0000879316 名下 251 份申报全部是 SC 13D/13G、SC 14D1/14D9、Form 3/4 这类持股与要约表格，最新一份停在 2015-01-20，没有 20-F、没有 6-K、没有 F-1。本页因此没有任何 EDGAR 来源，全部数据来自公司自行发布的季度 Earnings Release 与 DART 电子公告，两者互为独立读数。",
            "全页以韩元列示，不折算美元。三星本身不发布美元财务数字，折算会在页面上制造一个任何申报里都不存在的数；而 2026Q2 韩元兑美元季度均价较去年同期贬值 6.7%，折算还会把汇率腿混进本页真正想读的价格周期里。公司自己披露的汇率影响是：2026Q2 美元走强对营业利润的环比正向影响约 3.1 兆韩元。",
            "合并损益按十亿韩元记录、分部与现金流按公司披露的兆韩元记录，两套精度不同是因为公司本身用两种精度发布，本页不做统一。",
            "分部收入含分部间销售，四个分部之和大于合并收入；分部营业利润侧没有抵销，可以直接加总，逐季加总与合并数的差在 ±0.1 兆韩元以内。抵销额一行公司没有披露，本页由减法得出并标注 D。",
            "公司在 DS 之下只披露 Memory 一行收入。Memory 的营业利润、System LSI 与 Foundry 的收入和利润、DRAM 与 NAND 的分别口径、HBM 的收入与占比，八个季度一次都没有披露过。页面上出现的「DS 减 Memory」是减法残值，且含 Foundry 为自家 HBM 生产 base die 的内部收入，绝对水平不精确。",
            "第一节 bit 出货图的区间与实际值，是本页对公司定性措辞的数值化读数，公司从未给过数字：low single digit 记 1–4%、mid-single digit 记 4–7%、high single digit 记 7–10%、single digit 记 1–10%、low teens 记 10–13%，实际值取所述措辞区间的中点。原话逐季列在核对表里，读者可以自行改用别的映射。",
            "速报与确定数的对照只有四个季度，因为更早季度的速报公告原文本页没有取得。四季全部为正上修，但四个观测不足以支撑「总是上修」这一结论。速报的营业收入按兆韩元取整发布，所以收入两次之间的差主要是取整而非修正，本页因此只对营业利润作图。",
            "第三节的阈值是本地研究设定，不是公司指引，也不构成评级或投资建议；「距阈值余量」统一为正值代表安全侧。DX 分部那条阈值取 1% 而不是 0，是因为距零阈值的百分比余量在算术上没有定义。",
            "本季销管费用含公司口径为「上半年累计营业利润的 10.5%」的特别绩效奖金一次性补提，1Q26 为零计提，两季费用基数因此不可比。公司未拆分其中被资本化进在产品存货、递延至下半年的金额，本页也不估算。",
            "资本开支存在两个口径且方向相反：公司电话会给的应计口径本季 16.8 兆韩元、环比 +5.5，现金流量表的购置 PP&E 为 14.11 兆韩元、环比 −3.0。公司没有提供两者的调节。本页图上画的是现金流量表口径，因为它八季齐全且定义一致。",
            "三星每季披露两次，且两次在 DART 上都标注为「잠정」（暂定），因为完整财报同样发布于外部审阅完成之前。本页 release_date 取月末完整财报日，不取季末速报日。",
            "本页只发布公司披露值、可复算的简单派生值，以及明确标注为卖方估计的第三方数字；D 标记代表 Derived / 自算。市面上流传的 Foundry 亏损额、HBM 收入、DRAM 与 NAND 分别收入均为卖方估计，本页不予采用。",
            "本页已知未接入：HBM 的任何量化序列（公司不披露）、DRAM 与 NAND 的分别收入、智能手机出货量的完整八季序列（仅个别季度在电话会上给过绝对数）、地区与客户结构、股份回购的完整八季序列（现金流量表该行只在部分季度的简报中单列）、以及 2024Q3 之前的历史。",
            "电话会文字稿仅链接公司官方 IR 托管版本，公开仓不复制原件或逐字全文；页面内引用的英文原话为逐字短句引用。",
        ],
        "footer": "Samsung Electronics quarterly results · 数据来自公司公开披露、DART 公告与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "samsung.js"), payload, "samsung")
    shell_dir = ROOT / "samsung"
    shell_dir.mkdir(exist_ok=True)
    # Rendered here, not at import: the shell stamps the payload's content hash
    # into its <script src>, so it has to be built after write_dash.
    (shell_dir / "index.html").write_text(
        render_shell("005930.KS", "samsung"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(
        f"Samsung page: {charts} charts in {len(payload['sections'])} sections "
        f"+ {len(payload['tables'])} audit tables"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
