# Artha — Working Rules for Claude Code

## Phase tracker (update every session)

**ALL FIVE TRACKS EXECUTED as of 2026-07-20.** Current state:

- Track A (P0-P6 research) COMPLETE; Track B (P7-P9 + B1-B6 production)
  BUILT with live paper ops running (daily 19:00 task, B1 clock day 1 =
  2026-07-19 on minvar+tau0.5); Track C (construction v2 + SPA) EXECUTED;
  Track D (single-name lab, ICICIBANK) COMPLETE with 4 nulls + the
  leaky-decomposition exposure; Track E (adaptive estimation) EXECUTED
  (E1 null, E2 signal-health live, E3 schedules registered).
- Production config: production_constructor() = LW minvar + GP tau 0.5,
  Sharpe 1.018 net (post-hardening; ADR 0008 has the 1.119->1.018
  correction history). DSR 0.20 vs the 89-trial ledger as published in the
  report; the E2 monitor's live refresh reads 0.163 vs 111 trials
  (2026-09-06) as scheduled re-runs keep adding trials. Cite the published
  pair for the report, the live pair for current state — never mix them.
- 10-finding code review 2026-07-20 fixed (fbceca4) + studies rerun.
- C7 blend candidate HELD (ADR 0011): PBO 0.500 + family SPA 0.655 failed
  the pre-registered gates. SPA claim corrected project-wide: the shipped
  book wins on RISK-ADJUSTED return (Sharpe 1.02 vs index 0.94), not raw
  excess return (13.7% vs 14.97% CAGR at lower vol).
- Scheduled tasks: artha-daily 19:00, artha-heartbeat 21:00,
  artha-weekly SAT 10:00, artha-monthly 1st 10:00, artha-quarterly.
  Laptop must be ON at 19:00 (and 21:00 for the heartbeat to fire).
  REGISTER ONLY VIA `scripts/register_tasks.ps1` — never `schtasks /TR`.
  2026-07-22: all five tasks had been silently broken since registration.
  The shell stripped the quotes around a repo path containing spaces, so
  Windows stored Execute=`...\Desktop\Personal` + Arguments=`Projects\...`
  and every run failed 0x80070002 while the task still displayed "Ready".
  The heartbeat's staleness alarm is what caught it (68h no cycle).
  Run the script ELEVATED for the S4U principal; unelevated it falls back
  to Interactive (works only while logged in). A long cycle launched by
  hand into a transient console can die 0xC000013A — start the B1 clock
  with a direct `uv run` instead, not `schtasks /Run`.
- B1 clock RESTARTED 2026-09-07 (ADR 0014). Attempt one (2026-07-21 ->
  2026-09-04) FAILED the gate: 18 of 34 sessions missed (laptop off at
  19:00) and -2.06% divergence vs the research path, because
  `today in cal.week_last_days()` is true on EVERY session when the
  calendar ends at today — the book rebalanced DAILY against a weekly
  strategy. Use `TradingCalendar.is_live_rebalance_day` for any live
  grid decision; `week_last_days()` is only correct on a full historical
  panel. Same pass fixed two more live-vs-research breaks: the runbook
  scored and filled on the SAME close (no exec_lag=1) and fed the ADV cap
  a single session's traded value instead of the 21-day median. The
  runbook now carries TWO dates — scored on `signal_date` (previous
  session), filled at `today` — and logs both. Anything read for the
  DECISION must be dated signal_date; only quotes and fills use today.
  Attempt two: day 1 = trade_date 2026-09-04 (signal 2026-09-03), 25
  positions, reconcile_ok, 0 rejects. Binding constraint is machine uptime.
- Heartbeat `b1_progress` is the CONSECUTIVE streak (the gate metric),
  not the row count. `alerts.jsonl` criticals before 2026-09-07 include
  test-suite artifacts; the suite now isolates ARTHA_DATA_DIR
  (tests/conftest.py) so a pytest run no longer writes the live ledger.
- Signal health as of 2026-09-06: IC 63d 0.040 / 252d 0.041 healthy, PSI
  worst 0.089 (the 0.61 dist_52w_low drift cleared after the
  outlier-robust PSI fix, 382baa5), DSR 0.163 vs a 111-trial ledger.
- Track H (RL, ADR 0013): RL is CONTROL not prediction here. H1 null —
  LinUCB tau control ties the fixed constant, PBO 0.93, flat objective
  surface. H2 live — research agent learns idea-family value from the
  ledger (artha/agent/memory.py + artha/rl/bandits.py), never touches
  the live book. Do NOT add a return-predicting RL agent (D3 + DSR 0.20).
- Track G (ops hygiene, ADR 0012): alerts are DURABLE (alerts.jsonl +
  severity, Telegram optional); run_heartbeat.py alarms on SILENCE (a
  cycle that never ran) -> health.json; dashboard health banner + alert
  feed. Never raise an alarm with a bare print — use safety.alert().
- WAITS ON VJ ONLY: Kite credentials (B2/C5/E4), funding >= Rs 2L (B3),
  GROQ_API_KEY (optional), laptop uptime at 19:00.
- Details: PROJECT_PLAN.md post-v2 changelog (authoritative history),
  TRACK_B/C/D/E/G/H_PLAN.md statuses, docs/research/ notes, ADRs 0001-0013,
  HANDBOOK.md (full onboarding), SYSTEM_OVERVIEW.md.
- GPU note: CUDA torch via `uv pip install torch --index-url .../cu126
  --reinstall`; `uv sync` reverts it; always `uv run --no-sync`.

## Rules
1. Read `docs/PROJECT_PLAN.md` first. It is authoritative. When reality disagrees
   with the plan, change the plan in a commit, never silently in code.
2. Never start a phase before the prior gate passes (plan §14). Gates are
   automated in `tests/` wherever possible.
3. Any plan decision change → short ADR in `docs/decisions/` before session ends.
4. Zero lookahead tolerance. From P2 onward the lookahead suite in
   `tests/lookahead/` must stay green in CI.
5. Uncertain external facts (fees, SEBI rules, API pricing, format cutovers) live
   in plan Appendix B. Verify with current sources before relying; record the
   confirmation date next to the item.
6. Global personal standards from `~/.claude/CLAUDE.md` apply (typed, tested,
   simplicity first, surgical changes).

## Commands
- Setup: `uv sync`
- Local gate (all must pass): `uv run ruff format --check .` ·
  `uv run ruff check .` · `uv run mypy` · `uv run pytest`
- Hooks: `uv run pre-commit run --all-files`

## Stack
Python 3.12 (uv-managed), polars, DuckDB + Parquet, pydantic v2, LightGBM (P3+),
pytest + hypothesis, ruff (lint + format), mypy --strict, GitHub Actions.

## Environment facts
- Windows 11. Repo lives inside OneDrive (`Personal Projects\Quant\artha`).
  Consequence: bulk data never lives in the repo. Data root defaults to
  `~\quant-data` (outside OneDrive), override via `ARTHA_DATA_DIR`; raw zone
  is immutable with a sha256 manifest. GitHub is the backup of record.
- GPU: RTX 2050, 4 GB VRAM. Transformer stretch (plan §15.2) limited to small
  models with small batches; LightGBM primary is CPU-bound and unaffected.
- Broker: none yet. Zerodha Kite planned at P6 (verify-list items first).

## Directory map
- `src/artha/{marketspec,data,features,labels,models,portfolio,backtest,risk,live,news,reports}`
- Tests: `tests/{unit,integration,lookahead,parity}`
- Plan: `docs/PROJECT_PLAN.md` · ADRs: `docs/decisions/` · Runners: `scripts/`
