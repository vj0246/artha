# Artha: A Survivorship-Free Cross-Sectional Study of NSE Cash Equities

**Data construction, model comparison, event alpha, and a cost-aware
portfolio — with Lopez de Prado-grade validation throughout.**

VJ · 2026-07-18 · Track A final report (plan v2 P6). Every number below is
reproducible from the repo's scripts against the immutable raw zone; every
experiment is a trial in `reports/ledger.jsonl`.

---

## 1. Summary

We build a point-in-time, survivorship-free daily panel for NSE cash
equities from primary exchange sources (2010-2026, 7.1M rows, 3,623
instruments including every delisting), and use it to answer three
questions honestly:

1. **Do ML models beat simple factors net of Indian costs?** No. Four
   model families under one purged protocol; the in-sample winner is
   overfit 86% of the time (PBO), and none beats plain momentum or low-vol
   net. Ridge is the best ML model precisely because it stays closest to
   the slow factors.
2. **Do exchange announcements carry incremental alpha?** No, at weekly
   horizon — a published null with a twist: post-earnings drift is
   INVERTED in India (large surprises mean-revert, t = -6.9).
3. **What survives construction into a shippable strategy?** Momentum
   12-1 under caps, no-trade bands, and volatility targeting: net Sharpe
   0.97 at 13.5% vol with half the naive drawdown, capacity flat to
   ~Rs 25Cr.

Measured throughout: survivorship bias alone inflates this strategy's
CAGR by **+2.5pp/year** (Sharpe +0.09) — the gap between our panel and a
survivor-only dataset of the kind most personal projects use.

## 2. Data layer (P1)

- **Sources**: daily NSE bhavcopy archives (both formats across the 2024
  UDiFF cutover, one parser interface), declared corporate-actions API
  (2010+), symbol-change file, daily index closes, constituent snapshots,
  1.48M corporate announcements with exchange receipt timestamps, 157k
  board meetings. Raw zone immutable with sha256 manifest (~9,900 files).
- **Findings that shaped the design** (each an ADR):
  - bhavcopy PREVCLOSE is never CA-adjusted, in either format — adjustment
    factors must come from the declared CA feed (bonus/split ratios parsed;
    demergers/rights use the observed ex-date gap, dates gated by the feed).
  - NSE holds weekend special sessions; skipping them creates phantom
    events. 4,097 sessions ingested including 21 weekend ones.
  - No scriptable historical NIFTY 500 membership exists; the investable
    universe is defined by PIT liquidity filters instead (top-500 by 63d
    median traded value, price and age floors) — survivorship-free by
    construction because the bhavcopy lists everything that traded.
- **Verification**: 19-name spot-check vs snapshotted Yahoo references
  (108 price samples within 2.5%; one genuine Yahoo error found — the
  2013 WIPRO demerger it never adjusted), zero structural QA errors,
  every check a permanent regression test.

## 3. Validation protocol (used by every result below)

Purged expanding walk-forward (3y minimum train, ~quarterly test blocks,
horizon + 4-week embargo), CPCV (8 choose 2) for PBO, deflated Sharpe
against the full trial ledger, T+1-close execution with a lookahead suite
in CI (a planted-jump test that fails if any pre-execution return is
captured — it caught one real ordering bug during development). Costs:
STT/stamp/exchange/GST + flat DP charge + sqrt impact, ~0.22% round trip
before slippage.

## 4. Baselines and the model study (P2-P3)

Net of full costs, 2012-2026, top-25 weekly:

| Strategy / model | OOS IC | Net Sharpe | Net CAGR | Turnover | DSR |
|---|---|---|---|---|---|
| Momentum 12-1 | — | 0.96 | 23.6% | 8.9x | — |
| Low-vol 63d | — | 1.08 | 12.3% | 7.4x | — |
| 5d reversal | — | 0.17 (0.72 gross) | 1.1% | 47x | — |
| Ridge | 0.043 | 0.84 | 15.5% | 18x | 0.998 |
| Transformer (GPU) | 0.041 | 0.89 | 16.0% | 30x | 0.84 |
| MLP | 0.025 | 0.50 | 8.7% | 39x | 0.46 |
| LightGBM | 0.025 | 0.27 | 3.8% | 39x | 0.52 |

