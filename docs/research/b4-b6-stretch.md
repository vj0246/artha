# B4-B6: futures hedge, dashboard, research agent (Track B stretch)

Date: 2026-07-19. Builds on the completed Track A (P0-P6) and Track B
core (P7-P9, B1). Plan deviations recorded in docs/TRACK_B_PLAN.md
status notes.

## B4: NIFTY futures beta hedge overlay

**Data.** F&O bhavcopy ingest mirrors the equity dual-format story
(probed live 2026-07-18): old `foDDMMMYYYYbhav.csv.zip` with
INSTRUMENT=FUTIDX rows under content/historical/DERIVATIVES, UDiFF
`BhavCopy_NSE_FO_0_0_0_*` with FinInstrmTp=IDF under content/fo, same
2024-07-01 cutover. Raw zips stored whole and immutable; the parser
extracts NIFTY index futures only. Backfill 2021-01-01 onward.

**Front-month series.** Per date, the nearest expiry >= trade date.
The daily return always compares a contract's settle to its own
previous settle (`.shift(1).over("expiry")`), so roll days show the new
contract's true move — no artificial calendar jump. Verified by unit
test: a planted 7% calendar gap across a roll never appears in returns.

**Overlay.** Rolling 60d OLS beta of strategy net returns on
front-month futures returns, shifted one day so the hedge ratio applied
at t uses information through t-1 only. Hedged return:
`net_t - beta_t * fut_t - cost_t`, with costs = 2bps per side on
day-over-day hedge-notional changes plus a monthly roll (2 sides x 2bps
x 12/252 amortized daily). Margin financing not modeled (cash covers
SPAN comfortably at this gross); stated limitation. Unit tests recover
a planted 0.6 beta to within 0.05 and kill >50% of variance on a
0.6-beta book.

**Gate run** (2026-07-19, `reports/hedge_study_20260719T061633Z.json`).
1,372 F&O files parsed (2021-01-01 to 2026-07-17, zero skips), overlap
window 2021-04-05 to 2026-07-17 (1,251 days once the 60d beta warms up).

| | unhedged | hedged |
|---|---|---|
| CAGR | 10.5% | 7.1% |
| vol | 13.2% | 11.0% |
| Sharpe | 0.82 | 0.68 |
| max drawdown | -16.9% | -14.4% |
| hit rate | 59.5% | 55.2% |

Mean hedge beta 0.58 (matches the P5 attribution beta 0.59 estimated
independently over 2012-2026). **Residual beta -0.020 — GATE PASS**
(|residual| < 0.1). Hedge cost drag 36 bps/yr.

**Reading.** Hedging is not a free lunch here and the numbers say so
honestly: the strategy's market beta carried real return, so stripping
it costs ~3.4pp CAGR and 0.14 Sharpe in exchange for a 2.2pp vol cut
and a shallower worst drawdown. The hedged series is the alpha stream —
7.1% CAGR at near-zero market exposure — which is what you would size
up under leverage or run when the mandate is market-neutral. As an
always-on overlay for a long-only cash book it is not worth the drag;
as a risk dial (crisis regimes, drawdown control) it is now built,
tested, and one flag away.

## B5: read-only ops dashboard

FastAPI app (`src/artha/dashboard/`, `scripts/run_dashboard.py`, port
8787) over run artifacts: P5 tearsheet KPIs, synthetic NIFTY 500 TRI
chart, model-study table (per-batch report files merged oldest-first),
paper log, trial ledger. Front end is one dependency-free static HTML
page — inline CSS/JS, canvas chart, no CDNs, dark/light via
`prefers-color-scheme`. Deviation from plan: no Next.js; a localhost
read-only tool does not justify a node toolchain. Strictly read-only,
no auth, bind 127.0.0.1 only. Verified against real artifacts (all
endpoints 200) plus TestClient unit tests.

## B6: research agent

Plain loop (no LangGraph — single linear pass needs no graph state):

1. **Propose.** Deterministic seed specs offline; with GROQ_API_KEY, a
   Groq (llama-3.3-70b) proposer with the prompt as a versioned
   constant, bounded max_tokens, 30s timeout, one retry on 429/5xx,
   pydantic re-validation, and seed fallback on any failure.
2. **Validate.** `FeatureProposal` schema bounds name, rationale,
   expression length, lookback.
3. **Sandbox.** Expressions are a restricted DSL compiled via an AST
   whitelist: arithmetic, numeric/string constants, and nine named
   functions (col over 5 whitelisted columns, dret, shift, rolling
   mean/std/max/min, absv, log1p). No attribute access, no subscripts,
   no keywords, empty builtins, windows capped at 252. Model output is
   audited before anything is evaluated; `map_elements`, `__import__`,
   `open` are all structurally unreachable.
4. **Screen.** Candidate is z-scored per date (library convention),
   appended to the library matrix, and re-run through the ridge
   walk-forward study on a quick protocol (26-week test blocks, 24
   folds). Verdict = IC delta vs the library-only baseline under
   identical folds.
5. **Ledger.** Every screen appends a Trial, so the deflated-Sharpe
   trial count stays honest no matter who proposed the feature.

**First offline run** (real panel, 234k weekly rows): library baseline
IC 0.0419 (t=6.5). Three seed candidates screened — vol_ratio_21_63
delta +0.0002, range_pos_21d −0.0005, illiq_trend_5_63 −0.0009. None
admitted. Consistent with the P3 finding: this library is hard to beat
with price/volume transforms; the ledger records all three trials.

The parked event-reversal assignment needs the event-feature join (not
the price DSL) and stays with VJ's deferred item 3.
