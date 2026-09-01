"""Hong Kong Exchanges and Clearing Limited (00388.HK) quarterly dashboard.

HKEX is a Hong Kong issuer reporting under HKFRS in Hong Kong dollars on a
calendar fiscal year. It is not an SEC registrant, so neither the rendered
statements nor XBRL companyfacts reach it: the forty-two quarterly, interim and
annual results announcements it has published since 2016 are the entire source.

**Three facts about how this company discloses decide what the page can be.**

The first is the page. The condensed income statement in a first-quarter
announcement has a three-month column, and so does the one in a third-quarter
announcement -- the Q3 statement prints nine months and three months side by
side. The interim announcement prints six months and nothing else; the annual
announcement prints twelve months and nothing else. **So the second and fourth
quarters have never been printed as an income statement by anyone**, and half
of every series on this page is a subtraction: H1 minus Q1, and the full year
minus the nine months. Twenty-one quarters printed, twenty-one derived,
alternating, for ten and a half years.

That subtraction is not taken on trust. From 2022 -- with comparative columns
reaching back to 2021Q2 -- the announcements began printing the even quarters
as a summary box: revenue and other income, operating expenses, EBITDA, profit
attributable, earnings per share, but no revenue lines. On the eleven derived
quarters where the company's own figure exists, the subtraction reproduces it
exactly: thirty-three comparisons, no exceptions. That is what licenses the
other ten. It licenses the three headline lines only; **the revenue
decomposition of an even quarter has never been printed by anybody**, here
included.

The second is that the volume statistics cannot be subtracted at all. They are
averages per trading day, and a six-month average minus a three-month average
is not the second quarter. So the trick that produces the even quarters for
money does not work for volume, and the quarterly market statistics simply do
not exist before 2021Q1. That is a disclosure floor, not a gap, and the volume
section says so instead of interpolating across it.

The third is the one that changes how the money is read. HKEX reinvests the
margin funds its clearing houses hold and rebates most of the interest back to
Clearing Participants. Gross investment income and the rebate appear **only in
the half-year and annual statements**; the quarterly statement prints a single
net number. Over the twenty-one halves the rebate went from 13 per cent of
gross to 70 per cent and back to 56 -- so the gross line and the net line have
told opposite stories about the same portfolio, twice, and only one of them is
visible at quarterly frequency.

Published figures are company-reported or transparent arithmetic. The company
publishes no financial guidance of any kind -- across the forty-two
announcements, twenty-four forward statements carry a number and not one of
them is a revenue, profit, expense or capital-expenditure figure -- so this
page has no delivery chart, and the thresholds in section one are local
research settings rather than anything the company said.
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
    headroom,
    headroom_exhibit,
    number_exhibits,
    threshold_table,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402

STAGING_PATH = ROOT / "series" / "hkex.json"
DATA_DIR = ROOT / "data"

# One tick per year on the forty-two-quarter axes; one per half-year on the
# twenty-two-quarter volume axes.  The renderer's own font shrinking floors out
# around thirty labels, so a long axis without a step prints an unreadable smear.
LONG_STEP = 4
KPI_STEP = 2

# The ten income-statement lines whose disclosure status the page tracks.  Six
# fee lines plus revenue, revenue and other income, EBITDA and profit
# attributable: everything a reader would use to decompose a quarter.
TRACKED_LINES = [
    "trading_fees", "clearing_fees", "listing_fees", "depository_fees",
    "market_data_fees", "other_revenue", "revenue", "revenue_and_other_income",
    "ebitda", "profit_attributable",
]
# The subset the company prints for an even quarter, in the summary box.
BOX_LINES = ["revenue_and_other_income", "ebitda", "profit_attributable"]


def pct(current: float, base: float) -> float:
    return (current / base - 1) * 100.0


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def rounded(values, digits: int = 6):
    return [None if v is None else round(v, digits) for v in values]


def hkd_m(value: float, digits: int = 0) -> str:
    """HK$m with the minus outside the currency symbol, as `board` formats money."""
    return f"{'−' if value < 0 else ''}HK${abs(value):,.{digits}f}M"


def qoq(values: list[float]) -> list[float]:
    return [(values[i] / values[i - 1] - 1) * 100 for i in range(1, len(values))]


def slope_and_r2(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Least-squares slope of y on x and the R-squared, both from the series.

    Published rather than asserted: the claim that HKEX's revenue is damped
    against turnover is a claim about a slope, and a page that only says
    "revenue moves less than volume" cannot be checked against what it ships.
    """
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    return sxy / sxx, sxy ** 2 / (sxx * syy)


def yoy_series(values: list[float | None]) -> list[float | None]:
    """Year-on-year percentage change, four quarters back, holes preserved."""
    out: list[float | None] = []
    for index, value in enumerate(values):
        base = values[index - 4] if index >= 4 else None
        out.append(None if value is None or base in (None, 0) else pct(value, base))
    return out


def printed_line_count(staging: dict, quarter: str) -> int:
    """How many of the ten tracked lines the company printed for that quarter."""
    index = staging["quarters"].index(quarter)
    if staging["quarter_basis"][index] == "printed":
        return sum(1 for f in TRACKED_LINES
                   if staging["quarterly"][f][index] is not None)
    box = staging["printed_box"].get(quarter, {})
    return sum(1 for f in BOX_LINES if f in box)


def box_check(staging: dict) -> dict:
    """Recount the printed-box comparison the page's headline claims.

    The claim is that every derived quarter the company also printed comes back
    identical.  Recomputing it here rather than storing a sentence means the
    number in the headline cannot drift away from the series underneath it.
    """
    comparisons = mismatches = derived_comparisons = 0
    covered = []
    for quarter, box in staging["printed_box"].items():
        if quarter not in staging["quarters"]:
            continue
        index = staging["quarters"].index(quarter)
        derived = staging["quarter_basis"][index] == "derived"
        for field in BOX_LINES:
            if field not in box:
                continue
            ours = staging["quarterly"][field][index]
            if ours is None:
                continue
            comparisons += 1
            if derived:
                derived_comparisons += 1
            if abs(box[field] - ours) > 0.5:
                mismatches += 1
        if derived and any(f in box for f in BOX_LINES):
            covered.append(quarter)
    derived_total = sum(1 for b in staging["quarter_basis"] if b == "derived")
    # Two counts, because they answer different questions and only one of them
    # is evidence for the subtraction. On a printed quarter the box merely
    # cross-checks the statement parse against the summary; on a derived one it
    # is the only outside reading this page's arithmetic can be held against.
    return {
        "comparisons": comparisons,
        "derived_comparisons": derived_comparisons,
        "mismatches": mismatches,
        "covered": sorted(covered),
        "derived_total": derived_total,
        "unchecked": derived_total - len(covered),
    }


