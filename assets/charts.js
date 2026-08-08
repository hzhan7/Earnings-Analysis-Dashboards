/* ==========================================================================
   GS exhibit 渲染器 —— 零依赖 SVG，目标是与 skill 生成的 PDF 逐张一致。

   图型 ←→ build_report.py 的绘图函数：
     bar_line         柱 + 线（同一轴）                COST Ex1/5/6/7/8
     lines            N 条线（可带点标记 / 注解）        COST Ex2/9/10/11
     bar_line_dual    柱（左轴）+ 线（右轴）             COST Ex3
     diverging_bars   正负分色柱                        COST Ex4
     bars_labeled     柱 + 每柱数值 + 注解               COST Ex12
     gs_bar           柱 + 12月均线 + 每柱数值 + YoY/MoM 气泡  IBKR Ex2/4/6/10/12
     gs_line          平滑线 + 每点数值（可选底部气泡）   IBKR Ex3/5/11/13
     gs_line_avg      平滑线 + 12月均线 + 右端均值标注    IBKR Ex7
     lines_endlabels  多条平滑线 + 仅两端标数值          IBKR Ex9
     stacked_dual     堆叠柱 + 右轴线（段内标数值）       IBKR Ex8

   12 家看板新增的图型 ←→ build/gsx.py 的同名函数（PDF 版与网页版必须同型）：
     heat_matrix      行=年 列=月 的热力矩阵，格内写数值   gsx.heat_matrix
     year_lines       每年一条线叠在 1-12 月轴上，当年红   gsx.year_lines
     qtr_bar          月度汇总成季度柱 + 右轴 y/y          gsx.qtr_bar
     seasonality      灰=历史同月均值 / 蓝=今年 配对柱     gsx.seasonality
     bridge_bar       正上负下的恒等式桥 + 净额菱形        gsx.bridge_bar
     grouped_bars     同一 x 上两根并排柱 + 右轴误差线     gsx.implied_vs_actual
     range_band       指引区间带状填充 + 实际值菱形        gsx.range_vs_actual
   字段清单见 cache/engine_kinds.md（数据契约）。

   所有数值由 build_data.py（复用 skill 同一份算法）预先算好，本文件只负责画。
   —— 新图型同此：累计值、历史同月均值、季度合计、误差率一律在 Python 侧算完再传。
      唯一的例外是「桥」的净额：给了 ex.net 就用给的，没给才在这里求和（那是恒等式，
      不是口径判断）。

   ex 上与「基线规范」直接对应的可选字段（build_data.py 传入）：
     ycap    number    截轴上界（规矩 7）。超界的柱画到 cap 并加断口符号，超界的点钳位
                       画空心圈，真值一律竖排标出——截轴是为了看清主体，不是删点。
                       注意：双轴图上零点对齐可能把上界重新推高到 ycap 之上，此时就不截了
                       （宁可不截也不能让两轴零点错位）；截轴主要给单轴柱图用。
     yfloor  number    截轴下界，同上。
     cap_note string   截轴时图顶左上角的斜体小字（如 'axis capped — outliers shown in red'）。
     break_at  int|int[]   结构性断点的 x 索引（规矩 6），画在该期柱的左缘，
                           语义是「从这一期起与左侧不可比」。
     break_label string|string[]  断点竖排标签；给一条时所有断点共用。
     bar_marks int[]   需要标成斜纹的柱（如 53 周财年多出一周的月份），与 break_at 配合用。
     mark_note string  bar_marks 命中的期在 tooltip 里追加的说明。
     ylab2   string    右轴标题（双轴图），与左侧 ylab 对称。

   ex 上的可选「补 deck 缺口」字段（三条都**默认关闭**，给了才生效）：
     zero_base bool    kind:'lines' 的纵轴从 0 起（同 gsx.long_line 的 set_ylim(0, max*1.16)）。
                       不给就还是通用留白分支 —— 那实际是一次没有标注的隐性截轴，
                       长历史图务必给上。序列含负值时下界仍留在数据之下，不会把负值压没。
     end_label bool    kind:'lines' 每条序列的末点标出数值（同 gsx.long_line 的 n_label）。
                       长历史图上那是唯一的绝对水平锚点。
     yoy     {values,color,yfmt,name}
                       kind:'gs_bar' 的次轴同比折线（同 gsx.lvl_bar）。给了就画次轴 y/y
                       并**不画 12 个月均线**；没给维持现状。右轴刻度与折线同色。
   ========================================================================== */
