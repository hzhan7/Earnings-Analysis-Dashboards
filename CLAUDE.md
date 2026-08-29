# 并发接入一家公司：给每个 worktree 的协议

这份文件是给同时在这个仓库里干活的多个会话看的。2026-08-29 一天之内 main
动了二十几次、十几个 worktree 并行接入公司页，下面每一条都是那天真实踩过的，
不是预防性的清单。

**开工第一件事**：`git fetch origin && git rebase origin/main`。你的 worktree
建出来的那一刻起 main 就在动，别把建 worktree 时的基线当固定值。

---

## 1. GROUPS 组键 —— 已经定好，不要另造同义键

| key | label | order |
|---|---|---|
| `internet` | 互联网平台 | 1 |
| `software_cloud` | 软件与云平台 | 2 |
| `semiconductor_ai` | 半导体与 AI 基础设施 | 3 |
| `financial_data_indices` | 金融数据、评级与指数 | 4 |
| `payment_networks` | 支付网络 | 5 |
| `brokerage_wealth` | 券商与财富管理 | 6 |
| `consumer_retail` | 消费零售 | 7 |
| `consumer_staples` | 消费必需品与烟草 | 8 |
| `luxury_brands` | 奢侈品与豪华汽车 | 9 |
| `exchanges` | 交易所 | 10 |

**规则**：先落地 `origin/main` 的会话拥有该键，后到的服从，不要造同义键。
需要新组就追加，`order` 取当前最大值 +1 —— `test_groups_render_in_the_order_they_declare`
要求 `order` 按列表位置升序且不重复，所以新行放在末尾、给最大的 order。

写这一行之前，先读一次真值：

```bash
git show origin/main:build/all.py | grep -c '"key": "<你的键>"'
```

一次不会错的读，胜过一次不会冲突的合并。

**为什么这条要写死**：重复的 GROUPS 行**不会**产生冲突。四种情况实测过：

```
同一行、同一位置          干净合并，一行   （去重）
同键不同 label            冲突，git 停下
同键同 label 不同 order   冲突，git 停下
同一行、不同位置          干净合并，两行   ← 真正会中的那个
```

所以光约定字面量不够，**插入位置也要一致**。重复的键会让下拉框里那一组的每家
公司出现两次，而整套测试全绿 —— `test_every_entry_group_exists_in_groups` 的
合法键集是**从 GROUPS 构造出来的**，重复的键仍然是集合成员，所以它按构造就抓
不到；`test_group_keys_are_unique` 是为此单独加的断言。

---

## 2. 接入一家公司要动的共享文件

新的 `build/<slug>.py` + `series/<slug>.json` 之外，还有六处，其中两处失败是静默的：

1. **`.gitignore`** —— `series/*.json` 被忽略，每家公司一行 `!series/<slug>.json`
   反否定。漏了，`git add` 会以 rc=0 跳过你的 series，`git diff --cached` 里也看不见。
2. **`build/all.py`** —— 顶部 import 行、`MODULES`、`ENTRIES`、必要时 `GROUPS`。
   `MODULES` 与 `ENTRIES` 严格按 slug 字典序，**同序同索引**。按位置插入，不要追加：
   `'amzn' < 'avgo' < 'axp' < 'cdns' < 'cost'`。
3. **`index.html`** —— 手写，不读 payload。卡片块 + 第 14 行的 masthead 计数。
4. **`tests/test_content_boundary.py`** —— 模块级 `COMPANY_SLUGS` 常量（在文件顶部，
   不在测试函数里）。变红就加 slug，**不要改断言**。
5. **`tests/test_tsm_dashboard.py`** —— `test_published_payload_roster_and_shell`
   里那个**有序**的 roster 字面量。按序插入，不要追加。
6. **`README.md`** —— 开头的公司清单、`http://127.0.0.1:8765/<slug>/` 那份列表，
   以及那句用分号一路串下来的长句（见 §4 第 3 条）。

