#!/usr/bin/env python3
"""Render the latest finance draft into a faceless short and STAGE it for posting (never auto-posts).

Wired as the `video` cron lane. Generation is autonomous + safe (no outward action); the upload itself
stays a manual/irreversible step Srijan does. Output: video/out/<stem>.mp4 + <stem>.caption.txt, plus a
one-line digest flag so the morning ops digest surfaces "a video is ready to post".
"""
import glob
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
DRAFTS = ENGINE / "drafts"
OUT = HERE / "out"
PY = sys.executable or "/opt/homebrew/bin/python3"


def latest_finance_draft() -> Path | None:
    cands = sorted(DRAFTS.glob("*finance*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return next((p for p in cands if "LINKEDIN CAROUSEL" in p.read_text()), None)


def caption(md: str) -> str:
    m = re.search(r"X / TWITTER THREAD.*?\*\*1/\*\*\s*(.+?)\n\n", md, re.S)
    hook = m.group(1).strip() if m else "Today's market read."
    return f"{hook}\n\nData/education only. Not investment advice.\n#Nifty #StockMarket #India"


def main() -> int:
    d = latest_finance_draft()
    if not d:
        print("no finance draft with a LINKEDIN CAROUSEL to render"); return 1
    rc = subprocess.run([PY, str(HERE / "make_video.py"), str(d), "--max-slides", "6"]).returncode
    if rc:
        return rc
    mp4 = OUT / (d.stem + ".mp4")
    (OUT / (d.stem + ".caption.txt")).write_text(caption(d.read_text()))
    log = Path.home() / "autonomy" / "logs" / f"x-activity-{datetime.now():%Y-%m-%d}.md"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as f:
        f.write(f"{datetime.now():%H:%M} VIDEO READY to post: {mp4.name} (+caption) — manual upload\n")
    print(f"staged {mp4} (+ caption) — ready for manual upload")
    return 0


if __name__ == "__main__":
    sys.exit(main())
