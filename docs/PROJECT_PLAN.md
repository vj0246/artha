# Artha: Cross-Sectional ML Trading System for NSE Equities

Working codename "Artha" (Sanskrit: wealth, purpose). Rename freely; nothing depends on it.

One-line pitch: a research-to-production quant platform for Indian cash equities, built on a
survivorship-bias-free data layer from primary NSE sources, an ML alpha pipeline validated with
Lopez de Prado-grade anti-overfitting statistics, a custom event-driven engine with a realistic
Indian cost model, and a live paper/real trading leg through a broker API. Market-agnostic by
design via a MarketSpec abstraction.

---

## 0. Locked scope

Decisions finalized in planning conversation (2026-07-08):

| Dimension     | Decision |
|---------------|----------|
| Market        | NSE cash equities (India first, portable architecture) |
| Frequency     | EOD signals, weekly rebalance with daily risk checks |
| End state     | Research + backtest + live paper trading, then small real capital |
| Data budget   | Rs 0 to start; primary NSE sources; upgrade path documented |
| Broker        | None yet; Zerodha Kite recommended (Section 13) |
| ML stack      | LightGBM primary; transformer as conditional stretch (GPU-dependent) |
| Derivatives   | Out of v1. Optional NIFTY futures hedge overlay as stretch phase |
| News          | Supporting risk-gate module, not core alpha |
| Options / market making / HFT / intraday | Explicitly out of scope |

Non-functional requirements: correctness over speed, full type coverage, every phase gated by
verification criteria, zero lookahead tolerance, all uncertain external facts tracked in the
verify-list (Appendix B) until confirmed.

---

## 1. Why this stands out to a quant recruiter

1. **Point-in-time, survivorship-free data layer built from primary sources.** Daily NSE bhavcopy
   archives list every security that traded that day, including names later delisted. Almost every
   personal project uses yfinance and silently inherits survivorship bias and bad corporate-action
   handling. Building the adjustment and universe-reconstruction layer yourself, with QA tests, is
   a differentiator on its own.
2. **Backtest/live parity.** The same strategy code runs through a fast vectorized research loop
   and a custom event-driven engine, with an automated parity test between them. The event engine
   is the one that later drives paper and live trading. This is the Nautilus Trader philosophy,
   implemented small.
3. **Honest validation.** Purged walk-forward CV with embargo, deflated Sharpe ratio, probability
   of backtest overfitting (CPCV), permutation tests, and a multiple-testing ledger. Most
   candidates show an equity curve; very few can defend it statistically.
4. **India-calibrated cost model.** STT, stamp duty, exchange charges, DP charges, and a
   square-root impact model. Turnover economics drive the design (Section 6), not an afterthought.
5. **Portability as architecture.** All India-specific facts live in one MarketSpec object.
   Strategy code never touches them directly.
6. **Guardrailed LLM usage.** LLMs appear only in the news gate and the optional research agent,
   deterministic core everywhere else, with schema validation, fallbacks, and audit logs.

---

## 2. System architecture

```
                        +---------------------------+
                        |  MarketSpec (nse / us)    |
                        |  calendar, costs, lots,   |
                        |  bands, settlement rules  |
                        +------------+--------------+
                                     | injected everywhere
  +---------------+   +-------------v-----------+   +----------------------+
  | NSE primary   |   |        Data Layer       |   |  Feature / Label     |
  | sources       +-->| ingest -> adjust -> PIT +-->|  Layer               |
  | bhavcopy, CA, |   | universe -> QA -> store |   |  factor lib, labels  |
  | index constit.|   | (Parquet + DuckDB)      |   +----------+-----------+
  +---------------+   +-------------------------+              |
                                                    +----------v-----------+
  +---------------+                                 |  Model Layer         |
  | News sources  |                                 |  LightGBM, purged CV |
  | RSS / GDELT   +----> News Gate (LLM/FinBERT,    |  multiple-test ledger|
  +---------------+      schema-validated, logged)  +----------+-----------+
                                        |                      |
                                        v                      v
                              +---------+----------------------+---------+
                              |     Portfolio Construction               |
                              |  ranks -> weights, constraints, bands,   |
                              |  vol targeting                           |
                              +---------+----------------------+---------+
                                        |                      |
                          +-------------v----------+  +--------v----------------+
                          | Vectorized research    |  | Event-driven engine     |
                          | backtester (sweeps)    |  | (validation + live)     |
                          +-------------+----------+  +--------+----------------+
                                        |    parity test       |
                                        +-----------+----------+
                                                    |
                              +---------------------v--------------------+
                              | Live layer: OMS, broker adapter          |
                              | (Zerodha / paper), reconciliation,       |
                              | scheduler, alerts, kill switches         |
                              +---------------------+--------------------+
                                                    |
                                          Risk + Reports + Dashboard
```

