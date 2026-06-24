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
    return {
        "nifty_close": round(nifty["last_price"], 2),
        "nifty_change_pct": _change_pct(nifty),
        "vix": round(vix_q.get("last_price"), 2) if vix_q.get("last_price") else None,
        "sectors": sectors,
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
    print("kite_quotes selfcheck OK (sign-correct change; no fabricated values)")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck()
    else:
        d = fetch_quotes()
        print(f"NIFTY {d['nifty_close']} ({d['nifty_change_pct']:+.2f}%) | VIX {d['vix']} | "
              f"{len(d['sectors'])} sectors: {d['sectors']}")