还有一条不是"改"而是"带上"：**`ai_capex_cycle_table` 每一页都要发布**，包括
和 AI 供应链毫无关系的公司（Visa、Mastercard、TJX、Ferrari 都带着）。它不是图，
是收在 `<details class="appendix-drawer">` 里的全站共享对照表，标题本身就写着
「跨页对照」。`test_cross_page_table_is_identical_on_every_page` 用一个无默认值的
`next()` 取它，缺了会抛 **StopIteration** 而不是断言失败 —— 修法是补上表，不是
给页面开豁免。**带着这张表**和**成为表里的一列**是两件事，Cadence / Synopsys /
TSMC / NVIDIA 都带着它却不在 `_CASH_CAPEX_SOURCES` 里。

---

## 3. 并发规则

- **共享检出（主仓的 main）里只 Edit 自己的 hunk，绝不 Write 整个共享文件。**
  凭记忆重写一份会静默删掉别人的 slug，而测试仍然绿 —— 因为
  `COMPANY_SLUGS` 和 `test_tsm_dashboard.py` 的 roster 字面量是手工维护的列表，
  会跟着它们守护的注册一起消失。改之前重读一次。
- **共享检出里绝不 `git add -A` / `git reset` / `git restore` / `git stash`。**
  它们会动到别人正在暂存的文件，而且 **stash 栈是跨所有 worktree 共享的**。
  在你自己独占的 worktree 里这些命令没问题。
- **`git commit --only <显式路径>`**，它只从这些路径构建提交、忽略索引其余部分，
  所以别人在你编辑和提交之间暂存的文件不会被卷进来。但它的另一半也会咬人：
  **它同样会排除你自己重新生成的文件**。每个 `?v=` 都是内容哈希，所以
  **任何动了 `data/*.js` 的提交都必须带上所有链接它的 shell**；动了
  `data/roster.js` 的提交要带上全部 shell。
- 别人落地之后你的 shell 就作废了：每个 `*/index.html` 都盖着
  `sha256(data/roster.js)[:8]`，而 roster.js 是**整个公司集合**的函数。rebase
  之后必须重跑 `build/all.py`、重新暂存 shell，**绝不沿用 rebase 前构建的 shell**。
- **排程和授权是两件事，不要混。** 多个会话并行时会出现一个协调者，它可以决定
  顺序、门槛、谁先谁后、谁的方案落地 —— 那些都是排程。**但「推不推」不在里面。**
  推到共享远端是对外动作，只有那个会话自己的用户能批准；同伴会话的 OK 替代不了它。
  2026-08-29 当天四个会话先后按住不推，三次是协调者把「队列空了」说成了「你可以推
  了」—— 队列空只解除了一个约束，而它们等的是另一个，**协调者无权解除**。混过一次
  就会变成惯例，所以每次都要分开说：「轮到你了」不等于「你被授权了」。
- **争用的单位不是你编辑的文件，是你的断言依赖的文件。** 按「谁改哪个文件」串行
  是不够的：一条放在 `tests/` 里的断言可能读 `README.md`，而另一个会话正在写
  `README.md` —— 两人文件不重叠，却会互相把对方变红。2026-08-29 这一整天的排程
  都是按前者做的，只是恰好没撞上。开工前问的是「我读什么」，不只是「我写什么」。

---

## 4. rebase 配方：冲突列表看着吓人，绝大多数是生成物

一次典型的 rebase 会冲突 20 多个文件，其中 18 个是 `data/roster.js` 加每一个
`*/index.html` —— 它们**每次都冲突**，因为 roster.js 的摘要盖在所有 shell 上。
不要手工合并它们：

```bash
for f in $(git status --porcelain | grep '^UU' | awk '{print $2}' \
           | grep -E '^[a-z]+/index\.html$|^data/roster\.js$'); do
  git checkout --ours -- "$f" && git add -- "$f"
done
python3 build/all.py
```

剩下真正需要判断的只有五六个：`build/all.py`、`COMPANY_SLUGS`、
`test_tsm_dashboard.py` 的有序字面量、`.gitignore`、`index.html`、`README.md`。
下面三个坑**都不会给你冲突标记**：

