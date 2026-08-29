"""MSCI Inc. quarterly dashboard.

MSCI is the first company on this site whose published guidance is **annual and
cost-side only**. Its "Full-Year Guidance" table -- in every earnings 8-K EX-99.1
since the Q3 2020 release -- guides total operating expense, adjusted EBITDA
expense, interest expense, D&A, the effective tax rate, capital expenditures,
operating cash flow and free cash flow. It never guides revenue and it never
guides EPS. So the first section of this page settles a *cost and cash* record
over six finished years rather than a revenue record over twenty-four quarters,
and the page says why.

The finding that record produces is two-sided and only visible because the same
table carries both legs. Measured against the LAST guidance of each year,
operating expense landed inside its range six times out of six. Measured against
the FIRST guidance of the same year, it landed inside three times out of six.
The perfect record is a product of revision, not of forecasting. Free cash flow
behaves the opposite way: it beat the top of the range four years out of six
against both the first and the last guidance, so revising it did not close the
gap -- the company simply generates more cash than it tells you it will.

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


STAGING_PATH = ROOT / "series" / "msci.json"
DATA_DIR = ROOT / "data"

# One tick per year keeps the thirty-one-quarter axes readable.
LONG_STEP = 4


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100.0


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def rounded(values, digits: int = 6):
    return [None if v is None else round(v, digits) for v in values]


def mid(low, high):
    return [(a + b) / 2 for a, b in zip(low, high)]


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


def annual_deviation(ref: str, metric: str, years: list[str], low: list[float],
                     high: list[float], actual: list[float], *, src_extra: str,
                     extra_note: str = "") -> dict:
    """Distance from the guided midpoint, for an ANNUAL record.

    ``board.midpoint_deviation`` hard-codes the word 季 into every sentence it
    builds, so an annual series renders as "7 季里 6 季为正". Rather than add a
    parameter to a shared helper that another session is already changing, this
    page builds its own annual twin; the arithmetic is the same.
    """
    midpoints = mid(low, high)
    deviation = [(a / m - 1) * 100 for a, m in zip(actual, midpoints)]
    above = sum(1 for v in deviation if v > 0)
    mean_abs = statistics.fmean(abs(v) for v in deviation)
    biggest = max(deviation, key=abs)
    return {
        "ref": ref,
        "kind": "grouped_bars",
        "title": (f"{metric}相对指引中值的偏离：{len(deviation)} 个完整年度里 {above} 年为正，"
                  f"平均绝对偏离 {mean_abs:.1f}%"),
        "xlabels": list(years),
        "groups": [{"name": f"实际{metric} vs 指引中值", "color": "BLUE",
                    "values": rounded(deviation)}],
        "bar_labels": True,
        "fmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "% vs 指引中值",
        "note": ("正值 = 高于指引区间的中值。"
                 f"窗口内最大的一次是 {years[deviation.index(biggest)]} 的 {biggest:+.1f}%。"
                 + extra_note),
        "src_extra": src_extra,
    }


def guidance_charts(staging: dict) -> tuple[list[dict], list[dict]]:
    """The annual guidance record: three metrics, band then deviation each."""
    hist = staging["annual_guidance_history"]
    finished = [y for y in hist["years"] if y < 2026]
    labels = [f"FY{y}" for y in finished]

    def legs(key):
        by_year = hist["items"][key]["by_year"]
        first_lo, first_hi, last_lo, last_hi, actual = [], [], [], [], []
        for y in finished:
            block = by_year[str(y)]
            guided = [g for g in block["guided"] if g]
            first_lo.append(guided[0][0]); first_hi.append(guided[0][1])
            last_lo.append(guided[-1][0]); last_hi.append(guided[-1][1])
            actual.append(block["actual"])
        return first_lo, first_hi, last_lo, last_hi, actual

    charts, tables = [], []
    spec = [
        ("operating_expense", "营业费用", "EX_OPEX"),
        ("adj_ebitda_expense", "调整后 EBITDA 费用", "EX_AEBX"),
        ("free_cash_flow", "自由现金流", "EX_FCF"),
    ]
    for key, name, ref in spec:
        flo, fhi, llo, lhi, act = legs(key)
        charts.append(delivery_band(
            f"{ref}_BAND", name, labels, llo, lhi, act,
            fmt="f0c", ylab="US$M", unit="US$M",
            venue="业绩新闻稿",
            timing="该年<b>当年内</b>",
            period_word="年",
            extra_note=(
                "这里画的是<b>当年最后一次</b>指引，不是年初那一次 —— MSCI 每季在业绩新闻稿里"
                "重新给一次全年指引，最后一次通常发布于 10 月底，此时全年已过去四分之三。"
                f"同一指标对<b>年初第一次</b>指引的兑现情况见 Exhibit {{{ref}_DEV}}。"),
            src_extra=("指引取自各年业绩 8-K EX-99.1 的 Full-Year Guidance 表；"
                       "实际值取自次年 Q4 发布中 Table 11 与 Table 12 的 Year Ended 列。"),
        ))
        charts.append(annual_deviation(
            f"{ref}_DEV", name, labels, llo, lhi, act,
            src_extra="偏离 = 实际值 ÷ 指引中值 − 1，中值取当年最后一次指引区间的中点。",
            extra_note=(
                "<b>同一年、同一指标，换成年初那次指引就是另一幅样子</b>："
                + "、".join(
                    f"{lab} 对年初指引{'高' if a > (lo + hi) / 2 else '低'}"
                    f" {abs(pct_change(a, (lo + hi) / 2)):.1f}%"
                    for lab, lo, hi, a in zip(labels, flo, fhi, act))
                + "。"),
        ))
        rows = [[lab,
                 f"${lo:,.0f}–{hi:,.0f}M", f"${l2:,.0f}–{h2:,.0f}M", f"${a:,.0f}M",
                 "区间内" if l2 <= a <= h2 else ("高于上限" if a > h2 else "低于下限")]
                for lab, lo, hi, l2, h2, a in zip(labels, flo, fhi, llo, lhi, act)]
        tables.append({"title": f"{name}：年初指引、年末指引与全年实际",
                       "headers": ["年度", "年初第一次指引", "当年最后一次指引", "全年实际", "对最后一次指引"],
                       "rows": rows})
    return charts, tables


def build_payload(staging: dict) -> dict:
    fin = staging["financials"]
    seg = staging["segments_usd_m"]
    om = staging["operating_metrics"]
    hist = staging["annual_guidance_history"]
    labels = staging["period_labels"]
    long_labels = om["period_labels"]

    revenue = fin["revenue_usd_m"]
    aum = om["aum_period_end_usd_b"]
    bp = om["aum_basis_point_fee"]
    run_rate = om["run_rate_total_usd_m"]

    settled, settled_tables = guidance_charts(staging)

    # ── section one: how the latest revision moved ──────────────────────────
    fy26 = {k: v["by_year"]["2026"] for k, v in hist["items"].items()}
    moves = []
    for key, name in [("operating_expense", "营业费用"),
                      ("adj_ebitda_expense", "调整后 EBITDA 费用"),
                      ("op_cash_flow", "经营现金流"),
                      ("capex", "资本开支"),
                      ("free_cash_flow", "自由现金流")]:
        guided = [g for g in fy26[key]["guided"] if g]
        first, last = guided[0], guided[-1]
        moves.append((name, pct_change((last[0] + last[1]) / 2, (first[0] + first[1]) / 2)))
    revision_chart = {
        "ref": "EX_FY26",
        "kind": "diverging_bars",
        "title": (f"FY2026 指引三次发布后的净移动：营业费用中值上调 {moves[0][1]:+.1f}%，"
                  f"自由现金流仅 {moves[4][1]:+.1f}%"),
        "xlabels": [m for m, _ in moves],
        "values": [round(v, 2) for _, v in moves],
        "legend": "相对年初指引中值的移动",
        "positive_label": "上调",
        "negative_label": "下调",
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1",
        "ylab": "% vs 年初指引中值",
        "zero_line": True,
        "note": ("<b>本季（2026-07-21）是 FY2026 指引第一次真正移动</b>：1 月与 4 月两次发布"
                 "逐字相同，7 月把营业费用、调整后 EBITDA 费用、利息与折旧摊销一起上调，"
                 "现金流两条只跟着抬了很小一步，资本开支完全没动。"
                 "费用抬得比现金流多，意味着公司把增量成本的现金影响判断为可吸收 —— "
                 "这条判断的兑现要等 FY2026 的 Q4 发布才能结清，届时会并入 Exhibit {EX_OPEX_BAND}。"),
        "src_extra": ("三次发布：2026-01-28、2026-04-21、2026-07-21 的业绩 8-K EX-99.1 "
                      "Full-Year Guidance 表；移动为最后一次中值相对第一次中值的百分比。"),
    }
    settled.insert(0, revision_chart)

    # ── section two: what moved this quarter ────────────────────────────────
    rec, abf, non = fin["recurring_usd_m"], fin["abf_usd_m"], fin["nonrecurring_usd_m"]
    mix_chart = {
        "ref": "EX_MIX",
        "kind": "grouped_bars",
        "title": (f"三条收入腿：资产型费用同比 "
                  f"{signed(pct_change(abf[-1], abf[-5]))}，订阅 "
                  f"{signed(pct_change(rec[-1], rec[-5]))}"),
        "xlabels": labels,
        "groups": [
            {"name": "经常性订阅", "color": "NAVY", "values": rounded(rec)},
            {"name": "资产型费用", "color": "BLUE", "values": rounded(abf)},
            {"name": "非经常性", "color": "GOLD", "values": rounded(non)},
        ],
        "fmt": "f0c", "label_fmt": "f0c", "ylab": "US$M",
        "note": ("<b>三条腿的性质不同</b>：订阅收入按合同确认、随 Run Rate 走；"
                 "资产型费用直接挂在挂钩 MSCI 股票指数的 ETF 资产规模上，随市场涨跌；"
                 "非经常性是一次性授权与咨询。"
                 f"本季资产型费用占总收入 {abf[-1] / revenue[-1] * 100:.1f}%，"
                 f"四个季度前是 {abf[-5] / revenue[-5] * 100:.1f}%。"
                 "三条相加等于合并收入，31 个季度逐季核对无差。"),
        "src_extra": "各季业绩 8-K EX-99.1 的 Table 5「Consolidated」区块。",
    }
    seg_names = [("index", "Index"), ("analytics", "Analytics"),
                 ("sustainability_climate", "Sustainability & Climate"),
                 ("private_assets", "All Other – Private Assets")]
    seg_rev_chart = {
        "ref": "EX_SEG",
        "kind": "grouped_bars",
        "title": (f"四个分部：Index 一家贡献本季收入的 "
                  f"{seg['index']['revenue'][-1] / revenue[-1] * 100:.0f}%"),
        "xlabels": labels,
        "groups": [{"name": name, "color": c,
                    "values": rounded(seg[key]["revenue"])}
                   for (key, name), c in zip(seg_names, ["NAVY", "BLUE", "GOLD", "RED"])],
        "fmt": "f0c", "label_fmt": "f0c", "ylab": "US$M",
        "note": ("Index 是唯一同时拥有订阅与资产型费用两条腿的分部，也是唯一在本窗口内"
                 "加速的分部。四个分部收入相加等于合并收入，逐季核对无差。"
                 "2021 年之前 ESG 与 Private Assets 合并为一个 All Other 分部，"
                 "本图窗口全部在拆分之后。"),
        "src_extra": "各季业绩 8-K EX-99.1 的 Table 5 四个分部区块。",
    }
    seg_margin_chart = {
        "ref": "EX_SEGM",
        "kind": "lines",
        "title": (f"分部调整后 EBITDA 利润率：Index "
                  f"{seg['index']['adj_ebitda_margin_pct'][-1]:.1f}%，"
                  f"Private Assets {seg['private_assets']['adj_ebitda_margin_pct'][-1]:.1f}%"),
        "xlabels": labels,
        "series": [{"name": name, "values": rounded(seg[key]["adj_ebitda_margin_pct"]),
                    "color": c}
                   for (key, name), c in zip(seg_names, ["NAVY", "BLUE", "GOLD", "RED"])],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
        "ylab": "调整后 EBITDA 利润率 %",
        "note": ("四条线之间的差距，比任何一条自己的变化都大：Index 的分部利润率长期在 75% 以上，"
                 "Private Assets 在 20% 出头。合并利润率因此主要由收入落在哪个分部决定，"
                 "而不是由任何一个分部自己的成本控制决定。"),
        "src_extra": "各季业绩 8-K EX-99.1 的 Table 5；分部利润率为公司披露值，不是自算。",
    }
    aum_chart = {
        "ref": "EX_AUM",
        "kind": "bar_line",
        "title": (f"挂钩 MSCI 股票指数的 ETF AUM 与基点费率："
                  f"AUM US${aum[-1]:,.0f}B，费率 {bp[-1]:.2f}bp"),
        "xlabels": long_labels,
        "bar": {"name": "期末 AUM", "values": rounded(aum), "color": "BLUE"},
        "line": {"name": "期末基点费率", "values": rounded(bp), "color": "RED", "yfmt": "f2"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "US$B",
        "xstep": LONG_STEP,
        "note": ("<b>这张图是这家公司的核心张力</b>：31 个季度里 AUM 从 US$696B 涨到 "
                 f"US${aum[-1]:,.0f}B（约 {aum[-1] / aum[0]:.1f} 倍），"
                 f"同期期末基点费率从 {max(v for v in bp if v is not None):.2f}bp 降到 {bp[-1]:.2f}bp。"
                 "资产型费用收入是两者相乘，所以规模增长里有一部分被费率稀释掉了。"
                 "费率序列自 2020Q2 起 —— 公司此前不披露这个数，图上因此从那里开始，不做回补。"),
        "src_extra": "各季业绩 8-K EX-99.1 的 Table 7；费率为公司披露的期末基点费率。",
    }
    rr_chart = {
        "ref": "EX_RR",
        "kind": "lines",
        "title": (f"Run Rate 与收入的同比增速：Run Rate "
                  f"{pct_change(run_rate[-1], run_rate[-5]):+.1f}%，收入 "
                  f"{pct_change(revenue[-1], revenue[-5]):+.1f}%"),
        "xlabels": long_labels[4:],
        "series": [
            {"name": "Run Rate 同比", "color": "NAVY",
             "values": rounded([pct_change(run_rate[i], run_rate[i - 4])
                                for i in range(4, len(run_rate))])},
            {"name": "收入同比", "color": "BLUE",
             "values": rounded([pct_change(om["revenue_usd_m"][i], om["revenue_usd_m"][i - 4])
                                for i in range(4, len(om["revenue_usd_m"]))])},
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
        "ylab": "同比 %", "xstep": LONG_STEP,
        "note": ("Run Rate 是公司对「按当前合同价格与资产规模，未来 12 个月能确认多少收入」"
                 "的口径，因此它领先收入。两条线的<b>差</b>比各自的水平更有意义："
                 "Run Rate 高于收入时，未来几个季度的收入还有上行空间。"),
        "src_extra": "Run Rate 取自各季 Table 8，收入取自 Table 5；同比为本页自算（D）。",
    }
    highlights = [mix_chart, seg_rev_chart, seg_margin_chart, aum_chart, rr_chart]

    # ── section three: what to watch next ───────────────────────────────────
    kpi = staging["next_kpi"]["quantified"]
    next_ex = [headroom_exhibit(
        f"下季 {len(kpi)} 条阈值：当前值离阈值的余量",
        kpi, "current",
        ("正值表示仍在安全侧。阈值为本地研究设定，<b>不是公司指引</b> —— "
         "MSCI 的公司指引只覆盖费用、税率、资本开支与现金流，见第一节。"
         + staging["next_kpi"]["excluded"]),
        "当前值为 2026Q2 披露值；阈值为本地研究设定。")]
    for entry in kpi:
        key_map = {
            "调整后 EBITDA 利润率": (om["adj_ebitda_margin_pct"], long_labels, "pct1", "%"),
            "ETF AUM 期末余额": (aum, long_labels, "f0c", "US$B"),
            "期末基点费率": (bp, long_labels, "f2", "bp"),
            "总留存率": (om["retention_rate_pct"], long_labels, "pct1", "%"),
        }
        if entry["metric"] not in key_map:
            continue
        values, xlab, fmt, unit = key_map[entry["metric"]]
        next_ex.append(threshold_exhibit(
            f"{entry['metric']}：当前 {entry['current']:.2f}{unit}，阈值 {entry['threshold']:.2f}{unit}",
            xlab, rounded(values), entry["threshold"],
            fmt=fmt, ylab=unit,
            actual_name=entry["metric"], threshold_name="本地阈值",
            note=("红线是本地研究设定的阈值，不是公司指引，也不是公司披露的目标。"
                  "序列从公司开始披露该指标的那一季起画，不向前回补。"),
            src_extra="各季业绩 8-K EX-99.1；阈值为本地研究设定。"))
        next_ex[-1]["xstep"] = LONG_STEP

    # ── section four: the long routine series ──────────────────────────────
    routine = [
        {
            "ref": "EX_MARGIN",
            "kind": "lines",
            "title": (f"31 季利润率：调整后 EBITDA {om['adj_ebitda_margin_pct'][-1]:.1f}%，"
                      f"经营 {om['operating_margin_pct'][-1]:.1f}%"),
            "xlabels": long_labels,
            "series": [
                {"name": "调整后 EBITDA 利润率", "values": rounded(om["adj_ebitda_margin_pct"]), "color": "NAVY"},
                {"name": "经营利润率", "values": rounded(om["operating_margin_pct"]), "color": "BLUE"},
            ],
            "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
            "ylab": "%", "xstep": LONG_STEP,
            "note": ("两条线的<b>缺口</b>就是折旧摊销加股权激励等被调整掉的成本，"
                     "31 季里它从 5.5pp 走到 "
                     f"{om['adj_ebitda_margin_pct'][-1] - om['operating_margin_pct'][-1]:.1f}pp。"
                     "每年第一季两条线同时下沉，是薪酬税与年度激励集中在 Q1 确认所致，"
                     "属于季节性而非趋势。"),
            "src_extra": "各季业绩 8-K EX-99.1 的 Table 5「Consolidated」区块，均为公司披露值。",
        },
        {
            "ref": "EX_RET",
            "kind": "lines",
            "title": (f"31 季总留存率：本季 {om['retention_rate_pct'][-1]:.1f}%，"
                      f"窗口内区间 {min(v for v in om['retention_rate_pct'] if v is not None):.1f}–"
                      f"{max(v for v in om['retention_rate_pct'] if v is not None):.1f}%"),
            "xlabels": long_labels,
            "series": [{"name": "总留存率", "values": rounded(om["retention_rate_pct"]), "color": "NAVY"}],
            "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
            "ylab": "%", "xstep": LONG_STEP,
            "note": ("留存率有强季节性：每年第四季是合同集中续约的季度，读数系统性低于其余三季。"
                     "跨年比较必须同季对同季，否则每年年底都会读出一次「恶化」。"),
            "src_extra": "各季业绩 8-K EX-99.1 的 Table 6；公司披露值。",
        },
        {
            "ref": "EX_RRMIX",
            "kind": "grouped_bars",
            "title": (f"Run Rate 的两条腿：订阅 US${om['run_rate_recurring_usd_m'][-1]:,.0f}M、"
                      f"资产型 US${om['run_rate_abf_usd_m'][-1]:,.0f}M"),
            "xlabels": long_labels,
            "groups": [
                {"name": "经常性订阅 Run Rate", "color": "NAVY",
                 "values": rounded(om["run_rate_recurring_usd_m"])},
                {"name": "资产型费用 Run Rate", "color": "BLUE",
                 "values": rounded(om["run_rate_abf_usd_m"])},
            ],
            "fmt": "f0c", "label_fmt": "f0c", "ylab": "US$M", "xstep": LONG_STEP,
            "note": ("资产型那条腿随市场波动，订阅那条腿不。2022 年的市场回撤在这张图上是"
                     "唯一一次资产型 Run Rate 连续三季下行，而订阅腿在同期继续上行 —— "
                     "这是这家公司抗周期性的直接读数。"),
            "src_extra": "各季业绩 8-K EX-99.1 的 Table 8；两条腿相加等于总 Run Rate。",
        },
    ]

    exhibits = number_exhibits(settled + highlights + next_ex + routine)
    resolve_exhibit_refs(exhibits)
    n_settled, n_high, n_next = len(settled), len(highlights), len(next_ex)
    settled_ex = exhibits[:n_settled]
    highlight_ex = exhibits[n_settled:n_settled + n_high]
    next_block = exhibits[n_settled + n_high:n_settled + n_high + n_next]
    routine_ex = exhibits[n_settled + n_high + n_next:]

    first_table = exhibits[-1]["n"] + 1
    tables = [{**t, "n": first_table + i} for i, t in enumerate(settled_tables)]
    tables.append({
        "n": first_table + len(settled_tables),
        "title": "近八季合并损益与收入结构（公司披露值）",
        "headers": ["期间", "收入", "经常性订阅", "资产型费用", "非经常性",
                    "调整后 EBITDA", "调整后 EBITDA 利润率", "经营利润率",
                    "摊薄 EPS", "Adjusted EPS"],
        "rows": [[labels[i], f"${revenue[i]:,.1f}M", f"${rec[i]:,.1f}M", f"${abf[i]:,.1f}M",
                  f"${non[i]:,.1f}M", f"${fin['adj_ebitda_usd_m'][i]:,.1f}M",
                  f"{fin['adj_ebitda_margin_pct'][i]:.1f}%",
                  f"{fin['operating_margin_pct'][i]:.1f}%",
                  f"${fin['diluted_eps_usd'][i]:.2f}", f"${fin['adjusted_eps_usd'][i]:.2f}"]
                 for i in range(len(labels))],
    })
    tables.append(threshold_table(first_table + len(settled_tables) + 1,
                                  "下季阈值与当前值（原始单位）",
                                  kpi, "current", "当前值"))
    tables.append(ai_capex_cycle_table(first_table + len(settled_tables) + 2))

    latest_rr_growth = pct_change(run_rate[-1], run_rate[-5])
    return {
        "schema_version": "quarterly-dashboard/msci-v1",
        "page": {"slug": "msci", "language": "zh-CN"},
        "company": {
            "ticker": "MSCI",
            "name": "MSCI Inc.",
            "group": "financial_data_indices",
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
        "tracker": "Watchlist Quarterly Tracker · MSCI",
        "title": "MSCI Inc. (MSCI)：Q2 2026 季报仪表盘",
        "subtitle": ("截至 2026-06-30 · 发布 2026-07-21 · US GAAP · 未审计 · "
                     "自然年财年，季度标注与财年一致"),
        "headline": (
            f"收入 US${revenue[-1]:,.1f}M、同比 {signed(fin['revenue_yoy_pct'][-1])}，"
            f"资产型费用同比 {signed(pct_change(abf[-1], abf[-5]))} 是全部加速的来源；"
            f"挂钩 ETF 的 AUM 创 US${aum[-1]:,.0f}B 新高，"
            f"但期末基点费率同时降到 {bp[-1]:.2f}bp、为有披露以来最低；"
            f"公司本季首次上调 FY2026 费用指引，现金流两条几乎没动。"),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>记录</span><b>费用指引靠修订，现金流指引靠低估</b>'
            '<p>六个完整年度里，营业费用对<b>当年最后一次</b>指引 6 次全部落在区间内，'
            '对<b>年初第一次</b>指引只有 3 次。自由现金流两种口径都是 4 次穿出上限。</p></article>'
            '<article><span>亮点</span><b>资产型费用是唯一的加速腿</b>'
            f'<p>US${abf[-1]:,.1f}M、同比 {signed(pct_change(abf[-1], abf[-5]))}，'
            f'占收入 {abf[-1] / revenue[-1] * 100:.1f}%；订阅腿同比 '
            f'{signed(pct_change(rec[-1], rec[-5]))}。</p></article>'
            '<article><span>代价</span><b>规模在涨，过路费率在降</b>'
            f'<p>AUM 31 季涨约 {aum[-1] / aum[0]:.1f} 倍，期末基点费率从 2.67bp 降到 '
            f'{bp[-1]:.2f}bp，资产型收入是两者相乘。</p></article>'
            '</div>'),
        "source": ('Source: <a href="https://www.sec.gov/Archives/edgar/data/1408198/'
                   '000140819826000044/exhibit991earningsrelease-.htm" rel="noopener">'
                   'MSCI 2026 年第二季度业绩新闻稿（8-K EX-99.1）</a>与截至 2026-06-30 的 10-Q。'),
        "source_url": ("https://www.sec.gov/Archives/edgar/data/1408198/"
                       "000140819826000044/exhibit991earningsrelease-.htm"),
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {"id": "settled", "title": "一、公司自己的指引兑现了吗",
             "description": ("MSCI 的指引是年度的，而且只覆盖成本与现金 —— 费用、税率、"
                             "资本开支、经营现金流与自由现金流，从不指引收入与 EPS。"
                             "所以这一节结清的是六个完整年度的费用与现金记录，"
                             "并且把「年初那次」与「年末那次」分开算，因为两者的答案不一样。"),
             "exhibits": settled_ex},
            {"id": "quarter_highlights", "title": "二、本季重点",
             "description": "三条收入腿的分化、四个分部的利润率落差，以及 AUM 与基点费率的反向移动。",
             "exhibits": highlight_ex},
            {"id": "next_quarter", "title": "三、下季要跟踪什么",
             "description": "当前值离下季阈值还有多远，统一用「距阈值余量」口径；不接入的四条也写在这里。",
             "exhibits": next_block},
            {"id": "routine", "title": "四、长期常规跟踪",
             "description": "MSCI 专属的常规序列：31 季利润率与它的调整缺口、留存率的季节性，以及 Run Rate 的两条腿。",
             "exhibits": routine_ex},
        ],
        "tables": tables,
        "notes": [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "MSCI 财年即自然年，本页季度标注与公司自己的口径一致，无需换算。",
            "第一节结清的是年度指引而不是季度指引：MSCI 在每季业绩新闻稿里给出并更新一次全年 Guidance 表，但从不给季度指引，也从不指引收入与每股收益。本站其他公司页第一节结清的是季度收入区间，本页不是，差别源于公司披露口径而非编辑选择。",
            "全年 Guidance 表自 2020 年第三季度业绩新闻稿起以表格形式发布，此前同一组指引以正文段落给出。本页的指引记录自表格化那一期起算，共 24 次发布、覆盖 FY2020 至 FY2026 七个年度，其中六个年度已完结。",
            "同一年的指引在四次发布中会被修订，本页把「年初第一次」与「当年最后一次」分别对全年实际结清，两个答案不同：营业费用对最后一次是 6 年 6 次落在区间内，对第一次只有 3 次。把这两者混为一谈，会把修订的功劳读成预测的准确。",
            "全年实际值一律取次年第一季发布（各年 Q4 业绩新闻稿）中 Table 11 与 Table 12 的 Year Ended 列，不使用年初至今列差分。自由现金流 = 经营现金流 − 资本开支，七个年度逐年核对该恒等式均成立。",
            "各表的金额单位在不同年份、不同表之间在千美元、百万美元与十亿美元之间切换，本页逐表读该表自己的单位表头后统一换算为百万美元；AUM 保留十亿美元。",
            "2021 年之前 Sustainability and Climate 与 All Other – Private Assets 合并为一个 All Other 分部，且该分部当时名为 ESG and Climate。分部图的窗口全部落在拆分之后；31 季的合并口径序列不受影响，分部相加等于合并收入在全部 31 季均成立。",
            "期末基点费率自 2020 年第二季度起有披露，摊薄股数自 2022 年第四季度起在业绩新闻稿中单列，两条序列均从数字存在的那一季开始画，不向前回补。",
            "本页不发布市场一致预期：没有可核对的、带日期的公开来源，站点规则允许发布带日期的「市场预期」对照点，但不允许凭印象填一个数。本页同样不发布评级、目标价与估值。",
            "本页只发布公司披露值、可复算的简单派生值；D 标记代表 Derived / 自算。",
            "核对抽屉最后那张「AI capex 循环」是全站共用的跨页对照块，在每一页都逐字节相同，不是对 MSCI 的判断。它追的是四家云厂现金资本开支 → NVDA 数据中心收入 → TSM 晶圆这条链，MSCI 不在这条链的任何一环上：它既不是其中的支出方，也不是供应方。把它放在这里是为了让读者在任意一页都能查到同一份上下游对照。它在折叠的抽屉里，不参与本页的论证。",
            "本页已知未接入：非 ETF 指数产品与固定收益产品挂钩的资产规模（公司只按季披露挂钩其股票指数的 ETF AUM）、分部层面的资本开支与现金流（公司只在合并层面披露）、客户集中度，以及 2026 年第三季度之后的任何数据（本页数据截至 2026-07-21 的申报）。",
            "业绩电话会文字稿仅链接官方 IR 与 SEC 托管版本，公开仓不复制原件或逐字内容。",
        ],
        "footer": "MSCI quarterly results · 数据来自 MSCI 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "msci.js"), payload, "msci")
    shell_dir = ROOT / "msci"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("MSCI", "msci"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"MSCI page: {charts} charts in {len(payload['sections'])} sections "
          f"+ {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
