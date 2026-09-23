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
across the phrase readings the band a careful reader must allow averages a few
percentage points and reaches ten, some of the phrases are one-sided with no
upper bound at all, and when four quarters of them are chained the permitted
range for a single year's DRAM revenue growth spans tens of points. The company
then reports the answer to nine significant figures.

Two consequences run through the rest of the page. Because the guided variable
is volume and the unguided one is price, a quarter can land its shipment
guidance exactly and still miss on revenue. And because the average selling
price is quoted in US dollars while revenue is reported in won, any
bit-times-price bridge against won revenue carries an unstated exchange-rate
term; a bridge that closes without one has absorbed the currency into a
residual and called it mix.

Published numbers are company-reported or transparent arithmetic. Thresholds in
section three are local research settings, not company guidance.

Rolling a quarter is a data edit (see CLAUDE.md §9): every period label, count
and figure in the prose is computed from ``series/skhynix.json``. What belongs
to one quarter -- the lines below operating profit, what the quarter's own
documents did and did not print, the thresholds -- sits in blocks stamped with
that quarter and read through ``board.stamped_block``, and every "only / all /
first / highest" sentence is printed only while the data still says so.
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
    cn_count,
    cn_fraction,
    cn_ordinal,
    display_period,
    fill_story,
    headroom,
    headroom_exhibit,
    latest_block,
    number_exhibits,
    stamped_block,
    threshold_exhibit,
    unit_text,
)
from build.page_shell import render_shell  # noqa: E402
from build.payload_guard import write_dash  # noqa: E402


STAGING_PATH = ROOT / "series" / "skhynix.json"
DATA_DIR = ROOT / "data"

# Twenty-two quarters on one axis: a tick a year keeps the labels readable.
LONG_STEP = 4

# The page's window before it was extended back to 2016: 2021Q1 through 2026Q2,
# twenty-two quarters. Two captions explain what that shorter window got wrong,
# so its bounds are history, not something a roll moves.
OLD_WINDOW = ("2021Q1", "2026Q2")

# The worked example of integer-margin rounding in the notes: two consecutive
# quarters whose printed integers overstate the step.
ROUNDING_EXAMPLE = ("2025Q2", "2025Q3")

# The last quarter the Form 424B4's thirteen-quarter phrase table reaches. It is
# a fact about that one document, not something a roll moves: every quarter
# after it is worded by a later periodic report (the semi-annual report for
# 2Q 2026), and the captions say so.
PROSPECTUS_PHRASES_END = "1Q 2026"


def rounded(values, digits: int = 4):
    return [None if v is None else round(v, digits) for v in values]


def tn(values):
    """Won billions as printed -> trillions, the unit the company itself quotes."""
    return [None if v is None else round(v / 1000.0, 4) for v in values]


def pct_change(current: float, comparison: float) -> float:
    return (current / comparison - 1) * 100.0


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    return f"{value:+.{digits}f}{suffix}"


def iso_quarter(label: str) -> str:
    """``'1Q 2026'`` (the phrase table's spelling) → ``'2026Q1'``."""
    match = re.match(r"^([1-4])Q (\d{4})$", label)
    return f"{match.group(2)}Q{match.group(1)}" if match else label


def shift_quarter(quarter: str, step: int) -> str:
    """``shift_quarter('2026Q4', 1)`` → ``'2027Q1'``."""
    year, number = int(quarter[:4]), int(quarter[-1])
    index = year * 4 + number - 1 + step
    return f"{index // 4}Q{index % 4 + 1}"


def cn_quarter(quarter: str) -> str:
    """``'2026Q1'`` or ``'1Q 2026'`` → 「2026 年第一季」."""
    quarter = iso_quarter(quarter)
    return f"{quarter[:4]} 年第{cn_ordinal(int(quarter[-1]))}季"


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


def crossings(values: list[float], level: float) -> list[int]:
    """Indices where a series steps across `level`, in either direction.

    Written because the threshold note used to state its own crossing count in
    prose. On the eight-quarter window that count was never checked; on the
    22-quarter window it was wrong (it named a 2022 downward crossing, but the
    line never reached 55% between 2021Q1 and 2022Q4 to cross down from); and on
    42 quarters it is wrong in the other direction as well. A count that is
    recomputed cannot rot when the axis moves.
    """
    return [i for i in range(1, len(values))
            if (values[i - 1] < level <= values[i])
            or (values[i - 1] >= level > values[i])]


def first_upturn(values: list[float]) -> int | None:
    """Index of the first quarter-on-quarter move from negative to positive."""
    return next((i for i in range(1, len(values)) if values[i - 1] < 0 < values[i]), None)


def spaced_after(word: str) -> str:
    """A phrase that ends in Latin letters or digits takes a space before the
    Chinese that follows it (「向 SEC 报送的 6-K 里」); a Chinese one does not."""
    return f"{word} " if word[-1:].isascii() and word[-1:].isalnum() else word


def spaced_before(word: str) -> str:
    """The mirror of `spaced_after`: 「只有」 + 「DRAM 售价」 needs a space between."""
    return f" {word}" if word[:1].isascii() and word[:1].isalnum() else word


# The closure chart's buckets, in the order TSM's page draws them. A verdict
# outside these stops the build rather than being dropped from the tally.
CLOSURE_ORDER = ["已验证", "部分验证", "被证伪", "仍未披露"]


def mean_abs(values: list[float]) -> float:
    return sum(abs(v) for v in values) / len(values)


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


def headline_metrics(staging: dict) -> list[str]:
    """The three figures on this company's home-page card, computed from the series."""
    fin = staging["financials_krw_bn"]
    return [f"Revenue ₩{fin['revenue'][-1] / 1000:.1f}T",
            f"营业利润率 {fin['operating_profit'][-1] / fin['revenue'][-1] * 100:.1f}%",
            "量价只给用词"]


