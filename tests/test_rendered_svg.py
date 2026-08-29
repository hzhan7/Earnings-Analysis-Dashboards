"""Run `tests/render_check.js` -- the only gate that looks at a rendered chart.

Everything else in this suite reads payloads and source. `build/payload_guard.py`
rejects a non-finite number *in the payload*; `build/all.py && git status`
proves the payload is a pure function of the reviewed series; the per-company
tests pin the numbers. None of them renders anything, so a NaN produced by the
renderer's own arithmetic -- one call after the payload was read -- passes all
475 of them. AVGO Exhibit 16 shipped `<line y1="NaN">` that way, and the browser
drops such an element without a console message, so the chart looked complete.

This runs the same page load a browser does, under jsdom, and fails on any
non-finite value that reaches an SVG attribute or a chart label.

jsdom is the repo's only third-party dependency and is deliberately not
vendored: a static site published by GitHub Pages should not need `npm install`
to build. So this test **skips** when node or jsdom is missing, and the skip
message says how to make it run:

    npm --prefix tests install

A skipping gate protects nothing on a machine that never installs it, which is
why `tests/test_chart_contract.py` exists alongside this file and pins the same
defect from the source and the payloads with no dependency at all. Treat that
one as the guard and this one as the proof.
"""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK = Path(__file__).resolve().parent / "render_check.js"


def _node() -> str | None:
    return shutil.which("node")


def _jsdom_resolves(node: str) -> bool:
    """Whether `require('jsdom')` works from `tests/`.

    Resolution is run with `cwd=tests` so it finds `tests/node_modules`, which
    is what `npm --prefix tests install` creates and what `.gitignore` keeps out
    of the tree.
    """
    return subprocess.run(
        [node, "-e", "require.resolve('jsdom')"],
        cwd=CHECK.parent,
        capture_output=True,
    ).returncode == 0


class RenderedSvgTest(unittest.TestCase):
    def test_the_check_script_is_present(self) -> None:
        """Runs everywhere, including where the skip below applies.

        The failure this guards against is the check quietly disappearing from
        the tree while the test that runs it keeps reporting a tidy `skipped`.
        """
        self.assertTrue(CHECK.is_file(), f"{CHECK.relative_to(ROOT)} is missing")

    def test_every_page_renders_without_a_non_finite_value(self) -> None:
        node = _node()
        if node is None:
            self.skipTest("node is not on PATH; the rendered-SVG gate did not run")
        if not _jsdom_resolves(node):
            self.skipTest(
                "jsdom is not installed, so the rendered-SVG gate did not run. "
                "Install it with `npm --prefix tests install`."
            )
        result = subprocess.run(
            [node, str(CHECK), str(ROOT)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode, 0,
            "a published page renders a broken chart:\n"
            + result.stdout + result.stderr,
        )


if __name__ == "__main__":
    unittest.main()
