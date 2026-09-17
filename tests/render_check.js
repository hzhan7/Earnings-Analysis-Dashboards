/* Render every published page under jsdom and fail on a broken SVG.
 *
 * Why this exists as a separate gate. The Python suite reads *payloads*: 475
 * tests, `build/payload_guard.py`, and `build/all.py && git status` all agree a
 * tree is clean without any of them ever looking at a rendered chart. So a
 * value that is finite in `data/<slug>.js` and only becomes NaN inside the
 * renderer's own arithmetic is invisible to every one of them.
 *
 * That is not hypothetical. `assets/charts.js` drew the gs_bar reference line
 * from `ex.avg12`, a number the payload supplies and the engine never computes,
 * whenever `ex.yoy` was absent. Across the whole site 27 exhibits are gs_bar,
 * 26 carry `yoy` and **none has ever carried `avg12`** — so the branch had
 * never once been exercised with real data. AVGO Exhibit 16 was the first
 * exhibit to reach it, and it emitted
 *
 *     <line x1="81.2" x2="499.7" y1="NaN" y2="NaN" stroke="#1F3864" …>
 *
 * The browser silently drops an element with a NaN geometry attribute: no
 * console error, no blank card, no layout shift. The chart looked finished.
 * The only visible trace was the legend still promising a "Prior 12mo Avg."
 * dashed line that no longer existed anywhere on the canvas.
 *
 * Run:  node tests/render_check.js [repo-root]
 * Exit: 0 when every page renders clean, 1 otherwise.
 *
 * jsdom is the one third-party dependency in this repo and it is deliberately
 * not vendored: `tests/test_rendered_svg.py` runs this file when jsdom resolves
 * and skips, loudly, when it does not. Install it with
 * `npm --prefix tests install`.
 */

"use strict";

const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.resolve(process.argv[2] || path.join(__dirname, ".."));

/* Token boundary, not `includes`. Every page's source links carry SEC and IR
 * URLs, and `.../Financial-Information/...` contains "nan" — matched as a
 * substring, this scan is red on all 17 pages and gets deleted. Anchoring on
 * non-letters also keeps Chinese labels (the majority of the text on these
 * pages) from being split mid-token. */
const BAD = /(^|[^A-Za-z])(NaN|Infinity|undefined)([^A-Za-z]|$)/;

function slugs() {
  return fs
    .readdirSync(ROOT)
    .filter(
      (name) =>
        fs.existsSync(path.join(ROOT, name, "index.html")) &&
        fs.existsSync(path.join(ROOT, "data", `${name}.js`))
    )
    .sort();
}

/* The card an offending node sits in, so a failure names an exhibit rather
 * than an anonymous <line>. */
function locate(node) {
  const card = node.closest("section.card") || node.closest(".grid > *");
  const head = card && card.querySelector("h3, h4, .card-title");
  return head ? head.textContent.trim().slice(0, 72) : "(chart with no title)";
}

/* Every y a path's outline reaches, or null when `d` cannot be read.
 *
 * The stroked-path check below gets away with pairing numbers, because the
 * engine writes those as absolute `M x y L x y`. A bar is not written that way:
 * `barPath()` in `assets/charts.js` emits `M x y V y a r r 0 0 1 r -r h w a ...`,
 * where a pair of numbers is as likely to be an arc radius or a relative step
 * as a point. So this walks the commands and tracks the pen. Arcs are measured
 * at their endpoints: the only arcs the engine draws are a bar's quarter-circle
 * corners, which lie between their endpoints. */
