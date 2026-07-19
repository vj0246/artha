# TRACK_C_PLAN v1 (2026-07-19) — research v2: state-of-the-art extensions

Adopted after Track A (P0-P6) and Track B (P7-P9, B1-B6) completed. Same
discipline: gates, trial-ledger honesty, plan changes by commit. ADR 0006
records the adoption decision.

Motivation: the shipped strategy (constructed momentum, net Sharpe 0.97)
is validated but uses first-generation construction (equal weight,
ad-hoc no-trade bands) and reports multiple-testing honesty only through
the deflated Sharpe. Each phase below replaces an ad-hoc component with
the literature-standard tool, or closes a known statistical gap. Every
phase is judged net of full Indian costs under the identical backtest
protocol — an upgrade ships only if it survives costs, and a null is
published as a null, as before.

---

## C1: Superior Predictive Ability — the correct multiple-testing answer

**What.** White's Reality Check and Hansen's SPA test over the family of
strategies actually tried, using a stationary bootstrap of daily excess
returns vs the benchmark and vs the best simple baseline.

**Why.** The deflated Sharpe (Bailey & Lopez de Prado 2014) corrects one
observed Sharpe for the expected maximum under the null given N trials —
but it assumes a cross-trial Sharpe variance rather than measuring the
dependence between trials. The RC/SPA family tests the sharp null "no
strategy in the tried set beats the benchmark" directly on the joint
bootstrap distribution, capturing cross-strategy correlation exactly.
Hansen's studentized, recentred variant fixes the RC's conservatism when
poor strategies are included. This is the standard of evidence in the
forecasting literature and the correct complement to the DSR + ledger.

**Sources.** White, H. (2000), "A Reality Check for Data Snooping",
Econometrica 68(5). Hansen, P.R. (2005), "A Test for Superior Predictive
Ability", JBES 23(4). Politis, D. & Romano, J. (1994), "The Stationary
Bootstrap", JASA 89(428). Sullivan, Timmermann & White (1999) for the
canonical application to technical trading rules.

**Build.** `artha/models/spa.py`: stationary bootstrap (mean block ~21
days), RC p-value, Hansen SPA-consistent p-value; unit tests on planted
nulls/alternatives. `scripts/run_spa.py`: regenerate daily net series for
the strategy family (baselines + constructed variants), test vs the
synthetic NIFTY 500 TRI. Gate: script runs on real data; conclusion (in
either direction) recorded in the research note and the ledger.

## C2: Covariance-aware construction (Ledoit-Wolf risk model)

**What.** Replace equal weight inside the selected top-N with
risk-model-aware schemes: inverse-vol (naive risk parity) and long-only
minimum-variance from a Ledoit-Wolf shrunk covariance — compared against
equal weight under identical selection, costs, and constraints.

**Why.** Equal weight ignores that the book's risk is concentrated in its
most volatile names; the P5 attribution shows beta 0.59 doing much of the
work. A shrunk covariance is the institutional standard because the
25×252 sample covariance is noise-dominated (Ledoit-Wolf's "Honey, I
Shrunk the Sample Covariance Matrix"); DeMiguel et al. (2009) set the
bar to clear — naive 1/N is famously hard to beat after estimation error,
so publishing "1/N survives" is itself a defensible result.

**Sources.** Ledoit, O. & Wolf, M. (2004), "Honey, I Shrunk the Sample
Covariance Matrix", JPM 30(4), and (2003) JEF for the shrinkage
intensity. DeMiguel, Garlappi & Uppal (2009), "Optimal Versus Naive
Diversification", RFS 22(5). Clarke, de Silva & Thorley (2011) for
long-only minimum variance behavior.

**Build.** `artha/portfolio/riskmodel.py`: LW shrinkage toward the
scaled identity, per-name trailing vols, closed-form min-var weights with
long-only clip + renormalize (disclosed heuristic, no QP dependency).
Constructor gains `scheme: equal | ivol | minvar`; the backtester feeds a
knowable-at-t trailing return window for the picks. Gate: three-way
comparison net of costs on the full window; winner (or 1/N null) ships.

## C3: Turnover-optimal trading (Gârleanu-Pedersen partial adjustment)

**What.** Replace the ad-hoc 25% no-trade band with the
aim-portfolio/trading-speed rule: trade a fixed fraction toward the
target each rebalance, with the fraction set by the cost-vs-alpha-decay
tradeoff.

**Why.** Gârleanu & Pedersen (2013) show the optimal policy under
quadratic costs is "aim in front of the target, trade partially toward
the aim" — in discrete implementable form, w_new = w_prior + τ(target −
w_prior). Bands create a dead zone then trade fully (bang-bang); partial
adjustment trades a little always, cutting turnover at equal tracking.
Turnover is the strategy's largest controllable cost (the P2 reversal
autopsy: 47x turnover killed a 0.72 gross Sharpe), so this is the
highest-leverage cost lever left.

