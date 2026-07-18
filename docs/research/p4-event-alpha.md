# P4: event and announcement alpha (plan v2 section 12)

Date: 2026-07-13. Verdict: **gate PASSED** — classifier accuracy measured,
CARs significant per category, Model A vs B delta reported. Headline:
**event effects are real but small; announcement features add no
incremental weekly cross-sectional alpha, and Indian earnings events show
REVERSAL, not PEAD.**

## Corpus and classifier

355,138 in-universe events (of 1.48M announcements) classified by the
deterministic rule taxonomy. Accuracy measured by manual review of a
stratified 297-subject sample (`reports/taxonomy_audit_sample.csv`):
**81% overall**, with four systematic collisions found and fixed
(SAST-regulation "acquisition" false-positives had m_and_a precision at
41% — post-fix the category shrank 18.6k -> 10.5k events; GST "orders",
NCLT scheme meetings, figurative pledges). Audit cases are pinned as unit
tests. LLM classifier (guardrailed, cached, audited) is implemented and
key-gated; expected to lift the weak categories.

## Event-study results (market-model AR vs synthetic NIFTY 50 TR)

| Category | n | CAR(0,1) bps [t] | CAR(2,20) bps [t] | CAR(2,60) bps [t] |
|---|---|---|---|---|
| earnings_result | 28,270 | -40 [-9.6] | -25 [-2.9] | -23 [-1.7] |
| m_and_a | 10,497 | +14 [+3.5] | -64 [-6.0] | -106 [-5.7] |
| dividend_distribution | 13,991 | -14 [-3.2] | -59 [-5.8] | -67 [-3.8] |
| litigation_regulatory | 1,866 | -22 [-2.3] | -64 [-2.3] | -61 [-1.3] |
| order_win | 966 | +65 [+4.3] | -113 [-2.4] | -306 [-3.1] |
| capex_expansion | 563 | +39 [+2.4] | -2 [-0.1] | +38 [+0.5] |

Pattern: day-0/1 reactions in the presumed direction, then FADE — order
wins pop +65bps and give back -306bps over the next quarter (overreaction),
M&A drifts down after the pop.

**PEAD inverted.** Earnings events bucketed by day-0 abnormal return
(surprise proxy; no analyst consensus exists free for India, stated
honestly): top-quintile surprises (+555bps day 0) REVERSE -213bps over
days 2-60 (t = -6.9); bottom-quintile shows no downward drift. Indian
large/mid caps mean-revert after announcement shocks — the opposite of
Bernard-Thomas US drift, consistent with our P2 finding that reversal is
the strong gross signal here.

## Model A vs B (the section 12.4 punchline)

Same folds, backtester, and ledger as P3; ridge and transformer:

| | A: price | B: +events | delta | C: events only |
|---|---|---|---|---|
| Ridge IC | 0.0427 | 0.0402 | **-0.0026** | 0.0024 (t 0.8) |
| Ridge net Sharpe | 0.84 | 0.79 | **-0.05** | 0.23 |
| Transformer IC | 0.0413 | 0.0344 | **-0.0070** | 0.0006 (t 0.2) |
| Transformer net Sharpe | 0.89 | 0.68 | **-0.20** | -0.14 |

Orthogonality: C's scores are nearly uncorrelated with momentum (-0.01)
and reversal (-0.10) — the event block is not subsumed by price features;
it simply carries ~no exploitable signal at the weekly horizon in this
aggregation. Adding it dilutes both models. **Published null.**

## Why the null is credible (and what it does NOT say)

- CARs are tens of bps against weekly cross-sectional dispersion of
  several hundred bps; after the 15:30 knowability rule shifts most events
  (58.5%) a day later, little tradeable edge remains at weekly rebalance.
- It does NOT rule out: daily-horizon event trading (the -213bps
  top-quintile reversal has a 6.9 t-stat), LLM-graded materiality/tone
  (rule labels are coarse: 81%), or results-calendar timing effects.
  Recorded as future work, each a ledger trial when attempted.

## Gate checklist

- Classifier accuracy measured: 81% (297-sample manual audit, file in
  repo, systematic errors fixed and pinned). PASS.
- CARs with significance per category: table above, t-tests + bootstrap.
  PASS.
- Model A vs B delta reported: negative deltas published to the ledger.
  PASS (null).
- Research note: this document. PASS.

Next: P5 — portfolio construction (no-trade bands, vol targeting, caps),
full validation tearsheet, risk analytics.
