# P5: portfolio construction, validation, risk (plan v2 sections 8, 10, 11)

Date: 2026-07-18. Verdict: **gate PASSED** — constraints verified on all
~720 rebalances (zero violations), vol targeting in band, full tearsheet
with attribution, regimes, capacity, and risk artifacts produced.

## Construction stack (momentum 12-1, Rs 25L)

Top-25 -> position cap 6%, sector cap 25% (current-sector map; UNKNOWN
uncapped by design), 25% no-trade bands, ADV participation cap 2%, vol
target 13.5% using max(21d, 63d) FULLY-INVESTED book vol, long-only, cash
remainder.

Two real bugs the gate run itself exposed, both fixed with regression
tests:

1. **Vol-targeting feedback loop** — scaling by the scaled portfolio's own
   vol snaps gross back to 1 as soon as vol hits target; the estimator now
   measures the unscaled book (portfolio return / gross exposure).
2. **Missing-ADV exit freeze** — names rotating out had no ADV entry, the
   participation cap read that as max_move 0, exits froze, gross pinned at
   1.0 and silently erased vol targeting. Missing ADV now fails open;
   the backtester passes its persistent ADV map.

## Tearsheet (2012-08 -> 2026-07, net of full costs)

| | Constructed momentum | Naive momentum (P2) | NIFTY 500 syn-TRI | EW universe |
|---|---|---|---|---|
| CAGR | 12.9% | 23.6% | 14.4% | 15.7% |
| Vol | **13.5%** | 25.6% | 16.0% | 19.7% |
| Sharpe | 0.97 | 0.96 | 0.95 | 0.78 |
| MaxDD | **-27.1%** | -49.2% | -38.3% | -56.9% |
| Sortino | 0.84 | — | — | — |
| Calmar | 0.47 | 0.44 | — | — |
| Turnover | 5.2x | 8.9x | — | — |

The construction stack converts the same signal into half the drawdown at
the same Sharpe: exactly what construction is for. Absolute CAGR drops
with gross (cash earns 0% in v1 — a liquid-fund yield would add back
~1.5-2pp on the ~40% average cash balance).

- Vol targeting: median trailing 21d vol 11.8%, 84% of days <= 17%,
  full-sample 13.45% vs 13.5% target. IN BAND.
- Regimes: Sharpe 0.60 (2012-16), 0.66 (2017-20, contains the crash),
  1.23 (2021-26). Positive in all three.
- Attribution vs synthetic TRI: beta 0.59, annualized alpha 4.0%
  (t = 1.55), correlation 0.70. Half the book's risk is idiosyncratic.
- DSR 0.64 against 20 ledger trials.

## Risk artifacts

- VaR(95/99) 1.4%/2.7% historical; Cornish-Fisher close (fat tails mild
  after vol targeting). CVaR(95) 2.2%.
- Drawdown rules: 652 days would have run at half gross, 416 flat
  (2020 crash dominates); worst 21d window -19.9% (Mar 2020).
- Liquidity: worst name liquidates in < 0.01 days at 20% ADV at Rs 25L.
- Capacity: Sharpe 0.97 flat through Rs 25Cr, 0.92 at Rs 100Cr — the
  liquidity-filtered universe absorbs institutional-adjacent capital;
  DP/impact drag only bites at the top level.

## Decision

Production candidate: constructed momentum 12-1 as specified. Remaining
Track A phase: P6 — the research report assembling P1-P5 notes, plus the
survivorship before/after demonstration.
