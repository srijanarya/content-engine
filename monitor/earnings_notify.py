#!/usr/bin/env python3
"""Park notification for the earnings-treum lane.

Called by x/cron/run.sh when x/EARNINGS_TREUM_LIVE is absent. Finds the most recent
earnings draft, extracts the thread preview, and writes an ops escalation to
~/autonomy/escalations/ (picked up by the 08:10 digest).

Exit 0 always — a notification failure must never fail the lane.
"""
from __future__ import annotations
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ENGINE_DIR = Path(__file__).parent.parent
IST = timezone(timedelta(hours=5, minutes=30))
ESC_DIR = Path.home() / "autonomy" / "escalations"
GO_FLAG = ENGINE_DIR / "x" / "EARNINGS_TREUM_LIVE"


def _latest_earnings_draft() -> Path | None:
    drafts = sorted(ENGINE_DIR.glob("drafts/*-earnings-*.md"), reverse=True)
    return drafts[0] if drafts else None


def _extract_thread(body: str) -> str:
    """Extract the X / TWITTER THREAD section from a draft body."""
    marker = "## X / TWITTER THREAD"
    source = "## SOURCE"
    start = body.find(marker)
    if start == -1:
        return "(no thread found in draft)"
    end = body.find(source, start)
    snippet = body[start + len(marker):end if end != -1 else start + 1200].strip()
    # Trim to ~600 chars for the escalation preview
    return snippet[:600] + ("…" if len(snippet) > 600 else "")


def main() -> None:
    draft = _latest_earnings_draft()
    if not draft:
        return   # no draft yet; nothing to preview

    try:
        body = draft.read_text()
    except OSError:
        return

    thread_preview = _extract_thread(body)
    now = datetime.now(IST)
    ESC_DIR.mkdir(parents=True, exist_ok=True)
    esc = ESC_DIR / f"earnings-treum-{now:%Y%m%d-%H%M%S}.md"
    esc.write_text(
        f"# @TreumAlgotech earnings draft parked — review needed\n\n"
        f"**Draft:** `{draft.name}`\n"
        f"**Generated:** {now:%Y-%m-%d %H:%M} IST\n\n"
        f"The earnings lane generated a result but `x/EARNINGS_TREUM_LIVE` is absent.\n"
        f"Review the thread below, then enable auto-posting with:\n\n"
        f"```\ntouch /Users/srijan/loop\\ engineering/content-engine/x/EARNINGS_TREUM_LIVE\n```\n\n"
        f"After that one touch the lane posts fully autonomously — no further input needed.\n\n"
        f"---\n\n**Thread preview:**\n\n{thread_preview}\n\n"
        f"---\n\n*Full draft:* `{draft}`\n"
    )
    print(f"earnings_notify: escalation written → {esc.name}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"earnings_notify: error (non-fatal) — {e}", file=sys.stderr)
    sys.exit(0)
