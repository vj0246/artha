# Artha

[![ci](https://github.com/vj0246/artha/actions/workflows/ci.yml/badge.svg)](https://github.com/vj0246/artha/actions/workflows/ci.yml)

Cross-sectional ML trading system for NSE cash equities: survivorship-bias-free
point-in-time data layer built from primary NSE sources, LightGBM alpha validated
with Lopez de Prado-grade statistics (purged CV, deflated Sharpe, PBO), a custom
event-driven engine with an India-calibrated cost model, and a live paper/real
trading leg. Market-agnostic by design via a `MarketSpec` abstraction.

**Status: Phase P0 (repo scaffold).**
Full plan and phase gates: [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md).
