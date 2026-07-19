# ADR 0006: adopt Track C (research v2 extensions)

Date: 2026-07-19. Written at VJ's direction after Track A and Track B
completed and all wall-clock gates were handed to their owner.

## Decision

Adopt `docs/TRACK_C_PLAN.md` as the next execution plan: C1 SPA/Reality
Check, C2 Ledoit-Wolf construction, C3 Gârleanu-Pedersen partial
adjustment, C4+C6 regime/crowding gate, C5 execution study (blocked on
Kite credentials). Full rationale and sources live in the plan; this ADR
records the decision and its constraints.

## Constraints carried over unchanged

1. Identical backtest protocol (T+1-close execution, full Indian costs,
   PIT universe) for every comparison; no upgrade ships on gross numbers.
2. Every configuration run is appended to the trial ledger BEFORE its
   result is read. C1's SPA test and the existing DSR both depend on the
   ledger counting losers.
3. Nulls are published as nulls. DeMiguel et al. (2009) makes "1/N
   survives" a publishable C2 outcome; Daniel-Moskowitz makes "vol
   targeting already captures the crash premium" a publishable C4 one.
4. No new dependencies beyond numpy/scipy already present (C2's min-var
   uses closed-form LW + long-only clip, not a QP solver — heuristic
   disclosed in the plan).

## Why now

The shipped strategy's remaining ad-hoc components (equal weight, 25%
no-trade band) each have a literature-standard replacement with a
directly measurable net effect, and the statistics gap (max-Sharpe
deflation without cross-trial dependence) has a standard fix. These are
the highest evidence-per-effort items available without credentials or
wall clock.
