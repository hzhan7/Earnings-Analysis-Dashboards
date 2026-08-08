#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""整站视觉 QA 跑批 —— 把「只有渲染出来才看得见」的缺陷变成机器判据。

    python3 tools/visual_qa.py --all
    python3 tools/visual_qa.py --page tmx

只读渲染，不改仓里任何东西。零第三方依赖（标准库 + 本机 Chrome）。
判据的阈值推导、已知误报、能力边界见 docs/VISUAL_QA_RUNNER.md。

工作方式
--------
1. 起一个临时 http server（127.0.0.1 + 随机端口，跑完关掉）。它做两件事：
   a. 静态服务仓根；
   b. 给每个 .html **在内存里**注入一小段错误捕获 shim（不落盘、不改仓里的文件），
      这样 iframe 里的 JS 报错能被读到；
   c. 从内存吐一个 /__qa__/probe.html 测量页（同样不落盘）。
2. headless Chrome 打开 probe.html，probe 用同源 iframe 装载被测页、等渲染稳定，
   再用 getBoundingClientRect / getBBox / getScreenCTM 逐元素量几何，
   最后把 JSON **POST 回**这个 server（不用 --dump-dom，理由见 probe 里的注释）。
3. Python 侧按阈值定级、出 report.json / report.md，🔴 页另出整页截图。

为什么是 iframe 而不是直接开被测页：要在页面里跑测量脚本就得注入 JS，
headless Chrome 没有注入入口。docs/verify/qa/qa_geom.html 上一轮用的就是这条路，
这里沿用，并补上它的四个短板：
  1. 旋转文字用 OBB（有向包围盒）而不是 AABB —— 上一轮直接跳过所有 rotate 文字，
     等于放弃「45° 类别标签压字」「竖排断点标签压字」这两整类；
  2. 刻度等距改判「像素-数值比恒定」而不是「数值差相等」—— dropClashingTicks 故意
     让位漏掉一格时不再假阳（上一轮全站 71 条告警无一真错）；
  3. 补上控制台错误、横向滚动、NaN 属性、exhibit 数对账；
  4. 按严重度定级并给退出码，页名从 data/roster.js 自动发现而不是写死 12 个。
