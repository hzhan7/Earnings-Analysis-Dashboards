#!/usr/bin/env python3
"""Build every reviewed company dashboard and the shared roster."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import amzn, cdns, googl, ibkr, ma, meta, msft, nvda, schw, snps, tsm, v  # noqa: E402
from build.payload_guard import write_js  # noqa: E402


DATA_DIR = ROOT / "data"

MODULES = {
    "amzn": amzn,
    "cdns": cdns,
    "googl": googl,
    "ibkr": ibkr,
    "ma": ma,
    "meta": meta,
    "msft": msft,
    "nvda": nvda,
    "schw": schw,
    "snps": snps,
    "tsm": tsm,
    "v": v,
}

GROUPS = [
    {"key": "internet", "label": "互联网平台", "order": 1},
    {"key": "software_cloud", "label": "软件与云平台", "order": 2},
    {"key": "semiconductor_ai", "label": "半导体与 AI 基础设施", "order": 3},
    {"key": "payment_networks", "label": "支付网络", "order": 5},
    {"key": "brokerage_wealth", "label": "券商与财富管理", "order": 6},
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
        "slug": "ibkr",
        "ticker": "IBKR",
        "name": "Interactive Brokers Group",
        "aliases": ["Interactive Brokers", "盈透证券", "IB"],
        "group": "brokerage_wealth",
        "cadence_label": "自然年季度；完整披露",
        "headline_metrics": ["Revenue $1.90B", "NIM 1.93%", "账户 5.19M"],
        "search_text": ("ibkr interactive brokers 盈透证券 券商 经纪 交易 保证金 "
                        "净息差 nim 客户权益 darts 期权 期货 清算 托管 up-c"),
    },
    {
        "slug": "ma",
        "ticker": "MA",
        "name": "Mastercard",
        "aliases": ["Mastercard", "万事达", "支付网络"],
        "group": "payment_networks",
        "cadence_label": "自然年季度；完整披露",
        "headline_metrics": ["Revenue $9.28B", "Rebate ratio 52.4%", "VAS share 41.2%"],
        "search_text": "ma mastercard 万事达 支付 网络 跨境 清算 返点 激励 增值服务 vas 发卡行 收单 稳定币",
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
        "slug": "schw",
        "ticker": "SCHW",
        "name": "Charles Schwab",
        "aliases": ["嘉信理财", "Schwab"],
        "group": "brokerage_wealth",
        "cadence_label": "自然年季度；完整披露",
        "headline_metrics": ["Revenue $7.07B", "NIM 3.00%", "DATs 11.9M"],
        "search_text": "schw schwab 嘉信 嘉信理财 券商 经纪 财富管理 银行 净利息收入 nim sweep 现金 交易 nna 客户资产",
    },
    {
        "slug": "snps",
        "ticker": "SNPS",
        "name": "Synopsys",
        "aliases": ["新思科技", "Ansys"],
        "group": "semiconductor_ai",
        "cadence_label": "10 月制财年；本站按自然年季度标注",
        "headline_metrics": ["Revenue $2.48B", "Design IP +10.8%", "Non-GAAP OpM 41.6%"],
        "search_text": "snps synopsys 新思科技 eda 半导体 设计 ip ansys 仿真 芯片设计 backlog agentic",
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
    {
        "slug": "v",
        "ticker": "V",
        "name": "Visa",
        "aliases": ["Visa", "维萨", "签证卡"],
        "group": "payment_networks",
        "cadence_label": "9 月制财年；本站按自然年季度标注",
        "headline_metrics": ["Net revenue $11.6B", "激励率 28.7%", "GAAP OpM 59.1%"],
        "search_text": "v visa 维萨 支付 卡组织 网络 跨境 client incentives 激励 借记卡 信用卡 发卡行 收单",
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
