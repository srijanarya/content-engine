#!/usr/bin/env python3
"""Market-data refresh -> monitor/regime_safe.json (SEBI-safe, index/sector only).

PRIMARY source is Kite (authoritative NSE): NIFTY 50 + India VIX + NSE sector indices, with the daily %
change taken from Kite's net_change/prior-close — correctly signed by construction. This replaces the old
Yahoo `chartPreviousClose` path, which returned a GARBAGE prior close for NSE indices and inverted the
sign (it published a +0.83% green day as a -0.61% red day on 2026-06-24). Yahoo is now used ONLY for the
long daily-close history feeding 75-EMA distance + Wilder ADX/DMI (that close series is reliable; only the
meta prevClose was junk). If Kite is unavailable, we FAIL CLOSED — no regime_safe.json is written, so the
wrap refuses to post (no post beats a wrong post). A Kite-vs-Yahoo close cross-check is a second hard stop.
NEVER emits a per-stock field, index and sector level only.

  python3 monitor/public_market_refresh.py            # fetch (Kite + Yahoo) + write regime_safe.json
  python3 monitor/public_market_refresh.py --selfcheck # offline math check (no network)
"""
from __future__ import annotations
import json, sys
from datetime import datetime, date
from pathlib import Path
from urllib.request import Request, urlopen

ENGINE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ENGINE_DIR))
sys.path.insert(0, str(Path(__file__).parent))  # so `from kite_quotes import ...` works when imported too
OUT = Path(__file__).parent / "regime_safe.json"

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d"
# Sector + index numbers now come from Kite (monitor/kite_quotes.py); Yahoo only serves NIFTY daily-close
# history for EMA75/ADX14 below. The old Yahoo sector map is gone — its prevClose was the junk that lied.


def _fetch(sym, rng="1y"):
    req = Request(CHART.format(sym=sym, rng=rng), headers=UA)
    with urlopen(req, timeout=15) as r:
        return json.load(r)["chart"]["result"][0]


def _ema(values, period):
    k = 2 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


def _adx(highs, lows, closes, period=14):
    """Wilder ADX/+DI/-DI. Returns (adx, +di, -di) or (None,None,None) if too little history."""
    n = len(closes)
    if n < period * 2 + 1:
        return None, None, None
    trs, pdm, mdm = [], [], []
    for i in range(1, n):
        up, dn = highs[i] - highs[i - 1], lows[i - 1] - lows[i]
        pdm.append(up if (up > dn and up > 0) else 0.0)
        mdm.append(dn if (dn > up and dn > 0) else 0.0)
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))

    def wilder(x):
        s = [sum(x[:period])]
        for v in x[period:]:
            s.append(s[-1] - s[-1] / period + v)
        return s

    atr, spdm, smdm = wilder(trs), wilder(pdm), wilder(mdm)
    pdi = [100 * spdm[i] / atr[i] if atr[i] else 0.0 for i in range(len(atr))]
    mdi = [100 * smdm[i] / atr[i] if atr[i] else 0.0 for i in range(len(atr))]
    dx = [100 * abs(pdi[i] - mdi[i]) / ((pdi[i] + mdi[i]) or 1) for i in range(len(atr))]
    if len(dx) < period:
        return None, None, None
    adx = sum(dx[:period]) / period
    for v in dx[period:]:
        adx = (adx * (period - 1) + v) / period
    return round(adx, 2), round(pdi[-1], 2), round(mdi[-1], 2)


def _clean_ohlc(res):
    q = res["indicators"]["quote"][0]
    h, l, c = q["high"], q["low"], q["close"]
    H, L, C = [], [], []
    for i in range(len(c)):
        if None in (h[i], l[i], c[i]):
            continue
        H.append(h[i]); L.append(l[i]); C.append(c[i])
    return H, L, C


