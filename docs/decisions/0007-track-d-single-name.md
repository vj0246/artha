# ADR 0007: adopt Track D (single-name laboratory)

Date: 2026-07-19. At VJ's direction after his review of a
forecasting-literature summary; full plan in docs/TRACK_D_PLAN.md.

## Decision

Run a single-ticker research track (D1-D5) alongside the untouched
cross-sectional production book. Primary target: test whether
decomposition/denoising preprocessing claims survive causal evaluation
and Indian costs. Secondary: model-family comparison without GPU
constraints, a free Indian news-sentiment pipeline (GDELT historical +
RSS forward + our announcement corpus as baseline), and drift/regime
analysis.

## Constraints

1. The claim "models are only valid per-ticker" is treated as a
   HYPOTHESIS to test, not a premise — recorded because the
   cross-sectional evidence (P3: PBO 0.86 with 100x more data) points
   the other way, and expectation-setting is part of the record.
2. Leaky vs causal decomposition are both run, deliberately: the
   difference IS the finding.
3. Utility over error metrics: every model judged as a costed long/flat
   strategy with Sharpe/Sortino/Calmar/maxDD + ledger + DSR.
4. Ticker locked by D1's composite screen (shortlist RELIANCE /
   ICICIBANK, tiebreak ICICIBANK per VJ); changing it needs a new ADR.
5. New dependencies allowed: PyWavelets, EMD-signal, feedparser/nltk
   (VADER) — pure-python, free.
