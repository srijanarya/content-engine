#!/usr/bin/env python3
"""Acceptance tests for the value-correctness gate.

test_incident_sign_flip_blocked IS the 2026-06-24 fake-NIFTY incident, locked in as a permanent
regression: a thread claiming a red NIFTY on a green-day regime must never publish. Plain asserts,
run with `python3 compliance/test_value_check.py` (no framework).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # content-engine root
from compliance.value_check import verify_values

# A real green-day regime (the 2026-06-24 shape): NIFTY +0.83%, mixed sectors.
GREEN_REGIME = {
    "nifty_change_pct": 0.83,
    "sector_rotation": {"all_sectors_pct": {
        "REALTY": 2.17, "IT": 2.05, "BANK": 1.69, "ENERGY": -0.89, "PSE": -0.48, "AUTO": -0.42,
    }},
}


def test_incident_sign_flip_blocked():
    # THE incident: regime says +0.83% (green), the draft claims -0.61% (red). Must block on sign.
    text = "NIFTY closed -0.61% at 24021.65 today. Risk-off print."
    ok, reason = verify_values(text, GREEN_REGIME)
    assert not ok and "NIFTY" in reason and "sign" in reason.lower(), reason


def test_matching_numbers_pass():
    text = ("NIFTY closed +0.83% at 24021.65 today.\n"
            "Leaders: REALTY +2.17%, IT +2.05%, BANK +1.69%.\n"
            "Laggards: ENERGY -0.89%, PSE -0.48%, AUTO -0.42%.")
    ok, reason = verify_values(text, GREEN_REGIME)
    assert ok, reason


def test_rounding_within_tolerance_passes():
    text = "NIFTY closed +0.8% at 24021 today."  # 0.8 vs regime 0.83, within TOL
    ok, reason = verify_values(text, GREEN_REGIME)
    assert ok, reason


def test_sector_sign_mismatch_blocked():
    # ENERGY is -0.89% in the regime; the draft paints it green. Must block.
    text = "NIFTY closed +0.83% today. Leaders: ENERGY +0.89%."
    ok, reason = verify_values(text, GREEN_REGIME)
    assert not ok and "ENERGY" in reason, reason


def test_no_regime_blocks_finance():
    ok, reason = verify_values("NIFTY closed +0.83% today.", None)
    assert not ok and "regime" in reason.lower(), reason


def test_unicode_minus_treated_negative():
    text = "NIFTY closed −0.61% at 24021.65 today."  # U+2212 MINUS SIGN, not a hyphen
    ok, reason = verify_values(text, GREEN_REGIME)
    assert not ok, reason


def test_english_it_not_confused_with_sector_it():
    # The English word "It" must not be parsed as sector IT. Here IT is correctly +2.05%.
    text = "NIFTY closed +0.83% today. It was a range day. IT +2.05% led the tape."
    ok, reason = verify_values(text, GREEN_REGIME)
    assert ok, reason


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok {_name}")
    print("value_check selfcheck OK")
