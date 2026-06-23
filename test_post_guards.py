#!/usr/bin/env python3
"""Guards the 2026-06-23 incidents so they can't recur:
  - FLOOD/ORDER: post_x must post ONE lane's TODAY draft only, never a backlog / prior-day / wrong-lane.
  - PER-COMPANY: post_x must never post a finance draft that is ABOUT a single listed company (SEBI).

Run:  python3 test_post_guards.py   (prints PASS/FAIL, exits nonzero on failure; pytest-discoverable)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import post_x as px

TODAY = "2026-06-23"


def fm(status="needs-review", engine="finance", generated=TODAY, topic="daily market wrap 2026-06-23"):
    return {"status": status, "engine": engine, "generated": generated, "topic": topic}


# ── per-company title guard ──
def test_blocks_tcs_title():
    assert px.names_company("Tata Consultancy Services Limited Financ",
                            "2026-06-23-finance-tata-consultancy-services-limited-financ.md")


def test_blocks_hcl_title():
    assert px.names_company("HCL Technologies Limited financial resul",
                            "2026-06-21-finance-hcl-technologies-limited-financial-resul.md")


def test_blocks_bare_ticker_title():
    assert px.names_company("INFY Q4FY26 read", "2026-06-20-finance-infy-q4fy26.md")


def test_allows_sector_wrap_titles():
    assert not px.names_company("daily market wrap 2026-06-23", "2026-06-23-finance-daily-market-wrap.md")
    assert not px.names_company("pre-market note 2026-06-23", "2026-06-23-finance-premarket-note.md")
    assert not px.names_company("evening wrap 2026-06-23", "2026-06-23-finance-evening-wrap.md")


# ── eligibility: one lane, today only, no per-company ──
def test_picks_todays_lane_draft():
    assert px.eligible("2026-06-23-finance-premarket-note.md", fm(topic="pre-market note 2026-06-23"),
                       lane_slug="premarket-note", today=TODAY, auto_approve=True)


def test_rejects_other_lane_draft():
    # asking for the premarket lane must NOT select the daily-wrap draft (the out-of-order flood)
    assert not px.eligible("2026-06-23-finance-daily-market-wrap.md", fm(),
                           lane_slug="premarket-note", today=TODAY, auto_approve=True)


def test_rejects_prior_day_backlog():
    # yesterday's stuck evening wrap must never post today (the backlog flush)
    assert not px.eligible("2026-06-22-finance-evening-wrap.md",
                           fm(generated="2026-06-22", topic="evening wrap 2026-06-22"),
                           lane_slug="evening-wrap", today=TODAY, auto_approve=True)


def test_rejects_already_posted():
    assert not px.eligible("2026-06-23-finance-premarket-note.md", fm(status="posted"),
                           lane_slug="premarket-note", today=TODAY, auto_approve=True)


def test_rejects_per_company_draft_even_when_fresh():
    # a per-company finance draft must never be eligible, even fresh + matching slug + auto
    assert not px.eligible("2026-06-23-finance-tata-consultancy-services-limited-financ.md",
                           fm(topic="Tata Consultancy Services Limited Financ"),
                           lane_slug="tata-consultancy", today=TODAY, auto_approve=True)


def test_auto_only_lifts_finance_needs_review():
    # auto mode auto-approves finance needs-review ONLY; an ai-world needs-review draft is not eligible
    assert not px.eligible("2026-06-23-ai-worl-something.md", fm(engine="ai-world", topic="some ai topic"),
                           lane_slug=None, today=TODAY, auto_approve=True)


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
