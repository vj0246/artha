# Artha — Working Rules for Claude Code

## Phase tracker (update every session)
**Plan v2 (2026-07-11) adopted: research Track A first. P1 gate passed
2026-07-09; v2 section 5.0 acceptance audit PASSED 2026-07-12 (see
docs/research/p1-audit.md): 19-name Yahoo spot-check green (caught and
fixed combined bonus+split parsing and missing demerger/rights gap
factors — ADR 0005 addendum), security master built, universe overlap
evidenced. P1b gate PASSED 2026-07-13 (1.48M announcements, knowability rule; bulk
deals deferred — API truncates at 70 rows/window). P2 gate PASSED
2026-07-13 (docs/research/p2-baselines.md): MarketSpec + NSE cost model,
weekly vectorized backtester (T+1-close execution), lookahead suite in
CI (planted-jump, scrambled-signal, registry audit). Stylized facts net
of costs 2012-2026: momentum 12-1 Sharpe 0.96/CAGR 23.6%, low-vol 1.08,
reversal killed by 47x turnover (gross 0.72 -> net 0.17), benchmark
0.87. P3 gate PASSED 2026-07-13 (docs/research/p3-model-study.md): 4 models,
48 purged folds + 28 CPCV combos. Ridge best (IC 0.043, net Sharpe 0.84,
DSR 0.998); transformer 0.89 on GPU; LGBM/MLP overfit fast signals
(PBO 0.86). NO model beats P2 momentum 0.96/low-vol 1.08 net — honest
null per plan 7.1. Synthetic TRI benchmarks + integrity scan shipped.
P4 core code started (taxonomy + event-study framework committed).
GPU note: CUDA torch via `uv pip install torch --index-url .../cu126
--reinstall`; `uv sync` reverts it; run with `uv run --no-sync`.
P4 gate PASSED 2026-07-13: 355k events, 81% audited taxonomy, PEAD
INVERTED in India, Model A vs B published null. P5 gate PASSED
2026-07-18 (docs/research/p5-portfolio-validation.md): constructed
momentum (caps/bands/ADV/vol-target 13.5%) — Sharpe 0.97, vol 13.45%
IN BAND, maxDD halved to -27%, zero constraint violations, capacity
flat to Rs 25Cr, beta 0.59/alpha 4%pa, DSR 0.64 @ 20 trials. Two bugs
caught by the gate run: vol-target feedback loop (scale by unscaled
book vol) and missing-ADV exit freeze (fail open). TRACK A COMPLETE 2026-07-18 (P0-P6; survivorship +2.5pp measured,
report + README + blog in repo). TRACK B BUILT 2026-07-18
(docs/research/p7-p9-track-b.md): P7 event engine + PARITY GATE in CI
(fractional agrees to <2e-5/day; integer bounded by rounding); P8 live
layer complete (PaperBroker, key-gated KiteAdapter, OMS with
idempotent ids + pre-trade checks, kill switch, reconcile, Telegram,
run_paper_day.py dry-run verified on real data) — 6-week paper clock
starts when the runbook is scheduled daily; P9 US portability smoke
passed (us_stub.py, pipeline unchanged). B4-B6 STRETCH DONE 2026-07-19
(docs/research/b4-b6-stretch.md): B4 futures hedge GATE PASSED
(residual beta -0.020; hedged 0.68 Sharpe/11% vol vs unhedged
0.82/13.2% — overlay is a risk dial, beta carried return); B5 read-only
dashboard (FastAPI + static page, scripts/run_dashboard.py); B6
research agent (AST-sandboxed DSL, seed/Groq proposer, ridge quick
screen — first run: 3 candidates, none beat library IC 0.0419).**

- [x] P0-P6 Track A · [x] P7 engine+parity · [x] P8 live build
  ([ ] 6-wk paper run — wall clock, needs daily scheduling)
- [x] P9 US smoke · Track B roadmap: docs/TRACK_B_PLAN.md
  ([x] B1 paper ops tooling → B2 Kite hardening (needs credentials) →
  B3 real capital · [x] B4 futures overlay · [x] B5 dashboard ·
  [x] B6 research agent)

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
