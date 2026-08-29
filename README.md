# Earnings Analysis Dashboards

Static GitHub Pages dashboards for presenting quarterly earnings as concise,
chart-led research pages. Reviewed pages currently cover Alphabet, Amazon,
American Express, Broadcom, Cadence, Charles Schwab, Costco, Ferrari,
Interactive Brokers, Mastercard, Meta, Microsoft, Moody's, MSCI, Nasdaq,
NIKE, NVIDIA, Philip Morris International, S&P Global, Synopsys, TJX, TSMC
and Visa.

## Build

```bash
python3 build/all.py
python3 -m http.server 8765
```

Open `http://127.0.0.1:8765/`, then choose:

- `http://127.0.0.1:8765/amzn/`
- `http://127.0.0.1:8765/avgo/`
- `http://127.0.0.1:8765/axp/`
- `http://127.0.0.1:8765/cdns/`
- `http://127.0.0.1:8765/cost/`
- `http://127.0.0.1:8765/googl/`
- `http://127.0.0.1:8765/ibkr/`
- `http://127.0.0.1:8765/ma/`
- `http://127.0.0.1:8765/mco/`
- `http://127.0.0.1:8765/meta/`
- `http://127.0.0.1:8765/msci/`
- `http://127.0.0.1:8765/msft/`
- `http://127.0.0.1:8765/ndaq/`
- `http://127.0.0.1:8765/nke/`
- `http://127.0.0.1:8765/nvda/`
- `http://127.0.0.1:8765/pm/`
- `http://127.0.0.1:8765/race/`
- `http://127.0.0.1:8765/schw/`
- `http://127.0.0.1:8765/snps/`
- `http://127.0.0.1:8765/spgi/`
- `http://127.0.0.1:8765/tjx/`
- `http://127.0.0.1:8765/tsm/`
- `http://127.0.0.1:8765/v/`

Live site: https://hzhan7.github.io/Earnings-Analysis-Dashboards/

## Verification

```bash
python3 -m unittest discover -s tests -q
```

The suite reads payloads and source; it does not render anything. That gap is
real: `build/payload_guard.py` rejects a non-finite number *in a payload*, so a
NaN produced one call later, inside `assets/charts.js`, passes every check.
AVGO Exhibit 16 shipped `<line y1="NaN">` that way — the browser drops such an
element with no console message, so the chart looked finished while its dashed
reference line was simply absent and the legend went on naming it.

`tests/render_check.js` closes that gap by loading all 17 pages under jsdom the
way a browser does and failing on any non-finite value that reaches an SVG
attribute or a chart label. It is the one thing here with a third-party
dependency, so it is not vendored and `tests/test_rendered_svg.py` skips when
jsdom is absent:

```bash
npm --prefix tests install
```

`tests/test_chart_contract.py` pins the same class from source and payloads with
no dependency at all, and is what actually runs on a fresh clone.

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
- Amounts are in the currency the filer reports in. Ferrari reports under IFRS
  in euro, so its page is denominated in EUR and its figures are not addable to
  the US-dollar pages.
- Quarters are labelled by calendar quarter on every page. Microsoft's fiscal
  year ends in June, so its `Q2 2026` is the quarter ended 2026-06-30, which the
  company itself calls FY2026 Q4; NVIDIA's ends in late January, so its
  `Q1 2026` is the quarter ended 2026-04-26, which the company calls FY2027 Q1;
  Synopsys' ends in October, so its `Q2 2026` is the quarter ended 2026-07-31,
  which the company calls FY2026 Q3; Broadcom's ends in early November, so its
  `Q1 2026` is the quarter ended 2026-05-03, which the company calls FY2026 Q2;
  Visa's ends in September, so its `Q2 2026`
  is the quarter ended 2026-06-30, which the company also calls FY2026 Q3;
  NIKE's ends in May, so its `Q2 2026` is the quarter ended 2026-05-31, which
  the company calls FY2026 Q4 — and because that year-end sits mid-quarter, the
  offset is not constant across its own year: NIKE's fiscal Q1 and Q2 land in
  the *previous* calendar year (`Q3` and `Q4`) while its Q3 and Q4 land in the
  same one. Each page says so in its subtitle and notes. Without one convention the
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
   intensity; Broadcom gets its two engines' segment operating margins, the
   capital intensity a fab-lite designer actually runs on, cash conversion, and
   the post-VMware deleveraging path; TSMC gets node migration, platform mix and
   working capital;
   Mastercard gets its two revenue legs, the operating margin on the same basis
   the company adjusts to, the leverage its buyback now runs on, and the price
   it paid for its own stock quarter by quarter; Visa
   gets thirteen years of its client-incentive rate, the two revenue growth
   rates whose gap is that rate moving, the mix shift across its four gross
   revenue lines, the non-US share of net revenue, and capital returned against
   the cash flow that funds it; Interactive Brokers gets the revenue mix that a
   full rate cycle rewrote, net interest margin against the earning assets that
   quadrupled under it, accounts and the equity each one carries, the Up-C wedge,
   operating leverage, and the realised fee per order, which ends the record
   below where it starts; Moody's gets eight years of the operating margin
   cycle its guidance rides, the widening and narrowing gap between GAAP and
   adjusted EPS, the two cash-flow legs, and the adjusted operating income of
   its two segments — one line that has not retraced in twenty-one quarters
   and one that has travelled a full cycle inside them; S&P Global gets the
   two legs of Ratings across a full issuance cycle, its reported operating
   margin against the same margin with disposition gains taken out, the
   revenue and segment structure the IHS Markit merger rewrote, the six filed
   revenue types, the index assets its asset-linked fees are charged on, and
   the buyback that ran at 4.6x operating cash flow in the year the merger
   closed; TJX gets ten years of pretax margin against capital
   intensity, the store count and square footage that are its whole growth
   engine, ten years of buybacks against the share count, and the three-bar
   cash structure that shows what is left for shareholders after the stores
   are built; Philip Morris gets ten years of the smoke-free transition in
   filed dollars, thirty-eight quarters of revenue against the two margins
   that diverge across them, and the operating cash flow of a company whose
   capital expenditure has never exceeded 17.4% of it in ten years; NIKE gets
   thirteen years of its direct-to-consumer share against the gross margin
   that shift was supposed to buy, the two channels in dollars, thirty-two
   quarters of the same share at quarterly resolution, the two
   selling-and-administrative lines that carry the cost of running a direct
   business, ten years of cash flow against capital returned, and the price it
   actually paid for its own stock; Nasdaq gets forty-six quarters of its two operating margins and
   the amortization gap between them, the same window showing the trading
   business shrinking from 37% of net revenue to 23%, and the index assets that
   went from US$114B to over a trillion; American Express gets
   thirty-eight quarters of the two prices it charges — the annual fee per
   card against the merchant discount rate — the four revenue legs those two
   prices land in, and the wedge between net income and earnings per share
   that its buyback opens; Costco gets the two legs its operating margin
   splits into across thirteen years, the gross margin against the SG&A rate
   that is the one of the two that actually moved, how long a single
   membership-fee increase takes to finish arriving, and what a retailer
   running at 2% capital intensity does with the cash it keeps.

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

Amazon's, Broadcom's, Cadence's, Synopsys', TJX's, TSMC's, NVIDIA's and Meta's
first sections are built out further than the others, because those eight
companies put a quarterly number in a filing. Eight quarters cannot say whether
clearing a range is normal for a company; the full record can. Broadcom is the
one of the eight whose filed number is usually **not** a range, which turns out
to be the point of its page rather than a caveat on it.

Moody's is a **third** case rather than a member of either group, and its page is
built out for that reason. It files no quarterly range at all, but it does file a
numeric one — a **full-year outlook table** in the EX-99.1 of every earnings 8-K,
set in February and revised in April, July and October. So the object its first
section settles is a *year*, and the variable that turns out to matter is not
whether the company cleared its range but **how far ahead it was standing when it
drew one**. Against the final October range, seven finished years look like every
other never-missed record here: adjusted diluted EPS landed above the top four
times, inside three, and never once below. Against the initial February range the
same seven years land above six times and below once — and **not once inside**.
The February band has never contained the answer. The two vintages' mean absolute
deviation from the guided midpoint is **13.3% in February and 1.9% in October** —
a seventh of the error for the same metric, the same years, and the same company.

