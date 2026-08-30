#!/usr/bin/env python3
"""Build the V (Visa) quarterly-results page.

Same four-part, chart-led shape as the other company pages (上季兑现 → 本季重点
→ 下季跟踪 → 长期常规).  Visa's fiscal year ends 30 September, so every label
here is the calendar quarter the fiscal one covers: the quarter ended
2026-06-30 is the company's FY2026 Q3 and this page's ``Q2 2026``.

Two things make this page different from the guidance-record pages.

The first is a sourcing limit rather than an editorial choice.  **Visa has never
filed a numeric QUARTERLY outlook.**  Every Financial Outlook it ever published
was fiscal-full-year, so the object the Amazon, Cadence and Synopsys pages are
built on -- a next-quarter range and the quarter that settles it -- does not
exist here at any point in the filing history.  The full-year outlook is
disappearing too, in four steps: numeric on some metrics through fiscal 2020,
present but explicitly withheld in fiscal 2020-2021, absent for most of
2022-2023, reduced in fiscal 2024 to one sentence pointing at an earnings
presentation that is not archived on EDGAR, and gone entirely from every release
after 2025-01-30.  The page says so instead of transcribing webcast material
that cannot be checked against a second source.

Deliberately absent: a count of how many releases carried a number.  A sampled
tally does not generalise to the full forty-plus release window, so the page
describes the eras and leaves the arithmetic alone.

The second is what Visa *did* guide, and it happens to be the number this whole
page is about.  "Client incentives as a percent of gross revenues" was given as
a numeric range in the release that opened each fiscal year from 2017 to 2020 --
the only forward number Visa ever put in a filing more than once.  In three of
those four years the rate came in **below** the guided floor: the company gave
back less than it had promised to.  Then it stopped guiding the number, and in
the six years since, the rate has gone from 23.4% to 28.7%.

That rate is the page's spine, and it is a filed figure every quarter back to
2012: the four gross revenue lines and the client-incentive contra line are
disclosed separately, so the ratio is arithmetic on disclosed numbers, not an
estimate.

Published numbers are company-reported or transparent arithmetic.  Market
expectations are labelled as such, with no broker attribution.
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
    headroom,
    headroom_exhibit,
    number_exhibits,
    threshold_exhibit,
    threshold_table,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "v.json"
DATA_DIR = ROOT / "data"

# One tick per year keeps the 55-quarter and 40-quarter axes readable.
LONG_STEP = 4

# The site's window starts 2016Q1. `revenue_lines_usd_m` runs from Q4 2012, so
# the charts that used to take a hand-picked tail of 13 take this instead --
# one number, derived from the target rather than typed next to each chart.
def window_from_2016(staging: dict) -> int:
    quarters = staging["revenue_lines_usd_m"]["quarters"]
    return len(quarters) - quarters.index("Q1 2016")


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


def plain_text(html: str) -> str:
    """Strip inline markup for the two slots the renderer escapes rather than parses.

    `assets/page.js` writes exhibit notes with `innerHTML` but runs section
    descriptions and the 口径与方法说明 list through `esc()`, so a `<b>` that
    reads as emphasis on a chart caption reaches the reader as the literal
    characters `<b>` in those two places. The same sentence is often wanted in
    both, so it is written once with markup and stripped here.
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


SOURCE_FILINGS = (
    "四条毛收入线（Service / Data processing / International transaction / Other）与"
    "Client incentives 抵减线均为各季 10-Q、10-K 收入分解附注里的<b>申报值</b>，"
    "本页的激励率 = 激励 ÷ 四条毛收入线之和，是申报值之间的除法，不含任何估计。"
)

NO_GUIDANCE_NOTE = (
    "<b>Visa 从不在申报文件里给<u>季度</u>数字指引。</b>"
    "它历史上给过的 Financial Outlook 一律是<b>财年</b>口径，从来没有过下一季度的区间，"
    "因此其他几页那种「本季指引 → 本季实际」的逐季兑现对象，在 Visa 这里根本不存在。"
    "财年口径的那部分也在退场，分四个阶段："
    "FY2016–FY2020 有 Financial Outlook，其中客户激励率与有效税率是数字区间、"
    "收入与 EPS 多为「mid-teens」这类文字区间；"
    "FY2020–FY2021 保留小节但明确不给指引；"
    "FY2022–FY2023 大部分季度连小节都没有；"
    "FY2024 只剩一句话，指向一份<b>未在 EDGAR 归档</b>的 earnings presentation；"
    "2025-01-30 之后的历次新闻稿连这句话也没有了。"
    "把无法与第二个来源核对的电话会内容抄成一份十几季的记录，正是本仓要避免的做法。"
)