**Sources.** Gârleanu, N. & Pedersen, L.H. (2013), "Dynamic Trading with
Predictable Returns and Transaction Costs", JF 68(6). Frazzini, Israel &
Moskowitz (2018) for realized trading-cost context.

**Build.** Constructor gains `trade_speed: float | None` (replaces bands
when set); sweep τ in {0.25, 0.5, 0.75} vs the band baseline in one
script, identical everything else. Gate: report net Sharpe / turnover /
tracking for each; ship the winner.

## C4: Regime-conditional gross (with the momentum-crash literature)

**What.** Scale gross exposure by an observable regime signal — bear
state (benchmark below its own 2-year path) and stress vol — testing the
Daniel-Moskowitz momentum-crash mechanism on Indian data.

**Why.** Momentum's known failure mode is the crash after bear-market
reversals (Daniel & Moskowitz 2016): the short/loser leg rallies
violently when the market turns. Long-only Indian momentum holds the
winner leg only, but the 2018-2020 drawdown in our own tearsheet is the
same regime signature. Vol targeting (already shipped) captures part of
this; the conditional question is whether an explicit bear+vol gate adds
net value beyond it — answered out-of-sample under the standard protocol,
not by inspection.

**Sources.** Daniel, K. & Moskowitz, T. (2016), "Momentum Crashes", JFE
122(2). Barroso, P. & Santa-Clara, P. (2015), "Momentum Has Its Moments",
JFE 116(1) — constant-vol momentum, the direct ancestor of our vol
targeting. Cooper, Gutierrez & Hameed (2004) for market-state dependence.

**Build.** Regime features from the synthetic TRI (knowable at t):
2-year cumulative return sign, 63d realized vol percentile. Gross gate =
f(bear, stress) applied on top of vol targeting; compare {vol-target
only} vs {vol-target + regime gate} net. Gate: OOS improvement in MAR /
maxDD at comparable CAGR, or publish the null.

## C5: Realized execution study (BLOCKED on Kite credentials)

**What.** Implementation shortfall vs close benchmark per fill, impact
curve recalibration (a, b in cost_bps = a + b sqrt(V/ADV)) from our own
orders once Kite LTP quotes flow.

**Why.** The cost model's impact constants are priors; B3's gate is
"realized within 2x model". Fitting the impact curve to own fills is
the only honest calibration, and per-order shortfall attribution
(Almgren-Chriss decomposition) is the standard.

**Sources.** Perold, A. (1988), "The Implementation Shortfall", JPM.
Almgren, R. & Chriss, N. (2000), "Optimal Execution of Portfolio
Transactions", J. Risk. Almgren et al. (2005) for sqrt impact evidence.

**Build.** Foundation already shipped (per-fill orders_log.jsonl +
run_slippage_report.py). Remaining: shortfall decomposition + curve fit,
buildable the week live quotes exist. Owner: waits on VJ's credentials.

## C6: Crowding and liquidity stress overlay

**What.** Amihud illiquidity shocks as a stress indicator for the
momentum book; combine with C4's regime gate rather than a separate
mechanism.

**Why.** Momentum crashes and liquidity spirals co-move (Pedersen's
liquidity-spiral mechanism); the book's own illiquidity exposure is
measurable daily from the panel. Folding it into the C4 gate keeps one
regime mechanism with two observable inputs instead of stacking
overlays.

**Sources.** Amihud, Y. (2002), "Illiquidity and Stock Returns", JFM
5(1). Brunnermeier, M. & Pedersen, L.H. (2009), "Market Liquidity and
Funding Liquidity", RFS 22(6).

**Build.** Book-weighted Amihud percentile as a third input to the C4
gate; evaluated inside the same C4 script and gate.

---

## Status 2026-07-19: C1-C4+C6 EXECUTED (docs/research/track-c-study.md)

C2+C3 GATE PASSED with a winner: minvar + tau 0.5 — Sharpe 1.055 vs
0.960 shipped, maxDD -21.2% vs -27.1%, turnover 3.8x vs 5.2x. DeMiguel
1/N null REJECTED on this book. C1: RC p = 0.0125, SPA p = 0.046 — the
family beats the synthetic TRI at 5% after snooping correction. C4+C6:
NULL PUBLISHED — vol targeting already captures the crash premium; DM
gate trades 0.05 Sharpe for 4.5 DD points (MAR wash), crowding input
subtracts. Live paper stays on equal+bands until the B1 clock ends;
minvar+tau0.5 adoption = one line + clock restart (VJ's call). C5
still blocked on credentials.

## Sequencing and gates

C2 + C3 first (one "construction v2" study: shared backtests, one
report), then C1 (SPA machinery over the enlarged strategy family — the
family should include construction v2 variants so the test covers them),
then C4 + C6 (one regime study). C5 whenever credentials land. Every
config run appends to the trial ledger BEFORE its result is read —
DSR/SPA honesty depends on counting the losers.
