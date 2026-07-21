# Artha: Cross-Sectional ML Trading System for NSE Equities
## PROJECT_PLAN v2 (2026-07-11), supersedes v1 (2026-07-08)

Before replacing the repo copy: diff against your local `docs/PROJECT_PLAN.md` in case you made
local edits during P1.

### Changelog v1 -> v2

1. **Reprioritized for quant-researcher impact.** Research track (Track A) now runs first and is
   the resume core. Event-driven engine, parity, broker, and live layer move to Track B (later,
   quant-dev showcase). Live trading remains the end goal, just sequenced after the research
   deliverable.
2. **P1 marked complete**, subject to the acceptance audit in Section 5.0. New **P1b** addendum:
   NSE corporate announcements and results-calendar ingestion, required by the new event-alpha
   phase.
3. **News upgraded from risk-gate garnish to a research phase (P4), reframed as event and
   announcement alpha** from NSE primary sources. Rationale in Section 12. Scraped-news sentiment
   (GDELT/RSS) demoted to exploratory secondary. The live-time news risk gate moves to Track B.
4. **Transformer promoted** from conditional stretch into the P3 model comparison study. GPU
   confirmed: RTX 2050 (4 GB) locally, Colab for larger sweeps. Daily cross-sectional panels are
   small; this is sufficient.
5. Market making: already out in v1, unchanged. Derivatives: unchanged, Track B stretch (futures
   hedge overlay first; options only as a later, data-cost-gated decision).

Everything not mentioned in a section below carries over from v1 unchanged (MarketSpec, storage
design, cost model, QA discipline, verify-list).

### Post-v2 execution changelog (kept current so VJ can follow every change)

- 2026-07-20 (Track G: ops hygiene, ADR 0012): an ops audit found the alerting had no
  delivery channel (Telegram unset, so freezes/breaks/drift landed only in a log tail) and
  that NOTHING alarmed on silence — a daily cycle that never runs produced no signal, while
  the scheduled task had in fact returned a refusal code that same day. Fixed: alert() is now
  durable (appends to alerts.jsonl with severity before any push channel; unit-tested to
  degrade rather than crash); scripts/run_heartbeat.py runs nightly at 21:00 (artha-heartbeat)
  checking book freshness vs the NSE calendar, missed B1 sessions, kill-switch state,
  cycle.log age, scheduled-task presence and accumulated criticals -> health.json + non-zero
  exit + critical alert; the dashboard pins a health banner and an alert feed; the weekly
  review runs the heartbeat too. Known limit (documented, not hidden): a local watchdog cannot
  detect "machine was off" — external dead-man's switch is VJ's call. Zero ledger cost.

- 2026-07-20 (C7 verdict + SPA correction, ADR 0011): the blend candidate ran its
  pre-registered battery and was HELD, not shipped — PBO 0.500 (gate < 0.5) and family
  SPA p = 0.655 (gate < 0.05) failed; sub-period stability and DSR passed. Production
  unchanged. The battery also corrected a project claim: Track C's SPA rejection
  (p = 0.0415) came from the naive fully-invested momentum baseline in that family; over
  constructed configurations only, SPA p = 0.655, because SPA tests raw excess return and
  the shipped vol-targeted book beats the index on Sharpe (1.02 vs 0.94) at lower vol and
  slightly lower raw return. README, report, overview, handbook and Track C docs amended.
  Stale doc claims swept (retired 1.055/1.119 figures marked superseded at point of use).

- 2026-07-20 (wrap-up, ADR 0010): Track F published — working paper on the leaky-decomposition
  finding (PAPER_leaky_decomposition.md) + research report Part II complete. C7 blend study:
  momentum+low-vol 50/50 rank blend = Sharpe 1.297 vs 1.018 live — UPGRADE CANDIDATE, not
  shipped pending the full validation battery + deliberate clock restart (c7-blend.md).
  Post-tax lens: STCG 20.8% takes production from 13.7% to 11.0% CAGR, Sharpe 1.02 to 0.82
  (run_posttax.py). Project state: wrap-up complete; all further progress gated on wall clocks
  and VJ's credentials.

- 2026-07-20: Track E adopted and executed (docs/TRACK_E_PLAN.md, ADR 0009) — the honest
  answer to daily retraining: production has no fitted parameters (and D5 measured retraining
  cadence as irrelevant), so Track E ships EWMA-vs-LW covariance as a gated study (E1),
  signal-health monitoring in the daily cycle (E2: IC decay, PSI drift, DSR refresh — first
  run: IC healthy, dist_52w_low PSI 0.46 flagged, production DSR 0.20 vs 89-trial ledger),
  monthly/quarterly scheduled research refresh (E3, tasks registered), credential-gated
  execution-cost learning (E4), and a binding retrain-cadence policy (E5).