Storage: immutable raw zone (as-downloaded files), curated zone (adjusted Parquet, partitioned by
year), DuckDB for ad hoc queries, polars for pipelines. Live state (positions, orders, fills) in
SQLite v1. No cloud dependency required for research; live leg can run on a small VPS later.

---

## 3. Repository layout

```
artha/
  pyproject.toml            # uv-managed, Python 3.12
  CLAUDE.md                 # working rules for Claude Code (Appendix C)
  docs/
    PROJECT_PLAN.md         # this file
    decisions/              # short ADRs when a plan decision changes
  src/artha/
    marketspec/             # base.py, nse.py, us_stub.py
    data/                   # ingest/, adjust.py, universe.py, calendar.py, qa.py, store.py
    features/               # factor library, feature registry
    labels/                 # horizon returns, triple-barrier (v2)
    models/                 # lgbm.py, cv.py (purged/CPCV), ledger.py, transformer/ (stretch)
    portfolio/              # construct.py, constraints.py, vol_target.py, hedge.py (stretch)
    backtest/
      vectorized.py         # cross-sectional research loop
      engine/               # events.py, orders.py, fills.py, costs.py, accounting.py
    risk/                   # var.py, exposure.py, stress.py, reports.py
    live/                   # adapters/{base,zerodha,paper}.py, oms.py, reconcile.py,
                            # scheduler.py, alerts.py, killswitch.py
    news/                   # ingest.py, scorer.py, gate.py
    reports/                # tearsheets, attribution
  tests/
    unit/  integration/  lookahead/  parity/
  scripts/                  # one-off runners, data backfill
  dashboard/                # Next.js 14 + FastAPI, later phase
```

---

## 4. MarketSpec: the portability contract

A frozen dataclass injected into every layer. Strategy and engine code never hardcode market
facts.

```python
@dataclass(frozen=True)
class MarketSpec:
    name: str                      # "NSE"
    currency: str                  # "INR"
    calendar: TradingCalendar      # sessions, holidays, half days
    settlement_lag_days: int       # 1 (T+1)
    shorting: ShortingRules        # cash shorting disallowed positional
    price_bands: BandRules         # 5/10/20% circuits, dynamic bands for F&O names
    tick_size_fn: Callable         # price -> tick
    lot_size_fn: Callable          # instrument -> lot (1 for cash equity)
    cost_model: CostModel          # Section 6
    session_times: SessionTimes    # 09:15-15:30 IST
```

US portability is proven with `us_stub.py` plus a 20-line smoke test on free daily data (stretch,
Section 15). No US deliverable in v1; the abstraction is the deliverable.

---

## 5. Data layer

### 5.1 Sources (all free)