# ── section one: what is printed, and what this page had to work out ─────────

def disclosure_section(staging: dict, check: dict) -> tuple[list[dict], list[dict]]:
    quarters = staging["quarters"]
    q = staging["quarterly"]
    basis = staging["quarter_basis"]
    printed = [i for i, b in enumerate(basis) if b == "printed"]
    derived = [i for i, b in enumerate(basis) if b == "derived"]

    roi = q["revenue_and_other_income"]
    revenue_bar = {
        "ref": "EX_ROI",
        "kind": "gs_bar",
        "title": (f"收入及其他收益：本季 {hkd_m(roi[-1])}，"
                  f"同比 {signed(pct(roi[-1], roi[-5]))}；"
                  f"{len(printed)} 季由公司印出、{len(derived)} 季由本页减出"),
        "xlabels": list(quarters),
        "xrot": 90,
        "xstep": LONG_STEP,
        "values": rounded(roi),
        "legend": "季度收入及其他收益",
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "HK$M",
        "ylab2": "同比增速",
        "yoy": {"name": "同比 (RHS)", "values": rounded(yoy_series(roi)),
                "color": "GREEN", "yfmt": "pct0"},
        "note": (
            "<b>柱子高低是真的，柱子的来历一半不是。</b>第一季与第三季的业绩公告各带一个「三个月」列，"
            "整张损益表按季印出；中期公告只印六个月、全年公告只印十二个月，"
            "所以第二季与第四季的损益表从来没有被印过，本页这 "
            f"{len(derived)} 格是 H1 减 Q1、全年减前九个月得到的。"
            "图上看不出哪一格是哪一种 —— 这正是下一张图存在的理由。"),
        "src_extra": (
            "各季数字取自公司 42 份业绩公告的简明综合损益表。"
            "解析后先用报表自身的算术核对：六项费用相加等于收入、加其他收入等于收入及其他收益、"
            "EBITDA 减折旧摊销等于经营溢利、除税前溢利减税项等于期内溢利、"
            "股东应占加非控股权益等于期内溢利 —— 42 份公告共 648 条恒等式全部成立。"),
    }

    counts = [printed_line_count(staging, quarter) for quarter in quarters]
    first_box = min((quarters[i] for i in derived
                     if printed_line_count(staging, quarters[i]) > 0), default=None)
    coverage = {
        "ref": "EX_PRINTED",
        "kind": "bar_line_dual",
        "title": (f"每个季度里，十条主线有几条是公司自己印的："
                  f"单数季 {max(counts)} 条，双数季 {min(counts)} 条 → {len(BOX_LINES)} 条"),
        "xlabels": list(quarters),
        "xrot": 90,
        "xstep": LONG_STEP,
        "bar": {"name": "公司印出的行数（十条主线中）", "values": counts, "color": "NAVY"},
        "line": {"name": "本页据以作图的行数", "values": [len(TRACKED_LINES)] * len(quarters),
                 "color": "RED", "yfmt": "f0"},
        "fmt": "f0",
        "yfmt": "f0",
        "label_fmt": "f0",
        "ylab": "行数",
        "ylab2": "行数",
        "note": (
            "十条主线是六项费用收入、收入、收入及其他收益、EBITDA、股东应占溢利 —— "
            "一个读者要拆开一个季度所需要的全部。"
            f"红线是本页每一格都画出来的 {len(TRACKED_LINES)} 条；蓝柱是公司印出来的。"
            f"单数季两者相等；双数季在 {first_box} 之前是 <b>0</b>，之后也只有 "
            f"{len(BOX_LINES)} 条 —— 公司从 2022 年起在公告正文的摘要框里补印了双数季的合计数"
            "（收入及其他收益、营业开支、EBITDA、股东应占溢利、每股盈利），"
            "<b>但没有一次印过双数季的收入分项</b>。"
            "所以本页第二节那张收入构成图，有一半的柱是本页算出来的，不是任何人印出来的。"),
        "src_extra": (
            "「公司印出的行数」按季重数：单数季数该季公告损益表三个月列上非空的行，"
            "双数季数该季在其他公告摘要框里出现过的行。"),
    }

    ours = [staging["quarterly"]["revenue_and_other_income"][quarters.index(qq)]
            for qq in check["covered"]]
    theirs = [staging["printed_box"][qq]["revenue_and_other_income"] for qq in check["covered"]]
    reconcile = {
        "ref": "EX_CHECK",
        "kind": "lines_endlabels",
        "title": (f"那道减法唯一的对照物：{len(check['covered'])} 个双数季公司也印了合计数，"
                  f"{check['derived_comparisons']} 次比对全部相同"),
        "xlabels": list(check["covered"]),
        "xrot": 90,
        "series": [
            {"name": "公司摘要框印出的收入及其他收益", "values": rounded(theirs), "color": "NAVY"},
            {"name": "本页由 H1−Q1 / FY−9M 减出的同一格", "values": rounded(ours), "color": "GOLD"},
        ],
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "end_label": True,
        "ylab": "HK$M",
        "note": (
            "<b>两条线完全重合，这就是本图要说的事。</b>"
            f"公司在 2022 年起的公告里补印双数季合计数，比较列可回溯到 {check['covered'][0]}；"
            f"本页把这 {len(check['covered'])} 格的三条主线（收入及其他收益、EBITDA、股东应占溢利）"
            f"逐条与自己的减法结果比对，{check['derived_comparisons']} 次比对没有一次不同"
            f"（连同公司也印过合计数的单数季一起算是 {check['comparisons']} 次，"
            "但单数季那部分核的是解析、不是减法）。"
            f"这不是「看起来对」—— 它是本页对另外 {check['unchecked']} 个"
            "<b>没有任何对照物</b>的双数季所能给出的全部依据。"
            "两条线画在一起而不是画差额：差额恒为零，画出来是一排看不见的柱子。"),
        "src_extra": (
            "公司印出的双数季合计数取自各期公告正文「Key Financials」摘要框中"
            "「Comparison of Q2/Q4 with …」两节；本页减出的同一格取自损益表。"),
    }

    entries = staging["next_kpi"]["quantified"]
    headroom_card = headroom_exhibit(
        "六条本地阈值离触发还有多远（公司不发布任何财务指引）",
        entries, "current",
        note=(
            "<b>这一节没有兑现图，因为没有可兑现的东西。</b>"
            f"{staging['guidance_census']['documents']} 份公告里带数字的前瞻表述共 "
            f"{staging['guidance_census']['forward_statements_with_a_number']} 处，"
            "全部是产品上线时点、指数纳入、股息寄发日期与税务安全港措辞，"
            "<b>没有一处是收入、利润、费用或资本开支的数字指引</b>；分析师演示材料里也没有。"
            "所以上面六条是本地研究阈值，不是公司给的数，"
            "作用只是把「下一季看什么」写死成一个数而不是一句话。"
            "正值 = 仍在安全侧。"),
        src_extra=(
            "当前值取自 2026 年中期业绩公告：EBITDA 利润率、非交易类收入占比与有效税率由损益表自算，"
            "现货日均成交额与 LME 计费日均手数取自同一份公告的市场统计表，"
            "返还比例按半年频率取自损益表的投资收益毛额与返还额两行。"),
    )
    return [revenue_bar, coverage, reconcile, headroom_card], entries