1. **`ENTRIES` 的冲突会切在一个 dict 字面量的内部。**
   "两边都留"会把两家公司熔成一个 dict，而 **Python 对重复键不报错、最后一个胜出**，
   于是前一家静默消失。源码 grep 出来的 `"slug":` 行数还是对的，所以肉眼抽查没用。
   2026-08-29 接 RACE 时真实发生：`MODULES` 21 家、`ENTRIES` 20 家。每次解完跑一行：

   ```bash
   python3 -c "import sys;sys.path.insert(0,'.');from build.all import MODULES,ENTRIES;\
   e=[x['slug'] for x in ENTRIES];print(list(MODULES)==e,len(e))"
   ```

   反方向是响的（`ENTRIES` 有而 `MODULES` 没有 → `roster_payload` 抛 `KeyError`）；
   有 `MODULES` 没 `ENTRIES` 才是静默的：页面照建照收录，只是从 roster 和每一页的
   导航里消失，和悬空组键是同一种"没人能到达的页面"。

2. **`index.html` 的公司计数，最危险的是它*不*冲突的时候。**
   如果两个分支各自在自己的基线上都数对了，它们写的是**同一个数**，git 干净合并
   这一行、同时合并两边的卡片块 —— 结果 N+1 张卡片配着 N 的计数，任何地方都没有标记。
   **重数，不要 +1**：从 `len(ENTRIES)` 重新算，并用
   `grep -c 'class="hcard"' index.html` 交叉核对。那一行第二个数字是八季窗口，不是
   公司数，别动它。

   2026-08-29 连续四次全中：NKE 19 张卡配 18、RACE 20 配 19、NDAQ 21 配 20、
   AXP 22 配 21。`test_the_home_page_counts_the_companies_it_lists` 会抓到，
   但前提是你在 rebase 之后**重新跑了测试**。

   **结果相同的时候，两种写法的区别才最要紧。** CME 落地那次，合并后卡片是 25 张
   而 masthead 还写着 24（CBOE 落地时的数）。按「24 + 1」写会得到 25 —— 答案正确，
   但**你不会发现 masthead 本来就落后了一格**，那个已经存在的错误被算对了一次，然后
   继续往前走，直到某次增量与重数的结果不同才暴露，而那时它已经错了不知道多少个提交。
   这和 §5 那条是同一族：**增量法的输入里包含它要检查的那个数。**

3. **README 那句用分号串起来的长句**，两个会话都会往同一段里加自己的分句，
   git 会把两个完整版本都交给你，哪个都不是答案。要拼成**一句**，不是两段。
   2026-08-29 接 NDAQ 时这里接错过，在 main 上留下一个以 `are built; Nasdaq gets`
   开头的悬空片段，直到接 AXP 时才修掉。README 没有任何测试守着，只能靠读。

---

## 5. 提交前后的门禁

顺序是固定的，因为其中两道**必须在提交之后**跑：

```bash
python3 build/all.py && git status --porcelain          # 必须只剩未跟踪文件
python3 -m unittest discover -s tests -p 'test_*.py'    # 读数量，不是读 OK
python3 -m unittest discover -s tests -p 'test_*.py' -v | grep -c _FailedTest   # 必须是 0
```

**读测试*数量*，不是 `OK`/`FAILED` 那一行。** 一个 import 失败的测试文件贡献
**零**个测试，并且报成 `ERROR`（`unittest.loader._FailedTest`）而不是 failure，
所以套件照样打印一个自信的 `Ran N tests`，而 N 悄悄变小。实测过：一行多余的语法
让总数从 373 掉到 345，输出结尾照常。解冲突时改到测试文件正是这事发生的时刻。

最省事的验法是对着 main 做算术，不用逐文件：

```
origin/main 的总数 + 你自己那个 test_<slug>_dashboard.py 的数 == 你分支的总数
```

2026-08-29 五次接入全部精确对上：475+49=524、524+32=556、556+34=590、
590+45=635、635+42=677。

**提交之后**，从提交本身抽取，跑两道检查 —— 它们需要相反的形式，混成一道会让
第二道永远不可能失败：

- **import 检查，要构建**：`git archive HEAD | tar -x -C <tmp>`，然后在里面跑
  `python3 build/all.py`。抓的是 `build/all.py` import 了一个 builder 却没被跟踪
  —— 这在工作区里跑测试是发现不了的。抽取里 `test_content_boundary` 的四个测试
  会 ERROR（它们 shell out 到 `git ls-files`，抽取不是仓库），这是预期的。