| Data | Source | Notes |
|------|--------|-------|
| Daily equity OHLCV + traded value | NSE bhavcopy archives | Full history, per-day files. Format changed to UDiFF around mid-2024; ingester must handle both (verify cutover date) |
| Corporate actions | NSE corporate actions file | Splits, bonuses, face-value changes; dividends optional for total-return series |
| Index constituents over time | niftyindices.com change reports | Needed to reconstruct point-in-time NIFTY 500 membership |
| Benchmark | NIFTY 500 TRI from niftyindices | Total-return index for fair comparison |
| Trading calendar | NSE holiday lists | Feeds MarketSpec calendar |
| F&O bhavcopy (stretch) | NSE archives | Only for the futures hedge overlay |
| News | GDELT, Google News RSS | Section 12 |

Rules: raw files are immutable and versioned on disk. Every derived table records the source file
hash and build timestamp. NSE endpoints are scrape-hostile; the ingester uses polite headers,
retries with backoff, and fails loudly rather than silently skipping days.

### 5.2 Point-in-time universe

Reconstruct NIFTY 500 membership by replaying constituent change reports. Investable universe on
date t: members on t, median 63-day traded value above threshold (start Rs 5 cr/day), price above
Rs 20, listed at least 126 trading days. All filters use only data available at t.

### 5.3 Corporate-action adjustment

Build backward adjustment factors from the CA file (splits, bonuses, face-value changes). Keep
both raw and adjusted series; features use adjusted, cost/impact math uses raw traded value.
Spot-check adjusted series for 20 well-known names against two independent references and store
the diffs as a regression test.

### 5.4 Data QA (runs on every backfill and nightly)

Zero/negative prices, high < low, missing trading days vs calendar, duplicate (symbol, date) rows,
return outliers not explained by a CA event, universe-count drift vs known constituent history,
stale symbols. QA failures block downstream builds.

---

## 6. Cost model and turnover economics

Per-side costs, delivery equity, Zerodha-style discount broker (all rates in Appendix B
verify-list; treat as approximate until confirmed):

| Component | Buy | Sell |
|-----------|-----|------|
| Brokerage (delivery) | 0 | 0 |
| STT | 0.100% | 0.100% |
| Stamp duty | 0.015% | 0 |
| Exchange txn charge | ~0.003% | ~0.003% |
| SEBI fee + GST on charges | negligible % | negligible % |
| DP charge | 0 | ~Rs 15 flat per scrip per day |

Roughly 0.12% buy side, 0.10% sell side, ~0.22% round trip before slippage.

Slippage/impact model: `cost_bps = a + b * sqrt(order_value / ADV_value)`, start a = 3, b = 10,
recalibrate against realized paper-trading fills in Phase 6. Fills assumed near close via
next-day VWAP-ish reference; the event engine makes this assumption explicit and testable.

Why this drives design:

- 30% weekly one-way turnover costs about 3.4%/yr in charges plus ~3%/yr slippage. That kills
  most daily-horizon signals in delivery equities.
- Therefore: weekly rebalance, no-trade bands (only trade when target weight deviates by more
  than a band, e.g. 25% of target), turnover penalty in construction, target 10-20% weekly
  one-way turnover.
- Flat DP charges are material at small capital: selling 10 scrips/week is ~Rs 7,800/yr, which is
  1.6% on Rs 5L. Minimum sensible live capital is roughly Rs 3-5L; below that, run paper only.
- Capacity analysis is a first-class report: the capital level at which impact consumes the alpha.
  Recruiters rarely see this from candidates.

---

## 7. Alpha and ML layer

### 7.1 Baselines first (Phase 2)

Momentum 12-1, short-term reversal (5d), low volatility, equal-weight universe. Purpose: verify
the pipeline reproduces known stylized facts in Indian data net of costs, and set the bar the ML
model must beat. If ML cannot beat the best simple factor net of costs out of sample, the project
ships the simple factor and says so. That honesty is a feature.

### 7.2 Features (~60-80, price/volume only in v1)

