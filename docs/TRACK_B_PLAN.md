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

Status 2026-07-19: all code slices built ahead of credentials —
scripts/kite_login.py (manual browser step by design),
KiteAdapter.ltp_many + key-gated LTP overlay in run_paper_day (falls
back to curated closes on any failure; quote_source logged per day),
scripts/run_reconcile_readonly.py (never places orders; appends
reconcile_readonly.jsonl). Verify-list confirmed 2026-07-19 against
zerodha.com/charges: brokerage 0, STT 0.1% both sides, stamp 0.015%
buy, SEBI Rs 10/crore, DP Rs 15.34/scrip sell, GST 18% on
(brokerage+SEBI+txn) — all match; NSE transaction charge drifted
0.00297% -> 0.00307%, constant updated. SEBI retail-algo framework
(circular 2025-02-04, effective 2026-04-01): below 10 orders/sec per
exchange = regular API user, no algo registration — artha's ~25 EOD
orders/week is orders of magnitude under; note broker API now requires
static-IP whitelisting + 2FA (part of VJ's Kite setup). Kite order tag
limit 20 chars — client_order_id[:20] already enforced. GATE ITSELF
waits on VJ's credentials + a funded account.

## B3: Real capital go-live (after B1 + B2 gates)

Rs 1-2L, the section 11 risk limits active (drawdown de-risking rules
enforced by the runbook, not just reported), kill-switch drill executed
deliberately in week one (freeze + flatten on paper first, then a
one-share live drill). Weekly realized-vs-modeled slippage report feeds
back into the impact model constants.

Gate B3: 4 weeks live with slippage within 2x model and zero manual
interventions other than the scheduled token login.

Status 2026-07-19: safety slices built and rehearsed ahead of the
gates — drawdown de-risk ENFORCED in run_paper_day (10% from peak
halves gross, 15% freezes; unit-tested; gross_scalar logged daily);
kill-switch drill executed on a synthetic scratch book at real prices
(scripts/run_kill_drill.py: freeze -> flatten -> 3 positions to 0,
PASS, evidence in kill_drills.jsonl; real paper state untouched);
realized-vs-modeled slippage report (scripts/run_slippage_report.py
over the new per-fill orders_log.jsonl — currently degenerate by
construction with close-fill quotes, activates with B2's kite_ltp).
GATE ITSELF waits on B1 + B2 gates + funded capital.

## B4: NIFTY futures hedge overlay (stretch, ~2 sessions)

F&O bhavcopy ingest (UDiFF derivatives file, same raw-zone discipline),
front-month futures series with rollover, basis and margin model,
beta-hedge sizing from the P5 attribution beta (0.59), hedged tearsheet.
Gate: hedged backtest beta within +/-0.1 of zero; net Sharpe reported
honestly vs unhedged.

Status 2026-07-19: built (fo.py ingest both formats, front-month series
with same-contract rolls, lagged rolling-beta overlay with per-side +
roll costs). Basis/margin model simplified to a cost-rate model; margin
financing stated as a limitation. GATE PASSED 2026-07-19
(scripts/run_hedge_study.py): residual beta -0.020 (< 0.1), mean beta
0.58, hedged 0.68 Sharpe / 11.0% vol vs unhedged 0.82 / 13.2% over
2021-2026 — beta carried real return; overlay is a risk dial, not an
always-on default. See docs/research/b4-b6-stretch.md.

## B5: Dashboard (stretch, ~2 sessions)

FastAPI read-only API over reports/ + curated artifacts; Next.js 14 app:
equity curves, paper log, risk reports, constraint history, ledger
browser. No writes, no auth complexity (localhost first).

Status 2026-07-19: shipped v1 as FastAPI + one dependency-free static
page (src/artha/dashboard/, scripts/run_dashboard.py) instead of
Next.js — zero node toolchain for a localhost read-only tool. Next.js
remains the upgrade path if the dashboard grows interactive.

## B6: Research agent (stretch, ~2 sessions)

LangGraph loop: propose feature spec -> generate feature fn into a
sandboxed module -> run the standard purged evaluation -> append to the
trial ledger (DSR stays honest automatically). Offline only. First
assignment: the parked daily-horizon event-reversal trial (P4's t=-6.9
fade).

Status 2026-07-19: shipped as a plain loop, not LangGraph (single
linear propose->screen->ledger pass needs no graph state). Sandbox is
an AST-whitelisted expression DSL rather than free codegen — narrower
but auditable. Proposer: deterministic seeds offline, Groq gated on
GROQ_API_KEY. First offline run screened 3 candidates vs the library
baseline (IC 0.0419): best delta +0.0002 — none admitted. The
event-reversal first assignment stays parked with VJ's item 3 (it needs
the event-feature join, not the price DSL).

## Parked items owned by VJ (tracked, not scheduled)

1. Register the daily task (starts B1's clock).
2. Zerodha account + KITE_API_KEY/KITE_ACCESS_TOKEN (unlocks B2).
3. GROQ_API_KEY (LLM taxonomy upgrade), liquid-fund yield on idle cash,
   TRI source watch.

## Sequencing

B1 tooling -> [clock runs] -> B2 (parallel with the B1 clock once
credentials exist) -> B3. B4-B6 any time after B1 tooling, by interest.
