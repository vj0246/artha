# ADR 0005: hybrid CA adjustment — implied pre-UDiFF, declared after

Date: 2026-07-08. Amends ADR 0003 after full-history validation falsified
one of its assumptions.

## What validation found

- RELIANCE Bonus 1:1 ex 2024-10-28: raw UDiFF row shows
  `PrvsClsgPric = 2655.70` against `ClsPric = 1334.35`. NSE does NOT
  base-price-adjust the UDiFF bhavcopy previous close. The implied-factor
  method (ADR 0003) therefore sees nothing on post-cutover ex-dates; it
  remains valid only for the old format (pre 2024-07-01), where the
  known bonuses/splits do appear (verified on full history).
- Every "small factor" implied event for RELIANCE (0.96-1.01) traced to
  NSE weekend special sessions (2010-02-06 DR drill, 2020-02-01 and
  2026-02-?? budget Saturdays, 2024-01-20 special session, muhurat
  weekends): the weekday-only backfill skipped those files, so PREVCLOSE
  referenced a close we did not have. Fix: backfills attempt every
  calendar day; holidays 404 harmlessly.

## Decision

`combined_ca_events` merges two factor sources at the UDiFF cutover:

- ex-date < 2024-07-01: implied factors from the exchange-adjusted old
  PREVCLOSE (ADR 0003 mechanics unchanged).
- ex-date >= 2024-07-01: factors parsed from the declared CA feed
  (`corporates-corporateActions`, monthly raw files): "Bonus a:b" ->
  b/(a+b), face-value split Rs x -> Rs y -> y/x. Declared symbols are
  canonicalized date-aware before use.

Each source cross-checks the other on the pre-cutover overlap
(2011-2024); the review frames land in the reports dir on every build.

## Consequences and accepted limits

- Post-cutover rights issues and special dividends have no parseable
  ratio and are NOT adjusted; the QA return-outlier scan flags any large
  unexplained ex-date move for manual review. Pre-cutover these were
  captured implicitly.
- Declared feed is fetched up to the last complete month; a CA with an
  ex-date in the current month appears only after the next backfill run.
- If NSE resumes base-price adjustment (or the CA API dies), the cutover
  constant is the single switch point to revisit.
