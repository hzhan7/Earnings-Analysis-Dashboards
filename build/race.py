"""Ferrari N.V. quarterly dashboard.

Ferrari is the first company on this site that files no 10-Q, no 10-K and no
8-K. It is a Dutch-incorporated foreign private issuer reporting under IFRS in
euro, so its annual filing is a 20-F and every quarterly figure it has ever
published sits in the EX-99.1 of a results 6-K. The rendered-statement R-files
the rest of this site leans on cover 10-Q and 10-K schedules, and Ferrari has
neither, so the releases themselves are the whole source.

**And the guidance record it files has a shape no other page here carries.**
The other guidance pages settle a range: did the reported number land inside
it. Ferrari's full-year outlook is mostly not a range at all -- it is a
one-sided inequality. Across 31 vintages and five guided metrics, 69 readings
are floors, 31 are points, 6 are ceilings and only 49 are two-sided ranges.

The finding is what happens to that mix as a year runs. The opening, Q1 and Q2
vintages carry 15 to 17 ranges each. The Q3 vintage -- the one that settles the
year, published in early November with about ten of twelve months banked --
carries **one range out of 35**. Every other year-end vintage is a floor, a
point or a ceiling. In all five years where adjusted EBITDA opened as a
two-sided range (FY2019 through FY2023) it ended that same year as a point or a
floor, and from FY2024 the range is gone from the opening vintage too.

So the guidance sheds its upper bound exactly as the year becomes knowable,
which is the opposite of a forecast narrowing onto an answer. That is why this
page does not report a hit rate as its headline: against a floor, "never
missed" is close to a tautology, and it is the *distance above* the floor and
the *path the floor took* that still carry information.

Published numbers are company-reported or transparent arithmetic. Thresholds in
section three are local research settings, not company guidance.
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
    headroom_exhibit,
    number_exhibits,
    threshold_exhibit,
    threshold_table,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "race.json"
DATA_DIR = ROOT / "data"

# One tick per year keeps the forty-two-quarter axes readable.
LONG_STEP = 4

METRIC_NAMES = {
    "revenue": "净收入",
    "adj_ebitda": "调整后 EBITDA",
    "adj_ebit": "调整后 EBIT",
    "adj_eps": "调整后摊薄 EPS",
    "ifcf": "工业自由现金流",
}
FORM_NAMES = {"range": "两端区间", "floor": "只给下限", "point": "单点约数", "ceiling": "只给上限"}
SLOT_NAMES = {"initial": "年初首次", "q1": "Q1 修订", "q2": "Q2 修订", "q3": "Q3 修订"}

SOURCE_6K = ("全年指引的每一档逐字取自当季业绩 6-K 的 EX-99.1 展望表；"
             "该表的指引列在 2018–2025 年各期都排在最右，2026 年起改排最左，"
             "本页按表头逐期判断，不按列序取值。")


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100.0


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


def decimals(value: float) -> int:
    text = f"{value:.10f}".rstrip("0")
    return len(text.split(".")[1]) if "." in text else 0


def verdict(low: float, high: float, form: str, actual: float) -> str:
    """How a year landed, with a tolerance equal to the PRINTED precision.

    `~1.27` is stated to EUR 0.01B and therefore carries +/- EUR 5M. FY2019
    adjusted EBITDA came in at EUR 1.269B -- three million euro under a figure
    the company printed to two decimals. Scoring that as a miss would apply a
    threshold finer than the disclosure it is measured against, which is the
    same reason the Mastercard page retired a currency-neutral threshold.
    """
    tolerance = 0.5 * 10 ** -decimals(high)
    if form == "range":
        if actual > high + tolerance:
            return "above"
        if actual < low - tolerance:
            return "below"
        return "inside"
    if form == "ceiling":
        return "within" if actual <= high + tolerance else "exceeded"
    if abs(actual - high) <= tolerance:
        return "met"
    return "above" if actual > high else "below"


# ── section one: the full-year guidance record ───────────────────────────────
def form_chart(record: dict) -> dict:
    """How often each vintage slot published a two-sided range at all."""
    slots = ["initial", "q1", "q2", "q3"]
    counts = {slot: {form: 0 for form in FORM_NAMES} for slot in slots}
    for index, slot in enumerate(record["vintage_slots"]):
        for metric in METRIC_NAMES:
            form = record["items"][metric]["form"][index]
            if form:
                counts[slot][form] += 1
    totals = {slot: sum(counts[slot].values()) for slot in slots}
    return {
        "ref": "EX_FORM",
        "kind": "grouped_bars",
        "title": (f"指引的<b>形状</b>按发布档次分布：年初那一档 {totals['initial']} 个读数里 "
                  f"{counts['initial']['range']} 个是两端区间，"
                  f"结算这一年的 Q3 那一档 {totals['q3']} 个读数里只有 "
                  f"{counts['q3']['range']} 个"),
        "xlabels": [SLOT_NAMES[slot] for slot in slots],
        "groups": [
            {"name": FORM_NAMES["range"], "color": "NAVY",
             "values": [counts[s]["range"] for s in slots]},
            {"name": FORM_NAMES["floor"], "color": "BLUE",
             "values": [counts[s]["floor"] for s in slots]},
            {"name": FORM_NAMES["point"], "color": "GOLD",
             "values": [counts[s]["point"] for s in slots]},
            {"name": FORM_NAMES["ceiling"], "color": "RED",
             "values": [counts[s]["ceiling"] for s in slots]},
        ],
        "bar_labels": True,
        "fmt": "f0", "label_fmt": "f0",
        "ylab": "读数个数",
        "note": ("<b>这是本页的核心发现，也是本站其他指引页问不出来的问题。</b>"
                 "别的公司给的是区间，可以问「实际值有没有落在区间里」；"
                 "法拉利给的大多不是区间，而是单边不等式 —— 利润与现金给「至少」，"
                 "净工业负债给「不超过」，收入与出货给「约」。"
                 "五个指标、31 档 vintage 共 155 个读数里，只有 49 个是两端都有的区间。"
                 "更关键的是它们<b>什么时候</b>是区间："
                 "年初、Q1、Q2 三档各有 15–17 个区间，而到了 Q3 那一档 —— 也就是结算这一年的那一档，"
                 "发布时全年已过去约十个月 —— 35 个读数里只剩 1 个还是区间。"
                 "<b>不确定性最小的时候，指引反而卸掉了上界。</b>"
                 "这跟「预测随时间收敛到答案」正好相反，也是本页不把命中率当结论的原因："
                 "对着一个下限说「从没跌破」，接近同义反复。"),
        "src_extra": SOURCE_6K,
    }


def guidance_band(ref: str, record: dict, metric: str, *, fmt: str, ylab: str,
                  unit: str, extra_note: str = "") -> dict:
    """One guided metric's own vintages against the year that settled them."""
    item = record["items"][metric]
    labels = record["vintages"]
    tally: dict[str, int] = {}
    for low, high, form, actual in zip(item["lo"], item["hi"], item["form"], item["actual"]):
        if actual is None or low is None:
            continue
        result = verdict(low, high, form, actual)
        tally[result] = tally.get(result, 0) + 1
    finished = sum(tally.values())
    words = {"above": "高于所给的数", "below": "低于所给的数", "inside": "落在区间内",
             "met": "与所给的数持平（在印刷精度内）", "within": "守住了上限",
             "exceeded": "越过了上限"}
    verdict_text = "、".join(f"{count} 年{words[key]}" for key, count in
                            sorted(tally.items(), key=lambda kv: -kv[1]))
    forms_used = [FORM_NAMES[f] for f in dict.fromkeys(f for f in item["form"] if f)]
    return {
        "ref": ref,
        "kind": "range_band",
        "title": f"{METRIC_NAMES[metric]}：{finished} 个已完结年度里，{verdict_text}",
        "xlabels": list(labels),
        "xrot": 90,
        "lo": list(item["lo"]),
        "hi": list(item["hi"]),
        "actual": list(item["actual"]),
        "actual_color": "NAVY",
        "names": {
            "range": f"公司{METRIC_NAMES[metric]}全年指引",
            "actual": f"全年实际{METRIC_NAMES[metric]}",
            "lo": f"指引下缘（{unit}）",
            "hi": f"指引上缘（{unit}）",
        },
        "fmt": fmt, "label_fmt": fmt, "ylab": ylab,
        "note": ("<b>每个财年占据连续的四格</b>：年初首次指引，然后 Q1、Q2、Q3 三次修订；"
                 "菱形只落在该年<b>最后</b>那一格上，因为那才是结算这一年的那一档。"
                 f"这条指引在窗口内用过的形状有：{'、'.join(forms_used)}。"
                 "<b>只给下限或只给单点时，色块没有宽度</b> —— 画成有宽度的区间等于替公司发明一个上界，"
                 f"所以那些格子是一条细线（见 Exhibit {{EX_FORM}}）。"
                 + extra_note
                 + "<b>时点必须说清楚</b>：四档分别发布于当年的 2 月、5 月、7–8 月与 10–11 月，"
                 "最后一档发出时全年已经过去约十个月，所以「结清」这个词在这里比在季度指引页上弱得多。"
                 "纵轴不自 0 起，但没有任何点被截掉。"),
        "src_extra": SOURCE_6K,
    }