const PATH_ARGS = { M: 2, L: 2, T: 2, H: 1, V: 1, S: 4, Q: 4, C: 6, A: 7, Z: 0 };
function pathYs(d) {
  const tokens = d.match(/[A-Za-z]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?/g) || [];
  const ys = [];
  let cmd = null, x = 0, y = 0, startX = 0, startY = 0, i = 0;
  while (i < tokens.length) {
    const letter = /^[A-Za-z]$/.test(tokens[i]);
    if (letter) cmd = tokens[i++];
    if (!cmd || !(cmd.toUpperCase() in PATH_ARGS)) return null;
    const upper = cmd.toUpperCase(), rel = cmd !== upper;
    if (upper === "Z") {
      if (!letter) return null;                 // a number after Z has no command
      x = startX; y = startY;
      continue;
    }
    const args = tokens.slice(i, i + PATH_ARGS[upper]).map(Number);
    i += PATH_ARGS[upper];
    if (args.length < PATH_ARGS[upper] || !args.every(isFinite)) return null;
    const oy = rel ? y : 0, ox = rel ? x : 0;
    if (upper === "H") { x = ox + args[0]; }
    else if (upper === "V") { y = oy + args[0]; }
    else {
      for (let k = 1; k < args.length - 2; k += 2) if (upper !== "A") ys.push(oy + args[k]);
      x = ox + args[args.length - 2];
      y = oy + args[args.length - 1];
    }
    ys.push(y);
    if (upper === "M") { startX = x; startY = y; cmd = rel ? "l" : "L"; }
  }
  return ys;
}

