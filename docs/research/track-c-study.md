# Track C: construction v2, SPA, regime gate — results

Date: 2026-07-19 (numbers below are the CLEAN-DATA rerun — see
"Data integrity find" at the end). Protocol identical throughout: momentum 12-1
selection, top 25, full Indian costs, T+1-close execution, Rs 25L,
caps + vol targeting, 2012-2026. All 13 configurations appended to the
trial ledger before results were read. Reports:
`construction_v2_20260719T162345Z.json`, `spa_20260719T162355Z.json`,
`regime_study_20260719T162407Z.json`.

## C2 + C3: construction v2 (Ledoit-Wolf weights x trading speed)

| config | Sharpe | CAGR | maxDD | turnover |
|---|---|---|---|---|
| equal + bands (P5 baseline) | 0.963 | 12.8% | −27.1% | 5.2x |
| ivol + bands | 1.024 | 13.6% | −26.8% | 5.5x |
| minvar + bands | 1.095 | 11.5% | −19.0% | 5.7x |
| equal + tau 0.25 | 0.952 | 13.2% | −32.1% | 2.5x |
| equal + tau 0.50 | 0.973 | 13.3% | −29.2% | 3.7x |
| equal + tau 0.75 | 0.975 | 13.2% | −27.5% | 4.6x |
| ivol + tau 0.50 | 1.027 | 14.1% | −29.2% | 3.9x |
| **minvar + tau 0.50 (shipped)** | **1.119** | 12.1% | **−21.2%** | **3.8x** |

Zero constraint violations in every configuration.

**The DeMiguel 1/N null is REJECTED on this book**: both risk-model
schemes beat equal weight, and the Ledoit-Wolf minimum-variance tilt is
the larger effect (+0.13 Sharpe, drawdown −27% -> −19%) — consistent
with Clarke-de Silva-Thorley: long-only min-var keeps the return and
sheds the vol. Gârleanu-Pedersen partial adjustment at tau 0.5 removes
~30% of turnover at unchanged-or-better Sharpe versus bands (bands'
bang-bang trading is the pure cost). The combined **minvar + tau 0.5 is
the new best construction: Sharpe 1.119, maxDD −21%, turnover 3.8x** —
sixteen hundredths of Sharpe and six drawdown points over the P5
config from construction alone, same signal, same costs. (The tainted
first run understated min-var at 1.055: phantom CA returns inflate
sample covariance noise, which is exactly what a shrunk min-var
punishes; cleaning the data widened its lead.)

**Deployment**: VJ approved the switch 2026-07-19.
production_constructor() (construct.py) is the single source of the
live configuration; paper day / weekly review / readiness consume it,
equal-bands history archived, B1 clock restarted on minvar+tau0.5.

## C1: Reality Check / SPA (family of 10 vs synthetic NIFTY 500 TRI)

Family: 8 construction-v2 configs + naive momentum + naive low-vol.
3,438 overlapping days, stationary bootstrap (21d mean block), 2,000
resamples.

- **White Reality Check p = 0.012**
- **Hansen SPA (consistent) p = 0.0445**
- Best by mean excess: naive momentum, +10.5%/yr over the TRI.

Reading: even after accounting for having tried the entire family, "no
strategy here beats the index" is rejected at 5%. This is the sharp
data-snooping test the deflated Sharpe approximates — and it lands on
the same side as the DSR (0.64) but with a cleaner conclusion, because
it measures cross-strategy dependence instead of assuming a Sharpe
variance. Caveats stated: the benchmark is the synthetic TRI, and the
family shares one selection signal, so this rejects snooping over
CONSTRUCTION variants + two baselines, not over all of quant.

## C4 + C6: regime gate — published NULL

826 of 3,460 days in a stressed state (bear / vol-stress / illiquidity).

| config | Sharpe | CAGR | maxDD | MAR |
|---|---|---|---|---|
| vol targeting only | 0.963 | 12.8% | −27.1% | 0.47 |
| + Daniel-Moskowitz gate | 0.914 | 11.6% | −22.6% | 0.51 |
| + Amihud crowding input | 0.882 | 11.1% | −22.4% | 0.49 |

The DM bear/stress gate buys ~4.5 drawdown points at a ~0.05 Sharpe
cost (MAR up slightly); the crowding input only subtracts. Conclusion:
**Barroso-Santa-Clara vol targeting, which the strategy already
carries, captures the crash-management premium on Indian long-only
momentum; an explicit regime gate on top is not worth its return drag.
Null published**, exactly as the plan's constraint 3 anticipated. The
gate machinery stays in the codebase (one dict argument) as the crisis
override lever for live risk management.

## Ledger and honesty

13 trials appended (8 construction, 3 regime, 2 baselines regenerated
for SPA context). The SPA test itself consumed the family rather than a
cherry-picked winner; the minvar+tau0.5 promotion claim should be read
against SPA p = 0.0445 for the family, not against a fresh single-trial
p-value.

## C5 (execution study): blocked on Kite credentials, foundation shipped
(per-fill orders_log + slippage report). Plan unchanged.

## Data integrity find (during deployment, 2026-07-19)

Wiring min-var into the live runbook produced uniform weights — Ledoit-
Wolf shrinkage had hit 1.0. The cause was upstream: the declared CA feed
carried a 1:5 TVSMOTOR split ex 2025-08-25 whose price never split,
manufacturing a phantom +398% adjusted return. apply_adjustment now
rejects material declared factors that the ex-day close/prev_close
ratio contradicts by more than 2.5x. The gate caught SIX phantom
declarations across the full history (TVSMOTOR, PCBL, KMSUGAR, UEL,
DRCSYSTEMS, ESSENTIA — each a declared 3x-10x event with a flat price).
Curated zone rebuilt; every Track C number above is from the clean
rerun. Equal-weight configs barely moved (phantom names are a tiny
equal slice); min-var strengthened materially, as expected when
covariance noise is removed. The failure would never have been caught
by backtest metrics alone — it surfaced because the risk model's
fail-safe (full shrinkage) looked wrong at deployment. Defense in
depth: the declared feed is now verified against prices, exactly as
ADR 0005 verified prices against the declared feed.
