#!/usr/bin/env python3
"""
No-hype gate — the quality ceiling for NON-finance auto-posting lanes (the audit lane).

Finance content has the SEBI gates (lint + review + value_check). Audit / ai-world content carries
no market-compliance surface, but it still must not auto-post marketing hype: the brand is
"honesty + receipts" (voice.md), and a game-changer / revolutionary / guaranteed line reads as
bot-written slop and kills the credibility the whole audit offer rests on.

check(text) -> (ok, reason). Same (bool, str) shape as compliance/review.py, so post_x.py can call
either one behind a single engine branch. Fail-closed by construction: a novel hype phrasing that
isn't on the list slips through (add it), but nothing here can ever mark real hype as clean.

ponytail: word-list + one narrow regex, no LLM. Ceiling = a hype phrasing not on the list gets
through; upgrade path is add the phrase (or bolt on a review.py-style LLM gate) if that bites.
"""
from __future__ import annotations
import re
import sys

# voice.md "Hard nos" (lines 28, 31) plus the usual marketing tells. Substring-matched on lowercased
# text, so multi-word phrases work as-is. Keep additions lowercase.
HYPE_WORDS = (
    "game-changer", "game changer", "gamechanger", "revolutionary", "insane",
    "mind-blowing", "mind blowing", "mindblowing", "you won't believe", "you wont believe",
    "unbelievable", "jaw-dropping", "jaw dropping", "groundbreaking", "next-level",
    "world-class", "the future of", "trust me", "no-brainer", "no brainer", "10x engineer",
)
GUARANTEE_WORDS = ("guaranteed", "guarantee", "risk-free", "risk free")
# Engagement-bait (voice.md line 31).
BAIT_PHRASES = (
    "comment yes", "comment below", "comment 'yes'", "like and retweet", "retweet if",
    "smash that", "drop a ", "tag someone", "tag a friend", "follow for more",
    "who's with me",
)
# Unqualified inflated-multiplier claim ("10x faster" / "100x better") with NO evidence marker in
# the text. The voice WANTS real receipts ("54% on a clean run vs 70%"), so this fires ONLY when the
# claim has no source/measurement word anywhere in the text — a bare superlative, not a number.
_MULT_CLAIM = re.compile(r"\b\d+\s*x\s+(faster|better|smarter|easier|cheaper|more)\b", re.I)
_EVIDENCE = ("benchmark", "measured", " vs ", "http", "logged", "counted", "on the ", "%",
             "p=", "sharpe")


def check(text: str) -> tuple[bool, str]:
    """Return (ok, reason). ok=True only if no hype word / bait / guarantee / unqualified
    multiplier fires. Fail-closed on empty input (an empty thread is not something to post)."""
    if not text or not text.strip():
        return (False, "empty text (fail-closed)")
    low = text.lower()
    for w in HYPE_WORDS:
        if w in low:
            return (False, f"hype word: {w!r}")
    for w in GUARANTEE_WORDS:
        if w in low:
            return (False, f"guarantee claim: {w!r}")
    for b in BAIT_PHRASES:
        if b in low:
            return (False, f"engagement-bait: {b!r}")
    m = _MULT_CLAIM.search(low)
    if m and not any(e in low for e in _EVIDENCE):
        return (False, f"unqualified multiplier claim: {m.group(0)!r} (no source in text)")
    return (True, "ok")


def demo():
    assert not check("This is a game-changer.")[0], "hype word must block"
    assert not check("Guaranteed to fix your codebase.")[0], "guarantee must block"
    assert not check("Comment YES if you want the checklist.")[0], "engagement-bait must block"
    assert not check("It runs 100x faster.")[0], "unqualified multiplier must block"
    assert check("It ran 10x faster on the SWE-bench benchmark vs the baseline.")[0], "sourced multiplier is fine"
    assert check("I audited my own repo. Found 3 leaked keys and 2 authz gaps. Here is the checklist.")[0], "clean receipts pass"
    assert not check("")[0], "empty is fail-closed"
    print("hype_check demo: all assertions passed")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        demo()
    elif len(sys.argv) > 1:
        import pathlib
        ok, reason = check(pathlib.Path(sys.argv[1]).read_text())
        print(("CLEAN" if ok else "BLOCK") + (f": {reason}" if not ok else ""))
        sys.exit(0 if ok else 1)
    else:
        demo()
