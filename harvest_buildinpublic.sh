#!/bin/bash
# Weekly build-in-public harvester (Fridays). Mines the week's real artifacts (gtm digests,
# funding digests, git log) into ONE honest build-in-public draft for the approval queue.
# Approval-gated: draft lands as status: needs-review + linkedin_status: pending — Srijan
# ticks before post_x.py / post_linkedin.py will touch it. Srijan authorized lane 2026-07-12.
set -u
ENGINE="$(cd "$(dirname "$0")" && pwd)"
AKSH="$HOME/aksh_backtesting_trading"
WEEK=$(date +%F)
OUT="$ENGINE/drafts/$WEEK-finance-build-in-public.md"
[ -f "$OUT" ] && { echo "draft exists"; exit 0; }
MATERIAL=$(mktemp)
{ echo "## GTM digests this week"; tail -n 60 "$AKSH"/brain/gtm-autopilot/digest-*.md 2>/dev/null | tail -120
  echo "## Funding digests"; tail -n 40 "$AKSH"/brain/funding/DIGEST-*.md 2>/dev/null | tail -80
  echo "## Commits"; git -C "$AKSH" log --since="7 days ago" --oneline | head -30; } > "$MATERIAL"
codex exec --skip-git-repo-check -m gpt-5.6-luna -c model_reasoning_effort="high" \
  --sandbox workspace-write -C "$ENGINE" \
  "NON-INTERACTIVE BATCH JOB: no human is available to reply and stdin is closed. Do NOT use the brainstorming skill or any planning/design/approval skill, and do NOT ask for approval or confirmation. Just do the task and write the output file directly, then stop. Read $MATERIAL. Write ONE build-in-public X thread (5-8 tweets) about this week building AKSH (real-time BSE earnings-signal platform, solo founder). Rules: only REAL events/numbers from the material, self-deprecating honesty beats hype, no per-stock names/calls/ratings (SEBI), no em-dashes, each tweet <260 chars, end with what's next. Also a '## LINKEDIN' section: same story as one 150-word post. Write to $OUT with frontmatter: id, engine: finance, topic, status: needs-review, linkedin_status: pending, lane: build-in-public, generated: $WEEK" </dev/null
rm -f "$MATERIAL"
[ -f "$OUT" ] && echo "draft: $OUT" || { echo "HARVEST FAILED - no draft produced" >&2; exit 1; }
