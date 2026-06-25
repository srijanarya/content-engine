#!/usr/bin/env python3
"""Pre-market finance draft (~8:45 IST). Reads regime_safe.json (public data) and generates a
SEBI-safe pre-open note: prior-close regime + what the index/sector setup shows going into the open.
Draft only; the launchd poster (post_x.py) posts the clean ones. Run public_market_refresh.py first.
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from market_common import load_safe_regime, render_finance_draft

GUIDE = """Write a SHORT pre-market note in Srijan's voice for Indian markets (NIFTY).
RULES (SEBI, auto-linted, BLOCKED if violated):
- The % moves shown are the PRIOR session's close (yesterday), NOT today; the market has not opened.
  Frame them as "NIFTY closed [X]% in the prior session" and describe today's setup. NEVER call today
  flat / up / down and NEVER cite a "0.00%" or a "today" move; today has not traded yet.
- INDEX and SECTOR level only. Describe the regime and what the data shows heading into the open.
- NEVER name a single stock with any buy/sell/short/avoid/target view. No per-stock calls at all.
- Observation/education framing ("here is what the setup shows"), never "do X".
- NO em-dashes anywhere.
Output: a tight ~120-word note + a 3-tweet thread. End with no call to action to trade."""


def main():
    safe = load_safe_regime()
    if not safe:
        print("No regime_safe.json. Run public_market_refresh.py first.")
        return 0
    out = render_finance_draft(safe, GUIDE, f"pre-market note {date.today().isoformat()}", "premarket-note")
    print(f"Pre-market draft: {out}" if out else "Pre-market draft blocked by scrub.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