- **摘要检查，不要构建**：抽取后**直接**核对每个 `*/index.html` 里的 `?v=` 与它
  指向的那个已提交文件的 `sha256`。**在抽取里先构建再核对，等于把两边都重新生成
  再互相比较，无论提交了什么都会通过。**

  一般形式，值得带出这个仓库：**一个从被检查对象推导出自己期望值的检查，不可能失败。**
  更早的探测信号是：**一个你还没挣到的绿灯。**

**变异验证本身有三个坑，全部在 2026-08-29 当天被踩到：**

- **注入必须自己带断言。** `str.replace` / `sed` / 正则替换在找不到目标时**静默
  返回原文**，于是你是在对一个没被改过的文件跑闸门，然后拿它的绿灯当证据。当天
  三个人各中一次，三次都是这一种，`assert old in s`（或注入后 `assert 改过 != 原文`）
  都能拦住 —— 两次拦住了，一次没写这句 assert。锚点失效的原因往往很平常：那一次
  用的是几小时前的措辞，而文件在那之后被别人重排过。
  **「变异后仍然绿」既可能是闸门有洞，也可能是你根本没变异，两者看起来一模一样。**
- **对照两个读数之前，先确认它们读的不是同一份东西。** 上面那条讲的是怎么**防住**，
  这条讲的是为什么**难以察觉**：注入 no-op 之后，你手里的"对照组"和"实验组"是同
  一份文本，于是两个读数必然一致，而那个一致读起来像是证据。同一形状的第三种外形
  在本节上面就有 —— **在抽取里先构建再核对摘要**，那一种连注入步骤都没有，assert
  无从下手，只能靠认出「这两个读数的输入是同一个」。三者是同一个错误的三张脸：
  两个正则跑同一份文本、构建后再和自己比、抽取里重新生成两边再互相比较。
  **共享同一个输入的两个读数，它们的一致不构成证据。**

  **别人的报告是一个输入，不是两个。** 并发会话里这条最常被绕过：拿同伴的描述和
  自己的假设互相印证，两者的共同输入是那份描述，于是印证必然成功。当天有会话据此
  给另一次事故分了错类 —— 它读的是叙述，没去核那个字符串在不在树上，而那一步才是
  独立的第二个输入。反过来，当天所有站住脚的交叉验证都有这个特征：拿到坐标之后用
  **自己写的脚本**重量一遍（`y=[-57.3, -50.5]` 被三方各自独立量到）、拿到「你的内容
  已在 main 上」之后自己跑 `git merge-base --is-ancestor` 确认、拿到一个数之后回
  申报文件重算。**同伴给的数字是线索，不是证据。**
- **上一个基线上验过 ≠ 这个基线上成立。** 变异跑起来麻烦、结论又是二元的，做完
  一次就很想当成那条断言的固有属性。它不是，它是那条断言**在某一棵树上**的属性。
  rebase 之后连同变异一起重跑，**包括你认为「按理说不会变」的时候** —— 只在觉得
  可能出事时重跑，等于没有这条规矩。
- **skip 对上面那套数量算术结构上不可见。** 一个被跳过的测试**仍然计入 `Ran N`**，
  所以「基线 730 + 我的 1 条 = 731」在 render gate 根本没跑的情况下照样成立。数量
  能抓住 import 失败导致的静默掉测试，抓不住这个。**读 skip 数，不要读最后一行。**

```bash
python3 - <<'PY'
import hashlib, pathlib, re, sys
root = pathlib.Path(sys.argv[1] if len(sys.argv)>1 else ".")
bad = n = 0
shells = sorted(root.glob("*/index.html"))
for s in shells:
    for m in re.finditer(r'src="\.\./(\S+?)\?v=([0-9a-f]+)"', s.read_text(encoding="utf-8")):
        n += 1
        if hashlib.sha256((root/m.group(1)).read_bytes()).hexdigest()[:len(m.group(2))] != m.group(2):
            bad += 1; print("DRIFT", s.parent.name, m.group(1))
print(f"{n} script tags / {len(shells)} shells / {bad} drifted")
PY
```

---

## 6. 绿测试不等于图画出来了

