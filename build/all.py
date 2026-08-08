#!/usr/bin/env python3
"""Build every reviewed company dashboard and the shared roster."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import googl, tsm  # noqa: E402
from build.payload_guard import write_js  # noqa: E402


DATA_DIR = ROOT / "data"


def roster_payload(googl_payload: dict, tsm_payload: dict) -> dict:
    """Return the deterministic two-company navigation payload."""
    return {
        "schema_version": "quarterly-roster/v1",
        "groups": [
            {"key": "internet", "label": "互联网平台", "order": 1},
            {"key": "semiconductor_ai", "label": "半导体与 AI 基础设施", "order": 2},
        ],
        "items": [
            {
                "slug": "googl",
                "ticker": "GOOGL",
                "name": "Alphabet",
                "aliases": ["Google", "谷歌"],
                "group": "internet",
                "latest_label": googl_payload["latest"]["disclosed_period_label"],
                "latest_full_label": googl_payload["latest"]["full_financial_period_label"],
                "release_date": googl_payload["latest"]["release_date"],
                "status": googl_payload["latest"]["status"],
                "cadence_label": "自然年季度；完整披露",
                "headline_metrics": ["Revenue $119.8B", "Cloud +81.8%", "FCF -$5.9B"],
                "search_text": "googl google alphabet 谷歌 互联网 cloud search youtube",
            },
            {
                "slug": "tsm",
                "ticker": "TSM",
                "name": "TSMC",
                "aliases": ["台积电", "Taiwan Semiconductor"],
                "group": "semiconductor_ai",
                "latest_label": tsm_payload["latest"]["disclosed_period_label"],
                "latest_full_label": tsm_payload["latest"]["full_financial_period_label"],
                "release_date": tsm_payload["latest"]["release_date"],
                "status": tsm_payload["latest"]["status"],
                "cadence_label": "自然年季度；完整披露",
                "headline_metrics": ["Revenue $40.2B", "HPC 66%", "GM 67.7%"],
                "search_text": "tsm tsmc taiwan semiconductor 台积电 半导体 foundry hpc ai 2nm",
            },
        ],
        "footer": "Quarterly Results · 公司披露值与透明自算 · 仅供研究",
    }


def write_roster(payload: dict) -> None:
    write_js(DATA_DIR / "roster.js", "ROSTER", payload, "all")


def main() -> int:
    googl.main()
    tsm.main()
    googl_source = json.loads(googl.STAGING_PATH.read_text(encoding="utf-8"))
    tsm_source = json.loads(tsm.STAGING_PATH.read_text(encoding="utf-8"))
    roster = roster_payload(googl.build_payload(googl_source), tsm.build_payload(tsm_source))
    write_roster(roster)
    print("Quarterly Results: 2 reviewed companies + shared roster")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
