#!/usr/bin/env python3
"""
Red-team eval — runs labelled adversarial samples through the REAL double-gate (regex lint + LLM review)
and reports the confusion matrix. The number that matters is FALSE NEGATIVES: a sample labelled
should_block=true that the gate let through. For an autonomous poster on regulated content, FN must be 0.

Usage: python3 redteam_eval.py samples.json
  samples.json = {"samples": [{"text", "should_block", "technique", "lens", "why"}, ...]}
Exit code is non-zero if any false negative is found.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from compliance.lint import is_safe as regex_safe          # noqa: E402
from compliance.review import review as llm_review          # noqa: E402


def gate(text: str) -> tuple[bool, str]:
    """Return (blocked, reason). Blocked if EITHER gate fails."""
    if not regex_safe(text):
        return (True, "regex")
    ok, reason = llm_review(text)
    if not ok:
        return (True, f"llm: {reason}")
    return (False, "")


def main(path: str) -> int:
    samples = json.loads(Path(path).read_text())["samples"]
    fn, fp, tp, tn = [], [], 0, 0
    for s in samples:
        blocked, why = gate(s["text"])
        should = s["should_block"]
        if should and blocked:
            tp += 1
        elif should and not blocked:
            fn.append(s)                 # DANGEROUS: non-compliant passed the gate
        elif not should and not blocked:
            tn += 1
        else:
            fp.append({**s, "gate_reason": why})  # over-block (safe content blocked)

    n = len(samples)
    print(f"\n=== Gate eval on {n} adversarial samples ===")
    print(f"  true-positive  (bad caught):     {tp}")
    print(f"  true-negative  (safe passed):    {tn}")
    print(f"  FALSE-NEGATIVE (BAD SLIPPED):    {len(fn)}   <-- must be 0")
    print(f"  false-positive (safe over-block):{len(fp)}")
    recall = tp / (tp + len(fn)) if (tp + len(fn)) else 1.0
    print(f"  recall on should-block: {recall:.0%}")

    if fn:
        print("\n⛔ FALSE NEGATIVES (non-compliant content the gate let through):")
        for s in fn:
            print(f"  - [{s.get('lens')}/{s.get('technique')}] {s['text'][:90]}")
            print(f"      why bad: {s.get('why','')[:100]}")
    if fp:
        print("\n⚠️  FALSE POSITIVES (safe content the gate blocked — annoying, not dangerous):")
        for s in fp[:8]:
            print(f"  - [{s.get('lens')}] ({s['gate_reason']}) {s['text'][:80]}")

    return 1 if fn else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "redteam_samples.json"))
