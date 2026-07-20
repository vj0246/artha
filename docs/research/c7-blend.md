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

---

# Validation battery (2026-07-20): HOLD — unproven

`scripts/run_c7_validation.py`, report
`c7_validation_20260720T091128Z.json`, 5 ledger trials. Criteria were
fixed in the script docstring BEFORE the run (PBO < 0.5, stable in
>= 2 of 3 sub-periods, SPA p < 0.05, DSR improves).

## The weight sweep is a plateau, not a spike

| w (low-vol weight) | Sharpe | CAGR | vol | maxDD | turnover |
|---|---|---|---|---|---|
| 0.00 (pure momentum, live) | 1.018 | 13.7% | 13.6% | −28.3% | 4.2x |
| 0.25 | 1.232 | 16.1% | 12.8% | −24.5% | 5.8x |
| **0.50** | **1.297** | 16.1% | 12.1% | −30.3% | 6.2x |
| 0.75 | 1.248 | 14.0% | 11.0% | −29.8% | 5.9x |
| 1.00 (pure low-vol) | 1.050 | 10.1% | 9.6% | −29.0% | 4.7x |

Every interior weight beats both pure endpoints by 0.2+ Sharpe — a
smooth inverted-U, the signature of a real diversification effect
rather than a mined parameter.

## Sub-period stability: PASS

The blend beats momentum-only in all three disjoint regimes
(2012-16: 1.32 vs 0.82; 2017-20: 0.78 vs 0.77; 2021-26: 1.68 vs 1.37).

## PBO: 0.500 — FAIL (by the pre-registered rule)

Across 28 combinatorial purged splits, the in-sample winner landed in
the bottom half out-of-sample exactly half the time. Diagnostic
observation, offered as interpretation and NOT as a re-test: PBO here
measures whether picking the BEST WEIGHT generalizes, and on a plateau
of statistically indistinguishable configs (0.25/0.50/0.75) that
choice is inherently a coin flip. PBO 0.5 is therefore consistent both
with "blending helps but the exact weight is unidentified" and with
"the whole effect is noise" — it does not discriminate between them.
The sharper question (PBO over just {momentum, blend-0.5}) is
specified for the next quarterly re-validation. Running it now, after
seeing this result, would be precisely the p-hacking this project
exists to avoid.

## SPA: p = 0.655 — FAIL, and it corrects one of our own claims

Over the enlarged family of 13 CONSTRUCTED configurations (5 blend
weights + 8 construction-v2 variants), White RC p = 0.687 and Hansen
SPA p = 0.655: on raw excess return over the benchmark, after
snooping correction, none of them is distinguishable from the index.

This is not a contradiction of the Track C result (p = 0.0415) — it
explains it. **SPA tests mean EXCESS RETURN, not risk-adjusted
return.** The synthetic NIFTY 500 TRI returns 14.97% at 15.98% vol
over this window. The shipped constructed configuration deliberately
runs at 13.6% vol and below full investment (vol targeting), so its
raw CAGR of 13.7% sits slightly BELOW the index while its Sharpe
(1.02) sits above (0.94). The Track C rejection was therefore driven
by the naive, fully-invested momentum baseline in that family
(CAGR 23.6%), not by the shipped construction.

**The honest claim, restated**: the shipped book delivers better
risk-adjusted return and shallower drawdowns than the index, at lower
volatility and lower raw return. It does not, on this evidence,
deliver more raw return than the index after correcting for the number
of configurations tried. Every document quoting "family beats the
index, SPA p = 0.0415" has been amended to say which family and on
what metric.

## DSR: PASS (0.55 blend vs 0.18 momentum at 98 trials)

## Verdict: HOLD

Two of four pre-registered criteria failed. Production stays on
momentum + min-var + tau 0.5. The blend is recorded as an unproven
candidate with a specified decision path, not adopted. What would
change the verdict: the pre-registered two-config PBO at the next
quarterly re-validation, plus live out-of-sample evidence once the B1
clock has run.