function render(slug) {
  const errors = [];
  const dom = new JSDOM(
    fs.readFileSync(path.join(ROOT, slug, "index.html"), "utf8"),
    { runScripts: "outside-only", pretendToBeVisual: true, url: "https://x/" }
  );
  /* The renderer reports nothing today, but a future guard that reports
   * instead of throwing has to land somewhere this gate can see. */
  dom.window.console.error = (...args) =>
    errors.push(`console.error: ${args.join(" ")}`);

  try {
    for (const rel of [
      "data/roster.js",
      `data/${slug}.js`,
      "assets/charts.js",
      "assets/page.js",
    ]) {
      dom.window.eval(fs.readFileSync(path.join(ROOT, rel), "utf8"));
    }
    dom.window.document.dispatchEvent(
      new dom.window.Event("DOMContentLoaded", { bubbles: true })
    );
  } catch (err) {
    errors.push(`threw: ${err.message}`);
  }

  const doc = dom.window.document;
  const svgs = doc.querySelectorAll(".grid svg");

  /* A chart that threw leaves its host empty. `无数据` is a legitimate render
   * (the engine prints it when a series has no finite point), so it is counted
   * and reported rather than failed on. */
  const empty = [...doc.querySelectorAll(".grid > *")].filter(
    (node) => !node.querySelector("svg")
  );
  for (const node of empty) errors.push(`grid child with no <svg>: ${locate(node)}`);

  for (const node of doc.querySelectorAll(".grid svg, .grid svg *")) {
    for (const name of node.getAttributeNames()) {
      const value = node.getAttribute(name);
      if (BAD.test(value)) {
        errors.push(
          `<${node.tagName} ${name}="${value}"> in ${locate(node)}`
        );
        break;
      }
    }
  }

  /* Attributes are not the whole surface: a label formatted from a missing
   * number prints the characters `NaN` into the chart as text, which no
   * attribute scan sees. `fv(avg)` in the gs_line_avg branch does exactly
   * that when `avg12` is absent. */
  for (const node of doc.querySelectorAll(".grid svg text, .grid svg title")) {
    if (BAD.test(node.textContent)) {
      errors.push(`<${node.tagName}> reads "${node.textContent}" in ${locate(node)}`);
    }
  }

  /* A finite coordinate can still be off the canvas, and that is invisible to
   * every check above: the element carries no NaN, the payload is finite, the
   * card is not empty, and the browser simply clips whatever falls outside the
   * viewBox without a word. `stacked_dual` reaches this the moment its
   * right-hand series passes 60: `charts.js` scales that axis to
   * `ticks(0, rc.ymax || 60, 6)` rather than to the data, so a share line at
   * 80% is drawn at a negative y and disappears, while the legend goes on
   * advertising it -- the same ending as AVGO Exhibit 16, one arithmetic step
   * further along. Found on CME Exhibit 4 while that page was being built, and
   * on IBKR Exhibit 8, which had been shipping that way.
   *
   * Only stroked paths and polylines are checked here, and only against the
   * vertical extent: bar labels and end labels are deliberately allowed to sit
   * in the margin, and the horizontal axis is padded by the renderer. Painted
   * shapes -- the bars themselves -- have their own check below. */
  for (const svg of doc.querySelectorAll(".grid svg")) {
    const box = (svg.getAttribute("viewBox") || "").split(/\s+/).map(Number);
    const height = box.length === 4 ? box[3] : null;
    if (!height || !isFinite(height)) continue;
    for (const node of svg.querySelectorAll("path, polyline")) {
      if (node.getAttribute("fill") !== "none") continue;
      const geometry = node.getAttribute("d") || node.getAttribute("points") || "";
      const ys = [...geometry.matchAll(/(-?[\d.]+)[ ,](-?[\d.]+)/g)].map((m) => Number(m[2]));
      const finite = ys.filter((y) => isFinite(y));
      if (!finite.length) continue;
      const low = Math.min(...finite);
      const high = Math.max(...finite);
      if (low < -1 || high > height + 1) {
        errors.push(
          `<${node.tagName}> is drawn at y ${low.toFixed(0)}..${high.toFixed(0)} ` +
            `outside a canvas ${height.toFixed(0)} tall in ${locate(node)}`
        );
      }
    }
  }

  /* The bars themselves, which the check above never looked at.
   *
   * A bar is a painted shape, not a stroke: `barPath()` fills a <path>, and the
   * stacked, bridge and range kinds fill <rect>s. The stroked-only rule above
   * was written so stacked blocks sitting flush on the plot edge would not trip
   * it, and so it passed every bar on the site unread. That left this open:
   * `grouped_bars` set its axis to `min(0, min*1.15) .. max*1.22`, so when every
   * value was negative the top of the axis was still below zero, and each bar
   * -- drawn from zero -- started above the plot and ran up over the card.
   * Found while building the Kering page (Exhibit 2), worked around there by
   * plotting magnitudes before the renderer was fixed.
   *
   * The bound is the plot band, not the viewBox. The renderer declares it as
   * `data-plot="<top> <bottom>"` (an explicit contract, like `data-xtick`). The
   * viewBox is too loose to see this defect reliably: how far the bars overrun
   * shrinks with the smallest bar's share of the largest, and with v Exhibit 5
   * made all-negative they reached y = -69, but with snps Exhibit 25 made
   * -50..-1,211 they overran the plot by 12px and stayed inside the top margin
   * -- wrong on the screen, clean against the viewBox. An svg that paints shapes
   * and declares no band is reported, not waved through.
   *
   * What is exempt, and why none of it is the hole this closes. Text is never
   * read: bar labels and end labels are deliberately set in the margin. Only
   * the vertical extent is read, as above. A bar flush with the band -- every
   * baseline, every stacked block -- passes on a 1px tolerance. A marker is
   * judged by its centre, because that is the data point: the range_band and
   * bridge diamonds are drawn at their value with a radius of up to 4.2px, and
   * one at the bottom of the band reaches 1.95px past it (nvda Exhibit 10)
   * without being wrong. "Marker" is read from size, at most MARKER px tall,
   * so a bar that short is also judged by its centre and can overrun by half its
   * height unreported. Shapes in <defs> (arrow marker, hatch patterns) live in
   * their own coordinates; `fill="none"` is the check above; `transparent` is
   * the tooltip hit area; a zero-height shape paints nothing. A painted shape
   * under a transform is *reported*, not skipped: nothing the engine fills
   * carries one today, and one that did would make every number here wrong
   * without saying so. */
  const MARKER = 9;
  for (const svg of doc.querySelectorAll(".grid svg")) {
    const shapes = [...svg.querySelectorAll("path, rect, polygon")].filter((node) => {
      const fill = (node.getAttribute("fill") || "").trim().toLowerCase();
      return fill !== "none" && fill !== "transparent" && !node.closest("defs");
    });
    if (!shapes.length) continue;
    const band = (svg.getAttribute("data-plot") || "").trim().split(/\s+/).map(Number);
    if (band.length !== 2 || !band.every(isFinite) || !(band[1] > band[0])) {
      errors.push(`svg paints ${shapes.length} shapes but declares no data-plot band in ${locate(svg)}`);
      continue;
    }
    const [top, bottom] = band;
    let count = 0, low = Infinity, high = -Infinity, tag = "";
    for (const node of shapes) {
      const moved = node.closest("[transform]");
      if (moved && svg.contains(moved)) {
        errors.push(`painted <${node.tagName}> under a transform cannot be bounds-checked in ${locate(node)}`);
        continue;
      }
      const name = node.tagName.toLowerCase();
      let ys;
      if (name === "rect") {
        const y = Number(node.getAttribute("y") || 0);
        ys = [y, y + Number(node.getAttribute("height") || 0)];
      } else if (name === "polygon") {
        ys = (node.getAttribute("points") || "").trim().split(/[\s,]+/).map(Number)
          .filter((_, k) => k % 2 === 1);
      } else {
        ys = pathYs(node.getAttribute("d") || "");
      }
      const finite = (ys || []).filter((y) => isFinite(y));
      if (!finite.length) continue;              // non-finite geometry is the NaN scan's to report
      const lo = Math.min(...finite), hi = Math.max(...finite);
      if (hi - lo < 1e-6) continue;
      const [a, b] = hi - lo <= MARKER ? [(lo + hi) / 2, (lo + hi) / 2] : [lo, hi];
      if (a < top - 1 || b > bottom + 1) {
        count++;
        low = Math.min(low, lo);
        high = Math.max(high, hi);
        tag = tag || name;
      }
    }
    if (count) {
      errors.push(
        `${count} painted <${tag}> shape${count > 1 ? "s" : ""} reach y ` +
          `${low.toFixed(0)}..${high.toFixed(0)} outside the plot band ` +
          `${top.toFixed(0)}..${bottom.toFixed(0)} in ${locate(svg)}`
      );
    }
  }

  /* Every chart labels its own last point.
   *
   * Derived from what an x axis promises, not from how this one broke: if a
   * chart plots N points and thins its ticks, the newest point is the one the
   * card's title, its end label and the page's headline are all talking about,
   * so it is the one tick that cannot be dropped. Stepping from index 0 drops
   * it whenever (N-1) % xstep !== 0, which was true for 196 of the 198 charts
   * that set an xstep -- and pulling a window from eight quarters to forty-two
   * is precisely the edit that gives a chart an xstep, so the count grew with
   * the migration instead of being fixed by it.
   *
   * Read from `data-xtick`, which the renderer puts only on x-axis ticks. The
   * last label's text usually also appears as an end label or a bar label, so
   * scanning every <text> would be satisfied by those and could never fail.
   * That makes an empty tick set the failure this check must also catch: if
   * the attribute is ever dropped, `drawn.length === 0` is reported rather
   * than passing silently on a chart that labels nothing. */
  const payload = dom.window.DASH;
  if (payload && Array.isArray(payload.sections)) {
    const charts = [...doc.querySelectorAll(".grid > *")];
    const exhibits = payload.sections.flatMap((section) => section.exhibits || []);
    exhibits.forEach((exhibit, index) => {
      const labels = exhibit.xlabels || [];
      const host = charts[index];
      if (!labels.length || !host || !host.querySelector("svg")) return;
      const drawn = [...host.querySelectorAll("svg text[data-xtick]")].map((n) =>
        n.textContent
      );
      const last = String(labels[labels.length - 1]);
      if (!drawn.length) {
        errors.push(`no x-axis tick labels at all in ${locate(host)}`);
      } else if (!drawn.includes(last)) {
        errors.push(
          `last x label ${JSON.stringify(last)} is never drawn ` +
            `(${labels.length} points, ticks end at ${JSON.stringify(drawn[drawn.length - 1])}) ` +
            `in ${locate(host)}`
        );
      }
    });
  }

  const nodata = [...doc.querySelectorAll("p.note")].filter((n) =>
    /无数据/.test(n.textContent)
  ).length;
  return { errors, svgs: svgs.length, nodata };
}

let failed = 0;
const names = slugs();
if (!names.length) {
  console.error(`no pages found under ${ROOT}`);
  process.exit(1);
}
for (const slug of names) {
  const { errors, svgs, nodata } = render(slug);
  const ok = errors.length === 0;
  if (!ok) failed++;
  console.log(
    `${ok ? "OK  " : "FAIL"} ${slug.padEnd(6)} svg=${String(svgs).padStart(2)} 无数据=${nodata}` +
      (ok ? "" : `\n       ${errors.join("\n       ")}`)
  );
}
console.log(`\n${names.length} pages rendered under jsdom, ${failed} with problems`);
process.exit(failed ? 1 : 0);
