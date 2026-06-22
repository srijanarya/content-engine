#!/usr/bin/env python3
"""Public market-data refresh -> monitor/regime_safe.json (SEBI-safe, index/sector only).

Decouples the daily finance posts from the stale private trading artifact. Pulls NIFTY 50 + India VIX
+ NSE sector indices from Yahoo Finance's public chart endpoint (no key), computes a regime from
75-EMA distance + Wilder ADX/DMI, ranks sector 1-day moves, and writes a regime shaped to
compliance/scrub.py's allowlist. Runs scrub_regime() on its own output as a fail-closed self-check.
NEVER emits a per-stock field, index and sector level only.

  python3 monitor/public_market_refresh.py            # fetch + write regime_safe.json
  python3 monitor/public_market_refresh.py --selfcheck # offline math check (no network)
"""
from __future__ import annotations
import json, sys
from datetime import datetime, date
from pathlib import Path
from urllib.request import Request, urlopen

ENGINE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ENGINE_DIR))
OUT = Path(__file__).parent / "regime_safe.json"

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d"

# NSE sector indices Yahoo serves (URL-encoded ^). Unresolved symbols are SKIPPED + logged, never faked.
SECTORS = {
    "IT": "%5ECNXIT", "BANK": "%5ENSEBANK", "AUTO": "%5ECNXAUTO", "PHARMA": "%5ECNXPHARMA",
    "FMCG": "%5ECNXFMCG", "METAL": "%5ECNXMETAL", "REALTY": "%5ECNXREALTY", "ENERGY": "%5ECNXENERGY",
    "PSUBANK": "%5ECNXPSUBANK", "MEDIA": "%5ECNXMEDIA", "INFRA": "%5ECNXINFRA", "PSE": "%5ECNXPSE",
}


def _fetch(sym, rng="1y"):
    req = Request(CHART.format(sym=sym, rng=rng), headers=UA)
    with urlopen(req, timeout=15) as r:
        return json.load(r)["chart"]["result"][0]


def _meta_change(sym):
    """(price, day_pct) from the chart meta; (None, None) if the symbol didn't resolve."""
    m = _fetch(sym, "5d")["meta"]
    price, prev = m.get("regularMarketPrice"), m.get("chartPreviousClose") or m.get("previousClose")
    if price is None or not prev:
        return None, None
    return round(price, 2), round((price - prev) / prev * 100, 2)


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
    # Daily change from the 5d meta (chartPreviousClose on a 1y range is a YEAR ago, not yesterday).
    close, chg = _meta_change("%5ENSEI")
    if close is None:
        raise RuntimeError("NIFTY (^NSEI) did not resolve")
    nifty = _fetch("%5ENSEI", "1y")  # 1y history is only for EMA75 / ADX14
    H, L, C = _clean_ohlc(nifty)
    if len(C) < 80:
        raise RuntimeError(f"insufficient NIFTY history: {len(C)} candles")
    ema75 = _ema(C, 75)
    dist = round((close - ema75) / ema75 * 100, 2)
    adx, pdi, mdi = _adx(H, L, C, 14)
    vix, _ = _meta_change("%5EINDIAVIX")

    # Regime from trend side (EMA) + strength (ADX) + direction (DMI). Index-level only.
    if adx is None:
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

    reason = (f"NIFTY {close} ({chg:+.2f}%), {dist:+.2f}% vs 75-EMA. "
              f"ADX14 {adx} (+DI {pdi} / -DI {mdi}). India VIX {vix}.")

    moves = {}
    for name, sym in SECTORS.items():
        try:
            _, pct = _meta_change(sym)
            if pct is not None:
                moves[name] = pct
        except Exception as e:
            print(f"sector {name} skipped: {e}", file=sys.stderr)
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
            "note": f"{len(moves)} NSE sector indices, 1-day % move from public data.",
        },
    }


def main():
    regime = build_regime()
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