# ── section one: the one number Visa ever guided ─────────────────────────────
def incentive_guidance_charts(staging: dict) -> tuple[list[dict], dict]:
    """Visa's only repeated filed forward number, against what it delivered.

    ``Client incentives as a percent of gross revenues`` appeared as a numeric
    range in the "Financial Outlook" block of the release that opened each
    fiscal year from 2013 through 2020, and nowhere since.  The floor is the
    quarterly series, not the guidance: gross revenue and the incentive line
    start at FY2013Q1, so FY2013 is the first year whose delivered rate can be
    computed on the same basis as the four the page used to show.  Both legs
    are filed:
    the guided range from the release, the delivered rate from that year's 10-K
    revenue note (four gross lines and the contra line, disclosed separately).
    """
    record = staging["incentive_guidance"]
    entries = record["entries"]
    labels = [f"FY{entry['fiscal_year']}" for entry in entries]
    low = [entry["lo"] for entry in entries]
    high = [entry["hi"] for entry in entries]
    actual = [entry["actual_pct"] for entry in entries]

    # The one year whose two legs sit on different bases, written from the
    # record rather than typed beside it -- if a second one is ever added this
    # sentence grows by itself instead of going quietly out of date.
    breaks = "".join(
        f"<b>FY{entry['fiscal_year']} 有一处口径断点。</b>"
        + entry["basis_break"]["what"]
        + f"剔除该季后的 {entry['basis_break']['clean_quarters']} 季比率为 "
        + f"{entry['basis_break']['clean_actual_pct']:.2f}%，全年为 "
        + f"{entry['actual_pct']:.2f}%，"
        + ("两者落在同一侧，所以这一年的判定不依赖那个断点。"
           if entry["basis_break"]["verdict_unchanged"]
           else "<b>两者的判定不同，这一年只能当作存疑</b>。")
        for entry in entries if "basis_break" in entry
    )

    below = [index for index, value in enumerate(actual) if value < low[index]]
    inside = [index for index, value in enumerate(actual)
              if low[index] <= value <= high[index]]
    above = [index for index, value in enumerate(actual) if value > high[index]]
    assert len(below) + len(inside) + len(above) == len(actual)

    band = delivery_band(
        "EX_INC_BAND", "客户激励率", labels, low, high, actual,
        fmt="pct1", ylab="激励 / 毛收入", unit="%", venue="业绩发布",
        timing="该财年<b>开始时</b>", period_word="年",
        src_extra=(
            "指引区间逐字取自各财年开局那份业绩 8-K 的「Financial Outlook」块中"
            "「Client incentives as a percent of gross revenues」一行；"
            "实际值取自该财年 10-K 收入附注里的四条毛收入线与激励线。"
        ),
        extra_note=(
            f"<b>方向要读反过来</b>：这条线低于区间是<b>好事</b> —— 返给客户的钱比承诺的少。"
            f"{len(entries)} 年里 {len(below)} 年跌破下限、{len(inside)} 年落在区间内、"
            f"{len(above)} 年高于上限。"
            "Visa 在自己愿意给数字的那些年里，从没有超发过激励。"
            "<b>这个结论把窗口从四年拉到八年之后仍然成立</b> —— "
            "新接进来的 FY2013–FY2016 里最大的一次是 FY2013 的 "
            f"{min(actual[index] - low[index] for index in below):+.2f}pp，方向仍然是少发。"
            + breaks
        ),
    )

    gap = [actual[index] - (low[index] + high[index]) / 2 for index in range(len(entries))]
    deviation = {
        "ref": "EX_INC_DEV",
        "kind": "grouped_bars",
        "title": (
            f"实际激励率相对指引中值的偏离："
            f"{len(entries)} 年里 {sum(1 for value in gap if value < 0)} 年为负，平均 "
            f"{sum(gap) / len(gap):+.2f}pp"
        ),
        "xlabels": labels,
        "groups": [{
            "name": "实际激励率 − 指引中值",
            "color": "BLUE",
            "values": rounded(gap),
        }],
        "bar_labels": True,
        "fmt": "pp1",
        "label_fmt": "pp1",
        "ylab": "pp vs 指引中值",
        "note": (
            "负值 = 激励率低于公司自己给的中值，即少返给客户、多留给自己。"
            f"最大的一次是 {labels[gap.index(min(gap))]} 的 {min(gap):+.2f}pp。"
            f"<b>本页此前只画 FY2017–FY2020 四年，并印着「四年全部为负」——"
            f"那句话当时就是错的</b>，FY2020 的偏离是 "
            f"{gap[[entry['fiscal_year'] for entry in entries].index(2020)]:+.2f}pp，"
            "为正。八年的窗口里为正的有两年。"
            "<b>然后这条指引就消失了。</b>"
            f"公司在 FY{record['stopped_after_fiscal_year']} 之后再没有给过这个数字，"
            "而同一个比率在其后六年里继续往上走 —— 见第四节的长序列。"
        ),
        "src_extra": "同上；单位是百分点，与收入类图的百分比不可直接比大小。",
    }
    return [band, deviation], record


# ── section four: the long filed record ──────────────────────────────────────
def incentive_rate_long(staging: dict) -> dict:
    lines = staging["revenue_lines_usd_m"]
    labels = [compact_period(period) for period in lines["quarters"]]
    rate = lines["incentive_rate_pct"]
    low_at = labels[rate.index(min(rate))]
    high_at = labels[rate.index(max(rate))]
    return {
        "ref": "EX_INC_LONG",
        "kind": "gs_line",
        "title": (
            f"客户激励率 {len(rate)} 个季度从 {rate[0]:.1f}% 升到 {rate[-1]:.1f}%："
            f"每一美元毛收入返给客户的钱多了 {rate[-1] - rate[0]:.1f} 美分"
        ),
        "xlabels": labels,
        "xstep": LONG_STEP,
        "values": rounded(rate),
        "legend": "Client incentives / 毛收入",
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "占毛收入比",
        "note": (
            f"区间 {min(rate):.1f}%（{low_at}）到 {max(rate):.1f}%（{high_at}）。"
            "这是本页最重要的一条线，也是八个季度的窗口<b>看不出来</b>的那种线："
            "近八季它在 27%–29% 之间小幅摆动，像噪声；"
            f"拉到 {len(rate)} 季才看得出这是一条走了十三年的单向斜坡。"
            "它衡量的是网络生意的定价权 —— 分子是为留住发卡行与收单方付出的对价，"
            "分母是在没有这些对价之前 Visa 本可以收到的钱。"
            "<b>比率上行不等于绝对额失控</b>：同期毛收入本身涨了近四倍，"
            "激励是跟着规模一起长的，这条线说的是<b>每一美元</b>里被让渡的份额在变大。"
            + SOURCE_FILINGS
        ),
        "src_extra": "各季 10-Q / 10-K 收入分解附注。",
    }


