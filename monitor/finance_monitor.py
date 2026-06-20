#!/usr/bin/env python3
"""
Finance news monitor — checks NSE earnings calendar + market events for content triggers.
IT services transcripts + macro events (RBI, SEBI, earnings season) → draft generation.
Run daily via launchd. SEBI: education/data/language-analysis only.
"""
import json, re, sys
from pathlib import Path
from datetime import date, datetime

import requests

MONITOR_DIR = Path(__file__).parent
ENGINE_DIR = MONITOR_DIR.parent
SEEN_FILE = MONITOR_DIR / "seen_finance.json"
sys.path.insert(0, str(ENGINE_DIR))

# IT services and key names to watch for transcript opportunities
WATCH_COMPANIES = [
    "infosys", "tcs", "wipro", "hcl", "tech mahindra", "ltimindtree",
    "accenture", "cognizant", "capgemini",
]

WATCH_EVENTS = [
    "rbi", "sebi", "repo rate", "monetary policy", "earnings season",
    "q1 fy", "q2 fy", "q3 fy", "q4 fy", "results", "ipo",
]

# NSE publicly available earnings calendar — no auth needed
NSE_CORPORATE_ACTIONS = "https://www.nseindia.com/api/event-calendar"


def load_seen() -> dict:
    if SEEN_FILE.exists():
        return json.loads(SEEN_FILE.read_text())
    return {"items": [], "last_run": None}


def save_seen(state: dict):
    SEEN_FILE.write_text(json.dumps(state, indent=2))


def fetch_nse_events() -> list[dict]:
    """Fetch upcoming earnings/board meetings from NSE."""
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Referer": "https://www.nseindia.com/",
    }
    try:
        resp = requests.get(NSE_CORPORATE_ACTIONS, headers=headers, timeout=10)
        data = resp.json()
        events = data if isinstance(data, list) else data.get("data", [])
        results = []
        for ev in events[:50]:
            symbol = str(ev.get("symbol", "")).lower()
            purpose = str(ev.get("purpose", "")).lower()
            company = str(ev.get("company", "")).lower()
            if any(w in symbol or w in company for w in WATCH_COMPANIES):
                results.append({
                    "source": "nse",
                    "id": f"nse-{ev.get('symbol','')}-{ev.get('date','')}",
                    "symbol": ev.get("symbol", ""),
                    "company": ev.get("company", ""),
                    "purpose": ev.get("purpose", ""),
                    "date": ev.get("date", ""),
                })
        return results
    except Exception as e:
        print(f"NSE fetch failed: {e}", file=sys.stderr)
        return []


def search_finance_news() -> list[dict]:
    """Simple HN search for finance/market news."""
    try:
        resp = requests.get(
            "https://hn.algolia.com/api/v1/search_by_date",
            params={"query": "earnings IT services India market", "tags": "story", "hitsPerPage": 20},
            timeout=10,
        )
        hits = resp.json().get("hits", [])
        results = []
        for h in hits:
            title = (h.get("title") or "").lower()
            score = h.get("points", 0)
            if score < 30:
                continue
            match = any(w in title for w in WATCH_COMPANIES + WATCH_EVENTS)
            if match:
                results.append({
                    "source": "hn_finance",
                    "id": h.get("objectID", title[:40]),
                    "title": h.get("title", ""),
                    "url": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                    "score": score,
                })
        return results[:5]
    except Exception as e:
        print(f"HN finance search failed: {e}", file=sys.stderr)
        return []


def build_context(item: dict) -> str:
    if item["source"] == "nse":
        return f"""Event: {item['company']} ({item['symbol']}) — {item['purpose']} on {item['date']}

This is an upcoming earnings event for an IT services company we track.
Write a preview piece: what language signals should we watch for in the transcript?
What did the last transcript signal about guidance? (reference SEBI-safe data/language analysis only)
What's the broader sector context (AI productivity deflation, deal ramp timing, macro)?"""
    else:
        return f"""Source: HN Finance news
Title: {item['title']}
URL: {item.get('url', '')}

Write about this market/sector development from a data and language-signal perspective.
SEBI: education/data/process only. No buy/sell/hold calls."""


def main():
    state = load_seen()
    seen_ids = set(state.get("items", []))

    candidates = fetch_nse_events() + search_finance_news()
    novel = [c for c in candidates if c["id"] not in seen_ids]

    if not novel:
        print("No new notable finance items found.")
        state["last_run"] = datetime.now().isoformat()
        save_seen(state)
        return

    print(f"Found {len(novel)} novel item(s):")
    for item in novel:
        label = item.get("title") or f"{item.get('company')} {item.get('purpose')}"
        print(f"  [{item['source']}] {label[:80]}")

    top = novel[0]
    context = build_context(top)
    label = top.get("title") or f"{top.get('company', '')} {top.get('purpose', '')}"
    topic = re.sub(r"[^a-zA-Z0-9 ]", " ", label)[:60].strip()

    from generate_draft import generate
    out = generate("finance", topic, context)
    print(f"Draft: {out}")

    state["items"] = list(seen_ids | {c["id"] for c in novel})
    state["last_run"] = datetime.now().isoformat()
    save_seen(state)


if __name__ == "__main__":
    main()
