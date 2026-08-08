from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.googl import build_payload, parse_number  # noqa: E402


class GooglePrototypeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        staging = json.loads((ROOT / "series" / "googl.json").read_text(encoding="utf-8"))
        cls.payload = build_payload(staging)

    def test_currency_sign_parsing(self) -> None:
        self.assertEqual(parse_number("-$5,855M"), -5855)
        self.assertEqual(parse_number("($5,855M)"), -5855)
        self.assertEqual(parse_number("$5,855M"), 5855)

    def test_expected_exhibit_order(self) -> None:
        exhibits = [ex for section in self.payload["sections"] for ex in section["exhibits"]]
        self.assertEqual([ex["n"] for ex in exhibits], [2, 3, 4, 5, 6, 7, 8, 9])
        self.assertTrue(all(not ex.get("full", False) for ex in exhibits))
        fcf = next(ex for ex in exhibits if ex["n"] == 7)
        self.assertEqual(fcf["values"][-1], -5855)

    def test_source_truth_corrections(self) -> None:
        staging = json.loads((ROOT / "series" / "googl.json").read_text(encoding="utf-8"))
        rows = {row[0]: row for row in staging["snapshot"]["rows"]}
        self.assertEqual(rows["TTM 自由现金流"][1], "$66,728M")
        self.assertIn("EPS（剔权益证券收益，简单自算）", rows)

    def test_published_payload_matches_builder(self) -> None:
        text = (ROOT / "data" / "googl.js").read_text(encoding="utf-8")
        body = text.split("window.DASH = ", 1)[1].rsplit(";", 1)[0]
        self.assertEqual(json.loads(body), self.payload)
        labels = {item["label"] for item in self.payload["source_links"]}
        self.assertIn("Q2 2026 Alphabet earnings call webcast", labels)

    def test_public_payload_excludes_restricted_material(self) -> None:
        text = json.dumps(self.payload, ensure_ascii=False).lower()
        for forbidden in [
            "谨慎多", "alphastreet", "yahoo finance", "bofa", "anthropic",
            "stockanalysis.com", "onedrive/",
        ]:
            self.assertNotIn(forbidden, text)
        self.assertNotIn("/users/", text)
        self.assertNotIn("/library/cloudstorage/", text)
        self.assertNotIn("$73,552m", text)
        self.assertNotIn("经营口径 eps", text)

    def test_derived_rows_are_marked(self) -> None:
        rows = self.payload["summary"]["blocks"][0]["rows"]
        derived = {row["label"] for row in rows if row["cells"][0]["status"] == "derived"}
        self.assertEqual(
            derived,
            {"Cloud OPM", "经营利润率", "EPS（剔权益证券收益，简单自算）"},
        )
        for row in rows:
            for cell in row["cells"][3:]:
                if cell["v"] != "—":
                    self.assertEqual(cell["status"], "derived")


if __name__ == "__main__":
    unittest.main()
