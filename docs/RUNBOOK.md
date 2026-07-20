# Paper-trading runbook (Track B B1)

## One-time setup — DONE 2026-07-19

Both tasks are registered (wrappers in `scripts/artha_daily.cmd` /
`scripts/artha_weekly.cmd`, output appended to
`~/quant-data/reports/paper/cycle.log`):

```
schtasks /Create /TN "artha-daily"  /SC DAILY        /ST 19:00 /TR "...\scripts\artha_daily.cmd"
schtasks /Create /TN "artha-weekly" /SC WEEKLY /D SAT /ST 10:00 /TR "...\scripts\artha_weekly.cmd"
```

Daily fires 19:00 (NSE bhavcopy lands ~18:30). Tasks run as the logged-on
user: the machine must be on (or asleep-with-wake) at 19:00; a missed
day shows up as a gap in paper_log.jsonl and resets nothing by itself —
the gate only counts consecutive logged sessions.

Telegram alerts (optional): set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID as
user environment variables; without them alerts print to the log.

The 6-week clean-paper clock starts at the first non-dry-run day in
`~/quant-data/reports/paper/paper_log.jsonl`.

## What the daily cycle does

backfill (bhavcopy + index closes from the last curated day; monthly CA /
announcements top-ups no-op mid-month) -> incremental curated rebuild ->
raw-zone integrity scan -> paper runbook (weekly momentum through the P5
constructor; trades only on Fridays/last-session-of-week, holds otherwise;
reconcile; append log) -> summary alert. Every step is idempotent: a
failed or duplicated run cannot corrupt state or double-trade (client
order ids are deterministic per day).

## Manual interventions

- Kill switch: `~/quant-data/reports/paper/FREEZE` — its existence halts
  the runbook. Delete the file to resume (investigate first; the file
  records the freeze reason).
- Full curated rebuild (after adjustment-logic changes):
  `uv run --no-sync python scripts/build_curated.py` (no --incremental).
- Reset the paper book (before the real clock starts only): delete
  `paper_state.json` and `paper_log.jsonl`.

## Kite morning login (B2, once credentials exist)

`uv run --no-sync python scripts/kite_login.py` prints the login URL;
after the manual browser login rerun with the request_token to exchange
for the day's KITE_ACCESS_TOKEN (printed once, never written to disk).
With KITE_API_KEY/KITE_ACCESS_TOKEN set, run_paper_day upgrades quotes
to Kite LTP automatically (quote_source in the daily log shows which).

## Read-only account reconcile (B2 gate evidence)

`uv run --no-sync python scripts/run_reconcile_readonly.py` — daily,
for at least a week before any live order. Never places orders.

## Kill-switch drill (B3 rehearsal)

`uv run --no-sync python scripts/run_kill_drill.py [--synthetic]` —
freeze -> flatten on a scratch copy of the paper book; evidence in
kill_drills.jsonl. Real state never touched.

## Live readiness evaluation (B3 go/no-go)

`uv run --no-sync python scripts/run_live_readiness.py` — run weekly
during paper and before/while live. Six sections: operations discipline,
live-vs-research tracking error, execution quality, risk conformance
(vol band, drawdown rails, Kupiec VaR test), small-sample statistics
(PSR + minimum track record length), and capital sizing with flat DP
charges + integer-share granularity. Prints the go-live checklist; all
items true = GO candidate.

## Slippage report (B3 feedback loop)

`uv run --no-sync python scripts/run_slippage_report.py` — realized vs
modeled per fill from orders_log.jsonl; meaningful once quote_source
is kite_ltp.

## Signal health (E2, runs inside the daily cycle)

`uv run --no-sync python scripts/run_signal_health.py` — momentum IC
decay watch (63d/252d), PSI feature drift (alert > 0.25), DSR refresh
vs the live ledger count. Appends signal_health.jsonl; alerts via
Telegram.

## Scheduled research refresh (E3) — REGISTERED 2026-07-20

artha-monthly (1st, 10:00): research agent + SPA refresh.
artha-quarterly (every 3rd month, 2nd, 10:00): construction study
re-validation. Wrappers: scripts/artha_monthly.cmd / artha_quarterly.cmd.

## Dashboard (B5)

`uv run --no-sync python scripts/run_dashboard.py [port]` — read-only
FastAPI app on localhost (default 8787): tearsheet KPIs, benchmark
chart, model study, paper log, trial ledger. No auth, no writes; do not
expose beyond localhost.

## Research agent (B6)

`uv run --no-sync python scripts/run_research_agent.py [--n 3] [--offline]`
— proposes candidate features (deterministic seeds offline; Groq when
GROQ_API_KEY is set), screens each with the ridge quick protocol, and
appends every screen to the trial ledger. Report lands in
`reports/research_agent_<ts>.json`. A candidate only graduates to the
feature library after a full model-study run by hand.

## Futures hedge study (B4)

`uv run --no-sync python scripts/backfill_fo.py 2021-01-01 <today>` then
`uv run --no-sync python scripts/run_hedge_study.py` — hedged vs
unhedged constructed momentum; gate |residual beta| < 0.1.

## B1 gate (from docs/TRACK_B_PLAN.md)

30 consecutive logged sessions with zero reconciliation breaks, zero
missed runs (holidays excluded), and weekly live-vs-research divergence
under 25 bps/week. Evidence: paper_log.jsonl + weekly_review.json.
