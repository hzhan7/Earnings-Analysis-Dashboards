# Earnings Analysis Dashboards

Static GitHub Pages dashboards for presenting quarterly earnings as concise,
chart-led research pages. Reviewed pages currently cover Alphabet, Amazon,
Cadence, Meta, Microsoft, NVIDIA, Synopsys and TSMC.

## Build

```bash
python3 build/all.py
python3 -m http.server 8765
```

Open `http://127.0.0.1:8765/`, then choose:

- `http://127.0.0.1:8765/amzn/`
- `http://127.0.0.1:8765/cdns/`
- `http://127.0.0.1:8765/googl/`
- `http://127.0.0.1:8765/meta/`
- `http://127.0.0.1:8765/msft/`
- `http://127.0.0.1:8765/nvda/`
- `http://127.0.0.1:8765/snps/`
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
  `Q1 2026` is the quarter ended 2026-04-26, which the company calls FY2027 Q1;
  Synopsys' ends in October, so its `Q2 2026` is the quarter ended 2026-07-31,
  which the company calls FY2026 Q3. Each page says so in its subtitle and
  notes. Without one convention the
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
   geography; Amazon gets revenue growth, capital intensity, how far the
   depreciation wave still has to run, and AWS's two shares — a fifth of the
   revenue and three fifths of the operating profit; Meta gets the depreciation curve, trailing cash conversion and its
   two non-advertising revenue lines; Microsoft gets capital intensity, margins,
   the depreciation curve and the finance-lease channel that sits outside its
   capex definition; Cadence gets the ASC 606 revenue record, ten years of
   margin, the same margin with stock compensation put back as a cost, the
   operating leverage that produced it, and the coverage multiple behind its
   record backlog; NVIDIA gets six years of margins and operating leverage
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

- Alphabet, Meta and Microsoft file their cash-flow lines year-to-date only, so
  every quarter after the first is one filed figure minus the previous one, and
  the fiscal fourth is the year minus the nine months. Both legs are filed
  numbers. Where a printed quarterly column also exists it wins, because each
  leg of a subtraction is rounded to the million first: Alphabet's 2025Q4
  revenue derives to 113,829 and the company prints 113,828.
- Amazon is the exception and needs no differencing at all: its 10-Q cash-flow
  statement prints three-month, year-to-date and trailing-twelve-month columns
  side by side, so every quarter but the fiscal fourth is a filed figure. Even
  the fourth is printed — in the Q4 press release — and where it is, it wins:
  2020Q4 capex derives to 14,823 and the release prints 14,824. Amazon's
  quarterly capex and depreciation stop at 2016Q2 rather than 2016Q1, because
  the earlier quarter exists only year-to-date and that year's annual total is
  not tagged either; the charts start where the number does.
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
- Cadence's long series start at 2018Q1 rather than being padded backwards:
  ASC 606 replaced ASC 605 for the quarter beginning 2018-01-01 and the earlier
  years were never restated, so the two segments are not one line. Its
  guidance/actual pairs are unaffected — each pair sits inside a single basis —
  and only the level charts carry the break.
- Cadence discloses product-category mix (`Core EDA` / `Semiconductor IP` /
  `System Design and Analysis`) as **integer percentages of revenue and nothing
  else**, so every dollar in that chart is a percentage times the reported
  total. Dividing two of those integers compounds ±0.5pp into roughly ±10pp on a
  growth rate, which is why the page reads its own "+43%" IP number as "just
  over 40%" — the same thing the press release says. Geography is the exception
  and the page uses it: China is a **filed dollar line** in the segment note, so
  it is plotted from the filing rather than derived. The derivation the local
  note used reads this quarter's China move as +107%; the filed dollars say
  +95.7%.
- One threshold set last quarter is reported as **unsettleable rather than
  breached**. Book-to-bill's numerator is the difference of two backlog figures
  the company rounds to US$0.1B, so a US$100M net add carries ±US$100M and the
  ratio spans 1.00x–1.13x — straddling the 1.10x line it was meant to be judged
  against. The backlog level and the coverage multiple survive the same rounding
  and are kept.
- Amazon's trailing free cash flow is a **disclosed** series — the company
  prints it in every release — and reading thirty quarters of it corrected the
  local note, which called this quarter's −$7.6B the first negative reading
  since 2014. The company's own series was negative through 2021Q4–2023Q1 and
  bottomed at −$23.5B in 2022Q2. The note was not careless: each release shows
  only six quarters, so the previous trough is invisible unless you stack them.
  The page plots all thirty and says so. Amazon also moved the *definition*
  twice, in 2018 and 2019, ending at "net of proceeds from sales and
  incentives"; the series starts after the last move rather than splicing.

