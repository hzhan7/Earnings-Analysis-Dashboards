# Earnings Analysis Dashboards

Static GitHub Pages dashboards for presenting quarterly earnings as concise,
chart-led research pages. Reviewed pages currently cover Alphabet, Amazon,
Broadcom, Cadence, Charles Schwab, Interactive Brokers, Mastercard, Meta,
Microsoft, Moody's, NVIDIA, S&P Global, Synopsys, TSMC and Visa.

## Build

```bash
python3 build/all.py
python3 -m http.server 8765
```

Open `http://127.0.0.1:8765/`, then choose:

- `http://127.0.0.1:8765/amzn/`
- `http://127.0.0.1:8765/avgo/`
- `http://127.0.0.1:8765/cdns/`
- `http://127.0.0.1:8765/googl/`
- `http://127.0.0.1:8765/ibkr/`
- `http://127.0.0.1:8765/ma/`
- `http://127.0.0.1:8765/mco/`
- `http://127.0.0.1:8765/meta/`
- `http://127.0.0.1:8765/msft/`
- `http://127.0.0.1:8765/nvda/`
- `http://127.0.0.1:8765/snps/`
- `http://127.0.0.1:8765/spgi/`
- `http://127.0.0.1:8765/tsm/`
- `http://127.0.0.1:8765/v/`

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
  which the company calls FY2026 Q3; Broadcom's ends in early November, so its
  `Q1 2026` is the quarter ended 2026-05-03, which the company calls FY2026 Q2;
  Visa's ends in September, so its `Q2 2026`
  is the quarter ended 2026-06-30, which the company also calls FY2026 Q3. Each
  page says so in its subtitle and notes. Without one convention the
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
   closed.

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

Amazon's, Broadcom's, Cadence's, Synopsys', TSMC's, NVIDIA's and Meta's first
sections are built out further than the others, because those seven companies
put a quarterly number in a filing. Eight quarters cannot say whether clearing
a range is normal for a company; the full record can. Broadcom is the one of
the seven whose filed number is usually **not** a range, which turns out to be
the point of its page rather than a caveat on it.

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

S&P Global files the only **annual** guidance record on this site, and it
produces the sharpest two-sided answer of any of them. It has never published a
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

**Microsoft, Alphabet, Mastercard, Visa and Interactive Brokers get no such
record, and that is a
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

Eight of the series exist only on this site, because the number that decides the
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
