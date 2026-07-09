# ADR 0005: adjustment factors from the declared CA feed (supersedes 0003)

Date: 2026-07-08. Written after full-history validation; supersedes the
implied-factor design of ADR 0003 and this ADR's own earlier hybrid draft.

## What validation established

1. The bhavcopy previous close is the RAW prior close in BOTH formats.
   NSE never base-price-adjusts it: INFY bonus 1:1 ex 2015-06-15 shows
   prev_close 1975.05 (= prior close), WIPRO bonus ex 2017-06-13 shows
   526.35, RELIANCE bonus ex 2024-10-28 (UDiFF) shows 2655.70. ADR 0003's
   premise is empirically false; there is no implied factor in the price
   files.
2. The 23,640 "implied events" of the first full build were phantoms:
   NSE weekend special sessions (budget Saturdays, muhurat, DR drills)
   missing from a weekday-only backfill made our prior close disagree
   with NSE's prev_close on the following Monday. Backfills now attempt
   every calendar day; a prev_close-vs-prior-close mismatch is kept as a
   QA warning because it detects exactly this failure mode.

## Decision

Adjustment factors come solely from the declared corporate-actions feed
(www.nseindia.com CA API, monthly raw JSON, coverage probed back to 2005;
ingested from 2010 to match the panel):

- "Bonus a:b" -> factor b / (a + b)
- Face-value split Rs x -> Rs y -> factor y / x
- Subject wording varies by era; the parser reads the first number after
  the keyword and after "to". Everything else (dividends, rights, AGMs)
  yields no factor.
- Symbols are canonicalized date-aware; same-day factors multiply;
  ex-dates on non-trading days snap forward to the symbol's next session.

## Safety nets and accepted limits

- QA return-outlier scan (|1-day adjusted return| > 30%) is the catch-all
  for unparseable or missed CAs -- rights issues and special dividends
  are NOT adjusted in v1 and will surface there for review.
- QA prev_close-mismatch scan detects missing session files.
- Declared feed fetched to the last complete month; current-month CAs
  appear on the next backfill run.
- Spot-checks against independent references (plan 5.3) remain the P1
  gate for the resulting adjusted series.
