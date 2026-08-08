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
- Excluded: ratings, target prices, valuation, sell-side consensus, unverified
  customer-concentration estimates, local absolute paths, source PDFs, PPTs and
  transcripts.
- `D` means Derived / 自算; it does not mean a company-defined non-GAAP metric.

## Page modules

Every company page is built in two layers, because the page answers two
different questions and they need different shapes.

**Layer 2 — tracking board (Exhibit 1).** The handful of metrics that carry an
explicit threshold and a trigger action, plus a status chip. It answers "what
changed in the things I actually track". Rows are expected to be re-cut as the
thesis moves: a threshold that has been priced in, or has stopped
discriminating, should be retired rather than rolled forward. Thresholds are
local research settings, not company guidance and not a rating.

**Layer 1 — quarterly operating panel (after the charts).** Fixed fields, same
rows every quarter, grouped and collapsible: eight-quarter trends first, then
the current quarter against the prior quarter and the year-ago quarter. It
answers "what did the last few quarters look like". Panel fields deliberately do
not follow the quarter's theme — a field that appears and disappears destroys
its own history.

Around those two layers:

- One conclusion-led headline stating the quarter's core tension, plus three
  short takeaways.
- Numbered exhibits with chart/table toggle, ordered growth → quality → capital
  and cash → forward-looking.
- A guidance / capital-cadence table where the company gives one.
- A shared `AI capex 循环` cross-reference table published identically on both
  pages, plus the official-source drawer.
- Desktop and mobile layouts using the same static payload.

Each company has a reviewed source series and a company-specific builder;
`build/board.py` holds the shared board and panel primitives. The shared
`build/all.py` entry point rebuilds both company payloads, their thin HTML
shells and the cross-company roster without exposing local source files.

Fields a series is knowingly missing are listed in that page's own
`口径与方法说明` block, so the gap is visible to a reader instead of only to the
builder.