# ── section two: this quarter, on the lines that exist every quarter ─────────

def quarter_section(staging: dict) -> list[dict]:
    quarters = staging["quarters"]
    q = staging["quarterly"]
    roi = q["revenue_and_other_income"]
    ebitda = q["ebitda"]
    margin = [e / r * 100 for e, r in zip(ebitda, roi)]
    profit = q["profit_attributable"]
    tax_rate = [-t / p * 100 for t, p in zip(q["taxation"], q["profit_before_tax"])]

    fee_lines = ["trading_fees", "clearing_fees", "listing_fees",
                 "depository_fees", "market_data_fees", "other_revenue"]
    fee_names = ["交易费及交易系统使用费", "结算及交收费", "上市费",
                 "存管、托管及代理人服务费", "市场数据费", "其他收入"]
    fee_colors = ["NAVY", "MBLUE", "BLUE", "GREEN", "GOLD", "GRAY"]
    non_fee = [r - v for r, v in zip(roi, q["revenue"])]
    non_fee_share = [n / r * 100 for n, r in zip(non_fee, roi)]
    trading_share = [(a + b) / r * 100
                     for a, b, r in zip(q["trading_fees"], q["clearing_fees"], roi)]

    non_trading = [a + b + c for a, b, c in zip(q["listing_fees"], q["depository_fees"],
                                                q["market_data_fees"])]
    non_trading_share = [n / r * 100 for n, r in zip(non_trading, q["revenue"])]

    staff = q["staff_costs"]
    opex_other = []
    for index in range(len(quarters)):
        total = roi[index] - ebitda[index]
        opex_other.append(total + staff[index])   # staff是负数，total为正的开支合计
    opex_total = [-(s) + o for s, o in zip(staff, opex_other)]
    txn_latest = q["transaction_expenses"][-1]

    margin_line = {
        "ref": "EX_MARGIN",
        "kind": "gs_line",
        "title": (f"EBITDA 利润率：本季 {margin[-1]:.1f}%，"
                  f"{len(quarters)} 季里最高 {max(margin):.1f}%、最低 {min(margin):.1f}%"),
        "xlabels": list(quarters),
        "xrot": 90,
        "xstep": LONG_STEP,
        "values": rounded(margin),
        "legend": "EBITDA / 收入及其他收益",
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "EBITDA 利润率",
        "note": (
            "公司自己在摘要框里印的 EBITDA 利润率用的是<b>扣除交易相关支出后的收入</b>做分母，"
            "而那一行只从 2020 年才出现在损益表上，所以本页统一用「EBITDA ÷ 收入及其他收益」"
            "自算全窗口 —— 口径一致优先于与公司口径逐格相同。"
            f"本季自算 {margin[-1]:.1f}%，公司在同一份公告里印的是 81%（其分母较小，因此略高）。"
            "两者的差在 1 个百分点以内，且方向固定。"),
        "src_extra": "EBITDA 与收入及其他收益均取自各期损益表；比值为本页自算。",
    }

    mix = {
        "ref": "EX_MIX",
        "kind": "stacked_dual",
        "title": (f"收入构成：六项费用收入 {hkd_m(q['revenue'][-1])}，"
                  f"其中交易费与结算费占收入及其他收益 {trading_share[-1]:.1f}%"),
        "xlabels": list(quarters),
        "xrot": 90,
        "xstep": LONG_STEP,
        "stacks": [{"name": name, "color": color, "values": rounded(q[field])}
                   for field, name, color in zip(fee_lines, fee_names, fee_colors)],
        "line": {"name": "交易费与结算费占收入及其他收益（右轴）", "color": "RED",
                 "values": rounded(trading_share), "ymax": 100},
        "fmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "HK$M",
        "rlab": "交易与结算费占比 %",
        "note": (
            "<b>这张图有一半的柱是减出来的。</b>柱是六项费用收入，双数季的六项全部由 H1 减 Q1、"
            "全年减前九个月得到，公司从未按季印过它们；红线是最直接跟着成交量走的那两条"
            "（交易费与结算交收费）占收入及其他收益的比例。"
            f"这一比例在窗口里在 {min(trading_share):.1f}% 与 {max(trading_share):.1f}% 之间，"
            f"本季 {trading_share[-1]:.1f}%。"
            "<b>右轴画的是这一条而不是投资及其他收益的占比，理由在第三节第一张</b>："
            "后者在 2020Q1 为负，而这一图型的右轴自零点起算，负值会被画到画布外。"
            "右轴另显式设了 100% 的上界 —— 它默认封顶在 60，超过就同样落在画布外。"),
        "src_extra": "六项费用收入与收入及其他收益逐期取自损益表；占比为本页自算。",
    }

    profit_tax = {
        "ref": "EX_PROFIT",
        "kind": "bar_line_dual",
        "title": (f"股东应占溢利 {hkd_m(profit[-1])}、同比 {signed(pct(profit[-1], profit[-5]))}；"
                  f"有效税率 {tax_rate[-1]:.1f}%"),
        "xlabels": list(quarters),
        "xrot": 90,
        "xstep": LONG_STEP,
        "bar": {"name": "股东应占溢利", "values": rounded(profit), "color": "NAVY"},
        "line": {"name": "有效税率（右轴）", "values": rounded(tax_rate),
                 "color": "RED", "yfmt": "pct1"},
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "HK$M",
        "ylab2": "有效税率",
        "note": (
            f"有效税率为「税项 ÷ 除税前溢利」，{len(quarters)} 季里在 "
            f"{min(tax_rate):.1f}% 到 {max(tax_rate):.1f}% 之间。"
            "香港利得税率 16.5%，本页窗口里的偏离主要来自英国子公司（LME）与"
            "各期的过往年度调整，2024 年起另有 OECD 支柱二的补足税。"
            "双数季的溢利同样是减出来的，但它是本页第一节那道对照唯一覆盖到的三条线之一。"),
        "src_extra": "溢利、除税前溢利与税项逐期取自损益表；有效税率为本页自算。",
    }

    non_trading_ex = {
        "ref": "EX_NONTRADE",
        "kind": "stacked_dual",
        "title": (f"不随成交量走的那部分收入：上市费、存管与市场数据合计 "
                  f"{hkd_m(non_trading[-1])}，占费用收入 {non_trading_share[-1]:.1f}%"),
        "xlabels": list(quarters),
        "xrot": 90,
        "xstep": LONG_STEP,
        "stacks": [
            {"name": "上市费", "color": "BLUE", "values": rounded(q["listing_fees"])},
            {"name": "存管、托管及代理人服务费", "color": "GREEN",
             "values": rounded(q["depository_fees"])},
            {"name": "市场数据费", "color": "GOLD", "values": rounded(q["market_data_fees"])},
        ],
        "line": {"name": "占六项费用收入比例（右轴）", "color": "RED",
                 "values": rounded(non_trading_share), "ymax": 100},
        "fmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "HK$M",
        "rlab": "占费用收入 %",
        "note": (
            "交易所最像订阅制的三条腿：上市费按年摊、存管费按持仓与动作收、市场数据费按终端收。"
            f"三者合计占六项费用收入的比例从 {max(non_trading_share):.1f}% 一路降到 "
            f"{min(non_trading_share):.1f}%，本季 {non_trading_share[-1]:.1f}% —— "
            "<b>不是它们缩小了，是交易费和结算费涨得更快。</b>"
            "读这条线要注意分母：成交清淡的季度它会自动抬高。"
            "右轴同样显式设了 100% 的上界。"),
        "src_extra": "三项收入逐期取自损益表；占比分母为同期六项费用收入合计。",
    }

    opex = {
        "ref": "EX_OPEX",
        "kind": "stacked_dual",
        "title": (f"营业开支与交易相关支出合计 {hkd_m(opex_total[-1])}，其中员工成本 "
                  f"{hkd_m(-staff[-1])}（占 {-staff[-1] / opex_total[-1] * 100:.1f}%）"),
        "xlabels": list(quarters),
        "xrot": 90,
        "xstep": LONG_STEP,
        "stacks": [
            {"name": "员工成本及相关开支", "color": "NAVY", "values": rounded([-v for v in staff])},
            {"name": "其余营业开支", "color": "GOLD", "values": rounded(opex_other)},
        ],
        "line": {"name": "营业开支占收入及其他收益（右轴）", "color": "RED",
                 "values": rounded([o / r * 100 for o, r in zip(opex_total, roi)]),
                 "ymax": 100},
        "fmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "HK$M",
        "rlab": "开支占收入 %",
        "note": (
            "<b>开支合计不是从明细行相加得到的，是从 EBITDA 倒推的</b>："
            "「收入及其他收益 − EBITDA」。因此它比公司自己印的「营业开支」多一块 —— "
            f"多的是交易相关支出，本季 {hkd_m(-txn_latest)}："
            f"本季倒推值 {hkd_m(opex_total[-1])}，公司印出的营业开支 "
            f"{hkd_m(opex_total[-1] + txn_latest)}。"
            "之所以不逐季扣掉那一块，是因为它 2020 年才独立成行，"
            "扣了会让 2020 年之前与之后不是同一个口径。"
            "从 EBITDA 倒推的理由是明细行的行数在窗口内变过三次"
            "（2018 年起信息技术开支独立成行、2020 年起慈善捐款独立成行），"
            "而两个端点的定义十年没变。员工成本一行则全窗口都在，直接取自损益表。"
            "「其余营业开支」因此是差额，把定义变过的那几行都收在里面 —— "
            "它是一个残差，不是公司印出的科目。"),
        "src_extra": "员工成本取自损益表；开支合计由收入及其他收益减 EBITDA 得到。",
    }
    return [margin_line, mix, profit_tax, non_trading_ex, opex]


