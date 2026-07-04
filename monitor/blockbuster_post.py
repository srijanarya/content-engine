#!/usr/bin/env python3
"""Earnings-season blockbuster summary — factual-only digest of verified strong-quarter
results. Manual trigger (earnings season is short and irregular; not worth a cron). Run when
a batch of results lands, e.g. Q1 FY27 ~mid-July.

Strips everything advisory before it ever reaches the LLM prompt:
  - blockbuster_score (0-100 rating) — dropped entirely.
  - the "consider technical confirmation before investing" line — this script never sees it,
    since it reads the DB directly rather than calling generate_report()/main().
  - ordering is by RECENCY (verified_at), never by score/growth — a "top movers by growth"
    sort is itself a de facto ranked recommendation list.

  /opt/homebrew/bin/python3 monitor/blockbuster_post.py [--limit N] [--dry-run]

Drafts-only; Srijan posts. FINANCE-CONTENT-WIKI.md §5 lane 4.
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ENGINE_DIR))
AKSH = Path("/Users/srijan/aksh_backtesting_trading")

FACTUAL_FIELDS = ("company_name", "quarter", "fy_year", "revenue_cr", "pat_cr", "eps",
                 "revenue_yoy_growth", "pat_yoy_growth", "eps_growth", "verified_at")


def factual_stocks(limit: int = 8) -> list[dict]:
    """Recency-ordered, factual-only rows: no blockbuster_score, no advisory notes."""
    sys.path.insert(0, str(AKSH))
    from scripts.generate_blockbuster_report import get_blockbuster_stocks
    rows = get_blockbuster_stocks(min_score=0)
    rows = sorted(rows, key=lambda r: r.get("verified_at") or "", reverse=True)[:limit]
    return [{k: r.get(k) for k in FACTUAL_FIELDS} for r in rows]


def build_context(stocks: list[dict]) -> str:
    if not stocks:
        raise SystemExit("blockbuster_post: no verified blockbuster rows to summarize")
    lines = [
        "Source: publicly filed quarterly results (BSE), verified against Screener.in. "
        "Factual financials only — no rating, no score, no buy/sell view.",
        f"{len(stocks)} companies with recently verified results (most recent first):",
    ]
    for s in stocks:
        lines.append(
            f"- {s['company_name']} ({s['quarter']} FY{s['fy_year']}): revenue "
            f"Rs{s['revenue_cr']}cr (YoY {s['revenue_yoy_growth']}%), PAT Rs{s['pat_cr']}cr "
            f"(YoY {s['pat_yoy_growth']}%), EPS {s['eps']} (YoY {s['eps_growth']}%)."
        )
    lines.append(
        "Angle: report the numbers as filed, in the order verified (never ranked by growth "
        "or scored) — this is a factual roundup, not a stock-picking list. No buy/sell/hold "
        "language, no forward view, no target."
    )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    context = build_context(factual_stocks(args.limit))
    if args.dry_run:
        print("DRY blockbuster_post: context that would be sent to generate():\n")
        print(context)
        return 0

    from generate_draft import generate
    from market_common import append_disclaimer
    from datetime import date
    out = generate("finance", "verified quarterly results roundup", context,
                   slug=f"blockbuster-{date.today().isoformat()}")
    append_disclaimer(out)
    print(f"Blockbuster draft: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