(function () {
  'use strict';
  var SVG = 'http://www.w3.org/2000/svg';

  /* PDF 使用的 GS 风格取色，与 build_report.py 完全一致 */
  var C = {
    NAVY: '#1F3864', BLUE: '#9DC3E6', MBLUE: '#2E75B6',
    GRAY: '#A6A6A6', GREEN: '#548235', RED: '#B23A48',
    /* gsx.py 的第 6 个序列色。原先漏在这里，导致六品种堆叠图（CME）没有第 6 个颜色可用，
       只能把 RED 拿去当数据色 —— 而 RED 在这套语言里是断点与离群值的专用色，
       一根红柱到底是「金属品种」还是「这个点被截轴了」就分不清了。 */
    GOLD: '#BF9000',
    WHITE: '#FFFFFF', GRID: '#E3E3E3', AXIS: '#999999', INK: '#333333',
  };
  /* 认得的色名 → 十六进制；本来就是 CSS 颜色（#xxx / rgb() / url(#pat)）的原样放行；
     其余一律退回 NAVY。
     原先是 `C[k] || k`：payload 写了 'GOLD' 这种 C 里没有的名字时，字符串会被原样塞进
     fill 属性，浏览器当作无效值 → 渲染成黑色。黑色不在这套配色里，但它看起来像是
     「故意的深色」，所以这种错会一路上线而没人看出来。退回 NAVY 至少是本套色。 */
  var col = function (k) {
    if (C[k]) return C[k];
    if (typeof k === 'string' && /^(#|rgb|hsl|url\()/i.test(k)) return k;
    return C.NAVY;
  };
  var BREAK = '#C00000';        // 断点/截轴标注专用红，与 gsx.py 的 RED 同一角色
  var uid = 0;                  // 一页多张图共存，pattern 之类的 id 必须全局唯一

  /* ── 屏幕字号缩放 ──────────────────────────────────────────────────────
     各处 size: 的数值照搬 PDF exhibit，而 PDF 的一页宽 ≈ 屏幕上半栏卡片的两倍，
     缩到 web 上就偏小。这里 1 SVG user unit = 1 CSS px（viewBox 的 W 直接取自
     host.clientWidth），所以 size: 6.6 就是屏幕上实打实的 6.6px —— 用户看不清的
     正是这批。

     所有文字统一乘 FS，凡是「为放文字而留的空」（边距、标签行距、竖排标签长度、
     热力图格高）也按它缩放，否则字变大而空间没变，只会把 thinLabels 逼着多抽掉
     标签、把刻度顶出画布。不随字号变的量（网格线宽、柱宽、点半径）一律不动。

     ── FS 跟卡片宽度走，不是全站一个数 ──────────────────────────────────
     半栏卡片（~571px）和通栏卡片（~1172px）画的是同样多的点，通栏那张每个点分到
     的横向空间是前者的两倍 —— 同一个字号在通栏上显得更小、而且它明明放得下更大的字。
     所以按 W 在 [FS_MIN, FS_MAX] 之间线性插值：窄卡克制，宽卡放开。
     这也是压住重叠的关键：挤的是窄卡，而窄卡拿的正好是下界。

     FS_MIN = FS_MAX 就退化成全站统一一个数；两个都设 1 则全站输出逐字节退回改前。

     辅助函数别取名 fsz：draw() 里 seasonality 那一支有个局部的
     `var fsz = fmtOf(...)`（数值格式器）。var 是函数作用域且会提升，那一个 var
     就把**整个 draw()** 里的外层同名函数遮成 undefined，每张图都会在 draw 里炸掉。 */
  var FS_MIN = 1.45, FS_MAX = 1.70;
  var W_NARROW = 571, W_WIDE = 1172;   // 实测：1280px 视口下的半栏 / 通栏卡片宽度
  var FS = FS_MIN;                     // 每张图开画前由 setFS(W) 定，画的过程中不变
  function setFS(W) {
    var t = (W - W_NARROW) / (W_WIDE - W_NARROW);
    FS = FS_MIN + (FS_MAX - FS_MIN) * Math.max(0, Math.min(1, t));
  }
  function fscale(v) { return Math.round((v == null ? 9 : v) * FS * 100) / 100; }

  /* 「基线 → 放大」的统一模板，全文件所有受几何硬约束的字号都走它：
       base  基线字号（一个字节不动，保证退回时输出相同）
       capW  由可用宽度/格宽推出的**硬上界**，它不随 FS 长
     返回值还要经 txt() 再乘一次 FS，所以这里先除回去。
     语义：放得下就长到 base*FS，放不下就退回 base —— 永不小于基线。 */
  function fitSize(base, capW) {
    return Math.max(base, Math.min(base * FS, capW)) / FS;
  }

  /* 一段文字有多宽，以 em 计（乘上字号就是 px）。汉字与全角标点按 1 em，其余按 0.55 em。
     为什么要分开：x 轴标签在多数图上是「Jul-24」这种拉丁短串，但有的图上是
     「新台币汇率 vs 假设（升值为逆风）」这种中英混排长短语，两者每字宽度差近一倍，
     用同一个系数估，长中文标签会被严重低估、算出来的留白根本不够。
     这是**估算**不是实测 —— 实测要元素进了渲染树才行，而这里在建 SVG 之前就要用它
     定标签带高度。只用来定上界，估宽一点只会让字保守一点，不会造成越界。 */
  function emWidth(s) {
    var w = 0, k, ch;
    s = String(s == null ? '' : s);
    for (k = 0; k < s.length; k++) {
      ch = s.charCodeAt(k);
      w += (ch >= 0x2e80 && ch <= 0x9fff) || (ch >= 0xff00 && ch <= 0xffef) ||
           (ch >= 0x3000 && ch <= 0x303f) ? 1 : 0.55;
    }
    return w || 1;
  }

  /* 竖排长标签的**实测**收缩：把已经画出来的文字缩到不超过 maxLen（user 单位）。
     这里能实测（元素已经在渲染树里了），就不用 emWidth 估 —— getComputedTextLength()
     是浏览器算好的真实长度，中英混排也准。
     下界是基线字号：基线本来就放得下，没有理由缩得比基线还小。
     量不到（卡片 display:none）时什么都不做。 */
  function fitVertical(node, maxLen, baseSize) {
    var len, cur, want;
    if (!node || !(maxLen > 0)) return;
    try { len = node.getComputedTextLength(); } catch (e) { return; }
    if (!len || len <= maxLen) return;
    cur = parseFloat(node.getAttribute('font-size'));
    if (!(cur > 0)) return;
    want = Math.max(baseSize, cur * maxLen / len);
    if (want < cur) node.setAttribute('font-size', +want.toFixed(2));
  }

  /* 数值格式 —— 逐个对应 build_report.py 里的 lambda */
  function comma(v, d) {
    var s = Math.abs(v).toFixed(d), p = s.split('.');
    p[0] = p[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    return (v < 0 ? '-' : '') + p.join('.');
  }
  var FMT = {
    f1:    function (v) { return v.toFixed(1); },
    f0:    function (v) { return v.toFixed(0); },
    f0c:   function (v) { return comma(v, 0); },
    int:   function (v) { return comma(v, 0); },
    pct0:  function (v) { return v.toFixed(0) + '%'; },
    pct1:  function (v) { return v.toFixed(1) + '%'; },
    pct0z: function (v) { return (Math.abs(v) < 0.5 ? 0 : v).toFixed(0) + '%'; },
    pp0:   function (v) { return (v >= 0 ? '+' : '') + v.toFixed(0) + 'pp'; },
    pp1:   function (v) { return (v >= 0 ? '+' : '') + v.toFixed(1) + 'pp'; },
    x0:    function (v) { return v.toFixed(0) + 'X'; },
    usd0:  function (v) { return '$' + v.toFixed(0); },
    usd1:  function (v) { return '$' + v.toFixed(1); },
    usd2:  function (v) { return '$' + v.toFixed(2); },
    /* 高精度档。缺这几个的时候 fmtOf 会**静默**退回 f1，于是 $0.0719 的合约单价被印成
       $0.1、3 位小数的 RPC 掉到 1 位有效数字 —— 图还是画出来了，只是数字没了意义。
       补齐比让每个生成器各自换单位绕过去更稳妥。 */
    f2:    function (v) { return v.toFixed(2); },
    f3:    function (v) { return v.toFixed(3); },
    pct2:  function (v) { return v.toFixed(2) + '%'; },
    usd3:  function (v) { return '$' + v.toFixed(3); },
    usd4:  function (v) { return '$' + v.toFixed(4); },
  };
  var fmtOf = function (k) { return FMT[k] || FMT.f1; };

  /* 纯数字轴刻度：小数位数随步长自适应，可选千分位。
     IBKR 的 exhibit 在 build_report.py 里没有设置 y 轴格式器（Ex8 例外，显式加了
     千分位），所以轴上只有数字，单位靠轴标题与数据标签表达。此处照此还原。 */
  function plainAxis(step, useComma) {
    var d = Math.max(0, Math.min(4, -Math.floor(Math.log10(Math.abs(step) || 1)))) ;
    if (Math.abs(step - Math.round(step)) < 1e-9) d = 0;
    return function (v) {
      return useComma ? comma(v, d) : (v < 0 ? '-' : '') + Math.abs(v).toFixed(d);
    };
  }

  function el(tag, attrs, parent) {
    var n = document.createElementNS(SVG, tag), k;
    for (k in attrs) if (attrs[k] != null) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  /* o.halo：给文字加白色描边打底（paint-order 让描边画在填充下面，字形不变粗）。

     为什么需要它：这套图里的数值标签是画在绘图区**内部**的，而同一块画布上还有
     均线虚线、折线、断点竖线。均线尤其致命 —— 它按构造就落在柱子中段附近，凡是当月值
     接近 12 个月均值的月份，标签必然被一条横线拦腰划掉，数字糊成黑白相间的一团。
     两轮独立的人眼审查都把这一条列为 blocker，且同一根因还制造了十几条
     「折线划穿自己的端点标签」（IBKR Ex3/5/7、HKEX Ex3、MSCI Ex3、HOOD Ex9/16/25、TSM Ex5…）。

     描边比「把线画在标签下面」更彻底：z 序只能解决同一图元的先后，解决不了
     两个标签互相压、也解决不了标签压坐标轴刻度。 */
  function txt(parent, x, y, s, o) {
    o = o || {};
    var t = el('text', {
      x: x, y: y, fill: o.fill || C.INK, 'font-size': fscale(o.size),
      'text-anchor': o.anchor || 'middle', 'font-weight': o.weight || null,
      'font-style': o.style || null, transform: o.transform || null,
      stroke: o.halo === false ? null : C.WHITE,
      /* 描边宽度跟着字号走：字大了而描边不变，等于打底变薄，均线穿过标签又会糊。 */
      'stroke-width': o.halo === false ? null : fscale(o.halo_w || 2.4),
      'stroke-linejoin': o.halo === false ? null : 'round',
      'paint-order': o.halo === false ? null : 'stroke fill',
    }, parent);
    t.textContent = s;
    return t;
  }
  /* 文字的**渲染**外接框（user 单位）。getBBox() 不含元素自身的 transform，而这套图里
     竖排的标签（断点标签、截轴真值、x 轴月份）全是 rotate(±90 cx cy) —— 不还原的话
     拿到的是「把它横过来摆」的框，长宽正好互换，用它去判压字必然算错。
     只解析 rotate(角度 cx cy) 这一种形式：引擎里所有 transform 都是这个形式，
     多解析一种就是多一处没有调用方的死代码。量不到（卡片 display:none）时返回 null。 */
  function textRect(t) {
    var b, m;
    try { b = t.getBBox(); } catch (e) { return null; }
    if (!b || !b.width || !b.height) return null;
    m = /rotate\(\s*(-?[\d.]+)[ ,]+(-?[\d.]+)[ ,]+(-?[\d.]+)/.exec(t.getAttribute('transform') || '');
    if (!m) return { x: b.x, y: b.y, w: b.width, h: b.height };
    var a = +m[1] * Math.PI / 180, cx = +m[2], cy = +m[3],
        co = Math.cos(a), si = Math.sin(a), xs = [], ys = [], i, dx, dy,
        P = [[b.x, b.y], [b.x + b.width, b.y], [b.x + b.width, b.y + b.height], [b.x, b.y + b.height]];
    for (i = 0; i < 4; i++) {
      dx = P[i][0] - cx; dy = P[i][1] - cy;
      xs.push(cx + dx * co - dy * si); ys.push(cy + dx * si + dy * co);
    }
    return { x: Math.min.apply(null, xs), y: Math.min.apply(null, ys),
             w: Math.max.apply(null, xs) - Math.min.apply(null, xs),
             h: Math.max.apply(null, ys) - Math.min.apply(null, ys) };
  }

  function ticks(min, max, count) {
    if (!isFinite(min) || !isFinite(max)) { min = 0; max = 1; }
    if (min === max) { min -= 1; max += 1; }
    var raw = (max - min) / count;
    var mag = Math.pow(10, Math.floor(Math.log10(raw)));
    var cand = [1, 2, 2.5, 5, 10], step = null, i;   // 与 matplotlib MaxNLocator 默认 steps 相同
    for (i = 0; i < cand.length; i++) if (cand[i] * mag >= raw) { step = cand[i] * mag; break; }
    if (!step) step = 10 * mag;
    var lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step, out = [], v;
    for (v = lo; v <= hi + step / 2; v += step) out.push(Math.abs(v) < step / 1e6 ? 0 : v);
    return out;
  }

  /* ---- 双轴零点对齐（规矩：柱的基线与线的 0 必须是同一条水平线）----------
     zeroFrac：0 在该轴上的相对高度（0 = 贴画布底，1 = 贴顶）。 */
  function zeroFrac(a0, a1) {
    if (!(a1 > a0) || a0 >= 0) return 0;
    if (a1 <= 0) return 1;
    return -a0 / (a1 - a0);
  }
  /* alignZero：把 [a0,a1] 重排成「0 落在相对高度 f」。只放大不缩小 ——
     新范围写成 [-f·R, (1-f)·R]，要同时罩住原来的上下界，
     故 R = max(a1/(1-f), -a0/f)。两条轴各自这样扩一次，零点自然落在同一高度，
     且没有任何数据点被挤出画布。 */
  function alignZero(a0, a1, f) {
    if (!(f > 1e-9) || f >= 1 - 1e-9) return [a0, a1];
    var R = Math.max(Math.max(a1, 0) / (1 - f), Math.max(-a0, 0) / f);
    return [-f * R, (1 - f) * R];
  }
  /* ---- 对齐的兜底：代价过大时改为不对齐并明确标注 ----------------------
     对齐只扩不缩，所以「扩出来的那一段」按构造就是无数据区。
     浪费率 = 扩出来的量程 ÷ 对齐后的量程，两轴取大者。

     阈值 0.38 是实测定的，不是拍的。把当前 14 页 25 张双轴图的浪费率全量出来：
       0%（15 张，f=0，两轴本来就同零点 —— 含 IBKR Ex8/Ex18 与 COST Ex4，
           所以这条规矩碰不到那两个已上线的站）
       13% hood Ex15 / 14% lpla Ex11 / 17% spgi Ex5·msci Ex5·hood Ex3·hood Ex22 /
       20% hkex Ex7 / 25% msci Ex10·lpla Ex14 / 29% tsm Ex5 / 33% cme Ex7
       ── 空档 ──
       40% schw Ex11 / 44% axp Ex8 / 50% hood Ex4 / 50% hood Ex14
     33% 与 40% 之间是空的，阈值放在这段空档里对数据抖动最不敏感；
     取 0.38 而不是 0.40，是因为 schw Ex11（本规矩的起因，柱全为正却把左轴拉到 −144）
     恰好压在 40.0% 上，写成 `> 0.40` 会把起因本身漏掉。
     语义上就是任务说的「某一轴超过 40% 的量程落在无数据区」。 */
  var ALIGN_WASTE_MAX = 0.38;

  /* Catmull-Rom 平滑，端点外推方式与 build_report.py 的 smooth() 相同。

     ── bnd（可选，{lo, hi}）：插值曲线不得越过的上下界 ──────────────────────
     样条只保证过点，不保证过点之间不出界：尖峰后回落时三次段会冲过下一个数据点，
     谷底之后那一段又带着谷底那个陡负切线出发，于是**曲线**被画到数据从未到过的地方。
     yfloor/ycap 只钳数据点（见 polyline），钳不住插值出来的这段，所以非负序列会被
     画到零线以下、截轴图会把线甩出画布（实测 17 张图，最深的 LSEG Ex15 到 −112.9 GBP mn，
     ASX Ex20 到 −12,135，LPLA Ex7 反向冲到 ycap=35 之上的 211）。

     做法（三选一里挑的第三条，理由写在这里，免得以后有人以为是随手写的）：
       (a) 整体换单调保形插值（PCHIP / Fritsch–Carlson）——「数据的局部极值处切线归零」
           能根治，但那条规则对**每一个**局部极值都生效，月度数据几乎每隔一两个月就有
           一个极值，等于全站 307 条平滑曲线的形状一起变。修一张图代价是改 28 页观感，
           不划算。
       (b) 对插值结果逐点 clamp 到 [min,max] —— 改动最小，但曲线会在界上压出一段平直线，
           读者会把那段当成「连着几个月都停在最低点」的真实数据。把一个可见的错画成一个
           看不出来的错，更糟。
       (c) 只在**越界的那一段**上按比例压小两端切线（λ∈[0,1] 二分求最大可行值），
           λ=0 退化成两点之间的直线弦，必然在界内，所以一定有解；λ 记在**节点**上、
           左右两段共享，曲线仍是 C1 的（不会在数据点上折出尖角）。
     取 (c)。关键性质：**先按原式算一遍，界内就原样返回**（下面那个 early return），
     所以不出界的曲线连一次浮点运算的差别都没有 —— 全站 307 条里 290 条走这条路径，
     实测 path 的 d 属性逐字节相同。视觉回归比修得漂亮重要，这是本文件被 28 个页面
     共用的代价。
     ────────────────────────────────────────────────────────────────────── */
  function smooth(vals, n, bnd) {
    n = n || 24;
    var N = vals.length, X = [-1], Y = [vals[0] - (vals[1] - vals[0])], i, j, t, ox = [], oy = [];
    for (i = 0; i < N; i++) { X.push(i); Y.push(vals[i]); }
    X.push(N); Y.push(vals[N - 1] + (vals[N - 1] - vals[N - 2]));
    function cr(v0, v1, v2, v3, tt) {
      return 0.5 * ((2 * v1) + (-v0 + v2) * tt + (2 * v0 - 5 * v1 + 4 * v2 - v3) * tt * tt +
                    (-v0 + 3 * v1 - 3 * v2 + v3) * tt * tt * tt);
    }
    for (i = 1; i < X.length - 2; i++) {
      for (j = 0; j < n; j++) {
        t = j / n;
        ox.push(cr(X[i - 1], X[i], X[i + 1], X[i + 2], t));
        oy.push(cr(Y[i - 1], Y[i], Y[i + 1], Y[i + 2], t));
      }
    }
    ox.push(X[X.length - 2]); oy.push(Y[Y.length - 2]);
    if (!bnd) return { x: ox, y: oy };

    var lo = bnd.lo != null ? bnd.lo : -Infinity, hi = bnd.hi != null ? bnd.hi : Infinity;
    /* 容差按**数据自身的量级**取，不能按 [lo,hi] 取：单边定界时另一边是 Infinity，
       用界宽算出来的 EPS 就是 Infinity，于是「有没有越界」永远判成没有。 */
    var vmn = Infinity, vmx = -Infinity;
    for (i = 0; i < N; i++) { if (vals[i] < vmn) vmn = vals[i]; if (vals[i] > vmx) vmx = vals[i]; }
    var EPS = ((vmx - vmn) || Math.abs(vmx) || 1) * 1e-9;
    var okAll = true;
    for (i = 0; i < oy.length; i++)
      if (!(oy[i] >= lo - EPS && oy[i] <= hi + EPS)) { okAll = false; break; }
    if (okAll) return { x: ox, y: oy };       // ← 不出界的曲线在这里原样返回，下面一行都不跑

    /* 均匀节点上的 Catmull-Rom 等价于切线 m[k] = (Y[k+2]-Y[k])/2 的三次 Hermite；
       x 方向的 cr() 在等距节点上恒等于 k+t（代进去二次、三次项系数都是 0）。 */
    var m = [], k, pass;
    for (k = 0; k < N; k++) m.push((Y[k + 2] - Y[k]) / 2);
    function hval(kk, tt, m0, m1) {
      var p0 = Y[kk + 1], p1 = Y[kk + 2], t2 = tt * tt, t3 = t2 * tt;
      return (2 * t3 - 3 * t2 + 1) * p0 + (t3 - 2 * t2 + tt) * m0 +
             (-2 * t3 + 3 * t2) * p1 + (t3 - t2) * m1;
    }
    /* 只检查真正画出来的那 n 个采样点：路径是折线段连起来的，采样点在界内 ⇒ 画出来的
       线也在界内。t=0 是数据点本身（调用方保证已在界内），不用查。
       这里**不留容差**（上面那道筛才留）：留了的话「谷底 ≥ 0」就只能说成
       「谷底 ≥ −1e-6」，报出去的数字自己就先破了功。λ=0 的直弦是两端点的凸组合，
       恒在界内，所以严格判据也一定有解。 */
    function segOK(kk, m0, m1) {
      for (var q = 1; q < n; q++) {
        var v = hval(kk, q / n, m0, m1);
        if (!(v >= lo && v <= hi)) return false;
      }
      return true;
    }
    /* 二分：a 恒为已验证可行的下界（λ=0 是直弦，必可行），b 恒为不可行，返回 a。
       不假设可行域连通 —— 返回值一定是实测通过 segOK 的那个 λ。 */
    function segScale(kk, m0, m1) {
      if (segOK(kk, m0, m1)) return 1;
      var a = 0, b = 1, c;
      for (var it = 0; it < 24; it++) {
        c = (a + b) / 2;
        if (segOK(kk, c * m0, c * m1)) a = c; else b = c;
      }
      return a;
    }
    var lam = [];
    for (k = 0; k < N; k++) lam.push(1);
    /* 节点共享 λ ⇒ 压一个节点会同时改左右两段，故要迭代到不再有段越界。
       每轮只会让 λ 变小，且 λ=0 全局可行，所以必然收敛；4 轮是实测够用的上限，
       不够也不要紧——出循环后每段还会各自兜一次底。 */
    for (pass = 0; pass < 4; pass++) {
      var moved = false;
      for (k = 0; k < N - 1; k++) {
        var s = segScale(k, lam[k] * m[k], lam[k + 1] * m[k + 1]);
        if (s < 1 - 1e-9) { lam[k] *= s; lam[k + 1] *= s; moved = true; }
      }
      if (!moved) break;
    }
    ox = []; oy = [];
    for (k = 0; k < N - 1; k++) {
      var a0 = lam[k] * m[k], a1 = lam[k + 1] * m[k + 1];
      /* 兜底：迭代没收干净时对这一段单独再压一次。只有这种情况会在节点上破 C1
         （曲线仍精确过点，只是左右斜率不同），代价远小于让线跑出画布。 */
      var s2 = segScale(k, a0, a1);
      if (s2 < 1) { a0 *= s2; a1 *= s2; }
      for (j = 0; j < n; j++) { t = j / n; ox.push(k + t); oy.push(hval(k, t, a0, a1)); }
    }
    ox.push(N - 1); oy.push(vals[N - 1]);
    return { x: ox, y: oy };
  }

  /* 顶部圆角、基线端方角的柱（负值自动翻转） */
  function barPath(x, yBase, yVal, w, r) {
    var top = Math.min(yBase, yVal), h = Math.abs(yVal - yBase);
    if (h < 0.6) return 'M' + x + ' ' + top + 'h' + w;
    var rr = Math.min(r, w / 2, h);
    if (yVal <= yBase) {
      return 'M' + x + ' ' + (top + h) + 'V' + (top + rr) +
             'a' + rr + ' ' + rr + ' 0 0 1 ' + rr + ' ' + (-rr) +
             'h' + (w - 2 * rr) + 'a' + rr + ' ' + rr + ' 0 0 1 ' + rr + ' ' + rr +
             'V' + (top + h) + 'Z';
    }
    return 'M' + x + ' ' + top + 'V' + (top + h - rr) +
           'a' + rr + ' ' + rr + ' 0 0 0 ' + rr + ' ' + rr +
           'h' + (w - 2 * rr) + 'a' + rr + ' ' + rr + ' 0 0 0 ' + rr + ' ' + (-rr) +
           'V' + top + 'Z';
  }

  /* 截轴处的断口符号：两道白色斜线画在柱端，告诉读者这根柱被截过而不是到顶了 */
  function capMark(g, xc, y, w) {
    var hw = Math.min(w, 11) / 2, k, yy;
    for (k = 0; k < 2; k++) {
      yy = y + 2.4 + k * 3.2;
      el('line', { x1: xc - hw, y1: yy + 1.8, x2: xc + hw, y2: yy - 1.8,
        stroke: C.WHITE, 'stroke-width': 1.5 }, g);
    }
  }

  /* PDF 里的白底灰框圆角气泡，可带虚线箭头。
     xlo：气泡左缘的下限（绘图区左边界）。调用点只给中心点、不知道文案有多宽，
     所以钳制必须放在算出 w 之后的这里 —— 一处管住全部四个调用点。
     不钳的后果：y 轴刻度数字是 anchor:end 画在 M.l-6 的，而白底 rect 在刻度之后绘制，
     气泡一越界就把顶档刻度整个盖掉（lpla Ex10 的「3.5%」被盖 61%，只剩一个「3」）。
     触发条件纯几何：gs_bar 的气泡定位在 M.l + band*0.75，只要 w > 1.5*band + 12
     就必然伸进刻度栏 —— 25 根柱的窄卡片上 band 只有 10~21px，「-0.5pp y/y」w=74，必中。 */
  function oval(g, x, y, s, arrowTo, xlo) {
    /* 气泡是「文字的外壳」：宽高全由文案长度和字号定，所以整体随 FS 放大，
       否则 size:10 的字变大而 17px 的壳不变，字直接顶出壳外。 */
    var w = Math.max(fscale(28), s.length * fscale(6.2) + fscale(12));
    if (xlo != null && x - w / 2 < xlo) x = xlo + w / 2;
    el('rect', { x: x - w / 2, y: y - fscale(8), width: w, height: fscale(17), rx: 5,
      fill: '#fff', stroke: '#555555', 'stroke-width': 0.9 }, g);
    txt(g, x, y + fscale(3.6), s, { size: 10, style: 'italic', fill: '#000' });
    if (arrowTo) {
      el('path', { d: 'M' + (x + w / 2 + 2) + ' ' + y + 'L' + arrowTo[0] + ' ' + arrowTo[1],
        stroke: '#444444', 'stroke-width': 0.9, fill: 'none', 'stroke-dasharray': '3 2',
        'marker-end': 'url(#exArrow)' }, g);
    }
  }

  /* ────────────────────── 新图型共用的小零件 ────────────────────── */
  function isNum(v) { return v != null && isFinite(v); }

  /* qtr_bar 的末季未满时，右轴那条 y/y 一律作废。
     拿 2 个月的累计去比上年完整 3 个月，必然砸出一个 -8% 之类的假坑，而线是连续的、
     没有任何视觉提示说这一点不可比 —— 读者会当成业务塌了。柱子有浅蓝 + 图例提示，
     线没有，所以只能丢。
     在引擎侧丢而不是指望每个 build/<t>.py 传 null：这是口径错误不是排版偏好，
     漏一次就是发布一张误导图。
     范围计算、绘图、表格视图、tooltip **四处都要用它** —— 漏掉任何一处就会出现
     「图上没有但表里有」的不一致，或者右轴被一个不画出来的点撑开。 */
  /* 谁在右轴上：gs_bar 是可选的 ex.yoy（见下），其余双轴图型都是 ex.line。
     dual 判定、量程、绘图、图例、表格、tooltip 全都要认同一个来源，
     否则会出现「右轴被一个不画出来的序列撑开」这类分歧。 */
  function rhsOf(ex) {
    if (ex.kind === 'gs_bar') return (ex.yoy && ex.yoy.values) ? ex.yoy : null;
    return (ex.line && ex.line.values) ? ex.line : null;
  }
  function lineVals(ex) {
    var r = rhsOf(ex), v = r && r.values;
    if (!v || ex.kind !== 'qtr_bar') return v;
    if (isNum(ex.partial_months) && +ex.partial_months > 0 &&
        +ex.partial_months < (ex.qtr_months || 3)) {
      v = v.slice();
      v[v.length - 1] = null;
    }
    return v;
  }
  function lastFinite(a) {
    var k;
    for (k = (a || []).length - 1; k >= 0; k--) if (isNum(a[k])) return k;
    return -1;
  }

  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  function rgbOf(h) {
    return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
  }
  /* 在两个 C.* 之间线性插值。热力图必须有连续色标，但端点只许取 C.* —— 中间色是
     这两个端点的混合，不算新引入的颜色。 */
  function mix(a, b, t) {
    var A = rgbOf(a), B = rgbOf(b), o = '#', k, v;
    t = t < 0 ? 0 : (t > 1 ? 1 : t);
    for (k = 0; k < 3; k++) {
      v = Math.round(A[k] + (B[k] - A[k]) * t);
      o += (v < 16 ? '0' : '') + v.toString(16);
    }
    return o;
  }
  /* 深底上的字必须翻白，否则 RdGn 两端（RED/GREEN 亮度都只有 0.4 上下）压着深色字看不清。
     gsx 里格子字固定 #111111，那是 matplotlib 的老毛病，网页版不跟。 */
  function inkOn(hex) {
    var r = rgbOf(hex);
    return (0.299 * r[0] + 0.587 * r[1] + 0.114 * r[2]) / 255 > 0.58 ? C.INK : C.WHITE;
  }
  /* numpy.percentile 的线性插值版，用来复刻 gsx.heat_matrix 的 5/95 分位色标 */
  function pctile(sorted, p) {
    if (!sorted.length) return 0;
    var idx = (sorted.length - 1) * p, lo = Math.floor(idx), hi = Math.ceil(idx);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
  }
  function heatScale(ex) {
    var m = ex.matrix || [], fin = [], i, j, row;
    for (i = 0; i < m.length; i++) {
      row = m[i] || [];
      for (j = 0; j < row.length; j++) if (isNum(row[j])) fin.push(+row[j]);
    }
    fin.sort(function (a, b) { return a - b; });
    var lo = fin.length ? pctile(fin, 0.05) : 0;
    var hi = fin.length ? pctile(fin, 0.95) : 1;
    if (!(hi > lo)) { lo = lo - 0.5; hi = hi + 0.5; }     // 全同值：不除零，整片中性色
    var loc = ex.reverse ? C.GREEN : C.RED, hic = ex.reverse ? C.RED : C.GREEN;
    return { lo: lo, hi: hi, loc: loc, hic: hic,
      at: function (v) {
        var t = (v - lo) / (hi - lo);
        return t < 0.5 ? mix(loc, C.WHITE, t * 2) : mix(C.WHITE, hic, t * 2 - 1);
      } };
  }

  /* sRGB 相对亮度与 CIE L*。只用来排明度阶和自查对比度，不参与配色本身。 */
  function relLum(hex) {
    var r = rgbOf(hex), o = [0, 0, 0], i, c;
    for (i = 0; i < 3; i++) {
      c = r[i] / 255;
      o[i] = c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    }
    return 0.2126 * o[0] + 0.7152 * o[1] + 0.0722 * o[2];
  }
  function lstar(hex) {
    var y = relLum(hex);
    return y > 0.008856 ? 116 * Math.pow(y, 1 / 3) - 16 : 903.3 * y;
  }
  /* 在 BLUE→NAVY 这条线上取 L* 恰为 target 的颜色（L* 沿这条线单调，二分即可）。
     所有往年色都落在这条线上 ⇒ 同一色相（H≈209°→218°），只有明度在动。 */
  function blueAtL(target) {
    var lo = 0, hi = 1, mid, k;
    for (k = 0; k < 20; k++) {
      mid = (lo + hi) / 2;
      if (lstar(mix(C.BLUE, C.NAVY, mid)) > target) lo = mid; else hi = mid;
    }
    return mix(C.BLUE, C.NAVY, (lo + hi) / 2);
  }
  /* ── year_lines 的年份配色 ──────────────────────────────────────────────
     往年一律走同一色相的**等间距明度阶**，越早越淡；当年红色加粗高亮。

     原来的阶梯是 [mix(GRAY,WHITE,.5)=#D3D3D3, mix(BLUE,WHITE,.45)=#C4DBEF,
     BLUE, MBLUE, NAVY]，两个浅端对白底的对比度只有 1.31:1 与 1.55:1 —— 而网格线
     #E3E3E3 本身就有 1.28:1，也就是说最早那一年**比网格线还淡**，
     旁边两条又只差 0.24 个对比度档，2021/2022/2023 三条在图上完全分不开
     （msci Ex9、schw Ex16/17、axp Ex14/16、lpla Ex18、hkex Ex16 都报了这一条）。
     逐年对比是这类图唯一的用途，颜色分不开等于这张图没画。

     现在的两条端点：最浅 = C.BLUE（对白底 1.85:1，是网格线 1.28:1 的 1.44 倍，
     压得住网格），最深 = C.NAVY（15.6:1）。中间按 **CIE L\*** 等分而不是按 RGB 等分：
     sRGB 是 gamma 编码的，同样的 RGB 步长在浅端的明度差要小得多，
     原来那种「兑白 45%」式的浅端正是这么挤到一起的。
     L\* 跨度 77.2 → 23.8：5 条往年线每档差 13.4、7 条差 8.9，都在细线也认得出的范围。

     STEP_MAX：往年线只有两三条时把步长封顶，别一上来就跳到 NAVY ——
     否则最近那条往年线比当年的红线（L\*≈42.7）还重，梯度反了（spgi Ex6 报过）。

     draw / seriesRows / legendHTML 三处必须拿到同一组颜色，所以抽出来。 */
  var YR_L_LIGHT = lstar(C.BLUE);      // 77.2
  var YR_L_DARK = lstar(C.NAVY);       // 23.8
  var YR_STEP_MAX = 16;                // 单档最大明度间隔（L*）
  function yearRamp(m) {
    var out = [], step, j;
    if (m <= 0) return out;
    if (m === 1) return [blueAtL((YR_L_LIGHT + YR_L_DARK) / 2)];   // 只有一条往年线：取中档
    step = Math.min(YR_STEP_MAX, (YR_L_LIGHT - YR_L_DARK) / (m - 1));
    for (j = 0; j < m; j++) out.push(blueAtL(YR_L_LIGHT - step * j));
    return out;
  }
  function yearColors(ex) {
    var ser = ex.series || [], nS = ser.length;
    var hl = ex.highlight != null ? +ex.highlight : nS - 1, k, m = 0;
    /* 阶梯只按「真正要自动配色的往年线」条数分档：payload 指定了颜色的、
       以及当年那条红线，都不占阶梯的位置，否则 6 年图与 8 年图的浅端会对不上。 */
    for (k = 0; k < nS; k++) if (k !== hl && !ser[k].color) m++;
    var ramp = yearRamp(m), out = [], j = 0;
    for (k = 0; k < nS; k++) {
      if (ser[k].color) { out.push(col(ser[k].color)); continue; }
      if (k === hl) { out.push(C.RED); continue; }
      out.push(ramp[j++]);
    }
    return out;
  }

  function stackLen(ex) {
    var L = 0, k, st = ex.stacks || [];
    for (k = 0; k < st.length; k++) L = Math.max(L, (st[k].values || []).length);
    return L;
  }
  /* 桥的净额：口径上应由 Python 给（ex.net），没给才在这里按恒等式求和 */
  function bridgeNet(ex, n) {
    if (ex.net && ex.net.values) return ex.net.values;
    var out = [], i, s, t, any, v;
    for (i = 0; i < n; i++) {
      t = 0; any = false;
      for (s = 0; s < ex.stacks.length; s++) {
        v = ex.stacks[s].values[i];
        if (isNum(v)) { t += v; any = true; }
      }
      out.push(any ? t : null);
    }
    return out;
  }

  function diamond(g, x, y, r, fill, stroke, sw) {
    el('path', { d: 'M' + x.toFixed(2) + ' ' + (y - r).toFixed(2) +
      'L' + (x + r).toFixed(2) + ' ' + y.toFixed(2) +
      'L' + x.toFixed(2) + ' ' + (y + r).toFixed(2) +
      'L' + (x - r).toFixed(2) + ' ' + y.toFixed(2) + 'Z',
      fill: fill, stroke: stroke || null, 'stroke-width': sw || null }, g);
  }

  /* 把 tooltip 定位到某个画布 x（与 draw() 里的逻辑一致，heat_matrix 也要用） */
  function placeTip(tip, host, xInSvg, W) {
    var tw = tip.offsetWidth, px = xInSvg / W * host.clientWidth;
    tip.style.left = Math.max(2, Math.min(host.clientWidth - tw - 2, px - tw / 2)) + 'px';
    tip.style.top = '0px';
  }

  /* ───────────── heat_matrix：行=年、列=月的热力矩阵（gsx.heat_matrix）─────────────
     它不吃 band/y 轴那一整套，所以在 draw() 里提前分流，自己排版。
     色标取 5/95 分位：一两个离群月不该把整张表压成一片白。 */
  function drawHeat(host, ex, W) {
    setFS(W);
    var rows = ex.rows || [], cols = ex.cols || MONTHS, m = ex.matrix || [];
    if (!rows.length || !cols.length) { host.innerHTML = '<p class="note">无数据</p>'; return; }
    var fmt = fmtOf(ex.fmt || 'f1'), i, j, v;
    /* 行标签列、底部月份带、格高都是「装文字的盒子」，随 FS 放大；
       格宽 cw 是**硬约束** —— 它 = 卡片宽度 ÷ 列数，列数由数据定（12 或 24 个月），
       放不宽。所以格内数字与列标签的字号只能在 cw 允许的范围里长，见下面两处 capW。 */
    var M = { t: 3, r: 6, b: fscale(15), l: fscale(ex.row_lab_w || 32) };
    var pw = Math.max(60, W - M.l - M.r), cw = pw / cols.length;
    var chh0 = Math.max(13, Math.min(26, ex.cell_h || 19));   // 基线格高，算基线字号要用
    var chh = fscale(chh0);
    var ph = rows.length * chh, H = M.t + ph + M.b;
    var svg = el('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img',
      'aria-label': 'Exhibit ' + ex.n + ': ' + ex.title }, host);
    var g = el('g', {}, svg), sc = heatScale(ex);
    var maxLen = 1;
    for (i = 0; i < rows.length; i++)
      for (j = 0; j < cols.length; j++) {
        v = (m[i] || [])[j];
        if (isNum(v)) maxLen = Math.max(maxLen, fmt(+v).length);
      }
    /* 字号按格宽收缩：半栏 12 列时一格只有 ~38px，宁可字小也不能让数字压出格子。
       走 fitSize 模板 —— capW 是格宽给的硬上界（cw = 卡片宽 ÷ 列数，放不宽）。 */
    var fs = fitSize(Math.max(4.6, Math.min(9, (cw - 5) / (maxLen * 0.58), chh0 * 0.52)),
                     (cw - 5) / (maxLen * 0.58));
    var tip = host.parentElement ? host.parentElement.querySelector('.tip') : null;
    var name = ex.legend || ex.ylab || '数值', pf = precise(fmt);

    for (i = 0; i < rows.length; i++) {
      for (j = 0; j < cols.length; j++) {
        v = (m[i] || [])[j];
        var ok = isNum(v), x = M.l + j * cw, y = M.t + i * chh;
        var fc = ok ? sc.at(+v) : C.GRID;
        var rc = el('rect', { x: x.toFixed(2), y: y.toFixed(2), width: cw.toFixed(2),
          height: chh, fill: fc, stroke: C.WHITE, 'stroke-width': 1.1 }, g);
        /* halo:false 是必须的，不是省事 —— txt() 默认给每个字加 2.4px 的**白色**描边，
           而深色格子上 inkOn() 返回的字色也是白的：白字 + 白描边在 4.6–9px 的字号上
           把笔画糊成一团白斑，颜色越深的格子（也就是最该被读到的极值）越读不出来。
           格子本身是实心色块，底下没有网格线要挡，描边在这里没有任何作用。 */
        if (ok) txt(g, x + cw / 2, y + chh / 2 + fs * 0.35, fmt(+v),
          { size: +fs.toFixed(2), fill: inkOn(fc), halo: false });
        if (tip) (function (node, head, val, sw, cx) {
          node.setAttribute('style', 'cursor:crosshair');
          node.addEventListener('mouseenter', function () {
            tip.innerHTML = '<div class="th">' + head + '</div><div class="row"><i style="background:' +
              sw + '"></i><span>' + name + '</span><b>' +
              (val == null ? '—' : pf(val)) + '</b></div>';
            tip.style.opacity = 1;
            placeTip(tip, host, cx, W);
          });
        }(rc, rows[i] + ' · ' + cols[j], ok ? +v : null, fc, x + cw / 2));
      }
      txt(g, M.l - 5, M.t + i * chh + chh / 2 + fscale(3), rows[i], { size: 8, anchor: 'end' });
    }
    /* 列标签同一个模板。注意 capW 必须按**最长列名的字数**算：原来的 cw/3.4 是照
       3 个字的月名（Jan/Feb）定的经验值，24 列的「Aug-24」有 6 个字，基线上是靠
       风格上界 8 挡住的 —— 风格上界一随 FS 抬高，就没人挡了（实测这一条自己贡献了
       全站 184 条 TEXT_OVERLAP）。 */
    var cmax = 1;
    for (j = 0; j < cols.length; j++) cmax = Math.max(cmax, String(cols[j]).length);
    var cfs = fitSize(Math.max(5, Math.min(8, cw / 3.4)), (cw - 2) / (cmax * 0.56));
    for (j = 0; j < cols.length; j++)
      txt(g, M.l + (j + 0.5) * cw, M.t + ph + fscale(11), cols[j], { size: +cfs.toFixed(2) });
    if (tip) g.addEventListener('mouseleave', function () { tip.style.opacity = 0; });
  }

  function draw(host, ex, opt) {
    host.innerHTML = '';
    opt = opt || {};
    var W = host.clientWidth || 520, i, s;
    if (ex.kind === 'heat_matrix') { drawHeat(host, ex, W); return; }
    setFS(W);                          // 字号档位只跟画布宽度有关，先定下来再排版
    var labels = ex.xlabels || opt.xlabels || [], n = labels.length;
    if (!n) { host.innerHTML = '<p class="note">无数据</p>'; return; }
    var kind = ex.kind;
    /* x 标签角度：COST 月份标签 90°、IBKR 月份标签 45°、COST Ex12 年份水平（同 PDF）。
       year_lines 的 x 是 Jan..Dec 十二格，PDF 里是水平标的，默认跟着走。 */
    var rot = ex.xrot != null ? ex.xrot : (kind === 'year_lines' ? 0 : (n > 20 ? 90 : 45));
    /* x 标签带：90° 时带高 = 标签**文字长度**，45° 是它的斜边投影，0° 只是一个行高 ——
       三种都正比于字号，所以整条按 FS 缩放。 */
    var XB = fscale(rot === 90 ? 48 : (rot === 0 ? 22 : 36));
    /* 但 48/36/22 是照「Jul-24」这种 3~4 个拉丁字符的月份标签定的常数。x 轴是**长短语**
       时（「新台币汇率 vs 假设（升值为逆风）」20+ em）标签远比这个带高，多出来的部分
       会伸出卡片、盖在下面的 Note / Source 正文上 —— 这不是重叠，是跑到别人的地盘上。
       所以按最长标签反算一次需要的带高，**只增不减**：月份标签的图算出来比常数小，
       走 max 之后一个像素都不变；只有长标签的图会把带子撑开到真正够用。 */
    var xstep = ex.xstep || 1, xlEm = 1;
    for (i = 0; i < n; i += xstep)
      if (labels[i] != null) xlEm = Math.max(xlEm, emWidth(labels[i]));
    if (rot !== 0)
      XB = Math.max(XB, xlEm * fscale(8.2) * (rot === 90 ? 1 : 0.707) + fscale(10));
    /* 新图型里 qtr_bar / grouped_bars 的右轴（y/y、误差）是可选的：payload 没给 ex.line
       就退化成单轴柱图，不画空的右刻度。gs_bar 的 ex.yoy 同理（默认不给 = 维持现状）。 */
    var dual = kind === 'bar_line_dual' || kind === 'stacked_dual' ||
               ((kind === 'qtr_bar' || kind === 'grouped_bars' || kind === 'gs_bar') && !!rhsOf(ex));
    var perPointLabels = kind === 'gs_bar' || kind === 'gs_line' || kind === 'gs_line_avg' ||
                         kind === 'stacked_dual' || kind === 'lines_endlabels' ||
                         kind === 'qtr_bar' || kind === 'seasonality' || kind === 'bridge_bar' ||
                         kind === 'grouped_bars' || kind === 'range_band' || kind === 'year_lines';
    /* 绘图区高度（ph）跟字号无关，但**逐点标签**是竖着排在数据点上方的，字大了就要
       多留一点，否则 spreadY 会把整列往下压、末点标签贴着轴走。只给带逐点标签的图型
       按 FS 补一次高，不带的（纯折线/柱）维持原高，免得一整页凭空长高。 */
    var H = (opt.height || (perPointLabels ? 268 : 248)) +
            (perPointLabels ? Math.round(26 * (FS - 1)) : 0) + XB;
    /* 截轴时真值标注竖排在图顶之上，顶边距要留够一行竖排文字（约 22px）；
       右轴有标题时右边距要在刻度数字之外再让出一列。
       ── 这四个数全是「为放某段文字留的空」，一律随 FS 缩放：
          t 是一行竖排真值、r 是刻度数字（+ 可选轴标题）、b 是 x 标签带（已缩过）、
          l 是刻度数字（+ 可选轴标题 + lines_endlabels 的左端标签列）。
          M.r 的 14 与 M.l 的基数留的是「半个刻度数字的溢出」，同样正比于字号。 */
    var capOn = ex.ycap != null || ex.yfloor != null;
    var M = { t: fscale(capOn ? 30 : 14),
              r: fscale(dual ? (ex.ylab2 ? 56 : 42)
                      : (kind === 'lines_endlabels' || kind === 'gs_line_avg' ||
                         kind === 'year_lines' ? 42 : 14)),
              b: XB,
              /* lines_endlabels 的左端标签要有自己的一列：不加这 30px 就只能挤在
                 Xc(0)-7，正好压在 y 轴刻度栏上（右端早就有 42px 的专列了）。 */
              l: fscale((ex.ylab ? 56 : 46) + (kind === 'lines_endlabels' ? 30 : 0)) };
    var pw = Math.max(60, W - M.l - M.r), ph = Math.max(80, H - M.t - M.b);

    var svg = el('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img',
      'aria-label': 'Exhibit ' + ex.n + ': ' + ex.title }, host);
    var defs = el('defs', {}, svg);
    var mk = el('marker', { id: 'exArrow', viewBox: '0 0 10 10', refX: 8, refY: 5,
      markerWidth: 5, markerHeight: 5, orient: 'auto-start-reverse' }, defs);
    el('path', { d: 'M0 1L9 5L0 9z', fill: '#444444' }, mk);

    /* 斜纹填充：给「与相邻柱不可比」的柱用（如 53 周财年多出一周的月份）。
       pattern 里塞的是该图自己的柱色，所以 id 必须一图一个，不能共用。 */
    /* 右轴刻度文字与「优先标签」（次轴 y/y 的末点读数）。
       末点读数按构造落在它自己那个值的轴高度上，而右轴刻度也在同一列 ——
       两者数值一接近就必然叠字（实测 6 页 18 处：'+5.0pp × +5.1pp'、'50% × 52%'…）。
       末点读数是真实数据、刻度只是标尺，冲突时让刻度让位（见 draw 末尾的 dropClashingTicks）。 */
    var rtickEls = [], priorityLabs = [], brks = [];

    var markSet = null, hatchId = null;
    if (ex.bar_marks && ex.bar_marks.length) {
      markSet = {};
      for (i = 0; i < ex.bar_marks.length; i++) markSet[ex.bar_marks[i]] = 1;
      hatchId = 'exHatch' + (++uid);
      var pat = el('pattern', { id: hatchId, width: 5, height: 5,
        patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' }, defs);
      // 底色必须跟本图柱色一致，否则斜纹柱会整根变色、看着像另一个系列。
      // gs_bar 没有 ex.bar 且柱子固定是 BLUE，不能退成 NAVY。
      el('rect', { width: 5, height: 5,
        fill: (ex.bar && ex.bar.color) ? col(ex.bar.color)
                                       : (kind === 'gs_bar' ? C.BLUE : C.NAVY) }, pat);
      el('line', { x1: 0, y1: 0, x2: 0, y2: 5, stroke: C.WHITE, 'stroke-width': 1.8 }, pat);
    }

    var band = pw / n;
    var Xc = function (k) { return M.l + band * (k + 0.5); };

    /* 左轴参与计算的值 */
    var lv = [];
    if (kind === 'bar_line') lv = ex.bar.values.concat(ex.line.values);
    else if (kind === 'bar_line_dual') lv = ex.bar.values.slice();
    else if (kind === 'lines' || kind === 'lines_endlabels' || kind === 'year_lines') {
      for (s = 0; s < ex.series.length; s++) lv = lv.concat(ex.series[s].values);
    } else if (kind === 'seasonality') {
      lv = (ex.base.values || []).concat(ex.actual.values || []);
    } else if (kind === 'grouped_bars') {
      for (s = 0; s < ex.groups.length; s++) lv = lv.concat(ex.groups[s].values);
    } else if (kind === 'range_band') {
      lv = (ex.lo || []).concat(ex.hi || [], ex.actual || []);
      if (isNum(ex.qtd)) lv.push(ex.qtd);
    } else if (kind === 'bridge_bar') {
      /* 桥的纵轴要罩住「正向堆到哪」「负向堆到哪」两条包络，不是单项的最值 */
      var bp_, bn_, bv_;
      for (i = 0; i < n; i++) {
        bp_ = 0; bn_ = 0;
        for (s = 0; s < ex.stacks.length; s++) {
          bv_ = ex.stacks[s].values[i];
          if (!isNum(bv_)) continue;
          if (bv_ >= 0) bp_ += bv_; else bn_ += bv_;
        }
        lv.push(bp_); lv.push(bn_);
      }
      lv = lv.concat(bridgeNet(ex, n));
    } else if (kind === 'stacked_dual') {
      for (i = 0; i < n; i++) {
        var tot = 0;
        for (s = 0; s < ex.stacks.length; s++) tot += ex.stacks[s].values[i] || 0;
        lv.push(tot);
      }
    } else lv = ex.values.slice();

    var clean = lv.filter(function (v) { return v != null && isFinite(v); });
    if (!clean.length) { host.innerHTML = '<p class="note">无数据</p>'; return; }
    var mn = Math.min.apply(null, clean), mx = Math.max.apply(null, clean);
    var avg = ex.avg12, y0, y1, tk;
    var hasBar = kind === 'bar_line' || kind === 'bar_line_dual' || kind === 'diverging_bars' ||
                 kind === 'bars_labeled';

    /* 柱状图的 ylim 与 PDF 一致（0 .. max×倍数），刻度算在 ylim 上而非数据最大值上
       —— matplotlib 的 locator 作用于最终 ylim，算在 max 上会得到两倍密度的刻度。
       各分支只定 y0/y1，刻度统一放到截轴、对零点之后再算。 */
    if (kind === 'gs_bar') { y0 = 0; y1 = mx * 1.22; }
    else if (kind === 'stacked_dual') { y0 = 0; y1 = mx * 1.28; }
    else if (kind === 'bars_labeled') { y0 = 0; y1 = mx * 1.13; }
    /* 以下四个与 gsx.py 同名函数的 set_ylim 一一对应（qtr_bar 的 1.32 是给竖排标签留的） */
    else if (kind === 'qtr_bar') { y0 = Math.min(0, mn * 1.15); y1 = mx * 1.32; }
    else if (kind === 'seasonality') { y0 = Math.min(0, mn * 1.15); y1 = mx * 1.26; }
    else if (kind === 'grouped_bars') { y0 = Math.min(0, mn * 1.15); y1 = mx * 1.22; }
    else if (kind === 'bridge_bar') {
      var bpad = (mx - mn) * 0.16 || 1; y0 = mn - bpad; y1 = mx + bpad;
    } else if (kind === 'range_band') {
      /* gsx 用 min*0.88 / max*1.10 的乘法留白；那在负值上会往零点缩（越界画到画布外），
         所以只在整段非负时照抄，含负值时改成按极差加白。 */
      if (mn >= 0) { y0 = mn * 0.88; y1 = mx * 1.10; }
      else { var rr0 = (mx - mn) || 1; y0 = mn - rr0 * 0.12; y1 = mx + rr0 * 0.10; }
    }
    else if (kind === 'gs_line' || kind === 'gs_line_avg') {
      if (avg != null) { mn = Math.min(mn, avg); mx = Math.max(mx, avg); }
      var rr = (mx - mn) || 1, pd = kind === 'gs_line_avg' ? 0.35 : 0.30;
      y0 = mn - rr * pd; y1 = mx + rr * pd;
    } else if (kind === 'lines_endlabels') {
      var r2 = (mx - mn) || 1; y0 = mn - r2 * 0.20; y1 = mx + r2 * 0.18;
    } else {
      /* COST 的 exhibit 在 PDF 里走 matplotlib 默认 autoscale：数据范围 ±5% 留白，
         再画落在范围内的刻度（不把轴对齐到刻度边界，否则会多出上下各一档）。
         柱状图从 0 起，含 axhline(0) 的线图（Ex9）也要把 0 纳入数据域。 */
      var incZero = hasBar || !!ex.zero_line;
      var dmn = incZero ? Math.min(mn, 0) : mn;
      var dmx = incZero ? Math.max(mx, 0) : mx;
      var rg = (dmx - dmn) || 1;
      if (ex.zero_base) {
        /* zero_base ← gsx.long_line 的 ax.set_ylim(0, max*1.16)。
           kind:'lines' 落进本分支时用的是 y0 = dmn - rg*0.05，那是一次**没有任何标注的
           隐性截轴** —— 与本仓「截轴必须标注」的规矩正相反，而且长历史图上没有零基线
           就等于把增长幅度凭空放大（LPLA Ex17 实测被放大约 2.5 倍，Ex8 同样；
           SCHW Ex7/10/14/15、HKEX Ex4/14/15、CBOE Ex6 都是同一个根因）。

           但**不全局强制**：这里只在 payload 显式给了 zero_base 时才归零，且序列有负值时
           下界照常留在数据之下 —— 把负值硬压到零线以上是删点，比隐性截轴更糟
           （SCHW Ex14 的负增长月必须还能画到零线以下）。 */
        var rz = (mx - mn) || Math.abs(mx) || 1;
        y0 = mn < 0 ? mn - rz * 0.08 : 0;
        y1 = mx > 0 ? mx * 1.16 : rz * 0.08;
      } else {
        /* 有柱的图 y0 不能因为 5% 留白掉到 0 以下：那样柱的基线 Y(0) 会浮在画布底
           上方几像素，而右轴的 0 在底边，图上唯一那条零线就骗人了（实测 Ex3 里
           y/y < 1.59% 的三个正增长月被画到零线下方）。数据本身有负值时照常留白。 */
        y0 = (hasBar && dmn >= 0) ? 0 : dmn - rg * 0.05;
        y1 = dmx + rg * 0.05;
      }
    }

    /* 截轴（规矩 7）：离群值只截轴、不删点，超界的柱/点后面单独标真值。 */
    if (ex.ycap != null) y1 = ex.ycap;
    if (ex.yfloor != null) y0 = ex.yfloor;

    var Y = function (v) { return M.t + ph - ((v - y0) / (y1 - y0)) * ph; };

    /* 右轴范围先算出来，好在画任何东西之前跟左轴对齐零点 */
    var r0 = null, r1 = null, rtk = null, rc = null, misalign = false;
    if (dual) {
      rc = rhsOf(ex);
      /* 用 lineVals()：被作废的未满季 y/y 不能参与右轴量程，否则轴被一个根本不画出来的
         点撑开（实测会把 0~15% 的轴拉成 -10%~15%，整条线压扁在上半幅）。 */
      var rv = lineVals(ex).filter(function (v) { return v != null && isFinite(v); });
      if (kind === 'stacked_dual') { rtk = ticks(0, rc.ymax || 60, 6); r0 = 0; r1 = rtk[rtk.length - 1]; }
      else {
        rtk = ticks(Math.min.apply(null, rv.concat([0])), Math.max.apply(null, rv), 9);
        r0 = rtk[0]; r1 = rtk[rtk.length - 1];
      }
      /* 两轴的 0 必须落在同一画布高度：取两者中较高的那个零点比例 f，
         再让两条轴各自向下扩量程去凑（只扩不缩，数据点一个都不会被挤出去）。
         左右都不含负值时 f = 0，走的还是老路径，不影响既有图。

         兜底见 ALIGN_WASTE_MAX：对齐的代价过大时宁可不对齐，但必须在图上说出来
         —— 读者的默认假设就是两轴零点同高，不说的话「柱在零线之上、点在零线之下」
         会被读成同号。 */
      var f = Math.max(zeroFrac(y0, y1), zeroFrac(r0, r1));
      if (f > 1e-9) {
        var la = alignZero(y0, y1, f), ra = alignZero(r0, r1, f);
        var waste = Math.max(1 - (y1 - y0) / (la[1] - la[0]),
                             1 - (r1 - r0) / (ra[1] - ra[0]));
        if (waste > ALIGN_WASTE_MAX) {
          misalign = true;            // 两轴各自缩放，下面画一行说明
        } else {
          y0 = la[0]; y1 = la[1];
          r0 = ra[0]; r1 = ra[1];
          rtk = ticks(r0, r1, 9);     // 量程动过，右轴刻度要重算
        }
      }
    }

    tk = ticks(y0, y1, 9);   // 截轴 / 对零点之后才算刻度，否则刻度会跑到 cap 之外
    /* COST 的 exhibit 在 PDF 里显式设了轴格式器（%、$、pp），故用 yfmt；
       IBKR 的没设，轴为纯数字（Ex8 带千分位）。 */
    var tstep = tk.length > 1 ? tk[1] - tk[0] : 1;
    var yfKey = ex.yfmt || (ex.bar && ex.bar.yfmt);          // 双轴图的左轴格式在 bar 上
    var yf = yfKey ? fmtOf(yfKey) : plainAxis(tstep, kind === 'stacked_dual');

    var tickW = 0;
    for (i = 0; i < tk.length; i++) {
      if (tk[i] < y0 - 1e-9 || tk[i] > y1 + 1e-9) continue;
      el('line', { x1: M.l, x2: M.l + pw, y1: Y(tk[i]), y2: Y(tk[i]), stroke: C.GRID, 'stroke-width': 1 }, svg);
      var tkn = txt(svg, M.l - fscale(6), Y(tk[i]) + fscale(3.2), yf(tk[i]), { size: 9, anchor: 'end' });
      /* 打个标记给 tools/visual_qa.py 认轴刻度。原先它靠「font-size == 9」筛，
         而字号现在按卡片宽度变，没有一个固定的数可筛了 —— 而且那种筛法失效的表现
         是整节静默漏报，不是报错。属性是显式契约，改字号不会把它弄丢。 */
      tkn.setAttribute('data-tick', 'l');
      try { tickW = Math.max(tickW, tkn.getComputedTextLength()); } catch (e) { }
    }
    if (y0 < -1e-9 && y1 > 1e-9)
      el('line', { x1: M.l, x2: M.l + pw, y1: Y(0), y2: Y(0), stroke: C.AXIS, 'stroke-width': 0.9 }, svg);

    var step = xstep;
    /* x 标签的字号上界 —— 两条约束取严的那条（xlEm 在上面算 XB 时已求过，不重复扫）：

       轴向：相邻两个标签不许互压。竖排只占一个行高（与文字长度无关），横排要整条塞进
             一格，45° 占的是斜边投影。exchanges12 的 x 是交易所名（「Deutsche Börse」
             14 字），基线字号下差之毫厘躲过去了，一放大就实打实压 94px。

       纵深：标签不许伸出标签带 XB。月份标签上从不触发（「Jul-24」才 3.3 em），但 x 是
             长中文短语时（「新台币汇率 vs 假设（升值为逆风）」20+ em）它是唯一挡得住
             的约束 —— 伸出去就直接盖在卡片下面的 Note / Source 正文上。

       两条都是几何硬约束，不随 FS 长。 */
    var xlCapAxis = rot === 90 ? band / 1.15 : (rot === 0 ? band : band * 1.414) / xlEm;
    var xlCapDepth = rot === 0 ? Infinity : (rot === 90 ? XB : XB * 1.414) / xlEm;
    var xlfs = fitSize(8.2, Math.min(xlCapAxis, xlCapDepth));
    for (i = 0; i < n; i++) {
      if (i % step) continue;
      var xx = Xc(i), yy = M.t + ph + fscale(rot === 0 ? 13 : 9);
      txt(svg, xx, yy, labels[i], { size: +xlfs.toFixed(2), anchor: rot === 0 ? 'middle' : 'end',
        transform: rot === 0 ? null : 'rotate(' + (-rot) + ' ' + xx + ' ' + yy + ')' });
    }

    /* 右轴刻度（范围与零点对齐在上面已经定好） */
    var Y2 = null;
    if (dual) {
      Y2 = function (v) { return M.t + ph - ((v - r0) / (r1 - r0)) * ph; };
      var rf = fmtOf(rc.yfmt || 'pct0');
      /* 右轴刻度跟序列同色：gs_bar 的柱是浅蓝、y/y 线是金色，两套刻度都是黑字的话
         「哪一列刻度归谁」只能靠位置猜。既有图型的刻度保持黑字，不动已上线的两个站。 */
      var rtc = (kind === 'gs_bar') ? col(rc.color || 'GOLD') : C.INK;
      for (i = 0; i < rtk.length; i++) {
        if (rtk[i] < r0 - 1e-9 || rtk[i] > r1 + 1e-9) continue;   // 对齐后量程会窄于刻度序列
        var rtkn = txt(svg, M.l + pw + fscale(6), Y2(rtk[i]) + fscale(3.2), rf(rtk[i]),
          { size: 9, anchor: 'start', fill: rtc });
        rtkn.setAttribute('data-tick', 'r');          // 同左轴，见上面的说明
        rtickEls.push(rtkn);
      }
      /* 右轴标题：否则「哪条系列读右轴」全靠 legend 里「(RHS)」三个字 */
      if (ex.ylab2) {
        var cy2 = M.t + ph / 2, xr = W - fscale(11);
        txt(svg, xr, cy2, ex.ylab2, { size: 8.4, transform: 'rotate(90 ' + xr + ' ' + cy2 + ')' });
      }
    }

    var g = el('g', {}, svg);
    var BW = function (frac) { return Math.max(1.5, Math.min(band * frac, band - 1.5)); };

    /* 截轴后的真值标注一律竖排：被截的往往是连着几个月（COVID 低基数），
       横排标签在 band 只有几像素宽的图上必然叠成一团。 */
    var capFmt = fmtOf(ex.label_fmt || yfKey || ex.fmt || 'f1');
    /* 被截的点常常挨在一起（同一个月的柱和线都超界、或连着几个月的低基数尖峰），
       竖排字宽约 8px，比 band 还宽，所以要占位排开；只向右挪，仍紧贴各自的柱。 */
    var capSlots = [];
    function capSlot(x) {
      var moved = true, k;
      while (moved) {
        moved = false;
        for (k = 0; k < capSlots.length; k++)
          if (Math.abs(capSlots[k] - x) < 8) { x = capSlots[k] + 8; moved = true; break; }
      }
      capSlots.push(x);
      return x;
    }
    function capLabel(x, over, s) {
      /* over=true 标在图顶之上（M.t 已为此留位），false 标在图内贴底 */
      var yy = over ? M.t - 3 : M.t + ph - 3;
      x = capSlot(x);
      txt(g, x, yy, s, { size: 7.2, fill: BREAK, anchor: 'start',
        transform: 'rotate(-90 ' + x + ' ' + yy + ')' });
    }

    function polyline(vals, color, lw, doSmooth, markers, yfn) {
      yfn = yfn || Y;
      var d = '', pen = false, pts = [], out = [], vs = vals;
      /* 只有左轴参与截轴；超界的点钳到边界画空心圈 + 真值，绝不丢点（规矩 7） */
      if (yfn === Y && capOn) {
        vs = vals.map(function (v, k) {
          if (v == null || !isFinite(v)) return v;
          if (ex.ycap != null && v > y1) { out.push([k, v, y1, true]); return y1; }
          if (ex.yfloor != null && v < y0) { out.push([k, v, y0, false]); return y0; }
          return v;
        });
      }
      if (doSmooth) {
        /* ── 平滑曲线的上下界（见 smooth() 头部的长注释）──
           两条来源，都只是把**已经对数据点生效的规矩**同样加到插值曲线上：
             1) 非负序列不得画到零线以下。窗口里全部 ≥ 0 的量（家数、募资额、份额%）
                被样条甩到负数，是画出了一个数据里根本不存在的值 —— 与「截轴不删点」
                同一条底线：图上只能出现真值。
             2) 显式给了 yfloor / ycap 的图，曲线与数据点同受那条边界约束。上面那段
                map() 只钳了点，曲线照样能穿过去（LPLA Ex7 的线冲到 ycap=35 之上的
                211，直接画进标题区）。
           序列里有 null / NaN 时一律不设界：那种情况下样条本来就产出 NaN（既有行为），
           不在这次改动的范围里，宁可保持原样也不要顺手改出第二处差异。 */
        var blo = -Infinity, bhi = Infinity, bfin = true, bmn = Infinity, bi;
        for (bi = 0; bi < vs.length; bi++) {
          if (!isNum(vs[bi])) { bfin = false; break; }
          if (vs[bi] < bmn) bmn = vs[bi];
        }
        if (bfin && vs.length > 1) {
          if (bmn >= 0) blo = 0;
          if (yfn === Y) {                       // 截轴只作用于左轴，与上面的 map() 一致
            if (ex.yfloor != null && y0 > blo) blo = y0;
            if (ex.ycap != null) bhi = y1;
          }
        }
        var sm = smooth(vs, 24,
          (blo > -Infinity || bhi < Infinity) ? { lo: blo, hi: bhi } : null);
        for (i = 0; i < sm.x.length; i++)
          d += (i ? 'L' : 'M') + (M.l + band * (sm.x[i] + 0.5)).toFixed(2) + ' ' + yfn(sm.y[i]).toFixed(2);
      } else {
        for (i = 0; i < vs.length; i++) {
          if (vs[i] == null || !isFinite(vs[i])) { pen = false; continue; }
          d += (pen ? 'L' : 'M') + Xc(i).toFixed(2) + ' ' + yfn(vs[i]).toFixed(2);
          pen = true; pts.push([Xc(i), yfn(vs[i])]);
        }
      }
      el('path', { d: d, fill: 'none', stroke: color, 'stroke-width': lw,
        'stroke-linejoin': 'round', 'stroke-linecap': 'round' }, g);
      if (markers) for (i = 0; i < pts.length; i++)
        el('circle', { cx: pts[i][0], cy: pts[i][1], r: 2.1, fill: color }, g);
      for (i = 0; i < out.length; i++) {
        el('circle', { cx: Xc(out[i][0]), cy: yfn(out[i][2]), r: 2.6, fill: C.WHITE,
          stroke: BREAK, 'stroke-width': 1.1 }, g);
        capLabel(Xc(out[i][0]) + 3.4, out[i][3], capFmt(out[i][1]));
      }
    }

    /* ── 新图型共用：截轴不删点的柱与点 ──
       与上面 bar_line 分支里那段内联逻辑同规矩（超界画到边界 + 断口符号 + 真值竖排），
       抽成函数是因为新图型里同一张图要画好几组柱（配对柱、并排柱、区间带）。 */
    function clampY(v) {
      if (ex.ycap != null && v > y1) return y1;
      if (ex.yfloor != null && v < y0) return y0;
      return v;
    }
    function capBar(xl, w, v, color, r) {
      var vp = clampY(v), cut = vp !== v;
      el('path', { d: barPath(xl, Y(0), Y(vp), w, cut ? 0 : (r == null ? 3 : r)), fill: color }, g);
      if (cut) { capMark(g, xl + w / 2, Y(vp), w); capLabel(xl + w / 2 + 3.4, v > vp, capFmt(v)); }
      return cut;
    }
    /* 被截的「点」（菱形/圆点）一律换成空心红圈 + 真值，同 polyline 里的规矩 */
    function capPoint(x, v) {
      var vp = clampY(v), cut = vp !== v;
      if (cut) {
        el('circle', { cx: x.toFixed(2), cy: Y(vp).toFixed(2), r: 2.9, fill: C.WHITE,
          stroke: BREAK, 'stroke-width': 1.1 }, g);
        capLabel(x + 3.4, v > vp, capFmt(v));
      }
      return cut;
    }
    /* ── 逐点数值标签的密度控制 ──
       每根柱都标数值，在窄卡片 / 窄屏上 band 会掉到 10px 出头，而「$10.35」这类标签
       实测宽 25px —— 相邻标签直接叠字（schw Ex5 @375px 实测横向重叠 14.15px，
       25 根柱的标签连成「$9.41$9.57$9.74…」一条串，一个都读不出）。band 随视口等比缩，
       字号却是写死的 8px，所以这是几何必然，不是某张图碰巧。

       做法：不猜宽度、也不缩字号（要让 25 个「$10.35」不重叠得压到 3.5px 以下，
       那是不可读）。先照常把标签全部画出来，再用**实测 bbox** 判断是不是真的压在一起；
       压上了才按步长抽稀，步长从最后一期往回数，保证最新一期永远有标签。
       被抽掉的数值在「表格」视图里一个不少，切一下就能看到。

       关键性质：一对标签都没压上时一个都不删 —— 所以本来就不挤的图（COST / IBKR
       两个已上线的站，实测最小标签间距 29px）输出逐字节不变，不是靠调参保证的。
       只对「一个 x 一个标签」的图型调用：并排柱（grouped_bars）的同 x 多标签
       用步长抽不掉，得另想办法，别往这里挂。 */
    var LAB_GAP = 1.5;                            // 留给读者的最小横向间隙
    function thinLabels(nodes) {
      var m = nodes.length, i, j, k, bx = [], b, keep, ok;
      if (m < 3) return;                          // 只有两个标签，抽完只剩一个，不值当
      for (i = 0; i < m; i++) {
        try { b = nodes[i].el.getBBox(); } catch (e) { return; }
        if (!b || !b.width) return;               // 量不到（卡片被 display:none）：一个都不删
        bx.push({ i: nodes[i].i, el: nodes[i].el,
          x: b.x, r: b.x + b.width, y: b.y, b: b.y + b.height });
      }
      function hit(a, c) {
        return Math.max(a.x, c.x) - Math.min(a.r, c.r) < LAB_GAP &&
               Math.min(a.b, c.b) - Math.max(a.y, c.y) > 0.2;
      }
      var last = bx[bx.length - 1].i;
      for (k = 1; k <= m; k++) {
        keep = bx.filter(function (o) { return (last - o.i) % k === 0; });
        ok = true;
        for (i = 0; i < keep.length && ok; i++)
          for (j = i + 1; j < keep.length; j++) if (hit(keep[i], keep[j])) { ok = false; break; }
        if (ok) break;
      }
      if (k <= 1) return;
      for (i = 0; i < bx.length; i++)
        if ((last - bx[i].i) % k) bx[i].el.parentNode.removeChild(bx[i].el);
    }

    /* 一列标签的竖向避让：按最小行距推开，整列超出下界就整体上移，
       上下都顶满时从上边界顺排。lines_endlabels 与 lines 的末点标注共用。 */
    function spreadY(arr, gap) {
      gap = fscale(gap || 9.6);        // 行距 = 字高，字大了不跟着放就是让标签互相压
      var lo = M.t + 7, hi = M.t + ph + 3, k, over;
      arr.sort(function (a, b) { return a.y - b.y; });
      for (k = 1; k < arr.length; k++)
        if (arr[k].y - arr[k - 1].y < gap) arr[k].y = arr[k - 1].y + gap;
      over = arr.length ? arr[arr.length - 1].y - hi : 0;
      if (over > 0) for (k = 0; k < arr.length; k++) arr[k].y -= over;
      if (arr.length && arr[0].y < lo)
        for (k = 0; k < arr.length; k++) arr[k].y = lo + k * gap;
      return arr;
    }

    /* 竖排数值标签（qtr_bar 用）：柱很高时把标签压回画布内，不许越过 viewBox 顶 */
    function vLabel(x, yTop, s, o) {
      var need = s.length * fscale(o.size || 8) * 0.62;   // 竖排长度 = 字数 × 实际字号
      var yy = Math.max(yTop, need + 2);
      txt(g, x, yy, s, { size: o.size || 8, anchor: 'start', fill: o.fill || C.INK,
        transform: 'rotate(-90 ' + x.toFixed(2) + ' ' + yy.toFixed(2) + ')' });
    }

    if (kind === 'bar_line' || kind === 'diverging_bars' || kind === 'bars_labeled' || kind === 'bar_line_dual') {
      var vals = (kind === 'bar_line' || kind === 'bar_line_dual') ? ex.bar.values : ex.values;
      var w = BW(0.75);
      for (i = 0; i < n; i++) {
        var v = vals[i];
        if (v == null || !isFinite(v)) continue;
        var cc = kind === 'diverging_bars' ? (v >= 0 ? C.NAVY : C.RED)
               : col((kind === 'bar_line' || kind === 'bar_line_dual') ? ex.bar.color : 'NAVY');
        if (markSet && markSet[i]) cc = 'url(#' + hatchId + ')';
        /* 超出截轴范围的柱画到边界，柱端加断口符号，真值竖排标在图外 */
        var vp = v, ov = false;
        if (ex.ycap != null && v > y1) { vp = y1; ov = true; }
        else if (ex.yfloor != null && v < y0) { vp = y0; ov = false; }
        var cut = vp !== v;
        el('path', { d: barPath(Xc(i) - w / 2, Y(0), Y(vp), w, cut ? 0 : 3), fill: cc }, g);
        if (cut) { capMark(g, Xc(i), Y(vp), w); capLabel(Xc(i) + 3.4, ov, capFmt(v)); }
      }
      if (kind === 'bar_line') polyline(ex.line.values, col(ex.line.color), 1.6, false, false);
      if (kind === 'bar_line_dual') polyline(ex.line.values, col(ex.line.color), 1.6, false, false, Y2);
      if (kind === 'bars_labeled') {
        var lf = fmtOf(ex.label_fmt || 'f1'), labb = [];
        for (i = 0; i < n; i++) {
          if (vals[i] == null) continue;
          /* 柱被截过时数值标签跟着柱端走，否则会跑到画布外 */
          var yl = ex.ycap != null ? Math.min(vals[i], y1) : vals[i];
          if (yl !== vals[i]) continue;             // 真值已由 capLabel 竖排标出，别重复
          labb.push({ i: i, el: txt(g, Xc(i), Y(yl) - fscale(5), lf(vals[i]), { size: 8.5 }) });
        }
        /* 本图型原先没接 thinLabels —— 它是「一个 x 一个标签」，正是 thinLabels 的适用面，
           只是基线字号下恰好不撞才一直没暴露（lseg Ex38/53/54 的 '6.96' 与 '6.91'
           在放大后互压 8–18px）。这里补上，别再靠字号碰巧不撞。 */
        thinLabels(labb);
      }
    } else if (kind === 'lines') {
      /* end_label ← gsx.long_line 的 n_label：长历史图上标出最新一点。
         那是这类图上**唯一的绝对水平锚点** —— 不标的话读者只能从轴刻度目测，
         而长历史图的轴刻度间隔往往就是几百个单位（SCHW Ex7/10/14/15、LPLA Ex8/17、
         MSCI Ex4/11、TSM Ex3/10/12、CBOE Ex6 全丢了这个标注）。
         默认关闭：既有的 kind:'lines' 图（含 COST/IBKR 两个已上线站）不给就一个都不画。 */
      var fle = fmtOf(ex.label_fmt || ex.fmt || ex.yfmt || 'f1'), LB = [];
      for (s = 0; s < ex.series.length; s++) {
        polyline(ex.series[s].values, col(ex.series[s].color), 1.6, false, !!ex.markers);
        if (!ex.end_label) continue;
        var je2 = lastFinite(ex.series[s].values);
        /* 末点被截时真值已由 capLabel 竖排标出，不重复标 */
        if (je2 < 0 || clampY(ex.series[s].values[je2]) !== ex.series[s].values[je2]) continue;
        LB.push({ i: je2, y: Y(ex.series[s].values[je2]) - 7,
          t: fle(ex.series[s].values[je2]), c: col(ex.series[s].color) });
      }
      if (LB.length) {
        /* 标签落在末点的**左上方**（同 deck 的 xytext=(-6,12) + ha='right'）：
           往上避开 x 轴刻度，往左避开右边界，末点自己的圆点仍然露着。 */
        spreadY(LB, 10);
        for (i = 0; i < LB.length; i++)
          txt(g, Xc(LB[i].i) - 4, LB[i].y, LB[i].t,
            { size: 8.5, anchor: 'end', weight: 700, fill: LB[i].c });
      }
    } else if (kind === 'gs_bar') {
      var wg = BW(0.62), fb = fmtOf(ex.fmt), labg = [];
      var yoyS = rhsOf(ex);
      /* ── 可选的次轴 y/y 折线（ex.yoy）──
         deck 的 gsx.lvl_bar 画的是「浅蓝柱 + 次轴金色 y/y 折线」，docstring 明写
         「次轴画的是同比而不是滚动均线 —— 均线只是把柱子再平滑一遍、不带新信息，
         同比才回答『相对去年这个月是好是坏』」；build_hood.py 记的用户既定规范第 1 条
         也是「全部换成 y/y」。网页版一律画成了 12 个月均线，把这条规矩丢了
         （MSCI Ex2/7/8、SPGI Ex2/3、TSM Ex7/9 等 8 页 29 张图都受影响）。

         给了 ex.yoy 就画 y/y 折线并**不画均线** —— 两条一起画太挤，而且它们回答的是
         同一个问题的两种说法，读者要在同一张图上分辨两条横向线的含义。
         没给就完全维持现状（默认关闭，不动任何已上线的页面）。 */
      if (!yoyS) {
        /* 均线**必须画在数值标签之前**。它按构造就落在柱子中段附近，凡是当月值接近
           12 个月均值的月份，标签必然被这条横线拦腰划掉 —— 两轮独立人眼审查都把这条
           列为 blocker（SCHW Ex12 三个数连着被划、LPLA Ex16 连续 9 个百分比被划断）。
           光靠 txt() 的白色描边挡不住：描边只压得住画在它**下面**的东西。 */
        el('line', { x1: M.l, x2: M.l + pw, y1: Y(avg), y2: Y(avg), stroke: C.NAVY,
          'stroke-width': 1.4, 'stroke-dasharray': '6 4' }, g);
      }
      for (i = 0; i < n; i++) {
        /* 原来这里是直接 barPath(Y(values[i]))，没走截轴：设了 ycap 的话柱和数值标签
           会一起画到画布外几百像素（IBKR 现有 payload 没设过 ycap，所以一直没暴露）。
           改走 capBar 后，没设 ycap 时输出与从前逐字节相同。 */
        if (!isNum(ex.values[i])) continue;
        var cutg2 = capBar(Xc(i) - wg / 2, wg, ex.values[i],
          (markSet && markSet[i]) ? 'url(#' + hatchId + ')' : C.BLUE);
        if (!cutg2) labg.push({ i: i,
          el: txt(g, Xc(i), Y(ex.values[i]) - 4.5, fb(ex.values[i]), { size: 8 }) });
      }
      thinLabels(labg);
      if (yoyS && Y2) {
        var lcy = col(yoyS.color || 'GOLD'), vy = yoyS.values, kk;
        /* 零线：y/y 的正负是这条线的全部意义，没有零线读者只能靠右轴刻度反推 */
        if (r0 < -1e-9 && r1 > 1e-9)
          el('line', { x1: M.l, x2: M.l + pw, y1: Y2(0), y2: Y2(0), stroke: lcy,
            'stroke-width': 0.7, 'stroke-dasharray': '2 2' }, g);
        polyline(vy, lcy, 1.6, false, true, Y2);
        /* 柱顶数值标签重新置顶。y/y 线横穿柱顶一带，画在标签之上就会把数字拦腰划断
           （同均线那条规矩，白色描边只压得住画在它下面的东西）。
           这里用「把已有节点再 appendChild 一次」把它们移到 g 的末尾，而不是把整个柱子
           循环拆成两趟 —— 拆循环会连带改掉**没开 y/y** 那条路径的 DOM 顺序，
           而 IBKR 的 5 张 gs_bar 正走那条路径，要求逐字节不变。 */
        for (kk = 0; kk < labg.length; kk++)
          if (labg[kk].el.parentNode === g) g.appendChild(labg[kk].el);
        var jy = lastFinite(vy);
        /* 末点读数标在点的**右下方**（同 deck 的 xytext=(5,-7)）：柱顶那一排数值标签
           在点的上方，标上面必压。 */
        if (jy >= 0)
          priorityLabs.push(txt(g, Xc(jy) + 5, Y2(vy[jy]) + 9.5, fmtOf(yoyS.yfmt || 'pct0')(vy[jy]),
            { size: 8, anchor: 'start', weight: 700, fill: lcy }));
      }
      /* y/y 折线在场时不再画 y/y 气泡：同一件事说两遍，气泡还占着左上角 */
      if (ex.yoy_txt && !yoyS) oval(g, Xc(0) + band * 0.25, Y(y1 * 0.93), ex.yoy_txt, null, M.l);
      if (ex.mom_txt) {
        var last = ex.values[n - 1];
        /* 气泡与箭头按**窗口末端**定位，不能写死 Xc(9)/Xc(11)。
           原先是照 PDF 的 13 个月窗口硬编的坐标，窗口一改成 25 根柱，箭头就指到第 12 根，
           而那根柱看着完全正常 —— 读者会把它当成最新月。n=13 时 n-4/n-2 正好还原原值。 */
        oval(g, Xc(n - 4) + band * 0.2, Y(Math.min(last * 1.13, y1 * 0.94)), ex.mom_txt,
          [Xc(n - 2) + band * 0.3, Y(last * 1.06)], M.l);   // PDF: arrow_to=(11.8, vals[-1]*1.06)
      }
    } else if (kind === 'gs_line' || kind === 'gs_line_avg') {
      var fv = fmtOf(ex.fmt);
      var dmn = Math.min.apply(null, ex.values), dmx = Math.max.apply(null, ex.values);
      var rngv = (dmx - dmn) || 1;
      if (kind === 'gs_line_avg') {
        el('line', { x1: M.l, x2: M.l + pw, y1: Y(avg), y2: Y(avg), stroke: C.BLUE,
          'stroke-width': 1.4, 'stroke-dasharray': '6 4' }, g);
        txt(g, M.l + pw + 4, Y(avg) + 3.2, fv(avg), { size: 8.5, anchor: 'start', fill: C.MBLUE });
      }
      polyline(ex.values, C.NAVY, 1.8, true, false);
      var off = (kind === 'gs_line_avg' ? 0.05 * 1.7 : 0.06 * 1.6) * rngv;
      var labl = [];
      for (i = 0; i < n; i++) {
        var vv = ex.values[i];
        var up = !(i > 0 && i < n - 1 && vv < (ex.values[i - 1] + ex.values[i + 1]) / 2);
        labl.push({ i: i, el: txt(g, Xc(i), Y(vv + (up ? off : -off)) + (up ? 0 : 7), fv(vv),
          { size: 8, fill: C.NAVY }) });
      }
      thinLabels(labl);
      if (ex.ovals_at_bottom) {
        var by = Y(dmn - rngv * 0.12);
        if (ex.yoy_txt) oval(g, Xc(1), by, ex.yoy_txt, [Xc(2) + band * 0.6, by], M.l);
        // 同上：按窗口末端定位，不写死 13 个月窗口的下标
        if (ex.mom_txt) oval(g, Xc(n - 4) + band * 0.1, by, ex.mom_txt, [Xc(n - 2) + band * 0.5, by], M.l);
      }
    } else if (kind === 'lines_endlabels') {
      var fe = fmtOf(ex.fmt);
      /* 端点标签必须做避让：原来左右两端都是无条件按 Y(值) 落笔，两条线端值接近
         （CME Ex5 的 FX 788 / Metals 811）就互相盖住，端值相等时（CME Ex3 两条线
         都是 23.0）后画的把先画的整条盖没 —— 读者看到的是一个假数字，不是一团糊。
         左端还额外压在 y 轴刻度上（wealth Ex4 的「41%」压刻度「40」）。
         这里：竖向按最小行距推开；横向左端退到刻度栏左侧的专列（M.l 已多留 30px）。 */
      var LE = [], RE = [];
      for (s = 0; s < ex.series.length; s++) {
        var sr = ex.series[s], sc = col(sr.color);
        polyline(sr.values, sc, 1.8, true, false);
        LE.push({ y: Y(sr.values[0]) + 3.2, t: fe(sr.values[0]), c: sc });
        RE.push({ y: Y(sr.values[n - 1]) + 3.2, t: fe(sr.values[n - 1]), c: sc });
      }
      /* 左端标签的右边界：刻度栏左侧再留 4px。tickW 量不到时（图被 display:none）
         退回一个够宽的常数，宁可离轴远也不要压上去。 */
      var lx = M.l - 10 - (tickW || 26);
      spreadY(LE).forEach(function (d) {
        txt(g, lx, d.y, d.t, { size: 8, anchor: 'end', fill: d.c });
      });
      spreadY(RE).forEach(function (d) {
        txt(g, Xc(n - 1) + 7, d.y, d.t, { size: 8, anchor: 'start', fill: d.c });
      });
    } else if (kind === 'stacked_dual') {
      var ws = BW(0.62), base = [];
      for (i = 0; i < n; i++) base.push(0);
      for (s = 0; s < ex.stacks.length; s++) {
        var st = ex.stacks[s], labst = [];
        for (i = 0; i < n; i++) {
          var lo = base[i], hi = base[i] + st.values[i];
          var hgt = Math.max(0, Y(lo) - Y(hi) - (s ? 1.5 : 0));
          el('rect', { x: Xc(i) - ws / 2, y: Y(hi), width: ws, height: hgt, fill: col(st.color) }, g);
          if (st.label && hgt > 8)
            labst.push({ i: i,
              el: txt(g, Xc(i), (Y(lo) + Y(hi)) / 2 + 2.4, comma(st.values[i], 0),
                { size: 6.6, fill: col(st.label_color) }) });
          base[i] = hi;
        }
        /* 段内数值同样会横向连成一片（cboe Ex5 @375px 的「11,836」「12,215」重叠 3.3px）。
           一段一抽：同一段的标签在同一带高度上，互相压的只会是左右邻居。 */
        thinLabels(labst);
      }
      polyline(ex.line.values, col(ex.line.color), 1.8, true, false, Y2);
      /* 左右两轴各自缩放（左轴 0..stackMax*1.28，右轴 0..ymax），两者没有耦合，
         右轴折线经常落在柱体内部 —— 那里已经有段内数值标签，两个 6.6px 的数字会在
         同一个 x 上叠成一团（hood Ex9 的 Jun-25：「384」与「41.5%」基线只差 0.1px，
         放大后印成「4384%」，两个真值都读不出）；而且绿字压在深蓝/灰段上，
         对比度只有 1.9~2.5:1，本来也读不动。
         落进柱体就把百分比抬到柱顶之上的白底空白里（y1 = mx*1.28，最高的柱顶上方
         永远留着 22% 的绘图区高度），x 不动，仍看得出对应哪一列；抬上去之后是
         白底，#548235 对比度 5.4:1，顺带把对比度问题一起解决。
         Math.min 是关键：折线本来就在柱顶之上时取值不变，不动没坏的图。 */
      var labsd = [];
      for (i = 0; i < n; i++) {
        if (!isNum(ex.line.values[i])) continue;
        var yPct = Y2(ex.line.values[i]) - 5;
        if (isNum(base[i])) yPct = Math.min(yPct, Y(base[i]) - 2);
        labsd.push({ i: i, el: txt(g, Xc(i), yPct, ex.line.values[i].toFixed(1) + '%',
          { size: 6.6, fill: col(ex.line.color) }) });
      }
      thinLabels(labsd);

    /* ══════════════ 以下七个图型对应 build/gsx.py 的同名函数 ══════════════ */

    /* qtr_bar ← gsx.qtr_bar：季度柱 + 右轴 y/y；未满季用浅蓝并在图例里写明「几 of 3」。
       数值标签竖排在柱顶（gsx 是 rotation=90），所以纵轴上界给 1.32 倍。
       右轴的金色（gsx GOLD）不在本文件的 C.* 里，默认退到 GREEN，payload 可指定。 */
    } else if (kind === 'qtr_bar') {
      var wq = BW(0.70), fq = fmtOf(ex.label_fmt || ex.fmt || 'f0c'), qLab = [];
      var partialQ = isNum(ex.partial_months) && +ex.partial_months > 0 &&
                     +ex.partial_months < (ex.qtr_months || 3);
      /* 柱 → 右轴线 → 数值标签，三层顺序不能反。
         与 gs_bar 的均线同一条道理：右轴那条 y/y 线会横穿柱顶一带，画在数值标签之上
         就会把标签拦腰划断，而 txt() 的白色描边只压得住画在它**下面**的东西。
         零点对齐兜底（见 ALIGN_WASTE_MAX）生效后柱子变高、线相对下移，
         schw Ex11 实测由此新增两处「绿线划穿 $52 / $120」—— 所以标签必须最后画。 */
      for (i = 0; i < n; i++) {
        var vq = ex.values[i];
        if (!isNum(vq)) continue;
        var cq = (partialQ && i === n - 1) ? C.BLUE : C.NAVY;
        if (markSet && markSet[i]) cq = 'url(#' + hatchId + ')';
        var cutq = capBar(Xc(i) - wq / 2, wq, vq, cq);
        if (cutq || ex.bar_labels === false) continue;
        qLab.push(i);
      }
      if (Y2) {
        var lcq = col((ex.line.color) || 'GREEN');
        /* 未满季的那根柱有浅蓝 + 图例提示，但**右轴的 y/y 必须一起丢掉**：
           拿 2 个月的累计去比上年完整 3 个月，必然砸出一个 -8% 之类的假坑，
           而线是连续的、没有任何视觉提示说这一点不可比 —— 读者会当成业务塌了。
           这里在引擎侧直接丢，不指望每个 build/<t>.py 都记得传 null：
           这是口径错误，不是排版偏好，漏一次就是发布一张误导图。 */
        var lvq = lineVals(ex);
        if (r0 < -1e-9 && r1 > 1e-9)
          el('line', { x1: M.l, x2: M.l + pw, y1: Y2(0), y2: Y2(0), stroke: lcq,
            'stroke-width': 0.7, 'stroke-dasharray': '2 2' }, g);
        polyline(lvq, lcq, 1.6, false, true, Y2);
      }
      /* 数值标签最后画（见上）：正柱竖排在柱顶，负柱横排在柱底 —— 负柱竖排会插进柱体里 */
      for (var q2 = 0; q2 < qLab.length; q2++) {
        var iq = qLab[q2], vq2 = ex.values[iq];
        if (vq2 >= 0) vLabel(Xc(iq), Y(vq2) - 4, fq(vq2), { size: 7.4 });
        else txt(g, Xc(iq), Y(vq2) + 9, fq(vq2), { size: 7.4 });
      }
      if (Y2) {
        var lvq2 = lineVals(ex), jq = lastFinite(lvq2);
        if (jq >= 0)
          priorityLabs.push(txt(g, Xc(jq) + 5, Y2(lvq2[jq]) + 3.2,
            fmtOf(ex.line.yfmt || 'pct0')(lvq2[jq]),
            { size: 8, anchor: 'start', weight: 700, fill: col((ex.line.color) || 'GREEN') }));
      }

    /* seasonality ← gsx.seasonality：灰柱 = 过去 N 年同月均值、蓝柱 = 本期实际。
       两根柱各占 band 的 0.40，在 band 中心相接（同 matplotlib 的 ±0.20 偏移）。 */
    } else if (kind === 'seasonality') {
      var wb = BW(0.40), fsz = fmtOf(ex.label_fmt || ex.fmt || 'f1');
      var cb = col((ex.base && ex.base.color) || 'GRAY');
      var ca = col((ex.actual && ex.actual.color) || 'MBLUE');
      var bvals = (ex.base && ex.base.values) || [], avals = (ex.actual && ex.actual.values) || [];
      for (i = 0; i < n; i++) {
        if (isNum(bvals[i])) capBar(Xc(i) - wb, wb, bvals[i], cb);
        if (!isNum(avals[i])) continue;
        var cuta = capBar(Xc(i), wb, avals[i], ca);
        if (!cuta && ex.bar_labels !== false)
          txt(g, Xc(i) + wb / 2, Y(avals[i]) + (avals[i] < 0 ? 9 : -4), fsz(avals[i]),
            { size: 7.6, fill: ca });
      }

    /* bridge_bar ← gsx.bridge_bar：正的往上堆、负的往下堆，菱形标净额。
       堆叠段不参与截轴（截一段堆叠柱等于把恒等式画错），只有净额点会被截。 */
    } else if (kind === 'bridge_bar') {
      var wbr = BW(0.70), posB = [], negB = [];
      for (i = 0; i < n; i++) { posB.push(0); negB.push(0); }
      for (s = 0; s < ex.stacks.length; s++) {
        var stb = ex.stacks[s], cbb = col(stb.color);
        for (i = 0; i < n; i++) {
          var vb = stb.values[i];
          if (!isNum(vb) || vb === 0) continue;
          var bb0 = vb >= 0 ? posB[i] : negB[i], bb1 = bb0 + vb;
          if (vb >= 0) posB[i] = bb1; else negB[i] = bb1;
          /* 段也要吃截轴：不然一根 −46 的市值变动段会径直画到 x 轴标签底下去。
             这里只把「画到哪」钳住，真值下面按列标出，堆叠关系一个不删。 */
          var yA = Y(clampY(bb0)), yB = Y(clampY(bb1));
          if (Math.abs(yA - yB) < 0.05) continue;      // 整段在界外，不画 0 高的柱
          el('rect', { x: (Xc(i) - wbr / 2).toFixed(2), y: Math.min(yA, yB).toFixed(2),
            width: wbr.toFixed(2), height: Math.abs(yA - yB).toFixed(2), fill: cbb }, g);
        }
      }
      var netv = bridgeNet(ex, n);
      for (i = 0; i < n; i++) {
        /* 包络被截：柱端画断口 + 真值。净额与包络重合时（全负/全正列）不重复标 */
        if (ex.ycap != null && posB[i] > y1) {
          capMark(g, Xc(i), Y(y1), wbr);
          if (!(isNum(netv[i]) && Math.abs(netv[i] - posB[i]) < 1e-9))
            capLabel(Xc(i) + 3.4, true, capFmt(posB[i]));
        }
        if (ex.yfloor != null && negB[i] < y0) {
          capMark(g, Xc(i), Y(y0) - 8, wbr);
          if (!(isNum(netv[i]) && Math.abs(netv[i] - negB[i]) < 1e-9))
            capLabel(Xc(i) + 3.4, false, capFmt(negB[i]));
        }
        if (!isNum(netv[i]) || capPoint(Xc(i), netv[i])) continue;
        diamond(g, Xc(i), Y(netv[i]), 3.2, col(ex.net_color || 'INK'));
      }

    /* grouped_bars ← gsx.implied_vs_actual：同一 x 上两根并排柱 + 右轴误差线。
       误差是这张图存在的理由（桥的假设可不可信），所以末点误差要标出来。 */
    } else if (kind === 'grouped_bars') {
      var gps = ex.groups || [], ng = Math.max(1, gps.length);
      var wgb = BW(0.74 / ng), xg0 = -(ng * wgb) / 2;
      var gdef = ['BLUE', 'NAVY', 'MBLUE', 'GRAY'];
      var fgb = fmtOf(ex.label_fmt || ex.fmt || 'f0c');
      for (s = 0; s < gps.length; s++) {
        var cg = col(gps[s].color || gdef[s % gdef.length]);
        for (i = 0; i < n; i++) {
          var vg = gps[s].values[i];
          if (!isNum(vg)) continue;
          var cutg = capBar(Xc(i) + xg0 + s * wgb, wgb, vg, cg);
          if (!cutg && ex.bar_labels)
            txt(g, Xc(i) + xg0 + (s + 0.5) * wgb, Y(vg) + (vg < 0 ? 8.5 : -4), fgb(vg),
              { size: 6.6, fill: cg });
        }
      }
      if (Y2) {
        var lce = col((ex.line.color) || 'RED');
        if (r0 < -1e-9 && r1 > 1e-9)
          el('line', { x1: M.l, x2: M.l + pw, y1: Y2(0), y2: Y2(0), stroke: lce,
            'stroke-width': 0.7, 'stroke-dasharray': '2 2' }, g);
        polyline(ex.line.values, lce, 1.4, false, true, Y2);
        var je = lastFinite(ex.line.values);
        if (je >= 0)
          priorityLabs.push(txt(g, Xc(je) + 5, Y2(ex.line.values[je]) + 3.2,
            fmtOf(ex.line.yfmt || 'pct1')(ex.line.values[je]),
            { size: 8, anchor: 'start', weight: 700, fill: lce }));
      }

    /* range_band ← gsx.range_vs_actual：指引区间画成带、实际值打菱形。
       未完成期的累计值（qtd）用空心红菱形，标签压在点下方，跟实际值分得开。 */
    } else if (kind === 'range_band') {
      var wrb = BW(0.74), frb = fmtOf(ex.label_fmt || ex.fmt || 'f1');
      var loA = ex.lo || [], hiA = ex.hi || [], acA = ex.actual || [];
      for (i = 0; i < n; i++) {
        if (isNum(loA[i]) && isNum(hiA[i])) {
          var t0 = Math.min(loA[i], hiA[i]), t1 = Math.max(loA[i], hiA[i]);
          var c0 = clampY(t0), c1 = clampY(t1), yT = Y(c1), yB = Y(c0);
          el('rect', { x: (Xc(i) - wrb / 2).toFixed(2), y: yT.toFixed(2),
            width: wrb.toFixed(2), height: Math.max(0.9, yB - yT).toFixed(2), fill: C.BLUE }, g);
          var hwr = wrb * 0.46;
          el('line', { x1: (Xc(i) - hwr).toFixed(2), x2: (Xc(i) + hwr).toFixed(2),
            y1: yT.toFixed(2), y2: yT.toFixed(2), stroke: C.MBLUE, 'stroke-width': 0.9 }, g);
          el('line', { x1: (Xc(i) - hwr).toFixed(2), x2: (Xc(i) + hwr).toFixed(2),
            y1: yB.toFixed(2), y2: yB.toFixed(2), stroke: C.MBLUE, 'stroke-width': 0.9 }, g);
          if (c1 !== t1) { capMark(g, Xc(i), yT, wrb); capLabel(Xc(i) + 3.4, true, frb(t1)); }
          if (c0 !== t0) capLabel(Xc(i) + 3.4, false, frb(t0));
        }
        if (!isNum(acA[i]) || capPoint(Xc(i), acA[i])) continue;
        diamond(g, Xc(i), Y(acA[i]), 3.4, col(ex.actual_color || 'NAVY'));
        if (ex.bar_labels !== false)
          txt(g, Xc(i), Y(acA[i]) - 7, frb(acA[i]), { size: 7.6, fill: col(ex.actual_color || 'NAVY') });
      }
      if (isNum(ex.qtd)) {
        var jd = ex.qtd_at != null ? +ex.qtd_at : n - 1;
        if (jd >= 0 && jd < n && !capPoint(Xc(jd), ex.qtd)) {
          diamond(g, Xc(jd), Y(ex.qtd), 4.2, C.WHITE, C.RED, 1.4);
          txt(g, Xc(jd), Y(ex.qtd) + 12, frb(ex.qtd), { size: 7.8, fill: C.RED, weight: 700 });
        }
      }

    /* year_lines ← gsx.year_lines：每年一条线叠在 Jan..Dec 上，当年红色加粗带点。
       累计与否由 Python 决定（传进来的就是要画的值），本文件不再 cumsum。 */
    } else if (kind === 'year_lines') {
      var ycs = yearColors(ex), hly = ex.highlight != null ? +ex.highlight : ex.series.length - 1;
      var fyl = fmtOf(ex.label_fmt || ex.fmt || 'f0c');
      for (s = 0; s < ex.series.length; s++) {
        var isCur = (s === hly);
        /* 往年线 1.1 → 1.4：deck 那边 1.1 是 matplotlib 点（高 DPI 输出），
           照搬成 1.1 CSS px 后最浅那两条几乎是半透明的。加粗只加往年，
           当年仍是 2.0 + 圆点标记，主次不变。 */
        polyline(ex.series[s].values, ycs[s], isCur ? 2 : 1.4, false, isCur);
        if (!isCur) continue;
        var jl = lastFinite(ex.series[s].values), vl = jl >= 0 ? ex.series[s].values[jl] : null;
        /* 末点被截时真值已由 capLabel 竖排标出，别再横着标一遍 */
        if (jl >= 0 && clampY(vl) === vl)
          txt(g, Xc(jl) + 5, Y(vl) + 3.2, fyl(vl),
            { size: 8.2, anchor: 'start', weight: 700, fill: ycs[s] });
      }
    }

    /* 结构性断点（规矩 6）：口径变更、并表、周数不可比等「左右两侧不能连着读」的位置。
       画在该期柱的左缘（band*i，等价于 gsx._draw_break 的 x-0.5），语义是
       「从这一期起与左侧不可比」。放在系列之后画，保证虚线压在柱和线上面。 */
    if (ex.break_at != null) {
      var bAt = Array.isArray(ex.break_at) ? ex.break_at : [ex.break_at];
      var bLb = Array.isArray(ex.break_label) ? ex.break_label : [ex.break_label];
      for (i = 0; i < bAt.length; i++) {
        var bi = +bAt[i];
        if (!isFinite(bi) || bi < 0 || bi > n) continue;
        var bx = M.l + band * bi;
        el('line', { x1: bx, x2: bx, y1: M.t, y2: M.t + ph, stroke: BREAK,
          'stroke-width': 1, 'stroke-dasharray': '4 3' }, g);
        var bs = bLb.length === 1 ? bLb[0] : bLb[i];
        /* 标签照老位置先画出来，但**最终落位推迟到 draw 末尾**统一做：它要避的柱值标签
           这时才刚画完，而「左右轴零点不同高」「annot」两条说明还没画。详见末尾那段。 */
        var bel = bs ? txt(g, bx - 3, M.t + 3, bs, { size: 7, fill: BREAK, anchor: 'end',
          transform: 'rotate(-90 ' + (bx - 3) + ' ' + (M.t + 3) + ')' }) : null;
        /* 这条标签是 rotate(-90) 从图顶往下挂的，长度就是文字长度。文案由 payload 给，
           放大后会**比绘图区还长**，多出来的部分不是「和别的字重叠」，是直接盖到
           x 轴月份标签上。所以先按绘图区高度实测收缩，再进下面的避让流程 ——
           顺序不能反：避让是拿它的外接框找空档，框还没定住就找不准。 */
        fitVertical(bel, ph - 6, 7);
        brks.push({ x: bx, ax: bx - 3, ay: M.t + 3, el: bel });
      }
    }
    /* 截轴说明贴右上角：被截的通常是早期的低基数尖峰（图左侧），
       左上角要留给那几个竖排真值标签。 */
    if (capOn && ex.cap_note)
      txt(svg, M.l + pw, 8, ex.cap_note, { size: 7.4, anchor: 'end', style: 'italic', fill: BREAK });
    /* 零点没对齐就必须写出来（见 ALIGN_WASTE_MAX）。
       画在绘图区内的左上角而不是画布顶：那里是柱图天然的留白（y1 至少是 max 的 1.22 倍），
       而画布顶那一条要留给截轴的竖排真值。挂在 svg 上（在 g 之后）保证压在数据上面，
       文字本身有白色描边打底。 */
    if (misalign) {
      txt(svg, M.l + 3, M.t + 9, '左右轴零点不同高（两轴独立缩放）',
        { size: 7.4, anchor: 'start', style: 'italic', fill: BREAK });
      /* 右轴的零线也得画出来。零点对齐时图上那条唯一的零线两边通用，不对齐之后
         柱的基线只代表左轴 —— 读者若拿它当右轴的零，hood Ex4 那条在 −25pp..+25pp
         之间来回的 y/y 线会被整条读成正值。qtr_bar / grouped_bars / gs_bar 自己就画了，
         这里只补 bar_line_dual / stacked_dual 这两个原本没画的。 */
      if (r0 < -1e-9 && r1 > 1e-9 &&
          kind !== 'qtr_bar' && kind !== 'grouped_bars' && kind !== 'gs_bar')
        el('line', { x1: M.l, x2: M.l + pw, y1: Y2(0), y2: Y2(0),
          stroke: col((rc && rc.color) || 'GREEN'), 'stroke-width': 0.7,
          'stroke-dasharray': '2 2' }, svg);
    }

    if (ex.ylab) {
      var cy = M.t + ph / 2, xl = fscale(13);
      txt(svg, xl, cy, ex.ylab, { size: 8.4, transform: 'rotate(-90 ' + xl + ' ' + cy + ')' });
    }
    if (ex.annot) {
      if (kind === 'bars_labeled')
        txt(svg, M.l + 3, M.t + 13, ex.annot, { size: 9.5, anchor: 'start', weight: 600, fill: C.NAVY });
      else
        txt(svg, M.l + pw - 3, M.t + ph - 7, ex.annot, { size: 8.5, anchor: 'end' });
    }

    /* ── 断点标签避让 ────────────────────────────────────────────────────
       断点标签是一条竖排长条，从绘图区顶端挂下来贴在断点线左侧；柱值标签是横排的，
       钉死在各自柱顶。两者按构造垂直相交 —— 实测全站 29 页 × 2 视口 42 处直接印穿
       数字（lpla Ex9「Commonwealth」穿过 $49.5、enx 20 处穿过「23,516」这类；
       重叠面积清一色 25.9px²，正好是两条墨迹带的完整十字交叉，不是擦边）。
       谁让位：沿用引擎既有那条规矩 —— 读数是真实数据、注记只是标尺 —— 让注记让。
       做法只有一个动作：沿它自己那条竖线上下平移到空白段。标签仍锚在线上，
       「从这一期起与左侧不可比」的语义不变，只是起点不再写死在顶端。
       为什么不用别的办法：① 只靠白色描边遮盖没用 —— 描边压不住画在它**上面**的东西；
       ② 缩字号要跌破引擎里 4.6px 的下限，不可读；③ 加不透明底色只是把数字盖得更死。
       为什么放在这里而不是画断点线那一段：要避的对象里有「左右轴零点不同高」和 annot，
       它们是在断点之后才画出来的，早了就量不到。
       放不下就原地不动 —— 挪一半仍旧压着，不如维持现状（tmx Ex14/26/27 就是这种：
       标签 180px、竖线只有 254px，正中间还钉着一个柱值，上下两段都塞不进）。 */
    brks.forEach(function (bk) {
      var br = bk.el && textRect(bk.el);
      if (!br) return;
      var obs = [], PAD = 1.5, z;
      svg.querySelectorAll('text').forEach(function (o) {          // 同一竖直条带上的所有文字
        if (o === bk.el) return;
        var q = textRect(o);
        if (q && q.x < br.x + br.w + 0.5 && br.x - 0.5 < q.x + q.w) obs.push([q.y, q.y + q.h]);
      });
      var vacant = function (yy) {
        for (var j = 0; j < obs.length; j++)
          if (yy < obs[j][1] + PAD && obs[j][0] - PAD < yy + br.h) return false;
        return true;
      };
      if (vacant(br.y)) return;              // 本来就不压：一个属性都不改（输出逐字节不变）
      /* 候选位置只取「紧贴某个障碍的上沿或下沿」—— 最优解必然贴着某个障碍，
         逐像素扫描只是把同一个答案算得更慢。 */
      var cand = [];
      for (z = 0; z < obs.length; z++) { cand.push(obs[z][1] + PAD); cand.push(obs[z][0] - PAD - br.h); }
      cand = cand.filter(function (yy) { return yy >= M.t + 1 && yy + br.h <= M.t + ph - 1; });
      cand.sort(function (a, b) { return Math.abs(a - br.y) - Math.abs(b - br.y); });   // 挪得越少越好
      for (z = 0; z < cand.length; z++) if (vacant(cand[z])) {
        var ny = +(bk.ay + (cand[z] - br.y)).toFixed(2);
        bk.el.setAttribute('y', ny);
        bk.el.setAttribute('transform', 'rotate(-90 ' + bk.ax + ' ' + ny + ')');
        return;
      }
    });
    /* 挪不开的（以及被断点竖线本身划穿的）柱值标签，改用 z 序保命：把它 appendChild
       回 g 的末尾，它自带的白色描边就能在红字/红虚线上打个洞，数字先保住。
       断点线是「放在系列之后画」才压得住柱和折线的，代价就是也压在数值标签上面
       —— lpla Ex9 的 $45.8 就是被这条虚线拦腰划断的，不是被标签压的。
       手法与上面 y/y 那段一样（appendChild 已有节点 = 移到最后），只动 z 序、不动几何，
       所以 QA 的重叠面积照旧记账，它解决的是「能不能读出来」而不是「有没有重叠」。
       只提横排文字：竖排的都是红色注记，互相盖不出可读性问题。 */
    brks.forEach(function (bk) {
      var lr = bk.el && textRect(bk.el);
      g.querySelectorAll('text').forEach(function (o) {
        if (o === bk.el || o.parentNode !== g) return;
        if ((o.getAttribute('transform') || '').indexOf('rotate') >= 0) return;
        var q = textRect(o);
        if (!q) return;
        var onLine = q.y < M.t + ph && q.y + q.h > M.t &&
                     q.x - 0.6 <= bk.x && bk.x <= q.x + q.w + 0.6;
        var onLab = lr && q.x < lr.x + lr.w && lr.x < q.x + q.w &&
                    q.y < lr.y + lr.h && lr.y < q.y + q.h;
        if (onLine || onLab) g.appendChild(o);
      });
    });

    /* 次轴末点读数 vs 右轴刻度：冲突时让刻度让位。
       末点读数按构造落在它自己那个值的轴高度上，右轴刻度也在同一列，两者数值一接近
       就必然叠字 —— 实测 6 页 18 处（'+5.0pp × +5.1pp'、'50% × 52%'、'20% × 22%'…）。
       让读数让位是错的：它是真实数据，而刻度只是标尺，少一格刻度读者照样能读出量级。 */
    if (priorityLabs.length) {
      var hit = function (a, b) {
        return a.x < b.x + b.width + 1 && b.x < a.x + a.width + 1 &&
               a.y < b.y + b.height + 1 && b.y < a.y + a.height + 1;
      };
      priorityLabs.forEach(function (p) {
        if (!p.getBBox) return;
        rtickEls.forEach(function (t) {                 // 刻度让位
          if (t.parentNode && hit(p.getBBox(), t.getBBox())) t.parentNode.removeChild(t);
        });
        /* 还撞上的一定是别的**真实数据标签**（柱顶数值），那种不能删。
           柱顶标签锚死在自己的柱子上，末点读数是浮动的 —— 让读数让开。
           实测 6 处：schw Ex6「490 × 52%」、cboe Ex4「$7.3 × 44%」、axp Ex2「$113.8 × 7.6%」… */
        var others = [];
        g.querySelectorAll('text').forEach(function (t) {
          if (t !== p && !(t.getAttribute('transform') || '').indexOf) return;
          if (t !== p && (t.getAttribute('transform') || '').indexOf('rotate') < 0) others.push(t);
        });
        for (var k = 0; k < 6; k++) {
          var pb = p.getBBox(), clash = null;
          for (var q = 0; q < others.length; q++) {
            if (others[q].parentNode && hit(pb, others[q].getBBox())) { clash = others[q]; break; }
          }
          if (!clash) break;
          // 优先往下让（末点读数原本就在点的右下方）；顶到画布底就改往上
          var dy = (pb.y + pb.height + 10 < M.t + ph) ? 9 : -9;
          p.setAttribute('y', parseFloat(p.getAttribute('y')) + dy);
        }
        /* 推完要**再清一次刻度**：让开柱顶标签之后，读数可能正好落到另一条刻度上
           （实测 cboe Ex4 就是这样 —— 躲开 $7.3 之后压上了 40%）。 */
        rtickEls.forEach(function (t) {
          if (t.parentNode && hit(p.getBBox(), t.getBBox())) t.parentNode.removeChild(t);
        });
      });
    }

    /* hover：整段 band 命中，tooltip 列出该期全部系列 */
    var tip = host.parentElement.querySelector('.tip');
    if (tip) {
      var cross = el('line', { y1: M.t, y2: M.t + ph, stroke: C.AXIS, 'stroke-width': 1,
        opacity: 0, 'stroke-dasharray': '2 2' }, svg);
      var hit = el('g', {}, svg), rows = seriesRows(ex);
      for (i = 0; i < n; i++) {
        (function (idx) {
          var r = el('rect', { x: M.l + band * idx, y: M.t, width: band, height: ph,
            fill: 'transparent', style: 'cursor:crosshair' }, hit);
          r.addEventListener('mouseenter', function () {
            cross.setAttribute('x1', Xc(idx)); cross.setAttribute('x2', Xc(idx));
            cross.setAttribute('opacity', 1);
            var html = '<div class="th">' + labels[idx] + '</div>', j;
            for (j = 0; j < rows.length; j++) {
              var vr = rows[j].values[idx];
              html += '<div class="row"><i style="background:' + rows[j].color + '"></i><span>' +
                rows[j].name + '</span><b>' +
                (vr == null || !isFinite(vr) ? '—' : rows[j].fmt(vr)) + '</b></div>';
            }
            /* 斜纹柱（如 53 周月份）在 tooltip 里补一句为什么它与相邻柱不可比 */
            if (markSet && markSet[idx] && ex.mark_note)
              html += '<div class="row" style="font-style:italic;opacity:.85"><span>' +
                ex.mark_note + '</span></div>';
            tip.innerHTML = html; tip.style.opacity = 1;
            var tw = tip.offsetWidth, px = Xc(idx) / W * host.clientWidth;
            tip.style.left = Math.max(2, Math.min(host.clientWidth - tw - 2, px - tw / 2)) + 'px';
            tip.style.top = '0px';
          });
        }(i));
      }
      hit.addEventListener('mouseleave', function () {
        tip.style.opacity = 0; cross.setAttribute('opacity', 0);
      });
    }
  }

  function seriesRows(ex) {
    var f = fmtOf(ex.fmt || ex.yfmt), out = [], i;
    if (ex.kind === 'bar_line' || ex.kind === 'bar_line_dual') {
      out.push({ name: ex.bar.name, color: col(ex.bar.color), values: ex.bar.values,
        fmt: fmtOf(ex.bar.yfmt || ex.yfmt) });
      out.push({ name: ex.line.name, color: col(ex.line.color), values: ex.line.values,
        fmt: fmtOf(ex.line.yfmt || ex.yfmt) });
    } else if (ex.kind === 'lines' || ex.kind === 'lines_endlabels') {
      for (i = 0; i < ex.series.length; i++)
        out.push({ name: ex.series[i].name, color: col(ex.series[i].color),
          values: ex.series[i].values, fmt: f });
    } else if (ex.kind === 'stacked_dual') {
      for (i = 0; i < ex.stacks.length; i++)
        out.push({ name: ex.stacks[i].name, color: col(ex.stacks[i].color),
          values: ex.stacks[i].values, fmt: FMT.f0c });
      out.push({ name: ex.line.name, color: col(ex.line.color), values: ex.line.values, fmt: FMT.pct1 });
    } else if (ex.kind === 'diverging_bars') {
      out.push({ name: 'Reported − Core', color: C.NAVY, values: ex.values, fmt: f });

    /* ── 新图型：表格视图与 tooltip 都吃这里的行，缺一个就是「切过去一片空白」 ── */
    } else if (ex.kind === 'year_lines') {
      var yc = yearColors(ex);
      for (i = 0; i < ex.series.length; i++)
        out.push({ name: ex.series[i].name, color: yc[i], values: ex.series[i].values, fmt: f });
    } else if (ex.kind === 'qtr_bar') {
      out.push({ name: ex.legend || ex.ylab || '季度合计', color: C.NAVY, values: ex.values,
        fmt: fmtOf(ex.fmt || ex.label_fmt) });
      if (ex.line && ex.line.values)
        /* 同样走 lineVals()：图上抹掉的未满季 y/y，表格与 tooltip 也必须是「—」。
           两边不一致时，人会以为图画漏了，反而去信那个本来就不可比的数。 */
        out.push({ name: ex.line.name || 'y/y', color: col(ex.line.color || 'GREEN'),
          values: lineVals(ex), fmt: fmtOf(ex.line.yfmt || 'pct0') });
    } else if (ex.kind === 'seasonality') {
      var bs = ex.base || {}, as = ex.actual || {};
      out.push({ name: bs.name || '同月均值', color: col(bs.color || 'GRAY'),
        values: bs.values || [], fmt: f });
      out.push({ name: as.name || '实际', color: col(as.color || 'MBLUE'),
        values: as.values || [], fmt: f });
    } else if (ex.kind === 'bridge_bar') {
      for (i = 0; i < ex.stacks.length; i++)
        out.push({ name: ex.stacks[i].name, color: col(ex.stacks[i].color),
          values: ex.stacks[i].values, fmt: f });
      out.push({ name: (ex.net && ex.net.name) || 'Net change', color: col(ex.net_color || 'INK'),
        values: bridgeNet(ex, stackLen(ex)), fmt: f });
    } else if (ex.kind === 'grouped_bars') {
      var gd = ['BLUE', 'NAVY', 'MBLUE', 'GRAY'];
      for (i = 0; i < ex.groups.length; i++)
        out.push({ name: ex.groups[i].name, color: col(ex.groups[i].color || gd[i % gd.length]),
          values: ex.groups[i].values, fmt: f });
      if (ex.line && ex.line.values)
        out.push({ name: ex.line.name || 'Error', color: col(ex.line.color || 'RED'),
          values: ex.line.values, fmt: fmtOf(ex.line.yfmt || 'pct1') });
    } else if (ex.kind === 'range_band') {
      var nm = ex.names || {};
      out.push({ name: nm.lo || 'Guidance low', color: C.BLUE, values: ex.lo || [], fmt: f });
      out.push({ name: nm.hi || 'Guidance high', color: C.MBLUE, values: ex.hi || [], fmt: f });
      out.push({ name: nm.actual || 'Actual', color: col(ex.actual_color || 'NAVY'),
        values: ex.actual || [], fmt: f });
      if (isNum(ex.qtd)) {
        var qv = [], qj = ex.qtd_at != null ? +ex.qtd_at : (ex.actual || []).length - 1;
        for (i = 0; i < (ex.actual || []).length; i++) qv.push(i === qj ? ex.qtd : null);
        out.push({ name: nm.qtd || 'Quarter-to-date', color: C.RED, values: qv, fmt: f });
      }
    } else {
      out.push({ name: ex.legend || ex.ylab || '数值',
        color: ex.kind === 'gs_bar' ? C.BLUE : C.NAVY, values: ex.values, fmt: f });
      /* gs_bar 开了次轴 y/y 时，表格视图与 tooltip 都要有这一行 ——
         图上有、表里没有，读者会以为图画错了。 */
      var yq = ex.kind === 'gs_bar' ? rhsOf(ex) : null;
      if (yq) out.push({ name: yq.name || 'y/y', color: col(yq.color || 'GOLD'),
        values: yq.values, fmt: fmtOf(yq.yfmt || 'pct0') });
    }
    return out;
  }

  function legendHTML(ex) {
    var items = [], i;
    if (ex.kind === 'bar_line_dual') {
      /* PDF 里双轴图的图例是显式 h1+h2（柱在前、线在后） */
      items.push(['sq', col(ex.bar.color), ex.bar.name]);
      items.push(['line', col(ex.line.color), ex.line.name]);
    } else if (ex.kind === 'bar_line') {
      /* 单轴图走 matplotlib get_legend_handles_labels：线在前、柱在后 */
      items.push(['line', col(ex.line.color), ex.line.name]);
      items.push(['sq', col(ex.bar.color), ex.bar.name]);
    } else if (ex.kind === 'lines' || ex.kind === 'lines_endlabels') {
      for (i = 0; i < ex.series.length; i++)
        items.push(['line', col(ex.series[i].color), ex.series[i].name]);
    } else if (ex.kind === 'gs_bar') {
      items.push(['sq', C.BLUE, ex.legend]);
      /* 给了 ex.yoy 就是次轴同比折线，均线那条虚线根本没画，图例也不能留 */
      var yl = rhsOf(ex);
      if (yl) items.push(['line', col(yl.color || 'GOLD'), yl.name || 'y/y (RHS)']);
      else items.push(['dash', C.NAVY, 'Prior 12mo Avg.']);
    } else if (ex.kind === 'gs_line_avg') {
      items.push(['line', C.NAVY, ex.legend]);
      items.push(['dash', C.BLUE, ex.avg_label || 'Prior 12mo Avg.']);
    } else if (ex.kind === 'stacked_dual') {
      for (i = 0; i < ex.stacks.length; i++)
        items.push(['sq', col(ex.stacks[i].color), ex.stacks[i].name]);
      items.push(['line', col(ex.line.color), ex.line.name]);
    } else if (ex.kind === 'diverging_bars') {
      items.push(['sq', C.NAVY, 'Reported > Core（油汇顺风）']);
      items.push(['sq', C.RED, 'Reported < Core（油汇拖累）']);

    /* ── 新图型 ── */
    } else if (ex.kind === 'heat_matrix') {
      /* 矩阵没有系列可列，图例改成一条色标 + 两端真值 —— 否则读者只能靠格内数字，
         看不出「这一格算高还是低」是相对什么定的。 */
      var hs = heatScale(ex), hf = fmtOf(ex.fmt || 'f1');
      items.push(['grad', hs.loc + ',' + C.WHITE + ',' + hs.hic,
        hf(hs.lo) + ' → ' + hf(hs.hi) + '（5–95 分位色标）']);
    } else if (ex.kind === 'year_lines') {
      var ycl = yearColors(ex);
      for (i = 0; i < ex.series.length; i++) items.push(['line', ycl[i], ex.series[i].name]);
    } else if (ex.kind === 'qtr_bar') {
      items.push(['sq', C.NAVY, ex.legend || 'Complete quarter']);
      if (isNum(ex.partial_months) && +ex.partial_months > 0 &&
          +ex.partial_months < (ex.qtr_months || 3))
        items.push(['sq', C.BLUE, 'QTD (' + ex.partial_months + ' of ' +
          (ex.qtr_months || 3) + ' months)']);
      if (ex.line && ex.line.values)
        items.push(['line', col(ex.line.color || 'GREEN'), ex.line.name || 'y/y (RHS)']);
    } else if (ex.kind === 'seasonality') {
      items.push(['sq', col(((ex.base || {}).color) || 'GRAY'),
        (ex.base || {}).name || 'Prior-year same-month avg.']);
      items.push(['sq', col(((ex.actual || {}).color) || 'MBLUE'),
        (ex.actual || {}).name || 'Actual']);
    } else if (ex.kind === 'bridge_bar') {
      for (i = 0; i < ex.stacks.length; i++)
        items.push(['sq', col(ex.stacks[i].color), ex.stacks[i].name]);
      items.push(['dia', col(ex.net_color || 'INK'), (ex.net && ex.net.name) || 'Net change']);
    } else if (ex.kind === 'grouped_bars') {
      var gdf = ['BLUE', 'NAVY', 'MBLUE', 'GRAY'];
      for (i = 0; i < ex.groups.length; i++)
        items.push(['sq', col(ex.groups[i].color || gdf[i % gdf.length]), ex.groups[i].name]);
      if (ex.line && ex.line.values)
        items.push(['line', col(ex.line.color || 'RED'), ex.line.name || 'Error (RHS)']);
    } else if (ex.kind === 'range_band') {
      var rn = ex.names || {};
      items.push(['sq', C.BLUE, rn.range || 'Guidance range']);
      items.push(['dia', col(ex.actual_color || 'NAVY'), rn.actual || 'Actual']);
      if (isNum(ex.qtd)) items.push(['odia', C.RED, rn.qtd || 'Quarter-to-date']);
    }
    if (!items.length) return '';
    /* 新增的三种图示（菱形/空心菱形/色标）只用行内样式，不动 style.css ——
       那份文件是三个站共用的，为了图例改它等于同时改已上线的两个站。 */
    return '<div class="legend">' + items.map(function (it) {
      var dia = 'width:8px;height:8px;transform:rotate(45deg)';
      var sw = it[0] === 'sq' ? '<i class="sq" style="background:' + it[1] + '"></i>'
        : it[0] === 'dash' ? '<i class="dash" style="border-top-color:' + it[1] + '"></i>'
        : it[0] === 'dia' ? '<i style="background:' + it[1] + ';' + dia + '"></i>'
        : it[0] === 'odia' ? '<i style="background:' + C.WHITE + ';border:1.4px solid ' +
            it[1] + ';' + dia + '"></i>'
        : it[0] === 'grad' ? '<i style="width:54px;height:9px;background:linear-gradient(90deg,' +
            it[1] + ')"></i>'
        : '<i style="background:' + it[1] + '"></i>';
      return '<span>' + sw + it[2] + '</span>';
    }).join('') + '</div>';
  }

  /* 表格视图的存在意义就是逐条核对，所以比轴刻度多给一位小数
     （轴上写 $29 是对的，表格里应看到 29.24）。 */
  var PRECISE = { usd0: 'usd2', usd1: 'usd2', pct0: 'pct1', pct0z: 'pct1',
                  pp0: 'pp1', f0: 'f1', x0: 'f0' };
  function precise(fn) {
    var k;
    for (k in FMT) if (FMT[k] === fn && PRECISE[k]) return FMT[PRECISE[k]];
    return fn;
  }

  /* 热力矩阵的表格视图不是「期间 × 系列」，而是把矩阵原样铺开（行=年、列=月），
     不给它单独一支就是切到表格一片空白。 */
  function heatTable(ex) {
    var cols = ex.cols || MONTHS, rows = ex.rows || [], m = ex.matrix || [];
    var fmt = precise(fmtOf(ex.fmt || 'f1')), i, j, v;
    var h = '<div class="tblwrap"><table><caption>Exhibit ' + ex.n +
      ' — 表格视图（与图同源数值）</caption><thead><tr><th>' + (ex.row_head || '年') + '</th>';
    for (j = 0; j < cols.length; j++) h += '<th>' + cols[j] + '</th>';
    h += '</tr></thead><tbody>';
    for (i = 0; i < rows.length; i++) {
      h += '<tr><td>' + rows[i] + '</td>';
      for (j = 0; j < cols.length; j++) {
        v = (m[i] || [])[j];
        h += '<td>' + (isNum(v) ? fmt(+v) : '—') + '</td>';
      }
      h += '</tr>';
    }
    return h + '</tbody></table></div>';
  }

  function tableHTML(ex, labels) {
    if (ex.kind === 'heat_matrix') return heatTable(ex);
    var rows = seriesRows(ex), i, j;
    var h = '<div class="tblwrap"><table><caption>Exhibit ' + ex.n +
      ' — 表格视图（与图同源数值）</caption><thead><tr><th>期间</th>';
    for (j = 0; j < rows.length; j++) h += '<th>' + rows[j].name + '</th>';
    h += '</tr></thead><tbody>';
    for (i = 0; i < labels.length; i++) {
      h += '<tr><td>' + labels[i] + '</td>';
      for (j = 0; j < rows.length; j++) {
        var v = rows[j].values[i];
        h += '<td>' + (v == null || !isFinite(v) ? '—' : precise(rows[j].fmt)(v)) + '</td>';
      }
      h += '</tr>';
    }
    return h + '</tbody></table></div>';
  }

  var registry = [];
  window.Exhibits = {
    card: function (mount, ex, opt) {
      opt = opt || {};
      var labels = ex.xlabels || opt.xlabels || [];
      var card = document.createElement('section');
      card.className = 'card';
      card.innerHTML =
        '<header><h3>Exhibit ' + ex.n + ': ' + ex.title + '</h3>' +
        '<button class="toggle" type="button">表格</button></header>' +
        legendHTML(ex) +
        '<div class="plot"><div class="tip"></div><div class="host"></div></div>' +
        '<div class="tv" hidden></div>' +
        (ex.note ? '<p class="src"><b>Note:</b> ' + ex.note + '</p>' : '') +
        '<p class="src">' + (opt.source || '') +
        (ex.src_extra ? '<br>' + ex.src_extra : '') + '</p>';
      mount.appendChild(card);
      var host = card.querySelector('.host'), tv = card.querySelector('.tv'),
          btn = card.querySelector('.toggle'), mode = 'chart';
      function render() {
        if (mode === 'chart') draw(host, ex, opt);
        else tv.innerHTML = tableHTML(ex, labels);
      }
      btn.addEventListener('click', function () {
        mode = mode === 'chart' ? 'table' : 'chart';
        btn.textContent = mode === 'chart' ? '表格' : '图表';
        card.querySelector('.plot').hidden = mode === 'table';
        tv.hidden = mode === 'chart';
        render();
      });
      registry.push(render);
      render();
    },
    redrawAll: function () { registry.forEach(function (f) { f(); }); },
    /* 对外只读：字号缩放的两个端点（窄卡 / 通栏）。轴刻度不再靠字号识别，
       改由 text 上的 data-tick 属性标记，见 draw() 里画刻度那两处。 */
    FS_MIN: FS_MIN,
    FS_MAX: FS_MAX,
  };

  var t;
  window.addEventListener('resize', function () {
    clearTimeout(t); t = setTimeout(window.Exhibits.redrawAll, 150);
  });
})();
