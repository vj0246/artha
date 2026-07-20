# D3/D5: single-name model family — comprehensive null

Date: 2026-07-20. Ticker: ICICIBANK. Protocol: raw log returns (D2
verdict bars leaky transforms), standardized 20-lag window, expanding
AND rolling-3y walk-forward, quarterly retrain, 1-day embargo, 3y
burn-in, long/flat next-day strategy net of full NSE costs (28.7 bps
per switch). Report `d3_models_20260719T184303Z.json`; 14 trials in
the ledger.

| model | window | OOS IC | sign acc | net Sharpe | maxDD |
|---|---|---|---|---|---|
| **always long (floor)** | — | — | 50.5% | **+0.44** | −55% |
| ridge | expanding | −0.026 | 49.9% | −1.29 | −99% |
| LGBM | expanding | +0.010 | 50.7% | −1.28 | −99% |
| GRU | expanding | −0.007 | 50.7% | +0.01 | −64% |
| LSTM | expanding | −0.011 | 49.5% | +0.20 | −46% |
| transformer | expanding | −0.022 | 49.3% | −0.45 | −79% |
| ensemble mean | expanding | −0.024 | 49.7% | −0.50 | −82% |
| (rolling window) | all | ≈ same | ≈ same | ≈ same | ≈ same |

## Reading

1. **No model beats buying and holding the stock.** The best learner
   (LSTM, +0.20) sits under half the always-long floor (+0.44); most
   are strongly negative because ~50/50 sign accuracy plus 28.7 bps
   per switch is a cost treadmill. OOS ICs cluster at zero — daily
   ICICIBANK returns carry no exploitable memory for any of the five
   inductive biases tried.
2. **Ensembling does not rescue it** (−0.50): averaging five
   uninformative forecasters is still uninformative — the summary's
   "ensembles reduce overfitting" claim is true but irrelevant when
   there is no signal to protect.
3. **Drift is not the problem** (D5): rolling-3y retraining changes
   nothing materially vs expanding. The failure mode is absence of
   signal, not stale training data.
4. Together with D2, the single-name laboratory's conclusion is now
   complete and two-sided: the literature's positive results reproduce
   only with leaky preprocessing (D2), and honest evaluation of the
   standard model zoo lands exactly on the efficient-markets floor
   (D3/D5). This null pairs with the cross-sectional null (P3) — with
   100x more data the learners at least matched simple factors; with
   one series they cannot even pay their own transaction costs.
5. **Consequence**: no single-name model ships. The money remains in
   the cross-sectional book (Sharpe 1.12). D4's remaining question —
   whether news/announcement sentiment adds anything to an always-long
   or cross-sectional stance — is now the last open Track D item,
   pending the GDELT archive completing.

## Correction (2026-07-20 review): per-side costs + chronological sequences

Two fixes rerun: costs charged per side (old run double-charged), and
sequence models now read time forward with the readout on the newest
lag (old run fed them reversed). Corrected [expanding]: always-long
+0.44; GRU +0.10, LSTM +0.16, transformer -0.14, ensemble -0.23,
ridge -0.52, LGBM -0.48. The sequence arms improve as expected from
the fix but remain under half the floor: **the null stands on corrected
numbers** — no model beats holding the stock.
