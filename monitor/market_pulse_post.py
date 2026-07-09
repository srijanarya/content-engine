#!/usr/bin/env python3
"""Daily Market Pulse card — deterministic sector-breadth / RRG / macro read built from
AKSH's snapshot DB (data/market_pulse_history.db, written daily by
`python -m scripts.market_pulse_daily_snapshot` in the aksh repo).

Pipeline mirrors the other finance products but is DETERMINISTIC (no LLM — same rationale
as the factory's market_video.py: a rewrite would re-open the SEBI surface):
  read snapshot (today only, fail-closed on stale) → redact to the FREE product tier via
  aksh's api.services.market_pulse_gating (the ONE audit point the paid product uses; free
  tier given away free = the "show the shape, sell the depth" funnel, ADR-market-pulse-004)
  → deterministic descriptive text → HARD lint gate (refuse to write on any BLOCK — in a
  deterministic lane a block means a bug, not a bad generation) → draft .md for review.

Drafts-only; nothing here posts. Map: "content creation"/FINANCE-CONTENT-WIKI.md §5 lane 1.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

ENGINE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ENGINE_DIR))
AKSH = Path(os.environ.get("AKSH_DIR", "/Users/srijan/aksh_backtesting_trading"))

DISCLAIMER = ("Education and market data only. Not investment advice; no buy/sell/hold "
              "recommendation. Not a SEBI-registered research analyst or adviser.")

# The free-tier macro allowlist is display-name based ("USD/INR", "Brent Crude", "S&P 500" —
# MARKET_PULSE_TIER_MATRIX["big_picture.series"]); the snapshot store only keeps yahoo
# tickers, so we resolve the SAME three series by ticker rather than calling
# filter_big_picture (which would match nothing against re-hydrated rows).
MACRO_FREE_TIER = (("INR=X", "USD/INR"), ("BZ=F", "Brent crude"), ("^GSPC", "S&P 500"))

QUADRANT_ORDER = ("Leading", "Improving", "Weakening", "Lagging")

# The RRG/breadth universe mixes broad indices in with the sectoral ones; a "sector
# rotation" read listing "500" is noise. ponytail: static denylist, extend if the
# universe in aksh's symbol_map grows more non-sector entries.
NOT_A_SECTOR = {"NIFTY 500", "NIFTY MIDCAP 100", "NIFTY INDIA CONSUMPTION"}


def load_snapshot(day: str) -> dict:
    """Read aksh's pulse snapshot for `day`, redacted to the free tier. Fail-closed:
    a stale or empty snapshot raises SystemExit — yesterday's breadth must never post
    stamped as today's (the same failure mode the wrap lane hit on 2026-06-23)."""
    sys.path.insert(0, str(AKSH))
    from src.intelligence.market_pulse.snapshot_writer import read_snapshot, latest_snapshot_date
    from api.services.market_pulse_gating import filter_breadth, filter_rrg

    latest = latest_snapshot_date()
    if latest != day:
        raise SystemExit(f"market_pulse_post: snapshot is stale (latest {latest!r} != {day}) — "
                         f"run `python -m scripts.market_pulse_daily_snapshot` in {AKSH}")
    snap = read_snapshot(day)
    return {
        "as_of": day,
        "breadth": filter_breadth(snap["breadth"], "free"),
        "rrg": filter_rrg(snap["rrg"], "free"),
        "macro": snap["macro"],   # free-tier series picked by ticker in macro_lines()
    }


def _sector(name: str) -> str:
    return name.removeprefix("NIFTY ").title().replace("Fmcg", "FMCG").replace(
        "It", "IT").replace("Psu", "PSU").replace("Pse", "PSE")


def breadth_read(breadth: dict) -> tuple[str, list]:
    rows = [r for r in breadth.get("sectors", [])
            if r.get("pct_above_50dema") is not None
            and r.get("sector") not in NOT_A_SECTOR]
    if len(rows) < 5:
        raise SystemExit(f"market_pulse_post: only {len(rows)} breadth rows — refusing a thin read")
    rows.sort(key=lambda r: r["pct_above_50dema"], reverse=True)
    above = sum(1 for r in rows if r["pct_above_50dema"] > 50)
    hi, lo = rows[0], rows[-1]
    line = (f"{above} of {len(rows)} NIFTY sectors have a majority of members above their "
            f"50-day average. Widest breadth: {_sector(hi['sector'])} "
            f"({hi['pct_above_50dema']:.0f}%). Thinnest: {_sector(lo['sector'])} "
            f"({lo['pct_above_50dema']:.0f}%).")
    return line, rows


def rrg_quads(rrg: dict) -> dict[str, list]:
    quads: dict[str, list] = {q: [] for q in QUADRANT_ORDER}
    for s in rrg.get("sectors", []):
        q = s.get("q")
        if q in quads and s.get("sector") not in NOT_A_SECTOR:
            quads[q].append(_sector(s["sector"]))
    if not any(quads.values()):
        raise SystemExit("market_pulse_post: no RRG quadrant data, refusing")
    return {q: sorted(names) for q, names in quads.items()}


