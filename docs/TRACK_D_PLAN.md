# TRACK_D_PLAN v1 (2026-07-19) — single-name deep dive

Adopted at VJ's direction (ADR 0007) after review of a
literature-summary he supplied. Framing agreed up front: the
cross-sectional book (minvar+tau0.5) remains the money
engine and is untouched; Track D is a rigorous single-name laboratory
whose primary scientific target is whether the PREPROCESSING claims in
the retail-forecasting literature (denoising, decomposition) survive
honest causal evaluation and Indian costs. A publishable null is an
acceptable outcome; every trial lands in the ledger.

VJ's supplied research summary (kept verbatim in the repo history,
2026-07-19 conversation) flags: LSTM-dominated literature, pervasive
overfitting, no cross-stock generalization, ensembles/regularization
as mitigations, sentiment for volatile regimes, drawdown/Sortino/
Calmar/Sharpe as metrics, decomposition (EMD/ICEEMDAN) preprocessing,
DAELM for drift, hybrid CNN-BiLSTM+LGBM, transformer lag capture, and
the acknowledged gaps (look-ahead in expanding CV, survivorship,
error-metrics-not-utility). Track D tests the testable subset honestly
and records why the rest is skipped.

---

## D1: Ticker selection — data-driven, then locked

Composite screen over the curated panel, top-decile liquidity names:

1. unbroken trading history 2010 -> today (no listing gaps > 10
   sessions);
2. liquidity: 21d median traded value rank (execution friction and
   impact negligible at any size we trade);
3. volatility in the 25th-75th percentile band of the liquid universe
   (VJ: neither highly volatile nor dead);
4. clean corporate-action history (zero CA sanity-gate rejections);
5. no structural break (excludes HDFCBANK: 2023 merger).

Shortlist agreed: RELIANCE, ICICIBANK (VJ leans ICICIBANK; tiebreak
goes to it if scores are within 5%).

**LOCKED 2026-07-19: ICICIBANK** — clear composite winner (0.896 vs
RELIANCE 0.767; report ticker_selection_20260719T174147Z.json): ADV
Rs 1,806Cr (rank 2 of the liquid decile), vol 30.8% inside the
25-75th band (RELIANCE 26.8% sits below it), 4,103 unbroken sessions,
zero CA rejections. Changing the ticker requires a new ADR.

## D2: Preprocessing / noise-reduction study (the core experiment)

For the locked name's daily series: raw returns vs (a) wavelet
denoising (PyWavelets, db4 soft-threshold), (b) EMD / CEEMDAN
decomposition (EMD-signal package) — each in TWO variants:

- **leaky**: decompose the full series once, as most papers do;
- **causal**: re-decompose only the trailing window at each step, so
  no future sample ever touches the transform.

The delta between variants measures how much of the literature's
reported gain is look-ahead. Sources: Huang et al. (1998) for EMD;
Torres et al. (2011) for CEEMDAN; the leakage critique follows the
same logic as our lookahead suite (and is documented in e.g.
"pseudo-out-of-sample" critiques of decomposition forecasting).
Gate: table of OOS forecast value (IC of one-step-ahead sign/return)
and net strategy performance per variant; conclusion recorded either
way.

## D3: Model family — why more than one model

(Plain-language rationale, per VJ's question.) A single model's score
confounds three things: the information in the data, the model's
inductive bias, and luck. Running a FAMILY under one frozen protocol
separates them: a naive carry-forward and ARIMA set the floor any
learner must beat; ridge shows what linear structure exists; LGBM
shows nonlinear-but-tabular structure; GRU/LSTM and a small
transformer show whether sequence memory adds anything beyond lags;
an ensemble average tests the summary's "ensembles reduce overfitting"
claim. If the fancy models cannot beat the floor OOS, the data has no
exploitable memory — that conclusion is only credible when the whole
family ran identically. No GPU constraint imposed (VJ: model quality
first; large sweeps go to Colab per PROJECT_PLAN section on GPU).

Protocol: purged expanding walk-forward on the single series (embargo
>= horizon), strategy evaluation long/flat next-day net of NSE costs,
metrics Sharpe/Sortino/Calmar/maxDD + DSR against the ledger. Error
metrics reported but never the headline (VJ's summary: minimize-loss
!= make-money).

## D4: News sentiment pipeline (free, Indian) + event overlay

VJ: sentiment analysis has demonstrably added value; build a free
Indian news pipeline. Design:

1. **Historical**: GDELT 2.0 (free, 2015+) filtered to the locked
   ticker's company names — coverage of Indian corporates is shallow
   but nonzero; fidelity labeled clearly (plan v2 already demoted
   GDELT to exploratory).
2. **Forward**: daily RSS collectors (Google News query per company,
   Economic Times / Moneycontrol feeds) appended to the raw zone from
   adoption day — builds the proper archive we cannot buy backwards.
3. **Existing**: our 1.48M timestamped exchange announcements for the
   name — the highest-fidelity "news" already in house; D4's baseline.
4. Scoring: lexicon sentiment (VADER) offline; LLM scoring key-gated
   behind GROQ_API_KEY, same guardrails as the taxonomy path.

Gate: sentiment features added to the D3 winner; incremental OOS value
reported (expected small; the announcement corpus is the fair test).

## D5: Drift and regime honesty

Expanding vs rolling retrain windows (the summary's DAELM/data-drift
concern, tested without the exotic machinery), performance per regime
(bull/bear/stress from the C4 frame), and a stability table across
retrain frequencies. Gate: the chosen deployment recipe (window,
retrain cadence) justified by the table, not by default.

## Skipped, with reasons

- Sparrow Search / TLBO hyperparameter metaheuristics: standard
  cross-validated search covers the same space reproducibly.
- Satellite imagery / earnings-call audio: no free scriptable source.
- "Multimodal fusion": VJ's own summary notes reviewed papers reduce
  it to feature concatenation; D4 does the honest version of that.
- DAELM specifically: the drift QUESTION is kept (D5); the specific
  architecture is not required to answer it.

## Sequencing

D1 (one session, locks the ticker) -> D2 (core) -> D3 -> D4 (pipeline
starts collecting forward data immediately at D1 time so the archive
grows while D2-D3 run) -> D5. Ledger-first throughout; PROJECT_PLAN.md
changelog updated at each phase completion.
