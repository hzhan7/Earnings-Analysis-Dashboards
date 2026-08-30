"""Brunello Cucinelli S.p.A. half-year dashboard.

Brunello Cucinelli is an Italian issuer listed on Euronext Milan, reporting
under IFRS in euro on a calendar fiscal year. It is not an SEC registrant: the
only EDGAR entity in its name holds seven filings, all of them F-6 and 424B3
depositary paperwork for an unsponsored ADR filed by a custodian bank under the
Rule 12g3-2(b) exemption, and none of them carries a financial statement. So
neither the rendered-statement R-files nor companyfacts reaches this company --
the annual reports, the half-year reports and the quarterly revenue releases
are the entire source.

**Two structural facts shape every chart here, and they are the page.**

First, everything the issuer prints is a *to-date* figure. It publishes revenue
four times a year -- Q1, H1, nine months, full year -- and a complete income
statement only twice, at H1 and at the full year. It has never printed a second,
third or fourth quarter, nor a second half, as a discrete period. So one quarter
in four and one half in two are company-printed; the rest are obtained here by
subtracting one cumulative disclosure from the next. That is transparent
arithmetic, but it is not disclosure, and the page marks which is which
everywhere it matters. The subtraction is checkable in one place and one only:
the issuer quotes a standalone third quarter in prose without tabling it, and
those three quotes match the subtraction.

Second, and this is what the first section is about: the company guides revenue
growth every year in the same words -- "around 10%" -- and for five years it
never said which currency basis it meant. Across the eighteen results calls
read here, 120 forward statements carry a number and **110 of them state no
exchange-rate basis at all**; every one that does is dated December 2025 or
later. The exchange-rate basis is not a footnote: reported and constant-rate
growth have differed by as much as 5.9pp, and in the half just reported they
differ by 3.8pp in opposite directions across the guided range. The same company,
the same six months, is simultaneously running above and below its own target
depending on a basis it did not state when it set the target.

The record is not that the company misses. Forty-seven completed quantified
targets were all met. It is that only six of the forty-seven say what currency
they are in, so on a strict reading the other forty-one cannot be scored -- and
that is the more informative number.

Published figures are company-reported or transparent arithmetic. Thresholds in
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
    threshold_table,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402

STAGING_PATH = ROOT / "series" / "bc.json"
DATA_DIR = ROOT / "data"

SOURCE_RELEASES = ("各期数字逐一取自公司自己的年度财务报告、半年度财务报告与季度营收公告；"
                   "公司不是美国申报人，本站其他页依赖的 10-Q/10-K 渲染报表对它不存在。")


def pct(current: float, base: float) -> float:
    return (current / base - 1) * 100.0


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def rounded(values, digits: int = 6):
    return [None if v is None else round(v, digits) for v in values]


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


# ── section one: the guidance and the basis it was never given on ────────────
def guidance_charts(s: dict) -> list[dict]:
    g = s["annual_revenue_guidance"]
    by = s["guidance_basis_by_year"]
    cen = s["guidance_basis_census"]
    st = g["strict_judgeability"]

    labels = ["FY2022", "FY2023", "FY2024", "FY2025", "2026H1"]
    mid = [(g["final_low"][i] + g["final_high"][i]) / 2 for i in (1, 2, 3, 4)] + [10.5]
    rep = [g["actual_reported_pct"][i] for i in (1, 2, 3, 4)] + [s["growth_h1_pct"]["reported"][-1]]
    cfx = [g["actual_cfx_pct"][i] for i in (1, 2, 3, 4)] + [s["growth_h1_pct"]["cfx"][-1]]
    gap = round(cfx[-1] - rep[-1], 1)

    straddle = {
        "ref": "EX_STRADDLE",
        "kind": "lines",
        "title": (f"同一条指引，两个实际：本期两个口径相差 {gap:.1f}pp，"
                  f"而指引区间只有 1pp 宽"),
        "xlabels": labels,
        "series": [
            {"name": "公司全年指引（区间中值）", "values": rounded(mid), "color": "RED"},
            {"name": "报告口径实际增长", "values": rounded(rep), "color": "NAVY"},
            {"name": "恒定汇率实际增长", "values": rounded(cfx), "color": "BLUE"},
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1",
        "end_label": True,
        "ylab": "同比 %",
        "note": ("四个完整年度里两条实际线都稳稳高于指引，口径选哪个都不影响结论 —— "
                 "所以这个问题在那四年里是不用回答的。<b>到本期它变成了唯一要回答的问题</b>："
                 f"恒定汇率 {cfx[-1]:.1f}% 高于指引上限 11%，报告口径 {rep[-1]:.1f}% 低于指引下限 10%。"
                 "2026 年的指引写明了是恒定汇率，所以正确的读法是前者；"
                 "但把同一个「10%」按报告口径去读，会把一个跑在目标之上的半年读成跑输。"
                 "最后一格是上半年进度，不是全年结果。"),
        "src_extra": SOURCE_RELEASES,
    }

    basis = {
        "ref": "EX_BASIS",
        "kind": "grouped_bars",
        "title": (f"{cen['quantified_rows']} 条量化指引里 {cen['fx_basis_unstated']} 条没写汇率口径，"
                  f"写了的 {cen['fx_basis_stated']} 条全部在 {cen['first_stated_date']} 之后"),
        "xlabels": [str(y) for y in by["years"]],
        "groups": [
            {"name": "未写明汇率口径", "color": "RED", "values": by["basis_unstated"]},
            {"name": "写明汇率口径", "color": "NAVY", "values": by["basis_stated"]},
        ],
        "bar_labels": True,
        "fmt": "f0", "label_fmt": "f0",
        "ylab": "条",
        "note": ("按会议年份统计十八场业绩会里的每一条量化前瞻表述。"
                 "口径这一栏在 2025 年 12 月之前是空的 —— 不是偶尔漏写，是一条都没有。"
                 "同一批文件在报<b>结果</b>时几乎每次都同时给两个口径，"
                 "只有在给<b>目标</b>时把口径省掉。"
                 "另外两项口径的情况更彻底：租赁准则口径与并购口径在这 120 条里"
                 "<b>一次都没有</b>被说明过。"),
        "src_extra": "统计口径为业绩电话会中带数字的前瞻表述；订货会反馈等定性表述不计入。",
    }

    judge = {
        "ref": "EX_JUDGE",
        "kind": "bars_labeled",
        "title": (f"{st['completed_quantified_targets']} 条已完结目标全部达成，"
                  f"但只有 {st['scoreable_once_an_unstated_basis_is_treated_as_unjudgeable']} 条"
                  f"说清了自己该用哪个口径结算"),
        "xlabels": ["已完结的量化目标", "其中达成", "其中说明了汇率口径"],
        "values": [st["completed_quantified_targets"], st["met"],
                   st["scoreable_once_an_unstated_basis_is_treated_as_unjudgeable"]],
        "fmt": "f0", "label_fmt": "f0", "yfmt": "f0",
        "ylab": "条",
        "note": ("「从没错过」这句话本身是成立的，公司确实条条兑现。"
                 "但一条没写口径的目标，严格说不是「达成了」，而是「无法判定」—— "
                 f"按这个标准，{st['completed_quantified_targets']} 条里只有 "
                 f"{st['scoreable_once_an_unstated_basis_is_treated_as_unjudgeable']} 条可以打分。"
                 "把两种口径都算上去凑出一个高达成率，等于让公司在事后挑一个对自己有利的基准。"
                 "本页两个数都给，并写明哪个是哪个。"),
        "src_extra": "覆盖公司在书面申报中给出的全部已完结量化目标，不只营收增长一项。",
    }
    return [straddle, basis, judge]


# ── section two: the half just reported ──────────────────────────────────────
def quarter_charts(s: dict) -> list[dict]:
    h = s["half"]
    i26 = h["periods"].index("2026H1")
    i25 = h["periods"].index("2025H1")
    ch = s["channel_h1_eur_k"]
    geo = s["geography_h1_eur_k"]
    gr = s["growth_h1_pct"]

    rev_g_cfx, rev_g_rep = gr["cfx"][-1], gr["reported"][-1]
    ebit_g = pct(h["ebit_eur_k"][i26], h["ebit_eur_k"][i25])
    net_g = pct(h["net_profit_eur_k"][i26], h["net_profit_eur_k"][i25])

    ladder = {
        "ref": "EX_LADDER",
        "kind": "bars_labeled",
        "title": (f"从收入到净利，四个增速一路掉了 {rev_g_cfx - net_g:.1f}pp，"
                  f"而其中只有 {rev_g_cfx - rev_g_rep:.1f}pp 发生在经营层面之上"),
        "xlabels": ["收入（恒定汇率）", "收入（报告口径）", "EBIT", "净利润"],
        "values": [round(rev_g_cfx, 1), round(rev_g_rep, 1), round(ebit_g, 1), round(net_g, 1)],
        "fmt": "pct1", "label_fmt": "pct1", "yfmt": "pct1",
        "ylab": "同比 %",
        "note": ("四根柱子不是一条桥，是四个各自独立的同比增速，放在一起看落差在哪一段发生。"
                 f"汇率吃掉 {rev_g_cfx - rev_g_rep:.1f}pp；经营杠杆把它加回来 "
                 f"{ebit_g - rev_g_rep:.1f}pp，所以 EBIT 增速反而高于报告口径收入；"
                 f"真正的断层在 EBIT 之下 —— 净利只增 {net_g:.1f}%，"
                 f"落差 {ebit_g - net_g:.1f}pp 全部来自财务损益与税，与经营无关。"
                 "增速之间不做加减，因为分母不同。"),
        "src_extra": "收入两个口径与 EBIT 由公司印出；净利润为公司印出的期间利润。",
    }

    d_ret = ch["retail"][-1] - ch["retail"][-2]
    d_who = ch["wholesale"][-1] - ch["wholesale"][-2]
    d_tot = d_ret + d_who
    bridge = {
        "ref": "EX_BRIDGE",
        "kind": "bridge_bar",
        "title": (f"半年 €{d_tot:,.0f} 千的收入增量里，零售贡献 "
                  f"{d_ret / d_tot * 100:.1f}%，批发几乎原地不动"),
        "xlabels": ["零售渠道", "批发渠道", "合计增量"],
        "stacks": [{"name": "较上年同期的增量", "color": "NAVY",
                    "values": [d_ret, d_who, None]}],
        "net": {"name": "半年收入增量合计", "values": [None, None, d_tot]},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "€ 千",
        "note": (f"批发渠道的绝对额从 €{ch['wholesale'][-2]:,.0f} 千走到 "
                 f"€{ch['wholesale'][-1]:,.0f} 千，一年只多了 €{d_who:,.0f} 千。"
                 "在此之前它连续四年每年都增长。"
                 "公司把批发占比降到 30% 写成过目标，本期是 "
                 f"{ch['wholesale'][-1] / (ch['retail'][-1] + ch['wholesale'][-1]) * 100:.1f}% —— "
                 "占比确实在降，但降的原因是分母在跑，不是分子在缩。"),
        "src_extra": "渠道口径为公司自己的两分法：零售（直营门店与自营电商）与批发。",
    }

    share = [round(r / (r + w) * 100, 1) for r, w in zip(ch["retail"], ch["wholesale"])]
    mix = {
        "ref": "EX_MIX",
        "kind": "stacked_dual",
        "title": (f"零售占比连续三年停在 {min(share[2:5]):.1f}%–{max(share[2:5]):.1f}%，"
                  f"本期一步走到 {share[-1]:.1f}%"),
        "xlabels": [f"{y}H1" for y in ch["years"]],
        "stacks": [
            {"name": "零售渠道", "color": "NAVY", "values": ch["retail"]},
            {"name": "批发渠道", "color": "GOLD", "values": ch["wholesale"]},
        ],
        "line": {"name": "零售占比（右轴）", "color": "RED", "values": share, "ymax": 100},
        "fmt": "f0c", "label_fmt": "f0c",
        "ylab": "€ 千",
        "rlab": "零售占比 %",
        "note": ("柱是每年上半年的两个渠道绝对额，右轴红线是零售占比。"
                 "2023 到 2025 三年占比停在 63.4%–63.7%，看起来结构已经稳定；"
                 "本期跳升不是零售突然加速，是批发停住之后分母只剩一条腿在动。"
                 "右轴显式设了 100% 的上界 —— 这一图型的右轴默认封顶在 60，"
                 "占比线超过就会被画到画布外而图例照常显示。"),
        "src_extra": "各年上半年数取自当期半年度报告的渠道表；2026 年取自半年业绩新闻稿。",
    }

    names = ("欧洲", "美洲", "亚洲")
    rows = (geo["europe_total"], geo["americas"], geo["asia"])
    totals = [sum(col[i] for col in rows) for i in range(len(geo["years"]))]
    first = {n: col[0] / totals[0] * 100 for n, col in zip(names, rows)}
    last = {n: col[-1] / totals[-1] * 100 for n, col in zip(names, rows)}
    was_biggest = max(first, key=first.get)
    now_biggest = max(last, key=last.get)
    region = {
        "ref": "EX_REGION",
        "kind": "grouped_bars",
        "title": (f"三个区域六年：最大的一块从{was_biggest}换成{now_biggest}，"
                  f"{was_biggest}让出 {first[was_biggest] - last[was_biggest]:.1f} 个百分点"),
        "xlabels": [f"{y}H1" for y in geo["years"]],
        "groups": [
            {"name": "欧洲（含意大利）", "color": "NAVY", "values": geo["europe_total"]},
            {"name": "美洲", "color": "BLUE", "values": geo["americas"]},
            {"name": "亚洲", "color": "GOLD", "values": geo["asia"]},
        ],
        "bar_labels": False,
        "fmt": "f0c", "label_fmt": "f0c",
        "ylab": "€ 千",
        "note": ("公司到 2024 年上半年为止分四行披露：欧洲（不含意大利）、意大利、美洲、亚洲；"
                 "2025 年上半年起改成三行，意大利并进欧洲，上年同期也一并改按新口径重列。"
                 "<b>这次改动在文字里没有任何说明</b>，唯一的证据是算术："
                 "152,959 + 68,093 = 221,052。本图六年一律用「含意大利的欧洲」，"
                 "早年由两行相加还原，六年各自相加都精确等于公司印出的总额。"),
        "src_extra": "口径还原为本页自算（D）；相加校验见核对抽屉。",
    }
    return [ladder, bridge, mix, region]


# ── section three: what to track next ────────────────────────────────────────
def next_quarter_charts(s: dict) -> list[dict]:
    kpi = s["next_kpi"]
    head = headroom_exhibit(
        "下半年六条阈值与当前值：距阈值的余量",
        kpi["quantified"], "current",
        ("六条统一换算成「距阈值的余量」，正值表示还在安全侧。"
         "其中四条的阈值取自公司自己给出的年度目标（EBIT 利润率约 17%、"
         "资本开支约 6%、年末净负债占收入 11–12%、批发占比降至 30% 一线），"
         "两条是本页自设的观察线。"
         "<b>当前有三条已经越线</b>：资本开支上半年跑到 7.6%，"
         "隐含下半年要压到 4% 出头才够得着全年约 6%；"
         "净负债则同时高于上年末与上年同期；报告口径的半年收入增速也低于 10% 这条线。"
         "注意其中三条一年只更新两次 —— 完整损益与资产负债表只在半年和全年出现。"),
        "阈值为本地研究设定，不是公司指引；当前值为公司披露值或本页自算（D）。",
    )

    dec = s["ifrs16_disclosure_decay"]
    h = s["half"]
    idx = [h["periods"].index(f"{y}H1") for y in range(2021, 2027)]
    post = [round(h["ebitda_eur_k"][i] / h["revenue_eur_k"][i] * 100, 1) for i in idx]
    ex = [None if h["ebitda_ex_ifrs16_eur_k"][i] is None
          else round(h["ebitda_ex_ifrs16_eur_k"][i] / h["revenue_eur_k"][i] * 100, 1)
          for i in idx]
    ifrs = {
        "ref": "EX_IFRS16",
        "kind": "lines",
        "title": ("能把租赁会计和经营利润分开的那条线，公司发布了四年然后停了"),
        "xlabels": dec["periods"],
        "series": [
            {"name": "EBITDA 利润率（含租赁准则影响）", "values": post, "color": "NAVY"},
            {"name": "EBITDA 利润率（剔除租赁准则）", "values": ex, "color": "RED"},
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1",
        "end_label": True,
        "ylab": "占收入 %",
        "note": ("红线在 2024 年上半年之后就没有了 —— 不是数值变差，是公司不再披露："
                 "两个口径连同调节表一起给到 2023 年上半年，2024 年上半年去掉调节表，"
                 "2025 年上半年把「剔除租赁准则的 EBITDA」整个从其替代业绩指标里撤下，"
                 "2026 年的半年新闻稿连 EBITDA 本身都不再出现。"
                 "<b>值得说清的是红线消失前的走向</b>：两条线的差距从 13.0pp 收窄到 9.2pp，"
                 "也就是说被披露的那几年里，租赁对利润率的抬升作用是在<b>减弱</b>的。"
                 "撤下披露发生在 2024 年，早于外界就这个口径提出质疑的时间。"
                 "本页不替公司补算 2025 年之后的红线：还原它需要剔除租赁后的折旧，"
                 "而那个数同样不再披露。"),
        "src_extra": "两个口径的数值与调节表均为公司印出；停止披露的时点以各期报告的替代业绩指标章节为准。",
    }
    return [head, ifrs]


# ── section four: the long record ────────────────────────────────────────────
def long_charts(s: dict) -> list[dict]:
    q = s["quarterly"]
    labels, vals, basis = q["periods"], q["revenue_eur_k"], q["basis"]
    yoy = [None if i < 4 else round(pct(vals[i], vals[i - 4]), 1) for i in range(len(vals))]
    printed = sum(1 for b in basis if b == "printed")

    quarters = {
        "ref": "EX_Q",
        "kind": "gs_bar",
        "title": (f"{len(labels)} 个季度里只有 {printed} 个是公司印出来的，"
                  f"其余 {len(labels) - printed} 个由相邻两次累计披露相减得到"),
        "xlabels": labels,
        "values": vals,
        "yoy": {"name": "同比（右轴）", "color": "GOLD", "values": yoy},
        "fmt": "f0c", "label_fmt": "f0c",
        "ylab": "€ 千",
        "rlab": "同比 %",
        "note": ("公司每年只把第一季度当作一个季度来公布；半年、九个月、全年都是累计数。"
                 "所以第二、三、四季度在任何一份文件里都不存在，本图由 H1−Q1、9M−H1、FY−9M 得到。"
                 "<b>这个减法只有一处可以外部验证</b>：公司在正文里口头提过三次单季第三季度的规模，"
                 "而相减的结果与那三次逐一对上（2023 年 274.4、2024 年约 300、2025 年 335.0，"
                 "单位百万欧元）。四个季度相加等于全年这件事<b>不构成验证</b> —— "
                 "第四季度本来就是用全年减出来的。"
                 "同比线从第五格起才有值，因为需要上年同季。"),
        "src_extra": SOURCE_RELEASES,
    }

    h = s["half"]
    # Two lists on purpose. The payload keeps a rounded value so a rebuild is
    # idempotent; the prose formats the exact one. Rounding to 2dp and then
    # printing at 1dp double-rounds: 2023H2 is 16.7449%, which becomes 16.75 and
    # then prints as 16.8, a figure no arithmetic on this page produces.
    margin_exact = [e / r * 100 for e, r in zip(h["ebit_eur_k"], h["revenue_eur_k"])]
    margin = [round(v, 2) for v in margin_exact]
    guide = [17.0] * len(h["periods"])
    # Every count and list below is derived. On a half-year axis "a year ago" is
    # two indices back, not four, and a hand-typed run of values silently drops
    # one: the first draft of this note listed five halves for a six-half span
    # and skipped 2025H1 altogether.
    flat_from = h["periods"].index("2023H2")
    flat = margin_exact[flat_from:]
    flat_text = "、".join(f"{v:.1f}" for v in flat)
    peak_i = margin_exact.index(max(margin_exact))
    climb_to = max(margin_exact[:flat_from])
    ebit = {
        "ref": "EX_MARGIN",
        "kind": "lines",
        "title": (f"EBIT 利润率按半年：{margin_exact[0]:.1f}% 起步爬到 {climb_to:.1f}%，"
                  f"随后 {len(flat)} 个半年在 {min(flat):.1f}%–{max(flat):.1f}% 之间来回"),
        "xlabels": h["periods"],
        "series": [
            {"name": "EBIT 利润率（半年）", "values": margin, "color": "NAVY"},
            {"name": "公司 2026 年指引：约 17%", "values": guide, "color": "RED"},
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1",
        "end_label": True,
        "ylab": "占收入 %",
        "note": ("这是本站第一条以<b>半年</b>为时间轴的连续序列，因为这家公司的完整损益一年只有两次。"
                 "奇数格（H1）是公司印出的，偶数格（H2）由全年减上半年得到，公司从不单独公布下半年。"
                 f"{h['periods'][flat_from]} 到 {h['periods'][-1]} 共 {len(flat)} 个半年，"
                 f"依次是 {flat_text} —— 在 {min(flat):.1f}% 到 {max(flat):.1f}% 之间来回。"
                 f"最高的一格是 {h['periods'][peak_i]} 的 {margin_exact[peak_i]:.1f}%。"
                 "所以公司把 2026 年的目标定在「约 17%」，"
                 "要求的不是继续扩张，是守住这条线。"
                 "<b>2025 年下半年那一格里含一笔北美批发客户破产的拨备</b>，"
                 "公司在全年口径上另给了一个剔除该笔的「正常化」EBIT，本图一律用报告口径。"),
        "src_extra": "半年值为公司印出；下半年值为全年减上半年（D）。",
    }

    a = s["annual"]
    yrs = a["years"][1:]
    rep = a["revenue_yoy_reported_pct"][1:]
    norm = a["ebit_normalised_eur_k"]
    conv = {
        "ref": "EX_CONV",
        "kind": "bars_labeled",
        "title": ("年度营收增速五年从 30.9% 收敛到 10.1%，"
                  "而指引一直是同一句「约 10%」"),
        "xlabels": [f"FY{y}" for y in yrs],
        "values": rounded(rep),
        "fmt": "pct1", "label_fmt": "pct1", "yfmt": "pct1",
        "ylab": "报告口径同比 %",
        "note": ("2021 到 2023 年公司远远跑赢自己给的数，指引在那三年更像是一条地板。"
                 "2024 年起实际增速落到 12.2%、10.1%，"
                 "和「约 10%」之间的距离从二十多个百分点收到一个百分点以内 —— "
                 "<b>同一句话的性质因此变了</b>：它从一条容易越过的地板，"
                 "变成一条贴着实际走的线。这也是口径问题在今年才开始要紧的原因。"),
        "src_extra": "报告口径同比；恒定汇率口径公司自 2022 年起才逐年给出，2021 年没有。",
    }

    nd = s["net_debt_h1_eur_k"]
    trough = nd["pre_ifrs16"].index(min(nd["pre_ifrs16"]))
    span = nd["years"][-1] - nd["years"][trough]
    debt = {
        "ref": "EX_DEBT",
        "kind": "lines",
        "title": (f"核心净金融负债 {span} 年从 €{nd['pre_ifrs16'][trough] / 1000:.1f} 百万"
                  f"走到 €{nd['pre_ifrs16'][-1] / 1000:.1f} 百万，"
                  "而公司给的年末目标是收入的 11–12%"),
        "xlabels": [f"{y}H1" for y in nd["years"]],
        "series": [
            {"name": "核心净金融负债（不含租赁负债）", "values": nd["pre_ifrs16"], "color": "NAVY"},
        ],
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "end_label": True,
        "ylab": "€ 千",
        "note": ("公司主推的是这条不含租赁负债的「核心」口径，本图照此。"
                 "含租赁负债的口径在同一时点是 €1,045,855 千，量级差四倍以上，"
                 "两者不可混用。"
                 "本期 €225,100 千同时高于上年末的 €198,400 千与上年同期的 €197,183 千；"
                 "按公司自己的年末目标（收入的 11–12%）与它给的全年增速，"
                 "下半年需要回落到 €170,000 千一线。"),
        "src_extra": "两个口径均由公司印出；2026 年含租赁口径为本页自算（D）。",
    }
    return [quarters, ebit, conv, debt]


def build_payload(staging: dict) -> dict:
    s = staging
    settled = guidance_charts(s)
    highlights = quarter_charts(s)
    nxt = next_quarter_charts(s)
    routine = long_charts(s)

    exhibits = number_exhibits(settled + highlights + nxt + routine)
    resolve_exhibit_refs(exhibits)
    a, b, c = len(settled), len(highlights), len(nxt)
    settled_ex, highlight_ex = exhibits[:a], exhibits[a:a + b]
    next_ex, routine_ex = exhibits[a + b:a + b + c], exhibits[a + b + c:]

    h = s["half"]
    q = s["quarterly"]
    ch = s["channel_h1_eur_k"]
    geo = s["geography_h1_eur_k"]
    gr = s["growth_h1_pct"]
    first_table = exhibits[-1]["n"] + 1

    tables = [{
        "n": first_table,
        "title": "半年合并损益与利润率（公司披露值，H2 为全年减上半年）",
        "headers": ["期间", "来源", "收入", "EBITDA", "EBITDA（剔除租赁准则）",
                    "EBIT", "EBIT 利润率 D", "期间利润"],
        "rows": [[h["periods"][i],
                  "公司印出" if h["printed"][i] else "全年减上半年 D",
                  f"€{h['revenue_eur_k'][i]:,.0f}千",
                  f"€{h['ebitda_eur_k'][i]:,.0f}千",
                  "—" if h["ebitda_ex_ifrs16_eur_k"][i] is None
                  else f"€{h['ebitda_ex_ifrs16_eur_k'][i]:,.0f}千",
                  f"€{h['ebit_eur_k'][i]:,.0f}千",
                  f"{h['ebit_eur_k'][i] / h['revenue_eur_k'][i] * 100:.2f}%",
                  f"€{h['net_profit_eur_k'][i]:,.0f}千"]
                 for i in range(len(h["periods"]))],
    }, {
        "n": first_table + 1,
        "title": "季度收入与它的来源（公司只印第一季度）",
        "headers": ["期间", "收入", "来源", "同比 D"],
        "rows": [[q["periods"][i], f"€{q['revenue_eur_k'][i]:,.0f}千",
                  "公司印出" if q["basis"][i] == "printed" else "由累计披露相减 D",
                  "—" if i < 4 else f"{pct(q['revenue_eur_k'][i], q['revenue_eur_k'][i - 4]):+.1f}%"]
                 for i in range(len(q["periods"]))],
    }, {
        "n": first_table + 2,
        "title": "上半年的渠道、区域与两个口径的增速",
        "headers": ["期间", "零售", "批发", "零售占比 D", "欧洲（含意大利）", "美洲", "亚洲",
                    "报告口径同比", "恒定汇率同比"],
        "rows": [[f"{y}H1", f"€{ch['retail'][i]:,.0f}千", f"€{ch['wholesale'][i]:,.0f}千",
                  f"{ch['retail'][i] / (ch['retail'][i] + ch['wholesale'][i]) * 100:.1f}%",
                  f"€{geo['europe_total'][i]:,.0f}千", f"€{geo['americas'][i]:,.0f}千",
                  f"€{geo['asia'][i]:,.0f}千",
                  "—" if y == 2021 else f"{gr['reported'][gr['years'].index(y)]:+.1f}%",
                  "—" if y == 2021 else f"{gr['cfx'][gr['years'].index(y)]:+.1f}%"]
                 for i, y in enumerate(ch["years"])],
    }]
    tables.append(threshold_table(first_table + 3, "下半年阈值与当前值（原始单位）",
                                  s["next_kpi"]["quantified"], "current", "当前值"))
    tables.append(ai_capex_cycle_table(first_table + 4))

    i26, i25 = h["periods"].index("2026H1"), h["periods"].index("2025H1")
    ebit_g = pct(h["ebit_eur_k"][i26], h["ebit_eur_k"][i25])
    net_g = pct(h["net_profit_eur_k"][i26], h["net_profit_eur_k"][i25])
    d_ret = ch["retail"][-1] - ch["retail"][-2]
    d_tot = d_ret + (ch["wholesale"][-1] - ch["wholesale"][-2])
    cen = s["guidance_basis_census"]
    st = s["annual_revenue_guidance"]["strict_judgeability"]

    return {
        "schema_version": "quarterly-dashboard/bc-v1",
        "page": {"slug": "bc", "language": "zh-CN"},
        "company": {"ticker": "BC", "name": "Brunello Cucinelli S.p.A.",
                    "group": "luxury_brands", "accounting_standard": "IFRS"},
        "latest": {
            "disclosed_period_label": "H1 2026",
            "full_financial_period_label": "H1 2026",
            "period_end": "2026-06-30",
            "release_date": "2026-07-30",
            "analysis_date": "2026-08-30",
            "audit_status": "unaudited",
            "status": "history_ready",
        },
        "tracker": "Watchlist Quarterly Tracker · BC",
        "title": "Brunello Cucinelli S.p.A. (BC)：2026 年上半年业绩仪表盘",
        "subtitle": ("截至 2026-06-30 · 发布 2026-07-30 · IFRS · 欧元列示 · 自然年财年 · "
                     "季度只发营收、完整损益一年两次 · 数据来自公司年报、半年报与季度营收公告"),
        "headline": (
            f"上半年收入 €{h['revenue_eur_k'][i26]:,.0f} 千，恒定汇率 "
            f"{signed(gr['cfx'][-1])}、报告口径 {signed(gr['reported'][-1])} —— "
            f"前者高于全年指引上限 11%，后者低于下限 10%，"
            f"而公司在 2025 年 12 月之前给过的 {cen['fx_basis_unstated']} 条量化指引"
            f"没有一条写明该用哪个口径；"
            f"同一个半年里 EBIT 增 {signed(ebit_g)} 而净利只增 {signed(net_g)}，"
            f"落差全在经营线以下；收入增量的 {d_ret / d_tot * 100:.1f}% 来自零售，"
            f"批发在连续增长四年之后停住。"),
        "brief": (
            '<h4>本期三条主线</h4><div class="takeaway-grid">'
            '<article><span>记录</span><b>口径这一栏空了五年，今年开始决定答案</b>'
            f'<p>十八场业绩会里 {cen["quantified_rows"]} 条量化指引，'
            f'{cen["fx_basis_unstated"]} 条没写汇率口径；写了的全在 {cen["first_stated_date"]} 之后。'
            f'{st["completed_quantified_targets"]} 条已完结目标条条达成，'
            f'但只有 {st["scoreable_once_an_unstated_basis_is_treated_as_unjudgeable"]} 条'
            '说清了该用哪个口径结算。</p></article>'
            '<article><span>本期</span><b>断层在 EBIT 以下，不在收入</b>'
            f'<p>恒定汇率收入 {signed(gr["cfx"][-1])}、EBIT {signed(ebit_g)}，'
            f'经营层面没有问题；净利润只增 {signed(net_g)}，'
            f'{ebit_g - net_g:.1f}pp 的落差来自财务损益与税。</p></article>'
            '<article><span>结构</span><b>批发停住，增长只剩一条腿</b>'
            f'<p>半年收入增量 €{d_tot:,.0f} 千里零售占 {d_ret / d_tot * 100:.1f}%；'
            f'批发绝对额一年只多了 €{ch["wholesale"][-1] - ch["wholesale"][-2]:,.0f} 千，'
            '而它此前连续四年增长。</p></article>'
            '</div>'),
        "source": ('Source: <a href="https://investor.brunellocucinelli.com/en/services/'
                   'archive/investor/press-releases" rel="noopener">'
                   'Brunello Cucinelli 投资者关系 · 新闻稿与业绩公告归档</a>。'
                   '公司在 Euronext Milan 上市，不是美国申报人，'
                   'EDGAR 上仅有存托银行为无保荐 ADR 提交的 F-6/424B3 文件，不含任何财务报表。'),
        "source_url": ("https://investor.brunellocucinelli.com/en/services/archive/"
                       "investor/press-releases"),
        "source_links": s["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {"id": "settled", "title": "一、公司的指引，和它没说的口径",
             "description": ("公司每年用同一句话给指引：营收增长「约 10%」。"
                             "这一节先看这句话在报告口径与恒定汇率下会得到相反的结论，"
                             "再看口径这一栏在申报里是什么时候才开始被填上的。"),
             "exhibits": settled_ex},
            {"id": "quarter_highlights", "title": "二、本期重点",
             "description": "增速在哪一段掉下来、收入增量由谁贡献、渠道与区域结构走到了哪里。",
             "exhibits": highlight_ex},
            {"id": "next_quarter", "title": "三、下半年要跟踪什么",
             "description": ("六条阈值统一用「距阈值余量」口径，其中三条当前已越线；"
                             "另有一条公司发布四年后停掉的口径，单独列出。"),
             "exhibits": next_ex},
            {"id": "routine", "title": "四、长期常规跟踪",
             "description": "季度收入的来源构成、半年利润率的长期路径、增速收敛与净负债。",
             "exhibits": routine_ex},
        ],
        "tables": tables,
        "notes": [
            "本页按「指引与口径 → 本期重点 → 下半年跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "公司在 Euronext Milan 上市，按 IFRS 以欧元列报，财年即自然年。它不是美国证券法下的申报人：EDGAR 上以其名义存在的唯一实体只有七份文件，全部是存托银行为一只无保荐 ADR 提交的 F-6 与 424B3，依据 Rule 12g3-2(b) 豁免，不含任何财务报表。本站其他公司页依赖的 10-Q/10-K 渲染报表对本公司不存在，本页全部数据来自公司自己的年度财务报告、半年度财务报告与季度营收公告。",
            "披露节奏是本页所有图表形状的来源：收入一年公布四次（第一季度、半年、九个月、全年），完整损益表一年只有两次（半年与全年）。公司从未把第二、第三、第四季度或下半年作为独立期间公布过，它印出来的每一个数都是「截至某日累计」。因此本页 18 个季度里只有 5 个是公司印出的，11 个半年里只有 6 个是公司印出的，其余由相邻两次累计披露相减得到，图与表中逐格标明。",
            "相减这件事只有一处可以外部验证：公司在正文叙述里三次提到过单季第三季度的规模，而 9M 减 H1 的结果与这三次逐一吻合（2023 年 274.4、2024 年约 300、2025 年 335.0，单位百万欧元）。「四个季度相加等于全年」不构成验证，因为第四季度本来就是用全年减九个月得到的 —— 一个从被检查对象推导出自己期望值的检查不可能失败，本页不把它算作证据。",
            "指引口径是本页第一节的主题。十八场业绩会里共 120 条带数字的前瞻表述，其中 110 条没有说明汇率口径；说明了的 10 条全部发布于 2025 年 12 月 10 日或之后。租赁准则口径与并购口径在这 120 条里一次都没有被说明过。同一批文件在公布结果时几乎每次都同时给出报告口径与恒定汇率两个数，只在给出目标时把口径省略。",
            "口径的取舍不是措辞问题：报告口径与恒定汇率的差在本记录里介于 0.5pp 与 5.9pp 之间，本期为 3.8pp，而 2026 年的指引区间只有 1pp 宽。一条指引必须用它自己的口径结算 —— 把 2025 年 12 月给出的恒定汇率区间（+11% 至 +12%）拿去和报告口径实际（+10.1%）相比，会得到一次并不存在的未达标；那次修订同时给了报告口径「约 10%」这一条腿，两条腿各自都兑现了。",
            "公司已完结的量化目标共 47 条，全部达成。但其中只有 6 条说明了自己的汇率口径，其余 41 条严格说无法判定 —— 本页两个数都给出，并写明哪个是哪个。「从没错过」这句话成立，但它衡量的是指引的保守程度，不是预测的准确程度。",
            "区域披露口径在 2025 年上半年变过一次：此前分四行（欧洲不含意大利、意大利、美洲、亚洲），此后分三行，意大利并入欧洲，上年同期一并重列。这次改动在文字里没有任何说明，唯一的证据是算术恒等式 152,959 + 68,093 = 221,052。本页六年一律采用含意大利的欧洲口径，早年由两行相加还原，六年各自相加都精确等于公司印出的总额。",
            "「剔除租赁准则影响的 EBITDA」是公司自己的替代业绩指标，发布于 2021 至 2024 年上半年：2021 至 2023 年上半年同时给出两个口径与调节表，2024 年上半年去掉调节表，2025 年上半年将该指标整个撤下，2026 年的半年新闻稿不再出现 EBITDA 本身。被披露的那几年里两个口径的差距是收窄的（13.0pp 到 9.2pp），撤下发生在 2024 年。本页不向后补算这条线，因为还原它需要剔除租赁后的折旧，而该数同样不再披露。",
            "公司不发布任何期间的完整毛利表：其损益表按费用性质列示，没有销货成本，也没有毛利这一行。它另给一个自定义的「first margin」，且从不在同一期间同时印出该指标的绝对值与百分比，两者之中总有一个是算出来的。本页因此不发布毛利率序列。",
            "净金融负债有两个口径：公司主推不含租赁负债的「核心」口径，2026 年上半年为 €225,100 千；含租赁负债的口径在同一时点为 €1,045,855 千。量级相差四倍以上，任何跨页或跨期比较都必须先说明用的是哪一个。",
            "2025 年下半年的 EBIT 里含一笔北美批发客户破产相关的拨备，公司在全年口径上另给了一个剔除该笔的「正常化」EBIT（€235,851 千，占收入 16.8%），而报告口径为 €227,784 千、占收入 16.2%，比上一年的 16.6% 是下降的。本页所有利润率一律用报告口径，正常化值只在本说明中出现，因为把一年的正常化值和另一年的报告值放在同一条线上会让方向反过来。",
            "公司在 2025 年年度报告中把一家做空机构就其俄罗斯业务提出的指控列为关键审计事项，审计师据此对相关批发交易执行了程序并出具了无保留意见，未确认相关或有负债。本页记录这一披露事实本身，不对指控作判断，也不发布任何第三方的结论。",
            "本页不发布市场一致预期、评级、目标价与估值。第三节的六条阈值是本地研究设定，不是公司指引；其中四条的数值取自公司自己给出的年度目标，两条为本页自设的观察线。",
            "本页只发布公司披露值与可复算的简单派生值；D 标记代表 Derived / 自算。",
            "本页已知未接入：同店销售（like-for-like）与新增零售面积的贡献 —— 公司从未披露，两家券商在 2026 年 7 月 30 日的业绩会上先后追问均未获得数字，因此零售增长中「开店」与「同店」两部分无法拆分；零售面积与批发单品牌门店数（2025 年起不再出现在营收更新中）；分产品线收入（只在完整半年报与年报中披露，2026 年的半年新闻稿没有）；恒定汇率口径的分区域完整历史（公司自 2025 年第三季度起才逐区给出）；以及 2026 年上半年之后的任何数据。",
            "业绩电话会内容仅用于定位公司已在申报文件中量化的项目与统计指引口径的披露与否，公开仓不复制原件或逐字内容。",
            "核对抽屉最后那张「AI capex 循环」是全站共用的跨页对照块，在每一页都逐字节相同，不是对本公司的判断。它追的是四家云厂现金资本开支到 NVDA 数据中心收入再到 TSM 晶圆这条链，本公司不在这条链的任何一环上；它在折叠的抽屉里，不参与本页的论证。",
        ],
        "footer": "Brunello Cucinelli half-year results · 数据来自公司公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "bc.js"), payload, "bc")
    shell_dir = ROOT / "bc"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("BC", "bc"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"BC page: {charts} charts in {len(payload['sections'])} sections "
          f"+ {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