**PBO = 0.86**: LightGBM's in-sample IC of 0.36 collapses to 0.03 out of
sample; the best-IS config lands bottom-half OOS in 24/28 CPCV
combinations. The models' IC is real (t > 6.5 everywhere) but concentrates
in fast reversal-like patterns whose turnover Indian delivery costs
destroy. Complexity bought churn, not alpha — consistent with Gu-Kelly-Xiu
on price-only features, now shown for India with costs attached.

## 5. Event alpha (P4): a published null and an inverted PEAD

355k in-universe announcements classified (deterministic taxonomy, 81%
audited accuracy; guardrailed LLM upgrade implemented and key-gated).
Market-model event studies vs a synthetic NIFTY 50 TR index:

- Every major category shows a significant day-0/1 reaction followed by a
  FADE (order wins +65bps then -306bps over the quarter; M&A +14 then
  -106).
- **PEAD is inverted**: top-quintile day-0 surprises (+555bps) reverse
  -213bps over days 2-60 (t = -6.9). Indian large/mid caps mean-revert
  after announcement shocks — opposite to the classic US drift.
- Model A (price) vs Model B (price+events), same folds and ledger: event
  features SUBTRACT value (delta Sharpe -0.05 ridge, -0.20 transformer);
  events-only models carry no signal (IC t < 1) and are not subsumed by
  momentum/reversal — there is simply nothing weekly-tradeable in this
  aggregation. The 15:30 knowability rule matters: 58.5% of announcements
  arrive after the close.

## 6. The shipped strategy (P5)

Momentum 12-1 through construction: position cap 6%, sector cap 25%,
25% no-trade bands, 2% ADV participation, 13.5% vol target on unscaled
book vol (max of 21d/63d estimates), long-only, cash remainder.

| | Constructed | Naive momentum | NIFTY 500 syn-TRI | EW universe |
|---|---|---|---|---|
| CAGR | 12.9% | 23.6% | 14.4% | 15.7% |
| Vol | **13.5%** | 25.6% | 16.0% | 19.7% |
| Sharpe | 0.97 | 0.96 | 0.95 | 0.78 |
| MaxDD | **-27%** | -49% | -38% | -57% |

Zero constraint violations across ~720 rebalances (verified per
rebalance); regimes all positive (0.60 / 0.66 / 1.23); beta 0.59 with
4.0% annualized alpha (t = 1.55); VaR95 1.4%, worst 21d window -19.9%
(March 2020); every position liquidates intraday at Rs 25L; **capacity:
Sharpe flat to Rs 25Cr**, 0.92 at Rs 100Cr.

## 7. Survivorship: the measured punchline

Same naive strategy, same signal, two universes: the PIT panel vs only
names still trading at the panel's end (what a current-constituents
download gives you). 816 of 3,546 names (23%) vanish — mostly delisted
losers.

| Universe | Net CAGR | Net Sharpe |
|---|---|---|
| Point-in-time (honest) | 23.6% | 0.96 |
| Survivor-only (biased) | 26.1% | 1.04 |
| **Bias** | **+2.5pp/yr** | **+0.09** |

Compounded over 14 years, the biased backtest reports ~40% more terminal
wealth that never existed.

## 8. Publication bar (plan section 10) — addressed honestly

- OOS net edge vs best simple baseline: the shipped strategy IS the best
  simple baseline under construction; the ML challengers failed it. MET
  by shipping the factor and saying so.
- PBO < 0.5: 0.86 for the ML config set — that finding is a result, not a
  failure of the shipped strategy (which was not selected via that set).
  REPORTED.
