"""Every repo path the README names has to exist.

The README is the one published file with nothing checking it, and it has
already drifted twice in a single day. It said the render gate loads "all 17
pages" while the site had grown to 23, and a session reading it concluded the
suite was undocumented because the section is called `## Verification` rather
than `## Tests`. Both were caught by a person happening to look.

Renaming a test file is the same failure with a worse tail: `## Verification`
tells a reader to run `node tests/render_check.js`, and if that file moves the
README goes on giving an instruction that fails on a fresh clone, while every
test stays green.

**The list of paths is not written down here.** A hand-maintained list would be
the next thing to rot -- the same defect as the "17 pages" this repo removed
from the README, and as a `line 45` comment removed from `test_chart_contract.py`
in the same commit. The paths are extracted from the README itself, so a path
added to the prose tomorrow is covered tomorrow.

What counts as a path claim, and why commands do not:

* A token must contain `/`. That single rule is what separates
  `tests/render_check.js` from `python3`, `-m`, `unittest`, `discover`, `-s`,
  `tests`, `-q`, `npm`, `--prefix`, `install` and `node` -- every token of every
  command block in the README, none of which has a slash. It is a rule about
  shape, not an allow-list of command names, so a new command needs no
  maintenance here.
* A bare filename is deliberately **not** a path claim, and the README proves
  why: it discusses the `index.json` inside an EDGAR accession, which is a file
  on the SEC's servers and must never be looked for in this tree. Requiring the
  slash costs nothing real -- every path this repo actually names is written
  repo-relative, with a directory in front of it.
* URLs are rejected by scheme, so the twenty-three
  `http://127.0.0.1:8765/<slug>/` preview links do not become path claims.
* Anything outside `[A-Za-z0-9._/-]` is rejected, which drops the prose spans:
  `<line y1="NaN">`, `OK (skipped=1)`, `~30%`, `$5,047M +/- $75M`, and the
  Chinese section names.

Both forms the README uses are scanned: inline `` `backtick` `` spans, and
whitespace-split tokens inside fenced blocks -- the fenced ones matter because
they are what a reader copies and runs.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"

_FENCED = re.compile(r"```[A-Za-z0-9]*\n(.*?)```", re.S)
_INLINE = re.compile(r"`([^`\n]+)`")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_SHAPE = re.compile(r"^[A-Za-z0-9._/-]+$")

# Tokens that are not path claims, kept as a test rather than a comment so the
# rule above cannot be loosened without someone seeing what it would let in.
NOT_PATHS = (
    "index.json",            # an EDGAR accession's file, not one of ours
    "python3", "-m", "unittest", "discover", "-s", "tests", "-q",
    "npm", "--prefix", "install", "node", "http.server", "8765",
    "http://127.0.0.1:8765/avgo/",
    "_CASH_CAPEX_SOURCES",
    "test_cdns_is_not_in_the_cross_page_capex_table",
    "OK (skipped=1)", "Ran N", '<line y1="NaN">', "~1.27", "29% to 30%",
)


def is_path_claim(token: str) -> bool:
    """Whether `token` asserts that a file exists in this repository."""
    return (
        bool(_SHAPE.match(token))
        and "/" in token
        and not _SCHEME.match(token)
    )


def readme_paths() -> dict[str, str]:
    """`{path: which form of the README it came from}`."""
    text = README.read_text(encoding="utf-8")
    found: dict[str, str] = {}
    for block in _FENCED.findall(text):
        for token in block.split():
            if is_path_claim(token):
                found.setdefault(token, "a command block")
    for span in _INLINE.findall(_FENCED.sub("", text)):
        if is_path_claim(span):
            found.setdefault(span, "prose")
    return found


class ReadmeReferenceTest(unittest.TestCase):
    def test_every_repo_path_the_readme_names_exists(self) -> None:
        for path, where in sorted(readme_paths().items()):
            with self.subTest(path=path):
                # `ROOT / "/abs"` is `/abs` in pathlib, so an absolute path
                # would be looked up outside the tree and could pass on the
                # author's machine. Published files may not carry one anyway.
                self.assertFalse(
                    path.startswith("/") or ".." in Path(path).parts,
                    f"README names `{path}` in {where}; repo paths are written "
                    "relative to the root, without `..`")
                self.assertTrue(
                    (ROOT / path).exists(),
                    f"README names `{path}` in {where}, and it is not in the "
                    "tree. Rename the reference, or restore the file.")

    def test_the_scan_reads_both_forms_the_readme_uses(self) -> None:
        """Guards against a green light nobody earned.

        If the README were reformatted so that no token matched -- backticks
        dropped, commands moved into prose -- every assertion above would pass
        over an empty set and this file would report success while checking
        nothing. Both channels must keep yielding, because they fail
        independently: prose names files the commands never mention, and the
        command blocks are the part a reader actually runs.
        """
        found = readme_paths()
        self.assertGreaterEqual(
            len(found), 5,
            f"only {len(found)} path(s) extracted from the README; the scan is "
            "no longer finding what it is supposed to check")
        for form in ("prose", "a command block"):
            self.assertIn(
                form, found.values(),
                f"no repo path extracted from {form} in the README")

    def test_the_rule_rejects_what_is_not_a_path(self) -> None:
        for token in NOT_PATHS:
            with self.subTest(token=token):
                self.assertFalse(is_path_claim(token), token)

    def test_the_rule_accepts_the_shapes_this_repo_writes(self) -> None:
        for token in ("build/all.py", "assets/charts.js", "tests/render_check.js",
                      "data/roster.js", "series/avgo.json", "hooks/pre-push"):
            with self.subTest(token=token):
                self.assertTrue(is_path_claim(token), token)


if __name__ == "__main__":
    unittest.main()
