# Artha — complete system overview

One document that explains everything: what exists, why, where it
lives, how it runs, and what the ultimate purpose is. Updated whenever
architecture changes (repo rule). Companion docs: PROJECT_PLAN.md
(authoritative plan + execution changelog), TRACK_B/C/D_PLAN.md (phase
detail), RUNBOOK.md (operations), docs/research/ (one note per study),
docs/decisions/ (ADRs).

## Ultimate purpose

Prove, with institutional-grade honesty, that a retail-sized systematic
equity strategy on NSE can be researched, validated, and OPERATED end
to end at Rs 0 data cost — then run it live. The artifact is threefold:
(1) a validated strategy (constructed momentum, LW min-var + GP tau
0.5, net Sharpe ~1.02, live paper since 2026-07-19), (2) the research
record including every null, and (3) the production machinery that
trades it unattended. The honest-nulls record IS the credential: most
of quant is knowing what does not work.

## Data layer (src/artha/data)

- **Sources** (all free, primary): NSE bhavcopy (dual format, UDiFF
  cutover 2024-07-01), declared corporate-actions feed, index closes,
  1.48M timestamped announcements, F&O bhavcopy (NIFTY futures), and —
  since Track D — free news (Google News/ET RSS forward collector +
  GDELT historical), all in an immutable raw zone with a sha256
  manifest under ~/quant-data (outside OneDrive; ARTHA_DATA_DIR).
- **Adjustment**: factors ONLY from the declared CA feed (ADR 0005 —
  bhavcopy prev-close is never adjusted), now cross-checked against
  ex-day prices (the CA sanity gate rejects declared events the price
  contradicts; caught six phantom splits including a fake 1:5 TVSMOTOR
  split that manufactured a +398% return).
- **Universe**: point-in-time liquidity filters (ADR 0004) — no
  survivorship; the bias was MEASURED at +2.5pp/yr.
- **QA**: return outliers, prev-close mismatches, thin dates, integrity
  scan of every raw file's hash — all run in the daily cycle.

## Research stack (Tracks A, C, D)

- **Validation machinery** (src/artha/models): purged expanding
  walk-forward with embargo, CPCV, deflated Sharpe, PBO, White Reality
  Check + Hansen SPA (stationary bootstrap), append-only trial ledger
  feeding all of them. Every experiment — human or agent-proposed — is
  a ledger row before its result is read.
- **Key findings**: ML does not beat simple factors cross-sectionally
  net of costs (PBO 0.86); Indian PEAD is INVERTED (t = -6.9);
  construction alone lifts Sharpe 0.96 -> ~1.02 (post-hardening rerun)
  (Ledoit-Wolf min-var + Garleanu-Pedersen partial adjustment, Track
  C); the family beats the index with SPA p = 0.0445; regime gates add
  nothing beyond vol targeting (null); decomposition preprocessing
  (EMD/CEEMDAN) is 100% look-ahead — leaky IC 0.41 collapses to -0.04
  causal (Track D2, the paper-grade result).
- **Single-name lab** (Track D, ICICIBANK locked by composite screen):
  preprocessing study done; model family (ridge/LGBM/GRU/LSTM/
  transformer/ensemble) + drift arms running; news sentiment pipeline
  collecting forward daily from 2026-07-19.

## Production stack (Track B)

- **Engine parity**: the research backtester and the event-driven
  engine (T+1 settlement, halts, price bands) agree to <2e-5/day in CI.
- **Daily cycle** (19:00 IST scheduled task "artha-daily"): incremental
  backfills -> news collector -> curated rebuild -> integrity scan ->
  paper trading (production_constructor: minvar+tau0.5, knowable-at-t
  risk inputs) -> reconcile -> Telegram alert. Idempotent end to end:
  deterministic order ids, one non-dry log row per session, rerun-safe.
- **Safety**: kill-switch freeze file; drawdown rails ENFORCED (-10%
  halves gross, -15% freezes); emergency flatten bypasses pre-trade
  caps (reviewed + regression-tested); reconcile-or-freeze; pre-trade
  checks (order value, count, price bands).
- **Broker**: PaperBroker (persistent, idempotent) now; KiteAdapter
  key-gated behind KITE_API_KEY/KITE_ACCESS_TOKEN with batch LTP,
  morning-login script, read-only reconcile script — all waiting on
  credentials only.
- **Go/no-go**: run_live_readiness.py quantifies everything a decision
  needs: ops discipline, tracking error vs research, execution quality,
  vol band + Kupiec VaR test, PSR + minimum track record length, and
  capital sizing (Rs 2L minimum viable, Rs 5L preferred — flat DP
  charges and integer shares kill Rs 1L).

## Dashboard (src/artha/dashboard, http://127.0.0.1:8787)

Read-only FastAPI over run artifacts + one dependency-free page:
live-config KPIs, growth-of-100 with crosshair, construction bar chart,
statistical-honesty card, sizing, hedge, go-live checklist, paper log,
trial ledger — every section captioned with what it shows and why it
matters. Real-time 1s IST clock + NSE open/closed state; artifacts
poll every 10s (they change once per daily cycle). Millisecond/tick
data requires the Kite websocket -> unlocked by VJ's credentials; the
system's validated edge is EOD, so ticks are an ops nicety, not alpha.

## Realtime truth (recorded so expectations stay honest)

The strategy trades once a week at the close. Free data is EOD.
Sub-second market data on NSE is a paid product; the free live path is
Kite (needs credentials). Anything on this dashboard that claims to be
real-time IS real-time (clock, session state, file freshness); nothing
pretends tick data exists where it does not.

## What waits on VJ (nothing else blocks)

1. Laptop on at 19:00 IST daily (B1 clock: 30 clean sessions).
2. Zerodha credentials + static-IP/2FA setup (unlocks B2 reconcile
   week, live quotes, slippage measurement, C5 execution study).
3. Funding >= Rs 2L after B1+B2 gates (B3 4-week live gate).
4. Optional: GROQ_API_KEY (LLM taxonomy + research-agent proposer +
   news LLM scoring).

## Test surface

220+ tests: unit, integration (real-data, skip without curated zone),
lookahead suite (planted-jump caught a real bug), backtest/live parity
gate, CA sanity gate regressions, causal-transform bit-identity, SPA
statistical properties. CI on every push; local gate = ruff + mypy
--strict + pytest.