def rrg_read(quads: dict[str, list]) -> str:
    parts = [f"{q}: {', '.join(names)}" for q, names in quads.items() if names]
    return ("Weekly rotation map vs NIFTY 50. " + ". ".join(parts) +
            ". A quadrant describes where relative strength sits today, not where it goes next.")


def macro_lines(macro: dict) -> str:
    by_ticker = {r.get("yahoo"): r for r in macro.get("series", [])}
    bits = []
    for ticker, label in MACRO_FREE_TIER:
        row = by_ticker.get(ticker)
        if row and row.get("close") is not None:
            chg = row.get("pct_change")
            bits.append(f"{label} {row['close']:,.2f}"
                        + (f" ({chg:+.2f}%)" if chg is not None else ""))
    return " · ".join(bits)


def _nifty_headline(as_of: str) -> str:
    """Index-move opener for the newsletter, mirroring the spoken pulse script
    (content-creation market_video.py). Reads regime_safe.json (Kite-sourced); returns "" if the
    file is missing/unreadable or its date != the snapshot's as_of — never state a stale number."""
    try:
        r = json.loads((Path(__file__).parent / "regime_safe.json").read_text())
    except (OSError, json.JSONDecodeError):
        return ""
    if not r or (r.get("date") and as_of and r["date"] != as_of):
        return ""
    close, pct = r.get("nifty_close"), r.get("nifty_change_pct")
    if close is None or pct is None:
        return ""
    updown = "up" if pct >= 0 else "down"
    return f"NIFTY closed at {close:,.0f}, {updown} {abs(pct):.2f}%."


def build_texts(snap: dict) -> tuple[str, str]:
    """Returns (newsletter, x_thread); every number comes straight from the snapshot.
    House voice: no em-dashes anywhere. X tweets stay under 280 chars."""
    d = date.fromisoformat(snap["as_of"])
    nice = f"{d.day} {d.strftime('%B %Y')}"
    b_line, _ = breadth_read(snap["breadth"])
    quads = rrg_quads(snap["rrg"])
    r_line = rrg_read(quads)
    m_line = macro_lines(snap["macro"])

    newsletter = "\n\n".join(filter(None, [
        _nifty_headline(snap["as_of"]),
        f"Sector breadth check, {nice}.",
        b_line,
        r_line,
        f"Global backdrop: {m_line}." if m_line else "",
        "Breadth tells you how many stocks participate in a move; rotation tells you where "
        "relative strength currently sits. Both describe the tape as it is; neither "
        "predicts tomorrow.",
    ]))
    # Tweet 2 keeps only the two "strength" quadrants + counts for the rest, so it fits 280.
    lead = ", ".join(quads["Leading"]) or "none"
    improving = ", ".join(quads["Improving"]) or "none"
    rest = len(quads["Weakening"]) + len(quads["Lagging"])
    tweet2 = (f"**2/** Rotation map vs NIFTY 50 (weekly): Leading {lead}. Improving "
              f"{improving}. {rest} sectors sit in the weakening/lagging half. Where "
              f"strength SITS, not where it goes next.")
    thread = "\n\n".join(filter(None, [
        f"**1/** Sector breadth check, {nice}: {b_line}",
        tweet2,
        "**3/** " + (f"Global backdrop: {m_line}. " if m_line else "")
        + "Education, not advice. I post this read daily.",
    ]))
    for i, t in enumerate(thread.split("\n\n"), 1):
        if len(t) > 280:
            raise SystemExit(f"market_pulse_post: tweet {i} is {len(t)} chars (>280)")
    return newsletter, thread


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default=str(date.today()), help="YYYY-MM-DD (default today)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from trading_calendar import is_trading_day   # same NSE gate as the wrap lanes
    if not is_trading_day(date.fromisoformat(args.date)):
        print(f"market_pulse_post: {args.date} is not an NSE trading day; nothing to do")
        return 0

    out = ENGINE_DIR / "drafts" / f"{args.date}-finance-market-pulse.md"
    if out.exists():
        print(f"market_pulse_post: {out.name} already drafted")
        return 0

    snap = load_snapshot(args.date)
    newsletter, thread = build_texts(snap)

    # HARD lint gate — deterministic aggregate text must always pass; a BLOCK means the
    # snapshot leaked something per-stock, so refuse loudly instead of writing BLOCKED-sebi.
    from compliance.lint import report
    hits = [v for v in report(newsletter + "\n" + thread) if v["severity"] == "block"]
    if hits:
        raise SystemExit(f"market_pulse_post: SEBI lint BLOCK on deterministic text "
                         f"(bug or leaked field): {hits[:3]}")

    body = (f"---\nid: {args.date}-market-pulse\nengine: finance\n"
            f"topic: daily market pulse {args.date}\nstatus: needs-review\n"
            f"model: deterministic\ngenerated: {args.date}\n---\n\n"
            f"## NEWSLETTER\n\n{newsletter}\n\n## X / TWITTER THREAD\n\n{thread}\n\n"
            f"---\n> {DISCLAIMER}\n")
    if args.dry_run:
        print(f"DRY market_pulse_post: would write {out.name}\n\n{body}")
        return 0
    out.write_text(body)
    print(f"Market Pulse draft: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
