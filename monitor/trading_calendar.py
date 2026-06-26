#!/usr/bin/env python3
"""Is today an NSE trading day? The finance lanes must NEVER post a premarket/wrap/evening note on a
holiday or weekend — there is no session, so any "pre-market / heading in" note is wrong (the 2026-06-26
Muharram incident: a premarket note posted on a non-trading day and had to be pulled).

Single source of truth: the aksh trading system's authoritative NSE calendar (quant/market_calendar.py) —
the same one the live trading system trusts to not trade on holidays. Falls back to a weekend-only check
if that calendar is ever unreachable (a weekday with no reachable holiday list is assumed open; the rare
holiday slip is the documented ceiling, and the wrap/evening also get caught by the degenerate-regime gate
because net_change stays 0 on a holiday).

  python3 monitor/trading_calendar.py             # today (exit 0 = trading day, 1 = not)
  python3 monitor/trading_calendar.py 2026-06-26   # a specific date
"""
from __future__ import annotations
import contextlib
import os
import sys
from datetime import date

AKSH = "/Users/srijan/aksh_backtesting_trading"


def is_trading_day(d: date | None = None) -> bool:
    d = d or date.today()
    if d.weekday() >= 5:  # Saturday / Sunday
        return False
    try:
        if AKSH not in sys.path:
            sys.path.insert(0, AKSH)
        # Silence the aksh module's import-time DB/network chatter so it never pollutes the poster output.
        with open(os.devnull, "w") as _n, contextlib.redirect_stderr(_n), contextlib.redirect_stdout(_n):
            from quant.market_calendar import is_trading_day as _aksh_itd  # authoritative NSE holiday list
            return bool(_aksh_itd(d))
    except Exception as e:
        print(f"trading_calendar: aksh NSE calendar unreachable ({type(e).__name__}); weekday fallback",
              file=sys.stderr)
        return True  # weekday, no holiday list reachable -> assume open (documented rare-holiday ceiling)


if __name__ == "__main__":
    d = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    ok = is_trading_day(d)
    print(f"{d}: {'TRADING DAY' if ok else 'NON-TRADING DAY (weekend/holiday)'}")
    raise SystemExit(0 if ok else 1)
