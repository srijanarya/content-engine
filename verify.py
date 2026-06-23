#!/usr/bin/env python3
"""verify.py — one command, plain-English PASS/FAIL for every safety guarantee on the X finance bot.

Reads only; never posts. Run:   python3 verify.py     (exits nonzero if any guarantee fails)

Answers "have you corrected it, and how do I verify?" WITHOUT trusting any log or anyone's word: each
check re-derives the answer from the live code + the live market, every time you run it. The guarantees:
  1. bot state (off/live)            4. won't flood (one lane's today draft only)
  2. won't post stale data           5. data matches the live market
  3. won't post a single company     6. the unit tests are green
"""
from __future__ import annotations
import json, subprocess, sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "monitor"))

results: list[tuple] = []  # (True|False|None, line)   None = informational
def ok(line):   results.append((True, line))
def bad(line):  results.append((False, line))
def info(line): results.append((None, line))

TODAY = datetime.now().date().isoformat()


# 1) Bot state ────────────────────────────────────────────────────────────────
if (HERE / "x" / "POSTING_DISABLED").exists():
    info("BOT IS OFF — nothing will post until you delete x/POSTING_DISABLED")
else:
    info("BOT IS LIVE — posting is armed")


# 2) Won't post stale data ──────────────────────────────────────────────────────
try:
    from daily_market_post import fresh_or_reason
    anchor = datetime(2026, 6, 23, 16, 0, 0)  # a fixed post-close "now" so the check is deterministic
    may12 = fresh_or_reason({"date": "2026-05-12", "generated_at": "2026-05-12T15:48:00"}, anchor)
    preopen = fresh_or_reason({"date": "2026-06-23", "generated_at": "2026-06-23T09:06:00"}, anchor)
    if may12 and preopen:
        ok("won't post stale data (refused 6-week-old May-12 data AND a 09:06 pre-open sample)")
    else:
        bad(f"freshness gate let something through: May-12={may12!r}  pre-open={preopen!r}")
except Exception as e:  # noqa: BLE001
    bad(f"freshness gate check errored: {e}")


# 3) Won't post about a single company ──────────────────────────────────────────
try:
    from post_x import names_company, frontmatter
    flagged = names_company("Tata Consultancy Services Limited Financial Results", "x.md")
    leaks = []
    for f in sorted((HERE / "drafts").glob("*.md")):
        fm = frontmatter(f.read_text())
        if fm.get("engine") != "finance":
            continue
        company = names_company(fm.get("topic", ""), f.name)
        postable_status = fm.get("status") in ("needs-review", "approved")
        if company and postable_status and fm.get("generated") == TODAY:
            leaks.append(f"{f.name} (about {company})")
    if flagged and not leaks:
        ok("won't post about a single company (TCS title refused; 0 per-company drafts sit postable today)")
    elif not flagged:
        bad("per-company guard FAILED to flag a 'Tata Consultancy Services' title")
    else:
        bad("per-company draft(s) postable TODAY: " + "; ".join(leaks))
except Exception as e:  # noqa: BLE001
    bad(f"per-company guard check errored: {e}")


# 4) Won't flood — one lane posts at most its single today draft ────────────────
try:
    from post_x import eligible, frontmatter
    picked = []
    for f in sorted((HERE / "drafts").glob("*.md")):
        fm = frontmatter(f.read_text())
        if eligible(f.name, fm, lane_slug="premarket-note", today=TODAY, auto_approve=True):
            picked.append(f.name)
    wrong_lane = [n for n in picked if "premarket-note" not in n]
    if len(picked) <= 1 and not wrong_lane:
        shown = picked[0] if picked else "none today (already posted or none generated)"
        ok(f"won't flood (premarket lane would post {len(picked)}: {shown})")
    else:
        bad(f"FLOOD RISK: premarket lane would queue {len(picked)} drafts: {picked}")
except Exception as e:  # noqa: BLE001
    bad(f"flood check errored: {e}")


# 5) Data matches the live market ───────────────────────────────────────────────
try:
    import public_market_refresh as pmr
    rf = HERE / "monitor" / "regime_safe.json"
    if not rf.exists():
        info("no regime_safe.json yet — run monitor/public_market_refresh.py (nothing to post anyway)")
    else:
        safe = json.loads(rf.read_text())
        if safe.get("date") != TODAY:
            bad(f"data is NOT today's — regime_safe.json is dated {safe.get('date')} (today is {TODAY})")
        else:
            _, live_nifty = pmr._meta_change("%5ENSEI")
            file_nifty = safe.get("nifty_change_pct")
            parts = [f"Nifty file {file_nifty}% vs live {live_nifty}%"]
            worst = abs((live_nifty or 0) - (file_nifty or 0))
            for sec in ("IT", "BANK"):
                try:
                    _, lp = pmr._meta_change(pmr.SECTORS[sec])
                    fp = safe.get("sector_rotation", {}).get("all_sectors_pct", {}).get(sec)
                    if fp is not None and lp is not None:
                        parts.append(f"{sec} file {fp}% vs live {lp}%")
                        worst = max(worst, abs(lp - fp))
                except Exception:  # noqa: BLE001 - one sector failing isn't fatal to the check
                    pass
            # ponytail: 1.5% tolerance absorbs intraday drift between snapshot and now; a stale file
            # (the May-12 bug) diverges far past this. Tighten if posts run only post-close.
            if worst <= 1.5:
                ok("data matches the live market (" + "; ".join(parts) + ")")
            else:
                bad("data DIVERGES from the live market (" + "; ".join(parts) + ")")
except Exception as e:  # noqa: BLE001
    bad(f"reality check errored: {e}")


# 6) The unit tests are green ────────────────────────────────────────────────────
for label, rel in [("freshness", "monitor/test_daily_wrap_freshness.py"),
                   ("flood+per-company", "test_post_guards.py"),
                   ("video", "video/test_make_video.py")]:
    p = HERE / rel
    if not p.exists():
        bad(f"tests {label}: file missing ({rel})"); continue
    try:
        r = subprocess.run([sys.executable, str(p)], capture_output=True, text=True,
                           cwd=str(HERE), timeout=120)
        last = (r.stdout.strip().splitlines() or [""])[-1].strip()
        (ok if r.returncode == 0 else bad)(f"tests {label}: {last or 'no output'}")
    except Exception as e:  # noqa: BLE001
        bad(f"tests {label}: runner errored: {e}")


# ── report ──
print()
fails = 0
for status, line in results:
    if status is None:
        print(line)
    elif status:
        print(f"PASS  {line}")
    else:
        fails += 1
        print(f"FAIL  {line}")
print()
print("ALL GUARANTEES HOLD." if fails == 0 else f"{fails} GUARANTEE(S) FAILING — fix before re-arming.")
sys.exit(1 if fails else 0)
