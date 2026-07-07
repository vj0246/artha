# ADR 0002: Bhavcopy source format map (P1a)

Date: 2026-07-08. All findings verified empirically against
`nsearchives.nseindia.com` on this date; probe HTTP statuses recorded here
resolve the "UDiFF cutover" item on the plan's Appendix B verify-list.

## Findings

| Probe | Result |
|-------|--------|
| Old `cm*bhav.csv.zip` 2010-01-04, 2023-01-02, 2024-07-05 | 200 |
| Old format 2024-12-02, 2025-01-02 | 404 (discontinued) |
| UDiFF 2024-01-02, 2024-07-05, 2026-07-03 | 200 |
| UDiFF 2023-01-02, 2015-01-02, 2010-01-04 | 404 (not backfilled) |
| `sec_bhavdata_full` 2023, 2026 | 200 |
| `sec_bhavdata_full` 2015, 2010 | 404 (insufficient depth) |

## Decisions

1. **Dual parser, cutover 2024-07-01.** Old format for earlier dates, UDiFF
   from the cutover. Both formats confirmed live that week; the overlap gives
   a permanent cross-format parity test (tests/unit/test_bhavcopy.py) — OHLCV,
   volume, traded value, trades, ISIN identical on 2024-07-05 real data.
2. **`sec_bhavdata_full` rejected as primary** (no 2010-2015 coverage). Noted
   as optional enrichment later: it carries DELIV_QTY/DELIV_PER (delivery %),
   a potential feature, from roughly the late-2010s onward.
3. **Old format has two column variants**: pre-2011 lacks TOTALTRADES and
   ISIN (parsed as nulls). Both variants have a trailing comma producing a
   phantom column (handled by explicit column selection).
4. **Units:** TOTTRDVAL and TtlTrfVal are both rupees (verified qty x price
   on RELIANCE rows). No lakh conversion anywhere.
5. **Canonical schema** keeps every series (EQ, BE, GS, GB, N3, ...); the
   universe layer filters. Parser hard-fails on: zero rows, any row dated
   differently from the requested day, missing required columns, non-zip
   response bodies (NSE block pages).
6. **Raw zone location:** default `~/quant-data` (outside OneDrive), override
   via `ARTHA_DATA_DIR`. Raw zips stored as downloaded, sha256 + source URL
   in `manifest.jsonl`, overwrites refused.

## Notes for later phases

- Symbol changes are real: INFY traded as INFOSYSTCH until mid-2011 (absent
  from the 2010 fixture). The CA/symbol-map layer (P1b) must handle renames,
  not just splits/bonuses.
- RELIANCE closed ~3177 on 2024-07-05 vs ~1304 on 2026-07-03: the 2024 1:1
  bonus. Good adjustment-layer regression case.
