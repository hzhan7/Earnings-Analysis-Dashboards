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
    "amzn", "avgo", "axp", "bc", "cboe", "cdns", "cme", "cost", "googl", "ibkr",
    "ma", "mco",
    "meta", "msci", "msft", "mu", "ndaq", "nke", "nvda", "pm", "race", "rms",
    "samsung", "schw", "skhynix", "snps", "spgi", "tjx", "tsm", "v",
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


    def test_every_card_sits_under_the_group_it_registered(self) -> None:
        """A card in the wrong group is invisible to every other check.

        `index.html` is hand-written, and its cards are ordered **by group,
        then alphabetically within the group** -- not by global slug order.
        That is easy to get backwards, because `COMPANY_SLUGS` here and the
        roster literal in `test_tsm_dashboard.py` are both global-alphabetical:
        the same change touches two lists sorted one way and one sorted
        another.

        Nothing bound a card to the `<h2>` above it. `test_spgi_dashboard.py`
        asserts each group's heading *exists*; `test_home_page_matches_roster`
        asserts each slug's href *appears somewhere*; the counting assertion
        above only counts. Verified by mutation on 2026-08-29: moving the
        `skhynix` card out of 半导体与 AI 基础设施 and under 券商与财富管理 left
        the entire suite green and the len/hcard/masthead triple reading
        `26 26 26`. A reader would see a memory maker filed under brokerages.
        """
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        label_of = {group["key"]: group["label"] for group in GROUPS}
        group_of = {entry["slug"]: entry.get("group") for entry in ENTRIES}
        seen: dict[str, list[str]] = {}
        current = None
        for label, slug in re.findall(
            r'<h2 class="hubgrp">([^<]*)</h2>|<a class="hcard" href="([a-z0-9]+)/"', home
        ):
            if label:
                current = label.strip()
                seen.setdefault(current, [])
            else:
                self.assertIsNotNone(current, f"{slug} card precedes every group heading")
                seen[current].append(slug)
        misfiled = [
            f"{slug} is filed under {heading!r} but registers {label_of.get(group_of.get(slug))!r}"
            for heading, slugs in seen.items()
            for slug in slugs
            if label_of.get(group_of.get(slug)) != heading
        ]
        self.assertEqual(misfiled, [], "\n".join(misfiled))
        self.assertEqual(
            sorted(s for slugs in seen.values() for s in slugs),
            sorted(group_of),
            "the cards on the home page are not the registered roster",
        )

    def test_the_readme_names_every_page_whose_fiscal_year_is_offset(self) -> None:
        """The calendar-quarter paragraph must name every page that needs it.

        Each company whose fiscal year differs from the calendar one carries
        `本站按自然年季度标注` in its registry `cadence_label`, and the README
        paragraph beginning "Quarters are labelled by calendar
        quarter" is where a reader goes to find the whole set. Nothing kept the
        two in step: the marker lives in a generated payload, the paragraph is
        hand-written prose, and no test read either.

        Found on 2026-08-29 while landing Micron, whose page declares an
        August fiscal year-end. It was absent from the paragraph -- and so were
        **Costco and TJX**, which had been shipping that way since long before
        that day. Five of the eight offset pages were named, three were not, and
        every gate was green: the paragraph has no count to check and no roster
        to compare against, so a missing clause is invisible in exactly the way
        CLAUDE.md §4 says that sentence's contents always have been.

        Keyed on `cadence_label` in ENTRIES rather than on the generated
        subtitle. Both are prose, but the registry field is the one that sits
        beside the company and states what the site *does* ("relabelled to
        calendar quarters") instead of describing a year-end month, and it is
        the more complete of the two: the subtitle marker `制财年` misses
        Microsoft, which is an offset filer and is named in the paragraph.
        A prose key is still a key on wording, which is the weakness CLAUDE.md
        §5 records; `assertGreaterEqual` below is what actually holds it up --
        it is what caught the set silently shrinking from 8 to 7 when the
        Micron page reworded its subtitle an hour after this landed.
        """
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        paragraphs = [p for p in readme.split("\n\n")
                      if "Quarters are labelled by calendar quarter" in p]
        self.assertEqual(len(paragraphs), 1,
                         "the calendar-quarter paragraph is not findable")
        para = paragraphs[0]
        missing = []
        offset = []
        for entry in ENTRIES:
            slug = entry["slug"]
            if "本站按自然年季度标注" not in (entry.get("cadence_label") or ""):
                continue
            offset.append(slug)
            known = [entry["name"], *entry.get("aliases", [])]
            named = any(k.lower() in para.lower() for k in known)
            # `The TJX Companies` is named in prose as plain `TJX`, which is
            # neither its registered name nor any alias. The slug is the
            # registry's own short form, so accept it as a standalone word --
            # length-gated so that `v` cannot match a stray letter.
            if not named and len(slug) >= 3:
                named = re.search(rf"\b{re.escape(slug)}\b", para, re.I) is not None
            if not named:
                missing.append(f"{slug} declares an offset fiscal year but the paragraph does not name it")
        self.assertGreaterEqual(len(offset), 9, f"offset pages found: {offset}")
        self.assertEqual(missing, [], "\n".join(missing))

    def test_cards_run_in_slug_order_inside_each_group(self) -> None:
        """Which makes "where does my card go" a question with one answer.

        Every group on the page is already sorted this way, and three sessions
        adding a company at once need the insertion point to be derivable
        rather than negotiated.
        """
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        unsorted = []
        current = None
        seen: dict[str, list[str]] = {}
        for label, slug in re.findall(
            r'<h2 class="hubgrp">([^<]*)</h2>|<a class="hcard" href="([a-z0-9]+)/"', home
        ):
            if label:
                current = label.strip()
                seen.setdefault(current, [])
            else:
                seen[current].append(slug)
        for heading, slugs in seen.items():
            if slugs != sorted(slugs):
                unsorted.append(f"{heading}: {slugs} != {sorted(slugs)}")
        self.assertEqual(unsorted, [], "\n".join(unsorted))
    def test_the_readme_lists_every_company_page(self) -> None:
        """`README.md`'s preview-URL list is hand-written and nothing read it.

        Registering a company touches the builder, `MODULES`, `ENTRIES` and the
        roster -- each of which either raises or is asserted by the tests above
        -- and then a Markdown list that no test and no build step ever opens.
        So the README is the one place a company can be missed while every gate
        stays green -- and it is the normal outcome, not an accident anyone can
        be told to stop having. Of the 30 commits that touched both this list
        and `build/all.py`, **9 shipped a list shorter than the roster**:
        `a8525ed` 8/9, `2268de7` 11/12, `14f2512` 12/13, `c7f846e` 13/14,
        `a2b7dbe` 14/15, `52d48ff` 14/16, `b379a9e` 16/17, `ad86a37` 17/18,
        `6aba75a` 17/18. The gap is not brief either: `schw` landed in `a8525ed`
        and was absent here for sixteen commits until `b379a9e`; `msci` landed
        in `52d48ff` and was absent for seven until `be9cdbd` backfilled it
        while adding NKE. At `52d48ff` the list was two companies behind at
        once, which is why this asserts a set difference and not a length.

        Parsed from the anchored bullet form rather than from the bare URL, so a
        page address written inline in the prose -- `## Verification` invites
        exactly that -- is not counted as a twenty-fourth entry.

        The opening paragraph that names the companies is a separate problem
        and is **not** pinned here. Pinning it *by name* does work, and needs no
        suffix-stripping heuristic, but only in one direction: its short forms
        are contained *by* the registered names rather than equal to them, so
        `prose inside registered` is what carries them -- drop that direction
        and `meta` (`Meta` vs `Meta Platforms`) and `tjx` (`TJX` vs `The TJX
        Companies`) stop resolving, while dropping the opposite direction
        currently costs nothing. Counting the names instead was rejected rather
        than deferred: two registered names already contain a comma
        (`NIKE, Inc.`, `Nasdaq, Inc.`), so a writer copying a registered name
        into the prose would false-fail a count -- and a push gate that
        false-fails gets bypassed with `--no-verify` and then protects nothing.

        Order is asserted against `sorted()` rather than against `ENTRIES`' own
        order: the README presents an alphabetical-by-slug list, and that is the
        order a reader scans, so it holds even if `ENTRIES` is ever reordered.
        """
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        listed = re.findall(
            r"^- `http://127\.0\.0\.1:8765/([a-z0-9]+)/`$", readme, re.M)
        slugs = [entry["slug"] for entry in ENTRIES]

        self.assertEqual(
            sorted(set(slugs) - set(listed)), [], "registered but absent from README"
        )
        self.assertEqual(
            sorted(set(listed) - set(slugs)), [], "listed in README but not registered"
        )
        self.assertEqual(listed, sorted(slugs))

    def test_the_readme_paragraph_names_every_company(self) -> None:
        """The `Reviewed pages currently cover ...` sentence is its own mirror.

        It drifts separately from the bullet list below it. Of the 35 commits
        that touched README.md, 30 can be judged here (the rest predate one of
        the two files), and four of those left this sentence short: `c7f846e`
        had 13 names for 14 companies, `b379a9e` 16 for 17, `ad86a37` and
        `6aba75a` 17 for 18. Those four are a strict subset of the five that
        left the bullet list short, and the fifth is the proof that the two
        drift on their own: at `a2b7dbe` this sentence named all 15 companies
        while the list below it was missing one. Two hand-maintained rosters in
        one file, each missed on its own occasions.

        Matched on ENTRIES' own `name` and `aliases` rather than by counting
        the names, and containment in either direction, because what this has
        to survive is ordinary editing of English prose:

          - the sentence writes `Meta`, `TJX` and `NIKE` where ENTRIES has
            `Meta Platforms`, `The TJX Companies` and `NIKE, Inc.` -- prose
            shorter than the registered name;
          - writing `Costco Wholesale Corporation` for `Costco Wholesale` is
            the same thing the other way round;
          - three registered names contain a comma -- `NIKE, Inc.`,
            `Nasdaq, Inc.` and `Cboe Global Markets, Inc.` -- so splitting on
            commas and counting the pieces goes red on a correct sentence as
            soon as anyone writes a company the way ENTRIES spells it. That
            set only grows: zero comma-bearing names at 17 companies
            (`fde8497`), two at 23 (`f3bf923`), three at 24 (`dad3f80`). A
            count would have looked provably safe the whole way -- no
            counterexample to mutate against -- and gone red years later for
            whoever happened to register the next `..., Inc.`. A gate that
            fires on a clean tree gets bypassed, and then it guards nothing.

        The paragraph is read to the blank line, not to the first `.` at a line
        end, for the same reason from the other side: seven registered names
        carry a period (`Amazon.com`, `CME Group Inc.`, `MSCI Inc.`,
        `Ferrari N.V.` and the three above). Stopping at `\.\n` truncates the
        sentence the moment a wrap puts one of them last on a line, and every
        company after the wrap is then reported missing -- a failure that names
        the wrong company and sends the reader looking at the wrong end of the
        paragraph.

        Replayed over every commit that touched README.md: this catches all
        four misses, names the company each time (`schw` once, `msci` three
        times -- a count only ever says how many), and is ambiguous or falsely
        red at none of them. If a future company is named in prose by nothing
        resembling its `name` or any alias, the fix is to add that alias.

        Bullet-list coverage is `test_the_readme_links_every_company_page`;
        the semicolon-chained sentence further down is deliberately unguarded
        -- it broke by becoming a dangling fragment, not by losing a company,
        which neither a count nor a name can see.
        """
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        match = re.search(r"Reviewed pages currently cover (.+?)\.\n\n", readme, re.S)
        self.assertIsNotNone(match, "README no longer names the covered companies")
        sentence = " ".join(match.group(1).split())
        written = [name.strip() for name in re.split(r",\s*|\s+and\s+", sentence) if name.strip()]
        for entry in ENTRIES:
            known = [entry["name"], *entry.get("aliases", [])]
            self.assertTrue(
                any(w.lower() in k.lower() or k.lower() in w.lower()
                    for w in written for k in known),
                f"{entry['slug']} has a page but is not named in the README paragraph",
            )

    def test_literal_text_fields_carry_no_markup(self) -> None:
        """Some payload fields are escaped or textContent'd; a tag prints raw.

        `page.js` sets `headline`, `title`, `subtitle` and `tracker` with
        `node.textContent`, and runs `section.title`, `section.description`,
        every `notes` entry and every table title/header/cell through `esc()`.
        Markup in any of them reaches the reader as the literal characters
        `<b>`. `brief`, `footer` and each exhibit's `note` / `src_extra` are
        raw innerHTML and legitimately carry markup -- 140 chart notes across
        the site do -- so they are deliberately not checked here.

        `notes` is in this gate rather than excluded from it. It was the one
        escaped slot that was actually red across the site: seventeen notes in
        all -- `data/avgo.js` seven (fixed in `fde8497`), `data/cdns.js` five,
        `data/schw.js` three, `data/snps.js` two -- every one of them reaching
        the reader as the characters `<b>`. None of those seventeen sentences
        was reused in an innerHTML slot, so the markup was dead in the source
        as well as wrong in the output; the fix was to delete the tags, not to
        strip them at build time. Adding a `<b>` back to a note in any of the
        thirteen unwrapped builders turns this red.

        **It cannot go red for `v`, `ibkr`, `mco` or `spgi`**, whose payloads
        build notes as `[plain_text(p) for p in [...]]` and so strip any tag
        before it reaches the payload this test reads. Those four are protected
        by construction rather than by this assertion -- do not read a green
        run as evidence that their builders carry no markup.
        """
        for path in published_files():
            name = path.relative_to(ROOT).as_posix()
            if not name.startswith("data/") or name == "data/roster.js":
                continue
            payload = json.loads(
                path.read_text(encoding="utf-8").split(" = ", 1)[1].rstrip().rstrip(";\n"))
            for key in ("headline", "title", "subtitle", "tracker"):
                self.assertNotIn("<", payload.get(key) or "", f"{name}.{key}")
            for index, note in enumerate(payload.get("notes", [])):
                self.assertNotIn("<", note, f"{name} note {index}")
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