整套验证栈检查的是 **payload**，从来不看**图**。`payload_guard` 拒绝 payload 里的
非有限值，各家的测试断言数字和形状，`build/all.py` + `git status` 查漂移 —— 三者
都会被一个画出坏图的 payload 满足，因为**渲染器内部算术产生的 NaN 对它们不可见**。

两个已经踩到的真实例子：

- `kind: "gs_bar"` 不给 `yoy` 时会画一条 `Y(ex.avg12)` 的虚线基准线，而 `avg12`
  是**由 payload 提供**的、不是渲染器算的。全站 27 个 `gs_bar` 里 26 个给了 `yoy`、
  **0 个给了 `avg12`**，所以这条分支从来没被真实数据走过；唯一两者都没给的
  AVGO Ex16 输出 `<line y1="NaN" y2="NaN">`，浏览器静默丢弃，线根本没画出来。
- 八季序列上的十二期移动平均同样是 NaN。
- `kind: "stacked_dual"` 的右轴上界**写死在 60**（`charts.js:914`
  `rtk = ticks(0, rc.ymax || 60, 6)`，不看数据）。超过 60 的线被画到负 y、浏览器
  直接裁掉，而图例照常写着它。`ibkr` Ex8（少数股东占比 77.9%）就这样发了很久：
  实测坐标 `y=[-57.3, -50.5]`，画布高 `332.2`。**这一处一个 NaN 都没有** ——
  坐标全是合法有限数字，只是落在画布外，所以只查 NaN 的那套断言按构造看不见它。
  画占比线时传 `"ymax": 100`。其余 dual 图型走 `ticks(min(rv,0), max(rv), 9)`，
  按数据算，不受影响。

**比「要不要渲染」更难的是「渲染之后断言什么」。** MCO 那次少一根柱的作者当晚
**确实**开了浏览器 —— 它查了 NaN 属性、字面标签、SVG 数量，全是它前一小时刚被烧过
的失败模式；它没查「每张图的柱子数是不是等于它自己 x 轴承诺的数目」。少一根柱不留
NaN、不抛错、不产生空元素、数值还全对，三条断言按构造都看不见。**浏览器检查是对的
直觉，断言集选错了。**

一套只检查上次失败模式的渲染检查，和一套只检查 payload 的测试，是同一种局限，只是
换了一层楼。**断言要从「这张图自己承诺了什么」推导，不要从「上次是怎么坏的」推导** ——
`len(values) == len(xlabels)`（标签数 == 柱子数）、纵坐标落在 viewBox 之内，这类
结构恒等式能抓到你还没见过的那一类；失败模式清单不能。

**而闸门要活下来，靠的是它拒绝报警的地方。** 越界检查只对 `fill="none"` 的
path/polyline 生效、且只查纵轴：横向不查，因为 end_label 与柱标本来就故意画在边距
里；`fill` 不为 none 的不查，因为堆叠面积块本来就贴边。同理，NaN 要用 token 边界
而不是 `includes`（否则匹配到 IR 链接里 "Fi**nan**cial" 的中间），README 的 bullet
要锚定行首（否则吃掉正文里的行内地址），公司名匹配要双向包含而不做后缀剥离。
**一个会误红的闸门会被 `--no-verify` 绕过，然后什么都不保护** —— 这句话 2026-08-29
当天被四个互不通气的会话各自独立说了一遍，它是这一整节的前提，不是脚注。

**最后，闸门存在的理由不是「出过事」，是「躲开是靠运气」。** 写死 60 那条被发现的
当天，同时接入的另一个交易所页没有中招，它自己的复盘是：

> 我最后没中招，但那是因为唯一的 `stacked_dual` **恰好**传了 `ymax`，
> 不是因为我知道有这回事。

这是「没出事」和「不会出事」的全部区别。本节六条闸门对应的每一个缺陷，在被抓到
之前都有人这样躲过去过 —— `ibkr` Ex8 躲了很久没躲掉，那一页躲掉了却不知道自己在躲。
所以判断一条闸门值不值得存在，不要问「这个错误出现过几次」，要问「没出现的那些次，
是因为有东西挡着，还是因为恰好」。