- 2026-07-18: Track A complete (P0-P6); Track B built (P7-P9). Details in CLAUDE.md tracker
  and docs/research/.
- 2026-07-19: Track B operations live (B1 clock started, daily 19:00 task); B2/B3 code built
  ahead of credentials; B4-B6 stretch done. docs/TRACK_B_PLAN.md.
- 2026-07-19: Track C research v2 executed (docs/TRACK_C_PLAN.md, ADR 0006): Ledoit-Wolf
  min-var + Garleanu-Pedersen tau 0.5 replaces equal-weight+bands as the production
  construction (net Sharpe 1.12 vs 0.96, maxDD -21% vs -27% — SUPERSEDED, see the
  2026-07-20 entry: corrected to 1.018 vs 0.963); Hansen SPA p = 0.0445 for the
  family vs the synthetic TRI; regime-gate null published. Declared-CA sanity gate added to
  the adjuster after six phantom split declarations were caught (TVSMOTOR et al.).
- 2026-07-19: Track D adopted (docs/TRACK_D_PLAN.md, ADR 0007): single-name laboratory —
  ticker LOCKED by D1 screen 2026-07-19: ICICIBANK (composite 0.896 vs RELIANCE 0.767 —
  liquidity rank 2, vol 30.8% mid-band, unbroken history), causal-vs-leaky decomposition
  preprocessing study, unconstrained model family, free Indian news-sentiment pipeline
  (GDELT + RSS + announcement corpus), drift/regime honesty. Cross-sectional book unchanged.
- 2026-07-19 (later): D2 EXECUTED — decomposition preprocessing is look-ahead: EMD/CEEMDAN
  leaky reproduces the literature's IC 0.41 / Sharpe 3.15 and causal re-decomposition
  collapses it to ~0 (docs/research/d2-preprocessing.md). D3/D5 model family + drift arms
  launched. D4 news pipeline LIVE: RSS collector wired into the daily cycle (non-critical
  step) + GDELT historical backfill; VADER sentiment scored at ingest. Dashboard: real-time
  1s IST clock + NSE session state, 10s artifact refresh, per-chart explanatory captions.
  docs/SYSTEM_OVERVIEW.md added as the single full-system document; docs/HANDBOOK.md added
  as the complete new-maintainer onboarding (every file, every choice, from-scratch bootstrap,
  gotchas) — the project is now carry-forwardable without any verbal handover.
- 2026-07-20: 10-finding code review fixed (commit fbceca4) and all affected studies rerun
  on a rebuilt panel (CA gate tightened to 0.55-1.6x; 14 declared factors rejected, persisted
  to qa_ca_rejections). REVISED HEADLINE: construction v2 winner minvar+tau0.5 = Sharpe 1.018
  vs 0.963 equal (earlier 1.119 partly an artifact of the position-cap cash leak, now fixed
  by redistribution); minvar/ivol statistically tied; SPA p = 0.0415; D2 gap +3.40 Sharpe
  with per-side costs; D3 null stands with chronological sequences. Production config
  unchanged (tie does not justify a clock restart); ADR 0008 updated.
- 2026-07-20: D3/D5 EXECUTED — comprehensive null (docs/research/d3-d5-models.md): no model
  in the family (ridge/LGBM/GRU/LSTM/transformer/ensemble) beats always-long on ICICIBANK
  net of costs, under expanding OR rolling windows; OOS ICs ~0. Single-name lab conclusion:
  D2 leaky-preprocessing artifact + D3 efficient floor. No single-name model ships; the
  cross-sectional book remains the edge.
- 2026-07-20: D4 EXECUTED, TRACK D COMPLETE — sentiment gating loses to always-long on both
  arms (announcements: gated 0.06 vs floor 0.58, 5d IC -0.036, consistent with inverted PEAD;
  GDELT partial: -0.33). Null published (docs/research/d4-sentiment.md). Single-name lab
  verdict: every popular retail technique leaks, loses to buy-and-hold, or both. Millisecond data
  recorded as credential-gated (Kite) and out of the validated EOD edge's scope.

---

## 0. Locked scope (updated)

