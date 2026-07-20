# C7: momentum + low-vol blend — upgrade candidate found

Date: 2026-07-20. Report `c7_blend_20260720T053924Z.json`; two ledger
trials. Protocol: production construction (LW min-var + tau 0.5, full
costs, Rs 25L, 2012-2026), signals swapped only.

| signal | Sharpe | CAGR | vol | maxDD | turnover |
|---|---|---|---|---|---|
| momentum 12-1 (live) | 1.018 | 13.7% | 13.6% | −28.3% | 4.2x |
| low-vol 63d, pure | 1.037 | 9.9% | 9.5% | −29.7% | 4.7x |
| **50/50 rank blend** | **1.297** | **16.1%** | 12.1% | −30.3% | 6.2x |

## Why this was a legitimate trial (and only two)

The prior predates this project's search: P2 measured momentum (0.96)
and low-vol (1.08) as independent baselines in the very first study,
and the two signals are classically complementary (momentum earns in
trends, low-vol in churn; their pick overlap is small). The blend is
the single obvious combination, pre-registered in ADR 0010 before the
result was read.

## Reading

The diversification is real: the blend's Sharpe (1.30) exceeds BOTH
components by more than either exceeds the other, at vol between them
— the signature of genuinely decorrelated pick streams rather than a
lucky reweighting. Cost drag from the higher turnover (6.2x) is
already inside the net numbers.

## Status: CANDIDATE, NOT SHIPPED

Discipline holds: before the blend can replace momentum in
production_constructor it must pass the full battery on its own —
CPCV/PBO on the blend signal, SPA with the blend added to the strategy
family, DSR against the then-current ledger — and adoption coincides
with a deliberate B1 clock restart. The honest framing for the report:
a strong in-sample candidate with a clean prior, awaiting the same
scrutiny that revised min-var's own headline from 1.119 to 1.018.
