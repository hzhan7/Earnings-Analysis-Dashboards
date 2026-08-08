# Earnings Analysis Dashboards

Static GitHub Pages dashboards for presenting quarterly earnings as concise,
chart-led research pages. Reviewed pages currently cover Alphabet and TSMC.

## Build

```bash
python3 build/all.py
python3 -m http.server 8765
```

Open `http://127.0.0.1:8765/`, then choose:

- `http://127.0.0.1:8765/googl/`
- `http://127.0.0.1:8765/tsm/`

Live site: https://hzhan7.github.io/Earnings-Analysis-Dashboards/

## Content boundary

- Inputs: the local Earnings Analysis note plus company-reported quarterly data.
- Published numbers: company-reported figures and transparent arithmetic
  derivations only. Short commentary is research interpretation, not company
  guidance or a rating.
- Market expectations may be published as a labelled, dated comparison point
  (`市场预期`), with no broker or vendor named.
- Excluded: ratings, target prices, valuation, broker-attributed estimates,
  unverified customer-concentration estimates, local absolute paths, source
  PDFs, PPTs and transcripts.
- `D` means Derived / 自算; it does not mean a company-defined non-GAAP metric.

## Page modules

The page stands in for the slide deck that used to accompany the local earnings
note, so it is meant to be **scanned, not read**: charts carry the argument and
each one gets a sentence or two underneath. Prose tables are reference material
and live in the collapsed audit drawer.

Charts are ordered the way the note is actually used:

1. **上季兑现** — settle the thresholds set last quarter before looking at any
   new number. Without this the page only ever accumulates opinions.
2. **本季重点** — what actually moved: the beats, the misses, the one thing
   management would not disclose.
3. **下季跟踪** — the same thresholds pointed forward.
4. **长期常规** — the routine multi-quarter series, chosen per company rather
   than from a template. Alphabet gets revenue/capital intensity/depreciation/
   geography; TSMC gets node migration, platform mix and working capital.

Sections 1 and 3 are built the same way, twice over:

- One diverging bar of **distance from the threshold**, signed so positive
  always means safe. It puts percent, US$M, days and FX rates on a single axis,
  which is the only way a mixed-unit KPI list stops being a table.
- Then **one chart per tracked metric**, showing that metric's own history under
  a flat threshold line. The overview bar says which line broke; only the
  per-metric chart says how it got there. A metric is left out only when it has
  no series to plot (a single reportable point, or an unpublished spot rate),
  and the overview names what was left out and why.

`build/board.py` owns the normalisation, the threshold charts, exhibit numbering
and the audit tables that restore the original units. Exhibit numbers are
assigned in render order, so inserting a chart never leaves a caption pointing
at the wrong exhibit.

Around the charts: a headline stating the quarter's core tension, three short
takeaways, a shared `AI capex 循环` cross-reference published identically on both
pages, the official-source drawer, and a `口径与方法说明` block that lists what
each page knowingly does not carry.

Each company has a reviewed source series and a company-specific builder. The
shared `build/all.py` entry point rebuilds both company payloads, their thin
HTML shells and the cross-company roster without exposing local source files.

Thresholds on the page are local research settings, not company guidance and not
a rating. Market expectations may be published, but only unattributed and dated
— never with a broker name attached.
