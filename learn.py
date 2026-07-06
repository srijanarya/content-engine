#!/usr/bin/env python3
"""
Weekly learn pass — reads content_performance.json and outputs biases for next cycle.
Run weekly. Output appended to monitor/LEARNINGS.md.
"""
import json
from pathlib import Path
from datetime import date
from collections import defaultdict

ENGINE_DIR = Path(__file__).parent
PERF_FILE = ENGINE_DIR / "content_performance.json"
LEARNINGS_FILE = ENGINE_DIR / "monitor" / "LEARNINGS.md"


def main():
    data = json.loads(PERF_FILE.read_text())
    pieces = [p for p in data.get("pieces", []) if p.get("published_date")]

    if not pieces:
        print("No published pieces yet — nothing to learn from.")
        return

    # Group by dimensions
    by_hook = defaultdict(list)
    by_topic = defaultdict(list)
    by_engine = defaultdict(list)

    for p in pieces:
        m = p.get("metrics", {})
        x_eng = m.get("x_engagement_rate")
        li_eng = (m.get("linkedin_reactions", 0) or 0) + (m.get("linkedin_comments", 0) or 0)
        nl_open = m.get("newsletter_open_rate")

        for dim, key in [(by_hook, p.get("hook_style")), (by_topic, p.get("topic")), (by_engine, p.get("engine"))]:
            if key:
                if x_eng is not None:
                    dim[key].append(("x_eng", x_eng))
                if nl_open is not None:
                    dim[key].append(("nl_open", nl_open))

    lines = [
        f"# Content Engine LEARNINGS — {date.today().isoformat()}",
        f"\nBased on {len(pieces)} published piece(s).\n",
        "## Top-performing hooks",
    ]

    hook_avgs = {}
    for hook, vals in by_hook.items():
        x_vals = [v for k, v in vals if k == "x_eng"]
        if x_vals:
            hook_avgs[hook] = sum(x_vals) / len(x_vals)
    for hook, avg in sorted(hook_avgs.items(), key=lambda x: -x[1])[:5]:
        lines.append(f"- `{hook}`: avg X engagement {avg:.2%}")

    lines.append("\n## Top-performing topics")
    topic_counts = defaultdict(int)
    for p in pieces:
        topic_counts[p.get("topic")] += 1
    for topic, count in sorted(topic_counts.items(), key=lambda x: -x[1])[:5]:
        lines.append(f"- `{topic}`: {count} piece(s)")

    lines.append("\n## Engine breakdown")
    for engine, vals in by_engine.items():
        x_vals = [v for k, v in vals if k == "x_eng"]
        avg_x = f"{sum(x_vals)/len(x_vals):.2%}" if x_vals else "no data"
        lines.append(f"- `{engine}`: {avg_x} avg X engagement ({len(x_vals)} data points)")

    lines.append("\n## Biases for next cycle")
    lines.append("_(generated — review before applying)_")
    if hook_avgs:
        best_hook = max(hook_avgs, key=hook_avgs.get)
        lines.append(f"- Prefer hook style: `{best_hook}` (highest X engagement)")
    lines.append("- Continue publishing both engines; weight toward whichever audience converts\n")

    # Plain-text top biases for generate_draft.py to read (the signal, not the markdown report).
    # Include engines too: auto-ingested threads/replies have no hook_style, so engine is often the
    # only dimension with data — without it learnings_top.txt would stay empty.
    eng_avgs = {}
    for engine, vals in by_engine.items():
        xv = [v for k, v in vals if k == "x_eng"]
        if xv:
            eng_avgs[engine] = sum(xv) / len(xv)
    top = [f"hook '{h}' -> {a:.1%} avg X engagement"
           for h, a in sorted(hook_avgs.items(), key=lambda x: -x[1])[:2]]
    top += [f"engine '{e}' -> {a:.1%} avg X engagement"
            for e, a in sorted(eng_avgs.items(), key=lambda x: -x[1])[:2]]

    out = "\n".join(lines)
    LEARNINGS_FILE.parent.mkdir(exist_ok=True)
    if top:
        (ENGINE_DIR / "monitor" / "learnings_top.txt").write_text("\n".join(top) + "\n")

    # Append to learnings file (keep history)
    with open(LEARNINGS_FILE, "a") as f:
        f.write("\n---\n" + out + "\n")

    print(out)
    print(f"\nAppended to {LEARNINGS_FILE}")


if __name__ == "__main__":
    main()
