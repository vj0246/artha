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

Full scheduled roster (all registered):

| task | when | purpose |
|---|---|---|
| artha-daily | 19:00 daily | backfill -> rebuild -> trade -> reconcile |
| artha-heartbeat | 21:00 daily | did any of that actually happen? (Track G) |
| artha-weekly | Sat 10:00 | live-vs-research divergence + heartbeat |
| artha-monthly | 1st, 10:00 | research agent + SPA refresh |
| artha-quarterly | every 3rd month | construction re-validation |

Telegram push is optional (see "Alarms" below). Alerts are durable
without it: every one is appended to `reports/paper/alerts.jsonl` and
shown on the dashboard.

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

## Alarms: where they go and what to do (Track G)

Every alert this system raises is APPENDED to
`~/quant-data/reports/paper/alerts.jsonl` with a UTC timestamp and a
severity (`warning` | `critical`), regardless of any push channel.
The dashboard shows the recent feed and a health banner at the top.

**Optional Telegram push** (recommended, 5 minutes): create a bot via
@BotFather, get your chat id, then set the two user environment
variables `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` (names only —
never commit values). With them set, every alert also pushes to your
phone. Without them, alerts still land in the file and the dashboard.

**What each severity means:**
- `critical` — trading is halted or the operation is broken: kill-switch
  freeze, reconciliation mismatch, heartbeat failure. Act same day.
- `warning` — degradation worth watching: drawdown de-risk engaged,
  signal IC decay, feature drift (PSI), pre-trade rejections.

**Kill switch is active?** `reports/paper/FREEZE` exists and its
contents record the reason. Investigate the reason FIRST, then delete
the file to resume. Never auto-clear it.

## Heartbeat: the alarm for silence (G2, nightly 21:00)

`uv run --no-sync python scripts/run_heartbeat.py`

Registered as `artha-heartbeat`, two hours after the daily cycle. It
catches the failure mode nothing else does: the cycle that never ran
(task refused/disabled, machine off at 19:00, reboot mid-cycle, paper
day silently no-opping). It checks book freshness against the NSE
calendar, missed sessions inside the B1 window, kill-switch state,
cycle.log age, all scheduled tasks, and accumulated criticals — then
writes `health.json`, exits non-zero on any problem, and raises a
critical alert.

**Limitation you must know**: if the PC is OFF at 19:00 it is probably
off at 21:00, so a local watchdog cannot catch that case. The complete
fix is an external dead-man's switch (the cycle pings a free service on
success; that service emails you when the ping stops). It is not
enabled because it sends operational metadata to a third party and
needs an account — your call. Until then, the practical guard is: check
the dashboard banner when you sit down, and keep the machine on at
19:00 IST.

## Signal health (E2, runs inside the daily cycle)

`uv run --no-sync python scripts/run_signal_health.py` — momentum IC
decay watch (63d/252d), PSI feature drift (alert > 0.25), DSR refresh
vs the live ledger count. Appends signal_health.jsonl; alerts through
the durable channel (alerts.jsonl + dashboard + Telegram if set).

## Scheduled research refresh (E3) — REGISTERED 2026-07-20

artha-monthly (1st, 10:00): research agent + SPA refresh.
artha-quarterly (every 3rd month, 2nd, 10:00): construction study
re-validation. Wrappers: scripts/artha_monthly.cmd / artha_quarterly.cmd.

## Dashboard (B5)

`uv run --no-sync python scripts/run_dashboard.py [port]` — read-only
FastAPI app on localhost (default 8787): tearsheet KPIs, benchmark
chart, model study, paper log, trial ledger, health banner and alert
feed. No auth, no writes; **do not expose beyond localhost** — it shows
live positions, equity and operational state with no access control
(ADR 0012).

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
