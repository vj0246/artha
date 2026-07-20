# Decomposition-Based Preprocessing in Retail Price Forecasting Is Look-Ahead: A Reproduction and Correction on Indian Equity Data

**VJ** · Working paper, 2026-07-20 · Code and immutable data manifest:
github.com/vj0246/artha (every experiment ledgered in
`reports/ledger.jsonl`; this study: `scripts/run_d2_preprocess.py`)

## Abstract

A large applied-forecasting literature reports strong daily equity
prediction after decomposition-based preprocessing (EMD, EEMD,
CEEMDAN, wavelet hybrids), with out-of-sample information coefficients
above 0.3 and annualized Sharpe ratios above 3. We reproduce these
results exactly on ICICI Bank (NSE, 2010-2026, 4,102 daily
observations) — and show they are an artifact of applying the
decomposition to the full series before splitting: each transformed
training sample is then a function of future returns. Re-computing the
identical transform causally (re-decomposing only the trailing window
at each step, so no future observation ever touches the input)
collapses the edge to zero. The leaky-minus-causal gap — IC +0.45,
net Sharpe +3.4 — quantifies the look-ahead these papers ship as
performance. Wavelet soft-threshold denoising, which is nearly causal
by construction, shows no such gap and no exploitable edge either.
A companion evaluation of six model families (ridge, gradient
boosting, GRU, LSTM, transformer, ensemble) under the same causal
protocol finds none beat buy-and-hold net of realistic Indian
transaction costs, under either expanding or rolling retraining.

## 1. The claim under test

Papers applying EMD-family decomposition before neural forecasting
routinely report daily directional accuracy of 60-75% on single
equities. The standard pipeline: decompose the full price/return
series into intrinsic mode functions (IMFs), drop or model the
high-frequency component, train on the transformed series, evaluate on
a held-out tail. The flaw is structural: EMD is a global transform —
IMF values at time t depend on the entire series, including t+1
onward. A train/test split AFTER transformation does not remove the
dependence; the training features already contain the future.

## 2. Data and protocol

NSE cash-equity daily panel built from primary exchange sources with
declared-corporate-action adjustment, verified two ways (declared
factors against ex-day prices and vice versa; 14 phantom declared
events rejected). Test name ICICIBANK, selected by a pre-registered
composite screen (liquidity, mid-band volatility, unbroken history) —
not by result. Protocol held fixed across every variant: ridge on lags
1-10 of the (transformed) log-return series; the TARGET is always the
raw next-day return (this isolates feature leakage from the separate
denoised-target flaw); expanding walk-forward, monthly retrain, 1-day
embargo, 3-year burn-in; evaluation as a long/flat strategy net of
full Indian delivery costs charged per side (~14 bps each way at Rs 5L
including impact).

## 3. Results

| variant | OOS IC | sign acc. | net Sharpe | net CAGR |
|---|---|---|---|---|
| raw returns | −0.009 | 51.1% | −0.06 | ~0 |
| wavelet, leaky | −0.031 | 50.6% | +0.48 | +10% |
| wavelet, causal | −0.018 | 50.3% | +0.38 | +7% |
| **EMD, leaky (as published)** | **+0.413** | **63.3%** | **+3.62** | **+95%** |
| **EMD, causal (tradeable)** | **−0.038** | **50.5%** | **+0.22** | ~0 |
| CEEMDAN, leaky | +0.413 | 63.3% | +3.62 | +95% |

Look-ahead gap (EMD leaky − causal): **IC +0.450, Sharpe +3.40.**

Three observations. (i) The leaky pipeline reproduces the literature's
headline numbers almost exactly — this is not a strawman
implementation. (ii) The causal version of the SAME transform, same
model, same costs is indistinguishable from noise; the entire edge is
the transform's implicit access to the future. (iii) Wavelet
denoising, whose thresholding is local enough to be nearly causal,
shows a small gap and no edge in either direction — the modest
positive Sharpes reflect the stock's own drift at ~100%
time-in-market, not forecasting skill.

## 4. The model zoo under the honest protocol

With preprocessing settled, we ran ridge, LightGBM, GRU, LSTM, a small
causal transformer, and their ensemble mean on the raw series
(chronologically ordered sequences, per-side costs), against an
always-long floor, with both expanding and rolling-3y retraining:
best learner (LSTM) net Sharpe +0.16 vs floor +0.44; ensemble −0.23;
retraining cadence immaterial. A sentiment-gated variant using 2,400
days of official exchange-announcement sentiment also lost to the
floor (Sharpe 0.06), consistent with the inverted post-announcement
drift we document separately on this market.

## 5. Conclusion

On a liquid Indian large-cap at the daily horizon, every popular
retail forecasting technique we tested either leaks, loses to
buy-and-hold after costs, or both. The decomposition literature's
results are real in the narrow sense that they reproduce — and
illusory in the only sense that matters: no tradeable version
survives. The general lesson is methodological: any global transform
(decomposition, full-series scaling, full-series PCA) applied before a
temporal split converts test-set information into training features,
and the resulting numbers can be spectacular. The defense is equally
general: recompute every transform inside the information set
available at each decision time, and let the leaky-minus-causal gap
measure what the shortcut was worth.

## Reproducibility

`uv sync && uv run python scripts/run_d2_preprocess.py` regenerates
every number from the raw exchange archives (sha256-manifested). The
causal wrapper's no-lookahead property is unit-tested bit-identically
(perturbing the future leaves all past outputs unchanged).
