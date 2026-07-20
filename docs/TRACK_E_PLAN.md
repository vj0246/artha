# TRACK_E_PLAN v1 (2026-07-20) — adaptive estimation & drift defense

Adopted at VJ's direction (ADR 0009). Context that shapes everything
here: the production strategy has NO fitted predictive parameters —
momentum ranks, the LW covariance, vol target, and ADV caps are all
re-estimated from the full updated panel at every rebalance, so "daily
retraining" in the LSTM-literature sense has no target. D5 measured
the retraining question directly (expanding vs rolling across six
model families): zero difference — decay of parameters was not the
failure mode. Track E therefore does the version of "learn from each
new day" that the evidence supports: incremental RISK estimation,
drift MONITORING, scheduled research refresh, and (credential-gated)
execution-cost learning from our own fills.

## E1: EWMA covariance (the real daily partial update)

**What.** Replace the flat 252d window feeding Ledoit-Wolf with
exponentially weighted moving covariance (RiskMetrics lambda = 0.94):
each new day updates the estimate incrementally with recent days
weighted more — the canonical "partial retraining" for risk models.

**Why.** A flat window jumps when a crisis day enters or leaves the
sample; EWMA adapts smoothly and responds faster to regime shifts.
Whether that helps NET of the extra turnover it induces is an
empirical question, answered under the identical protocol.

**Sources.** J.P. Morgan/Reuters, RiskMetrics Technical Document
(4th ed., 1996) — lambda 0.94 for daily data. Ledoit-Wolf 2004 as the
incumbent. Fleming, Kirby & Ostdiek (2001) for the economic value of
volatility timing.

**Build.** `riskmodel.ewma_cov(returns, lam)`; `run_backtest` gains
`cov_estimator: "lw" | "ewma"`; study `scripts/run_e1_ewma.py`
compares minvar+tau0.5 under both, net of costs, ledger-first.
Gate: ship EWMA only if it clearly improves net Sharpe or drawdown;
otherwise publish the null and keep LW.

## E2: Signal-health monitoring (monitoring IS the retraining)

**What.** A daily step in the 19:00 cycle that measures whether the
shipped signal and features still look like the ones that were
validated: rolling 63d/252d rank-IC of momentum vs realized 5d forward
returns (alert on sustained sign flip), PSI drift of every library
feature's cross-sectional distribution vs its trailing-year reference
(alert past 0.25 — the standard "major shift" threshold), and a
monthly deflated-Sharpe refresh against the growing ledger.

**Why.** With no parameters to retrain, the update-worthy object is
the BELIEF that the edge persists. IC decay and feature drift are the
observable early warnings; alerting on them converts "when should we
revisit?" from vibes to thresholds.

**Sources.** PSI: standard credit-scoring population-stability
practice (>0.25 = major shift). IC monitoring: Grinold & Kahn, Active
Portfolio Management, ch. on information analysis.

**Build.** `scripts/run_signal_health.py` appending
reports/paper/signal_health.jsonl + alerts; wired into the daily cycle
as a non-critical step; PSI helper unit-tested.

## E3: Scheduled research refresh

**What.** artha-monthly task (1st of month): B6 research agent on the
updated panel + SPA refresh. artha-quarterly task: full construction
study re-run so the shipped config re-earns its seat on unseen data.

**Why.** New data accumulates ~21 sessions/month; re-running the
validated machinery on schedule is how the research itself "retrains"
— with every run ledgered, so multiple-testing honesty survives
automation (same principle as B6).

**Build.** Wrapper cmd scripts + schtasks registrations (monthly,
quarterly); no new study code.

## E4: Execution-cost online learning (BLOCKED on Kite credentials)

Impact-curve recalibration (a, b in a + b*sqrt(V/ADV)) from our own
fills — true per-fill online learning; foundation (orders_log +
slippage report) shipped in B3. Activates the week live quotes exist.

## E5: Retrain-cadence policy (binding)

1. Risk estimates: updated every rebalance from the full current
   panel; EWMA daily-weighting if E1's gate passes.
2. Predictive models: none shipped. If one ever ships, retrain
   cadence = quarterly (D5 evidence: faster adds churn, not signal),
   revisited only if E2's IC monitor fires.
3. Nothing retrains faster than its own measured decay; every
   scheduled re-run appends to the ledger BEFORE results are read.
4. Structural changes (new estimator, new signal) remain gated
   studies with ADRs — never silent swaps.

## Status 2026-07-20: TRACK E EXECUTED

E1 NULL PUBLISHED: EWMA 1.023 vs LW 1.018 Sharpe (statistical noise)
with worse drawdown (-29.8% vs -28.3%) and +9% turnover — the faster
estimator buys responsiveness the strategy then pays for in churn. LW
stays (report e1_ewma_20260720T051030Z.json; 2 ledger trials). E2 LIVE
in the daily cycle — first run: momentum IC healthy (63d +0.026 / 252d
+0.035), dist_52w_low PSI 0.46 flagged (regime-shape drift, watch),
and the DSR refresh delivered the multiple-testing bill: production
Sharpe 1.018 deflates to DSR 0.20 against the 89-trial ledger
(conservative — the count includes single-name D-track trials — but
directionally the honest number). E3 REGISTERED: artha-monthly +
artha-quarterly scheduled. E4 blocked on credentials. E5 policy
binding.