"""

import argparse
import http.server
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DEFAULT_OUT = "/tmp/visual_qa"

# ── 阈值 ────────────────────────────────────────────────────────────────────
# 每一条都有几何推导或实测依据；改之前先读 docs/VISUAL_QA_RUNNER.md §阈值推导。
THRESH = {
    # 1) SVG 图元越出画布。
    #    本底噪声：txt() 默认给每个字加 2.4px 白色描边（charts.js 的 txt()）→ 单边 1.2px；
    #    描边宽随 charts.js 的 FS 缩放（FS=1.30 → 3.12px，单边 1.56px）。
    #    图元最粗 stroke-width 1.8 → 单边 0.9px；再加 ~0.5px 抗锯齿与字形右侧承。
    #    本底 ≈ 1.56+0.9+0.5 ≈ 3.0px，取 6px 仍留 2 倍余量（实测全站无一张干净图超过 4px）。
    "overflow_floor": 6.0,
    #    🔴 线：24px。半栏图高 228–360px，24px ≈ 一行 12px 正文的两倍，
    #    到这个量级必然压到卡片下方的 Note 或隔壁栏；或占画布高 ≥10%（页面级破相，
    #    如 miax Ex13 的「柱画出画布 3.8 个图高」）。
    "overflow_red_px": 24.0,
    "overflow_red_frac": 0.10,

    # 2) <text> 越出所在 .card。卡片之间横向 gap 30px、纵向 26px（style.css:60），
    #    所以越界 6px 内不会碰到邻居；同样取 6px 起报，≥15px（半个 gap）判 🔴。
    "textcard_floor": 6.0,
    "textcard_red_px": 15.0,

    # 3) 文字互相压字，判据是**墨迹框**（不是 em 框）的重叠面积。
    #    Arial: ascent 0.905em / descent 0.212em，em 框高 1.117em；数字与大写字母
    #    只占基线上 0.716em。故墨迹框 = em 框自顶部内缩 (0.905-0.716)/1.117 = 16.9%、
    #    自底部内缩 0.212/1.117 = 19.0%，剩 64%。
    "ink_top": 0.169,
    "ink_bot": 0.190,
    #    9px 字的墨迹高 ≈ 0.716×9 = 6.4px。上一轮人工确认的真压字最轻的一处
    #    （db1 Ex14「80000000」×「76,941,267」）横向重叠 2.6px ⇒ 面积 ≈ 17px²。
    #    起报 8px²（≈1.2px 横向重叠，肉眼可见的「字碰字」下限），
    #    🟡 12px²，🔴 60px²（≈9.4px 横向重叠 ≈ 1.5 个字宽被完全盖住，必然读错数）。
    "overlap_floor": 8.0,
    "overlap_amber": 12.0,
    "overlap_red": 60.0,
    #    或者：重叠占较小那段文字墨迹面积的比例 ≥55% —— 近乎完全遮盖。
    "overlap_red_frac": 0.55,

    # 4) 轴刻度。像素-数值比 k=(Δ值)/(Δ像素) 在同一根轴上必须恒定。
    #    2.5 步长被印成整数时 Δ值 = 3,2,3,2 而 Δ像素恒定 ⇒ k 偏离 ±20%。
    #    dropClashingTicks 让位漏掉一格时 Δ值与 Δ像素同倍放大 ⇒ k 不变（不误报）。
    #    容差 5%：刻度值都是 [1,2,2.5,5,10]×10^k 的整倍数、可精确表示，
    #    真正的误差只来自 getBoundingClientRect 的亚像素，量级 <0.5px/40px = 1.2%。
    "axis_k_tol": 0.05,
    "axis_min_dy": 4.0,      # 两格刻度像素间距 <4px 时比值噪声太大，跳过

    # 5) 横向滚动条：documentElement.scrollWidth 超出 clientWidth 1px 以上。
    #    1px 是布局取整噪声。
    "hscroll_tol": 1.0,

    # 重复绘制：同内容 <text> 的墨迹框中心距 <1.5px 视为画了两遍。
    #    1.5px = 一个字号 9px 文字的 1/6 字宽，人眼完全分辨不出是两层。
    "dup_text_px": 1.5,

    # 几何自检：inkQuad 反算出的 AABB 中心与 getBoundingClientRect 中心
    #    差 >2px 说明 getScreenCTM 的变换算错了，此时压字结论不可信。
    "geom_selfcheck_px": 2.0,
}

VIEWPORTS = [1280, 768]   # 桌面 / 窄屏（style.css 的断点在 900px，768 落在窄屏侧）
VIEWPORT_H = 900

# ── 注入进被测页 <head> 的错误捕获 shim（内存注入，不写盘）────────────────────
ERR_SHIM = (
    "<script>(function(){window.__qaErr=[];"
    "function P(o){if(window.__qaErr.length<50)window.__qaErr.push(o);}"
    "window.addEventListener('error',function(e){"
    "P({k:e.message&&e.target===window?'error':'error',"
    "m:String(e.message||((e.target&&e.target.src)?('resource load failed: '+e.target.src):'unknown')),"
    "src:String(e.filename||''),ln:e.lineno|0,col:e.colno|0,"
    "stack:String((e.error&&e.error.stack)||'').slice(0,400)});},true);"
    "window.addEventListener('unhandledrejection',function(e){"
    "P({k:'unhandledrejection',m:String((e.reason&&(e.reason.message||e.reason))||''),"
    "src:'',ln:0,col:0,stack:String((e.reason&&e.reason.stack)||'').slice(0,400)});});"
    "var _e=console.error;console.error=function(){"
    "P({k:'console.error',m:Array.prototype.map.call(arguments,String).join(' ').slice(0,400),"
    "src:'',ln:0,col:0,stack:''});return _e.apply(console,arguments);};"
    "var _w=console.warn;console.warn=function(){"
    "P({k:'console.warn',m:Array.prototype.map.call(arguments,String).join(' ').slice(0,400),"
    "src:'',ln:0,col:0,stack:''});return _w.apply(console,arguments);};"
    "})();</script>"
)

# ── probe 页（内存服务，不写盘）──────────────────────────────────────────────
PROBE_HTML = r"""<!doctype html>
<meta charset="utf-8"><title>qa-probe</title>
<style>html,body{margin:0;padding:0;overflow:hidden;background:#fff}
iframe{border:0;display:block}
#out{position:fixed;left:-99999px;top:0;width:1px;height:1px;overflow:hidden}</style>
<pre id="out">PENDING</pre>
<script>
(function(){
"use strict";
var CFG = __CFG__;
var Q = {};
location.search.slice(1).split('&').forEach(function(kv){
  if(!kv) return; var a = kv.split('='); Q[decodeURIComponent(a[0])] = decodeURIComponent(a[1]||'');
});
var PATH = Q.path || '/';
var out = document.getElementById('out');
var emitted = false;

/* 结果**回传**给起它的那个 http server，而不是等 --dump-dom 把 <pre> 吐出来。
   为什么（Chrome 151 实测，见 docs/VISUAL_QA_RUNNER.md §2.b）：
   --virtual-time-budget 本身还好用，但**虚拟时间下 rAF 不回调** —— 等待链只要
   结尾是 rAF，测量就永远不执行，--dump-dom 吐出一份结构完整、只是 <pre> 还写着
   PENDING 的 DOM，不报错也不超时，是个静默失败。
   POST 回传后不再需要虚拟时间，rAF 与 document.fonts.ready 正常工作，
   能真等一帧画完再量版面；也不用再关心 Chrome 什么时候吐 DOM。 */
function emit(o){
  if (emitted) return; emitted = true;
  var s;
  try { s = JSON.stringify(o); } catch (e) { s = '{"fatal":"stringify: ' + String(e).replace(/"/g,"'") + '"}'; }
  out.textContent = 'DONE ' + s.length;
  document.title = 'qa-done';
  try {
    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/__qa__/result?id=' + encodeURIComponent(Q.id || 'x'), true);
    xhr.setRequestHeader('Content-Type', 'application/json;charset=utf-8');
    xhr.send(s);
  } catch (e) {}
}
window.onerror = function(m, src, l, c){ emit({fatal: 'harness onerror: ' + m + ' @' + l + ':' + c}); };

/* ── 几何工具 ─────────────────────────────────────────────────────────── */
function sarea(P){ var a=0,i,q; for(i=0;i<P.length;i++){ q=P[(i+1)%P.length];
  a += P[i][0]*q[1] - q[0]*P[i][1]; } return a/2; }

/* Sutherland-Hodgman 凸多边形裁剪。clip 归一成正signed area（此时内侧为 cross>=0）。 */
function clipPoly(sub, clip){
  if (sarea(clip) < 0) clip = clip.slice().reverse();
  var outp = sub, i, j;
  for (i = 0; i < clip.length; i++){
    var a = clip[i], b = clip[(i+1)%clip.length], inp = outp; outp = [];
    if (!inp.length) break;
    for (j = 0; j < inp.length; j++){
      var P = inp[j], R = inp[(j+1)%inp.length];
      var sp = (b[0]-a[0])*(P[1]-a[1]) - (b[1]-a[1])*(P[0]-a[0]);
      var sq = (b[0]-a[0])*(R[1]-a[1]) - (b[1]-a[1])*(R[0]-a[0]);
      if (sp >= 0) outp.push(P);
      if ((sp > 0 && sq < 0) || (sp < 0 && sq > 0)){
        var t = sp/(sp-sq);
        outp.push([P[0]+t*(R[0]-P[0]), P[1]+t*(R[1]-P[1])]);
      }
    }
  }
  return outp;
}
function overlapArea(A, B){ var c = clipPoly(A, B); return c.length < 3 ? 0 : Math.abs(sarea(c)); }
function quadAABB(P){
  var x0=1e18,y0=1e18,x1=-1e18,y1=-1e18,i;
  for(i=0;i<P.length;i++){ if(P[i][0]<x0)x0=P[i][0]; if(P[i][0]>x1)x1=P[i][0];
                           if(P[i][1]<y0)y0=P[i][1]; if(P[i][1]>y1)y1=P[i][1]; }
  return {l:x0,t:y0,r:x1,b:y1};
}
/* 文字的**墨迹**四边形（含自身 rotate），坐标系与 getBoundingClientRect 一致。
   用 getBBox（不含描边、不含自身 transform）+ getScreenCTM（含自身 transform）。 */
function inkQuad(t){
  var bb; try { bb = t.getBBox(); } catch(e){ return null; }
  if (!bb || bb.width <= 0 || bb.height <= 0) return null;
  var m; try { m = t.getScreenCTM(); } catch(e){ return null; }
  if (!m) return null;
  var x0 = bb.x, x1 = bb.x + bb.width;
  var y0 = bb.y + bb.height*CFG.ink_top, y1 = bb.y + bb.height*(1-CFG.ink_bot);
  var pts = [[x0,y0],[x1,y0],[x1,y1],[x0,y1]];
  var o = [], i;
  for (i=0;i<4;i++) o.push([m.a*pts[i][0] + m.c*pts[i][1] + m.e,
                            m.b*pts[i][0] + m.d*pts[i][1] + m.f]);
  return o;
}
function rectQuad(r){ return [[r.left,r.top],[r.right,r.top],[r.right,r.bottom],[r.left,r.bottom]]; }
function isect(a, b){ return !(a.r <= b.left || a.l >= b.right || a.b <= b.top || a.t >= b.bottom); }

function desc(el){
  var s = el.tagName ? el.tagName.toLowerCase() : '?';
  var cn = el.getAttribute ? (el.getAttribute('class')||'') : '';
  if (el.id) s += '#' + el.id;
  if (cn) s += '.' + cn.trim().split(/\s+/).join('.');
  var t = (el.textContent||'').trim().replace(/\s+/g,' ');
  if (t) s += ' "' + t.slice(0,28) + '"';
  return s;
}
function txtOf(t){ return (t.textContent||'').trim().replace(/\s+/g,' '); }

/* 轴刻度标签解析。FMT 里的格式器只产出 数字 / 千分位 / 前缀$ / 后缀% pp X，
   没有 k/mn/bn 之类的量级后缀，所以剥掉这些符号后必须是纯数字，否则放弃该轴。 */
function parseTick(s){
  s = String(s).replace(/\u2212/g,'-').replace(/[,\s$+]/g,'')
               .replace(/(%|pp|X|x|×)$/,'');
  if (!/^-?\d*\.?\d+$/.test(s)) return null;
  var v = parseFloat(s);
  return isFinite(v) ? v : null;
}

/* ── 主检查 ───────────────────────────────────────────────────────────── */
function analyze(d, w){
  var R = {
    ok: true, path: PATH, vw: window.innerWidth, vh: window.innerHeight,
    media_dark: matchMedia('(prefers-color-scheme: dark)').matches,
    theme_detect: themeInfo(d),
    console_errors: (w.__qaErr || []).slice(0, 50),
    content_height: 0, svg_count: 0, payload_exhibits: null,
    hscroll: null, defects: [], geom_selfcheck_fail: 0, notes: []
  };
  var de = d.documentElement, bd = d.body;
  R.content_height = Math.max(de.scrollHeight, bd ? bd.scrollHeight : 0);
  R.svg_count = d.querySelectorAll('.plot .host svg').length;

  var payload = null;
  try { payload = w.DASH; } catch(e){}
  if (payload && payload.exhibits) R.payload_exhibits = payload.exhibits.length;
  var byN = {};
  if (payload && payload.exhibits)
    payload.exhibits.forEach(function(e){ byN[String(e.n)] = e; });

  /* 5) 页面横向滚动 */
  var sw = Math.max(de.scrollWidth, bd ? bd.scrollWidth : 0), cw = de.clientWidth;
  if (sw > cw + CFG.hscroll_tol){
    var cul = [], all = d.body.getElementsByTagName('*'), i;
    for (i = 0; i < all.length; i++){
      var r = all[i].getBoundingClientRect();
      if (!r.width && !r.height) continue;
      var ov = Math.max(r.right - cw, -r.left);
      if (ov > CFG.hscroll_tol) cul.push({ el: desc(all[i]), over: +ov.toFixed(1) });
    }
    cul.sort(function(a,b){ return b.over - a.over; });
    R.hscroll = { scrollWidth: +sw.toFixed(1), clientWidth: +cw.toFixed(1),
                  over: +(sw - cw).toFixed(1), culprits: cul.slice(0, 6) };
  }

  /* 逐卡片 */
  var cards = d.querySelectorAll('section.card');
  for (var ci = 0; ci < cards.length; ci++){
    var card = cards[ci];
    var svg = card.querySelector('.plot .host > svg');
    if (!svg) continue;
    var h3 = card.querySelector('header h3');
    var ttl = h3 ? txtOf(h3) : '';
    var mm = /Exhibit\s+([0-9A-Za-z.\-]+)\s*[:：]/.exec(ttl);
    var exn = mm ? mm[1] : null;
    var ex = exn != null ? byN[exn] : null;
    var ctx = { ex_n: exn, title: ttl.replace(/^Exhibit\s+[0-9A-Za-z.\-]+\s*[:：]\s*/, '').slice(0, 90),
                kind: ex ? (ex.kind || '') : '', svg_i: ci };
    checkOne(R, card, svg, ctx, ex);
  }
  return R;
}

function push(R, ctx, type, sev_px, obj){
  var o = { ex: ctx.ex_n, title: ctx.title, kind: ctx.kind, type: type, px: sev_px };
  for (var k in obj) o[k] = obj[k];
  R.defects.push(o);
}

function checkOne(R, card, svg, ctx, ex){
  var sr = svg.getBoundingClientRect(), cr = card.getBoundingClientRect();
  ctx.canvas = { w: +sr.width.toFixed(1), h: +sr.height.toFixed(1) };
  ctx.page_y = Math.round(sr.top);

  /* ── 1) 图元越出 <svg> 视口 ──────────────────────────────────────────── */
  var nodes = svg.querySelectorAll('path,rect,circle,line,polyline,polygon,text,image');
  var worst = {}, i, n, b, sides = ['top','bottom','left','right'];
  var texts = [], nonFinite = 0;
  for (i = 0; i < nodes.length; i++){
    n = nodes[i];
    if (n.closest('defs')) continue;
    var av = ['x','y','x1','x2','y1','y2','width','height','cx','cy','d','points'];
    for (var ai = 0; ai < av.length; ai++){
      var vv = n.getAttribute(av[ai]);
      if (vv != null && /NaN|Infinity/.test(vv)) nonFinite++;
    }
    b = n.getBoundingClientRect();
    if (!b.width && !b.height) continue;
    var ov = { top: sr.top - b.top, bottom: b.bottom - sr.bottom,
               left: sr.left - b.left, right: b.right - sr.right };
    for (var si = 0; si < 4; si++){
      var s = sides[si];
      if (ov[s] > (worst[s] ? worst[s].px : 0)) worst[s] = { px: ov[s], el: desc(n) };
    }
    if (n.tagName.toLowerCase() === 'text') texts.push(n);
  }
  if (nonFinite)
    push(R, ctx, 'NON_FINITE_ATTR', nonFinite,
         { detail: nonFinite + ' 个图元属性里出现 NaN/Infinity', canvas: ctx.canvas, page_y: ctx.page_y });

  for (var si2 = 0; si2 < 4; si2++){
    var sd = sides[si2], wv = worst[sd];
    if (wv && wv.px > CFG.overflow_floor)
      push(R, ctx, 'SVG_OVERFLOW', +wv.px.toFixed(1),
           { side: sd, el: wv.el, canvas: ctx.canvas, page_y: ctx.page_y,
             frac: +(wv.px / Math.max(1, sr.height)).toFixed(3) });
  }

  /* ── 2) <text> 越出所在卡片；以及压在卡片正文（Note / 图例 / 标题）上 ─── */
  var proseEls = [];
  ['p.src', 'p.note', '.legend', 'header h3', '.toggle'].forEach(function(sel){
    var l = card.querySelectorAll(sel);
    for (var k = 0; k < l.length; k++) proseEls.push(l[k]);
  });
  var quads = [], aabbs = [], strs = [];
  for (i = 0; i < texts.length; i++){
    var t = texts[i], tb = t.getBoundingClientRect();
    var outC = Math.max(cr.top - tb.top, tb.bottom - cr.bottom,
                        cr.left - tb.left, tb.right - cr.right);
    if (outC > CFG.textcard_floor)
      push(R, ctx, 'TEXT_OUT_OF_CARD', +outC.toFixed(1),
           { text: txtOf(t), page_y: Math.round(tb.top), canvas: ctx.canvas });

    var q = inkQuad(t);
    if (q){
      var ab = quadAABB(q);
      // 几何自检：墨迹框中心应落在 client rect 中心附近
      if (Math.abs((ab.l+ab.r)/2 - (tb.left+tb.right)/2) > CFG.geom_selfcheck_px ||
          Math.abs((ab.t+ab.b)/2 - (tb.top+tb.bottom)/2) > CFG.geom_selfcheck_px)
        R.geom_selfcheck_fail++;
      quads.push(q); aabbs.push(ab); strs.push(txtOf(t));

      // 文字压住卡片里的 HTML 正文（45° 类别标签伸出画布压 Note 的典型症状）
      for (var pi = 0; pi < proseEls.length; pi++){
        var pr = proseEls[pi].getBoundingClientRect();
        if (!pr.width || !pr.height) continue;
        if (!isect(ab, pr)) continue;
        var a2 = overlapArea(q, rectQuad(pr));
        if (a2 > CFG.overlap_floor)
          push(R, ctx, 'TEXT_ON_PROSE', +a2.toFixed(1),
               { text: txtOf(t), over: desc(proseEls[pi]).slice(0, 60),
                 page_y: Math.round(tb.top), canvas: ctx.canvas });
      }
    } else { quads.push(null); aabbs.push(null); strs.push(txtOf(t)); }
  }

  /* ── 3) 文字互相压字（墨迹框 OBB 相交面积；先用 AABB 粗筛）───────────── */
  for (i = 0; i < quads.length; i++){
    if (!quads[i]) continue;
    for (var j = i + 1; j < quads.length; j++){
      if (!quads[j]) continue;
      var A = aabbs[i], B = aabbs[j];
      if (A.r <= B.l || A.l >= B.r || A.b <= B.t || A.t >= B.b) continue;
      var ar = overlapArea(quads[i], quads[j]);
      if (ar <= CFG.overlap_floor) continue;
      var sA = Math.abs(sarea(quads[i])), sB = Math.abs(sarea(quads[j]));
      var frac = ar / Math.max(1e-6, Math.min(sA, sB));
      var cA = [(A.l+A.r)/2, (A.t+A.b)/2], cB = [(B.l+B.r)/2, (B.t+B.b)/2];
      var dc = Math.hypot(cA[0]-cB[0], cA[1]-cB[1]);
      if (strs[i] === strs[j] && dc < CFG.dup_text_px)
        push(R, ctx, 'DUPLICATE_TEXT', +ar.toFixed(1),
             { text: strs[i], center_dist: +dc.toFixed(2),
               page_y: Math.round(A.t), canvas: ctx.canvas });
      else
        push(R, ctx, 'TEXT_OVERLAP', +ar.toFixed(1),
             { a: strs[i], b: strs[j], frac: +frac.toFixed(2),
               page_y: Math.round(Math.min(A.t, B.t)), canvas: ctx.canvas });
    }
  }

  /* ── 重复绘制的**虚线**（断点线被画 2–4 遍的直接判据）──────────────────
     只看 stroke-dasharray 不为空的图元。为什么要这个限制：实线里存在**合法**的
     完全重合 —— range_band 在 lo === hi 的类别上会把上下界横杠画在同一个 y
     （exchanges12 Ex4 有 7 个这样的类别，一放开就是 7 条 100% 误报）。
     而虚线在这套引擎里只用于断点线（'4 3'）、12 个月均线、零线等标注类图元，
     这些东西重合画两遍一定是 bug。代价：**实线的重复绘制抓不到**，
     只能靠 DUPLICATE_TEXT（断点标签跟着重复）兜住同一类缺陷。 */
  var seen = {}, dups = {};
  var ln = svg.querySelectorAll('line,path');
  for (i = 0; i < ln.length; i++){
    var e2 = ln[i];
    if (e2.closest('defs')) continue;
    var dash = e2.getAttribute('stroke-dasharray') || '';
    if (!dash) continue;
    var key = e2.tagName + '|' + (e2.getAttribute('d') || '') + '|' +
      [ 'x1','y1','x2','y2' ].map(function(a){ return e2.getAttribute(a)||''; }).join(',') + '|' +
      (e2.getAttribute('stroke')||'') + '|' + (e2.getAttribute('stroke-width')||'') + '|' +
      dash + '|' + (e2.getAttribute('transform')||'');
    seen[key] = (seen[key] || 0) + 1;
    if (seen[key] > 1) dups[key] = seen[key];
  }
  for (var dk in dups)
    push(R, ctx, 'DUPLICATE_ELEMENT', dups[dk],
         { detail: dups[dk] + ' 条完全重合的同色虚线（断点线/均线被画了多遍）',
           key: dk.slice(0, 110), page_y: ctx.page_y, canvas: ctx.canvas });

  /* ── 4) 坐标轴合理性 ────────────────────────────────────────────────── */
  axisChecks(R, svg, ctx, ex, texts);
}

/* 轴刻度定位：charts.js 在左右轴刻度上打了 data-tick（'l' / 'r'）。
   原先是按「font-size == 9」筛的，而字号现在按卡片宽度在 FS_MIN..FS_MAX 之间变，
   没有一个固定的数可筛；更要命的是那种筛法一旦失配是**静默漏报**，不是报错。
   老引擎（没有 data-tick）走 font-size == '9' 的回退分支，保持可比。
   再按「同一个 x 属性上至少 3 个」聚类，并取最靠右的那一列 ——
   lines_endlabels 的左端标签（anchor='end'，x = M.l-10-tickW）在刻度列**左**边，
   末点读数（anchor='start'，x = Xc(last)+5）在右轴刻度列**左**边，都被排除。 */
function pickCol(arr){
  if (arr.length < 3) return null;
  var mx = -1e18, i;
  for (i = 0; i < arr.length; i++) if (arr[i].x > mx) mx = arr[i].x;
  var col = [];
  for (i = 0; i < arr.length; i++) if (Math.abs(arr[i].x - mx) < 0.75) col.push(arr[i]);
  return col.length >= 3 ? col : null;
}

function axisChecks(R, svg, ctx, ex, texts){
  var L = [], Rr = [], i;
  var tagged = svg.querySelector('text[data-tick]') !== null;
  for (i = 0; i < texts.length; i++){
    var t = texts[i];
    if (tagged ? !t.hasAttribute('data-tick') : t.getAttribute('font-size') !== '9') continue;
    if (t.getAttribute('transform')) continue;          // 轴刻度不带 transform
    var an = t.getAttribute('text-anchor');
    var x = parseFloat(t.getAttribute('x'));
    if (!isFinite(x)) continue;
    if (an === 'end') L.push({ x: x, t: t });
    else if (an === 'start') Rr.push({ x: x, t: t });
  }
  var cl = pickCol(L), cr = pickCol(Rr);
  oneAxis(R, ctx, ex, cl, 'left', !!cr);
  oneAxis(R, ctx, ex, cr, 'right', !!cr);
}

function oneAxis(R, ctx, ex, col, side, hasRight){
  if (!col) return;
  var i, items = [];
  for (i = 0; i < col.length; i++){
    var s = txtOf(col[i].t), v = parseTick(s);
    if (v === null) return;                       // 有一个解析不了就整根轴放弃（宁可漏报）
    var b = col[i].t.getBoundingClientRect();
    items.push({ s: s, v: v, y: (b.top + b.bottom) / 2 });
  }
  items.sort(function(a, b2){ return a.y - b2.y; });

  // (a) 相邻标签字面重复 —— 2.5 步长被格式化成整数的直接症状
  for (i = 1; i < items.length; i++)
    if (items[i].s === items[i-1].s){
      push(R, ctx, 'AXIS_DUP_LABEL', 1,
           { side: side, labels: items.map(function(o){ return o.s; }).join(' │ '),
             page_y: ctx.page_y, canvas: ctx.canvas });
      break;
    }

  // (b) 方向：屏幕 y 越大值必须越小（全负值柱图把上下界颠倒时这里报）
  var inv = 0;
  for (i = 1; i < items.length; i++) if (items[i].v > items[i-1].v + 1e-12) inv++;
  if (inv && inv === items.length - 1)
    push(R, ctx, 'AXIS_INVERTED', items.length,
         { side: side, labels: items.map(function(o){ return o.s; }).join(' │ '),
           page_y: ctx.page_y, canvas: ctx.canvas });
  else if (inv)
    push(R, ctx, 'AXIS_NOT_MONOTONIC', inv,
         { side: side, labels: items.map(function(o){ return o.s; }).join(' │ '),
           page_y: ctx.page_y, canvas: ctx.canvas });

  // (c) 像素-数值比恒定（dropClashingTicks 让位不误报）
  if (items.length >= 3){
    var ks = [], ok = true;
    for (i = 1; i < items.length; i++){
      var dy = items[i].y - items[i-1].y, dv = items[i-1].v - items[i].v;
      if (dy < CFG.axis_min_dy){ ok = false; break; }
      ks.push(dv / dy);
    }
    if (ok && ks.length >= 2){
      var srt = ks.slice().sort(function(a,b2){ return a-b2; });
      var med = srt[Math.floor(srt.length/2)];
      if (Math.abs(med) > 1e-12){
        var dev = 0;
        for (i = 0; i < ks.length; i++) dev = Math.max(dev, Math.abs(ks[i]-med)/Math.abs(med));
        if (dev > CFG.axis_k_tol)
          push(R, ctx, 'AXIS_UNEVEN', +(dev*100).toFixed(1),
               { side: side, labels: items.map(function(o){ return o.s; }).join(' │ '),
                 detail: '刻度像素-数值比偏离 ' + (dev*100).toFixed(1) + '%',
                 page_y: ctx.page_y, canvas: ctx.canvas });
      }
    }
  }

  // (d) 零基线：柱图（无显式截轴）且数据全非负时，最小刻度必须是 0
  if (side !== 'left' || !ex) return;
  /* 双轴图豁免：charts.js 的 alignZero() 会为了把左右两轴的零点拉到同一屏幕高度，
     主动把左轴下界压到 0 以下（y/y 有负值时必然发生）。实测 tmx 26 张里有 5 张
     命中，全部是这个原因、没有一张是真的隐性截轴 —— 判据留着就是 100% 误报。
     代价：**双轴柱图上真正的隐性截轴抓不到**，只能靠单轴柱图这一半覆盖。 */
  if (hasRight) return;
  var BAR = { gs_bar:1, bars_labeled:1, stacked_dual:1, qtr_bar:1 };
  if (!BAR[ex.kind]) return;
  if (ex.ycap != null || ex.yfloor != null) return;
  var vals = collectVals(ex);
  if (vals.length < 3) return;
  var mn = Math.min.apply(null, vals), mx = Math.max.apply(null, vals);
  var tmin = Math.min.apply(null, items.map(function(o){ return o.v; }));
  var tmax = Math.max.apply(null, items.map(function(o){ return o.v; }));
  var span = Math.max(1e-12, tmax - tmin);
  if (mn >= 0 && Math.abs(tmin) > span * 1e-6)
    push(R, ctx, 'ZERO_BASE_BROKEN', +Math.abs(tmin / span * 100).toFixed(1),
         { side: side, detail: '柱图数据全非负，但最小刻度是 ' + items[items.length-1].s +
             '（隐性截轴，柱长不再与数值成比例）',
           page_y: ctx.page_y, canvas: ctx.canvas });
  else if (mn < 0 && mx > 0 && !(tmin < 0 && tmax > 0))
    push(R, ctx, 'ZERO_BASE_BROKEN', 100,
         { side: side, detail: '柱图有正有负，但零线不在轴量程内（' +
             items[items.length-1].s + ' … ' + items[0].s + '）',
           page_y: ctx.page_y, canvas: ctx.canvas });
}

function collectVals(ex){
  var out = [];
  function add(a){ if (!a) return; for (var i=0;i<a.length;i++){
    var v = a[i]; if (v != null && isFinite(v)) out.push(+v); } }
  add(ex.values);
  if (ex.series) for (var i=0;i<ex.series.length;i++) add(ex.series[i].values);
  if (ex.stacks) for (var j=0;j<ex.stacks.length;j++) add(ex.stacks[j].values);
  if (ex.groups) for (var k=0;k<ex.groups.length;k++) add(ex.groups[k].values);
  if (ex.bar) add(ex.bar.values);
  return out;
}

/* 主题支持探测：CSS 里有没有 prefers-color-scheme 规则 / 根节点有没有 data-theme。
   这套页面 style.css 显式写了 color-scheme:light 且注释「刻意只做浅色」，
   所以正常结果是 supported=false，深色一轮会被跳过并在报告里写明。 */
function themeInfo(d){
  var info = { supported: false, how: null,
               root_attr: d.documentElement.getAttribute('data-theme'),
               color_scheme: '' };
  try {
    var cs = getComputedStyle(d.documentElement).colorScheme;
    info.color_scheme = cs || '';
  } catch(e){}
  if (info.root_attr) { info.supported = true; info.how = 'data-theme'; }
  try {
    var ss = d.styleSheets, i, j;
    for (i = 0; i < ss.length; i++){
      var rules = null;
      try { rules = ss[i].cssRules; } catch(e){ continue; }
      if (!rules) continue;
      for (j = 0; j < rules.length; j++){
        var r = rules[j];
        if (r.media && String(r.conditionText || r.media.mediaText).indexOf('prefers-color-scheme') >= 0){
          info.supported = true; info.how = 'prefers-color-scheme'; return info;
        }
      }
    }
  } catch(e){}
  return info;
}

/* ── 装载 + 等渲染稳定 ────────────────────────────────────────────────── */
var fr = document.createElement('iframe');
fr.setAttribute('scrolling', 'no');
fr.width = String(window.innerWidth);
fr.height = String(window.innerHeight);
fr.src = PATH;
document.body.appendChild(fr);

setTimeout(function(){ emit({ fatal: 'timeout: 页面未在 ' + CFG.hard_ms + 'ms 内渲染完' }); },
           CFG.hard_ms);

function measure(d){
  try { emit(analyze(d, fr.contentWindow)); }
  catch(e){ emit({ fatal: 'analyze: ' + e + ' @' +
                          (e && e.stack ? String(e.stack).slice(0,300) : '') }); }
}

fr.onload = function(){
  var d;
  try { d = fr.contentDocument; } catch(e){ emit({ fatal: 'cross-origin: ' + e }); return; }
  if (!d){ emit({ fatal: 'no contentDocument' }); return; }
  var last = -1, stable = 0, tries = 0;
  (function poll(){
    if (emitted) return;
    var n = d.querySelectorAll('.plot .host svg').length;
    stable = (n === last && n > 0) ? stable + 1 : 0;
    last = n;
    if (stable >= 3 || ++tries > 80){
      /* 字体就绪 + 两帧之后再量。rAF 在 headless 里可能一直不回调，
         所以同时挂一个 250ms 的兜底，谁先到算谁（emit 自带幂等）。 */
      var go = function(){
        setTimeout(function(){ measure(d); }, 250);
        requestAnimationFrame(function(){ requestAnimationFrame(function(){ measure(d); }); });
      };
      if (d.fonts && d.fonts.ready) d.fonts.ready.then(go, go); else go();
      return;
    }
    setTimeout(poll, 60);
  })();
};
})();
</script>
"""


# ── 临时 http server ────────────────────────────────────────────────────────
class _Handler(http.server.SimpleHTTPRequestHandler):
    """静态服务仓根；对 .html 在内存里注入错误捕获 shim；/__qa__/* 走内存。"""

    probe_html = ""
    results = {}
    lock = threading.Lock()

    def log_message(self, *a):        # 静音
        pass

    def do_POST(self):
        path, _, qs = self.path.partition("?")
        if path != "/__qa__/result":
            self.send_error(404)
            return
        rid = dict(kv.split("=", 1) for kv in qs.split("&") if "=" in kv).get("id", "")
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n).decode("utf-8", "replace")
        with _Handler.lock:
            _Handler.results[rid] = body
        self._send(b"ok", "text/plain")

    def _send(self, body, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/__qa__/probe.html":
            return self._send(self.probe_html.encode("utf-8"), "text/html; charset=utf-8")
        fs = self.translate_path(self.path)
        if os.path.isdir(fs):
            fs = os.path.join(fs, "index.html")
        if fs.endswith(".html") and os.path.isfile(fs):
            try:
                raw = open(fs, "rb").read().decode("utf-8", "replace")
            except OSError:
                return super().do_GET()
            low = raw.lower()
            i = low.find("<head>")
            inj = raw[: i + 6] + ERR_SHIM + raw[i + 6:] if i >= 0 else ERR_SHIM + raw
            return self._send(inj.encode("utf-8"), "text/html; charset=utf-8")
        return super().do_GET()

    do_HEAD = do_GET


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def start_server(repo):
    _Handler.probe_html = PROBE_HTML.replace(
        "__CFG__", json.dumps(dict(THRESH, hard_ms=60000)))
    handler = lambda *a, **k: _Handler(*a, directory=repo, **k)   # noqa: E731
    srv = _Server(("127.0.0.1", 0), handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


# ── Chrome 驱动 ────────────────────────────────────────────────────────────
CHROME_BASE = [
    "--headless", "--disable-gpu", "--hide-scrollbars",
    "--force-device-scale-factor=1", "--no-first-run",
    "--no-default-browser-check", "--disable-extensions",
    "--disable-background-networking", "--disable-component-update",
    "--disable-default-apps", "--disable-sync", "--no-service-autorun",
    "--metrics-recording-only", "--mute-audio", "--password-store=basic",
    "--use-mock-keychain", "--disable-features=Translate,BackForwardCache",
    # 不让 headless 把「不可见」的窗口当后台节流，否则 setTimeout/rAF 会被拖慢
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
]
# 本机 Chrome 会跟随 macOS 的系统深色设置（实测 headless 默认 prefers-color-scheme: dark），
# 所以「浅色」这一轮必须显式钉住，否则跑的其实是深色媒体查询。
SCHEME_FLAG = {"light": "--blink-settings=preferredColorScheme=1",
               "dark": "--blink-settings=preferredColorScheme=0"}


def _run_chrome(args, ready_fn, timeout, profile_root):
    """跑一次 Chrome，ready_fn() 返回真值时立刻杀掉整个进程组。

    为什么不能用 subprocess.run 等它自己退出：Chrome 会拉起 GoogleUpdater 子进程，
    它继承了 stdout 且长期不退出 —— 等 EOF 会永远挂住（实测 90s 仍未返回，
    而页面其实 2s 就已经跑完了）。所以一律「自己判完成 + killpg」。
    """
    prof = tempfile.mkdtemp(prefix="prof-", dir=profile_root)
    cmd = [CHROME] + CHROME_BASE + ["--user-data-dir=" + prof] + args
    devnull = subprocess.DEVNULL
    p = subprocess.Popen(cmd, stdout=devnull, stderr=devnull, start_new_session=True)
    t0, got = time.time(), None
    try:
        while time.time() - t0 < timeout:
            time.sleep(0.15)
            got = ready_fn()
            if got:
                break
    finally:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except Exception:
            pass
    shutil.rmtree(prof, ignore_errors=True)
    return got, time.time() - t0


_rid = [0]


def probe(port, url_path, width, scheme, profile_root, timeout=120):
    with _Handler.lock:
        _rid[0] += 1
        rid = "r%d-%d" % (_rid[0], int(time.time() * 1000) % 100000)

    def ready():
        with _Handler.lock:
            return _Handler.results.pop(rid, None)

    url = ("http://127.0.0.1:%d/__qa__/probe.html?id=%s&path=%s"
           % (port, rid, url_path.replace("&", "%26")))
    args = [SCHEME_FLAG[scheme], "--window-size=%d,%d" % (width, VIEWPORT_H), url]
    body, took = _run_chrome(args, ready, timeout, profile_root)
    if not body:
        return {"ok": False, "fatal": "chrome 未在 %ds 内回传结果" % timeout,
                "took": round(took, 1)}
    try:
        data = json.loads(body)
    except Exception as e:
        return {"ok": False, "fatal": "结果解析失败: %s" % e, "took": round(took, 1)}
    data["took"] = round(took, 1)
    return data


def screenshot(port, url_path, width, height, dest, profile_root, timeout=180):
    """整页截图。--screenshot 只截 window-size 那么大，所以窗口高度直接给内容高。"""
    def ready():
        return os.path.exists(dest) and os.path.getsize(dest) > 2048

    url = "http://127.0.0.1:%d%s" % (port, url_path)
    args = [SCHEME_FLAG["light"],
            "--window-size=%d,%d" % (width, min(int(height) + 160, 24000)),
            "--screenshot=" + dest, url]
    ok, _ = _run_chrome(args, ready, timeout, profile_root)
    for _ in range(8):                       # 刚建好文件就被杀时给一点落盘时间
        if os.path.exists(dest) and os.path.getsize(dest) > 2048:
            return True
        time.sleep(0.25)
    return bool(ok)


# ── 定级 ───────────────────────────────────────────────────────────────────
SEV_RED, SEV_AMBER, SEV_INFO = "red", "amber", "info"
SEV_ORDER = {SEV_RED: 0, SEV_AMBER: 1, SEV_INFO: 2}
SEV_ICON = {SEV_RED: "🔴", SEV_AMBER: "🟡", SEV_INFO: "🔵"}

TYPE_CN = {
    "SVG_OVERFLOW": "图元画到画布外",
    "TEXT_OUT_OF_CARD": "文字越出卡片",
    "TEXT_ON_PROSE": "图上文字压住卡片正文",
    "TEXT_OVERLAP": "文字互相压字",
    "DUPLICATE_TEXT": "同一段文字被画了两遍",
    "DUPLICATE_ELEMENT": "同一图元被重复绘制",
    "AXIS_DUP_LABEL": "轴刻度出现重复标签",
    "AXIS_INVERTED": "坐标轴方向画反",
    "AXIS_NOT_MONOTONIC": "轴刻度不单调",
    "AXIS_UNEVEN": "轴刻度不等距（值被四舍五入）",
    "ZERO_BASE_BROKEN": "柱图零基线被破坏",
    "NON_FINITE_ATTR": "图元属性含 NaN/Infinity",
    "CONSOLE_ERROR": "渲染期 JS 报错",
    "HSCROLL": "页面出现横向滚动条",
    "SVG_COUNT_MISMATCH": "exhibit 数与渲染出的图数对不上",
    "RUN_FAILED": "该轮未能取到测量结果",
}


def severity(d):
    t = d["type"]
    px = d.get("px", 0) or 0
    if t == "SVG_OVERFLOW":
        if px >= THRESH["overflow_red_px"] or d.get("frac", 0) >= THRESH["overflow_red_frac"]:
            return SEV_RED
        return SEV_AMBER
    if t == "TEXT_OUT_OF_CARD":
        return SEV_RED if px >= THRESH["textcard_red_px"] else SEV_AMBER
    if t in ("TEXT_OVERLAP", "TEXT_ON_PROSE"):
        if px >= THRESH["overlap_red"] or d.get("frac", 0) >= THRESH["overlap_red_frac"]:
            return SEV_RED
        return SEV_AMBER if px >= THRESH["overlap_amber"] else SEV_INFO
    if t in ("DUPLICATE_TEXT", "AXIS_DUP_LABEL", "AXIS_INVERTED",
             "NON_FINITE_ATTR", "CONSOLE_ERROR", "HSCROLL",
             "SVG_COUNT_MISMATCH", "RUN_FAILED"):
        return SEV_RED
    if t == "AXIS_UNEVEN":
        # px 是「像素-数值比」的最大偏离百分比。偏离 ≥10% 只可能是标签被四舍五入到
        # 了错误的数值（2.5 步长印成 3/2、0.25 步长印成 0.3/0.2，实测偏离 33%）——
        # 也就是轴上印的数字本身是错的，属于正确性缺陷，判 🔴。
        # 5–10% 留 🟡：理论上不该出现，出现了先看一眼再说。
        return SEV_RED if px >= 10.0 else SEV_AMBER
    if t in ("DUPLICATE_ELEMENT", "AXIS_NOT_MONOTONIC", "ZERO_BASE_BROKEN"):
        return SEV_AMBER
    return SEV_INFO


# ── 页面清单 ───────────────────────────────────────────────────────────────
def discover_pages(repo):
    """从 data/roster.js（唯一权威名册）取页面清单，再加首页。"""
    pages = [("(首页)", "/")]
    rf = os.path.join(repo, "data", "roster.js")
    if os.path.isfile(rf):
        txt = open(rf, encoding="utf-8").read()
        i = txt.find("window.ROSTER")
        j = txt.find("{", i)
        try:
            obj = json.loads(txt[j:].strip().rstrip(";").strip())
            for g in obj.get("groups", []):
                for it in g.get("items", []):
                    t = it["ticker"]
                    if os.path.isfile(os.path.join(repo, t, "index.html")):
                        pages.append((t, "/%s/" % t))
        except Exception as e:
            print("! roster.js 解析失败（%s），回退到目录扫描" % e, file=sys.stderr)
    if len(pages) == 1:
        for d in sorted(os.listdir(repo)):
            if os.path.isfile(os.path.join(repo, d, "index.html")):
                pages.append((d, "/%s/" % d))
    seen, uniq = set(), []
    for k, u in pages:
        if u not in seen:
            seen.add(u)
            uniq.append((k, u))
    return uniq


# ── 报告 ───────────────────────────────────────────────────────────────────
def esc(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def write_reports(out_dir, meta, runs, defects, shots):
    js = {
        "meta": meta,
        "summary": {
            "red": sum(1 for d in defects if d["severity"] == SEV_RED),
            "amber": sum(1 for d in defects if d["severity"] == SEV_AMBER),
            "info": sum(1 for d in defects if d["severity"] == SEV_INFO),
            "by_type": {},
        },
        "pages": {},
        "defects": defects,
        "screenshots": shots,
    }
    for d in defects:
        k = d["type"]
        js["summary"]["by_type"][k] = js["summary"]["by_type"].get(k, 0) + 1
    for r in runs:
        p = js["pages"].setdefault(r["page"], {"url": r["url"], "runs": []})
        p["runs"].append({k: v for k, v in r.items() if k not in ("page", "url")})
    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(js, f, ensure_ascii=False, indent=1)

    # ── markdown ──
    L = []
    A = L.append
    A("# 整站视觉 QA 报告")
    A("")
    A("生成于 %s · 工具 `tools/visual_qa.py` · 判据与阈值见 `docs/VISUAL_QA_RUNNER.md`" % meta["generated"])
    A("")
    A("| | |")
    A("|---|---|")
    A("| 页面 | %d |" % meta["pages"])
    A("| 视口 | %s |" % " / ".join("%dpx" % v for v in meta["viewports"]))
    A("| 主题 | %s |" % meta["themes_note"])
    A("| 渲染轮次 | %d（其中失败 %d）|" % (meta["runs"], meta["runs_failed"]))
    A("| 用时 | %.0f 秒 |" % meta["duration_s"])
    A("| Chrome | %s |" % meta["chrome"])
    A("")
    A("| 严重度 | 条数 |")
    A("|---|---:|")
    A("| 🔴 | %d |" % js["summary"]["red"])
    A("| 🟡 | %d |" % js["summary"]["amber"])
    A("| 🔵 | %d |" % js["summary"]["info"])
    A("")
    if js["summary"]["by_type"]:
        A("| 缺陷类型 | 条数 |")
        A("|---|---:|")
        for k, v in sorted(js["summary"]["by_type"].items(), key=lambda kv: -kv[1]):
            A("| %s `%s` | %d |" % (TYPE_CN.get(k, k), k, v))
        A("")

    def one_line(d):
        bits = []
        if d["type"] == "SVG_OVERFLOW":
            bits.append("越出画布**%s缘 %.1fpx**（画布 %sx%s，元素 %s）" % (
                {"top": "上", "bottom": "下", "left": "左", "right": "右"}[d["side"]],
                d["px"], d["canvas"]["w"], d["canvas"]["h"], d.get("el", "")))
        elif d["type"] == "TEXT_OUT_OF_CARD":
            bits.append("「%s」越出卡片 **%.1fpx**" % (d.get("text", ""), d["px"]))
        elif d["type"] == "TEXT_ON_PROSE":
            bits.append("「%s」压在 `%s` 上，重叠 **%.1fpx²**" % (
                d.get("text", ""), d.get("over", ""), d["px"]))
        elif d["type"] == "TEXT_OVERLAP":
            bits.append("「%s」×「%s」重叠 **%.1fpx²**（占小者 %.0f%%）" % (
                d.get("a", ""), d.get("b", ""), d["px"], 100 * d.get("frac", 0)))
        elif d["type"] == "DUPLICATE_TEXT":
            bits.append("「%s」在同一位置画了两遍（中心距 %.2fpx）" % (
                d.get("text", ""), d.get("center_dist", 0)))
        elif d["type"] == "DUPLICATE_ELEMENT":
            bits.append("%s" % d.get("detail", ""))
        elif d["type"].startswith("AXIS"):
            bits.append("%s轴：%s" % ({"left": "左", "right": "右"}.get(d.get("side"), ""),
                                      d.get("detail") or d.get("labels", "")))
            if d.get("detail") and d.get("labels"):
                bits.append("刻度 `%s`" % d["labels"])
        elif d["type"] == "ZERO_BASE_BROKEN":
            bits.append(d.get("detail", ""))
        elif d["type"] == "CONSOLE_ERROR":
            bits.append("`%s` %s" % (d.get("kind_", ""), d.get("detail", "")))
        elif d["type"] == "HSCROLL":
            bits.append(d.get("detail", ""))
        else:
            bits.append(d.get("detail", ""))
        return " · ".join(b for b in bits if b)

    for sev in (SEV_RED, SEV_AMBER, SEV_INFO):
        sel = [d for d in defects if d["severity"] == sev]
        if not sel:
            continue
        A("---")
        A("")
        A("## %s %s 级（%d 条）" % (SEV_ICON[sev], {"red": "阻断", "amber": "待观察",
                                                   "info": "提示"}[sev], len(sel)))
        A("")
        A("| 页 | 视口 | 图号 | 图标题 | 缺陷 | 实测 | 页内 y |")
        A("|---|---:|---|---|---|---|---:|")
        for d in sel:
            A("| `%s` | %d | %s | %s | %s | %s | %s |" % (
                d["page"], d["viewport"],
                ("Ex%s" % d["ex"]) if d.get("ex") else "—",
                esc((d.get("title") or "")[:44]),
                TYPE_CN.get(d["type"], d["type"]),
                esc(one_line(d)),
                d.get("page_y", "—")))
        A("")

    A("---")
    A("")
    A("## 逐页快照")
    A("")
    A("| 页 | 视口 | exhibit 数 | 渲染出的 svg 数 | 内容高 | 🔴 | 🟡 | JS 报错 | 横向滚动 |")
    A("|---|---:|---:|---:|---:|---:|---:|---:|---|")
    for r in runs:
        red = sum(1 for d in defects if d["page"] == r["page"]
                  and d["viewport"] == r["viewport"] and d["severity"] == SEV_RED)
        amb = sum(1 for d in defects if d["page"] == r["page"]
                  and d["viewport"] == r["viewport"] and d["severity"] == SEV_AMBER)
        A("| `%s` | %d | %s | %s | %s | %d | %d | %d | %s |" % (
            r["page"], r["viewport"],
            r.get("payload_exhibits", "—"), r.get("svg_count", "—"),
            r.get("content_height", "—"), red, amb,
            len(r.get("console_errors", []) or []),
            ("是（超 %.0fpx）" % r["hscroll"]["over"]) if r.get("hscroll") else "否"))
    A("")
    if shots:
        A("## 失败截图")
        A("")
        for k, v in sorted(shots.items()):
            A("- `%s` → `%s`" % (k, v))
        A("")
    A("> 已知误报与能力边界见 `docs/VISUAL_QA_RUNNER.md`。")
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


# ── main ───────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="整站视觉 QA 跑批")
    ap.add_argument("--all", action="store_true", help="跑全站")
    ap.add_argument("--page", action="append", default=[],
                    help="只跑指定页（ticker，可重复；'index' = 首页）")
    ap.add_argument("--out", default=DEFAULT_OUT, help="输出目录（默认 %s）" % DEFAULT_OUT)
    ap.add_argument("--viewports", default=",".join(str(v) for v in VIEWPORTS),
                    help="视口宽度，逗号分隔")
    ap.add_argument("--jobs", type=int, default=4, help="并发 Chrome 数（默认 4）")
    ap.add_argument("--no-shots", action="store_true", help="不出截图")
    ap.add_argument("--timeout", type=int, default=120, help="单轮 Chrome 超时秒数")
    args = ap.parse_args()

    if not os.path.exists(CHROME):
        print("找不到 Chrome：%s" % CHROME, file=sys.stderr)
        return 3

    pages = discover_pages(REPO)
    if args.page:
        want = {p.strip().lower() for p in args.page}
        sel = [(k, u) for k, u in pages
               if k.lower() in want or (u == "/" and "index" in want)]
        if not sel:
            print("没有匹配的页：%s\n可选：%s"
                  % (", ".join(sorted(want)), ", ".join(k for k, _ in pages)), file=sys.stderr)
            return 3
        pages = sel
    elif not args.all:
        print("要么 --all，要么 --page <ticker>", file=sys.stderr)
        return 3

    vps = [int(v) for v in args.viewports.split(",") if v.strip()]
    out_dir = args.out
    shots_dir = os.path.join(out_dir, "shots")
    # 可重复跑、不留垃圾：每次把输出目录整个重建
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(shots_dir, exist_ok=True)
    profile_root = tempfile.mkdtemp(prefix="visual_qa-")

    srv, port = start_server(REPO)
    t0 = time.time()
    print("· http://127.0.0.1:%d  ← %s" % (port, REPO))
    print("· %d 页 × %d 视口" % (len(pages), len(vps)))
    try:
        return _run(args, pages, vps, out_dir, shots_dir, profile_root, srv, port, t0)
    finally:
        # 任何路径（含异常/Ctrl-C）都要收摊：关服务器、删临时 profile，不留后台进程
        try:
            srv.shutdown()
            srv.server_close()
        except Exception:
            pass
        shutil.rmtree(profile_root, ignore_errors=True)


def _run(args, pages, vps, out_dir, shots_dir, profile_root, srv, port, t0):

    runs, defects = [], []
    theme_support = {"any": False, "how": None}

    def one(page, url, vp, scheme):
        r = probe(port, url, vp, scheme, profile_root, timeout=args.timeout)
        r["page"], r["url"], r["viewport"], r["theme"] = page, url, vp, scheme
        return r

    jobs = [(k, u, vp) for k, u in pages for vp in vps]
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futs = [pool.submit(one, k, u, vp, "light") for k, u, vp in jobs]
        for f in futs:
            r = f.result()
            runs.append(r)
            st = "ok" if not r.get("fatal") else "FAIL"
            print("  %-16s %4dpx  %-4s  %s" % (r["page"], r["viewport"], st,
                                               r.get("fatal", "")[:70]))

    # 深色一轮：只在页面**真的**声明了深色支持时才跑。
    # 这套站的 style.css 顶上写着「刻意只做浅色」并钉死 color-scheme: light，
    # 所以正常情况下这里探测为 false、深色轮跳过，并把原因写进报告 —— 而不是
    # 用 Chrome 的 --force-dark-mode 造一份假的深色渲染出来充数。
    supported = sorted({r["page"] for r in runs
                        if (r.get("theme_detect") or {}).get("supported")})
    if supported:
        how = next((r["theme_detect"]["how"] for r in runs
                    if (r.get("theme_detect") or {}).get("supported")), "?")
        theme_support = {"any": True, "how": how, "pages": supported}
        print("· 探测到 %d 页声明了深色支持（%s），补跑深色轮" % (len(supported), how))
        sset = set(supported)
        dark_jobs = [(k, u, vp) for k, u in pages for vp in vps if k in sset]
        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
            futs = [pool.submit(one, k, u, vp, "dark") for k, u, vp in dark_jobs]
            for f in futs:
                r = f.result()
                runs.append(r)
                print("  %-16s %4dpx  dark  %s" % (r["page"], r["viewport"],
                                                   "ok" if not r.get("fatal") else "FAIL"))

    # ── 汇总缺陷 ──
    runs_failed = 0
    for r in runs:
        base = {"page": r["page"], "viewport": r["viewport"], "theme": r["theme"]}
        if r.get("fatal"):
            runs_failed += 1
            defects.append(dict(base, type="RUN_FAILED", px=0, ex=None, title="",
                                detail=r["fatal"], severity=SEV_RED))
            continue
        for d in r.get("defects", []):
            d2 = dict(base, **d)
            d2["severity"] = severity(d2)
            defects.append(d2)
        for ce in (r.get("console_errors") or []):
            if ce.get("k") == "console.warn":
                continue          # warn 不当缺陷，只留在 json 里
            defects.append(dict(base, type="CONSOLE_ERROR", px=0, ex=None, title="",
                                kind_=ce.get("k", ""),
                                detail="%s %s" % (ce.get("m", ""),
                                                  ("(%s:%s)" % (ce.get("src", ""), ce.get("ln", 0)))
                                                  if ce.get("src") else ""),
                                severity=SEV_RED))
        if r.get("hscroll"):
            h = r["hscroll"]
            defects.append(dict(
                base, type="HSCROLL", px=h["over"], ex=None, title="",
                detail="body 可横向滚动 %.0fpx（scrollWidth %.0f > clientWidth %.0f）；最宽越界元素：%s"
                       % (h["over"], h["scrollWidth"], h["clientWidth"],
                          "; ".join("%s +%.0fpx" % (c["el"][:50], c["over"])
                                    for c in h["culprits"][:3])),
                severity=SEV_RED))
        pe, sc = r.get("payload_exhibits"), r.get("svg_count")
        if pe is not None and sc is not None and pe != sc:
            defects.append(dict(base, type="SVG_COUNT_MISMATCH", px=abs(pe - sc), ex=None,
                                title="",
                                detail="payload 里 %d 个 exhibit，DOM 里只渲染出 %d 张图" % (pe, sc),
                                severity=SEV_RED))

    defects.sort(key=lambda d: (SEV_ORDER[d["severity"]], -float(d.get("px") or 0),
                                d["page"], d["viewport"]))

    # ── 🔴 页截图 ──
    shots = {}
    if not args.no_shots:
        redpages = {}
        for d in defects:
            if d["severity"] != SEV_RED:
                continue
            # 同一页在多个视口都有 🔴 时截主视口（清单里的第一个，默认桌面 1280）——
            # 窄屏图窄、字挤，拿去人工复核不如桌面版直观。
            cur = redpages.get(d["page"])
            if cur is None or (cur != vps[0] and d["viewport"] == vps[0]):
                redpages[d["page"]] = d["viewport"]
        for pg, vp in sorted(redpages.items()):
            url = next((u for k, u in pages if k == pg), None)
            if not url:
                continue
            h = max((r.get("content_height") or 0) for r in runs
                    if r["page"] == pg and r["viewport"] == vp) or 4000
            dest = os.path.join(shots_dir, "%s@%d.png" % (pg.strip("()"), vp))
            print("  截图 %s (%dx%d) …" % (pg, vp, h))
            if screenshot(port, url, vp, h, dest, profile_root):
                shots[pg] = dest

    meta = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "repo": REPO, "pages": len(pages), "viewports": vps,
        "runs": len(runs), "runs_failed": runs_failed,
        "duration_s": round(time.time() - t0, 1),
        "chrome": subprocess.run([CHROME, "--version"], capture_output=True,
                                 text=True).stdout.strip() or "?",
        "thresholds": THRESH,
        "themes_note": ("浅色 + 深色各一轮" if theme_support["any"] else
                        "仅浅色 —— 探测到页面未声明任何 prefers-color-scheme 规则或 "
                        "data-theme 切换（style.css 显式写死 color-scheme: light），"
                        "深色一轮跳过"),
        "geom_selfcheck_fail": sum(r.get("geom_selfcheck_fail", 0) or 0 for r in runs),
    }
    write_reports(out_dir, meta, runs, defects, shots)

    nred = sum(1 for d in defects if d["severity"] == SEV_RED)
    namb = sum(1 for d in defects if d["severity"] == SEV_AMBER)
    print("\n%s\n🔴 %d  🟡 %d  🔵 %d   用时 %.0fs"
          % ("-" * 60, nred, namb,
             sum(1 for d in defects if d["severity"] == SEV_INFO), meta["duration_s"]))
    print("· %s/report.md\n· %s/report.json" % (out_dir, out_dir))
    if meta["geom_selfcheck_fail"]:
        print("! 几何自检失败 %d 处 —— 压字结论存疑" % meta["geom_selfcheck_fail"])
    return 1 if nred else 0


if __name__ == "__main__":
    sys.exit(main())
