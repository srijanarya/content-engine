#!/bin/bash
# Daily content engine run — AI-world + finance monitors.
# Wire to a scheduler (cron/launchd) to run once a day.
set -e

# Resolve the engine dir from this script's location (portable — no hardcoded paths).
MONITOR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE_DIR="$(dirname "$MONITOR_DIR")"
LOG="$MONITOR_DIR/run.log"

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
python3 "$MONITOR_DIR/ai_world_monitor.py" >> "$LOG" 2>&1 || echo "ai_world_monitor failed" >> "$LOG"

echo "--- Finance monitor ---" >> "$LOG"
python3 "$MONITOR_DIR/finance_monitor.py" >> "$LOG" 2>&1 || echo "finance_monitor failed" >> "$LOG"

# Daily market wrap from the regime artifact (local-only; couples to the trading system).
if [ -f "$MONITOR_DIR/daily_market_post.py" ]; then
    echo "--- Daily market wrap ---" >> "$LOG"
    python3 "$MONITOR_DIR/daily_market_post.py" >> "$LOG" 2>&1 || echo "daily_market_post failed" >> "$LOG"
fi

echo "=== Done $(date) ===" >> "$LOG"
