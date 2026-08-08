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

- One conclusion-led headline and three short takeaways.
- One quarterly scorecard.
- Eight numbered exhibits with chart/table toggle.
- Collapsed audit tables and official-source drawer.
- Desktop and mobile layouts using the same static payload.

Each company has a reviewed source series and a company-specific builder. The
shared `build/all.py` entry point rebuilds both company payloads, their thin
HTML shells and the cross-company roster without exposing local source files.
