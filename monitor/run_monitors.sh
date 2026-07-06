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

# Model routing: set ANTHROPIC_AUTH_TOKEN + ANTHROPIC_BASE_URL however you like.
# Optionally drop a gitignored monitor/.env.local that exports them (e.g. a cheap
# Anthropic-compatible endpoint for bulk generation). If absent, the default
# Anthropic client env is used.
if [ -f "$MONITOR_DIR/.env.local" ]; then
    # shellcheck disable=SC1091
    source "$MONITOR_DIR/.env.local"
fi

echo "--- AI-world monitor ---" >> "$LOG"
python3 "$MONITOR_DIR/ai_world_monitor.py" >> "$LOG" 2>&1 || { echo "ai_world_monitor failed" >> "$LOG"; echo "$(date '+%F %H:%M') ai_world_monitor FAILED — tail monitor/run.log" >> "$STATUS"; }

echo "--- Finance monitor ---" >> "$LOG"
python3 "$MONITOR_DIR/finance_monitor.py" >> "$LOG" 2>&1 || { echo "finance_monitor failed" >> "$LOG"; echo "$(date '+%F %H:%M') finance_monitor FAILED — tail monitor/run.log" >> "$STATUS"; }

# NOTE: the daily market wrap is intentionally NOT run here. This batch fires pre-open (~08:30), but a
# "wrap" needs the COMPLETED session's data. It runs only in the postmarket lane (x/cron/run.sh, ~16:00)
# where regime_safe.json is post-close. Running it here produced the 2026-06-23 pre-open / stale wrap.

echo "=== Done $(date) ===" >> "$LOG"
