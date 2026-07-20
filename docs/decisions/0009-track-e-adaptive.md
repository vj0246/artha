# ADR 0009: adopt Track E (adaptive estimation & drift defense)

Date: 2026-07-20. At VJ's direction, following his question on daily
dynamic/partial retraining. Full plan: docs/TRACK_E_PLAN.md.

## Decision

Daily "retraining" is implemented as: (E1) an EWMA-vs-LW covariance
study gating any estimator change, (E2) signal-health monitoring in
the daily cycle (IC decay, PSI feature drift, monthly DSR refresh),
(E3) scheduled monthly research-agent + quarterly construction-study
re-runs, (E4) credential-gated impact recalibration from own fills,
and (E5) a binding retrain-cadence policy.

## Explicitly rejected

Daily/weekly retraining of predictive models. Grounds: the production
strategy carries no fitted parameters, and D5 measured expanding vs
rolling retraining across six model families with no material
difference — parameter staleness is not this system's failure mode.
Faster retraining would add turnover, ledger burn, and overfitting
surface with no evidenced benefit. Revisit only if E2's IC monitor
fires persistently.
