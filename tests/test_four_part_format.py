"""Every company page is laid out in the owner's four parts, in order.

The owner fixed the format on 2026-09-23, with the TSM page as the reference:

    一、上季跟踪指标兑现了吗 → 二、本季重点 → 三、下季要跟踪什么 → 四、长期常规跟踪

A census that day found 11 of 39 company pages in this shape. Nine used their
own thematic sections (six, seven, five…), and most of the rest had the right
four slots under other titles. Nothing turned red: every per-company test pinned
its own section ids, so a page could only ever be checked against itself.

This file checks every company page against the same four (id, title) pairs.
Whether each section's *content* earns its title is pinned in the per-company
tests, against the Obsidian earnings note the section is built from.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.all import CROSS_ENTRIES, ENTRIES  # noqa: E402

FOUR_PARTS = [
    ("settled", "一、上季跟踪指标兑现了吗"),
    ("quarter_highlights", "二、本季重点"),
    ("next_quarter", "三、下季要跟踪什么"),
    ("routine", "四、长期常规跟踪"),
]

# The sentence a page uses to describe its own layout, wherever it has one.
# 「两」 is in the class on purpose: a mutation run with 「两段排列」 passed while the class
# listed only 一…十, so the check had never been able to see a two-part layout.
LAYOUT_SENTENCE = re.compile(r"本页按「([^」]*)」([一二两三四五六七八九十]+)段排列")
FOUR_PART_LAYOUT = ("上季兑现 → 本季重点 → 下季跟踪 → 长期常规", "四")


def payload(slug: str) -> dict:
    text = (ROOT / "data" / f"{slug}.js").read_text(encoding="utf-8")
    return json.loads(text.split(" = ", 1)[1].rstrip().rstrip(";\n"))


class FourPartFormatTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pages = {entry["slug"]: payload(entry["slug"]) for entry in ENTRIES}

    def test_the_census_reaches_every_company_page(self) -> None:
        # A loop over an empty or shrunken roster passes by construction.
        # Company pages are every data/*.js except the roster and cross-company pages.
        published = {p.stem for p in (ROOT / "data").glob("*.js")}
        cross = {entry["slug"] for entry in CROSS_ENTRIES}
        self.assertEqual(set(self.pages), published - {"roster"} - cross)
        self.assertGreaterEqual(len(self.pages), 39)

    def test_every_company_page_has_the_four_parts_in_order(self) -> None:
        for slug, page in self.pages.items():
            with self.subTest(slug=slug):
                self.assertEqual([(s["id"], s["title"]) for s in page["sections"]], FOUR_PARTS)

    def test_no_part_is_left_empty(self) -> None:
        for slug, page in self.pages.items():
            for section in page["sections"]:
                with self.subTest(slug=slug, section=section["id"]):
                    self.assertTrue(section["exhibits"])
                    self.assertTrue(section.get("description", "").strip())

    def test_a_page_that_describes_its_layout_describes_these_four_parts(self) -> None:
        # Eight pages said 「六段排列」「五段排列」 about themselves; a restructure
        # that left that sentence behind would publish a page contradicting itself.
        for slug, page in self.pages.items():
            text = json.dumps(page, ensure_ascii=False)
            for match in LAYOUT_SENTENCE.finditer(text):
                with self.subTest(slug=slug, sentence=match.group(0)):
                    self.assertEqual(match.groups(), FOUR_PART_LAYOUT)


if __name__ == "__main__":
    unittest.main()
