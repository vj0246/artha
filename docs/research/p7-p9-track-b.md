# Track B: engine, parity, live layer, portability (P7-P9)

Date: 2026-07-18. Status: **P7 gate PASSED; P8 build complete with the
6-week paper clock ready to start; P9 portability proven.** Remaining
stretch modules listed at the end.

## P7: event-driven engine + parity gate — PASSED

`backtest/engine/`: order lifecycle (NEW -> FILLED/REJECTED/EXPIRED),
ledgered accounting with T+1 sell settlement and realized-PnL/charge
tracking, daily bar loop with halt carry/expiry and 20% price-band
rejects, integer or fractional shares, the same MarketSpec cost model and
T+1-close execution assumption as the research loop.

**The parity gate runs in CI** (`tests/parity/`): identical synthetic
data and identical targets through both engines.

- Fractional-share mode: mean daily divergence < 2e-5 — the engines agree
  to float noise, so every mechanism (costs, timing, drift) is identical.
- Integer-share mode: divergence bounded by share rounding; cumulative
  equity paths within 2% over a year. Every residual is attributable to a
  modeled friction (rounding), which is the plan's exact criterion.

## P8: live layer — BUILD COMPLETE, paper clock pending

Everything specified in plan v1 section 13.2 exists and is tested:
BrokerAdapter protocol; PaperBroker (persistent book, engine-consistent
fills, idempotent order history); key-gated KiteAdapter; OMS with
deterministic client order ids and pre-trade checks (value cap, price
band, max gross, order count); kill switch with freeze/flatten;
reconciliation that freezes on any mismatch; env-gated Telegram alerts;
and `run_paper_day.py` — the full daily cycle, dry-run verified against
real curated data (25 orders planned, zero rejects, reconcile clean).

**What cannot be done in a session** (by design, not omission):

1. The 6-week clean-paper gate is wall-clock: schedule
   `run_paper_day.py` daily (after refreshing curated data) and let the
   log accumulate. Gate: zero reconciliation breaks, slippage within 2x
   model.
2. Real-money step needs the Zerodha account + Kite credentials
   (KITE_API_KEY / KITE_ACCESS_TOKEN) and the Appendix B verify-list
   confirmations (SEBI algo rules, current charge schedule).

Runbook: `backfill_bhavcopy.py <last-date> <today>` ->
`build_curated.py` -> `run_paper_day.py` (drop `--dry-run` to trade the
paper book), daily after 18:30 IST when the bhavcopy lands.

## P9: US portability smoke — PASSED

`marketspec/us_stub.py` (~30 lines: T+1, SEC fee, no STT/stamp/DP, sqrt
impact) plus one end-to-end test running the identical momentum pipeline
on synthetic US data. Strategy, universe, construction, backtester and
engine code untouched — the portability claim of plan section 4,
demonstrated.

## Remaining stretch (optional, plan section 15 / v2 P9+)

- NIFTY futures hedge overlay (needs F&O bhavcopy ingest + basis model)
- Dashboard (Next.js + FastAPI over run artifacts)
- LangGraph research agent feeding the trial ledger
- Options: data-cost-gated, explicitly deferred

None gate anything; each is a dedicated session when wanted.
