#!/usr/bin/env python3
"""Weekly backtest-education draft — turns aksh's index/futures-level strategy validation
results into a SEBI-safe "how we test, including our failures" post. Historical/statistical
framing only: no forward calls, no capital sizing, no single-stock content.

Source: aksh's permutation_results/VALIDATION_REPORT.md (Monte Carlo Permutation Test across
INDEX/FUTURES daemons only). Deliberately narrow to a hardcoded allowlist of daemon names known
to be index-level (see DAEMON_ALLOWLIST) — most of aksh's other backtest JSONs are multi-hundred
single-stock universes and must NEVER be fed into this lane without a fresh underlying check.

Uses generate_draft.generate() like every other finance draft, so the hard SEBI lint inside it
still gates the output; this script's own job is just to keep the SOURCE material index-level
and strip any ₹ P&L / capital figures before they ever reach the prompt.

  /opt/homebrew/bin/python3 monitor/backtest_education_post.py [--report PATH] [--dry-run]

Weekly cadence (see monitor/launchd/com.srijan.backtest-education.plist, authored not
installed pending Srijan's first-draft review). Drafts-only; Srijan posts.
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ENGINE_DIR))
AKSH = Path("/Users/srijan/aksh_backtesting_trading")
DEFAULT_REPORT = AKSH / "permutation_results" / "VALIDATION_REPORT.md"

# Only these daemon names are known index/futures-level (verified against the source report,
# 2026-07-04). A daemon renamed or a NEW report naming anything outside this set is refused
# rather than silently trusted — a stock-level daemon slipping in here would be a SEBI problem
# this script cannot detect from prose alone.
DAEMON_ALLOWLIST = {"VRP Kite (original)", "VRP Kite (simplified)", "ORB",
                    "FNO Momentum", "Expiry Scalp", "FNO Momentum (D2)",
                    "Expiry Scalp (NIFTY)"}

# Bare rupee/lot-size figures (e.g. a total_pnl_rs-style number) must never reach the LLM
# prompt — generic risk-management vocabulary like "position sizing" is fine, a live ₹ amount
# or lot count is not.
BANNED_IN_SOURCE = ("₹", "lot size", "lots of")


def extract_daemons(report_text: str) -> list[dict]:
    """Parse the executive-summary table into per-daemon dicts. Refuses (raises) if a table
    row names a daemon outside DAEMON_ALLOWLIST, or if banned capital/₹ language survives."""
    for term in BANNED_IN_SOURCE:
        if term.lower() in report_text.lower():
            raise SystemExit(f"backtest_education_post: banned term {term!r} found in "
                             f"source report; strip it before this lane can use the file")

    daemons = []
    for line in report_text.splitlines():
        line = line.strip()
        if not (line.startswith("|") and line.endswith("|")):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 5 or cells[0] in ("Daemon",) or set(cells[0]) <= {"-"}:
            continue
        name, _s1, _s2, pval, overall = cells
        if name not in DAEMON_ALLOWLIST:
            raise SystemExit(f"backtest_education_post: daemon {name!r} not on the "
                             f"index/futures allowlist; verify its underlying before adding it")
        daemons.append({"name": name, "p_value": pval, "overall": overall})
    if not daemons:
        raise SystemExit("backtest_education_post: no daemon rows parsed from report")
    return daemons


def build_context(report_path: Path) -> str:
    text = report_path.read_text(encoding="utf-8")
    daemons = extract_daemons(text)
    m = re.search(r"\*\*Key Finding\*\*:\s*(.+)", text)
    key_finding = m.group(1).strip() if m else ""
    lines = [
        "Source: index/futures strategy validation via Monte Carlo Permutation Testing "
        "(Timothy Masters' bar-permutation method, NIFTY 2018-2024, 2000 permutations/strategy).",
        f"Key finding: {key_finding}" if key_finding else "",
        "Per-strategy results (index/futures level only, no single-stock content):",
    ]
    for d in daemons:
        lines.append(f"- {d['name']}: p-value {d['p_value']} ({d['overall']} at the "
                     f"1% significance threshold)")
    lines.append(
        "Angle: honesty as the hook. Most retail backtests never get permutation-tested; "
        "this one did, and most of our own strategies failed the strict bar. Explain what a "
        "p-value from permutation testing means in plain language, why 'looked good "
        "historically' isn't enough, and that even our best result (p=0.038) only clears "
        "the loose 5% bar, not the strict 1% one we hold ourselves to."
    )
    return "\n".join(l for l in lines if l)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.report.exists():
        raise SystemExit(f"backtest_education_post: report not found: {args.report}")
    context = build_context(args.report)

    if args.dry_run:
        print("DRY backtest_education_post: context that would be sent to generate():\n")
        print(context)
        return 0

    from generate_draft import generate
    from market_common import append_disclaimer
    out = generate("finance", "how we validate our own trading strategies", context,
                   slug="backtest-education")
    append_disclaimer(out)
    print(f"Backtest-education draft: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