def convergence_chart(record: dict) -> dict:
    """Deviation of each finished year from EVERY one of its four vintages."""
    slots = ["initial", "q1", "q2", "q3"]
    years = sorted({fy for fy, actual in zip(record["fiscal_years"],
                                             record["items"]["adj_eps"]["actual"])
                    if actual is not None})
    settled = {}
    for index, actual in enumerate(record["items"]["adj_eps"]["actual"]):
        if actual is not None:
            settled[record["fiscal_years"][index]] = actual
    series = {slot: [] for slot in slots}
    for year in years:
        actual = settled[year]
        for slot in slots:
            value = None
            for index, (fy, sl) in enumerate(zip(record["fiscal_years"],
                                                 record["vintage_slots"])):
                if fy == year and sl == slot:
                    low = record["items"]["adj_eps"]["lo"][index]
                    high = record["items"]["adj_eps"]["hi"][index]
                    if low is not None:
                        value = (actual / ((low + high) / 2) - 1) * 100
                    break
            series[slot].append(value)
    opening = [v for v in series["initial"] if v is not None]
    final = [v for v in series["q3"] if v is not None]
    open_abs = statistics.fmean(abs(v) for v in opening)
    final_abs = statistics.fmean(abs(v) for v in final)
    beaten = sum(1 for v in opening if v > 0)
    missed = [f"FY{years[i]}" for i, v in enumerate(series["initial"])
              if v is not None and v < 0]
    return {
        "ref": "EX_CONVERGE",
        "kind": "grouped_bars",
        "title": (f"调整后摊薄 EPS 相对<b>每一档</b>指引中值的偏离："
                  f"年初那一档 {len(opening)} 年里 {beaten} 年偏正，"
                  f"平均绝对偏离从 {open_abs:.1f}% 收敛到 {final_abs:.1f}%"),
        "xlabels": [f"FY{year}" for year in years],
        "groups": [
            {"name": "vs 年初首次指引", "color": "NAVY", "values": rounded(series["initial"])},
            {"name": "vs Q1 修订", "color": "BLUE", "values": rounded(series["q1"])},
            {"name": "vs Q2 修订", "color": "GOLD", "values": rounded(series["q2"])},
            {"name": "vs Q3 修订", "color": "RED", "values": rounded(series["q3"])},
        ],
        "bar_labels": False,
        "fmt": "pct1", "label_fmt": "pct1",
        "ylab": "% vs 该档指引中值",
        "note": ("<b>这张图问的是区间图问不了的那个问题：这一年在年初就知道了多少。</b>"
                 "每年四根柱子，是最终实际值相对该年四档指引中值的偏离；"
                 "柱子从左到右变矮，就是这一年的不确定性被逐季消掉的过程。"
                 f"平均绝对偏离从 {open_abs:.1f}% 收到 {final_abs:.1f}%，约 "
                 f"{open_abs / final_abs:.1f} 倍。"
                 + (f"年初那一档 {len(opening)} 年里有 {beaten} 年被最终结果超过，"
                    f"唯一低于年初指引的是 {missed[0]} —— 那一年公司在 5 月把全年收入指引从"
                    "「> €4.1B」下调到「€3.4–3.6B」，是这段记录里唯一一次下修。"
                    if missed else "")
                 + "把它和上面几张区间图并排看：区间图说的是「有没有兑现」，"
                   "这张说的是「兑现得多容易」。"),
        "src_extra": SOURCE_6K + "偏离为实际值 ÷ 该档指引中值 − 1，本页自算（D）。",
    }


