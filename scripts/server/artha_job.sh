#!/usr/bin/env bash
# Server entrypoint for every scheduled Artha job: the Linux twin of the
# scripts/artha_*.cmd wrappers. cron calls:  artha_job.sh <job>
set -uo pipefail

job="${1:?usage: artha_job.sh daily|heartbeat|weekly|monthly|quarterly}"
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo"

# Secrets (TELEGRAM_*, later KITE_*) live outside the repo, mode 600.
env_file="$HOME/.config/artha/env"
if [ -f "$env_file" ]; then set -a; . "$env_file"; set +a; fi
export PATH="$HOME/.local/bin:$PATH" PYTHONIOENCODING=utf-8

log="${ARTHA_DATA_DIR:-$HOME/quant-data}/reports/paper/cycle.log"
mkdir -p "$(dirname "$log")"

# One instance per job, like Task Scheduler's IgnoreNew: a slow run is never
# overlapped by the next trigger.
exec 9>"/tmp/artha-$job.lock"
if ! flock -n 9; then
  echo "$(date -Is) $job already running, skipped" >>"$log"
  exit 0
fi

rc=0
run() { uv run --no-sync python "$@" >>"$log" 2>&1 || rc=$?; }
case "$job" in
  daily)     run scripts/run_daily_cycle.py ;;
  heartbeat) run scripts/run_heartbeat.py ;;
  weekly)    run scripts/run_weekly_review.py ;;
  monthly)   run scripts/run_research_agent.py --offline; run scripts/run_spa.py ;;
  quarterly) run scripts/run_construction_v2.py; run scripts/run_spa.py ;;
  *) echo "unknown job: $job" >&2; exit 2 ;;
esac
exit "$rc"
