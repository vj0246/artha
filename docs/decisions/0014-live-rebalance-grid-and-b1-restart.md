# ADR 0014: the live rebalance grid was daily, not weekly — restart the B1 clock

Date: 2026-09-07
Status: accepted
Supersedes nothing; amends the B1 gate status in TRACK_B_PLAN.md.

## Context

`scripts/run_paper_day.py` decided whether to trade with

```python
today = cal.last                                    # latest curated session
is_rebalance_day = today in set(cal.week_last_days())
```

`week_last_days()` returns the last observed session of each ISO week. The
live calendar is built from curated data that ends at `today`, so `today` is
always the last observed session of its own (still-running) week. The
predicate was therefore **true on every session**: the paper book rebalanced
daily against a strategy researched, costed, and validated on a weekly grid.

The unit test for `week_last_days` was correct and green. The bug lived in
the one call site where the calendar's right edge is the present, and nothing
tested that call site. Every other caller (`vectorized.py`, the model study,
the research agent, the lookahead and parity suites) passes a full historical
panel, where the function means exactly what it says.

Evidence in the archived log: 16 of 16 logged sessions carry
`"rebalance": true`, including 2026-08-03 through 2026-08-07 — five
consecutive Monday-to-Friday rebalances. Position count drifted 25 -> 33 as
the tau-0.5 partial-adjustment exit tail was re-seeded daily instead of
weekly, and the 2026-09-05 weekly review reported cumulative divergence
-2.06% vs the research replay, breaking the 25 bps/week tolerance. The
mechanism is ~5x the researched turnover paying ~5x the researched costs.

Two smaller defects found in the same pass:

- `Oms(reference_prices=quotes)` handed the OMS the same dict object the
  paper broker quotes from, so the pre-trade price-band check compared a
  number with itself and could never fire. It is the only guard against a
  bad Kite tick, and it was dead exactly where B2 will need it.
- The heartbeat reported `b1_progress` as the raw logged-row count. With 16
  rows and 18 holes it displayed "16/30" for a gate that requires 30
  *consecutive* sessions; the true streak was 1.

## Decision

1. Replace the live predicate with `TradingCalendar.is_live_rebalance_day`,
   which is decidable at the close with no knowledge of future sessions:
   trade on Friday (the last session of every normal NSE week), or whenever
   five sessions have passed since the last rebalance. The session-count
   clause means a Friday holiday shifts that week's rebalance to the next
   session rather than skipping the week, and it also caps the cadence after
   a machine-off gap. Regression-tested by replaying the calendar one
   session at a time, exactly as the runbook sees it.
2. Pass the curated closes as the OMS reference prices.
3. Report the B1 clock as the consecutive streak; a gate metric must not
   flatter the thing it gates.
4. **Restart the B1 clock.** The 16 logged sessions are evidence about a
   process we no longer run, and the window already failed the gate's
   zero-missed-runs clause 18 times over. Book, order log and weekly review
   archived to `reports/paper/archive-dailyrebalance-20260907/`; the fresh
   clock starts at trade_date 2026-09-04, 25 positions, reconcile_ok, day
   1/30. Same convention as `archive-equalbands-20260719`.
5. Isolate `ARTHA_DATA_DIR` for the whole test suite. A plain `pytest` run
   was appending to the live `alerts.jsonl` — 13 rows, five of them
   "KILL SWITCH: trading frozen" — inflating the very critical count the
   heartbeat reports. The historical file is append-only and is left as is;
   its pre-2026-09-07 critical count is known to include test artifacts.

## Consequences

- B1 completion moves out by the length of a fresh 30-session clock
  (~6 calendar weeks at full attendance). Nothing downstream (B2 gate, B3
  go-live) was reachable on the old evidence anyway.
- Production construction is unchanged: `production_constructor()` still
  returns LW min-var + GP tau 0.5. This ADR changes *when* the live path
  trades, restoring it to what Track C actually validated. No re-run of the
  research studies is required, because the research path never had the bug.
- The missed-session problem is unchanged and remains VJ's: 18 of 34
  sessions in the old window were lost to a laptop that was off at 19:00.
  A 30-session streak needs the machine awake on every trading day, or an
  always-on host. This is now the binding constraint on B1, not the code.