def build_regime():
    # PRIMARY (authoritative, correctly-signed): NIFTY / VIX / sectors from Kite. fetch_quotes() raises
    # KiteUnavailable on any creds/auth/network failure -> main() fails closed and writes nothing.
    from kite_quotes import fetch_quotes
    kq = fetch_quotes()
    close = kq["nifty_close"]
    chg = kq["nifty_change_pct"]
    vix = kq["vix"]
    moves = dict(kq["sectors"])

    # Yahoo daily-close HISTORY (reliable series; only its meta prevClose was junk) ONLY for EMA75/ADX14.
    # Best-effort: if Yahoo is down we still publish the Kite headline + sectors, just without trend context.
    ema75 = dist = adx = pdi = mdi = None
    try:
        H, L, C = _clean_ohlc(_fetch("%5ENSEI", "1y"))
        if len(C) >= 80:
            # Cross-source HARD STOP: Yahoo's latest close must agree with Kite's authoritative close.
            if abs(C[-1] - close) / close > 0.005:
                raise RuntimeError(f"Kite NIFTY close {close} disagrees with Yahoo {round(C[-1], 2)} (>0.5%)")
            ema75 = _ema(C, 75)
            dist = round((close - ema75) / ema75 * 100, 2)
            adx, pdi, mdi = _adx(H, L, C, 14)
    except RuntimeError:
        raise  # cross-source disagreement is a hard stop (fail closed)
    except Exception as e:
        print(f"Yahoo history unavailable, EMA/ADX omitted: {e}", file=sys.stderr)

    # Regime from trend side (EMA) + strength (ADX) + direction (DMI). Index-level only.
    if adx is None or ema75 is None:
        regime, bias = "UNCLEAR", "neutral"
    elif adx >= 20 and close > ema75 and pdi >= mdi:
        regime, bias = "TREND-UP", "risk-on"
    elif adx >= 20 and close < ema75 and mdi >= pdi:
        regime, bias = "TREND-DOWN", "risk-off"
    elif adx < 18:
        regime, bias = "RANGE", "neutral"
    else:
        regime, bias = "TRANSITION", "neutral"
    if vix and vix >= 18:
        bias += ", elevated volatility"

    dist_s = f"{dist:+.2f}% vs 75-EMA" if dist is not None else "75-EMA n/a"
    adx_s = f"ADX14 {adx} (+DI {pdi} / -DI {mdi})" if adx is not None else "ADX n/a"
    reason = f"NIFTY {close} ({chg:+.2f}%), {dist_s}. {adx_s}. India VIX {vix}."

    ranked = sorted(moves.items(), key=lambda kv: kv[1], reverse=True)
    top_3 = [k for k, _ in ranked[:3]]
    bottom_3 = [k for k, _ in ranked[-3:]][::-1]

    return {
        "date": date.today().isoformat(),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "regime": regime,
        "regime_reason": reason,
        "market_bias": bias,
        "nifty_close": close,
        "nifty_change_pct": chg,
        "vix": vix,
        "regime_metrics": {
            "nifty_close": close, "nifty_change_pct": chg, "distance_from_ema_pct": dist,
            "vix": vix, "adx14": adx, "plus_di": pdi, "minus_di": mdi,
        },
        "sector_rotation": {
            "top_3": top_3, "bottom_3": bottom_3, "all_sectors_pct": moves,
            "note": f"{len(moves)} NSE sector indices, 1-day % move from Kite (authoritative NSE).",
        },
    }


def main():
    try:
        regime = build_regime()
    except Exception as e:
        # FAIL CLOSED: write NOTHING. No regime_safe.json -> the wrap's freshness gate refuses to post.
        # A missing/old file is safe; a wrong file is the bug we are killing. No silent stale fallback.
        print(f"FAIL CLOSED — no regime_safe.json written ({type(e).__name__}): {e}", file=sys.stderr)
        return 1
    from compliance.scrub import scrub_regime  # self-check: must keep keys, must not raise (fail-closed)
    safe = scrub_regime(regime)
    missing = set(regime) - set(safe)
    assert not missing, f"scrub unexpectedly dropped keys: {missing}"
    OUT.write_text(json.dumps(regime, indent=2))
    print(f"regime_safe.json: {regime['regime']} ({regime['market_bias']}) | "
          f"NIFTY {regime['nifty_close']} ({regime['nifty_change_pct']:+.2f}%) | "
          f"VIX {regime['vix']} | {len(regime['sector_rotation']['all_sectors_pct'])} sectors")
    return 0


def selfcheck():
    # Offline: a clean uptrend must read +DI>-DI and EMA below price. No network.
    C = [100 + i for i in range(120)]
    H = [c + 1 for c in C]; L = [c - 1 for c in C]
    adx, pdi, mdi = _adx(H, L, C, 14)
    assert adx is not None and pdi > mdi, f"uptrend should give +DI>-DI, got {pdi}/{mdi}"
    assert _ema(C, 75) < C[-1], "EMA should trail price in an uptrend"
    print(f"selfcheck OK: adx={adx} +DI={pdi} -DI={mdi}")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        selfcheck()
    else:
        raise SystemExit(main())
