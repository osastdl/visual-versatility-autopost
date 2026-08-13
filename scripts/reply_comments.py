#!/usr/bin/env python3
"""
Auto-replies to comments on Visual Versatility's OWN recent Instagram posts.

Scope, deliberately: this only ever replies under the business's own media.
It never comments on other accounts' posts -- that's automated engagement
behavior Instagram's Platform Policy prohibits and can get an account
restricted or banned, and it's explicitly not what this was built for.

Reads the last N media items, checks their comments, and replies to any
comment not already recorded in content/replied_comments.json. A few
templates are rotated so replies don't look identical/robotic, and a
couple of common keywords (price/cost, info) get a slightly more specific
nudge toward DMs.

Required environment variables (same as autopost.py):
  IG_ACCESS_TOKEN  - long-lived Instagram access token
  IG_USER_ID       - Instagram Business Account ID
"""

import json
import os
import random
import sys
import time

import requests

GRAPH_API = "https://graph.facebook.com/v21.0"
REPLIED_PATH = os.path.join(os.path.dirname(__file__), "..", "content", "replied_comments.json")
RECENT_MEDIA_COUNT = 10

IG_ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN")
IG_USER_ID = os.environ.get("IG_USER_ID")

GENERIC_REPLIES = [
    "Thank you so much for the love! 🙌",
    "We really appreciate you taking the time to comment! 💜",
    "Thanks for stopping by — means a lot to us! ✨",
    "Appreciate you! Let us know if you have any questions 🙂",
]

PRICING_KEYWORDS = ["price", "cost", "quote", "how much", "pricing"]
PRICING_REPLY = "Great question! Pricing depends on the project — send us a DM and we'll get you a quote 💬"

INFO_KEYWORDS = ["info", "details", "more info", "tell me more"]
INFO_REPLY = "We'd love to share more! Drop us a DM and we'll walk you through it 📩"


def load_replied():
    if not os.path.exists(REPLIED_PATH):
        return []
    with open(REPLIED_PATH) as f:
        return json.load(f)


def save_replied(ids):
    with open(REPLIED_PATH, "w") as f:
        json.dump(ids, f, indent=2)


def pick_reply(comment_text):
    text = (comment_text or "").lower()
    if any(k in text for k in PRICING_KEYWORDS):
        return PRICING_REPLY
    if any(k in text for k in INFO_KEYWORDS):
        return INFO_REPLY
    return random.choice(GENERIC_REPLIES)


def get_recent_media():
    resp = requests.get(
        f"{GRAPH_API}/{IG_USER_ID}/media",
        params={"fields": "id,caption", "limit": RECENT_MEDIA_COUNT, "access_token": IG_ACCESS_TOKEN},
    ).json()
    return resp.get("data", [])


def get_comments(media_id):
    resp = requests.get(
        f"{GRAPH_API}/{media_id}/comments",
        params={"fields": "id,text,username", "access_token": IG_ACCESS_TOKEN},
    ).json()
    return resp.get("data", [])


def reply_to_comment(comment_id, message):
    resp = requests.post(
        f"{GRAPH_API}/{comment_id}/replies",
        data={"message": message, "access_token": IG_ACCESS_TOKEN},
    ).json()
    if "id" not in resp:
        raise RuntimeError(f"reply failed: {resp}")
    return resp["id"]


def main():
    replied_ids = set(load_replied())
    media_items = get_recent_media()

    new_replies = 0
    for media in media_items:
        try:
            comments = get_comments(media["id"])
        except Exception as e:
            print(f"[media {media['id']}] failed to fetch comments: {e}", file=sys.stderr)
            continue

        for comment in comments:
            comment_id = comment["id"]
            if comment_id in replied_ids:
                continue

            reply_text = pick_reply(comment.get("text"))
            try:
                reply_to_comment(comment_id, reply_text)
                print(f"[media {media['id']}] replied to comment {comment_id} from @{comment.get('username', '?')}")
                replied_ids.add(comment_id)
                new_replies += 1
                time.sleep(1)
            except Exception as e:
                print(f"[media {media['id']}] FAILED to reply to comment {comment_id}: {e}", file=sys.stderr)

    save_replied(sorted(replied_ids))
    print(f"Done. {new_replies} new reply/replies posted.")


if __name__ == "__main__":
    missing = [name for name, val in [("IG_ACCESS_TOKEN", IG_ACCESS_TOKEN), ("IG_USER_ID", IG_USER_ID)] if not val]
    if missing:
        print(f"Missing required environment variables: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    main()
