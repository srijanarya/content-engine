#!/usr/bin/env python3
"""Value-correctness gate: a finance thread's published numbers must match the Kite-sourced regime.

This is the backstop the 2026-06-24 fake-NIFTY incident lacked. The root cause then was upstream
(Yahoo's prevClose inverted a +0.83% green day to -0.61%); that data bug is fixed at the source, but
this gate makes a sign-flipped or mis-transcribed index/sector % impossible to PUBLISH whatever the
cause — bad LLM transcription, a data-layer regression, or a stale regime. It cross-checks the prose
against the structured truth it was generated from.

Scope: the NIFTY headline % and any named NSE sector %. A sign mismatch, or a magnitude drift > TOL,
blocks. ponytail: regex extraction, no NLP. Ceiling — a sector written lowercase or a number phrased
without a sign-glyph is skipped (best-effort), but the NIFTY headline (the incident class) is always
checked; widen the patterns if a real draft ever dodges them.

  python3 compliance/value_check.py --selfcheck   # offline asserts (incident + happy path)
"""
from __future__ import annotations
import re
import sys

TOL = 0.1  # absolute percentage-point tolerance for rounding (regime 0.834 -> text "+0.83%")


def _to_float(sign: str, num: str) -> float:
    v = float(num)
    return -v if sign in ("-", "−") else v  # ASCII hyphen OR U+2212 MINUS SIGN -> negative


def _pct_after(label_re: str, text: str, flags: int) -> float | None:
    """First signed %-number appearing right after `label_re`, before a sentence break (. or newline).
    Non-greedy so it grabs the nearest %, e.g. 'NIFTY closed +0.83% at 24021.65' -> +0.83, not 24021."""
    m = re.search(rf"\b{label_re}\b[^.\n]*?([+\-−]?)(\d+\.?\d*)\s*%", text, flags)
    return _to_float(m.group(1), m.group(2)) if m else None


def _disagrees(claimed: float, actual: float) -> bool:
    # Sign disagreement (when the actual move is not ~flat), or magnitude beyond rounding tolerance.
    if (claimed >= 0) != (actual >= 0) and abs(actual) >= 0.05:
        return True
    return abs(claimed - actual) > TOL


def verify_values(text: str, regime: dict | None) -> tuple[bool, str]:
    """(ok, reason). Blocks a finance thread whose published % disagrees in SIGN, or by > TOL in
    magnitude, with the regime. regime=None -> blocked (cannot verify finance numbers with no source
    of truth). reason names the failing field, e.g. 'NIFTY sign mismatch: text -0.61% vs regime +0.83%'."""
    if not regime:
        return False, "no regime to verify finance numbers against"

    # 0) Degenerate pre-open snapshot: NIFTY ~0% AND every sector ~0%. A real intraday/close read never
    #    has all sectors at exactly 0.00; this signature means the regime was captured before the market
    #    moved (the 08:45 pre-open refresh), so a "flat / 0.00%" narrative built on it is FALSE: it
    #    silently paints yesterday's close as a flat tape. Fail closed. (2026-06-25 premarket incident.)
    _nifty = regime.get("nifty_change_pct")
    _sectors = (regime.get("sector_rotation") or {}).get("all_sectors_pct") or {}
    if _nifty is not None and _sectors and abs(_nifty) < 0.005 and all(abs(v) < 0.005 for v in _sectors.values()):
        return False, ("degenerate pre-open regime: NIFTY 0.00% and all sectors 0.0% "
                       "(snapshot taken before the market moved); refusing to publish a flat read")

    # 1) NIFTY headline % — the incident's exact failure class. Case-insensitive (label is distinctive).
    nifty = regime.get("nifty_change_pct")
    claimed = _pct_after("NIFTY", text, re.IGNORECASE)
    if claimed is not None and nifty is not None and _disagrees(claimed, nifty):
        kind = "sign mismatch" if (claimed >= 0) != (nifty >= 0) else "value mismatch"
        return False, f"NIFTY {kind}: text {claimed:+.2f}% vs regime {nifty:+.2f}%"

    # 2) Named NSE sector %s. Case-SENSITIVE: codes are uppercase (IT, PSE, AUTO), so the English word
    #    "it" can never be mistaken for sector IT. A sector not mentioned in the text is simply skipped.
    sectors = (regime.get("sector_rotation") or {}).get("all_sectors_pct") or {}
    for name, actual in sectors.items():
        claimed = _pct_after(re.escape(name), text, 0)
        if claimed is None or actual is None:
            continue
        if _disagrees(claimed, actual):
            kind = "sign mismatch" if (claimed >= 0) != (actual >= 0) else "value mismatch"
            return False, f"{name} {kind}: text {claimed:+.2f}% vs regime {actual:+.2f}%"

    return True, ""


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        # The incident, inline: green regime, red prose -> must block.
        r = {"nifty_change_pct": 0.83, "sector_rotation": {"all_sectors_pct": {"ENERGY": -0.89}}}
        ok, why = verify_values("NIFTY closed -0.61% today.", r)
        assert not ok and "NIFTY" in why, why
        ok, _ = verify_values("NIFTY closed +0.83% today. ENERGY -0.89%.", r)
        assert ok
        # Degenerate pre-open snapshot (all-zero) must block (2026-06-25 premarket incident).
        deg = {"nifty_change_pct": 0.0, "sector_rotation": {"all_sectors_pct": {"IT": 0.0, "BANK": 0.0}}}
        ok, why = verify_values("NIFTY closed 24021.65, dead flat, Change 0.00%.", deg)
        assert not ok and "pre-open" in why, why
        print("value_check selfcheck OK")
    else:
        print(__doc__)
