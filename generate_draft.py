#!/usr/bin/env python3
"""
Draft generator — takes a topic/context and outputs a formatted content draft.

Generation tries the `claude` CLI first (headless on your logged-in plan — no API key
needed) and degrades to a cheap Anthropic-compatible bulk endpoint when the CLI fails
(e.g. monthly spend limit) and one is configured via env (BULK_BASE_URL +
BULK_AUTH_TOKEN + BULK_MODEL). The BULK_* names are deliberate: exporting
ANTHROPIC_BASE_URL/AUTH_TOKEN would silently redirect the `claude` CLI subprocess to
the bulk endpoint too. See .env.template.
"""
from __future__ import annotations  # PEP 604 (`str | None`) on Python 3.7+
import os, sys, json, re
from datetime import date
from pathlib import Path

# Model routing — all env-driven, no hardcoded endpoints or credentials.
BULK_BASE = os.environ.get("BULK_BASE_URL")      # cheap degrade endpoint, optional
BULK_TOKEN = os.environ.get("BULK_AUTH_TOKEN")   # token for that endpoint
BULK_MODEL = os.environ.get("BULK_MODEL")        # model id on that endpoint

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


def _gen_via_sdk(prompt: str, system: str | None = SYSTEM_PROMPT) -> str:
    """Degrade path: a cheap Anthropic-compatible endpoint. Raises if not configured."""
    import anthropic
    if not (BULK_BASE and BULK_TOKEN and BULK_MODEL):
        raise ValueError("bulk endpoint not configured")
    client = anthropic.Anthropic(api_key=BULK_TOKEN, base_url=BULK_BASE)
    msg = client.messages.create(
        model=BULK_MODEL, max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
        **({"system": system} if system else {}),
    )
    return msg.content[0].text


def _gen_via_cli(prompt: str, system: str | None = SYSTEM_PROMPT) -> str:
    """Primary path: the `claude` CLI (uses your logged-in plan, works headless)."""
    import subprocess
    full = (system + "\n\n" + prompt) if system else prompt
    out = subprocess.run(
        ["claude", "-p", full], capture_output=True, text=True, timeout=300,
    )
    if out.returncode != 0 or not out.stdout.strip():
        err = (out.stderr.strip() or out.stdout.strip())[:300]  # spend-limit msg lands on stdout
        raise RuntimeError(f"claude CLI failed (rc={out.returncode}): {err}")
    return out.stdout.strip()


def _gen_via_failover(prompt: str, system: str | None = SYSTEM_PROMPT) -> tuple[str, str]:
    """Opt-in path (GEN_ENGINE_FAILOVER=1): ~/bin/llm-engine tries plan-a → plan-b →
    codex → glm with per-engine cooldown state, so a spend-capped default CLI degrades
    instead of silently killing the lane (the 2026-07-06 all-day outage). Text on
    stdout; the winning engine is announced on stderr as `engine=<name>`."""
    import shutil, subprocess
    bin_ = shutil.which("llm-engine") or str(Path.home() / "bin" / "llm-engine")
    full = (system + "\n\n" + prompt) if system else prompt
    # 240s per engine × up to 4 engines; outer bound leaves headroom over the sum.
    out = subprocess.run([bin_, "--timeout", "240", full],
                         capture_output=True, text=True, timeout=1020)
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(f"llm-engine failed (rc={out.returncode}): {out.stderr.strip()[:300]}")
    m = re.search(r"engine=(\S+)", out.stderr)
    return out.stdout.strip(), (f"llm-engine:{m.group(1)}" if m else "llm-engine")


def gen_text(prompt: str, system: str | None = SYSTEM_PROMPT) -> tuple[str, str]:
    """CLI first (logged-in plan); degrade to the bulk endpoint on failure. Returns (text, model).

    GEN_ENGINE_FAILOVER=1 (opt-in, see .env.template) replaces the whole ladder with
    ~/bin/llm-engine's multi-engine failover instead."""
    if os.environ.get("GEN_ENGINE_FAILOVER") == "1":
        return _gen_via_failover(prompt, system)
    try:
        return _gen_via_cli(prompt, system), "claude-cli"
    except Exception as e:
        if not (BULK_BASE and BULK_TOKEN and BULK_MODEL):
            raise
        print(f"claude CLI failed ({e}); degrading to bulk endpoint", file=sys.stderr)
        return _gen_via_sdk(prompt, system), BULK_MODEL


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

    body, model_used = gen_text(prompt)

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
