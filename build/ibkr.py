#!/usr/bin/env python3
"""Build the IBKR (Interactive Brokers Group) quarterly-results page.

Same four-part, chart-led shape as the other company pages (上季兑现 → 本季重点
→ 下季跟踪 → 长期常规).  Interactive Brokers' fiscal year is the calendar year,
so no quarter on this page needs remapping and this page's ``Q2 2026`` is the
quarter ended 2026-06-30 that the company also calls 2Q2026.

Three things make this page different from the ones built before it.

**No guidance record, and it is a sourcing limit rather than an editorial
choice.**  IBKR has never put a numeric quarterly outlook in a filing -- no
revenue range, no EPS range, no margin range, in any earnings 8-K in the
archive.  The object the Amazon, Cadence, Synopsys, NVIDIA, TSMC and Meta pages
are built on simply does not exist here, the same way it does not exist for
Microsoft, Alphabet and Visa.  Transcribing forward-looking remarks off a
webcast that cannot be checked against a second source is the failure this repo
exists to avoid, so section one carries what the company *does* publish about
its own prior quarter instead.

**This is the page's first quarter of coverage**, so there are no thresholds set
by a previous note to settle.  Section one says so rather than inventing a
record; the thresholds in section three are the first ones, and the loop closes
next quarter.

**The operating metrics are not XBRL facts.**  Accounts, customer equity, DARTs,
margin loans, credits and the whole net-interest-margin table live only in the
EX-99.1 of each quarterly earnings 8-K, so the reviewed series reads 31
consecutive releases back to 2018Q4 rather than the companyfacts API.  The
income statement is the other way round: every quarter but the fiscal fourth is
the 10-Q's own three-month column, and the fourth is the 10-K year minus the Q3
10-Q's nine months.

Two structural breaks are marked rather than smoothed:

* The company **renamed its per-order commission metric** at 1Q2020, from
  "Commission per DART" to "Commission per Cleared Commissionable Order".  The
  two never appear in the same release, so there is no overlap quarter to splice
  on and that series starts at 1Q2020 rather than being carried back.
* The **4-for-1 stock split** declared 2025-04-15 restated only those quarters
  that later served as a comparative, so the per-share figures in companyfacts
  are a mix of two bases.  This page therefore plots **net income available for
  common stockholders in dollars**, which is additive and split-invariant, and
  publishes no multi-quarter EPS line at all.

Published numbers are company-reported or transparent arithmetic.  No ratings,
no target prices, no broker-attributed estimates.
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
    headroom_exhibit,
    number_exhibits,
    threshold_exhibit,
    threshold_table,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "ibkr.json"
DATA_DIR = ROOT / "data"

# The recent window every 本季重点 chart uses, and the long window for 长期常规.
RECENT = 8
LONG_STEP = 4

NO_GUIDANCE_NOTE = (
    "<b>IBKR 从不在申报文件里给季度数字指引</b>，所以本页没有逐季的指引兑现记录。"
    "这是取数限制而不是编辑取舍：翻遍档案里的历次业绩 8-K，公司没有给过下一季的收入区间、"
    "EPS 区间或利润率区间中的任何一个。微软、Alphabet 与 Visa 三页出于同样的理由也没有这类记录。"
)


def compact_period(period: str) -> str:
    """``'Q2 2026'`` → ``'Q2'26'``."""
    quarter, year = period.split()
    return f"{quarter}'{year[-2:]}"


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def rounded(values: list[float | None], digits: int = 6) -> list[float | None]:
    return [None if value is None else round(value, digits) for value in values]


def ratio(numerator: list[float | None], denominator: list[float | None]
          ) -> list[float | None]:
    return [None if None in (a, b) or b == 0 else a / b * 100
            for a, b in zip(numerator, denominator)]


def yoy(values: list[float | None]) -> list[float | None]:
    """Year-over-year percent, ``None`` for the first four quarters."""
    return [None if index < 4 or None in (values[index], values[index - 4])
            or values[index - 4] == 0
            else pct_change(values[index], values[index - 4])
            for index in range(len(values))]


def qoq(values: list[float | None]) -> list[float | None]:
    return [None if index < 1 or None in (values[index], values[index - 1])
            or values[index - 1] == 0
            else pct_change(values[index], values[index - 1])
            for index in range(len(values))]


def plain_text(html: str) -> str:
    """Strip inline markup for the two slots the renderer escapes rather than parses.

    `assets/page.js` writes exhibit notes with `innerHTML` but runs section
    descriptions and the 口径与方法说明 list through `esc()`, so a `<b>` that
    reads as emphasis on a chart caption reaches the reader as the literal
    characters `<b>` in those two places.
    """
    return re.sub(r"<[^>]+>", "", html)


def resolve_exhibit_refs(exhibits: list[dict]) -> list[dict]:
    """Substitute ``{ref}`` placeholders with the numbers `number_exhibits` assigned."""
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


RELEASE_SOURCE = "各季业绩 8-K 的 EX-99.1「Operating Data」与「Net Interest Margin」两表。"
INCOME_SOURCE = ("各季 10-Q 合并损益表；会计第四季为 10-K 全年数减去第三季 10-Q 的九个月栏，"
                 "两端都是申报值。")


# ── section one ─────────────────────────────────────────────────────────────