def revenue_mix_long(staging: dict) -> dict:
    lines = staging["revenue_lines_usd_m"]
    labels = [compact_period(period) for period in lines["quarters"]]
    gross = lines["gross_revenue"]
    shares = {
        name: [value / total * 100 for value, total in zip(lines[key], gross)]
        for name, key in (
            ("Service", "service"),
            ("Data processing", "data_processing"),
            ("International transaction", "international_transaction"),
            ("Other", "other"),
        )
    }
    dp = shares["Data processing"]
    intl = shares["International transaction"]
    return {
        "ref": "EX_MIX_LONG",
        "kind": "lines",
        "title": (
            f"四条毛收入线各自占毛收入的比重：Data processing 从 {dp[0]:.1f}% 升到 {dp[-1]:.1f}%，"
            f"Service 从 {shares['Service'][0]:.1f}% 降到 {shares['Service'][-1]:.1f}%；"
            f"International transaction 在 2020 年一度掉到 {min(intl):.1f}%"
        ),
        "xlabels": labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": "Service", "values": rounded(shares["Service"]), "color": "NAVY"},
            {"name": "Data processing", "values": rounded(shares["Data processing"]),
             "color": "BLUE"},
            {"name": "International transaction",
             "values": rounded(shares["International transaction"]), "color": "GOLD"},
            {"name": "Other", "values": rounded(shares["Other"]), "color": "GREEN"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "占毛收入比",
        "note": (
            "分母是四条线之和（毛收入），不是净收入，所以四条线加起来恒等于 100%，"
            "激励率的变化不会串到这张图里 —— 两张图各管一件事。"
            "<b>2020 年那道深谷是疫情</b>：International transaction 依赖跨境交易，"
            f"当季占比从疫情前的约 {intl[len(intl) - 26]:.0f}% 掉到 {min(intl[-26:]):.1f}%，"
            "至今没有回到 2019 年的水平。"
            "Data processing 则一路向上 —— 它按处理笔数计费，"
            "是四条线里与「交易笔数」最直接挂钩的一条。"
        ),
        "src_extra": "各季 10-Q / 10-K 收入分解附注。",
    }


def geography_long(staging: dict) -> dict:
    geo = staging["geography_usd_m"]
    labels = [compact_period(period) for period in geo["quarters"]]
    us_share = [value / total * 100
                for value, total in zip(geo["us"], geo["net_revenue"])]
    return {
        "ref": "EX_GEO",
        "kind": "gs_line",
        "title": (
            f"美国以外贡献净收入的 {100 - us_share[-1]:.1f}%，"
            f"{len(labels)} 季里从 {100 - us_share[0]:.1f}% 起步"
        ),
        "xlabels": labels,
        "xstep": LONG_STEP,
        "values": rounded([100 - value for value in us_share]),
        "legend": "International 占净收入比",
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "ylab": "占净收入比",
        "note": (
            "公司在收入附注里把净收入拆成 U.S. 与 International 两行申报，"
            "两行相加恒等于申报净收入，本页逐季核对过。"
            "这条线只有 ASC 606 之后才有 —— 更早的申报文件不披露这个拆分，"
            "所以窗口从 2018 年底开始，不往前补。"
            "<b>它比区域增速更耐读</b>：占比是两条申报值的比，不受汇率换算口径影响，"
            "而公司从不单独披露分地区的恒定汇率增速。"
        ),
        "src_extra": "各季 10-Q / 10-K 收入分解附注的 U.S. / International 两行。",
    }


def margin_long(staging: dict) -> dict:
    lines = staging["revenue_lines_usd_m"]
    labels = [compact_period(period) for period in lines["quarters"]]
    return {
        "ref": "EX_MARGIN",
        "kind": "lines",
        "title": "净收入与毛收入的两条增速：中间的缺口就是激励率在动",
        "xlabels": labels[4:],
        "xstep": LONG_STEP,
        "series": [
            {"name": "毛收入 YoY", "values": rounded(
                [pct_change(lines["gross_revenue"][i], lines["gross_revenue"][i - 4])
                 for i in range(4, len(labels))]), "color": "GOLD"},
            {"name": "净收入 YoY", "values": rounded(
                [pct_change(lines["net_revenue"][i], lines["net_revenue"][i - 4])
                 for i in range(4, len(labels))]), "color": "NAVY"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "同比增速",
        "note": (
            "<b>这两条线之间的距离，就是上一张图那条斜坡的一阶导数。</b>"
            "毛收入增速高于净收入增速的季度，激励率在上升；反过来则在下降。"
            "把它画成两条增速而不是一条差值，是因为差值会把"
            "「毛收入加速、激励同步加速」和「毛收入减速、激励不减速」画成同一个数，"
            "而这两件事对生意的含义完全不同。"
            "两条线都用申报值计算，同比分母取四个季度之前的同一条线。"
        ),
        "src_extra": "各季 10-Q / 10-K 收入分解附注。",
    }


def capital_return_long(staging: dict) -> dict:
    capital = staging["capital_allocation_usd_m"]
    labels = [compact_period(period) for period in capital["quarters"]]
    ocf = capital["operating_cash_flow"]
    capex = capital["capex"]
    buyback = capital["buyback"]
    dividends = capital["dividends"]
    fcf = [None if o is None or c is None else o + c for o, c in zip(ocf, capex)]
    ret = [None if b is None or d is None else -(b + d) for b, d in zip(buyback, dividends)]
    ratio = [None if f is None or r is None or f <= 0 else r / f * 100
             for f, r in zip(fcf, ret)]
    over = sum(1 for value in ratio if value is not None and value > 100)
    return {
        "ref": "EX_RETURN",
        "kind": "lines",
        "title": (
            f"股东回报与自由现金流：{len(labels)} 季里有 {over} 季回报超过当季自由现金流"
        ),
        "xlabels": labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": "自由现金流 D（经营现金流 − 资本开支）",
             "values": rounded([None if v is None else v / 1000 for v in fcf]), "color": "NAVY"},
            {"name": "回购 + 分红", "values": rounded(
                [None if v is None else v / 1000 for v in ret]), "color": "RED"},
        ],
        "fmt": "usd1",
        "yfmt": "usd1",
        "label_fmt": "usd1",
        "end_label": True,
        "ylab": "US$B",
        "note": (
            "现金流量表在 10-Q 里只有年初至今栏，因此除会计第一季外，"
            "每个季度的四条现金流都是相邻两次申报值之差 —— 两端都是申报值，中间没有估计。"
            "<b>单季穿越并不稀奇</b>，回购按授权节奏走、现金流按季节走，"
            "值得看的是连续几季都在上面的那些窗口。"
            "自由现金流在这里是「经营现金流 − 购置不动产设备与技术」，"
            "是本页自算口径（D）；公司自己不发布自由现金流数字。"
        ),
        "src_extra": "各季 10-Q / 10-K 合并现金流量表。",
    }


# ── section two: this quarter ────────────────────────────────────────────────
def escrow_exhibit(staging: dict) -> dict:
    """The escrow against the accrual it actually funds, not the one it does not.

    This is the page's one flat contradiction of the local note, and it is a
    disclosure question rather than a judgement call: Visa prints the covered
    and non-covered accruals separately, in a table whose title says so.
    """
    litigation = staging["litigation"]
    labels = [compact_period(period) for period in litigation["quarters"]]
    escrow = litigation["escrow_usd_m"]
    covered = litigation["us_covered_litigation_usd_m"]
    total = litigation["accrued_litigation_total_usd_m"]
    surplus = [None if e is None or c is None else e - c for e, c in zip(escrow, covered)]
    short_vs_total = escrow[-1] - total[-1]
    negative = sum(1 for value in surplus if value is not None and value < 0)
    return {
        "ref": "EX_ESCROW",
        "kind": "lines",
        "title": (
            f"托管账户对它真正负责的那笔负债：本季 US${escrow[-1]:,.0f}M vs "
            f"US${covered[-1]:,.0f}M，盈余 US${surplus[-1]:,.0f}M"
        ),
        "xlabels": labels,
        "xstep": LONG_STEP,
        "series": [
            {"name": "美国诉讼托管账户（受限现金）", "values": rounded(escrow), "color": "NAVY"},
            {"name": "U.S. covered litigation 计提", "values": rounded(covered), "color": "RED"},
            {"name": "计提的诉讼负债合计（含不受托管账户覆盖的部分）",
             "values": rounded(total), "color": "GOLD"},
        ],
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "end_label": True,
        "ylab": "US$M",
        "note": (
            "<b>这张图上有三条线，而只有前两条该放在一起比。</b>"
            "美国追溯责任计划（RRP）下的托管账户只为一件事存在："
            "偿付 <b>U.S. covered litigation</b>。"
            "资产负债表上的「Accrued litigation」是更大的一个数，"
            "它还装着 VE Territory covered 与完全不在覆盖范围内的诉讼 —— "
            "那些钱托管账户既不负责、也不能用来付。"
            "10-Q 自己把这个拆分印在一张标题就叫"
            "「Schedule of Accrued Litigation for Both Covered and Non-Covered Litigation」的表里，"
            "所以覆盖口径是<b>申报值</b>，不需要任何推算。"
            f"<b>读数：</b>本季托管账户 US${escrow[-1]:,.0f}M、"
            f"U.S. covered 计提 US${covered[-1]:,.0f}M，账户是<b>盈余</b> US${surplus[-1]:,.0f}M；"
            f"{len(labels)} 季里只有 {negative} 季出现过缺口。"
            f"若改用合计口径去比，会得到 US${short_vs_total:,.0f}M 的「缺口」并据此预判一次大额补存 —— "
            "那是拿托管账户去对一笔它不负责的负债。"
        ),
        "src_extra": (
            "托管账户余额取自各季资产负债表的受限现金行与现金附注；"
            "两个计提口径取自法律事项附注的 covered / non-covered 计提表。"
        ),
    }


def quarter_revenue_lines(staging: dict) -> dict:
    lines = staging["revenue_lines_usd_m"]
    window = window_from_2016(staging)
    labels = [compact_period(period) for period in lines["quarters"][-window:]]
    def yoy(key):
        values = lines[key]
        start = len(values) - window
        return [pct_change(values[i], values[i - 4]) for i in range(start, len(values))]
    service, dp = yoy("service"), yoy("data_processing")
    intl, other = yoy("international_transaction"), yoy("other")
    return {
        "ref": "EX_LINES_YOY",
        "kind": "lines",
        "title": (
            f"四条毛收入线的同比增速本季分道扬镳："
            f"Other {other[-1]:+.0f}%、Data processing {dp[-1]:+.0f}%、"
            f"Service {service[-1]:+.0f}%、International transaction {intl[-1]:+.0f}%"
        ),
        "xlabels": labels,
        "xrot": 90,
        "xstep": LONG_STEP,
        "series": [
            {"name": "Service", "values": rounded(service), "color": "NAVY"},
            {"name": "Data processing", "values": rounded(dp), "color": "BLUE"},
            {"name": "International transaction", "values": rounded(intl), "color": "GOLD"},
            {"name": "Other", "values": rounded(other), "color": "GREEN"},
        ],
        "fmt": "pct1",
        "yfmt": "pct1",
        "label_fmt": "pct1",
        "end_label": True,
        "ylab": "同比增速",
        "note": (
            "<b>这四条线不能按同一个时点去读，公司自己在每份新闻稿里都写明了这一点。</b>"
            "Service revenue 按<b>上一个季度</b>的支付额确认，其余三条按<b>当季</b>活动确认。"
            "因此把 Service 的增速对着当季支付额增速看，会整整错开一个季度；"
            "而新闻稿开头那张「Key Business Drivers」表印的恰恰是<b>当季</b>的支付额。"
            "本页因此不发布任何「收入增速 vs 支付额增速」的对照图 —— "
            "口径能对齐的那一半在申报文件里，另一半（分季支付额的绝对金额）不在，"
            "详见「口径与方法说明」里的不接入清单。"
            f"International transaction 本季 {intl[-1]:+.1f}%，是四条线里唯一进入个位数的一条。"
            f"<b>十年的窗口里这四条同时为负过一次</b>："
            f"2020 年的疫情季，最低一格是 {min(min(service), min(dp), min(intl), min(other)):+.0f}%。"
            "除那一段之外，四条线的排序换过多次 —— 今天 Other 在最上面，"
            "而 2016 到 2019 年它长期在最下面。"
        ),
        "src_extra": "各季 10-Q / 10-K 收入分解附注；确认时点的表述见各季业绩 8-K 的 EX-99.1。",
    }


def incentive_quarter(staging: dict) -> dict:
    lines = staging["revenue_lines_usd_m"]
    window = window_from_2016(staging)
    labels = [compact_period(period) for period in lines["quarters"][-window:]]
    rate = lines["incentive_rate_pct"][-window:]
    full = lines["incentive_rate_pct"]
    yoy_gap = rate[-1] - full[-5]
    qoq_gap = rate[-1] - full[-2]
    return {
        "ref": "EX_INC_Q",
        "kind": "gs_line",
        "title": (
            f"激励率本季 {rate[-1]:.2f}%，同比 {yoy_gap:+.2f}pp、环比 {qoq_gap:+.2f}pp"
        ),
        "xlabels": labels,
        "xrot": 90,
        "xstep": LONG_STEP,
        "values": rounded(rate),
        "legend": "Client incentives / 毛收入",
        "fmt": "pct2",
        "yfmt": "pct2",
        "label_fmt": "pct2",
        "ylab": "占毛收入比",
        "note": (
            "<b>把这张图和第四节那条十三年的斜坡一起读。</b>"
            "近十三季这条线在 27%–29% 之间来回，单看像季节性噪声；"
            "它同时也是那条长坡的最后十三个点。"
            f"本季 {rate[-1]:.2f}% 是窗口内最高。"
            "反事实很好算，也全部是申报值："
            f"若激励率维持去年同期的 {full[-5]:.2f}%，"
            f"本季净收入会是 US${lines['gross_revenue'][-1] * (1 - full[-5] / 100):,.0f}M，"
            f"而不是申报的 US${lines['net_revenue'][-1]:,.0f}M —— "
            f"激励率这 {yoy_gap:+.2f}pp 单独吃掉了约 "
            f"US${lines['gross_revenue'][-1] * (rate[-1] - full[-5]) / 100:,.0f}M 的净收入。"
        ),
        "src_extra": "各季 10-Q 收入分解附注。",
    }


def gaap_wedge(staging: dict) -> dict:
    financials = staging["financials"]
    opex = financials["total_opex_usd_m"][-1]
    litigation = financials["litigation_provision_usd_m"][-1] or 0.0
    severance = staging["quarter_one_offs"]["severance_usd_m"]
    underlying = opex - litigation - severance
    prior = financials["total_opex_usd_m"][-5]
    return {
        "ref": "EX_WEDGE",
        "kind": "bars_labeled",
        "title": (
            f"本季 GAAP 营业费用 US${opex:,.0f}M 同比 "
            f"{signed(pct_change(opex, prior))}，剔除两笔一次性后为 "
            f"{signed(pct_change(underlying, prior - (financials['litigation_provision_usd_m'][-5] or 0)))}"
        ),
        "xlabels": [
            "GAAP 营业费用",
            "其中：诉讼计提",
            "其中：遣散费",
            "剔除两项后 D",
        ],
        "values": [opex, litigation, severance, underlying],
        "legend": "US$M",
        "fmt": "f0c",
        "yfmt": "f0c",
        "label_fmt": "f0c",
        "ylab": "US$M",
        "note": (
            f"诉讼计提 US${litigation:,.0f}M 是损益表上的<b>申报行</b>；"
            f"遣散费 US${severance:,.0f}M 由公司在业绩新闻稿里单列为特殊项。"
            "两笔都不是本季经营节奏的一部分，但它们进了同一个 GAAP 数字，"
            "所以直接拿 GAAP 营业费用同比去判断费用控制会读错方向。"
            "<b>本页不发布公司口径的 non-GAAP 营业费用增速</b>："
            "那条数据存在于业绩新闻稿的非 GAAP 对账表里，但公司对下一季的费用指引只给"
            "「low double digits」这样的定性区间，没有可对照的数字区间，"
            "把一个定性词翻译成百分数再画成兑现图，就是本页拒绝做的那件事。"
        ),
        "src_extra": (
            "营业费用与诉讼计提取自 10-Q 合并损益表；"
            "遣散费金额取自该季业绩 8-K 的 EX-99.1 特殊项说明。"
        ),
    }


def build_payload(staging: dict) -> dict:
    financials = staging["financials"]
    periods = staging["periods"]
    labels = [compact_period(period) for period in periods]
    lines = staging["revenue_lines_usd_m"]
    net_revenue = financials["net_revenue_usd_m"]
    gross = financials["gross_revenue_usd_m"]
    rate = financials["incentive_rate_pct"]
    operating_income = financials["operating_income_usd_m"]
    margin = [income / revenue * 100
              for income, revenue in zip(operating_income, net_revenue)]
    full_rate = lines["incentive_rate_pct"]

    # The 2016-onward window. `revenue_lines_usd_m` carries net revenue back to
    # Q4 2012 and `income_long_usd_m` carries operating income back to Q4 2015,
    # so both of the charts below run the whole window off series that were
    # already reconciled against the eight quarters the page used to show.
    long_from = lines["quarters"].index("Q1 2016")
    long_labels = [compact_period(q) for q in lines["quarters"][long_from:]]
    long_net_revenue = lines["net_revenue"][long_from:]
    long_gross = lines["gross_revenue"][long_from:]
    income_long = staging["income_long_usd_m"]
    inc_from = income_long["quarters"].index("Q1 2016")
    long_operating_income = income_long["operating_income_usd_m"][inc_from:]
    assert income_long["quarters"][inc_from:] == lines["quarters"][long_from:]
    long_margin = [income / revenue * 100 for income, revenue
                   in zip(long_operating_income, long_net_revenue)]

    # ── section one ─────────────────────────────────────────────────────────
    guidance_ex, guidance_record = incentive_guidance_charts(staging)
    closure = staging["followup_closure"]
    verdicts = staging["tracked_metric_verdicts"]

    settled_ex = [
        {
            "kind": "bars_labeled",
            "title": (
                f"上一份笔记留下的 {sum(closure['counts'])} 条待验问题："
                f"{closure['counts'][0]} 条已验证、"
                f"{closure['counts'][closure['labels'].index('仍未披露')]} 条公司仍未披露"
            ),
            "xlabels": closure["labels"],
            "values": closure["counts"],
            "legend": "条",
            "fmt": "f0",
            "yfmt": "f0",
            "label_fmt": "f0",
            "ylab": "条数",
            "note": closure["note"],
            "src_extra": "本站上一份 Visa 季度笔记的待验清单，逐条对本季与上一季的申报文件核销。",
        },
        {
            "kind": "bars_labeled",
            "title": (
                f"{sum(verdicts['counts'])} 条跟踪指标的结清方式："
                f"{verdicts['counts'][verdicts['labels'].index('退役：公司停披')]} 条因公司停止披露而退役"
            ),
            "xlabels": verdicts["labels"],
            "values": verdicts["counts"],
            "legend": "条",
            "fmt": "f0",
            "yfmt": "f0",
            "label_fmt": "f0",
            "ylab": "条数",
            "note": verdicts["note"],
            "src_extra": "同上。",
        },
    ] + guidance_ex

    # ── section two ─────────────────────────────────────────────────────────
    highlight_ex = [
        {
            "kind": "gs_bar",
            "title": (
                f"净收入 US${net_revenue[-1]:,.0f}M、同比 "
                f"{signed(pct_change(net_revenue[-1], net_revenue[-5]))}；"
                f"毛收入同比 {signed(pct_change(gross[-1], gross[-5]))}"
            ),
            "xlabels": long_labels,
            "xstep": LONG_STEP,
            "values": rounded(long_net_revenue),
            "legend": "净收入",
            "fmt": "f0c",
            "yfmt": "f0c",
            "label_fmt": "f0c",
            "ylab": "US$M",
            "ylab2": "同比增速",
            "yoy": {
                "name": "净收入 YoY (RHS)",
                "values": rounded([None if index < 4 else
                                   pct_change(long_net_revenue[index],
                                              long_net_revenue[index - 4])
                                   for index in range(len(long_net_revenue))]),
                "color": "GREEN",
                "yfmt": "pct1",
            },
            "note": (
                "净收入是四条毛收入线减去客户激励之后的数，公司损益表上的第一行。"
                f"本季毛收入同比 {signed(pct_change(gross[-1], gross[-5]))}、"
                f"净收入同比 {signed(pct_change(net_revenue[-1], net_revenue[-5]))} —— "
                "两者相差的那一截就是激励率上行，下一张图专门讲它。"
                "<b>四十二个季度里只有一段负增长</b>："
                "2020 财年的四个季度，最深一格是 2020 年 6 月止季的 −17.3%；"
                "在那之前和之后，净收入同比没有一个季度落到零以下。"
            ),
            "src_extra": "各季 10-Q 合并损益表。",
        },
        incentive_quarter(staging),
        quarter_revenue_lines(staging),
        {
            "kind": "lines",
            "title": (
                f"GAAP 营业利润率 {margin[-1]:.1f}%，同比 {margin[-1] - margin[-5]:+.1f}pp；"
                f"四十二季里的最低一格是 {min(long_margin):.1f}%"
            ),
            "xlabels": long_labels,
            "xstep": LONG_STEP,
            "series": [
                {"name": "GAAP 营业利润率", "values": rounded(long_margin), "color": "NAVY"},
            ],
            "fmt": "pct1",
            "yfmt": "pct1",
            "label_fmt": "pct1",
            "end_label": True,
            "ylab": "营业利润率",
            "note": (
                "<b>本页只发布 GAAP 营业利润率。</b>"
                "公司口径的 non-GAAP 利润率需要剔除诉讼计提、遣散费、并购摊销等特殊项，"
                "而每一季剔除哪几项由公司当季决定，"
                "把一条 non-GAAP 利润率连起来会把口径变化画成经营变化。"
                "<b>而 GAAP 口径本身也不是一条平线</b>：2016 年 6 月止季只有 "
                f"{min(long_margin):.1f}%，那一季计提了收购 Visa Europe 相关的诉讼准备，"
                "把营业利润压到了净收入的十分之一出头；"
                "另一处凹陷在 2020 年，那次是收入端而不是费用端。"
                f"本季 GAAP 口径被两笔一次性压低（见 Exhibit {{EX_WEDGE}}），"
                "读同比时要连着那张图一起看。"
            ),
            "src_extra": "各季 10-Q 合并损益表。",
        },
        gaap_wedge(staging),
        escrow_exhibit(staging),
    ]

    # ── section three ───────────────────────────────────────────────────────
    next_kpi = staging["next_kpi"]
    quantified = next_kpi["quantified"]
    next_ex = [
        headroom_exhibit(
            f"下季 {len(quantified)} 条阈值与当前值的距离（正数 = 仍在安全侧）",
            quantified, "current",
            note=(
                "所有阈值都是<b>本站的研究设定</b>，不是公司指引，也不是评级。"
                "把百分比、百分点与美元金额归一到「距阈值余量」这一个口径，"
                "是为了让一张图能同时回答「哪几条已经越线」。"
                + next_kpi["excluded"]
            ),
            src_extra="当前值全部来自本季 10-Q 与业绩 8-K 的申报值。",
        ),
        threshold_exhibit(
            "激励率：越低越安全",
            long_labels,
            rounded(full_rate[long_from:]),
            quantified[0]["threshold"],
            fmt="pct2", ylab="占毛收入比", xstep=LONG_STEP,
            actual_name="实际激励率", threshold_name="阈值 29.50%",
            note=(
                "上一张图说哪条线越了，这张说它是怎么走到那里的。"
                f"本季 {full_rate[-1]:.2f}%，距 {quantified[0]['threshold']:.2f}% 的阈值还有 "
                f"{quantified[0]['threshold'] - full_rate[-1]:.2f}pp。"
                "阈值取的是本季再向上一个季度级别的台阶，不是长期趋势的外推。"
                f"<b>四十二个季度里这条线一路向上</b>：2016 年初还在 "
                f"{full_rate[long_from]:.2f}%，十年抬高了约 "
                f"{full_rate[-1] - full_rate[long_from]:.0f} 个百分点，"
                "所以阈值只对最近这一段有意义，把它画到全窗口上会让前半段全部「安全」。"
            ),
            src_extra="各季 10-Q 收入分解附注。",
        ),
        threshold_exhibit(
            "International transaction 收入同比：越高越安全",
            long_labels,
            rounded([pct_change(lines["international_transaction"][index],
                                lines["international_transaction"][index - 4])
                     for index in range(long_from, len(lines["quarters"]))]),
            quantified[1]["threshold"],
            fmt="pct1", ylab="同比增速", xstep=LONG_STEP,
            actual_name="International transaction YoY", threshold_name="阈值 +4.0%",
            note=(
                "这是四条毛收入线里本季唯一掉进个位数的一条。"
                "阈值设在 +4%：跌破它意味着这条线的减速不再能用去年同期的高基数解释。"
                "<b>本页不把它对着跨境交易额增速去读</b> —— "
                "分季跨境交易额的绝对金额不在申报文件里，见不接入清单。"
                "<b>拉到四十二季之后，跌破 +4% 不再是罕见事</b>："
                "2020 财年那四个季度整条线深度为负，2016—2017 年也有数个季度在阈值之下。"
                "阈值守的是「在没有疫情这类外因时它是否还能维持两位数」，不是「历史上从未破过」。"
            ),
            src_extra="各季 10-Q 收入分解附注。",
        ),
        threshold_exhibit(
            "托管账户相对 U.S. covered 计提的盈余：越高越安全",
            [compact_period(period) for period in staging["litigation"]["quarters"]],
            rounded([
                None if e is None or c is None else e - c
                for e, c in zip(staging["litigation"]["escrow_usd_m"],
                                staging["litigation"]["us_covered_litigation_usd_m"])
            ]),
            quantified[2]["threshold"],
            fmt="f0c", ylab="US$M", xstep=LONG_STEP,
            actual_name="托管账户 − U.S. covered 计提 D", threshold_name="阈值 −US$500M",
            note=(
                "分子分母都是申报值，差值是本页自算（D）。"
                "阈值是负数：账户可以短暂低于计提额（公司按季补存），"
                "真正需要关注的是缺口大到必须一次性大额补存的时候。"
                f"本季为盈余 US${staging['litigation']['escrow_usd_m'][-1] - staging['litigation']['us_covered_litigation_usd_m'][-1]:,.0f}M。"
            ),
            src_extra="各季 10-Q 资产负债表、现金附注与法律事项附注。",
        ),
    ]

    # ── section four ────────────────────────────────────────────────────────
    routine_ex = [
        incentive_rate_long(staging),
        margin_long(staging),
        revenue_mix_long(staging),
        geography_long(staging),
        capital_return_long(staging),
    ]

    exhibits = number_exhibits(settled_ex + highlight_ex + next_ex + routine_ex, start=2)
    resolve_exhibit_refs(exhibits)
    first_table = exhibits[-1]["n"] + 1

    # ── audit tables ────────────────────────────────────────────────────────
    guide_rows = [
        [f"FY{entry['fiscal_year']}",
         f"{entry['lo']:.1f}%–{entry['hi']:.1f}%",
         f"{entry['actual_pct']:.2f}%",
         "跌破下限（少返给客户）" if entry["actual_pct"] < entry["lo"] else "区间内",
         f"{entry['actual_pct'] - (entry['lo'] + entry['hi']) / 2:+.2f}pp",
         f"毛收入 ${entry['gross_revenue_usd_m']:,.0f}M · 激励 ${-entry['client_incentives_usd_m']:,.0f}M",
         entry["released"]]
        for entry in guidance_record["entries"]
    ]

    quarterly_rows = [
        [periods[index], staging["fiscal_labels"][index],
         f"${gross[index]:,.0f}M",
         f"${-financials['client_incentives_usd_m'][index]:,.0f}M",
         f"{rate[index]:.2f}%",
         f"${net_revenue[index]:,.0f}M",
         f"{pct_change(net_revenue[index], net_revenue[index - 4]):+.1f}%" if index >= 4 else "—",
         f"${financials['total_opex_usd_m'][index]:,.0f}M",
         f"${operating_income[index]:,.0f}M",
         f"{margin[index]:.2f}%"]
        for index in range(len(periods))
    ]

    line_rows = [
        [lines["quarters"][index], lines["fiscal_labels"][index],
         f"${lines['service'][index]:,.0f}M",
         f"${lines['data_processing'][index]:,.0f}M",
         f"${lines['international_transaction'][index]:,.0f}M",
         f"${lines['other'][index]:,.0f}M",
         f"${lines['gross_revenue'][index]:,.0f}M",
         f"${-lines['client_incentives'][index]:,.0f}M",
         f"{lines['incentive_rate_pct'][index]:.2f}%",
         f"${lines['net_revenue'][index]:,.0f}M",
         "10-K 全年减九个月 D" if lines["basis"][index] == "fy_minus_9m" else "10-Q 申报三个月栏"]
        for index in range(len(lines["quarters"]) - 21, len(lines["quarters"]))
    ]

    litigation = staging["litigation"]
    litigation_rows = [
        [litigation["quarters"][index],
         f"${litigation['escrow_usd_m'][index]:,.0f}M",
         f"${litigation['us_covered_litigation_usd_m'][index]:,.0f}M"
         if litigation["us_covered_litigation_usd_m"][index] is not None else "—",
         f"${litigation['escrow_usd_m'][index] - litigation['us_covered_litigation_usd_m'][index]:,.0f}M D"
         if litigation["us_covered_litigation_usd_m"][index] is not None else "—",
         f"${litigation['accrued_litigation_total_usd_m'][index]:,.0f}M"
         if litigation["accrued_litigation_total_usd_m"][index] is not None else "—"]
        for index in range(len(litigation["quarters"]) - 13, len(litigation["quarters"]))
    ]

    capital = staging["capital_allocation_usd_m"]
    capital_rows = [
        [capital["quarters"][index],
         f"${capital['operating_cash_flow'][index]:,.0f}M"
         if capital["operating_cash_flow"][index] is not None else "—",
         f"${-capital['capex'][index]:,.0f}M" if capital["capex"][index] is not None else "—",
         f"${-capital['buyback'][index]:,.0f}M" if capital["buyback"][index] is not None else "—",
         f"${-capital['dividends'][index]:,.0f}M" if capital["dividends"][index] is not None else "—",
         "10-Q 三个月栏" if capital["basis"][index] == "filed_3m" else "相邻两次年初至今之差 D"]
        for index in range(len(capital["quarters"]) - 13, len(capital["quarters"]))
    ]

    tables = [
        {
            "n": first_table,
            "title": "Visa 唯一一份申报文件里的数字指引记录：客户激励率，FY2017–FY2020",
            "headers": ["财年", "指引区间", "实际", "兑现", "相对中值", "构成", "指引发布日"],
            "rows": guide_rows,
        },
        threshold_table(first_table + 1, "下季阈值与当前值（原单位）",
                        quantified, "current", "当前值"),
        {
            "n": first_table + 2,
            "title": "八季度毛收入、激励与利润率",
            "headers": ["期间", "公司口径", "毛收入", "客户激励", "激励率 D", "净收入",
                        "净收入 YoY", "营业费用", "营业利润", "营业利润率 D"],
            "rows": quarterly_rows,
        },
        {
            "n": first_table + 3,
            "title": "近二十一季四条毛收入线与激励（每季注明是申报三个月栏还是差分）",
            "headers": ["期间", "公司口径", "Service", "Data processing",
                        "International transaction", "Other", "毛收入 D", "客户激励",
                        "激励率 D", "净收入", "取数方式"],
            "rows": line_rows,
        },
        {
            "n": first_table + 4,
            "title": "近十三季诉讼托管账户与两个计提口径",
            "headers": ["期间", "托管账户", "U.S. covered 计提",
                        "盈余 / 缺口 D", "计提合计（含未覆盖）"],
            "rows": litigation_rows,
        },
        {
            "n": first_table + 5,
            "title": "近十三季现金流与股东回报",
            "headers": ["期间", "经营现金流", "资本开支", "回购", "分红", "取数方式"],
            "rows": capital_rows,
        },
        ai_capex_cycle_table(first_table + 6),
    ]

    latest_rate = full_rate[-1]
    return {
        "schema_version": "quarterly-dashboard/v-v1",
        "page": {"slug": "v", "language": "zh-CN"},
        "company": {
            "ticker": "V",
            "name": "Visa",
            "group": "payment_networks",
            "accounting_standard": "US GAAP",
        },
        "latest": {
            "disclosed_period_label": "Q2 2026",
            "full_financial_period_label": "Q2 2026",
            "period_end": "2026-06-30",
            "release_date": "2026-07-28",
            "analysis_date": "2026-07-29",
            "audit_status": "unaudited",
            "status": "history_ready",
        },
        "tracker": "Watchlist Quarterly Tracker · V",
        "title": "Visa (V)：Q2 2026 季报仪表盘",
        "subtitle": (
            "截至 2026-06-30 · 发布 2026-07-28 · US GAAP · 未审计 · "
            "9 月制财年，本站按自然年季度标注：本页 Q2 2026 即公司所称 FY2026 Q3"
        ),
        "headline": (
            f"净收入 US${net_revenue[-1]:,.0f}M、同比 "
            f"{signed(pct_change(net_revenue[-1], net_revenue[-5]))}，"
            f"毛收入同比 {signed(pct_change(gross[-1], gross[-5]))} 更快 —— "
            f"差的那一截是客户激励率升到 {latest_rate:.2f}%，"
            f"同比 {latest_rate - full_rate[-5]:+.2f}pp。"
            f"这个比率在本页的 {len(full_rate)} 个季度里从 {full_rate[0]:.1f}% 一路走到今天，"
            "而它恰好是 Visa 唯一一个在申报文件里给过数字区间的前瞻指标 —— "
            f"给到 FY{guidance_record['stopped_after_fiscal_year']} 为止，此后再没给过。"
        ),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>记录</span><b>唯一的数字指引，停在六年前</b>'
            f'<p>FY2017–FY2020 公司在申报文件里给过四次激励率区间，'
            f'三次实际低于下限（少返给客户）。此后停止披露，'
            f'比率从 23.4% 走到 {latest_rate:.2f}%。</p></article>'
            '<article><span>本季</span><b>毛收入比净收入快</b>'
            f'<p>毛收入同比 {signed(pct_change(gross[-1], gross[-5]))}、'
            f'净收入 {signed(pct_change(net_revenue[-1], net_revenue[-5]))}；'
            f'激励率同比 {latest_rate - full_rate[-5]:+.2f}pp，'
            f'单独吃掉约 US${gross[-1] * (latest_rate - full_rate[-5]) / 100:,.0f}M 净收入。</p></article>'
            '<article><span>更正</span><b>托管账户没有欠资</b>'
            f'<p>US${litigation["escrow_usd_m"][-1]:,.0f}M 对应的是 U.S. covered 计提 '
            f'US${litigation["us_covered_litigation_usd_m"][-1]:,.0f}M，'
            f'盈余 US${litigation["escrow_usd_m"][-1] - litigation["us_covered_litigation_usd_m"][-1]:,.0f}M；'
            '拿它去比计提合计才会看出「缺口」。</p></article>'
            '</div>'
        ),
        "source": (
            'Source: <a href="https://www.sec.gov/Archives/edgar/data/1403161/'
            '000140316126000103/q32026earningsrelease.htm" rel="noopener">Visa FY2026 Q3 '
            '业绩新闻稿（8-K EX-99.1）</a>与截至 2026-06-30 的 10-Q。'
        ),
        "source_url": (
            "https://www.sec.gov/Archives/edgar/data/1403161/"
            "000140316126000103/q32026earningsrelease.htm"
        ),
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {
                "id": "settled",
                "title": "一、上季兑现了吗",
                "description": plain_text(
                    "先结清上一份笔记留下的问题，再看新数字。"
                    "这一节和本站其他几页不一样。"
                    + NO_GUIDANCE_NOTE
                    + "能结算的只剩一件事，但它恰好是本页最要紧的那件 —— "
                    "公司曾经连续四年在申报文件里给出<b>客户激励率</b>的数字区间，"
                    "而那正是本页从头讲到尾的那个比率。"
                ),
                "exhibits": settled_ex,
            },
            {
                "id": "quarter_highlights",
                "title": "二、本季重点",
                "description": plain_text(
                    "毛收入与净收入之间那道由客户激励撑开的缺口、"
                    "四条毛收入线各自的去向、"
                    "被两笔一次性压住的 GAAP 费用，"
                    "以及一笔被广泛读错了参照物的诉讼托管余额。"
                ),
                "exhibits": highlight_ex,
            },
            {
                "id": "next_quarter",
                "title": "三、下季要跟踪什么",
                "description": plain_text(
                    "当前值离下季阈值还有多远，统一用「距阈值余量」口径；"
                    "无法从申报文件复算的几条写在不接入清单里，不给近似值。"
                ),
                "exhibits": next_ex,
            },
            {
                "id": "routine",
                "title": "四、长期常规跟踪",
                "description": plain_text(
                    "V 专属的常规序列：十三年的客户激励率、"
                    "毛收入与净收入的两条增速、四条毛收入线的结构迁移、"
                    "美国以外的收入占比，以及股东回报与自由现金流的关系。"
                ),
                "exhibits": routine_ex,
            },
        ],
        "tables": tables,
        "notes": [plain_text(_p) for _p in [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "本页所有季度按自然年标注。Visa 财年 9 月底结束，故本页的 Q2 2026 是截至 2026-06-30 的季度，公司自己称之为 FY2026 Q3；映射规则为公司 FY 的 Q1→上一自然年 Q4、Q2→Q1、Q3→Q2、Q4→Q3。不统一成一种约定，跨公司的资本开支对照表就会把不同的三个月放在一起比较。",
            "<b>Visa 从不在申报文件里给季度数字指引，因此本页没有逐季的指引兑现记录。</b>"
            "这是取数限制而不是编辑取舍。它历史上给过的 Financial Outlook 一律是<b>财年</b>口径，"
            "从来没有过下一季度的数字区间，所以「本季指引 → 本季实际」这个对象在 Visa 这里不存在。"
            "财年口径的那部分也在逐步退场：FY2016–FY2020 有 Financial Outlook 小节，"
            "其中客户激励率与有效税率是数字区间，收入与 EPS 多为「mid-teens」这类文字区间；"
            "FY2020–FY2021 保留小节但明确不给指引；FY2022–FY2023 多数季度没有该小节；"
            "FY2024 只剩一句指向未在 EDGAR 归档的 earnings presentation；"
            "2025-01-30 之后的历次新闻稿连这句也没有。"
            "微软与 Alphabet 两页出于同样的理由也没有这类记录。"
            "<b>本页不发布「多少份新闻稿里有几份给了数字」这类计数</b> —— "
            "要给出这样的计数必须把全部四十余份新闻稿逐份读完，抽样得到的比例会失真。",
            "唯一的例外是客户激励率：「Client incentives as a percent of gross revenues」"
            "在 FY2017–FY2020 每个财年开局的业绩新闻稿「Financial Outlook」块里都是一个数字区间，"
            "本页第一节把这四年逐年对上了该财年 10-K 的实际值。"
            "四年里三年实际低于指引下限 —— 方向上是<b>好消息</b>，返给客户的钱比承诺的少。"
            "FY2020 之后公司停止给这个数字：FY2024 的 outlook 块完全不提客户激励，FY2026 的新闻稿没有 outlook 小节。",
            "激励率 = Client incentives ÷（Service + Data processing + International transaction + Other 四条毛收入线之和）。"
            "五个数都是各季 10-Q、10-K 收入分解附注里的申报值，比率是申报值之间的除法，不含任何估计；"
            "四条毛收入线减去激励等于申报净收入，55 个季度逐季核对全部相等。",
            "会计季 Q1–Q3 的损益表数字直接取自 10-Q 自己印的三个月栏，无需差分；"
            "会计季 Q4 没有 10-Q，其损益表各行为 10-K 全年数减去 6 月 10-Q 的九个月栏，两端都是申报值，核对表逐行标注。"
            "现金流量表在 10-Q 里只有年初至今栏，因此除会计第一季外每季均为相邻两次申报值之差。",
            "<b>每股口径在会计季 Q4 是空档而不是推算值。</b>"
            "EPS 不是可加项，加权平均股数也无法由减法还原，"
            "因此本页不对会计第四季给出 Class A 摊薄 EPS 或股数，也不用全年数去近似。",
            "<b>本页不发布任何「收入增速 vs 交易额增速」的对照。</b>"
            "公司在每份业绩新闻稿里都写明：Service revenue 按<b>上一季度</b>的支付额确认，"
            "其余收入线按<b>当季</b>活动确认；而新闻稿开头的「Key Business Drivers」表印的是<b>当季</b>支付额。"
            "把两者对齐来看会整整错开一个季度。"
            "更关键的是，公司只披露支付额与跨境交易额的<b>同比百分比</b>，从不按季披露它们的<b>绝对金额</b>，"
            "所以单位变现率（收入 ÷ 交易额）在公开申报文件里无法复算。",
            "诉讼托管账户与计提额的对照口径：美国追溯责任计划下的托管账户只为偿付 "
            "<b>U.S. covered litigation</b> 而存在，资产负债表上的「Accrued litigation」合计还包含 "
            "VE Territory covered 与不在覆盖范围内的诉讼。10-Q 在"
            "「Schedule of Accrued Litigation for Both Covered and Non-Covered Litigation」一表里"
            "把两个口径分开申报，因此本页用托管账户对 U.S. covered 计提，"
            "并在图上同时画出计提合计，标明它不是托管账户负责的对象。",
            "自由现金流是本页自算口径（D）：经营现金流减去购置不动产、设备与技术的现金支出。"
            "公司自己不发布自由现金流数字，也没有自定义口径可援引。",
            "核对抽屉最后那张「AI capex 循环」是全站<b>共用</b>的跨页对照块，"
            "在每一页都逐字节相同，不是对 Visa 的判断。"
            "它追的是四家云厂的现金资本开支 → NVDA 数据中心收入 → TSM 晶圆这条链，"
            "Visa 不在这条链的任何一环上：它既不是其中的支出方，也不是供应方。"
            "把它放在这里是为了让读者在任意一页都能查到同一份上下游对照，"
            "而不是暗示支付网络与这条链有关联。它在折叠的抽屉里，不参与本页的论证。",
            "本页只发布公司披露值、可复算的简单派生值，以及明确标注的市场预期；D 标记代表 Derived / 自算。",
            "市场预期一律标注为「市场预期」并给出取数时点，不写卖方机构名，也不发布评级、目标价或估值。",
            "本页已知未接入：分季支付额与跨境交易额的<b>绝对金额</b>（公司只给同比百分比）、"
            "单位交易变现率、增值服务（VAS）与商业支付（CMS）的分部收入绝对额（公司不在申报文件里拆分）、"
            "消费支付的单独收入口径、公司口径 non-GAAP 营业费用与利润率的逐季序列（每季剔除项由公司当季决定）、"
            "员工人数与裁员规模（本季电话会未量化，申报文件未披露）、"
            "以及任何来自业绩电话会而无法与第二个来源核对的前瞻数字。",
            "业绩电话会文字稿仅链接官方 IR 与 SEC 托管版本，公开仓不复制原件或逐字内容。",
        ]],
        "footer": "V quarterly results · 数据来自 Visa 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "v.js"), payload, "v")
    shell_dir = ROOT / "v"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("V", "v"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(
        f"V page: {charts} charts in {len(payload['sections'])} sections "
        f"+ {len(payload['tables'])} audit tables"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