def guidance_charts(staging: dict) -> tuple[list[dict], list[dict]]:
    record = staging["annual_guidance_history"]
    charts = [
        form_chart(record),
        guidance_band("EX_EBITDA", record, "adj_ebitda", fmt="f2", ylab="€B", unit="€B",
                      extra_note=("这条指引在 FY2019–FY2023 的年初都是两端区间，"
                                  "而这五年<b>没有一年是以区间收尾的</b> —— "
                                  "全部在 Q3 那一档变成单点或下限；FY2024 起连年初那一档也不再给区间。")),
        guidance_band("EX_EPS", record, "adj_eps", fmt="f2", ylab="€/股", unit="€",
                      extra_note=("公司指引的是<b>调整后</b>摊薄 EPS，所以这里的实际值也取调整后口径。"
                                  "两者在多数年份相同，但 FY2020 不同：报告口径 €3.28、调整后 €2.88，"
                                  "拿报告值去结算一个按调整口径给出的指引，会凭空造出一次 14% 的超预期。")),
        guidance_band("EX_IFCF", record, "ifcf", fmt="f2", ylab="€B", unit="€B",
                      extra_note=("这条是五条里最松的一条：见 Exhibit {EX_CONVERGE} 的口径，"
                                  "工业自由现金流即便到了 Q3 那一档，离最终结果仍有两位数的百分比。")),
        convergence_chart(record),
    ]
    labels = record["vintages"]
    rows = []
    for index, label in enumerate(labels):
        cells = [label, record["release_dates"][index]]
        for metric in ["revenue", "adj_ebitda", "adj_ebit", "adj_eps", "ifcf"]:
            item = record["items"][metric]
            low, high, form = item["lo"][index], item["hi"][index], item["form"][index]
            if low is None:
                cells.append("—")
            elif form == "range":
                cells.append(f"{low:g}–{high:g}")
            else:
                mark = {"floor": "≥", "ceiling": "≤", "point": "~"}[form]
                cells.append(f"{mark}{high:g}")
        actual = record["items"]["adj_eps"]["actual"][index]
        cells.append("本档结算" if actual is not None else "")
        rows.append(cells)
    tables = [{
        "title": "全年指引的 31 档 vintage 原值（€B，EPS 为 €/股）",
        "headers": ["vintage", "发布日", "净收入", "调整后 EBITDA", "调整后 EBIT",
                    "调整后摊薄 EPS", "工业自由现金流", "结算档"],
        "rows": rows,
    }]
    return charts, tables