def consecutive_record(staging: dict) -> dict:
    """The company's own sequential comparison, carried across the whole record.

    IBKR prints a "Consecutive Quarters" table in every release -- this quarter
    against the one before it -- so the sequential move is the company's own
    published object rather than something this page invents. One quarter of it
    says nothing; the full run says whether a negative quarter is normal.
    """
    periods = staging["periods"]
    operating = staging["operating"]
    accounts = qoq(operating["accounts_thousands"])
    equity = qoq(operating["customer_equity_usd_bn"])
    darts = qoq(operating["darts_thousands"])
    finished = [value for value in accounts if value is not None]
    negative_equity = sum(1 for value in equity[1:] if value is not None and value < 0)
    negative_accounts = sum(1 for value in finished if value < 0)
    return {
        "ref": "EX_QOQ",
        "kind": "lines",
        "title": (
            f"公司自印的环比表拉成 {len(finished)} 季记录："
            f"账户数 {len(finished)} 季里 {len(finished) - negative_accounts} 季环比为正，"
            f"客户权益 {negative_equity} 季为负"
        ),
        "xlabels": [compact_period(period) for period in periods],
        "xrot": 90,
        "series": [
            {"name": "账户数 环比", "values": rounded(accounts), "color": "NAVY"},
            {"name": "客户权益 环比", "values": rounded(equity), "color": "BLUE"},
            {"name": "DARTs 环比", "values": rounded(darts), "color": "GOLD"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "环比增速",
        "zero_line": True,
        "note": (
            "<b>本页首次覆盖，第一节没有本站上季阈值可结算</b> —— 阈值从第三节开始设，"
            "闭环从下一季起。能结算的是公司自己每季都印的那张环比表：本图把它拉成完整记录。"
            f"账户数几乎从不环比下滑（{len(finished)} 季里仅 {negative_accounts} 季为负），"
            f"客户权益却有 {negative_equity} 季为负 —— 这是两条性质不同的线，"
            "前者是揽客，后者同时含市值波动。把客户权益的环比读成揽客成果，"
            "会在下跌季里把一次行情记成经营失利，在上涨季里反过来记成揽客成功。"
        ),
        "src_extra": RELEASE_SOURCE,
    }


def nim_record(staging: dict) -> dict:
    """Net interest margin against the same quarter a year earlier."""
    periods = staging["periods"]
    nim = staging["nim"]["nim_pct"]
    delta = [None if index < 4 or None in (nim[index], nim[index - 4])
             else nim[index] - nim[index - 4]
             for index in range(len(nim))]
    finished = [value for value in delta if value is not None]
    negative = sum(1 for value in finished if value < 0)
    streak = 0
    for value in reversed(finished):
        if value >= 0:
            break
        streak += 1
    return {
        "ref": "EX_NIM_YOY",
        "kind": "grouped_bars",
        "title": (
            f"净息差相对一年前：{len(finished)} 季里 {negative} 季为负，"
            f"最近连续 {streak} 季低于一年前"
        ),
        "xlabels": [compact_period(period) for period in periods],
        "xrot": 90,
        "groups": [{"name": "NIM 同比变化", "color": "BLUE", "values": rounded(delta)}],
        "bar_labels": False,
        "fmt": "pp1",
        "label_fmt": "pp1",
        "ylab": "pp vs 一年前",
        "note": (
            "净息差是公司自己在每份业绩新闻稿的「Net Interest Margin」表里印的数，不是本页自算。"
            "把它对一年前作差，是为了避开季节性：客户余额和交易量都有季度节奏，"
            "而利率周期没有。"
            "<b>本图单位是百分点</b>，与规模那几张的百分比不可直接比大小 —— "
            "率的变化取算术差，除一次只会得到一个没人引用的数。"
            f"最近这 {streak} 季连续为负，正是本页头条要讲的事：规模在涨，价在跌。"
        ),
        "src_extra": RELEASE_SOURCE,
    }


# ── section two ─────────────────────────────────────────────────────────────

def revenue_quarter(staging: dict) -> dict:
    periods = staging["periods"][-RECENT:]
    financials = staging["financials_usd_m"]
    revenue = financials["total_net_revenues"]
    return {
        "ref": "EX_REV",
        "kind": "gs_bar",
        "title": (
            f"总净收入 US${revenue[-1]:,.0f}M、同比 "
            f"{signed(pct_change(revenue[-1], revenue[-5]))}"
        ),
        "xlabels": [compact_period(period) for period in periods],
        "values": rounded(revenue[-RECENT:]),
        "legend": "总净收入",
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$M",
        "ylab2": "同比增速",
        "yoy": {
            "name": "总净收入 YoY (RHS)",
            "values": rounded(yoy(revenue)[-RECENT:]),
            "color": "GREEN",
            "yfmt": "pct1",
        },
        "note": (
            "总净收入 = 佣金 + 其他费用与服务 + 其他收入 + 净利息收入，公司损益表的小计行。"
            "本季创纪录，但增长的构成才是问题所在："
            f"见 Exhibit {{EX_MIX}} 的结构与 Exhibit {{EX_NIM}} 的价格。"
            "注意这条线自带噪音 —— 其中「其他收入」含公司的货币多元化头寸损益，"
            f"见 Exhibit {{EX_OTHER}}。"
        ),
        "src_extra": INCOME_SOURCE,
    }


def revenue_mix_quarter(staging: dict) -> dict:
    periods = staging["periods"][-RECENT:]
    financials = staging["financials_usd_m"]
    revenue = financials["total_net_revenues"]
    net_interest = financials["net_interest_income"]
    share = ratio(net_interest, revenue)
    return {
        "ref": "EX_MIX",
        "kind": "stacked_dual",
        "title": (
            f"收入三条腿：净利息 US${net_interest[-1]:,.0f}M，占总净收入 {share[-1]:.1f}%"
        ),
        "xlabels": [compact_period(period) for period in periods],
        "stacks": [
            {"name": "净利息收入", "color": "NAVY",
             "values": rounded(net_interest[-RECENT:])},
            {"name": "佣金", "color": "BLUE",
             "values": rounded(financials["commissions"][-RECENT:])},
            {"name": "其他费用与服务 + 其他收入", "color": "GOLD",
             "values": rounded([
                 None if None in (fee, other) else fee + other
                 for fee, other in zip(financials["other_fees_and_services"][-RECENT:],
                                       financials["other_income"][-RECENT:])])},
        ],
        "line": {"name": "净利息占比 (RHS)", "color": "RED",
                 "values": rounded(share[-RECENT:]), "yfmt": "pct1"},
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$M",
        "ylab2": "净利息占比",
        "note": (
            "<b>这家券商一半以上的收入不来自交易佣金，而来自客户余额的利差。</b>"
            f"本季净利息 US${net_interest[-1]:,.0f}M 对佣金 "
            f"US${financials['commissions'][-1]:,.0f}M，前者是后者的 "
            f"{net_interest[-1] / financials['commissions'][-1]:.2f} 倍。"
            "这也是为什么本页把净息差放在与交易量同等的位置："
            "对 IBKR 来说，利率是收入的价格，不是背景。"
            f"这个占比的长期迁移见 Exhibit {{EX_MIX_LONG}}。"
        ),
        "src_extra": INCOME_SOURCE,
    }


def nim_and_yields(staging: dict) -> dict:
    periods = staging["periods"][-RECENT:]
    nim = staging["nim"]
    return {
        "ref": "EX_NIM",
        "kind": "lines",
        "title": (
            f"净息差 {nim['nim_pct'][-1]:.2f}%，同比 "
            f"{nim['nim_pct'][-1] - nim['nim_pct'][-5]:+.2f}pp；三条年化收益率同比全线下行"
        ),
        "xlabels": [compact_period(period) for period in periods],
        "series": [
            {"name": "保证金贷款收益率", "values": rounded(nim["yield_margin_loans_pct"][-RECENT:]),
             "color": "NAVY"},
            {"name": "隔离资金收益率", "values": rounded(nim["yield_segregated_pct"][-RECENT:]),
             "color": "BLUE"},
            {"name": "客户贷方余额付息率", "values": rounded(nim["yield_credits_pct"][-RECENT:]),
             "color": "GOLD"},
            {"name": "净息差 NIM", "values": rounded(nim["nim_pct"][-RECENT:]),
             "color": "RED"},
        ],
        "fmt": "pct2",
        "yfmt": "pct2",
        "label_fmt": "pct2",
        "end_label": True,
        "ylab": "年化",
        "note": (
            "<b>本页的核心矛盾在这张图上。</b>四条线全部是公司自己在净息差表里印的年化数字，"
            "不是本页自算。同比看："
            f"保证金贷款 {nim['yield_margin_loans_pct'][-5]:.2f}% → "
            f"{nim['yield_margin_loans_pct'][-1]:.2f}%，"
            f"隔离资金 {nim['yield_segregated_pct'][-5]:.2f}% → "
            f"{nim['yield_segregated_pct'][-1]:.2f}%，"
            f"客户贷方付息 {nim['yield_credits_pct'][-5]:.2f}% → "
            f"{nim['yield_credits_pct'][-1]:.2f}%。"
            "付息率同时下降，说明利差的压缩比资产端收益率的降幅要小 —— "
            "但方向是一致的，四条线没有一条在往上走。"
            "纵轴不自 0 起，但没有任何点被截掉。"
        ),
        "src_extra": RELEASE_SOURCE,
    }


def customer_scale(staging: dict) -> dict:
    periods = staging["periods"][-RECENT:]
    operating = staging["operating"]
    accounts = operating["accounts_thousands"]
    equity = operating["customer_equity_usd_bn"]
    return {
        "ref": "EX_SCALE",
        "kind": "gs_bar",
        "title": (
            f"客户权益 US${equity[-1]:,.1f}B、同比 {signed(pct_change(equity[-1], equity[-5]))}；"
            f"账户数 {accounts[-1] / 1000:.2f} 百万、同比 "
            f"{signed(pct_change(accounts[-1], accounts[-5]))}"
        ),
        "xlabels": [compact_period(period) for period in periods],
        "values": rounded(equity[-RECENT:]),
        "legend": "客户权益",
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$B",
        "ylab2": "账户数同比",
        "yoy": {
            "name": "账户数 YoY (RHS)",
            "values": rounded(yoy(accounts)[-RECENT:]),
            "color": "GREEN",
            "yfmt": "pct1",
        },
        "note": (
            "柱是客户权益（US$B），右轴线是<b>账户数</b>的同比 —— 两个不同的量放在一张图上，"
            "是因为它们本季给出的答案一致：规模两端都在以三成以上的速度扩张。"
            "<b>但客户权益不是净流入。</b>公司披露的是期末权益，其变动同时包含客户净入金与市值波动，"
            "申报文件里没有把两者分开，所以本页不发布任何「净流入」口径的数字，"
            "也不用权益的环比变动去近似它。"
        ),
        "src_extra": RELEASE_SOURCE,
    }


def upc_wedge(staging: dict) -> dict:
    periods = staging["periods"][-RECENT:]
    financials = staging["financials_usd_m"]
    net_income = financials["net_income"]
    nci = financials["net_income_noncontrolling"]
    common = financials["net_income_common"]
    share = ratio(nci, net_income)
    return {
        "ref": "EX_UPC",
        "kind": "stacked_dual",
        "title": (
            f"净利润 US${net_income[-1]:,.0f}M 里，归上市公司普通股东的只有 "
            f"US${common[-1]:,.0f}M（{100 - share[-1]:.1f}%）"
        ),
        "xlabels": [compact_period(period) for period in periods],
        "stacks": [
            {"name": "归属少数股东（IBG Holdings）", "color": "GOLD",
             "values": rounded(nci[-RECENT:])},
            {"name": "归属普通股东", "color": "NAVY",
             "values": rounded(common[-RECENT:])},
        ],
        "line": {"name": "少数股东占比 (RHS)", "color": "RED",
                 "values": rounded(share[-RECENT:]), "yfmt": "pct1"},
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$M",
        "ylab2": "少数股东占比",
        "note": (
            "<b>这是本站其他任何一页都没有的一条线。</b>"
            "IBKR 是 Up-C 结构：上市主体 Interactive Brokers Group, Inc. 只持有经营实体 "
            "IBG LLC 的少数权益，其余由 IBG Holdings LLC 持有，"
            "因此合并报表上的净利润绝大部分被记为「归属少数股东」。"
            f"本季 US${net_income[-1]:,.0f}M 的净利润里，US${nci[-1]:,.0f}M "
            f"（{share[-1]:.1f}%）不归上市公司股东。"
            "读这家公司的利润表时，「净利润」和「普通股东能分到的利润」是两个相差四倍的数，"
            f"这个比例的长期走向见 Exhibit {{EX_UPC_LONG}}。"
        ),
        "src_extra": INCOME_SOURCE,
    }


def other_income_swing(staging: dict) -> dict:
    periods = staging["periods"]
    other = staging["financials_usd_m"]["other_income"]
    window = other[-13:]
    biggest = max((value for value in window if value is not None), key=abs)
    return {
        "ref": "EX_OTHER",
        "kind": "grouped_bars",
        "title": (
            f"「其他收入」的摆动：近 13 季在 US${min(v for v in window if v is not None):,.0f}M 与 "
            f"US${max(v for v in window if v is not None):,.0f}M 之间"
        ),
        "xlabels": [compact_period(period) for period in periods[-13:]],
        "xrot": 90,
        "groups": [{"name": "其他收入", "color": "BLUE", "values": rounded(window)}],
        "bar_labels": True,
        "fmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$M",
        "note": (
            "这一行里装着公司的<b>货币多元化策略</b>：IBKR 把自身净值锚定在一篮子十种货币"
            "（公司称之为 GLOBAL）上，该头寸的损益一部分进「其他收入」、一部分进其他综合收益。"
            "所以总净收入这条线自带一块与经营无关的波动 —— "
            f"窗口内最大的一次是 US${biggest:,.0f}M。"
            "<b>本页不把它剔除后另画一条「调整后收入」线</b>："
            "公司在新闻稿里确实同时给出 adjusted 口径，但每季剔除哪几项由公司当季决定，"
            "把若干季的 adjusted 数连成一条线会把口径变化画成经营变化。"
        ),
        "src_extra": INCOME_SOURCE,
    }


def pretax_margin_quarter(staging: dict) -> dict:
    periods = staging["periods"][-RECENT:]
    financials = staging["financials_usd_m"]
    margin = ratio(financials["pretax_income"], financials["total_net_revenues"])
    expense = ratio(financials["total_non_interest_expenses"],
                    financials["total_net_revenues"])
    return {
        "ref": "EX_MARGIN",
        "kind": "lines",
        "title": (
            f"税前利润率 {margin[-1]:.1f}%，同比 {margin[-1] - margin[-5]:+.1f}pp；"
            f"非息费用率 {expense[-1]:.1f}%"
        ),
        "xlabels": [compact_period(period) for period in periods],
        "series": [
            {"name": "税前利润率", "values": rounded(margin[-RECENT:]), "color": "NAVY"},
            {"name": "非息费用 / 总净收入", "values": rounded(expense[-RECENT:]),
             "color": "GOLD"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "占总净收入",
        "note": (
            "两条线相加恒等于 100%：税前利润率 = 1 − 非息费用率，这是损益表的恒等式，"
            "不是巧合，也不需要任何估计 —— 券商的损益表在总净收入之下只有一个费用小计。"
            "所以这张图真正要看的是费用率那条："
            f"本季 {expense[-1]:.1f}%，"
            f"公司把每一美元收入里的 {margin[-1]:.0f} 美分留在了税前利润里。"
            f"这条费用率的十年下行见 Exhibit {{EX_LEVERAGE}}。"
        ),
        "src_extra": INCOME_SOURCE,
    }


# ── section four ────────────────────────────────────────────────────────────

def revenue_mix_long(staging: dict) -> dict:
    periods = staging["periods"]
    financials = staging["financials_usd_m"]
    revenue = financials["total_net_revenues"]
    net_interest_share = ratio(financials["net_interest_income"], revenue)
    commission_share = ratio(financials["commissions"], revenue)
    # The two crossings are the whole point of the long window, so they are read
    # off the series rather than typed: an inverted stretch that moved by one
    # quarter would otherwise leave the caption quietly wrong.
    inverted_at = [index for index in range(len(periods))
                   if commission_share[index] > net_interest_share[index]]
    crossings = [periods[inverted_at[0]], periods[inverted_at[-1] + 1]]
    inverted = len(inverted_at)
    return {
        "ref": "EX_MIX_LONG",
        "kind": "lines",
        "title": (
            f"利率周期改写了收入结构：净利息占比 {net_interest_share[0]:.1f}% → "
            f"{net_interest_share[-1]:.1f}%，佣金占比 {commission_share[0]:.1f}% → "
            f"{commission_share[-1]:.1f}%"
        ),
        "xlabels": [compact_period(period) for period in periods],
        "xrot": 90,
        "series": [
            {"name": "净利息占比", "values": rounded(net_interest_share), "color": "NAVY"},
            {"name": "佣金占比", "values": rounded(commission_share), "color": "BLUE"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "占总净收入",
        "note": (
            f"{len(periods)} 个季度覆盖了完整的一轮利率周期：2020–2021 的零利率、"
            "2022–2023 的加息、以及 2024 年之后的降息。"
            f"两条线交叉过<b>两次</b> —— {crossings[0]} 零利率把净利息压到佣金之下，"
            f"直到 {crossings[1]} 加息把它重新推回第一大收入来源，"
            f"中间整整 {inverted} 个季度里佣金才是这家公司最大的一条收入线。"
            "<b>八个季度看不出这件事</b>：它需要一整轮周期才能显形，"
            "而这正是本页把常规序列拉到三十季而不是八季的原因。"
        ),
        "src_extra": INCOME_SOURCE,
    }


def nim_long(staging: dict) -> dict:
    periods = staging["periods"]
    nim = staging["nim"]
    values = [value for value in nim["nim_pct"] if value is not None]
    trough = min(values)
    peak = max(values)
    return {
        "ref": "EX_NIM_LONG",
        "kind": "lines",
        "title": (
            f"净息差走完一轮周期：谷底 {trough:.2f}%、峰值 {peak:.2f}%、本季 "
            f"{nim['nim_pct'][-1]:.2f}%；平均生息资产同期 "
            f"{nim['avg_earning_assets_usd_m'][0] / 1000:.0f} → "
            f"{nim['avg_earning_assets_usd_m'][-1] / 1000:.0f} 十亿美元"
        ),
        "xlabels": [compact_period(period) for period in periods],
        "xrot": 90,
        "series": [
            {"name": "净息差 NIM", "values": rounded(nim["nim_pct"]), "color": "RED"},
            {"name": "隔离资金收益率", "values": rounded(nim["yield_segregated_pct"]),
             "color": "BLUE"},
            {"name": "保证金贷款收益率", "values": rounded(nim["yield_margin_loans_pct"]),
             "color": "NAVY"},
        ],
        "fmt": "pct2",
        "yfmt": "pct2",
        "label_fmt": "pct2",
        "end_label": True,
        "ylab": "年化",
        "note": (
            "在零利率那几个季度，隔离资金的年化收益率是<b>负的</b> —— "
            "公司为持有客户的隔离现金而付费，这不是取数错误，是当时的市场利率。"
            f"净息差从 {trough:.2f}% 的谷底走到 {peak:.2f}% 的峰值再回落到今天，"
            "而同期平均生息资产翻了近四倍：规模的扩张一直在，价格没有。"
            "把这两件事放在同一张图上，就能看出为什么本季收入创纪录与净息差下行"
            "并不矛盾。纵轴不自 0 起，但没有任何点被截掉。"
        ),
        "src_extra": RELEASE_SOURCE,
    }


def scale_long(staging: dict) -> dict:
    periods = staging["periods"]
    operating = staging["operating"]
    accounts = operating["accounts_thousands"]
    equity = operating["customer_equity_usd_bn"]
    per_account = [None if None in (e, a) or a == 0 else e * 1e6 / a
                   for e, a in zip(equity, accounts)]
    return {
        "ref": "EX_SCALE_LONG",
        "kind": "lines",
        "title": (
            f"账户数 {accounts[0] / 1000:.2f} → {accounts[-1] / 1000:.2f} 百万，"
            f"户均权益 US${per_account[0]:,.0f} → US${per_account[-1]:,.0f}"
        ),
        "xlabels": [compact_period(period) for period in periods],
        "xrot": 90,
        "series": [
            {"name": "户均客户权益（US$）D", "values": rounded(per_account),
             "color": "NAVY"},
        ],
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "end_label": True,
        "ylab": "US$ / 账户",
        "note": (
            "户均权益是本页自算（D）：客户权益 ÷ 账户数，两个分量都是公司披露值。"
            "<b>这条线是判断增长质量的那一条</b>：如果新账户显著小于存量账户，"
            "它会被稀释下去，账户数的高增速就不会等比例地变成收入。"
            f"它确实被稀释过 —— 从 {periods[per_account.index(max(per_account))]} 的峰值 "
            f"US${max(per_account):,.0f} 一路跌到 "
            f"{periods[per_account.index(min(per_account))]} 的 US${min(per_account):,.0f}，"
            "熊市与一波小额新户同时压着它。"
            f"但此后它<b>回升了 {per_account[-1] / min(per_account) - 1:.1%}</b>，"
            f"而同期账户数还在继续翻倍 —— "
            "也就是说 2022 年之后新增的账户不再明显拖低平均值。"
            f"注意本季 US${per_account[-1]:,.0f} 仍比窗口起点低 "
            f"{1 - per_account[-1] / per_account[0]:.0%}，稀释发生过，只是已经停下来了。"
        ),
        "src_extra": RELEASE_SOURCE,
    }


def upc_long(staging: dict) -> dict:
    periods = staging["periods"]
    financials = staging["financials_usd_m"]
    share = ratio(financials["net_income_noncontrolling"], financials["net_income"])
    return {
        "ref": "EX_UPC_LONG",
        "kind": "lines",
        "title": (
            f"少数股东占净利润的比例：{share[0]:.1f}% → {share[-1]:.1f}%，"
            f"{len(periods)} 季共下降 {share[0] - share[-1]:.1f}pp"
        ),
        "xlabels": [compact_period(period) for period in periods],
        "xrot": 90,
        "series": [
            {"name": "归属少数股东占比 D", "values": rounded(share), "color": "GOLD"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "占合并净利润",
        "note": (
            "比例是本页自算（D）：归属少数股东的净利润 ÷ 合并净利润，两个分量都是申报值。"
            "这条线单向下行，是因为上市主体逐年从 IBG Holdings 手中收购 IBG LLC 的权益单位，"
            "上市公司股东对同一份利润的 claim 因此缓慢扩大。"
            f"但 {len(periods)} 季只走了 {share[0] - share[-1]:.1f}pp，"
            f"今天仍有 {share[-1]:.1f}% 的合并利润不归上市公司股东 —— "
            "按这个斜率，这不是一个几年内会消失的楔子。"
            "纵轴不自 0 起，但没有任何点被截掉。"
        ),
        "src_extra": INCOME_SOURCE,
    }


def operating_leverage_long(staging: dict) -> dict:
    periods = staging["periods"]
    financials = staging["financials_usd_m"]
    expense = ratio(financials["total_non_interest_expenses"],
                    financials["total_net_revenues"])
    compensation = ratio(financials["employee_compensation"],
                         financials["total_net_revenues"])
    return {
        "ref": "EX_LEVERAGE",
        "kind": "lines",
        "title": (
            f"经营杠杆：非息费用率 {expense[0]:.1f}% → {expense[-1]:.1f}%，"
            f"薪酬率 {compensation[0]:.1f}% → {compensation[-1]:.1f}%"
        ),
        "xlabels": [compact_period(period) for period in periods],
        "xrot": 90,
        "series": [
            {"name": "非息费用 / 总净收入 D", "values": rounded(expense), "color": "NAVY"},
            {"name": "员工薪酬 / 总净收入 D", "values": rounded(compensation),
             "color": "BLUE"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "占总净收入",
        "note": (
            "两条比率都是本页自算（D），分子分母都是申报值。"
            f"费用率从 {expense[0]:.1f}% 降到 {expense[-1]:.1f}%，"
            f"薪酬率从 {compensation[0]:.1f}% 降到 {compensation[-1]:.1f}% —— "
            "在一家几乎全自动化的券商里，收入随利率与客户余额放大，人力不随之放大。"
            "<b>但要小心把这读成纯粹的效率提升</b>：分母里有一半以上是净利息收入，"
            "而净利息收入的高低主要由利率决定。利率下行时，同一批人和同一套系统会让"
            "这条线自己回升，那不是费用失控。"
        ),
        "src_extra": INCOME_SOURCE,
    }


def commission_long(staging: dict) -> dict:
    periods = staging["periods"]
    operating = staging["operating"]
    commission = operating["commission_per_order_usd"]
    start = next(index for index, value in enumerate(commission) if value is not None)
    values = [value for value in commission if value is not None]
    return {
        "ref": "EX_COMMISSION",
        "kind": "lines",
        "title": (
            f"每笔已清算订单佣金：{len(values)} 季从 US${values[0]:.2f} 到 "
            f"US${values[-1]:.2f}，峰值 US${max(values):.2f}"
        ),
        "xlabels": [compact_period(period) for period in periods],
        "xrot": 90,
        "series": [
            {"name": "每笔已清算订单佣金", "values": rounded(commission), "color": "NAVY"},
        ],
        "fmt": "usd2",
        "yfmt": "usd2",
        "label_fmt": "usd2",
        "end_label": True,
        "ylab": "US$ / 笔",
        "note": (
            f"<b>这条线从 {periods[start]} 起算，不是本页少取了数。</b>"
            "公司在此之前公布的是「Commission per DART」，从这一季起改为"
            "「Commission per Cleared Commissionable Order」，两个口径从未在同一份新闻稿里"
            "并列出现过，因此没有可供拼接的重叠季 —— 强行接成一条线就是无中生有。"
            "<b>口径之内它并不平稳，也没有趋势性上行。</b>"
            f"US${values[0]:.2f} 起步，2021 年散户潮里被小额订单摊薄到 US${min(values):.2f} 的谷底，"
            f"随后回到 US${max(values[1:]):.2f}，此后一路走低到今天的 US${values[-1]:.2f}。"
            "<b>要小心把这条线读成公司的定价。</b>它是<b>实现</b>的单均佣金，"
            "同时受费率表与订单结构影响 —— 一批小额订单和一次降价在这张图上长得一模一样，"
            "申报文件不拆开这两者，所以本页只说它的走向，不说公司调没调价。"
            "能说的是结果：佣金收入的增长来自笔数，而单均收费同期是逆风。"
        ),
        "src_extra": RELEASE_SOURCE,
    }


# ── payload ─────────────────────────────────────────────────────────────────

def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    labels = [compact_period(period) for period in periods]
    financials = staging["financials_usd_m"]
    operating = staging["operating"]
    nim = staging["nim"]

    revenue = financials["total_net_revenues"]
    net_interest = financials["net_interest_income"]
    net_income = financials["net_income"]
    nci = financials["net_income_noncontrolling"]
    common = financials["net_income_common"]
    nci_share = ratio(nci, net_income)
    expense_ratio = ratio(financials["total_non_interest_expenses"], revenue)
    pretax_margin = ratio(financials["pretax_income"], revenue)
    accounts = operating["accounts_thousands"]
    equity = operating["customer_equity_usd_bn"]
    darts = operating["darts_thousands"]

    settled_ex = [consecutive_record(staging), nim_record(staging)]

    highlight_ex = [
        revenue_quarter(staging),
        revenue_mix_quarter(staging),
        nim_and_yields(staging),
        customer_scale(staging),
        upc_wedge(staging),
        other_income_swing(staging),
        pretax_margin_quarter(staging),
    ]

    next_kpi = staging["next_kpi"]
    quantified = next_kpi["quantified"]
    long_labels = labels
    next_ex = [
        headroom_exhibit(
            f"下季 {len(quantified)} 条阈值与当前值的距离（正数 = 仍在安全侧）",
            quantified, "current",
            note=(
                "所有阈值都是<b>本站的研究设定</b>，不是公司指引，也不是评级 —— "
                "IBKR 不发布季度指引，本页也不会替它编一个。"
                "把百分比、美元金额与每笔单价归一到「距阈值余量」这一个口径，"
                "是为了让一张图同时回答「哪几条已经越线」。"
                "<b>本页首次覆盖，这是第一组阈值</b>，下一季第一节才会有本站自己的闭环。"
                + next_kpi["excluded"]
            ),
            src_extra="当前值全部取自本季 10-Q 与业绩 8-K 的申报值。",
        ),
        threshold_exhibit(
            "净息差 NIM：越高越安全",
            long_labels, rounded(nim["nim_pct"]), quantified[0]["threshold"],
            fmt="pct2", ylab="年化",
            actual_name="实际 NIM", threshold_name="阈值 1.80%",
            note=(
                "上一张图说哪条线越了，这张说它是怎么走到那里的。"
                f"本季 {nim['nim_pct'][-1]:.2f}%，距 {quantified[0]['threshold']:.2f}% 还有 "
                f"{nim['nim_pct'][-1] - quantified[0]['threshold']:.2f}pp。"
                "阈值取的是本季再向下一个台阶，不是长期趋势的外推："
                "跌破它意味着降息对利差的侵蚀开始快过生息资产的扩张。"
            ),
            src_extra=RELEASE_SOURCE,
        ),
        threshold_exhibit(
            "账户数环比增速：越高越安全",
            long_labels, rounded(qoq(accounts)), quantified[1]["threshold"],
            fmt="pct1", ylab="环比增速",
            actual_name="账户数 环比", threshold_name="阈值 +6.0%",
            note=(
                f"本季 {qoq(accounts)[-1]:.2f}%。阈值 +6.0% 大致是过去两年的中枢，"
                "跌破它说明揽客速度回到加息周期之前的水平。"
                "<b>这里用环比而不是同比</b>：账户数是存量，同比会把四个季度前的一次性事件"
                "在图上拖四个季度。"
            ),
            src_extra=RELEASE_SOURCE,
        ),
        threshold_exhibit(
            "每笔已清算订单佣金：越高越安全",
            long_labels, rounded(operating["commission_per_order_usd"]),
            quantified[2]["threshold"],
            fmt="usd2", ylab="US$ / 笔",
            actual_name="每笔佣金", threshold_name="阈值 $2.55",
            note=(
                f"本季 US${operating['commission_per_order_usd'][-1]:.2f}。"
                f"这条线在 {operating['commission_metric_from']} 之前是空的，"
                "因为公司当时公布的是另一个口径的指标（Commission per DART），"
                f"详见 Exhibit {{EX_COMMISSION}}。"
                "阈值设在 $2.55：跌破它意味着单价开始承压，"
                "而 IBKR 的佣金增长至今几乎全部来自笔数。"
            ),
            src_extra=RELEASE_SOURCE,
        ),
        threshold_exhibit(
            "非息费用 / 总净收入：越低越安全",
            long_labels, rounded(expense_ratio), quantified[3]["threshold"],
            fmt="pct1", ylab="占总净收入",
            actual_name="非息费用率 D", threshold_name="阈值 25.0%",
            note=(
                f"本季 {expense_ratio[-1]:.2f}%，距 25.0% 的阈值还有 "
                f"{quantified[3]['threshold'] - expense_ratio[-1]:.2f}pp。"
                "<b>这条阈值天生偏松，说明写在这里而不是藏起来</b>：分母含净利息收入，"
                "利率下行会让这条线自己上移，所以越过 25% 不必然是费用出了问题。"
                "真正要看的是越线时费用的绝对额是否同步跳升。"
            ),
            src_extra=INCOME_SOURCE,
        ),
        threshold_exhibit(
            "少数股东占净利润比：越低越安全",
            long_labels, rounded(nci_share), quantified[4]["threshold"],
            fmt="pct1", ylab="占合并净利润",
            actual_name="少数股东占比 D", threshold_name="阈值 77.5%",
            note=(
                f"本季 {nci_share[-1]:.2f}%。这条线单向下行已有数年，"
                "阈值 77.5% 设在本季略上方：回到阈值以上意味着上市主体收购 LLC 权益单位的节奏中断，"
                "上市公司股东对利润的 claim 停止扩大。"
                f"长期走向见 Exhibit {{EX_UPC_LONG}}。"
            ),
            src_extra=INCOME_SOURCE,
        ),
        threshold_exhibit(
            "客户保证金贷款：越高越安全",
            long_labels, rounded(operating["customer_margin_loans_usd_bn"]),
            quantified[5]["threshold"],
            fmt="f0c", ylab="US$B",
            actual_name="客户保证金贷款", threshold_name="阈值 US$95B",
            note=(
                f"本季 US${operating['customer_margin_loans_usd_bn'][-1]:,.1f}B，"
                f"同比 {signed(pct_change(operating['customer_margin_loans_usd_bn'][-1], operating['customer_margin_loans_usd_bn'][-5]))}。"
                "保证金贷款是净利息收入里收益率最高的一块资产，"
                "所以它比客户权益更直接地决定下一季的净利息收入。"
                "这条线同样从 2020Q1 起算：公司在此之前不在新闻稿里按季给这个余额。"
            ),
            src_extra=RELEASE_SOURCE,
        ),
    ]

    routine_ex = [
        revenue_mix_long(staging),
        nim_long(staging),
        scale_long(staging),
        upc_long(staging),
        operating_leverage_long(staging),
        commission_long(staging),
    ]

    exhibits = number_exhibits(settled_ex + highlight_ex + next_ex + routine_ex, start=2)
    resolve_exhibit_refs(exhibits)
    first_table = exhibits[-1]["n"] + 1

    # ── audit tables ────────────────────────────────────────────────────────
    income_rows = [
        [periods[index],
         f"${revenue[index]:,.0f}M",
         f"${financials['commissions'][index]:,.0f}M",
         f"${financials['other_fees_and_services'][index]:,.0f}M D",
         f"${financials['other_income'][index]:,.0f}M D",
         f"${net_interest[index]:,.0f}M D",
         f"${financials['total_non_interest_expenses'][index]:,.0f}M",
         f"${financials['pretax_income'][index]:,.0f}M",
         f"${net_income[index]:,.0f}M",
         f"${nci[index]:,.0f}M",
         f"${common[index]:,.0f}M D",
         "10-K 全年减九个月 D" if staging["basis"][index] == "fy_minus_9m"
         else "10-Q 申报三个月栏"]
        for index in range(len(periods))
    ]

    operating_rows = [
        [periods[index],
         f"{accounts[index]:,.0f}K",
         f"${equity[index]:,.1f}B",
         f"{darts[index]:,.0f}K",
         f"${operating['commission_per_order_usd'][index]:.2f}"
         if operating["commission_per_order_usd"][index] is not None else "—",
         f"${operating['customer_credits_usd_bn'][index]:,.1f}B"
         if operating["customer_credits_usd_bn"][index] is not None else "—",
         f"${operating['customer_margin_loans_usd_bn'][index]:,.1f}B"
         if operating["customer_margin_loans_usd_bn"][index] is not None else "—",
         staging["release_dates"].get(periods[index]) or "—"]
        for index in range(len(periods))
    ]

    nim_rows = [
        [periods[index],
         f"${nim['avg_earning_assets_usd_m'][index]:,.0f}M",
         f"{nim['nim_pct'][index]:.2f}%",
         f"{nim['yield_segregated_pct'][index]:.2f}%",
         f"{nim['yield_margin_loans_pct'][index]:.2f}%",
         f"{nim['yield_credits_pct'][index]:.2f}%",
         f"${net_interest[index]:,.0f}M D"]
        for index in range(len(periods))
    ]

    tables = [
        threshold_table(first_table, "下季阈值与当前值（原单位）",
                        quantified, "current", "当前值"),
        {
            "n": first_table + 1,
            "title": f"{len(periods)} 季损益表（每季注明取自申报三个月栏还是全年减九个月）",
            "headers": ["期间", "总净收入", "佣金", "其他费用与服务 D", "其他收入 D",
                        "净利息收入 D", "非息费用", "税前利润", "净利润",
                        "归属少数股东", "归属普通股东 D", "取数方式"],
            "rows": income_rows,
        },
        {
            "n": first_table + 2,
            "title": f"{len(periods)} 季运营指标（含各季业绩新闻稿的申报日期）",
            "headers": ["期间", "账户数", "客户权益", "总 DARTs", "每笔订单佣金",
                        "客户贷方余额", "客户保证金贷款", "新闻稿申报日"],
            "rows": operating_rows,
        },
        {
            "n": first_table + 3,
            "title": f"{len(periods)} 季净息差表（公司披露值，非本页自算）",
            "headers": ["期间", "平均生息资产", "净息差 NIM", "隔离资金收益率",
                        "保证金贷款收益率", "客户贷方付息率", "GAAP 净利息收入 D"],
            "rows": nim_rows,
        },
        ai_capex_cycle_table(first_table + 4),
    ]

    return {
        "schema_version": "quarterly-dashboard/ibkr-v1",
        "page": {"slug": "ibkr", "language": "zh-CN"},
        "company": {
            "ticker": "IBKR",
            "name": "Interactive Brokers Group",
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
        "tracker": "Watchlist Quarterly Tracker · IBKR",
        "title": "Interactive Brokers (IBKR)：Q2 2026 季报仪表盘",
        "subtitle": (
            "截至 2026-06-30 · 发布 2026-07-21 · US GAAP · 未审计 · "
            "财年即自然年，本页季度标注无需映射"
        ),
        "headline": (
            f"客户端每一项都在爆发 —— 账户数 {accounts[-1] / 1000:.2f} 百万、同比 "
            f"{signed(pct_change(accounts[-1], accounts[-5]))}，"
            f"客户权益 US${equity[-1]:,.1f}B、同比 {signed(pct_change(equity[-1], equity[-5]))}，"
            f"DARTs 同比 {signed(pct_change(darts[-1], darts[-5]))} —— "
            f"但净息差从 {nim['nim_pct'][-5]:.2f}% 压到 {nim['nim_pct'][-1]:.2f}%，"
            "公司自己披露的三条年化收益率同比无一例外全线下行。"
            f"总净收入 US${revenue[-1]:,.0f}M 的纪录是量堆出来的，不是价。"
            f"而这 US${net_income[-1]:,.0f}M 净利润里，只有 US${common[-1]:,.0f}M"
            f"（{100 - nci_share[-1]:.1f}%）归上市公司普通股东。"
        ),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>矛盾</span><b>量在涨，价在跌</b>'
            f'<p>账户数、客户权益、DARTs 三项同比都在三成以上，'
            f'净息差却同比 {nim["nim_pct"][-1] - nim["nim_pct"][-5]:+.2f}pp。'
            f'保证金贷款收益率 {nim["yield_margin_loans_pct"][-5]:.2f}% → '
            f'{nim["yield_margin_loans_pct"][-1]:.2f}%，四条利率线没有一条在往上走。</p></article>'
            '<article><span>结构</span><b>一半以上的收入不是佣金</b>'
            f'<p>净利息收入 US${net_interest[-1]:,.0f}M，占总净收入 '
            f'{net_interest[-1] / revenue[-1] * 100:.1f}%，是佣金的 '
            f'{net_interest[-1] / financials["commissions"][-1]:.2f} 倍。'
            f'{len(periods)} 季里这个占比从 '
            f'{net_interest[0] / revenue[0] * 100:.1f}% 走到今天，走完了一整轮利率周期。</p></article>'
            '<article><span>结构</span><b>净利润有四分之三不归你</b>'
            f'<p>Up-C 结构下，合并净利润的 {nci_share[-1]:.1f}% 归 IBG Holdings。'
            f'这个比例 {len(periods)} 季只降了 {nci_share[0] - nci_share[-1]:.1f}pp，'
            '读这家公司的利润表必须先把这个楔子扣掉。</p></article>'
            '</div>'
        ),
        "source": (
            'Source: <a href="https://www.sec.gov/Archives/edgar/data/1381197/'
            '000138119726000118/ibkr-ex99_1.htm" rel="noopener">IBKR 2Q2026 '
            '业绩新闻稿（8-K EX-99.1）</a>与截至 2026-06-30 的 10-Q。'
        ),
        "source_url": (
            "https://www.sec.gov/Archives/edgar/data/1381197/"
            "000138119726000118/ibkr-ex99_1.htm"
        ),
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {
                "id": "settled",
                "title": "一、上季兑现了吗",
                "description": plain_text(
                    "本页首次覆盖，没有上一份笔记留下的阈值可结算，"
                    "本站自己的闭环从下一季开始。"
                    + NO_GUIDANCE_NOTE
                    + "这一节因此改为结算公司自己每季都印的那两个对照对象："
                    "「Consecutive Quarters」环比表，以及净息差表 —— "
                    "两者都拉成完整记录，因为一个季度的环比说明不了任何事。"
                ),
                "exhibits": settled_ex,
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": plain_text(
                    "创纪录的总净收入、它的三条腿、"
                    "决定其中最大一条腿价格的四条利率线、"
                    "客户端的规模、Up-C 结构切走的那一块，"
                    "以及总收入里那块与经营无关的货币头寸波动。"
                ),
                "exhibits": highlight_ex,
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": plain_text(
                    "六条阈值，全部是本站研究设定而非公司指引；"
                    "每条都先在归一化的余量图上出现一次，再各给一张自己的历史图。"
                    "不接入的几条写在阈值图的说明里，不给近似值。"
                ),
                "exhibits": next_ex,
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": plain_text(
                    "IBKR 专属的常规序列，窗口三十季而不是八季，"
                    "因为其中几条要走完一整轮利率周期才显形："
                    "收入结构的迁移、净息差与生息资产、账户与户均权益、"
                    "Up-C 楔子、经营杠杆，以及每笔订单的佣金单价。"
                ),
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": [plain_text(_p) for _p in [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，"
            "每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "IBKR 的财年即自然年，因此本页的季度标注不需要任何映射："
            "本页的 Q2 2026 就是公司所称的 2Q2026，即截至 2026-06-30 的三个月。"
            "本站的微软、新思与 Visa 三页需要映射，本页不需要。",
            "<b>IBKR 从不在申报文件里给季度数字指引，因此本页没有逐季的指引兑现记录。</b>"
            "这是取数限制而不是编辑取舍：档案里的历次业绩 8-K 都没有给过下一季的收入区间、"
            "EPS 区间或利润率区间。微软、Alphabet 与 Visa 三页出于同样的理由也没有这类记录；"
            "亚马逊、Cadence、新思、NVIDIA、台积电与 Meta 六页有，是因为那六家把区间写进了申报文件。"
            "把电话会上的前瞻措辞翻译成数字再画成兑现图，正是本仓库要避免的失败。",
            "损益表口径：会计 Q1–Q3 直接取自各季 10-Q 自己印的三个月栏，无需差分；"
            "会计 Q4 没有 10-Q，其各行为 10-K 全年数减去第三季 10-Q 的九个月栏，"
            "两端都是申报值，核对表逐行标注取数方式。",
            "「其他费用与服务」与「其他收入」两行标 D，是因为它们由申报值相减得到："
            "其他费用与服务 = 来自客户合同的收入 − 佣金；"
            "其他收入 = 总净收入 − 佣金 − 其他费用与服务 − 净利息收入。"
            "两条恒等式在全部三十季逐季成立，且与公司新闻稿印出来的对应行完全相等。",
            "运营指标与净息差表<b>不是 XBRL 事实</b>，只存在于各季业绩 8-K 的 EX-99.1 里，"
            "因此本页的这两组序列逐份读自 2018Q4 以来连续三十一份业绩新闻稿，"
            "而不是取自 companyfacts 接口。核对表给出每一季新闻稿的申报日期。",
            "<b>每笔订单佣金这条线从 2020Q1 起算，不是缺数。</b>"
            "公司在 2019Q4 及之前公布的指标叫「Commission per DART」，"
            "自 2020Q1 起改为「Commission per Cleared Commissionable Order」，"
            "两个口径从未在同一份新闻稿里并列出现，没有可供拼接的重叠季。"
            "客户贷方余额与客户保证金贷款两条同样自 2020Q1 起算，"
            "因为公司在此之前不在业绩新闻稿里按季给这两个期末余额。",
            "<b>本页不发布任何跨季度的每股收益序列。</b>"
            "公司于 2025-04-15 宣布 4 拆 1，而申报数据里只有那些后来充当比较期的季度被重述，"
            "因此 EPS 在公开接口上是拆股前后两种口径混在一起的序列，连成一条线会画出一个断崖。"
            "本页改用<b>归属普通股东的净利润（美元）</b>，它可加、且不受拆股影响。",
            "<b>Up-C 结构必须先扣掉再读利润表。</b>上市主体 Interactive Brokers Group, Inc. "
            "只持有经营实体 IBG LLC 的少数权益，其余由 IBG Holdings LLC 持有，"
            "所以合并净利润的大部分被记为「归属少数股东」。"
            "本页把这个比例作为一条常规序列逐季画出，"
            "并在所有涉及利润的图上区分「净利润」与「归属普通股东的净利润」。",
            "<b>客户权益不等于净流入。</b>公司披露的是期末客户权益，"
            "其变动同时包含客户净入金与市值波动，申报文件里没有把两者分开，"
            "因此本页不发布任何「净流入」口径的数字，也不用权益的环比变动去近似它。",
            "净息差、三条年化收益率与平均生息资产均为公司在净息差表里的<b>披露值</b>，"
            "非本页自算。需要注意公司在该表中的「净利息收入」口径略大于损益表上的 GAAP 净利息收入："
            "它把记在「其他费用与服务」和「其他收入」里、性质与利息相同的部分并了进来，"
            "公司在表下的脚注里逐季给出这两笔金额。本页的图与表分别标注了各自用的是哪一个口径。",
            "阈值是<b>本站的研究设定</b>，不是公司指引，也不是评级。"
            "本页首次覆盖，第三节的六条是第一组阈值，第一节的闭环从下一季开始。",
            "本页只发布公司披露值、可复算的简单派生值；D 标记代表 Derived / 自算。"
            "不发布评级、目标价、估值与卖方共识。",
            "本页已知未接入：公司对下一季的任何数字（公司不给）、"
            "分产品与分地区的佣金金额拆分（公司只按地区披露来自客户合同的收入总额，"
            "不把佣金按股票 / 期权 / 期货拆成金额）、客户资产净流入、"
            "公司口径 adjusted 收入与 adjusted EPS 的逐季序列（每季剔除项由公司当季决定）、"
            "以及任何来自业绩电话会而无法与第二个来源核对的前瞻数字。",
            "业绩电话会文字稿仅链接官方 IR 与 SEC 托管版本，公开仓不复制原件或逐字内容。",
        ]],
        "footer": ("IBKR quarterly results · 数据来自 Interactive Brokers 公开披露与透明自算 · "
                   "仅供研究，不构成投资建议"),
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "ibkr.js"), payload, "ibkr")
    shell_dir = ROOT / "ibkr"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("IBKR", "ibkr"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(
        f"IBKR page: {charts} charts in {len(payload['sections'])} sections "
        f"+ {len(payload['tables'])} audit tables"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