| Dimension     | Decision |
|---------------|----------|
| Market        | NSE cash equities, portable via MarketSpec |
| Frequency     | EOD signals, weekly rebalance, daily risk checks |
| Primary audience | Quant researcher roles. Quant-dev material (engine, live) deferred to Track B |
| End state     | Research report + validated strategy first; paper/live trading in Track B |
| Data budget   | Rs 0; primary NSE sources only in Track A |
| ML stack      | LightGBM primary; ridge baseline; small MLP and transformer in comparison study |
| Event/news    | Announcement-based event alpha is a core research phase (P4) |
| Derivatives   | Track B stretch (NIFTY futures hedge overlay), options later if ever |
| Out of scope  | Market making, HFT, intraday, options in v2 |

---

## 1. Why this impresses a quant researcher (updated emphasis)

1. Survivorship-free, point-in-time data layer from primary sources, with a measured
   before/after bias demonstration.
2. An event-study and announcement-alpha module built on official exchange filings, with
   knowability timestamps, not scraped headlines. Event studies are core researcher craft.
3. A Gu-Kelly-Xiu-style model comparison on Indian equities: ridge vs LightGBM vs MLP vs
   transformer under one purged-CV protocol and one multiple-testing ledger.
4. Lopez de Prado-grade validation: purged/embargoed walk-forward, CPCV, deflated Sharpe, PBO,
   permutation tests, honest publication bar that accepts a null result.
5. India-calibrated cost realism and capacity analysis.
6. A paper-style research report, not just a repo. Researchers are hired on how they think;
   the writeup is the product.

---

## 2-4. Architecture, repo layout, MarketSpec

Unchanged from v1, with two repo additions:

```
  src/artha/events/        # announcements ingest, taxonomy, event_study.py, event_features.py
  docs/research/           # one research note per phase: question, method, result, decision
```

The research-notes discipline is now mandatory: every phase ends with a short note in
`docs/research/`. These notes become the skeleton of the final report and of interview answers.

---

## 5. Data layer

### 5.0 P1 acceptance audit (run before anything else)

P1 is only "done" if these v1 gates actually pass. Everything downstream inherits this layer.

- [ ] Adjusted price series match two independent references for 20 well-known names; diffs
      stored as regression tests in `tests/`.
- [ ] PIT universe counts replay correctly against known NIFTY 500 constituent history at
      several spot dates.
- [ ] QA suite (zero/negative prices, high < low, calendar gaps, duplicate rows, CA-unexplained
      outliers) green on the full backfill.
- [ ] Both bhavcopy formats (pre/post UDiFF cutover) ingest through one interface.
- [ ] Raw zone immutable, source hashes recorded.
- [ ] Security master exists with sector mapping. Static current-sector mapping is acceptable
      for v2 (flag as a known limitation; point-in-time sector history is not freely available).
- [ ] Benchmark series present: NIFTY 500 TRI, plus NIFTY 50 for market-model event studies.

Any unchecked box is a P1 bug-fix task that precedes P2.

### 5.1 P1b: event data ingestion (new, ~1 week)

| Data | Source | Notes |
|------|--------|-------|
| Corporate announcements | NSE announcements archive per symbol | Subject line, category, exchange receipt timestamp, attachment URL. Timestamp is the crown jewel |
| Results calendar / board-meeting dates | NSE | Earnings event dates, known in advance (useful as a feature itself) |
| Bulk and block deals | NSE archives | Optional, cheap to add, decent event signal |
| Rating actions | Announcements stream carries most | Tag via taxonomy rather than separate ingest in v2 |

Rules: same immutable-raw-zone discipline as P1. **Knowability rule:** announcement with exchange
timestamp after 15:30 IST belongs to the next trading day. This rule lives in the feature
registry and is covered by the lookahead test suite. v2 ingests subject-line text and metadata
only; parsing attached PDFs (results extraction) is a later enhancement, noted in the report as
future work.

Sections 5.1-5.4 of v1 (sources, PIT universe, CA adjustment, QA) otherwise unchanged, with
two amendments already recorded during P1 and carried into v2: PIT universe is defined by
liquidity/price/age filters because no scriptable historical NIFTY 500 constituent source
exists (ADR 0004), and CA adjustment factors come solely from the declared CA feed because
bhavcopy PREVCLOSE is never exchange-adjusted (ADR 0005).

---

## 6. Cost model and turnover economics

Unchanged from v1. Weekly rebalance, no-trade bands, 10-20% weekly one-way turnover target,
capacity analysis as a first-class report. Verify-list items on exact rates still open.

---

## 7. P3: Alpha and the model comparison study (expanded)

### 7.1 Baselines (P2, unchanged)