The gap between those two tallies is the page, and 2022 is why. Debt issuance
collapsed with rates, and because MIS revenue is issuance-driven and issuance is
not a variable Moody's controls, the midpoint fell 34% between February and
October — from US$12.65 to US$8.35 — before the actual cleared even that. So the
February number is a bet on the debt markets and the October number is largely
bookkeeping on a year three-quarters banked. **A "never missed the bottom" record
means much less at a ten-week horizon than at a twelve-month one, and the page
draws both bands rather than reporting one hit rate.** The same caution the
Cadence page applies to guidance published four weeks into the quarter it guides,
applied to a horizon that shrinks across the year instead of being short from the
start.

Three things license reading that table as arithmetic rather than as targets. The
company prints its own previous guidance beside the current one with an explicit
`NC` marker, so the revision path is disclosed by the filer and each release
independently confirms the one before it. Every release reconciles GAAP diluted
EPS to adjusted diluted EPS, operating margin to adjusted operating margin, and
operating cash flow to free cash flow, with each bridging item named and
quantified — and all three close exactly, to the cent and the tenth of a point.
And what the table gives in *words* the page refuses to plot: revenue, operating
expenses and ARR are guided as "increase in the high-single-digit percent range",
which is not a range with endpoints, so those lines get no band and no hit rate.

Two traps in that record are handled rather than smoothed. The two guidance
columns **swap order** partway through the history — `Current` first until 2022,
`Last Publicly Disclosed` first after — so a fixed column position silently
produces the wrong series for half the record; the page reads the header. FY2018
is excluded outright: the filing window opens in October 2018, so that year has
only its final revision and no February setting, and counting it would put a stub
year beside seven complete ones.

Moody's segment columns swap the same way — MIS first until April 2023, MA first
after — and its **segment margins are struck on total segment revenue while the
page charts external revenue**. MIS bills MA about US$50M a quarter internally, so
dividing adjusted operating income by the plotted revenue overstates MIS's margin
by 2–3pp. Against total revenue the identity closes to within 0.05pp in all 21
quarters, which is the rounding of the published percentage and nothing else.

One series exists on this site because the number that decides the year is not one
any filing prints as such: **MIS's share of revenue against its share of adjusted
operating income.** Ratings run 44.6%–63.1% of revenue across 21 quarters but
57.4%–83.0% of adjusted operating income — a minority of the top line in bad
years and always the majority of the profit. That asymmetry is the mechanism
behind the February guidance's error distribution, and neither share is a figure
the company reports; both are two filed numbers divided.

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

Synopsys files the most *complete* guidance of the nine, and it produces the
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

S&P Global was the first **annual** guidance record on this site — Nasdaq is the
other one, and the two are not the same object, because S&P Global guides
earnings and Nasdaq guides only costs. S&P Global
produces the sharpest two-sided answer of the earnings records. It has never published a
quarterly outlook at all; what it files, in the EX-99.1 of every quarterly
earnings 8-K, is a full-year outlook that it then revises once a quarter. So the
object the six pages above are built on does not exist here, and the honest
isomorph is built instead: for each fiscal year the successive vintages (opening
guidance, then the Q1, Q2 and Q3 revisions) are drawn as one continuous band, and
the year's reported result lands on the **final** vintage, the cell that settles
it. Thirty-one vintages across FY2019-FY2026 come out of the releases themselves.

The finding is that the two earnings numbers on the same table behave like
different objects. In seven finished years **adjusted diluted EPS never once
landed below its final range** - five years above the top, two inside. **GAAP
diluted EPS landed below in three of those same seven years.** Same release,
same table, same twelve-month horizon; the gap between them is entirely the
items the company itself excludes - deal amortization, disposition gains and
losses, impairments. The number that never misses is the one the company
defines. A third metric completes the picture rather than muddying it: adjusted
free cash flow, guided only since FY2023, came in **below** its floor in two of
three years. The earnings guidance behaves like a floor and the cash guidance
like a forecast.

Two things about that record needed handling rather than smoothing. The timing
caveat is stronger here than on Cadence's page: the four vintages are published
in February, April-May, July-August and October-November **of the year they
guide**, so the last one goes out with about ten of twelve months already
banked. "Never missed the final range" is close to a tautology, and the page
says so on every band. What still carries information is the *opening* vintage,
so the page adds a chart the band cannot draw - the deviation of each year's
result from **every** one of its four vintages, which shows the funnel closing
from 8.9% average absolute error to 1.6%. It also shows that the opening
guidance was beaten in six of seven years, and that the single exception is
FY2022 - the year S&P Global **withdrew** its guidance mid-year, on 2022-06-01,
citing extraordinarily weak market conditions for its Ratings business. That is
the same year the transaction leg of Ratings revenue hit the bottom of its
cycle, which is the other thing this page is about.

Because Ratings charges per rated issue, S&P Global's revenue contains a genuine
cycle and an annuity side by side, and both are filed separately every quarter
back to 2017Q4. Over 35 quarters the transaction leg ran US$624M to US$244M to
US$746M - a 61% drawdown and a full recovery to a record - while the
non-transaction leg (surveillance, annual fees, entity ratings) never fell
through the same window. Eight quarters cannot see either half of that. The
company's own billed-issuance KPI is deliberately *not* used to carry this
argument: it entered SEC filings only in the 1Q2024 10-Q, so an honest series
starts at 2023Q1, contains no down-cycle at all, and three of its fourteen
quarters are residuals rather than printed figures. It is plotted, with that
window stated on the chart.

Two structural breaks are marked. The IHS Markit merger closed 2022-02-28, so
FY2022 carries about ten months of the acquired business and FY2021 none:
reported revenue rose 8,297 to 11,181 (+34.8%) while the 10-K's own pro-forma
basis shows it *falling* 12,382 to 11,842 (-4.4%). Same year, opposite signs, so
the line is not drawn through it. And S&P Global Mobility was spun off on
**2026-07-01** - one day after the quarter this page reports. The Q2 2026
release rebased the FY2026 outlook onto a basis excluding it, dropping adjusted
EPS guidance from US$19.40-19.65 to US$17.50-17.75 while stating that the two
are "not directly comparable"; against the restated FY2025 base the company
published separately, the same revision is an **increase**, from +9.5% to +11.2%
growth. Every filed statement still consolidates Mobility, and the page
publishes them that way, because the recast has not reached a filing yet: 2025Q2
revenue prints US$3,755M in both the 2025 and the 2026 10-Q, unchanged. The page
carries no bridge across the rebase - the US$1.98 per-share add-back the company
disclosed is for FY2025, not FY2026, and using it as a FY2026 bridge would be
the publisher's invention rather than the company's disclosure.

Nasdaq guides **two numbers and no others**, and neither of them is a forecast of
the business. It has never published revenue guidance, EPS guidance or margin
guidance; what it files in every earnings release is a full-year **non-GAAP
operating expense** range and a full-year **non-GAAP effective tax rate** range,
with a standing footnote saying no GAAP equivalent will be provided. So the object
this page's first section settles is the company's own budget, and the question
"did it hit its guidance" means something different from what it means on every
other page here.

The record is one-sided in both directions, and they are opposite directions.
Against the year's **last** range, full-year non-GAAP operating expense landed
inside 7 times in eleven finished years and above it 4 times — and **not once
below**. The floor of the expense band has never bound: Nasdaq has never spent
less than it told you it would. Against the same final vintage the non-GAAP tax
rate landed inside 5 times in seven years and below twice, and **not once above**
— and three of those five "inside" verdicts sit exactly on the range's lower
edge. One guided number is never beaten downward and the other is never missed
upward.

