#!/usr/bin/env python3
"""Build every reviewed company dashboard and the shared roster."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build import (  # noqa: E402
    amd, amzn, arm, avgo, axp, bc, cboe, cdns, cfr, cme, cost, googl, hkex, ibkr, intc, ker, ma, mc, mco,
    meta, msci, msft, mu, ndaq, nke, nvda, pm, race, rms, samsung, schw,
    skhynix, snps,
    spgi, tjx, tsm, v, zgn,
)
from build import luxury  # noqa: E402
from build.home import write_home  # noqa: E402
from build.payload_guard import write_js  # noqa: E402


DATA_DIR = ROOT / "data"

MODULES = {
    "amd": amd,
    "amzn": amzn,
    "arm": arm,
    "avgo": avgo,
    "axp": axp,
    "bc": bc,
    "cboe": cboe,
    "cdns": cdns,
    "cfr": cfr,
    "cme": cme,
    "cost": cost,
    "googl": googl,
    "hkex": hkex,
    "ibkr": ibkr,
    "intc": intc,
    "ker": ker,
    "ma": ma,
    "mc": mc,
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
    "rms": rms,
    "samsung": samsung,
    "schw": schw,
    "skhynix": skhynix,
    "snps": snps,
    "spgi": spgi,
    "tjx": tjx,
    "tsm": tsm,
    "v": v,
    "zgn": zgn,
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
# payload. Nothing that moves with a quarter is typed here: period label,
# release date and status are read from the payload, and the three card
# figures come from each builder's `headline_metrics(staging)`, computed from
# the series the page itself is built from.
ENTRIES = [
    {
        "slug": "amd",
        "ticker": "AMD",
        "name": "Advanced Micro Devices",
        "aliases": ["AMD", "超威", "超微", "超微半导体"],
        "group": "semiconductor_ai",
        "cadence_label": "自然年季度；业绩 8-K 指引收入、毛利率与费用",
        "search_text": ("amd advanced micro devices 超威 超微 半导体 cpu gpu epyc 服务器 instinct mi450 mi355 "
                        "helios 数据中心 ai 加速器 ryzen 客户端 radeon 游戏 半定制 嵌入式 xilinx 赛灵思 fpga "
                        "认股权证 openai meta anthropic 采购承诺"),
    },
    {
        "slug": "amzn",
        "ticker": "AMZN",
        "name": "Amazon.com",
        "aliases": ["Amazon", "亚马逊", "AWS"],
        "group": "internet",
        "cadence_label": "自然年季度；完整披露",
        "search_text": "amzn amazon 亚马逊 aws 云 电商 零售 广告 互联网 trainium prime",
    },
    {
        "slug": "arm",
        "ticker": "ARM",
        "name": "Arm Holdings plc",
        "aliases": ["Arm", "安谋", "ARM Holdings"],
        "group": "semiconductor_ai",
        "cadence_label": "3 月底制财年；本站按自然年季度标注",
        "search_text": ("arm arm holdings 安谋 半导体 ip 授权 license royalty 版税 cpu 架构 armv9 "
                        "neoverse css 数据中心 agi cpu 自研芯片 软银 softbank arm china 安谋中国 "
                        "关联方 acv rpo 外国私人发行人 20-f 6-k"),
    },
    {
        "slug": "avgo",
        "ticker": "AVGO",
        "name": "Broadcom",
        "aliases": ["Broadcom", "博通", "VMware"],
        "group": "semiconductor_ai",
        "cadence_label": "11 月制财年；本站按自然年季度标注",
        "search_text": "avgo broadcom 博通 半导体 ai xpu 定制加速器 asic networking 以太网 tomahawk jericho vmware 基础设施软件 vcf",
    },
    {
        "slug": "axp",
        "ticker": "AXP",
        "name": "American Express Company",
        "aliases": ["American Express", "美国运通", "运通"],
        "group": "payment_networks",
        "cadence_label": "自然年季度；全年指引逐季修订",
        "search_text": ("axp american express 美国运通 运通 支付 卡组织 发卡行 高端 platinum 白金卡 "
                        "年费 卡费 折扣率 商户 消费额 billed business 拨备 准备金 信用卡 cet1"),
    },
    {
        "slug": "bc",
        "ticker": "BC",
        "name": "Brunello Cucinelli S.p.A.",
        "aliases": ["Brunello Cucinelli", "库奇内利", "BCU.MI"],
        "group": "luxury_brands",
        "cadence_label": "自然年财年；季度只发营收，完整损益一年两次",
        "search_text": ("bc brunello cucinelli 布鲁内罗 库奇内利 奢侈品 意大利 羊绒 成衣 "
                        "静奢 quiet luxury 零售 批发 单品牌 恒定汇率 cfx ifrs 欧元 "
                        "米兰交易所 euronext milan 半年报 指引 门店 dos"),
    },
    {
        "slug": "cboe",
        "ticker": "CBOE",
        "name": "Cboe Global Markets, Inc.",
        "aliases": ["Cboe", "芝加哥期权交易所", "VIX", "SPX"],
        "group": "exchanges",
        "cadence_label": "自然年季度；全年指引逐季修订",
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
        "search_text": "cdns cadence 楷登 eda 半导体 设计 ip palladium 硬件仿真 agentic 芯片设计",
    },
    {
        "slug": "cfr",
        "ticker": "CFR",
        "name": "Compagnie Financière Richemont SA",
        "aliases": ["Richemont", "历峰", "CFR.SW", "Cartier"],
        "group": "luxury_brands",
        "cadence_label": "3 月底制财年；本站按自然年季度标注；销售按季，利润仅半年度",
        "search_text": ("cfr richemont 历峰 奢侈品 珠宝 cartier 卡地亚 van cleef arpels 梵克雅宝 buccellati "
                        "腕表 vacheron constantin 江诗丹顿 jaeger-lecoultre iwc piaget 伯爵 panerai "
                        "baume mercier montblanc 蒙布朗 chloé ynap 恒定汇率 半年度 瑞士 six 欧元 ifrs"),
    },
    {
        "slug": "cme",
        "ticker": "CME",
        "name": "CME Group Inc.",
        "aliases": ["CME Group", "芝商所", "芝加哥商品交易所"],
        "group": "exchanges",
        "cadence_label": "自然年季度；申报文件只指引资本开支",
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
        "cadence_label": "财年末为最接近 8 月 31 日的星期日；本站按自然年季度标注",
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
        "search_text": "googl google alphabet 谷歌 互联网 cloud search youtube",
    },
    {
        "slug": "hkex",
        "ticker": "00388.HK",
        "name": "Hong Kong Exchanges and Clearing Limited",
        "aliases": ["HKEX", "香港交易所", "港交所", "00388"],
        "group": "exchanges",
        "cadence_label": "自然年季度；只有单数季印损益表，双数季由减法得到",
        "search_text": ("hkex 00388 388 港交所 香港交易所 香港交易及结算所 交易所 现货市场 "
                        "日均成交额 adt 衍生品 期交所 股票期权 lme 伦敦金属交易所 金属 "
                        "沪港通 深港通 互联互通 stock connect 北向 南向 债券通 "
                        "上市费 存管费 市场数据 结算 保证金 投资收益 利息回赠 港元 hkfrs"),
    },
    {
        "slug": "ibkr",
        "ticker": "IBKR",
        "name": "Interactive Brokers Group",
        "aliases": ["Interactive Brokers", "盈透证券", "IB"],
        "group": "brokerage_wealth",
        "cadence_label": "自然年季度；完整披露",
        "search_text": ("ibkr interactive brokers 盈透证券 券商 经纪 交易 保证金 "
                        "净息差 nim 客户权益 darts 期权 期货 清算 托管 up-c"),
    },
    {
        "slug": "intc",
        "ticker": "INTC",
        "name": "Intel Corporation",
        "aliases": ["Intel", "英特尔", "Intel Foundry"],
        "group": "semiconductor_ai",
        "cadence_label": "自然年季度；52/53 周财年，季末落在自然季度末前后",
        "search_text": ("intc intel 英特尔 半导体 cpu 处理器 xeon 至强 core 酷睿 数据中心 dcai ccpg ccg "
                        "代工 foundry 18a 14a 晶圆厂 资本开支 scip 合伙人 altera mobileye "
                        "chips 法案 托管股份 escrowed shares 美国商务部 净债务 指引"),
    },
    {
        "slug": "ker",
        "ticker": "KER.PA",
        "name": "Kering",
        "aliases": ["Kering", "开云", "开云集团", "Gucci", "古驰"],
        "group": "luxury_brands",
        "cadence_label": "自然年季度；收入按季披露，利润仅半年度",
        "search_text": ("ker kering 开云 开云集团 gucci 古驰 saint laurent 圣罗兰 ysl bottega veneta 葆蝶家 "
                        "balenciaga 巴黎世家 mcqueen boucheron 宝诗龙 珠宝 眼镜 kering eyewear kering beauté "
                        "奢侈品 时装与皮具 可比增速 半年度 欧元 ifrs"),
    },
    {
        "slug": "ma",
        "ticker": "MA",
        "name": "Mastercard",
        "aliases": ["Mastercard", "万事达", "支付网络"],
        "group": "payment_networks",
        "cadence_label": "自然年季度；完整披露",
        "search_text": "ma mastercard 万事达 支付 网络 跨境 清算 返点 激励 增值服务 vas 发卡行 收单 稳定币",
    },
    {
        "slug": "mc",
        "ticker": "MC.PA",
        "name": "LVMH Moët Hennessy Louis Vuitton",
        "aliases": ["LVMH", "路威酩轩", "Louis Vuitton", "Dior"],
        "group": "luxury_brands",
        "cadence_label": "自然年季度；收入按季披露，利润仅半年度",
        "search_text": ("mc lvmh 路威酩轩 奢侈品 louis vuitton 路易威登 dior 迪奥 tiffany 蒂芙尼 "
                        "bvlgari 宝格丽 sephora 丝芙兰 hennessy 轩尼诗 干邑 香槟 时装 皮具 "
                        "手表 珠宝 精品零售 有机增速 半年度 欧元 ifrs"),
    },
    {
        "slug": "mco",
        "ticker": "MCO",
        "name": "Moody's Corporation",
        "aliases": ["Moody's", "穆迪", "评级"],
        "group": "financial_data_indices",
        "cadence_label": "自然年季度；全年指引逐季修订",
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
        "search_text": "meta facebook instagram whatsapp 脸书 广告 reality labs 互联网",
    },
    {
        "slug": "msci",
        "ticker": "MSCI",
        "name": "MSCI Inc.",
        "aliases": ["MSCI", "明晟", "指数"],
        "group": "financial_data_indices",
        "cadence_label": "自然年季度；完整披露",
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
        "search_text": "msft microsoft 微软 azure copilot m365 云 软件",
    },
    {
        "slug": "mu",
        "ticker": "MU",
        "name": "Micron Technology, Inc.",
        "aliases": ["Micron", "美光", "内存", "存储器"],
        "group": "semiconductor_ai",
        "cadence_label": "财年末为最接近 8 月 31 日的星期四；本站按自然年季度标注",
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
        "search_text": "nvda nvidia 英伟达 半导体 gpu ai 数据中心 hyperscale acie networking blackwell rubin",
    },
    {
        "slug": "pm",
        "ticker": "PM",
        "name": "Philip Morris International",
        "aliases": ["Philip Morris", "菲利普莫里斯", "IQOS", "ZYN"],
        "group": "consumer_staples",
        "cadence_label": "自然年季度；完整披露",
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
        "search_text": ("race ferrari \u6cd5\u62c9\u5229 \u8dc3\u9a6c \u5962\u4f88\u54c1 \u8c6a\u534e\u6c7d\u8f66 \u8dd1\u8f66 "
                        "\u4e2a\u6027\u5316 personalization \u51fa\u8d27 shipments f1 \u4e00\u7ea7\u65b9\u7a0b\u5f0f ifrs \u6b27\u5143 20-f 6-k"),
    },
    {
        "slug": "rms",
        "ticker": "RMS",
        "name": "Hermès International",
        "aliases": ["Hermès", "Hermes", "爱马仕"],
        "group": "luxury_brands",
        "cadence_label": "自然年季度；收入按季披露，利润仅半年度",
        "search_text": ("rms hermes hermès 爱马仕 奢侈品 皮具 马具 birkin kelly 铂金包 "
                        "成衣 丝绸 香水 钟表 珠宝 métier 板块 固定汇率 cc constant currency "
                        "亚太 日本 美洲 中东 半年报 ifrs 欧元 巴黎 euronext"),
    },
    {
        "slug": "samsung",
        "ticker": "005930.KS",
        "name": "Samsung Electronics",
        "aliases": ["Samsung", "三星", "三星电子", "삼성전자"],
        "group": "semiconductor_ai",
        "cadence_label": "自然年季度；季末速报与月末完整财报分两次披露",
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
        "search_text": "schw schwab 嘉信 嘉信理财 券商 经纪 财富管理 银行 净利息收入 nim sweep 现金 交易 nna 客户资产",
    },
    {
        "slug": "skhynix",
        "ticker": "SKHY",
        "name": "SK hynix Inc.",
        "aliases": ["SK hynix", "SK 海力士", "海力士", "000660", "HBM"],
        "group": "semiconductor_ai",
        "cadence_label": "自然年季度；不发布任何财务指引",
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
        "search_text": "snps synopsys 新思科技 eda 半导体 设计 ip ansys 仿真 芯片设计 backlog agentic",
    },
    {
        "slug": "spgi",
        "ticker": "SPGI",
        "name": "S&P Global",
        "aliases": ["标普全球", "S&P", "标普"],
        "group": "financial_data_indices",
        "cadence_label": "自然年季度；完整披露",
        "search_text": ("spgi s&p global 标普全球 标普 评级 信用评级 指数 ratings indices "
                        "market intelligence 大宗商品 能源 mobility 分拆 发行量 订阅"),
    },
    {
        "slug": "tjx",
        "ticker": "TJX",
        "name": "The TJX Companies",
        "aliases": ["TJ Maxx", "Marshalls", "HomeGoods", "TK Maxx", "折扣零售"],
        "group": "consumer_retail",
        "cadence_label": "财年末为最接近 1 月 31 日的星期六；本站按自然年季度标注",
        "search_text": "tjx tj maxx marshalls homegoods winners tk maxx sierra homesense 折扣零售 off-price 服装 家居 零售 关税 marmaxx",
    },
    {
        "slug": "tsm",
        "ticker": "TSM",
        "name": "TSMC",
        "aliases": ["台积电", "Taiwan Semiconductor"],
        "group": "semiconductor_ai",
        "cadence_label": "自然年季度；完整披露",
        "search_text": "tsm tsmc taiwan semiconductor 台积电 半导体 foundry hpc ai 2nm",
    },
    {
        "slug": "v",
        "ticker": "V",
        "name": "Visa",
        "aliases": ["Visa", "维萨", "签证卡"],
        "group": "payment_networks",
        "cadence_label": "9 月制财年；本站按自然年季度标注",
        "search_text": "v visa 维萨 支付 卡组织 网络 跨境 client incentives 激励 借记卡 信用卡 发卡行 收单",
    },
    {
        "slug": "zgn",
        "ticker": "ZGN",
        "name": "Ermenegildo Zegna N.V.",
        "aliases": ["Zegna", "杰尼亚", "Ermenegildo Zegna", "Thom Browne", "TOM FORD FASHION"],
        "group": "luxury_brands",
        "cadence_label": "自然年财年；收入按单季公布，完整损益一年两次",
        "search_text": ("zgn zegna ermenegildo 杰尼亚 奢侈品 意大利 男装 面料 filiera "
                        "thom browne tom ford fashion 汤姆布朗 汤姆福特 dtc 直营 批发 "
                        "retail-first 大中华区 gcr 有机增速 organic adjusted ebit 看跌期权 "
                        "put option 纽交所 外国私人发行人 20-f 6-k ifrs 欧元"),
    },
]


# ── cross-company pages ─────────────────────────────────────────────────────
# A page that is about a group rather than a company. It is deliberately NOT in
# `MODULES`/`ENTRIES`: it has no filings series of its own, it must not be
# counted in the home page's 「N 家公司」, and it must not get a company card.
# What it does share with the company pages is the build pipeline -- it is in
# `build_all()`, so `build/home.py`'s window counts see its charts, the AI capex
# cross-page table identity covers it, and `build/all.py && git status` stays
# the drift check for its payload and shell too.
CROSS_MODULES = {
    "luxury": luxury,
}

CROSS_ENTRIES = [
    {
        "slug": "luxury",
        "name": "奢侈品组跨公司对照",
        "group": "luxury_brands",
        "members": ["mc", "cfr", "rms", "ker", "zgn", "bc"],
        "blurb": "六家同框：能对齐的，和对不齐的",
    },
]


def roster_payload(payloads: dict) -> dict:
    """Return the deterministic cross-company navigation payload.

    ``payloads`` maps slug to that company's built dashboard payload, so a page
    whose latest quarter moved cannot leave a stale label in the nav.
    """
    items = []
    for entry in ENTRIES:
        slug = entry["slug"]
        latest = payloads[slug]["latest"]
        module = MODULES[slug]
        staging = json.loads(module.STAGING_PATH.read_text(encoding="utf-8"))
        item = {}
        for key, value in entry.items():
            item[key] = value
            if key == "cadence_label":
                item["headline_metrics"] = module.headline_metrics(staging)
        items.append({
            **item,
            "latest_label": latest["disclosed_period_label"],
            "latest_full_label": latest["full_financial_period_label"],
            "release_date": latest["release_date"],
            "status": latest["status"],
        })
    return {
        "schema_version": "quarterly-roster/v1",
        "groups": GROUPS,
        "items": items,
        # A separate key, not another `items` entry: `build/home.py` writes one
        # company card per `items` row and the home-page census counts them, so
        # a cross page added there would be counted as a 36th company.
        "cross": CROSS_ENTRIES,
        "footer": "Quarterly Results · 公司披露值与透明自算 · 仅供研究",
    }


def write_roster(payload: dict) -> None:
    write_js(DATA_DIR / "roster.js", "ROSTER", payload, "all")


def build_all() -> dict:
    """Return every published payload: the company pages and the cross pages.

    Cross pages are in here rather than beside it because three site-wide checks
    read this dict and each of them should cover every published page, not every
    company: `build/home.py`'s 42-quarter census, the AI-capex cross-page table
    identity, and the drift check. `roster_payload` walks `ENTRIES`, so the extra
    keys never reach the company roster.
    """
    payloads = {}
    for slug, module in {**MODULES, **CROSS_MODULES}.items():
        source = json.loads(module.STAGING_PATH.read_text(encoding="utf-8"))
        payloads[slug] = module.build_payload(source)
    return payloads


def main() -> int:
    # Roster first: each page's shell stamps the content hash of every script it
    # loads, roster.js included, so the roster has to be final before the shells
    # are rendered or they would carry the previous build's digest for it.
    payloads = build_all()
    roster = roster_payload(payloads)
    write_roster(roster)
    # The home page's cards and counts are written from the same roster and
    # payloads, so a quarter roll never has to retype a card.
    write_home(roster, payloads)
    for module in {**MODULES, **CROSS_MODULES}.values():
        module.main()
    print(f"Quarterly Results: {len(MODULES)} reviewed companies "
          f"+ {len(CROSS_MODULES)} cross-company page(s) + shared roster")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
