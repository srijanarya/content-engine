#!/usr/bin/env python3
"""Guards the audit lane (non-finance auto-posting) so it can't drift into the finance path:
  - APPROVAL: an audit draft posts ONLY when status: approved. auto mode never lifts it (auto only
    lifts FINANCE needs-review), so a hype-blocked draft can never sneak out.
  - LANE ISOLATION: --lane-slug audit selects only audit-* drafts, never a bare ai-world draft.
  - CAP UNTOUCHED: the shared MAX_THREADS_PER_DAY stays at Srijan's authorized 4.
  - HYPE GATE: compliance.hype_check blocks hype/bait/guarantee, passes clean receipts.

Run:  python3 test_audit_lane.py   (prints PASS/FAIL, exits nonzero on failure; pytest-discoverable)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import post_x as px
from compliance import hype_check as hc

TODAY = "2026-07-06"


def fm(status="approved", engine="ai-world", generated=TODAY, topic="the gate that re-checks the work"):
    return {"status": status, "engine": engine, "generated": generated, "topic": topic}


# ── approval / eligibility ──
def test_approved_audit_draft_is_eligible():
    # an approved audit draft posts on the audit lane WITHOUT auto mode (approved is its own ceiling)
    assert px.eligible("2026-07-06-ai-worl-audit-the-gate.md", fm(status="approved"),
                       lane_slug="audit", today=TODAY, auto_approve=False)


def test_audit_needs_review_never_autoposts():
    # a needs-review audit draft must NOT be eligible even in auto mode — auto only lifts FINANCE
    assert not px.eligible("2026-07-06-ai-worl-audit-the-gate.md", fm(status="needs-review"),
                           lane_slug="audit", today=TODAY, auto_approve=True)


def test_hype_blocked_audit_draft_never_posts():
    # the hype gate marks a bad draft BLOCKED-hype; that status is never eligible
    assert not px.eligible("2026-07-06-ai-worl-audit-the-gate.md", fm(status="BLOCKED-hype"),
                           lane_slug="audit", today=TODAY, auto_approve=True)


# ── lane isolation ──
def test_audit_lane_ignores_bare_ai_world_draft():
    # asking for the audit lane must not select a non-audit ai-world draft (no "audit" in the name)
    assert not px.eligible("2026-07-06-ai-worl-opus-benchmarks.md", fm(status="approved"),
                           lane_slug="audit", today=TODAY, auto_approve=False)


def test_audit_draft_needs_today_generation():
    # a prior-day approved audit draft must not flush (the backlog guard applies to every lane)
    assert not px.eligible("2026-07-05-ai-worl-audit-the-gate.md",
                           fm(status="approved", generated="2026-07-05"),
                           lane_slug="audit", today=TODAY, auto_approve=False)


# ── window + shared cap ──
def test_audit_window_registered():
    assert "audit" in px.LANE_WINDOWS
    lo, hi = px.LANE_WINDOWS["audit"]
    assert lo < hi and 0 <= lo and hi <= 24


def test_shared_cap_unchanged():
    # the audit lane must NOT have changed the shared cap (its value is Srijan's authorization)
    assert px.MAX_THREADS_PER_DAY == 4


# ── disclaimer: finance-only boilerplate must not ride a non-finance thread ──
_THREAD_HEADER = "## X / TWITTER THREAD\n\n"


def test_non_finance_thread_gets_no_sebi_disclaimer():
    text = _THREAD_HEADER + "**1/** First tweet body.\n\n**2/** Second tweet body.\n"
    tweets = px.parse_thread(text, finance=False)
    assert tweets == ["First tweet body.", "Second tweet body."], tweets


def test_finance_default_still_appends_disclaimer():
    # the default (finance=True) keeps the existing behavior every finance caller relies on
    text = _THREAD_HEADER + "**1/** First tweet body.\n"
    tweets = px.parse_thread(text)
    assert px.SHORT_DISCLAIMER in tweets[-1]


# ── the no-hype gate ──
def test_hype_gate_blocks_hype_word():
    assert not hc.check("This audit tool is a game-changer.")[0]


def test_hype_gate_blocks_guarantee():
    assert not hc.check("Guaranteed to clean up your codebase.")[0]


def test_hype_gate_blocks_engagement_bait():
    assert not hc.check("Comment YES if you want the audit checklist.")[0]


def test_hype_gate_blocks_unqualified_multiplier():
    assert not hc.check("My agents ship 100x faster now.")[0]


def test_hype_gate_passes_clean_receipts():
    ok, reason = hc.check("I ran the audit on my own repo. Found 3 leaked keys and 2 authz gaps. "
                          "Here is the checklist I used.")
    assert ok, reason


def test_hype_gate_passes_sourced_multiplier():
    ok, reason = hc.check("It ran 10x faster on the SWE-bench benchmark vs the baseline.")
    assert ok, reason


def test_hype_gate_fail_closed_on_empty():
    assert not hc.check("")[0]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t(); print(f"PASS {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1; print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
