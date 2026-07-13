# P3: model comparison study (plan v2 section 7.3)

Date: 2026-07-13. Verdict: **gate PASSED** — four families under one purged
protocol, DSR and PBO reported, and an honest headline: **no ML model beats
the simple baselines net of costs; ridge is the best of the four, and the
in-sample winner is overfit 86% of the time.**

## Question

Do ML models add value over simple factors on Indian equities when
validation is honest (purged CV, embargo, costs, multiple-testing
deflation)?

## Method

- Matrix: 233,294 weekly rows (PIT top-500 universe), 19 price/volume
  features cross-sectionally z-scored, label = 5d forward return z-scored
  per date.
- Walk-forward: 48 purged expanding folds, 13-week test blocks, 1-week
  horizon + 4-week embargo; OOS 2014-08 -> 2026-06.
- Models: ridge (GKX anchor), LightGBM, small MLP (early-stopped), tiny
  FT-style tabular transformer (d_model 32; trained on the RTX 2050 —
  CUDA torch installed via pip override; note `uv sync` reverts to the CPU
  wheel, rerun the cu126 install and use `uv run --no-sync`).
- Net performance: OOS predictions through the P2 backtester (top 25,
  weekly, full NSE cost model, Rs 25L).
- Every config a ledger trial (5 to date); DSR deflated by trial count.
- CPCV: 8 blocks choose 2 = 28 purged combinations; PBO across the four
  configs (Bailey et al. logit-rank method).

## Results

| Model | OOS rank IC | IC t | Decile spread (z) | Net Sharpe | Net CAGR | Turnover/yr | DSR | CPCV OOS IC |
|---|---|---|---|---|---|---|---|---|
| Ridge | **0.043** | 6.5 | 0.063 | 0.84 | 15.5% | 18x | **0.998** | **0.045** |
| LightGBM | 0.025 | 7.5 | 0.056 | 0.27 | 3.8% | 39x | 0.52 | 0.031 |
| MLP | 0.025 | 7.3 | 0.054 | 0.50 | 8.7% | 39x | 0.46 | 0.030 |
| Transformer | 0.041 | 7.4 | **0.072** | **0.89** | 16.0% | 30x | 0.84 | 0.039 |

**PBO = 0.86** (28 combinations): the best in-sample config — almost always
LightGBM, whose in-sample IC reaches 0.36 against 0.03-0.05 out of sample —
lands in the bottom half OOS in 24 of 28 combinations. Ridge shows no
IS/OOS gap at all (0.046 vs 0.052 in the fold shown); its DSR of 0.998
survives deflation because its Sharpe is real, not selected.

P2 baseline bars: momentum 12-1 net Sharpe 0.96, low-vol 1.08. **No model
clears them.** The tree/net models translate their statistically strong IC
(t > 7) into weak net performance because their signal is concentrated in
fast reversal-like patterns: 39x annual one-way turnover pays ~4% a year in
charges plus impact.

## Reading

1. Complexity without cost-awareness buys turnover, not alpha, at weekly
   horizons in this market. Consistent with the GKX finding that gains from
   nonlinearity are modest on price-only features.
2. The transformer is the interesting runner-up: transformer > MLP = LGBM
   in net terms at equal information, because attention over z-scored
   feature tokens preserved slower structure (30x vs 39x turnover).
3. Per plan section 7.1's promise: if ML cannot beat the best simple factor
   net of costs, ship the simple factor and say so. As of P3, the shipping
   candidate is momentum/low-vol; the ML story continues in P4 by testing
   whether EVENT features add orthogonal information (Model A vs B), and in
   P5 turnover controls (no-trade bands) that specifically address why the
   nonlinear models bleed.

## Limitations

- One hyperparameter config per family (deliberate: each extra config is a
  ledger trial and a DSR penalty); no tuning sweeps yet.
- 5d label only; 21d label queued as a P4-adjacent trial.
- Turnover penalty/bands not yet inside the backtest loop; nonlinear models
  are disadvantaged by their own churn, which is a finding, not a bug.
- DSR sr_variance uses a conservative prior rather than the cross-trial
  empirical variance (ledger too short); revisit as the ledger grows.
