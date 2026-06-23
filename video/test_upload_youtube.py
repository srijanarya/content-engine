#!/usr/bin/env python3
"""Self-check for upload_youtube's pure logic (no network, no creds). Run: python3 video/test_upload_youtube.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from upload_youtube import DISCLAIM, build_body, _clamp_tags, _truncate  # noqa: E402


def test_truncate():
    assert _truncate("abc", 10) == "abc"
    long = "x" * 200
    assert len(_truncate(long, 100)) == 100 and _truncate(long, 100).endswith("…")


def test_clamp_tags():
    assert _clamp_tags(["#Nifty", " ai ", ""]) == ["Nifty", "ai"]  # strips # and blanks
    big = [f"tag{i:03d}" for i in range(200)]  # would blow the char cap
    out = _clamp_tags(big)
    assert sum(len(t) for t in out) + max(0, len(out) - 1) <= 480
    assert len(out) < len(big)


def test_build_body_disclaimer_and_limits():
    b = build_body("t" * 150, "some desc", ["#a", "b"], "unlisted", "27")
    assert len(b["snippet"]["title"]) == 100
    assert DISCLAIM.lower() in b["snippet"]["description"].lower()  # auto-appended
    assert b["snippet"]["tags"] == ["a", "b"]
    assert b["snippet"]["categoryId"] == "27"
    assert b["status"]["privacyStatus"] == "unlisted"
    assert b["status"]["selfDeclaredMadeForKids"] is False


def test_build_body_no_double_disclaimer():
    desc = f"hello {DISCLAIM}"
    b = build_body("x", desc, [], "public", "28")
    assert b["snippet"]["description"].lower().count(DISCLAIM.lower()) == 1  # not duplicated


def test_bad_privacy_rejected():
    try:
        build_body("x", "y", [], "semi-public", "27")
        assert False, "should reject bad privacy"
    except ValueError:
        pass


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("all passed")