# ── section two: what moved this quarter ─────────────────────────────────────
def quarter_charts(staging: dict) -> list[dict]:
    fin = staging["financials"]
    labels = staging["periods"]
    long = staging["long_history"]
    ebit_margin = fin["ebit_margin_pct"]
    ebitda_margin = fin["ebitda_margin_pct"]
    da = fin["da_eur_m"]
    implied = 188.0

    wedge = {
        "ref": "EX_WEDGE",
        "kind": "lines",
        "title": (f"EBIT 利润率创纪录 {ebit_margin[-1]:.1f}%，"
                  f"同一季 EBITDA 利润率却环比 "
                  f"{signed(ebitda_margin[-1] - ebitda_margin[-2], 1, 'pp')}"),
        "xlabels": labels,
        "series": [
            {"name": "EBIT 利润率", "values": rounded(ebit_margin), "color": "NAVY"},
            {"name": "EBITDA 利润率", "values": rounded(ebitda_margin), "color": "BLUE"},
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
        "ylab": "%",
        "note": ("<b>两条线背离本身就是答案。</b>本季 EBIT 利润率环比 "
                 f"{signed(ebit_margin[-1] - ebit_margin[-2], 1, 'pp')}，"
                 f"EBITDA 利润率却 {signed(ebitda_margin[-1] - ebitda_margin[-2], 1, 'pp')} —— "
                 "两者之间只隔着折旧摊销一项，所以这次的利润率纪录发生在折旧线<b>以下</b>，"
                 f"不是折旧线以上的经营改善。当季 D&A 为 €{da[-1]:,.0f}M，"
                 f"是窗口内最低的一季，比上一季低 {abs(pct_change(da[-1], da[-2])):.1f}%（见 Exhibit {{EX_DA}}）。"),
        "src_extra": ("利润率为 EBIT ÷ 净收入、EBITDA ÷ 净收入，本页自算（D）；"
                      "两个分子与分母都是业绩新闻稿的披露值。"
                      "36 个公司自己印出利润率的季度里，自算值与印刷值最大差 0.14pp，即印刷精度本身。"),
    }

    da_chart = {
        "ref": "EX_DA",
        "kind": "lines",
        "title": (f"季度 D&A：本季 €{da[-1]:,.0f}M 是窗口低点，"
                  f"而全年指引隐含的下半年季均是 €{implied:,.0f}M"),
        "xlabels": labels,
        "series": [
            {"name": "季度 D&A", "values": rounded(da), "color": "NAVY"},
            {"name": "全年指引隐含的 H2 季均", "values": [implied] * len(labels), "color": "RED"},
        ],
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c", "end_label": True,
        "ylab": "€M",
        "note": ("红线不是公司给的季度指引 —— 公司不给季度指引。它是两个披露值相减："
                 "管理层在本季电话会上首次把全年 D&A 量化为「超过 €700M」，"
                 f"减去上半年实际的 €{da[-2] + da[-1]:,.0f}M，下半年就得 > €376M，季均 ≥ €{implied:,.0f}M。"
                 f"这个数并不陌生：2025 年第四季的实际 D&A 就是 €{long['da_eur_m'][long['quarters'].index('Q4 2025')]:,.0f}M。"
                 "换句话说下半年的「台阶」只是回到两个季度前出现过的水平，"
                 "而本季的低点才是这条序列里的异常。"),
        "src_extra": ("D&A 为各季业绩新闻稿 EBITDA 还原表的披露值；"
                      "隐含季均由公司全年口径与上半年实际相减得到，本页自算（D）。"),
    }

    regions = [("shipments_emea", "EMEA", "NAVY"),
               ("shipments_americas", "美洲", "BLUE"),
               ("shipments_china_hk_taiwan", "中国大陆、香港与台湾", "GOLD"),
               ("shipments_rest_of_apac", "亚太其余", "RED")]
    americas = fin["shipments_americas"]
    emea = fin["shipments_emea"]
    region_chart = {
        "ref": "EX_REGION",
        "kind": "grouped_bars",
        "title": (f"分地区出货：美洲同比 {signed(pct_change(americas[-1], americas[-5]))}，"
                  f"EMEA 同比 {signed(pct_change(emea[-1], emea[-5]))}"),
        "xlabels": labels,
        "groups": [{"name": name, "color": color, "values": rounded(fin[key], 0)}
                   for key, name, color in regions],
        "fmt": "f0c", "label_fmt": "f0c", "ylab": "台",
        "note": ("<b>法拉利按地区披露的是台数，不是收入</b>，所以地域分析只能做量的对比，"
                 "地域结构对利润的影响无法从申报里拆出来。"
                 f"本季美洲 {americas[-1]:,.0f} 台、同比 {signed(pct_change(americas[-1], americas[-5]))}，"
                 f"占比从一年前的 {americas[-5] / fin['shipments_units'][-5] * 100:.1f}% 降到 "
                 f"{americas[-1] / fin['shipments_units'][-1] * 100:.1f}%；"
                 "EMEA 是本季唯一同比正增长的地区。四个地区相加等于总出货，42 个季度逐季核对无差。"),
        "src_extra": "各季业绩新闻稿的 Shipments 表；地区口径由公司在同一份文件的脚注中定义。",
    }

    ship = fin["shipments_units"]
    per_unit = fin["cars_revenue_per_unit_eur_k"]
    unit_chart = {
        "ref": "EX_UNIT",
        "kind": "bar_line_dual",
        "title": (f"量与价：出货同比 {signed(pct_change(ship[-1], ship[-5]))}，"
                  f"单台车与零件收入同比 {signed(pct_change(per_unit[-1], per_unit[-5]))}"),
        "xlabels": labels,
        "bar": {"name": "出货（台）", "values": rounded(ship, 0), "color": "BLUE"},
        "line": {"name": "单台车与零件收入（€千）", "values": rounded(per_unit, 1),
                 "color": "RED", "yfmt": "f0c"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "台", "ylab2": "€千/台",
        "note": ("单台收入是 Cars and spare parts 收入 ÷ 出货台数，两个都是披露值，"
                 "相除是本页自算（D）。<b>它不是 ASP</b>：分子含零件与个性化，"
                 "分母只含整车，而公司明确表示永不披露车型级的出货与售价。"
                 "本季这两条走反方向 —— 台数下降而单台收入上升 —— 是这家公司近年的常态，"
                 f"完整的四十二季版本见 Exhibit {{EX_L_UNIT}}。"),
        "src_extra": "出货与 Cars and spare parts 收入均取自各季业绩新闻稿；比值为本页自算（D）。",
    }

    legs = [("cars_and_spare_parts_eur_m", "Cars and spare parts", "NAVY"),
            ("sponsorship_commercial_brand_eur_m", "Sponsorship, commercial and brand", "BLUE"),
            ("other_revenues_eur_m", "Other", "GOLD")]
    cars = fin["cars_and_spare_parts_eur_m"]
    other = fin["other_revenues_eur_m"]
    mix_chart = {
        "ref": "EX_MIX",
        "kind": "grouped_bars",
        "title": (f"三条收入腿：Cars and spare parts 同比 {signed(pct_change(cars[-1], cars[-5]))}，"
                  f"Other 同比 {signed(pct_change(other[-1], other[-5]))}"),
        "xlabels": labels,
        "groups": [{"name": name, "color": color, "values": rounded(fin[key], 0)}
                   for key, name, color in legs],
        "fmt": "f0c", "label_fmt": "f0c", "ylab": "€M",
        "note": ("三条腿相加等于合并净收入，42 个季度逐季核对无差。"
                 "Other 这一条本季增速最快，主因是向其他一级方程式车队出租引擎；"
                 "它同时也是口径变过的一条 —— 2024 年起公司把原先单列的 Engines 收入并入 Other，"
                 f"并重述了 2023 年可比数，所以长序列在那一季断开（见 Exhibit {{EX_L_MIX}}）。"),
        "src_extra": "各季业绩新闻稿的 Total net revenues 表。",
    }
    return [wedge, da_chart, region_chart, unit_chart, mix_chart]


# ── section three: what to watch next ────────────────────────────────────────
def next_quarter_charts(staging: dict) -> list[dict]:
    kpi = staging["next_kpi"]["quantified"]
    long = staging["long_history"]
    labels = staging["periods"]
    fin = staging["financials"]
    exhibits = [headroom_exhibit(
        f"下季 {len(kpi)} 条阈值：当前值离阈值的余量",
        kpi, "current",
        ("正值表示仍在安全侧。阈值为本地研究设定，<b>不是公司指引</b> —— "
         "法拉利只给全年指引，从不给季度指引。"
         "<b>D&A 那根柱子为负是设计使然，不是已经出事</b>："
         "它的阈值是全年指引隐含的下半年季均，本季读数低于它正是本页要说的那件事。"
         + staging["next_kpi"]["excluded"]),
        "当前值为 2026Q2 披露值或其自算比值；阈值为本地研究设定。")]

    americas = long["shipments_americas"]
    quarters = long["quarters"]
    yoy = [None if index < 4 else pct_change(americas[index], americas[index - 4])
           for index in range(len(americas))]
    window = 16
    exhibits.append(threshold_exhibit(
        f"EBIT 利润率：当前 {fin['ebit_margin_pct'][-1]:.2f}%，阈值 28.00%",
        labels, rounded(fin["ebit_margin_pct"]), 28.0,
        fmt="pct1", ylab="%",
        actual_name="EBIT 利润率", threshold_name="本地阈值",
        note=("红线是本地研究设定的撤回线，取 2025 年第三季的实际读数附近 —— "
              "低于它就不能再把下半年的降档只解释成折旧节奏。"
              "公司全年指引隐含的下半年利润率是 29.0%，比这条红线高一档，"
              "两者的差就是本页留给「成本节奏」与「结构退潮」之间的判别区间。"),
        src_extra="EBIT 与净收入为披露值，利润率为本页自算（D）；阈值为本地研究设定。"))

    exhibits.append(threshold_exhibit(
        f"单季 D&A：当前 €{fin['da_eur_m'][-1]:,.0f}M，阈值 €188M",
        labels, rounded(fin["da_eur_m"]), 188.0,
        fmt="f0c", ylab="€M",
        actual_name="季度 D&A", threshold_name="全年指引隐含的 H2 季均",
        note=("这条与上一条必须配对读：单看利润率会被折旧节奏骗，"
              "单看 D&A 又不构成投资判断。红线是公司全年口径减去上半年实际得到的隐含季均，"
              "不是公司给的季度指引。"),
        src_extra="D&A 为披露值；隐含季均为本页自算（D）。"))

    exhibits.append(threshold_exhibit(
        f"美洲出货同比：当前 {yoy[-1]:.1f}%，阈值 −15.0%",
        quarters[-window:], rounded(yoy[-window:]), -15.0,
        fmt="pct1", ylab="同比 %",
        actual_name="美洲出货同比", threshold_name="本地阈值",
        note=("公司把本季美洲的下滑解释为换代排产与「近市场先供」。"
              "这条线不能证伪那个解释，但它能把它变成可检验的："
              "如果是排产，随后的季度应当回补；如果同比降幅继续深于红线，"
              "就要按区域结构性再配置来建模。序列从有同比可算的那一季起画。"),
        src_extra="出货为披露值，同比为本页自算（D）；阈值为本地研究设定。"))
    exhibits[-1]["xstep"] = 2
    return exhibits


# ── section four: the long routine series ────────────────────────────────────
def long_charts(staging: dict) -> list[dict]:
    long = staging["long_history"]
    quarters = long["quarters"]
    ship = long["shipments_units"]
    per_unit = long["cars_revenue_per_unit_eur_k"]
    ebit_margin = long["ebit_margin_pct"]
    ebitda_margin = long["ebitda_margin_pct"]

    unit = {
        "ref": "EX_L_UNIT",
        "kind": "bar_line_dual",
        "title": (f"四十二季的量与价：出货从 {ship[0]:,.0f} 台到 {ship[-1]:,.0f} 台，"
                  f"单台车与零件收入从 €{per_unit[0]:,.0f}千 到 €{per_unit[-1]:,.0f}千"),
        "xlabels": quarters,
        "bar": {"name": "出货（台）", "values": rounded(ship, 0), "color": "BLUE"},
        "line": {"name": "单台车与零件收入（€千）", "values": rounded(per_unit, 1),
                 "color": "RED", "yfmt": "f0c"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "台", "ylab2": "€千/台", "xstep": LONG_STEP,
        "note": ("<b>这张图是这家公司的整个股权故事，八个季度看不出来。</b>"
                 f"十年半里出货只涨了 {ship[-1] / ship[0]:.2f} 倍，"
                 f"而每台车带来的车与零件收入涨了 {per_unit[-1] / per_unit[0]:.2f} 倍 —— "
                 "增长几乎全部来自单台价值而不是台数。"
                 "2020 年第二季那个坑是七周停产，不是需求。"
                 "单台收入不是 ASP：分子含零件与个性化，分母只含整车。"),
        "src_extra": "出货与 Cars and spare parts 收入取自 42 份季度业绩新闻稿；比值为本页自算（D）。",
    }

    margin = {
        "ref": "EX_L_MARGIN",
        "kind": "lines",
        "title": (f"四十二季利润率：EBIT 从 {ebit_margin[0]:.1f}% 到 {ebit_margin[-1]:.1f}%，"
                  f"EBITDA 从 {ebitda_margin[0]:.1f}% 到 {ebitda_margin[-1]:.1f}%"),
        "xlabels": quarters,
        "series": [
            {"name": "EBIT 利润率", "values": rounded(ebit_margin), "color": "NAVY"},
            {"name": "EBITDA 利润率", "values": rounded(ebitda_margin), "color": "BLUE"},
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
        "ylab": "%", "xstep": LONG_STEP,
        "note": ("两条线之间的距离就是折旧摊销占收入的比重，"
                 "它在这段记录里先收窄后走阔 —— 换代年的资本化研发陆续进入摊销是主因。"
                 "这两条画的是<b>报告口径</b>：2016 年有非经常调整项（Q2 与 Q4 两季 adjusted 高于 reported），"
                 "2017 年以后公司每份新闻稿都写明「adjusted 等于 reported」，"
                 "所以整段用报告口径既连续又与公司口径一致；"
                 "全年指引的结算另用调整口径，两者不混。"),
        "src_extra": "EBIT、EBITDA 与净收入为披露值，利润率为本页自算（D）。",
    }

    engines = long["engines_eur_m"]
    break_at = next((index for index, value in enumerate(engines)
                     if value is None and index > 0 and engines[index - 1] is not None), None)
    mix = {
        "ref": "EX_L_MIX",
        "kind": "grouped_bars",
        "title": "四十二季收入结构：Engines 这一行在 2024 年被并进 Other",
        "xlabels": quarters,
        "groups": [
            {"name": "Cars and spare parts", "color": "NAVY",
             "values": rounded(long["cars_and_spare_parts_eur_m"], 0)},
            {"name": "Sponsorship, commercial and brand", "color": "BLUE",
             "values": rounded(long["sponsorship_commercial_brand_eur_m"], 0)},
            {"name": "Other", "color": "GOLD", "values": rounded(long["other_revenues_eur_m"], 0)},
            {"name": "Engines（2024 年起并入 Other）", "color": "RED", "values": rounded(engines, 0)},
        ],
        "bar_labels": False,
        "fmt": "f0c", "label_fmt": "f0c", "ylab": "€M", "xstep": LONG_STEP,
        "note": ("<b>Engines 那一行是断的，不是归零的。</b>公司自 2024 年起把向 Maserati 售发动机的"
                 "剩余收入并入 Other，并在同一份新闻稿里重述了 2023 年的可比数；"
                 "本页把它留成空档而不是补零，因为补零会把一次列报变更画成一次业务消失。"
                 "四条腿在 2024 年之前相加等于合并净收入，之后前三条相加等于合并净收入，"
                 "42 个季度逐季核对无差。"),
        "src_extra": "各季业绩新闻稿的 Total net revenues 表；并表说明见 2024 年各期新闻稿脚注。",
    }
    if break_at is not None:
        mix["break_at"] = break_at
        mix["break_label"] = "Engines 并入 Other"

    china = long["shipments_china_hk_taiwan"]
    peak_index = china.index(max(china))
    region = {
        "ref": "EX_L_REGION",
        "kind": "lines",
        "title": ("四十二季分地区出货：中国大陆、香港与台湾在 42 个季度里都是四个地区中最小的一个，"
                  f"本季 {china[-1]:,.0f} 台、占 {china[-1] / long['shipments_units'][-1] * 100:.1f}%，"
                  f"而 {quarters[peak_index]} 曾是 {china[peak_index]:,.0f} 台、占 "
                  f"{china[peak_index] / long['shipments_units'][peak_index] * 100:.1f}%"),
        "xlabels": quarters,
        "series": [
            {"name": "EMEA", "values": rounded(long["shipments_emea"], 0), "color": "NAVY"},
            {"name": "美洲", "values": rounded(long["shipments_americas"], 0), "color": "BLUE"},
            {"name": "中国大陆、香港与台湾", "values": rounded(long["shipments_china_hk_taiwan"], 0),
             "color": "GOLD"},
            {"name": "亚太其余", "values": rounded(long["shipments_rest_of_apac"], 0), "color": "RED"},
        ],
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c", "end_label": True,
        "ylab": "台", "xstep": LONG_STEP,
        "note": ("四条线里最值得看的是最低那条。大中华区在这 42 个季度里<b>每一季</b>都是四个地区中"
                 "最小的一个，这跟多数奢侈品公司的中国曲线是反的。"
                 "<b>要分清台数与占比</b>：以台数论，本季比 2016 年第一季还多"
                 f"（{china[-1]:,.0f} 对 {china[0]:,.0f} 台）；以占比论则从 "
                 f"{china[0] / long['shipments_units'][0] * 100:.1f}% 降到 "
                 f"{china[-1] / long['shipments_units'][-1] * 100:.1f}%。"
                 f"真正的落差是相对自己的高点：{quarters[peak_index]} 的 {china[peak_index]:,.0f} 台"
                 f"是这条线的峰值，本季只有它的 {china[-1] / china[peak_index] * 100:.0f}%。"
                 "公司对此的口径是按订单先后交付、不按地域调配额。"
                 "地区名称在窗口内改过两次（Greater China → China, Hong Kong and Taiwan → "
                 "Mainland China, Hong Kong and Taiwan），口径未变，本页按同一条线画。"),
        "src_extra": "各季业绩新闻稿的 Shipments 表。",
    }

    ifcf = long["industrial_fcf_eur_m"]
    nid = long["net_industrial_debt_eur_m"]
    cash = {
        "ref": "EX_L_CASH",
        "kind": "bar_line_dual",
        "title": (f"四十二季工业自由现金流与净工业头寸：本季 IFCF €{ifcf[-1]:,.0f}M，"
                  f"期末净工业{'负债' if nid[-1] < 0 else '现金'} €{abs(nid[-1]):,.0f}M"),
        "xlabels": quarters,
        "bar": {"name": "季度工业自由现金流", "values": rounded(ifcf, 0), "color": "BLUE"},
        "line": {"name": "期末净工业（负债）/现金", "values": rounded(nid, 0),
                 "color": "RED", "yfmt": "f0c"},
        "fmt": "f0c", "yfmt": "f0c", "label_fmt": "f0c",
        "ylab": "€M", "ylab2": "€M", "xstep": LONG_STEP,
        "note": ("净工业负债是负数表示净负债、正数表示净现金。"
                 "两条线放在一起才看得出这家公司的资本配置："
                 "现金流逐年抬高，而净工业头寸始终在零附近来回 —— "
                 "多出来的现金没有留在资产负债表上，也没有变成产能，而是以股息与回购发了出去。"
                 "季度 IFCF 有强季节性（第二季通常最低），跨年比较要同季对同季。"),
        "src_extra": "工业自由现金流与净工业（负债）/现金均为各季业绩新闻稿的披露值。",
    }

    capex = long["capex_eur_m"]
    first = next(index for index, value in enumerate(capex) if value is not None)
    capex_chart = {
        "ref": "EX_L_CAPEX",
        "kind": "grouped_bars",
        "title": (f"资本开支与其中的资本化研发：本季 €{capex[-1]:,.0f}M，"
                  f"占收入 {capex[-1] / long['net_revenues_eur_m'][-1] * 100:.1f}%"),
        "xlabels": quarters[first:],
        "groups": [
            {"name": "资本开支", "color": "NAVY", "values": rounded(capex[first:], 0)},
            {"name": "其中：资本化研发", "color": "GOLD",
             "values": rounded(long["capitalised_development_eur_m"][first:], 0)},
        ],
        "bar_labels": False,
        "fmt": "f0c", "label_fmt": "f0c", "ylab": "€M", "xstep": LONG_STEP,
        "note": (f"<b>这条序列从 {quarters[first]} 起画，不向前回补</b> —— "
                 "业绩新闻稿是从那一期才开始印 Capex and R&D 表的，更早的季度这个数不存在。"
                 "资本化研发是资本开支里最大的一块，也是几年后折旧线上那一步的来源，"
                 f"所以它和 Exhibit {{EX_DA}} 是同一件事的两端。"),
        "src_extra": "各季业绩新闻稿的 Capex and R&D 表；资本开支不含 IFRS 16 使用权资产。",
    }
    return [unit, margin, mix, region, cash, capex_chart]


def build_payload(staging: dict) -> dict:
    fin = staging["financials"]
    long = staging["long_history"]
    labels = staging["periods"]
    record = staging["annual_guidance_history"]

    settled, settled_tables = guidance_charts(staging)
    highlights = quarter_charts(staging)
    next_block = next_quarter_charts(staging)
    routine = long_charts(staging)

    exhibits = number_exhibits(settled + highlights + next_block + routine)
    resolve_exhibit_refs(exhibits)
    n_settled, n_high, n_next = len(settled), len(highlights), len(next_block)
    settled_ex = exhibits[:n_settled]
    highlight_ex = exhibits[n_settled:n_settled + n_high]
    next_ex = exhibits[n_settled + n_high:n_settled + n_high + n_next]
    routine_ex = exhibits[n_settled + n_high + n_next:]

    first_table = exhibits[-1]["n"] + 1
    tables = [{**table, "n": first_table + index}
              for index, table in enumerate(settled_tables)]
    tables.append({
        "n": first_table + len(settled_tables),
        "title": "近八季合并损益与经营指标（公司披露值，除标注外）",
        "headers": ["期间", "出货（台）", "净收入", "Cars and spare parts", "EBITDA",
                    "EBIT", "EBIT 利润率 D", "D&A", "净利润", "摊薄 EPS",
                    "资本开支", "工业自由现金流", "净工业（负债）/现金"],
        "rows": [[labels[i], f"{fin['shipments_units'][i]:,.0f}",
                  f"€{fin['net_revenues_eur_m'][i]:,.0f}M",
                  f"€{fin['cars_and_spare_parts_eur_m'][i]:,.0f}M",
                  f"€{fin['ebitda_eur_m'][i]:,.0f}M",
                  f"€{fin['ebit_eur_m'][i]:,.0f}M",
                  f"{fin['ebit_margin_pct'][i]:.1f}%",
                  f"€{fin['da_eur_m'][i]:,.0f}M",
                  f"€{fin['net_profit_eur_m'][i]:,.0f}M",
                  f"€{fin['diluted_eps_eur'][i]:.2f}",
                  f"€{fin['capex_eur_m'][i]:,.0f}M",
                  f"€{fin['industrial_fcf_eur_m'][i]:,.0f}M",
                  f"€{fin['net_industrial_debt_eur_m'][i]:,.0f}M"]
                 for i in range(len(labels))],
    })
    tables.append(threshold_table(first_table + len(settled_tables) + 1,
                                  "下季阈值与当前值（原始单位）",
                                  staging["next_kpi"]["quantified"], "current", "当前值"))
    tables.append(ai_capex_cycle_table(first_table + len(settled_tables) + 2))

    revenue = fin["net_revenues_eur_m"]
    ebit = fin["ebit_eur_m"]
    da = fin["da_eur_m"]
    ship = fin["shipments_units"]
    per_unit = fin["cars_revenue_per_unit_eur_k"]
    ifcf = fin["industrial_fcf_eur_m"]
    ranges_q3 = sum(1 for index, slot in enumerate(record["vintage_slots"])
                    if slot == "q3"
                    for metric in METRIC_NAMES
                    if record["items"][metric]["form"][index] == "range")
    q3_total = sum(1 for index, slot in enumerate(record["vintage_slots"])
                   if slot == "q3"
                   for metric in METRIC_NAMES
                   if record["items"][metric]["form"][index])

    return {
        "schema_version": "quarterly-dashboard/race-v1",
        "page": {"slug": "race", "language": "zh-CN"},
        "company": {
            "ticker": "RACE",
            "name": "Ferrari N.V.",
            "group": "luxury_brands",
            "accounting_standard": "IFRS",
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
        "tracker": "Watchlist Quarterly Tracker · RACE",
        "title": "Ferrari N.V. (RACE)：Q2 2026 季报仪表盘",
        "subtitle": ("截至 2026-06-30 · 发布 2026-07-30 · IFRS · 欧元列示 · 未审计 · "
                     "自然年财年，季度标注与财年一致 · 数据来自季度业绩 6-K 的 EX-99.1"),
        "headline": (
            f"净收入 €{revenue[-1]:,.0f}M、同比 {signed(pct_change(revenue[-1], revenue[-5]))}，"
            f"EBIT 利润率 {fin['ebit_margin_pct'][-1]:.1f}% 创窗口新高，"
            f"但同一季 EBITDA 利润率 {signed(fin['ebitda_margin_pct'][-1] - fin['ebitda_margin_pct'][-2], 1, 'pp')}，"
            f"两者之间只隔着 D&A —— 本季 €{da[-1]:,.0f}M 是窗口低点，"
            f"而全年指引隐含的下半年季均是 €188M；"
            f"出货同比 {signed(pct_change(ship[-1], ship[-5]))} 而单台车与零件收入同比 "
            f"{signed(pct_change(per_unit[-1], per_unit[-5]))}。"),
        "brief": (
            '<h4>本季三条主线</h4><div class="takeaway-grid">'
            '<article><span>记录</span><b>指引在最确定的时候卸掉上界</b>'
            f'<p>31 档 vintage 里，年初那一档有 15 个读数是两端区间；'
            f'结算全年的 Q3 那一档 {q3_total} 个读数里只剩 {ranges_q3} 个。'
            '对着下限说「从没跌破」接近同义反复，所以本页看的是超出多少。</p></article>'
            '<article><span>本季</span><b>纪录利润率发生在折旧线以下</b>'
            f'<p>EBIT 利润率 {fin["ebit_margin_pct"][-1]:.1f}% 创新高，EBITDA 利润率却下滑；'
            f'差额全部是 D&amp;A，本季 €{da[-1]:,.0f}M 为窗口低点。</p></article>'
            '<article><span>结构</span><b>十年半里量几乎没动，价翻了倍</b>'
            f'<p>出货 {long["shipments_units"][0]:,.0f} → {ship[-1]:,.0f} 台，'
            f'单台车与零件收入 €{long["cars_revenue_per_unit_eur_k"][0]:,.0f}千 → '
            f'€{per_unit[-1]:,.0f}千。</p></article>'
            '</div>'),
        "source": ('Source: <a href="https://www.sec.gov/Archives/edgar/data/1648416/'
                   '000164841626000106/fnvq22026results.htm" rel="noopener">'
                   'Ferrari 2026 年第二季度业绩新闻稿（6-K EX-99.1）</a>。'
                   '法拉利为外国私人发行人，不报 10-Q/10-K/8-K，年度申报为 20-F。'),
        "source_url": ("https://www.sec.gov/Archives/edgar/data/1648416/"
                       "000164841626000106/fnvq22026results.htm"),
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {"id": "settled", "title": "一、公司自己的指引兑现了吗",
             "description": ("法拉利只给全年指引，每季修订一次，而且给的大多不是区间，"
                             "是「至少」「不超过」「约」这样的单边不等式。"
                             "所以这一节先看指引的形状怎么随年份推进而变，再看七个已完结年度落在哪里。"),
             "exhibits": settled_ex},
            {"id": "quarter_highlights", "title": "二、本季重点",
             "description": "利润率与折旧的背离、分地区出货的分化，以及量与价这一季再次走反方向。",
             "exhibits": highlight_ex},
            {"id": "next_quarter", "title": "三、下季要跟踪什么",
             "description": "四条可从申报复算的阈值，统一用「距阈值余量」口径；公司结构性不披露的两条写在这里。",
             "exhibits": next_ex},
            {"id": "routine", "title": "四、长期常规跟踪",
             "description": "四十二个季度的量价结构、利润率、收入构成、地区出货、现金流与资本开支。",
             "exhibits": routine_ex},
        ],
        "tables": tables,
        "notes": [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "法拉利是外国私人发行人（foreign private issuer），不提交 10-Q、10-K 或 8-K：年度申报是 20-F，季度业绩只以 6-K 的 EX-99.1 新闻稿提交。本站其他公司页所依赖的 10-Q/10-K 渲染报表（R-files）对本公司不存在，本页 42 个季度的数据全部来自这 42 份新闻稿本身。",
            "报表采用 IFRS 并以欧元列示，是本站第一家两者皆非美国口径的公司。财年即自然年，季度标注与公司自己的口径一致，无需换算。",
            "2016 至 2018 年的第二、三季新闻稿把累计栏印在标签左侧、当季栏印在右侧，2019 年起两栏对调。按固定列序取值会把半年报与九个月的数字读成单季，而且四条恒等式全都照样成立（收入分项相加、地区相加、EBITDA 还原、EBIT 还原），因为各项是一起变成累计的。本页按每张表自己的期间表头判断，并以「四个季度相加等于公司印出的全年」作为最终检查：10 个财年 × 7 个指标共 70 项全部通过。",
            "全年指引表的指引列在 2018 至 2025 年各期都排在最右，2026 年起改排最左。按固定列序取值会把上一年的实际值当成本年指引，本页按表头逐期判断。",
            "公司指引的是调整后口径，本页结算也用调整后口径。2016 年有非经常调整项（第二、四季 adjusted 高于 reported），2020 年调整后摊薄 EPS 为 €2.88 而报告口径为 €3.28；长序列的利润率一律用报告口径，指引结算一律用调整口径，两者不混。2017 年起公司在每份新闻稿写明 adjusted 等于 reported。",
            "指引形状分为四类：两端区间、只给下限、只给上限、单点约数。只给下限或单点时图上的色块没有宽度，画成有宽度的区间等于替公司发明一个上界。判定「兑现」时对单点与下限留出等于印刷精度的容差：公司把 €1.27B 印到小数点后两位，FY2019 的 €1.269B 因此记为持平而不是跌破。",
            "全年指引的四档分别发布于当年的 2 月、5 月、7–8 月与 10–11 月，最后一档发出时全年已过去约十个月。因此「结清」在本页比在季度指引页上弱得多，本页对每张区间图都写明了这一点，并另画一张相对每一档指引的偏离图。",
            "Engines 收入自 2024 年起并入 Other，公司同时重述了 2023 年可比数。长序列在那一季断开并加标记，不补零 —— 补零会把一次列报变更画成一次业务消失。",
            "资本开支与资本化研发的序列自 2019 年第一季起，因为业绩新闻稿是从那一期才开始印 Capex and R&D 表的；不向前回补。",
            "单台车与零件收入为 Cars and spare parts 收入除以出货台数，是本页自算（D），不是 ASP：分子含零件与个性化收入，分母只含整车。公司已明确表示永不披露车型级的出货量与售价。",
            "地区披露的是出货台数而非收入，因此地域结构对收入与利润的影响无法从申报中拆出来，本页不做该拆分。",
            "本页不发布市场一致预期、评级、目标价与估值。第三节的阈值是本地研究设定，不是公司指引。",
            "本页只发布公司披露值与可复算的简单派生值；D 标记代表 Derived / 自算。自算的利润率与公司自己印出利润率的 36 个季度逐季比对，最大差 0.14pp，即印刷精度本身。",
            "核对抽屉最后那张「AI capex 循环」是全站共用的跨页对照块，在每一页都逐字节相同，不是对法拉利的判断。它追的是四家云厂现金资本开支 → NVDA 数据中心收入 → TSM 晶圆这条链，法拉利不在这条链的任何一环上。把它放在这里是为了让读者在任意一页都能查到同一份上下游对照；它在折叠的抽屉里，不参与本页的论证。",
            "本页已知未接入：个性化收入占比与订单簿覆盖年限（只在电话会上以定性口径出现，从未进入新闻稿或申报）、2027 年汇率对冲覆盖率（管理层仅称覆盖率低得多，未给数）、车型级出货与售价（公司明确永不披露）、恒定汇率口径的完整历史序列（公司只在近年新闻稿中逐期给出），以及 2026 年第三季度之后的任何数据（本页数据截至 2026-07-30 的申报）。",
            "业绩电话会内容仅用于定位公司已在新闻稿中量化的项目，公开仓不复制原件或逐字内容。",
        ],
        "footer": "Ferrari quarterly results · 数据来自 Ferrari 公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "race.js"), payload, "race")
    shell_dir = ROOT / "race"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("RACE", "race"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"RACE page: {charts} charts in {len(payload['sections'])} sections "
          f"+ {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