Momentum 12-1, 5d reversal, low vol, equal weight. Pipeline must reproduce known stylized facts
in Indian data net of costs before any ML claim.

### 7.2 Features and labels

Unchanged from v1 (~60-80 price/volume features, registry with knowability timestamps; labels =
5d and 21d forward returns cross-sectionally z-scored; triple-barrier + meta-labeling in a second
pass on top of the best signal).

### 7.3 The model study (researcher centerpiece)

Four model families, identical data, identical purged expanding walk-forward CV with embargo,
identical ledger:

| Model | Role | Compute |
|-------|------|---------|
| Ridge / OLS | Interpretable floor, Gu-Kelly-Xiu anchor | CPU |
| LightGBM | Expected workhorse | CPU |
| Small MLP | Nonlinearity check | 2050 |
| Transformer (PatchTST-style per-name temporal, or small cross-sectional attention) | The headline comparison | 2050 for single fits; Colab for sweeps |

Panel size (~NIFTY 500 x 15y daily = ~1.5M rows) is small; 4 GB VRAM is not a constraint at this
scale. Deliverable: a comparison table of OOS rank IC, decile spread, net Sharpe, DSR per model,
plus an honest discussion. If LightGBM wins (likely on tabular daily features), that result plus
the reasoning is exactly what a researcher interview wants to hear. Every model config counts as
a trial in the ledger; DSR is computed against the full trial count.

---

## 8. Portfolio construction

Unchanged from v1 (top 25-30, caps, no-trade bands, 12-15% vol targeting, long-only; optimizer
comparison Ledoit-Wolf vs HRP as a v2.1 research note). Now scheduled inside P5.

---

## 9. Backtesting in Track A

Track A uses the **vectorized cross-sectional backtester only** (custom ~200-line loop, full cost
model, weekly grid). The event-driven engine and the parity gate move intact to Track B; their v1
specification (Section 9 of v1) is preserved and unchanged, just re-sequenced.

Lookahead test suite (shift test, scrambled-label test, registry audit) is unchanged and now also
covers event features and the 15:30 knowability rule.

---

## 10-11. Validation protocol and risk analytics

Unchanged from v1: DSR, PBO via CPCV, bootstrap CIs, permutation tests, rolling stability, regime
table, attribution vs beta/size/plain momentum, capacity curve. Publication bar unchanged: DSR >
0 at 95%, PBO < 0.5, OOS net edge over the best simple baseline, else publish the honest null.
Risk analytics (VaR/CVaR, exposures, drawdown rules, stress replays, liquidity) run as research
reports in P5; the live daily risk job moves to Track B.

---

## 12. P4: Event and announcement alpha (replaces v1 news module)

### Why announcements, not scraped news

You asked for news alpha. The defensible version of news alpha for Indian equities at Rs 0 is
**official exchange announcements**: complete history, per-symbol (no entity-to-ticker mapping
mess), exchange receipt timestamps (point-in-time knowability), survivorship-consistent with the
bhavcopy layer. Scraped news (GDELT, RSS, media archives) has shallow and uneven Indian coverage,
noisy ticker mapping, and ToS problems; backtests built on it are hard to defend in an interview.
GDELT stays as an exploratory side note, clearly labeled lower fidelity. If you disagree, say so
now; this is the one v2 decision made on your behalf.

### 12.1 Event taxonomy via guardrailed LLM

Classify announcement subject lines offline in batch: category (earnings result, order win,
capex/expansion, pledge creation/release, rating action, M&A, fundraising,
litigation/regulatory, board change, other), direction, materiality. Groq or local model,
temperature 0, pydantic-validated JSON schema, cache keyed by text hash, deterministic fallback
to other/neutral on any failure, full audit log. Reproducible: same corpus, same labels.
A hand-labeled sample of 300 announcements measures classifier accuracy; that number goes in the
report.

### 12.2 Event-study framework (`events/event_study.py`)

Generic module: market-model abnormal returns (vs NIFTY 50), CARs over configurable windows,
t-tests and block-bootstrap significance, plots. Applied per event category. This is a reusable
research asset and a classic interview artifact.

### 12.3 PEAD and event features

India has no free analyst-consensus estimates, so classic SUE is unavailable; state this
honestly. Surprise proxy: announcement-day (or next knowable day) market-adjusted abnormal
return, a standard fallback in the literature. Study drift over 5-60d windows. Features into the
ML model: days-since-event x category with decay, event-day abnormal return, materiality/tone,
trailing event counts, results-date proximity (from the calendar, known in advance).

