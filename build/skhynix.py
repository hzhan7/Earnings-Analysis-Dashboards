"""SK hynix quarterly dashboard.

SK hynix publishes no financial guidance at all. Not a revenue range, not a
margin, not an earnings-per-share number, not even an annual one -- the other
pages on this site that guide only costs, or only the full year, are still
guiding a *number*. What SK hynix publishes instead is the pair of physical
quantities whose product is revenue, bit shipments and average selling price,
and it publishes them **as English adjectives**: "Mid-60% Increase", "Flat",
"Slight Decrease", "Over 70% Increase".

That is not a press-release informality. The thirteen-quarter table this page's
first section is built on comes out of the Form 424B4 registration statement
filed for the July 2026 Nasdaq listing -- the document where a company has the
strongest possible reason to be precise. In the same filing, revenue is reported
to the million won. So the precision is total on the output and absent on both
inputs.

The first section therefore cannot settle what every other first section here
settles. There is no range to hit and no number to hit it with. What it can
settle is how much the words leave undetermined, and the answer is the finding:
across 52 phrase readings the band a careful reader must allow averages 3.2
percentage points and reaches 10, four of the phrases are one-sided with no
upper bound at all, and when four quarters of them are chained the permitted
range for a single year's DRAM revenue growth spans tens of points. The company
then reports the answer to nine significant figures.

Two consequences run through the rest of the page. Because the guided variable
is volume and the unguided one is price, a quarter can land its shipment
guidance exactly and still miss on revenue -- which is what happened in the
quarter this page reports. And because the average selling price is quoted in
US dollars while revenue is reported in won, any bit-times-price bridge against
won revenue carries an unstated exchange-rate term; a bridge that closes without
one has absorbed the currency into a residual and called it mix.

Published numbers are company-reported or transparent arithmetic. Thresholds in
section three are local research settings, not company guidance.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import (  # noqa: E402
    ai_capex_cycle_table,
    headroom_exhibit,
    number_exhibits,
    threshold_exhibit,
    threshold_table,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "skhynix.json"
DATA_DIR = ROOT / "data"

# Twenty-two quarters on one axis: a tick a year keeps the labels readable.
LONG_STEP = 4


def rounded(values, digits: int = 4):
    return [None if v is None else round(v, digits) for v in values]


def tn(values):
    """Won billions as printed -> trillions, the unit the company itself quotes."""
    return [None if v is None else round(v / 1000.0, 4) for v in values]


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100.0


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


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


def margin_series(op: list[float], rev: list[float]) -> list[float]:
    """Operating margin computed from the two won amounts, not the printed integer.

    The company prints an integer. Rounding to one costs up to half a point, and
    a quarter-on-quarter step built from two rounded integers can be a full point
    out -- 2025Q2 to 2025Q3 reads as +6pp from the printed 41 and 47, and as
    +5.1pp from the amounts. The printed integers are kept in the audit table so
    both are visible.
    """
    return [round(o / r * 100.0, 4) for o, r in zip(op, rev)]


def phrase_band_exhibit(ref: str, title: str, quarters: list[str], block: dict,
                        note: str, src_extra: str) -> dict:
    """The band a phrase permits, quarter by quarter, with no actual to compare.

    Every other band on this site draws a guided range and lays the reported
    number on top of it. Here there is no reported number: the outcome is
    published in the same vocabulary as the guidance, so the diamond that would
    settle the quarter does not exist. Drawing the band alone, with an empty
    actual series, is the honest picture -- the chart shows exactly what the
    filing determines and nothing more.
    """
    return {
        "ref": ref,
        "kind": "range_band",
        "title": title,
        "xlabels": list(quarters),
        "xrot": 90,
        "lo": list(block["low_pct"]),
        "hi": list(block["high_pct"]),
        "actual": [None] * len(quarters),
        "actual_color": "NAVY",
        "names": {
            "range": "用词允许的区间",
            "actual": "公司披露的数值",
            "lo": "区间下限（%）",
            "hi": "区间上限（%）",
        },
        "fmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "环比 %",
        "zero_line": True,
        "note": note,
        "src_extra": src_extra,
    }


def build_payload(staging: dict) -> dict:
    fin = staging["financials_krw_bn"]
    ann = staging["annual_audited_krw_bn"]
    prod = staging["revenue_by_product_krw_bn"]
    cust = staging["customer_concentration"]
    kpi = staging["kpi_phrases"]
    below = staging["q2_2026_below_operating_profit_krw_bn"]
    restate = staging["restatement_2022q4"]

    periods = staging["periods"]
    revenue = fin["revenue"]
    op = fin["operating_profit"]
    net = fin["net_income"]
    opm = margin_series(op, revenue)
    netm = [None if n is None else round(n / r * 100.0, 4)
            for n, r in zip(net, revenue)]

    kq = kpi["quarters"]
    dram_bit, dram_asp = kpi["dram_bit_shipment"], kpi["dram_asp"]
    nand_bit, nand_asp = kpi["nand_bit_shipment"], kpi["nand_asp"]

    widths = [h - l
              for blk in (dram_bit, dram_asp, nand_bit, nand_asp)
              for l, h in zip(blk["low_pct"], blk["high_pct"])]
    mean_width = sum(widths) / len(widths)
    one_sided = sum(sum(blk["one_sided"])
                    for blk in (dram_bit, dram_asp, nand_bit, nand_asp))

    # ── section one: a record written in adjectives ─────────────────────────
    settled = []

    settled.append(phrase_band_exhibit(
        "EX_DASP",
        (f"DRAM 平均售价的环比，全部以英文用词发布：{len(kq)} 个季度、"
         f"没有一个数字"),
        kq, dram_asp,
        note=(
            "色块是<b>用词允许的区间</b>，不是公司给的区间 —— 公司一个数字都没给。"
            "本页把每个用词读成一个闭区间（例如 “Mid-60% Increase” 读成 63–67%），"
            "映射规则一次性写死在数据文件里、对四条序列一视同仁。"
            "<b>没有菱形，是因为没有可以放上去的数。</b>本站其他页的第一节画的是"
            "「公司给的区间」对「随后报出来的实际值」；这一页两边是同一种用词，"
            "所以能结清的只有「用词留下多少不确定」。"
            f"四条序列 {len(widths)} 次读数里，区间平均宽 {mean_width:.1f} 个百分点，"
            f"最宽 {max(widths):.0f} 个百分点。"),
        src_extra=("Form 424B4「changes in our bit sales volumes and average selling "
                   "prices (in U.S. dollars) of our DRAMs」表；区间为本页读法（D）。"),
    ))

    settled.append(phrase_band_exhibit(
        "EX_NASP",
        (f"NAND 平均售价的环比：{one_sided} 次读数是单边的，"
         "“Over 70% Increase” 没有上限"),
        kq, nand_asp,
        note=(
            "四条序列里有四次用的是 “Over X% Increase”，<b>在申报文件里没有上界</b>。"
            "画出来必须给一个上界，本页统一取「下限 + 10 个百分点」，"
            "<b>这个上界是画图约定，不是披露</b>，图上最宽的几格就是它。"
            "一个下界式的说法与一个区间不是同一种信息：对着下界，"
            "「没有低于」几乎是同义反复。"),
        src_extra=("Form 424B4 同一节的 NAND 表；单边用词的上界为本页约定（D）。"),
    ))

    settled.append({
        "ref": "EX_DRIVER",
        "kind": "grouped_bars",
        "title": ("DRAM 的量与价，各自的环比中值：动的是价，"
                  "而价是公司唯一不指引的那个"),
        "xlabels": list(kq),
        "xrot": 90,
        "groups": [
            {"name": "出货量环比（用词中值）", "color": "NAVY",
             "values": rounded(dram_bit["midpoint_pct"])},
            {"name": "平均售价环比（用词中值，美元计）", "color": "GOLD",
             "values": rounded(dram_asp["midpoint_pct"])},
        ],
        "bar_labels": False,
        "fmt": "pct1", "label_fmt": "pct1", "ylab": "环比 %",
        "zero_line": True,
        "note": (
            "<b>这张图是这一页的因果链。</b>公司每季给的下季指引只覆盖出货量，"
            "而把两根柱子放在一起就能看到：出货量的中值多数季度在正负十个点以内，"
            "售价却能一季走出六十多个点。"
            "所以<b>指引全部兑现、收入仍然不及预期，在结构上是可能的</b> —— "
            "被指引的那个变量本来就不是决定收入的那个。"
            f"2026 年第一季就是极端形态：出货量用词是 “Flat”，售价用词是 “Mid-60% Increase”。"),
        "src_extra": "Form 424B4 的两张 DRAM 表；中值为区间中点（D）。",
    })

    settled.append({
        "ref": "EX_NDRIVER",
        "kind": "grouped_bars",
        "title": "NAND 的量与价：同一形态，且价的摆幅更大",
        "xlabels": list(kq),
        "xrot": 90,
        "groups": [
            {"name": "出货量环比（用词中值）", "color": "NAVY",
             "values": rounded(nand_bit["midpoint_pct"])},
            {"name": "平均售价环比（用词中值，美元计）", "color": "GOLD",
             "values": rounded(nand_asp["midpoint_pct"])},
        ],
        "bar_labels": False,
        "fmt": "pct1", "label_fmt": "pct1", "ylab": "环比 %",
        "zero_line": True,
        "note": (
            "闪存这条线上量与价都比 DRAM 摆得更凶，"
            "两次单边用词（“Over 70% Increase” 的出货、“Over 40% Increase” 的售价）都在这里。"
            "把两张图对读还有一层：<b>DRAM 与 NAND 的价格拐点不同步</b>，"
            "而公司只在年度层面披露两者的收入占比，"
            "所以「这一季的合并售价里有多少来自哪一边」在季度上无法还原，见 Exhibit {EX_MIX}。"),
        "src_extra": "Form 424B4 的两张 NAND 表；中值为区间中点（D）。",
    })

    # The chained band: what four quarters of words permit, against the one
    # disclosed answer. This is the only place the vocabulary can be scored.
    def chain(block_bit, block_asp, start, stop, bound):
        product = 1.0
        for i in range(start, stop):
            product *= (1 + block_bit[bound][i] / 100.0)
            product *= (1 + block_asp[bound][i] / 100.0)
        return (product - 1) * 100.0

    i0, i1 = kq.index("2Q 2025"), kq.index("1Q 2026") + 1
    dram_lo = chain(dram_bit, dram_asp, i0, i1, "low_pct")
    dram_hi = chain(dram_bit, dram_asp, i0, i1, "high_pct")
    nand_lo = chain(nand_bit, nand_asp, i0, i1, "low_pct")
    nand_hi = chain(nand_bit, nand_asp, i0, i1, "high_pct")
    dram_mid = chain(dram_bit, dram_asp, i0, i1, "midpoint_pct")
    nand_mid = chain(nand_bit, nand_asp, i0, i1, "midpoint_pct")
    dram_actual = pct_change(prod["dram"][4], prod["dram"][3])
    nand_actual = pct_change(prod["nand"][4], prod["nand"][3])

    settled.append({
        "ref": "EX_CHAIN",
        "kind": "grouped_bars",
        "title": ("把四个季度的用词连乘，再对上公司唯一披露的那个答案："
                  f"DRAM 用词允许 {dram_lo:.0f}–{dram_hi:.0f}%，实际 {dram_actual:.0f}%"),
        "xlabels": ["DRAM", "NAND"],
        "groups": [
            {"name": "四季用词连乘的下限", "color": "BLUE",
             "values": [round(dram_lo, 2), round(nand_lo, 2)]},
            {"name": "四季用词连乘的上限", "color": "MBLUE",
             "values": [round(dram_hi, 2), round(nand_hi, 2)]},
            {"name": "公司披露的同比实际（韩元收入）", "color": "NAVY",
             "values": [round(dram_actual, 2), round(nand_actual, 2)]},
        ],
        "bar_labels": True,
        "fmt": "pct1", "label_fmt": "pct1", "ylab": "同比 %",
        "note": (
            "2025 年第二季到 2026 年第一季四个季度的出货量与售价用词逐季连乘，"
            "得到用词允许的收入增长区间；深色柱是公司在审计报表里披露的"
            "同期分产品收入同比。"
            "<b>实际值确实落在区间内 —— 但这不构成一次验证。</b>"
            f"DRAM 那一格的区间宽 {dram_hi - dram_lo:.0f} 个百分点"
            f"（{dram_lo:.0f}% 到 {dram_hi:.0f}%），"
            "一个这么宽的区间几乎不可能被证伪，落在里面因此接近同义反复。"
            f"用中值连乘会得到 {dram_mid:.0f}%，比实际的 {dram_actual:.0f}% 高出 "
            f"{dram_mid - dram_actual:.0f} 个百分点 —— "
            "<b>这就是用中值代替区间的代价，而它整个被区间的宽度吞掉了。</b>"
            "还有一层同样被吞掉：售价用词以<b>美元</b>计，收入以<b>韩元</b>报告，"
            "两者之间隔着一个申报文件没有给的汇率项。"
            "在一个几十个百分点宽的区间里，几个百分点的汇率影响根本无从分辨 —— "
            "所以任何把美元售价乘上出货量、再声称与韩元收入「闭合」的桥，"
            "闭合的其实是区间的宽度，不是数据。"),
        "src_extra": ("用词取自 Form 424B4 的四张表；实际同比取自同一份文件的"
                      "分产品收入披露（note 24(2) 与中期报表）。连乘与同比为本页自算（D）。"),
    })

    # ── section two: the quarter ────────────────────────────────────────────
    highlights = []

    highlights.append({
        "ref": "EX_REV",
        "kind": "bar_line_dual",
        "title": (f"{len(periods)} 季营收与营业利润率："
                  f"本季营收 ₩{revenue[-1] / 1000:.1f}T、营业利润率 {opm[-1]:.1f}%"),
        "xlabels": list(periods),
        "xrot": 90,
        "bar": {"name": "营业收入（₩万亿）", "color": "BLUE",
                "values": tn(revenue), "yfmt": "f0"},
        "line": {"name": "营业利润率（右轴）", "color": "RED",
                 "values": rounded(opm, 2), "yfmt": "pct0"},
        "fmt": "f1", "label_fmt": "f1",
        "ylab": "₩万亿", "ylab2": "营业利润率 %",
        "note": (
            "整个窗口横跨一次完整的存储周期：2023 年第一季营业利润率 −66.9%，"
            f"2026 年第二季 {opm[-1]:.1f}%。"
            "<b>利润率这条线的形状比营收那排柱子更值得看</b> —— "
            "它在 2023 年触底、2024 年回正、然后在五个季度里从 23% 走到 76%，"
            "而这段路上公司对外指引的只有出货量。"
            "右轴按数据自算，负值段没有被截掉。"),
        "src_extra": ("各季业绩发布；利润率为营业利润 ÷ 营业收入（D），"
                      "公司披露的是四舍五入到整数的百分比，见核对表。"),
    })

    highlights.append({
        "ref": "EX_BELOW",
        "kind": "grouped_bars",
        "title": (f"营业利润、税前利润、净利润：本季税前比营业多出 "
                  f"₩{(below['profit_before_tax'][1] - below['operating_profit'][1]) / 1000:.1f}T，"
                  "而季度发布里对此一个字都没有"),
        "xlabels": ["2026Q1", "2026Q2"],
        "groups": [
            {"name": "营业利润", "color": "NAVY",
             "values": tn(below["operating_profit"])},
            {"name": "税前利润", "color": "GOLD",
             "values": tn(below["profit_before_tax"])},
            {"name": "净利润", "color": "BLUE",
             "values": tn(below["net_income"])},
        ],
        "bar_labels": True,
        "fmt": "f1", "label_fmt": "f1", "ylab": "₩万亿",
        "note": (
            "<b>净利润高过营业收入</b>：本季营收 ₩79.3T、净利 ₩93.9T，净利率 118%。"
            "差额来自营业利润以下。税前减营业利润 = "
            f"₩{(below['profit_before_tax'][1] - below['operating_profit'][1]) / 1000:.2f}T 的营业外净收益，"
            "是上一季同一算法的 "
            f"{(below['profit_before_tax'][1] - below['operating_profit'][1]) / (below['profit_before_tax'][0] - below['operating_profit'][0]):.1f} 倍；"
            "税前减净利 = "
            f"₩{(below['profit_before_tax'][1] - below['net_income'][1]) / 1000:.2f}T 的所得税，"
            f"有效税率 {(below['profit_before_tax'][1] - below['net_income'][1]) / below['profit_before_tax'][1] * 100:.1f}%。"
            "<b>这三个数都是两条已印出来的行相减，不是估计。</b>"
            "但税前那一行只出现在向 SEC 报送的 6-K 里 —— "
            "公司自己的季度业绩发布只印到净利润为止，"
            "对这笔占税前一半的营业外收益没有任何拆分或说明。"
            "本页因此不发布它的构成，也不发布任何「剔除一次性后的净利润」。"),
        "src_extra": ("Form 6-K（2026-07-29）的 Preliminary Results 表；"
                      "税负、营业外净额与有效税率为两行相减（D）。"),
    })

    highlights.append({
        "ref": "EX_MARGIN",
        "kind": "lines",
        "title": (f"营业利润率与净利率：本季净利率 {netm[-1]:.0f}%，"
                  "是会计口径而不是经营口径"),
        "xlabels": list(periods),
        "series": [
            {"name": "营业利润率", "values": rounded(opm, 2), "color": "NAVY"},
            {"name": "净利率", "values": rounded(netm, 2), "color": "GOLD"},
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1",
        "end_label": True, "zero_line": True,
        "ylab": "%", "xstep": LONG_STEP,
        "note": (
            "两条线在整个窗口里贴得很近，只有最后一格劈开：净利率跨过 100%。"
            "<b>一家制造业公司的净利率高于 100%，说明这一季的利润多数不是卖东西赚的</b>，"
            "见 Exhibit {EX_BELOW}。"
            "跨季比较净利润在这一格失效，营业利润仍然可比。"
            "2021 年第四季没有画点：公司那一期只印了当季营收与营业利润，"
            "没有印当季净利润，本页不用「全年减三季」补这个洞。"),
        "src_extra": "各季业绩发布；两条率均为本页自算（D）。",
    })

    highlights.append({
        "ref": "EX_MIX",
        "kind": "grouped_bars",
        "title": (f"分产品收入只有年度披露：DRAM 占比从 {prod['dram_pct'][0]:.1f}% "
                  f"升到 {prod['dram_pct'][2]:.1f}%"),
        "xlabels": ["FY2023", "FY2024", "FY2025"],
        "groups": [
            {"name": "DRAM", "color": "NAVY", "values": tn(prod["dram"][:3])},
            {"name": "NAND 闪存", "color": "BLUE", "values": tn(prod["nand"][:3])},
            {"name": "其他产品", "color": "GOLD", "values": tn(prod["other"][:3])},
        ],
        "bar_labels": True,
        "fmt": "f1", "label_fmt": "f1", "ylab": "₩万亿",
        "note": (
            "<b>这是公司披露的分产品收入，不是估算。</b>"
            "它是审计报表附注里的口径，三年相加逐年等于合并收入。"
            "但它<b>只有年度</b>（外加第一季度）—— "
            "季度上没有分产品收入，所以「本季 DRAM 与闪存各贡献多少」"
            "在公开披露里不存在，任何按季拆分都是外部假设。"
            "另有一条更硬的边界写在同一份申报文件里：公司称其决策层"
            "不接收任何组成部分的分部财务信息，因此财务报表中不含分部信息，"
            "只有单一报告分部。"),
        "src_extra": "Form 424B4 note 24(2) 与中期报表分产品附注；审计值。",
    })

    highlights.append({
        "ref": "EX_CUST",
        "kind": "grouped_bars",
        "title": (f"单一最大客户占收入：FY2023 不足 10%，FY2025 已到 "
                  f"{cust['largest_customer_pct'][2]:.1f}%"),
        "xlabels": list(cust["years"]),
        "groups": [
            {"name": "最大单一客户收入（₩万亿）", "color": "NAVY",
             "values": tn(cust["largest_customer_krw_bn"])},
        ],
        "line": {"name": "占合并收入比例（右轴）", "color": "RED",
                 "values": rounded(cust["largest_customer_pct"], 2),
                 "yfmt": "pct0"},
        "bar_labels": True,
        "fmt": "f1", "label_fmt": "f1",
        "ylab": "₩万亿", "ylab2": "占收入 %",
        "note": (
            "<b>这是这一页上信息量最高的一个披露，而它一年只出现一次。</b>"
            "审计报表附注按规则要求列示占收入 10% 以上的客户："
            "FY2023 没有任何单一客户达到 10%，FY2024 是 16.5%，FY2025 是 23.9%。"
            "两年之内，公司从「没有一个客户重要到需要披露」变成"
            "「近四分之一的收入来自一个客户」。"
            "FY2023 那一格没有柱子，是因为当年没有需要披露的客户，"
            "不是数据缺失。附注不点名。"),
        "src_extra": "Form 424B4 note 4(2)；审计值，客户名称未披露。",
    })

    # ── section three: what to watch ────────────────────────────────────────
    nonop_share = ((below["profit_before_tax"][1] - below["operating_profit"][1])
                   / below["profit_before_tax"][1] * 100.0)
    capex_intensity = ann["capital_expenditures"][2] / ann["revenue"][2] * 100.0
    net_cash = staging["balance_sheet_krw_bn"]["net_cash"][-1] / 1000.0

    watch = [
        {"metric": "营业利润率", "direction": "up", "threshold": 55.0,
         "unit": "pct", "current": round(opm[-1], 1)},
        {"metric": "资本开支占收入", "direction": "down", "threshold": 35.0,
         "unit": "pct", "current": round(capex_intensity, 1)},
        {"metric": "单一最大客户占收入", "direction": "down", "threshold": 30.0,
         "unit": "pct", "current": cust["largest_customer_pct"][2]},
        {"metric": "DRAM 占收入", "direction": "down", "threshold": 85.0,
         "unit": "pct", "current": prod["dram_pct"][2]},
        {"metric": "营业外净收益占税前利润", "direction": "down", "threshold": 10.0,
         "unit": "pct", "current": round(nonop_share, 1)},
        {"metric": "净现金", "direction": "up", "threshold": 20.0,
         "unit": "krw_tn", "current": round(net_cash, 1)},
    ]

    next_ex = [headroom_exhibit(
        f"下季 {len(watch)} 条阈值：当前值离阈值的余量",
        watch, "current",
        ("正值表示仍在安全侧。阈值为本地研究设定，<b>不是公司指引</b> —— "
         "SK hynix 不发布任何财务指引，连年度的都没有，"
         "它对外给的唯一前瞻数字是下一季的出货量，而且是用英文用词给的，见第一节。"
         "六条里有三条一年只更新一次（资本强度、客户集中度、DRAM 占比），"
         "因为它们的来源是年度审计附注。"),
        "当前值为最近一期披露值；阈值为本地研究设定。")]

    next_ex.append(threshold_exhibit(
        f"营业利润率：当前 {opm[-1]:.1f}%，阈值 55.0%",
        list(periods), rounded(opm, 2), 55.0,
        fmt="pct1", ylab="%",
        actual_name="营业利润率", threshold_name="本地阈值",
        note=("红线是本地研究设定的阈值，不是公司指引，也不是公司披露的目标。"
              "窗口里这条线两次穿过阈值：2022 年下行时向下穿，2026 年上行时向上穿。"
              "把阈值设在 55% 的理由是它高于本轮之前的任何一个季度，"
              "所以跌回它以下就等于本轮的超额利润已经消失。"),
        src_extra="各季业绩发布；利润率为自算（D），阈值为本地研究设定。"))
    next_ex[-1]["xstep"] = LONG_STEP
    next_ex[-1]["xrot"] = 90

    # ── section four: the long routine series ───────────────────────────────
    years = ann["years"]
    fcf = [o - c for o, c in zip(ann["operating_cash_flow"],
                                 ann["capital_expenditures"])]
    intensity = [round(c / r * 100.0, 2)
                 for c, r in zip(ann["capital_expenditures"], ann["revenue"])]
    da_share = [round(d / r * 100.0, 2)
                for d, r in zip(ann["depreciation_and_amortization"], ann["revenue"])]

    routine = [
        {
            "ref": "EX_CAPEX",
            "kind": "grouped_bars",
            "title": (f"经营现金流、资本开支与自由现金流：FY2025 资本强度 "
                      f"{intensity[2]:.1f}%，不是腰斩"),
            "xlabels": list(years),
            "groups": [
                {"name": "经营现金流", "color": "NAVY",
                 "values": tn(ann["operating_cash_flow"])},
                {"name": "资本开支", "color": "GOLD",
                 "values": tn(ann["capital_expenditures"])},
                {"name": "自由现金流", "color": "BLUE", "values": tn(fcf)},
            ],
            "bar_labels": True,
            "fmt": "f1", "label_fmt": "f1", "ylab": "₩万亿",
            "zero_line": True,
            "line": {"name": "资本开支占收入（右轴）", "color": "RED",
                     "values": intensity, "yfmt": "pct0"},
            "ylab2": "占收入 %",
            "note": (
                "资本开支的口径是申报文件自己写的：购置不动产、厂房及设备的现金流出，"
                "不含无形资产，与本页附录里那张跨页对照表对四家云厂用的是同一个口径。"
                f"三年的资本强度是 {intensity[0]:.1f}%、{intensity[1]:.1f}%、{intensity[2]:.1f}% —— "
                "<b>大体持平，最近一年还略微上行。</b>"
                "自由现金流 = 经营现金流 − 资本开支，三年逐年成立。"),
            "src_extra": ("Form 424B4 现金流量表摘要；资本强度与自由现金流为自算（D），"
                          "两个输入取自同一份文件的同一组期间列。"),
        },
        {
            "ref": "EX_DA",
            "kind": "bar_line_dual",
            "title": (f"折旧摊销几乎没动，占收入却从 {da_share[0]:.1f}% 掉到 "
                      f"{da_share[2]:.1f}%"),
            "xlabels": list(years),
            "bar": {"name": "折旧与摊销（₩万亿）", "color": "BLUE",
                    "values": tn(ann["depreciation_and_amortization"]),
                    "yfmt": "f0"},
            "line": {"name": "占收入比例（右轴）", "color": "RED",
                     "values": da_share, "yfmt": "pct0"},
            "fmt": "f1", "label_fmt": "f1",
            "ylab": "₩万亿", "ylab2": "占收入 %",
            "note": (
                "三年里折旧摊销的绝对额几乎是一条直线（₩13.6T → ₩12.5T → ₩13.9T），"
                "而收入涨了近两倍，所以它占收入的比例掉到三分之一。"
                "<b>本轮利润率扩张里有一部分来自这个分母效应，而不是单位成本下降</b> —— "
                "折旧基数没变，被暴涨的收入摊薄了。"
                "反过来也成立：收入回落时这条线会机械性抬升。"),
            "src_extra": "Form 424B4 的调整后 EBITDA 调节表；占比为自算（D）。",
        },
        {
            "ref": "EX_RESTATE",
            "kind": "grouped_bars",
            "title": ("2022 年第四季被重述过一次：营业利润与净利润各下调 "
                      "₩211bn，而收入只动了 ₩27bn"),
            "xlabels": ["营业收入", "营业利润", "净利润"],
            "groups": [
                {"name": "当期首次发布", "color": "NAVY",
                 "values": [restate["as_first_reported"]["revenue"],
                            restate["as_first_reported"]["operating_profit"],
                            restate["as_first_reported"]["net_income"]]},
                {"name": "一年后对照列", "color": "GOLD",
                 "values": [restate["as_restated"]["revenue"],
                            restate["as_restated"]["operating_profit"],
                            restate["as_restated"]["net_income"]]},
            ],
            "bar_labels": True,
            "fmt": "f0c", "label_fmt": "f0c", "ylab": "₩十亿",
            "zero_line": True,
            "note": (
                "<b>这是窗口里唯一一次重述，画出来是为了说明本页 22 季序列用的是哪一版。</b>"
                "公司在 2023 年 1 月发布的 2022 年第四季，与一年后 2023 年第四季发布中"
                "作为对照列印出来的同一个季度，不是同一组数。"
                "营业利润与净利润的下调完全相等（各 ₩211bn），收入只下调 ₩27bn —— "
                "这是一笔走营业费用、且没有产生税盾的调整在一个本就巨亏的季度里的形状。"
                "<b>本页序列用「当期首次发布」那一版</b>，因为只有这一版能让 2022 年"
                "四个季度加总回到公司当时印出来的全年数；"
                "把重述后的第四季换进来，前三季就会出现无法消解的残差，"
                "而公司从未重新发布过那三个季度。"),
            "src_extra": ("2022 年第四季业绩发布与 2023 年第四季业绩发布的对照列；"
                          "两版均为公司披露值。"),
        },
    ]

    exhibits = number_exhibits(settled + highlights + next_ex + routine)
    resolve_exhibit_refs(exhibits)
    n_s, n_h, n_n = len(settled), len(highlights), len(next_ex)
    settled_ex = exhibits[:n_s]
    highlight_ex = exhibits[n_s:n_s + n_h]
    next_block = exhibits[n_s + n_h:n_s + n_h + n_n]
    routine_ex = exhibits[n_s + n_h + n_n:]

    first_table = exhibits[-1]["n"] + 1
    tables = [
        {
            "n": first_table,
            "title": "近八季合并损益（公司披露值，₩十亿）",
            "headers": ["期间", "营业收入", "营业利润", "净利润",
                        "营业利润率 D", "公司披露的营业利润率", "净利率 D"],
            "rows": [[periods[i], f"{revenue[i]:,.1f}", f"{op[i]:,.1f}",
                      "—" if net[i] is None else f"{net[i]:,.1f}",
                      f"{opm[i]:.2f}%",
                      "—" if fin["operating_margin_pct_disclosed"][i] is None
                      else f"{fin['operating_margin_pct_disclosed'][i]}%",
                      "—" if netm[i] is None else f"{netm[i]:.2f}%"]
                     for i in range(len(periods) - 8, len(periods))],
        },
        {
            "n": first_table + 1,
            "title": "十三季量价用词与本页读成的区间（公司只发布左边那一列）",
            "headers": ["期间", "DRAM 出货量用词", "读成", "DRAM 售价用词", "读成",
                        "NAND 出货量用词", "读成", "NAND 售价用词", "读成"],
            "rows": [[kq[i],
                      dram_bit["phrases"][i],
                      f"{dram_bit['low_pct'][i]:g}–{dram_bit['high_pct'][i]:g}%",
                      dram_asp["phrases"][i],
                      f"{dram_asp['low_pct'][i]:g}–{dram_asp['high_pct'][i]:g}%",
                      nand_bit["phrases"][i],
                      f"{nand_bit['low_pct'][i]:g}–{nand_bit['high_pct'][i]:g}%",
                      nand_asp["phrases"][i],
                      f"{nand_asp['low_pct'][i]:g}–{nand_asp['high_pct'][i]:g}%"]
                     for i in range(len(kq))],
        },
        {
            "n": first_table + 2,
            "title": "年度审计数与恒等式核对（₩十亿）",
            "headers": ["项目", "FY2023", "FY2024", "FY2025"],
            "rows": [
                ["营业收入"] + [f"{v:,}" for v in ann["revenue"]],
                ["销货成本"] + [f"{v:,}" for v in ann["cost_of_sales"]],
                ["毛利"] + [f"{v:,}" for v in ann["gross_profit"]],
                ["销售及管理费用"] + [f"{v:,}" for v in ann["sga"]],
                ["研发费用"] + [f"{v:,}" for v in ann["rnd"]],
                ["营业利润（= 毛利 − 销管 − 研发）D"]
                + [f"{g - s - r:,}" for g, s, r in zip(ann["gross_profit"],
                                                       ann["sga"], ann["rnd"])],
                ["公司报告的营业利润"] + [f"{v:,}" for v in ann["operating_profit"]],
                ["税前利润"] + [f"{v:,}" for v in ann["profit_before_tax"]],
                ["所得税费用"] + [f"{v:,}" for v in ann["income_tax"]],
                ["净利润（= 税前 − 所得税）D"]
                + [f"{p - t:,}" for p, t in zip(ann["profit_before_tax"],
                                                ann["income_tax"])],
                ["公司报告的净利润"] + [f"{v:,}" for v in ann["net_income"]],
                ["资本开支（购置不动产、厂房及设备的现金流出）"]
                + [f"{v:,}" for v in ann["capital_expenditures"]],
                ["经营现金流"] + [f"{v:,}" for v in ann["operating_cash_flow"]],
                ["自由现金流 D"] + [f"{v:,}" for v in fcf],
                ["资本开支占收入 D"] + [f"{v:.1f}%" for v in intensity],
            ],
        },
        threshold_table(first_table + 3, "下季阈值与当前值（原始单位）",
                        watch, "current", "当前值"),
        ai_capex_cycle_table(first_table + 4),
    ]

    return {
        "schema_version": "quarterly-dashboard/skhynix-v1",
        "page": {"slug": "skhynix", "language": "zh-CN"},
        "company": {
            "ticker": "SKHY",
            "name": "SK hynix",
            "group": "semiconductor_ai",
            "accounting_standard": "K-IFRS",
        },
        "latest": {
            "disclosed_period_label": "Q2 2026",
            "full_financial_period_label": "Q2 2026",
            "period_end": "2026-06-30",
            "release_date": "2026-07-29",
            "analysis_date": "2026-08-29",
            "audit_status": "provisional",
            "status": "history_ready",
        },
        "tracker": "Watchlist Quarterly Tracker · SK hynix",
        "title": "SK hynix Inc. (000660.KS / SKHY)：Q2 2026 季报仪表盘",
        "subtitle": ("截至 2026-06-30 · 发布 2026-07-29 · K-IFRS · 暂定数，外部审计未完成 · "
                     "自然年财年，季度标注与财年一致 · 韩元列报"),
        "headline": (
            f"营收 ₩{revenue[-1] / 1000:.1f}T、同比 +257%，营业利润率 {opm[-1]:.1f}% 为历史最高；"
            f"净利率 {netm[-1]:.0f}% 高过 100%，因为税前比营业利润多出 "
            f"₩{(below['profit_before_tax'][1] - below['operating_profit'][1]) / 1000:.1f}T 的营业外收益，"
            "而公司的季度发布只印到净利润为止、对这笔钱没有任何拆分；"
            "全公司唯一的前瞻披露是下一季的出货量，而且它和售价一样，是用英文形容词发布的。"),
        "brief": (
            '<h4>这一页要说的三件事</h4><div class="takeaway-grid">'
            '<article><span>披露</span><b>营收报到百万韩元，两个驱动变量只给形容词</b>'
            '<p>十三个季度的出货量与售价环比，全部是 “Mid-60% Increase”、“Flat”、'
            '“Over 70% Increase” 这样的用词，且出自 Nasdaq 上市的注册声明书。'
            '52 次读数平均留下 3.2 个百分点的不确定，4 次根本没有上界。</p></article>'
            '<article><span>后果</span><b>指引全兑现，收入仍可能不及预期</b>'
            '<p>公司指引的是出货量，而出货量的摆幅是个位数到十几个点；'
            '售价一季能走六十多个点，且从不指引。被指引的变量不是决定收入的变量。</p></article>'
            '<article><span>本季</span><b>净利率 118% 不是经营突破</b>'
            f'<p>税前比营业利润多 ₩{(below["profit_before_tax"][1] - below["operating_profit"][1]) / 1000:.1f}T，'
            f'占税前 {nonop_share:.0f}%。这个数只在向 SEC 报送的 6-K 里印出来，'
            '公司自己的业绩发布没有；构成则任何文件都没有。</p></article>'
            '</div>'),
        "source": ('Source: <a href="https://www.sec.gov/Archives/edgar/data/2120882/'
                   '000119312526321989/d115239d6k.htm" rel="noopener">'
                   'SK hynix 2026 年第二季度业绩（Form 6-K，2026-07-29）</a>'
                   '与 <a href="https://www.sec.gov/Archives/edgar/data/2120882/'
                   '000119312526299963/d32785d424b4.htm" rel="noopener">'
                   'Form 424B4 招股说明书（2026-07-10）</a>。'
                   'SK hynix 为外国私人发行人，年报为 20-F，季度以 6-K 报送。'),
        "source_url": "https://www.skhynix.com/ir",
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {"id": "settled", "title": "一、公司指引了什么，以及为什么这一节结不出别页那种记录",
             "description": ("本站其他页的第一节结清「公司给的区间对随后报出来的实际值」。"
                             "SK hynix 不发布任何财务指引，它公开的量与价都是英文用词，"
                             "所以这一节能结清的是另一件事：这些词留下了多少不确定，"
                             "以及为什么指引全部兑现仍然可以对不上收入。"),
             "exhibits": settled_ex},
            {"id": "quarter_highlights", "title": "二、本季重点",
             "description": ("22 季的营收与利润率、净利率越过 100% 的来源，"
                             "以及两条一年只披露一次、却比任何季度数字都更能说明结构的口径："
                             "分产品收入与单一客户集中度。"),
             "exhibits": highlight_ex},
            {"id": "next_quarter", "title": "三、下季要跟踪什么",
             "description": ("当前值离阈值还有多远，统一用「距阈值余量」口径。"
                             "阈值为本地研究设定，不是公司指引，因为公司没有指引。"),
             "exhibits": next_block},
            {"id": "routine", "title": "四、长期常规跟踪",
             "description": ("资本强度与折旧的分母效应，以及窗口里唯一一次重述"
                             "和本页序列选用的版本。"),
             "exhibits": routine_ex},
        ],
        "tables": tables,
        "notes": [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "SK hynix 财年即自然年，本页季度标注与公司自己的口径一致，无需换算。",
            "本页以韩元列报，与本站其他以美元列报的页面不可直接相加。金额除特别标注外单位为万亿韩元（₩T）或十亿韩元。公司自己在业绩发布中以万亿韩元为主要单位。",
            "SK hynix 是 SEC 注册人：CIK 2120882，文件编号 001-43391，2026-07-10 起在纳斯达克以 SKHY 交易 ADR，年报为 20-F、季度以 6-K 报送。本页的一手来源因此同时包含公司自己的业绩发布与 SEC 托管的申报文件。",
            "第一节结清的不是指引兑现率：SK hynix 不发布营收、利润、利润率或每股收益的指引，无论季度还是年度。它唯一的前瞻数字是下一季的出货量，而出货量与售价一样以英文用词发布。本站其他公司页第一节结清的是数值区间，本页不是，差别源于公司披露口径而非编辑选择。",
            "用词到区间的映射由本页一次性设定，对四条序列一视同仁，完整对照见核对抽屉里的用词表。其中 Over 20%、Over 30%、Over 40%、Over 70% 四种说法在申报文件里没有上界，本页统一取「下限加十个百分点」以便作图，该上界是作图约定而非披露。",
            "平均售价的用词以美元计，而收入以韩元报告，两者之间存在申报文件未披露的汇率项。因此把出货量与售价相乘去对韩元收入，必然留下一个汇率造成的残差；本页把这个残差画出来而不是把它并入产品组合，见第一节最后一张图。",
            "营业利润率与净利率均为本页按两个韩元金额自算。公司在业绩发布中披露的是四舍五入到整数的百分比，两者并列在近八季核对表里。用整数做环比差最多可能偏约一个百分点，例如 2025 年第二季到第三季按整数读是 +6pp、按金额算是 +5.1pp。",
            "营业利润在 K-IFRS 的这套列报里不是一个报表行，而是毛利减销售及管理费用减研发费用。该恒等式在 FY2023 至 FY2025 三个年度以及 2026 年第一季逐期成立，且结果与公司在业绩发布中报告的营业利润完全一致，核对见年度审计数表。",
            "本季税前利润、所得税与营业外净收益：税前利润印在 2026-07-29 报送的 6-K 上，所得税为税前减净利、营业外净额为税前减营业利润，两者都是两条已印出的行相减。公司自己的季度业绩发布只印到净利润为止，对营业外收益没有任何科目拆分。本页因此不发布这笔收益的构成，也不发布任何「剔除一次性后的净利润」——那需要一个本页读过的文件里都不存在的数字。",
            "分产品收入与单一客户集中度只有年度披露（另加第一季度），来自审计报表附注。公司在同一份文件中说明其决策层不接收任何组成部分的分部财务信息，因此财务报表不含分部信息，只有单一报告分部。季度层面的 DRAM 与闪存收入拆分在公开披露中不存在。",
            "按地区的收入披露以「销售主体所在地」为口径，指的是 SK hynix 在哪里入账，不是需求在哪里，因此本页不据此画终端需求图。",
            "2022 年第四季被重述过一次：公司当期发布的数与一年后作为对照列印出的数不同，营业利润与净利润各下调 211、收入下调 27（₩十亿）。本页 22 季序列采用「当期首次发布」那一版，因为只有它能让 2022 年四季加总回到公司当时印出的全年数。2022 年前三季的印刷精度只到万亿韩元的两位小数，所以该年加总与全年数之间约有个位数十亿的残差，属于精度而非错误。",
            "2021 年第四季没有当季净利润与当季营业利润率：公司那一期只印了当季营收与营业利润，同篇中的 29% 与 9,616 是全年数。本页把这两格留空，不用「全年减三季」补。",
            "本页不发布市场一致预期、评级、目标价与估值。这一条对本页尤其要紧：SK hynix 不发布任何财务指引，所以任何看起来像「预期对实际」的对照都只能来自站外，而没有可核对的、带日期的公开来源时，宁可不发。",
            "本页只发布公司披露值、可复算的简单派生值；D 标记代表 Derived / 自算。",
            "核对抽屉最后那张「AI capex 循环」是全站共用的跨页对照块，在每一页都逐字节相同，不是对 SK hynix 的判断。它追的是四家云厂现金资本开支 → NVDA 数据中心 → TSM 晶圆这条链。SK hynix 是这条链上的供给方而不是其中任何一环的支出方，本页带着这张表是为了让读者在任意一页都能查到同一份上下游对照，它在折叠的抽屉里，不参与本页的论证。",
            "本页已知未接入：季度层面的分产品收入与利润、HBM 的收入与占比、季度资本开支与折旧、按客户或终端市场的收入拆分、2026 年第二季营业外收益的构成，以及 2026 年第三季度之后的任何数据（本页数据截至 2026-07-29 的申报）。其中 HBM 相关口径公司从未在任何申报文件中量化。",
            "业绩电话会文字稿仅链接官方 IR 与 SEC 托管版本，公开仓不复制原件或逐字内容。",
        ],
        "footer": "SK hynix quarterly results · 数据来自 SK hynix 公开披露、SEC 申报与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "skhynix.js"), payload, "skhynix")
    shell_dir = ROOT / "skhynix"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("SKHY", "skhynix"),
                                          encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"SK hynix page: {charts} charts in {len(payload['sections'])} sections "
          f"+ {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