Returns over 5/21/63/126/252d; 12-1 momentum; 1-5d reversal; realized and downside vol 21/63d;
distance from 52w high/low; beta and idiosyncratic vol vs NIFTY (60d); Amihud illiquidity;
turnover ratio; volume z-scores; ATR-normalized range; 63d max drawdown; calendar flags
(month-end, expiry week); sector membership; cross-sectional ranks/z-scores of the above.
Fundamentals deferred: no reliable free point-in-time fundamentals for NSE; bolting on current
fundamentals would inject lookahead. Revisit later as a paid-data decision.

Feature registry: every feature declares its formula, lookback, and the timestamp at which it is
knowable. The lookahead test suite consumes this registry.

### 7.3 Labels

v1: forward 5d and 21d returns, cross-sectionally z-scored per date (predict relative, not
absolute). v2: triple-barrier labels and meta-labeling on top of the baseline momentum signal
(Lopez de Prado), which becomes the headline ML story.

### 7.4 Models

LightGBM regressor on the cross-sectional target, grouped by date. Monthly refit on an expanding
window. Transformer track (PatchTST-style or a small cross-sectional attention model) only if GPU
access is confirmed, framed as a controlled comparison vs LightGBM with the same CV protocol;
GBMs usually win on tabular daily features and reporting that result honestly is itself good
interview material.

### 7.5 Cross-validation and the multiple-testing ledger

Purged expanding walk-forward with embargo >= label horizon. Combinatorial purged CV (CPCV) for
the PBO estimate. Every experiment (feature set, hyperparams, label) is appended to a ledger
(`models/ledger.py`); the count of trials feeds the deflated Sharpe ratio. Nothing is reported
without its ledger context.

Signal metrics: daily rank IC, IC t-stat and decay, decile spreads, coverage, turnover of the
signal itself.

---

## 8. Portfolio construction

Rank -> select top N (start N = 25-30) -> weights. v1 weighting: equal weight or rank-proportional
with position cap 6%, sector cap 25%, ADV participation cap (order <= 2% of 21d ADV). No-trade
bands as in Section 6. Volatility targeting: scale gross exposure to 12-15% annualized using 21d
portfolio vol estimate; remainder in cash (model idle cash at ~0% v1; liquid-fund yield as a
refinement). Optimizer track (Ledoit-Wolf shrunk covariance mean-variance, HRP as robustness
comparison) is v2; equal weight is a brutally strong baseline and keeps v1 simple.

Long-only is a hard constraint of cash equities for retail (SLB is illiquid). The market-neutral
story arrives with the futures hedge overlay stretch (Section 15).

---

## 9. Two backtesters and the parity gate

**Vectorized research loop** (`backtest/vectorized.py`): pure polars/pandas, weekly grid,
weights x forward returns minus cost model. Fast enough for CPCV and feature sweeps. Roughly 200
lines, fully tested. (Design change vs the initial repo survey: vectorbt is demoted to optional;
it is built for per-asset parameter sweeps and is awkward for cross-sectional portfolio work. A
small custom loop is simpler and standard practice for this strategy class.)

**Event-driven engine** (`backtest/engine/`): daily bar events; order lifecycle NEW -> FILLED /
REJECTED / EXPIRED; T+1 cash settlement; price-band and halt handling; explicit fill assumptions;
full cost model; ledgered accounting (cash, positions, realized/unrealized PnL, charges). Same
engine later consumes live events instead of historical bars: that is the backtest/live parity
claim.

**Parity gate (Phase 5 exit criterion):** identical strategy and data through both engines; daily
net PnL divergence must be below a set tolerance and every residual difference attributable to an
explicitly modeled friction. This test runs in CI forever after.

Lookahead test suite (CI, always on): shift test (lag all features one extra day; IC must
collapse toward zero in the expected way), scrambled-label test (IC ~ 0), feature-timestamp audit
against the registry, no use of same-day close in same-day decisions.

---

## 10. Validation and reporting protocol

Reported for every candidate strategy, always net of full costs:

- Equity curve vs NIFTY 500 TRI and equal-weight universe; CAGR, vol, Sharpe, Sortino, max
  drawdown, Calmar, hit rate, average turnover.
