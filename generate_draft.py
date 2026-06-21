#!/usr/bin/env python3
"""
Draft generator — takes a topic/context and outputs a formatted content draft.

Bulk generation routes to a cheap Anthropic-compatible endpoint when one is configured
via env (ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN + BULK_MODEL). If it isn't, it uses
the `claude` CLI, which works headless on your logged-in plan — no API key needed. See
.env.template.
"""
from __future__ import annotations  # PEP 604 (`str | None`) on Python 3.7+
import os, sys, json, re
from datetime import date
from pathlib import Path

# Model routing — all env-driven, no hardcoded endpoints or credentials.
BULK_BASE = os.environ.get("ANTHROPIC_BASE_URL")       # cheap endpoint, optional
BULK_TOKEN = os.environ.get("ANTHROPIC_AUTH_TOKEN")    # token for that endpoint
BULK_MODEL = os.environ.get("BULK_MODEL")              # cheap model id for bulk gen
FALLBACK_MODEL = os.environ.get("FALLBACK_MODEL", "claude-opus-4-8")  # quality fallback

ENGINE_DIR = Path(__file__).parent
VOICE_MD = (ENGINE_DIR / "voice.md").read_text()
DRAFTS_DIR = ENGINE_DIR / "drafts"
DRAFTS_DIR.mkdir(exist_ok=True)


SYSTEM_PROMPT = f"""You are a content generator writing in Srijan's voice. Follow this style guide exactly:

{VOICE_MD}

Output format — always produce all three sections:
## NEWSLETTER (~350-400 words)
[newsletter body]

## X / TWITTER THREAD
[numbered posts, each under 280 chars]

## LINKEDIN CAROUSEL (7 slides)
[slide 1: hook | slide 2-6: body | slide 7: CTA]

SEBI rule (for finance content): education/data/language-analysis only. Never say buy/sell/hold."""


def _gen_via_sdk(prompt: str) -> str:
    """Bulk path: a cheap Anthropic-compatible endpoint. Raises if not configured."""
    import anthropic
    if not (BULK_BASE and BULK_TOKEN and BULK_MODEL):
        raise ValueError("bulk endpoint not configured")
    client = anthropic.Anthropic(api_key=BULK_TOKEN, base_url=BULK_BASE)
    msg = client.messages.create(
        model=BULK_MODEL, max_tokens=2048,
        system=SYSTEM_PROMPT, messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def _gen_via_cli(prompt: str) -> str:
    """Default path: the `claude` CLI (uses your logged-in plan, works headless)."""
    import subprocess
    full = SYSTEM_PROMPT + "\n\n" + prompt
    out = subprocess.run(
        ["claude", "-p", full], capture_output=True, text=True, timeout=300,
    )
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(f"claude CLI failed (rc={out.returncode}): {out.stderr[:300]}")
    return out.stdout.strip()


def generate(engine: str, topic: str, context: str, slug: str | None = None) -> str:
    """Generate a draft and save it. Returns the saved file path."""
    today = date.today().isoformat()
    slug = slug or re.sub(r"[^a-z0-9]+", "-", topic.lower())[:40].strip("-")
    out_path = DRAFTS_DIR / f"{today}-{engine[:7]}-{slug}.md"

    prompt = f"""Engine: {engine}
Topic: {topic}

Context / source material:
{context}

Write the newsletter, X thread, and LinkedIn carousel for this piece. Follow the voice guide.
{"SEBI: finance content — education and data analysis only, no buy/sell calls." if engine == "finance" else ""}"""

    # Bulk endpoint if configured (saves quota); else the CLI (default plan).
    if BULK_BASE and BULK_TOKEN and BULK_MODEL:
        try:
            body, model_used = _gen_via_sdk(prompt), BULK_MODEL
        except Exception as e:
            print(f"Bulk endpoint failed ({e}); using claude CLI", file=sys.stderr)
            body, model_used = _gen_via_cli(prompt), "claude-cli"
    else:
        body, model_used = _gen_via_cli(prompt), "claude-cli"

    # HARD compliance gate for finance content — a per-stock call never reaches the queue.
    status = "needs-review"
    if engine == "finance":
        from compliance.lint import report as lint_report
        blocks = [v for v in lint_report(body) if v["severity"] == "block"]
        if blocks:
            status = "BLOCKED-sebi"
            offenders = "; ".join(f"{b.get('snippet') or b.get('path')}" for b in blocks[:5])
            body = (f"> ⛔ SEBI LINT BLOCKED — {len(blocks)} per-stock directional call(s) detected; "
                    f"do NOT publish. Offenders: {offenders}\n\n") + body
            print(f"⛔ SEBI gate BLOCKED this draft ({len(blocks)} violations) — marked BLOCKED-sebi",
                  file=sys.stderr)

    frontmatter = f"""---
id: {today}-{slug}
engine: {engine}
topic: {topic}
status: {status}
model: {model_used}
generated: {today}
---

"""
    out_path.write_text(frontmatter + body)
    print(f"Draft saved: {out_path}" + ("  [BLOCKED — see top of file]" if status == "BLOCKED-sebi" else ""))
    return str(out_path)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("engine", choices=["ai-world", "finance"])
    p.add_argument("topic")
    p.add_argument("--context", default="", help="Source material / news context")
    p.add_argument("--context-file", help="Read context from file")
    args = p.parse_args()

    ctx = args.context
    if args.context_file:
        ctx = Path(args.context_file).read_text()

    generate(args.engine, args.topic, ctx)