Against the year's **first** range the expense record stops being one-sided:
5 inside, 3 above, 3 below. The mean absolute distance from the guided midpoint
runs 2.84% in January against 0.97% in October, and the range narrows from US$60M
wide to US$22M. That gap is the page. Most of what reads as discipline in the
October record is the ten months already banked when it is published, which is
the same caution the Cadence and S&P Global pages apply to their own never-missed
records.

Four caveats are carried on the charts rather than smoothed away, because three
of the four "above" verdicts and two of the three "below" ones have an
explanation. FY2022 clears the top of its final range by exactly US$1M. FY2023's
final range was set on 2023-10-18 and the Adenza acquisition closed two weeks
later, so the actual carries two months of a business the guidance did not.
FY2020's overshoot was pre-announced in a **separate 8-K filed twelve days after
the guided year had already ended** — a volume-statistics release that said
expenses would exceed the top of the range by about US$45M against a US$1,414M
actual, which is guidance issued with zero days remaining and is not counted as a
vintage here. And FY2018 and FY2019 came in below their January ranges because
businesses were sold mid-year, not because anyone economised. FY2017 is the one
year whose actual moved: US$1,280M as first reported, US$1,271M after ASC 606 was
adopted retrospectively, which flips it from inside its final range to below.
The page uses the as-first-reported figure, because the guidance was written on
the pre-606 basis, and says what the other reading would do to the tally.

The second thing this page is about is that Nasdaq's **gross revenue line
contains a government fee**. Its headline top line is "revenues less
transaction-based expenses", and the two expenses subtracted are transaction
rebates paid to liquidity providers and a line called brokerage, clearance and
exchange fees. That second line ran US$274M in 2025Q1, then **US$6M in each of
the next three quarters, then US$320M** — a swing that no earnings release
anywhere in the corpus explains. It is the SEC's Section 31 fee, whose rate went
to zero and came back, and the quarterly figures for it exist only in the MD&A
tables of the 10-Q and 10-K: not XBRL-tagged, not in the R-files, so the primary
document has to be parsed directly. What licenses the split is that the residual
— the real brokerage and clearing cost — sits between US$4M and US$8M in every
one of eighteen quarters. The 10-Q states the mechanism in its own words: the fee
is recorded in revenue and in expense in equal amounts, so "there is no impact on
our net revenues". Anyone quoting Nasdaq's total revenue growth is partly quoting
a fee schedule; this quarter gross Market Services revenue grew 25.9% and the net
line 11.1%, and the gap is almost entirely that.

Two reporting-basis traps had to be handled rather than smoothed, and both were
caught by an identity failing rather than by reading the releases. Nasdaq has run
four segment structures since 2015 and reclassifies between them without always
saying so, so taking each line's earliest sighting splices two bases: the segment
revenues came out US$9M short of net revenue for three quarters, because Capital
Access was being read from a January 2023 release still on the old structure while
Financial Technology came from the 2024 release that restated the same quarter.
Every quarter is now taken from a single release and the sum closes in all
fifteen. The same trap in the ARR series is worse because it looks like news: read
across releases, Capital Access ARR appears to grow 2.4x in one quarter, and the
year-over-year rate comes out at 5.6% where the company's own release says 8% —
Solovis was sold in October 2025 and the prior year restated. Growth rates on this
page are read off the two columns printed side by side in one release. The
company itself publishes both readings this quarter, 11% reported and 12%
organic, and the difference is exactly that divestiture.

Two things the page refuses to publish. Index revenue divided by ETP assets would
print as a basis-point fee rate and is not one — that revenue also includes index
options and futures licensing, which the company says has been doubling
year-over-year, and Nasdaq has never disclosed a fee rate. And the pass-through
ratio is drawn only over the fifteen quarters since 2022Q4, because before that
the Market Services line included businesses carrying no transaction-based
expense at all; the same 2022Q3 is US$305M on the old basis and US$245M on the
new, and a single line through that would read a reclassification as a rise in
the cost of doing business.