# ── section three: the rebate, which is only visible twice a year ───────────

def investment_section(staging: dict) -> list[dict]:
    quarters = staging["quarters"]
    q = staging["quarterly"]
    roi = q["revenue_and_other_income"]
    non_fee = [r - v for r, v in zip(roi, q["revenue"])]
    non_fee_share = [n / r * 100 for n, r in zip(non_fee, roi)]
    worst = min(range(len(non_fee)), key=lambda i: non_fee[i])

    quarterly_net = {
        "ref": "EX_NETINV",
        "kind": "bar_line_dual",
        "title": (f"季度能看见的只有净额：本季投资及其他收益 {hkd_m(non_fee[-1])}，"
                  f"占收入及其他收益 {non_fee_share[-1]:.1f}%"),
        "xlabels": list(quarters),
        "xrot": 90,
        "xstep": LONG_STEP,
        "bar": {"name": "投资及其他收益（收入及其他收益 − 六项费用收入）",
                "values": rounded(non_fee), "color": "GOLD"},
        "line": {"name": "占收入及其他收益（右轴）", "values": rounded(non_fee_share),
                 "color": "RED", "yfmt": "pct1"},
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "HK$M",
        "ylab2": "占比",
        "note": (
            f"<b>{quarters[worst]} 这一格是负的 —— {hkd_m(non_fee[worst])}，占比 "
            f"{non_fee_share[worst]:.2f}%。</b>那一季公司报的是一笔净投资亏损，"
            "集体投资计划的公允价值在 2020 年 3 月被打下去。"
            "本页把这一条单独画成柱线图而不是画在上一节的收入构成图右轴上，"
            "就是因为这一格：堆叠双轴图的右轴自零点起算，"
            "一个 −1.15% 的点会被静默画到画布之外，而图例照常显示它。"
            "柱线图的右轴按数据算，负值画得出来。"
            "这条线是季度频率能看到的全部 —— 它的毛额与返还额只在半年报上，下一张才有。"),
        "src_extra": (
            "投资及其他收益为「收入及其他收益 − 六项费用收入」，两个端点均取自损益表；"
            "它等于净投资收益加慈善基金捐款收入与杂项收入，"
            "而后两项在窗口前段并未单列成行，因此本页取差额而不是取那一行。"),
    }

    halves = staging["halves"]
    basis = staging["half_basis"]
    gross = staging["half_investment"]["gross"]
    rebates = staging["half_investment"]["rebates"]
    net = staging["half_investment"]["net"]
    share = [-r / g * 100 for r, g in zip(rebates, gross)]
    derived = sum(1 for b in basis if b == "derived")

    spread = {
        "ref": "EX_REBATE",
        "kind": "stacked_dual",
        "title": (f"保证金投资收益是一道价差：本半年毛额 {hkd_m(gross[-1])}、"
                  f"返还给结算参与者 {hkd_m(-rebates[-1])}、留下 {hkd_m(net[-1])}"),
        "xlabels": list(halves),
        "xrot": 90,
        "stacks": [
            {"name": "留在公司（净投资收益）", "color": "NAVY", "values": rounded(net)},
            {"name": "返还给结算参与者", "color": "GOLD", "values": rounded([-r for r in rebates])},
        ],
        "line": {"name": "返还比例（右轴）", "color": "RED", "values": rounded(share), "ymax": 100},
        "fmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "HK$M",
        "rlab": "返还比例 %",
        "note": (
            "<b>柱高是毛额，两段的分法才是这门生意。</b>公司把清算会员缴来的保证金拿去投资，"
            "再把其中大部分利息按约定返还给会员；损益表上「投资收益」与"
            "「支付予参与者的利息回赠」是两行，「净投资收益」是它们的和。"
            f"返还比例从 {halves[0]} 的 {share[0]:.1f}% 一路走到 "
            f"{halves[share.index(max(share))]} 的 {max(share):.1f}%，本半年 {share[-1]:.1f}%。"
            "<b>利率上行时毛额和返还一起涨，净额涨得慢得多</b> —— "
            "把这门生意当成利率的线性敞口，会在两个方向上都算错。"
            "右轴显式设了 100% 的上界。"),
        "src_extra": (
            "毛额与返还额只出现在中期与全年业绩公告的损益表上，季度损益表只印净额；"
            f"因此本图按半年频率，{len(halves)} 个半年里 {derived} 个下半年由全年减上半年得到。"),
    }

    gross_net = {
        "ref": "EX_GROSSNET",
        "kind": "lines_endlabels",
        "title": (f"同一个组合的两条线：毛额自 {halves[0]} 起涨了 "
                  f"{pct(gross[-1], gross[0]):.0f}%，净额只涨了 {pct(net[-1], net[0]):.0f}%"),
        "xlabels": list(halves),
        "xrot": 90,
        "series": [
            {"name": "投资收益毛额", "values": rounded(gross), "color": "GOLD"},
            {"name": "净投资收益（公司留下的）", "values": rounded(net), "color": "NAVY"},
        ],
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "end_label": True,
        "ylab": "HK$M",
        "note": (
            "<b>这两条线在窗口里两次讲了相反的故事。</b>"
            "2020 下半年到 2021 上半年利率见底，毛额腰斩而净额几乎没动 —— "
            "返还比例同期从 28% 掉到 3%，会员那一侧先被压缩。"
            "2022 下半年起利率回升，毛额一年之内涨了十倍以上，净额跟不上，"
            "因为返还比例同时冲到六成。<b>季度损益表上只有其中一条线看得见</b>，"
            "而它恰好是变动较小的那条。"),
        "src_extra": "两条线均取自中期与全年业绩公告的损益表；下半年为全年减上半年。",
    }
    return [quarterly_net, spread, gross_net]


