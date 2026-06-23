#!/usr/bin/env python3
"""Fast unit tests for the video engine's pure logic (no rendering, no Chromium, no ffmpeg).

Run:  python3 video/test_make_video.py    (prints PASS/FAIL, exits nonzero on failure)
Also pytest-discoverable (test_* functions). The render path itself is covered by make_video's own
end-of-run assert (output mp4 exists + duration > 1s) — kept out of here so this stays sub-second.

TDD note for the next session: add a failing test HERE first (e.g. for multi-channel caption variants
or a Shorts <=60s slide-budget rule), then make it pass in make_video.py / render_latest.py.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_video as mv
import render_latest as rl

CAROUSEL = """## NEWSLETTER
blah

## LINKEDIN CAROUSEL (3 slides)

**Slide 1 — Hook**
First hook line.
Second line.

**Slide 2**
DATA A +1%
DATA B -2.5%

**Slide 3 — CTA**
Follow for honest reads.
"""

THREAD_ONLY = """## X / TWITTER THREAD

**1/**
Tweet one here.

**2/**
Tweet two here.
"""

CAROUSEL_NUMBERED = """## LINKEDIN CAROUSEL (3 slides)

1. **First hook.** sub line.
2. **Body point** data +5%.
3. **CTA** follow for receipts.
"""


def test_parse_carousel_splits_and_keeps_data_lines():
    s = mv.parse_slides(CAROUSEL)
    assert s == ["First hook line.\nSecond line.", "DATA A +1%\nDATA B -2.5%",
                 "Follow for honest reads."], s


def test_parse_falls_back_to_x_thread():
    s = mv.parse_slides(THREAD_ONLY)
    assert s == ["Tweet one here.", "Tweet two here."], s


def test_parse_numbered_carousel():
    # AI drafts use a "1. **...**" numbered carousel, not "**Slide N**"
    s = mv.parse_slides(CAROUSEL_NUMBERED)
    assert len(s) == 3, s
    assert s[0].startswith("First hook."), s
    assert "data +5%" in s[1], s


def test_parse_strips_bare_label_line():
    # defensive: a "Hook"/"CTA" word left as its own body line is dropped
    s = mv.parse_slides("## LINKEDIN CAROUSEL\n\n**Slide 1**\nHook\nReal content.\n")
    assert s == ["Real content."], s


def test_font_size_thresholds():
    assert mv._font_size("x" * 201) == 44
    assert mv._font_size("x" * 150) == 52
    assert mv._font_size("x" * 100) == 60
    assert mv._font_size("short") == 68


def test_card_html_escapes_and_brands():
    h = mv.card_html("buy < sell & hold")
    assert "@aryasrijan" in h and mv.DISCLAIM in h
    assert "&lt;" in h and "&amp;" in h and "<script" not in h.lower()


def test_clean_strips_markdown():
    assert mv._clean("**bold**") == "bold"
    assert mv._clean("- bullet") == "bullet"
    assert mv._clean("> quote") == "quote"


def test_caption_extracts_hook_and_disclaimer():
    c = rl.caption(THREAD_ONLY)
    assert c.startswith("Tweet one here.")
    assert "Not investment advice." in c


def test_chrome_bin_resolves():
    # the render path depends on this binary existing; fail loudly if the install moved
    assert Path(mv.chrome_bin()).exists()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t(); print(f"PASS {t.__name__}")
        except Exception as e:  # noqa: BLE001 - test runner surfaces all failures
            failed += 1; print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