- Deflated Sharpe ratio using the trial count from the ledger; PBO via CPCV; block-bootstrap
  confidence interval on Sharpe; permutation test.
- Rolling 1y Sharpe and IC stability; regime table (pre/post 2020 crash, rate cycles).
- Attribution: how much of the return is market beta, size, plain momentum vs incremental ML
  alpha.
- Capacity curve (Section 6).

Publication bar for the README: DSR > 0 at 95% confidence, PBO < 0.5, and out-of-sample net
outperformance vs the best simple baseline. If unmet, publish the honest negative result with the
analysis; the infrastructure and rigor remain the portfolio piece.

---

## 11. Risk module

Daily, on current book: historical and Cornish-Fisher VaR/CVaR (95/99), exposure report (gross,
per-name, sector, beta), drawdown state with de-risking rules (halve gross at -10% from peak,
flat at -15%; parameters configurable), stress scenarios replayed on current holdings (2008
proxy, 2020 crash, 2024 election-day gap), liquidity report (days-to-liquidate at 20% ADV
participation). Output: one dated risk report artifact per day, rendered in the dashboard later.

---

## 12. News module (guardrailed, supporting role)

Purpose: entry gate and monitoring, not alpha. Historical news depth good enough for backtesting
alpha is expensive; pretending otherwise produces fake results.

Pipeline: per-candidate-name headline pull (Google News RSS, GDELT) -> scorer -> gate. Scorer:
FinBERT locally, or Groq LLM with temperature 0, strict pydantic-validated JSON schema
(`{sentiment, severity, category, evidence}`), timeout and retry, and a deterministic fallback of
"neutral / no block" on any failure. Gate: block new entries on names with severe negative
categories (fraud, default, regulatory action); never touches sizing; every decision logged with
the raw headlines. Backtest usage: GDELT-based sanity replay only, clearly labeled as
lower-fidelity.

---

## 13. Live layer

### 13.1 Broker

Recommendation: **Zerodha Kite Connect**. Most mature Indian retail API, official pykiteconnect,
free for individual use since around Sept 2024 (verify), largest community. The historical-data
add-on is unnecessary: bhavcopy covers research; live quotes come via the Kite websocket.
Alternative kept open: Fyers (free API including historical intraday) if an intraday phase ever
happens. Action now: open the Zerodha account (PAN + Aadhaar, takes 1-3 days), create the Kite
Connect app when Phase 6 starts.

Known friction: Kite access tokens expire daily and require a login flow each morning. v1 handles
this with a small manual step in the daily runbook; automation options exist but check current
Zerodha ToS before using them.

### 13.2 Order management and safety

Adapter interface `BrokerAdapter` with `zerodha.py` and `paper.py` implementations; the paper
adapter simulates fills against live quotes using the same fill logic as the engine. OMS:
idempotent order submission with client order IDs, state machine mirroring the engine's,
pre-trade checks (price within bands, quantity caps, max order value, max daily order count,
portfolio-level max gross), dry-run mode that prints the order batch instead of sending. Kill
switch: single command flattens or freezes; auto-triggers on reconciliation mismatch or PnL
breach. Reconciliation: positions and cash vs broker at open and close; any mismatch halts
trading and alerts. Alerts via Telegram bot. Scheduler: pre-open job (data pull, signal, target
weights, order plan), execution near close per fill assumptions, post-close job (reconcile,
risk report, log archive).

### 13.3 Compliance note

SEBI's 2025 retail algo framework introduces order-rate thresholds above which strategies must be
registered through the broker, plus API access conditions (possibly static IP; broker-dependent).
A weekly-rebalance strategy submits a handful of orders per week and should sit far below
thresholds, but confirm the current rules and Zerodha's implementation before Phase 7 (Appendix
B). Paper trading has no such constraints.

