# ADR 0008: ship Ledoit-Wolf min-var + tau 0.5 as the production construction

Date: 2026-07-19 (decision; recorded 2026-07-20 after a code-review
finding flagged the missing record — repo rule 3).

## Decision

The live paper book's construction changed from the P5-certified
equal-weight + no-trade-bands to Ledoit-Wolf minimum-variance weights
with Garleanu-Pedersen partial adjustment (tau 0.5), embodied in
`production_constructor()` (src/artha/portfolio/construct.py), consumed
by run_paper_day, run_weekly_review, and run_live_readiness.

## Evidence and authorization

- Track C study: minvar+tau0.5 beat equal+bands at the time of decision
  (then-measured 1.119 vs 0.963). The 2026-07-20 post-hardening rerun
  (cap redistribution, epsilon exit, per-name coverage, tighter CA gate)
  revised this to 1.018 vs 0.963, maxDD -28.3% vs -27.1%, turnover 4.2x
  vs 5.2x — the earlier drawdown advantage was largely unintended cash
  from the cap-clip bug. minvar and ivol (1.024) are now statistically
  tied; the config stays because switching between tied configs would
  restart the B1 clock for noise (docs/research/track-c-study.md,
  post-hardening section; Hansen SPA p = 0.0415).
- VJ approved the switch explicitly on 2026-07-19 ("switch to minvar").

## Consequences

- The B1 30-session clock restarted 2026-07-19; equal-bands paper
  history archived to reports/paper/archive-equalbands-20260719/.
- Replay/readiness paths must warm the risk model up (>= 63 obs) before
  comparison windows — enforced after review finding 2026-07-20.
- The 2026-07-20 review hardening applies to this config: per-name risk
  coverage (no all-or-nothing equal fallback), scheme_used logged per
  session, position-cap excess redistribution, epsilon full-exit for
  dropped names. These change backtest numbers slightly; the Track C
  study is rerun and the note updated whenever construction mechanics
  change.
