"""The payload/renderer contract for exhibit fields, checked without a browser.

`tests/render_check.js` is the gate that actually looks at rendered SVG, and it
is the one that would have caught AVGO Exhibit 16. It needs node and jsdom, so
on a fresh clone it skips. This file is what runs unconditionally: pure stdlib,
no third-party dependency, and it pins the two halves of that defect that can be
checked from the source and the payloads alone.

The defect, for whoever reads this next. `assets/charts.js` draws the gs_bar
reference line from `ex.avg12` — a number the payload supplies and the engine
never computes — whenever `ex.yoy` is absent. Across the site 28 exhibits are
gs_bar, 27 carry `yoy`, and **none has ever carried `avg12`**, so that branch
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
CHECK_JS = ROOT / "tests" / "render_check.js"

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


class PayloadKeysAreReadTest(unittest.TestCase):
    """Every key a builder publishes is a key some consumer reads."""

    def test_no_exhibit_carries_a_key_no_consumer_reads(self) -> None:
        """A misspelled key is dead config that reads as live config.

        `build/bc.py` published `"rlab": "零售占比 %"` on two `stacked_dual`
        charts. The renderer's right-axis title is `ylab2` (documented at
        `charts.js:43`, drawn at 1029), so the label was silently dropped --
        and because the right margin is *also* sized from `ylab2`
        (`r: dual ? (ex.ylab2 ? 56 : 42)`), the axis was not merely unlabelled,
        it never reserved room for a label. Nothing failed: the payload guard
        accepts any finite value under any name, the chart drew, and the
        builder source said the axis was labelled.

        A second spelling, `rhs_label`, was doing the same thing on 18 charts
        across five pages -- nine times the first one, and found only because
        this check was written as a census rather than as a fix for `rlab`.
        Twenty right-axis titles in total were being discarded while twenty-three
        other pages spelled it `ylab2` and got theirs.

        Asserted as an exact set rather than a bare "is empty" so that adding a
        key the renderer genuinely reads through a computed path has to be
        recorded here with its reason, instead of the whole check being deleted
        the first time it is inconvenient.
        """
        consumers = "".join(
            (ROOT / "assets" / name).read_text(encoding="utf-8")
            for name in ("charts.js", "page.js")
        )
        unread = {}
        for label, exhibit in exhibits():
            for key in exhibit:
                if key not in consumers:
                    unread.setdefault(key, []).append(label)
        self.assertEqual(
            {key: sorted({name.split()[0] for name in where})
             for key, where in sorted(unread.items())},
            {},
            "these exhibit keys appear in no consumer -- either the renderer "
            "never reads them (a misspelling: check `ylab2`, `yfmt`, `ymax`) "
            "or they are read through a computed path and belong in this "
            "test's allowlist with the line that reads them",
        )


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

    def test_every_series_is_as_long_as_the_axis_it_is_plotted_against(self) -> None:
        """The renderer zips series to `xlabels` by index, so a short one shifts.

        `charts.js` walks `for (i = 0; i < n; i++)` with `n = xlabels.length`
        and reads `values[i]` / `yoy.values[i]` at that same `i`. Nothing
        compares the two lengths. A series one element short therefore does not
        fail, does not warn, and does not produce a NaN -- the missing index is
        `undefined`, every bar loop skips it as `v == null`, and `polyline()`
        drops it. The chart draws. Every point after the gap is simply read
        against the wrong period.

        That makes it invisible to every gate this repo has. `payload_guard`
        sees finite numbers. `build/all.py && git status` sees no drift,
        because the builder generates the short series consistently and the
        shell digest matches it. And `tests/render_check.js` sees no NaN,
        because there is none -- which is the difference from AVGO Ex16: the
        NaN at least left a mark in an attribute, and a shift leaves none.

        Verified by mutating a builder rather than a payload -- the distinction
        matters. Hand-editing `data/tsm.js` to drop one y/y point does go red,
        but on `test_shell_versions_every_script_by_content`, i.e. on the shell
        digest, not on the length; that is a false positive from editing a
        generated file. Injecting the same defect at its real source
        (`build/tsm.py`, `revenue_yoy_pct` -> `revenue_yoy_pct[1:]`, then
        `build/all.py`) passed all 725 tests and `render_check.js` clean.

        Asserted for `xlabels` as well as for `yoy`, since a short `values` is
        the same defect one layer down -- and it is not hypothetical: this
        assertion went red on its first run against `mco Ex9`, whose builder
        appends the five cumulative add-back steps but never the seventh bar
        the seventh label names, so the guidance bridge was published with its
        result column missing and `US$16.50` printed under `业务处置收益`.

        `tests/test_avgo_dashboard.py` checks the same widths for AVGO alone
        and stays -- that one is page-level and names the company first; this
        one is site-level and covers the other twenty-two. Site-wide that is
        27 `gs_bar` y/y lines, 27 `line` blocks, 43 range_band `lo`/`hi`/
        `actual` triples and every `groups` / `series` / `stacks` member, none
        of which had a length check anywhere before this.
        """
        for label, exhibit in exhibits():
            width = len(exhibit.get("xlabels") or [])
            self.assertGreater(width, 0, f"{label} has no xlabels")
            named = [("values", exhibit.get("values"))]
            # `lo` / `hi` / `actual` are bare lists on range_band, and `actual`
            # is a `{values: ...}` block on seasonality -- both are read as
            # `x[i]` against the same `i`, so both shapes belong here.
            # `net` is read at the same `i` as everything else (`bridgeNet`
            # returns a per-column list), but it was missing from this tuple
            # entirely, so no site-level check ever measured it: NKE Ex9's net
            # was unchecked outright, and CME Ex5's only by a page-level
            # assertion that required the broken bare-list shape.
            for key in ("yoy", "line", "base", "actual", "lo", "hi", "net"):
                block = exhibit.get(key)
                if isinstance(block, dict):
                    named.append((key, block.get("values")))
                elif isinstance(block, list):
                    named.append((key, block))
            for key in ("groups", "series", "stacks"):
                for block in exhibit.get(key) or []:
                    named.append((f"{key}:{block.get('name')}", block.get("values")))
            for name, values in named:
                if values is None:
                    continue
                self.assertEqual(
                    len(values), width,
                    f"{label} {name} has {len(values)} points for {width} xlabels",
                )

    def test_the_gs_bar_census_this_file_was_written_against(self) -> None:
        """Pins the numbers quoted in the module docstring so they stay true.

        Not a constraint on the data -- an exhibit added or converted moves
        these and the right fix is to update them. It exists because the
        argument for the guards above rests on "the avg12 branch has never been
        exercised", and a comment asserting that would rot silently.
        """
        bars = [ex for _, ex in exhibits() if ex.get("kind") == "gs_bar"]
        self.assertEqual(len(bars), 30)
        self.assertEqual(sum(1 for ex in bars if ex.get("yoy")), 29)
        self.assertEqual(sum(1 for ex in bars if "avg12" in ex), 0)
        neither = [label for label, ex in exhibits()
                   if ex.get("kind") == "gs_bar" and not ex.get("yoy")
                   and "avg12" not in ex]
        self.assertEqual(neither, ["avgo Ex16"])


class RenderGateRegexTest(unittest.TestCase):
    """The one line of `tests/render_check.js` that decides what the gate sees.

    `render_check.js` is the only check that looks at a rendered chart, and it
    decides every one of its verdicts with a single regex. Nothing that runs on
    a fresh clone reads that regex: `test_rendered_svg.py` only asserts the file
    exists, and the gate itself does not run until someone has done
    `npm --prefix tests install`.

    That asymmetry is the reason this class exists. Breaking the pattern in the
    obvious direction is loud -- widening it back to a plain substring match
    turns all 23 pages red, because `.../Financial-Information/...` in the SEC
    and IR links on every page contains `nan`. The dangerous edit is the
    opposite one, and it is the edit somebody reaches for *after* being shown
    those 23 false positives: tighten the pattern until `Financial` stops
    matching, land on something like `/^(NaN|Infinity|undefined)$/`, and the
    gate keeps passing while it quietly stops seeing `translate(NaN,3)` --
    which is the shape the AVGO Exhibit 16 defect actually had. On a machine
    without jsdom that weakening is invisible in every test, forever.

    So the behavioural assertions below run against the pattern **extracted
    from `render_check.js`**, never against a copy kept here -- a copy would be
    a test of itself, the shape CLAUDE.md warns about. The literal pin comes
    from the other direction: any edit at all to that line fails
    `test_the_gate_ships_the_regex_this_file_reasons_about`, which is a prompt
    to read this docstring before changing it, not a bug.
    """

    # Byte-for-byte what the `const BAD` declaration must read, flags included.
    # No `i` flag is load-bearing: `Financial` contains a lower-case `nan`, so a
    # case-insensitive variant of this pattern is red on every page.
    EXPECTED = "/(^|[^A-Za-z])(NaN|Infinity|undefined)([^A-Za-z]|$)/"

    # Values a browser drops or a reader sees. Every one is a shape the renderer
    # can actually emit: bare from `Y(undefined)`, embedded in a coordinate list
    # from `polyline`, inside `transform` from the rotated axis labels.
    DISCARDED = (
        "NaN", "81.2 NaN", "M0 NaN L4 2", "translate(NaN,3)",
        "rotate(-90 NaN 12)", "Infinity", "-Infinity", "undefined",
    )

    # Substring hits that must NOT match. The first two are not hypothetical:
    # they are in IR hostnames on the source lines of published pages, which is
    # what made the naive version unusable.
    ORDINARY = (
        "https://investor.spglobal.com/financial-information",
        "Financial Services", "S&P Global Market Intelligence",
        "NaNny", "Infinityx", "undefineds",
    )

    @staticmethod
    def shipped_literal() -> str:
        """The regex literal `render_check.js` ships, exactly as written."""
        source = CHECK_JS.read_text(encoding="utf-8")
        match = re.search(r"^const BAD = (/.*/[a-z]*);$", source, re.M)
        if match is None:
            raise AssertionError(
                "tests/render_check.js no longer declares `const BAD = /.../;` "
                "on one line; the render gate's scan pattern cannot be checked")
        return match.group(1)

    @classmethod
    def shipped_pattern(cls) -> "re.Pattern[str]":
        """The shipped literal compiled with `re`, so the cases test the real one.

        A JavaScript-only construct (a named group, a unicode property escape)
        raises here rather than passing quietly. That is the right outcome: this
        pattern has to stay expressible in both engines for the dependency-free
        half of the suite to be able to check it at all.
        """
        literal = cls.shipped_literal()
        body, _, flags = literal[1:].rpartition("/")
        if "i" in flags:
            raise AssertionError(
                f"the render gate's regex carries an `i` flag ({literal}); "
                "`Financial` contains `nan`, so that is red on every page")
        return re.compile(body)

    def test_the_gate_ships_the_regex_this_file_reasons_about(self) -> None:
        self.assertEqual(
            self.shipped_literal(), self.EXPECTED,
            "tests/render_check.js changed its scan pattern. Read this class's "
            "docstring, confirm the new one still rejects every value in "
            "DISCARDED and accepts every value in ORDINARY, then re-pin it here.")

    def test_it_matches_every_value_a_browser_would_discard(self) -> None:
        pattern = self.shipped_pattern()
        for value in self.DISCARDED:
            with self.subTest(value=value):
                self.assertRegex(value, pattern)

    def test_it_matches_no_ordinary_word_on_a_published_page(self) -> None:
        pattern = self.shipped_pattern()
        for value in self.ORDINARY:
            with self.subTest(value=value):
                self.assertNotRegex(value, pattern)

    def test_the_published_pages_contain_the_word_that_breaks_a_naive_scan(self) -> None:
        """Keeps the reason above from becoming folklore.

        The argument for the token boundary rests on `nan` really occurring
        inside published text. If that ever stopped being true the boundary
        would look like unmotivated complexity to the next reader, and this is
        where they would find out otherwise.
        """
        hits = [slug for slug, payload in payloads()
                if re.search(r"nan", json.dumps(payload, ensure_ascii=False))]
        self.assertTrue(
            hits,
            "no payload contains `nan` any more; re-read this class before "
            "simplifying the render gate's pattern")


class BridgeNetContractTest(unittest.TestCase):
    """`bridge_bar` reads its net from `ex.net.values`, not from `ex.net`.

    `bridgeNet` in `assets/charts.js` starts `if (ex.net && ex.net.values)`, and
    the legend reads `ex.net.name` beside it. A payload that supplies `net` as a
    bare list therefore satisfies the truthiness test, misses `.values`, and
    falls through to summing the stacks -- which is exactly the branch the
    object form exists to override. A waterfall's closing column carries no
    stack segment (its whole value *is* the net), so that column sums to null,
    `isNum(netv[i])` is false, and no diamond is drawn.

    Both `bridge_bar` exhibits on the site shipped that way. CME Exhibit 5 and
    NKE Exhibit 9 each rendered three bars under four x labels: the closing
    column had its label, its tooltip hit-area and nothing else, while the
    legend advertised a `Net change` series -- the default name, because
    `ex.net.name` was undefined too -- that appeared nowhere on the canvas. It
    is the MCO Exhibit 9 ending reached by a different road, and every existing
    check was green: the values are finite, the build is deterministic, the
    render gate finds no NaN and no empty card, and `len(values) == len(xlabels)`
    holds because the missing entry is a `None`, not a missing element.

    Three independent builders wrote the bare list -- CME and NKE months apart,
    and MU on a branch being written the day this gate was added, whose closing
    column renders empty under a title that promises `US$12.20 -> US$25.11`.
    That is the part worth reacting to: a contract three authors get wrong the
    same way is not being guarded by being documented. Both assertions below are
    derived from what the renderer reads, not from what the payloads happen to
    contain.
    """

    def bridges(self) -> list[tuple[str, dict]]:
        return [(label, ex) for label, ex in exhibits() if ex.get("kind") == "bridge_bar"]

    def test_the_site_still_has_a_bridge_to_check(self) -> None:
        """Both assertions below pass vacuously if the census goes to zero."""
        self.assertGreaterEqual(len(self.bridges()), 2, "bridge_bar exhibits")

    def test_every_bridge_net_is_the_shape_the_renderer_reads(self) -> None:
        wrong = []
        for label, ex in self.bridges():
            if "net" not in ex:
                continue  # legitimate: the engine then sums the stacks
            net = ex["net"]
            if not isinstance(net, dict) or not isinstance(net.get("values"), list):
                wrong.append(f"{label}: net is {type(net).__name__}, "
                             f"renderer reads net.values")
                continue
            if len(net["values"]) != len(ex.get("xlabels") or []):
                wrong.append(f"{label}: net.values has {len(net['values'])} entries "
                             f"for {len(ex.get('xlabels') or [])} x labels")
        self.assertEqual(wrong, [], "\n".join(wrong))

    def test_every_bridge_column_has_something_to_draw(self) -> None:
        """Each x label names a column; a column with neither a stack segment
        nor a net value draws a label over empty canvas."""
        blank = []
        for label, ex in self.bridges():
            xlabels = ex.get("xlabels") or []
            net = ex.get("net")
            netvals = net.get("values") if isinstance(net, dict) else (net if isinstance(net, list) else [])
            for i, name in enumerate(xlabels):
                legs = [st["values"][i] for st in ex.get("stacks", [])
                        if isinstance(st.get("values"), list) and i < len(st["values"])]
                drawn = [v for v in legs if isinstance(v, (int, float)) and v != 0]
                netv = netvals[i] if isinstance(netvals, list) and i < len(netvals) else None
                if not drawn and not isinstance(netv, (int, float)):
                    blank.append(f"{label} column {i} ({name!r}) has a label and nothing to draw")
        self.assertEqual(blank, [], "\n".join(blank))


class StackedDualRightAxisTest(unittest.TestCase):
    """`stacked_dual` is the only kind whose right axis ignores its own data.

    Every other dual kind runs `ticks(min(rv, 0), max(rv), 9)` -- computed from
    the values. `stacked_dual` runs `ticks(0, ex.line.ymax || 60, 6)`, so the
    ceiling is whatever a builder declared, or 60. Two ways that goes wrong, both
    of which have actually happened here:

      * the declaration is written at the exhibit's top level instead of inside
        `line`. `rhsOf(ex)` returns `ex.line`, so a top-level `ymax` is accepted
        and ignored -- no error, no warning, axis silently back to 60.
      * the declaration was right for a shorter window. `ibkr Ex8` declared 100
        when the chart drew eight quarters peaking at 77%; pulling it out to 42
        quarters brought in Q4'17 at 101.2% -- a quarter where the parent's own
        result was negative, so the minority share exceeds the whole -- and that
        point was drawn above the topmost gridline with no tick to read it
        against. Same shape as a stale hand-typed count: a constant that was
        true of the old window and was never re-derived.

    The renderer now takes `max(declared, peak)` so no point can fall outside the
    drawn range. These assertions cover what that cannot: that the declaration is
    somewhere it will actually be read, and that no page is quietly riding on the
    invisible default.
    """

    def _duals(self):
        return [(label, exhibit) for label, exhibit in exhibits()
                if exhibit.get("kind") == "stacked_dual"]

    def test_the_ceiling_is_declared_where_the_renderer_looks_for_it(self) -> None:
        stray = [label for label, exhibit in self._duals() if "ymax" in exhibit]
        self.assertEqual(stray, [], "`ymax` at the top level of a stacked_dual is "
                                    "read by nothing; it belongs inside `line`.")

    def test_no_stacked_dual_rides_on_the_invisible_default(self) -> None:
        """60 is a number no builder chose and no reader can see."""
        undeclared = [label for label, exhibit in self._duals()
                      if (exhibit.get("line") or {}).get("ymax") is None]
        self.assertEqual(undeclared, [],
                         "declare ex.line.ymax explicitly rather than inheriting 60")

    def test_the_renderer_lifts_a_ceiling_the_data_has_outgrown(self) -> None:
        """The guarantee the assertions above rest on, checked against the real
        renderer rather than assumed: a value over the declared ceiling still
        lands inside the drawn tick range."""
        source = (ROOT / "assets" / "charts.js").read_text(encoding="utf-8")
        # anchor on the declaration itself -- `kind === 'stacked_dual'` appears
        # several times in this file and the first one is the y-limit branch
        self.assertEqual(source.count("rc.ymax"), 1)
        block = source.split("rc.ymax", 1)[1][:600]
        self.assertIn("rcap", block)
        # the lift must scan every right-axis value, not just the last
        self.assertIn("ri < rv.length", block)
        self.assertIn("rv[ri] > rcap", block)
        self.assertIn("ticks(0, rcap, 6)", block)

    def test_every_declared_ceiling_is_a_round_number(self) -> None:
        """A ceiling derived from the data would defeat the point: the round
        number is what tells the reader the line is a share of something."""
        for label, exhibit in self._duals():
            ymax = (exhibit.get("line") or {}).get("ymax")
            # a missing ceiling is the test above's business, not this one's --
            # otherwise removing one turns two assertions red and neither says
            # what actually broke
            if ymax is None:
                continue
            with self.subTest(exhibit=label):
                self.assertEqual(ymax, int(ymax))
                self.assertEqual(int(ymax) % 10, 0, "not a round ceiling")


if __name__ == "__main__":
    unittest.main()
