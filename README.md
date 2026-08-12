# Earnings Analysis Dashboards

Static GitHub Pages dashboards for presenting quarterly earnings as concise,
chart-led research pages. Reviewed pages currently cover Alphabet, Meta,
Microsoft, NVIDIA and TSMC.

## Build

```bash
python3 build/all.py
python3 -m http.server 8765
```

Open `http://127.0.0.1:8765/`, then choose:

- `http://127.0.0.1:8765/googl/`
- `http://127.0.0.1:8765/meta/`
- `http://127.0.0.1:8765/msft/`
- `http://127.0.0.1:8765/nvda/`
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
  company itself calls FY2026 Q4; NVIDIA's ends in late January, so its
  `Q1 2026` is the quarter ended 2026-04-26, which the company calls FY2027 Q1.
  Both pages say so in their subtitle and notes. Without one convention the
  cross-company capex table would compare different three-month periods and look
  fine doing it.

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
   capex definition; NVIDIA gets six years of margins and operating leverage
   plus the inventory-and-supply-commitment block that carries its real capital
   intensity; TSMC gets node migration, platform mix and working capital.

On the Alphabet, Meta and Microsoft pages these run on the ten-year record
rather than eight quarters, because eight quarters cannot tell a trend from a
wobble and — for capital intensity — is barely one build cycle. It changes what
several of them say: Microsoft's capital intensity sat in a narrow band from
2016 to 2019 and is now at a ten-year high, and Alphabet's revenue
reacceleration reads as a third episode rather than a first.

The window is per chart, not per page, and it stops where the company's own
disclosure stops rather than being padded:

- All three file their cash-flow lines year-to-date only, so every quarter after
  the first is one filed figure minus the previous one, and the fiscal fourth is
  the year minus the nine months. Both legs are filed numbers. Where a printed
  quarterly column also exists it wins, because each leg of a subtraction is
  rounded to the million first: Alphabet's 2025Q4 revenue derives to 113,829 and
  the company prints 113,828.
- Three charts keep a short axis because the number does not exist further back,
  and each says so on the chart. Microsoft discloses depreciation annually to
  2009 but quarterly only recently; Alphabet tagged no comparable quarterly
  depreciation line before 2023; Meta's two segment lines begin when segment
  reporting began, and its finance-lease principal begins with ASC 842, which is
  what its own free-cash-flow definition nets.
- Meta's Family-of-Apps other revenue for 2024Q4 was 522 here and 519 in the
  company's own release — 519 is also what the filed year minus the three
  reported quarters gives, while 522 overshoots the year by 3. Corrected, with a
  test pinning the reconciliation.

TSMC's, NVIDIA's and Meta's first sections are built out further than the
others, because those three companies put a quarterly guidance range in a filing
and the other two do not. Eight quarters cannot say whether clearing a range is
normal for a company; the full record can.

TSMC guides three numbers every quarter — revenue, gross margin and operating
margin — and fifteen quarters pulled from the fifteen earnings 6-Ks themselves
answer it. The answer differs sharply by metric: revenue cleared the top of its
range in 8 of 14 quarters, gross margin in 9, and **operating margin in all 14 — not one
quarter landed back inside the range**. That last one reframes the guidance as
a floor rather than a forecast, which is not visible from any single quarter.

Two more charts sit with them. One splits each revenue beat into what the
company produced and what the currency did — an identity, not an estimate,
because revenue is guided in US dollars at an FX assumption stated on the call
and reported at the rate the quarter realised, so the two legs compound exactly
to the reported beat. It changes the reading: the dollar beat usually
*understates* the operating beat, and in 2025Q2 it inverts it. The other asks
the separate question of whether the quarter beat the *market* rather than the
company, and shows why the answer depends on the profit line — a headline EPS
beat of +12.2% is +2.2% once the quarter's one-off disposal gain comes out.