Gate before real money: minimum 6 consecutive weeks of clean paper trading (zero reconciliation
breaks, realized slippage within 2x of model), then start with Rs 1-2L and the risk limits of
Section 11.

---

## 14. Phased roadmap with verification gates

Effort estimates assume roughly 10 focused hours/week; compress freely.

| Phase | Deliverable | Exit gate (verify) | Effort |
|-------|-------------|--------------------|--------|
| P0 | Repo scaffold: uv, ruff, mypy (strict), pytest, pre-commit, GitHub Actions CI, CLAUDE.md | CI green on empty skeleton | 2-3 days |
| P1 | Data layer: bhavcopy + CA + constituents ingest, adjustment, PIT universe, QA suite | Adjusted series match reference spot-checks; universe counts match known history; QA suite passes on full backfill (2010-present minimum, earlier if clean) | 2-3 wks |
| P2 | Vectorized backtester + cost model + baseline factors | Momentum/low-vol stylized facts reproduced net of costs; lookahead suite passes; cost sensitivity table produced | 1-2 wks |
| P3 | ML alpha: features, labels, LightGBM, purged CV, CPCV, ledger | OOS rank IC stable across folds; DSR/PBO computed and reported; beats or honestly fails vs baselines | 2-4 wks |
| P4 | Portfolio construction + risk module | Constraints verified on every rebalance; vol targeting within band; daily risk report artifact generated | 1-2 wks |
| P5 | Event-driven engine | Parity gate passes (Section 9) and runs in CI | 2-3 wks |
| P6 | Live layer + paper trading | 6 weeks clean paper: zero reconciliation breaks, slippage within 2x model, all alerts functional | 2 wks build + 6 wks run |
| P7 | Real capital (small), README with results, technical writeup | Live vs backtest attribution report; publication bar of Section 10 addressed either way | ongoing |

Rule: no phase starts until the previous gate passes. Gates are automated wherever possible and
live in `tests/`.

---

## 15. Stretch modules (only after P6, pick by interest)

1. **NIFTY futures hedge overlay**: beta-hedge the long book with index futures (free EOD F&O
   bhavcopy; margin, rollover, and basis modeled). Turns the story market-neutral and satisfies
   the derivatives ambition without options data costs.
2. **Transformer comparison**: conditional on GPU; same CV protocol, reported head-to-head vs
   LightGBM.
3. **LangGraph research agent**: proposes candidate features as specs, generates the feature
   function into a sandboxed module, runs the standard evaluation, and appends every trial to the
   multiple-testing ledger so DSR stays honest. Offline only, never touches live. This is the
   creative differentiator that ties your agentic-AI background to quant rigor.
4. **US smoke test**: `us_stub.py` MarketSpec + free daily data, one baseline strategy end to end,
   proving portability in ~20 lines of config.
5. **Dashboard**: Next.js 14 + FastAPI read-only API over run artifacts (equity curves, risk
   reports, live positions, news-gate log). Plays to your full-stack brand; strictly after the
   quant core works.

---

## 16. Reading list mapped to components

| Component | Read |
|-----------|------|
| Labels, purged CV, meta-labeling, backtest stats | Lopez de Prado, "Advances in Financial Machine Learning" (2018), the core reference for this build |
| Anti-overfitting | Bailey & Lopez de Prado, "The Deflated Sharpe Ratio"; Bailey, Borwein, Lopez de Prado, Zhu, "The Probability of Backtest Overfitting" |
| Multiple testing discipline | Harvey, Liu, Zhu, "... and the Cross-Section of Expected Returns" |
| ML cross-section framing | Gu, Kelly, Xiu, "Empirical Asset Pricing via Machine Learning" (2020); Kelly, Malamud, Zhou, "The Virtue of Complexity in Return Prediction" |
| Momentum foundation | Jegadeesh & Titman (1993) |
| Covariance / allocation (v2) | Ledoit & Wolf, "Honey, I Shrunk the Sample Covariance Matrix" (2004); Lopez de Prado, HRP paper (2016) |
| Transformer stretch | Lim et al., "Temporal Fusion Transformers" (2021); Nie et al., "A Time Series is Worth 64 Words" (PatchTST, 2023) |
| News scoring | Araci, "FinBERT" (2019); Lopez-Lira & Tang, "Can ChatGPT Forecast Stock Price Movements?" (2023) |
| Impact model context | Square-root market impact literature (Bouchaud et al.); skim, do not over-engineer |
| India-specific evidence | Search: "momentum profitability Indian equities" (Sehgal et al. line of work), "low volatility anomaly NSE". Thinner literature; cite what you verify, not from memory |

