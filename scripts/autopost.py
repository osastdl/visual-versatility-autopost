#!/usr/bin/env python3
"""
Publishes scheduled posts to Instagram and Facebook via the Meta Graph API.

Reads content/calendar.json for posts scheduled at or before "now" that
haven't been posted yet, publishes each to Instagram and/or Facebook,
then marks them posted by rewriting the file back to the repo.

Required environment variables (set as GitHub repo secrets):
  IG_ACCESS_TOKEN   - long-lived Instagram access token
  IG_USER_ID        - Instagram Business Account ID
  FB_PAGE_ID        - Facebook Page ID
  FB_PAGE_TOKEN     - Page access token (can be same long-lived token)
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

GRAPH_API = "https://graph.facebook.com/v21.0"
CALENDAR_PATH = os.path.join(os.path.dirname(__file__), "..", "content", "calendar.json")

IG_ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN")
IG_USER_ID = os.environ.get("IG_USER_ID")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN")


def load_calendar():
    with open(CALENDAR_PATH) as f:
        return json.load(f)


def save_calendar(posts):
    with open(CALENDAR_PATH, "w") as f:
        json.dump(posts, f, indent=2)


def due_posts(posts):
    now = datetime.now(timezone.utc)
    due = []
    for post in posts:
        if post.get("posted"):
            continue
        scheduled = datetime.fromisoformat(post["scheduled_at"].replace("Z", "+00:00"))
        if scheduled <= now:
            due.append(post)
    return due


def publish_instagram(post):
    images = post["images"]
    caption = post["caption"]

    if len(images) == 1:
        container = requests.post(
            f"{GRAPH_API}/{IG_USER_ID}/media",
            data={
                "image_url": images[0],
                "caption": caption,
                "access_token": IG_ACCESS_TOKEN,
            },
        ).json()
        if "id" not in container:
            raise RuntimeError(f"IG container failed: {container}")
        creation_id = container["id"]
    else:
        child_ids = []
        for url in images:
            child = requests.post(
                f"{GRAPH_API}/{IG_USER_ID}/media",
                data={
                    "image_url": url,
                    "is_carousel_item": "true",
                    "access_token": IG_ACCESS_TOKEN,
                },
            ).json()
            if "id" not in child:
                raise RuntimeError(f"IG carousel child failed: {child}")
            child_ids.append(child["id"])
            time.sleep(1)

        container = requests.post(
            f"{GRAPH_API}/{IG_USER_ID}/media",
            data={
                "media_type": "CAROUSEL",
                "children": ",".join(child_ids),
                "caption": caption,
                "access_token": IG_ACCESS_TOKEN,
            },
        ).json()
        if "id" not in container:
            raise RuntimeError(f"IG carousel container failed: {container}")
        creation_id = container["id"]

    time.sleep(2)

    publish = requests.post(
        f"{GRAPH_API}/{IG_USER_ID}/media_publish",
        data={"creation_id": creation_id, "access_token": IG_ACCESS_TOKEN},
    ).json()
    if "id" not in publish:
        raise RuntimeError(f"IG publish failed: {publish}")
    return publish["id"]


def publish_facebook(post):
    images = post["images"]
    caption = post["caption"]

    if len(images) == 1:
        resp = requests.post(
            f"{GRAPH_API}/{FB_PAGE_ID}/photos",
            data={
                "url": images[0],
                "caption": caption,
                "access_token": FB_PAGE_TOKEN,
            },
        ).json()
        if "id" not in resp and "post_id" not in resp:
            raise RuntimeError(f"FB post failed: {resp}")
        return resp.get("post_id", resp.get("id"))

    photo_ids = []
    for url in images:
        resp = requests.post(
            f"{GRAPH_API}/{FB_PAGE_ID}/photos",
            data={
                "url": url,
                "published": "false",
                "access_token": FB_PAGE_TOKEN,
            },
        ).json()
        if "id" not in resp:
            raise RuntimeError(f"FB unpublished photo failed: {resp}")
        photo_ids.append(resp["id"])
        time.sleep(1)

    attached = [{"media_fbid": pid} for pid in photo_ids]
    resp = requests.post(
        f"{GRAPH_API}/{FB_PAGE_ID}/feed",
        data={
            "message": caption,
            "attached_media": json.dumps(attached),
            "access_token": FB_PAGE_TOKEN,
        },
    ).json()
    if "id" not in resp:
        raise RuntimeError(f"FB multi-photo post failed: {resp}")
    return resp["id"]


def main():
    posts = load_calendar()
    pending = due_posts(posts)

    if not pending:
        print("No posts due right now.")
        return

    for post in pending:
        label = post.get("id", post["scheduled_at"])
        targets = post.get("platforms", ["instagram", "facebook"])
        errors = []

        if "instagram" in targets:
            try:
                ig_id = publish_instagram(post)
                print(f"[{label}] Instagram published: {ig_id}")
            except Exception as e:
                errors.append(f"instagram: {e}")
                print(f"[{label}] Instagram FAILED: {e}", file=sys.stderr)

        if "facebook" in targets:
            try:
                fb_id = publish_facebook(post)
                print(f"[{label}] Facebook published: {fb_id}")
            except Exception as e:
                errors.append(f"facebook: {e}")
                print(f"[{label}] Facebook FAILED: {e}", file=sys.stderr)

        if not errors:
            post["posted"] = True
            post["posted_at"] = datetime.now(timezone.utc).isoformat()
        else:
            post["last_error"] = "; ".join(errors)

    save_calendar(posts)


if __name__ == "__main__":
    missing = [
        name
        for name, val in [
            ("IG_ACCESS_TOKEN", IG_ACCESS_TOKEN),
            ("IG_USER_ID", IG_USER_ID),
            ("FB_PAGE_ID", FB_PAGE_ID),
            ("FB_PAGE_TOKEN", FB_PAGE_TOKEN),
        ]
        if not val
    ]
    if missing:
        print(f"Missing required environment variables: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    main()
