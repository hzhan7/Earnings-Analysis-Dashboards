"""The owner's 2026-09-24 ruling on sell-side consensus, held on every page.

Consensus may be published, but only as README's content boundary puts it: labelled
「市场预期」, dated, and with no broker or vendor named. Before the ruling the site said
three different things -- the home page «不放卖方共识», README «may be published», and
four different page-level wordings -- so eight pages printed consensus figures while
three pages told the reader the site forbids it.

What this file checks, on every published company page:

1. Every consensus figure carries its as-of date. For a chart, the date must be in its
   note or source line; for a page note, in the same note. A figure without a date is
   the case README rules out, and the one that slipped through on five pages.
2. No broker or data vendor is named in a sentence about consensus. NVDA named
   «LSEG» (via a CNBC report) for one quarter.
3. No page claims a site-level prohibition. A page may choose not to carry consensus;
   it may not tell the reader the site forbids it, because the site no longer does.

Sentences that say what a page does *not* carry («本页不发布」「不接入」「没画」) are
not figures, so they are skipped by (1) and (2) -- but not by (3).
"""
import json
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.all import ENTRIES  # noqa: E402

LABEL = re.compile(r"市场预期|一致预期")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
FIGURE = re.compile(r"(US\$|NT\$|\$|€|₩)\s?\d|\d(\.\d+)?\s?%")
NEGATED = re.compile(r"不发布|不接入|不画|没画|画不了|画不出来|不上页|本页不|本站不|不放")
VENDORS = ("LSEG", "Refinitiv", "FactSet", "Bloomberg", "Visible Alpha", "Capital IQ", "Zacks",
           "Seeking Alpha", "MarketScreener", "Yahoo", "CNBC", "Reuters", "Morgan Stanley",
           "Goldman", "J.P. Morgan", "JPMorgan", "Bernstein", "Barclays", "UBS", "Jefferies",
           "Evercore", "Citi", "BofA", "Wells Fargo", "Baird", "Cowen", "Melius", "Cantor")
SITE_PROHIBITION = re.compile(r"(站点|本站|全站)[^。；]{0,15}不(放|发布)[^。；]{0,15}(共识|一致预期|市场预期)"
                              r"|(共识|一致预期|市场预期)[^。；]{0,15}(站点|本站|全站)[^。；]{0,6}不(放|发布)")


def payload(slug: str) -> dict:
    text = (ROOT / f"data/{slug}.js").read_text(encoding="utf-8")
    return json.loads(re.search(r"=\s*(\{.*\})\s*;?\s*$", text, re.S).group(1))


def sentences(text: str) -> list:
    return [s for s in re.split(r"(?<=[。；])", re.sub(r"<[^>]+>", "", text or "")) if s.strip()]


def strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, list):
        for item in obj:
            yield from strings(item)
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from strings(value)


def consensus_sentences(text: str) -> list:
    return [s for s in sentences(text) if LABEL.search(s) and not NEGATED.search(s)]


class MarketExpectationTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.pages = {e["slug"]: payload(e["slug"]) for e in ENTRIES}

    def test_the_census_sees_every_page_that_prints_consensus(self) -> None:
        # The eight pages that carried consensus figures on 2026-09-24. If this
        # set shrinks to nothing, the checks below pass by having nothing to look at.
        carrying = set()
        for slug, page in self.pages.items():
            for section in page["sections"]:
                for exhibit in section["exhibits"]:
                    text = " ".join(strings([exhibit.get("title"), exhibit.get("note"),
                                             exhibit.get("xlabels"), exhibit.get("legend")]))
                    if consensus_sentences(text):
                        carrying.add(slug)
            if any(FIGURE.search(s) for note in page.get("notes") or [] for s in consensus_sentences(note)):
                carrying.add(slug)
        self.assertGreaterEqual(len(carrying), 6, sorted(carrying))

    def test_every_consensus_chart_is_dated(self) -> None:
        for slug, page in self.pages.items():
            for section in page["sections"]:
                for exhibit in section["exhibits"]:
                    text = " ".join(strings([exhibit.get("title"), exhibit.get("note"),
                                             exhibit.get("xlabels"), exhibit.get("legend")]))
                    if not consensus_sentences(text):
                        continue
                    with self.subTest(page=slug, chart=exhibit.get("title", "")[:40]):
                        self.assertRegex((exhibit.get("note") or "") + (exhibit.get("src_extra") or ""), DATE,
                                         "a consensus figure on a chart carries no as-of date")

    def test_every_consensus_figure_in_the_notes_is_dated(self) -> None:
        for slug, page in self.pages.items():
            for note in page.get("notes") or []:
                figures = [s for s in consensus_sentences(note) if FIGURE.search(s)]
                figures += [s for s in sentences(note) if re.search(r"收入预期|EPS 预期", s) and FIGURE.search(s)]
                if figures:
                    with self.subTest(page=slug, note=note[:40]):
                        self.assertRegex(note, DATE, "a consensus figure in the notes carries no as-of date")

    def test_no_broker_or_vendor_is_named_beside_consensus(self) -> None:
        for slug, page in self.pages.items():
            for text in strings(page):
                for sentence in sentences(text):
                    if not re.search(r"预期|共识|consensus", sentence, re.I):
                        continue
                    for vendor in VENDORS:
                        with self.subTest(page=slug, vendor=vendor):
                            self.assertNotIn(vendor, sentence, sentence[:80])

    def test_no_page_claims_the_site_forbids_consensus(self) -> None:
        for slug, page in self.pages.items():
            for text in strings(page):
                with self.subTest(page=slug):
                    self.assertIsNone(SITE_PROHIBITION.search(text), text[:120])

    def test_the_home_page_and_readme_state_the_ruling(self) -> None:
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIsNone(SITE_PROHIBITION.search(home))
        self.assertNotIn("外部共识", home)
        self.assertIn("市场预期可以作为对照点发布", home)
        self.assertIn("labelled, dated comparison point", readme)


if __name__ == "__main__":
    unittest.main()
