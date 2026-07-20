# D4: news/announcement sentiment on ICICIBANK — null published

Date: 2026-07-20. Report `d4_sentiment_20260720T044815Z.json`; two
trials in the ledger. Protocol: daily VADER sentiment index (5d
trailing mean), knowability via next-actual-session snap (15:30 IST
cutoff), gate = long when trailing sentiment above its 1y median else
flat, per-side NSE costs, vs the always-long floor.

| arm | coverage | IC (1d) | IC (5d) | gated Sharpe | always-long | delta |
|---|---|---|---|---|---|---|
| exchange announcements (2010+) | 2,400 days | -0.008 | -0.036 | 0.06 | 0.58 | **-0.52** |
| GDELT web news (partial, 47/115 mo) | 263 days | +0.004 | +0.024 | 0.25 | 0.58 | -0.33 |

## Reading

1. **The high-fidelity arm is decisive**: official announcement
   subject-line sentiment has ~zero next-day IC and mildly NEGATIVE
   5-day IC on the locked name — consistent with P4's inverted-PEAD
   finding (Indian announcement reactions fade/reverse). Gating on it
   just keeps you out of the market (47% time-in) and behind the floor.
2. GDELT's arm is data-starved (263 covered days spread over years)
   and its tiny positive ICs are noise; it will be refreshed when the
   throttled backfill completes, but no plausible completion turns
   -0.33 into a win.
3. VADER on financial headlines is a blunt lexicon; a finance-tuned
   scorer (or the GROQ-gated LLM path) is the only untested upgrade,
   noted as future work — expectations low given (1).

## Track D closes

Five phases, five honest results: D1 locked ICICIBANK by screen; D2
exposed decomposition preprocessing as pure look-ahead (the
paper-grade artifact); D3/D5 found no model in the zoo beats holding
the stock, under any retrain window; D4 found sentiment gating
subtracts value. The single-name laboratory's summary sentence for the
research report: **at the daily horizon on a liquid Indian large-cap,
every popular retail forecasting technique either leaks, loses to
buy-and-hold, or both — and the cross-sectional book remains the only
validated edge.** The forward news archive keeps collecting daily; the
question can be reopened with better data in a year.
