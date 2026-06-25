#!/usr/bin/env python3
"""Authoritative NSE index/sector/VIX quotes from Kite (Zerodha) for the SEBI-safe finance posts.

Why this exists: the old Yahoo path computed daily % change from Yahoo's `chartPreviousClose` meta
field, which is GARBAGE for NSE indices (it flaps between wrong values — e.g. it reported NIFTY's prior
close as 24,168 / 23,719 when the real prior close was 23,824). That inverted the SIGN of the change and
published a green day as a red one. Kite's `net_change` + `ohlc.close` are the real NSE numbers, so the
change is exact and correctly signed.

Reuses the LIVE Kite access token the trading system already refreshes daily (TOTP autologin). We read
the token, never a frozen data file — so this is NOT the 2026-06-23 stale-private-file coupling, it is a
live authoritative API. If the token is stale / Kite is unreachable, we raise KiteUnavailable so the
caller can FAIL CLOSED (no post beats a wrong post).

  python3 monitor/kite_quotes.py              # live fetch, print NIFTY/VIX/sectors
  python3 monitor/kite_quotes.py --selfcheck  # offline: change-sign math (no network, no creds)
"""
from __future__ import annotations
import os, sys
from pathlib import Path

# engine sector key -> Kite tradingsymbol (NSE). Unresolved symbols are SKIPPED + logged, never faked.
SECTORS = {
    "IT": "NIFTY IT", "BANK": "NIFTY BANK", "AUTO": "NIFTY AUTO", "PHARMA": "NIFTY PHARMA",
    "FMCG": "NIFTY FMCG", "METAL": "NIFTY METAL", "REALTY": "NIFTY REALTY", "ENERGY": "NIFTY ENERGY",
    "PSUBANK": "NIFTY PSU BANK", "MEDIA": "NIFTY MEDIA", "INFRA": "NIFTY INFRA", "PSE": "NIFTY PSE",
}
# Default to the trading repo's .env (the one place the access token is kept fresh). Override w/ KITE_ENV_PATH.
DEFAULT_ENV = "/Users/srijan/aksh_backtesting_trading/.env"


class KiteUnavailable(RuntimeError):
    """Raised on any creds/auth/network failure so the finance posts can fail closed."""


def _change_pct(q: dict) -> float | None:
    """Daily % change from the AUTHORITATIVE fields: net_change over the prior close (ohlc.close).
    Correctly signed by construction — this is the whole point of the fix."""
    prev = (q.get("ohlc") or {}).get("close")
    nc = q.get("net_change")
    if not prev or nc is None:
        return None
    return round(nc / prev * 100, 2)


def _prior_session_change(k, token) -> float | None:
    """Close-over-close % of the last COMPLETED daily candle. Used PRE-OPEN, when the live quote's
    net_change is 0 for everything and publishing it would falsely paint the tape flat (the 2026-06-25
    premarket incident). Filtered to candles strictly BEFORE today, so it always returns the prior
    session's real, correctly-signed move regardless of whether a partial today-candle exists yet."""
    from datetime import datetime, timedelta
    to_d = datetime.now()
    candles = k.historical_data(int(token), to_d - timedelta(days=12), to_d, "day")
    closes = [c["close"] for c in candles if c.get("close") and c["date"].date() < to_d.date()]
    if len(closes) < 2 or not closes[-2]:
        return None
    return round((closes[-1] - closes[-2]) / closes[-2] * 100, 2)


def _load_creds() -> tuple[str, str]:
    key, tok = os.environ.get("KITE_API_KEY"), os.environ.get("KITE_ACCESS_TOKEN")
    if key and tok:
        return key, tok
    p = Path(os.environ.get("KITE_ENV_PATH") or DEFAULT_ENV)
    if not p.exists():
        raise KiteUnavailable(f"no Kite creds in env and no env file at {p}")
    env = {}
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    key, tok = env.get("KITE_API_KEY"), env.get("KITE_ACCESS_TOKEN")
    if not key or not tok:
        raise KiteUnavailable(f"KITE_API_KEY / KITE_ACCESS_TOKEN missing in {p}")
    return key, tok