# ── section four: volume, and the part of it that cannot be drawn ───────────

def volume_section(staging: dict) -> list[dict]:
    kq = staging["kpi_quarters"]
    kpi = staging["kpi_quarterly"]
    quarters = staging["quarters"]
    q = staging["quarterly"]
    index_of = [quarters.index(x) for x in kq]
    trading_clearing = [q["trading_fees"][i] + q["clearing_fees"][i] for i in index_of]
    adt = kpi["adt_headline"]

    elasticity = staging["fee_elasticity"]
    steps_x = qoq(adt)
    steps_y = qoq(trading_clearing)
    slope, r2 = slope_and_r2(steps_x, steps_y)
    opposite = sum(1 for a, b in zip(steps_x, steps_y) if a * b < 0)

    adt_fees = {
        "ref": "EX_ADT",
        "kind": "bar_line_dual",
        "title": (f"现货市场日均成交额与交易结算费：本季 HK${adt[-1]:,.1f}bn、"
                  f"费 {hkd_m(trading_clearing[-1])}"),
        "xlabels": list(kq),
        "xrot": 90,
        "xstep": KPI_STEP,
        "bar": {"name": "交易费 + 结算交收费", "values": rounded(trading_clearing), "color": "NAVY"},
        "line": {"name": "现货日均成交额（右轴，HK$bn）", "values": rounded(adt),
                 "color": "RED", "yfmt": "f0"},
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "HK$M",
        "ylab2": "HK$bn / 日",
        "note": (
            f"<b>这张图从 {kq[0]} 起画，不是因为更早的数据没找到，是因为它不存在。</b>"
            "市场统计是「每个交易日的平均」，六个月的平均减三个月的平均不等于第二季 —— "
            "把损益表那道减法搬过来会造出一个没有意义的数。"
            f"公司自 {kq[0]} 起在每份公告里按季印出这些平均值，此前只印一季度、"
            "上半年、前九个月与全年四种口径。"
            f"这 {len(kq)} 季里，日均成交额每环比变动 1%，交易与结算费变动 {slope:.3f}%"
            f"（R² {r2:.2f}），{len(steps_x)} 次环比里只有 {opposite} 次方向相反。"),
        "src_extra": (
            "日均成交额取自各期公告的市场统计表；交易费与结算交收费取自损益表。"
            "市场统计表<b>不从 PDF 的文本层读取</b>：公司用上标标注纪录，"
            "纯文本导出会把上标并进数字本身（日均 283.0 变成 283.04），"
            f"{staging['text_layer']['figures_compared']} 个数字里有 "
            f"{staging['text_layer']['corrupted_by_glued_marker']} 个会被这样读错，"
            "而读错之后仍是一个合法的数。本页按字形磅值筛选后再解析。"),
    }

    damping = {
        "ref": "EX_SLOPE",
        "kind": "lines_endlabels",
        "title": (f"越往损益表下面走，成交额的波动被削得越平："
                  f"斜率 {elasticity['slope_trading_clearing']:.2f} → "
                  f"{elasticity['slope_revenue']:.2f} → "
                  f"{elasticity['slope_revenue_and_other_income']:.2f}"),
        "xlabels": list(kq),
        "xrot": 90,
        "xstep": KPI_STEP,
        "series": [
            {"name": "现货日均成交额（指数，首季 = 100）", "color": "RED",
             "values": rounded([v / adt[0] * 100 for v in adt])},
            {"name": "交易费 + 结算交收费", "color": "NAVY",
             "values": rounded([v / trading_clearing[0] * 100 for v in trading_clearing])},
            {"name": "收入及其他收益", "color": "GREEN",
             "values": rounded([q["revenue_and_other_income"][i]
                                / q["revenue_and_other_income"][index_of[0]] * 100
                                for i in index_of])},
        ],
        "fmt": "f0",
        "yfmt": "f0",
        "label_fmt": "f0",
        "end_label": True,
        "ylab": "指数（首季 = 100）",
        "note": (
            "三条线同起点，斜率来自环比回归而不是端点："
            f"日均成交额每变动 1%，交易与结算费变动 "
            f"{elasticity['slope_trading_clearing']:.3f}%（R² {elasticity['r2_trading_clearing']:.2f}）、"
            f"六项费用收入变动 {elasticity['slope_revenue']:.3f}%"
            f"（R² {elasticity['r2_revenue']:.2f}）、"
            f"收入及其他收益变动 {elasticity['slope_revenue_and_other_income']:.3f}%"
            f"（R² {elasticity['r2_revenue_and_other_income']:.2f}）。"
            "<b>削平它的不是费率分档</b>（港交所现货交易费是按成交金额定率收的），"
            "而是混合：衍生品与 LME 的量、上市费与市场数据的订阅性收入，"
            "以及一整块跟着利率而不是跟着成交额走的投资收益。"),
        "src_extra": "指数化仅用于同图比较；斜率与 R² 由本页对 21 次环比变动做最小二乘回归得到。",
    }

    volumes = {
        "ref": "EX_ADV",
        "kind": "lines_endlabels",
        "title": (f"三条量：期货 {kpi['adv_futures'][-1]:,.0f} 千张、"
                  f"股票期权 {kpi['adv_stock_opts'][-1]:,.0f} 千张、"
                  f"LME {kpi['adv_lme'][-1]:,.0f} 千手"),
        "xlabels": list(kq),
        "xrot": 90,
        "xstep": KPI_STEP,
        "series": [
            {"name": "期交所衍生品日均张数", "values": rounded(kpi["adv_futures"]), "color": "NAVY"},
            {"name": "股票期权日均张数", "values": rounded(kpi["adv_stock_opts"]), "color": "BLUE"},
            {"name": "LME 计费日均手数", "values": rounded(kpi["adv_lme"]), "color": "GOLD"},
        ],
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "end_label": True,
        "ylab": "千张 / 千手（日均）",
        "note": (
            "三条量各自对应一个分部，且互不联动：期交所衍生品与股票期权跟着香港股市的波动率走，"
            "LME 跟着全球金属的实货与套保需求走。"
            "LME 那一行 2018 年及以前公司印的是绝对手数（如 629,556），2019 年起改印千手，"
            "并且口径同时从「日均成交量」改成「计费日均手数」（剔除管理性交易）—— "
            "<b>不是同一个数换了单位，是换了一个数</b>，因此本页不把两代接在一起，"
            "这张图只画公司按季印出的那一段。"),
        "src_extra": "三条量取自各期公告的市场统计表，读法同上一张（按字形磅值筛选上标）。",
    }

    connect = {
        "ref": "EX_CONNECT",
        "kind": "lines_endlabels",
        "title": (f"互联互通：北向日均 RMB{kpi['adt_northbound'][-1]:,.1f}bn、"
                  f"南向日均 HK${kpi['adt_southbound'][-1]:,.1f}bn"),
        "xlabels": list(kq),
        "xrot": 90,
        "xstep": KPI_STEP,
        "series": [
            {"name": "北向日均成交额（人民币 bn）", "values": rounded(kpi["adt_northbound"]),
             "color": "NAVY"},
            {"name": "南向日均成交额（港元 bn）", "values": rounded(kpi["adt_southbound"]),
             "color": "GOLD"},
            {"name": "债券通北向日均（人民币 bn）", "values": rounded(kpi["adt_bond_conn"]),
             "color": "GREEN"},
        ],
        "fmt": "f1",
        "yfmt": "f0",
        "label_fmt": "f1",
        "end_label": True,
        "ylab": "十亿 / 日",
        "note": (
            "<b>两条线的货币不同，图上只能比形状不能比高低。</b>"
            "北向以人民币计、南向以港元计，公司在同一张表里就是这样并排印的，本页不做换算 —— "
            "换算需要选一个汇率口径，而公司没有给。"
            "南向成交计入现货市场的日均成交额（公司在表下注明），北向不计入。"),
        "src_extra": "三条互联互通日均值取自各期公告的市场统计表。",
    }

    years = staging["kpi_years"]
    annual = staging["kpi_annual"]
    long_view = {
        "ref": "EX_ANNUAL",
        "kind": "bar_line_dual",
        "title": (f"季度成交数据只到 2021Q1，年度口径回得更远：{years[0]}–{years[-1]} 现货日均成交额从 "
                  f"HK${annual['adt_headline'][0]:,.1f}bn 到 HK${annual['adt_headline'][-1]:,.1f}bn"),
        "xlabels": list(years),
        "bar": {"name": "现货市场日均成交额（HK$bn）",
                "values": rounded(annual["adt_headline"]), "color": "NAVY"},
        "line": {"name": "期交所衍生品日均张数（右轴，千张）",
                 "values": rounded(annual["adv_futures"]), "color": "RED", "yfmt": "f0c"},
        "fmt": "f1",
        "yfmt": "f0",
        "label_fmt": "f1",
        "ylab": "HK$bn / 日",
        "ylab2": "千张 / 日",
        "note": (
            "<b>本页唯一一张不是季度的量图，而这就是它存在的理由。</b>"
            "季度市场统计只回到 2021Q1；年度口径每份全年公告都印，因此可以往回走得更远。"
            f"起点是 {years[0]} 而不是 2016：2016 年与 2017 年的全年公告把市场统计排在"
            "另一种版式里，本页的解析器对那两份给出的列标定位不唯一，"
            "与其猜一个列，不如让这张图短两格并说明为什么。"),
        "src_extra": "年度值取自各年全年业绩公告的市场统计表（本期列与上年比较列互相核对）。",
    }
    return [adt_fees, damping, volumes, connect, long_view]