- DSR > 0 at 95%: constructed momentum's DSR is 0.64 against a 20-trial
  ledger with a conservative variance prior. **NOT MET** at 95%. The
  strategy's Sharpe is economically strong but, deflated for search, we
  cannot claim statistical certainty — so we do not.

Verdict: mixed, published as such. The defensible claims are the data
layer, the validation machinery, the measured survivorship bias, the
inverted-PEAD finding, and a cost-aware construction that halves drawdown
at constant Sharpe.

## 9. Limitations and forward work

Static current-sector map; synthetic TRI benchmark (price + trailing
yield/252); cash modeled at 0% (liquid-fund yield would add ~1.5-2pp);
rights/special dividends unadjusted (QA-flagged); rule-based taxonomy at
81% (LLM upgrade one env var away); cost rates on the verify-list until
confirmed against current schedules; daily-horizon event reversal (the
t = -6.9 fade) is the most promising unexplored trial. Track B adds the
event-driven engine, backtest/live parity in CI, and the Zerodha paper leg
with realized-vs-modeled slippage.

---

*Methods and per-phase evidence: docs/research/p1-audit.md through
p5-portfolio-validation.md. Decision history: docs/decisions/. Trial
count at publication: 22.*

---

# Part II: Production, Construction v2, and the Single-Name Laboratory

Addendum, 2026-07-20 (Tracks B-E; each section has a full note in
docs/research/ and every configuration is a ledger trial).

## 7. From research to unattended operation (Track B)

The validated strategy runs live-paper daily: an idempotent 19:00 cycle
(incremental backfill -> curated rebuild -> integrity scan -> signal
health -> paper trading -> reconcile -> alert) with deterministic order
ids, kill-switch + enforced drawdown rails (-10% halves gross, -15%
freezes), backtest/live parity as a CI gate, and a quantified go/no-go
(PSR, minimum track record length, Kupiec VaR test, capital sizing).
Sizing result worth stating: flat DP charges and integer shares make
Rs 1L structurally unviable (38 bps per exit); minimum viable capital
is Rs 2L, comfortable at Rs 5L. A NIFTY-futures beta hedge passed its
gate (residual beta -0.02) and is shipped as a risk dial: stripping
beta 0.58 costs ~3.4pp CAGR because the beta carried real return.

## 8. Construction v2 (Track C): the literature-standard replacements

Ledoit-Wolf min-var weights and Garleanu-Pedersen partial adjustment
(tau 0.5) replaced equal weight and no-trade bands after a gated
comparison. Post-hardening honest numbers: **Sharpe 1.018 vs 0.963
equal-weight**, turnover 3.8-4.2x vs 5.2x; minvar and inverse-vol are
statistically tied (~1.02). An instructive correction is part of the
record: the first measurement (1.119, maxDD -21%) was inflated by a
position-cap bug that silently parked gross in cash — accidental
de-risking discovered by our own code review, fixed, and re-measured.
Family-level data-snooping tests: White Reality Check p = 0.012,
Hansen SPA p = 0.0415 vs the synthetic TRI. A Daniel-Moskowitz regime
gate added nothing beyond the vol targeting already shipped (null);
crowding inputs subtracted (null).

## 9. The single-name laboratory (Track D): the retail literature, tested

ICICIBANK, locked by objective screen. Four results:

1. **Decomposition preprocessing is look-ahead** (the headline).
   EMD/CEEMDAN applied full-series — as the forecasting literature does
   — reproduces its spectacular numbers exactly (OOS IC 0.41, Sharpe
   3.6 net); re-decomposing causally each day collapses them to zero.
   The leaky-minus-causal gap IS the published edge.
2. **No model beats holding the stock**: ridge, LGBM, GRU, LSTM, a
   transformer, and their ensemble all land at or below half the
   always-long floor net of per-side costs, under expanding AND
   rolling retraining (the drift question, answered: staleness is not
   the failure mode).
