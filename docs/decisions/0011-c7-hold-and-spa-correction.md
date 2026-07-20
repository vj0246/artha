# ADR 0011: C7 blend held (unproven); SPA claim corrected

Date: 2026-07-20. Follows the pre-registered validation battery
required by ADR 0010 (`scripts/run_c7_validation.py`).

## Decision 1: the momentum+low-vol blend is NOT adopted

Two of four pre-registered criteria failed: PBO = 0.500 (gate < 0.5)
and family SPA p = 0.655 (gate < 0.05). Sub-period stability and DSR
passed. Production stays on momentum + LW min-var + tau 0.5.

The blend remains a documented candidate (docs/research/c7-blend.md)
with a specified decision path: a pre-registered two-config PBO
({momentum, blend-0.5}) at the next quarterly re-validation, plus live
out-of-sample evidence. Deliberately NOT re-tested now — inventing a
friendlier test after seeing a failed gate is the exact behavior this
project's ledger discipline exists to prevent.

## Decision 2: correct how the SPA result is stated everywhere

The Track C SPA rejection (p = 0.0415) was driven by the naive,
fully-invested momentum baseline present in that family (CAGR 23.6%),
not by the shipped construction. Re-running SPA over 13 CONSTRUCTED
configurations gives p = 0.655.

Cause, and it is not a bug: SPA tests mean EXCESS RETURN over the
benchmark. The shipped configuration deliberately runs at 13.6% vol
versus the index's 15.98% and below full investment (vol targeting),
so its raw CAGR (13.7%) sits below the index (14.97%) while its Sharpe
(1.02) sits above (0.94).

Consequently every document is amended to state the claim precisely:
the shipped book delivers better RISK-ADJUSTED return and shallower
drawdowns at lower volatility — not more raw return than the index
after snooping correction. A risk-adjusted-loss variant of SPA is
noted as possible future methodology, pre-registered for a future
re-validation rather than run now to recover a preferred answer.