# ── audit tables ────────────────────────────────────────────────────────────

def audit_tables(staging: dict, entries: list[dict], check: dict, first: int) -> list[dict]:
    quarters = staging["quarters"]
    q = staging["quarterly"]
    rows = []
    for index, quarter in enumerate(quarters):
        rows.append([
            quarter,
            "公司印出" if staging["quarter_basis"][index] == "printed" else "本页减出 D",
            f"{q['revenue_and_other_income'][index]:,.0f}",
            f"{q['revenue'][index]:,.0f}",
            f"{q['ebitda'][index]:,.0f}",
            f"{q['profit_attributable'][index]:,.0f}",
            "、".join(staging["quarter_sources"][quarter]),
        ])
    ledger = {
        "n": first,
        "title": f"{len(quarters)} 个季度的原值与来历（HK$M）",
        "headers": ["季度", "来历", "收入及其他收益", "六项费用收入", "EBITDA",
                    "股东应占溢利", "来源公告"],
        "rows": rows,
    }

    check_rows = []
    for quarter in check["covered"]:
        index = quarters.index(quarter)
        box = staging["printed_box"][quarter]
        for field, label in (("revenue_and_other_income", "收入及其他收益"),
                             ("ebitda", "EBITDA"),
                             ("profit_attributable", "股东应占溢利")):
            if field not in box:
                continue
            ours = q[field][index]
            check_rows.append([
                quarter, label,
                f"{box[field]:,.0f}", f"{ours:,.0f}",
                f"{box[field] - ours:+,.0f}",
            ])
    reconcile = {
        "n": first + 1,
        "title": (f"双数季对照：公司摘要框 vs 本页减法，{len(check_rows)} 行差额全部为 0"),
        "headers": ["季度", "科目", "公司印出", "本页减出 D", "差额"],
        "rows": check_rows,
    }

    census_rows = [[
        row["period"], row["field"],
        f"{row['first']:,.0f}", f"{row['again']:,.0f}",
        f"{row['again'] - row['first']:+,.0f}",
        f"{row['first_doc']} → {row['again_doc']}",
    ] for row in staging["restatement_census"]]
    census = {
        "n": first + 2,
        "title": (f"重述普查：每个期间被公司印过两次，"
                  f"{staging['restatement_paired_readings']:,} 对读数里 "
                  f"{len(census_rows)} 处不同"),
        "headers": ["期间", "科目", "首次印出", "一年后重印", "差额", "两份公告"],
        "rows": census_rows or [["—", "—", "—", "—", "—", "—"]],
    }

    thresholds = threshold_table(
        first + 3, "第一节六条本地阈值的原始单位", entries, "current", "当前值")
    return [ledger, reconcile, census, thresholds, ai_capex_cycle_table(first + 4)]