Amazon's, Cadence's, Synopsys', TSMC's, NVIDIA's and Meta's first sections are
built out further than the others, because those six companies put a quarterly
guidance range in a filing and the other two do not. Eight quarters cannot say whether
clearing a range is normal for a company; the full record can.

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
Operating expenses are the third answer again: guided as a single number with no
range at all, and landing above it 12 times and below it 11 — as close to
unbiased as this record gets.

Each of the three gets the same pair, level chart then deviation chart, grouped
so one metric is read through before the next begins. The opex level chart draws
its guidance as a hairline rather than a band, because a point guidance has no
width and pretending otherwise would invent one; its title says "above" and
"below" instead of "cleared the upper bound", which would be a category error.

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
pair is compared within the single basis that applied at the time. That change
is visible in exactly one place, the opex *level* chart, where it steps the line
up by about US$1.9B; it carries a structural-break marker at that quarter rather
than being drawn as one continuous series. Its deviation twin needs no marker,
because dividing actual by guided cancels the change out — both legs moved
together.

Meta guides one number — next-quarter revenue, as a dollar range in the Outlook
section of every quarterly 8-K EX-99.1 — so its page carries the same pair of
charts: the range against the reported result, then the distance from the guided
midpoint. Its answer is a third distinct shape. In 18 finished quarters Meta
cleared the top of its range 8 times, landed inside it 10, and **never once
missed the bottom**, so that lower bound has never been tested and reads as a
floor the company is willing to publish rather than one end of a forecast. The
midpoint chart adds what the band cannot show: the beat is narrowing.

Amazon is the only company here that puts **two** ranges in every filing — net
sales and operating income, in the `Financial Guidance` block of each quarterly
8-K's EX-99.1, in the same sentence structure, unbroken for 37 guided quarters
back to Q3 2017. It did not withdraw guidance in 2020 either; it widened the
operating-income range to $(1.5)B–$1.5B and kept publishing. The record is a
fourth distinct shape: in 36 finished quarters net sales cleared the top 21
times and operating income 27 times, and **neither one ever landed below the
bottom**.

Having both is what makes the interesting chart possible. Guiding a level and a
profit implies an operating margin Amazon never prints, and the distance from
what it reported splits exactly two ways — a revenue leg and a margin leg, no
estimate anywhere. The revenue leg never exceeds $0.60B in nine years; the
margin leg carries the rest, $5.00B of the $5.46B beat in the latest quarter. So
the demand forecast is close to honest and the *cost* forecast is the half held
back, which is not how a "beats its own guidance" record usually reads — and it
is the reason the page's own thresholds, set a quarter earlier against
management's guided midpoint, all held. A framework anchored on the guidance of
a company that has never missed the bottom of either range is anchored too low
by construction.

Cadence files the longest record of the five, and the most one-sided. Its
quarterly outlook — revenue, GAAP and non-GAAP operating margin, GAAP and
non-GAAP EPS — is stated in the CFO Commentary filed as EX-99.02 of every
quarterly earnings 8-K, unbroken for 43 quarters back to Q1 2016. In the 42
finished ones **reported revenue never landed below the guided floor, and never
even below the guided midpoint — 42 times out of 42**. Non-GAAP EPS never broke
the floor either. Only the operating margin ever came up short, twice, by 0.3pp
and 0.1pp, and both times against a guidance that was a single number rather
than a range, so there was no band to land in.

That last distinction is the reason the parser had to be told about it. Cadence
writes some ranges with the word "to" — `29% to 30%` — and reading those as a
point overstated three 2018 beats by about a hundred basis points each. Twenty
of the 43 margin guidances really are single points (`~30%`, `approximately
30%`) and are drawn as hairlines; the other 23 are bands. A test now pins that
the form flag and the two endpoints agree.

**A perfect record means less here than it looks, and the page says so on every
one of the six charts.** Cadence publishes each quarter's outlook alongside the
*previous* quarter's results, and that release lands inside the quarter being
guided: about four weeks in for Q2, Q3 and Q4, and past the halfway mark for Q1,
whose guidance waits for the mid-February annual release — the Q1 2021 range was
published on day 50 of a 91-day quarter. This is not an ex-ante forecast, and a
page that let "never missed in 42 quarters" stand without that sentence would be
publishing a tautology dressed as a finding.

Synopsys files the most *complete* guidance of the eight, and it produces the
only two-sided answer on this site. The "Financial Targets" table in every
earnings 8-K EX-99.1 guides **every input of earnings per share** — revenue,
GAAP and non-GAAP expenses, non-GAAP other income, the non-GAAP tax rate and the
fully diluted share count — and then guides GAAP and non-GAAP EPS themselves.
Twenty-four quarters of it run back to Q4 2020.

Because the sixth number is implied by the other five, the table can be checked
against itself: running the five midpoints through
`(revenue − expenses + other) × (1 − tax) ÷ shares` reproduces the company's own
printed EPS midpoint to within US$0.02 in 15 of the 24 quarters and within
US$0.06 in all of them, the residual being the rounding of the published
endpoints. That is what licenses the page to treat "guided revenue minus guided
expenses" as an operating income Synopsys stands behind but never prints, and to
split each beat into a revenue leg and an expense leg with no estimate anywhere.
The legs say the beats are a demand story, not a cost story: the revenue leg
dominates almost every quarter.

