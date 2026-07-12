# P1b: event data layer (plan v2 section 5.1)

Date: 2026-07-13. Verdict: **gate PASSED** — announcements and results
calendar ingested with exchange timestamps, knowability rule implemented and
tested, corpus QA green. Bulk deals deferred (see limitation 3).

## Question

Can official NSE filings supply a survivorship-consistent, point-in-time
event corpus deep enough for the P4 announcement-alpha study, at Rs 0?

## Method

Monthly-window ingest from www.nseindia.com/api into the immutable raw zone
(570 files, zero failures): `corporate-announcements` (subject text,
category, attachment URL, and the crown jewel — exchange receipt timestamp
`an_dt`), `corporate-board-meetings` (meeting date + advance intimation
timestamp), `historicalOR/bulk-block-short-deals`. Truncation check before
committing to monthly windows: a full month equals the sum of its weeks
(14,534 records, June 2026). Curated Parquet + corpus QA in
`scripts/build_events.py`.

## Result

- **Announcements: 1,479,080 records, 2010-01-01 -> 2026-06-30.** Zero null
  symbols; per-year counts grow monotonically 26k -> 183k (organic listing
  and disclosure growth, no coverage holes).
- **58.5% of announcements carry a timestamp at or after the 15:30 close.**
  The knowability rule (`artha.events.knowability`: at/after 15:30 IST or a
  non-trading day -> next trading day) is therefore not a formality; naive
  same-calendar-day dating would leak overnight information into more than
  half the corpus. Boundary unit-tested; lookahead suite (P2) will enforce
  it end to end.
- **Board meetings: 156,783 records, 2012+.** Meeting dates plus advance
  intimation timestamps: a results-calendar feature knowable ahead of the
  event. The 2023+ volume jump reflects NSE intimation-rule changes, not a
  data artifact.

## Limitations

1. Announcement categories (`desc`) are coarse; the P4 taxonomy classifier
   does the real labeling from subject text.
2. Attachment PDFs are referenced, not fetched; results extraction is
   future work (plan v2 already notes this).
3. **Bulk deals: the endpoint truncates every window at exactly 70 rows**
   (13,860 = 70 x 198 discovered in QA). Raw files kept, no curated table;
   complete re-ingest needs daily windows (~4,100 requests), deferred until
   P4 decides bulk-deal features are wanted.
4. Timestamps are naive IST as published by the exchange; pre-2010
   announcements exist at NSE but are out of panel scope.

## Decision

Event corpus accepted as the P4 substrate. Next: P2 (vectorized backtester,
cost model, baselines, lookahead suite).
