#!/usr/bin/env python3
"""Guards the weekly prodseed lane (AKSH feature-marketing through the finance gate stack):
  - LANE ISOLATION: prodseed never flushes another lane's draft and no other lane flushes a
    prodseed draft (the 2026-06-23 flood class of bug).
  - SLATE INTEGRITY: every slate slug matches the lane selector and rotation is total.
  - CAP UNTOUCHED: MAX_THREADS_PER_DAY stays at Srijan's authorized 4 (Wed = trio 3 + seed 1).

Run:  python3 test_prodseed_lane.py   (prints PASS/FAIL, exits nonzero on failure)
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import post_x as px
from monitor.product_seed_post import SLATE, pick

TODAY = "2026-07-08"  # a Wednesday


def fm(status="needs-review", engine="finance", generated=TODAY, topic="seed topic"):
    return {"status": status, "engine": engine, "generated": generated, "topic": topic}


# ── lane registration ──
def test_prodseed_window_registered():
    assert "prodseed" in px.LANE_WINDOWS
    lo, hi = px.LANE_WINDOWS["prodseed"]
    assert 0 <= lo < hi <= 24


def test_shared_cap_unchanged():
    assert px.MAX_THREADS_PER_DAY == 4


# ── slate integrity ──
def test_all_slate_slugs_match_lane_selector():
    for s in SLATE:
        name = f"{TODAY}-finance-{s['slug']}.md"
        assert "prodseed" in name, s["slug"]
        assert px.eligible(name, fm(), lane_slug="prodseed", today=TODAY, auto_approve=True), s["slug"]


def test_rotation_covers_slate():
    seen = {pick(date(2026, 7, 1) + timedelta(weeks=w), None)["slug"] for w in range(len(SLATE))}
    assert seen == {s["slug"] for s in SLATE}, seen


def test_slate_contexts_pass_hard_lint():
    # the context we FEED the generator must itself be clean (defense in depth; the
    # generated draft is linted again at generation and at post time)
    from compliance.lint import is_safe
    for s in SLATE:
        assert is_safe(s["context"]), f"slate context for {s['slug']} trips the SEBI lint"


# ── isolation both directions ──
def test_prodseed_lane_ignores_other_lanes():
    for other in ("2026-07-08-finance-premarket-note.md",
                  "2026-07-08-finance-daily-market-wrap.md",
                  "2026-07-08-finance-evening-wrap.md",
                  "2026-07-08-ai-worl-audit-the-gate.md"):
        assert not px.eligible(other, fm(), lane_slug="prodseed", today=TODAY, auto_approve=True), other


def test_other_lanes_ignore_prodseed_draft():
    name = "2026-07-08-finance-prodseed-dcf-sensitivity.md"
    for lane in ("premarket-note", "daily-market-wrap", "evening-wrap", "audit"):
        assert not px.eligible(name, fm(), lane_slug=lane, today=TODAY, auto_approve=True), lane


def test_prodseed_auto_lift_is_finance_only_behavior():
    # prodseed drafts are finance-engine, so auto mode lifts needs-review — same authorized
    # behavior as the daily trio. A hypothetical non-finance prodseed draft must NOT lift.
    name = "2026-07-08-finance-prodseed-dcf-sensitivity.md"
    assert px.eligible(name, fm(status="needs-review"), lane_slug="prodseed", today=TODAY, auto_approve=True)
    assert not px.eligible(name, fm(status="needs-review", engine="ai-world"),
                           lane_slug="prodseed", today=TODAY, auto_approve=True)


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
