# TRACK_G_PLAN v1 (2026-07-20) — operational hygiene, alarms, error control

Adopted at VJ's direction (ADR 0012) after an ops audit found that the
project's alerting had no delivery channel and its most expensive
failure mode produced no signal at all. Zero ledger cost: nothing here
is a research trial, so none of it spends statistical credibility.

## The two problems this track fixes

**1. Alerts had nowhere to go.** `safety.alert()` printed to stderr and
POSTed to Telegram only when `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`
were set — and they are not set. Every alarm the system raises (kill
switch freezes, reconciliation breaks, drawdown de-risk, constraint
violations, signal decay, feature drift, cycle failures) was therefore
landing in a log tail nobody reads. A freeze could halt trading for a
week in silence.

**2. Nothing alarmed on silence.** Every other check fires when
something DOES the wrong thing. Nothing fired when nothing happened:
scheduled task refused (observed: `Last Result = -2147020576` on
2026-07-20), machine off/asleep at 19:00, reboot mid-cycle, paper day
silently no-opping. Because the B1 clock (30 consecutive sessions) is
the binding constraint on every remaining milestone, a silently stalled
clock is the most expensive bug available: it costs wall-clock weeks
and is discovered late.

## G1: durable alerts

`safety.alert(message, severity=...)` now appends every alert to
`reports/paper/alerts.jsonl` BEFORE attempting any other channel, with
a UTC timestamp and severity (`warning` | `critical`; kill-switch
freezes are critical). File-writing failures are individually
suppressed — alerting must degrade, never crash the runbook, and that
contract is unit-tested (including an unwritable data dir).

Every existing call site inherits durability with no change. Telegram
remains the optional push channel on top.

## G2: heartbeat monitor (`scripts/run_heartbeat.py`)

Scheduled nightly at 21:00, two hours after the daily cycle, so a
refusal or crash surfaces the same night. Checks:

- book freshness: latest non-dry paper session vs the NSE calendar
  (alert past 1 session behind — "the daily cycle is not running");
- missed sessions inside the B1 window (the gate counts consecutive);
- kill-switch state, with the freeze reason;
- `cycle.log` age (> 30h untouched = scheduler probably dead);
- all four scheduled tasks exist and are enabled;
- accumulated critical alerts;
- whether a push channel is even configured.

Writes `reports/paper/health.json`, exits non-zero on any problem so
the scheduler itself records a failure, and raises one critical alert
summarizing everything wrong.

**Known limitation, stated honestly**: a local watchdog cannot detect
"the machine was off" — if the PC is down at 19:00 it is likely down at
21:00 too. The only complete fix is an external dead-man's switch (the
cycle pings a third-party service on success; the service notifies when
the ping stops). That is a one-line addition on our side but involves
signing up for and pinging an external service, so it is VJ's decision,
documented in RUNBOOK rather than enabled unilaterally.

## G3: surfacing

The dashboard gained `/api/health` and `/api/alerts`, a health banner
pinned above every other panel (green with B1 progress, red with the
explicit problem list), and an operational-alert feed. Rationale: an
alert nobody sees is not an alert. The banner also states when Telegram
is unconfigured, so the absence of pushes is never mistaken for the
absence of problems.

The weekly review runs the heartbeat too, so a stalled clock cannot
survive a week even if the nightly task is the thing that broke.

## Scheduled task roster after G

| task | when | purpose |
|---|---|---|
| artha-daily | 19:00 daily | backfill -> rebuild -> trade -> reconcile |
| artha-heartbeat | 21:00 daily | did any of that actually happen? |
| artha-weekly | Sat 10:00 | live-vs-research divergence + heartbeat |
| artha-monthly | 1st, 10:00 | research agent + SPA refresh |
| artha-quarterly | every 3rd month | construction re-validation |

## Not built, deliberately

- External dead-man's switch: VJ's call (see G2 limitation).
- Email/SMS channels: Telegram already covers push; more channels means
  more secrets to manage for no additional coverage.
- Auto-remediation (auto-unfreeze, auto-restart): every freeze in this
  system is a decision point that deserves a human. Alarms inform; they
  do not act.
