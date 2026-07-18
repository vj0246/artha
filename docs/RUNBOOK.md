# Paper-trading runbook (Track B B1)

## One-time setup (VJ)

Register the daily task (19:00 IST, after the NSE bhavcopy lands ~18:30):

```
schtasks /Create /TN "artha-daily" /SC DAILY /ST 19:00 /TR "cmd /c cd /d \"C:\Users\vivaa\OneDrive\Desktop\Personal Projects\Quant\artha\" && %USERPROFILE%\.local\bin\uv.exe run --no-sync python scripts\run_daily_cycle.py >> %USERPROFILE%\quant-data\reports\paper\cycle.log 2>&1"
```

Optional weekly review (Saturdays 10:00):

```
schtasks /Create /TN "artha-weekly" /SC WEEKLY /D SAT /ST 10:00 /TR "cmd /c cd /d \"C:\Users\vivaa\OneDrive\Desktop\Personal Projects\Quant\artha\" && %USERPROFILE%\.local\bin\uv.exe run --no-sync python scripts\run_weekly_review.py >> %USERPROFILE%\quant-data\reports\paper\cycle.log 2>&1"
```

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
