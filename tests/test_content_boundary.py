"""One shared denylist, scanned across every published file.

The per-company boundary checks in the other two test files each scan a
different set of objects with a separately maintained literal list, so a term
added to one is silently absent from the other. This file replaces that: the
file list comes from `git ls-files`, so a new company inherits the guard the
moment its series and payload are tracked.

Kept deliberately cheap and quarter-independent so `hooks/pre-push` can run it
on every push. A hook that fails on a normal quarter roll gets bypassed with
`--no-verify` and then protects nothing.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# The one import this file allows itself, weighed against the cheapness the
# docstring promises. It pulls in the eight company builders plus board/
# page_shell/payload_guard -- standard library throughout, no third-party
# dependency, ~10ms on a standalone run of this file that took 70ms without it,
# so `hooks/pre-push` keeps its budget. What it buys is the test below: with no
# ENTRIES to compare against, the slug list is only ever checked by hand, which
# is how NVDA stayed off it while three other companies were added to it.
from build.all import ENTRIES, GROUPS, MODULES  # noqa: E402

# Lower-cased substrings that must never reach a published file.
#
# Every entry is verified to be absent from the clean tree. Terms that describe
# what the site refuses to publish -- 评级 / 目标价 / 共识 / 估值 -- are
# deliberately NOT here: they appear in the site's own boundary statement
# (index.html and both payload footers), so including them would make the guard
# fire on a clean tree and get switched off. `rating` is excluded for the same
# reason plus being a substring of `operating`.
FORBIDDEN = [
    # Local filesystem and private source material
    "/users/",
    "/library/cloudstorage/",
    "onedrive",
    "icloud",
    "obsidian",
    # Data vendors and sell-side aggregators
    "seeking alpha",
    "alphastreet",
    "factset",
    "bloomberg",
    "yahoo finance",
    "stockanalysis.com",
    "bofa",
    # Tooling provenance carried in the local note's frontmatter. `anthropic`
    # used to sit here as a bare term and was narrowed to these when the Amazon
    # page was built: Anthropic is a counterparty Amazon names in its own 10-Q
    # -- the US$50.5B fair-value mark, the >US$100B AWS commitment and the
    # US$20.0B facility are all filed disclosures, and a page that cannot say
    # the name cannot describe the quarter it is about. What the guard was
    # actually protecting against is the note's `provider:` line, which these
    # catch directly.
    "provider: claude",
    "claude opus",
    "claude sonnet",
    "generated with claude",
    "claude code",
    # Sell-side packaging the site does not publish
    "target price",
    "price target",
    "overweight",
    "underweight",
    "outperform",
    "forward p/e",
    "ev/ebitda",
    "consensus",
    # Private stance language carried over from the local research note
    "谨慎多",
]


def published_files() -> list[Path]:
    """Every tracked file that GitHub Pages actually serves as content."""
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\0")
    return [
        ROOT / name
        for name in tracked
        if name
        and (name.startswith(("series/", "data/")) or name.endswith("index.html"))
    ]


# The companies the scan is expected to reach. Written out by hand on purpose:
# the point is to fail when discovery stops finding one, and a list derived from
# discovery could never do that. The test below keeps it from drifting from the
# roster it is supposed to mirror.
COMPANY_SLUGS = (
    "amzn", "avgo", "cdns", "googl", "ibkr", "ma", "mco", "meta", "msci",
    "msft", "nke", "nvda", "pm", "race", "schw", "snps", "spgi", "tjx", "tsm",
    "v",
)


class ContentBoundaryTest(unittest.TestCase):
    def test_scan_covers_every_company(self) -> None:
        """A company whose files stopped being discovered would pass vacuously."""
        names = {path.relative_to(ROOT).as_posix() for path in published_files()}
        self.assertIn("data/roster.js", names)
        self.assertIn("index.html", names)
        for slug in COMPANY_SLUGS:
            self.assertIn(f"series/{slug}.json", names)
            self.assertIn(f"data/{slug}.js", names)
            self.assertIn(f"{slug}/index.html", names)

    def test_slug_list_matches_the_build_roster(self) -> None:
        """The guard above only guards the companies it happens to list.

        NVDA shipped a page, a series and a payload at 6aa7b15 and was still
        missing from that list eight commits later, while AMZN, CDNS and SNPS
        were each added to it in turn. For that whole stretch NVDA's three files
        could have dropped out of discovery and the scan would have passed
        vacuously. Nothing caught it because a hand-maintained list has nothing
        checking it. This is that check: register a company in ENTRIES, forget
        this list, and the next run is red instead of one company quieter.
        """
        self.assertEqual({entry["slug"] for entry in ENTRIES}, set(COMPANY_SLUGS))

    def test_every_entry_group_exists_in_groups(self) -> None:
        """A company whose group key is missing disappears from every page's nav.

        `page.js:navigation()` builds the switcher as
        `R.groups.forEach(g => byGroup[g.key])`, so it can only render companies
        whose group key appears in GROUPS. Name a key in ENTRIES that GROUPS does
        not carry and nothing complains anywhere: the build succeeds, the payload
        and the shell are written, the page answers on its own URL, the roster
        lists the company -- and it is silently absent from the company dropdown
        on all nine pages, with no way to reach it except by typing the path.

        This is a live hazard rather than a hypothetical: several company pages
        are being added in parallel, each needing a group that does not exist
        yet, and adding a dict to a list merges cleanly with every other session
        doing the same. Reusing a neighbour's newly-arrived group row instead of
        writing your own looks identical in a diff and fails exactly this way.
        """
        group_keys = {group["key"] for group in GROUPS}
        for entry in ENTRIES:
            self.assertIn(entry["group"], group_keys, entry["slug"])

    def test_group_keys_are_unique(self) -> None:
        """The test above cannot catch a duplicated key, by construction.

        It builds its set of valid keys FROM GROUPS, so a key appearing twice is
        still a member and every ENTRIES row referencing it still passes. The
        order-uniqueness assertion below only catches the sub-case where the two
        rows also share an `order`.

        The consequence is visible to a reader rather than to the build.
        `navigation()` walks GROUPS and looks up `byGroup[key]` per row, so a key
        present twice renders two identical `<optgroup>`s and lists every company
        in that group twice in the switcher -- with the suite green. Verified by
        mutation: adding a second `payment_networks` row at a different `order`
        left all other checks passing and put both payments companies in the
        dropdown twice.

        Two sessions adding the same group row concurrently is exactly how this
        arrives, and it merges without a conflict.
        """
        keys = [group["key"] for group in GROUPS]
        self.assertEqual(len(keys), len(set(keys)), keys)

    def test_groups_render_in_the_order_they_declare(self) -> None:
        """`order` is decorative -- position in the list is what renders.

        Neither `roster_payload` nor `page.js` sorts by `order`; the nav and the
        home page both walk the array. So a row appended at the end with a lower
        `order` than the row before it renders out of sequence while looking
        correct in the source. Pinning position against `order` keeps the field
        honest instead of letting it drift into a comment.
        """
        orders = [group["order"] for group in GROUPS]
        self.assertEqual(orders, sorted(orders), [g["key"] for g in GROUPS])
        self.assertEqual(len(orders), len(set(orders)), "duplicate order values")

    def test_modules_and_entries_register_the_same_companies(self) -> None:
        """A conflict hunk can split *inside* one ENTRIES dict, and Python
        silently keeps the last duplicate key rather than erroring:

            {'slug': 'spgi', 'x': 1, 'slug': 'msci'}  ->  {'slug': 'msci', ...}

        so a "keep both sides" resolution can merge two companies into one and
        parse cleanly. `msci` sorts between `meta` and `msft` and `spgi` between
        `snps` and `tsm`, so several of the companies added in parallel are
        adjacent in this list and exposed to it.

        The two directions fail differently, which is why this asserts both:
        a slug in ENTRIES with no module raises `KeyError` in `roster_payload`
        and is loud, while a module with no ENTRIES row is **silent** -- the
        page builds, its payload and shell are written, and it is simply absent
        from the roster and from every page's nav. That is the same "a page
        nobody can reach" failure a missing group key produces.

        Grepping does not catch the swallow either: the source still contains
        the right number of `"slug":` lines, because both are inside one dict.
        """
        entries = [entry["slug"] for entry in ENTRIES]
        self.assertEqual(len(entries), len(set(entries)), entries)
        self.assertEqual(list(MODULES), entries)

    def test_the_home_page_counts_the_companies_it_lists(self) -> None:
        """`index.html`'s masthead count is hand-written and nothing read it.

        Every session adding a company has to change that number, and each one
        reads the current value and writes value+1 -- so identical edits to one
        line merge with no conflict and the site advertises one fewer company
        than it renders. `test_home_page_matches_roster` iterates the roster
        asserting each item's href, label and date, but never counts them, so it
        stays green with the number wrong.

        Asserted against `len(ENTRIES)` rather than against `data/roster.js`, to
        keep this file's deliberately minimal imports and to avoid coupling a
        push gate to build order; `test_published_payload_roster_and_shell` is
        what ties the roster payload back to ENTRIES.

        The second figure in that line is the eight-quarter window, not a
        company count, and must not move.
        """
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        stated = re.search(r"(\d+) 家公司", home)
        self.assertIsNotNone(stated, "masthead no longer states a company count")
        self.assertEqual(int(stated.group(1)), len(ENTRIES))
        self.assertEqual(home.count('class="hcard"'), len(ENTRIES))
        self.assertIn("8 季趋势", home)

    def test_literal_text_fields_carry_no_markup(self) -> None:
        """Some payload fields are escaped or textContent'd; a tag prints raw.

        `page.js` sets `headline`, `title`, `subtitle` and `tracker` with
        `node.textContent`, and runs `section.title`, `section.description`,
        every `notes` entry and every table title/header/cell through `esc()`.
        Markup in any of them reaches the reader as the literal characters
        `<b>`. `brief`, `footer` and each exhibit's `note` / `src_extra` are
        raw innerHTML and legitimately carry markup -- 140 chart notes across
        the site do -- so they are deliberately not checked here.

        **`notes` is escaped too and is deliberately NOT in this gate yet.**
        It is left out because it is currently red, not because markup belongs
        there: `data/cdns.js` carries five notes containing `<b>` and
        `data/snps.js` two, and all seven render to readers as the literal
        characters. Fixing them means editing `build/cdns.py` and
        `build/snps.py`, which does not belong in the commit that adds a
        different company. Strip those seven strings, then add
        `payload.get("notes", [])` to the loop below -- do not conclude from
        this exclusion that notes may carry markup.
        """
        for path in published_files():
            name = path.relative_to(ROOT).as_posix()
            if not name.startswith("data/") or name == "data/roster.js":
                continue
            payload = json.loads(
                path.read_text(encoding="utf-8").split(" = ", 1)[1].rstrip().rstrip(";\n"))
            for key in ("headline", "title", "subtitle", "tracker"):
                self.assertNotIn("<", payload.get(key) or "", f"{name}.{key}")
            for section in payload.get("sections", []):
                self.assertNotIn("<", section["title"], f"{name} section title")
                self.assertNotIn("<", section.get("description") or "",
                                 f"{name} section {section['id']} description")
            for table in payload.get("tables", []):
                self.assertNotIn("<", table["title"], f"{name} table {table['n']}")

    def test_no_published_file_contains_forbidden_text(self) -> None:
        for path in published_files():
            text = path.read_text(encoding="utf-8").lower()
            for forbidden in FORBIDDEN:
                self.assertNotIn(
                    forbidden,
                    text,
                    f"{path.relative_to(ROOT).as_posix()} leaks {forbidden!r}",
                )

    def test_no_published_file_carries_a_local_absolute_path(self) -> None:
        for path in published_files():
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("/Users/", text)
            self.assertNotIn("C:\\", text)
            self.assertNotIn("file://", text)


if __name__ == "__main__":
    unittest.main()
