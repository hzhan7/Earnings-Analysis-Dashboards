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

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

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
    "anthropic",
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


class ContentBoundaryTest(unittest.TestCase):
    def test_scan_covers_every_company(self) -> None:
        """A company whose files stopped being discovered would pass vacuously."""
        names = {path.relative_to(ROOT).as_posix() for path in published_files()}
        self.assertIn("data/roster.js", names)
        self.assertIn("index.html", names)
        for slug in ("googl", "meta", "msft", "tsm"):
            self.assertIn(f"series/{slug}.json", names)
            self.assertIn(f"data/{slug}.js", names)
            self.assertIn(f"{slug}/index.html", names)

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
