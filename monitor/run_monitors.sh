#!/bin/bash
# Daily content engine run — AI-world + finance monitors.
# Wire to a scheduler (cron/launchd) to run once a day.
set -e

# Resolve the engine dir from this script's location (portable — no hardcoded paths).
MONITOR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE_DIR="$(dirname "$MONITOR_DIR")"
LOG="$MONITOR_DIR/run.log"
# Ops-digest escalation: failures land here; the 08:10 digest globs logs/*-status.md
# and skips empty files. Truncated each run so a recovered lane stops nagging.
STATUS="$HOME/autonomy/logs/content-engine-status.md"
mkdir -p "$HOME/autonomy/logs" && : > "$STATUS"

echo "=== Content Engine run $(date) ===" >> "$LOG"

# Model routing: generation uses the claude CLI first; a gitignored monitor/.env.local
# can export BULK_BASE_URL + BULK_AUTH_TOKEN + BULK_MODEL as the degrade endpoint used
# when the CLI fails (e.g. monthly spend limit). See .env.template.
if [ -f "$MONITOR_DIR/.env.local" ]; then
    # shellcheck disable=SC1091
    source "$MONITOR_DIR/.env.local"
fi

# Each monitor's rc also feeds fail_breaker: 3 consecutive failing days → one escalation in
# ~/autonomy/escalations/ (louder than the per-run status note; includes the log tail).
echo "--- AI-world monitor ---" >> "$LOG"
rc=0; python3 "$MONITOR_DIR/ai_world_monitor.py" >> "$LOG" 2>&1 || rc=$?
[ "$rc" -ne 0 ] && { echo "ai_world_monitor failed rc=$rc" >> "$LOG"; echo "$(date '+%F %H:%M') ai_world_monitor FAILED rc=$rc — tail monitor/run.log" >> "$STATUS"; }
python3 "$MONITOR_DIR/fail_breaker.py" ai-world-monitor "$rc" >> "$LOG" 2>&1 || true

echo "--- Finance monitor ---" >> "$LOG"
rc=0; python3 "$MONITOR_DIR/finance_monitor.py" >> "$LOG" 2>&1 || rc=$?
[ "$rc" -ne 0 ] && { echo "finance_monitor failed rc=$rc" >> "$LOG"; echo "$(date '+%F %H:%M') finance_monitor FAILED rc=$rc — tail monitor/run.log" >> "$STATUS"; }
python3 "$MONITOR_DIR/fail_breaker.py" finance-monitor "$rc" >> "$LOG" 2>&1 || true

# NOTE: the daily market wrap is intentionally NOT run here. This batch fires pre-open (~08:30), but a
# "wrap" needs the COMPLETED session's data. It runs only in the postmarket lane (x/cron/run.sh, ~16:00)
# where regime_safe.json is post-close. Running it here produced the 2026-06-23 pre-open / stale wrap.

echo "=== Done $(date) ===" >> "$LOG"
