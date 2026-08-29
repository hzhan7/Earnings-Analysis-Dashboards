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
   * Only stroked paths and polylines are checked, and only against the
   * vertical extent: bar labels and end labels are deliberately allowed to sit
   * in the margin, and the horizontal axis is padded by the renderer. */
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
