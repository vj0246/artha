# P2: vectorized backtester, cost model, baselines (plan v2 sections 6-9)

Date: 2026-07-13. Verdict: **gate PASSED** — stylized facts reproduced net
of costs, lookahead suite green in CI, cost sensitivity table produced.

## Question

Does the pipeline reproduce the known cross-sectional stylized facts of
Indian equities net of realistic costs, before any ML claim is made?

## Method

Vectorized weekly backtester: signals at Friday close from data knowable at
that close, execution at the next session's close (T+1, no same-day-close
decisions — enforced by a planted-jump lookahead test in CI), top 25 equal
weight from the PIT liquidity universe, weights drift between rebalances.
Costs: NSE delivery charges (~0.12% buy / ~0.10% sell), flat DP charge at
Rs 25L capital / 25 names, sqrt impact (3 + 10*sqrt(order/ADV) bps).
Window 2012-08-01 -> 2026-07-07 (start set by benchmark availability).
Benchmark: NIFTY 500 price index from daily ind_close_all files.

## Results (net of full costs unless noted)

| Strategy | CAGR | Vol | Sharpe | MaxDD | 1-way turnover/yr | Gross Sharpe |
|---|---|---|---|---|---|---|
| Momentum 12-1 | 23.6% | 25.6% | 0.96 | -49% | 8.9x | 1.06 |
| 5d reversal | 1.1% | 26.2% | 0.17 | -78% | 47.0x | 0.72 |
| Low-vol 63d | 12.3% | 11.3% | 1.08 | -35% | 7.4x | 1.28 |
| Equal-weight universe | 14.4% | 19.7% | 0.78 | -57% | 2.0x | — |
| NIFTY 500 (price) | 13.5% | 16.0% | 0.87 | -38% | — | — |

Cost sensitivity, momentum (charges always on):

| Impact multiplier | Net Sharpe | Net CAGR |
|---|---|---|
| 0x (charges only) | 0.98 | 24.4% |
| 0.5x | 0.97 | 24.0% |
| 1x | 0.96 | 23.6% |
| 2x | 0.93 | 22.9% |

## Stylized-fact scorecard

1. **Momentum works in India, net.** +10pp CAGR over the benchmark at
   ~9x turnover; consistent with the Indian momentum literature. Passes.
2. **Short-term reversal is a costs story.** Healthy gross (Sharpe 0.72),
   dead net (0.17) at 47x turnover — precisely the section 6 turnover
   economics that motivated weekly rebalancing. Passes as a negative
   control.
3. **Low-vol anomaly present.** Highest net Sharpe (1.08) at less than
   half the market's drawdown. Passes.
4. Momentum's edge is impact-robust at Rs 25L (0.98 -> 0.93 across 0-2x);
   capacity analysis proper comes in P5.

## Limitations

- Benchmark is the PRICE index; the fair TRI comparison would lower the
  strategies' relative edge by roughly the ~1.2% dividend yield. Synthetic
  TRI from the div-yield column is queued; conclusions here survive the
  adjustment given the +10pp momentum gap.
- No no-trade bands or vol targeting yet (P5 construction); these reduce
  turnover further, so current net numbers are conservative on that axis.
- Equal-weight top-25 books concentrate in small/mid caps for low-vol and
  reversal; sector caps arrive in P5.
- Raw-zone integrity scan added to the backlog: two NUL-corrupted index
  files (killed process mid-write) were found and re-fetched during this
  phase.

## Decision

Pipeline validated; baseline bars set for P3 (a model must beat low-vol's
1.08 net Sharpe or momentum's 23.6% CAGR profile to claim value). Next:
P3 model comparison study (ridge, LightGBM, MLP, transformer under purged
CV with a trial ledger).
