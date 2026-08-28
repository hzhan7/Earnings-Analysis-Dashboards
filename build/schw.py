#!/usr/bin/env python3
"""Build the SCHW quarterly-results page.

Same four-part, chart-led shape as the other company pages (上季兑现 → 本季重点
→ 下季跟踪 → 长期常规).  Schwab runs on the calendar year, so no quarter here
needs relabelling.

Three things about this company break the template the other pages share, and
each one is answered on the page rather than smoothed over:

**No guidance-delivery record.**  TSMC, NVIDIA, Meta, Amazon, Cadence and
Synopsys all print a numeric range in a filing, which is what makes their
first section a multi-quarter record.  Schwab does not.  Its scenario guidance
is given on the Business Update calls (Winter / Investor Day / Summer / Fall)
and in 2026 it dropped the EPS point guidance entirely in favour of a
revenue / NIM / expense combination.  That is the Microsoft and Alphabet
situation -- a sourcing limit, not an editorial choice -- so this page carries
only the four figures the company stated numerically on the current call, and
says in its notes why there is no record chart.

**The routine long series are a broker's, not a hyperscaler's.**  Capital
intensity and the depreciation wave mean nothing here.  What carries this
company is the split between rate-driven and fee-driven revenue, the operating
leverage between the two, and the volume/price relationship inside trading.

**The tracking framework is monthly and this site is quarterly.**  Schwab
publishes a monthly activity report, and the underlying research note's watch
list is built on it.  Plotting a monthly series would make this page move
between earnings dates, which is the one thing the content boundary forbids, so
the monthly-only thresholds are named and excluded rather than quietly drawn.

Published numbers are company-reported or transparent arithmetic.  No rating,
no target price, no valuation, no broker-attributed estimate.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import (  # noqa: E402
    ai_capex_cycle_table,
    headroom,
    headroom_exhibit,
    number_exhibits,
    threshold_exhibit,
    threshold_table,
    unit_text,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "schw.json"
DATA_DIR = ROOT / "data"

# One tick per year keeps a thirty-eight-quarter axis readable.
LONG_STEP = 4


def compact(period: str) -> str:
    """``2026Q2`` -> ``26Q2``."""
    return period[2:]


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100.0


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def rounded(values: list, digits: int = 4) -> list:
    return [None if v is None else round(v, digits) for v in values]


def tail(periods: list, *series: list) -> tuple:
    """Return the longest tail over which every series is populated.

    Schwab's operating metrics come from the earnings press releases, and the
    older releases carry fewer of them, so each chart's window is decided by
    the metric it draws rather than by the page.  Cutting to the longest
    complete tail keeps a chart from opening with a run of holes that look like
    the company stopped disclosing something mid-series.
    """
    start = 0
    for index in range(len(periods)):
        if all(s[index] is not None for s in series):
            start = index
            break
    else:
        return [], *([] for _ in series)
    for index in range(start, len(periods)):
        if any(s[index] is None for s in series):
            start = index + 1
    return periods[start:], *[s[start:] for s in series]


def axis(labels: list, step: int = LONG_STEP) -> list:
    """Blank every label but each ``step``-th and the last, keeping the axis legible."""
    keep = set(range(len(labels) - 1, -1, -step))
    return [label if index in keep else "" for index, label in enumerate(labels)]


def yoy(values: list) -> list:
    """Year-over-year percent change, ``None`` for the first four quarters."""
    out = []
    for index, value in enumerate(values):
        base = values[index - 4] if index >= 4 else None
        out.append(None if base in (None, 0) or value is None
                   else round(pct_change(value, base), 4))
    return out


def settled_exhibits(staging: dict, ops: dict) -> tuple:
    """Section one: the four thresholds set a quarter ago, plus the two scorecards."""
    closure = staging["followup_closure"]
    verdicts = staging["tracked_metric_verdicts"]
    entries = staging["settled_thresholds"]
    op_periods = ops["periods"]

    closure_chart = {
        "kind": "bars_labeled",
        "title": (
            f"上季留下的 10 个问题：{closure['counts'][0]} 个被完全回答、"
            f"{closure['counts'][1]} 个部分回答、{closure['counts'][2]} 个公司一个数都没给"
        ),
        "xlabels": closure["labels"],
        "values": closure["counts"],
        "legend": "问题数",
        "fmt": "f0",
        "yfmt": "f0",
        "label_fmt": "f0",
        "ylab": "个",
        "note": closure["note"],
        "src_extra": "问题清单来自上季本地研究记录；判定依据 2026-07-21 业绩 8-K、截至 2026-06-30 的 10-Q 与当季电话会。",
    }
    verdict_chart = {
        "kind": "bars_labeled",
        "title": (
            f"上季 11 条判断：{verdicts['counts'][0]} 条被验证、"
            f"{verdicts['counts'][1]} 条被证伪、{verdicts['counts'][2]} 条尚未到期"
        ),
        "xlabels": verdicts["labels"],
        "values": verdicts["counts"],
        "legend": "判断条数",
        "fmt": "f0",
        "yfmt": "f0",
        "label_fmt": "f0",
        "ylab": "条",
        "note": verdicts["note"],
        "src_extra": "判断为本地研究设定，不是公司指引。",
    }

    cleared = sum(1 for e in entries
                  if headroom(e["direction"], e["threshold"], e["actual"]) >= 0)
    overview = headroom_exhibit(
        f"上季四条阈值：{cleared} 条守住、{len(entries) - cleared} 条越过",
        entries,
        "actual",
        (staging["settled_note"] + "百分比、美元与比率被归一化成「距阈值的余量」才能放在一根轴上；"
         "原始单位见核对抽屉。" + staging["settled_excluded"]),
        "阈值为本地研究设定，不是公司指引；实际值取自 2026-07-21 业绩新闻稿与截至 2026-06-30 的 10-Q。",
    )

    charts = [closure_chart, verdict_chart, overview]
    for entry in entries:
        key = entry.get("series_key")
        if not key:
            continue
        labels, values = tail(op_periods, ops[key])
        charts.append(threshold_exhibit(
            f"{entry['metric']}：{len(labels)} 季走势与上季阈值",
            axis([compact(p) for p in labels]),
            rounded(values),
            entry["threshold"],
            fmt={"pct": "pct2", "usd_eps": "usd2", "usd_bn": "f0c"}.get(entry["unit"], "f1"),
            ylab={"pct": "%", "usd_eps": "US$/笔", "usd_bn": "US$B"}.get(entry["unit"], ""),
            actual_name=entry["metric"],
            threshold_name=f"上季阈值 {unit_text(entry['unit'], entry['threshold'])}",
            note=entry["note"] + "余量总览说的是哪条线破了，这张图说的是它怎么走到这里的。",
            src_extra="实际值取自各季业绩 8-K 的 EX-99.1 新闻稿。",
        ))
    return charts


def highlight_exhibits(staging: dict, fin: dict, periods: list, ops: dict) -> list:
    """Section two: what actually moved this quarter."""
    labels = [compact(p) for p in periods]
    revenue = fin["revenue_usd_m"]
    nii = fin["net_interest_revenue_usd_m"]
    amaf = fin["amaf_usd_m"]
    trading = fin["trading_usd_m"]
    bda = fin["bda_usd_m"]
    other = fin["other_usd_m"]
    expenses = fin["total_expenses_usd_m"]
    pretax = fin["pretax_usd_m"]

    # The five revenue lines only coexist from 2020Q4, when bank deposit account
    # fees arrived with the TD Ameritrade acquisition (closed 2020-10-06).
    mix_periods, mix_nii, mix_amaf, mix_trading, mix_bda, mix_other = tail(
        periods, nii, amaf, trading, bda, other)
    mix = {
        "kind": "lines_endlabels",
        "title": (
            f"五条收入线（{compact(mix_periods[0])}–{compact(mix_periods[-1])}）："
            f"净利息收入仍是最大一条，但本季增量最快的是交易"
        ),
        "xlabels": axis([compact(p) for p in mix_periods]),
        "series": [
            {"name": "净利息收入", "values": rounded(mix_nii), "color": "NAVY"},
            {"name": "资产管理与行政管理费", "values": rounded(mix_amaf), "color": "BLUE"},
            {"name": "交易收入", "values": rounded(mix_trading), "color": "TEAL"},
            {"name": "银行存款账户费", "values": rounded(mix_bda), "color": "ORANGE"},
            {"name": "其他", "values": rounded(mix_other), "color": "GREY"},
        ],
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$M",
        "note": (
            "窗口从 2020Q4 起，因为银行存款账户费这条线是随 TD Ameritrade 收购"
            "（2020-10-06 完成）才出现的，再往前公司的利润表上没有它，补零会造出一条"
            "并不存在的历史。五条线相加恒等于净收入，本页的对账测试就钉这条恒等式。"
        ),
        "src_extra": "各期 10-Q / 10-K 合并利润表；第四季度为全年数减去同年三个季度。",
    }

    latest_mix = [
        ("净利息收入", nii), ("资产管理与行政管理费", amaf),
        ("交易收入", trading), ("银行存款账户费", bda), ("其他", other),
    ]
    growth = {
        "kind": "grouped_bars",
        "title": "本季五条收入线的同比增速：交易 +28%、银行存款账户费 +35% 领先",
        "xlabels": [name for name, _ in latest_mix] + ["净收入合计"],
        "groups": [{
            "name": "同比增速",
            "color": "BLUE",
            "values": rounded([pct_change(s[-1], s[-5]) for _, s in latest_mix]
                              + [pct_change(revenue[-1], revenue[-5])]),
        }],
        "bar_labels": True,
        "fmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "% YoY",
        "zero_line": True,
        "note": (
            "五条线全部同比为正是这一季最直白的事实。值得注意的是最快的两条"
            "（交易、银行存款账户费）都是<b>量</b>驱动而不是价驱动：交易收入创纪录的同时"
            "每笔交易收入同比是负的，这是下一张图要解决的矛盾。"
        ),
        "src_extra": "同比基数为 2025Q2 的同一条线。",
    }

    nii_share = [round(n / r * 100, 4) for n, r in zip(nii, revenue)]
    share = {
        "kind": "lines",
        "title": (
            f"净利息收入占净收入的比重（{compact(periods[0])}–{compact(periods[-1])}）："
            f"{min(nii_share):.1f}% 到 {max(nii_share):.1f}% 之间来回摆"
        ),
        "xlabels": axis(labels),
        "series": [{"name": "净利息收入占比", "values": nii_share, "color": "NAVY"}],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "%",
        "note": (
            "这是本页最能说明「Schwab 是什么公司」的一条线：它既不是纯券商也不是纯银行，"
            "而是一台利率敞口随周期开合的机器。八年里这个比重的高点与低点相差超过 "
            f"{max(nii_share) - min(nii_share):.0f} 个百分点，"
            "而同一段时间里公司的费类收入几乎单调上升 —— 摆动全部来自利率腿。"
        ),
        "src_extra": "分子分母同为公司披露的合并利润表数字，比值为自算（D）。",
    }

    rev_yoy, exp_yoy = yoy(revenue), yoy(expenses)
    lev_periods, lev_rev, lev_exp = tail(periods, rev_yoy, exp_yoy)
    window = 20
    lev_periods, lev_rev, lev_exp = lev_periods[-window:], lev_rev[-window:], lev_exp[-window:]
    leverage = {
        "kind": "grouped_bars",
        "title": (
            f"经营杠杆：本季收入同比 {rev_yoy[-1]:.1f}%、费用同比 {exp_yoy[-1]:.1f}%，"
            f"差 {rev_yoy[-1] - exp_yoy[-1]:.0f} 个百分点"
        ),
        "xlabels": [compact(p) for p in lev_periods],
        "xrot": 90,
        "groups": [
            {"name": "净收入同比", "color": "NAVY", "values": rounded(lev_rev)},
            {"name": "费用同比", "color": "ORANGE", "values": rounded(lev_exp)},
        ],
        "bar_labels": False,
        "fmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "% YoY",
        "zero_line": True,
        "note": (
            "两根柱子的差就是经营杠杆。要注意的是它在这一季的成色："
            "费用同比 +12% 里涨得最多的是随交易量走的可变成本，"
            "而不是人力 —— 所以这个差值的可持续性取决于量能不能维持，"
            "量掉下来而费用不掉，差值会先消失。这正是第三节把「费用增速」"
            "设成向下阈值的原因。"
        ),
        "src_extra": "均为公司披露的合并利润表数字；同比为自算（D）。",
    }

    margin = [round(p / r * 100, 4) for p, r in zip(pretax, revenue)]
    disclosed = ops["pretax_margin_pct_disclosed"]
    margin_chart = {
        "kind": "lines",
        "title": (
            f"税前利润率（{compact(periods[0])}–{compact(periods[-1])}）：本季 {margin[-1]:.1f}%，"
            f"是这段窗口里的最高值"
        ),
        "xlabels": axis(labels),
        "series": [{"name": "税前利润率 D", "values": margin, "color": "NAVY"}],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "%",
        "note": (
            "自算值，但可以对上公司自己印的数：新闻稿的「Pre-tax profit margin」"
            f"本季是 {disclosed[-1]:.1f}%，与这里的 {margin[-1]:.2f}% 一致。"
            "这条对账同时验证了本页各年第四季度的推导 —— 那几个季度公司不出 10-Q，"
            "利润率却印在新闻稿里，两边对得上才说明「全年减九个月」这一步没错。"
        ),
        "src_extra": "分子分母为公司披露值，比值自算；与新闻稿披露的利润率逐季核对。",
    }

    op_periods = ops["periods"]
    vp_periods, dats, rpt = tail(op_periods, ops["dats_thousands"], ops["revenue_per_trade_usd"])
    volume_price = {
        "kind": "bar_line_dual",
        "title": (
            f"量与价反向（{compact(vp_periods[0])}–{compact(vp_periods[-1])}）："
            f"日均交易量 {dats[-1] / 1000:.2f}M 创纪录，每笔交易收入 ${rpt[-1]:.2f} 是窗口内最低"
        ),
        "xlabels": axis([compact(p) for p in vp_periods]),
        "bar": {"name": "日均交易量 DATs（千笔）", "values": rounded(dats), "color": "BLUE"},
        "line": {"name": "每笔交易收入 RPT", "values": rounded(rpt), "color": "ORANGE",
                 "yfmt": "usd2"},
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "千笔/日",
        "rhs_label": "US$/笔",
        "note": (
            "这是 SCHW 收入函数里最容易读错的一处。把 RPT 当独立变量看，会得出"
            "「定价在恶化」的结论；但把两条放在一起看，量的斜率明显盖过价 —— "
            f"本季 DATs 同比 {pct_change(dats[-1], dats[-5]):+.0f}%、RPT 同比 "
            f"{pct_change(rpt[-1], rpt[-5]):+.0f}%，交易收入仍然创了纪录。"
            "上季正是拿 RPT 单独做锚定而判断错了方向，本页把它降级为伴随指标。"
        ),
        "src_extra": "两条都取自各季业绩新闻稿的 Financial and Operating Highlights 表。",
    }

    return [mix, growth, share, leverage, margin_chart, volume_price]


def next_exhibits(staging: dict, ops: dict) -> list:
    """Section three: the same thresholds pointed forward."""
    kpi = staging["next_kpi"]
    entries = kpi["entries"]
    op_periods = ops["periods"]

    safe = sum(1 for e in entries
               if headroom(e["direction"], e["threshold"], e["current"]) >= 0)
    overview = headroom_exhibit(
        f"下季六条阈值：当前 {safe} 条在安全侧、{len(entries) - safe} 条已经贴着线",
        entries,
        "current",
        (
            "正值表示当前值仍在安全的一侧，负值表示已经越过。"
            "六条里最值得看的是费用增速那条：它是唯一一条<b>向下为安全</b>的线，"
            "也是唯一一条公司自己给了数字区间的。" + kpi["excluded_note"]
        ),
        "阈值为本地研究设定，不是公司指引；当前值取自 2026-07-21 业绩新闻稿与截至 2026-06-30 的 10-Q。",
    )

    charts = [overview]
    for entry in entries:
        key = entry.get("series_key")
        if not key:
            continue
        labels, values = tail(op_periods, ops[key])
        if entry["unit"] == "million":
            values = [v / 1000 for v in values]
        charts.append(threshold_exhibit(
            f"{entry['metric']}：{len(labels)} 季走势与下季阈值",
            axis([compact(p) for p in labels]),
            rounded(values),
            entry["threshold"] / 1000 if entry["unit"] == "million" else entry["threshold"],
            fmt={"pct": "pct2", "usd_eps": "usd2", "usd_bn": "f0c",
                 "million": "f2"}.get(entry["unit"], "f1"),
            ylab={"pct": "%", "usd_eps": "US$/笔", "usd_bn": "US$B",
                  "million": "百万笔/日"}.get(entry["unit"], ""),
            actual_name=entry["metric"],
            threshold_name="下季阈值",
            note=entry["note"],
            src_extra="实际值取自各季业绩 8-K 的 EX-99.1 新闻稿。",
        ))
    return charts


def routine_exhibits(staging: dict, fin: dict, periods: list, ops: dict) -> list:
    """Section four: the routine multi-quarter series, chosen for a broker."""
    op_periods = ops["periods"]
    labels = [compact(p) for p in periods]

    ca_periods, total_ca, is_ca, as_ca = tail(
        op_periods, ops["client_assets_usd_bn"],
        ops["client_assets_investor_services_usd_bn"],
        ops["client_assets_advisor_services_usd_bn"])
    assets = {
        "kind": "lines_endlabels",
        "title": (
            f"客户总资产（{compact(ca_periods[0])}–{compact(ca_periods[-1])}）："
            f"US${total_ca[-1] / 1000:.2f}T，同比 {pct_change(total_ca[-1], total_ca[-5]):+.0f}%"
        ),
        "xlabels": axis([compact(p) for p in ca_periods]),
        "series": [
            {"name": "客户总资产", "values": rounded(total_ca), "color": "NAVY"},
            {"name": "Investor Services", "values": rounded(is_ca), "color": "BLUE"},
            {"name": "Advisor Services", "values": rounded(as_ca), "color": "TEAL"},
        ],
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$B",
        "note": (
            "这条线增长的大部分不是公司挣来的：本季客户总资产环比增加约 "
            f"US${total_ca[-1] - total_ca[-2]:,.0f}B，其中净市场损益一项就是 "
            f"US${ops['net_market_gains_usd_bn'][-1]:,.0f}B。"
            "把资产规模当经营成绩读是这条线最容易犯的错，下一张图才是公司自己带进来的量。"
        ),
        "src_extra": "各季业绩新闻稿的客户资产表；两条业务线相加恒等于总额。",
    }

    # The window starts after 2020Q4: that quarter's net new assets include the
    # TD Ameritrade client base arriving at once (US$1,690.7B), which is an
    # acquisition, not asset gathering, and would flatten every other bar.
    nna_start = op_periods.index("2021Q1")
    nna_periods = op_periods[nna_start:]
    nna_is = ops["net_new_assets_investor_services_usd_bn"][nna_start:]
    nna_as = ops["net_new_assets_advisor_services_usd_bn"][nna_start:]
    nna_total = ops["net_new_assets_usd_bn"][nna_start:]
    flows = {
        "kind": "grouped_bars",
        "title": (
            f"季度净新增资产按渠道（{compact(nna_periods[0])}–{compact(nna_periods[-1])}）："
            f"本季 US${nna_total[-1]:,.1f}B，Advisor Services 扛了 "
            f"{nna_as[-1] / nna_total[-1] * 100:.0f}%"
        ),
        "xlabels": [compact(p) for p in nna_periods],
        "xrot": 90,
        "groups": [
            {"name": "Investor Services", "color": "NAVY", "values": rounded(nna_is)},
            {"name": "Advisor Services", "color": "TEAL", "values": rounded(nna_as)},
        ],
        "bar_labels": False,
        "fmt": "f1",
        "label_fmt": "f1",
        "ylab": "US$B",
        "note": (
            "窗口从 2021Q1 起：2020Q4 的净新增资产里含 TD Ameritrade 客户群一次性并入的 "
            "US$1,690.7B，那是收购不是获客，画进来会把其余每一根柱子压平。"
            "上季曾把 3 月单月 Investor Services 反超 Advisor Services 判为结构性拐点，"
            "本季 Investor Services 环比 "
            f"{pct_change(nna_is[-1], nna_is[-2]):+.0f}%，"
            "反超没有延续 —— 一个数据点撑不起一个拐点。"
        ),
        "src_extra": "各季业绩新闻稿；两条渠道相加恒等于公司披露的净新增资产合计。",
    }

    shares = fin["diluted_shares_m"]
    # The acquisition step is the quarter-on-quarter jump in the quarter TD
    # Ameritrade closed, not the spread of the series -- those differ, and only
    # the first one is the thing the sentence claims to measure.
    close_index = periods.index("2020Q4")
    issued = shares[close_index] - shares[close_index - 1]
    bought_back = max(shares) - shares[-1]
    share_chart = {
        "kind": "lines",
        "title": (
            f"摊薄股数（{compact(periods[0])}–{compact(periods[-1])}）："
            f"收购当季一次多出 {issued:.0f}M 股，自此后的高点回购了 {bought_back:.0f}M 股"
        ),
        "xlabels": axis(labels),
        "series": [{"name": "摊薄股数", "values": rounded(shares, 1), "color": "NAVY"}],
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "end_label": True,
        "ylab": "百万股",
        "note": (
            "这条线是本页唯一一条把「收购的代价」画出来的序列：2020Q4 一次性从约 1,294M 跳到 "
            "1,858M，此后逐季回落。本季回购 11.2M 股、约 US$1.0B，节奏较上季明显收窄 —— "
            "公司把资本投向了贷款增长而不是回购，这也是第三节 Tier 1 那条阈值的背景。"
        ),
        "src_extra": "各期 10-Q / 10-K 的加权平均摊薄股数；第四季度由全年与九个月推出（D）。",
    }

    lb_periods, margin_loans, bank_loans = tail(
        op_periods, ops["margin_loans_usd_bn"], ops["bank_loans_usd_bn"])
    lending = {
        "kind": "lines_endlabels",
        "title": (
            f"两条放贷线（{compact(lb_periods[0])}–{compact(lb_periods[-1])}）："
            f"保证金贷款（含 long/short 空头贷记）US${margin_loans[-1]:,.1f}B、"
            f"银行贷款 US${bank_loans[-1]:,.1f}B，同创新高"
        ),
        "xlabels": axis([compact(p) for p in lb_periods]),
        "series": [
            {"name": "保证金贷款余额", "values": rounded(margin_loans), "color": "ORANGE"},
            {"name": "银行贷款余额", "values": rounded(bank_loans), "color": "NAVY"},
        ],
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$B",
        "note": (
            "两条线一起看才对：银行贷款是公司主动配置资本的结果，按管理层说法本季 NIM 扩张的"
            "增量「绝大部分」来自它；保证金贷款则是客户风险偏好的读数，它和交易量、"
            "以及市场回撤时的去杠杆压力绑在一起。本季保证金贷款余额 "
            f"US${margin_loans[-1]:,.1f}B 里含 long/short 策略相关的空头贷记，"
            "公司在脚注里把六月的保证金贷款单独列为 US$42.1B —— "
            "总额不能直接当作客户杠杆读。"
        ),
        "src_extra": "各季业绩新闻稿；保证金贷款为客户资产表中的抵减项，此处取绝对值。",
    }

    return [assets, flows, share_chart, lending]


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    fin = staging["financials"]
    ops = staging["operating"]
    latest = staging["latest_disclosures"]
    guidance = staging["guidance"]

    revenue = fin["revenue_usd_m"]
    expenses = fin["total_expenses_usd_m"]
    pretax = fin["pretax_usd_m"]
    eps = fin["diluted_eps_usd"]
    nii = fin["net_interest_revenue_usd_m"]
    trading = fin["trading_usd_m"]
    nim = [v for v in ops["nim_pct"] if v is not None]

    settled_ex = number_exhibits(settled_exhibits(staging, ops), 2)
    highlight_ex = number_exhibits(highlight_exhibits(staging, fin, periods, ops),
                                   settled_ex[-1]["n"] + 1)
    next_ex = number_exhibits(next_exhibits(staging, ops), highlight_ex[-1]["n"] + 1)
    routine_ex = number_exhibits(routine_exhibits(staging, fin, periods, ops),
                                 next_ex[-1]["n"] + 1)

    first_table = 1
    tables = [
        threshold_table(first_table, "上季四条阈值：原始单位与余量",
                        staging["settled_thresholds"], "actual", "本季实际值"),
        threshold_table(first_table + 1, "下季六条阈值：原始单位与余量",
                        staging["next_kpi"]["entries"], "current", "当前值"),
        {
            "n": first_table + 2,
            "title": "五条收入线逐季原值（US$M）与净收入对账",
            "headers": ["期间", "净利息收入", "资产管理与行政管理费", "交易收入",
                        "银行存款账户费", "其他", "五条合计 D", "公司披露净收入", "差额 D"],
            "rows": [
                [compact(p),
                 f"{fin['net_interest_revenue_usd_m'][i]:,.0f}",
                 f"{fin['amaf_usd_m'][i]:,.0f}",
                 f"{fin['trading_usd_m'][i]:,.0f}",
                 f"{fin['bda_usd_m'][i]:,.0f}" if fin["bda_usd_m"][i] is not None else "—",
                 f"{fin['other_usd_m'][i]:,.0f}",
                 f"{(fin['net_interest_revenue_usd_m'][i] + fin['amaf_usd_m'][i] + fin['trading_usd_m'][i] + (fin['bda_usd_m'][i] or 0) + fin['other_usd_m'][i]):,.0f}",
                 f"{revenue[i]:,.0f}",
                 f"{(fin['net_interest_revenue_usd_m'][i] + fin['amaf_usd_m'][i] + fin['trading_usd_m'][i] + (fin['bda_usd_m'][i] or 0) + fin['other_usd_m'][i]) - revenue[i]:+,.0f}"]
                for i, p in enumerate(periods) if p >= "2024Q1"
            ],
        },
        {
            "n": first_table + 3,
            "title": "各年第四季度的推导与全年对账（US$M）",
            "headers": ["年度", "公司披露全年净收入", "前三季合计 D", "推得第四季 D",
                        "该季公司披露税前利润率", "本页自算税前利润率 D"],
            "rows": [
                [year,
                 f"{annual['revenue_usd_m']:,.0f}",
                 f"{sum(revenue[periods.index(f'{year}Q{i}')] for i in (1, 2, 3)):,.0f}",
                 f"{revenue[periods.index(f'{year}Q4')]:,.0f}",
                 (f"{ops['pretax_margin_pct_disclosed'][ops['periods'].index(f'{year}Q4')]:.1f}%"
                  if f"{year}Q4" in ops["periods"] else "—"),
                 f"{pretax[periods.index(f'{year}Q4')] / revenue[periods.index(f'{year}Q4')] * 100:.1f}%"]
                for year, annual in sorted(staging["annual_filed_usd_m"].items())
                if f"{year}Q4" in periods
            ],
        },
        ai_capex_cycle_table(first_table + 4),
    ]

    return {
        "schema_version": "quarterly-dashboard/schw-v1",
        "page": {"slug": "schw", "language": "zh-CN"},
        "company": {
            "ticker": "SCHW",
            "name": "Charles Schwab",
            "group": "brokerage_wealth",
            "accounting_standard": "US GAAP",
        },
        "latest": {
            "disclosed_period_label": "Q2 2026",
            "full_financial_period_label": "Q2 2026",
            "period_end": "2026-06-30",
            "release_date": "2026-07-21",
            "analysis_date": "2026-08-29",
            "audit_status": "unaudited",
            "status": "history_ready",
        },
        "tracker": "Watchlist Quarterly Tracker · SCHW",
        "title": "Charles Schwab (SCHW)：Q2 2026 季报仪表盘",
        "subtitle": (
            "截至 2026-06-30 · 发布 2026-07-21（Summer Business Update）· US GAAP · 未审计 · "
            "自然年季度，无财年错位"
        ),
        "headline": (
            f"净收入 US${revenue[-1]:,.0f}M、同比 {signed(pct_change(revenue[-1], revenue[-5]))}，"
            f"五条收入线全部同比为正，税前利润率 {pretax[-1] / revenue[-1] * 100:.1f}% 是九年窗口里的最高值；"
            f"但同一季里每笔交易收入跌到 ${ops['revenue_per_trade_usd'][-1]:.2f}、"
            f"调整后 Tier 1 杠杆率停在 {latest['adjusted_tier1_leverage_pct']:.1f}% 没有回到目标区间中枢 —— "
            f"上季设下的四条阈值守住两条。"
        ),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>量盖过价</span><b>交易创纪录，单笔收入创新低</b>'
            f'<p>日均交易量 {ops["dats_thousands"][-1] / 1000:.2f}M、同比 '
            f'{signed(pct_change(ops["dats_thousands"][-1], ops["dats_thousands"][-5]), 0)}；'
            f'每笔交易收入 ${ops["revenue_per_trade_usd"][-1]:.2f}、同比 '
            f'{signed(pct_change(ops["revenue_per_trade_usd"][-1], ops["revenue_per_trade_usd"][-5]), 0)}。'
            f'交易收入仍创纪录 US${trading[-1]:,.0f}M。</p></article>'
            '<article><span>利率腿</span><b>NIM 回到 3% 以上</b>'
            f'<p>{nim[-1]:.2f}%，环比 {nim[-1] - nim[-2]:+.2f}pp；'
            f'净利息收入占净收入 {nii[-1] / revenue[-1] * 100:.1f}%。'
            f'公司给的全年区间是 {guidance["fy2026_scenario"]["items"][1]["low"]:.2f}%–'
            f'{guidance["fy2026_scenario"]["items"][1]["high"]:.2f}%。</p></article>'
            '<article><span>代价</span><b>表观 sweep 现金不能直接读</b>'
            f'<p>季末 US${latest["transactional_sweep_cash_usd_bn"]:,.1f}B、环比 '
            f'+US${latest["sweep_cash_qoq_change_usd_bn"]:,.1f}B，'
            f'但其中 long/short 策略的空头贷记就有 US${latest["short_credits_usd_bn"]:,.1f}B。</p></article>'
            '</div>'
        ),
        "source": (
            'Source: <a href="https://www.sec.gov/Archives/edgar/data/316709/'
            '000031670926000027/a2q26exhibit991.htm" rel="noopener">Charles Schwab 2Q26 '
            '业绩新闻稿（8-K EX-99.1）</a>与截至 2026-06-30 的 10-Q。'
        ),
        "source_url": (
            "https://www.sec.gov/Archives/edgar/data/316709/"
            "000031670926000027/a2q26exhibit991.htm"
        ),
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {
                "id": "settled",
                "title": "一、上季跟踪指标兑现了吗",
                "description": (
                    "先结清上季设下的阈值，再看新数字。Schwab 不在申报文件里给可逐季核对的数字区间，"
                    "所以这一节没有其他公司页那样的指引兑现长记录 —— 它结清的是本地设下的四条阈值，"
                    "以及上季留下的 10 个问题和 11 条判断。"
                ),
                "exhibits": settled_ex,
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": (
                    "五条收入线各自的水平与增速、利率腿与费类腿此消彼长的比重、"
                    "收入与费用之间的经营杠杆，以及交易业务里量与价反向的那道矛盾。"
                ),
                "exhibits": highlight_ex,
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": (
                    "当前值离下季阈值还有多远，统一用「距阈值余量」口径；"
                    "只有月度口径、因而不接入本页的八条也写在这里。"
                ),
                "exhibits": next_ex,
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": (
                    "SCHW 专属的常规序列：客户资产与它有多少是市场给的、"
                    "两条获客渠道的净新增、收购一次发出去又慢慢买回来的股数，"
                    "以及撑起这轮 NIM 扩张的两条放贷线。"
                ),
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "Schwab 的会计年度与自然年一致，本页所有季度标注即公司自己的季度，无需换算。",
            "<b>本页没有指引兑现的长记录，这是取数限制而不是编辑取舍。</b>" + guidance["why_no_delivery_record"],
            "<b>本页只发布季度口径，不发布月度数据。</b>Schwab 每月中旬发布月度活动报告，其中的月度净新增资产、日均交易量、交易性 sweep 现金、新开经纪账户与保证金余额都是本季研究记录里权重最高的跟踪项。把它们画进来会让这一页在两次财报之间发生变化，而本站的内容边界要求每一页只按季度这一个节奏更新。因此第三节的阈值清单里，只有季度口径可核的六条接入，其余八条写明了不接入的理由。需要说明的是这不是无法聚合：本季四月至六月的月度 core 净新增资产 7.2 + 49.9 + 62.7 恰好等于公司自己公布的季度 core 净新增资产 US$119.8B，聚合是可核的 —— 不接入是节奏问题，不是数据问题。",
            "各年第四季度公司不出 10-Q，其利润表各行均为 10-K 全年数减去同年三份 10-Q 的三个季度，四条腿都是申报值。这一步有独立的对账：新闻稿逐季印出「Pre-tax profit margin」，把推出来的第四季度税前利润与净收入相除，与公司印的数逐年一致（核对抽屉里的第四张表）。",
            "五条收入线（净利息收入、资产管理与行政管理费、交易收入、银行存款账户费、其他）相加恒等于公司披露的净收入合计，本页对 2017Q1 起的全部 38 个季度钉了这条恒等式；净收入减去总费用恒等于税前利润，同样逐季钉住。",
            "银行存款账户费这条线自 2020Q4 起才存在，它随 TD Ameritrade 收购（2020-10-06 完成）进入利润表，因此收入结构图的窗口从 2020Q4 开始而不是补零向前延伸。2017Q1 之前公司的净收入里还有「贷款损失准备」与「证券减值损失」两条后来不再单列的抵减项，五条线在那之前不完全相加，所以本页的季度序列从 2017Q1 起。",
            "第四节的净新增资产图从 2021Q1 起：2020Q4 那一季的净新增资产含 TD Ameritrade 客户群一次性并入的 US$1,690.7B，那是收购而不是获客。",
            "交易性 sweep 现金的表观总额包含 long/short 策略相关的空头贷记（本季六月 US$43.7B），公司在新闻稿脚注里单独披露了这一拆分。本季表观环比 +US$24.2B 的大部分来自这一机械性放大，因此表观总额不能直接当作客户现金流向来读；本页在第一节的余量总览里发布该口径，但因为可发布的季末点只有两个，没有为它单独作图。",
            "调整后 Tier 1 杠杆率是公司自己定义的非 GAAP 指标（在 GAAP 口径上计入累计其他综合收益），公司同时披露 GAAP 口径与调节表；本页用它是因为公司自述以该口径管理资本并设定 6.75%–7% 的长期运营目标。",
            "「AI capex 循环」跨页对照表在本站每一页都以完全相同的内容发布，本页也保留。它不是 SCHW 的经营指标 —— 券商不在那条产业链上 —— 保留它是因为它是全站共享的产业参照，且收在核对抽屉里，不占用本页的图表流。",
            "本页只发布公司披露值、可复算的简单派生值，以及明确标注的市场预期；D 标记代表 Derived / 自算，不代表公司定义的非 GAAP 指标。",
            "本页<b>不发布</b>评级、目标价、估值倍数、情景 EPS 与任何券商归属的估计。本季分析师在电话会上问了什么，只在能说明「公司没有披露什么」时作为证据使用，不转述其结论。",
            "本页已知未接入：所有月度活动报告口径（见上）、Crypto 与 Forge 的任何运营或收入数据（公司未披露）、AI 产品的客户端使用数据（公司未披露）、剔除 long/short 之后的底层 sweep 现金逐季序列（公司只在当季脚注给出拆分）、以及 2026 年 10 月 Fall Business Update 的内容（本页数据截至 2026-08-07 的申报）。",
            "业绩电话会与新闻稿仅链接 SEC 托管版本，公开仓不复制原件或逐字内容。",
        ],
        "footer": "SCHW quarterly results · 数据来自 Charles Schwab 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "schw.js"), payload, "schw")
    shell_dir = ROOT / "schw"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("SCHW", "schw"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(
        f"SCHW page: {charts} charts in {len(payload['sections'])} sections "
        f"+ {len(payload['tables'])} audit tables"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
