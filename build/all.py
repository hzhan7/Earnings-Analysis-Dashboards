#!/usr/bin/env python3
"""Build every reviewed company dashboard and the shared roster."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import amzn, cdns, googl, meta, msft, nvda, tsm  # noqa: E402
from build.payload_guard import write_js  # noqa: E402


DATA_DIR = ROOT / "data"

MODULES = {
    "amzn": amzn,
    "cdns": cdns,
    "googl": googl,
    "meta": meta,
    "msft": msft,
    "nvda": nvda,
    "tsm": tsm,
}

GROUPS = [
    {"key": "internet", "label": "互联网平台", "order": 1},
    {"key": "software_cloud", "label": "软件与云平台", "order": 2},
    {"key": "semiconductor_ai", "label": "半导体与 AI 基础设施", "order": 3},
]

# Everything here is navigation copy, not analysis: it is what a reader sees
# before choosing a page, so it must be short and it must not drift from the
# payload. The three fields that can go stale on their own -- period label,
# release date, status -- are read from the payload instead of typed here.
ENTRIES = [
    {
        "slug": "amzn",
        "ticker": "AMZN",
        "name": "Amazon.com",
        "aliases": ["Amazon", "亚马逊", "AWS"],
        "group": "internet",
        "cadence_label": "自然年季度；完整披露",
        "headline_metrics": ["Revenue $200.6B", "AWS +37%", "TTM FCF -$7.6B"],
        "search_text": "amzn amazon 亚马逊 aws 云 电商 零售 广告 互联网 trainium prime",
    },
    {
        "slug": "cdns",
        "ticker": "CDNS",
        "name": "Cadence Design Systems",
        "aliases": ["Cadence", "楷登", "EDA"],
        "group": "semiconductor_ai",
        "cadence_label": "自然年季度；完整披露",
        "headline_metrics": ["Revenue $1.58B", "Backlog $8.1B", "Non-GAAP OpM 45.5%"],
        "search_text": "cdns cadence 楷登 eda 半导体 设计 ip palladium 硬件仿真 agentic 芯片设计",
    },
    {
        "slug": "googl",
        "ticker": "GOOGL",
        "name": "Alphabet",
        "aliases": ["Google", "谷歌"],
        "group": "internet",
        "cadence_label": "自然年季度；完整披露",
        "headline_metrics": ["Revenue $119.8B", "Cloud +81.8%", "FCF -$5.9B"],
        "search_text": "googl google alphabet 谷歌 互联网 cloud search youtube",
    },
    {
        "slug": "meta",
        "ticker": "META",
        "name": "Meta Platforms",
        "aliases": ["Facebook", "脸书", "元宇宙"],
        "group": "internet",
        "cadence_label": "自然年季度；完整披露",
        "headline_metrics": ["Revenue $60.8B", "Ads +27.5%", "FCF $0.8B"],
        "search_text": "meta facebook instagram whatsapp 脸书 广告 reality labs 互联网",
    },
    {
        "slug": "msft",
        "ticker": "MSFT",
        "name": "Microsoft",
        "aliases": ["微软", "Azure"],
        "group": "software_cloud",
        "cadence_label": "6 月制财年；本站按自然年季度标注",
        "headline_metrics": ["Revenue $90.0B", "Azure +43%", "FCF $19.6B"],
        "search_text": "msft microsoft 微软 azure copilot m365 云 软件",
    },
    {
        "slug": "nvda",
        "ticker": "NVDA",
        "name": "NVIDIA",
        "aliases": ["英伟达", "Nvidia"],
        "group": "semiconductor_ai",
        "cadence_label": "1 月制财年；本站按自然年季度标注",
        "headline_metrics": ["Revenue $81.6B", "Data Center +92%", "GM 75.0%"],
        "search_text": "nvda nvidia 英伟达 半导体 gpu ai 数据中心 hyperscale acie networking blackwell rubin",
    },
    {
        "slug": "tsm",
        "ticker": "TSM",
        "name": "TSMC",
        "aliases": ["台积电", "Taiwan Semiconductor"],
        "group": "semiconductor_ai",
        "cadence_label": "自然年季度；完整披露",
        "headline_metrics": ["Revenue $40.2B", "HPC 66%", "GM 67.7%"],
        "search_text": "tsm tsmc taiwan semiconductor 台积电 半导体 foundry hpc ai 2nm",
    },
]


def roster_payload(payloads: dict) -> dict:
    """Return the deterministic cross-company navigation payload.

    ``payloads`` maps slug to that company's built dashboard payload, so a page
    whose latest quarter moved cannot leave a stale label in the nav.
    """
    items = []
    for entry in ENTRIES:
        latest = payloads[entry["slug"]]["latest"]
        items.append({
            **entry,
            "latest_label": latest["disclosed_period_label"],
            "latest_full_label": latest["full_financial_period_label"],
            "release_date": latest["release_date"],
            "status": latest["status"],
        })
    return {
        "schema_version": "quarterly-roster/v1",
        "groups": GROUPS,
        "items": items,
        "footer": "Quarterly Results · 公司披露值与透明自算 · 仅供研究",
    }


def write_roster(payload: dict) -> None:
    write_js(DATA_DIR / "roster.js", "ROSTER", payload, "all")


def build_all() -> dict:
    """Return every company payload, built from its reviewed source series."""
    payloads = {}
    for slug, module in MODULES.items():
        source = json.loads(module.STAGING_PATH.read_text(encoding="utf-8"))
        payloads[slug] = module.build_payload(source)
    return payloads


def main() -> int:
    # Roster first: each page's shell stamps the content hash of every script it
    # loads, roster.js included, so the roster has to be final before the shells
    # are rendered or they would carry the previous build's digest for it.
    write_roster(roster_payload(build_all()))
    for module in MODULES.values():
        module.main()
    print(f"Quarterly Results: {len(MODULES)} reviewed companies + shared roster")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