One derivation on that page exists because the obvious form has a hole in it.
S&P Global's income statement reads `revenue - expenses + gain on dispositions +
equity income = operating profit`, and the gain is large enough to matter:
2022Q1's reported 79.2% operating margin contains US$1,344M of antitrust-driven
divestiture proceeds and is 22.8% without them. But the filer never tags the
gain for a fiscal fourth quarter, so "operating profit minus the gain" would
break every Q4. The page plots revenue minus total expenses instead - two filed
legs, no holes - and a test pins that the two forms agree wherever the gain is
filed. The same discipline applies to the gain series itself, which is stored as
null rather than zero where it is untagged: 2025Q4 carried roughly US$270M, and
a zero there would have drawn it as clean operating profit.

Broadcom files a quarterly outlook too, and its record answers a question none
of the others do: **what happens to a delivery record when the company changes
the shape of the promise.** Across 33 earnings 8-Ks the `Business Outlook` block
takes four forms. It opens as a GAAP/non-GAAP table with a revenue range
(`$5,047M +/- $75M`); becomes a fiscal-year number for the whole of FY2019;
returns as a quarterly range through the first COVID year; and from the FY2021
Q1 outlook onward is a bare point — `approximately $6.6 billion` — with Adjusted
EBITDA quoted as a percentage of projected revenue rather than a dollar amount.
It reverts to fiscal-year guidance for three releases across the VMware year,
then returns to quarterly points. Eight reported quarters inside the window were
therefore never guided as quarters at all; the page draws those as gaps and
lists the annual guidance that replaced them.

The two halves say opposite-looking things. In the **five** quarters Broadcom
published a revenue *range*, the reported number landed **inside it every
time** — never above, never below. In the **nineteen** finished quarters it
published a *point*, the number came in **above every time**. Read uniformly
against the guided point or midpoint, all **24** finished quarters are positive,
and Adjusted EBITDA margin has cleared its guided percentage in all **18**.

A record with no misses would normally be the finding. Here it is the setup for
a better one, and two facts do the work. First, the beats are tiny and
astonishingly regular: revenue deviation spans +0.17% to +3.53% with a median of
+0.80%, across eight years that contain a COVID quarter, a US$69B acquisition
and a four-fold increase in revenue. Second — the Cadence caveat again, and
sharper — the outlook goes out with the *previous* quarter's results, a median
of 31 days into the 91-day quarter it guides. A third of the quarter is already
banked when the number is published. So the page says on every guidance chart
that this is much less a forecast than a disclosure of something already largely
known, and it declines to read "never missed" as forecasting skill.

Its own series is the decomposition. Guiding a revenue level and an Adjusted
EBITDA *margin* implies an EBITDA dollar amount Broadcom never prints, and the
distance from what it reported splits exactly two ways with no estimate. The
answer is a third distinct shape: Amazon's beats sit almost entirely in the
margin leg and Synopsys' almost entirely in the revenue leg, while **Broadcom's
split roughly evenly** — the margin leg is the larger half in 12 of 18 quarters.

A second identity carries the segment view. The two reportable segments' filed
operating incomes sum to the company's non-GAAP operating income **exactly, in
all 30 quarters the segment note covers** (with the retired IP-licensing segment
included for FY2019 and earlier), so the margin the company guides can be
attributed to the semiconductor engine and the software engine without an
estimate. It is worth attributing: infrastructure software is 32% of revenue and
38% of segment operating profit.

Two things its page refuses. **Segment gross margin** is not plotted: Broadcom
first disclosed segment cost of revenue under ASU 2023-07 in the FY2025 10-K, so
the quarterly series is two points long — and a threshold the local note set on
it ("semiconductor segment GM below 68%") is therefore reported as
**unsettleable rather than passed or failed**. And **AI semiconductor revenue**,
the number the whole equity story runs on, is not a reportable segment: it
appears only in the CEO's quote in the earnings release, rounded to US$0.1B, in
one quarter as an inequality (`over $4.4 billion`) and in another not as a level
at all. The page plots the six readings it has, in a chart kept deliberately
apart from the formal record, and says on the chart why they are not the same
kind of number.

American Express files an annual outlook too — full-year revenue growth and
full-year EPS, in the CEO's quote in the EX-99.1 of every earnings 8-K, revised
once a quarter across eleven fiscal years and 43 releases. **It is the first
record on this site that cannot be settled**, and that is the page rather than a
caveat on it. Six of the eleven years have no honest answer: FY2016 printed a
GAAP range and an ex-restructuring range for the same year; FY2017's guidance of
$5.80–$5.90 is not comparable to a GAAP result of $2.97 after the Tax Act;
FY2018 changed basis mid-year to adjusted EPS with the release stating a GAAP
reconciliation was unavailable; FY2020 was withdrawn — not in an earnings 8-K
but in a separate Item 7.01 filing on 2020-03-17, so reading only the earnings
set reports it as "never guided" rather than "guided, then withdrawn"; FY2021
was never guided at all, and seven consecutive releases carry no annual number
of either kind; FY2026 is still open.

What survives is a two-sided answer that exists only because both metrics sit in
the same sentence of the same release. In the five years where EPS settles it
**never landed below its range** — four inside, one above. In the six where
revenue growth settles it **landed below its floor once**, in FY2023. The number
management can steer clears its range; the number it cannot does not, and the
page's second section is the mechanism: the year-over-year change in pretax
income splits exactly two ways, an operating leg and a provision leg, and in the
latest quarter the provision line carries US$321M of a US$521M increase.

The FY2023 miss is itself a basis question rather than a verdict. Guidance was
15%–17% and the company reported "up 14 percent (15 percent FX-adjusted)": the
FX-adjusted figure lands exactly on the floor and the reported one does not. The
page settles it on the reported basis and prints both. Two neighbouring years
are handled the other way and reported as landing *on* the bound rather than
under it — FY2019 delivered 7.98% against a floor of 8 and FY2024 delivered
8.98% against a point of 9. Both guidance and result are stated by the company
only in whole percentage points, so the band and the diamond are drawn in whole
percentage points; settling a promise written to the point against a quotient
carried to two decimals invents a precision the promise never had. The exact
quotients are in the audit drawer.

One American Express series exists on this site because the company stopped
publishing the number. Its **average discount rate** — the price it charges
merchants — appears in the statistical tables every quarter from 2015 to the
Q4 2022 release and never again. Over the 24 quarters inside this page's window
it runs 2.43% to 2.34%. The obvious continuation is not published as one: the
company's footnote computes that rate on proprietary *and* network-partner
volume net of what a third-party acquirer retains, so it is not discount revenue
over billed business, and in the eight quarters where both exist the derived
ratio sits a steady 3.9–5.0bp below the printed one. Joining them would draw
that offset as a step at the quarter the disclosure ended. The derived ratio is
plotted separately and starts at 2021Q1, because in 2020 its numerator still
contains processed revenue while its denominator had already been recast to
proprietary-only — old numerator over new denominator reads as a price rise that
never happened, and no filed identity catches it.

Two further windows on that page are the length of the disclosure rather than a
choice. **VCE** — the company's own defined aggregate of Card Member rewards,
business development and Card Member services — runs 22 quarters, because
business development only left the combined `Marketing and business development`
line in the April 2022 release and only 2021 was recast. The **four current
segments** run 26 quarters, from the appendix in the October 2022 release that
recast them back to 2020Q1; before that the company reported a different
three-segment structure it never recast. And the whole page starts at 2017Q1
rather than earlier because ASC 606 restated 2017 in the company's own tables
and never restated 2016 — Q1 2017 discount revenue is 4,519 in the January 2018
release and 5,387 in the April 2018 one.

**Microsoft, Alphabet, Mastercard, Visa and Interactive Brokers get no such
record, and that is a

Philip Morris files the longest record here — every quarterly earnings 8-K
since the March 2008 spin-off carries a full-year EPS forecast, revised each
quarter, seventy-one vintages across eighteen years — and it is the only
company on this site that guides **the same earnings number at two horizons and
on two definitions**. From the 2020 second quarter the releases add a
next-quarter forecast, and in 2022–2023 the guided quarterly metric moved from
reported diluted EPS to adjusted diluted EPS. Four records fall out of that,
and they disagree.

On the reported basis the record is the only two-sided one on this site: across
sixteen years with a published range, the year landed **above the top seven
times, inside four, and below the bottom five**. On the adjusted basis — same
company, same release, same table — the next-quarter number has cleared the top
**twelve times out of twelve** and the full year has missed once in six.

The reason is written into the guidance rather than inferred, which is why the
page is worth building. Across the 56 releases from April 2008 to February
2022, 54 attached the same clause to the forecast: it excludes future
acquisitions, unanticipated asset impairment and exit-cost charges, and any
unusual event. (The two exceptions are 2008-10-22 and the April 2020
withdrawal, which published no annual forecast at all.) The number labelled GAAP was therefore never a forecast of GAAP;
it was a GAAP number conditional on nothing unusual happening, and each of the
five misses is a year in which something unusual happened. FY2024 is the clean
case — reported EPS of US$4.52 against a final guidance of US$6.20–6.26,
entirely a US$1.49 non-cash impairment of the deconsolidated Canadian affiliate
recognised as a subsequent event after that guidance was published. The
adjusted line for the same year cleared its range. This is the S&P Global
finding ("the number that never misses is the one the company defines") over a
record twice as long and at two horizons at once.

Four things in that record are marked rather than smoothed. FY2008 is excluded
outright: PMI spun off in March 2008 and guided that year on a pro-forma
*adjusted* basis against a pro-forma 2007 base, so scoring it against reported
EPS would be a basis error rather than a miss. FY2019 and the FY2020 opening
were published as a floor with no upper bound ("forecast to be at least
US$5.37"), so those years sit outside the band chart with a break marker —
drawing a floor as a zero-width range invents a ceiling the company never
published. On 2020-04-21 PMI **withdrew** the full-year forecast outright for
one quarter and replaced it with a quarterly one, the only withdrawal in the
record. And **the fourth quarter is never guided**: in twenty guided quarters
the only Q4 is 2020's, which was itself a point ("around US$1.16") rather than
a range, so the quarterly axis carries no Q4 between 2021 and 2025 and says so.

Two more basis hazards had to be handled. The guided quarterly metric changes
definition mid-record, and the 2022 second and third quarters were guided —
and reported — on a *pro forma* adjusted basis excluding Russia and Ukraine,
printed beside a group figure that differs. Each quarter is therefore scored
inside the basis that applied to it, with a structural-break marker where the
definition moves; a pro-forma guidance scored against the group actual sitting
next to it in the same release is the plausible-and-wrong version of that
chart. The same care applies to the currency decomposition: PMI prints its
full-year adjusted EPS guidance twice, in dollars and excluding currency, and
the two often move in opposite directions — FY2024's ex-currency midpoint rose
US$0.39 across the year while the dollar midpoint rose US$0.10, and FY2026's
ex-currency band is byte-identical across all three vintages published so far
while the dollar midpoint fell US$0.12. FY2022 is left out of that chart alone,
because its dollar row was the group and its ex-currency row the pro forma, so
subtracting one from the other would compare two companies.

One series on that page exists because the number is filed and the percentage
everyone quotes is not: **net revenues split between combustible and smoke-free
products, in dollars, from the 10-K segment note, FY2016 to FY2025**. The share
runs 2.7% to 41.5% over ten years, and the shape is the finding — combustible
revenue is 8% below where it started while smoke-free grew from US$733M to
US$16,854M. The transition is additive, not substitutional. Two disclosure
details travel with it rather than being cleaned away: the line was called
"reduced-risk products" before 2019, and FY2020 and FY2021 were restated in the
FY2022 10-K when Wellness and Healthcare moved into the smoke-free category.

Three things that page refuses. **ZYN's US retail value share** (about 57% this
quarter) reaches the earnings call and not the release, so it is named in the
excluded list rather than plotted — the same rule that keeps fifteen quarters
of webcast guidance off the Microsoft page. **Net debt to adjusted EBITDA** has
a company-defined denominator PMI publishes annually and not in a quarterly
filing, so the ratio cannot be recomputed; the company's own target is quoted
in words. And the ZYN retail-offtake series ends in a hole rather than a zero:
the company described the latest quarter as "flat to slightly growing" and gave
no percentage, and filling in a zero would turn a phrase into a number a model
could use.

The segment charts on that page are four quarters long and cannot be extended.
PMI replaced six geographic segments with three (International Smoke-Free,
International Combustibles, U.S.) effective 2026Q1 and did not restate the
history into a filing, so the only comparable prior-year quarters are the two
restated columns the 2026 releases print beside the current ones. The page
draws those four and declines to splice them onto the segments they replaced.

TJX files the longest *quarterly* record on this site and the most one-sided,
and it is the first page here whose company sells nothing to a data centre. Every quarterly
earnings 8-K EX-99.1 ends with an Outlook paragraph, and from Q1 FY2013 onward
that paragraph guides next-quarter diluted EPS in the same sentence structure —
**52 guided quarters, 49 of them finished**. Pretax profit margin joins the
paragraph in 2022 and consolidated comparable sales in 2023, so the three
records are 52, 17 and 15 quarters long and each chart is drawn over its own
rather than over the shortest one they share.

Unlike Synopsys, the three answers do not disagree. **Reported EPS cleared the
top of its guided range 38 times in 49, landed inside it 8 times and broke the
bottom 3 times; pretax margin cleared the top 15 times in 16; consolidated comp
never once landed below its floor.** The three misses are not one phenomenon:
Q1 2014 missed by half a cent after the split conversion, Q1 2020 was the
quarter the stores shut, and Q1 2022 was the 2022 cost shock. The single margin
miss is the most useful entry in the record, because the company names its own
cause in the same release — "below the Company's plan due to an unplanned shrink
charge", against guidance that had assumed shrink would be a 0.5-point
*tailwind*.

Two things stop that from being a tautology, and the page puts both on the
charts rather than in a footnote. TJX publishes each quarter's outlook with the
*previous* quarter's results, and it reports about three weeks after a quarter
ends, so the Outlook paragraph lands **9 to 24 days into the quarter it guides**
— a tenth to a quarter of the period already banked. And the company withdrew
guidance outright for **seven consecutive quarters** in 2020–2021, writing "is
not providing guidance at this time" in five straight releases; the axis jumps
from Q1 2020 to Q1 2022 with a break marker, because a record that silently
deletes the quarters a company refused to guide is measuring its own filter.

Three basis hazards had to be handled rather than smoothed. TJX split two-for-one
in November 2018, so every EPS figure stated before it is divided by two — an
exact conversion, not an estimate — and exactly one pair straddles the split:
Q3 2018, guided at US$1.18–1.20 before and reported at US$0.61 after, which
converts to US$0.59–0.60 against US$0.61 and is a beat rather than the 49% miss
the raw comparison shows. FY2018 and FY2024 were 53-week years with the extra
week in the fiscal fourth, and that quarter's guidance was itself given on the
14-week basis, so the page compares like with like and marks the week count.
And two quarters carry an adjusting item that did not exist when the range was
set — the FY2026 Q4 litigation settlement and the FY2027 Q2 tariff refunds — so
those two are scored on the company's own adjusted figures, which is also the
basis the company used to call them "well above the Company's plan".

One number the page refuses to publish is the one the local note leans on
hardest. The company's adjusted EPS of US$1.22 still contains a tariff cost
tailwind — the CFO attributed the margin gain "mostly due to tariff
favorability" — but "mostly" is the only quantification ever given. Turning it
into a figure means choosing a ratio, which is an assumption rather than
arithmetic, so the de-tariffed earnings go in the excluded list instead, exactly
as Ansys' quarterly revenue does on the Synopsys page.

NIKE is the sharpest case of the same limit, and its page is built out because
of what the company filed *instead*. Forty earnings releases from FY2017 Q1 to
FY2026 Q4 were read end to end and **not one carries an operating outlook** —
three carry a forward number of any kind, and those are a futures-order backlog,
a buyback programme's start date and a restructuring charge estimate. The
releases say so themselves: "Revised guidance will be provided on the conference
call." So the object nine of these pages are built on does not exist here.

What NIKE did file is longer-dated and, unusually on this site, **finished**.
Three times it wrote a set of multi-year financial goals into the MD&A of its
10-K — through fiscal 2020, through fiscal 2023, and through fiscal 2025 — and
every window has closed, so the filed record settles all fourteen of them.
**One was met.** The last vintage, set in July 2021, missed on all six, and two
of its six asked for numbers the company has not printed once in the thirteen
filed years: a gross margin in the high 40s against a record high of 46.2%, and
an EBIT margin in the high teens against a record high of 15.5%. A third goal
missed in the other direction — NIKE said it expected annual capital
expenditures of "approximately 3% of annual revenues" and spent an average of
1.51% over the four years, having been at 2.9% in the year before the sentence
was written.

The withdrawal is a census rather than an impression. The FY2022 10-K still
refers to "our long-term financial goals" without restating one; the four 10-Ks
since contain the phrases "financial goal" and "long-term financial" **zero
times**, while the ROIC and EBIT-margin calculation tables those goals were
struck on are still published every year. What disappeared is the target, not
the measurement. A new set is due at the investor day announced for
2026-11-16/17.

Two things stop that record from being read more harshly than it deserves, and
both are on the charts. NIKE states its goals in **words** — "high single-digit",
"high 40s", "low thirties" — so the numeric band on each row is the page's
reading, printed as such; where a verdict turns on that reading the page reports
it as undecided instead of picking. And "on average, per year, through fiscal N"
names no base year, which matters once: the fiscal-2023 EPS goal is met at
+22.5% from FY2018 and missed at +4.3% from FY2017, because FY2018's earnings
carry the Tax Act's one-off charge at a 55.3% effective rate. That one is
published as base-dependent rather than as a hit. The fiscal-2025 misses need no
such care — they run 4 to 11 percentage points wide.

The mechanism behind them is in the same filings, which is why the long section
is built around it rather than around a template. **NIKE Direct went from 20.3%
of NIKE Brand revenue in fiscal 2014 to 43.7% in fiscal 2023, and consolidated
gross margin never made a new high after fiscal 2016** — the year the direct
share was 25.8%. The channel mix moved exactly as the strategy promised; the
gross margin it was supposed to buy did not arrive, and the
selling-and-administrative ratio rose 3.2 points instead, almost entirely in
operating overhead rather than marketing. In fiscal 2026 the shift reverses:
NIKE Brand revenue grew 1% with wholesale up 6% and direct down 6%, and the
company's own gross-margin bridge credits lower warehousing and logistics costs
"primarily due to channel mix".

There is one more record, eight quarters long and closed eight years ago, and it
is the reason the page can say what NIKE's guidance behaved like rather than
only that it stopped. From FY2017 Q1 to FY2018 Q4 NIKE furnished the earnings
call's prepared remarks as a second Item 2.02 exhibit, and those carry real
guidance. Of 34 next-quarter items only 10 are ranges with endpoints — 19 are
words and 5 are single points — and of those 10, **two landed inside the range,
five broke the bottom and three broke the top**. Every other guidance record on
this site is one-sided, which is what lets those pages read the range as a floor
the company publishes rather than a forecast. NIKE's is the exception: it misses
in both directions, which is what an actual forecast looks like. Then, on
2018-07-03, the exhibit stopped; the next four quarterly releases attach a press
release and nothing else.

Two figures the page corrects rather than carries. The local note put the fiscal
fourth quarter's severance at about US$170M by reading the 10-Q's *three-month*
charge of US$230M as a year-to-date figure; the filed nine-month number is
US$304M against a year of US$385M, so the quarter carries **US$81M** — and its
expense-line split is US$104M into cost of sales against a US$23M *release* from
operating overhead. And the note flagged the US$686M tariff receivable as its
largest open item, with collection timing and impairment risk unknown; the
filed figure is US$684M, and the 10-K — published nine days after the note —
states that substantially all of it was received after the year end, with no
allowance recorded.

Ferrari is the first company here that files **no 10-Q, no 10-K and no 8-K**. It
is a Dutch-incorporated foreign private issuer reporting under IFRS in euro, so
its annual filing is a 20-F and every quarterly figure it has ever published
sits in the EX-99.1 of a results 6-K. The rendered-statement R-files the rest of
this site leans on cover 10-Q and 10-K schedules, which Ferrari does not file,
so the releases themselves are the entire source — and four of those accessions
list no exhibit at all in their `index.json`, so the release has to be cut out
of the complete submission text instead.

What that exhibit contains is unusually complete: a three-month column beside
the cumulative one in every release, shipments split four ways by region,
revenue split by category, the full EBITDA and EBIT reconciliations, capex,
industrial free cash flow and net industrial debt. So **42 consecutive quarters
back to 2016Q1** come out of the releases with no differencing anywhere — the
fourth quarter included, which on most pages here has to be derived.

**And the guidance record it files has a shape no other page here carries.** The
other guidance pages settle a range: did the reported number land inside it.
Ferrari's full-year outlook mostly is not a range at all — it is a one-sided
inequality. Across 31 vintages and five guided metrics, 69 readings are floors,
31 are points, 6 are ceilings, and only 49 are two-sided ranges.

The finding is what happens to that mix as a year runs. The opening, Q1 and Q2
vintages carry 15 to 17 ranges each. The Q3 vintage — the one that settles the
year, published in early November with about ten of twelve months already
banked — carries **one range out of 35**. Every other year-end vintage is a
floor, a point or a ceiling. In all five years where adjusted EBITDA opened as a
two-sided range (FY2019 through FY2023) it ended that same year as a point or a
floor, and from FY2024 the range is gone from the opening vintage too. **The
guidance sheds its upper bound exactly as the year becomes knowable**, which is
the opposite of a forecast narrowing onto an answer. That is why the page does
not lead on a hit rate: against a floor, "never missed" is close to a tautology.
What it plots instead is the distance above the floor, and the deviation of each
finished year from *every* one of its four vintages, which shows the funnel
closing from 11.3% average absolute error at the opening vintage to 3.4% at the
last. Industrial free cash flow is the loosest of the five: even at the final
vintage it sits 11.7% from the answer on average, and it has cleared its own
number in all seven finished years.

Three hazards on that page are handled rather than smoothed, and the first is
the reason the year-sum test exists at all:

- **The period columns swap sides.** Ferrari's 2016–2018 second- and
  third-quarter releases print the cumulative block *left* of the row label and
  the three-month block right of it; from 2019 the two are reversed. Reading a
  fixed side puts half-year and nine-month figures into three years of quarterly
  slots — and every within-quarter identity still closes while that is true,
  because all the components go cumulative together. Only *four quarters must
  sum to the filed year* catches it; that check now runs over 10 fiscal years
  and 7 metrics and passes 70 of 70.
- **The guidance column moves.** The outlook table puts the current-year
  guidance in the last column in every release from 2018 to 2025 and in the
  **first** column from 2026. A fixed position would have published the
  prior-year actual, €7.15B, as the FY2026 revenue guidance. The page reads the
  header row.
- **A point guidance is settled at its printed precision.** FY2019 adjusted
  EBITDA came in at €1.269B against a guided `~1.27`, three million euro under a
  number the company printed to two decimals. That is recorded as landing *on*
  the guidance, not below it — scoring it as a miss would apply a threshold
  finer than the disclosure it is measured against, the same reason Mastercard's
  currency-neutral threshold was retired.

Two things the page refuses. **Personalisation as a share of Cars and spare
parts revenue** is the number the local note leans on hardest and the one the
company has never filed: it appears only as "over 20%" on earnings calls, never
in a release. **Model-level shipments and ASP** are refused by the company as a
matter of policy — asked directly, the CEO said Ferrari wants "to leave some
blur". Both are named in the excluded list rather than estimated, and the page's
own revenue-per-unit series is labelled as what it is: Cars and spare parts
revenue over total shipments, which includes parts and personalisation in the
numerator and only whole cars in the denominator, and is therefore not an ASP.

One series on that page exists because the number that decides the quarter is
not one any filing prints as such: **the quarterly depreciation and amortisation
line against the run-rate the full-year guidance implies.** Ferrari's latest
quarter set a record EBIT margin of 31.2% while its EBITDA margin *fell*, and
the entire gap between those two facts is D&A, which at €150M is the lowest
reading in eight quarters. Subtracting the half-year actual from the "more than
€700M" the company put on the year gives an implied second-half average of
€188M — within a million of what the company actually booked two quarters
earlier. So the record margin sits below the depreciation line, and the page
draws both legs rather than reporting the record.

**Microsoft, Alphabet, Mastercard and Visa get no such record, and that is a
sourcing limit rather than an editorial choice.** Microsoft's own 8-K says in as
many words that guidance is given on the earnings call and webcast, so nothing in
its filings can carry a range; the quarterly outlook block on its page comes from
the call, one quarter at a time. Alphabet gives no quarterly numeric guidance at
all — its capital-expenditure commitment for the year reaches a press release
only when it changes, twice in forty-five releases. Mastercard's earnings 8-K
contains no Outlook block at all: the words `outlook`, `guidance` and
`we expect` do not appear in it, and what the call gives is "high end of low
double-digit", which has no floor and no ceiling to clear. Interactive Brokers is
the plainest case of all: there is no outlook block, no range and no forward
number of any kind in any of its earnings 8-Ks, so the record is not thin — it is
absent. None of the five pages
gets a fabricated record: transcribing fifteen quarters off webcast material that
cannot be checked against a second source is the failure this repo is built to
avoid.

Visa is the sharpest version of the same limit, because the thing it withholds
is not the number but the *unit*. It has never filed a numeric **quarterly**
outlook at all: every Financial Outlook it ever published was fiscal-full-year,
so the object the other five pages are built on — a next-quarter range and the
quarter that settles it — does not exist anywhere in its filing history. Even
the full-year outlook is leaving, in four visible steps: numeric on some metrics
through fiscal 2020, present but explicitly withheld in fiscal 2020–2021, absent
from most of 2022–2023, reduced in fiscal 2024 to a single sentence pointing at
an earnings presentation that is **not archived on EDGAR**, and gone entirely
from every release after 2025-01-30. The page prints that era map and
deliberately prints no tally of how many releases carried a number: a count
sampled from eighteen of a forty-plus release window does not generalise, and a
precise-looking ratio would be the least defensible sentence on the page.

What Visa did guide, repeatedly and numerically, turns out to be the one number
its page is actually about. `Client incentives as a percent of gross revenues`
appears as a range in the release that opens each fiscal year from 2017 to 2020.
Both legs are filed — the range from the release, the delivered rate from that
year's 10-K revenue note — and the record is one-sided in the *helpful*
direction: three of the four years came in **below** the guided floor and none
ever exceeded the ceiling, meaning Visa handed back less of its gross revenue
than it had told the market it would. Then it stopped publishing the number, and
in the six years since, the rate has gone from 23.4% to 28.7%.

That rate is a filed figure every quarter back to 2012, because the four gross
revenue lines and the client-incentive contra line are disclosed separately, so
the ratio is division on disclosed numbers rather than an estimate — and the
five reconcile to filed net revenue in all fifty-five quarters, fiscal fourths
included. Over that window it climbs from 16.3% to 28.7%. Eight quarters cannot
see it: across the last eight the line just oscillates between 27% and 29% and
reads as noise. It is the clearest case on this site of a series whose meaning
is entirely a function of its window.

Two Visa hazards are handled rather than smoothed over, and both are places
where the obvious arithmetic gives the wrong answer:

- **Service revenue is recognised on the previous quarter's payments volume**,
  which Visa states in every release, while that same release's headline
  `Key Business Drivers` table prints the *current* quarter's volume. Lining the
  two up is off by exactly one quarter, every quarter. Worse, Visa discloses
  volume only as a year-over-year **percentage** and never as a quarterly dollar
  amount, so a unit take-rate cannot be recomputed from the filings at all. The
  page therefore publishes **no** revenue-versus-volume comparison and says why,
  rather than reproducing a misaligned one.
- **The litigation escrow is measured against the accrual it actually funds.**
  The U.S. Retrospective Responsibility Plan escrow pays U.S. covered litigation
  and nothing else; the balance sheet's `Accrued litigation` line is larger
  because it also carries VE Territory and uncovered matters the escrow cannot
  touch. Visa prints the split itself, in a table whose title says so. Against
  the covered accrual the latest quarter is a US$66M **surplus** — US$888M
  against US$822M. Against the total it looks like a US$386M shortfall, which is
  what the local note read it as and what produced a forecast of an imminent
  large top-up. Both lines are on the chart and the page names which pair
  belongs together.

**Mastercard's page answers the same question with a different quantity, and
that is the reason it was worth building.** The interesting thing about a
payment network is not whether it beats a range it never published; it is how
much of what it bills it actually keeps. So the first two sections carry
eighteen quarters of the rebate share of gross billings, and the answer has the
same one-sided shape the guidance records have: **the ratio rose from 44.5% to
52.4%, and in the fourteen comparable year-over-year readings it went up
thirteen times — the single exception is 0.31pp.** A ratio that has essentially
never come back is a structure, not a quarter.

That number is not printed anywhere. Under the presentation Mastercard adopted
in the first quarter of 2023, the four assessment lines are printed gross and
the payment network is printed net, so the rebate is the difference of two filed
figures. What licenses the series is that the company publishes the *growth
rate* of the line it does not print: it says rebates rose 22% in the quarter and
22% in the six months, and the subtraction gives 21.8% and 22.5%. A test pins
both.

Having the gross and the net side by side is what makes the page's own
decomposition possible, and it is an identity rather than an estimate: net
revenue = gross assessments − rebates + value-added services, so each quarter's
year-over-year change splits exactly three ways. It reframes the quarter. The
gross leg grew from US$944M to US$1,580M over fourteen quarters — and the part
that reached net payment-network revenue has sat in a US$506–570M band for seven
straight quarters. Everything extra the company billed was handed back. More
than half of the net revenue increase now comes from the value-added services
leg, which carries no rebate at all.

The page also refuses one thing the local note leans on. The month-by-month
cross-border split — travel against card-not-present — exists only in the
quarterly earnings presentation and reaches no filing, so no history is built
for it; the filings give total cross-border volume, gross dollar volume and
switched transactions, and the page plots those three instead and says which
question they cannot answer. One threshold from the previous quarter is reported
as **unsettleable rather than passed or failed**: it was written as "a
currency-neutral revenue growth of +11–12% triggers a downgrade", and Mastercard
publishes currency-neutral growth only to the whole percentage point. The
published figure was exactly +12%, sitting on the boundary, so the same number
reads as both outcomes. The threshold had a finer resolution than the disclosure
and has been retired.

**Interactive Brokers is the first page here whose subject is a price the
company does not set.** Its quarter reads as an unambiguous record — accounts up
34% to 5.19 million, customer equity up 40% to US$930.3B, DARTs up 36% — and the
page's headline is that none of that is the reason revenue hit a record. Over
the same year the net interest margin fell from 2.07% to 1.93% and all three
annualised yields the company publishes fell with it: margin loans 4.67% → 4.10%,
segregated cash 3.86% → 3.32%, the rate paid on customer credits 2.64% → 2.23%.
More than half of total net revenues is net interest rather than commissions, so
the volume story and the price story pull in opposite directions and only one of
them is management's to control.

Thirty quarters are what make that legible, and the window was chosen to cover
one full rate cycle rather than to look long. Inside it the two revenue lines
cross **twice**: zero rates pushed net interest below commissions in Q1 2020 and
kept it there for nine quarters, and the hiking cycle pushed it back on top in
Q2 2022. The net interest margin bottomed at 0.94% in Q3 2020 and peaked at 2.46%
in Q3 2023, and for three quarters of 2021 the yield on segregated customer cash
was **negative** — the company was paying to hold it. Average interest-earning
assets grew 3.7x across the same window, dipping in only two quarters of the
thirty. Eight quarters of
any of this would show a trend that is really a position in a cycle.

Two things on that page are structural rather than analytical, and both are
marked rather than smoothed. The company **renamed its per-order commission
metric** at Q1 2020, from "Commission per DART" to "Commission per Cleared
Commissionable Order"; the two never appear in the same release, so there is no
overlap quarter to splice on and the series starts there instead of being
carried back. And the **4-for-1 split** declared 2025-04-15 restated only those
quarters that later served as a comparative, so the per-share figures on the
public interface are two bases spliced together — which is why this page
publishes net income available for common stockholders in dollars and **no
multi-quarter EPS line at all**. A test asserts that no exhibit anywhere plots a
per-share series, because the failure mode is someone adding one later and it
drawing a step that reads as a business event.

One correction the data forced during the build is worth recording, because the
plausible version was wrong in both directions. Per-account equity looks like a
dilution story — accounts grew 8.3x while the average account shrank 24% — and
the first draft of that chart said the dilution had not yet begun. It had: the
average fell from US$268,966 in Q4 2020 to US$142,694 in Q3 2022. But it has
since recovered 25.7% while accounts more than doubled again, so the honest
reading is that the dilution happened, ended three years ago, and has not
resumed. The same pass caught a caption calling the per-order commission "stable"
when it has run from US$3.30 to US$2.31 to US$3.19 and back to US$2.64 — a
US$0.55 slide from its Q4 2023 high across ten quarters, and no net rise over the
twenty-six the series holds. The commission line grows on order count while the
realised fee per order falls, not with it.

Costco is the only company here whose filed guidance is about **capital rather
than profit**, and that gives its record a shape none of the others have. Its
earnings 8-K carries no outlook block at all — across twelve consecutive
releases the words `outlook`, `guidance` and `we expect` appear only inside the
forward-looking-statements legend. What it does file, in the `Capital
Expenditure Plans` paragraph of every 10-K and again in every 10-Q, is next
year's capital expenditure as a dollar range, plus a warehouse-opening plan and
— since 2024-05-30, in the EX-99.2 supplemental deck — a fiscal-year-end
warehouse count revised every quarter.

Against the plan as first published, twelve settled years land **five above the
range, two inside it and five below**. Every other guidance record here behaves
like a floor — Cadence's revenue never missed in 42 quarters, Meta's never in
18, S&P Global's adjusted earnings per share never in seven years — and this one
does not. But that is **not a like-for-like comparison and the page says so**:
the other records are forecasts of revenue, profit or earnings per share, made
to the market; this one is a budget the company writes for itself. Underspending
it is not a failure and overspending it is not a beat, so nothing pushes it
toward a number that will be cleared. The symmetry is a fact about what kind of
promise a capital plan is, not about how well Costco forecasts.

Three things qualify the tally, and all three are on the chart rather than in a
footnote. **It holds only for the opening vintage.** The plan is restated in
every 10-Q, and scored against each year's final 10-Q the same thirteen settled
years land six above, four inside and three below — leaning one way. **The
revision buys less than it looks like**: mean absolute error falls only from
9.1% to 5.5%, where Moody's and S&P Global, guiding a year the same way, close
their funnels to about a fifth or a seventh. A company that rewrites its number
four times a year and still lands 5% from the last version is revising the
number, not the uncertainty. And **twelve of the thirteen numeric ranges are
printed "approximately $X to $Y"**; two of the five overshoots clear the top by
under 5%, which is inside what that word plausibly covers, while the other three
are 8–12% over.

The regime does shift, but not cleanly, and the page had to be corrected on this
before it shipped. Before fiscal 2021 the eight settled years are five below,
two above and one inside; from fiscal 2021 they are three above and one inside
with nothing below. So it is not "underspent every year, then overspent every
year" — fiscal 2013 and fiscal 2018 are overshoots inside the early stretch.
What actually changed is that falling below the floor stopped happening.

The three records also disagree with each other in a way that is the page's
point rather than a loose end. The *store count* Costco estimates every quarter
in its supplemental deck has landed **exactly** on the final estimate in both
settled fiscal years; the *dollars* those stores cost miss by 5% to 15% every
year. It can tell you how many warehouses it will have and not what they will
cost.

Two things there are marked rather than smoothed. The 10-K is filed in early
October and the fiscal year begins in early September, so the plan goes out 37
to 53 days into the year it guides — the caveat Cadence and Broadcom carry, on
an annual horizon. And the fiscal 2024 10-K guides fiscal 2025 as "a similar
amount", with no number; that year is drawn with no band rather than an invented
one, and it is the year capital expenditure rose 16.7%.

The opening plan is the one record on this site that gets a chart and **no hit
rate**, because the sentence is not one object. Its qualifier moves four times
across the window — a range, then "up to", then "approximately", then
"approximately up to", then "up to" again — and the relocation clause flips
between naming relocations as part of the plan and as an addition to it. The
page plots the quantity (planned openings against actual openings, with the plan
restated as N + M in the years relocations are additional) and says in as many
words that a point estimate not reached and a ceiling not touched are not the
same event. The two earliest guided years are dropped outright: their plan is a
range rather than a number and their opening count is stated once as net-new and
once as gross-new.

Costco's quarters also do not line up with the calendar and cannot be made to.
Its fiscal year ends on the Sunday nearest 31 August, its first three quarters
are twelve weeks and its fourth is sixteen (seventeen in a 53-week year), so the
site's usual rule — label a fiscal quarter by the calendar quarter it mostly
covers — is **not one-to-one here**: fiscal 2026 Q2 and fiscal 2026 Q3 both have
more days in calendar Q1 2026. The page labels by the calendar quarter each
period *ends* in, which is monotone, and says so. Two consequences travel with
every chart: on an eight-quarter axis two bars cover a third more trading than
the other six, and one of them, Q3 2024, compares sixteen weeks against the
seventeen of the 53-week fiscal 2023 — its year-over-year figures are short by
roughly a week and are marked where they appear.

And Costco publishes its comparable sales **twice, at two precisions**: to one
decimal in the earnings release, rounded to whole percentages in the 10-Q. The
local note's central claim — that the ex-gasoline, ex-currency comp is a flat
line at about 6.5% — exists only at the finer one. In the filings the same three
quarters read 6%, 7%, 7%, which looks like acceleration. The page plots the
release series, carries the 10-Q series in the audit drawer, and says which is
which. Its adjusted comparable-sales record starts at fiscal 2020 Q1 for a
different reason: for the four quarters of fiscal 2019 the column labelled
"Adjusted" also strips an ASC 606 accounting change, so it is a second
definition wearing the first one's label.

One more thing the page refuses. Costco is the only company here that publishes
a sales figure **between** earnings dates — a comparable-sales reading for every
four- or five-week retail month. Only some of those reach EDGAR: about forty
8-Ks carry a retail month, overwhelmingly February, bundled into the
second-quarter earnings release. That is a sparse annual point rather than a
monthly series, and the site's cadence is quarterly either way, so none of it is
carried. The same bundling is a parser trap the build had to handle: every
second-quarter release prints *two* comparable-sales tables with identical row
labels, one for the twelve-week quarter and one for the February retail month.

Thirteen of the series exist only on this site, because the number that decides the
quarter is not one any filing prints:

- NIKE's **direct-to-consumer share of NIKE Brand revenue**, plotted against the
  gross margin over the same thirteen years. Both legs are filed — the numerator
  and denominator sit in one MD&A table and the margin in another — and the
  division is the whole argument: the share rose 23 points and the margin ended
  below where it started. NIKE publishes the two tables on facing pages and
  never the ratio.
- NIKE's **fiscal-fourth-quarter severance by expense line**, which exists only
  as the year in the 10-K minus the nine months in the 10-Q: US$81M in total,
  US$104M of it in cost of sales against a US$23M release from operating
  overhead. The company discloses the two endpoints and not the difference, and
  the difference is what moves the quarter's gross margin.

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
- Mastercard's **payment network rebates and incentives**, above, and the
  **share of gross billings** it represents. The company nets the line away
  before printing anything, so the eighteen-quarter record is a subtraction the
  company's own published growth rate has to agree with.
- Mastercard's **implied repurchase price**, quarter by quarter: the cash it
  spent divided by the shares it bought, both filed. It fell to US$500 in the
  quarter it spent more than in any other quarter this page holds, and the
  shares are disclosed to
  0.1 million, so the chart carries the ±US$5 band the subtraction leaves rather
  than a point estimate.
- Interactive Brokers' **share of consolidated net income that never reaches its
  listed shareholders**. Under the Up-C structure the public company holds only a
  minority of the operating LLC, so most of the reported profit is booked to the
  noncontrolling holder: US$1,026M of this quarter's US$1,338M, leaving US$312M.
  The company prints both figures but never the ratio, and the ratio is the whole
  point — it has fallen from 84.9% to 76.7% across thirty quarters as the listed
  entity buys units back, which is 8.2pp in seven and a half years. On that
  gradient the wedge is not a rounding item that will close; it is the structure.

- Costco's **two legs of the operating margin**. Operating income over net sales
  splits exactly into a merchandising leg (gross margin less SG&A less
  preopening) and a membership leg (fees over net sales), and the identity
  closes in all thirteen years. In fiscal 2013 the two were 0.75pp and 2.22pp —
  the company that "makes its money on membership fees" made three quarters of
  its operating profit that way. In fiscal 2025 they are 1.87pp and 1.97pp,
  0.10pp apart, and membership's share of operating income has fallen from 74.9%
  to 51.3%. Neither leg is a figure any filing prints, and the fee was raised
  twice inside the window.
- Costco's **four-leg decomposition of earnings-per-share growth**. Earnings per
  share is (operating income + other income) × (1 − tax rate) ÷ diluted shares,
  so the year-over-year ratio factors exactly into an operating leg, a
  below-the-line leg, a tax leg and a share-count leg with no estimate anywhere.
  The latest quarter's +15.3% is +11.3% operating and the rest interest income
  on an US$19.0B cash balance plus a lower tax rate. The record starts where the
  noncontrolling-interest line goes to nil, because before that a fifth leg
  would be needed and the two halves would not be one basis.
- Costco's **gasoline-and-currency gap in comparable sales** — reported comp
  minus the company's own ex-gasoline, ex-currency comp. Both legs are filed to
  one decimal; the difference is not, and the company never splits the two
  causes apart. Over 27 quarters the gap has been *negative* in 15, so gasoline
  and currency have suppressed the headline more often than flattered it, and it
  swung from −0.7pp to +3.2pp in four quarters. The local note read this
  quarter's tailwind as a risk still to come; the record says the tailwind is
  the unusual state.

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

**Carrying the table and being a column in it are separate things, and the
design already separated them.** Cadence, Synopsys, TSMC and NVIDIA all publish
the cross-reference without appearing in `_CASH_CAPEX_SOURCES`, and
`test_cdns_is_not_in_the_cross_page_capex_table` pins exactly that. So the block
is a standing site-wide reference — its title says `跨页对照` and it renders
inside the collapsed audit drawer, not in the chart flow — rather than a claim
that the page's company is in the AI supply chain. Visa, Mastercard, TJX, NIKE
and Costco carry it on the same terms. What TJX adds is a note saying so: the first pages
outside the chain shipped the block with no explanation, and a reader who meets
a foundry table in an off-price retailer's drawer deserves one sentence telling
them it is a site-wide reference.

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
