#!/usr/bin/env python3
"""Evening wrap finance draft (~20:00 IST). Reads regime_safe.json (public data) and generates a
SEBI-safe post-close reflection: how the day's index/sector action fit the regime, what shifted.
Draft only; the launchd poster (post_x.py) posts the clean ones. Run public_market_refresh.py first.
"""
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from market_common import load_safe_regime, render_finance_draft
from daily_market_post import fresh_or_reason  # same date==today + post-close gate the wrap uses

GUIDE = """Write a SHORT evening wrap in Srijan's voice for Indian markets (NIFTY), post-close.
RULES (SEBI, auto-linted, BLOCKED if violated):
- INDEX and SECTOR level only. Reflect on how the day's data fit the regime and what rotated.
- NEVER name a single stock with any buy/sell/short/avoid/target view. No per-stock calls at all.
- Observation/education framing ("here is what the day showed"), never "do X".
- NO em-dashes anywhere.
Output: a tight ~130-word reflection + a 3-tweet thread. End with no call to action to trade."""


def main():
    safe = load_safe_regime()
    if not safe:
        # Loud failure, not a silent success (CLAUDE.md): the refresh should have written regime_safe.json.
        print("FAIL: no regime_safe.json — run public_market_refresh.py first.", file=sys.stderr)
        return 1
    reason = fresh_or_reason(safe, datetime.now())
    if reason:
        # An evening wrap reflects the COMPLETED session; refuse stale or pre-open data (same bug class
        # as the 2026-06-23 daily wrap). No silent stale post.
        print(f"FAIL: refusing a stale/early evening wrap — {reason}", file=sys.stderr)
        return 1
    out = render_finance_draft(safe, GUIDE, f"evening wrap {date.today().isoformat()}", "evening-wrap")
    print(f"Evening wrap draft: {out}" if out else "Evening wrap draft blocked by scrub.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
