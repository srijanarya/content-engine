#!/usr/bin/env python3
"""
Draft generator — takes a topic/context and outputs a formatted content draft.

Generation tries the logged-in Claude plan, then ChatGPT-backed Codex, then the explicitly
configured Anthropic-compatible bulk endpoint. See .env.template.
"""
from __future__ import annotations  # PEP 604 (`str | None`) on Python 3.7+
import sys, re
from datetime import date
from pathlib import Path

from claude_env import TextResult, run_text

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


def gen_text(prompt: str, system: str | None = SYSTEM_PROMPT) -> TextResult:
    return run_text(prompt, system)


def _learnings_line() -> str:
    """One 'what's been working' line from learn.py's output. Empty until the loop has data."""
    lt = ENGINE_DIR / "monitor" / "learnings_top.txt"
    txt = lt.read_text().strip() if lt.exists() else ""
    if not txt:
        return ""
    return ("\n\nWhat's been working lately (lean toward these where natural; never at the expense of "
            "the voice or the SEBI rule):\n" + txt)


def generate(engine: str, topic: str, context: str, slug: str | None = None, *,
             use_learnings: bool = True) -> str:
    """Generate a draft and save it. Returns the saved file path.

    use_learnings (keyword-only, default on) folds learn.py's top biases into the USER prompt — not the
    system prompt, so it can never weaken the SEBI framing. No-op until monitor/learnings_top.txt exists.
    """
    today = date.today().isoformat()
    slug = slug or re.sub(r"[^a-z0-9]+", "-", topic.lower())[:40].strip("-")
    out_path = DRAFTS_DIR / f"{today}-{engine[:7]}-{slug}.md"

    prompt = f"""Engine: {engine}
Topic: {topic}

Context / source material:
{context}

Write the newsletter, X thread, and LinkedIn carousel for this piece. Follow the voice guide.
{"SEBI: finance content — education and data analysis only, no buy/sell calls." if engine == "finance" else ""}""" + (_learnings_line() if use_learnings else "")

    result = gen_text(prompt)
    body, model_used = result.text, result.provider

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
