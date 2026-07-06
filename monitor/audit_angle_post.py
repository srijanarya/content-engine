#!/usr/bin/env python3
"""Audit-lane draft — generates an audit-angle ai-world thread about Srijan's AI-native engineering
(the guardrails he builds around coding agents), the top-of-funnel for the Claude Code / automation
audit offer. NOT finance: no market content, so the SEBI gates don't apply; the no-hype gate
(compliance/hype_check) is the ceiling instead.

Flow (mirrors monitor/backtest_education_post.py): pick a topic from a small grounded slate, generate
via generate_draft.generate("ai-world", ...) so it inherits voice.md, then run hype_check on the
result and set the frontmatter status:
  - clean  -> status: approved   (post_x's audit lane will post it inside its window)
  - hype   -> status: BLOCKED-hype + a loud in-file banner (never auto-posts; eligible() needs approved)

Filenames come out as {today}-ai-worl-audit-<slug>.md; the "audit" substring is what post_x.py
--lane-slug audit selects on, so this lane never flushes a bare ai-world draft and vice-versa.

  /opt/homebrew/bin/python3 monitor/audit_angle_post.py [--topic <slug>] [--dry-run]

Cadence: x/launchd/com.srijan.x-audit.plist (AUTHORED, not installed — pending Srijan's first-draft
review). Drafts + gates locally; the post step is a separate lane run.
"""
from __future__ import annotations
import argparse
import re
import sys
from datetime import date
from pathlib import Path

ENGINE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ENGINE_DIR))

# Grounded audit-angle slate. Contexts are honest and receipt-shaped (no inflated counts, no "5
# identical loops" claim, no career-ops-CV-pipeline attribution — see the plan's accuracy
# guardrails). Each ends by asking for a soft CTA to the audit offer, not a hard sell. Keep slugs
# "audit-*" so the lane selector matches.
SLATE = [
    {
        "slug": "audit-the-gate",
        "topic": "the gate that re-checks the agent's work instead of trusting its verdict",
        "context": (
            "Angle: I don't let my coding agents grade their own work. A validator agent can report "
            "'pass' while its own evidence log shows a failure; my gate re-derives pass/fail from the "
            "raw evidence on disk, so a leaking log turns a claimed 'pass' into a hard fail. I also "
            "measure the validator itself against seeded fake results before I trust it to grade "
            "anything. Explain in plain language why 'the agent said it passed' is not the same as "
            "'it passed', and why re-checking the bytes is the cheap insurance most AI-generated "
            "codebases skip. Honest and concrete, no inflated numbers. End with a soft line that this "
            "is exactly the kind of guardrail I add when I audit an AI-generated codebase for a team."
        ),
    },
    {
        "slug": "audit-guardrails",
        "topic": "guardrails a coding agent literally cannot talk its way around",
        "context": (
            "Angle: policy the model can't override. Two of my shell/tool guardrails fail in OPPOSITE "
            "directions on purpose: the destructive-shell blocker fails OPEN (a bug in it can't brick "
            "my shell) while the money/trade blocker fails CLOSED (a bug in it can't let a real-money "
            "action through). A third hard-denies any agent dispatch that skips a required setting, "
            "quoting the rule back at the model. The point: you don't ask an agent nicely not to do "
            "the dangerous thing, you make it structurally unable to. Explain fail-open vs fail-closed "
            "in plain terms with the two real examples. No hype. End with a soft note that setting "
            "these fences up right is a big part of an AI-automation audit."
        ),
    },
    {
        "slug": "audit-capability",
        "topic": "the safest way to stop an agent doing something is to not give it the ability",
        "context": (
            "Angle: capability-absent beats policy-denied. My worker agents are declared with a tool "
            "allowlist that contains no shell and no network, so they physically cannot send, post, or "
            "run a command, no matter what a prompt injection tells them. The deny-list in settings is "
            "only a second layer. Explain why 'told not to' is weaker than 'unable to' for anything "
            "irreversible, using the allowlist idea. Plain language, honest, no inflated claims. End "
            "with a soft line that scoping an agent's real capabilities is one of the first things I "
            "check in an audit."
        ),
    },
]
BY_SLUG = {s["slug"]: s for s in SLATE}


def pick(today: date, override: str | None) -> dict:
    """Choose a slate entry: explicit --topic slug wins; else rotate by date so the lane doesn't
    repeat the same angle each run."""
    if override:
        if override in BY_SLUG:
            return BY_SLUG[override]
        raise SystemExit(f"audit_angle_post: unknown --topic {override!r}; "
                         f"choices: {', '.join(BY_SLUG)}")
    return SLATE[today.toordinal() % len(SLATE)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--topic", help="slate slug to force (else rotates by date)")
    ap.add_argument("--dry-run", action="store_true", help="print the chosen topic/context, generate nothing")
    args = ap.parse_args()

    entry = pick(date.today(), args.topic)

    if args.dry_run:
        print(f"DRY audit_angle_post: would generate slug={entry['slug']!r}\n")
        print(f"Topic: {entry['topic']}\n\nContext:\n{entry['context']}")
        return 0

    from generate_draft import generate
    out = Path(generate("ai-world", entry["topic"], entry["context"], slug=entry["slug"]))

    # Post-gate: hype_check the whole draft. Approve if clean, else mark BLOCKED-hype so it can never
    # auto-post (eligible() requires status: approved). Same "re-check at the boundary" posture as
    # post_x's re-lint at post time; post_x also re-runs this gate before it posts.
    from compliance.hype_check import check as hype_check
    text = out.read_text()
    ok, reason = hype_check(text)
    status = "approved" if ok else "BLOCKED-hype"
    text = re.sub(r"^status: .*$", f"status: {status}", text, count=1, flags=re.M)
    if not ok:
        banner = (f"> HYPE GATE BLOCKED — {reason}; do NOT publish as-is. Edit the hype out, "
                  f"then set status: approved.\n\n")
        text = re.sub(r"(---\n\n)", r"\1" + banner.replace("\\", r"\\"), text, count=1)
    out.write_text(text)

    print(f"Audit-angle draft: {out}  [status: {status}]"
          + ("" if ok else f"  — {reason}"), file=sys.stderr)
    print(str(out))
    return 0 if ok else 0  # non-zero only on generation failure, not a hype block (block is a valid outcome)


if __name__ == "__main__":
    sys.exit(main())
