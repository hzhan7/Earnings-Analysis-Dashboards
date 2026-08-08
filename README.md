# Earnings Analysis Dashboards — GOOGL prototype

Static GitHub Pages prototype for presenting quarterly earnings as a concise,
chart-led research page.  The first sample covers Alphabet Q2 2026.

## Build

```bash
python3 build/googl.py
python3 -m http.server 8765
```

Open `http://127.0.0.1:8765/googl/`.

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

## Prototype modules

- One conclusion-led headline and three short takeaways.
- One quarterly scorecard.
- Eight numbered exhibits with chart/table toggle.
- Collapsed audit tables and official-source drawer.
- Desktop and mobile layouts using the same static payload.

The build is intentionally GOOGL-specific.  It should become the visual and
content specification before the remaining watchlist companies are added.
