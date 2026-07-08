# ADR 0004: PIT universe from liquidity filters; index replay deferred (P1c)

Date: 2026-07-08

## Decision

The v1 investable universe is defined directly on the bhavcopy panel by
point-in-time filters (63-day median traded value floor and top-500 rank,
price floor, minimum listing age) instead of replaying NIFTY 500
constituent changes as plan section 5.2 originally specified.

## Why

- The bhavcopy panel lists every security that traded each day, including
  later-delisted names, so a filter-defined universe is survivorship-free
  by construction. Index membership was only ever a proxy for "large and
  liquid enough to trade"; the filters measure that directly.
- No scriptable primary source for historical NIFTY 500 membership was
  found (probed 2026-07-08): Wayback holds only ~7 usable snapshots of
  ind_nifty500list.csv since 2018, and niftyindices change announcements
  are press-release attachments without a stable machine-readable index.
- A liquidity-ranked top-N is itself PIT-reconstructable from data we
  already store, needs no new scraper, and its parameters are explicit
  rather than inherited from index committee decisions.

## Consequences

- Universe composition will differ from NIFTY 500 at the margins
  (typically the illiquid tail). Baselines and the benchmark comparison
  remain against NIFTY 500 (TRI when a source is secured -- open
  verify-list item; price index from ind_close_all meanwhile).
- Current constituent lists are still snapshotted daily-forward
  (constituents/nifty500_YYYYMMDD.csv), building a true membership
  history from today onward.
- If a scriptable change-report source appears, membership replay becomes
  an optional AND-refinement on top of the filters; the plan's
  universe-count QA check then compares our top-500 against known
  constituent counts as a sanity band rather than an exact match.

## Supporting evidence

- ind_close_all_DDMMYYYY.csv (nsearchives): available from ~2012-07-02,
  404 before; contains price indices only (no TRI rows); NIFTY 500 row
  named "CNX 500" pre-2015 rebrand, "Nifty 500" after.
- niftyindices Backpage.aspx endpoints (getTotalReturnIndexString,
  getHistoricaldatatabletoString) return the HTML shell regardless of
  payload as of 2026-07-08: the pre-revamp API is gone.