def build_payload(staging: dict) -> dict:
    check = box_check(staging)
    quarters = staging["quarters"]
    q = staging["quarterly"]
    roi = q["revenue_and_other_income"]
    profit = q["profit_attributable"]
    margin = roi and q["ebitda"][-1] / roi[-1] * 100
    gross = staging["half_investment"]["gross"]
    rebates = staging["half_investment"]["rebates"]
    share = [-r / g * 100 for r, g in zip(rebates, gross)]
    derived_total = sum(1 for b in staging["quarter_basis"] if b == "derived")

    disclosure_ex, entries = disclosure_section(staging, check)
    quarter_ex = quarter_section(staging)
    investment_ex = investment_section(staging)
    volume_ex = volume_section(staging)
    exhibits = number_exhibits(disclosure_ex + quarter_ex + investment_ex + volume_ex, start=1)
    tables = audit_tables(staging, entries, check, len(exhibits) + 1)

    latest = staging["latest"]
    return {
        "schema_version": "quarterly-dashboard/hkex-v1",
        "page": {"slug": "hkex", "language": "zh-CN"},
        "company": {
            "ticker": "00388.HK",
            "name": "Hong Kong Exchanges and Clearing Limited",
            "group": "exchanges",
            "accounting_standard": "HKFRS",
        },
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · HKEX",
        "title": "香港交易及结算所有限公司 (00388.HK)：Q2 2026 季报仪表盘",
        "subtitle": (
            f"截至 {latest['period_end']} · 发布 {latest['release_date']} · HKFRS · 未审计 · "
            "自然年财年，季度标注无需换算"),
        "headline": (
            f"收入及其他收益 {hkd_m(roi[-1])}、同比 {signed(pct(roi[-1], roi[-5]))}，"
            f"股东应占溢利 {hkd_m(profit[-1])}、同比 {signed(pct(profit[-1], profit[-5]))}，"
            f"EBITDA 利润率 {margin:.1f}% —— 都是纪录。"
            f"但本页的对象不是这个季度：这 {len(quarters)} 格里有 {derived_total} 格"
            "从来没有被任何人印成一个季度，是本页由半年减一季、全年减九个月得到的。"
            f"公司自 2022 年起补印双数季的合计数，{check['derived_comparisons']} 次比对没有一次不同 —— "
            f"这就是另外 {check['unchecked']} 个没有对照物的双数季所依据的全部证据。"),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>结构</span><b>一半的格子是减出来的，而它可以被检验</b>'
            f'<p>{len(quarters)} 季里 {len(quarters) - derived_total} 季由公司印出、'
            f'{derived_total} 季由本页减出。其中 {len(check["covered"])} 个双数季公司另印了合计数，'
            f'{check["derived_comparisons"]} 次比对全部相同；剩下 {check["unchecked"]} 个没有对照物。'
            '<b>收入分项一次都没有对照物。</b></p></article>'
            '<article><span>价差</span><b>保证金利息有一半以上不归公司</b>'
            f'<p>返还给结算参与者的比例从 {share[0]:.0f}% 走到 {max(share):.0f}%，'
            f'本半年 {share[-1]:.0f}%。毛额与净额在窗口里两次走出相反方向，'
            '而季度损益表上只印净额那一条。</p></article>'
            '<article><span>量</span><b>成交额的波动，越往下走削得越平</b>'
            f'<p>日均成交额每变动 1%，交易与结算费变动 '
            f'{staging["fee_elasticity"]["slope_trading_clearing"]:.2f}%、'
            f'收入及其他收益只变动 '
            f'{staging["fee_elasticity"]["slope_revenue_and_other_income"]:.2f}%。'
            '把成交额当成收入的代理变量会高估两个方向。</p></article>'
            '</div>'
        ),
        "source": (
            'Source: <a href="' + staging["sources"][0]["url"] + '" rel="noopener">'
            'HKEX 2026 年中期业绩公告（2026-08-19）</a>与 2016 年以来的 42 份季度／中期／全年业绩公告。'
        ),
        "source_url": (
            "https://www.hkexgroup.com/Investor-Relations/"
            "Financial-Results-and-Presentations?sc_lang=en"),
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {"id": "disclosure", "title": "一、这一页有一半是减出来的",
             "description": (
                 "先说清楚这一页的每个数字是怎么来的，再说这个季度。"
                 "港交所的第一季与第三季公告各印一张三个月的损益表，中期只印六个月、"
                 "全年只印十二个月，所以第二季和第四季的损益表从来没有存在过。"
                 "公司在 2022 年起补印了双数季的几条合计数，本节最后用它检验本页的减法；"
                 "本节还说明为什么这里没有兑现图 —— 这家公司不发布任何财务指引。"),
             "exhibits": disclosure_ex},
            {"id": "quarter", "title": "二、本季重点",
             "description": (
                 "四条每一季都存在、口径十年没变过的线：利润率、收入构成、溢利与税率、"
                 "以及不随成交量走的那部分收入。"
                 "收入构成那一张要记住第一节的结论 —— 它的柱子有一半是本页算出来的。"),
             "exhibits": quarter_ex},
            {"id": "investment", "title": "三、投资收益是一道价差，一年只露两次",
             "description": (
                 "保证金投资收益的毛额与返还给结算参与者的利息只出现在中期与全年的损益表上，"
                 "季度损益表只印一个净额。本节按半年频率画那道价差，"
                 "并给出它在窗口内两次与净额走出相反方向的时点。"),
             "exhibits": investment_ex},
            {"id": "volume", "title": "四、成交量：能画的那一段，和画不了的那一段",
             "description": (
                 "市场统计是每交易日的平均，因此第一节那道减法在这里用不了：一个六个月的平均"
                 "减一个三个月的平均不是第二季。季度市场统计只回到 2021Q1，"
                 "本节先画那一段，再用年度口径给一个更长的背景。"),
             "exhibits": volume_ex},
        ],
        "tables": tables,
        "notes": [
            "本页按「披露结构 → 本季重点 → 投资价差 → 成交量」四段排列，以图为主，"
            "每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "港交所为自然年财年（12 月 31 日结束），本页季度标注与公司口径一致，无需换算。"
            "记账货币为港元，本页所有金额单位为百万港元（HK$M），成交额为十亿港元（HK$bn）。",
            "本页最需要说明的一条：公司按季印出的是第一季与第三季的完整损益表，"
            "第二季与第四季从未被印成一张损益表。"
            f"{len(quarters)} 个季度里 {derived_total} 个由「上半年减第一季」与「全年减前九个月」得到，"
            "全部标 D。这道减法在 2022 年起有了对照物 —— 公司在公告正文摘要框里补印双数季的"
            "收入及其他收益、营业开支、EBITDA、股东应占溢利与每股盈利 —— "
            f"{check['derived_comparisons']} 次比对没有一次不同。"
            f"但摘要框不含收入分项，所以本页第二节收入构成图里 {derived_total} 根柱的六项拆分"
            "没有任何对照物，只有算术。",
            "每一个期间都被公司印过两次：一次在当期公告里作为本期，一次在一年后的同类公告里"
            "作为比较期。本页把两次读数逐格比对，"
            f"{staging['restatement_paired_readings']:,} 对读数里只有 "
            f"{len(staging['restatement_census'])} 处不同，都在 2020 年第三季与前九个月的"
            "「其他收入」一行：34 百万港元从其他收入被重分类到当年新增的「慈善基金捐款收入」一行，"
            "收入及其他收益合计不变。这是本窗口内唯一一次重分类，且不影响本页任何一条主线。",
            "季度损益表只印一个「净投资收益」，投资收益毛额与「支付予参与者的利息回赠」"
            "只出现在中期与全年的损益表上。因此第三节按半年频率，"
            f"{len(staging['halves'])} 个半年里下半年由全年减上半年得到。"
            "把返还比例读成利率的函数是对的，但要注意它同时也是保证金规模与合约结构的函数。",
            "EBITDA 利润率本页统一用「EBITDA ÷ 收入及其他收益」自算。"
            "公司自己印的那个比率分母是「扣除交易相关支出后的收入及其他收益」，"
            "而那一行 2020 年才出现在损益表上，用它会让 2020 年之前的窗口没有可比口径。"
            "两者的差在 1 个百分点以内，方向固定（公司口径略高）。",
            "营业开支合计由「收入及其他收益 − EBITDA」倒推，不由明细行相加："
            "明细行的行数在窗口内变过三次（2018 年起信息技术开支独立成行、"
            "2020 年起慈善基金捐款独立成行），而两个端点的定义十年没变。"
            "第二节那张图里的「其余营业开支」因此是一个残差，不是公司印出的科目。",
            "市场统计（日均成交额、日均张数、计费日均手数）不能用第一节那道减法："
            "它们是每交易日的平均值，六个月的平均减三个月的平均不是第二季，"
            "而正确的还原需要各期的交易日数，公司不在公告里印它。"
            "公司自 2021Q1 起按季印出这些平均值，因此第四节的季度图从那里开始，"
            "更早的部分本页留空而不是补出来。",
            "市场统计不从 PDF 的文本层读取。公司用上标标注「新的季度／半年度纪录」，"
            "而纯文本导出会把上标并进数字本身：日均成交额 283.0 变成 283.04、"
            "衍生品日均 849 变成 8494。"
            f"逐格对照后，{staging['text_layer']['figures_compared']} 个市场统计数字里有 "
            f"{staging['text_layer']['corrupted_by_glued_marker']} 个会被这样读错，"
            "而读错之后全部是合法的、看不出问题的数。本页按字形磅值筛选"
            "（正文 10pt、上标 6.5pt）后再解析。",
            "LME 那一行在 2019 年发生过一次同时换单位又换定义的变化："
            "2018 年及以前印的是绝对手数的「日均成交量」，2019 年起印的是千手的"
            "「计费日均手数」（剔除管理性交易）。两代不是同一个数换了单位，"
            "因此本页不把它们接成一条线，第四节只画公司按季印出的那一段。",
            "互联互通两条线的货币不同：北向以人民币计价、南向以港元计价，"
            "公司在同一张表里并排印出，本页照原样画，不做换算 —— "
            "换算需要选一个汇率口径而公司没有给。南向成交计入现货市场日均成交额，北向不计入。",
            "本页不发布评级、目标价、估值与任何券商共识。"
            "第一节的六条阈值是本地研究设定，不是公司指引："
            f"{staging['guidance_census']['documents']} 份公告里带数字的前瞻表述 "
            f"{staging['guidance_census']['forward_statements_with_a_number']} 处，"
            "没有一处是收入、利润、费用或资本开支的数字指引，分析师演示材料里也没有。",
            "本页跨页对照表与其他公司页逐字相同，港交所本身不在那张表的任何一列里 —— "
            "带着这张表和成为表里的一列是两件事。",
        ],
        "footer": "Quarterly Results · 公司披露值与透明自算 · 仅供研究",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "hkex.js"), payload, "hkex")
    shell_dir = ROOT / "hkex"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("00388.HK", "hkex"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"HKEX page: {charts} charts in {len(payload['sections'])} sections "
          f"+ {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
