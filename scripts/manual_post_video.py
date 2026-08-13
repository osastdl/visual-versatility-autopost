#!/usr/bin/env python3
"""
One-off manual video post to Instagram (Reels) and Facebook, triggered via
the "Manual video post" GitHub Actions workflow (workflow_dispatch inputs:
video_url, caption). Unlike autopost.py (calendar-driven, images), this is
for ad-hoc video posts -- e.g. a freshly generated brand video that isn't
part of the regular content calendar.

Runs synchronously end-to-end: creates the Instagram Reels container, polls
until Meta finishes processing (can take a few minutes), then publishes --
Actions jobs have plenty of runtime budget for that, unlike the outreach_app
web request which hands this off to finish_pending_videos.py instead.

Required environment variables (same GitHub repo secrets as autopost.py):
  IG_ACCESS_TOKEN, IG_USER_ID, FB_PAGE_ID, FB_PAGE_TOKEN
Required inputs (env vars set by the workflow from workflow_dispatch inputs):
  VIDEO_URL, CAPTION
"""

import json
import os
import sys
import time

import requests

GRAPH_API = "https://graph.facebook.com/v21.0"
POSTED_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "content", "posted_log.json")

IG_ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN")
IG_USER_ID = os.environ.get("IG_USER_ID")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN")
VIDEO_URL = os.environ.get("VIDEO_URL")
CAPTION = os.environ.get("CAPTION")


def log_post(instagram_id, facebook_id):
    entries = []
    if os.path.exists(POSTED_LOG_PATH):
        with open(POSTED_LOG_PATH) as f:
            entries = json.load(f)
    entries.append({
        "type": "video",
        "thumbnail_url": VIDEO_URL,
        "caption": CAPTION,
        "instagram_id": instagram_id,
        "facebook_id": facebook_id,
        "instagram_pending_creation_id": None,
        "posted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "manual_video",
    })
    with open(POSTED_LOG_PATH, "w") as f:
        json.dump(entries, f, indent=2)


def publish_facebook_video(video_url, caption):
    resp = requests.post(
        f"{GRAPH_API}/{FB_PAGE_ID}/videos",
        data={"file_url": video_url, "description": caption, "access_token": FB_PAGE_TOKEN},
    ).json()
    if "id" not in resp:
        raise RuntimeError(f"Facebook video post failed: {resp}")
    return resp["id"]


def publish_instagram_reel(video_url, caption):
    container = requests.post(
        f"{GRAPH_API}/{IG_USER_ID}/media",
        data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "access_token": IG_ACCESS_TOKEN,
        },
    ).json()
    if "id" not in container:
        raise RuntimeError(f"Instagram Reels container failed: {container}")
    creation_id = container["id"]

    print(f"  IG container created ({creation_id}), waiting for processing...")
    for attempt in range(60):  # up to ~10 min at 10s intervals
        time.sleep(10)
        status = requests.get(
            f"{GRAPH_API}/{creation_id}",
            params={"fields": "status_code", "access_token": IG_ACCESS_TOKEN},
        ).json()
        code = status.get("status_code")
        print(f"  [{attempt + 1}/60] status: {code}")
        if code == "FINISHED":
            break
        if code == "ERROR":
            raise RuntimeError(f"Instagram processing failed: {status}")
    else:
        raise RuntimeError("Instagram processing timed out after 10 minutes")

    publish = requests.post(
        f"{GRAPH_API}/{IG_USER_ID}/media_publish",
        data={"creation_id": creation_id, "access_token": IG_ACCESS_TOKEN},
    ).json()
    if "id" not in publish:
        raise RuntimeError(f"Instagram publish failed: {publish}")
    return publish["id"]


def main():
    print(f"Posting video: {VIDEO_URL}")
    print(f"Caption: {CAPTION}\n")

    errors = []
    fb_id = None
    ig_id = None

    try:
        fb_id = publish_facebook_video(VIDEO_URL, CAPTION)
        print(f"Facebook published: {fb_id}")
    except Exception as e:
        errors.append(f"facebook: {e}")
        print(f"Facebook FAILED: {e}", file=sys.stderr)

    try:
        ig_id = publish_instagram_reel(VIDEO_URL, CAPTION)
        print(f"Instagram published: {ig_id}")
    except Exception as e:
        errors.append(f"instagram: {e}")
        print(f"Instagram FAILED: {e}", file=sys.stderr)

    if fb_id or ig_id:
        log_post(ig_id, fb_id)

    if errors:
        print("\nOne or more platforms failed: " + "; ".join(errors), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    missing = [
        name
        for name, val in [
            ("IG_ACCESS_TOKEN", IG_ACCESS_TOKEN),
            ("IG_USER_ID", IG_USER_ID),
            ("FB_PAGE_ID", FB_PAGE_ID),
            ("FB_PAGE_TOKEN", FB_PAGE_TOKEN),
            ("VIDEO_URL", VIDEO_URL),
            ("CAPTION", CAPTION),
        ]
        if not val
    ]
    if missing:
        print(f"Missing required environment variables: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    main()