**推之前把页面渲染一遍。** 无人值守的会话里 `preview_start` 会被直接拒绝，
也不能用 `file://`（shell 靠相对 `<script src>` 加载 payload）——**不要绕过这个拒绝**，
改用 jsdom：把 `npm install jsdom` 装到临时目录（**不要装进仓库**），跑真实渲染器：

```js
const fs = require("fs"), { JSDOM } = require("jsdom");
const REPO = process.argv[2];
const SLUGS = fs.readdirSync(REPO).filter(d =>
  fs.existsSync(`${REPO}/${d}/index.html`) && fs.existsSync(`${REPO}/data/${d}.js`));
const NANRE = /(^|[^A-Za-z])(NaN|Infinity|undefined)([^A-Za-z]|$)/;
for (const slug of SLUGS) {
  const errs = [];
  const dom = new JSDOM(fs.readFileSync(`${REPO}/${slug}/index.html`, "utf8"),
                        { runScripts: "outside-only", pretendToBeVisual: true, url: "https://x/" });
  dom.window.console.error = (...a) => errs.push("console.error: " + a.join(" "));
  try {
    ["data/roster.js", `data/${slug}.js`, "assets/charts.js", "assets/page.js"]
      .forEach(r => dom.window.eval(fs.readFileSync(`${REPO}/${r}`, "utf8")));
    dom.window.document.dispatchEvent(new dom.window.Event("DOMContentLoaded", { bubbles: true }));
  } catch (e) { errs.push("threw: " + e.message); }
  const d = dom.window.document;
  for (const el of d.querySelectorAll(".grid svg *"))
    for (const a of el.getAttributeNames())
      if (NANRE.test(el.getAttribute(a))) { errs.push(`NaN attr ${el.tagName}.${a}`); break; }
  const empty = [...d.querySelectorAll(".grid > *")].filter(n => !n.querySelector("svg")).length;
  if (empty) errs.push(`${empty} grid children without svg`);
  // notes 走 esc()：这里出现字面标签就是读者看得见的字符
  const lit = [...d.querySelectorAll("li")].map(li => li.textContent)
                .filter(t => /<\/?[a-z][a-z0-9]*>/i.test(t));
  if (lit.length) errs.push(`literal tag in ${lit.length} <li>`);
  if (!d.querySelector("optgroup option")) errs.push("not in nav dropdown");
  console.log(`${errs.length ? "FAIL" : "OK  "} ${slug}` + (errs.length ? "  " + errs.join("; ") : ""));
}
```

检查器自己也有一个坑：**NaN 要用词边界判，不能用 `includes`。** 一个天真的
`/NaN|Infinity|undefined/i` 会匹配到 NVIDIA 那条 IR 链接里 "Fi**nan**cial" 的
中间，报出 26 个幻觉失败。

---

## 7. 渲染契约：哪些槽会把标记当字面字符印出来

`assets/page.js` 的分工是：

- `headline` / `title` / `subtitle` / `tracker` 用 `textContent` 写入；
- `section.title` / `section.description` / **`notes`** / 表格标题走 `esc()`；

以上四类里的 `<b>` 都会变成读者看得见的六个字符。
而 `brief` / `footer` / 每个 exhibit 的 `note` / `src_extra` 是原样 innerHTML，
那里的标记是合法且大量使用的（全站 140 多条图注用了）。

`test_literal_text_fields_carry_no_markup`（`tests/test_content_boundary.py`）
钉住这条。注意它**对 `v` / `ibkr` / `mco` / `spgi` 无法变红** —— 那四个 builder
把 notes 建成 `[plain_text(p) for p in [...]]`，标记在进 payload 之前就被剥掉了，
它们靠构造受保护而不是靠这条断言。绿灯不等于那四个 builder 的源码里没有标记。

写 note 的时候直接不写标记，比包一层 `plain_text()` 好：`plain_text()` 的立论是
"同一句话既要进图注又要进 notes，写一遍带标记再剥"，没有这个前提就只是在源码里
留下永远不生效的标记，还让闸门对那个 builder 永远无法变红。

---

## 8. 读提交标题时注意

这个仓库每条提交标题陈述的是**它修掉的那个发现**，不是它留下的状态。
`并入 SPGI：…13 张卡配着 12 的计数` 读起来像一棵坏掉的树，实际上是那次修复。
看树，别看句子。
