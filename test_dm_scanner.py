#!/usr/bin/env python3
"""Guards the E3 keyword-DM scanner (x/dm_scout.py + x/draft_dms.py): a keyword match on our
own posts queues exactly one dm-inbox item; the template stays DRAFT (unapproved) so nothing
drafts; once approved, a filled draft with a real link passes the gate and a bad one doesn't;
and NO sender exists yet (no post_dms.py, no x_browser.mjs sendDM) so nothing can actually send.

Run:  python3 test_dm_scanner.py   (PASS/FAIL, exits nonzero; pytest-discoverable)
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "x"))
import dm_scout
import draft_dms

FAKE_POSTS = {"posts": [
    {"url": "https://x.com/user1/status/1", "handle": "user1", "text": "send me the PULSE pdf"},
    {"url": "https://x.com/user2/status/2", "handle": "user2", "text": "nice thread, no keyword here"},
    {"url": "https://x.com/user3/status/3", "handle": "user3", "text": "what's in the REPORT?"},
]}


def test_keyword_scan_queues_exactly_matched_posts():
    with tempfile.TemporaryDirectory() as td:
        pipe = Path(td)
        with (
            mock.patch.object(dm_scout, "PIPE", pipe),
            mock.patch.object(dm_scout, "DM_INBOX", pipe / "dm-inbox"),
            mock.patch.object(dm_scout, "SEEN", pipe / "seen.json"),
            mock.patch.object(dm_scout.xb, "killed", return_value=False),
            mock.patch.object(dm_scout.xb, "search_posts", return_value=FAKE_POSTS),
            mock.patch.object(dm_scout.xb, "activity", lambda *a: None),
        ):
            rc = dm_scout.main()
        assert rc == 0
        queued = list((pipe / "dm-inbox").glob("*.json"))
        assert len(queued) == 2, queued   # user2's non-matching post must be excluded
        keywords = {json.loads(f.read_text())["keyword"] for f in queued}
        assert keywords == {"PULSE", "REPORT"}


def test_rescan_does_not_requeue_seen_posts():
    with tempfile.TemporaryDirectory() as td:
        pipe = Path(td)
        with (
            mock.patch.object(dm_scout, "PIPE", pipe),
            mock.patch.object(dm_scout, "DM_INBOX", pipe / "dm-inbox"),
            mock.patch.object(dm_scout, "SEEN", pipe / "seen.json"),
            mock.patch.object(dm_scout.xb, "killed", return_value=False),
            mock.patch.object(dm_scout.xb, "search_posts", return_value=FAKE_POSTS),
            mock.patch.object(dm_scout.xb, "activity", lambda *a: None),
        ):
            dm_scout.main()
            for f in (pipe / "dm-inbox").glob("*.json"):
                f.unlink()   # simulate draft_dms having drained the inbox
            dm_scout.main()
        assert list((pipe / "dm-inbox").glob("*.json")) == []


def test_unapproved_template_drafts_nothing():
    with tempfile.TemporaryDirectory() as td:
        pipe = Path(td)
        inbox = pipe / "dm-inbox"
        inbox.mkdir()
        (inbox / "1.json").write_text(json.dumps(
            {"handle": "user1", "keyword": "PULSE", "pillar": "finance",
             "url": "https://x.com/user1/status/1"}))
        draft_template = draft_dms.TEMPLATE_FILE.read_text()   # real file, status: DRAFT
        assert draft_dms.template_status(draft_template) == "draft"
        with (
            mock.patch.object(draft_dms, "PIPE", pipe),
            mock.patch.object(draft_dms, "DM_INBOX", inbox),
            mock.patch.object(draft_dms, "DM_APPROVED", pipe / "dm-approved"),
            mock.patch.object(draft_dms, "DM_REJECTED", pipe / "dm-rejected"),
            mock.patch.object(draft_dms.xb, "killed", return_value=False),
        ):
            rc = draft_dms.main()
        assert rc == 0
        assert list(inbox.glob("*.json")) == [inbox / "1.json"], \
            "unapproved template must leave the inbox untouched"


def test_approved_template_with_real_link_is_drafted_and_gated():
    approved_text = draft_dms.TEMPLATE_FILE.read_text().replace("status: DRAFT", "status: approved")
    with tempfile.TemporaryDirectory() as td:
        pipe = Path(td)
        inbox, approved_dir, rejected_dir = pipe / "dm-inbox", pipe / "dm-approved", pipe / "dm-rejected"
        inbox.mkdir()
        (inbox / "1.json").write_text(json.dumps(
            {"handle": "user1", "keyword": "PULSE", "pillar": "finance",
             "url": "https://x.com/user1/status/1"}))
        (inbox / "2.json").write_text(json.dumps(
            {"handle": "user2", "keyword": "REPORT", "pillar": "finance",   # no template links -> reject
             "url": "https://x.com/user2/status/2"}))
        with (
            mock.patch.object(draft_dms, "PIPE", pipe),
            mock.patch.object(draft_dms, "DM_INBOX", inbox),
            mock.patch.object(draft_dms, "DM_APPROVED", approved_dir),
            mock.patch.object(draft_dms, "DM_REJECTED", rejected_dir),
            mock.patch.object(draft_dms, "LINKS_FILE",
                              pipe / "does-not-exist.json"),   # no links configured -> PULSE also rejects
            mock.patch.object(draft_dms.xb, "killed", return_value=False),
            mock.patch.object(draft_dms, "TEMPLATE_FILE", pipe / "tmpl.md"),
        ):
            (pipe / "tmpl.md").write_text(approved_text)
            rc = draft_dms.main()
        assert rc == 0
        assert list(approved_dir.glob("*.md")) == [], "no links configured -> nothing should approve"
        assert len(list(rejected_dir.glob("*.md"))) == 2


def test_fill_refuses_on_missing_link():
    approved_text = draft_dms.TEMPLATE_FILE.read_text().replace("status: DRAFT", "status: approved")
    templates = draft_dms.parse_template(approved_text)
    try:
        draft_dms.fill(templates["PULSE"]["dm"], {"link": "https://pub/p.pdf"})   # signup missing
    except ValueError as e:
        assert "signup" in str(e)
        return
    raise AssertionError("missing placeholder did not refuse")


def test_gate_blocks_a_per_stock_directional_fill():
    ok, reason = draft_dms.gate(
        "Buy RELIANCE tomorrow, guaranteed target 3200. https://pub/p.pdf", "finance")
    assert not ok, reason


def test_no_dm_sender_exists_yet():
    """The plan explicitly scopes C4 to dry-run drafting only — no sendDM transport, no
    post_dms.py. This is a guard against silently adding one without updating the wiki."""
    x_dir = Path(__file__).resolve().parent / "x"
    assert not (x_dir / "post_dms.py").exists(), "post_dms.py must not exist yet (C4 is dry-run only)"
    browser_src = (x_dir / "x_browser.mjs").read_text()
    assert "sendDM" not in browser_src, "sendDM transport must not exist yet (C4 is dry-run only)"


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted({k: v for k, v in globals().items()
                            if k.startswith("test_") and callable(v)}.items()):
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {name}: {e}")
    sys.exit(1 if failed else 0)