### 12.4 Incremental-value test (the punchline)

Model A: price/volume features. Model B: price/volume + event features. Same CV, same ledger.
Report delta rank IC, delta net Sharpe, delta DSR, and an orthogonalization check (is event
information subsumed by momentum/reversal?). Positive result: news/event alpha demonstrated
rigorously. Null result: publish it; the methodology is still the portfolio piece.

The live-time news risk gate (blocking entries on severe negative events) is preserved as
specified in v1 Section 12 and moves to Track B.

---

## 13. Track B: engineering and live (deferred, spec preserved)

Sequenced after P6. Content unchanged from v1 Sections 9 (engine + parity gate) and 13 (Zerodha
Kite adapter, OMS with pre-trade checks and kill switch, paper adapter, reconciliation,
scheduler, alerts, SEBI compliance verify items, 6-week clean paper gate, then Rs 1-2L real).
Broker account can be opened anytime; not blocking Track A. Stretch modules unchanged: NIFTY
futures hedge overlay (the derivatives entry point), options module only as a future
data-cost-gated decision, dashboard, LangGraph research agent with ledger integration.

---

## 14. Roadmap v2

**Track A: research core**

| Phase | Deliverable | Exit gate | Effort |
|-------|-------------|-----------|--------|
| P1 | Data layer | DONE, pending Section 5.0 audit | done |
| P1b | Event data ingest (announcements, results calendar, bulk deals) | Knowability rule enforced in registry; corpus QA (coverage per year, timestamp sanity); raw zone immutable | ~1 wk |
| P2 | Vectorized backtester + cost model + baselines | Stylized facts reproduced net of costs; lookahead suite green; cost sensitivity table; research note | 1-2 wks |
| P3 | Model comparison study (ridge, LGBM, MLP, transformer) + ledger | OOS IC stable; DSR/PBO reported per model; comparison table + research note | 3-4 wks |
| P4 | Event alpha: taxonomy, event studies, PEAD, incremental-value test | Classifier accuracy measured; CARs with significance; Model A vs B delta reported; research note | 3-4 wks |
| P5 | Portfolio construction + full validation + risk analytics | Constraints verified; vol targeting in band; full tearsheet, attribution, capacity, regime analysis | 1-2 wks |
| P6 | Research report + README + blog post | Publication bar addressed either way; before/after survivorship demo included | 1-2 wks |

**Track B: engineering and live (after P6)**

| Phase | Deliverable |
|-------|-------------|
| P7 | Event-driven engine + parity gate in CI |
| P8 | Broker adapter, OMS, paper trading (6-wk clean gate), then small real capital |
| P9+ | Futures hedge overlay, dashboard, research agent, optional options decision |

Rule unchanged: no phase starts before the prior gate passes; gates automated where possible.

---

## 15. Definition of impressive v2 (researcher-weighted)

1. Paper-style research report (8-12 pages): data construction, methodology, model comparison,
   event-alpha study, validation statistics, limitations. This is item one now.
2. Survivorship before/after demonstration with the measured performance gap.
3. Model comparison table under one honest protocol, with the multiple-testing ledger count.
4. Event-study CARs and the incremental-value result (or honest null).
5. Net-of-cost OOS results vs NIFTY 500 TRI with DSR and PBO; capacity analysis.
6. Clean engineering signals: typed, tested, CI, lookahead suite.
7. Track B later adds: parity test, live paper log, realized-vs-modeled slippage.

---

## 16. Reading list additions for P4

All of v1 Section 16, plus: Ball & Brown (1968), the original earnings-announcement study;
Bernard & Thomas (1989), post-earnings-announcement drift; MacKinlay (1997), "Event Studies in
Economics and Finance" (the methodology reference). India-specific PEAD evidence exists but is
thin; search and cite only what you verify, not from memory.

---

## Appendix A: Claude Code handoff (updated)

Current phase pointer: **P1 audit (Section 5.0), then P1b.**
First session prompt: "Read docs/PROJECT_PLAN.md v2. Run the P1 acceptance audit in Section 5.0
against the existing data layer. Report each checkbox with evidence. Fix failures before
anything else." Then one phase or sub-slice per session, research note at the end of each phase.
When reality disagrees with the plan, change the plan in a commit.

## Appendix B: verify-list

Carries over from v1 (cost rates, Kite status, SEBI thresholds, UDiFF cutover, constituent
coverage). Additions: NSE announcements archive depth and access pattern per symbol; exchange
timestamp availability in the announcements feed; bulk/block deal archive format.
