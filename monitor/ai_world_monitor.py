#!/usr/bin/env python3
"""
AI-world news monitor — checks HN + arXiv for notable AI releases/benchmarks/models.
Drafts a content piece for anything new and notable.
Run daily via launchd.
"""
from __future__ import annotations  # PEP 604 union syntax on Python 3.7+
import json, os, sys, re, time
from pathlib import Path
from datetime import date, datetime, timedelta

import requests

MONITOR_DIR = Path(__file__).parent
ENGINE_DIR = MONITOR_DIR.parent
SEEN_FILE = MONITOR_DIR / "seen_ai.json"
sys.path.insert(0, str(ENGINE_DIR))

AI_KEYWORDS = {
    "high": ["claude", "gpt-5", "gemini", "llama", "qwen", "mistral", "grok", "deepseek",
             "benchmark", "swe-bench", "lmarena", "helm", "model release", "o3", "o4"],
    "med": ["arxiv", "transformer", "llm", "reasoning", "agent", "multimodal", "fine-tun"],
}
HN_API = "https://hacker-news.firebaseio.com/v0"
ARXIV_API = "https://export.arxiv.org/api/query"


def load_seen() -> dict:
    if SEEN_FILE.exists():
        return json.loads(SEEN_FILE.read_text())
    return {"items": [], "last_run": None}


def save_seen(state: dict):
    SEEN_FILE.write_text(json.dumps(state, indent=2))


def hn_top_ai(hours_back: int = 25) -> list[dict]:
    """Get HN stories from last `hours_back` hours that match AI keywords."""
    try:
        ids = requests.get(f"{HN_API}/newstories.json", timeout=10).json()[:300]
    except Exception as e:
        print(f"HN fetch failed: {e}", file=sys.stderr)
        return []

    cutoff = time.time() - hours_back * 3600
    results = []
    for item_id in ids[:100]:  # ponytail: cap at 100 to avoid rate limit
        try:
            item = requests.get(f"{HN_API}/item/{item_id}.json", timeout=5).json()
            if not item or item.get("time", 0) < cutoff:
                continue
            title = (item.get("title") or "").lower()
            url = item.get("url") or ""
            score = item.get("score", 0)
            if score < 50:  # filter low-signal
                continue
            match_score = 0
            for kw in AI_KEYWORDS["high"]:
                if kw in title or kw in url.lower():
                    match_score += 2
            for kw in AI_KEYWORDS["med"]:
                if kw in title:
                    match_score += 1
            if match_score >= 2:
                results.append({
                    "source": "hn",
                    "id": str(item_id),
                    "title": item.get("title", ""),
                    "url": url,
                    "score": score,
                    "match_score": match_score,
                })
        except Exception:
            continue
    results.sort(key=lambda x: (-x["match_score"], -x["score"]))
    return results[:5]


def arxiv_ai_recent(days_back: int = 2) -> list[dict]:
    """Get recent arXiv papers in cs.AI / cs.LG."""
    try:
        resp = requests.get(ARXIV_API, params={
            "search_query": "cat:cs.AI OR cat:cs.LG",
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": 20,
        }, timeout=15)
        # Simple XML parse — no lxml needed
        entries = re.findall(r"<entry>(.*?)</entry>", resp.text, re.DOTALL)
    except Exception as e:
        print(f"arXiv fetch failed: {e}", file=sys.stderr)
        return []

    results = []
    for entry in entries[:10]:
        title_m = re.search(r"<title>(.*?)</title>", entry, re.DOTALL)
        id_m = re.search(r"<id>(.*?)</id>", entry, re.DOTALL)
        summary_m = re.search(r"<summary>(.*?)</summary>", entry, re.DOTALL)
        if not title_m:
            continue
        title = re.sub(r"\s+", " ", title_m.group(1)).strip()
        match_score = sum(2 for kw in AI_KEYWORDS["high"] if kw in title.lower())
        match_score += sum(1 for kw in AI_KEYWORDS["med"] if kw in title.lower())
        if match_score >= 2:
            results.append({
                "source": "arxiv",
                "id": id_m.group(1).strip() if id_m else title,
                "title": title,
                "url": id_m.group(1).strip() if id_m else "",
                "summary": re.sub(r"\s+", " ", summary_m.group(1)).strip()[:500] if summary_m else "",
                "match_score": match_score,
            })
    return results[:3]


def main():
    state = load_seen()
    seen_ids = set(state.get("items", []))

    candidates = hn_top_ai() + arxiv_ai_recent()
    novel = [c for c in candidates if c["id"] not in seen_ids]

    if not novel:
        print("No new notable AI items found.")
        state["last_run"] = datetime.now().isoformat()
        save_seen(state)
        return

    print(f"Found {len(novel)} novel item(s):")
    for item in novel:
        print(f"  [{item['source']}] {item['title'][:80]}")

    # Generate a draft for the top item (highest match_score)
    top = sorted(novel, key=lambda x: -x["match_score"])[0]

    context = f"""Source: {top['source'].upper()}
Title: {top['title']}
URL: {top['url']}
{('Summary: ' + top['summary']) if top.get('summary') else ''}

Write about this AI development. Focus on what's actually true vs what the hype says.
Apply the eval-first lens: what would the standardized benchmark show vs the vendor claim?
What should readers test before trusting this?"""

    from generate_draft import generate
    topic = re.sub(r"[^a-zA-Z0-9 ]", " ", top["title"])[:60].strip()
    out = generate("ai-world", topic, context)
    print(f"Draft: {out}")

    # Mark all novel items as seen
    state["items"] = list(seen_ids | {c["id"] for c in novel})
    state["last_run"] = datetime.now().isoformat()
    save_seen(state)


if __name__ == "__main__":
    main()
