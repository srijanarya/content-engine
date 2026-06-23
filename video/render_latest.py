#!/usr/bin/env python3
"""Render the latest draft for a lane into a faceless short and STAGE it (optionally upload).

Lanes: finance (default, backward-compatible) and ai. Each lane picks its draft glob, caption
hashtags, and YouTube channel. Generation is autonomous + safe; --upload pushes to YouTube as
unlisted by default (flip to --privacy public in full-auto mode). Output: video/out/<stem>.mp4 +
<stem>.caption.txt + a one-line digest flag for the morning ops digest.

  python3 video/render_latest.py                      # finance, stage only
  python3 video/render_latest.py --lane ai --upload   # AI channel, upload unlisted
"""
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

LANES = {
    "finance": {"glob": "*finance*.md", "channel": "finance",
                "tags": "#Nifty #StockMarket #India",
                "disclaim": "Data/education only. Not investment advice."},
    "ai": {"glob": "*-ai-*.md", "channel": "ai",
           "tags": "#AI #LLM #Claude #coding",
           "disclaim": "Independent model evals. Reproducible runs, documented failure modes."},
}


def _flag(name: str, default=None):
    for i, a in enumerate(sys.argv):
        if a == name and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def latest_draft(glob: str) -> Path | None:
    cands = sorted(DRAFTS.glob(glob), key=lambda p: p.stat().st_mtime, reverse=True)
    return next((p for p in cands if "LINKEDIN CAROUSEL" in p.read_text()), None)


def caption(md: str, disclaim: str = "Data/education only. Not investment advice.",
            tags: str = "#Nifty #StockMarket #India") -> str:
    m = re.search(r"X / TWITTER THREAD.*?\*\*1/\*\*\s*(.+?)\n\n", md, re.S)
    hook = m.group(1).strip() if m else "Today's read."
    return f"{hook}\n\n{disclaim}\n{tags}"


def main() -> int:
    lane = _flag("--lane", "finance")
    if lane not in LANES:
        print(f"unknown lane {lane!r}; choose from {list(LANES)}"); return 2
    cfg = LANES[lane]
    d = latest_draft(cfg["glob"])
    if not d:
        print(f"no {lane} draft with a LINKEDIN CAROUSEL to render"); return 1
    rc = subprocess.run([PY, str(HERE / "make_video.py"), str(d), "--max-slides", "6"]).returncode
    if rc:
        return rc
    mp4 = OUT / (d.stem + ".mp4")
    (OUT / (d.stem + ".caption.txt")).write_text(caption(d.read_text(), cfg["disclaim"], cfg["tags"]))
    # --upload uploads to YouTube (unlisted unless --privacy public); default stays stage-only.
    if "--upload" in sys.argv:
        rc = subprocess.run([PY, str(HERE / "upload_youtube.py"), str(mp4),
                             "--channel", cfg["channel"], "--privacy", _flag("--privacy", "unlisted")]).returncode
        action = f"UPLOADED ({lane}/{cfg['channel']})" if rc == 0 else "upload FAILED — manual"
    else:
        action = "manual upload"
    log = Path.home() / "autonomy" / "logs" / f"x-activity-{datetime.now():%Y-%m-%d}.md"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as f:
        f.write(f"{datetime.now():%H:%M} VIDEO READY [{lane}]: {mp4.name} (+caption) — {action}\n")
    print(f"staged {mp4} (+ caption) [{lane}] — {action}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
