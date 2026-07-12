# Artha — Working Rules for Claude Code

## Phase tracker (update every session)
**Plan v2 (2026-07-11) adopted: research Track A first. P1 gate passed
2026-07-09; v2 section 5.0 acceptance audit PASSED 2026-07-12 (see
docs/research/p1-audit.md): 19-name Yahoo spot-check green (caught and
fixed combined bonus+split parsing and missing demerger/rights gap
factors — ADR 0005 addendum), security master built, universe overlap
evidenced. P1b gate PASSED 2026-07-13 (docs/research/p1b-event-data.md): 1.48M
announcements 2010+ with exchange timestamps (58.5% after 15:30 —
knowability rule implemented + tested), 157k board meetings 2012+;
bulk deals deferred (API truncates at 70 rows/window). Open: NIFTY 500
TRI source (synthetic TRI from div-yield column is the P2 fallback);
pre-2012-08 benchmark gap. Next: P2 vectorized backtester + cost model
+ baselines + lookahead suite.**

- [x] P0 scaffold · [x] P1 data layer · [ ] P2 vectorized backtest + baselines
- [ ] P3 ML alpha · [ ] P4 portfolio + risk · [ ] P5 event engine
- [ ] P6 live paper · [ ] P7 real capital

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
