"""A duplicate key in a dict literal is legal Python and silently wins.

`{"a": 1, "a": 2}` does not raise, does not warn, and evaluates to `{"a": 2}`.
So every check that runs *after* parsing -- the build, the payload guard, every
assertion in this suite -- sees a dict that is already missing whatever the
duplicate overwrote. The defect is only visible in the source, which is why
this file reads the source with `ast` instead of importing anything.

This is not hypothetical. It is the shape behind two separate incidents in this
repo on 2026-08-29, and it was about to cause a third:

- **`ENTRIES`, from a rebase.** A conflict hunk split *inside* one entry's dict
  literal, and resolving it as "keep both sides" fused the two companies into a
  single dict carrying `"slug"` twice. Python kept the last one, so `MODULES`
  had 21 entries while `ENTRIES` had 20 and a company nobody had touched went
  missing. Grepping did not catch it either: the file still contained the right
  number of `"slug":` lines, because both were inside one dict.
  `test_modules_and_entries_register_the_same_companies` does catch the
  consequence, but only as "why is a company I never worked on absent", one
  step removed from the cause.
- **`UNIT_FORMATS` in `build/board.py`.** Two sessions adding an exchange page
  at the same time both needed a `contracts_k` formatter. Appending the same
  key at two different positions merges with **no conflict** -- the hunks do
  not overlap -- and leaves the key twice. Nothing downstream can tell.

Note what this does and does not overlap with. `test_group_keys_are_unique`
guards a different failure: two *separate* dicts in the `GROUPS` list carrying
the same `key` field. That is a duplicate row, not a duplicate key, and it
stays invisible to this file. The two guards are complements.

Scoped to `build/` deliberately. That is where the registration surface lives
(`MODULES`, `ENTRIES`, `GROUPS`, `UNIT_FORMATS`, every exhibit dict), and it is
the code whose output is published. Test fixtures are excluded because a test
may legitimately construct a dict twice over to demonstrate the very behaviour
this file exists to forbid -- a gate that false-fails gets bypassed with
`--no-verify` and then protects nothing.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def duplicate_keys(path: Path) -> list[tuple[int, object]]:
    """`(line, key)` for every constant key that appears twice in one dict literal.

    Only keys `ast.literal_eval` can resolve are compared. A computed key
    (`{f(x): 1}`) is skipped rather than guessed at, and `**spread` entries --
    which `ast` represents as a `None` key -- are skipped too, because
    duplication there is resolved at runtime by design.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, object]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        seen: set[object] = set()
        for key_node in node.keys:
            if key_node is None:
                continue
            try:
                key = ast.literal_eval(key_node)
            except (ValueError, SyntaxError):
                continue
            if not isinstance(key, (str, int, float, bool, tuple)):
                continue
            if key in seen:
                found.append((key_node.lineno, key))
            seen.add(key)
    return found


class DictLiteralTest(unittest.TestCase):
    def test_no_builder_dict_literal_repeats_a_key(self) -> None:
        offenders = []
        for path in sorted((ROOT / "build").glob("*.py")):
            for line, key in duplicate_keys(path):
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{line} repeats {key!r}")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_the_scan_reaches_every_builder(self) -> None:
        """A scan that silently stops finding files reports success forever.

        `duplicate_keys` is only as good as the set it is pointed at, and that
        set is a glob. If `build/` were reorganised into packages the glob would
        quietly return fewer files and the test above would keep passing.
        """
        scanned = {p.name for p in (ROOT / "build").glob("*.py")}
        self.assertIn("all.py", scanned)
        self.assertIn("board.py", scanned)
        self.assertGreaterEqual(len(scanned), 20, sorted(scanned))

    def test_the_detector_actually_detects(self) -> None:
        """Pin the detector against a literal, not against the tree.

        The assertion above passes on a clean tree whether or not
        `duplicate_keys` works at all, so it cannot on its own distinguish "no
        duplicates" from "no detection". This one fails if the walk, the
        `literal_eval` or the `seen` set stops working.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            sample = Path(tmp) / "sample.py"
            sample.write_text(
                'D = {"slug": "spgi", "ticker": "SPGI", "slug": "msci"}\n'
                'CLEAN = {"a": 1, "b": 2}\n'
                'NESTED = {"outer": {"x": 1, "x": 2}}\n',
                encoding="utf-8",
            )
            found = duplicate_keys(sample)
        self.assertEqual([key for _, key in found], ["slug", "x"], found)


if __name__ == "__main__":
    unittest.main()