3. **Sentiment gating subtracts value**: official announcement
   sentiment (2,400 covered days) gates to Sharpe 0.06 vs 0.58
   always-long, with negative 5-day IC — consistent with Part I's
   inverted PEAD.
4. Summary sentence: at the daily horizon on a liquid Indian
   large-cap, every popular retail forecasting technique either leaks,
   loses to buy-and-hold, or both.

## 10. Adaptive estimation and the honest DSR (Track E)

"Daily retraining" resolves to: EWMA covariance tested against
Ledoit-Wolf (null — +0.005 Sharpe, worse drawdown, +9% turnover; LW
stays), signal-health monitoring in the daily cycle (rolling IC decay,
PSI feature drift, DSR refresh), and scheduled monthly/quarterly
re-validation. The DSR refresh delivers this report's most important
correction: **against the full 89-trial ledger, the production
strategy's deflated Sharpe is 0.20** — economically attractive,
statistically far from proven, and stated exactly that way. That
number is conservative (the ledger counts every single-name experiment
against the cross-sectional family), but its direction is the point:
three days of intensive research spends statistical credibility, the
ledger prices it, and only live out-of-sample time buys it back. The
30-session paper gate now running is that purchase.

## 11. Wrap-up findings (C7, post-tax) and the working paper

Two closing measurements. **The blend candidate**: a 50/50 rank blend
of momentum and low-vol — the single combination with a clean pre-
project prior (both components were measured independently in P2) —
scores net Sharpe 1.297 / CAGR 16.1% under the production
construction, exceeding both components by more than either exceeds
the other: genuine diversification of pick streams. It is an upgrade
CANDIDATE, deliberately not shipped until it passes the same battery
(CPCV, SPA, DSR) that revised min-var's own headline downward.
**The post-tax lens**: taxing FY-netted gains at STCG 20.8% (the
realistic regime at ~3-month average holding) takes the production
configuration from 13.7% to 11.0% CAGR and Sharpe 1.02 to 0.82 —
the number a real account eats, stated before real money exists.

The D2 finding is issued separately as a working paper:
`PAPER_leaky_decomposition.md` — "Decomposition-Based Preprocessing in
Retail Price Forecasting Is Look-Ahead: A Reproduction and Correction
on Indian Equity Data."

## 12. The blend verdict, and a correction to our own headline

The C7 candidate went through its pre-registered battery and **did not
pass**: PBO 0.500 (gate < 0.5) and family SPA p = 0.655 (gate < 0.05),
against passes on sub-period stability (blend beats momentum in all
three regimes) and DSR (0.55 vs 0.18). Production is unchanged. The
weight sweep is worth recording anyway because it is a plateau, not a
spike — every interior weight (0.25/0.50/0.75, Sharpe 1.23-1.30) beats
both pure endpoints (1.02 momentum, 1.05 low-vol) — which is what a
real diversification effect looks like, and simultaneously why PBO
cannot identify the "best" weight: choosing among statistically
indistinguishable configs is a coin flip by construction.

The battery also corrected a claim this report made earlier. Track C's
SPA rejection (p = 0.0415) came from a family that included the naive,
fully-invested momentum baseline (CAGR 23.6%). Over CONSTRUCTED
configurations only, SPA returns p = 0.655. The reason is structural,
not a bug: SPA tests mean EXCESS RETURN, and the shipped configuration
deliberately runs at 13.6% volatility against the index's 15.98% and
below full investment, so its raw CAGR (13.7%) sits just under the
index (14.97%) while its Sharpe (1.02) sits above (0.94).

**The precise claim, therefore**: the shipped book delivers better
risk-adjusted return and shallower drawdowns than the index at lower
volatility — not more raw return than the index once the number of
configurations tried is accounted for. That is a weaker claim than the
one this report carried for a day, and it is the correct one. It is
recorded here, in ADR 0011, and in every downstream document, because
a project whose entire thesis is honest evaluation does not get to
exempt its own headline from the same treatment.