NVIDIA guides revenue ±2%, both gross margins ±50bp and both operating expense
lines, so its record runs 23 finished quarters back to 2020, read from the 24
quarterly earnings 8-Ks. Its shape is the opposite of TSMC's, and the contrast
is why the page is worth the build-out: **revenue cleared the top of its band in
20 of 23 quarters, but gross margin sat inside its band in 15 of 23 and broke
the bottom three times** — by 21.3pp, 8.9pp and 10.0pp. So the revenue guidance
behaves like a floor and the margin guidance like a genuine forecast, and the
page has to say both things at once rather than settling on one verdict.

The decomposition chart is what makes that readable. Guiding revenue, margin and
opex together implies an operating income NVIDIA never prints, and the distance
from what it reported splits exactly three ways — revenue leg, margin leg, opex
leg — with no estimate anywhere. All three quarters that fell short of that
implied bar were the *margin* leg collapsing (gaming inventory write-downs in
2022, the US$4.5B H20 charge in 2025); in the worst of them the revenue leg was
still positive. The company's operating disappointments have come from cost and
write-downs, never from demand.

Two hazards had to be handled rather than smoothed over. NVIDIA's dollar band
chart is drawn over eight quarters, not 23, because revenue grew from US$4.4B to
US$91B and a ±2% band collapses to a few pixels at the left edge of a linear
axis; the full record is carried by the scale-free deviation chart instead, and
the page says so on the chart. And NVIDIA changed its non-GAAP definition in
FY2027 Q1 to include stock-based compensation, restating history — so the long
series run on GAAP, whose definition never moved, while every guidance/actual
pair is compared within the single basis that applied at the time.

Meta guides one number — next-quarter revenue, as a dollar range in the Outlook
section of every quarterly 8-K EX-99.1 — so its page carries the same pair of
charts: the range against the reported result, then the distance from the guided
midpoint. Its answer is a third distinct shape. In 18 finished quarters Meta
cleared the top of its range 8 times, landed inside it 10, and **never once
missed the bottom**, so that lower bound has never been tested and reads as a
floor the company is willing to publish rather than one end of a forecast. The
midpoint chart adds what the band cannot show: the beat is narrowing.

**Microsoft and Alphabet get no such record, and that is a sourcing limit rather
than an editorial choice.** Microsoft's own 8-K says in as many words that
guidance is given on the earnings call and webcast, so nothing in its filings
can carry a range; the quarterly outlook block on its page comes from the call,
one quarter at a time. Alphabet gives no quarterly numeric guidance at all — its
capital-expenditure commitment for the year reaches a press release only when it
changes, twice in forty-five releases. Neither page gets a fabricated record:
transcribing fifteen quarters off webcast material that cannot be checked
against a second source is the failure this repo is built to avoid.

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

NVIDIA sits between the two ends rather than at one of them, so the table now
carries its **Data Center** line as a middle column: hyperscaler cash capex →
the accelerator revenue it lands in → the foundry quarter that has to build it.
Data Center rather than total revenue, because a hyperscaler's capex does not
buy game consoles. Over these eight quarters the three hyperscalers' capex grew
3.1x, NVIDIA's Data Center 2.4x and TSMC's revenue 1.7x — the same wave,
attenuating as it moves upstream.

One caveat travels in the column header rather than being corrected away:
NVIDIA's quarters end about four weeks after the calendar quarters the rest of
the table uses (late April against 31 March), so a row compares periods that do
not exactly coincide. Shifting a reported quarter onto another company's
calendar would mean inventing a number, which is worse than an offset a reader
can see. The most recent row is a dash because NVIDIA has not reported that
quarter yet.

Each company has a reviewed source series and a company-specific builder. The
shared `build/all.py` entry point rebuilds every company payload, their thin
HTML shells and the cross-company roster without exposing local source files.

Thresholds on the page are local research settings, not company guidance and not
a rating. Market expectations may be published, but only unattributed and dated
— never with a broker name attached.
