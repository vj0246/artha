# Artha

[![ci](https://github.com/vj0246/artha/actions/workflows/ci.yml/badge.svg)](https://github.com/vj0246/artha/actions/workflows/ci.yml)

A survivorship-free, research-to-production quant platform for NSE cash
equities — built from primary exchange sources, validated with Lopez de
Prado-grade statistics, and honest about what did not work.

**Full study: [docs/research/ARTHA_RESEARCH_REPORT.md](docs/research/ARTHA_RESEARCH_REPORT.md)**

## Headline results (net of full Indian costs, 2012-2026)

| | CAGR | Vol | Sharpe | MaxDD |
|---|---|---|---|---|
| Constructed momentum (shipped) | 12.9% | 13.5% | **0.97** | **-27%** |
| Naive momentum 12-1 | 23.6% | 25.6% | 0.96 | -49% |
| NIFTY 500 (synthetic TRI) | 14.4% | 16.0% | 0.95 | -38% |

- **Survivorship bias, measured**: the same strategy on a survivor-only
  universe reports **+2.5pp/yr CAGR that never existed** (23% of names —
  the delisted losers — vanish from a current-constituents dataset).
- **ML vs simple factors**: ridge / LightGBM / MLP / transformer under one
  purged CV protocol — none beats momentum or low-vol net of costs;
  **PBO = 0.86** (the in-sample winner is overfit 24 times out of 28).
  Published as a null.
- **Event alpha**: 1.48M exchange announcements with receipt timestamps;
  significant event-day reactions that FADE, **inverted PEAD** (big
  positive surprises reverse, t = -6.9), and no incremental weekly alpha
  from event features. Published as a null.
- **Publication bar**: deflated Sharpe of the shipped strategy is 0.64
  against a 22-trial ledger — economically strong, below the 95%
  statistical bar, and reported exactly that way.

## What is inside

- **Point-in-time data layer** from NSE primary sources: dual-format
  bhavcopy ingest, declared-CA adjustment (the bhavcopy base price is
  never adjusted — discovered and documented), weekend special sessions,
  immutable raw zone with sha256 manifest, QA suite, PIT liquidity
  universe (ADRs in `docs/decisions/`).
- **Validation machinery**: purged walk-forward + CPCV, deflated Sharpe,
  PBO, trial ledger, and a lookahead suite in CI whose planted-jump test
  caught a real execution-ordering bug.
- **India-calibrated costs**: STT/stamp/exchange/GST, flat DP charges,
  sqrt impact; capacity analysis (Sharpe flat to ~Rs 25Cr).
- **Portfolio construction**: caps, no-trade bands, ADV participation,
  vol targeting on unscaled book vol — constraints verified on every
  rebalance.
- **Event framework**: taxonomy (rules + guardrailed LLM upgrade path),
  market-model event studies, knowability rule (58.5% of announcements
  land after the close).

## Reproduce

```
uv sync
uv run pytest                      # 145 tests incl. lookahead suite
uv run python scripts/backfill_bhavcopy.py 2010-01-01 2026-07-08
uv run python scripts/build_curated.py
uv run python scripts/run_baselines.py
uv run python scripts/run_model_study.py
uv run python scripts/run_p5.py
uv run python scripts/run_survivorship_demo.py
```

Data lands outside the repo (`~/quant-data`, override `ARTHA_DATA_DIR`).
GPU legs use CUDA torch (`uv pip install torch --index-url
https://download.pytorch.org/whl/cu126 --reinstall`, then `uv run
--no-sync`).

## Honest limitations

Synthetic TRI benchmark; static current-sector map; cash at 0%;
rights/special dividends unadjusted (QA-flagged); cost rates approximate
until verified; taxonomy 81% accurate (audited). Track B (event-driven
engine, backtest/live parity, Zerodha paper trading) is specified in
[docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md) and not yet built.
