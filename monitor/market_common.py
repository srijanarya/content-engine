#!/usr/bin/env python3
"""Shared SEBI-safe render path for the daily finance products (pre-market, post-market wrap, evening
wrap). One place loads the scrubbed regime, builds context, and runs scrub -> generate -> disclaimer.
The actual gates live in compliance/scrub.py + generate_draft's hard lint; this only routes through
them so every product gates identically. build_context mirrors daily_market_post.py's (kept compatible).
"""
from __future__ import annotations
import json, os, sys
from pathlib import Path
from datetime import date

ENGINE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ENGINE_DIR))
DEFAULT_SAFE = Path(__file__).parent / "regime_safe.json"


def load_safe_regime() -> dict | None:
    p = os.environ.get("REGIME_JSON") or str(DEFAULT_SAFE)
    if Path(p).exists():
        try:
            return json.loads(Path(p).read_text())
        except Exception as e:
            print(f"regime read failed {p}: {e}", file=sys.stderr)
    return None


def build_context(safe: dict) -> str:
    m = safe.get("regime_metrics", {})
    sr = safe.get("sector_rotation", {})
    lines = [
        f"Date: {safe.get('date','today')}",
        f"Market regime: {safe.get('regime','n/a')}. {safe.get('regime_reason','')}",
        f"Nifty close: {m.get('nifty_close','n/a')} ({m.get('nifty_change_pct','n/a')}%), "
        f"vs 75-EMA: {m.get('distance_from_ema_pct','n/a')}%",
        f"VIX: {m.get('vix','n/a')}, ADX14: {m.get('adx14','n/a')}, "
        f"+DI {m.get('plus_di','')}/-DI {m.get('minus_di','')}",
        f"Sector rotation. Leaders: {sr.get('top_3', [])}, laggards: {sr.get('bottom_3', [])}",
        f"All sectors %: {sr.get('all_sectors_pct', {})}",
        f"Note: {sr.get('note','')}",
    ]
    return "\n".join(str(x) for x in lines)


def render_finance_draft(safe: dict, guide: str, topic: str, slug: str) -> str | None:
    """scrub (fail-closed) -> generate in voice (hard-lint inside) -> append short disclaimer.
    Returns the draft path, or None if scrub refused. The draft itself carries status
    needs-review/BLOCKED-sebi from generate(); the launchd poster only posts clean ones."""
    from compliance.scrub import scrub_regime
    from compliance.lint import is_safe
    from generate_draft import generate

    try:
        safe = scrub_regime(safe)
    except RuntimeError as e:
        print(f"SCRUB refused to publish: {e}", file=sys.stderr)
        return None
    assert is_safe(safe), "scrubbed regime failed the linter, aborting (should never happen)"

    context = build_context(safe) + "\n\n" + guide
    out = generate("finance", topic, context, slug=slug)

    disc = (ENGINE_DIR / "compliance" / "disclaimer.md").read_text()
    # Take ONLY the quoted disclaimer lines, not the "## Short form" heading, whose em-dash
    # would otherwise land in the draft and trip the no-em-dash rule.
    section = disc.split("## Short form")[1].split("##")[0] if "## Short form" in disc else ""
    short = "\n".join(l for l in section.splitlines() if l.strip().startswith(">")).strip()
    if short and "BLOCKED-sebi" not in Path(out).read_text():
        with open(out, "a") as f:
            f.write("\n\n---\n" + short + "\n")
    return out


if __name__ == "__main__":
    # Self-check: build_context tolerates a minimal regime without throwing.
    ctx = build_context({"date": "2026-06-22", "regime": "RANGE", "regime_metrics": {"nifty_close": 1}})
    assert "RANGE" in ctx and "Nifty close" in ctx, ctx
    print("market_common OK")
