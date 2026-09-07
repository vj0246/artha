# ADR 0014: the live path did not match the research path — restart the B1 clock

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

Pulling that thread found two more live-vs-research parity breaks in the
same runbook, both in the same direction — the live log flattering itself:

- **No execution lag.** The runbook scored the book on `today`'s close and
  filled at `today`'s close. The backtester runs `exec_lag=1`, and the
  feature registry states the contract in as many words: "knowable at t's
  close and tradeable no earlier than t+1 (the backtester's execution lag
  enforces that side)". The live path did not enforce that side, so every
  position was bought at the very close whose prices generated the signal —
  one free day of momentum continuation per rebalance, recorded in the log
  that exists to be evidence FOR the research path. A real broker cannot
  fill at a close that has already happened.
- **Wrong ADV.** The participation cap and the cost model's impact term were
  fed a single session's raw traded value; the backtester feeds both a
  21-day rolling median. The live cap and live costs were therefore driven
  by a noisier input than anything that was validated.

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
2. Split the runbook's one date into two: the book is scored on
   `signal_date` (the previous session) and filled at `today`'s close.
   Signal, universe eligibility, risk inputs and ADV are all dated
   `signal_date`; only quotes and fills are dated `today`. Both dates are
   written to every log row, so the lag is auditable rather than asserted.
   ADV comes from `adv_median`, sharing `ADV_WINDOW` with the backtester by
   import so the two cannot drift apart again.
3. Pass the curated closes as the OMS reference prices.
4. Report the B1 clock as the consecutive streak; a gate metric must not
   flatter the thing it gates.
5. **Restart the B1 clock.** The 16 logged sessions are evidence about a
   process we no longer run, and the window already failed the gate's
   zero-missed-runs clause 18 times over. Book, order log and weekly review
   archived to `reports/paper/archive-dailyrebalance-20260907/`; the fresh
   clock starts at trade_date 2026-09-04, 25 positions, reconcile_ok, day
   1/30. Same convention as `archive-equalbands-20260719`.
6. Isolate `ARTHA_DATA_DIR` for the whole test suite. A plain `pytest` run
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
- The execution lag makes the live book trail the research book by one
  session at every rebalance, which is exactly the point: the weekly review's
  divergence number now measures real implementation slippage instead of a
  systematic one-day head start. Expect the fresh clock's divergence to be
  smaller AND more meaningful than the archived -2.06%.
- The missed-session problem is unchanged and remains VJ's: 18 of 34
  sessions in the old window were lost to a laptop that was off at 19:00.
  A 30-session streak needs the machine awake on every trading day, or an
  always-on host. This is now the binding constraint on B1, not the code.
