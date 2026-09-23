"""Hermès International quarterly dashboard.

Hermès is the first company on this site that runs on **two clocks**. Revenue is
published every quarter, split seven ways by métier and six ways by region, with
the company's own constant-currency rate printed beside each cell. Everything
else -- the income statement, the cash flow statement, the balance sheet, the
segment note -- is published **twice a year**. There is no such thing as a
second-quarter margin, a second-quarter EPS or a second-quarter free cash flow
for this company; the half-year report's comparative balance sheet is not even
the prior June, it is the prior December.

So this page does not put profit on a quarterly axis. The revenue exhibits run
on the quarter window and the profit exhibits run on their own half-year axis,
and every profit chart says 「半年」 in its title and its axis label, because the
two clocks sit on one page and a reader scrolling past cannot otherwise tell
which one a chart is on.

**And the guidance record has a shape no other page here carries.** Its entire
Outlook section, in every release held here since 2021Q1, is one sentence:

    In the medium-term, despite the economic, geopolitical and monetary
    uncertainties around the world, the group confirms an ambitious goal for
    revenue growth at constant exchange rates.

Word for word, zero numbers. There is nothing to settle, so this page does not
report a hit rate. What it settles instead is the one pair of numbers the
company does publish every quarter -- the published growth rate and the
constant-currency one -- and the wedge between them.

**A roll edits `series/rms.json` and nothing else** (CLAUDE.md §9). Every period
label, count and figure is computed from the series, and every sentence that
states something the data could stop saying (「唯一负增长」「全部落在」「每一次都」
「一路分开」) is printed only while the data says it. What belongs to one quarter
-- the call's quotes and refusals, the next thresholds, the numbers said on the
call -- lives in blocks stamped with the quarter (`next_kpi`, `quasi_guidance`,
`quarter_story`); what belongs to the half-year report -- its income statement,
its segment note, the half's cumulative revenue table and the reading of them --
lives in blocks stamped with the half (`h1_income`, `h1_segments`, `first_half`,
`half_story`). A block stamped for another period stops the build; a missing one
drops the charts and sentences that need it. Numbers a story sentence mentions
that the series already carries are placeholders filled by `board.fill_story`.

Where the company printed a margin the page also computes and the two round
differently -- H1 2026: 3,351 / 8,163 = 41.05%, printed 41.0% -- the page prints
the company's. Published numbers are company-reported or transparent
arithmetic. Thresholds in the tracking section are local research settings,
not company guidance.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.board import (  # noqa: E402
    ai_capex_cycle_table,
    cn_count,
    cn_fraction,
    cn_ordinal,
    fill_story,
    headroom as headroom_value,
    headroom_exhibit,
    latest_block,
    minus_sign,
    number_exhibits,
    stamped_block,
    threshold_exhibit,
    threshold_table,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "rms.json"
DATA_DIR = ROOT / "data"

SECTOR_ORDER = ["leather_goods_saddlery", "ready_to_wear_accessories", "silk_textiles",
                "other_hermes_sectors", "perfume_beauty", "watches", "other_products"]
REGION_ORDER = ["france", "europe_ex_france", "japan", "asia_pacific_ex_japan",
                "americas", "other_middle_east"]
SERIES_COLORS = ["NAVY", "MBLUE", "BLUE", "GOLD", "RED", "GREEN", "GRAY"]
# The short names the prose uses once the full label has been printed.
SECTOR_SHORT = {"leather_goods_saddlery": "皮具", "ready_to_wear_accessories": "成衣",
                "silk_textiles": "丝绸", "other_hermes_sectors": "其他爱马仕板块",
                "perfume_beauty": "香水", "watches": "钟表", "other_products": "其他产品"}
REGION_SHORT = {"france": "法国", "europe_ex_france": "欧洲（除法国）", "japan": "日本",
                "asia_pacific_ex_japan": "亚太（除日本）", "americas": "美洲",
                "other_middle_east": "中东"}
AUDIT_WORDS = {"limited_review": "半年度报告经有限审阅", "audited": "年度报告经审计",
               "unaudited": "收入公告未经审阅"}

SOURCE_QUARTER = ("各季数值逐字取自公司当期公告自己印出的单季表："
                  "第一、三季度取季度收入公告，第二季度取半年度业绩新闻稿，"
                  "第四季度取全年业绩新闻稿。固定汇率增速一律取该表印出的那一列。")
SOURCE_HALF = ("上半年数值取半年度财务报告与半年度业绩新闻稿；"
               "下半年为公司申报的全年减去公司申报的上半年（D），公司本身不单独披露下半年。")
AXIS = "纵轴不自 0 起，但没有任何点被截掉。"


def euro_cell(row: dict, field: str) -> str:
    """A euro amount, or an em dash where the backfill has no reading for it.

    The half-year window now reaches 2016, and the adjusted free-cash-flow line
    was not collected that far back -- it is a company-defined measure the early
    releases do not print. An absent cell prints as a dash rather than
    disappearing into a zero.
    """
    value = row.get(field)
    return "—" if value is None else f"€{value:,}M"


def pct_or_dash(value: float | None) -> str:
    """A rate, or an em dash where the company printed an amount and no rate."""
    return "—" if value is None else f"{value:.1f}%"


def rated_quarters(staging: dict) -> list[int]:
    """Indices of the quarters that carry a published *and* a constant-currency rate.

    The revenue window reaches back further than the rate window: the 2016
    quarters arrive as the prior-year column of the 2017 releases, which prints
    the euro amount and not the growth beside it. Every census, extreme and
    ranking below runs over these indices, so a sentence about "every quarter"
    means every quarter that could have carried the thing it is counting.
    """
    group = staging["group_revenue"]
    return [i for i in range(len(staging["periods"]))
            if group["published_pct"][i] is not None and group["cc_pct"][i] is not None]


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def rounded(values, digits: int = 6):
    """Round for the payload so a rebuild is idempotent, keeping ``None`` holes.

    Six places, never the display precision. The renderer rounds again when it
    formats, so a value stored at the precision it is printed at can move a
    digit on that second pass: this page published 香水与美妆's share of the
    quarter's constant-currency increment as −4.3% when the figure is −4.3527%,
    because the builder had already flattened it to −4.35 and `pct1` then took
    it down rather than up.
    """
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


def cc_increments(block: dict, order: list[str], index: int) -> tuple[dict, float]:
    """Each line's euro contribution to the group's constant-currency growth.

    A constant-currency rate is a percentage of that line's own prior-year base,
    so the rates cannot be averaged or compared for size directly -- Silk grew
    12.2% on €192M and Leather Goods 10.2% on €1,765M. Weighting each rate by
    the prior-year column the company prints beside it turns seven percentages
    into seven euro amounts that add up, which is the only form in which
    「哪个板块在推动集团」 has an answer.
    """
    increments = {key: block[key]["prior_year_eur_m"][index] * block[key]["cc_pct"][index] / 100
                  for key in order}
    return increments, sum(increments.values())


# ── periods and words ────────────────────────────────────────────────────────
def quarter_parts(period: str) -> tuple[int, int]:
    """``Q2 2026`` -> (2026, 2)."""
    return int(period[-4:]), int(period[1])


def quarter_cn(period: str) -> str:
    """``Q1 2026`` -> ``2026 年第一季``."""
    year, number = quarter_parts(period)
    return f"{year} 年第{cn_ordinal(number)}季"


def closes_half(period: str, half: str) -> bool:
    year, number = quarter_parts(period)
    return number in (2, 4) and half == f"H{number // 2} {year}"


def tenths(share: float) -> str:
    """A share of a whole in 「成」: 39.9 -> 「四成」, 69.3 -> 「近七成」."""
    n = round(share / 10)
    return f"{cn_count(n)}成" if abs(share - n * 10) < 0.5 else (
        f"近{cn_count(n)}成" if share < n * 10 else f"超过{cn_count(n)}成")


def near(value: float) -> str:
    """5.6 -> 「近 6%」: the whole number a reader would say."""
    n = round(value)
    return f"{'近' if value < n else '超过' if value > n else ''} {n}%".strip()


def official_margin(half: dict) -> float:
    """The half's margin as the company printed it, where the recomputation rounds differently."""
    printed = half.get("roi_margin_printed_pct")
    if printed is not None and round(half["roi_margin_pct"], 1) != printed:
        return printed
    return half["roi_margin_pct"]


def margin_cell(half: dict) -> str:
    """A half's margin in the audit table: recomputed to two places, or the company's figure.

    Where the company printed the half's margin and the recomputation from the
    two rounded amounts rounds to a different tenth, the cell carries the
    printed one and says so (H1 2026: 3,351 / 8,163 would print 41.05%).
    """
    official = official_margin(half)
    if official != half["roi_margin_pct"]:
        return f"{official:.1f}%（公司印）"
    return f"{half['roi_margin_pct']:.2f}%"


def release_quarter(label: str) -> tuple[int, int]:
    """The last quarter a release in `outlook.releases` covers.

    ``Q1 2021 收入公告`` -> (2021, 1); ``2025 半年度业绩`` -> (2025, 2);
    ``2024 全年业绩`` -> (2024, 4).
    """
    if label.startswith("Q"):
        return quarter_parts(label.split()[0] + " " + label.split()[1])
    year = int(label[:4])
    if "半年" in label:
        return year, 2
    if "全年" in label:
        return year, 4
    raise ValueError(f"outlook release label names no period: {label}")


def release_prefix(period: str) -> str:
    """The label a quarter's own release carries in `sources`."""
    year, number = quarter_parts(period)
    return {1: f"Q1 {year} 收入公告", 2: f"{year} 半年度业绩新闻稿",
            3: f"Q3 {year} 收入公告", 4: f"{year} 全年业绩新闻稿"}[number]


def story_values(staging: dict) -> dict[str, str]:
    """The computed numbers a story sentence may name (see `board.fill_story`)."""
    latest = len(staging["periods"]) - 1
    values = {}
    for key, block in staging["by_sector"].items():
        values[f"now:{key}"] = signed(block["cc_pct"][latest])
    increments, total = cc_increments(staging["by_sector"], SECTOR_ORDER, latest)
    for key in SECTOR_ORDER:
        values[f"share_words:{key}"] = tenths(increments[key] / total * 100)
    return values


def base_pair(sectors: dict, latest: int) -> tuple[str, str]:
    """The two métiers that show why rates cannot be compared for size.

    The line that carried the most constant-currency euros, and the fastest line
    that grew faster than it on a smaller base (Q2 2026: Silk +12.2% on €192M
    against Leather Goods +10.2% on €1,765M). With no such line, the smallest
    base stands in for it.
    """
    increments, _ = cc_increments(sectors, SECTOR_ORDER, latest)
    lead = max(SECTOR_ORDER, key=lambda k: increments[k])
    faster = [k for k in SECTOR_ORDER if k != lead
              and sectors[k]["cc_pct"][latest] > sectors[lead]["cc_pct"][latest]
              and sectors[k]["prior_year_eur_m"][latest] < sectors[lead]["prior_year_eur_m"][latest]]
    if faster:
        return max(faster, key=lambda k: sectors[k]["cc_pct"][latest]), lead
    return min(SECTOR_ORDER, key=lambda k: sectors[k]["prior_year_eur_m"][latest]), lead


