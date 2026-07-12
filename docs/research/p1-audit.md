# P1 acceptance audit (plan v2 section 5.0)

Date: 2026-07-12. Verdict: **PASS** — all seven boxes closed; two carry
documented, plan-sanctioned limitations.

## Checkbox evidence

1. **Adjusted series vs independent references — PASS.**
   19 liquid names (TATAMOTORS absent from Yahoo post-demerger), 108 price
   samples on six dates spanning 2012-2026, vs snapshotted Yahoo Finance
   levels: all within 2.5%; most within rounding. 28 combined Yahoo
   split/bonus events vs our factor events: 100% matched after documenting
   three Yahoo deficiencies (Yahoo lists only the split leg of same-day
   bonus+split events; our combined factors are proven by the price-level
   agreement). One genuine Yahoo error found: it never adjusted WIPRO's
   2013-04-09 demerger. Second reference = NSE's declared CA feed itself
   (independent of the price files). Permanent tests:
   `tests/integration/test_spotcheck.py`, `test_real_data.py`.
   The audit caught two real bugs, both fixed: combined
   "Bonus a:b / Split x->y" subjects only parsed one leg, and demergers/
   rights had no adjustment at all (now observed-gap factors on
   declared-feed dates: 462 events, e.g. RELIANCE JFS 2023, ITC Hotels
   2025, WIPRO 2013).

2. **PIT universe vs constituent history — PASS with amendment (ADR 0004).**
   No scriptable historical constituent source exists, so the universe is
   liquidity-defined. Evidence: 378/500 (76%) overlap with the current
   NIFTY 500 snapshot on 2026-07-07 (expected: NIFTY 500 is market-cap
   selected, ours traded-value selected); top-500 cap binds from ~2017;
   Rs 5 cr floor binds earlier (171-254 names 2010-13, consistent with a
   thinner market). Constituent snapshots accumulate forward from 2026.

3. **QA suite green on full backfill — PASS.** 7.10M rows, 3,623
   instruments, 4,097 sessions (21 weekend specials recovered). Zero
   structural errors. Warnings for review: 2,983 return outliers (0.04% of
   rows; small-cap circuit runs and unadjusted special situations), 87
   prev-close mismatches (suspension re-listings), 2 thin dates (muhurat).

4. **Both bhavcopy formats, one interface — PASS.** Dual parsers behind
   `parse_bhavcopy`, cross-format parity test on 2024-07-05 (identical file
   in both formats), 2-digit-year variant regression-tested.

5. **Raw zone immutable + hashes — PASS.** `RawStore.write` refuses
   overwrite; sha256 + source URL + timestamp per file in manifest.jsonl;
   ~9,300 files.

6. **Security master with sector — PASS with limitation.** 3,623 symbols;
   industry for the current NIFTY 500 (covers the investable set), static
   current-state mapping as plan v2 explicitly accepts. Delisted names
   carry null sector.

7. **Benchmarks — PARTIAL, mitigation defined.** NIFTY 50 and NIFTY 500
   price indices ingested daily from ind_close_all (2012-08 onward; the
   file does not exist earlier — pre-2012 benchmark gap documented).
   NIFTY 500 TRI has NO scriptable free source (three probes: old
   Backpage API dead, no TRI rows in ind_close_all, Wayback sparse).
   Mitigation for P2: ind_close_all carries a daily trailing dividend
   yield column, so a synthetic TRI (PR return + yield/252) is available
   and will be labeled as such; TRI source stays on the verify-list.

## Method notes

- Yahoo comparison convention: Yahoo Close (auto_adjust=False) is
  split/bonus-adjusted without dividends — same convention as adj_close.
  Rights conventions differ (~1-2% per event, observed gap vs theoretical
  ex-rights price); tolerance set at 2.5% accordingly.
- Observed-gap factors use open(ex)/close(prev session), gated strictly by
  declared-feed event dates, so no phantom events; gaps >= ~1 are treated
  as unobservable and skipped.