def fetch_quotes() -> dict:
    """Authoritative index/sector/VIX snapshot from Kite. Raises KiteUnavailable on ANY failure.
    Returns {nifty_close, nifty_change_pct, vix, sectors:{KEY:pct}} — real, correctly-signed NSE data."""
    try:
        from kiteconnect import KiteConnect
    except ImportError as e:
        raise KiteUnavailable(f"kiteconnect not installed: {e}")
    key, tok = _load_creds()
    syms = ["NSE:NIFTY 50", "NSE:INDIA VIX"] + [f"NSE:{s}" for s in SECTORS.values()]
    try:
        k = KiteConnect(api_key=key)
        k.set_access_token(tok)
        q = k.quote(syms)
    except Exception as e:  # TokenException, network, etc. -> fail closed
        raise KiteUnavailable(f"Kite quote failed ({type(e).__name__}): {str(e)[:160]}")

    nifty = q.get("NSE:NIFTY 50")
    if not nifty or _change_pct(nifty) is None:
        raise KiteUnavailable("NIFTY 50 quote missing or has no prior close")
    vix_q = q.get("NSE:INDIA VIX") or {}
    sectors = {}
    for keyname, sym in SECTORS.items():
        sq = q.get(f"NSE:{sym}")
        pct = _change_pct(sq) if sq else None
        if pct is not None:
            sectors[keyname] = pct
        else:
            print(f"sector {keyname} ({sym}) skipped: no Kite quote", file=sys.stderr)
    if len(sectors) < 6:  # half the sectors missing => something is wrong, don't publish a thin/odd picture
        raise KiteUnavailable(f"only {len(sectors)}/12 sectors resolved from Kite")

    nifty_change = _change_pct(nifty)
    market_open = True
    # PRE-OPEN GUARD: before the open the live quote has net_change=0 for everything, so NIFTY and every
    # sector read 0.0%. Publishing that as a "flat / 0.00%" tape is FALSE; it buries the prior session's
    # real move (the 2026-06-25 premarket incident). When NIFTY shows no live move, fall back to the LAST
    # COMPLETED daily candle's close-over-close % for NIFTY and each sector, so the pre-market note
    # describes yesterday's actual close. Fail closed if that history is unavailable.
    if (nifty.get("net_change") in (0, 0.0, None)) or os.environ.get("KITE_FORCE_PREOPEN"):
        market_open = False
        try:
            nc = _prior_session_change(k, nifty["instrument_token"])
            if nc is None:
                raise KiteUnavailable("pre-open: no prior-session NIFTY candle for the fallback")
            nifty_change = nc
            for keyname, sym in SECTORS.items():
                sq = q.get(f"NSE:{sym}")
                if sq and keyname in sectors:
                    pc = _prior_session_change(k, sq["instrument_token"])
                    if pc is not None:
                        sectors[keyname] = pc
        except KiteUnavailable:
            raise
        except Exception as e:
            raise KiteUnavailable(f"pre-open fallback failed ({type(e).__name__}): {str(e)[:120]}")

    return {
        "nifty_close": round(nifty["last_price"], 2),
        "nifty_change_pct": nifty_change,
        "vix": round(vix_q.get("last_price"), 2) if vix_q.get("last_price") else None,
        "sectors": sectors,
        "market_open": market_open,
    }


def _selfcheck():
    # The exact regression: a POSITIVE net_change must produce a POSITIVE % (green day stays green).
    up = {"net_change": 197.55, "ohlc": {"close": 23824.1}}
    assert _change_pct(up) == 0.83, _change_pct(up)          # the real 2026-06-24 NIFTY: +0.83%, NOT -0.61%
    dn = {"net_change": -146.35, "ohlc": {"close": 24168.0}}
    assert _change_pct(dn) == -0.61, _change_pct(dn)         # a real down day still reads negative
    assert _change_pct({"net_change": 0, "ohlc": {"close": 100}}) == 0.0
    assert _change_pct({"ohlc": {"close": 0}}) is None       # no prior close -> None, never a fake 0/inf
    assert _change_pct({"net_change": 5}) is None            # missing ohlc -> None
    # PRE-OPEN fallback: prior completed session's close-over-close, with any partial today-candle dropped.
    from datetime import datetime, timedelta
    _t = datetime.now()

    class _FakeK:
        def historical_data(self, *a, **kw):
            return [{"date": _t - timedelta(days=2), "close": 23824.1},
                    {"date": _t - timedelta(days=1), "close": 24021.65},
                    {"date": _t, "close": 24050.0}]  # today's partial candle MUST be ignored
    assert _prior_session_change(_FakeK(), 256265) == 0.83, _prior_session_change(_FakeK(), 256265)
    print("kite_quotes selfcheck OK (sign-correct change; pre-open prior-session fallback)")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck()
    else:
        d = fetch_quotes()
        print(f"NIFTY {d['nifty_close']} ({d['nifty_change_pct']:+.2f}%) | VIX {d['vix']} | "
              f"{len(d['sectors'])} sectors: {d['sectors']}")
