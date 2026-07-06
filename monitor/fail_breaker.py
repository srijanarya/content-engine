#!/usr/bin/env python3
"""Escalate-only circuit breaker for the cron/monitor lanes.

Usage: fail_breaker.py <job> <rc>. Called by x/cron/run.sh and monitor/run_monitors.sh after each
job with its exit code. rc=0 resets the job's streak; rc!=0 increments it. At THRESHOLD consecutive
failures it writes ONE escalation to ~/autonomy/escalations/ (the 08:10 ops digest globs that dir
into the morning email), then stays quiet for RENOTIFY_HOURS while the lane keeps retrying —
recovery is automatic, the nag is not repeated. Always exits 0: a breaker bug must never fail the
lane it watches.
"""
from __future__ import annotations
import json, sys
from datetime import datetime, timedelta
from pathlib import Path

THRESHOLD = 3        # consecutive failures before escalating
RENOTIFY_HOURS = 24  # while still failing, escalate at most once per this window

AUTONOMY = Path.home() / "autonomy"
STATE_FILE = AUTONOMY / "state" / "content-engine-failures.json"
ESC_DIR = AUTONOMY / "escalations"
ENGINE_DIR = Path(__file__).parent.parent


def _job_log(job: str) -> Path:
    """Where this job's output actually lands, for the escalation pointer."""
    if job.startswith("x-"):
        return AUTONOMY / "logs" / f"x-cron-{datetime.now():%Y-%m-%d}.log"
    return ENGINE_DIR / "monitor" / "run.log"


def _log_tail(path: Path, lines: int = 15) -> str:
    try:
        return "\n".join(path.read_text().splitlines()[-lines:])
    except OSError:
        return "(log not readable)"


def _escalate(job: str, entry: dict) -> None:
    log = _job_log(job)
    ESC_DIR.mkdir(parents=True, exist_ok=True)
    (ESC_DIR / f"content-engine-{job}-{datetime.now():%Y%m%d-%H%M%S}.md").write_text(
        f"# content-engine lane failing: {job}\n\n"
        f"- consecutive failures: **{entry['count']}** (last rc={entry['last_rc']})\n"
        f"- last failure: {entry['last_ts']}\n"
        f"- log: `{log}`\n\n"
        f"The lane keeps retrying on schedule and self-heals when the root cause clears\n"
        f"(quota reset / network back / Kite up). This note re-fires at most once per "
        f"{RENOTIFY_HOURS}h while it keeps failing.\n\n"
        f"Log tail:\n```\n{_log_tail(log)}\n```\n"
    )


def record(job: str, rc: int) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    if rc == 0:
        if state.pop(job, None) is not None:
            STATE_FILE.write_text(json.dumps(state, indent=2))
        return
    entry = state.get(job, {"count": 0, "escalated_ts": None})
    entry["count"] += 1
    entry["last_rc"] = rc
    now = datetime.now()
    entry["last_ts"] = now.isoformat(timespec="seconds")
    last_esc = entry.get("escalated_ts")
    if entry["count"] >= THRESHOLD and (
            not last_esc or now - datetime.fromisoformat(last_esc) > timedelta(hours=RENOTIFY_HOURS)):
        _escalate(job, entry)
        entry["escalated_ts"] = now.isoformat(timespec="seconds")
    state[job] = entry
    STATE_FILE.write_text(json.dumps(state, indent=2))


def main() -> int:
    # ponytail: escalate-only breaker — never parks a lane; add park-until-cleared if retry cost matters
    try:
        record(sys.argv[1], int(sys.argv[2]))
    except Exception as e:  # noqa: BLE001 — see module docstring: never fail the watched lane
        print(f"fail_breaker error (ignored): {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
