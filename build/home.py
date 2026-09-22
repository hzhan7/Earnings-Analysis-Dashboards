"""Write the generated regions of the home page, `index.html`.

The home page used to be typed by hand: one card per company carrying its period
label, release date and three headline figures, plus a masthead that counts the
companies and the charts that already reach 2016. Every quarter roll had to
retype a card, and the tests could only check that the retyped text agreed with
the payload somewhere on the page -- the NVIDIA card sat a whole quarter behind
its own page (Q1 2026 figures under a Q2 2026 payload) while every one of them
stayed green, because another card happened to carry the same date string.

So those regions are now written here, from the roster and the payloads, between
marker comments. Everything outside the markers is still hand-written prose.
`build/all.py` calls `write_home()` after the roster; `build/all.py && git
status` is the drift check for these regions the same way it is for the
payloads.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / "index.html"

STATUS_LABEL = {"history_ready": "历史趋势已接入"}
PENDING_LABEL = "最新季已接入 · 历史待补"


# ── the year parser behind the masthead counts ──────────────────────────────
# A deliberate copy of `label_year` / `first_year` in tests/test_chart_window.py
# rather than an import of it: `test_the_home_page_counts_the_companies_it_lists`
# recounts the masthead with the test's own parser, and a recount that imported
# the very function that wrote the number could not fail. If the two ever
# disagree about what a time axis is, that test turns red and both change
# together.
_PERIOD = [
    (re.compile(r"^Q([1-4])[ '](\d{4}|\d{2})\b"), 2),
    (re.compile(r"^([1-4])Q ?(\d{4}|\d{2})\b"), 2),
    (re.compile(r"^(\d{4}|\d{2})Q([1-4])$"), 1),
    (re.compile(r"^FY ?(\d{4}|\d{2})\b"), 1),
    (re.compile(r"^(?:1H|2H|H1|H2) ?(\d{4}|\d{2})$"), 1),
    (re.compile(r"^(\d{4})H[12]$"), 1),
    (re.compile(r"^(\d{4})-\d{2}(-\d{2})?$"), 1),
    (re.compile(r"^[A-Z][a-z]{2}[- ](\d{4}|\d{2})$"), 1),
    (re.compile(r"^(?:19|20)\d{2}$"), 0),
]
_QUALIFIER = re.compile(r"^(?:[Qq][1-4]|初|initial|基数|本季|原披露|重述后|→\s*FY\s*\d{2,4})[*†]?$")


def _label_year(label: object) -> int | None:
    if not isinstance(label, str) or not label.strip():
        return None
    text = label.strip()
    for pattern, group in _PERIOD:
        match = pattern.match(text)
        if not match:
            continue
        rest = text[match.end():].strip()
        if rest and not _QUALIFIER.match(rest):
            return None
        year = int(match.group(0) if group == 0 else match.group(group))
        if year < 100:
            year += 2000 if year < 80 else 1900
        return year if 1990 <= year <= 2030 else None
    return None


def _first_year(exhibit: dict) -> int | None:
    labels = exhibit.get("xlabels") or []
    years = [_label_year(label) for label in labels]
    parsed = [year for year in years if year is not None]
    lettered = sum(1 for label in labels if isinstance(label, str) and label.strip())
    if len(parsed) < 2 or len(parsed) / max(1, lettered) < 0.6:
        return None
    return min(parsed)


def window_counts(payloads: dict) -> tuple[int, int, int]:
    """(pages with a 42-point chart, time-axis charts, those reaching 2016)."""
    pages_with_long = reached = total = 0
    for slug in sorted(payloads):
        longest = 0
        for section in payloads[slug]["sections"]:
            for exhibit in section["exhibits"]:
                year = _first_year(exhibit)
                if year is None:
                    continue
                total += 1
                reached += year <= 2016
                longest = max(longest, len(exhibit.get("xlabels") or []))
        pages_with_long += longest >= 42
    return pages_with_long, total, reached


# ── the regions ─────────────────────────────────────────────────────────────
def _markers(name: str) -> tuple[str, str]:
    return (f"<!-- generated:{name} · build/all.py 写入，勿手改 -->",
            f"<!-- /generated:{name} -->")


def replace_region(text: str, name: str, body: str) -> str:
    """Replace what sits between one pair of markers; exactly one pair must exist."""
    start, end = _markers(name)
    pattern = re.compile(re.escape(start) + r"(.*?)" + re.escape(end), re.S)
    found = pattern.findall(text)
    if len(found) != 1:
        raise ValueError(f"index.html: expected one generated:{name} region, found {len(found)}")
    return pattern.sub(lambda _: start + body + end, text, count=1)


def period_line(item: dict) -> str:
    """``Q2 2026 · 发布 2026-07-30``; ``Q2 2026 / H1 2026 · …`` for a two-clock page."""
    disclosed, full = item["latest_label"], item["latest_full_label"]
    label = disclosed if full.startswith(disclosed) else f"{disclosed} / {full}"
    return f"{label} · 发布 {item['release_date']}"


def card(item: dict) -> str:
    esc = lambda text: html.escape(text, quote=False)  # noqa: E731
    badge = STATUS_LABEL.get(item["status"], PENDING_LABEL)
    return (
        f'  <a class="hcard" href="{item["slug"]}/">\n'
        f'    <span class="ht">{esc(item["ticker"])}<span class="hn">{esc(item["name"])}</span></span>\n'
        f'    <span class="hm">{esc(period_line(item))}</span>\n'
        f'    <span class="hh">{esc(" · ".join(item["headline_metrics"]))}</span>\n'
        f'    <span class="hc"><span class="dot"></span>{badge}</span>\n'
        f'  </a>\n'
    )


def cross_cards(roster: dict) -> str:
    """The cross-company pages, as their own block below the company cards.

    Deliberately not `class="hcard"`: three home-page checks count that string
    to census the companies, and a group page counted as a company would make
    「N 家公司」 wrong in a way those very checks would then certify.
    """
    items = roster.get("cross") or []
    if not items:
        return "\n"
    esc = lambda text: html.escape(text, quote=False)  # noqa: E731
    return ('\n<h2 class="hubgrp">跨公司对照</h2>\n<div class="hub">\n' + "".join(
        f'  <a class="xcard" href="{item["slug"]}/">\n'
        f'    <span class="ht">{esc(item["name"])}</span>\n'
        f'    <span class="hm">{esc(item["blurb"])}</span>\n'
        f'    <span class="hc">{esc("、".join(item["members"]).upper())}</span>\n'
        f'  </a>\n'
        for item in items) + "</div>\n")


def cards(roster: dict) -> str:
    """Group headings in GROUPS order, cards in slug order inside each group."""
    blocks = []
    for group in roster["groups"]:
        members = sorted((item for item in roster["items"] if item["group"] == group["key"]),
                         key=lambda item: item["slug"])
        if not members:
            continue
        blocks.append(f'<h2 class="hubgrp">{html.escape(group["label"], quote=False)}</h2>\n'
                      '<div class="hub">\n' + "".join(card(item) for item in members) + "</div>\n")
    return "\n" + "\n".join(blocks)


def render_home(text: str, roster: dict, payloads: dict) -> str:
    pages_with_long, total, reached = window_counts(payloads)
    text = replace_region(
        text, "masthead",
        '\n<div class="masthead">\n'
        '  <span class="tracker">Watchlist Quarterly Tracker</span>\n'
        f'  <span class="meta">{len(roster["items"])} 家公司 · 窗口拉长中，'
        f'{pages_with_long} 家已有 42 季（2016 起）的图</span>\n'
        '</div>\n')
    text = replace_region(text, "window", f"{total} 张时间轴图里 {reached} 张已经到位")
    text = replace_region(text, "cards", cards(roster))
    text = replace_region(text, "cross", cross_cards(roster))
    return text


def write_home(roster: dict, payloads: dict) -> None:
    text = HOME.read_text(encoding="utf-8")
    HOME.write_text(render_home(text, roster, payloads), encoding="utf-8")
