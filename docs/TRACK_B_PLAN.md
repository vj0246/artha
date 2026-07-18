# TRACK_B_PLAN v1 (2026-07-18)

Operational and stretch roadmap for the built Track B stack. Supersedes the
one-line P7-P9 rows of PROJECT_PLAN v2 section 14 with concrete phases,
gates, and improvements found during the build. Same discipline as Track A:
one phase (or sub-slice) per session, no phase before the prior gate,
plan changes via ADR.

Already done (2026-07-18): event engine + parity gate in CI (P7), live
layer build with dry-run-verified daily runbook (P8 build), US portability
smoke (P9). What follows is what remains.

---

## B1: Paper operations (6+ weeks wall clock; ~1 session of tooling first)

Goal: turn the runbook into an unattended daily operation and accumulate
the clean-paper evidence the real-money gate requires.

Tooling slice (build before the clock starts):
1. `scripts/run_daily_cycle.py` — one entrypoint chaining incremental
   bhavcopy/indexclose/events backfill -> curated rebuild (incremental:
   only the new days' parquet partitions) -> integrity scan ->
   `run_paper_day` -> Telegram summary. Idempotent; safe on holidays
   (backfill 404s, runbook no-ops on non-sessions).
2. Windows Task Scheduler registration doc + `schtasks` one-liner
   (19:00 IST daily). VJ runs the registration (deferred to-do #1).
3. Weekly review script: paper-log -> equity curve vs backtest
   expectation for the same dates (the vectorized loop replayed over the
   live window), divergence attribution (universe drift, fill timing,
   integer shares), constraint/violation summary.
4. Vol-targeting input: wire the paper log's trailing book returns into
   the constructor (currently None until 21 days accumulate).

Improvements over the v1 spec:
- Divergence-vs-backtest tracking from day 1 (the plan only demanded
  slippage-vs-model, which is degenerate for close-fill paper; comparing
  the LIVE path against the RESEARCH path over the same dates is the real
  parity-in-production test and directly rehearses the P8 gate metric).
- Curated rebuild must become incremental (full rebuild is ~15 min; a
  daily job should append the new day in seconds). Sub-slice: partition-
  append mode in build_curated + panel refresh limited to affected dates.

Gate B1: 30 consecutive logged sessions with zero reconciliation breaks,
zero unexplained divergence vs the research path (> 25bps/week
unattributed), zero missed runs (holiday no-ops excluded).

## B2: Kite integration hardening (~1 session + VJ's credentials)

1. Access-token morning flow: `scripts/kite_login.py` (request token ->
   access token exchange; manual browser step documented — automation is
   a ToS question, keep manual).
2. Live-quote source for the paper adapter (Kite LTP) so paper fills use
   real intraday prices near the close -> realized-vs-modeled slippage
   becomes measurable (the original P8 gate metric activates here).
3. Reconcile against the real account (read-only first: holdings/cash
   comparison runs for a week before any order is ever sent).
4. Verify-list closure: current charge schedule vs NSECostModel
   constants, SEBI retail-algo thresholds, Kite ToS on order tagging.

Gate B2: one week of read-only reconciliation against the live account
with zero mismatches; verify-list items confirmed and dated in the plan.

## B3: Real capital go-live (after B1 + B2 gates)

Rs 1-2L, the section 11 risk limits active (drawdown de-risking rules
enforced by the runbook, not just reported), kill-switch drill executed
deliberately in week one (freeze + flatten on paper first, then a
one-share live drill). Weekly realized-vs-modeled slippage report feeds
back into the impact model constants.

Gate B3: 4 weeks live with slippage within 2x model and zero manual
interventions other than the scheduled token login.

## B4: NIFTY futures hedge overlay (stretch, ~2 sessions)

F&O bhavcopy ingest (UDiFF derivatives file, same raw-zone discipline),
front-month futures series with rollover, basis and margin model,
beta-hedge sizing from the P5 attribution beta (0.59), hedged tearsheet.
Gate: hedged backtest beta within +/-0.1 of zero; net Sharpe reported
honestly vs unhedged.

## B5: Dashboard (stretch, ~2 sessions)

FastAPI read-only API over reports/ + curated artifacts; Next.js 14 app:
equity curves, paper log, risk reports, constraint history, ledger
browser. No writes, no auth complexity (localhost first).

## B6: Research agent (stretch, ~2 sessions)

LangGraph loop: propose feature spec -> generate feature fn into a
sandboxed module -> run the standard purged evaluation -> append to the
trial ledger (DSR stays honest automatically). Offline only. First
assignment: the parked daily-horizon event-reversal trial (P4's t=-6.9
fade).

## Parked items owned by VJ (tracked, not scheduled)

1. Register the daily task (starts B1's clock).
2. Zerodha account + KITE_API_KEY/KITE_ACCESS_TOKEN (unlocks B2).
3. GROQ_API_KEY (LLM taxonomy upgrade), liquid-fund yield on idle cash,
   TRI source watch.

## Sequencing

B1 tooling -> [clock runs] -> B2 (parallel with the B1 clock once
credentials exist) -> B3. B4-B6 any time after B1 tooling, by interest.
