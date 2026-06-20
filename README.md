# content-engine

A self-learning content pipeline for a technical + finance personal brand. It monitors two
news streams (the AI world and Indian markets), drafts pieces in a calibrated voice, and learns
from real engagement data which topics, hooks, and formats to lean into next.

The loop:

```
monitor  →  analyze  →  draft (voice-calibrated)  →  [human publishes]  →  measure  →  learn  →  repeat
```

The human stays in exactly one place — the publish click. Everything else runs autonomously.

## Why it exists

Most "AI content tools" generate generic slop. This one is built on two opinions:

1. **The draft is only as good as the source.** Each engine pulls from real signal — HN/arXiv for
   AI, the NSE earnings calendar + transcripts for finance — not a trending-topics API.
2. **It improves on data, not vibes.** Every published piece is logged with its engagement
   metrics. A weekly learn pass ranks what actually performed and biases the next cycle toward it.

## Architecture

| File | Role |
|------|------|
| `voice.md` | The style guide the generator follows. Warm, first-person, receipts-first — not analyst-clinical. The learn loop refines it from what performs. |
| `generate_draft.py` | Takes an engine + topic + source context, returns a newsletter / X thread / LinkedIn carousel in the voice. Routes to a cheap model for bulk gen, falls back to a frontier model. |
| `monitor/ai_world_monitor.py` | Watches Hacker News + arXiv for notable AI releases/benchmarks. Dedups against `seen_ai.json`, drafts the top item. |
| `monitor/finance_monitor.py` | Watches the NSE earnings calendar + finance news for IT-services earnings and macro events. SEBI-safe: education/data/language-analysis only, never buy/sell calls. |
| `learn.py` | Weekly pass over `content_performance.json` → ranks top hooks/topics/engines → writes biases for the next cycle. |
| `content_performance.json` | The ledger. One row per published piece: topic · hook · format · engine · metrics. |
| `monitor/run_monitors.sh` | Daily entrypoint (wired to a launchd agent). Runs both monitors. |

## The self-learning part

`content_performance.json` is to this engine what a feature-importance table is to a model. After
each publish, you fill in the engagement metrics (X impressions/engagement, LinkedIn
reactions/comments, newsletter open/click). `learn.py` then:

- ranks hook styles by average engagement,
- ranks topics by what got published and performed,
- emits a "biases for next cycle" block that the generator reads.

Losing hooks get dropped; winning ones get A/B'd further. The content improves on real audience
data, the same way a trading factor library improves on out-of-sample Sharpe.

## Running it

```bash
# one-off: draft a piece from a topic + context
python3 generate_draft.py ai-world "Some model dropped" --context "benchmark numbers, source links"
python3 generate_draft.py finance  "INFY Q4 results"    --context-file path/to/transcript.md

# the daily monitors (also run by the launchd agent)
bash monitor/run_monitors.sh

# the weekly learn pass
python3 learn.py
```

Model routing is via env vars (`ANTHROPIC_AUTH_TOKEN` + `ANTHROPIC_BASE_URL`); no credentials are
committed. Set them to point at whatever Anthropic-compatible endpoint you use, or leave them unset
to use the default Anthropic client.

## Design notes

- **Drafts-only by default.** The engine never publishes. It produces drafts for human review —
  the same safety property you'd want on any autonomous outbound system.
- **SEBI-aware.** Finance content is constrained to education, data, and language analysis. The
  generator prompt enforces "here's what the data signals," never "buy/sell/hold X."
- **Cheap-model-first.** Bulk generation routes to an inexpensive model; the frontier model is the
  fallback, not the default — content volume shouldn't burn premium quota.

---

Built as part of a broader autonomous-agent system. The interesting bit isn't the generation —
it's the closed loop: draft, measure, learn, repeat.
