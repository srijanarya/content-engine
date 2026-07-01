# content-engine — operations

Self-learning content pipeline: `monitor → draft (voice-calibrated) → [human publishes] →
measure → learn`. Architecture and rationale: `README.md`. Style guide: `voice.md`.

## Run (verified 2026-07-02)
- Draft a piece: `python3 generate_draft.py ai-world "<topic>" --context "<notes>"` or
  `python3 generate_draft.py finance "<topic>" --context-file <transcript.md>`.
- Daily monitors (launchd `com.srijan.content-engine`, 08:30): `bash monitor/run_monitors.sh`.
- Weekly learn pass (launchd `com.srijan.weekly-loop-tuner`, Sun 09:00): `python3 learn.py`.
- X lane: `python3 post_x.py --dry-run` first; a real run posts the single draft whose
  frontmatter is `status: approved`. Kill switch: the `x/POSTING_DISABLED` file — present
  means no auto-posting. Safety self-check: `python3 verify.py`.
- Tests: `python3 -m unittest discover` (stdlib unittest; each `test_*.py` also runs directly).

## Hard rules
- **This repo is PUBLIC; the strategy layer is private.** `STRATEGY.md`, `growth/`,
  `post-queue/`, `content_performance.json`, `x/`, `reply-pipeline/` etc. are gitignored —
  one blanket `git add` would publish them. Stage named paths only.
- **SEBI safety:** finance content is education/data/language-analysis only — never buy/sell
  calls. The `compliance/` gates (scrub, lint, value_check) must pass before anything ships.
- Posting to X/YouTube is an outward comm — Srijan reviews before anything is published.
- Env: `.env.template` documents model-routing vars; live secrets live in
  `monitor/.env.local` and `.secrets/` (both gitignored).
