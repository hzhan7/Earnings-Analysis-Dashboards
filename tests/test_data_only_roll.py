"""A quarter roll edits `series/<slug>.json` and nothing else.

The owner's rule of 2026-09-19: rolling a page to a new quarter is a data edit.
Four layers used to need hand edits beside the series -- the builder's `latest`
block and its prose, `build/all.py`'s card figures, the home page's cards and
counts, the README's fiscal-year paragraph -- and none of them had a gate. This
file pins the shared half of the fix, for every page:

* every builder gets its `latest` block from the series (`board.latest_block`),
  and that block refuses to build when the series file's own `latest` stamp is
  a quarter behind its arrays -- so a roll cannot ship last quarter's review
  date on this quarter's page;
* every builder computes its home-page card figures from the series
  (`headline_metrics`), so `build/all.py` types none;
* the home page's cards and counts are exactly what `build/home.py` writes from
  the roster and the payloads, so a stale card cannot survive a build.
"""

from __future__ import annotations

import copy
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.all import ENTRIES, MODULES, build_all, roster_payload  # noqa: E402
from build.home import HOME, render_home  # noqa: E402


def staging_of(slug: str) -> dict:
    return json.loads(MODULES[slug].STAGING_PATH.read_text(encoding="utf-8"))


class SharedLayerTest(unittest.TestCase):
    def test_every_builder_refuses_a_series_whose_latest_stamp_is_stale(self) -> None:
        """Tamper the stamp and nothing else: the build must stop, and say why.

        A builder that still typed its own `latest` block would build happily
        here, which is exactly the rot this replaces.
        """
        for slug in MODULES:
            staging = staging_of(slug)
            meta = staging["latest"]
            stamps = [key for key in ("period", "disclosed_period_label", "period_label")
                      if key in meta]
            self.assertTrue(stamps, f"{slug}: series `latest` block carries no period stamp")
            stale = copy.deepcopy(staging)
            for key in stamps:
                stale["latest"][key] = "Q1 1999"
            with self.subTest(slug=slug):
                with self.assertRaisesRegex(ValueError, "stamped"):
                    MODULES[slug].build_payload(stale)

    def test_the_latest_block_carries_what_no_filing_does_from_the_series_file(self) -> None:
        for slug in MODULES:
            staging = staging_of(slug)
            latest = MODULES[slug].build_payload(staging)["latest"]
            with self.subTest(slug=slug):
                self.assertEqual(latest["analysis_date"], staging["latest"]["analysis_date"])
                self.assertEqual(latest["audit_status"], staging["latest"]["audit_status"])

    def test_every_card_figure_is_computed_by_its_builder(self) -> None:
        roster = roster_payload(build_all())
        for entry, item in zip(ENTRIES, roster["items"]):
            slug = entry["slug"]
            with self.subTest(slug=slug):
                self.assertNotIn("headline_metrics", entry,
                                 "card figures are computed, not typed into ENTRIES")
                figures = MODULES[slug].headline_metrics(staging_of(slug))
                self.assertEqual(item["headline_metrics"], figures)
                self.assertEqual(len(figures), 3)
                self.assertTrue(all(isinstance(text, str) and text for text in figures))

    def test_the_home_page_is_what_the_generator_writes(self) -> None:
        """Rendering the committed page again must change nothing."""
        payloads = build_all()
        roster = roster_payload(payloads)
        text = HOME.read_text(encoding="utf-8")
        self.assertEqual(render_home(text, roster, payloads), text,
                         "index.html is stale: run build/all.py")

    def test_the_home_page_card_names_the_payload_period(self) -> None:
        """The NVIDIA card sat a quarter behind its own page while every test
        passed, because another card happened to carry the same date string.
        Each card is now checked against its own payload, inside its own anchor.
        """
        home = HOME.read_text(encoding="utf-8")
        payloads = build_all()
        for entry in ENTRIES:
            slug = entry["slug"]
            card = home.split(f'<a class="hcard" href="{slug}/">', 1)[1].split("</a>", 1)[0]
            latest = payloads[slug]["latest"]
            with self.subTest(slug=slug):
                self.assertIn(f"发布 {latest['release_date']}", card)
                self.assertIn(latest["disclosed_period_label"], card)


def checked_slugs() -> list[str]:
    """Pages migrated to the data-only roll: their series carries `_checks`."""
    return [slug for slug in MODULES if "_checks" in staging_of(slug)]


class ChecksBlockTest(unittest.TestCase):
    """What every migrated page's `_checks` block has to be.

    The block is a separate reading of the quarter's primary filing -- period,
    dates, a handful of headline figures and where in the document each was
    read -- keyed once per roll. Company tests assert the builder's output
    against it. Two things make it evidence rather than a snapshot, and both
    are asserted here for every page that has one: it names its source, and
    the builder never reads it (a check the builder could see would be the
    builder checking itself).
    """

    def test_there_is_at_least_one_migrated_page(self) -> None:
        self.assertTrue(checked_slugs(), "no series file carries `_checks` yet")

    def test_the_checks_name_the_quarter_the_page_publishes(self) -> None:
        for slug in checked_slugs():
            staging = staging_of(slug)
            checks = staging["_checks"]
            latest = MODULES[slug].build_payload(staging)["latest"]
            with self.subTest(slug=slug):
                self.assertEqual(latest["disclosed_period_label"], checks["period"])
                self.assertEqual(latest["period_end"], checks["period_end"])
                self.assertEqual(latest["release_date"], checks["release_date"])
                self.assertTrue(checks.get("source"), "a check without a source is a snapshot")

    def test_no_builder_reads_its_checks(self) -> None:
        for slug in checked_slugs():
            staging = staging_of(slug)
            stripped = {key: value for key, value in staging.items() if key != "_checks"}
            with self.subTest(slug=slug):
                self.assertEqual(MODULES[slug].build_payload(stripped),
                                 MODULES[slug].build_payload(staging))


class ExhibitReferenceTest(unittest.TestCase):
    """A sentence that names an exhibit by number must name the right one.

    Five pages say "Exhibit A 与 Exhibit B 的阈值是本地研究设定" in their notes.
    The numbers used to be typed, or computed by adding up list lengths, and two
    of the five had drifted: CDNS named the follow-up chart instead of the
    prior thresholds, GOOGL a highlights chart instead of the next ones. Both
    numbers are now read from the charts after numbering; this pins that each
    one lands on a thresholds chart, on every page that says it.
    """

    def test_threshold_references_land_on_threshold_charts(self) -> None:
        pattern = re.compile(r"Exhibit (\d+) 与 Exhibit (\d+) 的阈值")
        seen = 0
        for slug, payload in sorted(build_all().items()):
            exhibits = {ex["n"]: ex for section in payload["sections"]
                        for ex in section["exhibits"]}
            for note in payload["notes"]:
                for match in pattern.finditer(note):
                    prior, following = (exhibits[int(match.group(1))], exhibits[int(match.group(2))])
                    with self.subTest(slug=slug):
                        self.assertEqual(prior["kind"], "diverging_bars")
                        self.assertTrue(prior["title"].startswith("上季") and "阈值" in prior["title"])
                        self.assertEqual(following["kind"], "diverging_bars")
                        self.assertTrue(following["title"].startswith("下季") and "阈值" in following["title"])
                    seen += 1
        self.assertGreaterEqual(seen, 5)


if __name__ == "__main__":
    unittest.main()