The two-sided part is the finding. In 23 finished quarters **revenue landed
*inside* the guided range 13 times** — Synopsys forecasts its own top line about
as well as a backlog-driven model should let it — while **non-GAAP EPS landed
*above* the top of its range 20 times**. Same press release, same quarter, same
twelve-week horizon: the revenue number behaves like a forecast and the earnings
number like a floor. No other page here has one company saying both things at
once, and it is only visible because the two records sit side by side.

It also guides its own share count, which nothing else here does, and that line
is where the acquisition shows up: flat at 156 million for years, then a step to
187 million when Ansys closed in July 2025. The one quarter that broke *above*
the guided share range is the closing quarter itself.

Both revenue misses in the record are marked rather than smoothed. One is not a
miss at all: Synopsys moved Software Integrity to discontinued operations in the
quarter ended 2024-04-30, so that quarter was guided on a basis that included the
business and reported on one that did not. The 10-Q's discontinued-operations
note puts those three months at US$126.4M, and adding it back to the reported
US$1,454.7M gives US$1,581.1M — inside the US$1,560–1,590M that had been guided,
and near the top, which is exactly what the company called it in its own release.
The chart keeps the breaching bar and carries a structural-break marker at that
quarter. The other miss is real: Q2 2025, which the CEO's own release attributes
to Design IP underperforming — the line that has just turned back up.

One number the page refuses to publish is the one the local note leans on hardest.
"EDA excluding Ansys" cannot be recomputed from any filing: Synopsys has never
disclosed Ansys' actual quarterly revenue, only an *expected* figure in the
footnote to its full-year revenue target. So the page plots what that footnote
does support — the four FY2026 revenue targets split into the acquired half and
the rest, which shows the US$105M of raises breaking down into US$80M of Ansys
and US$25M of everything else — and names the quarterly split in the excluded
list instead of deriving it.

**Microsoft and Alphabet get no such record, and that is a sourcing limit rather
than an editorial choice.** Microsoft's own 8-K says in as many words that
guidance is given on the earnings call and webcast, so nothing in its filings
can carry a range; the quarterly outlook block on its page comes from the call,
one quarter at a time. Alphabet gives no quarterly numeric guidance at all — its
capital-expenditure commitment for the year reaches a press release only when it
changes, twice in forty-five releases. Neither page gets a fabricated record:
transcribing fifteen quarters off webcast material that cannot be checked
against a second source is the failure this repo is built to avoid.

Five of the series exist only on this site, because the number that decides the
quarter is not one any filing prints:

- Amazon's **two-leg decomposition of the operating-income beat**, above, and
  the **implied guided operating margin** it falls out of.
- Amazon's **AWS sequential revenue increment** in dollars. Under a supply
  constraint the year-over-year rate is set by how fast racks come up, not by
  the base — reading the base is what produced a wrong call on the quarter, so
  the page retires the growth-rate threshold and anchors on the increment.
- Meta's **year-over-year incremental operating margin** (ΔOI / ΔRevenue). A
  margin falling from 41% to 31% and a company whose extra dollar of revenue
  carries a negative extra dollar of profit look identical on a margin chart.
- Cadence's **implied fourth-quarter operating margin**. The company guides the
  full year and the third quarter and never the fourth, but the fourth is what
  the other two imply: the full-year non-GAAP operating income at the guidance
  midpoint, less the first half as reported, less the third quarter's guided
  midpoint, over the revenue the same subtraction leaves. It comes to 42.84%,
  level with the quarter that carried a US$128.5M legal charge, in a year whose
  revenue guidance was just raised — which is the tension the whole page is
  about, and it is four filed numbers and no estimate.
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

The cross-reference puts the four hyperscalers' quarterly **cash** capex against
the foundry quarter that has to build it. Cash purchases of property and
equipment is the one capex definition every filer here reports the same way —
Meta's headline number adds finance-lease principal, Microsoft's adds
finance-lease additions and Amazon's own free-cash-flow definition nets off
proceeds from equipment sales and incentives, so the company-defined totals are
not addable.

Amazon joined this table when its page was built. It is the largest spender of
the four in every quarter of the window, so leaving it out understated each row
by roughly a third.

NVIDIA sits between the two ends rather than at one of them, so the table now
carries its **Data Center** line as a middle column: hyperscaler cash capex →
the accelerator revenue it lands in → the foundry quarter that has to build it.
Data Center rather than total revenue, because a hyperscaler's capex does not
buy game consoles. Over these eight quarters the four hyperscalers' capex grew
2.8x, NVIDIA's Data Center 2.4x and TSMC's revenue 1.7x — the same wave,
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
