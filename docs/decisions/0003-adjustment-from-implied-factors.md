# ADR 0003: CA adjustment from exchange-adjusted prev_close (P1b)

Date: 2026-07-08

## Decision

Adjustment factors are DERIVED from the bhavcopy itself: NSE adjusts the
base price (PREVCLOSE) on every price-affecting ex-date, so
`factor = prev_close(ex) / close(prior traded day)`. The declared
corporate-actions feed is a cross-check, not the source.

Why:
- Primary-source, full-depth (works 2010-present wherever bhavcopy exists),
  survivorship-free, and self-consistent with the price series being adjusted.
- Captures exactly what the exchange adjusted for: splits, bonuses, FV
  changes, rights, special dividends. Regular dividends correctly excluded
  (price-return series; total-return deferred, plan 5.1 marks dividends
  optional).
- A declared-CA-driven adjuster must parse free-text subjects ("Bonus 1:1",
  "Face Value Split From Rs 10 To Re 1") into ratios — fragile, and still
  needs validation against prices. Inverting the dependency is strictly less
  code and fewer failure modes.

Assumption to be verified on full real data (P1b validation step, gate item):
PREVCLOSE is exchange-adjusted on ex-dates across the whole history.
RELIANCE Bonus 1:1 ex 2024-10-28 (confirmed via CA API probe) must yield
factor ~0.5.

## Supporting endpoints (probed live 2026-07-08)

- `symbolchange.csv` (nsearchives): full rename history since ~2000,
  header-less, company names may contain commas (right-anchored regex parse).
  INFOSYSTCH -> INFY 29-JUN-2011 present. Stored as dated snapshots in raw.
- CA API `corporates-corporateActions` (www.nseindia.com, cookie dance):
  works, reaches at least 2011-06 (131 records incl. AGM/dividend noise;
  filter by subject). Full ingest deferred to P1c for event cross-check.

## Mechanics

- Equity panel: series in {EQ, BE, BZ}, dedupe per (symbol, date) with EQ
  priority; renames unified date-aware onto terminal symbol (handles chains
  and later reuse of freed symbols).
- Event threshold: |prev_close - prior_close| > 0.02 AND > 0.5% of prior
  close (paise-rounding immunity on low-priced names). Sub-0.5% base-price
  adjustments (tiny rights dilutions) are accepted as one-day return noise.
- Backward adjustment: dates strictly before an ex-date multiply prices by
  the cumulative product of later factors; volume divides. Ex-date rows are
  already in post-CA units and stay untouched.
- Suspension gaps: prior close = last traded close, so a CA during
  suspension is still captured on resumption.

## Known limits (revisit if they bite)

- Total-return (dividend reinvestment) not modeled in v1.
- Simultaneous CA + suspension + relisting at a genuinely different price
  level is indistinguishable from a CA of that ratio; QA (P1c) flags factor
  outliers for eyeball review.
- Pre-2011 rows lack ISIN, so rename unification rests on symbolchange.csv
  completeness; QA cross-checks panel continuity.
