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
  correction history). DSR 0.20 vs 89-trial ledger — cite this.
- 10-finding code review 2026-07-20 fixed (fbceca4) + studies rerun.
- C7 blend candidate HELD (ADR 0011): PBO 0.500 + family SPA 0.655 failed
  the pre-registered gates. SPA claim corrected project-wide: the shipped
  book wins on RISK-ADJUSTED return (Sharpe 1.02 vs index 0.94), not raw
  excess return (13.7% vs 14.97% CAGR at lower vol).
- Scheduled tasks: artha-daily 19:00, artha-heartbeat 21:00,
  artha-weekly SAT 10:00, artha-monthly 1st 10:00, artha-quarterly.
  Laptop must be ON at 19:00 (and 21:00 for the heartbeat to fire).
- Track G (ops hygiene, ADR 0012): alerts are DURABLE (alerts.jsonl +
  severity, Telegram optional); run_heartbeat.py alarms on SILENCE (a
  cycle that never ran) -> health.json; dashboard health banner + alert
  feed. Never raise an alarm with a bare print — use safety.alert().
- WAITS ON VJ ONLY: Kite credentials (B2/C5/E4), funding >= Rs 2L (B3),
  GROQ_API_KEY (optional), laptop uptime at 19:00.
- Details: PROJECT_PLAN.md post-v2 changelog (authoritative history),
  TRACK_B/C/D/E/G_PLAN.md statuses, docs/research/ notes, ADRs 0001-0012,
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
