#!/usr/bin/env python3
"""Upload a rendered faceless short to YouTube via the Data API v3.

The pipeline renders + stages locally for free (see make_video.py); this is the one outward step.
First run per channel opens a browser for consent and caches a refresh token; after that it runs
silently (auto-refresh), so the autonomous factory loop can upload without re-auth.

  python3 video/upload_youtube.py video/out/<stem>.mp4 --channel ai --title "..." [--privacy unlisted]

Channels share nothing: each --channel key gets its own cached token (token-<key>.json), authorized
against the right brand account during consent. Default privacy is `unlisted` (safe); the loop sets
`public` only once it's in full-auto mode.

Setup (one time, Srijan): create an OAuth *Desktop app* client in Google Cloud Console with the
YouTube Data API v3 enabled, download it to .secrets/youtube/client_secret.json. .secrets/ is gitignored.

ponytail: stdlib argparse + the official google libs; no wrapper SDK, no extra abstraction. Resumable
upload because Shorts files cross the 5 MB simple-upload ceiling and renders can be flaky on mobile nets.
"""
import argparse
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
SECRETS = ENGINE / ".secrets" / "youtube"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
DISCLAIM = "Market data / AI commentary for education only. Not investment advice."

# YouTube API hard limits.
TITLE_MAX, DESC_MAX, TAGS_CHAR_MAX = 100, 5000, 480
# Sensible default category per channel key (28=Science & Tech, 27=Education).
CATEGORY = {"ai": "28", "finance": "27"}


def _truncate(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _clamp_tags(tags: list[str]) -> list[str]:
    """YouTube caps total tag characters (~500 incl. commas); drop tags once we'd exceed it."""
    out, used = [], 0
    for t in tags:
        t = t.strip().lstrip("#")
        if not t:
            continue
        cost = len(t) + (1 if out else 0)
        if used + cost > TAGS_CHAR_MAX:
            break
        out.append(t)
        used += cost
    return out


def build_body(title: str, description: str, tags: list[str], privacy: str, category: str) -> dict:
    """Pure: the request body the API expects. Tested without any network call."""
    if privacy not in ("public", "unlisted", "private"):
        raise ValueError(f"bad privacy: {privacy}")
    desc = _truncate(description, DESC_MAX)
    if DISCLAIM.lower() not in desc.lower():
        desc = _truncate(f"{desc}\n\n{DISCLAIM}", DESC_MAX)
    return {
        "snippet": {
            "title": _truncate(title, TITLE_MAX) or "Untitled",
            "description": desc,
            "tags": _clamp_tags(tags),
            "categoryId": category,
        },
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }


def _creds(channel: str):
    """Load/refresh/mint OAuth creds for one channel. Imports the google libs lazily so the pure
    helpers above stay importable (and testable) on a box without the deps installed."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    token = SECRETS / f"token-{channel}.json"
    client = SECRETS / "client_secret.json"
    creds = None
    if token.exists():
        creds = Credentials.from_authorized_user_file(str(token), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not client.exists():
            raise SystemExit(f"missing OAuth client at {client} — create a Desktop OAuth client "
                             "in Google Cloud Console (YouTube Data API v3) and download it there")
        creds = InstalledAppFlow.from_client_secrets_file(str(client), SCOPES).run_local_server(port=0)
    SECRETS.mkdir(parents=True, exist_ok=True)
    token.write_text(creds.to_json())
    return creds


def upload(video: Path, body: dict, channel: str) -> str:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    yt = build("youtube", "v3", credentials=_creds(channel))
    media = MediaFileUpload(str(video), chunksize=-1, resumable=True, mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            print(f"  upload {int(status.progress() * 100)}%")
    return f"https://youtu.be/{resp['id']}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Upload a rendered short to YouTube")
    ap.add_argument("video", type=Path)
    ap.add_argument("--channel", default="finance", help="channel key (own token + default category)")
    ap.add_argument("--title")
    ap.add_argument("--desc", help="description text; if omitted, reads <stem>.caption.txt")
    ap.add_argument("--tags", default="", help="comma-separated")
    ap.add_argument("--privacy", default="unlisted", choices=["public", "unlisted", "private"])
    ap.add_argument("--category", help="YouTube categoryId (default per channel)")
    ap.add_argument("--dry-run", action="store_true", help="build + print the request body, do not upload")
    a = ap.parse_args()

    if not a.video.exists():
        raise SystemExit(f"no such video: {a.video}")
    desc = a.desc
    if desc is None:
        cap = a.video.with_suffix("").with_suffix(".caption.txt")
        desc = cap.read_text() if cap.exists() else ""
    title = a.title or a.video.stem.replace("-", " ")
    tags = [t for t in a.tags.split(",") if t.strip()]
    category = a.category or CATEGORY.get(a.channel, "27")
    body = build_body(title, desc, tags, a.privacy, category)

    if a.dry_run:
        import json
        print(json.dumps({"channel": a.channel, "file": str(a.video), "body": body}, indent=2))
        return 0
    url = upload(a.video, body, a.channel)
    print(f"OK -> {url}  ({a.privacy}, channel={a.channel})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
