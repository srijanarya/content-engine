#!/usr/bin/env python3
"""Weekly product-seed draft — feature-marketing content for the AKSH paid product (valuation
workbench, backtester, screener, XBRL feed), generated through the FULL finance gate stack so
nothing per-stock or directional can ship. Mirrors monitor/audit_angle_post.py structurally,
but engine=finance: the hard SEBI lint runs at generation, and post time re-runs lint + the
LLM reviewer + the trading-calendar and value gates.

The slate is the SEBI-vetted seed list (growth/valuation-content-seeds.md): methodology and
aggregate framing only, zero named securities, zero fair-value claims. Rotation: ISO week
number mod slate size, so each Wednesday advances one seed.

  /opt/homebrew/bin/python3 monitor/product_seed_post.py [--topic <slug>] [--dry-run]

Cadence: x/launchd/com.srijan.x-prodseed.plist (Wed 11:00). Filename slug prodseed-* is the
post_x lane selector; the finance daily trio never matches it and vice versa.
"""
from __future__ import annotations
import argparse
import sys
from datetime import date
from pathlib import Path

ENGINE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ENGINE_DIR))

SLATE = [
    {
        "slug": "prodseed-dcf-sensitivity",
        "topic": "how much one percent of discount rate moves a valuation model",
        "context": (
            "Methodology-only DCF education: I stress-tested our valuation workbench's discount "
            "rate sensitivity on a hypothetical input set (say TTM EPS of 10, 12 percent growth "
            "for five years fading to 4 percent terminal). Moving the discount rate one percent "
            "moves the output more than most people's entire thesis. Show the arithmetic idea, "
            "explain why any single 'intrinsic value' number is really a range, and why the tool "
            "makes YOU supply every assumption instead of handing you a target. No named "
            "securities, no fair value of any stock, no recommendations. Soft close: the "
            "workbench ships in AKSH Pro."
        ),
    },
    {
        "slug": "prodseed-factor-deciles",
        "topic": "what a quality factor backtest across the FNO universe actually shows",
        "context": (
            "Aggregate factor-performance education: rank the FNO universe by a quality factor, "
            "compare top decile vs bottom decile spread historically, explain the exact "
            "methodology (ranking, rebalancing, horizon) and the honesty caveats (decile spreads "
            "shrink out of sample, transaction costs eat edges). No individual stock names, no "
            "per-stock factor scores, aggregate statistics only. Soft close: the factor data and "
            "timeseries live in the AKSH API."
        ),
    },
    {
        "slug": "prodseed-screen-passrates",
        "topic": "we run a screen on the whole market and only publish the pass rate",
        "context": (
            "Screener methodology education: we run rule-based screens (growth, margin "
            "expansion, earnings quality) across roughly 3,600 BSE companies and publicly share "
            "only the AGGREGATE pass rate (for example X percent passed this quarter vs Y "
            "percent last quarter) and the methodology. Explain WHY the named list itself is "
            "never published publicly: an unregistered entity publishing a ranked stock list is "
            "the SEBI line, and honest data infrastructure stays on the right side of it. The "
            "list exists inside the gated product for registered users. No stock names anywhere."
        ),
    },
    {
        "slug": "prodseed-hedge-words",
        "topic": "counting hedge words across a quarter of earnings calls",
        "context": (
            "Language-analysis education: count hedge words (headwinds, cautiously, challenging, "
            "uncertain) across this quarter's earnings call transcripts and compare sector-wide "
            "aggregates to last quarter. Explain the method (transcript parsing, word lists, "
            "normalization by call length) and what aggregate hedging shifts historically "
            "coincide with. Sector and aggregate level only, never a single company's language "
            "as a trading view. Soft close: this language layer powers our earnings reports."
        ),
    },
    {
        "slug": "prodseed-xbrl-latency",
        "topic": "the alpha is reading public filings faster not secret data",
        "context": (
            "Capability and latency story: XBRL filings are machine-readable structured data "
            "sitting free on the exchange, and almost nobody parses them. We pull revenue, PAT "
            "and EPS deltas minutes after a filing hits (median about 6 minutes) across roughly "
            "3,600 BSE companies. Factual deltas only, no scores, no verdicts, no "
            "recommendations. Deep-link to bseindia.com, never mirror PDFs. Soft close: this "
            "feed powers the screener and reports."
        ),
    },
]
BY_SLUG = {s["slug"]: s for s in SLATE}


def pick(today: date, override: str | None) -> dict:
    """ISO-week rotation: each Wednesday advances one seed; --topic overrides."""
    if override:
        if override in BY_SLUG:
            return BY_SLUG[override]
        raise SystemExit(f"product_seed_post: unknown --topic {override!r}; "
                         f"choices: {', '.join(BY_SLUG)}")
    return SLATE[today.isocalendar()[1] % len(SLATE)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--topic", help="slate slug to force (else rotates by ISO week)")
    ap.add_argument("--dry-run", action="store_true", help="print the chosen topic/context, generate nothing")
    args = ap.parse_args()

    entry = pick(date.today(), args.topic)

    if args.dry_run:
        print(f"DRY product_seed_post: would generate slug={entry['slug']!r}\n")
        print(f"Topic: {entry['topic']}\n\nContext:\n{entry['context']}")
        return 0

    from generate_draft import generate
    out = generate("finance", entry["topic"], entry["context"], slug=entry["slug"])
    print(f"Product-seed draft: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
