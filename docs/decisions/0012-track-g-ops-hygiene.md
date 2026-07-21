# ADR 0012: adopt Track G (operational hygiene, alarms, error control)

Date: 2026-07-20. At VJ's direction after an ops audit. Full plan:
docs/TRACK_G_PLAN.md. Zero ledger cost — no research trials involved.

## What the audit found

1. `safety.alert()` had NO delivery channel in practice: it printed to
   stderr and POSTed to Telegram only if TELEGRAM_BOT_TOKEN and
   TELEGRAM_CHAT_ID were set. They were not set. Every freeze,
   reconciliation break, drawdown de-risk, constraint violation, signal
   decay and drift warning was landing in a log tail nobody reads.
2. Nothing alarmed on SILENCE. The daily cycle alerts on failure and on
   success, but a cycle that never runs produces neither — and the
   scheduled task had in fact returned a refusal code
   (-2147020576) that same day with no notification.

## Decisions

1. **Alerts are durable by default.** `alert()` appends to
   `reports/paper/alerts.jsonl` (UTC timestamp + severity) before any
   other channel; kill-switch freezes are severity `critical`. Failures
   of the file write are suppressed — alerting must degrade rather than
   crash the runbook, and this is unit-tested including an unwritable
   data dir.
2. **A nightly heartbeat monitors silence** (`run_heartbeat.py`, 21:00
   task): book freshness vs the NSE calendar, missed sessions in the B1
   window, kill-switch state, cycle.log age, scheduled-task presence,
   accumulated criticals, push-channel configuration. Writes
   `health.json`, exits non-zero on problems, raises one critical alert.
3. **The dashboard surfaces health first**: `/api/health`,
   `/api/alerts`, a pinned banner above all panels, and an alert feed.
4. **The weekly review runs the heartbeat too**, so a stalled clock
   cannot survive a week even if the nightly task is what broke.

## Explicitly not done

- **External dead-man's switch.** A local watchdog cannot detect "the
  machine was off". The complete fix requires pinging a third-party
  service so it can notify when pings stop. That sends operational
  metadata off-machine and needs an account, so it is VJ's decision;
  documented in RUNBOOK, not enabled unilaterally.
- **Auto-remediation.** No auto-unfreeze, no auto-restart. Every freeze
  in this system is a decision point that deserves a human. Alarms
  inform; they do not act.
- **Vercel / any public deployment of the dashboard.** It is a
  read-only, unauthenticated view of a live trading book's positions,
  equity and health. Publishing it would expose the strategy's holdings
  and operational state to the internet with no access control, and
  requires a hosted data source that does not exist (artifacts are
  local files). It stays localhost-only until, at minimum, auth and a
  deliberate decision about what is safe to expose exist.
