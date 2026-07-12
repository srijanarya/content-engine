#!/usr/bin/env python3
"""Propose recently filing earnings companies missing from the curated universe.

This is deliberately a human-review lane: it writes a morning-digest escalation,
but never changes ``earnings_universe.txt`` itself.  Failures are non-fatal so a
missing filings database cannot interrupt the rest of the monitor.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ENGINE_DIR = Path(__file__).parent.parent
UNIVERSE_PATH = ENGINE_DIR / "monitor" / "earnings_universe.txt"
PROPOSED_PATH = ENGINE_DIR / "monitor" / "universe_proposed.json"
ESC_DIR = Path.home() / "autonomy" / "escalations"

# Grow this when a false proposal shows up.
ALIASES: dict[str, str] = {
    "avenue supermarts": "DMART",
    "ltm": "LTM",
    "hcl technologies": "HCLTECH",
    "tata consultancy": "TCS",
}


def _db_path() -> Path:
    default = Path.home() / "aksh_backtesting_trading" / "data" / "realtime_filings_log.db"
    return Path(os.environ.get("AKSH_FILINGS_DB", str(default)))


def _load_universe() -> list[str] | None:
    """Read the deliberate universe, ignoring comments and blank lines."""
    try:
        return [
            line.strip()
            for line in UNIVERSE_PATH.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
    except OSError as exc:
        print(f"universe_propose: warning — cannot read universe: {exc}", file=sys.stderr)
        return None


def _load_proposed() -> dict[str, dict[str, str]] | None:
    try:
        data = json.loads(PROPOSED_PATH.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        print(f"universe_propose: warning — cannot read proposed log: {exc}", file=sys.stderr)
        return None
    if not isinstance(data, dict):
        print("universe_propose: warning — proposed log is not a JSON object", file=sys.stderr)
        return None
    return data


def _parse_detected_at(value: object) -> datetime | None:
    """Parse the normal SQLite timestamp forms without trusting malformed rows."""
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
                try:
                    result = datetime.strptime(value, fmt)
                    break
                except ValueError:
                    continue
            else:
                return None
    else:
        return None
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)


def _is_in_universe(company_name: str, universe: list[str]) -> bool:
    name = company_name.casefold()
    symbols = {symbol.casefold() for symbol in universe}
    for alias, symbol in ALIASES.items():
        if alias.casefold() in name and symbol.casefold() in symbols:
            return True
    return any(re.search(rf"(?<!\w){re.escape(symbol.casefold())}(?!\w)", name) for symbol in symbols)


def _recent_earnings(now: datetime) -> list[dict[str, str]] | None:
    """Return valid earnings filings from the last 48 hours, or None on DB failure."""
    db_path = _db_path()
    if not db_path.exists():
        print(f"universe_propose: warning — filings DB missing: {db_path}", file=sys.stderr)
        return None

    try:
        with sqlite3.connect(db_path) as connection:
            rows = connection.execute(
                "SELECT bse_code, company_name, detected_at FROM realtime_filings "
                "WHERE filing_type = ?",
                ("earnings",),
            ).fetchall()
    except sqlite3.Error as exc:
        print(f"universe_propose: warning — cannot query filings DB: {exc}", file=sys.stderr)
        return None

    cutoff = now - timedelta(days=2)
    filings: list[dict[str, str]] = []
    for bse_code, company_name, detected_at in rows:
        parsed = _parse_detected_at(detected_at)
        if parsed is None or parsed < cutoff or parsed > now:
            continue
        if bse_code is None or not company_name:
            continue
        filings.append({
            "bse_code": str(bse_code),
            "company_name": str(company_name),
            "detected_at": str(detected_at),
        })
    return sorted(filings, key=lambda filing: filing["detected_at"], reverse=True)


def _write_escalation(proposals: list[dict[str, str]], more_count: int, now: datetime) -> Path:
    ESC_DIR.mkdir(parents=True, exist_ok=True)
    path = ESC_DIR / f"universe-proposal-{now.date().isoformat()}.md"
    lines = [
        "# Earnings universe proposals — human review needed",
        "",
        "Recent earnings filings below are outside the curated universe. Review each; do not auto-add.",
        "",
    ]
    for filing in proposals:
        lines.extend([
            f"## {filing['company_name']} ({filing['bse_code']})",
            "",
            f"Detected: {filing['detected_at']}",
            "",
            "Action: add the symbol to `monitor/earnings_universe.txt`.",
            "",
        ])
    if more_count:
        lines.extend([f"+{more_count} more recent out-of-universe earnings filings.", ""])
    path.write_text("\n".join(lines))
    return path


def _save_proposed(proposed: dict[str, dict[str, str]]) -> None:
    PROPOSED_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROPOSED_PATH.write_text(json.dumps(proposed, indent=2, sort_keys=True) + "\n")


def run(now: datetime | None = None) -> None:
    """Find and record at most five newly proposed companies."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    filings = _recent_earnings(now)
    if filings is None:
        return

    universe = _load_universe()
    proposed = _load_proposed()
    if universe is None or proposed is None:
        return
    candidates = [
        filing for filing in filings
        if filing["bse_code"] not in proposed
        and not _is_in_universe(filing["company_name"], universe)
    ]
    if not candidates:
        print("universe_propose: no new out-of-universe earnings filings")
        return

    selected = candidates[:5]
    escalation = _write_escalation(selected, len(candidates) - len(selected), now)
    for filing in selected:
        proposed[filing["bse_code"]] = {
            "company_name": filing["company_name"],
            "first_proposed": now.isoformat(),
        }
    _save_proposed(proposed)
    print(f"universe_propose: escalation written → {escalation.name}")


def main() -> None:
    run()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"universe_propose: warning (non-fatal) — {exc}", file=sys.stderr)
    sys.exit(0)
