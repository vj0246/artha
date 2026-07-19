# Artha Handbook — complete onboarding for a new maintainer

Purpose of this document: a person who has never spoken to VJ or read
any conversation should be able to understand every design choice,
navigate every file, rebuild the system from an empty machine, and
carry the project forward. Companion docs — PROJECT_PLAN.md (the
authoritative plan; its execution changelog is the project's history),
SYSTEM_OVERVIEW.md (condensed map), RUNBOOK.md (daily operations),
docs/decisions/ (ADRs: every irreversible choice with its evidence),
docs/research/ (one note per completed study). When this handbook and
the code disagree, the code is right and this file has a bug — fix it.

---

## 1. What this project is, and the choices that shaped it

Artha researches, validates, and operates a systematic equity strategy
on NSE cash equities at Rs 0 data cost. The production strategy is
weekly-rebalanced cross-sectional momentum, packaged through
institutional portfolio construction (Ledoit-Wolf minimum-variance
weights, Garleanu-Pedersen partial-adjustment trading, volatility
targeting, position/sector/ADV caps), traded automatically every
evening on a paper book, with real-money gates defined and quantified.

Foundational choices, each with its "why":

- **EOD, weekly rebalance** — free data is end-of-day; transaction
  costs kill faster signals (measured: 47x-turnover reversal went 0.72
  gross -> 0.17 net). Intraday/HFT is explicitly out of scope.
- **Primary exchange sources only** — bhavcopies, the declared CA
  feed, exchange announcements. Vendor data costs money and hides its
  survivorship; ours is survivorship-free by construction and the bias
  was MEASURED (+2.5pp/yr fake CAGR on a survivor-only universe).
- **Point-in-time discipline everywhere** — a feature registry with
  knowability rules, a lookahead test suite in CI (planted-jump,
  scrambled-signal), purged/embargoed cross-validation, T+1-close
  execution. The most valuable findings here are nulls, and nulls are
  only believable if leakage is structurally impossible.
- **Every experiment is a ledger row** — reports/ledger.jsonl is
  append-only; deflated Sharpe and the SPA test read the trial count
  from it. An experiment that is not in the ledger does not exist.
- **Data outside the repo** — ~/quant-data (override ARTHA_DATA_DIR),
  because the repo lives in OneDrive and bulk data must not sync. Raw
  zone is immutable with a sha256 manifest; curated is rebuildable.
- **Plan-first governance** — no phase before the prior gate; plan
  changes happen in commits; decision reversals need an ADR.

Headline results (all net of full Indian costs, details in
docs/research/): production construction Sharpe 1.12 / maxDD -21%;
family beats the index with Hansen SPA p = 0.0445; cross-sectional ML
null (PBO 0.86); inverted Indian PEAD (t = -6.9); decomposition
preprocessing exposed as 100% look-ahead (leaky IC 0.41 -> causal
-0.04); futures hedge gate passed (residual beta -0.02) but shipped as
a risk dial; six phantom corporate actions caught by the CA sanity
gate.

## 2. Repository map — every folder, every file

### src/artha/ (the library; mypy --strict, no side effects on import)

**config.py** — Settings dataclass; resolves ARTHA_DATA_DIR (default
~/quant-data) into raw/curated/reports dirs. Everything reads paths
from here; nothing hardcodes.

**marketspec/** — market abstraction so research code is
market-agnostic. `base.py`: MarketSpec protocol (calendar + cost
model). `nse.py`: India-calibrated NSECostModel — STT 0.1% both sides,
stamp 0.015% buy, NSE txn 0.00307% (verified 2026-07-19), SEBI fee,
GST on levies, flat Rs 15.34 DP charge per scrip-sell (the
small-account killer), sqrt impact (a=3bps, b=10bps at V/ADV=1);
`nse_spec()` builds the full spec. `us_stub.py`: P9 portability proof —
the pipeline runs on US-shaped data unchanged.

**data/** — the point-in-time data layer.
- `store.py`: RawStore — immutable writes, sha256 manifest; nothing
  ever overwrites a raw file.
- `ingest/nse_http.py`: hardened NSE client (headers, cookie dance for
  www.nseindia.com APIs, retries). All downloaders go through it.
- `ingest/bhavcopy.py`: daily equity bhavcopy, BOTH formats (old
  csv.zip and UDiFF from 2024-07-01; filename/URL builders + parsers).
- `ingest/indices.py`: index close files (three date formats across
  history — parser disambiguates by filename date).
- `ingest/ca_api.py`: declared corporate-actions feed (the ONLY source
  of adjustment factors — see ADR 0005) + symbol-change list.
- `ingest/fo.py`: NIFTY futures from F&O bhavcopies (both formats),
  front-month series with same-contract returns across rolls.
- `ingest/symbolchange.py`: ticker rename history feed.
- `adjust.py`: THE adjustment engine. Canonicalizes renamed symbols
  date-aware, parses declared ratios, computes observed-gap factors
  for demergers/rights, applies backward adjustment, and (since
  2026-07-19) REJECTS declared factors the ex-day price contradicts by
  >2.5x — the sanity gate that caught six phantom splits. Read its
  docstrings before touching anything here.
- `curated.py`: raw -> curated parquet build, yearly partitions, with
  an incremental mode (filename-level year currency check) used by the
  daily cycle.
- `calendar.py`: TradingCalendar from actual session dates (NSE holds
  weekend special sessions; never assume Mon-Fri).
- `universe.py`: PIT liquidity/price/age universe (ADR 0004 — no free
  historical index constituents exist, so the universe is defined by
  filters, replayable at any date).
- `master.py`: security master with sector mapping (static current
  sectors — known limitation).
- `benchmark.py`: synthetic NIFTY 500 total-return index (no free TRI
  source exists; construction documented in P2 note).
- `qa.py`: return outliers, prev-close mismatches, thin dates.
- `backfill.py`: shared calendar-days backfill runner used by all
  backfill scripts (attempts EVERY calendar day; 404 = holiday).

**events/** — announcement alpha (P4). `ingest.py` pulls the
announcements/board-meetings archives; `knowability.py` implements the
15:30 IST rule (an announcement after the close belongs to the next
session — enforced, lookahead-tested); `taxonomy.py` rule-based event
classification (81% audited accuracy) with `taxonomy_llm.py` as the
GROQ-key-gated upgrade; `event_study.py` market-model CARs;
`features.py` event features for the model matrix.

**features/** — `baselines.py`: momentum 12-1, 5d reversal, 63d
low-vol + the FeatureSpec registry (every feature declares its
knowability; the lookahead suite audits the registry).
`library.py`: the 17-feature cross-sectional library (returns, vol,
Amihud, turnover, 52w distances...), z-scored per date.

**labels/horizon.py** — forward n-day return labels, cross-sectionally
z-scored; the 5d label drives the weekly studies.

**models/** — validation machinery. `cv.py`: purged expanding
walk-forward with embargo. `cpcv.py`: combinatorial purged CV and PBO.
`dsr.py`: deflated Sharpe (expected-max correction from the ledger
count). `spa.py`: stationary bootstrap + White Reality Check + Hansen
SPA (the sharp multiple-testing test). `ledger.py`: the append-only
trial ledger. `study.py`: the one protocol every model family runs
under (fit per fold, stitch OOS predictions, rank IC, hand to the
backtester). `transformer.py`: small tabular transformer used in P3.

**portfolio/** — `construct.py`: the Constructor (position/sector
caps, ADV participation with fail-open on missing ADV, no-trade bands
OR trade_speed partial adjustment, vol targeting on UNSCALED book vol)
+ `production_constructor()` — THE single source of the live config
(currently minvar + tau 0.5); every live/replay script imports it.
`riskmodel.py`: Ledoit-Wolf shrunk covariance, inverse-vol and
long-only min-var weights, `risk_inputs()` (knowable-at-t trailing
window for the live path). `hedge.py`: rolling-beta NIFTY futures
overlay, lagged one day, with per-side + roll costs.

**backtest/** — `vectorized.py`: the research backtester. Signals at
t's close execute at t+1's close; return accrual precedes execution;
weights drift between rebalances; optional constructor, risk-input
feed, and gross_gate (regime dial). Read its module docstring — the
mechanics are the lookahead defense. `metrics.py`: summarize
(Sharpe/CAGR/vol/DD/hit/turnover). `engine/`: the event-driven twin —
`orders.py` order/state types, `accounting.py` ledger with T+1
settlement and avg-cost PnL, `engine.py` the loop with price bands,
halts, order expiry. tests/parity ensures the twins agree.

**risk/** — `analytics.py`: VaR/CVaR, drawdown states, rolling Sharpe,
sortino/calmar, worst windows, liquidity (days-to-liquidate).
`live_eval.py`: small-sample honesty — PSR, minimum track record
length, Kupiec VaR exception test (all unit-tested against known
properties).

**live/** — `adapters/base.py`: BrokerAdapter protocol.
`adapters/paper.py`: persistent idempotent paper broker (JSON state;
duplicate client ids short-circuit). `adapters/zerodha.py`: Kite
adapter, key-gated (KITE_API_KEY/KITE_ACCESS_TOKEN), batch LTP;
UNTESTED against a real account until credentials exist. `oms.py`:
deterministic client order ids (sha256 of date:symbol:side:qty),
sells-first planning, pre-trade checks (value/count/band caps).
`safety.py`: Telegram alerts (env-gated, never crash the runbook),
reconcile-or-freeze, KillSwitch (freeze file; flatten deliberately
BYPASSES pre-trade checks — an emergency exit must not be rejectable),
drawdown_action (-10% halves gross, -15% freezes; enforced in the
runbook).

**agent/** — B6 research agent. `spec.py` pydantic proposal schema;
`sandbox.py` AST-whitelisted expression DSL (no attributes, no
keywords, empty builtins — model output is audited before evaluation);
`proposer.py` deterministic seeds offline / Groq key-gated with
fallback; `loop.py` ridge quick-screen vs the library baseline. Every
screen appends to the ledger.

**singlename/** — Track D. `preprocess.py`: wavelet/EMD/CEEMDAN
denoising + the causal_transform wrapper (no-lookahead property is
unit-tested bit-identically). `models.py`: the D3 family — ridge,
LGBM, GRU, LSTM, tiny transformer, with one fit/predict interface.

**dashboard/** — `app.py`: read-only FastAPI over reports/curated
artifacts (localhost only); `static/index.html`: dependency-free page
(SVG charts, crosshair tooltips, live IST clock, captions). No CDNs,
no auth, no writes.

**news/** — namespace for D4 growth (collectors currently live in
scripts/; promote shared logic here when it stabilizes).

### scripts/ (entrypoints; each has a usage docstring — read it)

Backfills (all idempotent, raw-zone only): `backfill_bhavcopy.py`,
`backfill_indexclose.py`, `backfill_ca.py`, `backfill_events.py`,
`backfill_fo.py`, `backfill_gdelt.py`.
Builds: `build_curated.py` (--incremental for the daily append),
`build_benchmarks.py`, `build_events.py`.
QA: `scan_raw_integrity.py`, `run_incremental_test.py`,
`make_spotcheck_fixture.py` (Yahoo reference fixtures).
Research runners (one per study; each writes a timestamped JSON report
and appends the ledger): `run_baselines.py` (P2), `run_model_study.py`
(P3), `run_event_alpha.py` (P4), `run_p5.py` (P5 construction gate),
`run_survivorship_demo.py` (P6), `run_hedge_study.py` (B4),
`run_construction_v2.py` + `run_spa.py` + `run_regime_study.py`
(Track C), `run_ticker_selection.py` (D1), `run_d2_preprocess.py`
(D2), `run_d3_models.py` (D3/D5), `run_research_agent.py` (B6).
Operations: `run_daily_cycle.py` (the 19:00 task: backfills -> news ->
curated -> integrity -> paper day -> alert), `run_paper_day.py` (the
trading runbook), `run_weekly_review.py` (live-vs-research
divergence), `run_live_readiness.py` (B3 go/no-go),
`run_reconcile_readonly.py` (B2, needs credentials), `kite_login.py`
(daily token), `run_kill_drill.py` (freeze->flatten rehearsal),
`run_slippage_report.py` (realized vs modeled), `collect_news.py`
(D4 RSS + sentiment), `run_dashboard.py` (localhost:8787).
`artha_daily.cmd` / `artha_weekly.cmd`: the scheduled-task wrappers.

### tests/

`unit/` — module behavior incl. the regression tests that encode past
bugs (vol-target feedback loop, missing-ADV freeze, phantom-CA gate,
flatten bypass, causal-transform bit-identity, SPA properties).
`lookahead/` — planted-jump, scrambled-signal, registry audit; CI
gate; it caught a real execution-ordering bug once.
`parity/` — vectorized-vs-engine agreement (<2e-5/day fractional).
`integration/` — real-data checks (auto-skip when ~/quant-data absent,
so CI passes without data) + the 19-name Yahoo spot-check.
`fixtures/` — small committed samples for both bhavcopy formats etc.

### Root files

`CLAUDE.md` — working rules + phase tracker (updated every session).
`pyproject.toml` — deps, ruff, mypy --strict (files: src+tests; scripts
are exercised by running them), pytest config. `.github/workflows/` —
CI (ruff, mypy, pytest on every push). `.pre-commit-config.yaml` —
hooks run on every commit.

## 3. From-scratch bootstrap (empty machine -> running system)

```
# 0. prerequisites: git, uv (https://docs.astral.sh/uv/), ~10 GB disk
git clone https://github.com/vj0246/artha && cd artha
uv sync                                  # exact locked environment
uv run pytest                            # ~220 tests green without any data

# 1. data root (outside any synced folder!)
#    default ~/quant-data; override: setx ARTHA_DATA_DIR D:\quant-data

# 2. raw backfills (hours; all resumable/idempotent)
uv run python scripts/backfill_bhavcopy.py 2010-01-01 <today>
uv run python scripts/backfill_indexclose.py 2010-01-01 <today>
uv run python scripts/backfill_ca.py
uv run python scripts/backfill_events.py
uv run python scripts/backfill_fo.py 2021-01-01 <today>      # hedge overlay
uv run python scripts/backfill_gdelt.py 2017-01 <this-month> # news history

# 3. curated builds
uv run python scripts/build_curated.py     # ~15 min full
uv run python scripts/build_benchmarks.py
uv run python scripts/build_events.py
uv run python scripts/scan_raw_integrity.py

# 4. reproduce the research record (each writes reports/ JSON + note)
uv run python scripts/run_baselines.py
uv run python scripts/run_model_study.py          # slowest (transformer)
uv run python scripts/run_event_alpha.py
uv run python scripts/run_p5.py
uv run python scripts/run_survivorship_demo.py
uv run python scripts/run_hedge_study.py
uv run python scripts/run_construction_v2.py && uv run python scripts/run_spa.py
uv run python scripts/run_regime_study.py
uv run python scripts/run_ticker_selection.py
uv run python scripts/run_d2_preprocess.py
uv run python scripts/run_d3_models.py --windows expanding rolling

# 5. operations (see RUNBOOK.md)
schtasks /Create /TN "artha-daily"  /SC DAILY /ST 19:00 /TR "<repo>\scripts\artha_daily.cmd"
schtasks /Create /TN "artha-weekly" /SC WEEKLY /D SAT /ST 10:00 /TR "<repo>\scripts\artha_weekly.cmd"
uv run python scripts/run_dashboard.py     # http://127.0.0.1:8787

# 6. before every commit
uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest
```

GPU note: `uv sync` installs CPU torch. For CUDA:
`uv pip install torch --index-url https://download.pytorch.org/whl/cu126 --reinstall`,
then ALWAYS `uv run --no-sync ...` (a plain `uv run` re-syncs back to
the CPU wheel — this bites everyone once).

## 4. Environment variables (names only; never commit values)

ARTHA_DATA_DIR (data root override) · TELEGRAM_BOT_TOKEN /
TELEGRAM_CHAT_ID (alerts; optional) · KITE_API_KEY / KITE_API_SECRET /
KITE_ACCESS_TOKEN (broker; unlocks B2+) · GROQ_API_KEY (LLM taxonomy,
agent proposer, news scoring; optional).

## 5. Gotchas that cost real time (learn from our scars)

1. NSE bhavcopy PREVCLOSE is NEVER adjusted — factors come only from
   the declared feed, and the declared feed itself lies sometimes (six
   phantom splits) — hence the two-way verification in adjust.py.
2. NSE trades on some weekends (budget Saturdays, muhurat). Backfills
   attempt every calendar day; 404 means holiday, not failure.
3. Windows + polars: set PYTHONIOENCODING=utf-8 or box-drawing output
   crashes cp1252 pipes; subprocesses need encoding="utf-8" too.
4. PowerShell here-strings break on inner double quotes — commit long
   messages with `git commit -F file`.
5. Vol targeting must divide by UNSCALED book vol (portfolio return /
   gross); using the scaled portfolio's own vol is a feedback loop.
6. Missing ADV must fail OPEN in construction or exits freeze and
   gross pins at 1.0 (regression-tested).
7. Full-series decomposition (EMD/wavelet fit on all data) is
   look-ahead. Always use causal_transform for anything tradeable.
8. The paper log allows ONE non-dry row per session (rerun guard);
   the B1 gate counts sessions, and reruns must not inflate it.
9. mypy scope is src+tests; scripts are validated by execution. New
   untyped dependency -> add to the pyproject mypy override list.

## 6. How to extend without breaking the discipline

New data source -> ingest module + RawStore + backfill script + QA;
never write curated directly. New feature -> features/library.py with
a registry entry (knowability!) so the lookahead audit covers it. New
strategy/config -> run under the standard protocol, append the ledger,
report DSR/SPA context, write the research note, update PROJECT_PLAN's
changelog. New live behavior -> paper first, kill-switch compatible,
reconcile must still pass, and the readiness checklist stays the gate.
Decision reversal -> ADR. Every session ends with the tracker updated.
