# Earnings Analysis Dashboards

Static GitHub Pages dashboards for presenting quarterly earnings as concise,
chart-led research pages. Reviewed pages currently cover Alphabet, Meta,
Microsoft and TSMC.

## Build

```bash
python3 build/all.py
python3 -m http.server 8765
```

Open `http://127.0.0.1:8765/`, then choose:

- `http://127.0.0.1:8765/googl/`
- `http://127.0.0.1:8765/meta/`
- `http://127.0.0.1:8765/msft/`
- `http://127.0.0.1:8765/tsm/`

Live site: https://hzhan7.github.io/Earnings-Analysis-Dashboards/

## Content boundary

- Inputs: the local Earnings Analysis note plus company-reported quarterly data.
  Every page updates on one cadence — quarterly — so nothing plotted here can
  move between earnings dates.
- Published numbers: company-reported figures and transparent arithmetic
  derivations only. Short commentary is research interpretation, not company
  guidance or a rating.
- Market expectations may be published as a labelled, dated comparison point
  (`市场预期`), with no broker or vendor named.
- Excluded: ratings, target prices, valuation, broker-attributed estimates,
  unverified customer-concentration estimates, local absolute paths, source
  PDFs, PPTs and transcripts.
- `D` means Derived / 自算; it does not mean a company-defined non-GAAP metric.
- Quarters are labelled by calendar quarter on every page. Microsoft's fiscal
  year ends in June, so its `Q2 2026` is the quarter ended 2026-06-30, which the
  company itself calls FY2026 Q4; the page says so in its subtitle and notes.
  Without one convention the cross-company capex table would compare different
  three-month periods and look fine doing it.

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
   geography; Meta gets the depreciation curve, trailing cash conversion and its
   two non-advertising revenue lines; Microsoft gets capital intensity, margins,
   the depreciation curve and the finance-lease channel that sits outside its
   capex definition; TSMC gets node migration, platform mix and working capital.

TSMC's first section carries three guidance charts rather than one, because the
eight-quarter view cannot answer either question that matters about a company
which has beaten its own midpoint almost every quarter. The second pulls the
window back to the start of the guidance table; the third splits each beat into
what the company produced and what the currency did. That split is an identity,
not an estimate: revenue is guided in US dollars at an FX assumption stated on
the call and reported at the rate the quarter realised, so the two legs
compound exactly to the reported beat. It changes the reading — the dollar beat
usually *understates* the operating beat, and in 2025Q2 it inverts it.

Two of the series exist only on this site, because the number that decides the
quarter is not one any filing prints:

- Meta's **year-over-year incremental operating margin** (ΔOI / ΔRevenue). A
  margin falling from 41% to 31% and a company whose extra dollar of revenue
  carries a negative extra dollar of profit look identical on a margin chart.
- Microsoft's **free cash flow adjusted for unpaid capex**. Reported free cash
  flow counts only capex that was paid; the 10-K discloses how much was still
  sitting in accounts payable, so subtracting that year's increase turns a
  −6.5% year into a −31.6% one using three disclosed numbers and no estimate.

Where a threshold is settled on an adjusted basis but the history exists only on
the reported one, the chart carries both lines rather than silently plotting one
and captioning the other.

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
takeaways, a shared `AI capex 循环` cross-reference published byte-identically on
every page, the official-source drawer, and a `口径与方法说明` block that lists
what each page knowingly does not carry.

The cross-reference puts the three hyperscalers' quarterly **cash** capex against
the foundry quarter that has to build it. Cash purchases of property and
equipment is the one capex definition all four filers report the same way —
Meta's headline number adds finance-lease principal and Microsoft's adds
finance-lease additions, so the company-defined totals are not addable.

Each company has a reviewed source series and a company-specific builder. The
shared `build/all.py` entry point rebuilds every company payload, their thin
HTML shells and the cross-company roster without exposing local source files.

Thresholds on the page are local research settings, not company guidance and not
a rating. Market expectations may be published, but only unattributed and dated
— never with a broker name attached.
