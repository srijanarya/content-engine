#!/usr/bin/env python3
"""
LLM compliance reviewer — the SECOND gate, for autonomous posting.

The regex linter (lint.py) catches EXPLICIT per-stock calls. This catches the SUBTLE ones it can't:
implied directional views, "poised to recover", "use as a factor signal", hedged recommendations,
anything that reads as a basis for an investment decision on a specific security. When the human
review is removed (auto-post), this replaces the human ceiling.

Uses the `claude` CLI (Max plan, headless) — same path as generate_draft. Fail-closed: if the
reviewer can't run or returns anything unexpected, treat as BLOCK (never post on uncertainty).
"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path

REVIEW_PROMPT = """You are a strict SEBI compliance reviewer for Indian stock-market content published by an
UNREGISTERED individual (not a SEBI Research Analyst or Investment Adviser). Decide if it is safe to publish.

KEY DISTINCTION: indices and SECTORS are NOT specific securities. Commentary and data on Nifty, Bank Nifty,
Sensex, VIX, and sectors (IT, METAL, REALTY, PHARMA, etc.) is SAFE — including describing them as weak,
strong, falling, rising, leading, or lagging. Only a view on a NAMED COMPANY's stock (Infosys, TCS,
Reliance, HDFC Bank, etc.) can be a violation.

SAFE — pass these:
- "Nifty closed -1.6%, below its 75-EMA. VIX rose to 19.3." (index data)
- "FII sold 1,987 Cr; DII bought 4,224 Cr." (flows)
- "IT was the weakest sector, -3.7%; METAL held up best." (sector-level description — SAFE)
- "All 10 sectors closed red; a risk-off day." (market-condition commentary)
- "Infosys management hedged six times in the Q&A vs the prepared remarks." (language analysis of a public
  call, no directional view on the stock)

BLOCK — fail these:
- "Buy Reliance" / "I'd accumulate Infosys" / "short TCS" (explicit per-stock call)
- "HDFC Bank looks poised to recover" / "TCS should outperform" / "Infosys looks weak here" (implied
  per-stock directional view, even hedged)
- "Use INFY as a factor signal" / "expect negative drift in TCS" / price or stop-loss targets on a stock
- COMPARING TWO NAMED COMPANIES and framing one as superior / better-positioned / cheaper / mispriced /
  a better hold — e.g. "Company A's margins are simply better than Company B's", "the market is pricing
  A backwards vs B", "A screens better than B" — EVEN IF styled as pure data or 'just an observation'.
  (This is an implied relative recommendation on both stocks.) NOTE: comparing SECTORS/INDICES or broad
  CATEGORIES — "IT outperformed Pharma", "PSU banks lagged private banks", "Nifty Bank beat Nifty 50" —
  is SAFE. Only NAMED-COMPANY-vs-NAMED-COMPANY superiority framing is the violation.
- ANY actionable or predictive view on a NAMED COMPANY's stock, even softened or framed as 'education'.

Catching SUBTLE/IMPLIED per-stock views is the whole point. When genuinely unsure, BLOCK.

First reason in 1-2 sentences. Then output your decision on the FINAL line in EXACTLY this format:
VERDICT: SAFE
or
VERDICT: BLOCK — <short reason>

CONTENT TO REVIEW:
---
{content}
---"""


def review(content: str, timeout: int = 120) -> tuple[bool, str]:
    """Return (is_safe, reason). Fail-closed: any error or unrecognized reply => (False, ...)."""
    prompt = REVIEW_PROMPT.format(content=content[:8000])
    try:
        import sys as _sys
        from pathlib import Path as _P
        _sys.path.insert(0, str(_P(__file__).parent.parent))
        from claude_env import claude_env  # factory-plan routing (srijanaryaji@), 2026-07-12
        out = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True,
                             timeout=timeout, env=claude_env())
    except Exception as e:
        return (False, f"reviewer error (fail-closed): {e}")
    resp = (out.stdout or "").strip()
    if out.returncode != 0 or not resp:
        return (False, f"reviewer no-output (fail-closed): rc={out.returncode} {out.stderr[:120]}")
    # Read the VERDICT line (the model reasons first, then states the verdict last).
    verdict = next((ln for ln in reversed(resp.splitlines()) if "VERDICT:" in ln.upper()), "")
    up = verdict.upper()
    if "VERDICT: SAFE" in up or up.strip().endswith("SAFE"):
        return (True, "ok")
    if "VERDICT: BLOCK" in up or "BLOCK" in up:
        return (False, verdict.strip() or "blocked")
    # No clear verdict line → fail closed.
    return (False, f"reviewer unclear reply (fail-closed): {resp.splitlines()[-1][:120]}")


def demo():
    # These call the live CLI; run manually. Kept light so it doesn't burn tokens on import.
    safe_ok, _ = review("Nifty closed -1.6% below its 75-EMA. FII sold 1,987 Cr; IT sector was weakest at -3.7%.")
    bad_ok, bad_reason = review("Infosys looks poised to recover from here — I'd start accumulating.")
    print("safe sample →", "SAFE" if safe_ok else "BLOCK")
    print("subtle bad sample →", "SAFE" if bad_ok else f"BLOCK ({bad_reason})")
    assert safe_ok, "clean regime text should pass the LLM reviewer"
    assert not bad_ok, "subtle implied per-stock view should be blocked"
    print("review demo: passed")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        demo()
    elif len(sys.argv) > 1:
        ok, reason = review(Path(sys.argv[1]).read_text())
        print(("SAFE" if ok else "BLOCK") + (f": {reason}" if not ok else ""))
        sys.exit(0 if ok else 1)
    else:
        demo()