def second_quarter_by_subtraction(staging: dict, first_half: dict | None, half: str) -> list[tuple] | None:
    """What 「半年减第一季」 would give for each second-quarter cell, beside what was printed.

    The half's constant-currency revenue less the first quarter's, over the
    half's prior-year base less the first quarter's. Every input is printed to
    one decimal or to the million, so the result carries their rounding; the
    page never uses it, it only measures how far it strays.
    """
    if first_half is None or not half.startswith("H1"):
        return None
    periods = staging["periods"]
    year = half.split()[1]
    if f"Q1 {year}" not in periods or f"Q2 {year}" not in periods:
        return None
    q1, q2 = periods.index(f"Q1 {year}"), periods.index(f"Q2 {year}")
    rows = []
    for kind, order, short in (("by_sector", SECTOR_ORDER, SECTOR_SHORT), ("by_region", REGION_ORDER, REGION_SHORT)):
        for key in order:
            cumulative, quarterly = first_half[kind][key], staging[kind][key]
            base = cumulative["prior_year_eur_m"] - quarterly["prior_year_eur_m"][q1]
            at_cc = (cumulative["prior_year_eur_m"] * (1 + cumulative["cc_pct"] / 100)
                     - quarterly["prior_year_eur_m"][q1] * (1 + quarterly["cc_pct"][q1] / 100))
            rows.append((short[key], quarterly["cc_pct"][q2], (at_cc / base - 1) * 100))
    return rows


