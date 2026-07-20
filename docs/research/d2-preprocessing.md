# D2: decomposition preprocessing is look-ahead — measured

Date: 2026-07-19. Ticker: ICICIBANK (D1 lock). Protocol: ridge on lags
1-10 of the (transformed) log-return series, expanding walk-forward,
monthly retrain, 1-day embargo, 3y burn-in; TARGET always the raw
next-day return; long/flat strategy net of full NSE delivery costs at
Rs 5L (28.7 bps per full switch). Report
`d2_preprocess_20260719T180939Z.json`; six trials in the ledger.

| variant | OOS IC | sign acc | net Sharpe | net CAGR | maxDD |
|---|---|---|---|---|---|
| raw | −0.009 | 51.1% | −0.52 | −15.1% | −90% |
| wavelet leaky | −0.031 | 50.6% | +0.47 | +10.2% | −55% |
| wavelet causal | −0.018 | 50.3% | +0.37 | +6.8% | −57% |
| EMD leaky | **+0.413** | **63.3%** | **+3.15** | **+95.1%** | −15% |
| EMD causal | −0.038 | 50.5% | +0.03 | −2.7% | −75% |
| CEEMDAN leaky | +0.413 | 63.3% | +3.16 | +95.1% | −15% |

**Look-ahead gap (leaky − causal): EMD IC +0.450, Sharpe +3.12.**

## Reading

1. **The decomposition literature's headline numbers reproduce exactly
   — and are an artifact.** Decomposing the full series once (how the
   EMD/CEEMDAN forecasting papers do it) turns each IMF sample into a
   function of FUTURE returns; a ridge on lags of that series scores
   IC 0.41 and Sharpe 3+ "out of sample". Re-decomposing causally each
   day — the only version tradeable in real time — collapses to IC
   −0.04, Sharpe 0.03. The entire published edge is the transform
   leaking the future, not the market being predictable.
2. **Wavelet denoising is honest but adds nothing over a long-only
   stance**: causal Sharpe 0.37 with 96% time-in-market is mostly
   ICICIBANK's own drift, not forecasting skill (raw buy-and-hold over
   the window is comparable).
3. **Raw daily returns carry no exploitable linear memory net of
   costs** (IC −0.01, Sharpe −0.52 after 81 switches/yr at 28.7 bps) —
   consistent with the cross-sectional P3 null and with market
   efficiency at the single-name daily horizon.
4. Method note: our leaky variants avoid the OTHER common flaw
   (predicting a denoised target); the target was always raw. The gap
   is therefore attributable to feature leakage alone.

## Consequence for D3-D5

The D3 model family runs on the RAW series (and causal-wavelet as a
robustness arm): any model that needs the leaky transform to work is
disqualified by construction. Expectation for D3 recorded now: the
floor (always-long) is the bar; sequence models must beat it OOS net
of costs to claim memory exists.

## Correction (2026-07-20 review): per-side costs

The original run double-charged switches (full round trip per toggle).
Corrected numbers move every variant up but change nothing structural:
raw -0.06 (was -0.52), EMD leaky +3.62, EMD causal +0.22, look-ahead
gap now IC +0.45 / Sharpe +3.40. Conclusion unchanged: the decomposition
edge is the leak.
