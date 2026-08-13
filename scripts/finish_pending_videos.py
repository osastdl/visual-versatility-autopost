#!/usr/bin/env python3
"""
Finishes Instagram Reels publishes that poster.py (in the VV Outreach
Telegram bot) started but couldn't wait around for.

Instagram needs to finish processing an uploaded video before it can be
published -- that can take minutes, too long for a single web request on
shared hosting. So the quick-post flow only creates the video container
and records it in content/pending_videos.json; this script (run on a
schedule) polls each pending container's status and publishes it the
moment it's ready, then tells the user on Telegram it's live.

Required environment variables (GitHub repo secrets):
  IG_ACCESS_TOKEN   - same long-lived Instagram access token as autopost.py
  IG_USER_ID        - Instagram Business Account ID
  TELEGRAM_BOT_TOKEN - the VV Outreach bot's token, to notify the user
"""

import json
import os
import sys

import requests

GRAPH_API = "https://graph.facebook.com/v21.0"
PENDING_PATH = os.path.join(os.path.dirname(__file__), "..", "content", "pending_videos.json")
POSTED_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "content", "posted_log.json")

IG_ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN")
IG_USER_ID = os.environ.get("IG_USER_ID")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")


def load_pending():
    with open(PENDING_PATH) as f:
        return json.load(f)


def save_pending(items):
    with open(PENDING_PATH, "w") as f:
        json.dump(items, f, indent=2)


def resolve_posted_log(creation_id, media_id):
    """Fills in the real Instagram media ID on the posted_log.json entry
    that poster.py created (with instagram_id still null) when it first
    started this video's processing -- so the console/Telegram history view
    picks up a working post link and can fetch engagement for it."""
    if not os.path.exists(POSTED_LOG_PATH):
        return
    with open(POSTED_LOG_PATH) as f:
        entries = json.load(f)
    changed = False
    for entry in entries:
        if entry.get("instagram_pending_creation_id") == creation_id:
            entry["instagram_id"] = media_id
            entry["instagram_pending_creation_id"] = None
            changed = True
    if changed:
        with open(POSTED_LOG_PATH, "w") as f:
            json.dump(entries, f, indent=2)


def check_status(creation_id):
    resp = requests.get(
        f"{GRAPH_API}/{creation_id}",
        params={"fields": "status_code", "access_token": IG_ACCESS_TOKEN},
    ).json()
    return resp.get("status_code")


def publish(creation_id):
    resp = requests.post(
        f"{GRAPH_API}/{IG_USER_ID}/media_publish",
        data={"creation_id": creation_id, "access_token": IG_ACCESS_TOKEN},
    ).json()
    if "id" not in resp:
        raise RuntimeError(f"publish failed: {resp}")
    return resp["id"]


def notify(chat_id, text):
    if not TELEGRAM_BOT_TOKEN:
        return
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": text},
    )


def main():
    pending = load_pending()
    if not pending:
        print("No pending videos.")
        return

    still_pending = []
    for item in pending:
        creation_id = item["creation_id"]
        try:
            status = check_status(creation_id)
        except Exception as e:
            print(f"[{creation_id}] status check FAILED: {e}", file=sys.stderr)
            still_pending.append(item)
            continue

        if status == "FINISHED":
            try:
                media_id = publish(creation_id)
                print(f"[{creation_id}] published: {media_id}")
                resolve_posted_log(creation_id, media_id)
                notify(item["chat_id"], f"📸 Your Instagram video is live!\n\n{item.get('caption', '')}")
            except Exception as e:
                print(f"[{creation_id}] publish FAILED: {e}", file=sys.stderr)
                notify(item["chat_id"], f"❌ Instagram video failed to publish: {e}")
                # Don't requeue -- Meta already finished processing, retrying
                # publish on the same creation_id won't fix a real error.
        elif status == "ERROR":
            print(f"[{creation_id}] Meta reported a processing ERROR, dropping it.", file=sys.stderr)
            notify(item["chat_id"], "❌ Instagram couldn't process that video (processing error on their end). Facebook is still live.")
        else:
            # IN_PROGRESS or unknown -- keep waiting.
            still_pending.append(item)

    save_pending(still_pending)
    print(f"Done. {len(pending) - len(still_pending)} resolved, {len(still_pending)} still pending.")


if __name__ == "__main__":
    missing = [name for name, val in [("IG_ACCESS_TOKEN", IG_ACCESS_TOKEN), ("IG_USER_ID", IG_USER_ID)] if not val]
    if missing:
        print(f"Missing required environment variables: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)
    main()
