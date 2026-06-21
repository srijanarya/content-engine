#!/usr/bin/env python3
"""
Compliance scrubber — turns a personal/trading regime artifact into a SEBI-safe public version.

Allowlist approach (safer than denylist): keep ONLY fields known to be on the safe side of the
line — market data, broad-index/regime description, sector-level rotation. Everything per-stock
(fno_universe, aksh_strong_buys) and every personal trading parameter (max_positions, loss
multipliers) is dropped. The output is then re-linted; if a block survives, we raise rather than
publish — fail closed, never fail open.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lint import report as lint_report  # noqa: E402

# Fields safe to publish from a post_market_regime.json / market_intelligence.json.
REGIME_ALLOW = {
    "date", "generated_at", "regime", "regime_reason", "regime_metrics", "sector_rotation",
    "market_bias", "vix", "nifty_close", "nifty_change_pct",
}
# Inside regime_metrics, everything is index-level data — safe.
# Inside sector_rotation, sector-level — safe. But strip any embedded per-stock note via lint.


def scrub_regime(data: dict) -> dict:
    """Return a SEBI-safe subset of a regime artifact. Fails closed if a block survives."""
    out = {k: v for k, v in data.items() if k in REGIME_ALLOW}

    # Defense in depth: re-lint the scrubbed output. A surviving BLOCK = a bug in the allowlist.
    blocks = [v for v in lint_report(out) if v["severity"] == "block"]
    if blocks:
        raise RuntimeError(
            "scrub_regime left a per-stock call in the output — refusing to publish. "
            f"Offenders: {[b.get('path') for b in blocks]}"
        )
    return out


def scrub_file(in_path: str, out_path: str | None = None) -> dict:
    data = json.loads(Path(in_path).read_text())
    safe = scrub_regime(data)
    if out_path:
        Path(out_path).write_text(json.dumps(safe, indent=2))
    return safe


def demo():
    sample = {
        "date": "2026-05-12", "regime": "EXIT",
        "regime_reason": "Nifty -1.62% to 23,430, below EMA75. VIX 19.3.",
        "regime_metrics": {"nifty_close": 23430.55, "vix": 19.28, "adx14": 7.52},
        "sector_rotation": {"top_3": ["METAL", "ENERGY"], "bottom_3": ["IT", "REALTY"]},
        "max_positions": 1, "daily_loss_multiplier": 0.5,
        "fno_universe": [{"symbol": "HDFCBANK", "side_bias": "long-only", "sl_pct": 0.8}],
        "aksh_strong_buys": [{"symbol": "DYNAMIC", "score": 95.0}],
    }
    safe = scrub_regime(sample)
    assert "fno_universe" not in safe, "must drop per-stock fno_universe"
    assert "aksh_strong_buys" not in safe, "must drop strong_buys"
    assert "max_positions" not in safe, "must drop personal trading params"
    assert safe["regime"] == "EXIT" and "regime_metrics" in safe, "must keep regime + data"
    assert "sector_rotation" in safe, "must keep sector-level rotation"
    from lint import is_safe
    assert is_safe(safe), "scrubbed output must pass the linter"
    print("scrub demo: all assertions passed →", json.dumps(safe)[:120], "...")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] != "demo":
        out = sys.argv[2] if len(sys.argv) > 2 else None
        result = scrub_file(sys.argv[1], out)
        print(json.dumps(result, indent=2) if not out else f"scrubbed → {out}")
    else:
        demo()
