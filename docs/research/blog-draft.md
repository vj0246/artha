# I measured how much of my backtest was a lie

*Blog draft (plan v2 P6 deliverable). Working title options: the above, or
"Survivorship bias in Indian equities: +2.5% a year of imaginary alpha".*

Every personal quant project starts the same way: download prices for the
current NIFTY 500, compute momentum, marvel at the equity curve. I wanted
to know exactly how much of that curve is an artifact of the download.

So I built the dataset the hard way. NSE publishes a daily "bhavcopy" —
every security that traded that day, including the ones that later died.
Sixteen years of those files (plus the corporate-actions feed, the
symbol-change history, and 1.48 million exchange announcements) give you a
panel with no survivorship: 3,623 names, of which 816 no longer trade.

Then I ran the same momentum strategy twice.

| Universe | Net CAGR | Net Sharpe |
|---|---|---|
| Honest (point-in-time) | 23.6% | 0.96 |
| Survivor-only | 26.1% | 1.04 |

**+2.5 percentage points a year, compounding, from names that quietly
stopped existing.** Over 14 years that is ~40% extra terminal wealth that
was never available to anyone.

Three other things the honest dataset taught me:

**1. The exchange never adjusts its own prices.** Everyone assumes the
bhavcopy's previous-close column is corporate-action adjusted. It is not —
not in the old format, not in the new one. I verified this on Infosys'
2015 bonus, Wipro's 2017 bonus, and Reliance's 2024 bonus, then built
adjustment from the declared CA feed instead. (Bonus find: Yahoo Finance
never adjusted Wipro's 2013 demerger. Their series is ~9% wrong before it.)

**2. Machine learning bought me turnover, not alpha.** Ridge, LightGBM, an
MLP and a small transformer, all under purged walk-forward CV with an
embargo, every experiment logged in a trial ledger. Every model had
statistically real predictive power (IC t-stats above 6.5). None beat
plain momentum after Indian delivery costs, because the ML signal lives in
fast reversal patterns that cost 4%+ a year to trade. The probability of
backtest overfitting across my model configs: 0.86.

**3. Post-earnings drift is backwards in India.** The famous US result
says prices drift in the direction of an earnings surprise for weeks. On
28,270 Indian earnings events, the top surprise quintile REVERSES -213bps
over the next quarter (t = -6.9). If you replicate US papers on Indian
data without checking, you trade the wrong direction.

The strategy that survived everything is almost embarrassingly simple:
12-month momentum, 25 names, weekly, with position caps, no-trade bands
and volatility targeting. Net Sharpe 0.97 at 13.5% vol with half the
drawdown of the raw signal — and a deflated Sharpe of 0.64 against my own
trial count, which is below the 95% bar, and I say so in the report.

The infrastructure is the alpha. The repo, the ADRs recording every wrong
assumption, and the full research report are here: [repo link].
