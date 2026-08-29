#!/usr/bin/env python3
"""Build every reviewed company dashboard and the shared roster."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import (  # noqa: E402
    amzn, avgo, axp, cboe, cdns, cme, cost, googl, ibkr, ma, mco, meta, msci,
    msft, mu, ndaq, nke, nvda, pm, race, samsung, schw, skhynix, snps,
    spgi, tjx, tsm, v,
)
from build.payload_guard import write_js  # noqa: E402


DATA_DIR = ROOT / "data"

MODULES = {
    "amzn": amzn,
    "avgo": avgo,
    "axp": axp,
    "cboe": cboe,
    "cdns": cdns,
    "cme": cme,
    "cost": cost,
    "googl": googl,
    "ibkr": ibkr,
    "ma": ma,
    "mco": mco,
    "meta": meta,
    "msci": msci,
    "msft": msft,
    "mu": mu,
    "ndaq": ndaq,
    "nke": nke,
    "nvda": nvda,
    "pm": pm,
    "race": race,
    "samsung": samsung,
    "schw": schw,
    "skhynix": skhynix,
    "snps": snps,
    "spgi": spgi,
    "tjx": tjx,
    "tsm": tsm,
    "v": v,
}

GROUPS = [
    {"key": "internet", "label": "互联网平台", "order": 1},
    {"key": "software_cloud", "label": "软件与云平台", "order": 2},
    {"key": "semiconductor_ai", "label": "半导体与 AI 基础设施", "order": 3},
    {"key": "financial_data_indices", "label": "金融数据、评级与指数", "order": 4},
    {"key": "payment_networks", "label": "支付网络", "order": 5},
    {"key": "brokerage_wealth", "label": "券商与财富管理", "order": 6},
    {"key": "consumer_retail", "label": "消费零售", "order": 7},
    {"key": "consumer_staples", "label": "消费必需品与烟草", "order": 8},
    {"key": "luxury_brands", "label": "奢侈品与豪华汽车", "order": 9},
    {"key": "exchanges", "label": "交易所", "order": 10},
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
        "slug": "avgo",
        "ticker": "AVGO",
        "name": "Broadcom",
        "aliases": ["Broadcom", "博通", "VMware"],
        "group": "semiconductor_ai",
        "cadence_label": "11 月制财年；本站按自然年季度标注",
        "headline_metrics": ["Revenue $22.19B", "AI 半导体 $10.8B", "EBITDA 利润率 68.7%"],
        "search_text": "avgo broadcom 博通 半导体 ai xpu 定制加速器 asic networking 以太网 tomahawk jericho vmware 基础设施软件 vcf",
    },
    {
        "slug": "axp",
        "ticker": "AXP",
        "name": "American Express Company",
        "aliases": ["American Express", "美国运通", "运通"],
        "group": "payment_networks",
        "cadence_label": "自然年季度；全年指引逐季修订",
        "headline_metrics": ["Revenue $19.6B", "净卡费 +15.4%", "VCE 占收入 44.6%"],
        "search_text": ("axp american express 美国运通 运通 支付 卡组织 发卡行 高端 platinum 白金卡 "
                        "年费 卡费 折扣率 商户 消费额 billed business 拨备 准备金 信用卡 cet1"),
    },
    {
        "slug": "cboe",
        "ticker": "CBOE",
        "name": "Cboe Global Markets, Inc.",
        "aliases": ["Cboe", "芝加哥期权交易所", "VIX", "SPX"],
        "group": "exchanges",
        "cadence_label": "自然年季度；全年指引逐季修订",
        "headline_metrics": ["Net revenue $731.6M", "Multi-listed RPC $0.064", "调整后 OpM 70.4%"],
        "search_text": ("cboe 芝加哥期权交易所 交易所 期权 指数期权 spx vix 0dte 波动率 "
                        "multi-listed 做市返点 市占率 每合约收入 rpc adv 日均成交量 "
                        "data vantage 市场数据 期货 外汇 场外大宗 ats section 31 规费 事件合约"),
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
        "slug": "cme",
        "ticker": "CME",
        "name": "CME Group Inc.",
        "aliases": ["CME Group", "芝商所", "芝加哥商品交易所"],
        "group": "exchanges",
        "cadence_label": "自然年季度；申报文件只指引资本开支",
        "headline_metrics": ["Revenue $1.71B", "清算费同比 −2.6%", "调整后 OpM 69.5%"],
        "search_text": ("cme cme group 芝商所 芝加哥商品交易所 交易所 衍生品 期货 期权 清算 "
                        "adv 成交量 rpc 每手费率 分级费率 利率期货 股指期货 国债 "
                        "brokertec ebs 抵押品 保证金 行情数据 未平仓合约"),
    },
    {
        "slug": "cost",
        "ticker": "COST",
        "name": "Costco Wholesale",
        "aliases": ["Costco", "好市多", "开市客", "仓储会员店"],
        "group": "consumer_retail",
        "cadence_label": "8 月底制财年；本站按自然年季度标注",
        "headline_metrics": ["Revenue $70.5B", "调整后 comp +6.6%", "会员费/营业利润 51%"],
        "search_text": ("cost costco 好市多 开市客 仓储会员店 零售 会员费 续费率 executive "
                        "同店销售 comp 汽油 加油站 自有品牌 kirkland 药房 电商 仓库 山姆"),
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
        "slug": "mco",
        "ticker": "MCO",
        "name": "Moody's Corporation",
        "aliases": ["Moody's", "穆迪", "评级"],
        "group": "financial_data_indices",
        "cadence_label": "自然年季度；全年指引逐季修订",
        "headline_metrics": ["Revenue $2.19B", "MIS adj OpM 68.3%", "调整后 EPS $4.68"],
        "search_text": ("mco moodys 穆迪 评级 信用评级 mis ma 债券 发行量 issuance "
                        "arr 订阅 金融数据 指数 全年指引"),
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
        "slug": "msci",
        "ticker": "MSCI",
        "name": "MSCI Inc.",
        "aliases": ["MSCI", "明晟", "指数"],
        "group": "financial_data_indices",
        "cadence_label": "自然年季度；完整披露",
        "headline_metrics": ["Revenue $867M", "ETF AUM $2,818B", "Adj EBITDA 62.1%"],
        "search_text": ("msci 明晟 指数 index analytics 分析 可持续 sustainability climate "
                        "私募资产 private assets etf aum 基点费率 run rate 留存率 订阅 资产型费用"),
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
        "slug": "mu",
        "ticker": "MU",
        "name": "Micron Technology, Inc.",
        "aliases": ["Micron", "美光", "内存", "存储器"],
        "group": "semiconductor_ai",
        "cadence_label": "财年末为最接近 8 月 31 日的星期四；本站按自然年季度标注",
        "headline_metrics": ["Revenue $41.46B", "non-GAAP GM 84.9%", "\u9500\u8d27\u6210\u672c\u73af\u6bd4 +4.8%"],
        "search_text": ("mu micron 美光 内存 存储器 半导体 dram nand hbm 闪存 "
                        "颗粒 位元 售价 asp 周期 涨价 数据中心 服务器 ssd "
                        "供货协议 sca take-or-pay 资本开支 晶圆厂"),
    },
    {
        "slug": "ndaq",
        "ticker": "NDAQ",
        "name": "Nasdaq, Inc.",
        "aliases": ["Nasdaq", "纳斯达克", "交易所"],
        "group": "financial_data_indices",
        "cadence_label": "自然年季度；仅指引费用与税率",
        "headline_metrics": ["Net revenue $1.50B", "ETP AUM $1,114B", "Non-GAAP OpM 57.3%"],
        "search_text": ("ndaq nasdaq 纳斯达克 交易所 上市 listing 指数 index etp aum "
                        "金融科技 fintech verafin adenza calypso axiomsl 反金融犯罪 "
                        "监管科技 arr 订阅 做市返点 section 31 规费 市占率"),
    },
    {
        "slug": "nke",
        "ticker": "NKE",
        "name": "NIKE, Inc.",
        "aliases": ["Nike", "耐克", "Jordan", "Converse"],
        "group": "consumer_retail",
        "cadence_label": "5 月制财年；本站按自然年季度标注",
        "headline_metrics": ["Revenue $10.97B", "ex-退款 GM 40.2%", "直营占比 37.8%"],
        "search_text": ("nke nike 耐克 运动鞋 服装 jordan converse 直营 dtc nike direct 批发 "
                        "大中华区 关税 退款 ieepa 遣散 重组 投资者日 长期财务目标"),
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
        "slug": "pm",
        "ticker": "PM",
        "name": "Philip Morris International",
        "aliases": ["Philip Morris", "菲利普莫里斯", "IQOS", "ZYN"],
        "group": "consumer_staples",
        "cadence_label": "自然年季度；完整披露",
        "headline_metrics": ["Revenue $11.19B", "无烟收入占比 41.5%", "Adj EPS $2.20"],
        "search_text": ("pm philip morris 菲利普莫里斯 烟草 尼古丁 无烟 smoke-free iqos "
                        "heets terea zyn 尼古丁袋 veev 电子烟 marlboro 卷烟 消费必需品 提价"),
    },
    {
        "slug": "race",
        "ticker": "RACE",
        "name": "Ferrari N.V.",
        "aliases": ["Ferrari", "法拉利", "跃马"],
        "group": "luxury_brands",
        "cadence_label": "自然年季度；只报 6-K，无 10-Q",
        "headline_metrics": ["Net revenues \u20ac1,938M", "EBIT margin 31.2%", "\u51fa\u8d27 3,366 \u53f0"],
        "search_text": ("race ferrari \u6cd5\u62c9\u5229 \u8dc3\u9a6c \u5962\u4f88\u54c1 \u8c6a\u534e\u6c7d\u8f66 \u8dd1\u8f66 "
                        "\u4e2a\u6027\u5316 personalization \u51fa\u8d27 shipments f1 \u4e00\u7ea7\u65b9\u7a0b\u5f0f ifrs \u6b27\u5143 20-f 6-k"),
    },
    {
        "slug": "samsung",
        "ticker": "005930.KS",
        "name": "Samsung Electronics",
        "aliases": ["Samsung", "三星", "三星电子", "삼성전자"],
        "group": "semiconductor_ai",
        "cadence_label": "自然年季度；季末速报与月末完整财报分两次披露",
        "headline_metrics": ["Revenue 171.5 兆韩元", "Memory 占收入 70.4%", "营业利润率 52.2%"],
        "search_text": ("samsung 三星 三星电子 삼성전자 005930 半导体 存储 内存 dram nand "
                        "hbm hbm4 服务器 ssd 代工 foundry 晶圆 系统lsi 手机 galaxy mx "
                        "面板 oled sdc harman 韩国 韩元 krw k-ifrs dart 存储周期 涨价"),
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
        "slug": "skhynix",
        "ticker": "SKHY",
        "name": "SK hynix Inc.",
        "aliases": ["SK hynix", "SK 海力士", "海力士", "000660", "HBM"],
        "group": "semiconductor_ai",
        "cadence_label": "自然年季度；不发布任何财务指引",
        "headline_metrics": ["Revenue \u20a979.3T", "\u8425\u4e1a\u5229\u6da6\u7387 76.3%", "\u91cf\u4ef7\u53ea\u7ed9\u7528\u8bcd"],
        "search_text": ("skhynix sk hynix sk\u6d77\u529b\u58eb \u6d77\u529b\u58eb 000660 skhy \u5b58\u50a8 \u5185\u5b58 \u534a\u5bfc\u4f53 "
                        "dram nand \u95ea\u5b58 hbm hbm3e hbm4 \u97e9\u56fd k-ifrs \u97e9\u5143 \u51fa\u8d27\u91cf \u5e73\u5747\u552e\u4ef7 asp "
                        "\u5468\u671f \u8d44\u672c\u5f00\u652f \u5ba2\u6237\u96c6\u4e2d\u5ea6 solidigm kioxia adr 20-f 6-k"),
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
        "slug": "spgi",
        "ticker": "SPGI",
        "name": "S&P Global",
        "aliases": ["标普全球", "S&P", "标普"],
        "group": "financial_data_indices",
        "cadence_label": "自然年季度；完整披露",
        "headline_metrics": ["Revenue $4.15B", "Ratings 交易性 +25%", "调整后 EPS $4.83"],
        "search_text": ("spgi s&p global 标普全球 标普 评级 信用评级 指数 ratings indices "
                        "market intelligence 大宗商品 能源 mobility 分拆 发行量 订阅"),
    },
    {
        "slug": "tjx",
        "ticker": "TJX",
        "name": "The TJX Companies",
        "aliases": ["TJ Maxx", "Marshalls", "HomeGoods", "TK Maxx", "折扣零售"],
        "group": "consumer_retail",
        "cadence_label": "1 月制财年；本站按自然年季度标注",
        "headline_metrics": ["Revenue $15.18B", "Comp +4%", "Adj EPS $1.22"],
        "search_text": "tjx tj maxx marshalls homegoods winners tk maxx sierra homesense 折扣零售 off-price 服装 家居 零售 关税 marmaxx",
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
