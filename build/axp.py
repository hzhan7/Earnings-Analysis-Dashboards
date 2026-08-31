"""American Express quarterly dashboard.

**This is the first page on this site whose guidance record cannot be settled.**
Every other guidance page here ends in a tally -- Cadence never missed its floor
in 42 quarters, Amazon never missed either of two, S&P Global's adjusted EPS
never missed in seven years. American Express publishes a full-year outlook in
the EX-99.1 of every earnings 8-K and has done so across eleven fiscal years and
43 releases, and the honest answer to "did it clear it" is *for most of those
years there is no answer*, because the company moved the basis of its own
promise five times and stopped publishing one for eight consecutive releases.

What is left after the unsettleable years are removed is a two-sided finding
that only exists because both metrics sit in the same sentence of the same
release. Full-year EPS is settleable in five years and **never landed below its
range** -- four inside, one above. Full-year revenue growth is settleable in six
and **landed below its floor once, in FY2023**, where the company's own
FX-adjusted figure met the floor exactly and its reported figure did not. The
number the company can steer clears its range; the number it cannot does not.

Section two is why. The distance from one quarter's pretax income to the same
quarter a year before splits exactly two ways -- an operating leg and a
provision leg, both filed, no estimate anywhere -- and in the latest quarter the
provision line carries US$321M of a US$521M increase.

Published numbers are company-reported or transparent arithmetic. No rating, no
target price, no valuation. Market expectations are not published on this page:
no dated, checkable public source for one was available.
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
    headroom_exhibit,
    midpoint_deviation,
    number_exhibits,
    threshold_exhibit,
    threshold_table,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402

STAGING_PATH = ROOT / "series" / "axp.json"
DATA_DIR = ROOT / "data"

# One tick per year keeps a thirty-eight-quarter axis readable.
LONG_STEP = 4


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100.0


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def rounded(values, digits: int = 6):
    return [None if v is None else round(v, digits) for v in values]


def plain_text(html: str) -> str:
    """Strip markup for the fields the renderer writes with ``textContent``.

    ``section.description`` and every string in ``notes`` reach the page through
    ``esc()`` or ``textContent``, so a ``<b>`` in them is published as the four
    literal characters. Emphasis belongs in an exhibit note, which is rendered.
    """
    return re.sub(r"<[^>]+>", "", html)


def fiscal_of(vintage_label: str) -> str:
    """``'FY23 Q2'`` -> ``'FY23'`` -- the deviation charts count years."""
    return vintage_label.split()[0]


def resolve_exhibit_refs(exhibits: list[dict]) -> list[dict]:
    """Replace ``{EX_NAME}`` placeholders with numbers assigned at render time."""
    numbers = {ex["ref"]: ex["n"] for ex in exhibits if "ref" in ex}
    for exhibit in exhibits:
        for field in ("note", "src_extra", "title"):
            text = exhibit.get(field)
            if not text:
                continue
            for ref, number in numbers.items():
                text = text.replace("{" + ref + "}", str(number))
            exhibit[field] = text
    return exhibits


SOURCE_8K = (
    "全年指引的每一档 vintage 逐字取自当季业绩 8-K 的 EX-99.1；"
    "全年实际值取自次年 1 月发布中公司自己印的 FY 列，并与 SEC XBRL companyfacts 独立核对过。"
)

TIMING = "该财年<b>进行途中</b>"

TIMING_WARNING = (
    "<b>先读这一句，再读色块。</b>这不是一份事前预测的记录。每个财年的四档指引分别随该年 1 月、"
    "4 月、7 月、10 月的业绩发布出去 —— 年初那一档发布时全年还剩十二个月，10 月那一档发布时"
    "全年已经过去四分之三。越靠右的那一档越不是预测。"
)

def unsettled_warning(record: dict) -> str:
    """The blank run, counted from the record rather than typed."""
    blank = [f for f, eps, rev in zip(record["filed"], record["guide_eps_lo_usd"],
                                      record["guide_revenue_growth_lo_pct"])
             if eps is None and rev is None]
    run = [blank[0]]
    for date in blank[1:]:
        index = record["filed"].index(date)
        if record["filed"][index - 1] == run[-1]:
            run.append(date)
        else:
            break
    return (
        "<b>空档不是「公司没发业绩」，是「这一年结不了账」。</b>"
        "十一个财年里只有一部分能被诚实地结清，其余各有各的原因，"
        "整理在 Exhibit {EX_LEDGER} 那张表里。最长的一段空白是 "
        f"{run[0]} 到 {run[-1]} 连续 {len(run)} 份业绩发布 —— "
        "2020 年的指引在 2020-03-17 由另一份 8-K 撤回，2021 年则从头到尾没有给过。")


# ── section one: the eleven-year annual guidance record ──────────────────────
def guidance_charts(staging: dict) -> tuple[list[dict], list[dict]]:
    record = staging["annual_guidance_history"]
    UNSETTLED = unsettled_warning(record)
    labels = record["vintages"]
    years = record["actual_by_year"]

    eps_settled = record["verdicts"]["eps"]
    rev_settled = record["verdicts"]["revenue"]

    # The diamond is the company's OWN whole-percentage-point growth rate, not
    # the two-decimal number the filed dollars divide to. The guidance is
    # written in whole points and never in anything finer, so settling it
    # against a figure with two more digits invents a precision the promise
    # never had: FY2019 delivers 7.98% against a floor of 8 and FY2024 delivers
    # 8.98% against a point of 9, and both are the guided number as the company
    # states it. The exact quotients are in the audit table instead.
    actual_rev = [None] * len(labels)
    for year, block in rev_settled.items():
        actual_rev[record["filed"].index(block["settling_release"])] = \
            float(years[year]["growth_reported_pct"])
    actual_eps = record["actual_diluted_eps_usd"]

    eps_band = delivery_band(
        "EX_EPS_BAND", "全年摊薄 EPS", labels,
        record["guide_eps_lo_usd"], record["guide_eps_hi_usd"], actual_eps,
        fmt="usd2", ylab="US$/股", unit="US$", venue="业绩发布",
        timing=TIMING, period_word="年", src_extra=SOURCE_8K,
        extra_note=(
            "<b>每个财年占据连续的几格</b> —— 年初首次、Q1、Q2、Q3 修订 —— "
            "而菱形只落在<b>结算这一年的那一格</b>上，也就是该年最后一次印出数字的那一档。"
            f"能被结清的只有 {len(eps_settled)} 个财年，"
            "其余六年<b>不是没兑现，是没法判定</b>：FY2016 同一年印了 GAAP 与调整后两条区间；"
            "FY2017 指引 $5.80–$5.90，当年 GAAP 摊薄 EPS 因税改一次性费用只有 $2.97；"
            "FY2018 年中把口径改成调整后 EPS 并写明无法提供 GAAP 对照；"
            "FY2020 撤回；FY2021 从头到尾没给过；FY2026 还没结束。"
            + UNSETTLED + TIMING_WARNING),
    )
    eps_dev = midpoint_deviation(
        "EX_EPS_DEV", "全年摊薄 EPS", labels,
        record["guide_eps_lo_usd"], record["guide_eps_hi_usd"], actual_eps,
        mode="pct", window=len(eps_settled), label=fiscal_of, period_word="年",
        src_extra=SOURCE_8K + "偏离为实际值相对该年<b>结算那一档</b>指引中值的自算值。",
        extra_note=(
            "<b>这张图和上一张回答的不是同一个问题。</b>上一张问「有没有掉出区间」，"
            "答案是五年里一次都没有跌破下限；这一张问「离中值多远」，"
            "答案是五年里四年在中值之上、一年（FY2019）在中值之下但仍落在区间内。"
            "把这一条和 Exhibit {EX_REV_DEV} 并排读才是本节的重点：两条指引写在"
            "同一句话、同一份新闻稿、同一个十二个月的视野里，答案却是两个方向。"),
    )

    rev_band = delivery_band(
        "EX_REV_BAND", "全年收入增速", labels,
        record["guide_revenue_growth_lo_pct"], record["guide_revenue_growth_hi_pct"],
        actual_rev, fmt="pct0", ylab="同比 %", unit="%", venue="业绩发布",
        timing=TIMING, period_word="年", src_extra=SOURCE_8K,
        extra_note=(
            "<b>色块与菱形都是整数个百分点，因为公司只用这个精度说话。</b>"
            "指引写成「9% 到 10%」，实际值也写成「up 9 percent」——"
            "把申报的美元金额除出两位小数再去判定，是给这份承诺发明一个它从来没有过的精度。"
            "两位小数的商在核对抽屉里。"
            "<b>唯一一次真正跌破下限是 FY2023</b>：指引 15%–17%，公司自己报的是"
            "「up 14 percent（15 percent FX-adjusted）」—— 同一年、同一句话，"
            "汇率调整口径正好踩在下限上，报告口径没有。读哪一个口径决定这一年算不算失手。"
            "另有两档指引<b>没有宽度</b>：FY2024 的 10 月那一档是「at around 9 percent」，"
            "FY2026 的 7 月那一档是「10 percent」，都是单点，画在图上没有高度。"
            + UNSETTLED),
    )
    rev_dev = midpoint_deviation(
        "EX_REV_DEV", "全年收入增速", labels,
        record["guide_revenue_growth_lo_pct"], record["guide_revenue_growth_hi_pct"],
        actual_rev, mode="pp", window=len(rev_settled), label=fiscal_of, period_word="年",
        src_extra=SOURCE_8K + "偏离取算术差（百分点），不是比值。",
        extra_note=(
            "<b>与 Exhibit {EX_EPS_DEV} 对照着看。</b>"
            "EPS 那条六年里只有一年低于中值且仍在区间内；这一条六年里三年低于中值、"
            "一年正好等于中值、只有两年高于中值，而且其中一年（FY2023）直接掉出了区间。"
            "收入增速是这两条指引里公司<b>自己控制不了</b>的那一条，"
            "也是唯一一条被跌破过的。"),
    )

    # opening vintage against the one that settles the year: the same question
    # MSCI's page asks, and here it has the opposite answer for the two metrics.
    open_years, open_dev, final_dev = [], [], []
    for year in sorted(rev_settled, key=int):
        idx = [i for i, y in enumerate(record["fiscal_years"]) if str(y) == year
               and record["guide_revenue_growth_lo_pct"][i] is not None]
        first, last = idx[0], record["filed"].index(rev_settled[year]["settling_release"])
        actual = float(years[year]["growth_reported_pct"])
        mid = lambda i: (record["guide_revenue_growth_lo_pct"][i]
                         + record["guide_revenue_growth_hi_pct"][i]) / 2
        open_years.append(f"FY{year[2:]}")
        open_dev.append(round(actual - mid(first), 4))
        final_dev.append(round(actual - mid(last), 4))
    revision = {
        "ref": "EX_REVISION",
        "kind": "grouped_bars",
        "title": "收入增速：对年初那一档与对结算那一档的偏离，六个已完结财年",
        "xlabels": open_years,
        "groups": [
            {"name": "对年初第一档指引", "color": "GOLD", "values": open_dev},
            {"name": "对结算那一档指引", "color": "NAVY", "values": final_dev},
        ],
        "bar_labels": True,
        "fmt": "pp1", "label_fmt": "pp1", "ylab": "pp vs 指引中值",
        "note": (
            "两根柱子之间的距离就是<b>这一年被修订了多少</b>。"
            "FY2022 年初指引 18%–20%、7 月调到 23%–25%，实际 25% —— 对年初那一档高出 6pp，"
            "对修订后那一档正好落在上限。修订把一次大幅低估变成一次精准命中，"
            "这是修订的功劳，不是预测的功劳。"
            "反过来，FY2023 与 FY2024 两年<b>对两档都是负的</b>：修订也没能把它救回来。"),
        "src_extra": SOURCE_8K,
    }

    ledger = {
        "title": "十一个财年逐年：指引、实际值，以及不能结清的年份为什么不能",
        "headers": ["财年", "收入增速指引（结算那一档）", "公司自报增速", "收入判定",
                    "EPS 指引（结算那一档）", "GAAP 摊薄 EPS", "EPS 判定"],
        "rows": [],
    }
    verdict_zh = {"inside": "落在区间内", "above": "高于上限", "below": "跌破下限",
                  "inside_on_bound": "正好落在下限上（区间内）",
                  "equals_point": "与指引的单点相同"}
    for year in sorted(set(list(years) + ["2026"]), key=int):
        block = years.get(year)
        rev_v = rev_settled.get(year)
        eps_v = eps_settled.get(year)

        def band_text(metric, settled, lo_key, hi_key, prefix, digits):
            if not settled:
                return staging["annual_guidance_history"]["unsettleable"][metric].get(
                    year, "—")
            i = record["filed"].index(settled["settling_release"])
            lo, hi = record[lo_key][i], record[hi_key][i]
            return (f"{prefix}{lo:.{digits}f}" if lo == hi
                    else f"{prefix}{lo:.{digits}f}–{prefix}{hi:.{digits}f}")

        ledger["rows"].append([
            f"FY{year}",
            band_text("revenue", rev_v, "guide_revenue_growth_lo_pct",
                      "guide_revenue_growth_hi_pct", "", 0) + ("%" if rev_v else ""),
            f"{block['growth_reported_pct']}%" if block and block["growth_reported_pct"] is not None else "—",
            verdict_zh.get(rev_v["verdict"], "—") if rev_v else "无法判定",
            band_text("eps", eps_v, "guide_eps_lo_usd", "guide_eps_hi_usd", "$", 2),
            f"${block['eps']:.2f}" if block else "—",
            verdict_zh.get(eps_v["verdict"], "—") if eps_v else "无法判定",
        ])

    vintage_table = {
        "title": f"全年指引的全部 {len(labels)} 档 vintage（FY2016–FY2026）",
        "headers": ["vintage", "财年", "发布日", "收入增速指引", "形式",
                    "EPS 指引", "EPS 口径限定"],
        "rows": [],
    }
    basis_zh = {
        "adj_ex_restructuring": "调整后，剔除重组费用",
        "adjusted_no_gaap": "调整后，公司写明无 GAAP 对照",
        "adjusted_dual": "同时印 GAAP 与调整后两条",
        "ex_contingencies": "「subject to contingencies」",
        "high_end_only": "只重申「区间上沿」，不是整条区间",
        "fx_adjusted_revenue": "收入指引为汇率调整口径",
        "includes_accertify_gain": "含 Accertify 出售收益",
        "withdrawn": "已撤回",
        "never_issued": "从未给出",
        "reaffirmed_no_number": "口头重申，未印数字",
    }
    form_zh = {"range": "区间", "point": "单点", "floor": "只有下限", None: "—"}
    for i, label in enumerate(labels):
        lo, hi = record["guide_revenue_growth_lo_pct"][i], record["guide_revenue_growth_hi_pct"][i]
        elo, ehi = record["guide_eps_lo_usd"][i], record["guide_eps_hi_usd"][i]
        vintage_table["rows"].append([
            label, f"FY{record['fiscal_years'][i]}", record["filed"][i],
            "—" if lo is None else (f"{lo:.0f}%" if lo == hi else f"{lo:.0f}%–{hi:.0f}%"),
            form_zh.get(record["guide_revenue_form"][i], "—"),
            "—" if elo is None else (f"${elo:.2f} 以上" if record["guide_eps_form"][i] == "floor"
                                     else f"${elo:.2f}–${ehi:.2f}"),
            basis_zh.get(record["guide_eps_basis"][i], "—"),
        ])

    return [eps_band, eps_dev, rev_band, rev_dev, revision], [ledger, vintage_table]


# American Express recast 2017 onward for ASC 606 and never republished 2016 by
# quarter, so the income statement has one basis from 2017Q1 and another before
# it. Eight series the recast did not touch do carry 2016 -- net card fees,
# salaries, diluted shares, billed business, network volumes, average fee per
# card, proprietary cards in force, CET1 -- and those are the only ones allowed
# to run the longer axis. RECAST is derived from the data rather than typed, so
# adding a quarter at either end cannot silently move it.
RECAST = 4


def recast(block: dict) -> dict:
    """The block with every full-length series cut to the recast window."""
    length = None
    for value in block.values():
        if isinstance(value, list):
            length = max(length or 0, len(value))
    return {
        key: value[RECAST:] if isinstance(value, list) and len(value) == length
        else value
        for key, value in block.items()
    }


# ── section two: what moved this quarter ────────────────────────────────────
def quarter_charts(staging: dict) -> list[dict]:
    fin = recast(staging["financials"])
    # 2016 exists in this file for the eight series ASC 606 did not touch; the
    # rest of the record starts at the recast basis. Everything in this function
    # is on the recast side, so it reads the recast window.
    labels = staging["period_labels"][RECAST:]
    revenue = fin["revenue_usd_m"]
    expenses = fin["total_expenses_usd_m"]
    provisions = fin["provisions_usd_m"]
    pretax = fin["pretax_income_usd_m"]
    ppop = fin["ppop_usd_m"]

    # Guiding nothing and reporting both legs still implies an identity: the
    # year-over-year change in pretax income is the change in pre-provision
    # profit plus the change in the provision line, and `ppop - provisions =
    # pretax` closes in all 38 quarters, so the split carries no estimate.
    start = 4
    dev_labels = labels[start:]
    ppop_leg = [ppop[i] - ppop[i - 4] for i in range(start, len(revenue))]
    prov_leg = [-(provisions[i] - provisions[i - 4]) for i in range(start, len(revenue))]
    latest_total = pretax[-1] - pretax[-5]
    decomposition = {
        "ref": "EX_PTI",
        "kind": "grouped_bars",
        "title": (f"税前利润同比增量拆成两条腿：本季 +US${latest_total:,.0f}M 里，"
                  f"拨备行贡献 +US${prov_leg[-1]:,.0f}M"),
        "xlabels": dev_labels,
        "xrot": 90,
        "xstep": LONG_STEP,
        "groups": [
            {"name": "经营腿（拨备前利润的同比变化）", "color": "NAVY", "values": rounded(ppop_leg)},
            {"name": "拨备腿（拨备下降为正）", "color": "GOLD", "values": rounded(prov_leg)},
        ],
        "bar_labels": False,
        "fmt": "f0c", "label_fmt": "f0c", "ylab": "US$M（同比增量）",
        "note": (
            "<b>这是一个恒等式，不是估计。</b>拨备前利润 = 收入 − 总费用，"
            "而拨备前利润 − 拨备 = 税前利润 —— 三条都是申报值，"
            "这个等式在全部 38 个季度里逐季精确成立，所以两条腿相加正好等于税前利润的同比增量。"
            f"本季两条腿是 +US${ppop_leg[-1]:,.0f}M 与 +US${prov_leg[-1]:,.0f}M，"
            f"拨备腿占 {prov_leg[-1] / latest_total * 100:.0f}%。"
            "<b>拨备腿为正的意思是当季拨备比去年同期少</b>，它可以是信用真的变好，"
            "也可以是准备金释放 —— 图上分不出来，第三节的三条信用阈值才分得出来。"
            "2021 年那几根特别高的拨备腿是疫情期计提的准备金在回冲，"
            "它们同时也说明这条腿有物理边界：放完了就没有了。"),
        "src_extra": "各季业绩 8-K EX-99.2 的合并损益表；两条腿均为本页自算（D），加总等于申报的税前增量。",
    }

    rewards = fin["rewards_usd_m"]
    services = fin["card_member_services_usd_m"]
    bizdev = fin["business_development_usd_m"]
    vce_idx = [i for i, v in enumerate(bizdev) if v is not None]
    vce_labels = [labels[i] for i in vce_idx]
    vce_ratio = [(rewards[i] + services[i] + bizdev[i]) / revenue[i] * 100 for i in vce_idx]
    vce_chart = {
        "ref": "EX_VCE",
        "kind": "lines",
        "title": (f"VCE 占收入比（公司自己的定义）：本季 {vce_ratio[-1]:.1f}%，"
                  f"{len(vce_ratio)} 季区间 {min(vce_ratio):.1f}–{max(vce_ratio):.1f}%"),
        "xlabels": vce_labels,
        "series": [{"name": "VCE ÷ 收入", "values": rounded(vce_ratio), "color": "NAVY"}],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
        "ylab": "%",
        "note": (
            "VCE（variable customer engagement）是公司在业绩表附录里自己定义的口径："
            "Card Member rewards + business development + Card Member services 三条费用相加。"
            "<b>这条线只有 22 个季度，不是选出来的窗口，是这个数存在的全部长度</b> —— "
            "business development 在 2022 年 4 月那份发布里才第一次从 Marketing 里拆出来，"
            "公司只把 2021 年四个季度按新口径重述了一遍，再往前没有。"
            f"最近三季从 {vce_ratio[-4]:.1f}% 抬到 {vce_ratio[-1]:.1f}%，"
            "是三个季度以来的高位；这条线是本季负 jaws 的来源，也是第三节里那条阈值盯的东西。"),
        "src_extra": "各季业绩 8-K EX-99.2 的合并损益表三条费用行相加，除以同季收入；比值为本页自算（D）。",
    }

    jaws = [pct_change(revenue[i], revenue[i - 4]) - pct_change(expenses[i], expenses[i - 4])
            for i in range(start, len(revenue))]
    jaws_chart = {
        "ref": "EX_JAWS",
        "kind": "diverging_bars",
        "title": f"jaws（收入增速 − 费用增速）：本季 {jaws[-1]:+.1f}pp",
        "xlabels": dev_labels,
        "xrot": 90,
        "xstep": LONG_STEP,
        "values": rounded(jaws),
        "legend": "收入增速 − 总费用增速",
        "positive_label": "收入跑赢费用",
        "negative_label": "费用跑赢收入",
        "fmt": "pp1", "yfmt": "pp1", "label_fmt": "pp1",
        "ylab": "pp", "zero_line": True,
        "note": (
            "正值表示收入的同比增速快于总费用的同比增速。"
            "2023 年到 2024 年上半年是这条线最连续为正的一段（最高 +7.7pp），"
            f"自 2024 年第三季度起转负并停在负区间，本季 {jaws[-1]:+.1f}pp。"
            "<b>它和 Exhibit {EX_VCE} 是同一件事的两个看法</b>：费用里唯一持续超速的部分是 VCE，"
            "而 VCE 是随消费与权益使用量走的可变成本，不是一次性投入。"),
        "src_extra": "收入与总费用均为申报值，两个增速之差为本页自算（D）。",
    }

    discount = fin["discount_revenue_usd_m"]
    card_fees = fin["net_card_fees_usd_m"]
    other = fin["other_non_interest_revenue_usd_m"]
    nii = fin["net_interest_income_usd_m"]
    break_at = staging["periods"].index("2021Q1")
    mix = {
        "ref": "EX_MIX",
        "kind": "grouped_bars",
        "title": (f"四条收入腿：净卡费占收入 "
                  f"{card_fees[-1] / revenue[-1] * 100:.1f}%，"
                  f"38 季前是 {card_fees[0] / revenue[0] * 100:.1f}%"),
        "xlabels": labels,
        "xrot": 90,
        "xstep": LONG_STEP,
        "groups": [
            {"name": "商户折扣收入", "color": "NAVY", "values": rounded(discount)},
            {"name": "净卡费", "color": "GOLD", "values": rounded(card_fees)},
            {"name": "其他非利息收入", "color": "BLUE", "values": rounded(other)},
            {"name": "净利息收入", "color": "RED", "values": rounded(nii)},
        ],
        "bar_labels": False,
        "fmt": "f0c", "label_fmt": "f0c", "ylab": "US$M",
        "break_at": break_at,
        "break_label": "processed revenue 移出折扣收入",
        "note": (
            "四条腿相加正好等于「收入（扣除利息支出后）」，全部 38 个季度逐季精确成立。"
            f"38 个季度里折扣收入长到 {discount[-1] / discount[0]:.2f} 倍、"
            f"净卡费长到 {card_fees[-1] / card_fees[0]:.2f} 倍、"
            f"总收入长到 {revenue[-1] / revenue[0]:.2f} 倍 —— "
            "<b>卡费是唯一一条跑赢总收入的腿，商户那条跑输</b>。"
            "断点标记处（2021 年第一季度）公司把 processed revenue 从折扣收入里挪进了"
            "「其他非利息收入」，并只重述了 2021 年四个季度。"
            "<b>合计不受影响，所以任何总额层面的核对都发现不了这次挪动</b>，"
            "断点因此必须画在图上而不是靠等式发现。"
            "「其他非利息收入」这条腿是用合计减去前两条得到的，"
            "而不是取那一行印出来的数 —— 那一行本身在窗口内被改过两次名、并过一次。"),
        "src_extra": "各季业绩 8-K EX-99.2 合并损益表；「其他非利息收入」为非利息收入合计减折扣收入与净卡费（D）。",
    }

    seg = staging["segments_usd_m"]
    seg_labels = staging["segment_period_labels"]
    seg_chart = {
        "ref": "EX_SEG",
        "kind": "lines",
        "title": "四个分部的税前利润率：GMNS 长期在 50% 以上，其余三个在 20% 上下",
        "xlabels": seg_labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": block["name_zh"], "color": color,
             "values": rounded([None if p is None or r in (None, 0) else p / r * 100
                                for p, r in zip(block["pretax_usd_m"], block["revenue_usd_m"])])}
            for block, color in zip(
                [seg["USCS"], seg["CS"], seg["ICS"], seg["GMNS"]],
                ["NAVY", "BLUE", "GOLD", "RED"])
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
        "ylab": "分部税前利润率 %",
        "note": (
            "<b>这张图只有 26 个季度，而且不能往前接。</b>现在这四个分部是 2022 年 10 月那份"
            "业绩发布第一次启用的，同一份发布用一张附表把 2020 年第一季度以后的十个季度"
            "按新口径重算了一遍，本图的窗口就是那张附表能覆盖到的长度。"
            "再往前是 Global Consumer Services Group 那一套三分部结构，"
            "公司没有为它提供过按新口径的重算，两套结构的同名分部不是同一个东西。"
            "ICS 在 2026 年第一季度那个尖峰不是国际业务变好："
            "当季该分部记了 Swisscard 原持股的重估收益与一笔欧洲增值税诉讼的准备金释放，"
            "公司未单独披露金额，所以本页不做还原，只在这里说明它是什么。"),
        "src_extra": "各季业绩 8-K EX-99.2 的四张分部页；利润率 = 分部税前利润 ÷ 分部收入（D）。",
    }
    return [decomposition, vce_chart, jaws_chart, mix, seg_chart]


# ── section three: the thresholds pointed forward ────────────────────────────
def next_quarter_charts(staging: dict) -> list[dict]:
    fin = recast(staging["financials"])
    om = recast(staging["operating_metrics"])
    credit = recast(staging["credit_metrics"])
    # 2016 exists in this file for the eight series ASC 606 did not touch; the
    # rest of the record starts at the recast basis. Everything in this function
    # is on the recast side, so it reads the recast window.
    labels = staging["period_labels"][RECAST:]
    kpi = staging["next_kpi"]["quantified"]

    exhibits = [headroom_exhibit(
        f"下季 {len(kpi)} 条阈值：当前值离阈值的余量",
        kpi, "current",
        ("正值表示仍在安全侧。阈值为本地研究设定，<b>不是公司指引</b> —— "
         "公司的指引是全年的、只覆盖收入增速与 EPS 两个数，见第一节。"
         + staging["next_kpi"]["excluded"]),
        "当前值为 2026Q2 的申报值或由申报值直接相除；阈值为本地研究设定。")]

    revenue = fin["revenue_usd_m"]
    expenses = fin["total_expenses_usd_m"]
    billed = om["billed_business_usd_bn"]
    rewards, services, bizdev = (fin["rewards_usd_m"], fin["card_member_services_usd_m"],
                                 fin["business_development_usd_m"])
    vce_idx = [i for i, v in enumerate(bizdev) if v is not None]

    series_for = {
        "净卡费（季度额）": (staging["period_labels"],
                             staging["financials"]["net_card_fees_usd_m"], "f0c", "US$M",
                             "净卡费是 ASC 606 重述**没有动过**的几条之一 —— "
                             "2018 年 4 月那份重述表把 2017Q1 的商户折扣收入从 4,519 改成 "
                             "5,387，却把净卡费原样重印，所以这条线可以回到 2016Q1，"
                             "而同一份文件里的收入、折扣收入、奖励成本都不能。"),
        "消费额同比（报告口径）": (
            labels[4:],
            [pct_change(billed[i], billed[i - 4]) for i in range(4, len(billed))],
            "pct1", "%",
            "由两个印出来的美元金额相除得到，因此可以被结清；"
            "上季那份分析的阈值原本写在公司只披露到整数的汇率调整口径上，见上一张图的说明。"),
        # Credit quality is not a revenue-recognition item. These two were being
        # cut to the recast window only because they rode the same `recast()`
        # helper as the revenue lines -- a code path, not a basis limit.
        # Credit quality is not a revenue-recognition item; these two were cut to
        # the recast window only because they rode the same `recast()` helper as
        # the revenue lines. Now complete for all 42 quarters.
        "30+ 天逾期率": (staging["period_labels"],
                          staging["credit_metrics"]["past_due_30_pct"], "pct1", "%",
                          credit["basis_note"] + credit["pandemic_relief_note"]),
        "净核销率（本金口径）": (staging["period_labels"],
                                staging["credit_metrics"]["net_write_off_rate_principal_pct"],
                                "pct1", "%", credit["basis_note"]),
        "VCE 占收入比": ([labels[i] for i in vce_idx],
                          [(rewards[i] + services[i] + bizdev[i]) / revenue[i] * 100
                           for i in vce_idx], "pct1", "%",
                          "序列只有 22 季，因为 business development 到 2022 年才从 Marketing 里拆出来。"),
        "jaws（收入增速 − 费用增速）": (
            labels[4:],
            [pct_change(revenue[i], revenue[i - 4]) - pct_change(expenses[i], expenses[i - 4])
             for i in range(4, len(revenue))], "pp1", "pp",
            "阈值为负数：本地设定的是「收敛到 −1pp 以内」，不是「转正」。"),
        "CET1 比率": (staging["period_labels"],
                       staging["operating_metrics"]["cet1_ratio_pct"], "pct1", "%",
                       "公司按季披露的巴塞尔 III 普通股一级资本比率，非自算，"
                       "资本比率与收入确认口径无关，所以它同样回到 2016Q1。"
                       "<b>但 2016 那四格的两条取数路径没有重叠</b>："
                       "前三季来自业绩发布的统计表，第四季来自 FY2016 10-K —— "
                       "本站其余 2016 数据都是两条路径各读一遍再逐格比对，这一条没有。"),
    }
    for entry in kpi:
        if entry["metric"] not in series_for:
            continue
        xlab, values, fmt, unit, extra = series_for[entry["metric"]]
        if unit == "US$M":
            shown = (f"当前 US${entry['current']:,.0f}M，阈值 US${entry['threshold']:,.0f}M")
        else:
            shown = (f"当前 {entry['current']:,.2f}{unit}，阈值 {entry['threshold']:,.2f}{unit}")
        exhibit = threshold_exhibit(
            f"{entry['metric']}：{shown}",
            xlab, rounded(values), entry["threshold"],
            fmt=fmt, ylab=unit,
            actual_name=entry["metric"], threshold_name="本地阈值",
            note=("红线是本地研究设定的阈值，既不是公司指引，也不是公司披露的目标。"
                  "序列从这个数在申报文件里存在的那一季开始画，不向前回补。" + extra),
            src_extra="各季业绩 8-K EX-99.2；阈值为本地研究设定。")
        exhibit["xstep"] = LONG_STEP
        exhibits.append(exhibit)
    return exhibits


# ── section four: the long routine series ────────────────────────────────────
def routine_charts(staging: dict) -> list[dict]:
    fin = recast(staging["financials"])
    om = recast(staging["operating_metrics"])
    # 2016 exists in this file for the eight series ASC 606 did not touch; the
    # rest of the record starts at the recast basis. Everything in this function
    # is on the recast side, so it reads the recast window.
    labels = staging["period_labels"][RECAST:]
    revenue = fin["revenue_usd_m"]
    card_fees = fin["net_card_fees_usd_m"]
    fee_per_card = om["average_fee_per_card_usd"]
    cards = om["proprietary_cards_in_force_m"]
    discount = fin["discount_revenue_usd_m"]
    billed = om["billed_business_usd_bn"]
    printed_rate = om["company_average_discount_rate_pct"]

    # All three of these -- net card fees, average fee per card, proprietary
    # cards in force -- are on the untouched side of the ASC 606 recast, so this
    # chart runs the whole record rather than the recast window. Cards in force
    # is the exception inside the exception: the consolidated proprietary/GNS
    # split was not printed before the Q3 2017 supplement, so its first two
    # points are holes.
    long_labels = staging["period_labels"]
    long_card_fees = staging["financials"]["net_card_fees_usd_m"]
    long_fee_per_card = staging["operating_metrics"]["average_fee_per_card_usd"]
    long_cards = staging["operating_metrics"]["proprietary_cards_in_force_m"]
    cards_from = next(i for i, v in enumerate(long_cards) if v is not None)
    price_chart = {
        "ref": "EX_PRICE",
        "kind": "bar_line_dual",
        "title": (f"净卡费与每卡年费：卡费 US${long_card_fees[-1]:,.0f}M，"
                  f"每卡年费 US${long_fee_per_card[-1]:.0f}"),
        "xlabels": long_labels,
        "xrot": 90,
        "xstep": LONG_STEP,
        "bar": {"name": "净卡费（季度额）", "values": rounded(long_card_fees), "color": "NAVY"},
        "line": {"name": "每卡年费（年化，US$）", "values": rounded(long_fee_per_card),
                 "color": "RED", "yfmt": "f0"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c", "ylab": "US$M",
        "ylab2": "US$/卡·年",
        "note": (
            "<b>这是本页最长、也最需要长窗口才看得见的一张。</b>"
            f"{len(long_labels)} 个季度里净卡费从 US${long_card_fees[0]:,.0f}M 长到 "
            f"US${long_card_fees[-1]:,.0f}M"
            f"（{long_card_fees[-1] / long_card_fees[0]:.2f} 倍），"
            f"每卡年费从 US${long_fee_per_card[0]:.0f} 涨到 US${long_fee_per_card[-1]:.0f}"
            f"（{long_fee_per_card[-1] / long_fee_per_card[0]:.2f} 倍），"
            f"而自营卡量只从 {long_cards[cards_from]:.1f}M"
            f"（{long_labels[cards_from]}）长到 {long_cards[-1]:.1f}M"
            f"（{long_cards[-1] / long_cards[cards_from]:.2f} 倍）。"
            "两个倍数相乘约等于卡费那个倍数 —— <b>卡费的增长里，涨价那一半比发卡那一半更大</b>。"
            "每卡年费是公司自己印出来的数，不是本页除出来的；"
            "它的定义（自营净卡费年化 ÷ 平均自营总卡量）写在业绩表附录里。"
            "八个季度看这条线只是一条缓慢上行的直线，看不出它已经翻了近三倍。"
            "<b>本页大多数图只能回到 2017Q1，这一张回到 2016Q1</b>："
            "AmEx 2018 年按 ASC 606 全面追溯重述，却只重印到 2017Q1；"
            "净卡费与每卡年费是重述没有动过的两条，所以它们可以更长。"),
        "src_extra": "各季业绩 8-K EX-99.2：净卡费取合并损益表，每卡年费与卡量取 Selected Card Related Statistical Information。",
    }

    derived_idx = [i for i, p in enumerate(staging["periods"][RECAST:])
                   if p >= "2021Q1"]
    derived_rate = [None] * len(labels)
    for i in derived_idx:
        derived_rate[i] = discount[i] / (billed[i] * 1000) * 100
    overlap = [i for i in derived_idx if printed_rate[i] is not None]
    gap = [(derived_rate[i] - printed_rate[i]) * 100 for i in overlap]
    rate_chart = {
        "ref": "EX_RATE",
        "kind": "lines",
        "title": "商户那一侧的价格：公司自己印的平均折扣率停在 2022Q4，自算那条不是它的延续",
        "xlabels": labels,
        "xrot": 90,
        "xstep": LONG_STEP,
        "series": [
            {"name": "公司披露的平均折扣率", "values": rounded(printed_rate), "color": "NAVY"},
            {"name": "折扣收入 ÷ 消费额（本页自算，非同一口径）",
             "values": rounded(derived_rate), "color": "GOLD"},
        ],
        "fmt": "pct2", "yfmt": "pct2", "label_fmt": "pct2", "end_label": True,
        "ylab": "%",
        "note": (
            "<b>两条线不是同一个数，本页不把它们接成一条。</b>"
            f"公司在每份业绩表里印了 {sum(1 for v in printed_rate if v is not None)} 个季度的"
            "「Average discount rate」，最后一次出现在 2023 年 1 月发布的 Q4'22 那一格，"
            "之后这一行从统计表里消失，再也没有回来。它的脚注把分母定义为"
            "<b>自营与网络伙伴合计</b>的消费额、并扣掉第三方收单机构留存的部分，"
            "所以它不是「折扣收入 ÷ 消费额」。"
            f"在两条线重叠的 {len(overlap)} 个季度里，自算那条稳定地比公司印的"
            f"{'低' if max(gap) < 0 else '高'} {abs(max(gap)):.1f} 到 {abs(min(gap)):.1f} 个基点 —— "
            "<b>这是一个口径造成的水平差，不是噪声</b>，所以把公司那条的末端接到自算那条上，"
            "会在 2022Q4 与 2023Q1 之间画出一个纯属口径的台阶。"
            "自算那条也只从 2021Q1 起：2021 年之前折扣收入里还含着 processed revenue，"
            "而分母在 2020 年就已经改成只算自营，"
            "<b>拿旧口径的分子除新口径的分母，会读出一次并不存在的提价</b>。"),
        "src_extra": "平均折扣率为公司披露值；自算折扣率 = 折扣收入 ÷ 消费额（D），分母以十亿计需换算。",
    }

    shares = fin["diluted_shares_m"]
    # Net income and diluted EPS sit below the ASC 606 gross-up: the recast moved
    # revenue and expenses by 10-19% each and the two offset, leaving the bottom
    # line within 1.4% every quarter. So this chart reads the whole record, not
    # the recast window -- the same exception the net-card-fees chart above makes.
    long_labels = staging["period_labels"]
    net_income = staging["financials"]["net_income_usd_m"]
    eps = staging["financials"]["diluted_eps_usd"]
    ni_index = [v / net_income[0] * 100 for v in net_income]
    eps_index = [v / eps[0] * 100 for v in eps]
    buyback_chart = {
        "ref": "EX_BUYBACK",
        "kind": "lines",
        "title": (f"净利润与每股收益的分岔：{len(long_labels)} 季里净利润长到 "
                  f"{net_income[-1] / net_income[0]:.2f} 倍，"
                  f"摊薄 EPS 长到 {eps[-1] / eps[0]:.2f} 倍"),
        "xlabels": long_labels,
        "xrot": 90,
        "xstep": LONG_STEP,
        "series": [
            {"name": f"净利润（{long_labels[0]} = 100）", "values": rounded(ni_index), "color": "NAVY"},
            {"name": f"摊薄 EPS（{long_labels[0]} = 100）", "values": rounded(eps_index), "color": "GOLD"},
        ],
        "fmt": "f0", "yfmt": "f0", "label_fmt": "f0", "end_label": True,
        "ylab": f"指数（{long_labels[0]} = 100）",
        "note": (
            "<b>两条线之间的缺口几乎全是回购。</b>同期摊薄股数从 "
            f"{shares[0]:,.0f}M 降到 {shares[-1]:,.0f}M（{pct_change(shares[-1], shares[0]):+.1f}%），"
            f"倒数是 {shares[0] / shares[-1]:.3f} 倍，"
            f"而两条线的倍数之比是 {(eps[-1] / eps[0]) / (net_income[-1] / net_income[0]):.3f} 倍 —— "
            "剩下的一点点差额是优先股股息与参与型股权激励分走的部分，不是别的。"
            "<b>这条缺口是每股收益增长里不来自经营的那一半的量度</b>，"
            "而它依赖资本比率还有多少余量，见第三节的 CET1 那张图。"
            "2017Q4 净利润为负是当年的税改一次性费用，两条线在那一格同时下穿。"),
        "src_extra": "净利润、摊薄 EPS 与摊薄股数均取自各季业绩 8-K EX-99.2 的合并损益表；指数化为本页自算（D）。",
    }

    fee_share = [card_fees[i] / revenue[i] * 100 for i in range(len(revenue))]
    discount_share = [discount[i] / revenue[i] * 100 for i in range(len(revenue))]
    share_chart = {
        "ref": "EX_SHARE",
        "kind": "lines",
        "title": (f"两条腿占收入的比重：净卡费 {fee_share[0]:.1f}% → {fee_share[-1]:.1f}%，"
                  f"商户折扣收入 {discount_share[0]:.1f}% → {discount_share[-1]:.1f}%"),
        "xlabels": labels,
        "xrot": 90,
        "xstep": LONG_STEP,
        "series": [
            {"name": "净卡费 ÷ 收入", "values": rounded(fee_share), "color": "GOLD"},
            {"name": "商户折扣收入 ÷ 收入", "values": rounded(discount_share), "color": "NAVY"},
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
        "ylab": "占收入 %",
        "note": (
            "<b>同一家公司的两个价格，方向相反。</b>"
            "向持卡人收的年费从占收入不到九分之一涨到接近七分之一；"
            "向商户收的折扣收入从占收入六成以上降到略高于一半。"
            "2020 年那个尖峰是疫情：消费塌了而年费是合同性的，所以分母掉得比分子快，"
            "它是分母事件不是提价事件。"
            "折扣收入那条在 2021Q1 有一次口径下移（processed revenue 移出），见 Exhibit {EX_MIX} 的断点。"),
        "src_extra": "两条比值均由同一份合并损益表的申报值相除得到（D）。",
    }
    return [price_chart, share_chart, rate_chart, buyback_chart]


def build_payload(staging: dict) -> dict:
    fin = recast(staging["financials"])
    om = recast(staging["operating_metrics"])
    # 2016 exists in this file for the eight series ASC 606 did not touch; the
    # rest of the record starts at the recast basis. Everything in this function
    # is on the recast side, so it reads the recast window.
    labels = staging["period_labels"][RECAST:]
    record = staging["annual_guidance_history"]

    revenue = fin["revenue_usd_m"]
    expenses = fin["total_expenses_usd_m"]
    provisions = fin["provisions_usd_m"]
    pretax = fin["pretax_income_usd_m"]
    ppop = fin["ppop_usd_m"]
    card_fees = fin["net_card_fees_usd_m"]
    eps = fin["diluted_eps_usd"]

    rev_yoy = pct_change(revenue[-1], revenue[-5])
    eps_yoy = pct_change(eps[-1], eps[-5])
    jaws = rev_yoy - pct_change(expenses[-1], expenses[-5])
    d_pretax = pretax[-1] - pretax[-5]
    d_prov = -(provisions[-1] - provisions[-5])
    d_ppop = ppop[-1] - ppop[-5]
    vce = (fin["rewards_usd_m"][-1] + fin["card_member_services_usd_m"][-1]
           + fin["business_development_usd_m"][-1])
    vce_ratio = vce / revenue[-1] * 100
    fee_share = card_fees[-1] / revenue[-1] * 100

    settled, settled_tables = guidance_charts(staging)
    settled_kpi = staging["settled_kpi"]["quantified"]
    settled.append(headroom_exhibit(
        f"上季那份分析立的阈值里，能结清的 {len(settled_kpi)} 条",
        settled_kpi, "actual",
        ("正值表示仍在安全侧。这些是本地研究设定的阈值，不是公司指引。"
         + staging["settled_kpi"]["retired"]),
        "实际值为 2026Q2 的申报值；阈值为上季本地研究设定。"))

    highlights = quarter_charts(staging)
    next_block = next_quarter_charts(staging)
    routine = routine_charts(staging)

    exhibits = number_exhibits(settled + highlights + next_block + routine)
    resolve_exhibit_refs(exhibits)
    n1, n2, n3 = len(settled), len(highlights), len(next_block)
    settled_ex = exhibits[:n1]
    highlight_ex = exhibits[n1:n1 + n2]
    next_ex = exhibits[n1 + n2:n1 + n2 + n3]
    routine_ex = exhibits[n1 + n2 + n3:]

    first_table = exhibits[-1]["n"] + 1
    tables = [{**t, "n": first_table + i} for i, t in enumerate(settled_tables)]
    n = first_table + len(settled_tables)
    tables.append({
        "n": n,
        "title": "近八季合并损益与收入结构（公司披露值，D 为自算）",
        "headers": ["期间", "收入", "商户折扣收入", "净卡费", "其他非利息收入 D", "净利息收入",
                    "拨备", "总费用", "拨备前利润 D", "税前利润", "摊薄 EPS"],
        "rows": [[labels[i], f"${revenue[i]:,.0f}M", f"${fin['discount_revenue_usd_m'][i]:,.0f}M",
                  f"${card_fees[i]:,.0f}M", f"${fin['other_non_interest_revenue_usd_m'][i]:,.0f}M",
                  f"${fin['net_interest_income_usd_m'][i]:,.0f}M", f"${provisions[i]:,.0f}M",
                  f"${expenses[i]:,.0f}M", f"${ppop[i]:,.0f}M", f"${pretax[i]:,.0f}M",
                  f"${eps[i]:.2f}"]
                 for i in range(len(labels) - 8, len(labels))],
    })
    n += 1
    tables.append({
        "n": n,
        "title": "全年收入增速：公司自报的整数与申报金额除出来的两位小数",
        "headers": ["财年", "指引（结算那一档）", "公司自报（报告口径）", "公司自报（汇率调整）",
                    "申报金额相除 D", "全年收入"],
        "rows": [[f"FY{year}",
                  (lambda b: "—" if b is None else
                   (f"{record['guide_revenue_growth_lo_pct'][b]:.0f}%"
                    if record['guide_revenue_growth_lo_pct'][b] == record['guide_revenue_growth_hi_pct'][b]
                    else f"{record['guide_revenue_growth_lo_pct'][b]:.0f}%–"
                         f"{record['guide_revenue_growth_hi_pct'][b]:.0f}%"))(
                      record["filed"].index(record["verdicts"]["revenue"][year]["settling_release"])
                      if year in record["verdicts"]["revenue"] else None),
                  f"{block['growth_reported_pct']}%" if block["growth_reported_pct"] is not None else "—",
                  f"{block['growth_fx_pct']}%" if block["growth_fx_pct"] is not None else "—",
                  f"{block['growth_exact_pct']:+.2f}%" if block["growth_exact_pct"] is not None else "—",
                  f"${block['revenue_usd_m']:,.0f}M"]
                 for year, block in sorted(record["actual_by_year"].items())],
    })
    n += 1
    tables.append(threshold_table(n, "下季阈值与当前值（原始单位）",
                                  staging["next_kpi"]["quantified"], "current", "当前值"))
    n += 1
    tables.append(threshold_table(n, "上季阈值与本季实际值（原始单位）",
                                  settled_kpi, "actual", "本季实际值"))
    n += 1
    tables.append(ai_capex_cycle_table(n))

    # The ledger is a TABLE, not an exhibit, so it is numbered after the charts
    # and its placeholder cannot be resolved in the exhibit pass above.
    for exhibit in exhibits:
        for field in ("note", "src_extra", "title"):
            if exhibit.get(field):
                exhibit[field] = exhibit[field].replace("{EX_LEDGER}", str(first_table))

    eps_verdicts = record["verdicts"]["eps"]
    rev_verdicts = record["verdicts"]["revenue"]
    eps_below = sum(1 for v in eps_verdicts.values() if v["verdict"] == "below")
    rev_below = sum(1 for v in rev_verdicts.values() if v["verdict"] == "below")

    return {
        "schema_version": "quarterly-dashboard/axp-v1",
        "page": {"slug": "axp", "language": "zh-CN"},
        "company": {
            "ticker": "AXP",
            "name": "American Express Company",
            "group": "payment_networks",
            "accounting_standard": "US GAAP",
        },
        "latest": {
            "disclosed_period_label": "Q2 2026",
            "full_financial_period_label": "Q2 2026",
            "period_end": "2026-06-30",
            "release_date": "2026-07-24",
            "analysis_date": "2026-08-29",
            "audit_status": "unaudited",
            "status": "history_ready",
        },
        "tracker": "Watchlist Quarterly Tracker · AXP",
        "title": "American Express (AXP)：Q2 2026 季报仪表盘",
        "subtitle": ("截至 2026-06-30 · 发布 2026-07-24 · US GAAP · 未审计 · "
                     "自然年财年，季度标注与公司口径一致"),
        "headline": (
            f"收入 US${revenue[-1]:,.0f}M、同比 {signed(rev_yoy)}，摊薄 EPS ${eps[-1]:.2f}、"
            f"同比 {signed(eps_yoy)}；但税前利润 {signed(pct_change(pretax[-1], pretax[-5]))} 的增量里，"
            f"US${d_prov:,.0f}M 来自拨备行、US${d_ppop:,.0f}M 来自经营 —— "
            f"拨备前利润只增长 {signed(pct_change(ppop[-1], ppop[-5]))}，jaws {jaws:+.1f}pp。"),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>记录</span><b>公司自己的指引，一半年份结不了账</b>'
            f'<p>十一个财年、43 档全年指引里，EPS 只有 {len(eps_verdicts)} 年、收入只有 '
            f'{len(rev_verdicts)} 年能被诚实结清；其余各年或口径中途改过、或被撤回、或从未给出。'
            f'能结清的部分是两面的：EPS {eps_below} 次跌破下限，收入 {rev_below} 次。</p></article>'
            '<article><span>成色</span><b>税前增量的六成来自拨备行</b>'
            f'<p>税前同比 +US${d_pretax:,.0f}M = 经营腿 +US${d_ppop:,.0f}M + 拨备腿 '
            f'+US${d_prov:,.0f}M，是申报值构成的恒等式。VCE 占收入 {vce_ratio:.1f}%，'
            f'jaws {jaws:+.1f}pp。</p></article>'
            '<article><span>结构</span><b>持卡人的价格在涨，商户的在降</b>'
            f'<p>38 季里净卡费长到 {card_fees[-1] / card_fees[0]:.2f} 倍、占收入从 '
            f'{card_fees[0] / revenue[0] * 100:.1f}% 到 {fee_share:.1f}%；'
            f'商户折扣收入只长到 {fin["discount_revenue_usd_m"][-1] / fin["discount_revenue_usd_m"][0]:.2f} 倍，'
            '而公司自 2023 年起不再披露平均折扣率。</p></article>'
            '</div>'),
        "source": ('Source: <a href="https://www.sec.gov/Archives/edgar/data/4962/'
                   '000000496226000318/q226exhibit991.htm" rel="noopener">'
                   'American Express 2026 年第二季度业绩新闻稿（8-K EX-99.1）</a>'
                   '与同一份 8-K 的 EX-99.2 统计表。'),
        "source_url": ("https://www.sec.gov/Archives/edgar/data/4962/"
                       "000000496226000318/q226exhibit991.htm"),
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {"id": "settled", "title": "一、上季兑现了吗",
             "description": plain_text(
                 "这一节结清两样东西，而第一样在本站是头一回结不出一个数。"
                 "美国运通在每份业绩 8-K 的 EX-99.1 里给一次全年展望 —— 收入增速与摊薄 EPS —— "
                 "并在当年后三期各修订一次，十一个财年一共 43 档。"
                 "但这份记录不能当成一条连续的序列读：口径改过五次、撤回过一次、"
                 "还有一整年从头到尾没给。所以这一节先说清哪些年份能结清、哪些不能，再结清能结的。"
                 "第二样是上季那份本地分析立的五条阈值。"),
             "exhibits": settled_ex},
            {"id": "quarter_highlights", "title": "二、本季重点",
             "description": plain_text(
                 "本季的核心张力是「利润从哪来」：税前利润同比增量拆成经营与拨备两条腿，"
                 "这是一个由申报值构成的恒等式，不含任何估计。"
                 "其余三张分别是压住经营腿的那条费用（VCE）、它造成的负 jaws，以及四条收入腿的结构。"),
             "exhibits": highlight_ex},
            {"id": "next_quarter", "title": "三、下季要跟踪什么",
             "description": plain_text(
                 "当前值离下季阈值还有多远，统一用「距阈值余量」口径；"
                 "不接入的三条与它们各自的理由也写在这一节。"),
             "exhibits": next_ex},
            {"id": "routine", "title": "四、长期常规跟踪",
             "description": plain_text(
                 "美国运通专属的常规序列：卡费这台涨价机器的量价两条腿、"
                 "持卡人与商户两侧价格的反向移动、公司自己停掉的那条折扣率，以及资本比率。"),
             "exhibits": routine_ex},
        ],
        "tables": tables,
        "notes": [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "美国运通财年即自然年，本页季度标注与公司自己的口径一致，无需换算。",
            "长序列一律自 2017 年第一季度起，不向前回补。公司自 2018-01-01 起适用 ASC 606 并在自家统计表里重述了 2017 年 —— 2018 年 1 月发布中 Q1 2017 的折扣收入是 4,519，2018 年 4 月发布中同一季是 5,387，Card Member rewards 同步等额调高，收入合计从 7,889 变成 8,709。2016 年从未在统计表里被重述过，因为每份发布只并排印五个季度，最后一份带 Q4 2016 的发布早于该变更。把两段接起来会在 2018 年初凭空造出一个约 +10% 的收入台阶。",
            "第一节结清的是年度指引而不是季度指引：公司从不发布季度指引，也从不在申报文件里给季度区间。本站其他几页第一节结清的是季度收入区间，本页不是，差别源于公司披露口径而非编辑选择。",
            "十一个财年里，全年 EPS 指引只有五年（FY2019、FY2022–FY2025）、全年收入增速指引只有六年""（FY2018、FY2019、FY2022–FY2025）可以被诚实结清，逐年理由列在核对抽屉的第一张表里。""EPS 不能结清的六年各有原因：同一年印了 GAAP 与调整后两条区间（FY2016）；""指引与实际不在同一口径上（FY2017 当年 GAAP EPS 被税改一次性费用压到 $2.97，""FY2018 年中改用调整后 EPS 且公司写明无法提供 GAAP 对照）；被撤回（FY2020）；""从头到尾没有给过（FY2021）；本年度尚未结束（FY2026）。""另有一年是结清了但带限定：FY2024 的指引在 7 月被整体上调以容纳一笔出售收益，""上调后的区间与原区间不是同一个东西，这一点写在该年的那几格上。",
            "2020 年全年指引的撤回不在业绩 8-K 里。公司在 2020-03-17 单独报了一份 Item 7.01 的 8-K 说明无法预测第一季度以后的业绩，随后三份业绩新闻稿的前瞻性声明段里「2020 年展望」这个对象整段消失。只读业绩 8-K 会把它读成「没给过指引」，而不是「给过又撤回」。",
            "收入增速的指引与实际值在图上都用整数个百分点，因为公司只用这个精度说话：指引写成「9% 到 10%」，实际值写成「up 9 percent」。用申报金额除出两位小数再判定，会给这份承诺发明一个它从未有过的精度 —— FY2019 的 7.98% 是这样落在 8% 的下限上的，FY2024 的 8.98% 是这样落在 9% 那个单点上的。两位小数的商列在核对抽屉里。",
            "FY2023 是窗口内唯一一次收入增速真正跌破下限，而它同时是一次口径事件：指引 15%–17%，公司自己报的是「up 14 percent（15 percent FX-adjusted）」。汇率调整口径正好踩在下限上，报告口径没有。本页按报告口径判定并在图上写明两者都存在。",
            "VCE（可变客户参与成本）用公司自己的定义 —— Card Member rewards + business development + Card Member services —— 序列只有 22 个季度，因为 business development 到 2022 年 4 月那份发布才第一次从 Marketing 里拆出来，公司只把 2021 年四个季度按新口径重述过。这不是选出来的窗口，是这个数存在的全部长度。",
            "分部序列只有 26 个季度，且不能往前接。现在这四个分部是 2022 年 10 月那份业绩发布启用的，同一份发布用一张附表把 2020 年第一季度以后的十个季度按新口径重算了一遍，本页的分部窗口就是那张附表的长度。再往前是另一套三分部结构，公司没有为它提供过按新口径的重算。",
            "商户折扣收入在 2021 年第一季度有一次口径变化：processed revenue 被移出这一行、并进其他非利息收入，公司只重述了 2021 年四个季度。收入合计不受影响，因此任何总额层面的核对都发现不了这次挪动，图上因此打了断点。同样的原因，「其他非利息收入」这条腿是用非利息收入合计减去折扣收入与净卡费得到的，而不是取那一行印出来的数 —— 那一行在窗口内被改过两次名并被并过一次。",
            "公司披露的「平均折扣率」与本页自算的「折扣收入 ÷ 消费额」不是同一个数，本页把它们画成两条线而不是一条。公司的口径把分母定义为自营与网络伙伴合计的消费额并扣掉第三方收单机构留存的部分；在两条线重叠的八个季度里，自算那条稳定地比公司印的低 3.9 到 5.0 个基点 —— 是口径造成的水平差，不是噪声。公司自 2023 年 1 月发布的 Q4 2022 之后不再披露这一行，本页也不为它编一个延续。",
            "自算的折扣率只从 2021 年第一季度起。2020 年那四个季度的分子还含着 processed revenue，而分母在 2021 年 4 月那份发布里已经被改成只算自营消费额，拿旧口径的分子除新口径的分母会读出一次并不存在的提价 —— 没有任何一条恒等式能发现这个错误。",
            "信用指标的两段序列是接起来的，接线的依据写在图上：公司在 2026 年第一季度把 Card Member loans 与 receivables 合并列示为 Card balances，同一份发布把前四个季度按新口径重述了一遍，而这四个季度两种口径印出来的数字完全相同 —— 公司自己的附注也写明「无计量影响」。没有这段重叠就不会接。",
            "本页不发布市场一致预期，也不发布评级、目标价与估值。站点规则允许发布带日期、不署机构名的「市场预期」对照点，但不允许凭印象填一个数，而本季没有可核对的公开来源。",
            "本页只发布公司披露值与可复算的简单派生值；D 标记代表 Derived / 自算，不代表公司定义的非 GAAP 指标。",
            "本页已知未接入：季度层面的分红与回购金额（现金流量表按年初至今披露，业绩表只印回购股数不印金额）；汇率调整口径的消费与收入增速序列（公司只披露到整数个百分点）；反洗钱执法行动的任何金额（公司在 2026 年第二季度 10-Q 里只写了「预计将面临执法行动」，没有金额）；以及 2026 年 7 月 24 日之后的任何数据。",
            "核对抽屉最后那张「AI capex 循环」是全站共用的跨页对照块，在每一页都逐字节相同，不是对美国运通的判断。它追的是四家云厂现金资本开支 → NVDA 数据中心收入 → TSM 晶圆这条链，美国运通不在这条链的任何一环上。把它放在这里是为了让读者在任意一页都能查到同一份上下游对照；它在折叠的抽屉里，不参与本页的论证。",
            "业绩电话会内容不进本页。公司在电话会上给过若干前瞻数字（例如全年 VCE 占收入比、市场营销费用的增长口径），但业绩 8-K 里没有它们，无法与第二个来源核对，本站不转录只在网络广播里出现过的数字。",
        ],
        "footer": "American Express quarterly results · 数据来自 AXP 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "axp.js"), payload, "axp")
    shell_dir = ROOT / "axp"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("AXP", "axp"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"AXP page: {charts} charts in {len(payload['sections'])} sections "
          f"+ {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
