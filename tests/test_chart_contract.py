"""The payload/renderer contract for exhibit fields, checked without a browser.

`tests/render_check.js` is the gate that actually looks at rendered SVG, and it
is the one that would have caught AVGO Exhibit 16. It needs node and jsdom, so
on a fresh clone it skips. This file is what runs unconditionally: pure stdlib,
no third-party dependency, and it pins the two halves of that defect that can be
checked from the source and the payloads alone.

The defect, for whoever reads this next. `assets/charts.js` draws the gs_bar
reference line from `ex.avg12` — a number the payload supplies and the engine
never computes — whenever `ex.yoy` is absent. Across the site 27 exhibits are
gs_bar, 26 carry `yoy`, and **none has ever carried `avg12`**, so that branch
had never been exercised with real data. AVGO Exhibit 16 supplies neither, so
`Y(undefined)` produced `y1="NaN"`, the browser dropped the `<line>` without a
word, and the legend went on advertising a `Prior 12mo Avg.` dashed swatch for a
line that was not on the canvas. 475 tests, `build/payload_guard.py` and
`build/all.py && git status` were all green throughout: the guard scans for
non-finite values *in the payload*, and this NaN was born in the renderer's
arithmetic, one call after the payload was read.

So the two things pinned here are:

* the renderer never feeds a possibly-absent payload value into a coordinate
  without an `isNum` guard in front of it, and never prints a legend entry for
  a reference line it did not draw; and
* the payloads never half-declare one — `avg12` present but not a finite
  number is exactly the shape `payload_guard` lets through (it rejects float
  NaN and infinity, not `null` or `"n/a"`).
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.all import ENTRIES  # noqa: E402

CHARTS = ROOT / "assets" / "charts.js"

# Renderer branches that no published payload reaches. Hand-written, and that
# is the point: the whole failure above is what an unexercised branch does the
# first time a real exhibit walks into it, and nothing anywhere marked that
# branch as unexercised. A payload that starts using one of these turns
# `test_unexercised_renderer_branches_are_declared` red -- that is a prompt to
# read the branch and this file before publishing, not a bug. Delete the entry
# once the kind has a real exhibit behind it.
UNEXERCISED_KINDS = frozenset({
    "gs_line_avg",
    "heat_matrix",
    "seasonality",
    "year_lines",
    "qtr_bar",
})


def payloads() -> list[tuple[str, dict]]:
    """`(slug, payload)` for every published company payload."""
    out = []
    for entry in ENTRIES:
        slug = entry["slug"]
        text = (ROOT / "data" / f"{slug}.js").read_text(encoding="utf-8")
        out.append((slug, json.loads(text.split(" = ", 1)[1].rstrip().rstrip(";\n"))))
    return out


def exhibits() -> list[tuple[str, dict]]:
    """`(label, exhibit)` for every exhibit on every page."""
    out = []
    for slug, payload in payloads():
        for section in payload.get("sections", []):
            for exhibit in section.get("exhibits", []):
                out.append((f"{slug} Ex{exhibit.get('n', '?')}", exhibit))
    return out


class RendererGuardTest(unittest.TestCase):
    """Source-level pins on `assets/charts.js`."""

    def test_no_reference_line_is_drawn_from_an_unguarded_value(self) -> None:
        """Every `Y(avg)` / `fv(avg)` site sits behind an `isNum(avg)` guard.

        `avg` is `ex.avg12` and nothing else -- the engine does not compute a
        fallback, by design (`build_data.py` owns every number that reaches an
        axis). So the value is absent for any exhibit that simply does not
        declare it, and `Y(undefined)` is NaN rather than an error.

        Asserted as "an `isNum(avg)` appears in the twelve lines above the
        use" rather than by parsing the branch structure: the two current sites
        are `if (!yoyS && isNum(avg))` in gs_bar and
        `if (kind === 'gs_line_avg' && isNum(avg))`, both with a comment block
        between the guard and the draw. A restructuring that moves a use out of
        that window fails this test, which is the intended outcome -- come read
        the guard, then re-pin it.
        """
        lines = CHARTS.read_text(encoding="utf-8").splitlines()
        uses = [i for i, line in enumerate(lines)
                if re.search(r"\b(?:Y|Y2|fv)\(avg\)", line)]
        self.assertTrue(uses, "the reference-line draw sites moved or were renamed")
        for i in uses:
            window = "\n".join(lines[max(0, i - 12): i + 1])
            self.assertRegex(
                window, r"isNum\(avg\)",
                f"assets/charts.js:{i + 1} draws from `avg` with no isNum guard above it:"
                f"\n    {lines[i].strip()}",
            )

    def test_no_legend_promises_a_reference_line_that_was_not_drawn(self) -> None:
        """The legend is the visible half of the same defect.

        The line is geometry the browser can silently drop; the legend is HTML
        it always renders. AVGO Exhibit 16 shipped a navy dashed swatch reading
        `Prior 12mo Avg.` next to a chart that had no dashed line on it, which
        is worse than a missing line: it tells the reader to look for something
        that is not there. `legendHTML` must decide on the same condition the
        draw site does, so both entries are pinned to `isNum(ex.avg12)`.
        """
        lines = CHARTS.read_text(encoding="utf-8").splitlines()
        claims = [line for line in lines
                  if "Prior 12mo Avg." in line and "items.push" in line]
        self.assertEqual(len(claims), 2, "expected one legend claim per avg-line kind")
        for line in claims:
            self.assertIn("isNum(ex.avg12)", line, line.strip())

    def test_every_kind_a_payload_uses_is_one_the_renderer_implements(self) -> None:
        """A misspelt `kind` falls through to the engine's final `else`.

        `render()` dispatches on a chain of `kind === '…'` comparisons; the tail
        of that chain is not an error path, so an exhibit naming a kind that
        does not exist renders as whatever the last branch happens to do, on a
        page that otherwise looks built. Both sides of this comparison are read
        from source, so it needs no maintenance when a kind is added.
        """
        source = CHARTS.read_text(encoding="utf-8")
        implemented = set(re.findall(r"kind === '([a-z_0-9]+)'", source))
        self.assertTrue(implemented, "the dispatch chain moved or was renamed")
        for label, exhibit in exhibits():
            if "kind" not in exhibit:
                continue
            self.assertIn(exhibit["kind"], implemented, label)

    def test_unexercised_renderer_branches_are_declared(self) -> None:
        """Name the branches no published payload reaches -- see UNEXERCISED_KINDS.

        Asserted as an equality so it fires in every direction. A kind leaving
        the list is a branch getting its first real exhibit -- the AVGO Exhibit
        16 situation arriving again, so read the branch end to end, then drop
        the entry. A kind joining it is either a new unused kind or an existing
        one whose last exhibit was removed, and a branch nothing renders is a
        branch nothing checks. Either way the fix is one line here, after
        someone has looked.
        """
        source = CHARTS.read_text(encoding="utf-8")
        implemented = set(re.findall(r"kind === '([a-z_0-9]+)'", source))
        used = {exhibit["kind"] for _, exhibit in exhibits() if "kind" in exhibit}
        self.assertEqual(
            sorted(implemented - used), sorted(UNEXERCISED_KINDS),
            "the set of renderer branches with no published exhibit behind them "
            "moved; read the branch in assets/charts.js before updating this list",
        )


class ExhibitPayloadContractTest(unittest.TestCase):
    """What the payloads are allowed to declare."""

    def test_a_declared_average_is_a_finite_number(self) -> None:
        """`payload_guard` does not cover this shape.

        It rejects a float that is NaN or infinite and any string that reads as
        one. `"avg12": null` and `"avg12": "n/a"` pass it cleanly and still
        reach `Y()` as something that is not a number. Declaring the field at
        all is a promise that the reference line has a value.
        """
        for label, exhibit in exhibits():
            if "avg12" not in exhibit:
                continue
            value = exhibit["avg12"]
            self.assertIsInstance(value, (int, float), f"{label} avg12={value!r}")
            self.assertNotIsInstance(value, bool, f"{label} avg12={value!r}")
            self.assertEqual(value, value, f"{label} avg12 is NaN")  # NaN != NaN

    def test_a_gs_bar_never_declares_both_a_yoy_line_and_an_average(self) -> None:
        """The renderer can only honour one of them, and picks `yoy` silently.

        `if (!yoyS && isNum(avg))` means an exhibit carrying both gets the
        secondary-axis y/y line and no average line, with the average quietly
        dropped -- and the file header says why the two are not drawn together:
        they answer the same question two ways and the reader cannot tell two
        horizontal references apart. An exhibit that declares both has a number
        in its payload that reaches no pixel, which is how a stale field
        survives a review.
        """
        for label, exhibit in exhibits():
            if exhibit.get("kind") != "gs_bar":
                continue
            self.assertFalse(
                exhibit.get("yoy") and "avg12" in exhibit,
                f"{label} declares both yoy and avg12",
            )

    def test_a_yoy_block_carries_at_least_one_finite_value(self) -> None:
        """An empty `yoy` suppresses the average line without replacing it.

        `rhsOf(ex)` is truthy for `{"values": []}`, so such an exhibit takes the
        y/y path, skips the average line, draws no polyline, and prints a legend
        entry for a series with no points.
        """
        for label, exhibit in exhibits():
            yoy = exhibit.get("yoy")
            if not yoy:
                continue
            values = yoy.get("values") or []
            self.assertTrue(
                any(isinstance(v, (int, float)) and not isinstance(v, bool)
                    and v == v for v in values),
                f"{label} yoy carries no finite value",
            )

    def test_the_gs_bar_census_this_file_was_written_against(self) -> None:
        """Pins the numbers quoted in the module docstring so they stay true.

        Not a constraint on the data -- an exhibit added or converted moves
        these and the right fix is to update them. It exists because the
        argument for the guards above rests on "the avg12 branch has never been
        exercised", and a comment asserting that would rot silently.
        """
        bars = [ex for _, ex in exhibits() if ex.get("kind") == "gs_bar"]
        self.assertEqual(len(bars), 27)
        self.assertEqual(sum(1 for ex in bars if ex.get("yoy")), 26)
        self.assertEqual(sum(1 for ex in bars if "avg12" in ex), 0)
        neither = [label for label, ex in exhibits()
                   if ex.get("kind") == "gs_bar" and not ex.get("yoy")
                   and "avg12" not in ex]
        self.assertEqual(neither, ["avgo Ex16"])


if __name__ == "__main__":
    unittest.main()