---

## 17. Tech stack

Python 3.12, uv, polars (pandas at edges), DuckDB + Parquet, LightGBM, scikit-learn, pydantic v2,
pykiteconnect, FastAPI (dashboard API, later), Next.js 14 (dashboard, later), pytest +
hypothesis, ruff + mypy strict, GitHub Actions, Telegram bot for alerts, SQLite for live state.
Optional: vectorbt for single-name signal exploration only; PyTorch only if the transformer
stretch activates.

---

## 18. Definition of impressive (what the README must show)

1. Net-of-cost OOS equity curve vs NIFTY 500 TRI with DSR, PBO, and the trial ledger count.
2. The parity test, described and running in CI.
3. A 6+ week live paper log with realized-vs-modeled slippage analysis.
4. A short writeup of the survivorship-free data layer with a before/after bias demonstration
   (same strategy on yfinance-style data vs the PIT layer; the gap is the punchline).
5. Capacity analysis.
6. Clean engineering: typed, tested, CI badges, honest limitations section.
7. One technical blog post walking through items 1-5.

---

## 19. Risk register

| Risk | Mitigation |
|------|------------|
| Lookahead bugs (the classic project killer) | Feature registry + shift/scramble tests in CI from P2 onward |
| Corporate-action adjustment errors | Reference spot-checks stored as regression tests |
| NSE endpoint breakage | Immutable raw zone, loud failures, ingest isolated behind one interface |
| Overfitting via iteration | Ledger + DSR/PBO; publication bar accepts negative results |
| Cost underestimation | Conservative defaults; recalibrate from paper fills before real money |
| Kite daily-token friction breaking automation | Manual runbook step v1; revisit ToS-compliant automation later |
| SEBI rule drift | Verify-list item; re-check before P7 |
| Scope creep (your known failure mode is ambition) | Phase gates are contractual; stretch list exists so ideas go there instead of into v1 |

---

## Appendix A: Claude Code handoff

1. Create empty repo, drop this file at `docs/PROJECT_PLAN.md`.
2. `CLAUDE.md` (repo root) should state: read `docs/PROJECT_PLAN.md` first; current phase is
   tracked at the top of CLAUDE.md; never start a phase before the prior gate passes; every
   session ends by updating a short `docs/decisions/` note if any plan decision changed; global
   personal standards from your existing global CLAUDE.md apply.
3. First session prompt: "Read docs/PROJECT_PLAN.md. Execute Phase P0 exactly. Stop at the gate
   and show me the CI run." Subsequent sessions: one phase (or sub-slice) per session, gate
   verification before proceeding.
4. Keep this plan authoritative. When reality disagrees with the plan, change the plan in a
   commit, not silently in code.

## Appendix B: verify-list (confirm with current sources before relying on them)

- Kite Connect current pricing/free status for individuals; historical add-on price.
- Current STT, stamp duty, exchange transaction charge, SEBI fee, GST treatment; DP charge amount.
- SEBI retail algo framework: current thresholds, effective dates, Zerodha's implementation,
  static IP requirements.
- Bhavcopy UDiFF format cutover date and old-format archive availability.
- niftyindices historical constituent report coverage depth for NIFTY 500.
- Zerodha account-opening fees and timeline.
- Fyers/Angel historical API depth (only if intraday phase ever activates).