def build_payload(staging: dict) -> dict:
    fin = staging["financials_krw_bn"]
    ann = staging["annual_audited_krw_bn"]
    prod = staging["revenue_by_product_krw_bn"]
    cust = staging["customer_concentration"]
    kpi = staging["kpi_phrases"]
    restate = staging["restatement_2022q4"]
    census = staging["restatement_census"]

    periods = staging["periods"]
    period = display_period(periods[-1])
    latest = latest_block(
        staging,
        period=period,
        period_end=staging["period_ends"][-1],
        release_date=staging["release_dates"][-1])
    # One-quarter blocks: absent means this quarter has no such story and the
    # page leaves that part out; stamped with another quarter stops the build.
    below = stamped_block(staging, "below_operating_profit_krw_bn", period)
    story = stamped_block(staging, "quarter_story", period) or {}
    thresholds = stamped_block(staging, "next_kpi", period)
    if thresholds is None:
        raise ValueError("series block `next_kpi` is missing: the tracking section has no thresholds")
    if below is not None and below["periods"][-1] != periods[-1]:
        raise ValueError(f"series block `below_operating_profit_krw_bn` ends at "
                         f"{below['periods'][-1]!r}, but the series ends at {periods[-1]!r}: "
                         "it is stamped for this quarter and must carry it")
    year, quarter = periods[-1][:4], int(periods[-1][-1])
    filing_label = f"SK hynix {year} 年第{cn_ordinal(quarter)}季度业绩 6-K"
    filing = next((item for item in staging["sources"] if item["label"].startswith(filing_label)), None)
    if filing is None:
        raise ValueError(f"series `sources` has no entry labelled {filing_label!r}: "
                         "add this quarter's 6-K with the roll")
    prospectus = next(item for item in staging["sources"]
                      if item["label"].startswith("SK hynix Form 424B4"))
    prospectus_date = re.search(r"（(\d{4}-\d{2}-\d{2})", prospectus["label"]).group(1)
    ir_page = next(item for item in staging["sources"] if item["label"] == "SK hynix 投资者关系")

    revenue = fin["revenue"]
    op = fin["operating_profit"]
    net = fin["net_income"]
    opm = margin_series(op, revenue)
    netm = [None if n is None else round(n / r * 100.0, 4)
            for n, r in zip(net, revenue)]

    kq = kpi["quarters"]
    # The quarters whose product split an interim statement printed.
    split_quarters = [label for label in prod["labels"] if re.match(r"^\d{4}Q[1-4]$", label)]
    later_words = kq[kq.index(PROSPECTUS_PHRASES_END) + 1:]
    later_span = (f"{later_words[0]}–{later_words[-1]}" if len(later_words) > 1
                  else later_words[0] if later_words else "")
    dram_bit, dram_asp = kpi["dram_bit_shipment"], kpi["dram_asp"]
    nand_bit, nand_asp = kpi["nand_bit_shipment"], kpi["nand_asp"]
    blocks = (dram_bit, dram_asp, nand_bit, nand_asp)

    widths = [h - l
              for blk in blocks
              for l, h in zip(blk["low_pct"], blk["high_pct"])]
    mean_width = sum(widths) / len(widths)
    one_sided = sum(sum(blk["one_sided"]) for blk in blocks)
    vocabulary = kpi["phrase_vocabulary"]
    caps = {entry["high"] - entry["low"] for entry in vocabulary.values() if entry["one_sided"]}

    def one_sided_phrases(block: dict) -> list[str]:
        return [phrase for phrase, flag in zip(block["phrases"], block["one_sided"]) if flag]

    # ── section one: settle what last quarter set ───────────────────────────
    # (a) the follow-up questions last quarter's local analysis left, closed as
    # this quarter's analysis §0 judged them; (b) last quarter's §8 thresholds,
    # settled against this quarter's filed numbers; (c) the company's own forward
    # disclosure -- which for SK hynix is words, not numbers.
    closure = stamped_block(staging, "followup_closure", period)
    prior_kpi = stamped_block(staging, "prior_kpi_settlement", period)
    last_period = display_period(shift_quarter(periods[-1], -1))
    for name, block in (("followup_closure", closure), ("prior_kpi_settlement", prior_kpi)):
        if block is not None and block["set_in"] != last_period:
            raise ValueError(f"series block `{name}` settles what was set in {block['set_in']!r}, "
                             f"but last quarter was {last_period!r}")
    # The phrase series reaches this quarter only once a filing has worded it;
    # until then nothing below may read its last cell as this quarter's.
    phrases_reach_quarter = iso_quarter(kq[-1]) == periods[-1]
    after = story.get("shareholder_return_after_quarter")
    story_values = {}
    if story.get("capex_2026_spoken"):
        story_values["capex_spoken"] = f"“{story['capex_2026_spoken']}”"
    if phrases_reach_quarter:
        # Only while the last cell IS this quarter: otherwise a finding that
        # quotes "this quarter's word" would quote last quarter's, and
        # `fill_story` stops the build on the missing name instead.
        story_values["dram_asp_prev"] = f"“{dram_asp['phrases'][-2]}”"
        story_values["dram_asp_now"] = f"“{dram_asp['phrases'][-1]}”"
    settled = []
    settled_prior: list[dict] = []
    open_prior: list[dict] = []
    prior_all_open = ""

    if closure is not None:
        items = closure["items"]
        unknown = sorted({item["verdict"] for item in items} - set(CLOSURE_ORDER))
        if unknown:
            raise ValueError(f"series block `followup_closure` has verdicts {unknown} "
                             f"outside {CLOSURE_ORDER}")
        counts = [sum(1 for item in items if item["verdict"] == label) for label in CLOSURE_ORDER]
        groups = [(label, [item for item in items if item["verdict"] == label])
                  for label in CLOSURE_ORDER]
        later = next((item for item in items if item.get("answered_after_quarter")), None)
        answered = (f"其中「{later['topic']}」在本季本地分析写成之后有了答案：{after['filed']} 报送的 6-K "
                    f"公布约 ₩{after['buyback_krw_bn'] / 1000:.1f}T 的回购注销，以及「{after['policy']}」的"
                    "回报政策 —— 它归下一季结算，这里的判定仍按本季业绩发布时的情况。"
                    if later is not None and after else "")
        settled.append({
            "ref": "EX_CLOSURE",
            "kind": "bars_labeled",
            "title": (f"上季 {len(items)} 条待验证问题："
                      + "、".join(f"{count} 条{label}" for label, count in zip(CLOSURE_ORDER, counts) if count)
                      + ("，没有一条完全验证" if counts[0] == 0 else "")),
            "xlabels": list(CLOSURE_ORDER),
            "values": counts,
            "legend": "问题条数",
            "fmt": "f0", "yfmt": "f0", "label_fmt": "f0",
            "ylab": "条",
            "note": ("".join(
                f"{label}的{cn_count(len(group))}条："
                + "；".join(f"{item['topic']}——{fill_story(item['finding'], story_values)}" for item in group)
                + "。"
                for label, group in groups if group) + answered),
            "src_extra": ("问题清单是上季本地分析稿的 Follow-up Questions，判定取自本季本地分析稿第 0 节；"
                          "每条的证据按业绩发布、电话会与半年报核过。"),
        })

    if prior_kpi is not None:
        def prior_actual(entry: dict) -> float | None:
            """This quarter's filed value for a settleable threshold, or None."""
            if entry["id"] == "dram_asp":
                return dram_asp["midpoint_pct"][-1] if phrases_reach_quarter else None
            raise ValueError(f"series block `prior_kpi_settlement` names {entry['id']!r}, "
                             "which this page does not know how to settle")

        prior_entries = prior_kpi["entries"]
        for entry in prior_entries:
            actual = prior_actual(entry) if "threshold" in entry else None
            if actual is None:
                open_prior.append(entry if "threshold" not in entry else
                                  {**entry, "status": "未申报", "why": "本季的用词还没有申报"})
            else:
                settled_prior.append({**entry, "actual": actual})
        held = [e for e in settled_prior if headroom(e["direction"], e["threshold"], e["actual"]) >= 0]
        if len(settled_prior) == 1:
            only = settled_prior[0]
            verdict = f"能用本季实际值结算的只有{spaced_before(only['short'])}一条，{'守住' if held else '已击穿'}"
        else:
            verdict = (f"能用本季实际值结算的 {len(settled_prior)} 条里 {len(held)} 条守住、"
                       f"{len(settled_prior) - len(held)} 条被击穿")
        asp_words = ""
        dram_entry = next((e for e in settled_prior if e["id"] == "dram_asp"), None)
        if dram_entry is not None:
            band = vocabulary[dram_asp["phrases"][-1]]
            up = dram_entry["direction"] == "up"
            clear = band["low"] >= dram_entry["threshold"] if up else band["high"] <= dram_entry["threshold"]
            straddles = band["low"] < dram_entry["threshold"] < band["high"]
            spoken = story.get("call_words", {}).get("dram_asp")
            spoken_number = re.search(r"(\d+(?:\.\d+)?)%", spoken or "")
            spoken_holds = (spoken_number is not None
                            and (float(spoken_number.group(1)) >= dram_entry["threshold"]) == up)
            asp_words = (f"DRAM 售价的上季阈值是「Q2 ≥ {signed(dram_entry['threshold'], 0)}」。"
                         f"半年报把本季写成 “{dram_asp['phrases'][-1]}”，本页读成 "
                         f"{band['low']:g}–{band['high']:g}%，"
                         + ("整段都在安全侧；" if clear else "区间跨过了阈值；" if straddles else "整段都已越线；")
                         + (f"电话会上的说法是 “{spoken}”，按它读也在安全侧。" if spoken and spoken_holds else
                            f"电话会上的说法是 “{spoken}”。" if spoken else ""))

        def open_reason(entry: dict) -> str:
            extra = ""
            if entry["id"] == "fy26_capex" and story.get("capex_2026_spoken"):
                extra = f"；电话会给的 2026 年口径是 {story_values['capex_spoken']}"
            if entry["id"] == "fy26_return" and after:
                extra = f"；{after['filed']} 的 6-K 已公布约 ₩{after['buyback_krw_bn'] / 1000:.1f}T 的回购注销"
            return f"{entry['short']}（{entry['status']}：{entry['why']}{extra}）"

        open_words = "；".join(open_reason(entry) for entry in open_prior)
        if settled_prior:
            settled.append(headroom_exhibit(
                f"上季 {len(prior_entries)} 条量化阈值：{verdict}"
                + (f"；{len(open_prior)} 条本季无法结算" if open_prior else ""),
                settled_prior,
                "actual",
                ("正值 = 仍在安全侧。" + asp_words
                 + (f"无法结算的{cn_count(len(open_prior))}条：{open_words}。" if open_prior else "")),
                ("阈值与方向逐字取自上季本地分析稿第 8 节，不是公司指引；实际值为本季申报值，"
                 "售价用词按本页的用词表读成区间、取中点（D）。"),
            ))
        else:
            # Nothing to draw a bar for: a headroom chart with no bars is not
            # an overview. The section description carries the list instead.
            prior_all_open = (f"上季 {len(prior_entries)} 条量化阈值本季都无法用申报值结算"
                              f"（{open_words}），原文见核对抽屉。")
        for entry in settled_prior:
            if entry["id"] != "dram_asp":
                continue
            gap = headroom(entry["direction"], entry["threshold"], entry["actual"])
            chart = threshold_exhibit(
                f"{entry['metric']}：{'守住' if gap >= 0 else '击穿'}上季阈值 {signed(entry['threshold'], 0)}",
                list(kq), rounded(dram_asp["midpoint_pct"]), entry["threshold"],
                fmt="pct1", ylab="环比 %",
                actual_name="DRAM 售价环比（用词中点）",
                threshold_name=f"上季阈值（安全侧在{'上方' if entry['direction'] == 'up' else '下方'}）",
                note=(f"阈值 {signed(entry['threshold'], 0)}，本季 “{dram_asp['phrases'][-1]}” 的中点 "
                      f"{entry['actual']:g}%，余量 {gap:+.1f}%。线上每一点都是一个用词区间的中点 —— "
                      "公司给的是区间不是数，区间本身见 Exhibit {EX_DASP}。"),
                src_extra=("用词取自 Form 424B4 的量价表"
                           + (f"与之后 6-K 定期报告里 {later_span} 的用词" if later_words else "")
                           + "；阈值为上季本地研究设定，不是公司指引。"))
            chart["xrot"] = 90
            settled.append(chart)

    # (c) What the company itself says about the quarter ahead: bit shipments,
    # in words. Everything from here to the end of the section settles the
    # words, because there is no number to settle against.
    word_charts_from = len(settled)
    example = max(range(len(kq)), key=lambda i: dram_asp["midpoint_pct"][i])
    settled.append(phrase_band_exhibit(
        "EX_DASP",
        (f"DRAM 平均售价的环比，全部以英文用词发布：{len(kq)} 个季度、"
         f"没有一个数字"),
        kq, dram_asp,
        note=(
            "色块是<b>用词允许的区间</b>，不是公司给的区间 —— 公司一个数字都没给。"
            f"本页把每个用词读成一个闭区间（例如 “{dram_asp['phrases'][example]}” 读成 "
            f"{dram_asp['low_pct'][example]:g}–{dram_asp['high_pct'][example]:g}%），"
            "映射规则一次性写死在数据文件里、对四条序列一视同仁。"
            "<b>没有菱形，是因为没有可以放上去的数。</b>本站其他页的第一节画的是"
            "「公司给的区间」对「随后报出来的实际值」；这一页两边是同一种用词，"
            "所以能结清的只有「用词留下多少不确定」。"
            f"四条序列 {len(widths)} 次读数里，区间平均宽 {mean_width:.1f} 个百分点，"
            f"最宽 {max(widths):.0f} 个百分点。"),
        src_extra=("Form 424B4「changes in our bit sales volumes and average selling "
                   "prices (in U.S. dollars) of our DRAMs」表，"
                   + (f"{later_span} 取自之后报送的 6-K 定期报告（Price Trends 段）；" if later_words else "")
                   + "区间为本页读法（D）。"),
    ))

    nand_asp_open = one_sided_phrases(nand_asp)
    settled.append(phrase_band_exhibit(
        "EX_NASP",
        (f"NAND 平均售价的环比：{len(nand_asp_open)} 次读数是单边的"
         + (f"，“{nand_asp_open[0]}” 没有上限" if nand_asp_open else "")),
        kq, nand_asp,
        note=(
            f"四条序列里有{cn_count(one_sided)}次用的是 “Over X% Increase”，<b>在申报文件里没有上界</b>。"
            + (f"画出来必须给一个上界，本页统一取「下限 + {caps.pop():g} 个百分点」，"
               if len(caps) == 1 else "画出来必须给一个上界，")
            + "<b>这个上界是画图约定，不是披露</b>，图上最宽的几格就是它。"
            "一个下界式的说法与一个区间不是同一种信息：对着下界，"
            "「没有低于」几乎是同义反复。"),
        src_extra=("Form 424B4 同一节的 NAND 表"
                   + (f"，{later_span} 取自之后报送的 6-K 定期报告" if later_words else "")
                   + "；单边用词的上界为本页约定（D）。"),
    ))

    dram_bit_mid, dram_asp_mid = dram_bit["midpoint_pct"], dram_asp["midpoint_pct"]
    nand_bit_mid, nand_asp_mid = nand_bit["midpoint_pct"], nand_asp["midpoint_pct"]
    price_moves = mean_abs(dram_asp_mid) > mean_abs(dram_bit_mid)
    quiet_volume = (sum(1 for v in dram_bit_mid if abs(v) <= 10) * 2 > len(kq)
                    and sum(1 for v in nand_bit_mid if abs(v) <= 10) * 2 > len(kq))
    biggest_asp = max(dram_asp_mid)
    asp_words = f"{cn_count(int(biggest_asp // 10) * 10)}多个点"
    extreme = abs(dram_bit_mid[-1]) <= 2 and dram_asp_mid[-1] >= 30
    settled.append({
        "ref": "EX_DRIVER",
        "kind": "grouped_bars",
        "title": ("DRAM 的量与价，各自的环比中值"
                  + ("：动的是价，而价是公司唯一不指引的那个" if price_moves else "")),
        "xlabels": list(kq),
        "xrot": 90,
        "groups": [
            {"name": "出货量环比（用词中值）", "color": "NAVY",
             "values": rounded(dram_bit_mid)},
            {"name": "平均售价环比（用词中值，美元计）", "color": "GOLD",
             "values": rounded(dram_asp_mid)},
        ],
        "bar_labels": False,
        "fmt": "pct1", "label_fmt": "pct1", "ylab": "环比 %",
        "zero_line": True,
        "note": (
            "<b>这张图是这一页的因果链。</b>公司每季给的下季指引只覆盖出货量，"
            "而把两根柱子放在一起就能看到："
            + ("出货量的中值多数季度在正负十个点以内，" if quiet_volume else "")
            + f"售价却能一季走出{asp_words}。"
            + ("所以<b>指引全部兑现、收入仍然不及预期，在结构上是可能的</b> —— "
               "被指引的那个变量本来就不是决定收入的那个。" if price_moves else "")
            + (f"{cn_quarter(kq[-1])}就是极端形态：出货量用词是 “{dram_bit['phrases'][-1]}”，"
               f"售价用词是 “{dram_asp['phrases'][-1]}”。" if extreme else "")),
        "src_extra": ("Form 424B4 的两张 DRAM 表"
                      + (f"与之后 6-K 定期报告里 {later_span} 的用词" if later_words else "")
                      + "；中值为区间中点（D）。"),
    })

    nand_open = [(phrase, "出货") for phrase in one_sided_phrases(nand_bit)] + \
                [(phrase, "售价") for phrase in one_sided_phrases(nand_asp)]
    wilder = (mean_abs(nand_bit_mid) > mean_abs(dram_bit_mid)
              and mean_abs(nand_asp_mid) > mean_abs(dram_asp_mid))
    dram_turn, nand_turn = first_upturn(dram_asp_mid), first_upturn(nand_asp_mid)

    def open_phrase_list(pairs: list[tuple[str, str]]) -> str:
        by_leg: dict[str, list[str]] = {}
        for phrase, leg in pairs:
            by_leg.setdefault(leg, []).append(f"“{phrase}”")
        return "、".join(" 与 ".join(phrases) + f" 的{leg}" for leg, phrases in by_leg.items())

    settled.append({
        "ref": "EX_NDRIVER",
        "kind": "grouped_bars",
        "title": ("NAND 的量与价"
                  + ("：同一形态，且价的摆幅更大" if mean_abs(nand_asp_mid) > mean_abs(nand_bit_mid) else "")),
        "xlabels": list(kq),
        "xrot": 90,
        "groups": [
            {"name": "出货量环比（用词中值）", "color": "NAVY",
             "values": rounded(nand_bit_mid)},
            {"name": "平均售价环比（用词中值，美元计）", "color": "GOLD",
             "values": rounded(nand_asp_mid)},
        ],
        "bar_labels": False,
        "fmt": "pct1", "label_fmt": "pct1", "ylab": "环比 %",
        "zero_line": True,
        "note": (
            ("闪存这条线上量与价都比 DRAM 摆得更凶，" if wilder else "")
            + (f"{cn_count(len(nand_open))}次单边用词（{open_phrase_list(nand_open)}）都在这里。"
               if nand_open else "")
            + "把两张图对读还有一层："
            + ("<b>DRAM 与 NAND 的价格拐点不同步</b>，" if dram_turn != nand_turn else "")
            + "而分产品收入按季只在中期报表附注里出现，本页读到的只有"
            + f"{cn_count(len(split_quarters))}个季度（{'、'.join(split_quarters)}），"
            + "其余季度无法按产品加权，"
            + ("本季见 Exhibit {EX_PRODUCT_Q}。"
               if all(q in prod["labels"] for q in (periods[-1], shift_quarter(periods[-1], -1),
                                                    shift_quarter(periods[-1], -4)))
               else "年度见 Exhibit {EX_MIX}。")),
        "src_extra": ("Form 424B4 的两张 NAND 表"
                      + (f"与之后 6-K 定期报告里 {later_span} 的用词" if later_words else "")
                      + "；中值为区间中点（D）。"),
    })

    # The chained band: what four quarters of words permit, against the one
    # disclosed answer. This is the only place the vocabulary can be scored:
    # the latest phrase quarter for which the audited product split exists both
    # for it and for the same quarter a year earlier.
    def chain(block_bit, block_asp, start, stop, bound):
        product = 1.0
        for i in range(start, stop):
            product *= (1 + block_bit[bound][i] / 100.0)
            product *= (1 + block_asp[bound][i] / 100.0)
        return (product - 1) * 100.0

    labels = prod["labels"]

    def prod_source(label: str) -> str:
        """Which filing printed this product-split cell (see the block's `_cell_sources`)."""
        return prod.get("_cell_sources", {}).get(label, "Form 424B4")

    scorable = [i for i, label in enumerate(kq)
                if i >= 3 and iso_quarter(label) in labels
                and shift_quarter(iso_quarter(label), -4) in labels]
    if scorable:
        i1 = scorable[-1] + 1
        i0 = i1 - 4
        now, then = labels.index(iso_quarter(kq[i1 - 1])), labels.index(shift_quarter(iso_quarter(kq[i1 - 1]), -4))
        dram_lo = chain(dram_bit, dram_asp, i0, i1, "low_pct")
        dram_hi = chain(dram_bit, dram_asp, i0, i1, "high_pct")
        nand_lo = chain(nand_bit, nand_asp, i0, i1, "low_pct")
        nand_hi = chain(nand_bit, nand_asp, i0, i1, "high_pct")
        dram_mid = chain(dram_bit, dram_asp, i0, i1, "midpoint_pct")
        dram_actual = pct_change(prod["dram"][now], prod["dram"][then])
        nand_actual = pct_change(prod["nand"][now], prod["nand"][then])
        contained = dram_lo <= dram_actual <= dram_hi and nand_lo <= nand_actual <= nand_hi
        settled.append({
            "ref": "EX_CHAIN",
            "kind": "grouped_bars",
            "title": ("把四个季度的用词连乘，再对上公司披露的同比答案："
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
                f"{cn_quarter(kq[i0])}到 {cn_quarter(kq[i1 - 1])}四个季度的出货量与售价用词逐季连乘，"
                "得到用词允许的收入增长区间；深色柱是公司在财务报表附注里披露的"
                "同期分产品收入同比。"
                + ("<b>实际值确实落在区间内 —— 但这不构成一次验证。</b>"
                   if contained else "<b>实际值落在区间之外。</b>")
                + f"DRAM 那一格的区间宽 {dram_hi - dram_lo:.0f} 个百分点"
                f"（{dram_lo:.0f}% 到 {dram_hi:.0f}%），"
                + ("一个这么宽的区间几乎不可能被证伪，落在里面因此接近同义反复。"
                   if contained and dram_hi - dram_lo >= 40 else "")
                + f"用中值连乘会得到 {dram_mid:.0f}%，比实际的 {dram_actual:.0f}% "
                f"{'高出' if dram_mid >= dram_actual else '低'} "
                f"{abs(dram_mid - dram_actual):.0f} 个百分点 —— "
                "<b>这就是用中值代替区间的代价"
                + ("，而它整个被区间的宽度吞掉了。</b>" if contained else "。</b>")
                + "还有一层同样被吞掉：售价用词以<b>美元</b>计，收入以<b>韩元</b>报告，"
                "两者之间隔着一个申报文件没有给的汇率项。"
                "在一个几十个百分点宽的区间里，几个百分点的汇率影响根本无从分辨 —— "
                "所以任何把美元售价乘上出货量、再声称与韩元收入「闭合」的桥，"
                "闭合的其实是区间的宽度，不是数据。"),
            "src_extra": ("用词取自 Form 424B4 的四张表"
                          + ("与之后 6-K 定期报告里 " + "、".join(q for q in kq[i0:i1] if q in later_words) + " 的用词"
                             if any(q in later_words for q in kq[i0:i1]) else "")
                          + "；实际同比取自" + spaced_before("与".join(dict.fromkeys(
                              [prod_source(labels[then]), prod_source(labels[now])])))
                          + " 的分产品收入。"
                          "连乘与同比为本页自算（D）。"),
        })

    # ── section two: the quarter ────────────────────────────────────────────
    highlights = []

    # The cycle facts the EX_REV note states. Derived, because both of them
    # moved when the axis did: on 22 quarters the window really did hold one
    # cycle, and the sentence saying so was true when it was written.
    trough = opm.index(min(opm))
    pre = opm[:periods.index(OLD_WINDOW[0])] if OLD_WINDOW[0] in periods else []
    prev_peak = opm.index(max(pre)) if pre else trough
    prev_trough = opm.index(min(pre)) if pre else trough

    def drawdown(lo: int, hi: int) -> tuple[int, int, float]:
        """Peak, and the deepest revenue trough that comes AFTER it, in a span.

        Taking the min over the whole span instead would return 2016Q1 for the
        first cycle -- the lowest quarter on the axis, but the one the cycle
        starts from rather than falls to, so the percentage would not be a
        drawdown at all.
        """
        peak = lo + revenue[lo:hi + 1].index(max(revenue[lo:hi + 1]))
        low = peak + revenue[peak:hi + 1].index(min(revenue[peak:hi + 1]))
        return peak, low, (revenue[low] / revenue[peak] - 1.0) * 100.0

    prev_pk, prev_low, prev_dd = drawdown(0, prev_trough)
    this_pk, this_low, this_dd = drawdown(prev_trough + 1, trough)
    neg_run = 0
    run = 0
    for value in opm:
        run = run + 1 if value < 0 else 0
        neg_run = max(neg_run, run)
    at_top = opm[-1] == max(opm[trough:])
    margin_gap = opm[prev_trough] - opm[trough]
    revenue_gap = abs(this_dd) - abs(prev_dd)

    qoq_now = pct_change(revenue[-1], revenue[-2])
    qoq_prev = pct_change(revenue[-2], revenue[-3])
    step_words = ("放缓到" if qoq_now < qoq_prev else "加快到" if qoq_now > qoq_prev else "持平于")
    highlights.append({
        "ref": "EX_REV",
        "kind": "bar_line_dual",
        "title": (f"{len(periods)} 季营收与营业利润率："
                  f"本季营收 ₩{revenue[-1] / 1000:.1f}T、营业利润率 {opm[-1]:.1f}%，"
                  f"环比增速从 {qoq_prev:.1f}% {step_words} {qoq_now:.1f}%"),
        "xlabels": list(periods),
        "xrot": 90,
        "bar": {"name": "营业收入（₩万亿）", "color": "BLUE",
                "values": tn(revenue), "yfmt": "f0"},
        "line": {"name": "营业利润率（右轴）", "color": "RED",
                 "values": rounded(opm, 2), "yfmt": "pct0"},
        "fmt": "f1", "label_fmt": "f1",
        "ylab": "₩万亿", "ylab2": "营业利润率 %",
        "note": (
            f"{len(periods)} 季装得下<b>两轮</b>完整的存储周期，而不是一轮 —— "
            f"这是把窗口从 22 季拉到 {len(periods)} 季之后最直接的变化。"
            f"上一轮的顶在 {periods[prev_peak]} 的 {opm[prev_peak]:.1f}%，"
            f"底在 {periods[prev_trough]} 的 {opm[prev_trough]:.1f}%；"
            f"这一轮的底在 {periods[trough]} 的 {opm[trough]:.1f}%，"
            + (f"顶是本季的 {opm[-1]:.1f}%。" if at_top else f"本季 {opm[-1]:.1f}%。")
            + "<b>两轮的形状不一样，而差别正在利润率这条线上</b>："
            f"上一轮下行只把利润率压到 {opm[prev_trough]:.1f}%"
            + ("，从没转负" if opm[prev_trough] >= 0 else "")
            + f"；这一轮压到 {opm[trough]:.1f}%，连续 {neg_run} 个季度为负。"
            + ("<b>而营收那排柱子上，两轮的差距要小得多</b>："
               if revenue_gap < margin_gap else "营收那排柱子上：")
            + f"上一轮从 {periods[prev_pk]} 的峰值跌到 {periods[prev_low]} 是 "
            f"{prev_dd:.1f}%，这一轮从 {periods[this_pk]} 跌到 {periods[this_low]} 是 "
            f"{this_dd:.1f}% —— {'深' if revenue_gap >= 0 else '浅'}了约 "
            f"{abs(revenue_gap):.0f} 个百分点，"
            f"而同一对周期里利润率的底差了 {margin_gap:.0f} 个百分点。"
            + ("<b>量的回撤解释不了利润率的回撤</b>，差额来自价格 —— "
               "而价格正是公司唯一不指引、也不给数字的那一项。" if revenue_gap < margin_gap else "")
            + "右轴按数据自算，负值段没有被截掉。"),
        "src_extra": ("各季业绩发布；利润率为营业利润 ÷ 营业收入（D），"
                      "公司披露的是四舍五入到整数的百分比，见核对表。"),
    })

    # What moved this quarter in the company's own words: last quarter's four
    # phrases beside this quarter's. Only once a filing has worded this
    # quarter -- otherwise the pair would be last quarter and the one before.
    legs = [("DRAM 出货量", dram_bit), ("DRAM 平均售价", dram_asp),
            ("NAND 出货量", nand_bit), ("NAND 平均售价", nand_asp)]

    def move_word(block: dict) -> str:
        now_mid, prev_mid = block["midpoint_pct"][-1], block["midpoint_pct"][-2]
        return "放缓" if now_mid < prev_mid else "加快" if now_mid > prev_mid else "持平"

    def words_source(quarter: str) -> str:
        return ("之后报送的 6-K 定期报告（Price Trends 段）" if quarter in later_words
                else "Form 424B4 的量价表")

    quarter_labels = [label for label in labels if re.match(r"^\d{4}Q[1-4]$", label)]
    this_q, prev_q, yago_q = periods[-1], shift_quarter(periods[-1], -1), shift_quarter(periods[-1], -4)
    has_split = all(q in labels for q in (this_q, prev_q, yago_q))
    split_growth = ({key: pct_change(prod[key][labels.index(this_q)], prod[key][labels.index(prev_q)])
                     for key in ("dram", "nand")} if has_split else {})
    if phrases_reach_quarter:
        both_slow = move_word(dram_asp) == "放缓" and move_word(nand_asp) == "放缓"
        nand_volume_turn = nand_bit["midpoint_pct"][-2] < 0 < nand_bit["midpoint_pct"][-1]
        nand_outgrew = bool(split_growth) and split_growth["nand"] > split_growth["dram"]
        call = story.get("call_words", {})
        spoken_pairs = [(leg, call[key], block["phrases"][-1]) for leg, key, block in (
            ("出货", "dram_bit", dram_bit), ("售价", "dram_asp", dram_asp)) if call.get(key)]
        highlights.append({
            "ref": "EX_PRICE_STEP",
            "kind": "grouped_bars",
            "title": (f"本季量价用词：DRAM 售价环比从 “{dram_asp['phrases'][-2]}” {move_word(dram_asp)}到 "
                      f"“{dram_asp['phrases'][-1]}”，NAND 从 “{nand_asp['phrases'][-2]}” "
                      f"{move_word(nand_asp)}到 “{nand_asp['phrases'][-1]}”"),
            "xlabels": [name for name, _ in legs],
            "groups": [
                {"name": f"上季 {kq[-2]}（用词中点）", "color": "GRAY",
                 "values": [block["midpoint_pct"][-2] for _, block in legs]},
                {"name": f"本季 {kq[-1]}（用词中点）", "color": "NAVY",
                 "values": [block["midpoint_pct"][-1] for _, block in legs]},
            ],
            "bar_labels": True,
            "fmt": "pct0", "label_fmt": "pct0", "ylab": "环比 %",
            "zero_line": True,
            "note": (
                "每根柱子都是一个用词区间的中点（D），区间见核对抽屉里的用词表。"
                + ("<b>两条售价线都在减速。</b>" if both_slow else "")
                + (f"NAND 本季收入环比 {signed(split_growth['nand'])}、跑赢 DRAM 的 {signed(split_growth['dram'])}"
                   "（Exhibit {EX_PRODUCT_Q}），"
                   + (f"靠的不是售价加速，而是出货从 “{nand_bit['phrases'][-2]}” 转成 “{nand_bit['phrases'][-1]}”。"
                      if nand_volume_turn and move_word(nand_asp) != "加快" else "量价两条腿都有份。")
                   if nand_outgrew else "")
                + ("电话会与半年报对同一季 DRAM 用了不同的词：" + "；".join(
                    f"{leg}上电话会说 “{spoken}”、半年报记为 “{filed}”" for leg, spoken, filed in spoken_pairs) + "。"
                   if spoken_pairs else "")
                + "售价用词以美元计，收入以韩元报告，两者之间隔着一个汇率项。"),
            "src_extra": (f"上季用词取自{spaced_before(words_source(kq[-2]))}，"
                          f"本季取自{spaced_before(words_source(kq[-1]))}"
                          + ("；电话会用词取自 2Q26 业绩电话会开场陈述" if spoken_pairs else "") + "。"),
        })

    if has_split:
        now_i, prev_i, yago_i = (labels.index(q) for q in (this_q, prev_q, yago_q))
        share = {key: [prod[key][i] / prod["total"][i] * 100 for i in (prev_i, now_i)] for key in ("dram", "nand")}
        highlights.append({
            "ref": "EX_PRODUCT_Q",
            "kind": "grouped_bars",
            "title": (f"本季分产品收入：NAND 环比 {signed(split_growth['nand'])}、DRAM {signed(split_growth['dram'])}，"
                      f"NAND 占收入从 {share['nand'][0]:.1f}% "
                      f"{'升到' if share['nand'][1] >= share['nand'][0] else '降到'} {share['nand'][1]:.1f}%"),
            "xlabels": ["DRAM", "NAND 闪存", "其他"],
            "groups": [
                {"name": f"{yago_q}（去年同期）", "color": "GRAY",
                 "values": tn([prod[key][yago_i] for key in ("dram", "nand", "other")])},
                {"name": f"{prev_q}（上季）", "color": "MBLUE",
                 "values": tn([prod[key][prev_i] for key in ("dram", "nand", "other")])},
                {"name": f"{this_q}（本季）", "color": "NAVY",
                 "values": tn([prod[key][now_i] for key in ("dram", "nand", "other")])},
            ],
            "bar_labels": True,
            "fmt": "f1", "label_fmt": "f1", "ylab": "₩万亿",
            "note": (
                "<b>这是公司申报的分产品收入，不是估算。</b>"
                f"本季 DRAM 占收入 {share['dram'][1]:.1f}%、NAND {share['nand'][1]:.1f}%；"
                f"同比 DRAM {signed(pct_change(prod['dram'][now_i], prod['dram'][yago_i]))}、"
                f"NAND {signed(pct_change(prod['nand'][now_i], prod['nand'][yago_i]))}。"
                "季度分产品收入只在中期报表附注里出现，本页读到的 SEC 申报一共印了"
                f"{cn_count(len(quarter_labels))}个季度（{'、'.join(quarter_labels)}）；"
                "每一季都只有收入，没有分产品的利润。"),
            "src_extra": ("、".join(dict.fromkeys(prod_source(labels[i]) for i in (yago_i, prev_i, now_i)))
                          + "；环比、同比与占比为自算（D）。"),
        })

    nonop = pre_tax = nonop_share = None
    release_silent = False
    components: list[dict] = []
    if below is not None:
        pre_tax = below["profit_before_tax"]
        nonop = [p - o for p, o in zip(pre_tax, below["operating_profit"])]
        nonop_share = nonop[-1] / pre_tax[-1] * 100.0
        tax = pre_tax[-1] - below["net_income"][-1]
        net_above_revenue = below["net_income"][-1] > revenue[-1]
        # The quarter's own release says nothing below net income; whether any
        # later filing itemised the gap is a separate fact, carried by the block.
        release_silent = bool(story.get("release_stops_at_net_income"))
        components = below.get("components") or []
        highlights.append({
            "ref": "EX_BELOW",
            "kind": "grouped_bars",
            "title": (f"营业利润、税前利润、净利润：本季税前比营业多出 "
                      f"₩{nonop[-1] / 1000:.1f}T"
                      + ("，而季度发布里对此一个字都没有" if release_silent else "")),
            "xlabels": list(below["periods"]),
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
                (f"<b>净利润高过营业收入</b>：本季营收 ₩{revenue[-1] / 1000:.1f}T、"
                 f"净利 ₩{below['net_income'][-1] / 1000:.1f}T，净利率 {netm[-1]:.0f}%。"
                 if net_above_revenue else "")
                + "差额来自营业利润以下。税前减营业利润 = "
                f"₩{nonop[-1] / 1000:.2f}T 的营业外净收益，"
                "是上一季同一算法的 "
                f"{nonop[-1] / nonop[-2]:.1f} 倍；"
                "税前减净利 = "
                f"₩{tax / 1000:.2f}T 的所得税，"
                f"有效税率 {tax / pre_tax[-1] * 100:.1f}%。"
                "<b>这三个数都是两条已印出来的行相减，不是估计。</b>"
                + (f"税前那一行印在{spaced_after(story['pretax_printed_in'])}里 —— "
                   "公司自己的季度业绩发布只印到净利润为止，"
                   f"对这笔占税前{cn_fraction(nonop_share / 100)}的营业外收益没有任何拆分或说明；"
                   if release_silent and story.get("pretax_printed_in") else "")
                + (f"拆分要等之后{spaced_before(below['components_printed_in'])}，见 Exhibit {{EX_NONOP}}。"
                   if components else "本页读过的文件都没有给出它的构成。")
                + "本页不发布任何「剔除一次性后的净利润」：那需要假设这笔收益按平均税率纳税，"
                "而申报没有单独给出它的税负。"),
            "src_extra": (f"Form 6-K（{latest['release_date']}）的 Preliminary Results 表；"
                          "税负、营业外净额与有效税率为两行相减（D）。"),
        })
        if components:
            parts_total = sum(c["value"] for c in components)
            # The series carries the two printed rows to 0.1bn, so their
            # difference can sit up to 0.1bn off the million-won components.
            closes = abs(parts_total - nonop[-1]) <= 0.1 + 1e-9
            floor = abs(parts_total) * 0.01
            big = [c for c in components if abs(c["value"]) >= floor]
            small = [c for c in components if abs(c["value"]) < floor]
            bars = [(c["line"] + (" D" if c.get("derived") else ""), c["value"]) for c in big]
            if small:
                bars.append((f"其余{cn_count(len(small))}项合计 D", sum(c["value"] for c in small)))
            top = sorted(big, key=lambda c: -c["value"])[:2]
            highlights.append({
                "ref": "EX_NONOP",
                "kind": "grouped_bars",
                "title": (f"税前比营业利润多出的 ₩{nonop[-1] / 1000:.1f}T："
                          + "、".join(f"₩{c['value'] / 1000:.1f}T 是{c['line']}" for c in top)),
                "xlabels": [name for name, _ in bars],
                "groups": [{"name": f"{periods[-1]}（₩万亿）", "color": "NAVY",
                            "values": tn([value for _, value in bars])}],
                "bar_labels": True,
                "fmt": "f2", "label_fmt": "f2", "ylab": "₩万亿",
                "zero_line": True,
                "note": (
                    f"各项取自{spaced_before(below['components_printed_in'])}，那份报表经外部审阅、未经审计。"
                    + ("各项相加等于税前减营业利润（差额只在业绩表舍入到 ₩0.1bn 的那一位里）。" if closes else
                       f"各项相加与税前减营业利润差 ₩{abs(parts_total - nonop[-1]):,.1f}bn。")
                    + "标 D 的是同一附注里收益行减费用行的净额"
                    + (f"，「其余{cn_count(len(small))}项」是占营业外净额不到百分之一的"
                       + "、".join(c["line"] for c in small) if small else "")
                    + "。"
                    + (f"{top[0]['line']}与{top[1]['line']}相加，在电话会的精度上正好是 CFO 说的「投资资产出售与估值收益」；"
                       if len(top) == 2 and story.get("spoken_investment_gain_krw_tn") is not None
                       and round((top[0]["value"] + top[1]["value"]) / 1000, 1)
                       == story["spoken_investment_gain_krw_tn"] else "")
                    + "半年报没有说明它们来自哪一笔投资，本页也不替它补上。"
                    "季度业绩发布只印到净利润为止。"),
                "src_extra": ("Form 6-K（半年报）合并中期损益表、附注 24「金融收益与费用」、"
                              "附注 25「其他收益与费用」的三个月栏；净额与合计为自算（D）。"),
            })

    gap = [None if n is None or o is None else n - o for n, o in zip(netm, opm)]
    wide_gaps = [i for i, g in enumerate(gap) if g is not None and abs(g) > 10.0]
    widest_four = sorted(sorted(wide_gaps, key=lambda i: -abs(gap[i]))[:4])
    in_old_window = [i for i in wide_gaps if OLD_WINDOW[0] <= periods[i] < OLD_WINDOW[1]]
    before_old = [i for i in wide_gaps if periods[i] < OLD_WINDOW[0]]
    largest_now = bool(wide_gaps) and abs(gap[-1]) == max(abs(gap[i]) for i in wide_gaps)
    over_hundred = netm[-1] is not None and netm[-1] > 100
    fy_q4 = periods.index("2021Q4")
    fy2021 = sum(net[i] for i, p in enumerate(periods) if p.startswith("2021"))

    highlights.append({
        "ref": "EX_MARGIN",
        "kind": "lines",
        "title": (f"营业利润率与净利率：本季净利率 {netm[-1]:.0f}%"
                  + ("，是会计口径而不是经营口径" if netm[-1] - opm[-1] > 10 else "")),
        "xlabels": list(periods),
        "series": [
            {"name": "营业利润率", "values": rounded(opm, 2), "color": "NAVY"},
            {"name": "净利率", "values": rounded(netm, 2), "color": "GOLD"},
        ],
        "fmt": "pct1", "yfmt": "pct1", "label_fmt": "pct1",
        "end_label": True, "zero_line": True,
        "ylab": "%", "xstep": LONG_STEP,
        "note": (
            f"两条线在 {len(periods)} 季里分开过 {len(wide_gaps)} 次超过 10 个百分点，"
            "最大的四次是 "
            + "、".join(f"{periods[i]}（{gap[i]:+.0f}pp）" for i in widest_four) + "。"
            "此前这里写的是「只有最后一格劈开」—— 那句话在 22 季的窗口上"
            f"就已经不对：{len(in_old_window)} "
            "次超过 10pp 的分开发生在那个窗口内、且不是最后一格。"
            f"接上 2016–2020 之后又多了 {len(before_old)} 次。"
            + ("本季这一格仍然是其中最大的一次" if largest_now else "")
            + ("，而且方向特殊：净利率跨过 100%。" if largest_now and over_hundred else
               "。" if largest_now else "")
            + ("<b>一家制造业公司的净利率高于 100%，说明这一季的利润多数不是卖东西赚的</b>，"
               + ("见 Exhibit {EX_BELOW}。" if below is not None else "。")
               + "跨季比较净利润在这一格失效，营业利润仍然可比。" if over_hundred else "")
            + "<b>2021 年第四季这一格此前是空的，而它从来不该是空的。</b>"
            "那期发布的<b>正文</b>确实只写了当季营收与营业利润，"
            f"但同一篇里随文那张业绩表印着当季净利润 {net[fy_q4]:,.0f} 与当季营业利润率 "
            f"{fin['operating_margin_pct_disclosed'][fy_q4]}% —— "
            "本页读了正文没读表，把一处排版差异记成了公司没披露。"
            f"补上之后 2021 年四季净利润相加正好回到那期印出的全年 {fy2021:,.0f}。"),
        "src_extra": "各季业绩发布；两条率均为本页自算（D）。",
    })

    # Capital intensity: the audited years, then the reviewed halves. A half's
    # revenue is the sum of its two quarters in the series, so it cannot drift
    # from the quarterly bars above.
    fy_labels = list(ann["years"])
    fy_ratio = [c / r * 100.0 for c, r in zip(ann["capital_expenditures"], ann["revenue"])]
    halves = staging.get("half_year_capex_krw_bn")

    def half_revenue(half: str) -> float:
        first = 1 if half.endswith("H1") else 3
        return sum(revenue[periods.index(f"{half[:4]}Q{q}")] for q in (first, first + 1))

    def half_words(half: str) -> str:
        return f"{half[:4]} 年{'上' if half.endswith('H1') else '下'}半年"

    hy_ratio = ([c / half_revenue(h) * 100.0 for h, c in zip(halves["periods"], halves["capital_expenditures"])]
                if halves else [])
    if halves:
        audited_q = staging["quarterly_audited_krw_bn"]
        q1_ratio = [(p, c / r * 100.0) for p, c, r in zip(audited_q["periods"], audited_q["capital_expenditures"],
                                                          audited_q["revenue"])]
        sheet = staging["balance_sheet_krw_bn"]
        cash_now = sheet["net_cash"][-1] if sheet["periods"][-1] == periods[-1] else None
        ratio_to_year = hy_ratio[-1] / fy_ratio[-1]
        rev_multiple = half_revenue(halves["periods"][-1]) / half_revenue(halves["periods"][0])
        capex_growth = pct_change(halves["capital_expenditures"][-1], halves["capital_expenditures"][0])
        highlights.append({
            "ref": "EX_INTENSITY",
            "kind": "grouped_bars",
            "title": (f"资本开支占收入：{half_words(halves['periods'][-1])} {hy_ratio[-1]:.1f}%，"
                      + (f"约为 {fy_labels[-1]} 全年 {fy_ratio[-1]:.1f}% 的一半" if 0.4 <= ratio_to_year <= 0.6
                         else f"是 {fy_labels[-1]} 全年 {fy_ratio[-1]:.1f}% 的 {ratio_to_year * 100:.0f}%")),
            "xlabels": fy_labels + list(halves["periods"]),
            "groups": [{"name": "资本开支占收入", "color": "NAVY",
                        "values": rounded(fy_ratio + hy_ratio, 2)}],
            "bar_labels": True,
            "fmt": "pct1", "label_fmt": "pct1", "ylab": "占收入 %",
            "note": (
                "资本开支 = 购置不动产、厂房及设备的现金流出（不含无形资产）：全年取自 Form 424B4 的审计现金流量表，"
                "半年取自之后报送的半年报 6-K 的中期现金流量表，口径相同；半年收入取两季之和。"
                f"同样比上半年：{half_words(halves['periods'][0])} {hy_ratio[0]:.1f}%、"
                f"{half_words(halves['periods'][-1])} {hy_ratio[-1]:.1f}%。"
                + ("第一季就已经看得到：" + "、".join(f"{p} {v:.1f}%" for p, v in q1_ratio)
                   + "（Form 424B4 中期报表）。" if len(q1_ratio) >= 2 else "")
                + f"<b>比率变小主要是分母</b>：上半年收入是去年同期的 {rev_multiple:.1f} 倍，"
                f"资本开支只多了 {capex_growth:.0f}%。"
                + (f"季末净现金 ₩{cash_now / 1000:.1f}T（公司口径）。" if cash_now is not None else "")
                + "反过来也成立：收入回落时这个比率会机械性回升。"),
            "src_extra": ("Form 424B4 审计现金流量表与中期报表；Form 6-K（半年报）中期现金流量表；"
                          "业绩发布的净现金；比率为自算（D）。"),
        })

    # ── the structural series: product split and customer concentration ─────
    # The quarter's product split is drawn above; these are the long views --
    # the audited years, and every period a filing names a large customer --
    # so they sit with the routine series in section four.
    structure = []
    annual = [i for i, label in enumerate(labels) if label.startswith("FY")]
    dram_pct = [prod["dram_pct"][i] for i in annual]
    adds_up = all(abs(prod["dram"][i] + prod["nand"][i] + prod["other"][i] - prod["total"][i]) <= 1
                  and prod["total"][i] == ann["revenue"][annual.index(i)]
                  for i in annual)
    structure.append({
        "ref": "EX_MIX",
        "kind": "grouped_bars",
        "title": (f"分产品收入（年度）：DRAM 占比从 {dram_pct[0]:.1f}% "
                  f"{'升到' if dram_pct[-1] >= dram_pct[0] else '降到'} {dram_pct[-1]:.1f}%"),
        "xlabels": [labels[i] for i in annual],
        "groups": [
            {"name": "DRAM", "color": "NAVY", "values": tn([prod["dram"][i] for i in annual])},
            {"name": "NAND 闪存", "color": "BLUE", "values": tn([prod["nand"][i] for i in annual])},
            {"name": "其他产品", "color": "GOLD", "values": tn([prod["other"][i] for i in annual])},
        ],
        "bar_labels": True,
        "fmt": "f1", "label_fmt": "f1", "ylab": "₩万亿",
        "note": (
            "<b>这是公司披露的分产品收入，不是估算。</b>"
            "它是审计报表附注里的口径"
            + (f"，{cn_count(len(annual))}年相加逐年等于合并收入。" if adds_up else "。")
            + "季度数只在中期报表附注里出现：本页读到的 SEC 申报一共印了"
            f"{cn_count(len(quarter_labels))}个季度（{'、'.join(quarter_labels)}）"
            + ("，本季的拆分见 Exhibit {EX_PRODUCT_Q}。" if has_split else "。")
            + "另有一条更硬的边界写在同一份申报文件里：公司称其决策层"
            "不接收任何组成部分的分部财务信息，因此财务报表中不含分部信息，"
            "只有单一报告分部。"),
        "src_extra": "Form 424B4 note 24(2)；审计值。",
    })

    # Customer concentration, every period a filing names a customer over 10%:
    # the audited years and the interim periods, in order of their end date.
    # Shares are compared across period lengths (a share is a share); amounts
    # are not drawn, because a half-year amount beside a full-year one is not
    # comparable. Each filing labels its customers 'A' / 'B' per period, so
    # nothing here says two periods' 'A' is one customer.
    cp = cust["periods"]
    shares, seconds = cust["largest_customer_pct"], cust["second_customer_pct"]
    fy_at = [i for i, p in enumerate(cp) if p.startswith("FY")]
    interim_at = [i for i, p in enumerate(cp) if not p.startswith("FY")]
    none_years = [cp[i] for i in fy_at if shares[i] is None]
    shown_years = [i for i in fy_at if shares[i] is not None]
    last_fy = shown_years[-1]
    last_interim = interim_at[-1] if interim_at else None
    fell = last_interim is not None and last_interim > last_fy and shares[last_interim] < shares[last_fy]
    two_now = last_interim is not None and seconds[last_interim] is not None
    span = int(cp[last_fy][2:]) - int(cp[fy_at[0]][2:])
    year_share = shares[last_fy] / 100

    def period_words(label: str) -> str:
        if label.startswith("FY"):
            return f"{label[2:]} 年全年"
        return (f"{label[:4]} 年第{cn_ordinal(int(label[-1]))}季" if "Q" in label else half_words(label))

    interim_words = "；".join(
        f"{period_words(cp[i])} {shares[i]:g}%"
        + (f"（另一客户 {seconds[i]:g}%）" if seconds[i] is not None else "")
        for i in interim_at)
    structure.append({
        "ref": "EX_CUST",
        "kind": "grouped_bars",
        "title": ("最大单一客户占收入："
                  + (f"{none_years[0]} 不足 10%，" if none_years else "")
                  + f"{cp[last_fy]} 升到 {shares[last_fy]:g}%"
                  + (f"，{period_words(cp[last_interim])}回落到 {shares[last_interim]:g}%" if fell else "")
                  + ("，且第二个客户也超过 10%" if two_now else "")),
        "xlabels": list(cp),
        "groups": [
            {"name": "最大单一客户", "color": "NAVY", "values": list(shares)},
            {"name": "第二个超过 10% 的客户", "color": "GOLD", "values": list(seconds)},
        ],
        "bar_labels": True,
        "fmt": "pct1", "label_fmt": "pct2", "ylab": "占收入 %",
        "note": (
            "审计与审阅报表附注按规则列示占收入 10% 以上的客户，不点名："
            + "".join(f"{year} 没有任何单一客户达到 10%，" for year in none_years)
            + "，".join(f"{cp[i]} 是 {shares[i]:g}%" for i in shown_years) + "。"
            + (f"{cn_count(span)}年之内，公司从「没有一个客户重要到需要披露」变成"
               f"「{'近' if year_share < 1 / 4 else ''}{cn_fraction(year_share)}的收入来自一个客户」。"
               if none_years and none_years[0] == cp[fy_at[0]] else "")
            + (f"中期附注是同一口径：{interim_words}。" if interim_at else "")
            + ("<b>最新的中期读数比全年低了一截，而且出现了第二个超过 10% 的客户</b> —— "
               "集中度在往下走，不是往上。" if fell and two_now else "")
            + "附注里的「客户 A」「客户 B」逐期标注，本页不假定两期的 A 是同一家。"
            + "".join(f"{year} 那一格没有柱子，是因为当年没有需要披露的客户，"
                      "不是数据缺失。" for year in none_years)),
        "src_extra": ("Form 424B4 note 4(2)（审计年度与第一季中期）、之后报送的半年报 6-K note 4(2)（上半年，"
                      "经审阅）；客户名称未披露。"),
    })

    # ── section three: what to watch ────────────────────────────────────────
    # This quarter's local analysis, §8: five rows, six thresholds (the capex
    # row carries two). What a filed series can measure is charted; what it
    # cannot is named with its reason in the description and the drawer.
    following = display_period(shift_quarter(periods[-1], 1))
    if thresholds.get("for_period") and thresholds["for_period"] != following:
        raise ValueError(f"series block `next_kpi` is stamped for {thresholds['for_period']!r}, "
                         f"but the next quarter is {following!r}: update it with the roll")
    latest_half = (halves["periods"][-1], hy_ratio[-1]) if halves else (fy_labels[-1], fy_ratio[-1])

    def next_current(entry: dict) -> float | None:
        """This quarter's filed value for a next-quarter threshold, or None."""
        known = {
            "q3_revenue": lambda: revenue[-1] / 1000.0,
            "dram_asp": lambda: dram_asp["midpoint_pct"][-1] if phrases_reach_quarter else None,
            "opm": lambda: opm[-1],
            "capex_ratio": lambda: latest_half[1],
        }
        if entry["id"] not in known:
            raise ValueError(f"series block `next_kpi` names {entry['id']!r}, which this page "
                             "does not know how to measure")
        return known[entry["id"]]()

    watch, unmeasured = [], []
    for entry in thresholds["entries"]:
        current_value = next_current(entry) if "threshold" in entry else None
        if current_value is None:
            unmeasured.append(entry if "threshold" not in entry else
                              {**entry, "status": "未申报", "why": "本季的用词还没有申报"})
        else:
            watch.append({**entry, "current": current_value})
    stance = thresholds.get("stance") or {}
    guide_next = story.get("next_shipment_guidance")
    behind = [e for e in watch if headroom(e["direction"], e["threshold"], e["current"]) < 0]
    if len(behind) == 1:
        behind_words = (f"{behind[0]['short']}是唯一还在阈值另一侧的一条"
                        + ("（它的阈值是下一季的数）" if behind[0]["id"] == "q3_revenue" else ""))
    elif behind:
        behind_words = f"{len(behind)} 条还在阈值另一侧"
    else:
        behind_words = "当前值全部在安全侧"
    revenue_entry = next((e for e in watch if e["id"] == "q3_revenue"), None)
    need = (revenue_entry["threshold"] * 1000.0 / revenue[-1] - 1) * 100.0 if revenue_entry else None
    unmeasured_words = "；".join(f"{e['short']}（{e['status']}：{e['why']}）" for e in unmeasured)

    next_ex = [headroom_exhibit(
        f"下季 {len(watch)} 条量化阈值：{behind_words}",
        watch, "current",
        ("正值 = 仍在安全侧。阈值与方向取自本季本地分析稿第 8 节，<b>不是公司指引</b> —— "
         "SK hynix 不发布任何财务指引"
         + (f"，它对下一季给的唯一数字是出货用词：DRAM “{guide_next['dram']}”、NAND “{guide_next['nand']}”。"
            if guide_next else "。")
         + (f"Q3 营收的当前值是本季营收，要到阈值，第三季需要环比增长 {need:.1f}%。" if need is not None else "")
         + (f"另有{cn_count(len(unmeasured))}条画不了：{unmeasured_words}；原文见核对抽屉。" if unmeasured else "")),
        ("当前值：营收与营业利润率为本季申报值（营业利润率按两个韩元金额自算，D）；"
         "DRAM 售价为本季用词区间的中点（D）；资本强度为最近一个申报期的资本开支 ÷ 收入（D）。"))]

    def threshold_line(entry: dict) -> dict:
        eid = entry["id"]
        side = "上方" if entry["direction"] == "up" else "下方"
        if eid == "q3_revenue":
            upgrade = stance.get("upgrade_revenue_krw_tn")
            ret = stance.get("upgrade_return_krw_tn")
            met = after is not None and ret is not None and after["buyback_krw_bn"] / 1000.0 >= ret
            chart = threshold_exhibit(
                f"Q3 营收：下季阈值 {unit_text('krw_tn', entry['threshold'])}，当前 {unit_text('krw_tn', entry['current'])}",
                list(periods), tn(revenue), entry["threshold"], fmt="f1", ylab="₩万亿",
                actual_name="营业收入（₩万亿）", threshold_name=f"下季阈值（安全侧在{side}）",
                note=(f"阈值是第三季的营收，当前值是本季的：要到 {unit_text('krw_tn', entry['threshold'])}，"
                      f"第三季营收需要环比增长 {need:.1f}%（本季环比 {qoq_now:.1f}%）。"
                      + (f"报告给的锚区间是 {unit_text('krw_tn', entry['threshold'])}–"
                         f"{unit_text('krw_tn', entry['anchor_high'])}。" if entry.get("anchor_high") else "")
                      + (f"它把「第三季营收 ≥ {unit_text('krw_tn', upgrade)}、且年内公布 ≥ {unit_text('krw_tn', ret)} "
                         "的回购或特别股息」写成上调条件"
                         + (f" —— 后一半已由 {after['filed']} 的 6-K 满足（约 ₩{after['buyback_krw_bn'] / 1000:.1f}T "
                            "回购注销），剩下的是营收。" if met else "。")
                         if upgrade is not None and ret is not None else "")),
                src_extra="各季业绩发布；阈值为本季本地研究设定，不是公司指引。",
                xstep=LONG_STEP)
        elif eid == "dram_asp":
            band = vocabulary[dram_asp["phrases"][-1]]
            chart = threshold_exhibit(
                f"{entry['metric']}：下季阈值 {signed(entry['threshold'], 0)}，当前 {signed(entry['current'], 0)}"
                f"（“{dram_asp['phrases'][-1]}” 的中点）",
                list(kq), rounded(dram_asp["midpoint_pct"]), entry["threshold"], fmt="pct1", ylab="环比 %",
                actual_name="DRAM 售价环比（用词中点）", threshold_name=f"下季阈值（安全侧在{side}）",
                note=((f"报告要看的是{entry['report_source']}，" if entry.get("report_source") else "")
                      + "本页只用公司申报，所以这里画的是公司每季的混合售价用词，两者口径不同。"
                      f"本季 “{dram_asp['phrases'][-1]}” 读成 {band['low']:g}–{band['high']:g}%，"
                      + ("整段在阈值之上。" if band["low"] >= entry["threshold"] else "区间碰到了阈值。")
                      + (f"报告同时写了上行线 {signed(entry['upper_trigger'], 0)}：高于它读作递延出货回补。"
                         if entry.get("upper_trigger") is not None else "")
                      + "线上每一点是用词区间的中点，区间见 Exhibit {EX_DASP}。"),
                src_extra=("用词取自 Form 424B4 的量价表"
                           + (f"与之后 6-K 定期报告里 {later_span} 的用词" if later_words else "")
                           + "；阈值为本季本地研究设定，不是公司指引。"))
            chart["xrot"] = 90
        elif eid == "opm":
            line = entry["threshold"]
            cross_line = crossings(opm, line)
            # How long the previous cycle held above the threshold once it got there.
            peak_to_below = next((i - prev_peak for i in range(prev_peak + 1, len(opm))
                                  if opm[i] < line), 0)
            chart = threshold_exhibit(
                f"营业利润率：下季阈值 {line:.1f}%，当前 {opm[-1]:.1f}%",
                list(periods), rounded(opm, 2), line, fmt="pct1", ylab="%",
                actual_name="营业利润率", threshold_name=f"下季阈值（安全侧在{side}）",
                note=("红线来自本季本地分析稿第 8 节：连续两季低于它，读作利润率正常化启动。"
                      "它不是公司指引，也不是公司披露的目标。"
                      f"{len(periods)} 季里这条线穿过阈值 {len(cross_line)} 次："
                      + "、".join(f"{periods[i]}（{opm[i - 1]:.1f}% → {opm[i]:.1f}%）" for i in cross_line) + "。"
                      + (f"{line:g}% 不是「本轮独有」的高度：{periods[prev_peak]} 的 {opm[prev_peak]:.1f}% 就在它之上，"
                         f"那是上一轮周期；上一轮到过之后，只用了 {peak_to_below} 个季度就掉回它以下。"
                         "所以跌破它不等于「这一轮的超额利润消失了」，而是「回到了上一轮触顶后同样的位置」。"
                         if opm[prev_peak] >= line else "")),
                src_extra="各季业绩发布；利润率为自算（D），阈值为本季本地研究设定，不是公司指引。",
                xstep=LONG_STEP)
            chart["xrot"] = 90
        elif eid == "capex_ratio":
            second = next((e for e in unmeasured if e["id"] == "capex_2027"), None)
            chart = threshold_exhibit(
                f"资本开支占收入：下季阈值 {entry['threshold']:.1f}%，当前 {entry['current']:.1f}%（{latest_half[0]}）",
                fy_labels + ([latest_half[0]] if halves else []),
                rounded(fy_ratio + ([latest_half[1]] if halves else []), 2), entry["threshold"],
                fmt="pct1", ylab="占收入 %",
                actual_name="资本开支占收入", threshold_name=f"下季阈值（安全侧在{side}）",
                note=("阈值来自本季本地分析稿第 8 节，盯的是 2026 年以后：比率回到它之上，读作资本强度担忧重启"
                      + ("；同一行的另一半是 2027 年资本开支指引，公司还没给" if second else "")
                      + "。"
                      f"{fy_labels[0]}–{fy_labels[-1]} 三年是 " + "、".join(f"{v:.1f}%" for v in fy_ratio)
                      + (f"，{half_words(latest_half[0])}降到 {latest_half[1]:.1f}%，见 Exhibit {{EX_INTENSITY}}。"
                         if halves else "。")),
                src_extra=("Form 424B4 审计现金流量表；之后报送的半年报 6-K 中期现金流量表；比率为自算（D），"
                           "阈值为本季本地研究设定。"))
        return chart

    next_ex += [threshold_line(entry) for entry in watch]

    # ── section four: the long routine series ───────────────────────────────
    years = ann["years"]
    fcf = [o - c for o, c in zip(ann["operating_cash_flow"],
                                 ann["capital_expenditures"])]
    intensity = [round(c / r * 100.0, 2)
                 for c, r in zip(ann["capital_expenditures"], ann["revenue"])]
    da_share = [round(d / r * 100.0, 2)
                for d, r in zip(ann["depreciation_and_amortization"], ann["revenue"])]
    flat = max(intensity) - min(intensity) < 5.0
    da = ann["depreciation_and_amortization"]
    da_steady = max(da) / min(da) < 1.2
    growth = ann["revenue"][-1] / ann["revenue"][0] - 1
    growth_words = f"涨了{'近' if growth < round(growth) else ''}{cn_count(round(growth))}倍"
    count = cn_count(len(years))

    restated_quarter = next(q for q, lines in census["lines_moved"].items() if "revenue" in lines)
    earlier = [q for q in census["quarters"] if q != restated_quarter]
    earlier_moves = [abs(pair[1] / pair[0] - 1) * 100
                     for q in earlier for pair in census["lines_moved"][q].values()]
    earlier_amounts = [abs(pair[1] - pair[0])
                       for q in earlier for pair in census["lines_moved"][q].values()]
    delta = restate["delta"]
    scope_from, scope_to = census["scope"]
    scope_quarters = periods.index(scope_to) - periods.index(scope_from) + 1
    only_revenue = [q for q, lines in census["lines_moved"].items() if "revenue" in lines] == [restated_quarter]
    amount_order = abs(delta["operating_profit"]) >= 10 * max(earlier_amounts)

    routine = structure + [
        {
            "ref": "EX_CAPEX",
            "kind": "grouped_bars",
            "title": (f"经营现金流、资本开支与自由现金流：{years[0]}–{years[-1]} 资本强度在 "
                      f"{min(intensity):.1f}%–{max(intensity):.1f}% 之间"),
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
                f"{count}年的资本强度是 " + "、".join(f"{v:.1f}%" for v in intensity) + " —— "
                + (("<b>大体持平，最近一年还略微上行。</b>" if intensity[-1] > intensity[-2]
                    else "<b>大体持平。</b>") if flat else "")
                + (f"之后的{spaced_before(half_words(halves['periods'][-1]))}降到 {hy_ratio[-1]:.1f}%，"
                   "见 Exhibit {EX_INTENSITY}。" if halves else "")
                + f"自由现金流 = 经营现金流 − 资本开支，{count}年逐年成立。"),
            "src_extra": ("Form 424B4 现金流量表摘要；资本强度与自由现金流为自算（D），"
                          "两个输入取自同一份文件的同一组期间列。"),
        },
        {
            "ref": "EX_DA",
            "kind": "bar_line_dual",
            "title": (f"折旧摊销{'几乎没动，' if da_steady else ''}占收入却从 {da_share[0]:.1f}% "
                      f"{'掉到' if da_share[-1] < da_share[0] else '升到'} {da_share[-1]:.1f}%"),
            "xlabels": list(years),
            "bar": {"name": "折旧与摊销（₩万亿）", "color": "BLUE",
                    "values": tn(da),
                    "yfmt": "f0"},
            "line": {"name": "占收入比例（右轴）", "color": "RED",
                     "values": da_share, "yfmt": "pct0"},
            "fmt": "f1", "label_fmt": "f1",
            "ylab": "₩万亿", "ylab2": "占收入 %",
            "note": (
                f"{count}年里折旧摊销的绝对额"
                + ("几乎是一条直线" if da_steady else "")
                + "（" + " → ".join(f"₩{v / 1000:.1f}T" for v in da) + "），"
                f"而收入{growth_words}，所以它占收入的比例"
                f"{'掉到' if da_share[-1] < da_share[0] else '变为'}"
                f"{cn_fraction(da_share[-1] / da_share[0])}。"
                "<b>本轮利润率扩张里有一部分来自这个分母效应，而不是单位成本下降</b> —— "
                "折旧基数没变，被暴涨的收入摊薄了。"
                "反过来也成立：收入回落时这条线会机械性抬升。"),
            "src_extra": "Form 424B4 的调整后 EBITDA 调节表；占比为自算（D）。",
        },
        {
            "ref": "EX_RESTATE",
            "kind": "grouped_bars",
            "title": (f"{len(census['quarters'])} 个季度事后被改过，只有 {cn_quarter(restated_quarter)}"
                      "动到了收入：营业利润与净利润各下调 "
                      f"₩{abs(delta['operating_profit']):.0f}bn，收入下调 ₩{abs(delta['revenue']):.0f}bn"),
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
                ("<b>它不是窗口里唯一一次重述，但它是唯一一次动到收入的。</b>" if only_revenue else "")
                + f"{scope_from}–{scope_to} 的 {scope_quarters} 季里有 {len(census['quarters'])} "
                "个季度的数字在「当期发布」与「一年后的对照列」之间不一致："
                + "、".join(census["quarters"]) + "。"
                f"前{cn_count(len(earlier))}次只动营业利润和净利润，幅度在 "
                f"{min(earlier_moves):.1f}%–{max(earlier_moves):.1f}% 之间，收入一动没动；"
                "这一次三条线全动"
                + ("，且金额大一个量级以上" if amount_order else "")
                + "。"
                "<b>而它们的出现方式完全一样</b>：下一季发布的「上季」列每一次都"
                "原样重复首报数，改动只出现在大约四个季度之后的「去年同期」列 —— "
                "也就是外部审计走完之后。每期发布自己的免责声明写着"
                "「在外部审计人会计检查完成之前编制」，而没有任何一期用过"
                "「重述」「更正」「重分类」这些词。"
                "公司在 2023 年 1 月发布的 2022 年第四季，与一年后 2023 年第四季发布中"
                "作为对照列印出来的同一个季度，不是同一组数。"
                + (f"营业利润与净利润的下调完全相等（各 ₩{abs(delta['operating_profit']):.0f}bn），"
                   if delta["operating_profit"] == delta["net_income"] else "")
                + f"收入只下调 ₩{abs(delta['revenue']):.0f}bn —— "
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

    # The company's one forward-looking number, settled in words: what last
    # quarter's call guided for this quarter's bit shipments, against how this
    # quarter's filing worded the outcome. Printed only while the phrase series
    # reaches this quarter; the mismatch sentence only while the words disagree.
    guided = story.get("shipment_guidance_for_quarter")
    guidance_words = ""
    if guided and phrases_reach_quarter:
        def overlaps(a: str, b: str) -> bool:
            return vocabulary[a]["low"] <= vocabulary[b]["high"] and vocabulary[a]["high"] >= vocabulary[b]["low"]

        def band_text(phrase: str) -> str:
            return f"{vocabulary[phrase]['low']:g}–{vocabulary[phrase]['high']:g}%"

        filed_bits = {"dram": dram_bit["phrases"][-1], "nand": nand_bit["phrases"][-1]}
        off = [leg for leg in ("dram", "nand") if not overlaps(guided[leg], filed_bits[leg])]
        guidance_words = (
            f"上季电话会给本季的出货指引是 DRAM “{guided['dram']}”、NAND “{guided['nand']}”"
            + ("，本季电话会说两条都兑现了" if story.get("shipment_delivered_per_call") else "")
            + (("；而同季报送的半年报把"
                + "、".join(f" {leg.upper()} 出货记为 “{filed_bits[leg]}”（本页读成 {band_text(filed_bits[leg])}），"
                            f"与指引的 {band_text(guided[leg])} 不重叠" for leg in off)
                + " —— 同一个量，公司两份文件用了互不重叠的词")
               if off else "，半年报的用词与之一致")
            + "。")
    word_charts = n_s - word_charts_from
    settled_description = (
        (("先结算上季本地分析留下的两样东西："
          + "，".join(part for part in (
              f"{len(closure['items'])} 条待验证问题闭环了几条" if closure else "",
              f"{len(prior_kpi['entries'])} 条量化阈值能结算几条、守住没有" if prior_kpi else "") if part)
          + "。" + prior_all_open + "然后是公司自己的前瞻披露 —— ") if closure or prior_kpi else "")
        + "SK hynix 不发布任何财务指引，营收、利润率、每股收益都没有区间，季度和年度都没有；"
        "它唯一的前瞻数字是电话会上下一季出货量的英文用词。"
        + guidance_words
        + f"量价的实际变化也只以用词发布，所以本节最后{cn_count(word_charts)}张图结算的是这些用词本身："
        "它们留下多少不确定，以及为什么出货指引全部兑现、收入仍然可以对不上。")

    prior_rows = []
    for entry in (prior_kpi or {}).get("entries", []):
        done = next((e for e in settled_prior if e["id"] == entry["id"]), None)
        if done is None:
            gone = next(e for e in open_prior if e["id"] == entry["id"])
            prior_rows.append([entry["short"], entry["threshold_text"], "—", f"{gone['status']}：{gone['why']}"])
            continue
        gap = headroom(done["direction"], done["threshold"], done["actual"])
        reading = unit_text(done["unit"], done["actual"])
        if done["id"] == "dram_asp":
            reading = (f"“{dram_asp['phrases'][-1]}”，读成 "
                       f"{vocabulary[dram_asp['phrases'][-1]]['low']:g}–{vocabulary[dram_asp['phrases'][-1]]['high']:g}%，"
                       f"中点 {reading}")
        prior_rows.append([entry["short"], entry["threshold_text"], reading,
                           f"{'守住' if gap >= 0 else '击穿'}（余量 {gap:+.1f}%）"])

    first_table = exhibits[-1]["n"] + 1
    audited_quarter = staging["quarterly_audited_krw_bn"]
    identity_holds = (
        all(g - s - r == o for g, s, r, o in zip(ann["gross_profit"], ann["sga"], ann["rnd"],
                                                  ann["operating_profit"]))
        and all(g - s - r == o for g, s, r, o in zip(audited_quarter["gross_profit"], audited_quarter["sga"],
                                                      audited_quarter["rnd"], audited_quarter["operating_profit"])))
    tables = [
        {
            "n": first_table,
            "title": f"近{cn_count(8)}季合并损益（公司披露值，₩十亿）",
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
            "title": f"{cn_count(len(kq))}季量价用词与本页读成的区间（公司只发布左边那一列）",
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
            "headers": ["项目"] + list(years),
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
    ]
    if prior_rows:
        tables.append({
            "n": first_table + len(tables),
            "title": f"上季 {len(prior_rows)} 条阈值的原文与本季结算",
            "headers": ["指标", "上季阈值（本地分析稿第 8 节原文）", "本季读数", "结算"],
            "rows": prior_rows,
        })
    measured = {e["id"]: e for e in watch}
    gone = {e["id"]: e for e in unmeasured}

    def current_text(entry: dict) -> str:
        text = unit_text(entry["unit"], entry["current"])
        if entry["id"] == "dram_asp":
            return f"“{dram_asp['phrases'][-1]}” 的中点 {text}"
        if entry["id"] == "capex_ratio":
            return f"{text}（{latest_half[0]}）"
        return text

    next_rows = []
    for entry in thresholds["entries"]:
        if entry["id"] in measured:
            done = measured[entry["id"]]
            next_rows.append([entry["metric"], entry["threshold_text"], entry["action"], current_text(done),
                              f"{headroom(done['direction'], done['threshold'], done['current']):+.1f}%"])
        else:
            left = gone[entry["id"]]
            next_rows.append([entry["metric"], entry["threshold_text"], entry["action"], "—",
                              f"{left['status']}：{left['why']}"])
    tables += [
        {"n": first_table + len(tables),
         "title": "下季阈值：本季本地分析稿第 8 节原文与当前值",
         "headers": ["指标", "阈值原文", "触发动作", "当前值", "余量 D / 为什么画不了"],
         "rows": next_rows},
        ai_capex_cycle_table(first_table + len(tables) + 1),
    ]

    record = bool(story.get("record_margin_claimed")) and opm[-1] == max(opm)
    comp_top = sorted(components, key=lambda c: -c["value"])[:2] if components else []
    headline = (
        f"营收 ₩{revenue[-1] / 1000:.1f}T、同比 {pct_change(revenue[-1], revenue[-5]):+.0f}%，"
        f"营业利润率 {opm[-1]:.1f}%{' 为历史最高' if record else ''}，"
        f"环比增速从 {qoq_prev:.1f}% {step_words} {qoq_now:.1f}%；"
        + (f"DRAM 售价环比从 “{dram_asp['phrases'][-2]}” {move_word(dram_asp)}到 “{dram_asp['phrases'][-1]}”；"
           if phrases_reach_quarter else "")
        + (f"净利率 {netm[-1]:.0f}% 高过 100%，因为税前比营业利润多出 "
           f"₩{nonop[-1] / 1000:.1f}T 的营业外收益"
           + ("——季度发布只印到净利润为止，之后的半年报才拆开："
              + "、".join(f"₩{c['value'] / 1000:.1f}T 是{c['line']}" for c in comp_top)
              if release_silent and comp_top else
              "，而公司的季度发布只印到净利润为止、对这笔钱没有任何拆分" if release_silent else "")
           + "；" if below is not None and over_hundred else "")
        + "全公司唯一的前瞻披露是下一季的出货量，而且它和售价一样，是用英文形容词发布的。"
    )

    articles = [
        '<article><span>披露</span><b>营收报到百万韩元，两个驱动变量只给形容词</b>'
        f'<p>{cn_count(len(kq))}个季度的出货量与售价环比，全部是 “Mid-60% Increase”、“Flat”、'
        '“Over 70% Increase” 这样的用词，出自 Nasdaq 上市的注册声明书和之后报送的半年报。'
        f'{len(widths)} 次读数平均留下 {mean_width:.1f} 个百分点的不确定，'
        f'{one_sided} 次根本没有上界。</p></article>',
    ]
    if price_moves:
        articles.append(
            '<article><span>后果</span><b>指引全兑现，收入仍可能不及预期</b>'
            '<p>公司指引的是出货量'
            + ('，而出货量的中值多数季度在正负十个点以内' if quiet_volume else '')
            + f'；售价一季能走{asp_words}，且从不指引。被指引的变量不是决定收入的变量。</p></article>')
    if below is not None and over_hundred:
        articles.append(
            '<article><span>本季</span>'
            f'<b>净利率 {netm[-1]:.0f}% 不是经营突破</b>'
            f'<p>税前比营业利润多 ₩{nonop[-1] / 1000:.1f}T，'
            f'占税前 {nonop_share:.0f}%。'
            + (f'季度业绩发布只印到净利润为止，税前那一行印在{spaced_after(story["pretax_printed_in"])}里；'
               if release_silent and story.get("pretax_printed_in") else '')
            + ('之后的半年报把它拆开：' + '、'.join(f'₩{c["value"] / 1000:.1f}T 是{c["line"]}' for c in comp_top)
               + '，没有说来自哪一笔投资。' if comp_top else '构成则任何文件都没有。')
            + '</p></article>')
    if halves:
        to_year = hy_ratio[-1] / fy_ratio[-1]
        articles.append(
            '<article><span>资本</span>'
            f'<b>资本强度{"约减半" if 0.4 <= to_year <= 0.6 else "降到全年的 " + format(to_year * 100, ".0f") + "%"}：'
            f'{half_words(halves["periods"][-1])} {hy_ratio[-1]:.1f}%</b>'
            f'<p>{fy_labels[-1]} 全年是 {fy_ratio[-1]:.1f}%，同口径的{spaced_before(half_words(halves["periods"][0]))}是 '
            f'{hy_ratio[0]:.1f}%。主要是分母：收入涨得比资本开支快得多，收入回落时这个比率会机械性回升。</p></article>')

    audit_words = {"provisional": "暂定数，外部审计未完成", "reviewed": "中期报表已经外部审阅（未审计）",
                   "audited": "已审计"}[latest["audit_status"]]
    rounding_from, rounding_to = (periods.index(q) for q in ROUNDING_EXAMPLE)
    restate_moves = f"{min(earlier_moves):.1f}%–{max(earlier_moves):.1f}%"
    semi_source = next((item for item in staging["sources"] if "半年报 6-K" in item["label"]), None)
    data_through = after["filed"] if after else latest["release_date"]
    prior_overview = next((ex["n"] for ex in settled_ex
                           if ex["kind"] == "diverging_bars" and ex["title"].startswith("上季")), None)
    next_overview = next((ex["n"] for ex in next_block
                          if ex["kind"] == "diverging_bars" and ex["title"].startswith("下季")), None)
    lta = story.get("lta")
    return {
        "schema_version": "quarterly-dashboard/skhynix-v1",
        "page": {"slug": "skhynix", "language": "zh-CN"},
        "company": {
            "ticker": "SKHY",
            "name": "SK hynix",
            "group": "semiconductor_ai",
            "accounting_standard": "K-IFRS",
        },
        "latest": latest,
        "tracker": "Watchlist Quarterly Tracker · SK hynix",
        "title": f"SK hynix Inc. (000660.KS / SKHY)：{period} 季报仪表盘",
        "subtitle": (f"截至 {latest['period_end']} · 发布 {latest['release_date']} · K-IFRS · {audit_words} · "
                     "自然年财年，季度标注与财年一致 · 韩元列报"),
        "headline": headline,
        "brief": (
            f'<h4>这一页要说的{cn_count(len(articles))}件事</h4><div class="takeaway-grid">'
            + "".join(articles)
            + '</div>'),
        "source": (f'Source: <a href="{filing["url"]}" rel="noopener">'
                   f'SK hynix {year} 年第{cn_ordinal(quarter)}季度业绩（Form 6-K，{latest["release_date"]}）</a>'
                   f'、<a href="{prospectus["url"]}" rel="noopener">'
                   f'Form 424B4 招股说明书（{prospectus_date}）</a>'
                   + (f'与 <a href="{semi_source["url"]}" rel="noopener">半年报（Form 6-K，'
                      + re.search(r"（(\d{4}-\d{2}-\d{2})", semi_source["label"]).group(1) + '）</a>'
                      if semi_source else '')
                   + '。SK hynix 为外国私人发行人，年报为 20-F，季度以 6-K 报送。'),
        "source_url": ir_page["url"],
        "source_links": staging["sources"],
        "summary": {"blocks": []},
        "guidance": None,
        "sections": [
            {"id": "settled", "title": "一、上季跟踪指标兑现了吗",
             "description": settled_description,
             "exhibits": settled_ex},
            {"id": "quarter_highlights", "title": "二、本季重点",
             "description": (
                 f"{len(periods)} 季的营收与利润率"
                 + ("、本季的量价用词" if phrases_reach_quarter else "")
                 + ("、本季的分产品收入" if has_split else "")
                 + ("、净利率越过 100% 的来源与构成" if below is not None and over_hundred else "")
                 + ("，以及上半年的资本强度" if halves else "")
                 + "。本季本地分析稿里另外两条结论本页画不了：营收与营业利润低于市场预期 —— "
                 "那要用第三方的预期数据，本页按注释里的规矩不发布"
                 + (f"；约 10 家客户的长期协议（LTA）—— {lta['printed_in']}只印了 “{lta['customers_printed']}”，"
                    f"{lta['terms_spoken']}这两点只在电话会上说过，同期报送的半年报则写着 “{lta['filing_line']}”，"
                    "没有可画的序列" if lta else "")
                 + "。"),
             "exhibits": highlight_ex},
            {"id": "next_quarter", "title": "三、下季要跟踪什么",
             "description": (
                 f"本季本地分析稿第 8 节的阈值：{cn_count(len(watch))}个能用申报序列量，画在下面，"
                 "统一用「距阈值余量」口径"
                 + (f"；{cn_count(len(unmeasured))}个画不了（{'、'.join(e['short'] for e in unmeasured)}），"
                    "原文与原因在核对抽屉里" if unmeasured else "")
                 + "。阈值来自本地分析，不是公司指引 —— SK hynix 不发财务指引"
                 + (f"，它对下一季给的只有出货用词：DRAM “{guide_next['dram']}”、NAND “{guide_next['nand']}”。"
                    if guide_next else "。")),
             "exhibits": next_block},
            {"id": "routine", "title": "四、长期常规跟踪",
             "description": ("年度的分产品收入、年度与中期的单一客户集中度、资本强度与折旧的分母效应，"
                             f"以及 {len(census['quarters'])} 次事后改动里唯一动到收入的那一次"
                             "和本页序列选用的版本。"),
             "exhibits": routine_ex},
        ],
        "tables": tables,
        "notes": [
            "本页按「上季兑现 → 本季重点 → 下季跟踪 → 长期常规」四段排列，以图为主，每张图下一到两句解释；支撑表格收在核对抽屉里。",
            "SK hynix 财年即自然年，本页季度标注与公司自己的口径一致，无需换算。",
            "本页以韩元列报，与本站其他以美元列报的页面不可直接相加。金额除特别标注外单位为万亿韩元（₩T）或十亿韩元。公司自己在业绩发布中以万亿韩元为主要单位。",
            "SK hynix 是 SEC 注册人：CIK 2120882，文件编号 001-43391，2026-07-10 起在纳斯达克以 SKHY 交易 ADR，年报为 20-F、季度以 6-K 报送。本页的一手来源因此同时包含公司自己的业绩发布与 SEC 托管的申报文件。",
            "第一节先结算上季本地分析留下的待验证问题与量化阈值，再结算公司自己的前瞻披露。SK hynix 不发布营收、利润、利润率或每股收益的指引，无论季度还是年度；它唯一的前瞻数字是下一季的出货量，而出货量与售价一样以英文用词发布。所以第一节后半段结算的是用词本身而不是数值区间，差别源于公司披露口径而非编辑选择。",
            "用词到区间的映射由本页一次性设定，对四条序列一视同仁，完整对照见核对抽屉里的用词表。其中 "
            + "、".join(phrase.replace(" Increase", "") for phrase, entry in vocabulary.items() if entry["one_sided"])
            + f" {cn_count(len([1 for entry in vocabulary.values() if entry['one_sided']]))}种说法在申报文件里没有上界，本页统一取「下限加十个百分点」以便作图，该上界是作图约定而非披露。",
            "平均售价的用词以美元计，而收入以韩元报告，两者之间存在申报文件未披露的汇率项。因此把出货量与售价相乘去对韩元收入，必然留下一个汇率造成的残差；本页把这个残差画出来而不是把它并入产品组合，见第一节最后一张图。",
            "营业利润率与净利率均为本页按两个韩元金额自算。公司在业绩发布中披露的是四舍五入到整数的百分比，两者并列在近八季核对表里。用整数做环比差最多可能偏约一个百分点，例如"
            f" {cn_quarter(ROUNDING_EXAMPLE[0])}到第{cn_ordinal(int(ROUNDING_EXAMPLE[1][-1]))}季按整数读是 "
            f"{fin['operating_margin_pct_disclosed'][rounding_to] - fin['operating_margin_pct_disclosed'][rounding_from]:+d}pp、"
            f"按金额算是 {opm[rounding_to] - opm[rounding_from]:+.1f}pp。",
            ("营业利润在 K-IFRS 的这套列报里不是一个报表行，而是毛利减销售及管理费用减研发费用。"
             f"该恒等式在 {years[0]} 至 {years[-1]} {count}个年度以及 {cn_quarter(audited_quarter['periods'][-1])}逐期成立，"
             "且结果与公司在业绩发布中报告的营业利润完全一致，核对见年度审计数表。"
             if identity_holds else
             "营业利润在 K-IFRS 的这套列报里不是一个报表行，而是毛利减销售及管理费用减研发费用；"
             "该恒等式本期没有逐期成立，核对见年度审计数表。"),
            *([f"本季税前利润、所得税与营业外净收益：税前利润先印在 {latest['release_date']} 报送的 6-K 上，所得税为税前减净利、营业外净额为税前减营业利润，两者都是两条已印出的行相减。公司自己的季度业绩发布只印到净利润为止；"
               + (f"营业外的构成要到之后{spaced_before(below['components_printed_in'])}才出现，本页按那几行发布，不替它补上是哪一笔投资。" if components else "本页读过的文件都没有给出营业外的构成。")
               + "本页不发布任何「剔除一次性后的净利润」——那需要假设这笔收益按平均税率纳税，而申报没有单独给出它的税负。"]
              if below is not None and release_silent else []),
            *([f"{period} 的季度数字先由 {latest['release_date']} 的业绩发布与 6-K 初步公布；之后报送的半年报 6-K 附带经外部审阅、未经审计的合并中期报表，本季营收、营业利润、税前利润与净利润两份文件逐位相同，页头因此写「中期报表已经外部审阅」。"]
              if latest["audit_status"] == "reviewed" else []),
            "分产品收入与单一客户集中度来自审计与审阅报表的附注：年度取自 Form 424B4，季度与半年取自中期报表附注（Form 424B4 的第一季、之后报送的半年报）。"
            f"本页读到的季度分产品收入一共{cn_count(len(quarter_labels))}个季度（{'、'.join(quarter_labels)}），每一季都只有收入、没有利润。"
            "公司在同一份文件中说明其决策层不接收任何组成部分的分部财务信息，因此财务报表不含分部信息，只有单一报告分部。",
            "按地区的收入披露以「销售主体所在地」为口径，指的是 SK hynix 在哪里入账，不是需求在哪里，因此本页不据此画终端需求图。",
            f"{scope_from}–{scope_to} 里有{cn_count(len(census['quarters']))}个季度（{'、'.join(census['quarters'])}）的数字在当期发布与一年后的对照列之间不一致，"
            f"其中只有 {cn_quarter(restated_quarter)}动到了收入：营业利润与净利润各下调 {abs(delta['operating_profit']):.0f}、收入下调 {abs(delta['revenue']):.0f}（₩十亿）；"
            f"另外{cn_count(len(earlier))}次只动利润两行，幅度 {restate_moves}。"
            f"{cn_count(len(census['quarters']))}次都不带「重述」字样，都只出现在四个季度后的「去年同期」列上，而每期发布都声明自己在外部审计完成之前编制。"
            f"本页 {len(periods)} 季序列采用「当期首次发布」那一版，因为只有它能让 2022 年四季加总回到公司当时印出的全年数。2022 年前三季此前按英文发布正文的精度记（Q1、Q2 只到百亿），而 Q3 的营业利润与净利润记的是 2023 年第三季对照列里那一版、不是它自己那期印的 —— 2026-08-31 全部改回当期首次发布，并改用韩文发布表的 억원 精度。该年四季加总与全年数的残差因此从约十亿降到 ±0.6，本页对 2022 年的求和容差也从 15 收到 1。",
            f"2021 年第四季的当季净利润（{net[fy_q4]:,.0f}）与当季营业利润率（{fin['operating_margin_pct_disclosed'][fy_q4]}%）在公司那期发布里一直是披露的，印在随文那张业绩表上，只是没有出现在正文里。本页此前把这两格记成 null 并写明「公司没印」，那是读正文没读表的结果，2026-08-31 更正。四季相加等于同篇印出的全年 {fy2021:,.0f}。",
            "本页不发布市场一致预期、评级、目标价与估值。这一条对本页尤其要紧：SK hynix 不发布任何财务指引，所以任何看起来像「预期对实际」的对照都只能来自站外，而没有可核对的、带日期的公开来源时，宁可不发。",
            "本页只发布公司披露值、可复算的简单派生值；D 标记代表 Derived / 自算。",
            "核对抽屉最后那张「AI capex 循环」是全站共用的跨页对照块，在每一页都逐字节相同，不是对 SK hynix 的判断。它追的是四家云厂现金资本开支 → NVDA 数据中心 → TSM 晶圆这条链。SK hynix 是这条链上的供给方而不是其中任何一环的支出方，本页带着这张表是为了让读者在任意一页都能查到同一份上下游对照，它在折叠的抽屉里，不参与本页的论证。",
            *([f"Exhibit {prior_overview} 与 Exhibit {next_overview} 的阈值来自本地分析稿，不是公司指引：前者是上季那份的第 8 节，后者是本季这份的。"]
              if prior_overview and next_overview else []),
            "本页已知未接入：分产品的利润、HBM 的收入与占比、按客户或终端市场的收入拆分、"
            "其余各季的分产品收入与资本开支（本页读过的 SEC 申报只印了上面几个期间）、"
            + ("营业外收益来自哪一笔投资，" if components else
               f"{cn_quarter(periods[-1])}营业外收益的构成，" if below is not None else "")
            + f"以及 {cn_quarter(shift_quarter(periods[-1], 1))}度之后的任何数据（本页数据截至 {data_through} 的申报）。其中 HBM 相关口径公司从未在任何申报文件中量化。",
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
