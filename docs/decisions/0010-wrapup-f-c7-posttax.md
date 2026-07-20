# ADR 0010: wrap-up scope — Track F publication, C7 blend study, post-tax lens

Date: 2026-07-20. VJ's direction: wrap up; execute the publication
track, the momentum+low-vol blend study, and whatever else is
necessary within the locked scope (no paid data, no more
preprocessing).

## Decisions

1. **Track F**: the D2 leaky-decomposition finding is written as a
   working paper (docs/research/PAPER_leaky_decomposition.md) and a
   shareable blog post; the research report carries Part II. These are
   publication artifacts — no new experiments.
2. **C7**: two pre-registered configurations (pure low-vol and a 50/50
   rank blend with momentum) under the production construction.
   Result: blend Sharpe 1.297 / CAGR 16.1% vs momentum-only 1.018 —
   a large, prior-backed improvement. **Status: UPGRADE CANDIDATE,
   NOT shipped.** Adoption requires the full validation battery
   (CPCV/PBO on the blend, SPA with the blend in the family, DSR
   context at the then-current ledger) and coincides with a deliberate
   clock restart — never a silent swap. Two ledger trials recorded.
3. **Post-tax lens**: STCG-approximation report (20.8% on FY-netted
   gains, loss carryforward) so the post-tax number is on record
   before real money. Reporting only; no strategy change.

## Rationale for stopping here

DSR 0.20 against the 89-trial ledger prices further in-sample research
at near-zero marginal credibility; the binding constraint is
out-of-sample time (the B1 clock), not ideas. C7 was admitted because
its prior predates this project's ledger (P2 measured both components
independently) and it cost two trials; the same bar applies to any
future addition.