# ── section one: what the company actually publishes ─────────────────────────
def outlook_charts(staging: dict, story: dict | None) -> list[dict]:
    periods = staging["periods"]
    n = len(periods)
    group = staging["group_revenue"]
    published = group["published_pct"]
    cc = group["cc_pct"]
    # The window reaches further back than the rates do: the 2016 quarters are
    # in this file as the prior-year column of the 2017 releases, which prints
    # the euro amount and not the growth. Everything below therefore runs over
    # the quarters that actually carry both rates, and the prose counts those
    # rather than the window, so a sentence cannot claim a span the lines do
    # not cover.
    rated = rated_quarters(staging)
    wedge = [None if published[i] is None or cc[i] is None else published[i] - cc[i]
             for i in range(n)]
    worst = min(rated, key=lambda i: wedge[i])
    peak = max(rated, key=lambda i: wedge[i])
    diverging = (peak < worst
                 and all(wedge[j] < wedge[i] for i, j in zip(rated, rated[1:])
                         if peak <= i and j <= worst))

    flips_group = [i for i in rated if published[i] < 0 < cc[i]]
    rates_note = ("<b>这两条线是这家公司每季度唯一给出的可结算数字，而它们不是同一件事。</b>"
                  "published 是读者在标题里看到的那个数，固定汇率是公司自己按上期平均汇率重算的那个数。")
    if diverging and wedge[peak] > 0:
        rates_note += (f"{cn_count(len(rated))}个季度里两条线一路分开：{periods[peak]} 时 published 还比固定汇率高 "
                       f"{signed(wedge[peak], 1, 'pp')}，到 {periods[worst]} 已经低了 "
                       f"{abs(wedge[worst]):.1f}pp。")
    if flips_group:
        i = flips_group[0]
        rates_note += (f"红线在 {quarter_cn(periods[i])}<b>转负</b>，而同一季蓝线是 {signed(cc[i])} —— "
                       f"同一家公司、同一个季度，一个口径说收入在萎缩，另一个说它增长了{near(cc[i])}。")
    rates_note += AXIS
    two_rates = {
        "ref": "EX_RATES",
        "kind": "lines",
        "title": (f"公司每季给出的两个增速：published {signed(published[-1])} 对固定汇率 "
                  f"{signed(cc[-1])}；"
                  + ("这是窗口里两者差得最远的一季" if worst == n - 1 else
                     f"{periods[worst]} 是两者差得最远的一季（{signed(published[worst])} 对 {signed(cc[worst])}）")),
        "xlabels": list(periods),
        "series": [
            {"name": "published（按当期汇率）", "values": rounded(published), "color": "RED"},
            {"name": "固定汇率（cc）", "values": rounded(cc), "color": "NAVY"},
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
        "ylab": "同比 %",
        "note": rates_note,
        "src_extra": SOURCE_QUARTER,
    }

    narrowed = abs(wedge[-1]) < abs(wedge[-2])
    wedge_note = ("这张图只是把 Exhibit {EX_RATES} 的两条线相减，但它回答的问题不同："
                  "<b>不是「增长了多少」，而是「你读到的那个数有多少不是经营」</b>。")
    if diverging and wedge[peak] > 0 and all(v < 0 for v in wedge[peak + 1:worst + 1]):
        wedge_note += (f"{quarter_cn(periods[peak])}汇率还在帮忙（{signed(wedge[peak], 1, 'pp')}），"
                       f"此后连续{cn_count(worst - peak)}个季度转为拖累并逐季加深，"
                       f"到 {periods[worst]} 达到 {abs(wedge[worst]):.1f}pp。")
    year, number = quarter_parts(periods[-1])
    year_ago = f"Q{number} {year - 1}"
    first_half = stamped_block(staging, "first_half", staging["half_years"][-1]["label"])
    if story and narrowed and year_ago in periods and first_half is not None:
        half_wedge = first_half["group"]["published_pct"] - first_half["group"]["cc_pct"]
        wedge_note += fill_story(story["wedge_reading"], {
            "wedge_now": f"{abs(wedge[-1]):.1f}",
            "year_ago_quarter": f"第{cn_ordinal(number)}季",
            "wedge_year_ago": minus_sign(f"{wedge[periods.index(year_ago)]:+.1f}"),
            "half_wedge": f"{abs(half_wedge):.1f}",
        })
    wedge_chart = {
        "ref": "EX_WEDGE",
        "kind": "diverging_bars",
        "title": (f"汇率把标题增速抬高或压低了多少：{cn_count(n)}季从 {signed(wedge[min(peak, worst)], 1, 'pp')} 走到"
                  + (f"本季的 {signed(wedge[worst], 1, 'pp')}" if worst == n - 1 else
                     f" {signed(wedge[max(peak, worst)], 1, 'pp')}，本季{'收窄到' if narrowed else '为'} "
                     f"{signed(wedge[-1], 1, 'pp')}")),
        "xlabels": list(periods),
        "values": rounded(wedge),
        "legend": "published 减固定汇率",
        "positive_label": "汇率抬高了标题增速",
        "negative_label": "汇率压低了标题增速",
        "fmt": "pp1", "yfmt": "pp1", "label_fmt": "pp1",
        "ylab": "pp",
        "zero_line": True,
        "note": wedge_note,
        "src_extra": SOURCE_QUARTER,
    }

    regions = staging["by_region"]
    latest = n - 1
    # Same rule as the group lines above: only the quarters that carry both
    # rates are in the census, so the denominator the note prints is the number
    # of cells that could have flipped, not the number of cells on the axis.
    flips = [(periods[i], block["label"], block["published_pct"][i], block["cc_pct"][i], key)
             for key, block in regions.items()
             for i in rated
             if block["published_pct"][i] * block["cc_pct"][i] < 0]
    gap = {k: regions[k]["cc_pct"][latest] - regions[k]["published_pct"][latest] for k in REGION_ORDER}
    focus = max(REGION_ORDER, key=lambda k: abs(gap[k]))
    f_pub, f_cc = regions[focus]["published_pct"][latest], regions[focus]["cc_pct"][latest]
    rank = sorted(REGION_ORDER, key=lambda k: -regions[k]["cc_pct"][latest]).index(focus) + 1
    title = (f"本季{cn_count(len(REGION_ORDER))}个地区的两个口径：{regions[focus]['label']} published {signed(f_pub)}"
             f"、固定汇率 {signed(f_cc)}")
    if f_pub < 0 < f_cc:
        title += ("，一个口径说它在萎缩，另一个说它是"
                  + ("全集团最快" if rank == 1 else
                     f"{cn_count(len(REGION_ORDER))}个地区里增长第{cn_ordinal(rank)}快的"))
    same = [k for k in REGION_ORDER if regions[k]["published_pct"][latest] == regions[k]["cc_pct"][latest]]
    flip_regions = {key for *_, key in flips}
    region_note = ""
    if "france" in same:
        region_note += "法国两根柱一样高 —— 本币计价，没有汇率可换算；"
    region_note += (f"{regions[focus]['label']}两根柱差 {abs(gap[focus]):.1f}pp，是全表最大的一格。"
                    f"把窗口拉到{cn_count(len(rated))}个印出增速的季度、"
                    f"{cn_count(len(REGION_ORDER))}个地区共 "
                    f"{len(rated) * len(REGION_ORDER)} 格，其中 <b>{len(flips)} 格的两个口径符号相反</b>")
    if flips:
        region_note += ("：" + "、".join(f"{p} 的{label}（{signed(a)} 对 {signed(b)}）"
                                        for p, label, a, b, _ in flips) + "。")
        if flip_regions == {"japan", "asia_pacific_ex_japan"}:
            region_note += (f"这{cn_count(len(flips))}格全部落在日本与亚太（除日本），也就是本页最需要判断需求方向的两个地区 —— "
                            "读错口径不是读小了一点，是把方向读反。")
    else:
        region_note += "。"
    regions_chart = {
        "ref": "EX_REGION_RATES",
        "kind": "grouped_bars",
        "title": title,
        "xlabels": [regions[key]["label"] for key in REGION_ORDER],
        "xrot": 45,
        "groups": [
            {"name": "published（按当期汇率）", "color": "RED",
             "values": [regions[key]["published_pct"][latest] for key in REGION_ORDER]},
            {"name": "固定汇率（cc）", "color": "NAVY",
             "values": [regions[key]["cc_pct"][latest] for key in REGION_ORDER]},
        ],
        "bar_labels": True,
        "fmt": "pct1", "label_fmt": "pct1",
        "ylab": "同比 %",
        "note": region_note,
        "src_extra": SOURCE_QUARTER,
    }
    return [two_rates, wedge_chart, regions_chart]


# ── section two: the quarter, which exists only at the revenue line ──────────
def quarter_charts(staging: dict, story: dict | None) -> list[dict]:
    rated = rated_quarters(staging)
    periods = staging["periods"]
    n = len(periods)
    latest = n - 1
    sectors = staging["by_sector"]
    regions = staging["by_region"]
    group = staging["group_revenue"]

    def pct(value: float) -> str:
        return minus_sign(signed(value))

    deltas = {key: sectors[key]["cc_pct"][latest] - sectors[key]["cc_pct"][latest - 1]
              for key in SECTOR_ORDER}
    accelerating = [k for k in SECTOR_ORDER if deltas[k] > 0]
    biggest_drop = min(SECTOR_ORDER, key=lambda k: deltas[k])
    # How much of the acceleration is the base rather than the quarter: a line
    # whose previous reading was the low of the whole window has an easier
    # comparison than one that accelerated from mid-range. Counted rather than
    # asserted -- the sentence that used to say "three of the four" was typed by
    # hand and was wrong by one.
    off_the_low = [k for k in accelerating
                   if sectors[k]["cc_pct"][latest - 1] == min(sectors[k]["cc_pct"][i] for i in rated)]
    negative_now = [k for k in SECTOR_ORDER if sectors[k]["cc_pct"][latest] < 0]
    k_acc = cn_count(len(accelerating))
    pace_note = ""
    together = len(accelerating) >= 2
    if accelerating:
        pace_note += ((f"<b>{k_acc}个板块同时加速，" if together else
                       f"<b>{cn_count(len(SECTOR_ORDER))}个板块里只有{SECTOR_SHORT[accelerating[0]]}在加速，")
                      + (story["pace_story"] if story else "")).rstrip("，")
        pace_note += ("</b>" if story else "。</b>")
        pace_note += ("，".join(f"{SECTOR_SHORT[k]}从 {pct(sectors[k]['cc_pct'][latest - 1])} 到 "
                               f"{pct(sectors[k]['cc_pct'][latest])}" for k in accelerating) + "。")
        if off_the_low:
            pace_note += ((f"但这{k_acc}条里有 {len(off_the_low)} 条" if together else "但它")
                          + f"（{'、'.join(sectors[k]['label'] for k in off_the_low)}）"
                          "的上季读数正好是本窗口的低点，即加速有一部分来自比较基数"
                          + (f" —— {story['base_quote']}" if story else "") + "。")
    if negative_now == [biggest_drop]:
        pace_note += (f"另一侧同样要写出来：{sectors[biggest_drop]['label']}是{cn_count(len(SECTOR_ORDER))}个板块里唯一负增长的一个，"
                      f"环比掉了 {abs(deltas[biggest_drop]):.1f}pp"
                      + (f"，{story['unexplained_drop']}" if story else "") + "。")
    sector_pace = {
        "ref": "EX_SECTOR_PACE",
        "kind": "grouped_bars",
        "title": (f"{cn_count(len(SECTOR_ORDER))}个板块的环比加减速（固定汇率）：{len(accelerating)} 个在加速"
                  + (f"，而减速最深的{sectors[biggest_drop]['label']}掉了 {abs(deltas[biggest_drop]):.1f}pp"
                     if deltas[biggest_drop] < 0 else "")),
        "xlabels": [sectors[key]["label"] for key in SECTOR_ORDER],
        "xrot": 45,
        "groups": [
            {"name": f"{periods[latest - 1]} 固定汇率", "color": "BLUE",
             "values": [sectors[key]["cc_pct"][latest - 1] for key in SECTOR_ORDER]},
            {"name": f"{periods[latest]} 固定汇率", "color": "NAVY",
             "values": [sectors[key]["cc_pct"][latest] for key in SECTOR_ORDER]},
        ],
        "bar_labels": True,
        "fmt": "pct1", "label_fmt": "pct1",
        "ylab": "同比 %（固定汇率）",
        "note": pace_note,
        "src_extra": SOURCE_QUARTER,
    }

    increments, total = cc_increments(sectors, SECTOR_ORDER, latest)
    lead = max(SECTOR_ORDER, key=lambda k: increments[k])
    share = {key: increments[key] / total * 100 for key in SECTOR_ORDER}
    weight = {key: sectors[key]["revenue_eur_m"][latest] / group["revenue_eur_m"][latest] * 100
              for key in SECTOR_ORDER}
    top_down = group["prior_year_eur_m"][latest] * group["cc_pct"][latest] / 100
    small, _ = base_pair(sectors, latest)
    faster = [small] if (sectors[small]["cc_pct"][latest] > sectors[lead]["cc_pct"][latest]
                         and sectors[small]["prior_year_eur_m"][latest] < sectors[lead]["prior_year_eur_m"][latest]) else []
    negative = [k for k in SECTOR_ORDER if increments[k] < 0]
    mix_note = ("<b>这张图是本页对「增长有多集中」的全部证据，也是本站少见的一种自算：</b>"
                "把每个板块公司印出的固定汇率增速乘以它自己印出的上年同期收入，"
                f"得到 {len(SECTOR_ORDER)} 个可相加的欧元增量，合计 €{total:.0f}M；"
                f"用集团口径复核是 €{top_down:.0f}M，"
                + ("两者相差不到 1%，差额是各行四舍五入。" if abs(total / top_down - 1) < 0.01 else
                   f"两者相差 {abs(total / top_down - 1) * 100:.1f}%。"))
    if faster:
        ex = faster[0]
        mix_note += (f"不能直接比增速大小 —— {SECTOR_SHORT[ex]} {signed(sectors[ex]['cc_pct'][latest])} 比"
                     f"{SECTOR_SHORT[lead]} {signed(sectors[lead]['cc_pct'][latest])} 高，但它的基数只有"
                     f"{SECTOR_SHORT[lead]}的"
                     f"{cn_fraction(sectors[ex]['prior_year_eur_m'][latest] / sectors[lead]['prior_year_eur_m'][latest])}。")
    if share[lead] > 50:
        mix_note += (f"<b>{SECTOR_SHORT[lead]}一个板块顶掉了{tenths(share[lead])}的增量"
                     + ("，而" + "、".join(SECTOR_SHORT[k] for k in negative) + "是负贡献" if negative else "")
                     + "</b>；换句话说集团的增长现在压在一条腿上，这条腿每一次小幅不及预期都会被放大。")
    sector_mix = {
        "ref": "EX_SECTOR_MIX",
        "kind": "grouped_bars",
        "title": (f"占收入与占增量不是一回事：{sectors[lead]['label']}占本季收入 "
                  f"{weight[lead]:.1f}%，却贡献了固定汇率增量的 {share[lead]:.1f}%"),
        "xlabels": [sectors[key]["label"] for key in SECTOR_ORDER],
        "xrot": 45,
        "groups": [
            {"name": "占本季收入", "color": "BLUE",
             "values": rounded([weight[key] for key in SECTOR_ORDER])},
            {"name": "占本季固定汇率增量", "color": "NAVY",
             "values": rounded([share[key] for key in SECTOR_ORDER])},
        ],
        "bar_labels": True,
        "fmt": "pct1", "label_fmt": "pct1",
        "ylab": "占比 %",
        "note": mix_note,
        "src_extra": SOURCE_QUARTER + "（增量权重为本页自算 D）",
    }

    r_inc, r_total = cc_increments(regions, REGION_ORDER, latest)
    r_share = {key: r_inc[key] / r_total * 100 for key in REGION_ORDER}
    r_weight = {key: regions[key]["revenue_eur_m"][latest] / group["revenue_eur_m"][latest] * 100
                for key in REGION_ORDER}
    engine = max(REGION_ORDER, key=lambda k: r_inc[k])
    biggest = max(REGION_ORDER, key=lambda k: r_weight[k])
    flipped = r_share[engine] > r_weight[engine] and r_share[biggest] < r_weight[biggest]
    region_note = ("<b>两根柱的高低关系整个反了过来，这就是本季最值得记住的一格。</b>" if flipped else "")
    half = staging["half_years"][-1]["label"]
    segments = stamped_block(staging, "h1_segments", half)
    first_half = stamped_block(staging, "first_half", half)
    if engine != biggest and r_share[biggest] < r_share[engine] / 2:
        top_profit = (segments is not None and
                      max((r for r in segments["rows"] if r["key"] != "unallocated"),
                          key=lambda r: r["roi_now"])["key"] == biggest)
        region_note += (f"{regions[biggest]['label']}是集团最大的一块收入"
                        + ("，也是上半年分部经常性经营利润里最大的一块" if top_profit else "")
                        + f"，但它贡献的增量还不到{regions[engine]['label']}的一半；"
                        f"{regions[engine]['label']}用{cn_fraction(r_weight[engine] / 100)}的收入顶起了"
                        f"{tenths(r_share[engine])}的增量。")
    if first_half is not None and closes_half(periods[-1], half):
        h1_rows = first_half["by_region"]
        h1_inc = {k: h1_rows[k]["prior_year_eur_m"] * h1_rows[k]["cc_pct"] / 100 for k in REGION_ORDER}
        h1_share = h1_inc[engine] / sum(h1_inc.values()) * 100
        g = first_half["group"]
        without = (g["prior_year_eur_m"] * g["cc_pct"] / 100 - h1_inc[engine]) / g["prior_year_eur_m"] * 100
        region_note += (f"按上半年累计口径算，这个数是 {h1_share:.1f}% —— "
                        f"<b>抽掉{regions[engine]['label']}，集团上半年的固定汇率增速会从 {signed(g['cc_pct'])} "
                        f"{'掉' if without < g['cc_pct'] else '升'}到 {signed(without)}</b>"
                        f"（本页自算 D：把{regions[engine]['label']}的增量从合计里剔除后除以上年同期收入）。")
    r_delta = {k: regions[k]["cc_pct"][latest] - regions[k]["cc_pct"][latest - 1] for k in REGION_ORDER}
    if min(REGION_ORDER, key=r_delta.get) == engine and r_delta[engine] < 0:
        region_note += (f"而{regions[engine]['label']}自己已经从上季的 {signed(regions[engine]['cc_pct'][latest - 1])} "
                        f"减速到 {signed(regions[engine]['cc_pct'][latest])}，"
                        f"是{cn_count(len(REGION_ORDER))}个地区里减速最快的一个。")
        if story:
            region_note += story["region_moral"]
    region_mix = {
        "ref": "EX_REGION_MIX",
        "kind": "grouped_bars",
        "title": (f"同一张图换成地区：{regions[engine]['label']}占收入 {r_weight[engine]:.1f}%、"
                  f"贡献增量 {r_share[engine]:.1f}%，而最大的{regions[biggest]['label']}"
                  f"占收入 {r_weight[biggest]:.1f}%、只贡献 {r_share[biggest]:.1f}%"),
        "xlabels": [regions[key]["label"] for key in REGION_ORDER],
        "xrot": 45,
        "groups": [
            {"name": "占本季收入", "color": "BLUE",
             "values": rounded([r_weight[key] for key in REGION_ORDER])},
            {"name": "占本季固定汇率增量", "color": "NAVY",
             "values": rounded([r_share[key] for key in REGION_ORDER])},
        ],
        "bar_labels": True,
        "fmt": "pct1", "label_fmt": "pct1",
        "ylab": "占比 %",
        "note": region_note,
        "src_extra": SOURCE_QUARTER + "（增量权重为本页自算 D）",
    }

    peak = max(rated, key=lambda i: group["cc_pct"][i])
    double_digit = [k for k in SECTOR_ORDER if sectors[k]["cc_pct"][peak] >= 10.0]
    lowest = [k for k in SECTOR_ORDER
              if k in sorted(SECTOR_ORDER, key=lambda key: sectors[key]["cc_pct"][peak])[:2]]
    stepped_down = peak + 1 < n and all(sectors[k]["cc_pct"][peak + 1] < sectors[k]["cc_pct"][peak]
                                        for k in SECTOR_ORDER)
    watches = sectors["watches"]["cc_pct"]
    watch_positive = sum(1 for v in watches[-4:] if v > 0)
    deep = [(periods[i], v) for i, v in enumerate(watches[:n // 2])
            if v is not None and v <= -10]
    consecutive = len(deep) >= 2 and all(periods.index(b[0]) == periods.index(a[0]) + 1
                                         for a, b in zip(deep, deep[1:]))
    trend_note = ""
    if stepped_down:
        trend_note += (f"{periods[peak]} 那一格是本窗口的顶：{cn_count(len(SECTOR_ORDER))}条线里有 "
                       f"{len(double_digit)} 条在两位数以上"
                       f"（最低的两条是{sectors[lowest[0]]['label']} {sectors[lowest[0]]['cc_pct'][peak]:.1f}% 与"
                       f"{sectors[lowest[1]]['label']} {sectors[lowest[1]]['cc_pct'][peak]:.1f}%），"
                       "此后一起下台阶" + (" —— " if together else "。"))
        if together:
            trend_note += (f"所以本季的「{k_acc}个板块同时加速」要放在这个背景里读："
                           "<b>是从低位反弹，不是回到原来的斜率</b>。")
    watch_weight = sectors["watches"]["revenue_eur_m"][latest] / group["revenue_eur_m"][latest] * 100
    if deep:
        trend_note += ("钟表那条线的形状最值得单独看：窗口前段"
                       + ("是连续的两位数负增长" if consecutive else
                          f"{cn_count(len(deep))}度出现两位数负增长（"
                          + "、".join(f"{p} {pct(v)}" for p, v in deep) + "）")
                       + f"，最近四季里有 {watch_positive} 季为正"
                       + ("但仍在正负之间来回" if 0 < watch_positive < 4 else "")
                       + f"，而它只有集团收入的 {watch_weight:.1f}%，对集团的贡献停在 {share['watches']:.1f}%。")
    if len(negative_now) == 1 and sectors[negative_now[0]]["cc_pct"][latest] < sectors[negative_now[0]]["cc_pct"][latest - 1]:
        trend_note += f"{sectors[negative_now[0]]['label']}是唯一一条本季仍在零以下并且还在下探的线。"
    trend_note += AXIS
    sector_trend = {
        "ref": "EX_SECTOR_TREND",
        "kind": "lines",
        "title": (f"{cn_count(n)}季{cn_count(len(SECTOR_ORDER))}个板块的固定汇率增速"
                  + (f"：唯一没有回到正区间的是{sectors[negative_now[0]]['label']}" if len(negative_now) == 1 else "")),
        "xlabels": list(periods),
        "series": [
            {"name": sectors[key]["label"], "values": rounded(sectors[key]["cc_pct"]),
             "color": SERIES_COLORS[i]}
            for i, key in enumerate(SECTOR_ORDER)
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1", "end_label": True,
        "ylab": "同比 %（固定汇率）",
        "note": trend_note,
        "src_extra": SOURCE_QUARTER,
    }
    return [sector_pace, sector_mix, region_mix, sector_trend]


# ── section three: the other clock ───────────────────────────────────────────
def half_year_charts(staging: dict, hstory: dict | None, period: str) -> list[dict]:
    halves = {h["label"]: h for h in staging["half_years"]}
    latest_half = staging["half_years"][-1]
    years = sorted({h["label"].split()[1] for h in staging["half_years"]})
    first = [official_margin(halves[f"H1 {y}"]) if f"H1 {y}" in halves else None for y in years]
    second = [halves[f"H2 {y}"]["roi_margin_pct"] if f"H2 {y}" in halves else None for y in years]
    complete = [(y, f, s) for y, f, s in zip(years, first, second) if f is not None and s is not None]
    gaps = [f - s for _, f, s in complete]
    every = bool(gaps) and all(g > 0 for g in gaps)
    narrowing = len(gaps) >= 2 and gaps[-1] < gaps[0]
    # No markup in a title: the card prints it as HTML, but the same string is
    # the chart's SVG aria-label, where a screen reader gets the literal `<b>`.
    title = f"半年经常性经营利润率：{years[0]}–{years[-1]} 年的上半年与下半年"
    if every:
        title += (f"：上半年在{cn_count(len(gaps))}个完整年度里每一次都高于下半年，落差从 {gaps[0]:.2f}pp "
                  f"{'收窄' if narrowing else '变'}到 {gaps[-1]:.2f}pp")
    note = "<b>横轴是年份，每个点是一个半年，不是一个季度 —— 这家公司不存在季度利润率。</b>"
    h1_now = official_margin(latest_half)
    if latest_half["label"].startswith("H1") and every:
        mean = sum(gaps) / len(gaps)
        note += (f"上半年 {h1_now:.1f}% 被广泛引用为「这家公司的利润率」，"
                 f"但它是季节性偏强的那一半：{cn_count(len(gaps))}个完整年度里上半年每次都高于下半年，"
                 f"落差依次是 {'、'.join(f'{g:.2f}pp' for g in gaps)}。"
                 f"把这条落差套到本年：若重复 {complete[-1][0]} 年的 {gaps[-1]:.2f}pp，全年落在 "
                 f"{h1_now - gaps[-1] / 2:.1f}% 附近；若重复{cn_count(len(gaps))}年平均的 {mean:.2f}pp，"
                 f"全年落在 {h1_now - mean / 2:.1f}% 附近。"
                 "<b>这个区间不是预测，是把已发生的季节性原样搬过来的算术</b>，"
                 f"它的作用是说明「上半年 {h1_now:.1f}%」本身不构成全年 {h1_now:.0f}% 的证据。")
    elif every:
        note += (f"{cn_count(len(gaps))}个完整年度里上半年每次都高于下半年，"
                 f"落差依次是 {'、'.join(f'{g:.2f}pp' for g in gaps)}。")
    note += "下半年为公司申报全年减公司申报上半年，公司不单独披露下半年。" + AXIS
    seasonality = {
        "ref": "EX_HALF_MARGIN",
        "kind": "lines",
        "title": title,
        "xlabels": years,
        "series": [
            {"name": "上半年（公司披露）", "values": rounded(first), "color": "NAVY"},
            {"name": "下半年（全年减上半年 D）", "values": rounded(second), "color": "GOLD"},
        ],
        "fmt": "pct2", "yfmt": "pct1", "label_fmt": "pct2", "end_label": True,
        "ylab": "半年经常性经营利润率 %",
        "note": note,
        "src_extra": SOURCE_HALF,
    }
    charts = [seasonality]

    income = stamped_block(staging, "h1_income", latest_half["label"])
    segments = stamped_block(staging, "h1_segments", latest_half["label"])
    year = latest_half["label"].split()[1]
    prior_label = f"H1 {int(year) - 1}"
    if income is not None:
        lines = {key: (cur, prior) for key, _, cur, prior in income["lines"]}
        detail = {key: (cur, prior) for key, _, cur, prior in income["other_detail"]}
        rev_now, rev_before = lines["revenue"]

        def share_delta(now: float, before: float) -> float:
            """One line's contribution in percentage points of revenue."""
            return now / rev_now * 100 - before / rev_before * 100

        # Every expense line is stored with the sign the income statement prints it
        # with, so a single subtraction gives the contribution in the right
        # direction -- a cost that grew faster than revenue comes out negative.
        gross = share_delta(*lines["gross_margin"])
        sga = share_delta(*lines["sga"])
        da = share_delta(*detail["da"])
        impair = share_delta(*detail["impairment"])
        free_share = share_delta(*detail["free_share_plans"])
        start = lines["recurring_operating_income"][1] / rev_before * 100
        end = lines["recurring_operating_income"][0] / rev_now * 100
        residual = (end - start) - (gross + sga + da + impair + free_share)
        legs = [gross, sga, da, impair, free_share, residual]
        cost_now, cost_before = lines["cost_of_sales"]
        impair_now, impair_before = detail["impairment"]
        free_now, free_before = detail["free_share_plans"]
        printed_start = official_margin(halves[prior_label]) if prior_label in halves else start
        printed_end = official_margin(latest_half)
        # The endpoints are the margins the company printed; the legs are
        # recomputed from the income statement to the million, and their net is
        # what they add to.
        bridge_title = (f"上半年经常性经营利润率 {printed_start:.1f}% → {printed_end:.1f}%："
                        f"按科目重算净{'降' if end < start else '升'} {signed(end - start, 2, 'pp')}")
        inside = {"折旧与摊销": da, "减值损失": impair, "免费股计划费用": free_share}
        if min(inside, key=inside.get) == "减值损失" and impair < 0:
            bridge_title += f"，其中减值一项就是 {signed(impair, 2, 'pp')}"
        note = ""
        if cost_now == cost_before and gross > 0:
            note += ("<b>「汇率压毛利」这条最常见的叙述在这家公司身上不成立。</b>"
                     "上半年销货成本的绝对额与去年同期<b>一分未涨</b>"
                     f"（€{abs(cost_now):,}M 对 €{abs(cost_before):,}M），"
                     f"毛利率反而扩张 {signed(gross, 2, 'pp')}。")
        else:
            note += (f"上半年销货成本从 €{abs(cost_before):,}M 到 €{abs(cost_now):,}M，"
                     f"毛利率变动 {signed(gross, 2, 'pp')}。")
        if abs(gross + sga) < 0.05:
            note += (f"<b>头两根柱几乎正好抵消</b>：毛利率 {signed(gross, 2, 'pp')} 对销售及管理费用 "
                     f"{signed(sga, 2, 'pp')}，净额只有 {signed(gross + sga, 2, 'pp')}。")
        if end < start and abs(gross + sga) < 0.05 and min(inside, key=inside.get) == "减值损失":
            note += (f"所以这 {abs(end - start):.2f}pp 的净降幅实际上整个落在「其他收支」这一行里，"
                     f"而那一行里最大的一项既不是广告也不是折旧，是<b>减值损失</b>："
                     f"从 €{abs(impair_before)}M 涨到 €{abs(impair_now)}M，单项 {signed(impair, 2, 'pp')}，"
                     f"占 {abs(end - start):.2f}pp 净降幅的 "
                     f"{abs(impair / (end - start)) * 100:.0f}%。")
            if hstory:
                note += hstory["impairment_use"]
        if free_share > 0:
            note += (f"反方向的一项也要写出来：免费股计划费用从 €{abs(free_before)}M 降到 €{abs(free_now)}M，贡献 "
                     f"{signed(free_share, 2, 'pp')}" + (f"，{hstory['share_price']}" if hstory else "。"))
        note += ("最后一格是把计提准备净变动、其他收支净额与合并报表的印刷舍入并在一起，"
                 "让六项相加恰好等于净变动。")
        charts.append({
            "ref": "EX_MARGIN_BRIDGE",
            "kind": "bridge_bar",
            "title": bridge_title,
            "xlabels": ["毛利率", "销售及管理费用", "折旧与摊销", "减值损失",
                        "免费股计划费用", "计提准备、其他与舍入", "合计变动"],
            "xrot": 45,
            "stacks": [{
                "name": "对上半年利润率的影响",
                "color": "NAVY",
                "values": rounded(legs) + [None],
            }],
            "net": {
                "name": "上半年利润率净变动",
                "values": [None] * len(legs) + [round(end - start, 6)],
            },
            "fmt": "pp1", "yfmt": "pp1", "label_fmt": "pp1",
            "ylab": "对利润率的影响 pp",
            "note": note,
            "src_extra": income["_source"] + "；各项占收入比重为本页自算 D。",
        })

    if segments is not None and income is not None:
        rows = segments["rows"]
        lines = {key: (cur, prior) for key, _, cur, prior in income["lines"]}
        operating = [s for s in rows if s["key"] != "unallocated"]
        unallocated = next(s for s in rows if s["key"] == "unallocated")
        six_now = sum(s["roi_now"] for s in operating)
        six_before = sum(s["roi_prior"] for s in operating)
        total_now = lines["recurring_operating_income"][0]
        total_before = lines["recurring_operating_income"][1]
        swing = unallocated["roi_now"] - unallocated["roi_prior"]
        only_unallocated = six_now < six_before and total_now > total_before
        free_now, free_before = next((cur, prior) for key, _, cur, prior in income["other_detail"]
                                     if key == "free_share_plans")
        tallest = max(s["roi_now"] for s in operating)
        small = max(abs(unallocated["roi_now"]), abs(unallocated["roi_prior"]))
        prior_year = str(int(year) - 1)
        title = (f"半年分部经常性经营利润：{cn_count(len(operating))}个经营地区合计 €{six_before:,}M → €{six_now:,}M"
                 f"（{signed((six_now / six_before - 1) * 100)}）")
        if only_unallocated:
            title += (f"，集团之所以是 {signed((total_now / total_before - 1) * 100)}，"
                      f"全靠未分配一栏摆动 €{swing:+,}M")
        note = ""
        if only_unallocated:
            note += ("<b>这张表在公司自己的文件里是附注 3，很少被引用，而它推翻了「利润小幅增长」这句概括。</b>"
                     f"{cn_count(len(operating))}个经营地区加起来是 €{six_before:,}M → €{six_now:,}M，也就是 −€{six_before - six_now}M；"
                     f"集团口径的 +€{total_now - total_before}M 完全来自未分配一栏从 "
                     f"{'−' if unallocated['roi_prior'] < 0 else '+'}€{abs(unallocated['roi_prior'])}M "
                     f"{'翻正' if unallocated['roi_prior'] < 0 < unallocated['roi_now'] else '变'}到 "
                     f"{'+' if unallocated['roi_now'] >= 0 else '−'}€{abs(unallocated['roi_now'])}M。")
        note += "公司对未分配栏的定义是「免费股分配计划费用、未分配的中央成本与内部计费」"
        if abs(free_now) < abs(free_before):
            note += f"，而同期免费股计划费用降了 €{abs(free_before) - abs(free_now)}M。"
        else:
            note += "。"
        note += ("<b>未分配那一栏没有画在图上</b>："
                 f"一根 €{small}M 的柱子挨着一根 €{tallest:,}M 的柱子"
                 "既读不出高低、又会把自己的数值标签压到地区名上，它的两个数在标题里、"
                 "在这段话里、也在核对抽屉的分部表里。")
        if only_unallocated:
            note += "<b>所以「上半年利润还在增长」这句话，要成立必须把一个与本期经营无关的科目算进去。</b>"
        note += ("另外附注 3 自己写明：上半年的分部利润率<b>不含内部转移定价调整</b>，"
                 "这些调整对合并利润中性、将发生在下半年，且主要影响法国与亚太（除日本）——"
                 "所以这两个地区的半年利润率不可外推全年，而表内所有半年对半年的同比变动是同口径的。")
        charts.append({
            "ref": "EX_SEGMENT_ROI",
            "kind": "grouped_bars",
            "title": title,
            "xlabels": [s["label"] for s in operating],
            "xrot": 45,
            "groups": [
                {"name": f"上半年 {prior_year}", "color": "BLUE", "values": [s["roi_prior"] for s in operating]},
                {"name": f"上半年 {year}", "color": "NAVY", "values": [s["roi_now"] for s in operating]},
            ],
            "bar_labels": True,
            "fmt": "f0c", "label_fmt": "f0c",
            "ylab": "€M（半年）",
            "note": note,
            "src_extra": f"{year} 半年度财务报告附注 3（分部信息），上半年口径。",
        })

        margin_now = {s["key"]: s["roi_now"] / s["revenue_now"] * 100 for s in operating}
        margin_prior = {s["key"]: s["roi_prior"] / s["revenue_prior"] * 100 for s in operating}
        margin_delta = [margin_now[s["key"]] - margin_prior[s["key"]] for s in operating]
        big = max(operating, key=lambda s: s["roi_now"])
        big_i = operating.index(big)
        expanded = [s for s, d in zip(operating, margin_delta) if d > 0]
        both = [s for s, d in zip(operating, margin_delta)
                if d > 0 and s["revenue_now"] > s["revenue_prior"]]
        against = [s for s, d in zip(operating, margin_delta)
                   if d > 0 and s["revenue_now"] < s["revenue_prior"]]
        longest = operating[margin_delta.index(min(margin_delta))]
        margin_note = (f"{cn_count(len(operating))}个地区里{'只' if len(expanded) * 2 < len(operating) else ''}"
                       f"有{cn_count(len(expanded))}个扩张。")
        if len(both) == 1:
            s = both[0]
            margin_note += (f"<b>唯一量与利润率同时改善的是{s['label']}</b>"
                            f"（利润 {signed((s['roi_now'] / s['roi_prior'] - 1) * 100)}、"
                            f"利润率 {signed(margin_delta[operating.index(s)], 2, 'pp')}）")
            if against:
                a = against[0]
                margin_note += (f"，而{a['label']}利润率的 {signed(margin_delta[operating.index(a)], 2, 'pp')} "
                                "是在收入按当期汇率<b>下降</b> "
                                f"{abs((a['revenue_now'] / a['revenue_prior'] - 1) * 100):.1f}% 的情况下取得的"
                                + (f" —— {hstory['japan_fx']}" if hstory and a["key"] == "japan" else "。"))
            else:
                margin_note += "。"
        if margin_delta[big_i] < 0 and big["roi_now"] < big["roi_prior"]:
            margin_note += (f"最该盯的是{big['label']}：它一个地区占了集团分部利润的 "
                            f"{big['roi_now'] / total_now * 100:.1f}%，"
                            "利润率和利润额同时下滑，是集团利润率的第一决定变量。")
        if longest is not big and min(margin_delta) < 0:
            margin_note += (f"{REGION_SHORT[longest['key']]}那条最长的负柱只有 €{longest['revenue_now']}M 的收入基数，"
                            "对集团的绝对影响远小于它的柱长。")
        margin_note += ("利润率为本页按分部收入与分部利润自算 D；公司自己只印到整数百分比"
                        f"（{margin_now[big['key']]:.0f}%、{margin_prior[big['key']]:.0f}%），"
                        "两位小数的变动量按未取整的原值计算。")
        charts.append({
            "ref": "EX_SEGMENT_MARGIN",
            "kind": "diverging_bars",
            "title": (f"半年分部利润率变动：{big['label']}"
                      f"{'掉了' if margin_delta[big_i] < 0 else '升了'} "
                      f"{abs(margin_delta[big_i]):.2f}pp，而它占集团分部利润的 "
                      f"{big['roi_now'] / total_now * 100:.1f}%"),
            "xlabels": [s["label"] for s in operating],
            "xrot": 45,
            "values": rounded(margin_delta),
            "legend": "上半年利润率同比变动",
            "positive_label": "利润率扩张",
            "negative_label": "利润率收缩",
            "fmt": "pp1", "yfmt": "pp1", "label_fmt": "pp1",
            "ylab": "pp（半年对半年）",
            "zero_line": True,
            "note": margin_note,
            "src_extra": f"{year} 半年度财务报告附注 3；利润率与变动量为本页自算 D。",
        })

    invest_first = [halves[f"H1 {y}"]["operating_investments_eur_m"] if f"H1 {y}" in halves else None
                    for y in years]
    invest_second = [halves[f"H2 {y}"]["operating_investments_eur_m"] if f"H2 {y}" in halves else None
                     for y in years]
    capex_story = (hstory or {}).get("capex")
    last_full = max(int(y) for y in staging["full_years"])
    fy_prior = staging["full_years"][str(last_full)]["operating_investments_eur_m"]
    target = (capex_story if capex_story and latest_half["label"].startswith("H1")
              and capex_story["target_year"] == int(year) else None)
    ramp = [s / f for f, s in zip(invest_first, invest_second) if f and s]
    group_names = ["上半年（公司披露）"]
    capex_note = ""
    annot = None
    if target is not None:
        fy_target = target["target_eur_m"]
        implied = fy_target - invest_first[-1]
        invest_second[-1] = implied
        cut = abs((fy_target / fy_prior - 1) * 100)
        prior_i = years.index(str(last_full))
        derived_years = [y for y, s in zip(years, invest_second) if s is not None and y != year]
        group_names.append(f"下半年（{derived_years[0]}–{derived_years[-1]} 为全年减上半年 D，{year} 为按全年目标反推）")
        capex_title = (f"半年经营性投资：{target['said']}，而全年目标 €{fy_target:,}M 比 {last_full} 年"
                       f"实际的 €{fy_prior:,}M {'少' if fy_target < fy_prior else '多'} {cut:.1f}%")
        weaker = implied / invest_first[-1] < invest_second[prior_i] / invest_first[prior_i]
        if ramp and all(r > 1 for r in ramp) and weaker:
            capex_note += "<b>下半年投资爬坡是这家公司每年都有的季节性，问题在于今年的爬坡比往年弱。</b>"
        yoy = (implied / invest_second[prior_i] - 1) * 100
        capex_note += (f"{last_full} 年下半年花了 €{invest_second[prior_i]:,}M，是上半年的 "
                       f"{invest_second[prior_i] / invest_first[prior_i]:.2f} 倍；"
                       f"{year} 年按全年目标反推的下半年是 €{implied:,}M，{'只有' if weaker else '是'}上半年的 "
                       f"{implied / invest_first[-1]:.2f} 倍，同比 "
                       f"{signed(yoy)}。"
                       # 「下半年是自由现金流的顺风」 holds only while the implied
                       # second half is below last year's.
                       + (fill_story(target["reading"], {
                           # the reading was written the quarter the half was reported
                           "season": "本季" if closes_half(period, latest_half["label"]) else "半年报发布时",
                       }) if yoy < 0 else "")
                       + f"Operating investments 那一行同时印着上半年 €{invest_first[-1]}M、"
                       f"{last_full} 全年 €{fy_prior:,}M 与上年同期 €{invest_first[prior_i]}M，三列同口径。"
                       + (fill_story(target["question"], {"cut": f"{round(cut)}"})
                          if fy_target < fy_prior else ""))
        annot = f"{year} 下半年 €{implied:,}M 为按全年目标 €{fy_target:,}M 反推的隐含值"
        src = SOURCE_HALF + "；" + target["source"]
    else:
        group_names.append("下半年（全年减上半年 D）")
        capex_title = (f"半年经营性投资：{latest_half['label']} "
                       f"€{latest_half['operating_investments_eur_m']:,}M，{last_full} 年全年 €{fy_prior:,}M")
        if ramp and all(r > 1 for r in ramp):
            capex_note += ("下半年投资爬坡是这家公司每年都有的季节性："
                           + "；".join(f"{y} 年下半年是上半年的 {s / f:.2f} 倍"
                                      for y, f, s in zip(years, invest_first, invest_second) if f and s) + "。")
        src = SOURCE_HALF
    capex = {
        "ref": "EX_CAPEX",
        "kind": "grouped_bars",
        "title": capex_title,
        "xlabels": years,
        "groups": [
            {"name": group_names[0], "color": "NAVY", "values": invest_first},
            {"name": group_names[1], "color": "GOLD", "values": invest_second},
        ],
        "bar_labels": True,
        "fmt": "f0c", "label_fmt": "f0c",
        "ylab": "€M（半年）",
        "note": capex_note or "经营性投资按半年列示；下半年为全年减上半年（D）。",
        "src_extra": src,
    }
    if annot:
        capex["annot"] = annot
    # Keep the key order the page has always published.
    if annot:
        capex = {k: capex[k] for k in ("ref", "kind", "title", "xlabels", "groups", "bar_labels", "fmt",
                                       "label_fmt", "ylab", "annot", "note", "src_extra")}
    charts.append(capex)
    return charts


# ── section four: what the next release can and cannot settle ────────────────
def kpi_entries(staging: dict, kpi: dict) -> list[dict]:
    """The next thresholds with their current values read from the series."""
    latest = len(staging["periods"]) - 1

    def current(reads: str) -> float:
        parts = reads.split(".")
        if parts[0] == "group_revenue":
            return staging["group_revenue"][parts[1]][latest]
        if parts[0] in ("by_sector", "by_region"):
            return staging[parts[0]][parts[1]][parts[2]][latest]
        if parts[0] == "increment_share":
            increments, total = cc_increments(staging["by_sector"], SECTOR_ORDER, latest)
            return round(increments[parts[1]] / total * 100, 1)
        raise KeyError(f"next_kpi entry reads an unknown series: {reads}")
    return [{**{k: v for k, v in entry.items() if k != "reads"}, "current": current(entry["reads"])}
            for entry in kpi["quantified"]]


def next_quarter_charts(staging: dict, kpi: dict, entries: list[dict], values: dict) -> list[dict]:
    periods = staging["periods"]
    n = len(periods)
    rated = rated_quarters(staging)
    breached = [e for e in entries
                if headroom_value(e["direction"], e["threshold"], e["current"]) < 0]
    later = kpi["full_year_only"]
    year, number = quarter_parts(periods[-1])
    next_number = number % 4 + 1
    revenue_only = next_number in (1, 3)
    fy = kpi["full_year_settles_on"]
    note = (f"{len(entries)} 条全部是收入类，因为 <b>{kpi['settles_on']} 的第{cn_ordinal(next_number)}季度公告只有收入</b> —— "
            f"没有损益表、没有现金流量表、没有资产负债表，所以任何「第{cn_ordinal(next_number)}季度利润率」都不存在。"
            if revenue_only else
            f"{len(entries)} 条阈值都在 {kpi['settles_on']} 的业绩公告上结算。")
    note += (f"利润与投资类的 {len(later)} 条要等 {fy[:4]} 年 {int(fy[5:7])} 月的全年业绩，列在核对抽屉里。"
             "阈值方向统一为「正值 = 仍在安全侧」，各条的原始单位见核对表。")
    if breached:
        note += (f"越过阈值的是{'、'.join(e['metric'] for e in breached)}，"
                 f"共 {len(breached)} 条，彼此不重叠。")
    charts = [headroom_exhibit(
        f"下季 {len(entries)} 条阈值的余量：本季已有 {len(breached)} 条落在阈值的另一侧",
        entries, "current",
        note=note,
        src_extra="阈值为本页本地研究设定，不是公司指引；公司不发布任何数字化指引。",
    )]

    by_metric = {e["metric"]: e for e in entries}
    raw = {e["metric"]: e for e in kpi["quantified"]}
    first_half = stamped_block(staging, "first_half", staging["half_years"][-1]["label"])
    segments = stamped_block(staging, "h1_segments", staging["half_years"][-1]["label"])
    income = stamped_block(staging, "h1_income", staging["half_years"][-1]["label"])
    for metric in kpi.get("threshold_charts", []):
        entry = by_metric[metric]
        kind, key, _ = raw[metric]["reads"].split(".")
        block = staging[kind][key]
        values_now = block["cc_pct"]
        threshold = entry["threshold"]
        # Counted over the quarters that carry a rate, not over the axis: the
        # early quarters have a euro amount and no growth beside it, and a
        # quarter with no rate is neither above nor below the threshold.
        scored = [values_now[i] for i in rated]
        above = sum(1 for v in scored if v >= threshold)
        chart_note = ""
        if kind == "by_region" and first_half is not None and segments is not None and income is not None:
            total_roi = next(cur for k, _, cur, _ in income["lines"] if k == "recurring_operating_income")
            row = next(r for r in segments["rows"] if r["key"] == key)
            largest = max((r for r in segments["rows"] if r["key"] != "unallocated"),
                          key=lambda r: r["roi_now"])["key"] == key
            chart_note += (f"这条线为什么值得单独画：该地区占上半年集团收入 "
                           f"{first_half['by_region'][key]['revenue_eur_m'] / first_half['group']['revenue_eur_m'] * 100:.1f}%、"
                           f"占分部经常性经营利润 {row['roi_now'] / total_roi * 100:.1f}%"
                           + ("，是集团利润率的第一决定变量" if largest else "")
                           + f"，而它在这 {len(scored)} 个季度里有 {sum(1 for v in scored if v < threshold)} 季"
                           f"低于 {threshold:g}%。")
        chart_note += fill_story(raw[metric].get("chart_note", ""), values)
        charts.append(threshold_exhibit(
            f"{block['label']}固定汇率增速与 {threshold:g}% 阈值：{cn_count(len(scored))}季里 {above} 季在阈值之上",
            list(periods), rounded(values_now), threshold,
            fmt="pct1", ylab="同比 %（固定汇率）",
            actual_name=f"{block['label']}固定汇率增速", threshold_name=f"本页阈值 {threshold:.1f}%",
            note=chart_note + AXIS,
            src_extra=SOURCE_QUARTER,
        ))
    return charts


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    group = staging["group_revenue"]
    half = staging["half_years"][-1]
    # The company's own one-decimal margin when it prints one: 3,351 / 8,163 is
    # 41.05%, which rounds to 41.1%, while Hermès prints 41.0% off unrounded
    # figures. Where the two disagree the page carries the company's.
    margin = half.get("roi_margin_printed_pct", half["roi_margin_pct"])
    return [f"{staging['periods'][-1].split()[0]} revenue €{group['revenue_eur_m'][-1]:,.0f}M",
            f"固定汇率 {group['cc_pct'][-1]:+.1f}%",
            f"{half['label'].split()[0]} 经营利润率 {margin:.1f}%"]


def build_payload(staging: dict) -> dict:
    periods = staging["periods"]
    n = len(periods)
    latest = n - 1
    period = periods[-1]
    group = staging["group_revenue"]
    halves = {h["label"]: h for h in staging["half_years"]}
    half = staging["half_years"][-1]["label"]
    sectors = staging["by_sector"]
    regions = staging["by_region"]
    latest_meta = latest_block(
        staging,
        period=period,
        release_date=staging["release_dates"][period],
        full_label=half)
    kpi = stamped_block(staging, "next_kpi", period)
    quasi = stamped_block(staging, "quasi_guidance", period)
    story = stamped_block(staging, "quarter_story", period)
    hstory = stamped_block(staging, "half_story", half)
    income = stamped_block(staging, "h1_income", half)
    segments = stamped_block(staging, "h1_segments", half)
    first_half = stamped_block(staging, "first_half", half)
    prefix = release_prefix(period)
    if not any(source["label"].startswith(prefix) for source in staging["sources"]):
        raise ValueError(f"series `sources` has no entry for the {prefix} release: add it with the roll")
    values = story_values(staging)
    entries = kpi_entries(staging, kpi) if kpi is not None else []

    outlook = outlook_charts(staging, story)
    quarter = quarter_charts(staging, story)
    half_year = half_year_charts(staging, hstory, period)
    next_block = next_quarter_charts(staging, kpi, entries, values) if kpi is not None else []

    # Four parts, in the site's order. What the latest release made news goes
    # in part two; a long record with no reading of this quarter goes in part
    # four. The half's profit charts are news only in the quarter whose release
    # closed that half (the second quarter for H1, the fourth for the year): in
    # a first- or third-quarter roll they are last half's reading, and they
    # move to the routine part rather than sitting under 「本季重点」.
    half_is_news = closes_half(period, half)
    long_refs = ("EX_SECTOR_TREND", "EX_HALF_MARGIN")
    long_run = [ex for ex in quarter + half_year if ex.get("ref") in long_refs]
    quarter_news = [ex for ex in quarter if ex.get("ref") not in long_refs]
    half_reading = [ex for ex in half_year if ex.get("ref") not in long_refs]
    settled_ex = outlook
    highlight_ex = quarter_news + (half_reading if half_is_news else [])
    next_ex = next_block
    routine_ex = long_run + ([] if half_is_news else half_reading)
    exhibits = number_exhibits(settled_ex + highlight_ex + next_ex + routine_ex)
    resolve_exhibit_refs(exhibits)

    increments, total_inc = cc_increments(sectors, SECTOR_ORDER, latest)
    lead = max(SECTOR_ORDER, key=lambda k: increments[k])
    lead_share = increments[lead] / total_inc * 100
    r_inc, r_total = cc_increments(regions, REGION_ORDER, latest)
    engine = max(REGION_ORDER, key=lambda k: r_inc[k])
    engine_share = r_inc[engine] / r_total * 100
    wedge = [None if p is None or c is None else p - c
             for p, c in zip(group["published_pct"], group["cc_pct"])]
    year, number = quarter_parts(period)
    outlook_block = staging["outlook"]

    first_table = exhibits[-1]["n"] + 1
    tables = [
        {
            "title": f"近{cn_count(n)}季分板块收入与两个增速口径（公司披露值）",
            "headers": ["期间", "集团收入", "集团 published", "集团固定汇率"]
                       + [sectors[key]["label"] for key in SECTOR_ORDER],
            "rows": [[periods[i], f"€{group['revenue_eur_m'][i]:,}M",
                      pct_or_dash(group["published_pct"][i]), pct_or_dash(group["cc_pct"][i])]
                     + [f"€{sectors[key]['revenue_eur_m'][i]:,}M / "
                        + pct_or_dash(sectors[key]["cc_pct"][i])
                        for key in SECTOR_ORDER]
                     for i in range(n)],
        },
        {
            "title": f"近{cn_count(n)}季分地区收入与两个增速口径（公司披露值）",
            "headers": ["期间"] + [f"{regions[key]['label']}（收入 / published / 固定汇率）"
                                   for key in REGION_ORDER],
            "rows": [[periods[i]]
                     + [f"€{regions[key]['revenue_eur_m'][i]:,}M / "
                        + pct_or_dash(regions[key]["published_pct"][i]) + " / "
                        + pct_or_dash(regions[key]["cc_pct"][i])
                        for key in REGION_ORDER]
                     for i in range(n)],
        },
        {
            "title": "半年度损益、现金流与投资（下半年为全年减上半年 D）",
            "headers": ["半年", "口径", "收入", "经常性经营利润", "经常性经营利润率 D",
                        "归母净利润", "经营现金流", "经营性投资", "调整后自由现金流"],
            "rows": [[h["label"], "公司披露" if not h["derived"] else "全年减上半年 D",
                      euro_cell(h, "revenue_eur_m"),
                      euro_cell(h, "recurring_operating_income_eur_m"),
                      margin_cell(h),
                      euro_cell(h, "net_profit_group_eur_m"),
                      euro_cell(h, "operating_cash_flows_eur_m"),
                      euro_cell(h, "operating_investments_eur_m"),
                      euro_cell(h, "adjusted_fcf_eur_m")]
                     for h in staging["half_years"]],
        },
    ]
    if income is not None:
        lines = {key: (cur, prior) for key, _, cur, prior in income["lines"]}
        h_year = half.split()[1]
        tables.append({
            "title": "上半年合并损益表与其他收支明细（公司披露值）",
            "headers": ["科目", f"上半年 {h_year}", f"上半年 {int(h_year) - 1}", "变动", "占收入变动 D"],
            "rows": [[label, f"€{cur:,}M", f"€{prior:,}M", f"€{cur - prior:+,}M",
                      f"{cur / lines['revenue'][0] * 100 - prior / lines['revenue'][1] * 100:+.3f}pp"]
                     for _, label, cur, prior in income["lines"]]
                    + [[f"其中：{label}", f"€{cur:,}M", f"€{prior:,}M", f"€{cur - prior:+,}M",
                        f"{cur / lines['revenue'][0] * 100 - prior / lines['revenue'][1] * 100:+.3f}pp"]
                       for _, label, cur, prior in income["other_detail"]]
                    + [["稀释每股收益", f"€{income['eps_diluted_eur'][0]:.2f}",
                        f"€{income['eps_diluted_eur'][1]:.2f}",
                        f"€{income['eps_diluted_eur'][0] - income['eps_diluted_eur'][1]:+.2f}",
                        f"{(income['eps_diluted_eur'][0] / income['eps_diluted_eur'][1] - 1) * 100:+.2f}%"]],
        })
    if segments is not None:
        s_year = half.split()[1]
        tables.append({
            "title": "分地区经常性经营利润与投资（附注 3，上半年口径）",
            "headers": ["地区", f"利润 {s_year}", f"利润 {int(s_year) - 1}", "同比", f"利润率 {s_year} D",
                        f"利润率 {int(s_year) - 1} D", "利润率变动 D", f"投资 {s_year}", f"投资 {int(s_year) - 1}"],
            "rows": [[s["label"], f"€{s['roi_now']:,}M", f"€{s['roi_prior']:,}M",
                      f"{(s['roi_now'] / s['roi_prior'] - 1) * 100:+.1f}%"
                      if s["roi_prior"] > 0 else "—",
                      f"{s['roi_now'] / s['revenue_now'] * 100:.2f}%" if s["revenue_now"] else "—",
                      f"{s['roi_prior'] / s['revenue_prior'] * 100:.2f}%" if s["revenue_prior"] else "—",
                      f"{s['roi_now'] / s['revenue_now'] * 100 - s['roi_prior'] / s['revenue_prior'] * 100:+.2f}pp"
                      if s["revenue_now"] and s["revenue_prior"] else "—",
                      f"€{s['capex_now']:,}M", f"€{s['capex_prior']:,}M"]
                     for s in segments["rows"]],
        })
    tables.append({
        "title": "官方展望的原文与它出现过的每一份公告",
        "headers": ["发布日期", "公告", "展望段的数字个数", "展望段原文"],
        "rows": [[r["date"], r["label"], "0", outlook_block["sentence"]]
                 for r in outlook_block["releases"]],
    })
    if quasi is not None:
        tables.append({
            "title": f"电话会上给出的 {len(quasi['items'])} 条数字化「准指引」（不是新闻稿里的书面指引）",
            "headers": ["项目", "数值", "对下半年的方向", "何时可结算", "限定"],
            "rows": [[q["item"], q["value"], q["direction"], q["settles"], q["note"]]
                     for q in quasi["items"]],
        })
    if kpi is not None:
        tables.append(threshold_table(0, "下季阈值与当前值（原始单位）", entries, "current", "当前值"))
        tables.append({
            "title": f"只有全年业绩才能结算的 {len(kpi['full_year_only'])} 条（{kpi['full_year_settles_on']}）",
            "headers": ["指标", "当前值", "阈值", "为什么"],
            "rows": [[k["metric"], k["current"], k["threshold"], k["why"]]
                     for k in kpi["full_year_only"]],
        })
    for offset, table in enumerate(tables):
        table["n"] = first_table + offset
    tables = [{"n": t["n"], **{k: v for k, v in t.items() if k != "n"}} for t in tables]
    tables.append(ai_capex_cycle_table(first_table + len(tables)))

    # ── the quarter and the half in one sentence ──
    headline = (f"第{cn_ordinal(number)}季度收入 €{group['revenue_eur_m'][latest]:,}M，"
                f"published {signed(group['published_pct'][latest])} 而固定汇率 "
                f"{signed(group['cc_pct'][latest])}；"
                f"{SECTOR_SHORT[lead]}占本季收入 "
                f"{sectors[lead]['revenue_eur_m'][latest] / group['revenue_eur_m'][latest] * 100:.1f}%"
                f"、却贡献了固定汇率增量的 {lead_share:.1f}%，"
                f"{regions[engine]['label']}用 {regions[engine]['revenue_eur_m'][latest] / group['revenue_eur_m'][latest] * 100:.1f}% 的收入"
                f"贡献了 {engine_share:.1f}%；")
    latest_half = halves[half]
    if segments is not None and income is not None:
        operating = [s for s in segments["rows"] if s["key"] != "unallocated"]
        six_now = sum(s["roi_now"] for s in operating)
        six_before = sum(s["roi_prior"] for s in operating)
        roi_now, roi_before = next((cur, prior) for key, _, cur, prior in income["lines"]
                                   if key == "recurring_operating_income")
        headline += (f"而利润只有上半年口径 —— 经常性经营利润率 {official_margin(latest_half):.1f}%，"
                     f"{cn_count(len(operating))}个经营地区的利润合计 {signed((six_now / six_before - 1) * 100)}，"
                     f"集团口径的 {signed((roi_now / roi_before - 1) * 100)} "
                     + ("全部来自未分配一栏。" if six_now < six_before and roi_now > roi_before else "。"))
    else:
        full = staging["full_years"].get(half.split()[1]) if half.startswith("H2") else None
        if full is not None:
            fy_margin = full.get("roi_margin_printed_pct",
                                 full["recurring_operating_income_eur_m"] / full["revenue_eur_m"] * 100)
            headline += f"而利润停在 {half.split()[1]} 全年口径 —— 经常性经营利润率 {fy_margin:.1f}%。"
        else:
            headline += f"而利润停在 {half} 口径 —— 经常性经营利润率 {official_margin(latest_half):.1f}%。"

    # How long the sentence has stood, in reporting periods: the first release
    # held covers Q1 2021 and the latest covers the half to June 2026, which is
    # 22 quarters -- 「五年半」.
    first_y, first_q = release_quarter(outlook_block["releases"][0]["label"])
    last_y, last_q = release_quarter(outlook_block["releases"][-1]["label"])
    span_quarters = (last_y - first_y) * 4 + (last_q - first_q) + 1
    span_words = (cn_count(span_quarters // 4) + "年"
                  + {0: "", 1: "多", 2: "半", 3: "半多"}[span_quarters % 4])
    pub_step = group["published_pct"][latest] - group["published_pct"][latest - 1]
    cc_step = group["cc_pct"][latest] - group["cc_pct"][latest - 1]
    # The quarter whose release carries the profit figures on this page -- the
    # one a reader would wrongly attach them to: the half-year report comes with
    # the second quarter's revenue, the annual report with the fourth's.
    profit_quarter = f"第{cn_ordinal(2 if half.startswith('H1') else 4)}季度"
    cards = [
        '<article><span>口径</span><b>这家公司有两个时钟</b>'
        f'<p>收入按季披露，利润只按半年披露。不存在{profit_quarter}的利润率、每股收益或自由现金流；'
        '半年报的资产负债表比较期还是上年 12 月而不是上年 6 月。'
        '本页的利润图全部走半年轴，标题里都写着「半年」。</p></article>',
        f'<article><span>记录</span><b>展望{span_words}没换过一个字，也没有一个数</b>'
        f'<p>手上 {len(outlook_block["releases"])} 份公告的 Outlook 段逐字相同，'
        f'数字个数为 {outlook_block["numbers_in_sentence"]}：没有收入区间、没有利润率、没有每股收益，'
        '连时间边界都是「中期」而不是某一年。能结算的只有它每季给的两个增速口径。</p></article>',
    ]
    if pub_step > cc_step > 0:
        cards.append(
            f'<article><span>本季</span><b>标题增速与经营增速差 {abs(wedge[latest]):.1f}pp，上季差 '
            f'{abs(wedge[latest - 1]):.1f}pp</b>'
            f'<p>published 从 {signed(group["published_pct"][latest - 1])} 跳到 '
            f'{signed(group["published_pct"][latest])}，抬升 {pub_step:.1f}pp；'
            f'固定汇率只从 {signed(group["cc_pct"][latest - 1])} 到 {signed(group["cc_pct"][latest])}，'
            f'抬升 {cc_step:.1f}pp。'
            f'真实加速是 {cc_step:.1f}pp，不是 {pub_step:.1f}pp。</p></article>')

    half_words = "、".join((["上半年利润率变动的逐项拆解"] if income is not None else [])
                           + ["分地区利润与投资节奏" if segments is not None else "投资节奏"])
    profit_period = "上半年" if half.startswith("H1") else "全年"
    sections = [
        {"id": "settled", "short": "上季兑现", "title": "一、上季跟踪指标兑现了吗",
         "description": (f"公司自己给出、可以拿来核对的东西：书面展望里没有 —— 手上 {len(outlook_block['releases'])} 份公告的 "
                         "Outlook 段是同一句话、零个数字。公司每季确实给出的是 published 与固定汇率两个增速，"
                         "以及它们之间那道逐季张开的口子。"),
         "exhibits": settled_ex},
        {"id": "quarter_highlights", "short": "本季重点", "title": "二、本季重点",
         "description": (f"本季的收入读数：{cn_count(len(SECTOR_ORDER))}个板块的加减速与增长的集中度"
                         + (f"；以及随本季公告一起发布的{profit_period}利润读数：{half_words}。"
                            "利润只有半年口径，这几张图的横轴是半年或地区，没有一张是季度 —— "
                            f"把其中任何一个数称作「{profit_quarter}」都是错的。" if half_is_news else "。")),
         "exhibits": highlight_ex},
        {"id": "next_quarter", "short": "下季跟踪", "title": "三、下季要跟踪什么",
         "description": ((f"{len(kpi['quantified'])} 条可在 "
                          f"{kpi['settles_on']} 第{cn_ordinal(number % 4 + 1)}季度收入公告上结算的阈值，"
                          "统一用「距阈值余量」口径；利润与投资类的 "
                          f"{len(kpi['full_year_only'])} 条要等 {kpi['full_year_settles_on']} 的全年业绩，"
                          "收在核对抽屉里。") if kpi is not None and next_ex else "本季没有设定下季阈值。"),
         "exhibits": next_ex},
        {"id": "routine", "short": "长期常规", "title": "四、长期常规跟踪",
         "description": (f"爱马仕专属的长期序列：{cn_count(n)}个季度{cn_count(len(SECTOR_ORDER))}个板块的固定汇率增速，"
                         f"以及 {staging['half_years'][0]['label'].split()[1]}–{half.split()[1]} 年的半年经常性经营利润率"
                         + ("。" if half_is_news else f"；上一个利润期（{half}）的读数也收在这里，它不是本季公告的内容。")),
         "exhibits": routine_ex},
    ]
    order = " → ".join(section.pop("short") for section in sections)

    # ── reconciliations the notes state, recomputed ──
    sector_sum = max(abs(sum(sectors[k]["revenue_eur_m"][i] for k in SECTOR_ORDER) - group["revenue_eur_m"][i])
                     for i in range(n))
    region_sum = max(abs(sum(regions[k]["revenue_eur_m"][i] for k in REGION_ORDER) - group["revenue_eur_m"][i])
                     for i in range(n))
    worst_sum = max(sector_sum, region_sum)
    checks = [f"{cn_count(n)}个季度里,{cn_count(len(SECTOR_ORDER))}个板块相加与{cn_count(len(REGION_ORDER))}个地区相加"
              + (f"都等于公司印出的集团合计（最大差 {worst_sum}，为各行四舍五入）" if worst_sum <= 1 else
                 f"与公司印出的集团合计最多差 €{worst_sum}M")]
    full_year_quarters = [y for y in {p[-4:] for p in periods} if all(f"Q{k} {y}" in periods for k in (1, 2, 3, 4))]
    for y in sorted(full_year_quarters):
        quarters_sum = sum(group["revenue_eur_m"][periods.index(f"Q{k} {y}")] for k in (1, 2, 3, 4))
        if y not in staging["full_years"]:
            continue
        filed = staging["full_years"][y]["revenue_eur_m"]
        if quarters_sum == filed:
            checks.append(f"{y} 年四个季度相加等于公司申报的全年 €{quarters_sum:,}M")
        else:
            # Hermès's own four printed quarters do not always re-add to its own
            # printed year. Saying so is the point of a reconciliation note: a
            # check that only speaks when it passes is not a check.
            gap = abs(quarters_sum - filed)
            # Printed at the precision the two figures carry, not at whatever
            # binary subtraction produced: €0.1000000000003638M is not a
            # reconciliation note, it is a float artefact wearing one.
            digits = 1 if any(float(v) != int(v) for v in (quarters_sum, filed)) else 0
            checks.append(f"{y} 年四个季度相加 €{quarters_sum:,}M，"
                          f"与公司申报的全年 €{filed:,}M 差 €{gap:,.{digits}f}M")
    if first_half is not None and f"Q1 {half.split()[1]}" in periods and f"Q2 {half.split()[1]}" in periods:
        q1, q2 = periods.index(f"Q1 {half.split()[1]}"), periods.index(f"Q2 {half.split()[1]}")
        diffs = [abs(group["revenue_eur_m"][q1] + group["revenue_eur_m"][q2] - first_half["group"]["revenue_eur_m"]),
                 abs(group["prior_year_eur_m"][q1] + group["prior_year_eur_m"][q2]
                     - first_half["group"]["prior_year_eur_m"])]
        for name, order_keys in (("by_sector", SECTOR_ORDER), ("by_region", REGION_ORDER)):
            for k in order_keys:
                row = first_half[name][k]
                b = staging[name][k]
                diffs.append(abs(b["revenue_eur_m"][q1] + b["revenue_eur_m"][q2] - row["revenue_eur_m"]))
                diffs.append(abs(b["prior_year_eur_m"][q1] + b["prior_year_eur_m"][q2] - row["prior_year_eur_m"]))
        checks.append(f"{half.split()[1]} 年第一、二季度相加"
                      + ("等于公司印出的上半年累计各行" if max(diffs) == 0 else
                         f"与公司印出的上半年累计各行最多差 €{max(diffs)}M（各行四舍五入）"))
    full_halves = [y for y in staging["full_years"] if f"H1 {y}" in halves and f"H2 {y}" in halves]
    # The second half is stored as the year less the first, so this holds by
    # construction -- checked anyway, because a typo in any one of the three
    # would otherwise be printed under the word 「都」.
    # Per year, not from one year's field list: the backfilled years carry
    # fewer lines than the recent ones (adjusted free cash flow is a
    # company-defined measure the early releases do not print), and taking the
    # newest year's fields would have asked 2016 for a cell that does not exist.
    def closing_fields(year: str) -> list[str]:
        rows = [staging["full_years"][year], halves[f"H1 {year}"], halves[f"H2 {year}"]]
        return [k for k in rows[0]
                if k.endswith("_eur_m") and all(row.get(k) is not None for row in rows)]
    # A derived half closes by construction, so the only thing that can break
    # this is a typo -- or binary subtraction on the one-decimal years, which is
    # not a disagreement. Half a unit of the printed precision is the tolerance.
    unequal = [y for y in full_halves
               if any(abs(halves[f"H1 {y}"][k] + halves[f"H2 {y}"][k] - staging["full_years"][y][k]) > 0.05
                      for k in closing_fields(y))]
    if full_halves and not unequal:
        checks.append(f"{cn_count(len(full_halves))}个财年的上下半年相加都等于公司申报的全年")
    elif unequal:
        checks.append(f"{'、'.join(unequal)} 年的上下半年相加与公司申报的全年不等（核对表以公司申报的全年为准）")
    print_gap = None
    if income is not None:
        lines = {key: (cur, prior) for key, _, cur, prior in income["lines"]}
        print_gap = abs(lines["gross_margin"][0] + lines["sga"][0] + lines["other_income_expenses"][0]
                        - lines["recurring_operating_income"][0])
    tracking = next((i for i, s in enumerate(sections, start=1)
                     if s["id"] == "next_quarter" and s["exhibits"]), None)
    subtraction = second_quarter_by_subtraction(staging, first_half, half)
    subtraction_words = ""
    if subtraction:
        worst_gap = max(abs(derived - printed) for _, printed, derived in subtraction)
        shown = sorted((row for row in subtraction if round(row[2], 1) != row[1]),
                       key=lambda row: -abs(row[2] - row[1]))[:2]
        subtraction_words = f"与官方值最大相差 {worst_gap:.1f}pp"
        if shown:
            subtraction_words += ("（例如" + "、".join(
                f"{name}的 {minus_sign(signed(printed))} 会被反推成 {minus_sign(signed(round(derived, 1)))}"
                for name, printed, derived in shown) + "）")
        subtraction_words += "，"
    small, big = base_pair(sectors, latest)
    top_down = group["prior_year_eur_m"][latest] * group["cc_pct"][latest] / 100
    recheck = abs(total_inc / top_down - 1) * 100
    notes = [
        f"本页按「{order}」{cn_count(len(sections))}段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
        "爱马仕不是美国证券交易委员会的申报人。CIK 0001436949 名下只有四类文件：2008-02-25 的一份 12G3-2B（依 Rule 12g3-2(b) 豁免登记）、同日的两份 ARS 与一份 SUPPL，以及 2008、2013、2017、2019 年的四份 F-6EF（存托凭证登记）—— 没有 20-F、没有 6-K、没有 F-1，也没有任何一张财务报表。因此本站其他公司页所依赖的 10-Q/10-K 渲染报表（R-files）与 companyfacts 对它都不存在。本页全部数据来自公司自己在法国发布的季度收入公告、半年度业绩新闻稿与半年度财务报告。",
        "这家公司有两个披露时钟，本页不把它们混在一根轴上。收入按季度披露，分七个 métier、六个地区，每一格都带公司自己算的固定汇率增速；损益表、现金流量表、资产负债表与分部附注一年只出两次。"
        f"所以本页不存在任何形式的「{profit_quarter}利润率」「{profit_quarter}每股收益」「{profit_quarter}自由现金流」—— 利润类的每一张图都走半年轴，标题与轴标里都写着「半年」。",
        "固定汇率增速一律取公司自己在该期表格里印出的那一列，绝不由「半年减第一季」反推。反推值含各行四舍五入，"
        + subtraction_words + "而这类差异恰好落在判断加减速的量级上。",
        "季度数值取自四种不同的公告：第一、三季度取季度收入公告，第二季度取半年度业绩新闻稿的「2nd quarter」子表，第四季度取全年业绩新闻稿的「4th quarter」子表。四种公告的表格结构一致，都同时印出当期、上年同期、published 与固定汇率四列。",
        "已做的对账：" + "；".join(checks) + "。",
        "下半年的利润、现金流与投资是公司申报的全年减去公司申报的上半年（D）。公司本身从不单独披露下半年，所以这几格是本页可复算的派生值而不是披露值；上半年那几格全部是披露值。",
    ]
    if print_gap is not None:
        notes.append("上半年经常性经营利润率的逐项拆解按各科目占收入的比重相减得到，是本页自算（D）。合并损益表印到百万欧元，"
                     + (f"所以毛利减销管费用再减其他收支与印出的经常性经营利润之间存在 €{print_gap}M 的印刷差；" if print_gap else
                        "毛利减销管费用再减其他收支与印出的经常性经营利润逐位相等；")
                     + "拆解图最后一格把计提准备、其他收支净额与这笔舍入并在一起，使六项相加恰好等于净变动。")
    if segments is not None:
        notes.append("分部利润率（附注 3）公司只印到整数百分比。本页图上的两位小数变动量是按分部利润除以分部收入的未取整原值计算的（D），与公司印出的整数不矛盾但比它精细。附注 3 同时写明：上半年的分部利润率不含内部转移定价调整，这些调整对合并经营利润中性、将发生在下半年，且主要影响法国与亚太（除日本）——所以这两个地区的半年利润率不可外推全年，而表内所有半年对半年的同比变动是同口径的。")
    notes.append("「固定汇率增量贡献」是本页自算（D）：把每一行公司印出的固定汇率增速乘以它自己印出的上年同期收入，得到可相加的欧元增量。这一步是必要的 —— 固定汇率增速是各行相对自己基数的百分比，"
                 f"直接比较大小会把一个 €{sectors[small]['prior_year_eur_m'][latest]:,}M 的板块和一个 "
                 f"€{sectors[big]['prior_year_eur_m'][latest]:,}M 的板块放在同一把尺上。"
                 + ("用集团口径复核，两种算法相差不到 1%。" if recheck < 1 else
                    f"用集团口径复核，两种算法相差 {recheck:.1f}%。"))
    first_quarter = outlook_block["releases"][0]["label"].split()[:2]
    notes.append(f"公司的官方展望自 {first_quarter[1]} 年第{cn_ordinal(int(first_quarter[0][1]))}季以来逐字未变，且不含任何数字。"
                 "所以第一节里没有「公司指引兑现」这一块，本页也不报命中率 —— 对着一句没有数字的话报命中率，得到的只会是一列破折号。"
                 + (f"电话会上出现过{cn_count(len(quasi['items']))}条数字化的说法，它们收在核对抽屉的单独一张表里，"
                    f"并逐条标注了限定：{quasi['provenance_note']}" if quasi is not None else ""))
    notes.append("本页不发布市场一致预期、评级、目标价与估值。"
                 + (f"第{cn_ordinal(tracking)}节的阈值是本地研究设定，不是公司指引；每条阈值都写明了它当初想检验的机制，"
                    "以便下一季判断它是被触发还是被证明设计失效。" if tracking else ""))
    season = [(y, official_margin(halves[f"H1 {y}"]) - halves[f"H2 {y}"]["roi_margin_pct"])
              for y in sorted({h["label"].split()[1] for h in staging["half_years"]})
              if f"H1 {y}" in halves and f"H2 {y}" in halves]
    if season and all(g > 0 for _, g in season):
        notes.append(f"上半年利润率与全年利润率的关系是季节性的，不是趋势性的。{cn_count(len(season))}个完整年度里上半年每一次都高于下半年，"
                     f"落差依次为 {'、'.join(f'{g:.2f}pp' for _, g in season)}。"
                     + ("本页给出的全年区间是把这条已发生的落差原样搬到本年的算术，不是预测。"
                        if half.startswith("H1") else ""))
    notes += [
        "本页只发布公司披露值与可复算的简单派生值；D 标记代表 Derived / 自算。",
        "核对抽屉最后那张「AI capex 循环」是全站共用的跨页对照块，在每一页都逐字节相同，不是对爱马仕的判断。它追的是四家云厂现金资本开支 → NVDA 数据中心收入 → TSM 晶圆这条链，爱马仕不在这条链的任何一环上。把它放在这里是为了让读者在任意一页都能查到同一份上下游对照；它在折叠的抽屉里，不参与本页的论证。",
        "本页已知未接入：" + (story["unconnected"] + "以及 " if story else "")
        + f"{year} 年第{cn_ordinal(number)}季度之后的任何数据（本页数据截至 {latest_meta['release_date']} 的披露）。",
    ]
    if income is not None and hstory:
        lines = {key: (cur, prior) for key, _, cur, prior in income["lines"]}
        pre_tax = lines["recurring_operating_income"][0] + lines["net_financial_income"][0]
        notes.append(fill_story(hstory["tax_note"], {"tax_rate": f"{abs(lines['income_tax'][0]) / pre_tax * 100:.2f}%"}))
    notes.append("业绩电话会内容仅用于定位公司已在公告中量化的项目，或用于标注公司口头给出、书面未给的说法；公开仓不复制原件或逐字内容。")

    return {
        "schema_version": "quarterly-dashboard/rms-v1",
        "page": {"slug": "rms", "language": "zh-CN"},
        "company": {
            "ticker": "RMS",
            "name": "Hermès International",
            "group": "luxury_brands",
            "accounting_standard": "IFRS",
        },
        "latest": latest_meta,
        "tracker": "Watchlist Quarterly Tracker · RMS",
        "title": (f"Hermès International (RMS)：{period} 收入与 "
                  + (f"{half} 利润" if half.startswith("H1") else f"{half.split()[1]} 全年利润") + "仪表盘"),
        "subtitle": (f"收入截至 {latest_meta['period_end']} 单季 · "
                     f"利润仅{'上半年' if half.startswith('H1') else '全年'}累计 · 发布 {latest_meta['release_date']} · "
                     f"IFRS · 欧元列示 · {AUDIT_WORDS[latest_meta['audit_status']]} · 自然年财年 · "
                     "数据来自公司季度收入公告与半年度业绩新闻稿及财务报告"),
        "headline": headline,
        "brief": (f'<h4>本期{cn_count(len(cards))}条主线</h4><div class="takeaway-grid">'
                  + "".join(cards) + '</div>'),
        "source": ('Source: <a href="https://finance.hermes.com/en/publications/" rel="noopener">'
                   'Hermès Finance — 财务出版物</a>（各期季度收入公告、半年度与全年业绩新闻稿）。'
                   '爱马仕不是美国证券交易委员会的申报人：它自 2008 年起依 Rule 12g3-2(b) 豁免登记，'
                   '从未提交过 20-F 或 6-K。'),
        "source_url": "https://finance.hermes.com/en/publications/",
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": sections,
        "tables": tables,
        "notes": notes,
        "footer": "Hermès International quarterly and half-year results · 数据来自公司公开披露与透明自算 · 仅供研究，不构成投资建议",
    }


def main() -> int:
    staging = json.loads(STAGING_PATH.read_text(encoding="utf-8"))
    payload = build_payload(staging)
    write_dash(str(DATA_DIR / "rms.js"), payload, "rms")
    shell_dir = ROOT / "rms"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "index.html").write_text(render_shell("RMS", "rms"), encoding="utf-8")
    charts = sum(len(section["exhibits"]) for section in payload["sections"])
    print(f"RMS page: {charts} charts in {len(payload['sections'])} sections "
          f"+ {len(payload['tables'])} audit tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
