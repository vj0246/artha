# Track C: construction v2, SPA, regime gate — results

Date: 2026-07-19. Protocol identical throughout: momentum 12-1
selection, top 25, full Indian costs, T+1-close execution, Rs 25L,
caps + vol targeting, 2012-2026. All 13 configurations appended to the
trial ledger before results were read. Reports:
`construction_v2_20260719T151054Z.json`, `spa_20260719T151108Z.json`,
`regime_study_20260719T151123Z.json`.

## C2 + C3: construction v2 (Ledoit-Wolf weights x trading speed)

| config | Sharpe | CAGR | vol | maxDD | turnover |
|---|---|---|---|---|---|
| equal + bands (shipped P5) | 0.960 | 12.7% | 13.4% | −27.1% | 5.2x |
| ivol + bands | 1.020 | 13.6% | 13.4% | −26.8% | 5.5x |
| minvar + bands | 1.037 | 11.1% | 10.7% | −19.0% | 5.7x |
| equal + tau 0.25 | 0.951 | 13.2% | 14.0% | −32.1% | 2.5x |
| equal + tau 0.50 | 0.972 | 13.3% | 13.8% | −29.2% | 3.7x |
| equal + tau 0.75 | 0.974 | 13.2% | 13.7% | −27.5% | 4.6x |
| ivol + tau 0.50 | 1.025 | 14.1% | 13.8% | −29.2% | 3.9x |
| **minvar + tau 0.50** | **1.055** | 11.7% | 11.0% | **−21.2%** | **3.8x** |

Zero constraint violations in every configuration.

**The DeMiguel 1/N null is REJECTED on this book**: both risk-model
schemes beat equal weight, and the Ledoit-Wolf minimum-variance tilt is
the larger effect (+0.08 Sharpe, drawdown −27% -> −19%) — consistent
with Clarke-de Silva-Thorley: long-only min-var keeps the return and
sheds the vol. Gârleanu-Pedersen partial adjustment at tau 0.5 removes
~30% of turnover at unchanged-or-better Sharpe versus bands (bands'
bang-bang trading is the pure cost). The combined **minvar + tau 0.5 is
the new best construction: Sharpe 1.055, maxDD −21%, turnover 3.8x** —
a tenth of Sharpe and six drawdown points over the shipped P5 config
from construction alone, same signal, same costs.

**Deployment note**: the live paper book stays on equal+bands until the
B1 30-session clock completes — switching construction mid-clock would
invalidate the live-vs-research replay. Adopting minvar+tau0.5 for
paper is a one-line change (Constructor(scheme="minvar",
trade_speed=0.5)) plus a clock restart; owner: VJ's call.

## C1: Reality Check / SPA (family of 10 vs synthetic NIFTY 500 TRI)

Family: 8 construction-v2 configs + naive momentum + naive low-vol.
3,438 overlapping days, stationary bootstrap (21d mean block), 2,000
resamples.

- **White Reality Check p = 0.0125**
- **Hansen SPA (consistent) p = 0.046**
- Best by mean excess: naive momentum, +10.3%/yr over the TRI.

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
| vol targeting only (shipped) | 0.960 | 12.7% | −27.1% | 0.47 |
| + Daniel-Moskowitz gate | 0.911 | 11.6% | −22.6% | 0.51 |
| + Amihud crowding input | 0.879 | 11.0% | −22.4% | 0.49 |

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
against SPA p = 0.046 for the family, not against a fresh single-trial
p-value.

## C5 (execution study): blocked on Kite credentials, foundation shipped
(per-fill orders_log + slippage report). Plan unchanged.
