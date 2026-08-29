"""What `_BAD_TEXT` must reject, and what it must leave alone.

The guard scans every string in a payload for a non-finite value that was
formatted into text before it got there -- a `nan` that reached `str()` is no
longer a float, so the `math.isfinite` arm never sees it.

The pattern's tail is the delicate part. It is not "any one or two letters"; it
is the set of unit suffixes `UNIT_FORMATS` appends (`pp`, `bp`, `M`, `B`, `x`),
because those are what a formatted non-finite value actually looks like here --
`nanM`, `nanx`, `infpp`. Written as `[A-Za-z]{1,2}` instead it also rejects
every ordinary word that happens to be `nan` or `inf` plus a letter or two, and
this corpus is full of them: **NAND** on all three memory-maker pages, the
competitor **Nanya**, and `nano`, `info`, `infra`. A gate that false-fails on
the industry's own vocabulary gets bypassed with `--no-verify`, and then it
protects nothing -- so the tail was narrowed to the suffixes and this file
exists to keep the narrowing honest in both directions.

`test_every_formatter_output_for_a_non_finite_value_is_rejected` is the half
that makes the narrowing safe to keep. It does not hardcode the suffixes: it
asks `UNIT_FORMATS` itself what it prints. A formatter added later with a
suffix the pattern does not know -- a `krw_tn` rendering trillions as `1.2T`,
say -- turns this file red on the day it lands, instead of silently opening a
hole that only shows up as a chart with `NaNT` painted on it.
"""

from __future__ import annotations

import json
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build.board import UNIT_FORMATS, unit_text  # noqa: E402
from build.payload_guard import PayloadGuardError, check  # noqa: E402

NON_FINITE = (float("nan"), float("inf"), float("-inf"))


def rejects(text: str) -> bool:
    """Whether the guard refuses a payload carrying `text` as a string value."""
    try:
        check({"exhibits": [{"note": text}]})
    except PayloadGuardError:
        return True
    return False


class FormattedNonFiniteTest(unittest.TestCase):
    def test_every_formatter_output_for_a_non_finite_value_is_rejected(self) -> None:
        """Ask `UNIT_FORMATS` what it prints; every answer must be refused.

        This is what licenses the narrow tail. The suffix set in the pattern is
        a literal, but it is never compared against another literal -- it is
        exercised against the real formatters, so the two cannot drift apart
        without this failing.
        """
        escaped = []
        for unit in sorted(UNIT_FORMATS):
            for value in NON_FINITE:
                try:
                    text = unit_text(unit, value)
                except (ValueError, OverflowError):
                    continue  # a formatter that refuses outright is also safe
                if not rejects(text):
                    escaped.append(f"{unit}({value}) -> {text!r}")
        self.assertEqual(escaped, [], "\n".join(escaped))

    def test_the_bare_reprs_are_rejected(self) -> None:
        spellings = []
        for value in NON_FINITE:
            spellings += [str(value), repr(value), f"{value}", f"{value:.1f}",
                          f"{value:,.2f}", f"{value:.1%}", json.dumps(value)]
        spellings += ["NaN", "Infinity", "-Infinity", "nan%", "$NaN", "NaN 亿美元",
                      "translate(NaN,3)", "NaN×"]
        escaped = [s for s in spellings if not rejects(s)]
        self.assertEqual(escaped, [], "\n".join(escaped))

    def test_a_non_finite_float_is_still_rejected(self) -> None:
        """The float arm is independent of the text pattern; pin it separately."""
        for value in NON_FINITE:
            with self.subTest(value=value):
                with self.assertRaises(PayloadGuardError):
                    check({"exhibits": [{"values": [1.0, value]}]})
        self.assertTrue(all(not math.isfinite(v) for v in NON_FINITE))


class OrdinaryVocabularyTest(unittest.TestCase):
    def test_the_words_these_pages_have_to_use_are_not_rejected(self) -> None:
        """The false positives that forced the narrowing, kept as a red line.

        Every entry here is a word a memory-maker page cannot write around.
        `NAND` is a reporting segment in Micron's 10-K and in the Samsung and
        SK hynix quarterly releases; Nanya is a DRAM competitor. Under the old
        `[A-Za-z]{1,2}` tail each of these failed the build with
        "suspicious formatted value" -- a message pointing at arithmetic for a
        defect that was entirely in the prose.
        """
        allowed = [
            "NAND", "nand", "NAND 闪存", "DRAM 与 NAND", "DRAM/NAND", "非 NAND",
            "(NAND)", "NAND flash", "Nanya", "Nanya Technology", "南亞科 Nanya",
            "nano", "info", "infra", "information", "nanometer", "financial",
            "Infineon", "Inotera",
            "https://ir.skhynix.com/info/",
            "https://www.micron.com/about/our-commitment/nand",
        ]
        rejected = [w for w in allowed if rejects(w)]
        self.assertEqual(rejected, [], "\n".join(rejected))

    def test_the_check_is_capable_of_rejecting(self) -> None:
        """Pin the detector, not the tree.

        Every assertion above that ends in "is not rejected" passes if `check`
        stopped rejecting anything at all, so on its own the class cannot tell
        "no false positives" from "no detection".
        """
        self.assertTrue(rejects("NaN"))
        self.assertFalse(rejects("DRAM"))


if __name__ == "__main__":
    unittest.main()
