#!/usr/bin/env python3
"""Turn an engine finance draft into a faceless vertical short. Fully local, no paid API, no account:
macOS `say` (Indian-English voice) narrates; Playwright's already-installed headless Chromium renders
each card from HTML/CSS (this ffmpeg has no drawtext/freetype, and HTML cards look better anyway);
ffmpeg muxes card+voiceover per slide and concatenates.

  python3 video/make_video.py drafts/2026-06-22-finance-daily-market-wrap.md [--max-slides 6] [--voice Aman]

Input  : a draft markdown the engine already writes (LINKEDIN CAROUSEL preferred, X THREAD fallback) —
         the same SEBI-safe index/sector copy the text posts use (no per-stock calls).
Output : video/out/<draft-stem>.mp4 (1080x1920 H.264/AAC), ready to hand-post to Shorts/Reels.

ponytail: reuses the project's existing Chromium (rung 4) instead of adding moviepy/PIL/a TTS dep or a
paid video API. One static card per slide. Add motion/b-roll only if engagement data says it's worth it.
"""
import glob
import html
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
OUT_DIR = Path(__file__).resolve().parent / "out"
HANDLE = "@aryasrijan"
DISCLAIM = "Market data for education only. Not investment advice."
W, H, FPS, PAD = 1080, 1920, 30, 0.5

SAY = shutil.which("say") or "/usr/bin/say"
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
FFPROBE = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"


def chrome_bin() -> str:
    pat = str(Path.home() / "Library/Caches/ms-playwright/chromium_headless_shell-*/"
                            "chrome-headless-shell-mac-*/chrome-headless-shell")
    hits = sorted(glob.glob(pat))
    if not hits:
        raise SystemExit("no Playwright chrome-headless-shell found (expected under ~/Library/Caches/ms-playwright)")
    return hits[-1]


CHROME = None  # resolved lazily in main


def _clean(line: str) -> str:
    return re.sub(r"\*\*|__|^#+\s*|^[-*>]\s*", "", line.strip()).strip()


def _slides_from(block: str, pat: str) -> list[str]:
    out = []
    for b in re.split(pat, block):
        lines = [_clean(l) for l in b.splitlines() if _clean(l)]
        if lines and lines[0].lower() in ("hook", "cta"):
            lines = lines[1:]
        if lines:
            out.append("\n".join(lines))
    return out


def parse_slides(md: str) -> list[str]:
    """Per-card text, newlines preserved (data lines stay on their own line). Handles both carousel
    styles: '**Slide N**' (finance drafts) and '1. ...' numbered (AI drafts)."""
    car = re.search(r"LINKEDIN CAROUSEL.*?\n(.*?)(?:\n---|\Z)", md, re.S | re.I)
    if car:
        block = car.group(1)
        if re.search(r"\*\*Slide\s*\d+", block, re.I):
            out = _slides_from(block, r"\*\*Slide\s*\d+[^\n]*\*\*")
        elif re.search(r"(?m)^\s*\d+\.\s+\S", block):
            # ponytail: numbered carousel — split on line-leading "N. "; a slide body line that itself
            # starts with "<digit>." would over-split, acceptable for current drafts.
            out = _slides_from(block, r"(?m)^\s*\d+\.\s+")
        else:
            out = _slides_from(block, r"\Z")  # no markers: degenerate single card
        if out:
            return out
    thread = re.split(r"\*\*\d+/\*\*", md.split("LINKEDIN")[0])
    return ["\n".join(_clean(l) for l in b.splitlines() if _clean(l)) for b in thread[1:] if b.strip()]


def _font_size(text: str) -> int:
    n = len(text.replace("\n", ""))
    return 44 if n > 200 else 52 if n > 140 else 60 if n > 90 else 68


def card_html(text: str) -> str:
    body = "<br>".join(html.escape(l) for l in text.split("\n"))
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;width:{W}px;height:{H}px}}
body{{background:#0A0E27;color:#fff;font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;
display:flex;flex-direction:column;justify-content:center;align-items:center;
padding:150px 90px;box-sizing:border-box;text-align:center}}
.bar{{position:absolute;top:0;left:0;right:0;height:12px;background:#64FFDA}}
.handle{{position:absolute;top:120px;left:0;right:0;color:#64FFDA;font-size:46px;font-weight:700;letter-spacing:.5px}}
.body{{font-size:{_font_size(text)}px;line-height:1.34;font-weight:700}}
.foot{{position:absolute;bottom:110px;left:0;right:0;color:#8892B0;font-size:30px;padding:0 60px}}
</style></head><body>
<div class="bar"></div><div class="handle">{HANDLE}</div>
<div class="body">{body}</div>
<div class="foot">{DISCLAIM}</div></body></html>"""


def _dur(path: Path) -> float:
    out = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def make_card(text: str, voice: str, tmp: Path, idx: int) -> Path:
    # narration (newlines -> sentence pauses so `say` doesn't run data points together)
    narr = tmp / f"n{idx}.txt"; narr.write_text(text.replace("\n", ". "))
    aiff = tmp / f"n{idx}.aiff"
    subprocess.run([SAY, "-v", voice, "-f", str(narr), "-o", str(aiff)], check=True)
    dur = _dur(aiff) + PAD
    # card png via headless chromium
    hpath = tmp / f"c{idx}.html"; hpath.write_text(card_html(text))
    png = tmp / f"c{idx}.png"
    subprocess.run([CHROME, "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                    f"--window-size={W},{H}", f"--screenshot={png}", f"file://{hpath}"],
                   check=True, capture_output=True)
    # compose card + voiceover
    seg = tmp / f"s{idx}.mp4"
    subprocess.run([FFMPEG, "-y", "-loop", "1", "-framerate", str(FPS), "-i", str(png),
                    "-i", str(aiff), "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
                    "-pix_fmt", "yuv420p", "-r", str(FPS), "-vf", f"scale={W}:{H}",
                    "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2", "-t", f"{dur:.3f}",
                    str(seg)], check=True, capture_output=True)
    return seg


def _flag(name: str, default: str) -> str:
    for i, a in enumerate(sys.argv):
        if a == name and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return default


def main() -> int:
    global CHROME
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("usage: make_video.py <draft.md> [--max-slides N] [--voice Aman]"); return 2
    draft = Path(args[0])
    if not draft.is_absolute():
        draft = next((p for p in (ENGINE / draft, ENGINE.parent / draft, Path.cwd() / draft) if p.exists()), draft)
    slides = parse_slides(draft.read_text())[:int(_flag("--max-slides", "7"))]
    if not slides:
        raise SystemExit(f"no slides parsed from {draft} (need a LINKEDIN CAROUSEL or X THREAD section)")
    voice = _flag("--voice", "Aman")
    CHROME = chrome_bin()
    print(f"{draft.name}: {len(slides)} cards, voice={voice}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / (draft.stem + ".mp4")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        segs = [make_card(s, voice, tmp, i) for i, s in enumerate(slides)]
        lst = tmp / "list.txt"; lst.write_text("".join(f"file '{s}'\n" for s in segs))
        subprocess.run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-c", "copy", str(out)], check=True, capture_output=True)

    total = _dur(out)
    assert out.exists() and total > 1, f"render produced no real video: {out} ({total}s)"
    print(f"OK -> {out}  ({total:.1f}s, {out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
